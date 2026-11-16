"""Trend (``tto/quanttrend.py``): volatility-targeted time-series momentum on the quant universe, on synthetic data whose
answers are known - a planted trend gives a long and its reverse a short, a flat noise series a weak score, every line
the same daily risk, no look-ahead (the future rewritten changes nothing decided before it, in the family's own walk and
in the backtest), a turned direction "YENİ" and first in its group, the groups in their order, an offshore line's
"offshore limiti"; the line in the plan's format and the card's sentence; the backtest's daily positions; the log and
the alert on a turn; the page over HTTP (last: leaving its client stops the module's service); the fit's added time on
~100 instruments × two years."""
from __future__ import annotations

import datetime as dt
import math
import random
import time

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quant as qq
from tto import quantbt as qbt
from tto import quantfam as qf
from tto import quanttrend as qt
from tto import quantuniv as qu
from tto import quantopt as qopt
from tto.server import create_app

TODAY = dt.date(2026, 11, 16)
N_DAYS = 504                                                            # two years of business days
MONTHS = {"1W": 0.25, "2W": 0.5, "1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12, "15M": 15, "18M": 18, "21M": 21, "2Y": 24,
          "3Y": 36, "4Y": 48, "5Y": 60, "6Y": 72, "7Y": 84, "8Y": 96, "9Y": 108, "10Y": 120}
G10 = {"EURUSD": 1.10, "USDJPY": 150.0, "GBPUSD": 1.27, "AUDUSD": 0.66, "USDCAD": 1.37, "USDCHF": 0.88, "NZDUSD": 0.60}
ISIN = "TRT150329T15"


def cfg(**kw):
    out = dict(qq.DEFAULTS, usdtry=42.0)
    out.update(kw)
    return out


