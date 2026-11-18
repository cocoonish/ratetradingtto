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

* up to 18 months ``TRYI…``, FX swap implied: one period, simple ACT/360 - an FX swap has no coupons:
  ``DF = 1 / (1 + r/100 · d/360)``;
* from 2 years ``TRYSAQ…``, cross currency swaps: an annual ACT/360 par rate,
  ``DF_n = (1 − r/100 · Σ τ_k DF_k) / (1 + r/100 · τ_n)`` over its yearly coupon dates (12, 24, … months: their discount
  factors the curve's as built so far - the sheet's own nodes, at or before the tenor quoted before), ``τ`` a year's
  days / 360.

The kind goes by the tenor (≤ 18M FX swap implied, ≥ 2Y XCCY), ``d`` is the sheet's node days of the tenor.  A tenor
without an FX price keeps its OIS quote as it is.

**To the sheet**, tenor by tenor in order: the discount factor the rate gives by its own convention is the target; up to
3M the sheet's quote with it is closed form (``p = (1/DF − 1) · 365/d``), from 6M on it is solved for - bisection on the
replica of the sheet's formulas (:func:`sheet_curve`), whose discount factor at the tenor falls as its quote rises.

**The history** ("ASW geçmişi", ``ASW!B66:Z325``: day by day, oldest first, each row the sheet's curve and the chosen
bonds' ASW on that day's OIS closes - ``C66:R325``, Bloomberg history blocks) on the offshore curve as well
(``Service._asw_hist_fx``): each past row's quotes swapped the same way for that day's offshore rates.  Those are the
dashboard's own daily closes (``tto/history.py``, nothing asked of Bloomberg for this), the series of each tenor by
:func:`history_series`: the FX swap implied yields of the Forward sheet's offshore rows (group ``off``: TRYI1M … TRYI9M)
at 1M–9M, its cross currency swaps (``xccy``) at 1Y (TRYSAQ1: the history keeps no TRYI12M - the desk's Forward sheet
takes this very swap as its offshore 12M; at one year an annual ACT/360 par rate is one period simple ACT/360, the FX
swap's reading) and at 2Y–10Y (TRYSAQ2 … TRYSAQ10, as EK_FX); each the first source with a close (ICPL, then the
workbook's BGN ticker; ``SeriesDef.merged``).  18M has no series (no TRYI18M is kept), and a day without a close of a
tenor has none either: there the day's OIS quote stays, as a tenor without an FX price does today."""
from __future__ import annotations

import math
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .xl.model import COLS

#: the tenors of the sheet's curve in months (ASW!C64:R64: 1M 2M 3M 6M 9M 1Y 18M 2Y … 10Y)
TENORS: Tuple[int, ...] = (1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120)
#: its nodes in months ("D0" … "D120", "L0" … "L120")
NODES: Tuple[int, ...] = (0, 1, 2, 3) + tuple(range(6, 121, 3))
#: today's row of the curve, the columns of the first quote (C), the first node's days (AB, "D0") and ln DF (BS, "L0")
ROW, QUOTE_COL, DAY_COL = 65, 3, 28
LN_COL = DAY_COL + len(NODES)
#: the longest tenor quoted as an FX swap implied yield (TRYI…); the longer ones are cross currency swaps (TRYSAQ…)
FX_SWAP_MAX = 18
#: a tenor's kind: FX swap implied, cross currency swap, no FX price (the OIS quote as it is)
FX_SWAP, XCCY, OIS = "fx", "xccy", "ois"
#: how a kind of rate is read (the EK_FX table's words)
RULES = {FX_SWAP: "FX swap ima: tek dönem, basit ACT/360", XCCY: "XCCY: yıllık par, ACT/360",
         OIS: "fiyat yok: OIS kotası, sayfanın kuralıyla"}
#: the quotes a solve looks between (%) and how close its discount factor must come to the target
LOW, HIGH, TOLERANCE = -100.0, 1000.0, 1e-12
#: the history's rows (day by day, oldest first: ``B66:Z325``) and the column of their days
HIST_FIRST, HIST_LAST, HIST_DATE_COL = 66, 325, 2
#: the groups of the dashboard's history a tenor's series is looked for in, in this order (tto/history.py): the Forward
#: sheet's FX swap implied yields (TRYI…), then its cross currency swaps (TRYSAQ…)
HIST_GROUPS = ("off", "xccy")

_INDEX = {m: i for i, m in enumerate(NODES)}
_TENOR_SET = frozenset(TENORS)
#: a node between two tenors: the two (the quotes it is interpolated between)
_BRACKET = {m: (max(t for t in TENORS if t < m), min(t for t in TENORS if t > m)) for m in NODES
            if m not in _TENOR_SET and TENORS[0] < m < TENORS[-1]}


class Tenor(NamedTuple):
    """A tenor of the FX swap implied curve: ``kind`` (``FX_SWAP``, ``XCCY``, ``OIS``), the rate ``quote``d (the FX rate,
    or the OIS quote without one), the discount factor ``df`` the FX rate gives at the tenor by its own convention (None
    for ``OIS``) and the ``par`` quote the sheet is given - the rate of its own convention with that discount factor
    (the OIS quote for ``OIS``; None when there is none: a missing day or quote, a discount factor no quote reaches)."""
    months: int
    kind: str
    quote: Optional[float]
    df: Optional[float]
    par: Optional[float]


def kind_of(months: int) -> str:
    """The kind of the FX rate of a tenor: an FX swap implied yield up to 18 months, a cross currency swap after."""
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


def to_sheet(ois: Sequence[Any], fx: Sequence[Any], days: Sequence[Any]) -> List[Tenor]:
    """The FX swap implied curve's tenors (``TENORS``) as the sheet is to be given them: ``ois`` the sheet's quotes
    (``C65:R65``), ``fx`` EK_FX's rates of the same tenors (``D6:D21``; anything but a number: no FX price), ``days``
    the days to the sheet's nodes (``AB65:BR65``).  See the module's text for the conventions."""
    day = [_at(days, i) for i in range(len(NODES))]
    pars: Dict[int, Optional[float]] = {}
    ln: List[Optional[float]] = [0.0] + [None] * (len(NODES) - 1)
    h: List[Optional[float]] = [None] * len(NODES)
    out: List[Tenor] = []
    done = 0                                                    # the last node worked out (with the tenors so far)
    for k, m in enumerate(TENORS):
        i = node_of(m)
        rate = _at(fx, k)
        if rate is None:
            q = _at(ois, k)
            pars[m] = q
            _walk(pars, day, ln, h, done + 1, i)
            done = i
            out.append(Tenor(m, OIS, q, None, q))
            continue
        kind = kind_of(m)
        target = _target(kind, rate, m, day, ln)
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
    ann, last = 0.0, 0.0                                        # the yearly coupons before the last one
    for y in range(12, m, 12):
        j = node_of(y)
        if day[j] is None or ln[j] is None:
            return None
        ann += (day[j] - last) / 360 * math.exp(ln[j])
        last = day[j]
    df = (1 - r * ann) / (1 + r * (d - last) / 360)
    return df if df > 0 else None


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


# ---------------------------------------------------------------------------------------------- the history
def history_series(defs: Sequence[Any]) -> List[Optional[Any]]:
    """The series of the dashboard's history that stands for each tenor (``TENORS``) on a past day: its FX swap implied
    yield (group ``off``: TRYI1M … TRYI9M), else its cross currency swap (``xccy``: TRYSAQ1 at 1Y, TRYSAQ2 … TRYSAQ10),
    matched by months; None where the history keeps neither (18M) - there the day's OIS quote stays.  ``defs``: the
    history's series (``History.snapshot()["defs"]``, ``SeriesDef``: ``group``, ``months``)."""
    out: List[Optional[Any]] = []
    for m in TENORS:
        out.append(next((d for g in HIST_GROUPS for d in defs
                         if d.group == g and type(d.months) is float and abs(d.months - m) < 1e-9), None))
    return out


def history_anchors(sheet: Any) -> List[Optional[int]]:
    """The array formula whose result holds each tenor's history quotes (``C66:R325``), by its anchor (``rc``): ``B66``
    for 1M (one BDH call with its days: ``B:C``), ``D66`` … ``R66`` one BDH each; None where the cell is neither (a
    workbook of another layout).  ``sheet``: the ASW sheet of the model (``fml``, ``members``)."""
    out: List[Optional[int]] = []
    for k in range(len(TENORS)):
        rc = HIST_FIRST * COLS + QUOTE_COL + k
        out.append(rc if rc in sheet.fml else sheet.members.get(rc))
    return out


def history_row(ois: Sequence[Any], fx: Sequence[Any], days: Sequence[Any]) -> Tuple[List[Optional[float]], List[str]]:
    """A past day of the history on the offshore curve, tenor by tenor: the par quote of the sheet's convention the row is
    given for that day's rate (None: no quote reaches its discount factor; ``to_sheet``) and the kind of the quote
    (``FX_SWAP``, ``XCCY``: a rate of that day; ``OIS``: none - the row keeps its OIS quote as it is)."""
    got = to_sheet(ois, fx, days)
    return [t.par for t in got], [t.kind for t in got]
