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
    # the hedge legs make the package neutral to PC1 and PC2
    e = fit["vectors"]
    idx = {k: i for i, k in enumerate(fit["keys"])}
    for f in (0, 1):
        assert abs(sum(leg["weight"] * e[f][idx[leg["key"]]] for leg in planted.legs)) < 1e-9
    assert 0 < planted.half_life < 20


def test_pca_neutral_flies_and_spreads():
    ctx, _ = synth_ctx(shock=3.0)
    fit = qf.pca_fit(ctx)
    from tto import volcarry as vc
    items = vc.parse_items("1y2y3y, 2y5y10y, 2y5y")
    mons, table = qf.fam_rv(ctx, fit, items)
    e = fit["vectors"]
    idx = {k: i for i, k in enumerate(fit["keys"])}
    rows = {r["label"]: r for r in table["rows"]}
    fly = rows["1s2s3s PCA-nötr fly"]
    assert [l["key"] for l in fly["legs"] if l["weight"] == 1.0] == ["OIS:2Y"]           # the body
    for f in (0, 1):
        assert abs(sum(l["weight"] * e[f][idx[l["key"]]] for l in fly["legs"])) < 1e-9
    spread = rows["2s5s PC1-nötr spread"]
    assert abs(sum(l["weight"] * e[0][idx[l["key"]]] for l in spread["legs"])) < 1e-9
    assert all(l["notional"] > 0 and abs(l["dv01"] - l["weight"] * DEFAULTS["dv01_base"]) < 1e-6 for l in fly["legs"])
    m = next(x for x in mons if x.sid == "rv:fly:1Y/2Y/3Y")
    m.score({}, {})
    assert m.z > 2.0
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["expression"] == "Receive 1s2s3s PCA-nötr fly"
    assert {l["key"]: l["side"] for l in s["legs"]} == {"OIS:1Y": 1, "OIS:2Y": -1, "OIS:3Y": 1}


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


