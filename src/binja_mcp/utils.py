"""Common utilities for binja-mcp."""

from __future__ import annotations

from typing import Any


def parse_address(value: str | int) -> int:
    """Parse an address from int or hex/dec string.

    Accepts: 0x1234, 0X1234, 1234, "0x1234".
    """
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise TypeError(f"address must be int or str, got {type(value).__name__}")
    s = value.strip()
    if not s:
        raise ValueError("empty address")
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s, 0)  # auto-detect base
    except ValueError as exc:
        raise ValueError(f"invalid address: {value!r}") from exc


def paginate(items: list[Any], offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Apply offset/limit pagination and return a structured response.

    Returns:
        {"items": [...], "offset": N, "limit": N, "total": N, "has_more": bool}
    """
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if limit <= 0:
        raise ValueError(f"limit must be > 0, got {limit}")
    total = len(items)
    end = min(offset + limit, total)
    return {
        "items": items[offset:end],
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": end < total,
    }


def truncate_text(text: str, max_len: int = 50_000) -> dict[str, Any]:
    """Truncate text and report whether it was truncated.

    Returns:
        {"text": "...", "truncated": bool, "original_length": N}
    """
    if len(text) <= max_len:
        return {"text": text, "truncated": False, "original_length": len(text)}
    return {
        "text": text[:max_len],
        "truncated": True,
        "original_length": len(text),
    }
