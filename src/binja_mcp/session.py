"""Per-binary session wrapper.

Wraps a single BinaryView (real or mock) with metadata used by the supervisor:
handle ID, file path, load time, last-accessed time. Also provides safe close
semantics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    binary_id: str
    path: str
    bv: Any  # binaryninja.BinaryView (or mock)
    is_mock: bool = False
    opened_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_accessed = time.time()

    def close(self) -> None:
        """Close the underlying BinaryView's file handle.

        Both real Binary Ninja and the mock backend expose `bv.file.close()`.
        """
        bv = self.bv
        if bv is None:
            return
        try:
            bv.file.close()
        except Exception:
            pass
        self.bv = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "binary_id": self.binary_id,
            "path": self.path,
            "is_mock": self.is_mock,
            "opened_at": self.opened_at,
            "last_accessed": self.last_accessed,
        }
