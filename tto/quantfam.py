"""The signal families of the quant package (``tto.quant`` runs them): every analysis ends in *monitors* - one per
instrument it follows - and a monitor whose score is past its entry threshold is a *signal*.

A family reads a :class:`Ctx`: the daily closes kept in the history (only days before today: today is the live value),
the values now and the desk's settings.  It fits what it needs on the closes once a day and leaves, per instrument, a
:class:`Monitor`: the series it scores (with its window mean and standard deviation, Ornstein-Uhlenbeck half-life,
regime), the legs of the trade, its carry + roll, and a function that reads the level *now* from the live values - so
the once-a-minute refresh with live prices costs nothing but that function.

Families (``FAMILIES``) and what they score:

    corr      rolling correlation of daily changes; the 20-day one against its own long-run distribution (Fisher z)
    pca       TRY OIS curve: PC1-PC2 residual of each tenor (rich / cheap)
    rv        PCA-neutral flies (PC1 + PC2) and spreads (PC1), DV01-weighted
    macro     TRY curve changes on UST 2Y / 10Y, DXY, EM FX, Brent, CDS: today's TRY-specific residual
    pairs     Engle-Granger cointegrated pairs: the spread y − α − β·x
    kalman    the same pairs with a Kalman hedge ratio β_t: the one-step-ahead residual
    momentum  1W / 1M / 3M changes over volatility, moving-average cross; regime-gated
    volprem   ATM 3M implied − realized volatility
    volfc     ATM 3M implied − GARCH(1,1) forecast of the next three months
    emcarry   TRY's carry / vol against the EM basket
    viopcal   VİOP calendar spreads against the OIS / USD covered-interest-parity fair value
    frapath   OIS forwards (1x3 … 9x12) against the meeting-dated PPK path
    cycle     2s10s / 1s2s over the next weeks, by the phase of the policy cycle (TLREF)
    fwdprem   the depreciation the USDTRY / EURTRY forwards imply against the forecast drift (carry timing)
    model     L2 logistic regression of next week's direction, walk-forward validated
    imapath   the implied MPC / FOMC path against its grid: a period's kink against its neighbours (quantpath.py)
    imacal    the priced bigger move against what was decided: a calibration bias (quantpath.py)
    leadlag   who moves first: a follower that has not caught up with its leader's move yet (quantlead.py)

Units: rates are kept in per cent and move in bp; spreads, flies, residuals and CDS are in bp; FX levels move in per
cent (log); vols in vol points.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quantmath as qm

# ---------------------------------------------------------------------------------------------- families
#: id -> (label, kind, page): ``kind`` says how a signal is read - "mr" bets on the level returning to its mean (gated by
#: a mean-reverting regime and a half-life within the horizon), "trend" on it going on (gated by a trending regime),
#: "carry", "cycle", "model" on a premium / a conditional drift / a validated forecast, "surprise" fades today's
#: unexplained move, "corr" on a correlation coming back, "sys" a systematic family's daily line (no regime or half-life
#: gate: its own rules decide).  The families on the universe (Trend, Carry + momentum, ML) are ``quantuniv.FAMILIES``.
FAMILIES: Dict[str, Tuple[str, str, str]] = {
    "corr": ("Korelasyon kırılması", "corr", "quant-corr"),
    "pca": ("PCA kalıntısı", "mr", "quant-pca"),
    "rv": ("PCA-nötr fly / spread", "mr", "quant-pca"),
    "frapath": ("FRA / PPK patikası", "mr", "quant-pca"),
    "macro": ("Makro artık", "surprise", "quant-macro"),
    "pairs": ("Eşbütünleşik çift", "mr", "quant-pairs"),
    "kalman": ("Kalman çift", "mr", "quant-pairs"),
    "viopcal": ("VİOP takvim", "mr", "quant-pairs"),
    "momentum": ("Momentum", "trend", "quant-regime"),
    "cycle": ("PPK döngüsü", "cycle", "quant-regime"),
    "volprem": ("Vol primi", "mr", "quant-fx"),
    "volfc": ("Vol tahmini", "mr", "quant-fx"),
    "emcarry": ("EM carry", "carry", "quant-fx"),
    "fwdprem": ("Forward primi", "carry", "quant-fx"),
    "model": ("Tahmin modeli", "model", "quant-model"),
    "izscore": ("Gün içi z", "mr", "quant-intraday"),
    "iorb": ("Gün içi kırılım", "trend", "quant-intraday"),
    "irv": ("Gün içi RV", "mr", "quant-intraday"),
    "ipath": ("USDTRY carry patikası", "mr", "quant-intraday"),
    "imapath": ("İma patikası ayrıklığı", "mr", "quant-path"),       # quantpath.py: kinks of the implied path
    "imacal": ("İma kalibrasyonu", "model", "quant-path"),          # quantpath.py: a bias of the priced bigger move
    "leadlag": ("Öncü-takipçi", "model", "quant-lead"),             # quantlead.py: a follower that has not caught up
}

ASSETS = ("TRY OIS", "Offshore", "VİOP", "DİBS", "FX", "FX vol", "EM carry", "Global")

#: tenor label -> months (the OIS / offshore labels of the history)
_TENOR_MONTHS = {"1W": 0.25, "2W": 0.5, "1M": 1, "2M": 2, "3M": 3, "4M": 4, "5M": 5, "6M": 6, "9M": 9, "1Y": 12, "15M": 15,
                 "18M": 18, "21M": 21, "2Y": 24, "3Y": 36, "4Y": 48, "5Y": 60, "6Y": 72, "7Y": 84, "8Y": 96, "9Y": 108, "10Y": 120}
_MONTH_LABEL = {v: k for k, v in _TENOR_MONTHS.items()}

LN2 = math.log(2.0)
Z_REGIME = 1.645                 # |VR z| beyond this: a mean-reverting or a trending regime (10 %, two-sided)


def sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _num(v: Any) -> Optional[float]:
    return v if type(v) is float and math.isfinite(v) else (float(v) if type(v) is int else None)


# ---------------------------------------------------------------------------------------------- series kinds
#: how a level moves: rate (per cent, moves in bp), bp, vol / pts (moves as they are), fx / index (moves in % log), xr
#: (an FX pair's excess-return index: the cumulative log return of holding the pair through its forwards, carry
#: included, in per cent - it moves as it is)
def change(kind: str, a: float, b: float) -> Optional[float]:
    if kind == "rate":
        return (b - a) * 100.0
    if kind in ("fx", "index"):
        return math.log(b / a) * 100.0 if a > 0 and b > 0 else None
    return b - a


def to_level(kind: str, amount: float, level: float) -> float:
    """A move in change units (bp, %, points) as a move of the level."""
    if kind == "rate":
        return amount / 100.0
    if kind in ("fx", "index"):
        return level * amount / 100.0
    return amount


def change_unit(kind: str) -> str:
    return {"rate": "bp", "fx": "%", "index": "%", "xr": "%", "vol": "vol", "pts": "puan"}.get(kind, "bp")


def level_unit(kind: str) -> str:
    return {"rate": "%", "bp": "bp", "vol": "vol", "pts": "puan", "xr": "%"}.get(kind, "")


def pnl_scale(kind: str, level: Optional[float]) -> Tuple[str, Optional[float]]:
    """How a move of a level reads as profit and loss: (unit, factor) - a rate's move in bp, an excess-return index's
    in per cent of the notional, a spot's or an index's in per cent (log, near the level), vol in vol points."""
    if kind == "rate":
        return "bp", 100.0
    if kind == "xr":
        return "%", 1.0
    if kind in ("fx", "index"):
        return "%", (100.0 / level) if level else None
    if kind == "vol":
        return "vol", 1.0
    return "bp", 1.0


def shrunk_mean(values: Sequence[float], ewma: Optional[float] = None) -> Optional[Dict[str, float]]:
    """The mean of daily changes with its precision, shrunk towards zero by it: ``m × max(0, 1 − 4 / t²)`` where t is
    the mean over its standard error - a mean within two standard errors of zero is noise and contributes nothing.  ``ewma``: an exponentially weighted
    mean with this λ instead of the plain one (its standard error from the effective sample, (1 − λ) / (1 + λ))."""
    xs = [x for x in values if x is not None]
    if len(xs) < 10:
        return None
    sd = qm.stdev(xs)
    if not sd:
        return None
    if ewma:
        m = sum(xs[:20]) / min(20, len(xs))
        for x in xs[20:]:
            m = ewma * m + (1.0 - ewma) * x
        se = sd * math.sqrt((1.0 - ewma) / (1.0 + ewma))
    else:
        m = sum(xs) / len(xs)
        se = sd / math.sqrt(len(xs))
    t = m / se if se else 0.0
    w = shrink(t)
    return {"mean": m, "raw": m, "t": t, "w": w, "shrunk": m * w, "sd": sd, "n": len(xs)}


def shrink(t: float, k: float = 2.0) -> float:
    """The weight an estimate with this t keeps (positive-part James-Stein): 0 within ±k standard errors."""
    return max(0.0, 1.0 - k * k / (t * t)) if t else 0.0


# ---------------------------------------------------------------------------------------------- what the families read
class Ctx(object):
    """The closes before today (``series``: key -> {ISO day: value}), what each key is (``meta``: label, kind, months,
    group …), the values now (``live``), the settings (``cfg``) and the extras some families need: the VİOP history
    (``viop``), carry + roll per OIS tenor (``carry``: months -> bp a week, receiver), the meeting-pricing history
    (``mpc``) and today's meeting path (``path``)."""

    def __init__(self, cfg: Dict[str, Any], today: _dt.date, series: Dict[str, Dict[str, float]], meta: Dict[str, Dict[str, Any]],
                 live: Optional[Dict[str, float]] = None, viop: Optional[List[Dict[str, Any]]] = None,
                 carry: Optional[Dict[float, float]] = None, mpc: Optional[Dict[str, Any]] = None, path: Optional[Dict[str, Any]] = None,
                 holidays: Optional[set] = None, fwd_scale: Optional[Dict[str, int]] = None, desk: Optional[Dict[str, Any]] = None):
        self.cfg = cfg
        #: what the workbook says a trade's size is made of (``quant.Quant._read_engine``): USDTRY (OIS_MAIN!D2) and each
        #: OIS tenor's annuity (Motor!I) - as the blotter sizes a trade; empty: the quant's own (FX:USDTRY, the par rates)
        self.desk: Dict[str, Any] = desk or {}
        self.today = today
        self.today_iso = today.isoformat()
        self.series = {k: {d: v for d, v in pts.items() if d < self.today_iso and _num(v) is not None} for k, pts in series.items()}
        self.meta = meta
        self.live = {k: v for k, v in (live or {}).items() if _num(v) is not None}
        self.viop = viop or []
        self.carry = carry or {}
        self.mpc = mpc or {}
        self.path = path
        self.holidays = holidays or set()
        self.fwd_scale = fwd_scale or {}
        self._pts: Dict[str, List[Tuple[str, float]]] = {}
        self.notes: Dict[str, str] = {}
        self._construct()

    # ---- reading
    def pts(self, key: str) -> List[Tuple[str, float]]:
        hit = self._pts.get(key)
        if hit is None:
            hit = self._pts[key] = sorted((self.series.get(key) or {}).items())
        return hit

    def has(self, key: str, n: int = 2) -> bool:
        return len(self.series.get(key) or ()) >= n

    def last(self, key: str) -> Optional[float]:
        p = self.pts(key)
        return p[-1][1] if p else None

    def last_day(self, key: str) -> Optional[str]:
        p = self.pts(key)
        return p[-1][0] if p else None

    def cur(self, key: str, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        v = (self.live if live is None else live).get(key)
        return v if v is not None else self.last(key)

    def kind(self, key: str) -> str:
        return (self.meta.get(key) or {}).get("kind") or "rate"

    def label(self, key: str) -> str:
        return (self.meta.get(key) or {}).get("label") or key

    def months(self, key: str) -> Optional[float]:
        return (self.meta.get(key) or {}).get("months")

    def window(self) -> int:
        return int(self.cfg["lookback"])

    def min_obs(self) -> int:
        return int(self.cfg["min_obs"])

    def ois_keys(self, min_months: float = 0.0) -> List[str]:
        """The OIS tenors kept, shortest first."""
        keys = [k for k, m in self.meta.items() if k.startswith("OIS:") and m.get("months") is not None and m["months"] >= min_months
                and self.has(k)]
        return sorted(keys, key=lambda k: self.meta[k]["months"])

    def ois_at(self, months: float) -> Optional[str]:
        for k in self.ois_keys():
            if abs(self.meta[k]["months"] - months) < 1e-6:
                return k
        return None

    def carry_week(self, key: str) -> Optional[float]:
        """Carry + roll of paying the tenor (the level going up profits), bp a week (the carry engine gives receivers)."""
        m = self.months(key)
        if m is None or not key.startswith("OIS:"):
            return None
        for months, cr in self.carry.items():
            if abs(months - m) < 1e-6 and cr is not None:
                return -cr
        return None

    # ---- a package's size: its main leg's DV01, as the desk sizes a trade (OIS_MAIN!F2 "DV01/bacak $")
    def usdtry(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """USDTRY of the packages' TRY sizes: the workbook's (OIS_MAIN!D2 - what the blotter and DİBS RV!AK use), else
        the quant's own FX:USDTRY."""
        v = self.desk.get("usdtry")
        return v if v else self.try_per("USD", live)

    def dv01_size(self, live: Optional[Dict[str, float]] = None) -> Tuple[float, Optional[float]]:
        """The main leg's DV01 of every package: USD a bp (the setting ``dv01_usd``, 1.000 - the desk's OIS_MAIN!F2) and
        TRY a bp at USDTRY now (``None`` without a USDTRY)."""
        usd = float(self.cfg.get("dv01_usd") or 0.0)
        fx = self.usdtry(live)
        return usd, (usd * fx if usd and fx else None)

    def ois_annuity(self, key: str, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """A TRY OIS tenor's annuity (years; a unit nominal's DV01 is annuity × 1e-4): the workbook's (Motor!I - what the
        blotter sizes a trade with), else from its own par rate by the workbook's schedule (:func:`_annuity`)."""
        a = (self.desk.get("ois_annuity") or {}).get(key.split(":", 1)[-1].upper())
        if a:
            return a
        m, par = self.months(key), self.cur(key, live)
        return _annuity(par, m) if m and par is not None else None

    # ---- series built from others: the EM FX index and the FX forwards
    def _construct(self) -> None:
        em = [k for k in self.meta if k.startswith("FX:") and (self.meta[k].get("group") == "EM")]
        self._em_spots = [k for k in em if self.has(k, 20)]
        if len(self._em_spots) >= 3:
            days = sorted({d for k in self._em_spots for d in self.series[k]})
            prev: Dict[str, float] = {}
            level = 100.0
            out: Dict[str, float] = {}
            for d in days:
                moves = []
                for k in self._em_spots:
                    v = self.series[k].get(d)
                    if v is None:
                        continue
                    if k in prev and prev[k] > 0 and v > 0:
                        moves.append(math.log(v / prev[k]))
                    prev[k] = v
                if len(moves) >= 3:
                    level *= math.exp(sum(moves) / len(moves))
                    out[d] = level
            if out:
                self.series["EMFX"] = out
                self.meta["EMFX"] = {"label": "EM FX (USD / EM sepeti)", "kind": "index", "group": "Global", "asset": "Global"}
        for k in [k for k in self.meta if k.startswith("FXP:")]:
            _, pair, tenor = k.split(":")
            spot = self.series.get("FX:" + pair) or {}
            pts = self.series.get(k) or {}
            fwd = {}
            for d, p in pts.items():
                s = spot.get(d)
                f = self.forward(pair, s, p) if s else None
                if f is not None:
                    fwd[d] = f
            if fwd:
                key = "FWD:%s:%s" % (pair, tenor)
                self.series[key] = fwd
                self.meta[key] = {"label": "%s %s forward" % (pair, tenor), "kind": "fx", "group": "FX", "asset": "FX",
                                  "pair": pair, "tenor": tenor, "days": _tenor_days(tenor)}
        # the excess return of holding each pair through its forwards (carry included): what a directional FX trade
        # earns - only over the days a forward says what the carry was (never a carry made up)
        self._xr_last: Dict[str, Tuple[str, float]] = {}
        for pair in sorted({k.split(":")[1] for k in self.series if k.startswith("FWD:")}):
            spot = self.series.get("FX:" + pair) or {}
            carry = self.fx_carry_days(pair)
            if len(spot) < 2 or not carry:
                continue
            xr: Dict[str, float] = {}
            level = 0.0
            prev = None
            last_c: Optional[Tuple[str, float]] = None
            for d in sorted(spot):
                if prev is not None and last_c is not None:
                    if (_dt.date.fromisoformat(prev) - _dt.date.fromisoformat(last_c[0])).days <= 7:
                        gap = (_dt.date.fromisoformat(d) - _dt.date.fromisoformat(prev)).days
                        if spot[prev] > 0 and spot[d] > 0:
                            level += math.log(spot[d] / spot[prev]) * 100.0 + last_c[1] * gap / 365.0
                        xr[d] = level
                    else:
                        xr, level = {}, 0.0                  # the forwards stopped for a while: start again after it
                if d in carry:
                    last_c = (d, carry[d])
                    if not xr:
                        xr[d] = level
                prev = d
            if len(xr) >= 2:
                key = "XR:" + pair
                self.series[key] = xr
                g = (self.meta.get("FX:" + pair) or {}).get("group") or "FX"
                self.meta[key] = {"label": "%s forward pozisyonu" % pair, "kind": "xr", "group": g, "asset": "FX", "pair": pair}
                if last_c is not None:
                    self._xr_last[pair] = last_c

    # ---- FX carry: what holding a pair through its forwards pays or costs
    def fx_pairs(self) -> List[str]:
        """The pairs with a spot history, in the order of their keys - the desk's list (a pair only the G10 universe
        keeps, ``meta["universe"]``, is the families' on it: quantuniv.py)."""
        return sorted(k[3:] for k in self.meta if k.startswith("FX:") and self.series.get(k) and not self.meta[k].get("universe"))

    def fx_tenors(self, pair: str) -> List[Tuple[str, float]]:
        """The forward tenors kept for a pair, shortest first: (tenor, calendar days)."""
        out = [(k.split(":")[2], float(self.meta[k]["days"])) for k in self.series if k.startswith("FWD:%s:" % pair) and k in self.meta]
        return sorted(out, key=lambda t: t[1])

    def fx_carry_days(self, pair: str) -> Dict[str, float]:
        """Each close's carry of holding the pair long (see :meth:`fx_carry`), from the shortest forward kept that day."""
        out: Dict[str, float] = {}
        spot = self.series.get("FX:" + pair) or {}
        for tenor, days in reversed(self.fx_tenors(pair)):          # the shortest last: it wins
            for d, f in (self.series.get("FWD:%s:%s" % (pair, tenor)) or {}).items():
                s = spot.get(d)
                if s and f and s > 0 and f > 0:
                    out[d] = (math.log(s) - math.log(f)) * 365.0 / days * 100.0
        return out

    def fx_carry(self, pair: str, live: Optional[Dict[str, float]] = None, days: Optional[float] = None) -> Optional[float]:
        """The carry of holding the pair long - the base currency against the quote - through its forward, annualised
        (%, log, a year of 365 days): (ln S − ln F) × 365 / days.  Negative when the forward is above the spot (long
        USDTRY pays the TRY rate).  ``days``: over a holding of that many calendar days, interpolated along the
        forwards kept (flat beyond them); else the shortest forward's.  ``None`` without a forward: no carry is made up."""
        live = self.live if live is None else live
        s = self.cur("FX:" + pair, live)
        if not s or s <= 0:
            return None
        pts = []
        for tenor, n in self.fx_tenors(pair):
            f = self.cur("FWD:%s:%s" % (pair, tenor), live)
            if live.get("FX:" + pair) is not None or live.get("FXP:%s:%s" % (pair, tenor)) is not None:
                f = self.forward(pair, s, self.cur("FXP:%s:%s" % (pair, tenor), live))
            if f and f > 0:
                pts.append((n, (math.log(s) - math.log(f)) * 365.0 / n * 100.0))
        if not pts:
            return None
        if days is None:
            return pts[0][1]
        return _interp(pts, float(days))

    def try_per(self, ccy: str, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """TRY a unit of ``ccy`` is worth now (through USDTRY and the dollar pair of the currency)."""
        if ccy == "TRY":
            return 1.0
        usdtry = self.cur("FX:USDTRY", live)
        if not usdtry:
            return None
        if ccy == "USD":
            return usdtry
        direct = self.cur("FX:%sTRY" % ccy, live)
        if direct:
            return direct
        x = self.cur("FX:USD" + ccy, live)
        if x:
            return usdtry / x
        y = self.cur("FX:%sUSD" % ccy, live)
        return usdtry * y if y else None

    def forward(self, pair: str, spot: Optional[float], quote: Optional[float]) -> Optional[float]:
        """The outright forward from a forward quote: a quote near the spot is an outright already (NDF tickers),
        otherwise points in units of 10^-scale (Bloomberg's FWD_SCALE: 4, 2 for the yen …)."""
        if spot is None or quote is None or spot <= 0:
            return None
        if 0.8 * spot <= quote <= 1.25 * spot:
            return quote
        scale = self.fwd_scale.get(pair)
        if scale is None:
            scale = 2 if pair.endswith("JPY") else 4
        f = spot + quote * 10.0 ** (-scale)
        return f if f > 0 else None

    def derive_live(self, live: Dict[str, float]) -> Dict[str, float]:
        """The live values of the series built from others (the EM FX index, the forwards)."""
        out = dict(live)
        if "EMFX" in self.series and self._em_spots:
            moves = [math.log(live[k] / self.last(k)) for k in self._em_spots if live.get(k) and self.last(k)]
            if len(moves) >= 3 and self.last("EMFX"):
                out["EMFX"] = self.last("EMFX") * math.exp(sum(moves) / len(moves))
        for k in [k for k in self.series if k.startswith("FWD:")]:
            _, pair, tenor = k.split(":")
            s, q = live.get("FX:" + pair), live.get("FXP:%s:%s" % (pair, tenor))
            if s is not None or q is not None:
                f = self.forward(pair, s if s is not None else self.last("FX:" + pair), q if q is not None else self.last("FXP:%s:%s" % (pair, tenor)))
                if f is not None:
                    out[k] = f
        # the excess-return index now: the spot's move since the last close plus the carry of the days since
        for pair, (cday, c) in self._xr_last.items():
            key = "XR:" + pair
            s, s0, x0, d0 = live.get("FX:" + pair), self.last("FX:" + pair), self.last(key), self.last_day(key)
            if s is None or not s0 or x0 is None or d0 is None or s <= 0:
                continue
            gap = max(0, (self.today - _dt.date.fromisoformat(d0)).days)
            out[key] = x0 + math.log(s / s0) * 100.0 + c * gap / 365.0
        return out


def _tenor_days(tenor: str) -> float:
    """Calendar days of an FX tenor (a year 365)."""
    m = _TENOR_MONTHS.get(tenor.upper().replace("12M", "1Y"))
    return 365.0 * (m or 3) / 12.0


# ---------------------------------------------------------------------------------------------- alignment
def aligned(ctx: Ctx, keys: Sequence[str], last: Optional[int] = None) -> Tuple[List[str], List[List[float]]]:
    """The days every key has a close on (at most the ``last`` of them) and the values of each key on them."""
    sets = [ctx.series.get(k) or {} for k in keys]
    if not sets or any(not s for s in sets):
        return [], [[] for _ in keys]
    days = sorted(set(sets[0]).intersection(*sets[1:]))
    if last is not None:
        days = days[-last:]
    return days, [[s[d] for d in days] for s in sets]


def diffs(kind: str, values: Sequence[float]) -> List[float]:
    out = []
    for a, b in zip(values, values[1:]):
        c = change(kind, a, b)
        out.append(c if c is not None else 0.0)
    return out


# ---------------------------------------------------------------------------------------------- monitors
class Monitor(object):
    """One instrument a family follows: the series it scores, how to read it now, the trade it stands for."""

    def __init__(self, sid: str, family: str, asset: str, name: str, unit: str, digits: int, days: List[str], values: List[float],
                 legs: List[Dict[str, Any]], calc: Callable[[Dict[str, float]], Optional[float]], **kw: Any):
        self.sid = sid
        self.family = family
        self.kind = FAMILIES[family][1]
        self.asset = asset
        self.name = name
        self.unit = unit
        self.digits = digits
        self.days = days                      # the level's history (closes) - what the chart draws
        self.values = values
        self.legs = legs                      # [{key, name, weight}]: the package moves as Σ weight × level of key
        self.calc = calc                      # live values -> the level now
        self.zvalues: Optional[List[Optional[float]]] = kw.get("zvalues")      # the score's history, when not the level's z
        self.zfn: Optional[Callable[[float, Dict[str, float]], Optional[float]]] = kw.get("zfn")
        self.mean: Optional[float] = kw.get("mean")
        self.sd: Optional[float] = kw.get("sd")
        self.transform: Optional[str] = kw.get("transform")                   # "fisher": z of the Fisher transform
        self.entry: Optional[float] = kw.get("entry")                         # own entry threshold (None: the desk's)
        self.follows: bool = bool(kw.get("follows", False))                   # the trade goes with the score (not against)
        self.mode: str = kw.get("mode", "mr")                                 # "mr": target/stop on the level's own z; "drift"
        self.reward: Optional[float] = kw.get("reward")
        self.risk: Optional[float] = kw.get("risk")
        self.half_life: Optional[float] = kw.get("half_life")
        self.hold: Optional[float] = kw.get("hold")
        self.regime: Optional[Dict[str, Any]] = kw.get("regime")
        self.gate: Optional[Callable[[int], Tuple[float, str]]] = kw.get("gate")
        self.carry_up: Optional[float] = kw.get("carry_up")                   # bp (level units) a week for the package going up
        self.pkg: str = kw.get("pkg", "pair")
        self.legs_sign: Optional[int] = kw.get("legs_sign")                   # the legs' own direction (correlation)
        self.note: str = kw.get("note", "")
        self.info: Dict[str, Any] = kw.get("info") or {}
        self.score_name: str = kw.get("score_name", "z")
        # the decision: the expected move of the level over the holding (level units, + up; a number or a function of
        # the level and the score), the standard deviation of its daily moves, how a move reads as profit (unit, factor),
        # the FX pair whose carry the trade earns or pays (its level then is the excess-return index: carry inside), a
        # one-sentence thesis (a function of the signal), a minimum distance of the level from 0 (a tolerance) and the
        # sample behind it (n, the independent periods in it, the threshold it was held to)
        self.fcast: Any = kw.get("fcast")
        self.dsd: Optional[float] = kw.get("dsd")
        self.pnl: Optional[Tuple[str, Optional[float]]] = kw.get("pnl")
        self.fx: Optional[str] = kw.get("fx")
        self.thesis: Optional[Callable[[Dict[str, Any]], str]] = kw.get("thesis")
        self.min_abs: Optional[float] = kw.get("min_abs")
        self.sample: Optional[Dict[str, Any]] = kw.get("sample")
        self.gate_name: str = kw.get("gate_name", "Onay")
        self.expect: Optional[Callable[[int, float], Optional[float]]] = kw.get("expect")    # (side, hold) -> P&L, carry in
        self.pnl_sd: Optional[float] = kw.get("pnl_sd")                       # a day's (a bar's) σ of the P&L, when not dsd × factor
        self.horizon_unit: str = kw.get("horizon_unit", "gün")
        self.horizon: Optional[float] = kw.get("horizon")                     # what its half-life is held to, in horizon_unit (None: the desk's)
        self.intraday: bool = bool(kw.get("intraday", False))
        # the trade told leg by leg (a hedged package: the expression names every leg); its title, and other packages
        # that trade the same signal ([{name, legs, carry_up (P&L units a week, the package going up), note}])
        self.explicit: bool = bool(kw.get("explicit", False))
        self.pkg_name: Optional[str] = kw.get("pkg_name")
        self.packages: List[Dict[str, Any]] = kw.get("packages") or []
        # an FX trade told in the prices of what is traded (:func:`fx_trade`): how the level reads as that price - None:
        # the forward of the holding (its value date the holding's end), the level moving in per cent of it (an
        # excess-return index, a deviation in log %); "level": the level is the price (a spot, the 3M forward); a
        # function (level, fx info) -> price -, the instrument when it is not the holding's forward (its name, its
        # length in calendar days), what the expected P&L's per cent is a per cent of ("inst": the instrument's price,
        # a log return; "spot": the spot, a simple one) and what the drawn series is, when it is not that price
        self.price: Any = kw.get("price")
        self.inst: Optional[str] = kw.get("inst")
        self.inst_days: Optional[float] = kw.get("inst_days")
        self.pct_base: str = kw.get("pct_base", "inst")
        self.series_label: Optional[str] = kw.get("series_label")
        # (currency, money a P&L unit makes) of a line whose money is linear in it and told by no other way: an
        # option's vega (vol points), a swap's points - the universe's lines set it (quantuniv.py)
        self.cash: Optional[Tuple[str, float]] = kw.get("cash")
        self.fxinfo: Dict[str, Any] = {}
        self.level: Optional[float] = None
        self.z: Optional[float] = None
        self.live = False

    def zof(self, level: Optional[float], live: Optional[Dict[str, float]] = None) -> Optional[float]:
        if level is None:
            return None
        if self.zfn is not None:
            return self.zfn(level, live or {})
        if self.mean is None or not self.sd:
            return None
        x = qm.fisher(level) if self.transform == "fisher" else level
        return (x - self.mean) / self.sd

    def score(self, live: Dict[str, float], raw_live: Dict[str, float]) -> None:
        try:
            self.level = self.calc(live)
            self.z = self.zof(self.level, live)
        except Exception:  # noqa: BLE001 - a value that cannot be read now is no score (the monitor stays)
            self.level, self.z = None, None
        self.live = any(leg.get("key") in raw_live for leg in self.legs) or any(k in raw_live for k in self.info.get("inputs", ()))

    def inv(self, x: float) -> float:
        return math.tanh(x) if self.transform == "fisher" else x

    def z_history(self) -> List[Optional[float]]:
        if self.zvalues is not None:
            return list(self.zvalues)
        if self.mean is None or not self.sd:
            return [None] * len(self.values)
        return [((qm.fisher(v) if self.transform == "fisher" else v) - self.mean) / self.sd for v in self.values]

    def history(self) -> Dict[str, Any]:
        return {"days": list(self.days), "values": list(self.values), "z": self.z_history(), "mean": self.inv(self.mean) if self.mean is not None else None,
                "sd": self.sd, "transform": self.transform}


def window_stats(values: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    sd = qm.stdev(values)
    return (sum(values) / len(values) if values else None), sd


def regime_of(values: Sequence[float], kind: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The regime of a level series: the variance ratio of its changes (Lo-MacKinlay, robust z) decides
    mean-reverting / trending / neither; the Hurst exponent (variance-time) and where today's 20-day volatility stands
    among the window's are shown with it."""
    win = int(cfg.get("regime_window") or 250)
    ch = diffs(kind, values)[-win:]
    q = int(cfg.get("vr_q") or 10)
    vr = qm.variance_ratio(ch, q) if len(ch) >= 4 * q else None
    h = qm.hurst(ch)
    tag = "Nötr"
    if vr and vr["z"] is not None:
        if vr["z"] <= -Z_REGIME:
            tag = "MR"
        elif vr["z"] >= Z_REGIME:
            tag = "Trend"
    vols = []
    if len(ch) >= 40:
        for i in range(20, len(ch) + 1):
            sd = qm.stdev(ch[i - 20:i])
            if sd:
                vols.append(sd)
    pct = qm.percentile(vols[-1], vols) if vols else None
    vol_tag = "yüksek vol" if pct is not None and pct >= 0.8 else ("düşük vol" if pct is not None and pct <= 0.2 else "")
    return {"tag": tag if vr else None, "vr": vr["vr"] if vr else None, "vr_z": vr["z"] if vr else None, "q": q, "hurst": h,
            "vol_pct": pct, "vol_tag": vol_tag, "n": len(ch)}


REGIME_TEXT = {"MR": "Ortalamaya dönüş", "Trend": "Trend", "Nötr": "Nötr", None: "—"}


def ou_of(values: Sequence[float]) -> Optional[Dict[str, Any]]:
    return qm.ou_fit(list(values)) if len(values) >= 20 else None


def mr_monitor(ctx: Ctx, sid: str, family: str, asset: str, name: str, unit: str, digits: int, days: List[str],
               values: List[float], kind: str, legs: List[Dict[str, Any]], calc: Callable, **kw: Any) -> Optional[Monitor]:
    """A mean-reversion monitor on its own level: window mean / standard deviation, OU half-life, regime."""
    win = ctx.window()
    days, values = days[-win:], values[-win:]
    if len(values) < ctx.min_obs() * kw.pop("min_share", 1.0):
        return None
    mean, sd = window_stats(values)
    if not sd:
        return None
    ou = ou_of(values)
    kw.setdefault("dsd", qm.stdev([b - a for a, b in zip(values, values[1:])]))         # level units
    kw.setdefault("pnl", ("bp", 1.0) if unit == "bp" else pnl_scale(kind, values[-1]))
    return Monitor(sid, family, asset, name, unit, digits, days, values, legs, calc, mean=mean, sd=sd,
                   half_life=ou["half_life"] if ou else None, regime=kw.pop("regime", None) or regime_of(values, kind, ctx.cfg),
                   info=dict(kw.pop("info", {}), ou=ou), **kw)


# ---------------------------------------------------------------------------------------------- leg texts
#: what a position on a level is called, by the key's kind: (+1 profits when the level rises, −1 when it falls)
def _verbs(key: str) -> Tuple[str, str]:
    if key.startswith(("OIS:", "OFF:", "USD:", "MPC:", "FOMC:")) or key == "TLREF":      # (MPC: / FOMC: meeting-dated OIS)
        return "Pay", "Receive"
    if key.startswith(("UST:", "DIBS:")):
        return "Sell", "Buy"
    if key.startswith("FXP:"):
        return "Pay", "Receive"
    if key == "CDS":
        return "Buy protection", "Sell protection"
    if key.startswith("SLOPE:"):
        return "Steepener", "Flattener"
    return "Buy", "Sell"


PKG_VERBS = {"rate": ("Pay", "Receive"), "bond": ("Sell", "Buy"), "fx": ("Buy", "Sell"), "vol": ("Buy", "Sell"),
             "cds": ("Buy protection", "Sell protection"), "slope": ("Steepener", "Flattener"), "spread": ("Buy", "Sell")}


def fmt_w(w: float) -> str:
    return ("%.2f" % abs(w)).replace(".", ",")


def signal_leg(leg: Dict[str, Any], pkg_s: int) -> Dict[str, Any]:
    """A package's leg as a signal shows it: what to do (``action``: Pay / Receive, Buy / Sell …) on what, its DV01
    weight, and its size for the package's main-leg DV01 - TRY and USD a bp, nominal in mn TRY (unsigned: the action
    says the side)."""
    w = leg.get("weight", 1.0)
    side = sign(pkg_s * w)
    up, down = _verbs(leg["key"])
    action = up if side > 0 else down
    out = {"key": leg["key"], "name": leg["name"], "weight": abs(w), "side": side, "action": action,
           "text": "%s %s" % (action, leg["name"]) + ("" if abs(abs(w) - 1.0) < 1e-9 else " ×" + fmt_w(w))}
    for k in ("dv01", "dv01_usd", "notional"):
        v = leg.get(k)
        out[k] = abs(v) if v is not None else None
    return out


def size_legs(ctx: "Ctx", legs: List[Dict[str, Any]], live: Optional[Dict[str, float]] = None) -> None:
    """Each TRY OIS leg's size for its package's main-leg DV01 (:meth:`Ctx.dv01_size`; weights are DV01 weights): its
    DV01 in TRY and USD a bp (signed as the weight) and its nominal (mn TRY) - DV01 ÷ (annuity × 1e-4), the annuity
    the workbook's.  A leg its family sized already (a bond: its DV01 a 1 mn nominal) is left as it is."""
    usd, tl = ctx.dv01_size(live)
    if not usd:
        return
    for leg in legs:
        key = leg.get("key") or ""
        if "dv01_usd" in leg or not key.startswith("OIS:"):
            continue
        w = float(leg.get("weight", 1.0))
        ann = ctx.ois_annuity(key, live)
        leg["dv01_usd"] = w * usd
        leg["dv01"] = w * tl if tl else None
        leg["notional"] = abs(w) * tl / (ann * 1e-4) / 1e6 if tl and ann else None


def size_monitors(ctx: "Ctx", mons: List["Monitor"]) -> None:
    """Every monitor's packages sized (once: a sized leg is left)."""
    for m in mons:
        size_legs(ctx, m.legs)
        for p in m.packages:
            size_legs(ctx, p["legs"])


# ---------------------------------------------------------------------------------------------- signals
def strength(ratio: float) -> str:
    return "Güçlü" if ratio >= 1.5 else ("Orta" if ratio >= 1.25 else "Zayıf")


STRENGTHS = ("Zayıf", "Orta", "Güçlü")


def regime_factor(kind: str, tag: Optional[str]) -> Tuple[float, str]:
    if kind in ("mr", "surprise"):
        if tag == "MR":
            return 1.0, ""
        if tag == "Trend":
            return 0.0, "rejim trend: ortalamaya dönüş sinyali sayılmaz"
        return 0.5, ""
    if kind == "trend":
        if tag == "Trend":
            return 1.0, ""
        if tag == "MR":
            return 0.0, "rejim ortalamaya dönüş: momentum sinyali sayılmaz"
        return 0.5, ""
    return 1.0, ""


def hl_factor(kind: str, hl: Optional[float], cfg: Dict[str, Any], horizon: Optional[float] = None, unit: str = "gün") -> Tuple[float, str]:
    """A mean reversion's weight by its half-life against the horizon: 1 within it, horizon ÷ half-life up to
    ``hl_max_mult`` horizons, 0 beyond - and with no half-life.  ``horizon`` in the half-life's own ``unit`` (an
    intraday monitor's in bars); not given: the desk's, ``cfg["horizon"]`` business days."""
    if kind not in ("mr", "corr"):
        return 1.0, ""
    horizon = float(cfg["horizon"] if horizon is None else horizon)
    if hl is None:
        return 0.0, "ortalamaya dönmüyor (AR(1) katsayısı 0 – 1 dışında)"
    if hl <= horizon:
        return 1.0, ""
    if hl <= float(cfg["hl_max_mult"]) * horizon:
        return horizon / hl, ""
    return 0.0, "yarı ömür %.0f %s: ufkun (%d %s) %g katından uzun" % (hl, unit, int(horizon), unit, float(cfg["hl_max_mult"]))


def _gate(name: str, ok: bool, text: str, part: Optional[float] = None) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "text": text, "part": part}


def _g(v: Optional[float], d: int = 1) -> str:
    """A number for the texts, Turkish style (decimal comma)."""
    if v is None:
        return "—"
    return ("%.*f" % (d, v)).replace(".", ",")


def _sg(v: Optional[float], d: int = 1) -> str:
    return "—" if v is None else ("+" if v > 0 else "") + _g(v, d)


def fx_info(ctx: "Ctx", pair: str, live: Dict[str, float], hold: Optional[float], cal_days: Optional[float] = None) -> Dict[str, Any]:
    """What an FX trade's decision needs now: the spot, the carry of a long (annualised, the shortest forward's and the
    holding's), the forward of the holding's end and what a unit of the quote currency is in TRY.  ``hold`` in business
    days (``cal_days``: calendar days instead - an intraday holding)."""
    cal = cal_days if cal_days is not None else (hold or 20.0) * 7.0 / 5.0
    s = ctx.cur("FX:" + pair, live)
    c = ctx.fx_carry(pair, live)
    ch = ctx.fx_carry(pair, live, days=cal)
    return {"pair": pair, "spot": s, "carry_yr": c, "carry_h_yr": ch, "cal_days": cal,
            "fwd_h": s * math.exp(-ch * cal / 365.0 / 100.0) if s and ch is not None else None,
            "try_per_quote": ctx.try_per(pair[3:], live), "try_per_usd": ctx.try_per("USD", live), "tenors": [t for t, _ in ctx.fx_tenors(pair)]}


# ---------------------------------------------------------------------------------------------- the trade in desk words
#: an FX signal's money is told for this much of the base currency (1 mn USD of USDTRY, 1 mn EUR of EURUSD ...)
FX_NOTIONAL = 1e6
#: the lengths a forward is named by (calendar days -> the desk's Turkish tenor): a 28-day holding is the "1A" forward
TENORS_TR = ((7.0, "1H"), (14.0, "2H"), (30.4375, "1A"), (60.875, "2A"), (91.3125, "3A"), (182.625, "6A"), (273.9375, "9A"), (365.25, "1Y"))
_TENOR_WORDS = {"H": "haftalık", "A": "aylık", "Y": "yıllık"}


def _th(v: float, d: int = 0) -> str:
    """A number Turkish style, with thousands: 2.325 · 44,1250 · -1.800."""
    s = "%.*f" % (d, abs(v))
    whole, _, frac = s.partition(".")
    out = "{:,}".format(int(whole)).replace(",", ".") + ("," + frac if frac else "")
    return ("-" if v < 0 and any(c in "123456789" for c in s) else "") + out


def _money(v: Optional[float], ccy: str, sign: bool = True) -> str:
    """Money as the desk says it: "+525 bin TRY", "4,2 bin USD", "-1.800 bin TL" (thousands; 10 mn and over in mn)."""
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e7:
        txt = "%s mn" % _th(a / 1e6, 1)
    elif a >= 1e3:
        txt = "%s bin" % _th(a / 1e3, 1 if a < 1e4 else 0)
    else:
        txt = _th(a, 0)
    nz = any(c in "123456789" for c in txt)
    sg = ("+" if v > 0 and sign else "-" if v < 0 else "") if nz else ""
    return ("%s%s %s" % (sg, txt, ccy)).strip()


def tenor_tr(days: Optional[float]) -> Optional[str]:
    """A forward's length in calendar days as the desk names it: "1H", "1A", "3A", "1Y" - or "45 gün"."""
    if days is None:
        return None
    best = min(TENORS_TR, key=lambda t: abs(t[0] - days))
    return best[1] if abs(best[0] - days) <= max(3.0, 0.1 * best[0]) else "%d gün" % int(round(days))


def _tenor_en(tenor: str) -> str:
    """A tenor of the history's keys ("1W", "3M", "1Y") the desk's Turkish way ("1H", "3A", "1Y")."""
    t = tenor.upper()
    return t[:-1] + {"W": "H", "M": "A"}.get(t[-1:], t[-1:])


def _tenor_long(tenor: str) -> str:
    """"3A" -> "3 aylık", "1H" -> "1 haftalık", "45 gün" -> "45 günlük"."""
    if tenor.endswith(" gün"):
        return tenor + "lük"
    return "%s %s" % (tenor[:-1], _TENOR_WORDS.get(tenor[-1:], tenor[-1:]))


def fx_digits(price: float) -> int:
    """Decimals a pair's price is quoted with: USDTRY 44,1250, EURUSD 1,08430, USDJPY 155,230, USDKRW 1.390,50."""
    a = abs(price)
    return 5 if a < 10 else 4 if a < 100 else 3 if a < 1000 else 2


def pct_money(pct: float, s: int, ref: float, log: bool = True, notional: float = FX_NOTIONAL) -> float:
    """A P&L of ``pct`` per cent (in the trade's favour, side ``s``) as money in the quote currency for ``notional`` of
    the base: a log return of the price ``ref`` (the price moves to ref × e^(s × pct / 100)) - or, ``log`` False, a
    simple per cent of ``ref`` (the spot)."""
    if log:
        return notional * s * ref * (math.exp(s * pct / 100.0) - 1.0)
    return notional * ref * pct / 100.0


def fx_trade(m: "Monitor", s: int, target: Optional[float], stop: Optional[float], exp: Optional[float], carry_h: Optional[float],
             fx: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """An FX signal as the desk trades it.  The instrument: the forward of the holding (its value date the holding's
    end), else the family's own (the 3M forward, the spot).  Its price now, at the target, at the stop and where the
    expected P&L takes it by the end of the holding, the spot now and then.  Its money for 1 mn of the base currency,
    in the quote currency: the expected P&L (= notional × the instrument's expected price move), the forward premium's
    part of it (the carry the holding earns or pays) and the spot's move (the rest: carry + move = total, move =
    notional × the spot's expected move), what the target and the stop make.  ``(None, None)`` without a spot and a
    forward of the holding: no carry is made up."""
    pair = str(fx.get("pair") or m.fx or "")
    spot, fwd = fx.get("spot"), fx.get("fwd_h")
    if not spot or not fwd or m.level is None or len(pair) != 6:
        return None, None
    _, factor = m.pnl or (None, None)
    level = m.level
    cal = fx.get("cal_days")
    days = m.inst_days if m.inst_days is not None else cal
    at_spot = (m.inst or "").endswith(" spot") or (m.inst is None and days is not None and days < 1.0)
    anchor = spot if at_spot else fwd                     # (an intraday holding trades the spot, a longer one its forward)
    if m.price == "level":
        price: Callable[[float], Optional[float]] = lambda x: x                    # noqa: E731
    elif callable(m.price):
        price = lambda x: m.price(x, fx)                                          # noqa: E731
    elif factor:
        price = lambda x: anchor * math.exp((x - level) * factor / 100.0)         # noqa: E731
    else:
        return None, None
    try:
        p0 = price(level)
        pt = price(target) if target is not None else None
        ps = price(stop) if stop is not None else None
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None, None
    if not p0 or p0 <= 0:
        return None, None
    n = FX_NOTIONAL
    log = m.pct_base != "spot"
    ref = p0 if log else spot
    total = pct_money(exp, s, ref, log) if exp is not None else None
    if not log and cal and m.inst_days:
        # (a premium told as a simple per cent of the spot: the instrument's points earned over the holding, the spot
        # where it is - so the rest is the spot's expected move alone)
        carry: Optional[float] = n * s * (spot - p0) * cal / m.inst_days
    else:
        carry = pct_money(carry_h, s, ref, log) if carry_h is not None else None       # (log: the roll of the instrument, exact)
    move = total - carry if total is not None and carry is not None else None
    tenor = None if at_spot else tenor_tr(days)
    inst = m.inst or ("%s spot" % pair if at_spot else "%s %s forward" % (pair, tenor))
    note = "spot" if at_spot else "bugünkü %s forward%s" % (tenor, "" if m.inst or days is None else ", %d gün: ufkun sonu valörlü" % int(round(days)))
    base, quote = pair[:3], pair[3:]
    tpq, tpu = fx.get("try_per_quote"), fx.get("try_per_usd")
    usd_per = 1.0 if quote == "USD" else (tpq / tpu if tpq and tpu else None)
    px = {"pair": pair, "inst": inst, "label": inst.replace(" forward", " fwd"), "tenor": tenor, "days": days, "note": note,
          "digits": fx_digits(p0), "unit": quote, "entry": p0, "target": pt, "stop": ps,
          "exit": p0 + s * total / n if total is not None else None, "spot": spot,
          "spot_exp": spot + s * move / n if move is not None else None, "fwd_h": fwd}
    money = {"ccy": quote, "base": base, "notional": n, "total": total, "carry": carry, "move": move,
             "target": n * s * (pt - p0) if pt is not None else None, "stop": n * s * (ps - p0) if ps is not None else None,
             "try_per": tpq, "usd_per": usd_per, "pct": exp, "ref": ref, "log": log}
    return px, money


def rate_money(legs: List[Dict[str, Any]], cfg: Dict[str, Any], tl: Optional[float], exp: Optional[float], carry_h: Optional[float],
               reward: Optional[float], risk: Optional[float]) -> Optional[Dict[str, Any]]:
    """A rates package's money: bp of its main leg's DV01 at ``tl`` TL a bp - the expected P&L, its carry + roll and
    the rest (the move), what the target makes and the stop loses; in bp and TL."""
    if not tl:
        return None
    main = legs[0] if legs else {}
    usd = main["dv01_usd"] / main["weight"] if main.get("dv01_usd") and main.get("weight") else cfg.get("dv01_usd")
    bp = {"total": exp, "carry": carry_h, "move": exp - carry_h if exp is not None and carry_h is not None else None,
          "target": reward, "stop": -risk if risk is not None else None}
    out: Dict[str, Any] = {"ccy": "TL", "per_bp": tl, "dv01_usd": float(usd) if usd else None, "bp": bp}
    out.update({k: v * tl if v is not None else None for k, v in bp.items()})
    return out


def cash_money(ccy: str, per: float, unit: Optional[str], exp: Optional[float], carry_h: Optional[float], reward: Optional[float],
               risk: Optional[float], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """A line whose money is linear in its P&L units (``Monitor.cash``: an option's vega, a swap's points): ``per`` of
    ``ccy`` a unit - the expected P&L, its carry and the rest, the target's and the stop's; ``try_per`` its TRY."""
    pu = {"total": exp, "carry": carry_h, "move": exp - carry_h if exp is not None and carry_h is not None else None,
          "target": reward, "stop": -risk if risk is not None else None}
    fx = cfg.get("usdtry")
    out: Dict[str, Any] = {"ccy": ccy, "per_unit": per, "unit": unit, "pu": pu,
                           "try_per": 1.0 if ccy in ("TRY", "TL") else (float(fx) if ccy == "USD" and fx else None)}
    out.update({k: v * per if v is not None else None for k, v in pu.items()})
    return out


#: what a leg's action is in plain words, by the kind of instrument: a swap's fixed rate, a forward's points, the rest
_LEG_WORDS = {("swap", "Receive"): "sabit faiz alınan (receive)", ("swap", "Pay"): "sabit faiz ödenen (pay)",
              ("points", "Receive"): "swap puanı alınan (receive)", ("points", "Pay"): "swap puanı ödenen (pay)",
              ("", "Buy"): "alınan", ("", "Sell"): "satılan", ("", "Buy protection"): "koruma alınan", ("", "Sell protection"): "koruma satılan"}


def _leg_kind(key: str) -> str:
    if key.startswith(("OIS:", "OFF:", "USD:", "MPC:", "FOMC:")) or key == "TLREF":
        return "swap"
    return "points" if key.startswith("FXP:") else ""


def what_text(legs: List[Dict[str, Any]]) -> str:
    """The legs of a trade in plain words, grouped by what is done: "sabit faiz alınan (receive): 2Y OIS · sabit faiz
    ödenen (pay): 1Y OIS ×0,45, 5Y OIS ×0,30" - and the floating leg of a TRY / USD OIS."""
    groups: Dict[str, List[str]] = {}
    for leg in legs:
        word = _LEG_WORDS.get((_leg_kind(leg.get("key") or ""), leg.get("action")), _LEG_WORDS.get(("", leg.get("action")), leg.get("action") or ""))
        w = leg.get("weight", 1.0)
        groups.setdefault(word, []).append(leg.get("name", "") + ("" if abs(abs(w) - 1.0) < 1e-9 else " ×" + fmt_w(w)))
    text = " · ".join("%s: %s" % (word, ", ".join(names)) for word, names in groups.items())
    keys = [leg.get("key") or "" for leg in legs]
    floats = [name for name, pre in (("TLREF", ("OIS:", "MPC:")), ("SOFR", ("USD:", "FOMC:"))) if any(k.startswith(pre) for k in keys)]
    return text + (" (değişken bacak %s)" % " / ".join(floats) if floats else "")


def hold_of(m: Monitor) -> Optional[float]:
    """A signal's expected holding: its family's own, else - a mean reversion - the time its expected |z| takes to fall
    to 0.5 (half-lives × log₂(|z| ÷ 0.5), at least one)."""
    if m.hold is not None:
        return m.hold
    if m.half_life and m.z:
        return m.half_life * max(1.0, math.log(abs(m.z) / 0.5, 2))
    return None


def make_signal(m: Monitor, cfg: Dict[str, Any], stamp: str) -> Optional[Dict[str, Any]]:
    """A monitor past its entry threshold as a signal of the common format (``None`` below it), with its decision:
    every gate it passed or failed, the expected profit over the holding with carry + roll in it (bp, % or vol points,
    and TRY where it can be told), risk / reward, the thesis in one sentence.  A signal a gate keeps out is "elendi"."""
    if m.z is None or m.level is None:
        return None
    thr = float(m.entry or cfg["entry_z"])
    if abs(m.z) < thr:
        return None
    zs = sign(m.z)
    s = zs if m.follows else -zs                         # +1: the trade profits when the monitored level rises
    pkg_s = m.legs_sign if m.legs_sign is not None else s
    target_z, stop_z = float(cfg["target_z"]), float(cfg["stop_z"])
    gated = ""
    gates = [_gate("Eşik", True, "|%s| %s ≥ %s" % (m.score_name, _g(abs(m.z), 2), _g(thr, 2)))]
    if m.mode == "mr" and m.mean is not None and m.sd:
        target = m.inv(m.mean + zs * target_z * m.sd)
        stop = m.inv(m.mean + zs * stop_z * m.sd)
        scale = m.sd
        if abs(m.z) >= stop_z:
            gated = "stop bölgesinde (|z| ≥ %s)" % ("%g" % stop_z).replace(".", ",")
        gates.append(_gate("Stop bölgesi", not gated, gated or "|z| %s < stop %s" % (_g(abs(m.z), 2), _g(stop_z, 1))))
    else:
        target = m.level + s * (m.reward or 0.0)
        stop = m.level - s * (m.risk or 0.0)
        scale = m.risk or None
    legs = [signal_leg(leg, pkg_s) for leg in m.legs]
    if m.explicit and len(legs) > 1:
        expression = " · ".join("%s %s" % (l["action"], l["name"]) for l in legs)      # a hedged package: every leg told
    elif m.pkg in PKG_VERBS:
        up, down = PKG_VERBS[m.pkg]
        expression = "%s %s" % (up if pkg_s > 0 else down, m.name)
    elif m.pkg == "corr":
        expression = "Korelasyon normale döner: %s · %s" % (m.name, " / ".join(l["text"] for l in legs))
    else:
        expression = " / ".join(l["text"] for l in legs)
    tag = (m.regime or {}).get("tag")
    rf, why_r = regime_factor(m.kind, tag)
    if m.kind in ("mr", "surprise", "trend"):
        gates.append(_gate("Rejim", rf > 0, why_r or "%s%s" % (REGIME_TEXT.get(tag), " · yarım ağırlık" if rf == 0.5 else ""), rf))
    hf, why_h = hl_factor(m.kind, m.half_life, cfg, m.horizon, m.horizon_unit)
    if m.kind in ("mr", "corr"):
        gates.append(_gate("Yarı ömür", hf > 0, why_h or ("%s %s%s" % (_g(m.half_life, 1), m.horizon_unit,
                                                                       "" if hf >= 1.0 else " · ağırlık %s" % _g(hf, 2))), hf))
    if m.gate is not None:
        g, why_g = m.gate(pkg_s)
        gates.append(_gate(m.gate_name, g > 0.0, why_g or "geçti"))
        if g == 0.0:
            rf, why_r = 0.0, why_g
    why_x = ""
    if m.sample is not None:
        gates.append(_gate("Örneklem", bool(m.sample.get("ok")), m.sample.get("text") or ""))
        if not m.sample.get("ok"):
            why_x = m.sample.get("text") or "örneklem yetersiz"
    if m.min_abs is not None and not why_x:
        ok = abs(m.level) >= m.min_abs
        gates.append(_gate("Tolerans", ok, "|%s| %s %s %s %s" % ("fark", _g(abs(m.level), 1), "≥" if ok else "<", _g(m.min_abs, 1), m.unit)))
        if not ok:
            why_x = "fark %s %s: çözücünün toleransı içinde (en az %s)" % (_g(abs(m.level), 1), m.unit, _g(m.min_abs, 1))
    hold = hold_of(m)
    # ---- what it is expected to earn over the holding, carry + roll in it
    unit, factor = m.pnl or (None, None)
    move = None
    try:
        if callable(m.fcast):
            move = m.fcast(m.level, m.z)
        elif m.fcast is not None:
            move = float(m.fcast)
        elif m.mode == "mr" and m.mean is not None and m.half_life and hold:
            move = (m.inv(m.mean) - m.level) * (1.0 - 0.5 ** (hold / m.half_life))   # OU: the share of the gap closed in the hold
    except Exception:  # noqa: BLE001 - no forecast is no expected profit, not a failed signal
        move = None
    fx = m.fxinfo if m.fx else {}
    carry_yr = carry_week = carry_h = None
    if m.fx:
        if fx.get("carry_yr") is not None:
            carry_yr = pkg_s * fx["carry_yr"]
            carry_week = carry_yr * 7.0 / 365.0
        if fx.get("carry_h_yr") is not None:
            carry_h = pkg_s * fx["carry_h_yr"] * fx["cal_days"] / 365.0
    elif m.carry_up is not None:
        carry_week = pkg_s * m.carry_up
        carry_h = carry_week * (hold or 0.0) / 5.0
    exp = None
    if m.expect is not None:
        try:
            exp = m.expect(pkg_s, hold or 0.0)
        except Exception:  # noqa: BLE001
            exp = None
    elif move is not None and factor:
        exp = s * move * factor
        if not m.fx and carry_h is not None:
            exp += carry_h                                   # (an FX trade's level is its excess return: carry is in it)
    daily = m.pnl_sd if m.pnl_sd is not None else (m.dsd * factor if m.dsd and factor else None)
    sig_h = daily * math.sqrt(hold) if daily and hold else None
    margin = float(cfg.get("carry_margin", 0.5)) * sig_h if sig_h else 0.0
    reward = abs(target - m.level) * factor if factor and target is not None else None
    risk = abs(stop - m.level) * factor if factor and stop is not None else None
    # ---- the same in money: an FX trade in the prices of what is traded and per 1 mn of its base currency, a rates
    # package in TL of its main leg's DV01 (as sized, else the setting at the fit's USDTRY)
    px = money = None
    pnl_try = None
    if m.fx:
        px, money = fx_trade(m, pkg_s, target, stop, exp, carry_h, fx)
        if money is not None and money["total"] is not None and money.get("try_per"):
            pnl_try = money["total"] * money["try_per"]
    elif unit == "bp":
        main = legs[0] if legs else {}
        tl = main["dv01"] / main["weight"] if main.get("dv01") and main.get("weight") else None
        if tl is None and cfg.get("dv01_usd") and cfg.get("usdtry"):
            tl = float(cfg["dv01_usd"]) * float(cfg["usdtry"])
        money = rate_money(legs, cfg, tl, exp, carry_h, reward, risk)
        pnl_try = exp * tl if exp is not None and tl else None
    elif m.cash is not None and m.cash[1]:
        money = cash_money(m.cash[0], float(m.cash[1]), unit, exp, carry_h, reward, risk, cfg)
        pnl_try = money["total"] * money["try_per"] if money["total"] is not None and money.get("try_per") else None

    def amount(v: Optional[float], signed: bool = True, cash: Optional[float] = None) -> str:
        """A P&L of the holding (P&L units) as the gates say it: FX in money per 1 mn of the base (``cash`` when it is
        known already), bp with its TL, a line of linear money (vol, points) with its money."""
        if v is None:
            return "—"
        if money is not None and px is not None:
            c = cash if cash is not None else pct_money(v, pkg_s, money["ref"], money["log"])
            return "%s / 1 mn %s" % (_money(c, money["ccy"], signed), money["base"])
        if money is not None and money.get("per_unit"):
            return "%s %s ≈ %s" % (_sg(v, 2) if signed else _g(v, 2), unit or "", _money(v * money["per_unit"], money["ccy"], signed))
        txt = ("%s %s" % (_sg(v, 2) if signed else _g(v, 2), unit or "")).strip()
        return txt + (" ≈ %s" % _money(v * money["per_bp"], "TL", signed) if money is not None and money.get("per_bp") else "")

    cf = 1.0
    if m.fx:
        prem = money.get("carry") if money is not None else None           # the forward premium of the holding, in money
        if carry_h is None:
            gates.append(_gate("Carry", False, "forward yok: carry bilinmiyor"))
            why_x = why_x or "forward yok: carry bilinmiyor"
        elif carry_h < 0:
            ok = exp is not None and exp >= margin
            text = ("forward primi aleyhte (ufukta %s) · beklenen %s ≥ tampon %s" % (amount(carry_h, cash=prem), amount(exp), amount(margin, False)) if ok
                    else "carry'yi karşılamıyor: beklenen %s < tampon %s (forward primi ufukta %s)" % (amount(exp), amount(margin, False),
                                                                                                       amount(carry_h, cash=prem)))
            gates.append(_gate("Carry", ok, text))
            if not ok:
                why_x = why_x or "carry'yi karşılamıyor (beklenen %s, forward primi ufukta %s)" % (amount(exp), amount(carry_h, cash=prem))
        else:
            gates.append(_gate("Carry", True, "forward primi lehte: ufukta %s" % amount(carry_h, cash=prem)))
    elif carry_week is not None:
        cf = 0.5 if carry_week < 0 else 1.0
        gates.append(_gate("Carry", True, "carry + roll %s %s / hafta%s" % (_sg(carry_week, 2), unit or "bp", " · aleyhte: ağırlık 0,5" if cf < 1 else ""), cf))
    if exp is not None and not why_x and not (m.fx and carry_h is not None and carry_h < 0):
        ok = exp > 0
        inside = "forward primi dahil" if m.fx else ("carry + roll dahil" if carry_h is not None else "")
        gates.append(_gate("Beklenen kâr", ok, "ufukta %s%s" % (amount(exp), " (%s)" % inside if inside else "")))
        if not ok:
            why_x = "beklenen kâr yok (%s%s)" % (amount(exp), ", " + inside if inside else "")
    # |z| on the desk's scale (a family with its own threshold is brought to it), counted at most up to the stop: no
    # family's score can outrank the others by its scale alone
    base = min(abs(m.z) * float(cfg["entry_z"]) / thr, stop_z)
    composite = base * rf * hf * cf
    gated = gated or why_r or why_h or why_x
    # the packages that trade it: the main one, then the others (each leg told, sized; its own carry + roll and the
    # same expected move with it)
    packages = []
    if m.pkg_name or m.packages:
        packages.append({"name": m.pkg_name or "Paket", "legs": legs, "carry_week": carry_week, "exp_pnl": exp, "note": "",
                         "trade": " · ".join("%s %s" % (l["action"], l["name"]) for l in legs)})
        for p in m.packages:
            pl = [signal_leg(leg, pkg_s) for leg in p["legs"]]
            cw = pkg_s * p["carry_up"] if p.get("carry_up") is not None else None
            e2 = s * move * factor + cw * (hold or 0.0) / 5.0 if move is not None and factor and cw is not None else None
            packages.append({"name": p["name"], "legs": pl, "carry_week": cw, "exp_pnl": e2, "note": p.get("note") or "",
                             "trade": " · ".join("%s %s" % (l["action"], l["name"]) for l in pl)})
    sg = {"id": m.sid, "family": m.family, "family_label": FAMILIES[m.family][0], "page": FAMILIES[m.family][2], "kind": m.kind,
          "asset": m.asset, "instrument": m.name, "expression": expression, "legs": legs, "direction": s, "z": m.z,
          "score_name": m.score_name, "entry_z": thr, "strength": "elendi" if gated else strength(abs(m.z) / thr), "level": m.level,
          "unit": m.unit, "digits": m.digits, "entry": m.level, "target": target, "stop": stop, "scale": scale, "target_z": target_z,
          "stop_z": stop_z, "mode": m.mode, "half_life": m.half_life, "hold": hold, "carry_week": carry_week, "carry_yr": carry_yr,
          "carry_h": carry_h, "exp_pnl": exp, "pnl_unit": unit, "pnl_try": pnl_try, "sigma_h": sig_h, "reward": reward, "risk": risk,
          "rr": reward / risk if reward is not None and risk else None, "exp_r": exp / risk if exp is not None and risk else None,
          "gates": gates, "fx": dict(fx) if fx else None, "intraday": m.intraday, "horizon_unit": m.horizon_unit,
          "regime": REGIME_TEXT.get(tag), "regime_info": m.regime, "composite": 0.0 if gated else composite,
          "parts": {"z": base, "regime": rf, "hl": hf, "carry": cf}, "gated": gated, "live": m.live, "time": stamp,
          "note": m.note, "info": {k: v for k, v in m.info.items() if k not in ("ou", "inputs")}, "agree": 0, "conflict": 0,
          "agree_with": [], "conflict_with": [], "packages": packages, "px": px, "money": money}
    try:
        sg["trade_tr"] = trade_text(sg)
        sg["plain"] = plain_text(sg)
    except Exception:  # noqa: BLE001 - the words are told from the numbers; words that cannot be are left out, not the signal
        sg.setdefault("trade_tr", sg["expression"])
        sg["plain"] = ""
    try:
        sg["thesis"] = m.thesis(sg) if m.thesis is not None else default_thesis(m, sg)
    except Exception:  # noqa: BLE001 - a sentence that cannot be written is no reason to lose the signal
        sg["thesis"] = default_thesis(m, sg)
    return sg


def exp_text(sg: Dict[str, Any], d: int = 2) -> str:
    """The expected P&L as the desk reads it: FX in money per 1 mn of the base currency, a rates package in bp with
    its TL, anything else in its own unit."""
    e, mo = sg.get("exp_pnl"), sg.get("money") or {}
    if e is None:
        return "—"
    if sg.get("px") and mo.get("total") is not None:
        return "~%s / 1 mn %s" % (_money(mo["total"], mo["ccy"]), mo["base"])
    if mo.get("per_unit") and mo.get("total") is not None:
        return "%s %s ≈ %s" % (_sg(e, d), sg.get("pnl_unit") or "", _money(mo["total"], mo["ccy"]))
    txt = ("%s %s" % (_sg(e, d), sg.get("pnl_unit") or "")).strip()
    return txt + (" ≈ %s" % _money(mo["total"], "TL") if mo.get("per_bp") and mo.get("total") is not None else "")


def _incl(sg: Dict[str, Any]) -> str:
    """What the expected P&L has in it beside the move: the forward premium (FX), the carry + roll (a rates package)."""
    if sg.get("carry_h") is None:
        return ""
    return " (forward primi dahil)" if sg.get("fx") else " (carry + roll dahil)"


def default_thesis(m: Monitor, sg: Dict[str, Any]) -> str:
    """One sentence: what is out of line, by how much, and the trade - with what it is expected to earn."""
    where = "ortalamasının %s" % ("üstünde" if (m.z or 0) > 0 else "altında") if m.mode == "mr" else "eşiğin ötesinde"
    tail = "; beklenen %s%s" % (exp_text(sg), _incl(sg)) if sg.get("exp_pnl") is not None else ""
    return "%s %s (%s %s) → %s%s." % (m.name, where, m.score_name, _sg(m.z, 2), sg["expression"], tail)


def trade_text(sg: Dict[str, Any]) -> str:
    """The trade in desk words: an FX trade as the instrument and the side ("USDTRY 1A forward sat"), any other as what
    is received / paid, bought / sold ("sabit faiz alınan (receive): 2Y OIS · sabit faiz ödenen (pay): 1Y OIS ×0,45")."""
    px = sg.get("px")
    legs = sg.get("legs") or []
    if px is not None:
        first = "%s %s" % (px["inst"], "al" if sg["direction"] > 0 else "sat")
        return " · ".join([first] + ["%s %s" % (l["name"], "al" if l["side"] > 0 else "sat") for l in legs[1:]])
    if sg.get("kind") == "corr" or not legs:
        return sg.get("expression") or ""
    return what_text(legs)


def _level_text(v: Optional[float], unit: str, digits: int) -> str:
    """A level as the desk writes it: a rate "%38,50", a spread "+3,0 bp", anything else with its unit."""
    if v is None:
        return "—"
    if unit == "%":
        return "%" + _th(v, min(digits, 2))
    if unit == "bp":
        return "%s bp" % _sg(v, 1)
    return ("%s %s" % (_th(v, digits), unit)).strip()


def sheet_text(sg: Dict[str, Any], v: Optional[float], inner: bool = False) -> str:
    """A level's quote on the desk's own sheet, beside it - when the signal carries one (``info["sheet"]``: the
    universe's flies, the OIS sheet's 2·body − wings): " (OIS sayfasında -25,0)", or "; OIS sayfasında -25,0" inside
    a parenthesis."""
    sh = (sg.get("info") or {}).get("sheet") or {}
    if v is None or not sh.get("factor"):
        return ""
    t = "%s %s" % (sh.get("where") or "OIS sayfasında", _sg(v * float(sh["factor"]), 1))
    return "; " + t if inner else " (%s)" % t


def plain_text(sg: Dict[str, Any]) -> str:
    """The signal in plain words, from its own numbers: what to do on which instrument and at what price, what it is
    expected to make over the holding (FX: per 1 mn of the base currency, the forward premium's part and the spot's;
    a rates package: bp and TL of its main leg's DV01, the carry + roll's part) and what the target and the stop make."""
    px, mo = sg.get("px"), sg.get("money") or {}
    s = sg["direction"]
    hold = sg.get("hold")
    span = "~%s %s" % (_g(hold, 0), "bar (5 dk)" if sg.get("horizon_unit") == "bar" else "iş günü") if hold else "ufuk boyunca"
    if px is not None:
        d = px["digits"]
        ccy, base = mo["ccy"], mo["base"]
        p = lambda v: _th(v, d) if v is not None else "—"                       # noqa: E731
        verb = "alıp" if s > 0 else "satıp"
        if px["tenor"] is None:
            head = "Şimdi spot %s %s %s tutarsan (giriş %s)" % (px["pair"], verb, span, p(px["entry"]))
        else:
            head = "Bugün %s %s forward'ını %s %s tutarsan (giriş %s)" % (_tenor_long(px["tenor"]), px["pair"], verb, span, p(px["entry"]))
        if mo.get("total") is None:
            out = head + "."
        else:
            out = "%s ve kur o sürede beklenen seviyeye gelirse (%s), 1 mn %s başına ~%s %s" % (
                head, p(px["spot_exp"]), base, _money(abs(mo["total"]), ccy, False), "kazanırsın" if mo["total"] >= 0 else "kaybedersin")
            if px["tenor"] is not None and mo.get("carry") is not None:
                out += ": forward priminden (carry) %s, kur hareketinden %s (spot %s → %s)" % (
                    _money(mo["carry"], ccy), _money(mo["move"], ccy), p(px["spot"]), p(px["spot_exp"]))
            out += "."
        ends = []
        for word, key in (("hedefte", "target"), ("stopta", "stop")):
            if px.get(key) is not None and mo.get(key) is not None:
                ends.append("%s (%s) ~%s %s" % (word, p(px[key]), _money(abs(mo[key]), ccy, False), "kâr" if mo[key] >= 0 else "zarar"))
        if ends:
            tail = ", ".join(ends)
            out += " " + tail[0].upper() + tail[1:] + "."
        others = (sg.get("legs") or [])[1:]                     # (EM carry: the basket against it - not in the money above)
        if others:
            out += " Karşı bacak: %s (yukarıdaki K/Z'ye dahil değil)." % ", ".join(
                "%s %s" % (l["name"], "al" if l["side"] > 0 else "sat") for l in others)
        return out
    # (a level with its quote on the desk's own sheet beside it, when the signal has one: a universe fly's)
    lv = lambda v, inner=False: _level_text(v, sg.get("unit") or "", sg.get("digits") or 2) + sheet_text(sg, v, inner)  # noqa: E731
    what = sg.get("trade_tr") or sg.get("expression") or ""
    out = "%s. %s şimdi %s" % (what[:1].upper() + what[1:], sg.get("instrument") or "", lv(sg.get("level")))
    if mo.get("per_bp"):
        bp = mo["bp"]
        parts = []
        if bp.get("target") is not None:
            parts.append("hedef seviyesine (%s) gelirse %s bp ≈ %s kazanırsın" % (lv(sg.get("target"), True), _g(bp["target"], 1), _money(abs(mo["target"]), "TL", False)))
        if bp.get("stop") is not None:
            parts.append("stop seviyesine (%s) gelirse %s bp ≈ %s kaybedersin" % (lv(sg.get("stop"), True), _g(abs(bp["stop"]), 1), _money(abs(mo["stop"]), "TL", False)))
        out += ("; " + ", ".join(parts) if parts else "") + "."
        if bp.get("total") is not None:
            out += " Beklenen: %s içinde %s bp ≈ %s" % (span, _sg(bp["total"], 1), _money(mo["total"], "TL"))
            out += (" (%s bp'si carry + roll)." % _sg(bp["carry"], 1)) if bp.get("carry") is not None else "."
        if mo.get("dv01_usd"):
            out += " Ana bacak %s $ DV01 = %s TL / bp." % (_th(mo["dv01_usd"], 0), _th(mo["per_bp"], 0))
        return out
    out += "; hedef %s, stop %s." % (lv(sg.get("target")), lv(sg.get("stop")))
    unit = {"vol": "vol puanı"}.get(sg.get("pnl_unit") or "", sg.get("pnl_unit") or "")
    if mo.get("per_unit"):
        # (a line of linear money - an option's vega, a swap's points: its P&L units and their money, for its size)
        size = (sg.get("info") or {}).get("size")
        if sg.get("exp_pnl") is not None and mo.get("total") is not None:
            out += " Beklenen: %s içinde %s %s ≈ %s%s." % (span, _sg(sg["exp_pnl"], 2), unit, _money(mo["total"], mo["ccy"]),
                                                           " (%s)" % size if size else "")
        ends = ["%s ~%s %s" % (word, _money(abs(mo[key]), mo["ccy"], False), "kâr" if mo[key] >= 0 else "zarar")
                for word, key in (("hedefte", "target"), ("stopta", "stop")) if mo.get(key) is not None]
        if ends:
            tail = ", ".join(ends)
            out += " " + tail[0].upper() + tail[1:] + "."
        return out
    if sg.get("exp_pnl") is not None:
        out += " Beklenen: %s içinde %s %s." % (span, _sg(sg["exp_pnl"], 2), unit)
    return out


def rank(signals: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Agreement counts (how many other families take the same side of a shared leg, how many the other side), then
    the live signals ranked by the composite (ties: more agreement first) and the ones a gate kept out."""
    by_key: Dict[str, List[Tuple[int, int]]] = {}
    for i, sg in enumerate(signals):
        for leg in sg["legs"]:
            by_key.setdefault(leg["key"], []).append((i, leg["side"]))
    for i, sg in enumerate(signals):
        agree, conflict = set(), set()
        for leg in sg["legs"]:
            for j, side in by_key.get(leg["key"], ()):
                other = signals[j]
                if j == i or other["family"] == sg["family"] or other["gated"]:
                    continue
                (agree if side == leg["side"] else conflict).add(other["family"])
        sg["agree"], sg["conflict"] = len(agree), len(conflict)
        sg["agree_with"] = sorted(FAMILIES[f][0] for f in agree)
        sg["conflict_with"] = sorted(FAMILIES[f][0] for f in conflict)
    live = sorted((s for s in signals if not s["gated"]), key=lambda s: (-s["composite"], -s["agree"], -abs(s["z"])))
    gated = sorted((s for s in signals if s["gated"]), key=lambda s: -abs(s["z"]))
    return live, gated


# ================================================================================================ the families
def _ois_name(ctx: Ctx, key: str) -> str:
    return "%s OIS" % key.split(":", 1)[1]


def _curve_matrix(ctx: Ctx, keys: List[str], last: int) -> Tuple[List[str], List[str], List[List[float]]]:
    """Tenors with a close on most days (at least 80 % of the best covered), and the days all of them closed."""
    if not keys:
        return [], [], []
    most = max(len(ctx.series[k]) for k in keys)
    keep = [k for k in keys if len(ctx.series[k]) >= 0.8 * most]
    days, vals = aligned(ctx, keep, last)
    return keep, days, [[vals[j][i] for j in range(len(keep))] for i in range(len(days))]


# ---------------------------------------------------------------------------------------------- 1. correlation
CORR_UNIVERSE = ("OIS:3M", "OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y", "OFF:3M", "OFF:1Y", "VIOPI:FRONT", "FX:USDTRY", "FXP:USDTRY:3M",
                 "CDS", "UST:2Y", "UST:10Y", "DXY", "EMFX", "BRENT")


def fam_corr(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    cfg = ctx.cfg
    windows = [int(w) for w in cfg["corr_windows"]]
    short, long_w = min(windows), max(windows)
    win = ctx.window()
    keys = [k for k in CORR_UNIVERSE if ctx.has(k, short + 2)]
    n = len(keys)
    mats = {str(w): [[None] * n for _ in range(n)] for w in windows}
    zmat = [[None] * n for _ in range(n)]
    nmat = [[0] * n for _ in range(n)]
    pairs = []
    mons: List[Monitor] = []
    for i in range(n):
        for w in windows:
            mats[str(w)][i][i] = 1.0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = keys[i], keys[j]
            days, (va, vb) = aligned(ctx, [a, b], win + short + 1)
            ka, kb = ctx.kind(a), ctx.kind(b)
            da, db = diffs(ka, va), diffs(kb, vb)
            m = len(da)
            nmat[i][j] = nmat[j][i] = m
            if m < short:
                continue
            for w in windows:
                if m >= w:
                    c = qm.corr(da[-w:], db[-w:])
                    mats[str(w)][i][j] = mats[str(w)][j][i] = c
            roll = qm.rolling_corr(da, db, short)
            fz = [qm.fisher(r) for r in roll if r is not None]
            hist = fz[:-short] if len(fz) > 2 * short else []
            long_c = qm.corr(da[-win:], db[-win:])
            row = {"a": a, "b": b, "a_label": ctx.label(a), "b_label": ctx.label(b), "n": m, "long": long_c,
                   "c": {str(w): mats[str(w)][i][j] for w in windows}, "z": None, "half_life": None, "signal": False}
            if len(hist) >= max(20, ctx.min_obs() - short) and m >= ctx.min_obs():
                mean, sd = window_stats(hist)
                if sd:
                    zf = (fz[-1] - mean) / sd
                    zmat[i][j] = zmat[j][i] = zf
                    row["z"] = zf
                    ou = ou_of(fz[-win:])
                    row["half_life"] = ou["half_life"] if ou else None
                    var_b = qm.var(db[-win:])
                    beta = (qm.cov(da[-win:], db[-win:]) or 0.0) / var_b if var_b else 0.0
                    drift = sum(x - beta * y for x, y in zip(da[-short:], db[-short:]))
                    row.update({"beta": beta, "drift": drift})
                    if long_c is not None and abs(long_c) >= float(cfg["corr_min"]):
                        roll_days = days[1:]
                        rd = [roll_days[t] for t, r in enumerate(roll) if r is not None]
                        rv = [r for r in roll if r is not None]
                        last_a, last_b = va[-1], vb[-1]
                        tail_a, tail_b = da[-(short - 1):], db[-(short - 1):]

                        def calc(live, a=a, b=b, ka=ka, kb=kb, last_a=last_a, last_b=last_b, tail_a=tail_a, tail_b=tail_b, rv=rv):
                            xa, xb = live.get(a), live.get(b)
                            if xa is None or xb is None:
                                return rv[-1]
                            ca, cb = change(ka, last_a, xa), change(kb, last_b, xb)
                            if ca is None or cb is None:
                                return rv[-1]
                            return qm.corr(tail_a + [ca], tail_b + [cb])

                        name = "%s ↔ %s" % (ctx.label(a), ctx.label(b))
                        mon = Monitor("corr:%s|%s" % (a, b), "corr", _asset_of(a), name, "ρ", 2, rd[-win:], rv[-win:],
                                      [{"key": a, "name": ctx.label(a), "weight": 1.0}, {"key": b, "name": ctx.label(b), "weight": -beta}],
                                      calc, mean=mean, sd=sd, transform="fisher", half_life=row["half_life"], pkg="corr",
                                      legs_sign=-sign(drift) if drift else 1,
                                      regime={"tag": None}, info={"long": long_c, "beta": beta, "drift": drift, "short": short},
                                      note="%d günlük korelasyon %s; uzun dönem (%d gün) %s. Son %d günde %s, %s'ye göre beklenenden %s %s ayrıştı."
                                      % (short, _f2(rv[-1]), min(win, m), _f2(long_c), short, ctx.label(a), ctx.label(b), _f2(abs(drift)),
                                         change_unit(ka)))
                        mons.append(mon)
                        row["signal"] = True
            pairs.append(row)
    pairs.sort(key=lambda r: -abs(r["z"]) if r["z"] is not None else 0.0)
    table = {"keys": keys, "labels": [ctx.label(k) for k in keys], "windows": windows, "matrices": mats, "z": zmat, "n": nmat,
             "pairs": pairs, "short": short, "long": long_w, "min": float(cfg["corr_min"])}
    return mons, table


def _f2(v: Optional[float]) -> str:
    return ("%.2f" % v).replace(".", ",") if v is not None else "—"


def _asset_of(key: str) -> str:
    if key.startswith("OIS:") or key == "TLREF":
        return "TRY OIS"
    if key.startswith("OFF:"):
        return "Offshore"
    if key.startswith("VIOP"):
        return "VİOP"
    if key.startswith("DIBS:"):
        return "DİBS"
    if key.startswith(("FXV:", "FXR:")):
        return "FX vol"
    if key.startswith(("FX:", "FXP:", "FWD:")):
        return "FX"
    return "Global"


# ---------------------------------------------------------------------------------------------- 2. PCA, 3. PCA-neutral packages
def _pca_signs(vectors: List[List[float]], months: List[float]) -> List[List[float]]:
    """PC1 positive on average (level up), PC2 long end above the short end (steepening), PC3 belly up."""
    out = []
    for k, v in enumerate(vectors[:3]):
        if k == 0:
            s = sum(v)
        elif k == 1:
            s = v[-1] - v[0]
        else:
            mid = len(v) // 2
            s = v[mid] - 0.5 * (v[0] + v[-1])
        out.append([-x for x in v] if s < 0 else list(v))
    return out


#: the windows the curve's PCA is fitted on (business days): their loadings side by side say how stable the factors are;
#: the signals use the longest one the history covers (they say which)
PCA_WINDOWS = (60, 120, 250)


def _pca_window(ctx: Ctx, keys: List[str], w: int) -> Optional[Dict[str, Any]]:
    """One window's fits: the PCA of the daily changes (the risk factors: today's move, the hedges of the flies) and the
    PCA of the levels (the directions the curve itself moved in over the window: a cycle's trend among them)."""
    keep, days, rows = _curve_matrix(ctx, keys, w + 1)
    if len(keep) < 3 or len(days) < w + 1:
        return None
    k = len(keep)
    chg = [[(rows[t][j] - rows[t - 1][j]) * 100.0 for j in range(k)] for t in range(1, len(rows))]
    p = qm.pca(chg)
    pl = qm.pca([[v * 100.0 for v in r] for r in rows])
    if p is None or pl is None:
        return None
    months = [ctx.months(x) for x in keep]
    xbar = [sum(r[j] for r in rows) / len(rows) for j in range(k)]
    return {"keys": keep, "days": days, "rows": rows, "changes": chg, "values": p["values"][:3], "vectors": _pca_signs(p["vectors"], months),
            "explained": p["explained"][:3], "mean_change": p["means"], "xbar": xbar, "months": months, "window": w,
            "lvl_vectors": _pca_signs(pl["vectors"], months), "lvl_explained": pl["explained"][:3]}


def pca_stability(fits: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """How much the loadings of PC1–PC3 (of the daily changes) moved between the windows: per component and pair of
    windows the |cosine| of the two loading vectors (1: the same shape) and the largest move of a tenor's loading."""
    out = []
    for c in range(3):
        row: Dict[str, Any] = {"pc": c + 1, "pairs": []}
        for a, b in ((60, 120), (120, 250), (60, 250)):
            fa, fb = fits.get(a), fits.get(b)
            if fa is None or fb is None or len(fa["vectors"]) <= c or len(fb["vectors"]) <= c:
                continue
            common = [x for x in fa["keys"] if x in fb["keys"]]
            va = [fa["vectors"][c][fa["keys"].index(x)] for x in common]
            vb = [fb["vectors"][c][fb["keys"].index(x)] for x in common]
            na, nb = math.sqrt(sum(x * x for x in va)), math.sqrt(sum(x * x for x in vb))
            dot = sum(x * y for x, y in zip(va, vb))
            if dot < 0:
                vb = [-x for x in vb]
            row["pairs"].append({"a": a, "b": b, "cos": abs(dot) / (na * nb) if na and nb else None,
                                 "max_move": max((abs(x - y) for x, y in zip(va, vb)), default=None)})
        out.append(row)
    return out


def pca_fit(ctx: Ctx) -> Optional[Dict[str, Any]]:
    """The curve's PCA on every window of ``PCA_WINDOWS`` the history covers; the main fit - what the signals use - is the
    longest one with at least the desk's minimum of closes (or the longest at all)."""
    keys = ctx.ois_keys(min_months=1.0)
    fits = {w: f for w, f in ((w, _pca_window(ctx, keys, w)) for w in PCA_WINDOWS) if f is not None}
    if not fits:
        return None
    ok = [w for w in fits if w >= ctx.min_obs()]
    main = dict(fits[max(ok) if ok else max(fits)])
    main["windows"] = fits
    main["stability"] = pca_stability(fits)
    return main


def _pkg_series(fit: Dict[str, Any], weights: Dict[int, float]) -> List[float]:
    """A package's level in bp against the window's means, day by day."""
    xbar = fit["xbar"]
    return [sum(w * (r[j] - xbar[j]) for j, w in weights.items()) * 100.0 for r in fit["rows"]]


def _proj(vec: List[float], d: List[float]) -> float:
    return sum(a * b for a, b in zip(vec, d))


def fam_pca(ctx: Ctx, fit: Optional[Dict[str, Any]]) -> Tuple[List[Monitor], Dict[str, Any]]:
    """Rich / cheap tenors against the curve's own shape.  The residual is measured on the levels, against the level-PCA
    of the window (its first two components): a cycle moves the whole curve along the directions the levels moved in, so
    those are taken out and what is left - the tenor against a package of its two neighbours neutral to them - does not
    trend with the cycle (residuals against the change-PCA, or against a rolling mean, keep a trending cycle's part in
    them: the change factors are not the directions the levels drifted in, and a rolling mean lags the drift)."""
    if fit is None:
        return [], {"ok": False, "why": "PCA için en az 3 OIS vadesinde %d ortak gün gerekli" % (PCA_WINDOWS[0] + 1)}
    keys, rows, vec, xbar = fit["keys"], fit["rows"], fit["vectors"], fit["xbar"]
    lvec = fit["lvl_vectors"]
    k = len(keys)
    w_main = fit["window"]

    def dev(levels: List[float]) -> List[float]:
        return [(levels[j] - xbar[j]) * 100.0 for j in range(k)]

    levels_now = lambda live: [ctx.cur(key, live) for key in keys]                       # noqa: E731
    mons: List[Monitor] = []
    table_rows = []
    others = {w: f for w, f in fit["windows"].items() if w != w_main}
    for j, key in enumerate(keys):
        hedge = _hedges(keys, lvec, j)
        weights = {j: 1.0}
        for h_, w_ in hedge:
            weights[h_] = weights.get(h_, 0.0) + w_
        series = _pkg_series(fit, weights)

        def calc(live, weights=weights):
            lv = levels_now(live)
            if any(lv[i] is None for i in weights):
                return None
            return sum(w * (lv[i] - xbar[i]) for i, w in weights.items()) * 100.0

        # the same tenor's package in the other windows: its z there (does the shorter past say the same?)
        zs = {}
        for w, f in others.items():
            if key in f["keys"]:
                jj = f["keys"].index(key)
                ww = {jj: 1.0}
                for h_, w_ in _hedges(f["keys"], f["lvl_vectors"], jj):
                    ww[h_] = ww.get(h_, 0.0) + w_
                s_ = _pkg_series(f, ww)
                mu, sd = window_stats(s_)
                zs[w] = (s_[-1] - mu) / sd if sd else None
        legs = [{"key": key, "name": _ois_name(ctx, key), "weight": 1.0}] + [
            {"key": keys[h], "name": _ois_name(ctx, keys[h]), "weight": w} for h, w in hedge]
        carry = _pkg_carry(ctx, legs)

        def pthesis(sg, key=key, zs=zs):
            other = ", ".join("%d günde z %s" % (w, _sg(z, 1)) for w, z in sorted(zs.items()) if z is not None)
            return ("%s, iki komşusuyla eğrinin seviye-PCA'sının ilk iki bileşenine nötr pakette %s bp %s (%d günlük pencere, z %s%s); "
                    "yarı ömür %s gün → %s; beklenen %s%s." % (
                        _ois_name(ctx, key), _g(abs(sg["level"]), 1), "ucuz" if sg["level"] > 0 else "pahalı", w_main, _sg(sg["z"], 2),
                        "; " + other if other else "", _g(sg.get("half_life"), 1), sg["expression"], exp_text(sg, 1), _incl(sg)))

        # (the series is the hedged package itself: "hedge'li" is its name)
        mon = mr_monitor(ctx, "pca:" + key, "pca", "TRY OIS", "%s (PC1–PC2 hedge'li)" % _ois_name(ctx, key), "bp", 1, fit["days"], series,
                         "bp", legs, calc, carry_up=carry, pkg="rate", thesis=pthesis, info={"window": w_main, "z_windows": zs},
                         explicit=True, pkg_name="Paket · iki komşu vadeyle hedge'li (PC1 ve PC2'ye nötr, DV01 ağırlıklı)",
                         note="%d günlük pencere: seviyelerin PCA'sı (bileşenler, eğrinin pencerede gerçekten kaydığı yönler) ile tenor ve iki "
                              "komşusundan PC1 ve PC2'ye nötr paket; seviyesi pencerenin ortalamasına göre (bp): + ise tenor ucuz (yüksek faiz → "
                              "receive), − ise pahalı (pay). Döngünün trendi bileşenlerde kaldığı için kalıntı onunla trend yapmaz." % w_main)
        row = {"key": key, "label": key.split(":", 1)[1], "loadings": [v[j] for v in vec], "resid": series[-1] if series else None,
               "z_windows": zs, "window": w_main}
        if mon is not None:
            mons.append(mon)
            row.update({"sid": mon.sid, "z_hist": mon.zof(series[-1]), "half_life": mon.half_life, "regime": (mon.regime or {}).get("tag"),
                        "hedge": [{"key": keys[h], "weight": w} for h, w in hedge]})
        table_rows.append(row)
    # today's move in factor terms and where the factors stand (the change-PCA: the risk factors)
    last = rows[-1]
    sd_f = [math.sqrt(max(v, 1e-12)) for v in fit["values"]]
    levels_f = [[_proj(vec[f], dev(r)) for r in rows] for f in range(len(vec))]

    def factors(live: Dict[str, float]) -> Dict[str, Any]:
        lv = levels_now(live)
        out = {"scores": [None] * len(vec), "z": [None] * len(vec), "level_z": [None] * len(vec)}
        if any(v is None for v in lv):
            return out
        move = [(lv[j] - last[j]) * 100.0 - fit["mean_change"][j] for j in range(k)]
        d = dev(lv)
        for f in range(len(vec)):
            sc = _proj(vec[f], move)
            out["scores"][f] = sc
            out["z"][f] = sc / sd_f[f] if sd_f[f] else None
            out["level_z"][f] = qm.zscore(_proj(vec[f], d), levels_f[f])
        return out

    windows = []
    for w, f in sorted(fit["windows"].items()):
        windows.append({"window": w, "explained": f["explained"], "lvl_explained": f["lvl_explained"], "first": f["days"][0], "last": f["days"][-1],
                        "loadings": {x: [f["vectors"][c][f["keys"].index(x)] for c in range(min(3, len(f["vectors"])))] for x in f["keys"]}})
    table = {"ok": True, "keys": keys, "labels": [x.split(":", 1)[1] for x in keys], "explained": fit["explained"],
             "values": fit["values"], "vectors": vec, "rows": table_rows, "days": len(fit["days"]), "first": fit["days"][0],
             "last": fit["days"][-1], "factors": factors, "names": ["PC1 · seviye", "PC2 · eğim", "PC3 · eğrilik"], "window": w_main,
             "windows": windows, "stability": fit["stability"], "lvl_explained": fit["lvl_explained"]}
    return mons, table


def _hedges(keys: List[str], vec: List[List[float]], j: int) -> List[Tuple[int, float]]:
    """Two tenors and their DV01 weights that make a unit of tenor ``j`` neutral to PC1 and PC2: the nearest tenor
    on each side (the two nearest on one side at the ends of the curve)."""
    k = len(keys)
    left = [i for i in range(j - 1, -1, -1)]
    right = [i for i in range(j + 1, k)]
    if left and right:
        h1, h2 = left[0], right[0]
    elif right:
        h1, h2 = right[0], right[1] if len(right) > 1 else right[0]
    else:
        h1, h2 = left[1] if len(left) > 1 else left[0], left[0]
    e1, e2 = vec[0], vec[1]
    if h1 != h2:
        w = qm.solve([[e1[h1], e1[h2]], [e2[h1], e2[h2]]], [-e1[j], -e2[j]])
        if w is not None and all(abs(x) < 25 for x in w):
            return [(h1, w[0]), (h2, w[1])]
    h = h2 if h1 == h2 else (left[0] if left else right[0])
    return [(h, -e1[j] / e1[h])] if e1[h] else []


def _pkg_carry(ctx: Ctx, legs: List[Dict[str, Any]]) -> Optional[float]:
    total = 0.0
    for leg in legs:
        c = ctx.carry_week(leg["key"])
        if c is None:
            return None
        total += leg.get("weight", 1.0) * c
    return total


#: the workbook's TRY OIS (Motor!A325:K342, OIS_MAIN's DV01, the blotter): a single payment up to 3 months, quarterly
#: coupons beyond - the notional a DV01 needs follows it
OIS_SINGLE_MONTHS = 3
OIS_COUPON_MONTHS = 3


def _annuity(par: float, months: float) -> float:
    """Annuity (years) of a par OIS from its own rate, by the workbook's rule: one payment up to 3 months, quarterly
    coupons beyond (a flat curve at the par rate)."""
    r = par / 100.0
    if months <= OIS_SINGLE_MONTHS:
        t = months / 12.0
        return t / (1.0 + r * t)
    tau = OIS_COUPON_MONTHS / 12.0
    n = max(1, int(round(months / OIS_COUPON_MONTHS)))
    return sum(tau / (1.0 + r * tau) ** i for i in range(1, n + 1))


def _pkg_name(tenors: List[str], kind: str, version: str = "pca") -> str:
    head = "".join("%ss" % t[:-1] for t in tenors) if all(t.upper().endswith("Y") for t in tenors) else "/".join(t.upper() for t in tenors)
    if version == "klasik":
        return head + (" klasik 50/50 fly" if kind == "fly" else " 1:1 spread")
    return head + (" PCA ağırlıklı fly" if kind == "fly" else " PCA ağırlıklı spread")


def rv_weights(kind: str, js: List[int], vec: List[List[float]], version: str) -> Optional[Dict[int, float]]:
    """A spread's / fly's DV01 weights by tenor index: ``klasik`` the desk's convention - a spread 1:1 (long leg +1, short
    −1), a fly 50/50 (body 1, wings −0.5 each): neutral to a parallel move -; ``pca`` neutral to the risk factors - a
    spread to PC1 (long leg 1), a fly to PC1 and PC2 (body 1)."""
    if kind == "spread":
        s_, l_ = js
        if version == "klasik":
            return {l_: 1.0, s_: -1.0}
        return {l_: 1.0, s_: -vec[0][l_] / vec[0][s_]} if vec[0][s_] else None
    w1_, b_, w2_ = js
    if version == "klasik":
        return {b_: 1.0, w1_: -0.5, w2_: -0.5}
    sol = qm.solve([[vec[0][w1_], vec[0][w2_]], [vec[1][w1_], vec[1][w2_]]], [-vec[0][b_], -vec[1][b_]])
    return {b_: 1.0, w1_: sol[0], w2_: sol[1]} if sol is not None else None


def pkg_exposures(weights: Dict[int, float], vec: List[List[float]], values: List[float]) -> List[float]:
    """What is left of the risk factors in a package: its move (bp) for a 1σ move of PC1 / PC2 / PC3,
    Σ wᵢ · e_k[i] · √λ_k."""
    return [sum(w * vec[k][i] for i, w in weights.items()) * math.sqrt(max(values[k], 0.0)) for k in range(min(3, len(vec), len(values)))]


def rv_compare(kind: str, versions: Dict[str, Dict[str, Any]]) -> str:
    """One line on what the two versions leave: the classic one's hidden factor exposure, the PCA one's net DV01."""
    k, p = versions.get("klasik"), versions.get("pca")
    if not k or not p:
        return ""
    ek, ep = k["exposures"], p["exposures"]
    hidden = max(range(len(ek)), key=lambda i: abs(ek[i])) if ek else 0
    names = ("seviye", "eğim", "eğrilik")
    return ("klasik: paralel kaymaya nötr (net DV01 %s TL/bp), gizli %s maruziyeti %s bp/σ; PCA: %s nötr (%s), net DV01 %s TL/bp" % (
        _g(k["net_dv01"], 0), names[hidden], _sg(ek[hidden], 2), "seviyeye" if kind == "spread" else "seviye ve eğime",
        " · ".join("PC%d %s" % (i + 1, _sg(x, 2)) for i, x in enumerate(ep)), _g(p["net_dv01"], 0)))


def fam_rv(ctx: Ctx, fit: Optional[Dict[str, Any]], items: List[Dict[str, Any]]) -> Tuple[List[Monitor], Dict[str, Any]]:
    """The desk's spreads and flies in both conventions side by side: the classic one (1:1 / 50/50 in DV01, neutral to a
    parallel move) and the PCA-weighted one (neutral to PC1 / PC1 + PC2) - each with its series, z, half-life, regime,
    carry + roll, legs (DV01, nominal), net DV01 and what is left of the risk factors; both may signal."""
    if fit is None:
        return [], {"ok": False, "rows": []}
    keys, rows, vec, values = fit["keys"], fit["rows"], fit["vectors"], fit["values"]
    win_ = fit.get("window") or ctx.window()
    index = {key: j for j, key in enumerate(keys)}
    base = ctx.dv01_size()[1] or 0.0                     # the main leg's DV01, TRY a bp
    mons: List[Monitor] = []
    table = []
    for it in items:
        if it.get("product") != "OIS" or it.get("kind") not in ("spread", "fly"):
            continue
        tk = ["OIS:" + t.upper() for t in it["tenors"]]
        if any(t not in index for t in tk):
            table.append({"label": it["label"], "error": "vadesi PCA eğrisinde yok"})
            continue
        js = [index[t] for t in tk]
        row: Dict[str, Any] = {"label": _pkg_name(it["tenors"], it["kind"], "pca"), "item": it["label"], "kind": it["kind"], "tenors": it["tenors"],
                               "versions": {}}
        for version in ("klasik", "pca"):
            weights = rv_weights(it["kind"], js, vec, version)
            if weights is None:
                row["versions"][version] = {"error": "PC1/PC2 sistemi çözülemedi"}
                continue
            series = [sum(w * r[j] for j, w in weights.items()) * 100.0 for r in rows]
            legs = [{"key": keys[j], "name": _ois_name(ctx, keys[j]), "weight": w}
                    for j, w in sorted(weights.items(), key=lambda x: fit["months"][x[0]])]
            size_legs(ctx, legs)                         # DV01 (TRY / USD) and nominal of each leg
            expo = pkg_exposures(weights, vec, values)
            net = sum(weights.values()) * base

            def calc(live, weights=weights):
                lv = {j: ctx.cur(keys[j], live) for j in weights}
                if any(v is None for v in lv.values()):
                    return None
                return sum(w * lv[j] for j, w in weights.items()) * 100.0

            name = _pkg_name(it["tenors"], it["kind"], version)
            sid = "rv:%s:%s" % (it["kind"], "/".join(t.upper() for t in it["tenors"])) + (":klasik" if version == "klasik" else "")
            if version == "klasik":
                how = "Ağırlıklar masanın usulü: %s, DV01 cinsinden - paralel kaymaya nötr" % ("1:1" if it["kind"] == "spread" else "50/50 (gövde 1, kanatlar −0,5)")
            else:
                how = "Ağırlıklar %s, DV01 cinsinden" % ("PC1 ve PC2'ye nötr (gövde 1)" if it["kind"] == "fly" else "PC1'e nötr (uzun bacak 1)")
            ver = {"name": name, "sid": sid, "legs": legs, "net_dv01": net, "exposures": expo, "weights": {keys[j]: w for j, w in weights.items()}}
            mon = mr_monitor(ctx, sid, "rv", "TRY OIS", name, "bp", 1, fit["days"], series, "bp", legs, calc, carry_up=_pkg_carry(ctx, legs), pkg="rate",
                             info={"window": win_, "version": version, "net_dv01": net, "exposures": expo},
                             note="%s; %d günlük pencere. Net DV01 %s TL/bp; 1σ PC1 / PC2 / PC3 hareketinde paket %s bp. + ise paket seviyesi yüksek "
                                  "(receive ile ortalamaya dönüş)." % (how, win_, _g(net, 0), " / ".join(_sg(x, 2) for x in expo)))
            if mon is not None:
                mons.append(mon)
                ver.update({"level": series[-1], "z": mon.zof(series[-1]), "half_life": mon.half_life, "carry": mon.carry_up,
                            "regime": (mon.regime or {}).get("tag")})
            else:
                ver["error"] = "gün sayısı az"
            row["versions"][version] = ver
        row["compare"] = rv_compare(it["kind"], row["versions"])
        for v in row["versions"].values():
            m = next((x for x in mons if x.sid == v.get("sid")), None)
            if m is not None:
                m.info["compare"] = row["compare"]
        # (the PCA version's fields on the row itself, as before)
        p = row["versions"].get("pca") or {}
        row.update({k: p.get(k) for k in ("legs", "level", "z", "half_life", "carry", "regime", "sid", "error") if k in p})
        table.append(row)
    return mons, {"ok": True, "rows": table, "window": win_}


# ---------------------------------------------------------------------------------------------- 4. macro betas
MACRO_TARGETS = ("OIS:3M", "OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y", "XR:USDTRY")
MACRO_DRIVERS = ("UST:2Y", "UST:10Y", "DXY", "EMFX", "BRENT", "CDS")
MACRO_HOLD = 5                            # business days: the residual is expected back within a week


def _macro_name(ctx: Ctx, t: str) -> str:
    return "%s (forward pozisyonu)" % t[3:] if t.startswith("XR:") else _ois_name(ctx, t)


def xr_label(pair: str) -> str:
    """What an FX signal's drawn series is (``XR:``): the analysis' own, not the prices the trade is told in."""
    return "%s forward pozisyonunun birikimli getirisi (%%, kur değişimi − forward primi)" % pair


def fam_macro(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    drivers = [d for d in MACRO_DRIVERS if ctx.has(d, ctx.min_obs())]
    targets = [t for t in MACRO_TARGETS if ctx.has(t, ctx.min_obs())]
    rows = []
    mons: List[Monitor] = []
    if not drivers:
        return [], {"ok": False, "why": "küresel sürücülerin (UST, DXY, EM FX, Brent, CDS) geçmişi yok", "drivers": [], "rows": []}
    for t in targets:
        tk = ctx.kind(t)                                  # rate (bp moves) or xr (an FX pair's excess return, %)
        fx = t[3:] if t.startswith("XR:") else None
        days, vals = aligned(ctx, [t] + drivers, ctx.window() + 1)
        if len(days) < ctx.min_obs() + 1:
            rows.append({"key": t, "label": _macro_name(ctx, t), "error": "ortak gün az (%d)" % len(days)})
            continue
        y = diffs(tk, vals[0])
        xs = [diffs(ctx.kind(d), vals[1 + i]) for i, d in enumerate(drivers)]
        r = qm.ols(y, xs)
        if r is None:
            rows.append({"key": t, "label": _macro_name(ctx, t), "error": "regresyon kurulamadı"})
            continue
        sigma = math.sqrt(r["sigma2"])
        coef = r["coef"]
        last = [v[-1] for v in vals]
        resid_hist = r["resid"]
        # how much of a day's residual the following week took back: the next five days' move on the residual (OLS);
        # a residual that is not taken back is no trade (its expected profit is about nothing)
        nxt = [sum(y[i + 1:i + 1 + MACRO_HOLD]) for i in range(len(y) - MACRO_HOLD)]
        rv = qm.ols(nxt, [resid_hist[:len(nxt)]]) if len(nxt) >= 30 else None
        rev_beta = rv["coef"][1] if rv else None
        rev_t = rv["t"][1] if rv else None

        def attribution(live, t=t, last=last, coef=coef, tk=tk):
            now = [live.get(k) for k in [t] + drivers]
            if all(v is not None for v in now):
                dy = change(tk, last[0], now[0])
                dx = [change(ctx.kind(d), last[1 + i], now[1 + i]) for i, d in enumerate(drivers)]
                when = "canlı"
            else:
                dy, dx, when = y[-1], [x[-1] for x in xs], "son kapanış"
            if dy is None or any(v is None for v in dx):
                return None
            parts = [coef[1 + i] * dx[i] for i in range(len(drivers))]
            glob = sum(parts)
            return {"dy": dy, "global": glob, "parts": parts, "resid": dy - coef[0] - glob, "when": when, "dx": dx}

        def zfn(level, live, attribution=attribution, sigma=sigma):
            a = attribution(live)
            return a["resid"] / sigma if a and sigma else None

        cur = attribution(ctx.live)
        row = {"key": t, "label": _macro_name(ctx, t), "n": r["n"], "r2": r["r2"], "alpha": coef[0], "sigma": sigma,
               "betas": coef[1:], "t": r["t"][1:], "today": cur, "z": (cur["resid"] / sigma) if cur and sigma else None,
               "rev_beta": rev_beta, "rev_t": rev_t, "unit": change_unit(tk)}
        rows.append(row)
        reg = regime_of(vals[0], tk, ctx.cfg)
        zh = [e / sigma for e in resid_hist] if sigma else None
        div = 100.0 if tk == "rate" else 1.0             # a change (bp / %) in level units

        def mfcast(level, z, sigma=sigma, rev_beta=rev_beta, div=div):
            # the week's expected move: what the residual's history says the next week takes back of it
            return (rev_beta or 0.0) * (z or 0.0) * sigma / div if rev_beta is not None and rev_beta < 0 else 0.0

        def mthesis(sg, t=t, fx=fx, rev_beta=rev_beta):
            a = attribution(ctx.derive_live(ctx.live)) or {}
            u = change_unit(tk)
            return ("%s bugün %s %s hareket etti; küresel sürücüler %s %s açıklıyor, %s %s TRY'ye özgü (z %s). Geçmişte böyle bir kalıntının %%%s'i "
                    "ertesi hafta geri döndü → %s; beklenen %s%s." % (
                        _macro_name(ctx, t), _sg(a.get("dy"), 1), u, _sg(a.get("global"), 1), u, _sg(a.get("resid"), 1), u, _sg(sg["z"], 2),
                        _g(max(0.0, -(rev_beta or 0.0)) * 100.0, 0), sg["expression"], exp_text(sg), _incl(sg)))

        legs = [{"key": "FX:" + fx, "name": "%s forward" % fx, "weight": 1.0}] if fx else [{"key": t, "name": _ois_name(ctx, t), "weight": 1.0}]
        mon = Monitor("macro:" + t, "macro", "FX" if fx else "TRY OIS", "%s forward" % fx if fx else _ois_name(ctx, t), "%", 3,
                      days[1:][-ctx.window():], vals[0][1:][-ctx.window():],
                      legs, lambda live, t=t: ctx.cur(t, live), zfn=zfn,
                      zvalues=zh[-ctx.window():] if zh else None, mode="drift", hold=float(MACRO_HOLD), regime=reg, pkg="fx" if fx else "rate",
                      carry_up=None if fx else ctx.carry_week(t), info={"inputs": list(drivers) + (["FX:" + fx] if fx else []), "rev_beta": rev_beta,
                                                                      "rev_t": rev_t},
                      fx=fx, dsd=sigma / div, pnl=pnl_scale(tk, None), fcast=mfcast, thesis=mthesis,
                      series_label=xr_label(fx) if fx else None,
                      note="Bugünkü hareketin küresel sürücülerin (β × değişim) açıklamadığı kısmı: + ise TRY'ye özgü yükseliş (geri dönüş beklenir). "
                           "Beklenen: geçmişte kalıntının ertesi hafta geri dönen payı (sonraki 5 günün hareketinin kalıntıya regresyonu, β %s, t %s) "
                           "× bugünkü kalıntı%s." % (_f2(rev_beta), _f2(rev_t), "; FX'te forward pozisyonunun getirisi üzerinden (kur değişimi − "
                                                                               "forward primi) - işlem fiyatları ve 1 mn baz döviz başına K/Z yukarıda" if fx else ""))
        mon.reward = None
        mon.risk = None
        mon._sigma = sigma                       # type: ignore[attr-defined]
        mon._attr = attribution                  # type: ignore[attr-defined]
        mon._div = div                           # type: ignore[attr-defined]
        mons.append(mon)
    labels = {"UST:2Y": "UST 2Y (bp)", "UST:10Y": "UST 10Y (bp)", "DXY": "DXY (%)", "EMFX": "EM FX (%)", "BRENT": "Brent (%)", "CDS": "CDS (bp)"}
    return mons, {"ok": True, "drivers": drivers, "driver_labels": [labels.get(d, d) for d in drivers], "rows": rows}


def macro_levels(m: Monitor, cfg: Dict[str, Any]) -> None:
    """Target and stop of a macro residual signal: the level the global move alone would give, and the level where the
    residual would be at the stop's z."""
    sigma = getattr(m, "_sigma", None)
    if m.z is None or not sigma:
        return
    div = getattr(m, "_div", 100.0)
    m.reward = abs(m.z) * sigma / div
    m.risk = max(float(cfg["stop_z"]) - abs(m.z), 0.5) * sigma / div


# ---------------------------------------------------------------------------------------------- 5. pairs, 7. Kalman
def _interp(points: List[Tuple[float, float]], x: float) -> Optional[float]:
    if not points:
        return None
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    i = bisect.bisect_left([p[0] for p in points], x)
    (x0, y0), (x1, y1) = points[i - 1], points[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y0


def _ois_curves(ctx: Ctx) -> Dict[str, List[Tuple[float, float]]]:
    """Per day: the OIS curve (months, %), for the rate of any maturity."""
    out: Dict[str, List[Tuple[float, float]]] = {}
    for k in ctx.ois_keys(min_months=1.0):
        m = ctx.months(k)
        for d, v in ctx.series[k].items():
            out.setdefault(d, []).append((m, v))
    for d in out:
        out[d].sort()
    return out


def _months_between(a: _dt.date, b: _dt.date) -> float:
    return (b - a).days / 30.4375


def pair_specs(ctx: Ctx) -> List[Dict[str, Any]]:
    """The pairs the scanner tests: ``{pid, label, group, y, x (key or series), units …}``."""
    specs: List[Dict[str, Any]] = []
    # onshore vs offshore OIS, tenor by tenor
    for k in sorted((k for k in ctx.meta if k.startswith("OFF:")), key=lambda k: ctx.months(k) or 0):
        m = ctx.months(k)
        o = ctx.ois_at(m) if m else None
        if o and ctx.has(k) and ctx.has(o):
            specs.append({"pid": "off:" + k[4:], "label": "Offshore %s / OIS %s" % (k[4:], o[4:]), "group": "Offshore − OIS", "asset": "Offshore",
                          "y": k, "x": o, "scale": 100.0})
    # VİOP implied vs the OIS of its dates
    for c in ctx.viop:
        yk, xk = "VIOPI:" + c["ticker"], "VIOPO:" + c["ticker"]
        if ctx.has(yk) and ctx.has(xk):
            specs.append({"pid": "viop:" + c["ticker"], "label": "VİOP %s ima / OIS" % c["name"], "group": "VİOP − OIS", "asset": "VİOP",
                          "y": yk, "x": xk, "scale": 100.0, "min_share": 100.0 / max(100.0, ctx.min_obs())})
    # DİBS: the yield against the OIS of the bond's maturity; a TLREF floater's discount margin against it
    curves = None
    bonds = [k for k in ctx.meta if k.startswith("DIBS:") and ctx.has(k, ctx.min_obs())]
    bonds.sort(key=lambda k: -len(ctx.series[k]))
    taken = 0
    for k in bonds:
        info = ctx.meta[k]
        mat = info.get("maturity")
        if not mat:
            continue
        try:
            md = _dt.date.fromisoformat(mat)
        except ValueError:
            continue
        if _months_between(ctx.today, md) < 6:
            continue
        if curves is None:
            curves = _ois_curves(ctx)
        floater = info.get("unit") == "px"
        xs: Dict[str, float] = {}
        ys: Dict[str, float] = {}
        for d, v in ctx.series[k].items():
            dd = _dt.date.fromisoformat(d)
            months = _months_between(dd, md)
            if months <= 0 or d not in curves:
                continue
            x = _interp(curves[d], months)
            if x is None:
                continue
            xs[d] = x
            ys[d] = (100.0 - v) / (months / 12.0) * 100.0 if floater else v
        if len(xs) < ctx.min_obs():
            continue
        name = info.get("name") or k[5:]
        specs.append({"pid": ("frn:" if floater else "dibs:") + k[5:], "label": ("%s TLREF FRN marjı / OIS" if floater else "%s getiri / OIS") % name,
                      "group": "TLREF FRN − OIS" if floater else "DİBS − OIS", "asset": "DİBS", "y": k, "x": "OISAT:" + k[5:],
                      "ys": ys, "xs": xs, "scale": 1.0 if floater else 100.0, "maturity": md, "floater": floater})
        taken += 1
        if taken >= 12:
            break
    # USDTRY forward points (the implied differential) against TRY OIS − USD OIS
    if ctx.has("FWD:USDTRY:3M") and ctx.has("FX:USDTRY") and ctx.has("USD:3M") and ctx.ois_at(3):
        o = ctx.ois_at(3)
        ys = {}
        for d, f in ctx.series["FWD:USDTRY:3M"].items():
            s = ctx.series["FX:USDTRY"].get(d)
            if s:
                ys[d] = (f / s - 1.0) * 365.0 / 91.25 * 100.0
        xs = {d: ctx.series[o][d] - u for d, u in ctx.series["USD:3M"].items() if d in ctx.series[o]}
        specs.append({"pid": "pts:USDTRY3M", "label": "USDTRY 3M puan farkı / OIS 3M − USD 3M", "group": "Forward puanı", "asset": "FX",
                      "y": "FXP:USDTRY:3M", "x": o, "ys": ys, "xs": xs, "scale": 100.0, "points": True})
    return specs


def _pair_now(ctx: Ctx, spec: Dict[str, Any], live: Dict[str, float]) -> Tuple[Optional[float], Optional[float]]:
    """The pair's y and x now (live where there is a live value)."""
    if spec.get("points"):
        f, s, o, u = live.get("FWD:USDTRY:3M"), live.get("FX:USDTRY"), live.get(spec["x"]), live.get("USD:3M")
        f = f if f is not None else ctx.last("FWD:USDTRY:3M")
        s = s if s is not None else ctx.last("FX:USDTRY")
        o = o if o is not None else ctx.last(spec["x"])
        u = u if u is not None else ctx.last("USD:3M")
        if None in (f, s, o, u) or not s:
            return None, None
        return (f / s - 1.0) * 365.0 / 91.25 * 100.0, o - u
    if "xs" in spec:
        md = spec["maturity"]
        months = _months_between(ctx.today, md)
        pts = []
        for k in ctx.ois_keys(min_months=1.0):
            v = ctx.cur(k, live)
            if v is not None:
                pts.append((ctx.months(k), v))
        pts.sort()
        x = _interp(pts, months)
        yv = ctx.last(spec["y"])                               # DİBS: the last close (no live yield here)
        if yv is None or x is None:
            return None, None
        y = (100.0 - yv) / (months / 12.0) * 100.0 if spec.get("floater") else yv
        return y, x
    return ctx.cur(spec["y"], live), ctx.cur(spec["x"], live)


def _pair_legs(ctx: Ctx, spec: Dict[str, Any], beta: float) -> List[Dict[str, Any]]:
    y, x = spec["y"], spec["x"]
    yname = ctx.label(y) if not y.startswith("DIBS:") else (ctx.meta[y].get("name") or y[5:])
    if spec.get("points"):
        yname = "USDTRY 3M swap puanı"
    xname = ctx.label(x) if not x.startswith("OISAT:") else "OIS (vadesine göre)"
    xkey = x if not x.startswith("OISAT:") else "OIS:%s" % _nearest_label(_months_between(ctx.today, spec["maturity"]))
    # (a floater's margin moves like a yield: wider is cheaper - the bond leg reads the same way as a fixed bond's)
    return [{"key": y, "name": yname, "weight": 1.0}, {"key": xkey, "name": xname, "weight": -beta}]


def _nearest_label(months: float) -> str:
    best = min(_TENOR_MONTHS.items(), key=lambda kv: abs(kv[1] - months))
    return best[0]


def fam_pairs(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    mons: List[Monitor] = []
    rows = []
    win = ctx.window()
    q = float(ctx.cfg["kalman_q"])
    for spec in pair_specs(ctx):
        ys = spec.get("ys") or ctx.series.get(spec["y"]) or {}
        xs = spec.get("xs") or ctx.series.get(spec["x"]) or {}
        days = sorted(set(ys) & set(xs))[-win:]
        need = int(ctx.min_obs() * spec.get("min_share", 1.0))
        row = {"pid": spec["pid"], "label": spec["label"], "group": spec["group"], "n": len(days)}
        if len(days) < need:
            row["error"] = "ortak gün az (%d / %d)" % (len(days), need)
            rows.append(row)
            continue
        y = [ys[d] for d in days]
        x = [xs[d] for d in days]
        eg = qm.engle_granger(y, x)
        if eg is None:
            row["error"] = "regresyon kurulamadı"
            rows.append(row)
            continue
        a, b = eg["alpha"], eg["beta"]
        k = spec["scale"]
        spread = [(y[i] - a - b * x[i]) * k for i in range(len(days))]
        test = eg["adf"] or {}
        # a pair is a pair when the residual has no unit root (ADF, Engle-Granger 5 %) *and* the hedge ratio means
        # something (|t| ≥ 2): a y that is stationary on its own passes the first test with β ≈ 0
        passes = bool(eg["passes"] and eg["t_beta"] is not None and abs(eg["t_beta"]) >= 2.0)
        row.update({"alpha": a, "beta": b, "t_beta": eg["t_beta"], "r2": eg["r2"], "adf": test.get("stat"), "crit5": (test.get("crit") or {}).get(5),
                    "level": test.get("level"), "passes": passes, "adf_passes": eg["passes"], "spread": spread[-1]})
        legs = _pair_legs(ctx, spec, b)

        def calc(live, spec=spec, a=a, b=b, k=k):
            yv, xv = _pair_now(ctx, spec, live)
            return None if yv is None or xv is None else (yv - a - b * xv) * k

        unit = "bp" if k == 100.0 or spec.get("floater") else ""
        mon = mr_monitor(ctx, "pairs:" + spec["pid"], "pairs", spec["asset"], spec["label"], unit, 1, days, spread, "bp", legs, calc,
                         min_share=spec.get("min_share", 1.0), pkg="pair",
                         note="Engle-Granger: %s = α + β × %s; β = %s. Spread + ise y pahalı tarafta (y'nin seviyesi yüksek)." %
                         ("y", "x", _f2(b)))
        if mon is not None:
            row.update({"z": mon.zof(spread[-1]), "half_life": mon.half_life, "regime": (mon.regime or {}).get("tag"), "sid": mon.sid})
            mon.info.update({"beta": b, "adf": test.get("stat"), "crit5": (test.get("crit") or {}).get(5), "passes": passes})
            if passes:
                mons.append(mon)
        # Kalman: β that drifts, the one-step-ahead residual
        var_x = qm.var(x) or 0.0
        r_obs = eg["sigma"] ** 2
        if var_x > 0 and r_obs > 0:
            kf = qm.kalman_beta(y, x, a, b, r_obs / (var_x * len(x)), r_obs, q * r_obs / var_x)
            kres = [e * k for e in kf["innov"]]
            burn = min(20, len(kres) // 5)
            kd, kv = days[burn:], kres[burn:]
            kadf = qm.adf(kv, 4, 1)
            beta_t = kf["post"][-1]
            row.update({"k_beta": beta_t, "k_beta_series": kf["post"][-60:], "k_adf": kadf["stat"] if kadf else None,
                        "k_passes": bool(kadf and kadf["level"] in (1, 5))})

            def kcalc(live, spec=spec, a=a, beta_t=beta_t, k=k, last=kv[-1]):
                # a new point (live) against the ratio after the last close; without one, the last close's own residual
                if spec["y"] not in live and spec["x"] not in live:
                    return last
                yv, xv = _pair_now(ctx, spec, live)
                return None if yv is None or xv is None else (yv - a - beta_t * xv) * k

            kmon = mr_monitor(ctx, "kalman:" + spec["pid"], "kalman", spec["asset"], spec["label"] + " (Kalman β)", unit, 1, kd, kv, "bp",
                              _pair_legs(ctx, spec, beta_t), kcalc, min_share=spec.get("min_share", 1.0) * 0.9, pkg="pair",
                              note="Kalman filtresiyle günlük güncellenen hedge oranı β_t = %s (statik %s); kalıntı bir gün önceki β ile." % (
                                  _f2(beta_t), _f2(b)))
            if kmon is not None:
                row.update({"k_z": kmon.zof(kv[-1]), "k_half_life": kmon.half_life, "k_sid": kmon.sid})
                kmon.info.update({"beta": beta_t, "static_beta": b, "static_z": row.get("z")})
                if row["k_passes"]:
                    mons.append(kmon)
        rows.append(row)
    return mons, {"rows": rows, "q": q}


# ---------------------------------------------------------------------------------------------- h. VİOP calendar spreads
def _fwd(r1: float, d1: float, r2: float, d2: float) -> Optional[float]:
    """The simple forward rate (%, ACT/360) between two dates from the rates (%) to each (days from the same start)."""
    if d2 <= d1 or d1 < 0:
        return None
    return ((1.0 + r2 / 100.0 * d2 / 360.0) / (1.0 + r1 / 100.0 * d1 / 360.0) - 1.0) * 360.0 / (d2 - d1) * 100.0


def fam_viopcal(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    contracts = sorted((c for c in ctx.viop if c.get("expiry")), key=lambda c: c["expiry"])
    mons: List[Monitor] = []
    rows = []
    for i in range(len(contracts)):
        for j in range(i + 1, len(contracts)):
            near, far = contracts[i], contracts[j]
            days = sorted(set(near["imp"]) & set(far["imp"]) & set(near["ois360"]) & set(far["ois360"]) & set(near["days"]) & set(far["days"]))
            dev_days, dev = [], []
            for d in days:
                fi = _fwd(near["imp"][d], near["days"][d], far["imp"][d], far["days"][d])
                fo = _fwd(near["ois360"][d], near["days"][d], far["ois360"][d], far["days"][d])
                if fi is not None and fo is not None:
                    dev_days.append(d)
                    dev.append((fi - fo) * 100.0)
            label = "%s / %s" % (near["name"] or near["ticker"], far["name"] or far["ticker"])
            row = {"label": label, "near": near["ticker"], "far": far["ticker"], "n": len(dev)}

            def calc(live, near=near, far=far, last=dev[-1] if dev else None):
                # the VİOP sheet's live row; without it (no prices yet, replay), the last close's deviation
                ln, lf = near.get("live") or {}, far.get("live") or {}
                vals = [ln.get("imp"), ln.get("days"), lf.get("imp"), lf.get("days"), ln.get("ois360"), lf.get("ois360")]
                if any(v is None for v in vals):
                    return last
                fi = _fwd(ln["imp"], ln["days"], lf["imp"], lf["days"])
                fo = _fwd(ln["ois360"], ln["days"], lf["ois360"], lf["days"])
                return (fi - fo) * 100.0 if fi is not None and fo is not None else last

            legs = [{"key": "VIOPI:" + far["ticker"], "name": "VİOP " + (far["name"] or far["ticker"]), "weight": 1.0},
                    {"key": "VIOPI:" + near["ticker"], "name": "VİOP " + (near["name"] or near["ticker"]), "weight": -1.0}]
            mon = mr_monitor(ctx, "viopcal:%s|%s" % (near["ticker"], far["ticker"]), "viopcal", "VİOP", "VİOP takvim " + label, "bp", 1,
                             dev_days, dev, "bp", legs, calc, min_share=100.0 / max(100.0, ctx.min_obs()), pkg="spread",
                             info={"inputs": ["VIOPI:" + near["ticker"], "VIOPI:" + far["ticker"]]},
                             note="İki vade arasındaki ima TRY forward faizinin, OIS'ten (aynı tarihler, USD faiziyle faiz paritesi) "
                                  "hesaplanan adil forward'dan farkı (bp): + ise uzak vade yakına göre pahalı (uzak sat / yakın al).")
            if dev:
                row["dev"] = dev[-1]
            if mon is not None:
                row.update({"z": mon.zof(dev[-1]), "half_life": mon.half_life, "sid": mon.sid})
                mons.append(mon)
            rows.append(row)
    return mons, {"rows": rows, "contracts": [{"ticker": c["ticker"], "name": c["name"], "expiry": c["expiry"], "n": len(c["imp"])} for c in contracts]}


# ---------------------------------------------------------------------------------------------- i. FRA / OIS forwards vs the PPK path
FRA_BUCKETS = ((1, 3), (3, 6), (6, 9), (9, 12))
PATH_TENORS = (1, 2, 3, 6, 9, 12)


def _add_months(d: _dt.date, months: int) -> _dt.date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return _dt.date(y, m, min(d.day, last))


def business_on_or_after(d: _dt.date, holidays: set) -> _dt.date:
    while d.weekday() >= 5 or d in holidays:
        d += _dt.timedelta(days=1)
    return d


def tenor_end(spot: _dt.date, months: int, holidays: set) -> _dt.date:
    """A TRY OIS tenor's end as the workbook counts it (Motor!B325: ``WORKDAY(EDATE(spot, m) − 1, 1, holidays)``): the
    same day ``months`` later, or the first business day after it."""
    return business_on_or_after(_add_months(spot, months), holidays)


#: TRY OIS conventions (the workbook's Motor!G325:K342): up to 3 months one payment at the end, ACT/365 simple; longer
#: tenors pay quarterly (each quarter's end as a tenor's end), the par rate (1 − DF_T) / Σ accrual × DF; the overnight
#: rate compounds business day by business day (a weekend or a holiday accrues simply at the rate before it)
SINGLE_PAYMENT_MONTHS = 3


def par_rate(spot: _dt.date, df: Callable[[_dt.date], Optional[float]], months: int, holidays: set) -> Optional[float]:
    """The par rate (%) of a TRY OIS of ``months`` from discount factors ``df(date)``, in the convention above."""
    end = tenor_end(spot, months, holidays)
    dfe = df(end)
    if dfe is None or dfe <= 0:
        return None
    if months <= SINGLE_PAYMENT_MONTHS:
        return (1.0 / dfe - 1.0) * 365.0 / (end - spot).days * 100.0
    ann = 0.0
    prev = spot
    for k in range(1, int(math.ceil(months / 3.0)) + 1):
        t = tenor_end(spot, min(3 * k, months), holidays)
        dft = df(t)
        if dft is None:
            return None
        ann += (t - prev).days / 365.0 * dft
        prev = t
    return (1.0 - dfe) / ann * 100.0 if ann > 0 else None


def curve_dfs(spot: _dt.date, quotes: Dict[int, float], holidays: set) -> List[Tuple[_dt.date, float]]:
    """Discount factors at each quoted tenor's end, bootstrapped in the convention above (the quarters inside a longer
    tenor read off the factors found so far, log-linear in days, the tenor's own one solved with them)."""
    pillars: List[Tuple[_dt.date, float]] = []

    def interp(d: _dt.date, pts: List[Tuple[_dt.date, float]]) -> Optional[float]:
        return curve_df(spot, [], d, pts)

    for m in sorted(quotes):
        r = quotes[m] / 100.0
        end = tenor_end(spot, m, holidays)
        days = (end - spot).days
        if days <= 0:
            continue
        if m <= SINGLE_PAYMENT_MONTHS:
            pillars.append((end, 1.0 / (1.0 + r * days / 365.0)))
            continue
        guess = 1.0 / (1.0 + r * days / 365.0)
        for _ in range(4):                                # the quarters past the last pillar lean on this one: iterate
            pts = pillars + [(end, guess)]
            known, prev, ok = 0.0, spot, True
            dates = [tenor_end(spot, min(3 * k, m), holidays) for k in range(1, int(math.ceil(m / 3.0)) + 1)]
            for t in dates[:-1]:
                dft = interp(t, pts)
                if dft is None:
                    ok = False
                    break
                known += (t - prev).days / 365.0 * dft
                prev = t
            if not ok:
                break
            acc = (end - prev).days / 365.0
            guess = (1.0 - r * known) / (1.0 + r * acc)
        pillars.append((end, guess))
        pillars.sort()
    return pillars


def path_df(spot: _dt.date, base: float, steps: List[Tuple[_dt.date, float]], end: _dt.date, holidays: set) -> float:
    """The discount factor to ``end`` of the overnight path: ``base`` (a fraction) until the first meeting, then the
    level after each meeting from the day after it - compounded business day by business day (ACT/365, a weekend or
    a holiday accruing at the rate of the business day before it)."""
    df = 1.0
    d = spot
    k = 0
    rate = base
    while d < end:
        nxt = d + _dt.timedelta(days=1)
        while nxt.weekday() >= 5 or nxt in holidays:
            nxt += _dt.timedelta(days=1)
        nxt = min(nxt, end)
        while k < len(steps) and steps[k][0] < d:
            rate = steps[k][1]
            k += 1
        df /= 1.0 + rate * (nxt - d).days / 365.0
        d = nxt
    return df


def curve_df(spot: _dt.date, pillars: List[Tuple[_dt.date, float]], end: _dt.date,
             dfs: Optional[List[Tuple[_dt.date, float]]] = None) -> Optional[float]:
    """Discount factor to ``end``: log-linear in days between discount factors ``dfs`` (date, factor) - or, from par
    rates of one payment ``pillars`` (date, %), their own factors."""
    pts = [(0.0, 0.0)]
    if dfs is not None:
        for d, f in dfs:
            t = (d - spot).days
            if t > 0 and f > 0:
                pts.append((float(t), math.log(f)))
    else:
        for d, r in pillars:
            t = (d - spot).days
            if t > 0:
                pts.append((float(t), math.log(1.0 / (1.0 + r / 100.0 * t / 365.0))))
    pts.sort()
    x = float((end - spot).days)
    if x > pts[-1][0] + 1e-9 or len(pts) < 2:
        return None
    return math.exp(_interp(pts, x))


def mpc_periods(spot: _dt.date, steps: List[Tuple[_dt.date, float]], reach: _dt.date, count: int = 4) -> List[Tuple[_dt.date, _dt.date, _dt.date]]:
    """The periods between the coming meetings, as a meeting-dated OIS runs: ``(meeting, start, end)`` - from the day
    after one decision to the day after the next, the first ``count`` that end within the curve's ``reach``."""
    dates = [d for d, _ in steps if d >= spot]
    out = []
    for a, b in zip(dates, dates[1:]):
        start, end = a + _dt.timedelta(days=1), b + _dt.timedelta(days=1)
        if end > reach:
            break
        out.append((a, start, end))
        if len(out) >= count:
            break
    return out


def frapath_day(spot: _dt.date, base: float, steps: List[Tuple[_dt.date, float]], quotes: Dict[int, float], holidays: set) -> Dict[str, Any]:
    """One day, in the workbook's own convention (``SINGLE_PAYMENT_MONTHS``): each quoted tenor's par rate from the
    meeting path against its quote - the path was solved from these quotes, so they should agree to a basis point or
    two -, each FRA bucket's forward from the curve (the quotes bootstrapped) and from the path, and the path's level
    for each coming meeting period."""
    dfs = curve_dfs(spot, quotes, holidays)
    reach = max(d for d, _ in dfs) if dfs else spot
    out: Dict[str, Any] = {"fra": {}, "tenor": {}, "mpc": {}}

    def pdf(d: _dt.date) -> float:
        return path_df(spot, base, steps, d, holidays)

    def cdf(d: _dt.date) -> Optional[float]:
        return curve_df(spot, [], d, dfs)

    for m, r in quotes.items():
        par = par_rate(spot, pdf, m, holidays)
        if par is not None:
            out["tenor"][m] = {"quote": r, "path": par, "dev": (r - par) * 100.0}
    for m1, m2 in FRA_BUCKETS:
        a, b = tenor_end(spot, m1, holidays), tenor_end(spot, m2, holidays)
        if b > reach or b <= a:
            continue
        ca, cb = cdf(a), cdf(b)
        if ca is None or cb is None:
            continue
        pa, pb = pdf(a), pdf(b)
        fc = (ca / cb - 1.0) * 365.0 / (b - a).days
        fp = (pa / pb - 1.0) * 365.0 / (b - a).days
        out["fra"]["%dx%d" % (m1, m2)] = {"curve": fc * 100.0, "path": fp * 100.0, "dev": (fc - fp) * 10000.0}
    prev = base
    for meeting, a, b in mpc_periods(spot, steps, reach):
        level = next((lv for d, lv in steps if d == meeting), None)
        if level is None:
            continue
        pa, pb = pdf(a), pdf(b)
        out["mpc"][meeting.isoformat()] = {"start": a.isoformat(), "end": b.isoformat(), "path": level * 100.0,
                                           "fwd": (pa / pb - 1.0) * 365.0 / max(1, (b - a).days) * 100.0, "step": (level - prev) * 10000.0}
        prev = level
    return out


#: an FRA bucket the path does not reproduce by at least this much (bp) is a deviation; below it, the solver's tolerance
FRA_MIN_BP = 5.0


def fam_frapath(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    mpc = ctx.mpc or {}
    days_meta = mpc.get("days") or {}
    by_day: Dict[str, List[Tuple[str, float]]] = {}
    for r in mpc.get("values") or []:
        if r.get("level") is not None:
            by_day.setdefault(r["day"], []).append((r["meeting"], r["level"]))
    tenor_keys = {m: ctx.ois_at(m) for m in PATH_TENORS}
    tenor_keys = {m: k for m, k in tenor_keys.items() if k}
    if len(tenor_keys) < 4:
        return [], {"ok": False, "why": "1A – 1Y OIS vadelerinin geçmişi yok", "rows": [], "tenors": []}
    series: Dict[str, List[Tuple[str, float]]] = {}
    tenor_series: Dict[int, List[Tuple[str, float]]] = {}
    last_day: Optional[str] = None
    for d in sorted(by_day):
        meta = days_meta.get(d) or {}
        if d >= ctx.today_iso or meta.get("flag") in ("inconsistent", "error") or not meta.get("spot") or meta.get("base") is None:
            continue
        quotes = {m: ctx.series[k][d] for m, k in tenor_keys.items() if d in ctx.series[k]}
        if len(quotes) < 4:
            continue
        spot = _dt.date.fromisoformat(meta["spot"])
        steps = sorted((_dt.date.fromisoformat(mt), lv) for mt, lv in by_day[d])
        base = meta["fit_base"] if meta.get("fit_base") is not None else meta["base"]
        res = frapath_day(spot, base, steps, quotes, ctx.holidays)
        for name, v in res["fra"].items():
            series.setdefault(name, []).append((d, v["dev"]))
        for m, v in res["tenor"].items():
            tenor_series.setdefault(m, []).append((d, v["dev"]))
        last_day = d
    # today: the path the history solved today with today's quotes (the same day); an earlier path is not compared
    # with today's quotes - their difference would be the market's move since, not the path's fit
    now = None
    p = ctx.path
    same_day = bool(p and p.get("day") == ctx.today_iso)
    if same_day and p.get("spot") and p.get("base") is not None and p.get("steps"):
        now_quotes = {m: ctx.cur(k) for m, k in tenor_keys.items() if ctx.cur(k) is not None}
        if len(now_quotes) >= 4:
            now = frapath_day(p["spot"], p.get("fit_base") if p.get("fit_base") is not None else p["base"], p["steps"], now_quotes, ctx.holidays)
    mons: List[Monitor] = []
    rows = []
    for m1, m2 in FRA_BUCKETS:
        name = "%dx%d" % (m1, m2)
        pts = series.get(name) or []
        far, near = tenor_keys.get(m2), tenor_keys.get(m1)
        row = {"bucket": name, "n": len(pts), "now": (now or {}).get("fra", {}).get(name), "dev": pts[-1][1] if pts else None}
        if not pts or not far or not near:
            rows.append(row)
            continue
        ann_far = _annuity(ctx.cur(far) or 30.0, m2)
        ann_near = _annuity(ctx.cur(near) or 30.0, m1)
        span = ann_far - ann_near
        legs = [{"key": far, "name": _ois_name(ctx, far), "weight": ann_far / span if span > 0 else 1.0},
                {"key": near, "name": _ois_name(ctx, near), "weight": -ann_near / span if span > 0 else -1.0}]

        def calc(live, name=name, last=pts[-1][1]):
            # today with today's path and quotes (live where there are); before today's path, the last close's
            q = {m: ctx.cur(k, live) for m, k in tenor_keys.items()}
            q = {m: v for m, v in q.items() if v is not None}
            if not same_day or len(q) < 4:
                return last
            pp = ctx.path
            r = frapath_day(pp["spot"], pp.get("fit_base") if pp.get("fit_base") is not None else pp["base"], pp["steps"], q, ctx.holidays)
            v = (r["fra"].get(name) or {}).get("dev")
            return v if v is not None else last

        def fthesis(sg, name=name):
            return ("Eğrinin %s forward'ı, aynı günün kotalarından çözülen PPK patikasının verdiğinden %s bp %s (z %s) → %s; beklenen %s%s." % (
                name, _g(abs(sg["level"]), 1), "yüksek" if sg["level"] > 0 else "düşük", _sg(sg["z"], 2), sg["expression"], exp_text(sg, 1),
                _incl(sg)))

        mon = mr_monitor(ctx, "frapath:" + name, "frapath", "TRY OIS", "%s FRA (PPK patikasına göre)" % name, "bp", 1, [d for d, _ in pts],
                         [v for _, v in pts], "bp", legs, calc, pkg="rate", carry_up=_pkg_carry(ctx, legs), min_abs=FRA_MIN_BP, thesis=fthesis,
                         min_share=60.0 / max(60.0, ctx.min_obs()),
                         note="Eğrinin (OIS kotaları, masa konvansiyonuyla: ≤ 3A tek ödeme, uzunlar üç ayda bir kupon) %s forward'ı ile aynı günün "
                              "kotalarından çözülen toplantı tarihli PPK patikasının aynı dönem için verdiği forward arasındaki fark (bp). Patika kotaları "
                              "yeniden üretir; fark yalnızca %s bp'yi aşınca (çözücünün toleransı) sinyaldir: + ise eğri patikadan yüksek, uzak bacak "
                              "ucuz (FRA receive: %s receive / %s pay)." % (name, _g(FRA_MIN_BP, 0), _ois_name(ctx, far), _ois_name(ctx, near)))
        if mon is not None:
            row.update({"z": mon.zof(pts[-1][1]), "half_life": mon.half_life, "sid": mon.sid})
            mons.append(mon)
        rows.append(row)
    # the path's fit: quote − the path's own par rate, tenor by tenor (≈ 0: the same day, the same convention)
    tenors = []
    for m in sorted(tenor_series):
        pts = tenor_series[m]
        vals = [v for _, v in pts][-ctx.window():]
        cur = ((now or {}).get("tenor") or {}).get(m)
        tenors.append({"months": m, "label": _MONTH_LABEL.get(m, "%dM" % m), "dev": cur["dev"] if cur else (vals[-1] if vals else None),
                       "quote": cur["quote"] if cur else None, "path": cur["path"] if cur else None,
                       "max_abs": max((abs(v) for v in vals[-60:]), default=None), "n": len(vals),
                       "convention": "tek ödeme, ACT/365" if m <= SINGLE_PAYMENT_MONTHS else "üç ayda bir kupon, ACT/365"})
    periods = [dict(v, meeting=k) for k, v in sorted(((now or {}).get("mpc") or {}).items())]
    return mons, {"ok": True, "rows": rows, "tenors": tenors, "periods": periods, "live": now is not None, "path_day": (p or {}).get("day"),
                  "last_day": last_day, "min_bp": FRA_MIN_BP,
                  "convention": "TRY OIS: ≤ 3 ay vade sonunda tek ödeme (ACT/365, basit); daha uzunlar üç ayda bir kupon, par = (1 − DF) ÷ Σ "
                                "(gün / 365 × DF); vade sonu WORKDAY(EDATE(spot, ay) − 1, 1). Patika: TLREF (çözücünün taban seviyesi) her "
                                "toplantının ertesi iş gününden yeni seviyeye geçer, iş günü bileşik, tatil / hafta sonu basit. Çalışma kitabının "
                                "Motor!G325:K342 hesabıyla aynı."}


def _tr(iso: str) -> str:
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[2:4])


# ---------------------------------------------------------------------------------------------- 8/9. momentum and regime
MOM_UNIVERSE = (("OIS:3M", "Eğri"), ("OIS:6M", "Eğri"), ("OIS:1Y", "Eğri"), ("OIS:2Y", "Eğri"), ("OIS:3Y", "Eğri"), ("OIS:5Y", "Eğri"),
                ("OIS:10Y", "Eğri"), ("OFF:3M", "Eğri"), ("OFF:1Y", "Eğri"),
                ("UST:2Y", "Küresel"), ("UST:10Y", "Küresel"), ("DXY", "Küresel"), ("BRENT", "Küresel"), ("CDS", "Küresel"))


def mom_universe(ctx: Ctx) -> List[Tuple[str, str]]:
    """What the momentum board follows: the curve and the global drivers, and every FX pair kept - on the excess return
    of holding it through its forwards (``XR:``), carry included; a pair without forwards on its spot, told so."""
    out = list(MOM_UNIVERSE)
    for pair in ctx.fx_pairs():
        out.append(("XR:" + pair if "XR:" + pair in ctx.series else "FX:" + pair, "FX"))
    return out


def momentum_of(ctx: Ctx, key: str, live: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    cfg = ctx.cfg
    pts = ctx.pts(key)
    if len(pts) < 64 + 2:
        return None
    kind = ctx.kind(key)
    values = [v for _, v in pts]
    now = ctx.cur(key, live)
    if now is None:
        return None
    ch = diffs(kind, values)
    sd = qm.stdev(ch[-60:])
    if not sd:
        return None
    m = {}
    for n, name in ((5, "w1"), (21, "m1"), (63, "m3")):
        c = change(kind, values[-n], now)
        m[name] = c / (sd * math.sqrt(n)) if c is not None else None
    if any(v is None for v in m.values()):
        return None
    score = (m["w1"] + m["m1"] + m["m3"]) / 3.0
    fast, slow = int(cfg["ma_fast"]), int(cfg["ma_slow"])
    seq = values + [now]
    ma_f = sum(seq[-fast:]) / fast
    ma_s = sum(seq[-slow:]) / slow
    state = 1 if ma_f > ma_s else -1
    since = 0
    for back in range(1, min(len(seq) - slow, 120)):
        f = sum(seq[-fast - back:-back]) / fast
        s = sum(seq[-slow - back:-back]) / slow
        if (1 if f > s else -1) != state:
            break
        since = back
    return {"score": score, "sd": sd, "ma_fast": ma_f, "ma_slow": ma_s, "state": state, "since": since, "level": now, **m}


def _mom_thesis(m: Monitor, sg: Dict[str, Any]) -> str:
    up = (m.z or 0) > 0
    i = m.info
    if m.fx:
        c = sg.get("carry_yr")
        # the series is the excess return: up, the spot outruns what the forwards priced (a forward bought earns); down,
        # it falls behind (a forward sold earns)
        return ("%s forward'ların fiyatladığından %s (1H / 1A / 3A skorları %s / %s / %s, skor %s), hareketli ortalamalar %s; forward primi "
                "işlemin %s (yıllık %%%s) → %s; beklenen %s%s." % (
                    m.fx, "hızlı gidiyor: kur, forward primini aşıyor - forward'la alan kazanıyor" if up else
                    "geride kalıyor: kur, forward priminin gerisinde - forward'la satan kazanıyor", _sg(i.get("w1"), 2), _sg(i.get("m1"), 2),
                    _sg(i.get("m3"), 2), _sg(m.z, 2), "aynı yönde" if i.get("ma") == sign(m.z or 0) else "ters yönde",
                    "lehine" if (c or 0) >= 0 else "aleyhine", _sg(c, 1), sg["expression"], exp_text(sg), _incl(sg)))
    return ("%s 1H / 1A / 3A'da %s (skor %s), hareketli ortalamalar %s → %s; ufukta beklenen %s%s." % (
        m.name, "yükseliyor" if up else "düşüyor", _sg(m.z, 2), "aynı yönde" if i.get("ma") == sign(m.z or 0) else "ters yönde",
        sg["expression"], exp_text(sg, 1), _incl(sg)))


def fam_momentum(ctx: Ctx, extra: Sequence[Tuple[str, str]] = ()) -> Tuple[List[Monitor], Dict[str, Any]]:
    cfg = ctx.cfg
    horizon = float(cfg["horizon"])
    mons: List[Monitor] = []
    rows = []
    universe = mom_universe(ctx) + list(extra)
    for key, group in universe:
        if key.startswith("FX:"):
            pair = key[3:]
            if ctx.has(key, 66):
                rows.append({"key": key, "label": pair, "group": group, "error": "forward yok: carry hesaplanamadı (sinyal üretilmez)",
                             "carry": None})
            continue
        mo = momentum_of(ctx, key)
        if mo is None:
            if key.startswith("XR:") and ctx.has("FX:" + key[3:], 66):
                rows.append({"key": key, "label": key[3:], "group": group, "error": "carry geçmişi kısa (%d gün)" % len(ctx.series.get(key) or ()),
                             "carry": ctx.fx_carry(key[3:])})
            continue
        kind = ctx.kind(key)
        pts = ctx.pts(key)
        values = [v for _, v in pts][-ctx.window():]
        reg = regime_of(values, kind, cfg)
        fx = key[3:] if key.startswith("XR:") else None
        row = dict(mo, key=key, label=fx or ctx.label(key), group=group, regime=reg["tag"], hurst=reg["hurst"], vr=reg["vr"], vr_z=reg["vr_z"],
                   vol_pct=reg["vol_pct"], unit=level_unit(kind), carry=ctx.fx_carry(fx) if fx else None)
        rows.append(row)

        def calc(live, key=key):
            return ctx.cur(key, live)

        def zfn(level, live, key=key):
            r = momentum_of(ctx, key, live)
            return r["score"] if r else None

        level = mo["level"]
        steps = [b - a for a, b in zip(values, values[1:])]
        drift = shrunk_mean(steps[-63:])
        dsd = qm.stdev(steps[-60:])
        reward = (dsd or 0.0) * math.sqrt(horizon)
        to_ma = abs(level - mo["ma_slow"])
        legs = [{"key": "FX:" + fx, "name": "%s forward" % fx, "weight": 1.0}] if fx else [{"key": key, "name": ctx.label(key), "weight": 1.0}]
        mon = Monitor("momentum:" + key, "momentum", _asset_of("FX:" if fx else key), "%s forward" % fx if fx else ctx.label(key),
                      level_unit(kind), 3 if kind in ("rate", "xr") else 4, [d for d, _ in pts][-ctx.window():], values, legs, calc, zfn=zfn,
                      entry=float(cfg["mom_entry"]), follows=True, mode="drift", reward=reward,
                      risk=to_ma if 0.25 * reward <= to_ma <= 3 * reward else reward, hold=horizon, regime=reg,
                      pkg={"rate": "rate", "fx": "fx", "xr": "fx", "index": "fx", "bp": "cds", "vol": "vol"}.get(kind, "fx") if key != "CDS" else "cds",
                      carry_up=None if fx else ctx.carry_week(key), score_name="mom", fx=fx, dsd=dsd, pnl=pnl_scale(kind, level),
                      fcast=(drift["shrunk"] * horizon) if drift else None, gate_name="Ortalamalar",
                      gate=lambda s, mo=mo: (0.0, "hareketli ortalamalar onaylamıyor (%d / %d gün)" % (int(cfg["ma_fast"]), int(cfg["ma_slow"])))
                      if s != mo["state"] else (1.0, "%d / %d günlük ortalamalar aynı yönde" % (int(cfg["ma_fast"]), int(cfg["ma_slow"]))),
                      series_label=xr_label(fx) if fx else None,
                      note=("1H / 1A / 3A değişimlerin günlük vol × √gün'e bölümünün ortalaması; %d / %d günlük ortalamalar aynı yönü göstermeli. "
                            "Hedef: ufuk boyunca 1σ; stop: %d günlük ortalama. Beklenen: son 63 günün ortalama günlük değişimi (kesinliğiyle "
                            "küçültülmüş) × ufuk." % (int(cfg["ma_fast"]), int(cfg["ma_slow"]), int(cfg["ma_slow"])))
                      + (" FX: analiz serisi forward pozisyonunun birikimli getirisi (kur değişimi − forward primi, %); işlem ufkun sonu valörlü "
                         "forward'la, fiyatları ve 1 mn baz döviz başına K/Z yukarıda." if fx else ""),
                      info={"w1": mo["w1"], "m1": mo["m1"], "m3": mo["m3"], "ma": mo["state"], "drift_t": drift["t"] if drift else None})
        if key.startswith("UST:"):
            mon.pkg = "bond"
        mon.thesis = lambda sg, mon=mon: _mom_thesis(mon, sg)             # (a signal's thesis is called with the signal only)
        mons.append(mon)
    # cross-sectional rank within the curve and within FX
    for group in ("Eğri", "FX", "Küresel"):
        members = sorted((r for r in rows if r["group"] == group and r.get("score") is not None), key=lambda r: -r["score"])
        for i, r in enumerate(members):
            r["rank"] = i + 1
            r["of"] = len(members)
    return mons, {"rows": rows, "windows": [5, 21, 63], "ma": [int(cfg["ma_fast"]), int(cfg["ma_slow"])]}


def regime_table(ctx: Ctx, mons: List[Monitor]) -> List[Dict[str, Any]]:
    out = []
    for m in mons:
        r = m.regime or {}
        if not r or r.get("tag") is None and m.family in ("corr",):
            continue
        out.append({"sid": m.sid, "family": FAMILIES[m.family][0], "name": m.name, "tag": r.get("tag"), "vr": r.get("vr"), "vr_z": r.get("vr_z"),
                    "hurst": r.get("hurst"), "vol_pct": r.get("vol_pct"), "vol_tag": r.get("vol_tag"), "q": r.get("q"), "n": r.get("n")})
    return out


# ---------------------------------------------------------------------------------------------- l. the policy cycle
def cycle_phases(tlref: List[Tuple[str, float]], lag: int, threshold_bp: float) -> Dict[str, str]:
    """Each day's phase of the policy cycle from TLREF: its change over the last ``lag`` business days (closes) at or
    below −threshold: cutting; at or above it: hiking; in between: hold."""
    out: Dict[str, str] = {}
    for i in range(lag, len(tlref)):
        chg = (tlref[i][1] - tlref[i - lag][1]) * 100.0
        out[tlref[i][0]] = "indirim" if chg <= -threshold_bp else ("artırım" if chg >= threshold_bp else "sabit")
    return out


PHASES = ("indirim", "sabit", "artırım")


def fam_cycle(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    cfg = ctx.cfg
    horizon = int(cfg["horizon"])
    tl = ctx.pts("TLREF")
    phases = cycle_phases(tl, 63, float(cfg["cycle_bp"]))
    if not phases:
        return [], {"ok": False, "why": "TLREF geçmişi kısa (en az 64 kapanış)", "rows": [], "phase": None}
    now_phase = phases[max(phases)]
    slopes = []
    for name, long_k, short_k in (("2s10s", "OIS:10Y", "OIS:2Y"), ("1s2s", "OIS:2Y", "OIS:1Y"), ("2s5s", "OIS:5Y", "OIS:2Y")):
        if ctx.has(long_k) and ctx.has(short_k):
            slopes.append((name, long_k, short_k))
    mons: List[Monitor] = []
    rows = []
    counts = {p: sum(1 for v in phases.values() if v == p) for p in PHASES}
    for name, long_k, short_k in slopes:
        days, (lv, sv) = aligned(ctx, [long_k, short_k])
        s = [(a - b) * 100.0 for a, b in zip(lv, sv)]
        stats = {}
        for p in PHASES:
            fwd = [s[i + horizon] - s[i] for i in range(len(s) - horizon) if phases.get(days[i]) == p]
            nw = qm.newey_west(fwd, horizon - 1) if len(fwd) >= 3 else None
            cv = qm.nw_critical(len(fwd), horizon)
            stats[p] = {"n": len(fwd), "mean": nw["mean"] if nw else None, "t": nw["t"] if nw else None, "sd": nw["sd"] if nw else None,
                        "periods": len(fwd) / float(horizon), "cv": cv}
        cur = stats.get(now_phase) or {}
        row = {"slope": name, "level": s[-1] if s else None, "stats": stats, "phase": now_phase}
        rows.append(row)
        # the overlapping changes of a phase carry n / horizon independent periods: at least two are needed for any
        # test, and the t is held to the critical value of that sample (nw_critical) - not to 1.96
        if cur.get("t") is None or cur.get("n", 0) < 2 * horizon or not cur.get("sd"):
            continue

        def calc(live, long_k=long_k, short_k=short_k):
            a, b = ctx.cur(long_k, live), ctx.cur(short_k, live)
            return (a - b) * 100.0 if a is not None and b is not None else None

        t_now = cur["t"]
        cv = cur["cv"]
        entry = max(float(cfg["cycle_t"]), cv or 0.0)
        legs = [{"key": long_k, "name": _ois_name(ctx, long_k), "weight": 1.0}, {"key": short_k, "name": _ois_name(ctx, short_k), "weight": -1.0}]
        sample = {"ok": cv is not None, "n": cur["n"], "periods": cur["periods"], "cv": cv,
                  "text": "%d örtüşen gözlem ≈ %s bağımsız %d günlük dönem; küçük örneklem eşiği |t| ≥ %s" % (
                      cur["n"], _g(cur["periods"], 1), horizon, _g(cv, 2)) if cv is not None else "bağımsız dönem 2'den az: test yapılamaz"}

        def cthesis(sg, name=name, cur=cur, now_phase=now_phase):
            return ("TLREF %s fazında; bu fazda geçmişte %s sonraki %d iş gününde ortalama %s bp değişti (t %s, %s bağımsız dönem, eşik %s) → %s; "
                    "beklenen %s%s." % (now_phase, name, horizon, _sg(cur["mean"], 1), _g(cur["t"], 2), _g(cur["periods"], 1),
                                        _g(cur["cv"], 2), sg["expression"], exp_text(sg, 1), _incl(sg)))

        mon = Monitor("cycle:" + name, "cycle", "TRY OIS", name, "bp", 1, days[-ctx.window():], s[-ctx.window():], legs, calc,
                      zfn=lambda level, live, t_now=t_now: t_now, entry=entry, follows=True, mode="drift",
                      reward=abs(cur["mean"]), risk=cur["sd"], hold=float(horizon), pkg="slope", carry_up=_pkg_carry(ctx, legs),
                      regime={"tag": None}, score_name="t", zvalues=None, sample=sample, fcast=cur["mean"], pnl=("bp", 1.0),
                      dsd=qm.stdev([b - a for a, b in zip(s, s[1:])][-ctx.window():]), thesis=cthesis,
                      note="Bugünkü faz: %s. Bu fazdaki günlerden sonraki %d iş gününde %s ortalama %s bp değişti (n = %d örtüşen gözlem ≈ %s "
                           "bağımsız dönem, Newey-West t = %s). Eşik: masanın |t|'si ile bu örneklemin kritik değerinin (%s) büyüğü - az dönemle "
                           "Newey-West t'si şişer." % (now_phase, horizon, name, _f2(cur["mean"]), cur["n"], _g(cur["periods"], 1), _f2(t_now),
                                                     _g(cv, 2)),
                      info={"phase": now_phase, "mean": cur["mean"], "n": cur["n"], "t": t_now, "cv": cv, "periods": cur["periods"]})
        mon.zvalues = [None] * len(mon.values)
        mons.append(mon)
    return mons, {"ok": True, "phase": now_phase, "rows": rows, "counts": counts, "horizon": horizon, "rule": float(cfg["cycle_bp"])}


# ---------------------------------------------------------------------------------------------- 11. vol premium, m. vol forecast
VOL_PAIRS = ("USDTRY", "EURUSD", "USDZAR", "USDMXN", "USDBRL", "USDINR", "USDIDR", "USDHUF", "USDPLN", "USDCOP")


def vol_pairs(ctx: Ctx) -> List[str]:
    """The pairs with an ATM 3M vol history kept (USDTRY first, then by name)."""
    out = [p for p in ctx.fx_pairs() if ctx.series.get("FXV:" + p)]
    return sorted(out, key=lambda p: (p != "USDTRY", p))
FC_HORIZON = 63                          # business days of a 3M option


def _rets(values: Sequence[float]) -> List[float]:
    return [math.log(b / a) * 100.0 for a, b in zip(values, values[1:]) if a > 0 and b > 0]


def fam_vol(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    mons: List[Monitor] = []
    rows = []
    win = ctx.window()
    for pair in vol_pairs(ctx):
        sk, vk, rk = "FX:" + pair, "FXV:" + pair, "FXR:" + pair
        if not ctx.has(sk, 130) or not ctx.has(vk, 60):
            continue
        spot = ctx.pts(sk)
        sdays = [d for d, _ in spot]
        sval = [v for _, v in spot]
        rets = _rets(sval)
        rdays = sdays[1:]
        rv: Dict[int, Dict[str, float]] = {}
        for w in (21, 63, 126):
            out = {}
            for i in range(w - 1, len(rets)):
                sd = qm.stdev(rets[i - w + 1:i + 1])
                if sd:
                    out[rdays[i]] = sd * math.sqrt(252.0)
            rv[w] = out
        iv = ctx.series[vk]
        days = sorted(d for d in iv if d in rv[63])[-win:]
        if len(days) < 20:
            continue
        vrp = [iv[d] - rv[63][d] for d in days]
        # GARCH(1,1) fitted on the window's returns, its 3M average-variance forecast day by day; EWMA beside it
        fit_rets = rets[-(win + 1):]
        g = qm.garch_fit(fit_rets)
        ew = qm.ewma_var(rets, 0.94)
        fc_g: Dict[str, float] = {}
        fc_e: Dict[str, float] = {}
        if g:
            path = qm.garch_path(rets, g)
            for i, d in enumerate(rdays):
                fc_g[d] = math.sqrt(252.0 * qm.garch_avg_var(path[i + 1], g, FC_HORIZON))
        for i, d in enumerate(rdays):
            if ew[i + 1] is not None:
                fc_e[d] = math.sqrt(252.0 * ew[i + 1])
        fdays = [d for d in days if d in fc_g]
        vf = [iv[d] - fc_g[d] for d in fdays]
        row = {"pair": pair, "iv": ctx.cur(vk), "rv21": rv[21].get(rdays[-1]), "rv63": rv[63].get(rdays[-1]), "rv126": rv[126].get(rdays[-1]),
               "ewma": fc_e.get(rdays[-1]), "garch": fc_g.get(rdays[-1]), "garch_fit": g, "n": len(days)}
        rv63_now = rv[63].get(rdays[-1])
        g_now = fc_g.get(rdays[-1])

        def calc_vrp(live, vk=vk, rv63_now=rv63_now):
            v = ctx.cur(vk, live)
            return v - rv63_now if v is not None and rv63_now is not None else None

        def calc_vf(live, vk=vk, g_now=g_now):
            v = ctx.cur(vk, live)
            return v - g_now if v is not None and g_now is not None else None

        legs = [{"key": vk, "name": "%s 3M ATM vol" % pair, "weight": 1.0}]
        m1 = mr_monitor(ctx, "volprem:" + pair, "volprem", "FX vol", "%s 3M ATM vol" % pair, "vol", 2, days, vrp, "vol", legs, calc_vrp,
                        pkg="vol", note="ATM 3M ima vol − son 63 günün gerçekleşen vol'ü: + ise vol pahalı (sat), − ise ucuz (al).")
        if m1 is not None:
            mons.append(m1)
            row.update({"vrp": vrp[-1], "vrp_z": m1.zof(vrp[-1]), "vrp_hl": m1.half_life, "vrp_sid": m1.sid})
        if len(vf) >= 20:
            m2 = mr_monitor(ctx, "volfc:" + pair, "volfc", "FX vol", "%s 3M ATM vol" % pair, "vol", 2, fdays, vf, "vol", legs, calc_vf, pkg="vol",
                            note="ATM 3M ima vol − GARCH(1,1)'in önümüzdeki 63 iş günü için ortalama vol tahmini (α = %s, β = %s): + ise ima "
                                 "tahminden yüksek (sat)." % (_f2(g["alpha"]) if g else "—", _f2(g["beta"]) if g else "—"),
                            info={"garch": g, "ewma": fc_e.get(rdays[-1])})
            if m2 is not None:
                mons.append(m2)
                row.update({"vf": vf[-1], "vf_z": m2.zof(vf[-1]), "vf_hl": m2.half_life, "vf_sid": m2.sid})
        # skew: the 25D risk reversal's moves against the spot's (vol points per 1 % of spot)
        if ctx.has(rk, 64):
            rr = ctx.series[rk]
            common = [d for d in sdays if d in rr][-64:]
            if len(common) >= 30:
                sp = ctx.series[sk]
                x = [math.log(sp[b] / sp[a]) * 100.0 for a, b in zip(common, common[1:])]
                y = [rr[b] - rr[a] for a, b in zip(common, common[1:])]
                r = qm.ols(y, [x])
                if r:
                    row.update({"skew_beta": r["coef"][1], "skew_t": r["t"][1], "rr": ctx.cur(rk)})
        rows.append(row)
    return mons, {"rows": rows, "horizon": FC_HORIZON}


# ---------------------------------------------------------------------------------------------- 12. EM carry
CARRY_CCYS = ("TRY", "ZAR", "MXN", "BRL", "INR", "IDR", "HUF", "PLN", "COP")


def carry_ccys(ctx: Ctx) -> List[str]:
    """TRY and the emerging currencies quoted against the dollar (USD<ccy>) with a 3M forward and an ATM vol kept."""
    out = []
    for p in ctx.fx_pairs():
        g = (ctx.meta.get("FX:" + p) or {}).get("group")
        if p.startswith("USD") and (p == "USDTRY" or g == "EM") and "FWD:%s:3M" % p in ctx.series and ctx.series.get("FXV:" + p):
            out.append(p[3:])
    return sorted(out, key=lambda c: (c != "TRY", c))


def carry_series(ctx: Ctx, ccy: str) -> Dict[str, float]:
    """The annualised carry of the currency against USD (%): what the 3M forward implies, (F/S − 1)·365/days."""
    pair = "USD" + ccy
    f = ctx.series.get("FWD:%s:3M" % pair) or {}
    s = ctx.series.get("FX:" + pair) or {}
    return {d: (fv / s[d] - 1.0) * 365.0 / 91.25 * 100.0 for d, fv in f.items() if s.get(d)}


def fam_emcarry(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    win = ctx.window()
    cv: Dict[str, Dict[str, float]] = {}
    rows = []
    for ccy in carry_ccys(ctx):
        pair = "USD" + ccy
        c = carry_series(ctx, ccy)
        vol = ctx.series.get("FXV:" + pair) or {}
        x = {d: c[d] / vol[d] for d in c if vol.get(d)}
        if len(x) < 20:
            continue
        cv[ccy] = x
        days = sorted(x)[-win:]
        vals = [x[d] for d in days]
        car_now = _carry_now(ctx, ccy, ctx.live)
        vol_now = ctx.cur("FXV:" + pair)
        now = car_now / vol_now if car_now is not None and vol_now else vals[-1]
        rows.append({"ccy": ccy, "pair": pair, "carry": car_now, "vol": vol_now, "cv": now, "z": qm.zscore(now, vals) if len(vals) >= 20 else None,
                     "m1": now - vals[-21] if len(vals) > 21 else None, "n": len(vals)})
    rows.sort(key=lambda r: -(r["cv"] if r["cv"] is not None else -1e9))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    mons: List[Monitor] = []
    peers = [c for c in cv if c != "TRY"]
    if "TRY" in cv and len(peers) >= 3:
        rel_days, rel = [], []
        for d in sorted(cv["TRY"]):
            vals = [cv[c][d] for c in peers if d in cv[c]]
            if len(vals) >= 3:
                rel_days.append(d)
                rel.append(cv["TRY"][d] - sum(vals) / len(vals))
        rel_days, rel = rel_days[-win:], rel[-win:]
        if len(rel) >= ctx.min_obs():
            mean, sd = window_stats(rel)

            def rel_now(live):
                t = _carry_now(ctx, "TRY", live)
                tv = ctx.cur("FXV:USDTRY", live)
                others = []
                for c in peers:
                    cn, vn = _carry_now(ctx, c, live), ctx.cur("FXV:USD" + c, live)
                    if cn is not None and vn:
                        others.append(cn / vn)
                if t is None or not tv or len(others) < 3:
                    return None
                return t / tv - sum(others) / len(others)

            fwd = ctx.pts("FWD:USDTRY:3M")
            f_now = ctx.cur("FWD:USDTRY:3M")
            s_now = ctx.cur("FX:USDTRY")
            if fwd and f_now and s_now and sd:
                fv = [v for _, v in fwd]
                sd_f = qm.stdev(diffs("fx", fv)[-60:]) or 1.0
                horizon = float(ctx.cfg["horizon"])
                ol = fx_outlook(ctx, "USDTRY")

                def eexpect(side, hold, ol=ol):
                    # the USDTRY leg's expected excess return (the carry less the expected drift) over the holding, for its side
                    return side * ol["exp_long"] * hold * 7.0 / 5.0 / 365.0 if ol and ol.get("exp_long") is not None else None

                def ethesis(sg, ol=ol):
                    o = ol or {}
                    prem = -o["carry_long"] if o.get("carry_long") is not None else None      # (a long pays it: the forward above the spot)
                    return ("TRY'nin forward primi / vol oranı EM sepetine göre %s (z %s): USDTRY forward'ları yıllık %%%s prim fiyatlıyor, kur için "
                            "beklenen artış yıllık %%%s → %s; beklenen %s%s." % (
                                "yüksek" if (sg["z"] or 0) > 0 else "düşük", _sg(sg["z"], 2), _g(prem, 1), _g(o.get("drift"), 1),
                                sg["expression"], exp_text(sg), _incl(sg)))

                mon = Monitor("emcarry:TRY", "emcarry", "EM carry", "USDTRY 3M forward (EM sepetine karşı)", "", 4, [d for d, _ in fwd][-win:], fv[-win:],
                              [{"key": "FX:USDTRY", "name": "USDTRY 3M forward", "weight": 1.0}, {"key": "EMFX", "name": "USD / EM sepeti", "weight": -1.0}],
                              lambda live: ctx.cur("FWD:USDTRY:3M", live), zfn=lambda level, live: (rel_now(live) - mean) / sd if rel_now(live) is not None else None,
                              mode="drift", reward=(f_now - s_now) * horizon / 63.0, risk=to_level("fx", sd_f * math.sqrt(horizon), f_now),
                              hold=horizon, regime={"tag": None}, pkg="fx", score_name="z", fx="USDTRY", expect=eexpect, thesis=ethesis,
                              pnl=("%", None), pnl_sd=(ol or {}).get("daily_sd"), price="level", inst="USDTRY 3A forward", inst_days=_tenor_days("3M"),
                              zvalues=None, info={"rel": rel[-1], "mean": mean, "sd": sd, "inputs": ["FXV:USDTRY", "FX:USDTRY"]},
                              note="TRY'nin carry / vol oranı (3M forward'ın ima ettiği yıllık getiri farkı ÷ ATM 3M vol) ile EM sepetinin ortalaması "
                                   "arasındaki farkın z'si: + ise TRY carry'si göreli cazip (USDTRY forward sat, EM sepetine karşı). Hedef: ufuk boyunca "
                                   "carry kadar; stop: ufuk σ'sı kadar ters hareket. Beklenen: USDTRY bacağının carry − beklenen kayması ufuk boyunca.")
                rel_at = dict(zip(rel_days, rel))
                mon.zvalues = [(rel_at[d] - mean) / sd if d in rel_at else None for d in mon.days]
                mon.follows = False
                mons.append(mon)
            for r in rows:
                if r["ccy"] == "TRY":
                    r.update({"rel": rel[-1], "rel_z": (rel[-1] - mean) / sd if sd else None})
    return mons, {"rows": rows, "peers": peers}


def _carry_now(ctx: Ctx, ccy: str, live: Dict[str, float]) -> Optional[float]:
    pair = "USD" + ccy
    f, s = ctx.cur("FWD:%s:3M" % pair, live), ctx.cur("FX:" + pair, live)
    return (f / s - 1.0) * 365.0 / 91.25 * 100.0 if f and s else None


# ---------------------------------------------------------------------------------------------- n. forward premium / carry timing
FWD_TENORS = (("USDTRY", "1M", 21), ("USDTRY", "3M", 63), ("USDTRY", "6M", 126), ("USDTRY", "1Y", 252), ("EURTRY", "3M", 63))


def ewma_drift(rets: Sequence[float], days: Sequence[str], lam: float = 0.97) -> Dict[str, float]:
    """Day by day: the annualised EWMA (λ) of the daily log returns (%), shrunk towards zero by its precision - the
    t of the EWMA mean (its variance an EWMA too), nothing kept within three standard errors: a free float's month of
    noise is no drift, a managed crawl's is (USDTRY: t ≈ 10)."""
    out: Dict[str, float] = {}
    if len(rets) < 21:
        return out
    m = sum(rets[:20]) / 20.0
    v = sum((r - m) ** 2 for r in rets[:20]) / 19.0
    k = math.sqrt((1.0 - lam) / (1.0 + lam))
    for i in range(20, len(rets)):
        r = rets[i]
        v = lam * v + (1.0 - lam) * (r - m) ** 2
        m = lam * m + (1.0 - lam) * r
        se = math.sqrt(v) * k if v > 0 else 0.0
        t = m / se if se else 0.0
        out[days[i]] = m * shrink(t, 3.0) * 252.0
    return out


def fx_outlook(ctx: Ctx, pair: str, live: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """A pair's carry and what the spot is expected to do against it: the carry of a long (%/yr, the shortest forward),
    the expected drift (%/yr: the EWMA of the daily log returns shrunk by its precision), the expected excess return of a
    long (drift + carry), the buffer of the carry side (its expected excess), the vol it is weighed with (the ATM 3M,
    else the realized one of the excess returns) and the verdict on the pair's currency of interest."""
    spot = ctx.pts("FX:" + pair)
    if len(spot) < 30:
        return None
    sv = [v for _, v in spot]
    days = [d for d, _ in spot]
    rets = [math.log(b / a) * 100.0 if a > 0 and b > 0 else 0.0 for a, b in zip(sv, sv[1:])]
    dr = ewma_drift(rets, days[1:])
    drift = dr.get(days[-1]) if dr else None
    raw = shrunk_mean(rets[-250:], ewma=0.97)
    if raw:
        raw["w"] = shrink(raw["t"], 3.0)
    carry = ctx.fx_carry(pair, live)
    xr = [v for _, v in ctx.pts("XR:" + pair)]
    xs = [b - a for a, b in zip(xr, xr[1:])][-60:] if len(xr) > 20 else rets[-60:]
    daily_sd = qm.stdev(xs)
    iv = ctx.cur("FXV:" + pair, live)
    vol = iv if iv else (daily_sd * math.sqrt(252.0) if daily_sd else None)
    base, quote = pair[:3], pair[3:]
    focus = "TRY" if "TRY" in pair else (quote if base == "USD" else base)
    out = {"pair": pair, "spot": ctx.cur("FX:" + pair, live), "carry_long": carry, "drift": drift, "drift_raw": raw["raw"] * 252.0 if raw else None,
           "drift_w": raw["w"] if raw else None, "vol": vol, "vol_src": "ATM 3M" if iv else "gerçekleşen", "daily_sd": daily_sd, "focus": focus,
           "tenors": [t for t, _ in ctx.fx_tenors(pair)], "exp_long": None, "buffer": None, "sharpe": None, "verdict": None, "carry_side": None}
    if carry is None:
        out["verdict"] = "forward yok"
        return out
    if drift is None:
        return out
    exp_long = drift + carry
    side = 1 if carry > 0 else -1                        # the side the carry pays
    out.update({"exp_long": exp_long, "buffer": side * exp_long, "carry_side": side, "sharpe": exp_long / vol if vol else None})
    thr = float(ctx.cfg.get("fx_verdict", 0.3))
    sh = out["sharpe"]
    if sh is None or abs(sh) < thr:
        out["verdict"] = "nötr"
    else:
        long_base = sh > 0
        out["verdict"] = "%s %s" % (focus, "long" if (long_base == (focus == base)) else "short")
    return out


def fx_summary(ctx: Ctx) -> List[Dict[str, Any]]:
    """One line per pair: carry %/yr, expected drift, buffer, the verdict on its currency (TRY first)."""
    rows = []
    for pair in sorted(ctx.fx_pairs(), key=lambda p: ("TRY" not in p, (ctx.meta.get("FX:" + p) or {}).get("group") or "", p)):
        ol = fx_outlook(ctx, pair)
        if ol is None:
            continue
        ol["group"] = (ctx.meta.get("FX:" + pair) or {}).get("group") or ""
        ol["term"] = {t: ctx.fx_carry(pair, days=n) for t, n in ctx.fx_tenors(pair)}
        rows.append(ol)
    return rows


def fam_fwdprem(ctx: Ctx, usdtry_trend: Optional[Dict[str, Any]]) -> Tuple[List[Monitor], Dict[str, Any]]:
    win = ctx.window()
    mons: List[Monitor] = []
    mons_by: Dict[str, Monitor] = {}
    rows = []
    for pair, tenor, n in FWD_TENORS:
        fk = "FWD:%s:%s" % (pair, tenor)
        sk = "FX:" + pair
        if fk not in ctx.series or not ctx.has(sk, n + 40):
            continue
        spot = ctx.pts(sk)
        sd_days = [d for d, _ in spot]
        sv = [v for _, v in spot]
        rets = [math.log(b / a) * 100.0 if a > 0 and b > 0 else 0.0 for a, b in zip(sv, sv[1:])]
        # the forecast drift: the EWMA (λ 0.97, a half-life of about 23 days) of the daily log returns, a year's worth,
        # shrunk towards zero by its own precision (shrunk_mean): a drift that is noise is no forecast
        drift: Dict[str, float] = ewma_drift(rets, sd_days[1:])
        realized = {sd_days[i]: (math.log(sv[i] / sv[i - n])) * 252.0 / n * 100.0 for i in range(n, len(sv))}
        days_t = _tenor_days(tenor)
        f = ctx.series[fk]
        s = ctx.series[sk]
        imp = {d: (f[d] / s[d] - 1.0) * 365.0 / days_t * 100.0 for d in f if s.get(d)}
        days = sorted(d for d in imp if d in drift)[-win:]
        cushion = [imp[d] - drift[d] for d in days]
        row = {"pair": pair, "tenor": tenor, "implied": None, "realized": realized.get(sd_days[-1]), "forecast": drift.get(sd_days[-1]), "n": len(days)}
        last_drift = drift.get(sd_days[-1])

        def implied_now(live, fk=fk, sk=sk, days_t=days_t):
            fv, svv = ctx.cur(fk, live), ctx.cur(sk, live)
            return (fv / svv - 1.0) * 365.0 / days_t * 100.0 if fv and svv else None

        row["implied"] = implied_now(ctx.live)

        def calc(live, last_drift=last_drift, implied_now=implied_now):
            i = implied_now(live)
            return i - last_drift if i is not None and last_drift is not None else None

        def gate(s, pair=pair):
            tr = usdtry_trend if pair == "USDTRY" else None
            if not tr or tr.get("regime") != "Trend":
                return 1.0, ""
            if s < 0 and tr.get("score", 0) > 0:
                return 0.0, "USDTRY yukarı trendde: carry (TRY alma) bekletilir"
            if s > 0 and tr.get("score", 0) < 0:
                return 0.0, "USDTRY aşağı trendde: forward alımı bekletilir"
            return 1.0, ""

        legs = [{"key": "FX:" + pair, "name": "%s %s forward" % (pair, tenor), "weight": 1.0}]
        ol = fx_outlook(ctx, pair)
        sid = "fwdprem:%s:%s" % (pair, tenor)

        def fexpect(side, hold, sid=sid):
            # holding the forward: a short earns the premium the forward prices less the drift (the cushion), a long the reverse
            m = mons_by.get(sid)
            cushion_now = m.level if m is not None and m.level is not None else None
            return -side * cushion_now * hold * 7.0 / 5.0 / 365.0 if cushion_now is not None else None

        def fthesis(sg, pair=pair, tenor=tenor):
            i = (sg.get("info") or {})
            return ("%s %s forward'ı yıllık %%%s kur artışı fiyatlıyor, beklenen artış yıllık %%%s (günlük getirilerin EWMA'sı, kesinliğiyle "
                    "küçültülmüş): forward artışı %s fiyatlıyor, tampon %s puan (z %s) → %s; beklenen %s%s." % (
                        pair, _tenor_en(tenor), _g(i.get("implied"), 1), _g(i.get("drift"), 1), "fazla" if (sg["level"] or 0) > 0 else "az",
                        _sg(sg["level"], 1), _sg(sg["z"], 2), sg["expression"], exp_text(sg), _incl(sg)))

        def fprice(c, fx, last_drift=last_drift, days_t=days_t):
            # the forward the premium stands for, the spot as it is now: S × (1 + (drift + cushion) × days / 365)
            sp = fx.get("spot")
            return sp * (1.0 + (last_drift + c) / 100.0 * days_t / 365.0) if sp and last_drift is not None else None

        mon = mr_monitor(ctx, sid, "fwdprem", "FX", "%s %s forward" % (pair, tenor), "%", 2, days, cushion, "bp",
                         legs, calc, pkg="fx", gate=gate, gate_name="USDTRY trendi", info={"inputs": [fk, sk], "implied": row["implied"], "drift": last_drift},
                         fx=pair, expect=fexpect, thesis=fthesis, pnl=("%", None), pnl_sd=(ol or {}).get("daily_sd"),
                         price=fprice, inst="%s %s forward" % (pair, _tenor_en(tenor)), inst_days=days_t, pct_base="spot",
                         series_label="Tampon: forward'ın fiyatladığı yıllık kur artışı − beklenen artış (yüzde puan)",
                         note="Forward'ın ima ettiği yıllık değer kaybı − beklenen kayma (günlük getirilerin EWMA'sı, λ 0,97, yıllık, kesinliğiyle "
                              "küçültülmüş): + ise forward değer kaybını fazla fiyatlıyor → carry lehine (%s forward sat); − ise tersi. Beklenen: "
                              "tamponun tutma süresine düşen payı - forward primi eksi beklenen kur hareketi. Hedef / stop fiyatları: tampon oraya "
                              "gelince forward, spot bugünkü yerindeyken. USDTRY'nin forward pozisyonu trendde ise sinyal bekletilir." % pair)
        if mon is not None:
            mon.kind = "carry"
            mons_by[sid] = mon
            row.update({"cushion": cushion[-1], "z": mon.zof(cushion[-1]), "half_life": mon.half_life, "sid": mon.sid})
            mons.append(mon)
        rows.append(row)
    return mons, {"rows": rows}


# ---------------------------------------------------------------------------------------------- r. forecast model
MODEL_UNIVERSE = ("OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y", "XR:USDTRY", "CDS", "UST:10Y")
MODEL_FEATURES = ("z60", "mom1h", "mom1a", "carry", "rejim", "vol")
MODEL_STEP = 5                          # a week: the label's horizon and the step between test points
MODEL_REFIT = 4                         # refit every 4 test points (four weeks)


def model_features(values: List[float], kind: str, carry: List[Optional[float]]) -> List[Optional[List[float]]]:
    """Each day's features from the closes up to that day only: z of the level over 60 days, the 1W and 1M changes over
    volatility, carry, regime (the first-order autocorrelation of the last 60 changes) and volatility (log of the 20-day
    over the 120-day one)."""
    n = len(values)
    ch = [0.0] + diffs(kind, values)
    out: List[Optional[List[float]]] = [None] * n
    for t in range(125, n):
        win = values[t - 59:t + 1]
        sd_l = qm.stdev(win)
        c60 = ch[t - 59:t + 1]
        sd = qm.stdev(c60)
        sd20, sd120 = qm.stdev(ch[t - 19:t + 1]), qm.stdev(ch[t - 119:t + 1])
        if not sd_l or not sd or not sd20 or not sd120:
            continue
        m1w = change(kind, values[t - 5], values[t])
        m1m = change(kind, values[t - 21], values[t])
        if m1w is None or m1m is None:
            continue
        rho = qm.corr(c60[:-1], c60[1:]) or 0.0
        out[t] = [(values[t] - sum(win) / 60.0) / sd_l, m1w / (sd * math.sqrt(5)), m1m / (sd * math.sqrt(21)),
                  carry[t] if carry[t] is not None else 0.0, rho, math.log(sd20 / sd120)]
    return out


def _standardize(rows: List[List[float]]) -> Tuple[List[float], List[float]]:
    k = len(rows[0])
    means = [sum(r[j] for r in rows) / len(rows) for j in range(k)]
    sds = []
    for j in range(k):
        v = sum((r[j] - means[j]) ** 2 for r in rows) / max(1, len(rows) - 1)
        sds.append(math.sqrt(v) if v > 1e-18 else 0.0)
    return means, sds


def _scaled(row: List[float], means: List[float], sds: List[float]) -> List[float]:
    return [(row[j] - means[j]) / sds[j] if sds[j] else 0.0 for j in range(len(row))]


def walk_forward(feats: List[Optional[List[float]]], labels: List[Optional[int]], train: int, min_train: int, l2: float) -> Dict[str, Any]:
    """Rolling out-of-sample test: at test day T (every week) the model is fitted on the ``train`` samples whose label
    was known by T (t + 5 ≤ T) - nothing after T is used, the features standardised with the training sample's own
    means - and predicts T's direction; refitted every four weeks.  Returns the test points and the hit rate /
    log-loss over them."""
    n = len(feats)
    idx = [t for t in range(n) if feats[t] is not None]
    if not idx:
        return {"n": 0, "tests": []}
    first = idx[0]
    tests = []
    coef = None
    norm = None
    k = 0
    T = first + min_train + MODEL_STEP
    while T < n:
        if feats[T] is not None and labels[T] is not None:
            if coef is None or k % MODEL_REFIT == 0:
                lo = max(first, T - MODEL_STEP - train + 1)
                sample = [t for t in range(lo, T - MODEL_STEP + 1) if feats[t] is not None and labels[t] is not None]
                if len(sample) >= min_train // 2:
                    rows = [feats[t] for t in sample]
                    means, sds = _standardize(rows)
                    fitted = qm.logistic_fit([_scaled(r, means, sds) for r in rows], [labels[t] for t in sample], l2, 12, coef)
                    if fitted is not None:
                        coef, norm = fitted, (means, sds)
            if coef is not None:
                p = qm.logistic_prob(coef, _scaled(feats[T], *norm))
                tests.append((T, p, labels[T]))
                k += 1
        T += MODEL_STEP
    hits = sum(1 for _, p, y in tests if (p > 0.5) == (y == 1))
    return {"n": len(tests), "hits": hits, "hit_rate": hits / len(tests) if tests else None,
            "log_loss": qm.log_loss([p for _, p, _ in tests], [y for _, _, y in tests]),
            "base_rate": sum(y for _, _, y in tests) / len(tests) if tests else None, "tests": tests}


def fam_model(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    cfg = ctx.cfg
    train = int(cfg["lookback"])
    min_train = int(cfg["min_obs"])
    l2 = float(cfg["model_l2"])
    mons: List[Monitor] = []
    rows = []
    tl = ctx.series.get("TLREF") or {}
    for key in MODEL_UNIVERSE:
        pts = ctx.pts(key)
        fx = key[3:] if key.startswith("XR:") else None
        if fx and not pts and ctx.has("FX:" + fx):
            rows.append({"key": key, "label": fx, "error": "forward yok: carry hesaplanamadı"})
            continue
        if len(pts) < 125 + min_train + 2 * MODEL_STEP:
            if pts:
                rows.append({"key": key, "label": fx or ctx.label(key), "error": "geçmiş kısa (%d kapanış)" % len(pts)})
            continue
        kind = ctx.kind(key)
        days = [d for d, _ in pts]
        values = [v for _, v in pts]
        if key.startswith("OIS:"):
            tls = sorted(tl.items())
            carry = []
            j = 0
            last_tl = None
            for d, v in pts:
                while j < len(tls) and tls[j][0] <= d:
                    last_tl = tls[j][1]
                    j += 1
                carry.append((v - last_tl) * 100.0 if last_tl is not None else None)
        elif fx:
            cs = ctx.fx_carry_days(fx)                   # the carry of a long, annualised: the trade's own
            carry = [cs.get(d) for d in days]
        else:
            carry = [None] * len(days)
        feats = model_features(values, kind, carry)
        labels: List[Optional[int]] = [None] * len(values)
        for t in range(len(values) - MODEL_STEP):
            c = change(kind, values[t], values[t + MODEL_STEP])
            if c is not None and c != 0:
                labels[t] = 1 if c > 0 else 0
        wf = walk_forward(feats, labels, train, min_train, l2)
        # the model of today: the latest window whose labels are known
        sample = [t for t in range(max(0, len(values) - MODEL_STEP - train), len(values) - MODEL_STEP) if feats[t] is not None and labels[t] is not None]
        row = {"key": key, "label": fx or ctx.label(key), "n_test": wf["n"], "hit_rate": wf.get("hit_rate"), "log_loss": wf.get("log_loss"),
               "base_rate": wf.get("base_rate"), "features": list(MODEL_FEATURES)}
        if len(sample) < min_train // 2 or feats[-1] is None:
            row["error"] = "eğitim örneği az"
            rows.append(row)
            continue
        srows = [feats[t] for t in sample]
        means, sds = _standardize(srows)
        coef = qm.logistic_fit([_scaled(r, means, sds) for r in srows], [labels[t] for t in sample], l2, 25)
        if coef is None:
            row["error"] = "model kurulamadı"
            rows.append(row)
            continue
        p_now = qm.logistic_prob(coef, _scaled(feats[-1], means, sds))
        row.update({"coef": coef, "p": p_now, "means": means, "sds": sds})
        valid = (wf.get("hit_rate") or 0.0) >= float(cfg["model_hit"]) and wf["n"] >= int(cfg["model_min_tests"])
        row["valid"] = valid
        rows.append(row)
        steps = [b - a for a, b in zip(values, values[1:])]
        sd = qm.stdev(steps[-60:]) or 0.0
        level = ctx.cur(key)
        # what a week is expected to bring: (2p − 1) × the average size of a week's move (level units)
        week = [abs(values[t + MODEL_STEP] - values[t]) for t in range(max(0, len(values) - 250), len(values) - MODEL_STEP)]
        size = sum(week) / len(week) if week else 0.0
        explain = " · ".join("%s %s%s" % (name, "+" if c >= 0 else "−", _f2(abs(c))) for name, c in zip(MODEL_FEATURES, coef[1:]))
        legs = [{"key": "FX:" + fx, "name": "%s forward" % fx, "weight": 1.0}] if fx else [{"key": key, "name": ctx.label(key), "weight": 1.0}]

        def mthesis(sg, p_now=p_now, wf=wf, fx=fx):
            what = ("gelecek hafta %s'nin forward'ların fiyatladığından iyi gitme (forward'la alanın kazanma)" % fx if fx
                    else "gelecek haftanın yukarı yönlü olma")
            return ("Lojistik model %s olasılığını %%%s veriyor (kayan pencereli doğrulamada isabet %%%s, %d test)%s → %s; beklenen %s%s." % (
                what, _f1(p_now * 100), _f1((wf.get("hit_rate") or 0) * 100), wf["n"],
                "" if not fx else "; forward primi işlemin %s (yıllık %%%s)" % ("lehine" if (sg.get("carry_yr") or 0) >= 0 else "aleyhine",
                                                                              _sg(sg.get("carry_yr"), 1)),
                sg["expression"], exp_text(sg), _incl(sg)))

        mon = Monitor("model:" + key, "model", _asset_of("FX:" if fx else key), "%s forward" % fx if fx else ctx.label(key), level_unit(kind),
                      3 if kind in ("rate", "xr") else 4, days[-ctx.window():],
                      values[-ctx.window():], legs, lambda live, key=key: ctx.cur(key, live),
                      zfn=lambda level, live, p_now=p_now: (p_now - 0.5) / 0.05, follows=True, mode="drift",
                      reward=sd * math.sqrt(MODEL_STEP), risk=sd * math.sqrt(MODEL_STEP),
                      hold=float(MODEL_STEP), regime={"tag": None}, pkg={"rate": "rate", "bp": "cds", "fx": "fx", "xr": "fx"}.get(kind, "fx"),
                      carry_up=None if fx else ctx.carry_week(key), score_name="z(p)", fx=fx, dsd=sd, pnl=pnl_scale(kind, level),
                      fcast=(2.0 * p_now - 1.0) * size, thesis=mthesis, series_label=xr_label(fx) if fx else None,
                      info={"p": p_now, "hit_rate": wf.get("hit_rate"), "n_test": wf["n"], "log_loss": wf.get("log_loss"), "valid": valid,
                            "coef": dict(zip(MODEL_FEATURES, coef[1:]))},
                      note="Gelecek haftanın yönü için L2 lojistik regresyon (özellikler standart: %s). Yukarı olasılığı %%%s; kayan "
                           "pencereli doğrulamada isabet %%%s (%d test, log-loss %s). z = (p − 0,5) / 0,05. Beklenen: (2p − 1) × bir haftalık "
                           "hareketin ortalama büyüklüğü.%s" % (
                               explain, _f1(p_now * 100), _f1((wf.get("hit_rate") or 0) * 100), wf["n"], _f2(wf.get("log_loss")),
                               " FX: etiket ve analiz serisi forward pozisyonunun getirisi (kur değişimi − forward primi); işlem 1 haftalık "
                               "forward'la, fiyatları ve 1 mn baz döviz başına K/Z yukarıda." if fx else ""))
        if key.startswith("UST:"):
            mon.pkg = "bond"
        mon.zvalues = [None] * len(mon.values)
        if valid:
            mons.append(mon)
        else:
            row["why"] = "doğrulanmış isabet eşiğin altında" if wf["n"] >= int(cfg["model_min_tests"]) else "test noktası az"
    return mons, {"rows": rows, "features": list(MODEL_FEATURES), "step": MODEL_STEP, "refit": MODEL_REFIT}


def _f1(v: Optional[float]) -> str:
    return ("%.1f" % v).replace(".", ",") if v is not None else "—"


# ================================================================================================ the rationale of a signal
ANALOG_K = 10                            # the nearest days shown
ANALOG_GAP = 5                           # business days between two analogs (a week of the same episode is one analog)
ANALOG_FEATURES = ("z", "eğim", "rejim", "vol", "carry")
ANALOG_Z_WEIGHT = 2.0                    # the squared distance in z counts twice: the score is what the signal is about


def analog_features(values: Sequence[float], zs: Optional[Sequence[Optional[float]]] = None,
                    carry: Optional[Sequence[Optional[float]]] = None) -> List[Optional[List[float]]]:
    """Each day's description, from the closes up to it: z (the signal's own where it keeps one, else the level's over 60
    days), slope (the week's move over the daily σ × √5), regime (the lag-1 autocorrelation of the last 60 daily moves),
    vol (the log of the 20-day σ over the 60-day one) and, where there is one, the carry."""
    n = len(values)
    ch = [0.0] + [b - a for a, b in zip(values, values[1:])]
    out: List[Optional[List[float]]] = [None] * n
    for t in range(60, n):
        sd = qm.stdev(ch[t - 59:t + 1])
        sd20 = qm.stdev(ch[t - 19:t + 1])
        if not sd or not sd20:
            continue
        z = zs[t] if zs is not None and t < len(zs) and zs[t] is not None else None
        if z is None:
            w = values[t - 59:t + 1]
            s_ = qm.stdev(w)
            z = (values[t] - sum(w) / len(w)) / s_ if s_ else 0.0
        rho = qm.corr(ch[t - 59:t], ch[t - 58:t + 1]) or 0.0
        f = [z, (values[t] - values[t - 5]) / (sd * math.sqrt(5.0)), rho, math.log(sd20 / sd)]
        if carry is not None:
            c = carry[t] if t < len(carry) else None
            if c is None:
                continue
            f.append(c)
        out[t] = f
    return out


def _bdays_between(a: _dt.date, b: _dt.date, holidays: set) -> int:
    n, d = 0, a
    while d < b:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            n += 1
    return n


def rationale(ctx: Ctx, m: Monitor, sg: Optional[Dict[str, Any]], cfg: Dict[str, Any], k: int = ANALOG_K) -> Dict[str, Any]:
    """Why the signal: the ``k`` past days most like today (z, slope, regime, vol, carry - standardised, Euclidean, z
    counting twice, a week apart at least) and what the level did over the holding after each (in the trade's direction, P&L units;
    an FX trade's level is its excess return - carry in it -, a rate package's move is without its carry), and the conditions that undo it: the stop, a change of regime, an event inside the horizon."""
    out: Dict[str, Any] = {"analogs": [], "summary": None, "invalidation": [], "features": list(ANALOG_FEATURES[:4])}
    values, days = list(m.values), list(m.days)
    if m.intraday or len(values) < 80 or m.level is None:
        out["why"] = "benzer gün için seri kısa" if not m.intraday else "gün içi sinyal: benzer gün aranmaz"
        return out
    hold = int(round((sg or {}).get("hold") or m.hold or float(cfg.get("horizon") or 20)))
    hold = max(1, min(hold, 60))
    s = (sg or {}).get("direction") or (sign(m.z or 0) if m.follows else -sign(m.z or 0))
    unit, factor = m.pnl or (None, None)
    factor = factor or 1.0
    zh = m.z_history()
    carry = None
    if m.fx:
        cd = ctx.fx_carry_days(m.fx)
        carry = [cd.get(d) for d in days]
        out["features"].append("carry")
    feats = analog_features(values + [m.level], zh + [m.z], carry + [(m.fxinfo or {}).get("carry_yr")] if carry is not None else None)
    now = feats[-1]
    usable = [t for t in range(len(values) - hold) if feats[t] is not None]
    if now is None or len(usable) < 2 * k:
        out["why"] = "benzer gün için geçmiş kısa (%d gün)" % len(usable)
        return out
    dim = len(now)
    means = [sum(feats[t][j] for t in usable) / len(usable) for j in range(dim)]
    sds = []
    for j in range(dim):
        v = sum((feats[t][j] - means[j]) ** 2 for t in usable) / max(1, len(usable) - 1)
        sds.append(math.sqrt(v) if v > 1e-18 else 1.0)
    wts = [ANALOG_Z_WEIGHT] + [1.0] * (dim - 1)              # the signal's own score counts double
    dist = sorted((math.sqrt(sum(wts[j] * ((feats[t][j] - now[j]) / sds[j]) ** 2 for j in range(dim))), t) for t in usable)
    picked: List[int] = []
    for _, t in dist:
        if all(abs(t - u) >= ANALOG_GAP for u in picked):
            picked.append(t)
        if len(picked) >= k:
            break
    # what an outcome is in money, where the level moves in P&L units: an FX trade per 1 mn of its base currency (the
    # instrument's price the signal's), a rates package in TL of its main leg's DV01
    mo = (sg or {}).get("money") or {}
    conv: Optional[Callable[[float], float]] = None
    if (m.pnl or (None, None))[1]:
        if (sg or {}).get("px") and mo.get("ref"):
            conv = lambda x: pct_money(x, s, mo["ref"], mo["log"])               # noqa: E731
        elif mo.get("per_bp"):
            conv = lambda x: x * mo["per_bp"]                                   # noqa: E731
    outcomes = []
    for t in sorted(picked, key=lambda x: -x):
        res = s * (values[t + hold] - values[t]) * factor
        outcomes.append(res)
        out["analogs"].append({"day": days[t], "features": feats[t], "distance": next(dd for dd, tt in dist if tt == t), "outcome": res,
                               "level": values[t], "end": days[t + hold], "money": conv(res) if conv else None})
    srt = sorted(outcomes)
    n = len(srt)
    out["summary"] = {"n": n, "hits": sum(1 for x in srt if x > 0), "share": sum(1 for x in srt if x > 0) / n if n else None,
                      "mean": sum(srt) / n if n else None, "median": srt[n // 2] if n else None,
                      "q25": srt[max(0, n // 4)] if n else None, "q75": srt[min(n - 1, (3 * n) // 4)] if n else None,
                      "hold": hold, "unit": unit, "now": now, "carry_in": bool(m.fx)}
    sm = out["summary"]
    if conv and n:
        sm["money"] = dict({k: conv(sm[k]) for k in ("mean", "median", "q25", "q75")}, ccy=mo["ccy"], base=mo.get("base"))
    # ---- what undoes it
    inv = []
    px = (sg or {}).get("px")
    if sg and px and px.get("stop") is not None:
        inv.append("Stop: %s %s (giriş %s)%s" % (px["inst"], _th(px["stop"], px["digits"]), _th(px["entry"], px["digits"]),
                                                 " - |z| %s" % _g(float(cfg["stop_z"]), 1) if m.mode == "mr" else ""))
    elif sg and sg.get("stop") is not None:
        inv.append("Stop: seviye %s (giriş %s)%s" % (_level_text(sg["stop"], m.unit, m.digits) + sheet_text(sg, sg["stop"], True),
                                                     _level_text(sg["entry"], m.unit, m.digits) + sheet_text(sg, sg["entry"], True),
                                                     " - |z| %s" % _g(float(cfg["stop_z"]), 1) if m.mode == "mr" else ""))
    reg = m.regime or {}
    if m.kind in ("mr", "surprise"):
        inv.append("Rejim trende dönerse (varyans oranı z ≥ +%s; şimdi %s)" % (_g(Z_REGIME, 3), _sg(reg.get("vr_z"), 2)))
    elif m.kind == "trend":
        inv.append("Rejim ortalamaya dönüşe dönerse (varyans oranı z ≤ −%s; şimdi %s) ya da ortalamalar ters keserse" % (
            _g(Z_REGIME, 3), _sg(reg.get("vr_z"), 2)))
    if m.half_life:
        inv.append("Yarı ömür ufkun %s katını aşarsa (şimdi %s gün)" % (_g(float(cfg["hl_max_mult"]), 0), _g(m.half_life, 1)))
    if m.fx and (sg or {}).get("carry_yr") is not None:
        inv.append("Forward primi tersine dönerse (şimdi işlemin %s: yıllık %%%s)" % ("lehine" if sg["carry_yr"] >= 0 else "aleyhine",
                                                                                     _sg(sg["carry_yr"], 1)))
    if m.family in ("pairs", "kalman"):
        inv.append("Eşbütünleşme bozulursa (kalıntıya ADF %5'i geçemezse)")
    if m.family == "model":
        inv.append("Kayan pencereli doğrulamada isabet eşiğin altına düşerse")
    # events inside the horizon: the coming PPK meetings (today's path), holidays
    end = ctx.today
    left = hold
    while left > 0:
        end += _dt.timedelta(days=1)
        if end.weekday() < 5 and end not in ctx.holidays:
            left -= 1
    meetings = [d for d, _ in ((ctx.path or {}).get("steps") or []) if ctx.today <= d <= end]
    for d in meetings:
        inv.append("PPK toplantısı %s ufkun içinde (%d. iş günü): karar fiyatlanandan ayrılırsa" % (
            _tr(d.isoformat()), _bdays_between(ctx.today, d, ctx.holidays)))
    hol = sorted(d for d in ctx.holidays if ctx.today < d <= end and d.weekday() < 5)
    if hol:
        inv.append("Ufukta tatil: %s (işlem günü az)" % ", ".join(_tr(d.isoformat()) for d in hol))
    out["invalidation"] = inv
    return out


# ================================================================================================ everything
def run_all(ctx: Ctx, rv_items: List[Dict[str, Any]], timing: Optional[Dict[str, float]] = None,
            pause: Optional[Callable[[], None]] = None) -> Tuple[List[Monitor], Dict[str, Any]]:
    """Every family on one context: the monitors and each page's tables.  ``pause`` is called between families (the
    worker lets the engine thread have the interpreter)."""
    timing = timing if timing is not None else {}
    tables: Dict[str, Any] = {}
    mons: List[Monitor] = []
    errors: Dict[str, str] = {}

    def step(name: str, fn: Callable[[], Tuple[List[Monitor], Any]]) -> Any:
        t0 = time.perf_counter()
        try:
            m, t = fn()
            mons.extend(m)
            tables[name] = t
        except Exception as exc:  # noqa: BLE001 - one family failing must not take the others with it
            errors[name] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            tables[name] = {"ok": False, "why": errors[name], "rows": []}
        timing[name] = time.perf_counter() - t0
        if pause is not None:
            pause()
        return tables.get(name)

    fit = None
    t0 = time.perf_counter()
    try:
        fit = pca_fit(ctx)
    except Exception as exc:  # noqa: BLE001
        errors["pca"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    timing["pca_fit"] = time.perf_counter() - t0
    step("corr", lambda: fam_corr(ctx))
    step("pca", lambda: fam_pca(ctx, fit))
    step("rv", lambda: fam_rv(ctx, fit, rv_items))
    step("frapath", lambda: fam_frapath(ctx))
    step("macro", lambda: fam_macro(ctx))
    step("pairs", lambda: fam_pairs(ctx))
    step("viopcal", lambda: fam_viopcal(ctx))
    step("momentum", lambda: fam_momentum(ctx))
    step("cycle", lambda: fam_cycle(ctx))
    step("vol", lambda: fam_vol(ctx))
    step("emcarry", lambda: fam_emcarry(ctx))
    usd = next((r for r in (tables.get("momentum") or {}).get("rows", []) if r["key"] in ("XR:USDTRY", "FX:USDTRY") and r.get("score") is not None), None)
    step("fwdprem", lambda: fam_fwdprem(ctx, usd))
    step("model", lambda: fam_model(ctx))
    tables["regime"] = regime_table(ctx, mons)
    tables["errors"] = errors
    return mons, tables


def score_all(ctx: Ctx, mons: List[Monitor], raw_live: Dict[str, float]) -> None:
    live = ctx.derive_live(raw_live)
    size_monitors(ctx, mons)
    for m in mons:
        m.score(live, raw_live)
        if m.family == "macro":
            macro_levels(m, ctx.cfg)
        if m.fx:
            # the carry over the signal's own holding (a mean reversion's: from its half-life and z, as make_signal has it)
            hold = hold_of(m)
            try:
                m.fxinfo = fx_info(ctx, m.fx, live, hold, cal_days=(hold or 12.0) * 5.0 / 1440.0 if m.intraday else None)
            except Exception:  # noqa: BLE001 - a carry that cannot be read is told as missing
                m.fxinfo = {"pair": m.fx}