def build(n=N_DAYS, today=TODAY, seed=7, drift=None, flat=(), mpc=True, live=None, cut=None, bump=0.0, **kw):
    """A context with the universe's series over ``n`` business days: TRY OIS tenors (a common random walk and each
    tenor's own noise), the offshore curve, G10 spots / 3M points / vols, USDTRY / EURTRY and their points, the global
    inputs, a DİBS, every day's meeting path (the PPK periods).  ``drift``: key -> a planted move a day (a rate's in
    per cent, an FX price's in log, a vol's in vol points) added to that series; ``flat``: keys that are white noise
    around a constant (no trend at all); ``cut`` / ``bump``: every value after the day ``cut`` moved by ``bump`` (a
    rewritten future)."""
    rnd = random.Random(seed)
    drift = drift or {}
    days = quant_synth.business_days(today, n)
    series, meta = {}, {}

    def put(key, values, **m):
        if key in flat:
            base = values[0]
            values = [base + (0.002 * base if m.get("kind") == "fx" else (0.05 if m.get("kind") == "rate" else 0.1)) * rnd.gauss(0, 1)
                      for _ in values]
        mu = drift.get(key)
        if mu:
            values = [v * math.exp(mu * i) if m.get("kind") == "fx" else v + mu * i for i, v in enumerate(values)]
        if cut is not None:
            values = [v + (bump if d > cut else 0.0) for d, v in zip(days, values)]
        series[key] = dict(zip(days, values))
        meta[key] = m

    # ---- TRY OIS: a common level (a random walk, 8 bp a day) and each tenor's own mean-reverting noise
    level, lv = 38.0, []
    for _ in days:
        level += rnd.gauss(0, 0.08)
        lv.append(level)
    for label, mo in MONTHS.items():
        own, vals = 0.0, []
        for i in range(n):
            own = 0.9 * own + rnd.gauss(0, 0.03)
            vals.append(lv[i] + 0.02 * mo + own)
        put("OIS:" + label, vals, label=label + " OIS", kind="rate", months=float(mo))
    for label in ("1M", "3M", "1Y"):
        put("OFF:" + label, [v - 2.0 + rnd.gauss(0, 0.05) for v in (series["OIS:" + label][d] for d in days)], label="Offshore " + label,
            kind="rate", months=float(MONTHS[label]), group="off")
    # ---- G10: spots (0,5 % a day), 3M points (a constant differential: a carry), option quotes around their means
    for pair, s0 in G10.items():
        s, vals = s0, []
        for _ in days:
            s *= math.exp(rnd.gauss(0, 0.005))
            vals.append(s)
        put("FX:" + pair, vals, label=pair, kind="fx", group="G10", universe=True)
        put("FXP:%s:3M" % pair, [v * (-0.01 if pair[:3] == "USD" else 0.01) * 91.25 / 365.0 * (100.0 if pair.endswith("JPY") else 1e4)
                                 for v in vals], label=pair + " 3M swap puanı", kind="pts", group="G10", universe=True)
        for vk, tenor in qu.G10_VOLS:
            mean = 7.0 if vk == "ATM" else (0.5 if vk == "RR25" else 0.25)
            x, vv = mean, []
            for _ in days:
                x = mean + 0.95 * (x - mean) + rnd.gauss(0, 0.15 if vk == "ATM" else 0.05)
                vv.append(x)
            put(qopt.key(pair, vk, tenor), vv, label=qopt.label(pair, vk, tenor), kind="vol", group="G10", universe=True)
    # ---- USDTRY (a managed walk), EURTRY, their points; the global inputs
    s, usdtry = 40.0, []
    for _ in days:
        s *= math.exp(0.0007 + rnd.gauss(0, 0.002))
        usdtry.append(s)
    put("FX:USDTRY", usdtry, label="USDTRY", kind="fx", group="TRY")
    for tenor, dd in (("1M", 30.4), ("3M", 91.25), ("6M", 182.5), ("1Y", 365.0)):
        put("FXP:USDTRY:" + tenor, [x * 0.30 * dd / 365.0 * 1e4 for x in usdtry], label="USDTRY %s swap puanı" % tenor, kind="pts", group="TRY")
    eurtry = [usdtry[i] * series["FX:EURUSD"][d] for i, d in enumerate(days)]
    put("FX:EURTRY", eurtry, label="EURTRY", kind="fx", group="TRY")
    put("FXP:EURTRY:3M", [x * 0.28 * 91.25 / 365.0 * 1e4 for x in eurtry], label="EURTRY 3M swap puanı", kind="pts", group="TRY")
    for key, v0 in (("UST:2Y", 3.8), ("UST:10Y", 4.3), ("DXY", 100.0), ("BRENT", 70.0), ("CDS", 280.0), ("TLREF", 39.5)):
        put(key, [v0 + 0.01 * math.sin(i / 4.0) for i in range(n)], label=key, kind="rate" if key.startswith(("UST", "TLREF")) else "index",
            group="Global")
    y, yy = 35.0, []
    for _ in days:
        y += rnd.gauss(0, 0.12)
        yy.append(y)
    put("DIBS:" + ISIN, yy, label=ISIN, kind="rate", group="dibs", unit="pct", maturity="2029-03-15", type="S", name="")
    path = {"days": {}, "values": []}
    if mpc:
        meetings = [(today + dt.timedelta(days=42 * j - 2 * 365)).isoformat() for j in range(25)]
        for i, d in enumerate(days):
            spot = qf.business_on_or_after(dt.date.fromisoformat(d) + dt.timedelta(days=1), set()).isoformat()
            path["days"][d] = {"spot": spot, "base": lv[i] / 100.0, "status": "OK"}
            for j, m in enumerate(x for x in meetings if x >= spot):
                if j >= 4:
                    break
                path["values"].append({"day": d, "meeting": m, "level": (lv[i] - 0.5 * (j + 1)) / 100.0})
    eng = {"dibs": [{"isin": ISIN, "type": "S", "row": 5, "name": "", "maturity": "2029-03-15", "coupon": 30.0, "freq": 2.0,
                     "simple": 0.35, "compound": 0.38, "source": ""}]}
    ctx = qf.Ctx(cfg(**kw), today, series, meta, live or {}, mpc=path)
    return ctx, eng


def fit(ctx, eng=None):
    reg = qu.Registry(ctx, None, eng)
    mons, table = qt.run(ctx, reg, ctx.cfg)
    qf.score_all(ctx, mons, ctx.live)
    return reg, {m.sid: m for m in mons}, table


def signal(mon, c=None):
    return qf.make_signal(mon, c or mon.trend.cfg, "10:00")


@pytest.fixture(scope="module")
def planted():
    """EURUSD and the 2Y OIS planted up (+0,08 % a day: ~20 % a year against a 0,5 % daily σ; +3 bp a day against 8),
    USDJPY and the 5Y OIS down by as much, GBPUSD and the 1Y OIS white noise around a constant."""
    ctx, eng = build(drift={"FX:EURUSD": 0.0008, "FX:USDJPY": -0.0008, "OIS:2Y": 0.03, "OIS:5Y": -0.03}, flat=("FX:GBPUSD", "OIS:1Y"))
    return (ctx, eng) + fit(ctx, eng)


