"""Binary metadata."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ._helpers import get_session, hex_or_none


@tool()
def binary_info(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Return high-level metadata about an open binary.

    Includes architecture, platform, entry point, and function count.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    arch = getattr(bv, "arch", None)
    arch_name = getattr(arch, "name", None) if arch is not None else getattr(bv, "arch_name", None)
    platform = getattr(bv, "platform", None)
    platform_name = (
        getattr(platform, "name", None)
        if platform is not None
        else getattr(bv, "platform_name", None)
    )
    entry = getattr(bv, "entry_point", None)
    file_obj = getattr(bv, "file", None)
    filename = getattr(file_obj, "filename", None) or session.path

    funcs = getattr(bv, "functions", None)
    try:
        function_count = len(funcs) if funcs is not None else None
    except TypeError:
        # funcs doesn't support len() — fall back to iteration
        try:
            function_count = len(list(funcs))
        except Exception:
            function_count = None

    return {
        "binary_id": binary_id,
        "filename": filename,
        "arch": arch_name,
        "platform": platform_name,
        "entry_point": hex_or_none(entry),
        "function_count": function_count,
        "is_mock": session.is_mock,
    }
