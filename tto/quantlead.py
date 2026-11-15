"""Lead-lag: who moves first - the offshore curve or onshore OIS, the USDTRY swap points or OIS, VİOP or OIS, USDTRY /
EURTRY or the OIS front end, the 1Y or the 2Y / 5Y.  On the quant package's worker (``tto.quant`` calls :func:`run` on
a full fit and :func:`refresh` on the minute's live refresh; the page "Öncü-Takipçi" reads :func:`view`).

**Daily.**  The daily changes of each candidate pair (rates in bp, FX in % log, swap points as they are) on the days
both closed: the cross-correlation of x_t with y_t+k for k = −5 … +5 (k > 0: x leads), and a Granger test each way -
the follower on its own lags with and without the other's, OLS, the F-test of the other's lags, the lag order by AIC
on one sample.  Who leads is read from the asymmetry of the cross-correlations: at each lag l, x leading, r(+l),
against y leading, r(−l) - two series that only share a component (with noise of their own on top, around a spread
that mean-reverts, or a common component that is itself autocorrelated) have r(+l) ≈ r(−l), and each one's lags then
"help" the other in a Granger test without anyone leading; a lead makes one side stronger.  z = (r(+l) − r(−l)) ÷
√(2 ÷ n) at the lag with the largest |z|, past the 5 % level over the lags looked at (Bonferroni: 2,58 for five);
the leader the side with the larger |r|, the lag ℓ that lag; and the leader's Granger test must say so too (p < 5 %).
β is the follower's total response within ℓ days to a leader's move, Σ b_0 … b_ℓ of the distributed lag (fitted as
one coefficient, so its standard error is the regression's own), with its R².  Stability: the asymmetry at lag ℓ in
the last 60 / 120 / 250 days - the same sign and |z| ≥ 2 in each window there is data for.

**Signal** (family "Öncü-takipçi").  When the leader moved - its move over the last ℓ + 1 days at least k σ (k a desk
setting) - and the follower has not caught up: the expected catch-up is β × the leader's move − the follower's own
move over the same days; its σ comes from β's standard error and the follower's own noise over the window, z = the
catch-up ÷ σ.  Entry is the follower's level now, the target that level plus the catch-up, the stop one σ the other way
(the follower's units); carry is not counted.  The same rule run over the history (every day the leader moved that
much, in-sample β) says how often the follower then moved the expected way and how much of it came - beside each pair.

**Intraday, later.**  The analysis takes any aligned series, so it runs on bars at minute lags as it does on days.
With a bar source at run time (minute bars of the live feed: :func:`bar_source`, feature-detected on the service as a
callable ``(key, minutes) -> (times, values)``), the same table is made for 1- and 5-minute bars; without one the page
says "gün içi barlar yok".
"""
from __future__ import annotations

import copy
import math
import statistics
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf
from . import quantmath as qm

# ---------------------------------------------------------------------------------------------- settings
#: the desk's settings of this module (quant.py adds them to its own: "Masa ayarları", for everyone)
DEFAULTS: Dict[str, Any] = {"lead_k": 2.0, "lead_lag": 5}
LIMITS: Dict[str, Tuple[float, float, type]] = {"lead_k": (0.5, 10.0, float), "lead_lag": (1, 10, int)}
LABELS = {"lead_k": "Öncü hareket eşiği (σ)", "lead_lag": "Öncü-takipçi en çok gecikme (gün)"}

FAMILY = "leadlag"
VIEWS = {"lead": "quant-lead"}
ALPHA = 0.05                                    # the Granger test's level
WINDOWS = (60, 120, 250)                        # the stability windows (observations)
STABLE_T = 2.0
MIN_OBS = 60                                    # changes a pair needs (the desk's "en az gözlem" when that is less)
BAR_MINUTES = (1, 5)
BAR_LAGS = 10                                   # bars: the most lags looked at intraday
REFRESH_BARS = 300.0                            # seconds between two intraday passes
BarSource = Callable[[str, int], Optional[Tuple[Sequence[Any], Sequence[float]]]]


