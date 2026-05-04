# Tools Reference (v0.1)

All tools accept a `binary_id` returned by `open_binary` (except the lifecycle
tools themselves). Errors raise standard Python exceptions, which FastMCP
converts into MCP `isError: true` responses with the original message.

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
exceeds 50 000 characters.

### `get_disasm(binary_id, addr_or_name, length=64)`
Disassembly text. If `addr_or_name` resolves to a function, the entire
function is disassembled. If it's a raw address, `length` bytes are
disassembled starting there.

## Cross-references

### `get_xrefs_to(binary_id, addr_or_name, offset=0, limit=100)`
Code references that point at a given function or address. Items contain
`{"address", "function"}`.

## Strings

### `search_strings(binary_id, pattern=None, regex=False, case_sensitive=True, offset=0, limit=100)`
Search strings discovered by Binary Ninja's analysis.
- Omitting `pattern` returns every string.
- Set `regex=True` to interpret `pattern` as a Python regular expression.
- Items contain `{"value", "address", "length"}`.

---

## Error semantics

| Condition | Exception |
|-----------|-----------|
| Unknown `binary_id` | `ValueError("unknown binary_id: ...")` |
| File missing on `open_binary` | `FileNotFoundError` |
| Path is not a regular file | `ValueError` |
| Function not found by name/address | `ValueError("function not found: ...")` |
| Invalid IL level | `ValueError("unknown IL level: ...")` |
| `offset` < 0 or `limit` ≤ 0 | `ValueError` |

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
