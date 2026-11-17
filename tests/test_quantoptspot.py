"""The Opsiyon → spot family (``tto/quantoptspot.py``) on synthetic history with known answers
(``quant_synth_optspot.py``): its pairs by their keys - USDTRY in Offshore, EURTRY without options saying so; a planted
lead (USDJPY's spot follows its risk reversal) found out of sample and printed AL in the desk's words with the option
signal behind it; the direction the walk-forward chose (EURUSD goes the other way: SAT after its calls were bid; every
pair the other way: the pooled direction is "ters"); pure noise never prints, not even a pair that passes the 55 % / 40
rule by chance; no look-ahead (the future changed: every earlier signal, forecast and trade the same); the butterfly
scales the levels, never the direction; the live quotes rescore today; the backtest's trades with their paths in
quantbt's format; the measured fit time; the page, the list and the backtest through the service (the HTTP part last:
leaving its client stops the module's service)."""
from __future__ import annotations

import math
import random
import re
import time

import pytest
from starlette.testclient import TestClient

import quant_synth_optspot as so
from conftest import auth
from tto import quantbt as qbt
from tto import quantfam as qf
from tto import quantoptspot as osp
from tto import quantuniv as qu
from tto.server import create_app

#: the line in the desk's words: the option signal behind it, then the trade, its size and record
LINE = re.compile(r"^(?P<driver>.+) → (?P<verb>AL|SAT) (?P<pair>[A-Z]{6}) spot · (?P<size>[\d.,]+ (?:mn|bin) [A-Z]{3}) · isabet %(?P<hit>\d+) "
                  r"\((?P<tests>\d+)\)(?P<tag> · offshore limiti)?$")
FIELDS = {"sid", "family", "type", "entry_day", "exit_day", "dir", "entry", "exit", "outcome", "held", "pnl", "unit", "pnl_sigma", "pnl_try",
          "expression"}


def _fit(**kw):
    osp.reset()
    ctx, days = so.context(**kw)
    mons, tab = osp.run(ctx, qu.Registry(ctx), ctx.cfg)
    return ctx, days, mons, tab, osp.state()


def _signals(ctx, mons, live=None):
    qf.score_all(ctx, mons, live or {})
    out = {}
    for m in mons:
        sg = qf.make_signal(m, ctx.cfg, "10:00")
        if sg is not None:
            out[m.sid] = sg
    return out


@pytest.fixture(scope="module")
def planted():
    """Every pair over two years: USDJPY and USDTRY follow their RR, EURUSD goes against it, today's RR moves pushed."""
    osp.reset()
    ctx, days = so.context(leads=so.LEADS, shock=so.SHOCK)
    reg = qu.Registry(ctx)
    t0 = time.perf_counter()
    mons, tab = osp.run(ctx, reg, ctx.cfg)
    took = time.perf_counter() - t0
    print("\nOpsiyon → spot: %d parite × %d gün, %d satır, %d aylık model %.2f sn (%s)" % (
        tab["timing"]["pairs"], len(days), tab["timing"]["rows"], tab["timing"]["models"], took, tab["timing"]))
    return {"ctx": ctx, "days": days, "reg": reg, "mons": {m.sid: m for m in mons}, "tab": tab, "rows": {r["pair"]: r for r in tab["rows"]},
            "sigs": _signals(ctx, mons), "st": osp.state(), "took": took}


