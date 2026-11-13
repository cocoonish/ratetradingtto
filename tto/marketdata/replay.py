"""Replay provider: serves a frozen snapshot (no Bloomberg connection needed).

Used for the offline demo and for tests.  The snapshot is a plain dict ``key -> value`` (see
:mod:`tto.marketdata.base` for the key shapes); :func:`snapshot_from_model` rebuilds one from the values
Excel cached in the workbook at its last save.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..xl.errors import E_NA, XlError
from ..xl.values import XlArray
from .base import INVALID_FIELD, INVALID_SECURITY, NOT_APPLICABLE, Provider, bdp_key


class ReplayProvider(Provider):
    live = False

    def __init__(self, snapshot: Optional[Dict[Tuple, Any]] = None, label: str = ""):
        self.snapshot: Dict[Tuple, Any] = dict(snapshot or {})
        self.label = label
        self.missing: Dict[Tuple, int] = {}
        self.recorded_history: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}

    def _get(self, key):
        v = self.snapshot.get(key)
        if v is None:
            self.missing[key] = self.missing.get(key, 0) + 1
            return E_NA
        return v

    get_bdp = _get
    get_bdh = _get
    get_bds = _get
    get_bfx = _get
    get_rt = _get

    def set(self, key: Tuple, value: Any) -> None:
        self.snapshot[key] = value

    def update(self, values: Dict[Tuple, Any]) -> List[Tuple]:
        """Merge values; returns the keys whose value changed."""
        changed = []
        for k, v in values.items():
            if self.snapshot.get(k) != v:
                self.snapshot[k] = v
                changed.append(k)
        return changed

    def status(self) -> Dict[str, Any]:
        return {"mode": "replay", "connected": False, "label": self.label, "items": len(self.snapshot)}

    def unknown(self) -> List[Tuple[Tuple, str]]:
        """What Excel saved as Bloomberg's "no such security / field" answer (the add-in's text)."""
        final = (INVALID_SECURITY, INVALID_FIELD, NOT_APPLICABLE)
        return [(k, v) for k, v in self.snapshot.items() if type(v) is str and v in final]

    def load_history(self, path: str) -> int:
        """Load daily closes kept next to the offline quotes:
        ``{"series": {"TICKER|FIELD": {"yyyy-mm-dd": value, ...}}}`` (keys starting with "_" are comments)."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        n = 0
        for name, points in (data.get("series") or {}).items():
            sec, _, fld = name.partition("|")
            rows = sorted((d, float(v)) for d, v in points.items() if isinstance(v, (int, float)))
            self.recorded_history[(sec.strip(), (fld.strip() or "PX_LAST").upper())] = rows
            n += len(rows)
        return n

    def history(self, items, start, end, timeout=60.0):
        """What the snapshot holds: the history calls recorded in the workbook (``BDH`` blocks) and the
        closes loaded with :meth:`load_history`."""
        lo = "%s-%s-%s" % (start[:4], start[4:6], start[6:8])
        hi = "%s-%s-%s" % (end[:4], end[4:6], end[6:8])
        wanted = {(sec, fld.upper()) for sec, fld in items}
        found: Dict[Tuple[str, str], Dict[str, float]] = {}
        for key, value in self.snapshot.items():
            if key[0] != "BDH" or (key[1], key[2]) not in wanted:
                continue
            for day, v in _recorded_rows(key, value):
                if isinstance(v, float) and lo <= day <= hi:
                    found.setdefault((key[1], key[2]), {})[day] = v
        for item in wanted:
            for day, v in self.recorded_history.get(item, ()):
                if lo <= day <= hi:
                    found.setdefault(item, {}).setdefault(day, v)      # what the workbook recorded itself wins
        return {item: sorted(points.items()) for item, points in found.items() if points}

    def load_quotes(self, path: str) -> None:
        """Load ``{"TICKER|FIELD": value}`` JSON (keys starting with "_" are comments)."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if k.startswith("_"):
                continue
            sec, _, fld = k.partition("|")
            self.snapshot[bdp_key(sec.strip(), fld.strip() or "PX_LAST")] = float(v) if isinstance(v, (int, float)) else v


def _recorded_rows(key: Tuple, value: Any) -> List[Tuple[str, Any]]:
    """The rows of a recorded ``BDH`` block as ``[(yyyy-mm-dd, value), ...]``.

    A block saved with its dates carries them; one saved without (``Dates=H``) is a run of consecutive
    days from the start date of the call - week days when the call said ``Days=W``."""
    import datetime as _dt
    from ..xl.values import serial_to_date
    opts = dict(key[5])
    rows = value.rows if type(value) is XlArray else [[value]]
    out: List[Tuple[str, Any]] = []
    if opts.get("DATES") == "H" or type(value) is not XlArray:
        if opts.get("DIR") == "H" or opts.get("SORT") in ("D", "R"):
            return []
        try:
            day = _dt.datetime.strptime(key[3], "%Y%m%d").date()
        except ValueError:
            return []
        weekdays = opts.get("DAYS") == "W"
        if not weekdays and opts.get("DAYS") not in ("A", "C"):
            return []                                  # trading days only: the dates cannot be told
        for row in rows:
            while weekdays and day.weekday() >= 5:
                day += _dt.timedelta(days=1)
            out.append((day.isoformat(), row[0] if row else None))
            day += _dt.timedelta(days=1)
        return out
    for row in rows:
        if not row or type(row[0]) is not float or not (20000 < row[0] < 80000):
            continue
        out.append((serial_to_date(row[0]).isoformat(), row[1] if len(row) > 1 else None))
    return out


def addin_callers(engine) -> Dict[Tuple, List[Tuple[int, int]]]:
    """Which cell asks for which market-data item: every add-in call of the workbook - also one inside a
    larger formula (``WORKDAY(BDP(...)-1, ...)``) - with the key its arguments make now, in the shared
    calculation: ``{key: [(sheet index, rc), ...]}``.  Must run on the engine's thread."""
    from ..xl.compiler import ADDINS
    from ..xl.engine import addin_cells
    from ..xl.model import COLS
    from ..xl.parser import parse_template, walk

    model = engine.model
    calc = engine.shared
    capture = _KeyCapture()
    nodeps = _NoDeps()
    out: Dict[Tuple, List[Tuple[int, int]]] = {}
    calls: Dict[int, List[Any]] = {}
    for si, rc in addin_cells(model):
        tid = model.sheets[si].fml[rc]
        found = calls.get(tid)
        if found is None:
            try:
                found = [nd for nd in walk(parse_template(model.templates[tid]))
                         if nd[0] == "func" and (nd[3] or nd[1] in ADDINS) and nd[1] != "BINTERPOL"]
            except Exception:  # noqa: BLE001 - a formula the parser cannot read asks for nothing we know
                found = []
            calls[tid] = found
        r, c = divmod(rc, COLS)
        for nd in found:
            try:
                args = [engine.compiler.compile_node(a)(calc, si, r, c) if a[0] != "missing" else None for a in nd[2]]
                key = capture.call(nodeps, nd[1], si, r, c, args)
            except Exception:  # noqa: BLE001
                continue
            if type(key) is tuple:
                out.setdefault(key, []).append((si, rc))
    return out


