"""Options analytics (``tto/quantopt.py``): the new FX vol tickers and their place in the history's list, a known smile
giving known probabilities (a flat one the lognormal's, an SVI one its own), the moves measured from the forward
(carry-aware), the realized frequencies over the history, and the family's signals on synthetic quotes.  The service
and the HTTP API of the page are in ``test_quantcurve.py`` (one seeded service for both new pages)."""
from __future__ import annotations

import datetime as dt
import math

import pytest

import quant_synth
import quant_synth_extra as qx
from test_fxvol import _quotes_of
from tto import fxvol as fv
from tto import quantfam as qf
from tto import quantopt as qo
from tto.quant import DEFAULTS, HISTORY_DAYS, history_defs, series_specs

TODAY = dt.date(2026, 11, 3)


# ================================================================================================ the tickers
def test_the_new_tickers_and_their_history():
    own = qo.series_specs()
    tickers = [s["ticker"] for s in own]
    # per pair: ATM 1W / 1M / 6M / 1Y, 25D RR 1M, 25D BF 1M / 3M, 10D RR and BF 1M / 3M (ATM 3M and 25D RR 3M are the package's)
    assert len(own) == 2 * 11 + 2 and len(set(tickers)) == len(tickers)
    for t in ("USDTRYV1W BGN Curncy", "USDTRYV1M BGN Curncy", "USDTRYV6M BGN Curncy", "USDTRYV1Y BGN Curncy", "USDTRY25R1M BGN Curncy",
              "USDTRY25B1M BGN Curncy", "USDTRY25B3M BGN Curncy", "USDTRY10R1M BGN Curncy", "USDTRY10R3M BGN Curncy", "USDTRY10B1M BGN Curncy",
              "USDTRY10B3M BGN Curncy", "EURUSDV1M BGN Curncy", "EURUSD10B3M BGN Curncy", "EUR1M Curncy", "EUR3M Curncy"):
        assert t in tickers, t
    assert "USDTRYV3M BGN Curncy" not in tickers and qo.key("USDTRY", "ATM", "3M") == "FXV:USDTRY" and qo.key("USDTRY", "RR25", "3M") == "FXR:USDTRY"
    every = series_specs()
    # the package's own and these, none twice: EURUSD's 3M points are also a pair's forward of the package (kept once); a
    # ticker may come back with another field (USDTRY's day high and low for the VİOP page: one series a field)
    pairs = {(s["ticker"], s.get("field", "PX_LAST")) for s in every}
    assert len(pairs) == len(every) and set(tickers) <= {s["ticker"] for s in every}
    assert sum(1 for s in every if s["ticker"] == "EUR3M Curncy") == 1
    assert [s["ticker"] for s in qo.series_specs("CMPN")][0] == "USDTRYV1W CMPN Curncy"   # the desk's pricing source
    defs = {d.ticker: d for d in history_defs()}
    for t in tickers:
        d = defs[t]
        assert d.group == "Quant" and d.info["backfill"] and d.info["lookback"] == HISTORY_DAYS and d.field == "PX_LAST"
    # the first backfill takes them after the package's own (the forward points with the other points)
    order = [d.info["key"] for d in history_defs()]
    assert all(order.index(k) > order.index("FXR:USDZAR") for k in (s["key"] for s in own if s["key"].startswith("OPT:")))


# ================================================================================================ the distribution
def usdtry_ctx(spot=50.0, fwd=51.5, live=None, tenor="1M"):
    """A context with a short history of the spot and the forward points (so the forward is built) and ``live``."""
    days = quant_synth.business_days(TODAY, 30)
    pts = (fwd - spot) * 1e4
    series = {"FX:USDTRY": {d: spot for d in days}, "FXP:USDTRY:%s" % tenor: {d: pts for d in days}}
    meta = {"FX:USDTRY": {"label": "USDTRY", "kind": "fx"}, "FXP:USDTRY:%s" % tenor: {"label": "pts", "kind": "pts"}}
    for kind, t in qo.SURFACE:
        meta[qo.key("USDTRY", kind, t)] = {"label": kind + t, "kind": "vol"}
    base = {"FX:USDTRY": spot, "FXP:USDTRY:%s" % tenor: pts}
    base.update(live or {})
    return qf.Ctx(dict(DEFAULTS), TODAY, series, meta, live=base)


def lognormal_above(F, K, s, T):
    return fv.ncdf((math.log(F / K) - 0.5 * s * s * T) / (s * math.sqrt(T)))