# ================================================================================================ the score and the line
def test_a_planted_trend_gives_a_long_its_reverse_a_short_and_noise_a_weak_line(planted):
    ctx, eng, reg, mons, table = planted
    up, dn = signal(mons["trend:FX:EURUSD"]), signal(mons["trend:FX:USDJPY"])
    assert up["direction"] == 1 and up["z"] > 1.0 and up["strength"] == "Güçlü" and up["expression"] == "AL EURUSD spot"
    assert dn["direction"] == -1 and dn["z"] < -1.0 and dn["expression"] == "SAT USDJPY spot"
    pay, rec = signal(mons["trend:OIS:2Y"]), signal(mons["trend:OIS:5Y"])
    assert pay["direction"] == 1 and pay["expression"] == "pay 2Y OIS" and rec["direction"] == -1 and rec["expression"] == "receive 5Y OIS"
    # every horizon agrees on a planted trend: each term of the score on its side
    assert all(t > 0 for t in up["trend"]["terms"]) and all(t < 0 for t in rec["trend"]["terms"])
    for sg in (up, dn, pay, rec):                                        # (the contributions add up to the score, ±2 at most)
        assert sg["z"] == pytest.approx(max(-qt.CLIP, min(qt.CLIP, sum(sg["trend"]["terms"]))))
    assert abs(up["z"]) == qt.CLIP and sum(up["trend"]["terms"]) > qt.CLIP
    # white noise around a constant: a weak line - still a line (no gate), at the bottom of its strength
    for key in ("trend:FX:GBPUSD", "trend:OIS:1Y"):
        sg = signal(mons[key])
        assert sg is not None and abs(sg["z"]) < 0.5 and sg["strength"] == "Zayıf" and not sg["gated"] and sg["line"], key
    # one line per instrument (no gate), whatever its score; those without 63 closes or without a move: a row and why
    assert table["lines"] == len(mons) == len([r for r in table["rows"] if r["sid"]]) and len(table["rows"]) == len(list(reg))
    lines = [signal(m) for m in mons.values()]
    assert all(s is not None and not s["gated"] and s["family"] == "trend" and s["kind"] == "sys" for s in lines)
    strength = {s["id"]: s["strength"] for s in lines}
    assert {"Zayıf", "Orta", "Güçlü"} >= set(strength.values()) and all(
        strength[s["id"]] == ("Güçlü" if abs(s["z"]) >= 1 else ("Orta" if abs(s["z"]) >= 0.5 else "Zayıf")) for s in lines)


def test_the_score_is_the_mean_of_three_horizons_over_their_volatility():
    """By hand on one series: 1, 3 and 12 month moves (its own P&L: bp of the level) over σ of its last 60 daily moves
    × √days; with less than a year the long horizon is all there is; with less than 63 closes no line."""
    ctx, eng = build(n=300, drift={"OIS:2Y": 0.02})
    reg = qu.Registry(ctx, None, eng)
    inst = reg["OIS:2Y"]
    tr = qt.track(inst)
    vals = inst.values
    moves = [(b - a) * 100.0 for a, b in zip(vals, vals[1:])]
    sd = qf.qm.stdev(moves[-60:])
    lvl = vals[-1] + 0.10
    sc, terms, hl = qt.score_now(tr, inst.kind, lvl, ctx.today)
    xn = lvl
    want = [((xn - vals[-h]) * 100.0) / (sd * math.sqrt(h)) for h in (21, 63, 252)]
    assert hl == 252 and [round(t, 9) for t in terms] == [round(w, 9) for w in want]
    assert sc == pytest.approx(max(-2.0, min(2.0, sum(want) / 3.0)))
    short = qu.Registry(build(n=150)[0], None, eng)["OIS:2Y"]
    _, _, hl2 = qt.score_now(qt.track(short), "rate", short.values[-1], TODAY)
    assert hl2 == 150                                                    # (the long horizon: what the instrument has)
    few, _ = build(n=60)
    reg2 = qu.Registry(few, None, eng)
    mons2, tab2 = qt.run(few, reg2, few.cfg)
    assert not mons2 and all(r["why"].startswith("geçmiş kısa: 60 gün (en az 63)") for r in tab2["rows"])


def test_an_instrument_that_cannot_be_read_is_its_row_s_reason_not_the_family_s_end():
    ctx, eng = build(n=120)
    reg = qu.Registry(ctx, None, eng)

    def bad():
        raise ValueError("bozuk seri")

    reg["OIS:2Y"].adjusted = bad
    mons, table = qt.run(ctx, reg, ctx.cfg)
    rows = {r["key"]: r for r in table["rows"]}
    assert rows["OIS:2Y"]["why"] == "hesaplanamadı: ValueError: bozuk seri" and not rows["OIS:2Y"]["sid"]
    assert "trend:OIS:2Y" not in {m.sid for m in mons} and len(mons) == len(table["rows"]) - 1 >= 90


