"""Makine öğrenmesi: the direction of the next five business days of every line of the family's universe, by shallow
gradient-boosted trees in plain Python (no numpy on the desk machine), retrained every month and tested only on the month
after - a line prints where that out-of-sample record holds.

**Target.**  The sign of the up side's P&L over the next ``HORIZON`` closes in its own unit (``inst.verbs[0]``: AL, pay,
steepener, vol al; a rate's receive side is its down side): the level's move (roll days out: ``inst.adjusted()``), and
for an FX line - a spot, an offshore forward - the carry of the holding too (the forward points; its level is a price).
A rates line's carry + roll is not in its history (the carry engine is today's only): ``make_signal`` adds it to the
expected P&L, as for every family.

**Features** (``FEATURES``, 34 per line), each known at the line's close of the day - nothing after it:
own z over 20 / 60 / 250 closes, momentum over 5 / 21 / 63 closes (÷ σ √n), carry (FX: % a year from the forwards; a
rate: the level over TLREF; ATM vol: implied − realised), realised σ (20 closes) and its change (σ20 / σ60); the TRY OIS
curve's level / slope / curvature (2Y, 2s10s, 2s5s10s) and their 5-day changes (the same day: the curve closes with
TRY); the 1- and 5-day changes of UST 2Y / 10Y, DXY, EM FX, Brent and the CDS, TLREF's 3-month change, the next PPK
step the meeting path priced, the VİOP − OIS basis at 30 days, the 25D RR 3M (the pair's own for a G10 line, the
seven pairs' mean else) and its 5-day change - these from the day before (their close comes after TRY's: no
look-ahead); whether the holding has a month end in it, and the weekday.  A feature that is not there (a series too
short, an input missing) is a value of its own the trees route.

**Model** (``Trees``): ``TREES`` trees of depth ``DEPTH`` on the logistic loss, learning rate ``RATE``, each on
``SUBSAMPLE`` of the rows and ``COLSAMPLE`` of the features, leaves of at least ``MIN_LEAF`` rows, Newton leaf values
(``L2``); each feature cut into ``BINS`` quantiles of the training rows (+ a missing bin) - the splits are searched on
the bins' sums (a histogram per node, the larger child's by subtraction).  Seeded per line and month: the same data,
the same model.

**Walk-forward** (``walk``).  Each calendar month's model is fitted on every row whose label was known before the
month began (its fifth close before the month's first day) and predicts only that month's rows; the current month's
model is the one that trades today.  From the first month with ``MIN_TRAIN`` known rows on - with two years of closes a
year and more of out-of-sample predictions.  Hit rate and log-loss over every out-of-sample day whose label is known;
the test count is the independent 5-day periods in them (days ÷ 5: the labels overlap).  A model is kept by the
line's key, its month and a digest of its training rows (``_MODELS``): the next fit of the same data - a refresh,
another fit of the day, the backtest - fits nothing; a new close adds no model but on a month's first day; a new
month, a revised close, a backfilled series fit again exactly the months whose rows changed.  Nothing is kept by a
sheet's row or column: a PPK calendar edit, a VİOP roll, a new or matured bond moves no line's state to another line.

**The line** (only where the out-of-sample hit rate ≥ the desk's ``model_hit`` (55 %) with ≥ ``model_min_tests`` (40)
tests - the Tahmin modeli's rule - and its score past the entry: z(p) = (p − 0,5) ÷ 0,05 as that model's):
"AL EURUSD spot · 1 mn EUR · olasılık %63 · isabet %58 (52)"; target (2p − 1) × the line's mean |5-day P&L| (the
last 250 rows), stop 1,5 σ of five days, held five days; size in the desk's unit and the P&L in money through the
registry (``inst.monitor``).  Its card says what to do and why: the three features that moved this prediction most
(the trees' path contributions of today's row), in the desk's words; the log-loss beside the hit rate.  During the day
only the live features are scored again (the level, the curve): the trees are the fit's.

**Backtest** (``tto.quantbt``: every family refitted every ten days on the closes up to that day).  The refit's
lines are the walk-forward's own out-of-sample predictions of each day - nothing is fitted again -, scored with the
live rules (the probability past the entry; no 55 % gate: that gate is this record itself) and their trades kept per
line (the backtest's type).

**Page** ``quant-ml`` (a tab of Sinyaller, ``VIEWS``): every line with its out-of-sample record, whether it prints,
today's probability and the three features behind it; the features' share of the trees' gain per group.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import hashlib
import math
import random
import threading
import time
import zlib
from itertools import accumulate
from operator import itemgetter, mul
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf
from . import quantmath as qm
from . import quantopt as qopt
from . import quantuniv as qu

FAMILY = "ml"
#: the page (a tab of Sinyaller: ``tto.quant.MENU``) and the view of ``/api/quant/ml``
PAGES = (("quant-ml", "Makine öğrenmesi"),)
TAB = ("quant-ml", "Makine öğrenmesi")
VIEWS = {"ml": "quant-ml"}

# ---------------------------------------------------------------------------------------------- the model's settings
#: the trees: shallow and shrunk - on two years of daily rows of noise, depth 3, L2 1, leaves of 20 learned the noise
#: (log-loss 0,82 out of sample, probabilities ±0,17 from 50 %); depth 2 with leaves of 30 and L2 30 keep a planted
#: driver's 71 % and give noise 0,72 (±0,08) - and fit in two thirds of the time (tests/test_quantml.py)
HORIZON = 5                     # business days: the label's horizon, the line's holding
TREES = 50
DEPTH = 2
RATE = 0.1
SUBSAMPLE = 0.7                 # the rows a tree sees
COLSAMPLE = 0.5                 # the features a tree may split on
MIN_LEAF = 30                   # rows a leaf keeps at least
BINS = 10                       # quantile bins of a feature (one more for a missing value)
L2 = 30.0                       # the leaf values' penalty (the Newton step −G / (H + L2)) and the split gain's
WARMUP = 21                     # closes before a line's first row (its one-month momentum)
MIN_TRAIN = 100                 # rows of known label a month's model needs
MOVE_ROWS = 250                 # the mean |5-day P&L| (the target's scale) over the last rows
STOP_SIGMA = 1.5                # the stop: σ of five days
Z_SCALE = 0.05                  # z(p) = (p − 0,5) ÷ 0,05: the Tahmin modeli's score (p 60 % is the desk's entry 2,0)
STALE_DAYS = 10                 # an input older than this (calendar days) is missing
#: what a model is made with: a model of other settings is another model
MODEL_SIG = (HORIZON, TREES, DEPTH, RATE, SUBSAMPLE, COLSAMPLE, MIN_LEAF, BINS, L2, WARMUP)
SETTINGS = {"horizon": HORIZON, "trees": TREES, "depth": DEPTH, "rate": RATE, "subsample": SUBSAMPLE, "colsample": COLSAMPLE,
            "min_leaf": MIN_LEAF, "bins": BINS, "l2": L2, "min_train": MIN_TRAIN, "retrain": "aylık"}

# ---------------------------------------------------------------------------------------------- the universe
#: the lines of the family, by the registry's keys (the plan: G10 spot and ATM 3M vol, TRY OIS outrights ≤ 2Y and 5Y /
#: 10Y, spreads 3M/1Y, 6M/2Y, 1Y/2Y, 2Y/5Y, flies 3M/6M/1Y, 6M/1Y/2Y, FRA 3×6, 6×9 and 12×15 - the registry's grid has
#: no 12×18 -, the next PPK period; then the DİBS benchmarks, the VİOP front and four offshore lines)
FIXED = (tuple("FX:" + p for p in qu.G10_PAIRS) + tuple(qopt.key(p, "ATM", "3M") for p in qu.G10_PAIRS)
         + ("OIS:1M", "OIS:2M", "OIS:3M", "OIS:6M", "OIS:9M", "OIS:1Y", "OIS:18M", "OIS:2Y", "OIS:5Y", "OIS:10Y",
            "OISS:3M/1Y", "OISS:6M/2Y", "OISS:1Y/2Y", "OISS:2Y/5Y", "OISF:3M/6M/1Y", "OISF:6M/1Y/2Y",
            "FRA:3x6", "FRA:6x9", "FRA:12x15", "PPK:1",
            "FWD:USDTRY:1M", "FWD:USDTRY:3M", "FXP:USDTRY:3M", "OFF:1Y"))
#: the DİBS benchmarks: the fixed-coupon bonds of the DİBS RV list nearest these maturities (years), by ISIN
DIBS_YEARS = (2.0, 5.0, 10.0)
#: the VİOP front: the listed contract nearest its expiry with at least this many days left
VIOP_MIN_DAYS = 7


def universe(reg: qu.Registry) -> Tuple[List[qu.Instrument], Dict[str, str]]:
    """The family's lines in the list's order and the planned ones the registry has not (``{key: why}``)."""
    want = set(FIXED)
    missing = {k: reg.missing.get(k) or "seri yok" for k in FIXED if k not in reg}
    today = reg.ctx.today
    bonds = [i for i in reg.tradeable("DİBS") if getattr(i, "bond", None) is not None]
    for years in DIBS_YEARS:
        target = today + _dt.timedelta(days=int(round(years * 365.25)))
        left = [b for b in bonds if b.key not in want]
        if left:
            want.add(min(left, key=lambda b: (abs((b.bond.maturity - target).days), b.key)).key)
    if not bonds:
        missing["DIBS"] = "DİBS RV listesinde sabit kuponlu kâğıt yok"
    front = [v for v in reg.tradeable("VİOP") if getattr(v, "g", 0) >= VIOP_MIN_DAYS]
    if front:
        want.add(min(front, key=lambda v: (v.c.expiry, v.key)).key)
    else:
        missing["VIOP"] = "işlemde VİOP kontratı yok"
    return [i for i in reg if i.key in want], missing


# ---------------------------------------------------------------------------------------------- the features
#: (name, label, unit): the own features, the curve, the drivers (from the day before), TRY's, the risk reversal, the
#: calendar - a row's values in this order
FEATURES: Tuple[Tuple[str, str, str], ...] = (
    ("z20", "z (20 gün)", "σ"), ("z60", "z (60 gün)", "σ"), ("z250", "z (250 gün)", "σ"),
    ("mom5", "momentum 1 hafta", "σ"), ("mom21", "momentum 1 ay", "σ"), ("mom63", "momentum 3 ay", "σ"),
    ("carry", "carry", ""), ("vol", "oynaklık (20 gün)", ""), ("volchg", "oynaklık değişimi (20 / 60 gün)", ""),
    ("lvl", "2Y OIS", "%"), ("slope", "eğim 2s10s", "bp"), ("fly", "eğrilik 2s5s10s", "bp"),
    ("lvl5", "2Y OIS 5 günde", "bp"), ("slope5", "2s10s 5 günde", "bp"), ("fly5", "2s5s10s 5 günde", "bp"),
    ("ust2_1", "UST 2Y 1 gün", "bp"), ("ust2_5", "UST 2Y 5 gün", "bp"), ("ust10_1", "UST 10Y 1 gün", "bp"), ("ust10_5", "UST 10Y 5 gün", "bp"),
    ("dxy_1", "DXY 1 gün", "%"), ("dxy_5", "DXY 5 gün", "%"), ("emfx_1", "EM FX 1 gün", "%"), ("emfx_5", "EM FX 5 gün", "%"),
    ("brent_1", "Brent 1 gün", "%"), ("brent_5", "Brent 5 gün", "%"), ("cds_1", "CDS 1 gün", "bp"), ("cds_5", "CDS 5 gün", "bp"),
    ("tlref", "TLREF 3 ayda", "bp"), ("ppk", "sıradaki PPK adımı", "bp"), ("viop", "VİOP − OIS (1A)", "bp"),
    ("rr", "25D RR 3A", "vol"), ("rr5", "25D RR 5 günde", "vol"),
    ("month_end", "ufukta ay sonu", ""), ("weekday", "haftanın günü", ""),
)
NAMES = tuple(f[0] for f in FEATURES)
LABELS = {f[0]: f[1] for f in FEATURES}
MODEL_SIG += NAMES
N_OWN = 9
#: the drivers read from the day before: (name, the registry's key)
DRIVERS = (("ust2", "UST:2Y"), ("ust10", "UST:10Y"), ("dxy", "DXY"), ("emfx", "EMFX"), ("brent", "BRENT"), ("cds", "CDS"))
CURVE = ("OIS:2Y", "OIS:5Y", "OIS:10Y")
WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def _num(v: Any) -> Optional[float]:
    return v if type(v) is float and math.isfinite(v) else (float(v) if type(v) is int else None)


def _sd(xs: Sequence[float]) -> Optional[float]:
    """The sample σ (sums at C speed); ``None`` for fewer than two points or a series flat to its rounding."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    v = sum(map(mul, xs, xs)) / n - m * m
    return math.sqrt(v * n / (n - 1)) if v > 0.0 and v > 1e-12 * m * m else None