def test_a_flat_smile_gives_the_lognormal_probabilities():
    ctx = usdtry_ctx(live={qo.key("USDTRY", "ATM", "1M"): 12.0})
    res = qo.implied(ctx, "USDTRY", "1M", ctx.derive_live(ctx.live), (2.0, 5.0))
    F, T = 51.5, 30.4167 / 365.0
    assert res["model"] == "flat" and abs(res["F"] - F) < 1e-9 and abs(res["T"] - T) < 1e-4
    for i, x in enumerate((2.0, 5.0)):
        assert abs(res["up"][i] - lognormal_above(F, F * (1 + x / 100), 0.12, res["T"])) < 1e-12
        assert abs(res["down"][i] - (1 - lognormal_above(F, F * (1 - x / 100), 0.12, res["T"]))) < 1e-12
    assert abs(res["fwd_pct"] - 3.0) < 1e-9 and abs(res["q"]["0.5"] - (math.exp(-0.5 * 0.0144 * res["T"]) - 1) * 100) < 1e-6


def test_a_known_smile_gives_its_own_probabilities():
    """A USDTRY-like SVI smile → the five quotes it makes → the module's smile and probabilities: those of the smile
    itself (Breeden-Litzenberger on the known SVI)."""
    F, T = 51.5, 30.4167 / 365.0
    truth = fv.SviSmile(F, T, a=0.0008, b=0.006, rho=0.45, m=0.015, s=0.05)
    q = _quotes_of(truth, F, T, True)
    live = {qo.key("USDTRY", k, "1M"): q[f] * 100 for k, f in (("ATM", "atm"), ("RR25", "rr25"), ("BF25", "bf25"), ("RR10", "rr10"), ("BF10", "bf10"))}
    ctx = usdtry_ctx(live=live)
    moves = (2.0, 3.0, 5.0)
    res = qo.implied(ctx, "USDTRY", "1M", ctx.derive_live(ctx.live), moves)
    known = fv.Distribution(truth)
    assert res["model"] == "svi" and not res["arbitrage"] and max(abs(v) for v in res["fit"].values()) < 0.01     # vol points
    for i, x in enumerate(moves):
        assert abs(res["up"][i] - known.above(F * (1 + x / 100))) < 2e-4, (x, res["up"][i], known.above(F * (1 + x / 100)))
        assert abs(res["down"][i] - known.cdf(F * (1 - x / 100))) < 2e-4
    assert res["up"][-1] > res["down"][-1]                       # the call wing: USDTRY's upside priced above the downside


def test_the_moves_are_measured_from_the_forward():
    """Carry-aware: the same smile around the same forward gives the same probabilities whatever the spot; the moves
    follow the forward."""
    vols = {qo.key("USDTRY", "ATM", "1M"): 11.0, qo.key("USDTRY", "RR25", "1M"): 5.0, qo.key("USDTRY", "BF25", "1M"): 1.0}
    a = usdtry_ctx(spot=50.0, fwd=51.5, live=vols)
    b = usdtry_ctx(spot=49.0, fwd=51.5, live=vols)
    c = usdtry_ctx(spot=50.0, fwd=53.0, live=vols)
    ra, rb, rc = (qo.implied(x, "USDTRY", "1M", x.derive_live(x.live), (3.0,)) for x in (a, b, c))
    assert abs(ra["up"][0] - rb["up"][0]) < 1e-12 and abs(ra["down"][0] - rb["down"][0]) < 1e-12
    assert abs(ra["up"][0] - rc["up"][0]) < 1e-9                                           # (the shape in K/F)
    assert abs(rb["fwd_pct"] - (51.5 / 49.0 - 1) * 100) < 1e-9


def test_realized_frequencies_from_the_forward():
    days = quant_synth.business_days(TODAY, 200)
    spot = [(d, 100.0 * (1.0 + 0.001 * i)) for i, d in enumerate(days)]
    # each day's forward set so that the spot 30 days on ends +6 %, −4 % or +1 % from it, in turn
    targets = {}
    ends = (1.06, 0.96, 1.01)
    ds = [d for d, _ in spot]
    vs = dict(spot)
    import bisect
    for i, d in enumerate(days):
        t = (dt.date.fromisoformat(d) + dt.timedelta(days=30)).isoformat()
        j = bisect.bisect_left(ds, t)
        if j < len(ds):
            targets[d] = vs[ds[j]] / ends[i % 3]
    moves = qo.realized(spot, targets, 30)
    assert len(moves) == len(targets) and all(abs(r - (ends[i % 3] - 1)) < 1e-12 for i, (_, r) in enumerate(moves))
    f = qo.frequencies(moves, (2.0, 5.0), 21)
    n = len(moves)
    up2 = sum(1 for i in range(n) if ends[i % 3] - 1 > 0.02) / n
    assert f["n"] == n and abs(f["n_eff"] - n / 21) < 1e-12 and abs(f["up"][0] - up2) < 1e-12
    assert abs(f["down"][0] - sum(1 for i in range(n) if ends[i % 3] - 1 < -0.02) / n) < 1e-12 and f["down"][1] == 0.0
    assert abs(f["up_se"][0] - math.sqrt(up2 * (1 - up2) / (n / 21))) < 1e-12
    assert abs(f["mean"] - sum(ends[i % 3] - 1 for i in range(n)) / n * 100) < 1e-9
    # a day whose spot a tenor later is more than a week away (the end of the history) is left out
    assert qo.realized(spot[:10], {days[0]: 100.0}, 30) == []


