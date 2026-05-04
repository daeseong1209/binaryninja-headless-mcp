"""Binary metadata."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor
from ._helpers import (
    get_arch_name,
    get_function_count,
    get_platform_name,
    get_session,
    hex_or_none,
)


@tool()
def binary_info(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Return high-level metadata about an open binary.

    Includes architecture, platform, entry point, and function count.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv

    file_obj = getattr(bv, "file", None)
    filename = getattr(file_obj, "filename", None) or session.path

    return {
        "binary_id": binary_id,
        "filename": filename,
        "arch": get_arch_name(bv),
        "platform": get_platform_name(bv),
        "entry_point": hex_or_none(getattr(bv, "entry_point", None)),
        "function_count": get_function_count(bv),
        "is_mock": session.is_mock,
    }
