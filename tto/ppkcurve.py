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

**The desk's list of points** (Ayarlar → Eğri noktaları, tto/curvepoints.py): the quotes each curve is built from are the
desk's to choose - the workbook's own (the default list: every number as above), others typed or read from a Bloomberg
ticker, some switched off.  A curve whose list differs from the default is built on its points (:class:`Spec`,
:func:`list_curves`), both ways: Bootstrap the desk's own method - OIS as Motor builds it (the points' par rates linear in
months on its quarterly nodes, bootstrapped; a point off that grid an extra node), offshore a node at every point
(:func:`bootstrap`, ln DF linear in days, as the Forward sheet's curve) - and PPK basamak calibrated to the very points.
"""
from __future__ import annotations

import bisect
import calendar
import datetime as _dt
import math
from typing import Any, Callable, Dict, FrozenSet, List, NamedTuple, Optional, Sequence, Tuple

from .xl.values import date_to_serial, serial_to_date, to_num

#: the overnight rate's day basis (TLREF: ACT/365, compounded on business days)
BASIS = 365.0
#: a calibrated quote comes back within ``TOLERANCE`` (|par − quote|, a rate) after at most ``STEPS`` secant steps
TOLERANCE, STEPS = 1e-12, 60
#: :func:`window_overnight`'s steps - the sheet's formula takes as many (extras.overnight_bd)
ON_STEPS = 8

# where the TRY workbook keeps what both ways are built from (1-based rows / columns)
#: Motor's meeting table: C the effective day (days from the OIS spot), K the implied TLREF from it on (L: its ln G)
PATH_ROWS, PATH_DAY, PATH_RATE = (4, 84), 3, 11
#: Motor's daily calendar: F the cumulative weekend / holiday term Pcum (day 0 … 3700)
PCUM_ROWS, PCUM_COL = (528, 4228), 6
#: Motor's bootstrap: C its nodes' days, D their accruals, E their months, I ln DF (BOOT_GUN / BOOT_LNDF)
BOOT_ROWS, BOOT_DAY, BOOT_ACCRUAL, BOOT_MONTH, BOOT_LNDF = (88, 130), 3, 4, 5, 9
#: the copy of the OIS quotes the bootstrap and the PPK solver read: A months, B quote (OIS_MAIN B9:B26 without 15M, 21M)
QUOTE_ROWS, QUOTE_MONTH, QUOTE_RATE = (306, 321), 1, 2
#: Motor's quarterly calendar (3M … 120M) the FRA lists price on: F the payment day, D the accrual (ACT/365)
GRID_ROWS, GRID_DAY, GRID_ACCRUAL = (139, 178), 6, 4
#: the offshore curve's quotes on Forward: TRYI 1W … 9M (H label, G days, J mid %), TRYSAQ1 … 10 (C, K, E)
TRYI_ROWS, TRYI_LABEL, TRYI_DAY, TRYI_RATE = (8, 16), 8, 7, 10
XCCY_ROWS, XCCY_LABEL, XCCY_DAY, XCCY_RATE = (125, 134), 3, 11, 5
#: the OIS spot (OIS_MAIN!B2: a TRY business day after today) and the FX spot the offshore curve counts from (Forward!I2:
#: the USDTRY spot, a TRY + USD business day after today - extras.FX_SPOTS; Bloomberg's SETTLE_DT stands beside it in J2)
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


# ================================================================================================== TLREF over a window
# How TLREF compounds over a window of days - the MPC ima model's own (Motor!L, OIS_MAIN!BJ; :class:`StepCurve`), and so
# the PPK step a window's rate prices on OIS · PPK (EK_PPK) and in Broker Chat (the desk, 25.11.2026: "B"): on business
# days only, each business day's overnight rate accruing for the calendar days to the next business day (1; 3 over a
# weekend - Friday's rate for three days in one step -; more over a holiday), ACT/365.  Over ``days`` calendar days whose
# business days are g apart the growth is Π (1 + x·g), x = O/N / 365; the model takes its log to the second order in x:
#
#     ln G = days·ln(1 + x) − term·x²,    term = Σ g(g − 1)/2,
#
# ``term`` the window's weekend / holiday term - Motor's Pcum (its daily calendar on the TRY holiday list, F528:F4228;
# J at a meeting's effective day) at the window's end less at its start, days counted from the OIS spot.  A window's
# simple ACT/365 rate R is 1 + R·days/365 = G.  With no weekend or holiday in the window (term 0) it is every day
# compounded alone.
def growth(on: float, days: float, term: float) -> float:
    """ln G of a window of ``days`` calendar days at the overnight rate ``on`` (decimal, ACT/365) compounded on business
    days, ``term`` its weekend / holiday term."""
    x = on / BASIS
    return days * math.log(1.0 + x) - term * x * x


def window_rate(on: float, days: float, term: float, extra: float = 0.0) -> float:
    """The simple ACT/365 rate of a window at the overnight rate ``on``: (G − 1)·365 / days - the model's window rate
    (OIS_MAIN!BJ's formula on Motor's TLREF).  ``extra``: what TLREF's normalization stretch adds to the window's ln G
    (:meth:`Norm.stretch`: the rate is then the actual window's, ``on`` the normal path's; 0 - off - adds an exact 0)."""
    return (math.exp(growth(on, days, term) + extra) - 1.0) * BASIS / days


def window_overnight(rate: float, days: float, term: float, extra: float = 0.0) -> float:
    """The overnight rate that, compounded on business days over the window, gives its simple ACT/365 rate ``rate`` -
    :func:`window_rate`'s inverse: ln(1 + x) = (ln(1 + R·days/365) + term·x²) / days, solved in ``ON_STEPS`` steps from
    the rate compounded every day (term 0; each step a few hundred times closer at TRY's rates, so the last ones leave
    nothing - the sheet's formula takes the same steps).  ``extra``: the normalization stretch's part of the window's ln
    G, taken off first (the rate's O/N on the normal path; 0 - off - takes an exact 0 off).  ValueError without a window
    or below −365/days."""
    if not days > 0:
        raise ValueError("dönem yok")
    lr = math.log(1.0 + rate * days / BASIS) - extra
    x = math.exp(lr / days) - 1.0
    for _ in range(ON_STEPS - 1):
        x = math.exp((lr + term * (x * x)) / days) - 1.0
    return BASIS * x


# ================================================================================================== TLREF's normalization
# The desk, 26.11.2026 (docs/desk-decisions.md, "TLREF normalleşmesi"): TCMB paused its one-week repo auctions, so TLREF
# sits a few hundred bp over its normal level until a normalization date N - "Burada tlref'e geri gelecek gibi hesap
# yapacagiz".  The switch is on OIS · PPK (OIS_MAIN!K2:L5, each user's own); everybody reads it from four cells
# (OIS_MAIN!M2:M5): ON (1: on, with a date and a normal TLREF in use; else 0), n (days from the OIS spot to N), REF (the
# normal TLREF L0 when on, today's TLREF otherwise) and gap · ON (H − L0, H today's TLREF OIS_MAIN!J2).  While it is on,
# TLREF is the normal path + the gap before N; the PPK model solves the normal path, and the stretch adds to ln G from the
# OIS spot to a day t, m = min(t, n), as the model compounds TLREF (Pcum: Motor's daily calendar term):
#
#     E(m) = m·[ln(1 + H/365) − ln(1 + L0/365)] − Pcum(m)·[(H/365)² − (L0/365)²].
#
# A window's rate is taken to the normal path by taking its stretch part E(min(end, n)) − E(min(start, n)) off its ln G
# (:func:`window_overnight`'s ``extra``; EK_PPK's AG column the same, OIS_MAIN!BJ adds it back: the model's actual rate).
#: the switch's cells (sheet, row, column): ON, n, REF, gap · ON - and H, today's TLREF
NORM_ON, NORM_DAYS, NORM_REF, NORM_GAP = ("OIS_MAIN", 2, 13), ("OIS_MAIN", 3, 13), ("OIS_MAIN", 4, 13), ("OIS_MAIN", 5, 13)
TLREF_TODAY = ("OIS_MAIN", 2, 10)
#: Motor's daily calendar ends at day ``PCUM_LAST`` (its readers take MIN(t, 3700))
PCUM_LAST = PCUM_ROWS[1] - PCUM_ROWS[0]


class Norm(NamedTuple):
    """TLREF's normalization while the switch is on: ``days`` n (≥ 0), ``ref`` the normal TLREF L0, ``gap`` H − L0 (as
    the switch's cell has it), ``dl`` / ``dq`` - E's two factors, ln(1 + H/365) − ln(1 + L0/365) and (H/365)² −
    (L0/365)², in the sheet's order of operations (EK_PPK's helper cells), so the page and Broker Chat agree to the bit."""
    days: float
    ref: float
    gap: float
    dl: float
    dq: float

    def extra(self, t: float, pcum: Callable[[float], float]) -> float:
        """E(min(t, n)): what the stretch adds to ln G from the OIS spot to day ``t`` - ``pcum(m)`` Motor's Pcum at day
        m (its daily calendar, MIN(m, 3700))."""
        m = min(t, self.days)
        return m * self.dl - pcum(m) * self.dq

    def stretch(self, a: float, b: float, pcum: Callable[[float], float]) -> float:
        """The stretch's part of the window from day ``a`` to day ``b`` (days from the OIS spot): E at b − E at a."""
        return self.extra(b, pcum) - self.extra(a, pcum)


def norm(get: Callable[[str, int, int], Any]) -> Optional[Norm]:
    """The switch as a calculation has it (``get(sheet, row, column)``): ``None`` when off (ON not 1, or a value missing) -
    nothing then reads more than ON.  n below 0 (a date before the OIS spot) is 0: no stretch."""
    if _num(get(*NORM_ON)) != 1.0:
        return None
    n, ref, gap, h = (_num(get(*at)) for at in (NORM_DAYS, NORM_REF, NORM_GAP, TLREF_TODAY))
    if n is None or ref is None or gap is None or h is None or not (h > -365.0 and ref > -365.0):
        return None
    return Norm(max(n, 0.0), ref, gap, math.log(1 + h / 365) - math.log(1 + ref / 365), (h / 365) ** 2 - (ref / 365) ** 2)


class StepCurve(object):
    """Discount factors from an overnight rate flat between knots, compounded as Motor compounds TLREF (:func:`growth`):
    over a stretch [a, b) at the rate r the growth factor's log rises by (b − a)·ln(1 + r/365) − (P(b) − P(a))·(r/365)², P
    the calendar's cumulative weekend / holiday term (Motor!F528:F4228: Σ g(g − 1)/2 over the gaps between business days,
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
        return growth(r, b - a, self._p(b) - self._p(a))

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

    def with_stretch(self, end: float, add: float) -> "StepCurve":
        """The path (without its shifts) with ``add`` on top of it before day ``end`` - a knot there: TLREF while its
        normalization is on, the model's normal path + the gap up to the normalization date (``end`` = n).  A meeting
        inside the stretch moves both (the gap rides on the path)."""
        knots = sorted(set(self.knots) | {float(end)})
        return StepCurve(knots, [self._path_rate(k) + (add if k < end else 0.0) for k in knots], self.pcum)

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


# ================================================================================================== the desk's list of points
#: what a point of the desk's list is (Ayarlar → Eğri noktaları, tto/curvepoints.py), each by its own convention: an OIS
#: (up to Motor's 3M node one period simple ACT/365, then quarterly ACT/365 par - Motor's grid for its tenors, else
#: counted back from the maturity as MASA's broken-date block does), an FX swap implied rate (one period, simple
#: ACT/360) or a cross currency swap (annual ACT/360 par, its coupons counted back from the maturity: the short period
#: first - "18 ayda 6 ay + 12 ay, sondan başlayıp")
OIS_KIND, FX_KIND, XCCY_KIND = "ois", "fx", "xccy"
#: where its rate comes from: the workbook's own quote (the default points), typed by the desk, a Bloomberg ticker (a
#: percent, EK_INTERP's slot), or none - computed: where the curve is read, never a point it is built on
BOOK, TYPED, TICKER, COMPUTED = "book", "typed", "ticker", "calc"
#: the holiday lists a point's dates roll on - (sheet, rows, columns): the TRY list (Motor: OIS) and the FX value dates'
#: (EK_TATIL B:C, USD and the TRY copy: offshore)
OIS_HOLIDAYS, FX_HOLIDAYS = ("Motor", (361, 523), (1, 1)), ("EK_TATIL", (5, 264), (2, 3))
#: a point is solved until its par comes back within this (a rate), in at most ``STEPS`` secant steps
NODE_TOLERANCE = 1e-14


class Spec(NamedTuple):
    """A point of the desk's list as a curve is built from it (tto/curvepoints.py makes it out of the list's row):
    ``kind`` (``OIS_KIND`` / ``FX_KIND`` / ``XCCY_KIND``), ``source`` (``BOOK`` / ``TYPED`` / ``TICKER`` / ``COMPUTED``),
    its maturity - a tenor, ``months`` or ``weeks``, or a ``date`` (an Excel serial) -, ``row`` the workbook's own quote's
    row (OIS: Motor's quote copy, A306:B321; offshore: the Forward sheet's TRYI row 8 … 16 or TRYSAQ row 125 … 134), ``rate``
    a typed rate (decimal), ``cell`` a ticker's value ((sheet, row, column): a percent)."""
    id: str
    name: str
    kind: str
    source: str
    months: Optional[int] = None
    weeks: Optional[int] = None
    date: Optional[float] = None
    row: Optional[int] = None
    rate: Optional[float] = None
    cell: Optional[Tuple[str, int, int]] = None


class Resolved(NamedTuple):
    """A point read off the workbook: its maturity (``end``: days from the curve's spot; ``serial``: the date), its rate
    (decimal; None for a computed point or a quote without a price) and the swap it is - ``pays`` / ``accruals``; ``error``
    why it cannot be used ("": it can)."""
    spec: Spec
    end: Optional[float]
    serial: Optional[float]
    rate: Optional[float]
    pays: Tuple[float, ...]
    accruals: Tuple[float, ...]
    error: str = ""

    @property
    def quote(self) -> "Quote":
        return Quote(self.spec.name, self.rate if self.rate is not None else float("nan"), self.pays, self.accruals)


def edate(serial: float, months: int) -> float:
    """EDATE: the same day ``months`` later (the month's last day when it has fewer)."""
    d = serial_to_date(serial)
    year, month = divmod(d.year * 12 + d.month - 1 + int(months), 12)
    return date_to_serial(_dt.date(year, month + 1, min(d.day, calendar.monthrange(year, month + 1)[1])))


def following(serial: float, holidays: FrozenSet[float]) -> float:
    """The first business day on or after ``serial`` (``WORKDAY(serial − 1, 1, holidays)``: Monday to Friday, not a
    holiday)."""
    s = float(math.floor(serial))
    while serial_to_date(s).weekday() >= 5 or s in holidays:
        s += 1.0
    return s


def holidays(get: Callable[[str, int, int], Any], where: Tuple[str, Tuple[int, int], Tuple[int, int]]) -> FrozenSet[float]:
    """A holiday list of the workbook as serials (``where``: :data:`OIS_HOLIDAYS`, :data:`FX_HOLIDAYS`)."""
    sheet, (r1, r2), (c1, c2) = where
    out = set()
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = _num(to_num(get(sheet, r, c)))
            if v is not None and v > 0:
                out.add(float(math.floor(v)))
    return frozenset(out)


class Dates(object):
    """What a curve's points are dated with (``curve``: ``OIS_KIND`` or "off"): its spot (serial: OIS_MAIN!B2 /
    Forward!I2), the calendars - the TRY list (Motor's: OIS and XCCY dates, as MASA's broken-date block and Fiyatlama date
    them) and, offshore, the FX value dates' (EK_TATIL B:C, USD and TRY: an FX swap's) - and, OIS, Motor's node days by
    month; read once through ``get``.  The rules are Fiyatlama's (tto/pricing.py ``resolve`` / ``coupons``): a tenor is
    ``WORKDAY(EDATE(spot, months) − 1, 1, holidays)``, a week ``spot + 7·n`` rolled on, a date rolled on; a swap's k-th
    payment back is the tenor date of (months − k·step) - a date's ``EDATE(date, −k·step)`` rolled on -, after the
    spot: the short period first."""

    def __init__(self, get: Callable[[str, int, int], Any], curve: str):
        self.get, self.curve = get, curve
        self.spot = _num(to_num(get(*(OIS_SPOT if curve == OIS_KIND else FX_SPOT))))
        self.hol = holidays(get, OIS_HOLIDAYS)
        self.fx_hol = holidays(get, FX_HOLIDAYS) if curve != OIS_KIND else self.hol
        self.node: Dict[int, float] = {}
        if curve == OIS_KIND:
            for r in range(BOOT_ROWS[0], BOOT_ROWS[1] + 1):
                m, d = _num(get("Motor", r, BOOT_MONTH)), _num(get("Motor", r, BOOT_DAY))
                if m is not None and d is not None:
                    self.node[int(round(m))] = d

    def calendar(self, kind: str) -> FrozenSet[float]:
        return self.fx_hol if kind == FX_KIND else self.hol

    def day(self, serial: float) -> float:
        return serial - self.spot

    def on(self, spec: Spec, months: int) -> float:
        """The day of the tenor ``months`` from the spot (Motor's own node day on its grid)."""
        if self.curve == OIS_KIND and months in self.node:
            return self.node[months]
        return self.day(following(edate(self.spot, months), self.calendar(spec.kind)))

    def maturity(self, spec: Spec) -> Optional[float]:
        """The point's maturity: days from the spot to the business day it falls on."""
        hol = self.calendar(spec.kind)
        if spec.date is not None:
            return self.day(following(spec.date, hol))
        if spec.weeks is not None:
            return self.day(following(self.spot + 7.0 * spec.weeks, hol))
        if spec.months is not None:
            return self.on(spec, spec.months)
        return None

    def payments(self, spec: Spec, end: float, step: int) -> Tuple[float, ...]:
        """The pay days of a swap to ``end`` paying every ``step`` months, counted back from its maturity: the short
        period first (one payment for a tenor in weeks)."""
        pays = [end]
        hol = self.calendar(spec.kind)
        for k in range(1, 2000):
            if spec.months is not None:
                if spec.months - k * step <= 0:
                    break
                d = self.on(spec, spec.months - k * step)
            elif spec.date is not None:
                d = self.day(following(edate(spec.date, -k * step), hol))
            else:
                break
            if d <= 0.0:
                break
            if d < pays[0]:
                pays.insert(0, d)
        return tuple(pays)


def _accruals(pays: Sequence[float], basis: float) -> Tuple[float, ...]:
    return tuple((b - a) / basis for a, b in zip((0.0,) + tuple(pays[:-1]), pays))


def resolve(get: Callable[[str, int, int], Any], specs: Sequence[Spec], curve: str,
            where: Optional["Dates"] = None) -> List[Resolved]:
    """The points of a curve's list (``curve``: ``OIS_KIND`` or ``"off"``) read off the workbook: their maturities, rates
    and swaps, each by its convention.  A point that cannot be dated or has no price says so in ``error``."""
    w = where or Dates(get, OIS_KIND if curve == OIS_KIND else "off")
    out: List[Resolved] = []
    for sp in specs:
        out.append(_resolve(get, sp, w))
    return out


def _resolve(get: Callable[[str, int, int], Any], sp: Spec, w: Dates) -> Resolved:
    if w.spot is None:
        return Resolved(sp, None, None, None, (), (), "spot tarihi yok")
    rate: Optional[float] = None
    if sp.source == BOOK:
        return _resolve_book(get, sp, w)
    if sp.source == TYPED:
        rate = sp.rate
    elif sp.source == TICKER and sp.cell is not None:
        v = _num(get(*sp.cell))
        rate = v / 100.0 if v is not None else None
    end = w.maturity(sp)
    if end is None:
        return Resolved(sp, None, None, rate, (), (), "vade yok")
    if end <= 0.0:
        return Resolved(sp, end, w.spot + end, rate, (), (), "vade spot'tan sonra değil")
    if sp.kind == FX_KIND:
        pays: Tuple[float, ...] = (end,)
        acc = (end / 360.0,)
    elif sp.kind == XCCY_KIND:
        pays = w.payments(sp, end, 12)
        acc = _accruals(pays, 360.0)
    else:
        pays = w.payments(sp, end, 3)                        # (a tenor on Motor's grid: its quarterly node days)
        acc = _accruals(pays, BASIS)
    error = "" if rate is not None or sp.source == COMPUTED else "fiyat yok"
    return Resolved(sp, end, w.spot + end, rate, pays, acc, error)


def _resolve_book(get: Callable[[str, int, int], Any], sp: Spec, w: Dates) -> Resolved:
    """The workbook's own quote, read as :func:`ois_quotes` / :func:`offshore_quotes` read it: OIS on Motor's node days,
    TRYI / TRYSAQ on the Forward sheet's days (an XCCY's coupons on the days of the TRYSAQ rows before it)."""
    r = sp.row
    if sp.kind == OIS_KIND:
        m, rate = _num(get("Motor", r, QUOTE_MONTH)), _num(get("Motor", r, QUOTE_RATE))
        m = int(round(m)) if m is not None else None
        if m is None or m not in w.node or (m > 3 and not all(k in w.node for k in range(3, m + 1, 3))):
            return Resolved(sp, None, None, rate, (), (), "Motor'un düğümü yok")
        pays = (w.node[m],) if m <= 3 else tuple(w.node[k] for k in range(3, m + 1, 3))
        q = Resolved(sp, pays[-1], w.spot + pays[-1], rate, pays, _accruals(pays, BASIS))
    else:
        tryi = sp.kind == FX_KIND
        day = _num(get("Forward", r, TRYI_DAY if tryi else XCCY_DAY))
        rate = _num(get("Forward", r, TRYI_RATE if tryi else XCCY_RATE))
        rate = rate / 100.0 if rate is not None else None
        if day is None or day <= 0:
            return Resolved(sp, None, None, rate, (), (), "gün yok")
        if tryi:
            pays = (day,)
        else:
            before = [_num(get("Forward", k, XCCY_DAY)) for k in range(XCCY_ROWS[0], r)]
            pays = tuple([d for d in before if d is not None and 0.0 < d < day] + [day])
        q = Resolved(sp, day, w.spot + day, rate, pays, _accruals(pays, 360.0))
    return q._replace(error="" if rate is not None else "fiyat yok")


def _known(curve: Optional["LogLinear"], t: float) -> float:
    return curve.df(t) if curve is not None else (1.0 if t == 0.0 else float("nan"))


def bootstrap(quotes: Sequence["Quote"], days: Sequence[float] = (0.0,), lndf: Sequence[float] = (0.0,)) -> "LogLinear":
    """A curve with a node at every quote's maturity, ln DF linear in days between the nodes (the Forward sheet's offshore
    curve, AJ123:AN143), on top of the nodes given (the spot; Motor's grid): quote by quote in maturity order, each node's
    discount factor the one its swap is priced back at.  Coupons at known discount factors - on or before the node before
    it - give it in closed form (``(1 − r·Σ τ·DF) / (1 + r·τ_n)``: the sheet's own XCCY bootstrap); a coupon between that
    node and the maturity reads the new node, solved for by the secant method.  ``ValueError`` when one cannot be met."""
    nodes: Dict[float, float] = {float(d): float(v) for d, v in zip(days, lndf)}
    for q in sorted(quotes, key=lambda x: x.end):
        if q.end in nodes:
            raise ValueError("%s: bu günde zaten bir düğüm var" % q.name)
        nodes[q.end] = _node(nodes, q)
    ds = sorted(nodes)
    return LogLinear(ds, [nodes[d] for d in ds])


def _node(nodes: Dict[float, float], q: "Quote") -> float:
    """ln DF at ``q``'s maturity that prices its swap back on ``nodes`` plus that node."""
    if not (q.rate == q.rate):
        raise ValueError("%s: oran yok" % q.name)
    before = max((d for d in nodes if d < q.end), default=0.0)
    base = LogLinear(sorted(nodes), [nodes[d] for d in sorted(nodes)]) if len(nodes) >= 2 else None
    if all(p <= before for p in q.pays[:-1]):
        known = sum(a * _known(base, p) for p, a in zip(q.pays[:-1], q.accruals[:-1]))
        df = (1.0 - q.rate * known) / (1.0 + q.rate * q.accruals[-1])
        if not df > 0.0:
            raise ValueError("%s kotasına oturulamadı" % q.name)
        return math.log(df)

    def miss(x: float) -> float:
        c = LogLinear(list(nodes) + [q.end], list(nodes.values()) + [x])
        return par(c, q.pays, q.accruals) - q.rate

    x0 = base.ln(q.end) if base is not None else -q.rate * q.end / BASIS
    x1 = x0 - 1e-4
    f0, f1 = miss(x0), miss(x1)
    for _ in range(STEPS):
        if abs(f1) <= NODE_TOLERANCE or f1 == f0:
            break
        x0, x1 = x1, x1 - f1 * (x1 - x0) / (f1 - f0)
        f0, f1 = f1, miss(x1)
    if not abs(f1) <= TOLERANCE:
        raise ValueError("%s kotasına oturulamadı" % q.name)
    return x1


def motor_curve(months: Sequence[Any], days: Sequence[Any], accruals: Sequence[Any],
                points: Sequence[Tuple[float, float]]) -> Tuple[List[Optional[float]], List[float]]:
    """Motor's bootstrap (Motor!F88:I130) on other quotes: ``points`` ``(months, rate)``, the par rate at each of Motor's
    nodes (``months`` / ``days`` / ``accruals``: its E, C and D) linear in months between them, flat before the first and
    after the last (F); then G and H as the sheet has them - the 1M - 3M nodes one period ``1 / (1 + F·D)``, from 6M the
    quarterly chain ``(1 − F·H_prev) / (1 + F·D)`` from the 3M node's annuity.  Returns the pars (None at the spot) and ln
    DF at every node."""
    pts = sorted((float(m), float(r)) for m, r in points)
    if not pts:
        raise ValueError("eğride nokta yok")
    xs = [m for m, _ in pts]

    def par_at(m: float) -> float:
        if m <= xs[0]:
            return pts[0][1]
        if m >= xs[-1]:
            return pts[-1][1]
        i = bisect.bisect_right(xs, m) - 1
        (a0, b0), (a1, b1) = pts[i], pts[i + 1]
        return b0 + (b1 - b0) * (m - a0) / (a1 - a0)

    pars: List[Optional[float]] = [None]
    lndf = [0.0]
    annuity = 0.0
    for k in range(1, len(months)):
        m, d = float(months[k]), float(accruals[k])
        f = par_at(m)
        if k <= 3:
            g = 1.0 / (1.0 + f * d)
            annuity = d * g
        else:
            g = (1.0 - f * annuity) / (1.0 + f * d)
            annuity = annuity + d * g
        if not g > 0.0:
            raise ValueError("Motor'un %g aylık düğümü kurulamadı" % m)
        pars.append(f)
        lndf.append(math.log(g))
    return pars, lndf


class MotorNodes(NamedTuple):
    """Motor's bootstrap nodes (Motor!C88:E130, the spot first): their months (E), days from the OIS spot (C) and accruals
    (D) - what Motor's method builds the OIS list's Bootstrap on (:func:`list_ois_curve`)."""
    months: Tuple[float, ...]
    days: Tuple[float, ...]
    accruals: Tuple[float, ...]


def list_ois_curve(quotes: Sequence["Quote"], nodes: MotorNodes) -> Tuple[List[Optional[float]], "LogLinear"]:
    """The OIS list's Bootstrap from its points' swaps (``quotes``): Motor's method - each node's par the points' rates
    linear in months (a point's months: :func:`month_of` its maturity), Motor's own bootstrap (:func:`motor_curve`) - and
    a point off Motor's quarterly grid an extra node priced back by its own swap (:func:`bootstrap`).  The node pars
    (what Motor!F takes) and the curve.  The one builder of it: the list's cells and Fiyatlama's DV01 buckets (each point
    +1 bp, built again) both call it."""
    pars, ln = motor_curve(nodes.months, nodes.days, nodes.accruals,
                           [(month_of(q.end, nodes.months, nodes.days), q.rate) for q in quotes])
    on_grid = set(nodes.days)
    return pars, bootstrap([q for q in quotes if q.end not in on_grid], nodes.days, ln)


def month_of(day: float, node_months: Sequence[float], node_days: Sequence[float]) -> float:
    """A maturity's place in months on Motor's grid: a node's own months, between two nodes linear in days (beyond the
    last one its last stretch goes on) - where a point off the grid sits among the quotes interpolated in months."""
    i = min(max(bisect.bisect_right(node_days, day) - 1, 0), len(node_days) - 2)
    d0, d1 = node_days[i], node_days[i + 1]
    m0, m1 = node_months[i], node_months[i + 1]
    return m0 + (m1 - m0) * (day - d0) / (d1 - d0)


def list_curves(get: Callable[[str, int, int], Any], points: Dict[str, Optional[Sequence[Spec]]]) -> Dict[str, Any]:
    """The Bootstrap of the curves whose list differs from the default (``points``: ``{"ois": [Spec] | None, "off": …}``,
    the points a curve is built on; None: the workbook's own - nothing made here):

    * ``ois`` - Motor's method on the points (:func:`motor_curve`): their par rates linear in months on Motor's nodes
      (``pars``: what Motor!F takes, by its row), bootstrapped; a point off the quarterly grid (a date, 2Y1M) an extra
      node priced back by its own swap (``boot``: the curve with it, ln DF linear in days);
    * ``off`` - a node at every point (:func:`bootstrap`).

    Each with its ``quotes`` (the points with a price, as :class:`Quote`) and ``points`` (every point resolved: a point
    without a price is left out and says so - :attr:`Resolved.error`).  ``errors``: a curve that cannot be built."""
    out: Dict[str, Any] = {"ois": None, "off": None, "errors": []}
    errors: List[str] = out["errors"]
    specs = points.get(OIS_KIND)
    if specs is not None:
        rows = range(BOOT_ROWS[0], BOOT_ROWS[1] + 1)
        months = [_num(get("Motor", r, BOOT_MONTH)) for r in rows]
        days = [_num(get("Motor", r, BOOT_DAY)) for r in rows]
        acc = [_num(get("Motor", r, BOOT_ACCRUAL)) for r in rows]
        res = resolve(get, specs, OIS_KIND)
        usable = [p for p in res if not p.error and p.rate is not None]
        if None in months or None in days or None in acc[1:] or not usable:
            errors.append("OIS listesinin eğrisi kurulamadı (%s)" % ("nokta yok" if not usable else "Motor'un düğümleri eksik"))
        else:
            try:
                nodes = MotorNodes(tuple(float(m) for m in months), tuple(float(d) for d in days),
                                   tuple(float(a) if a is not None else 0.0 for a in acc))
                quotes = [p.quote for p in sorted(usable, key=lambda x: x.end)]
                pars, boot = list_ois_curve(quotes, nodes)
                out[OIS_KIND] = {"quotes": quotes, "points": res, "boot": boot, "pars": dict(zip(rows, pars)),
                                 "nodes": nodes}
            except ValueError as exc:
                errors.append("OIS listesi: %s" % exc)
    specs = points.get("off")
    if specs is not None:
        res = resolve(get, specs, "off")
        usable = [p for p in res if not p.error and p.rate is not None]
        try:
            quotes = [p.quote for p in sorted(usable, key=lambda x: x.end)]
            if not quotes:
                raise ValueError("nokta yok")
            out["off"] = {"quotes": quotes, "points": res, "boot": bootstrap(quotes)}
        except ValueError as exc:
            errors.append("offshore listesi: %s" % exc)
    return out


# ================================================================================================== the workbook
def read(get: Callable[[str, int, int], Any], points: Optional[Dict[str, Optional[Sequence[Spec]]]] = None) -> Dict[str, Any]:
    """Both ways from the TRY workbook, ``get(sheet, row, column)`` reading its cells (a user's calculation: their own
    inputs count).  Keys, each ``None`` where the workbook gives too little (``errors`` says why):

    * ``boot`` - the bootstrap (:class:`LogLinear` on Motor's nodes), as the sheet has it;
    * ``shape`` - MPC ima (:class:`StepCurve`: Motor's meeting table and calendar term); with TLREF's normalization on
      (``norm``: :func:`norm`, the user's switch - ``None`` off) the model's normal path + the gap before the
      normalization date (:meth:`StepCurve.with_stretch`), what both PPK curves are calibrated from;
    * ``quotes``, ``ppk``, ``report`` - the OIS quotes, the PPK step curve calibrated to them and :func:`calibrate`'s
      report;
    * ``grid`` - Motor's quarterly calendar (:class:`Grid`);
    * ``fx_shift`` - the FX spot − the OIS spot (days); ``off_quotes``, ``off_ppk``, ``off_report`` - the offshore
      quotes and the shape seen from the FX spot with a flat basis between them, calibrated the same way.

    ``points`` - the desk's list (tto/curvepoints.py): ``{"ois": [Spec] | None, "off": …}``, the points of a curve whose
    list differs from the default (None, or no ``points``: the workbook's own, read as above).  Such a curve is built on
    them (:func:`list_curves`): ``boot`` (OIS) and ``off_boot`` (offshore) their Bootstrap, ``quotes`` / ``off_quotes``
    the points, the PPK curves calibrated to those - and it says so: ``ois_nodes`` (:class:`MotorNodes`: the OIS list's
    Bootstrap is :func:`list_ois_curve` on them), ``off_listed`` (the offshore list's is :func:`bootstrap`)."""
    def col(sheet: str, rows: Tuple[int, int], c: int) -> List[Any]:
        return [get(sheet, r, c) for r in range(rows[0], rows[1] + 1)]

    out: Dict[str, Any] = {k: None for k in ("boot", "shape", "norm", "quotes", "ppk", "report", "grid", "fx_shift",
                                              "off_quotes", "off_ppk", "off_report")}
    errors: List[str] = []
    out["errors"] = errors
    points = points or {}
    ois_list, off_list = points.get(OIS_KIND), points.get("off")
    lc = list_curves(get, points) if (ois_list is not None or off_list is not None) else None
    if lc is not None:
        errors.extend(lc["errors"])
    if ois_list is None:
        try:
            out["boot"] = LogLinear(col("Motor", BOOT_ROWS, BOOT_DAY), col("Motor", BOOT_ROWS, BOOT_LNDF))
        except ValueError as exc:
            errors.append("bootstrap: %s" % exc)
    elif lc[OIS_KIND] is not None:
        out["boot"] = lc[OIS_KIND]["boot"]
        out["ois_nodes"] = lc[OIS_KIND]["nodes"]
    days, acc = col("Motor", GRID_ROWS, GRID_DAY), col("Motor", GRID_ROWS, GRID_ACCRUAL)
    if all(_num(x) is not None for x in days + acc):
        out["grid"] = Grid(tuple(float(x) for x in days), tuple(float(x) for x in acc))
    else:
        errors.append("çeyreklik takvim eksik (Motor!D139:F178)")
    try:
        pcum = [_num(x) for x in col("Motor", PCUM_ROWS, PCUM_COL)]
        pcum = pcum[:pcum.index(None)] if None in pcum else pcum
        shape = StepCurve(col("Motor", PATH_ROWS, PATH_DAY), col("Motor", PATH_ROWS, PATH_RATE), pcum)
        # TLREF's normalization on (the user's switch, OIS · PPK): Motor's path is the normal one - TLREF is it + the gap
        # up to the normalization date (a knot there).  Off, or no gap, or a date not after the spot: the path as it is.
        out["norm"] = nm = norm(get)
        if nm is not None and nm.gap != 0.0 and nm.days > 0.0:
            shape = shape.with_stretch(nm.days, nm.gap)
        out["shape"] = shape
    except ValueError as exc:
        errors.append("MPC ima: %s" % exc)
        return out
    if ois_list is None:
        quotes = ois_quotes(col("Motor", QUOTE_ROWS, QUOTE_MONTH), col("Motor", QUOTE_ROWS, QUOTE_RATE),
                            col("Motor", BOOT_ROWS, BOOT_MONTH), col("Motor", BOOT_ROWS, BOOT_DAY))
    else:
        quotes = list(lc[OIS_KIND]["quotes"]) if lc[OIS_KIND] is not None else []
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
    if off_list is None:
        tryi = [(get("Forward", r, TRYI_LABEL), get("Forward", r, TRYI_DAY), get("Forward", r, TRYI_RATE))
                for r in range(TRYI_ROWS[0], TRYI_ROWS[1] + 1)]
        xccy = [(get("Forward", r, XCCY_LABEL), get("Forward", r, XCCY_DAY), get("Forward", r, XCCY_RATE))
                for r in range(XCCY_ROWS[0], XCCY_ROWS[1] + 1)]
        off = offshore_quotes(tryi, xccy)
    else:
        off = list(lc["off"]["quotes"]) if lc["off"] is not None else []
        out["off_boot"] = lc["off"]["boot"] if lc["off"] is not None else None
        out["off_listed"] = True
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
