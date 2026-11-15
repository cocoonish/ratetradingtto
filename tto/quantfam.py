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
#: unexplained move, "corr" on a correlation coming back
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
#: how a level moves: rate (per cent, moves in bp), bp, vol / pts (moves as they are), fx / index (moves in % log)
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
    return {"rate": "bp", "fx": "%", "index": "%", "vol": "vol", "pts": "puan"}.get(kind, "bp")


def level_unit(kind: str) -> str:
    return {"rate": "%", "bp": "bp", "vol": "vol", "pts": "puan"}.get(kind, "")


# ---------------------------------------------------------------------------------------------- what the families read
class Ctx(object):
    """The closes before today (``series``: key -> {ISO day: value}), what each key is (``meta``: label, kind, months,
    group …), the values now (``live``), the settings (``cfg``) and the extras some families need: the VİOP history
    (``viop``), carry + roll per OIS tenor (``carry``: months -> bp a week, receiver), the meeting-pricing history
    (``mpc``) and today's meeting path (``path``)."""

    def __init__(self, cfg: Dict[str, Any], today: _dt.date, series: Dict[str, Dict[str, float]], meta: Dict[str, Dict[str, Any]],
                 live: Optional[Dict[str, float]] = None, viop: Optional[List[Dict[str, Any]]] = None,
                 carry: Optional[Dict[float, float]] = None, mpc: Optional[Dict[str, Any]] = None, path: Optional[Dict[str, Any]] = None,
                 holidays: Optional[set] = None, fwd_scale: Optional[Dict[str, int]] = None):
        self.cfg = cfg
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


def leg_text(leg: Dict[str, Any], side: int) -> str:
    up, down = _verbs(leg["key"])
    return "%s %s" % (up if side > 0 else down, leg["name"])


def fmt_w(w: float) -> str:
    return ("%.2f" % abs(w)).replace(".", ",")


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


def hl_factor(kind: str, hl: Optional[float], cfg: Dict[str, Any]) -> Tuple[float, str]:
    if kind not in ("mr", "corr"):
        return 1.0, ""
    horizon = float(cfg["horizon"])
    if hl is None:
        return 0.0, "ortalamaya dönmüyor (AR(1) katsayısı 0 – 1 dışında)"
    if hl <= horizon:
        return 1.0, ""
    if hl <= float(cfg["hl_max_mult"]) * horizon:
        return horizon / hl, ""
    return 0.0, "yarı ömür %.0f gün: ufkun (%d gün) %g katından uzun" % (hl, int(horizon), float(cfg["hl_max_mult"]))


def make_signal(m: Monitor, cfg: Dict[str, Any], stamp: str) -> Optional[Dict[str, Any]]:
    """A monitor past its entry threshold as a signal of the common format (``None`` below it)."""
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
    if m.mode == "mr" and m.mean is not None and m.sd:
        target = m.inv(m.mean + zs * target_z * m.sd)
        stop = m.inv(m.mean + zs * stop_z * m.sd)
        scale = m.sd
        if abs(m.z) >= stop_z:
            gated = "stop bölgesinde (|z| ≥ %s)" % ("%g" % stop_z).replace(".", ",")
    else:
        target = m.level + s * (m.reward or 0.0)
        stop = m.level - s * (m.risk or 0.0)
        scale = m.risk or None
    legs = []
    for leg in m.legs:
        side = sign(pkg_s * leg.get("weight", 1.0))
        legs.append({"key": leg["key"], "name": leg["name"], "weight": abs(leg.get("weight", 1.0)), "side": side,
                     "text": leg_text(leg, side) + ("" if abs(abs(leg.get("weight", 1.0)) - 1.0) < 1e-9 else " ×" + fmt_w(leg.get("weight", 1.0))),
                     "dv01": leg.get("dv01"), "notional": leg.get("notional")})
    if m.pkg in PKG_VERBS:
        up, down = PKG_VERBS[m.pkg]
        expression = "%s %s" % (up if pkg_s > 0 else down, m.name)
    elif m.pkg == "corr":
        expression = "Korelasyon normale döner: %s · %s" % (m.name, " / ".join(l["text"] for l in legs))
    else:
        expression = " / ".join(l["text"] for l in legs)
    rf, why_r = regime_factor(m.kind, (m.regime or {}).get("tag"))
    hf, why_h = hl_factor(m.kind, m.half_life, cfg)
    if m.gate is not None:
        g, why_g = m.gate(pkg_s)
        if g == 0.0:
            rf, why_r = 0.0, why_g
    carry = pkg_s * m.carry_up if m.carry_up is not None else None
    cf = 0.5 if carry is not None and carry < 0 else 1.0
    # |z| on the desk's scale (a family with its own threshold is brought to it), counted at most up to the stop: no
    # family's score can outrank the others by its scale alone
    base = min(abs(m.z) * float(cfg["entry_z"]) / thr, stop_z)
    composite = base * rf * hf * cf
    gated = gated or why_r or why_h
    hold = m.hold
    if hold is None and m.half_life:
        hold = m.half_life * max(1.0, math.log(abs(m.z) / 0.5, 2))        # expected z falls to 0.5
    return {"id": m.sid, "family": m.family, "family_label": FAMILIES[m.family][0], "page": FAMILIES[m.family][2], "kind": m.kind,
            "asset": m.asset, "instrument": m.name, "expression": expression, "legs": legs, "direction": s, "z": m.z,
            "score_name": m.score_name, "entry_z": thr, "strength": strength(abs(m.z) / thr), "level": m.level, "unit": m.unit,
            "digits": m.digits, "entry": m.level, "target": target, "stop": stop, "scale": scale, "target_z": target_z, "stop_z": stop_z,
            "mode": m.mode, "half_life": m.half_life, "hold": hold, "carry_week": carry,
            "regime": REGIME_TEXT.get((m.regime or {}).get("tag")), "regime_info": m.regime, "composite": 0.0 if gated else composite,
            "parts": {"z": base, "regime": rf, "hl": hf, "carry": cf}, "gated": gated, "live": m.live, "time": stamp,
            "note": m.note, "info": {k: v for k, v in m.info.items() if k not in ("ou", "inputs")}, "agree": 0, "conflict": 0,
            "agree_with": [], "conflict_with": []}


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


