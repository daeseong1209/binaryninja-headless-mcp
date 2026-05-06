"""Direct tool-function tests against the mock backend.

We invoke tool functions directly with a tiny fake Context to avoid the cost
of spinning up a full FastMCP server for unit tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from binja_mcp.tools import callgraph as t_callgraph
from binja_mcp.tools import decompile as t_decompile
from binja_mcp.tools import functions as t_functions
from binja_mcp.tools import info as t_info
from binja_mcp.tools import lifecycle as t_lifecycle
from binja_mcp.tools import sections as t_sections
from binja_mcp.tools import strings as t_strings
from binja_mcp.tools import symbols as t_symbols
from binja_mcp.tools import types as t_types
from binja_mcp.tools import undo as t_undo
from binja_mcp.tools import xrefs as t_xrefs


@pytest.fixture
def ctx(supervisor):
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=supervisor)
        )
    )


@pytest.fixture
def open_id(ctx, fixture_binary) -> str:
    res = t_lifecycle.open_binary(str(fixture_binary), ctx)
    return res["binary_id"]


# --- lifecycle ---------------------------------------------------------------


class TestLifecycle:
    def test_open_returns_handle_and_mock_flag(self, ctx, fixture_binary):
        res = t_lifecycle.open_binary(str(fixture_binary), ctx)
        assert "binary_id" in res
        assert res["path"] == str(fixture_binary)
        assert res["is_mock"] is True

    def test_open_with_update_analysis_false(self, ctx, fixture_binary):
        res = t_lifecycle.open_binary(str(fixture_binary), ctx, update_analysis=False)
        assert res["binary_id"]

    def test_close_then_list_empty(self, ctx, open_id):
        t_lifecycle.close_binary(open_id, ctx)
        listing = t_lifecycle.list_binaries(ctx)
        assert listing["total"] == 0

    def test_list_shows_open_binaries(self, ctx, open_id):
        listing = t_lifecycle.list_binaries(ctx)
        assert listing["total"] == 1
        assert listing["items"][0]["binary_id"] == open_id

    # --- path traversal / security -------------------------------------------

    def test_open_allowed_roots_accepted(self, ctx, tmp_path, monkeypatch):
        """File inside BINJA_MCP_ALLOWED_ROOTS is accepted."""
        binary = tmp_path / "ok.bin"
        binary.write_bytes(b"\x7fELF" + b"\x00" * 60)
        monkeypatch.setenv("BINJA_MCP_ALLOWED_ROOTS", str(tmp_path))
        res = t_lifecycle.open_binary(str(binary), ctx)
        assert "binary_id" in res

    def test_open_allowed_roots_rejected(self, ctx, tmp_path, monkeypatch):
        """File outside BINJA_MCP_ALLOWED_ROOTS raises PermissionError."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        forbidden = tmp_path / "other.bin"
        forbidden.write_bytes(b"\x7fELF" + b"\x00" * 60)
        monkeypatch.setenv("BINJA_MCP_ALLOWED_ROOTS", str(allowed))
        with pytest.raises(PermissionError):
            t_lifecycle.open_binary(str(forbidden), ctx)

    def test_open_no_allowed_roots_env_skips_check(self, ctx, tmp_path, monkeypatch):
        """When BINJA_MCP_ALLOWED_ROOTS is unset, any path is accepted (backward compat)."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        binary = tmp_path / "any.bin"
        binary.write_bytes(b"\x7fELF" + b"\x00" * 60)
        res = t_lifecycle.open_binary(str(binary), ctx)
        assert "binary_id" in res

    def test_open_symlink_rejected(self, ctx, tmp_path, monkeypatch):
        """Symlinks are rejected regardless of allowed roots."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        target = tmp_path / "real.bin"
        target.write_bytes(b"\x7fELF" + b"\x00" * 60)
        link = tmp_path / "link.bin"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not available on this platform/user")
        with pytest.raises(PermissionError, match="symlinks not allowed"):
            t_lifecycle.open_binary(str(link), ctx)


# --- info --------------------------------------------------------------------


class TestInfo:
    def test_binary_info_fields(self, ctx, open_id):
        info = t_info.binary_info(open_id, ctx)
        assert info["binary_id"] == open_id
        assert info["arch"] == "x86_64"
        assert info["function_count"] >= 1
        assert info["is_mock"] is True
        assert info["entry_point"].startswith("0x")

    def test_binary_info_unknown_id(self, ctx):
        with pytest.raises(ValueError, match="unknown binary_id"):
            t_info.binary_info("does-not-exist", ctx)

    def test_binary_info_function_count_o1(self, ctx, open_id):
        """function_count should use len() not list() materialisation."""
        info = t_info.binary_info(open_id, ctx)
        # Mock has exactly 7 functions
        assert info["function_count"] == 7


