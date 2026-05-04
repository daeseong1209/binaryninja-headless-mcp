"""Backend-agnostic helpers shared by tool modules.

Wraps the small differences between the real binaryninja API and the mock
backend so individual tool functions stay short.
"""

from __future__ import annotations

from typing import Any

from ..session import Session
from ..supervisor import BinaryNotFoundError, Supervisor
from ..utils import parse_address


def get_session(supervisor: Supervisor, binary_id: str) -> Session:
    """Look up an open session, raising a clean ValueError if missing."""
    try:
        return supervisor.get(binary_id)
    except BinaryNotFoundError as exc:
        raise ValueError(f"unknown binary_id: {binary_id}") from exc


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

    raise ValueError(f"function not found: {addr_or_name!r}")


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
        raise ValueError(f"unknown IL level: {level!r} (expected LLIL/MLIL/HLIL)")
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
