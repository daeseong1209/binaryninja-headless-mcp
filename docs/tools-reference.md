# Tools Reference (v0.3.1)

**23 tools** are registered across 9 modules. All tools accept a `binary_id`
returned by `open_binary` (except the lifecycle tools themselves). Errors raise
standard Python exceptions, which FastMCP converts into MCP `isError: true`
responses with the original message.

Address arguments accept either an integer or a string (`"0x401234"`,
`"4198964"`).

## Lifecycle

### `open_binary(path, update_analysis=True)`
Load a binary file.
- **path** — absolute path on the server's filesystem.
- **update_analysis** — set `False` to parse only headers (much faster).
- Returns `{"binary_id", "path", "is_mock"}`.

### `close_binary(binary_id)`
Close a session and free its resources. Returns `{"closed": binary_id}`.
Raises `BinjaError(BINARY_NOT_FOUND)` for an unknown `binary_id`.

### `list_binaries()`
Returns `{"items": [{...}], "total": N}` describing every open session.

## Inspection

### `binary_info(binary_id)`
Returns architecture, platform, entry point (hex), function count, and the
backend type (`is_mock`).

### `list_functions(binary_id, offset=0, limit=100)`
Paginated list of function summaries:
```json
{
  "items": [{"name": "...", "start": "0x...", "end": "0x...",
             "basic_block_count": N, "parameter_count": N}],
  "offset": 0, "limit": 100, "total": N, "has_more": true
}
```

## Decompilation & IL

### `decompile(binary_id, addr_or_name)`
HLIL decompilation as text. Convenience wrapper around `get_il(level="HLIL")`.

### `get_il(binary_id, addr_or_name, level="HLIL")`
Returns IL text for the function. `level` is `LLIL`, `MLIL`, or `HLIL`
(case-insensitive). The response includes a `truncated` flag when the IL
exceeds 50 000 characters. Passing a non-string `level` (e.g. `None`) raises
`BinjaError(INVALID_IL_LEVEL)` rather than an `AttributeError`.

### `get_disasm(binary_id, addr_or_name, length=64)`
Disassembly text. If `addr_or_name` resolves to a function, the entire
function is disassembled. If it's a raw address, `length` bytes are
disassembled starting there.

## Cross-references

### `get_xrefs_to(binary_id, addr_or_name, offset=0, limit=100)`
Code references that point at a given function or address. Items contain
`{"address", "function"}`.

## Memory Layout

### `list_segments(binary_id)`
List all memory segments defined in the binary.
```json
{
  "items": [{"start": "0x...", "end": "0x...", "data_offset": N, "data_length": N,
             "readable": true, "writable": false, "executable": true}],
  "total": N
}
```

### `list_sections(binary_id)`
List all named sections (e.g. `.text`, `.data`, `.rodata`).
```json
{
  "items": [{"name": ".text", "start": "0x...", "end": "0x...", "semantics": "CodeSectionSemantics"}],
  "total": N
}
```
The `semantics` field is the BN enum's `.name` attribute (e.g. `"CodeSectionSemantics"`,
`"ReadWriteDataSectionSemantics"`) on both real BN and the mock backend. On
real BN, this avoids the bare integer representation that `str(SectionSemantics.X)` would produce.

### `list_imports(binary_id, offset=0, limit=100)`
List imported symbols (paginated). Returns `ImportedFunctionSymbol` and `ImportAddressSymbol` entries.
```json
{
  "items": [{"name": "printf", "address": "0x...", "type": "...", "full_name": "printf", "ordinal": null}],
  "offset": 0, "limit": 100, "total": N, "has_more": false
}
```

### `list_exports(binary_id, offset=0, limit=100)`
List exported symbols (paginated). Returns `ExportedFunctionSymbol` entries.
```json
{
  "items": [{"name": "DllMain", "address": "0x...", "type": "...", "full_name": "DllMain", "ordinal": null}],
  "offset": 0, "limit": 100, "total": N, "has_more": false
}
```
> **Heuristic note**: Real BN has no `ExportedFunctionSymbol` enum value. We
> approximate exports as `FunctionSymbol` entries that are *not* auto-generated.
> PE files with an explicit export table match this heuristic well; stripped ELFs
> may produce false negatives (exported functions appear as regular symbols).