def pca_fit(ctx: Ctx) -> Optional[Dict[str, Any]]:
    keys = ctx.ois_keys(min_months=1.0)
    keys, days, rows = _curve_matrix(ctx, keys, ctx.window() + 1)
    if len(keys) < 3 or len(days) < ctx.min_obs() + 1:
        return None
    chg = [[(rows[t][j] - rows[t - 1][j]) * 100.0 for j in range(len(keys))] for t in range(1, len(rows))]
    p = qm.pca(chg)
    if p is None:
        return None
    months = [ctx.months(k) for k in keys]
    vec = _pca_signs(p["vectors"], months)
    xbar = [sum(r[j] for r in rows) / len(rows) for j in range(len(keys))]
    return {"keys": keys, "days": days, "rows": rows, "changes": chg, "values": p["values"][:3], "vectors": vec,
            "explained": p["explained"][:3], "mean_change": p["means"], "xbar": xbar, "months": months}


def _proj(vec: List[float], d: List[float]) -> float:
    return sum(a * b for a, b in zip(vec, d))


def fam_pca(ctx: Ctx, fit: Optional[Dict[str, Any]]) -> Tuple[List[Monitor], Dict[str, Any]]:
    if fit is None:
        return [], {"ok": False, "why": "PCA için en az 3 OIS vadesinde %d ortak gün gerekli" % (ctx.min_obs() + 1)}
    keys, rows, vec, xbar = fit["keys"], fit["rows"], fit["vectors"], fit["xbar"]
    k = len(keys)
    e1, e2 = vec[0], vec[1]

    def dev(levels: List[float]) -> List[float]:
        return [(levels[j] - xbar[j]) * 100.0 for j in range(k)]

    def resid(levels: List[float]) -> List[float]:
        d = dev(levels)
        f1, f2 = _proj(e1, d), _proj(e2, d)
        return [d[j] - f1 * e1[j] - f2 * e2[j] for j in range(k)]

    res = [resid(r) for r in rows]
    levels_now = lambda live: [ctx.cur(key, live) for key in keys]                       # noqa: E731
    mons: List[Monitor] = []
    table_rows = []
    for j, key in enumerate(keys):
        hedge = _hedges(keys, vec, j)
        series = [r[j] for r in res]

        def calc(live, j=j):
            lv = levels_now(live)
            if any(v is None for v in lv):
                return None
            return resid(lv)[j]

        legs = [{"key": key, "name": _ois_name(ctx, key), "weight": 1.0}] + [
            {"key": keys[h], "name": _ois_name(ctx, keys[h]), "weight": w} for h, w in hedge]
        carry = _pkg_carry(ctx, legs)
        mon = mr_monitor(ctx, "pca:" + key, "pca", "TRY OIS", "%s (PC1–PC2 hedge'li)" % _ois_name(ctx, key), "bp", 1, fit["days"], series,
                         "bp", legs, calc, carry_up=carry, pkg="rate",
                         note="PC1 (seviye) ve PC2 (eğim) çıkarıldıktan sonra kalan (bp): + ise tenor eğriye göre ucuz (yüksek faiz → receive), "
                              "− ise pahalı (pay). Hedge bacakları paketi PC1 ve PC2'ye nötr yapar.")
        row = {"key": key, "label": key.split(":", 1)[1], "loadings": [v[j] for v in vec], "resid": series[-1] if series else None}
        if mon is not None:
            mons.append(mon)
            row.update({"z_hist": mon.zof(series[-1]), "half_life": mon.half_life, "regime": (mon.regime or {}).get("tag"),
                        "hedge": [{"key": keys[h], "weight": w} for h, w in hedge]})
        table_rows.append(row)
    # today's move in factor terms and where the factors stand
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

    table = {"ok": True, "keys": keys, "labels": [x.split(":", 1)[1] for x in keys], "explained": fit["explained"],
             "values": fit["values"], "vectors": vec, "rows": table_rows, "days": len(fit["days"]), "first": fit["days"][0],
             "last": fit["days"][-1], "factors": factors, "names": ["PC1 · seviye", "PC2 · eğim", "PC3 · eğrilik"]}
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


