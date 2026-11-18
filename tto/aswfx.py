"""DİBS ASW's second curve, the FX swap implied TRY curve ("ASW FX"): the offshore TRY rates of EK_FX, each read by its
own convention, handed to the ASW sheet as the par quotes of the sheet's own convention that give the same discount
factor at their tenor.  The sheet's formulas stay as they are: ``Service._asw_fx_calc`` puts these quotes in the place
of the OIS quotes its curve is built from (``ASW!C65:R65``).

**The sheet's curve** (row 65, today): the quotes of 16 tenors (``C65:R65``: 1M 2M 3M 6M 9M 1Y 18M 2Y 3Y … 10Y), the
days from the spot to 43 nodes - the spot, 1, 2, 3 months, then every quarter to 10 years (``AB65:BR65``, "D0" …
"D120": ``WORKDAY(EDATE(spot, m) − 1, 1, holidays) − spot``) -, the ln discount factor at each (``BS65:DI65``, "L0" …
"L120") and the quarterly annuity (``DJ65:EW65``, "H3" … "H120"):

* 1M–3M one period, simple ACT/365: ``L = −LN(1 + p/100 · d/365)``;
* from 6M a quarterly ACT/365 par bootstrap: ``L_n = LN((1 − p/100 · H_prev) / (1 + p/100 · (d_n − d_prev)/365))``,
  ``H3 = d3/365 · DF3``, ``H_n = H_prev + (d_n − d_prev)/365 · DF_n``; a quarter between two quoted tenors takes the
  quote interpolated linearly by months (L15: 1Y → 18M at 3/6; L27 … L33: 2Y → 3Y at 3/12 … 9/12; …).

A bond's discount factor is log-linear in ln DF between the node days.

**The FX rates' own conventions** - the desk's workbook reads the very same tickers so (its offshore TRY discount curve
behind DİBS RV's FX swap ASW, Forward!AJ123:AN142 and C123:K134):

* up to 9 months ``TRYI…``, FX swap implied: one period, simple ACT/360 - an FX swap has no coupons:
  ``DF = 1 / (1 + r/100 · d/360)``;
* from 1 year ``TRYSAQ…``, cross currency swaps (1Y ``TRYSAQ1``, the one year XCCY the desk's Forward sheet takes as
  its offshore 1Y - the desk, 18.11.2026; ``TRYI12M`` had no price on either source, 1Y stood on its OIS quote; with
  its one coupon the 1Y par gives the FX swap's discount factor above): an annual ACT/360 par rate,
  ``DF_n = (1 − r/100 · Σ τ_k DF_k) / (1 + r/100 · τ_n)`` over its coupon dates - yearly, counted back from the maturity,
  the short period first (:func:`xccy_months`; 12, 24, … months for a whole number of years): their discount factors the
  curve's as built so far (the sheet's own nodes, at or before the tenor quoted before), ``τ`` the days between / 360;
* **18M is no quote** (the desk, 18.11.2026: "TRYI18M gerçek bir kotasyon değil. Orada annual payment olduğu için 1Y'den
  sonra XCCY trade ediyor. Zero'yu oradan bulmamız gerekli ... 18M hesaplanacak, gerçek kotasyon girilmeyecek"): it is
  computed off the offshore curve (:func:`point_18m`) - its discount factor at the sheet's 18M node day between its 1Y
  and 2Y XCCY nodes (TRYSAQ1, TRYSAQ2), on the user's own curve setting (``Service._asw_fx_18m``: Bootstrap, the Forward
  sheet's curve, ln DF linear between its nodes; PPK basamak, ppkcurve's offshore PPK curve).  Its rate is the 18M XCCY
  par on that curve - annual ACT/360, coupons 6M and then 12M on, counted back from the maturity.

The kind goes by the tenor (≤ 9M FX swap implied, 18M computed, 1Y and ≥ 2Y XCCY), ``d`` is the sheet's node days of
the tenor.
A tenor without an FX price (18M: without the curve's 1Y and 2Y XCCY quotes) keeps its OIS quote as it is.

**To the sheet**, tenor by tenor in order: the discount factor the rate gives by its own convention is the target; up to
3M the sheet's quote with it is closed form (``p = (1/DF − 1) · 365/d``), from 6M on it is solved for - bisection on the
replica of the sheet's formulas (:func:`sheet_curve`), whose discount factor at the tenor falls as its quote rises.

**The history** ("ASW geçmişi", ``ASW!B66:Z325``: day by day, oldest first, each row the sheet's curve and the chosen
bonds' ASW on that day's OIS closes - ``C66:R325``, Bloomberg history blocks) on the offshore curve as well
(``Service._asw_hist_fx``): each past row's quotes swapped the same way for that day's offshore rates.  Those are the
dashboard's own daily closes (``tto/history.py``, nothing asked of Bloomberg for this), the series of each tenor by
:func:`history_series`: the FX swap implied yields of the Forward sheet's offshore rows (group ``off``: TRYI1M … TRYI9M)
at 1M–9M, its cross currency swaps (``xccy``) at 1Y–10Y (TRYSAQ1 … TRYSAQ10, as EK_FX) - each tenor in its kind's
group only (an FX swap implied 12M, were one kept, is not the 1Y); each the first source with a close (ICPL, then the
workbook's BGN ticker; ``SeriesDef.merged``).  18M is computed the same way from that day's TRYSAQ1 and TRYSAQ2 closes
(:func:`history_pair`; the offshore XCCY curve of the two, bootstrapped as the Forward sheet does and ln DF linear between
them - Bootstrap: a past day has no PPK curve), when both are there.  A day without a close of a tenor has none: there the
day's OIS quote stays, as a tenor without an FX price does today.  A day without any offshore close has no offshore ASW
(the page leaves its point and its cells empty), as today's ASW FX has none without an FX rate."""
from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .ppkcurve import LogLinear
from .xl.model import COLS

