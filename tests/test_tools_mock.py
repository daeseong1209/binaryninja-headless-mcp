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
    }
    assert expected.issubset(names), f"missing: {expected - names}"