def _annuity(par: float, months: float) -> float:
    """Annuity (years) of a par OIS from its own rate - one payment up to a year, annual coupons beyond (flat curve)."""
    r = par / 100.0
    if months <= 12:
        t = months / 12.0
        return t / (1.0 + r * t)
    years = int(round(months / 12.0))
    return sum(1.0 / (1.0 + r) ** i for i in range(1, years + 1))


def _pkg_name(tenors: List[str], kind: str) -> str:
    if all(t.upper().endswith("Y") for t in tenors):
        return "".join("%ss" % t[:-1] for t in tenors) + (" PCA-nötr fly" if kind == "fly" else " PC1-nötr spread")
    return "/".join(t.upper() for t in tenors) + (" PCA-nötr fly" if kind == "fly" else " PC1-nötr spread")


def fam_rv(ctx: Ctx, fit: Optional[Dict[str, Any]], items: List[Dict[str, Any]]) -> Tuple[List[Monitor], Dict[str, Any]]:
    if fit is None:
        return [], {"ok": False, "rows": []}
    keys, rows, vec = fit["keys"], fit["rows"], fit["vectors"]
    index = {key: j for j, key in enumerate(keys)}
    e1, e2 = vec[0], vec[1]
    base = float(ctx.cfg["dv01_base"])
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
        if it["kind"] == "spread":
            s_, l_ = js
            if not e1[s_]:
                continue
            weights = {l_: 1.0, s_: -e1[l_] / e1[s_]}
        else:
            w1_, b_, w2_ = js
            sol = qm.solve([[e1[w1_], e1[w2_]], [e2[w1_], e2[w2_]]], [-e1[b_], -e2[b_]])
            if sol is None:
                table.append({"label": it["label"], "error": "PC1/PC2 sistemi çözülemedi"})
                continue
            weights = {b_: 1.0, w1_: sol[0], w2_: sol[1]}
        series = [sum(w * r[j] for j, w in weights.items()) * 100.0 for r in rows]
        today = [ctx.cur(k_) for k_ in keys]
        legs = []
        for j, w in sorted(weights.items(), key=lambda x: fit["months"][x[0]]):
            par = today[j]
            ann = _annuity(par, fit["months"][j]) if par is not None else None
            dv01 = w * base
            legs.append({"key": keys[j], "name": _ois_name(ctx, keys[j]), "weight": w, "dv01": dv01,
                         "notional": abs(dv01) / (ann * 1e-4) / 1e6 if ann else None})

        def calc(live, weights=weights):
            lv = {j: ctx.cur(keys[j], live) for j in weights}
            if any(v is None for v in lv.values()):
                return None
            return sum(w * lv[j] for j, w in weights.items()) * 100.0

        name = _pkg_name(it["tenors"], it["kind"])
        mon = mr_monitor(ctx, "rv:%s:%s" % (it["kind"], "/".join(t.upper() for t in it["tenors"])), "rv", "TRY OIS", name, "bp", 1, fit["days"],
                         series, "bp", legs, calc, carry_up=_pkg_carry(ctx, legs), pkg="rate",
                         note=("Ağırlıklar PC1 ve PC2'ye nötr (gövde 1)" if it["kind"] == "fly" else "Ağırlıklar PC1'e nötr (uzun bacak 1)")
                         + "; DV01 cinsinden. + ise paket seviyesi yüksek (receive ile ortalamaya dönüş).")
        row = {"label": name, "kind": it["kind"], "tenors": it["tenors"], "legs": legs}
        if mon is not None:
            mons.append(mon)
            row.update({"level": series[-1], "z": mon.zof(series[-1]), "half_life": mon.half_life, "carry": mon.carry_up,
                        "regime": (mon.regime or {}).get("tag"), "sid": mon.sid})
        else:
            row["error"] = "gün sayısı az"
        table.append(row)
    return mons, {"ok": True, "rows": table}


# ---------------------------------------------------------------------------------------------- 4. macro betas
MACRO_TARGETS = ("OIS:3M", "OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y")
MACRO_DRIVERS = ("UST:2Y", "UST:10Y", "DXY", "EMFX", "BRENT", "CDS")


