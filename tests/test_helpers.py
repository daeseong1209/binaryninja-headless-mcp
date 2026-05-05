"""Unit tests for tools._helpers.

Covers paths that the mock backend doesn't naturally exercise — in particular
the il_text() fallback that iterates basic blocks when str(il_func) returns
the LLIL/MLIL repr instead of textual IL (real Binary Ninja behavior).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from binja_mcp.tools._helpers import (
    function_to_summary,
    hex_or_none,
    il_text,
)


def test_hex_or_none_handles_none_and_int():
    assert hex_or_none(None) is None
    assert hex_or_none(0) == "0x0"
    assert hex_or_none(0x401234) == "0x401234"


# --- il_text fallback for real-BN-style IL repr ----------------------------


@dataclass
class _StubInstr:
    address: int
    text: str

    def __str__(self) -> str:  # noqa: D401 - matches BN ILInstruction
        return self.text


class _StubBB:
    def __init__(self, instructions):
        self._instructions = instructions

    def __iter__(self):
        return iter(self._instructions)


class _StubILFunction:
    """Mimics binaryninja.LowLevelILFunction:
    - str() returns ``<LowLevelILFunction: ...>`` (repr-style)
    - basic_blocks yields blocks of instructions with .address
    """

    def __init__(self, basic_blocks):
        self.basic_blocks = basic_blocks

    def __str__(self) -> str:
        return "<LowLevelILFunction: x86_64@0x401000>"


def test_il_text_falls_back_to_basic_block_iteration():
    bb = _StubBB(
        [
            _StubInstr(0x401000, "rax = 1"),
            _StubInstr(0x401005, "ret"),
        ]
    )
    func = SimpleNamespace(llil=_StubILFunction([bb]))

    text = il_text(func, "LLIL")

    assert "<LowLevelILFunction" not in text
    assert "0x401000: rax = 1" in text
    assert "0x401005: ret" in text


def test_il_text_uses_str_for_hlil_like_objects():
    """If str(il) already returns text, we keep it as-is."""
    func = SimpleNamespace(hlil="int main() { return 0; }\n")
    assert il_text(func, "HLIL") == "int main() { return 0; }\n"


def test_il_text_invalid_level_raises():
    with pytest.raises(ValueError, match="unknown IL level"):
        il_text(SimpleNamespace(), "XLIL")


def test_il_text_missing_il_raises():
    func = SimpleNamespace(hlil=None)
    with pytest.raises(ValueError, match="has no HLIL"):
        il_text(func, "HLIL")


# --- function_to_summary defensiveness -------------------------------------


def test_function_to_summary_real_bn_style():
    """Real BN exposes start/address_ranges/basic_blocks/parameter_vars."""
    bb = SimpleNamespace(start=0x401000)
    addr_range = SimpleNamespace(end=0x401040)
    func = SimpleNamespace(
        name="main",
        start=0x401000,
        basic_blocks=[bb, bb, bb],
        address_ranges=[addr_range],
        parameter_vars=["a", "b"],
    )
    summary = function_to_summary(func)
    assert summary["name"] == "main"
    assert summary["start"] == "0x401000"
    assert summary["end"] == "0x401040"
    assert summary["basic_block_count"] == 3
    assert summary["parameter_count"] == 2


# ---------------------------------------------------------------------------
# _func_disasm: real-BN-style basic_block iteration
# ---------------------------------------------------------------------------

try:
    import importlib.util

    _DECOMPILE_AVAILABLE = importlib.util.find_spec("binja_mcp.tools.decompile") is not None
except Exception:
    _DECOMPILE_AVAILABLE = False

_skip_if_no_decompile = pytest.mark.skipif(
    not _DECOMPILE_AVAILABLE, reason="binja_mcp.tools.decompile not importable"
)


class _StubToken:
    """Mimics a binaryninja InstructionTextToken."""

    def __init__(self, text: str) -> None:
        self._text = text

    def __str__(self) -> str:
        return self._text


class _StubBBDisasm:
    """Yields (tokens, length) pairs like a real BN basic block."""

    def __init__(self, entries):
        # entries: list of (token_list, length)
        self._entries = entries

    def __iter__(self):
        return iter(self._entries)


class _StubFuncDisasm:
    """Minimal stand-in for a BN Function with basic_blocks."""

    def __init__(self, basic_blocks, start: int) -> None:
        self.basic_blocks = basic_blocks
        self.start = start
        # No _disasm attribute so _func_disasm falls through to basic_block path

    @property
    def _disasm(self):  # noqa: D401
        raise AttributeError("no _disasm")


@_skip_if_no_decompile
def test_func_disasm_basic_block_iteration():
    """_func_disasm should format 0x<addr>: <tokens> lines from basic blocks."""
    from binja_mcp.tools.decompile import _func_disasm as func_disasm

    tokens0 = [_StubToken("push"), _StubToken(" "), _StubToken("rbp")]
    tokens1 = [_StubToken("mov"), _StubToken(" "), _StubToken("rsp, rbp")]

    bb = _StubBBDisasm(
        [
            (tokens0, 1),  # instruction length 1
            (tokens1, 3),  # instruction length 3
        ]
    )
    bb.start = 0x401000  # basic block start address — set after construction

    # SimpleNamespace without _disasm forces the basic_block iteration path
    func = SimpleNamespace(basic_blocks=[bb])

    result = func_disasm(None, func)
    assert "0x401000" in result
    assert "push rbp" in result
    assert "0x401001" in result  # addr advances by length=1
    assert "mov rsp, rbp" in result


@_skip_if_no_decompile
def test_func_disasm_uses_prebuilt_disasm_string():
    """_func_disasm returns _disasm directly when available (mock path)."""
    from binja_mcp.tools.decompile import _func_disasm as func_disasm

    func = SimpleNamespace(_disasm="nop\nret\n", basic_blocks=[])
    result = func_disasm(None, func)
    assert result == "nop\nret\n"


# ---------------------------------------------------------------------------
# _raw_disasm: BinaryView.get_disassembly path
# ---------------------------------------------------------------------------


@_skip_if_no_decompile
def test_raw_disasm_multi_line():
    """_raw_disasm should produce one line per instruction within the range."""
    from binja_mcp.tools.decompile import _raw_disasm

    instructions = {
        0x1000: ("nop", 1),
        0x1001: ("push rbp", 1),
        0x1002: ("mov rax, 0", 4),
        0x1006: ("ret", 1),
    }

    def get_disassembly(addr):
        entry = instructions.get(addr)
        return entry[0] if entry else None

    def get_instruction_length(addr):
        entry = instructions.get(addr)
        return entry[1] if entry else 1

    bv = SimpleNamespace(
        get_disassembly=get_disassembly,
        get_instruction_length=get_instruction_length,
    )

    result = _raw_disasm(bv, 0x1000, 7)  # 7 bytes covers nop+push+mov (1+1+4=6 < 7)
    assert "0x1000: nop" in result
    assert "0x1001: push rbp" in result
    assert "0x1002: mov rax, 0" in result


@_skip_if_no_decompile
def test_raw_disasm_get_disassembly_exception_yields_no_disasm():
    """If get_disassembly raises, _raw_disasm should stop and return what it has."""
    from binja_mcp.tools.decompile import _raw_disasm

    call_count = {"n": 0}

    def get_disassembly(addr):
        if call_count["n"] == 0:
            call_count["n"] += 1
            return "nop"
        raise RuntimeError("BN crashed")

    bv = SimpleNamespace(get_disassembly=get_disassembly)
    result = _raw_disasm(bv, 0x1000, 32)
    # Should have at least the first line, then stop (no crash)
    assert isinstance(result, str)


@_skip_if_no_decompile
def test_raw_disasm_get_instruction_length_exception_uses_step_1():
    """If get_instruction_length raises, cursor must advance by 1."""
    from binja_mcp.tools.decompile import _raw_disasm

    addrs_seen = []

    def get_disassembly(addr):
        addrs_seen.append(addr)
        if len(addrs_seen) > 3:
            return None  # stop after 3 instructions
        return f"instr_{addr:#x}"

    def get_instruction_length(addr):
        raise RuntimeError("length API broken")

    bv = SimpleNamespace(
        get_disassembly=get_disassembly,
        get_instruction_length=get_instruction_length,
    )

    result = _raw_disasm(bv, 0x2000, 32)
    # Addresses should increment by 1 each time
    assert addrs_seen[0] == 0x2000
    assert addrs_seen[1] == 0x2001
    assert addrs_seen[2] == 0x2002
    assert "instr_0x2000" in result


# ---------------------------------------------------------------------------
# xrefs: ref.function object branch
# ---------------------------------------------------------------------------


def test_xrefs_to_ref_function_object(tmp_path):
    """get_xrefs_to should extract function name from ref.function.name."""
    from binja_mcp.supervisor import Supervisor
    from binja_mcp.tools import xrefs as t_xrefs

    # Stub reference with a .function object (real BN style)
    class _StubRef:
        address = 0x401100
        function = SimpleNamespace(name="caller_func")

    # Create a temp binary file the mock backend will accept
    tmp_bin = tmp_path / "sample.bin"
    tmp_bin.write_bytes(b"\x7fELF" + b"\x00" * 64)

    sup = Supervisor(force_mock=True)
    try:
        binary_id = sup.open(str(tmp_bin))
        session = sup.get(binary_id)
        bv = session.bv

        target_addr = bv.entry_point

        # Inject a stub reference that carries a .function object
        bv._xrefs_to[target_addr] = [_StubRef()]

        ctx = SimpleNamespace(
            request_context=SimpleNamespace(
                lifespan_context=SimpleNamespace(supervisor=sup)
            )
        )

        result = t_xrefs.get_xrefs_to(binary_id, f"0x{target_addr:x}", ctx)
        assert len(result["items"]) >= 1
        assert result["items"][0]["function"] == "caller_func"
    finally:
        sup.close_all()
