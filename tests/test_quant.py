"""Quant signals (tto/quantmath.py, tto/quantfam.py, tto/quant.py): every statistic on synthetic series whose answer is
known, every family's signal on a planted pattern, the common signal format, the ranking, the signal log and the alerts,
then the service and the HTTP API on a synthetic two-year history."""
from __future__ import annotations

import datetime as dt
import math
import random
import threading

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quantfam as qf
from tto import quantmath as qm
from tto.quant import DEFAULTS, HISTORY_DAYS, Quant, series_specs
from tto.server import create_app
from tto.store import Store

TODAY = dt.date(2026, 11, 3)
DAYS = quant_synth.business_days(TODAY, 520)
OIS_MONTHS = {"OIS:1M": 1.0, "OIS:3M": 3.0, "OIS:6M": 6.0, "OIS:9M": 9.0, "OIS:1Y": 12.0, "OIS:18M": 18.0, "OIS:2Y": 24.0, "OIS:3Y": 36.0,
              "OIS:4Y": 48.0, "OIS:5Y": 60.0, "OIS:7Y": 84.0, "OIS:10Y": 120.0}


def cfg(**kw):
    out = dict(DEFAULTS)
    out.update(kw)
    return out


def ar1(n, b, sd, rnd, x0=0.0):
    out, x = [], x0
    for _ in range(n):
        x = b * x + rnd.gauss(0, sd)
        out.append(x)
    return out


def walk(n, sd, rnd, x0=0.0, drift=0.0):
    out, x = [], x0
    for _ in range(n):
        x += drift + rnd.gauss(0, sd)
        out.append(x)
    return out


def ctx_of(series, meta, today=TODAY, **kw):
    settings = cfg(**kw.pop("settings", {}))
    return qf.Ctx(settings, today, series, meta, **kw)


def synth_ctx(**kw):
    days, data = quant_synth.build(TODAY, OIS_MONTHS, 520, 11, **kw)
    meta = {}
    for k in data:
        if k.startswith("OIS:"):
            meta[k] = {"label": k[4:] + " OIS", "kind": "rate", "months": OIS_MONTHS[k]}
        elif k.startswith("OFF:"):
            meta[k] = {"label": "Offshore " + k[4:], "kind": "rate", "months": OIS_MONTHS["OIS:" + k[4:]]}
    for s in series_specs():
        meta.setdefault(s["key"], {"label": s["label"], "kind": s["kind"], "group": s["group"]})
    meta["TLREF"] = {"label": "TLREF", "kind": "rate"}
    return qf.Ctx(cfg(), TODAY, data, meta), data


# ================================================================================================ the statistics
def test_rolling_correlation_matches_the_direct_one():
    rnd = random.Random(1)
    xs = [rnd.gauss(0, 1) for _ in range(300)]
    ys = [0.6 * x + rnd.gauss(0, 1) for x in xs]
    roll = qm.rolling_corr(xs, ys, 20)
    assert roll[18] is None
    for i in (19, 77, 299):
        assert abs(roll[i] - qm.corr(xs[i - 19:i + 1], ys[i - 19:i + 1])) < 1e-9


def test_pca_recovers_planted_factors():
    rnd = random.Random(2)
    k = 8
    level = [1.0] * k
    slope = [(i - (k - 1) / 2) / ((k - 1) / 2) for i in range(k)]
    rows = []
    for _ in range(600):
        f1, f2 = rnd.gauss(0, 5), rnd.gauss(0, 2)
        rows.append([f1 * level[i] + f2 * slope[i] + rnd.gauss(0, 0.3) for i in range(k)])
    p = qm.pca(rows)

    def cos(a, b):
        return abs(sum(x * y for x, y in zip(a, b))) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))

    assert cos(p["vectors"][0], level) > 0.999 and cos(p["vectors"][1], slope) > 0.999
    # variances: 25·8 = 200 for the level, 4·Σslope² for the slope, the rest is noise
    assert abs(p["values"][0] / 200.0 - 1) < 0.15 and p["explained"][0] + p["explained"][1] > 0.99
    vals, vecs = qm.jacobi_eigen([[2.0, 1.0], [1.0, 2.0]])
    assert [round(v, 9) for v in vals] == [3.0, 1.0] and abs(abs(vecs[0][0]) - math.sqrt(0.5)) < 1e-9


def test_ou_half_life_is_recovered():
    for b in (0.8, 0.9, 0.95):
        x = ar1(4000, b, 1.0, random.Random(3), 0.0)
        ou = qm.ou_fit([10.0 + v for v in x])
        true = math.log(2) / -math.log(b)
        assert abs(ou["half_life"] / true - 1) < 0.25, (b, ou["half_life"], true)
        assert abs(ou["mu"] - 10.0) < 0.5 and abs(ou["sigma_eq"] / (1 / math.sqrt(1 - b * b)) - 1) < 0.1
    assert qm.ou_fit(walk(500, 1.0, random.Random(4)))["b"] > 0.97          # a random walk barely returns
    trend = [0.01 * i * i for i in range(200)]
    assert qm.ou_fit(trend)["half_life"] is None                          # b ≥ 1: no half-life


def test_cointegrated_pair_with_known_beta_and_half_life():
    rnd = random.Random(5)
    x = walk(700, 1.0, rnd, 100.0)
    e = ar1(700, 0.8, 0.5, rnd)
    y = [3.0 + 1.5 * a + b for a, b in zip(x, e)]
    eg = qm.engle_granger(y, x)
    assert abs(eg["beta"] - 1.5) < 0.03 and eg["passes"] and eg["adf"]["level"] == 1
    hl = qm.ou_fit(eg["resid"])["half_life"]
    assert abs(hl - math.log(2) / -math.log(0.8)) < 1.0
    other = walk(700, 1.0, random.Random(6))
    assert not qm.engle_granger(other, x)["passes"]                       # two random walks: no pair


def test_adf_critical_values_and_decisions():
    crit = qm.mackinnon_crit(1, 10 ** 6)
    assert abs(crit[5] + 2.8615) < 1e-3 and abs(crit[1] + 3.4304) < 1e-3
    assert abs(qm.mackinnon_crit(2, 10 ** 6)[5] + 3.3361) < 1e-3
    assert qm.mackinnon_crit(1, 100)[5] < crit[5]                         # small samples need more
    assert qm.adf(ar1(400, 0.7, 1.0, random.Random(7)))["level"] == 1
    # a random walk is rejected about as often as the level says (5 %), a stationary series practically always
    walks = sum(qm.adf(walk(300, 1.0, random.Random(100 + s)))["level"] in (1, 5) for s in range(80))
    stationary = sum(qm.adf(ar1(300, 0.8, 1.0, random.Random(300 + s)))["level"] in (1, 5) for s in range(20))
    assert walks <= 9 and stationary >= 19


def test_kalman_follows_a_drifting_hedge_ratio():
    rnd = random.Random(9)
    xs, ys, beta = [], [], 1.0
    for _ in range(500):
        beta += 0.01
        x = 10 + rnd.gauss(0, 1)
        xs.append(x)
        ys.append(2.0 + beta * x + rnd.gauss(0, 0.2))
    kf = qm.kalman_beta(ys, xs, 2.0, 1.0, 1.0, 0.04, 1e-4)
    assert abs(kf["post"][-1] - beta) < 0.1 and abs(kf["post"][250] - 3.51) < 0.15
    static = qm.ols(ys, [xs])["coef"][1]
    assert abs(static - 3.5) < 0.6                                        # the static ratio sits in the middle


def test_regime_switch_is_detected():
    rnd = random.Random(10)
    mr = [0.0]
    for c in ar1(600, -0.4, 1.0, rnd):                                    # moves that undo themselves
        mr.append(mr[-1] + c)
    tr = [0.0]
    for c in ar1(600, 0.45, 1.0, rnd):                                    # moves that carry on
        tr.append(tr[-1] + c)
    c = cfg()
    assert qf.regime_of(mr, "bp", c)["tag"] == "MR"
    assert qf.regime_of(tr, "bp", c)["tag"] == "Trend"
    both = mr + [mr[-1] + v - tr[0] for v in tr]                           # the switch: the window sees the last 250 moves
    assert qf.regime_of(both[:400], "bp", c)["tag"] == "MR" and qf.regime_of(both, "bp", c)["tag"] == "Trend"
    h_mr, h_tr = qm.hurst([b - a for a, b in zip(mr, mr[1:])]), qm.hurst([b - a for a, b in zip(tr, tr[1:])])
    assert h_mr < 0.5 < 0.55 < h_tr
    vr = qm.variance_ratio([b - a for a, b in zip(mr, mr[1:])], 10)
    assert vr["vr"] < 0.8 and vr["z"] < -3


