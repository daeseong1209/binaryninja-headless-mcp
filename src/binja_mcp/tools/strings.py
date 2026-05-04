"""String search tool."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import get_session, hex_or_none

MAX_PATTERN_LENGTH = 256
STRING_REGEX_TIMEOUT_S = 2.0


@tool()
def search_strings(
    binary_id: str,
    ctx: Context,
    pattern: str | None = None,
    regex: bool = False,
    case_sensitive: bool = True,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Search strings discovered in a binary.

    Args:
        pattern: substring or regex. If omitted, returns all strings.
        regex: when True, pattern is treated as a Python regex.
        case_sensitive: case-sensitive comparison (default True).
    """
    if pattern is not None and len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(f"pattern too long (max {MAX_PATTERN_LENGTH})")

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    raw = bv.get_strings() if hasattr(bv, "get_strings") else []
    matcher = _build_matcher(pattern, regex=regex, case_sensitive=case_sensitive)

    if regex and pattern:
        # Run regex matching under a watchdog to defeat catastrophic backtracking.
        with ThreadPoolExecutor(max_workers=1) as ex:
            try:
                items = ex.submit(_collect, raw, matcher).result(
                    timeout=STRING_REGEX_TIMEOUT_S
                )
            except FuturesTimeout as exc:
                raise TimeoutError(
                    f"regex match exceeded {STRING_REGEX_TIMEOUT_S}s"
                ) from exc
    else:
        items = _collect(raw, matcher)

    return paginate(items, offset=offset, limit=limit)


def _collect(raw, matcher) -> list[dict[str, Any]]:
    """Project matching strings into a JSON-friendly list."""
    result: list[dict[str, Any]] = []
    for s in raw or []:
        value = getattr(s, "value", None)
        if value is None or not matcher(value):
            continue
        addr = getattr(s, "address", None) or getattr(s, "start", None)
        result.append(
            {
                "value": value,
                "address": hex_or_none(addr),
                "length": getattr(s, "length", len(value)),
            }
        )
    return result


def _build_matcher(pattern: str | None, *, regex: bool, case_sensitive: bool):
    """Return a value→bool predicate for the requested mode."""
    if pattern is None or pattern == "":
        return lambda _v: True
    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern, flags)
        return lambda v: bool(compiled.search(v))
    if case_sensitive:
        return lambda v: pattern in v
    needle = pattern.lower()
    return lambda v: needle in v.lower()
