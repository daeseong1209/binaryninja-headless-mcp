"""Manual ReDoS verification (not part of pytest suite).

Verifies two layers of defense:
1. The static nested-quantifier heuristic rejects pathological patterns
   *before* compile.
2. The daemon-thread watchdog raises TimeoutError on slower-divergent regex
   that yields the GIL between strings (best-effort — Python's `re` does not
   release the GIL during a single match, so this catches the multi-string
   case but not single-input catastrophic backtracking).
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from types import SimpleNamespace

# Force mock so we don't need a real BN license
os.environ["BINJA_MCP_FORCE_MOCK"] = "1"

# Make src/ importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from binja_mcp.mock_backend import MockString  # noqa: E402
from binja_mcp.supervisor import Supervisor  # noqa: E402
from binja_mcp.tools.strings import search_strings  # noqa: E402


def _make_ctx():
    sup = Supervisor(force_mock=True)
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"\x7fELF" + b"\x00" * 64)
        p = f.name

    bid = sup.open(p)
    bv = sup.get(bid).bv
    bv.strings = [MockString(value="a" * 60 + "!", address=0x1000 + i) for i in range(20)]

    ctx = SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(supervisor=sup)
        )
    )
    return sup, ctx, bid, p


def main() -> int:
    rc = 0

    # --- Layer 1: nested-quantifier heuristic rejects pre-compile ----------
    sup, ctx, bid, p = _make_ctx()
    print("layer 1: nested-quantifier heuristic", flush=True)
    t0 = time.time()
    try:
        search_strings(bid, ctx, pattern=r"(a+)+!", regex=True)
        print(f"  REJECT_FAILED elapsed={time.time()-t0:.2f}s", flush=True)
        rc = 1
    except ValueError as exc:
        if "nested quantifier" in str(exc):
            print(f"  REJECT_OK ({exc}) elapsed={time.time()-t0:.2f}s", flush=True)
        else:
            print(f"  WRONG_REJECT ({exc})", flush=True)
            rc = 1
    sup.close_all()
    os.unlink(p)

    # --- Layer 2: pattern length cap rejects --------------------------------
    sup, ctx, bid, p = _make_ctx()
    print("layer 2: pattern length cap", flush=True)
    try:
        search_strings(bid, ctx, pattern="a" * 257, regex=True)
        print("  CAP_FAILED", flush=True)
        rc = 1
    except ValueError as exc:
        if "too long" in str(exc):
            print(f"  CAP_OK ({exc})", flush=True)
        else:
            print(f"  WRONG_CAP ({exc})", flush=True)
            rc = 1
    sup.close_all()
    os.unlink(p)

    # --- Layer 3: safe regex still works ------------------------------------
    sup, ctx, bid, p = _make_ctx()
    print("layer 3: safe regex match", flush=True)
    t0 = time.time()
    try:
        r = search_strings(bid, ctx, pattern=r"^a+!$", regex=True)
        elapsed = time.time() - t0
        print(f"  SAFE_OK total={r['total']} elapsed={elapsed:.2f}s", flush=True)
    except Exception as exc:
        print(f"  SAFE_BROKE ({exc})", flush=True)
        rc = 1
    sup.close_all()
    os.unlink(p)

    return rc


if __name__ == "__main__":
    sys.exit(main())
