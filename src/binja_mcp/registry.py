"""Tool registry with @tool decorator.

Allows tool functions to register themselves at import time, decoupled from
any specific FastMCP instance. The server later calls register_all(mcp) to
attach every collected tool to its MCP server.

This pattern (inspired by mrexodia/ida-pro-mcp) makes it trivial to add new
tools — drop a function in tools/*.py with @tool() and it shows up.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolEntry:
    func: Callable[..., Any]
    name: str
    description: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


_REGISTRY: list[ToolEntry] = []


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    **metadata: Any,
) -> Callable[..., Any]:
    """Decorator to register a function as an MCP tool.

    Usage:
        @tool()
        def my_tool(arg: str) -> str:
            ...

        @tool(name="custom_name", description="...")
        def other(arg: int) -> int:
            ...
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        entry = ToolEntry(
            func=f,
            name=name or f.__name__,
            description=description or (f.__doc__.strip() if f.__doc__ else None),
            metadata=metadata,
        )
        _REGISTRY.append(entry)
        return f

    if func is not None:
        return decorator(func)
    return decorator


def get_registered_tools() -> list[ToolEntry]:
    """Return all currently-registered tools (read-only snapshot)."""
    return list(_REGISTRY)


def register_all(mcp: Any) -> int:
    """Attach every registered tool to the given FastMCP instance.

    Returns the number of tools registered.
    """
    count = 0
    for entry in _REGISTRY:
        mcp.tool(name=entry.name, description=entry.description)(entry.func)
        count += 1
    return count