# ================================================================================================ the pairs
def test_the_pairs_by_their_keys_usdtry_in_offshore_eurtry_without_options_says_why(planted):
    rows = planted["tab"]["rows"]
    assert [r["pair"] for r in rows] == list(osp.PAIRS) and [r["key"] for r in rows] == ["FX:" + p for p in osp.PAIRS]
    assert all(r["group"] == "G10 spot" and not r["tag"] and r["label"] == r["pair"] + " spot" for r in rows if r["pair"] in qu.G10_PAIRS)
    usd = planted["rows"]["USDTRY"]
    assert usd["group"] == "Offshore" and usd["tag"] == "offshore limiti" and usd["size"].endswith(" USD") and usd["valid"]
    eur = planted["rows"]["EURTRY"]
    assert eur["group"] == "Offshore" and not eur["prints"] and eur["why"] == "opsiyon serisi yok: EURTRY'nin ATM / 25D RR kotası tutulmuyor"
    # the quotes by the universe's keys: the series the registry's option lines and the Opsiyon page read
    keys = osp.quote_keys("USDJPY")
    assert keys == {"atm1": "OPT:USDJPY:ATM:1M", "atm3": "FXV:USDJPY", "rr1": "OPT:USDJPY:RR25:1M", "rr3": "FXR:USDJPY", "bf3": "OPT:USDJPY:BF25:3M"}
    assert all(k in planted["reg"] for k in keys.values()) and osp.quote_keys("USDTRY")["rr1"] == "OPT:USDTRY:RR25:1M"
    # a pair the history does not keep: its row says so, the rest go on
    ctx, _, mons, tab, _ = _fit(leads=so.LEADS, shock=so.SHOCK, drop=("FX:NZDUSD",))
    rows2 = {r["pair"]: r for r in tab["rows"]}
    assert rows2["NZDUSD"]["why"] == "seri yok" and not rows2["NZDUSD"]["prints"] and rows2["USDJPY"]["valid"]
    # a pair whose history is short: its closes and the least it needs
    ctx, _, _, tab, _ = _fit(n=200, leads=so.LEADS, shock=so.SHOCK)
    assert all(r["why"] == "geçmiş kısa (200 kapanış; en az %d)" % osp.MIN_CLOSES for r in tab["rows"] if r["pair"] != "EURTRY")
    # a pair whose options are still filling (their two years not in yet), its spot long: it says so
    days, series, _ = so.build(leads=so.LEADS, shock=so.SHOCK)
    mine = set(osp.quote_keys("USDJPY").values())
    short = {k: ({d: v for d, v in pts.items() if d >= days[-150]} if k in mine else pts) for k, pts in series.items()}
    _, _, _, tab, _ = _fit(leads=so.LEADS, shock=so.SHOCK, series=short)
    row = {r["pair"]: r for r in tab["rows"]}["USDJPY"]
    assert row["why"] == "opsiyon geçmişi kısa (25D RR 150, ATM 150 kapanış; en az %d)" % osp.MIN_CLOSES and not row["prints"]


