# Client Setup

How to register `binja-mcp` with the two clients we target: Claude Code (OMC)
and Codex CLI (OMX).

## Prerequisites

1. **Install** the package — see the README's Install section.
2. **Confirm the CLI is on PATH** by running `binja-mcp --version`. If you used a venv, either activate the venv before launching the MCP-aware client, or invoke via the full path / `python -m binja_mcp`.
3. **Binary Ninja API**: for real binaries, run `python "<Binary Ninja install>/scripts/install_api.py"` once so that `import binaryninja` works in your environment. Without it the mock backend is used automatically.

---

## Claude Code (OMC)

### Quick add

```bash
claude mcp add binja-mcp -- binja-mcp
```

### Project-scoped

```bash
claude mcp add --scope project binja-mcp -- binja-mcp
```

### With explicit Python interpreter

```bash
claude mcp add binja-mcp -- /path/to/.venv/bin/python -m binja_mcp
```

### Verify

```bash
claude mcp list
```

You should see `binja-mcp` listed. Inside Claude Code, the tool palette will
expose `open_binary`, `decompile`, `get_il`, etc.

---

## Codex CLI (OMX)

Codex CLI reads MCP server definitions from `~/.codex/config.toml`.

### stdio (recommended)

```toml
[mcp_servers.binja]
command = "binja-mcp"
args = []
startup_timeout_sec = 30
tool_timeout_sec = 120

[mcp_servers.binja.env]
# optional — force mock backend for unlicensed dev machines
# BINJA_MCP_FORCE_MOCK = "1"
```

### From a venv

```toml
[mcp_servers.binja]
command = "P:/binaryninja-headless-mcp/.venv/Scripts/python.exe"
args = ["-m", "binja_mcp"]
```

(Use the full path to the venv's `python.exe` on Windows or
`.venv/bin/python` on macOS/Linux.)

### Remote / HTTP

If you want to run the server on a different machine, start it with the SSE
or streamable-http transport:

```bash
binja-mcp --transport sse  # listens on http://127.0.0.1:8000/sse by default
```

…and register the URL in `config.toml`:

```toml
[mcp_servers.binja-remote]
url = "http://your-host:8000/sse"
startup_timeout_sec = 30
tool_timeout_sec = 120
```

---

## Smoke-test the integration

After registering, ask the agent:

> Open `/path/to/binary` and list the first 10 functions.

The expected sequence is `open_binary` → `list_functions(limit=10)` →
results. If the agent reports it can't find the tool, run
`binja-mcp --version` from the same shell to confirm the CLI works, then
double-check the client's MCP configuration.

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `BINJA_MCP_FORCE_MOCK` | Set to `1` to force the mock backend even if `binaryninja` is importable. |
| `BN_DISABLE_USER_SETTINGS` | Set automatically to `True`. Override only if you need user settings honoured. |
| `BN_DISABLE_USER_PLUGINS` | Set automatically to `True`. Override only if you need user plugins loaded inside the MCP server. |
