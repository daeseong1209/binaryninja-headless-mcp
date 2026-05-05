"""Structured errors for binja-mcp tools."""
from __future__ import annotations

from typing import Any


class BinjaError(ValueError):
    """ValueError-compatible structured error.

    Subclassing ValueError keeps backward compatibility with
    pytest.raises(ValueError, match=...) and with FastMCP's automatic
    error->isError conversion.
    """

    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code = code
        # Validate extras are JSON-serialisable to prevent response shape drift
        import json
        try:
            json.dumps(extra)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"BinjaError extra fields must be JSON-serialisable: {exc}") from exc
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.extra}


# Error code constants
BINARY_NOT_FOUND = "BINARY_NOT_FOUND"
FUNCTION_NOT_FOUND = "FUNCTION_NOT_FOUND"
INVALID_IL_LEVEL = "INVALID_IL_LEVEL"
INVALID_ADDRESS = "INVALID_ADDRESS"
UNDO_STATE_INVALID = "UNDO_STATE_INVALID"


# Factory helpers (consistent hint messages)
def binary_not_found(binary_id: str) -> BinjaError:
    return BinjaError(
        BINARY_NOT_FOUND,
        f"unknown binary_id: {binary_id}",
        binary_id=binary_id,
        hint="call open_binary first to obtain a valid binary_id",
    )


def function_not_found(addr_or_name: Any) -> BinjaError:
    return BinjaError(
        FUNCTION_NOT_FOUND,
        f"function not found: {addr_or_name!r}",
        target=str(addr_or_name),
        hint="use list_functions to enumerate available functions",
    )


def invalid_il_level(level: str) -> BinjaError:
    return BinjaError(
        INVALID_IL_LEVEL,
        f"unknown IL level: {level!r} (expected LLIL/MLIL/HLIL)",
        level=level,
        hint="pass one of LLIL, MLIL, or HLIL (case-insensitive)",
    )


def invalid_address(value: Any) -> BinjaError:
    return BinjaError(
        INVALID_ADDRESS,
        f"could not interpret {value!r} as function or address",
        value=str(value),
        hint='use a hex address like "0x401000" or a known function name',
    )


def undo_state_invalid(state_id: str) -> BinjaError:
    return BinjaError(
        UNDO_STATE_INVALID,
        f"unknown or already-committed undo state_id: {state_id}",
        state_id=state_id,
        hint=(
            "call begin_undo first to obtain a valid state_id;"
            " commit_undo can be called only once per state"
        ),
    )


TYPE_PARSE_ERROR = "TYPE_PARSE_ERROR"
SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
BYTE_SEARCH_INVALID_PATTERN = "BYTE_SEARCH_INVALID_PATTERN"


def type_parse_error(source: str, original: str = "") -> BinjaError:
    return BinjaError(
        TYPE_PARSE_ERROR,
        f"failed to parse type definition: {original or 'syntax error'}",
        source=source[:200],
        original_error=original,
        hint="ensure the source is valid C-style declaration (e.g. 'typedef struct {int x;} Foo;')",
    )


def symbol_not_found(target: Any) -> BinjaError:
    return BinjaError(
        SYMBOL_NOT_FOUND,
        f"symbol not found: {target!r}",
        target=str(target),
        hint="use list_symbols to enumerate available symbols",
    )


def byte_search_invalid_pattern(pattern: Any, reason: str) -> BinjaError:
    return BinjaError(
        BYTE_SEARCH_INVALID_PATTERN,
        f"invalid hex pattern: {reason}",
        pattern=str(pattern)[:200],
        reason=reason,
        hint=(
            "use whole-byte hex (1-1024 bytes), e.g. '48 89 e5 c3'"
            " or '4889e5c3'; search_pattern also accepts '??' wildcards"
        ),
    )
