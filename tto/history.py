"""History: daily closes of the market series, what the market priced for every MPC meeting day by day, the
end-of-day change matrix and the meeting calendar.

Three things live here.

**Daily closes.**  A table of ``(series, day, value)`` in the dashboard's database, filled from Bloomberg
history (``HistoricalDataRequest``) one year back and kept up to date while the server runs.  Offline it
holds what the workbook recorded (its ``BDH`` blocks) plus the TLREF fixings that ship with the dashboard.
Which series are kept is read from the workbook itself: the OIS ticker roots of ``OIS_MAIN``, the offshore
curve tickers of ``Forward``, the bonds of ``DİBS RV``.

**Meeting pricing history.**  For every past day the workbook's own solver (``Motor`` "GLOBAL İMA PPK") is
run again with that day's closes - on a second engine that is fed one day at a time (:class:`MpcMachine`).
The implied step / level of every meeting is stored per ``(day, meeting date)``, so a series stays with its
meeting when the list of meetings is rolled, and the series of meetings that have been held are kept.

**The meeting calendar.**  Meetings that are still in the workbook's list (``OIS_MAIN!P10:P89``) and the ones
that were taken out of it after they passed (the archive).  When the list is edited or rolled, everything
typed per meeting - the scenario steps ``U:W`` of every user, their saved scenarios and the workbook's own
steps - moves with its meeting (:func:`align_meetings`).
"""
from __future__ import annotations

import bisect
import datetime as _dt
import hashlib
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .books import Book, formula_text
from .inputs import parse_date
from .marketdata.base import Provider, tr_date_text
from .xl.engine import Clock
from .xl.model import COLS, parse_a1
from .xl.values import date_to_serial, serial_to_date

#: bump to have every stored MPC day computed again after a change of method
METHOD = 1
NA = "#N/A N/A"
BOOK = "tto"
OIS_SHEET = "OIS_MAIN"
MEETING_ROWS = (10, 89)                 # OIS_MAIN!P10:P89 - the 80 meeting slots of the workbook
OIS_ROWS = (9, 26)                      # OIS_MAIN!A9:J26 - tenor label (A) and ticker root (J)
HOLIDAY_ROWS = (361, 523)               # Motor!A361:A523
STEP_COLS = ("U", "V", "W")             # scenario step per meeting (S1, S2, S3)
MAX_STALE = 5                           # week days a close may be carried forward (a bayram is shorter)
MIN_QUOTES = 3                          # OIS quotes a day needs before the solver is run for it
PRICE_FIELDS = ("MID", "PX_LAST", "PX_MID", "BID", "ASK", "PX_BID", "PX_ASK", "LAST_PRICE")
#: meetings held before the workbook's list starts (CBRT calendar); the archive starts with these
DEFAULT_PAST_MEETINGS = ("2025-01-23", "2025-03-06", "2025-04-17", "2025-06-19", "2025-07-24", "2025-09-11", "2025-10-23",
                         "2025-12-11", "2026-01-22", "2026-03-12", "2026-04-22", "2026-06-11", "2026-07-23", "2026-09-10",
                         "2026-10-22")
DEFAULTS = {"dibs_field": "YLD_YTM_MID", "lookback_days": 370}
# the order of the Bloomberg pricing sources when the workbook has no source sheet (EK_KAYNAK, see tto.extras)
SOURCE_DEFAULTS = {"ois": ["GFOF"], "off": ["ICPL"], "xccy": ["ICPL"]}
SOURCE_ROWS = {"ois": 4, "off": 5, "xccy": 6}           # EK_KAYNAK!B4:E6


def source_lists(val) -> Dict[str, List[str]]:
    """The pricing sources per curve, in order (``val`` reads a cell of the workbook as everyone sees it)."""
    out: Dict[str, List[str]] = {}
    for kind, row in SOURCE_ROWS.items():
        first = val("EK_KAYNAK!A%d" % row)
        if first is None:                                   # no source sheet in this file
            out[kind] = list(SOURCE_DEFAULTS[kind])
            continue
        codes = []
        for col in "BCDE":
            c = re.sub(r"\s+", "", _text(val("EK_KAYNAK!%s%d" % (col, row)))).upper()
            if len(c) >= 2 and c not in codes:
                codes.append(c)
        out[kind] = codes
    return out


def source_text(snap: Dict[str, Any]) -> str:
    """How the OIS closes are sourced, for the notes of the pages: "GFOF → Excel (Curncy)"."""
    if not snap.get("src"):
        return ""
    codes = (snap.get("sources") or {}).get("ois") or []
    return " → ".join(list(codes) + ["Excel (%s)" % (snap.get("backup") or "Curncy")])


# ---------------------------------------------------------------------------------------------- small helpers
def _iso(d: _dt.date) -> str:
    return d.isoformat()