def fam_macro(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    drivers = [d for d in MACRO_DRIVERS if ctx.has(d, ctx.min_obs())]
    targets = [t for t in MACRO_TARGETS if ctx.has(t, ctx.min_obs())]
    rows = []
    mons: List[Monitor] = []
    if not drivers:
        return [], {"ok": False, "why": "küresel sürücülerin (UST, DXY, EM FX, Brent, CDS) geçmişi yok", "drivers": [], "rows": []}
    for t in targets:
        days, vals = aligned(ctx, [t] + drivers, ctx.window() + 1)
        if len(days) < ctx.min_obs() + 1:
            rows.append({"key": t, "label": _ois_name(ctx, t), "error": "ortak gün az (%d)" % len(days)})
            continue
        y = diffs("rate", vals[0])
        xs = [diffs(ctx.kind(d), vals[1 + i]) for i, d in enumerate(drivers)]
        r = qm.ols(y, xs)
        if r is None:
            rows.append({"key": t, "label": _ois_name(ctx, t), "error": "regresyon kurulamadı"})
            continue
        sigma = math.sqrt(r["sigma2"])
        coef = r["coef"]
        last = [v[-1] for v in vals]
        resid_hist = r["resid"]

        def attribution(live, t=t, last=last, coef=coef):
            now = [live.get(k) for k in [t] + drivers]
            if all(v is not None for v in now):
                dy = change("rate", last[0], now[0])
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
        row = {"key": t, "label": _ois_name(ctx, t), "n": r["n"], "r2": r["r2"], "alpha": coef[0], "sigma": sigma,
               "betas": coef[1:], "t": r["t"][1:], "today": cur, "z": (cur["resid"] / sigma) if cur and sigma else None}
        rows.append(row)
        reg = regime_of(vals[0], "rate", ctx.cfg)
        zh = [e / sigma for e in resid_hist] if sigma else None
        mon = Monitor("macro:" + t, "macro", "TRY OIS", _ois_name(ctx, t), "%", 3, days[1:][-ctx.window():], vals[0][1:][-ctx.window():],
                      [{"key": t, "name": _ois_name(ctx, t), "weight": 1.0}], lambda live, t=t: ctx.cur(t, live), zfn=zfn,
                      zvalues=zh[-ctx.window():] if zh else None, mode="drift", hold=5.0, regime=reg, pkg="rate",
                      carry_up=ctx.carry_week(t), info={"inputs": list(drivers)},
                      note="Bugünkü hareketin küresel sürücülerin (β × değişim) açıklamadığı kısmı: + ise TRY'ye özgü yükseliş (receive ile geri dönüş beklenir).")
        mon.reward = None
        mon.risk = None
        mon._sigma = sigma                       # type: ignore[attr-defined]
        mon._attr = attribution                  # type: ignore[attr-defined]
        mons.append(mon)
    labels = {"UST:2Y": "UST 2Y (bp)", "UST:10Y": "UST 10Y (bp)", "DXY": "DXY (%)", "EMFX": "EM FX (%)", "BRENT": "Brent (%)", "CDS": "CDS (bp)"}
    return mons, {"ok": True, "drivers": drivers, "driver_labels": [labels.get(d, d) for d in drivers], "rows": rows}


def macro_levels(m: Monitor, cfg: Dict[str, Any]) -> None:
    """Target and stop of a macro residual signal: the level the global move alone would give, and the level where the
    residual would be at the stop's z."""
    sigma = getattr(m, "_sigma", None)
    if m.z is None or not sigma:
        return
    m.reward = abs(m.z) * sigma / 100.0
    m.risk = max(float(cfg["stop_z"]) - abs(m.z), 0.5) * sigma / 100.0


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


def curve_df(spot: _dt.date, pillars: List[Tuple[_dt.date, float]], end: _dt.date) -> Optional[float]:
    """Discount factor to ``end`` from par OIS rates of one payment (≤ 1Y): log-linear between the pillars."""
    pts = [(0.0, 0.0)]
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
    """One day: each FRA bucket's forward and each coming meeting period's forward from the curve and from the meeting
    path (bp apart), and each tenor's par rate against the path's own."""
    pillars = sorted((_add_months(spot, m), r) for m, r in quotes.items())
    out: Dict[str, Any] = {"fra": {}, "tenor": {}, "mpc": {}}
    reach = max(d for d, _ in pillars) if pillars else spot
    for meeting, a, b in mpc_periods(spot, steps, reach):
        ca, cb = curve_df(spot, pillars, a), curve_df(spot, pillars, b)
        if ca is None or cb is None:
            continue
        pa, pb = path_df(spot, base, steps, a, holidays), path_df(spot, base, steps, b, holidays)
        fc = (ca / cb - 1.0) * 365.0 / (b - a).days
        fp = (pa / pb - 1.0) * 365.0 / (b - a).days
        out["mpc"][meeting.isoformat()] = {"start": a.isoformat(), "end": b.isoformat(), "curve": fc * 100.0, "path": fp * 100.0,
                                           "dev": (fc - fp) * 10000.0}
    for m1, m2 in FRA_BUCKETS:
        a, b = _add_months(spot, m1), _add_months(spot, m2)
        ca, cb = curve_df(spot, pillars, a), curve_df(spot, pillars, b)
        if ca is None or cb is None:
            continue
        pa, pb = path_df(spot, base, steps, a, holidays), path_df(spot, base, steps, b, holidays)
        fc = (ca / cb - 1.0) * 365.0 / (b - a).days
        fp = (pa / pb - 1.0) * 365.0 / (b - a).days
        out["fra"]["%dx%d" % (m1, m2)] = {"curve": fc * 100.0, "path": fp * 100.0, "dev": (fc - fp) * 10000.0}
    for m, r in quotes.items():
        e = _add_months(spot, m)
        pdf = path_df(spot, base, steps, e, holidays)
        par = (1.0 / pdf - 1.0) * 365.0 / (e - spot).days * 100.0
        out["tenor"][m] = {"quote": r, "path": par, "dev": (r - par) * 100.0}
    return out


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
    mpc_series: Dict[str, List[Tuple[str, float]]] = {}
    for d in sorted(by_day):
        meta = days_meta.get(d) or {}
        if d >= ctx.today_iso or meta.get("flag") in ("inconsistent", "error") or not meta.get("spot") or meta.get("base") is None:
            continue
        quotes = {m: ctx.series[k][d] for m, k in tenor_keys.items() if d in ctx.series[k]}
        if len(quotes) < 4:
            continue
        spot = _dt.date.fromisoformat(meta["spot"])
        steps = sorted((_dt.date.fromisoformat(mt), lv) for mt, lv in by_day[d])
        res = frapath_day(spot, meta["base"], steps, quotes, ctx.holidays)
        for name, v in res["fra"].items():
            series.setdefault(name, []).append((d, v["dev"]))
        for m, v in res["tenor"].items():
            tenor_series.setdefault(m, []).append((d, v["dev"]))
        for meeting, v in res["mpc"].items():
            mpc_series.setdefault(meeting, []).append((d, v["dev"]))
    now = None
    p = ctx.path
    if p and p.get("spot") and p.get("base") is not None and p.get("steps"):
        now_quotes = {m: ctx.cur(k) for m, k in tenor_keys.items() if ctx.cur(k) is not None}
        if len(now_quotes) >= 4:
            now = frapath_day(p["spot"], p["base"], p["steps"], now_quotes, ctx.holidays)
    mons: List[Monitor] = []
    rows = []
    for m1, m2 in FRA_BUCKETS:
        name = "%dx%d" % (m1, m2)
        pts = series.get(name) or []
        far, near = tenor_keys.get(m2), tenor_keys.get(m1)
        row = {"bucket": name, "n": len(pts), "now": (now or {}).get("fra", {}).get(name)}
        if not pts or not far or not near:
            rows.append(row)
            continue
        ann_far = _annuity(ctx.cur(far) or 30.0, m2)
        ann_near = _annuity(ctx.cur(near) or 30.0, m1)
        span = ann_far - ann_near
        legs = [{"key": far, "name": _ois_name(ctx, far), "weight": ann_far / span if span > 0 else 1.0},
                {"key": near, "name": _ois_name(ctx, near), "weight": -ann_near / span if span > 0 else -1.0}]

        def calc(live, name=name, last=pts[-1][1]):
            # today: the latest meeting path the history computed with the quotes now; without one, the last close's
            q = {m: ctx.cur(k, live) for m, k in tenor_keys.items()}
            q = {m: v for m, v in q.items() if v is not None}
            if ctx.path is None or len(q) < 4:
                return last
            r = frapath_day(ctx.path["spot"], ctx.path["base"], ctx.path["steps"], q, ctx.holidays)
            v = (r["fra"].get(name) or {}).get("dev")
            return v if v is not None else last

        mon = mr_monitor(ctx, "frapath:" + name, "frapath", "TRY OIS", "%s FRA (PPK patikasına göre)" % name, "bp", 1, [d for d, _ in pts],
                         [v for _, v in pts], "bp", legs, calc, pkg="rate", carry_up=_pkg_carry(ctx, legs),
                         note="Eğrinin (OIS kotalarından) %s forward'ı ile toplantı tarihli PPK patikasının aynı dönem için verdiği forward "
                              "arasındaki fark (bp): + ise eğri patikadan yüksek, uzak bacak ucuz (FRA receive: %s receive / %s pay)." % (
                                  name, _ois_name(ctx, far), _ois_name(ctx, near)))
        if mon is not None:
            row.update({"z": mon.zof(pts[-1][1]), "half_life": mon.half_life, "sid": mon.sid, "dev": pts[-1][1]})
            mons.append(mon)
        rows.append(row)
    tenors = []
    for m in sorted(tenor_series):
        pts = tenor_series[m]
        vals = [v for _, v in pts][-ctx.window():]
        cur = ((now or {}).get("tenor") or {}).get(m)
        tenors.append({"months": m, "label": _MONTH_LABEL.get(m, "%dM" % m), "dev": cur["dev"] if cur else (vals[-1] if vals else None),
                       "quote": cur["quote"] if cur else None, "path": cur["path"] if cur else None,
                       "z": qm.zscore(cur["dev"] if cur else vals[-1], vals) if len(vals) >= 20 else None, "n": len(vals)})
    # the coming meeting periods (today's path): the meeting-dated OIS of each against the path's level for it
    periods = []
    for meeting, cur in sorted(((now or {}).get("mpc") or {}).items()):
        pts = mpc_series.get(meeting) or []
        row = {"meeting": meeting, "start": cur["start"], "end": cur["end"], "curve": cur["curve"], "path": cur["path"], "dev": cur["dev"],
               "n": len(pts)}
        name = "PPK dönemi %s – %s" % (_tr(cur["start"]), _tr(cur["end"]))

        def pcalc(live, meeting=meeting, last=pts[-1][1] if pts else None):
            q = {m: ctx.cur(k, live) for m, k in tenor_keys.items()}
            q = {m: v for m, v in q.items() if v is not None}
            if ctx.path is None or len(q) < 4:
                return last
            r = frapath_day(ctx.path["spot"], ctx.path["base"], ctx.path["steps"], q, ctx.holidays)
            v = (r["mpc"].get(meeting) or {}).get("dev")
            return v if v is not None else last

        if pts:
            mon = mr_monitor(ctx, "frapath:mpc:" + meeting, "frapath", "TRY OIS", name + " (toplantı tarihli OIS)", "bp", 1, [d for d, _ in pts],
                             [v for _, v in pts], "bp", [{"key": "MPC:" + meeting, "name": name, "weight": 1.0}], pcalc, pkg="rate",
                             min_share=60.0 / max(60.0, ctx.min_obs()),
                             note="Eğrinin bu toplantı dönemi için forward'ı (OIS kotalarından) − PPK patikasının aynı dönemdeki seviyesi (bp): + ise "
                                  "toplantı tarihli OIS patikaya göre ucuz (receive), − ise pahalı (pay).")
            if mon is not None:
                row.update({"z": mon.zof(row["dev"]), "half_life": mon.half_life, "sid": mon.sid})
                mons.append(mon)
        periods.append(row)
    return mons, {"ok": True, "rows": rows, "tenors": tenors, "periods": periods, "live": now is not None}


def _tr(iso: str) -> str:
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[2:4])