def test_garch_ewma_and_logistic_fits():
    rnd = random.Random(12)
    r, v = [], 1.0
    for _ in range(800):
        eps = rnd.gauss(0, 1) * math.sqrt(v)
        r.append(eps)
        v = 0.05 + 0.1 * eps * eps + 0.85 * v
    g = qm.garch_fit(r)
    assert abs(g["alpha"] - 0.1) < 0.06 and abs(g["beta"] - 0.85) < 0.08 and g["alpha"] + g["beta"] < 1
    avg = qm.garch_avg_var(5.0, g, 63)
    assert g["long_var"] < avg < 5.0                                       # a high variance decays toward the long run
    ew = qm.ewma_var(r, 0.94)
    assert ew[0] is None and ew[-1] > 0
    xs, ys = [], []
    for _ in range(600):
        a, b = rnd.gauss(0, 1), rnd.gauss(0, 1)
        xs.append([a, b])
        ys.append(1 if rnd.random() < qm.logistic(1.5 * a - 1.0 * b) else 0)
    w = qm.logistic_fit(xs, ys, 0.1)
    assert abs(w[1] - 1.5) < 0.35 and abs(w[2] + 1.0) < 0.3
    assert qm.log_loss([0.5, 0.5], [1, 0]) == pytest.approx(math.log(2))
    nw = qm.newey_west([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 2)
    assert nw["mean"] == 5.5 and nw["t"] > 0


# ================================================================================================ the families
def test_correlation_break_signal():
    rnd = random.Random(13)
    a = walk(520, 0.05, rnd, 30.0)
    da = [y - x for x, y in zip(a, a[1:])]
    db = [0.9 * d + rnd.gauss(0, 0.02) for d in da[:-20]] + [rnd.gauss(0, 0.05) for _ in range(20)]     # coupled, then not
    b = [4.0]
    for d in db:
        b.append(b[-1] + d)
    series = {"OIS:2Y": dict(zip(DAYS, a)), "UST:10Y": dict(zip(DAYS, b))}
    meta = {"OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0}, "UST:10Y": {"label": "UST 10Y", "kind": "rate"}}
    mons, table = qf.fam_corr(ctx_of(series, meta))
    row = table["pairs"][0]
    assert row["long"] > 0.6 and row["z"] < -3 and row["c"]["20"] < 0.5
    m = next(x for x in mons if x.sid == "corr:OIS:2Y|UST:10Y")
    m.score({}, {})
    assert abs(m.z - row["z"]) < 1e-9
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["expression"].startswith("Korelasyon normale döner") and s["unit"] == "ρ" and s["target"] > s["entry"]


def test_pca_residual_marks_the_planted_cheap_tenor():
    ctx, _ = synth_ctx(shock=3.0)
    fit = qf.pca_fit(ctx)
    assert fit["explained"][0] > 0.6
    mons, table = qf.fam_pca(ctx, fit)
    for m in mons:
        m.score({}, {})
    by = {m.sid: m for m in mons}
    planted = by["pca:OIS:2Y"]
    assert planted.z > 2.0 and planted.z == max(m.z for m in mons)
    s = qf.make_signal(planted, cfg(), "10:00")
    assert s["expression"].startswith("Receive 2Y OIS") and s["direction"] == -1 and s["target"] < s["entry"] < s["stop"]
    # the hedge legs make the package neutral to PC1 and PC2 of the levels (the directions the curve moved in)
    e = fit["lvl_vectors"]
    idx = {k: i for i, k in enumerate(fit["keys"])}
    for f in (0, 1):
        assert abs(sum(leg["weight"] * e[f][idx[leg["key"]]] for leg in planted.legs)) < 1e-9
    assert 0 < planted.half_life < 20


def _curve(n, seed, shape=None, slope_of=None, trend=0.0, beta=None):
    """OIS levels: a random-walk level (flat) and slope, an optional steady trend along beta (a cycle)."""
    rnd = random.Random(seed)
    labels = ["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y"]
    months = [1, 3, 6, 12, 24, 36, 60, 120]
    beta = beta or [1.6, 1.5, 1.4, 1.25, 1.0, 0.85, 0.7, 0.6]
    days = DAYS[-n:]
    lv, sl = 0.0, 0.0
    lev = {x: [] for x in labels}
    for i in range(n):
        lv += rnd.gauss(0, 0.05)
        sl += rnd.gauss(0, 0.02)
        shape_i = slope_of(i) if slope_of else [(math.log(m) - math.log(8)) / 2.0 for m in months]
        for j, x in enumerate(labels):
            lev[x].append(30.0 - trend * i * beta[j] + lv + sl * shape_i[j] + rnd.gauss(0, 0.01))
    series = {"OIS:" + x: dict(zip(days, lev[x])) for x in labels}
    meta = {"OIS:" + x: {"label": x + " OIS", "kind": "rate", "months": float(m)} for x, m in zip(labels, months)}
    return ctx_of(series, meta)


def test_dynamic_pca_windows_stability_and_level_residuals():
    ctx, _ = synth_ctx(shock=3.0)
    fit = qf.pca_fit(ctx)
    assert set(fit["windows"]) == {60, 120, 250} and fit["window"] == 250
    st = {r["pc"]: {(x["a"], x["b"]): x for x in r["pairs"]} for r in fit["stability"]}
    assert st[1][(120, 250)]["cos"] > 0.95 and st[1][(60, 250)]["max_move"] < 0.2      # the level is the same shape in every window
    mons, table = qf.fam_pca(ctx, fit)
    planted = next(m for m in mons if m.sid == "pca:OIS:2Y")
    assert planted.info["window"] == 250 and set(planted.info["z_windows"]) == {60, 120} and table["window"] == 250
    planted.score({}, {})
    s = qf.make_signal(planted, cfg(), "10:00")
    assert "250 günlük pencere" in s["thesis"] and "120 günde z" in s["thesis"]
    # the second factor's shape changes in the last 60 days (a twist turns into a bow): PC2 of the 60-day window is not
    # the 250-day one's, PC1 still is
    early = [(math.log(m) - math.log(8)) / 2.0 for m in (1, 3, 6, 12, 24, 36, 60, 120)]
    late = [x * x - 0.8 for x in early]
    ctx2 = _curve(300, 6, slope_of=lambda i: late if i >= 240 else early)
    st2 = {r["pc"]: {(x["a"], x["b"]): x for x in r["pairs"]} for r in qf.pca_fit(ctx2)["stability"]}
    assert st2[1][(60, 250)]["cos"] > 0.95 and st2[2][(60, 250)]["cos"] < 0.9 and st2[2][(60, 250)]["max_move"] > 0.2
    # a cutting cycle moves the curve along its own shape (the short end more): residuals against the change-PCA trend
    # with it (|correlation with time| 1), the packages neutral to the level-PCA do not - no tenor is "rich" or "cheap"
    for seed in (3, 4):
        ctx3 = _curve(300, seed, trend=0.02)
        f3 = qf.pca_fit(ctx3)
        m3, _ = qf.fam_pca(ctx3, f3)
        t_ = list(range(len(f3["rows"])))
        e, xbar, k = f3["vectors"], f3["xbar"], len(f3["keys"])
        old = []
        for j in range(k):
            rs = []
            for r in f3["rows"]:
                d = [(r[i] - xbar[i]) * 100.0 for i in range(k)]
                rs.append(d[j] - sum(qf._proj(e[c], d) * e[c][j] for c in (0, 1)))
            old.append(abs(qm.corr(rs, t_)))
        new = [abs(qm.corr(m.values, t_)) for m in m3]
        for m in m3:
            m.score({}, {})
        assert max(old) > 0.9 and max(new) < 0.2 and max(abs(m.z) for m in m3) < 2.0


def test_pca_neutral_flies_and_spreads():
    ctx, _ = synth_ctx(shock=3.0)
    fit = qf.pca_fit(ctx)
    from tto import volcarry as vc
    items = vc.parse_items("1y2y3y, 2y5y10y, 2y5y")
    mons, table = qf.fam_rv(ctx, fit, items)
    e = fit["vectors"]
    idx = {k: i for i, k in enumerate(fit["keys"])}
    rows = {r["label"]: r for r in table["rows"]}
    fly = rows["1s2s3s PCA ağırlıklı fly"]
    assert [l["key"] for l in fly["legs"] if l["weight"] == 1.0] == ["OIS:2Y"]           # the body
    for f in (0, 1):
        assert abs(sum(l["weight"] * e[f][idx[l["key"]]] for l in fly["legs"])) < 1e-9
    assert all(abs(x) < 1e-6 for x in fly["versions"]["pca"]["exposures"][:2])
    classic = fly["versions"]["klasik"]
    assert classic["name"] == "1s2s3s klasik 50/50 fly" and classic["net_dv01"] == 0.0
    assert sorted(l["weight"] for l in classic["legs"]) == [-0.5, -0.5, 1.0] and "klasik: paralel kaymaya nötr" in fly["compare"]
    spread = rows["2s5s PCA ağırlıklı spread"]
    assert abs(sum(l["weight"] * e[0][idx[l["key"]]] for l in spread["legs"])) < 1e-9
    assert spread["versions"]["klasik"]["name"] == "2s5s 1:1 spread" and spread["versions"]["klasik"]["net_dv01"] == 0.0
    # each leg sized for the main one's 1.000 $ a bp (TRY at USDTRY): its DV01 and the nominal its annuity gives
    tl = DEFAULTS["dv01_usd"] * ctx.usdtry()
    for l in fly["legs"]:
        assert abs(l["dv01"] - l["weight"] * tl) < 1e-6 and abs(l["dv01_usd"] - l["weight"] * DEFAULTS["dv01_usd"]) < 1e-9
        assert l["notional"] == pytest.approx(abs(l["dv01"]) / (qf._annuity(ctx.cur(l["key"]), ctx.months(l["key"])) * 1e-4) / 1e6, rel=1e-12)
    m = next(x for x in mons if x.sid == "rv:fly:1Y/2Y/3Y")
    m.score({}, {})
    assert m.z > 2.0
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["expression"] == "Receive 1s2s3s PCA ağırlıklı fly"
    assert {l["key"]: l["side"] for l in s["legs"]} == {"OIS:1Y": 1, "OIS:2Y": -1, "OIS:3Y": 1}
    k = next(x for x in mons if x.sid == "rv:fly:1Y/2Y/3Y:klasik")
    assert k.family == "rv" and k.info["version"] == "klasik" and k.info["compare"] == fly["compare"]


def test_rationale_finds_past_analogs_and_says_what_undoes_the_signal():
    rnd = random.Random(51)
    sd = 0.05 / math.sqrt(1 - 0.85 ** 2)
    vals = [x * 100.0 for x in ar1(500, 0.85, 0.05, rnd)]               # bp, mean-reverting (half-life ~4 days)
    vals[-1] = 3.0 * sd * 100.0
    days = DAYS[-500:]
    meeting = TODAY + dt.timedelta(days=6)
    ctx = ctx_of({"X": dict(zip(days, vals))}, {"X": {"label": "X", "kind": "bp"}},
                 path={"spot": TODAY, "base": 0.4, "steps": [(meeting, 0.39)], "day": TODAY.isoformat()})
    m = qf.mr_monitor(ctx, "pca:X", "pca", "TRY OIS", "X", "bp", 1, days, vals, "bp", [{"key": "X", "name": "X", "weight": 1.0}],
                      lambda live: vals[-1], pkg="rate")
    m.score({}, {})
    sg = qf.make_signal(m, cfg(), "10:00")
    assert sg["direction"] == -1 and sg["z"] > 2
    r = qf.rationale(ctx, m, sg, cfg())
    sm = r["summary"]
    a = sorted(dt.date.fromisoformat(x["day"]) for x in r["analogs"])
    assert sm["n"] == qf.ANALOG_K and len(a) == qf.ANALOG_K
    assert all(days.index(y.isoformat()) - days.index(x.isoformat()) >= qf.ANALOG_GAP for x, y in zip(a, a[1:]))  # a week apart
    assert sum(x["features"][0] for x in r["analogs"]) / len(a) > 1.0                       # days that sat high too
    assert sm["share"] >= 0.7 and sm["mean"] > 0 and sm["hold"] == round(sg["hold"])   # ... and came back after
    inv = r["invalidation"]
    assert inv[0].startswith("Stop: seviye") and any("Rejim trende dönerse" in x for x in inv)
    assert any(x.startswith("PPK toplantısı %s ufkun içinde" % meeting.strftime("%d.%m.%y")) for x in inv)


def test_classic_and_pca_weighted_packages_with_their_exposures():
    # three tenors, known loadings (PC1 not flat: the short end moves more) and variances (σ 10, 4, 2 bp a day)
    vec = [[0.62, 0.58, 0.53], [-0.70, 0.05, 0.71], [0.35, -0.81, 0.47]]
    values = [100.0, 16.0, 4.0]
    k = qf.rv_weights("fly", [0, 1, 2], vec, "klasik")
    assert k == {1: 1.0, 0: -0.5, 2: -0.5}
    ek = qf.pkg_exposures(k, vec, values)
    assert ek == pytest.approx([(0.58 - 0.31 - 0.265) * 10.0, (0.05 + 0.35 - 0.355) * 4.0, (-0.81 - 0.175 - 0.235) * 2.0])
    p = qf.rv_weights("fly", [0, 1, 2], vec, "pca")
    ep = qf.pkg_exposures(p, vec, values)
    assert p[1] == 1.0 and abs(ep[0]) < 1e-12 and abs(ep[1]) < 1e-12 and abs(ep[2]) > 1.0
    net = sum(p.values()) * 10000.0
    assert abs(net) > 100.0                                                # neutral to the factors, not to a parallel move
    versions = {"klasik": {"exposures": ek, "net_dv01": 0.0}, "pca": {"exposures": ep, "net_dv01": net}}
    line = qf.rv_compare("fly", versions)
    assert line.startswith("klasik: paralel kaymaya nötr (net DV01 0 TL/bp), gizli eğrilik maruziyeti") and "PCA: seviye ve eğime nötr" in line
    assert ("net DV01 %s TL/bp" % qf._g(net, 0)) in line
    s = qf.rv_weights("spread", [0, 2], vec, "klasik")
    assert s == {2: 1.0, 0: -1.0} and qf.pkg_exposures(s, vec, values)[0] == pytest.approx((0.53 - 0.62) * 10.0)
    sp = qf.rv_weights("spread", [0, 2], vec, "pca")
    assert sp == {2: 1.0, 0: pytest.approx(-0.53 / 0.62)} and abs(qf.pkg_exposures(sp, vec, values)[0]) < 1e-12


def test_pairs_scanner_finds_the_cointegrated_basis_and_kalman():
    ctx, _ = synth_ctx(basis_shock=3.0)
    mons, table = qf.fam_pairs(ctx)
    rows = {r["pid"]: r for r in table["rows"]}
    off3 = rows["off:3M"]
    assert off3["passes"] and abs(off3["beta"] - 1.0) < 0.05 and off3["z"] > 2.0 and off3["half_life"] < 10
    m = next(x for x in mons if x.sid == "pairs:off:3M")
    m.score({}, {})
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["legs"][0]["text"].startswith("Receive Offshore 3M") and s["legs"][1]["text"].startswith("Pay 3M OIS")
    assert "k_beta" in off3 and abs(off3["k_beta"] - off3["beta"]) < 0.2
    k = next(x for x in mons if x.sid == "kalman:off:3M")
    k.score({}, {})
    assert k.z > 1.5 and k.info["static_beta"] == off3["beta"]


def test_macro_betas_split_today_into_global_and_try_specific():
    ctx, data = synth_ctx()
    mons, table = qf.fam_macro(ctx)
    row = next(r for r in table["rows"] if r["key"] == "OIS:2Y")
    drivers = table["drivers"]
    betas = dict(zip(drivers, row["betas"]))
    assert abs(betas["CDS"] - quant_synth.BETA_CDS) < 0.15 and abs(betas["UST:10Y"] - quant_synth.BETA_UST10) < 0.2
    assert abs(betas["DXY"]) < 1.5 and row["r2"] > 0.1
    today = row["today"]
    assert abs(today["dy"] - (row["alpha"] + today["global"] + today["resid"])) < 1e-9
    # a TRY-specific jump today (live): 2Y up 30 bp with nothing moving abroad -> a large residual z, receive
    live = {k: ctx.last(k) for k in ["OIS:2Y"] + drivers}
    live["OIS:2Y"] += 0.30
    m = next(x for x in mons if x.sid == "macro:OIS:2Y")
    qf.score_all(ctx, [m], live)
    assert m.z > 3 and qf.make_signal(m, cfg(), "10:00")["expression"] == "Receive 2Y OIS"


def test_momentum_signal_on_a_trend():
    rnd = random.Random(14)
    level = walk(420, 0.04, rnd, 30.0) + []
    for _ in range(100):
        level.append(level[-1] + 0.03 + rnd.gauss(0, 0.01))             # a steady climb: 3 bp a day
    series = {"OIS:2Y": dict(zip(DAYS, level))}
    meta = {"OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0}}
    mons, table = qf.fam_momentum(ctx_of(series, meta))
    m = mons[0]
    m.score({}, {})
    row = table["rows"][0]
    assert m.z > DEFAULTS["mom_entry"] and row["state"] == 1 and row["m3"] > 2
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["expression"] == "Pay 2Y OIS" and s["direction"] == 1 and s["target"] > s["entry"] > s["stop"]
    assert s["gated"] in ("", "rejim ortalamaya dönüş: momentum sinyali sayılmaz") and s["hold"] == DEFAULTS["horizon"]


def test_vol_premium_and_garch_forecast_signals():
    rnd = random.Random(15)
    spot, s = [], 18.0
    for _ in DAYS:
        s *= math.exp(rnd.gauss(0, 0.15 / math.sqrt(252)))
        spot.append(s)
    iv = [17.0 + rnd.gauss(0, 0.3) for _ in DAYS]
    iv[-1] = 26.0                                                         # implied jumps, realized does not
    series = {"FX:USDZAR": dict(zip(DAYS, spot)), "FXV:USDZAR": dict(zip(DAYS, iv)), "FXR:USDZAR": {d: 1.0 + rnd.gauss(0, 0.1) for d in DAYS}}
    meta = {"FX:USDZAR": {"label": "USDZAR", "kind": "fx", "group": "EM"}, "FXV:USDZAR": {"label": "USDZAR ATM 3M vol", "kind": "vol"},
            "FXR:USDZAR": {"label": "USDZAR 25D RR 3M", "kind": "vol"}}
    mons, table = qf.fam_vol(ctx_of(series, meta))
    row = table["rows"][0]
    assert abs(row["rv63"] - 15.0) < 3.5 and row["vrp_z"] > 4 and row["vf_z"] > 4
    assert 0 <= row["garch_fit"]["alpha"] and row["garch_fit"]["alpha"] + row["garch_fit"]["beta"] < 1
    by = {m.sid: m for m in mons}
    for sid in ("volprem:USDZAR", "volfc:USDZAR"):
        by[sid].score({}, {})
        s = qf.make_signal(by[sid], cfg(stop_z=50.0), "10:00")
        assert s["expression"] == "Sell USDZAR 3M ATM vol" and s["legs"][0]["key"] == "FXV:USDZAR"
    sigs = [qf.make_signal(by[sid], cfg(stop_z=50.0, hl_max_mult=10.0), "10:00") for sid in ("volprem:USDZAR", "volfc:USDZAR")]
    qf.rank(sigs)
    assert all(x["agree"] == 1 and x["agree_with"] for x in sigs)        # the realized and the forecast benchmark agree


def test_em_carry_ranking():
    ctx, _ = synth_ctx()
    mons, table = qf.fam_emcarry(ctx)
    order = [r["ccy"] for r in table["rows"]]
    assert order[0] == "TRY" and order[1] == "BRL" and set(order[-2:]) == {"HUF", "PLN"}
    try_row = table["rows"][0]
    assert abs(try_row["carry"] - quant_synth.CARRY["TRY"]) < 1.0
    assert abs(try_row["cv"] - quant_synth.CARRY["TRY"] / (quant_synth.VOL["TRY"] + 2.0)) < 0.5
    assert "rel" in try_row and len(mons) == 1 and mons[0].sid == "emcarry:TRY"


def test_viop_calendar_spread_against_cip_fair_value():
    rnd = random.Random(16)
    days = DAYS[-150:]
    dev = ar1(150, 0.7, 4.0, rnd)
    dev[-1] = 25.0                                                        # bp: the far contract got rich
    near = {"ticker": "A1Z6 Curncy", "name": "Ara 26", "expiry": "2026-12-31", "imp": {}, "ois360": {}, "days": {}, "px": {}, "baz": {}, "live": {}}
    far = {"ticker": "A1H7 Curncy", "name": "Mar 27", "expiry": "2027-03-31", "imp": {}, "ois360": {}, "days": {}, "px": {}, "baz": {}, "live": {}}
    for i, d in enumerate(days):
        g1, g2 = 200.0 - i, 290.0 - i
        ois1, ois2 = 39.0, 38.0
        fwd_ois = qf._fwd(ois1, g1, ois2, g2)
        fwd_imp = fwd_ois + dev[i] / 100.0
        imp1 = ois1 + 0.2
        # the far implied rate that gives this forward
        imp2 = ((1 + imp1 / 100 * g1 / 360) * (1 + fwd_imp / 100 * (g2 - g1) / 360) - 1) * 360 / g2 * 100
        near["imp"][d], near["ois360"][d], near["days"][d] = imp1, ois1, g1
        far["imp"][d], far["ois360"][d], far["days"][d] = imp2, ois2, g2
    ctx = ctx_of({}, {}, viop=[near, far])
    mons, table = qf.fam_viopcal(ctx)
    assert abs(table["rows"][0]["dev"] - 25.0) < 1e-6
    m = mons[0]
    m.score({}, {})
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["z"] > 2 and {l["key"]: l["side"] for l in s["legs"]} == {"VIOPI:A1H7 Curncy": -1, "VIOPI:A1Z6 Curncy": 1}
    assert s["legs"][0]["text"].startswith("Sell VİOP Mar 27") and s["expression"].startswith("Sell VİOP takvim")


def test_fra_path_reproduces_its_quotes_in_the_desk_s_convention():
    spot = dt.date(2026, 11, 5)
    steps = [(dt.date(2026, 12, 11), 0.385), (dt.date(2027, 1, 22), 0.37), (dt.date(2027, 3, 12), 0.355), (dt.date(2027, 6, 10), 0.34)]
    base = 0.395
    hol = set()

    def pdf(d):
        return qf.path_df(spot, base, steps, d, hol)

    quotes = {m: qf.par_rate(spot, pdf, m, hol) for m in qf.PATH_TENORS}          # the path's own par rates, the desk's convention
    # up to 3M one payment, longer quarterly: the 1Y quote is far below the one-payment rate of the same path (the old mismatch)
    end = qf.tenor_end(spot, 12, hol)
    single = (1.0 / pdf(end) - 1.0) * 365.0 / (end - spot).days * 100.0
    assert single - quotes[12] > 3.0                                  # more than 300 bp
    same = qf.frapath_day(spot, base, steps, quotes, hol)
    assert all(abs(v["dev"]) < 0.01 for v in same["tenor"].values())                # the path reproduces the quotes it was solved from
    assert all(abs(v["dev"]) < 0.5 for v in same["fra"].values())                  # ... and the forwards between them
    bumped = dict(quotes)
    bumped[6] += 0.20                                                     # the 6M quote 20 bp too high
    out = qf.frapath_day(spot, base, steps, bumped, hol)
    assert abs(out["tenor"][6]["dev"] - 20.0) < 0.01 and out["fra"]["3x6"]["dev"] > 30 and out["fra"]["6x9"]["dev"] < -30
    # the coming meeting periods: from the day after one decision to the day after the next, the level and the priced step
    first = same["mpc"]["2026-12-11"]
    assert (first["start"], first["end"]) == ("2026-12-12", "2027-01-23") and first["path"] == pytest.approx(38.5) and first["step"] == pytest.approx(-100.0)
    # day by day: the 3x6 deviation mean-reverts and ends 3σ high -> receive the FRA (receive 6M, pay 3M); a deviation inside
    # the solver's tolerance is no signal
    for sd, ok in ((0.03, True), (0.003, False)):
        rnd = random.Random(17)
        noise = ar1(300, 0.7, sd, rnd)
        noise[-1] = 3.0 * sd / math.sqrt(1 - 0.49)
        days = DAYS[-300:]
        series = {"OIS:%s" % lbl: {} for lbl in ("1M", "2M", "3M", "6M", "9M", "1Y")}
        meta = {k: {"label": k[4:] + " OIS", "kind": "rate", "months": {"1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12}[k[4:]]} for k in series}
        values = []
        mdays = {}
        for i, d in enumerate(days):
            sp = dt.date.fromisoformat(d) + dt.timedelta(days=2)
            for m, lbl in zip(qf.PATH_TENORS, ("1M", "2M", "3M", "6M", "9M", "1Y")):
                par = qf.par_rate(sp, lambda x, sp=sp: qf.path_df(sp, base, [], x, set()), m, set())
                series["OIS:" + lbl][d] = par + (noise[i] if m == 6 else 0.0)
            mdays[d] = {"spot": sp.isoformat(), "base": base, "flag": ""}
            values.append({"day": d, "meeting": "2030-01-01", "level": base})
        ctx = ctx_of(series, meta, mpc={"days": mdays, "values": values}, path=None)
        mons, table = qf.fam_frapath(ctx)
        assert table["tenors"] and all(abs(r["dev"]) < 0.01 for r in table["tenors"] if r["months"] != 6)
        m = next(x for x in mons if x.sid == "frapath:3x6")
        m.score({}, {})
        s = qf.make_signal(m, cfg(), "10:00")
        assert s["z"] > 2 and s["expression"].startswith("Receive 3x6 FRA")
        assert {l["key"]: l["side"] for l in s["legs"]} == {"OIS:6M": -1, "OIS:3M": 1}
        if ok:
            assert not s["gated"] and s["exp_pnl"] > 0 and "FRA" in s["thesis"]
        else:
            assert "tolerans" in s["gated"] and s["strength"] == "elendi" and s["composite"] == 0


def test_the_workbook_s_own_path_reproduces_its_quotes():
    """The saved workbook as Excel left it: OIS_MAIN's meeting levels (S10…), the solver's own base (Motor!K4) and the
    quotes (B9:B14, 1M … 1Y): in the convention frapath_day uses the path's par rates are the quotes to a basis point -
    the one-payment reading of the 6M / 9M / 1Y quotes was 1.5 – 5 points off."""
    import os
    from conftest import ROOT
    from tto.xl.model import Model, parse_a1
    from tto.xl.values import serial_to_date
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    ois, motor = model.sheet("OIS_MAIN"), model.sheet("Motor")

    def val(s, ref):
        rc = parse_a1(ref)
        return s.consts.get(rc, s.cached.get(rc))

    spot = serial_to_date(val(ois, "B2"))
    hol = {serial_to_date(v) for v in (val(motor, "A%d" % r) for r in range(361, 524)) if isinstance(v, float) and v > 20000}
    steps = sorted((serial_to_date(val(ois, "P%d" % r)), val(ois, "S%d" % r)) for r in range(10, 90)
                   if isinstance(val(ois, "S%d" % r), float) and isinstance(val(ois, "P%d" % r), float))
    quotes = {m: val(ois, "B%d" % r) * 100.0 for m, r in zip((1, 2, 3, 6, 9, 12), range(9, 15))}
    assert [val(motor, "B%d" % r) for r in range(325, 331)] == [float((qf.tenor_end(spot, m, hol) - spot).days) for m in (1, 2, 3, 6, 9, 12)]
    out = qf.frapath_day(spot, val(motor, "K4"), steps, quotes, hol)
    # the workbook's own par rates of its solved path (Motor!K325:K330) to a twentieth of a basis point - the same convention
    for m, r in zip((1, 2, 3, 6, 9, 12), range(325, 331)):
        assert abs(out["tenor"][m]["path"] - val(motor, "K%d" % r) * 100.0) < 0.05, (m, out["tenor"][m])
    # and so the quotes, to the solver's own fit (its 1M is 2 bp off in the workbook too)
    assert len(out["tenor"]) == 6 and all(abs(v["dev"]) < 2.5 for v in out["tenor"].values()), out["tenor"]
    assert sum(abs(v["dev"]) for m, v in out["tenor"].items() if m > 1) < 0.5


# ================================================================================================ FX: carry inside
def fx_series(pair="USDTRY", mu=0.20, carry=0.30, vol=0.01, n=520, seed=31, tenors=("1M", "3M"), s0=34.0, group="TRY", points=True):
    """A spot with a known drift (log, a year of 252 days) and vol, and forward points built from a known carry (the
    forward above the spot by ``carry`` a year, continuously compounded)."""
    rnd = random.Random(seed)
    days = DAYS[-n:]
    s = s0
    spot = []
    for _ in days:
        s *= math.exp(mu / 252.0 + rnd.gauss(0, vol / math.sqrt(252.0)))
        spot.append(s)
    series = {"FX:" + pair: dict(zip(days, spot))}
    meta = {"FX:" + pair: {"label": pair, "kind": "fx", "group": group}}
    if points:
        for t in tenors:
            dd = qf._tenor_days(t)
            series["FXP:%s:%s" % (pair, t)] = {d: (v * math.exp(carry * dd / 365.0) - v) * 1e4 for d, v in zip(days, spot)}
            meta["FXP:%s:%s" % (pair, t)] = {"label": "%s %s swap puanı" % (pair, t), "kind": "pts"}
    return series, meta


def test_fx_excess_return_takes_the_carry_out():
    # USDTRY: a crawl of 20 % a year against forwards that price 30 %: long USDTRY loses about 10 % a year of carry
    series, meta = fx_series()
    ctx = ctx_of(series, meta)
    assert ctx.fx_carry("USDTRY") == pytest.approx(-30.0, abs=1e-6)              # a long pays the TRY rate
    assert ctx.fx_carry("USDTRY", days=60.0) == pytest.approx(-30.0, abs=1e-6)
    xr = [v for _, v in ctx.pts("XR:USDTRY")]
    per_year = (xr[-1] - xr[0]) / (len(xr) - 1) * 252.0
    assert -14.0 < per_year < -6.0                                                # the excess return of a long: −10 % a year
    ol = qf.fx_outlook(ctx, "USDTRY")
    assert ol["carry_long"] == pytest.approx(-30.0, abs=1e-6) and 8.0 < ol["drift"] < 30.0 and ol["exp_long"] < -2.0
    assert ol["buffer"] > 2.0 and ol["carry_side"] == -1 and ol["verdict"] == "TRY long"
    # momentum on the excess return: the crawl does not make a "buy USDTRY"; the excess return falls - sell, with carry
    mons, table = qf.fam_momentum(ctx)
    assert "momentum:FX:USDTRY" not in {m.sid for m in mons}
    m = next(x for x in mons if x.sid == "momentum:XR:USDTRY")
    qf.score_all(ctx, [m], {})
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["expression"] == "Sell USDTRY forward" and s["direction"] == -1 and s["legs"][0]["key"] == "FX:USDTRY"
    assert s["carry_yr"] == pytest.approx(30.0, abs=1e-6) and s["carry_week"] == pytest.approx(30.0 * 7 / 365, abs=1e-6)
    assert s["exp_pnl"] > 0 and s["pnl_unit"] == "%" and s["pnl_try"] == pytest.approx(s["exp_pnl"] / 100 * 1e6 * ctx.last("FX:USDTRY"))
    carry_gate = next(g for g in s["gates"] if g["name"] == "Carry")
    assert carry_gate["ok"] and "lehte" in carry_gate["text"] and "carry" in s["thesis"]
    row = next(r for r in table["rows"] if r["key"] == "XR:USDTRY")
    assert row["carry"] == pytest.approx(-30.0, abs=1e-6) and row["score"] < -1.5
    # a pair without forwards: its spot alone is no trade - told so, no carry made up
    s2, m2 = fx_series("USDKRW", mu=0.0, vol=0.08, s0=1400.0, group="EM", points=False, seed=32)
    series.update(s2)
    meta.update(m2)
    ctx = ctx_of(series, meta)
    assert ctx.fx_carry("USDKRW") is None and "XR:USDKRW" not in ctx.series
    mons, table = qf.fam_momentum(ctx)
    assert not [m for m in mons if "USDKRW" in m.sid]
    assert next(r for r in table["rows"] if r["key"] == "FX:USDKRW")["error"].startswith("forward yok")
    assert qf.fx_outlook(ctx, "USDKRW")["verdict"] == "forward yok"


def _fx_mon(z, fcast, carry_yr=-30.0):
    m = qf.Monitor("momentum:XR:USDTRY", "momentum", "FX", "USDTRY forward", "%", 3, DAYS[-200:], [0.0] * 200,
                   [{"key": "FX:USDTRY", "name": "USDTRY forward", "weight": 1.0}], lambda live: 0.0, follows=True, mode="drift", entry=1.5,
                   reward=1.0, risk=1.0, hold=20.0, regime={"tag": "Trend"}, pkg="fx", fx="USDTRY", dsd=0.1, pnl=("%", 1.0), fcast=fcast)
    m.zfn = lambda level, live, z=z: z
    m.score({}, {})
    m.level = 0.0
    m.fxinfo = {"pair": "USDTRY", "spot": 34.0, "carry_yr": carry_yr, "carry_h_yr": carry_yr, "cal_days": 28.0, "try_per_quote": 1.0,
                "tenors": ["1M"], "fwd_h": 34.0 * math.exp(-carry_yr * 28.0 / 365.0 / 100.0)}
    return m


def test_a_trade_against_carry_needs_an_expected_move_that_beats_it():
    margin = 0.5 * 0.1 * math.sqrt(20.0)                                  # half the holding's σ (the desk's tampon)
    # buy USDTRY: against the carry; an expected excess return (carry already in it) above the margin passes
    s = qf.make_signal(_fx_mon(2.5, 0.40), cfg(), "10:00")
    g = next(x for x in s["gates"] if x["name"] == "Carry")
    assert s["direction"] == 1 and s["carry_h"] == pytest.approx(-30.0 * 28 / 365) and g["ok"] and "aleyhte" in g["text"] and not s["gated"]
    assert s["exp_pnl"] == pytest.approx(0.40) and s["pnl_try"] == pytest.approx(0.004 * 1e6 * 34.0)
    # ... one below it is held back: carry'yi karşılamıyor, "elendi", no composite
    s = qf.make_signal(_fx_mon(2.5, 0.5 * margin), cfg(), "10:00")
    assert "carry'yi karşılamıyor" in s["gated"] and s["strength"] == "elendi" and s["composite"] == 0.0
    assert not next(x for x in s["gates"] if x["name"] == "Carry")["ok"]
    # selling USDTRY earns the carry: no extra hurdle, only an expected profit
    s = qf.make_signal(_fx_mon(-2.5, -0.05), cfg(), "10:00")
    assert s["direction"] == -1 and s["carry_yr"] == pytest.approx(30.0) and not s["gated"] and s["exp_pnl"] == pytest.approx(0.05)
    # without a forward the carry is unknown: no FX trade
    m = _fx_mon(2.5, 1.0)
    m.fxinfo = {"pair": "USDTRY"}
    assert "forward yok" in qf.make_signal(m, cfg(), "10:00")["gated"]


def test_fx_pair_summary_tells_carry_drift_buffer_and_verdict():
    series, meta = fx_series()
    for pair, mu, carry, vol, s0, seed in (("USDZAR", 0.0, 0.07, 0.15, 18.0, 33), ("EURUSD", 0.0, -0.015, 0.07, 1.15, 34)):
        s, m = fx_series(pair, mu=mu, carry=carry, vol=vol, s0=s0, seed=seed, tenors=("3M",), group="EM" if pair == "USDZAR" else "G10")
        series.update(s)
        meta.update(m)
    series["FXV:USDZAR"] = {d: 15.0 for d in DAYS}
    meta["FXV:USDZAR"] = {"label": "USDZAR ATM 3M vol", "kind": "vol"}
    ctx = ctx_of(series, meta)
    rows = {r["pair"]: r for r in qf.fx_summary(ctx)}
    assert list(rows)[0] == "USDTRY" and rows["USDTRY"]["verdict"] == "TRY long" and set(rows["USDTRY"]["term"]) == {"1M", "3M"}
    z = rows["USDZAR"]
    # a free float without a drift: the drift is shrunk towards 0, the carry is what is left; ZAR's 7 % against a 15 % vol
    assert z["carry_long"] == pytest.approx(-7.0, abs=1e-6) and abs(z["drift"]) < 6.0 and z["vol_src"] == "ATM 3M" and z["vol"] == 15.0
    assert z["buffer"] == pytest.approx(-z["exp_long"]) and z["verdict"] in ("ZAR long", "nötr")
    e = rows["EURUSD"]
    assert e["carry_long"] == pytest.approx(1.5, abs=1e-6) and e["focus"] == "EUR" and e["verdict"] in ("nötr", "EUR long")


def test_every_signal_carries_its_decision():
    def mon(carry):
        m = qf.Monitor("pca:OIS:2Y", "pca", "TRY OIS", "2Y OIS (PC1–PC2 hedge'li)", "bp", 1, DAYS[-200:], [0.0] * 200,
                       [{"key": "OIS:2Y", "name": "2Y OIS", "weight": 1.0}], lambda live: 0.0, mean=0.0, sd=1.0, half_life=5.0,
                       regime={"tag": "MR"}, carry_up=carry, pkg="rate", dsd=0.4, pnl=("bp", 1.0))
        m.zfn = lambda level, live: 3.0
        m.score({}, {})
        m.level = 3.0
        return m

    hold = 5.0 * math.log(6, 2)
    back = 3.0 * (1.0 - 0.5 ** (hold / 5.0))                             # OU: the share of the gap closed in the holding
    s = qf.make_signal(mon(-1.0), cfg(usdtry=40.0), "10:00")              # receive 2Y, which also earns 1 bp a week
    assert s["direction"] == -1 and s["hold"] == pytest.approx(hold) and s["carry_week"] == pytest.approx(1.0)
    assert s["exp_pnl"] == pytest.approx(back + hold / 5.0) and s["pnl_unit"] == "bp" and s["pnl_try"] == pytest.approx(s["exp_pnl"] * 1000.0 * 40.0)   # 1.000 $ a bp at 40
    assert s["reward"] == pytest.approx(3.0) and s["risk"] == pytest.approx(0.5) and s["rr"] == pytest.approx(6.0)
    assert s["sigma_h"] == pytest.approx(0.4 * math.sqrt(hold))
    assert [g["name"] for g in s["gates"]] == ["Eşik", "Stop bölgesi", "Rejim", "Yarı ömür", "Carry", "Beklenen kâr"] and all(g["ok"] for g in s["gates"])
    assert s["strength"] == "Güçlü" and "Receive 2Y OIS" in s["thesis"] and "beklenen" in s["thesis"]
    # the same signal paying more carry than the reversion is worth: no expected profit, eliminated - and said so
    s = qf.make_signal(mon(1.5), cfg(), "10:00")
    assert s["exp_pnl"] < 0 and "beklenen kâr yok" in s["gated"] and s["strength"] == "elendi"
    assert [g["name"] for g in s["gates"] if not g["ok"]] == ["Beklenen kâr"]
    live, gated = qf.rank([s])
    assert not live and gated[0]["strength"] == "elendi"


def test_policy_cycle_holds_a_small_sample_to_its_own_critical_value():
    # the critical values: many independent periods tend to 1.96; two of them need a t near 8 (simulated on random walks)
    assert qm.nw_critical(30, 20) is None and qm.nw_critical(40, 20) == pytest.approx(7.8)
    assert qm.nw_critical(200, 20) == pytest.approx(3.0) and qm.nw_critical(20000, 20) == pytest.approx(1.96)
    cvs = [qm.nw_critical(n, 20) for n in range(40, 2000, 40)]
    assert all(a >= b for a, b in zip(cvs, cvs[1:]))
    rnd = random.Random(41)
    ts = []
    for _ in range(400):                                                  # the 5 % value holds on random walks (r = 4)
        e = [rnd.gauss(0, 1) for _ in range(50)]
        x = [sum(e[i:i + 10]) for i in range(40)]
        ts.append(abs(qm.newey_west(x, 9)["t"]))
    rej = sum(1 for t in ts if t > qm.nw_critical(40, 10)) / len(ts)
    assert rej < 0.10 and sum(1 for t in ts if t > 1.96) / len(ts) > 0.2  # (1.96 would find a drift in noise a third of the time)
    # a short cutting phase (~2.4 periods): a t of ~5 is no signal; the same drift over a long phase is
    for start, signal in ((470, False), (200, True)):
        rnd = random.Random(42)
        tl, two, ten = [], [], []
        lvl, slope = 45.0, 0.0
        for i in range(520):
            cutting = i >= start
            if cutting and i % 20 == 0:
                lvl -= 1.0
            tl.append(lvl)
            slope += (0.02 if cutting else 0.0) + rnd.gauss(0, 0.01)
            two.append(40.0 + rnd.gauss(0, 0.01))
            ten.append(two[-1] + slope)
        series = {"TLREF": dict(zip(DAYS, tl)), "OIS:2Y": dict(zip(DAYS, two)), "OIS:10Y": dict(zip(DAYS, ten))}
        meta = {"TLREF": {"label": "TLREF", "kind": "rate"}, "OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0},
                "OIS:10Y": {"label": "10Y OIS", "kind": "rate", "months": 120.0}}
        mons, table = qf.fam_cycle(ctx_of(series, meta))
        row = next(r for r in table["rows"] if r["slope"] == "2s10s")
        st = row["stats"]["indirim"]
        for m in mons:
            m.score({}, {})
        sigs = [qf.make_signal(m, cfg(), "10:00") for m in mons if m.sid == "cycle:2s10s"]
        if signal:
            assert st["periods"] > 10 and st["cv"] < 3.1 and sigs and sigs[0] and sigs[0]["expression"] == "Steepener 2s10s"
            assert next(g for g in sigs[0]["gates"] if g["name"] == "Örneklem")["ok"] and sigs[0]["exp_pnl"] > 0
        else:
            assert st["periods"] < 3 and (st["cv"] is None or st["cv"] > 5) and not [s for s in sigs if s]


# ================================================================================================ the pairs
def test_more_pairs_with_their_tickers_and_a_list_the_desk_keeps():
    from tto.quant import fx_pair_list, history_defs, parse_pairs
    specs = {s["key"]: s for s in series_specs()}
    pairs = [k[3:] for k in specs if k.startswith("FX:")]
    assert pairs[0] == "USDTRY" and {"GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "USDCNH", "USDCZK", "USDKRW", "USDCLP", "USDILS", "GBPTRY"} <= set(pairs)
    tick = {k: s["ticker"] for k, s in specs.items()}
    assert tick["FXP:GBPUSD:3M"] == "GBP3M Curncy" and tick["FXP:USDJPY:3M"] == "JPY3M Curncy" and tick["FXP:GBPTRY:3M"] == "GBPTRY3M Curncy"
    assert tick["FXP:EURUSD:3M"] == "EUR3M Curncy" and tick["FXV:USDCNH"] == "USDCNHV3M BGN Curncy" and tick["FXR:USDILS"] == "USDILS25R3M BGN Curncy"
    assert {"FXP:USDTRY:1M", "FXP:USDTRY:6M", "FXP:USDTRY:1Y"} <= set(specs) and "FXV:GBPTRY" not in specs and "FXV:EURTRY" not in specs
    assert specs["FX:GBPUSD"]["group"] == "G10" and specs["FX:USDKRW"]["group"] == "EM" and specs["FX:GBPTRY"]["group"] == "TRY"
    assert parse_pairs("eurusd; usdtry, USD/MXN") == ["USDTRY", "EURUSD", "USDMXN"]
    for bad in ("USDTR", "USD1RY", "USDUSD"):
        with pytest.raises(ValueError):
            parse_pairs(bad)
    q = Quant(_Svc())
    q.svc.history = type("H", (), {"kick": lambda self: None})()
    out = q.set_settings("ayse", {"fx_pairs": "EURUSD, USDNOK"})
    assert out["values"]["fx_pairs"] == "USDTRY, EURUSD, USDNOK" and fx_pair_list(q.store) == ["USDTRY", "EURUSD", "USDNOK"]
    assert q.svc.nudged >= 1                                              # the history reads its list again (bump)
    defs = history_defs("BGN", fx_pair_list(q.store))
    assert {d.ticker for d in defs} >= {"USDNOK Curncy", "NOK3M Curncy", "USDNOKV3M BGN Curncy"} and "GBPUSD Curncy" not in {d.ticker for d in defs}
    assert all("tail" not in d.info and d.info["backfill"] is True for d in defs)       # (new days every sync, as the desk keeps it)
    with pytest.raises(Exception):
        q.set_settings("ayse", {"fx_pairs": "EURUSD, XX"})


def test_curve_signal_conditioned_on_the_policy_cycle():
    rnd = random.Random(18)
    tl, slope, lvl = [], [], 45.0
    two, ten = [], []
    for i in range(520):
        cutting = 100 <= i < 220 or i >= 420
        if cutting and i % 20 == 0:
            lvl -= 1.0
        tl.append(lvl)
        s = (slope[-1] if slope else 0.0) + (0.02 if cutting else -0.004) + rnd.gauss(0, 0.01)
        slope.append(s)
        two.append(40.0 + rnd.gauss(0, 0.01))
        ten.append(two[-1] + s)
    series = {"TLREF": dict(zip(DAYS, tl)), "OIS:2Y": dict(zip(DAYS, two)), "OIS:10Y": dict(zip(DAYS, ten)),
              "OIS:1Y": dict(zip(DAYS, [x + 0.5 for x in two]))}
    meta = {"TLREF": {"label": "TLREF", "kind": "rate"}, "OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0},
            "OIS:10Y": {"label": "10Y OIS", "kind": "rate", "months": 120.0}, "OIS:1Y": {"label": "1Y OIS", "kind": "rate", "months": 12.0}}
    phases = qf.cycle_phases(sorted(series["TLREF"].items()), 63, 100.0)
    assert phases[DAYS[180]] == "indirim" and phases[DAYS[350]] == "sabit"
    mons, table = qf.fam_cycle(ctx_of(series, meta))
    assert table["phase"] == "indirim"
    row = next(r for r in table["rows"] if r["slope"] == "2s10s")
    assert row["stats"]["indirim"]["mean"] > 20 and row["stats"]["indirim"]["t"] > 2 and row["stats"]["sabit"]["mean"] < 0
    m = next(x for x in mons if x.sid == "cycle:2s10s")
    m.score({}, {})
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["expression"] == "Steepener 2s10s" and {l["key"]: l["side"] for l in s["legs"]} == {"OIS:10Y": 1, "OIS:2Y": -1}


def test_forward_premium_carry_timing_and_its_regime_gate():
    rnd = random.Random(19)
    spot, s = [], 34.0
    for _ in DAYS:
        s *= math.exp(0.20 / 252 + rnd.gauss(0, 0.015 / math.sqrt(252)))     # a quiet, steady depreciation of 20 % a year
        spot.append(s)
    implied = [30.0 + rnd.gauss(0, 0.5) for _ in DAYS]
    implied[-1] = 45.0                                                    # the forward suddenly prices much more depreciation
    pts = [sp * im / 100.0 * 91.25 / 365.0 * 1e4 for sp, im in zip(spot, implied)]
    series = {"FX:USDTRY": dict(zip(DAYS, spot)), "FXP:USDTRY:3M": dict(zip(DAYS, pts))}
    meta = {"FX:USDTRY": {"label": "USDTRY", "kind": "fx"}, "FXP:USDTRY:3M": {"label": "USDTRY 3M swap puanı", "kind": "pts"}}
    ctx = ctx_of(series, meta)
    mons, table = qf.fam_fwdprem(ctx, None)
    row = table["rows"][0]
    assert row["tenor"] == "3M" and abs(row["implied"] - 45.0) < 0.5 and row["z"] > 3
    m = mons[0]
    qf.score_all(ctx, [m], {})
    s = qf.make_signal(m, cfg(stop_z=20.0), "10:00")
    assert s["expression"] == "Sell USDTRY 3M forward" and not s["gated"]
    # selling the forward earns its premium less the drift: carry with the trade, the cushion over the holding expected
    assert s["carry_yr"] > 30.0 and s["exp_pnl"] == pytest.approx(m.level * s["hold"] * 7 / 5 / 365) and "tampon" in s["thesis"]
    mons, _ = qf.fam_fwdprem(ctx, {"regime": "Trend", "score": 2.5})
    qf.score_all(ctx, [mons[0]], {})
    s = qf.make_signal(mons[0], cfg(stop_z=20.0), "10:00")
    assert "trend" in s["gated"] and s["composite"] == 0


def test_model_walk_forward_validates_and_cannot_look_ahead():
    # an OU with a three-day half-life: next week's direction is about 70 % predictable from where it stands
    rnd = random.Random(20)
    ou = [30.0 + x for x in ar1(700, 0.8, 0.05, rnd)]
    rw = walk(700, 0.05, rnd, 30.0)
    days = quant_synth.business_days(TODAY, 700)
    series = {"OIS:2Y": dict(zip(days, ou)), "OIS:5Y": dict(zip(days, rw))}
    meta = {"OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0}, "OIS:5Y": {"label": "5Y OIS", "kind": "rate", "months": 60.0}}
    mons, table = qf.fam_model(ctx_of(series, meta))
    rows = {r["key"]: r for r in table["rows"]}
    assert rows["OIS:2Y"]["valid"] and rows["OIS:2Y"]["hit_rate"] >= 0.55 and rows["OIS:2Y"]["log_loss"] < math.log(2)
    assert not rows["OIS:5Y"]["valid"] and rows["OIS:5Y"]["n_test"] >= 40
    assert [m.sid for m in mons] == ["model:OIS:2Y"]
    m = mons[0]
    m.score({}, {})
    assert m.z == pytest.approx((m.info["p"] - 0.5) / 0.05)
    # no look-ahead: what happens after a test day does not change that day's prediction
    feats = qf.model_features(ou, "rate", [None] * len(ou))
    labels = [None if c == 0 else int(c > 0) for c in (qf.change("rate", ou[t], ou[t + 5]) for t in range(len(ou) - 5))] + [None] * 5
    wf = qf.walk_forward(feats, labels, 250, 120, 5.0)
    t0 = wf["tests"][10][0]
    future = ou[:t0 + 1] + [v + 5.0 for v in ou[t0 + 1:]]                 # the future rewritten
    feats2 = qf.model_features(future, "rate", [None] * len(future))
    labels2 = [None if c == 0 else int(c > 0) for c in (qf.change("rate", future[t], future[t + 5]) for t in range(len(future) - 5))] + [None] * 5
    wf2 = qf.walk_forward(feats2, labels2, 250, 120, 5.0)
    before = {t: p for t, p, _ in wf["tests"] if t <= t0}
    after = {t: p for t, p, _ in wf2["tests"] if t <= t0}
    assert before == after and len(before) == 11


# ================================================================================================ the signal format, ranking, log
def _mon(sid, family, z, regime="MR", hl=5.0, carry=None, legs=None, entry=None, mode="mr", follows=False):
    days = DAYS[-200:]
    values = [math.sin(i / 7.0) for i in range(200)]
    m = qf.Monitor(sid, family, "TRY OIS", sid, "bp", 1, days, values, legs or [{"key": "OIS:2Y", "name": "2Y OIS", "weight": 1.0}],
                   lambda live: 0.0, mean=0.0, sd=1.0, half_life=hl, regime={"tag": regime}, carry_up=carry, pkg="rate", entry=entry, mode=mode,
                   follows=follows, reward=1.0, risk=0.5)
    m.zfn = lambda level, live, z=z: z
    m.score({}, {})
    m.level = z                                                           # the level: z standard deviations from a mean of 0
    return m


def test_signal_format_composite_and_agreement():
    c = cfg()
    mons = [_mon("a", "pca", 3.0, carry=1.0), _mon("b", "pairs", -2.5, hl=10.0), _mon("c", "rv", 2.2, regime="Trend"),
            _mon("d", "pairs", 2.4, hl=100.0, legs=[{"key": "OIS:5Y", "name": "5Y OIS", "weight": 1.0}]),
            _mon("e", "momentum", -2.0, regime="Trend", entry=1.5, mode="drift", follows=True), _mon("f", "pca", 1.5),
            _mon("g", "rv", 3.8)]
    sigs = [s for s in (qf.make_signal(m, c, "10:00") for m in mons) if s]
    assert [s["id"] for s in sigs] == ["a", "b", "c", "d", "e", "g"]             # f is below the entry threshold
    need = {"family", "family_label", "asset", "instrument", "expression", "legs", "direction", "z", "strength", "entry", "target", "stop",
            "half_life", "hold", "carry_week", "regime", "agree", "conflict", "composite", "parts", "time", "gated", "live"}
    assert all(need <= set(s) for s in sigs)
    by = {s["id"]: s for s in sigs}
    # a: z 3 against receive carry (carry_up +1, the trade receives): × 0.5; strength by |z| / entry
    assert by["a"]["direction"] == -1 and by["a"]["carry_week"] == -1.0 and by["a"]["composite"] == pytest.approx(1.5) and by["a"]["strength"] == "Güçlü"
    assert by["a"]["target"] == pytest.approx(0.0) and by["a"]["stop"] == pytest.approx(3.5) and by["a"]["hold"] == pytest.approx(5.0 * math.log(6, 2))
    # b: half-life 10 ≤ horizon 20: no penalty; strength
    assert by["b"]["composite"] == pytest.approx(2.5) and by["b"]["strength"] == "Orta" and by["b"]["expression"] == "Pay b"
    assert "trend" in by["c"]["gated"] and by["c"]["composite"] == 0                # a mean-reversion signal in a trend
    assert "yarı ömür" in by["d"]["gated"]                                           # half-life beyond twice the horizon
    assert by["e"]["direction"] == -1 and by["e"]["parts"]["z"] == pytest.approx(2.0 * 2.0 / 1.5) and by["e"]["composite"] > 0
    assert "stop" in by["g"]["gated"]                                                # past the stop already: not a new entry
    live, gated = qf.rank(sigs)
    assert [s["id"] for s in live] == ["e", "b", "a"] and {s["id"] for s in gated} == {"c", "d", "g"}
    # agreement: a (receive 2Y), e (receive 2Y, momentum) agree; b pays 2Y: a conflict for both
    assert by["a"]["agree"] == 1 and by["a"]["conflict"] == 1 and by["a"]["agree_with"] == ["Momentum"]
    assert by["b"]["conflict"] == 2


class _Svc(object):
    """Just what the log and the alerts need of the service."""

    def __init__(self):
        self.store = Store(":memory:")
        self.mode = "replay"
        self.nudged = 0

    def require_user(self, user):
        return user

    def nudge(self):
        self.nudged += 1

    def bump(self):
        self.nudged += 1


def test_signal_log_follows_entries_to_target_stop_and_expiry():
    svc = _Svc()
    q = Quant(svc)
    c = cfg(log_days=3)
    got = []
    q.add_alert_hook(got.append)

    def look(day, mons, signals):
        q._track({"cfg": c, "today": day, "mons": {m.sid: m for m in mons}}, signals)

    a, b, e = _mon("a", "pca", 1.0), _mon("b", "pairs", 1.0), _mon("e", "rv", 1.0)
    look("2026-11-02", [a, b, e], [])                                    # the first look: nothing is a crossing yet
    assert q._log() == []
    for m in (a, b, e):
        m.zfn = lambda level, live, k=m: 2.6
        m.score({}, {})
        m.level = 2.6
    sigs = [qf.make_signal(m, c, "10:00") for m in (a, b, e)]
    look("2026-11-03", [a, b, e], sigs)
    log = q._log()
    assert [x["sid"] for x in log] == ["a", "b", "e"] and all(x["status"] == "open" for x in log) and len(got) == 3
    look("2026-11-03", [a, b, e], sigs)                                  # still past the threshold: not written again
    assert len(q._log()) == 3
    a.level = -0.1                                                       # back to the mean: the target
    b.level = 3.6                                                        # further away: the stop
    look("2026-11-04", [a, b, e], [])
    by = {x["sid"]: x for x in q._log()}
    assert by["a"]["status"] == "hedef" and by["a"]["pnl"] == pytest.approx(2.7) and by["a"]["pnl_sigma"] == pytest.approx(2.7)
    assert by["b"]["status"] == "stop" and by["b"]["pnl"] < 0 and by["e"]["status"] == "open"
    look("2026-11-06", [a, b, e], [])                                    # three business days on: e expires
    by = {x["sid"]: x for x in q._log()}
    assert by["e"]["status"] == "süre" and by["e"]["held"] == 3
    hits = {r["family"]: r for r in q.log_view()["families"]}
    assert hits["pca"]["hit_rate"] == 1.0 and hits["pairs"]["hit_rate"] == 0.0 and hits["rv"]["expired"] == 1
    # alerts reach only those who subscribed, filtered by family and strength
    q.set_subscription("ayse", {"on": True, "families": ["pca"], "min": "Zayıf"})
    q.set_subscription("mehmet", {"on": True, "families": [], "min": "Güçlü"})
    assert [x["sid"] for x in q.alerts("ayse", 0)["alerts"]] == ["a"]
    assert q.alerts("mehmet", 0)["alerts"] == [] and q.alerts("zeynep", 0)["alerts"] == []
    assert q.alerts("ayse", None)["alerts"] == [] and q.counters()["alerts"] == 3
    assert got[0]["expression"] == "Receive a" and got[0]["family"] == "pca"


def test_strong_signals_ring_as_the_desk_s_alarms():
    """Through the desk's alarms (deskalarms.py, the operations branch): what its ``fired`` / ``close`` get - a
    stand-in with just those two (muting there is personal and on its side: a firing is for everyone)."""
    class Desk(object):
        def __init__(self):
            self.events, self.closed = [], []

        def fired(self, events):
            self.events.extend(events)

        def close(self, alarm, why):
            self.closed.append((alarm, why))

    svc = _Svc()
    svc.desk_alarms = desk = Desk()
    q = Quant(svc)
    c = cfg()

    def look(day, mons, signals):
        q._track({"cfg": c, "today": day, "mons": {m.sid: m for m in mons}}, signals)

    def at(m, z):
        m.zfn = lambda level, live, z=z: z
        m.score({}, {})
        m.level = z

    strong, medium = _mon("a", "pca", 1.0), _mon("b", "pairs", 1.0)
    look("2026-11-02", [strong, medium], [])
    at(strong, 3.2)                                      # 3,2 / 2 = 1,6: Güçlü
    at(medium, 2.6)                                      # Orta
    look("2026-11-03", [strong, medium], [qf.make_signal(m, c, "10:00") for m in (strong, medium)])
    assert [e["id"] for e in desk.events] == ["quant:a"] and svc.nudged >= 1          # the desk's setting: Güçlü and up
    e = desk.events[0]
    assert e["label"] == "Sinyal · PCA kalıntısı: Receive a" and e["value_text"] == "z +3,20 (Güçlü)" and e["mode"] == "level"
    assert e["condition"] == "giriş eşiği |z| ≥ 2"
    at(strong, 0.0)                                      # the target: its desk alarm closes
    look("2026-11-04", [strong, medium], [])
    assert desk.closed == [("quant:a", "hedefe ulaştı")]
    # the desk's setting: from Orta up; then switched off (the alert itself is there all the same)
    q.set_settings("ayse", {"desk_alarm": "orta"})
    assert q.settings()["desk_alarm"] == "Orta"
    with pytest.raises(Exception):
        q.set_settings("ayse", {"desk_alarm": "bazen"})
    third = _mon("e", "rv", 1.0)
    look("2026-11-05", [third], [])
    at(third, 2.6)
    look("2026-11-06", [third], [qf.make_signal(third, c, "10:00")])
    assert [e["id"] for e in desk.events] == ["quant:a", "quant:e"] and desk.events[1]["value_text"] == "z +2,60 (Orta)"
    q.set_settings("ayse", {"desk_alarm": "kapalı"})
    fourth = _mon("f", "rv", 1.0)
    look("2026-11-09", [fourth], [])
    at(fourth, 3.4)
    look("2026-11-10", [fourth], [qf.make_signal(fourth, c, "10:00")])
    assert [e["id"] for e in desk.events] == ["quant:a", "quant:e"] and q.counters()["alerts"] == 4


def test_settings_are_validated_and_shared():
    q = Quant(_Svc())
    out = q.set_settings("ayse", {"entry_z": "2,5", "horizon": 15, "corr_windows": "10, 30, 90", "rv_items": "1y2y, 2y5y10y"})
    assert out["values"]["entry_z"] == 2.5 and out["values"]["horizon"] == 15 and out["values"]["corr_windows"] == [10, 30, 90]
    assert out["by"] == "ayse" and q.settings()["rv_items"] == "1y2y, 2y5y10y"
    for bad in ({"entry_z": "abc"}, {"stop_z": 2.0}, {"horizon": 500}, {"ma_slow": 10}, {"rv_items": "2y, USDTRY"}, {"corr_windows": "1"}):
        with pytest.raises(Exception):
            q.set_settings("ayse", bad)
    assert q.settings()["entry_z"] == 2.5


def test_a_package_is_sized_in_dollars_and_an_old_try_size_is_not_read_as_dollars():
    """Every package's main leg is the setting's DV01 in USD - 1.000 $ a bp, the desk's OIS_MAIN!F2 ("DV01/bacak $") -,
    in TRY at USDTRY (the workbook's OIS_MAIN!D2, else the quant's own); an OIS leg's nominal its DV01 over its annuity
    (Motor's, as the blotter sizes a trade, else from its own par).  A database the TRY-sized version saved
    (``dv01_base``: 10.000 TRY) is not read as dollars."""
    q = Quant(_Svc())
    q.store.put(Quant.SET_KEY, {"dv01_base": 10000.0, "entry_z": 2.5})
    s = q.settings()
    assert s["dv01_usd"] == 1000.0 == DEFAULTS["dv01_usd"] and "dv01_base" not in s and s["entry_z"] == 2.5
    from tto.quant import LABELS
    assert "USD" in LABELS["dv01_usd"]
    assert q.set_settings("ayse", {"dv01_usd": "2500"})["values"]["dv01_usd"] == 2500.0
    assert "dv01_base" not in q.store.get(Quant.SET_KEY)
    with pytest.raises(Exception):
        q.set_settings("ayse", {"dv01_usd": 0})
    meta = {"OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0}}
    own = qf.Ctx(cfg(dv01_usd=2500.0), TODAY, {"FX:USDTRY": {"2026-11-02": 42.0}}, meta, live={"OIS:2Y": 36.0})
    assert own.dv01_size() == (2500.0, 2500.0 * 42.0) and own.ois_annuity("OIS:2Y") == qf._annuity(36.0, 24.0)
    desk = qf.Ctx(cfg(), TODAY, {"FX:USDTRY": {"2026-11-02": 42.0}}, meta, live={"OIS:2Y": 36.0},
                  desk={"usdtry": 50.0, "ois_annuity": {"2Y": 1.4}})
    assert desk.usdtry() == 50.0 and desk.dv01_size() == (1000.0, 50000.0) and desk.ois_annuity("OIS:2Y") == 1.4
    legs = [{"key": "OIS:2Y", "name": "2Y OIS", "weight": -0.5}, {"key": "VIOPI:FRONT", "name": "VİOP", "weight": 1.0}]
    qf.size_legs(desk, legs)
    assert legs[0]["dv01_usd"] == -500.0 and legs[0]["dv01"] == -25000.0
    assert legs[0]["notional"] == pytest.approx(25000.0 / (1.4 * 1e-4) / 1e6) and "dv01_usd" not in legs[1]
    # a signal's legs: what to do and how much, unsigned (the action says the side); its P&L in TRY by the main leg
    m = qf.Monitor("x:2Y", "pca", "TRY OIS", "2Y OIS", "bp", 1, ["2026-11-02"], [0.0], [dict(legs[0], weight=1.0, dv01_usd=1000.0,
                   dv01=50000.0, notional=357.1)], lambda live: 3.0, mean=0.0, sd=1.0, half_life=5.0, regime={"tag": "MR"},
                   pnl=("bp", 1.0), dsd=1.0)
    m.level, m.z = 3.0, 3.0
    sg = qf.make_signal(m, cfg(), "10:00")
    leg = sg["legs"][0]
    assert (leg["action"], leg["dv01_usd"], leg["dv01"], leg["notional"]) == ("Receive", 1000.0, 50000.0, 357.1)
    assert sg["exp_pnl"] > 0 and sg["pnl_try"] == pytest.approx(sg["exp_pnl"] * 50000.0) and sg["packages"] == []


# ================================================================================================ Bloomberg's daily budget
def test_a_live_day_of_history_syncs_stays_within_bloomberg_s_budget(tmp_path):
    """The fake terminal through a first sync and a whole day of 15-minute syncs, then the next days:

    * no series' full range twice in a day; Bloomberg's own start of the short ones is kept and never asked again;
    * the quant series (every pair of the desk's list) get their first two years five a sync, those never asked first;
    * the history's own series the analyses read (OIS, offshore, TLREF, DİBS) get their own window at once, and the year
      before it from the next day on - only the part they miss, a week into what they have - five a sync too;
    * afterwards only the new days: the history's own every sync from their last close, the quant series once a day
      (after 07:00; none on the day of their full range) - the day's hits and data points stay bounded;
    * the next day: the series without any history once more, the quant series their new days once;
    * a longer window whose answers do not come in time: asked once that day, once more the day after, then never."""
    import fake_blpapi
    from test_history import TODAY, D, _fake_history, _weekdays
    from tto.config import Settings
    from tto.history import History
    from tto.marketdata.bloomberg import BloombergProvider
    from tto.service import Service
    from tto.xl.engine import Clock
    from tto.xl.values import date_to_serial

    server = fake_blpapi.Server()
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    provider.start()
    today = float(date_to_serial(D(TODAY)))
    clock = Clock(today + 0.5)                               # 12:00: past the 07:00 of the once-a-day series
    clock.today = lambda: today
    svc = Service(Settings(data_dir=str(tmp_path), mode="live", history=False), provider=provider, clock=clock)
    q = History.BACKFILL_PER_SYNC
    try:
        h = svc.history
        snap = h.snapshot()
        hist, _ = _fake_history(svc, snap)
        # the quant series: more than two years for most; Bloomberg's history of four is shorter, of two there is none
        short = {"USDCOPV3M BGN Curncy": 120, "USDIDR25R3M BGN Curncy": 200, "TURKEY CDS USD SR 5Y D14 Corp": 400, "INR3M Curncy": 60}
        none = {"BRL3M Curncy", "IDR3M Curncy"}
        quant = [d for d in snap["defs"] if d.group == "Quant"]
        assert len(quant) == len(series_specs()) and {"GBP3M Curncy", "JPY3M Curncy", "USDCNHV3M BGN Curncy", "GBPTRY Curncy", "EUR3M Curncy"} <= {d.ticker for d in quant}
        for d in quant:
            if d.ticker not in none:
                start = D(TODAY) - dt.timedelta(days=short.get(d.ticker, 900))
                hist[(d.ticker, "PX_LAST")] = [(x, 1.0 + 0.001 * i) for i, x in enumerate(_weekdays(start, D(TODAY)))]
        server.history.update(hist)
        qt = {d.ticker for d in quant}

        def requests():
            return [r for r in server.requests if r["op"] == "HistoricalDataRequest"]

        def known(s, field):
            """The fake terminal's history of a security, however the request spelled it (``/isin/…`` for a bond)."""
            return server.stored(server.history, s, field) or ()

        def rows(r):
            """What the fake terminal gave back for a request (data points)."""
            a, b = (dt.datetime.strptime(r["options"][k], "%Y%m%d").date() for k in ("startDate", "endDate"))
            return sum(sum(1 for x, _ in known(s, r["fields"][0]) if a <= x <= b) for s in r["securities"])

        def kind(r, day=D(TODAY)):
            """full: from far back to the day; gap: the part before a series' first close; tail: the new days."""
            start, end = r["options"]["startDate"], r["options"]["endDate"]
            if end < day.strftime("%Y%m%d"):
                return "gap"
            return "full" if start < (day - dt.timedelta(days=30)).strftime("%Y%m%d") else "tail"

        def run(n):
            out = []
            for _ in range(n):
                m = len(requests())
                h._fetch()
                out.append(requests()[m:])
            return out

        syncs = run(1 + 4 * 24)                              # the first sync, then a day of 15-minute syncs
        reqs = [r for s in syncs for r in s]
        full = {}
        for r in reqs:
            if kind(r) == "full":
                for s in r["securities"]:
                    full[s] = full.get(s, 0) + 1
        assert max(full.values()) == 1 and not any(kind(r) == "gap" for r in reqs)     # no range twice; no older year today
        stored = svc.store.hist_bounds()
        own = {s for r in syncs[0] for s in r["securities"]} - qt
        # the first sync: the history's own series in full (their own window) and the first five quant series
        first = {s for r in syncs[0] if kind(r) == "full" for s in r["securities"]}
        assert len(first - qt) == 117 and len(first & qt) == q
        # the quant series: five a sync until every one of them was asked; afterwards only new days - of every series with
        # data, the quant ones too, each sync (the desk keeps its 15-minute sync for every series)
        per_q = [sum(1 for r in s if kind(r) == "full" for x in r["securities"] if x in qt) for s in syncs]
        nq = len(quant)
        k = -(-nq // q)
        assert per_q[:k] == [q] * (k - 1) + [nq - q * (k - 1)] and not any(per_q[k:])
        news = {(D(b[1]) - dt.timedelta(days=History.OVERLAP_DAYS)).strftime("%Y%m%d") for s, b in stored.items() if s.split("|")[0] not in qt}
        assert {r["options"]["startDate"] for s in syncs[k:] for r in s if set(r["securities"]) - qt} == news == {"20261030", "20261031"}
        with_data = {s.split("|")[0] for s in stored} & qt
        assert all({x for r in s if kind(r) == "tail" for x in r["securities"] if x in qt} == with_data for s in syncs[k:])
        records = h.fetch_records()
        for t, back in short.items():                        # Bloomberg's own start of the short ones is kept
            rec = records[t + "|PX_LAST"]
            assert full[t] == 1 and rec["first"] > rec["from"] and rec["first"] >= (D(TODAY) - dt.timedelta(days=back)).isoformat()
        assert all(full.get(t) == 1 for t in none)          # asked once today, nothing came
        everything = len({s for r in reqs for s in r["securities"]})
        hits = sum(len(r["securities"]) for r in reqs)       # security × field per request: the terminal's hits
        points = sum(rows(r) for r in reqs)
        own_data = [s for s in stored if s.split("|")[0] not in qt]
        # bounded: one full range a series, then one request of the new days per series with data a sync
        assert hits <= everything + len(syncs) * (len(own_data) + len(with_data))
        new_rows = len(list(_weekdays(D(TODAY) - dt.timedelta(days=History.OVERLAP_DAYS + 1), D(TODAY))))     # (3: the TLREF's)
        full_rows = sum(len(v) for v in hist.values())
        assert points <= full_rows + len(syncs) * (len(own_data) + len(with_data)) * new_rows
        print("live day: %d syncs, %d requests, %d hits, %d data points (%d securities, %d with history, %d quant series)"
              % (len(syncs), len(reqs), hits, points, everything, len(stored), nq))
        # the next day: the series without any history once more, every series with data its new days every sync - and
        # the history's own series their older year, five a sync
        clock.today = lambda: today + 1
        svc.bump()
        day1 = D(TODAY) + dt.timedelta(days=1)
        ng = len(own_data)
        nxt = run(-(-ng // q) + 2)
        full_next = [s for x in nxt for r in x if kind(r, day1) == "full" for s in r["securities"]]
        missing = {s for r in reqs for s in r["securities"] if not known(s, r["fields"][0])}
        assert set(full_next) == missing and len(full_next) == len(missing) and none <= set(full_next)    # once each
        tails_q = [{x for r in s if kind(r, day1) == "tail" for x in r["securities"] if x in qt} for s in nxt]
        assert all(t == qt - none for t in tails_q)
        gaps = [[x for r in s if kind(r, day1) == "gap" for x in r["securities"]] for s in nxt]
        flat = [x for g in gaps for x in g]
        assert len(flat) == len(set(flat)) == ng and all(len(g) <= q for g in gaps) and not gaps[-1]
        far = (day1 - dt.timedelta(days=HISTORY_DAYS)).isoformat()
        records = h.fetch_records()
        nb = svc.store.hist_bounds()
        assert all(records[s]["from"] == far and records[s]["first"] == nb[s][0] for s in own_data)
        hits1 = sum(len(r["securities"]) for s in nxt for r in s)
        print("next day: %d hits in %d syncs (the older year of %d series in them), then %d a sync"
              % (hits1, len(nxt), ng, sum(len(r["securities"]) for r in nxt[-1])))
        # the window grows past two years (Ayarlar → Geriye bakış) and the answers do not come in time: each series' older
        # part is asked once that day (five a sync) and does not count as had; the day after once more, then never again
        silent = []

        class Silent(object):
            def history(self, items, start, end, timeout=60.0):
                silent.extend((start, "%s|%s" % (t, f)) for t, f in items)
                return {}

        def day(n):
            return D(TODAY) + dt.timedelta(days=n)

        h.set_settings({"lookback_days": 1000})
        stored = svc.store.hist_bounds()
        clock.today = lambda: today + 2
        svc.bump()
        before = h.fetch_records()
        real, svc.provider = svc.provider, Silent()
        try:
            for _ in range(60):
                h._fetch()
        finally:
            svc.provider = real
        grown = [s for start, s in silent if start == (day(2) - dt.timedelta(days=1000)).strftime("%Y%m%d") and s in stored]
        assert len(grown) == len(set(grown)) and set(grown) == set(stored)
        rec = h.fetch_records()
        assert all(rec[s]["day"] == day(2).isoformat() and rec[s].get("from") == (before.get(s) or {}).get("from") for s in grown)
        clock.today = lambda: today + 3
        svc.bump()
        n = len(requests())
        for _ in range(60):
            h._fetch()
        again = [s for r in requests()[n:] if r["options"]["startDate"] == (day(3) - dt.timedelta(days=1000)).strftime("%Y%m%d")
                 for s in r["securities"] if known(s, r["fields"][0])]
        assert len(again) == len(set(again)) == len(grown)
        rec = h.fetch_records()
        assert all(rec[s]["day"] == day(3).isoformat() and rec[s]["from"] == (day(3) - dt.timedelta(days=1000)).isoformat() for s in grown)
        clock.today = lambda: today + 4
        svc.bump()
        h._fetch()
        assert all(h.fetch_records()[s]["day"] == day(3).isoformat() for s in grown)
    finally:
        svc.stop()


# ================================================================================================ the service and the API
@pytest.fixture(scope="module")
def seeded(module_service):
    svc = module_service
    svc.quant.use_live = False                                           # the workbook's live quotes are not of this history
    quant_synth.seed(svc)
    return svc


def test_history_keeps_the_new_series_two_years_back(seeded):
    svc = seeded
    snap = svc.history.snapshot()
    quant = [d for d in snap["defs"] if d.group == "Quant"]
    tickers = {d.ticker for d in quant}
    assert {"USGG2YR Index", "USGG10YR Index", "DXY Curncy", "CO1 Comdty", "TURKEY CDS USD SR 5Y D14 Corp", "USDZAR Curncy",
            "USDZARV3M BGN Curncy", "ZAR3M Curncy", "TRY12M Curncy"} <= tickers
    assert all(d.info["lookback"] == HISTORY_DAYS for d in quant)
    cov = svc.history.coverage()["series"]
    assert any(r["group"] == "Quant" and r["ticker"] == "DXY Curncy" and r["n"] > 400 for r in cov)
    asked = []

    class Recorder(object):
        def history(self, items, start, end, timeout=60.0):
            asked.append((start, [t for t, _ in items]))
            return {}

    real, svc.provider = svc.provider, Recorder()
    try:
        svc.store.hist_delete("DXY Curncy|PX_LAST")
        svc.history._empty.clear()
        svc.history._fetch()
    finally:
        svc.provider = real
        quant_synth.seed(svc)
    today = snap["today"]
    starts = {t: s for s, items in asked for t in items}
    assert starts["DXY Curncy"] == (today - dt.timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d")
    ois = next(d for d in snap["defs"] if d.group == "ois")
    assert ois.ticker not in starts or starts[ois.ticker] >= (today - dt.timedelta(days=380)).strftime("%Y%m%d")


def test_fit_runs_off_the_engine_thread_and_finds_the_planted_signals(seeded, monkeypatch):
    svc = seeded
    threads = []
    real = qf.run_all

    def spy(*args, **kw):
        threads.append(threading.current_thread().name)
        return real(*args, **kw)

    monkeypatch.setattr(qf, "run_all", spy)
    st = svc.quant.compute()
    assert threads and "engine" not in threads[0] and st["ready"] and not st["errors"]
    assert st["engine_ms"] < st["fit_ms"]
    user = svc.login("quant okuyucu")["user"]
    v = svc.quant.view("signals", user, {})
    ids = {s["id"]: s for s in v["signals"]}
    assert "pca:OIS:2Y" in ids and ids["pca:OIS:2Y"]["expression"].startswith("Receive 2Y OIS")
    assert "pairs:off:3M" in ids and ids["pairs:off:3M"]["direction"] == -1
    ranks = [s["composite"] for s in v["signals"]]
    assert ranks == sorted(ranks, reverse=True)
    assert {f["id"] for f in v["families"]} == set(qf.FAMILIES)
    only = svc.quant.view("signals", user, {"family": "pca"})["signals"]
    assert only and all(s["family"] == "pca" for s in only)
    one = svc.quant.view("signal", user, {"id": "pca:OIS:2Y"})
    assert len(one["history"]["days"]) >= DEFAULTS["min_obs"] and len(one["history"]["z"]) == len(one["history"]["days"])
    assert one["signal"]["entry"] == one["monitor"]["level"]
    t0 = svc.quant.state["refreshes"]
    svc.quant.refresh_live()
    assert svc.quant.state["refreshes"] == t0 + 1 and svc.quant.state["live_ms"] < 2000


def test_the_service_backtests_every_family_and_shows_it_beside_each_signal(seeded):
    import time as _time
    svc = seeded
    q = svc.quant
    q.compute()
    t0 = _time.perf_counter()
    res = q.run_backtest(days=120, step=20)
    took = _time.perf_counter() - t0
    print("backtest: %d days, %d refits, %d trades, %.1f s" % (res["days"], res["refits"], res["n_trades"], took))
    assert res["complete"] and res["refits"] == 6 and res["families"] and q.backtest_result() is res
    assert res["key"] == q._bt_key() and svc.store.get(q.BT_KEY)["n_trades"] == res["n_trades"]
    q.compute()                                                          # the signals now carry their family's record
    user = svc.login("quant okuyucu")["user"]
    sigs = q.view("signals", user, {})["signals"]
    assert sigs and all(s["bt"] is not None and s["bt"]["text"].startswith(("bu aile", "geri testte")) for s in sigs)
    assert all(any(g["name"] == "Geri test" for g in s["gates"]) for s in sigs)
    view = q.view("backtest", user, {})
    assert view["ready"] and view["rows"] and {"trades", "hit", "avg_sigma", "sharpe", "max_dd"} <= set(view["rows"][0])
    # the desk's floor: a family whose record is below it has its signals held back ("geri testte zayıf")
    fam = sigs[0]["family"]
    q.set_settings(user, {"bt_mute": "açık", "bt_min_trades": 1, "bt_min_hit": 1.0})
    q.compute()
    held = [s for s in q.view("signals", user, {})["gated"] if s["family"] == fam and (q.backtest_result()["families"].get(fam) or {}).get("trades")]
    assert held and all(s["strength"] == "elendi" for s in held) and any("geri testte zayıf" in s["gated"] for s in held)
    q.set_settings(user, {"bt_mute": "kapalı", "bt_min_trades": 10, "bt_min_hit": 0.5})
    q.compute()


def test_quant_http_api(seeded):
    svc = seeded
    if not svc.quant.status()["ready"]:
        svc.quant.compute()
    app = create_app(svc)
    with TestClient(app, headers=auth(svc, "Quant HTTP")) as client:
        res = client.get("/api/quant/signals")
        assert res.status_code == 200 and res.json()["ready"] and res.json()["signals"]
        for what in ("corr", "pca", "pairs", "regime", "fx", "macro", "model", "log", "status", "settings", "subscription"):
            r = client.get("/api/quant/" + what)
            assert r.status_code == 200, what
        body = client.get("/api/quant/pca").json()
        assert body["pca"]["ok"] and len(body["pca"]["names"]) == 3 and body["rv"]["rows"] and "today" in body["pca"]
        assert client.get("/api/quant/corr").json()["corr"]["matrices"]
        assert client.get("/api/quant/nonsense").status_code == 400
        assert client.get("/api/quant/signal", params={"id": "yok"}).status_code == 400
        one = client.get("/api/quant/signal", params={"id": "pca:OIS:2Y"}).json()
        why = one["rationale"]
        assert why["summary"]["n"] == 10 and len(why["analogs"]) == 10 and why["invalidation"][0].startswith("Stop")
        assert one["signal"]["thesis"] and one["signal"]["gates"] and "exp_pnl" in one["signal"]
        assert client.post("/api/quant/settings", json={"values": {"entry_z": "9"}}).status_code == 400
        res = client.post("/api/quant/settings", json={"values": {"entry_z": "2.2"}})
        assert res.status_code == 200 and res.json()["values"]["entry_z"] == 2.2
        client.post("/api/quant/settings", json={"values": {"entry_z": "2"}})
        res = client.post("/api/quant/subscription", json={"on": True, "families": ["pca", "yok"], "min": "Orta"})
        assert res.status_code == 200 and res.json()["families"] == ["pca"] and res.json()["min"] == "Orta"
        assert client.get("/api/quant/alerts", params={"since": 0}).status_code == 200
        res = client.post("/api/quant/recompute", json={})
        assert res.status_code == 200 and res.json()["ready"]
        nav = client.get("/api/nav").json()["pages"]
        quant = [p for p in nav if p["group"] == "Quant"]
        assert [p["id"] for p in quant][:2] == ["quant", "quant-corr"] and len(quant) == 14 and quant[8]["id"] == "quant-intraday" and quant[-1]["id"] == "quant-lead"
        for path in ("/static/js/pages/quant.js", "/static/js/pages/quantbase.js", "/static/js/pages/quantviews.js"):
            assert client.get(path).status_code == 200
        assert client.get("/api/quant/signals", headers={"Authorization": ""}).status_code == 401
    assert set(svc.quant.counters()) == {"alerts", "version"}


# ================================================================================================ the backtest
def _bt_inputs(n=520, seed=61):
    rnd = random.Random(seed)
    days = DAYS[-n:]
    ou = [x * 100.0 for x in ar1(n, 0.8, 0.05, rnd)]                    # bp: mean-reverting, a half-life of ~3 days
    rw = [x * 100.0 for x in walk(n, 0.05, rnd)]                        # bp: a random walk
    series = {"OU": dict(zip(days, ou)), "RW": dict(zip(days, rw))}
    meta = {"OU": {"label": "OU", "kind": "bp"}, "RW": {"label": "RW", "kind": "bp"}}

    def make_ctx(T, series=series):
        return qf.Ctx(cfg(), dt.date.fromisoformat(T) + dt.timedelta(days=1), series, {k: dict(v) for k, v in meta.items()})

    def runner(ctx):
        out = []
        for key in ("OU", "RW"):
            pts = ctx.pts(key)
            m = qf.mr_monitor(ctx, "pca:" + key, "pca", "TRY OIS", key, "bp", 1, [d for d, _ in pts], [v for _, v in pts], "bp",
                              [{"key": key, "name": key, "weight": 1.0}], lambda live, key=key, ctx=ctx: ctx.cur(key, live), pkg="rate")
            if m is not None:
                out.append(m)
        return out

    return days, series, make_ctx, runner


def test_backtest_walks_forward_with_the_live_rules():
    from tto import quantbt as qbt
    days, series, make_ctx, runner = _bt_inputs()
    res = qbt.backtest(days[-250:], make_ctx, runner, series, cfg(usdtry=40.0), step=10)
    ou = [t for t in res["trades"] if t["sid"] == "pca:OU"]
    rw = [t for t in res["trades"] if t["sid"] == "pca:RW"]
    assert res["refits"] == 25 and res["complete"] and res["first"] == days[-250]
    # the mean-reverting series: entered past |z| 2, mostly back at its mean; the random walk: its half-life keeps it out
    assert len(ou) >= 8 and sum(1 for t in ou if t["pnl"] > 0) / len(ou) >= 0.65 and sum(t["pnl_sigma"] for t in ou) / len(ou) > 0.3
    assert len(rw) <= len(ou) / 2
    assert all(t["outcome"] in ("hedef", "stop", "süre") and 1 <= t["held"] <= 20 and t["unit"] == "bp" for t in res["trades"])
    assert all(t["entry_day"] < t["exit_day"] for t in res["trades"])
    fam = res["families"]["pca"]
    assert fam["trades"] == len(ou) + len(rw) and set(fam["types"]) == {"TRY OIS"} and fam["avg_try"] == pytest.approx(fam["avg"] * 1000.0 * 40.0)
    # no look-ahead: the future rewritten after a day changes nothing decided by that day
    cut = days[-100]
    later = {k: {d: (v + 50.0 if d > cut else v) for d, v in pts.items()} for k, pts in series.items()}
    _, _, make2, run2 = _bt_inputs()
    res2 = qbt.backtest(days[-250:], lambda T: make2(T, later), run2, later, cfg(), step=10)
    def before(r):
        return sorted((t["sid"], t["entry_day"], round(t["entry"], 9), t["exit_day"], round(t["pnl"], 9)) for t in r["trades"] if t["exit_day"] <= cut)
    entries = lambda r: sorted((t["sid"], t["entry_day"], round(t["entry"], 9)) for t in r["trades"] if t["entry_day"] <= cut)
    assert before(res) == before(res2) and entries(res)[:len(before(res))] == entries(res2)[:len(before(res))]


def test_backtest_statistics_and_the_desk_s_floor():
    from tto import quantbt as qbt
    trades = [{"sid": "a", "exit_day": "2026-01-%02d" % (i + 1), "pnl": p, "pnl_sigma": p, "unit": "bp", "pnl_try": p * 10000.0}
              for i, p in enumerate([1.0, -2.0, 1.5, 0.5, -0.5, 2.0])]
    st = qbt.summarize(trades, "2025-01-01", "2026-01-01")
    m = 2.5 / 6.0
    sd = math.sqrt(sum((x - m) ** 2 for x in [1.0, -2.0, 1.5, 0.5, -0.5, 2.0]) / 5.0)
    assert st["trades"] == 6 and st["hits"] == 4 and st["hit"] == pytest.approx(4 / 6) and st["avg_sigma"] == pytest.approx(m)
    assert st["sharpe"] == pytest.approx(m / sd * math.sqrt(6.0)) and st["max_dd"] == pytest.approx(2.0) and st["avg_try"] == pytest.approx(m * 10000.0)
    assert qbt.bt_text(st, 2.0) == "bu aile son 2 yılda 6 işlem, %67 isabet, ort. +0,4σ"
    weak = {"trades": 20, "hit": 0.42, "sharpe": -0.3}
    assert qbt.bt_gate(weak, cfg()) is None                               # the default: the stats shown, nothing muted
    on = cfg(bt_mute="açık", bt_min_hit=0.5, bt_min_sharpe=0.0, bt_min_trades=10)
    assert qbt.bt_gate(weak, on) == "geri testte zayıf: isabet %42 < %50"
    assert qbt.bt_gate(dict(weak, hit=0.6), on) == "geri testte zayıf: Sharpe -0,30 < 0,00"
    assert qbt.bt_gate(dict(weak, trades=5), on) is None                  # too few trades to judge


# ================================================================================================ intraday
def _ibars(today, n_days=12, seed=71, plant=None):
    """Five-minute bars (09:35 … 18:00) of a few keys over ``n_days`` past days and today until 12:00, mean-reverting
    noise around their levels; ``plant(key, day, k, value)`` may change a bar."""
    rnd = random.Random(seed)
    base = {"OIS:1Y": 36.0, "OIS:2Y": 35.0, "OFF:1Y": 34.0, "FX:USDTRY": 42.0}
    days, d = [], today
    while len(days) < n_days:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    days = sorted(days) + [today]
    out = {k: {} for k in base}
    for day in days:
        last = 12 * 60 if day == today else 18 * 60
        mins = list(range(9 * 60 + 35, last + 1, 5))
        for k, b in base.items():
            x, rows = 0.0, []
            for i, m in enumerate(mins):
                x = 0.7 * x + rnd.gauss(0, 0.004 if k != "FX:USDTRY" else 0.003)
                v = b + x if k != "FX:USDTRY" else b * (1.0 + x / 100.0)
                if plant:
                    v = plant(k, day, i, v, mins)
                rows.append((m, v))
            out[k][day.isoformat()] = rows
    return out


def test_intraday_bars_are_kept_small_and_made_five_minutes(tmp_path):
    from tto import quantintraday as qi
    b = qi.Bars(str(tmp_path / "bars.sqlite3"))
    start = dt.datetime(2026, 10, 1, 9, 30)
    day, kept = start, 0
    while kept < 25:
        if day.weekday() < 5:
            for m in (0, 1, 2, 3, 4, 5, 6):
                b.record(day + dt.timedelta(minutes=m), {"OIS:1Y": 36.0 + m * 0.01, "FX:USDTRY": 42.0, "NOT:A:KEY": 1.0})
            kept += 1
        day += dt.timedelta(days=1)
    st = b.stats()
    assert st["days"] == qi.KEEP_DAYS and st["rows"] == qi.KEEP_DAYS * 7 * 2       # 20 trading days, the known keys only
    pts = b.load(["OIS:1Y"])["OIS:1Y"]
    bars = qi.five(pts)
    first = sorted(bars)[-1]
    assert bars[first] == [(9 * 60 + 30, 36.0), (9 * 60 + 35, 36.05), (9 * 60 + 40, 36.06)]   # each bar its last minute's close
    b.close()


def test_intraday_families_on_planted_bars():
    from tto import quantintraday as qi
    today = dt.date(2026, 11, 3)
    now = dt.datetime(2026, 11, 3, 12, 0)

    def plant(key, day, i, v, mins):
        if key == "OIS:2Y":                                  # every day: a 30-minute range, a break up at 11:00 that carries on
            if i < qi.OR_BARS:
                return 35.0 + (0.02 if i % 2 else -0.02)
            if mins[i] >= 11 * 60:
                return 35.05 + 0.001 * (mins[i] - 11 * 60)
            return 35.0
        if day == today and i == len(mins) - 1:
            if key == "OIS:1Y":
                return v + 0.01                              # 1 bp more above its 60-minute mean: fade it
            if key == "OFF:1Y":
                return v - 0.006                             # offshore − OIS 1Y ~1,6 bp narrower than usual
            if key == "FX:USDTRY":
                return 42.0 * 1.0006                         # 0,06 % ahead of the path its carry implies
        return v

    raw = _ibars(today, plant=plant)
    series, meta = fx_series(n=300)                          # USDTRY's forwards: a carry of −30 % a year
    for k, lab in (("OIS:1Y", "1Y OIS"), ("OIS:2Y", "2Y OIS"), ("OFF:1Y", "Offshore 1Y")):
        meta[k] = {"label": lab, "kind": "rate", "months": 12.0}
    ctx = ctx_of(series, meta, today=today)
    mons, table = qi.intraday_monitors(ctx, raw, now)
    live = {k: rows[today.isoformat()][-1][1] for k, rows in raw.items()}
    qf.score_all(ctx, mons, live)
    sig = {m.sid: qf.make_signal(m, cfg(), "12:00") for m in mons}
    z1 = sig["izscore:OIS:1Y"]
    assert z1 and z1["expression"].startswith("Receive") and z1["intraday"] and z1["horizon_unit"] == "bar" and not z1["gated"]
    assert 2 < z1["z"] < 3.5 and z1["exp_pnl"] > 0 and z1["pnl_unit"] == "bp"
    orb = sig["iorb:OIS:2Y"]
    row = next(r for r in table["z"] if r["key"] == "OIS:2Y")
    assert row["breaks"] >= qi.MIN_BREAKS and row["cont"] > 0 and orb and orb["expression"].startswith("Pay 2Y OIS")
    assert orb["direction"] == 1 and orb["exp_pnl"] > 0 and next(g for g in orb["gates"] if g["name"] == "Örneklem")["ok"]
    rv = sig["irv:OFF:1Y|OIS:1Y"]
    assert rv and rv["z"] < -2 and not rv["gated"]
    path = sig["ipath:USDTRY"]
    assert table["path"]["carry"] == pytest.approx(-30.0, abs=1e-6) and path and path["expression"].startswith("Sell USDTRY")
    assert path["z"] > 2 and path["carry_yr"] > 25.0 and path["fx"]["cal_days"] < 1.0           # selling it earns the carry
    # a PPK day's announcement window holds the mean-reversion ones back; after 17:00 no new intraday trade at all
    m2, _ = qi.intraday_monitors(ctx, raw, dt.datetime(2026, 11, 3, 14, 0), meeting_day=True)
    qf.score_all(ctx, m2, live)
    held = {m.sid: qf.make_signal(m, cfg(), "14:00") for m in m2}
    assert "PPK açıklama penceresi" in held["izscore:OIS:1Y"]["gated"] and held["izscore:OIS:1Y"]["strength"] == "elendi"
    assert not held["iorb:OIS:2Y"]["gated"]                 # a breakout may follow the decision
    m3, _ = qi.intraday_monitors(ctx, raw, dt.datetime(2026, 11, 3, 17, 30))
    qf.score_all(ctx, m3, live)
    late = [s for s in (qf.make_signal(m, cfg(), "17:30") for m in m3) if s]
    assert late and all(s["gated"] and any(g["name"] == "Seans" and not g["ok"] and "seans sonuna" in g["text"] for g in s["gates"]) for s in late)


def test_intraday_needs_live_prices_and_its_log_does_not_stay_over_night():
    from tto import quantintraday as qi
    svc = _Svc()
    q = Quant(svc)
    mons, table = q.intraday.monitors(qf.Ctx(cfg(), TODAY, {}, {}), dt.datetime(2026, 11, 3, 12, 0))
    assert not mons and "Kayıtlı veri modunda gün içi bar yok" in table["why"]       # replay: no bars, said so
    assert q.intraday.sample({"OIS:1Y": 36.0}, dt.datetime(2026, 11, 3, 12, 0)) == 0
    c = cfg()
    m = _mon("izscore:OIS:1Y", "izscore", 0.5)
    m.intraday, m.horizon_unit = True, "bar"
    q._track({"cfg": c, "today": "2026-11-03", "mons": {m.sid: m}}, [])
    m.zfn = lambda level, live: 2.6
    m.score({}, {})
    m.level = 2.6
    q._track({"cfg": c, "today": "2026-11-03", "mons": {m.sid: m}}, [qf.make_signal(m, c, "12:00")])
    e = q._log()[-1]
    assert e["intraday"] and e["status"] == "open" and e["expires"] and e["expires"] <= "18:00"
    q._track({"cfg": c, "today": "2026-11-04", "mons": {m.sid: m}}, [])              # the next day: closed, never carried
    assert q._log()[-1]["status"] == "veri yok"
