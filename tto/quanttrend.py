"""Trend: volatility-targeted time-series momentum on every line of the quant universe (``quantuniv``) - the first of
the three systematic families of the plan of 16.11.2026.

**The score.**  Each instrument's return over 1, 3 and 12 months (21, 63 and 252 business days) in its own P&L unit:
an FX line's with its carry (what a long earns or pays: the spot's from its forwards, a forward's and a swap point's
roll towards the spot), a rate's, a DİBS yield's, a spread's, a fly's in bp of its level, a vol's in vol points; each
over the instrument's daily volatility (σ of its last 60 daily P&L moves) × √days; the score is their mean, clipped to
±2.  With less than a year of closes the long horizon is all there is; with less than 63 there is no line.  Every
number is the level's up side's, as the universe has it ("AL", "pay", "vol al", "steepener", "SAT" for a DİBS yield):
a score above 0 plays the rise, below 0 the fall.

**The line.**  One a day for every instrument, no gate: a weak score is a weak line (Zayıf below 0,5, Orta below 1,
Güçlü from 1); its group sorts it by its expectancy (``quantuniv.order``), a line whose direction turned since the
previous close says "YENİ".  Its size: the desk's unit scaled to the same daily risk - the desk setting
``trend_risk_usd`` over the line's daily σ in money (USD), two significant figures, 0,1 – 10 units: "EURUSD 1,4 mn",
"2Y OIS 370 $ DV01".  **No target; a trailing stop** k σ behind the best level since the entry (σ: a month's, the
daily σ × √21), k calibrated on the family's own past trades (``tto.quantlevels``, "trail": every position from a
turn to the next turn, its path in that σ, month by month on what had happened before - its group's, the family's where
the group has too few): the k with the best expectancy whose average winner is at least k (Ödül / risk = the average
winning trade ÷ k ≥ 1).  The line: "iz süren stop", its record at that k (isabet: the share of trades closed in profit,
out of sample) and the expectancy × σ now in money; its holding the record's mean.  Held until the direction turns or
the trailing stop.  A line whose stop lost money all the same is "düşük güven" (it stays in the list).  Without enough
trades for a calibration the old rule stands: the mean gain of the past daily lines of the same strength (|score| in
[0, 0,5), [0,5, 1), [1, 1,5), [1,5, 2]) over their holding as the target, 2σ of the holding against as the stop.

**The walk-forward.**  Every past day's line as it was drawn that day - its score from the closes up to it, its stop
from the holdings closed by then - followed to its turn or its stop: the strength buckets' gains and holdings, each
instrument's trades (a position from a turn, or the first day, to the next turn or the stop) with their hit rate, the
daily P&L of the risk-equal positions and its Sharpe.  Nothing after a day decides on that day.  The live refresh only
scores the lines again with the values now (``zfn``); the walk runs on the full fit and on each backtest refit.
"""
from __future__ import annotations

import bisect
import copy
import datetime as _dt
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf
from . import quantlevels as qlv
from . import quantuniv as qu

# ---------------------------------------------------------------------------------------------- the model's constants
HORIZONS = (21, 63, 252)        # business days: 1, 3 and 12 months
HREF = 21.0                     # a trade's σ: a month's (the daily σ × √21) - the trailing stop's and the record's unit
H_LABELS = ("1A", "3A", "1Y")
MIN_DAYS = 63                   # closes a line needs (the 3-month horizon)
VOL_DAYS = qu.VOL_DAYS          # the daily σ: over the last 60 P&L moves
MIN_VOL = 20                    # moves before a σ is one
CLIP = 2.0                      # |score| at most
EDGES = (0.5, 1.0, 1.5)         # the strength buckets of |score|: [0, 0,5), [0,5, 1), [1, 1,5), [1,5, 2]
BUCKETS = ("0–0,5", "0,5–1", "1–1,5", "1,5–2")
STRONG = 1.0                    # |score| from here: Güçlü (Orta from 0,5)
STOP_SIGMA = 2.0                # the stop: 2σ of the holding against
HOLD0 = 21.0                    # the holding before the walk has closed enough lines (business days)
MIN_SIGNALS = 40                # a bucket's closed daily lines before its own mean counts (else the family's)
MIN_TRADES = 10                 # an instrument's closed trades before its own hit rate is shown (else its group's)
K_RANGE = (0.1, 10.0)           # the size, in the desk's unit: a line that barely moves is not levered without end
ENTRY_ANY = 1e-9                # make_signal's threshold: every line, whatever its score (no gate)
YEAR = 252.0

#: the desk's setting (tto.quant takes it into its own): the daily risk every Trend line is sized to
DEFAULTS: Dict[str, Any] = {"trend_risk_usd": 5000.0}
LIMITS: Dict[str, Tuple[float, float, type]] = {"trend_risk_usd": (100.0, 1e7, float)}
LABELS: Dict[str, str] = {"trend_risk_usd": "Trend · hedef günlük risk (USD, satır başına)"}

#: the page (a tab of the Sinyaller entry) and the view it reads (``/api/quant/trend``)
PAGES = (("quant-trend", "Trend"),)
VIEWS = {"trend": "quant-trend"}

NOTE = ("Skor: 1A, 3A ve 1Y getirisinin (enstrümanın kendi K/Z biriminde: FX'te carry dahil, faizde ve fly / spread'de bp, "
        "vol'de vol puanı) günlük σ × √gün'e bölümünün ortalaması, ±2 ile sınırlı; + ise yükselişe (AL, pay, vol al), − ise "
        "düşüşe oyna. Büyüklük: her satır aynı günlük riske (masa ayarı). Hedef: geri testte aynı güçteki geçmiş günlük "
        "satırların tutma boyunca ortalama kazancı; stop: tutmanın 2σ'sı; yön dönene ya da stopa kadar tutulur.")


def sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def bucket(a: float) -> int:
    """The strength bucket of |score| (0 … 3)."""
    return bisect.bisect_right(EDGES, a)


def strength(score: float) -> str:
    a = abs(score)
    return "Güçlü" if a >= STRONG else ("Orta" if a >= EDGES[0] else "Zayıf")


def round2(k: float) -> float:
    """Two significant figures: 1,43 → 1,4; 0,372 → 0,37 (a size the desk says)."""
    if not k or k <= 0 or not math.isfinite(k):
        return k
    e = math.floor(math.log10(k)) - 1
    return round(k / 10.0 ** e) * 10.0 ** e


