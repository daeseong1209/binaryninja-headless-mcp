# binja-mcp

**Binary Ninja headless MCP server** for Claude Code (OMC) and Codex CLI (OMX).

A Model Context Protocol server that exposes Binary Ninja's analysis engine
to LLM agents — decompilation, IL, cross-references, strings, and more —
without requiring the Binary Ninja GUI.

## Features

- **Headless-first**: runs without a GUI; ideal for containers, CI, and remote agents.
- **Multi-binary supervisor**: a single server can hold many binaries open at once. Each `open_binary` returns a handle that subsequent tools reference.
- **Mock backend**: tests and CI work without a Binary Ninja license (`BINJA_MCP_FORCE_MOCK=1`).
- **Pluggable tool registry**: drop a new function decorated with `@tool()` into `src/binja_mcp/tools/`, and it's auto-registered on startup.
- **MIT licensed**.

## Status — v0.1 (MVP)

Ten core tools, fully documented and tested:

| Tool | Purpose |
|------|---------|
| `open_binary(path)` | Load a binary, return a handle ID |
| `close_binary(binary_id)` | Free resources |
| `list_binaries()` | Currently open binaries |
| `binary_info(binary_id)` | Arch, platform, entry point, function count |
| `list_functions(binary_id)` | Paginated function list |
| `decompile(binary_id, addr_or_name)` | HLIL decompilation |
| `get_il(binary_id, addr_or_name, level)` | LLIL / MLIL / HLIL |
| `get_disasm(binary_id, addr_or_name, length)` | Disassembly |
| `get_xrefs_to(binary_id, addr_or_name)` | Incoming code references |
| `search_strings(binary_id, pattern)` | String search (literal or regex) |

See [`docs/tools-reference.md`](docs/tools-reference.md) for full schemas.

Roadmap (Phase C): symbols/types, comments, patching, imports/exports,
sections/segments, byte-pattern search, call graphs, debugger integration.

## Requirements

- Python 3.10+
- For real binaries: a Binary Ninja **Commercial** or **Ultimate** license. The `binaryninja` Python module must be importable (run `install_api.py` from your Binary Ninja install).
- The mock backend has no requirements and is used automatically when `binaryninja` cannot be imported, or when `BINJA_MCP_FORCE_MOCK=1`.

## Install

```bash
git clone https://github.com/your-org/binaryninja-headless-mcp.git
cd binaryninja-headless-mcp
python -m venv .venv
.venv/Scripts/activate     # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -e ".[dev]"
```

Hook up the Binary Ninja API (Commercial/Ultimate license required):

```bash
python "<Binary Ninja install>/scripts/install_api.py"
```

## Run

```bash
binja-mcp                            # stdio transport (default)
binja-mcp --transport sse            # SSE for remote clients
binja-mcp --log-level DEBUG          # verbose
```

## Register with clients

See [`docs/client-setup.md`](docs/client-setup.md) for full instructions.

Quick version:

**Claude Code (OMC):**
```bash
claude mcp add binja-mcp -- binja-mcp
```

**Codex CLI (OMX)** — add to `~/.codex/config.toml`:
```toml
[mcp_servers.binja]
command = "binja-mcp"
args = []
```

## Test

```bash
pytest                               # 39 tests, no Binary Ninja needed
pytest --cov=binja_mcp               # with coverage
```

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Architectural patterns drawn from:
- [mrexodia/ida-pro-mcp](https://github.com/mrexodia/ida-pro-mcp) — supervisor pattern, `@tool` decorator
- [MCPPhalanx/binaryninja-mcp](https://github.com/MCPPhalanx/binaryninja-mcp) — uvx entry point
- [fosdickio/binary_ninja_mcp](https://github.com/fosdickio/binary_ninja_mcp) — tool catalog reference

Note: [mrphrazer/binary-ninja-headless-mcp](https://github.com/mrphrazer/binary-ninja-headless-mcp) is GPLv2; only its design has been studied — no code reused.
