"""Target and stop calibrated on what past trades actually did: the layer every quant family's lines go through.

A family's rule for its target and stop used to be its own (the window's mean, 2σ of the week, the mean gain of a
bucket, (2p − 1) × the mean move ...) - and a target of a few pips against a stop of hundreds made "Ödül / risk" 0,02.
Here the levels are chosen on the family's own past trades: how far each went against the trade and for it before it
ended, in σ of its holding horizon.

**The path of a trade.**  From the family's walk-forward backtest (``tto.quantbt`` records it for every family the
refits run; Trend, Carry + momentum and Makine öğrenmesi walk forward on their own and give theirs), every past trade's
P&L at each close of its holding, in σ of the holding horizon - σ_h, the daily σ known at the entry × √ the holding
(a basket's: its ex-ante weekly σ) -: its maximum adverse excursion (MAE), its maximum favourable excursion (MFE) and
where it ended.  Only what was known at the entry scales it; the path itself is what came after.

**The calibration** (per family × the Sinyaller list's group, ``quantuniv.GROUPS``).  A stop multiple k and a target
multiple m, both in σ_h, chosen on the trades that had ended before the calibration month (walk-forward: each month
again, on what was known when it began).  The candidates: a stop where 70 / 80 / 90 % of the winning trades never went
(their MAE's percentiles), targets from the MFE distribution (its 30th … 70th percentiles) and 1 / 1,5 / 2 × the stop;
for a mean-reversion family also the target at its fair value (the window's mean), the stop then at most as far as it.
The objective: the expected P&L per trade (carry in it where the trades had it), subject to Ödül / risk = m / k ≥ 1 and
at least ``MIN_TRADES`` trades - a group with fewer takes the family's (all its groups pooled), a family with fewer has
no calibrated levels (its own rule stands and its line says why).  A trade reaches its target at the target (a limit
order), its stop at the stop - or at the close that went through it (a gap is the trade's) -, else it expires at its
last close.

**Closes only** (``BETA``).  The history has closes; a level resting all day is met between them too.  The paths are
played with Broadie, Glasserman and Kou's continuity correction: β ≈ 0,5826 × the path's σ a close (σ_step: σ_h ÷ √ the
closes σ_h is of - 0,26 σ_h for a five-day holding).  A stop k counts as hit once a close is k − β·σ_step against the
entry (sooner than on the closes: filled at the stop, or at that close when it went through); a target m as reached
only once a close is m + β·σ_step in the trade's favour (later: a touch is not a fill - the conservative side).  The
choice of k and m and the record shown (İsabet, Beklenen K/Z) are played so; the levels shown and placed are k·σ_h and
m·σ_h themselves.

* **Trend** (``RULES``: "trail"): no target - a trailing stop k·σ below the best level since the entry, else the
  direction's turn (hit once a close is k − β·σ_step below the best close); its Ödül / risk is the average winning
  trade ÷ k (≥ 1 as well), σ a month's (``trend``'s horizon).
* **Carry + momentum**: the basket is the trade - its daily P&L in its own (diversified) weekly σ; each leg gets the
  basket's k and m scaled to its own σ, the card shows the basket's ratio.

**The line.**  Entry: the level now.  Target and stop: the multiples × the instrument's own σ of its holding now.  It
carries Ödül / risk (≥ 1 by construction), İsabet - the share of trades that reached the target, or expired in profit,
in the out-of-sample record (each month's trades at the levels chosen before that month; with fewer than ``MIN_OOS`` of
them, the in-sample record of today's levels, said so) -, Beklenen K/Z (the expectancy per trade × σ_h now, in money
through the family's own conversion) and the trade count.  A line whose levels lost money all the same stays in the
list as "düşük güven" with ``LOSS``; a group is sorted by the expectancy.

**Families that keep their own levels** (``KEEP``): VİOP adil değer (its page's order levels), İma kalibrasyonu (the
meeting's two outcomes are its levels), the intraday families (session-bound levels on 5-minute bars - there is no
daily backtest of them), Korelasyon kırılması (a correlation has no P&L σ).  Not in the walk-forward backtest either and
so with their own levels and the reason on the line: İma patikası ayrıklığı (its path is rebuilt day by day) and DİBS
adil değeri (its curve fit needs the workbook's bond list).

**For the writer of a family: the contract.**  A family is calibrated with no extra code when its trades with their
paths reach this layer:

1. *Run in the backtest's refits* (``quantfam.run_all``, ``quantuniv.family`` without ``own_backtest`` - any monitor
   the refit runner returns): ``quantbt.backtest`` records each trade's path itself - the monitor needs a daily σ
   (``dsd`` in level units, or ``pnl_sd``), a P&L scale (``pnl``) and a holding (``hold``, or a half-life) - and
   ``tto.quant`` applies the levels to its live lines.  Nothing else to write.
2. *A family that walks forward on its own* (``quantuniv.family(…, own_backtest=True)``) gives its trades in its table's
   ``backtest`` - quantbt's trade format - with their paths: ``tto.quant`` calibrates them on every fit
   (``calibrate_tables``: the table's ``"levels"``) and applies them to its live lines.  Nothing else to write.  (Trend,
   Carry + momentum and ML call ``calibrate`` themselves: a trailing stop, a basket, their own σ.)  A trade - quantbt's
   fields and these::

       {"sid": "optspot:FX:EURUSD", "family": "optspot",   # its line: the group from the key after the family's id
        "entry_day": "2026-03-02",                     # the entry's close (ISO)
        "path_sigma": [0.21, -0.40, ...],              # the move in the trade's favour at each close after the entry,
                                                       # σ of the holding (known at the entry), its whole horizon
                                                       # whatever its exit - the level's own move
        "sigma": 0.8,                                  # that σ in the P&L unit (``unit``: %, bp, vol …)
        "held": 3, "carry": 0.02,                      # quantbt's: the carry's P&L over the closes held, in ``unit``
        "horizon": 5,                                  # the path's closes (for its last close's date; see below)
        "mae_sigma": 0.40, "mfe_sigma": 1.30,          # (optional: computed from the path)
        "pnl": 0.5, "pnl_try": 21000.0}                # (optional: TRY a unit of P&L, for the panel's money)

   and, where the family knows them: ``"group"`` (the list's), ``"end_day"`` (the path's last close - else ``"days"``,
   every close of it; else no earlier than ``horizon`` × 7/5 + 4 calendar days after the entry, so a month's choice
   never sees a path that was still running), ``"carry_sigma"`` (carry a close in σ, instead of ``carry`` / ``held``),
   ``"carry_in"`` (its P&L has its carry), ``"fair_sigma"`` (a mean reversion: the distance to its fair value at the
   entry, σ - the "fair value" candidate), ``"open"`` (still running: left out of a fixed rule; a trailing stop's marked
   at the cut), ``"try"`` (TRY a unit of P&L), ``"sigma_closes"`` (the closes ``sigma`` is of when they are not the
   path's own - Trend's month, 21 -: the path's σ a close, for the correction; else ``horizon``, else the path's
   length).  ``RULES[family] = "trail"`` for a trailing stop (Trend's; "fixed" the default).

**Cost.**  A calibration is kept by (family, scope, month, a digest of the trades it saw): a month's levels are chosen
once - a refresh, the day's next fit, the backtest's refits of the same data find them; a revised close chooses again.
"""
from __future__ import annotations