def test_fra_forwards_against_the_meeting_path():
    spot = dt.date(2026, 11, 5)
    steps = [(dt.date(2026, 12, 11), 0.385), (dt.date(2027, 1, 22), 0.37), (dt.date(2027, 3, 12), 0.355)]
    base = 0.395
    quotes = {}
    for m in qf.PATH_TENORS:                                              # quotes that are the path's own par rates
        e = qf._add_months(spot, m)
        quotes[m] = (1.0 / qf.path_df(spot, base, steps, e, set()) - 1.0) * 365.0 / (e - spot).days * 100.0
    same = qf.frapath_day(spot, base, steps, quotes, set())
    assert all(abs(v["dev"]) < 0.5 for v in same["tenor"].values())
    assert all(abs(v["dev"]) < 3.0 for v in same["fra"].values())                # log-linear between pillars: a few bp at most
    bumped = dict(quotes)
    bumped[6] += 0.20                                                     # the 6M quote 20 bp too high
    out = qf.frapath_day(spot, base, steps, bumped, set())
    assert out["tenor"][6]["dev"] > 19 and out["fra"]["3x6"]["dev"] > 30 and out["fra"]["6x9"]["dev"] < -30
    # the periods between the coming meetings: from the day after one decision to the day after the next
    assert set(same["mpc"]) == {"2026-12-11", "2027-01-22"}
    first = same["mpc"]["2026-12-11"]
    assert (first["start"], first["end"]) == ("2026-12-12", "2027-01-23") and 38.5 < first["path"] < 40.0
    higher = dict(quotes)
    higher[2] += 0.50                                                     # the 2M quote up: the period around it gets dearer
    assert qf.frapath_day(spot, base, steps, higher, set())["mpc"]["2026-12-11"]["dev"] - first["dev"] > 8
    # day by day: the 3x6 deviation mean-reverts and ends 3σ high -> receive the FRA (receive 6M, pay 3M)
    rnd = random.Random(17)
    noise = ar1(300, 0.7, 0.03, rnd)
    noise[-1] = 3.0 * 0.03 / math.sqrt(1 - 0.49)
    days = DAYS[-300:]
    series = {"OIS:%s" % lbl: {} for lbl in ("1M", "2M", "3M", "6M", "9M", "1Y")}
    meta = {k: {"label": k[4:] + " OIS", "kind": "rate", "months": {"1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12}[k[4:]]} for k in series}
    values = []
    mdays = {}
    for i, d in enumerate(days):
        sp = dt.date.fromisoformat(d) + dt.timedelta(days=2)
        for m, lbl in zip(qf.PATH_TENORS, ("1M", "2M", "3M", "6M", "9M", "1Y")):
            e = qf._add_months(sp, m)
            par = (1.0 / qf.path_df(sp, base, [], e, set()) - 1.0) * 365.0 / (e - sp).days * 100.0
            series["OIS:" + lbl][d] = par + (noise[i] if m == 6 else 0.0)
        mdays[d] = {"spot": sp.isoformat(), "base": base, "flag": ""}
        values.append({"day": d, "meeting": "2030-01-01", "level": base})
    sp = dt.date.fromisoformat(days[-1]) + dt.timedelta(days=2)
    path = {"spot": sp, "base": base, "steps": [(sp + dt.timedelta(days=40), base), (sp + dt.timedelta(days=90), base)]}
    ctx = ctx_of(series, meta, mpc={"days": mdays, "values": values}, path=path)
    mons, table = qf.fam_frapath(ctx)
    assert [p["meeting"] for p in table["periods"]] == [(sp + dt.timedelta(days=40)).isoformat()] and abs(table["periods"][0]["dev"]) < 1.0
    m = next(x for x in mons if x.sid == "frapath:3x6")
    m.score({}, {})
    s = qf.make_signal(m, cfg(), "10:00")
    assert s["z"] > 2 and s["expression"].startswith("Receive 3x6 FRA")
    assert {l["key"]: l["side"] for l in s["legs"]} == {"OIS:6M": -1, "OIS:3M": 1}


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
    m.score({}, {})
    s = qf.make_signal(m, cfg(stop_z=20.0), "10:00")
    assert s["expression"] == "Sell USDTRY 3M forward" and not s["gated"]
    mons, _ = qf.fam_fwdprem(ctx, {"regime": "Trend", "score": 2.5})
    mons[0].score({}, {})
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


# ================================================================================================ Bloomberg's daily budget
def test_a_live_day_of_history_syncs_stays_within_bloomberg_s_budget(tmp_path):
    """The fake terminal through a first sync and a whole day of 15-minute syncs: every series' full range is asked
    once (Bloomberg's own start of the short ones is kept, nothing is asked again in full), the quant series' first
    backfill five at a time, then only the recent days - and the day's requests stay bounded.  The next day: the
    series without any history are asked once more, everything else its recent days.  A longer window whose answers
    do not come in time: asked once that day, once more the day after, then never again."""
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
    clock = Clock(today + 0.5)
    clock.today = lambda: today
    svc = Service(Settings(data_dir=str(tmp_path), mode="live", history=False), provider=provider, clock=clock)
    try:
        h = svc.history
        snap = h.snapshot()
        hist, _ = _fake_history(svc, snap)
        # the quant series: more than two years for most; Bloomberg's history of four is shorter, of two there is none
        short = {"USDCOPV3M BGN Curncy": 120, "USDIDR25R3M BGN Curncy": 200, "TURKEY CDS USD SR 5Y D14 Corp": 400, "INR3M Curncy": 60}
        none = {"BRL3M Curncy", "IDR3M Curncy"}
        quant = [d for d in snap["defs"] if d.group == "Quant"]
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

        syncs = []
        for _ in range(1 + 4 * 24):                          # the first sync, then a day of 15-minute syncs
            n = len(requests())
            h._fetch()
            syncs.append(requests()[n:])
        reqs = [r for s in syncs for r in s]
        old = (D(TODAY) - dt.timedelta(days=30)).strftime("%Y%m%d")         # a request from further back: a full range
        fulls = {}
        for r in reqs:
            if r["options"]["startDate"] < old:
                for s in r["securities"]:
                    fulls[s] = fulls.get(s, 0) + 1
        assert max(fulls.values()) == 1                      # no series' full range twice in a day
        per_sync = [sum(1 for r in s if r["options"]["startDate"] < old for x in r["securities"] if x in qt) for s in syncs]
        assert per_sync[:10] == [History.BACKFILL_PER_SYNC] * 10 and not any(per_sync[10:])      # 5 a sync, all 50 in 10 syncs
        stored = svc.store.hist_bounds()
        news = {(D(b[1]) - dt.timedelta(days=History.OVERLAP_DAYS)).strftime("%Y%m%d") for b in stored.values()}
        assert {r["options"]["startDate"] for s in syncs[10:] for r in s} == news == {"20261030", "20261031"}   # then new days only
        records = h.fetch_records()
        for t, back in short.items():                        # Bloomberg's own start of the short ones is kept
            rec = records[t + "|PX_LAST"]
            assert fulls[t] == 1 and rec["first"] > rec["from"] and rec["first"] >= (D(TODAY) - dt.timedelta(days=back)).isoformat()
        assert all(fulls.get(t) == 1 for t in none)          # asked once today, nothing came
        with_data = len(stored)
        everything = len({s for r in reqs for s in r["securities"]})
        hits = sum(len(r["securities"]) for r in reqs)       # security × field per request: the terminal's hits
        points = sum(rows(r) for r in reqs)
        # bounded: one full range per series, then at most one request of the recent days per series with data a sync
        assert hits <= everything + len(syncs) * with_data
        new_rows = len(list(_weekdays(D(TODAY) - dt.timedelta(days=History.OVERLAP_DAYS + 1), D(TODAY))))     # (3: the TLREF's)
        full_rows = sum(len(v) for v in hist.values())
        assert points <= full_rows + len(syncs) * with_data * new_rows
        print("live day: %d syncs, %d requests, %d hits, %d data points (%d series, %d with history)"
              % (len(syncs), len(reqs), hits, points, everything, with_data))
        # the next day: the series without any history once more, everything else its recent days
        clock.today = lambda: today + 1
        svc.bump()
        n = len(requests())
        h._fetch()
        nxt = requests()[n:]
        full_next = {s for r in nxt if r["options"]["startDate"] < old for s in r["securities"]}
        missing = {s for r in reqs for s in r["securities"] if not known(s, r["fields"][0])}
        assert full_next == missing and none <= full_next
        assert {r["options"]["startDate"] for r in nxt if r["options"]["startDate"] >= old} == news      # (no new close here)
        # the window grows (Ayarlar → Geriye bakış) and the answers do not come in time: the longer range is asked
        # once that day and does not count as had; the day after once more, then never again
        silent = []

        class Silent(object):
            def history(self, items, start, end, timeout=60.0):
                silent.extend((start, "%s|%s" % (t, f)) for t, f in items)
                return {}

        def day(k):
            return D(TODAY) + dt.timedelta(days=k)

        h.set_settings({"lookback_days": 500})
        before = h.fetch_records()
        real, svc.provider = svc.provider, Silent()
        try:
            for _ in range(3):
                h._fetch()
        finally:
            svc.provider = real
        grown = [s for start, s in silent if start == (day(1) - dt.timedelta(days=500)).strftime("%Y%m%d")]
        assert len(grown) == len(set(grown)) and set(grown) == {s for s in stored if s.split("|")[0] not in qt}
        rec = h.fetch_records()
        assert all(rec[s]["day"] == day(1).isoformat() and rec[s]["from"] == before[s]["from"] for s in grown)
        clock.today = lambda: today + 2
        svc.bump()
        h._fetch()
        rec = h.fetch_records()
        assert all(rec[s]["day"] == day(2).isoformat() and rec[s]["from"] == (day(2) - dt.timedelta(days=500)).isoformat() for s in grown)
        clock.today = lambda: today + 3
        svc.bump()
        h._fetch()
        assert all(h.fetch_records()[s]["day"] == day(2).isoformat() for s in grown)
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
        assert [p["id"] for p in quant][:2] == ["quant", "quant-corr"] and len(quant) == 9           # (with İma Patikası)
        for path in ("/static/js/pages/quant.js", "/static/js/pages/quantbase.js", "/static/js/pages/quantviews.js"):
            assert client.get(path).status_code == 200
        assert client.get("/api/quant/signals", headers={"Authorization": ""}).status_code == 401
    assert set(svc.quant.counters()) == {"alerts", "version"}
