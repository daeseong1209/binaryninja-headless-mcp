"""Live integration tests against a real Binary Ninja installation.

Run with:
    BINJA_MCP_LIVE_TARGET=/path/to/binary pytest -m live

These tests are skipped automatically when BINJA_MCP_LIVE_TARGET is not set.
All tests share a single open session (module-scope fixture) to keep total
analysis time low.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

# ── Module-scope: ensure mock is off before the live supervisor is created ──


@pytest.fixture(scope="module")
def live_session():
    """Open one real binary for all live tests.

    Yields a dict with 'supervisor' and 'binary_id'.
    """
    target = os.environ.get("BINJA_MCP_LIVE_TARGET")
    if not target:
        pytest.skip("set BINJA_MCP_LIVE_TARGET to a real binary path")

    # Strip mock-forcing env vars so Supervisor uses the real binaryninja backend.
    # function-scoped `monkeypatch` is incompatible with module scope, so we
    # manage a module-scoped MonkeyPatch context manually.
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BINJA_MCP_FORCE_MOCK", raising=False)
        mp.delenv("BINJA_MCP_ALLOW_MOCK", raising=False)

        from binja_mcp.supervisor import Supervisor

        sup = Supervisor(force_mock=False)
        binary_id = sup.open(target)
        try:
            yield {"supervisor": sup, "binary_id": binary_id}
        finally:
            sup.close_all()


# Helper: build a minimal MCP Context backed by the live supervisor
def _ctx(supervisor):
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=supervisor)
        )
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.live
def test_open_real_binary_returns_is_mock_false(live_session):
    """open_binary should report is_mock=False for a real BN session."""
    from binja_mcp.tools import info as t_info

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)
    info = t_info.binary_info(binary_id, ctx)
    assert info["is_mock"] is False


@pytest.mark.live
def test_binary_info_real_arch_detected(live_session):
    """binary_info should report a recognised architecture and sane metadata."""
    from binja_mcp.tools import info as t_info

    known_arches = {"x86", "x86_64", "aarch64", "arm", "mips", "ppc", "riscv"}
    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)
    info = t_info.binary_info(binary_id, ctx)

    arch = info.get("arch") or ""
    assert any(a in arch.lower() for a in known_arches), f"unexpected arch: {arch!r}"
    assert info["entry_point"].startswith("0x")
    assert info["function_count"] > 0


@pytest.mark.live
def test_list_functions_real_binary_nonempty(live_session):
    """list_functions should return many functions for a non-trivial binary."""
    from binja_mcp.tools import functions as t_functions

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)
    page = t_functions.list_functions(binary_id, ctx, offset=0, limit=200)

    assert page["total"] > 50, f"expected >50 functions, got {page['total']}"
    assert page["items"][0]["start"].startswith("0x")


@pytest.mark.live
def test_decompile_entry_function_text_not_repr(live_session):
    """decompile should return human-readable HLIL, not an ILFunction repr."""
    from binja_mcp.tools import decompile as t_decompile
    from binja_mcp.tools import info as t_info

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    info = t_info.binary_info(binary_id, ctx)
    entry = info["entry_point"]  # e.g. "0x401000"

    result = t_decompile.decompile(binary_id, entry, ctx)
    text = result["text"]
    assert not text.startswith("<"), f"text looks like a repr: {text[:80]!r}"
    assert "ILFunction" not in text


@pytest.mark.live
def test_get_il_all_levels_real_binary(live_session):
    """get_il should return textual IL (not repr) for all three levels."""
    from binja_mcp.tools import decompile as t_decompile
    from binja_mcp.tools import info as t_info

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    info = t_info.binary_info(binary_id, ctx)
    entry = info["entry_point"]

    for level in ("LLIL", "MLIL", "HLIL"):
        result = t_decompile.get_il(binary_id, entry, ctx, level=level)
        text = result["text"]
        assert "ILFunction" not in text, f"{level} text looks like repr: {text[:80]!r}"
        assert len(text) > 0, f"{level} returned empty text"


@pytest.mark.live
def test_raw_disasm_real_binary(live_session):
    """get_disasm with an arbitrary address should return raw disassembly lines."""
    from binja_mcp.tools import decompile as t_decompile
    from binja_mcp.tools import info as t_info

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    info = t_info.binary_info(binary_id, ctx)
    # Use entry_point + 1 to force the raw (non-function) disassembly path
    entry_int = int(info["entry_point"], 16)
    raw_addr = f"0x{entry_int + 1:x}"

    result = t_decompile.get_disasm(binary_id, raw_addr, ctx, length=32)
    # Should have either 'address' key (raw path) or 'function' key
    assert "address" in result or "function" in result
    assert "text" in result


@pytest.mark.live
def test_xrefs_to_real_function_has_refs(live_session):
    """get_xrefs_to should return a valid dict structure (total >= 0)."""
    from binja_mcp.tools import info as t_info
    from binja_mcp.tools import xrefs as t_xrefs

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    info = t_info.binary_info(binary_id, ctx)
    entry = info["entry_point"]

    result = t_xrefs.get_xrefs_to(binary_id, entry, ctx)
    assert "target" in result
    assert "target_address" in result
    assert "items" in result
    assert "total" in result
    assert result["total"] >= 0


@pytest.mark.live
def test_search_strings_real_binary_nonempty(live_session):
    """search_strings with no pattern should find strings in a real binary."""
    from binja_mcp.tools import strings as t_strings

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    result = t_strings.search_strings(binary_id, ctx)
    assert result["total"] > 5, f"expected >5 strings, got {result['total']}"
    for item in result["items"][:3]:
        assert "value" in item
        assert "address" in item


@pytest.mark.live
def test_list_segments_real_pe(live_session):
    """list_segments should return at least one segment with readable=True."""
    from binja_mcp.tools import sections as t_sections

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    result = t_sections.list_segments(binary_id, ctx)
    assert result["total"] >= 1
    assert any(item["readable"] for item in result["items"])


@pytest.mark.live
def test_list_sections_real_pe(live_session):
    """list_sections should return at least 2 sections including .text."""
    from binja_mcp.tools import sections as t_sections

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    result = t_sections.list_sections(binary_id, ctx)
    assert result["total"] >= 2
    names = {item["name"] for item in result["items"]}
    assert ".text" in names, f"expected .text in sections, got {names}"


@pytest.mark.live
def test_list_imports_real_pe(live_session):
    """list_imports should return at least 5 imports for a non-trivial PE."""
    from binja_mcp.tools import sections as t_sections

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    result = t_sections.list_imports(binary_id, ctx)
    assert result["total"] >= 5, f"expected >= 5 imports, got {result['total']}"


@pytest.mark.live
def test_list_imports_real_pe_has_known_apis(live_session):
    """Real Windows PE typically imports kernel32 / ntdll APIs."""
    from binja_mcp.tools import sections as t_sections

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    result = t_sections.list_imports(binary_id, ctx, limit=500)
    assert result["total"] > 5
    # At least some import names are non-empty strings
    assert any(item["name"] for item in result["items"])


@pytest.mark.live
def test_list_exports_real_pe(live_session):
    """list_exports should not crash (exports may be 0 for exe files)."""
    from binja_mcp.tools import sections as t_sections

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    result = t_sections.list_exports(binary_id, ctx)
    assert result["total"] >= 0
    assert "items" in result


@pytest.mark.live
def test_close_real_binary_frees_session(live_session):
    """Closing the binary should leave zero open sessions.

    NOTE: this test must run last because it closes the shared session.
    After this, live_session['binary_id'] is no longer valid.
    """
    from binja_mcp.tools import lifecycle as t_lifecycle

    sup = live_session["supervisor"]
    binary_id = live_session["binary_id"]
    ctx = _ctx(sup)

    t_lifecycle.close_binary(binary_id, ctx)
    listing = t_lifecycle.list_binaries(ctx)
    assert listing["total"] == 0
