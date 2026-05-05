"""Undo / redo tools — exposes Binary Ninja's undo pipeline."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context

from ..errors import undo_state_invalid
from ..registry import tool
from ..server import get_supervisor
from ._helpers import get_session


@tool()
def undo(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Roll back the most recent undo group on the binary.

    No-op (returns ``{"undone": False}``) if the undo stack is empty.
    On real BN where the undo stack is not exposed, ``remaining`` is None
    and ``undone`` reflects whether the call completed without error.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    before = _stack_depth(bv, "_undo_stack")
    bv.undo()
    after = _stack_depth(bv, "_undo_stack")
    if before is None or after is None:
        # Real BN: stack not exposed; we cannot tell if anything actually changed
        return {
            "undone": None,
            "remaining": None,
            "note": "real BN does not expose undo stack depth",
        }
    return {"undone": after < before, "remaining": after}


@tool()
def redo(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Re-apply the most recently undone group.

    On real BN where the redo stack is not exposed, ``remaining`` is None.
    """
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    before = _stack_depth(bv, "_redo_stack")
    bv.redo()
    after = _stack_depth(bv, "_redo_stack")
    if before is None or after is None:
        # Real BN: stack not exposed; we cannot tell if anything actually changed
        return {
            "redone": None,
            "remaining": None,
            "note": "real BN does not expose redo stack depth",
        }
    return {"redone": after < before, "remaining": after}


@tool()
def begin_undo(binary_id: str, ctx: Context) -> dict[str, Any]:
    """Start a new undo group; returns state_id to pass to commit_undo."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    state_id = bv.begin_undo_actions()
    return {"state_id": str(state_id)}


@tool()
def commit_undo(binary_id: str, state_id: str, ctx: Context) -> dict[str, Any]:
    """Commit an open undo group identified by state_id."""
    sup = get_supervisor(ctx)
    session = get_session(sup, binary_id)
    bv = session.bv
    try:
        bv.commit_undo_actions(state_id)
    except (KeyError, ValueError) as exc:
        raise undo_state_invalid(state_id) from exc
    return {"committed": state_id}


def _stack_depth(bv: Any, attr: str) -> int | None:
    """Return the depth of an undo/redo stack, or None if not exposed by backend."""
    stack = getattr(bv, attr, None)
    return len(stack) if stack is not None else None
