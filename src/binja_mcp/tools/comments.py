"""Comment annotation tools — global (BinaryView) and function-scoped."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import comment_invalid_scope, invalid_address
from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate, parse_address
from ._helpers import find_function, get_session, hex_or_none, undo_transaction

_VALID_WRITE_SCOPES = ("global", "function")
_VALID_LIST_SCOPES = ("global", "function", "all")


def _resolve_addr(addr: str | int) -> int:
    if addr is None or not isinstance(addr, (str, int)):
        raise invalid_address(addr)
    try:
        return parse_address(addr)
    except (ValueError, TypeError) as exc:
        raise invalid_address(addr) from exc


def _resolve_function(bv: Any, scope: str, function: str | int | None) -> Any:
    if scope != "function":
        return None
    if function is None:
        raise ValueError('scope="function" requires a function argument')
    return find_function(bv, function)


@tool()
def set_comment(
    binary_id: str,
    addr: str | int,
    text: str,
    ctx: Context,
    scope: str = "global",
    function: str | int | None = None,
) -> dict[str, Any]:
    """Set a comment at the given address.

    scope="global" attaches to the BinaryView; scope="function" requires
    `function` (name or address) and attaches to that function's comment map.
    Pass an empty string to clear an existing comment. Wrapped in an explicit
    undo transaction so undo() reliably reverts the write across BN versions.
    """
    if scope not in _VALID_WRITE_SCOPES:
        raise comment_invalid_scope(scope)

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    address = _resolve_addr(addr)

    with undo_transaction(bv):
        if scope == "global":
            bv.set_comment_at(address, text)
        else:
            func = _resolve_function(bv, scope, function)
            func.set_comment_at(address, text)

    return {"address": hex_or_none(address), "text": text, "scope": scope}


@tool()
def get_comment(
    binary_id: str,
    addr: str | int,
    ctx: Context,
    scope: str = "global",
    function: str | int | None = None,
) -> dict[str, Any]:
    """Read the comment at the given address.

    Returns text=None when no comment exists at that address. scope="function"
    requires `function` (name or address).
    """
    if scope not in _VALID_WRITE_SCOPES:
        raise comment_invalid_scope(scope)

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    address = _resolve_addr(addr)

    if scope == "global":
        text = bv.get_comment_at(address) or None
    else:
        func = _resolve_function(bv, scope, function)
        text = func.get_comment_at(address) or None

    return {"address": hex_or_none(address), "text": text, "scope": scope}


@tool()
def list_comments(
    binary_id: str,
    ctx: Context,
    scope: str = "all",
    function: str | int | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List comments in the binary (paginated).

    scope="global" → BinaryView comments. scope="function" requires `function`
    and returns that function's comments. scope="all" returns global + every
    function's comments, each item tagged with its scope.
    """
    if scope not in _VALID_LIST_SCOPES:
        raise comment_invalid_scope(scope)

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    items: list[dict[str, Any]] = []

    if scope in ("global", "all"):
        for addr, text in (getattr(bv, "address_comments", None) or {}).items():
            items.append({"address": hex_or_none(addr), "text": text, "scope": "global"})

    if scope == "function":
        func = _resolve_function(bv, "function", function)
        fname = getattr(func, "name", None)
        for addr, text in (getattr(func, "comments", None) or {}).items():
            items.append(
                {
                    "address": hex_or_none(addr),
                    "text": text,
                    "scope": "function",
                    "function": fname,
                }
            )
    elif scope == "all":
        for f in getattr(bv, "functions", None) or []:
            fname = getattr(f, "name", None)
            for addr, text in (getattr(f, "comments", None) or {}).items():
                items.append(
                    {
                        "address": hex_or_none(addr),
                        "text": text,
                        "scope": "function",
                        "function": fname,
                    }
                )

    # Sort by (scope, integer address) so 0x200 < 0x1000 ordering is correct.
    def _addr_key(it: dict[str, Any]) -> int:
        a = it.get("address")
        return int(a, 16) if isinstance(a, str) and a.startswith("0x") else 0

    items.sort(key=lambda it: (it["scope"], _addr_key(it)))
    return paginate(items, offset=offset, limit=limit)


@tool()
def remove_comment(
    binary_id: str,
    addr: str | int,
    ctx: Context,
    scope: str = "global",
    function: str | int | None = None,
) -> dict[str, Any]:
    """Remove the comment at the given address. Returns removed=False if none existed."""
    if scope not in _VALID_WRITE_SCOPES:
        raise comment_invalid_scope(scope)

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    address = _resolve_addr(addr)

    if scope == "global":
        existing = bv.get_comment_at(address) or ""
        if existing:
            with undo_transaction(bv):
                bv.set_comment_at(address, "")
    else:
        func = _resolve_function(bv, scope, function)
        existing = func.get_comment_at(address) or ""
        if existing:
            with undo_transaction(bv):
                func.set_comment_at(address, "")

    return {"address": hex_or_none(address), "removed": bool(existing), "scope": scope}