class _KeyCapture(Provider):
    """Returns the normalised key of a call instead of its value."""

    def get_bdp(self, key):
        return key

    get_bdh = get_bds = get_bfx = get_rt = get_bdp


class _NoDeps(object):
    def depend_on_market(self, key):
        pass


def snapshot_from_model(engine) -> Dict[Tuple, Any]:
    """Rebuild ``key -> value`` from the workbook: every cell that is exactly one add-in call and has a
    cached value tells what Bloomberg returned for that call at the last save."""
    from ..xl.compiler import ADDINS
    from ..xl.engine import addin_cells
    from ..xl.model import COLS
    from ..xl.parser import parse_template

    model = engine.model
    calc = engine.shared
    capture = _KeyCapture()
    nodeps = _NoDeps()
    snap: Dict[Tuple, Any] = {}
    ast_cache: Dict[int, Any] = {}
    for si, rc in addin_cells(model):
        sh = model.sheets[si]
        if rc not in sh.cached:
            continue
        tid = sh.fml[rc]
        root = ast_cache.get(tid)
        if root is None:
            try:
                root = parse_template(model.templates[tid])
            except Exception:  # noqa: BLE001
                root = ("num", 0.0)
            while root[0] == "paren":
                root = root[1]
            ast_cache[tid] = root
        if root[0] != "func" or not (root[3] or root[1] in ADDINS) or root[1] == "BINTERPOL":
            continue
        r, c = divmod(rc, COLS)
        try:
            args = [engine.compiler.compile_node(a)(calc, si, r, c) if a[0] != "missing" else None for a in root[2]]
            key = capture.call(nodeps, root[1], si, r, c, args)
        except Exception:  # noqa: BLE001
            continue
        if type(key) is not tuple:
            continue
        value = sh.cached[rc]
        if root[1] in ("BDH", "BDS"):
            # the block the call filled: its saved array range, or the area reserved for it below / right
            # (the cells an add-in writes into are plain value cells in the file)
            ref = sh.arr.get(rc)
            zone = engine.spill_anchors[si].get(rc)
            if ref is not None and (ref[0] != ref[2] or ref[1] != ref[3]):
                r1, c1, r2, c2 = ref
            elif zone is not None and (zone[0] > 1 or zone[1] > 1):
                r1, c1, r2, c2 = r, c, r + zone[0] - 1, c + zone[1] - 1
            else:
                r1 = None
            if r1 is not None:
                rows = []
                for rr in range(r1, r2 + 1):
                    rows.append([sh.cached.get(rr * COLS + cc, sh.consts.get(rr * COLS + cc)) for cc in range(c1, c2 + 1)])
                while len(rows) > 1 and all(x is None for x in rows[-1]):
                    rows.pop()
                width = max((max((j + 1 for j, x in enumerate(row) if x is not None), default=1) for row in rows), default=1)
                rows = [row[:width] for row in rows]
                if len(rows) > 1 or width > 1:
                    value = XlArray(rows)
        snap[key] = value
    return snap
