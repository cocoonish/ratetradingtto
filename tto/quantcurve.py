"""Curve fair value: a Nelson-Siegel-Svensson fit of the TRY OIS curve and a Nelson-Siegel one of the DİBS curve, each
point's rich / cheap against its fit, the bonds' carry + roll and the best bond to receive / pay with.  ``tto.quant``
runs it next to the families of ``tto.quantfam`` (page "Eğri Adil Değeri"; families "Eğri adil değeri" and "DİBS adil
değeri").

**The model.**  Svensson's extension of Nelson-Siegel writes the continuously compounded zero rate (ACT/365) of a
maturity of t years as

    z(t) = β0 + β1·g(t/τ1) + β2·(g(t/τ1) − e^(−t/τ1)) + β3·(g(t/τ2) − e^(−t/τ2)),    g(x) = (1 − e^(−x)) / x

(β0 the long end, β0 + β1 the overnight end, β2 and β3 two humps around τ1 and τ2) and the instantaneous forward
f(t) = β0 + β1·e^(−t/τ1) + β2·(t/τ1)·e^(−t/τ1) + β3·(t/τ2)·e^(−t/τ2).  With τ1 and τ2 held a zero rate is linear in the
β, so a fit is Gauss-Newton in the four β (Levenberg-Marquardt damping, started from a linear fit of rough zero
rates); the τ are searched on a grid with τ2 ≥ 2·τ1 (the two humps apart - closer, β2 and β3 are one and the same),
then Levenberg-Marquardt runs on all six parameters from the five best grid points (the NSS surface has several
shallow valleys, and the grid's order is not theirs) and the best one to the end.  The fits are robust: residuals
beyond two robust standard deviations are down-weighted (Huber, reweighted up to three times), so one bond far off its
value does not bend the curve onto its neighbours and make them look rich / cheap the other way.

**The τ are searched once a fit,** on the latest close (today's quotes when there is no history); every day of the
window is then fitted with them - only the β, each day started from the day before - and so is the live point every
minute.  A tenor's or a bond's distance from the curve is so measured with one model across the window: its z, half
life and regime (``quantfam.mr_monitor``) mean the same on every day.  The two searches of a fit (OIS, DİBS) take
0.15 - 0.3 s each, the window's daily refits a few hundred milliseconds.

**TRY OIS.**  The par rates are fitted in the workbook's own conventions - Motor!B88:K130 (the bootstrap) and
Motor!A325:K340 (each tenor's par and annuity, what OIS_MAIN's DV01 and the blotter use): a single payment at maturity
up to 3M, fixed coupons every three months from 6M on, ACT/365, the dates months on from the OIS spot (the next week
day): par = (1/DF(T) − 1)/τ, or (1 − DF(T)) / Σ τ_k·DF(t_k) on the quarterly schedule.  (``quantfam._annuity`` and the
FRA family read a tenor up to a year as one payment and annual coupons beyond: not what the workbook does -
``SINGLE_MONTHS`` / ``COUPON_MONTHS`` say which is used here.)  A tenor's rich / cheap is its quote − the fitted par
(bp): + it is cheap (receive), − rich (pay).  A signal's package is the tenor hedged with two neighbours to the fit's
level (β0) and slope (β1), DV01-weighted, as the PCA family hedges to PC1 / PC2.

**DİBS.**  The fixed-coupon bonds and the bills / zero-coupon bonds of the DİBS RV list (TLREF floaters, FRNs and CPI
linkers stay out), priced as that sheet prices them (BIST): coupons of c/f every round(364/f) days back from the
maturity, the yield compounded f times a year over the periods left (the first one a fraction of a period), a bill's
simple yield (100/P − 1)·365/days; the dirty price of the value date (the next week day; a bill priced "ISL0" on its own
day).  The curve is fitted to the fixed-coupon bonds' yields (``FIT_KINDS``, the desk's decision of 18.11.2026): each
bond's model price Σ CF·DF(t) against its market price, the difference divided by the price's sensitivity to its yield
(the sum is one of yield errors).  The bills are priced on that curve, not fitted to it: a bill's rich / cheap reads the
curve the coupon bonds give at the short end.  A bond's rich / cheap, fitted or not, is its yield − the yield of its
model price (bp, in the bond's own yield convention): + cheap (buy), − rich (sell).  The DİBS curve is Nelson-Siegel's
(``DIBS_MODEL``: β3 held at 0, one hump - with a dozen or two bonds Svensson's second hump fits the bonds' own noise, its
β run to hundreds of per cent and swing day to day; the evidence is at ``DIBS_MODEL``), its τ1 searched on the grid of
both τ.  Each fitted bond's leave-one-out residual - its distance from the curve fitted again without it, the τ held -
says how far the curve misses a bond it was not given (``BondFit.loo``; the table's "LOO RMSE").  Beside it the same
cash flows on the OIS fit: the bond's yield over the OIS curve (bp, the sheet's "Getiri − OIS" read cash flow by cash
flow - an asset-swap-like spread) next to the sheet's own ASW.

Live yields come from the DİBS RV sheet (its simple and compound BIST yields); past days from the history's daily
closes (Bloomberg's ``YLD_YTM_MID``, whose convention is not documented for these bonds): each bond's history is read
as the sheet's simple yield or as its compound one, whichever today's quotes of the sheet are closer to (at these
levels the two are 300 - 400 bp apart, a day's move a few dozen).

**Carry + roll** over a week and a month (7 / 30 days), per 100 nominal and in bp (÷ the DV01: the sheet's AM / AN
units).  Carry = the price at an unchanged yield + the coupons paid in between − the dirty price grown at the funding
rate; funding is the repo of the bond's row on the sheet, else the fitted OIS curve's rate to the horizon (the sheet's
default "Bootstrap" path), else TLREF compounded daily.  Roll = the price on the unchanged fitted curve (each cash flow
at the curve's rate of its new time to maturity, plus the bond's own spread to the curve) − the price at an unchanged
yield.  Coupons paid before the horizon are not reinvested.

**Receive / pay için en iyi kâğıt.**  score = z × (carry + roll over a month) ÷ σ, σ the month's standard deviation of
the bond's yield (its daily changes over the last 60 closes × √21): positive when the rich / cheap and the carry point
the same way - cheap with positive carry for receive (buy), rich with negative carry for pay (sell) - and the larger
the more both say so per unit of risk.  A bond whose carry argues against its z scores below zero on its side.

**A quote from the fair curve** (``/api/quant/quote``): any fixed-coupon DİBS - on the list, or by its ISIN with the
catalog's coupon and maturity - at its value date: the fair yield (the yield of Σ CF·DF on the curve now), its clean
and dirty price (accrued as the sheet's DİBS RV!Q: c/f × the days since the last coupon over the period's), and a
two-way quote at the desk's half spread of the bond's maturity bucket (bid = fair + half, ask = fair − half, bp of the
simple yield; ``QUOTE_DEFAULTS``, the desk's setting in the store); beside it the market yield, its distance from fair,
z, carry + roll, and the line to send.  **A switch** A → B (``/api/quant/switch``): sell A, buy B, the nominal of B
for 1 mn of A that keeps the DV01 (each at its market yield), the pickup against the curve (B's rich / cheap − A's),
the carry + roll difference, the switch's level and the z of B − A on the curve over their common days.
"""
from __future__ import annotations

import datetime as _dt
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf
from . import quantmath as qm

#: the families (``quantfam.FAMILIES`` takes them in), the page and the view of ``/api/quant/curve``
FAMILIES = {"curve": ("Eğri adil değeri", "mr", "quant-curve"), "dibsfv": ("DİBS adil değeri", "mr", "quant-curve")}
PAGES = (("quant-curve", "Eğri Adil Değeri"),)
VIEW = "curve"
TABLES = ("curve", "dibsfv")

#: the workbook's OIS: a single payment up to this tenor (months), fixed coupons every ``COUPON_MONTHS`` beyond
SINGLE_MONTHS = 3
COUPON_MONTHS = 3
#: the (τ1, τ2) grid of the search (years, about 1.55 apart); τ2 ≥ TAU_RATIO·τ1
TAU1_GRID = (0.1, 0.16, 0.25, 0.4, 0.6, 0.95, 1.5, 2.3, 3.6, 5.5)
TAU2_GRID = (0.5, 0.8, 1.2, 1.9, 3.0, 4.6, 7.0, 11.0, 17.0, 26.0)
TAU_RATIO = 2.0
TAU_BOUNDS = (0.05, 30.0)
#: τ1 at least this share of the shortest maturity of a fit
TAU_FLOOR = 0.5
#: the models by the β free in them: Nelson-Siegel (β0 … β2, τ1) and Svensson's (β0 … β3, τ1, τ2)
NS, NSS = 3, 4
MODEL_NAMES = {NS: "NS", NSS: "NSS"}
MODEL_TEXT = {NS: "Nelson-Siegel", NSS: "Nelson-Siegel-Svensson"}
MIN_OIS = 6                     # tenors a day's OIS fit needs
MIN_BONDS = 6                   # bonds a day's DİBS fit needs
MIN_DAYS = 30                   # a bond this close to its maturity (days) is left out of the fit
#: the kinds the DİBS curve is fitted to: the fixed-coupon bonds (the desk's decision, 18.11.2026).  The bills are priced
#: on the curve - a model yield and a rich / cheap, as any bond -, not fitted: their rich / cheap reads the curve the
#: coupon bonds give at the short end (on the recorded day 134 / 221 bp rich; fitted too they read 45 / 150)
FIT_KINDS = ("fixed",)
#: the DİBS curve's model: Nelson-Siegel, whatever the number of bonds.  On the evidence (18.11.2026, the recorded day
#: and histories fitted as the family fits them): on the list's 13 coupon bonds Svensson's two more parameters were not
#: better out of sample (leave-one-out RMSE 85 bp against NS's 73; 101 / 96 with the bills fitted too), its β ran to
#: ±900 % and moved 9 - 40 points a day against NS's 0,2 - 0,5 (measured with the bills fitted), its short end 2 - 3
#: times as unsteady; on synthetic lists of 8 - 40 bonds priced off a Svensson curve or an NS one (σ 5 / 25 / 50 bp)
#: NS's LOO was the lower or equal one in 34 cases of 36 (the two others one draw, 24 bonds at 50 bp, under both curves:
#: noise) - no number of bonds the list can hold is one where Svensson pays.  (The OIS curve stays Svensson's: 16
#: tenors, 1 - 3 bp.)
DIBS_MODEL = NS
HORIZONS = (("1w", 7), ("1m", 30))
YEAR = 365.0
DIBS_KINDS = {"S": "fixed", "B": "bill"}

RV_SHEET = "DİBS RV"
RV_ROWS = (5, 54)
#: what is read of a row of DİBS RV (engine thread): field -> column
RV_COLS = (("name", "C"), ("maturity", "E"), ("coupon", "CS"), ("freq", "CU"), ("value_date", "P"), ("dirty", "R"),
           ("simple", "S"), ("compound", "T"), ("mod_dur", "AG"), ("dv01", "AI"), ("repo", "AL"), ("asw", "Z"),
           ("wb_rc", "AB"), ("source", "BS"),
           # (the sheet's carry + roll over its horizon - DİBS RV!J2 months -: carry, roll and C+R in bp, C+R in TL a 1 mn:
           # the DİBS switch family's line tells it, quantdibssw.py)
           ("carry_bp", "AM"), ("roll_bp", "AN"), ("cr_bp", "AO"), ("cr_tl", "AP"))
#: DİBS RV's C+R horizon (months: "Ufuk (ay)")
RV_HORIZON = "J2"


# ---------------------------------------------------------------------------------------------- the curve
def _g(x: float) -> Tuple[float, float]:
    """(1 − e^−x)/x and e^−x (the first by its series near 0)."""
    e = math.exp(-x)
    return ((1.0 - e) / x if x > 1e-6 else 1.0 - 0.5 * x + x * x / 6.0), e


def loadings(t: float, tau1: float, tau2: float) -> Tuple[float, float, float, float]:
    """A zero rate's loadings on β0 … β3 at a maturity of ``t`` years."""
    a, e1 = _g(t / tau1)
    b, e2 = _g(t / tau2)
    return 1.0, a, a - e1, b - e2