import bisect
import math
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import quantfam as qf

# ---------------------------------------------------------------------------------------------- the rule's constants
MIN_TRADES = 30                 # trades a calibration needs (a group with fewer: its family's, pooled)
MIN_OOS = 10                    # out-of-sample trades before their record is the one shown (else today's in-sample one)
WINDOW_MONTHS = 12              # the out-of-sample record: the months before the current one
WIN_Q = (0.7, 0.8, 0.9)         # the stop candidates: these percentiles of the winning trades' MAE
MFE_Q = (0.3, 0.4, 0.5, 0.6, 0.7)   # the target candidates: these percentiles of every trade's MFE
RR_MULTS = (1.0, 1.5, 2.0)      # ... and these multiples of the stop (Ödül / risk at least 1)
#: a trailing stop's candidates (σ of a month): its winners' drawdowns from the peak (70 / 80 / 90 %) fall among them -
#: a fixed grid, so each trade's exit at each is found once
TRAIL_K = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
K_RANGE = (0.5, 3.0)            # a stop outside this is no level (σ_h: nearer than half of it is a day or two's noise; past 3 none)
M_MAX = 4.0                     # a target farther than this (σ_h) is no level either: the most a target is set at
MIN_WINNERS = 5                 # winners a percentile of their MAE needs (else every trade's)
LOSS = qf.LEVELS_LOSS            # "bu kurulum bu seviyelerle geçmişte zarar ettirdi"
#: the continuity correction of a close-only path (Broadie, Glasserman & Kou 1997): a stop counts as hit β σ_step
#: sooner, a target as reached β σ_step later (σ_step: the path's σ a close, in σ_h)
BETA = 0.5826
_EPS = 1e-9                     # (a corrected stop never at or past the entry: a close at the entry is not "through" it)
#: what the stored backtest's levels were made with (a result of another version is run again)
VERSION = 2