def test_an_fx_line_s_return_has_its_carry_in_it():
    """A spot that does not move but whose forwards pay a long: its P&L index rises by the carry, the score is up."""
    ctx, eng = build(n=200, flat=())
    pair = "AUDUSD"
    days = sorted(ctx.series["FX:" + pair])
    ctx.series["FX:" + pair] = {d: 0.66 + 0.0005 * math.sin(i) for i, d in enumerate(days)}       # (no trend in the price)
    ctx.series["FXP:%s:3M" % pair] = {d: -150.0 for d in days}       # forward below the spot: a long earns ~2,3 % a year
    ctx._construct()
    reg = qu.Registry(ctx, None, eng)
    tr = qt.track(reg["FX:" + pair])
    carry = reg["FX:" + pair].carry_days()[days[-1]]
    assert carry > 2.0 and tr["rate"][-1] == pytest.approx(carry / 365.0)
    span = (dt.date.fromisoformat(days[-1]) - dt.date.fromisoformat(days[0])).days
    assert tr["x"][-1] == pytest.approx(math.log(ctx.series["FX:" + pair][days[-1]] / ctx.series["FX:" + pair][days[0]]) * 100.0
                                        + carry / 365.0 * span, rel=0.02)
    assert tr["score"][-1] > 0.5


# ================================================================================================ size
def test_every_line_is_sized_to_the_same_daily_risk(planted):
    ctx, eng, reg, mons, table = planted
    target = ctx.cfg["trend_risk_usd"]
    assert target == qt.DEFAULTS["trend_risk_usd"] == 5000.0 and qq.LABELS["trend_risk_usd"].startswith("Trend · hedef günlük risk")
    usdtry = ctx.usdtry()
    rows = [r for r in table["rows"] if r["sid"]]
    assert len(rows) > 80
    inside = 0
    for r in rows:
        inst = reg[r["key"]]
        risk = abs(inst.money(r["sigma"], r["k"]))
        risk_usd = risk / usdtry if inst.ccy in ("TL", "TRY") else risk
        assert r["risk_k"] == pytest.approx(risk_usd, rel=1e-6), r["key"]
        lo, hi = qt.K_RANGE
        if lo < r["k"] < hi:
            inside += 1
            assert risk_usd == pytest.approx(target, rel=0.05), (r["key"], r["k"], risk_usd)       # (2 significant figures)
        else:
            assert r["k"] in (lo, hi), r["key"]
        assert r["size"] == inst.size_text(r["k"]) and mons[r["sid"]].trend.k == r["k"]
    assert inside >= 0.7 * len(rows)
    # the desk's words: an FX line "1,4 mn EUR", a rates line "370 $ DV01"; the card's legs at that size
    e = next(r for r in rows if r["key"] == "FX:EURUSD")
    assert e["size"].endswith(" EUR") and (" mn " in e["size"] or " bin " in e["size"])
    o = next(r for r in rows if r["key"] == "OIS:2Y")
    assert o["size"] == "%s $ DV01" % qf._th(1000.0 * o["k"], 0)
    sg = signal(mons["trend:OIS:2Y"])
    assert sg["legs"][0]["dv01_usd"] == pytest.approx(1000.0 * o["k"]) and sg["info"]["size"] == o["size"]
    # a higher daily risk: every line bigger by as much
    c2, _ = build(drift={"FX:EURUSD": 0.0008, "FX:USDJPY": -0.0008, "OIS:2Y": 0.03, "OIS:5Y": -0.03}, flat=("FX:GBPUSD", "OIS:1Y"),
                  trend_risk_usd=10000.0)
    _, _, t2 = fit(c2, eng)
    k2 = {r["key"]: r["k"] for r in t2["rows"] if r["sid"]}
    assert k2["OIS:2Y"] == pytest.approx(qt.round2(min(2 * o["k"], 10.0)), rel=0.06)


# ================================================================================================ target, stop, hold
def test_target_stop_and_holding_come_from_the_walk_s_buckets(planted):
    ctx, eng, reg, mons, table = planted
    for key in ("trend:FX:EURUSD", "trend:OIS:2Y", "trend:OPT:EURUSD:ATM:1M", "trend:OISS:1Y/2Y"):
        m = mons[key]
        sg = signal(m)
        line = m.trend
        b = qt.bucket(abs(sg["z"]))
        st = line.buckets[b]
        sd = line.sigma
        assert sg["hold"] == pytest.approx(st["hold"]) and sg["trend"]["bucket"] == qt.BUCKETS[b]
        # the stop: 2σ of the holding against; the expected P&L: the bucket's mean gain (σ of each line's day × σ now);
        # the target: the level's own move that, with the holding's carry, makes it (an FX line: its forwards' carry)
        inst = m.trend.inst
        risk_cu = qt.STOP_SIGMA * sd * math.sqrt(st["hold"])
        assert abs(sg["stop"] - sg["entry"]) == pytest.approx(qf.to_level(inst.kind, risk_cu, sg["entry"]), rel=1e-9), key
        gain_cu = st["gain"] * sd
        carry = 0.0
        if inst.fx:
            cal = st["hold"] * 7.0 / 5.0
            carry = sg["direction"] * ctx.fx_carry(inst.fx, ctx.derive_live(ctx.live), days=cal) * cal / 365.0
            assert sg["exp_pnl"] == pytest.approx(gain_cu, rel=1e-6)                      # (its carry in the walk's gain)
        else:
            assert sg["exp_pnl"] == pytest.approx(gain_cu * inst.per_cu + (sg["carry_h"] or 0.0), rel=1e-6)      # (+ carry + roll)
        if gain_cu - carry > 0:
            assert (sg["target"] - sg["entry"]) * sg["direction"] == pytest.approx(qf.to_level(inst.kind, gain_cu - carry, sg["entry"]), rel=1e-6)
            assert "hedef " + qt._price(sg, "target") in sg["line"]
        else:
            assert sg["target"] == sg["entry"] and ("hedef —" in sg["line"]) == (sg["exp_pnl"] <= 0)
        assert st["n"] >= qt.MIN_SIGNALS and st["scope"] in ("enstrüman", inst.group, "aile", "aile, tüm güçler")
    # the buckets the page shows: every group's four, then the family's
    groups = [r["group"] for r in table["buckets"]]
    assert groups[-4:] == ["Tümü"] * 4 and [r["bucket"] for r in table["buckets"][:4]] == list(qt.BUCKETS)
    assert sum(r["n"] for r in table["buckets"] if r["group"] == "Tümü") == sum(r["n"] for r in table["buckets"] if r["group"] != "Tümü")