def _finite(v: Any) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


# ---------------------------------------------------------------------------------------------- one instrument's P&L
def _carry_rates(inst: qu.Instrument, days: Sequence[str], lv: Sequence[float]) -> List[Optional[float]]:
    """Each close's carry of the up side, in change units a calendar day (``None``: none known): a forward's roll
    towards the spot ((ln S − ln F) ÷ its days, % a day of a long), a spot's from that day's forwards (the universe's
    ``carry_days``: % a year, a close within a week), a swap point's roll (its points ÷ its days, lost by "pay").  A
    rate's, a vol's, a spread's: none (the history has no carry engine)."""
    out: List[Optional[float]] = [None] * len(days)
    if isinstance(inst, qu.FxForward):
        spot = inst.ctx.series.get("FX:" + inst.pair) or {}
        for i, (d, f) in enumerate(zip(days, lv)):
            s = spot.get(d)
            if s and f and s > 0 and f > 0 and inst.inst_days:
                out[i] = (math.log(s) - math.log(f)) * 100.0 / inst.inst_days
        return out
    if isinstance(inst, qu.FxSpot):
        known = sorted((d, c) for d, c in (inst.carry_days() or {}).items() if _finite(c))
        j, last = 0, None
        for i, d in enumerate(days):
            while j < len(known) and known[j][0] <= d:
                last = known[j]
                j += 1
            if last is not None and (_dt.date.fromisoformat(d) - _dt.date.fromisoformat(last[0])).days <= 7:
                out[i] = last[1] / 365.0
        return out
    if isinstance(inst, qu.SwapPoints) and inst.days_t:
        return [-p / inst.days_t for p in lv]
    return out


def track(inst: qu.Instrument) -> Dict[str, Any]:
    """The instrument's closes (the rolls' jumps out) as a P&L index ``x`` (change units, carry in), its daily moves
    ``dx``, σ, and each close's score, horizon terms and direction - all from the closes up to that day."""
    pts = inst.adjusted()
    days = [d for d, _ in pts]
    lv = [v for _, v in pts]
    n = len(lv)
    dates = [_dt.date.fromisoformat(d) for d in days]
    rate = _carry_rates(inst, days, lv)
    carry = any(r is not None for r in rate)
    dx = [0.0] * n
    x = [0.0] * n
    kind = inst.kind
    log = math.log
    for t in range(1, n):
        a, b = lv[t - 1], lv[t]
        if kind == "rate":
            c = (b - a) * 100.0
        elif kind in ("fx", "index"):
            c = log(b / a) * 100.0 if a > 0 and b > 0 else 0.0
        else:
            c = b - a
        if carry:
            r = rate[t - 1]
            if r is not None:
                c += r * (dates[t] - dates[t - 1]).days
        dx[t] = c
        x[t] = x[t - 1] + c
    # σ of the last VOL_DAYS moves at every close (running sums)
    sig: List[Optional[float]] = [None] * n
    s1 = s2 = 0.0
    for t in range(1, n):
        v = dx[t]
        s1 += v
        s2 += v * v
        if t > VOL_DAYS:
            o = dx[t - VOL_DAYS]
            s1 -= o
            s2 -= o * o
        m = min(t, VOL_DAYS)
        if m >= MIN_VOL:
            var = (s2 - s1 * s1 / m) / (m - 1)
            sig[t] = math.sqrt(var) if var > 1e-18 else 0.0
    score: List[Optional[float]] = [None] * n
    terms: List[Optional[Tuple[float, float, float]]] = [None] * n
    d = [0] * n
    r1, r3 = math.sqrt(HORIZONS[0]), math.sqrt(HORIZONS[1])
    for t in range(MIN_DAYS, n):
        sg = sig[t]
        if not sg:
            continue
        hl = min(HORIZONS[2], t)
        xt = x[t]
        tt = ((xt - x[t - HORIZONS[0]]) / (sg * r1), (xt - x[t - HORIZONS[1]]) / (sg * r3), (xt - x[t - hl]) / (sg * math.sqrt(hl)))
        sc = (tt[0] + tt[1] + tt[2]) / 3.0
        sc = CLIP if sc > CLIP else (-CLIP if sc < -CLIP else sc)
        score[t], terms[t], d[t] = sc, tt, sign(sc)
    # each close's next turn: the first later close whose direction is another (n: none before the end)
    turn = [n] * n
    for t in range(n - 2, -1, -1):
        turn[t] = t + 1 if d[t + 1] != d[t] else turn[t + 1]
    return {"days": days, "dates": dates, "lv": lv, "n": n, "rate": rate, "carry": carry, "dx": dx, "x": x, "sig": sig, "score": score,
            "terms": terms, "d": d, "turn": turn}


def _no_track() -> Dict[str, Any]:
    """An instrument without a readable series: no close, no line."""
    return {"days": [], "dates": [], "lv": [], "n": 0, "rate": [], "carry": False, "dx": [], "x": [], "sig": [], "score": [],
            "terms": [], "d": [], "turn": []}


def score_now(tr: Dict[str, Any], kind: str, level: Optional[float], today: _dt.date, rolled: bool = False
              ) -> Optional[Tuple[float, Tuple[float, float, float], int]]:
    """The score with the level now (the closes before today, then ``level``): (score, the three terms, the long
    horizon's days).  ``rolled``: today the series moved to its next period - its move today is no market move."""
    n = tr["n"]
    if n < MIN_DAYS or level is None or not _finite(level):
        return None
    sg = tr["sig"][-1]
    if not sg:
        return None
    move = 0.0 if rolled else qf.change(kind, tr["lv"][-1], level)
    if move is None or not math.isfinite(move):
        return None
    r = tr["rate"][-1]
    if r is not None:
        move += r * max(0, (today - tr["dates"][-1]).days)
    x = tr["x"]
    xn = x[-1] + move
    hl = min(HORIZONS[2], n)
    tt = ((xn - x[n - HORIZONS[0]]) / (sg * math.sqrt(HORIZONS[0])), (xn - x[n - HORIZONS[1]]) / (sg * math.sqrt(HORIZONS[1])),
          (xn - x[n - hl]) / (sg * math.sqrt(hl)))
    sc = (tt[0] + tt[1] + tt[2]) / 3.0
    return max(-CLIP, min(CLIP, sc)), tt, hl


