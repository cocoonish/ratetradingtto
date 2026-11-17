"""The ML family (``tto/quantml.py``) on synthetic history with known answers (``quant_synth_ml.py``): its universe by
the registry's keys; a planted driver found out of sample - the line prints in the plan's form, its card names the
driver first, the driver tops the trees' gain; pure noise neither passes the 55 % / 40 rule nor prints; no look-ahead
(the future changed, every earlier prediction the same to the bit); each month's model fitted only on what was known
before it and predicting only that month; the daily training's time; the models kept through a live refresh and a
second fit; a calendar edit, a VİOP roll and a new bond moving no line's state; the backtest replaying the walk-forward's
own predictions; the page, the list and the backtest through the service.  (The HTTP part last: leaving its client stops
the module's service.)"""
from __future__ import annotations

import datetime as dt
import math
import random
import re
import time

import pytest
from starlette.testclient import TestClient

import quant_synth_ml as sm
from conftest import auth
from tto import quantbt as qbt
from tto import quantfam as qf
from tto import quantlevels as qlv
from tto import quantml as ml
from tto import quantuniv as qu
from tto.server import create_app

LINE = re.compile(r"^(AL|SAT) AUDUSD spot · 1 mn AUD · olasılık %(\d+) · isabet %(\d+) \((\d+)\)$")
#: random walks (the G10 spots but the planted one) and lines whose level is one (the OIS outrights)
NOISE = tuple("FX:" + p for p in qu.G10_PAIRS if p != "AUDUSD") + ("OIS:2Y", "OIS:5Y", "OIS:10Y")


@pytest.fixture(scope="module")
def fitted():
    """The family on the full synthetic universe (42 lines × 460 days, AUDUSD planted): the real size."""
    ml.reset()
    ctx, eng, days = sm.context(plant=sm.PLANT)
    reg = qu.Registry(ctx, None, eng)
    n0 = ml.FITS["n"]
    t0 = time.perf_counter()
    mons, tab = ml.run(ctx, reg, ctx.cfg)
    took = time.perf_counter() - t0
    print("\nML, gerçek boyut: %d satır × %d gün, %d model %.1f sn'de (%s)" % (tab["lines"], len(days), ml.FITS["n"] - n0, took, tab["timing"]))
    return {"ctx": ctx, "eng": eng, "days": days, "reg": reg, "mons": {m.sid: m for m in mons}, "tab": tab, "st": ml.state(),
            "fits": ml.FITS["n"] - n0, "took": took, "models": dict(ml._MODELS)}


# ================================================================================================ the trees
def test_the_trees_learn_a_rule_route_missing_values_and_explain_each_prediction():
    rnd = random.Random(5)
    X, y = [], []
    for _ in range(400):
        a, b = rnd.gauss(0, 1), rnd.gauss(0, 1)
        c = None if rnd.random() < 0.3 else rnd.gauss(0, 1)                # (a third missing: those rise more often)
        up = (a > 0.3) if c is not None else (a > -0.8)
        X.append([a, b, c, 7.0])                                            # (the last one constant: never split on)
        y.append(int(up) if rnd.random() > 0.1 else 1 - int(up))
    t = ml.Trees.fit(X, y, seed=3)
    hit = sum(1 for x, v in zip(X, y) if (t.prob(x) > 0.5) == (v == 1)) / len(X)
    imp = t.importance()
    assert hit > 0.8 and max(range(4), key=lambda j: imp[j]) == 0 and imp[2] > imp[1] and imp[3] == 0.0
    assert t.prob([0.0, 0.0, None, 7.0]) > t.prob([0.0, 0.0, 0.0, 7.0])           # (missing goes its own, learnt way)
    # each prediction's log-odds = the prior + every tree's root + the features' path contributions, to the bit's error
    roots = sum(tree[0][5] for tree in t.trees)
    for x in X[:50]:
        assert t.logit(x) == pytest.approx(t.base + roots + sum(t.contributions(x)), abs=1e-12)
    # the same rows and seed: the same trees; another seed: other ones
    assert ml.Trees.fit(X, y, seed=3).trees == t.trees and ml.Trees.fit(X, y, seed=4).trees != t.trees
    # no model anywhere (the recorded month): no features' table
    assert ml.importance_by_group({}) == {"groups": [], "rows": [], "models": {}}