# ================================================================================================ no look-ahead
def test_no_look_ahead_in_the_walk():
    """Every value after a day rewritten: the scores up to it, the lines drawn up to it and closed by it, their stops
    and the bucket statistics known on it - all the same."""
    base, eng = build(n=320, seed=3)
    cut = sorted(base.series["OIS:2Y"])[-90]
    moved, _ = build(n=320, seed=3, cut=cut, bump=0.75)
    out = []
    for ctx in (base, moved):
        reg = qu.Registry(ctx, None, eng)
        insts = list(reg)
        tracks = [qt.track(i) for i in insts]
        pooled, lines = qt.walk(tracks, [i.group for i in insts])
        out.append((insts, tracks, lines))
    changed = 0
    for i, inst in enumerate(out[0][0]):
        ta, tb = out[0][1][i], out[1][1][i]
        la, lb = out[0][2][i], out[1][2][i]
        assert ta["days"] == tb["days"], inst.key
        for t, d in enumerate(ta["days"]):
            if d > cut:
                if la[t] != lb[t] or ta["score"][t] != tb["score"][t]:
                    changed += 1
                continue
            assert ta["score"][t] == tb["score"][t] and ta["d"][t] == tb["d"][t], (inst.key, d)
            if la[t] is None:
                continue
            assert la[t][3:] == lb[t][3:], (inst.key, d)                # (its bucket and the holding its stop used)
            u = la[t][0]
            if u is not None and ta["days"][u] <= cut:                   # closed by the cut: the same outcome
                assert la[t][:3] == lb[t][:3], (inst.key, d)
    assert changed > 0                                                   # (the rewrite did reach the walk after the cut)


def test_no_look_ahead_in_the_backtest_and_its_daily_positions():
    """The backtest machinery on the family alone: a Trend line is a daily position - opened on its direction's first
    day, closed at its turn ("dönüş") or its stop, never at a target or a time - and a rewritten future changes no trade
    closed before it."""
    base, eng = build(n=420, seed=5, mpc=False)
    cut = sorted(base.series["OIS:2Y"])[-60]
    moved, _ = build(n=420, seed=5, mpc=False, cut=cut, bump=0.5)

    def run(ctx0):
        series = ctx0.series
        meta = ctx0.meta

        def make_ctx(T):
            return qf.Ctx(ctx0.cfg, dt.date.fromisoformat(T) + dt.timedelta(days=1), series, {k: dict(v) for k, v in meta.items()}, {})

        def runner(ctx):
            reg = qu.Registry(ctx)
            return [m for m in qt.run(ctx, reg, ctx.cfg)[0] if m.trend.inst.group == "G10 spot" or m.trend.inst.key.startswith("OIS:")]

        test = sorted(series["OIS:2Y"])[-120:]
        return qbt.backtest(test, make_ctx, runner, series, ctx0.cfg, step=10), test

    res, test = run(base)
    res2, _ = run(moved)
    trades = [t for t in res["trades"] if t["family"] == "trend"]
    assert 20 <= len(trades) == res["n_trades"] < qbt.BT_KEEP and res["families"]["trend"]["trades"] == len(trades)
    assert {t["outcome"] for t in trades} <= {"dönüş", "stop"} and "dönüş" in {t["outcome"] for t in trades}
    assert set(res["families"]["trend"]["types"]) <= {"G10 spot", "TRY OIS"}
    # every line opened on the window's first day; a turn closes one and opens the other side the same day
    first = {t["sid"] for t in trades if t["entry_day"] == test[0]}
    assert len(first) >= 10
    by = {}
    for t in sorted(trades, key=lambda t: t["entry_day"]):
        by.setdefault(t["sid"], []).append(t)
    for sid, ts in by.items():
        for a, b in zip(ts, ts[1:]):
            assert b["entry_day"] >= a["exit_day"] and (b["entry_day"] > a["exit_day"] or (a["outcome"] == "dönüş" and b["dir"] == -a["dir"])), sid
    before = lambda r: sorted((t["sid"], t["entry_day"], t["exit_day"], round(t["pnl"], 9)) for t in r["trades"] if t["exit_day"] <= cut)
    assert before(res) and before(res) == before(res2)


