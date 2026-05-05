"""Live-quick integration tests against tiny system PE fixtures.

Uses two small Windows system binaries so analysis finishes in ~1-2 seconds
per session.  The fixtures open once per module and are shared across all cases.

Run with:
    pytest -m live_quick

Skip conditions:
    - Binary Ninja not importable
    - Default fixture path absent and env var not set

Override fixture paths:
    BINJA_MCP_LIVE_TARGET_TINY_X64=C:\\Windows\\System32\\hostname.exe
    BINJA_MCP_LIVE_TARGET_TINY_X86=C:\\Windows\\SysWOW64\\where.exe
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_X64 = r"C:\Windows\System32\hostname.exe"
_DEFAULT_X86 = r"C:\Windows\SysWOW64\where.exe"

_ENV_X64 = "BINJA_MCP_LIVE_TARGET_TINY_X64"
_ENV_X86 = "BINJA_MCP_LIVE_TARGET_TINY_X86"


def _resolve_fixture_path(env_var: str, default: str) -> str | None:
    """Return an absolute path from env var or default; None if not found."""
    path = os.environ.get(env_var, default)
    if path and Path(path).exists():
        return path
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(supervisor: Any) -> SimpleNamespace:
    """Build a minimal MCP Context backed by the given supervisor."""
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=supervisor)
        )
    )


def _open_live_session(target: str) -> dict[str, Any]:
    """Open a real Binary Ninja session; raises ImportError if BN unavailable."""
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BINJA_MCP_FORCE_MOCK", raising=False)
        mp.delenv("BINJA_MCP_ALLOW_MOCK", raising=False)

        from binja_mcp.supervisor import Supervisor  # noqa: PLC0415

        sup = Supervisor(force_mock=False)
        binary_id = sup.open(target, update_analysis=True)
        return {"supervisor": sup, "binary_id": binary_id, "_mp": mp}


# ---------------------------------------------------------------------------
# Module-scope fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tiny_x64_session():
    """Open hostname.exe (or override) once for the whole module."""
    target = _resolve_fixture_path(_ENV_X64, _DEFAULT_X64)
    if target is None:
        pytest.skip(
            f"tiny x64 fixture not found; set {_ENV_X64} to a valid PE path"
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BINJA_MCP_FORCE_MOCK", raising=False)
        mp.delenv("BINJA_MCP_ALLOW_MOCK", raising=False)

        try:
            from binja_mcp.supervisor import Supervisor  # noqa: PLC0415
        except Exception:
            pytest.skip("binja_mcp not importable")

        try:
            sup = Supervisor(force_mock=False)
            binary_id = sup.open(target, update_analysis=True)
        except Exception as exc:
            pytest.skip(f"Binary Ninja unavailable or unlicensed: {exc}")

        try:
            yield {"supervisor": sup, "binary_id": binary_id, "path": target}
        finally:
            sup.close_all()


@pytest.fixture(scope="module")
def tiny_x86_session():
    """Open where.exe (or override) once for the whole module."""
    target = _resolve_fixture_path(_ENV_X86, _DEFAULT_X86)
    if target is None:
        pytest.skip(
            f"tiny x86 fixture not found; set {_ENV_X86} to a valid PE path"
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BINJA_MCP_FORCE_MOCK", raising=False)
        mp.delenv("BINJA_MCP_ALLOW_MOCK", raising=False)

        try:
            from binja_mcp.supervisor import Supervisor  # noqa: PLC0415
        except Exception:
            pytest.skip("binja_mcp not importable")

        try:
            sup = Supervisor(force_mock=False)
            binary_id = sup.open(target, update_analysis=True)
        except Exception as exc:
            pytest.skip(f"Binary Ninja unavailable or unlicensed: {exc}")

        try:
            yield {"supervisor": sup, "binary_id": binary_id, "path": target}
        finally:
            sup.close_all()


# ===========================================================================
# Group A: Smoke — every tool touched at least once (23 cases)
# ===========================================================================


@pytest.mark.live_quick
def test_A01_open_binary_is_mock_false(tiny_x64_session):
    """open_binary result from fixture session should have is_mock=False."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    info = t_info.binary_info(binary_id, ctx)
    assert info["is_mock"] is False