class Nss(object):
    """A fitted curve: ``beta`` (decimal rates), ``tau1``, ``tau2`` (years); ``k`` the β free in it - 4 Svensson's
    (NSS), 3 Nelson-Siegel's (NS: β3 held at 0, τ2 says nothing).  ``beta`` is always four long."""

    __slots__ = ("beta", "tau1", "tau2", "k")

    def __init__(self, beta: Sequence[float], tau1: float, tau2: float, k: int = 4):
        self.beta = [float(b) for b in beta][:4]
        self.beta += [0.0] * (4 - len(self.beta))
        self.k = NS if k == NS else NSS
        if self.k == NS:
            self.beta[3] = 0.0
        self.tau1, self.tau2 = float(tau1), float(tau2)

    @property
    def model(self) -> str:
        return MODEL_NAMES[self.k]

    def zero(self, t: float) -> float:
        return sum(b * x for b, x in zip(self.beta, loadings(max(t, 0.0), self.tau1, self.tau2)))

    def forward(self, t: float) -> float:
        b0, b1, b2, b3 = self.beta
        x1, x2 = max(t, 0.0) / self.tau1, max(t, 0.0) / self.tau2
        e1, e2 = math.exp(-x1), math.exp(-x2)
        return b0 + b1 * e1 + b2 * x1 * e1 + b3 * x2 * e2

    def df(self, t: float) -> float:
        return math.exp(-self.zero(t) * t) if t > 0 else 1.0

    def info(self, longest: float = 10.0) -> Dict[str, Any]:
        """The parameters (per cent) and the curve's own zero rates at round maturities up to ``longest`` years - with
        few, noisy points the β can run large with opposite signs (the loadings nearly alike over the maturities
        fitted) while the curve inside them stays put: its rates say what the β do not.  ``model`` "NS" / "NSS" (an NS
        curve has no β3 nor τ2: ``None``)."""
        b = self.beta
        ns = self.k == NS
        return {"model": self.model, "b0": b[0] * 100.0, "b1": b[1] * 100.0, "b2": b[2] * 100.0, "b3": None if ns else b[3] * 100.0,
                "tau1": self.tau1, "tau2": None if ns else self.tau2,
                "zero": {"%gY" % t: self.zero(t) * 100.0 for t in (1.0, 2.0, 5.0, 10.0) if t <= longest + 1e-9}}


# ---------------------------------------------------------------------------------------------- least squares
def _normal(J: Sequence[Sequence[float]], r: Sequence[float], k: int) -> Tuple[List[List[float]], List[float]]:
    A = [[0.0] * k for _ in range(k)]
    g = [0.0] * k
    for row, e in zip(J, r):
        for a in range(k):
            ja = row[a]
            if ja:
                g[a] += ja * e
                Aa = A[a]
                for b in range(a, k):
                    Aa[b] += ja * row[b]
    for a in range(k):
        for b in range(a):
            A[a][b] = A[b][a]
    return A, g


Fn = Callable[[List[float]], Tuple[List[float], List[List[float]]]]


def _damped(A: List[List[float]], g: List[float], mu: float) -> Optional[List[float]]:
    """The Levenberg-Marquardt step (A + μ·diag(A)) d = −g (a floor on the diagonal for a direction without data)."""
    k = len(g)
    top = max(A[i][i] for i in range(k)) or 1.0
    M = [row[:] for row in A]
    for i in range(k):
        M[i][i] += mu * max(A[i][i], 1e-12 * top) + 1e-14 * top
    return qm.solve(M, [-x for x in g])


def gauss_newton(fn: Fn, beta: Sequence[float], iters: int = 12, tol: float = 1e-11,
                 first: Optional[Tuple[List[float], List[List[float]]]] = None) -> Tuple[List[float], float, List[float], List[List[float]]]:
    """Least squares by Gauss-Newton with Levenberg-Marquardt damping: ``fn(beta) -> (residuals, jacobian rows)``
    (``first``: what it gives at ``beta``, when known).  Stops when a step is below ``tol`` (no evaluation for it).
    Returns ``(beta, sse, residuals, jacobian)``."""
    beta = list(beta)
    r, J = first if first is not None else fn(beta)
    sse = sum(e * e for e in r)
    k = len(beta)
    mu = 0.0
    for _ in range(iters):
        A, g = _normal(J, r, k)
        done = True
        for _try in range(8):
            d = _damped(A, g, mu)
            if d is None:
                mu = max(mu * 10.0, 1e-6)
                continue
            if max(abs(x) for x in d) < tol:
                break
            nb = [b + x for b, x in zip(beta, d)]
            r2, J2 = fn(nb)
            s2 = sum(e * e for e in r2)
            if s2 <= sse * (1.0 + 1e-10) + 1e-300:
                beta, r, J, sse = nb, r2, J2, s2
                mu = mu * 0.1 if mu > 1e-9 else 0.0
                done = False
                break
            mu = max(mu * 10.0, 1e-4)
        if done:
            break
    return beta, sse, r, J


def _ols_start(ts: Sequence[float], zs: Sequence[float], tau1: float, tau2: float, k: int = NSS) -> List[float]:
    """The first ``k`` β of a linear fit of rough zero rates ``zs`` at maturities ``ts`` (a start for Gauss-Newton; a
    whisker of ridge keeps it defined when two loadings are alike)."""
    rows = [loadings(t, tau1, tau2)[:k] for t in ts]
    A, g = _normal(rows, zs, k)
    for i in range(k):
        A[i][i] += 1e-10 * (A[0][0] or 1.0)
    beta = qm.solve(A, g) if len(zs) >= k else None
    if beta is None or not all(math.isfinite(b) for b in beta):
        return [sum(zs) / len(zs) if zs else 0.3] + [0.0] * (k - 1)
    return beta


def _free(fn: Fn, k: int) -> Fn:
    """``fn`` of the first ``k`` β alone, the others held at 0 (Nelson-Siegel's problem out of Svensson's)."""
    if k >= NSS:
        return fn
    pad = [0.0] * (NSS - k)

    def fk(beta: List[float]) -> Tuple[List[float], List[List[float]]]:
        r, J = fn(list(beta) + pad)
        return r, [row[:k] for row in J]

    return fk


#: a problem for the search: (τ1, τ2) -> (its residual function, a function giving a start for the first k β)
Make = Callable[[float, float], Tuple[Fn, Callable[..., List[float]]]]


def _project(u1: float, u2: float, tau_min: float = TAU_BOUNDS[0], tau_max: float = TAU_BOUNDS[1]) -> Tuple[float, float]:
    """(log τ1, log τ2) brought inside the bounds - τ1 at least ``tau_min``, τ2 at most ``tau_max`` -, τ2 ≥ TAU_RATIO·τ1."""
    lo, hi = math.log(max(TAU_BOUNDS[0], tau_min)), math.log(min(TAU_BOUNDS[1], tau_max))
    u1 = min(max(u1, lo), hi - math.log(TAU_RATIO))
    u2 = min(max(u2, u1 + math.log(TAU_RATIO)), hi)
    return u1, u2


#: robust fits (Huber): a point farther than this many robust standard deviations (1.4826 × the median |residual|)
#: from the curve counts with the weight HUBER·s/|r| - one bond far off its value does not bend the curve onto its
#: neighbours (it would make them look rich / cheap the other way).  Reweighted at most ROBUST_PASSES times
#: (iteratively reweighted least squares), until the weights settle.
HUBER = 2.0
ROBUST_PASSES = 3


