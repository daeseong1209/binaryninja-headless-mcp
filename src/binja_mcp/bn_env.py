"""Binary Ninja environment setup and safe import.

Sets recommended environment variables before importing the binaryninja module
so that user settings and user plugins do not interfere with the MCP server.

Also provides a fallback to a mock backend when binaryninja is unavailable
(e.g., on CI machines without a Commercial/Ultimate license).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_BN_ENV_DEFAULTS = {
    "BN_DISABLE_USER_SETTINGS": "True",
    "BN_DISABLE_USER_PLUGINS": "True",
}


def configure_environment() -> None:
    """Set Binary Ninja environment variables before module import.

    Idempotent — only sets variables that are not already defined, so users
    can override by exporting their own values.
    """
    for key, value in _BN_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def import_binaryninja(allow_mock: bool = True):
    """Import the real binaryninja module, or fall back to the mock backend.

    Returns:
        Tuple of (module, is_mock).
    """
    configure_environment()
    try:
        import binaryninja  # type: ignore[import-not-found]

        log.info(
            "Loaded real binaryninja module (version=%s)",
            getattr(binaryninja, "core_version", "unknown"),
        )
        return binaryninja, False
    except ImportError as exc:
        if not allow_mock:
            raise
        log.warning("binaryninja module not available (%s); falling back to mock backend", exc)
        from . import mock_backend
        return mock_backend, True


def is_mock_only() -> bool:
    """Return True if BINJA_MCP_FORCE_MOCK is set (test/CI environments)."""
    return os.environ.get("BINJA_MCP_FORCE_MOCK", "").lower() in ("1", "true", "yes")
