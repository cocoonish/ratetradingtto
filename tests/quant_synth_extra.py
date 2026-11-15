"""Synthetic history for the curve fair-value and options families (``tto/quantcurve.py``, ``tto/quantopt.py``): bond
yields priced every day off a known, moving Nelson-Siegel-Svensson curve (one bond with a planted mean-reverting
mispricing that ends far from the curve), and FX vol quotes - ATM term structure, risk reversals, butterflies - that
move around known levels (one quote ending far from its mean)."""
from __future__ import annotations

import datetime as _dt
import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

from tto import quantcurve as qc
from tto import quantopt as qo

TAU = (0.9, 4.5)
#: the curve's β on the first day (decimal) and how far each walks a day
BETA0 = (0.30, 0.06, -0.05, 0.03)
BETA_SD = (0.0012, 0.0010, 0.0010, 0.0008)
MISPRICE_SD = 0.0006          # the planted bond's own mispricing: AR(1), b 0.85 (yield, decimal)
#: bonds of the synthetic list: (isin, years to maturity from the last day, coupon % - 0 a bill); coupon bonds from a
#: quarter of a year on, as on the DİBS RV list (the bills are measured against the coupon bonds' curve, not fitted)
BONDS = (("TRB000001T11", 0.35, 0.0), ("TRB000002T11", 0.8, 0.0), ("TRT000013T11", 0.28, 25.0), ("TRT000014T11", 0.6, 34.5),
         ("TRT000003T11", 1.2, 37.8), ("TRT000004T11", 1.7, 20.2),
         ("TRT000005T11", 2.3, 31.1), ("TRT000006T11", 2.9, 36.8), ("TRT000007T11", 3.6, 26.2), ("TRT000008T11", 4.4, 17.3),
         ("TRT000009T11", 5.3, 32.0), ("TRT000010T11", 6.6, 12.6), ("TRT000011T11", 8.1, 27.5), ("TRT000012T11", 9.6, 30.0))
PLANTED = "TRT000007T11"


def business_days(end: _dt.date, n: int) -> List[str]:
    out = []
    d = end
    while len(out) < n:
        d -= _dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return list(reversed(out))


def curves(days: Sequence[str], seed: int = 21, beta0: Sequence[float] = BETA0) -> Dict[str, qc.Nss]:
    """Each day's true curve: the β walk around ``beta0`` (mean-reverting, so the levels stay sensible), the τ fixed."""
    rnd = random.Random(seed)
    beta = list(beta0)
    out = {}
    for d in days:
        beta = [b0 + 0.97 * (b - b0) + rnd.gauss(0, sd) for b, b0, sd in zip(beta, beta0, BETA_SD)]
        out[d] = qc.Nss(beta, *TAU)
    return out


def bond_list(today: _dt.date, bonds: Sequence[Tuple[str, float, float]] = BONDS) -> List[qc.Bond]:
    return [qc.Bond(isin, isin, "bill" if cpn == 0 else "fixed", today + _dt.timedelta(days=int(years * 365)), cpn, 2)
            for isin, years, cpn in bonds]


def bond_yields(today: _dt.date, n: int = 520, seed: int = 21, planted: Optional[str] = PLANTED, shock: float = 3.0,
                bonds: Optional[List[qc.Bond]] = None, conv: str = "simple", noise: float = 0.0003,
                beta0: Sequence[float] = BETA0) -> Tuple[List[str], Dict[str, Dict[str, float]], Dict[str, qc.Nss]]:
    """``(days, {isin: {day: yield %}}, {day: curve})``: every bond priced off the day's curve (value date the next
    week day), its yield in ``conv``, a bond's own noise of ``noise`` (3 bp a day); the planted bond's mispricing AR(1)
    and its last close ``shock`` of its standard deviations cheap."""
    days = business_days(today, n)
    true = curves(days, seed, beta0)
    rnd = random.Random(seed + 1)
    bonds = bonds if bonds is not None else bond_list(today)
    out: Dict[str, Dict[str, float]] = {b.isin: {} for b in bonds}
    mis = 0.0
    sd_eq = MISPRICE_SD / math.sqrt(1 - 0.85 ** 2)
    for i, d in enumerate(days):
        day = _dt.date.fromisoformat(d)
        value = qc.next_weekday(day)
        mis = 0.85 * mis + rnd.gauss(0, MISPRICE_SD)
        if i == len(days) - 1 and planted:
            mis = shock * sd_eq
        for b in bonds:
            if (b.maturity - value).days < qc.MIN_DAYS:
                continue
            flows, _ = b.flows(value)
            p = sum(cf * true[d].df((x - value).days / 365.0) for x, cf in flows)
            y = b.yield_of(p, value, conv, 0.3)
            if y is None:
                continue
            y += rnd.gauss(0, noise) + (mis if b.isin == planted else 0.0)
            out[b.isin][d] = y * 100.0
    return days, out, true


