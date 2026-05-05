"""FastMCP in-memory round-trip integration tests.

Uses ``mcp.shared.memory.create_connected_server_and_client_session`` to
exercise the full tool dispatch path (lifespan → Supervisor → tool → JSON)
without starting any real network transport.

The mock backend is forced by ``conftest.py`` (``BINJA_MCP_FORCE_MOCK=1``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def integration_server():
    """Build a fresh FastMCP server for integration tests."""
    from binja_mcp.server import build_server

    return build_server()


@pytest.mark.asyncio
async def test_round_trip_open_list_close(integration_server, fixture_binary: Path):
    """open_binary → list_functions → close_binary round-trip via in-memory client."""
    async with create_connected_server_and_client_session(integration_server) as client:
        await client.initialize()

        # --- open_binary -------------------------------------------------------
        open_result = await client.call_tool(
            "open_binary", {"path": str(fixture_binary)}
        )
        assert not open_result.isError, f"open_binary failed: {open_result.content}"
        open_data = json.loads(open_result.content[0].text)
        assert "binary_id" in open_data
        assert open_data["path"] == str(fixture_binary)
        assert open_data["is_mock"] is True
        binary_id = open_data["binary_id"]

        # --- list_functions ----------------------------------------------------
        list_result = await client.call_tool(
            "list_functions", {"binary_id": binary_id}
        )
        assert not list_result.isError, f"list_functions failed: {list_result.content}"
        list_data = json.loads(list_result.content[0].text)
        assert "items" in list_data
        assert list_data["total"] >= 1
        first_fn = list_data["items"][0]
        assert "name" in first_fn
        assert first_fn["start"].startswith("0x")

        # --- close_binary ------------------------------------------------------
        close_result = await client.call_tool(
            "close_binary", {"binary_id": binary_id}
        )
        assert not close_result.isError, f"close_binary failed: {close_result.content}"
        close_data = json.loads(close_result.content[0].text)
        assert close_data["closed"] == binary_id
