"""Function listing."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ..utils import paginate
from ._helpers import function_to_summary, get_session


@tool()
def list_functions(
    binary_id: str,
    ctx: Context,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List functions in an open binary, with offset/limit pagination.

    Returns a page of function summaries: name, start, end, basic_block_count,
    parameter_count. Use offset+limit to walk large binaries.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    funcs = list(getattr(bv, "functions", []) or [])
    summaries = [function_to_summary(f) for f in funcs]
    return paginate(summaries, offset=offset, limit=limit)
