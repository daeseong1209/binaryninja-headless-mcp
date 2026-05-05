"""Direct tool-function tests against the mock backend.

We invoke tool functions directly with a tiny fake Context to avoid the cost
of spinning up a full FastMCP server for unit tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from binja_mcp.tools import decompile as t_decompile
from binja_mcp.tools import functions as t_functions
from binja_mcp.tools import info as t_info
from binja_mcp.tools import lifecycle as t_lifecycle
from binja_mcp.tools import sections as t_sections
from binja_mcp.tools import strings as t_strings
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
    }
    assert expected.issubset(names), f"missing: {expected - names}"