# ================================================================================================ the family
@pytest.fixture(scope="module")
def fitted():
    months = {"OIS:1M": 1.0, "OIS:3M": 3.0, "OIS:1Y": 12.0, "OIS:2Y": 24.0}
    days, data = quant_synth.build(TODAY, months, 520, 11)
    _, quotes = qx.option_quotes(TODAY)
    data.update(quotes)
    for t, v in qx.forward_points(data["FX:EURUSD"], 2.0).items():
        data["FXP:EURUSD:" + t] = v
    meta = {}
    for s in series_specs():
        meta[s["key"]] = {"label": s["label"], "kind": s["kind"], "group": s["group"]}
    ctx = qf.Ctx(dict(DEFAULTS), TODAY, data, meta)
    mons, tables, timing = [], {}, {}
    qo.run(ctx, {}, mons, tables, timing)
    qf.score_all(ctx, mons, {})
    t = dict(tables)
    qo.live_tables(t, ctx)
    return ctx, mons, tables, t, timing


def test_the_family_flags_the_planted_risk_reversal(fitted):
    ctx, mons, tables, t, timing = fitted
    assert not tables["errors"] and {m.sid for m in mons} >= {"opt:USDTRY:RR25:1M", "opt:USDTRY:RR25:3M", "opt:USDTRY:BF25:1M",
                                                             "opt:USDTRY:BF10:1M", "opt:USDTRY:SLOPE", "opt:EURUSD:SLOPE"}
    sig = {s["id"]: s for s in (qf.make_signal(m, ctx.cfg, "10:00") for m in mons) if s}
    s = sig["opt:USDTRY:RR25:1M"]
    assert s["expression"] == "Sell USDTRY 1M 25D RR" and s["z"] > 2.5 and s["asset"] == "FX vol" and s["family_label"] == "Opsiyon smile"
    assert s["unit"] == "vol" and s["target"] < s["entry"] < s["stop"]
    slope = next(m for m in mons if m.sid == "opt:USDTRY:SLOPE")
    assert [leg["key"] for leg in slope.legs] == ["OPT:USDTRY:ATM:1Y", "OPT:USDTRY:ATM:1M"] and slope.pkg == "spread"
    assert timing["opt"] < 2.0


def test_the_page_table_surface_term_structure_and_probabilities(fitted):
    ctx, mons, tables, t, timing = fitted
    o = t["opt"]
    pairs = {p["pair"]: p for p in o["pairs"]}
    usd = pairs["USDTRY"]
    one = next(r for r in usd["surface"] if r["tenor"] == "1M")
    rr = next(m for m in mons if m.sid == "opt:USDTRY:RR25:1M")
    assert abs(one["RR25_z"] - rr.z) < 1e-9 and one["RR25_sid"] == rr.sid and abs(one["RR25_atm"] - one["RR25"] / one["ATM"]) < 1e-12
    assert set(next(r for r in usd["surface"] if r["tenor"] == "1W")) >= {"ATM", "ATM_z"} and "RR25" not in next(r for r in usd["surface"] if r["tenor"] == "1W")
    sl = {s["name"]: s for s in usd["slopes"]}
    assert sl["1Y−1M"]["sid"] == "opt:USDTRY:SLOPE" and abs(sl["1Y−1M"]["value"] - (next(r for r in usd["surface"] if r["tenor"] == "1Y")["ATM"] - one["ATM"])) < 1e-12
    for pair, p in pairs.items():
        for s in p["smiles"]:
            assert s["model"] == "svi" and not s["arbitrage"] and abs(s["mean_error"]) < 5e-4, (pair, s["tenor"])
            assert [x["x"] for x in s["probs"]] == list(qo.MOVES[pair][s["tenor"]])
            ups = [x["up"] for x in s["probs"]]
            assert ups == sorted(ups, reverse=True) and all(0 < u < 0.5 for u in ups)         # farther moves, rarer
            assert s["realized"]["n"] > 300 and all(x["up_real"] is not None and x["up_se"] > 0 for x in s["probs"][:1])
    assert pairs["EURUSD"]["smiles"][0]["delta"] == "spot" and pairs["USDTRY"]["smiles"][0]["delta"] == "forward"
    assert pairs["USDTRY"]["smiles"][1]["fwd_pct"] > pairs["USDTRY"]["smiles"][0]["fwd_pct"] > 2        # the carry in the forward


def test_without_quotes_the_page_says_why():
    ctx = qf.Ctx(dict(DEFAULTS), TODAY, {}, {})
    mons, tables, timing = [], {}, {}
    qo.run(ctx, {}, mons, tables, timing)
    t = dict(tables)
    qo.live_tables(t, ctx)
    assert not mons and t["opt"]["ok"]
    s = t["opt"]["pairs"][0]["smiles"][0]
    assert s["why"] == "forward yok" and all(x["up"] is None for x in s["probs"])
