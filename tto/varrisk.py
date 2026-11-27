"""DV01 Risk → VaR: the realized vol and correlations of the TRY OIS and offshore curves' DV01 buckets.

The desk (27.11.2026): "Bir de dv01 risk'e var hesaplamasi koyalim. Burada offshore'u, ve ois'e ayri ayri bakacagiz. Ois
tarafini da onshore ve ois olarak ikiye ayiralim, bunlarin toplamina ve ayri ayri da bakacagiz. Realized vol'den
hesaplayacagiz".

From the history's daily closes (:mod:`tto.history` - the series it keeps anyway: nothing is asked of Bloomberg) this
works out, for each window of ``extras.VAR_WINDOWS``, the covariance (bp² a day) of the day-to-day moves of the 20 DV01
buckets (``extras.VAR_BUCKETS``, O/N … 10Y) of each curve - the two are never mixed (docs/curves.md):

* **OIS** (TRY OIS, TLREF): O/N and S/N move with TLREF, 1W … 10Y with the OIS quotes (TYSO…: GFOF, the plain ticker
  filling its gaps, as the history keeps them);
* **offshore**: O/N with TRYION, S/N with TRYITN (USDTRY's spot is T+1: its tom/next is spot/next), 1W … 9M with the FX
  swap implied TRYI…, 1Y … 10Y with the XCCY TRYSAQ1…10;
* 3W, which neither curve quotes, halfway between 2W and 1M (linear by months, as the buckets split).

A curve's closes are made into one quote a tenor a market day as the MPC history makes them (:func:`history.curve_quotes`:
a tenor without a close goes on by its neighbours' move for a few days, a wrong print that comes back the next day is
left out); a move counts only between two market days on which every bucket of the curve has a level.  Today's (live)
point is left out: the moves end at the last close before today.

The covariances go into EK_VAR as shared values, uncounted (as tto/interp.py writes the PPK cells: a figure made of the
market, no input of the desk's); the workbook's own formulas (``extras._tto_dv01_var``) weigh each user's DV01s with the
window, the confidence and the horizon they chose.  Made again when the history changed (``History.rev``) or the day
did - on the calculation thread, when a calculation of the TRY workbook is asked for (``Service._calc``).
"""
from __future__ import annotations

import datetime as _dt
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import extras as ex
from .history import CARRY_DAYS, curve_quotes, tenor_months
from .xl.values import date_to_serial, serial_to_date

#: the engine's dependency group of the cells written (one bit: they change together)
GROUP = "var-stats"
#: how each bucket reads a curve's tenors: a tenor's label, or two whose levels it lies between (linear by months)
Source = Union[str, Tuple[str, str]]
OIS_SOURCES: Dict[str, Source] = {"O/N": "TLREF", "S/N": "TLREF", "3W": ("2W", "1M")}
OFF_SOURCES: Dict[str, Source] = {"S/N": "T/N", "3W": ("2W", "1M")}
#: calendar days of closes read back from today: the longest window's business days and room for holidays and gaps
LOOKBACK_DAYS = 800


def curve_levels(tenors: Sequence[Tuple[str, float, Dict[str, float]]]) -> Dict[str, Dict[str, float]]:
    """``{label: {day: level %}}`` of a curve's tenors (``(label, months, {day: close})`` each) made one quote a tenor a
    market day (:func:`history.curve_quotes`)."""
    order = sorted((t for t in tenors if t[2]), key=lambda t: t[1])
    if not order:
        return {}
    values, _ = curve_quotes([(months, points) for _, months, points in order])
    return {label: values[k] for k, (label, _, _) in enumerate(order)}


def carried(points: Dict[str, float], days: Sequence[str], stale: int = CARRY_DAYS) -> Dict[str, float]:
    """A series (TLREF) on a curve's market days: a day without its close takes the last one, at most ``stale`` market
    days old."""
    out: Dict[str, float] = {}
    last: Optional[float] = None
    age = 0
    for d in days:
        v = points.get(d)
        if v is not None:
            last, age = v, 0
        elif last is not None:
            age += 1
            if age > stale:
                last = None
        if last is not None:
            out[d] = last
    return out


