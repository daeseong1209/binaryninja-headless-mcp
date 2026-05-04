"""CLI entry point for `binja-mcp`."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__


def _configure_logging(level: str) -> None:
    # Critical: log to stderr so we don't corrupt stdio MCP traffic
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="binja-mcp",
        description="Binary Ninja headless MCP server",
    )
    parser.add_argument("--version", action="version", version=f"binja-mcp {__version__}")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()
    _configure_logging(args.log_level)

    # Import inside main() so --help / --version don't pay the cost
    from .server import build_server

    mcp = build_server()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