## Symbols

### `list_symbols(binary_id, symbol_type=None, name_or_addr=None, offset=0, limit=100)`
List symbols in the binary (paginated).
- **symbol_type** — optional filter: `"function"`, `"imported_function"`, `"import_address"`,
  `"imports"`, `"data"`, `"external"`, `"library_function"`. `None` = all symbols.
- **name_or_addr** — if provided, look up a single symbol by name or hex address; raises
  `SYMBOL_NOT_FOUND` if absent. Ignores `symbol_type`, `offset`, and `limit`.
- Response (`paginate()` envelope):
```json
{
  "items": [{"name": "...", "full_name": "...", "address": "0x...",
             "type": "FunctionSymbol", "auto": true, "ordinal": 0}],
  "offset": 0, "limit": 100, "total": N, "has_more": false
}
```

### `rename_symbol(binary_id, addr, new_name)`
Rename a function or data symbol at the given address.
- Function path: assigns `func.name` directly (Binary Ninja preferred path for functions).
- Data path: calls `define_user_symbol(DataSymbol)` — creates a new symbol or renames existing.
- Automatically wraps the write in `begin_undo` / `commit_undo` so the operation is
  undoable with `undo()`.
- Response: `{"kind": "function"|"data", "address": "0x...", "before": "old_name"|null, "after": "new_name"}`
  `before` is `null` only when there was no pre-existing symbol at that address (data path, new definition).

## Types

### `define_data_var(binary_id, addr, type_str)`
Annotate a data variable at `addr` with the given type.
- **type_str** — any type string accepted by Binary Ninja's `parse_type_string`:
  `"uint64_t"`, `"char*"`, `"struct Foo*"`.
- Automatically wrapped in an undo transaction.
- Response: `{"address": "0x...", "type": "uint64_t"}`

### `get_type(binary_id, name)`
Retrieve a named type from the binary's type library.
- Response: `{"name": "Foo", "definition": "typedef struct {...} Foo;"}`.
  `definition` is `None` if the type is not defined.

### `define_type(binary_id, name, source)`
Define or replace a named type from C source.
- **source** — C source string, e.g. `"typedef struct {int x; int y;} Point;"`.
- Multi-type source is accepted; `name` must appear among the parsed types.
- QualifiedName keys are auto-converted to plain strings.
- Response: `{"name": "Point", "definition": "typedef struct {...} Point;"}`

## Undo / Redo

### `begin_undo(binary_id)`
Start a new undo group. Returns `{"state_id": "..."}`. Pass the returned
`state_id` to `commit_undo` after performing write operations.

### `commit_undo(binary_id, state_id)`
Commit the open undo group identified by `state_id`. All write operations
recorded since `begin_undo` are grouped into a single undoable action.
Returns `{"committed": state_id}`.
Empty groups (no recorded writes) are silently dropped — the undo stack is not
modified, but `commit_undo` still returns successfully.

**Bulk-undo pattern**: when an explicit `begin_undo`/`commit_undo` pair wraps
multiple tool calls (e.g. `rename_symbol` + `define_type`), all writes are
recorded in the outer group. A single subsequent `undo()` reverts all of them
atomically. This works because the internal `undo_transaction` helper detects
the open outer state and skips creating a nested group (mock backend only;
real BN always creates its own group per write).

### `undo(binary_id)`
Roll back the most recent undo group.
Returns `{"undone": bool, "remaining": int|null}`. `undone` is `False` when
the undo stack is empty (no-op). On real Binary Ninja the undo stack depth is
not exposed by the API; in that case `remaining` is `null` and `undone` is
`true` (best-effort — the `undo()` call was made without error). Committing a
new change after `undo` clears the redo stack (standard Binary Ninja behavior).