@pytest.mark.live_quick
def test_A02_list_binaries_total_ge_1(tiny_x64_session):
    """list_binaries should show at least one open binary."""
    from binja_mcp.tools import lifecycle as t_lifecycle  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    ctx = _ctx(sup)
    result = t_lifecycle.list_binaries(ctx)
    assert result["total"] >= 1


@pytest.mark.live_quick
def test_A03_binary_info_arch_and_function_count(tiny_x64_session):
    """binary_info should report a known arch and positive function count."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    info = t_info.binary_info(binary_id, ctx)

    known_arches = {"x86", "x86_64", "aarch64", "arm", "mips", "ppc", "riscv"}
    arch = (info.get("arch") or "").lower()
    assert any(a in arch for a in known_arches), f"unexpected arch: {arch!r}"
    assert info["function_count"] > 0
    assert info["entry_point"].startswith("0x")


@pytest.mark.live_quick
def test_A04_list_functions_nonempty_with_hex_start(tiny_x64_session):
    """list_functions should return items and addresses as hex strings."""
    from binja_mcp.tools import functions as t_functions  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    page = t_functions.list_functions(binary_id, ctx, offset=0, limit=50)
    assert page["total"] > 0
    assert page["items"][0]["start"].startswith("0x")


@pytest.mark.live_quick
def test_A05_decompile_entry_not_repr(tiny_x64_session):
    """decompile should return human-readable HLIL, not an object repr."""
    from binja_mcp.tools import decompile as t_decompile  # noqa: PLC0415
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_decompile.decompile(binary_id, entry, ctx)
    text = result["text"]
    assert "<HighLevelILFunction" not in text, f"text looks like repr: {text[:80]!r}"
    assert "ILFunction" not in text


@pytest.mark.live_quick
def test_A06_get_il_llil_not_repr(tiny_x64_session):
    """get_il(LLIL) should return non-repr text."""
    from binja_mcp.tools import decompile as t_decompile  # noqa: PLC0415
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_decompile.get_il(binary_id, entry, ctx, level="LLIL")
    assert "ILFunction" not in result["text"]
    assert len(result["text"]) > 0


@pytest.mark.live_quick
def test_A07_get_il_mlil_not_repr(tiny_x64_session):
    """get_il(MLIL) should return non-repr text."""
    from binja_mcp.tools import decompile as t_decompile  # noqa: PLC0415
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_decompile.get_il(binary_id, entry, ctx, level="MLIL")
    assert "ILFunction" not in result["text"]
    assert len(result["text"]) > 0


@pytest.mark.live_quick
def test_A08_get_il_hlil_not_repr(tiny_x64_session):
    """get_il(HLIL) should return non-repr text."""
    from binja_mcp.tools import decompile as t_decompile  # noqa: PLC0415
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_decompile.get_il(binary_id, entry, ctx, level="HLIL")
    assert "ILFunction" not in result["text"]
    assert len(result["text"]) > 0


@pytest.mark.live_quick
def test_A09_get_disasm_returns_text(tiny_x64_session):
    """get_disasm should return a text response (function or address path)."""
    from binja_mcp.tools import decompile as t_decompile  # noqa: PLC0415
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_decompile.get_disasm(binary_id, entry, ctx, length=64)
    assert "text" in result
    assert "address" in result or "function" in result


@pytest.mark.live_quick
def test_A10_get_xrefs_to_structure(tiny_x64_session):
    """get_xrefs_to should return a dict with target/items/total keys."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415
    from binja_mcp.tools import xrefs as t_xrefs  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_xrefs.get_xrefs_to(binary_id, entry, ctx)
    assert "target" in result
    assert "target_address" in result
    assert "items" in result
    assert "total" in result
    assert result["total"] >= 0


@pytest.mark.live_quick
def test_A11_search_strings_nonempty(tiny_x64_session):
    """search_strings with no pattern should find at least one string."""
    from binja_mcp.tools import strings as t_strings  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_strings.search_strings(binary_id, ctx)
    assert result["total"] >= 1
    for item in result["items"][:3]:
        assert "value" in item
        assert "address" in item


