"""Synthetic market history for the quant tests: a TRY OIS curve built from three factors with a planted rich / cheap
tenor, an offshore curve cointegrated with it, a policy cycle in TLREF, FX spots with known drifts and vols, forward
points from known rate differentials, global drivers that move the TRY curve with known betas."""
from __future__ import annotations

import datetime as _dt
import math
import random
from typing import Dict, List, Tuple

#: the differential (%, annual) each currency's 3M forward is built with, and its 3M ATM vol (%)
CARRY = {"TRY": 31.0, "ZAR": 4.0, "MXN": 5.0, "BRL": 10.0, "INR": 2.0, "IDR": 2.5, "HUF": 2.0, "PLN": 1.0, "COP": 5.0}
VOL = {"TRY": 9.0, "ZAR": 15.0, "MXN": 13.0, "BRL": 16.0, "INR": 5.0, "IDR": 7.0, "HUF": 11.0, "PLN": 9.0, "COP": 12.0}
SPOT0 = {"TRY": 34.0, "ZAR": 18.0, "MXN": 18.5, "BRL": 5.4, "INR": 84.0, "IDR": 15800.0, "HUF": 360.0, "PLN": 3.9, "COP": 4100.0}
BETA_CDS = 0.5          # TRY curve level, bp per CDS bp
BETA_UST10 = 0.3        # TRY curve level, bp per UST 10Y bp
RESID_SD = 0.02         # the planted tenor's own noise (per cent a day): below the slope's, so PC2 stays the slope


def business_days(end: _dt.date, n: int) -> List[str]:
    """The ``n`` week days before ``end`` (oldest first)."""
    out = []
    d = end
    while len(out) < n:
        d -= _dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return list(reversed(out))


