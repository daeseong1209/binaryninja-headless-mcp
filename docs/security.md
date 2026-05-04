# Security

## Threat model

binja-mcp is designed for use with LLM agents (Claude Code, Codex CLI) and assumes:

- **LLM agent input is untrusted.** Prompts may be adversarially crafted to request analysis of unexpected file paths, large or malicious binaries, or computationally expensive operations.
- **Binaries are untrusted.** Binary Ninja parses potentially malicious files. Parsing a crafted binary could trigger vulnerabilities in BN itself; binja-mcp does not add a sandbox around the analysis engine.
- **Network transports (SSE/HTTP) are unauthenticated by default.** Any process that can reach the bound address can call every tool.

## Recommended deployment

The safest configuration is **stdio transport only** with a **local LLM**:

```bash
binja-mcp  # no --transport flag; stdio is the default
```

In this mode the server communicates only through standard input/output of the
spawning process. There are no sockets, no ports, no HTTP surface.

## SSE / HTTP transport — your responsibility

If you need remote access, you are responsible for:

1. **Binding correctly.** The default is `127.0.0.1`; change with `--host`.
2. **Authentication.** binja-mcp does not implement auth. Put the server behind an authenticated reverse proxy (e.g. nginx + mTLS, Tailscale, a VPN).
3. **Path allowlist.** Set `BINJA_MCP_ALLOWED_ROOTS` to restrict which directories the agent may open.

## Input validation

| Input | Validation |
|-------|-----------|
| `open_binary` path | Symlink check; optional `BINJA_MCP_ALLOWED_ROOTS` confinement |
| `search_strings` pattern | Max 256 characters; regex execution has a 2-second timeout |
| `get_il` level | Allowlist: LLIL, MLIL, HLIL only |
| `open_binary` count | Hard cap at 32 simultaneous sessions |

## Known limitations

- **Binary Ninja core is not sandboxed.** A malicious binary could exploit a BN parser bug. Run the server in an isolated environment (Docker, VM, dedicated user) when analyzing untrusted samples.
- **Mock backend is intentional.** `BINJA_MCP_FORCE_MOCK=1` replaces the analysis engine with deterministic stubs. It is intended for tests and CI only; it does not provide any security isolation for real analysis work.
- **No rate limiting.** There is no built-in rate limit on tool calls. A runaway agent could open many large binaries in succession and exhaust memory.

## Reporting

Report security issues privately to the maintainers before public disclosure.