### `redo(binary_id)`
Re-apply the most recently undone group.
Returns `{"redone": bool, "remaining": int|null}`. `remaining` is `null` on
real BN (redo stack not exposed).

## v0.4 — Call graph

### `get_callers(binary_id, addr_or_name, offset=0, limit=100)`
List call sites that call into a function. Each item is `{"address", "function": <summary>}`,
where `address` is the call instruction in the caller. Multiple sites from one caller produce
multiple items.

### `get_callees(binary_id, addr_or_name, offset=0, limit=100)`
List outgoing call sites from a function. Each item is `{"address", "target": <summary>|null}`,
where `address` is the call site in the source function and `target` is the resolved callee
(or `null` for indirect calls).

### `get_call_sites(binary_id, addr_or_name, offset=0, limit=100)`
Raw list of call-site addresses inside a function: `{"items": [{"address"}], ...}`.

## Strings

### `search_strings(binary_id, pattern=None, regex=False, case_sensitive=True, offset=0, limit=100)`
Search strings discovered by Binary Ninja's analysis.
- Omitting `pattern` returns every string.
- Set `regex=True` to interpret `pattern` as a Python regular expression.
- Items contain `{"value", "address", "length"}`.

---

## Error semantics

| Tool | Condition | Exception |
|------|-----------|-----------|
| any | Unknown `binary_id` | `BinjaError(BINARY_NOT_FOUND, "unknown binary_id: ...")` |
| `close_binary` | Unknown `binary_id` | `BinjaError(BINARY_NOT_FOUND)` |
| `open_binary` | File missing | `FileNotFoundError` |
| `open_binary` | Path is a symlink | `PermissionError("symlinks not allowed")` |
| `open_binary` | Path outside `BINJA_MCP_ALLOWED_ROOTS` | `PermissionError("path ... is outside allowed roots: ...")` |
| `open_binary` | Path is not a regular file | `ValueError` |
| `open_binary` | Too many binaries already open (> 32) | `RuntimeError("too many open binaries (max 32)")` |
| any | Function not found by name/address | `ValueError("function not found: ...")` |
| `get_il` / `decompile` | Invalid IL level | `ValueError("unknown IL level: ...")` |
| `list_functions` | `offset` < 0 or `limit` ≤ 0 | `ValueError` |
| `list_imports` | `offset` < 0 or `limit` ≤ 0 | `ValueError` |
| `list_exports` | `offset` < 0 or `limit` ≤ 0 | `ValueError` |
| `search_strings` | `pattern` exceeds 256 characters | `ValueError("pattern too long (max 256)")` |
| `search_strings` | Regex evaluation exceeds 2 s | `TimeoutError("regex match exceeded 2.0s")` |
| `commit_undo` | `state_id` not open or already committed | `BinjaError("unknown or already-committed undo state_id: ...")` (`.code == "UNDO_STATE_INVALID"`) |
| `define_data_var`, `define_type` | invalid / unparseable type | `BinjaError("failed to parse type definition: ...")` (`.code == "TYPE_PARSE_ERROR"`) |
| `list_symbols` (with `name_or_addr`) | symbol not found | `BinjaError("symbol not found: ...")` (`.code == "SYMBOL_NOT_FOUND"`) |
| `rename_symbol`, `define_data_var` | bad / unparseable address | `BinjaError(.code == "INVALID_ADDRESS")` |

All exceptions surface to the MCP client as a tool error with the original
message intact.

## Adding a tool

1. Drop a new file in `src/binja_mcp/tools/`.
2. Register the file in `src/binja_mcp/tools/__init__.py`.
3. Decorate the function with `@tool()`:

```python
from mcp.server.fastmcp import Context
from ..registry import tool
from ..server import get_supervisor
from ._helpers import get_session

@tool()
def my_new_tool(binary_id: str, ctx: Context) -> dict:
    """Tool docstring becomes the MCP description."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    # ... call into Binary Ninja or the mock backend ...
    return {...}
```

4. Add a test in `tests/test_tools_mock.py` using the existing `ctx` fixture.