# ================================================================================================ YENİ, order, offshore
def test_a_turned_direction_is_yeni_and_first_in_its_group(planted):
    ctx, eng, reg, mons, table = planted
    m = mons["trend:FX:EURUSD"]
    assert m.trend.d_prev == 1 and not signal(m)["new"]
    # the spot falls far below today: the score turns down - "YENİ", its days in position 0, first in G10 spot
    last = reg["FX:EURUSD"].last()
    live = {"FX:EURUSD": last * math.exp(-0.25)}
    qf.score_all(ctx, list(mons.values()), live)
    sg = signal(m)
    assert sg["direction"] == -1 and sg["new"] and sg["days_in"] == 0 and sg["line"].startswith("YENİ · SAT EURUSD spot · ")
    assert sg["plain"].startswith("YENİ - yön bugün döndü. SAT EURUSD spot")
    others = [signal(x) for x in mons.values() if x.sid != m.sid]
    ordered = qu.order([sg] + [s for s in others if s is not None], [])
    g10 = [s for s in ordered if s["group"] == "G10 spot"]
    assert g10[0]["id"] == m.sid and [s["composite"] for s in g10[1:]] == sorted((s["composite"] for s in g10[1:]), reverse=True)
    # the other lines: their own days in the direction (the walk's run at the last close)
    o = signal(mons["trend:OIS:2Y"])
    assert not o["new"] and o["days_in"] == mons["trend:OIS:2Y"].trend.run >= 1
    qf.score_all(ctx, list(mons.values()), {})


def test_the_groups_keep_their_order_and_offshore_lines_say_their_limit(planted):
    ctx, eng, reg, mons, table = planted
    sigs = [signal(m) for m in mons.values()]
    live, gated = qf.rank(sigs)
    ordered = qu.order(live, gated)
    pri = [s["priority"] for s in ordered]
    assert pri == sorted(pri) and [g for g in qu.GROUPS if any(s["group"] == g for s in ordered)][:4] == ["G10 spot", "G10 opsiyon", "TRY OIS", "DİBS"]
    assert ordered[-1]["group"] == "Offshore"
    for p in set(pri):                                                   # each group: "YENİ" first, then by strength
        mine = [s for s in ordered if s["priority"] == p]
        keys = [(0 if s.get("new") else 1, -s["composite"]) for s in mine]
        assert keys == sorted(keys), p
    # the table: the registry's order
    assert [r["key"] for r in table["rows"]] == [i.key for i in reg]
    off = [s for s in ordered if s["group"] == "Offshore"]
    assert {s["id"] for s in off} >= {"trend:FWD:USDTRY:1M", "trend:FXP:USDTRY:3M", "trend:OFF:3M"}
    for s in off:
        assert s["tag"] == "offshore limiti" and " · offshore limiti · giriş " in s["line"] and "offshore limiti" in s["plain"]
    assert not any("offshore limiti" in s["line"] for s in ordered if s["group"] != "Offshore")


