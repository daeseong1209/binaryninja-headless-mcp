"""Multi-binary session supervisor.

Maintains a registry of open BinaryView sessions keyed by handle ID. Lets a
single MCP server serve multiple binaries simultaneously — clients open(path)
to get a handle, then pass that handle to every subsequent tool call.

Pattern is inspired by mrexodia/ida-pro-mcp's supervisor for multi-DB workers.
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from .bn_env import import_binaryninja, is_mock_only
from .session import Session

log = logging.getLogger(__name__)


class BinaryNotFoundError(KeyError):
    """Raised when a binary_id is not registered."""


class Supervisor:
    """Manages the lifecycle of multiple BinaryView sessions."""

    def __init__(self, *, force_mock: bool | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        # Decide backend once at construction. force_mock=None -> use env var.
        if force_mock is None:
            force_mock = is_mock_only()
        self._bn, self._is_mock = import_binaryninja(allow_mock=True)
        if force_mock and not self._is_mock:
            from . import mock_backend

            self._bn = mock_backend
            self._is_mock = True
        log.info("Supervisor backend: %s", "mock" if self._is_mock else "binaryninja")

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    def open(self, path: str, *, update_analysis: bool = True) -> str:
        """Load a binary and return a handle ID.

        Raises:
            FileNotFoundError: if path does not exist.
            RuntimeError: if Binary Ninja fails to load the file.
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"binary not found: {path}")
        if not p.is_file():
            raise ValueError(f"not a regular file: {path}")

        bv = self._bn.load(str(p), update_analysis=update_analysis)
        if bv is None:
            raise RuntimeError(f"binaryninja could not load: {path}")

        binary_id = uuid.uuid4().hex[:12]
        session = Session(binary_id=binary_id, path=str(p), bv=bv, is_mock=self._is_mock)
        with self._lock:
            self._sessions[binary_id] = session
        log.info("opened binary %s -> %s", path, binary_id)
        return binary_id

    def close(self, binary_id: str) -> None:
        """Close a session and free its resources."""
        with self._lock:
            session = self._sessions.pop(binary_id, None)
        if session is None:
            raise BinaryNotFoundError(binary_id)
        session.close()
        log.info("closed binary %s (%s)", binary_id, session.path)

    def get(self, binary_id: str) -> Session:
        """Look up an open session, raising BinaryNotFoundError if missing."""
        with self._lock:
            session = self._sessions.get(binary_id)
        if session is None:
            raise BinaryNotFoundError(binary_id)
        session.touch()
        return session

    def list(self) -> list[dict[str, Any]]:
        """Return metadata for all open sessions."""
        with self._lock:
            return [s.to_dict() for s in self._sessions.values()]

    def close_all(self) -> None:
        """Close every session. Used during server shutdown."""
        with self._lock:
            ids = list(self._sessions.keys())
        for bid in ids:
            try:
                self.close(bid)
            except Exception as exc:
                log.warning("error closing %s: %s", bid, exc)
