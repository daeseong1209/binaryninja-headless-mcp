"""Cross-reference tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate, parse_address
from ._helpers import find_function, get_session, hex_or_none


@tool()
def get_xrefs_to(
    binary_id: str,
    addr_or_name: str,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Return code references that point at the given address or function.

    Args:
        addr_or_name: target address (int/hex string) or function name.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    target_addr: int
    target_label: str

    try:
        target_addr = parse_address(addr_or_name)
        target_label = f"0x{target_addr:x}"
    except (ValueError, TypeError):
        func = find_function(bv, addr_or_name)
        target_addr = getattr(func, "start", None)
        if target_addr is None:
            raise ValueError(f"could not resolve target: {addr_or_name!r}") from None
        target_label = getattr(func, "name", None) or f"0x{target_addr:x}"

    refs = bv.get_code_refs(target_addr) if hasattr(bv, "get_code_refs") else []
    items: list[dict[str, Any]] = []
    for ref in refs or []:
        ref_addr = getattr(ref, "address", None)
        func_obj = getattr(ref, "function", None)
        if func_obj is not None:
            func_name = getattr(func_obj, "name", None)
        else:
            func_name = getattr(ref, "function_name", None)
        items.append(
            {
                "address": hex_or_none(ref_addr),
                "function": func_name,
            }
        )
    return {
        "target": target_label,
        "target_address": hex_or_none(target_addr),
        **paginate(items, offset=offset, limit=limit),
    }
