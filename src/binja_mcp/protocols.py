"""typing.Protocol definitions for backend duck-typing.

These define the minimum surface that both real Binary Ninja and the mock
backend must satisfy. Used by tools to make mock/real divergence visible to
type checkers (mypy/pyright) instead of failing silently at runtime.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FunctionLike(Protocol):
    name: str

    @property
    def start(self) -> int: ...


@runtime_checkable
class BinaryViewLike(Protocol):
    @property
    def functions(self) -> Any: ...  # iterable, often len()-supported

    def get_function_at(self, addr: int) -> Any | None: ...
    def get_strings(self) -> Any: ...
    def get_code_refs(self, addr: int) -> Any: ...
