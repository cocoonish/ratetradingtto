"""Parity check: evaluate every formula with the engine and compare with the values Excel cached.

Add-in (Bloomberg) cells are pinned to their cached values and the clock is fixed at the workbook's
last calculation date, so every other formula must reproduce Excel's own result.

    python tools/parity.py models/tto.json.gz [--sheet NAME] [--show 30] [--tol 1e-9]
"""
from __future__ import annotations

import argparse
import collections
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tto.xl.engine import Clock, Engine, cached_pins, formula_has_addin, run_with_big_stack  # noqa: E402
from tto.xl.errors import XlError  # noqa: E402
from tto.xl.model import COLS, Model, a1  # noqa: E402


def same(a, b, tol):
    ta, tb = type(a), type(b)
    if ta is float and tb is float:
        if a == b:
            return True
        d = abs(a - b)
        return d <= tol * max(abs(a), abs(b)) or d <= 1e-12
    if ta is XlError or tb is XlError:
        return a is b
    if ta is str and tb is str:
        return a == b
    if ta is bool and tb is bool:
        return a == b
    if a is None:
        return b is None or b == ""
    return False


def find_today(model):
    """Serial cached by a cell that is exactly =TODAY()."""
    for s in model.sheets:
        for rc, tid in s.fml.items():
            if model.templates[tid].upper() == "TODAY()" and rc in s.cached:
                return s.cached[rc]
    return None


def local_parity(model, eng, pins, args):
    """Evaluate each formula on the *cached* values of its precedents (isolates single-formula semantics)."""
    calc = eng.shared
    for s in model.sheets:
        memo = calc.memo[s.index]
        for rc, v in s.cached.items():
            memo[rc] = v
    total = ok = 0
    by_sheet = collections.OrderedDict()
    bad = []
    for s in model.sheets:
        if args.sheet and s.name not in args.sheet:
            continue
        memo = calc.memo[s.index]
        n = good = 0
        for rc in list(s.fml.keys()):
            if rc not in s.cached or (s.index, rc) in pins:
                continue
            r, c = divmod(rc, COLS)
            ref = s.arr.get(rc)
            cells = [rc]
            if ref is not None and (ref[0] != ref[2] or ref[1] != ref[3]):
                cells = [rr * COLS + cc for rr in range(ref[0], ref[2] + 1) for cc in range(ref[1], ref[3] + 1)]
            for m in cells:
                memo.pop(m, None)
            calc.rcache.clear()
            try:
                calc.get(s.index, r, c)
                err = None
            except Exception as exc:  # noqa: BLE001
                err = "EXC:%s:%s" % (type(exc).__name__, str(exc)[:100])
            dirty = False
            for m in cells:
                if m not in s.cached:
                    continue
                v = err if err is not None else memo.get(m)
                n += 1
                if same(v, s.cached[m], args.tol):
                    good += 1
                else:
                    bad.append((s.name, m, v, s.cached[m]))
                    dirty = True
                memo[m] = s.cached[m]
            if dirty:
                calc.rcache.clear()
        by_sheet[s.name] = (n, good)
        total += n
        ok += good
    return total, ok, by_sheet, bad


def run(args):
    model = Model.load(args.model)
    today = args.today if args.today is not None else find_today(model)
    eng = Engine(model, clock=Clock(today))
    pins = cached_pins(model)
    eng.set_pins(pins)
    calc = eng.shared
    t0 = time.time()
    total = ok = 0
    by_sheet = collections.OrderedDict()
    bad = []
    if args.local:
        total, ok, by_sheet, bad = local_parity(model, eng, pins, args)
    else:
        for s in model.sheets:
            if args.sheet and s.name not in args.sheet:
                continue
            n = good = 0
            for rc in list(s.cached.keys()):
                if rc not in s.fml and rc not in s.members:
                    continue
                if (s.index, rc) in pins:
                    continue
                r, c = divmod(rc, COLS)
                try:
                    v = calc.get(s.index, r, c)
                except Exception as exc:  # noqa: BLE001
                    v = "EXC:%s:%s" % (type(exc).__name__, str(exc)[:100])
                n += 1
                if same(v, s.cached[rc], args.tol):
                    good += 1
                else:
                    bad.append((s.name, rc, v, s.cached[rc]))
            by_sheet[s.name] = (n, good)
            total += n
            ok += good
    dt = time.time() - t0
    print("today=%s  pins=%d  evaluated=%d formulas in %.1fs  (engine evals=%d)" % (today, len(pins), total, dt, calc.evals))
    for name, (n, good) in by_sheet.items():
        if n:
            print("  %-18s %6d / %6d  %7.3f%%  mismatches=%d" % (name, good, n, 100.0 * good / n, n - good))
    print("TOTAL %d / %d = %.4f%%   mismatches=%d" % (ok, total, 100.0 * ok / max(total, 1), total - ok))
    if eng.compiler.unknown_functions:
        print("unknown functions:", sorted(eng.compiler.unknown_functions))
    if eng.compiler.errors:
        print("compile errors:", len(eng.compiler.errors), eng.compiler.errors[:5])
    if eng.circular:
        print("circular:", eng.circular[:10])
    if args.show:
        kinds = collections.Counter()
        for name, rc, v, exp in bad:
            kinds[(name, type(v).__name__ if not isinstance(v, str) or not v.startswith("EXC") else "EXC", type(exp).__name__)] += 1
        print("mismatch kinds:", dict(kinds))
        shown = collections.Counter()
        for name, rc, v, exp in bad:
            if shown[name] >= args.show:
                continue
            shown[name] += 1
            s = model.sheet(name)
            tpl = model.templates[s.fml[rc]] if rc in s.fml else "(array member of %s)" % a1(s.members[rc])
            print("  %s!%s  got=%r  excel=%r   %s" % (name, a1(rc), v, exp, tpl[:args.width]))
    return bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--sheet", action="append")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--width", type=int, default=220)
    ap.add_argument("--tol", type=float, default=1e-9)
    ap.add_argument("--today", type=float, default=None)
    ap.add_argument("--local", action="store_true", help="evaluate each formula on cached precedents")
    a = ap.parse_args()
    run_with_big_stack(run, a)