#: the tenors of the sheet's curve in months (ASW!C64:R64: 1M 2M 3M 6M 9M 1Y 18M 2Y … 10Y)
TENORS: Tuple[int, ...] = (1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120)
#: its nodes in months ("D0" … "D120", "L0" … "L120")
NODES: Tuple[int, ...] = (0, 1, 2, 3) + tuple(range(6, 121, 3))
#: today's row of the curve, the columns of the first quote (C), the first node's days (AB, "D0") and ln DF (BS, "L0")
ROW, QUOTE_COL, DAY_COL = 65, 3, 28
LN_COL = DAY_COL + len(NODES)
#: the longest tenor quoted as an FX swap implied yield (TRYI…); the longer ones are cross currency swaps (TRYSAQ…; 1Y
#: TRYSAQ1, as the desk's Forward sheet - the desk, 18.11.2026) - 18M aside: no quote at all, computed off the offshore
#: curve between its 1Y and 2Y XCCY nodes (:func:`point_18m`)
FX_SWAP_MAX = 9
#: the tenor computed off the offshore curve and the XCCY nodes it lies between (TRYSAQ1, TRYSAQ2)
CURVE_TENOR, CURVE_NODES = 18, (12, 24)
#: a tenor's kind: FX swap implied, cross currency swap, computed off the offshore XCCY curve, no FX price (the OIS quote
#: as it is)
FX_SWAP, XCCY, CURVE, OIS = "fx", "xccy", "curve", "ois"
#: how a kind of rate is read (the EK_FX table's words)
RULES = {FX_SWAP: "FX swap ima: tek dönem, basit ACT/360", XCCY: "XCCY: yıllık par, ACT/360",
         CURVE: "hesaplanan: XCCY 1Y–2Y eğrisinin 18A iskonto faktörü; par yıllık ACT/360, 6A + 12A (vadeden geriye)",
         OIS: "fiyat yok: OIS kotası, sayfanın kuralıyla"}
