"""Byte-pattern search via bv.read over readable segments (exact + ?? wildcards)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import byte_search_invalid_pattern
from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate, parse_address
from ._helpers import get_session, hex_or_none

# DoS guards
MAX_PATTERN_BYTES = 1024
MAX_RESULTS = 10_000
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _normalise_pattern(pattern: str) -> str:
    if not isinstance(pattern, str):
        raise byte_search_invalid_pattern(pattern, "pattern must be a string")
    # Pre-gate raw length so adversarial input can't amplify CPU before validation.
    if len(pattern) > MAX_PATTERN_BYTES * 4:
        raise byte_search_invalid_pattern(
            pattern[:200], f"raw pattern length exceeds {MAX_PATTERN_BYTES * 4} chars"
        )
    return "".join(ch for ch in pattern if ch not in " ,\t\r\n")


def _parse_hex_bytes(pattern: str) -> bytes:
    cleaned = _normalise_pattern(pattern)
    if not cleaned:
        raise byte_search_invalid_pattern(pattern, "pattern is empty")
    if len(cleaned) % 2 != 0:
        raise byte_search_invalid_pattern(
            pattern, f"odd nibble count ({len(cleaned)}); pattern must be whole bytes"
        )
    if len(cleaned) // 2 > MAX_PATTERN_BYTES:
        raise byte_search_invalid_pattern(
            pattern, f"pattern too long ({len(cleaned) // 2} bytes; max {MAX_PATTERN_BYTES})"
        )
    for i, ch in enumerate(cleaned):
        if ch not in _HEX_DIGITS:
            raise byte_search_invalid_pattern(
                pattern, f"invalid hex char {ch!r} at position {i}"
            )
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:  # pragma: no cover — guarded above
        raise byte_search_invalid_pattern(pattern, str(exc)) from exc


def _parse_pattern_with_wildcards(pattern: str) -> tuple[bytes, bytes]:
    """Return (value, mask) where mask[i]==0xff is a fixed byte, 0x00 is a wildcard."""
    cleaned = _normalise_pattern(pattern)
    if not cleaned:
        raise byte_search_invalid_pattern(pattern, "pattern is empty")
    if len(cleaned) % 2 != 0:
        raise byte_search_invalid_pattern(
            pattern, f"odd nibble count ({len(cleaned)}); pattern must be whole bytes"
        )
    nbytes = len(cleaned) // 2
    if nbytes > MAX_PATTERN_BYTES:
        raise byte_search_invalid_pattern(
            pattern, f"pattern too long ({nbytes} bytes; max {MAX_PATTERN_BYTES})"
        )
    value = bytearray(nbytes)
    mask = bytearray(nbytes)
    for i in range(nbytes):
        pair = cleaned[2 * i : 2 * i + 2]
        if pair == "??":
            value[i] = 0
            mask[i] = 0
            continue
        for j, ch in enumerate(pair):
            if ch == "?":
                raise byte_search_invalid_pattern(
                    pattern,
                    f"single-nibble wildcard at position {2 * i + j};"
                    " use '??' for whole-byte wildcards",
                )
            if ch not in _HEX_DIGITS:
                raise byte_search_invalid_pattern(
                    pattern, f"invalid hex char {ch!r} at position {2 * i + j}"
                )
        value[i] = int(pair, 16)
        mask[i] = 0xFF
    if not any(mask):
        raise byte_search_invalid_pattern(
            pattern, "pattern is entirely wildcards; at least one fixed byte required"
        )
    return bytes(value), bytes(mask)


def _resolve_bound(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return parse_address(value)
    raise TypeError(f"address must be int, str, or None, got {type(value).__name__}")


def _iter_readable_segments(bv: Any):
    segs = []
    for seg in getattr(bv, "segments", []) or []:
        if not getattr(seg, "readable", False):
            continue
        start = getattr(seg, "start", None)
        end = getattr(seg, "end", None)
        if start is None or end is None or end <= start:
            continue
        segs.append((int(start), int(end)))
    segs.sort()
    return segs


def _scan_segment_exact(
    data: bytes, base: int, needle: bytes, results: list[dict[str, Any]]
) -> bool:
    """Append exact matches (overlapping). Returns True if MAX_RESULTS reached."""
    pos = 0
    nlen = len(needle)
    while True:
        idx = data.find(needle, pos)
        if idx < 0:
            return False
        results.append({"address": hex_or_none(base + idx)})
        if len(results) >= MAX_RESULTS:
            return True
        pos = idx + 1
        if pos + nlen > len(data):
            return False


def _scan_segment_masked(
    data: bytes,
    base: int,
    value: bytes,
    mask: bytes,
    results: list[dict[str, Any]],
) -> bool:
    """Append masked matches anchored on the first fixed byte. Returns True if capped."""
    nlen = len(value)
    if nlen > len(data):
        return False
    # _parse_pattern_with_wildcards guarantees at least one fixed byte.
    anchor_idx = mask.find(b"\xff")
    anchor_byte = bytes([value[anchor_idx]])
    last_start = len(data) - nlen
    pos = 0
    while pos <= last_start:
        found = data.find(anchor_byte, pos + anchor_idx, last_start + anchor_idx + 1)
        if found < 0:
            return False
        start = found - anchor_idx
        if _matches_at(data, start, value, mask):
            results.append({"address": hex_or_none(base + start)})
            if len(results) >= MAX_RESULTS:
                return True
        pos = start + 1
    return False


def _matches_at(data: bytes, start: int, value: bytes, mask: bytes) -> bool:
    for i, m in enumerate(mask):
        if m and data[start + i] != value[i]:
            return False
    return True


def _search(
    bv: Any,
    *,
    value: bytes,
    mask: bytes | None,
    start: int | None,
    end: int | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Scan readable segments. Returns (results, capped) where capped is True if MAX_RESULTS hit."""
    results: list[dict[str, Any]] = []
    nlen = len(value)
    for seg_start, seg_end in _iter_readable_segments(bv):
        s = seg_start if start is None else max(seg_start, start)
        e = seg_end if end is None else min(seg_end, end)
        if e <= s or e - s < nlen:
            continue
        try:
            data = bv.read(s, e - s)
        except Exception:
            continue
        if not data or len(data) < nlen:
            continue
        if mask is None:
            capped = _scan_segment_exact(data, s, value, results)
        else:
            capped = _scan_segment_masked(data, s, value, mask, results)
        if capped:
            return results, True
    return results, False