#: a family's exit style: "trail" a trailing stop and no target (Trend), "fixed" target and stop (the default)
RULES: Dict[str, str] = {"trend": "trail"}
#: the families that calibrate on their own walk-forward (the backtest records no path of theirs; the panel shows
#: their own record)
OWN = {"trend", "sira", "ml"}
#: the families whose design fixes their own levels: the reason their line says
KEEP: Dict[str, str] = {
    "viop": "seviyeler ailenin kendi tasarımı: VİOP sayfasındaki emir seviyeleri (doluş olasılıklarıyla)",
    "imacal": "seviyeler ailenin kendi tasarımı: toplantının iki sonucu (fiyatlanan ve diğer adım)",
    "wirp": "seviyeler ailenin kendi tasarımı: hedef politika faizinin ankette (ya da beklentinde) olduğu seviye, stop ızgaranın payı",
    "izscore": "seviyeler ailenin kendi tasarımı: gün içi (5 dk bar, seans sonuna kadar) - günlük geri testi yok",
    "iorb": "seviyeler ailenin kendi tasarımı: gün içi açılış aralığı - günlük geri testi yok",
    "irv": "seviyeler ailenin kendi tasarımı: gün içi (5 dk bar, seans sonuna kadar) - günlük geri testi yok",
    "ipath": "seviyeler ailenin kendi tasarımı: gün içi carry patikası - günlük geri testi yok",
    "corr": "seviyeler ailenin kendi tasarımı: korelasyon işleminin K/Z σ'sı yok",
    "imapath": "seviyeler ailenin kendi kuralıyla: ima patikası her gün yeniden kuruluyor, yürüyen geri testte yok",
    "dibsfv": "seviyeler ailenin kendi kuralıyla: DİBS eğri uyumu çalışma kitabının kâğıt listesini istiyor, yürüyen geri testte yok",
}


def month_of(day: str) -> str:
    return day[:8] + "01"


def months_back(month: str, n: int) -> List[str]:
    """``n`` months before ``month`` and it, oldest first ("2026-11-01", 2 → 2026-09-01, 2026-10-01, 2026-11-01)."""
    y, m = int(month[:4]), int(month[5:7])
    out = []
    for i in range(n, -1, -1):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append("%04d-%02d-01" % (yy, mm))
    return out


def _q(xs: Sequence[float], p: float) -> Optional[float]:
    """The ``p`` percentile of sorted ``xs`` (linear between the ranks)."""
    if not xs:
        return None
    pos = p * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _clip(k: float) -> float:
    return min(max(k, K_RANGE[0]), K_RANGE[1])


def _up2(x: float) -> float:
    """``x`` to the hundredth above (a stop placed beyond where the trades went, never inside it)."""
    return math.ceil(x * 100.0 - 1e-6) / 100.0


def _down2(x: float) -> float:
    """``x`` to the hundredth below (a target within what the trades reached)."""
    return math.floor(x * 100.0 + 1e-6) / 100.0