# --- functions ---------------------------------------------------------------


class TestFunctions:
    def test_list_functions_pagination(self, ctx, open_id):
        page = t_functions.list_functions(open_id, ctx, offset=0, limit=3)
        assert page["limit"] == 3
        assert page["offset"] == 0
        assert page["total"] >= 1
        assert len(page["items"]) <= 3

        for item in page["items"]:
            assert "name" in item
            assert item["start"].startswith("0x")

    def test_list_functions_offset_past_end(self, ctx, open_id):
        page = t_functions.list_functions(open_id, ctx, offset=9999, limit=10)
        assert page["items"] == []
        assert page["has_more"] is False

    def test_list_functions_negative_offset_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_functions.list_functions(open_id, ctx, offset=-1)

    def test_list_functions_zero_limit_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_functions.list_functions(open_id, ctx, limit=0)

    def test_list_functions_two_pages_cover_all(self, ctx, open_id):
        """Two paginated calls should together return all 7 mock functions."""
        page1 = t_functions.list_functions(open_id, ctx, offset=0, limit=3)
        page2 = t_functions.list_functions(open_id, ctx, offset=3, limit=10)

        assert page1["total"] == 7
        assert page2["total"] == 7
        assert page1["has_more"] is True
        assert page2["has_more"] is False

        all_names = {it["name"] for it in page1["items"]} | {it["name"] for it in page2["items"]}
        assert len(page1["items"]) + len(page2["items"]) == 7
        # Verify we got distinct functions (no overlap)
        assert len(all_names) == 7

    def test_list_functions_slice_before_summarize(self, ctx, open_id):
        """offset=3, limit=3 must return exactly the middle 3 functions."""
        page = t_functions.list_functions(open_id, ctx, offset=3, limit=3)
        assert len(page["items"]) == 3
        assert page["offset"] == 3
        assert page["total"] == 7


# --- decompile / IL / disasm -------------------------------------------------


class TestDecompile:
    def test_decompile_by_name(self, ctx, open_id):
        result = t_decompile.decompile(open_id, "main", ctx)
        assert result["il_level"] == "HLIL"
        assert "main" in result["text"]
        assert result["function"]["name"] == "main"

    def test_decompile_by_address(self, ctx, open_id):
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]
        result = t_decompile.decompile(open_id, addr, ctx)
        assert "text" in result

    def test_decompile_unknown_function(self, ctx, open_id):
        with pytest.raises(ValueError, match="function not found"):
            t_decompile.decompile(open_id, "no_such_function", ctx)

    @pytest.mark.parametrize("level", ["LLIL", "MLIL", "HLIL", "llil", "mlil", "hlil"])
    def test_get_il_levels(self, ctx, open_id, level):
        result = t_decompile.get_il(open_id, "main", ctx, level=level)
        assert result["il_level"] == level.upper()
        assert result["text"]

    def test_get_il_invalid_level(self, ctx, open_id):
        with pytest.raises(ValueError, match="unknown IL level"):
            t_decompile.get_il(open_id, "main", ctx, level="XLIL")

    def test_get_disasm_by_function(self, ctx, open_id):
        result = t_decompile.get_disasm(open_id, "main", ctx)
        assert result["text"]

    def test_get_disasm_by_raw_address(self, ctx, open_id):
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]
        result = t_decompile.get_disasm(open_id, addr, ctx, length=16)
        assert "address" in result or "function" in result

    def test_get_disasm_negative_length_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_decompile.get_disasm(open_id, "main", ctx, length=0)


# --- xrefs -------------------------------------------------------------------


class TestXrefs:
    def test_xrefs_to_function_by_name(self, ctx, open_id):
        result = t_xrefs.get_xrefs_to(open_id, "main", ctx)
        assert "items" in result
        assert result["target"] == "main"

    def test_xrefs_to_address(self, ctx, open_id):
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]
        result = t_xrefs.get_xrefs_to(open_id, addr, ctx)
        assert result["target_address"] == addr


# --- callgraph ---------------------------------------------------------------