@tool()
def search_bytes(
    binary_id: str,
    hex_pattern: str,
    ctx: Context,
    start: str | int | None = None,
    end: str | int | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Locate exact byte sequences (no wildcards) in readable segments.

    Args:
        hex_pattern: hex bytes optionally separated by spaces/commas
                     (e.g. ``"48 89 e5 c3"``, ``"4889e5c3"``, ``"48,89,e5,c3"``).
                     Must be 1-1024 whole bytes; ``??`` wildcards are rejected
                     here — use ``search_pattern`` instead.
        start: optional inclusive lower address bound (int or hex string).
        end:   optional exclusive upper address bound.
    """
    needle = _parse_hex_bytes(hex_pattern)

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    lo = _resolve_bound(start)
    hi = _resolve_bound(end)
    items, capped = _search(bv, value=needle, mask=None, start=lo, end=hi)

    page = paginate(items, offset=offset, limit=limit)
    if capped:
        page["note"] = f"result capped at {MAX_RESULTS}"
    return page


@tool()
def search_pattern(
    binary_id: str,
    hex_pattern: str,
    ctx: Context,
    start: str | int | None = None,
    end: str | int | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Locate byte patterns with ``??`` wildcards in readable segments.

    Args:
        hex_pattern: hex bytes with optional whole-byte wildcards
                     (e.g. ``"48 89 ?? c3"``). Half-nibble wildcards like
                     ``"4?"`` are rejected; at least one fixed byte is required.
        start: optional inclusive lower address bound.
        end:   optional exclusive upper address bound.
    """
    value, mask = _parse_pattern_with_wildcards(hex_pattern)

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    lo = _resolve_bound(start)
    hi = _resolve_bound(end)
    items, capped = _search(bv, value=value, mask=mask, start=lo, end=hi)

    page = paginate(items, offset=offset, limit=limit)
    if capped:
        page["note"] = f"result capped at {MAX_RESULTS}"
    return page
