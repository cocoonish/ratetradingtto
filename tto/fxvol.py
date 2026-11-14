"""FX option smiles, and what they say about where a currency pair will be.

The market quotes a pair's volatility by tenor as five numbers: the at-the-money vol, the 25- and 10-delta risk
reversals (call vol − put vol) and the 25- and 10-delta butterflies.  Bloomberg's tickers say so plainly:
``USDTRYV1M`` (ATM), ``USDTRY25R1M`` / ``USDTRY10R1M`` (risk reversals), ``USDTRY25B1M`` / ``USDTRY10B1M``
(butterflies), in vol points.  What the numbers mean depends on the pair's conventions:

* **delta** - the forward delta ``N(d1)`` or, when the premium is paid in the base currency (USDJPY, USDTRY, the
  crosses), the *premium-adjusted* delta ``(K/F)·N(d2)``; a spot delta is the forward delta times the base
  currency's discount factor (G10 up to a year; USDTRY and its crosses use forward deltas at every tenor);
* **at the money** - the delta-neutral straddle: ``K = F·exp(+σ²T/2)``, premium-adjusted ``F·exp(−σ²T/2)``;
* **risk reversal** - the vol of the 25-delta call minus that of the 25-delta put, each at the strike the smile
  itself gives that delta (the "smile" deltas);
* **butterfly** - the *market* (broker) strangle: a 25-delta call and put priced at the one vol ATM + BF, the
  strikes taken at that vol.  The smile must price that strangle the same; the vol of the smile's own 25-delta
  wings is not ATM + BF (for a pair as skewed as USDTRY the two differ by much more than a rounding).

Three ways to draw the smile through the quotes (:func:`build_smile`):

``svi`` (the default)
    Gatheral's raw SVI - total variance ``w(k) = a + b·(ρ(k − m) + √((k − m)² + s²))`` of log-moneyness
    ``k = ln(K/F)`` - fitted to all five quotes by least squares in vol points (ATM weighted most, the 10-delta
    wings least), with Gatheral's no-butterfly condition ``g(k) ≥ 0`` and Lee's wing bound as penalties: the smile
    that comes out never has a negative density, and its wings grow at most linearly in variance.  G10 smiles it
    fits to the quote; USDTRY's mid quotes are not always free of arbitrage among themselves, and then the closest
    arbitrage-free smile is taken (the residuals say how far, typically well inside the bid / ask).
``sabr``
    Hagan's SABR with β = 1: the ATM vol held exactly, ρ and ν fitted to the other four quotes.  Smooth and
    parsimonious; it cannot follow a smile as skewed as USDTRY's (the residuals say how far off, and the density
    check whether the distribution is still one).
``vv``
    Vanna-Volga (Castagna-Mercurio) through 25P / ATM / 25C, the 25-delta strangle repriced; the 10-delta quotes are
    not used (their residuals tell how well the 25-delta smile extends).

Why not the exact five-pillar construction (pillar vols solved from the quotes, a spline between them): it reprices
G10 quotes exactly, but for USDTRY's mid quotes the market strangles may have no solution at all and the spline
then shows a negative density - a probability table cannot be built on that.

**The distribution.**  Prices are undiscounted (forward measure), so what follows is the risk-neutral law of the
spot at expiry.  ``P(S_T > K) = −∂C/∂K = N(d2) − F·n(d1)·√T·σ'(K)`` (Breeden-Litzenberger, first derivative only:
no numerical second difference).  Its mean is the forward by construction; :func:`check` measures that, the mass
and whether the density stays positive (a smile that does not is an arbitrage, and is flagged).

Everything here is plain Python (no numpy): the dashboard runs without installing anything.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)
#: the quantiles of the cloud (the fan chart)
QUANTILES = (0.01, 0.05, 0.10, 0.16, 0.25, 0.50, 0.75, 0.84, 0.90, 0.95, 0.99)
MODELS = ("svi", "sabr", "vv")
#: the pillars of a smile: name, delta, call
PILLARS = (("10P", 0.10, False), ("25P", 0.25, False), ("ATM", 0.5, None), ("25C", 0.25, True), ("10C", 0.10, True))


class SmileError(ValueError):
    """The quotes cannot make a smile (a vol at or below zero, strikes out of order, a calibration that fails)."""


#: what a smile far outside its range may raise (a logarithm of a negative number, an overflow)
MATH_ERRORS = (SmileError, ValueError, OverflowError, ZeroDivisionError)


# ---------------------------------------------------------------------------------------------- the normal law
def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / SQRT2)


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
      -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
      -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
      4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)


def ninv(p: float) -> float:
    """The inverse of the normal distribution (Acklam's approximation and one Halley step: ~1e-15)."""
    if not 0.0 < p < 1.0:
        raise ValueError("probability out of (0, 1): %r" % p)
    if p < 0.02425:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    elif p <= 1.0 - 0.02425:
        q = p - 0.5
        r = q * q
        x = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
            (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    e = ncdf(x) - p
    u = e * SQRT2PI * math.exp(0.5 * x * x)
    return x - u / (1.0 + 0.5 * x * u)


# ---------------------------------------------------------------------------------------------- root finding
def brent(f: Callable[[float], float], a: float, b: float, fa: Optional[float] = None, fb: Optional[float] = None,
          xtol: float = 1e-13, maxiter: int = 200) -> float:
    """A root of ``f`` between ``a`` and ``b`` (``f(a)`` and ``f(b)`` of opposite sign): Brent's method."""
    fa = f(a) if fa is None else fa
    fb = f(b) if fb is None else fb
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    if (fa > 0) == (fb > 0):
        raise SmileError("no sign change between %r and %r" % (a, b))
    c, fc = a, fa
    d = e = b - a
    for _ in range(maxiter):
        if (fb > 0) == (fc > 0):
            c, fc = a, fa
            d = e = b - a
        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        tol = 2.0 * 2.2e-16 * abs(b) + 0.5 * xtol
        m = 0.5 * (c - b)
        if abs(m) <= tol or fb == 0.0:
            return b
        if abs(e) >= tol and abs(fa) > abs(fb):
            s = fb / fa
            if a == c:
                p, q = 2.0 * m * s, 1.0 - s
            else:
                q, r = fa / fc, fb / fc
                p = s * (2.0 * m * q * (q - r) - (b - a) * (r - 1.0))
                q = (q - 1.0) * (r - 1.0) * (s - 1.0)
            if p > 0:
                q = -q
            p = abs(p)
            if 2.0 * p < min(3.0 * m * q - abs(tol * q), abs(e * q)):
                e, d = d, p / q
            else:
                d = e = m
        else:
            d = e = m
        a, fa = b, fb
        b = b + (d if abs(d) > tol else (tol if m > 0 else -tol))
        fb = f(b)
    return b


def _bracket(f: Callable[[float], float], x0: float, step: float, sign: float, limit: int = 60) -> Tuple[float, float]:
    """From ``x0`` (where ``f`` has the sign ``sign``) walk by ``step`` until the sign changes: (x, f(x))."""
    x = x0
    for _ in range(limit):
        x += step
        fx = f(x)
        if (fx > 0) != (sign > 0):
            return x, fx
        step *= 1.6
    raise SmileError("no bracket")


# ---------------------------------------------------------------------------------------------- Black and deltas
def black(F: float, K: float, vol: float, T: float, call: bool = True) -> float:
    """Undiscounted Black price (the forward measure)."""
    if T <= 0.0 or vol <= 0.0:
        return max(F - K, 0.0) if call else max(K - F, 0.0)
    sd = vol * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if call:
        return F * ncdf(d1) - K * ncdf(d2)
    return K * ncdf(-d2) - F * ncdf(-d1)


def vega(F: float, K: float, vol: float, T: float) -> float:
    """dPrice / dvol, undiscounted."""
    sd = vol * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    return F * npdf(d1) * math.sqrt(T)


def delta(F: float, K: float, vol: float, T: float, call: bool, premium: bool, df: float = 1.0) -> float:
    """The delta the market quotes: forward ``N(d1)`` or premium-adjusted ``(K/F)·N(d2)``, puts negative; times
    the base currency's discount factor ``df`` for a spot delta (1 for a forward delta)."""
    sd = vol * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    if premium:
        d2 = d1 - sd
        v = (K / F) * ncdf(d2) if call else -(K / F) * ncdf(-d2)
    else:
        v = ncdf(d1) if call else -ncdf(-d1)
    return v * df


def atm_strike(F: float, vol: float, T: float, premium: bool) -> float:
    """Delta-neutral straddle strike."""
    return F * math.exp((-0.5 if premium else 0.5) * vol * vol * T)


def strike_at(F: float, T: float, dl: float, call: bool, vol: Callable[[float], float], premium: bool, df: float = 1.0,
              flat: Optional[float] = None) -> float:
    """The strike whose delta is ``dl`` (positive, 0 < dl < 0.5) for a call or a put, the vol being the smile's own
    at that strike (``flat``: one vol for every strike - the market strangle's).

    The premium-adjusted call delta is not monotone in the strike (deep in the money it falls again); the quoted
    deltas lie on its falling branch, right of the delta-neutral strike, where the search is kept."""
    target = dl / df
    if flat is not None:
        sd = flat * math.sqrt(T)
        if not premium:                                            # closed form
            d1 = ninv(target) if call else -ninv(target)
            return F * math.exp(-d1 * sd + 0.5 * sd * sd)
        vol = lambda K, _v=flat: _v                                 # noqa: E731
    v0 = vol(F)
    if not (v0 > 0.0):
        raise SmileError("vol not positive")
    k_atm = math.log(atm_strike(F, v0, T, premium))
    sd0 = v0 * math.sqrt(T)

    def g(x: float) -> float:
        K = math.exp(x)
        s = vol(K)
        if not (s > 0.0):
            raise SmileError("vol not positive at %g" % K)
        return abs(delta(F, K, s, T, call, premium)) - target

    ga = g(k_atm)
    if call:
        if ga < 0:                                                  # walk left to where the delta is above the target
            a, fa = _bracket(g, k_atm, -0.5 * sd0, -1.0)
            return math.exp(brent(g, a, k_atm, fa, ga))
        b, fb = _bracket(g, k_atm, 0.5 * sd0 + 1e-6, 1.0)
        return math.exp(brent(g, k_atm, b, ga, fb))
    if ga < 0:
        b, fb = _bracket(g, k_atm, 0.5 * sd0 + 1e-6, -1.0)
        return math.exp(brent(g, k_atm, b, ga, fb))
    a, fa = _bracket(g, k_atm, -0.5 * sd0 - 1e-6, 1.0)
    return math.exp(brent(g, a, k_atm, fa, ga))


# ---------------------------------------------------------------------------------------------- smiles
class Smile(object):
    """A smile at one tenor: ``vol(K)`` and its slope ``dvol(K)``."""

    F = 1.0
    T = 1.0

    def vol(self, K: float) -> float:
        raise NotImplementedError

    def dvol(self, K: float) -> float:
        h = 1e-5 * K
        return (self.vol(K + h) - self.vol(K - h)) / (2.0 * h)


class FlatSmile(Smile):
    def __init__(self, F: float, T: float, v: float):
        self.F, self.T, self.v = F, T, v

    def vol(self, K: float) -> float:
        return self.v

    def dvol(self, K: float) -> float:
        return 0.0


class SviSmile(Smile):
    """Gatheral's raw SVI: total variance ``w(k) = a + b·(ρ·(k − m) + √((k − m)² + s²))`` of log-moneyness."""

    def __init__(self, F: float, T: float, a: float, b: float, rho: float, m: float, s: float):
        self.F, self.T, self.a, self.b, self.rho, self.m, self.s = F, T, a, b, rho, m, s

    def wk(self, k: float) -> Tuple[float, float, float]:
        x = k - self.m
        r = math.sqrt(x * x + self.s * self.s)
        w = self.a + self.b * (self.rho * x + r)
        return max(w, 1e-14), self.b * (self.rho + x / r), self.b * self.s * self.s / (r * r * r)

    def vol(self, K: float) -> float:
        return math.sqrt(self.wk(math.log(K / self.F))[0] / self.T)

    def dvol(self, K: float) -> float:
        w, dw, _ = self.wk(math.log(K / self.F))
        return dw / (2.0 * math.sqrt(w / self.T) * self.T * K)

    def g(self, k: float) -> float:
        """Gatheral's density factor: the density is positive where it is."""
        w, dw, d2w = self.wk(k)
        return (1.0 - k * dw / (2.0 * w)) ** 2 - dw * dw / 4.0 * (1.0 / w + 0.25) + d2w / 2.0


class SabrSmile(Smile):
    """Hagan's lognormal SABR vol with β = 1."""

    def __init__(self, F: float, T: float, alpha: float, rho: float, nu: float):
        self.F, self.T, self.alpha, self.rho, self.nu = F, T, alpha, rho, nu

    def vol(self, K: float) -> float:
        a, r, n, T = self.alpha, self.rho, self.nu, self.T
        corr = 1.0 + (r * n * a / 4.0 + (2.0 - 3.0 * r * r) * n * n / 24.0) * T
        z = n / a * math.log(self.F / K)
        if abs(z) < 1e-7:
            zx = 1.0 - 0.5 * r * z
        else:
            x = math.log((math.sqrt(1.0 - 2.0 * r * z + z * z) + z - r) / (1.0 - r))
            zx = z / x
        return a * zx * corr


class VannaVolgaSmile(Smile):
    """Castagna and Mercurio's second-order Vanna-Volga vol through three pillars (25P, ATM, 25C)."""

    def __init__(self, F: float, T: float, ks: Sequence[float], vs: Sequence[float]):
        self.F, self.T = F, T
        (self.k1, self.k2, self.k3), (self.v1, self.v2, self.v3) = ks, vs
        if not self.k1 < self.k2 < self.k3:
            raise SmileError("pillars out of order")
        sd = self.v2 * math.sqrt(T)
        self.sd = sd
        self.e1 = self._dd(self.k1)
        self.e3 = self._dd(self.k3)
        self.rough = 0                                  # strikes where the formula fell back to its first order

    def _dd(self, K: float) -> float:
        d1 = (math.log(self.F / K) + 0.5 * self.sd * self.sd) / self.sd
        return d1 * (d1 - self.sd)

    def vol(self, K: float) -> float:
        k1, k2, k3, v1, v2, v3 = self.k1, self.k2, self.k3, self.v1, self.v2, self.v3
        l21, l31, l32 = math.log(k2 / k1), math.log(k3 / k1), math.log(k3 / k2)
        y1 = math.log(k2 / K) * math.log(k3 / K) / (l21 * l31)
        y2 = math.log(K / k1) * math.log(k3 / K) / (l21 * l32)
        y3 = math.log(K / k1) * math.log(K / k2) / (l31 * l32)
        first = y1 * v1 + y2 * v2 + y3 * v3 - v2
        second = y1 * self.e1 * (v1 - v2) ** 2 + y3 * self.e3 * (v3 - v2) ** 2
        dd = self._dd(K)
        if abs(dd) < 1e-10:
            return v2 + first + second / (2.0 * v2)
        arg = v2 * v2 + dd * (2.0 * v2 * first + second)
        if arg < 0.0:
            self.rough += 1
            return max(v2 + first, 1e-4)
        return max(v2 + (-v2 + math.sqrt(arg)) / dd, 1e-4)


# ---------------------------------------------------------------------------------------------- calibration
class Quotes(object):
    """One tenor's quotes in vol units (0.05 = 5 vol), the forward and the conventions."""

    __slots__ = ("F", "T", "atm", "rr25", "bf25", "rr10", "bf10", "premium", "df")

    def __init__(self, F: float, T: float, atm: float, rr25: Optional[float] = None, bf25: Optional[float] = None,
                 rr10: Optional[float] = None, bf10: Optional[float] = None, premium: bool = False, df: float = 1.0):
        self.F, self.T, self.atm = float(F), float(T), float(atm)
        self.rr25, self.bf25, self.rr10, self.bf10 = rr25, bf25, rr10, bf10
        self.premium, self.df = bool(premium), float(df)

    @property
    def has25(self) -> bool:
        return self.rr25 is not None and self.bf25 is not None

    @property
    def has10(self) -> bool:
        return self.has25 and self.rr10 is not None and self.bf10 is not None


def market_strangle(q: Quotes, dl: float, bf: float) -> Tuple[float, float, float, float]:
    """The market strangle of ``dl`` delta: its call and put strikes at the one vol ATM + BF, its price, its vega."""
    s = q.atm + bf
    if s <= 0:
        raise SmileError("strangle vol not positive")
    kc = strike_at(q.F, q.T, dl, True, None, q.premium, q.df, flat=s)
    kp = strike_at(q.F, q.T, dl, False, None, q.premium, q.df, flat=s)
    value = black(q.F, kc, s, q.T, True) + black(q.F, kp, s, q.T, False)
    return kc, kp, value, vega(q.F, kc, s, q.T) + vega(q.F, kp, s, q.T)


def _solve(fn: Callable[[List[float]], List[float]], x0: List[float], tol: float = 1e-11, steps: int = 40) -> Tuple[List[float], List[float]]:
    """Newton's method with a finite-difference Jacobian (one or two unknowns), the step halved while it does not
    make the residual smaller."""
    x = list(x0)
    r = fn(x)
    n = len(x)
    for _ in range(steps):
        if max(abs(v) for v in r) < tol:
            break
        h = 1e-6
        J = []
        for j in range(n):
            xp = list(x)
            xp[j] += h
            rp = fn(xp)
            J.append([(rp[i] - r[i]) / h for i in range(n)])          # J[j][i] = d r_i / d x_j
        if n == 1:
            if J[0][0] == 0:
                break
            dx = [-r[0] / J[0][0]]
        else:
            a, b, c, d = J[0][0], J[1][0], J[0][1], J[1][1]            # [[dr0/dx0, dr0/dx1], [dr1/dx0, dr1/dx1]]
            det = a * d - b * c
            if det == 0:
                break
            dx = [(-r[0] * d + r[1] * b) / det, (-r[1] * a + r[0] * c) / det]
        lam = 1.0
        norm0 = sum(v * v for v in r)
        for _ in range(30):
            xn = [x[i] + lam * dx[i] for i in range(n)]
            try:
                rn = fn(xn)
            except SmileError:
                rn = None
            if rn is not None and sum(v * v for v in rn) < norm0:
                x, r = xn, rn
                break
            lam *= 0.5
        else:
            break
    return x, r


def residuals(q: Quotes, smile: Smile, targets: Optional[Dict[str, Tuple[float, float, float, float]]] = None) -> Dict[str, Optional[float]]:
    """How far the smile is from each quote, in vol (0.01 = 1 vol point): ATM, the risk reversals at the smile's
    own delta strikes, the market strangles repriced (price difference over the strangle's vega).  ``targets``:
    the market strangles already worked out (:func:`market_strangle`), by "25" / "10"."""
    out: Dict[str, Optional[float]] = {"ATM": smile.vol(atm_strike(q.F, q.atm, q.T, q.premium)) - q.atm}
    for tag, dl, rr, bf in (("25", 0.25, q.rr25, q.bf25), ("10", 0.10, q.rr10, q.bf10)):
        if rr is None or bf is None:
            out["RR" + tag] = out["BF" + tag] = None
            continue
        try:
            kc = strike_at(q.F, q.T, dl, True, smile.vol, q.premium, q.df)
            kp = strike_at(q.F, q.T, dl, False, smile.vol, q.premium, q.df)
            out["RR" + tag] = smile.vol(kc) - smile.vol(kp) - rr
            mc, mp, value, vg = (targets or {}).get(tag) or market_strangle(q, dl, bf)
            out["BF" + tag] = (black(q.F, mc, smile.vol(mc), q.T, True) + black(q.F, mp, smile.vol(mp), q.T, False) - value) / vg
        except MATH_ERRORS:
            out["RR" + tag] = out["BF" + tag] = None
    return out


def _fit_vv(q: Quotes) -> Tuple[Smile, Dict[str, Any]]:
    target = market_strangle(q, 0.25, q.bf25)

    def make(s25: float) -> Tuple[VannaVolgaSmile, Dict[str, Tuple[float, float]]]:
        pts = {}                                    # the pillars' strikes come from their own vols
        for name, dl, call in PILLARS[1:4]:
            v = q.atm if call is None else q.atm + s25 + (q.rr25 / 2.0 if call else -q.rr25 / 2.0)
            if v <= 1e-4:
                raise SmileError("%s vol not positive" % name)
            K = atm_strike(q.F, v, q.T, q.premium) if call is None else strike_at(q.F, q.T, dl, call, None, q.premium, q.df, flat=v)
            pts[name] = (K, v)
        sm = VannaVolgaSmile(q.F, q.T, [pts[n][0] for n in ("25P", "ATM", "25C")], [pts[n][1] for n in ("25P", "ATM", "25C")])
        return sm, pts

    def fn(x: List[float]) -> List[float]:
        try:
            sm, _ = make(x[0])
            mc, mp, value, vg = target
            return [(black(q.F, mc, sm.vol(mc), q.T, True) + black(q.F, mp, sm.vol(mp), q.T, False) - value) / vg]
        except MATH_ERRORS as exc:
            raise SmileError(str(exc))

    note = ""
    try:
        x, r = _solve(fn, [q.bf25])
        if abs(r[0]) > 1e-6:
            raise SmileError("market strangle not repriced")
    except SmileError as exc:
        x, note = [q.bf25], "market strangle çözülemedi (%s): smile strangle = BF alındı" % exc
    sm, pts = make(x[0])
    return sm, {"pillars": pts, "smile_bf25": x[0], "smile_bf10": None, "note": note}


def _nelder_mead(f: Callable[[List[float]], float], x0: List[float], step: List[float], iters: int = 300,
                 tol: float = 1e-12) -> Tuple[List[float], float]:
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (step[j] if j == i else 0.0) for j in range(n)] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts = [pts[i] for i in order]
        vals = [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) < tol:
            break
        cen = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        xr = [cen[j] + (cen[j] - pts[-1][j]) for j in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [cen[j] + 2.0 * (cen[j] - pts[-1][j]) for j in range(n)]
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = [cen[j] + 0.5 * (pts[-1][j] - cen[j]) for j in range(n)]
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, n + 1):
                    pts[i] = [pts[0][j] + 0.5 * (pts[i][j] - pts[0][j]) for j in range(n)]
                    vals[i] = f(pts[i])
    i = min(range(n + 1), key=lambda i: vals[i])
    return pts[i], vals[i]


def _gauss(A: List[List[float]], b: List[float]) -> List[float]:
    """Solve a small linear system (partial pivoting)."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda i: abs(M[i][c]))
        if abs(M[p][c]) < 1e-300:
            raise ZeroDivisionError("singular")
        M[c], M[p] = M[p], M[c]
        for i in range(c + 1, n):
            f = M[i][c] / M[c][c]
            if f:
                for j in range(c, n + 1):
                    M[i][j] -= f * M[c][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def _lm(fn: Callable[[List[float]], List[float]], x0: Sequence[float], iters: int = 80, tol: float = 1e-14) -> Tuple[List[float], List[float]]:
    """Levenberg-Marquardt (finite-difference Jacobian): the least-squares minimum of the residuals near ``x0``."""
    x = list(x0)
    r = fn(x)
    cost = sum(v * v for v in r)
    n, m = len(x), len(r)
    lam = 1e-3
    for _ in range(iters):
        if cost < tol:
            break
        J = [[0.0] * n for _ in range(m)]
        for j in range(n):
            h = 1e-7 * max(1.0, abs(x[j]))
            xp = list(x)
            xp[j] += h
            rp = fn(xp)
            for i in range(m):
                J[i][j] = (rp[i] - r[i]) / h
        A = [[sum(J[i][p] * J[i][q] for i in range(m)) for q in range(n)] for p in range(n)]
        g = [sum(J[i][p] * r[i] for i in range(m)) for p in range(n)]
        improved = False
        while lam < 1e12:
            M = [[A[p][q] + (lam * (A[p][p] + 1e-12) if p == q else 0.0) for q in range(n)] for p in range(n)]
            try:
                dx = _gauss(M, [-v for v in g])
            except ZeroDivisionError:
                lam *= 10.0
                continue
            xn = [x[j] + dx[j] for j in range(n)]
            rn = fn(xn)
            cn = sum(v * v for v in rn)
            if cn < cost:
                small = cost - cn < 1e-12 * max(cost, 1e-30)
                x, r, cost = xn, rn, cn
                lam = max(lam / 3.0, 1e-12)
                improved = not small
                break
            lam *= 4.0
        if not improved:
            break
    return x, r


#: weights of the quotes in the least-squares fits: the ATM vol is the best known, the 10-delta wings the least
FIT_WEIGHTS = {"ATM": 2.0, "RR25": 1.0, "BF25": 1.0, "RR10": 0.5, "BF10": 0.5}
SVI_GRID = 41


def _svi_params(t: Sequence[float]) -> Tuple[float, float, float, float, float]:
    """Unconstrained (α, β, γ, m, σ) -> raw SVI (a, b, ρ, m, s) with b > 0, |ρ| < 1, s > 0 and a minimum variance > 0."""
    b = math.exp(t[1])
    rho = math.tanh(t[2])
    s = math.exp(t[4])
    a = math.exp(t[0]) - b * s * math.sqrt(1.0 - rho * rho)
    return a, b, rho, t[3], s


def _svi_unparams(a: float, b: float, rho: float, m: float, s: float) -> List[float]:
    rho = max(-0.999999, min(0.999999, rho))
    return [math.log(max(a + b * s * math.sqrt(1.0 - rho * rho), 1e-12)), math.log(b), math.atanh(rho), m, math.log(s)]


def _approx_pillars(q: Quotes) -> List[Tuple[float, float]]:
    """(k, w) of the pillars as if the butterflies were smile strangles: a first guess."""
    vols = [(None, 0.5, q.atm)]
    if q.has25:
        vols += [(True, 0.25, q.atm + q.bf25 + q.rr25 / 2.0), (False, 0.25, q.atm + q.bf25 - q.rr25 / 2.0)]
    if q.has10:
        vols += [(True, 0.10, q.atm + q.bf10 + q.rr10 / 2.0), (False, 0.10, q.atm + q.bf10 - q.rr10 / 2.0)]
    out = []
    for call, dl, v in vols:
        v = max(v, 0.2 * q.atm)
        K = atm_strike(q.F, v, q.T, q.premium) if call is None else strike_at(q.F, q.T, dl, call, None, q.premium, q.df, flat=v)
        out.append((math.log(K / q.F), v * v * q.T))
    return sorted(out)


def _fit_svi(q: Quotes, start: Optional[Sequence[float]] = None) -> Tuple[Smile, Dict[str, Any]]:
    """SVI fitted to the quotes (least squares in vol points) with Gatheral's no-butterfly condition as a penalty:
    the smile that comes out never has a negative density."""
    pts = _approx_pillars(q)
    sd = q.atm * math.sqrt(q.T)
    k_lo, k_hi = min(p[0] for p in pts) - 4.0 * sd, max(p[0] for p in pts) + 4.0 * sd
    grid = [k_lo + (k_hi - k_lo) * i / (SVI_GRID - 1) for i in range(SVI_GRID)]
    targets = {"25": market_strangle(q, 0.25, q.bf25)}
    if q.has10:
        targets["10"] = market_strangle(q, 0.10, q.bf10)

    def penalty(sm: SviSmile) -> float:
        worst = min(sm.g(k) for k in grid)
        lee = max(0.0, sm.b * (1.0 + abs(sm.rho)) - 2.0)
        return max(0.0, -worst) * 100.0 + lee * 100.0

    # ---- a first guess: through the approximate pillars (no strike search: cheap)
    def first(t: List[float]) -> List[float]:
        try:
            sm = SviSmile(q.F, q.T, *_svi_params(t))
            return [(sm.wk(k)[0] / w - 1.0) * 100.0 for k, w in pts] + [penalty(sm)]
        except (ValueError, OverflowError, ZeroDivisionError):
            return [1e3] * (len(pts) + 1)

    w_atm = q.atm * q.atm * q.T
    guesses = [list(start)] if start else []
    skew = (q.rr25 or 0.0) / max(q.atm, 1e-6)
    for rho0 in (max(-0.9, min(0.9, skew)), 0.0, 0.8 if skew > 0 else -0.8):
        for s0 in (sd, 3.0 * sd):
            guesses.append(_svi_unparams(0.5 * w_atm, w_atm / (2.0 * s0), rho0, 0.0, s0))
    best = None
    for g0 in guesses:
        x, r = _lm(first, g0, iters=60)
        c = sum(v * v for v in r)
        if best is None or c < best[1]:
            best = (x, c)
        if c < 1e-6 and not start:
            break

    # ---- the quotes themselves: market strangles, risk reversals at the smile's own deltas
    keys = ["ATM", "RR25", "BF25"] + (["RR10", "BF10"] if q.has10 else [])

    def fn(t: List[float]) -> List[float]:
        try:
            sm = SviSmile(q.F, q.T, *_svi_params(t))
            res = residuals(q, sm, targets)
            out = []
            for key in keys:
                v = res.get(key)
                out.append(1e2 if v is None else v * 100.0 * FIT_WEIGHTS[key])
            out.append(penalty(sm))
            return out
        except MATH_ERRORS:
            return [1e3] * (len(keys) + 1)

    x, r = _lm(fn, best[0], iters=60)
    sm = SviSmile(q.F, q.T, *_svi_params(x))
    a, b, rho, m, s = _svi_params(x)
    return sm, {"pillars": None, "svi": {"a": a, "b": b, "rho": rho, "m": m, "s": s}, "start": x,
                "min_g": min(sm.g(k) for k in grid), "note": ""}


def _sabr_alpha(q: Quotes, rho: float, nu: float) -> float:
    """The alpha that gives the quoted ATM vol at the ATM strike."""
    katm = atm_strike(q.F, q.atm, q.T, q.premium)
    g = lambda a: SabrSmile(q.F, q.T, a, rho, nu).vol(katm) - q.atm   # noqa: E731
    lo, hi = q.atm * 0.05, q.atm * 3.0
    flo, fhi = g(lo), g(hi)
    if (flo > 0) == (fhi > 0):
        raise SmileError("SABR alpha")
    return brent(g, lo, hi, flo, fhi, xtol=1e-14)


def _fit_sabr(q: Quotes, start: Optional[Tuple[float, float]] = None) -> Tuple[Smile, Dict[str, Any]]:
    use10 = q.has10
    weights = {k: v for k, v in FIT_WEIGHTS.items() if k != "ATM"}            # the ATM vol is held exactly
    targets = {"25": market_strangle(q, 0.25, q.bf25)}
    if use10:
        targets["10"] = market_strangle(q, 0.10, q.bf10)

    def smile_of(x: List[float]) -> SabrSmile:
        rho, nu = math.tanh(x[0]), math.exp(x[1])
        return SabrSmile(q.F, q.T, _sabr_alpha(q, rho, nu), rho, nu)

    def cost(x: List[float]) -> float:
        try:
            r = residuals(q, smile_of(x), targets)
        except MATH_ERRORS:
            return 1e6
        total = 0.0
        for key, w in weights.items():
            if key.endswith("10") and not use10:
                continue
            v = r.get(key)
            total += w * (v * 100.0) ** 2 if v is not None else 1e4
        return total

    skew = 0.5 if (q.rr25 or 0.0) > 0 else -0.5
    starts = [tuple(start)] if start else []
    starts += [(math.atanh(skew), math.log(1.0)), (0.0, math.log(0.5)), (math.atanh(-skew), math.log(2.0))]
    best = None
    for s in starts:
        x, c = _nelder_mead(cost, list(s), [0.3, 0.3], iters=150)
        if best is None or c < best[1]:
            best = (x, c)
        if c < 1e-4:
            break
    sm = smile_of(best[0])
    return sm, {"pillars": None, "alpha": sm.alpha, "rho": sm.rho, "nu": sm.nu, "start": (best[0][0], best[0][1]), "note": ""}


def build_smile(q: Quotes, model: str = "svi", start: Any = None) -> Tuple[Smile, Dict[str, Any]]:
    """The smile of one tenor and how it was made: ``(smile, info)``; ``info["fit"]`` holds the residuals."""
    if not (q.atm > 0 and q.T > 0 and q.F > 0):
        raise SmileError("ATM vol / forward / time not positive")
    if not q.has25:
        sm: Smile = FlatSmile(q.F, q.T, q.atm)
        info: Dict[str, Any] = {"pillars": {"ATM": (atm_strike(q.F, q.atm, q.T, q.premium), q.atm)}, "note": "yalnız ATM: smile düz"}
    elif model == "sabr":
        sm, info = _fit_sabr(q, start)
    elif model == "vv":
        sm, info = _fit_vv(q)
    else:
        sm, info = _fit_svi(q, start)
    info["model"] = (model if model in MODELS else "svi") if q.has25 else "flat"
    info["fit"] = residuals(q, sm)
    info["points"] = pillar_points(q, sm)
    return sm, info


def pillar_points(q: Quotes, smile: Smile) -> Dict[str, Optional[Tuple[float, float]]]:
    """The smile's own 10P / 25P / ATM / 25C / 10C: ``{name: (strike, vol)}`` (the strike where the smile gives that
    delta, with the pair's conventions)."""
    out: Dict[str, Optional[Tuple[float, float]]] = {}
    for name, dl, call in PILLARS:
        try:
            K = atm_strike(q.F, q.atm, q.T, q.premium) if call is None else strike_at(q.F, q.T, dl, call, smile.vol, q.premium, q.df)
            out[name] = (K, smile.vol(K))
        except MATH_ERRORS:
            out[name] = None
    return out


# ---------------------------------------------------------------------------------------------- the distribution
class Distribution(object):
    """The risk-neutral law of the spot at expiry implied by a smile."""

    def __init__(self, smile: Smile):
        self.smile = smile
        self.F, self.T = smile.F, smile.T
        self.sd = smile.vol(self.F) * math.sqrt(self.T)

    def above(self, K: float) -> float:
        """P(S_T > K) = N(d2) − F·n(d1)·√T·σ'(K)."""
        F, T = self.F, self.T
        s = self.smile.vol(K)
        sd = s * math.sqrt(T)
        d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
        return ncdf(d1 - sd) - F * npdf(d1) * math.sqrt(T) * self.smile.dvol(K)

    def cdf(self, K: float) -> float:
        return min(1.0, max(0.0, 1.0 - self.above(K)))

    def density(self, K: float) -> float:
        h = 1e-4 * K
        return (self.above(K - h) - self.above(K + h)) / (2.0 * h)

    def quantile(self, p: float) -> float:
        """The level the spot ends below with probability ``p``."""
        g = lambda x: (1.0 - self.above(math.exp(x))) - p                 # noqa: E731
        x0 = math.log(self.F)
        g0 = g(x0)
        step = 0.5 * max(self.sd, 1e-4)
        if g0 < 0:
            b, gb = _bracket(g, x0, step, -1.0, limit=80)
            return math.exp(brent(g, x0, b, g0, gb, xtol=1e-12))
        a, ga = _bracket(g, x0, -step, 1.0, limit=80)
        return math.exp(brent(g, a, x0, ga, g0, xtol=1e-12))

    def check(self, n: int = 600) -> Dict[str, Any]:
        """Mass, mean (should be the forward) and the lowest density on a grid wide enough for both tails."""
        sd = max(self.sd, 1e-4)
        n += n % 2                                               # Simpson's rule wants an even number of slices
        lo = math.log(self.F) - 12.0 * sd
        hi = math.log(self.F) + 12.0 * sd * max(1.0, self.smile.vol(self.F * math.exp(3 * sd)) / max(self.smile.vol(self.F), 1e-6))
        step = (hi - lo) / n
        xs = [lo + step * i for i in range(n + 1)]
        ks = [math.exp(x) for x in xs]
        ab = [self.above(K) for K in ks]
        mass = ab[0] - ab[-1]
        # E[S] = ∫ P(S > K) dK over (0, ∞): below the grid P = 1, above it ~0; on the grid in x = ln K, dK = K dx
        f = [a * K for a, K in zip(ab, ks)]
        mean = ks[0] + step / 3.0 * (f[0] + f[-1] + 4.0 * sum(f[1:-1:2]) + 2.0 * sum(f[2:-1:2]))
        drops = [ab[i] - ab[i + 1] for i in range(n)]            # probability of each slice: never below zero
        worst = min(drops)
        return {"mass": mass, "mean": mean, "mean_error": mean / self.F - 1.0, "min_slice": worst,
                "arbitrage": worst < -1e-7, "lo": ks[0], "hi": ks[-1]}


def quantiles(dist: Distribution, ps: Sequence[float] = QUANTILES) -> Dict[float, Optional[float]]:
    out: Dict[float, Optional[float]] = {}
    for p in ps:
        try:
            out[p] = dist.quantile(p)
        except MATH_ERRORS:
            out[p] = None
    return out