# ================================================================================================ known answers
def test_a_planted_lead_is_found_out_of_sample_and_prints_in_its_direction(planted):
    row, st, ctx = planted["rows"]["USDJPY"], planted["st"], planted["ctx"]
    line = st.lines["FX:USDJPY"]
    assert row["valid"] and row["tests"] >= 40 and row["hit"] >= 0.58 and row["prints"] and row["sid"] == "optspot:FX:USDJPY"
    sg = planted["sigs"]["optspot:FX:USDJPY"]
    assert not sg["gated"] and sg["direction"] == 1
    got = LINE.match(sg["expression"])
    assert got and got["verb"] == "AL" and got["pair"] == "USDJPY" and not got["tag"] and sg["line"] == sg["expression"]
    # the option signal behind it, in the desk's words: the risk reversal bid this week, the spot not there yet
    assert sg["optspot"]["driver"] in ("drr1", "drr3", "div") and got["driver"].startswith("25D RR ")
    assert ("USD call'ları pahalandı" in got["driver"] or "oynadı, spot ise" in got["driver"]) and got["driver"].endswith(", spot henüz gelmedi")
    assert int(got["hit"]) == round(row["hit"] * 100) and int(got["tests"]) == row["tests"] and got["size"] == line.inst.size_text(line.k)
    # levels from the option-implied week: σ = ATM 1M × √(5/252) × the BF factor; target 1,25σ, stop 1σ, five days
    d = line.now
    sig, level = d["sigma"], sg["level"]
    assert sig == pytest.approx(d["atm"] * math.sqrt(5 / 252.0) * d["f"]) and d["atm"] == ctx.last("OPT:USDJPY:ATM:1M")
    assert sg["target"] == pytest.approx(level * (1 + 1.25 * sig / 100.0)) and sg["stop"] == pytest.approx(level * (1 - sig / 100.0))
    assert sg["rr"] == pytest.approx(1.25) and sg["hold"] == 5.0 and sg["exp_pnl"] == pytest.approx(d["mu_cal"] * sig)
    assert d["p"] == pytest.approx(osp._ND.cdf(d["cal"] * d["mu"] / line.model.s)) and 0.0 <= d["cal"] <= 1.0
    # the size: the desk's weekly 1σ risk over a unit's (1 mn USD) week in USD, two significant figures
    assert line.k == osp._round2(ctx.cfg["optspot_risk_usd"] / abs(line.inst.money(line.h.now(level, {})["sig"] * d["f"], 1.0)))
    # the money through the registry: the spot's price, 1 mn USD, P&L in JPY / USD; the card in plain words
    assert sg["px"]["inst"] == "USDJPY spot" and sg["money"]["base"] == "USD" and sg["money"]["total"] > 0
    assert sg["plain"].startswith("Opsiyon piyasası: 25D RR ") and "Model önümüzdeki 5 iş gününde yükseliş olasılığını %" in sg["plain"]
    assert "Seviyeler opsiyonların ima ettiği 1 haftalık hareketten" in sg["plain"] and sg["thesis"].startswith("Opsiyon → spot: 25D RR ")
    assert sg["info"]["why"][0]["name"] in ("drr1", "drr3", "div") and sg["info"]["why"][0]["with"]
    gates = {g["name"]: g for g in sg["gates"]}
    assert gates["Örneklem"]["ok"] and "örneklem dışı isabet" in gates["Örneklem"]["text"]
    assert qu.classify(sg)["group"] == "G10 spot" and sg["family_label"] == "Opsiyon → spot" and sg["page"] == "quant-optspot"
    # the signal's own record: in USDJPY the RR's weekly move led the spot, the way it moved (momentum)
    rec = {s["name"]: s for s in planted["tab"]["signals"]}
    mine = next(p for p in rec["drr1"]["pairs"] if p["pair"] == "USDJPY")
    assert mine["sign_text"] == "momentum" and mine["leads"] and mine["hit"] >= 0.6 and "USDJPY momentum %" in rec["drr1"]["pairs_text"]
    # the chart's lower panel: the out-of-sample probability day by day as z(p)
    m = planted["mons"]["optspot:FX:USDJPY"]
    assert sum(1 for z in m.zvalues if z is not None) == len(line.preds) and len(m.zvalues) == len(m.days)
    # USDTRY: the planted lead found, SAT after USD puts were bid (it earns the carry: no gate holds it), in Offshore
    tr = planted["sigs"]["optspot:FX:USDTRY"]
    got = LINE.match(tr["expression"])
    assert got and got["verb"] == "SAT" and got["tag"] and not tr["gated"] and qu.classify(tr)["group"] == "Offshore" and tr["tag"] == "offshore limiti"
    assert "USD put'ları pahalandı" in got["driver"] or "-" in got["driver"].split(" vol")[0]