#: the quotes' levels (vol points) around which they move, per pair
LEVELS = {"USDTRY": {"ATM": {"1W": 9.0, "1M": 10.0, "3M": 12.0, "6M": 13.5, "1Y": 15.0}, "RR25": {"1M": 5.5, "3M": 7.0},
                     "BF25": {"1M": 1.2, "3M": 1.6}, "RR10": {"1M": 11.0, "3M": 14.0}, "BF10": {"1M": 4.0, "3M": 5.5}},
          "EURUSD": {"ATM": {"1W": 6.5, "1M": 7.0, "3M": 7.3, "6M": 7.6, "1Y": 7.9}, "RR25": {"1M": 0.4, "3M": 0.5},
                     "BF25": {"1M": 0.18, "3M": 0.22}, "RR10": {"1M": 0.8, "3M": 1.0}, "BF10": {"1M": 0.6, "3M": 0.75}}}


def option_quotes(today: _dt.date, n: int = 520, seed: int = 31, planted: Optional[Tuple[str, str, str]] = ("USDTRY", "RR25", "1M"),
                  shock: float = 3.0) -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    """``(days, {key: {day: vol points}})`` for every quote of ``quantopt.SURFACE`` of both pairs (the keys the module
    reads, the package's own FXV / FXR included): ATM vols and the 25-delta quotes each an AR(1) around its level
    (b 0.9), the 10-delta quotes their 25-delta ones scaled as the levels are plus a little noise (a smile keeps its
    shape); the planted one's last close ``shock`` of its standard deviations up."""
    days = business_days(today, n)
    rnd = random.Random(seed)
    out: Dict[str, Dict[str, float]] = {}
    wing = {"RR10": "RR25", "BF10": "BF25"}
    for pair in qo.PAIRS:
        common = 0.0
        devs = {}
        series = {qo.key(pair, k, t): {} for k, t in qo.SURFACE}
        for i, d in enumerate(days):
            common = 0.9 * common + rnd.gauss(0, 0.25)
            now = {}
            for kind, tenor in sorted(qo.SURFACE, key=lambda q: q[0] in wing):
                k = qo.key(pair, kind, tenor)
                lvl = LEVELS[pair][kind][tenor]
                sd = 0.06 * lvl
                if kind in wing:
                    inner = wing[kind]
                    v = now[(inner, tenor)] * lvl / LEVELS[pair][inner][tenor] * (1.0 + rnd.gauss(0, 0.01))
                else:
                    devs[k] = 0.9 * devs.get(k, 0.0) + rnd.gauss(0, sd)
                    v = lvl + devs[k] + (common * lvl / 10.0 if kind == "ATM" else 0.0)
                if planted and (pair, kind, tenor) == planted and i == len(days) - 1:
                    v = lvl + shock * sd / math.sqrt(1 - 0.81)
                now[(kind, tenor)] = v
                series[k][d] = v
        out.update(series)
    return days, out


def forward_points(spot: Dict[str, float], diff: float, tenors: Sequence[str] = ("1M", "3M")) -> Dict[str, Dict[str, float]]:
    """``{"FXP:<pair>:<tenor>": {day: points}}`` of a pair whose forward is the spot × (1 + ``diff`` (% a year) × days / 365)
    - in pips (FWD_SCALE 4), as Bloomberg quotes them.  ``spot``: the pair's closes; the pair from the caller's key."""
    out = {}
    for tenor in tenors:
        days = {"1M": 30.4167, "3M": 91.25}[tenor]
        out[tenor] = {d: s * diff / 100.0 * days / 365.0 * 1e4 for d, s in spot.items()}
    return out
