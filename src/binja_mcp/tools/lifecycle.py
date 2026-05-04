"""Binary lifecycle tools: open, close, list."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from ..registry import tool
from ..server import get_supervisor

_ALLOWED_ROOTS_ENV = "BINJA_MCP_ALLOWED_ROOTS"


def _validate_path(path: str) -> None:
    """Validate path for symlinks and optional allowed-roots confinement.

    Raises:
        PermissionError: if path is a symlink or outside allowed roots.
        FileNotFoundError: if strict=True resolution fails.
    """
    p = Path(path)

    # Symlink check (before resolution)
    if p.is_symlink():
        raise PermissionError("symlinks not allowed")

    allowed_env = os.environ.get(_ALLOWED_ROOTS_ENV, "").strip()
    if not allowed_env:
        return  # backward compat: no restriction

    roots_raw = allowed_env.split(os.pathsep)
    roots = [Path(r).resolve() for r in roots_raw if r.strip()]
    if not roots:
        return

    try:
        resolved = p.resolve(strict=True)
    except (OSError, FileNotFoundError) as exc:
        raise FileNotFoundError(f"path not found: {path!r}") from exc

    for root in roots:
        try:
            resolved.relative_to(root)
            return  # within at least one allowed root
        except ValueError:
            continue

    raise PermissionError(
        f"path {path!r} is outside allowed roots: {[str(r) for r in roots]}"
    )


@tool()
def open_binary(path: str, ctx: Context, update_analysis: bool = True) -> dict[str, Any]:
    """Load a binary file and return a handle ID for use in other tools.

    Args:
        path: absolute path to the binary file.
        update_analysis: if False, only headers are parsed (faster).

    Returns:
        {"binary_id": "...", "path": "...", "is_mock": bool}
    """
    _validate_path(path)
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