# ================================================================================================ the universe
def test_the_universe_is_the_plan_s_forty_odd_lines_by_the_registry_s_keys():
    ctx, eng, _ = sm.context()
    reg = qu.Registry(ctx, None, eng)
    insts, missing = ml.universe(reg)
    keys = [i.key for i in insts]
    assert not missing and len(keys) == len(set(keys)) == 42
    assert set(ml.FIXED) <= set(keys) and all(k in reg for k in keys)
    assert [k for k in keys if k.startswith("FX:")] == ["FX:" + p for p in qu.G10_PAIRS]
    assert [k for k in keys if k.startswith("FXV:")] == ["FXV:" + p for p in qu.G10_PAIRS]                 # (ATM 3M)
    assert {"OISS:3M/1Y", "OISS:6M/2Y", "OISS:1Y/2Y", "OISS:2Y/5Y", "OISF:3M/6M/1Y", "OISF:6M/1Y/2Y", "PPK:1"} <= set(keys)
    assert [k for k in keys if k.startswith("FRA:")] == ["FRA:3x6", "FRA:6x9", "FRA:12x15"]                 # (no 12×18 on the grid)
    # the DİBS benchmarks nearest 2 / 5 / 10 years (by ISIN), the VİOP front, the offshore lines with their limit
    assert [k for k in keys if k.startswith("DIBS:")] == ["DIBS:" + isin for isin, _, _ in sm.BONDS]
    assert [k for k in keys if k.startswith("VIOP:")] == ["VIOP:" + sm.CONTRACTS[0]]
    off = [i for i in insts if i.group == "Offshore"]
    assert [i.key for i in off] == ["FWD:USDTRY:1M", "FWD:USDTRY:3M", "FXP:USDTRY:3M", "OFF:1Y"] and all(i.tag == "offshore limiti" for i in off)
    # the list's order (G10 spot first, TRY OIS's short end before its long end, Offshore last)
    pr = [i.priority for i in insts]
    assert pr == sorted(pr) and insts[0].group == "G10 spot" and insts[-1].group == "Offshore"
    # a planned line the registry has not is said so (and the rest stay)
    ctx2, eng2, _ = sm.context(keep={k for k in ctx.series if k != "FX:NZDUSD" and not k.startswith("OPT:NZDUSD")})
    insts2, missing2 = ml.universe(qu.Registry(ctx2, None, eng2))
    assert missing2 == {"FX:NZDUSD": "seri yok"} and "FX:NZDUSD" not in {i.key for i in insts2} and "FXV:NZDUSD" in {i.key for i in insts2}


