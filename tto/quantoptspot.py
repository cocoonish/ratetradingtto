"""Opsiyon → spot: the option market's signals turned into spot trades - AL / SAT a pair's spot where its 25-delta risk
reversals, their divergence from the spot and the ATM vol moving with them have led the spot out of sample; the
butterfly, which says nothing of the direction, scales the levels.

**Pairs** (``PAIRS``): the seven G10 pairs (the universe's spot lines, group G10 spot) and USDTRY / EURTRY where their
options are kept - the registry keeps those two spots as inputs, so their line is a spot line of the Offshore group
here ("offshore limiti").  The quotes by the universe's keys (``quantopt.key``): ATM 1M / 3M, 25D RR 1M / 3M, 25D BF 3M -
the series the history keeps already (the G10 universe's; USDTRY's of the Opsiyon page; EURTRY has none and its row
says so).  Nothing here asks Bloomberg.

**Timing.**  Option and spot closes are both the day's close.  A close's features read the quotes as of that close (a
quote's last close within a week of it) and the spot's closes up to it; its target the spot's next five closes.  Every
z is against the window of the 250 closes before the close (at least 60): today's - live quotes and spot, else the last
closes - against the same window as the last close's own next row would be.

**Signals** (``SIGNALS``) - candidates for the next week's move of the base currency, each a z:
  drr1, drr3   the 25D RR's (1M, 3M) change over five closes ÷ the σ of its five-close changes
  rrz          the 25D RR 3M's level against its year (1M where there is no 3M)
  div          the RR - spot divergence: the front RR's (1M, else 3M) five-close change less β × the spot's (β: its daily
               change on the spot's, over the window) ÷ the σ of that residual - the options moved, the spot did not
  vrr          the front ATM vol's five-close rise (its z, only up) × the front RR's change z: vol bid together with the
               skew - a stressed directional move
and the 25D BF 3M's level z (tails priced rich), which has no direction: it scales the levels (below).

**Target** ``y``: the next five closes' excess return of a long - the spot's log move and the carry of the holding (the
forwards: ``Ctx.fx_carry_days``) - over the option-implied week, ATM 1M (3M without it) × √(5/252), clipped at ±4.

**Model**: a ridge regression of y on the five signals over every pair together, partially pooled - a pair's
coefficient is a shared one plus a deviation of its own, the deviations penalised ten times as hard (``L_SHARED``,
``L_PAIR``): what holds everywhere is learnt from all pairs, a pair's own from its rows; the pair dummies (``L_INT``)
take each pair's mean (a carry trade's drift) and stay out of the forecast - μ, the expected move in σ of the week, is
the option signals' part alone.  A coefficient's sign is the direction the data chose: + "momentum" (calls bid → spot
up), − "ters" (the move came back).  P(up) = Φ(c·μ ÷ s): s the fit's residual σ, c the pair's calibration - the slope of
what came on what was forecast over its out-of-sample rows known so far, within 0 – 1 (every pair's while it has fewer
than ``MIN_CAL``): a pair whose forecasts never came true stays near a coin's however loud its options are, and the
expected move is c·μ too.

**Walk-forward**, monthly as the ML family: each calendar month's model is fitted on every row whose label was known
before the month began and predicts only that month's rows; today is this month's model's.  The normal equations grow
month by month (one pass over the rows; a fit is a small linear solve).  Per pair: the hit rate of μ's sign against
the excess return's and the log-loss, over the out-of-sample days with a known label; tests = days ÷ 5 (the labels
overlap).  Per signal - pooled and per pair -, its own record: the direction its training rows chose (the within-pair
slope's sign), played out of sample on every day it says something (hit rate, mean move in σ; it leads by the same
55 % / 40 rule) and on the days it is past ±1, and the information coefficient.  That table says which option signals
lead the spot, and which way.

**The line** - only where the pair's out-of-sample hit rate ≥ the desk's ``model_hit`` (55 %) with ≥ ``model_min_tests``
(40) tests, the existing model families' rule, and P past the entry (z(p) = (p − 0,5) ÷ 0,05): "25D RR 1A 1 haftada
+1,2 vol (z +2,1; USD call'ları pahalandı), spot henüz gelmedi → AL USDJPY spot · 1,1 mn USD · giriş 150,250 · hedef
152,630 · stop 148,350 · beklenen +3,4 bin USD · isabet %57 (64)" - the signal that moved today's forecast most in the
trade's direction, in the desk's words, then the plan's line.  Levels from the option-implied week σ = ATM 1M × √(5/252)
× the BF factor (% of spot): entry the spot now, target 1,25 σ, stop 1 σ (R/R 1,25), held five days, expected c·μ × σ
- until the levels calibrated on the family's past trades (``tto.quantlevels``) come with the signal (``sg["levels"]``:
make_signal sets the target and stop at its multiples of the same σ, the expected P&L at its expectancy): the line and
the card then tell its multiples, hit rate and expectancy, never these.  The BF factor is evidence too: how much bigger
the weeks were when the wings were rich - the training rows' y² on the BF z, its slope kept past two standard errors
(the overlap counted) - √(1 + b·z) within 0,85 – 1,5 (1 without such evidence); a factor above 1 also lowers the line's
rank (composite ÷ factor).  Size: the desk's weekly 1σ risk (``optspot_risk_usd``) over a unit's (1 mn of the base) 1σ
week in USD, two significant figures, 0,1 – 10.

**Backtest** (``own_backtest``: the walk-forward is the backtest): every out-of-sample day the probability crossed the
entry (it had not the day before, no position open) opens a trade at that close, closed at its target or stop (on the
closes) or the fifth close, P&L with the carry - quantbt's trade format plus its path: the spot's move in the trade's
favour at each of the five closes after the entry in σ of its week (``path_sigma``, the whole horizon whatever the exit),
the path's last close (``end_day``) and MAE / MFE over it (``mae_sigma``, ``mfe_sigma``) - the levels' calibration
(``tto.quantlevels``) reads them as they are.

**Page** ``quant-optspot``, a tab of FX: every pair with today's RR / BF / ATM moves and z's, the forecast, whether it
prints and its record; every signal's out-of-sample record, pooled and per pair.  Everything is keyed by the pair's code
and the series' keys, nothing by a sheet's row.
"""
from __future__ import annotations

import datetime as _dt
import math
import statistics
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import quantbt as qbt
from . import quantfam as qf
from . import quantopt as qopt
from . import quantuniv as qu

FAMILY = "optspot"
#: the page (a tab of FX: ``tto.quant.MENU``) and the view of ``/api/quant/optspot``
PAGES = (("quant-optspot", "Opsiyon → spot"),)
TAB = ("quant-optspot", "Opsiyon → spot")
VIEWS = {"optspot": "quant-optspot"}

#: the desk's setting (tto.quant takes it into its own): the weekly 1σ risk every line is sized to
DEFAULTS: Dict[str, Any] = {"optspot_risk_usd": 10000.0}
LIMITS: Dict[str, Tuple[float, float, type]] = {"optspot_risk_usd": (100.0, 1e7, float)}
LABELS: Dict[str, str] = {"optspot_risk_usd": "Opsiyon → spot · haftalık 1σ risk (USD, satır başına)"}

# ---------------------------------------------------------------------------------------------- the pairs
PAIRS = tuple(qu.G10_PAIRS) + ("USDTRY", "EURTRY")
#: the pairs of the Offshore group: the registry keeps their spots as inputs, this family's line is a spot of that group
OFFSHORE = ("USDTRY", "EURTRY")
#: the quotes read per pair: (name, kind, tenor) by the universe's keys
QUOTES = (("atm1", "ATM", "1M"), ("atm3", "ATM", "3M"), ("rr1", "RR25", "1M"), ("rr3", "RR25", "3M"), ("bf3", "BF25", "3M"))
TENOR = {"atm1": "1A", "atm3": "3A", "rr1": "1A", "rr3": "3A", "bf3": "3A"}

# ---------------------------------------------------------------------------------------------- the signals
SIGNALS: Tuple[Tuple[str, str], ...] = (
    ("drr1", "25D RR 1A · 1 haftalık değişim"),
    ("drr3", "25D RR 3A · 1 haftalık değişim"),
    ("rrz", "25D RR 3A · seviye (1 yıla göre)"),
    ("div", "RR – spot ayrışması (1 hafta)"),
    ("vrr", "ATM vol artışı × RR yönü"),
)
NAMES = tuple(s[0] for s in SIGNALS)
LABEL_OF = dict(SIGNALS)
J = len(NAMES)

