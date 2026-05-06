"""Function variable tools: list, rename, and set type for params/locals."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import type_parse_error
from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import (
    _variable_identity,
    find_function,
    find_variable,
    get_session,
    iter_function_variables,
    undo_transaction,
)


def _source_type_name(v: Any) -> str:
    """Return a string-stable VariableSourceType name (Stack/Register/Flag/...)."""
    st = getattr(v, "source_type", None)
    if st is None:
        return "Stack"  # mock or older BN — treat as user-meaningful
    name = getattr(st, "name", None)
    if isinstance(name, str):
        return name.replace("VariableSourceType", "") or name
    return str(st)


def _is_safe_target(v: Any, param_ids: set[tuple[Any, ...]]) -> bool:
    """True for parameters and stack locals; False for register/flag temporaries.

    Real BN's ``func.vars`` includes compiler-generated register temporaries
    (``rax``, ``rax_1``, ``cond:0``, ...) which the LLM should not rename or
    retype — doing so corrupts analysis state. Parameters are always safe
    (they may use register storage on x64 calling conventions).
    """
    if _variable_identity(v) in param_ids:
        return True
    return _source_type_name(v).startswith("Stack")


def _variable_to_dict(v: Any, fallback_index: int, *, kind: str) -> dict[str, Any]:
    var_type = getattr(v, "type", None) or getattr(v, "type_str", None)
    type_str = str(var_type) if var_type is not None else ""

    storage = getattr(v, "storage", None)
    index = getattr(v, "index", None)
    if index is None:
        index = fallback_index

    return {
        "name": getattr(v, "name", "<unnamed>"),
        "type": type_str,
        "kind": kind,
        "index": int(index),
        "storage": int(storage) if isinstance(storage, int) else storage,
        "source_type": _source_type_name(v),
    }


@tool()
def list_function_variables(
    binary_id: str,
    function: str | int,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
    include_temporaries: bool = False,
) -> dict[str, Any]:
    """List parameters and stack locals of a function (paginated).

    Default output includes parameters + stack locals only.
    Real BN's ``func.vars`` also surfaces compiler-generated register and
    flag temporaries (``rax``, ``cond:0``, ...) which are unsafe to mutate;
    pass ``include_temporaries=True`` to see them (read-only inspection).

    Each item: ``{name, type, kind, index, storage, source_type}`` where
    ``kind`` ∈ {"parameter", "local"} and ``source_type`` is the BN
    VariableSourceType name (e.g. "Stack", "Register", "Flag").
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    func = find_function(bv, function)
    param_ids: set[tuple[Any, ...]] = {
        _variable_identity(p) for p in (getattr(func, "parameter_vars", None) or [])
    }

    items: list[dict[str, Any]] = []
    for i, v in enumerate(iter_function_variables(func)):
        if not include_temporaries and not _is_safe_target(v, param_ids):
            continue
        kind = "parameter" if _variable_identity(v) in param_ids else "local"
        items.append(_variable_to_dict(v, fallback_index=i, kind=kind))

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

    params = getattr(func, "parameter_vars", None) or []
    param_ids = {_variable_identity(p) for p in params}
    if not _is_safe_target(var, param_ids):
        # Refuse to rename register/flag temporaries — they're compiler-generated
        # and mutating them corrupts analysis state.
        raise ValueError(
            f"variable {var_name!r} is a {_source_type_name(var)} temporary; "
            "rename_variable only supports parameters and stack locals"
        )

    var_storage = getattr(var, "storage", None)
    kind = "parameter" if _variable_identity(var) in param_ids else "local"

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

    params = getattr(func, "parameter_vars", None) or []
    param_ids = {_variable_identity(p) for p in params}
    if not _is_safe_target(var, param_ids):
        raise ValueError(
            f"variable {var_name!r} is a {_source_type_name(var)} temporary; "
            "set_variable_type only supports parameters and stack locals"
        )

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