def build(today: _dt.date, ois_months: Dict[str, float], n: int = 520, seed: int = 11, planted: str = "OIS:2Y",
          shock: float = 3.0, basis_shock: float = 3.0) -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    """``{key: {day: value}}`` for the quant keys (OIS:<T>, OFF:<T>, TLREF, FX:…, FXV:…, FXR:…, FXP:…, UST:…, DXY, BRENT,
    CDS, USD:3M) over the ``n`` business days before ``today``.  The planted tenor's residual is mean-reverting (AR(1),
    b = 0.85) and its last close sits ``shock`` of its standard deviations away; so does the 3M offshore basis."""
    rnd = random.Random(seed)
    days = business_days(today, n)
    out: Dict[str, Dict[str, float]] = {}
    # ---- global drivers
    ust2, ust10, dxy, brent, cds, usd = 3.8, 4.3, 100.0, 70.0, 280.0, 4.0
    g: Dict[str, List[float]] = {"UST:2Y": [], "UST:10Y": [], "DXY": [], "BRENT": [], "CDS": [], "USD:3M": []}
    d_cds, d_u10 = [], []
    for _ in days:
        a, b = rnd.gauss(0, 4.0), rnd.gauss(0, 5.0)                     # bp
        ust2 += a / 100.0
        ust10 += b / 100.0
        dxy *= math.exp(rnd.gauss(0, 0.004))
        brent *= math.exp(rnd.gauss(0, 0.018))
        c = rnd.gauss(0, 6.0)
        cds += c
        usd += rnd.gauss(0, 0.01)
        d_cds.append(c)
        d_u10.append(b)
        for k, v in (("UST:2Y", ust2), ("UST:10Y", ust10), ("DXY", dxy), ("BRENT", brent), ("CDS", cds), ("USD:3M", usd)):
            g[k].append(v)
    for k, vals in g.items():
        out[k] = dict(zip(days, vals))
    # ---- TLREF: a cutting cycle, a hold, a hiking cycle, a hold
    tl = []
    level = 47.0
    for i, _ in enumerate(days):
        if i < 200 and i % 30 == 29:
            level -= 2.5
        if 330 <= i < 420 and i % 30 == 0:
            level += 2.0
        tl.append(level + rnd.gauss(0, 0.05))
    out["TLREF"] = dict(zip(days, tl))
    # ---- the OIS curve: level (a random walk the drivers move), slope and curvature (mean-reverting)
    tenors = sorted(ois_months.items(), key=lambda kv: kv[1])
    lm = [math.log(max(m, 0.25)) for _, m in tenors]
    mid = sum(lm) / len(lm)
    span = (max(lm) - min(lm)) or 1.0
    level_, slope, curv = 38.0, 0.0, 0.0
    resid_b, resid = 0.85, 0.0
    curve: Dict[str, List[float]] = {k: [] for k, _ in tenors}
    for i, _ in enumerate(days):
        level_ += (rnd.gauss(0, 6.0) + BETA_CDS * d_cds[i] + BETA_UST10 * d_u10[i]) / 100.0
        slope = 0.98 * slope + rnd.gauss(0, 0.06)
        curv = 0.95 * curv + rnd.gauss(0, 0.04)
        resid = resid_b * resid + rnd.gauss(0, RESID_SD)
        for (k, _m), x in zip(tenors, lm):
            sl = (x - mid) / span
            cu = sl * sl - 0.25
            v = level_ + slope * sl + curv * cu + rnd.gauss(0, 0.01)
            if k == planted:
                v += resid
            curve[k].append(v)
    if planted in curve and shock:
        sd = RESID_SD / math.sqrt(1 - resid_b ** 2)
        curve[planted][-1] += shock * sd - resid                       # the last close: far from the curve
    for k, vals in curve.items():
        out[k] = dict(zip(days, vals))
    # ---- offshore = OIS − 2 % + a basis that returns to its mean (cointegrated, β 1); the 3M basis ends far away
    basis = 0.0
    off3 = []
    for _ in days:
        basis = 0.8 * basis + rnd.gauss(0, 0.05)
        off3.append(basis)
    if basis_shock:
        off3[-1] = basis_shock * 0.05 / math.sqrt(1 - 0.64)
    for k, m in tenors:
        if m in (1, 3, 6, 12):
            name = "OFF:" + k.split(":", 1)[1]
            base = curve[k]
            out[name] = {d: base[i] - 2.0 + (off3[i] if m == 3 else rnd.gauss(0, 0.03)) for i, d in enumerate(days)}
    # ---- FX: spots, vols (implied above realized), risk reversals, forward points from the differentials
    for ccy in CARRY:
        pair = "USD" + ccy
        s = SPOT0[ccy]
        drift = (25.0 if ccy == "TRY" else 0.0) / 100.0 / 252.0
        sp, iv, rr, pts = [], [], [], []
        v_dev = 0.0
        for _ in days:
            s *= math.exp(drift + rnd.gauss(0, VOL[ccy] / 100.0 / math.sqrt(252.0)))
            v_dev = 0.9 * v_dev + rnd.gauss(0, 0.4)
            sp.append(s)
            iv.append(VOL[ccy] + 2.0 + v_dev)
            rr.append(1.0 + 0.3 * v_dev)
            f = s * (1.0 + (CARRY[ccy] + rnd.gauss(0, 0.2)) / 100.0 * 91.25 / 365.0)
            pts.append((f - s) * 1e4)
        out["FX:" + pair] = dict(zip(days, sp))
        out["FXV:" + pair] = dict(zip(days, iv))
        out["FXR:" + pair] = dict(zip(days, rr))
        out["FXP:%s:3M" % pair] = dict(zip(days, pts))
        if ccy == "TRY":
            for tenor, dd in (("1M", 30.4), ("6M", 182.5), ("1Y", 365.0)):
                out["FXP:USDTRY:" + tenor] = {d: v * 31.0 / 100.0 * dd / 365.0 * 1e4 for d, v in zip(days, sp)}
    eu = []
    eurusd = 1.15
    for _ in days:
        eurusd *= math.exp(rnd.gauss(0, 0.005))
        eu.append(eurusd)
    out["FX:EURUSD"] = dict(zip(days, eu))
    out["FXV:EURUSD"] = {d: 7.0 + rnd.gauss(0, 0.3) for d in days}
    out["FXR:EURUSD"] = {d: 0.2 + rnd.gauss(0, 0.1) for d in days}
    out["FX:EURTRY"] = {d: eu[i] * out["FX:USDTRY"][d] for i, d in enumerate(days)}
    out["FXP:EURTRY:3M"] = {d: out["FX:EURTRY"][d] * 0.29 * 91.25 / 365.0 * 1e4 for d in days}
    return days, out


def seed(svc, n: int = 520, seed_: int = 11, **kw) -> Tuple[List[str], Dict[str, Dict[str, float]]]:
    """Write the synthetic history into ``svc``'s store under the series ids of the history's own definitions."""
    from tto.quant import Quant
    snap = svc.history.snapshot()
    defs = {}
    months = {}
    for d in snap["defs"]:
        k = Quant._key_of(d)
        if k and k not in defs:
            defs[k] = d
            if k.startswith("OIS:") and d.months and d.months >= 1:
                months[k] = d.months
    days, data = build(snap["today"], months, n, seed_, **kw)
    for k, points in data.items():
        d = defs.get(k)
        if d is None:
            continue
        for sid in d.ids():
            svc.store.hist_delete(sid)
        svc.store.hist_upsert(d.id, sorted(points.items()))
    svc.history.rev += 1
    return days, data