def test_the_direction_is_the_one_the_walk_forward_chose(planted):
    st = planted["st"]
    # EURUSD's spot went against its RR: its calls bid this week → SAT, and the line says the move came back before
    sg = planted["sigs"]["optspot:FX:EURUSD"]
    got = LINE.match(sg["expression"])
    assert planted["rows"]["EURUSD"]["valid"] and got and got["verb"] == "SAT" and sg["direction"] == -1
    assert got["driver"].endswith(", geçmişte bu hareket tersine döndü") and "EUR call'ları pahalandı" in got["driver"]
    d = st.lines["FX:EURUSD"].now
    j = osp.NAMES.index(sg["optspot"]["driver"])
    assert d["coef"][j] < 0 < d["x"][j]
    # the records: each pair its own direction - EURUSD "ters", USDJPY and USDTRY "momentum" - every pair's is
    # "momentum" (the two outweigh the one), the same in every month's model
    rec = {s["name"]: s for s in planted["tab"]["signals"]}
    by = {p["pair"]: p for p in rec["drr1"]["pairs"]}
    assert by["EURUSD"]["sign_text"] == "ters" and by["EURUSD"]["leads"] and by["USDJPY"]["sign"] == by["USDTRY"]["sign"] == 1
    assert rec["drr1"]["sign_text"] == "momentum" and rec["drr1"]["months_same"] == rec["drr1"]["months"] >= 13 and "EURUSD ters" in rec["drr1"]["against"]
    # every pair against its RR: the pooled direction is "ters" and it leads; every pair with it: "momentum"
    for lead, way in ((-1.0, "ters"), (1.0, "momentum")):
        _, _, _, tab, _ = _fit(leads={p: lead for p in so.SPOT})
        s = {x["name"]: x for x in tab["signals"]}["drr1"]
        assert s["sign_text"] == way and s["leads"] and s["hit"] >= 0.6 and s["tests"] >= 40 and s["months_same"] == s["months"]
        assert all(p["sign_text"] == way for p in s["pairs"]) and s["strong_hit"] > 0.6 and s["ic"] > 0.1


def test_pure_noise_does_not_print():
    """Random walks: no pair's line prints - not even where a pair passes the 55 % / 40 rule by chance (seeds 5 and
    21: the calibration keeps a forecast that never came true near a coin's)."""
    passed = 0
    for seed in (11, 5, 21):
        ctx, _, mons, tab, _ = _fit(seed=seed)
        assert _signals(ctx, mons) == {} and not any(r.get("prints") for r in tab["rows"])
        hits = [r["hit"] for r in tab["rows"] if r.get("hit") is not None]
        assert len(hits) == 8 and 0.44 < sum(hits) / len(hits) < 0.53
        assert all(abs(r["p"] - 0.5) < 0.1 for r in tab["rows"] if r.get("p") is not None)
        assert not any(s["leads"] for s in tab["signals"])
        passed += sum(1 for r in tab["rows"] if r.get("valid"))
    assert passed >= 1                                                  # (the rule alone did let one through)


def _future_changed(days, series, cut, seed=99):
    """The same history to ``cut``; after it every series moved by noise of its own size."""
    rnd = random.Random(seed)
    out = {}
    for k, pts in series.items():
        vals = [v for d, v in sorted(pts.items()) if d <= cut]
        scale = max(1e-9, sum(abs(v) for v in vals[-20:]) / max(1, len(vals[-20:])))
        out[k] = {d: (v if d <= cut else v * (1.0 + rnd.gauss(0, 0.02)) + rnd.gauss(0, 0.02 * scale)) for d, v in pts.items()}
    return out


def test_no_look_ahead_the_future_changed_every_earlier_signal_forecast_and_trade_the_same():
    days, series, _ = so.build(leads=so.LEADS, shock=so.SHOCK)
    cut = days[-90]
    early = days[days.index(cut) - osp.HORIZON]                       # (a trade's whole path within the cut)
    runs = []
    for ser in (series, _future_changed(days, series, cut)):
        _, _, _, tab, st = _fit(leads=so.LEADS, shock=so.SHOCK, series=ser)
        runs.append(st)
    a, b = runs
    for key, la in a.lines.items():
        lb = b.lines[key]
        fa = [(r.day, r.x, r.bfz, r.sig) for r in la.h.rows if r.day <= cut]
        assert fa == [(r.day, r.x, r.bfz, r.sig) for r in lb.h.rows if r.day <= cut] and len(fa) > 300, key
        pa = {d: v for d, v in la.preds.items() if d <= cut}
        assert pa == {d: v for d, v in lb.preds.items() if d <= cut} and len(pa) > 250, key
        ta = [t for t in la.trades if t["entry_day"] <= early]
        assert ta == [t for t in lb.trades if t["entry_day"] <= early], key
        assert any(la.preds[d] != lb.preds.get(d) for d in la.preds if d > cut), key       # (the future did change)


