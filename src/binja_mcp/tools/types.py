"""Type system tools — get/define types and data variables."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import invalid_address, type_parse_error
from ..registry import tool
from ..server import get_supervisor
from ..utils import parse_address
from ._helpers import get_session, hex_or_none, undo_transaction


@tool()
def define_data_var(binary_id: str, addr: str, type_str: str, ctx: Context) -> dict[str, Any]:
    """Define a typed data variable at the address.

    Parses type_str (e.g., 'uint64_t', 'char*', 'struct Foo*') via BN's
    parse_type_string and registers the variable. Records an undo entry.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    try:
        address = parse_address(addr)
    except ValueError as exc:
        raise invalid_address(addr) from exc

    if not type_str or not isinstance(type_str, str):
        raise ValueError("type_str must be a non-empty string")

    try:
        parsed = bv.parse_type_string(type_str)
    except Exception as exc:
        raise type_parse_error(type_str, str(exc)) from exc

    type_obj = parsed[0] if isinstance(parsed, tuple) else parsed

    # Wrap in an explicit undo transaction so real BN records a roll-backable entry.
    with undo_transaction(bv):
        bv.define_user_data_var(address, type_obj)

    return {
        "address": hex_or_none(address),
        "type": str(type_obj),
    }


@tool()
def get_type(binary_id: str, name: str, ctx: Context) -> dict[str, Any]:
    """Look up a named type definition. Returns definition=None when not found."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    if not hasattr(bv, "get_type_by_name"):
        return {"name": name, "definition": None}

    type_obj = bv.get_type_by_name(name)
    if type_obj is None:
        return {"name": name, "definition": None}
    return {
        "name": name,
        "definition": str(type_obj),
    }


@tool()
def define_type(binary_id: str, name: str, source: str, ctx: Context) -> dict[str, Any]:
    """Define one or more user types from a C-style source string.

    The source can declare a single type (e.g. 'typedef struct {int x;} Foo;')
    or multiple. The 'name' argument selects which parsed type to register
    under that name. Records an undo entry.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    if not name:
        raise ValueError("name must be non-empty")
    if not source:
        raise ValueError("source must be non-empty")

    # Real Binary Ninja 5.x exposes parse_types_from_source on Platform, not on
    # BinaryView. The mock backend defines it on MockBinaryView. Try BV first,
    # then fall back to bv.platform.
    parser = getattr(bv, "parse_types_from_source", None)
    if parser is None:
        platform = getattr(bv, "platform", None)
        parser = getattr(platform, "parse_types_from_source", None) if platform else None

    if parser is None:
        raise type_parse_error(source, "backend does not expose parse_types_from_source")

    try:
        result = parser(source)
    except Exception as exc:
        raise type_parse_error(source, str(exc)) from exc

    if result is None:
        raise type_parse_error(source, "no types parsed")

    # Normalise keys: real BN returns QualifiedName objects, not plain strings.
    raw_types = getattr(result, "types", None) or {}
    types_map: dict[str, Any] = {
        str(k): v for k, v in (raw_types.items() if hasattr(raw_types, "items") else [])
    }

    if not types_map:
        raise type_parse_error(source, "no types parsed (result.types is empty)")

    if name in types_map:
        type_obj = types_map[name]
    elif len(types_map) == 1:
        # Single-type source — use first entry regardless of name mismatch
        type_obj = next(iter(types_map.values()))
    else:
        raise type_parse_error(
            source,
            f"name {name!r} not in parsed types {sorted(types_map.keys())}",
        )

    # Wrap in an explicit undo transaction so real BN records a roll-backable entry.
    with undo_transaction(bv):
        bv.define_user_type(name, type_obj)

    return {
        "name": name,
        "definition": str(type_obj),
    }