# ---------------------------------------------------------------------------------------------- the F distribution
def _betacf(a: float, b: float, x: float) -> float:
    """The continued fraction of the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def f_sf(f: Optional[float], d1: float, d2: float) -> Optional[float]:
    """P(F > f) for an F(d1, d2) variable."""
    if f is None or d1 <= 0 or d2 <= 0:
        return None
    if f <= 0:
        return 1.0
    return betainc(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


# ---------------------------------------------------------------------------------------------- generic series
def _finite(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def align(tx: Sequence[Any], vx: Sequence[float], ty: Sequence[Any], vy: Sequence[float]) -> Tuple[List[Any], List[float], List[float]]:
    """Two series on the times both have (days, or bar times), in order."""
    bx = {t: float(v) for t, v in zip(tx, vx) if _finite(v)}
    by = {t: float(v) for t, v in zip(ty, vy) if _finite(v)}
    times = sorted(set(bx) & set(by))
    return times, [bx[t] for t in times], [by[t] for t in times]


def changes(kind: str, values: Sequence[float]) -> List[float]:
    """Changes of a level series in its kind's units (rates bp, FX and indices % log, the rest as they are)."""
    return qf.diffs(kind, values)


def xcorr(dx: Sequence[float], dy: Sequence[float], max_lag: int) -> Dict[int, Optional[float]]:
    """corr(x_t, y_t+k) for k = −max_lag … max_lag: k > 0 is x leading y by k, k < 0 y leading x."""
    n = min(len(dx), len(dy))
    out: Dict[int, Optional[float]] = {}
    for k in range(-max_lag, max_lag + 1):
        if k >= 0:
            a, b = dx[:n - k], dy[k:n]
        else:
            a, b = dx[-k:n], dy[:n + k]
        out[k] = qm.corr(list(a), list(b)) if len(a) >= 10 else None
    return out


