"""Per-binary session wrapper.

Wraps a single BinaryView (real or mock) with metadata used by the supervisor:
handle ID, file path, load time, last-accessed time. Also provides safe close
semantics.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Session:
    binary_id: str
    path: str
    bv: Any  # binaryninja.BinaryView (or mock)
    is_mock: bool = False
    opened_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False, compare=False
    )
    _closed: bool = field(default=False, init=False, repr=False, compare=False)
    _inflight: int = field(default=0, init=False, repr=False, compare=False)

    def touch(self) -> None:
        self.last_accessed = time.time()

    @contextmanager
    def use(self):
        """Context manager that guards against use-after-close.

        Raises RuntimeError if the session is already closed. Tracks in-flight
        operations so close() can wait until they finish.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("session closed")
            self._inflight += 1
        try:
            yield self
        finally:
            with self._lock:
                self._inflight -= 1

    def close(self) -> None:
        """Close the underlying BinaryView's file handle.

        Marks the session as closed, then polls until all in-flight operations
        complete (up to 5 seconds), then releases the BinaryView.

        Both real Binary Ninja and the mock backend expose `bv.file.close()`.
        """
        with self._lock:
            self._closed = True

        # Wait for in-flight operations to finish (poll up to 5s)
        deadline = time.monotonic() + 5.0
        while True:
            with self._lock:
                if self._inflight == 0:
                    break
            if time.monotonic() >= deadline:
                log.warning(
                    "session %s still has %d in-flight operations after timeout; closing anyway",
                    self.binary_id,
                    self._inflight,
                )
                break
            time.sleep(0.01)

        bv = self.bv
        try:
            if bv is not None:
                bv.file.close()
        except Exception as exc:
            log.warning("error closing bv for session %s: %s", self.binary_id, exc)
        finally:
            self.bv = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "binary_id": self.binary_id,
            "path": self.path,
            "is_mock": self.is_mock,
            "opened_at": self.opened_at,
            "last_accessed": self.last_accessed,
        }