# ================================================================================================ the line and the card
def test_the_line_in_the_plan_s_format_and_the_card_s_sentence(planted):
    ctx, eng, reg, mons, table = planted
    sg = signal(mons["trend:FWD:USDTRY:1M"])
    line = mons["trend:FWD:USDTRY:1M"].trend
    s = sg["direction"]
    verb = "AL" if s > 0 else "SAT"
    px = sg["px"]
    d = px["digits"]
    exp = sg["money"]["total"] * line.k
    st = line.stats
    want = ["YENİ"] if sg["new"] else []
    want += ["%s USDTRY 1A forward" % verb, reg["FWD:USDTRY:1M"].size_text(line.k), "offshore limiti", "giriş " + qf._th(px["entry"], d)]
    # (the target: the forward's move to it - its entry when the carry alone makes the expected gain, none without one)
    target = qf._th(px["target"], d) if sg["reward"] > 0 or sg["exp_pnl"] > 0 else "—"
    want += ["hedef " + target, "stop " + qf._th(px["stop"], d), "beklenen " + qf._money(exp, "TRY")]
    want += ["isabet %%%s (%d%s)" % (qf._g(st["hit"] * 100.0, 0), st["trades"], ", grup" if st["scope"] == "grup" else ""), "model: Trend"]
    assert sg["line"] == " · ".join(want)
    # a rates line: its level as the desk writes it, its money in TL at its size (the card's legs sized at k)
    o = signal(mons["trend:OIS:2Y"])
    lo = mons["trend:OIS:2Y"].trend
    assert " · giriş %" in o["line"] and o["line"].endswith(" · model: Trend") and " $ DV01 · giriş " in o["line"]
    assert "beklenen %s" % qf._money(o["money"]["total"], "TL") in o["line"] and o["money"]["per_bp"] == pytest.approx(lo.k * reg.dv01()[1])
    # the card's sentence: what, why (the horizons), what is expected, target and stop in money, the record
    p = o["plain"]
    assert p.startswith("pay 2Y OIS · %s $ DV01." % qf._th(1000.0 * lo.k, 0))
    assert "Neden: 1A ↑, 3A ↑, 1Y ↑ - üç ufuk da yükselişte (skor +" in p and "Beklenen: ~" in p and "carry" not in p.split("Beklenen")[0]
    assert ("Hedef %" in p or "Hedef yok" in p) and "stop" in p.lower() and "Geri test: " in p and "yön dönene ya da stopa kadar" in p
    assert o["thesis"].startswith("Trend yukarı (skor +") and o["trend"]["labels"] == ["1A", "3A", "1Y"]
    e = signal(mons["trend:FX:USDJPY"])
    assert e["line"].startswith("SAT USDJPY spot · ") and " USD · isabet " in e["line"]             # (the yen's money in USD)
    # every line: the plan's parts in the plan's order
    for m in mons.values():
        x = signal(m)
        parts = x["line"].split(" · ")
        assert parts[-1] == "model: Trend" and parts[-2].startswith("isabet ") and parts[-3].startswith("beklenen ")
        assert any(q.startswith("giriş ") for q in parts) and any(q.startswith("hedef ") for q in parts) and any(q.startswith("stop ") for q in parts)


def test_hit_rate_is_the_instrument_s_or_its_group_s_when_it_has_few(planted):
    ctx, eng, reg, mons, table = planted
    for r in (r for r in table["rows"] if r["sid"]):
        st = mons[r["sid"]].trend.stats
        if r["own_trades"] >= qt.MIN_TRADES:
            assert st["scope"] == "enstrüman" and st["trades"] == r["own_trades"]
        else:
            g = next(x for x in table["groups"] if x["group"] == r["group"])
            assert st["scope"] == "grup" and st["trades"] == g["trades"] and ", grup)" in signal(mons[r["sid"]])["line"]
    fam = table["groups"][-1]
    assert fam["group"] == "Tümü" and fam["trades"] == sum(g["trades"] for g in table["groups"][:-1]) > 100
    assert fam["sharpe"] is not None and 0 <= fam["hit"] <= 1


# ================================================================================================ the service
@pytest.fixture(scope="module")
def seeded(module_service):
    svc = module_service
    svc.quant.use_live = False
    quant_synth.seed(svc)
    return svc


