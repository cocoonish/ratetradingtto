"""The statistics behind the quant signals (``tto.quant``), in plain Python.

The single-file installer ships only the web packages - there is no numpy on the desk machine - and the sizes are
small (a few dozen series of a few hundred daily points), so lists and loops do:

* means, standard deviations, correlations (and a rolling one kept up to date in O(1) a step), z-scores, percentiles;
* least squares by the normal equations (Gaussian elimination with partial pivoting; an optional ridge term);
* the eigen-decomposition of a symmetric matrix by Jacobi rotations, and principal components on top of it;
* the augmented Dickey-Fuller test with MacKinnon's (2010) response-surface critical values, Engle-Granger;
* the Ornstein-Uhlenbeck fit of a series by its AR(1) regression (half-life, equilibrium mean and spread);
* a scalar Kalman filter for a hedge ratio that drifts;
* the variance-ratio test (Lo-MacKinlay, robust to heteroskedasticity) and a variance-time Hurst exponent;
* EWMA and GARCH(1,1) volatility (maximum likelihood on a grid, the long-run variance targeted) and their forecasts;
* logistic regression with an L2 penalty (Newton / IRLS), log-loss;
* a Newey-West t-statistic for the mean of overlapping observations.

Every function takes lists of floats without gaps (the caller aligns the series first) and answers ``None`` where the
data do not allow an answer (too few points, no variance, a singular system) rather than raising.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vector = List[float]
Matrix = List[List[float]]


# ---------------------------------------------------------------------------------------------- basics
def mean(xs: Sequence[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def var(xs: Sequence[float], ddof: int = 1) -> Optional[float]:
    n = len(xs)
    if n <= ddof:
        return None
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - ddof)


def stdev(xs: Sequence[float], ddof: int = 1) -> Optional[float]:
    """Sample standard deviation (Excel's STDEV); ``None`` for too few points or none at all."""
    v = var(xs, ddof)
    return math.sqrt(v) if v is not None and v > 0 else None


def cov(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx, my = sum(xs[:n]) / n, sum(ys[:n]) / n
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (n - 1)


def corr(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson correlation; ``None`` with fewer than three points or a flat series."""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    mx, my = sum(xs[:n]) / n, sum(ys[:n]) / n
    sxy = sxx = syy = 0.0
    for i in range(n):
        a, b = xs[i] - mx, ys[i] - my
        sxy += a * b
        sxx += a * a
        syy += b * b
    if sxx <= 0 or syy <= 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def zscore(value: Optional[float], xs: Sequence[float]) -> Optional[float]:
    """Where ``value`` stands against ``xs``: (value − mean) / sample standard deviation."""
    sd = stdev(xs)
    if value is None or sd is None:
        return None
    return (value - sum(xs) / len(xs)) / sd


def percentile(value: Optional[float], xs: Sequence[float]) -> Optional[float]:
    """The share of ``xs`` at or below ``value`` (0 … 1)."""
    if value is None or not xs:
        return None
    return sum(1 for x in xs if x <= value) / len(xs)


def fisher(r: float) -> float:
    """Fisher's z of a correlation (its sampling distribution is close to normal)."""
    r = max(-0.999999, min(0.999999, r))
    return 0.5 * math.log((1.0 + r) / (1.0 - r))


def rolling_corr(xs: Sequence[float], ys: Sequence[float], window: int) -> List[Optional[float]]:
    """The correlation of the ``window`` points ending at each index (``None`` before), the sums kept up to date as
    the window moves - O(n) for the whole series."""
    n = min(len(xs), len(ys))
    out: List[Optional[float]] = [None] * n
    if window < 3 or n < window:
        return out
    sx = sy = sxx = syy = sxy = 0.0
    for i in range(n):
        x, y = xs[i], ys[i]
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y
        if i >= window:
            a, b = xs[i - window], ys[i - window]
            sx -= a
            sy -= b
            sxx -= a * a
            syy -= b * b
            sxy -= a * b
        if i >= window - 1:
            vx = sxx - sx * sx / window
            vy = syy - sy * sy / window
            if vx > 1e-12 * max(1.0, sxx) and vy > 1e-12 * max(1.0, syy):
                out[i] = max(-1.0, min(1.0, (sxy - sx * sy / window) / math.sqrt(vx * vy)))
    return out


# ---------------------------------------------------------------------------------------------- linear algebra
def solve(a: Matrix, b: Vector) -> Optional[Vector]:
    """``a·x = b`` by Gaussian elimination with partial pivoting; ``None`` when ``a`` is (numerically) singular."""
    n = len(b)
    m = [list(map(float, a[i])) + [float(b[i])] for i in range(n)]
    scale = max((abs(v) for row in a for v in row), default=0.0) or 1.0
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) <= 1e-12 * scale:
            return None
        if piv != col:
            m[col], m[piv] = m[piv], m[col]
        p = m[col][col]
        for r in range(col + 1, n):
            f = m[r][col] / p
            if f:
                row, top = m[r], m[col]
                for c in range(col, n + 1):
                    row[c] -= f * top[c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))
        x[r] = s / m[r][r]
    return x


def inverse(a: Matrix) -> Optional[Matrix]:
    n = len(a)
    cols = []
    for j in range(n):
        e = [1.0 if i == j else 0.0 for i in range(n)]
        x = solve(a, e)
        if x is None:
            return None
        cols.append(x)
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def ols(y: Sequence[float], xs: Sequence[Sequence[float]], const: bool = True, ridge: float = 0.0) -> Optional[Dict[str, Any]]:
    """Least squares of ``y`` on the regressors ``xs`` (a list of columns), with an intercept first when ``const``.

    Normal equations (X'X + ridge·I) b = X'y - the intercept is never penalised.  Returns ``{"coef", "se", "t", "resid",
    "fitted", "r2", "sigma2", "n", "k"}`` (``se``/``t`` from the classical covariance σ²(X'X)⁻¹), or ``None`` for too
    few points or collinear regressors."""
    n = len(y)
    cols = ([[1.0] * n] if const else []) + [list(c) for c in xs]
    k = len(cols)
    if k == 0 or n <= k or any(len(c) != n for c in cols):
        return None
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for i in range(k):
        ci = cols[i]
        xty[i] = sum(ci[t] * y[t] for t in range(n))
        for j in range(i, k):
            cj = cols[j]
            v = sum(ci[t] * cj[t] for t in range(n))
            xtx[i][j] = xtx[j][i] = v
    if ridge > 0:
        for i in range(1 if const else 0, k):
            xtx[i][i] += ridge
    inv = inverse(xtx)
    if inv is None:
        return None
    coef = [sum(inv[i][j] * xty[j] for j in range(k)) for i in range(k)]
    fitted = [sum(coef[j] * cols[j][t] for j in range(k)) for t in range(n)]
    resid = [y[t] - fitted[t] for t in range(n)]
    sse = sum(e * e for e in resid)
    sigma2 = sse / (n - k)
    se = [math.sqrt(max(0.0, sigma2 * inv[i][i])) for i in range(k)]
    tstat = [coef[i] / se[i] if se[i] > 0 else None for i in range(k)]
    my = sum(y) / n
    sst = sum((v - my) ** 2 for v in y)
    r2 = 1.0 - sse / sst if sst > 0 else None
    return {"coef": coef, "se": se, "t": tstat, "resid": resid, "fitted": fitted, "r2": r2, "sigma2": sigma2, "n": n, "k": k}


# ---------------------------------------------------------------------------------------------- eigen / PCA
def jacobi_eigen(a: Matrix, tol: float = 1e-12, sweeps: int = 100) -> Tuple[Vector, Matrix]:
    """Eigenvalues and eigenvectors of a symmetric matrix by cyclic Jacobi rotations.  Returns ``(values, vectors)``
    sorted by value, largest first; ``vectors[k]`` is the unit eigenvector of ``values[k]``."""
    n = len(a)
    m = [list(map(float, row)) for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(sweeps):
        off = sum(m[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off <= tol * max(1e-300, sum(m[i][i] ** 2 for i in range(n))):
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                apq = m[p][q]
                if abs(apq) < 1e-300:
                    continue
                theta = (m[q][q] - m[p][p]) / (2.0 * apq)
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):                      # columns p and q
                    akp, akq = m[k][p], m[k][q]
                    m[k][p] = c * akp - s * akq
                    m[k][q] = s * akp + c * akq
                for k in range(n):                      # rows p and q
                    apk, aqk = m[p][k], m[q][k]
                    m[p][k] = c * apk - s * aqk
                    m[q][k] = s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    order = sorted(range(n), key=lambda i: -m[i][i])
    return [m[i][i] for i in order], [[v[k][i] for k in range(n)] for i in order]


def covariance(rows: Sequence[Sequence[float]]) -> Tuple[Vector, Matrix]:
    """Means and the sample covariance matrix of observations ``rows`` (n × k)."""
    n = len(rows)
    k = len(rows[0]) if rows else 0
    means = [sum(r[j] for r in rows) / n for j in range(k)]
    c = [[0.0] * k for _ in range(k)]
    for r in rows:
        d = [r[j] - means[j] for j in range(k)]
        for i in range(k):
            di = d[i]
            ci = c[i]
            for j in range(i, k):
                ci[j] += di * d[j]
    for i in range(k):
        for j in range(i, k):
            c[i][j] /= max(1, n - 1)
            c[j][i] = c[i][j]
    return means, c


def pca(rows: Sequence[Sequence[float]]) -> Optional[Dict[str, Any]]:
    """Principal components of observations ``rows`` (n × k): ``{"means", "values" (variances, largest first),
    "vectors" (unit loadings), "explained" (shares)}``."""
    if len(rows) < 3 or not rows[0]:
        return None
    means, c = covariance(rows)
    values, vectors = jacobi_eigen(c)
    total = sum(max(0.0, x) for x in values)
    if total <= 0:
        return None
    return {"means": means, "values": values, "vectors": vectors, "explained": [max(0.0, x) / total for x in values], "cov": c}


# ---------------------------------------------------------------------------------------------- unit roots, cointegration
#: MacKinnon (2010), "Critical values for cointegration tests", table of the response surfaces
#: crit(T) = b∞ + b1/T + b2/T² + b3/T³ for the τ statistic with a constant; N = number of variables
#: (1: the Dickey-Fuller test of one series, 2: Engle-Granger on the residual of a pair)
MACKINNON_C = {
    1: {1: (-3.43035, -6.5393, -16.786, -79.433), 5: (-2.86154, -2.8903, -4.234, -40.040), 10: (-2.56677, -1.5384, -2.809, 0.0)},
    2: {1: (-3.89644, -10.9519, -33.527, 0.0), 5: (-3.33613, -6.1101, -6.823, 0.0), 10: (-3.04445, -4.2412, -2.720, 0.0)},
}


def mackinnon_crit(n_vars: int, nobs: int) -> Dict[int, float]:
    """The 1 / 5 / 10 % critical values of the τ statistic (constant, no trend) for a sample of ``nobs``."""
    table = MACKINNON_C[2 if n_vars >= 2 else 1]
    t = float(max(nobs, 10))
    return {lvl: b[0] + b[1] / t + b[2] / t ** 2 + b[3] / t ** 3 for lvl, b in table.items()}


def adf(x: Sequence[float], max_lag: int = 4, n_vars: int = 1) -> Optional[Dict[str, Any]]:
    """Augmented Dickey-Fuller test with a constant: Δx_t = a + γ·x_{t−1} + Σ φ_i·Δx_{t−i} + e_t, τ = γ / se(γ).

    The number of lagged differences (0 … ``max_lag``) is the one with the lowest AIC on a common sample; τ is then
    estimated with that lag on every point it allows.  ``n_vars`` 2 for the residual of a cointegrating regression
    (Engle-Granger's critical values).  Returns ``{"stat", "lag", "nobs", "gamma", "crit", "level"}`` - ``level`` the
    smallest of 1 / 5 / 10 (%) at which a unit root is rejected, ``None`` when it is not."""
    n = len(x)
    if n < 20 + max_lag:
        return None
    dx = [x[t] - x[t - 1] for t in range(1, n)]

    def fit(p: int, start: int) -> Optional[Dict[str, Any]]:
        # rows t = start … n−1 (indices of x); Δx_t = dx[t−1]
        y = [dx[t - 1] for t in range(start, n)]
        cols = [[x[t - 1] for t in range(start, n)]]
        for i in range(1, p + 1):
            cols.append([dx[t - 1 - i] for t in range(start, n)])
        return ols(y, cols)

    best_p, best_aic = 0, None
    common = max_lag + 1
    for p in range(0, max_lag + 1):
        r = fit(p, common)
        if r is None:
            continue
        m = r["n"]
        sse = r["sigma2"] * (m - r["k"])
        if sse <= 0:
            continue
        aic = m * math.log(sse / m) + 2 * r["k"]
        if best_aic is None or aic < best_aic - 1e-12:
            best_p, best_aic = p, aic
    r = fit(best_p, best_p + 1)
    if r is None or r["t"][1] is None:
        return None
    stat = r["t"][1]
    crit = mackinnon_crit(n_vars, r["n"])
    level = next((lvl for lvl in (1, 5, 10) if stat < crit[lvl]), None)
    return {"stat": stat, "lag": best_p, "nobs": r["n"], "gamma": r["coef"][1], "crit": crit, "level": level}


def engle_granger(y: Sequence[float], x: Sequence[float], max_lag: int = 4) -> Optional[Dict[str, Any]]:
    """Engle-Granger: the static regression y = α + β·x + e, then the ADF test of e with the critical values of a
    two-variable cointegrating regression.  ``{"alpha", "beta", "t_beta", "r2", "resid", "adf", "passes" (5 %)}``."""
    r = ols(y, [x])
    if r is None:
        return None
    test = adf(r["resid"], max_lag, n_vars=2)
    return {"alpha": r["coef"][0], "beta": r["coef"][1], "t_beta": r["t"][1], "r2": r["r2"], "resid": r["resid"],
            "sigma": math.sqrt(r["sigma2"]), "adf": test, "passes": bool(test and test["level"] in (1, 5))}


# ---------------------------------------------------------------------------------------------- Ornstein-Uhlenbeck
def ou_fit(x: Sequence[float]) -> Optional[Dict[str, Any]]:
    """The Ornstein-Uhlenbeck reading of a series by its AR(1) regression x_{t+1} = a + b·x_t + e:
    b = e^{−κ}, half-life = ln 2 / κ (in steps, here business days), μ = a / (1 − b), σ_eq = σ_e / √(1 − b²).
    ``half_life`` (and ``mu``, ``sigma_eq``) are ``None`` when b ≥ 1 - the series does not return to a mean; with
    b ≤ 0 it is back (or overshoots) within a step: a half-life of 0."""
    if len(x) < 10:
        return None
    r = ols(list(x[1:]), [list(x[:-1])])
    if r is None:
        return None
    a, b = r["coef"]
    sig = math.sqrt(r["sigma2"])
    out: Dict[str, Any] = {"a": a, "b": b, "t_b": r["t"][1], "sigma": sig, "half_life": None, "kappa": None, "mu": None, "sigma_eq": None,
                           "n": r["n"]}
    if -1.0 < b < 1.0:
        out.update({"mu": a / (1.0 - b), "sigma_eq": sig / math.sqrt(1.0 - b * b)})
        if b > 0.0:
            kappa = -math.log(b)
            out.update({"kappa": kappa, "half_life": math.log(2.0) / kappa})
        else:
            out["half_life"] = 0.0
    return out


# ---------------------------------------------------------------------------------------------- Kalman
def kalman_beta(y: Sequence[float], x: Sequence[float], alpha: float, beta0: float, p0: float, r: float, q: float) -> Dict[str, List[float]]:
    """A hedge ratio that follows a random walk, observed through y_t = α + β_t·x_t + ε_t (ε ~ N(0, r), the walk's
    step ~ N(0, q)): the scalar Kalman filter.  Returns the prior (one step ahead) and posterior β, the innovation
    e_t = y_t − α − β_{t|t−1}·x_t and its variance S_t = x_t²·P_{t|t−1} + r - the one-step-ahead residual."""
    beta, p = beta0, p0
    prior, post, innov, var_s = [], [], [], []
    for yt, xt in zip(y, x):
        p_pred = p + q
        e = yt - alpha - beta * xt
        s = xt * xt * p_pred + r
        k = p_pred * xt / s if s > 0 else 0.0
        prior.append(beta)
        innov.append(e)
        var_s.append(s)
        beta = beta + k * e
        p = (1.0 - k * xt) * p_pred
        post.append(beta)
    return {"prior": prior, "post": post, "innov": innov, "S": var_s}


# ---------------------------------------------------------------------------------------------- regime
def variance_ratio(changes: Sequence[float], q: int) -> Optional[Dict[str, float]]:
    """Lo-MacKinlay variance ratio of the ``q``-period changes (overlapping sums) to ``q`` one-period changes, with the
    heteroskedasticity-robust z statistic.  VR < 1: moves partly undo themselves (mean reversion), VR > 1: they
    continue (trend)."""
    n = len(changes)
    if q < 2 or n < 4 * q:
        return None
    mu = sum(changes) / n
    dev = [c - mu for c in changes]
    s2 = sum(d * d for d in dev)
    if s2 <= 0:
        return None
    var_a = s2 / (n - 1)
    m = q * (n - q + 1) * (1.0 - q / n)
    acc = sum(dev[:q])
    tot = (acc) ** 2
    for t in range(q, n):
        acc += dev[t] - dev[t - q]
        tot += acc * acc
    var_c = tot / m
    vr = var_c / var_a
    theta = 0.0
    for j in range(1, q):
        delta = n * sum((dev[t] ** 2) * (dev[t - j] ** 2) for t in range(j, n)) / (s2 * s2)
        theta += (2.0 * (q - j) / q) ** 2 * delta
    # z* = √n · (VR − 1) / √θ: θ / n is the asymptotic variance of VR (Lo and MacKinlay 1988, eq. 19)
    z = math.sqrt(n) * (vr - 1.0) / math.sqrt(theta) if theta > 0 else None
    return {"vr": vr, "z": z, "q": q}


def hurst(changes: Sequence[float], scales: Sequence[int] = (1, 2, 4, 8, 16)) -> Optional[float]:
    """Hurst exponent by the variance-time rule: the standard deviation of the sums of q consecutive changes grows
    like q^H (non-overlapping sums; 0.5 a random walk, below it mean reversion, above it trend).  Scales that
    leave fewer than eight sums are not used."""
    pts = []
    n = len(changes)
    for q in scales:
        m = n // q
        if m < 8:
            break
        sums = [sum(changes[i * q:(i + 1) * q]) for i in range(m)]
        sd = stdev(sums)
        if sd:
            pts.append((math.log(q), math.log(sd)))
    if len(pts) < 3:
        return None
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx > 0 else None


# ---------------------------------------------------------------------------------------------- volatility
def ewma_var(returns: Sequence[float], lam: float = 0.94, seed: int = 20) -> List[Optional[float]]:
    """RiskMetrics: the variance forecast for each day from the returns before it, σ²_t = λσ²_{t−1} + (1−λ)r²_{t−1}
    (the first one the sample variance of the first ``seed`` returns).  ``out[t]`` is the forecast for day t."""
    n = len(returns)
    out: List[Optional[float]] = [None] * (n + 1)
    if n < seed + 1:
        return out
    v = sum(r * r for r in returns[:seed]) / seed
    out[seed] = v
    for t in range(seed, n):
        v = lam * v + (1.0 - lam) * returns[t] * returns[t]
        out[t + 1] = v
    return out


def garch_loglik(returns: Sequence[float], omega: float, alpha: float, beta: float, v0: float) -> float:
    v = v0
    ll = 0.0
    for r in returns:
        if v <= 0:
            return -1e300
        ll -= 0.5 * (math.log(v) + r * r / v)
        v = omega + alpha * r * r + beta * v
    return ll


def garch_fit(returns: Sequence[float]) -> Optional[Dict[str, float]]:
    """GARCH(1,1) σ²_t = ω + α·r²_{t−1} + β·σ²_{t−1} by maximum likelihood on a grid of (α, β), the long-run
    variance targeted (ω = σ̄²·(1 − α − β), σ̄² the sample variance), then a finer grid around the best point.
    Returns ``{"omega", "alpha", "beta", "long_var", "loglik", "last_var"}`` (``last_var``: the forecast for the day
    after the last return)."""
    n = len(returns)
    if n < 60:
        return None
    mu = sum(returns) / n
    rs = [r - mu for r in returns]
    lv = sum(r * r for r in rs) / n
    if lv <= 0:
        return None
    best = None

    def consider(a: float, b: float) -> None:
        nonlocal best
        if a < 0 or b < 0 or a + b >= 0.999:
            return
        ll = garch_loglik(rs, lv * (1.0 - a - b), a, b, lv)
        if best is None or ll > best[0]:
            best = (ll, a, b)

    for a in [0.02 * i for i in range(1, 16)]:
        for b in [0.50 + 0.05 * j for j in range(0, 9)] + [0.92, 0.94, 0.96, 0.97, 0.98]:
            consider(a, b)
    if best is None:
        return None
    _, a0, b0 = best
    for da in (-0.015, -0.01, -0.005, 0.0, 0.005, 0.01, 0.015):
        for db in (-0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02):
            consider(a0 + da, b0 + db)
    ll, a, b = best
    omega = lv * (1.0 - a - b)
    v = lv
    for r in rs:
        v = omega + a * r * r + b * v
    return {"omega": omega, "alpha": a, "beta": b, "long_var": lv, "loglik": ll, "last_var": v, "mu": mu}


def garch_path(returns: Sequence[float], fit: Dict[str, float]) -> List[float]:
    """The one-step variance forecasts of a fitted GARCH(1,1): ``out[t]`` for day t from the returns before it."""
    v = fit["long_var"]
    out = [v]
    for r in returns:
        r = r - fit.get("mu", 0.0)
        v = fit["omega"] + fit["alpha"] * r * r + fit["beta"] * v
        out.append(v)
    return out


def garch_avg_var(next_var: float, fit: Dict[str, float], h: int) -> float:
    """The mean of the variance forecasts over the next ``h`` days, starting from tomorrow's ``next_var``: the
    forecast decays to the long-run variance at the rate α + β."""
    phi = fit["alpha"] + fit["beta"]
    lv = fit["long_var"]
    if h <= 1 or abs(1.0 - phi) < 1e-12:
        return next_var
    return lv + (next_var - lv) * (1.0 - phi ** h) / (h * (1.0 - phi))


# ---------------------------------------------------------------------------------------------- logistic regression
def logistic(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def logistic_fit(rows: Sequence[Sequence[float]], ys: Sequence[int], l2: float = 1.0, iters: int = 25,
                 init: Optional[Vector] = None) -> Optional[Vector]:
    """L2-penalised logistic regression by Newton steps (IRLS).  ``rows`` are feature vectors (no intercept: it is
    added first and not penalised); returns the coefficients ``[intercept, w1, …]``."""
    n = len(rows)
    if n < 10:
        return None
    k = len(rows[0]) + 1
    w = list(init) if init is not None and len(init) == k else [0.0] * k
    xs = [[1.0] + list(r) for r in rows]
    for _ in range(iters):
        g = [0.0] * k
        h = [[0.0] * k for _ in range(k)]
        for x, y in zip(xs, ys):
            p = logistic(sum(w[j] * x[j] for j in range(k)))
            d = p - y
            s = p * (1.0 - p)
            for i in range(k):
                xi = x[i]
                g[i] += d * xi
                if s:
                    hi = h[i]
                    for j in range(i, k):
                        hi[j] += s * xi * x[j]
        for i in range(k):
            for j in range(i + 1, k):
                h[j][i] = h[i][j]
        for i in range(1, k):
            g[i] += l2 * w[i]
            h[i][i] += l2
        h[0][0] += 1e-9
        step = solve(h, g)
        if step is None:
            return None
        w = [w[i] - step[i] for i in range(k)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return w


def logistic_prob(w: Vector, row: Sequence[float]) -> float:
    return logistic(w[0] + sum(w[j + 1] * row[j] for j in range(len(row))))


def log_loss(probs: Sequence[float], ys: Sequence[int]) -> Optional[float]:
    if not probs:
        return None
    eps = 1e-12
    return -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1.0 - p)) for p, y in zip(probs, ys)) / len(probs)


# ---------------------------------------------------------------------------------------------- overlapping means
def newey_west(xs: Sequence[float], lags: int) -> Optional[Dict[str, float]]:
    """The mean of ``xs`` and its t-statistic with the Newey-West (Bartlett) variance - for averages of overlapping
    changes (an N-day change measured every day shares N − 1 days with the next one)."""
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    d = [x - m for x in xs]
    g0 = sum(v * v for v in d) / n
    s = g0
    for j in range(1, min(lags, n - 1) + 1):
        gj = sum(d[t] * d[t - j] for t in range(j, n)) / n
        s += 2.0 * (1.0 - j / (lags + 1.0)) * gj
    se = math.sqrt(s / n) if s > 0 else None
    return {"mean": m, "se": se, "t": m / se if se else None, "n": n, "sd": math.sqrt(g0 * n / (n - 1)) if n > 1 else None}


#: the two-sided 5 % critical value of |t| from :func:`newey_west` (lag h − 1) on the mean of overlapping h-day changes,
#: by r = n / h - the independent h-day periods in the sample - simulated on random walks (the null of no drift; h of
#: 5, 10 and 20 give the same values for the same r, 1 500 – 3 000 draws a point, the tail smoothed): with a few periods
#: the Newey-West variance is far too small and 1.96 would find a drift in noise about one time in three
NW_CRITICAL = ((2.0, 7.8), (2.5, 6.3), (3.0, 5.3), (4.0, 4.2), (5.0, 3.8), (7.5, 3.2), (10.0, 3.0), (15.0, 2.7), (20.0, 2.55),
               (30.0, 2.45), (50.0, 2.3), (100.0, 2.15), (1000.0, 1.96))


def nw_critical(n: int, h: int) -> Optional[float]:
    """The 5 % two-sided critical value of a Newey-West t on ``n`` overlapping ``h``-day changes (``None``: fewer than two
    independent periods - no test is possible)."""
    if h <= 1:
        return 1.96 if n >= 30 else None
    r = n / float(h)
    if r < NW_CRITICAL[0][0]:
        return None
    if r >= NW_CRITICAL[-1][0]:
        return NW_CRITICAL[-1][1]
    for (r0, c0), (r1, c1) in zip(NW_CRITICAL, NW_CRITICAL[1:]):
        if r0 <= r <= r1:
            w = (math.log(r) - math.log(r0)) / (math.log(r1) - math.log(r0))
            return math.exp(math.log(c0) + w * (math.log(c1) - math.log(c0)))
    return None
