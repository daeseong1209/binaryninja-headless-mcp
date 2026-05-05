"""Backend-agnostic helpers shared by tool modules.

Wraps the small differences between the real binaryninja API and the mock
backend so individual tool functions stay short.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from ..errors import binary_not_found, function_not_found, invalid_il_level, symbol_not_found
from ..session import Session
from ..supervisor import BinaryNotFoundError, Supervisor
from ..utils import parse_address

_SYMBOL_TYPE_FILTERS: dict[str, tuple[str, ...]] = {
    "function": ("FunctionSymbol",),
    "imported_function": ("ImportedFunctionSymbol",),
    "import_address": ("ImportAddressSymbol",),
    "imports": ("ImportedFunctionSymbol", "ImportAddressSymbol"),
    "data": ("DataSymbol",),
    "external": ("ExternalSymbol",),
    "library_function": ("LibraryFunctionSymbol",),
}


def resolve_symbol_types(filter_name: str) -> tuple[Any, ...]:
    """Resolve a symbol-type filter string to backend-appropriate enum values.

    Prefers real ``binaryninja.SymbolType`` enum objects; falls back to the
    ``MockSymbolType`` IntEnum (whose integer values match real BN exactly).
    Raises ValueError for unknown filter names.
    """
    name = filter_name.lower().replace("-", "_")
    enum_names = _SYMBOL_TYPE_FILTERS.get(name)
    if enum_names is None:
        raise ValueError(
            f"unknown symbol_type: {name!r}; valid: {sorted(_SYMBOL_TYPE_FILTERS.keys())}"
        )
    try:
        from binaryninja import SymbolType  # type: ignore[import]

        return tuple(getattr(SymbolType, n) for n in enum_names if hasattr(SymbolType, n))
    except ImportError:
        from ..mock_backend import MockSymbolType

        return tuple(
            getattr(MockSymbolType, n) for n in enum_names if hasattr(MockSymbolType, n)
        )


def symbol_to_dict(s: Any) -> dict[str, Any]:
    """Convert a Symbol-like object into a JSON-friendly dict.

    Used by both list_symbols (symbols.py) and list_imports/list_exports
    (sections.py). Tolerates missing attributes from either backend.
    """
    sym_type = getattr(s, "type", None)
    return {
        "name": getattr(s, "name", "<unnamed>"),
        "full_name": getattr(s, "full_name", "") or "",
        "address": hex_or_none(getattr(s, "address", None)),
        "type": getattr(sym_type, "name", str(sym_type)) if sym_type is not None else None,
        "auto": bool(getattr(s, "auto", True)),
        "ordinal": int(getattr(s, "ordinal", 0) or 0),
    }


@contextmanager
def undo_transaction(bv: Any):
    """Wrap a write block in a Binary Ninja undo group.

    If the mock backend already has an open undo state (e.g. the caller
    invoked ``begin_undo`` explicitly), this nests cleanly: writes are appended
    to that outer state and we do NOT begin/commit our own group. The outer
    caller is responsible for commit.

    On real BN, ``_open_undo_states`` is absent so ``has_outer`` is always
    False and we always begin+commit our own group (existing behaviour).
    """
    open_states = getattr(bv, "_open_undo_states", None)
    has_outer = bool(open_states)  # truthy only on mock with an outer state open

    state_id = None
    if not has_outer and hasattr(bv, "begin_undo_actions"):
        state_id = bv.begin_undo_actions()
    try:
        yield state_id
    finally:
        # Only commit if WE opened the state (not an outer caller's group)
        if state_id is not None and hasattr(bv, "commit_undo_actions"):
            try:
                bv.commit_undo_actions(state_id)
            except Exception:
                pass  # best-effort; don't mask the original error


def get_session(supervisor: Supervisor, binary_id: str) -> Session:
    """Look up an open session, raising a clean ValueError if missing."""
    try:
        return supervisor.get(binary_id)
    except BinaryNotFoundError:
        raise binary_not_found(binary_id) from None


def find_function(bv: Any, addr_or_name: str | int) -> Any:
    """Locate a function by address (int/hex string) or symbol name.

    Works against both real BN BinaryView and the mock backend.
    Raises ValueError if nothing matches.
    """
    # 1. Try as an address
    addr: int | None = None
    try:
        if isinstance(addr_or_name, int):
            addr = addr_or_name
        elif isinstance(addr_or_name, str) and (
            addr_or_name.lower().startswith("0x") or addr_or_name.isdigit()
        ):
            addr = parse_address(addr_or_name)
    except ValueError:
        addr = None

    if addr is not None:
        func = bv.get_function_at(addr)
        if func is None:
            # Some BNs return None for an inner address — try containing
            getter = getattr(bv, "get_functions_containing", None)
            if getter is not None:
                matches = getter(addr)
                if matches:
                    return matches[0]
        if func is not None:
            return func

    # 2. Try as a name. Mock exposes get_function_by_name; real BN uses symbols.
    name = addr_or_name if isinstance(addr_or_name, str) else str(addr_or_name)

    by_name = getattr(bv, "get_function_by_name", None)
    if by_name is not None:
        func = by_name(name)
        if func is not None:
            return func

    sym_getter = getattr(bv, "get_symbols_by_name", None)
    if sym_getter is not None:
        for sym in sym_getter(name) or []:
            sym_addr = getattr(sym, "address", None)
            if sym_addr is None:
                continue
            func = bv.get_function_at(sym_addr)
            if func is not None:
                return func

    raise function_not_found(addr_or_name)


def find_symbol(bv: Any, target: Any) -> Any:
    """Find a symbol by address (int/hex string) or name. Sister to find_function.

    Returns the first matching symbol or raises BinjaError(SYMBOL_NOT_FOUND).
    """
    # Address path
    addr: int | None = None
    try:
        if isinstance(target, int):
            addr = target
        elif isinstance(target, str) and (
            target.lower().startswith("0x") or target.isdigit()
        ):
            addr = parse_address(target)
    except ValueError:
        addr = None

    syms = list(bv.get_symbols()) if hasattr(bv, "get_symbols") else []

    if addr is not None:
        for s in syms:
            if getattr(s, "address", None) == addr:
                return s

    # Name path
    name = target if isinstance(target, str) else str(target)
    for s in syms:
        if getattr(s, "name", None) == name or getattr(s, "full_name", None) == name:
            return s

    raise symbol_not_found(target)


def function_to_summary(func: Any) -> dict[str, Any]:
    """Extract a small JSON-friendly summary of a function."""
    name = getattr(func, "name", None) or "<unnamed>"
    start = getattr(func, "start", None)
    if start is None:
        # Real BN: function.start is property; try first basic block
        bbs = getattr(func, "basic_blocks", None)
        if bbs:
            start = getattr(bbs[0], "start", None)
    end = getattr(func, "end", None)
    if end is None:
        ranges = getattr(func, "address_ranges", None)
        if ranges:
            try:
                end = max(getattr(r, "end", 0) for r in ranges)
            except Exception:
                end = None
    bb_count = getattr(func, "basic_block_count", None)
    if bb_count is None:
        bbs = getattr(func, "basic_blocks", None)
        bb_count = len(bbs) if bbs is not None else None
    param_count = getattr(func, "parameter_count", None)
    if param_count is None:
        params = getattr(func, "parameter_vars", None)
        if params is not None:
            try:
                param_count = len(list(params))
            except Exception:
                param_count = None

    return {
        "name": name,
        "start": hex_or_none(start),
        "end": hex_or_none(end),
        "basic_block_count": bb_count,
        "parameter_count": param_count,
    }


def hex_or_none(value: int | None) -> str | None:
    if value is None:
        return None
    return f"0x{value:x}"


def il_text(func: Any, level: str) -> str:
    """Return IL text for the requested level (LLIL, MLIL, HLIL).

    Real Binary Ninja's HighLevelILFunction renders nicely via str(), but
    LowLevelILFunction / MediumLevelILFunction fall back to repr like
    ``<LowLevelILFunction: ...>``. For those we iterate basic blocks and
    stringify each instruction, prefixing with its address.
    """
    level_lower = level.lower()
    attr = {"llil": "llil", "mlil": "mlil", "hlil": "hlil"}.get(level_lower)
    if attr is None:
        raise invalid_il_level(level)
    il = getattr(func, attr, None)
    if il is None:
        raise ValueError(f"function has no {level.upper()}")

    text = str(il)
    if not text.startswith("<") or "ILFunction" not in text:
        return text

    # Real BN: iterate basic blocks and stringify instructions
    lines: list[str] = []
    try:
        for bb in il.basic_blocks:
            for instr in bb:
                addr = getattr(instr, "address", None)
                if addr is not None:
                    lines.append(f"{addr:#x}: {instr}")
                else:
                    lines.append(str(instr))
    except Exception:
        try:
            for instr in il.instructions:
                addr = getattr(instr, "address", None)
                if addr is not None:
                    lines.append(f"{addr:#x}: {instr}")
                else:
                    lines.append(str(instr))
        except Exception:
            return text  # last-ditch fallback

    return "\n".join(lines) if lines else text


# ---------------------------------------------------------------------------
# BinaryView adapter helpers — normalise real BN vs mock attribute differences
# Defined here for future import by info.py and other tool modules.
# ---------------------------------------------------------------------------


def get_arch_name(bv: Any) -> str | None:
    """Return architecture name from real BN (bv.arch.name) or mock (bv.arch_name)."""
    arch = getattr(bv, "arch", None)
    if arch is not None:
        name = getattr(arch, "name", None)
        if name is not None:
            return str(name)
    # Mock backend may expose arch_name directly
    direct = getattr(bv, "arch_name", None)
    if direct is not None:
        return str(direct)
    return None


def get_platform_name(bv: Any) -> str | None:
    """Return platform name from real BN (bv.platform.name) or mock (bv.platform_name)."""
    platform = getattr(bv, "platform", None)
    if platform is not None:
        name = getattr(platform, "name", None)
        if name is not None:
            return str(name)
    direct = getattr(bv, "platform_name", None)
    if direct is not None:
        return str(direct)
    return None


def get_function_count(bv: Any) -> int | None:
    """Return number of functions from real BN or mock BinaryView."""
    functions = getattr(bv, "functions", None)
    if functions is not None:
        try:
            return len(functions)
        except TypeError:
            try:
                return sum(1 for _ in functions)
            except Exception:
                pass
    return None
