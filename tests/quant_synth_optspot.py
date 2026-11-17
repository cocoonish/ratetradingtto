"""Synthetic history for the Opsiyon → spot family (``tto/quantoptspot.py``): the seven G10 pairs and USDTRY - spot,
forward points, ATM 1M / 3M, 25D RR 1M / 3M, 25D BF 3M - and EURTRY's spot and points (no options, as the history keeps
it); and, when asked, a **planted** lead: a pair's spot follows its 1M risk reversal's daily moves over the next five
days (``leads``: pair -> the spot's % per vol point of the RR's move, + the same way, − the other way), weeks that are
bigger when the wings (BF 3M) were rich (``bf_vol``), and the RR's last closes pushed (``shock``: pair -> vol points
over the last four closes) so that today's reading is a clear one."""
from __future__ import annotations

import datetime as dt
import math
import random
from typing import Any, Dict, List, Optional, Tuple

import quant_synth
from tto import quantfam as qf
from tto import quantopt as qopt

TODAY = dt.date(2026, 11, 3)
SPOT = {"EURUSD": 1.10, "USDJPY": 150.0, "GBPUSD": 1.27, "AUDUSD": 0.66, "USDCAD": 1.37, "USDCHF": 0.88, "NZDUSD": 0.60, "USDTRY": 42.0}
ATM = {"USDJPY": 9.0, "USDTRY": 12.0}                      # (8 vol the rest)
RR = {"EURUSD": -0.3, "USDJPY": -0.8, "GBPUSD": -0.5, "AUDUSD": -0.9, "USDCAD": 0.4, "USDCHF": 0.2, "NZDUSD": -0.8, "USDTRY": 3.0}
RR_SD = {"USDTRY": 0.2}                                    # the 1M RR's daily move (0,12 vol the rest)
#: each pair's 3M forward points (pips); USDTRY's term structure from its ~30 % carry
POINTS = {"USDJPY": -80.0, "AUDUSD": -25.0, "USDCHF": -60.0}
BF_MEAN, BF_B, BF_SD = 0.30, 0.98, 0.015
#: the spot's move with its RR's on the same day (% a vol point): spot and skew move together, as they do - the
#: divergence is what the spot has not done of it
COMOVE = 1.5
#: the planted lines of the tests: USDJPY and USDTRY follow their RR, EURUSD goes the other way
LEADS = {"USDJPY": 1.0, "EURUSD": -1.0, "USDTRY": 1.2}
#: today: USDJPY's and EURUSD's RR up (calls bid), USDTRY's down (USD puts bid: SAT USDTRY earns the carry)
SHOCK = {"USDJPY": 0.7, "EURUSD": 0.7, "USDTRY": -1.6}


def _ar(rnd: random.Random, n: int, mean: float, b: float, sd: float, shocks: Optional[List[float]] = None) -> Tuple[List[float], List[float]]:
    """An AR(1) around ``mean`` and its own shocks (given ones, or N(0, sd))."""
    eps = shocks if shocks is not None else [rnd.gauss(0, sd) for _ in range(n)]
    out, x = [], mean
    for e in eps:
        x = mean + b * (x - mean) + e
        out.append(x)
    return out, eps


