"""TRY rates two ways (18.11.2026).  A counterparty told the desk that FRA prices can differ "by the interpolation
choice"; the desk wants to see the rates both ways, side by side:

* **Bootstrap (Murex)** - today's curve, the workbook's own, which is also how Murex marks to market: the OIS quotes'
  par rates linear in months on a quarterly grid, bootstrapped, ln DF linear in days between the nodes
  (Motor!C88:I130, ``BOOT_GUN`` / ``BOOT_LNDF``); offshore the TRYI FX swap implied (up to 9M) and TRYSAQ cross
  currency (1Y-10Y) curve the same way (Forward!AJ123:AN143, ``OFF_GUN`` / ``OFF_LNDF``).  Read as it is
  (:class:`LogLinear`): nothing here changes it.
* **PPK basamak** - the meeting-date step method: the overnight rate (TLREF) flat between PPK meetings, jumping at
  them (:class:`StepCurve`).  Its shape is the PPK solver's implied path, "MPC ima" (Motor!C4:L84, read as MASA!H62 /
  I62 read it); :func:`calibrate` adds a flat overnight shift on each stretch between two successive quoted
  maturities, solved maturity by maturity, so that every quote the bootstrap is built from comes back exactly by its
  own convention (OIS: up to 3M one period simple ACT/365, then quarterly ACT/365 par; offshore: TRYI one period simple
  ACT/360, TRYSAQ annual ACT/360 par).  Offshore the same shape gets a flat basis between the offshore quotes instead.

The two curves agree at every quoted maturity and differ only in how they split the stretch between two quotes - what
an FRA or a broken date between them sees.  Days are calendar days from the curve's spot, rates decimals.  :func:`read`
builds everything from the workbook through a cell getter; the rest knows no workbook.
"""
from __future__ import annotations

import bisect
import math
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .xl.values import to_num

#: the overnight rate's day basis (TLREF: ACT/365, compounded on business days)
BASIS = 365.0
#: a calibrated quote comes back within ``TOLERANCE`` (|par − quote|, a rate) after at most ``STEPS`` secant steps
TOLERANCE, STEPS = 1e-12, 60

# where the TRY workbook keeps what both ways are built from (1-based rows / columns)
#: Motor's meeting table: C the effective day (days from the OIS spot), K the implied TLREF from it on (L: its ln G)
PATH_ROWS, PATH_DAY, PATH_RATE = (4, 84), 3, 11
#: Motor's daily calendar: F the cumulative weekend / holiday term Pcum (day 0 … 3700)
PCUM_ROWS, PCUM_COL = (528, 4228), 6
#: Motor's bootstrap: C its nodes' days, E their months, I ln DF (BOOT_GUN / BOOT_LNDF)
BOOT_ROWS, BOOT_DAY, BOOT_MONTH, BOOT_LNDF = (88, 130), 3, 5, 9
#: the copy of the OIS quotes the bootstrap and the PPK solver read: A months, B quote (OIS_MAIN B9:B26 without 15M, 21M)
QUOTE_ROWS, QUOTE_MONTH, QUOTE_RATE = (306, 321), 1, 2
#: Motor's quarterly calendar (3M … 120M) the FRA lists price on: F the payment day, D the accrual (ACT/365)
GRID_ROWS, GRID_DAY, GRID_ACCRUAL = (139, 178), 6, 4
#: the offshore curve's quotes on Forward: TRYI 1W … 9M (H label, G days, J mid %), TRYSAQ1 … 10 (C, K, E)
TRYI_ROWS, TRYI_LABEL, TRYI_DAY, TRYI_RATE = (8, 16), 8, 7, 10
XCCY_ROWS, XCCY_LABEL, XCCY_DAY, XCCY_RATE = (125, 134), 3, 11, 5
#: the OIS spot (OIS_MAIN!B2) and the FX spot the offshore curve counts from (Forward!I2: Bloomberg's SETTLE_DT text)
OIS_SPOT, FX_SPOT = ("OIS_MAIN", 2, 2), ("Forward", 2, 9)
#: MASA's broken-date block (KIRIK VADE & KARŞILIK, B170:N185): its rows whose market (column F) comes from a curve -
#: the forward outright and points, the simple ACT/360 and ACT/365 rates and the O/N equivalent off the offshore
#: discount factor at the date, OIS (onshore, 3M coupons ACT/365) and XCCY (offshore, yearly coupons ACT/360)
BROKEN_SHEET, BROKEN_FWD, BROKEN_POINTS, BROKEN_SIMPLE, BROKEN_SIMPLE365, BROKEN_ON, BROKEN_OIS, BROKEN_XCCY = (
    "MASA", 173, 174, 175, 176, 177, 178, 179)