# ---------------------------------------------------------------------------------------------- the walk-forward
def _follow(tr: Dict[str, Any], t: int, stop: float) -> Tuple[Optional[int], str, float]:
    """The line drawn at close ``t``, held until its direction turns or ``stop`` (change units) against: (the exit
    close or ``None`` - still open -, why, its gain)."""
    x, n = tr["x"], tr["n"]
    s = tr["d"][t]
    x0 = x[t]
    f = tr["turn"][t]
    end = f + 1 if f < n else n                          # (the turn's own close: its stop first)
    if end > t + 1:
        if s > 0:
            thr = x0 - stop
            if min(x[t + 1:end]) <= thr:                 # (most lines end at their turn: a C-speed look first)
                for u in range(t + 1, end):
                    if x[u] <= thr:
                        return u, "stop", x[u] - x0
        else:
            thr = x0 + stop
            if max(x[t + 1:end]) >= thr:
                for u in range(t + 1, end):
                    if x[u] >= thr:
                        return u, "stop", x0 - x[u]
    if f < n:
        return f, "dönüş", s * (x[f] - x0)
    return None, "açık", s * (x[n - 1] - x0)


#: a line's statistics, most particular first: (key, scope) - the instrument's own lines of its strength, its group's,
#: the family's, the family's of every strength
def _scopes(i: int, group: str, b: int) -> Tuple[Tuple[Tuple[Any, int], str], ...]:
    return (((i, b), "enstrüman"), ((group, b), group), (("*", b), "aile"), (("*", -1), "aile, tüm güçler"))


def bucket_stats(pooled: Dict[Tuple[Any, int], List[float]], i: int, group: str, b: int) -> Dict[str, Any]:
    """A line's past daily lines of its strength - the instrument's own when it has enough, else its group's, else
    the family's: ``{gain (σ of each line's day), hold (days), hit, n, scope}``."""
    for key, scope in _scopes(i, group, b):
        st = pooled.get(key)
        if st and st[0] >= MIN_SIGNALS:
            return {"gain": st[1] / st[0], "hold": st[2] / st[0], "hit": st[3] / st[0], "n": int(st[0]), "scope": scope}
    return {"gain": 0.0, "hold": HOLD0, "hit": None, "n": 0, "scope": "yok"}


def walk(tracks: Sequence[Dict[str, Any]], groups: Sequence[str]) -> Tuple[Dict[Tuple[Any, int], List[float]], List[List[Optional[tuple]]]]:
    """Every past day's line of every instrument as it was drawn that day, day by day across the universe: its stop
    2σ of the mean holding of the lines of its strength by then, followed to its turn or its stop.  The lines by then:
    the closed ones and the ones still open, these with their holding so far (left out, every trend still running
    would be missing: only the turned ones would count).  ``(pooled, lines)``: each (key, bucket)'s lines at the last
    close - [n, Σ gain in σ of its day, Σ holding, hits], the open ones marked at their last close; a key the
    instrument's index, its group, "*" the family (bucket -1: every strength) - and per instrument per close its
    line's (exit, why, gain, bucket, holding its stop used)."""
    every = sorted({d for tr in tracks for d in tr["days"]})
    at = {d: j for j, d in enumerate(every)}
    by_day: Dict[str, List[Tuple[int, int]]] = {}
    for i, tr in enumerate(tracks):
        days, d = tr["days"], tr["d"]
        for t in range(tr["n"]):
            if d[t]:
                by_day.setdefault(days[t], []).append((i, t))
    # one accumulator a (key, bucket): [closed n, Σ gain σ, Σ holding, hits, open n, Σ the day each open one was drawn];
    # each instrument's strength its four, most particular first
    accs: Dict[Tuple[Any, int], List[float]] = {}

    def acc(key: Tuple[Any, int]) -> List[float]:
        a = accs.get(key)
        if a is None:
            a = accs[key] = [0, 0.0, 0.0, 0, 0, 0]
        return a

    slots = [[[acc(key) for key, _ in _scopes(i, groups[i], b)] for b in range(len(BUCKETS))] for i in range(len(tracks))]
    pending: Dict[str, List[Tuple[List[List[float]], float, int, int]]] = {}
    lines: List[List[Optional[tuple]]] = [[None] * tr["n"] for tr in tracks]
    sqrt = math.sqrt
    for j, day in enumerate(every):
        # (what closed at today's close is known at today's close: before today's lines are drawn)
        for sl, gs, hit, j0 in pending.pop(day, ()):
            for a in sl:
                a[4] -= 1
                a[5] -= j0
                a[0] += 1
                a[1] += gs
                a[2] += j - j0
                a[3] += hit
        drawn = []
        for i, t in by_day.get(day, ()):
            tr = tracks[i]
            sg = tr["sig"][t]
            b = bucket(abs(tr["score"][t]))
            sl = slots[i][b]
            hold = HOLD0
            for a in sl:
                cnt = a[0] + a[4]
                if cnt >= MIN_SIGNALS:
                    hold = max(1.0, (a[2] + a[4] * j - a[5]) / cnt)
                    break
            u, why, gain = _follow(tr, t, STOP_SIGMA * sg * sqrt(hold))
            lines[i][t] = (u, why, gain, b, hold)
            drawn.append(sl)
            if u is not None:
                pending.setdefault(tr["days"][u], []).append((sl, gain / sg, 1 if gain > 0 else 0, j))
        for sl in drawn:                                    # (today's lines count from tomorrow: no order among them)
            for a in sl:
                a[4] += 1
                a[5] += j
    # at the last close: the closed lines and the open ones, marked there
    pooled = {k: [a[0], a[1], a[2], a[3]] for k, a in accs.items()}
    for i, tr in enumerate(tracks):
        if not tr["n"]:
            continue
        x, d, sig, days, n = tr["x"], tr["d"], tr["sig"], tr["days"], tr["n"]
        j_last = at[days[-1]]
        keys = [[key for key, _ in _scopes(i, groups[i], b)] for b in range(len(BUCKETS))]
        for t in range(n):
            ln = lines[i][t]
            if ln is None or ln[0] is not None:
                continue
            gs = d[t] * (x[n - 1] - x[t]) / sig[t]
            for key in keys[ln[3]]:
                c = pooled[key]
                c[0] += 1
                c[1] += gs
                c[2] += j_last - at[days[t]]
                c[3] += 1 if gs > 0 else 0
    return pooled, lines