# ---------------------------------------------------------------------------------------------- 8/9. momentum and regime
MOM_UNIVERSE = (("OIS:3M", "Eğri"), ("OIS:6M", "Eğri"), ("OIS:1Y", "Eğri"), ("OIS:2Y", "Eğri"), ("OIS:3Y", "Eğri"), ("OIS:5Y", "Eğri"),
                ("OIS:10Y", "Eğri"), ("OFF:3M", "Eğri"), ("OFF:1Y", "Eğri"), ("FX:USDTRY", "FX"), ("FX:EURUSD", "FX"), ("FX:EURTRY", "FX"),
                ("UST:2Y", "Küresel"), ("UST:10Y", "Küresel"), ("DXY", "Küresel"), ("BRENT", "Küresel"), ("CDS", "Küresel"))


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


def fam_momentum(ctx: Ctx, extra: Sequence[Tuple[str, str]] = ()) -> Tuple[List[Monitor], Dict[str, Any]]:
    cfg = ctx.cfg
    horizon = float(cfg["horizon"])
    mons: List[Monitor] = []
    rows = []
    universe = list(MOM_UNIVERSE) + list(extra)
    for key, group in universe:
        mo = momentum_of(ctx, key)
        if mo is None:
            continue
        kind = ctx.kind(key)
        pts = ctx.pts(key)
        values = [v for _, v in pts][-ctx.window():]
        reg = regime_of(values, kind, cfg)
        row = dict(mo, key=key, label=ctx.label(key), group=group, regime=reg["tag"], hurst=reg["hurst"], vr=reg["vr"], vr_z=reg["vr_z"],
                   vol_pct=reg["vol_pct"], unit=level_unit(kind))
        rows.append(row)

        def calc(live, key=key):
            return ctx.cur(key, live)

        def zfn(level, live, key=key):
            r = momentum_of(ctx, key, live)
            return r["score"] if r else None

        level = mo["level"]
        reward = to_level(kind, mo["sd"] * math.sqrt(horizon), level)
        to_ma = abs(level - mo["ma_slow"])
        mon = Monitor("momentum:" + key, "momentum", _asset_of(key), ctx.label(key), level_unit(kind), 3 if kind == "rate" else 4,
                      [d for d, _ in pts][-ctx.window():], values, [{"key": key, "name": ctx.label(key), "weight": 1.0}], calc, zfn=zfn,
                      entry=float(cfg["mom_entry"]), follows=True, mode="drift", reward=reward,
                      risk=to_ma if 0.25 * reward <= to_ma <= 3 * reward else reward, hold=horizon, regime=reg,
                      pkg={"rate": "rate", "fx": "fx", "index": "fx", "bp": "cds", "vol": "vol"}.get(kind, "fx") if key != "CDS" else "cds",
                      carry_up=ctx.carry_week(key), score_name="mom",
                      gate=lambda s, mo=mo: (0.0, "hareketli ortalamalar onaylamıyor (%d / %d gün)" % (int(cfg["ma_fast"]), int(cfg["ma_slow"])))
                      if s != mo["state"] else (1.0, ""),
                      note="1H / 1A / 3A değişimlerin günlük vol × √gün'e bölümünün ortalaması; %d / %d günlük ortalamalar aynı yönü göstermeli. "
                           "Hedef: ufuk boyunca 1σ; stop: %d günlük ortalama." % (int(cfg["ma_fast"]), int(cfg["ma_slow"]), int(cfg["ma_slow"])),
                      info={"w1": mo["w1"], "m1": mo["m1"], "m3": mo["m3"], "ma": mo["state"]})
        if key.startswith("UST:"):
            mon.pkg = "bond"
        mons.append(mon)
    # cross-sectional rank within the curve and within FX
    for group in ("Eğri", "FX", "Küresel"):
        members = sorted((r for r in rows if r["group"] == group), key=lambda r: -r["score"])
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
            stats[p] = {"n": len(fwd), "mean": nw["mean"] if nw else None, "t": nw["t"] if nw else None, "sd": nw["sd"] if nw else None}
        cur = stats.get(now_phase) or {}
        row = {"slope": name, "level": s[-1] if s else None, "stats": stats, "phase": now_phase}
        rows.append(row)
        if cur.get("t") is None or cur.get("n", 0) < 3 * horizon or not cur.get("sd"):
            continue

        def calc(live, long_k=long_k, short_k=short_k):
            a, b = ctx.cur(long_k, live), ctx.cur(short_k, live)
            return (a - b) * 100.0 if a is not None and b is not None else None

        t_now = cur["t"]
        legs = [{"key": long_k, "name": _ois_name(ctx, long_k), "weight": 1.0}, {"key": short_k, "name": _ois_name(ctx, short_k), "weight": -1.0}]
        mon = Monitor("cycle:" + name, "cycle", "TRY OIS", name, "bp", 1, days[-ctx.window():], s[-ctx.window():], legs, calc,
                      zfn=lambda level, live, t_now=t_now: t_now, entry=float(cfg["cycle_t"]), follows=True, mode="drift",
                      reward=abs(cur["mean"]), risk=cur["sd"], hold=float(horizon), pkg="slope", carry_up=_pkg_carry(ctx, legs),
                      regime={"tag": None}, score_name="t", zvalues=None,
                      note="Bugünkü faz: %s. Bu fazdaki günlerden sonraki %d iş gününde %s ortalama %s bp değişti (n = %d, Newey-West t = %s)."
                      % (now_phase, horizon, name, _f2(cur["mean"]), cur["n"], _f2(t_now)),
                      info={"phase": now_phase, "mean": cur["mean"], "n": cur["n"], "t": t_now})
        mon.zvalues = [None] * len(mon.values)
        mons.append(mon)
    return mons, {"ok": True, "phase": now_phase, "rows": rows, "counts": counts, "horizon": horizon, "rule": float(cfg["cycle_bp"])}


