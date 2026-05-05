"""Segment / section / import / export listings."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import get_session, hex_or_none


@tool()
def list_segments(binary_id: str, ctx: Context) -> dict[str, Any]:
    """List memory segments (start/end/r/w/x/data_offset/data_length)."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    items = []
    for seg in getattr(bv, "segments", []) or []:
        items.append(
            {
                "start": hex_or_none(getattr(seg, "start", None)),
                "end": hex_or_none(getattr(seg, "end", None)),
                "data_offset": getattr(seg, "data_offset", None),
                "data_length": getattr(seg, "data_length", None),
                "readable": bool(getattr(seg, "readable", False)),
                "writable": bool(getattr(seg, "writable", False)),
                "executable": bool(getattr(seg, "executable", False)),
            }
        )
    return {"items": items, "total": len(items)}


@tool()
def list_sections(binary_id: str, ctx: Context) -> dict[str, Any]:
    """List sections (name/start/end/semantics)."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    sections_obj = getattr(bv, "sections", None) or {}
    if hasattr(sections_obj, "items"):
        iterable = sections_obj.items()
    else:
        iterable = ((getattr(s, "name", "?"), s) for s in sections_obj)
    items = []
    for name, sec in iterable:
        items.append(
            {
                "name": name,
                "start": hex_or_none(getattr(sec, "start", None)),
                "end": hex_or_none(getattr(sec, "end", None)),
                "semantics": str(getattr(sec, "semantics", "") or ""),
            }
        )
    return {"items": items, "total": len(items)}


@tool()
def list_imports(
    binary_id: str, ctx: Context, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """List imported symbols (paginated, often large)."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    items = _symbols_to_dicts(_collect_imports(bv))
    return paginate(items, offset=offset, limit=limit)


@tool()
def list_exports(
    binary_id: str, ctx: Context, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """List exported symbols (paginated).

    Real BN has no ExportedFunctionSymbol enum value. For real binaries we
    approximate exports as FunctionSymbols that are not auto-generated (i.e.
    named via the binary's export table).  For the mock backend we use the
    explicit ``is_export=True`` flag on MockSymbol.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    items = _symbols_to_dicts(_collect_exports(bv))
    return paginate(items, offset=offset, limit=limit)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _import_type_values(bv: Any) -> list[Any]:
    """Return import-related SymbolType values appropriate for *bv*'s backend.

    Prefers real binaryninja enum objects; falls back to MockSymbolType ints.
    """
    try:
        import binaryninja  # type: ignore[import]

        return [
            binaryninja.SymbolType.ImportedFunctionSymbol,
            binaryninja.SymbolType.ImportAddressSymbol,
        ]
    except Exception:
        from ..mock_backend import MockSymbolType

        return [
            MockSymbolType.ImportedFunctionSymbol,
            MockSymbolType.ImportAddressSymbol,
        ]


def _collect_imports(bv: Any) -> list[Any]:
    """Collect imported function/address symbols from any BinaryView backend."""
    types = _import_type_values(bv)
    getter = getattr(bv, "get_symbols_of_type", None)
    if getter is not None:
        result: list[Any] = []
        for t in types:
            result.extend(getter(t))
        return result
    # Fallback: filter all symbols by integer type comparison
    type_ints = {int(t) for t in types}
    all_syms = getattr(bv, "symbols", []) or []
    if hasattr(all_syms, "values"):
        all_syms = list(all_syms.values())
    return [s for s in all_syms if int(getattr(s, "type", -1)) in type_ints]


def _collect_exports(bv: Any) -> list[Any]:
    """Collect export-like symbols from any BinaryView backend.

    Real BN has no ``ExportedFunctionSymbol`` enum value.  We approximate
    exports as FunctionSymbols (int type == 0) that are *not* auto-generated,
    meaning BN assigned the name from the binary's export table rather than by
    analysis.  On the mock backend we use the explicit ``is_export=True`` flag.
    """
    all_syms: list[Any] = []
    getter = getattr(bv, "get_symbols", None)
    if getter is not None:
        all_syms = list(getter())
    else:
        raw = getattr(bv, "symbols", []) or []
        all_syms = list(raw.values()) if hasattr(raw, "values") else list(raw)

    out: list[Any] = []
    for s in all_syms:
        # Mock backend path: explicit export marker
        if getattr(s, "is_export", False):
            out.append(s)
            continue
        # Real BN heuristic: FunctionSymbol (0) that is not auto-generated
        sym_type = getattr(s, "type", None)
        is_func = sym_type is not None and int(sym_type) == 0
        is_auto = getattr(s, "auto", True)
        if is_func and not is_auto:
            out.append(s)
    return out


def _symbols_to_dicts(syms: list[Any]) -> list[dict[str, Any]]:
    """Convert symbol objects into JSON-friendly dicts."""
    result = []
    for sym in syms:
        sym_type = getattr(sym, "type", None)
        result.append(
            {
                "name": getattr(sym, "name", None),
                "address": hex_or_none(getattr(sym, "address", None)),
                "type": str(sym_type) if sym_type is not None else None,
                "full_name": getattr(sym, "full_name", None),
                "ordinal": getattr(sym, "ordinal", None),
            }
        )
    return result
