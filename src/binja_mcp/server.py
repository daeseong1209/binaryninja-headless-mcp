"""FastMCP server entry point.

Wires up the Supervisor as the lifespan context, then registers every tool
that decorated itself with @tool() into the FastMCP instance.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP

from .registry import register_all
from .supervisor import Supervisor

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    supervisor: Supervisor


def get_supervisor(ctx: Context) -> Supervisor:
    """Helper for tools to retrieve the active Supervisor from FastMCP Context."""
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return app_ctx.supervisor


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    sup = Supervisor()
    log.info("binja-mcp lifespan start (mock=%s)", sup.is_mock)
    try:
        yield AppContext(supervisor=sup)
    finally:
        sup.close_all()
        log.info("binja-mcp lifespan end")


def build_server(name: str = "binja-mcp") -> FastMCP:
    """Construct a FastMCP server with all tools registered."""
    # Import tools lazily here so that get_supervisor() is already defined when
    # tool modules import it. This avoids circular-import issues that would
    # otherwise hit when binja_mcp.server is imported as the entry point.
    from . import tools as _tools  # noqa: F401  -- triggers @tool registrations

    mcp = FastMCP(name, lifespan=lifespan)
    n = register_all(mcp)
    log.info("registered %d tools with FastMCP server", n)
    return mcp


# Module-level instance so `mcp dev src/binja_mcp/server.py` works
mcp = build_server()