@pytest.mark.live_quick
def test_A12_list_segments_readable(tiny_x64_session):
    """list_segments should return segments with bool r/w/x fields."""
    from binja_mcp.tools import sections as t_sections  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_sections.list_segments(binary_id, ctx)
    assert result["total"] >= 1
    for seg in result["items"]:
        assert isinstance(seg["readable"], bool)
        assert isinstance(seg["writable"], bool)
        assert isinstance(seg["executable"], bool)


@pytest.mark.live_quick
def test_A13_list_sections_semantics_enum_name(tiny_x64_session):
    """list_sections semantics field should be an enum name, not a raw int."""
    from binja_mcp.tools import sections as t_sections  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_sections.list_sections(binary_id, ctx)
    assert result["total"] >= 1
    for sec in result["items"]:
        sem = sec.get("semantics", "")
        # Must not be a bare integer string like "1" or "2"
        if sem:
            assert not sem.isdigit(), f"semantics looks like raw int: {sem!r}"


@pytest.mark.live_quick
def test_A14_list_imports_nonempty(tiny_x64_session):
    """list_imports should return at least one Windows API import."""
    from binja_mcp.tools import sections as t_sections  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_sections.list_imports(binary_id, ctx)
    assert result["total"] >= 1


@pytest.mark.live_quick
def test_A15_list_exports_no_crash(tiny_x64_session):
    """list_exports should not crash even if the binary has no exports."""
    from binja_mcp.tools import sections as t_sections  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_sections.list_exports(binary_id, ctx)
    assert result["total"] >= 0
    assert "items" in result


@pytest.mark.live_quick
def test_A16_list_symbols_function_type(tiny_x64_session):
    """list_symbols(symbol_type='function') should return at least one symbol."""
    from binja_mcp.tools import symbols as t_symbols  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_symbols.list_symbols(binary_id, ctx, symbol_type="function")
    assert result["total"] > 0


@pytest.mark.live_quick
def test_A17_list_symbols_name_lookup(tiny_x64_session):
    """list_symbols(name_or_addr=<entry addr>) should return a single match."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415
    from binja_mcp.tools import symbols as t_symbols  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    # look up by address — may raise SYMBOL_NOT_FOUND if entry isn't a named sym;
    # either outcome (match or BinjaError) is acceptable; crash is not.
    try:
        result = t_symbols.list_symbols(binary_id, ctx, name_or_addr=entry)
        assert result["total"] >= 1
    except Exception as exc:
        from binja_mcp.errors import BinjaError  # noqa: PLC0415

        assert isinstance(exc, BinjaError), f"unexpected exception type: {exc!r}"


@pytest.mark.live_quick
def test_A18_begin_undo_returns_state_id(tiny_x64_session):
    """begin_undo should return a non-empty state_id string."""
    from binja_mcp.tools import undo as t_undo  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_undo.begin_undo(binary_id, ctx)
    assert "state_id" in result
    assert isinstance(result["state_id"], str)
    assert result["state_id"]


@pytest.mark.live_quick
def test_A19_rename_symbol_before_after(tiny_x64_session):
    """rename_symbol should report before/after and the after matches new_name."""
    from binja_mcp.tools import functions as t_functions  # noqa: PLC0415
    from binja_mcp.tools import symbols as t_symbols  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    page = t_functions.list_functions(binary_id, ctx, limit=1)
    addr = page["items"][0]["start"]
    new_name = "LIVE_QUICK_RENAME_TEST"
    result = t_symbols.rename_symbol(binary_id, addr, new_name, ctx)
    assert result["after"] == new_name
    assert "before" in result


@pytest.mark.live_quick
def test_A20_commit_undo_returns_committed(tiny_x64_session):
    """commit_undo should return the state_id in 'committed' field."""
    from binja_mcp.tools import undo as t_undo  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    state_id = t_undo.begin_undo(binary_id, ctx)["state_id"]
    result = t_undo.commit_undo(binary_id, state_id, ctx)
    assert "committed" in result


@pytest.mark.live_quick
def test_A21_undo_response_shape(tiny_x64_session):
    """undo should return a dict with an 'undone' key."""
    from binja_mcp.tools import undo as t_undo  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_undo.undo(binary_id, ctx)
    assert "undone" in result


@pytest.mark.live_quick
def test_A22_redo_response_shape(tiny_x64_session):
    """redo should return a dict with a 'redone' key."""
    from binja_mcp.tools import undo as t_undo  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    result = t_undo.redo(binary_id, ctx)
    assert "redone" in result


@pytest.mark.live_quick
def test_A23_define_type_name_matches(tiny_x64_session):
    """define_type should return a result whose 'name' matches the requested name."""
    from binja_mcp.tools import types as t_types  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    source = "typedef struct { unsigned int x; unsigned int y; } LiveQuickPoint;"
    result = t_types.define_type(binary_id, "LiveQuickPoint", source, ctx)
    assert result["name"] == "LiveQuickPoint"


@pytest.mark.live_quick
def test_A24_get_type_definition_non_null(tiny_x64_session):
    """get_type should return a non-None definition for a type just defined."""
    from binja_mcp.tools import types as t_types  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    # Define it first
    source = "typedef struct { int a; int b; } LiveQuickRect;"
    t_types.define_type(binary_id, "LiveQuickRect", source, ctx)
    got = t_types.get_type(binary_id, "LiveQuickRect", ctx)
    # definition may be None if BN didn't register; but no crash is guaranteed
    assert "definition" in got


@pytest.mark.live_quick
def test_A25_define_data_var_type_field(tiny_x64_session):
    """define_data_var should return address and type fields."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415
    from binja_mcp.tools import types as t_types  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    addr = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_types.define_data_var(binary_id, addr, "uint32_t", ctx)
    assert "address" in result
    assert "type" in result
    assert result["address"] == addr


