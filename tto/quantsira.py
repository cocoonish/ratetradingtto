"""Carry + momentum (family "sira"): the universe's instruments (``quantuniv.py``) ranked against each other set by set,
one basket a set, rebalanced every week - "the best three AL, the worst three SAT".  Page "Carry + momentum" under
Sinyaller; its legs are lines of the Sinyaller list.

**When.**  At Monday's close - the first close of the week; a week whose Monday is a holiday rebalances at its first
business day's close - each set is ranked on the closes up to that close only, and its basket is held to the next
rebalance's close.  Between the two its lines stay as they were made (rank, size), with the basket's P&L so far; every
card says the next rebalance's date.

**The sets** (``SETS``):

* **G10 spot** - the seven pairs' currencies against USD: z(carry) + z(momentum), z across the pairs at that close.
  Carry: the 3M forward's annualised rate differential, the currency's own way (the pair's for a base currency, its
  negative for a quote one); momentum: the 3-month return of holding the currency through its forwards, carry included
  (the pair's excess-return index ``XR:``).  Long the best three, short the worst three against USD, told as the pair
  goes (buying JPY is SAT USDJPY); equal risk a leg within a side (USD notional ∝ 1 ÷ its daily σ, a median pair 1 mn
  USD), the two sides' dollars equal (dollar-neutral).
* **G10 vol** - the pairs' 3M ATM straddles: z(premium: the 3M implied − the spot's 63-day realised) + z(a vol seller's
  momentum: −the implied's 3-month change).  Sell the three richest, buy the three cheapest, 10.000 $ vega each
  (vega-neutral).  A straddle's P&L: the implied's change × vega plus its theta and gamma, delta-hedged daily
  (vega ÷ (2σ τ) × (r² − σ² ÷ 252) a day, τ three months: rolled).
* **TRY OIS** - the outrights to 2Y (1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y): z(carry + roll ÷ volatility) + z(−the 3-month
  change of the yield: falling yields favour receive).  Receive the best two, pay the worst two, 1.000 $ DV01 each.
* **TRY OIS spreads** and, apart, **flies** (the registry's: spreads DV01 1:1, flies 50/50, ≤ 2Y first in the list) -
  each package its own way: its carry + roll ÷ volatility plus its 3-month move, each over its root mean square across
  the set (not centred: the score's sign is the package's way - + steepener / gövde pay, − flattener / gövde receive);
  the three strongest, each its own way, 1.000 $ DV01.
* **DİBS** - the DİBS RV list's fixed-coupon bonds: z(carry + roll ÷ volatility) + z(cheapness: the DİBS curve fit's
  residual z) + z(−the 3-month yield change).  Buy the best three, sell the worst three, 1.000 $ DV01 each.

**Carry + roll on past closes.**  The Carry & Roll engine's numbers and the DİBS fit's carry are today's alone; a
basket made at a past close (the walk-forward, and the week's own basket all week long - a fit on Wednesday must make
Monday's basket again) needs them as of that close.  So the ranking reads each close's own curve: a TRY OIS tenor's
week is (its rate − TLREF of the week) × 7/365 ÷ its annuity (the workbook's schedule) plus its roll a week down that
close's curve (linear in months, TLREF at 0) - bp of its DV01, for a receiver; a bond's is (its yield − TLREF of the
week) × 7/365 ÷ its modified duration plus its roll down that close's fitted curve (each bond's yield less its
residual, linear in maturity).  TLREF of the week is the close's meeting path's (PPK Fiyatlama Geçmişi): a decision
within the week moves it by the priced step from the next day - the floating leg the engine compounds along its path
too.  The lines' "carry + roll" on the card is the engine's (the fit's for DİBS) where there is one.

**Volatility** is the σ of the last 60 daily moves (P&L units), × √5 a week.

**Backtest** (walk-forward, no look-ahead).  At every rebalance of the history (two years of closes less the three
months a momentum needs; DİBS on the curve fit's residual window) the set's basket is made of the closes up to it and
held to the next rebalance's close: its P&L in money (the legs' moves; a rates leg's carry + roll of the rebalance for
the days held; FX carry-inclusive; a straddle's theta and gamma) and its risk, the ex-ante σ of the week (the basket's
daily P&L over the 60 closes before, at its weights, × √5).  Per set and for the family: weeks, hit rate, Sharpe (the
week's P&L in risk units, mean ÷ σ × √52) and the largest drawdown - the Sinyaller backtest panel takes them
(``quantuniv.own_backtests``: this family walks its own weekly calendar, not the refits').

**The lines.**  A basket's leg is a line of the Sinyaller list, in its group ("model: Carry + momentum · G10 spot
sepeti"): the trade in the desk's words with its size ("SAT USDJPY spot · 1,2 mn USD"), entry, target and stop in its
price, the expected P&L in money, the hit rate and the trade count of its levels.  **Levels** (``tto.quantlevels``): the
basket is the trade - every week of the walk its daily P&L in its own ex-ante weekly σ (diversified), calibrated per
list group (TRY OIS's three sets pooled) month by month on the weeks that had ended before: a stop k and a target m
in that σ, the best expectancy with m / k ≥ 1.  Each leg gets the basket's multiples of its own weekly σ (its target m
× σ_leg, its stop k × σ_leg), its expectancy the basket's (the record's mean × the basket's risk) shared by its σ; the
card shows the basket's Ödül / risk.  Weeks that lost money even at the best levels make every leg "düşük güven".
Without enough weeks the old rule stands: the backtest's mean week as the target, 2σ against as the stop.  Every
instrument of a set has a monitor - its score
"sıra" 2 for the strongest of a side down to 1 for the weakest, under 1 out of the basket (entry 1) -, so an
instrument entering a basket at a rebalance is a new line: logged and alerted.  No gates: a basket's legs are its
lines whatever their carry or expected profit (the card shows those checks) - only their levels' record can make them
"düşük güven".  Lines are keyed by what they are (a
pair, a tenor, a package, an ISIN): a calendar edit, a roll or a new bond moves no state from one line to another.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quantbt as qbt
from . import quantcurve as qc
from . import quantfam as qf
from . import quantlevels as qlv
from . import quantmath as qm
from . import quantuniv as qu

FAMILY = "sira"
PAGES = (("quant-sira", "Carry + momentum"),)
VIEWS = {"sira": "quant-sira"}

MOM_DAYS = 63                    # three months of closes: the momentum's span
VOL_DAYS = qu.VOL_DAYS           # the daily moves a σ is measured over (60)
RV_DAYS = 63                     # the spot's realised vol a straddle's premium is measured against
MIN_MOVES = 20                   # moves a σ needs at least
STALE_DAYS = 7                   # a close older than this (calendar days) at a rebalance is no close
WEEK = 5.0                       # business days a basket is held (its lines' holding)
H_YEARS = 7.0 / 365.0            # a week of carry, in years
H_MONTHS = 7.0 / 30.4375         # a week of an OIS tenor's roll, in months
STRADDLE_YEARS = 0.25            # a 3M straddle's time to expiry (held: rolled every day)
TRADING_DAYS = 252.0
RESID_WINDOW = 250               # the cheapness z's window of residuals (the curve fit's lookback)
MIN_RESID = 20
MIN_WEEKS = 8                    # backtest weeks an expected P&L needs
STOP_SIGMA = 2.0                 # the stop: 2σ of the week's P&L against
FX_MONEY = 1e4                   # USD a 1 % move of 1 mn USD notional (a G10 leg's P&L unit: % of its notional)
TR_DAYS = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")
SHORT_OUTRIGHTS = tuple(t for t in qu.OUTRIGHTS if qf._TENOR_MONTHS[t] <= qu.SHORT_MONTHS)

#: the sets in the page's order: id, basket's name, the list's group, mode ("ls": the best k one way, the worst k the
#: other; "best": the k strongest, each its own way), k
SETS: Tuple[Tuple[str, str, str, str, int], ...] = (
    ("g10", "G10 spot sepeti", "G10 spot", "ls", 3),
    ("vol", "G10 vol sepeti", "G10 opsiyon", "ls", 3),
    ("ois", "TRY OIS sepeti", "TRY OIS", "ls", 2),
    ("spread", "TRY OIS spread sepeti", "TRY OIS", "best", 3),
    ("fly", "TRY OIS fly sepeti", "TRY OIS", "best", 3),
    ("dibs", "DİBS sepeti", "DİBS", "ls", 3),
)
#: what a set's columns are (the page's ranking table): carry, momentum, the score's direction
COLUMNS: Dict[str, Dict[str, str]] = {
    "g10": {"carry": "Carry % / yıl", "mom": "Momentum % (3A, carry dahil)", "way": "para birimi long"},
    "vol": {"carry": "Prim (vol): ima − gerçekleşen", "mom": "Momentum (vol): −Δ ima 3A", "way": "vol sat"},
    "ois": {"carry": "Carry + roll bp / hf (receive)", "mom": "Momentum bp: −Δ 3A", "way": "receive"},
    "spread": {"carry": "Carry + roll bp / hf (steepener)", "mom": "Momentum bp: Δ 3A", "way": "steepener"},
    "fly": {"carry": "Carry + roll bp / hf (gövde pay)", "mom": "Momentum bp: Δ 3A", "way": "gövde pay"},
    "dibs": {"carry": "Carry + roll bp / hf (alıcı)", "mom": "Momentum bp: −Δ 3A", "way": "kâğıdı al"},
}
NOTES = {
    "g10": "Sepet: carry (3A forward'ın yıllık faiz farkı) ve son 3 ayın carry dahil getirisi en yüksek üç para birimi USD'ye karşı "
           "alınır, en düşük üçü satılır; her bacak kendi oynaklığıyla eşit risk, iki tarafın dolar tutarı eşit (dolar-nötr).",
    "vol": "Sepet: 3A ATM ima vol'ün son 63 günün gerçekleşen vol'ünden farkı (prim) ve ima vol'ün son 3 aydaki düşüşü en büyük üç "
           "paritede vol satılır, en küçük üçte alınır; 10.000 $ vega'lık straddle'lar (vega-nötr). K/Z: ima vol'ün değişimi artı "
           "straddle'ın teta / gama'sı (her gün delta hedge'li).",
    "ois": "Sepet: haftalık carry + roll'u oynaklığına göre en yüksek ve faizi son 3 ayda en çok düşen iki vade receive, en kötü iki "
           "vade pay edilir; her bacak 1.000 $ DV01 (DV01-nötr). Carry + roll: o günün eğrisinden (faiz − TLREF) ve eğride bir hafta "
           "yuvarlanma.",
    "spread": "Her spread kendi yönünde: carry + roll ÷ oynaklık artı son 3 ayın hareketi (+ steepener, − flattener); en güçlü üç spread, "
              "1.000 $ DV01 (1:1).",
    "fly": "Her fly kendi yönünde: carry + roll ÷ oynaklık artı son 3 ayın hareketi (+ gövde pay / kanatlar receive, − tersi); en güçlü "
           "üç fly, 1.000 $ DV01 (50/50).",
    "dibs": "Sepet: carry + roll ÷ oynaklık, DİBS eğri uyumuna göre ucuzluk (kalıntının z'si) ve getirinin son 3 aydaki düşüşü en iyi "
            "üç kâğıt alınır, en kötü üçü satılır; her bacak 1.000 $ DV01 (DV01-nötr).",
}


def _d(iso: str) -> _dt.date:
    return _dt.date.fromisoformat(iso)


def _num(v: Any) -> Optional[float]:
    return v if isinstance(v, float) and math.isfinite(v) else (float(v) if isinstance(v, int) and not isinstance(v, bool) else None)


# ---------------------------------------------------------------------------------------------- series and scores
class _Ser(object):
    """A series as arrays: its closes (``days``, ``vals``) and each close's move from the one before in P&L units of the
    up side (``moves``, the first 0), with their running sums - a move over any span, a σ over any window in O(1)."""

    def __init__(self, days: List[str], vals: List[float], moves: List[float]):
        self.days, self.vals, self.moves = days, vals, moves
        self.pos = {d: i for i, d in enumerate(days)}
        c1, c2 = [0.0], [0.0]
        for x in moves:
            c1.append(c1[-1] + x)
            c2.append(c2[-1] + x * x)
        self.c1, self.c2 = c1, c2

    def __len__(self) -> int:
        return len(self.days)

    def at(self, day: str) -> Optional[int]:
        """The last close on or before ``day`` - none staler than ``STALE_DAYS``."""
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0 or (_d(day) - _d(self.days[i])).days > STALE_DAYS:
            return None
        return i

    def total(self, i: int, j: int) -> float:
        """The moves after close ``i`` up to close ``j``."""
        return self.c1[j + 1] - self.c1[i + 1] if j > i else 0.0

    def sigma(self, i: int, n: int = VOL_DAYS) -> Optional[float]:
        """The σ of the ``n`` moves up to close ``i`` (P&L units a day); ``None`` with fewer than ``MIN_MOVES``."""
        lo = max(1, i - n + 1)
        m = i - lo + 1
        if m < MIN_MOVES:
            return None
        s1 = self.c1[i + 1] - self.c1[lo]
        s2 = self.c2[i + 1] - self.c2[lo]
        v = (s2 - s1 * s1 / m) / (m - 1)
        return math.sqrt(v) if v > 1e-12 * (s2 / m) + 1e-18 else None


def _ser(pts: Sequence[Tuple[str, float]], move: Callable[[float, float], Optional[float]]) -> _Ser:
    days = [d for d, _ in pts]
    vals = [v for _, v in pts]
    mv = [0.0]
    for a, b in zip(vals, vals[1:]):
        x = move(a, b)
        mv.append(x if x is not None and math.isfinite(x) else 0.0)
    return _Ser(days, vals, mv)


def _asof(days: Sequence[str], vals: Sequence[float], day: str) -> Optional[float]:
    i = bisect.bisect_right(days, day) - 1
    if i < 0 or (_d(day) - _d(days[i])).days > STALE_DAYS:
        return None
    return vals[i]


#: a component that varies less than this across a set (in its own units: bp, %, vol, z) does not rank it - float noise
#: of equal values is no order
FLAT = 1e-9


def _z(xs: Sequence[float]) -> List[float]:
    """Cross-sectional z: (x − the set's mean) ÷ its σ at that close; all 0 when they do not differ."""
    n = len(xs)
    if n < 2:
        return [0.0] * n
    m = sum(xs) / n
    sd = qm.stdev(xs)
    return [(x - m) / sd for x in xs] if sd and sd > FLAT else [0.0] * n


def _rms(xs: Sequence[float]) -> List[float]:
    """Each over the set's root mean square: a scale, not a centre (the sign stays the package's own way)."""
    n = len(xs)
    r = math.sqrt(sum(x * x for x in xs) / n) if n else 0.0
    return [x / r for x in xs] if r > FLAT else [0.0] * n


def rebalance_days(days: Sequence[str], holidays: Optional[set] = None) -> List[str]:
    """The rebalances among a set's closes: each week's first close on a business day (Monday's, or the next one's
    when Monday is a holiday)."""
    hol = holidays or set()
    out: List[str] = []
    week = None
    for d in days:
        dd = _d(d)
        if dd.weekday() >= 5 or dd in hol:
            continue
        w = dd.isocalendar()[:2]
        if w != week:
            out.append(d)
            week = w
    return out


def next_rebalance(today: _dt.date, days: Sequence[str], holidays: Optional[set] = None) -> _dt.date:
    """The next rebalance's close: today's week's first business day on or after today while the week has no close yet
    (a Monday: today), else the next week's first business day."""
    hol = holidays or set()
    week = today.isocalendar()[:2]
    done = any(_d(x).isocalendar()[:2] == week for x in days[-7:])
    d = today if not done else today + _dt.timedelta(days=7 - today.weekday())
    while d.weekday() >= 5 or d in hol:
        d += _dt.timedelta(days=1)
    return d


def _day_tr(d: _dt.date) -> str:
    return "%s (%s)" % (d.strftime("%d.%m.%Y"), TR_DAYS[d.weekday()])


# ---------------------------------------------------------------------------------------------- carry + roll of a close
class _Curve(object):
    """Each close's TRY OIS curve as the history keeps it (every tenor, 1W … 10Y, 15M / 21M among them; TLREF at 0
    months) and its meeting path (``quantpath.try_paths``: the PPK Fiyatlama Geçmişi of that day): a tenor's carry +
    roll of a week for a receiver, bp of its DV01 - from that close only."""

    def __init__(self, ctx: qf.Ctx, paths: Optional[Dict[str, Dict[str, Any]]] = None):
        self.ctx = ctx
        self.paths = paths or {}
        self.tenors = sorted((float(m["months"]), k) for k, m in ctx.meta.items() if k.startswith("OIS:") and m.get("months"))
        self.arr = {k: ([d for d, _ in ctx.pts(k)], [v for _, v in ctx.pts(k)]) for _, k in self.tenors}
        ref = ctx.pts("TLREF")
        self.ref = ([d for d, _ in ref], [v for _, v in ref])
        self._memo: Dict[str, Tuple[Optional[float], List[Tuple[float, float]]]] = {}
        self._float: Dict[str, Optional[float]] = {}

    def rate(self, key: str, day: str) -> Optional[float]:
        a = self.arr.get(key)
        return _asof(a[0], a[1], day) if a else None

    def floating(self, day: str) -> Optional[float]:
        """TLREF over the week after the close, as that close's meeting path expects it: TLREF at the close (the
        shortest tenor's rate without it), a decision within the week moving it from its next day by the step the path
        prices (its level after the meeting − the path's base).  Without a path that day: TLREF at the close."""
        if day in self._float:
            return self._float[day]
        f0 = self.points(day)[0]
        p = self.paths.get(day)
        out = f0
        if f0 is not None and p:
            d0 = _d(day)
            steps = sorted((_d(m), lv - p["base"]) for m, lv in p["meetings"])
            tot = 0.0
            for j in range(1, 8):
                t = d0 + _dt.timedelta(days=j)
                tot += f0 + next((s for m, s in reversed(steps) if m < t), 0.0)
            out = tot / 7.0
        self._float[day] = out
        return out

    def points(self, day: str) -> Tuple[Optional[float], List[Tuple[float, float]]]:
        hit = self._memo.get(day)
        if hit is None:
            pts = [(m, v) for m, k in self.tenors for v in [self.rate(k, day)] if v is not None]
            f = _asof(self.ref[0], self.ref[1], day) if self.ref[0] else None
            if f is None and pts:
                f = pts[0][1]
            hit = self._memo[day] = (f, ([(0.0, f)] if f is not None else []) + pts)
        return hit

    def receive(self, key: str, day: str) -> Optional[float]:
        """A week of receiving the tenor from ``day``'s close, bp of its DV01: (rate − TLREF of the week, ``floating``) ×
        7/365 ÷ its annuity (the workbook's schedule) plus its roll a week down the curve."""
        months = self.ctx.months(key)
        r = self.rate(key, day)
        curve = self.points(day)[1]
        f = self.floating(day)
        if not months or r is None or f is None:
            return None
        ann = qf._annuity(r, months)
        if not ann or ann <= 0:
            return None
        rolled = qf._interp(curve, max(0.0, months - H_MONTHS))
        return (r - f) * 100.0 * H_YEARS / ann + ((r - rolled) * 100.0 if rolled is not None else 0.0)


# ---------------------------------------------------------------------------------------------- the sets
class _Cand(object):
    """An instrument of a set: its registry line, the series it is paid on (``pay``: P&L units of the up side a close)
    and its level (``lvl``: the price its card tells), the money of a P&L unit (size 1) and the way its score points
    (``orient``: +1 when the score's side is the line's up side)."""

    __slots__ = ("inst", "key", "label", "pay", "lvl", "money1", "orient", "x")

    def __init__(self, inst: Any, pay: _Ser, money1: float, orient: int, lvl: Optional[_Ser] = None, **x: Any):
        self.inst, self.key, self.label = inst, inst.key, inst.label
        self.pay, self.lvl = pay, lvl if lvl is not None else pay
        self.money1, self.orient, self.x = money1, orient, x


class _Book(object):
    """One set: its instruments, how each reads at a close (``feats``), its basket at a close, the basket's risk and the
    P&L of its week."""

    def __init__(self, sid: str, name: str, group: str, mode: str, k: int, ccy: str, cands: List[_Cand], why: str = ""):
        self.sid, self.name, self.group, self.mode, self.k, self.ccy = sid, name, group, mode, k, ccy
        self.cands = cands
        self.why = why
        self.min_n = 2 * k if mode == "ls" else k + 1
        self.calendar = sorted({d for c in cands for d in c.pay.days})
        self.cols = COLUMNS[sid]

    def feats(self, c: _Cand, day: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    # ---- a basket
    def basket(self, day: str) -> Optional[Dict[str, Any]]:
        """The ranking at ``day``'s close (only closes up to it) and its basket: the members with their side and size."""
        rows = []
        for c in self.cands:
            f = self.feats(c, day)
            if f is not None:
                f["cand"] = c
                rows.append(f)
        if len(rows) < self.min_n:
            return None
        cols = list(zip(*[r["parts"] for r in rows]))
        scale = _z if self.mode == "ls" else _rms
        zs = [scale(list(col)) for col in cols]
        for i, r in enumerate(rows):
            r["zs"] = [z[i] for z in zs]
            r["composite"] = sum(r["zs"])
        _rank(rows, self.mode, self.k)
        legs = sorted((r for r in rows if r["side"]), key=lambda r: r["rank"])
        if not legs:
            return None
        self.size(legs, rows, day)
        risk = self.risk(legs, day)
        if risk is None:
            return None
        return {"day": day, "rows": rows, "legs": legs, "risk": risk}

    def size(self, legs: List[Dict[str, Any]], rows: List[Dict[str, Any]], day: str) -> None:
        for leg in legs:
            leg["size"] = leg["k"] = 1.0

    def risk(self, legs: List[Dict[str, Any]], day: str) -> Optional[float]:
        """The ex-ante σ of the basket's week (money): its daily P&L at these weights over the set's last 60 closes up to
        ``day``, × √5; each leg's own (``sigma_w``) beside it."""
        end = bisect.bisect_right(self.calendar, day)
        window = self.calendar[max(0, end - VOL_DAYS):end]
        daily = []
        for d in window:
            x = 0.0
            for leg in legs:
                c = leg["cand"]
                i = c.pay.pos.get(d)
                if i:
                    x += leg["side"] * leg["size"] * c.money1 * c.pay.moves[i]
            daily.append(x)
        sd = qm.stdev(daily) if len(daily) >= MIN_MOVES else None
        for leg in legs:
            leg["sigma_w"] = leg["size"] * leg["cand"].money1 * leg["sigma"] * math.sqrt(WEEK)
        return sd * math.sqrt(WEEK) if sd else None

    def week(self, legs: List[Dict[str, Any]], day: str, end: str) -> Tuple[float, int]:
        """The basket's P&L from ``day``'s close to ``end``'s (money; a rates leg's carry + roll of ``day`` for the
        business days held) and the business days held."""
        nb = bisect.bisect_right(self.calendar, end) - bisect.bisect_right(self.calendar, day)
        tot = 0.0
        for leg in legs:
            c = leg["cand"]
            i, j = c.pay.at(day), c.pay.at(end)
            units = c.pay.total(i, j) if i is not None and j is not None else 0.0
            units += (leg.get("cu") or 0.0) * nb / WEEK
            tot += leg["side"] * leg["size"] * c.money1 * units
        return tot, nb

    def path(self, legs: List[Dict[str, Any]], day: str, end: str) -> List[float]:
        """The basket's P&L at every close after ``day``'s up to ``end``'s (money, as :meth:`week` - its carry + roll
        pro rata): the path its levels are calibrated on (``quantlevels``); its last the week's P&L."""
        i0, i1 = bisect.bisect_right(self.calendar, day), bisect.bisect_right(self.calendar, end)
        out = []
        for j in range(i0, i1):
            d = self.calendar[j]
            tot = 0.0
            for leg in legs:
                c = leg["cand"]
                a, b = c.pay.at(day), c.pay.at(d)
                units = c.pay.total(a, b) if a is not None and b is not None else 0.0
                units += (leg.get("cu") or 0.0) * (j - i0 + 1) / WEEK
                tot += leg["side"] * leg["size"] * c.money1 * units
            out.append(tot)
        return out

    # ---- the walk forward
    def walk(self, holidays: Optional[set]) -> Dict[str, Any]:
        """Every rebalance of the history: the basket of its close, held to the next one's (the weeks), the score of each
        instrument then (``z``: day -> key -> sıra) and the basket of the last rebalance - this week's."""
        rebal = rebalance_days(self.calendar, holidays)
        weeks: List[Dict[str, Any]] = []
        zs: Dict[str, Dict[str, float]] = {}
        for day, end in zip(rebal, rebal[1:]):
            b = self.basket(day)
            if b is None:
                continue
            zs[day] = {r["cand"].key: r["z"] for r in b["rows"]}
            pnl, nb = self.week(b["legs"], day, end)
            weeks.append({"day": day, "end": end, "pnl": pnl, "risk": b["risk"], "r": pnl / b["risk"], "held": nb,
                          "legs": [(leg["cand"].key, leg["side"]) for leg in b["legs"]],
                          "path": [x / b["risk"] for x in self.path(b["legs"], day, end)],
                          "text": " · ".join("%s %s" % (leg["cand"].inst.verb(leg["side"]), leg["cand"].label) for leg in b["legs"])})
        cur = self.basket(rebal[-1]) if rebal else None
        if cur is not None:
            zs[cur["day"]] = {r["cand"].key: r["z"] for r in cur["rows"]}
        return {"rebal": rebal, "weeks": weeks, "z": zs, "current": cur}


def _rank(rows: List[Dict[str, Any]], mode: str, k: int) -> None:
    """Each row's rank, side (the line's up side: +1 / −1, 0 out of the basket) and score "sıra": 2 the strongest of a
    side … 1 its weakest, under 1 in absolute value out of the basket (its distance from the basket's edge)."""
    n = len(rows)
    if mode == "ls":
        order = sorted(range(n), key=lambda i: (-rows[i]["composite"], rows[i]["cand"].key))
        thr = (n - 2 * k + 1) / float(n - 1)
        for r, i in enumerate(order):
            row = rows[i]
            o = row["cand"].orient
            row["rank"] = r + 1
            if r < k:
                side_c, j = 1, r
            elif r >= n - k:
                side_c, j = -1, n - 1 - r
            else:
                side_c, j = 0, 0
            row["side_c"] = side_c
            row["side"] = side_c * o
            row["z"] = (row["side"] * (2.0 - j / (k - 1.0) if k > 1 else 2.0) if side_c
                        else o * (1.0 - 2.0 * r / (n - 1)) / thr)
    else:
        order = sorted(range(n), key=lambda i: (-abs(rows[i]["composite"]), rows[i]["cand"].key))
        thr = 1.0 - (k - 1) / float(n - 1)
        for r, i in enumerate(order):
            row = rows[i]
            s = qf.sign(row["composite"])
            row["rank"] = r + 1
            member = r < k and s != 0
            row["side_c"] = s if member else 0
            row["side"] = s if member else 0
            row["z"] = (s * (2.0 - r / (k - 1.0) if k > 1 else 2.0) if member else s * (1.0 - r / (n - 1)) / thr)


class _G10(_Book):
    """The G10 pairs' currencies against USD."""

    def __init__(self, ctx: qf.Ctx, reg: qu.Registry, sid: str, name: str, group: str, mode: str, k: int):
        cands = []
        for inst in reg.tradeable("G10 spot"):
            xr = ctx.pts("XR:" + inst.pair)
            carry = sorted(inst.carry_days().items())
            if len(xr) < 2 or not carry:
                continue
            base = inst.pair[:3] != "USD"                                 # (long the currency: long the pair when it is the base)
            cands.append(_Cand(inst, _ser(xr, lambda a, b: b - a), FX_MONEY, 1 if base else -1,
                               lvl=_ser(inst.pts(), lambda a, b: None), carry=([d for d, _ in carry], [v for _, v in carry]),
                               ccy=inst.pair[:3] if base else inst.pair[3:]))
        super().__init__(sid, name, group, mode, k, "USD", cands, "" if cands else "G10 spot ve 3A forward puanı geçmişi yok")

    def feats(self, c: _Cand, day: str) -> Optional[Dict[str, Any]]:
        i = c.pay.at(day)
        if i is None or i < MOM_DAYS:
            return None
        car = _asof(c.x["carry"][0], c.x["carry"][1], day)
        sd = c.pay.sigma(i)
        spot = _asof(c.lvl.days, c.lvl.vals, day)
        if car is None or sd is None or not spot:
            return None
        o = c.orient
        carry, mom = o * car, o * (c.pay.vals[i] - c.pay.vals[i - MOM_DAYS])
        return {"carry": carry, "mom": mom, "sigma": sd, "parts": [carry, mom], "cu": 0.0, "spot": spot, "ccy": c.x["ccy"]}

    def size(self, legs: List[Dict[str, Any]], rows: List[Dict[str, Any]], day: str) -> None:
        """Equal risk a leg within a side (USD notional ∝ 1 ÷ σ; the set's median σ is 1 mn USD), the two sides' dollars
        equal: dollar-neutral."""
        ref = sorted(r["sigma"] for r in rows)[len(rows) // 2]
        for leg in legs:
            leg["usd"] = 1e6 * ref / leg["sigma"]
        gross = sum(leg["usd"] for leg in legs)
        for side in (1, -1):
            mine = [leg for leg in legs if leg["side_c"] == side]
            tot = sum(leg["usd"] for leg in mine)
            for leg in mine:
                leg["usd"] *= gross / 2.0 / tot if tot else 0.0
        for leg in legs:
            leg["size"] = leg["usd"] / 1e6
            leg["k"] = leg["usd"] / (1e6 * leg["spot"]) if leg["cand"].orient > 0 else leg["usd"] / 1e6


class _Vol(_Book):
    """The G10 pairs' 3M ATM straddles."""

    def __init__(self, ctx: qf.Ctx, reg: qu.Registry, sid: str, name: str, group: str, mode: str, k: int):
        cands = []
        for pair in qu.G10_PAIRS:
            inst, spot = reg.get("FXV:" + pair), reg.get("FX:" + pair)
            if inst is None or spot is None:
                continue
            sp = spot.pts()
            sd, sv = [d for d, _ in sp], [v for _, v in sp]
            iv = inst.pts()
            if len(iv) < 2 or len(sp) < 2:
                continue
            mv = [0.0]
            for (d0, a), (d1, b) in zip(iv, iv[1:]):
                s0, s1 = _asof(sd, sv, d0), _asof(sd, sv, d1)
                tg = 0.0
                if a > 0 and s0 and s1 and s0 > 0 and s1 > 0:
                    r = math.log(s1 / s0)
                    # (theta + gamma of a day, vol points of vega: vega ÷ (2σ τ) × (r² − σ² dt), σ = a ÷ 100, dt = 1 / 252)
                    tg = 100.0 / (2.0 * (a / 100.0) * STRADDLE_YEARS) * (r * r - (a / 100.0) ** 2 / TRADING_DAYS)
                mv.append(b - a + tg)
            pay = _Ser([d for d, _ in iv], [v for _, v in iv], mv)
            cands.append(_Cand(inst, pay, qu.VEGA_USD, -1, rets=_ser(sp, lambda a, b: math.log(b / a) * 100.0 if a > 0 and b > 0 else None)))
        super().__init__(sid, name, group, mode, k, "USD", cands, "" if cands else "G10 ATM 3A vol geçmişi yok")

    def feats(self, c: _Cand, day: str) -> Optional[Dict[str, Any]]:
        i = c.pay.at(day)
        j = c.x["rets"].at(day)
        if i is None or i < MOM_DAYS or j is None:
            return None
        rv = c.x["rets"].sigma(j, RV_DAYS)
        sd = c.pay.sigma(i)
        if rv is None or sd is None:
            return None
        iv = c.pay.vals[i]
        rv *= math.sqrt(TRADING_DAYS)
        prem, mom = iv - rv, -(iv - c.pay.vals[i - MOM_DAYS])
        return {"carry": prem, "mom": mom, "sigma": sd, "parts": [prem, mom], "cu": 0.0, "iv": iv, "rv": rv}


class _Ois(_Book):
    """The TRY OIS outrights to 2Y."""

    def __init__(self, ctx: qf.Ctx, reg: qu.Registry, curve: _Curve, tl: float, ccy: str, sid: str, name: str, group: str, mode: str, k: int):
        self.curve = curve
        want = {"OIS:" + t for t in SHORT_OUTRIGHTS}
        cands = [_Cand(inst, _ser(inst.pts(), lambda a, b, p=inst.per_cu: (b - a) * 100.0 * p), tl, -1)
                 for inst in reg.tradeable("TRY OIS") if inst.key in want and len(getattr(inst, "quote", ())) == 1]
        super().__init__(sid, name, group, mode, k, ccy, cands, "" if cands else "TRY OIS vadelerinin geçmişi yok")

    def feats(self, c: _Cand, day: str) -> Optional[Dict[str, Any]]:
        i = c.pay.at(day)
        if i is None or i < MOM_DAYS:
            return None
        sd = c.pay.sigma(i)
        cr = self.curve.receive(c.key, c.pay.days[i])
        if sd is None or cr is None:
            return None
        mom = -(c.pay.vals[i] - c.pay.vals[i - MOM_DAYS]) * 100.0
        cv = cr / (sd * math.sqrt(WEEK))
        return {"carry": cr, "cv": cv, "mom": mom, "sigma": sd, "parts": [cv, mom], "cu": -cr}


class _Pkg(_Book):
    """The TRY OIS spreads (or flies) of the registry, each its own way."""

    def __init__(self, ctx: qf.Ctx, reg: qu.Registry, curve: _Curve, tl: float, ccy: str, prefix: str, sid: str, name: str, group: str,
                 mode: str, k: int):
        self.curve = curve
        cands = [_Cand(inst, _ser(inst.pts(), lambda a, b, p=inst.per_cu: (b - a) * p), tl, 1)
                 for inst in reg.tradeable("TRY OIS") if inst.key.startswith(prefix)]
        super().__init__(sid, name, group, mode, k, ccy, cands, "" if cands else "spread / fly'ların vadeleri yok")

    def feats(self, c: _Cand, day: str) -> Optional[Dict[str, Any]]:
        i = c.pay.at(day)
        if i is None or i < MOM_DAYS:
            return None
        sd = c.pay.sigma(i)
        cu = 0.0
        for key, w in c.inst.dv01w.items():
            cr = self.curve.receive(key, c.pay.days[i])
            if cr is None:
                return None
            cu -= w * cr                                     # (the up side pays where the weight is +, receives where −)
        if sd is None:
            return None
        cv = cu / (sd * math.sqrt(WEEK))
        mom = c.pay.vals[i] - c.pay.vals[i - MOM_DAYS]
        return {"carry": cu, "cv": cv, "mom": mom, "sigma": sd, "parts": [cv, mom], "cu": cu}


class _Dibs(_Book):
    """The DİBS RV list's fixed-coupon bonds: carry + roll, cheapness against the curve fit, momentum."""

    def __init__(self, ctx: qf.Ctx, reg: qu.Registry, curve: _Curve, tl: float, ccy: str, sid: str, name: str, group: str, mode: str, k: int):
        self.curve = curve
        fit = reg.tables.get("dibsfv") if isinstance(reg.tables.get("dibsfv"), dict) else {}
        resid = fit.get("resid") if isinstance(fit.get("resid"), dict) else {}
        cands = []
        for inst in reg.tradeable("DİBS"):
            res = sorted(resid.get(inst.isin) or [])
            if not res:
                continue
            cands.append(_Cand(inst, _ser(inst.pts(), lambda a, b, p=inst.per_cu: (b - a) * 100.0 * p), tl, -1,
                               resid=([d for d, _ in res], [v for _, v in res])))
        self._model: Dict[str, List[Tuple[float, float]]] = {}
        why = "" if cands else ("DİBS eğri uyumunun kalıntıları yok (Eğri Adil Değeri)" if reg.tradeable("DİBS") else "DİBS geçmişi yok")
        super().__init__(sid, name, group, mode, k, ccy, cands, why)

    def model_curve(self, day: str) -> List[Tuple[float, float]]:
        """The close's fitted curve as the bonds read it: (years to maturity, yield − residual), by maturity."""
        hit = self._model.get(day)
        if hit is None:
            pts = []
            for c in self.cands:
                y = _asof(c.pay.days, c.pay.vals, day)
                r = _asof(c.x["resid"][0], c.x["resid"][1], day)
                if y is not None and r is not None:
                    pts.append(((c.inst.bond.maturity - _d(day)).days / 365.0, y - r / 100.0))
            hit = self._model[day] = sorted(pts)
        return hit

    def feats(self, c: _Cand, day: str) -> Optional[Dict[str, Any]]:
        i = c.pay.at(day)
        if i is None or i < MOM_DAYS or (c.inst.bond.maturity - _d(day)).days < qu.DIBS_MIN_DAYS + 7:
            return None
        sd = c.pay.sigma(i)
        rd, rv = c.x["resid"]
        j = bisect.bisect_right(rd, day) - 1
        if sd is None or j < MIN_RESID - 1 or (_d(day) - _d(rd[j])).days > STALE_DAYS:
            return None
        win = rv[max(0, j - RESID_WINDOW + 1):j + 1]
        rsd = qm.stdev(win)
        if not rsd:
            return None
        cheap = (rv[j] - sum(win) / len(win)) / rsd
        y = c.pay.vals[i]
        f = self.curve.floating(day)
        if f is None:
            return None
        try:
            p, dp = c.inst.bond.price(y / 100.0, qc.next_weekday(_d(day)), c.inst.conv)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        if not p or dp >= 0:
            return None
        years = (c.inst.bond.maturity - _d(day)).days / 365.0
        rolled = qf._interp(self.model_curve(day), max(0.0, years - H_YEARS))
        carry = (y - f) * 100.0 * H_YEARS / (-dp / p) + ((y - rv[j] / 100.0 - rolled) * 100.0 if rolled is not None else 0.0)
        carry *= c.inst.per_cu                                   # (bp of the desk's DV01, as its P&L)
        cv = carry / (sd * math.sqrt(WEEK))
        mom = -(y - c.pay.vals[i - MOM_DAYS]) * 100.0
        return {"carry": carry, "cv": cv, "cheap": cheap, "mom": mom, "sigma": sd, "parts": [cv, cheap, mom], "cu": -carry}


def books(ctx: qf.Ctx, reg: qu.Registry) -> List[_Book]:
    """The six sets on a registry, in ``SETS``' order."""
    usd, tl = reg.dv01()
    money, ccy = (tl, "TL") if tl else (usd, "USD")
    try:
        paths = reg.paths()
    except Exception:  # noqa: BLE001 - no meeting path: TLREF at the close
        paths = {}
    curve = _Curve(ctx, paths)
    out: List[_Book] = []
    for sid, name, group, mode, k in SETS:
        if sid == "g10":
            out.append(_G10(ctx, reg, sid, name, group, mode, k))
        elif sid == "vol":
            out.append(_Vol(ctx, reg, sid, name, group, mode, k))
        elif sid == "ois":
            out.append(_Ois(ctx, reg, curve, money, ccy, sid, name, group, mode, k))
        elif sid in ("spread", "fly"):
            out.append(_Pkg(ctx, reg, curve, money, ccy, "OISS:" if sid == "spread" else "OISF:", sid, name, group, mode, k))
        else:
            out.append(_Dibs(ctx, reg, curve, money, ccy, sid, name, group, mode, k))
    return out


# ---------------------------------------------------------------------------------------------- the family
def _stats(weeks: List[Dict[str, Any]], book: _Book, try_per: Dict[str, Optional[float]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The weeks as the backtest's trades and their summary (``quantbt.summarize``: weeks, hit rate, Sharpe …)."""
    trades = []
    for w in weeks:
        tp = try_per.get(book.ccy)
        trades.append({"sid": "%s:%s" % (FAMILY, book.sid), "family": FAMILY, "type": book.name, "entry_day": w["day"], "exit_day": w["end"],
                       "dir": 1, "entry": None, "exit": None, "outcome": "süre", "held": w["held"], "pnl": w["pnl"], "unit": book.ccy,
                       "pnl_sigma": w["r"], "pnl_try": w["pnl"] * tp if tp else None, "expression": w["text"]})
    first, last = (weeks[0]["day"], weeks[-1]["end"]) if weeks else (None, None)
    st = qbt.summarize(trades, first, last)
    rs = [w["r"] for w in weeks]
    st.update({"first": first, "last": last, "mean_r": sum(rs) / len(rs) if rs else None, "sd_r": qm.stdev(rs) if len(rs) >= 2 else None})
    return trades, st


def _zhist(days: Sequence[str], zs: Dict[str, Dict[str, float]], key: str) -> List[Optional[float]]:
    """An instrument's score day by day: the one of the last rebalance up to that close (None before it was ranked)."""
    rebal = sorted(zs)
    out: List[Optional[float]] = []
    for d in days:
        i = bisect.bisect_right(rebal, d) - 1
        out.append(zs[rebal[i]].get(key) if i >= 0 else None)
    return out


def _level_text(v: Optional[float], inst: Any) -> str:
    if v is None:
        return "—"
    if inst.fx:
        return qf._th(v, qf.fx_digits(v))
    return qf._level_text(v, inst.unit, inst.digits)


def plan_line(sg: Dict[str, Any], head: str, exp_money: Optional[float], ccy: str, stats: Dict[str, Any], model: str) -> str:
    """A line in the plan's format: "SAT USDJPY spot · 1,2 mn USD · giriş 150,250 · hedef 149,900 · stop 151,800 ·
    beklenen +2,1 bin USD · isabet %58 (87) · model: Carry + momentum · G10 spot sepeti" - its prices the instrument's
    (an FX line's the pair's), its money the line's own size's."""
    px = sg.get("px")
    if px:
        p = lambda v: qf._th(v, px["digits"]) if v is not None else "—"                   # noqa: E731
        ent, tgt, stp = p(px.get("entry")), p(px.get("target")), p(px.get("stop"))
    else:
        lv = lambda v: qf._level_text(v, sg.get("unit") or "", sg.get("digits") or 2)       # noqa: E731
        ent, tgt, stp = lv(sg.get("entry")), lv(sg.get("target")), lv(sg.get("stop"))
    hit = ("isabet %%%s (%d)" % (qf._g((stats.get("hit") or 0.0) * 100.0, 0), stats["trades"]) if stats.get("trades")
           else "isabet — (0)")
    return " · ".join([head, "giriş " + ent, "hedef " + tgt, "stop " + stp, "beklenen " + qf._money(exp_money, ccy), hit, "model: " + model])


def _lines(book: _Book, walk: Dict[str, Any], stats: Dict[str, Any], ctx: qf.Ctx, nxt: _dt.date,
           lv: Optional[Dict[str, Any]] = None) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """The monitors of a set's instruments - the basket's legs are its lines - and the set's table: its basket's card
    (legs, sizes, the week's expected P&L, target, stop, the backtest, the next rebalance) and its ranking.  ``lv``: the
    basket's calibrated levels (``quantlevels``: k and m in its weekly σ, the record at them) - each leg's target and
    stop the basket's multiples of its own weekly σ, its expectancy the basket's share by its σ; without them the old
    rule (the backtest's mean week, 2σ against)."""
    cur = walk["current"]
    model = "%s · %s" % (qu.FAMILIES[FAMILY][0], book.name)
    lv = lv or {"ok": False, "why": "seviye kalibrasyonu yok"}
    out: Dict[str, Any] = {"id": book.sid, "name": book.name, "group": book.group, "mode": book.mode, "k": book.k, "ccy": book.ccy,
                           "cols": book.cols, "note": NOTES[book.sid], "ok": cur is not None, "next": nxt.isoformat(), "next_text": _day_tr(nxt),
                           "backtest": {k: stats.get(k) for k in ("trades", "hits", "hit", "sharpe", "max_dd", "avg", "avg_sigma", "first", "last",
                                                                   "mean_r", "sd_r")},
                           "rows": [], "legs": [], "basket": None, "model": model,
                           "levels": dict({k: lv.get(k) for k in ("ok", "k", "m", "rr", "hit", "exp", "n", "oos", "scope", "held", "why")},
                                          text=qf.levels_text(dict(lv, rule="given") if lv.get("ok") else lv))}
    if cur is None:
        n = len(book.cands)
        out["why"] = book.why or ("geçmiş yetersiz: en az %d enstrümanın %d kapanışı gerekli (%d enstrüman var)" % (book.min_n, MOM_DAYS + 1, n))
        return [], out
    day = cur["day"]
    cal = bool(lv.get("ok"))
    if cal:
        k_b, m_b = float(lv["k"]), float(lv["m"])
        exp_b = float(lv["exp"]) * cur["risk"] if lv.get("exp") is not None else None
        stats_line = {"hit": lv.get("hit"), "trades": lv.get("n") or 0}
        # (every leg's levels: the basket's multiples, its record - make_signal's "given": the leg's own target and stop)
        leg_lv = {"ok": True, "rule": "given", "k": k_b, "m": m_b, "rr": m_b / k_b, "hit": lv.get("hit"), "exp": lv.get("exp"),
                  "n": lv.get("n"), "oos": lv.get("oos"), "oos_n": lv.get("oos_n"), "scope": lv.get("scope"), "held": lv.get("held"),
                  "family": FAMILY, "group": book.group, "month": lv.get("month")}
    else:
        k_b, m_b = STOP_SIGMA, None
        m_r = stats.get("mean_r") if (stats.get("trades") or 0) >= MIN_WEEKS else None
        exp_b = m_r * cur["risk"] if m_r is not None else None
        stats_line = dict(stats)
        leg_lv = lv
    tot_w = sum(leg["sigma_w"] for leg in cur["legs"]) or 1.0
    last = book.calendar[-1] if book.calendar else day
    held = bisect.bisect_right(book.calendar, last) - bisect.bisect_right(book.calendar, day)
    so_far_b = 0.0
    mons: List[qf.Monitor] = []
    for row in sorted(cur["rows"], key=lambda r: r["rank"]):
        c: _Cand = row["cand"]
        inst = c.inst
        side = row["side"]
        k = row.get("k", 1.0)
        sid = "%s:%s:%s" % (FAMILY, book.sid, c.key)
        disp = {"key": c.key, "label": c.label, "tier": inst.tier, "rank": row["rank"], "n": len(cur["rows"]), "composite": row["composite"],
                "zs": row["zs"], "z": row["z"], "carry": row.get("carry"), "cv": row.get("cv"), "mom": row.get("mom"), "cheap": row.get("cheap"),
                "iv": row.get("iv"), "rv": row.get("rv"), "sid": sid, "side": side, "way": row["side_c"], "verb": inst.verb(side) if side else "",
                "size": inst.size_text(k) if side else ""}
        out["rows"].append(disp)
        info = {"version": book.name, "model": model, "set": book.sid, "formed": day, "next": nxt.isoformat(), "rank": row["rank"],
                "of": len(cur["rows"]), "composite": row["composite"]}
        common = dict(zfn=lambda lv, live, z=row["z"]: z, zvalues=_zhist(inst.days, walk["z"], c.key), mode="drift", follows=True,
                      entry=1.0, score_name="sıra", ungated=True, note=NOTES[book.sid], info=info)
        if not side:
            mons.append(inst.monitor(sid, FAMILY, k=1.0, hold=WEEK, **common))
            continue
        # ---- a leg: its size, risk and share of the basket's week; its entry at the rebalance and P&L so far
        pu_money = row["size"] * c.money1                       # money a P&L unit of the leg
        i0, i1 = c.pay.at(day), c.pay.at(last)
        so_far = side * pu_money * ((c.pay.total(i0, i1) if i0 is not None and i1 is not None else 0.0) + (row.get("cu") or 0.0) * held / WEEK)
        so_far_b += so_far
        exp_i = exp_b * row["sigma_w"] / tot_w if exp_b is not None else None
        stop_i = k_b * row["sigma_w"]                            # (the basket's stop multiple of the leg's own weekly σ)
        tgt_i = m_b * row["sigma_w"] if cal else None            # (... and its target multiple)
        factor = inst.pnl()[1] or 1.0
        lvl = inst.now()
        line = inst.line(side, k)
        cu_live = None
        if not inst.fx:
            cw = inst.carry_week()
            cu_live = cw * inst.per_cu if cw is not None else None
            if cu_live is None and book.sid in ("ois", "spread", "fly", "dibs"):
                f_last = book.feats(c, last)
                cu_live = f_last.get("cu") if f_last else None
            elif book.sid == "vol":
                f_last = book.feats(c, last)
                if f_last:
                    iv, rv = f_last["iv"], f_last["rv"]
                    cu_live = WEEK * (rv * rv - iv * iv) / (126.0 * iv) if iv else None       # (theta + gamma of a week, long vol)
        kw: Dict[str, Any] = {"levels": leg_lv}
        if exp_i is not None:
            e_pu = exp_i / pu_money
            carry_h = side * (cu_live or 0.0) * WEEK / 5.0 if not inst.fx else 0.0
            kw.update(fcast=side * (e_pu - carry_h) / factor, reward=(tgt_i / pu_money if cal else max(e_pu, 0.0)) / factor)
        elif cal:
            kw["reward"] = tgt_i / pu_money / factor
        kw["risk"] = stop_i / pu_money / factor
        if cu_live is not None:
            kw["carry_up"] = cu_live
        entry = _asof(c.lvl.days, c.lvl.vals, day)

        def thesis(sg: Dict[str, Any], line: str = line, exp_i: Optional[float] = exp_i, row: Dict[str, Any] = row, entry: Optional[float] = entry,
                   inst: Any = inst, stats_line: Dict[str, Any] = stats_line, label: str = c.label) -> str:
            head = plan_line(sg, line, exp_i, book.ccy, stats_line, model)
            why = "%s %d. / %d (bileşik %s) · sepet %s kapanışında kuruldu (giriş %s), sonraki dengeleme %s kapanışı" % (
                label, row["rank"], len(cur["rows"]), qf._sg(row["composite"], 2), _d(day).strftime("%d.%m.%Y"), _level_text(entry, inst), _day_tr(nxt))
            return "%s. %s." % (head, why)

        mons.append(inst.monitor(sid, FAMILY, k=k, hold=WEEK, expression=line, thesis=thesis, **dict(common, **kw)))
        leg = dict(disp, line=line, k=k, usd=row.get("usd"), entry=entry, last=_asof(c.lvl.days, c.lvl.vals, last), level=lvl, kind=inst.kind,
                   per_cu=inst.per_cu, fx=bool(inst.fx), unit=inst.unit, digits=inst.digits, pu_money=pu_money, sigma_w=row["sigma_w"],
                   exp=exp_i, stop=-stop_i, target=tgt_i, so_far=so_far,
                   carry_week=(cu_live * side * pu_money) if cu_live is not None else None, ccy=book.ccy)
        out["legs"].append(leg)
    signed = sum(leg["side"] * (leg["usd"] if book.sid == "g10" else leg["k"]) * (leg["cand"].orient if book.sid == "g10" else 1)
                 for leg in cur["legs"])
    # the basket's card: its levels in its own (diversified) weekly σ - Ödül / risk the basket's
    out["basket"] = {"formed": day, "formed_text": _day_tr(_d(day)), "last": last, "held": held, "risk": cur["risk"], "exp": exp_b,
                     "target": (m_b * cur["risk"]) if cal else (max(exp_b, 0.0) if exp_b is not None else None),
                     "stop": -k_b * cur["risk"], "rr": (m_b / k_b) if cal else None, "so_far": so_far_b,
                     "net": signed, "net_unit": {"g10": "USD", "vol": "$ vega"}.get(book.sid, "$ DV01"), "legs": len(cur["legs"])}
    return mons, out


@qu.family(FAMILY, own_backtest=True)
def run(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """Every set's walk forward, this week's baskets and their lines; the table of the page and of the backtest."""
    t0 = time.perf_counter()
    usdtry = ctx.usdtry()
    try_per = {"TL": 1.0, "TRY": 1.0, "USD": usdtry}
    mons: List[qf.Monitor] = []
    sets: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    timing: Dict[str, float] = {}
    walks = []
    for book in books(ctx, reg):
        t1 = time.perf_counter()
        walk = book.walk(ctx.holidays)
        tr, st = _stats(walk["weeks"], book, try_per)
        walks.append((book, walk, tr, st))
        timing[book.sid] = round((time.perf_counter() - t1) * 1000.0, 1)
    # the baskets' levels (quantlevels): every week a trade - its daily P&L in its own ex-ante weekly σ -, calibrated per
    # group (TRY OIS's three sets pooled), month by month on the weeks that had ended before
    t1 = time.perf_counter()
    paths = [{"family": FAMILY, "group": book.group, "sid": "%s:%s" % (FAMILY, book.sid), "entry_day": w["day"], "end_day": w["end"],
              "path_sigma": w["path"], "carry_sigma": 0.0, "carry_in": True, "sigma": w["risk"], "unit": book.ccy, "try": try_per.get(book.ccy)}
             for book, walk, _, _ in walks for w in walk["weeks"] if w.get("path")]
    levels = qlv.calibrate(paths, FAMILY, ctx.today_iso)
    timing["levels"] = round((time.perf_counter() - t1) * 1000.0, 1)
    for book, walk, tr, st in walks:
        nxt = next_rebalance(ctx.today, book.calendar, ctx.holidays)
        m, tab = _lines(book, walk, st, ctx, nxt, levels.line(book.group))
        tab["weeks"] = [{k: w[k] for k in ("day", "end", "pnl", "risk", "r", "held", "text")} for w in walk["weeks"]]
        mons.extend(m)
        sets.append(tab)
        trades.extend(tr)
    first = min((t["entry_day"] for t in trades), default=None)
    last = max((t["exit_day"] for t in trades), default=None)
    table = {"ok": True, "today": ctx.today_iso, "sets": sets, "ms": round((time.perf_counter() - t0) * 1000.0, 1), "timing": timing,
             "backtest": {"trades": trades, "first": first, "last": last}, "levels": levels.to_json()}
    return mons, table


# ---------------------------------------------------------------------------------------------- the page
def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "Carry + momentum" reads: each set's ranking and basket with the legs' P&L so far now (the
    monitors' levels: live), the family's lines, its backtest per set."""
    from .quant import _clean
    raw = (fit.get("tables") or {}).get(FAMILY) or {}
    tab = {k: x for k, x in raw.items() if k != "backtest"}
    sets = []
    for s in raw.get("sets") or ():
        s = dict(s)
        legs = []
        so_far = 0.0 if s.get("legs") else None
        for leg in s.get("legs") or ():
            leg = {k: x for k, x in leg.items() if k != "cand"}
            m = fit["mons"].get(leg.get("sid") or "")
            now = m.level if m is not None and m.level is not None else leg.get("level")
            add = 0.0
            if now is not None and leg.get("last") is not None:
                ch = qf.change(leg["kind"], leg["last"], now)
                add = leg["side"] * leg["pu_money"] * (ch or 0.0) * (leg.get("per_cu") or 1.0)
            leg["now"] = now
            leg["so_far_now"] = (leg.get("so_far") or 0.0) + add
            so_far = (so_far or 0.0) + leg["so_far_now"]
            if m is not None:
                leg["z"] = m.z
            legs.append(leg)
        s["legs"] = legs
        if s.get("basket"):
            s["basket"] = dict(s["basket"], so_far_now=so_far)
        sets.append(s)
    tab["sets"] = sets
    base["sira"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["family"] == FAMILY]
    base["settings"] = fit["cfg"]
    # (the series the sets read: the G10 spots, their 3M points and ATM 3M vols, every OIS tenor, TLREF)
    keys = {"TLREF"} | {r["key"] for s in sets for r in s.get("rows") or ()}
    keys |= {pre % p for p in qu.G10_PAIRS for pre in ("FX:%s", "FXP:%s:3M", "FXV:%s")}
    base["coverage"] = [c for c in fit.get("coverage") or () if c["key"] in keys or c["key"].startswith("OIS:")]
    base["errors"] = {k: e for k, e in ((v.get("tables") or {}).get("errors") or {}).items() if k == FAMILY}
    return _clean(base)
