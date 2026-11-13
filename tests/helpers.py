"""Shared test helpers."""
from __future__ import annotations

import datetime as _dt
import os
import sys
from typing import Any, Dict, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fake_blpapi  # noqa: E402

from tto.marketdata.bloomberg import RT_FIELDS, _override_value  # noqa: E402
from tto.xl.values import XlArray, serial_to_date  # noqa: E402


def server_from_snapshot(snapshot: Dict[Tuple, Any]) -> "fake_blpapi.Server":
    """A fake Bloomberg that answers exactly what the workbook's cached add-in results say."""
    srv = fake_blpapi.Server()
    for key, value in snapshot.items():
        kind = key[0]
        if kind == "BDP":
            ov = tuple(sorted((n, _override_value(n, v)) for n, v in key[3]))
            srv.ref[(key[1], key[2], ov)] = value
            if not key[3] and key[2] in RT_FIELDS and isinstance(value, float):
                srv.rt.setdefault((key[1], RT_FIELDS[key[2]]), value)
        elif kind == "BDS":
            rows = value.rows if type(value) is XlArray else [[value]]
            out = []
            for row in rows:
                if all(x is None for x in row):
                    continue
                item = {}
                for j, x in enumerate(row):
                    if x is None:
                        continue
                    item["col%d" % j] = serial_to_date(x) if (j == 0 and isinstance(x, float) and 30000 < x < 80000) else x
                out.append(item)
            srv.ref[(key[1], key[2], key[3])] = out
        elif kind == "BDH":
            opts = dict(key[5])
            start = _dt.datetime.strptime(key[3], "%Y%m%d").date()
            rows = value.rows if type(value) is XlArray else [[value]]
            canned = []
            if opts.get("DATES") == "H" or type(value) is not XlArray:
                day = start
                for row in rows:
                    while opts.get("DAYS") == "W" and day.weekday() >= 5:
                        day += _dt.timedelta(days=1)
                    canned.append((day, row[0]))
                    day += _dt.timedelta(days=1)
            else:
                for row in rows:
                    if row[0] is None:
                        continue
                    canned.append((serial_to_date(row[0]), row[1] if len(row) > 1 else None))
            srv.history_exact[(key[1], key[2], key[3], key[4])] = canned
    return srv


def close(a: Any, b: Any, rel: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        if a != a and b != b:
            return True
        return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))
    return type(a) is type(b) and a == b


def close(a: Any, b: Any, rel: float = 1e-9, abs_tol: float = 1e-12) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        if a != a and b != b:
            return True
        return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))
    return type(a) is type(b) and a == b


def complete_snapshot(replay_service) -> Dict[Tuple, Any]:
    """The workbook snapshot plus the TRY OIS quotes that only appear inside larger formulas.

    ``BDP`` calls that are wrapped in other functions (``IFERROR(BDP(..)/100, ..)``) leave no raw result in
    the workbook; for the OIS curve the raw quote is simply the cached par rate in percent.
    """
    snap = dict(replay_service.provider.snapshot)
    tto = replay_service.books["tto"]

    def collect():
        calc = tto.engine.shared
        out = {}
        for row in range(9, 27):
            root, par = calc.value("OIS_MAIN!J%d" % row), calc.value("OIS_MAIN!B%d" % row)
            if isinstance(root, str) and root and isinstance(par, float):
                q = round(par * 100.0, 6)
                for sec, fld in ((root + " GFOF Curncy", "MID"), (root + " GFOF Curncy", "PX_LAST"),
                                 (root + " Curncy", "PX_LAST"), (root + " Curncy", "MID")):
                    out[("BDP", sec, fld, ())] = q
        tlref = calc.value("OIS_MAIN!J2")
        if isinstance(tlref, float):
            out[("BDP", "BISTTREF Index", "PX_LAST", ())] = round(tlref * 100.0, 6)
        return out

    for k, v in replay_service.et.call(collect).items():
        snap.setdefault(k, v)
    return {k: v for k, v in snap.items() if k[0] not in ("BFX", "RT")}


def complete_snapshot(replay_service) -> Dict[Tuple, Any]:
    """The workbook snapshot plus the raw results of add-in calls that sit inside larger formulas.

    A cell like ``=BDP("BISTTREF Index","PX_LAST")/100`` leaves only its final value in the workbook.  The
    raw Bloomberg answer is recovered by trying the obvious candidates (the value itself, ×100, ÷100, the
    date as text) and keeping the one for which the cell's own formula reproduces the cached value.
    Returns the snapshot without BFXFORWARD / RTGET items (they have no Bloomberg API equivalent).
    """
    from tto.marketdata.base import tr_date_text
    from tto.marketdata.replay import _KeyCapture, _NoDeps
    from tto.render import calc_value
    from tto.xl.compiler import ADDINS
    from tto.xl.engine import addin_cells
    from tto.xl.model import COLS
    from tto.xl.parser import parse_template, walk

    provider = replay_service.provider
    capture, nodeps = _KeyCapture(), _NoDeps()

    def candidates(cv):
        if isinstance(cv, bool):
            return [cv]
        if isinstance(cv, float):
            out = [cv, round(cv * 100.0, 10), cv / 100.0]
            if 30000 < cv < 80000 and cv == int(cv):
                out.insert(0, tr_date_text(serial_to_date(cv)))
            return out
        return [cv]

    def run():
        added = 0
        for book in replay_service.books.values():
            eng, model, calc = book.engine, book.model, book.engine.shared
            for si, rc in addin_cells(model):
                sh = model.sheets[si]
                cv = sh.cached.get(rc)
                if cv is None or type(cv).__name__ == "XlError":
                    continue
                tid = sh.fml[rc]
                try:
                    root = parse_template(model.templates[tid])
                except Exception:  # noqa: BLE001
                    continue
                top = root
                while top[0] == "paren":
                    top = top[1]
                calls = [n for n in walk(root) if n[0] == "func" and (n[3] or n[1] in ADDINS) and n[1] != "BINTERPOL"]
                if not calls or (top[0] == "func" and top is calls[0]):
                    continue                                   # no add-in, or a bare call (already in the snapshot)
                r, c = divmod(rc, COLS)
                node = calls[0]
                try:
                    args = [eng.compiler.compile_node(a)(calc, si, r, c) if a[0] != "missing" else None for a in node[2]]
                    key = capture.call(nodeps, node[1], si, r, c, args)
                except Exception:  # noqa: BLE001
                    continue
                if type(key) is not tuple or key[0] in ("BFX", "RT") or key in provider.snapshot:
                    continue
                fn = eng.code(si, rc, tid)
                for cand in candidates(cv):
                    provider.snapshot[key] = cand
                    try:
                        got = calc_value(calc, fn, si, r, c)
                    except Exception:  # noqa: BLE001
                        got = None
                    if close(got, cv, 1e-12):
                        added += 1
                        break
                    del provider.snapshot[key]
        return added

    replay_service.et.call(run)
    return {k: v for k, v in provider.snapshot.items() if k[0] not in ("BFX", "RT")}




