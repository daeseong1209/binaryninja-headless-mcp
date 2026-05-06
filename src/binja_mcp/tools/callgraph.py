"""Call-graph tools: callers, callees, and raw call sites for a function."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import find_function, function_to_summary, get_session, hex_or_none


@tool()
def get_callers(
    binary_id: str,
    addr_or_name: str,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List call sites that target the given function.

    Each item describes one call instruction in some other function that calls
    INTO the target. ``address`` is the call instruction address, ``function``
    is a summary of the calling function. If a single caller has multiple call
    sites to the target, one item is emitted per site.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    target = find_function(bv, addr_or_name)
    target_addr = getattr(target, "start", None)

    # Prefer call-only sources: target.caller_sites (real BN) gives caller
    # ReferenceSource for actual call edges. Falling back to bv.get_code_refs
    # would include non-call data refs as callers, which is wrong.
    sites = getattr(target, "caller_sites", None)
    if sites is None:
        sites = bv.get_code_refs(target_addr) if hasattr(bv, "get_code_refs") else []

    items: list[dict[str, Any]] = []
    for ref in sites or []:
        caller = getattr(ref, "function", None)
        items.append(
            {
                "address": hex_or_none(getattr(ref, "address", None)),
                "function": function_to_summary(caller) if caller is not None else None,
            }
        )
    return {
        "target": getattr(target, "name", None) or hex_or_none(target_addr),
        "target_address": hex_or_none(target_addr),
        **paginate(items, offset=offset, limit=limit),
    }


@tool()
def get_callees(
    binary_id: str,
    addr_or_name: str,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List outgoing call sites from the given function.

    For each call instruction in the target, emit ``{address, target}`` where
    ``address`` is the call site inside the source function and ``target`` is
    a summary of the resolved callee (or ``None`` for indirect calls). Indirect
    sites with multiple resolved targets emit one item per resolved target.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    source = find_function(bv, addr_or_name)
    source_addr = getattr(source, "start", None)

    source_arch = getattr(source, "arch", None)
    items: list[dict[str, Any]] = []
    for site in getattr(source, "call_sites", None) or []:
        site_addr = getattr(site, "address", None)
        if site_addr is None:
            continue
        # Pass func+arch when available so overlapping/multi-arch views resolve
        # the correct callee set; bv.get_callees(addr) alone considers every
        # function containing the address.
        if source_arch is not None:
            try:
                callee_addrs = list(bv.get_callees(site_addr, source, source_arch) or [])
            except TypeError:
                callee_addrs = list(bv.get_callees(site_addr) or [])
        else:
            callee_addrs = list(bv.get_callees(site_addr) or [])
        if not callee_addrs:
            items.append({"address": hex_or_none(site_addr), "target": None})
            continue
        for ca in callee_addrs:
            callee_func = bv.get_function_at(ca)
            if callee_func is not None:
                target_payload: Any = function_to_summary(callee_func)
            else:
                # Resolved address but no Function at that address (typically a
                # thunk/import). Surface address + symbol if present so the
                # callee is identifiable; only fully-unresolved indirect calls
                # produce target=None.
                sym = bv.get_symbol_at(ca) if hasattr(bv, "get_symbol_at") else None
                target_payload = {
                    "name": getattr(sym, "name", None) if sym is not None else None,
                    "start": hex_or_none(ca),
                    "end": None,
                    "basic_block_count": 0,
                    "parameter_count": 0,
                }
            items.append({"address": hex_or_none(site_addr), "target": target_payload})
    return {
        "source": getattr(source, "name", None) or hex_or_none(source_addr),
        "source_address": hex_or_none(source_addr),
        **paginate(items, offset=offset, limit=limit),
    }


@tool()
def get_call_sites(
    binary_id: str,
    addr_or_name: str,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List raw call-site addresses inside the given function."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    source = find_function(bv, addr_or_name)
    source_addr = getattr(source, "start", None)

    items: list[dict[str, Any]] = []
    for site in getattr(source, "call_sites", None) or []:
        site_addr = getattr(site, "address", None)
        if site_addr is None:
            continue
        items.append({"address": hex_or_none(site_addr)})
    return {
        "source": getattr(source, "name", None) or hex_or_none(source_addr),
        "source_address": hex_or_none(source_addr),
        **paginate(items, offset=offset, limit=limit),
    }