def granger(dy: Sequence[float], dx: Sequence[float], p: int, start: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Does x's past help predict y?  y_t on its own p lags with and without x's p lags (OLS on the rows from
    ``start`` - the same sample for every order), the F-test of x's lags and the unrestricted model's AIC."""
    n = min(len(dx), len(dy))
    s = p if start is None else start
    rows = range(s, n)
    if len(rows) < 2 * p + 10:
        return None
    y = [dy[t] for t in rows]
    own = [[dy[t - i] for t in rows] for i in range(1, p + 1)]
    other = [[dx[t - i] for t in rows] for i in range(1, p + 1)]
    u = qm.ols(y, own + other)
    r = qm.ols(y, own)
    if u is None or r is None:
        return None
    rss_u = u["sigma2"] * (u["n"] - u["k"])
    rss_r = r["sigma2"] * (r["n"] - r["k"])
    df2 = u["n"] - u["k"]
    if rss_u <= 0 or df2 <= 0:
        return None
    f = max(0.0, (rss_r - rss_u) / p) / (rss_u / df2)
    return {"F": f, "p": f_sf(f, p, df2), "df1": p, "df2": df2, "order": p,
            "aic": u["n"] * math.log(rss_u / u["n"]) + 2.0 * u["k"]}


def best_granger(dy: Sequence[float], dx: Sequence[float], max_lag: int) -> Optional[Dict[str, Any]]:
    """The Granger test at the lag order the unrestricted model's AIC prefers (1 … max_lag, one sample)."""
    fits = [g for g in (granger(dy, dx, p, start=max_lag) for p in range(1, max_lag + 1)) if g is not None]
    return min(fits, key=lambda g: g["aic"]) if fits else None


def z_lead(max_lag: int) -> float:
    """The asymmetry's critical |z|: 5 % two-sided over ``max_lag`` lags looked at (Bonferroni)."""
    return statistics.NormalDist().inv_cdf(1.0 - ALPHA / (2.0 * max(1, max_lag)))


def asymmetry(xc: Dict[int, Optional[float]], n: int, max_lag: int) -> Optional[Dict[str, Any]]:
    """Who moves first, by the cross-correlations themselves: at each lag l the one of x leading, r(+l), against the
    one of y leading, r(−l).  Two series that only share a component - noise of their own on top, a spread that
    mean-reverts, a common component that is itself autocorrelated - have r(+l) ≈ r(−l); a lead makes one side
    stronger.  z = (r(+l) − r(−l)) ÷ √(2 ÷ (n − l)); the lag with the largest |z|, the side with the larger |r|."""
    best = None
    for lag in range(1, max_lag + 1):
        a, b = xc.get(lag), xc.get(-lag)
        if a is None or b is None or n - lag < 10:
            continue
        z = (a - b) / math.sqrt(2.0 / (n - lag))
        if best is None or abs(z) > abs(best["z"]):
            best = {"lag": lag, "z": z, "side": "x" if abs(a) >= abs(b) else "y", "r": a if abs(a) >= abs(b) else b}
    return best


def distributed_lag(follow: Sequence[float], lead: Sequence[float], lag: int) -> Optional[Dict[str, Any]]:
    """The follower's change on the leader's changes at lags 0 … lag; the sum of the coefficients is fitted as one
    (the regressors x_t and x_t−i − x_t), so β = Σ b_i comes with its own standard error."""
    n = min(len(follow), len(lead))
    rows = range(lag, n)
    if len(rows) < lag + 12:
        return None
    y = [follow[t] for t in rows]
    cols = [[lead[t] for t in rows]] + [[lead[t - i] - lead[t] for t in rows] for i in range(1, lag + 1)]
    fit = qm.ols(y, cols)
    if fit is None:
        return None
    later = fit["coef"][2:]
    return {"beta": fit["coef"][1], "se": fit["se"][1], "t": fit["t"][1], "r2": fit["r2"], "sigma": math.sqrt(fit["sigma2"]),
            "b": [fit["coef"][1] - sum(later)] + list(later), "n": fit["n"]}


def _t_of(r: Optional[float], n: int) -> Optional[float]:
    if r is None or n < 3 or abs(r) >= 1.0:
        return None
    return r * math.sqrt(n - 2) / math.sqrt(1.0 - r * r)


def stability(dx: Sequence[float], dy: Sequence[float], lag: int, sign: int, windows: Sequence[int] = WINDOWS) -> List[Dict[str, Any]]:
    """Does the lead hold in the last ``w`` observations - the asymmetry at ``lag`` (x's side minus y's) there with
    the same sign and |z| ≥ 2?"""
    out = []
    n = min(len(dx), len(dy))
    for w in windows:
        if n < w:
            out.append({"window": w, "z": None, "ok": None})
            continue
        xs, ys = list(dx[n - w:n]), list(dy[n - w:n])
        a, b = qm.corr(xs[:w - lag], ys[lag:]), qm.corr(ys[:w - lag], xs[lag:])
        z = (a - b) / math.sqrt(2.0 / (w - lag)) if a is not None and b is not None else None
        out.append({"window": w, "z": z, "ok": bool(z is not None and qf.sign(z) == sign and abs(z) >= STABLE_T)})
    return out


def events(lead: Sequence[float], follow: Sequence[float], lag: int, beta: float, k: float) -> Dict[str, Any]:
    """The rule over the history (in-sample β): every step the leader's move over the last lag + 1 steps was at least
    k σ, the expected catch-up β × that move − the follower's own move, against the follower's move over the next
    ``lag`` steps: how often it went the expected way, and how much of the catch-up came (Σ realized ÷ Σ expected)."""
    n = min(len(lead), len(follow))
    sd = qm.stdev(list(lead))
    out = {"n": 0, "hits": 0, "hit_rate": None, "ratio": None}
    if not sd or lag < 1:
        return out
    w = lag + 1
    thr = k * sd * math.sqrt(w)
    exp_sum = got_sum = 0.0
    t = w - 1
    while t < n - lag:
        m_l = sum(lead[t - j] for j in range(w))
        if abs(m_l) >= thr:
            c = beta * m_l - sum(follow[t - j] for j in range(w))
            real = sum(follow[t + j] for j in range(1, lag + 1))
            if abs(c) > 1e-12:
                out["n"] += 1
                out["hits"] += 1 if real * c > 0 else 0
                exp_sum += abs(c)
                got_sum += real * qf.sign(c)
            t += w                                                         # the next event after this one's window
            continue
        t += 1
    if out["n"]:
        out["hit_rate"] = out["hits"] / out["n"]
        out["ratio"] = got_sum / exp_sum if exp_sum > 0 else None
    return out


def lead_lag(dx: Sequence[float], dy: Sequence[float], max_lag: int = 5, k: float = 2.0,
             windows: Sequence[int] = WINDOWS) -> Dict[str, Any]:
    """The lead-lag of two aligned change series: cross-correlations, Granger both ways, the leader ("x" / "y" / None),
    the lag, β with its standard error, R², stability, the rule's history."""
    n = min(len(dx), len(dy))
    xc = xcorr(dx, dy, max_lag)
    gxy, gyx = best_granger(dy, dx, max_lag), best_granger(dx, dy, max_lag)
    out: Dict[str, Any] = {"n": n, "xcorr": xc, "granger_xy": gxy, "granger_yx": gyx, "leader": None, "lag": None}
    asym = asymmetry(xc, n, max_lag)
    out["asym"] = asym
    if asym is None or abs(asym["z"]) < z_lead(max_lag):
        out["why"] = "öncü yok: gecikmeli ilişki iki yönde aynı"
        return out
    leader, lag = asym["side"], asym["lag"]
    g = gxy if leader == "x" else gyx
    if g is None or g["p"] is None or g["p"] >= ALPHA:
        out["why"] = "öncü yok: Granger p ≥ %%%d" % round(ALPHA * 100)
        return out
    lead, follow = (dx, dy) if leader == "x" else (dy, dx)
    r_lag = asym["r"]
    dl = distributed_lag(follow, lead, lag)
    if dl is None:
        return out
    out.update({"leader": leader, "lag": lag, "F": g["F"], "p": g["p"], "order": g["order"], "beta": dl["beta"], "se": dl["se"],
                "t": dl["t"], "r2": dl["r2"], "sigma": dl["sigma"], "b": dl["b"], "r_lag": r_lag,
                "asym_z": asym["z"], "stability": stability(dx, dy, lag, qf.sign(asym["z"]), windows),
                "events": events(lead, follow, lag, dl["beta"], k)})
    st = [s["ok"] for s in out["stability"] if s["ok"] is not None]
    out["stable"] = "%d/%d" % (sum(1 for s in st if s), len(st)) if st else "—"
    return out


def catch_up(kind_l: str, kind_f: str, lead_levels: Sequence[float], follow_levels: Sequence[float], lead_now: float, follow_now: float,
             res: Dict[str, Any], k: float, sd_lead: float) -> Optional[Dict[str, Any]]:
    """Now: the leader's and the follower's moves over the last lag + 1 steps (to the values now), the expected
    catch-up β × the leader's move − the follower's, its σ and z; ``event`` is whether the leader moved k σ."""
    lag = res.get("lag")
    if not lag or len(lead_levels) < lag + 1 or len(follow_levels) < lag + 1:
        return None
    w = lag + 1
    m_l = qf.change(kind_l, lead_levels[-w], lead_now)
    m_f = qf.change(kind_f, follow_levels[-w], follow_now)
    if m_l is None or m_f is None:
        return None
    c = res["beta"] * m_l - m_f
    sigma = math.sqrt((res["se"] * m_l) ** 2 + res["sigma"] ** 2 * w)
    thr = k * sd_lead * math.sqrt(w)
    return {"lead_move": m_l, "follow_move": m_f, "catch_up": c, "sigma": sigma, "z": c / sigma if sigma > 0 else None,
            "event": abs(m_l) >= thr, "threshold": thr, "k_moved": m_l / (sd_lead * math.sqrt(w)) if sd_lead else None}


# ---------------------------------------------------------------------------------------------- the pairs
def candidate_pairs(ctx: qf.Ctx) -> List[Tuple[str, str, str]]:
    """(x, y, group) for the series the context has: offshore (ICAP's page, not the cross-currency swaps) ↔ OIS by
    tenor, USDTRY swap points ↔ OIS, VİOP's front implied rate ↔ OIS 1M / 3M, USDTRY / EURTRY ↔ OIS 1M / 3M, OIS 1Y ↔
    2Y / 5Y."""
    ois = {}
    for key, m in ctx.meta.items():
        if key.startswith("OIS:") and m.get("months"):
            ois.setdefault(m["months"], key)
    out: List[Tuple[str, str, str]] = []
    for key, m in sorted(ctx.meta.items(), key=lambda kv: kv[1].get("months") or 0):
        if key.startswith("OFF:") and m.get("group") == "off" and (m.get("months") or 0) >= 1 and m["months"] in ois:
            out.append((key, ois[m["months"]], "Offshore ↔ OIS"))
    for tenor, months in (("1M", 1), ("3M", 3), ("6M", 6), ("1Y", 12)):
        if "FXP:USDTRY:" + tenor in ctx.meta and months in ois:
            out.append(("FXP:USDTRY:" + tenor, ois[months], "Swap puanı ↔ OIS"))
    for months in (1, 3):
        if "VIOPI:FRONT" in ctx.meta and months in ois:
            out.append(("VIOPI:FRONT", ois[months], "VİOP ↔ OIS"))
    for spot in ("FX:USDTRY", "FX:EURTRY"):
        for months in (1, 3):
            if spot in ctx.meta and months in ois:
                out.append((spot, ois[months], "Kur ↔ OIS ön uç"))
    for months in (24, 60):
        if 12 in ois and months in ois:
            out.append((ois[12], ois[months], "Eğri içi"))
    return out


def _label(ctx: qf.Ctx, key: str) -> str:
    return ctx.label(key)


def _asset(key: str) -> str:
    if key.startswith("OFF:"):
        return "Offshore"
    if key.startswith("VIOP"):
        return "VİOP"
    if key.startswith(("FX:", "FXP:", "FWD:")):
        return "FX"
    return "TRY OIS"


def _unit_digits(kind: str) -> Tuple[str, int]:
    return qf.level_unit(kind), {"rate": 3, "fx": 4, "index": 2}.get(kind, 1)


def _verbs_pkg(key: str, kind: str) -> str:
    return "fx" if kind in ("fx", "index") and not key.startswith("FXP:") else "rate"


def analyse(ctx: qf.Ctx, x: str, y: str, group: str) -> Dict[str, Any]:
    """One pair on the daily closes (the last ``lookback`` changes)."""
    cfg = ctx.cfg
    max_lag = int(cfg.get("lead_lag") or DEFAULTS["lead_lag"])
    k = float(cfg.get("lead_k") or DEFAULTS["lead_k"])
    days, (vx, vy) = qf.aligned(ctx, [x, y])
    kx, ky = ctx.kind(x), ctx.kind(y)
    row: Dict[str, Any] = {"x": x, "y": y, "group": group, "x_label": _label(ctx, x), "y_label": _label(ctx, y), "n": max(0, len(days) - 1)}
    if len(days) - 1 < max(MIN_OBS, ctx.min_obs()):
        row["why"] = "geçmiş kısa (%d gün)" % max(0, len(days) - 1)
        return row
    win = ctx.window() + 1
    days, vx, vy = days[-win:], vx[-win:], vy[-win:]
    dx, dy = changes(kx, vx), changes(ky, vy)
    res = lead_lag(dx, dy, max_lag, k)
    row.update({"n": len(dx), "xcorr": res["xcorr"], "granger_xy": res["granger_xy"], "granger_yx": res["granger_yx"],
                "asym_z": (res.get("asym") or {}).get("z")})
    if res["leader"] is None:
        row["why"] = res.get("why") or "öncü yok"
        return row
    lead_key, follow_key = (x, y) if res["leader"] == "x" else (y, x)
    lead_v, follow_v = (vx, vy) if res["leader"] == "x" else (vy, vx)
    row.update({k2: res[k2] for k2 in ("lag", "F", "p", "order", "beta", "se", "t", "r2", "sigma", "b", "r_lag", "asym_z", "stability",
                                       "stable", "events")})
    row.update({"leader": lead_key, "follower": follow_key, "leader_label": _label(ctx, lead_key), "follower_label": _label(ctx, follow_key),
                "days": days, "lead_levels": lead_v, "follow_levels": follow_v, "sd_lead": qm.stdev(changes(ctx.kind(lead_key), lead_v)),
                "kind_l": ctx.kind(lead_key), "kind_f": ctx.kind(follow_key)})
    return row


# ---------------------------------------------------------------------------------------------- the monitor
def _stable_gate(row: Dict[str, Any]) -> Callable[[int], Tuple[float, str]]:
    """A lead the signal trades must hold in every window there is data for (60 / 120 / 250 days)."""
    marks = [s["ok"] for s in row.get("stability") or () if s["ok"] is not None]
    held = bool(marks) and all(marks)
    why = "öncülük her pencerede tutmuyor (60 / 120 / 250 gün: %s)" % row.get("stable", "—")
    return lambda side: (1.0, "") if held else (0.0, why)


class LeadMonitor(qf.Monitor):
    """A follower that has not caught up with its leader: the level is the follower's now, the score the catch-up's
    z when the leader moved k σ (no score otherwise), the target the catch-up, the stop its σ; a lead that does not
    hold in every stability window is shown but gated."""

    def __init__(self, ctx: qf.Ctx, row: Dict[str, Any], k: float):
        unit, digits = _unit_digits(row["kind_f"])
        lag = row["lag"]
        name = "%s (%s öncülüğünde)" % (row["follower_label"], row["leader_label"])
        legs = [{"key": row["follower"], "name": row["follower_label"], "weight": 1.0}]
        history = self._history(row, k)
        qf.Monitor.__init__(self, "%s:%s|%s" % (FAMILY, row["leader"], row["follower"]), FAMILY, _asset(row["follower"]), name, unit,
                            digits, row["days"][-ctx.window():], list(row["follow_levels"][-ctx.window():]), legs, lambda live: None,
                            follows=True, mode="drift", hold=float(lag), regime={"tag": None}, pkg=_verbs_pkg(row["follower"], row["kind_f"]),
                            score_name="z", gate=_stable_gate(row),
                            info={"inputs": [row["leader"]], "leader": row["leader"], "lag": lag, "beta": row["beta"],
                                  "events": row["events"], "stable": row["stable"]})
        self.zvalues = history[-len(self.values):]
        self.ctx, self.row, self.k = ctx, row, k
        self.now: Optional[Dict[str, Any]] = None

    @staticmethod
    def _history(row: Dict[str, Any], k: float) -> List[Optional[float]]:
        """The score day by day (in-sample β): the catch-up's z on the days the leader had moved k σ."""
        out: List[Optional[float]] = []
        lv, fv = row["lead_levels"], row["follow_levels"]
        for i in range(len(fv)):
            if i < row["lag"] + 1:
                out.append(None)
                continue
            c = catch_up(row["kind_l"], row["kind_f"], lv[:i], fv[:i], lv[i], fv[i], row, k, row["sd_lead"] or 0.0)
            out.append(c["z"] if c and c["event"] else None)
        return out

    def score(self, live: Dict[str, float], raw_live: Dict[str, float]) -> None:
        row, ctx = self.row, self.ctx
        lead_now, follow_now = ctx.cur(row["leader"], live), ctx.cur(row["follower"], live)
        self.level, self.z, self.now = follow_now, None, None
        self.live = row["follower"] in raw_live or row["leader"] in raw_live
        if lead_now is None or follow_now is None:
            return
        c = catch_up(row["kind_l"], row["kind_f"], row["lead_levels"], row["follow_levels"], lead_now, follow_now, row, self.k, row["sd_lead"] or 0.0)
        self.now = c
        if c is None:
            return
        self.reward = abs(qf.to_level(row["kind_f"], c["catch_up"], follow_now))
        self.risk = abs(qf.to_level(row["kind_f"], c["sigma"], follow_now))
        self.note = thesis(row, c)
        self.info["now"] = {kk: c[kk] for kk in ("lead_move", "follow_move", "catch_up", "sigma", "k_moved")}
        if c["event"]:
            self.z = c["z"]


def _f(v: Optional[float], d: int = 1) -> str:
    return "—" if v is None else ("%+.*f" % (d, v)).replace(".", ",").replace("-", "−")


def thesis(row: Dict[str, Any], c: Dict[str, Any]) -> str:
    """One Turkish sentence: who moved, how much the follower should still move, how sure, how it went before."""
    ev = row.get("events") or {}
    unit_l, unit_f = qf.change_unit(row["kind_l"]), qf.change_unit(row["kind_f"])
    hist = (" Geçmişte %d olayda %%%d isabet, beklenenin %%%d'i geldi (örneklem içi)." % (ev["n"], round(100 * ev["hit_rate"]),
            round(100 * (ev["ratio"] or 0.0))) if ev.get("n") else " Geçmişte benzer olay yok.")
    return ("%s son %d günde %s %s oynadı (%s σ); %s onu %d gün gecikmeyle β %s ile izler ve şimdiye kadar %s %s gitti: %s %s daha "
            "bekleniyor (z %s)." % (row["leader_label"], row["lag"] + 1, _f(c["lead_move"]), unit_l, _f(c["k_moved"]), row["follower_label"],
                                    row["lag"], _f(row["beta"], 2), _f(c["follow_move"]), unit_f, _f(c["catch_up"]), unit_f, _f(c["z"], 2))) + hist


# ---------------------------------------------------------------------------------------------- intraday bars (adapter)
def bar_source(svc: Any) -> Optional[BarSource]:
    """The live feed's minute bars, if this dashboard has them: a callable ``(key, minutes) -> (times, values)`` - the
    service's ``bars.series`` or ``bars`` itself (feature-detected; wired at the merge)."""
    for name in ("bars", "intraday_bars", "minute_bars"):
        src = getattr(svc, name, None)
        if src is None:
            continue
        fn = getattr(src, "series", None)
        if callable(fn):
            return fn
        if callable(src):
            return src
    return None


def bars_of(quant: Any) -> Optional[BarSource]:
    """The bars the lead-lag analysis reads: the quant worker's own (``quantintraday.Intraday.series``: the minute
    closes it keeps of the live feed), else whatever the service offers (``bar_source``)."""
    intra = getattr(quant, "intraday", None)
    fn = getattr(intra, "series", None)
    if callable(fn):
        live = getattr(intra, "live", None)
        return fn if not callable(live) or live() else None              # (replay keeps no bars: none at all)
    return bar_source(getattr(quant, "svc", None))


def intraday(source: Optional[BarSource], pairs: Sequence[Tuple[str, str, str]], kinds: Dict[str, str], k: float,
             minutes: Sequence[int] = BAR_MINUTES, max_lag: int = BAR_LAGS) -> Dict[str, Any]:
    """The same analysis on minute bars (lags in bars), or why there is none."""
    if source is None:
        return {"ok": False, "why": "gün içi barlar yok", "rows": []}
    rows = []
    for m in minutes:
        for x, y, group in pairs:
            try:
                sx, sy = source(x, m), source(y, m)
            except Exception:  # noqa: BLE001 - a key the bars do not keep
                sx = sy = None
            if not sx or not sy:
                continue
            times, vx, vy = align(sx[0], sx[1], sy[0], sy[1])
            row = {"minutes": m, "x": x, "y": y, "group": group, "n": max(0, len(times) - 1)}
            if len(times) - 1 < MIN_OBS:
                row["why"] = "bar az (%d)" % max(0, len(times) - 1)
                rows.append(row)
                continue
            res = lead_lag(changes(kinds.get(x, "rate"), vx), changes(kinds.get(y, "rate"), vy), max_lag, k)
            row.update({kk: res.get(kk) for kk in ("leader", "lag", "F", "p", "beta", "se", "t", "r2", "stable", "events")})
            if res["leader"] is None:
                row["why"] = "öncü yok"
            else:
                row["leader"] = x if res["leader"] == "x" else y
                row["follower"] = y if res["leader"] == "x" else x
            rows.append(row)
    return {"ok": True, "rows": rows, "minutes": list(minutes)}


# ---------------------------------------------------------------------------------------------- the quant worker's part
_PUBLIC = ("x", "y", "group", "x_label", "y_label", "n", "why", "lag", "F", "p", "order", "beta", "se", "t", "r2", "sigma", "b", "r_lag",
           "stability", "stable", "events", "leader", "follower", "leader_label", "follower_label", "granger_xy", "granger_yx", "sid", "xcorr",
           "asym_z")


def run(quant: Any, ctx: qf.Ctx, mons: List[qf.Monitor], tables: Dict[str, Any], timing: Optional[Dict[str, float]] = None) -> None:
    """The full fit's part (``Quant.compute``): every candidate pair on the daily closes, a monitor for each pair
    with a leader, the intraday table when there are bars.  Never raises: a failure is the fit's error ``lead``."""
    t0 = time.perf_counter()
    try:
        k = float(ctx.cfg.get("lead_k") or DEFAULTS["lead_k"])
        pairs = candidate_pairs(ctx)
        rows, own = [], []
        for x, y, group in pairs:
            row = analyse(ctx, x, y, group)
            if row.get("leader"):
                mon = LeadMonitor(ctx, row, k)
                own.append(mon)
                row["sid"] = mon.sid
            rows.append(row)
        mons.extend(own)
        kinds = {key: ctx.kind(key) for p in pairs for key in p[:2]}
        bars = intraday(bars_of(quant), pairs, kinds, k)
        tables["lead"] = {"rows": [{kk: r.get(kk) for kk in _PUBLIC if kk in r} for r in rows], "intraday": bars, "lags": int(ctx.cfg.get("lead_lag") or 5),
                          "k": k, "pairs": len(pairs), "_kinds": kinds, "_pairs": pairs, "_bars_at": time.time()}
    except Exception as exc:  # noqa: BLE001 - this module failing must not take the other families with it
        tables.setdefault("errors", {})["lead"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        tables["lead"] = {"rows": [], "why": tables["errors"]["lead"], "intraday": {"ok": False, "why": "", "rows": []}}
    if timing is not None:
        timing["lead"] = time.perf_counter() - t0


def refresh(quant: Any, fit: Dict[str, Any]) -> None:
    """The minute's refresh (``Quant.refresh_live``): the intraday table again, at most every five minutes, when the
    dashboard has bars (the monitors read the live values themselves)."""
    tab = (fit.get("tables") or {}).get("lead")
    if not tab or "_pairs" not in tab or time.time() - tab.get("_bars_at", 0.0) < REFRESH_BARS:
        return
    src = bars_of(quant)
    if src is None:
        return
    try:
        tab["intraday"] = intraday(src, tab["_pairs"], tab["_kinds"], float(tab.get("k") or DEFAULTS["lead_k"]))
    except Exception as exc:  # noqa: BLE001
        tab["intraday"] = {"ok": False, "why": "%s: %s" % (type(exc).__name__, str(exc)[:160]), "rows": []}
    tab["_bars_at"] = time.time()


def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "Öncü-Takipçi" reads: the pairs with the monitors' state now, the signals, the intraday table."""
    from .quant import _clean
    tab = copy.deepcopy({kk: x for kk, x in ((v.get("tables") or {}).get("lead") or {}).items() if not kk.startswith("_")})
    for r in tab.get("rows") or ():
        m = fit["mons"].get(r.get("sid") or "")
        if m is not None:
            now = getattr(m, "now", None) or {}
            r.update({"z": m.z, "level": m.level, "event": now.get("event"), "now": {kk: now.get(kk) for kk in ("lead_move", "follow_move", "catch_up",
                                                                                                           "sigma", "k_moved")}})
    base["lead"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["page"] == VIEWS[what]]
    base["settings"] = fit["cfg"]
    base["coverage"] = [c for c in fit.get("coverage") or () if any(c["key"] in (r.get("x"), r.get("y")) for r in tab.get("rows") or ())]
    base["errors"] = {kk: e for kk, e in ((v.get("tables") or {}).get("errors") or {}).items() if kk == "lead"}
    base["mode"] = getattr(quant.svc, "mode", "")
    return _clean(base)