def _moves(pts: Sequence[Tuple[str, float]], kind: str, k: int) -> Tuple[List[str], List[Optional[float]]]:
    """A series' change over ``k`` of its own closes, day by day (change units: bp, %, as they are)."""
    days, vals = [], []
    for i in range(k, len(pts)):
        days.append(pts[i][0])
        vals.append(qf.change(kind, pts[i - k][1], pts[i][1]))
    return days, vals


class Inputs(object):
    """The features the lines share, read once a fit from the registry: each of them as-of a day - the drivers, TLREF,
    the PPK step, the VİOP basis and the risk reversals from the closes before it, the curve from the day's own close
    (``row(day, rr, live)``: ``live`` - the curve's values now, the rest from the last closes)."""

    def __init__(self, reg: qu.Registry):
        self.reg = reg
        ctx = reg.ctx
        self.ctx = ctx
        self.hol = set(ctx.holidays or ())
        self.lagged: Dict[str, Tuple[List[str], List[Optional[float]]]] = {}
        for name, key in DRIVERS:
            inst = reg.get(key)
            pts = inst.pts() if inst is not None else []
            kind = inst.kind if inst is not None else "rate"
            self.lagged[name + "_1"] = _moves(pts, kind, 1)
            self.lagged[name + "_5"] = _moves(pts, kind, 5)
        tl = reg.get("TLREF")
        self.lagged["tlref"] = _moves(tl.pts() if tl is not None else [], "rate", 63)
        self.tlref = (tl.days, tl.values) if tl is not None else ([], [])
        steps = []
        for day, p in sorted(reg.paths().items()):
            ms = p.get("meetings") or []
            if ms and _num(p.get("base")) is not None:
                steps.append((day, (ms[0][1] - p["base"]) * 100.0))
        self.lagged["ppk"] = ([d for d, _ in steps], [v for _, v in steps])
        try:
            cm = ((reg.viop_history() or {}).get("cm") or {}).get(30) or {}
        except Exception:  # noqa: BLE001 - no VİOP history is a missing feature
            cm = {}
        basis = sorted((d, x["basis"]) for d, x in cm.items() if _num(x.get("basis")) is not None)
        self.lagged["viop"] = ([d for d, _ in basis], [v for _, v in basis])
        # the risk reversals: each pair's own, and the seven pairs' mean
        self.rr: Dict[str, Tuple[Tuple[List[str], List[float]], Tuple[List[str], List[Optional[float]]]]] = {}
        by_day: Dict[str, List[float]] = {}
        for pair in qu.G10_PAIRS:
            inst = reg.get(qopt.key(pair, "RR25", "3M"))
            pts = inst.pts() if inst is not None else []
            if pts:
                self.rr[pair] = (([d for d, _ in pts], [v for _, v in pts]), _moves(pts, "vol", 5))
                for d, v in pts:
                    by_day.setdefault(d, []).append(v)
        avg = sorted((d, sum(vs) / len(vs)) for d, vs in by_day.items())
        self.rr["avg"] = (([d for d, _ in avg], [v for _, v in avg]), _moves(avg, "vol", 5))
        # the curve: the days its three tenors closed together
        sets = [dict(reg[k].pts()) if k in reg else {} for k in CURVE]
        days = sorted(set(sets[0]).intersection(*sets[1:])) if all(sets) else []
        self.curve_days = days
        self.curve = [self._curve(sets[0][d], sets[1][d], sets[2][d]) for d in days]
        self._memo: Dict[Tuple[str, str], List[Optional[float]]] = {}
        self._me: Dict[str, float] = {}

    @staticmethod
    def _curve(r2: float, r5: float, r10: float) -> Tuple[float, float, float]:
        return r2, (r10 - r2) * 100.0, (2.0 * r5 - r2 - r10) * 100.0

    def _asof(self, days: List[str], vals: List[Any], day: str, strict: bool) -> Any:
        i = (bisect.bisect_left(days, day) if strict else bisect.bisect_right(days, day)) - 1
        if i < 0:
            return None
        if (_dt.date.fromisoformat(day) - _dt.date.fromisoformat(days[i])).days > STALE_DAYS:
            return None
        return vals[i]

    def tlref_before(self, day: str) -> Optional[float]:
        """TLREF's last close before the day (its fixing comes the morning after)."""
        return self._asof(self.tlref[0], self.tlref[1], day, True)

    def curve_at(self, day: str, live: Optional[Dict[str, float]] = None) -> List[Optional[float]]:
        """Level, slope, curvature and their 5-day changes - at the day's close, or now (``live``)."""
        days = self.curve_days
        if live is not None:
            vals = [self.ctx.cur(k, live) for k in CURVE]
            if any(v is None for v in vals):
                return [None] * 6
            now = self._curve(*vals)
            i = len(days)
        else:
            i = bisect.bisect_right(days, day) - 1
            if i < 0 or (_dt.date.fromisoformat(day) - _dt.date.fromisoformat(days[i])).days > STALE_DAYS:
                return [None] * 6
            now = self.curve[i]
        back = self.curve[i - 5] if i >= 5 else None
        return list(now) + ([now[0] * 100.0 - back[0] * 100.0, now[1] - back[1], now[2] - back[2]] if back else [None] * 3)

    def month_end(self, day: str) -> float:
        """1 when a month's last business day is among the next ``HORIZON`` business days (the holding's), else 0."""
        hit = self._me.get(day)
        if hit is None:
            d = _dt.date.fromisoformat(day)
            seen, hit = 0, 0.0
            while seen < HORIZON:
                d += _dt.timedelta(days=1)
                if d.weekday() >= 5 or d in self.hol:
                    continue
                seen += 1
                nxt = qf.business_on_or_after(d + _dt.timedelta(days=1), self.hol)
                if nxt.month != d.month:
                    hit = 1.0
                    break
            self._me[day] = hit
        return hit

    def row(self, day: str, rr: str, live: Optional[Dict[str, float]] = None) -> List[Optional[float]]:
        """Every shared feature of a line's row on ``day`` (its risk reversal ``rr``: a pair, or "avg")."""
        memo = (day, rr) if live is None else None
        if memo is not None and memo in self._memo:
            return self._memo[memo]
        out = self.curve_at(day, live)
        for name, _ in DRIVERS:
            for k in ("_1", "_5"):
                days, vals = self.lagged[name + k]
                out.append(self._asof(days, vals, day, True))
        for name in ("tlref", "ppk", "viop"):
            days, vals = self.lagged[name]
            out.append(self._asof(days, vals, day, True))
        lv, ch = self.rr.get(rr) or self.rr["avg"]
        out.append(self._asof(lv[0], lv[1], day, True))
        out.append(self._asof(ch[0], ch[1], day, True))
        out.append(self.month_end(day))
        out.append(float(_dt.date.fromisoformat(day).weekday()))
        if memo is not None:
            self._memo[memo] = out
        return out


