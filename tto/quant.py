"""Quant signals: the desk's statistical analyses of the TRY rates and FX markets, each ending in trade signals of one
format, ranked on the "Sinyaller" page, logged as they fire and sent to the users who subscribe.

**Where the numbers come from.**  The daily closes of the history (``tto/history.py``): the TRY OIS tenors, the offshore
curve, DİBS, TLREF - and the series this package adds to the history's own list (``history_defs``: USDTRY / EURTRY /
EM spots, their 3M ATM vols and risk reversals, forward points, UST 2Y / 10Y, DXY, Brent, Türkiye 5Y CDS, USD OIS 3M),
which the live dashboard fetches two years back with its normal history sync.  From the workbook (one short read on the
engine thread): today's OIS / offshore quotes as the spread pages read them, the VİOP history (``EK_VIOP``), the
meeting path of OIS_MAIN and the carry + roll of the tenor engine.  The meeting-pricing history of every past day comes
from the store.

**Off the engine thread.**  All workbook calculations run on the one engine thread; a long job there would freeze every
user.  So the analyses run in a thread of their own (``tto-quant``) on a snapshot of the closes: the full fit when a
new close arrived (and on a new day, a change of the settings), then - at most once a minute - only the latest point
with the live values (each monitor keeps a function that reads its level now).  Pages read the cached result.

**Signals** (``quantfam.make_signal``): family, the trade with its legs and weights, direction, score z and a strength
bucket, entry / target / stop, half-life and expected holding, carry + roll a week, regime, how many other families
agree, time.  Ranked by |z| × regime fit × half-life fit × carry agreement - within their group of the Sinyaller list
(``quantuniv``: G10 spot, G10 opsiyon, TRY OIS ≤ 2Y then the long end, DİBS, VİOP, Offshore), the ones a gate holds
after the others as "düşük güven".  The universe the systematic families trade (``quantuniv.Registry``) is built on
every full fit after the other families; theirs run on it.

**Log.**  Each time a signal crosses its entry threshold it is written down (time, level, z) and followed: target,
stop, or ``log_days`` business days later - live tracking (no backtest), so the desk sees which families work.

**Alerts.**  A crossing is also an alert: the live stream carries a counter (``counters``), a page asks for the alerts
after the last it saw (``alerts``) - the ones its user subscribed to.  ``add_alert_hook`` lets the desk-wide alarms
(``tto/watch.py``) take them in once both are merged.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import fx as fxm
from . import quantbt as qbt
from . import quantcurve as qcurve
from . import quantfam as qf
from . import quantintraday as qi
from . import quantopt as qopt
from . import quantlead as ql
from . import quantuniv as qu
from . import quantviop as qv
from . import quantpath as qp
from . import quanttrend as qtr               # Trend: its setting, page and view (its family plugs in through quantuniv)
from . import volcarry as vc
from .service import ServiceError

#: the analyses beside quantfam's families, each with its families, page, series, part of the engine read, live
#: values, run after ``quantfam.run_all``, live tables, view and coverage (Eğri Adil Değeri, Opsiyon)
EXTRAS = (qcurve, qopt)
for _x in EXTRAS:
    qf.FAMILIES.update(_x.FAMILIES)
qf.FAMILIES.update(qv.FAMILIES)                  # VİOP (quantviop.py)
qf.FAMILIES.update(qu.FAMILIES)                  # the families on the universe (quantuniv.py: Trend, Carry + momentum, ML)

# ---------------------------------------------------------------------------------------------- settings
DEFAULTS: Dict[str, Any] = {
    "entry_z": 2.0, "target_z": 0.0, "stop_z": 3.5, "horizon": 20, "hl_max_mult": 2.0, "min_obs": 120, "lookback": 250,
    "corr_windows": [20, 60, 120], "corr_min": 0.3, "mom_entry": 1.5, "ma_fast": 20, "ma_slow": 60, "vr_q": 10, "regime_window": 250,
    "log_days": 20, "kalman_q": 0.01, "model_hit": 0.55, "model_min_tests": 40, "model_l2": 5.0, "cycle_bp": 100.0, "cycle_t": 2.0,
    "dv01_usd": 1000.0, "rv_items": "1y2y, 2y5y, 5y10y, 2y10y, 1y5y, 6m1y2y, 1y2y3y, 1y2y5y, 2y3y5y, 2y5y10y, 3y5y10y",
    "desk_alarm": "Güçlü", "carry_margin": 0.5, "fx_verdict": 0.3,
    "bt_mute": "kapalı", "bt_min_hit": 0.5, "bt_min_sharpe": 0.0, "bt_min_trades": 10,
    "fx_pairs": "USDTRY, EURTRY, GBPTRY, EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, USDCNH, USDZAR, USDMXN, USDBRL, USDINR, USDIDR, "
                "USDHUF, USDPLN, USDCOP, USDCZK, USDKRW, USDCLP, USDILS",
}
#: which signals also ring as the desk's alarms (deskalarms.py, for everyone): at least this strong, or none
DESK_ALARM_CHOICES = ("kapalı", "Zayıf", "Orta", "Güçlü")
#: the backtest's floor: off (the stats are shown), or on (a family below it has its signals held back)
BT_MUTE_CHOICES = ("kapalı", "açık")
#: name -> (lowest, highest, type)
LIMITS: Dict[str, Tuple[float, float, type]] = {
    "entry_z": (0.5, 5.0, float), "target_z": (-1.0, 2.0, float), "stop_z": (1.0, 10.0, float), "horizon": (2, 120, int),
    "hl_max_mult": (1.0, 10.0, float), "min_obs": (30, 750, int), "lookback": (60, 750, int), "corr_min": (0.0, 0.95, float),
    "mom_entry": (0.25, 5.0, float), "ma_fast": (2, 120, int), "ma_slow": (5, 250, int), "vr_q": (2, 30, int), "regime_window": (60, 750, int),
    "log_days": (1, 120, int), "kalman_q": (1e-6, 1.0, float), "model_hit": (0.5, 0.9, float), "model_min_tests": (10, 200, int),
    "model_l2": (0.0, 100.0, float), "cycle_bp": (10.0, 1000.0, float), "cycle_t": (0.5, 10.0, float), "dv01_usd": (1.0, 1e7, float),
    "carry_margin": (0.0, 3.0, float), "fx_verdict": (0.0, 3.0, float),
    "bt_min_hit": (0.0, 1.0, float), "bt_min_sharpe": (-5.0, 5.0, float), "bt_min_trades": (1, 1000, int),
}
LABELS = {
    "entry_z": "Giriş eşiği |z|", "target_z": "Hedef z (ortalamaya göre)", "stop_z": "Stop |z|", "horizon": "Elde tutma ufku (iş günü)",
    "hl_max_mult": "Yarı ömür sınırı (ufkun katı)", "min_obs": "En az gözlem (gün)", "lookback": "Tahmin penceresi (gün)",
    "corr_windows": "Korelasyon pencereleri (gün)", "corr_min": "Kırılma için uzun dönem |ρ| en az", "mom_entry": "Momentum eşiği",
    "ma_fast": "Hızlı ortalama (gün)", "ma_slow": "Yavaş ortalama (gün)", "vr_q": "Varyans oranı q (gün)", "regime_window": "Rejim penceresi (gün)",
    "log_days": "Sinyal kaydı süresi (iş günü)", "kalman_q": "Kalman β değişkenliği (q)", "model_hit": "Model isabet eşiği",
    "model_min_tests": "Model en az test noktası", "model_l2": "Model L2 cezası", "cycle_bp": "PPK fazı eşiği (TLREF 3A değişimi, bp)",
    "cycle_t": "PPK sinyali için |t| en az", "dv01_usd": "Paket DV01'i (USD / bp, ana bacak; masa: OIS_MAIN!F2)", "rv_items": "PCA-nötr spread ve fly'lar",
    "desk_alarm": "Masa alarmına düşen en az güç",
    "carry_margin": "Carry aleyhine işlemde tampon (ufuk σ'sı)", "fx_verdict": "Parite kararı için en az beklenen getiri / vol",
    "fx_pairs": "FX pariteleri (Bloomberg geçmişi: ilk doldurma turda 40 seri)",
    "bt_mute": "Geri testi zayıf aileyi sustur", "bt_min_hit": "Geri test: en az isabet", "bt_min_sharpe": "Geri test: en az Sharpe",
    "bt_min_trades": "Geri test: karar için en az işlem",
}
for _mod in (qp, ql, qv, qtr):                  # the implied path's grids and policy rate, lead-lag's k and lag, VİOP's window,
    DEFAULTS.update(_mod.DEFAULTS)              # Trend's daily risk
    LIMITS.update(_mod.LIMITS)
    LABELS.update(_mod.LABELS)

#: the history keeps this series this many calendar days back (about two years)
HISTORY_DAYS = 740
START_DELAY = 8.0               # seconds after the start before the first fit (the workbook and the history come first)
LIVE_EVERY = 60.0               # at most this often: the latest point with live values
MARK_EVERY = 300.0              # how often the store is asked whether a new close arrived
LOG_KEEP = 1500
ALERT_KEEP = 300
PAGES = (("quant", "Sinyaller"), ("quant-corr", "Korelasyon"), ("quant-pca", "PCA / RV"), ("quant-pairs", "Çiftler"),
         ("quant-regime", "Rejim & Momentum"), ("quant-fx", "FX Vol Primi & Carry"), ("quant-macro", "Makro Beta"),
         ("quant-model", "Tahmin Modeli"), ("quant-intraday", "Gün İçi"))
PAGES += tuple(p for _x in EXTRAS for p in _x.PAGES)
PAGES += (("quant-path", "İma Patikası"), ("quant-wirp", "TCMB WIRP"), ("quant-lead", "Öncü-Takipçi"))   # quantpath.py, quantlead.py
PAGES += qv.PAGES                                                                                          # quantviop.py
PAGES += qtr.PAGES                                                                                         # quanttrend.py
#: the menu: four entries, each one page whose tabs are the pages above - (entry, its name, ((page, tab's name) ...)).
#: A page keeps its own address (#/quant-pca opens "Faiz" on "PCA / RV"); an entry of one page is that page itself.
MENU = (("quant.sinyal", "Sinyaller", (("quant", "Sinyaller"), ("quant-intraday", "Gün içi"), ("quant-model", "Model"),
                                       ("quant-trend", "Trend"))),
        ("quant.faiz", "Faiz", (("quant-pca", "PCA / RV"), ("quant-pairs", "Çiftler"), ("quant-corr", "Korelasyon"),
                                ("quant-regime", "Rejim"), ("quant-curve", "Eğri Adil Değeri"), ("quant-path", "İma Patikası"),
                                ("quant-wirp", "TCMB WIRP"), ("quant-lead", "Öncü-Takipçi"))),
        ("quant.fx", "FX", (("quant-fx", "FX"), ("quant-macro", "Makro"), ("quant-opt", "Opsiyon"))),
        ("quant-viop", "VİOP", (("quant-viop", "VİOP"),)))


# ---------------------------------------------------------------------------------------------- the series this package adds
G10 = ("USD", "EUR", "JPY", "GBP", "CHF", "AUD", "CAD", "NZD", "NOK", "SEK", "DKK")
#: the forward tenors kept per pair: USDTRY its term structure (the carry of any holding), the others the 3M
TRY_TENORS = ("1M", "3M", "6M", "1Y")


def pair_group(code: str) -> str:
    """TRY (USDTRY and the TRY crosses), G10 (both currencies), EM (the rest - the EM FX basket's members)."""
    if "TRY" in code:
        return "TRY"
    if code[:3] in G10 and code[3:] in G10 and "CNH" not in code:
        return "G10"
    return "EM"


def parse_pairs(text: Any) -> List[str]:
    """The pair codes of a setting ("USDTRY, EURUSD …"): six letters each, USDTRY always first, no repeats."""
    raw = text if isinstance(text, (list, tuple)) else str(text or "").replace(";", ",").replace("\n", ",").split(",")
    out = ["USDTRY"]
    for x in raw:
        code = str(x).strip().upper().replace("/", "").replace(" ", "")
        if not code:
            continue
        if len(code) != 6 or not code.isalpha() or code[:3] == code[3:]:
            raise ValueError("parite anlaşılamadı: %r (örn. USDTRY, EURUSD)" % str(x).strip())
        if code not in out:
            out.append(code)
    if len(out) > 40:
        raise ValueError("en çok 40 parite")
    return out


def fx_pair_list(store: Any) -> List[str]:
    """The pairs of the desk's quant setting (the defaults without one) - the history keeps their series."""
    saved = store.get(Quant.SET_KEY) if store is not None else None
    text = saved.get("fx_pairs") if isinstance(saved, dict) and saved.get("fx_pairs") else DEFAULTS["fx_pairs"]
    try:
        return parse_pairs(text)
    except ValueError:
        return parse_pairs(DEFAULTS["fx_pairs"])


def series_specs(source: str = fxm.DEFAULT_SOURCE, pairs: Optional[Sequence[str]] = None) -> List[Dict[str, str]]:
    """The tickers the quant analyses need that the workbook does not keep: ``{key, label, ticker, kind, group}`` - per
    pair of ``pairs`` (the setting's list; its defaults) the spot, the 3M forward points (USDTRY 1M / 3M / 6M / 1Y) and,
    but for the TRY crosses, the ATM 3M vol and the 25D risk reversal; the global drivers; the pages' own; the fixed
    G10 universe's (``quantuniv.series_specs``).  Every one of them is to be checked on the terminal (README, "Quant
    sinyaller")."""
    out: List[Dict[str, str]] = []

    def add(key: str, label: str, ticker: str, kind: str, group: str) -> None:
        out.append({"key": key, "label": label, "ticker": ticker, "kind": kind, "group": group})

    codes = parse_pairs(DEFAULTS["fx_pairs"] if pairs is None else pairs)
    known = {p.code: p for p in fxm.PAIRS}
    objs = {code: known.get(code) or fxm._pair(code, pair_group(code), 3 if code.endswith("JPY") else 4) for code in codes}
    for code in codes:
        add("FX:" + code, code, fxm.spot_ticker(objs[code]), "fx", pair_group(code))
    for code in codes:
        if code == "USDTRY" or "TRY" not in code:
            add("FXV:" + code, "%s ATM 3M vol" % code, fxm.vol_ticker(code, "ATM", "3M", source), "vol", pair_group(code))
            add("FXR:" + code, "%s 25D RR 3M" % code, fxm.vol_ticker(code, "RR25", "3M", source), "vol", pair_group(code))
    for code in codes:
        for tenor in (TRY_TENORS if code == "USDTRY" else ("3M",)):
            add("FXP:%s:%s" % (code, tenor), "%s %s swap puanı" % (code, tenor), fxm.points_ticker(objs[code], tenor), "pts", pair_group(code))
    add("UST:2Y", "UST 2Y", "USGG2YR Index", "rate", "Global")
    add("UST:10Y", "UST 10Y", "USGG10YR Index", "rate", "Global")
    add("DXY", "DXY", "DXY Curncy", "index", "Global")
    add("BRENT", "Brent", "CO1 Comdty", "index", "Global")
    add("CDS", "Türkiye 5Y CDS", "TURKEY CDS USD SR 5Y D14 Corp", "bp", "Global")
    add("USD:3M", "USD OIS 3M", "USSOC Curncy", "rate", "Global")
    # the analyses of their own (curve fair value, options, VİOP) add theirs - a series the list has already (EURUSD's
    # 3M points, also a pair's forward) is kept once: the history must not ask Bloomberg for one series twice
    have = {(s["ticker"], s.get("field", "PX_LAST")) for s in out} | {s["key"] for s in out}
    usdtry = next((s["ticker"] for s in out if s["key"] == "FX:USDTRY"), "USDTRY Curncy")
    # ... and the fixed G10 universe of the families on it (quantuniv.py: spots, 3M points, ATM / RR / BF), whatever the
    # desk's pair list: the ones the list has are its own, the rest the universe's ("universe": the FX analyses above
    # keep to the desk's list)
    for s in [x for mod in EXTRAS for x in mod.series_specs(source)] + qv.series_specs() + qv.spot_specs(usdtry) + qu.series_specs(source):
        tf = (s["ticker"], s.get("field", "PX_LAST"))
        if tf not in have and s["key"] not in have:
            out.append(s)
            have.update((tf, s["key"]))
    return out


#: the order the first backfill takes them in (live: a few a sync): the global drivers, the spots, the forward points
#: (with the spots: the carry of every pair), the ATM vols, the risk reversals, then the pages' own (Opsiyon, VİOP) -
#: and last the G10 universe's (its spots, points, then its vols tenor by tenor: what the analyses read comes first)
BACKFILL_ORDER = ("Global", "FX:", "FXP:", "FXV:", "FXR:")


def _backfill_rank(spec: Dict[str, str]) -> int:
    if spec.get("universe"):
        return len(BACKFILL_ORDER) + 1
    if spec["group"] == "Global":
        return 0
    return next((i for i, p in enumerate(BACKFILL_ORDER) if i and spec["key"].startswith(p)), len(BACKFILL_ORDER))


def history_defs(source: str = fxm.DEFAULT_SOURCE, pairs: Optional[Sequence[str]] = None,
                 viop: Optional[Dict[str, Any]] = None) -> List[Any]:
    """The series above as definitions of the history (``tto.history.SeriesDef``): fetched with its normal sync, two
    years back (``info["lookback"]``) - the first time a few per sync in live mode (``info["backfill"]``), in the order
    of ``BACKFILL_ORDER`` -, then their new days with every sync like the history's own series (the desk keeps the
    15-minute sync for every series; the history can still ask a series' new days once a day, ``info["tail"] = "daily"``,
    but none of these is marked so), shown on the settings page's coverage table under "Quant"."""
    from .history import SeriesDef
    specs = sorted(series_specs(source, pairs), key=_backfill_rank)
    if viop and viop.get("active"):
        # VİOP's contracts (quantviop.py): the listed ones and two years of expired ones, each close / high / low
        specs += qv.contract_specs(viop["active"], viop["today"])
    out = []
    for s in specs:
        info = {"key": s["key"], "kind": s["kind"], "group": s["group"], "lookback": s.get("lookback", HISTORY_DAYS),
                "backfill": s.get("backfill", True)}
        if s.get("tail"):
            info["tail"] = s["tail"]
        out.append(SeriesDef("Quant", s["label"], s["ticker"], s.get("field", "PX_LAST"), s.get("alts", ()),
                             unit="pct" if s["kind"] == "rate" else "px", info=info))
    return out


#: the history's own series the analyses read (the OIS curve, offshore, the XCCY, TLREF, DİBS): kept two years back as
#: well - the first fill as the history's own setting says, the year before it afterwards, a few series a sync
QUANT_GROUPS = ("ref", "ois", "off", "xccy", "dibs")


def extend_for_quant(defs: Sequence[Any]) -> None:
    """Mark the history's own series the quant analyses read for two years of closes (see ``QUANT_GROUPS``)."""
    for d in defs:
        if d.group in QUANT_GROUPS:
            d.info = dict(d.info or {}, lookback=HISTORY_DAYS, backfill="extend")


# ---------------------------------------------------------------------------------------------- small helpers
def _clean(v: Any) -> Any:
    """What JSON can carry: no NaN / infinity, no functions, tuples and sets as lists."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items() if not callable(x)}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x) for x in v]
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return v


def _now() -> _dt.datetime:
    return _dt.datetime.now().replace(microsecond=0)


def _bdays(a: str, b: str) -> int:
    """Business days after ``a`` up to ``b`` (ISO days)."""
    d0, d1 = _dt.date.fromisoformat(a), _dt.date.fromisoformat(b)
    n = 0
    while d0 < d1:
        d0 += _dt.timedelta(days=1)
        if d0.weekday() < 5:
            n += 1
    return n


class QuantError(ServiceError):
    pass


# ---------------------------------------------------------------------------------------------- the service part
class Quant(object):
    LOG_KEY = "quant.log"
    LAST_KEY = "quant.last"
    ALERT_KEY = "quant.alerts"
    SUBS_KEY = "quant.subs"
    SET_KEY = "quant.settings"

    def __init__(self, svc):
        self.svc = svc
        self.store = svc.store
        self._lock = threading.RLock()
        self._run = threading.Lock()                # one fit / refresh at a time (the worker, a test, "Şimdi hesapla")
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fit: Optional[Dict[str, Any]] = None  # the last fit: context, monitors, tables
        self._view: Optional[Dict[str, Any]] = None  # what the pages read
        self._mark: Optional[str] = None
        self._mark_at = 0.0
        self._force = False
        self._hooks: List[Callable[[Dict[str, Any]], None]] = []
        self._scale: Dict[str, Tuple[str, Optional[int]]] = {}
        self.use_live = True                        # False: the last close stands for today (tests on synthetic history)
        self._last_base: Optional[Dict[str, Any]] = None   # the last fit's inputs (the backtest refits on them)
        self._bt: Optional[Dict[str, Any]] = None
        self._bt_thread: Optional[threading.Thread] = None
        self.intraday = qi.Intraday(self)
        self.version = 0
        self.state: Dict[str, Any] = {"phase": "idle", "fit_at": None, "fit_ms": None, "live_at": None, "live_ms": None, "engine_ms": None,
                                      "error": "", "timing": {}, "fits": 0, "refreshes": 0}
        seq = max([int(a.get("seq") or 0) for a in self._alerts()] or [0])
        self._alert_seq = seq

    # ================================================================== settings
    def settings(self) -> Dict[str, Any]:
        out = dict(DEFAULTS)
        saved = self.store.get(self.SET_KEY)
        if isinstance(saved, dict):
            out.update({k: v for k, v in saved.items() if k in DEFAULTS})
        return out

    def set_settings(self, user: Optional[str], values: Dict[str, Any]) -> Dict[str, Any]:
        user = self.svc.require_user(user)
        if not isinstance(values, dict):
            raise QuantError("ayarlar anlaşılamadı")
        cur = self.settings()
        pairs_changed = False
        for name, raw in values.items():
            if name in LIMITS:
                lo, hi, typ = LIMITS[name]
                try:
                    v = typ(float(str(raw).replace(",", ".")))
                except (TypeError, ValueError):
                    raise QuantError("%s bir sayı olmalı" % LABELS.get(name, name))
                if not lo <= v <= hi:
                    raise QuantError("%s %s – %s arasında olmalı" % (LABELS.get(name, name), _txt(lo), _txt(hi)))
                cur[name] = v
            elif name == "corr_windows":
                try:
                    ws = sorted({int(float(x)) for x in (raw if isinstance(raw, list) else str(raw).replace(";", ",").split(","))})
                except (TypeError, ValueError):
                    raise QuantError("korelasyon pencereleri gün sayıları olmalı (örn. 20, 60, 120)")
                if not 1 <= len(ws) <= 4 or ws[0] < 5 or ws[-1] > 500:
                    raise QuantError("korelasyon pencereleri 1 – 4 tane, 5 – 500 gün olmalı")
                cur[name] = ws
            elif name == "rv_items":
                text = str(raw or "")[:600]
                items = [it for it in vc.parse_items(text) if it.get("ok")]
                if not items or any(it["product"] != "OIS" or it["kind"] not in ("spread", "fly") for it in items):
                    raise QuantError("yalnızca OIS spread'i (1y2y) ve fly'ı (2y5y10y) yazılabilir")
                cur[name] = ", ".join(it["raw"] for it in items)
            elif name == "fx_pairs":
                try:
                    codes = parse_pairs(raw)
                except ValueError as exc:
                    raise QuantError(str(exc))
                if codes != parse_pairs(cur.get("fx_pairs") or DEFAULTS["fx_pairs"]):
                    pairs_changed = True
                cur[name] = ", ".join(codes)
            elif name in ("desk_alarm", "bt_mute"):
                options = DESK_ALARM_CHOICES if name == "desk_alarm" else BT_MUTE_CHOICES
                choice = next((c for c in options if c.casefold() == str(raw or "").strip().casefold()), None)
                if choice is None:
                    raise QuantError("%s: %s" % (LABELS[name], " / ".join(options)))
                cur[name] = choice
        if not cur["stop_z"] > cur["entry_z"] > cur["target_z"]:
            raise QuantError("stop |z| > giriş |z| > hedef z olmalı")
        if cur["ma_slow"] <= cur["ma_fast"]:
            raise QuantError("yavaş ortalama hızlıdan uzun olmalı")
        if cur["lookback"] < cur["min_obs"]:
            raise QuantError("tahmin penceresi en az gözlem kadar olmalı")
        cur["by"], cur["at"] = user, _now().isoformat(sep=" ")
        self.store.put(self.SET_KEY, cur)
        self._force = True
        if pairs_changed:
            try:
                self.svc.bump()                              # the history reads its list of series again (a new pair's tickers)
                self.svc.history.kick()
            except Exception:  # noqa: BLE001
                pass
        self.kick()
        return self.settings_view()

    def settings_view(self) -> Dict[str, Any]:
        saved = self.store.get(self.SET_KEY) or {}
        return _clean({"values": self.settings(), "defaults": DEFAULTS, "labels": LABELS, "choices": {"desk_alarm": list(DESK_ALARM_CHOICES), "bt_mute": list(BT_MUTE_CHOICES)},
                       "limits": {k: [lo, hi, "int" if t is int else "float"] for k, (lo, hi, t) in LIMITS.items()},
                       "by": saved.get("by") if isinstance(saved, dict) else None, "at": saved.get("at") if isinstance(saved, dict) else None})

    # ================================================================== the worker
    def start(self, force: bool = False) -> None:
        """Keep the results up to date in the background - with the history (the analyses read its closes: switched off
        with it, ``--no-history`` and the tests; "Şimdi hesapla" still computes on request)."""
        if self._thread is not None or self._stop.is_set():
            return
        if not force and not getattr(self.svc.settings, "history", True):
            return
        self._thread = threading.Thread(target=self._loop, name="tto-quant", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5.0)
        self._thread = None

    def kick(self) -> None:
        self._kick.set()

    def _loop(self) -> None:
        # live: the workbook's own Bloomberg requests and the first pages go first
        self._stop.wait(START_DELAY * (4 if self.svc.mode == "live" else 1))
        while not self._stop.is_set():
            try:
                if self._needs_fit():
                    self.compute()
                    self._backtest_soon()
                elif self._fit is not None and time.time() - (self.state.get("live_t") or 0.0) >= LIVE_EVERY - 1.0:
                    self.refresh_live()
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                self.state["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                self.state["phase"] = "idle"
            self._kick.wait(LIVE_EVERY)
            self._kick.clear()

    def _needs_fit(self) -> bool:
        if self._fit is None or self._force:
            return True
        if self._fit.get("today") != self.svc.history.today().isoformat():
            return True
        if time.time() - self._mark_at < MARK_EVERY:
            return False
        self._mark_at = time.time()
        return self._data_mark() != self._fit.get("mark")

    def _data_mark(self) -> str:
        """What the fit was made of: the last day and the count of every series kept, the meeting-pricing days - and how
        many series the history has asked in full (a backfill turn that brought nothing still changes the coverage)."""
        bounds = self.store.hist_bounds()
        days = self.store.mpc_days(None, None)
        last = max(days) if days else None
        asked = len(self.svc.history.fetch_records())
        text = repr(sorted((k, v[1], v[2]) for k, v in bounds.items())) + repr((len(days), last, days[last].get("computed_at") if last else None, asked))
        return hashlib.sha1(text.encode()).hexdigest()

    # ================================================================== the backtest
    BT_KEY = "quant.backtest"

    def _bt_key(self) -> Optional[str]:
        base = self._last_base
        if base is None:
            return None
        cfg = {k: v for k, v in base["cfg"].items() if k not in ("by", "at", "desk_alarm", "bt_mute", "bt_min_hit", "bt_min_sharpe", "bt_min_trades")}
        return hashlib.sha1(repr((base["today"].isoformat(), sorted(cfg.items()))).encode()).hexdigest()

    def backtest_result(self) -> Optional[Dict[str, Any]]:
        if self._bt is None:
            v = self.store.get(self.BT_KEY)
            self._bt = v if isinstance(v, dict) else None
        return self._bt

    def _backtest_soon(self) -> None:
        """Once a day (and after a change of the settings): the walk-forward backtest, in a thread of its own at the
        engine's pace (it pauses between families as the fit does)."""
        key = self._bt_key()
        cur = self.backtest_result()
        if key is None or (cur is not None and cur.get("key") == key) or (self._bt_thread is not None and self._bt_thread.is_alive()):
            return
        self._bt_thread = threading.Thread(target=self._bt_worker, name="tto-quant-bt", daemon=True)
        self._bt_thread.start()

    def _bt_worker(self) -> None:
        try:
            self.run_backtest()
            self.kick()                                     # the signals carry the new stats at the next refresh
        except Exception as exc:  # noqa: BLE001 - the backtest is not worth the signals
            self.state["bt_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])

    def run_backtest(self, days: int = qbt.BT_DAYS, step: int = qbt.BT_STEP, budget: float = 900.0) -> Optional[Dict[str, Any]]:
        """The walk-forward backtest (``tto.quantbt``) on the inputs of the last fit: every family fitted every ``step``
        business days on the closes up to that day only, scored day by day with the very same rules."""
        base = self._last_base
        if base is None:
            return None
        self.state["bt_phase"] = "çalışıyor"
        try:
            cfg = dict(base["cfg"])
            today_iso = base["today"].isoformat()
            series = {k: {d: v for d, v in pts.items() if d < today_iso} for k, pts in base["series"].items()}
            test = sorted({d for k, pts in series.items() if k.startswith(("OIS:", "FX:")) for d in pts})[-days:]
            items = [it for it in vc.parse_items(cfg["rv_items"]) if it.get("ok")]
            mpc = base["mpc"]

            def make_ctx(T: str) -> qf.Ctx:
                nxt = _dt.date.fromisoformat(T) + _dt.timedelta(days=1)
                mp = {"days": {d: x for d, x in (mpc.get("days") or {}).items() if d <= T},
                      "values": [r for r in mpc.get("values") or [] if r["day"] <= T]}
                viop = [dict(c, **{f: {d: v for d, v in (c.get(f) or {}).items() if d <= T} for f in ("px", "days", "imp", "baz", "ois360")}, live={})
                        for c in base["viop"]]
                meta = {k: dict(v) for k, v in base["meta"].items()}
                return qf.Ctx(cfg, nxt, series, meta, {}, viop=viop, carry={}, mpc=mp, path=self._path(mp), holidays=base["holidays"],
                              fwd_scale=base["fwd_scale"])

            def runner(ctx: qf.Ctx) -> List[qf.Monitor]:
                # quantfam's families and the ones on the universe (quantuniv.py: their registry of the day's context)
                return qf.run_all(ctx, items, None, self.pause)[0] + qu.monitors(ctx, self.pause)

            res = qbt.backtest(test, make_ctx, runner, series, cfg, step=step, pause=self.pause, deadline=time.perf_counter() + budget)
            first, last = res.get("first"), res.get("last")
            res.update({"at": _now().isoformat(sep=" "), "today": today_iso, "key": self._bt_key(),
                        "years": ((_dt.date.fromisoformat(last) - _dt.date.fromisoformat(first)).days / 365.0) if first and last else None})
            self.store.put(self.BT_KEY, _clean(res))
            self._bt = _clean(res)
            self.state.update({"bt_at": res["at"], "bt_ms": res["ms"], "bt_error": ""})
            return self._bt
        finally:
            self.state["bt_phase"] = ""

    def backtest_view(self) -> Dict[str, Any]:
        bt = self.backtest_result()
        if not bt:
            return {"ready": False, "running": self._bt_thread is not None and self._bt_thread.is_alive()}
        rows = []
        for fam, st in sorted((bt.get("families") or {}).items(), key=lambda kv: qf.FAMILIES.get(kv[0], (kv[0],))[0]):
            rows.append(dict({k: v for k, v in st.items() if k != "types"}, family=fam, label=qf.FAMILIES.get(fam, (fam,))[0], type=""))
            for ty, s in (st.get("types") or {}).items():
                rows.append(dict(s, family=fam, label=qf.FAMILIES.get(fam, (fam,))[0], type=ty))
        return _clean({"ready": True, "rows": rows, "trades": list(reversed(bt.get("trades") or []))[:150], "first": bt.get("first"),
                       "last": bt.get("last"), "years": bt.get("years"), "at": bt.get("at"), "ms": bt.get("ms"), "refits": bt.get("refits"),
                       "step": bt.get("step"), "days": bt.get("days"), "n_trades": bt.get("n_trades"), "complete": bt.get("complete"),
                       "running": self._bt_thread is not None and self._bt_thread.is_alive()})

    def pause(self) -> None:
        """Between two families: the engine thread gets the interpreter (a calculation waiting for it goes first)."""
        time.sleep(0.002)

    # ================================================================== the snapshot
    def _engine_read(self, full: bool) -> Dict[str, Any]:
        t0 = time.perf_counter()
        try:
            # (at the calculation thread's lowest priority: a page, the header or a write that waits goes first)
            return self.svc.et.call_at(self.svc.et.BACKGROUND, self._read_engine, full)
        finally:
            self.state["engine_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)

    def _read_engine(self, full: bool) -> Dict[str, Any]:
        """Engine thread, short: today's OIS / offshore quotes (the source in use, as the spread pages read them), the
        VİOP history and its live row, the meeting path of OIS_MAIN and - with ``full`` - the carry + roll of the
        tenor engine."""
        from . import extras as ex
        from .xl.model import COLS, parse_a1
        from .xl.tokenizer import index_to_col
        from .xl.values import serial_to_date
        svc = self.svc
        out: Dict[str, Any] = {"ois": {}, "off": {}, "viop": [], "path": None, "tlref": None, "carry": {}, "horizon_a": None}
        book = svc.books.get("tto")
        if book is None:
            return out
        calc = svc._calc(None, book)
        index = book.model.sheet_index

        def reader(sheet: str):
            si = index[sheet]
            return lambda ref: calc.get(si, *divmod(parse_a1(ref), COLS))

        def num(v: Any) -> Optional[float]:
            return v if type(v) is float and math.isfinite(v) else None

        if ex.SRC_SHEET in index:
            get = reader(ex.SRC_SHEET)
            titles = {title: kind for kind, title, _, _, _ in ex.SRC_LISTS}
            for r in range(ex.SRC_FIRST, ex.SRC_FIRST + 60):
                kind = titles.get(get("A%d" % r))
                tenor = get("B%d" % r)
                if kind is None or not isinstance(tenor, str) or not tenor.strip():
                    continue
                if kind == "ois":
                    v = num(get("I%d" % r))
                    if v is not None:
                        out["ois"][tenor.strip().upper()] = v
                else:
                    bid, ask = num(get("I%d" % r)), num(get("J%d" % r))
                    if bid is not None and ask is not None:
                        out["off"][tenor.strip().upper()] = (bid + ask) / 2.0
        if "OIS_MAIN" in index:
            # TLREF only: the meeting levels of the sheet are the solver's - a read of them can set off the whole solver on
            # this thread; the meeting path comes from the history instead (computed on its own engine)
            tl = num(reader("OIS_MAIN")("J2"))
            if tl is not None:
                out["tlref"] = tl if tl > 1.0 else tl * 100.0
            # a package's size as the desk's trades are sized (blotter.OisMarket): USDTRY of OIS_MAIN!D2 and, with
            # ``full``, every OIS tenor's annuity on Motor (I316+ the tenor's OIS_MAIN row)
            fx = num(reader("OIS_MAIN")("D2"))
            out["desk"] = {"usdtry": fx if fx and fx > 0 else None, "ois_annuity": {}}
            if full and "Motor" in index:
                from .blotter import OIS_ROW
                motor = reader("Motor")
                for tenor, row in OIS_ROW.items():
                    a = num(motor("I%d" % (316 + row)))
                    if a and a > 0:
                        out["desk"]["ois_annuity"][tenor] = a
        if ex.VH_SHEET in index:
            get = reader(ex.VH_SHEET)
            C = ex.VH_COLS

            def iso(v: Any) -> Optional[str]:
                return serial_to_date(v).isoformat() if type(v) is float and 20000 < v < 80000 else None

            dates = [iso(get("A%d" % r)) for r in range(ex.VH_FIRST, ex.VH_FIRST + ex.VH_ROWS)] if full else []
            for k in range(ex.VH_SLOTS):
                slot = index_to_col(2 + k)
                ticker, expiry = get("%s4" % slot), get("%s5" % slot)
                if not isinstance(ticker, str) or not ticker.strip() or type(expiry) is not float:
                    continue
                name = get("%s6" % slot)
                c: Dict[str, Any] = {"ticker": ticker.strip(), "name": (name.split("·")[0].strip() if isinstance(name, str) else "") or ticker.strip(),
                                     "expiry": iso(expiry), "px": {}, "days": {}, "imp": {}, "ois360": {}, "baz": {}, "live": {}}
                for f in ("px", "days", "imp", "baz", "ois360"):
                    col = C[f][k]
                    if full:
                        for i, r in enumerate(range(ex.VH_FIRST, ex.VH_FIRST + ex.VH_ROWS)):
                            d = dates[i]
                            v = num(get("%s%d" % (col, r)))
                            if d and v is not None:
                                c[f][d] = v
                    v = num(get("%s%d" % (col, ex.VH_LIVE)))
                    if v is not None:
                        c["live"][f] = v
                out["viop"].append(c)
        if full and "C & R" in index and "Motor" in index:
            try:
                engine = svc._carry_engine(book, calc)
                horizons = svc._carry_horizons(book, calc)
                days_a = (horizons.get("a") or {}).get("days") or 0
                out["horizon_a"] = horizons.get("a")
                if days_a > 0:
                    out["carry"] = {m: (row["a"] * 5.0 / days_a if row.get("a") is not None else None) for m, row in engine.items()}
            except Exception:  # noqa: BLE001 - no carry is a signal without carry, not a failed fit
                out["carry"] = {}
        for x in EXTRAS:
            x.read_engine(out, index, reader, num)
        qv.read_engine(out, index, reader, num)
        return out

    def _quant_meta(self) -> Dict[str, Dict[str, str]]:
        try:
            source = self.svc.fx.source()
        except Exception:  # noqa: BLE001
            source = fxm.DEFAULT_SOURCE
        try:
            pairs = parse_pairs(self.settings().get("fx_pairs") or DEFAULTS["fx_pairs"])
        except ValueError:
            pairs = None
        return {s["key"]: s for s in series_specs(source, pairs)}

    def _fwd_scales(self, live: bool) -> Dict[str, int]:
        """Bloomberg's FWD_SCALE of each forward-points ticker (live only, asked once a day); 4 (2 for the yen) else."""
        out: Dict[str, int] = {}
        today = _dt.date.today().isoformat()
        for key, spec in self._quant_meta().items():
            if not key.startswith("FXP:"):
                continue
            pair = key.split(":")[1]
            hit = self._scale.get(spec["ticker"])
            if (hit is None or hit[0] != today) and live:
                v, _ = self.svc.fx.value(spec["ticker"], "FWD_SCALE")
                hit = (today, int(v) if v is not None and 0 <= v <= 6 else None)
                if hit[1] is not None:
                    self._scale[spec["ticker"]] = hit
            if hit and hit[1] is not None:
                out[pair] = hit[1]
        return out

    def _live_values(self, eng: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if not self.use_live:
            return out
        for label, v in eng.get("ois", {}).items():
            out["OIS:" + label] = v
        for label, v in eng.get("off", {}).items():
            out["OFF:" + label] = v
        if eng.get("tlref") is not None:
            out["TLREF"] = eng["tlref"]
        for c in eng.get("viop", []):
            live = c.get("live") or {}
            if live.get("imp") is not None:
                out["VIOPI:" + c["ticker"]] = live["imp"]
            if live.get("ois360") is not None:
                out["VIOPO:" + c["ticker"]] = live["ois360"]
        for key, spec in self._quant_meta().items():
            if spec.get("field", "PX_LAST") != "PX_LAST":
                continue                                    # a day's high / low (VİOP's USDTRY): no live value - not the spot's
            try:
                v, _ = self.svc.fx.value(spec["ticker"])
            except Exception:  # noqa: BLE001
                v = None
            if v is not None and math.isfinite(v):
                out[key] = v
        for x in EXTRAS:
            out.update(x.live_values(eng))
        out.update(qv.live_values(eng))
        return out

    def snapshot(self) -> Tuple[qf.Ctx, Dict[str, Any], Dict[str, float]]:
        """The closes, the workbook's part and the live values: the context the families run on."""
        from .history import day_flag
        from .xl.values import serial_to_date
        svc = self.svc
        cfg = self.settings()
        snap = svc.history.snapshot()
        today = snap["today"]
        start = (today - _dt.timedelta(days=int(int(cfg["lookback"]) * 1.5 + 260))).isoformat()
        defs = snap["defs"]
        data = self.store.hist_many([i for d in defs for i in d.ids()], start, today.isoformat())
        qmeta = self._quant_meta()
        try:
            fill = svc.history.fill_states()                # "geçmiş doluyor": the series whose first backfill still waits
        except Exception:  # noqa: BLE001 - the coverage table only
            fill = {}
        series: Dict[str, Dict[str, float]] = {}
        meta: Dict[str, Dict[str, Any]] = {}
        for d in defs:
            key = self._key_of(d)
            if key is None:
                continue
            _, points = d.pick(data)
            if d.group in ("off", "xccy") and key in series:
                continue                                    # one series per offshore tenor (the first, as the vol page takes it)
            label = d.label.strip().upper()
            if d.group == "Quant":
                spec = qmeta.get(key) or {"label": d.label, "kind": d.info.get("kind") or "index", "group": d.info.get("group") or "Global"}
                m = {"label": spec["label"], "kind": spec["kind"], "group": spec["group"], "ticker": d.ticker}
                if spec.get("universe"):
                    m["universe"] = True                    # (the G10 universe's own: not the desk's FX pair list)
            elif d.group == "ois":
                m = {"label": "%s OIS" % label, "kind": "rate", "months": d.months, "group": "ois", "ticker": d.ticker}
            elif d.group == "ref":
                m = {"label": "TLREF", "kind": "rate", "group": "ref", "ticker": d.ticker}
            elif d.group in ("off", "xccy"):
                m = {"label": "Offshore %s" % label, "kind": "rate", "months": d.months, "group": d.group, "ticker": d.ticker}
            else:
                info = d.info or {}
                m = {"label": info.get("name") or info.get("isin") or d.label, "kind": "rate" if d.unit == "pct" else "index",
                     "group": "dibs", "unit": d.unit, "maturity": info.get("maturity"), "name": info.get("name") or info.get("isin"),
                     "type": info.get("type"), "ticker": d.ticker}
            m["fill"] = fill.get(d.id)
            series[key] = points
            meta[key] = m
        eng = self._engine_read(True)
        raw_live = self._live_values(eng)
        viop = []
        for c in eng.get("viop", []):
            if not c["imp"]:
                continue
            series["VIOPI:" + c["ticker"]] = c["imp"]
            series["VIOPO:" + c["ticker"]] = c["ois360"]
            meta["VIOPI:" + c["ticker"]] = {"label": "VİOP %s ima" % c["name"], "kind": "rate", "group": "viop"}
            meta["VIOPO:" + c["ticker"]] = {"label": "VİOP %s OIS" % c["name"], "kind": "rate", "group": "viop"}
            viop.append(c)
        front = self._front(viop, today)
        if front is not None:
            series["VIOPI:FRONT"] = front["imp"]
            meta["VIOPI:FRONT"] = {"label": "VİOP ön vade ima (%s)" % front["name"], "kind": "rate", "group": "viop", "ticker": front["ticker"]}
            if front["live"].get("imp") is not None:
                raw_live["VIOPI:FRONT"] = front["live"]["imp"]
        mpc_days = self.store.mpc_days(start, today.isoformat())
        mpc = {"days": {d: dict(x, flag=day_flag(x)) for d, x in mpc_days.items()}, "values": self.store.mpc_values(start, today.isoformat())}
        holidays = {serial_to_date(x) for x in snap.get("holidays") or [] if 20000 < x < 80000}
        ctx = qf.Ctx(cfg, today, series, meta, raw_live, viop=viop, carry=eng.get("carry") or {}, mpc=mpc, path=self._path(mpc),
                     holidays=holidays, fwd_scale=self._fwd_scales(self.svc.mode == "live"), desk=eng.get("desk"))
        cfg["usdtry"] = ctx.usdtry()                    # the packages' TRY sizes (and a backtest's TRY P&L) at this USDTRY
        # (what the fit was made of: the backtest fits on it again, day by day)
        ctx.base = {"series": series, "meta": {k: dict(v) for k, v in meta.items()}, "viop": viop, "mpc": mpc, "holidays": holidays,
                    "fwd_scale": ctx.fwd_scale, "cfg": cfg, "today": today}
        return ctx, eng, raw_live

    @staticmethod
    def _path(mpc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The latest meeting path the history computed (today's, once its sync ran): spot, TLREF base, levels."""
        days = mpc.get("days") or {}
        good = [d for d, x in days.items() if x.get("flag") not in ("inconsistent", "error") and x.get("spot") and x.get("base") is not None]
        if not good:
            return None
        day = max(good)
        steps = sorted((_dt.date.fromisoformat(r["meeting"]), r["level"]) for r in mpc.get("values") or []
                       if r["day"] == day and r.get("level") is not None)
        if not steps:
            return None
        return {"day": day, "spot": _dt.date.fromisoformat(days[day]["spot"]), "base": days[day]["base"], "steps": steps,
                "fit_base": days[day].get("fit_base")}

    @staticmethod
    def _front(viop: List[Dict[str, Any]], today: _dt.date) -> Optional[Dict[str, Any]]:
        """The nearest VİOP contract at least 20 days from expiry: the front of the curve the correlations read."""
        best = None
        for c in viop:
            if not c.get("expiry"):
                continue
            left = (_dt.date.fromisoformat(c["expiry"]) - today).days
            if left >= 20 and (best is None or c["expiry"] < best["expiry"]):
                best = c
        return best

    @staticmethod
    def _key_of(d: Any) -> Optional[str]:
        if d.group == "Quant":
            return d.info.get("key")
        if d.group == "ois":
            return "OIS:" + d.label.strip().upper()
        if d.group == "ref":
            return "TLREF"
        if d.group in ("off", "xccy"):
            return "OFF:" + d.label.strip().upper()
        if d.group == "dibs":
            return "DIBS:" + str((d.info or {}).get("isin") or d.label).strip()
        return None

    # ================================================================== fit and refresh
    def compute(self) -> Dict[str, Any]:
        """The full fit (worker thread; tests call it directly): every family on a fresh snapshot."""
        with self._run:
            self._force = False
            self.state["phase"] = "fit"
            t0 = time.perf_counter()
            try:
                ctx, eng, raw_live = self.snapshot()
                cfg = ctx.cfg
                self._last_base = ctx.base
                items = [it for it in vc.parse_items(cfg["rv_items"]) if it.get("ok")]
                timing: Dict[str, float] = {}
                mons, tables = qf.run_all(ctx, items, timing, self.pause)
                imons, tables["intraday"] = self._intraday_step(ctx, raw_live)
                mons = mons + imons
                for x in EXTRAS:
                    x.run(ctx, eng, mons, tables, timing, self.pause)
                qp.run(self, ctx, mons, tables, raw_live, timing)          # the implied path, the WIRP (quantpath.py)
                ql.run(self, ctx, mons, tables, timing)                    # lead-lag (quantlead.py)
                qv.run(self, ctx, eng, mons, tables, timing)               # VİOP (quantviop.py)
                reg = qu.Registry(ctx, tables, eng)                        # the universe and the families on it (quantuniv.py)
                qu.run(ctx, reg, mons, tables, timing, self.pause)
                qf.score_all(ctx, mons, raw_live)
                fit = {"ctx": ctx, "mons": {m.sid: m for m in mons}, "tables": tables, "today": ctx.today_iso, "mark": self._data_mark(),
                       "cfg": cfg, "coverage": self._coverage(ctx), "registry": reg}
                with self._lock:
                    self._fit = fit
                self._publish(fit, raw_live, eng)
                ms = (time.perf_counter() - t0) * 1000.0
                self.state.update({"fit_at": _now().isoformat(sep=" "), "fit_ms": round(ms, 1), "timing": {k: round(v * 1000.0, 1) for k, v in timing.items()},
                                   "error": "", "fits": self.state["fits"] + 1, "live_t": time.time(), "live_at": _now().isoformat(sep=" ")})
                return self.status()
            finally:
                self.state["phase"] = "idle"

    def refresh_live(self) -> Dict[str, Any]:
        """The latest point with the live values: every monitor's level now (no fit)."""
        with self._run:
            fit = self._fit
            if fit is None:
                return self.status()
            t0 = time.perf_counter()
            eng = self._engine_read(False)
            raw_live = self._live_values(eng)
            ctx: qf.Ctx = fit["ctx"]
            by = {c["ticker"]: c for c in eng.get("viop", [])}
            for c in ctx.viop:
                if c["ticker"] in by:
                    c["live"] = by[c["ticker"]].get("live") or {}
            front = self._front(ctx.viop, ctx.today)
            if front is not None and front["live"].get("imp") is not None:
                raw_live["VIOPI:FRONT"] = front["live"]["imp"]
            qp.refresh(self, fit, raw_live)                                # the USD path now (quantpath.py)
            ql.refresh(self, fit)                                          # intraday bars, when there are some (quantlead.py)
            qv.refresh(self, fit)                                          # VİOP's 5-minute bars from Bloomberg, live (quantviop.py)
            ctx.live = dict(raw_live)
            imons, fit["tables"]["intraday"] = self._intraday_step(ctx, raw_live)
            for sid in [s for s, m in fit["mons"].items() if m.intraday]:
                del fit["mons"][sid]
            fit["mons"].update({m.sid: m for m in imons})
            qf.score_all(ctx, list(fit["mons"].values()), raw_live)
            self._publish(fit, raw_live, eng)
            self.state.update({"live_at": _now().isoformat(sep=" "), "live_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                               "refreshes": self.state["refreshes"] + 1, "live_t": time.time()})
            return self.status()

    def _publish(self, fit: Dict[str, Any], raw_live: Dict[str, float], eng: Dict[str, Any]) -> None:
        cfg = fit["cfg"]
        stamp = _now().strftime("%H:%M")
        signals = []
        for m in fit["mons"].values():
            s = qf.make_signal(m, cfg, stamp)
            if s is not None:
                s["day"] = fit["today"]
                signals.append(s)
        self._bt_attach(fit, signals, cfg)
        live, gated = qf.rank(signals)
        # the Sinyaller list: by group (G10 spot … Offshore), the confident lines by strength, then "düşük güven" -
        # the ones a gate holds: in the list, never logged nor alerted (quantuniv.order)
        ordered = qu.order(live, gated)
        ctx: qf.Ctx = fit["ctx"]
        view = {"signals": live, "gated": gated, "list": ordered, "tables": self._tables(fit, ctx), "live_keys": sorted(raw_live),
                "today": fit["today"], "at": _now().isoformat(sep=" ")}
        with self._lock:
            self._view = _clean(view)
            self.version += 1
        try:
            self._track(fit, live)
        except Exception as exc:  # noqa: BLE001 - the log is not worth the signals
            self.state["error"] = "kayıt: %s: %s" % (type(exc).__name__, str(exc)[:160])
        try:
            self.svc.nudge()
        except Exception:  # noqa: BLE001
            pass

    def _intraday_step(self, ctx: qf.Ctx, raw_live: Dict[str, float]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
        """The minute's values into the bars (live), and the intraday monitors on them."""
        now = _now()
        try:
            self.intraday.sample(raw_live, now)
            return self.intraday.monitors(ctx, now)
        except Exception as exc:  # noqa: BLE001 - the intraday part is not worth the daily one
            return [], {"ok": False, "why": "%s: %s" % (type(exc).__name__, str(exc)[:160]), "z": [], "rv": []}

    def _bt_attach(self, fit: Dict[str, Any], signals: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
        """Each signal with its family's backtest ("bu aile son 2 yılda 41 işlem, %58 isabet, ort. +0,4σ"; its type's when
        that has trades enough) and, if the desk set a floor, held back below it."""
        bt = self.backtest_result()
        fams = (bt or {}).get("families") or {}
        years = (bt or {}).get("years")
        for s in signals:
            fam = fams.get(s["family"])
            m = fit["mons"].get(s["id"])
            ty = ((fam or {}).get("types") or {}).get(qbt.bt_type(m)) if m is not None else None
            use = ty if ty and (ty.get("trades") or 0) >= 5 else fam
            if bt is None:
                s["bt"] = None
                continue
            short = {k: (use or {}).get(k) for k in ("trades", "hit", "avg_sigma", "avg", "unit", "avg_try", "sharpe", "max_dd")}
            s["bt"] = dict(short, text=qbt.bt_text(use, years), scope="tür" if use is ty and ty else "aile")
            why = qbt.bt_gate(fam, cfg)
            s["gates"].append({"name": "Geri test", "ok": not why, "text": why or s["bt"]["text"], "part": None})
            if why and not s["gated"]:
                s.update({"gated": why, "strength": "elendi", "composite": 0.0})

    def _tables(self, fit: Dict[str, Any], ctx: qf.Ctx) -> Dict[str, Any]:
        t = dict(fit["tables"])
        pca = dict(t.get("pca") or {})
        fn = pca.pop("factors", None)
        if callable(fn):
            pca["today"] = fn(ctx.derive_live(ctx.live))
        t["pca"] = pca
        macro = dict(t.get("macro") or {})
        rows = []
        for r in macro.get("rows") or []:
            r = dict(r)
            m = fit["mons"].get("macro:" + r.get("key", ""))
            attr = getattr(m, "_attr", None) if m is not None else None
            if attr is not None:
                cur = attr(ctx.derive_live(ctx.live))
                r["today"] = cur
                r["z"] = cur["resid"] / getattr(m, "_sigma") if cur and getattr(m, "_sigma", None) else None
            rows.append(r)
        macro["rows"] = rows
        t["macro"] = macro
        for name in ("pca", "pairs", "vol", "rv", "frapath", "viopcal", "fwdprem"):
            tab = t.get(name) or {}
            for r in tab.get("rows") or []:
                for key in ("sid", "vrp_sid", "vf_sid", "k_sid"):
                    m = fit["mons"].get(r.get(key)) if r.get(key) else None
                    if m is not None and m.z is not None:
                        r[{"sid": "z", "vrp_sid": "vrp_z", "vf_sid": "vf_z", "k_sid": "k_z"}[key]] = m.z
        mom = t.get("momentum") or {}
        for r in mom.get("rows") or []:
            m = fit["mons"].get("momentum:" + r["key"])
            if m is not None and m.z is not None:
                r["score"] = m.z
                r["level"] = m.level
        try:
            live = ctx.derive_live(ctx.live)
            rows = []
            for r in qf.fx_summary(ctx):
                rows.append(dict(r, spot=ctx.cur("FX:" + r["pair"], live)))
            t["fxsum"] = {"rows": rows, "threshold": float(fit["cfg"].get("fx_verdict", 0.3))}
        except Exception as exc:  # noqa: BLE001 - the summary is not worth the page
            t["fxsum"] = {"rows": [], "why": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        for x in EXTRAS:
            x.live_tables(t, ctx)
        return t

    @staticmethod
    def _coverage(ctx: qf.Ctx) -> List[Dict[str, Any]]:
        rows = []
        for key, m in sorted(ctx.meta.items(), key=lambda kv: (kv[1].get("group") or "", kv[0])):
            if key.startswith("DIBS:"):
                continue
            pts = ctx.pts(key)
            fill = m.get("fill")
            state = "geçmiş doluyor" if fill == "filling" else ("geçmiş yok" if fill == "none" or not pts else "var")
            rows.append({"key": key, "label": m.get("label") or key, "group": m.get("group") or "", "ticker": m.get("ticker") or "",
                         "n": len(pts), "first": pts[0][0] if pts else None, "last": pts[-1][0] if pts else None, "live": key in ctx.live,
                         "state": state, "universe": bool(m.get("universe"))})
        return rows

    # ================================================================== the log
    def _log(self) -> List[Dict[str, Any]]:
        v = self.store.get(self.LOG_KEY)
        return v if isinstance(v, list) else []

    def _track(self, fit: Dict[str, Any], live_signals: List[Dict[str, Any]]) -> None:
        """Write down the signals that crossed their entry threshold since the last look, and follow the open ones to
        their target, their stop or the end of ``log_days``."""
        cfg = fit["cfg"]
        today = fit["today"]
        stamp = _now()
        mons = fit["mons"]
        last = self.store.get(self.LAST_KEY)
        first_look = not isinstance(last, dict)
        last = last if isinstance(last, dict) else {}
        log = self._log()
        changed = False
        open_sids = {e["sid"] for e in log if e.get("status") == "open"}
        open_by = {e["sid"]: e for e in log if e.get("status") == "open"}
        logged_today = {e["sid"] for e in log if e.get("day") == today}
        new_alerts = []
        seq = max([int(e.get("seq") or 0) for e in log] or [0])
        for sg in live_signals:
            prev = last.get(sg["id"])
            prev_z = prev[0] if isinstance(prev, list) and prev else None
            daily = bool(sg.get("daily"))
            if daily:
                # a daily line (Trend's: there every day) is written down the first time on a day it is "YENİ" (its
                # direction turned since the previous close) - the entry of its old direction closing on it
                if first_look or not sg.get("new") or sg["id"] in logged_today:
                    continue
                old = open_by.get(sg["id"])
                if old is not None and old["dir"] != sg["direction"]:
                    pnl = old["dir"] * (sg["level"] - old["level"])
                    old.update({"status": "dönüş", "closed_day": today, "closed_time": stamp.strftime("%H:%M"), "closed_level": sg["level"],
                                "closed_z": sg["z"], "pnl": pnl, "pnl_sigma": pnl / old["scale"] if old.get("scale") else None,
                                "held": _bdays(old["day"], today)})
                    self._desk_close(old["sid"], "yön döndü")
                    open_sids.discard(sg["id"])
                    changed = True
                if sg["id"] in open_sids:
                    continue
            elif first_look or prev_z is None or abs(prev_z) >= sg["entry_z"] or sg["id"] in open_sids:
                continue
            seq += 1
            expires = None
            if sg.get("intraday"):
                mins = stamp.hour * 60 + stamp.minute + int(round(sg.get("hold") or 12)) * qi.BAR
                mins = min(mins, qi.SESSION[1])
                expires = "%02d:%02d" % (mins // 60, mins % 60)
            e = {"seq": seq, "sid": sg["id"], "family": sg["family"], "family_label": sg["family_label"], "asset": sg["asset"],
                 "group": sg.get("group"), "intraday": bool(sg.get("intraday")), "expires": expires,
                 "expression": sg["expression"], "dir": sg["direction"], "z": sg["z"], "entry_z": sg["entry_z"], "level": sg["level"],
                 "target": sg["target"], "stop": sg["stop"], "scale": sg["scale"], "unit": sg["unit"], "digits": sg["digits"], "strength": sg["strength"],
                 "composite": sg["composite"], "day": today, "time": stamp.strftime("%H:%M"), "status": "open"}
            if daily:
                e["daily"] = True                            # (followed to its stop or its direction's turn: no target, no time)
            log.append(e)
            open_sids.add(sg["id"])
            new_alerts.append(e)
            changed = True
        for e in log:
            if e.get("status") != "open":
                continue
            m = mons.get(e["sid"])
            level = m.level if m is not None else None
            held = _bdays(e["day"], today)
            # an intraday entry closes at its horizon or the session's end - and never lives over night
            gone = bool(e.get("intraday")) and (today != e["day"] or stamp.strftime("%H:%M") >= (e.get("expires") or "18:00"))
            if e.get("intraday") and today != e["day"]:
                level = None                                 # (today's monitor is another day's)
            if level is None:
                if held >= int(cfg["log_days"]) or gone:
                    e.update({"status": "veri yok", "closed_day": today, "closed_time": stamp.strftime("%H:%M"), "held": held})
                    self._desk_close(e["sid"], "veri yok")
                    changed = True
                continue
            s = e["dir"]
            outcome = None
            daily = bool(e.get("daily"))
            if not daily and e.get("target") is not None and s * (level - e["target"]) >= 0:
                outcome = "hedef"
            elif e.get("stop") is not None and s * (level - e["stop"]) <= 0:
                outcome = "stop"
            elif not daily and (held >= int(cfg["log_days"]) or gone):
                outcome = "süre"
            if outcome:
                pnl = s * (level - e["level"])
                e.update({"status": outcome, "closed_day": today, "closed_time": stamp.strftime("%H:%M"), "closed_level": level,
                          "closed_z": m.z, "pnl": pnl, "pnl_sigma": pnl / e["scale"] if e.get("scale") else None, "held": held})
                self._desk_close(e["sid"], {"hedef": "hedefe ulaştı", "stop": "stop oldu", "süre": "süresi doldu"}[outcome])
                changed = True
        if changed:
            opened = [e for e in log if e.get("status") == "open"]
            closed = [e for e in log if e.get("status") != "open"]
            self.store.put(self.LOG_KEY, closed[-(LOG_KEEP - len(opened)):] + opened if len(log) > LOG_KEEP else log)
        new_last = {sid: [m.z, today] for sid, m in mons.items() if m.z is not None}
        if new_last != last:
            self.store.put(self.LAST_KEY, new_last)
        for e in new_alerts:
            self._alert(e)

    def log_view(self) -> Dict[str, Any]:
        log = self._log()
        fams: Dict[str, Dict[str, Any]] = {}
        for e in log:
            f = fams.setdefault(e["family"], {"family": e["family"], "label": e.get("family_label") or qf.FAMILIES.get(e["family"], (e["family"],))[0],
                                              "n": 0, "open": 0, "hedef": 0, "stop": 0, "süre": 0, "veri yok": 0, "wins": 0, "pnl_sigma": [], "held": []})
            f["n"] += 1
            st = e.get("status")
            if st == "open":
                f["open"] += 1
                continue
            f[st] = f.get(st, 0) + 1
            if st == "hedef" or (st in ("süre", "dönüş") and (e.get("pnl") or 0) > 0):        # (dönüş: a daily line's turn)
                f["wins"] += 1
            if e.get("pnl_sigma") is not None:
                f["pnl_sigma"].append(e["pnl_sigma"])
            if e.get("held") is not None:
                f["held"].append(e["held"])
        rows = []
        for f in fams.values():
            closed = f["n"] - f["open"] - f.get("veri yok", 0)
            rows.append({"family": f["family"], "label": f["label"], "n": f["n"], "open": f["open"], "target": f["hedef"], "stop": f["stop"],
                         "expired": f["süre"], "nodata": f.get("veri yok", 0), "closed": closed, "hit_rate": f["wins"] / closed if closed else None,
                         "avg_pnl_sigma": sum(f["pnl_sigma"]) / len(f["pnl_sigma"]) if f["pnl_sigma"] else None,
                         "avg_held": sum(f["held"]) / len(f["held"]) if f["held"] else None})
        rows.sort(key=lambda r: r["label"])
        return _clean({"entries": list(reversed(log[-400:])), "families": rows})

    # ================================================================== alerts
    def _alerts(self) -> List[Dict[str, Any]]:
        v = self.store.get(self.ALERT_KEY)
        return v if isinstance(v, list) else []

    def _alert(self, e: Dict[str, Any]) -> None:
        with self._lock:
            self._alert_seq += 1
            a = {"seq": self._alert_seq, "sid": e["sid"], "family": e["family"], "family_label": e["family_label"], "asset": e["asset"],
                 "group": e.get("group"), "expression": e["expression"], "z": e["z"], "level": e["level"], "unit": e["unit"],
                 "digits": e["digits"], "strength": e["strength"], "day": e["day"], "time": e["time"]}
            self.store.put(self.ALERT_KEY, (self._alerts() + [a])[-ALERT_KEEP:])
        self._desk_alarm(a, e)
        for fn in list(self._hooks):
            try:
                fn(dict(a))
            except Exception:  # noqa: BLE001 - a listener that fails does not stop the others
                pass

    def _desk_alarm(self, a: Dict[str, Any], e: Dict[str, Any]) -> None:
        """A signal at least as strong as the desk's setting rings as one of the desk's alarms (deskalarms.py): for
        everyone, answered with "Gördüm", in the day's log - one alarm per signal (``quant:<id>``), closed when its log
        entry closes.  Muting is the desk's and personal (a trader mutes ``quant:<id>`` for themselves there): it
        fires all the same.  Without the desk's alarms (an older dashboard) nothing happens."""
        desk = getattr(self.svc, "desk_alarms", None)
        minimum = self.settings().get("desk_alarm") or "kapalı"
        if desk is None or minimum not in DESK_ALARM_CHOICES[1:]:
            return
        rank = {s: i for i, s in enumerate(qf.STRENGTHS)}
        if rank.get(a.get("strength"), -1) < rank[minimum]:
            return
        alarm = "quant:" + a["sid"]
        try:
            z = ("%+.2f" % a["z"]).replace(".", ",")
            desk.fired([{"id": alarm, "label": "Sinyal · %s: %s" % (a["family_label"], a["expression"]), "time": _now().strftime("%H:%M:%S"),
                         "mode": "level", "value_text": "z %s (%s)" % (z, a["strength"]),
                         "condition": "yön döndü (YENİ)" if e.get("daily") else "giriş eşiği |z| ≥ %s" % _txt(float(e.get("entry_z") or DEFAULTS["entry_z"])),
                         "measure_text": "",
                         "note": "Sinyaller sayfası", "by": ""}])
            self.svc.bump()                                  # the pages ask what fired
        except Exception:  # noqa: BLE001 - the desk's alarms are not worth the signal log
            pass

    def _desk_close(self, sid: str, why: str) -> None:
        desk = getattr(self.svc, "desk_alarms", None)
        if desk is not None:
            try:
                desk.close("quant:" + sid, why)
                self.svc.bump()                              # the top bar's count of open alarms
            except Exception:  # noqa: BLE001
                pass

    def add_alert_hook(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Called with every new signal alert ``{seq, sid, family, family_label, asset, group, expression, z, level,
        unit, strength, day, time}`` - for other listeners (the desk's alarms are wired in already: :meth:`_desk_alarm`)."""
        self._hooks.append(fn)

    def counters(self) -> Dict[str, int]:
        """What the live stream carries: the last alert's number and the version of the results."""
        return {"alerts": self._alert_seq, "version": self.version}

    def subscription(self, user: Optional[str]) -> Dict[str, Any]:
        user = self.svc.require_user(user)
        subs = self.store.get(self.SUBS_KEY) or {}
        mine = subs.get(user) if isinstance(subs, dict) else None
        out = {"on": False, "families": [], "groups": [], "min": "Zayıf"}
        if isinstance(mine, dict):
            out.update({k: mine[k] for k in out if k in mine})
        out["all_families"] = [{"id": k, "label": v[0]} for k, v in qf.FAMILIES.items()]
        out["all_groups"] = [{"id": g, "label": g, "slug": qu.SLUGS[g]} for g in qu.GROUPS]
        out["strengths"] = list(qf.STRENGTHS)
        return out

    def set_subscription(self, user: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
        user = self.svc.require_user(user)
        fams = [f for f in (data.get("families") or []) if f in qf.FAMILIES]
        groups = [g for g in (data.get("groups") or []) if g in qu.GROUPS]
        minimum = data.get("min") if data.get("min") in qf.STRENGTHS else "Zayıf"
        subs = self.store.get(self.SUBS_KEY)
        subs = subs if isinstance(subs, dict) else {}
        subs[user] = {"on": bool(data.get("on")), "families": fams, "groups": groups, "min": minimum}
        self.store.put(self.SUBS_KEY, subs)
        return self.subscription(user)

    def alerts(self, user: Optional[str], since: Any = None) -> Dict[str, Any]:
        """The alerts after ``since`` that ``user`` subscribed to - its families and groups (none chosen: all), at
        least its strength (``since`` empty: none - only the last number)."""
        sub = self.subscription(user)
        try:
            since_n = int(since) if since not in (None, "") else None
        except (TypeError, ValueError):
            since_n = None
        items = []
        if since_n is not None and sub["on"]:
            rank = {s: i for i, s in enumerate(qf.STRENGTHS)}
            for a in self._alerts():
                if int(a.get("seq") or 0) <= since_n:
                    continue
                if sub["families"] and a["family"] not in sub["families"]:
                    continue
                if sub.get("groups") and a.get("group") not in sub["groups"]:
                    continue
                if rank.get(a.get("strength"), 0) < rank.get(sub["min"], 0):
                    continue
                items.append(a)
        return _clean({"alerts": items[-20:], "last": self._alert_seq, "on": sub["on"]})

    # ================================================================== what the pages read
    def pages(self) -> List[Dict[str, Any]]:
        """The pages for the menu, in ``MENU``'s order: a page of an entry with tabs names its entry (``menu``,
        ``menu_title``) and its tab (``tab``); a page the menu does not name comes last, an entry of its own."""
        def page(pid: str, title: str) -> Dict[str, Any]:
            return {"id": pid, "title": title, "group": "Quant", "book": "tto", "sheet": None, "custom": True}

        titles = dict(PAGES)
        out = []
        for mid, name, tabs in MENU:
            for pid, tab in tabs:
                if pid in titles:
                    p = page(pid, titles.pop(pid))
                    if len(tabs) > 1:
                        p.update({"menu": mid, "menu_title": name, "tab": tab})
                    out.append(p)
        return out + [page(pid, title) for pid, title in PAGES if pid in titles]

    def status(self) -> Dict[str, Any]:
        st = {k: v for k, v in self.state.items() if k != "live_t"}
        st.update({"ready": self._view is not None, "version": self.version, "running": self._thread is not None and self._thread.is_alive(),
                   "mode": self.svc.mode, "alerts": self._alert_seq, "bt_running": self._bt_thread is not None and self._bt_thread.is_alive()})
        fit = self._fit
        if fit is not None:
            st.update({"monitors": len(fit["mons"]), "today": fit["today"], "errors": fit["tables"].get("errors") or {},
                       "filling": sum(1 for c in fit["coverage"] if c.get("state") == "geçmiş doluyor")})
        return _clean(st)

    def view(self, what: str, user: Optional[str], q: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.svc.require_user(user)
        q = q or {}
        for x in EXTRAS:
            if what in getattr(x, "QUERIES", ()):
                return _clean(x.query(what, q, self.store, self._fit))
        if what == "status":
            return self.status()
        if what == "settings":
            return self.settings_view()
        if what == "subscription":
            return _clean(self.subscription(user))
        if what == "alerts":
            return self.alerts(user, q.get("since"))
        if what == "log":
            return self.log_view()
        if what == "backtest":
            return self.backtest_view()
        if what == "box":
            return self.box_view(q)
        v = self._view
        fit = self._fit
        base = {"ready": v is not None, "status": self.status(), "version": self.version}
        if v is None or fit is None:
            return base
        t = v["tables"]
        if what in qp.VIEWS:                                # İma Patikası, TCMB WIRP (quantpath.py)
            return qp.view(self, what, base, v, fit)
        if what in ql.VIEWS:                                # Öncü-Takipçi (quantlead.py)
            return ql.view(self, what, base, v, fit)
        if what in qv.VIEWS:                                # VİOP (quantviop.py)
            return qv.view(self, what, base, v, fit)
        if what in qtr.VIEWS:                               # Trend (quanttrend.py)
            return qtr.view(self, what, base, v, fit)
        if what == "signals":
            # the list (quantuniv.order): every group's confident lines, then its "düşük güven" ones; ``group`` one group
            fam, asset, group = q.get("family") or "", q.get("asset") or "", q.get("group") or ""
            mine = [s for s in v["list"] if self._keep(s, fam, asset)]
            counts = {}
            for s in v["signals"]:
                counts[s["family"]] = counts.get(s["family"], 0) + 1
            families = [{"id": k, "label": lbl, "kind": kind, "page": page, "live": counts.get(k, 0),
                         "monitors": sum(1 for m in fit["mons"].values() if m.family == k)} for k, (lbl, kind, page) in qf.FAMILIES.items()]
            base.update({"signals": [s for s in mine if not group or s.get("group") == group],
                         "gated": [s for s in v["gated"] if self._keep(s, fam, asset)][:60], "groups": qu.group_counts(mine), "group": group,
                         "families": families, "assets": list(qf.ASSETS), "settings": fit["cfg"], "today": v["today"], "at": v["at"],
                         "hits": self.log_view()["families"], "coverage": fit["coverage"]})
            return _clean(base)
        if what == "signal":
            return self.signal_view(q.get("id"))
        if what == "universe":
            return self.universe_view()
        pages = {"corr": ("corr",), "pca": ("pca", "rv", "frapath"), "pairs": ("pairs", "viopcal"), "regime": ("momentum", "cycle", "regime"),
                 "fx": ("fxsum", "vol", "emcarry", "fwdprem"), "macro": ("macro",), "model": ("model",), "intraday": ("intraday",)}
        pages.update({x.VIEW: x.TABLES for x in EXTRAS})
        if what not in pages:
            raise QuantError("bilinmeyen görünüm: %s" % what)
        for name in pages[what]:
            base[name] = t.get(name)
        base["signals"] = [s for s in v["signals"] + v["gated"] if s["page"] == "quant-" + what]
        base["settings"] = fit["cfg"]
        # (a page's coverage: its own series - the G10 universe's are the families', on Sinyaller)
        base["coverage"] = [c for c in fit["coverage"] if self._covers(what, c["key"]) and not c.get("universe")]
        base["errors"] = {k: e for k, e in (t.get("errors") or {}).items() if k in pages[what] or (what == "fx" and k == "vol")}
        return _clean(base)

    #: the boxes of the quant pages (``/api/quant/box?of=``)
    BOXES = ("signals", "viop", "wirp", "fxsum")

    def box_view(self, q: Dict[str, Any]) -> Dict[str, Any]:
        """What a box of a quant page reads - on a launchpad, in the side drawer, in a window of its own: a light part
        of its page.  ``of``: ``signals`` the live list (``family`` / ``asset`` filter it as the page does), ``viop``
        the contracts now with their order levels, ``wirp`` each bank's meeting table (without the matrices and the
        history), ``fxsum`` the pair summary.  ``version`` is the result's: a box asks again when the live stream says
        it moved (VİOP's live part is made again on each read, from the minute's live values - a version of its own)."""
        of = q.get("of") or ""
        if of not in self.BOXES:
            raise QuantError("bilinmeyen kutu: %s" % str(of)[:40])
        v, fit = self._view, self._fit
        out: Dict[str, Any] = {"of": of, "ready": v is not None and fit is not None, "version": self.version}
        if not out["ready"]:
            out["error"] = self.state.get("error") or ""
            return _clean(out)
        out.update({"at": v.get("at"), "entry_z": fit["cfg"].get("entry_z")})
        if of == "signals":
            # (the page's list, its filters: a family, an asset, a group)
            fam, asset, group = q.get("family") or "", q.get("asset") or "", q.get("group") or ""
            out["signals"] = [s for s in v["list"] if self._keep(s, fam, asset) and (not group or s.get("group") == group)]
            out["family_label"] = qf.FAMILIES[fam][0] if fam in qf.FAMILIES else ""
            out["families"] = [{"id": k, "label": x[0]} for k, x in qf.FAMILIES.items()]          # (the box's filter)
            out["assets"] = list(qf.ASSETS)
            out["groups"] = list(qu.GROUPS)
        elif of == "viop":
            page = qv.view(self, "viop", {}, v, fit)
            tab = page.get("viop") or {}
            live = tab.get("live") or {}
            out.update({"rows": live.get("rows") or [], "why": live.get("why") or tab.get("why") or "", "live_at": live.get("at"),
                        "mode": page.get("mode") or ""})
        elif of == "wirp":
            page = qp.view(self, "wirp", {}, v, fit)
            light = ("bank", "label", "ok", "why", "grid", "day", "policy", "base", "live", "check")
            out["banks"] = {k: dict({x: b.get(x) for x in light},
                                    rows=[{f: y for f, y in r.items() if f not in ("matrix", "dist")} for r in b.get("rows") or ()])
                            for k, b in ((page.get("wirp") or {}).get("banks") or {}).items()}
        else:
            out["fxsum"] = v["tables"].get("fxsum") or {}
        return _clean(out)

    @staticmethod
    def _keep(s: Dict[str, Any], fam: str, asset: str) -> bool:
        return (not fam or s["family"] == fam) and (not asset or s["asset"] == asset)

    def universe_view(self) -> Dict[str, Any]:
        """The universe of the families on it (quantuniv.py): every trade line and input with its group, level, σ,
        carry, size and the money of a unit move - what they read, as of the last fit and the values now."""
        fit = self._fit
        if fit is None or fit.get("registry") is None:
            return {"ready": False}
        reg: qu.Registry = fit["registry"]
        ctx: qf.Ctx = fit["ctx"]
        try:
            out = reg.table(ctx.derive_live(ctx.live))
        except Exception as exc:  # noqa: BLE001 - the table is not worth the page
            out = {"rows": [], "inputs": [], "why": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        out.update({"ready": True, "today": fit["today"], "families": [{"id": k, "label": x[0], "plugged": k in qu.RUNNERS}
                                                                     for k, x in qu.FAMILIES.items()]})
        return _clean(out)

    @staticmethod
    def _covers(what: str, key: str) -> bool:
        for x in EXTRAS:
            if what == x.VIEW:
                return x.covers(key)
        if what == "viop":
            return qv.covers(key)
        if what == "corr":
            return key in qf.CORR_UNIVERSE
        if what == "pca":
            return key.startswith("OIS:") or key == "TLREF"
        if what == "pairs":
            return key.startswith(("OFF:", "OIS:", "VIOP", "USD:", "FXP:USDTRY"))
        if what == "regime":
            return any(key == k for k, _ in qf.MOM_UNIVERSE) or key == "TLREF" or key.startswith(("FX:", "XR:"))
        if what == "fx":
            return key.startswith(("FX", "FWD", "XR:"))
        if what == "macro":
            return key in qf.MACRO_DRIVERS or key in qf.MACRO_TARGETS
        if what == "model":
            return key in qf.MODEL_UNIVERSE
        if what == "intraday":
            return key in qi.KEYS
        return False

    def signal_view(self, sid: Any) -> Dict[str, Any]:
        """One monitor in depth: its series and z, the window's mean, entry / target / stop - what a click draws."""
        fit = self._fit
        v = self._view
        if fit is None or v is None:
            return {"ready": False}
        m = fit["mons"].get(str(sid or ""))
        if m is None:
            raise QuantError("böyle bir sinyal yok: %s" % sid)
        sg = next((s for s in v["signals"] + v["gated"] if s["id"] == m.sid), None)
        hist = m.history()
        try:
            why = qf.rationale(fit["ctx"], m, sg, fit["cfg"])
        except Exception as exc:  # noqa: BLE001 - the rationale is not worth the chart
            why = {"analogs": [], "invalidation": [], "why": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        return _clean({"ready": True, "signal": sg, "rationale": why, "monitor": {"sid": m.sid, "family": m.family, "family_label": qf.FAMILIES[m.family][0],
                                                                 "name": m.name, "level": m.level, "z": m.z, "unit": m.unit, "digits": m.digits,
                                                                 "series_label": m.series_label,
                                                                 "half_life": m.half_life, "regime": m.regime, "note": m.note, "mode": m.mode,
                                                                 "entry": m.entry or fit["cfg"]["entry_z"], "score_name": m.score_name,
                                                                 "info": {k: x for k, x in m.info.items() if k not in ("inputs",)}},
                       "history": hist, "today": fit["today"], "settings": fit["cfg"]})

    def action(self, what: str, user: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
        for x in EXTRAS:
            if what in getattr(x, "ACTIONS", ()):
                try:
                    return _clean(x.act(what, self.svc.require_user(user), data, self.store))
                except ValueError as exc:
                    raise QuantError(str(exc))
        if what == "settings":
            out = self.set_settings(user, data.get("values") if isinstance(data.get("values"), dict) else data)
            return out
        if what == "subscription":
            return _clean(self.set_subscription(user, data))
        if what == "recompute":
            self.svc.require_user(user)
            self._force = True
            if self._thread is None:                        # (no worker: the tests, or the history switched off)
                return self.compute()
            self.kick()
            return self.status()
        raise QuantError("bilinmeyen işlem: %s" % what)


def _txt(v: float) -> str:
    return ("%g" % v).replace(".", ",")
