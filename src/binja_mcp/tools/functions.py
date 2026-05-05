"""Function listing."""

from __future__ import annotations

import itertools
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

    funcs = getattr(bv, "functions", None) or []

    # Determine total without forcing full materialisation where possible
    if hasattr(funcs, "__len__"):
        total = len(funcs)
        funcs_seq = funcs
    else:
        funcs_list = list(funcs)
        total = len(funcs_list)
        funcs_seq = funcs_list

    # Slice only the requested page before summarising. Real BN's FunctionList
    # raises (TypeError or IndexError) for slice objects despite supporting
    # int-based __getitem__, so fall back to islice on either.
    try:
        sliced = list(funcs_seq[offset : offset + limit])
    except (TypeError, IndexError):
        sliced = list(itertools.islice(funcs_seq, offset, offset + limit))

    summaries = [function_to_summary(f) for f in sliced]
    return paginate(summaries, offset=offset, limit=limit, total=total)