def test_the_butterfly_scales_the_levels_never_the_direction():
    # weeks bigger after rich wings (the BF's z of the day before): the fit finds it, the levels widen with it
    ctx, _, mons, tab, st = _fit(leads=so.LEADS, shock=so.SHOCK, bf_vol=0.6)
    line = st.lines["FX:USDJPY"]
    assert line.model.bf_ratio > 0.1 and line.model.bf_t > 2.0
    key = osp.quote_keys("USDJPY")["bf3"]
    level = line.inst.now({})
    lo, hi = dict(line.score(level, {key: so.BF_MEAN - 0.05})), dict(line.score(level, {key: so.BF_MEAN + 0.15}))
    assert hi["bfz"] > 1.5 > -0.5 > lo["bfz"] and hi["f"] > 1.1 > 0.95 > lo["f"]
    assert hi["mu"] == lo["mu"] and hi["p"] == lo["p"] and hi["sigma"] / lo["sigma"] == pytest.approx(hi["f"] / lo["f"])
    m = next(x for x in mons if x.sid == "optspot:FX:USDJPY")
    sl, sh = _signals(ctx, [m], {key: so.BF_MEAN - 0.05})[m.sid], _signals(ctx, [m], {key: so.BF_MEAN + 0.15})[m.sid]
    assert sl["direction"] == sh["direction"] == 1 and sl["z"] == sh["z"]
    assert (sh["target"] - level) / (sl["target"] - level) == pytest.approx(hi["f"] / lo["f"])
    assert (level - sh["stop"]) / (level - sl["stop"]) == pytest.approx(hi["f"] / lo["f"])
    assert sh["composite"] < sl["composite"] and sh["parts"]["bf"] == pytest.approx(1.0 / hi["f"])     # (rich wings: lower in the list)
    # the butterflies replaced by another history's: every forecast and its direction the same (BF is no input to it)
    days, series, _ = so.build(leads=so.LEADS, shock=so.SHOCK)
    other = so.build(seed=99)[1]
    swapped = dict(series, **{osp.quote_keys(p)["bf3"]: other[osp.quote_keys(p)["bf3"]] for p in so.SPOT})
    _, _, _, _, a = _fit(leads=so.LEADS, shock=so.SHOCK)
    _, _, _, _, b = _fit(leads=so.LEADS, shock=so.SHOCK, series=swapped)
    for k, la in a.lines.items():
        assert {d: v[:2] for d, v in la.preds.items()} == {d: v[:2] for d, v in b.lines[k].preds.items()}, k
        assert la.now["mu"] == b.lines[k].now["mu"] and la.now["p"] == b.lines[k].now["p"], k


def test_today_is_scored_again_with_the_live_quotes(planted):
    ctx, st = planted["ctx"], planted["st"]
    m = planted["mons"]["optspot:FX:USDJPY"]
    line = st.lines["FX:USDJPY"]
    model = line.model
    qf.score_all(ctx, [m], {})
    z0 = m.z
    rr1 = osp.quote_keys("USDJPY")["rr1"]
    # the week's RR rise undone on the screen now: the forecast falls back; the same model (nothing fitted)
    qf.score_all(ctx, [m], {rr1: ctx.series[rr1][planted["days"][-5]]})
    assert m.z < z0 and line.model is model and line.now["x"][0] < 0.5
    qf.score_all(ctx, [m], {})
    assert m.z == pytest.approx(z0)