def bucket_moves(levels: Dict[str, Dict[str, float]], sources: Dict[str, Source], buckets: Sequence[str],
                 before: str) -> Tuple[List[str], List[List[float]]]:
    """The day-to-day moves (bp) of the buckets: ``(days, [[move of each bucket] a day])`` - a move between two market
    days (before ``before``) on which every bucket has a level."""
    days = sorted({d for pts in levels.values() for d in pts if d < before})

    def reader(bucket: str):
        src = sources.get(bucket, bucket)
        if isinstance(src, tuple):
            lo, hi = src
            a, b, m = tenor_months(lo), tenor_months(hi), tenor_months(bucket)
            w = (m - a) / (b - a)
            pa, pb = levels.get(lo) or {}, levels.get(hi) or {}

            def between(d: str) -> Optional[float]:
                x, y = pa.get(d), pb.get(d)
                return None if x is None or y is None else x + w * (y - x)
            return between
        return (levels.get(src) or {}).get

    readers = [reader(b) for b in buckets]
    rows = [[f(d) for f in readers] for d in days]
    out_days: List[str] = []
    out: List[List[float]] = []
    for k in range(1, len(days)):
        a, b = rows[k - 1], rows[k]
        if None in a or None in b:
            continue
        out_days.append(days[k])
        out.append([(y - x) * 100.0 for x, y in zip(a, b)])
    return out_days, out


def covariance(moves: Sequence[Sequence[float]]) -> Optional[List[List[float]]]:
    """The sample covariance (n − 1) of the moves' columns; ``None`` for fewer than two days."""
    n = len(moves)
    if n < 2:
        return None
    m = len(moves[0])
    mean = [sum(x[j] for x in moves) / n for j in range(m)]
    cols = [[x[j] - mean[j] for x in moves] for j in range(m)]
    cov = [[0.0] * m for _ in range(m)]
    for i in range(m):
        ci = cols[i]
        for j in range(i, m):
            v = sum(a * b for a, b in zip(ci, cols[j])) / (n - 1)
            cov[i][j] = cov[j][i] = v
    return cov


def window_stats(days: Sequence[str], moves: Sequence[Sequence[float]], window: int) -> Dict[str, Any]:
    """The last ``window`` moves: how many, the first and last day, their covariance."""
    take = list(moves[-window:]) if window > 0 else []
    picked = list(days[-window:]) if window > 0 else []
    return {"n": len(take), "first": picked[0] if picked else None, "last": picked[-1] if picked else None,
            "cov": covariance(take)}


def stats(defs: Sequence[Any], data: Dict[str, Dict[str, float]], today: _dt.date,
          windows: Sequence[Tuple[str, int]] = ex.VAR_WINDOWS,
          buckets: Sequence[str] = ex.VAR_BUCKETS) -> Dict[str, List[Dict[str, Any]]]:
    """Each curve's (``"ois"``, ``"off"``) statistics for each window, from the history's series ``defs``
    (:class:`history.SeriesDef`) and their closes ``data`` (``{series id: {day: close}}``, backups merged in as the
    history does)."""
    before = today.isoformat()
    tenors: Dict[str, List[Tuple[str, float, Dict[str, float]]]] = {"ois": [], "off": []}
    tlref: Dict[str, float] = {}
    for d in defs:
        if d.group == "ref":
            tlref = d.merged(data)[1]
        elif d.group in ("ois", "off", "xccy") and d.months is not None:
            tenors["ois" if d.group == "ois" else "off"].append((d.label, float(d.months), d.merged(data)[1]))
    out: Dict[str, List[Dict[str, Any]]] = {}
    for curve, sources in (("ois", OIS_SOURCES), ("off", OFF_SOURCES)):
        levels = curve_levels(tenors[curve])
        if curve == "ois" and levels:
            market = sorted({d for pts in levels.values() for d in pts})
            levels["TLREF"] = carried(tlref, market)
        days, moves = bucket_moves(levels, sources, buckets, before)
        out[curve] = [window_stats(days, moves, n) for _, n in windows]
    return out


