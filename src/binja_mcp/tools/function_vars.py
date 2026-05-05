"""Function variable inspection and renaming tools.

Adds three v0.4 tools that operate on a function's parameters and locals:

* ``list_function_variables`` — paginated listing with kind/storage/type
* ``rename_variable`` — rename a parameter or local by current name
* ``set_variable_type`` — re-type a variable via ``parse_type_string``
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import type_parse_error
from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import (
    find_function,
    find_variable,
    get_session,
    iter_function_variables,
    undo_transaction,
)


def _variable_to_dict(v: Any, fallback_index: int) -> dict[str, Any]:
    """Convert a Variable-like object into a JSON-friendly dict."""
    var_type = getattr(v, "type", None)
    if var_type is None:
        var_type = getattr(v, "type_str", None)
    type_str = str(var_type) if var_type is not None else ""

    raw_kind = getattr(v, "kind", None)
    if isinstance(raw_kind, str):
        kind = raw_kind
    else:
        # Real BN exposes source_type (Stack/Register VariableSourceType) but
        # not a clean "parameter vs local" tag. Caller stamps the kind below
        # based on parameter_vars membership (authoritative).
        kind = "local"

    storage = getattr(v, "storage", None)
    index = getattr(v, "index", None)
    if index is None:
        index = fallback_index

    return {
        "name": getattr(v, "name", "<unnamed>"),
        "type": type_str,
        "kind": kind,
        "index": int(index) if index is not None else fallback_index,
        "storage": int(storage) if isinstance(storage, int) else storage,
    }


@tool()
def list_function_variables(
    binary_id: str,
    function: str | int,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List parameters and locals of a function (paginated).

    Variables are returned in ``parameter_vars`` order followed by remaining
    locals from ``func.vars``, deduplicated by storage. Each item:
    ``{name, type, kind: "parameter"|"local", index, storage}``.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    func = find_function(bv, function)
    param_storages: set[Any] = set()
    for p in getattr(func, "parameter_vars", None) or []:
        param_storages.add(getattr(p, "storage", None))

    items: list[dict[str, Any]] = []
    for i, v in enumerate(iter_function_variables(func)):
        d = _variable_to_dict(v, fallback_index=i)
        # Stamp kind from membership in parameter_vars (authoritative on real BN).
        if getattr(v, "storage", None) in param_storages:
            d["kind"] = "parameter"
        elif d["kind"] not in ("parameter", "local"):
            d["kind"] = "local"
        items.append(d)

    return paginate(items, offset=offset, limit=limit)


@tool()
def rename_variable(
    binary_id: str,
    function: str | int,
    var_name: str,
    new_name: str,
    ctx: Context,
) -> dict[str, Any]:
    """Rename a parameter or local variable by its current name.

    Raises ``BinjaError(VARIABLE_NOT_FOUND)`` if no variable carries
    ``var_name``. Records an undo entry. When multiple variables share the
    same name (rare), the first match wins; rename ambiguous vars uniquely
    before further ops.
    """
    if not new_name or not isinstance(new_name, str):
        raise ValueError("new_name must be a non-empty string")

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    func = find_function(bv, function)
    var = find_variable(func, var_name)

    # Determine kind based on parameter membership (authoritative).
    params = getattr(func, "parameter_vars", None) or []
    param_storages = {getattr(p, "storage", None) for p in params}
    var_storage = getattr(var, "storage", None)
    kind = "parameter" if var_storage in param_storages else "local"

    with undo_transaction(bv):
        if hasattr(bv, "rename_variable"):
            # Mock path — bv.rename_variable handles _record_undo
            func_start = getattr(func, "start", None)
            bv.rename_variable(func_start, var_storage, new_name)
        else:
            # Real BN: assignment auto-records undo
            var.name = new_name

    return {
        "function": getattr(func, "name", None),
        "before": var_name,
        "after": new_name,
        "kind": kind,
    }


@tool()
def set_variable_type(
    binary_id: str,
    function: str | int,
    var_name: str,
    type_str: str,
    ctx: Context,
) -> dict[str, Any]:
    """Set the type of a parameter or local variable.

    Parses ``type_str`` via ``bv.parse_type_string`` and assigns the
    resulting Type. Raises ``BinjaError(TYPE_PARSE_ERROR)`` on bad syntax
    and ``BinjaError(VARIABLE_NOT_FOUND)`` when ``var_name`` doesn't match.
    Records an undo entry.
    """
    if not type_str or not isinstance(type_str, str):
        raise ValueError("type_str must be a non-empty string")

    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    func = find_function(bv, function)
    var = find_variable(func, var_name)

    try:
        parsed = bv.parse_type_string(type_str)
    except Exception as exc:
        raise type_parse_error(type_str, str(exc)) from exc

    type_obj = parsed[0] if isinstance(parsed, tuple) else parsed
    before_type = str(getattr(var, "type", None) or getattr(var, "type_str", "") or "")

    with undo_transaction(bv):
        if hasattr(bv, "retype_variable"):
            # Mock path — bv.retype_variable handles _record_undo
            func_start = getattr(func, "start", None)
            var_storage = getattr(var, "storage", None)
            bv.retype_variable(func_start, var_storage, str(type_obj))
        else:
            # Real BN: setter accepts a Type object and auto-records undo
            var.type = type_obj

    after_type = str(type_obj)
    return {
        "function": getattr(func, "name", None),
        "var_name": var_name,
        "before_type": before_type,
        "after_type": after_type,
    }