# ---------------------------------------------------------------------------------------------- 11. vol premium, m. vol forecast
VOL_PAIRS = ("USDTRY", "EURUSD", "USDZAR", "USDMXN", "USDBRL", "USDINR", "USDIDR", "USDHUF", "USDPLN", "USDCOP")
FC_HORIZON = 63                          # business days of a 3M option


def _rets(values: Sequence[float]) -> List[float]:
    return [math.log(b / a) * 100.0 for a, b in zip(values, values[1:]) if a > 0 and b > 0]


def fam_vol(ctx: Ctx) -> Tuple[List[Monitor], Dict[str, Any]]:
    mons: List[Monitor] = []
    rows = []
    win = ctx.window()
    for pair in VOL_PAIRS:
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
    for ccy in CARRY_CCYS:
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
                mon = Monitor("emcarry:TRY", "emcarry", "EM carry", "USDTRY 3M forward (EM sepetine karşı)", "", 4, [d for d, _ in fwd][-win:], fv[-win:],
                              [{"key": "FX:USDTRY", "name": "USDTRY 3M forward", "weight": 1.0}, {"key": "EMFX", "name": "USD / EM sepeti", "weight": -1.0}],
                              lambda live: ctx.cur("FWD:USDTRY:3M", live), zfn=lambda level, live: (rel_now(live) - mean) / sd if rel_now(live) is not None else None,
                              mode="drift", reward=(f_now - s_now) * horizon / 63.0, risk=to_level("fx", sd_f * math.sqrt(horizon), f_now),
                              hold=horizon, regime={"tag": None}, pkg="fx", score_name="z",
                              zvalues=None, info={"rel": rel[-1], "mean": mean, "sd": sd, "inputs": ["FXV:USDTRY", "FX:USDTRY"]},
                              note="TRY'nin carry / vol oranı (3M forward'ın ima ettiği yıllık getiri farkı ÷ ATM 3M vol) ile EM sepetinin ortalaması "
                                   "arasındaki farkın z'si: + ise TRY carry'si göreli cazip (USDTRY forward sat, EM sepetine karşı). Hedef: ufuk boyunca "
                                   "carry kadar; stop: ufuk σ'sı kadar ters hareket.")
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