# ---------------------------------------------------------------------------------------------- the model's settings
HORIZON = 5                     # business days: the label's horizon, the line's holding
YEAR = 252.0
WIN = 250                       # the window of every z (closes before the close)
MIN_WIN = 60                    # ... at least
REAL_WIN = 60                   # the realised σ that stands in for a missing ATM vol
STALE_DAYS = 7                  # a quote older than this (calendar days) at a close is missing
CLIP = 4.0                      # |signal| at most
Y_CLIP = 4.0                    # |label| at most (σ of the week)
ACTIVE = 1.0                    # |signal| from which a day counts in the signal's own record
MIN_TRAIN = 300                 # rows of known label (every pair together) a month's model needs
MIN_PAIR = 60                   # rows of known label a pair's own direction of a signal needs
MIN_CAL = 100                   # out-of-sample rows of known label a pair's own calibration needs (else every pair's)
L_SHARED = 20.0                 # ridge: the shared coefficients
L_PAIR = 200.0                  # ... a pair's deviation from them
L_INT = 1.0                     # ... the pair dummies
T_MULT = 1.25                   # target: σ of the week
S_MULT = 1.0                    # stop: σ of the week (R/R 1,25)
F_RANGE = (0.85, 1.5)           # the BF factor's bounds
Z_SCALE = 0.05                  # z(p) = (p − 0,5) ÷ 0,05: the model families' score (p 60 % is the desk's entry 2,0)
K_RANGE = (0.1, 10.0)           # the size, in the desk's unit (1 mn of the base)
#: the closes a pair needs before its record can hold: the first change, the window, 40 tests of five days
MIN_CLOSES = HORIZON + MIN_WIN + 40 * HORIZON
SETTINGS = {"horizon": HORIZON, "window": WIN, "min_window": MIN_WIN, "min_train": MIN_TRAIN, "l_shared": L_SHARED, "l_pair": L_PAIR,
            "t_mult": T_MULT, "s_mult": S_MULT, "f_min": F_RANGE[0], "f_max": F_RANGE[1], "active": ACTIVE, "retrain": "aylık"}

NOTE = ("Risk reversal'ın haftalık değişimi (1A, 3A), seviyesi (1 yıla göre z), spotla ayrışması ve ATM vol artışıyla birlikte hareketi: "
        "bütün paritelerde birlikte, ortak katsayı + paritenin kendi sapması (ridge, aylık yeniden eğitim, her ay yalnız o ay başlamadan "
        "bilinenle). Hedef: önümüzdeki 5 kapanışın carry'li getirisi ÷ opsiyonların ima ettiği 1 haftalık σ (ATM 1A × √(5/252)). "
        "z(p) = (p − 0,5) ÷ 0,05; hedef 1,25σ, stop 1σ (BF çarpanıyla), 5 gün.")

_ND = statistics.NormalDist()


def _num(v: Any) -> Optional[float]:
    return v if type(v) is float and math.isfinite(v) else (float(v) if type(v) is int else None)


def _clip(v: Optional[float], c: float = CLIP) -> Optional[float]:
    return None if v is None else (c if v > c else (-c if v < -c else v))


def _sign(x: Optional[float]) -> int:
    return 0 if not x else (1 if x > 0 else -1)


def _month(day: str) -> str:
    return day[:8] + "01"


def _round2(k: float) -> float:
    """Two significant figures: 1,43 → 1,4; 0,372 → 0,37 (a size the desk says)."""
    if not k or k <= 0 or not math.isfinite(k):
        return k
    e = math.floor(math.log10(k)) - 1
    return round(k / 10.0 ** e) * 10.0 ** e


def quote_keys(pair: str) -> Dict[str, str]:
    """The history's keys of a pair's quotes: ``{atm1, atm3, rr1, rr3, bf3}``."""
    return {name: qopt.key(pair, kind, tenor) for name, kind, tenor in QUOTES}


# ---------------------------------------------------------------------------------------------- series with gaps
def _asof(days: Sequence[str], dates: Sequence[_dt.date], pts: Sequence[Tuple[str, float]]) -> List[Optional[float]]:
    """A series' value as of each day: its last close on or before it, within ``STALE_DAYS`` (else ``None``)."""
    out: List[Optional[float]] = []
    j, last = 0, None
    for d, dt in zip(days, dates):
        while j < len(pts) and pts[j][0] <= d:
            if _num(pts[j][1]) is not None:
                last = pts[j]
            j += 1
        out.append(last[1] if last is not None and (dt - _dt.date.fromisoformat(last[0])).days <= STALE_DAYS else None)
    return out


def _diff(xs: Sequence[Optional[float]], k: int) -> List[Optional[float]]:
    return [xs[i] - xs[i - k] if i >= k and xs[i] is not None and xs[i - k] is not None else None for i in range(len(xs))]


def _psum(vals: Sequence[Optional[float]]) -> List[float]:
    out, s = [0.0], 0.0
    for v in vals:
        if v is not None:
            s += v
        out.append(s)
    return out


class _Win(object):
    """A series' window statistics before each close (prefix sums): count, mean and σ of the closes [i − w, i − 1]."""

    def __init__(self, xs: Sequence[Optional[float]], w: int = WIN):
        self.w = w
        self.c = _psum([1.0 if v is not None else None for v in xs])
        self.s1 = _psum(xs)
        self.s2 = _psum([v * v if v is not None else None for v in xs])

    def stats(self, i: int) -> Tuple[int, Optional[float], Optional[float]]:
        lo, hi = max(0, i - self.w), min(i, len(self.c) - 1)
        if hi <= lo:
            return 0, None, None
        n = int(round(self.c[hi] - self.c[lo]))
        if n < MIN_WIN:
            return n, None, None
        a, b = self.s1[hi] - self.s1[lo], self.s2[hi] - self.s2[lo]
        m = a / n
        var = (b - a * a / n) / (n - 1)
        return n, m, (math.sqrt(var) if var > 1e-18 else None)

    def z(self, v: Optional[float], i: int, demean: bool = True) -> Optional[float]:
        """``v`` against the window before close ``i`` - a level's z (``demean``), or a move over the σ of the moves."""
        if v is None:
            return None
        _, m, sd = self.stats(i)
        if sd is None:
            return None
        return ((v - m) if demean else v) / sd


class _Div(object):
    """The RR - spot divergence before each close: β of the daily RR change on the daily spot change over the window,
    and the σ of the five-close residual (RR's change − β × the spot's) with that β."""

    def __init__(self, r1: Sequence[Optional[float]], s1: Sequence[Optional[float]], r5: Sequence[Optional[float]],
                 s5: Sequence[Optional[float]]):
        ok1 = [a is not None and b is not None for a, b in zip(r1, s1)]
        ok5 = [a is not None and b is not None for a, b in zip(r5, s5)]
        g = lambda xs, ok: [x if k else None for x, k in zip(xs, ok)]                   # noqa: E731
        p = lambda ok, fn: _psum([fn(i) if k else None for i, k in enumerate(ok)])       # noqa: E731
        self.c1 = _psum([1.0 if k else None for k in ok1])
        self.sx, self.sy = _psum(g(s1, ok1)), _psum(g(r1, ok1))
        self.sxx = p(ok1, lambda i: s1[i] * s1[i])
        self.sxy = p(ok1, lambda i: s1[i] * r1[i])
        self.c5 = _psum([1.0 if k else None for k in ok5])
        self.rr5 = p(ok5, lambda i: r5[i] * r5[i])
        self.rs5 = p(ok5, lambda i: r5[i] * s5[i])
        self.ss5 = p(ok5, lambda i: s5[i] * s5[i])

    def z(self, r5: Optional[float], s5: Optional[float], i: int) -> Optional[float]:
        if r5 is None or s5 is None:
            return None
        lo, hi = max(0, i - WIN), min(i, len(self.c1) - 1)
        n = self.c1[hi] - self.c1[lo]
        m = self.c5[hi] - self.c5[lo]
        if n < MIN_WIN or m < MIN_WIN:
            return None
        sx, sy = self.sx[hi] - self.sx[lo], self.sy[hi] - self.sy[lo]
        vxx = (self.sxx[hi] - self.sxx[lo]) - sx * sx / n
        beta = ((self.sxy[hi] - self.sxy[lo]) - sx * sy / n) / vxx if vxx > 1e-18 else 0.0
        ee = (self.rr5[hi] - self.rr5[lo]) - 2.0 * beta * (self.rs5[hi] - self.rs5[lo]) + beta * beta * (self.ss5[hi] - self.ss5[lo])
        if ee <= 1e-18:
            return None
        return (r5 - beta * s5) / math.sqrt(ee / m)