# ================================================================================================ known answers
def test_a_planted_driver_is_found_out_of_sample_its_line_prints_and_it_ranks_top(fitted):
    st, ctx = fitted["st"], fitted["ctx"]
    line = st.lines["FX:AUDUSD"]
    rec = line.rec
    assert rec["tests"] >= 40 and rec["hit"] >= 0.62 and rec["log_loss"] < 0.65 and line.valid
    # the driver - Brent's last five moves, the day before - tops the trees' gain, in every month's model
    imp = dict(zip(ml.NAMES, line.model.importance()))
    assert max(imp, key=imp.get) == "brent_5" and imp["brent_5"] > 0.3
    assert all(max(zip(m.importance(), ml.NAMES))[1] in ("brent_5", "brent_1") for m in line.models.values())
    # the line: the plan's form, a target of (2p − 1) × the mean |5-day P&L|, a stop of 1,5 σ of five days, five days
    m = fitted["mons"]["ml:FX:AUDUSD"]
    qf.score_all(ctx, [m], {})
    sg = qf.make_signal(m, ctx.cfg, "10:00")
    p = m.info["p"]
    assert sg is not None and not sg["gated"] and p >= 0.6 and sg["direction"] == 1
    got = LINE.match(sg["expression"])
    assert got and got.group(1) == "AL" and int(got.group(2)) == round(p * 100) and int(got.group(3)) == round(rec["hit"] * 100)
    assert int(got.group(4)) == rec["tests"]
    level = m.level
    # (its target and stop: the levels calibrated on the family's out-of-sample trades - their own test below)
    lv = sg["levels"]
    assert lv["ok"] and sg["rr"] >= 1.0 and sg["hold"] == 5.0
    sigma = level * line.sd1 * math.sqrt(5) / 100.0
    assert sg["target"] == pytest.approx(level + lv["m"] * sigma) and sg["stop"] == pytest.approx(level - lv["k"] * sigma)
    # its size and money through the registry: 1 mn AUD, P&L in USD, the spot's price
    assert sg["px"]["inst"] == "AUDUSD spot" and sg["money"]["ccy"] == "USD" and sg["money"]["base"] == "AUD" and sg["money"]["total"] > 0
    # the card: what to do and why - the three features that moved it most, in the desk's words; the record with log-loss
    why = sg["info"]["why"]
    assert len(why) == 3 and why[0]["name"] == "brent_5" and why[0]["effect"] > 0
    assert sg["plain"].startswith("Şimdi spot AUDUSD alıp ~5 iş günü tutarsan")
    assert "Neden: en çok Brent son 5 günde +%12,5 (lehte)" in sg["plain"] and "log-loss" in sg["plain"]
    assert "log-loss" in sg["thesis"] and sg["expression"] in sg["thesis"]
    gates = {g["name"]: g for g in sg["gates"]}
    assert gates["Örneklem"]["ok"] and "örneklem dışı isabet" in gates["Örneklem"]["text"]
    # in the list: G10 spot
    assert qu.classify(sg)["group"] == "G10 spot"
    # the page's row says the same
    row = next(r for r in fitted["tab"]["rows"] if r["key"] == "FX:AUDUSD")
    assert row["prints"] and row["valid"] and row["top"][0]["name"] == "brent_5" and row["verb"] == "AL"
    # the measured time of the real size: within a few minutes
    assert fitted["took"] < 300.0 and fitted["fits"] == fitted["tab"]["timing"]["fitted"] > 500


def test_the_levels_are_calibrated_on_the_family_s_out_of_sample_trades(fitted):
    """Every line's out-of-sample predictions past the entry are trades (one at a time a line, five closes, in σ of the
    five days as known that day); their group's levels (quantlevels: a month at a time) set the line's target and stop
    - the planted AUDUSD's group G10 spot -, Ödül / risk ≥ 1, the record's hit rate and expectancy on the card; a backtest
    refit's line takes the levels of its day's month."""
    st, ctx = fitted["st"], fitted["ctx"]
    line = st.lines["FX:AUDUSD"]
    entry = float(ctx.cfg["entry_z"])
    trades = line.level_trades(entry)
    days = [r.day for r in line.rows]
    assert len(trades) >= 30 and all(t["family"] == "ml" and t["group"] == "G10 spot" and 1 <= len(t["path_sigma"]) <= ml.HORIZON for t in trades)
    for a, b in zip(trades, trades[1:]):                                 # (one at a time: the next after the five closes)
        assert days.index(b["entry_day"]) - days.index(a["entry_day"]) >= ml.HORIZON
    for t in trades:
        p = line.preds[t["entry_day"]]
        assert abs(p - 0.5) / ml.Z_SCALE >= entry
        i = next(r.i for r in line.rows if r.day == t["entry_day"])
        s = 1 if p > 0.5 else -1
        unit = line.scale[t["entry_day"]][1] * math.sqrt(ml.HORIZON)
        assert t["path_sigma"][0] == pytest.approx(s * qf.change("fx", line.L[i], line.L[i + 1]) / unit)
    # the planted line's trades earn: its group's levels have a positive record (out of sample)
    book = line.book
    lv = book.line("G10 spot")
    assert lv["ok"] and lv["rr"] >= 1.0 and lv["exp"] > 0 and lv["n"] >= qlv.MIN_OOS and fitted["tab"]["levels"]["family"] == "ml"
    m = fitted["mons"]["ml:FX:AUDUSD"]
    qf.score_all(ctx, [m], {})
    sg = qf.make_signal(m, ctx.cfg, "10:00")
    assert sg["levels"]["n"] == lv["n"] and sg["levels"]["hit"] == lv["hit"] and sg["rr"] == pytest.approx(lv["m"] / lv["k"])
    assert "Seviyeler geçmiş işlemlerden" in sg["plain"] and not sg["gated"]
    # a refit's line (the backtest): its day's month's levels, its σ that day's
    ml._STATE = st
    T = fitted["days"][-60]
    cT = qf.Ctx(dict(ctx.cfg), dt.date.fromisoformat(T) + dt.timedelta(days=1), ctx.series, {k: dict(v) for k, v in ctx.meta.items()}, {},
                mpc=ctx.mpc)
    rm = next(x for x in ml.run(cT, qu.Registry(cT), ctx.cfg)[0] if x.sid == "ml:FX:AUDUSD")
    t = fitted["days"][-55]
    cT.today, cT.today_iso = dt.date.fromisoformat(t), t
    qf.score_all(cT, [rm], {k: v[t] for k, v in ctx.series.items() if t in v})
    want = book.line("G10 spot", qlv.month_of(t))
    assert rm.levels["ok"] == want["ok"]
    if want["ok"]:
        assert (rm.levels["k"], rm.levels["m"]) == (want["k"], want["m"])
        assert rm.levels["sigma"] == pytest.approx(rm.level * line.scale[t][1] * math.sqrt(ml.HORIZON) / 100.0)