def trades_of(tr: Dict[str, Any], lines: List[Optional[tuple]]) -> Dict[str, Any]:
    """The instrument's trades - the line of its first scored day and of every turn, held to the next turn or its stop
    (after a stop: none until the next turn) - and the daily P&L of that position in σ of the day before (``pnl``:
    {day: σ}, flat days 0)."""
    d, dx, sig, days, n = tr["d"], tr["dx"], tr["sig"], tr["days"], tr["n"]
    out: List[Dict[str, Any]] = []
    pnl: Dict[str, float] = {}
    first = None
    for t in range(n):
        if not d[t] or lines[t] is None or (t > 0 and d[t - 1] == d[t]):
            continue
        u, why, gain, b, hold = lines[t]
        out.append({"entry": days[t], "exit": days[u] if u is not None else None, "dir": d[t], "why": why, "gain": gain,
                    "gain_sigma": gain / sig[t] if sig[t] else None, "held": (u if u is not None else n - 1) - t, "i": t,
                    "u": u if u is not None else n - 1})
        if first is None:
            first = t
    if first is not None:
        for tau in range(first + 1, n):
            pnl[days[tau]] = 0.0
        for tr_ in out:
            s = tr_["dir"]
            for tau in range(tr_["i"], tr_["u"]):
                sg = sig[tau]
                if sg:
                    pnl[days[tau + 1]] = s * dx[tau + 1] / sg
    closed = [x for x in out if x["exit"] is not None]
    return {"trades": out, "closed": len(closed), "hits": sum(1 for x in closed if x["gain"] > 0), "pnl": pnl}


def level_trades(insts: Sequence[qu.Instrument], tracks: Sequence[Dict[str, Any]], money: Optional[Dict[str, float]] = None
                 ) -> List[Dict[str, Any]]:
    """Every position of the walk (a turn, or the first scored day, to the next turn) as ``quantlevels``' trade - its
    path to the turn, in σ of a month as known at its entry (the daily σ of its P&L index × √21), its carry in it;
    one still running is open (marked at the last close).  ``money``: TRY a change unit at the line's size, by key."""
    out: List[Dict[str, Any]] = []
    root = math.sqrt(HREF)
    for inst, tr in zip(insts, tracks):
        d, x, sig, days, n, turn = tr["d"], tr["x"], tr["sig"], tr["days"], tr["n"], tr["turn"]
        try_per = (money or {}).get(inst.key)
        for t in range(n):
            s = d[t]
            if not s or (t > 0 and d[t - 1] == s) or not sig[t]:
                continue
            unit = sig[t] * root
            f = turn[t]
            end = f if f < n else n - 1
            x0 = x[t]
            out.append({"family": "trend", "group": inst.group, "sid": "trend:" + inst.key, "entry_day": days[t], "days": days[t + 1:end + 1],
                        "path_sigma": [s * (x[u] - x0) / unit for u in range(t + 1, end + 1)], "open": f >= n, "carry_sigma": 0.0,
                        "carry_in": bool(tr["carry"]), "sigma": unit, "unit": qf.change_unit(inst.kind), "try": try_per})
    return out


def sharpe(values: Sequence[float]) -> Optional[float]:
    """Annualised Sharpe of daily P&L (mean ÷ σ × √252)."""
    xs = [v for v in values if v is not None]
    if len(xs) < 20:
        return None
    m = sum(xs) / len(xs)
    var = sum((v - m) ** 2 for v in xs) / (len(xs) - 1)
    return m / math.sqrt(var) * math.sqrt(YEAR) if var > 1e-18 else None