#: what the computed tenor's source is called (EK_FX; ``%s``: the curve - the user's setting)
CURVE_LABEL = "hesaplanan (XCCY 1Y–2Y, %s)"
#: an XCCY's day basis and its coupon period in months (the coupons counted back from the maturity, the short one first)
XCCY_BASIS, XCCY_PERIOD = 360.0, 12
#: the quotes a solve looks between (%) and how close its discount factor must come to the target
LOW, HIGH, TOLERANCE = -100.0, 1000.0, 1e-12
#: the history's rows (day by day, oldest first: ``B66:Z325``) and the column of their days
HIST_FIRST, HIST_LAST, HIST_DATE_COL = 66, 325, 2
#: the group of the dashboard's history a tenor's series is looked for in, by the tenor's kind (tto/history.py): the
#: Forward sheet's FX swap implied yields (TRYI…), its cross currency swaps (TRYSAQ…)
HIST_GROUP = {FX_SWAP: "off", XCCY: "xccy"}

_INDEX = {m: i for i, m in enumerate(NODES)}
_TENOR_SET = frozenset(TENORS)
#: a node between two tenors: the two (the quotes it is interpolated between)
_BRACKET = {m: (max(t for t in TENORS if t < m), min(t for t in TENORS if t > m)) for m in NODES
            if m not in _TENOR_SET and TENORS[0] < m < TENORS[-1]}


class Tenor(NamedTuple):
    """A tenor of the FX swap implied curve: ``kind`` (``FX_SWAP``, ``XCCY``, ``CURVE``, ``OIS``), the rate ``quote``d (the
    FX rate; the computed 18M XCCY par; the OIS quote without either), the discount factor ``df`` the FX rate gives at the
    tenor by its own convention (the curve's at 18M; None for ``OIS``) and the ``par`` quote the sheet is given - the rate
    of its own convention with that discount factor (the OIS quote for ``OIS``; None when there is none: a missing day or
    quote, a discount factor no quote reaches)."""
    months: int
    kind: str
    quote: Optional[float]
    df: Optional[float]
    par: Optional[float]


class Point(NamedTuple):
    """A tenor read off the offshore curve (:func:`point_18m`): the discount factor there, the XCCY par (%: annual
    ACT/360, the coupons counted back from the maturity) and the zero-coupon rate (%: compounded once a year, ACT/365 -
    EK_FX's column K)."""
    df: float
    par: float
    zero: float


def kind_of(months: int) -> str:
    """The kind of the FX rate of a tenor: an FX swap implied yield up to 9 months, 18M computed off the offshore XCCY
    curve, a cross currency swap from 1Y (TRYSAQ1, TRYSAQ2 …)."""
    if months == CURVE_TENOR:
        return CURVE
    return FX_SWAP if months <= FX_SWAP_MAX else XCCY


def node_of(months: int) -> int:
    """The node of a tenor (its index in ``NODES``: the column ``DAY_COL`` / ``LN_COL`` + it)."""
    return _INDEX[months]


def zero_rate(df: Any, days: Any) -> Optional[float]:
    """The zero-coupon rate (%) of a discount factor ``days`` from the spot, compounded once a year, ACT/365:
    ``DF^(−365/d) − 1``."""
    if not (_num(df) and _num(days)) or df <= 0 or days <= 0:
        return None
    return (math.exp(-math.log(df) * 365.0 / days) - 1.0) * 100.0


def _num(v: Any) -> bool:
    return type(v) is float and math.isfinite(v)


def _real(v: Any) -> bool:
    """A finite number (an int too - not a bool)."""
    return type(v) in (float, int) and math.isfinite(v)


def _quote_at(m: int, pars: Dict[int, Optional[float]]) -> Optional[float]:
    """The quote of the node ``m`` months out: a tenor's own, a quarter between two tenors the two interpolated linearly by
    months (as the sheet writes it: ``a + (b − a) * 3 / 12``)."""
    if m in _TENOR_SET:
        return pars.get(m)
    lo, hi = _BRACKET[m]
    a, b = pars.get(lo), pars.get(hi)
    if a is None or b is None:
        return None
    return a + (b - a) * (m - lo) / (hi - lo)


