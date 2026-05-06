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
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any


class MockSymbolType(IntEnum):
    FunctionSymbol = 0
    ImportAddressSymbol = 1
    ImportedFunctionSymbol = 2
    DataSymbol = 3
    ImportedDataSymbol = 4
    ExternalSymbol = 5
    LibraryFunctionSymbol = 6


@dataclass
class MockSymbol:
    name: str
    address: int
    type: MockSymbolType = MockSymbolType.FunctionSymbol
    full_name: str = ""
    ordinal: int = 0
    is_export: bool = False


@dataclass
class MockSegment:
    start: int
    end: int
    data_offset: int = 0
    data_length: int = 0
    readable: bool = True
    writable: bool = False
    executable: bool = True


@dataclass
class MockSection:
    name: str
    start: int
    end: int
    semantics: str = "CodeSectionSemantics"


@dataclass
class MockReference:
    address: int
    function_name: str | None = None
    # Real BN ReferenceSource exposes .function — populate for callgraph callers.
    function: MockFunction | None = None


@dataclass
class MockCallSite:
    """Mirrors real BN's call_site shape; only .address is consumed by tools."""

    address: int


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
    call_sites: list[MockCallSite] = field(default_factory=list)
    caller_sites: list[MockReference] = field(default_factory=list)
    arch: Any | None = None

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
class MockDataVariable:
    address: int
    type_str: str
    name: str | None = None


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
    segments: list[MockSegment] = field(default_factory=list)
    sections: dict[str, MockSection] = field(default_factory=dict)
    _xrefs_to: dict[int, list[MockReference]] = field(default_factory=dict)
    # call_site_addr -> list of resolved callee start addresses (empty == indirect)
    _callees_map: dict[int, list[int]] = field(default_factory=dict)
    data_vars: dict[int, MockDataVariable] = field(default_factory=dict)
    user_types: dict[str, str] = field(default_factory=dict)
    _undo_stack: list[dict] = field(default_factory=list, init=False, repr=False, compare=False)
    _redo_stack: list[dict] = field(default_factory=list, init=False, repr=False, compare=False)
    _open_undo_states: dict[str, list] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

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
        # Segments: .text (rx) and .data (rw)
        text_start = base
        text_end = base + 0x300
        data_start = base + 0x400
        data_end = base + 0x600
        self.segments.extend(
            [
                MockSegment(
                    start=text_start,
                    end=text_end,
                    data_offset=0,
                    data_length=text_end - text_start,
                    readable=True,
                    writable=False,
                    executable=True,
                ),
                MockSegment(
                    start=data_start,
                    end=data_end,
                    data_offset=text_end - text_start,
                    data_length=data_end - data_start,
                    readable=True,
                    writable=True,
                    executable=False,
                ),
            ]
        )
        # Sections: .text, .data, .rodata
        self.sections = {
            ".text": MockSection(
                name=".text",
                start=text_start,
                end=text_end,
                semantics="CodeSectionSemantics",
            ),
            ".data": MockSection(
                name=".data",
                start=data_start,
                end=data_end,
                semantics="ReadWriteDataSectionSemantics",
            ),
            ".rodata": MockSection(
                name=".rodata",
                start=base + 0x500,
                end=base + 0x580,
                semantics="ReadOnlyDataSectionSemantics",
            ),
        }
        # Extra symbols for list_imports/exports tests
        self.symbols.append(
            MockSymbol(
                name="printf",
                address=base + 0x800,
                type=MockSymbolType.ImportedFunctionSymbol,
                full_name="printf",
            )
        )
        self.symbols.append(
            MockSymbol(
                name="malloc",
                address=base + 0x810,
                type=MockSymbolType.ImportAddressSymbol,
                full_name="malloc",
            )
        )
        self.symbols.append(
            MockSymbol(
                name="global_var",
                address=base + 0x820,
                type=MockSymbolType.DataSymbol,
                full_name="global_var",
            )
        )
        # exported_func: FunctionSymbol with is_export=True (real BN has no
        # ExportedFunctionSymbol; we track exports via is_export flag in mock)
        self.symbols.append(
            MockSymbol(
                name="exported_func",
                address=base + 0x830,
                type=MockSymbolType.FunctionSymbol,
                full_name="exported_func",
                is_export=True,
            )
        )

        # ---- Callgraph wiring (added in v0.4) -------------------------------
        # Backfill .function on the seeded _start xrefs so get_callers can
        # synthesise a function summary; previous shape only had function_name.
        start_func = self.get_function_by_name("_start")
        if start_func is not None:
            for refs in self._xrefs_to.values():
                for r in refs:
                    if r.function is None and r.function_name == "_start":
                        r.function = start_func

        # Layer a small call graph onto the existing 7 mock functions:
        #   main -> helper_func (callsite at main.start + 0x4)
        #   main -> decode      (callsite at main.start + 0x10)
        #   helper_func -> encrypt (callsite at helper_func.start + 0x8)
        #   decode -> indirect (callsite at decode.start + 0x4, no resolved target)
        # encrypt has no outgoing calls; init has no outgoing calls.
        main_f = self.get_function_by_name("main")
        helper_f = self.get_function_by_name("helper_func")
        encrypt_f = self.get_function_by_name("encrypt")
        decode_f = self.get_function_by_name("decode")
        if main_f and helper_f and encrypt_f and decode_f:
            site_main_to_helper = main_f.start + 0x4
            site_main_to_decode = main_f.start + 0x10
            site_helper_to_encrypt = helper_f.start + 0x8
            site_decode_indirect = decode_f.start + 0x4

            main_f.call_sites = [
                MockCallSite(address=site_main_to_helper),
                MockCallSite(address=site_main_to_decode),
            ]
            helper_f.call_sites = [MockCallSite(address=site_helper_to_encrypt)]
            decode_f.call_sites = [MockCallSite(address=site_decode_indirect)]

            self._callees_map[site_main_to_helper] = [helper_f.start]
            self._callees_map[site_main_to_decode] = [decode_f.start]
            self._callees_map[site_helper_to_encrypt] = [encrypt_f.start]
            self._callees_map[site_decode_indirect] = []  # indirect

            # caller_sites mirrors call edges into each target — used by
            # get_callers to filter call-only edges from generic xrefs.
            helper_f.caller_sites.append(
                MockReference(address=site_main_to_helper, function_name="main", function=main_f)
            )
            decode_f.caller_sites.append(
                MockReference(address=site_main_to_decode, function_name="main", function=main_f)
            )
            encrypt_f.caller_sites.append(
                MockReference(
                    address=site_helper_to_encrypt,
                    function_name="helper_func",
                    function=helper_f,
                )
            )

            self._xrefs_to.setdefault(helper_f.start, []).append(
                MockReference(
                    address=site_main_to_helper, function_name="main", function=main_f
                )
            )
            self._xrefs_to.setdefault(decode_f.start, []).append(
                MockReference(
                    address=site_main_to_decode, function_name="main", function=main_f
                )
            )
            self._xrefs_to.setdefault(encrypt_f.start, []).append(
                MockReference(
                    address=site_helper_to_encrypt,
                    function_name="helper_func",
                    function=helper_f,
                )
            )

    # Undo / redo API surface --------------------------------------------------

    def begin_undo_actions(self, anonymous: bool = False) -> str:  # noqa: ARG002
        state_id = uuid.uuid4().hex
        self._open_undo_states[state_id] = []
        return state_id

    def commit_undo_actions(self, state_id: str = "") -> None:
        if not state_id:
            if not self._open_undo_states:
                return
            state_id = next(reversed(self._open_undo_states))
        if state_id not in self._open_undo_states:
            raise KeyError(state_id)
        entries = self._open_undo_states.pop(state_id)
        if entries:
            self._undo_stack.append({"id": state_id, "entries": entries})
        self._redo_stack.clear()

    def revert_undo_actions(self, state_id: str = "") -> None:
        self._open_undo_states.pop(state_id, None)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        group = self._undo_stack.pop()
        for entry in reversed(group.get("entries", [])):
            self._revert_entry(entry)
        self._redo_stack.append(group)

    def redo(self) -> None:
        if not self._redo_stack:
            return
        group = self._redo_stack.pop()
        for entry in group.get("entries", []):
            self._reapply_entry(entry)
        self._undo_stack.append(group)

    def _revert_entry(self, entry: dict) -> None:
        """Revert a single undo entry by restoring 'before' state."""
        kind = entry.get("kind")
        if kind == "rename_function":
            addr = entry["addr"]
            before = entry["before"]
            f = self.get_function_at(addr)
            if f is not None and before is not None:
                f.name = before
            for s in self.symbols:
                if s.address == addr and int(s.type) == int(MockSymbolType.FunctionSymbol):
                    s.name = before
                    break
        elif kind == "define_user_symbol":
            addr = entry["addr"]
            before = entry["before"]
            after = entry["after"]
            for i, s in enumerate(self.symbols):
                if s.address == addr and s.name == after:
                    if before is None:
                        del self.symbols[i]
                    else:
                        s.name = before
                    break
        elif kind == "define_user_data_var":
            addr = entry["addr"]
            before = entry["before"]
            if before is None:
                self.data_vars.pop(addr, None)
            else:
                type_str, name = before
                self.data_vars[addr] = MockDataVariable(address=addr, type_str=type_str, name=name)
        elif kind == "define_user_type":
            type_name = entry["type_name"]
            before = entry["before"]
            if before is None:
                self.user_types.pop(type_name, None)
            else:
                self.user_types[type_name] = before

    def _reapply_entry(self, entry: dict) -> None:
        """Re-apply a single undo entry by restoring 'after' state."""
        kind = entry.get("kind")
        if kind == "rename_function":
            addr = entry["addr"]
            after = entry["after"]
            f = self.get_function_at(addr)
            if f is not None:
                f.name = after
            for s in self.symbols:
                if s.address == addr and int(s.type) == int(MockSymbolType.FunctionSymbol):
                    s.name = after
                    break
        elif kind == "define_user_symbol":
            addr = entry["addr"]
            after = entry["after"]
            sym_type = entry.get("sym_type", MockSymbolType.DataSymbol)
            for s in self.symbols:
                if s.address == addr:
                    s.name = after
                    return
            self.symbols.append(MockSymbol(name=after, address=addr, type=sym_type))
        elif kind == "define_user_data_var":
            addr = entry["addr"]
            after = entry["after"]
            type_str, name = after
            self.data_vars[addr] = MockDataVariable(address=addr, type_str=type_str, name=name)
        elif kind == "define_user_type":
            type_name = entry["type_name"]
            after = entry["after"]
            self.user_types[type_name] = after

    def _record_undo(self, kind: str, **payload) -> None:
        """Append an entry to the most recent open undo state, or to a singleton group."""
        entry = {"kind": kind, **payload}
        if self._open_undo_states:
            latest = next(reversed(self._open_undo_states))
            self._open_undo_states[latest].append(entry)
        else:
            self._undo_stack.append({"id": "auto", "entries": [entry]})
            self._redo_stack.clear()

    # Write API — symbols / types / data vars ---------------------------------

    def rename_function(self, addr: int, new_name: str) -> bool:
        f = self.get_function_at(addr)
        if f is None:
            return False
        old = f.name
        f.name = new_name
        # Keep corresponding FunctionSymbol in sync
        for s in self.symbols:
            if s.address == addr and int(s.type) == int(MockSymbolType.FunctionSymbol):
                s.name = new_name
                break
        self._record_undo("rename_function", addr=addr, before=old, after=new_name)
        return True

    def define_user_symbol(self, sym: object) -> None:
        """Accept a symbol-like object or dict and update the symbol list."""
        if isinstance(sym, dict):
            sym_type = sym.get("type")
            addr = sym.get("address")
            name = sym.get("name")
        else:
            sym_type = getattr(sym, "type", None)
            addr = getattr(sym, "address", None)
            name = getattr(sym, "name", None)
        if addr is None or name is None:
            return
        before = None
        for s in self.symbols:
            if s.address == addr:
                before = s.name
                s.name = name
                break
        else:
            self.symbols.append(
                MockSymbol(name=name, address=addr, type=sym_type or MockSymbolType.DataSymbol)
            )
        self._record_undo("define_user_symbol", addr=addr, before=before, after=name)

    def define_user_data_var(
        self, address: int, var_type: object, name: str | None = None
    ) -> MockDataVariable:
        type_str = str(var_type) if not isinstance(var_type, str) else var_type
        before = self.data_vars.get(address)
        dv = MockDataVariable(address=address, type_str=type_str, name=name)
        self.data_vars[address] = dv
        self._record_undo(
            "define_user_data_var",
            addr=address,
            before=(before.type_str, before.name) if before else None,
            after=(type_str, name),
        )
        return dv

    def define_user_type(self, name: object, type_obj: object) -> None:
        type_str = str(type_obj) if not isinstance(type_obj, str) else type_obj
        before = self.user_types.get(str(name))
        self.user_types[str(name)] = type_str
        self._record_undo(
            "define_user_type",
            type_name=str(name),
            before=before,
            after=type_str,
        )

    def get_type_by_name(self, name: str) -> str | None:
        return self.user_types.get(str(name))

    @property
    def types(self) -> dict:
        return dict(self.user_types)

    def parse_type_string(self, s: str) -> tuple[str, str]:
        """Mock parser: returns (type_str, '') or raises ValueError on bad syntax."""
        s = s.strip()
        if not s:
            raise ValueError(f"invalid type: {s!r}")
        # Detect unclosed braces as a basic syntax check
        if s.count("{") != s.count("}"):
            raise ValueError(f"invalid type: {s!r}")
        return (s, "")

    def parse_types_from_source(self, source: str) -> object:
        """Mock: extract typedef/struct names. Returns object with .types dict."""
        import re

        types: dict[str, str] = {}
        # typedef struct {...} Name; or struct Name {...};
        for m in re.finditer(
            r"(?:typedef\s+)?struct\s+(?:(\w+)\s*)?\{[^}]*\}\s*(\w+)?\s*;", source
        ):
            name = m.group(2) or m.group(1)
            if name:
                types[name] = m.group(0)
        if not types:
            # simple typedef X Y;
            for m in re.finditer(r"typedef\s+\S+\s+(\w+)\s*;", source):
                types[m.group(1)] = m.group(0)
        if not types:
            raise ValueError(f"no types found in source: {source[:80]!r}")

        class _ParseResult:
            def __init__(self, types_dict: dict) -> None:
                self.types = types_dict

        return _ParseResult(types)

    # API surface used by tools ------------------------------------------------

    def get_symbols(self) -> list[MockSymbol]:
        return list(self.symbols)

    def get_symbols_of_type(self, sym_type: int) -> list[MockSymbol]:
        return [s for s in self.symbols if int(s.type) == int(sym_type)]

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

    def get_callees(self, call_site_addr: int, func: Any = None, arch: Any = None) -> list[int]:
        """Return resolved callee start addresses for a call site (empty == indirect).

        Real BN signature is ``get_callees(addr, func=None, arch=None)``; func+arch
        narrow the lookup to one function on overlapping/multi-arch views.
        """
        del func, arch  # Mock has no overlapping functions, so the args don't matter.
        return list(self._callees_map.get(call_site_addr, []))

    def get_symbol_at(self, addr: int) -> MockSymbol | None:
        for s in self.symbols:
            if s.address == addr:
                return s
        return None

    def get_strings(self) -> list[MockString]:
        return list(self.strings)

    def read(self, addr: int, length: int) -> bytes:
        # Return a deterministic but uninteresting buffer
        return bytes((addr + i) & 0xFF for i in range(length))


def load(path: str, update_analysis: bool = True) -> MockBinaryView:  # noqa: ARG001
    """Mock equivalent of binaryninja.load(path)."""
    p = Path(path)
    return MockBinaryView(path=str(p))