# ================================================================================================ the backtest
def test_the_backtest_s_trades_with_their_paths(planted):
    trades = planted["tab"]["backtest"]["trades"]
    assert trades and all(FIELDS <= set(t) for t in trades) and planted["tab"]["backtest"]["first"] == min(t["entry_day"] for t in trades)
    for t in trades:
        path, k = t["path_sigma"], t["held"]
        assert len(path) == t["horizon"] == osp.HORIZON and t["family"] == "optspot" and t["unit"] == "%"
        assert t["sid"] == "optspot:FX:" + t["type"].split()[0] and t["type"].endswith(" spot") and t["dir"] in (1, -1)
        assert t["mae_sigma"] == pytest.approx(max(0.0, -min(path))) and t["mfe_sigma"] == pytest.approx(max(0.0, max(path)))
        inside = all(-osp.S_MULT < x < osp.T_MULT for x in path[:k - 1])
        if t["outcome"] == "hedef":
            assert path[k - 1] >= osp.T_MULT and inside
        elif t["outcome"] == "stop":
            assert path[k - 1] <= -osp.S_MULT and inside
        else:
            assert t["outcome"] == "süre" and k == osp.HORIZON and all(-osp.S_MULT < x < osp.T_MULT for x in path)
        assert t["pnl_sigma"] == pytest.approx(path[k - 1]) and t["pnl"] == pytest.approx(t["pnl_sigma"] * t["sigma"] + t["carry"])
        assert t["exit"] == pytest.approx(t["entry"] * math.exp(t["dir"] * t["pnl_sigma"] * t["sigma"] / 100.0))
    # one at a time per pair; each opened on a day its probability crossed the entry (it had not the day before)
    st = planted["st"]
    entry = planted["ctx"].cfg["entry_z"]
    for line in st.lines.values():
        days = line.h.days
        for a, b in zip(line.trades, line.trades[1:]):
            assert b["entry_day"] >= a["exit_day"]
        for t in line.trades:
            i = days.index(t["entry_day"])
            assert abs(line.preds[t["entry_day"]][1] - 0.5) / osp.Z_SCALE >= entry
            prev = line.preds.get(days[i - 1])
            assert prev is None or abs(prev[1] - 0.5) / osp.Z_SCALE < entry
            assert t["dir"] == (1 if line.preds[t["entry_day"]][0] > 0 else -1)
    # the planted pairs' trades made money more often than not
    for pair in ("USDJPY", "EURUSD", "USDTRY"):
        r = planted["rows"][pair]
        assert r["trades"] >= 20 and r["trade_hit"] > 0.55, pair
    # into the backtest as a family that walks forward on its own (quantuniv.OWN_BT): by pair, its own span
    assert "optspot" in qu.OWN_BT
    res = {"families": {}, "trades": [], "n_trades": 0}
    qbt.add_own(res, "optspot", trades, planted["tab"]["backtest"]["first"], planted["tab"]["backtest"]["last"])
    fam = res["families"]["optspot"]
    assert fam["own"] and fam["trades"] == len(trades) and {"USDJPY spot", "EURUSD spot", "USDTRY spot"} <= set(fam["types"])
    assert fam["types"]["USDJPY spot"]["hit"] > 0.55 and res["n_trades"] == len(trades)


def test_the_fit_keeps_to_its_budget(planted):
    assert planted["took"] < 10.0 and planted["tab"]["timing"]["total_ms"] < 10000.0
    assert planted["tab"]["timing"]["rows"] > 3000 and planted["tab"]["timing"]["models"] >= 13


# ================================================================================================ the service
@pytest.fixture(scope="module")
def served(module_service):
    svc = module_service
    svc.quant.use_live = False
    osp.reset()
    so.seed(svc, leads=so.LEADS, shock=so.SHOCK)
    return svc