def _day(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def _serial(d: _dt.date) -> float:
    return float(date_to_serial(d))


def _of_serial(x: Any) -> Optional[_dt.date]:
    if type(x) is float and 20000 < x < 80000:
        return serial_to_date(x)
    return None


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def weekdays_ending(day: _dt.date, n: int) -> List[_dt.date]:
    """The last ``n`` week days up to and including ``day`` (oldest first)."""
    out: List[_dt.date] = []
    d = day
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= _dt.timedelta(days=1)
    out.reverse()
    return out


def next_business_day(day: _dt.date, holidays) -> _dt.date:
    d = day + _dt.timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d += _dt.timedelta(days=1)
    return d


def add_months(d: _dt.date, months: int) -> _dt.date:
    """Excel's EDATE."""
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return _dt.date(y, m, min(d.day, last))


def tenor_months(label: str) -> Optional[float]:
    """``"1W"`` -> 0.25, ``"3M"`` -> 3, ``"18M"`` -> 18, ``"2Y"`` -> 24, ``"O/N"`` -> 0.01, ``"T/N"`` -> 0.02."""
    s = label.strip().upper().replace(" ", "")
    if s in ("O/N", "ON"):
        return 0.01
    if s in ("T/N", "TN"):
        return 0.02
    m = re.match(r"^(\d+)([WMY])$", s)
    if not m:
        return None
    n = int(m.group(1))
    return {"W": n * 0.25, "M": float(n), "Y": n * 12.0}[m.group(2)]


def filled(points: Dict[str, float], axis: Sequence[_dt.date], stale: int = MAX_STALE) -> List[Optional[float]]:
    """The series along a week-day axis, a missing day taking the previous close (as ``Fill=P`` does) - but
    not for longer than ``stale`` week days, so that a series that stopped does not look unchanged."""
    out: List[Optional[float]] = []
    last: Optional[float] = None
    age = 0
    for d in axis:
        v = points.get(_iso(d))
        if v is not None:
            last, age = v, 0
        elif last is not None:
            age += 1
            if age > stale:
                last = None
        out.append(last)
    return out


#: trading days a tenor without a close may go on from its last one
CARRY_DAYS = 3
#: percent points (25 bp): a close that leaves what its neighbours did by this much, and comes back the next day
SPIKE = 0.25
#: tenors (months) below this are not judged that way: the very front does jump on its own (meeting days, month ends)
SPIKE_FROM_MONTHS = 2.0


def curve_quotes(tenors: Sequence[Tuple[float, Dict[str, float]]], stale: int = CARRY_DAYS, spike: float = SPIKE,
                 judge_from: float = SPIKE_FROM_MONTHS) -> Tuple[List[Dict[str, float]], Dict[str, Dict[str, List[int]]]]:
    """The quotes of a curve for every day the market closed on, from the daily closes of its tenors.

    ``tenors`` is ``[(maturity in months, {day: close in percent}), ...]``, shortest first.  The solver that reads
    these quotes fits all of them at once and is thrown about by a single one that does not belong to its day
    (a 3M quote 40 bp off moves the nearest meetings by a hundred basis points and more), so:

    * a tenor that has **no close** on a day goes on from its last one (at most ``stale`` trading days old)
      *by what its neighbours did since* - the nearest tenor on each side that closed on both days, weighted by
      maturity.  Carrying the level alone, as a plain "previous value" fill does, leaves a stale point in a
      curve that has moved; on a tenor that trades every other day that draws a zigzag;
    * a close that **leaves both its neighbours and comes back**: against the tenor on either side, it moves
      by ``spike`` or more into the day and by as much the other way out of it.  That is a quote that was not
      updated that day, or a wrong print; it is not used, and the day is filled as above.  A move that a
      neighbour shares - a segment of the curve, or all of it - is the market and is kept, however short
      lived.  (The largest such close of a day is taken out first and the others are looked at again.  Tenors
      shorter than ``judge_from`` months are left alone, and so is the latest day: it has no next day to
      come back on yet.)

    Returns ``(values, marks)``: ``values[i]`` = ``{day: quote}`` of tenor ``i``; ``marks[day]`` =
    ``{"carried": [i, ...], "cleaned": [i, ...]}`` for the days on which a quote is not that day's own close.
    """
    n = len(tenors)
    months = [float(m or 0.0) for m, _ in tenors]
    src: List[Dict[str, float]] = [dict(points) for _, points in tenors]       # the closes that count
    days = sorted({d for points in src for d in points})

    def move(i: int, a: str, b: str) -> Optional[float]:
        """What the neighbours of tenor ``i`` did between two days."""
        lo = next((j for j in range(i - 1, -1, -1) if a in src[j] and b in src[j]), None)
        hi = next((j for j in range(i + 1, n) if a in src[j] and b in src[j]), None)
        if lo is None and hi is None:
            return None
        if lo is None or hi is None:
            j = hi if lo is None else lo
            return src[j][b] - src[j][a]
        span = months[hi] - months[lo]
        w = (months[i] - months[lo]) / span if span > 0 else 0.5
        return (1.0 - w) * (src[lo][b] - src[lo][a]) + w * (src[hi][b] - src[hi][a])

    def alone(i: int, a: str, t: str, b: str) -> float:
        """How far tenor ``i`` left its neighbours on day ``t`` and came back on ``b`` (0: it did not)."""
        sides = [next((j for j in range(i - 1, -1, -1) if a in src[j] and t in src[j] and b in src[j]), None),
                 next((j for j in range(i + 1, n) if a in src[j] and t in src[j] and b in src[j]), None)]
        size, sign = None, 0.0
        for j in sides:
            if j is None:
                continue
            into = (src[i][t] - src[i][a]) - (src[j][t] - src[j][a])
            out = (src[i][b] - src[i][t]) - (src[j][b] - src[j][t])
            if into * out >= 0 or (sign and into * sign < 0):
                return 0.0                                 # it stayed there, or left the two sides in different directions
            sign = into
            size = min(abs(into), abs(out)) if size is None else min(size, abs(into), abs(out))
        return size or 0.0

    removed: Dict[str, List[int]] = {}
    for k in range(1, len(days) - 1):
        a, t, b = days[k - 1], days[k], days[k + 1]
        while True:
            worst, size = None, spike
            for i in range(n):
                if months[i] < judge_from or not (a in src[i] and t in src[i] and b in src[i]):
                    continue
                e = alone(i, a, t, b)
                if e >= size:
                    worst, size = i, e
            if worst is None:
                break
            del src[worst][t]
            removed.setdefault(t, []).append(worst)
    values: List[Dict[str, float]] = [dict(points) for points in src]
    marks: Dict[str, Dict[str, List[int]]] = {}
    for i in range(n):
        for k, t in enumerate(days):
            if t in src[i]:
                continue
            back = next((days[j] for j in range(k - 1, max(-1, k - 1 - stale), -1) if days[j] in src[i]), None)
            if back is None:
                continue                                   # no close for longer than a quote may be carried
            shift = move(i, back, t)
            values[i][t] = src[i][back] + (shift or 0.0)
            kind = "cleaned" if i in removed.get(t, ()) else "carried"
            marks.setdefault(t, {"carried": [], "cleaned": []})[kind].append(i)
    return values, marks


def day_flag(meta: Dict[str, Any]) -> str:
    """What is wrong with a computed day, by the workbook's own status of it (``OIS_MAIN!AU12``):

    * ``""``              nothing: every tenor quoted and the solver matched the quotes;
    * ``"missing"``       some tenors had no close ("Kota eksik: …"): solved with the rest, meetings beyond the
                          quotes are not priced - a result to use;
    * ``"inconsistent"``  the solver could not match the quotes within the sheet's tolerance ("Kota/takvim
                          tutarsız – kontrolü incele"): typically one close of that day is stale or wrong, and
                          the steps it gives are not to be trusted;
    * ``"error"``         the day could not be computed at all.
    """
    status = meta.get("status") or ""
    if status.startswith("HATA"):
        return "error"
    control, tolerance = meta.get("control"), meta.get("tolerance")
    if status.startswith("Kota/takvim tutarsız") or (control is not None and tolerance is not None and control > tolerance):
        return "inconsistent"
    return "missing" if status and status != "OK" else ""


#: days with these flags are kept in the database but left out of series, ranges and changes
UNRELIABLE = ("inconsistent", "error")


def align_meetings(old: Sequence[str], new: Sequence[str], tolerance: int = 45) -> Dict[int, Optional[int]]:
    """Which entry of the new list of meeting dates each entry of the old list became.

    ``{old index: new index, or None when the meeting is no longer in the list}``.  A date that is in both
    lists is the same meeting.  Between two such dates, a date that disappeared and a new date at most
    ``tolerance`` days away are a meeting whose date was corrected - the pairs are chosen so that the dates
    move as little as possible and stay in order; what is left over was removed (old) or is a new meeting.
    Both lists are ISO dates in ascending order.
    """
    pos = {d: j for j, d in enumerate(new)}
    out: Dict[int, Optional[int]] = {i: pos.get(d) for i, d in enumerate(old)}
    anchors = [(-1, -1)] + [(i, pos[d]) for i, d in enumerate(old) if d in pos] + [(len(old), len(new))]
    skip = tolerance / 2.0 + 0.25                       # leaving a pair unmatched costs more than any allowed move
    for (i0, j0), (i1, j1) in zip(anchors, anchors[1:]):
        gone = list(range(i0 + 1, i1))                  # old dates that are not in the new list
        fresh = list(range(j0 + 1, j1))                 # new dates that are not in the old list
        if not gone or not fresh:
            continue
        n, m = len(gone), len(fresh)
        cost = [[0.0] * (m + 1) for _ in range(n + 1)]
        step = [[""] * (m + 1) for _ in range(n + 1)]
        for a in range(n + 1):
            for b in range(m + 1):
                if a == 0 and b == 0:
                    continue
                best, how = float("inf"), ""
                if a > 0 and cost[a - 1][b] + skip < best:
                    best, how = cost[a - 1][b] + skip, "old"
                if b > 0 and cost[a][b - 1] + skip < best:
                    best, how = cost[a][b - 1] + skip, "new"
                if a > 0 and b > 0:
                    dist = abs((_day(new[fresh[b - 1]]) - _day(old[gone[a - 1]])).days)
                    if dist <= tolerance and cost[a - 1][b - 1] + dist < best:
                        best, how = cost[a - 1][b - 1] + dist, "pair"
                cost[a][b], step[a][b] = best, how
        a, b = n, m
        while a > 0 or b > 0:
            how = step[a][b]
            if how == "pair":
                out[gone[a - 1]] = fresh[b - 1]
                a, b = a - 1, b - 1
            elif how == "old":
                a -= 1
            else:
                b -= 1
    return out


# ---------------------------------------------------------------------------------------------- series
class SeriesDef(object):
    """One series of the history: where it comes from and how it is shown."""

    __slots__ = ("group", "label", "ticker", "field", "alts", "unit", "months", "root", "info")

    def __init__(self, group: str, label: str, ticker: str, field: str = "PX_LAST", alts: Sequence[str] = (),
                 unit: str = "pct", months: Optional[float] = None, root: str = "", info: Optional[Dict[str, Any]] = None):
        self.group = group              # ref | ois | off | xccy | dibs
        self.label = label
        self.ticker = ticker
        self.field = field.upper()
        self.alts = [a for a in alts if a and a != ticker]
        self.unit = unit                # pct: level in percent, change in bp · px: price, change in points
        self.months = months
        self.root = root
        self.info = info or {}

    @property
    def id(self) -> str:
        return "%s|%s" % (self.ticker, self.field)

    def ids(self) -> List[str]:
        return ["%s|%s" % (t, self.field) for t in [self.ticker] + self.alts]

    def pick(self, data: Dict[str, Dict[str, float]]) -> Tuple[str, Dict[str, float]]:
        """The ticker the series stands for and its closes (see :meth:`merged`)."""
        ticker, points, _ = self.merged(data)
        return ticker, points

    def merged(self, data: Dict[str, Dict[str, float]]) -> Tuple[str, Dict[str, float], Dict[str, str]]:
        """The closes of the main source, the backups filling only the days it has none.

        A backup's close is not taken as it stands - two sources rarely agree to the basis point, and a series that
        jumped between them would show moves that never happened (in a day's change, a realized vol, a z-score).
        The backup's move is laid on the main source's level instead: a missing day is the main source's close of
        the nearest day both have, plus what the backup did from that day to this one (the day before first; the
        day after for days before the main source began).  A main source without any close gives way to the
        backup as it is.  Returns ``(ticker, {day: close}, {day: backup ticker})`` - the ticker the series is
        shown with is the main one whenever it has a close at all.
        """
        points = dict(data.get(self.id) or {})
        ticker = self.ticker
        used: Dict[str, str] = {}
        for t in self.alts:
            other = data.get("%s|%s" % (t, self.field)) or {}
            if not other:
                continue
            if not points:
                points, ticker, used = dict(other), t, {}
                continue
            missing = [d for d in other if d not in points]
            if not missing:
                continue
            common = sorted(d for d in other if d in points)
            if not common:
                continue                            # nothing in common: the two levels cannot be tied together
            for d in sorted(missing):
                k = bisect.bisect_left(common, d)
                a = common[k - 1] if k > 0 else common[0]
                points[d] = points[a] + (other[d] - other[a])
                used[d] = t
        return ticker, points, used


# ---------------------------------------------------------------------------------------------- one past day
class DayProvider(Provider):
    """Answers the workbook's Bloomberg calls with the closes of one day."""

    live = False

    def __init__(self, tlref_ticker: str = "BISTTREF Index"):
        self.tlref_ticker = tlref_ticker
        self.quotes: Dict[str, float] = {}       # ticker root -> close (percent)
        self.tlref: Optional[float] = None
        self.spot_text: Optional[str] = None
        self.unknown: set = set()

    def get_bdp(self, key: Tuple) -> Any:
        sec, field = key[1], key[2]
        if field == "SETTLE_DT" and sec.split(" ", 1)[0] in ("TRY", "USDTRY"):
            return self.spot_text or NA
        if sec == self.tlref_ticker:
            return self.tlref if self.tlref is not None else NA
        if field in PRICE_FIELDS:
            v = self.quotes.get(sec.split(" ", 1)[0])
            return v if v is not None else NA          # no close that day: the workbook's own fallback applies
        self.unknown.add("%s|%s" % (sec, field))
        return NA

    def _none(self, key: Tuple) -> Any:
        self.unknown.add("%s|%s" % (key[1], key[0]))
        return NA

    get_bdh = get_bds = get_bfx = get_rt = _none

    def status(self) -> Dict[str, Any]:
        return {"mode": "history", "connected": False}


class MpcMachine(object):
    """A second engine of the TRY workbook that is fed one past day at a time and answers what the market
    priced for the meetings on that day - with the workbook's own formulas, nothing re-implemented."""

    def __init__(self, model, tlref_ticker: str = "BISTTREF Index"):
        self.provider = DayProvider(tlref_ticker)
        self.clock = Clock(0.5)
        self.book = Book(BOOK, "TRY masa (geçmiş)", model, provider=self.provider, clock=self.clock, replay=False)
        self.si = model.sheet_index[OIS_SHEET]
        self.mi = model.sheet_index["Motor"]
        self.book.declare("%s!P%d:P%d" % ((OIS_SHEET,) + MEETING_ROWS), scope="shared", group="hist-calendar")
        self.book.declare("%s!J%d:J%d" % ((OIS_SHEET,) + OIS_ROWS), scope="shared", group="hist-roots")
        self.book.declare("Motor!A%d:A%d" % HOLIDAY_ROWS, scope="shared", group="hist-holidays")
        self.solves = 0

    def solve(self, day: _dt.date, spot: _dt.date, tlref: float, quotes: Dict[str, float], meetings: Sequence[_dt.date],
              roots: Dict[int, Any], holidays: Sequence[float], horizon: Optional[_dt.date] = None) -> Dict[str, Any]:
        """Run the workbook for ``day``.  Returns ``{"rows": [...], "status", "control", "spot", "unknown"}``;
        a row is ``{"meeting", "step", "level", "cum", "sigma", "front"}`` (bp / fraction / bp / bp)."""
        eng = self.book.engine
        prov = self.provider
        prov.quotes = dict(quotes)
        prov.tlref = tlref
        prov.spot_text = tr_date_text(spot)
        prov.unknown = set()
        self.clock.fixed = _serial(day) + 0.5
        si, mi = self.si, self.mi
        values: Dict[Tuple[int, int], Any] = {}
        r1, r2 = MEETING_ROWS
        pc = parse_a1("P1") % COLS
        for k, r in enumerate(range(r1, r2 + 1)):
            values[(si, r * COLS + pc)] = _serial(meetings[k]) if k < len(meetings) else None
        jc = parse_a1("J1") % COLS
        for r in range(OIS_ROWS[0], OIS_ROWS[1] + 1):
            values[(si, r * COLS + jc)] = roots.get(r)
        h1, h2 = HOLIDAY_ROWS
        hol = list(holidays)[:h2 - h1 + 1]
        for k, r in enumerate(range(h1, h2 + 1)):
            values[(mi, r * COLS + 1)] = hol[k] if k < len(hol) else None
        eng.set_inputs(values)
        eng.reset()                                    # a new day: the clock and every quote changed
        calc = eng.shared
        col = {name: parse_a1(name + "1") % COLS for name in ("N", "P", "R", "S", "T")}
        rows: List[Dict[str, Any]] = []
        front_seen = False
        front_row: Optional[int] = None
        spot_serial = _serial(spot)
        for r in range(r1, r2 + 1):
            p = calc.get(si, r, col["P"])
            if type(p) is not float:
                continue
            level = calc.get(si, r, col["S"])
            step = calc.get(si, r, col["R"])
            if type(level) is not float or type(step) is not float:
                continue                               # passed ("geçti"), or beyond the quotes
            meeting = serial_to_date(p)
            front = (not front_seen) and p >= spot_serial
            front_seen = front_seen or front
            if front:
                front_row = r
            if horizon is not None and meeting > horizon:
                continue
            cum = calc.get(si, r, col["T"])
            sigma = calc.get(si, r, col["N"])
            rows.append({"meeting": _iso(meeting), "step": step, "level": level,
                         "cum": cum if type(cum) is float else None, "sigma": sigma if type(sigma) is float else None,
                         "front": front})
        # A day on which a meeting is held: the close already prices the decision, the TLREF fixing of that
        # day does not (it follows the next day).  Measured against that fixing - as the sheet does - the next
        # meeting would carry today's decision as well.  On such a day the steps are measured from the level
        # the solver itself puts before the next meeting.
        base = tlref / 100.0
        decision = any(m == day for m in meetings)
        if decision and front_row is not None and rows:
            own = self._solver_step(front_row, calc)
            first = next((x for x in rows if x["front"]), None)
            if own is not None and first is not None:
                base = first["level"] - own
                first["step"] = own * 10000.0
                for x in rows:
                    x["cum"] = round((x["level"] - base) * 10000.0, 2)
            else:
                decision = False
        status = calc.get(si, *divmod(parse_a1("AU12"), COLS))
        control = calc.get(si, *divmod(parse_a1("AU11"), COLS))
        allowed = calc.get(si, *divmod(parse_a1("AU6"), COLS))         # the sheet's own rule: AU11 > 5·AU6 is "tutarsız"
        b2 = calc.get(si, *divmod(parse_a1("B2"), COLS))
        self.solves += 1
        return {"rows": rows, "status": status if isinstance(status, str) else "",
                "control": control if type(control) is float else None,
                "tolerance": 5.0 * allowed if type(allowed) is float else None, "base": base, "decision": decision,
                "spot": _iso(serial_to_date(b2)) if type(b2) is float and 20000 < b2 < 80000 else None,
                "unknown": sorted(prov.unknown)}

    def _solver_step(self, row: int, calc) -> Optional[float]:
        """The solver's own step of the meeting in a row of the list (the cell the sheet's "Implied bps"
        formula of that row names: ``Motor!$A$5734`` for the first row)."""
        rc = row * COLS + parse_a1("R1") % COLS
        m = re.search(r"Motor!\$A\$(\d+)", formula_text(self.book, self.si, rc) or "")
        if not m:
            return None
        v = calc.get(self.mi, int(m.group(1)), 1)
        return v if type(v) is float else None


# ---------------------------------------------------------------------------------------------- the history
class History(object):
    def __init__(self, service):
        self.svc = service
        self.store = service.store
        self.rev = 1                                   # increases whenever stored history changed
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._het = None                               # big-stack thread that owns the MPC machine
        self._machine: Optional[MpcMachine] = None
        self._snap: Optional[Tuple[int, Dict[str, Any]]] = None
        self._empty: Dict[str, str] = {}               # series without any history -> the day it was asked (once a day)
        self._empty_day = ""                           # the day _empty was read for (from the store's records)
        self._force = False                            # the next pass recomputes every day
        self.state: Dict[str, Any] = {"phase": "idle", "done": 0, "total": 0, "error": "", "last_sync": None,
                                      "fetched": 0, "computed": 0}

    # ================================================================== settings
    def settings(self) -> Dict[str, Any]:
        out = dict(DEFAULTS)
        saved = self.store.get("hist.settings")
        if isinstance(saved, dict):
            out.update({k: v for k, v in saved.items() if k in DEFAULTS})
        return out

    def set_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        cur = self.settings()
        field = values.get("dibs_field")
        if field is not None:
            field = str(field).strip().upper().replace(" ", "_")
            if not re.match(r"^[A-Z][A-Z0-9_]{1,40}$", field):
                raise ValueError("alan adı anlaşılamadı: %r" % values.get("dibs_field"))
            cur["dibs_field"] = field
        days = values.get("lookback_days")
        if days is not None:
            try:
                days = int(days)
            except (TypeError, ValueError):
                raise ValueError("gün sayısı anlaşılamadı: %r" % (values.get("lookback_days"),))
            if not 30 <= days <= 1100:
                raise ValueError("geriye bakış 30 – 1100 gün arasında olmalı")
            cur["lookback_days"] = days
        self.store.put("hist.settings", cur)
        self._snap = None
        self.kick()
        return cur

    # ================================================================== what the workbook says
    def today(self) -> _dt.date:
        book = self.svc.books.get(BOOK)
        if book is None:
            return _dt.date.today()
        return serial_to_date(book.engine.clock.today())

    def snapshot(self) -> Dict[str, Any]:
        """The series to keep and the calendar, read from the live workbook (cached until something changes)."""
        gen = self.svc.gen
        hit = self._snap
        if hit is not None and hit[0] == gen:
            return hit[1]
        snap = self.svc.et.call(self._read_workbook)
        self._snap = (gen, snap)
        return snap

    def _read_workbook(self) -> Dict[str, Any]:
        book = self.svc.books.get(BOOK)
        if book is None:
            return {"today": _dt.date.today(), "spot": None, "defs": [], "roots": {}, "holidays": [], "rows": [], "labels": [],
                    "src": "", "backup": "", "sources": {k: [] for k in SOURCE_DEFAULTS}, "tlref": "BISTTREF Index", "stub": {}}
        calc = book.engine.shared
        model = book.model
        cfg = self.settings()

        def val(ref: str) -> Any:
            try:
                si, rc = book.cell(ref)
                return calc.get(si, *divmod(rc, COLS))
            except Exception:  # noqa: BLE001 - a sheet that is not in this file
                return None

        def literal_ticker(ref: str, fallback: str) -> str:
            """The security a cell's own BDP call names (``=BDP("TYSO1Z GFOF Curncy","MID")/100``)."""
            try:
                si, rc = book.cell(ref)
                m = re.search(r'BDP\(\s*"([^"]+)"', formula_text(book, si, rc) or "")
                return m.group(1) if m else fallback
            except Exception:  # noqa: BLE001
                return fallback

        today = serial_to_date(book.engine.clock.today())
        spot = _of_serial(val("%s!B2" % OIS_SHEET))
        # the order of the pricing sources, as the live pages use it (settings -> data sources, EK_KAYNAK):
        # OIS GFOF, offshore and XCCY ICPL, and last the workbook's own ticker (BGN) - here the source of
        # MASA's own history (MASA!S171) for the OIS
        lists = source_lists(val)
        other = _text(val("MASA!S171")) or "Curncy"

        def chain(root: str, codes: Sequence[str], last: str) -> List[str]:
            out: List[str] = []
            for t in ["%s %s Curncy" % (root, c) for c in codes] + [last]:
                if t and t not in out:
                    out.append(t)
            return out

        def ois_def(label: str, root: str) -> SeriesDef:
            tickers = chain(root, lists["ois"], "%s %s" % (root, other))
            return SeriesDef("ois", label, tickers[0], "PX_LAST", tickers[1:], months=tenor_months(label), root=root)

        src = ("%s Curncy" % lists["ois"][0]) if lists["ois"] else other
        tlref = literal_ticker("%s!J2" % OIS_SHEET, "BISTTREF Index")
        defs: List[SeriesDef] = [SeriesDef("ref", "TLREF", tlref, "PX_LAST")]
        roots: Dict[int, Any] = {}
        stub: Dict[str, str] = {}
        for label, ref in (("1W", "AU13"), ("2W", "AU14")):
            root = literal_ticker("%s!%s" % (OIS_SHEET, ref), "TYSO%sZ" % label[0]).split(" ", 1)[0]
            stub[label] = root
            defs.append(ois_def(label, root))
        for r in range(OIS_ROWS[0], OIS_ROWS[1] + 1):
            root = val("%s!J%d" % (OIS_SHEET, r))
            roots[r] = root if isinstance(root, str) and root.strip() else None
            label = _text(val("%s!A%d" % (OIS_SHEET, r)))
            if roots[r] is None or not label:
                continue
            root = root.strip()
            defs.append(ois_def(label, root))
        if "Forward" in model.sheet_index:
            for r in range(6, 27):
                ticker = _text(val("Forward!AO%d" % r))
                if not ticker:
                    continue
                if r <= 16:
                    label, group = _text(val("Forward!H%d" % r)), "off"
                else:
                    label, group = _text(val("Forward!C%d" % (125 + r - 17))), "xccy"
                if not label:
                    continue
                # offshore: the listed sources first (ICAP's page by default), the workbook's own ticker (BGN) last
                parts = ticker.split()
                tickers = chain(parts[0], lists[group], ticker) if len(parts) > 1 and parts[-1].upper() == "CURNCY" else [ticker]
                defs.append(SeriesDef(group, label, tickers[0], "PX_LAST", tickers[1:], months=tenor_months(label)))
        if "DİBS RV" in model.sheet_index:
            for r in range(5, 55):
                isin = _text(val("DİBS RV!A%d" % r))
                if not isin:
                    continue
                priced, plain = _text(val("DİBS RV!BT%d" % r)), _text(val("DİBS RV!BR%d" % r))
                if not priced and not plain:
                    continue
                kind = _text(val("DİBS RV!D%d" % r))
                name = _text(val("DİBS RV!C%d" % r))
                maturity = _of_serial(val("DİBS RV!E%d" % r))
                floater = kind in ("T", "F")           # a floater (TLREF, FRN) has no yield: its price is followed
                bist = val("DİBS RV!T%d" % r)          # the workbook's own BIST compound yield (as it stands now)
                defs.append(SeriesDef("dibs", isin, priced or plain, "PX_LAST" if floater else cfg["dibs_field"],
                                      [plain] if priced else [], unit="px" if floater else "pct",
                                      info={"isin": isin, "name": "" if name.startswith("#") else name, "type": kind,
                                            "maturity": _iso(maturity) if maturity else None, "row": r,
                                            "bist": bist if type(bist) is float else None}))
        # the global drivers and FX series of the quant signals (tto.quant): kept like the others, two years back
        from .quant import history_defs
        fx = getattr(self.svc, "fx", None)
        defs.extend(history_defs(fx.source() if fx is not None else "BGN"))
        holidays: List[float] = []
        mi = model.sheet_index.get("Motor")
        if mi is not None:
            for r in range(HOLIDAY_ROWS[0], HOLIDAY_ROWS[1] + 1):
                v = calc.get(mi, r, 1)
                if type(v) is float:
                    holidays.append(v)
        rows: List[Optional[str]] = []
        labels: List[str] = []
        for r in range(MEETING_ROWS[0], MEETING_ROWS[1] + 1):
            d = _of_serial(val("%s!P%d" % (OIS_SHEET, r)))
            rows.append(_iso(d) if d else None)
            labels.append(_text(val("%s!O%d" % (OIS_SHEET, r))) or "MPC%d" % (r - MEETING_ROWS[0] + 1))
        return {"today": today, "spot": spot, "defs": defs, "roots": roots, "holidays": holidays, "rows": rows,
                "labels": labels, "src": src, "backup": other, "sources": lists, "tlref": tlref, "stub": stub}

    # ================================================================== calendar
    def archive(self) -> List[str]:
        saved = self.store.get("mpc.archive")
        if not isinstance(saved, list):
            saved = list(DEFAULT_PAST_MEETINGS)
        out = []
        for d in saved:
            try:
                out.append(_iso(_day(str(d))))
            except ValueError:
                continue
        return sorted(set(out))

    def meetings(self, snap: Optional[Dict[str, Any]] = None) -> List[str]:
        """Every meeting the dashboard knows: the archive and the workbook's list (ISO dates, ascending)."""
        snap = snap or self.snapshot()
        return sorted(set(self.archive()) | {d for d in snap["rows"] if d})

    def calendar(self) -> Dict[str, Any]:
        snap = self.snapshot()
        spot = snap["spot"] or next_business_day(snap["today"], set())
        rows = []
        in_rows = set()
        for k, d in enumerate(snap["rows"]):
            if not d:
                continue
            in_rows.add(d)
            rows.append({"date": d, "row": MEETING_ROWS[0] + k, "label": snap["labels"][k], "passed": _day(d) < spot,
                         "where": "list"})
        past = [{"date": d, "row": None, "label": "", "passed": True, "where": "archive"} for d in self.archive() if d not in in_rows]
        items = sorted(past + rows, key=lambda x: x["date"])
        upcoming = [x for x in items if not x["passed"]]
        return {"today": _iso(snap["today"]), "spot": _iso(spot), "meetings": items, "slots": MEETING_ROWS[1] - MEETING_ROWS[0] + 1,
                "passed_in_list": sum(1 for x in rows if x["passed"]),
                "next": upcoming[0]["date"] if upcoming else None, "gen": self.svc.gen,
                "history_days": len(self.store.mpc_days()),       # what a new calendar makes the meeting history compute again
                "autoroll": self.store.get("mpc.autoroll"), "autoroll_error": self.state.get("autoroll_error") or ""}

    #: what a pasted column of dates may do to the list being edited
    PASTE_MODES = ("correct", "merge", "future")

    def preview_calendar(self, current: Sequence[Any], pasted: Sequence[Any], mode: str = "correct") -> Dict[str, Any]:
        """What a pasted column of dates does to the list being edited - nothing is saved:

        * ``correct`` - the dates the central bank announced: each corrects the meeting ahead nearest to it (at most
          45 days away; in order, the dates moving as little as possible - the pairing of ``align_meetings``, which
          saving uses to carry what was typed per meeting), a date with no meeting that near is added, every other
          meeting stays as it is;
        * ``merge`` - the dates that are not in the list are added;
        * ``future`` - the meetings ahead are replaced by the dates pasted.

        Meetings before the OIS spot (held, or in the archive) are never touched; pasted dates before it are left
        out (``skipped``).  Returns the list as saving would get it (``dates``), ``corrected`` ([was, now] pairs),
        ``added``, ``removed``, ``unchanged`` (pasted dates the list already had right) and ``history_days``.  More
        than the workbook's 80 rows is refused here already, with the dates that make it so."""
        from .service import ServiceError
        if mode not in self.PASTE_MODES:
            raise ServiceError("bilinmeyen yapıştırma şekli: %s" % mode)
        try:
            have = self.parse_dates(current)
            given = self.parse_dates(pasted)
        except ValueError as exc:
            raise ServiceError(str(exc))
        if not given:
            raise ServiceError("yapıştırılanlarda tarih yok")
        snap = self.snapshot()
        spot = _iso(snap["spot"] or next_business_day(snap["today"], set()))
        held = [d for d in have if d < spot]
        ahead = [d for d in have if d >= spot]
        skipped = [d for d in given if d < spot]
        given = [d for d in given if d >= spot]
        corrected: List[List[str]] = []
        added: List[str] = []
        removed: List[str] = []
        unchanged = 0
        if mode == "correct":
            moves = align_meetings(ahead, given)
            taken = set()
            kept = []
            for i, d in enumerate(ahead):
                j = moves[i]
                if j is None:
                    kept.append(d)                                # not announced (yet): stays as it is
                    continue
                taken.add(j)
                kept.append(given[j])
                if given[j] == d:
                    unchanged += 1
                else:
                    corrected.append([d, given[j]])
            added = [d for j, d in enumerate(given) if j not in taken]
            ahead = sorted(set(kept) | set(added))
        elif mode == "merge":
            added = [d for d in given if d not in set(ahead)]
            unchanged = len(given) - len(added)
            ahead = sorted(set(ahead) | set(given))
        else:
            removed = [d for d in ahead if d not in set(given)]
            added = [d for d in given if d not in set(ahead)]
            unchanged = len(given) - len(added)
            ahead = list(given)
        dates = held + ahead
        # the workbook's list counts from its first meeting (or the spot, the earlier) - as saving will
        old = [d for d in snap["rows"] if d]
        cutoff = min(old[0], spot) if old else spot
        slots = MEETING_ROWS[1] - MEETING_ROWS[0] + 1
        listed = [d for d in dates if d >= cutoff]
        if len(listed) > slots:
            tr = lambda d: _day(d).strftime("%d.%m.%Y")                      # noqa: E731
            why = " (yakınında toplantı olmadığı için eklenen: %s)" % ", ".join(tr(d) for d in added) if added else ""
            raise ServiceError("listede en fazla %d toplantı olabilir, yapıştırılanlarla %d olur%s. Önce en uzaktaki %d toplantıyı "
                               "listeden çıkarın: %s" % (slots, len(listed), why, len(listed) - slots,
                                                         ", ".join(tr(d) for d in listed[slots:])))
        return {"dates": dates, "corrected": corrected, "added": added, "removed": removed, "unchanged": unchanged,
                "skipped": skipped, "spot": spot, "history_days": len(self.store.mpc_days())}

    @staticmethod
    def parse_dates(dates: Sequence[Any]) -> List[str]:
        out = set()
        for raw in dates:
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                serial = float(raw)
            else:
                serial = parse_date(str(raw))
            d = _of_serial(serial) if serial is not None else None
            if d is None or not 2000 <= d.year <= 2100:
                raise ValueError("tarih anlaşılamadı: %r" % (raw,))
            out.add(_iso(d))
        return sorted(out)

    def set_calendar(self, user: str, dates: Sequence[Any], roll: bool = False) -> Dict[str, Any]:
        """Replace the list of meetings.  Dates before the first meeting of the workbook's list go to the
        archive; with ``roll`` every meeting that has passed does, and the list starts at the next one.
        Whatever was typed per meeting moves with its meeting."""
        user = self.svc.require_user(user)
        try:
            wanted = self.parse_dates(dates)
        except ValueError as exc:
            from .service import ServiceError
            raise ServiceError(str(exc))
        res = self.svc.et.call_at(self.svc.et.WRITE, self._set_calendar, user, wanted, bool(roll))
        self._snap = None
        self.svc.bump()
        self.svc.warm()                                # every page reads the meetings: made again ahead
        self.kick()
        res["gen"] = self.svc.gen
        return res

    def _typed_rows(self, user: str, typed: Dict[int, Any]) -> Dict[str, Any]:
        """Meeting dates typed or pasted on the OIS page (``{row: value}``; a blank one leaves the list) change the
        list the way the calendar does: whatever was typed per meeting moves with its meeting.  Engine thread."""
        rows = list(self._read_workbook()["rows"])
        for r, value in typed.items():
            rows[r - MEETING_ROWS[0]] = value
        wanted = self.parse_dates(list(self.archive()) + [d for d in rows if d is not None])
        res = self._set_calendar(user, wanted, False)
        self._snap = None
        self.kick()
        return res

    def roll_calendar(self, user: str) -> Dict[str, Any]:
        """Take the meetings that have passed out of the workbook's list (into the archive)."""
        return self.set_calendar(user, self.meetings(), roll=True)

    #: who the automatic roll is, where a change is noted with its author
    AUTO_USER = "otomatik"

    def auto_roll(self) -> Optional[Dict[str, Any]]:
        """A meeting that has passed leaves the workbook's list by itself: the list starts at the next meeting, which
        is MPC1, the one that passed goes to the archive, and what was typed per meeting (the workbook's steps,
        every user's own, saved scenarios) moves with its meeting - what "Geçen toplantıları arşivle" does.  The
        service calls it when it starts and when the day turns.  ``None`` when no meeting of the list has passed."""
        try:
            if not self.calendar()["passed_in_list"]:
                return None
            res = self.svc.et.call_at(self.svc.et.WRITE, self._set_calendar, self.AUTO_USER, self.meetings(), True)
        except Exception as exc:  # noqa: BLE001 - the list stays as it is; the settings page says why
            self.state["autoroll_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            return None
        self.state["autoroll_error"] = ""
        self._snap = None
        self.store.put("mpc.autoroll", {"at": _dt.datetime.now().replace(microsecond=0).isoformat(sep=" "),
                                        "rolled": res["rolled"], "first": res["first"]})
        self.svc.bump()
        self.svc.warm()
        self.kick()
        return res

    def _set_calendar(self, user: str, wanted: List[str], roll: bool) -> Dict[str, Any]:
        from .service import ServiceError, _to_json
        svc = self.svc
        book = svc.books.get(BOOK)
        if book is None:
            raise ServiceError("TRY çalışma kitabı yüklü değil", 500)
        snap = self._read_workbook()
        spot = snap["spot"] or next_business_day(snap["today"], set())
        old = [d for d in snap["rows"] if d]
        if any(d is None for d in snap["rows"][:len(old)]):
            raise ServiceError("OIS sayfasındaki toplantı listesinde boş satır var – önce listeyi düzeltin")
        cutoff = spot if (roll or not old) else min(_day(old[0]), spot)
        new = [d for d in wanted if _day(d) >= cutoff]
        slots = MEETING_ROWS[1] - MEETING_ROWS[0] + 1
        if len(new) > slots:
            raise ServiceError("listede en fazla %d toplantı olabilir (%d verildi)" % (slots, len(new)))
        if not new:
            raise ServiceError("en az bir gelecek toplantı gerekli")
        archive = [d for d in wanted if _day(d) < cutoff]
        moves = align_meetings(old, new)
        si = book.model.sheet_index[OIS_SHEET]
        sheet = book.model.sheets[si]
        r0 = MEETING_ROWS[0]
        engine = book.engine

        # ---- what was typed per meeting: the workbook's own steps (as everybody sees them) ...
        source = {j: i for i, j in moves.items() if j is not None}          # new index -> old index
        shared_set: Dict[Tuple[int, int], Any] = {}
        shared_clear: List[Tuple[int, int]] = []
        span = max(len(old), len(new))                  # rows below both lists are left as they are
        for name in STEP_COLS:
            c = parse_a1(name + "1") % COLS
            current = {}
            for k in range(slots):
                rc = (r0 + k) * COLS + c
                current[k] = engine.input_value[si][rc] if rc in engine.input_value[si] else sheet.consts.get(rc)
            for k in range(span):
                rc = (r0 + k) * COLS + c
                value = current[source[k]] if k in source else None
                base = sheet.consts.get(rc)
                if value == base and type(value) is type(base):
                    if rc in engine.input_value[si]:
                        shared_clear.append((si, rc))
                elif current[k] != value or type(current[k]) is not type(value):
                    shared_set[(si, rc)] = value
        # ---- ... and every user's own steps and saved scenarios
        cells: Dict[str, Optional[str]] = {}
        for i in range(span):
            j = moves.get(i) if i < len(old) else None
            if j == i:
                continue
            for name in STEP_COLS:
                cells["%s!%s%d" % (OIS_SHEET, name, r0 + i)] = None if j is None else "%s!%s%d" % (OIS_SHEET, name, r0 + j)
        # ---- the dates
        pc = parse_a1("P1") % COLS
        dates: Dict[Tuple[int, int], Any] = {}
        for k in range(slots):
            dates[(si, (r0 + k) * COLS + pc)] = _serial(_day(new[k])) if k < len(new) else None

        for key in list(shared_set) + shared_clear + list(dates):
            if key not in book.inputs:
                book.declare(book.ref(*key), scope="shared", group="adhoc-shared")
        if shared_clear:
            engine.clear_inputs(shared_clear)
            self.store.clear_shared_inputs(BOOK, [book.ref(*k) for k in shared_clear])
        changes = dict(shared_set)
        changes.update(dates)
        engine.set_inputs(changes)
        self.store.set_shared_inputs(BOOK, {book.ref(*k): _to_json(v) for k, v in changes.items()}, user)
        moved = self.store.remap_user_cells(BOOK, cells) if cells else {"moved": 0, "dropped": 0, "scenarios": 0}
        if cells:
            for name in list(engine.users):                       # overlays are rebuilt from what is stored now
                svc._overlays.pop((name, BOOK), None)
                engine.set_user_inputs(name, svc._overlay(name, book))
            for key in [k for k in svc._overlays if k[1] == BOOK]:
                svc._overlays.pop(key, None)
            svc._note_private()
        self.store.put("mpc.archive", sorted(set(archive)))
        rolled = [d for d in old if d not in new and _day(d) < cutoff]
        return {"meetings": len(new), "archive": len(archive), "rolled": rolled, "first": new[0],
                "moved": moved["moved"], "dropped": moved["dropped"], "scenarios": moved["scenarios"],
                "changed": sum(1 for i, j in moves.items() if j != i)}

    # ================================================================== fetching closes
    def kick(self) -> None:
        self._kick.set()

    def start(self, force: bool = False) -> None:
        """Keep the history up to date in the background (``force``: also when the setting turns it off)."""
        if self._thread is not None or self._stop.is_set():
            return
        if not force and not getattr(self.svc.settings, "history", True):
            return
        self._thread = threading.Thread(target=self._loop, name="tto-history", daemon=True)
        self._thread.start()

    def request_sync(self, recompute: bool = False) -> Dict[str, Any]:
        """Ask for an update now (it runs in the background; :meth:`status` tells how far it is)."""
        if recompute:
            self._force = True
        self._empty.clear()                            # series that had no history are asked again
        self.kick()
        self.start(force=True)
        return self.status()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        t = self._thread
        if t is not None:
            t.join(timeout=8.0)
        self._thread = None
        if self._het is not None:
            self._het.stop()
            self._het = None

    def _loop(self) -> None:
        live = self.svc.mode == "live"
        if live:
            # the workbook's own requests go first
            busy = getattr(self.svc.provider, "busy", None)
            t0 = time.time()
            while not self._stop.is_set() and time.time() - t0 < 90.0 and (time.time() - t0 < 5.0 or (busy is not None and busy())):
                self._stop.wait(0.5)
        while not self._stop.is_set():
            try:
                force, self._force = self._force, False
                self.sync(recompute=force)
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything (the log says what it was)
                self.state["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                self.state["phase"] = "idle"
                ops = getattr(self.svc, "ops", None)
                if ops is not None:
                    ops.failure("tarihçe", exc)
            interval = float(getattr(self.svc.settings, "history_refresh", 900.0) or 0.0)
            self._kick.wait(interval if (live and interval > 0) else None)

    def sync(self, recompute: bool = False, limit: Optional[int] = None, only: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """One pass: bring the closes up to date, then run the solver for the days whose inputs changed
        (newest first; ``limit`` caps how many, ``only`` names the days).  Blocks until done or until
        :meth:`kick` / :meth:`stop`."""
        with self._sync_lock:
            self._kick.clear()
            st = self.state
            st["error"] = ""
            try:
                st["phase"] = "fetch"
                fetched = self._fetch()
                st["fetched"] = fetched
                if fetched:
                    self.rev += 1
                st["phase"] = "mpc"
                computed = self._compute(recompute, limit, only)
                st["computed"] = computed
            finally:
                st["phase"] = "idle"
                st["last_sync"] = _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
            return {"fetched": fetched, "computed": computed, "rev": self.rev}

    #: every sync asks a series from its last close on - that close again and the day before it (calendar days back:
    #: a weekend), for the final value of a close stored during its day and a correction - and nothing older; a series
    #: further behind (the dashboard was off) the same way, from its last close: never the whole range again for that
    OVERLAP_DAYS = 3
    #: live: series that are new to the history and ask for it (``info["backfill"]``: the quant package's) get their
    #: first full range a few per sync, in the order they are listed - not all of them in one sync
    BACKFILL_PER_SYNC = 5
    #: the store's record of the full-range requests: series id -> {"day" of the last one, "from" the day it asked
    #: from, "first" the earliest day Bloomberg gave (None: nothing)}
    FETCH_KEY = "hist.fetch"

    def fetch_records(self) -> Dict[str, Dict[str, Any]]:
        v = self.store.get(self.FETCH_KEY)
        return v if isinstance(v, dict) else {}

    def _fetch(self) -> int:
        """Bring the closes up to date, asking Bloomberg as little as it takes (its daily data limit is the desk's):

        * a series' **full range** is asked at most **once a day** - and never again once it was asked from as far
          back as the window: what came back starts where Bloomberg's history of it starts (that day is kept in
          ``FETCH_KEY``); only a window that grows past every earlier request asks again;
        * otherwise only the **new days**: from the last close on (``OVERLAP_DAYS`` before it, for its final value);
        * a series without any history is asked once a day (a manual update asks again: :meth:`request_sync`);
        * live, the series marked ``backfill`` get their first full range ``BACKFILL_PER_SYNC`` at a time (the others
          wait for the next syncs: ``state["backfill"]``)."""
        snap = self.snapshot()
        today = snap["today"]
        today_iso = _iso(today)
        look = int(self.settings()["lookback_days"])
        first = today - _dt.timedelta(days=look)
        bounds = self.store.hist_bounds()
        records = self.fetch_records()
        if self._empty_day != today_iso:
            # a new day (or the first sync since the start): what was asked today and had nothing stays unasked today
            self._empty_day = today_iso
            self._empty = {sid: today_iso for sid, r in records.items() if r.get("day") == today_iso and sid not in bounds}
        rationed = self.svc.mode == "live"
        backfill: List[Tuple[int, int, str, str, _dt.date, Optional[Tuple[str, str, int]]]] = []
        full: Dict[Tuple[str, _dt.date], List[str]] = {}
        tail: Dict[Tuple[str, _dt.date], List[str]] = {}

        def recent(field: str, t: str, b: Tuple[str, str, int]) -> None:
            start = min(today, _day(b[1])) - _dt.timedelta(days=self.OVERLAP_DAYS)
            tail.setdefault((field, start), []).append(t)

        for d in snap["defs"]:
            # a series may ask for a longer past than the setting (the quant package's own: two years)
            since = min(first, today - _dt.timedelta(days=int(d.info.get("lookback") or 0)))
            reach = _iso(since + _dt.timedelta(days=20))
            for t in [d.ticker] + d.alts:
                sid = "%s|%s" % (t, d.field)
                b = bounds.get(sid)
                rec = records.get(sid) or {}
                if b is None:
                    if self._empty.get(sid) == today_iso:
                        continue                               # asked today, nothing came: not again before tomorrow
                    wanted = True
                else:
                    # the window reaches further back than anything asked so far (and not asked today)
                    wanted = b[0] > reach and str(rec.get("from") or "9999") > reach and rec.get("day") != today_iso
                if wanted and rationed and d.info.get("backfill"):
                    # (in turn: a series never asked before goes ahead of one asked again by hand)
                    backfill.append((1 if sid in records else 0, len(backfill), d.field, t, since, b))
                elif wanted:
                    full.setdefault((d.field, since), []).append(t)
                elif b is not None:
                    recent(d.field, t, b)
        backfill.sort()
        for _, _, field, t, since, b in backfill[:self.BACKFILL_PER_SYNC]:
            full.setdefault((field, since), []).append(t)
        for _, _, field, t, since, b in backfill[self.BACKFILL_PER_SYNC:]:
            if b is not None:
                recent(field, t, b)                            # what it has stays up to date meanwhile
        self.state["backfill"] = {"waiting": ["%s|%s" % (t, f) for _, _, f, t, _, _ in backfill[self.BACKFILL_PER_SYNC:]],
                                  "per_sync": self.BACKFILL_PER_SYNC if rationed else None}
        prov = self.svc.provider
        changed = 0
        end = today.strftime("%Y%m%d")
        for group in (full, tail):
            for (field, start), tickers in group.items():
                tickers = sorted(set(tickers))
                if not tickers or self._stop.is_set():
                    continue
                got = prov.history([(t, field) for t in tickers], start.strftime("%Y%m%d"), end, timeout=120.0)
                for t in tickers:
                    rows = got.get((t, field))
                    sid = "%s|%s" % (t, field)
                    if group is full:
                        # the day counts even when nothing came back; the range itself only once it did (an answer
                        # that did not come in time leaves the range to be asked again on another day)
                        old = records.get(sid) or {}
                        records[sid] = {"day": today_iso, "from": _iso(start) if rows else old.get("from"),
                                        "first": min(d for d, _ in rows) if rows else old.get("first")}
                    if rows:
                        self._empty.pop(sid, None)
                        changed += self.store.hist_upsert(sid, [(d, v) for d, v in rows if d <= _iso(today)])
                    elif sid not in bounds:
                        self._empty[sid] = today_iso
                if group is full:
                    self.store.put(self.FETCH_KEY, records)     # at once: a sync cut short still counts what it asked
        return changed

    def fill_states(self) -> Dict[str, str]:
        """Per series (by its main id): ``"ok"`` (it has closes), ``"filling"`` (its first full range is still waiting
        its turn, or it was not asked yet), ``"none"`` (asked, and Bloomberg had nothing)."""
        bounds = self.store.hist_bounds()
        records = self.fetch_records()
        waiting = set((self.state.get("backfill") or {}).get("waiting") or ())
        out: Dict[str, str] = {}
        for d in self.snapshot()["defs"]:
            ids = d.ids()
            has = any(i in bounds for i in ids)
            asked = any((records.get(i) or {}).get("day") for i in ids)
            out[d.id] = "filling" if (d.id in waiting or (not has and not asked)) else ("ok" if has else "none")
        return out

    # ================================================================== the meeting pricing of past days
    def _holidays(self, snap: Dict[str, Any], tlref: Dict[str, float]) -> Tuple[List[float], set]:
        """The workbook's holiday list plus the week days of the past on which TLREF was not fixed (the
        workbook only lists the holidays still ahead): ``(serials for Motor!A361:A523, set of dates)``."""
        base = [h for h in snap["holidays"]]
        known = set(base)
        extra: List[float] = []
        if tlref:
            days = sorted(tlref)
            d, last = _day(days[0]), _day(days[-1])
            while d < last:
                if d.weekday() < 5 and _iso(d) not in tlref and _serial(d) not in known:
                    extra.append(_serial(d))
                d += _dt.timedelta(days=1)
            if len(extra) > 0.08 * max(1, len(days)):
                extra = []                                     # that many gaps are missing data, not holidays
        room = HOLIDAY_ROWS[1] - HOLIDAY_ROWS[0] + 1 - len(base)
        extra = sorted(extra)[-room:] if room > 0 else []
        serials = sorted(base + extra)
        return serials, {serial_to_date(x) for x in serials if 20000 < x < 80000}

    def _plan(self, snap: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """The inputs of every day the solver can be run for (newest first) and what they share."""
        today = snap["today"]
        look = int(self.settings()["lookback_days"])
        first = today - _dt.timedelta(days=look)
        ois = [d for d in snap["defs"] if d.group == "ois"]
        ref = next((d for d in snap["defs"] if d.group == "ref"), None)
        ids = [i for d in ois for i in d.ids()] + (ref.ids() if ref else [])
        data = self.store.hist_many(ids, _iso(first - _dt.timedelta(days=12)), _iso(today))
        tlref = ref.pick(data)[1] if ref else {}
        serials, holidays = self._holidays(snap, tlref)
        own: Dict[str, int] = {}                               # day -> tenors with a close of that very day
        closes = []
        for d in ois:
            points = d.pick(data)[1]
            for k in points:
                own[k] = own.get(k, 0) + 1
            closes.append((d.months or 0.0, points))
        order = sorted(range(len(ois)), key=lambda i: closes[i][0])          # shortest first, as curve_quotes wants
        values, marks = curve_quotes([closes[i] for i in order])
        picked = [(ois[i], values[k]) for k, i in enumerate(order)]
        roots = [ois[i].root for i in order]
        calendar = [_day(d) for d in self.meetings(snap)]
        shared = {"roots": snap["roots"], "holidays": serials, "tlref_ticker": snap["tlref"]}
        hol_mark = hashlib.sha1(repr(serials).encode()).hexdigest()[:12]
        roots_mark = repr(sorted((k, v) for k, v in snap["roots"].items()))
        tl_days = sorted(tlref)
        plan: List[Dict[str, Any]] = []
        day = today
        while day >= first:
            if day.weekday() < 5 and day not in holidays:
                key = _iso(day)
                quotes = {d.root: pts[key] for d, pts in picked if key in pts}
                months = [d.months for d, pts in picked if key in pts and d.months]
                mark = marks.get(key) or {}
                carried = len(mark.get("carried", ())) + len(mark.get("cleaned", ()))
                cleaned = ", ".join(roots[i] for i in mark.get("cleaned", ()))
                # today's TLREF is the last fixing published by the close of the day
                fix = None
                for k in reversed(tl_days):
                    if k <= key:
                        fix = tlref[k] if (day - _day(k)).days <= 10 else None
                        break
                # a day counts when the market closed on it: carried-forward quotes alone do not make a day
                if len(quotes) >= MIN_QUOTES and own.get(key, 0) >= MIN_QUOTES and fix is not None:
                    spot = next_business_day(day, holidays)
                    meetings = [m for m in calendar if m >= day][:MEETING_ROWS[1] - MEETING_ROWS[0] + 1]
                    horizon = add_months(spot, int(max(months))) if months else spot
                    basis = hashlib.sha1(repr((METHOD, key, _iso(spot), fix, sorted(quotes.items()),
                                               [_iso(m) for m in meetings], hol_mark, roots_mark)).encode()).hexdigest()
                    plan.append({"day": day, "spot": spot, "tlref": fix, "quotes": quotes, "meetings": meetings,
                                 "horizon": horizon, "basis": basis, "carried": carried, "cleaned": cleaned})
            day -= _dt.timedelta(days=1)
        return plan, shared

    def _compute(self, recompute: bool = False, limit: Optional[int] = None, only: Optional[Sequence[str]] = None) -> int:
        snap = self.snapshot()
        if BOOK not in self.svc.books:
            return 0
        plan, shared = self._plan(snap)
        stored = self.store.mpc_days()
        todo = [p for p in plan if recompute or stored.get(_iso(p["day"]), {}).get("basis") != p["basis"]]
        window = _iso(snap["today"] - _dt.timedelta(days=int(self.settings()["lookback_days"])))
        gone = sorted(d for d in set(stored) - {_iso(p["day"]) for p in plan} if d >= window)
        if gone:
            self.store.mpc_delete(gone)                        # days that can no longer be computed (older ones are kept)
            self.rev += 1
        if only is not None:
            todo = [p for p in todo if _iso(p["day"]) in set(only)]
        if limit is not None:
            todo = todo[:limit]
        st = self.state
        st["done"], st["total"] = 0, len(todo)
        done = 0
        # live: the solver shares the interpreter with the engine that serves the desk, so it rests after every
        # day (history_pace times as long as the day took) - a year of history may take a little longer
        pace = float(getattr(self.svc.settings, "history_pace", 0.0) or 0.0) if self.svc.mode == "live" else 0.0
        for p in todo:
            if self._stop.is_set() or self._kick.is_set():
                break                                          # asked to stop, or the inputs changed: start over
            t0 = time.time()
            try:
                res = self._het_call(self._solve, p, shared)
                note = ""
                if res["unknown"]:
                    note = "eksik veri: " + ", ".join(res["unknown"][:6])
                self.store.mpc_save(_iso(p["day"]), p["basis"],
                                    {"spot": _iso(p["spot"]), "tlref": p["tlref"], "quotes": len(p["quotes"]),
                                     "status": res["status"], "note": note, "base": res["base"],
                                     "decision": res["decision"], "control": res.get("control"),
                                     "tolerance": res.get("tolerance"), "carried": p.get("carried"),
                                     "cleaned": p.get("cleaned") or ""}, res["rows"])
            except Exception as exc:  # noqa: BLE001 - one bad day must not stop the others
                self.store.mpc_save(_iso(p["day"]), p["basis"],
                                    {"spot": _iso(p["spot"]), "tlref": p["tlref"], "quotes": len(p["quotes"]),
                                     "status": "HATA", "note": "%s: %s" % (type(exc).__name__, str(exc)[:160])}, [])
            done += 1
            st["done"] = done
            self.rev += 1
            if pace > 0 and done < len(todo):
                self._kick.wait(min(5.0, pace * (time.time() - t0)))
        return done

    def _het_call(self, fn, *args):
        if self._het is None:
            from .service import EngineThread
            self._het = EngineThread("tto-history-engine")
        return self._het.call(fn, *args)

    def _solve(self, p: Dict[str, Any], shared: Dict[str, Any]) -> Dict[str, Any]:
        if self._machine is None or self._machine.provider.tlref_ticker != shared["tlref_ticker"]:
            self._machine = MpcMachine(self.svc.books[BOOK].model, shared["tlref_ticker"])
        return self._machine.solve(p["day"], p["spot"], p["tlref"], p["quotes"], p["meetings"], shared["roots"],
                                   shared["holidays"], p["horizon"])

    # ================================================================== status
    def status(self) -> Dict[str, Any]:
        bounds = self.store.hist_bounds()
        days = self.store.mpc_days()
        st = dict(self.state)
        flags = [day_flag(d) for d in days.values()]
        partial = sum(1 for f in flags if f)
        first = min((b[0] for b in bounds.values()), default=None)
        last = max((b[1] for b in bounds.values()), default=None)
        st.update({"rev": self.rev, "series": len(bounds), "first_day": first, "last_day": last, "mpc_days": len(days),
                   "mpc_partial": partial, "mpc_missing": flags.count("missing"),
                   "mpc_unreliable": sum(1 for f in flags if f in UNRELIABLE),
                   "mpc_first": min(days) if days else None, "mpc_last": max(days) if days else None,
                   "running": self._thread is not None and self._thread.is_alive(), "mode": self.svc.mode,
                   "auto": bool(getattr(self.svc.settings, "history", True)), "settings": self.settings(),
                   "refresh": float(getattr(self.svc.settings, "history_refresh", 900.0) or 0.0)})
        return st

    def coverage(self) -> Dict[str, Any]:
        """What is stored for every series the workbook asks for (the first place to look when a row of the
        matrix stays empty: a ticker or a field Bloomberg has no history for)."""
        snap = self.snapshot()
        bounds = self.store.hist_bounds()
        rows = []
        for d in snap["defs"]:
            backed = any(bounds.get("%s|%s" % (t, d.field)) for t in d.alts)       # a backup has closes
            for k, t in enumerate([d.ticker] + d.alts):
                b = bounds.get("%s|%s" % (t, d.field))
                rows.append({"group": d.group, "label": d.label, "ticker": t, "field": d.field, "alt": k > 0,
                             "main": k == 0 and bool(d.alts), "backed": k == 0 and backed,
                             "first": b[0] if b else None, "last": b[1] if b else None, "n": b[2] if b else 0})
        return {"series": rows, "state": self.status()}

    # ================================================================== end-of-day matrix
    @staticmethod
    def _changes(values: List[Optional[float]], scale: float) -> Dict[str, Any]:
        """Last value and its change against 1 / 5 / 21 week days earlier."""
        last = values[-1]
        out: Dict[str, Any] = {"last": last}
        for name, back in (("d1", 1), ("w1", 5), ("m1", 21)):
            prev = values[-1 - back] if len(values) > back else None
            out[name] = None if last is None or prev is None else (last - prev) * scale
            out[name + "_from"] = prev
        return out

    def matrix(self, asof: Optional[str] = None) -> Dict[str, Any]:
        """Levels on a day and their change over one day, one week (5 week days) and one month (21 week
        days) - the convention of the workbook's own Δ1G / Δ1H / Δ1A columns."""
        snap = self.snapshot()
        defs: List[SeriesDef] = snap["defs"]
        bounds = self.store.hist_bounds()
        core = [i for d in defs if d.group in ("ois", "ref") for i in d.ids() if i in bounds]
        last_day = max((bounds[i][1] for i in core), default=None) or max((b[1] for b in bounds.values()), default=None)
        days_with_data: List[str] = []
        if core:
            seen = set()
            for i in core[:6]:
                seen.update(d for d, _ in self.store.hist_series(i))
            days_with_data = sorted(seen, reverse=True)[:400]
        if asof:
            try:
                day = _day(asof)
            except ValueError:
                from .service import ServiceError
                raise ServiceError("tarih anlaşılamadı: %s" % asof)
        elif last_day:
            day = _day(last_day)
        else:
            day = snap["today"]
        while day.weekday() >= 5:
            day -= _dt.timedelta(days=1)
        axis = weekdays_ending(day, 22 + MAX_STALE)
        data = self.store.hist_many([i for d in defs for i in d.ids()], _iso(axis[0]), _iso(day))

        def entry(d: SeriesDef) -> Optional[Dict[str, Any]]:
            ticker, points, used = d.merged(data)
            if not points:
                return None
            vals = filled(points, axis)
            if vals[-1] is None:
                return None
            out = self._changes(vals, 100.0 if d.unit == "pct" else 1.0)
            out["sid"] = d.id                              # what a click on the row draws (:meth:`closes`)
            last = max((k for k in points if k <= _iso(day)), default=None)
            # the close of the day came from the backup (its move laid on the main source's level)
            out.update({"ticker": ticker, "field": d.field, "unit": d.unit, "day": last, "backup": used.get(last) if last else None})
            return out

        ref = next((d for d in defs if d.group == "ref"), None)
        curve: Dict[float, Dict[str, Any]] = {}
        for d in defs:
            if d.group not in ("ois", "off", "xccy") or d.months is None:
                continue
            row = curve.setdefault(d.months, {"tenor": d.label, "months": d.months, "ois": None, "off": None})
            side = "ois" if d.group == "ois" else "off"
            e = entry(d)
            if e is not None:
                e["kind"] = d.group
                row[side] = e
            if side == "ois":
                row["tenor"] = d.label
        bonds = []
        for d in defs:
            if d.group != "dibs":
                continue
            e = entry(d) or {"last": None, "d1": None, "w1": None, "m1": None, "ticker": d.ticker, "field": d.field,
                             "unit": d.unit, "day": None, "sid": d.id}
            e.update(d.info)
            bonds.append(e)
        bonds.sort(key=lambda b: (b.get("maturity") or "9999", b.get("isin") or ""))
        out = {"asof": _iso(day), "ref": {"d1": _iso(axis[-2]), "w1": _iso(axis[-6]), "m1": _iso(axis[-22])},
               "days": days_with_data, "tlref": entry(ref) if ref else None,
               "curve": [curve[k] for k in sorted(curve)], "bonds": bonds, "mpc": self._mpc_matrix(day, axis),
               "decision_day": bool((self.store.mpc_days(_iso(day), _iso(day)).get(_iso(day)) or {}).get("decision")),
               "source": {"ois": source_text(snap), "off": " → ".join((snap["sources"].get("off") or []) + ["Excel (BGN)"]),
                          "xccy": " → ".join((snap["sources"].get("xccy") or []) + ["Excel (BGN)"]),
                          "dibs_field": self.settings()["dibs_field"]},
               "live": self.svc.mode == "live", "rev": self.rev, "state": self.status()}
        return out

    def closes(self, sid: str) -> Dict[str, Any]:
        """The daily closes of one series of the history (its backups filling the days it has none, as the matrix
        reads it), the lookback and a little more: what a click on a row of the end-of-day matrix draws."""
        snap = self.snapshot()
        d = next((x for x in snap["defs"] if x.id == sid), None)
        if d is None:
            raise ValueError("tarihçede böyle bir seri yok: %s" % sid)
        today = snap["today"]
        start = today - _dt.timedelta(days=int(self.settings()["lookback_days"]) + 10)
        ticker, points, used = d.merged(self.store.hist_many(d.ids(), _iso(start)))
        return {"sid": sid, "label": d.label, "group": d.group, "unit": d.unit, "ticker": ticker, "field": d.field,
                "points": sorted((k, v) for k, v in points.items() if k <= _iso(today)), "backup_days": len(used),
                "info": d.info, "today": _iso(today)}

    def _mpc_matrix(self, day: _dt.date, axis: List[_dt.date]) -> List[Dict[str, Any]]:
        rows = self.store.mpc_values(_iso(axis[0]), _iso(day))
        meta = self.store.mpc_days(_iso(axis[0]), _iso(day))
        unreliable = {d for d, x in meta.items() if day_flag(x) in UNRELIABLE}
        by_day: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for r in rows:
            if r["day"] not in unreliable:
                by_day.setdefault(r["day"], {})[r["meeting"]] = r
        if not by_day:
            return []

        def at(target: _dt.date) -> Optional[Dict[str, Dict[str, Any]]]:
            """The last computed day up to ``target`` (not older than a bayram)."""
            for back in range(0, MAX_STALE + 3):
                hit = by_day.get(_iso(target - _dt.timedelta(days=back)))
                if hit is not None:
                    return hit
            return None

        now = at(day)
        if not now:
            return []
        refs = {"d1": at(axis[-2]), "w1": at(axis[-6]), "m1": at(axis[-22])}
        out = []
        for meeting in sorted(now):
            cur = now[meeting]
            item: Dict[str, Any] = {"meeting": meeting, "front": bool(cur["front"]), "sigma": cur["sigma"]}
            for measure, scale in (("step", 1.0), ("level", 10000.0), ("cum", 1.0)):
                e: Dict[str, Any] = {"last": cur[measure]}
                for name, ref in refs.items():
                    prev = ref.get(meeting) if ref else None
                    pv = prev[measure] if prev else None
                    e[name] = None if cur[measure] is None or pv is None else (cur[measure] - pv) * scale
                    e[name + "_from"] = pv
                item[measure] = e
            out.append(item)
        return out[:12]

    # ================================================================== meeting pricing time series
    def mpc(self, days: Optional[int] = None, upcoming: int = 16) -> Dict[str, Any]:
        snap = self.snapshot()
        today = snap["today"]
        look = int(days or self.settings()["lookback_days"])
        start = _iso(today - _dt.timedelta(days=look))
        meta = self.store.mpc_days(start, _iso(today))
        rows = self.store.mpc_values(start, _iso(today))
        axis = sorted(meta)
        index = {d: i for i, d in enumerate(axis)}
        cal = self.calendar()
        info = {m["date"]: m for m in cal["meetings"]}
        spot = _day(cal["spot"])
        flags = {d: day_flag(x) for d, x in meta.items()}
        unreliable = {d for d, f in flags.items() if f in UNRELIABLE}
        per: Dict[str, List[Dict[str, Any]]] = {}
        flagged: Dict[str, Dict[str, Dict[str, Any]]] = {}     # what the solver gave on the days it does not stand behind
        for r in rows:
            if r["day"] in unreliable:
                flagged.setdefault(r["day"], {})[r["meeting"]] = {k: r[k] for k in ("step", "level", "cum")}
            else:
                per.setdefault(r["meeting"], []).append(r)
        ahead = sorted(m for m in per if _day(m) >= spot)[:max(1, int(upcoming))]
        held = sorted(m for m in per if _day(m) < spot)
        ref = next((d for d in snap["defs"] if d.group == "ref"), None)
        tl: Dict[str, float] = {}
        if ref is not None:
            tl = ref.pick(self.store.hist_many(ref.ids(), start, _iso(today + _dt.timedelta(days=5))))[1]
        tl_days = sorted(tl)
        meetings = []
        series: Dict[str, Dict[str, List[Optional[float]]]] = {}
        for m in held + ahead:
            pts = sorted(per[m], key=lambda r: r["day"])
            cols = {k: [None] * len(axis) for k in ("step", "level", "cum")}
            for r in pts:
                i = index.get(r["day"])
                if i is None:
                    continue
                for k in cols:
                    cols[k][i] = r[k]
            series[m] = cols
            last = pts[-1]
            steps = [r["step"] for r in pts if r["step"] is not None]
            item = {"date": m, "passed": _day(m) < spot, "label": (info.get(m) or {}).get("label") or "",
                    "where": (info.get(m) or {}).get("where") or "", "n": len(pts), "first_day": pts[0]["day"],
                    "last_day": last["day"], "last": {k: last[k] for k in ("step", "level", "cum", "sigma")},
                    "min": min(steps) if steps else None, "max": max(steps) if steps else None}
            # change of the priced step against 1 / 5 / 21 week days earlier (the matrix's convention)
            wk = weekdays_ending(_day(last["day"]), 22 + MAX_STALE)
            chg = self._changes(filled({r["day"]: r["step"] for r in pts if r["step"] is not None}, wk), 1.0)
            for name in ("d1", "w1", "m1"):
                item[name] = chg[name]
            if item["passed"]:
                # what TLREF did: the fixing after the meeting against the fixing of the meeting day
                before = next((tl[k] for k in reversed(tl_days) if k <= m), None)
                after = next((tl[k] for k in tl_days if k > m), None)
                item["realized"] = None if before is None or after is None else (after - before) * 100.0
                item["priced"] = last["step"]
                item["surprise"] = None if item["realized"] is None or last["step"] is None else item["realized"] - last["step"]
            meetings.append(item)
        partial = sorted(d for d in axis if flags[d])
        issues = []
        for kind in ("inconsistent", "error", "missing"):
            hit = [d for d in axis if flags[d] == kind]
            if hit:
                texts: Dict[str, int] = {}
                for d in hit:
                    texts[meta[d].get("status") or ""] = texts.get(meta[d].get("status") or "", 0) + 1
                worst = max((meta[d]["control"] for d in hit if meta[d].get("control") is not None), default=None)
                issues.append({"kind": kind, "count": len(hit), "days": hit[-12:], "status": max(texts, key=texts.get),
                               "control": worst})
        return {"today": _iso(today), "spot": cal["spot"], "days": axis, "meetings": meetings, "series": series,
                "decision_days": [d for d in axis if meta[d].get("decision")],
                "tlref": [tl.get(d) if d in tl else next((tl[k] for k in reversed(tl_days) if k <= d), None) for d in axis],
                "quotes": [meta[d].get("quotes") for d in axis], "partial": len(partial),
                "flags": [flags[d] for d in axis], "control": [meta[d].get("control") for d in axis],
                "carried": [meta[d].get("carried") for d in axis], "cleaned": [meta[d].get("cleaned") or "" for d in axis],
                "issues": issues, "flagged": flagged,
                "status": sorted({x.get("status") or "" for x in meta.values()} - {""}),
                "notes": sorted({x.get("note") or "" for x in meta.values()} - {""})[:5],
                "source": source_text(snap), "live": self.svc.mode == "live", "rev": self.rev, "state": self.status()}
