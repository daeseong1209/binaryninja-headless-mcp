"""String search tool."""

from __future__ import annotations

import re
import threading
from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import get_session, hex_or_none

MAX_PATTERN_LENGTH = 256
STRING_REGEX_TIMEOUT_S = 2.0

# Reject known catastrophic-backtracking constructs before re.compile, because
# Python's `re` engine holds the GIL during a single match — meaning a daemon
# thread + Event watchdog cannot interrupt it. A length cap + this static
# heuristic is the real defense; the watchdog only catches slower divergent
# patterns that yield the GIL between strings.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*]")


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

    if regex and pattern and _NESTED_QUANTIFIER.search(pattern):
        raise ValueError(
            "pattern rejected: nested quantifier construct can cause "
            "catastrophic backtracking (e.g. '(a+)+', '(a*)*')"
        )

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    raw = bv.get_strings() if hasattr(bv, "get_strings") else []
    matcher = _build_matcher(pattern, regex=regex, case_sensitive=case_sensitive)

    if regex and pattern:
        items = _collect_with_timeout(raw, matcher, STRING_REGEX_TIMEOUT_S)
    else:
        items = _collect(raw, matcher)

    return paginate(items, offset=offset, limit=limit)


def _collect_with_timeout(raw, matcher, timeout: float) -> list[dict[str, Any]]:
    """Run _collect on a daemon thread; raise TimeoutError if it overruns.

    A daemon thread lets the caller return immediately on timeout — the worker
    keeps spinning in the regex engine until the process exits. ThreadPoolExecutor
    cannot achieve this because its context manager joins the worker on exit,
    re-blocking the caller for the very catastrophic-backtracking pattern we
    were trying to defend against.
    """
    result: list[dict[str, Any]] = []
    error: list[BaseException] = []
    done = threading.Event()

    def worker() -> None:
        try:
            result.extend(_collect(raw, matcher))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    if not done.wait(timeout):
        raise TimeoutError(f"regex match exceeded {timeout}s")
    if error:
        raise error[0]
    return result


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