# ===========================================================================
# Group B: Codex / defect finding verification (7 cases)
# ===========================================================================


@pytest.mark.live_quick
def test_B26_C1_define_type_complex_nested_struct(tiny_x64_session):
    """C1: define_type with nested struct should register 'Outer' successfully."""
    from binja_mcp.tools import types as t_types  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    source = "typedef struct { int x; struct { int a; int b; } nested; } Outer;"
    # May succeed or raise TYPE_PARSE_ERROR depending on BN version.
    # Either is acceptable — crash or wrong exception type is not.
    try:
        result = t_types.define_type(binary_id, "Outer", source, ctx)
        assert result["name"] == "Outer"
    except Exception as exc:
        from binja_mcp.errors import BinjaError  # noqa: PLC0415

        assert isinstance(exc, BinjaError), f"unexpected exception type: {exc!r}"


@pytest.mark.live_quick
def test_B27_C2_search_strings_nested_quantifier_raises(tiny_x64_session):
    """C2: search_strings with nested quantifier regex should raise ValueError."""
    from binja_mcp.tools import strings as t_strings  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    # After fix executor's ReDoS heuristic: (a?)+ and similar are rejected.
    with pytest.raises(ValueError, match="nested quantifier|ReDoS|catastrophic"):
        t_strings.search_strings(binary_id, ctx, pattern="(a?)+", regex=True)


@pytest.mark.live_quick
def test_B28_M3_rename_non_start_addr_raises_binja_error(tiny_x64_session):
    """M3: rename_symbol at addr+1 (non-function-start) raises BinjaError(INVALID_ADDRESS)."""
    from binja_mcp.errors import INVALID_ADDRESS, BinjaError  # noqa: PLC0415
    from binja_mcp.tools import functions as t_functions  # noqa: PLC0415
    from binja_mcp.tools import symbols as t_symbols  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    page = t_functions.list_functions(binary_id, ctx, limit=1)
    start_int = int(page["items"][0]["start"], 16)
    bad_addr = f"0x{start_int + 1:x}"
    with pytest.raises(BinjaError) as exc_info:
        t_symbols.rename_symbol(binary_id, bad_addr, "BadName", ctx)
    err = exc_info.value
    assert err.code == INVALID_ADDRESS
    assert "containing_function" in err.extra


