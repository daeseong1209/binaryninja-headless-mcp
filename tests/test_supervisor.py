"""Supervisor lifecycle tests using the mock backend."""

from __future__ import annotations

import pytest

from binja_mcp.supervisor import BinaryNotFoundError


def test_supervisor_uses_mock(supervisor):
    assert supervisor.is_mock is True


def test_open_binary_returns_handle(supervisor, fixture_binary):
    binary_id = supervisor.open(str(fixture_binary))
    assert isinstance(binary_id, str)
    assert len(binary_id) >= 8


def test_open_unknown_path_raises(supervisor, tmp_path):
    with pytest.raises(FileNotFoundError):
        supervisor.open(str(tmp_path / "does-not-exist"))


def test_open_directory_raises(supervisor, tmp_path):
    with pytest.raises(ValueError):
        supervisor.open(str(tmp_path))


def test_close_binary(supervisor, fixture_binary):
    binary_id = supervisor.open(str(fixture_binary))
    supervisor.close(binary_id)
    with pytest.raises(BinaryNotFoundError):
        supervisor.get(binary_id)


def test_close_unknown_raises(supervisor):
    with pytest.raises(BinaryNotFoundError):
        supervisor.close("nonexistent")


def test_list_returns_open_sessions(supervisor, fixture_binary, tmp_path):
    second = tmp_path / "other.bin"
    second.write_bytes(b"\x00" * 32)

    a = supervisor.open(str(fixture_binary))
    b = supervisor.open(str(second))

    rows = supervisor.list()
    assert len(rows) == 2
    ids = {r["binary_id"] for r in rows}
    assert ids == {a, b}
    paths = {r["path"] for r in rows}
    assert str(fixture_binary) in paths
    assert str(second) in paths


def test_close_all_clears_sessions(supervisor, fixture_binary):
    supervisor.open(str(fixture_binary))
    supervisor.open(str(fixture_binary))
    assert len(supervisor.list()) == 2
    supervisor.close_all()
    assert supervisor.list() == []


def test_get_touches_last_accessed(supervisor, fixture_binary):
    binary_id = supervisor.open(str(fixture_binary))
    s1 = supervisor.get(binary_id)
    first = s1.last_accessed
    s2 = supervisor.get(binary_id)
    assert s2.last_accessed >= first