def test_pure_noise_does_not_pass_the_rule_and_does_not_print(fitted):
    st = fitted["st"]
    recs = [st.lines[k].rec for k in NOISE]
    assert all(r["tests"] >= 40 for r in recs)                        # (tests enough: it is the hit rate that holds them back)
    assert not any(st.lines[k].valid for k in NOISE) and not any("ml:" + k in fitted["mons"] for k in NOISE)
    hits = [r["hit"] for r in recs]
    assert max(hits) < 0.55 and 0.40 < sum(hits) / len(hits) < 0.55
    assert sum(r["log_loss"] for r in recs) / len(recs) > 0.69          # (no skill: a coin's log-loss is 0,693)
    for k in NOISE:
        assert next(r for r in fitted["tab"]["rows"] if r["key"] == k)["why"].startswith("örneklem dışı isabet %")
    # the planted line without its driver: noise as well
    ml.reset()
    ctx, eng, _ = sm.context(plant=None, keep={"FX:AUDUSD", "FXP:AUDUSD:3M"})
    reg = qu.Registry(ctx, None, eng)
    mons, tab = ml.run(ctx, reg, ctx.cfg)
    line = ml.state().lines["FX:AUDUSD"]
    assert line.rec["tests"] >= 40 and line.rec["hit"] < 0.55 and not line.valid and "ml:FX:AUDUSD" not in {m.sid for m in mons}


def _future_changed(days, series, cut, seed=99):
    """The same history to ``cut``; after it every series moved by noise of its own size."""
    rnd = random.Random(seed)
    out = {}
    for k, pts in series.items():
        vals = [v for d, v in sorted(pts.items()) if d <= cut]
        scale = max(1e-9, sum(abs(v) for v in vals[-20:]) / max(1, len(vals[-20:])))
        out[k] = {d: (v if d <= cut else v * (1.0 + rnd.gauss(0, 0.03)) + rnd.gauss(0, 0.01 * scale)) for d, v in pts.items()}
    return out


def test_no_look_ahead_the_future_changed_every_earlier_prediction_is_the_same():
    keys = ("FX:AUDUSD", "OIS:2Y", "OISS:1Y/2Y", "FXV:EURUSD", "DIBS:TRT150531T17", "FWD:USDTRY:1M")
    days, series, meta = sm.build(plant=sm.PLANT)
    cut = days[-90]
    preds = []
    for ser in (series, _future_changed(days, series, cut)):
        ml.reset()                                                     # (every model fitted again: nothing from the cache)
        ctx = qf.Ctx(dict(qf_cfg()), sm.TODAY, {k: dict(v) for k, v in ser.items()}, {k: dict(v) for k, v in meta.items()}, {},
                     mpc=sm.mpc_of(days[-120:] + [sm.TODAY.isoformat()]))
        reg = qu.Registry(ctx, None, sm.eng_rows())
        inputs = ml.Inputs(reg)
        out = {}
        for k in keys:
            rows = ml.rows_of(reg[k], inputs)[0]
            out[k] = ml.walk(k, rows, ctx.today_iso)["preds"]
        preds.append(out)
    a, b = preds
    for k in keys:
        early = sorted(d for d in a[k] if d <= cut)
        assert len(early) > 150 and [a[k][d] for d in early] == [b[k][d] for d in early], k
        assert any(a[k][d] != b[k].get(d) for d in a[k] if d > cut), k     # (the future did change)