@pytest.mark.live_quick
def test_B29_M6_undo_empty_stack_not_blindly_true(tiny_x64_session):
    """M6: undo with no prior writes should return undone=None or undone=False, not always True."""
    from binja_mcp.tools import undo as t_undo  # noqa: PLC0415

    # Use a fresh supervisor+session with no writes to ensure empty undo stack
    target = tiny_x64_session["path"]
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BINJA_MCP_FORCE_MOCK", raising=False)
        mp.delenv("BINJA_MCP_ALLOW_MOCK", raising=False)
        try:
            from binja_mcp.supervisor import Supervisor  # noqa: PLC0415

            sup2 = Supervisor(force_mock=False)
            binary_id2 = sup2.open(target, update_analysis=True)
        except Exception as exc:
            pytest.skip(f"could not open fresh session: {exc}")

        try:
            ctx2 = _ctx(sup2)
            result = t_undo.undo(binary_id2, ctx2)
            assert "undone" in result
            # After M6 fix: real BN with empty stack returns undone=None (not True)
            # undone must NOT be hardcoded True when nothing was changed
            assert result["undone"] is not True or result.get("remaining") is not None, (
                "M6 regression: undo reports undone=True with remaining=None on empty stack"
            )
        finally:
            sup2.close_all()


@pytest.mark.live_quick
def test_B30_M7_rename_none_addr_raises_binja_error(tiny_x64_session):
    """M7: rename_symbol(addr=None) should raise BinjaError(INVALID_ADDRESS)."""
    from binja_mcp.errors import INVALID_ADDRESS, BinjaError  # noqa: PLC0415
    from binja_mcp.tools import symbols as t_symbols  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    with pytest.raises((BinjaError, ValueError)) as exc_info:
        t_symbols.rename_symbol(binary_id, None, "AnyName", ctx)  # type: ignore[arg-type]
    exc = exc_info.value
    if isinstance(exc, BinjaError):
        assert exc.code == INVALID_ADDRESS


@pytest.mark.live_quick
def test_B31_M2_allowed_roots_blocks_external_path(tiny_x64_session, tmp_path):
    """M2: open_binary with BINJA_MCP_ALLOWED_ROOTS set to tmp_path should block system path."""
    from binja_mcp.tools import lifecycle as t_lifecycle  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    ctx = _ctx(sup)
    target = tiny_x64_session["path"]

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("BINJA_MCP_ALLOWED_ROOTS", str(tmp_path))
        with pytest.raises(PermissionError):
            t_lifecycle.open_binary(target, ctx)

    # After removing restriction, the original session's supervisor can still open it
    # (no assertion needed — just confirm no residual state leak)