class TestCallgraph:
    """Mock backend wires: main -> helper_func + decode; helper_func -> encrypt;
    decode has one indirect call site (no resolved target)."""

    # ---- get_callers --------------------------------------------------------

    def test_callers_helper_includes_main(self, ctx, open_id):
        result = t_callgraph.get_callers(open_id, "helper_func", ctx)
        assert result["target"] == "helper_func"
        assert any(it["function"]["name"] == "main" for it in result["items"])
        # caller call-site address must be a hex string
        assert all(it["address"].startswith("0x") for it in result["items"])

    def test_callers_by_address(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        helper = bv.get_function_by_name("helper_func")
        result = t_callgraph.get_callers(open_id, f"0x{helper.start:x}", ctx)
        assert result["target_address"] == f"0x{helper.start:x}"
        assert result["total"] >= 1

    def test_callers_function_with_no_refs(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        compute = bv.get_function_by_name("compute")
        # compute is a leaf: no caller_sites seeded, so it has 0 callers
        compute.caller_sites = []
        result = t_callgraph.get_callers(open_id, "compute", ctx)
        assert result["items"] == []
        assert result["total"] == 0

    def test_callers_unknown_function_raises(self, ctx, open_id):
        from binja_mcp.errors import FUNCTION_NOT_FOUND, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_callgraph.get_callers(open_id, "no_such_func_xyz", ctx)
        assert exc_info.value.code == FUNCTION_NOT_FOUND

    def test_callers_pagination(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        from binja_mcp.mock_backend import MockReference

        helper = bv.get_function_by_name("helper_func")
        main_f = bv.get_function_by_name("main")
        # Populate caller_sites (call edges) for pagination check
        helper.caller_sites = [
            MockReference(address=main_f.start + 0x20 + i, function_name="main", function=main_f)
            for i in range(5)
        ]
        page1 = t_callgraph.get_callers(open_id, "helper_func", ctx, offset=0, limit=2)
        page2 = t_callgraph.get_callers(open_id, "helper_func", ctx, offset=2, limit=10)
        assert page1["total"] == 5
        assert len(page1["items"]) == 2
        assert page1["has_more"] is True
        assert len(page2["items"]) == 3
        assert page2["has_more"] is False

    # ---- get_callees --------------------------------------------------------

    def test_callees_main_has_direct_targets(self, ctx, open_id):
        result = t_callgraph.get_callees(open_id, "main", ctx)
        assert result["source"] == "main"
        targets = {it["target"]["name"] for it in result["items"] if it["target"]}
        assert "helper_func" in targets
        assert "decode" in targets

    def test_callees_indirect_yields_target_none(self, ctx, open_id):
        result = t_callgraph.get_callees(open_id, "decode", ctx)
        # decode has exactly one site with no resolved callee
        assert result["total"] == 1
        assert result["items"][0]["target"] is None
        assert result["items"][0]["address"].startswith("0x")

    def test_callees_function_with_no_call_sites(self, ctx, open_id):
        result = t_callgraph.get_callees(open_id, "encrypt", ctx)
        assert result["items"] == []
        assert result["total"] == 0

    def test_callees_unknown_function_raises(self, ctx, open_id):
        from binja_mcp.errors import FUNCTION_NOT_FOUND, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_callgraph.get_callees(open_id, "no_such_func_xyz", ctx)
        assert exc_info.value.code == FUNCTION_NOT_FOUND

    # ---- get_call_sites -----------------------------------------------------

    def test_call_sites_main_has_two(self, ctx, open_id, supervisor):
        result = t_callgraph.get_call_sites(open_id, "main", ctx)
        bv = supervisor.get(open_id).bv
        main_f = bv.get_function_by_name("main")
        assert result["total"] == 2
        for it in result["items"]:
            site = int(it["address"], 16)
            assert main_f.start <= site < main_f.end

    def test_call_sites_function_with_none(self, ctx, open_id):
        result = t_callgraph.get_call_sites(open_id, "encrypt", ctx)
        assert result["items"] == []
        assert result["total"] == 0

    def test_call_sites_unknown_function_raises(self, ctx, open_id):
        from binja_mcp.errors import FUNCTION_NOT_FOUND, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_callgraph.get_call_sites(open_id, "no_such_func_xyz", ctx)
        assert exc_info.value.code == FUNCTION_NOT_FOUND

    def test_call_sites_resolves_by_address(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        main_f = bv.get_function_by_name("main")
        result = t_callgraph.get_call_sites(open_id, f"0x{main_f.start:x}", ctx)
        assert result["source_address"] == f"0x{main_f.start:x}"
        assert result["total"] == 2


# --- strings -----------------------------------------------------------------


class TestStrings:
    def test_search_strings_no_pattern_returns_all(self, ctx, open_id):
        result = t_strings.search_strings(open_id, ctx)
        assert result["total"] >= 1
        for item in result["items"]:
            assert "value" in item
            assert "address" in item

    def test_search_strings_substring(self, ctx, open_id):
        result = t_strings.search_strings(open_id, ctx, pattern="error")
        # Mock has "error: %s\n"
        assert any("error" in it["value"] for it in result["items"])

    def test_search_strings_case_insensitive(self, ctx, open_id):
        sensitive = t_strings.search_strings(open_id, ctx, pattern="HELLO")
        assert sensitive["total"] == 0
        insensitive = t_strings.search_strings(
            open_id, ctx, pattern="HELLO", case_sensitive=False
        )
        assert insensitive["total"] >= 1

    def test_search_strings_regex(self, ctx, open_id):
        result = t_strings.search_strings(open_id, ctx, pattern=r"^/etc/", regex=True)
        assert any(v["value"].startswith("/etc/") for v in result["items"])

    def test_search_strings_pattern_too_long(self, ctx, open_id):
        """Pattern longer than MAX_PATTERN_LENGTH raises ValueError."""
        from binja_mcp.tools.strings import MAX_PATTERN_LENGTH

        long_pattern = "a" * (MAX_PATTERN_LENGTH + 1)
        with pytest.raises(ValueError, match="pattern too long"):
            t_strings.search_strings(open_id, ctx, pattern=long_pattern)

    def test_search_strings_pattern_at_max_length_accepted(self, ctx, open_id):
        """Pattern exactly at MAX_PATTERN_LENGTH must NOT raise ValueError."""
        from binja_mcp.tools.strings import MAX_PATTERN_LENGTH

        exact_pattern = "x" * MAX_PATTERN_LENGTH
        # Won't match anything, but must not raise
        result = t_strings.search_strings(open_id, ctx, pattern=exact_pattern)
        assert "items" in result

    def test_search_strings_regex_uses_timeout_helper(self, ctx, open_id, monkeypatch):
        """When regex=True, the timeout-guarded code path is exercised."""
        import binja_mcp.tools.strings as strings_mod

        calls = []
        original = strings_mod._collect_with_timeout

        def tracked(raw, matcher, timeout):
            calls.append("called")
            return original(raw, matcher, timeout)

        monkeypatch.setattr(strings_mod, "_collect_with_timeout", tracked)
        result = t_strings.search_strings(open_id, ctx, pattern=r"error", regex=True)
        assert len(calls) >= 1, "_collect_with_timeout was not used for regex=True"
        assert any("error" in it["value"] for it in result["items"])

    def test_search_strings_regex_rejects_nested_quantifier(self, ctx, open_id):
        """Catastrophic-backtracking constructs are rejected before compile."""
        with pytest.raises(ValueError, match="nested quantifier"):
            t_strings.search_strings(open_id, ctx, pattern=r"(a+)+$", regex=True)
        with pytest.raises(ValueError, match="nested quantifier"):
            t_strings.search_strings(open_id, ctx, pattern=r"(a*)*", regex=True)

    def test_search_strings_regex_timeout_helper_raises(self, ctx, open_id, monkeypatch):
        """The daemon-thread watchdog raises TimeoutError when wait expires."""
        import binja_mcp.tools.strings as strings_mod

        monkeypatch.setattr(strings_mod, "STRING_REGEX_TIMEOUT_S", 0.001)

        def slow_collect(raw, matcher):
            import time as _time

            _time.sleep(1.0)
            return []

        monkeypatch.setattr(strings_mod, "_collect", slow_collect)
        with pytest.raises(TimeoutError, match="regex match exceeded"):
            t_strings.search_strings(open_id, ctx, pattern="anything", regex=True)


# --- sections / segments / imports / exports --------------------------------


class TestSections:
    def test_list_segments_nonempty(self, ctx, open_id):
        result = t_sections.list_segments(open_id, ctx)
        assert result["total"] > 0
        assert len(result["items"]) == result["total"]

    def test_list_segments_item_keys(self, ctx, open_id):
        result = t_sections.list_segments(open_id, ctx)
        for item in result["items"]:
            assert item["start"].startswith("0x")
            assert item["end"].startswith("0x")
            assert isinstance(item["readable"], bool)
            assert isinstance(item["writable"], bool)
            assert isinstance(item["executable"], bool)

    def test_list_segments_has_executable_segment(self, ctx, open_id):
        result = t_sections.list_segments(open_id, ctx)
        assert any(item["executable"] for item in result["items"])

    def test_list_sections_nonempty(self, ctx, open_id):
        result = t_sections.list_sections(open_id, ctx)
        assert result["total"] > 0

    def test_list_sections_contains_text_and_data(self, ctx, open_id):
        result = t_sections.list_sections(open_id, ctx)
        names = {item["name"] for item in result["items"]}
        assert ".text" in names
        assert ".data" in names

    def test_list_sections_item_keys(self, ctx, open_id):
        result = t_sections.list_sections(open_id, ctx)
        for item in result["items"]:
            assert "name" in item
            assert item["start"].startswith("0x")
            assert item["end"].startswith("0x")
            assert "semantics" in item

    def test_list_imports_has_items(self, ctx, open_id):
        result = t_sections.list_imports(open_id, ctx)
        assert result["total"] >= 1
        assert len(result["items"]) >= 1

    def test_list_imports_returns_imports_not_exports(self, ctx, open_id):
        """list_imports must return ImportedFunctionSymbol/ImportAddressSymbol entries."""
        result = t_sections.list_imports(open_id, ctx)
        names = {it["name"] for it in result["items"]}
        # mock has 'printf' (ImportedFunctionSymbol) and 'malloc' (ImportAddressSymbol)
        assert "printf" in names or "malloc" in names, (
            f"expected import names not found: {names}"
        )
        # export-marked symbol must not leak into imports
        assert "exported_func" not in names

    def test_list_imports_pagination_structure(self, ctx, open_id):
        result = t_sections.list_imports(open_id, ctx, offset=0, limit=1)
        assert "offset" in result
        assert "limit" in result
        assert "has_more" in result
        assert result["limit"] == 1

    def test_list_imports_offset_equals_total_returns_empty(self, ctx, open_id):
        total = t_sections.list_imports(open_id, ctx)["total"]
        result = t_sections.list_imports(open_id, ctx, offset=total)
        assert result["items"] == []
        assert result["has_more"] is False

    def test_list_imports_negative_offset_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_sections.list_imports(open_id, ctx, offset=-1)

    def test_list_imports_zero_limit_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_sections.list_imports(open_id, ctx, limit=0)

    def test_list_exports_has_items(self, ctx, open_id):
        result = t_sections.list_exports(open_id, ctx)
        assert result["total"] >= 1

    def test_list_exports_returns_exports_not_imports(self, ctx, open_id):
        """list_exports must return export-marked entries, not import symbols."""
        result = t_sections.list_exports(open_id, ctx)
        names = {it["name"] for it in result["items"]}
        # mock marks 'exported_func' with is_export=True
        assert "exported_func" in names or any("export" in n.lower() for n in names), (
            f"expected export names not found: {names}"
        )
        # imports must not leak into exports
        assert "printf" not in names, f"import 'printf' leaked into exports: {names}"
        assert "malloc" not in names, f"import 'malloc' leaked into exports: {names}"

    def test_list_exports_offset_equals_total_returns_empty(self, ctx, open_id):
        total = t_sections.list_exports(open_id, ctx)["total"]
        result = t_sections.list_exports(open_id, ctx, offset=total)
        assert result["items"] == []
        assert result["has_more"] is False

    def test_list_exports_negative_offset_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_sections.list_exports(open_id, ctx, offset=-1)

    def test_list_exports_zero_limit_rejected(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_sections.list_exports(open_id, ctx, limit=0)

    def test_list_segments_empty_bv(self, ctx, fixture_binary):
        """BinaryView with no segments returns total=0."""
        res = t_lifecycle.open_binary(str(fixture_binary), ctx)
        bid = res["binary_id"]
        # Monkeypatch the bv segments to empty
        from binja_mcp.supervisor import Supervisor

        sup: Supervisor = ctx.request_context.lifespan_context.supervisor
        sup.get(bid).bv.segments = []
        result = t_sections.list_segments(bid, ctx)
        assert result["total"] == 0
        assert result["items"] == []


# --- undo / redo -------------------------------------------------------------


class TestUndo:
    def test_begin_undo_returns_state_id(self, ctx, open_id):
        r = t_undo.begin_undo(open_id, ctx)
        assert "state_id" in r
        assert isinstance(r["state_id"], str)
        assert len(r["state_id"]) >= 8

    def test_begin_then_commit_pushes_to_undo_stack(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        state = t_undo.begin_undo(open_id, ctx)["state_id"]
        # Simulate a write operation (PR #4 territory) by calling _record_undo directly
        bv._record_undo("rename", addr=0x401000, before="old", after="new")
        result = t_undo.commit_undo(open_id, state, ctx)
        assert result["committed"] == state
        assert len(bv._undo_stack) == 1
        assert bv._undo_stack[-1]["id"] == state
        assert bv._undo_stack[-1]["entries"][0]["kind"] == "rename"

    def test_commit_unknown_state_raises_binja_error(self, ctx, open_id):
        from binja_mcp.errors import UNDO_STATE_INVALID, BinjaError
        with pytest.raises(BinjaError) as exc_info:
            t_undo.commit_undo(open_id, "no-such-state", ctx)
        assert exc_info.value.code == UNDO_STATE_INVALID
        assert "no-such-state" in str(exc_info.value)
        assert exc_info.value.extra.get("state_id") == "no-such-state"

    def test_commit_empty_group_is_noop(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        state = t_undo.begin_undo(open_id, ctx)["state_id"]
        # No _record_undo calls — empty group
        t_undo.commit_undo(open_id, state, ctx)
        assert len(bv._undo_stack) == 0  # empty group not pushed

    def test_undo_pops_and_pushes_redo(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        st = t_undo.begin_undo(open_id, ctx)["state_id"]
        bv._record_undo("rename", addr=0x1000, before="a", after="b")
        t_undo.commit_undo(open_id, st, ctx)
        assert len(bv._undo_stack) == 1
        r = t_undo.undo(open_id, ctx)
        assert r["undone"] is True
        assert r["remaining"] == 0
        assert len(bv._redo_stack) == 1

    def test_undo_empty_stack_returns_false(self, ctx, open_id):
        r = t_undo.undo(open_id, ctx)
        assert r["undone"] is False
        assert r["remaining"] == 0

    def test_redo_pops_and_pushes_undo(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        st = t_undo.begin_undo(open_id, ctx)["state_id"]
        bv._record_undo("rename", addr=0x1000, before="a", after="b")
        t_undo.commit_undo(open_id, st, ctx)
        t_undo.undo(open_id, ctx)
        r = t_undo.redo(open_id, ctx)
        assert r["redone"] is True
        assert len(bv._undo_stack) == 1
        assert len(bv._redo_stack) == 0

    def test_redo_empty_stack_returns_false(self, ctx, open_id):
        r = t_undo.redo(open_id, ctx)
        assert r["redone"] is False

    def test_commit_invalidates_redo_stack(self, ctx, open_id, supervisor):
        """A new commit must clear the redo stack (BN standard behavior)."""
        bv = supervisor.get(open_id).bv
        # 1st commit + undo → redo stack has 1 entry
        st1 = t_undo.begin_undo(open_id, ctx)["state_id"]
        bv._record_undo("rename", addr=0x1000, before="a", after="b")
        t_undo.commit_undo(open_id, st1, ctx)
        t_undo.undo(open_id, ctx)
        assert len(bv._redo_stack) == 1
        # 2nd commit → redo stack cleared
        st2 = t_undo.begin_undo(open_id, ctx)["state_id"]
        bv._record_undo("comment", addr=0x2000, text="x")
        t_undo.commit_undo(open_id, st2, ctx)
        assert len(bv._redo_stack) == 0

    def test_unknown_binary_id_raises(self, ctx):
        with pytest.raises(ValueError, match="unknown binary_id"):
            t_undo.undo("does-not-exist", ctx)


# --- symbols -----------------------------------------------------------------


class TestSymbols:
    def test_list_symbols_all(self, ctx, open_id):
        result = t_symbols.list_symbols(open_id, ctx)
        assert result["total"] >= 1
        names = {it["name"] for it in result["items"]}
        # Mock has _start, printf (ImportedFunctionSymbol), global_var (DataSymbol)
        assert "_start" in names, f"_start not in {names}"
        assert "printf" in names, f"printf not in {names}"
        assert "global_var" in names, f"global_var not in {names}"

    def test_list_symbols_function_filter(self, ctx, open_id):
        result = t_symbols.list_symbols(open_id, ctx, symbol_type="function")
        names = {it["name"] for it in result["items"]}
        # FunctionSymbol entries from populate_default
        assert "_start" in names, f"_start not in function symbols: {names}"
        # imported function must not appear
        assert "printf" not in names, f"printf (imported) leaked into function filter: {names}"

    def test_list_symbols_imported_function_filter(self, ctx, open_id):
        result = t_symbols.list_symbols(open_id, ctx, symbol_type="imported_function")
        names = {it["name"] for it in result["items"]}
        assert "printf" in names, f"printf not in imported_function filter: {names}"

    def test_list_symbols_data_filter(self, ctx, open_id):
        result = t_symbols.list_symbols(open_id, ctx, symbol_type="data")
        names = {it["name"] for it in result["items"]}
        assert "global_var" in names, f"global_var not in data filter: {names}"

    def test_list_symbols_pagination_offset_past_end(self, ctx, open_id):
        total = t_symbols.list_symbols(open_id, ctx)["total"]
        result = t_symbols.list_symbols(open_id, ctx, offset=total)
        assert result["items"] == []
        assert result["has_more"] is False

    def test_list_symbols_unknown_type_raises(self, ctx, open_id):
        with pytest.raises(ValueError, match="unknown symbol_type"):
            t_symbols.list_symbols(open_id, ctx, symbol_type="bogus_type")

    def test_rename_symbol_function_path_and_undo(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        # Get _start address
        funcs = t_functions.list_functions(open_id, ctx, limit=10)
        start_func = next(it for it in funcs["items"] if it["name"] == "_start")
        addr = start_func["start"]

        # Rename
        result = t_symbols.rename_symbol(open_id, addr, "RENAMED_START", ctx)
        assert result["kind"] == "function"
        assert result["after"] == "RENAMED_START"
        assert result["before"] == "_start"

        # Verify new name appears in list_symbols
        syms = t_symbols.list_symbols(open_id, ctx)
        names = {it["name"] for it in syms["items"]}
        assert "RENAMED_START" in names

        # Verify undo entry recorded before calling undo
        assert len(bv._undo_stack) >= 1
        entry = bv._undo_stack[-1]["entries"][-1]
        assert entry["kind"] == "rename_function"
        assert entry["before"] == "_start"
        assert entry["after"] == "RENAMED_START"

        # Undo: entry moves from undo_stack to redo_stack
        t_undo.undo(open_id, ctx)
        assert len(bv._redo_stack) >= 1

    def test_rename_symbol_data_path_and_undo(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        # global_var is a DataSymbol; find its address
        syms_all = t_symbols.list_symbols(open_id, ctx, symbol_type="data")
        global_sym = next(it for it in syms_all["items"] if it["name"] == "global_var")
        addr = global_sym["address"]

        # Rename via data path (no function at that address in mock)
        result = t_symbols.rename_symbol(open_id, addr, "RENAMED_GLOBAL", ctx)
        assert result["kind"] == "data"
        assert result["after"] == "RENAMED_GLOBAL"

        # Verify it appears
        syms_after = t_symbols.list_symbols(open_id, ctx, symbol_type="data")
        names = {it["name"] for it in syms_after["items"]}
        assert "RENAMED_GLOBAL" in names

        # Undo entry recorded
        assert len(bv._undo_stack) >= 1

    def test_rename_symbol_invalid_address_raises(self, ctx, open_id):
        from binja_mcp.errors import INVALID_ADDRESS, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_symbols.rename_symbol(open_id, "not_an_address", "name", ctx)
        assert exc_info.value.code == INVALID_ADDRESS

    def test_rename_symbol_empty_name_raises(self, ctx, open_id):
        with pytest.raises(ValueError):
            t_symbols.rename_symbol(open_id, "0x1000", "", ctx)

    def test_rename_symbol_unknown_binary_id(self, ctx):
        with pytest.raises(ValueError, match="unknown binary_id"):
            t_symbols.rename_symbol("no-such-id", "0x1000", "name", ctx)

    def test_list_symbols_by_name(self, ctx, open_id):
        """name_or_addr lookup by name returns the single matching symbol."""
        result = t_symbols.list_symbols(open_id, ctx, name_or_addr="printf")
        assert result["total"] == 1
        assert result["items"][0]["name"] == "printf"

    def test_list_symbols_by_addr(self, ctx, open_id):
        """name_or_addr lookup by hex address returns the matching symbol."""
        # pick the address of 'printf' symbol
        syms = t_symbols.list_symbols(open_id, ctx, symbol_type="imported_function")
        printf_sym = next(it for it in syms["items"] if it["name"] == "printf")
        result = t_symbols.list_symbols(open_id, ctx, name_or_addr=printf_sym["address"])
        assert result["total"] == 1
        assert result["items"][0]["name"] == "printf"

    def test_list_symbols_unknown_target_raises_symbol_not_found(self, ctx, open_id):
        """name_or_addr with an unknown name raises BinjaError(SYMBOL_NOT_FOUND)."""
        from binja_mcp.errors import SYMBOL_NOT_FOUND, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_symbols.list_symbols(open_id, ctx, name_or_addr="no_such_symbol_xyz")
        assert exc_info.value.code == SYMBOL_NOT_FOUND
        assert exc_info.value.extra.get("target") == "no_such_symbol_xyz"

    def test_rename_symbol_function_undo_actually_reverts(self, ctx, open_id):
        """After undo, the renamed function reverts to its original name."""
        funcs = t_functions.list_functions(open_id, ctx, limit=10)
        start_func = next(it for it in funcs["items"] if it["name"] == "_start")
        addr = start_func["start"]
        original = "_start"

        t_symbols.rename_symbol(open_id, addr, "UNDO_TEST_FUNC", ctx)
        names_after = {
            f["name"]
            for f in t_functions.list_functions(open_id, ctx, limit=10)["items"]
        }
        assert "UNDO_TEST_FUNC" in names_after

        t_undo.undo(open_id, ctx)
        names_reverted = {
            f["name"]
            for f in t_functions.list_functions(open_id, ctx, limit=10)["items"]
        }
        assert "UNDO_TEST_FUNC" not in names_reverted
        assert original in names_reverted


# --- types -------------------------------------------------------------------


class TestTypes:
    def test_define_data_var_simple_type(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]

        result = t_types.define_data_var(open_id, addr, "uint64_t", ctx)
        assert result["address"] == addr
        assert result["type"] == "uint64_t"

        # data_vars dict updated
        int_addr = int(addr, 16)
        assert int_addr in bv.data_vars
        assert bv.data_vars[int_addr].type_str == "uint64_t"

        # Undo entry recorded
        assert len(bv._undo_stack) >= 1
        assert bv._undo_stack[-1]["entries"][-1]["kind"] == "define_user_data_var"

        # Undo reverts the data_var and moves entry to redo_stack
        t_undo.undo(open_id, ctx)
        assert len(bv._redo_stack) >= 1
        assert int_addr not in bv.data_vars

    def test_define_data_var_pointer_type(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        funcs = t_functions.list_functions(open_id, ctx, limit=2)
        addr = funcs["items"][1]["start"]

        result = t_types.define_data_var(open_id, addr, "char*", ctx)
        assert result["type"] == "char*"
        int_addr = int(addr, 16)
        assert bv.data_vars[int_addr].type_str == "char*"

    def test_define_data_var_bad_type_raises(self, ctx, open_id):
        from binja_mcp.errors import TYPE_PARSE_ERROR, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            # Unclosed brace — mock parse_type_string raises ValueError
            t_types.define_data_var(open_id, "0x1000", "struct {int x;", ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR
        assert "source" in exc_info.value.extra
        assert "hint" in exc_info.value.extra

    def test_get_type_not_found_returns_none(self, ctx, open_id):
        result = t_types.get_type(open_id, "NonExistentType", ctx)
        assert result["name"] == "NonExistentType"
        assert result["definition"] is None

    def test_define_type_single_struct_roundtrip(self, ctx, open_id, supervisor):
        bv = supervisor.get(open_id).bv
        source = "typedef struct {int x; int y;} Point;"
        result = t_types.define_type(open_id, "Point", source, ctx)
        assert result["name"] == "Point"
        assert result["definition"]

        # get_type retrieves it
        got = t_types.get_type(open_id, "Point", ctx)
        assert got["definition"] is not None
        assert "Point" in got["definition"] or "struct" in got["definition"]

        # Undo entry recorded
        assert len(bv._undo_stack) >= 1
        entry = bv._undo_stack[-1]["entries"][-1]
        assert entry["kind"] == "define_user_type"
        assert entry["type_name"] == "Point"

        # Undo reverts the type definition — get_type should return None after
        t_undo.undo(open_id, ctx)
        assert len(bv._redo_stack) >= 1
        reverted = t_types.get_type(open_id, "Point", ctx)
        assert reverted["definition"] is None

    def test_define_type_multi_source_name_present(self, ctx, open_id):
        source = "typedef struct {int a;} Alpha; typedef struct {int b;} Beta;"
        result = t_types.define_type(open_id, "Alpha", source, ctx)
        assert result["name"] == "Alpha"

    def test_define_type_multi_source_name_absent_raises(self, ctx, open_id):
        from binja_mcp.errors import TYPE_PARSE_ERROR, BinjaError

        source = "typedef struct {int a;} Alpha; typedef struct {int b;} Beta;"
        with pytest.raises(BinjaError) as exc_info:
            t_types.define_type(open_id, "Gamma", source, ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR

    def test_define_type_bad_source_raises(self, ctx, open_id):
        from binja_mcp.errors import TYPE_PARSE_ERROR, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_types.define_type(open_id, "Foo", "this is not c code", ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR

    def test_define_type_empty_name_raises(self, ctx, open_id):
        with pytest.raises(ValueError, match="name must be non-empty"):
            t_types.define_type(open_id, "", "typedef int X;", ctx)

    def test_define_type_empty_source_raises(self, ctx, open_id):
        with pytest.raises(ValueError, match="source must be non-empty"):
            t_types.define_type(open_id, "X", "", ctx)

    def test_type_parse_error_extra_fields(self, ctx, open_id):
        """TYPE_PARSE_ERROR must expose .extra['source'] and a hint."""
        from binja_mcp.errors import TYPE_PARSE_ERROR, BinjaError

        with pytest.raises(BinjaError) as exc_info:
            t_types.define_data_var(open_id, "0x1000", "struct {int x;", ctx)
        err = exc_info.value
        assert err.code == TYPE_PARSE_ERROR
        assert "source" in err.extra
        assert err.extra["source"]  # non-empty
        assert "hint" in err.extra
        assert "C-style" in err.extra["hint"] or "declaration" in err.extra["hint"]


# --- registry sanity --------------------------------------------------------


def test_registry_contains_all_core_tools():
    from binja_mcp.registry import get_registered_tools

    names = {t.name for t in get_registered_tools()}
    expected = {
        "open_binary",
        "close_binary",
        "list_binaries",
        "binary_info",
        "list_functions",
        "decompile",
        "get_il",
        "get_disasm",
        "get_xrefs_to",
        "search_strings",
        "list_segments",
        "list_sections",
        "list_imports",
        "list_exports",
        "undo",
        "redo",
        "begin_undo",
        "commit_undo",
        "list_symbols",
        "rename_symbol",
        "define_data_var",
        "get_type",
        "define_type",
        "get_callers",
        "get_callees",
        "get_call_sites",
    }
    assert expected.issubset(names), f"missing: {expected - names}"
    assert len(names) == 26, f"expected 26 tools, got {len(names)}: {sorted(names)}"
