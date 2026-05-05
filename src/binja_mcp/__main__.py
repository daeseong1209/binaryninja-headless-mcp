"""CLI entry point for `binja-mcp`."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__

_NETWORK_TRANSPORTS = ("sse", "streamable-http")


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
        "--bind",
        default="127.0.0.1",
        help="Bind address for network transports (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--allow-public",
        action="store_true",
        default=False,
        help="Allow binding to non-loopback addresses (required when --bind != 127.0.0.1)",
    )
    parser.add_argument(
        "--allow-mock",
        action="store_true",
        default=False,
        help="Allow mock backend (sets BINJA_MCP_ALLOW_MOCK=1)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args()

    if args.allow_mock:
        os.environ["BINJA_MCP_ALLOW_MOCK"] = "1"

    if args.transport in _NETWORK_TRANSPORTS:
        if args.bind != "127.0.0.1" and not args.allow_public:
            parser.error(
                f"public bind requires --allow-public "
                f"(refusing to expose {args.transport} on {args.bind} without explicit consent)"
            )
        if args.allow_public:
            print(
                "\033[1mWARNING: binja-mcp is binding to a non-loopback address.\n"
                "This exposes the MCP server on the network. You are responsible\n"
                "for ensuring access is restricted (firewall, auth proxy, VPN, etc.).\033[0m",
                file=sys.stderr,
            )

    _configure_logging(args.log_level)

    # Import inside main() so --help / --version don't pay the cost
    from .server import build_server

    mcp = build_server()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
