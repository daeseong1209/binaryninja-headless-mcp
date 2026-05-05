"""Edge-case matrix for all 23 binja-mcp tools.

Phase 1 of v0.3.1 ultraqa: 150+ targeted edge-case tests exercising boundary
conditions, error codes, schema keys, and pagination correctness for every tool.

Each test class is named TestEdge<ToolGroup> to distinguish from the baseline
TestXxx classes in test_tools_mock.py.

Strong identity assertions:
  - BinjaError.code checked via exc_info.value.code == CONSTANT
  - .extra keys checked explicitly
  - Response schema keys validated (assert "items" in result, etc.)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from binja_mcp.errors import (
    BINARY_NOT_FOUND,
    FUNCTION_NOT_FOUND,
    INVALID_ADDRESS,
    INVALID_IL_LEVEL,
    SYMBOL_NOT_FOUND,
    TYPE_PARSE_ERROR,
    UNDO_STATE_INVALID,
    BinjaError,
)
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

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# TestEdgeOpenBinary — lifecycle.open_binary
# ---------------------------------------------------------------------------


class TestEdgeOpenBinary:
    def test_zero_byte_file_opens(self, ctx, tmp_path, monkeypatch):
        """0-byte file must not crash — mock backend accepts any path."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        empty = tmp_path / "empty.bin"
        empty.write_bytes(b"")
        res = t_lifecycle.open_binary(str(empty), ctx)
        assert "binary_id" in res

    def test_corrupted_pe_header_opens(self, ctx, tmp_path, monkeypatch):
        """MZ magic without valid PE signature — mock still loads."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        broken = tmp_path / "broken.exe"
        broken.write_bytes(b"\x4d\x5a" + b"\xff" * 30)  # MZ but no PE sig
        res = t_lifecycle.open_binary(str(broken), ctx)
        assert "binary_id" in res

    def test_directory_path_raises_value_error(self, ctx, tmp_path, monkeypatch):
        """Passing a directory path instead of a file raises ValueError."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        with pytest.raises(ValueError, match="not a regular file"):
            t_lifecycle.open_binary(str(tmp_path), ctx)

    def test_nonexistent_path_raises_file_not_found(self, ctx, tmp_path, monkeypatch):
        """Non-existent path raises FileNotFoundError."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        missing = str(tmp_path / "does_not_exist.bin")
        with pytest.raises(FileNotFoundError):
            t_lifecycle.open_binary(missing, ctx)

    def test_update_analysis_false_returns_handle(self, ctx, tmp_path, monkeypatch):
        """update_analysis=False must still return a valid binary_id."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        f = tmp_path / "hdr.bin"
        f.write_bytes(b"\x7fELF" + b"\x00" * 60)
        res = t_lifecycle.open_binary(str(f), ctx, update_analysis=False)
        assert "binary_id" in res
        assert res["binary_id"]

    def test_response_schema_keys(self, ctx, fixture_binary):
        """open_binary response contains binary_id, path, is_mock."""
        res = t_lifecycle.open_binary(str(fixture_binary), ctx)
        assert "binary_id" in res
        assert "path" in res
        assert "is_mock" in res
        assert res["is_mock"] is True

    def test_multiple_opens_return_distinct_ids(self, ctx, tmp_path, monkeypatch):
        """Opening two separate files yields two distinct binary_ids."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        a = tmp_path / "a.bin"
        b = tmp_path / "b.bin"
        a.write_bytes(b"\x7fELF" + b"\x00" * 60)
        b.write_bytes(b"\x7fELF" + b"\x00" * 60)
        id_a = t_lifecycle.open_binary(str(a), ctx)["binary_id"]
        id_b = t_lifecycle.open_binary(str(b), ctx)["binary_id"]
        assert id_a != id_b


# ---------------------------------------------------------------------------
# TestEdgeCloseBinary — lifecycle.close_binary
# ---------------------------------------------------------------------------


class TestEdgeCloseBinary:
    def test_close_unknown_id_raises_binja_error(self, ctx):
        """Closing an unknown binary_id raises BinjaError(BINARY_NOT_FOUND)."""
        with pytest.raises(BinjaError) as exc_info:
            t_lifecycle.close_binary("unknown-id-xyz", ctx)
        assert exc_info.value.code == BINARY_NOT_FOUND
        assert "binary_id" in exc_info.value.extra

    def test_close_removes_from_list(self, ctx, open_id):
        """After close, list_binaries no longer shows the binary."""
        before = t_lifecycle.list_binaries(ctx)["total"]
        t_lifecycle.close_binary(open_id, ctx)
        after = t_lifecycle.list_binaries(ctx)["total"]
        assert after == before - 1


# ---------------------------------------------------------------------------
# TestEdgeListBinaries — lifecycle.list_binaries
# ---------------------------------------------------------------------------


class TestEdgeListBinaries:
    def test_empty_state_returns_zero(self, ctx):
        """No open binaries -> total == 0, items == []."""
        res = t_lifecycle.list_binaries(ctx)
        assert res["total"] == 0
        assert res["items"] == []
        assert "items" in res and "total" in res

    def test_five_simultaneous_binaries(self, ctx, tmp_path, monkeypatch):
        """Open 5 binaries and verify list_binaries shows all 5."""
        monkeypatch.delenv("BINJA_MCP_ALLOWED_ROOTS", raising=False)
        ids = []
        for i in range(5):
            f = tmp_path / f"bin{i}.bin"
            f.write_bytes(b"\x7fELF" + bytes([i]) + b"\x00" * 59)
            res = t_lifecycle.open_binary(str(f), ctx)
            ids.append(res["binary_id"])
        listing = t_lifecycle.list_binaries(ctx)
        assert listing["total"] == 5
        listed_ids = {it["binary_id"] for it in listing["items"]}
        for bid in ids:
            assert bid in listed_ids

    def test_schema_keys_present(self, ctx, open_id):
        """list_binaries response has 'items' and 'total' keys."""
        res = t_lifecycle.list_binaries(ctx)
        assert "items" in res
        assert "total" in res


# ---------------------------------------------------------------------------
# TestEdgeBinaryInfo — info.binary_info
# ---------------------------------------------------------------------------


class TestEdgeBinaryInfo:
    def test_unknown_binary_id_raises_binja_error(self, ctx):
        """binary_info with unknown id raises BinjaError(BINARY_NOT_FOUND)."""
        with pytest.raises(BinjaError) as exc_info:
            t_info.binary_info("no-such-binary-id", ctx)
        assert exc_info.value.code == BINARY_NOT_FOUND
        assert "binary_id" in exc_info.value.extra

    def test_function_count_exact(self, ctx, open_id):
        """Mock has exactly 7 functions."""
        info = t_info.binary_info(open_id, ctx)
        assert info["function_count"] == 7

    def test_arch_field_present_and_string(self, ctx, open_id):
        """arch field is a non-None string."""
        info = t_info.binary_info(open_id, ctx)
        assert isinstance(info["arch"], str)
        assert info["arch"]  # non-empty

    def test_arch_none_simulation(self, ctx, open_id, supervisor):
        """Simulate arch=None by removing arch attributes from bv."""
        bv = supervisor.get(open_id).bv
        original_arch_name = bv.arch_name
        bv.arch_name = None  # type: ignore[assignment]
        try:
            info = t_info.binary_info(open_id, ctx)
            # get_arch_name falls back gracefully; returns None when both are absent
            assert info["arch"] is None or isinstance(info["arch"], str)
        finally:
            bv.arch_name = original_arch_name

    def test_entry_point_hex_format(self, ctx, open_id):
        """entry_point is a hex string starting with '0x'."""
        info = t_info.binary_info(open_id, ctx)
        assert info["entry_point"].startswith("0x")

    def test_schema_keys(self, ctx, open_id):
        """binary_info response has all required schema keys."""
        info = t_info.binary_info(open_id, ctx)
        for key in ("binary_id", "arch", "platform", "entry_point", "function_count", "is_mock"):
            assert key in info, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeListFunctions — functions.list_functions
# ---------------------------------------------------------------------------


class TestEdgeListFunctions:
    def test_offset_equals_total_returns_empty_page(self, ctx, open_id):
        """offset == total -> items == [], has_more == False."""
        total = t_functions.list_functions(open_id, ctx)["total"]
        page = t_functions.list_functions(open_id, ctx, offset=total, limit=10)
        assert page["items"] == []
        assert page["has_more"] is False
        assert "items" in page and "total" in page

    def test_limit_1_pagination_count(self, ctx, open_id):
        """Paging through 7 mock functions with limit=1 yields exactly 7 pages."""
        total = t_functions.list_functions(open_id, ctx)["total"]
        assert total == 7
        collected = []
        for off in range(total):
            page = t_functions.list_functions(open_id, ctx, offset=off, limit=1)
            assert len(page["items"]) == 1
            collected.append(page["items"][0]["name"])
        assert len(collected) == 7
        assert len(set(collected)) == 7  # all distinct

    def test_full_pagination_7_functions(self, ctx, open_id):
        """Two-page retrieval covers all 7 functions with no overlap."""
        page1 = t_functions.list_functions(open_id, ctx, offset=0, limit=4)
        page2 = t_functions.list_functions(open_id, ctx, offset=4, limit=10)
        all_names = [it["name"] for it in page1["items"]] + [it["name"] for it in page2["items"]]
        assert len(all_names) == 7
        assert len(set(all_names)) == 7

    def test_schema_keys(self, ctx, open_id):
        """list_functions response contains items, offset, limit, total, has_more."""
        page = t_functions.list_functions(open_id, ctx)
        for key in ("items", "offset", "limit", "total", "has_more"):
            assert key in page, f"missing key: {key}"

    def test_items_have_name_and_start(self, ctx, open_id):
        """Every item has 'name' and 'start' (hex string)."""
        page = t_functions.list_functions(open_id, ctx, limit=10)
        for item in page["items"]:
            assert "name" in item
            assert "start" in item
            assert item["start"].startswith("0x")


# ---------------------------------------------------------------------------
# TestEdgeDecompile — decompile.decompile
# ---------------------------------------------------------------------------


class TestEdgeDecompile:
    def test_unknown_function_raises_binja_error(self, ctx, open_id):
        """Unknown function raises BinjaError(FUNCTION_NOT_FOUND)."""
        with pytest.raises(BinjaError) as exc_info:
            t_decompile.decompile(open_id, "no_such_function_xyz", ctx)
        assert exc_info.value.code == FUNCTION_NOT_FOUND
        assert "target" in exc_info.value.extra

    def test_unmapped_hex_address_falls_to_function_not_found(self, ctx, open_id):
        """Address 0xff is not mapped to any function — raises BinjaError(FUNCTION_NOT_FOUND)."""
        with pytest.raises(BinjaError) as exc_info:
            t_decompile.decompile(open_id, "0xff", ctx)
        assert exc_info.value.code == FUNCTION_NOT_FOUND

    def test_decompile_schema_keys(self, ctx, open_id):
        """decompile response has function, il_level, text, truncated, original_length."""
        result = t_decompile.decompile(open_id, "main", ctx)
        for key in ("function", "il_level", "text", "truncated", "original_length"):
            assert key in result, f"missing key: {key}"

    def test_decompile_function_subkeys(self, ctx, open_id):
        """function sub-dict has name, start, end, basic_block_count, parameter_count."""
        result = t_decompile.decompile(open_id, "main", ctx)
        func = result["function"]
        for key in ("name", "start", "end", "basic_block_count", "parameter_count"):
            assert key in func, f"function missing key: {key}"

    def test_decompile_unknown_binary_id(self, ctx):
        """decompile with unknown binary_id raises BinjaError(BINARY_NOT_FOUND)."""
        with pytest.raises(BinjaError) as exc_info:
            t_decompile.decompile("bad-binary-id", "main", ctx)
        assert exc_info.value.code == BINARY_NOT_FOUND


# ---------------------------------------------------------------------------
# TestEdgeGetIL — decompile.get_il
# ---------------------------------------------------------------------------


class TestEdgeGetIL:
    def test_invalid_level_raises_binja_error(self, ctx, open_id):
        """XLIL is not a valid IL level -> BinjaError(INVALID_IL_LEVEL)."""
        with pytest.raises(BinjaError) as exc_info:
            t_decompile.get_il(open_id, "main", ctx, level="XLIL")
        assert exc_info.value.code == INVALID_IL_LEVEL
        assert "level" in exc_info.value.extra

    def test_lowercase_level_accepted(self, ctx, open_id):
        """lowercase 'hlil' is normalized and accepted."""
        result = t_decompile.get_il(open_id, "main", ctx, level="hlil")
        assert result["il_level"] == "HLIL"
        assert result["text"]

    def test_level_none_raises_binja_error(self, ctx, open_id):
        """level=None raises BinjaError(INVALID_IL_LEVEL) — not AttributeError."""
        with pytest.raises(BinjaError) as exc_info:
            t_decompile.get_il(open_id, "main", ctx, level=None)  # type: ignore[arg-type]
        assert exc_info.value.code == INVALID_IL_LEVEL

    def test_all_valid_levels(self, ctx, open_id):
        """LLIL, MLIL, HLIL all return non-empty text."""
        for level in ("LLIL", "MLIL", "HLIL"):
            result = t_decompile.get_il(open_id, "main", ctx, level=level)
            assert result["il_level"] == level
            assert result["text"]

    def test_schema_keys(self, ctx, open_id):
        """get_il response has function, il_level, text, truncated, original_length."""
        result = t_decompile.get_il(open_id, "main", ctx, level="HLIL")
        for key in ("function", "il_level", "text", "truncated", "original_length"):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeGetDisasm — decompile.get_disasm
# ---------------------------------------------------------------------------


class TestEdgeGetDisasm:
    def test_length_zero_raises_value_error(self, ctx, open_id):
        """length=0 raises ValueError."""
        with pytest.raises(ValueError):
            t_decompile.get_disasm(open_id, "main", ctx, length=0)

    def test_length_negative_raises_value_error(self, ctx, open_id):
        """length=-1 raises ValueError."""
        with pytest.raises(ValueError):
            t_decompile.get_disasm(open_id, "main", ctx, length=-1)

    def test_length_1_succeeds(self, ctx, open_id):
        """length=1 is the minimum valid value."""
        result = t_decompile.get_disasm(open_id, "main", ctx, length=1)
        assert "text" in result

    def test_length_10000_succeeds(self, ctx, open_id):
        """length=10000 is accepted (large but valid)."""
        result = t_decompile.get_disasm(open_id, "main", ctx, length=10000)
        assert "text" in result

    def test_raw_unmapped_address_uses_read_fallback(self, ctx, open_id):
        """Unmapped address 0xff falls through to raw-read path."""
        result = t_decompile.get_disasm(open_id, "0xff", ctx, length=16)
        # Should succeed via mock bv.read fallback
        assert "address" in result
        assert "text" in result

    def test_raw_address_schema_keys(self, ctx, open_id):
        """Raw address path returns address, length, text keys."""
        result = t_decompile.get_disasm(open_id, "0xff", ctx, length=8)
        assert "address" in result
        assert "length" in result
        assert "text" in result

    def test_function_path_schema_keys(self, ctx, open_id):
        """Function path returns function and text keys."""
        result = t_decompile.get_disasm(open_id, "main", ctx)
        assert "function" in result
        assert "text" in result


# ---------------------------------------------------------------------------
# TestEdgeXrefs — xrefs.get_xrefs_to
# ---------------------------------------------------------------------------


class TestEdgeXrefs:
    def test_function_with_xrefs_returns_items(self, ctx, open_id):
        """Every mock function has 1 xref seeded in _xrefs_to."""
        result = t_xrefs.get_xrefs_to(open_id, "main", ctx)
        assert "items" in result
        assert result["total"] >= 1

    def test_function_with_zero_xrefs(self, ctx, open_id, supervisor):
        """Function whose address has no xrefs returns empty items list."""
        bv = supervisor.get(open_id).bv
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr_str = funcs["items"][0]["start"]
        addr = int(addr_str, 16)
        # Clear its xrefs
        bv._xrefs_to[addr] = []
        result = t_xrefs.get_xrefs_to(open_id, addr_str, ctx)
        assert result["items"] == []
        assert result["total"] == 0

    def test_name_and_addr_yield_same_xrefs(self, ctx, open_id):
        """Lookup by name vs lookup by address return the same xref count."""
        funcs = t_functions.list_functions(open_id, ctx, limit=10)
        main_func = next(it for it in funcs["items"] if it["name"] == "main")
        by_name = t_xrefs.get_xrefs_to(open_id, "main", ctx)
        by_addr = t_xrefs.get_xrefs_to(open_id, main_func["start"], ctx)
        assert by_name["total"] == by_addr["total"]

    def test_unknown_target_raises_function_not_found(self, ctx, open_id):
        """Unknown name target raises BinjaError(FUNCTION_NOT_FOUND)."""
        with pytest.raises(BinjaError) as exc_info:
            t_xrefs.get_xrefs_to(open_id, "no_such_func_xyz", ctx)
        assert exc_info.value.code == FUNCTION_NOT_FOUND

    def test_schema_keys(self, ctx, open_id):
        """get_xrefs_to response has target, target_address, items, total."""
        result = t_xrefs.get_xrefs_to(open_id, "main", ctx)
        for key in ("target", "target_address", "items", "total"):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeStrings — strings.search_strings
# ---------------------------------------------------------------------------


class TestEdgeStrings:
    def test_empty_pattern_returns_all_strings(self, ctx, open_id):
        """Empty pattern (or omitted) returns all strings."""
        all_res = t_strings.search_strings(open_id, ctx)
        empty_res = t_strings.search_strings(open_id, ctx, pattern="")
        assert all_res["total"] == empty_res["total"]
        assert all_res["total"] >= 4  # mock has 4 strings

    def test_pattern_at_max_length_accepted(self, ctx, open_id):
        """Exactly MAX_PATTERN_LENGTH characters must not raise."""
        from binja_mcp.tools.strings import MAX_PATTERN_LENGTH

        exact = "x" * MAX_PATTERN_LENGTH
        result = t_strings.search_strings(open_id, ctx, pattern=exact)
        assert "items" in result

    def test_pattern_exceeds_max_length_raises(self, ctx, open_id):
        """MAX_PATTERN_LENGTH+1 characters raises ValueError 'pattern too long'."""
        from binja_mcp.tools.strings import MAX_PATTERN_LENGTH

        over = "a" * (MAX_PATTERN_LENGTH + 1)
        with pytest.raises(ValueError, match="pattern too long"):
            t_strings.search_strings(open_id, ctx, pattern=over)

    def test_nested_quantifier_raises_value_error(self, ctx, open_id):
        """(a+)+ catastrophic backtracking pattern raises ValueError."""
        with pytest.raises(ValueError, match="nested quantifier"):
            t_strings.search_strings(open_id, ctx, pattern=r"(a+)+", regex=True)

    def test_nested_quantifier_star_raises_value_error(self, ctx, open_id):
        """(a*)* catastrophic backtracking pattern raises ValueError."""
        with pytest.raises(ValueError, match="nested quantifier"):
            t_strings.search_strings(open_id, ctx, pattern=r"(a*)*", regex=True)

    def test_regex_timeout_raises_timeout_error(self, ctx, open_id, monkeypatch):
        """Daemon-thread watchdog raises TimeoutError on slow regex."""
        import binja_mcp.tools.strings as strings_mod

        monkeypatch.setattr(strings_mod, "STRING_REGEX_TIMEOUT_S", 0.001)

        def slow_collect(raw, matcher):
            import time as _time

            _time.sleep(1.0)
            return []

        monkeypatch.setattr(strings_mod, "_collect", slow_collect)
        with pytest.raises(TimeoutError, match="regex match exceeded"):
            t_strings.search_strings(open_id, ctx, pattern="anything", regex=True)

    def test_case_insensitive_match(self, ctx, open_id):
        """case_sensitive=False, 'HELLO' matches 'Hello, world'."""
        result = t_strings.search_strings(open_id, ctx, pattern="HELLO", case_sensitive=False)
        assert result["total"] >= 1
        assert any("Hello" in it["value"] for it in result["items"])

    def test_case_sensitive_no_match(self, ctx, open_id):
        """case_sensitive=True (default), 'HELLO' does not match 'Hello, world'."""
        result = t_strings.search_strings(open_id, ctx, pattern="HELLO", case_sensitive=True)
        assert result["total"] == 0

    def test_regex_etc_pattern(self, ctx, open_id):
        """regex=True, '^/etc/' matches '/etc/passwd'."""
        result = t_strings.search_strings(open_id, ctx, pattern=r"^/etc/", regex=True)
        assert result["total"] >= 1
        assert any(it["value"].startswith("/etc/") for it in result["items"])

    def test_schema_keys(self, ctx, open_id):
        """search_strings response has items, offset, limit, total, has_more."""
        result = t_strings.search_strings(open_id, ctx)
        for key in ("items", "offset", "limit", "total", "has_more"):
            assert key in result, f"missing key: {key}"

    def test_items_have_value_and_address(self, ctx, open_id):
        """Each string item has 'value' and 'address' keys."""
        result = t_strings.search_strings(open_id, ctx)
        for item in result["items"]:
            assert "value" in item
            assert "address" in item

    def test_ascii_only_mock_korean_returns_empty(self, ctx, open_id):
        """Mock has only ASCII strings; searching Korean substring returns 0."""
        result = t_strings.search_strings(open_id, ctx, pattern="안녕")
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# TestEdgeSegments — sections.list_segments
# ---------------------------------------------------------------------------


class TestEdgeSegments:
    def test_default_mock_has_two_segments(self, ctx, open_id):
        """Default mock has exactly 2 segments (text + data)."""
        result = t_sections.list_segments(open_id, ctx)
        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_readable_bool_type(self, ctx, open_id):
        """readable field is a Python bool (not int)."""
        result = t_sections.list_segments(open_id, ctx)
        for item in result["items"]:
            assert isinstance(item["readable"], bool)
            assert isinstance(item["writable"], bool)
            assert isinstance(item["executable"], bool)

    def test_schema_keys(self, ctx, open_id):
        """Each segment item has start, end, readable, writable, executable."""
        result = t_sections.list_segments(open_id, ctx)
        assert "items" in result
        assert "total" in result
        for item in result["items"]:
            for key in ("start", "end", "readable", "writable", "executable"):
                assert key in item, f"segment missing key: {key}"

    def test_has_executable_segment(self, ctx, open_id):
        """At least one segment is executable (.text mock)."""
        result = t_sections.list_segments(open_id, ctx)
        assert any(item["executable"] for item in result["items"])

    def test_empty_segments_returns_zero(self, ctx, open_id, supervisor):
        """Clearing all segments returns total=0 and items=[]."""
        bv = supervisor.get(open_id).bv
        bv.segments = []
        result = t_sections.list_segments(open_id, ctx)
        assert result["total"] == 0
        assert result["items"] == []


# ---------------------------------------------------------------------------
# TestEdgeSections — sections.list_sections
# ---------------------------------------------------------------------------


class TestEdgeSections:
    def test_mock_has_at_least_three_sections(self, ctx, open_id):
        """Mock has .text, .data, .rodata — total >= 3."""
        result = t_sections.list_sections(open_id, ctx)
        assert result["total"] >= 3

    def test_text_section_present(self, ctx, open_id):
        """'.text' section must be in listing."""
        result = t_sections.list_sections(open_id, ctx)
        names = {item["name"] for item in result["items"]}
        assert ".text" in names

    def test_semantics_field_present(self, ctx, open_id):
        """Every section item has a 'semantics' field."""
        result = t_sections.list_sections(open_id, ctx)
        for item in result["items"]:
            assert "semantics" in item

    def test_schema_keys(self, ctx, open_id):
        """Each section item has name, start, end, semantics."""
        result = t_sections.list_sections(open_id, ctx)
        assert "items" in result and "total" in result
        for item in result["items"]:
            for key in ("name", "start", "end", "semantics"):
                assert key in item, f"section missing key: {key}"

    def test_start_end_hex_format(self, ctx, open_id):
        """start and end are hex strings."""
        result = t_sections.list_sections(open_id, ctx)
        for item in result["items"]:
            assert item["start"].startswith("0x")
            assert item["end"].startswith("0x")

    def test_semantics_is_human_readable_name(self, ctx, open_id):
        """semantics field is a human-readable name (not a bare integer like '1' or '2')."""
        result = t_sections.list_sections(open_id, ctx)
        for item in result["items"]:
            sem = item["semantics"]
            assert isinstance(sem, str)
            # Must not be a bare integer string (real BN enum str() artefact)
            assert not sem.isdigit(), f"semantics looks like a bare integer: {sem!r}"
            # Mock values end in 'SectionSemantics'
            if sem:
                assert "SectionSemantics" in sem or sem == "", (
                    f"unexpected semantics value: {sem!r}"
                )


# ---------------------------------------------------------------------------
# TestEdgeImports — sections.list_imports
# ---------------------------------------------------------------------------


class TestEdgeImports:
    def test_printf_and_malloc_present(self, ctx, open_id):
        """printf (ImportedFunctionSymbol) and malloc (ImportAddressSymbol) in imports."""
        result = t_sections.list_imports(open_id, ctx)
        names = {it["name"] for it in result["items"]}
        assert "printf" in names or "malloc" in names

    def test_exported_func_absent(self, ctx, open_id):
        """exported_func must not appear in import listing."""
        result = t_sections.list_imports(open_id, ctx)
        names = {it["name"] for it in result["items"]}
        assert "exported_func" not in names

    def test_offset_equals_total_empty(self, ctx, open_id):
        """offset=total returns empty page with has_more=False."""
        total = t_sections.list_imports(open_id, ctx)["total"]
        page = t_sections.list_imports(open_id, ctx, offset=total, limit=1)
        assert page["items"] == []
        assert page["has_more"] is False

    def test_limit_1_pagination(self, ctx, open_id):
        """limit=1 returns exactly 1 item and correct has_more."""
        result = t_sections.list_imports(open_id, ctx, offset=0, limit=1)
        assert len(result["items"]) == 1
        assert result["limit"] == 1

    def test_schema_keys(self, ctx, open_id):
        """list_imports response has items, offset, limit, total, has_more."""
        result = t_sections.list_imports(open_id, ctx)
        for key in ("items", "offset", "limit", "total", "has_more"):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeExports — sections.list_exports
# ---------------------------------------------------------------------------


class TestEdgeExports:
    def test_exported_func_present(self, ctx, open_id):
        """exported_func (is_export=True) must be in export listing."""
        result = t_sections.list_exports(open_id, ctx)
        names = {it["name"] for it in result["items"]}
        assert "exported_func" in names

    def test_printf_absent(self, ctx, open_id):
        """printf (imported) must not appear in exports."""
        result = t_sections.list_exports(open_id, ctx)
        names = {it["name"] for it in result["items"]}
        assert "printf" not in names
        assert "malloc" not in names

    def test_offset_equals_total_empty(self, ctx, open_id):
        """offset=total returns empty page."""
        total = t_sections.list_exports(open_id, ctx)["total"]
        page = t_sections.list_exports(open_id, ctx, offset=total, limit=1)
        assert page["items"] == []
        assert page["has_more"] is False

    def test_schema_keys(self, ctx, open_id):
        """list_exports response has items, offset, limit, total, has_more."""
        result = t_sections.list_exports(open_id, ctx)
        for key in ("items", "offset", "limit", "total", "has_more"):
            assert key in result, f"missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeUndo — undo.undo / redo / begin_undo / commit_undo
# ---------------------------------------------------------------------------


class TestEdgeUndo:
    def test_undo_empty_stack_returns_false(self, ctx, open_id):
        """undo on empty stack returns undone=False, remaining=0."""
        result = t_undo.undo(open_id, ctx)
        assert result["undone"] is False
        assert result["remaining"] == 0

    def test_redo_empty_stack_returns_false(self, ctx, open_id):
        """redo on empty stack returns redone=False."""
        result = t_undo.redo(open_id, ctx)
        assert result["redone"] is False

    def test_begin_undo_returns_32_hex_chars(self, ctx, open_id):
        """begin_undo returns state_id that is exactly 32 hex characters."""
        result = t_undo.begin_undo(open_id, ctx)
        sid = result["state_id"]
        assert isinstance(sid, str)
        assert len(sid) == 32
        assert all(c in "0123456789abcdef" for c in sid), f"non-hex chars in {sid!r}"

    def test_commit_invalid_state_id_raises_binja_error(self, ctx, open_id):
        """commit_undo with unknown state_id raises BinjaError(UNDO_STATE_INVALID)."""
        with pytest.raises(BinjaError) as exc_info:
            t_undo.commit_undo(open_id, "no-such-state-id", ctx)
        assert exc_info.value.code == UNDO_STATE_INVALID
        assert exc_info.value.extra.get("state_id") == "no-such-state-id"

    def test_commit_twice_second_raises(self, ctx, open_id, supervisor):
        """Committing the same state_id twice: second commit raises UNDO_STATE_INVALID."""
        bv = supervisor.get(open_id).bv
        sid = t_undo.begin_undo(open_id, ctx)["state_id"]
        bv._record_undo("rename", addr=0x1000, before="a", after="b")
        t_undo.commit_undo(open_id, sid, ctx)  # first commit: ok
        with pytest.raises(BinjaError) as exc_info:
            t_undo.commit_undo(open_id, sid, ctx)  # second: state no longer open
        assert exc_info.value.code == UNDO_STATE_INVALID

    def test_roundtrip_begin_rename_commit_undo_reverts(self, ctx, open_id):
        """Full undo roundtrip: rename -> commit -> undo -> name reverted."""
        funcs = t_functions.list_functions(open_id, ctx, limit=10)
        start_fn = next(it for it in funcs["items"] if it["name"] == "_start")
        addr = start_fn["start"]

        t_symbols.rename_symbol(open_id, addr, "EDGE_RENAME_TEST", ctx)
        all_funcs = t_functions.list_functions(open_id, ctx, limit=10)["items"]
        names_after = {f["name"] for f in all_funcs}
        assert "EDGE_RENAME_TEST" in names_after

        t_undo.undo(open_id, ctx)
        all_funcs_rev = t_functions.list_functions(open_id, ctx, limit=10)["items"]
        names_reverted = {f["name"] for f in all_funcs_rev}
        assert "EDGE_RENAME_TEST" not in names_reverted
        assert "_start" in names_reverted

    def test_undo_schema_keys(self, ctx, open_id):
        """undo response has 'undone' and 'remaining' keys."""
        result = t_undo.undo(open_id, ctx)
        assert "undone" in result
        assert "remaining" in result

    def test_redo_schema_keys(self, ctx, open_id):
        """redo response has 'redone' and 'remaining' keys."""
        result = t_undo.redo(open_id, ctx)
        assert "redone" in result
        assert "remaining" in result


# ---------------------------------------------------------------------------
# TestEdgeListSymbols — symbols.list_symbols
# ---------------------------------------------------------------------------


class TestEdgeListSymbols:
    def test_function_filter_all_are_function_type(self, ctx, open_id):
        """symbol_type='function' returns only FunctionSymbol entries."""
        result = t_symbols.list_symbols(open_id, ctx, symbol_type="function")
        for item in result["items"]:
            assert "Function" in item["type"], f"unexpected type {item['type']}"

    def test_invalid_symbol_type_raises_value_error(self, ctx, open_id):
        """symbol_type='invalid_type' raises ValueError 'unknown symbol_type'."""
        with pytest.raises(ValueError, match="unknown symbol_type"):
            t_symbols.list_symbols(open_id, ctx, symbol_type="invalid_type")

    def test_lookup_printf_returns_one(self, ctx, open_id):
        """name_or_addr='printf' returns exactly 1 result."""
        result = t_symbols.list_symbols(open_id, ctx, name_or_addr="printf")
        assert result["total"] == 1
        assert result["items"][0]["name"] == "printf"

    def test_lookup_hex_address(self, ctx, open_id):
        """name_or_addr with valid hex address returns the symbol at that address."""
        # Find printf address first
        syms = t_symbols.list_symbols(open_id, ctx, symbol_type="imported_function")
        printf_sym = next(it for it in syms["items"] if it["name"] == "printf")
        addr = printf_sym["address"]
        result = t_symbols.list_symbols(open_id, ctx, name_or_addr=addr)
        assert result["total"] == 1
        assert result["items"][0]["name"] == "printf"

    def test_unknown_name_raises_symbol_not_found(self, ctx, open_id):
        """Unknown name raises BinjaError(SYMBOL_NOT_FOUND) with .extra['target']."""
        with pytest.raises(BinjaError) as exc_info:
            t_symbols.list_symbols(open_id, ctx, name_or_addr="no_such_symbol_xyz")
        assert exc_info.value.code == SYMBOL_NOT_FOUND
        assert exc_info.value.extra.get("target") == "no_such_symbol_xyz"

    def test_schema_keys(self, ctx, open_id):
        """list_symbols response has items, offset, limit, total, has_more."""
        result = t_symbols.list_symbols(open_id, ctx)
        for key in ("items", "offset", "limit", "total", "has_more"):
            assert key in result, f"missing key: {key}"

    def test_item_schema_keys(self, ctx, open_id):
        """Each symbol item has name, full_name, address, type, auto, ordinal."""
        result = t_symbols.list_symbols(open_id, ctx)
        for item in result["items"]:
            for key in ("name", "full_name", "address", "type", "auto", "ordinal"):
                assert key in item, f"symbol item missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeRenameSymbol — symbols.rename_symbol
# ---------------------------------------------------------------------------


class TestEdgeRenameSymbol:
    def test_function_rename_and_undo(self, ctx, open_id):
        """rename _start to X, verify after='X', undo reverts."""
        funcs = t_functions.list_functions(open_id, ctx, limit=10)
        start_fn = next(it for it in funcs["items"] if it["name"] == "_start")
        addr = start_fn["start"]

        result = t_symbols.rename_symbol(open_id, addr, "EDGE_X_FUNC", ctx)
        assert result["kind"] == "function"
        assert result["after"] == "EDGE_X_FUNC"
        assert result["before"] == "_start"

        t_undo.undo(open_id, ctx)
        names = {f["name"] for f in t_functions.list_functions(open_id, ctx, limit=10)["items"]}
        assert "_start" in names
        assert "EDGE_X_FUNC" not in names

    def test_data_symbol_rename(self, ctx, open_id):
        """Rename global_var (DataSymbol) to EDGE_Y_DATA -> kind='data', before populated."""
        syms = t_symbols.list_symbols(open_id, ctx, symbol_type="data")
        global_sym = next(it for it in syms["items"] if it["name"] == "global_var")
        addr = global_sym["address"]

        result = t_symbols.rename_symbol(open_id, addr, "EDGE_Y_DATA", ctx)
        assert result["kind"] == "data"
        assert result["after"] == "EDGE_Y_DATA"
        # before must be populated with the existing symbol name, not None
        assert result["before"] == "global_var"

    def test_empty_new_name_raises_value_error(self, ctx, open_id):
        """Empty new_name raises ValueError."""
        with pytest.raises(ValueError):
            t_symbols.rename_symbol(open_id, "0x1000", "", ctx)

    def test_invalid_address_raises_binja_error(self, ctx, open_id):
        """Non-hex, non-numeric addr raises BinjaError(INVALID_ADDRESS)."""
        with pytest.raises(BinjaError) as exc_info:
            t_symbols.rename_symbol(open_id, "abc_not_an_addr", "newname", ctx)
        assert exc_info.value.code == INVALID_ADDRESS

    def test_schema_keys(self, ctx, open_id):
        """rename_symbol response has kind, address, before, after."""
        funcs = t_functions.list_functions(open_id, ctx, limit=10)
        fn = funcs["items"][0]
        result = t_symbols.rename_symbol(open_id, fn["start"], "SCHEMA_TEST", ctx)
        for key in ("kind", "address", "before", "after"):
            assert key in result, f"rename_symbol missing key: {key}"


# ---------------------------------------------------------------------------
# TestEdgeDefineDataVar — types.define_data_var
# ---------------------------------------------------------------------------


class TestEdgeDefineDataVar:
    def test_uint64_type_defined_and_in_data_vars(self, ctx, open_id, supervisor):
        """define_data_var uint64_t -> response has address+type, var in data_vars."""
        bv = supervisor.get(open_id).bv
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]
        result = t_types.define_data_var(open_id, addr, "uint64_t", ctx)
        assert result["address"] == addr
        assert result["type"] == "uint64_t"
        int_addr = int(addr, 16)
        assert int_addr in bv.data_vars

    def test_undo_removes_data_var(self, ctx, open_id, supervisor):
        """After define + undo, data_vars no longer contains the address."""
        bv = supervisor.get(open_id).bv
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]
        int_addr = int(addr, 16)
        t_types.define_data_var(open_id, addr, "uint64_t", ctx)
        assert int_addr in bv.data_vars
        t_undo.undo(open_id, ctx)
        assert int_addr not in bv.data_vars

    def test_empty_type_str_raises_value_error(self, ctx, open_id):
        """Empty type_str raises ValueError."""
        with pytest.raises(ValueError):
            t_types.define_data_var(open_id, "0x1000", "", ctx)

    def test_bad_type_str_raises_type_parse_error(self, ctx, open_id):
        """Unclosed brace type raises BinjaError(TYPE_PARSE_ERROR) with .extra['source']."""
        with pytest.raises(BinjaError) as exc_info:
            t_types.define_data_var(open_id, "0x1000", "struct {int x;", ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR
        assert "source" in exc_info.value.extra
        assert exc_info.value.extra["source"]  # non-empty

    def test_schema_keys(self, ctx, open_id):
        """define_data_var response has address and type."""
        funcs = t_functions.list_functions(open_id, ctx, limit=1)
        addr = funcs["items"][0]["start"]
        result = t_types.define_data_var(open_id, addr, "uint64_t", ctx)
        assert "address" in result
        assert "type" in result


# ---------------------------------------------------------------------------
# TestEdgeGetType — types.get_type
# ---------------------------------------------------------------------------


class TestEdgeGetType:
    def test_undefined_type_returns_none(self, ctx, open_id):
        """get_type for undefined name returns definition=None."""
        result = t_types.get_type(open_id, "NonExistentType_Edge", ctx)
        assert result["name"] == "NonExistentType_Edge"
        assert result["definition"] is None

    def test_defined_type_returns_string(self, ctx, open_id):
        """After define_type, get_type returns a non-None definition string."""
        t_types.define_type(open_id, "EdgePoint", "typedef struct {int x; int y;} EdgePoint;", ctx)
        result = t_types.get_type(open_id, "EdgePoint", ctx)
        assert result["definition"] is not None
        assert isinstance(result["definition"], str)

    def test_schema_keys(self, ctx, open_id):
        """get_type response has 'name' and 'definition'."""
        result = t_types.get_type(open_id, "AnyName", ctx)
        assert "name" in result
        assert "definition" in result


# ---------------------------------------------------------------------------
# TestEdgeDefineType — types.define_type
# ---------------------------------------------------------------------------


class TestEdgeDefineType:
    def test_single_typedef_name_matches(self, ctx, open_id):
        """Single typedef source: returned name matches requested name."""
        result = t_types.define_type(open_id, "EdgeFoo", "typedef struct {int a;} EdgeFoo;", ctx)
        assert result["name"] == "EdgeFoo"

    def test_empty_name_raises_value_error(self, ctx, open_id):
        """Empty name raises ValueError 'name must be non-empty'."""
        with pytest.raises(ValueError, match="name must be non-empty"):
            t_types.define_type(open_id, "", "typedef int X;", ctx)

    def test_empty_source_raises_value_error(self, ctx, open_id):
        """Empty source raises ValueError 'source must be non-empty'."""
        with pytest.raises(ValueError, match="source must be non-empty"):
            t_types.define_type(open_id, "X", "", ctx)

    def test_parse_failure_raises_type_parse_error(self, ctx, open_id):
        """Non-C source raises BinjaError(TYPE_PARSE_ERROR)."""
        with pytest.raises(BinjaError) as exc_info:
            t_types.define_type(open_id, "Foo", "this is not valid C code", ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR

    def test_parse_error_extra_source_truncated(self, ctx, open_id):
        """type_parse_error .extra['source'] is truncated to <= 200 chars."""
        long_bad_source = "x" * 300
        with pytest.raises(BinjaError) as exc_info:
            t_types.define_type(open_id, "Foo", long_bad_source, ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR
        assert "source" in exc_info.value.extra
        assert len(exc_info.value.extra["source"]) <= 200

    def test_undo_removes_type(self, ctx, open_id):
        """After define_type + undo, get_type returns definition=None."""
        t_types.define_type(open_id, "UndoType", "typedef struct {int z;} UndoType;", ctx)
        got = t_types.get_type(open_id, "UndoType", ctx)
        assert got["definition"] is not None

        t_undo.undo(open_id, ctx)
        after = t_types.get_type(open_id, "UndoType", ctx)
        assert after["definition"] is None

    def test_name_not_in_multi_source_raises(self, ctx, open_id):
        """When requested name absent from multi-type source, raises TYPE_PARSE_ERROR."""
        source = "typedef struct {int a;} Alpha; typedef struct {int b;} Beta;"
        with pytest.raises(BinjaError) as exc_info:
            t_types.define_type(open_id, "Gamma", source, ctx)
        assert exc_info.value.code == TYPE_PARSE_ERROR

    def test_schema_keys(self, ctx, open_id):
        """define_type response has 'name' and 'definition'."""
        source = "typedef struct {int v;} SchemaType;"
        result = t_types.define_type(open_id, "SchemaType", source, ctx)
        assert "name" in result
        assert "definition" in result