# ---------------------------------------------------------------------------------------------- a pair's history
class Row(object):
    """One close of a pair: its signals (``x``, ``None`` where a quote is missing), BF z, the week's σ (% of spot) and -
    once known - the excess return of the next five closes (% and ``y`` in σ) and the day it is known."""

    __slots__ = ("p", "i", "day", "end", "x", "bfz", "sig", "ret", "y")

    def __init__(self, p: int, i: int, day: str, x: List[Optional[float]], bfz: Optional[float], sig: float):
        self.p, self.i, self.day, self.x, self.bfz, self.sig = p, i, day, x, bfz, sig
        self.end: Optional[str] = None
        self.ret: Optional[float] = None
        self.y: Optional[float] = None


class Hist(object):
    """One pair: its spot's closes, its quotes as of each, every close's signals, σ and label - and what today's row
    needs (the windows before today)."""

    def __init__(self, inst: qu.FxSpot, ctx: qf.Ctx, p: int):
        self.inst, self.ctx, self.p = inst, ctx, p
        self.pair = inst.pair
        self.key = inst.key
        self.keys = quote_keys(self.pair)
        pts = [(d, v) for d, v in inst.pts() if v and v > 0]
        self.days = [d for d, _ in pts]
        self.S = [v for _, v in pts]
        self.n = n = len(pts)
        self.dates = [_dt.date.fromisoformat(d) for d in self.days]
        self.lnS = [math.log(v) for v in self.S]
        self.have = {name: len(ctx.pts(key)) for name, key in self.keys.items()}
        self.q: Dict[str, List[Optional[float]]] = {name: (_asof(self.days, self.dates, ctx.pts(key)) if self.have[name] else [None] * n)
                                                    for name, key in self.keys.items()}
        self.carry = _asof(self.days, self.dates, sorted(ctx.fx_carry_days(self.pair).items()))
        enough = lambda *names: next((x for x in names if self.have[x] >= MIN_WIN), None)       # noqa: E731
        self.rr_front = enough("rr1", "rr3")            # (the divergence and the vol move read the front RR)
        self.rr_level = enough("rr3", "rr1")            # (the level's z: the 3M's year)
        self.atm_front = enough("atm1", "atm3")         # (the week's σ and the vol move: the 1M ATM)
        self.rows: List[Row] = []
        self._build()

    def _build(self) -> None:
        n, q, H = self.n, self.q, HORIZON
        lnS = self.lnS
        self.s1 = [(lnS[i] - lnS[i - 1]) * 100.0 if i >= 1 else None for i in range(n)]
        self.s5 = [(lnS[i] - lnS[i - H]) * 100.0 if i >= H else None for i in range(n)]
        self.d5 = {name: _diff(q[name], H) for name in ("rr1", "rr3", "atm1", "atm3")}
        self.zm = {name: _Win(d) for name, d in self.d5.items()}
        self.zl = _Win(q[self.rr_level]) if self.rr_level else None
        self.zb = _Win(q["bf3"])
        self.zs = _Win(self.s1, REAL_WIN)
        f = self.rr_front
        self.dv = _Div(_diff(q[f], 1), self.s1, self.d5[f], self.s5) if f else None
        for i in range(H, n):
            x = self._signals(i, {name: q[name][i] for name in q}, {name: self.d5[name][i] for name in self.d5}, self.s5[i])
            if x is None:
                continue
            sig = self._sigma(i, q[self.atm_front][i] if self.atm_front else None)
            if sig is None:
                continue
            r = Row(self.p, i, self.days[i], x, self.zb.z(q["bf3"][i], i), sig)
            if i + H < n and self.carry[i] is not None:
                r.end = self.days[i + H]
                r.ret = (lnS[i + H] - lnS[i]) * 100.0 + self.carry[i] * (self.dates[i + H] - self.dates[i]).days / 365.0
                r.y = _clip(r.ret / sig, Y_CLIP)
            self.rows.append(r)

    def _signals(self, i: int, cur: Dict[str, Optional[float]], ch: Dict[str, Optional[float]], s5: Optional[float]
                 ) -> Optional[List[Optional[float]]]:
        """The five signals of close ``i`` (today: ``i`` = n) from its quotes ``cur``, their five-close changes ``ch``
        and the spot's ``s5`` - each against the window before ``i``; ``None`` without a RR change."""
        drr1 = self.zm["rr1"].z(ch["rr1"], i, demean=False)
        drr3 = self.zm["rr3"].z(ch["rr3"], i, demean=False)
        f = self.rr_front
        div = self.dv.z(ch[f], s5, i) if f and self.dv is not None else None
        if drr1 is None and drr3 is None and div is None:
            return None
        rrz = self.zl.z(cur[self.rr_level], i) if self.zl is not None else None
        vrr = None
        if f and self.atm_front:
            za = self.zm[self.atm_front].z(ch[self.atm_front], i, demean=False)
            zf = drr1 if f == "rr1" else drr3
            if za is not None and zf is not None:
                vrr = max(za, 0.0) * zf
        return [_clip(drr1), _clip(drr3), _clip(rrz), _clip(div), _clip(vrr)]

    def _sigma(self, i: int, atm: Optional[float]) -> Optional[float]:
        """The option-implied week, % of spot: the ATM vol × √(5/252); without one, the spot's realised σ of the last
        60 closes × √5."""
        if atm is not None and atm > 0:
            return atm * math.sqrt(HORIZON / YEAR)
        _, _, sd = self.zs.stats(i)
        return sd * math.sqrt(HORIZON) if sd else None

    def now(self, level: Optional[float], live: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Today's row: the quotes now (live, else as of the last close), the spot ``level``, every signal against the
        windows before today, the BF z and the week's σ - with the moves behind them for the desk's words."""
        n, H = self.n, HORIZON
        if n < H + MIN_WIN or level is None or not level > 0:
            return None
        b = n - H
        cur = {}
        for name, key in self.keys.items():
            v = _num(live.get(key))
            cur[name] = v if v is not None else self.q[name][n - 1]
        ch = {name: cur[name] - self.q[name][b] if cur[name] is not None and self.q[name][b] is not None else None for name in cur}
        s5 = (math.log(level) - self.lnS[b]) * 100.0
        x = self._signals(n, cur, ch, s5)
        if x is None:
            return None
        atm = cur[self.atm_front] if self.atm_front else None
        sig = self._sigma(n, atm)
        if sig is None:
            return None
        return {"x": x, "bfz": self.zb.z(cur["bf3"], n), "sig": sig, "cur": cur, "ch": ch, "s5": s5, "level": level, "atm": atm,
                "rr_front": self.rr_front, "rr_level": self.rr_level, "atm_front": self.atm_front}


# ---------------------------------------------------------------------------------------------- the model
class Model(object):
    """One month's fit: the coefficients (shared, each pair's deviation, the pairs' dummies), the residual σ, each
    pair's calibration, each signal's direction as the training rows chose it - pooled and per pair - and the BF's
    scale of the week."""

    __slots__ = ("month", "theta", "s", "n", "signs", "psigns", "bf_ratio", "bf_t", "cal", "cal_n")

    def __init__(self, month: str, theta: List[float], s: float, n: int, signs: List[int], psigns: List[List[int]],
                 bf_ratio: float, bf_t: Optional[float], cal: List[float], cal_n: List[int]):
        self.month, self.theta, self.s, self.n = month, theta, s, n
        self.signs, self.psigns, self.bf_ratio, self.bf_t = signs, psigns, bf_ratio, bf_t
        self.cal, self.cal_n = cal, cal_n

    def coef(self, p: int) -> List[float]:
        """Pair ``p``'s coefficients: the shared ones plus its own deviations (σ of the week a σ of the signal)."""
        th = self.theta
        return [th[j] + th[J + p * J + j] for j in range(J)]

    def mu(self, p: int, x: Sequence[Optional[float]]) -> float:
        """The forecast: the option signals' part of next week's move, σ of the week (its direction the line's)."""
        c = self.coef(p)
        return sum(c[j] * x[j] for j in range(J) if x[j] is not None)

    def prob(self, p: int, mu: float) -> float:
        """P(up) of pair ``p``'s forecast ``mu``: Φ(c·μ ÷ s) - c how much of its forecasts came true out of sample."""
        return _ND.cdf(self.cal[p] * mu / self.s) if self.s > 0 else 0.5

    def f_bf(self, z: Optional[float]) -> float:
        """The BF factor of the week: √(1 + b·z), b the training rows' (1 where they gave no evidence)."""
        if z is None or not self.bf_ratio:
            return 1.0
        return min(F_RANGE[1], max(F_RANGE[0], math.sqrt(max(0.25, 1.0 + self.bf_ratio * z))))


class _Rec(object):
    """A signal's out-of-sample record, played in the direction its training rows chose: every day it says something
    (hits, mean move in σ), the days it is strong (|z| ≥ ``ACTIVE``), the information coefficient."""

    __slots__ = ("n", "hits", "move", "na", "ha", "ma", "ic")

    def __init__(self):
        self.n, self.hits, self.move = 0, 0, 0.0
        self.na, self.ha, self.ma = 0, 0, 0.0
        self.ic = [0, 0.0, 0.0, 0.0, 0.0, 0.0]          # n, Σa, Σy, Σa², Σy², Σay

    def add(self, sign: int, f: float, y: float) -> None:
        if not sign or y == 0.0:
            return
        a = sign * f
        ic = self.ic
        ic[0] += 1
        ic[1] += a
        ic[2] += y
        ic[3] += a * a
        ic[4] += y * y
        ic[5] += a * y
        if not f:
            return
        d = sign * (1 if f > 0 else -1)
        hit = 1 if d * y > 0 else 0
        self.n += 1
        self.hits += hit
        self.move += d * y
        if abs(f) >= ACTIVE:
            self.na += 1
            self.ha += hit
            self.ma += d * y

    def out(self) -> Dict[str, Any]:
        n, sa, sy, saa, syy, say = self.ic
        ic = None
        if n >= 10:
            va, vy = saa - sa * sa / n, syy - sy * sy / n
            ic = (say - sa * sy / n) / math.sqrt(va * vy) if va > 1e-18 and vy > 1e-18 else None
        return {"days": self.n, "tests": self.n // HORIZON, "hit": self.hits / float(self.n) if self.n else None,
                "move": self.move / self.n if self.n else None, "strong_days": self.na,
                "strong_hit": self.ha / float(self.na) if self.na else None, "strong_move": self.ma / self.na if self.na else None, "ic": ic}


def walk(hists: Sequence[Hist], today: str) -> Dict[str, Any]:
    """The monthly walk-forward over every pair together: each month from the first with ``MIN_TRAIN`` rows of known
    label before it to today's, its model fitted on those rows, predicting that month's rows - ``{"models": {month:
    Model}, "preds": [{day: (μ, p, BF factor)} per pair], "signals": [the pooled record per signal], "psignals": [per
    pair, per signal], "months": [...]}``."""
    from . import quantmath as qm
    NP = len(hists)
    K = J * (1 + NP) + NP
    xtx = [[0.0] * K for _ in range(K)]
    xty = [0.0] * K
    tot = {"n": 0, "yy": 0.0}
    uni = [[[0, 0.0, 0.0, 0.0, 0.0] for _ in range(J)] for _ in range(NP)]       # per pair, signal: n, Σf, Σy, Σfy, Σf²
    bf = [0, 0.0, 0.0, 0.0, 0.0, 0.0]                                            # n, Σz, Σu, Σzu, Σz², Σu² (u = y²)
    rows = [r for h in hists for r in h.rows]
    known = sorted((r for r in rows if r.y is not None), key=lambda r: (r.end, r.p, r.day))
    by_month: Dict[str, List[Row]] = {}
    for r in rows:
        by_month.setdefault(_month(r.day), []).append(r)
    months = sorted(set(by_month) | {_month(today)})
    preds: List[Dict[str, Tuple[float, float, float]]] = [{} for _ in range(NP)]
    models: Dict[str, Model] = {}
    recs = [_Rec() for _ in range(J)]
    precs = [[_Rec() for _ in range(J)] for _ in range(NP)]
    out_months: List[Dict[str, Any]] = []
    lam = [L_SHARED] * J + [L_PAIR] * (NP * J) + [L_INT] * NP
    # the calibration: each pair's out-of-sample forecasts against what came, once their label is known (n, Σμy, Σμ²)
    cal = [[0, 0.0, 0.0] for _ in range(NP + 1)]                                  # (the last: every pair's)
    pending: List[Tuple[str, int, float, float]] = []

    def calib(p: int) -> float:
        """How much of a forecast came true: the slope of y on μ through 0 over the out-of-sample rows known so far,
        within 0 – 1 - the pair's own from ``MIN_CAL`` rows, else every pair's, else 1 (the model's word)."""
        for c, least in ((cal[p], MIN_CAL), (cal[NP], MIN_TRAIN)):
            if c[0] >= least and c[2] > 1e-12:
                return min(1.0, max(0.0, c[1] / c[2]))
        return 1.0

    def add(r: Row) -> None:
        y = r.y
        xs = [v if v is not None else 0.0 for v in r.x]
        idx = list(range(J)) + [J + r.p * J + j for j in range(J)] + [J + NP * J + r.p]
        vals = xs + xs + [1.0]
        for a, ia in enumerate(idx):
            va = vals[a]
            if not va:
                continue
            row = xtx[ia]
            for b, ib in enumerate(idx):
                vb = vals[b]
                if vb:
                    row[ib] += va * vb
            xty[ia] += va * y
        tot["n"] += 1
        tot["yy"] += y * y
        for j, f in enumerate(r.x):
            if f is not None:
                u = uni[r.p][j]
                u[0] += 1
                u[1] += f
                u[2] += y
                u[3] += f * y
                u[4] += f * f
        if r.bfz is not None:
            uu = y * y
            bf[0] += 1
            bf[1] += r.bfz
            bf[2] += uu
            bf[3] += r.bfz * uu
            bf[4] += r.bfz * r.bfz
            bf[5] += uu * uu

    def fit(M: str) -> Optional[Model]:
        a = [row[:] for row in xtx]
        for i in range(K):
            a[i][i] += lam[i]
        theta = qm.solve(a, xty)
        if theta is None:
            return None
        fitted = sum(theta[i] * sum(xtx[i][k] * theta[k] for k in range(K) if xtx[i][k]) for i in range(K))
        sse = tot["yy"] - 2.0 * sum(t * v for t, v in zip(theta, xty)) + fitted
        s = math.sqrt(max(sse / tot["n"], 1e-12))
        # each signal's direction as these rows chose it: the slope's sign within each pair (pooled: summed over them)
        num = [[u[3] - u[1] * u[2] / u[0] if u[0] >= 2 else 0.0 for u in uni[p]] for p in range(NP)]
        signs = [_sign(sum(num[p][j] for p in range(NP))) for j in range(J)]
        psigns = [[_sign(num[p][j]) if uni[p][j][0] >= MIN_PAIR else 0 for j in range(J)] for p in range(NP)]
        # the BF's scale: the weeks' y² on the BF z, the slope kept past two standard errors of n ÷ 5 independent weeks
        ratio, t = 0.0, None
        n = bf[0]
        if n >= MIN_TRAIN // 2:
            sxx = bf[4] - bf[1] * bf[1] / n
            sxy = bf[3] - bf[1] * bf[2] / n
            syy = bf[5] - bf[2] * bf[2] / n
            if sxx > 1e-12:
                slope = sxy / sxx
                icpt = (bf[2] - slope * bf[1]) / n
                res = max(syy - slope * sxy, 0.0)
                se = math.sqrt(res / max(n - 2, 1) / sxx) * math.sqrt(HORIZON) if res > 0 else None
                t = slope / se if se else None
                kept = slope * qf.shrink(t) if t is not None else 0.0
                ratio = kept / icpt if icpt > 1e-9 else 0.0
        return Model(M, theta, s, tot["n"], signs, psigns, ratio, t, [calib(p) for p in range(NP)], [cal[p][0] for p in range(NP)])

    k = 0
    for M in months:
        while k < len(known) and known[k].end < M:
            add(known[k])
            k += 1
        left = []
        for end, p, mu, y in pending:
            if end < M:
                for c in (cal[p], cal[NP]):
                    c[0] += 1
                    c[1] += mu * y
                    c[2] += mu * mu
            else:
                left.append((end, p, mu, y))
        pending = left
        if tot["n"] < MIN_TRAIN:
            continue
        model = fit(M)
        if model is None:
            continue
        models[M] = model
        test = by_month.get(M) or []
        for r in test:
            mu = model.mu(r.p, r.x)
            preds[r.p][r.day] = (mu, model.prob(r.p, mu), model.f_bf(r.bfz))
            if r.y is not None:
                pending.append((r.end, r.p, mu, r.y))
                for j, f in enumerate(r.x):
                    if f is not None:
                        recs[j].add(model.signs[j], f, r.y)
                        precs[r.p][j].add(model.psigns[r.p][j], f, r.y)
        out_months.append({"month": M, "train": tot["n"], "test": len(test), "s": model.s, "bf_ratio": model.bf_ratio})
    return {"models": models, "preds": preds, "signals": [r.out() for r in recs], "psignals": [[r.out() for r in pr] for pr in precs],
            "months": out_months}


def record(rows: Sequence[Row], preds: Dict[str, Tuple[float, float, float]]) -> Dict[str, Any]:
    """A pair's out-of-sample record: hit rate of μ's sign against the excess return's, log-loss, the share of rises,
    days and independent tests (days ÷ 5) of its predicted rows with a known label."""
    pts = [(preds[r.day], r.y) for r in rows if r.y is not None and r.y != 0.0 and r.day in preds]
    n = len(pts)
    if not n:
        return {"days": 0, "tests": 0, "hit": None, "log_loss": None, "base": None}
    from . import quantmath as qm
    hits = sum(1 for (mu, _, _), y in pts if mu * y > 0)
    return {"days": n, "tests": n // HORIZON, "hit": hits / float(n), "log_loss": qm.log_loss([pr[1] for pr, _ in pts], [1 if y > 0 else 0 for _, y in pts]),
            "base": sum(1 for _, y in pts if y > 0) / float(n)}


# ---------------------------------------------------------------------------------------------- the backtest
def trades_of(h: Hist, preds: Dict[str, Tuple[float, float, float]], entry: float, models: Optional[Dict[str, Model]] = None
              ) -> List[Dict[str, Any]]:
    """The walk-forward's out-of-sample days as trades, with the live rules: a day the probability is past the entry
    and was not the day before (no position open) opens one at that close in μ's direction - target 1,25 σ, stop 1 σ of
    its week (the BF factor in), on the closes, else the fifth close; P&L the spot's move with the carry of the days
    held (%).  Each with its path: the spot's move in its favour at each of the five closes after the entry, σ of its
    week (``path_sigma`` - the whole horizon, whatever the exit), the path's last close (``end_day``), MAE and MFE over
    it, and the signal behind it (its month's model's) - what the levels' calibration (``tto.quantlevels``) reads; a
    trade whose horizon goes past the last close is still open: none."""
    models = models or {}
    inst = h.inst
    usdtry = _asof(h.days, h.dates, h.ctx.pts("FX:USDTRY")) if h.pair != "USDTRY" else h.S
    out: List[Dict[str, Any]] = []
    by_i = {r.i: r for r in h.rows}
    prev_live = False
    busy = -1
    H = HORIZON
    for i, d in enumerate(h.days):
        pr = preds.get(d)
        live = pr is not None and abs(pr[1] - 0.5) / Z_SCALE >= entry
        if live and not prev_live and i >= busy and i + H < h.n and i in by_i:
            r = by_i[i]
            mu, p, f = pr
            s = 1 if mu > 0 else -1
            sig = r.sig * f
            path = [s * (h.lnS[i + k] - h.lnS[i]) * 100.0 / sig for k in range(1, H + 1)]
            u, why = i + H, "süre"
            for k, x in enumerate(path, 1):
                if x >= T_MULT:
                    u, why = i + k, "hedef"
                    break
                if x <= -S_MULT:
                    u, why = i + k, "stop"
                    break
            c = h.carry[i] or 0.0
            carry = s * c * (h.dates[u] - h.dates[i]).days / 365.0
            move = path[u - i - 1] * sig
            pnl = move + carry
            out.append({"sid": "%s:%s" % (FAMILY, inst.key), "family": FAMILY, "type": inst.label, "entry_day": d, "exit_day": h.days[u],
                        "end_day": h.days[i + H],                 # (the path's last close: the levels' month cut uses it)
                        "dir": s, "entry": h.S[i], "exit": h.S[u], "outcome": why, "held": u - i, "pnl": pnl, "unit": "%",
                        "pnl_sigma": move / sig, "pnl_try": _try_of(h, i, pnl, usdtry[i]),
                        "expression": "%s %s" % (inst.verb(s), inst.label), "p": p, "mu": mu, "sigma": sig, "f_bf": f,
                        "target_sigma": T_MULT, "stop_sigma": S_MULT, "horizon": H, "path_sigma": path,
                        "mae_sigma": max(0.0, -min(path)), "mfe_sigma": max(0.0, max(path)), "carry": carry,
                        "driver": _driver_of(models[_month(d)], h.p, r.x, s) if _month(d) in models else None})
            busy = u
        prev_live = live
    return out


def _try_of(h: Hist, i: int, pnl: float, usdtry: Optional[float]) -> Optional[float]:
    """A trade's P&L (% of 1 mn of the base) in TRY at its entry day's rates: the quote currency's money - TRY itself,
    USD at that day's USDTRY, a USD-based pair's quote through its own spot."""
    quote = h.pair[3:]
    money = pnl / 100.0 * qf.FX_NOTIONAL * h.S[i]                     # (in the quote currency)
    if quote == "TRY":
        return money
    if not usdtry:
        return None
    if quote == "USD":
        return money * usdtry
    return money * usdtry / h.S[i] if h.pair[:3] == "USD" else None


def _driver_of(model: Model, p: int, x: Sequence[Optional[float]], s: int) -> Optional[str]:
    """The signal that moved a forecast most in the trade's direction."""
    c = model.coef(p)
    cand = [(s * c[j] * x[j], j) for j in range(J) if x[j] is not None]
    if not cand:
        return None
    v, j = max(cand)
    return NAMES[j] if v > 0 else None


# ---------------------------------------------------------------------------------------------- the desk's words
def _pct(p: Optional[float]) -> str:
    return qf._g(p * 100.0, 0) if p is not None else "—"


def _cut(p: float) -> str:
    """A share as a per cent to one decimal, cut not rounded (54,98 % is below 55 %: "54,9")."""
    return qf._g(math.floor(p * 1000.0) / 10.0, 1)


def _way(sign: int) -> str:
    """A direction the data chose for a signal: "momentum" (the spot followed the options), "ters" (it went back)."""
    return "momentum" if sign > 0 else ("ters" if sign < 0 else "—")


def _sp(v: Optional[float], d: int = 2) -> str:
    """A signed per cent the Turkish way: "+%0,12", "-%0,80"."""
    if v is None:
        return "—"
    txt = qf._g(abs(v), d)
    return ("+" if v > 0 else "-" if v < 0 else "") + "%" + txt if any(c in "123456789" for c in txt) else "%" + txt


def phrase(name: str, d: Dict[str, Any], pair: str) -> str:
    """A signal of today's row as the desk says it: "25D RR 1A 1 haftada +1,2 vol (z +2,1; USD call'ları pahalandı)"."""
    base = pair[:3]
    x = d["x"][NAMES.index(name)]
    ch, cur = d["ch"], d["cur"]

    def side(v: Optional[float]) -> str:
        return "%s %s'ları" % (base, "call" if (v or 0.0) > 0 else "put")

    if name in ("drr1", "drr3"):
        q = "rr1" if name == "drr1" else "rr3"
        return "25D RR %s 1 haftada %s vol (z %s; %s pahalandı)" % (TENOR[q], qf._sg(ch[q], 1), qf._sg(x, 1), side(ch[q]))
    if name == "rrz":
        q = d["rr_level"]
        return "25D RR %s %s vol, son bir yılına göre %s (z %s; %s her zamankinden pahalı)" % (
            TENOR[q], qf._sg(cur[q], 1), "yüksek" if x > 0 else "düşük", qf._sg(x, 1), side(x))
    if name == "div":
        q = d["rr_front"]
        return "25D RR %s 1 haftada %s vol oynadı, spot ise %s (ayrışma z %s)" % (TENOR[q], qf._sg(ch[q], 1), _sp(d["s5"], 2), qf._sg(x, 1))
    a, q = d["atm_front"], d["rr_front"]
    return "ATM %s vol 1 haftada %s vol, 25D RR %s %s vol: gerilimli %s (z %s)" % (
        TENOR[a], qf._sg(ch[a], 1), TENOR[q], qf._sg(ch[q], 1), "yükseliş" if (ch[q] or 0.0) > 0 else "düşüş", qf._sg(x, 1))


# ---------------------------------------------------------------------------------------------- a line
class Line(object):
    """One pair after a fit: its rows, the walk-forward's predictions and record, today's model, its backtest trades,
    its size - and, scored, today's forecast (``now``)."""

    def __init__(self, h: Hist, wf: Dict[str, Any], model: Optional[Model], cfg: Dict[str, Any]):
        self.h, self.inst, self.key, self.pair = h, h.inst, h.inst.key, h.pair
        self.ctx = h.ctx
        self.today = h.ctx.today_iso                         # the fit's day: its monitor scores live only then
        self.preds: Dict[str, Tuple[float, float, float]] = wf["preds"][h.p]
        self.model = model
        self.rec = record(h.rows, self.preds)
        self.hit_min, self.tests_min = float(cfg["model_hit"]), int(cfg["model_min_tests"])
        self.valid = bool(self.rec["hit"] is not None and self.rec["hit"] >= self.hit_min and self.rec["tests"] >= self.tests_min)
        self.months = sorted({_month(d) for d in self.preds})
        self.entry = float(cfg["entry_z"])
        self.trades = trades_of(h, self.preds, self.entry, wf["models"])
        self.bt = qbt.summarize(self.trades, self.trades[0]["entry_day"], self.trades[-1]["exit_day"]) if self.trades else qbt.summarize([], None, None)
        self.now: Optional[Dict[str, Any]] = None
        live = self.ctx.derive_live(self.ctx.live)
        first = self.score(self.inst.now(live), live)
        risk = cfg.get("optspot_risk_usd") or DEFAULTS["optspot_risk_usd"]
        self.k, self.risk1 = 1.0, None
        if first is not None:
            try:
                m1 = self.inst.money(first["sigma"], 1.0, live)
            except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                m1 = None
            if m1:
                self.risk1 = abs(m1)
                self.k = _round2(min(max(float(risk) / self.risk1, K_RANGE[0]), K_RANGE[1]))

    def score(self, level: Optional[float], live: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Today's forecast with the quotes and the spot now: the signals, μ (σ of the week), P(up), the BF factor, the
        week's σ with it (% of spot), each signal's part of μ - kept as ``now`` (the card reads it)."""
        if self.model is None:
            self.now = None
            return None
        d = self.h.now(level, live)
        if d is None:
            self.now = None
            return None
        m, p = self.model, self.h.p
        c = m.coef(p)
        mu = m.mu(p, d["x"])
        f = m.f_bf(d["bfz"])
        d.update({"coef": c, "contrib": [c[j] * d["x"][j] if d["x"][j] is not None else 0.0 for j in range(J)], "mu": mu,
                  "cal": m.cal[p], "mu_cal": m.cal[p] * mu, "p": m.prob(p, mu), "f": f, "sigma": d["sig"] * f})
        self.now = d
        return d

    def driver(self, d: Dict[str, Any], s: int) -> Dict[str, str]:
        """The signal behind the trade - the largest part of μ in its direction - in the desk's words, and what goes
        with it: "spot henüz gelmedi" (the RR moved its way, the spot not yet), "geçmişte bu hareket tersine döndü" (the
        data chose against the move)."""
        cand = [(s * d["contrib"][j], j) for j in range(J) if d["x"][j] is not None]
        v, j = max(cand) if cand else (0.0, 0)
        name = NAMES[j]
        tail = ""
        if d["coef"][j] < 0:
            tail = ", geçmişte bu uç seviye geri döndü" if name == "rrz" else ", geçmişte bu hareket tersine döndü"
        else:
            dv = d["x"][NAMES.index("div")]
            if dv is not None and s * dv >= ACTIVE and d["coef"][NAMES.index("div")] >= 0:
                tail = ", spot henüz gelmedi"
        return {"name": name, "text": phrase(name, d, self.pair), "tail": tail}

    def why(self, d: Dict[str, Any], s: int, k: int = 3) -> List[Dict[str, Any]]:
        """The ``k`` signals that moved today's forecast most: name, label, value (z), part of μ (σ; + toward a rise) and
        the desk's words."""
        top = sorted((j for j in range(J) if d["x"][j] is not None), key=lambda j: (-abs(d["contrib"][j]), j))[:k]
        return [{"name": NAMES[j], "label": LABEL_OF[NAMES[j]], "value": d["x"][j], "effect": d["contrib"][j], "coef": d["coef"][j],
                 "text": phrase(NAMES[j], d, self.pair), "with": (d["contrib"][j] > 0) == (s > 0)} for j in top if d["contrib"][j] != 0.0]

    def status(self, d: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """(prints, why not) of the line now."""
        h, r = self.h, self.rec
        if h.n < MIN_CLOSES:
            return False, "geçmiş kısa (%d kapanış; en az %d)" % (h.n, MIN_CLOSES)
        rr, atm = max(h.have["rr1"], h.have["rr3"]), max(h.have["atm1"], h.have["atm3"])
        if min(rr, atm) < MIN_CLOSES:
            return False, "opsiyon geçmişi kısa (25D RR %d, ATM %d kapanış; en az %d)" % (rr, atm, MIN_CLOSES)
        if not any(x is not None for x in h.carry):
            return False, "forward puanı yok: carry'si bilinmeyen getiri yazılmaz"
        if not self.months:
            return False, "eğitim için etiketli satır az (paritelerin hepsinde en az %d)" % MIN_TRAIN
        if r["tests"] < self.tests_min:
            return False, "örneklem dışı test az (%d < %d)" % (r["tests"], self.tests_min)
        if (r["hit"] or 0.0) < self.hit_min:
            return False, "örneklem dışı isabet %%%s < %%%s" % (_cut(r["hit"] or 0.0), qf._g(self.hit_min * 100.0, 0))
        if self.model is None:
            return False, "bu ayın modeli yok"
        if d is None:
            return False, "bugünkü opsiyon kotası yok"
        if abs(d["p"] - 0.5) / Z_SCALE < self.entry:
            return False, "olasılık %%%s < eşik %%%s" % (_cut(max(d["p"], 1.0 - d["p"])), qf._g((0.5 + Z_SCALE * self.entry) * 100.0, 0))
        return True, ""


def _no_quotes(ctx: qf.Ctx, pair: str) -> str:
    """Why a pair has no line before its history is read: no spot, no option quotes kept (``""``: it has them)."""
    keys = quote_keys(pair)
    kept = lambda name: keys[name] in ctx.meta or keys[name] in ctx.series        # noqa: E731
    if not (kept("rr1") or kept("rr3")) or not (kept("atm1") or kept("atm3")):
        return "opsiyon serisi yok: %s'nin ATM / 25D RR kotası tutulmuyor" % pair
    return ""


def _instrument(reg: qu.Registry, pair: str) -> Tuple[Optional[qu.FxSpot], str]:
    """The pair's spot line: the universe's (G10), or a spot of the Offshore group (USDTRY, EURTRY: the registry keeps
    their spots as inputs)."""
    key = "FX:" + pair
    if pair in OFFSHORE:
        if key not in reg.ctx.meta and key not in reg.ctx.series:
            return None, "spot serisi yok"
        return qu.FxSpot(reg, pair, group="Offshore"), ""
    inst = reg.get(key)
    if not isinstance(inst, qu.FxSpot):
        return None, reg.missing.get(key) or "spot serisi yok"
    return inst, ""


# ---------------------------------------------------------------------------------------------- the monitors
def _monitor(line: Line, cfg: Dict[str, Any]) -> qf.Monitor:
    """The line's monitor: z(p) of today's forecast with the quotes now; target 1,25 σ, stop 1 σ of the week (the BF
    factor in), the expected move μ σ, held five days; the card's words in ``finish``."""
    inst = line.inst
    ctx = inst.ctx
    rec = line.rec
    m = inst.monitor("%s:%s" % (FAMILY, inst.key), FAMILY, k=line.k, zfn=None, mode="drift", follows=True, hold=float(HORIZON),
                     score_name="z(p)", regime={"tag": None}, reward=None, risk=None, fcast=None, pnl_sd=None, note=NOTE,
                     sample={"ok": True, "text": "örneklem dışı isabet %%%s (%d test, log-loss %s) ≥ %%%s, en az %d test" % (
                         _pct(rec["hit"]), rec["tests"], qf._g(rec["log_loss"], 3), _pct(line.hit_min), line.tests_min)},
                     info={"version": inst.label, "p": None, "hit_rate": rec["hit"], "n_test": rec["tests"], "log_loss": rec["log_loss"],
                           "valid": line.valid, "inputs": [inst.key] + list(line.h.keys.values())})

    def zfn(level: Optional[float], live: Dict[str, float]) -> Optional[float]:
        if level is None or ctx.today_iso != line.today:
            return None
        d = line.score(level, live)
        if d is None:
            return None
        sig = d["sigma"]
        m.info["p"] = d["p"]
        m.reward = level * T_MULT * sig / 100.0
        m.risk = level * S_MULT * sig / 100.0
        m.fcast = level * d["mu_cal"] * sig / 100.0          # (the calibrated forecast: what came true of such forecasts)
        m.pnl_sd = sig / math.sqrt(HORIZON)                  # (the gates' σ of the holding: the option-implied week)
        return (d["p"] - 0.5) / Z_SCALE

    m.zfn = zfn
    m.zvalues = [(line.preds[d][1] - 0.5) / Z_SCALE if d in line.preds else None for d in m.days]
    m.finish = lambda sg: _finish(line, sg)
    m.optspot = line
    return m


def levels_of(sg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The levels calibrated on the family's past trades that the signal carries (``tto.quantlevels``: make_signal
    sets ``sg["levels"]``, its target and stop already those multiples × the σ of the holding) - ``None`` where it has
    none (this family's own 1,25σ / 1σ stand)."""
    lv = sg.get("levels")
    if isinstance(lv, dict) and lv.get("ok") and lv.get("k") is not None and lv.get("m") is not None:
        return lv
    return None


def _price(sg: Dict[str, Any], which: str) -> str:
    """The line's entry / target / stop in the pair's own price (its ``px``), else the level's."""
    px = sg.get("px")
    v = px.get(which) if px is not None else sg.get(which)
    if v is None:
        return "—"
    return qf._th(v, px.get("digits") or 4) if px is not None else qf._level_text(v, sg.get("unit") or "", sg.get("digits") or 2)


def _money_line(sg: Dict[str, Any], k: float) -> str:
    """The expected P&L at the line's size in USD: the card's money is per 1 mn of the base in the quote currency."""
    mo = sg.get("money") or {}
    v = mo.get("total")
    if v is None:
        return "—"
    v *= k
    if mo.get("ccy") != "USD" and mo.get("usd_per"):
        return qf._money(v * mo["usd_per"], "USD")
    return qf._money(v, mo.get("ccy") or "")


def _finish(line: Line, sg: Dict[str, Any]) -> None:
    """make_signal's line made this family's: the option signal behind it first - "… → AL USDJPY spot · 1,1 mn USD ·
    giriş … · hedef … · stop … · beklenen … · isabet %57 (64)" -, the card's sentence with why, the rank lowered by a rich
    BF.  The levels the signal carries are told as they are: the calibrated ones (``sg["levels"]``) with their
    multiples, hit rate and expectancy - this family's own 1,25σ / 1σ and its record only where there are none."""
    d = line.now
    if d is None:
        return
    inst, rec = line.inst, line.rec
    s = int(sg["direction"])
    drv = line.driver(d, s)
    lv = levels_of(sg)
    t_mult, s_mult = (float(lv["m"]), float(lv["k"])) if lv is not None else (T_MULT, S_MULT)
    hit, n = (lv.get("hit"), int(lv.get("n") or 0)) if lv is not None else (rec["hit"], rec["tests"])
    head = "%s %s · %s" % (inst.verb(s), inst.label, inst.size_text(line.k))
    parts = [head, "giriş " + _price(sg, "entry"), "hedef " + _price(sg, "target"), "stop " + _price(sg, "stop"),
             "beklenen " + _money_line(sg, line.k), "isabet %%%s (%d)" % (_pct(hit), n)]
    text = "%s%s → %s" % (drv["text"], drv["tail"], " · ".join(parts + ([inst.tag] if inst.tag else [])))
    sg["expression"] = sg["line"] = text
    conf = min(1.0, 1.0 / d["f"]) if d["f"] else 1.0
    if conf < 1.0 and not sg.get("gated"):
        sg["composite"] = sg["composite"] * conf
        sg["parts"] = dict(sg.get("parts") or {}, bf=conf)
    why = line.why(d, s)
    sg.setdefault("info", {}).update({"why": why, "driver": drv["name"]})
    prob = d["p"] if s > 0 else 1.0 - d["p"]
    told = ["%s (%s)" % (w["text"], "lehte" if w["with"] else "aleyhte") for w in why]
    reason = (" Tahmini en çok %s etkiledi." % (", ".join(told[:-1]) + " ve " + told[-1] if len(told) > 1 else told[0])) if told else ""
    atm = "ATM %s %s vol × √(5/252)" % (TENOR.get(d["atm_front"] or "", ""), qf._g(d["atm"], 2)) if d.get("atm") else "gerçekleşen σ × √5"
    bf = ("; kanatlar (25D BF 3A z %s) ×%s" % (qf._sg(d["bfz"], 1), qf._g(d["f"], 2))) if abs(d["f"] - 1.0) > 0.005 else ""
    if lv is not None and lv.get("text"):
        # (make_signal has told the levels in the card already - their own sentence, their text: what σ is, once)
        levels = "σ, opsiyonların ima ettiği 1 haftalık hareket: %%%s (%s%s)." % (qf._g(d["sigma"], 2), atm, bf)
    elif lv is not None:
        levels = ("Seviyeler geçmiş işlemlerden, opsiyonların ima ettiği 1 haftalık σ'nın katları: σ %%%s (%s%s); hedef %sσ, stop %sσ "
                  "(isabet %%%s, %d işlem, %s; işlem başına %sσ)." % (
                      qf._g(d["sigma"], 2), atm, bf, qf._g(t_mult, 2), qf._g(s_mult, 2), _pct(hit), n,
                      "örneklem dışı" if lv.get("oos") else "örneklem içi", qf._sg(lv.get("exp"), 2)))
    else:
        levels = "Seviyeler opsiyonların ima ettiği 1 haftalık hareketten: σ %%%s (%s%s); hedef %sσ, stop %sσ." % (
            qf._g(d["sigma"], 2), atm, bf, qf._g(t_mult, 2), qf._g(s_mult, 0))
    sg["plain"] = ("Opsiyon piyasası: %s%s. Model önümüzdeki %d iş gününde %s olasılığını %%%s veriyor (yönde örneklem dışı isabet %%%s, %d test; "
                   "geçmişte tahminin ×%s'i gerçekleşti).%s %s %s" % (
                       drv["text"], drv["tail"], HORIZON, "yükseliş" if s > 0 else "düşüş", _pct(prob), _pct(rec["hit"]), rec["tests"], qf._g(d["cal"], 2), reason,
                       sg.get("plain") or "", levels))
    sg["thesis"] = "Opsiyon → spot: %s%s → %s; beklenen %s." % (drv["text"], drv["tail"], head, qf.exp_text(sg))
    sg["optspot"] = {"driver": drv["name"], "mu": d["mu"], "cal": d["cal"], "p": d["p"], "sigma": d["sigma"], "f_bf": d["f"], "bfz": d["bfz"],
                     "x": dict(zip(NAMES, d["x"])), "coef": dict(zip(NAMES, d["coef"])), "k": line.k,
                     "levels": {"source": "kalibrasyon" if lv is not None else "kendi", "target_sigma": t_mult, "stop_sigma": s_mult, "hit": hit, "n": n,
                                "exp": lv.get("exp") if lv is not None else None}}


# ---------------------------------------------------------------------------------------------- the family
class State(object):
    """The last full fit's lines (the page reads them with the quotes now)."""

    def __init__(self, ctx: qf.Ctx, lines: Dict[str, Line]):
        self.ctx, self.lines = ctx, lines
        self.today = ctx.today_iso


_STATE: Optional[State] = None


def reset() -> None:
    """Forget the last fit (tests)."""
    global _STATE
    _STATE = None


def state() -> Optional[State]:
    return _STATE


@qu.family(FAMILY, own_backtest=True)
def run(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """Every pair's history, the walk-forward over them together, a monitor for each pair whose record holds; the
    table of the page and the backtest's trades (with their paths)."""
    global _STATE
    t0 = time.perf_counter()
    hists: List[Hist] = []
    gone: Dict[str, Tuple[Optional[qu.FxSpot], str]] = {}
    errors: Dict[str, str] = {}
    for pair in PAIRS:
        inst, why = _instrument(reg, pair)
        why = why or _no_quotes(ctx, pair)
        if why:
            gone[pair] = (inst, why)
            continue
        try:
            hists.append(Hist(inst, ctx, len(hists)))
        except Exception as exc:  # noqa: BLE001 - one pair failing is its row's reason, not the family's
            errors[pair] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        time.sleep(0)                                     # (the engine thread gets the interpreter between pairs)
    t_rows = time.perf_counter()
    wf = walk(hists, ctx.today_iso)
    t_walk = time.perf_counter()
    model = wf["models"].get(_month(ctx.today_iso))
    lines: Dict[str, Line] = {}
    mons: List[qf.Monitor] = []
    for h in hists:
        line = Line(h, wf, model, cfg)
        lines[h.key] = line
        if line.valid and model is not None:
            mons.append(_monitor(line, cfg))
    trades = sorted((t for line in lines.values() for t in line.trades), key=lambda t: (t["exit_day"], t["sid"]))
    table = _table(ctx, cfg, lines, wf, model, gone, errors)
    table["backtest"] = {"trades": trades, "first": min((t["entry_day"] for t in trades), default=None),
                         "last": max((t["exit_day"] for t in trades), default=None)}
    t1 = time.perf_counter()
    table["timing"] = {"rows_ms": round((t_rows - t0) * 1000.0, 1), "walk_ms": round((t_walk - t_rows) * 1000.0, 1),
                       "total_ms": round((t1 - t0) * 1000.0, 1), "rows": sum(len(h.rows) for h in hists), "models": len(wf["models"]),
                       "pairs": len(hists)}
    _STATE = State(ctx, lines)
    return mons, table


def _row(line: Line, d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A pair's row of the page: today's quotes, their moves and the signals' z's, the forecast, whether it prints,
    its record and its backtest."""
    inst, h, rec = line.inst, line.h, line.rec
    prints, why = line.status(d)
    out: Dict[str, Any] = {"key": inst.key, "pair": line.pair, "label": inst.label, "group": inst.group, "tier": inst.tier, "tag": inst.tag,
                           "n": h.n, "rows": len(h.rows), "days": rec["days"], "tests": rec["tests"], "hit": rec["hit"], "log_loss": rec["log_loss"],
                           "base": rec["base"], "valid": line.valid, "months": len(line.months), "first": line.months[0] if line.months else None,
                           "prints": prints, "why": why, "sid": "%s:%s" % (FAMILY, inst.key) if line.valid and line.model is not None else None,
                           "trades": line.bt.get("trades"), "trade_hit": line.bt.get("hit"), "avg_sigma": line.bt.get("avg_sigma"),
                           "sharpe": line.bt.get("sharpe"), "size": inst.size_text(line.k), "k": line.k,
                           "quotes": {name: h.have[name] for name in h.keys}}
    if d is not None:
        s = _sign(d["mu"])
        drv = line.driver(d, s) if s else None
        out.update({"spot": d["level"], "atm": d["atm"], "atm_tenor": TENOR.get(d["atm_front"] or ""), "atm_ch": d["ch"].get(d["atm_front"]) if d["atm_front"] else None,
                    "rr1": d["cur"]["rr1"], "rr1_ch": d["ch"]["rr1"], "rr3": d["cur"]["rr3"], "rr3_ch": d["ch"]["rr3"], "bf": d["cur"]["bf3"],
                    "bfz": d["bfz"], "f_bf": d["f"], "sigma": d["sigma"], "s5": d["s5"], "mu": d["mu"], "cal": d["cal"], "p": d["p"],
                    "prob": max(d["p"], 1.0 - d["p"]), "side": s, "verb": inst.verb(s) if s else "", "z": (d["p"] - 0.5) / Z_SCALE,
                    "x": dict(zip(NAMES, d["x"])), "coef": dict(zip(NAMES, d["coef"])), "contrib": dict(zip(NAMES, d["contrib"])),
                    "driver": (drv["text"] + drv["tail"]) if drv else "", "driver_name": drv["name"] if drv else None})
    return out


def _table(ctx: qf.Ctx, cfg: Dict[str, Any], lines: Dict[str, Line], wf: Dict[str, Any], model: Optional[Model],
           gone: Dict[str, Tuple[Optional[qu.FxSpot], str]], errors: Dict[str, str]) -> Dict[str, Any]:
    entry = float(cfg["entry_z"])
    hit_min, tests_min = float(cfg["model_hit"]), int(cfg["model_min_tests"])
    rows = []
    for pair in PAIRS:
        key = "FX:" + pair
        line = lines.get(key)
        if line is not None:
            rows.append(_row(line, line.now))
            continue
        inst, why = gone.get(pair, (None, errors.get(pair) or "hesaplanamadı"))
        group = "Offshore" if pair in OFFSHORE else "G10 spot"
        rows.append({"key": key, "pair": pair, "label": "%s spot" % pair, "group": group, "tier": None, "tag": qu.TAGS.get(group, ""),
                     "prints": False, "why": errors.get(pair) or why, "sid": None})
    # every signal's record: pooled, and the pairs where its own holds
    hists = {line.h.p: line for line in lines.values()}
    sigs = []
    signs_hist = [m.signs for _, m in sorted(wf["models"].items())]
    for j, (name, label) in enumerate(SIGNALS):
        r = dict(wf["signals"][j]) if j < len(wf["signals"]) else _Rec().out()
        sign = model.signs[j] if model is not None else 0
        r.update({"name": name, "label": label, "sign": sign, "sign_text": _way(sign),
                  "months": len(signs_hist), "months_same": sum(1 for sg in signs_hist if sg[j] == sign) if sign else 0,
                  "coef": model.theta[j] if model is not None else None,
                  "leads": bool(r.get("hit") is not None and r["hit"] >= hit_min and r["tests"] >= tests_min)})
        pairs = []
        for p, line in sorted(hists.items()):
            pr = wf["psignals"][p][j]
            ps = model.psigns[p][j] if model is not None else 0
            pairs.append(dict(pr, pair=line.pair, sign=ps, sign_text=_way(ps), coef=model.coef(p)[j] if model is not None else None,
                              leads=bool(ps and pr["hit"] is not None and pr["hit"] >= hit_min and pr["tests"] >= tests_min)))
        r["pairs"] = pairs
        r["pairs_text"] = " · ".join("%s %s %%%s (%d)" % (x["pair"], x["sign_text"], _pct(x["hit"]), x["tests"]) for x in pairs if x["leads"])
        # (the pairs whose own rows chose the other direction this month: their sign is their own, the model's
        # deviation of theirs carries it)
        r["against"] = ["%s %s" % (x["pair"], x["sign_text"]) for x in pairs if sign and x["sign"] == -sign]
        sigs.append(r)
    fits = wf["months"]
    return {"ok": True, "rows": rows, "signals": sigs, "today": ctx.today_iso,
            "model": {"months": len(fits), "first": fits[0]["month"] if fits else None, "n": model.n if model is not None else None,
                      "s": model.s if model is not None else None, "bf_ratio": model.bf_ratio if model is not None else None,
                      "bf_t": model.bf_t if model is not None else None, "pairs": len(lines)},
            "settings": dict(SETTINGS, model_hit=hit_min, model_min_tests=tests_min, entry_z=entry, p_entry=0.5 + Z_SCALE * entry,
                             risk_usd=float(cfg.get("optspot_risk_usd") or DEFAULTS["optspot_risk_usd"])),
            "valid": sum(1 for line in lines.values() if line.valid), "lines": len(lines)}


# ---------------------------------------------------------------------------------------------- the page
def coverage_keys() -> set:
    """The series the page's coverage table lists: every pair's spot, its forward points and its quotes."""
    keys = set()
    for pair in PAIRS:
        keys.update(("FX:" + pair, "FXP:%s:3M" % pair, "FXP:%s:1M" % pair))
        keys.update(quote_keys(pair).values())
    return keys


def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "Opsiyon → spot" reads: every pair's row with the quotes now (the fit's lines rescored with the
    live values), every signal's record, the family's signals."""
    from .quant import _clean
    raw = (fit.get("tables") or {}).get(FAMILY) or {}
    tab = {k: x for k, x in raw.items() if k != "backtest"}
    st = _STATE
    ctx = fit.get("ctx")
    if st is not None and ctx is not None and st.today == fit.get("today"):          # (the lines of this day's data)
        live = ctx.derive_live(ctx.live)
        rows = []
        for r in tab.get("rows") or []:
            line = st.lines.get(r.get("key"))
            rows.append(_row(line, line.score(line.inst.now(live), live)) if line is not None else r)
        tab["rows"] = rows
    # (a line past the rule and the entry that a gate of the list holds - the FX carry buffer, no expected profit - is
    # in the list as "düşük güven": the page says so and why)
    held = {s["id"]: s["gated"] for s in v["gated"] if s["family"] == FAMILY}
    tab["rows"] = [dict(r, prints=False, why="düşük güven: " + held[r["sid"]]) if r.get("prints") and held.get(r.get("sid")) else r
                   for r in tab.get("rows") or []]
    base["optspot"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["family"] == FAMILY]
    base["settings"] = fit["cfg"]
    keys = coverage_keys()
    base["coverage"] = [c for c in fit.get("coverage") or () if c.get("key") in keys]
    base["errors"] = {k: e for k, e in ((v.get("tables") or {}).get("errors") or {}).items() if k == FAMILY}
    return _clean(base)
