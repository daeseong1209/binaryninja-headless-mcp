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
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.extra}


# Error code constants
BINARY_NOT_FOUND = "BINARY_NOT_FOUND"
FUNCTION_NOT_FOUND = "FUNCTION_NOT_FOUND"
INVALID_IL_LEVEL = "INVALID_IL_LEVEL"
INVALID_ADDRESS = "INVALID_ADDRESS"
INVALID_PAGINATION = "INVALID_PAGINATION"


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
