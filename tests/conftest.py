"""Shared test fixtures.

Forces mock backend so tests run on any machine, with or without a Binary
Ninja license.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Force mock backend before any binja_mcp import
os.environ["BINJA_MCP_FORCE_MOCK"] = "1"

# Make src/ importable
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402  (must come after sys.path / env-var setup)


@pytest.fixture
def fixture_binary(tmp_path: Path) -> Path:
    """Create a tiny placeholder file that the mock backend will accept."""
    p = tmp_path / "sample.bin"
    p.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 64)
    return p


@pytest.fixture
def supervisor():
    """Provide a clean Supervisor (mock backend)."""
    from binja_mcp.supervisor import Supervisor

    sup = Supervisor(force_mock=True)
    yield sup
    sup.close_all()
