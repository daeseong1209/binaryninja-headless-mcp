"""Performance, load, and race-condition tests.

All tests are decorated with @pytest.mark.perf. Run them in isolation:

    pytest tests/test_perf.py -v -m perf

They are skipped in default CI runs; add ``-m perf`` to opt in.
"""

from __future__ import annotations

import statistics
import threading
import time
from types import SimpleNamespace

import pytest

from binja_mcp.supervisor import MAX_OPEN_BINARIES, BinaryNotFoundError
from binja_mcp.tools import decompile as t_decompile
from binja_mcp.tools import functions as t_functions
from binja_mcp.tools import lifecycle as t_lifecycle
from binja_mcp.tools import strings as t_strings

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx(supervisor):
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=supervisor)
        )
    )


@pytest.fixture()
def open_id(ctx, fixture_binary) -> str:
    res = t_lifecycle.open_binary(str(fixture_binary), ctx)
    return res["binary_id"]


# ---------------------------------------------------------------------------
# 1. list_functions mock baseline latency (Phase 1 regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_list_functions_baseline_latency(ctx, open_id):
    """100 calls to list_functions must all complete; median < 100 ms."""
    latencies: list[float] = []
    for _ in range(100):
        t0 = time.perf_counter()
        page = t_functions.list_functions(open_id, ctx, offset=0, limit=7)
        latencies.append(time.perf_counter() - t0)
        assert page["total"] == 7

    median_ms = statistics.median(latencies) * 1000
    assert median_ms < 100, f"median list_functions latency {median_ms:.2f} ms exceeds 100 ms"


# ---------------------------------------------------------------------------
# 2. search_strings ReDoS defence latency
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_search_strings_safe_regex_latency(ctx, open_id):
    """A safe regex pattern completes within 0.05 s."""
    t0 = time.perf_counter()
    t_strings.search_strings(open_id, ctx, pattern=r"^/etc/", regex=True)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05, f"safe regex took {elapsed:.4f}s (expected < 0.05s)"


@pytest.mark.perf
def test_search_strings_nested_quantifier_rejected_fast(ctx, open_id):
    """Nested-quantifier pattern must be rejected before compile (< 0.001 s)."""
    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="nested quantifier"):
        t_strings.search_strings(open_id, ctx, pattern=r"(a+)+", regex=True)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.001, f"rejection took {elapsed:.6f}s (expected < 0.001s)"


# ---------------------------------------------------------------------------
# 3. search_strings timeout accuracy
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_search_strings_timeout_accuracy(ctx, open_id, monkeypatch):
    """TimeoutError must fire between the configured timeout and 3×timeout."""
    import binja_mcp.tools.strings as strings_mod

    monkeypatch.setattr(strings_mod, "STRING_REGEX_TIMEOUT_S", 0.05)

    def slow_collect(raw, matcher):
        time.sleep(1.0)
        return []

    monkeypatch.setattr(strings_mod, "_collect", slow_collect)

    t0 = time.perf_counter()
    with pytest.raises(TimeoutError, match="regex match exceeded"):
        t_strings.search_strings(open_id, ctx, pattern="anything", regex=True)
    elapsed = time.perf_counter() - t0

    # Should fire at ~0.05 s; allow 3× headroom for slow CI runners
    assert 0.05 <= elapsed <= 0.15, (
        f"TimeoutError fired after {elapsed:.4f}s (expected 0.05..0.15s)"
    )


# ---------------------------------------------------------------------------
# 4. decompile truncate boundary
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_decompile_truncate_large(ctx, open_id, supervisor):
    """60 000-char HLIL must be truncated to 50 000 chars with truncated=True."""
    bv = supervisor.get(open_id).bv
    func = bv.get_function_by_name("main")
    assert func is not None
    original_hlil = func._hlil
    func._hlil = "x" * 60_000
    try:
        result = t_decompile.decompile(open_id, "main", ctx)
        assert len(result["text"]) == 50_000
        assert result["truncated"] is True
    finally:
        func._hlil = original_hlil


@pytest.mark.perf
def test_decompile_no_truncate_small(ctx, open_id):
    """A function with <= 50 000-char HLIL must not be truncated."""
    result = t_decompile.decompile(open_id, "main", ctx)
    assert result["truncated"] is False
    assert len(result["text"]) <= 50_000


