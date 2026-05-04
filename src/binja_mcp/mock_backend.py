"""Mock Binary Ninja backend for tests and license-free CI.

Implements just enough of the binaryninja API surface that the MCP tools can
exercise their code paths without a real Binary Ninja installation. Enabled
automatically when binaryninja cannot be imported, or forced via
BINJA_MCP_FORCE_MOCK=1.

Mock binary contents are derived from the file path or constructed
in-memory so tests are reproducible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MockSymbol:
    name: str
    address: int


@dataclass
class MockReference:
    address: int
    function_name: str | None = None


@dataclass
class MockString:
    value: str
    address: int
    length: int = 0

    def __post_init__(self) -> None:
        if self.length == 0:
            self.length = len(self.value)


@dataclass
class MockFunction:
    name: str
    start: int
    end: int
    parameter_count: int = 0
    basic_block_count: int = 1
    _hlil: str = "// mock HLIL\n"
    _mlil: str = "// mock MLIL\n"
    _llil: str = "// mock LLIL\n"
    _disasm: str = "nop\n"

    @property
    def hlil(self) -> str:
        return self._hlil

    @property
    def mlil(self) -> str:
        return self._mlil

    @property
    def llil(self) -> str:
        return self._llil


@dataclass
class MockFile:
    filename: str

    def close(self) -> None:
        return None


@dataclass
class MockBinaryView:
    """A minimal stand-in for binaryninja.BinaryView."""

    path: str
    arch_name: str = "x86_64"
    platform_name: str = "linux-x86_64"
    entry_point: int = 0x1000
    file: MockFile = field(init=False)
    functions: list[MockFunction] = field(default_factory=list)
    strings: list[MockString] = field(default_factory=list)
    symbols: list[MockSymbol] = field(default_factory=list)
    _xrefs_to: dict[int, list[MockReference]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.file = MockFile(self.path)
        if not self.functions:
            self._populate_default()

    def _populate_default(self) -> None:
        # Deterministic mock contents seeded from path
        seed = int(hashlib.sha1(self.path.encode("utf-8")).hexdigest()[:8], 16)
        base = 0x1000 + (seed & 0xFF) * 0x10
        self.entry_point = base
        names = ["_start", "main", "init", "helper_func", "compute", "encrypt", "decode"]
        for i, name in enumerate(names):
            start = base + i * 0x40
            end = start + 0x30
            self.functions.append(
                MockFunction(
                    name=name,
                    start=start,
                    end=end,
                    parameter_count=i % 3,
                    basic_block_count=1 + (i % 4),
                    _hlil=f"// HLIL of {name}\nint {name}() {{ return {i}; }}\n",
                    _mlil=f"// MLIL of {name}\nreturn {i}\n",
                    _llil=f"// LLIL of {name}\nrax = {i}; ret\n",
                    _disasm=f"; {name}\nmov rax, {i}\nret\n",
                )
            )
            self.symbols.append(MockSymbol(name=name, address=start))
            self._xrefs_to[start] = [
                MockReference(address=base + 0x100 + i * 8, function_name="_start"),
            ]
        self.strings.extend(
            [
                MockString(value="Hello, world", address=base + 0x500),
                MockString(value="error: %s\n", address=base + 0x520),
                MockString(value="/etc/passwd", address=base + 0x540),
                MockString(value="binja-mcp", address=base + 0x560),
            ]
        )

    # API surface used by tools ------------------------------------------------

    def get_function_at(self, addr: int) -> MockFunction | None:
        for f in self.functions:
            if f.start == addr:
                return f
        return None

    def get_functions_containing(self, addr: int) -> list[MockFunction]:
        return [f for f in self.functions if f.start <= addr < f.end]

    def get_function_by_name(self, name: str) -> MockFunction | None:
        for f in self.functions:
            if f.name == name:
                return f
        return None

    def get_code_refs(self, addr: int) -> list[MockReference]:
        return list(self._xrefs_to.get(addr, []))

    def get_strings(self) -> list[MockString]:
        return list(self.strings)

    def read(self, addr: int, length: int) -> bytes:
        # Return a deterministic but uninteresting buffer
        return bytes((addr + i) & 0xFF for i in range(length))


def load(path: str, update_analysis: bool = True) -> MockBinaryView:  # noqa: ARG001
    """Mock equivalent of binaryninja.load(path)."""
    p = Path(path)
    return MockBinaryView(path=str(p))