def build(today: dt.date = TODAY, n: int = 500, seed: int = 11, leads: Optional[Dict[str, float]] = None,
          shock: Optional[Dict[str, float]] = None, bf_vol: float = 0.0) -> Tuple[List[str], Dict[str, Dict[str, float]], Dict[str, Dict[str, Any]]]:
    """``(days, series, meta)`` over the ``n`` business days before ``today``.  Every spot moves with its 1M RR the same
    day (``COMOVE``) plus noise of its ATM's size; a pair of ``leads`` also by lead × its RR's moves of the five days
    before (% a vol point); ``bf_vol``: every pair's daily noise is × (1 + bf_vol × the BF's z of the day before) - rich
    wings, bigger weeks; ``shock``: the RR's last four closes moved by that many vol points in all (its 3M by 0,6)."""
    rnd = random.Random(seed)
    leads, shock = leads or {}, shock or {}
    days = quant_synth.business_days(today, n)
    series: Dict[str, Dict[str, float]] = {}
    meta: Dict[str, Dict[str, Any]] = {}

    def put(key: str, values: List[float], **m: Any) -> None:
        series[key] = dict(zip(days, values))
        meta[key] = m

    bf_sd_eq = BF_SD / math.sqrt(1.0 - BF_B * BF_B)
    for pair, s0 in SPOT.items():
        group = "TRY" if "TRY" in pair else "G10"
        atm0 = ATM.get(pair, 8.0)
        sd = RR_SD.get(pair, 0.12)
        eps = [rnd.gauss(0, sd) for _ in range(n)]
        if shock.get(pair):
            for i in range(n - 4, n):
                eps[i] += shock[pair] / 4.0
        rr1, eps = _ar(rnd, n, RR[pair], 0.99, sd, eps)
        rr3, _ = _ar(rnd, n, RR[pair], 0.99, 0.0, [0.6 * e + rnd.gauss(0, 0.04) for e in eps])
        a1, ea = _ar(rnd, n, atm0, 0.98, 0.15)
        a3, _ = _ar(rnd, n, atm0, 0.99, 0.0, [0.5 * e + rnd.gauss(0, 0.04) for e in ea])
        bf, _ = _ar(rnd, n, BF_MEAN, BF_B, BF_SD)
        sd_d = atm0 / math.sqrt(252.0)
        lead = leads.get(pair, 0.0)
        drift = 0.07 if pair == "USDTRY" else 0.0
        x, spot = s0, []
        for i in range(n):
            push = COMOVE * eps[i] + lead * sum(eps[i - k] for k in range(1, 6) if i - k >= 0)
            mult = max(0.3, 1.0 + bf_vol * (bf[i - 1] - BF_MEAN) / bf_sd_eq) if i >= 1 else 1.0
            x *= math.exp((drift + push + rnd.gauss(0, sd_d) * mult) / 100.0)
            spot.append(x)
        put("FX:" + pair, spot, label=pair, kind="fx", group=group, universe=pair == "NZDUSD")
        if pair == "USDTRY":
            for tenor, dd in (("1M", 30.4), ("3M", 91.25), ("6M", 182.5), ("1Y", 365.0)):
                put("FXP:USDTRY:" + tenor, [s * (0.30 + rnd.gauss(0, 0.005)) * dd / 365.0 * 1e4 for s in spot], label="USDTRY %s swap puanı" % tenor,
                    kind="pts", group="TRY")
        else:
            put("FXP:%s:3M" % pair, [POINTS.get(pair, 25.0) + rnd.gauss(0, 1.0) for _ in range(n)], label=pair + " 3M swap puanı", kind="pts", group="G10")
        for (kind, tenor), vals in ((("ATM", "1M"), a1), (("ATM", "3M"), a3), (("RR25", "1M"), rr1), (("RR25", "3M"), rr3), (("BF25", "3M"), bf)):
            put(qopt.key(pair, kind, tenor), vals, label=qopt.label(pair, kind, tenor), kind="vol", group=group)
    eurtry = [series["FX:USDTRY"][d] * series["FX:EURUSD"][d] for d in days]
    put("FX:EURTRY", eurtry, label="EURTRY", kind="fx", group="TRY")
    put("FXP:EURTRY:3M", [s * 0.28 * 91.25 / 365.0 * 1e4 for s in eurtry], label="EURTRY 3M swap puanı", kind="pts", group="TRY")
    return days, series, meta


def context(today: dt.date = TODAY, n: int = 500, seed: int = 11, leads: Optional[Dict[str, float]] = None, shock: Optional[Dict[str, float]] = None,
            bf_vol: float = 0.0, live: Optional[Dict[str, float]] = None, cfg: Optional[Dict[str, Any]] = None, series: Optional[Dict[str, Any]] = None,
            drop: Tuple[str, ...] = ()):
    """A context of the synthetic history (``series``: these closes instead - a test's own edit of them; ``drop``: keys
    the history does not keep at all)."""
    from tto import quant as qq
    days, built, meta = build(today, n, seed, leads, shock, bf_vol)
    conf = dict(qq.DEFAULTS, usdtry=42.0)
    conf.update(cfg or {})
    ser = series if series is not None else built
    return qf.Ctx(conf, today, {k: dict(v) for k, v in ser.items() if k not in drop}, {k: dict(v) for k, v in meta.items() if k not in drop},
                  live or {}), days


def seed(svc, n: int = 500, seed_: int = 11, leads: Optional[Dict[str, float]] = None, shock: Optional[Dict[str, float]] = None) -> List[str]:
    """Write the synthetic history into ``svc``'s store under the ids of the history's own definitions."""
    from tto.quant import Quant
    snap = svc.history.snapshot()
    days, series, _ = build(snap["today"], n, seed_, leads, shock)
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