def fam_fwdprem(ctx: Ctx, usdtry_trend: Optional[Dict[str, Any]]) -> Tuple[List[Monitor], Dict[str, Any]]:
    win = ctx.window()
    mons: List[Monitor] = []
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
        # the forecast drift: the EWMA (λ 0.97, a half-life of about 23 days) of the daily log returns, a year's worth
        drift: Dict[str, float] = {}
        m = 0.0
        for i, r in enumerate(rets):
            if i < 20:
                continue
            if i == 20:
                m = sum(rets[:20]) / 20.0
            m = 0.97 * m + 0.03 * r
            drift[sd_days[i + 1]] = m * 252.0
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
        mon = mr_monitor(ctx, "fwdprem:%s:%s" % (pair, tenor), "fwdprem", "FX", "%s %s forward" % (pair, tenor), "%", 2, days, cushion, "bp",
                         legs, calc, pkg="fx", gate=gate, info={"inputs": [fk, sk]},
                         note="Forward'ın ima ettiği yıllık değer kaybı − beklenen kayma (günlük getirilerin EWMA'sı, λ 0,97, yıllık): + ise forward "
                              "değer kaybını fazla fiyatlıyor → carry lehine (%s forward sat, TRY al); − ise tersi. USDTRY'de trend rejimi sinyali "
                              "bekletir." % pair)
        if mon is not None:
            mon.kind = "carry"
            row.update({"cushion": cushion[-1], "z": mon.zof(cushion[-1]), "half_life": mon.half_life, "sid": mon.sid})
            mons.append(mon)
        rows.append(row)
    return mons, {"rows": rows}


