"""All MCP tool modules.

Importing this package triggers @tool() registrations for every tool function.
The server.py side then calls registry.register_all(mcp) to wire them up.
"""

from . import (
    decompile,  # noqa: F401
    function_vars,  # noqa: F401
    functions,  # noqa: F401
    info,  # noqa: F401
    lifecycle,  # noqa: F401
    sections,  # noqa: F401
    strings,  # noqa: F401
    symbols,  # noqa: F401
    types,  # noqa: F401
    undo,  # noqa: F401
    xrefs,  # noqa: F401
)
