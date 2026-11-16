"""Synthetic market history for the ML family (``tto/quantml.py``): every line of its universe as random walks of
realistic size - the G10 spots, their 3M points, ATM / RR / BF vols, the TRY OIS curve (a level that walks, a slope and a
curvature that revert), offshore, USDTRY / EURTRY and their points, three DİBS around 2, 5 and 10 years, two VİOP
contracts, the global drivers, TLREF and the meeting path - and, when asked, a **planted** line whose daily move follows
a driver's moves of the week before with a lag (``plant``): what it does over the next five days is partly known at
the close (the driver's last five moves, the day before), nothing else in the data is."""
from __future__ import annotations

import datetime as dt
import math
import random
from typing import Any, Dict, List, Optional, Tuple

import quant_synth
from tto import quantfam as qf
from tto import quantopt as qopt
from tto import quantuniv as qu
from tto import quantviop as qv

TODAY = dt.date(2026, 11, 3)
MONTHS = {"1W": 0.25, "2W": 0.5, "1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12, "15M": 15, "18M": 18, "21M": 21, "2Y": 24,
          "3Y": 36, "4Y": 48, "5Y": 60, "6Y": 72, "7Y": 84, "8Y": 96, "9Y": 108, "10Y": 120}
G10_SPOT = {"EURUSD": 1.10, "USDJPY": 150.0, "GBPUSD": 1.27, "AUDUSD": 0.66, "USDCAD": 1.37, "USDCHF": 0.88, "NZDUSD": 0.60}
EM = {"USDZAR": 18.0, "USDMXN": 18.5, "USDBRL": 5.4}
#: each pair's 3M forward points (pips): AUDUSD's below spot - a long earns the carry (its planted line is not held back
#: by the FX carry gate)
POINTS = {"USDJPY": -80.0, "AUDUSD": -25.0}
#: DİBS of the synthetic list: (ISIN, years to maturity from TODAY, coupon %)
BONDS = (("TRT100128T10", 1.9, 30.0), ("TRT150531T17", 4.6, 28.0), ("TRT120836T13", 9.8, 26.0))
CONTRACTS = ("A1Z6 Curncy", "A1H7 Curncy")
#: the drivers and inputs a context keeps whatever lines it keeps (``context(keep=...)``)
DRIVERS = ("UST:2Y", "UST:10Y", "DXY", "BRENT", "CDS", "TLREF", "USD:1M", "USD:3M", "USD:6M", "USD:1Y")
MEETINGS = ("2026-12-10", "2027-01-21", "2027-03-04")
#: the planted line, its driver and how much of the driver's % move the line makes (per cent a day)
PLANT = {"key": "FX:AUDUSD", "driver": "BRENT", "beta": 0.06, "noise": 0.30, "shock": 2.5}


def _walk(rnd: random.Random, n: int, start: float, sd: float, log: bool = False) -> List[float]:
    out, x = [], start
    for _ in range(n):
        x = x * math.exp(rnd.gauss(0, sd)) if log else x + rnd.gauss(0, sd)
        out.append(x)
    return out


def _ar(rnd: random.Random, n: int, mean: float, b: float, sd: float) -> List[float]:
    out, x = [], mean
    for _ in range(n):
        x = mean + b * (x - mean) + rnd.gauss(0, sd)
        out.append(x)
    return out