def _own(L: List[float], ch: List[Optional[float]], i: int, kind: str, carry: Optional[float]) -> List[Optional[float]]:
    """A line's own features at index ``i`` of its closes ``L`` (``ch[i]``: the move into ``i``): only ``L[:i + 1]``."""
    x = L[i]
    out: List[Optional[float]] = []
    for w in (20, 60, 250):
        if i + 1 >= w:
            sd = _sd(L[i - w + 1:i + 1])
            out.append((x - sum(L[i - w + 1:i + 1]) / w) / sd if sd else None)
        else:
            out.append(None)
    c60 = [c for c in ch[max(1, i - 59):i + 1] if c is not None]
    c20 = [c for c in ch[max(1, i - 19):i + 1] if c is not None]
    sd60 = _sd(c60) if len(c60) >= 20 else None
    sd20 = _sd(c20) if len(c20) >= 10 else None
    for k in (5, 21, 63):
        mv = qf.change(kind, L[i - k], x) if i >= k else None
        out.append(mv / (sd60 * math.sqrt(k)) if mv is not None and sd60 else None)
    out.append(carry)
    out.append(sd20)
    out.append(math.log(sd20 / sd60) if sd20 and sd60 else None)
    return out


def _fx(inst: qu.Instrument) -> bool:
    return isinstance(inst, qu.FxSpot)


def _rr_of(inst: qu.Instrument, inputs: Inputs) -> str:
    """The risk reversal a line reads: a G10 line its pair's, every other line (and a pair without one) the mean."""
    pair = getattr(inst, "pair", None) if inst.group in ("G10 spot", "G10 opsiyon") else None
    return pair if pair in inputs.rr else "avg"


def carry_days(inst: qu.Instrument, inputs: Inputs) -> Dict[str, float]:
    """The carry feature of each of the line's closes: FX % a year of a long (a spot: its forward points; an offshore
    forward: its points rolling to spot), a rate's level over TLREF (bp), an ATM vol's implied − realised (21 closes of
    the pair's spot, vol points); none for a spread, a fly or swap points (their level is it)."""
    ctx = inputs.ctx
    if isinstance(inst, qu.FxForward):
        spot = dict(ctx.pts("FX:" + inst.pair))
        out = {}
        for d, f in inst.pts():
            s = spot.get(d)
            if s and f and s > 0 and f > 0:
                out[d] = -(math.log(f) - math.log(s)) * 100.0 * 365.0 / inst.inst_days
        return out
    if isinstance(inst, qu.FxSpot):
        return dict(ctx.fx_carry_days(inst.pair))
    if isinstance(inst, qu.FxVol):
        spot = ctx.pts("FX:" + inst.pair)
        rets = [(d, math.log(b / a) * 100.0) for (_, a), (d, b) in zip(spot, spot[1:]) if a > 0 and b > 0]
        rv: Dict[str, float] = {}
        for i in range(20, len(rets)):
            sd = _sd([r for _, r in rets[i - 20:i + 1]])
            if sd:
                rv[rets[i][0]] = sd * math.sqrt(252.0)
        return {d: v - rv[d] for d, v in inst.pts() if d in rv}
    if inst.kind == "rate":
        out = {}
        for d, v in inst.pts():
            t = inputs.tlref_before(d)
            if t is not None:
                out[d] = (v - t) * 100.0
        return out
    return {}


def carry_now(inst: qu.Instrument, inputs: Inputs, level: Optional[float], live: Dict[str, float], hist: Dict[str, float],
              closes: Dict[str, float]) -> Optional[float]:
    """The carry feature now (as :func:`carry_days` of a close; ``hist`` that, ``closes`` the line's closes): an ATM
    vol's realised vol is the last close's (a day's spot hardly moves 21 days' σ)."""
    ctx = inputs.ctx
    if level is None:
        return None
    try:
        if isinstance(inst, qu.FxForward):
            s = ctx.cur("FX:" + inst.pair, live)
            return -(math.log(level) - math.log(s)) * 100.0 * 365.0 / inst.inst_days if s and level > 0 and s > 0 else None
        if isinstance(inst, qu.FxSpot):
            return ctx.fx_carry(inst.pair, live)
        if isinstance(inst, qu.FxVol):
            if not hist:
                return None
            d = max(hist)
            return level - (closes[d] - hist[d]) if d in closes else None
        if inst.kind == "rate":
            t = inputs.tlref_before(ctx.today_iso)
            return (level - t) * 100.0 if t is not None else None
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return None