#: its helper (BK170:CC234), column BL: S0 the FX spot (171), d the days to the date (173), xS = S0 − the OIS spot
#: (175), the spot rate (180), g = 1 + USD rate·d/360 (188); the OIS schedule BL192:BL233 (BM in use, BO τ ACT/365, BP
#: days from the OIS spot), the XCCY schedule BU192:BU203 (BV in use, BX τ ACT/360)
BL, BM, BO, BP, BU, BV, BX = 64, 65, 67, 68, 73, 74, 76
OIS_SCHEDULE, XCCY_SCHEDULE = (192, 233), (192, 203)


def _num(v: Any) -> Optional[float]:
    return float(v) if type(v) in (float, int) and v == v else None


def tenor_label(months: int) -> str:
    """1M … 11M, 1Y, 18M, 2Y … - as OIS_MAIN names its tenors."""
    return "%dM" % months if months < 12 or months % 12 else "%dY" % (months // 12)


# ================================================================================================== curves
class LogLinear(object):
    """A curve known at nodes - days and ln DF - log-linear between them; before the first and after the last node the
    end segment goes on (BOOT: ``MIN(MATCH(t, BOOT_GUN, 1), 42)``; offshore: the last slope ``OFF_SL``)."""

    def __init__(self, days: Sequence[float], lndf: Sequence[float]):
        nodes: Dict[float, float] = {}
        for d, v in zip(days, lndf):
            d, v = _num(d), _num(v)
            if d is not None and v is not None:
                nodes[d] = v
        if len(nodes) < 2:
            raise ValueError("eğride en az iki düğüm gerekli")
        self.days = sorted(nodes)
        self.lndf = [nodes[d] for d in self.days]

    def ln(self, t: float) -> float:
        """ln DF at day ``t``."""
        d, v = self.days, self.lndf
        i = min(max(bisect.bisect_right(d, t) - 1, 0), len(d) - 2)
        return v[i] + (v[i + 1] - v[i]) * (t - d[i]) / (d[i + 1] - d[i])

    def df(self, t: float) -> float:
        return math.exp(self.ln(t))


class StepCurve(object):
    """Discount factors from an overnight rate flat between knots, compounded as Motor compounds TLREF: over a stretch
    [a, b) at the rate r the growth factor's log rises by (b − a)·ln(1 + r/365) − (P(b) − P(a))·(r/365)², P the
    calendar's cumulative weekend / holiday term (Motor!F528:F4228: Σ g(g − 1)/2 over the gaps between business days,
    read at MIN(t, its last day) as the sheet reads it).

    ``knots``, ``rates``: the days the rate steps (the meetings' effective days; the spot, 0, first) and the rate from
    each on - a day listed twice takes its last rate, a rate before the first knot the first one; ``pcum``: P by day
    (none: every day compounds alone); ``shifts``: ``[(end, add)]``, ``add`` on top of the rate from the previous
    ``end`` (the first: the spot) up to ``end``, the last ``add`` beyond the last ``end``."""

    def __init__(self, knots: Sequence[float], rates: Sequence[float], pcum: Optional[Sequence[float]] = None,
                 shifts: Sequence[Tuple[float, float]] = ()):
        path: Dict[float, float] = {}
        for k, r in zip(knots, rates):
            k, r = _num(k), _num(r)
            if k is not None and r is not None:
                path[k] = r
        if not path:
            raise ValueError("TLREF patikası boş")
        days = sorted(path)
        if days[0] > 0.0:
            path[0.0] = path[days[0]]
            days.insert(0, 0.0)
        self.knots = days
        self.rates = [path[d] for d in days]
        self.pcum = [float(x) for x in pcum] if pcum else None
        self._build(shifts)

    def _build(self, shifts: Sequence[Tuple[float, float]], upto: Optional[float] = None) -> None:
        # the days the overnight rate changes (a meeting, a shift's end), the rate from each and ln G at each; ``upto``:
        # none after that day (a curve read no further - a quote's while it is solved)
        self.shifts = [(float(e), float(a)) for e, a in shifts]
        bp = sorted(set([d for d in self.knots if d >= 0.0] + [e for e, _ in self.shifts if e > 0.0] + [0.0]))
        if upto is not None:
            bp = [b for b in bp if b <= upto] or [0.0]
        self._bp = bp
        self._rate = [self._path_rate(b) + self._add(b) for b in bp]
        cum = [0.0]
        for i in range(len(bp) - 1):
            cum.append(cum[-1] + self._piece(bp[i], bp[i + 1], self._rate[i]))
        self._cum = cum

    # ---------------------------------------------------------------------------------------------- pieces
    def _p(self, t: float) -> float:
        p = self.pcum
        return p[min(max(int(t), 0), len(p) - 1)] if p else 0.0

    def _piece(self, a: float, b: float, r: float) -> float:
        x = r / BASIS
        return (b - a) * math.log(1.0 + x) - (self._p(b) - self._p(a)) * x * x

    def _path_rate(self, t: float) -> float:
        return self.rates[max(bisect.bisect_right(self.knots, t) - 1, 0)]

    def _add(self, t: float) -> float:
        for end, add in self.shifts:
            if t < end:
                return add
        return self.shifts[-1][1] if self.shifts else 0.0

    # ---------------------------------------------------------------------------------------------- reading
    def lng(self, t: float) -> float:
        """ln G at day ``t`` (G = 1 / DF: what 1 grows to by then)."""
        i = max(bisect.bisect_right(self._bp, t) - 1, 0)
        return self._cum[i] + self._piece(self._bp[i], t, self._rate[i])

    def df(self, t: float) -> float:
        return math.exp(-self.lng(t))

    def overnight(self, t: float) -> float:
        """The overnight rate of day ``t`` (the one from ``t`` to the next day), shift included."""
        return self._rate[max(bisect.bisect_right(self._bp, t) - 1, 0)]

    def steps(self) -> List[Tuple[float, float]]:
        """Where the overnight rate changes and to what: [(day, rate)], the spot first."""
        return list(zip(self._bp, self._rate))

    # ---------------------------------------------------------------------------------------------- variants
    def with_shifts(self, shifts: Sequence[Tuple[float, float]], upto: Optional[float] = None) -> "StepCurve":
        """The same path with other shifts on top (``upto``: read no further than that day)."""
        out = object.__new__(StepCurve)
        out.knots, out.rates, out.pcum = self.knots, self.rates, self.pcum
        out._build(shifts, upto)
        return out

    def rebased(self, origin: float) -> "StepCurve":
        """The path (without its shifts) seen from day ``origin`` as its spot: another curve's spot (the FX spot of the
        offshore curve against the OIS spot).  Its calendar term is the one from ``origin`` on."""
        if origin == 0.0:
            return StepCurve(self.knots, self.rates, self.pcum)
        knots = [0.0] + [k - origin for k in self.knots if k > origin]
        rates = [self._path_rate(origin)] + [r for k, r in zip(self.knots, self.rates) if k > origin]
        pcum = None
        if self.pcum:
            base, last = self._p(origin), len(self.pcum) - 1
            pcum = [self._p(origin + t) - base for t in range(0, max(int(last - origin), 0) + 1)]
        return StepCurve(knots, rates, pcum)


# ================================================================================================== instruments
def par(curve, pays: Sequence[float], accruals: Sequence[float], start: float = 0.0) -> float:
    """The par rate of a swap on ``curve``: fixed paid on ``pays`` (the last its end) for ``accruals`` (year fractions)
    against the floating leg from ``start`` - (DF(start) − DF(end)) / Σ τ_k·DF(pay_k).  One period is the simple rate
    over it (a zero-coupon OIS, an FX swap implied rate: (DF(start)/DF(end) − 1)/τ); a later ``start`` makes a
    forward-starting swap, an FRA."""
    annuity = 0.0
    for t, a in zip(pays, accruals):
        annuity += a * curve.df(t)
    return (curve.df(start) - curve.df(pays[-1])) / annuity


def forward(curve, start: float, end: float, basis: float = BASIS) -> float:
    """The simple rate between two days, ``basis`` days a year: (DF(start)/DF(end) − 1)·basis/days."""
    return (curve.df(start) / curve.df(end) - 1.0) * basis / (end - start)


class Grid(NamedTuple):
    """A quarterly calendar from the spot: the k-th quarter's payment day and accrual (Motor!F139:F178 / D139:D178:
    3M … 120M, WORKDAY(EDATE(spot, 3k) − 1, 1), ACT/365) - the one OIS · PPK's FRA lists price on."""
    days: Tuple[float, ...]
    accruals: Tuple[float, ...]


def fra(curve, grid: Grid, m1: int, m2: int) -> Optional[float]:
    """An ``m1`` × ``m2`` months FRA on ``grid``: the swap from the grid's day at ``m1`` (the spot for 0) to its day at
    ``m2``, paying every quarter of the grid in between - what OIS_MAIN!B336 is on the bootstrap: (DF(M) − DF(N)) /
    Σ τ·DF over the quarters in (M, N].  ``None`` off the grid (months not a multiple of 3, beyond its end)."""
    if m1 < 0 or m2 <= m1 or m1 % 3 or m2 % 3 or m2 // 3 > len(grid.days):
        return None
    k1, k2 = m1 // 3, m2 // 3
    return par(curve, grid.days[k1:k2], grid.accruals[k1:k2], grid.days[k1 - 1] if k1 else 0.0)


# ================================================================================================== calibration
class Quote(NamedTuple):
    """A quote a curve is built from: its name, rate and the swap it prices - the pay days and accruals (one period:
    a zero-coupon OIS or an FX swap implied rate)."""
    name: str
    rate: float
    pays: Tuple[float, ...]
    accruals: Tuple[float, ...]

    @property
    def end(self) -> float:
        return self.pays[-1]


def calibrate(shape: StepCurve, quotes: Sequence[Quote]) -> Tuple[StepCurve, List[Dict[str, Any]]]:
    """``shape`` made to reprice ``quotes``: a flat overnight shift on each stretch between two successive quoted
    maturities (the first from the spot; after the last one its shift goes on), solved maturity by maturity - a quote
    depends only on its own stretch and the ones before it, solved already - by the secant method until it comes back
    within :data:`TOLERANCE`.  The overnight rate stays flat between the meetings inside a stretch and steps at its ends.

    Returns the curve and, per quote in maturity order: ``name``, ``end`` (days), ``quote``, ``shape`` (the shape's own
    par - MPC ima's), ``miss_bp`` (shape − quote: what the shape misses by), ``shift_bp`` (the stretch's overnight shift)
    and ``after_bp`` (the curve's par − quote).  A quote that cannot be solved raises ``ValueError``."""
    qs = sorted(quotes, key=lambda q: q.end)
    shifts: List[Tuple[float, float]] = []
    last, guess = 0.0, 0.0
    for q in qs:
        if q.end <= last:
            raise ValueError("kotaların vadesi artmalı: %s" % q.name)

        def miss(add: float, q: Quote = q) -> float:
            return par(shape.with_shifts(shifts + [(q.end, add)], q.end), q.pays, q.accruals) - q.rate

        a0, a1 = guess, guess + 1e-4
        f0, f1 = miss(a0), miss(a1)
        for _ in range(STEPS):
            if abs(f1) <= TOLERANCE * 1e-3 or f1 == f0:
                break
            a0, a1 = a1, a1 - f1 * (a1 - a0) / (f1 - f0)
            f0, f1 = f1, miss(a1)
        if not abs(f1) <= TOLERANCE:
            raise ValueError("%s kotasına oturulamadı" % q.name)
        shifts.append((q.end, a1))
        last, guess = q.end, a1
    curve = shape.with_shifts(shifts)
    report = []
    for q, (_, add) in zip(qs, shifts):
        own = par(shape, q.pays, q.accruals)
        report.append({"name": q.name, "end": q.end, "quote": q.rate, "shape": own, "miss_bp": (own - q.rate) * 1e4,
                       "shift_bp": add * 1e4, "after_bp": (par(curve, q.pays, q.accruals) - q.rate) * 1e4})
    return curve, report


def ois_quotes(months: Sequence[Any], rates: Sequence[Any], node_months: Sequence[Any],
               node_days: Sequence[Any]) -> List[Quote]:
    """The OIS quotes the bootstrap is built from (Motor!A306:B321: months, rate) as the swaps they are, on the
    bootstrap's own days (Motor!E88:E130 / C88:C130): up to 3M one period, simple ACT/365; from 6M quarterly ACT/365 par
    on the 3-month nodes (the first quarter from the spot).  A tenor without a rate or a node is left out."""
    day = {}
    for m, d in zip(node_months, node_days):
        m, d = _num(m), _num(d)
        if m is not None and d is not None:
            day[int(round(m))] = d
    out = []
    for m, r in zip(months, rates):
        m, r = _num(m), _num(r)
        if m is None or r is None:
            continue
        m = int(round(m))
        if m <= 3 and m in day:
            out.append(Quote(tenor_label(m), r, (day[m],), (day[m] / BASIS,)))
        elif m > 3 and m % 3 == 0 and all(k in day for k in range(3, m + 1, 3)):
            pays = tuple(day[k] for k in range(3, m + 1, 3))
            out.append(Quote(tenor_label(m), r, pays, tuple((b - a) / BASIS for a, b in zip((0.0,) + pays[:-1], pays))))
    return out


def offshore_quotes(tryi: Sequence[Tuple[Any, Any, Any]], xccy: Sequence[Tuple[Any, Any, Any]]) -> List[Quote]:
    """The offshore TRY quotes as the offshore curve reads them (Forward!AJ123:AN143), each ``(label, days, mid %)``:
    TRYI - FX swap implied - one period, simple ACT/360; TRYSAQ n - n years' cross currency swap - annual ACT/360 par
    paying on the days of TRYSAQ 1 … n, up to the first one missing (the sheet's bootstrap stops there too)."""
    out = []
    for label, d, r in tryi:
        d, r = _num(d), _num(r)
        if d is not None and r is not None and d > 0:
            out.append(Quote("TRYI %s" % label, r / 100.0, (d,), (d / 360.0,)))
    pays: List[float] = []
    for label, d, r in xccy:
        d, r = _num(d), _num(r)
        if d is None or r is None or (pays and d <= pays[-1]):
            break
        pays.append(d)
        out.append(Quote("XCCY %s" % label, r / 100.0, tuple(pays),
                         tuple((b - a) / 360.0 for a, b in zip([0.0] + pays[:-1], pays))))
    return out


# ================================================================================================== the workbook
def read(get: Callable[[str, int, int], Any]) -> Dict[str, Any]:
    """Both ways from the TRY workbook, ``get(sheet, row, column)`` reading its cells (a user's calculation: their own
    inputs count).  Keys, each ``None`` where the workbook gives too little (``errors`` says why):

    * ``boot`` - the bootstrap (:class:`LogLinear` on Motor's nodes), as the sheet has it;
    * ``shape`` - MPC ima (:class:`StepCurve`: Motor's meeting table and calendar term);
    * ``quotes``, ``ppk``, ``report`` - the OIS quotes, the PPK step curve calibrated to them and :func:`calibrate`'s
      report;
    * ``grid`` - Motor's quarterly calendar (:class:`Grid`);
    * ``fx_shift`` - the FX spot − the OIS spot (days); ``off_quotes``, ``off_ppk``, ``off_report`` - the offshore
      quotes and the shape seen from the FX spot with a flat basis between them, calibrated the same way."""
    def col(sheet: str, rows: Tuple[int, int], c: int) -> List[Any]:
        return [get(sheet, r, c) for r in range(rows[0], rows[1] + 1)]

    out: Dict[str, Any] = {k: None for k in ("boot", "shape", "quotes", "ppk", "report", "grid", "fx_shift",
                                              "off_quotes", "off_ppk", "off_report")}
    errors: List[str] = []
    out["errors"] = errors
    try:
        out["boot"] = LogLinear(col("Motor", BOOT_ROWS, BOOT_DAY), col("Motor", BOOT_ROWS, BOOT_LNDF))
    except ValueError as exc:
        errors.append("bootstrap: %s" % exc)
    days, acc = col("Motor", GRID_ROWS, GRID_DAY), col("Motor", GRID_ROWS, GRID_ACCRUAL)
    if all(_num(x) is not None for x in days + acc):
        out["grid"] = Grid(tuple(float(x) for x in days), tuple(float(x) for x in acc))
    else:
        errors.append("çeyreklik takvim eksik (Motor!D139:F178)")
    try:
        pcum = [_num(x) for x in col("Motor", PCUM_ROWS, PCUM_COL)]
        pcum = pcum[:pcum.index(None)] if None in pcum else pcum
        shape = StepCurve(col("Motor", PATH_ROWS, PATH_DAY), col("Motor", PATH_ROWS, PATH_RATE), pcum)
        out["shape"] = shape
    except ValueError as exc:
        errors.append("MPC ima: %s" % exc)
        return out
    quotes = ois_quotes(col("Motor", QUOTE_ROWS, QUOTE_MONTH), col("Motor", QUOTE_ROWS, QUOTE_RATE),
                        col("Motor", BOOT_ROWS, BOOT_MONTH), col("Motor", BOOT_ROWS, BOOT_DAY))
    out["quotes"] = quotes
    try:
        out["ppk"], out["report"] = calibrate(shape, quotes) if quotes else (None, None)
    except ValueError as exc:
        errors.append("PPK basamak: %s" % exc)
    ois_spot, fx_spot = _num(to_num(get(*OIS_SPOT))), _num(to_num(get(*FX_SPOT)))
    if ois_spot is None or fx_spot is None:
        errors.append("spot tarihi yok (OIS_MAIN!B2 / Forward!I2)")
        return out
    out["fx_shift"] = fx_spot - ois_spot
    tryi = [(get("Forward", r, TRYI_LABEL), get("Forward", r, TRYI_DAY), get("Forward", r, TRYI_RATE))
            for r in range(TRYI_ROWS[0], TRYI_ROWS[1] + 1)]
    xccy = [(get("Forward", r, XCCY_LABEL), get("Forward", r, XCCY_DAY), get("Forward", r, XCCY_RATE))
            for r in range(XCCY_ROWS[0], XCCY_ROWS[1] + 1)]
    off = offshore_quotes(tryi, xccy)
    out["off_quotes"] = off
    try:
        out["off_ppk"], out["off_report"] = calibrate(shape.rebased(out["fx_shift"]), off) if off else (None, None)
    except ValueError as exc:
        errors.append("offshore PPK basamak: %s" % exc)
    return out


def broken(get: Callable[[str, int, int], Any], ois, off) -> Dict[int, float]:
    """MASA's broken-date block's market (its column F) on other curves, by row: the forward, simple and O/N rows and
    XCCY on ``off`` (an offshore curve: days from the FX spot), OIS on ``ois`` (days from the OIS spot) - with the
    block's own date, spot, USD factor, coupon schedules and day counts, read from its helper through ``get`` as for
    :func:`read`, so a difference to the block's market is the curve's alone.  On the curves the block reads itself
    (BOOT, the offshore curve) it is the block's market.  A row without its inputs (no date, a curve not given) is left
    out."""
    def at(r: int, c: int) -> Optional[float]:
        return _num(get(BROKEN_SHEET, r, c))

    def schedule(rows: Tuple[int, int], on: int, pay: int, tau: int, origin: float) -> Tuple[List[float], List[float]]:
        legs = sorted((at(r, pay) - origin, at(r, tau)) for r in range(rows[0], rows[1] + 1)
                      if at(r, on) == 1.0 and at(r, pay) is not None and at(r, tau) is not None)
        return [p for p, _ in legs], [a for _, a in legs]

    out: Dict[int, float] = {}
    s0, d = at(171, BL), at(173, BL)
    if d is None or d <= 0 or s0 is None:
        return out
    if off is not None:
        dfx = off.df(d)
        spot, g = at(180, BL), at(188, BL)
        if spot is not None and g:
            out[BROKEN_FWD] = spot / (dfx * g)
            out[BROKEN_POINTS] = (spot / (dfx * g) - spot) * 10000.0
        out[BROKEN_SIMPLE] = (1.0 / dfx - 1.0) * 360.0 / d
        out[BROKEN_SIMPLE365] = (1.0 / dfx - 1.0) * 365.0 / d
        out[BROKEN_ON] = 360.0 * ((1.0 / dfx) ** (1.0 / d) - 1.0)
        pays, acc = schedule(XCCY_SCHEDULE, BV, BU, BX, s0)
        if pays:
            out[BROKEN_XCCY] = par(off, pays, acc)
    xs = at(175, BL)
    if ois is not None and xs is not None:
        pays, acc = schedule(OIS_SCHEDULE, BM, BP, BO, 0.0)
        if pays:
            out[BROKEN_OIS] = par(ois, pays, acc, max(0.0, xs))
    return out