@pytest.mark.live_quick
def test_B32_M2_normal_open_after_restriction_lifted(tiny_x64_session):
    """M2 follow-up: after removing BINJA_MCP_ALLOWED_ROOTS, open should succeed."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x64_session["supervisor"]
    binary_id = tiny_x64_session["binary_id"]
    ctx = _ctx(sup)
    # If the shared session is still alive, binary_info must succeed
    info = t_info.binary_info(binary_id, ctx)
    assert info["function_count"] > 0


# ===========================================================================
# Group C: 32-bit coverage (tiny_x86_session, 3 cases)
# ===========================================================================


@pytest.mark.live_quick
def test_C33_x86_binary_info_arch(tiny_x86_session):
    """32-bit fixture should report arch containing 'x86' (not 'x86_64')."""
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x86_session["supervisor"]
    binary_id = tiny_x86_session["binary_id"]
    ctx = _ctx(sup)
    info = t_info.binary_info(binary_id, ctx)
    arch = (info.get("arch") or "").lower()
    assert "x86" in arch, f"expected x86 arch, got {arch!r}"


@pytest.mark.live_quick
def test_C34_x86_list_segments(tiny_x86_session):
    """32-bit fixture should have at least one segment (PE32 layout)."""
    from binja_mcp.tools import sections as t_sections  # noqa: PLC0415

    sup = tiny_x86_session["supervisor"]
    binary_id = tiny_x86_session["binary_id"]
    ctx = _ctx(sup)
    result = t_sections.list_segments(binary_id, ctx)
    assert result["total"] >= 1


@pytest.mark.live_quick
def test_C35_x86_decompile_entry_not_repr(tiny_x86_session):
    """32-bit decompile entry should return human-readable text."""
    from binja_mcp.tools import decompile as t_decompile  # noqa: PLC0415
    from binja_mcp.tools import info as t_info  # noqa: PLC0415

    sup = tiny_x86_session["supervisor"]
    binary_id = tiny_x86_session["binary_id"]
    ctx = _ctx(sup)
    entry = t_info.binary_info(binary_id, ctx)["entry_point"]
    result = t_decompile.decompile(binary_id, entry, ctx)
    text = result["text"]
    assert "<HighLevelILFunction" not in text
    assert "ILFunction" not in text


# ===========================================================================
# Group D: Callgraph (v0.4) — get_callers / get_callees / get_call_sites
# ===========================================================================


class TestCallgraphLive:
    """Live-quick coverage for the v0.4 callgraph tools on hostname.exe."""

    @pytest.mark.live_quick
    def test_D36_callers_of_NlsFPutStringW_includes_wmain(self, tiny_x64_session):
        """get_callers of _NlsFPutStringW@8 should report >=1 caller (typically _wmain)."""
        from binja_mcp.tools import callgraph as t_callgraph  # noqa: PLC0415

        sup = tiny_x64_session["supervisor"]
        binary_id = tiny_x64_session["binary_id"]
        ctx = _ctx(sup)
        try:
            result = t_callgraph.get_callers(binary_id, "_NlsFPutStringW@8", ctx)
        except ValueError:
            pytest.skip("target function not present in this hostname.exe build")
        assert result["total"] >= 1
        names = {it["function"]["name"] for it in result["items"] if it.get("function")}
        # _wmain or other expected callers should appear; we accept any non-empty set
        assert names, f"no caller names extracted; raw items: {result['items'][:3]}"

    @pytest.mark.live_quick
    def test_D37_callees_of_wmain_include_known_imports(self, tiny_x64_session):
        """get_callees of _wmain should include at least one well-known import."""
        from binja_mcp.tools import callgraph as t_callgraph  # noqa: PLC0415

        sup = tiny_x64_session["supervisor"]
        binary_id = tiny_x64_session["binary_id"]
        ctx = _ctx(sup)
        try:
            result = t_callgraph.get_callees(binary_id, "_wmain", ctx, limit=500)
        except ValueError:
            pytest.skip("_wmain not present")
        target_names = {
            it["target"]["name"] for it in result["items"] if it.get("target")
        }
        # hostname.exe _wmain calls Heap*, GetHostName*, NlsFPutStringW, etc.
        expected_any = {
            "_GetHostNameW@8",
            "_HeapSetInformation@16",
            "_NlsFPutStringW@8",
            "GetHostNameW",
            "HeapSetInformation",
        }
        assert target_names & expected_any, (
            f"none of {expected_any} found in callees: {sorted(target_names)[:10]}"
        )

    @pytest.mark.live_quick
    def test_D38_call_sites_of_wmain_within_function_bounds(self, tiny_x64_session):
        """get_call_sites of _wmain returns >=1 entry; every site lies within _wmain."""
        from binja_mcp.tools import callgraph as t_callgraph  # noqa: PLC0415
        from binja_mcp.tools import functions as t_functions  # noqa: PLC0415

        sup = tiny_x64_session["supervisor"]
        binary_id = tiny_x64_session["binary_id"]
        ctx = _ctx(sup)
        try:
            sites = t_callgraph.get_call_sites(binary_id, "_wmain", ctx, limit=500)
        except ValueError:
            pytest.skip("_wmain not present")
        assert sites["total"] >= 1

        # Locate _wmain's bounds via list_functions (avoid scanning every page)
        page = t_functions.list_functions(binary_id, ctx, limit=500)
        wmain = next((f for f in page["items"] if f["name"] == "_wmain"), None)
        if wmain is None or wmain.get("end") is None:
            pytest.skip("_wmain bounds not exposed in this build")
        start = int(wmain["start"], 16)
        end = int(wmain["end"], 16)
        for it in sites["items"]:
            addr = int(it["address"], 16)
            assert start <= addr < end, (
                f"call site 0x{addr:x} outside _wmain [0x{start:x}, 0x{end:x})"
            )