def qf_cfg():
    from tto import quant as qq
    return dict(qq.DEFAULTS, usdtry=42.0)


def test_each_month_s_model_learns_only_what_was_known_before_it_and_predicts_only_that_month(fitted):
    st, ctx = fitted["st"], fitted["ctx"]
    for key in ("OISS:1Y/2Y", "FX:AUDUSD"):
        line = st.lines[key]
        known = [r for r in line.rows if r.y is not None]
        months = [m["month"] for m in line.months]
        # every calendar month from the first with enough known rows to today's: more than a year out of sample
        assert months[-1] == ctx.today_iso[:8] + "01" and len(months) >= 13
        for a, b in zip(months, months[1:]):
            d = dt.date.fromisoformat(a)
            assert b == dt.date(d.year + d.month // 12, d.month % 12 + 1, 1).isoformat()
        first = months[0]
        assert sum(1 for r in known if r.end < first) >= ml.MIN_TRAIN
        d = dt.date.fromisoformat(first) - dt.timedelta(days=1)
        assert sum(1 for r in known if r.end < d.replace(day=1).isoformat()) < ml.MIN_TRAIN      # (the month before: too few)
        for m in line.months:
            # fitted on the rows whose label was known before the month began - all of them, none after
            assert m["train"] == sum(1 for r in known if r.end < m["month"]) and m["last_end"] < m["month"]
        # every prediction is its own month's model's; a row of a month without a model has none
        for r in line.rows:
            M = r.day[:8] + "01"
            if M in line.models:
                assert line.preds[r.day] == line.models[M].prob(r.x)
            else:
                assert r.day not in line.preds and r.day < first
        assert len({id(m) for m in line.models.values()}) == len(line.models) and line.model is line.models[months[-1]]
        # the label: the up side's P&L over the next five closes (FX with the carry of the holding)
        pts = line.pts
        r = line.rows[100]
        move = qf.change(line.inst.kind, pts[r.i][1], pts[r.i + 5][1])
        if key.startswith("FX:"):
            move += line.carry[r.day] * (dt.date.fromisoformat(r.end) - dt.date.fromisoformat(r.day)).days / 365.0
        assert r.end == pts[r.i + 5][0] and r.pnl == pytest.approx(move) and r.y == (1 if move > 0 else 0)


def test_the_daily_training_keeps_to_its_budget():
    """A reduced size (8 lines × 300 days) from nothing: within budget; the same closes again fit nothing."""
    ml.reset()
    keep = {"FX:EURUSD", "FXP:EURUSD:3M", "FX:AUDUSD", "FXP:AUDUSD:3M", "FXV:EURUSD", "OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y", "OFF:1Y",
            "FX:USDTRY", "FXP:USDTRY:1M", "FXP:USDTRY:3M"}
    ctx, eng, days = sm.context(n=300, plant=sm.PLANT, keep=keep)
    reg = qu.Registry(ctx, None, eng)
    t0 = time.perf_counter()
    _, tab = ml.run(ctx, reg, ctx.cfg)
    took = time.perf_counter() - t0
    n = tab["timing"]["fitted"]
    print("\nML, küçük boyut: %d satır × %d gün, %d model %.1f sn (model başına %.0f ms)" % (tab["lines"], len(days), n, took, 1000.0 * took / max(1, n)))
    assert tab["lines"] >= 8 and n >= 30 and took < 60.0 and took / n < 0.5
    n0 = ml.FITS["n"]
    t0 = time.perf_counter()
    _, tab2 = ml.run(ctx, qu.Registry(ctx, None, eng), ctx.cfg)
    assert ml.FITS["n"] == n0 and tab2["timing"]["fitted"] == 0 and tab2["timing"]["cached"] == n and time.perf_counter() - t0 < took


def test_the_models_survive_a_live_refresh_and_a_second_fit_of_the_same_closes(fitted):
    ctx, st = fitted["ctx"], fitted["st"]
    with ml._MODELS_LOCK:                                              # (the fit's models, whatever ran in between)
        ml._MODELS.clear()
        ml._MODELS.update(fitted["models"])
    m = fitted["mons"]["ml:FX:AUDUSD"]
    line = st.lines["FX:AUDUSD"]
    model = line.model
    n0 = ml.FITS["n"]
    qf.score_all(ctx, [m], {})
    p0, z0 = m.info["p"], m.z
    # a live refresh: the level now and the curve now in the features, the same trees
    live = {"FX:AUDUSD": m.level * 1.02, "OIS:2Y": ctx.last("OIS:2Y") + 0.5, "OIS:5Y": ctx.last("OIS:5Y") + 0.2, "OIS:10Y": ctx.last("OIS:10Y")}
    qf.score_all(ctx, [m], live)
    assert m.info["p"] != p0 and m.z != z0 and line.model is model and ml.FITS["n"] == n0
    assert line.now[1][:ml.N_OWN] != line.row_now(m.level / 1.02, {})[:ml.N_OWN]
    # a second fit of the day on the same closes: every model from the cache, the same predictions
    mons2, tab2 = ml.run(ctx, qu.Registry(ctx, None, fitted["eng"]), ctx.cfg)
    st2 = ml.state()
    assert ml.FITS["n"] == n0 and tab2["timing"]["fitted"] == 0 and tab2["timing"]["cached"] == fitted["fits"]
    for key, l1 in st.lines.items():
        l2 = st2.lines[key]
        assert l2.preds == l1.preds and all(l2.models[M] is l1.models[M] for M in l1.models), key
    assert {mm.sid for mm in mons2} == set(fitted["mons"])


def test_a_calendar_edit_a_viop_roll_and_a_new_bond_move_no_line_s_state():
    """The DİBS RV list gets a new bond on top (every row below one down) nearer five years than the old benchmark; the
    VİOP sheet's columns move at a roll; a meeting is added to the calendar (today's path).  Every line keeps its own
    models - the same objects - and predictions; the new bond fits its own; nothing else is fitted."""
    ml.reset()
    keep = {"OIS:1Y", "OIS:2Y", "OIS:5Y", "OIS:10Y", "OIS:3M", "FX:USDTRY"} | {"DIBS:" + b[0] for b in sm.BONDS} | {"VIOPF:" + t for t in sm.CONTRACTS}
    days, series, meta = sm.build()
    series = {k: v for k, v in series.items() if k in keep or k in sm.DRIVERS or k in {"FX:" + p for p in sm.EM}}
    meta = {k: v for k, v in meta.items() if k in series}
    mpc = sm.mpc_of(days[-120:] + [sm.TODAY.isoformat()])
    eng = sm.eng_rows()
    eng["viopq"] = [{"ticker": t, "n": i + 1} for i, t in enumerate(sm.CONTRACTS)]
    ctx = qf.Ctx(qf_cfg(), sm.TODAY, {k: dict(v) for k, v in series.items()}, {k: dict(v) for k, v in meta.items()}, {}, mpc=mpc)
    _, tab1 = ml.run(ctx, qu.Registry(ctx, None, eng), ctx.cfg)
    st1 = ml.state()
    n1 = ml.FITS["n"]
    # the edits
    new = "TRT050631T16"
    old5 = "DIBS:" + sm.BONDS[1][0]
    lvl = series["OIS:5Y"]
    s2 = dict(series, **{"DIBS:" + new: {d: v - 0.1 + 0.02 * math.sin(i / 3.0) for i, (d, v) in enumerate(sorted(lvl.items()))}})
    m2 = dict(meta, **{"DIBS:" + new: {"label": new, "kind": "rate", "group": "dibs", "unit": "pct", "type": "S", "name": "",
                                      "maturity": (sm.TODAY + dt.timedelta(days=int(5.0 * 365.25))).isoformat()}})
    eng2 = {"dibs": [{"isin": new, "type": "S", "row": 5, "name": "", "maturity": m2["DIBS:" + new]["maturity"], "coupon": 29.0, "freq": 2.0,
                      "simple": 0.35, "compound": 0.38, "source": ""}] + [dict(r, row=r["row"] + 1) for r in eng["dibs"]],
            "viopq": [{"ticker": sm.CONTRACTS[1], "n": 1}, {"ticker": "A1M7 Curncy", "n": 2}]}
    mpc2 = {"days": dict(mpc["days"]), "values": list(mpc["values"])}
    mpc2["values"] += [{"day": sm.TODAY.isoformat(), "meeting": "2026-11-20", "level": 0.395}]
    ctx2 = qf.Ctx(qf_cfg(), sm.TODAY, {k: dict(v) for k, v in s2.items()}, {k: dict(v) for k, v in m2.items()}, {}, mpc=mpc2)
    reg2 = qu.Registry(ctx2, None, eng2)
    _, tab2 = ml.run(ctx2, reg2, ctx2.cfg)
    st2 = ml.state()
    # the new bond is the 5-year benchmark now, with models of its own; the old one is out
    assert "DIBS:" + new in st2.lines and old5 in st1.lines and old5 not in st2.lines
    assert ml.FITS["n"] - n1 == len(st2.lines["DIBS:" + new].models) > 0
    assert not set(map(id, st2.lines["DIBS:" + new].models.values())) & {id(m) for l in st1.lines.values() for m in l.models.values()}
    # every other line: its own models, the same objects, and the same predictions
    same = [k for k in st1.lines if k in st2.lines]
    assert len(same) >= 6 and "VIOP:" + sm.CONTRACTS[0] in same and "DIBS:" + sm.BONDS[0][0] in same and "PPK:1" in same
    for k in same:
        l1, l2 = st1.lines[k], st2.lines[k]
        assert set(l1.models) == set(l2.models) and all(l1.models[M] is l2.models[M] for M in l1.models), k
        assert l1.preds == l2.preds, k
    # the PPK line follows its meeting by date: today's period is after the added meeting
    assert reg2["PPK:1"].meeting()[0] == "2026-11-20"


def test_the_backtest_replays_the_walk_forward_s_own_predictions(fitted):
    st, ctx = fitted["st"], fitted["ctx"]
    ml._STATE = st                                                     # (the module's last fit: this one's)
    days = fitted["days"]
    series = {k: dict(v) for k, v in sm.build(plant=sm.PLANT)[1].items()}
    cfg = dict(ctx.cfg)
    n0 = ml.FITS["n"]

    def make_ctx(T):
        nxt = dt.date.fromisoformat(T) + dt.timedelta(days=1)
        mpc = sm.mpc_of(days[-120:])
        mp = {"days": {d: x for d, x in mpc["days"].items() if d <= T}, "values": [r for r in mpc["values"] if r["day"] <= T]}
        return qf.Ctx(cfg, nxt, series, {k: dict(v) for k, v in ctx.meta.items()}, {}, mpc=mp)

    T = days[-60]
    cT = make_ctx(T)
    mons, tab = ml.run(cT, qu.Registry(cT), cfg)
    assert tab.get("replay") and ml.FITS["n"] == n0
    by = {m.sid: m for m in mons}
    assert set(by) == {"ml:" + k for k, l in st.lines.items() if l.preds and k in qu.Registry(cT)}
    # a day after the refit: that day's own out-of-sample prediction, the line's own close
    t = days[-55]
    cT.today, cT.today_iso = dt.date.fromisoformat(t), t
    qf.score_all(cT, mons, {k: v[t] for k, v in series.items() if t in v})
    aud = by["ml:FX:AUDUSD"]
    line = st.lines["FX:AUDUSD"]
    assert aud.z == pytest.approx((line.preds[t] - 0.5) / ml.Z_SCALE) and aud.level == line.levels[t] and aud.info["version"] == "AUDUSD spot"
    # the family's backtest: the predictions as trades with the live rules, per line (its type) - nothing fitted
    res = qbt.backtest(days[-120:], make_ctx, lambda c: ml.run(c, qu.Registry(c), cfg)[0], series, cfg, step=10)
    fam = res["families"]["ml"]
    assert ml.FITS["n"] == n0 and res["complete"] and fam["trades"] > 0 and fam["sharpe"] is not None
    assert "AUDUSD spot" in fam["types"] and fam["types"]["AUDUSD spot"]["hit"] > 0.5 and fam["types"]["AUDUSD spot"]["trades"] >= 3
    assert all(t["family"] == "ml" for t in res["trades"])


# ================================================================================================ the service
@pytest.fixture(scope="module")
def served(module_service):
    svc = module_service
    svc.quant.use_live = False
    ml.reset()
    sm.seed(svc, plant=sm.PLANT)
    return svc


def test_the_page_the_list_and_the_backtest_through_the_service(served):
    svc = served
    q = svc.quant
    n0 = ml.FITS["n"]
    st = q.compute()
    assert st["ready"] and not st["errors"].get("ml") and "ml" in st["timing"] and ml.FITS["n"] > n0
    user = svc.login("ml okuyucu")["user"]
    v = q.view("ml", user, {})
    tab = v["ml"]
    rows = {r["key"]: r for r in tab["rows"]}
    aud = rows["FX:AUDUSD"]
    assert aud["valid"] and aud["prints"] and aud["tests"] >= 40 and aud["hit"] >= 0.6 and aud["top"][0]["name"] == "brent_5" and aud["sid"] == "ml:FX:AUDUSD"
    assert all(r.get("why") or r.get("prints") for r in tab["rows"])           # (every line says why it does not print)
    assert "G10 spot" in tab["groups"]["groups"] and tab["groups"]["rows"][0]["shares"] and tab["settings"]["trees"] == ml.TREES
    assert [s["id"] for s in v["signals"]] and all(s["family"] == "ml" for s in v["signals"])
    # a line a gate of the list holds ("düşük güven": the FX carry buffer, no expected profit) says so on the page
    for s in q.view("signals", user, {})["gated"]:
        if s["family"] == "ml":
            row = next(r for r in tab["rows"] if r.get("sid") == s["id"])
            assert not row["prints"] and row["why"] == "düşük güven: " + s["gated"], s["id"]
    # the Sinyaller list: the line in the plan's form, in its group
    sigs = q.view("signals", user, {"family": "ml"})["signals"]
    line = next(s for s in sigs if s["id"] == "ml:FX:AUDUSD")
    assert LINE.match(line["expression"]) and line["group"] == "G10 spot" and line["family_label"] == "Makine öğrenmesi" and not line["gated"]
    # the models survive a live refresh and a second fit of the same closes
    mon = q._fit["mons"]["ml:FX:AUDUSD"]
    n1 = ml.FITS["n"]
    q.refresh_live()
    assert ml.FITS["n"] == n1 and q._fit["mons"]["ml:FX:AUDUSD"] is mon and mon.z is not None
    q.compute()
    assert ml.FITS["n"] == n1 and q._fit["tables"]["ml"]["timing"]["fitted"] == 0
    # the backtest: the family's row and its lines, nothing fitted
    res = q.run_backtest(days=60, step=20)
    assert "ml" in res["families"] and ml.FITS["n"] == n1
    bt = q.view("backtest", user, {})
    assert any(r["family"] == "ml" and not r["type"] for r in bt["rows"]) and any(r["family"] == "ml" and r["type"] for r in bt["rows"])
    # (the HTTP part last)
    with TestClient(create_app(svc), headers=auth(svc, "ML HTTP")) as client:
        r = client.get("/api/quant/ml").json()
        assert r["ready"] and {x["key"] for x in r["ml"]["rows"]} == set(rows) and r["signals"]
        nav = [p for p in client.get("/api/nav").json()["pages"] if p["group"] == "Quant"]
        page = next(p for p in nav if p["id"] == "quant-ml")
        assert page["menu"] == "quant.sinyal" and page["tab"] == "Makine öğrenmesi" and nav[0]["id"] == "quant"
        assert client.get("/static/js/pages/quantml.js").status_code == 200