def _walk(pars: Dict[int, Optional[float]], days: Sequence[Optional[float]], ln: List[Optional[float]],
          h: List[Optional[float]], start: int, stop: int) -> None:
    """The sheet's formulas from node ``start`` to ``stop`` (indices of ``NODES``, both in), ``ln`` / ``h`` filled in
    place (the ln discount factor and the annuity of each node; None where a formula gives an error).  In the sheet's
    order of operations, to the last digit."""
    for i in range(start, stop + 1):
        m, d = NODES[i], days[i]
        p = _quote_at(m, pars)
        ln[i] = h[i] = None
        if m <= 3:
            if p is None or d is None:
                continue
            x = 1 + p / 100 * d / 365                                       # -LN(1+$C65/100*AC65/365)
            if x <= 0:
                continue
            ln[i] = -math.log(x)
            if m == 3:
                h[i] = d / 365 * math.exp(ln[i])                            # AE65/365*EXP(BV65)
            continue
        hp, dp = h[i - 1], days[i - 1]
        if p is None or d is None or hp is None or dp is None:
            continue
        den = 1 + p / 100 * (d - dp) / 365
        if den == 0:
            continue
        x = (1 - p / 100 * hp) / den                                       # LN((1-$F65/100*DJ65)/(1+$F65/100*(AF65-AE65)/365))
        if x <= 0:
            continue
        ln[i] = math.log(x)
        h[i] = hp + (d - dp) / 365 * math.exp(ln[i])                        # DJ65+(AF65-AE65)/365*EXP(BW65)


def sheet_curve(quotes: Sequence[Any], days: Sequence[Any]) -> List[Optional[float]]:
    """The sheet's ln discount factor at each of its nodes (``ASW!BS65:DI65``) from the quotes of its tenors (``C65:R65``,
    %) and the days to its nodes (``AB65:BR65``), worked out as its formulas work it out; None where one gives an error
    (a quote or a day missing, a log of a negative)."""
    pars = {m: _at(quotes, k) for k, m in enumerate(TENORS)}
    ln: List[Optional[float]] = [0.0] + [None] * (len(NODES) - 1)
    h: List[Optional[float]] = [None] * len(NODES)
    _walk(pars, [_at(days, i) for i in range(len(NODES))], ln, h, 1, len(NODES) - 1)
    return ln


def _at(values: Sequence[Any], k: int) -> Optional[float]:
    """The ``k``-th of a row of cells as a number (None: anything else, or none)."""
    return values[k] if k < len(values) and _num(values[k]) else None


def to_sheet(ois: Sequence[Any], fx: Sequence[Any], days: Sequence[Any],
             given: Optional[Dict[int, Optional[Point]]] = None) -> List[Tenor]:
    """The FX swap implied curve's tenors (``TENORS``) as the sheet is to be given them: ``ois`` the sheet's quotes
    (``C65:R65``), ``fx`` EK_FX's rates of the same tenors (``D6:D21``; anything but a number: no FX price), ``days``
    the days to the sheet's nodes (``AB65:BR65``), ``given`` the tenors computed off the offshore curve - 18M: its
    :class:`Point` (:func:`point_18m`; none: no price there, whatever ``fx`` says).  See the module's text for the
    conventions."""
    day = [_at(days, i) for i in range(len(NODES))]
    pars: Dict[int, Optional[float]] = {}
    ln: List[Optional[float]] = [0.0] + [None] * (len(NODES) - 1)
    h: List[Optional[float]] = [None] * len(NODES)
    out: List[Tenor] = []
    done = 0                                                    # the last node worked out (with the tenors so far)
    for k, m in enumerate(TENORS):
        i = node_of(m)
        kind = kind_of(m)
        point = (given or {}).get(m) if kind == CURVE else None
        rate = point.par if point is not None else (_at(fx, k) if kind != CURVE else None)
        if rate is None:
            q = _at(ois, k)
            pars[m] = q
            _walk(pars, day, ln, h, done + 1, i)
            done = i
            out.append(Tenor(m, OIS, q, None, q))
            continue
        target = point.df if point is not None else _target(kind, rate, m, day, ln)
        par = _solve(target, m, pars, day, ln, h, done) if target is not None else None
        pars[m] = par
        _walk(pars, day, ln, h, done + 1, i)
        done = i
        out.append(Tenor(m, kind, rate, target, par))
    return out