# ---------------------------------------------------------------------------
# 5. list_functions slice-before-summarize efficiency (PR #4 deslop guard)
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_list_functions_slice_before_summarize(ctx, open_id, monkeypatch):
    """offset=3, limit=2 must invoke function_to_summary exactly 2 times."""
    import binja_mcp.tools.functions as functions_mod

    call_count: list[int] = [0]
    original = functions_mod.function_to_summary

    def counting_summary(func):
        call_count[0] += 1
        return original(func)

    monkeypatch.setattr(functions_mod, "function_to_summary", counting_summary)

    page = t_functions.list_functions(open_id, ctx, offset=3, limit=2)
    assert len(page["items"]) == 2
    assert call_count[0] == 2, (
        f"function_to_summary called {call_count[0]} times for offset=3, limit=2 "
        f"(expected exactly 2 — slice-before-summarize regression)"
    )


# ---------------------------------------------------------------------------
# 6. MAX_OPEN_BINARIES=32 cap
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_max_open_binaries_cap(supervisor, fixture_binary):
    """Opening 32 binaries succeeds; the 33rd raises RuntimeError with '32'."""
    ids: list[str] = []
    for _ in range(MAX_OPEN_BINARIES):
        ids.append(supervisor.open(str(fixture_binary)))

    try:
        with pytest.raises(RuntimeError) as exc_info:
            supervisor.open(str(fixture_binary))
        msg = str(exc_info.value)
        assert "32" in msg, f"error message does not mention limit 32: {msg!r}"
    finally:
        for bid in ids:
            try:
                supervisor.close(bid)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 7. Multi-thread tool call race (no crash, consistent results)
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_multithreaded_list_functions(supervisor, fixture_binary):
    """4 concurrent threads listing functions must all get identical results."""
    binary_id = supervisor.open(str(fixture_binary))
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=supervisor)
        )
    )

    results: list[dict] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker():
        try:
            page = t_functions.list_functions(binary_id, ctx, offset=0, limit=100)
            with lock:
                results.append(page)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    supervisor.close(binary_id)

    assert not errors, f"threads raised exceptions: {errors}"
    assert len(results) == 4
    # All threads must have seen the same function names
    first_names = {it["name"] for it in results[0]["items"]}
    for r in results[1:]:
        assert {it["name"] for it in r["items"]} == first_names


# ---------------------------------------------------------------------------
# 8. In-flight use() during close — close must wait
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_inflight_close_waits(supervisor, fixture_binary):
    """close() must wait for an in-flight use() to finish before returning."""
    binary_id = supervisor.open(str(fixture_binary))
    session = supervisor.get(binary_id)

    use_exited_at: list[float] = []
    close_returned_at: list[float] = []
    inside = threading.Event()

    def slow_user():
        with session.use():
            inside.set()
            time.sleep(0.5)
            use_exited_at.append(time.monotonic())

    def close_after_delay():
        inside.wait()
        time.sleep(0.1)
        supervisor.close(binary_id)
        close_returned_at.append(time.monotonic())

    t_user = threading.Thread(target=slow_user, daemon=True)
    t_close = threading.Thread(target=close_after_delay, daemon=True)
    t_user.start()
    t_close.start()
    t_user.join(timeout=5.0)
    t_close.join(timeout=5.0)

    assert use_exited_at, "slow_user thread did not complete"
    assert close_returned_at, "close thread did not complete"
    # close must have returned at or after use() exited
    assert close_returned_at[0] >= use_exited_at[0] - 0.02, (
        f"close returned {close_returned_at[0]:.4f} before use exited {use_exited_at[0]:.4f}"
    )
    # After close, use_session must raise
    with pytest.raises((RuntimeError, BinaryNotFoundError)):
        with supervisor.use_session(binary_id):
            pass


# ---------------------------------------------------------------------------
# 9. 3 concurrent closes on the same binary_id — RLock safety
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_concurrent_close_rlock_safety(supervisor, fixture_binary):
    """Only one thread wins the close; others get BinaryNotFoundError."""
    binary_id = supervisor.open(str(fixture_binary))

    successes: list[int] = []
    not_founds: list[int] = []
    other_errors: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(3)

    def try_close():
        barrier.wait()  # all three start simultaneously
        try:
            supervisor.close(binary_id)
            with lock:
                successes.append(1)
        except BinaryNotFoundError:
            with lock:
                not_founds.append(1)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                other_errors.append(exc)

    threads = [threading.Thread(target=try_close, daemon=True) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert not other_errors, f"unexpected errors: {other_errors}"
    assert len(successes) == 1, f"expected exactly 1 successful close, got {len(successes)}"
    assert len(not_founds) == 2, (
        f"expected 2 BinaryNotFoundError, got {len(not_founds)}"
    )