def mini_engine(cells: Dict[str, Any], today: float = 46329.0, array: Tuple[str, ...] = ()):
    """A tiny one-sheet workbook for unit tests: ``{"A1": 5, "B1": "=A1*2"}`` -> ``Engine``.

    Addresses listed in ``array`` are entered as legacy array formulas (Ctrl+Shift+Enter) of one cell.
    """
    from tto.xl.engine import Clock, Engine
    from tto.xl.model import COLS, Model, parse_a1
    from tto.xl.tokenizer import to_template

    model = Model()
    sh = model.add_sheet("S")
    model.xfs = [["General", False, None, None, None, False]]
    model.numfmts = ["General"]
    model.xf_flags = [0]
    for addr, v in cells.items():
        rc = parse_a1(addr)
        r, c = divmod(rc, COLS)
        if isinstance(v, str) and v.startswith("="):
            t = to_template(v[1:], r, c)
            if t not in model.templates:
                model.templates.append(t)
            sh.fml[rc] = model.templates.index(t)
            if addr in array:
                sh.arr[rc] = (r, c, r, c)
        elif isinstance(v, bool) or v is None or isinstance(v, str):
            sh.consts[rc] = v
        else:
            sh.consts[rc] = float(v)
        sh.max_row = max(sh.max_row, r)
        sh.max_col = max(sh.max_col, c)
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)      # type: ignore[assignment]
    return Engine(model, provider=None, clock=clock)


def ev(formula: str, cells: Dict[str, Any] = None, **kw) -> Any:
    """Value of one formula placed in Z50 of a tiny workbook holding ``cells``."""
    data = dict(cells or {})
    data["Z50"] = formula if formula.startswith("=") else "=" + formula
    return mini_engine(data, **kw).shared.value("S!Z50")


def mini_book(cells: Dict[str, Any], **sheet_attrs):
    """A one-sheet ``Book`` (sheet "S") for renderer tests; ``sheet_attrs`` set fields of the sheet
    (``hidden_cols=[[3, 3]]``, ``freeze=[0, 1]``, ``merges=["A1:C1"]``, ``comments={rc: text}`` ...)."""
    from tto.books import Book

    model = mini_engine(cells).model
    for key, value in sheet_attrs.items():
        setattr(model.sheets[0], key, value)
    return Book("mini", "Mini", model)


def read_xlsx(raw: bytes) -> Dict[str, Dict[str, Any]]:
    """Read an .xlsx written by ``tto.xlsx`` back: ``{sheet name: {"A1": value, ...}}``.

    The special keys ``"!formats"`` (address -> number format), ``"!merges"`` and ``"!pane"`` describe the rest.
    """
    import io
    import xml.etree.ElementTree as ET
    import zipfile

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    out: Dict[str, Dict[str, Any]] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert zf.testzip() is None
        for name in zf.namelist():                       # every part is well-formed XML
            ET.fromstring(zf.read(name))
        styles = ET.fromstring(zf.read("xl/styles.xml"))
        codes = {int(f.get("numFmtId")): f.get("formatCode") for f in styles.iter(ns + "numFmt")}
        xfs = [codes.get(int(x.get("numFmtId")), "General") for x in styles.find(ns + "cellXfs")]
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))}
        for sh in wb.find(ns + "sheets"):
            root = ET.fromstring(zf.read("xl/" + rels[sh.get(rel + "id")]))
            cells: Dict[str, Any] = {"!formats": {}, "!merges": [m.get("ref") for m in root.iter(ns + "mergeCell")], "!pane": None}
            pane = root.find(".//" + ns + "pane")
            if pane is not None:
                cells["!pane"] = pane.get("topLeftCell")
            for c in root.iter(ns + "c"):
                t, v = c.get("t"), c.find(ns + "v")
                if t == "inlineStr":
                    value: Any = "".join(x.text or "" for x in c.iter(ns + "t"))
                elif v is None:
                    continue
                elif t == "b":
                    value = v.text == "1"
                elif t == "e":
                    value = v.text
                else:
                    value = float(v.text)
                cells[c.get("r")] = value
                cells["!formats"][c.get("r")] = xfs[int(c.get("s", "0"))]
            out[sh.get("name")] = cells
    return out