def _target(kind: str, rate: float, m: int, day: Sequence[Optional[float]], ln: Sequence[Optional[float]]) -> Optional[float]:
    """The discount factor at ``m`` months that ``rate`` gives by its own convention (``ln``: the curve so far)."""
    d = day[node_of(m)]
    if d is None or d <= 0:
        return None
    r = rate / 100
    if kind == FX_SWAP:
        x = 1 + r * d / 360
        return 1 / x if x > 0 else None
    pays = xccy_months(m)                                       # the coupons, counted back from the maturity
    dfs = []
    for y in pays[:-1]:
        j = node_of(y)
        if day[j] is None or ln[j] is None:
            return None
        dfs.append(math.exp(ln[j]))
    return xccy_df(r, [day[node_of(y)] for y in pays[:-1]] + [d], dfs)


def _solve(target: float, m: int, pars: Dict[int, Optional[float]], day: Sequence[Optional[float]],
           ln: List[Optional[float]], h: List[Optional[float]], done: int) -> Optional[float]:
    """The sheet's quote of the tenor ``m`` that gives the discount factor ``target`` there, the nodes up to ``done``
    worked out with the tenors before it.  (The nodes after ``done`` are left at the last quote tried: the caller works
    them out again with the one found.)"""
    i = node_of(m)
    d = day[i]
    if d is None:
        return None
    if m <= 3:
        return (1 / target - 1) * 365 / d * 100

    def miss(p: float) -> float:
        pars[m] = p
        _walk(pars, day, ln, h, done + 1, i)
        return math.exp(ln[i]) - target if ln[i] is not None else -math.inf    # (no value: a log failed - too high)

    lo, hi = LOW, HIGH
    for _ in range(200):
        mid = (lo + hi) / 2
        if mid in (lo, hi):
            break
        if miss(mid) > 0:
            lo = mid
        else:
            hi = mid
    best = min((lo, hi), key=lambda p: abs(miss(p)))
    return best if abs(miss(best)) <= TOLERANCE else None


# ---------------------------------------------------------------------------------------------- XCCY and the 18M point
def xccy_months(months: int) -> List[int]:
    """The coupon months of an XCCY to ``months``: annual, counted back from the maturity - the short period first (the
    desk, 18.11.2026: "18 ayda 6 ay + 12 ay olarak kupon ödemesi yapılıyor, sondan başlayıp"): 18M → 6, 18; 2Y → 12, 24;
    27M → 3, 15, 27."""
    return sorted(range(months, 0, -XCCY_PERIOD))


def xccy_df(rate: float, days: Sequence[float], dfs: Sequence[float]) -> Optional[float]:
    """The discount factor at the maturity of an XCCY at ``rate`` (a decimal: annual par, ACT/360) paying on ``days``
    (from the spot, the maturity last: :func:`xccy_months`), ``dfs`` the discount factors of the coupons before the
    maturity - ``(1 − r·Σ τ_k·DF_k) / (1 + r·τ_n)``, ``τ`` the days between / 360: the bootstrap's step, as the desk's
    Forward sheet takes it (Forward!G126).  None where it gives none (≤ 0)."""
    ann, last = 0.0, 0.0
    for d, df in zip(days[:-1], dfs):
        ann += (d - last) / XCCY_BASIS * df
        last = d
    x = 1 + rate * (days[-1] - last) / XCCY_BASIS
    if x == 0:
        return None
    df = (1 - rate * ann) / x
    return df if df > 0 else None


