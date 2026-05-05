"""Symbol enumeration and renaming tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import invalid_address
from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate, parse_address
from ._helpers import (
    find_symbol,
    get_session,
    hex_or_none,
    resolve_symbol_types,
    symbol_to_dict,
    undo_transaction,
)


@tool()
def list_symbols(
    binary_id: str,
    ctx: Context,
    symbol_type: str | None = None,
    name_or_addr: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List symbols in the binary.

    Args:
        symbol_type: optional filter — one of "function", "imported_function",
                     "import_address", "data", "external", "library_function".
                     None = all symbols.
        name_or_addr: if provided, look up a single symbol by name or hex
                      address and return it. Raises SYMBOL_NOT_FOUND if absent.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    if name_or_addr is not None:
        sym = find_symbol(bv, name_or_addr)  # raises BinjaError(SYMBOL_NOT_FOUND) if absent
        items = [symbol_to_dict(sym)]
        return paginate(items, offset=0, limit=1)

    if symbol_type is not None:
        syms: list[Any] = []
        for t in resolve_symbol_types(symbol_type):
            syms.extend(bv.get_symbols_of_type(t))
    else:
        syms = list(bv.get_symbols())

    items = [symbol_to_dict(s) for s in syms]
    return paginate(items, offset=offset, limit=limit)


@tool()
def rename_symbol(binary_id: str, addr: str, new_name: str, ctx: Context) -> dict[str, Any]:
    """Rename a function or data symbol at the given address.

    Function path: assigns to func.name (preferred for functions).
    Data path: defines a user symbol of type DataSymbol.
    Records an undo entry; use undo() to revert.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    try:
        address = parse_address(addr)
    except ValueError as exc:
        raise invalid_address(addr) from exc

    if not new_name or not isinstance(new_name, str):
        raise ValueError("new_name must be a non-empty string")

    # Wrap the entire rename in an explicit undo transaction so real BN records
    # a roll-backable entry regardless of which write path is taken.
    with undo_transaction(bv):
        # Function path (preferred)
        func = bv.get_function_at(address)
        if func is not None:
            old = getattr(func, "name", None)
            if hasattr(bv, "rename_function"):
                # mock path — bv.rename_function handles _record_undo
                bv.rename_function(address, new_name)
            else:
                # real BN path — assignment triggers BN undo internally
                func.name = new_name
            return {
                "kind": "function",
                "address": hex_or_none(address),
                "before": old,
                "after": new_name,
            }

        # Data symbol path
        try:
            from binaryninja import Symbol, SymbolType  # type: ignore[import]
            sym_obj = Symbol(SymbolType.DataSymbol, address, new_name)
        except ImportError:
            sym_obj = type("_Sym", (), {"type": 3, "address": address, "name": new_name})()
        bv.define_user_symbol(sym_obj)
        return {
            "kind": "data",
            "address": hex_or_none(address),
            "before": None,
            "after": new_name,
        }


