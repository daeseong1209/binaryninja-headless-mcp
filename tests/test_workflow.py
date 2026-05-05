"""End-to-end workflow integration tests.

These tests exercise realistic multi-step usage patterns against the mock
backend.  They run in standard CI (no @pytest.mark.perf decoration) and must
pass on every push.

Scenarios
---------
A — Analysis workflow (open → inspect → close)
B — Transaction + undo round-trip
C — Multi-binary isolation
D — Error recovery (invalid ops do not kill the session)
E — Path-traversal defence (BINJA_MCP_ALLOWED_ROOTS)
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from binja_mcp.errors import UNDO_STATE_INVALID, BinjaError
from binja_mcp.tools import decompile as t_decompile
from binja_mcp.tools import functions as t_functions
from binja_mcp.tools import lifecycle as t_lifecycle
from binja_mcp.tools import strings as t_strings
from binja_mcp.tools import symbols as t_symbols
from binja_mcp.tools import types as t_types
from binja_mcp.tools import undo as t_undo
from binja_mcp.tools import xrefs as t_xrefs

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _ctx(supervisor) -> SimpleNamespace:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=supervisor)
        )
    )


# ---------------------------------------------------------------------------
# Scenario A — Full analysis workflow
# ---------------------------------------------------------------------------


def test_scenario_a_analysis_workflow(supervisor, fixture_binary):
    """Open a binary, inspect it through several tools, then close.

    Verifies that each tool in a typical analysis pipeline returns the expected
    response shape and that identity assertions hold across calls.
    """
    ctx = _ctx(supervisor)

    # 1. open
    open_res = t_lifecycle.open_binary(str(fixture_binary), ctx)
    assert "binary_id" in open_res
    assert open_res["path"] == str(fixture_binary)
    assert open_res["is_mock"] is True
    bid = open_res["binary_id"]

    # 2. list_functions (limit=3)
    funcs_res = t_functions.list_functions(bid, ctx, limit=3)
    assert "items" in funcs_res
    assert "total" in funcs_res
    assert len(funcs_res["items"]) <= 3
    first_func = funcs_res["items"][0]
    assert "name" in first_func
    assert first_func["start"].startswith("0x")

    # 3. decompile first function
    decompile_res = t_decompile.decompile(bid, first_func["name"], ctx)
    assert "text" in decompile_res
    assert "truncated" in decompile_res
    assert decompile_res["function"]["name"] == first_func["name"]

    # 4. search_strings
    strings_res = t_strings.search_strings(bid, ctx, pattern="error")
    assert "items" in strings_res
    assert any("error" in it["value"] for it in strings_res["items"])

    # 5. get_xrefs_to first function address
    xrefs_res = t_xrefs.get_xrefs_to(bid, first_func["start"], ctx)
    assert "items" in xrefs_res
    assert "target_address" in xrefs_res
    assert xrefs_res["target_address"] == first_func["start"]

    # 6. close
    close_res = t_lifecycle.close_binary(bid, ctx)
    assert close_res["closed"] == bid

    listing = t_lifecycle.list_binaries(ctx)
    assert listing["total"] == 0


# ---------------------------------------------------------------------------
# Scenario B — Transaction + undo round-trip
# ---------------------------------------------------------------------------


def test_scenario_b_transaction_undo_roundtrip(supervisor, fixture_binary):
    """begin_undo / commit_undo + serial undo() round-trip.

    Each tool call (rename_symbol, define_type) internally wraps its write in
    its own undo_transaction, so each lands as a separate entry on the undo
    stack.  This test verifies the full round-trip:

      - open → rename F1 ("X") → define_type("Foo")
      - verify X in list_symbols, Foo in get_type
      - undo() → Foo reverted
      - undo() → X reverted
      - verify X absent in list_symbols; Foo definition=None
    """
    ctx = _ctx(supervisor)
    bid = t_lifecycle.open_binary(str(fixture_binary), ctx)["binary_id"]

    # Collect the first function
    funcs = t_functions.list_functions(bid, ctx, limit=10)["items"]
    f1 = funcs[0]
    f1_addr = f1["start"]
    f1_original = f1["name"]

    # Rename F1 → "X"
    r1 = t_symbols.rename_symbol(bid, f1_addr, "X", ctx)
    assert r1["after"] == "X"
    assert r1["before"] == f1_original

    # Define a type "Foo"
    define_res = t_types.define_type(bid, "Foo", "typedef struct {int a; int b;} Foo;", ctx)
    assert define_res["name"] == "Foo"
    assert define_res["definition"]

    # Verify both changes are visible
    sym_names = {s["name"] for s in t_symbols.list_symbols(bid, ctx)["items"]}
    assert "X" in sym_names

    type_res = t_types.get_type(bid, "Foo", ctx)
    assert type_res["definition"] is not None

    # First undo — reverts define_type("Foo")
    undo1 = t_undo.undo(bid, ctx)
    assert undo1["undone"] is True
    foo_after_undo1 = t_types.get_type(bid, "Foo", ctx)
    assert foo_after_undo1["definition"] is None, "Foo type was not reverted by first undo"

    # Second undo — reverts rename F1 → "X"
    undo2 = t_undo.undo(bid, ctx)
    assert undo2["undone"] is True
    sym_names_after = {s["name"] for s in t_symbols.list_symbols(bid, ctx)["items"]}
    assert "X" not in sym_names_after, "rename X was not reverted by second undo"
    assert f1_original in sym_names_after, f"original name {f1_original!r} not restored"

    t_lifecycle.close_binary(bid, ctx)


# ---------------------------------------------------------------------------
# Scenario B2 — Bulk-undo: external begin/commit groups multiple writes
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    bool(os.environ.get("BINJA_MCP_LIVE_TARGET")),
    reason="bulk-undo nesting is mock-only behavior; real BN creates per-write groups",
)
def test_scenario_b2_bulk_undo_single_revert(supervisor, fixture_binary):
    """External begin_undo → multiple writes → commit_undo → single undo() reverts all.

    Mock-only: when a caller issues begin_undo before tool calls, the re-entrant
    undo_transaction helper must NOT open a nested state. All writes land in
    the outer group so a single undo() rolls them all back atomically.
    """
    ctx = _ctx(supervisor)
    bid = t_lifecycle.open_binary(str(fixture_binary), ctx)["binary_id"]

    funcs = t_functions.list_functions(bid, ctx, limit=10)["items"]
    f1 = funcs[0]
    f1_addr = f1["start"]
    f1_original = f1["name"]

    # Open an explicit outer undo group
    state_id = t_undo.begin_undo(bid, ctx)["state_id"]

    # Perform two writes inside the outer group
    t_symbols.rename_symbol(bid, f1_addr, "BULK_X", ctx)
    t_types.define_type(bid, "BulkFoo", "typedef struct {int v;} BulkFoo;", ctx)

    # Commit the outer group
    t_undo.commit_undo(bid, state_id, ctx)

    # Verify both writes are visible
    sym_names = {s["name"] for s in t_symbols.list_symbols(bid, ctx)["items"]}
    assert "BULK_X" in sym_names
    foo_res = t_types.get_type(bid, "BulkFoo", ctx)
    assert foo_res["definition"] is not None

    # Single undo() must revert both changes atomically
    undo_res = t_undo.undo(bid, ctx)
    assert undo_res["undone"] is True

    sym_names_after = {s["name"] for s in t_symbols.list_symbols(bid, ctx)["items"]}
    assert "BULK_X" not in sym_names_after, "BULK_X was not reverted by single undo"
    assert f1_original in sym_names_after, f"original name {f1_original!r} not restored"

    foo_after = t_types.get_type(bid, "BulkFoo", ctx)
    assert foo_after["definition"] is None, "BulkFoo type was not reverted by single undo"

    t_lifecycle.close_binary(bid, ctx)


# ---------------------------------------------------------------------------
# Scenario C — Multi-binary isolation
# ---------------------------------------------------------------------------


def test_scenario_c_multi_binary_isolation(supervisor, tmp_path):
    """Changes to binary A must not affect binary B.

    Steps:
      - open A and B → list_binaries total=2
      - rename addr_in_A to "ALPHA"
      - B.list_symbols must not contain "ALPHA"
      - undo on A → B still unaffected
      - close A → B still works
      - close B → total=0
    """
    ctx = _ctx(supervisor)

    # Create two distinct files
    file_a = tmp_path / "a.bin"
    file_b = tmp_path / "b.bin"
    file_a.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 64)
    file_b.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x01" * 64)

    bid_a = t_lifecycle.open_binary(str(file_a), ctx)["binary_id"]
    bid_b = t_lifecycle.open_binary(str(file_b), ctx)["binary_id"]

    listing = t_lifecycle.list_binaries(ctx)
    assert listing["total"] == 2
    ids = {it["binary_id"] for it in listing["items"]}
    assert bid_a in ids and bid_b in ids

    # Rename a function in A
    funcs_a = t_functions.list_functions(bid_a, ctx, limit=1)["items"]
    addr_a = funcs_a[0]["start"]
    t_symbols.rename_symbol(bid_a, addr_a, "ALPHA", ctx)

    # Verify A has ALPHA
    syms_a = {s["name"] for s in t_symbols.list_symbols(bid_a, ctx)["items"]}
    assert "ALPHA" in syms_a

    # B must not have ALPHA
    syms_b = {s["name"] for s in t_symbols.list_symbols(bid_b, ctx)["items"]}
    assert "ALPHA" not in syms_b, f"ALPHA leaked into B's symbols: {syms_b}"

    # Undo A → B unchanged
    t_undo.undo(bid_a, ctx)
    syms_b_after_undo = {s["name"] for s in t_symbols.list_symbols(bid_b, ctx)["items"]}
    assert "ALPHA" not in syms_b_after_undo

    # Close A → B still works
    t_lifecycle.close_binary(bid_a, ctx)
    funcs_b = t_functions.list_functions(bid_b, ctx, limit=3)
    assert funcs_b["total"] >= 1

    # Close B → empty
    t_lifecycle.close_binary(bid_b, ctx)
    assert t_lifecycle.list_binaries(ctx)["total"] == 0


# ---------------------------------------------------------------------------
# Scenario D — Error recovery
# ---------------------------------------------------------------------------


def test_scenario_d_error_recovery(supervisor, fixture_binary):
    """Invalid operations must not kill the session.

    Steps:
      - open → rename with empty name → ValueError → list_functions still works
      - begin_undo → commit_undo with wrong id → BinjaError → new begin_undo works
    """
    ctx = _ctx(supervisor)
    bid = t_lifecycle.open_binary(str(fixture_binary), ctx)["binary_id"]

    # -- Part 1: invalid rename (empty new_name) --
    funcs = t_functions.list_functions(bid, ctx, limit=1)["items"]
    addr = funcs[0]["start"]

    with pytest.raises(ValueError):
        t_symbols.rename_symbol(bid, addr, "", ctx)

    # Session must still be alive
    recover = t_functions.list_functions(bid, ctx, limit=3)
    assert recover["total"] >= 1

    # -- Part 2: commit_undo with wrong state_id --
    _valid_state = t_undo.begin_undo(bid, ctx)["state_id"]

    with pytest.raises(BinjaError) as exc_info:
        t_undo.commit_undo(bid, "wrong-state-id-xyz", ctx)
    assert exc_info.value.code == UNDO_STATE_INVALID

    # Session must still be alive; a fresh begin_undo works
    new_state = t_undo.begin_undo(bid, ctx)["state_id"]
    assert isinstance(new_state, str) and len(new_state) >= 8

    t_lifecycle.close_binary(bid, ctx)


# ---------------------------------------------------------------------------
# Scenario E — Path traversal defence
# ---------------------------------------------------------------------------


def test_scenario_e_path_traversal_defence(supervisor, tmp_path, monkeypatch):
    """BINJA_MCP_ALLOWED_ROOTS restricts which paths can be opened.

    Steps:
      - Set ALLOWED_ROOTS to tmp_path
      - open(tmp_path/file) → succeeds
      - open(different_path) → PermissionError
      - unset ALLOWED_ROOTS → open(any path) → succeeds again
    """
    ctx = _ctx(supervisor)

    allowed_file = tmp_path / "allowed.bin"
    allowed_file.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 64)

    # File that lives outside tmp_path
    other_dir = tmp_path.parent
    other_file = other_dir / "outside.bin"
    try:
        other_file.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 64)
    except (PermissionError, OSError):
        pytest.skip("cannot write outside tmp_path on this system")

    monkeypatch.setenv("BINJA_MCP_ALLOWED_ROOTS", str(tmp_path))

    # File inside allowed root → OK
    res = t_lifecycle.open_binary(str(allowed_file), ctx)
    assert "binary_id" in res
    bid_allowed = res["binary_id"]

    # File outside allowed root → PermissionError
    with pytest.raises(PermissionError):
        t_lifecycle.open_binary(str(other_file), ctx)

    # Unset env → restriction lifted
    monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
    # Confirm env is really gone
    assert os.environ.get("BINJA_MCP_ALLOWED_ROOTS") is None

    # Can now open the previously forbidden file (if it exists and is accessible)
    res2 = t_lifecycle.open_binary(str(other_file), ctx)
    assert "binary_id" in res2

    # Cleanup
    t_lifecycle.close_binary(bid_allowed, ctx)
    t_lifecycle.close_binary(res2["binary_id"], ctx)
    try:
        other_file.unlink()
    except Exception:
        pass