# ---------------------------------------------------------------------------------------------- r. forecast model
MODEL_UNIVERSE = ("OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y", "FX:USDTRY", "CDS", "UST:10Y")
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
        if len(pts) < 125 + min_train + 2 * MODEL_STEP:
            if pts:
                rows.append({"key": key, "label": ctx.label(key), "error": "geçmiş kısa (%d kapanış)" % len(pts)})
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
        elif key == "FX:USDTRY":
            cs = carry_series(ctx, "TRY")
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
        row = {"key": key, "label": ctx.label(key), "n_test": wf["n"], "hit_rate": wf.get("hit_rate"), "log_loss": wf.get("log_loss"),
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
        sd = qm.stdev(diffs(kind, values)[-60:]) or 0.0
        level = ctx.cur(key)
        explain = " · ".join("%s %s%s" % (name, "+" if c >= 0 else "−", _f2(abs(c))) for name, c in zip(MODEL_FEATURES, coef[1:]))
        mon = Monitor("model:" + key, "model", _asset_of(key), ctx.label(key), level_unit(kind), 3 if kind == "rate" else 4, days[-ctx.window():],
                      values[-ctx.window():], [{"key": key, "name": ctx.label(key), "weight": 1.0}], lambda live, key=key: ctx.cur(key, live),
                      zfn=lambda level, live, p_now=p_now: (p_now - 0.5) / 0.05, follows=True, mode="drift",
                      reward=to_level(kind, sd * math.sqrt(MODEL_STEP), level or 0.0), risk=to_level(kind, sd * math.sqrt(MODEL_STEP), level or 0.0),
                      hold=float(MODEL_STEP), regime={"tag": None}, pkg={"rate": "rate", "bp": "cds", "fx": "fx"}.get(kind, "fx"),
                      carry_up=ctx.carry_week(key), score_name="z(p)",
                      info={"p": p_now, "hit_rate": wf.get("hit_rate"), "n_test": wf["n"], "log_loss": wf.get("log_loss"), "valid": valid,
                            "coef": dict(zip(MODEL_FEATURES, coef[1:]))},
                      note="Gelecek haftanın yönü için L2 lojistik regresyon (özellikler standart: %s). Yukarı olasılığı %%%s; kayan "
                           "pencereli doğrulamada isabet %%%s (%d test, log-loss %s). z = (p − 0,5) / 0,05." % (
                               explain, _f1(p_now * 100), _f1((wf.get("hit_rate") or 0) * 100), wf["n"], _f2(wf.get("log_loss"))))
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
    usd = next((r for r in (tables.get("momentum") or {}).get("rows", []) if r["key"] == "FX:USDTRY"), None)
    step("fwdprem", lambda: fam_fwdprem(ctx, usd))
    step("model", lambda: fam_model(ctx))
    tables["regime"] = regime_table(ctx, mons)
    tables["errors"] = errors
    return mons, tables


def score_all(ctx: Ctx, mons: List[Monitor], raw_live: Dict[str, float]) -> None:
    live = ctx.derive_live(raw_live)
    for m in mons:
        m.score(live, raw_live)
        if m.family == "macro":
            macro_levels(m, ctx.cfg)
