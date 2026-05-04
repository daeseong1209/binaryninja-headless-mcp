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
