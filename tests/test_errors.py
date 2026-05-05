"""Tests for binja_mcp.errors — structured error hierarchy and factories."""
from __future__ import annotations

import pytest

from binja_mcp.errors import (
    BINARY_NOT_FOUND,
    FUNCTION_NOT_FOUND,
    INVALID_ADDRESS,
    INVALID_IL_LEVEL,
    BinjaError,
    binary_not_found,
    function_not_found,
    invalid_address,
    invalid_il_level,
)

# ---------------------------------------------------------------------------
# BinjaError base class
# ---------------------------------------------------------------------------


def test_binja_error_is_value_error_subclass():
    err = BinjaError("SOME_CODE", "some message")
    assert isinstance(err, ValueError)


def test_binja_error_str_returns_message():
    err = BinjaError("SOME_CODE", "some message")
    assert str(err) == "some message"


def test_binja_error_to_dict_contains_code_and_message():
    err = BinjaError("MY_CODE", "my message", extra_field="extra_value")
    d = err.to_dict()
    assert d["code"] == "MY_CODE"
    assert d["message"] == "my message"
    assert d["extra_field"] == "extra_value"


def test_binja_error_to_dict_with_no_extra():
    err = BinjaError("CODE", "msg")
    d = err.to_dict()
    assert d == {"code": "CODE", "message": "msg"}


def test_binja_error_caught_as_value_error():
    with pytest.raises(ValueError, match="some message"):
        raise BinjaError("SOME_CODE", "some message")


# ---------------------------------------------------------------------------
# binary_not_found factory
# ---------------------------------------------------------------------------


def test_binary_not_found_code():
    err = binary_not_found("abc123")
    assert err.code == BINARY_NOT_FOUND


def test_binary_not_found_message():
    err = binary_not_found("abc123")
    assert "unknown binary_id" in str(err)
    assert "abc123" in str(err)


def test_binary_not_found_hint():
    err = binary_not_found("abc123")
    assert "hint" in err.extra
    assert "open_binary" in err.extra["hint"]


def test_binary_not_found_extra_binary_id():
    err = binary_not_found("abc123")
    assert err.extra["binary_id"] == "abc123"


def test_binary_not_found_caught_as_value_error():
    with pytest.raises(ValueError, match="unknown binary_id"):
        raise binary_not_found("abc123")


# ---------------------------------------------------------------------------
# function_not_found factory
# ---------------------------------------------------------------------------


def test_function_not_found_code():
    err = function_not_found("main")
    assert err.code == FUNCTION_NOT_FOUND


def test_function_not_found_message():
    err = function_not_found("main")
    assert "function not found" in str(err)
    assert "main" in str(err)


def test_function_not_found_hint():
    err = function_not_found("main")
    assert "hint" in err.extra
    assert "list_functions" in err.extra["hint"]


def test_function_not_found_caught_as_value_error():
    with pytest.raises(ValueError, match="function not found"):
        raise function_not_found("main")


# ---------------------------------------------------------------------------
# invalid_il_level factory
# ---------------------------------------------------------------------------


def test_invalid_il_level_code():
    err = invalid_il_level("XLIL")
    assert err.code == INVALID_IL_LEVEL


def test_invalid_il_level_message():
    err = invalid_il_level("XLIL")
    assert "unknown IL level" in str(err)
    assert "XLIL" in str(err)


def test_invalid_il_level_hint():
    err = invalid_il_level("XLIL")
    assert "hint" in err.extra
    assert "LLIL" in err.extra["hint"]


def test_invalid_il_level_caught_as_value_error():
    with pytest.raises(ValueError, match="unknown IL level"):
        raise invalid_il_level("XLIL")


# ---------------------------------------------------------------------------
# invalid_address factory
# ---------------------------------------------------------------------------


def test_invalid_address_code():
    err = invalid_address("bad_addr")
    assert err.code == INVALID_ADDRESS


def test_invalid_address_message():
    err = invalid_address("bad_addr")
    assert "could not interpret" in str(err)
    assert "bad_addr" in str(err)


def test_invalid_address_hint():
    err = invalid_address("bad_addr")
    assert "hint" in err.extra
    assert "0x401000" in err.extra["hint"]


def test_invalid_address_caught_as_value_error():
    with pytest.raises(ValueError, match="could not interpret"):
        raise invalid_address("bad_addr")


# ---------------------------------------------------------------------------
# to_dict completeness
# ---------------------------------------------------------------------------


def test_to_dict_includes_all_extra_fields():
    err = BinjaError("C", "m", alpha="a", beta="b")
    d = err.to_dict()
    assert d["alpha"] == "a"
    assert d["beta"] == "b"
    assert d["code"] == "C"
    assert d["message"] == "m"