def xccy_par(days: Sequence[float], dfs: Sequence[float]) -> Optional[float]:
    """The par rate (a decimal) of an XCCY paying on ``days`` (from the spot, the maturity last) with the discount factors
    ``dfs`` there: ``(1 − DF_n) / Σ τ_k·DF_k``, ACT/360 - the rate :func:`xccy_df` gives the same ``DF_n`` back of."""
    ann, last = 0.0, 0.0
    for d, df in zip(days, dfs):
        ann += (d - last) / XCCY_BASIS * df
        last = d
    return (1 - dfs[-1]) / ann if ann > 0 else None


def point_18m(curve: Any, d6: Any, d18: Any, shift: Any = 0.0) -> Optional[Point]:
    """**The 18M point of the offshore curve** - computed, never a quote (the desk, 18.11.2026: "TRYI18M gerçek bir
    kotasyon değil ... Zero'yu oradan bulmamız gerekli"; "18M hesaplanacak, gerçek kotasyon girilmeyecek").  The one
    function behind every 18M a page shows: EK_FX's 18M row and the ASW FX curve (``Service._asw_fx_18m``, on the
    user's curve setting), the ASW history's past days (:func:`history_row`).

    ``curve``: the offshore TRY curve - anything with ``df(t)``, ``t`` days from its spot: the Forward sheet's
    (OFF_GUN / OFF_LNDF, ln DF linear between its nodes: :class:`tto.ppkcurve.LogLinear` - Bootstrap) or ppkcurve's
    offshore PPK curve (:class:`tto.ppkcurve.StepCurve` - PPK basamak); at 18M it lies between its 1Y and 2Y XCCY nodes
    (TRYSAQ1, TRYSAQ2), and an 18M node of its own would be read as it is.  ``d6``, ``d18``: the days from the spot to the
    point's coupon dates, counted back from the maturity (6M, then 12M on to 18M: :func:`xccy_months`); ``shift``: that
    spot's day on the curve (the ASW sheet's spot − the FX spot).  The discount factor from that spot to 18M, the 18M
    XCCY par on the curve with that schedule (ACT/360: :func:`xccy_par` - :func:`xccy_df` of it gives the discount factor
    back) and the zero rate (:func:`zero_rate`); None where the curve or the days give none."""
    if curve is None or not all(_real(x) for x in (d6, d18, shift)) or not 0 < d6 < d18:
        return None
    d6, d18, shift = float(d6), float(d18), float(shift)
    try:
        base = curve.df(shift)
        df6, df18 = curve.df(shift + d6) / base, curve.df(shift + d18) / base
    except (ArithmeticError, ValueError):
        return None
    if not (_real(df6) and _real(df18)) or df6 <= 0 or df18 <= 0:
        return None
    par = xccy_par([d6, d18], [float(df6), float(df18)])
    zero = zero_rate(float(df18), d18)
    if par is None or zero is None:
        return None
    return Point(df18, par * 100, zero)


def xccy_curve(quotes: Sequence[Tuple[Any, Any]]) -> Optional[LogLinear]:
    """The offshore XCCY curve made of ``quotes`` - ``(days from the spot, annual ACT/360 par %)`` of 1Y, 2Y … in order -
    as the desk's Forward sheet bootstraps it (each node's discount factor from its rate and the yearly coupons before
    it: :func:`xccy_df`), ln DF linear in days between the spot and its nodes (Bootstrap).  None without them all."""
    days: List[float] = [0.0]
    lns: List[float] = [0.0]
    dfs: List[float] = []
    for d, rate in quotes:
        if not (_real(d) and _real(rate)) or d <= days[-1]:
            return None
        d = float(d)
        df = xccy_df(rate / 100, days[1:] + [d], dfs)
        if df is None:
            return None
        days.append(d)
        dfs.append(df)
        lns.append(math.log(df))
    return LogLinear(days, lns) if len(days) > 1 else None