class Row(object):
    """One close of a line: its features, its label (1: the up side gained over the next ``HORIZON`` closes, ``None``:
    not known yet or no move) and the day the label is known, the P&L behind it (change units)."""

    __slots__ = ("day", "x", "y", "end", "pnl", "i")

    def __init__(self, day: str, x: List[Optional[float]], y: Optional[int], end: Optional[str], pnl: Optional[float], i: int):
        self.day, self.x, self.y, self.end, self.pnl, self.i = day, x, y, end, pnl, i


def rows_of(inst: qu.Instrument, inputs: Inputs) -> Tuple[List[Row], List[Tuple[str, float]], List[Optional[float]], Dict[str, float]]:
    """Every row of a line (its closes, the roll days' jumps out), the closes they are made of, the moves and the carry."""
    pts = inst.adjusted()
    L = [v for _, v in pts]
    days = [d for d, _ in pts]
    kind = inst.kind
    ch: List[Optional[float]] = [None] + [qf.change(kind, a, b) for a, b in zip(L, L[1:])]
    carry = carry_days(inst, inputs)
    fx = _fx(inst)
    rr = _rr_of(inst, inputs)
    out: List[Row] = []
    for i in range(WARMUP, len(L)):
        d = days[i]
        x = _own(L, ch, i, kind, carry.get(d)) + inputs.row(d, rr)
        y = end = pnl = None
        if i + HORIZON < len(L):
            end = days[i + HORIZON]
            pnl = qf.change(kind, L[i], L[i + HORIZON])
            if pnl is not None and fx:
                c = carry.get(d)
                pnl = pnl + c * (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(d)).days / 365.0 if c is not None else None
            if pnl is not None and pnl != 0.0:
                y = 1 if pnl > 0 else 0
        out.append(Row(d, x, y, end, pnl, i))
    return out, pts, ch, carry


# ---------------------------------------------------------------------------------------------- the trees
#: a node's row is its gradient + the pack: a bin's sum is G + pack × count, both read back from it (|G| < count, and
#: the pack is a power of two above four times the rows: count < pack / 4)
_PACK_MIN = 4096


