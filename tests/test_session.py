"""Unit tests for Session race-condition protection."""

from __future__ import annotations

import threading
import time

import pytest

from binja_mcp.session import Session


def _make_session() -> Session:
    """Create a minimal Session with a stub bv."""

    class _FakeFile:
        def close(self):
            pass

    class _FakeBV:
        file = _FakeFile()

    return Session(binary_id="test-id", path="/fake/path", bv=_FakeBV(), is_mock=True)


def test_use_increments_and_decrements_inflight():
    """Entering use() increments _inflight; exiting decrements it."""
    s = _make_session()
    assert s._inflight == 0

    with s.use():
        assert s._inflight == 1

    assert s._inflight == 0


def test_use_after_close_raises():
    """use() raises RuntimeError when the session is already closed."""
    s = _make_session()
    s.close()
    with pytest.raises(RuntimeError, match="session closed"):
        with s.use():
            pass


def test_close_waits_for_inflight(tmp_path):
    """close() waits until in-flight operations complete before returning."""
    s = _make_session()

    close_returned_at: list[float] = []
    use_exited_at: list[float] = []

    ready = threading.Event()
    proceed = threading.Event()

    def worker():
        with s.use():
            ready.set()       # signal that we're inside use()
            proceed.wait()    # hold the in-flight slot open
            time.sleep(0.05)  # small delay after proceed so close must wait
            use_exited_at.append(time.monotonic())

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    ready.wait()  # worker is inside use() now

    # Start close in a thread so it runs concurrently
    def do_close():
        proceed.set()  # let worker begin exiting
        s.close()
        close_returned_at.append(time.monotonic())

    close_thread = threading.Thread(target=do_close, daemon=True)
    close_thread.start()

    t.join(timeout=3.0)
    close_thread.join(timeout=3.0)

    assert use_exited_at, "worker did not finish"
    assert close_returned_at, "close did not return"
    # close() must have returned after (or at roughly the same time as) use() exited
    assert close_returned_at[0] >= use_exited_at[0] - 0.01
