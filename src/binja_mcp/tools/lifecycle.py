"""Binary lifecycle tools: open, close, list."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from ..errors import binary_not_found
from ..registry import tool
from ..server import get_supervisor
from ..supervisor import BinaryNotFoundError

_ALLOWED_ROOTS_ENV = "BINJA_MCP_ALLOWED_ROOTS"


def _is_within(child: Path, root: Path) -> bool:
    """Return True if child is within root (or is root itself)."""
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_path(path: str) -> Path:
    """Validate path for symlinks and optional allowed-roots confinement.

    Returns the resolved (canonical) Path so callers use the same path that
    was validated — eliminating the TOCTOU window between validation and open.

    Raises:
        PermissionError: if path is a symlink or outside allowed roots.
        FileNotFoundError: if strict=True resolution fails.
    """
    p = Path(path)

    # Symlink check (before resolution) — always enforced regardless of roots env
    if p.is_symlink():
        raise PermissionError("symlinks not allowed")

    allowed_env = os.environ.get(_ALLOWED_ROOTS_ENV, "").strip()
    if not allowed_env:
        # Backward compat: no restriction — but still resolve for canonicality
        try:
            return p.resolve(strict=True)
        except (OSError, FileNotFoundError) as exc:
            raise FileNotFoundError(f"path not found: {path!r}") from exc

    roots_raw = allowed_env.split(os.pathsep)
    roots = [Path(r).resolve() for r in roots_raw if r.strip()]
    if not roots:
        try:
            return p.resolve(strict=True)
        except (OSError, FileNotFoundError) as exc:
            raise FileNotFoundError(f"path not found: {path!r}") from exc

    try:
        resolved = p.resolve(strict=True)
    except (OSError, FileNotFoundError) as exc:
        raise FileNotFoundError(f"path not found: {path!r}") from exc

    if not any(_is_within(resolved, root) for root in roots):
        raise PermissionError(
            f"path {path!r} is outside allowed roots: {[str(r) for r in roots]}"
        )
    return resolved


@tool()
def open_binary(path: str, ctx: Context, update_analysis: bool = True) -> dict[str, Any]:
    """Load a binary file and return a handle ID for use in other tools.

    Args:
        path: absolute path to the binary file.
        update_analysis: if False, only headers are parsed (faster).

    Returns:
        {"binary_id": "...", "path": "...", "is_mock": bool}
    """
    resolved = _validate_path(path)  # may raise; returns canonical Path
    sup = get_supervisor(ctx)
    binary_id = sup.open(str(resolved), update_analysis=update_analysis)
    return {"binary_id": binary_id, "path": str(resolved), "is_mock": sup.is_mock}


@tool()
def close_binary(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Close an open binary session and free resources."""
    sup = get_supervisor(ctx)
    try:
        sup.close(binary_id)
    except BinaryNotFoundError:
        raise binary_not_found(binary_id) from None
    return {"closed": binary_id}


@tool()
def list_binaries(ctx: Context) -> dict[str, Any]:
    """Return metadata for every binary currently open in this server."""
    sup = get_supervisor(ctx)
    items = sup.list()
    return {"items": items, "total": len(items)}