def build(today: dt.date = TODAY, n: int = 460, seed: int = 7, plant: Optional[Dict[str, Any]] = None) -> Tuple[List[str], Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
    """``(days, series, meta)``: every key the ML family's universe and inputs read, over the ``n`` business days before
    ``today``.  ``plant``: ``{"key", "driver", "beta", "noise", "shock"}`` - the line's daily move (% for FX, bp for a
    rate) is ``beta`` × the driver's moves of two to six days before (each move pushes the line for a week, a day late)
    + noise; ``shock``: the driver's last five moves (% a day) - today's prediction is then a clear one; ``None``:
    every line is a random walk."""
    rnd = random.Random(seed)
    days = quant_synth.business_days(today, n)
    series: Dict[str, Dict[str, float]] = {}
    meta: Dict[str, Dict[str, Any]] = {}

    def put(key: str, values: List[float], **m: Any) -> None:
        series[key] = dict(zip(days, values))
        meta[key] = m

    # ---- the drivers
    put("UST:2Y", _walk(rnd, n, 3.8, 0.04), label="UST 2Y", kind="rate", group="Global")
    put("UST:10Y", _walk(rnd, n, 4.3, 0.05), label="UST 10Y", kind="rate", group="Global")
    put("DXY", _walk(rnd, n, 100.0, 0.004, True), label="DXY", kind="index", group="Global")
    put("BRENT", _walk(rnd, n, 70.0, 0.018, True), label="Brent", kind="index", group="Global")
    put("CDS", [max(50.0, v) for v in _walk(rnd, n, 280.0, 6.0)], label="CDS", kind="bp", group="Global")
    for key in ("USD:1M", "USD:3M", "USD:6M", "USD:1Y"):
        put(key, _walk(rnd, n, 4.0, 0.01), label=key, kind="rate", group="Global")
    tl, level = [], 41.0
    for i in range(n):
        if i % 30 == 29:
            level -= 1.0 if i < n // 2 else -0.5
        tl.append(level + rnd.gauss(0, 0.03))
    put("TLREF", tl, label="TLREF", kind="rate", group="ref")
    for pair, s0 in EM.items():
        put("FX:" + pair, _walk(rnd, n, s0, 0.008, True), label=pair, kind="fx", group="EM")
    # ---- the TRY OIS curve: a level that walks, a slope and a curvature that revert
    lv = _walk(rnd, n, 38.0, 0.06)
    sl = _ar(rnd, n, -2.0, 0.98, 0.05)
    cu = _ar(rnd, n, 0.0, 0.95, 0.03)
    span = math.log(120.0) - math.log(0.25)
    for label, mo in MONTHS.items():
        x = (math.log(mo) - math.log(0.25)) / span - 0.5
        put("OIS:" + label, [lv[i] + sl[i] * x + cu[i] * (x * x - 0.25) + rnd.gauss(0, 0.01) for i in range(n)], label=label + " OIS", kind="rate",
            months=float(mo), group="ois")
    for label in ("1M", "3M", "1Y"):
        base = series["OIS:" + label]
        put("OFF:" + label, [base[d] - 2.0 + rnd.gauss(0, 0.05) for d in days], label="Offshore " + label, kind="rate", months=float(MONTHS[label]), group="off")
    # ---- G10: spots (carry from 3M points), ATM / RR / BF vols
    for pair, s0 in G10_SPOT.items():
        put("FX:" + pair, _walk(rnd, n, s0, 0.005, True), label=pair, kind="fx", group="G10", universe=pair == "NZDUSD")
        pts = POINTS.get(pair, 25.0)
        put("FXP:%s:3M" % pair, [pts + rnd.gauss(0, 1.0) for _ in range(n)], label=pair + " 3M swap puanı", kind="pts", group="G10")
        for vk, tenor in qu.G10_VOLS:
            mean = 8.0 if vk == "ATM" else (0.4 if vk == "RR25" else 0.25)
            put(qopt.key(pair, vk, tenor), _ar(rnd, n, mean, 0.97, 0.15 if vk == "ATM" else 0.05), label=qopt.label(pair, vk, tenor), kind="vol", group="G10")
    # ---- USDTRY, EURTRY and their points
    usdtry = [42.0 * math.exp(0.0007 * i + rnd.gauss(0, 0.002)) for i in range(n)]
    put("FX:USDTRY", usdtry, label="USDTRY", kind="fx", group="TRY")
    for tenor, dd in (("1M", 30.4), ("3M", 91.25), ("6M", 182.5), ("1Y", 365.0)):
        put("FXP:USDTRY:" + tenor, [s * (0.30 + rnd.gauss(0, 0.005)) * dd / 365.0 * 1e4 for s in usdtry], label="USDTRY %s swap puanı" % tenor, kind="pts",
            group="TRY")
    eurtry = [usdtry[i] * series["FX:EURUSD"][d] for i, d in enumerate(days)]
    put("FX:EURTRY", eurtry, label="EURTRY", kind="fx", group="TRY")
    put("FXP:EURTRY:3M", [s * 0.28 * 91.25 / 365.0 * 1e4 for s in eurtry], label="EURTRY 3M swap puanı", kind="pts", group="TRY")
    # ---- DİBS: the curve's level + a spread of each
    for isin, years, _ in BONDS:
        spread = 1.0 - 0.2 * years
        put("DIBS:" + isin, [lv[i] + spread + rnd.gauss(0, 0.03) for i in range(n)], label=isin, kind="rate", group="dibs", unit="pct",
            maturity=(today + dt.timedelta(days=int(years * 365.25))).isoformat(), type="S", name="")
    # ---- VİOP: two contracts priced at the 3M OIS + 2 % against USD
    hol: set = set()
    for t in CONTRACTS:
        _, month, digits, _ = qv.parse_ticker(t)
        exp = qv.expiry_of(qv.year_of(digits, today), month, hol)
        px = {}
        for i, d in enumerate(days):
            g = qv.days_to(exp, d, hol)
            if g > 0:
                r = series["OIS:3M"][d] / 100.0 + 0.02
                px[d] = usdtry[i] * (1.0 + r * g / 360.0) / (1.0 + 0.04 * g / 360.0)
        series["VIOPF:" + t] = px
        meta["VIOPF:" + t] = {"label": "VİOP %s kapanış" % t, "kind": "px", "group": "VİOP"}
    # ---- the planted line: each driver move pushes it for a week, starting the day after the next
    if plant:
        if plant.get("shock"):
            drv = [series[plant["driver"]][d] for d in days]
            for i in range(n - 5, n):
                drv[i] = drv[i - 1] * math.exp(plant["shock"] / 100.0)
            series[plant["driver"]] = dict(zip(days, drv))
        drv = [series[plant["driver"]][d] for d in days]
        moves = [0.0] + [math.log(b / a) * 100.0 if meta[plant["driver"]]["kind"] in ("fx", "index") else (b - a) for a, b in zip(drv, drv[1:])]
        old = [series[plant["key"]][d] for d in days]
        kind = meta[plant["key"]]["kind"]
        x = old[0]
        out = [x]
        for s in range(1, n):
            push = plant["beta"] * sum(moves[s - j] for j in range(2, 7) if s - j >= 1)
            step = push + rnd.gauss(0, plant["noise"])
            x = x * math.exp(step / 100.0) if kind == "fx" else x + step / 100.0
            out.append(x)
        series[plant["key"]] = dict(zip(days, out))
    return days, series, meta


def mpc_of(days: List[str]) -> Dict[str, Any]:
    """Each day's meeting path (three meetings ahead, one cut each, the market's level moving a little)."""
    rnd = random.Random(3)
    out: Dict[str, Any] = {"days": {}, "values": []}
    drift = 0.0
    for d in days:
        drift += rnd.gauss(0, 0.0003)
        spot = qf.business_on_or_after(dt.date.fromisoformat(d) + dt.timedelta(days=1), set()).isoformat()
        out["days"][d] = {"spot": spot, "base": 0.40, "status": "OK"}
        for k, m in enumerate(MEETINGS):
            out["values"].append({"day": d, "meeting": m, "level": 0.40 - 0.01 * (k + 1) + drift})
    return out


def eng_rows(today: dt.date = TODAY) -> Dict[str, Any]:
    """The workbook's part the registry reads: the DİBS RV rows (by ISIN)."""
    rows = []
    for k, (isin, years, cpn) in enumerate(BONDS):
        rows.append({"isin": isin, "type": "S", "row": 5 + k, "name": "", "maturity": (today + dt.timedelta(days=int(years * 365.25))).isoformat(),
                     "coupon": cpn, "freq": 2.0, "simple": 0.35, "compound": 0.38, "source": ""})
    return {"dibs": rows}


def context(today: dt.date = TODAY, n: int = 460, seed: int = 7, plant: Optional[Dict[str, Any]] = None, live: Optional[Dict[str, float]] = None,
            mpc: Optional[Dict[str, Any]] = None, cfg: Optional[Dict[str, Any]] = None, keep: Optional[set] = None):
    """A context of the synthetic history (``keep``: only these keys and the drivers) and the workbook's part."""
    from tto import quant as qq
    days, series, meta = build(today, n, seed, plant)
    if keep is not None:
        always = set(DRIVERS) | {"FX:" + p for p in EM} | {"FX:USDTRY"}
        drop = [k for k in series if k not in keep and k not in always]
        for k in drop:
            series.pop(k, None)
            meta.pop(k, None)
    conf = dict(qq.DEFAULTS, usdtry=42.0)
    conf.update(cfg or {})
    ctx = qf.Ctx(conf, today, series, meta, live or {}, mpc=mpc if mpc is not None else mpc_of(days[-120:] + [today.isoformat()]))
    return ctx, eng_rows(today), days


def seed(svc, n: int = 460, seed_: int = 7, plant: Optional[Dict[str, Any]] = None) -> List[str]:
    """Write the synthetic history into ``svc``'s store under the ids of the history's own definitions (the keys the
    store has a definition of: the TRY OIS curve, offshore, TLREF, the quant package's series)."""
    from tto.quant import Quant
    snap = svc.history.snapshot()
    days, series, _ = build(snap["today"], n, seed_, plant)
    defs = {}
    for d in snap["defs"]:
        k = Quant._key_of(d)
        if k and k not in defs:
            defs[k] = d
    for k, points in series.items():
        d = defs.get(k)
        if d is None:
            continue
        for sid in d.ids():
            svc.store.hist_delete(sid)
        svc.store.hist_upsert(d.id, sorted(points.items()))
    svc.history.rev += 1
    return days
