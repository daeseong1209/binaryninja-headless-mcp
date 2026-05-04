"""Binary lifecycle tools: open, close, list."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor


@tool()
def open_binary(path: str, ctx: Context, update_analysis: bool = True) -> dict[str, Any]:
    """Load a binary file and return a handle ID for use in other tools.

    Args:
        path: absolute path to the binary file.
        update_analysis: if False, only headers are parsed (faster).

    Returns:
        {"binary_id": "...", "path": "...", "is_mock": bool}
    """
    sup = get_supervisor(ctx)
    binary_id = sup.open(path, update_analysis=update_analysis)
    return {"binary_id": binary_id, "path": path, "is_mock": sup.is_mock}


@tool()
def close_binary(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Close an open binary session and free resources."""
    sup = get_supervisor(ctx)
    sup.close(binary_id)
    return {"closed": binary_id}


@tool()
def list_binaries(ctx: Context) -> dict[str, Any]:
    """Return metadata for every binary currently open in this server."""
    sup = get_supervisor(ctx)
    items = sup.list()
    return {"items": items, "total": len(items)}
