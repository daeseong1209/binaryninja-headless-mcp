"""Decompilation, IL, and disassembly tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import invalid_address, invalid_il_level
from ..registry import tool
from ..server import get_supervisor
from ..utils import parse_address, truncate_text
from ._helpers import find_function, function_to_summary, get_session, il_text


@tool()
def decompile(binary_id: str, addr_or_name: str, ctx: Context) -> dict[str, Any]:
    """Return HLIL (high-level IL) decompilation for a function.

    Args:
        binary_id: handle from open_binary.
        addr_or_name: function address (int / "0x1234") or symbol name.

    Returns:
        Function summary plus HLIL text (truncated if very large).
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    func = find_function(session.bv, addr_or_name)
    text_payload = truncate_text(il_text(func, "HLIL"))
    return {
        "function": function_to_summary(func),
        "il_level": "HLIL",
        **text_payload,
    }


@tool()
def get_il(
    binary_id: str,
    addr_or_name: str,
    ctx: Context,
    level: str = "HLIL",
) -> dict[str, Any]:
    """Return LLIL, MLIL, or HLIL text for a function.

    Args:
        level: one of "LLIL", "MLIL", "HLIL" (case-insensitive).
    """
    if not isinstance(level, str):
        raise invalid_il_level(level)
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    func = find_function(session.bv, addr_or_name)
    text_payload = truncate_text(il_text(func, level))
    return {
        "function": function_to_summary(func),
        "il_level": level.upper(),
        **text_payload,
    }


@tool()
def get_disasm(
    binary_id: str,
    addr_or_name: str,
    ctx: Context,
    length: int = 64,
) -> dict[str, Any]:
    """Return disassembly for a function or starting at an address.

    Args:
        addr_or_name: function name, function address, or arbitrary address.
        length: bytes to disassemble when an arbitrary address is given.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    if length <= 0:
        raise ValueError(f"length must be > 0, got {length}")

    # Try function lookup first; fall back to raw address disassembly
    try:
        func = find_function(bv, addr_or_name)
    except ValueError:
        func = None

    if func is not None:
        # Mock provides _disasm field; real BN exposes via instruction iteration
        disasm = _func_disasm(bv, func)
        return {
            "function": function_to_summary(func),
            **truncate_text(disasm),
        }

    # Raw address path
    try:
        addr = parse_address(addr_or_name)
    except ValueError:
        raise invalid_address(addr_or_name) from None

    text = _raw_disasm(bv, addr, length)
    return {
        "address": f"0x{addr:x}",
        "length": length,
        **truncate_text(text),
    }


def _func_disasm(bv: Any, func: Any) -> str:
    """Concatenate disassembly text for a function.

    Mock backend stores a prepared `_disasm` string. Real Binary Ninja
    exposes basic blocks that yield ``(tokens, length)`` pairs per instruction.
    """
    pre = getattr(func, "_disasm", None)
    if pre:
        return pre

    parts: list[str] = []
    for bb in getattr(func, "basic_blocks", None) or []:
        addr = getattr(bb, "start", None)
        for entry in bb:
            if isinstance(entry, tuple) and entry:
                line = "".join(str(t) for t in entry[0])
                step = entry[1] if len(entry) >= 2 else 0
            else:
                line = str(entry)
                step = 0
            parts.append(f"0x{addr:x}: {line}" if addr is not None else line)
            if addr is not None and step:
                addr += step
    return "\n".join(parts) if parts else "<no disassembly available>"


def _raw_disasm(bv: Any, addr: int, length: int) -> str:
    """Fall back to byte-by-byte disassembly via BinaryView.get_disassembly."""
    get_dis = getattr(bv, "get_disassembly", None)
    if get_dis is not None:
        out: list[str] = []
        cursor = addr
        end = addr + length
        # Real BN: get_disassembly(addr) returns a single-line string;
        # use get_instruction_length to advance.
        get_len = getattr(bv, "get_instruction_length", None)
        while cursor < end:
            try:
                line = get_dis(cursor)
            except Exception:
                break
            if not line:
                break
            out.append(f"0x{cursor:x}: {line}")
            step = 1
            if get_len is not None:
                try:
                    step = max(1, int(get_len(cursor)))
                except Exception:
                    step = 1
            cursor += step
        return "\n".join(out) if out else "<no disassembly>"

    # Mock fallback: read bytes and pretty-print
    raw = bv.read(addr, length) if hasattr(bv, "read") else b""
    return " ".join(f"{b:02x}" for b in raw)
