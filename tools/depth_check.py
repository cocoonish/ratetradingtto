"""Depth check: every page and the header strip are the same whether long chains are unwound or evaluated in one go.

The calculation threads evaluate ``engine.DEEP_LIMIT`` nested cells before unwinding; other threads unwind at
``engine.DEPTH_LIMIT``.  This renders the header and every page (helper tables included) of a replay service from cold
once per limit and compares what the browser would get, cell by cell, and every value the engines computed.

    python tools/depth_check.py [--limits 90,1000] [--views masa,ois]

Exit code 0: identical; 1: a difference (listed).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tto.config import Settings  # noqa: E402
from tto.service import Service  # noqa: E402
from tto.xl.engine import set_depth_limit  # noqa: E402

VOLATILE = ("ms", "gen")             # the time a page took and the generation it belongs to


def _clean(v):
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if k not in VOLATILE}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _values(svc: Service):
    """Every value the shared calculations hold: {book: {(sheet, rc): (type, value)}}."""
    out = {}
    for bid, book in svc.books.items():
        calc = book.engine.shared
        out[bid] = {(si, rc): (type(v).__name__, repr(v)) for si, memo in enumerate(calc.memo) for rc, v in memo.items()}
    return out


def render_all(svc: Service, user: str, limit: int, views):
    """Header and pages from cold with ``limit``: (renders, values, seconds, restarts)."""
    def cold():
        set_depth_limit(limit)
        for book in svc.books.values():
            book.engine.reset()
            book.engine.shared.restarts = 0

    svc.et.call(cold)
    svc.bump()
    t0 = time.time()
    out = {"header": _clean(svc.header(user))}
    for vid in views:
        out["view:" + vid] = _clean(svc.view(user, vid, True))
    seconds = time.time() - t0
    restarts = sum(b.engine.shared.restarts for b in svc.books.values())
    return out, svc.et.call(_values, svc), seconds, restarts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limits", default="90,1000", help="depth limits to compare (the first is the reference)")
    ap.add_argument("--views", default="", help="only these pages (comma separated); default: every page")
    a = ap.parse_args()
    limits = [int(x) for x in a.limits.split(",") if x.strip()]
    data = tempfile.mkdtemp(prefix="tto_depth_")
    svc = Service(Settings(data_dir=data, mode="replay", history=False))
    try:
        user = svc.login("Derinlik Kontrolü")["user"]
        views = [v.strip() for v in a.views.split(",") if v.strip()] or [v["id"] for v in svc.views]
        ref = None
        bad = 0
        for limit in limits:
            renders, values, seconds, restarts = render_all(svc, user, limit, views)
            cells = sum(len(v) for v in values.values())
            print("limit %5d: header + %d pages in %.1f s, %d chains unwound, %d values"
                  % (limit, len(views), seconds, restarts, cells), flush=True)
            if ref is None:
                ref = (limit, renders, values)
                continue
            for key in ref[1]:
                if json.dumps(ref[1][key], sort_keys=True) != json.dumps(renders[key], sort_keys=True):
                    bad += 1
                    print("  DIFFERENT: %s (limit %d vs %d)" % (key, ref[0], limit))
            for bid in ref[2]:
                a_vals, b_vals = ref[2][bid], values[bid]
                diff = [k for k in set(a_vals) | set(b_vals) if a_vals.get(k) != b_vals.get(k)]
                if diff:
                    bad += 1
                    print("  %s: %d values differ, e.g. %s" % (bid, len(diff), [(k, a_vals.get(k), b_vals.get(k)) for k in diff[:3]]))
        print("identical" if not bad else "%d differences" % bad)
        return 1 if bad else 0
    finally:
        svc.stop()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
