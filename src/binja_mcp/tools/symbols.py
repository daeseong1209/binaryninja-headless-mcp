"""Symbol enumeration and renaming tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import invalid_address
from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate, parse_address
from ._helpers import find_symbol, get_session, hex_or_none


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
        items = [_symbol_to_dict(sym)]
        return paginate(items, offset=0, limit=1)

    if symbol_type is not None:
        types = _resolve_symbol_type(bv, symbol_type)
        syms: list[Any] = []
        for t in types:
            got = bv.get_symbols_of_type(t) if hasattr(bv, "get_symbols_of_type") else []
            syms.extend(got)
    else:
        syms = list(bv.get_symbols()) if hasattr(bv, "get_symbols") else []

    items = [_symbol_to_dict(s) for s in syms]
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
    state_id = bv.begin_undo_actions() if hasattr(bv, "begin_undo_actions") else None
    try:
        # Function path (preferred)
        func = bv.get_function_at(address) if hasattr(bv, "get_function_at") else None
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
        if hasattr(bv, "define_user_symbol"):
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
    finally:
        if state_id is not None and hasattr(bv, "commit_undo_actions"):
            try:
                bv.commit_undo_actions(state_id)
            except Exception:
                pass  # best-effort; don't mask the original error

    raise invalid_address(addr)


def _symbol_to_dict(s: Any) -> dict[str, Any]:
    return {
        "name": getattr(s, "name", "<unnamed>"),
        "full_name": getattr(s, "full_name", "") or "",
        "address": hex_or_none(getattr(s, "address", None)),
        "type": _symbol_type_name(getattr(s, "type", None)),
        "auto": bool(getattr(s, "auto", True)),
        "ordinal": int(getattr(s, "ordinal", 0) or 0),
    }


def _resolve_symbol_type(bv: Any, name: str) -> tuple[Any, ...]:
    """Convert string filter to enum values appropriate for the backend."""
    name = name.lower().replace("-", "_")
    mapping: dict[str, tuple[str, ...]] = {
        "function": ("FunctionSymbol",),
        "imported_function": ("ImportedFunctionSymbol",),
        "import_address": ("ImportAddressSymbol",),
        "imports": ("ImportedFunctionSymbol", "ImportAddressSymbol"),
        "data": ("DataSymbol",),
        "external": ("ExternalSymbol",),
        "library_function": ("LibraryFunctionSymbol",),
    }
    enum_names = mapping.get(name)
    if enum_names is None:
        raise ValueError(
            f"unknown symbol_type: {name!r}; valid: {sorted(mapping.keys())}"
        )

    try:
        from binaryninja import SymbolType  # type: ignore[import]
        return tuple(getattr(SymbolType, n) for n in enum_names if hasattr(SymbolType, n))
    except ImportError:
        from ..mock_backend import MockSymbolType
        return tuple(getattr(MockSymbolType, n) for n in enum_names if hasattr(MockSymbolType, n))


def _symbol_type_name(sym_type: Any) -> str | None:
    if sym_type is None:
        return None
    return getattr(sym_type, "name", str(sym_type))