def _logistic(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _edges(col: Sequence[Optional[float]], bins: int) -> List[float]:
    """The cut points of a feature's quantile bins over the training rows (ties merged)."""
    xs = sorted(v for v in col if v is not None)
    out: List[float] = []
    for k in range(1, bins):
        if not xs:
            break
        e = xs[min(len(xs) - 1, (k * len(xs)) // bins)]
        if e > xs[0] and (not out or e > out[-1]):
            out.append(e)
    return out


class Trees(object):
    """Gradient-boosted trees on the logistic loss.  A tree is a list of nodes ``(feature, bin, missing_left, left,
    right, value)`` (a leaf: feature −1); ``value`` is every node's Newton value × the rate, the leaves' sum the tree's
    output - and a path's steps the features' contributions (:meth:`contributions`)."""

    __slots__ = ("base", "trees", "edges", "gain", "miss", "n")

    def __init__(self, base: float, trees: List[List[Tuple]], edges: List[List[float]], gain: List[float], miss: int, n: int):
        self.base, self.trees, self.edges, self.gain, self.miss, self.n = base, trees, edges, gain, miss, n

    @classmethod
    def fit(cls, X: Sequence[Sequence[Optional[float]]], y: Sequence[int], seed: int = 0, trees: int = TREES, depth: int = DEPTH,
            rate: float = RATE, subsample: float = SUBSAMPLE, colsample: float = COLSAMPLE, min_leaf: int = MIN_LEAF,
            bins: int = BINS, l2: float = L2) -> "Trees":
        n, nf = len(X), len(X[0])
        miss, nb = bins, bins + 1
        pack = float(max(_PACK_MIN, 1 << (4 * n).bit_length()))
        edges: List[List[float]] = []
        B: List[List[int]] = []
        for j in range(nf):
            col = [r[j] for r in X]
            e = _edges(col, bins)
            edges.append(e)
            B.append([miss if v is None else bisect.bisect_left(e, v) for v in col])
        # each bin's rows as one C-level getter (a bin of one row or none padded with the zero slot n: always a tuple)
        getters: List[List[Callable]] = []
        for j in range(nf):
            lists: List[List[int]] = [[] for _ in range(nb)]
            for i, b in enumerate(B[j]):
                lists[b].append(i)
            getters.append([itemgetter(*(lst + [n] * (2 - len(lst)) if len(lst) < 2 else lst)) for lst in lists])
        ybar = min(max(sum(y) / float(n), 1e-3), 1.0 - 1e-3)
        base = math.log(ybar / (1.0 - ybar))
        F = [base] * n
        rnd = random.Random(seed)
        every = list(range(n))
        ncol = max(1, int(round(nf * colsample)))
        gain = [0.0] * nf
        out: List[List[Tuple]] = []
        for _ in range(trees):
            p = [_logistic(f) for f in F]
            g = [pi - yi for pi, yi in zip(p, y)]
            hs = [pi * (1.0 - pi) for pi in p]
            gk = [gi + pack for gi in g]
            gz, hz = g + [0.0], hs + [0.0]                # (the zero slot n of the padded getters)
            rows = [i for i in every if rnd.random() < subsample] if subsample < 1.0 else every
            if len(rows) < 2 * min_leaf:
                rows = every
            feats = sorted(rnd.sample(range(nf), ncol))
            nodes: List[List[Any]] = []
            leaves: List[Tuple[List[int], float]] = []

            def hist(rs: List[int]) -> Dict[int, List[float]]:
                m = [0.0] * (n + 1)
                for i in rs:
                    m[i] = gk[i]
                return {j: [sum(gt(m)) for gt in getters[j]] for j in feats}

            def best(H: Dict[int, List[float]]) -> Tuple[float, Optional[Tuple[int, int, int]]]:
                top, where = 0.0, None
                for j in feats:
                    hj = H[j]
                    sm = hj[miss]
                    cm = int(sm / pack + 0.5)
                    gm = sm - pack * cm
                    cum = list(accumulate(hj[:miss - 1]))
                    cc = [int(s / pack + 0.5) for s in cum]
                    gc = [s - pack * c for s, c in zip(cum, cc)]
                    tot = sum(hj)
                    ct = int(tot / pack + 0.5)
                    gt = tot - pack * ct
                    lo, hi = min_leaf, ct - min_leaf
                    if hi < lo:
                        continue
                    parent = gt * gt / (ct + l2)
                    # missing values right, then (where the node has some) left
                    g0 = [a * a / (c + l2) + (gt - a) ** 2 / (ct - c + l2) if lo <= c <= hi else 0.0 for a, c in zip(gc, cc)]
                    x0 = max(g0) if g0 else 0.0
                    if x0 - parent > top:
                        top, where = x0 - parent, (j, g0.index(x0), 0)
                    if cm:
                        g1 = [(a + gm) ** 2 / (c + cm + l2) + (gt - a - gm) ** 2 / (ct - c - cm + l2) if lo <= c + cm <= hi else 0.0
                              for a, c in zip(gc, cc)]
                        x1 = max(g1) if g1 else 0.0
                        if x1 - parent > top:
                            top, where = x1 - parent, (j, g1.index(x1), 1)
                return top, where

            def grow(rs: List[int], al: List[int], H: Optional[Dict[int, List[float]]], d: int) -> int:
                get = itemgetter(*(rs + [n] * (2 - len(rs)) if len(rs) < 2 else rs))
                gg, hh = sum(get(gz)), sum(get(hz))
                k = len(nodes)
                val = -gg / (hh + l2) * rate
                nodes.append([-1, 0, 0, -1, -1, val])
                split = None
                if d < depth and len(rs) >= 2 * min_leaf and H is not None:
                    gn, split = best(H)
                if split is None:
                    leaves.append((al, val))
                    return k
                j, b, ml = split
                bj = B[j]
                if ml:
                    left = [i for i in rs if bj[i] <= b or bj[i] == miss]
                    right = [i for i in rs if b < bj[i] < miss]
                    aleft = [i for i in al if bj[i] <= b or bj[i] == miss]
                    aright = [i for i in al if b < bj[i] < miss]
                else:
                    left = [i for i in rs if bj[i] <= b]
                    right = [i for i in rs if bj[i] > b]
                    aleft = [i for i in al if bj[i] <= b]
                    aright = [i for i in al if bj[i] > b]
                gain[j] += gn
                hl = hr = None
                if d + 1 < depth:
                    small = left if len(left) <= len(right) else right
                    hs_ = hist(small)
                    hb = {jj: [a - c for a, c in zip(H[jj], hs_[jj])] for jj in feats}
                    hl, hr = (hs_, hb) if small is left else (hb, hs_)
                nodes[k][0:3] = [j, b, ml]
                nodes[k][3] = grow(left, aleft, hl, d + 1)
                nodes[k][4] = grow(right, aright, hr, d + 1)
                return k

            grow(rows, every, hist(rows), 0)
            for al, val in leaves:
                for i in al:
                    F[i] += val
            out.append([tuple(nd) for nd in nodes])
        return cls(base, out, edges, gain, miss, n)

    def binned(self, x: Sequence[Optional[float]]) -> List[int]:
        return [self.miss if v is None else bisect.bisect_left(e, v) for v, e in zip(x, self.edges)]

    def logit(self, x: Sequence[Optional[float]]) -> float:
        b = self.binned(x)
        miss = self.miss
        out = self.base
        for tree in self.trees:
            nd = tree[0]
            while nd[0] >= 0:
                v = b[nd[0]]
                nd = tree[nd[3]] if ((v <= nd[1]) if v != miss else nd[2]) else tree[nd[4]]
            out += nd[5]
        return out

    def prob(self, x: Sequence[Optional[float]]) -> float:
        return _logistic(self.logit(x))

    def contributions(self, x: Sequence[Optional[float]]) -> List[float]:
        """Each feature's part of this row's log-odds: the change of the node's value along every tree's path at a
        split on it (the bias - the roots - aside)."""
        b = self.binned(x)
        miss = self.miss
        out = [0.0] * len(self.edges)
        for tree in self.trees:
            nd = tree[0]
            while nd[0] >= 0:
                v = b[nd[0]]
                nxt = tree[nd[3]] if ((v <= nd[1]) if v != miss else nd[2]) else tree[nd[4]]
                out[nd[0]] += nxt[5] - nd[5]
                nd = nxt
        return out

    def importance(self) -> List[float]:
        """The features' shares of the trees' split gain (sum 1; all 0 for a model that never split)."""
        tot = sum(self.gain)
        return [g / tot for g in self.gain] if tot > 0 else [0.0] * len(self.gain)


# ---------------------------------------------------------------------------------------------- the walk-forward
#: (line key, month, rows, digest of the rows, MODEL_SIG) -> Trees: the models fitted, kept while a fit uses them
_MODELS: Dict[Tuple, Trees] = {}
_MODELS_LOCK = threading.Lock()
#: how many models were fitted in this process (a refresh or a refit of the same data fits none: the tests read it)
FITS = {"n": 0}


def _month(day: str) -> str:
    return day[:8] + "01"


def _seed(key: str, month: str) -> int:
    return zlib.crc32(("%s|%s" % (key, month)).encode("utf-8"))


def walk(key: str, rows: List[Row], today: str, used: Optional[Dict[Tuple, Trees]] = None) -> Dict[str, Any]:
    """The monthly walk-forward of one line: every month from the first with ``MIN_TRAIN`` rows of known label before
    it to today's, its model fitted on those rows (or taken from ``_MODELS``) predicting that month's rows.  ``used``
    collects the models (the fit keeps them).  Returns ``{"preds": {day: p}, "months": [...], "models": {month: Trees},
    "model": today's month's Trees or None, "fitted": n, "cached": n}``."""
    known = [r for r in rows if r.y is not None]
    months = sorted({_month(r.day) for r in rows} | {_month(today)})
    preds: Dict[str, float] = {}
    out_months: List[Dict[str, Any]] = []
    models: Dict[str, Trees] = {}
    model_now = None
    fitted = cached = 0
    digest = hashlib.sha1(repr(MODEL_SIG).encode())
    k = 0
    by_month: Dict[str, List[Row]] = {}
    for r in rows:
        by_month.setdefault(_month(r.day), []).append(r)
    for M in months:
        while k < len(known) and known[k].end < M:
            digest.update(repr((known[k].day, known[k].x, known[k].y)).encode())
            k += 1
        if k < MIN_TRAIN:
            continue
        ck = (key, M, k, digest.hexdigest())
        model = _MODELS.get(ck)
        if model is None:
            model = Trees.fit([r.x for r in known[:k]], [r.y for r in known[:k]], seed=_seed(key, M))
            fitted += 1
            FITS["n"] += 1
        else:
            cached += 1
        if used is not None:
            used[ck] = model
        models[M] = model
        test = by_month.get(M) or []
        for r in test:
            preds[r.day] = model.prob(r.x)
        out_months.append({"month": M, "train": k, "test": len(test), "last_train": known[k - 1].day, "last_end": known[k - 1].end})
        if M == _month(today):
            model_now = model
    return {"preds": preds, "months": out_months, "models": models, "model": model_now, "fitted": fitted, "cached": cached}


def record(rows: List[Row], preds: Dict[str, float], until: Optional[str] = None) -> Dict[str, Any]:
    """The out-of-sample record: hit rate, log-loss, the share of rises, days and independent tests (days ÷ the
    horizon) of the predicted rows whose label is known (``until``: by that day)."""
    pts = [(preds[r.day], r.y) for r in rows if r.y is not None and r.day in preds and (until is None or r.end <= until)]
    n = len(pts)
    if not n:
        return {"days": 0, "tests": 0, "hit": None, "log_loss": None, "base": None}
    hits = sum(1 for p, y in pts if (p > 0.5) == (y == 1))
    return {"days": n, "tests": n // HORIZON, "hit": hits / float(n), "log_loss": qm.log_loss([p for p, _ in pts], [y for _, y in pts]),
            "base": sum(y for _, y in pts) / float(n)}


# ---------------------------------------------------------------------------------------------- a line's result
class Line(object):
    """One line of the family after a fit: its rows, the walk-forward, its record, today's model and what its
    monitor needs - kept by the line's key."""

    def __init__(self, inst: qu.Instrument, inputs: Inputs, rows: List[Row], pts: List[Tuple[str, float]], ch: List[Optional[float]],
                 carry: Dict[str, float], wf: Dict[str, Any], cfg: Dict[str, Any]):
        self.inst, self.inputs, self.rows, self.pts, self.ch, self.carry = inst, inputs, rows, pts, ch, carry
        self.key = inst.key
        self.today = inst.ctx.today_iso                                   # the fit's day: its monitor scores live only then
        self.L = [v for _, v in pts]
        self.preds: Dict[str, float] = wf["preds"]
        self.months: List[Dict[str, Any]] = wf["months"]
        self.models: Dict[str, Trees] = wf["models"]
        self.model: Optional[Trees] = wf["model"]
        self.rec = record(rows, self.preds)
        self.hit_min, self.tests_min = float(cfg["model_hit"]), int(cfg["model_min_tests"])
        self.valid = bool(self.rec["hit"] is not None and self.rec["hit"] >= self.hit_min and self.rec["tests"] >= self.tests_min)
        pnl = [abs(r.pnl) for r in rows if r.pnl is not None][-MOVE_ROWS:]
        self.mean5 = sum(pnl) / len(pnl) if pnl else None                 # change units (FX: carry in it)
        self.sd1 = inst.vol()                                             # a day's σ, change units
        self.levels = dict(pts)
        self.rr = _rr_of(inst, inputs)
        self.now: Optional[Tuple[float, List[Optional[float]]]] = None    # (p, today's row) of the last score
        self.scale: Dict[str, Tuple[Optional[float], Optional[float]]] = self._scales()

    def _scales(self) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
        """Each close's (mean |5-day P&L| of the rows known by then, a day's σ of the 60 moves before): the backtest's
        target and stop of that day."""
        out: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        known = [(r.end, abs(r.pnl)) for r in self.rows if r.pnl is not None]
        j = 0
        acc: List[float] = []
        days = [d for d, _ in self.pts]
        for i, d in enumerate(days):
            while j < len(known) and known[j][0] <= d:
                acc.append(known[j][1])
                j += 1
            ch = [c for c in self.ch[max(1, i - 59):i + 1] if c is not None]
            win = acc[-MOVE_ROWS:]
            out[d] = (sum(win) / len(win) if win else None, _sd(ch) if len(ch) >= 10 else None)
        return out

    # ---- today
    def row_now(self, level: float, live: Dict[str, float]) -> List[Optional[float]]:
        """Today's row: the own features with the level now, the curve now, the rest from the last closes."""
        L = self.L + [level]
        ch = self.ch + [qf.change(self.inst.kind, self.L[-1], level) if self.L else None]
        carry = carry_now(self.inst, self.inputs, level, live, self.carry, self.levels)
        return _own(L, ch, len(L) - 1, self.inst.kind, carry) + self.inputs.row(self.today, self.rr, live)

    def prob_now(self, level: Optional[float], live: Dict[str, float]) -> Optional[float]:
        if self.model is None or level is None or len(self.L) < WARMUP:
            return None
        x = self.row_now(level, live)
        p = self.model.prob(x)
        self.now = (p, x)
        return p

    def why(self, x: Sequence[Optional[float]], k: int = 3) -> List[Dict[str, Any]]:
        """The ``k`` features that moved this row's prediction most: name, label, value, the contribution (log-odds; +
        toward a rise) and the desk's words."""
        if self.model is None:
            return []
        c = self.model.contributions(x)
        top = sorted(range(len(c)), key=lambda j: (-abs(c[j]), j))[:k]
        return [{"name": NAMES[j], "label": LABELS[NAMES[j]], "value": x[j], "effect": c[j], "text": phrase(NAMES[j], x[j], self.inst)}
                for j in top if c[j] != 0.0]

    # ---- the record
    def status(self, entry: float, p: Optional[float]) -> Tuple[bool, str]:
        """(prints, why not) of the line now."""
        r = self.rec
        if len(self.L) < WARMUP + HORIZON + MIN_TRAIN:
            return False, "geçmiş kısa (%d kapanış; en az %d)" % (len(self.L), WARMUP + HORIZON + MIN_TRAIN)
        if _fx(self.inst) and not self.carry:
            return False, "forward puanı yok: carry'si bilinmeyen getiri yazılmaz"
        if not self.months:
            return False, "eğitim için etiketli satır az (en az %d)" % MIN_TRAIN
        if r["tests"] < self.tests_min:
            return False, "örneklem dışı test az (%d < %d)" % (r["tests"], self.tests_min)
        if (r["hit"] or 0.0) < self.hit_min:
            return False, "örneklem dışı isabet %%%s < %%%s" % (_cut(r["hit"] or 0.0), qf._g(self.hit_min * 100.0, 0))
        if self.model is None:
            return False, "bu ayın modeli yok"
        if p is None:
            return False, "bugünkü seviye yok"
        if abs(p - 0.5) / Z_SCALE < entry:
            return False, "olasılık %%%s < eşik %%%s" % (_cut(max(p, 1.0 - p)), qf._g((0.5 + Z_SCALE * entry) * 100.0, 0))
        return True, ""

    def trades(self, entry: float) -> Dict[str, Any]:
        """The out-of-sample predictions as trades: every day the probability is past the entry, the five days after in
        its direction (P&L units of the line: bp of the package, %, vol, puan; FX with its carry) - hit rate, mean,
        Sharpe (mean ÷ σ × √(trades a year))."""
        pnl = []
        for r in self.rows:
            p = self.preds.get(r.day)
            if p is None or r.pnl is None or abs(p - 0.5) / Z_SCALE < entry:
                continue
            pnl.append((1.0 if p > 0.5 else -1.0) * r.pnl * self.inst.per_cu)
        if not pnl:
            return {"n": 0}
        n = len(pnl)
        m = sum(pnl) / n
        sd = _sd(pnl)
        span = max(1.0, len(self.preds) / 250.0)
        return {"n": n, "hit": sum(1 for x in pnl if x > 0) / float(n), "mean": m, "sharpe": m / sd * math.sqrt(n / float(HORIZON) / span) if sd else None}


# ---------------------------------------------------------------------------------------------- the desk's words
def _v(v: Optional[float], d: int = 1) -> str:
    return qf._g(v, d) if v is not None else "—"


def _s(v: Optional[float], d: int = 1) -> str:
    return qf._sg(v, d) if v is not None else "—"


def _sp(v: Optional[float], d: int = 1) -> str:
    """A signed per cent the Turkish way: "+%12,5", "-%0,8"."""
    if v is None:
        return "—"
    txt = qf._g(abs(v), d)
    return ("+" if v > 0 else "-" if v < 0 else "") + "%" + txt if any(c in "123456789" for c in txt) else "%" + txt


def phrase(name: str, v: Optional[float], inst: qu.Instrument) -> str:
    """A feature's value as the desk says it ("Brent son 5 günde %−4,2", "2Y OIS 60 günlük ortalamasının üstünde (z +1,8)")."""
    lab = inst.label
    if v is None:
        return "%s yok" % LABELS[name]
    if name in ("z20", "z60", "z250"):
        return "%s %s günlük ortalamasının %s (z %s)" % (lab, name[1:], "üstünde" if v > 0 else "altında", _s(v))
    if name in ("mom5", "mom21", "mom63"):
        span = {"mom5": "1 haftada", "mom21": "1 ayda", "mom63": "3 ayda"}[name]
        return "%s son %s %s (%sσ)" % (lab, span, "yükseldi" if v > 0 else "düştü", _s(v))
    if name == "carry":
        if _fx(inst):
            return "carry yıllık %s (uzun tarafın)" % _sp(v)
        if isinstance(inst, qu.FxVol):
            return "ima vol gerçekleşenin %s puan %s" % (_v(abs(v)), "üstünde" if v > 0 else "altında")
        return "%s TLREF'in %s bp %s" % (lab, _v(abs(v), 0), "üstünde" if v > 0 else "altında")
    if name == "vol":
        return "%s günlük oynaklığı %s %s" % (lab, _v(v, 2), qf.change_unit(inst.kind))
    if name == "volchg":
        return "oynaklık %s (20 / 60 gün %s)" % ("arttı" if v > 0 else "azaldı", _v(math.exp(v), 2))
    if name == "lvl":
        return "2Y OIS %%%s" % _v(v, 2)
    if name == "slope":
        return "2s10s %s bp" % _s(v)
    if name == "fly":
        return "2s5s10s eğriliği %s bp" % _s(v)
    if name in ("lvl5", "slope5", "fly5"):
        return "%s 5 günde %s bp" % ({"lvl5": "2Y OIS", "slope5": "2s10s", "fly5": "2s5s10s"}[name], _s(v))
    if "_" in name and name.split("_")[0] in dict(DRIVERS):
        base, span = name.split("_")
        what = {"ust2": "UST 2Y", "ust10": "UST 10Y", "dxy": "DXY", "emfx": "EM kurları (USD / EM)", "brent": "Brent", "cds": "CDS"}[base]
        when = "dün" if span == "1" else "son 5 günde"
        if base in ("dxy", "emfx", "brent"):
            return "%s %s %s" % (what, when, _sp(v, 1))
        return "%s %s %s bp" % (what, when, _s(v))
    if name == "tlref":
        return "TLREF son 3 ayda %s bp" % _s(v, 0)
    if name == "ppk":
        return "sıradaki PPK için fiyatlanan adım %s bp" % _s(v, 0)
    if name == "viop":
        return "VİOP − OIS farkı %s bp" % _s(v)
    if name == "rr":
        return "25D RR 3A %s" % _s(v, 2)
    if name == "rr5":
        return "25D RR 5 günde %s" % _s(v, 2)
    if name == "month_end":
        return "ufukta ay sonu var" if v else "ufukta ay sonu yok"
    if name == "weekday":
        return "günlerden %s" % WEEKDAYS[int(v) % 7]
    return "%s %s" % (LABELS.get(name, name), _v(v))


def _pct(p: Optional[float]) -> str:
    return qf._g(p * 100.0, 0) if p is not None else "—"


def _cut(p: float) -> str:
    """A share as a per cent to one decimal, cut not rounded (54,98 % is below 55 %: "54,9")."""
    return qf._g(math.floor(p * 1000.0) / 10.0, 1)


def line_text(inst: qu.Instrument, side: int, prob: float, rec: Dict[str, Any]) -> str:
    """The plan's line: "AL EURUSD spot · 1 mn EUR · olasılık %63 · isabet %58 (52)"."""
    return "%s · olasılık %%%s · isabet %%%s (%d)" % (inst.line(side), _pct(prob), _pct(rec["hit"]), rec["tests"])


# ---------------------------------------------------------------------------------------------- the monitors
def _monitor(line: Line, cfg: Dict[str, Any], replay: bool = False) -> qf.Monitor:
    """The line's monitor: z(p) of the probability now (today: the live features; a backtest's day: that day's
    out-of-sample prediction), target (2p − 1) × the mean |5-day P&L|, stop 1,5 σ of five days, held five days.
    ``replay``: a backtest refit's (its level is the line's own close of the day: a roll is no P&L)."""
    inst = line.inst
    ctx = inst.ctx
    kind = inst.kind
    rec = line.rec
    entry = float(cfg["entry_z"])

    def scales(level: float) -> Tuple[Optional[float], Optional[float]]:
        mean5, sd1 = line.mean5, line.sd1
        if replay:
            mean5, sd1 = line.scale.get(ctx.today_iso, (None, None))
        mv = qf.to_level(kind, mean5, level) if mean5 is not None else None
        risk = qf.to_level(kind, STOP_SIGMA * sd1 * math.sqrt(HORIZON), level) if sd1 else None
        return mv, risk

    m = inst.monitor("ml:" + inst.key, FAMILY, zfn=None, mode="drift", follows=True, hold=float(HORIZON), score_name="z(p)",
                     regime={"tag": None}, reward=None, risk=None, fcast=None, pnl_sd=None,
                     sample=None if replay else {"ok": True, "text": "örneklem dışı isabet %%%s (%d test, log-loss %s) ≥ %%%s, en az %d test" % (
                         _pct(rec["hit"]), rec["tests"], _v(rec["log_loss"], 3), _pct(line.hit_min), line.tests_min)},
                     # (the backtest's row is the line's name without what changes as it rolls: "PPK 1. dönem (17.12–22.01)"
                     # is one row through every period, not a row each)
                     info={"version": inst.label.split(" (")[0], "p": None, "hit_rate": rec["hit"], "n_test": rec["tests"],
                           "log_loss": rec["log_loss"], "valid": line.valid})

    def zfn(level: float, live: Dict[str, float]) -> Optional[float]:
        if level is None:
            return None
        p = line.preds.get(ctx.today_iso)                  # a backtest's day: the walk-forward's own prediction
        if p is None:
            if replay or ctx.today_iso != line.today:
                return None
            p = line.prob_now(level, live)                 # today: the live features, this month's trees
        if p is None:
            return None
        mv, risk = scales(level)
        m.info["p"] = p
        m.reward = abs(2.0 * p - 1.0) * mv if mv is not None else None
        m.fcast = (2.0 * p - 1.0) * mv if mv is not None else None
        m.risk = risk
        return (p - 0.5) / Z_SCALE

    m.zfn = zfn
    if replay:
        lv = line.levels
        m.calc = lambda live: lv.get(ctx.today_iso)                        # noqa: E731
    else:
        # the chart's lower panel: the out-of-sample probability day by day (as z(p))
        m.zvalues = [(line.preds[d] - 0.5) / Z_SCALE if d in line.preds else None for d in m.days]

        def words(sg: Dict[str, Any]) -> str:
            return _words(line, m, sg, entry)

        m.thesis = words
        m.note = ("Gradyan artırmalı ağaçlar (%d ağaç, derinlik %d, öğrenme %s, %d özellik): önümüzdeki %d iş gününün yönü. Aylık yeniden "
                  "eğitim: her ayın modeli yalnız o ay başlamadan bilinenle kurulur, yalnız o ayda test edilir. Örneklem dışı isabet %%%s (%d test, "
                  "log-loss %s). z(p) = (p − 0,5) ÷ 0,05; hedef (2p − 1) × ortalama %d günlük K/Z, stop %s σ (%d gün)." % (
                      TREES, DEPTH, qf._g(RATE, 1), len(NAMES), HORIZON, _cut(rec["hit"] or 0.0), rec["tests"], _v(rec["log_loss"], 3), HORIZON,
                      qf._g(STOP_SIGMA, 1), HORIZON))
    return m


def _words(line: Line, m: qf.Monitor, sg: Dict[str, Any], entry: float) -> str:
    """The line's words, written when ``make_signal`` asks the monitor for its thesis (its last step): the line in the
    plan's form (``expression``), the card's sentence with why (the three features that moved today's prediction most)
    - and the thesis itself."""
    inst = line.inst
    rec = line.rec
    p = m.info.get("p")
    side = sg["direction"]
    prob = p if side > 0 else 1.0 - p
    sg["expression"] = line_text(inst, side, prob, rec)
    up = "yükseliş" if side > 0 else "düşüş"
    why = line.why(line.now[1]) if line.now is not None else []
    told = ["%s (%s)" % (w["text"], "lehte" if (w["effect"] > 0) == (side > 0) else "aleyhte") for w in why]
    reason = ""
    if told:
        reason = " Neden: en çok %s etkiledi." % (", ".join(told[:-1]) + " ve " + told[-1] if len(told) > 1 else told[0])
    sg["plain"] = ("%s %s için önümüzdeki %d iş gününde %s olasılığı %%%s (örneklem dışı isabet %%%s, %d test, log-loss %s)."
                   % (sg.get("plain") or "", inst.label, HORIZON, up, _pct(prob), _pct(rec["hit"]), rec["tests"], _v(rec["log_loss"], 3))
                   ).strip() + reason
    sg.setdefault("info", {})["why"] = why
    return ("Gradyan artırmalı ağaçlar (aylık yeniden eğitim, yalnız sonraki ayda test) %s için %d iş gününde %s olasılığını %%%s veriyor "
            "(isabet %%%s, %d test, log-loss %s) → %s; beklenen %s%s." % (
                inst.label, HORIZON, up, _pct(prob), _pct(rec["hit"]), rec["tests"], _v(rec["log_loss"], 3), sg["expression"],
                qf.exp_text(sg), qf._incl(sg)))


# ---------------------------------------------------------------------------------------------- the family
class State(object):
    """The last full fit's lines (the backtest's refits and the page read them)."""

    def __init__(self, ctx: qf.Ctx, lines: Dict[str, Line], table: Dict[str, Any]):
        self.ctx, self.lines, self.table = ctx, lines, table
        self.today = ctx.today_iso


_STATE: Optional[State] = None


def reset() -> None:
    """Forget the last fit and every model (tests)."""
    global _STATE
    _STATE = None
    with _MODELS_LOCK:
        _MODELS.clear()


def state() -> Optional[State]:
    return _STATE


@qu.family(FAMILY)
def run(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """The family on the universe: a full fit's (every line's rows, the walk-forward - its models kept -, a monitor for
    each line whose record holds) or a backtest refit's (an earlier day than the last fit's: the walk-forward's own
    predictions, nothing fitted)."""
    st = _STATE
    if st is not None and ctx.today_iso < st.today:
        return _replay(ctx, reg, cfg, st), {"ok": True, "replay": True}
    return _fit(ctx, reg, cfg)


def _replay(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any], st: State) -> List[qf.Monitor]:
    mons = []
    for key, line in st.lines.items():
        inst = reg.get(key)
        if inst is None or not line.preds:
            continue
        rl = Line.__new__(Line)
        rl.__dict__.update(line.__dict__)
        rl.inst = inst                                    # (this refit's instrument: its legs, size and money)
        mons.append(_monitor(rl, cfg, replay=True))
    return mons


def _fit(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    global _STATE
    t0 = time.perf_counter()
    insts, missing = universe(reg)
    inputs = Inputs(reg)
    t_in = time.perf_counter()
    used: Dict[Tuple, Trees] = {}
    lines: Dict[str, Line] = {}
    fitted = cached = 0
    t_rows = t_walk = 0.0
    errors: Dict[str, str] = {}
    for inst in insts:
        try:
            a = time.perf_counter()
            rows, pts, ch, carry = rows_of(inst, inputs)
            b = time.perf_counter()
            wf = walk(inst.key, rows, ctx.today_iso, used)
            t_rows += b - a
            t_walk += time.perf_counter() - b
            fitted += wf["fitted"]
            cached += wf["cached"]
            lines[inst.key] = Line(inst, inputs, rows, pts, ch, carry, wf, cfg)
        except Exception as exc:  # noqa: BLE001 - one line failing is its row's reason, not the family's
            errors[inst.key] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        time.sleep(0)                                     # (the engine thread gets the interpreter between lines)
    with _MODELS_LOCK:                                    # (keep what this fit used: the next fit of the same data fits nothing)
        _MODELS.clear()
        _MODELS.update(used)
    mons = []
    for line in lines.values():
        if line.valid and line.model is not None:
            mons.append(_monitor(line, cfg))
    table = _table(ctx, cfg, insts, lines, missing, errors)
    table["timing"] = {"inputs_ms": round((t_in - t0) * 1000.0, 1), "rows_ms": round(t_rows * 1000.0, 1), "train_ms": round(t_walk * 1000.0, 1),
                       "total_ms": round((time.perf_counter() - t0) * 1000.0, 1), "fitted": fitted, "cached": cached, "lines": len(lines)}
    _STATE = State(ctx, lines, table)
    return mons, table


def _row(line: Line, entry: float, p: Optional[float]) -> Dict[str, Any]:
    inst = line.inst
    prints, why = line.status(entry, p)
    rec = line.rec
    side = (1 if p > 0.5 else -1) if p is not None and p != 0.5 else 0
    tr = line.trades(entry)
    return {"key": inst.key, "label": inst.label, "group": inst.group, "tier": inst.tier, "tag": inst.tag, "n": len(line.L), "rows": len(line.rows),
            "days": rec["days"], "tests": rec["tests"], "hit": rec["hit"], "log_loss": rec["log_loss"], "base": rec["base"], "valid": line.valid,
            "months": len(line.months), "first": line.months[0]["month"] if line.months else None, "p": p, "side": side,
            "verb": inst.verb(side) if side else "", "prob": max(p, 1.0 - p) if p is not None else None,
            "z": (p - 0.5) / Z_SCALE if p is not None else None, "prints": prints, "why": why, "sid": "ml:" + inst.key if line.valid else None,
            "top": [{k: w[k] for k in ("name", "label", "value", "effect", "text")} for w in line.why(line.now[1])] if line.now is not None else [],
            "trades": tr.get("n", 0), "trade_hit": tr.get("hit"), "sharpe": tr.get("sharpe"), "unit": inst.pnl()[0]}


def _table(ctx: qf.Ctx, cfg: Dict[str, Any], insts: List[qu.Instrument], lines: Dict[str, Line], missing: Dict[str, str],
           errors: Dict[str, str]) -> Dict[str, Any]:
    entry = float(cfg["entry_z"])
    live = ctx.derive_live(ctx.live)
    rows = []
    for inst in insts:
        line = lines.get(inst.key)
        if line is None:
            rows.append({"key": inst.key, "label": inst.label, "group": inst.group, "tier": inst.tier, "tag": inst.tag, "prints": False,
                         "why": errors.get(inst.key) or "hesaplanamadı", "top": []})
            continue
        p = line.prob_now(inst.now(live), live)
        rows.append(_row(line, entry, p))
    for key, why in missing.items():
        rows.append({"key": key, "label": key, "group": "", "prints": False, "why": why, "top": []})
    return {"ok": True, "rows": rows, "features": [{"name": n, "label": l, "unit": u} for n, l, u in FEATURES],
            "groups": importance_by_group(lines), "settings": dict(SETTINGS, model_hit=float(cfg["model_hit"]), model_min_tests=int(cfg["model_min_tests"]),
                                                                    entry_z=entry, p_entry=0.5 + Z_SCALE * entry),
            "valid": sum(1 for l in lines.values() if l.valid), "lines": len(lines)}


def importance_by_group(lines: Dict[str, Line]) -> Dict[str, Any]:
    """Each feature's share of the split gain of today's models, per group (each line's shares averaged over its
    group): ``{"groups": [...], "rows": [{name, label, shares: {group: share}}]}``."""
    per: Dict[str, List[List[float]]] = {}
    for line in lines.values():
        if line.model is not None and sum(line.model.gain) > 0:
            per.setdefault(line.inst.group, []).append(line.model.importance())
    groups = [g for g in qu.GROUPS if g in per]
    rows = []
    for j, (name, label, _) in enumerate(FEATURES if groups else ()):           # (no model anywhere: no table)
        shares = {g: sum(v[j] for v in per[g]) / len(per[g]) for g in groups}
        rows.append({"name": name, "label": label, "shares": shares})
    rows.sort(key=lambda r: -max(r["shares"].values()))
    return {"groups": groups, "rows": rows, "models": {g: len(per[g]) for g in groups}}


# ---------------------------------------------------------------------------------------------- the page
def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "Makine öğrenmesi" reads: the lines with today's probability now (the live features where the
    fit's lines are at hand) and the three features behind it, the features' shares per group, the family's signals."""
    from .quant import _clean
    tab = dict(((fit.get("tables") or {}).get(FAMILY) or {}))
    st = _STATE
    ctx = fit.get("ctx")
    if st is not None and ctx is not None and st.today == fit.get("today"):          # (the lines of this day's data)
        entry = float(fit["cfg"]["entry_z"])
        live = ctx.derive_live(ctx.live)
        rows = []
        for r in tab.get("rows") or []:
            line = st.lines.get(r.get("key"))
            if line is None:
                rows.append(r)
                continue
            rows.append(_row(line, entry, line.prob_now(line.inst.now(live), live)))
        tab["rows"] = rows
    # (a line past the rule and the entry that a gate of the list holds - the FX carry buffer, no expected profit -
    # is in the list as "düşük güven": the page says so and why)
    held = {s["id"]: s["gated"] for s in v["gated"] if s["family"] == FAMILY}
    tab["rows"] = [dict(r, prints=False, why="düşük güven: " + held[r["sid"]]) if r.get("prints") and held.get(r.get("sid")) else r
                   for r in tab.get("rows") or []]
    base["ml"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["family"] == FAMILY]
    base["settings"] = fit["cfg"]
    keys = {r.get("key") for r in tab.get("rows") or ()} | {k for _, k in DRIVERS} | set(CURVE) | {"TLREF"}
    base["coverage"] = [c for c in fit.get("coverage") or () if c.get("key") in keys]
    base["errors"] = {k: e for k, e in ((v.get("tables") or {}).get("errors") or {}).items() if k == FAMILY}
    return _clean(base)