def _finite(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _path_end(r: Dict[str, Any], entry: str, n: int) -> str:
    """The last close of a path a trade does not date (quantbt's format: ``exit_day`` is where it left, its path goes on
    to its ``horizon``): no earlier than the truth - ⌈n × 7 / 5⌉ + 4 calendar days after the entry (weekends and a
    holiday or two), never before its exit."""
    import datetime as _dt
    n = int(r.get("horizon") or n or 0)
    est = (_dt.date.fromisoformat(entry) + _dt.timedelta(days=-(-n * 7 // 5) + 4)).isoformat()
    ex = r.get("exit_day")
    return max(est, str(ex)) if isinstance(ex, str) else est


def group_of_key(key: str) -> str:
    """The Sinyaller list's group of a line by its instrument's key ("FX:EURUSD" → G10 spot, "FX:USDTRY" → Offshore,
    "OIS:2Y" → TRY OIS …): a trade that does not say its group (``quantuniv.classify``)."""
    from . import quantuniv as qu
    return qu.classify({"legs": [{"key": key}] if key else [], "asset": "", "info": {}})["group"]


# ---------------------------------------------------------------------------------------------- a trade
class Trade(object):
    """One past trade, ready to be played at any levels: its path's running best and worst (a first passage is a
    bisection), its drawdowns from the running peak (a trailing stop's), the P&L it ended with, the correction's shift
    of its closes (``bs``: β × its σ a close, σ_h)."""

    __slots__ = ("family", "group", "entry", "end", "days", "path", "c", "fair", "open", "n", "up", "dn", "mdd", "fin", "mae",
                 "mfe", "sid", "sig", "unit", "try_", "carry_in", "cum", "key", "tex", "bs")

    def __init__(self, r: Dict[str, Any]):
        self.family = str(r.get("family") or "")
        self.sid = str(r.get("sid") or "")
        self.group = str(r.get("group") or group_of_key(self.sid.split(":", 1)[1] if ":" in self.sid else ""))
        self.entry = str(r["entry_day"])
        self.days: Optional[List[str]] = list(r["days"]) if r.get("days") is not None else None
        path = [float(x) for x in r.get("path_sigma") or ()]
        self.path = path
        self.n = len(path)
        # (the path's σ a close: σ_h is of ``sigma_closes`` closes - Trend's month -, else of its horizon, its own length)
        sc = _finite(r.get("sigma_closes")) or _finite(r.get("horizon")) or float(self.n)
        self.bs = BETA / math.sqrt(sc) if sc and sc > 0 else 0.0
        self.sig = _finite(r.get("sigma"))
        held = r.get("held")
        self.c = _finite(r.get("carry_sigma"))
        if self.c is None:
            # (quantbt's trade: its carry the P&L the carry made over the closes it was held, in its unit)
            carry = _finite(r.get("carry"))
            self.c = carry / float(held) / self.sig if carry and held and self.sig else 0.0
        self.end = str(r.get("end_day") or (self.days[-1] if self.days else None) or _path_end(r, self.entry, self.n))
        self.fair = _finite(r.get("fair_sigma"))
        self.fair = self.fair if self.fair is not None and self.fair > 0 else None
        self.open = bool(r.get("open"))
        self.unit = r.get("unit")
        tp = _finite(r.get("try"))
        if tp is None and _finite(r.get("pnl_try")) is not None and _finite(r.get("pnl")):
            tp = abs(r["pnl_try"] / r["pnl"])                         # (quantbt's trade: TRY a unit of its P&L)
        self.try_ = tp
        self.carry_in = bool(r.get("carry_in", self.c != 0.0 or r.get("carry") is not None))
        up, dn, mdd, cum = [], [], [], []
        hi = lo = -math.inf
        peak = dd = acc = 0.0
        for x in path:
            hi = x if x > hi else hi
            lo = -x if -x > lo else lo
            peak = x if x > peak else peak
            dd = peak - x if peak - x > dd else dd
            acc += x
            up.append(hi)
            dn.append(lo)
            mdd.append(dd)
            cum.append(acc)
        self.up, self.dn, self.mdd, self.cum = up, dn, mdd, cum
        self.fin = path[-1] + self.c * self.n if path else 0.0
        self.mae = max(0.0, dn[-1]) if path else 0.0
        self.mfe = max(0.0, up[-1]) if path else 0.0
        self.key = hash((self.family, self.sid, self.entry, self.n, round(acc, 9), round(path[-1], 9) if path else 0.0, round(self.c, 12),
                         round(self.fair, 9) if self.fair else None, self.open, round(self.bs, 9)))
        self.tex: Optional[List[int]] = None              # (a trailing stop's exit at each of TRAIL_K: found once)

    def cut(self, month: str) -> int:
        """The closes of its path before ``month`` (a trailing stop's trade still running then is marked there)."""
        if self.days is None:
            return self.n if self.end < month else 0
        return bisect.bisect_left(self.days, month)

    def cut_key(self, n: int) -> int:
        if n >= self.n:
            return self.key
        return hash((self.family, self.sid, self.entry, n, round(self.cum[n - 1], 9) if n else 0.0, round(self.bs, 9)))

    def trail_exits(self) -> List[int]:
        """Its exit at each trailing stop of ``TRAIL_K`` (the first close that far below its best, corrected): once."""
        if self.tex is None:
            self.tex = [bisect.bisect_left(self.mdd, max(k - self.bs, _EPS)) for k in TRAIL_K]
        return self.tex

    def trail_fill(self, j: int, k: float) -> float:
        """A trailing stop ``k`` hit at close ``j``: at the stop (its best so far − k), or at that close when it went
        through it; with its carry."""
        return min(self.path[j], max(0.0, self.up[j]) - k) + self.c * (j + 1)


def play_fixed(t: Trade, k: float, m: float, n: Optional[int] = None) -> Tuple[float, bool, int, str]:
    """The trade at a stop ``k`` and a target ``m`` (σ_h): (P&L σ_h with its carry, a hit, closes held, how it ended) -
    on its closes, corrected for what they miss (``BETA``): the target reached once a close is β σ_step past it, at the
    target (a limit); the stop hit once a close comes within β σ_step of it, at the stop - or at that close when it went
    through (a gap is the trade's); else the last close."""
    L = t.n if n is None else min(n, t.n)
    if not L:
        return 0.0, False, 0, "süre"
    i_m = bisect.bisect_left(t.up, m + t.bs, 0, L)
    i_k = bisect.bisect_left(t.dn, max(k - t.bs, _EPS), 0, L)
    if i_m < L and i_m <= i_k:
        return m + t.c * (i_m + 1), True, i_m + 1, "hedef"
    if i_k < L:
        x = min(t.path[i_k], -k) + t.c * (i_k + 1)
        return x, x > 0.0, i_k + 1, "stop"
    x = t.path[L - 1] + t.c * L
    return x, x > 0.0, L, "süre"


def play_fair(t: Trade, k: float, n: Optional[int] = None) -> Tuple[float, bool, int, str]:
    """The trade with its target at its fair value and its stop ``k`` - at most as far as the target (R/R ≥ 1)."""
    f = t.fair
    if f is None:
        return play_fixed(t, k, k, n)
    return play_fixed(t, min(k, f), f, n)


def play_trail(t: Trade, k: float, n: Optional[int] = None) -> Tuple[float, bool, int, str]:
    """The trade with a trailing stop ``k`` below its best close (hit once a close is k − β σ_step below it: at the
    stop, or at that close when it went through), else its own end (a direction's turn: "dönüş"); a trade still running
    (``n`` closes known of it) marked at its last close ("açık")."""
    L = t.n if n is None else min(n, t.n)
    if not L:
        return 0.0, False, 0, "açık"
    i = bisect.bisect_left(t.mdd, max(k - t.bs, _EPS), 0, L)
    if i < L:
        x = t.trail_fill(i, k)
        return x, x > 0.0, i + 1, "stop"
    x = t.path[L - 1] + t.c * L
    return x, x > 0.0, L, ("dönüş" if L == t.n and not t.open else "açık")


def play(t: Trade, ch: Dict[str, Any], n: Optional[int] = None) -> Tuple[float, bool, int, str]:
    rule = ch["rule"]
    if rule == "trail":
        return play_trail(t, ch["k"], n)
    if rule == "fair":
        return play_fair(t, ch["k"], n)
    return play_fixed(t, ch["k"], ch["m"], n)


# ---------------------------------------------------------------------------------------------- the choice
def candidates(trades: Sequence[Trade], rule: str, cuts: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
    """The levels tried on these trades: a fixed rule's stops from the winners' MAE (70 / 80 / 90 %), its targets from
    every trade's MFE (30 … 70 %) and 1 / 1,5 / 2 × the stop - m ≥ k -, and the fair value with each stop when every trade
    has one; a trailing stop's from its winners' drawdowns from the peak and ``TRAIL_K``."""
    if rule == "trail":
        return [{"rule": "trail", "k": k, "m": None, "ki": i} for i, k in enumerate(TRAIL_K)]
    # (corrected for the closes: the stop a winner needed is beyond its MAE by β σ_step, the target a trade reached is
    # short of its MFE by as much)
    win = sorted(t.mae + t.bs for t in trades if t.fin > 0)
    if len(win) < MIN_WINNERS:
        win = sorted(t.mae + t.bs for t in trades)
    ks = sorted({_up2(_clip(x)) for x in (_q(win, p) for p in WIN_Q) if x is not None})
    if not ks:
        ks = [1.0]
    mfe = sorted(t.mfe - t.bs for t in trades)
    from_mfe = [_down2(min(x, M_MAX)) for x in (_q(mfe, p) for p in MFE_Q) if x is not None and x > 0]
    out: List[Dict[str, Any]] = []
    seen = set()
    for k in ks:
        for m in from_mfe + [round(min(k * r, M_MAX), 2) for r in RR_MULTS]:
            if m <= 0 or m + 1e-9 < k or (k, m) in seen:
                continue
            seen.add((k, m))
            out.append({"rule": "fixed", "k": k, "m": m})
    if trades and all(t.fair is not None for t in trades):
        out += [{"rule": "fair", "k": k, "m": None} for k in ks]
    return out


def evaluate(trades: Sequence[Trade], ch: Dict[str, Any], cuts: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """The trades at the levels ``ch``: count, hit rate, the mean P&L (σ_h, carry in it), the mean winner, the closes
    held, the shares that reached the target and the stop; a fair-value rule's mean Ödül / risk."""
    n = len(trades)
    tot = win_sum = held = rr = 0.0
    wins = pos = tgt = stp = 0
    rule, k, m = ch["rule"], ch["k"], ch.get("m")
    bl = bisect.bisect_left
    ki = ch.get("ki")
    for i, t in enumerate(trades):
        if rule == "trail" and ki is not None:               # (play_trail, its exit at the grid's k found once a trade)
            L = t.n if cuts is None or cuts[i] > t.n else cuts[i]
            j = t.trail_exits()[ki]
            if j < L:
                x = t.trail_fill(j, k)
                hit, h, how = x > 0.0, j + 1, "stop"
            elif L:
                x = t.path[L - 1] + t.c * L
                hit, h, how = x > 0.0, L, ("dönüş" if L == t.n and not t.open else "açık")
            else:
                x, hit, h, how = 0.0, False, 0, "açık"
        elif rule == "fixed":                                # (play_fixed, inline: the calibration's inner loop)
            L = t.n
            i_m = bl(t.up, m + t.bs)
            i_k = bl(t.dn, max(k - t.bs, _EPS))
            if i_m < L and i_m <= i_k:
                x, hit, h, how = m + t.c * (i_m + 1), True, i_m + 1, "hedef"
            elif i_k < L:
                x = min(t.path[i_k], -k) + t.c * (i_k + 1)
                hit, h, how = x > 0.0, i_k + 1, "stop"
            else:
                x = t.fin
                hit, h, how = x > 0.0, L, "süre"
        else:
            x, hit, h, how = play(t, ch, None if cuts is None else cuts[i])
            if rule == "fair" and t.fair:
                rr += t.fair / min(k, t.fair)
        tot += x
        held += h
        if hit:
            wins += 1
        if x > 0:
            pos += 1
            win_sum += x
        if how == "hedef":
            tgt += 1
        elif how == "stop":
            stp += 1
    out = {"n": n, "hit": wins / n if n else None, "exp": tot / n if n else None, "held": held / n if n else None,
           "target": tgt / n if n else None, "stop": stp / n if n else None, "avg_win": win_sum / pos if pos else None}
    if rule == "trail":
        out["rr"] = out["avg_win"] / k if out["avg_win"] else None
    elif rule == "fair":
        out["rr"] = rr / n if n else None
    else:
        out["rr"] = m / k
    return out


def _trail_all(trades: Sequence[Trade], cuts: Optional[Sequence[int]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Every trailing stop of the grid on these trades at once (``evaluate``'s numbers): each trade's exit at each k
    found once (its first drawdown from the peak that deep, corrected), its mark at the cut once."""
    Ls, marks = [], []
    for i, t in enumerate(trades):
        t.trail_exits()
        L = t.n if cuts is None or cuts[i] > t.n else cuts[i]
        Ls.append(L)
        marks.append(t.path[L - 1] + t.c * L if L else 0.0)
    n = len(trades)
    out = []
    for ki, k in enumerate(TRAIL_K):
        tot = win_sum = 0.0
        wins = held = stp = 0
        for t, L, mk in zip(trades, Ls, marks):
            j = t.tex[ki]
            if j < L:
                x = t.trail_fill(j, k)
                held += j + 1
                stp += 1
            else:
                x = mk
                held += L
            tot += x
            if x > 0.0:
                wins += 1
                win_sum += x
        avg_win = win_sum / wins if wins else None
        out.append(({"rule": "trail", "k": k, "m": None, "ki": ki},
                    {"n": n, "hit": wins / n if n else None, "exp": tot / n if n else None, "held": held / n if n else None,
                     "target": 0.0, "stop": stp / n if n else None, "avg_win": avg_win, "rr": avg_win / k if avg_win else None}))
    return out


def choose(trades: Sequence[Trade], rule: str, cuts: Optional[Sequence[int]] = None) -> Optional[Dict[str, Any]]:
    """The levels with the best expectancy on these trades, Ödül / risk at least 1 - ``None`` with fewer than
    ``MIN_TRADES`` (or no candidate that keeps the ratio)."""
    if len(trades) < MIN_TRADES:
        return None
    best, key = None, None
    tried = _trail_all(trades, cuts) if rule == "trail" else [(ch, None) for ch in candidates(trades, rule, cuts)]
    for ch, st in tried:
        st = st or evaluate(trades, ch, cuts)
        if st["rr"] is None or st["rr"] < 1.0 - 1e-9 or st["exp"] is None:
            continue
        kk = (round(st["exp"], 12), round(st["hit"] or 0.0, 12), -ch["k"])
        if key is None or kk > key:
            best, key = dict(ch, **st), kk
    return best


# ---------------------------------------------------------------------------------------------- the walk forward (kept)
_CACHE: Dict[Tuple, Optional[Dict[str, Any]]] = {}
_LOCK = threading.Lock()
CACHE_LIMIT = 6000
#: what was chosen anew in this process (a refresh or a second fit of the same data chooses nothing: the tests read it)
STATS = {"chosen": 0, "cached": 0}


def _choose_kept(family: str, rule: str, scope: str, month: str, trades: Sequence[Trade], cuts: Optional[Sequence[int]]) -> Optional[Dict[str, Any]]:
    if len(trades) < MIN_TRADES:
        return None
    h = 0
    for i, t in enumerate(trades):
        h = (h + (t.key if cuts is None else t.cut_key(cuts[i]))) & 0xFFFFFFFFFFFFFFFF
    ck = (family, rule, scope, month, len(trades), h)
    with _LOCK:
        if ck in _CACHE:
            STATS["cached"] += 1
            return _CACHE[ck]
    ch = choose(trades, rule, cuts)
    with _LOCK:
        STATS["chosen"] += 1
        _CACHE[ck] = ch
        if len(_CACHE) > CACHE_LIMIT:
            for old in list(_CACHE)[:len(_CACHE) - CACHE_LIMIT // 2]:
                del _CACHE[old]
    return ch


def reset() -> None:
    """Forget every kept calibration (tests)."""
    with _LOCK:
        _CACHE.clear()


def _summary(rows: List[Tuple[Trade, float, bool, int, str]], first: Optional[str], last: Optional[str]) -> Dict[str, Any]:
    """An out-of-sample record as the backtest panel tells one (``quantbt.summarize``): trades, hit rate, mean P&L in
    σ_h and in its unit and TRY (where the trades say what σ_h was), Sharpe, the largest drawdown."""
    from . import quantbt as qbt
    trades = []
    for t, x, hit, h, how in rows:
        day = (t.days[h - 1] if t.days and 0 < h <= len(t.days) else t.end)
        units = x * float(t.sig) if isinstance(t.sig, (int, float)) and math.isfinite(t.sig) else None
        trades.append({"sid": t.sid, "exit_day": day, "pnl": units if units is not None else x, "pnl_sigma": x,
                       "unit": t.unit if units is not None else "σ", "pnl_try": units * float(t.try_) if units is not None and t.try_ else None,
                       "hit": hit})
    st = qbt.summarize(trades, first, last)
    st["hits"] = sum(1 for x in trades if x["hit"])
    st["hit"] = st["hits"] / st["trades"] if st["trades"] else None
    st["held"] = sum(r[3] for r in rows) / len(rows) if rows else None
    st["exp"] = st.get("avg_sigma")
    return st


class Book(object):
    """A family's calibrated levels: per group the month's choice (``line``) and the out-of-sample record, the family's
    record; ``to_json`` / ``from_json`` for the stored backtest."""

    def __init__(self, family: str, rule: str, month: str, groups: Dict[str, Dict[str, Any]], record: Dict[str, Any],
                 n: int = 0, why: str = ""):
        self.family, self.rule, self.month, self.groups, self.record, self.n, self.why = family, rule, month, groups, record, n, why

    def line(self, group: str, month: Optional[str] = None) -> Dict[str, Any]:
        """What a line of ``group`` reads (``Monitor.levels``): today's levels and the record shown with them -
        ``{"ok": False, "why": …}`` without a calibration."""
        g = self.groups.get(group)
        if g is None:
            return {"ok": False, "family": self.family, "group": group,
                    "why": "seviye kalibrasyonu yok: geri testte bu grubun işlemi yok" + (" (%s)" % self.why if self.why else "")}
        ch = (g.get("months") or {}).get(month) if month and month != self.month else g.get("live")
        if not ch:
            return {"ok": False, "family": self.family, "group": group, "why": g.get("why") or "seviye kalibrasyonu yok"}
        oos = g.get("oos") or {}
        use_oos = (oos.get("trades") or 0) >= MIN_OOS and (month is None or month == self.month)
        rec = ({"n": oos["trades"], "hit": oos["hit"], "exp": oos["exp"], "held": oos.get("held")} if use_oos
               else {"n": ch["n"], "hit": ch["hit"], "exp": ch["exp"], "held": ch.get("held")})
        return {"ok": True, "family": self.family, "group": group, "rule": ch["rule"], "k": ch["k"], "m": ch.get("m"), "rr": ch.get("rr"),
                "avg_win": ch.get("avg_win"), "scope": ch.get("scope") or "grup", "month": month or self.month, "oos": use_oos,
                "n": rec["n"], "hit": rec["hit"], "exp": rec["exp"], "held": rec["held"] if rec.get("held") is not None else ch.get("held"),
                "carry_in": bool(g.get("carry_in")), "is": {k: ch.get(k) for k in ("n", "hit", "exp", "held", "target", "stop")},
                "oos_n": oos.get("trades") or 0}

    def to_json(self) -> Dict[str, Any]:
        return {"family": self.family, "rule": self.rule, "month": self.month, "groups": self.groups, "record": self.record, "n": self.n,
                "why": self.why}

    @classmethod
    def from_json(cls, doc: Dict[str, Any]) -> "Book":
        return cls(doc.get("family") or "", doc.get("rule") or "fixed", doc.get("month") or "", dict(doc.get("groups") or {}),
                   dict(doc.get("record") or {}), int(doc.get("n") or 0), doc.get("why") or "")


def calibrate(records: Iterable[Dict[str, Any]], family: str, today: str, rule: Optional[str] = None,
              window: int = WINDOW_MONTHS, oos: bool = True) -> Book:
    """The family's levels, walking forward a month at a time over the ``window`` months before today's and today's:
    each month's choice per group on the trades that had ended before it began (the family's, pooled, for a group with
    too few), each month's trades played at its choice - the out-of-sample record.  ``oos`` False: today's levels alone
    (a backtest's refit)."""
    rule = rule or RULES.get(family, "fixed")
    trades = []
    for r in records:
        try:
            t = Trade(r)
        except (KeyError, TypeError, ValueError):
            continue
        if t.n:
            trades.append(t)
    cur = month_of(today)
    months = months_back(cur, window) if oos else [cur]
    groups = sorted({t.group for t in trades})
    by_group: Dict[str, List[Trade]] = {g: [] for g in groups}
    for t in trades:
        by_group[t.group].append(t)
    out: Dict[str, Dict[str, Any]] = {g: {"months": {}, "carry_in": any(t.carry_in for t in by_group[g])} for g in groups}
    for M in months:
        def usable(ts: List[Trade]) -> Tuple[List[Trade], Optional[List[int]]]:
            if rule == "trail":
                sel = [t for t in ts if t.entry < M]
                return sel, [t.cut(M) for t in sel]
            return [t for t in ts if not t.open and t.end < M], None
        fam: Any = False                                            # (the family's pool: chosen only when a group needs it)
        for g in groups:
            ts, cuts = usable(by_group[g])
            ch = _choose_kept(family, rule, g, M, ts, cuts)
            if ch is not None:
                ch = dict(ch, scope="grup")
            else:
                if fam is False:
                    fs, fc = usable(trades)
                    fam = _choose_kept(family, rule, "*", M, fs, fc)
                    fam_n = len(fs)
                ch = dict(fam, scope="aile") if fam else None
                if ch is None and M == cur:
                    out[g]["why"] = ("seviye kalibrasyonu yok: geri testte %d işlem (grubunda %d; en az %d)" % (fam_n, len(ts), MIN_TRADES)
                                     if fam_n < MIN_TRADES else "seviye kalibrasyonu yok: ödül / risk ≥ 1 olan seviye bulunamadı")
            out[g]["months"][M] = ch
        if M == cur:
            for g in groups:
                out[g]["live"] = out[g]["months"][M]
    record: Dict[str, Any] = {}
    if oos:
        rows_g: Dict[str, List[Tuple[Trade, float, bool, int, str]]] = {g: [] for g in groups}
        first = months[0]
        for t in trades:
            M = month_of(t.entry)
            if M < first or (rule != "trail" and t.open):
                continue
            ch = out[t.group]["months"].get(M)
            if not ch:
                continue
            x, hit, h, how = play(t, ch)
            rows_g[t.group].append((t, x, hit, h, how))
        last = max((t.end for t in trades), default=None)
        every = []
        for g in groups:
            rows = rows_g[g]
            every += rows
            out[g]["oos"] = _summary(rows, first, last)
        record = _summary(every, first, last)
    for g in groups:
        out[g]["months"] = {M: ch for M, ch in out[g]["months"].items() if ch is not None}
    why = "" if trades else "geri testte işlem yok"
    return Book(family, rule, cur, out, record, len(trades), why)


# ---------------------------------------------------------------------------------------------- the lines
def group_of(m: Any) -> str:
    """The Sinyaller list's group of a monitor (``quantuniv.classify`` of what its signal will be), kept on it."""
    g = getattr(m, "_group", None)
    if g is None:
        from . import quantuniv as qu
        sg = {"info": m.info or {}, "legs": [{"key": leg.get("key")} for leg in m.legs or ()], "asset": m.asset,
              "fx": {"pair": m.fx} if m.fx else None, "packages": m.packages}
        g = m._group = qu.classify(sg)["group"]
    return g


def books_of(doc: Optional[Dict[str, Any]]) -> Dict[str, Book]:
    """The calibrated families of a stored backtest (``quantbt.backtest``'s ``levels``)."""
    out: Dict[str, Book] = {}
    for fam, d in ((doc or {}).get("families") or {}).items():
        if isinstance(d, dict):
            out[fam] = Book.from_json(d)
    return out


def calibrate_tables(tables: Dict[str, Any], today: str) -> List[str]:
    """Every family whose fit table carries its own walk-forward's trades with their paths (``table["backtest"]
    ["trades"]`` in quantbt's format with ``path_sigma``: a family that walks forward on its own, ``quantuniv``'s
    ``own_backtest``) and has no levels of its own yet: calibrated on them, ``table["levels"]`` - no code of its own.
    The ids of those calibrated."""
    out = []
    for fid, tab in tables.items():
        if not isinstance(tab, dict) or fid in OWN or isinstance(tab.get("levels"), dict):
            continue
        bt = tab.get("backtest")
        trades = [t for t in (bt.get("trades") or () if isinstance(bt, dict) else ())
                  if isinstance(t, dict) and t.get("path_sigma") and t.get("family", fid) == fid]
        if trades:
            tab["levels"] = calibrate(trades, fid, today).to_json()
            out.append(fid)
    return out


def line_for(m: Any, books: Optional[Dict[str, Book]], month: Optional[str] = None) -> Dict[str, Any]:
    """A monitor's levels from its family's book (``books`` None: no backtest yet), or why it has none."""
    fam = m.family
    if fam in KEEP:
        return {"ok": False, "own": True, "family": fam, "why": KEEP[fam]}
    if books is None:
        return {"ok": False, "family": fam, "why": "seviye kalibrasyonu: geri test henüz yok (kendi seviyeleri)"}
    b = books.get(fam)
    if b is None:
        return {"ok": False, "family": fam, "why": "seviye kalibrasyonu yok: geri testte bu ailenin işlemi yok"}
    return b.line(group_of(m), month)


#: a monitor's σ of its holding (σ in P&L units, P&L units a level unit, the holding in closes): ``make_signal``'s own
sigma_of = qf.holding_sigma
#: the levels in a few words ("stop 1,20σ · hedef 1,80σ · ödül / risk 1,50 · isabet %57 (46 işlem, örneklem dışı) …")
text = qf.levels_text


def fair_of(m: Any, target: Optional[float], sig: float, factor: float) -> Optional[float]:
    """A mean reversion's distance to its fair value (the window's mean, ``target_z`` from it) in σ_h."""
    if m.mode != "mr" or target is None or m.level is None or not sig:
        return None
    d = abs(target - m.level) * factor / sig
    return d if d > 0 and math.isfinite(d) else None