def _portfolio(pnls: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """Risk-equal positions together: each day's P&L (σ) summed over the instruments."""
    out: Dict[str, float] = {}
    for p in pnls:
        for day, v in p.items():
            out[day] = out.get(day, 0.0) + v
    return out


# ---------------------------------------------------------------------------------------------- the family
def _usd(inst: qu.Instrument, amount: Optional[float], usdtry: Optional[float]) -> Optional[float]:
    if amount is None or not math.isfinite(amount):
        return None
    if inst.ccy in ("TL", "TRY"):
        return amount / usdtry if usdtry else None
    return amount


def _rolled_today(inst: qu.Instrument, state: Dict[str, Any]) -> bool:
    """A PPK period whose meeting today is another than the last close's (it rolled today: its jump is no move)."""
    if not isinstance(inst, qu.PpkPeriod):
        return False
    day = inst.ctx.today_iso
    hit = state.get("rolled")
    if hit is None or hit[0] != day:
        a, b = inst._row(True), inst._row(False)
        hit = state["rolled"] = (day, bool(a and b and a[1] != b[1]))
    return hit[1]


def _horizon_words(terms: Sequence[float], s: int, labels: Sequence[str]) -> str:
    """Which horizons agree with the line: "üç ufuk da yükselişte", "üç ufuktan ikisi düşüşte (1A ve 3A; 1Y ters)"."""
    word = "yükselişte" if s > 0 else "düşüşte"
    marks = ", ".join("%s %s" % (lab, "↑" if t > 0 else ("↓" if t < 0 else "→")) for lab, t in zip(labels, terms))
    agree = [lab for lab, t in zip(labels, terms) if sign(t) == s]
    other = [lab for lab, t in zip(labels, terms) if sign(t) != s]
    if len(agree) == len(labels):
        text = "üç ufuk da %s" % word
    elif len(agree) == 2:
        text = "üç ufuktan ikisi %s (%s ve %s; %s ters)" % (word, agree[0], agree[1], other[0])
    elif len(agree) == 1:
        text = "üç ufuktan yalnız %s %s, ortalama da o yönde" % (agree[0], word)
    else:
        text = "ortalama %s" % word
    return "%s - %s" % (marks, text)


def _price(sg: Dict[str, Any], which: str) -> str:
    """The line's entry / target / stop in the instrument's own price (an FX line's: px)."""
    px = sg.get("px")
    if px is not None:
        v = px.get(which)
        return qf._th(v, px.get("digits") or 4) if v is not None else "—"
    return qf._level_text(sg.get(which), sg.get("unit") or "", sg.get("digits") or 2)


def _money_at(sg: Dict[str, Any], key: str, k: float, ccy: str) -> Tuple[Optional[float], str]:
    """The card's money at the line's size, in the line's currency: an FX card's is per 1 mn of the base in the quote
    currency (× k; a G10 line's in USD, as the universe tells it: USDJPY's yen at the card's USD a yen), the others' at
    k already."""
    mo = sg.get("money") or {}
    v = mo.get(key)
    if v is None:
        return None, ccy
    if sg.get("px") is None:
        return v, mo.get("ccy") or ccy
    v *= k
    if mo.get("ccy") == ccy or ccy != "USD":
        return v, mo.get("ccy") or ccy
    return (v * mo["usd_per"], "USD") if mo.get("usd_per") else (v, mo.get("ccy") or ccy)


def _hit_text(stats: Dict[str, Any]) -> str:
    """ "isabet %58 (41)", the group's: "isabet %55 (120, grup)"."""
    if not stats.get("trades"):
        return "isabet — (0)"
    return "isabet %%%s (%d%s)" % (qf._g((stats.get("hit") or 0.0) * 100.0, 0), stats["trades"], ", grup" if stats.get("scope") == "grup" else "")


def _levels_hit(lv: Dict[str, Any]) -> str:
    """ "isabet %61 (148)": the calibrated trailing stop's record (out of sample)."""
    if not lv.get("n"):
        return "isabet — (0)"
    return "isabet %%%s (%d)" % (qf._g((lv.get("hit") or 0.0) * 100.0, 0), lv["n"])


def _sigma_text(sg: Dict[str, Any]) -> str:
    """The trailing stop's σ in the line's own price: "0,0123" / "12,5 bp"."""
    lv = sg.get("levels") or {}
    v = lv.get("sigma_lv")
    if v is None:
        return "—"
    v = abs(v)
    px = sg.get("px")
    if px is not None and sg.get("entry") and px.get("entry"):
        return qf._th(v * px["entry"] / sg["entry"], px.get("digits") or 4)
    unit = sg.get("unit") or ""
    if unit == "%":
        return "%s bp" % qf._g(v * 100.0, 1)                          # (a rate's σ in bp)
    if unit == "bp":
        return "%s bp" % qf._g(v, 1)
    return ("%s %s" % (qf._g(v, 2), unit)).strip()


def _record_text(stats: Dict[str, Any]) -> str:
    """The card's: "Geri test: isabet %58 (41 işlem), Sharpe 0,62." - the group's trades when the instrument has few."""
    if not stats.get("trades"):
        head = "Geri test: henüz kapanan işlem yok"
    else:
        head = "Geri test: isabet %%%s (%d işlem%s)" % (qf._g((stats.get("hit") or 0.0) * 100.0, 0), stats["trades"],
                                                       "; grubun - bu enstrümanda %d" % (stats.get("own_trades") or 0)
                                                       if stats.get("scope") == "grup" else "")
    return head + (", Sharpe %s." % qf._g(stats["sharpe"], 2) if stats.get("sharpe") is not None else ".")


class _Line(object):
    """What a Trend monitor keeps: the instrument, its walk, its size and statistics - and, scored, the line now."""

    def __init__(self, inst: qu.Instrument, tr: Dict[str, Any], k: float, stats: Dict[str, Any], buckets: List[Dict[str, Any]],
                 cfg: Dict[str, Any], lv: Optional[Dict[str, Any]] = None):
        self.inst = inst
        self.tr = tr
        self.k = k
        self.stats = stats
        self.buckets = buckets
        self.cfg = cfg
        self.lv = lv or {"ok": False, "why": "seviye kalibrasyonu yok"}     # (its group's trailing stop: quantlevels)
        n = tr["n"]
        self.sigma = tr["sig"][-1]
        self.d_prev = tr["d"][-1] if n else 0
        run = 0
        for t in range(n - 1, -1, -1):
            if tr["d"][t] != self.d_prev or not self.d_prev:
                break
            run += 1
        self.run = run
        self.labels = H_LABELS[:2] + ((H_LABELS[2] if min(HORIZONS[2], n) >= HORIZONS[2] else "%d g" % min(HORIZONS[2], n)),)
        self.now: Optional[Dict[str, Any]] = None
        self.mon: Optional[qf.Monitor] = None
        self.state: Dict[str, Any] = {}

    # ---- the score now, and the decision that goes with its strength
    def zfn(self, level: Optional[float], live: Dict[str, float]) -> Optional[float]:
        inst = self.inst
        r = score_now(self.tr, inst.kind, level, inst.ctx.today, _rolled_today(inst, self.state))
        if r is None:
            self.now = None
            return None
        score, terms, hl = r
        self.now = {"score": score, "terms": terms, "h_long": hl, "level": level}
        self.decide(score, level, live)
        return score

    def decide(self, score: float, level: float, live: Optional[Dict[str, float]] = None) -> None:
        """The levels make_signal reads.  Calibrated (``self.lv``): no target, the trailing stop k σ of a month behind
        the best level (here: from the entry now), the record's holding and expectancy (× σ now).  Without: the
        strength's bucket - its mean gain (σ of each line's day × σ now) the expected P&L (an FX line's and a swap
        point's with its carry in it, as the walk had them; a rate's the move alone: make_signal adds the carry engine's
        carry + roll), the target the level's own move that, with the holding's carry, makes it (none when the gain is
        no gain; the entry when the carry alone makes it), the stop 2σ of the holding against."""
        m = self.mon
        if m is None or not self.sigma:
            return
        b = bucket(abs(score))
        st = self.buckets[b]
        inst = self.inst
        kind = inst.kind
        s = sign(score)
        lv = self.lv
        if lv.get("ok"):
            unit = self.sigma * math.sqrt(HREF)                         # change units: a month's σ
            m.hold = max(1.0, float(lv.get("held") or HOLD0))
            m.levels = dict(lv, sigma=qf.to_level(kind, unit, level))
            m.reward, m.risk = 0.0, qf.to_level(kind, float(lv["k"]) * unit, level)
            m.fcast = s * qf.to_level(kind, float(lv.get("exp") or 0.0) * unit, level)
            self.now = dict(self.now or {}, bucket=b, b=st, gain=None, move=None, carry=None)
            return
        m.levels = lv                                                   # (the card says why there are none)
        hold = st["hold"]
        gain = st["gain"] * self.sigma                                  # change units, in the line's favour
        carry = 0.0                                                     # the part of it the position's carry makes
        if inst.fx:
            cal = hold * 7.0 / 5.0                                      # (as quantfam.fx_info has the holding's carry)
            try:
                c = inst.ctx.fx_carry(inst.fx, inst.reg.live if live is None else live, days=cal)
            except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                c = None
            carry = s * c * cal / 365.0 if c is not None else 0.0
            fcast = gain                                                # (make_signal adds no carry to an FX line's)
        elif self.tr["carry"]:
            carry = s * (m.carry_up or 0.0) * hold / 5.0                # (make_signal adds this carry to the move)
            fcast = gain - carry
        else:
            fcast = gain
        move = gain - carry
        m.hold = hold
        m.reward = qf.to_level(kind, max(move, 0.0), level)
        m.risk = qf.to_level(kind, STOP_SIGMA * self.sigma * math.sqrt(hold), level)
        m.fcast = s * qf.to_level(kind, fcast, level)
        self.now = dict(self.now or {}, bucket=b, b=st, gain=gain, move=move, carry=carry)

    # ---- the signal as the desk reads it
    def finish(self, sg: Dict[str, Any]) -> None:
        """make_signal's line made Trend's: no gate, its strength and rank by |score|, "YENİ", the plan's one-line
        format, the plain sentence (what, why, what is expected, target and stop in money), the walk's statistics."""
        now = self.now or {}
        inst = self.inst
        score = float(sg["z"])
        s = int(sg["direction"])
        cfg = self.cfg
        base = min(abs(score) * float(cfg.get("entry_z") or 2.0), float(cfg.get("stop_z") or 3.5))
        new = s != self.d_prev
        days_in = 0 if new else self.run
        b = now.get("b") or self.buckets[bucket(abs(score))]
        terms = now.get("terms") or (0.0, 0.0, 0.0)
        k = self.k
        exp_m, ccy = _money_at(sg, "total", k, inst.ccy)
        tgt_m, _ = _money_at(sg, "target", k, inst.ccy)
        stp_m, _ = _money_at(sg, "stop", k, inst.ccy)
        # the target: a level move to it; the entry when the carry alone makes the expected gain; none without a gain
        has_target = (sg.get("reward") or 0.0) > 0.0
        by_carry = not has_target and (sg.get("exp_pnl") or 0.0) > 0.0
        stats = self.stats
        # the calibrated trailing stop (quantlevels): no target; a stop that lost money all the same is "düşük güven"
        lv = sg.get("levels") or {}
        trail = bool(lv.get("ok")) and lv.get("rule") == "trail"
        loss = trail and (lv.get("exp") or 0.0) < 0.0
        # (``daily``: a line every day, held until its direction turns or its stop - the log, the alerts and the backtest
        # follow it so: tto.quant._track, quantbt.backtest; the gates of make_signal are none of its, but its levels')
        sg.update({"strength": strength(score), "gated": qf.LEVELS_LOSS if loss else "",
                   "gates": [g for g in sg.get("gates") or () if g.get("name") == "Seviyeler"], "composite": 0.0 if loss else base,
                   "parts": {"z": base, "regime": 1.0, "hl": 1.0, "carry": 1.0}, "entry_z": STRONG,
                   "expression": "%s %s" % (inst.verb(s), inst.label), "new": new, "days_in": days_in, "daily": True})
        if trail:
            parts = (["YENİ"] if new else []) + [inst.line(s, k), "giriş " + _price(sg, "entry"), "iz süren stop " + _price(sg, "stop"),
                                                  "beklenen " + qf._money(exp_m, ccy), _levels_hit(lv), "model: Trend"]
        else:
            parts = (["YENİ"] if new else []) + [inst.line(s, k), "giriş " + _price(sg, "entry"),
                                                  "hedef " + (_price(sg, "target") if has_target or by_carry else "—"), "stop " + _price(sg, "stop"),
                                                  "beklenen " + qf._money(exp_m, ccy), _hit_text(stats), "model: Trend"]
        sg["line"] = " · ".join(parts)
        incl = " (forward primi dahil)" if sg.get("px") is not None and sg.get("carry_h") is not None else (
            " (carry + roll dahil)" if sg.get("carry_h") is not None else "")
        hold = sg.get("hold")
        span = "~%s iş günü" % qf._g(hold, 0) if hold else "tutma boyunca"
        head = ("YENİ - yön bugün döndü. " if new else "") + "%s." % inst.line(s, k)
        why = "Neden: %s (skor %s, %s; %s)." % (_horizon_words(terms, s, self.labels), qf._sg(score, 2), strength(score).lower(),
                                                "yön bugün döndü" if new else "%d gündür bu yönde" % days_in)
        if trail:
            exp = ("Beklenen: %s tutarsan %s%s - iz süren stopla geçmiş işlemlerin ortalaması (%s, %d işlem)." % (
                span, qf._money(exp_m, ccy), incl, "örneklem dışı" if lv.get("oos") else "örneklem içi", lv.get("n") or 0)
                if exp_m is not None else "Beklenen: —.")
            ends = ("Hedef yok - iz süren stop: en iyi seviyeden %s σ geri gelirse (σ: aylık, %s) ya da yön dönerse çık; stop şimdi %s (%s). "
                    "Ödül / risk %s: kazanan işlemlerin ortalaması %s σ ÷ stop %s σ." % (
                        qf._g(lv["k"], 2), _sigma_text(sg), _price(sg, "stop"), qf._money(stp_m, ccy), qf._g(lv.get("rr"), 2),
                        qf._g(lv.get("avg_win"), 2), qf._g(lv["k"], 2)))
            record = "Geri test (iz süren stopla): isabet %%%s (%d işlem, %s), işlem başına %s σ%s." % (
                qf._g((lv.get("hit") or 0.0) * 100.0, 0), lv.get("n") or 0, "örneklem dışı" if lv.get("oos") else "örneklem içi",
                qf._sg(lv.get("exp"), 2), "; bu stopla bile zarar ettirdi: düşük güven" if loss else "")
        else:
            exp = ("Beklenen: %s tutarsan %s%s - bu güçteki (|skor| %s) geçmiş günlük satırların ortalaması (%s, %d satır)." % (
                span, qf._money(exp_m, ccy), incl, BUCKETS[bucket(abs(score))], b.get("scope") or "—", b.get("n") or 0)
                if exp_m is not None else "Beklenen: —.")
            if has_target:
                ends = "Hedef %s (%s), stop %s (%s); yön dönene ya da stopa kadar tut." % (
                    _price(sg, "target"), qf._money(tgt_m, ccy), _price(sg, "stop"), qf._money(stp_m, ccy))
            elif by_carry:
                ends = "Hedef giriş seviyesi (%s): beklenen kazancın tamamı carry'den. Stop %s (%s); yön dönene ya da stopa kadar tut." % (
                    _price(sg, "entry"), _price(sg, "stop"), qf._money(stp_m, ccy))
            else:
                ends = ("Hedef yok: bu güçteki geçmiş satırlar ortalamada kazandırmadı. Stop %s (%s); yön dönene ya da stopa kadar." % (
                    _price(sg, "stop"), qf._money(stp_m, ccy)))
            record = _record_text(stats) + ((" Seviyeler: %s." % lv["why"]) if lv.get("why") else "")
        sg["plain"] = " ".join([head, why, exp, ends, record])
        sg["thesis"] = "Trend %s (skor %s; %s katkıları %s) → %s; beklenen %s." % (
            "yukarı" if s > 0 else "aşağı", qf._sg(score, 2), " / ".join(self.labels), " / ".join(qf._sg(t / 3.0, 2) for t in terms),
            inst.line(s, k), qf._money(exp_m, ccy))
        sg["trend"] = {"terms": [t / 3.0 for t in terms], "labels": list(self.labels), "bucket": BUCKETS[bucket(abs(score))],
                       "bucket_stats": {kk: b.get(kk) for kk in ("gain", "hold", "hit", "n", "scope")}, "stats": dict(stats),
                       "k": k, "size": inst.size_text(k), "new": new, "days_in": days_in, "money": {"total": exp_m, "target": tgt_m,
                                                                                                      "stop": stp_m, "ccy": ccy},
                       "trail": trail}


def _risk_of(inst: qu.Instrument, sigma: Optional[float], usdtry: Optional[float]) -> Optional[float]:
    """A unit's daily σ in USD."""
    if not sigma:
        return None
    try:
        m = inst.money(sigma, 1.0)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        m = None
    v = _usd(inst, abs(m) if m is not None else None, usdtry)
    return v if v else None


@qu.family("trend")
def run(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """Every instrument of the universe: its walk, its line (a monitor) and its row of the Trend table."""
    t0 = time.perf_counter()
    target = float(cfg.get("trend_risk_usd") or DEFAULTS["trend_risk_usd"])
    insts = list(reg)
    broken: Dict[str, str] = {}                     # (an instrument whose series cannot be read: its row says why, the rest go on)
    tracks = []
    for inst in insts:
        try:
            tracks.append(track(inst))
        except Exception as exc:  # noqa: BLE001 - one instrument is not worth the family
            broken[inst.key] = "hesaplanamadı: %s: %s" % (type(exc).__name__, str(exc)[:120])
            tracks.append(_no_track())
    groups = [inst.group for inst in insts]
    t_track = time.perf_counter()
    pooled, lines = walk(tracks, groups)
    t_walk = time.perf_counter()
    sys_ = [trades_of(tr, ln) for tr, ln in zip(tracks, lines)]
    # the groups' and the family's trades and risk-equal P&L
    summary: Dict[str, Dict[str, Any]] = {}
    for g in [x for x in qu.GROUPS if x in set(groups)] + ["*"]:
        mine = [sys_[i] for i in range(len(insts)) if g == "*" or groups[i] == g]
        n_tr = sum(x["closed"] for x in mine)
        hits = sum(x["hits"] for x in mine)
        pnl = _portfolio([x["pnl"] for x in mine])
        summary[g] = {"trades": n_tr, "hits": hits, "hit": hits / n_tr if n_tr else None,
                      "sharpe": sharpe([pnl[d] for d in sorted(pnl)]), "lines": len(mine)}
    usdtry = ctx.usdtry()
    # every line's size (the same daily risk) and the trailing stop calibrated on the walk's positions (quantlevels: month
    # by month, on what had happened before; kept - a refresh, the day's next fit, a backtest refit choose nothing)
    t_cal = time.perf_counter()
    sizes: Dict[str, Tuple[Optional[float], float]] = {}
    money: Dict[str, float] = {}
    for inst, tr in zip(insts, tracks):
        sg_ = tr["sig"][-1] if tr["n"] else None
        r1 = _risk_of(inst, sg_, usdtry) if sg_ else None
        kk = round2(min(max(target / r1, K_RANGE[0]), K_RANGE[1])) if r1 else 1.0
        sizes[inst.key] = (r1, kk)
        try:
            m1 = inst.money(1.0, kk)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            m1 = None
        if m1 is not None and math.isfinite(m1):
            money[inst.key] = abs(m1) * (1.0 if inst.ccy in ("TL", "TRY") else (usdtry or 0.0))
    book = qlv.calibrate(level_trades(insts, tracks, money), "trend", ctx.today_iso)
    t_lv = time.perf_counter()
    mons: List[qf.Monitor] = []
    rows: List[Dict[str, Any]] = []
    for i, inst in enumerate(insts):
        tr = tracks[i]
        sx = sys_[i]
        own_sharpe = sharpe([sx["pnl"][d] for d in sorted(sx["pnl"])])
        if sx["closed"] >= MIN_TRADES:
            stats = {"trades": sx["closed"], "hits": sx["hits"], "hit": sx["hits"] / sx["closed"], "scope": "enstrüman", "sharpe": own_sharpe}
        else:
            gs = summary.get(groups[i]) or {}
            stats = {"trades": gs.get("trades") or 0, "hits": gs.get("hits") or 0, "hit": gs.get("hit"), "scope": "grup",
                     "sharpe": own_sharpe, "own_trades": sx["closed"]}
        last_trade = sx["trades"][-1] if sx["trades"] else None
        row: Dict[str, Any] = {"key": inst.key, "label": inst.label, "group": inst.group, "tier": inst.tier, "tag": inst.tag,
                               "priority": inst.priority, "n": tr["n"], "unit": qf.change_unit(inst.kind), "verbs": list(inst.verbs),
                               "trades": stats["trades"], "hits": stats["hits"], "hit": stats["hit"], "scope": stats["scope"],
                               "sharpe": own_sharpe, "own_trades": sx["closed"], "sid": None, "why": ""}
        sigma = tr["sig"][-1] if tr["n"] else None
        if inst.key in broken or tr["n"] < MIN_DAYS:
            row["why"] = broken.get(inst.key) or "geçmiş kısa: %d gün (en az %d)" % (tr["n"], MIN_DAYS)
            rows.append(row)
            continue
        if not sigma:
            row["why"] = "seviye oynamıyor (σ 0)"
            rows.append(row)
            continue
        risk1, k = sizes.get(inst.key) or (None, 1.0)
        buckets = [bucket_stats(pooled, i, inst.group, b) for b in range(len(BUCKETS))]
        lv = book.line(inst.group)
        line = _Line(inst, tr, k, stats, buckets, cfg, lv)
        row["levels"] = qf.levels_text(lv)
        sid = "trend:" + inst.key
        try:
            mon = inst.monitor(sid, "trend", k=k, zfn=line.zfn, mode="drift", follows=True, entry=ENTRY_ANY, hold=HOLD0, reward=0.0,
                               risk=0.0, fcast=0.0, score_name="skor", zvalues=list(tr["score"]), finish=line.finish, note=NOTE,
                               info={"k": k, "risk_usd": risk1, "trend_risk_usd": target})
        except Exception as exc:  # noqa: BLE001 - a line that cannot be made is its row's reason, not the family's end
            row["why"] = "satır kurulamadı: %s: %s" % (type(exc).__name__, str(exc)[:120])
            rows.append(row)
            continue
        line.mon = mon
        mon.trend = line
        last = tr["score"][-1]
        if last is not None:                                                   # (the last close's decision until it is scored)
            line.now = {"score": last, "terms": tr["terms"][-1], "h_long": min(HORIZONS[2], tr["n"] - 1), "level": tr["lv"][-1]}
            line.decide(last, inst.last() or tr["lv"][-1], None)
        mons.append(mon)
        row.update({"sid": sid, "k": k, "size": inst.size_text(k), "sigma": sigma, "risk_usd": risk1, "risk_k": risk1 * k if risk1 else None,
                    "d_prev": line.d_prev, "run": line.run, "labels": list(line.labels),
                    "stopped": bool(last_trade and last_trade["why"] == "stop" and last_trade["exit"] and last_trade["dir"] == line.d_prev),
                    "stopped_at": last_trade["exit"] if last_trade and last_trade["why"] == "stop" else None})
        if risk1 is None:
            row["why"] = "büyüklük: günlük risk ölçülemedi (1 birim)"
        rows.append(row)
    buckets_rows = []
    for g in [x for x in summary if x != "*"] + ["*"]:
        for b in range(len(BUCKETS)):
            st = pooled.get((g, b)) or [0, 0.0, 0.0, 0]
            buckets_rows.append({"group": "Tümü" if g == "*" else g, "bucket": BUCKETS[b], "n": int(st[0]),
                                 "gain": st[1] / st[0] if st[0] else None, "hold": st[2] / st[0] if st[0] else None,
                                 "hit": st[3] / st[0] if st[0] else None})
    # (the series the page's coverage table lists: every line's own, its legs', its carry's)
    keys = set()
    for inst in insts:
        keys.add(inst.key)
        keys.update(inst.info.get("inputs") or ())
        keys.update(getattr(inst, "quote", None) or ())
        if inst.fx:
            keys.update(("FX:" + inst.fx, "FXP:%s:3M" % inst.fx))
    t1 = time.perf_counter()
    table = {"ok": True, "rows": rows, "buckets": buckets_rows, "_keys": sorted(k for k in keys if k),
             "groups": [dict(v, group="Tümü" if g == "*" else g) for g, v in summary.items()],
             "risk_usd": target, "horizons": list(HORIZONS), "labels": list(H_LABELS), "min_days": MIN_DAYS, "stop_sigma": STOP_SIGMA,
             "edges": list(EDGES), "k_range": list(K_RANGE), "lines": len(mons), "instruments": len(insts),
             "levels": book.to_json(), "href": HREF,
             "ms": {"track": round((t_track - t0) * 1000.0, 1), "walk": round((t_walk - t_track) * 1000.0, 1),
                    "levels": round((t_lv - t_cal) * 1000.0, 1), "total": round((t1 - t0) * 1000.0, 1)}}
    return mons, table


# ---------------------------------------------------------------------------------------------- the page
def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "Trend" reads: every instrument's row with its line now (score, the horizons' contributions,
    direction, "YENİ", days in it, the line in the plan's format), the strength buckets, the groups' record."""
    from .quant import _clean
    tables = v.get("tables") or {}
    tab = copy.deepcopy({k: x for k, x in (tables.get("trend") or {}).items() if not k.startswith("_")})
    keys = set((tables.get("trend") or {}).get("_keys") or ())
    sigs = {s["id"]: s for s in v["signals"] + v["gated"] if s.get("family") == "trend"}
    for r in tab.get("rows") or ():
        m = fit["mons"].get(r.get("sid") or "")
        line = getattr(m, "trend", None)
        now = getattr(line, "now", None) if line is not None else None
        if m is not None and now and m.z is not None:
            s = sign(m.z)
            r.update({"score": m.z, "terms": [t / 3.0 for t in now.get("terms") or ()], "dir": s, "verb": line.inst.verb(s),
                      "new": s != line.d_prev, "days_in": 0 if s != line.d_prev else line.run, "strength": strength(m.z),
                      "level": m.level, "live": m.live})
        sg = sigs.get(r.get("sid") or "")
        if sg is not None:
            tm = (sg.get("trend") or {}).get("money") or {}
            r.update({"line": sg.get("line"), "exp": tm.get("total"), "ccy": tm.get("ccy"), "hold": sg.get("hold"),
                      "entry": sg.get("entry"), "target": sg.get("target"), "stop": sg.get("stop"), "px": sg.get("px"),
                      "unit_level": sg.get("unit"), "digits": sg.get("digits"), "bucket": (sg.get("trend") or {}).get("bucket")})
    base["trend"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s.get("page") == VIEWS[what]]
    base["settings"] = fit["cfg"]
    base["coverage"] = [c for c in fit.get("coverage") or () if c["key"] in keys]
    base["errors"] = {k: e for k, e in (tables.get("errors") or {}).items() if k == "trend"}
    return _clean(base)
