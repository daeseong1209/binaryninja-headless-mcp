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

## Security

binja-mcp exposes powerful analysis capabilities to LLM agents. Operate it with the principle of least privilege.

**Path allowlist** — restrict which directories the server may open:

```bash
export BINJA_MCP_ALLOWED_ROOTS="/home/user/binaries:/mnt/samples"
binja-mcp
```

**Network transport** — SSE and HTTP transports are disabled by default. The server binds only to `127.0.0.1` when enabled; you are responsible for TLS, authentication, and firewall rules:

```bash
binja-mcp --transport sse  # listens on http://127.0.0.1:8000/sse
```

**Mock backend** — `BINJA_MCP_FORCE_MOCK=1` is intended for CI/testing only. Real analysis requires a licensed Binary Ninja install; mock auto-fallback is not enabled in production.

See [`docs/security.md`](docs/security.md) for the full threat model and deployment guidance.

## Live tests

Run against a real Binary Ninja installation:

```bash
BINJA_MCP_LIVE_TARGET=/path/to/real/binary pytest -m live
```

Requires `binaryninja` importable and a valid Commercial/Ultimate license.

### Live test tiers

binja-mcp ships two live test markers:

- `live_quick` (~33 cases, ~1-2 min total) — uses tiny system PE fixtures
  (defaults: `C:\Windows\System32\hostname.exe` for x64, `C:\Windows\SysWOW64\where.exe` for x86).
  Override via `BINJA_MCP_LIVE_TARGET_TINY_X64` / `BINJA_MCP_LIVE_TARGET_TINY_X86`.
- `live_full` / `live` (~18 cases, ~5 min) — uses a real-world target via
  `BINJA_MCP_LIVE_TARGET` (e.g. `C:\Program Files\Vector35\BinaryNinja\update.exe`).

Run quick tier (per-PR sanity):

```bash
pytest -m live_quick
```

Run full tier (release sign-off):

```bash
BINJA_MCP_LIVE_TARGET=path/to/large.exe pytest -m "live or live_full"
```

## Test

```bash
pytest                               # all unit/mock tests, no BN license needed
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