def test_the_page_the_list_and_the_backtest_through_the_service(served, monkeypatch):
    # (the ML family's own tests run it over these closes: here it would only add its minutes)
    monkeypatch.delitem(qu.RUNNERS, "ml", raising=False)
    svc = served
    q = svc.quant
    st = q.compute()
    assert st["ready"] and not st["errors"].get("optspot") and "optspot" in st["timing"]
    user = svc.login("opsiyon spot okuyucu")["user"]
    v = q.view("optspot", user, {})
    tab = v["optspot"]
    rows = {r["pair"]: r for r in tab["rows"]}
    assert set(rows) == set(osp.PAIRS) and "backtest" not in tab and [s["name"] for s in tab["signals"]] == list(osp.NAMES)
    jpy = rows["USDJPY"]
    assert jpy["valid"] and jpy["prints"] and jpy["sid"] == "optspot:FX:USDJPY" and jpy["driver"].startswith("25D RR ") and jpy["verb"] == "AL"
    assert rows["USDTRY"]["group"] == "Offshore" and rows["EURTRY"]["why"].startswith("opsiyon serisi yok")
    assert all(r.get("prints") or r.get("why") for r in tab["rows"])           # (every pair says why it does not print)
    assert v["signals"] and all(s["family"] == "optspot" for s in v["signals"]) and v["coverage"]
    # the Sinyaller list: the line in the desk's words, in its group
    sigs = q.view("signals", user, {"family": "optspot"})["signals"]
    line = next(s for s in sigs if s["id"] == "optspot:FX:USDJPY")
    assert LINE.match(line["expression"]) and line["group"] == "G10 spot" and line["family_label"] == "Opsiyon → spot" and not line["gated"]
    off = next(s for s in sigs if s["id"] == "optspot:FX:USDTRY")
    assert off["group"] == "Offshore" and off["tag"] == "offshore limiti" and LINE.match(off["expression"])["tag"]
    # the live refresh rescores the same lines
    mon = q._fit["mons"]["optspot:FX:USDJPY"]
    q.refresh_live()
    assert q._fit["mons"]["optspot:FX:USDJPY"] is mon and mon.z is not None
    # the backtest: the family's own walk-forward trades, by pair; the line carries its pair's record
    res = q.run_backtest(days=60, step=20)
    fam = res["families"]["optspot"]
    assert fam["own"] and fam["trades"] > 0 and "USDJPY spot" in fam["types"]
    bt = q.view("backtest", user, {})
    assert any(r["family"] == "optspot" and not r["type"] for r in bt["rows"]) and any(r["family"] == "optspot" and r["type"] == "USDJPY spot" for r in bt["rows"])
    assert any(t.get("path_sigma") for t in bt["trades"] if t["family"] == "optspot")
    q.refresh_live()
    sg = next(s for s in q.view("signals", user, {"family": "optspot"})["signals"] if s["id"] == "optspot:FX:USDJPY")
    assert sg["bt"]["trades"] and sg["bt"]["scope"] in ("tür", "aile")
    # (the HTTP part last)
    with TestClient(create_app(svc), headers=auth(svc, "Opsiyon HTTP")) as client:
        r = client.get("/api/quant/optspot").json()
        assert r["ready"] and {x["pair"] for x in r["optspot"]["rows"]} == set(osp.PAIRS) and r["signals"]
        nav = [p for p in client.get("/api/nav").json()["pages"] if p["group"] == "Quant"]
        page = next(p for p in nav if p["id"] == "quant-optspot")
        assert page["menu"] == "quant.fx" and page["tab"] == "Opsiyon → spot" and page["title"] == "Opsiyon → spot"
        assert [p["id"] for p in nav if p.get("menu") == "quant.fx"] == ["quant-fx", "quant-macro", "quant-opt", "quant-optspot"]
        assert client.get("/static/js/pages/quantoptspot.js").status_code == 200
        s = client.get("/api/quant/settings").json()
        assert s["values"]["optspot_risk_usd"] == 10000.0 and s["labels"]["optspot_risk_usd"].startswith("Opsiyon → spot")