def huber_weights(r: Sequence[float]) -> Optional[List[float]]:
    """The Huber weights of residuals ``r`` (``None`` when every one is within the band)."""
    a = sorted(abs(e) for e in r)
    if len(a) < 5:
        return None
    n = len(a)
    s = 1.4826 * (a[n // 2] if n % 2 else 0.5 * (a[n // 2 - 1] + a[n // 2]))
    if not s > 1e-12:
        return None
    k = HUBER * s
    w = [1.0 if abs(e) <= k else k / abs(e) for e in r]
    return None if min(w) >= 1.0 else w


def _weighted(fn: Fn, w: Sequence[float]) -> Fn:
    sw = [math.sqrt(x) for x in w]

    def fw(beta: List[float]) -> Tuple[List[float], List[List[float]]]:
        r, J = fn(beta)
        return [e * s for e, s in zip(r, sw)], [[x * s for x in row] for row, s in zip(J, sw)]

    return fw


def _weighted_make(make: Make, w: Sequence[float]) -> Make:
    def mk(t1: float, t2: float) -> Tuple[Fn, Callable[..., List[float]]]:
        fn, start = make(t1, t2)
        return _weighted(fn, w), start

    return mk


def _joint(make: Make, beta: List[float], t1: float, t2: float, iters: int = 40, tau_min: float = TAU_BOUNDS[0],
           tau_max: float = TAU_BOUNDS[1], k: int = NSS) -> Tuple[float, List[float], List[float], List[List[float]], float, float, int]:
    """Levenberg-Marquardt on all the parameters - the ``k`` β and the log τ (log τ1, log τ2 for NSS; log τ1 for NS,
    its τ2 kept equal to it: β3 is 0) -, the τ columns of the Jacobian by forward differences - from a grid point.
    Returns ``(sse, beta, resid, jac_beta, tau1, tau2, evaluations)``, ``beta`` four long."""
    nt = 2 if k == NSS else 1
    lo, hi = math.log(max(TAU_BOUNDS[0], tau_min)), math.log(min(TAU_BOUNDS[1], tau_max))

    def place(a: float, b: float) -> Tuple[float, float]:
        if nt == 2:
            return _project(a, b, tau_min, tau_max)
        a = min(max(a, lo), hi)
        return a, a

    def problem(a: float, b: float) -> Fn:
        fn, _ = make(math.exp(a), math.exp(b))
        return _free(fn, k)

    u1, u2 = place(math.log(t1), math.log(t2))
    beta = list(beta[:k])
    fn = problem(u1, u2)
    r, J = fn(beta)
    sse = sum(e * e for e in r)
    mu = 1e-3
    evals = 1
    h = 1e-6
    for _ in range(iters):
        cols = []
        for j in range(nt):
            a, b = ((u1 + h, u2) if nt == 2 else (u1 + h, u1 + h)) if j == 0 else (u1, u2 + h)
            rh, _ = problem(a, b)(beta)
            evals += 1
            cols.append([(x - y) / h for x, y in zip(rh, r)])
        JJ = [list(row) + [c[i] for c in cols] for i, row in enumerate(J)]
        A, g = _normal(JJ, r, k + nt)
        moved = False
        for _try in range(10):
            d = _damped(A, g, mu)
            if d is None:
                mu *= 10.0
                continue
            if max(abs(x) for x in d) < 1e-12:
                break
            nu1, nu2 = place(u1 + d[k], u2 + d[k + 1] if nt == 2 else u1 + d[k])
            nb = [b + x for b, x in zip(beta, d[:k])]
            r2, J2 = problem(nu1, nu2)(nb)
            evals += 1
            s2 = sum(e * e for e in r2)
            if math.isfinite(s2) and s2 < sse:
                gain = (sse - s2) / sse if sse > 0 else 0.0
                beta, u1, u2, r, J, sse = nb, nu1, nu2, r2, J2, s2
                mu = max(mu / 3.0, 1e-12)
                moved = gain > 1e-13
                break
            mu *= 4.0
        if not moved:
            break
    return sse, beta + [0.0] * (NSS - k), r, J, math.exp(u1), math.exp(u2), evals


def search(make: Make, starts: int = 5, robust: bool = True, tau_min: float = TAU_BOUNDS[0],
           tau_max: float = TAU_BOUNDS[1], k: int = NSS) -> Optional[Dict[str, Any]]:
    """The NSS (``k`` 4) or NS (``k`` 3) of a problem: ``make(tau1, tau2) -> (fn, start)`` gives the residual function
    and (a function giving) a start of the β with those τ.  Every grid point a few Gauss-Newton steps in the β;
    Levenberg-Marquardt on all the parameters for a while from the ``starts`` best of them (the NSS surface has several
    shallow valleys, and the grid's order is not theirs), the best of those to the end; then, ``robust``, reweighted
    (Huber).  ``tau_min`` / ``tau_max``: the shortest / longest maturity of the problem - a hump far outside the data
    cannot be told from it, and there the β run off: a τ1 well below the shortest lets β1 and β2 run far apart into a
    front end like 1/t that an extrapolation (a roll-down) would read, two τ beyond the longest make the four loadings
    nearly polynomials in t (huge β of opposite sign, the same curve inside the data).  τ1 may go down to TAU_FLOOR ×
    the shortest (its e^(−t/τ1) still says something there), τ2 - NS's τ1 - up to the longest; NS's grid is both
    grids'.  ``{"nss", "sse", "resid", "jac", "evals", "weights"}`` - the residuals and the sum unweighted."""
    grid = []
    evals = 0
    floor = max(TAU_BOUNDS[0], TAU_FLOOR * tau_min)
    ceil = max(min(TAU_BOUNDS[1], tau_max), TAU_RATIO * floor)
    if k == NSS:
        pairs = [(t1, t2) for t1 in sorted({max(t, floor) for t in TAU1_GRID}) for t2 in sorted({min(t, ceil) for t in TAU2_GRID})
                 if not t2 < TAU_RATIO * t1 * (1.0 - 1e-12)]
    else:
        pairs = [(t, t) for t in sorted({min(max(t, floor), ceil) for t in TAU1_GRID + TAU2_GRID})]
    for t1, t2 in pairs:
        fn, start = make(t1, t2)
        beta, sse, _, _ = gauss_newton(_free(fn, k), start(k), iters=4, tol=1e-9)
        evals += 5
        if all(math.isfinite(b) for b in beta) and math.isfinite(sse):
            grid.append((sse, beta, t1, t2))
    if not grid:
        return None
    grid.sort(key=lambda g: g[0])
    best = None
    for sse0, beta, t1, t2 in grid[:starts]:
        res = _joint(make, beta, t1, t2, iters=25, tau_min=floor, tau_max=ceil, k=k)
        evals += res[6]
        if best is None or res[0] < best[0]:
            best = res
    res = _joint(make, best[1], best[4], best[5], iters=80, tau_min=floor, tau_max=ceil, k=k)
    evals += res[6]
    if res[0] <= best[0]:
        best = res
    sse, beta, r, J, t1, t2, _ = best
    w = None
    for _ in range(ROBUST_PASSES if robust else 0):
        w2 = huber_weights(r)
        if w2 is None or (w is not None and max(abs(a - b) for a, b in zip(w, w2)) < 0.02):
            break
        w = w2
        res = _joint(_weighted_make(make, w), beta, t1, t2, iters=40, tau_min=floor, tau_max=ceil, k=k)
        evals += res[6]
        beta, t1, t2 = res[1], res[4], res[5]
        r, J = _unweighted(res[2], res[3], w)
        sse = sum(e * e for e in r)
    return {"nss": Nss(beta, t1, t2, k), "sse": sse, "resid": r, "jac": J, "evals": evals, "weights": w}


def _unweighted(r: Sequence[float], J: Sequence[Sequence[float]], w: Sequence[float]) -> Tuple[List[float], List[List[float]]]:
    sw = [math.sqrt(x) for x in w]
    return [e / s for e, s in zip(r, sw)], [[x / s for x in row] for row, s in zip(J, sw)]


def refit(make: Make, nss: Nss, start: Optional[Sequence[float]] = None, iters: int = 8, robust: bool = True,
          tol: float = 1e-9) -> Dict[str, Any]:
    """The β of a problem with the model and the τ of ``nss`` held (from ``start``, else the problem's own start);
    ``robust``: then reweighted (Huber) as the search does.  The residuals and the sum unweighted."""
    k = nss.k
    fn, own = make(nss.tau1, nss.tau2)
    fn = _free(fn, k)
    beta, sse, r, J = gauss_newton(fn, list(start)[:k] if start is not None else own(k), iters, tol)
    w = None
    for _ in range(ROBUST_PASSES if robust else 0):
        w2 = huber_weights(r)
        if w2 is None or (w is not None and max(abs(a - b) for a, b in zip(w, w2)) < 0.02):
            break
        w = w2
        sw = [math.sqrt(x) for x in w]
        first = ([e * s for e, s in zip(r, sw)], [[x * s for x in row] for row, s in zip(J, sw)])
        beta, _, rw, Jw = gauss_newton(_weighted(fn, w), beta, iters, tol, first)
        r, J = _unweighted(rw, Jw, w)
        sse = sum(e * e for e in r)
    return {"nss": Nss(beta, nss.tau1, nss.tau2, k), "sse": sse, "resid": r, "jac": J, "weights": w}


# ---------------------------------------------------------------------------------------------- dates
def _weekday_on_or_after(d: _dt.date) -> _dt.date:
    while d.weekday() >= 5:
        d += _dt.timedelta(days=1)
    return d


def next_weekday(d: _dt.date) -> _dt.date:
    return _weekday_on_or_after(d + _dt.timedelta(days=1))


# ---------------------------------------------------------------------------------------------- TRY OIS
class OisDay(object):
    """One day's OIS par rates and the payment times of each tenor in the workbook's conventions.  ``quotes``:
    ``(key, months, par)`` with par a decimal rate."""

    def __init__(self, day: _dt.date, quotes: Sequence[Tuple[str, float, float]]):
        self.day = day
        self.spot = next_weekday(day)
        self.keys: List[str] = []
        self.months: List[float] = []
        self.par: List[float] = []
        self.mat: List[float] = []                     # each tenor's maturity (years from the spot)
        index: Dict[_dt.date, int] = {}
        self.ts: List[float] = []

        def at(d: _dt.date) -> int:
            i = index.get(d)
            if i is None:
                i = index[d] = len(self.ts)
                self.ts.append((d - self.spot).days / YEAR)
            return i

        dates: Dict[int, _dt.date] = {}

        def month_day(m: int) -> _dt.date:
            d = dates.get(m)
            if d is None:
                d = dates[m] = _weekday_on_or_after(qf._add_months(self.spot, m))
            return d

        # the coupon schedule every coupon tenor shares (months COUPON_MONTHS, 2·COUPON_MONTHS, …): its annuity is a
        # prefix of the same sum; a tenor off that grid keeps a schedule of its own
        quotes = sorted((q for q in quotes if q[2] is not None and math.isfinite(q[2]) and int(round(q[1])) >= 1), key=lambda q: q[1])
        longest = max([int(round(q[1])) for q in quotes] or [0])
        self.grid: List[Tuple[int, float]] = []
        prev = self.spot
        for k in range(COUPON_MONTHS, longest + 1, COUPON_MONTHS):
            d = month_day(k)
            self.grid.append((at(d), (d - prev).days / YEAR))
            prev = d
        # per tenor: (index of its maturity, kind, data) - "single": its accrual; "grid": how many grid dates; "own": its schedule
        self.legs: List[Tuple[int, str, Any]] = []
        for key, months, par in quotes:
            m = int(round(months))
            end = month_day(m)
            ie = at(end)
            if m <= SINGLE_MONTHS:
                self.legs.append((ie, "single", (end - self.spot).days / YEAR))
            elif m % COUPON_MONTHS == 0:
                self.legs.append((ie, "grid", m // COUPON_MONTHS))
            else:
                sched: List[Tuple[int, float]] = []
                prev = self.spot
                for k in list(range(COUPON_MONTHS, m, COUPON_MONTHS)) + [m]:
                    d = month_day(k)
                    sched.append((at(d), (d - prev).days / YEAR))
                    prev = d
                self.legs.append((ie, "own", sched))
            self.keys.append(key)
            self.months.append(months)
            self.par.append(par)
            self.mat.append(self.ts[ie])

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def shortest(self) -> float:
        """The shortest maturity of the fit (years)."""
        return min(self.mat) if self.mat else TAU_BOUNDS[0]

    @property
    def longest(self) -> float:
        """The longest maturity of the fit (years)."""
        return max(self.mat) if self.mat else TAU_BOUNDS[1]

    def _annuities(self, dfs: Sequence[float], dd: Optional[Sequence[Sequence[float]]] = None) -> Tuple[List[float], List[List[float]]]:
        """Σ τ_k·DF(t_k) over the first n grid dates for every n (and its β-derivatives, given ∂DF/∂β)."""
        ann, dann = [0.0], [[0.0, 0.0, 0.0, 0.0]]
        a = 0.0
        da = [0.0, 0.0, 0.0, 0.0]
        for i, tau in self.grid:
            a += tau * dfs[i]
            ann.append(a)
            if dd is not None:
                di = dd[i]
                da = [da[0] + tau * di[0], da[1] + tau * di[1], da[2] + tau * di[2], da[3] + tau * di[3]]
                dann.append(da)
        return ann, dann

    def pars(self, nss: Nss) -> List[float]:
        """The par rates the curve gives every tenor."""
        dfs = [nss.df(t) for t in self.ts]
        ann, _ = self._annuities(dfs)
        out = []
        for ie, kind, data in self.legs:
            if kind == "single":
                out.append((1.0 / dfs[ie] - 1.0) / data)
            else:
                a = ann[data] if kind == "grid" else sum(tau * dfs[i] for i, tau in data)
                out.append((1.0 - dfs[ie]) / a)
        return out

    def make(self, tau1: float, tau2: float) -> Tuple[Fn, List[float]]:
        L = [loadings(t, tau1, tau2) for t in self.ts]
        ts = self.ts
        legs = self.legs
        par = self.par

        def fn(beta: List[float]) -> Tuple[List[float], List[List[float]]]:
            b0, b1, b2, b3 = beta
            dfs = []
            dd = []                                      # ∂DF/∂β_j
            for t, (l0, l1, l2, l3) in zip(ts, L):
                df = math.exp(-(b0 + b1 * l1 + b2 * l2 + b3 * l3) * t)
                dfs.append(df)
                c = -t * df
                dd.append((c, c * l1, c * l2, c * l3))
            ann, dann = self._annuities(dfs, dd)
            r, J = [], []
            for (ie, kind, data), p in zip(legs, par):
                df = dfs[ie]
                de = dd[ie]
                if kind == "single":
                    r.append((1.0 / df - 1.0) / data - p)
                    k = -1.0 / (df * df * data)
                    J.append([k * de[0], k * de[1], k * de[2], k * de[3]])
                    continue
                if kind == "grid":
                    a, da = ann[data], dann[data]
                else:
                    a = sum(tau * dfs[i] for i, tau in data)
                    da = [sum(tau * dd[i][j] for i, tau in data) for j in range(4)]
                r.append((1.0 - df) / a - p)
                a2 = a * a
                J.append([(-de[j] * a - (1.0 - df) * da[j]) / a2 for j in range(4)])
            return r, J

        def start(k: int = NSS) -> List[float]:
            # rough zeros: the single payment's own, a coupon tenor's rate as continuous compounding of its frequency
            zs = []
            f = 12.0 / COUPON_MONTHS
            for (ie, kind, data), p in zip(legs, par):
                t = ts[ie]
                zs.append((math.log(1.0 + p * data) / t if t > 0 else p) if kind == "single" else f * math.log(1.0 + p / f))
            return _ols_start([ts[ie] for ie, _, _ in legs], zs, tau1, tau2, k)

        return fn, start


# ---------------------------------------------------------------------------------------------- DİBS
class Bond(object):
    """A fixed-coupon bond or a bill as the DİBS RV sheet prices it (BIST conventions).  ``coupon``: % a year of 100,
    paid ``freq`` times a year, every round(364/freq) days back from the maturity."""

    __slots__ = ("isin", "name", "kind", "maturity", "coupon", "freq", "period")

    def __init__(self, isin: str, name: str, kind: str, maturity: _dt.date, coupon: float = 0.0, freq: int = 2):
        self.isin, self.name, self.kind, self.maturity = isin, name or isin, kind, maturity
        self.coupon = float(coupon or 0.0)
        self.freq = int(freq) if freq and int(freq) > 0 else 2
        self.period = int(round(364.0 / self.freq))

    def flows(self, value: _dt.date) -> Tuple[List[Tuple[_dt.date, float]], float]:
        """The cash flows after the value date (per 100) and the fraction of the current coupon period left."""
        if value >= self.maturity:
            return [], 0.0
        if self.kind == "bill":
            return [(self.maturity, 100.0)], 0.0
        dates = []
        d = self.maturity
        while d > value:
            dates.append(d)
            d -= _dt.timedelta(days=self.period)
        dates.reverse()
        cpn = self.coupon / self.freq
        out = [(x, cpn) for x in dates]
        out[-1] = (out[-1][0], cpn + 100.0)
        return out, (dates[0] - value).days / float(self.period)

    def price(self, y: float, value: _dt.date, conv: str = "simple") -> Tuple[float, float]:
        """Dirty price per 100 at the yield ``y`` (decimal; ``conv`` "simple": compounded ``freq`` times a year - a
        bill's simple ACT/365 -, "compound": once a year) and its derivative dP/dy."""
        if self.kind == "bill":
            days = (self.maturity - value).days / YEAR
            if conv == "compound":
                p = 100.0 * (1.0 + y) ** (-days)
                return p, -days * p / (1.0 + y)
            q = 1.0 + y * days
            return 100.0 / q, -100.0 * days / (q * q)
        flows, frac = self.flows(value)
        f = float(self.freq)
        if conv == "compound":
            ys = f * ((1.0 + y) ** (1.0 / f) - 1.0)
            dys = (1.0 + y) ** (1.0 / f - 1.0)
        else:
            ys, dys = y, 1.0
        base = 1.0 + ys / f
        p = dp = 0.0
        for k, (_, cf) in enumerate(flows):
            n = k + frac
            v = cf * base ** (-n)
            p += v
            dp -= n / f * v / base
        return p, dp * dys

    def yield_of(self, p: float, value: _dt.date, conv: str = "simple", guess: Optional[float] = None) -> Optional[float]:
        """The yield of a dirty price (Newton, from ``guess``)."""
        y = guess if guess is not None and math.isfinite(guess) else 0.3
        for _ in range(40):
            q, dq = self.price(y, value, conv)
            if not dq:
                return None
            step = (q - p) / dq
            y -= step
            if y <= -0.99:
                y = -0.5
            if abs(step) < 1e-13:
                return y
        return y if abs(self.price(y, value, conv)[0] - p) < 1e-8 else None


class BondFit(object):
    """One day's bonds for a fit: per bond its value date, market yield (and convention), cash flows in years from the
    value date, the dirty price and its yield sensitivity.  The curve is fitted to the bonds of ``fit_kinds``
    (``fitted``: their places); every bond is measured against it (:meth:`evaluate`)."""

    def __init__(self, items: Sequence[Tuple[Bond, _dt.date, float, str]], fit_kinds: Sequence[str] = FIT_KINDS):
        self.bonds: List[Bond] = []
        self.value: List[_dt.date] = []
        self.y: List[float] = []
        self.conv: List[str] = []
        self.flows: List[List[Tuple[float, float]]] = []
        self.p: List[float] = []
        self.d: List[float] = []                          # −dP/dy (> 0)
        for bond, value, y, conv in items:
            if y is None or not math.isfinite(y) or (bond.maturity - value).days < MIN_DAYS:
                continue
            flows, _ = bond.flows(value)
            if not flows:
                continue
            p, dp = bond.price(y, value, conv)
            if not (p > 0 and dp < 0):
                continue
            self.bonds.append(bond)
            self.value.append(value)
            self.y.append(y)
            self.conv.append(conv)
            self.flows.append([((d - value).days / YEAR, cf) for d, cf in flows])
            self.p.append(p)
            self.d.append(-dp)
        self.fitted = [i for i, b in enumerate(self.bonds) if b.kind in fit_kinds]

    def __len__(self) -> int:
        return len(self.bonds)

    @property
    def n_fit(self) -> int:
        return len(self.fitted)

    @property
    def n_bills(self) -> int:
        """The bills priced on the curve and not fitted to it (``FIT_KINDS``: the fixed-coupon bonds alone)."""
        fit = set(self.fitted)
        return sum(1 for i, b in enumerate(self.bonds) if b.kind == "bill" and i not in fit)

    @property
    def shortest(self) -> float:
        """The shortest maturity of the fit (years)."""
        return min(self.flows[i][-1][0] for i in self.fitted) if self.fitted else TAU_BOUNDS[0]

    @property
    def longest(self) -> float:
        """The longest maturity of the fit (years)."""
        return max(self.flows[i][-1][0] for i in self.fitted) if self.fitted else TAU_BOUNDS[1]

    def model_prices(self, nss: Nss, spread: Optional[Sequence[float]] = None) -> List[float]:
        out = []
        for i, fl in enumerate(self.flows):
            s = spread[i] if spread is not None else 0.0
            out.append(sum(cf * math.exp(-(nss.zero(t) + s) * t) for t, cf in fl))
        return out

    def model_yields(self, nss: Nss) -> List[Optional[float]]:
        return [b.yield_of(p, v, c, y) for b, p, v, c, y in zip(self.bonds, self.model_prices(nss), self.value, self.conv, self.y)]

    def _fn(self, idx: Sequence[int], tau1: float, tau2: float) -> Fn:
        """The residuals of the bonds ``idx`` - (model price − market price) / (−dP/dy), the market yield − the model
        yield to first order - and their β-derivatives."""
        pre = [[(t, cf, loadings(t, tau1, tau2)) for t, cf in self.flows[i]] for i in idx]
        p_mkt = [self.p[i] for i in idx]
        d = [self.d[i] for i in idx]

        def fn(beta: List[float]) -> Tuple[List[float], List[List[float]]]:
            b0, b1, b2, b3 = beta
            r, J = [], []
            for fl, pm, di in zip(pre, p_mkt, d):
                p = 0.0
                g0 = g1 = g2 = g3 = 0.0
                for t, cf, (l0, l1, l2, l3) in fl:
                    v = cf * math.exp(-(b0 + b1 * l1 + b2 * l2 + b3 * l3) * t)
                    p += v
                    w = -t * v
                    g0 += w
                    g1 += w * l1
                    g2 += w * l2
                    g3 += w * l3
                r.append((p - pm) / di)
                J.append([g0 / di, g1 / di, g2 / di, g3 / di])
            return r, J

        return fn

    def evaluate(self, nss: Nss) -> Tuple[List[float], List[List[float]]]:
        """Every bond against the curve: its residual (yield, + cheap) and its β-derivatives."""
        return self._fn(range(len(self.bonds)), nss.tau1, nss.tau2)(nss.beta)

    def make(self, tau1: float, tau2: float) -> Tuple[Fn, Callable[..., List[float]]]:
        fn = self._fn(self.fitted, tau1, tau2)

        def start(k: int = NSS) -> List[float]:
            # rough zeros: each bond's yield as a continuous rate at its maturity
            ts, zs = [], []
            for i in self.fitted:
                b, y, c, fl = self.bonds[i], self.y[i], self.conv[i], self.flows[i]
                t = fl[-1][0]
                if b.kind == "bill":
                    z = math.log(1.0 + y) if c == "compound" else math.log(1.0 + y * t) / t
                else:
                    z = math.log(1.0 + y) if c == "compound" else b.freq * math.log(1.0 + y / b.freq)
                ts.append(t)
                zs.append(z)
            return _ols_start(ts, zs, tau1, tau2, k)

        return fn, start

    def spreads(self, nss: Nss) -> List[Optional[float]]:
        """Each bond's z-spread over the curve: the constant added to every rate that gives its market price."""
        out = []
        for fl, pm in zip(self.flows, self.p):
            s = 0.0
            for _ in range(30):
                p = dp = 0.0
                for t, cf in fl:
                    v = cf * math.exp(-(nss.zero(t) + s) * t)
                    p += v
                    dp -= t * v
                if not dp:
                    break
                step = (p - pm) / dp
                s -= step
                if abs(step) < 1e-13:
                    break
            out.append(s if math.isfinite(s) else None)
        return out

    def loo(self, nss: Nss) -> List[Optional[float]]:
        """Leave one out: each fitted bond's residual (yield, + cheap) against the curve fitted again without it - the
        model and the τ of ``nss`` held, the β refitted as the fit does (robust) -, in the order of ``fitted``: how far
        the curve misses a bond it was not given.  ``None`` where too few bonds are left."""
        out: List[Optional[float]] = []
        for j in self.fitted:
            idx = [i for i in self.fitted if i != j]
            if len(idx) < MIN_BONDS:
                out.append(None)
                continue

            def make(t1: float, t2: float, idx: List[int] = idx) -> Tuple[Fn, Callable[..., List[float]]]:
                return self._fn(idx, t1, t2), lambda k=NSS: list(nss.beta[:k])

            fit = refit(make, nss, nss.beta, iters=8)
            out.append(self._fn([j], nss.tau1, nss.tau2)(fit["nss"].beta)[0][0])
        return out


def dibs_search(fit_in: BondFit) -> Optional[Dict[str, Any]]:
    """The DİBS curve searched on the bonds of ``fit_in``: ``DIBS_MODEL`` (the quant family and DİBS RV · Genel alike)."""
    return search(fit_in.make, tau_min=fit_in.shortest, tau_max=fit_in.longest, k=DIBS_MODEL)


def loo_rmse(fit_in: BondFit, nss: Nss) -> Optional[float]:
    """The leave-one-out residuals' root mean square (bp): ``BondFit.loo``."""
    r = [e for e in fit_in.loo(nss) if e is not None]
    return math.sqrt(sum(e * e for e in r) / len(r)) * 1e4 if r else None


def carry_roll(bond: Bond, value: _dt.date, y: float, conv: str, nss: Nss, spread: float, days: int,
               fund: Callable[[float], float]) -> Optional[Dict[str, float]]:
    """Carry and roll of a bond over ``days`` (see the module text): ``{carry, roll}`` per 100 nominal and
    ``{carry_bp, roll_bp}`` (÷ today's DV01, the sheet's AM / AN units).  ``fund(t)`` is the funding growth factor over t years."""
    end = value + _dt.timedelta(days=days)
    if end >= bond.maturity:
        return None
    p0, dp0 = bond.price(y, value, conv)
    flows, _ = bond.flows(value)
    paid = sum(cf for d, cf in flows if d <= end)
    p_y, _ = bond.price(y, end, conv)
    p_c = sum(cf * math.exp(-(nss.zero((d - end).days / YEAR) + spread) * (d - end).days / YEAR) for d, cf in flows if d > end)
    carry = p_y + paid - p0 * fund(days / YEAR)
    roll = p_c - p_y
    dv01 = -dp0 * 1e-4                                   # today's: the sheet's FB / FC divide by its ED
    if not dv01 > 0:
        return None
    return {"carry": carry, "roll": roll, "carry_bp": carry / dv01, "roll_bp": roll / dv01}


#: a history's last close farther than this from both of the sheet's yields (per cent) says nothing of its convention
CONV_REACH = 1.5


def detect_convention(last: Optional[float], simple: Optional[float], compound: Optional[float]) -> str:
    """Which of the sheet's two yields (per cent) a history's last close (per cent) is: "compound" when it is the
    closer one (and within ``CONV_REACH``), "simple" otherwise."""
    if last is None or simple is None or compound is None:
        return "simple"
    near = abs(last - compound)
    return "compound" if near < abs(last - simple) and near <= CONV_REACH else "simple"


# ---------------------------------------------------------------------------------------------- the engine's part
def read_engine(out: Dict[str, Any], index: Dict[str, int], reader: Callable[[str], Callable[[str], Any]],
                num: Callable[[Any], Optional[float]]) -> None:
    """``quant.Quant._read_engine`` (engine thread, short): the fixed-coupon bonds and bills of the DİBS RV list as
    the sheet has them now - static data, value date, dirty price, its simple and compound yields, duration, DV01, the
    row's repo, the sheet's own ASW and rich / cheap, its carry + roll (AM:AP) - into ``out["dibs"]``; the C+R's horizon
    (J2, months) into ``out["dibs_cr_months"]``."""
    from .xl.values import serial_to_date
    rows: List[Dict[str, Any]] = []
    out["dibs"] = rows
    if RV_SHEET not in index:
        return
    get = reader(RV_SHEET)
    out["dibs_cr_months"] = num(get(RV_HORIZON))

    def day(v: Any) -> Optional[str]:
        return serial_to_date(v).isoformat() if type(v) is float and 20000 < v < 80000 else None

    for r in range(RV_ROWS[0], RV_ROWS[1] + 1):
        isin = get("A%d" % r)
        if not isinstance(isin, str) or not isin.strip():
            continue
        kind = get("D%d" % r)
        if not isinstance(kind, str) or kind.strip().upper() not in DIBS_KINDS:
            continue
        row: Dict[str, Any] = {"isin": isin.strip().upper(), "type": kind.strip().upper(), "row": r}
        for field, col in RV_COLS:
            v = get("%s%d" % (col, r))
            if field in ("maturity", "value_date"):
                row[field] = day(v)
            elif field in ("name", "source"):
                row[field] = v.strip() if isinstance(v, str) else ""
            else:
                row[field] = num(v)
        rows.append(row)


def series_specs(source: str = "") -> List[Dict[str, str]]:
    """``quant.series_specs``: no series of its own (the OIS tenors and the bonds are the history's)."""
    return []


def live_values(eng: Dict[str, Any]) -> Dict[str, float]:
    """``quant.Quant._live_values``: each bond's simple and compound yield on the sheet now (per cent), as
    ``DIBSS:<isin>`` / ``DIBSC:<isin>``."""
    out: Dict[str, float] = {}
    for row in eng.get("dibs") or []:
        if row.get("simple") is not None:
            out["DIBSS:" + row["isin"]] = row["simple"] * 100.0
        if row.get("compound") is not None:
            out["DIBSC:" + row["isin"]] = row["compound"] * 100.0
    return out


def covers(key: str) -> bool:
    """The series the page's data-coverage table lists."""
    return key.startswith("OIS:") or key == "TLREF"


# ---------------------------------------------------------------------------------------------- the OIS family
def _ois_keys(ctx: qf.Ctx) -> List[str]:
    keys = [k for k, m in ctx.meta.items() if k.startswith("OIS:") and (m.get("months") or 0) >= 1]
    return sorted(keys, key=lambda k: ctx.meta[k]["months"])


def _quotes(ctx: qf.Ctx, keys: Sequence[str], values: Callable[[str], Optional[float]]) -> List[Tuple[str, float, float]]:
    out = []
    for k in keys:
        v = values(k)
        if v is not None:
            out.append((k, float(ctx.meta[k]["months"]), v / 100.0))
    return out


def _cached(fn: Callable[[Tuple], Any]) -> Callable[[Tuple], Any]:
    """One result kept: the live refresh asks every monitor with the same values (and a quote, from a request's
    thread, the worker's last ones) - each caller gets what was computed for its own key."""
    memo: Dict[str, Any] = {"key": None, "val": None}
    lock = threading.Lock()

    def get(key: Tuple) -> Any:
        with lock:
            if memo["key"] == key:
                return memo["val"]
        val = fn(key)
        with lock:
            memo["key"], memo["val"] = key, val
        return val

    return get


def _exposures(jac: Sequence[Sequence[float]], sign: float = 1.0) -> List[List[float]]:
    """Level and slope exposures of each point (the fit's Jacobian on β0 and β1): what the hedges neutralise."""
    return [[sign * row[0] for row in jac], [sign * row[1] for row in jac]]


def fam_curve(ctx: qf.Ctx) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """NSS of the TRY OIS curve: today's fit and every tenor's rich / cheap, monitored."""
    keys = _ois_keys(ctx)
    win = ctx.window()
    if len(keys) < MIN_OIS:
        return [], {"ok": False, "why": "OIS eğrisinde en az %d vade gerekli" % MIN_OIS, "rows": []}
    days = sorted({d for k in keys for d in ctx.series.get(k, {})})[-win:]
    days = [d for d in days if sum(1 for k in keys if d in ctx.series.get(k, {})) >= MIN_OIS]
    t0 = time.perf_counter()
    # the τ: the latest close with most of the curve (today's quotes without a history)
    base = None
    for d in reversed(days):
        q = _quotes(ctx, keys, lambda k, d=d: ctx.series[k].get(d))
        if len(q) >= max(MIN_OIS, int(0.8 * len(keys))):
            base = OisDay(_dt.date.fromisoformat(d), q)
            break
    if base is None:
        q = _quotes(ctx, keys, lambda k: ctx.cur(k))
        if len(q) < MIN_OIS:
            return [], {"ok": False, "why": "OIS kotası yok", "rows": []}
        base = OisDay(ctx.today, q)
    found = search(base.make, tau_min=base.shortest, tau_max=base.longest)
    if found is None:
        return [], {"ok": False, "why": "NSS uyumu kurulamadı", "rows": []}
    nss0: Nss = found["nss"]
    search_ms = (time.perf_counter() - t0) * 1000.0
    # every day of the window with those τ
    resid: Dict[str, List[Tuple[str, float]]] = {k: [] for k in keys}
    rmse: List[Tuple[str, float]] = []
    beta = None
    for d in days:
        q = _quotes(ctx, keys, lambda k, d=d: ctx.series[k].get(d))
        day = OisDay(_dt.date.fromisoformat(d), q)
        fit = refit(day.make, nss0, beta, iters=6)
        beta = fit["nss"].beta
        for k, e in zip(day.keys, fit["resid"]):
            resid[k].append((d, -e * 1e4))                # quote − fit (bp): + cheap
        rmse.append((d, math.sqrt(fit["sse"] / len(day)) * 1e4))
    last_beta = beta or nss0.beta

    def today(key: Tuple) -> Optional[Dict[str, Any]]:
        q = [(k, float(ctx.meta[k]["months"]), v / 100.0) for k, v in zip(keys, key) if v is not None]
        if len(q) < MIN_OIS:
            return None
        day = OisDay(ctx.today, q)
        fit = refit(day.make, nss0, last_beta, iters=8)
        return {"day": day, "fit": fit, "resid": {k: -e * 1e4 for k, e in zip(day.keys, fit["resid"])}}

    now = _cached(today)

    def snap(live: Dict[str, float]) -> Optional[Dict[str, Any]]:
        return now(tuple(ctx.cur(k, live) for k in keys))

    first = snap(ctx.live)
    expo_day = first["day"] if first else base
    expo_fit = first["fit"] if first else refit(base.make, nss0, last_beta)
    vec = _exposures(expo_fit["jac"])
    order = list(expo_day.keys)
    mons: List[qf.Monitor] = []
    by_key: Dict[str, qf.Monitor] = {}
    for j, key in enumerate(order):
        pts = resid.get(key) or []
        hedge = qf._hedges(order, vec, j)
        legs = [{"key": key, "name": qf._ois_name(ctx, key), "weight": 1.0}] + [
            {"key": order[h], "name": qf._ois_name(ctx, order[h]), "weight": w} for h, w in hedge]

        def calc(live: Dict[str, float], key: str = key) -> Optional[float]:
            s = snap(live)
            return s["resid"].get(key) if s else None

        def quote(live: Dict[str, float], key: str = key, legs: List[Dict[str, Any]] = legs) -> Optional[Dict[str, Any]]:
            # the tenor as the desk trades it: its quote now; at a zero gap the fit's par rate of it (today's fit, the
            # live refit - held for the target and the stop: quote = fit + gap exactly)
            s = snap(live)
            r, rate = (s["resid"].get(key) if s else None), ctx.cur(key, live)
            if r is None or rate is None:
                return None
            fit = rate - r / 100.0
            name = qf._ois_name(ctx, key)
            return {"inst": name, "unit": "%", "digits": 2, "base": fit, "scale": 0.01,
                    "gap": {"name": "NSS farkı", "of": "NSS uyumunun", "at": "NSS uyumunda"},
                    "model": "NSS uyumunun %s par faizi (%%%s)" % (name, qf._th(fit, 2)), "note": "hedef / stop bugünkü NSS uyumuyla",
                    "held": "Hedef ve stop bugünkü NSS uyumuyla (uyumun %s par faizi %%%s): eğri yeniden uyunca onlar da değişir." % (
                        name, qf._th(fit, 2)),
                    "legs": [{"key": lg["key"], "name": lg["name"], "level": ctx.cur(lg["key"], live), "unit": "%", "digits": 2} for lg in legs]}

        # the series is the tenor's own distance from the fit ("NSS farkı"); the trade is the tenor against its two
        # neighbours - the hedge is the package's, not the series'
        mon = qf.mr_monitor(ctx, "curve:" + key, "curve", "TRY OIS", "%s OIS · NSS farkı" % key.split(":", 1)[1], "bp", 1,
                            [d for d, _ in pts], [v for _, v in pts], "bp", legs, calc, carry_up=qf._pkg_carry(ctx, legs), pkg="rate", quote=quote,
                            series_label="%s OIS − NSS uyumunun par faizi (bp)" % key.split(":", 1)[1],
                            info={"hedge": [{"key": order[h], "weight": w} for h, w in hedge]}, explicit=True,
                            pkg_name="Paket · iki komşu vadeyle hedge'li (NSS seviye β0 ve eğim β1'e nötr, DV01 ağırlıklı)",
                            note="Seri: kotanın NSS (Nelson-Siegel-Svensson) uyumundan farkı (bp, Excel'in OIS kuralıyla: 3A'ya kadar tek ödeme, "
                                 "ötesi üç ayda bir kupon): + ise vade eğriye göre ucuz (receive), − ise pahalı (pay). İşlem paketi: vade ve "
                                 "iki komşusu, uyumun seviye (β0) ve eğim (β1) faktörlerine nötr DV01 ağırlıklarıyla - eğri kayar ya da "
                                 "dikleşirse paket yerinde kalır, kazancı vadenin eğriye dönmesinden gelir.")
        if mon is not None:
            mons.append(mon)
            by_key[key] = mon

    def build(live: Dict[str, float]) -> Dict[str, Any]:
        s = snap(live)
        if s is None:
            return {"ok": False, "why": "OIS kotası yok", "rows": []}
        day, fit = s["day"], s["fit"]
        nss: Nss = fit["nss"]
        model = day.pars(nss)
        rows = []
        for j, key in enumerate(day.keys):
            m = by_key.get(key)
            r = s["resid"][key]
            t = day.mat[j]
            rows.append({"key": key, "label": key.split(":", 1)[1], "months": day.months[j], "t": t, "par": day.par[j] * 100.0,
                         "fit": model[j] * 100.0, "resid": r, "z": m.zof(r) if m is not None else None,
                         "half_life": m.half_life if m is not None else None, "regime": (m.regime or {}).get("tag") if m is not None else None,
                         "zero": nss.zero(t) * 100.0, "fwd": nss.forward(t) * 100.0, "n": len(resid.get(key) or []),
                         "sid": m.sid if m is not None else None, "live": key in live,
                         "hedge": (m.info.get("hedge") if m is not None else None) or []})
        grid = [0.05 * i for i in range(1, 21)] + [1.0 + 0.25 * i for i in range(1, 37)]
        return {"ok": True, "params": nss.info(day.longest), "rmse": math.sqrt(fit["sse"] / len(day)) * 1e4, "n": len(day), "rows": rows,
                "spot": day.spot.isoformat(), "days": len(days), "first": days[0] if days else None, "last": days[-1] if days else None,
                "search_ms": search_ms, "tau_day": base.day.isoformat(), "evals": found["evals"],
                "curve": {"t": grid, "zero": [nss.zero(t) * 100.0 for t in grid], "fwd": [nss.forward(t) * 100.0 for t in grid]},
                "rmse_hist": [v for _, v in rmse[-60:]],
                "conv": "≤ %dA tek ödeme, ötesi %d ayda bir kupon (ACT/365)" % (SINGLE_MONTHS, COUPON_MONTHS)}

    def zero_curve(live: Dict[str, float]) -> Optional[Nss]:
        s = snap(live)
        return s["fit"]["nss"] if s else None

    table = {"ok": True, "build": build, "nss": zero_curve}
    return mons, table


# ---------------------------------------------------------------------------------------------- the DİBS family
def _bond_of(isin: str, meta: Dict[str, Any], row: Optional[Dict[str, Any]]) -> Optional[Bond]:
    from . import bonds as bd
    kind = DIBS_KINDS.get(str((row or {}).get("type") or meta.get("type") or "").upper())
    cat = bd.by_isin(isin) or {}
    if kind is None:
        kind = {"fixed": "fixed", "bill": "bill", "zero": "bill"}.get(cat.get("kind") or "")
    mat = (row or {}).get("maturity") or meta.get("maturity") or cat.get("maturity")
    if kind is None or not mat:
        return None
    coupon = (row or {}).get("coupon")
    if coupon is None:
        coupon = cat.get("coupon")
    freq = (row or {}).get("freq") or 2
    if kind == "fixed" and not coupon:
        return None
    name = (row or {}).get("name") or meta.get("name") or cat.get("name") or isin
    return Bond(isin, name, kind, _dt.date.fromisoformat(mat), coupon or 0.0, int(freq) if freq and freq >= 1 else 2)


def _value_date(day: _dt.date, row: Optional[Dict[str, Any]]) -> _dt.date:
    """The value date of a day's price: the same day for a bond the sheet prices "ISL0", else the next week day."""
    if row is not None and str(row.get("source") or "").upper() == "ISL0":
        return day
    return next_weekday(day)


def fam_dibs(ctx: qf.Ctx, eng: Dict[str, Any], ois: Optional[Dict[str, Any]]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """The DİBS curve (``DIBS_MODEL``, fitted to the fixed-coupon bonds; the bills priced on it): today's fit, every
    bond's rich / cheap (monitored), its spread to the OIS fit, carry + roll, and the best bond to receive / pay with."""
    rows = {r["isin"]: r for r in (eng.get("dibs") or [])}
    win = ctx.window()
    bonds: Dict[str, Bond] = {}
    conv: Dict[str, str] = {}
    for key, meta in ctx.meta.items():
        if not key.startswith("DIBS:") or meta.get("unit") == "px":
            continue
        isin = key[5:].upper()
        b = _bond_of(isin, meta, rows.get(isin))
        if b is not None and b.maturity > ctx.today:
            bonds[isin] = b
    for isin, row in rows.items():
        if isin not in bonds:
            b = _bond_of(isin, {}, row)
            if b is not None and b.maturity > ctx.today:
                bonds[isin] = b
    if sum(1 for b in bonds.values() if b.kind in FIT_KINDS) < MIN_BONDS:
        return [], {"ok": False, "why": "DİBS RV listesinde en az %d sabit kuponlu kâğıt gerekli" % MIN_BONDS, "rows": []}
    for isin in bonds:
        row = rows.get(isin) or {}
        conv[isin] = detect_convention(ctx.last("DIBS:" + isin), _pct(row.get("simple")), _pct(row.get("compound")))
    t0 = time.perf_counter()
    hist = {isin: ctx.series.get("DIBS:" + isin) or {} for isin in bonds}
    days = sorted({d for s in hist.values() for d in s})[-win:]

    def day_fit(day: _dt.date, yields: Dict[str, float]) -> BondFit:
        return BondFit([(bonds[i], _value_date(day, rows.get(i)), y / 100.0, conv[i]) for i, y in yields.items()])

    good = []
    for d in days:
        n = sum(1 for i, s in hist.items() if d in s and bonds[i].kind in FIT_KINDS
                and (bonds[i].maturity - _dt.date.fromisoformat(d)).days >= MIN_DAYS)
        if n >= MIN_BONDS:
            good.append(d)
    base = None
    if good:
        d = good[-1]
        base = day_fit(_dt.date.fromisoformat(d), {i: s[d] for i, s in hist.items() if d in s})
    if base is None or base.n_fit < MIN_BONDS:
        base = day_fit(ctx.today, {i: v for i in bonds for v in [_yield_now(ctx, i, conv[i], ctx.live)] if v is not None})
    if base.n_fit < MIN_BONDS:
        return [], {"ok": False, "why": "en az %d sabit kuponlu kâğıdın getirisi gerekli" % MIN_BONDS, "rows": []}
    found = dibs_search(base)
    if found is None:
        return [], {"ok": False, "why": "%s uyumu kurulamadı" % MODEL_NAMES[DIBS_MODEL], "rows": []}
    nss0: Nss = found["nss"]
    model = nss0.model
    search_ms = (time.perf_counter() - t0) * 1000.0
    # a bond's rich / cheap: the fit's residual, (model price − market price) / (−dP/dy) - its yield − the yield of its
    # model price to first order (the second-order term is a hundredth of a bp at these sizes)
    resid: Dict[str, List[Tuple[str, float]]] = {i: [] for i in bonds}
    beta = None
    for d in good:
        fit_in = day_fit(_dt.date.fromisoformat(d), {i: s[d] for i, s in hist.items() if d in s})
        if fit_in.n_fit < MIN_BONDS:
            continue
        fit = refit(fit_in.make, nss0, beta, iters=5)
        beta = fit["nss"].beta
        for b, e in zip(fit_in.bonds, fit_in.evaluate(fit["nss"])[0]):
            resid[b.isin].append((d, e * 1e4))
    last_beta = beta or nss0.beta
    order = sorted(bonds, key=lambda i: bonds[i].maturity)

    def today(key: Tuple) -> Optional[Dict[str, Any]]:
        yields = {i: v for i, v in zip(order, key) if v is not None}
        fit_in = day_fit(ctx.today, yields)
        if fit_in.n_fit < MIN_BONDS:
            return None
        fit = refit(fit_in.make, nss0, last_beta, iters=8)
        r_all, j_all = fit_in.evaluate(fit["nss"])
        weights = {}
        for k, i in enumerate(fit_in.fitted):
            weights[fit_in.bonds[i].isin] = (fit.get("weights") or [1.0] * fit_in.n_fit)[k]
        return {"in": fit_in, "fit": fit, "jac": j_all, "weights": weights,
                "resid": {b.isin: e * 1e4 for b, e in zip(fit_in.bonds, r_all)}}

    now = _cached(today)

    def snap(live: Dict[str, float]) -> Optional[Dict[str, Any]]:
        return now(tuple(_yield_now(ctx, i, conv[i], live) for i in order))

    ref = snap(ctx.live)
    mons: List[qf.Monitor] = []
    by_isin: Dict[str, qf.Monitor] = {}
    carry_now = _bond_carry(ctx, ref, ois, rows, ctx.live) if ref is not None else {}
    usd, tl = ctx.dv01_size()
    if ref is not None:
        fit_in = ref["in"]
        keys = [b.isin for b in fit_in.bonds]
        vec = _exposures(ref["jac"], -1.0)
        # each bond's DV01 a 1 mn nominal (TL a bp): in its own yield convention (the fit's - the hedge weights are in
        # it) and as the desk has it (DİBS RV!AI: of the simple yield)
        own = list(fit_in.d)
        desk = [desk_dv01(b, fit_in.value[i], fit_in.p[i], fit_in.y[i]) or own[i] for i, b in enumerate(fit_in.bonds)]
        for j, isin in enumerate(keys):
            pts = resid.get(isin) or []
            b = bonds[isin]
            hedge = qf._hedges(keys, vec, j)
            idx = [j] + [h for h, _ in hedge]
            legs = [{"key": "DIBS:" + isin, "name": _bond_label(b), "weight": 1.0}] + [
                {"key": "DIBS:" + keys[h], "name": _bond_label(bonds[keys[h]]), "weight": w} for h, w in hedge]
            size_bond_legs(legs, [own[i] for i in idx], [desk[i] for i in idx], usd, tl)
            scale = own[j] / desk[j]                     # a bp of the residual (own convention) in bp of the desk's DV01
            cr = []
            for leg in legs:
                c = carry_now.get(leg["key"][5:]) or {}
                v = c.get("total_1w")
                cr.append(None if v is None else -leg["weight"] * v)
            carry_up = sum(cr) * scale if cr and all(v is not None for v in cr) else None
            p2 = ois_package(ctx, legs[0], fit_in.flows[j][-1][0], carry_now.get(isin), scale,
                             (rows.get(isin) or {}).get("asw")) if "dv01_usd" in legs[0] else None

            def calc(live: Dict[str, float], isin: str = isin) -> Optional[float]:
                s = snap(live)
                return s["resid"].get(isin) if s else None

            def quote(live: Dict[str, float], isin: str = isin, b: Bond = b, idx: List[int] = idx) -> Optional[Dict[str, Any]]:
                # the bond as the desk trades it: its yield now (its own convention, the fit's); at a zero gap the yield of its
                # model price on today's fit (held for the target and the stop: yield = model yield + gap - the gap is the
                # yield difference to first order, its second order a hundredth of a bp)
                s = snap(live)
                r, y = (s["resid"].get(isin) if s else None), _yield_now(ctx, isin, conv[isin], live)
                if r is None or y is None:
                    return None
                fit = y - r / 100.0
                cv = "bileşik" if conv[isin] == "compound" else "basit"
                return {"inst": _bond_label(b), "unit": "%", "digits": 2, "base": fit, "scale": 0.01,
                        "gap": {"name": "%s farkı" % model, "of": "%s uyumunun" % model, "at": "%s uyumunda" % model},
                        "model": "%s uyumunun model getirisi (%s, %%%s)" % (model, cv, qf._th(fit, 2)),
                        "note": "%s getiri; hedef / stop bugünkü %s uyumuyla" % (cv, model),
                        "held": "Hedef ve stop bugünkü %s uyumuyla (kâğıdın model getirisi %%%s, %s): eğri yeniden uyunca onlar da "
                                "değişir." % (model, qf._th(fit, 2), cv),
                        "legs": [{"key": "DIBS:" + keys[i], "name": _bond_label(bonds[keys[i]]), "level": _yield_now(ctx, keys[i], conv[keys[i]], live),
                                  "unit": "%", "digits": 2} for i in idx]}

            # the series is the bond's own distance from the fit ("NS farkı"); the hedges are its packages'
            mon = qf.mr_monitor(ctx, "dibsfv:" + isin, "dibsfv", "DİBS", "%s · %s farkı" % (_bond_label(b), model), "bp", 1,
                                [d for d, _ in pts], [v for _, v in pts], "bp", legs, calc, carry_up=carry_up, pkg="bond", quote=quote,
                                series_label="%s getirisi − %s model getirisi (bp)" % (_bond_label(b), model),
                                pnl=("bp", scale), explicit=True, packages=[p2] if p2 else [],
                                pkg_name="Paket 1 · DİBS komşularıyla hedge'li (%s seviye β0 ve eğim β1'e nötr)" % model,
                                info={"inputs": ["DIBSS:" + isin, "DIBSC:" + isin], "conv": conv[isin],
                                      "hedge": [{"key": "DIBS:" + keys[h], "weight": w} for h, w in hedge]},
                                note="Seri: getirinin DİBS " + model + " uyumundaki (" + MODEL_TEXT[nss0.k] + ", sabit kuponlulara; "
                                     "bonolar eğride fiyatlanır, uydurmaya girmez) model getirisinden farkı (bp, kâğıdın kendi getiri "
                                     "kuralıyla): + ise kâğıt eğriye göre ucuz (al), − ise pahalı (sat). Paket 1: kâğıt ve iki komşusu, "
                                     "DİBS uyumunun seviye ve eğim faktörlerine nötr DV01 ağırlıklarıyla - eğri kayar ya da dikleşirse paket "
                                     "yerinde kalır, kazancı kâğıdın eğriye dönmesinden gelir. Nominaller paket DV01'i için (ana bacak; DV01 "
                                     "DİBS RV!AI gibi: mod. süre × kirli fiyat), yuvarlanmadan - masa 5 mn TL'ye yuvarlar. Carry + roll: kupon "
                                     "tahakkuku − fonlama, artı eğride yuvarlanma.")
            if mon is not None:
                mons.append(mon)
                by_isin[isin] = mon

    sigma = {}
    for isin in bonds:
        vals = [v for _, v in sorted(hist[isin].items())][-61:]
        ch = [(b - a) * 100.0 for a, b in zip(vals, vals[1:])]
        sd = qm.stdev(ch) if len(ch) >= 20 else None
        sigma[isin] = sd * math.sqrt(21.0) if sd else None

    def build(live: Dict[str, float]) -> Dict[str, Any]:
        s = snap(live)
        if s is None:
            return {"ok": False, "why": "kâğıtların getirisi yok", "rows": []}
        fit_in, fit = s["in"], s["fit"]
        nss: Nss = fit["nss"]
        cr = _bond_carry(ctx, s, ois, rows, live)
        ois_nss = ois["nss"](live) if ois and callable(ois.get("nss")) else None
        ois_y = _ois_yields(fit_in, ois_nss)
        # "Kesit z": a row's residual over the dispersion of today's residuals of the bonds in the fit (the fixed-coupon
        # ones); the bills, priced on the curve and not fitted, are measured against it as any row
        cs = [s["resid"][fit_in.bonds[i].isin] for i in fit_in.fitted]
        cs_sd = qm.stdev(cs) if len(cs) >= 3 else None
        out_rows = []
        for i, b in enumerate(fit_in.bonds):
            isin = b.isin
            row = rows.get(isin) or {}
            m = by_isin.get(isin)
            r = s["resid"].get(isin)
            z = m.zof(r) if m is not None and r is not None else None
            c = cr.get(isin) or {}
            sg = sigma.get(isin)
            cpr = c["total_1m"] / sg if c.get("total_1m") is not None and sg else None
            years = (b.maturity - ctx.today).days / YEAR
            out_rows.append({"isin": isin, "name": b.name, "label": _bond_label(b), "kind": b.kind, "maturity": b.maturity.isoformat(),
                             "years": years, "coupon": b.coupon if b.kind == "fixed" else None, "conv": fit_in.conv[i],
                             "yield": fit_in.y[i] * 100.0, "model": fit_in.y[i] * 100.0 - r / 100.0 if r is not None else None, "resid": r,
                             "weight": s["weights"].get(isin), "fitted": isin in s["weights"],
                             "z": z, "cs_z": r / cs_sd if r is not None and cs_sd else None,
                             "half_life": m.half_life if m is not None else None,
                             "regime": (m.regime or {}).get("tag") if m is not None else None, "sid": m.sid if m is not None else None,
                             "n": len(resid.get(isin) or []), "live": ("DIBSS:" + isin) in live or ("DIBSC:" + isin) in live,
                             "ois_yield": ois_y[i] * 100.0 if ois_y[i] is not None else None,
                             "ois_spread": (fit_in.y[i] - ois_y[i]) * 1e4 if ois_y[i] is not None else None,
                             "wb_asw": row.get("asw"), "wb_rc": row.get("wb_rc"), "mod_dur": row.get("mod_dur"),
                             "dv01": row.get("dv01"), "sigma_1m": sg, "cpr": cpr, "score": z * cpr if z is not None and cpr is not None else None,
                             **{k: c.get(k) for k in ("carry_1w", "roll_1w", "total_1w", "carry_1m", "roll_1m", "total_1m", "funding")}})
        ranked = [r for r in out_rows if r["score"] is not None]
        receive = sorted((r for r in ranked if r["z"] > 0), key=lambda r: -r["score"])
        pay = sorted((r for r in ranked if r["z"] < 0), key=lambda r: -r["score"])
        pick = ("isin", "label", "maturity", "resid", "z", "total_1m", "sigma_1m", "cpr", "score", "sid")
        longest = max(fl[-1][0] for fl in fit_in.flows)
        grid = [0.1 * i for i in range(1, int(longest * 10) + 2)]
        return {"ok": True, "params": nss.info(fit_in.longest), "rmse": math.sqrt(fit["sse"] / fit_in.n_fit) * 1e4, "n": len(fit_in), "n_fit": fit_in.n_fit,
                "n_bills": fit_in.n_bills, "loo": loo_rmse(fit_in, nss),
                "model": nss.model, "rows": out_rows,
                "receive": [{k: r[k] for k in pick} for r in receive[:6]], "pay": [{k: r[k] for k in pick} for r in pay[:6]],
                "days": len(good), "first": good[0] if good else None, "last": good[-1] if good else None, "search_ms": search_ms,
                "evals": found["evals"], "curve": {"t": grid, "zero": [nss.zero(t) * 100.0 for t in grid]},
                "ois": ois_nss is not None, "funding": _funding_text(ctx, live, ois_nss)}

    def leg(isin: str, live: Dict[str, float], spreads: Dict[str, float], s: Dict[str, Any]) -> Dict[str, Any]:
        """One bond on the fair curve now: its quote, its market yield and distance from fair, z, carry + roll."""
        isin = isin.strip().upper()
        b = bonds.get(isin) or _bond_of(isin, {}, None)
        if b is None or b.kind != "fixed":
            return {"ok": False, "isin": isin, "why": "sabit kuponlu bir DİBS bulunamadı: %s" % (isin or "—")}
        if (b.maturity - ctx.today).days < MIN_DAYS:
            return {"ok": False, "isin": isin, "why": "vadesine %d günden az kaldı" % MIN_DAYS}
        nss: Nss = s["fit"]["nss"]
        value = _value_date(ctx.today, rows.get(isin))
        years = (b.maturity - ctx.today).days / YEAR
        bucket, half = spread_for(years, spreads)
        out = dict(quote_bond(b, value, nss, half), ok=True, isin=isin, label=_bond_label(b), name=b.name, maturity=b.maturity.isoformat(),
                   coupon=b.coupon, years=years, bucket=bucket, listed=isin in bonds, model=nss.model)
        y_now = _yield_now(ctx, isin, conv.get(isin, "simple"), live) if isin in bonds else None
        if y_now is not None:
            y = to_simple(b, y_now / 100.0, conv.get(isin, "simple"))
            p, dp = b.price(y, value, "simple")
            out["market"] = {"yield": y * 100.0, "dirty": p, "clean": p - out["accrued"], "dv01": -dp,
                             "live": ("DIBSS:" + isin) in live or ("DIBSC:" + isin) in live}
            out["distance"] = (y * 100.0 - out["fair"]["yield"]) * 100.0
            m = by_isin.get(isin)
            r = s["resid"].get(isin)
            out["z"] = m.zof(r) if m is not None and r is not None else None
            out["sid"] = m.sid if m is not None else None
        c = _bond_carry(ctx, s, ois, rows, live).get(isin) or {}
        out.update({k: c.get(k) for k in ("carry_1w", "roll_1w", "total_1w", "carry_1m", "roll_1m", "total_1m")})
        return out

    def quote(isin: str, live: Dict[str, float], spreads: Dict[str, float]) -> Dict[str, Any]:
        s = snap(live)
        if s is None:
            return {"ok": False, "why": "kâğıtların getirisi yok"}
        out = leg(isin, live, spreads, s)
        if out.get("ok"):
            f, bid, ask = out["fair"], out["bid"], out["ask"]
            out["line"] = ("DİBS %s (%s) · getiri %s / %s · temiz %s / %s · adil %s · valör %s"
                           % (out["label"], out["isin"], _tr(bid["yield"], 2), _tr(ask["yield"], 2), _tr(bid["clean"], 3), _tr(ask["clean"], 3),
                              _tr(f["yield"], 2), _tr_day(out["value_date"])))
        out["spreads"] = spreads
        return out

    def switch(a: str, b: str, live: Dict[str, float], spreads: Dict[str, float]) -> Dict[str, Any]:
        """Sell A, buy B: the DV01-neutral nominal of B for 1 mn A, the pickup against the fair curve (B's rich / cheap −
        A's), the carry + roll difference, the switch level and its z over the history, a line to read."""
        s = snap(live)
        if s is None:
            return {"ok": False, "why": "kâğıtların getirisi yok"}
        la, lb = leg(a, live, spreads, s), leg(b, live, spreads, s)
        out: Dict[str, Any] = {"a": la, "b": lb, "ok": bool(la.get("ok") and lb.get("ok"))}
        if not out["ok"]:
            out["why"] = la.get("why") or lb.get("why")
            return out
        if la["isin"] == lb["isin"]:
            return dict(out, ok=False, why="A ile B aynı kâğıt")
        dv_a = (la.get("market") or la["fair"])["dv01"]
        dv_b = (lb.get("market") or lb["fair"])["dv01"]
        ratio = dv_a / dv_b                                  # mn of B for 1 mn of A: the same DV01
        out["ratio"] = ratio
        out["dv01_mn"] = dv_a                                # TL per bp, per 1 mn A (and the B against it)
        if la.get("distance") is not None and lb.get("distance") is not None:
            out["pickup"] = lb["distance"] - la["distance"]
            out["level"] = (lb["market"]["yield"] - la["market"]["yield"]) * 100.0
        for k in ("total_1w", "total_1m"):
            if la.get(k) is not None and lb.get(k) is not None:
                out["cr_" + k[6:]] = lb[k] - la[k]
        # the switch on the fair curve over the window: B's rich / cheap − A's, day by day
        ha, hb = dict(resid.get(la["isin"]) or []), dict(resid.get(lb["isin"]) or [])
        days = sorted(set(ha) & set(hb))[-win:]
        if len(days) >= 20 and out.get("pickup") is not None:
            series = [hb[d] - ha[d] for d in days]
            mean, sd = qf.window_stats(series)
            now = s["resid"].get(lb["isin"], 0.0) - s["resid"].get(la["isin"], 0.0)
            ou = qf.ou_of(series)
            out.update({"z": (now - mean) / sd if sd else None, "mean": mean, "n": len(days), "half_life": ou["half_life"] if ou else None})
        out["line"] = _switch_text(out)
        return out

    def carry(live: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
        """Each bond's carry + roll now (bp of its yield convention) - the universe's DİBS lines (quantuniv.py)."""
        return _bond_carry(ctx, snap(live), ois, rows, live)

    # ("resid": each bond's distance from the fit day by day, bp - Carry + momentum's cheapness at its past rebalances,
    # quantsira.py; the published table is ``build``'s, without it)
    return mons, {"ok": True, "build": build, "quote": quote, "switch": switch, "carry": carry, "resid": resid}


def _tr(v: Optional[float], d: int) -> str:
    return ("%.*f" % (d, v)).replace(".", ",") if v is not None else "—"


def _tr_day(iso: str) -> str:
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[0:4])


def _switch_text(sw: Dict[str, Any]) -> str:
    """The switch in a line, in Turkish, for the desk and for a chat."""
    a, b = sw["a"], sw["b"]
    head = "Switch: %s sat / %s al · 1mn %s'e %s mn %s (DV01 nötr, %s TL/bp)" % (a["label"], b["label"], a["label"], _tr(sw["ratio"], 2), b["label"],
                                                                         _tr(sw["dv01_mn"], 0))
    parts = [head]
    pickup = sw.get("pickup")
    if pickup is not None:
        side = "daha ucuz (lehte)" if pickup > 0 else "daha pahalı (aleyhte)"
        parts.append("%s adil eğriye göre %s'den %s bp %s" % (b["label"], a["label"], _tr(abs(pickup), 1), side)
                     + (" · z %s" % ("%+.2f" % sw["z"]).replace(".", ",") if sw.get("z") is not None else ""))
    if sw.get("cr_1m") is not None:
        parts.append("carry + roll ayda %s bp, haftada %s bp" % (("%+.1f" % sw["cr_1m"]).replace(".", ","),
                                                                ("%+.1f" % sw.get("cr_1w", 0.0)).replace(".", ",")))
    return " · ".join(parts)


def _pct(v: Optional[float]) -> Optional[float]:
    return v * 100.0 if v is not None else None


def _bond_label(b: Bond) -> str:
    from . import bonds as bd
    try:
        return bd.short_label({"isin": b.isin, "kind": "bill" if b.kind == "bill" else "fixed", "maturity": b.maturity.isoformat(),
                               "coupon": b.coupon or None, "name": b.name})
    except Exception:  # noqa: BLE001 - a label is a label
        return b.isin


def _yield_now(ctx: qf.Ctx, isin: str, conv: str, live: Dict[str, float]) -> Optional[float]:
    """A bond's yield now (per cent) in the convention its history is read in: the sheet's live yield, else the last
    close."""
    v = live.get(("DIBSC:" if conv == "compound" else "DIBSS:") + isin)
    return v if v is not None else ctx.last("DIBS:" + isin)


def _funder(ctx: qf.Ctx, live: Dict[str, float], ois_nss: Optional[Nss], repo: Optional[float]) -> Tuple[Callable[[float], float], str]:
    """The funding growth over t years: the row's repo (simple), else the OIS fit's rate to the horizon, else TLREF
    compounded daily."""
    if repo is not None:
        r = repo / 100.0
        return (lambda t: 1.0 + r * t), "repo"
    if ois_nss is not None:
        return (lambda t: 1.0 / ois_nss.df(t)), "OIS"
    tl = ctx.cur("TLREF", live)
    r = (tl or 0.0) / 100.0
    return (lambda t: (1.0 + r / YEAR) ** (t * YEAR)), "TLREF"


def _funding_text(ctx: qf.Ctx, live: Dict[str, float], ois_nss: Optional[Nss]) -> Dict[str, Any]:
    if ois_nss is not None:
        return {"source": "OIS", "rate_1m": ois_nss.zero(30 / YEAR) * 100.0}
    return {"source": "TLREF", "rate_1m": ctx.cur("TLREF", live)}


def _bond_carry(ctx: qf.Ctx, snap: Optional[Dict[str, Any]], ois: Optional[Dict[str, Any]], rows: Dict[str, Dict[str, Any]],
                live: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
    """Carry + roll of every bond of a fit over the horizons (bp)."""
    out: Dict[str, Dict[str, Any]] = {}
    if snap is None:
        return out
    fit_in, nss = snap["in"], snap["fit"]["nss"]
    ois_nss = ois["nss"](live) if ois and callable(ois.get("nss")) else None
    spreads = fit_in.spreads(nss)
    for i, b in enumerate(fit_in.bonds):
        if spreads[i] is None:
            continue
        repo = (rows.get(b.isin) or {}).get("repo")
        fund, src = _funder(ctx, live, ois_nss, repo)
        c: Dict[str, Any] = {"funding": src}
        for name, days in HORIZONS:
            res = carry_roll(b, fit_in.value[i], fit_in.y[i], fit_in.conv[i], nss, spreads[i], days, fund)
            if res is not None:
                c["carry_" + name] = res["carry_bp"]
                c["roll_" + name] = res["roll_bp"]
                c["total_" + name] = res["carry_bp"] + res["roll_bp"]
        out[b.isin] = c
    return out


def _ois_yields(fit_in: BondFit, ois_nss: Optional[Nss]) -> List[Optional[float]]:
    """The yield (each bond's convention) of each bond's cash flows priced on the OIS fit."""
    if ois_nss is None:
        return [None] * len(fit_in)
    return [b.yield_of(p, v, c, y) for b, p, v, c, y in zip(fit_in.bonds, fit_in.model_prices(ois_nss), fit_in.value, fit_in.conv, fit_in.y)]


# ---------------------------------------------------------------------------------------------- the packages' sizes
def desk_dv01(bond: Bond, value: _dt.date, price: float, guess: Optional[float] = None) -> Optional[float]:
    """A bond's DV01 as the desk has it - DİBS RV!AI (ED): modified duration × dirty price, of the simple yield -, TL a
    bp for 1 mn nominal: −dP/dy (per 100) of the simple yield of its dirty price."""
    ys = bond.yield_of(price, value, "simple", guess)
    if ys is None:
        return None
    _, dp = bond.price(ys, value, "simple")
    return -dp if dp < 0 else None


def size_bond_legs(legs: List[Dict[str, Any]], own: Sequence[float], desk: Sequence[Optional[float]], usd: float,
                   tl: Optional[float]) -> None:
    """Bond legs sized for the package's main-leg DV01 (``usd`` / ``tl`` a bp).  ``weight``: each leg's DV01 weight in
    the bonds' own yield convention (the fit's); ``own`` / ``desk``: each bond's DV01 a 1 mn nominal in that convention
    and in the desk's (DİBS RV!AI).  The first leg is the main one - its desk DV01 the package's; each leg gets its
    desk DV01 (USD and TRY a bp, signed as the weight), the nominal (mn TRY) and ``dv01_mn``."""
    if not usd or not desk[0]:
        return
    for leg, o, d in zip(legs, own, desk):
        if not d or not o:
            continue
        w = leg["weight"] * (d / o) / (desk[0] / own[0])            # own-convention DV01 → the desk's, the main leg's 1
        leg["dv01_mn"] = d
        leg["dv01_usd"] = w * usd
        leg["dv01"] = w * tl if tl else None
        leg["notional"] = abs(w) * tl / d if tl else None             # mn: TL a bp ÷ TL a bp a 1 mn


def ois_hedge(years: float, tenors: Sequence[Tuple[str, float]]) -> Optional[Dict[str, Any]]:
    """The OIS side of a bond's asset swap, for a unit of its desk DV01 going up (its yield rising: the bond sold) - as
    DİBS RV hedges a bond (AJ, "OIS hedge oranı": an OIS to the bond's maturity with its DV01) - in the quoted tenors
    (``tenors``: ``(key, years)``, shortest first): the two around the bond's maturity share the OIS DV01, linearly by
    where the maturity falls between them (a broken date between two quotes); the total the bond's (the desk's 1:1).
    Beyond the ends of the curve, the end tenor alone.  ``{"legs": [(key, weight)], "years"}``."""
    if not tenors:
        return None
    keys = [k for k, _ in tenors]
    mats = [t for _, t in tenors]
    if years <= mats[0]:
        return {"legs": [(keys[0], -1.0)], "years": years}
    if years >= mats[-1]:
        return {"legs": [(keys[-1], -1.0)], "years": years}
    for i in range(len(keys) - 1):
        a, c = mats[i], mats[i + 1]
        if a <= years <= c and c > a:
            u_c = (years - a) / (c - a)
            legs = [(k, -u) for k, u in ((keys[i], 1.0 - u_c), (keys[i + 1], u_c)) if u > 1e-9]
            return {"legs": legs, "years": years}
    return None


def ois_package(ctx: qf.Ctx, main: Dict[str, Any], years: float, carry: Optional[Dict[str, Any]], scale: float,
                asw: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Package 2 of a bond's signal: the bond (its leg as in package 1) against TRY OIS around its maturity
    (:func:`ois_hedge`, the quoted tenors with a quote now), its carry + roll a week in P&L units (bp of the bond's
    desk DV01; the package going up - the bond sold) when every leg's is known: the bond's own (``carry``, its
    convention's bp, × ``scale``) and each tenor's of the carry engine."""
    tenors = [(k, ctx.meta[k]["months"] / 12.0) for k in _ois_keys(ctx) if ctx.cur(k) is not None]
    h = ois_hedge(years, tenors)
    if h is None:
        return None
    legs = [dict(main)] + [{"key": k, "name": qf._ois_name(ctx, k), "weight": u} for k, u in h["legs"]]
    carry_up = None
    v = (carry or {}).get("total_1w")
    cw = [ctx.carry_week(k) for k, _ in h["legs"]]
    if v is not None and all(c is not None for c in cw):
        carry_up = -v * scale + sum(u * c for (_, u), c in zip(h["legs"], cw))
    where = (" ve ".join("%s %%%d" % (qf._ois_name(ctx, k), round(abs(u) * 100)) for k, u in h["legs"]) if len(h["legs"]) > 1
             else "%s tek başına (vade eğrinin ucunun ötesinde)" % qf._ois_name(ctx, h["legs"][0][0]))
    note = ("Paket 2: kâğıt TRY OIS'le - DİBS RV'nin kendi OIS hedge'i gibi (AJ: kâğıdın vadesine kadar bir OIS, aynı DV01), kote "
            "vadelerle: vadesi %s yıl, OIS DV01'i %s (vadeye göre doğrusal); toplam OIS DV01'i kâğıdınkine eşit. Kâğıdı satana OIS "
            "receive, alana pay. Bu paketin K/Z'si kâğıdın OIS'e göre farkıyla (asset swap%s) gider: %s farkının yanında bütün "
            "eğrinin DİBS − OIS farkını da taşır, Paket 1 taşımaz. Sinyalin z'si ve beklenen hareketi %s farkınındır. OIS "
            "nominalleri DV01 ÷ (annuity × 1e-4), annuity Motor'unki (Günlük İşlemler'in OIS girişi gibi)."
            % (("%.1f" % years).replace(".", ","), where, ", DİBS RV ASW %s bp" % ("%.0f" % asw) if asw is not None else "",
               MODEL_NAMES[DIBS_MODEL], MODEL_NAMES[DIBS_MODEL]))
    return {"name": "Paket 2 · kâğıt + OIS, OIS'le hedge'li (asset swap: vadesine eş OIS, DV01 1:1)", "legs": legs, "carry_up": carry_up,
            "note": note}


# ---------------------------------------------------------------------------------------------- quotes from the fair curve
#: the desk's half bid / ask spreads of a quote from the fair curve (bp of yield), by the bond's years to maturity:
#: short up to ``short_until``, long from ``long_from``, mid between
QUOTE_KEY = "quant.quote"
QUOTE_DEFAULTS: Dict[str, float] = {"short_until": 2.0, "long_from": 5.0, "short": 10.0, "mid": 15.0, "long": 20.0}
QUOTE_LIMITS = {"short_until": (0.1, 30.0), "long_from": (0.1, 30.0), "short": (0.0, 500.0), "mid": (0.0, 500.0), "long": (0.0, 500.0)}
#: what ``quant.Quant.view`` / ``action`` hand to this module
QUERIES = ("quote", "switch", "quote_spreads")
ACTIONS = ("quote_spreads",)


def accrued(bond: Bond, value: _dt.date) -> float:
    """Accrued interest per 100 at the value date, as the sheet has it (DİBS RV!Q: c/f × days since the last coupon /
    the period's days); none on a bill."""
    if bond.kind == "bill":
        return 0.0
    flows, frac = bond.flows(value)
    return bond.coupon / bond.freq * (1.0 - frac) if flows else 0.0


def to_simple(bond: Bond, y: float, conv: str) -> float:
    """A yield (decimal) of ``conv`` as the bond's simple one (compounded ``freq`` times a year; a bill's simple)."""
    if conv != "compound":
        return y
    if bond.kind == "bill":
        return y                                          # (a bill's compound yield is read as it is: see ``price``)
    return bond.freq * ((1.0 + y) ** (1.0 / bond.freq) - 1.0)


def quote_bond(bond: Bond, value: _dt.date, nss: Nss, half_bp: float) -> Dict[str, Any]:
    """A two-way quote from the fair curve: the fair yield (the yield of Σ CF·DF on the curve), bid = fair + half,
    ask = fair − half (bp of the simple yield) - each with its compound yield and dirty / clean price - and the DV01
    (TL per 1 mn nominal, per bp: the sheet's AI)."""
    flows, _ = bond.flows(value)
    dirty = sum(cf * nss.df((d - value).days / YEAR) for d, cf in flows)
    y = bond.yield_of(dirty, value, "simple", nss.zero(max((bond.maturity - value).days / YEAR, 0.01)))
    acc = accrued(bond, value)

    def at(yy: float) -> Dict[str, float]:
        p, dp = bond.price(yy, value, "simple")
        comp = (1.0 + yy * (bond.maturity - value).days / YEAR) ** (YEAR / max(1, (bond.maturity - value).days)) - 1.0 \
            if bond.kind == "bill" else (1.0 + yy / bond.freq) ** bond.freq - 1.0
        return {"yield": yy * 100.0, "compound": comp * 100.0, "dirty": p, "clean": p - acc, "dv01": -dp}

    h = half_bp / 1e4
    return {"value_date": value.isoformat(), "accrued": acc, "half_bp": half_bp, "fair": at(y), "bid": at(y + h), "ask": at(y - h)}


def spread_for(years: float, spreads: Dict[str, float]) -> Tuple[str, float]:
    """The bucket of a bond's years to maturity and its half spread (bp)."""
    if years <= spreads["short_until"]:
        return "kısa", spreads["short"]
    if years >= spreads["long_from"]:
        return "uzun", spreads["long"]
    return "orta", spreads["mid"]


def quote_spreads(store: Any) -> Dict[str, Any]:
    out = dict(QUOTE_DEFAULTS)
    saved = store.get(QUOTE_KEY) if store is not None else None
    if isinstance(saved, dict):
        out.update({k: float(v) for k, v in saved.items() if k in QUOTE_DEFAULTS and isinstance(v, (int, float))})
        out.update({k: saved[k] for k in ("by", "at") if k in saved})
    return out


def set_quote_spreads(store: Any, user: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """The desk's half spreads (for everyone; who changed them is kept)."""
    if not isinstance(values, dict):
        raise ValueError("ayarlar anlaşılamadı")
    cur = quote_spreads(store)
    for name, raw in values.items():
        if name not in QUOTE_LIMITS:
            continue
        try:
            v = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError("%s bir sayı olmalı" % name)
        lo, hi = QUOTE_LIMITS[name]
        if not (math.isfinite(v) and lo <= v <= hi):
            raise ValueError("%s %g – %g arasında olmalı" % (name, lo, hi))
        cur[name] = v
    if not cur["short_until"] < cur["long_from"]:
        raise ValueError("kısa vadenin sınırı uzun vadeninkinden küçük olmalı")
    cur["by"], cur["at"] = user, _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
    store.put(QUOTE_KEY, {k: cur[k] for k in list(QUOTE_DEFAULTS) + ["by", "at"]})
    return quote_spreads(store)


def query(what: str, q: Dict[str, Any], store: Any, fit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``quant.Quant.view`` of this module's own requests: ``quote`` (``isin``), ``switch`` (``a``, ``b``) and
    ``quote_spreads`` - on the latest fit, with the values the worker read last."""
    spreads = quote_spreads(store)
    if what == "quote_spreads":
        return {"values": spreads, "defaults": QUOTE_DEFAULTS, "limits": QUOTE_LIMITS}
    tab = ((fit or {}).get("tables") or {}).get("dibsfv") or {}
    if not callable(tab.get(what)):
        return {"ok": False, "why": tab.get("why") or "DİBS uyumu henüz yok", "spreads": spreads}
    ctx = fit["ctx"]
    live = ctx.derive_live(ctx.live)
    if what == "quote":
        return tab["quote"](str(q.get("isin") or ""), live, spreads)
    return tab["switch"](str(q.get("a") or ""), str(q.get("b") or ""), live, spreads)


def act(what: str, user: str, data: Dict[str, Any], store: Any) -> Dict[str, Any]:
    """``quant.Quant.action`` of this module: saving the desk's half spreads."""
    values = data.get("values") if isinstance(data.get("values"), dict) else data
    return set_quote_spreads(store, user, values)


# ---------------------------------------------------------------------------------------------- run, live tables
def run(ctx: qf.Ctx, eng: Dict[str, Any], mons: List[qf.Monitor], tables: Dict[str, Any], timing: Dict[str, float],
        pause: Optional[Callable[[], None]] = None) -> None:
    """``quant.Quant.compute``: the two families after quantfam's - their monitors join ``mons``, their tables
    ``tables`` (an error in one is that family's, as in ``quantfam.run_all``)."""
    run_step("curve", lambda: fam_curve(ctx), mons, tables, timing, pause, ctx)
    run_step("dibsfv", lambda: fam_dibs(ctx, eng, tables.get("curve")), mons, tables, timing, pause, ctx)


def run_step(name: str, fn: Callable[[], Tuple[List[qf.Monitor], Dict[str, Any]]], mons: List[qf.Monitor], tables: Dict[str, Any],
             timing: Dict[str, float], pause: Optional[Callable[[], None]], ctx: qf.Ctx) -> None:
    """One family of the modules beside quantfam (this one and ``quantopt``): as ``quantfam.run_all``'s steps - its
    monitors, its table, its rows of the regime table, its time; an exception is that family's error."""
    t0 = time.perf_counter()
    errors = tables.setdefault("errors", {})
    try:
        m, t = fn()
        mons.extend(m)
        tables[name] = t
        tables["regime"] = list(tables.get("regime") or []) + qf.regime_table(ctx, m)
    except Exception as exc:  # noqa: BLE001 - one family failing must not take the others with it
        errors[name] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        tables[name] = {"ok": False, "why": errors[name], "rows": []}
    timing[name] = time.perf_counter() - t0
    if pause is not None:
        pause()


def live_tables(t: Dict[str, Any], ctx: qf.Ctx) -> None:
    """``quant.Quant._tables``: this page's tables with the values now (the fit's own functions, the τ held)."""
    build_tables(t, ctx, TABLES)


def build_tables(t: Dict[str, Any], ctx: qf.Ctx, names: Sequence[str]) -> None:
    """Each named table that a family left as ``{"build": fn}`` replaced by ``fn(the values now)``."""
    live = ctx.derive_live(ctx.live)
    for name in names:
        tab = t.get(name)
        if isinstance(tab, dict) and callable(tab.get("build")):
            try:
                t[name] = tab["build"](live)
            except Exception as exc:  # noqa: BLE001 - a table that cannot be built now says why
                t[name] = {"ok": False, "why": "%s: %s" % (type(exc).__name__, str(exc)[:160]), "rows": []}
