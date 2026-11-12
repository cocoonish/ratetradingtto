"""Independent reference: let LibreOffice recalculate the workbook and compare it with the engine.

The model is exported to a plain .xlsx in which every Bloomberg cell is frozen at the value Excel cached
(text dates turned into serial numbers) and TODAY()/NOW() are fixed, LibreOffice (headless) recalculates
it from scratch, and every formula cell is then compared with the engine's own full recalculation on the
same inputs.  Cells Excel never calculated are covered this way.

    python tools/lo_reference.py models/tto.json.gz --work /tmp/lo [--show 20]
"""
from __future__ import annotations

import argparse
import collections
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tto.xl import numfmt  # noqa: E402
from tto.xl.engine import Clock, Engine, addin_cells, cached_pins, run_with_big_stack  # noqa: E402
from tto.xl.errors import E_NA, XlError  # noqa: E402
from tto.xl.export import export_xlsx  # noqa: E402
from tto.xl.importer import import_workbook  # noqa: E402
from tto.xl.model import COLS, Model, a1  # noqa: E402
from tto.xl.values import parse_number_text  # noqa: E402

_PROFILE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
"""


def reference_pins(model, extra=None):
    """Freeze every add-in cell: cached value when there is one, otherwise #N/A; text dates -> serials."""
    pins = cached_pins(model)
    for key in addin_cells(model):
        if key not in pins:
            pins[key] = E_NA
    for key, v in list(pins.items()):
        if type(v) is str:
            n = parse_number_text(v)
            if n is not None and "." in v and v.count(".") == 2:
                pins[key] = n
    if extra:
        pins.update(extra)
    return pins


def libreoffice(src, outdir, profile):
    os.makedirs(os.path.join(profile, "user"), exist_ok=True)
    with open(os.path.join(profile, "user", "registrymodifications.xcu"), "w", encoding="utf-8") as fh:
        fh.write(_PROFILE)
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if exe is None:
        raise RuntimeError("LibreOffice (soffice) not found")
    cmd = [exe, "-env:UserInstallation=file://" + profile, "--headless", "--norestore", "--convert-to",
           "xlsx:Calc MS Excel 2007 XML", "--outdir", outdir, src]
    t0 = time.time()
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3600)
    return res.stdout.decode("utf-8", "replace"), time.time() - t0


def same(a, b, tol):
    ta, tb = type(a), type(b)
    if ta is float and tb is float:
        if a == b:
            return True
        d = abs(a - b)
        return d <= tol * max(abs(a), abs(b)) or d <= 1e-11
    if ta is XlError and tb is XlError:
        return True                      # LibreOffice reports some errors under another code
    if ta is str and tb is str:
        return a == b
    if ta is bool and tb is bool:
        return a == b
    if ta is bool and tb is float:
        return float(a) == b
    if tb is bool and ta is float:
        return float(b) == a
    if a is None:
        return b is None or b == "" or b == 0.0
    return False


def run(args):
    numfmt.set_engine_locale("en")
    model = Model.load(args.model)
    today = args.today
    extra = {}
    if args.inputs:
        import json
        with open(args.inputs, encoding="utf-8") as fh:
            for ref, val in json.load(fh).items():
                if ref.startswith("_"):
                    continue
                extra[model.cell_ref(ref)] = float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else val
    pins = reference_pins(model, extra)
    os.makedirs(args.work, exist_ok=True)
    src = os.path.join(args.work, "reference_input.xlsx")
    outdir = os.path.join(args.work, "out")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "reference_input.xlsx")
    if not (args.reuse and os.path.exists(out)):
        export_xlsx(model, src, pins=pins, today=today, now=today + 0.5, portable=True)
        log, secs = libreoffice(src, outdir, os.path.join(args.work, "profile"))
        print("LibreOffice: %.0fs  %s" % (secs, log.strip()[-200:]))
    ref = import_workbook(out)

    eng = Engine(model, clock=Clock(today + 0.5))
    eng.clock.today = lambda: float(today)
    eng.set_pins(pins)
    calc = eng.shared
    t0 = time.time()
    total = ok = 0
    by_sheet = collections.OrderedDict()
    bad = []
    skipped = collections.Counter()
    for s in model.sheets:
        if args.sheet and s.name not in args.sheet:
            continue
        rs = ref.sheet(s.name)
        n = good = 0
        cells = list(s.fml.keys()) + list(s.members.keys())
        for rc in cells:
            if (s.index, rc) in pins:
                continue
            r, c = divmod(rc, COLS)
            lo = rs.cached.get(rc, rs.consts.get(rc))
            try:
                v = calc.get(s.index, r, c)
            except Exception as exc:  # noqa: BLE001
                v = "EXC:%s:%s" % (type(exc).__name__, str(exc)[:100])
            n += 1
            if same(v, lo, args.tol):
                good += 1
            else:
                bad.append((s.name, rc, v, lo))
        by_sheet[s.name] = (n, good)
        total += n
        ok += good
    print("engine full recalculation: %.1fs (%d evaluations)" % (time.time() - t0, calc.evals))
    for name, (n, good) in by_sheet.items():
        if n:
            print("  %-18s %6d / %6d  %8.4f%%  mismatches=%d" % (name, good, n, 100.0 * good / n, n - good))
    print("TOTAL %d / %d = %.4f%%   mismatches=%d" % (ok, total, 100.0 * ok / max(total, 1), total - ok))
    if args.show:
        kinds = collections.Counter()
        for name, rc, v, lo in bad:
            kinds[(name, type(v).__name__, type(lo).__name__)] += 1
        print("mismatch kinds:", dict(kinds))
        shown = collections.Counter()
        for name, rc, v, lo in bad:
            if shown[name] >= args.show:
                continue
            shown[name] += 1
            s = model.sheet(name)
            tpl = model.templates[s.fml[rc]] if rc in s.fml else "(array member of %s)" % a1(s.members[rc])
            print("  %s!%s  engine=%r  libreoffice=%r   %s" % (name, a1(rc), v, lo, tpl[:args.width]))
    return bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--work", required=True)
    ap.add_argument("--sheet", action="append")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--width", type=int, default=200)
    ap.add_argument("--tol", type=float, default=1e-9)
    ap.add_argument("--today", type=float, default=46329.0)
    ap.add_argument("--reuse", action="store_true", help="reuse an existing LibreOffice result")
    ap.add_argument("--inputs", help="JSON file {\"Sheet!A1\": value} with extra frozen inputs")
    a = ap.parse_args()
    run_with_big_stack(run, a)