# ---------------------------------------------------------------------------------------------- the history
def history_series(defs: Sequence[Any]) -> List[Optional[Any]]:
    """The series of the dashboard's history that stands for each tenor (``TENORS``) on a past day, by the tenor's kind:
    its FX swap implied yield (group ``off``: TRYI1M … TRYI9M) or its cross currency swap (``xccy``: TRYSAQ1 …
    TRYSAQ10), matched by months; None where the history keeps none, and at 18M - computed, from the two series of
    :func:`history_pair` (:func:`history_row`).  ``defs``: the history's series (``History.snapshot()["defs"]``,
    ``SeriesDef``: ``group``, ``months``)."""
    out: List[Optional[Any]] = []
    for m in TENORS:
        group = HIST_GROUP.get(kind_of(m))
        out.append(None if group is None else next(
            (d for d in defs if d.group == group and type(d.months) is float and abs(d.months - m) < 1e-9), None))
    return out


def history_pair(defs: Sequence[Any]) -> Optional[Tuple[Any, Any]]:
    """The series of the XCCY nodes the 18M point lies between - TRYSAQ1 and TRYSAQ2 (group ``xccy``, 12 and 24 months),
    the series of 1Y and 2Y in :func:`history_series`; None without both."""
    got = [next((d for d in defs if d.group == "xccy" and type(d.months) is float and abs(d.months - m) < 1e-9), None)
           for m in CURVE_NODES]
    return (got[0], got[1]) if got[0] is not None and got[1] is not None else None


def history_anchors(sheet: Any) -> List[Optional[int]]:
    """The array formula whose result holds each tenor's history quotes (``C66:R325``), by its anchor (``rc``): ``B66``
    for 1M (one BDH call with its days: ``B:C``), ``D66`` … ``R66`` one BDH each; None where the cell is neither (a
    workbook of another layout).  ``sheet``: the ASW sheet of the model (``fml``, ``members``)."""
    out: List[Optional[int]] = []
    for k in range(len(TENORS)):
        rc = HIST_FIRST * COLS + QUOTE_COL + k
        out.append(rc if rc in sheet.fml else sheet.members.get(rc))
    return out


def history_point(xccy: Optional[Sequence[Any]], days: Sequence[Any]) -> Optional[Point]:
    """A past day's 18M point: :func:`point_18m` on the offshore XCCY curve of that day's TRYSAQ1 and TRYSAQ2 closes
    (``xccy``, %) at the sheet's node days of that row (``days``; :func:`xccy_curve`, ln DF linear - Bootstrap: a past day
    has no PPK curve).  None without both closes."""
    if xccy is None or len(xccy) != 2:
        return None
    d = [_at(days, node_of(m)) for m in (6, 18) + CURVE_NODES]
    if any(x is None for x in d):
        return None
    curve = xccy_curve([(d[2], xccy[0]), (d[3], xccy[1])])
    return point_18m(curve, d[0], d[1]) if curve is not None else None


def history_row(ois: Sequence[Any], fx: Sequence[Any], days: Sequence[Any],
                xccy: Optional[Sequence[Any]] = None) -> Tuple[List[Optional[float]], List[str]]:
    """A past day of the history on the offshore curve, tenor by tenor: the par quote of the sheet's convention the row is
    given for that day's rate (None: no quote reaches its discount factor; ``to_sheet``) and the kind of the quote
    (``FX_SWAP``, ``XCCY``: a rate of that day; ``CURVE``: 18M computed from that day's TRYSAQ1 and TRYSAQ2 closes,
    ``xccy`` - :func:`history_point`; ``OIS``: none - the row keeps its OIS quote as it is)."""
    point = history_point(xccy, days)
    got = to_sheet(ois, fx, days, {CURVE_TENOR: point} if point is not None else None)
    return [t.par for t in got], [t.kind for t in got]