def test_the_fit_lists_trend_lines_logs_a_turn_and_alerts_it(seeded):
    svc = seeded
    q = svc.quant
    st = q.compute()
    assert st["ready"] and "trend" in st["timing"] and not st["errors"].get("trend"), st["errors"]
    user = svc.login("trend okuyucu")["user"]
    v = q.view("signals", user, {})
    mine = [s for s in v["signals"] if s["family"] == "trend"]
    assert mine and all(s["line"].endswith("model: Trend") and not s["gated"] and s["page"] == "quant-trend" for s in mine)
    fam = next(f for f in v["families"] if f["id"] == "trend")
    assert fam["label"] == "Trend" and fam["live"] == len(mine) and fam["monitors"] == len(mine)
    # the page: every instrument, its line now, the buckets, the groups' record
    page = q.view("trend", user, {})
    rows = page["trend"]["rows"]
    assert page["ready"] and rows and {r["sid"] for r in rows if r["sid"]} == {s["id"] for s in mine}
    one = next(r for r in rows if r["sid"])
    assert {"score", "terms", "dir", "verb", "new", "days_in", "line", "size", "hit", "sharpe"} <= set(one) and len(one["terms"]) == 3
    assert page["signals"] and all(s["family"] == "trend" for s in page["signals"]) and page["coverage"]
    assert "_keys" not in page["trend"]
    # a turn: the line "YENİ" (its direction other than at the last close) is written down and alerted - once a day -,
    # the entry of its old direction closing on it ("dönüş")
    sid = mine[0]["id"]
    mon = q._fit["mons"][sid]
    q.set_subscription(user, {"on": True, "families": ["trend"], "groups": [], "min": "Zayıf"})
    seq0 = q.counters()["alerts"]
    old = {"seq": 1, "sid": sid, "family": "trend", "family_label": "Trend", "asset": mine[0]["asset"], "group": mine[0]["group"],
           "expression": "eski", "dir": -mine[0]["direction"], "z": -mine[0]["z"], "entry_z": 1.0, "level": mine[0]["level"],
           "target": None, "stop": None, "scale": 1.0, "unit": "", "digits": 2, "strength": "Zayıf", "composite": 0.0,
           "day": "2026-01-02", "time": "10:00", "status": "open", "daily": True}
    svc.store.put(q.LOG_KEY, [old])
    mon.trend.d_prev = -mine[0]["direction"]                             # (as if the last close had the other direction)
    q.refresh_live()
    log = q.log_view()["entries"]
    closed = next(e for e in log if e["sid"] == sid and e.get("expression") == "eski")
    new = [e for e in log if e["sid"] == sid and e["status"] == "open"]
    assert closed["status"] == "dönüş" and closed["closed_level"] is not None and len(new) == 1 and new[0]["daily"]
    assert new[0]["dir"] == mine[0]["direction"] and new[0]["expression"] == mine[0]["expression"]
    # every line written down is "YENİ" now (a turn of its own since the last close), each once, each alerted
    yeni = {s["id"] for s in q.view("signals", user, {})["signals"] if s["family"] == "trend" and s.get("new")}
    opened = [e for e in log if e["family"] == "trend" and e["status"] == "open"]
    assert sid in yeni and {e["sid"] for e in opened} == yeni and len(opened) == len(yeni)
    got = q.alerts(user, seq0)["alerts"]
    assert sorted(a["sid"] for a in got) == sorted(yeni) and all(a["family"] == "trend" for a in got)
    before = [e for e in log if e["family"] == "trend"]
    q.refresh_live()                                                     # (once a day: not again)
    assert [e for e in q.log_view()["entries"] if e["family"] == "trend"] == before
    assert len([a for a in q.alerts(user, seq0)["alerts"] if a["family"] == "trend"]) == len(yeni)
    hits = {f["family"]: f for f in q.log_view()["families"]}
    assert hits["trend"]["closed"] == 1 and hits["trend"]["open"] == len(yeni)
    mon.trend.d_prev = mine[0]["direction"]


def test_trend_page_over_http_and_in_the_menu(seeded):
    svc = seeded
    if not svc.quant.status()["ready"]:
        svc.quant.compute()
    with TestClient(create_app(svc), headers=auth(svc, "Trend HTTP")) as client:
        body = client.get("/api/quant/trend").json()
        assert body["ready"] and body["trend"]["rows"] and body["trend"]["risk_usd"] == 5000.0
        assert {"trades", "hit", "sharpe"} <= set(body["trend"]["groups"][-1])
        st = client.get("/api/quant/settings").json()
        assert st["values"]["trend_risk_usd"] == 5000.0 and st["labels"]["trend_risk_usd"].startswith("Trend")
        nav = [p for p in client.get("/api/nav").json()["pages"] if p["group"] == "Quant"]
        tabs = [p["id"] for p in nav if p.get("menu") == "quant.sinyal"]
        assert tabs[-1] == "quant-trend" and next(p for p in nav if p["id"] == "quant-trend")["tab"] == "Trend"
        assert client.get("/static/js/pages/quanttrend.js").status_code == 200


# ================================================================================================ time
def test_the_fit_s_added_time_on_a_hundred_instruments_over_two_years(capsys):
    """The family on the full universe: ~100 lines × two years (the registry's series made on the way), and the live
    refresh's re-scoring alone."""
    ctx, eng = build()
    reg = qu.Registry(ctx, None, eng)
    t0 = time.perf_counter()
    mons, table = qt.run(ctx, reg, ctx.cfg)
    took = time.perf_counter() - t0
    t1 = time.perf_counter()
    mons2, table = qt.run(ctx, reg, ctx.cfg)                             # (the series made: the family's own part)
    own = time.perf_counter() - t1
    t2 = time.perf_counter()
    qf.score_all(ctx, mons, {"FX:EURUSD": 1.1, "OIS:2Y": 39.0})
    sigs = [signal(m) for m in mons]
    live = time.perf_counter() - t2
    with capsys.disabled():
        print("\nTrend: %d lines of %d instruments × %d days - fit %.0f ms (series %.0f + family %.0f: track %.0f, walk %.0f), "
              "re-scoring and the lines %.0f ms" % (len(mons), len(list(reg)), N_DAYS, took * 1000.0, (took - own) * 1000.0, own * 1000.0,
                                                  table["ms"]["track"], table["ms"]["walk"], live * 1000.0))
    assert len(mons) >= 95 and all(s is not None for s in sigs)
    assert took < 30.0 and live < 5.0                                    # (loose: a loaded machine; the numbers are printed)