def cell_values(st: Optional[Dict[str, List[Dict[str, Any]]]]) -> Dict[str, Any]:
    """What goes into EK_VAR's cells (A1 address → value; ``None`` empties a cell) for ``stats``' result."""
    where = ex.var_stat_cells()
    out: Dict[str, Any] = {}

    def serial(day: Optional[str]) -> Optional[float]:
        return date_to_serial(_dt.date.fromisoformat(day)) if day else None

    empty: List[Dict[str, Any]] = [{} for _ in where["stats"]]
    ois_all, off_all = (st or {}).get("ois") or empty, (st or {}).get("off") or empty
    for k, cells in enumerate(where["stats"]):
        ois, off = ois_all[k], off_all[k]
        out[cells["n_ois"]] = float(ois.get("n") or 0)
        out[cells["first_ois"]] = serial(ois.get("first"))
        out[cells["n_off"]] = float(off.get("n") or 0)
        out[cells["first_off"]] = serial(off.get("first"))
        lasts = [x for x in (ois.get("last"), off.get("last")) if x]
        out[cells["last"]] = serial(max(lasts)) if lasts else None
        for curve, s in (("ois", ois), ("off", off)):
            cov = s.get("cov")
            for i, row in enumerate(where["cov"][k][curve]):
                for j, addr in enumerate(row):
                    out[addr] = cov[i][j] if cov else None
    return out


class VarRisk(object):
    """The EK_VAR cells of the TRY workbook, kept current with the history (see the module's notes)."""

    def __init__(self, service):
        self.svc = service
        self.tto = service.books.get("tto")
        self._lock = threading.Lock()
        self._key: Optional[Tuple[Any, ...]] = None
        self.cells: Dict[str, Tuple[int, int]] = {}
        self.stats: Dict[str, Any] = {"made": 0, "ms": 0.0, "error": ""}
        if self.tto is not None and ex.VAR_SHEET in self.tto.model.sheet_index:
            where = ex.var_stat_cells()
            addrs = [a for cells in where["stats"] for a in cells.values()]
            addrs += [a for block in where["cov"] for rows in block.values() for row in rows for a in row]
            self.cells = {a: self.tto.cell("%s!%s" % (ex.VAR_SHEET, a)) for a in addrs}

    @property
    def available(self) -> bool:
        return bool(self.cells)

    def declare(self) -> None:
        """The cells the service writes, to the engine (one dependency bit: nobody types into them)."""
        if self.available:
            self.tto.engine.declare_inputs(list(self.cells.values()), group=GROUP)

    def refresh(self) -> None:
        """EK_VAR made again when the history changed or the day did (calculation thread; a quick look otherwise)."""
        if not self.available:
            return
        hist = getattr(self.svc, "history", None)
        today = self.tto.engine.clock.today()
        key = (getattr(hist, "rev", None), int(today))
        if key == self._key:
            return
        with self._lock:
            if key == self._key:
                return
            t0 = time.perf_counter()
            try:
                st = self._compute(hist, serial_to_date(today)) if hist is not None else None
                self.stats["error"] = ""
            except Exception as exc:  # noqa: BLE001 - the page shows "no history" rather than nothing at all
                st = None
                self.stats["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                ops = getattr(self.svc, "ops", None)
                if ops is not None:
                    ops.failure("VaR gerçekleşen vol", exc)
            vals = {self.cells[a]: v for a, v in cell_values(st).items()}
            self.tto.engine.set_inputs(vals, counted=False)
            self._key = key
            self.stats.update(made=self.stats["made"] + 1, ms=round((time.perf_counter() - t0) * 1000.0, 1),
                              at=time.strftime("%H:%M:%S"))

    def _compute(self, hist: Any, today: _dt.date) -> Dict[str, List[Dict[str, Any]]]:
        snap = hist.snapshot()
        defs = [d for d in snap["defs"] if d.group in ("ref", "ois", "off", "xccy")]
        ids = [i for d in defs for i in d.ids()]
        start = (today - _dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
        data = self.svc.store.hist_many(ids, start, today.isoformat())
        return stats(defs, data, today)
