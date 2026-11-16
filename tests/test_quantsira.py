"""Carry + momentum (``tto/quantsira.py``) on synthetic markets whose answers are planted: a carry order gives the right
basket in each set (G10 spot: the three highest-carry currencies long and the three lowest short, as the pairs say it;
G10 vol: the richest premiums sold, the cheapest bought; TRY OIS: the best carry + roll ÷ volatility received; DİBS: the
cheapest bonds against the curve bought), the baskets' neutrality (dollar, vega, DV01) and equal risk, the weekly
rebalance (Monday's close, a holiday's week its next business day; the next one on the card), no look-ahead (closes after
a rebalance change nothing of its basket), the list's order (TRY OIS ≤ 2Y before the long end), no Offshore line, the
lines in the plan's format with their target and stop and no gate holding them, the backtest per set on the panel.
(The HTTP part last: leaving its client stops the module's service.)"""
from __future__ import annotations

import datetime as dt
import math
import re

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quant as qq
from tto import quantbt as qbt
from tto import quantfam as qf
from tto import quantsira as qs
from tto import quantuniv as qu
from tto.server import create_app

TODAY = dt.date(2026, 11, 18)                    # a Wednesday: this week's baskets were made at Monday's (16.11) close
MONDAY = "2026-11-16"
DAYS = quant_synth.business_days(TODAY, 520)     # (two years of week days before today)
#: pair: (spot, the currency's carry against USD % a year, its daily noise (log), the noise's period, 3M ATM implied vol)
G10 = {"EURUSD": (1.10, -1.0, 0.0003, 7, 7.5), "USDJPY": (150.0, -4.0, 0.0004, 9, 15.0), "GBPUSD": (1.27, 2.0, 0.00035, 21, 10.5),
       "AUDUSD": (0.66, 4.0, 0.00045, 3, 13.5), "USDCAD": (1.37, 0.5, 0.00025, 7, 6.0), "USDCHF": (0.88, -2.5, 0.0003, 9, 9.0),
       "NZDUSD": (0.60, 3.0, 0.0004, 21, 12.0)}
MONTHS = {"1W": 0.25, "2W": 0.5, "1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12, "15M": 15, "18M": 18, "21M": 21, "2Y": 24,
          "3Y": 36, "5Y": 60, "10Y": 120}
#: DİBS: ISIN -> (maturity, the residual it used to have against the curve, bp: now 0 for all - the negative ones are cheap
#: against their own history, the positive ones rich)
BONDS = {"TRT100727T11": ("2027-07-10", -30.0), "TRT150128T12": ("2028-01-15", 25.0), "TRT120728T13": ("2028-07-12", -10.0),
         "TRT170129T14": ("2029-01-17", 40.0), "TRT110729T15": ("2029-07-11", -45.0), "TRT160130T16": ("2030-01-16", 10.0),
         "TRT100730T17": ("2030-07-10", -20.0), "TRT150131T18": ("2031-01-15", 30.0)}


def wave(i, amp, period=3, phase=0.0):
    """A periodic noise: its period divides 63, so a 3-month move of it is 0 - the planted order is the carry's alone."""
    return amp * math.sin(2.0 * math.pi * i / period + phase)


def cfg(**kw):
    out = dict(qq.DEFAULTS, usdtry=42.0)
    out.update(kw)
    return out


def flat_ois(label, i):
    """The OIS curve rising 0,5 % a month of tenor from TLREF (30 %), each tenor with its own phase of the same noise
    (the same σ: carry ÷ volatility is carry's order)."""
    return 30.0 + 0.5 * MONTHS[label] + wave(i, 0.01, 3, 0.37 * list(MONTHS).index(label))


def market(days=None, today=TODAY, ois=flat_ois, g10=None, dibs=True, holidays=None, edit=None):
    """A context with the universe's series for the family: G10 spots, 3M points (the planted carry), ATM 3M vols; the
    TRY OIS curve and TLREF; DİBS yields with their curve fit's residuals - and the registry on it.  ``edit(key, i,
    value)``: a value changed (a test of look-ahead)."""
    days = list(days or DAYS)
    n = len(days)
    series, meta = {}, {}

    def put(key, vals, **m):
        if edit is not None:
            vals = [edit(key, i, v) for i, v in enumerate(vals)]
        series[key] = dict(zip(days, vals))
        meta[key] = m

    for k, (pair, spec) in enumerate((g10 or G10).items()):
        s0, c, amp, per, iv = spec[:5]
        trend = spec[5] if len(spec) > 5 else 0.0                       # (a planted momentum: log move a day)
        base = pair[:3] != "USD"
        cp = c if base else -c                                          # (the pair's carry: the base's rate less the quote's)
        spot = [s0 * math.exp(wave(i, amp, per, 0.3 * k) + trend * i) for i in range(n)]
        scale = 2 if pair.endswith("JPY") else 4
        put("FX:" + pair, spot, label=pair, kind="fx", group="G10", universe=True)
        put("FXP:%s:3M" % pair, [(s * math.exp(-cp / 100.0 * 91.25 / 365.0) - s) * 10 ** scale for s in spot], label=pair + " 3M swap puanı",
            kind="pts", group="G10")
        put("FXV:" + pair, [iv + wave(i, 0.1, 9, 0.5 * k) for i in range(n)], label=pair + " ATM 3M vol", kind="vol", group="G10")
    series["FX:USDTRY"] = {d: 42.0 for d in days}                       # (the TL of a DV01: never edited)
    meta["FX:USDTRY"] = {"label": "USDTRY", "kind": "fx", "group": "TRY"}
    # (TLREF and the yields: one noise, 0 at Monday's close - the close before the last one)
    zero = -2.0 * math.pi * (len(DAYS) - 2) / 3.0
    put("TLREF", [30.0 + wave(i, 0.01, 3, zero) for i in range(n)], label="TLREF", kind="rate", group="ref")
    for label, mo in MONTHS.items():
        put("OIS:" + label, [ois(label, i) for i in range(n)], label=label + " OIS", kind="rate", months=float(mo))
    eng, tables = {"dibs": []}, {}
    if dibs:
        resid = {}
        for r, (isin, (mat, past)) in enumerate(BONDS.items()):
            # the yields flat at TLREF and moving with it (no carry, no roll: the order is the cheapness'); the residuals at
            # their old level with a noise of their own, 0 from Monday on
            put("DIBS:" + isin, [30.0 + wave(i, 0.01 * (1.0 + 0.3 * r), 3, zero) for i in range(n)], label=isin, kind="rate", group="dibs",
                unit="pct", maturity=mat, type="S", name="")
            resid[isin] = [(d, (past + wave(i, 4.0, 7, 0.9 * r)) if d < MONDAY else 0.0) for i, d in enumerate(days)][-250:]
            eng["dibs"].append({"isin": isin, "type": "S", "row": 5 + r, "name": "", "maturity": mat, "coupon": 30.0, "freq": 2.0,
                                "simple": 0.30, "compound": 0.33, "source": ""})
        tables["dibsfv"] = {"resid": resid}
    ctx = qf.Ctx(cfg(), today, series, meta, {}, holidays=holidays or set())
    return ctx, qu.Registry(ctx, tables, eng)


def fit(ctx, reg):
    mons, tab = qs.run(ctx, reg, ctx.cfg)
    sets = {s["id"]: s for s in tab["sets"]}
    return mons, tab, sets


def signals(ctx, mons):
    qf.score_all(ctx, mons, {})
    out = {}
    for m in mons:
        sg = qf.make_signal(m, ctx.cfg, "10:00")
        if sg is not None:
            out[m.sid] = sg
    return out


@pytest.fixture(scope="module")
def planted():
    ctx, reg = market()
    mons, tab, sets = fit(ctx, reg)
    return ctx, reg, mons, tab, sets, signals(ctx, mons)


# ================================================================================================ the baskets
def test_a_planted_carry_order_gives_the_g10_basket_long_the_best_three_short_the_worst_three(planted):
    ctx, reg, mons, tab, sets, sigs = planted
    g10 = sets["g10"]
    assert g10["ok"] and g10["basket"]["formed"] == MONDAY and [r["key"] for r in g10["rows"]][:3] == ["FX:AUDUSD", "FX:NZDUSD", "FX:GBPUSD"]
    # long AUD, NZD, GBP; short JPY, CHF, EUR against USD - as each pair goes: selling JPY is AL USDJPY, selling EUR SAT EURUSD
    legs = {leg["key"]: leg for leg in g10["legs"]}
    assert {k: leg["side"] for k, leg in legs.items()} == {"FX:AUDUSD": 1, "FX:NZDUSD": 1, "FX:GBPUSD": 1, "FX:USDJPY": 1, "FX:USDCHF": 1,
                                                           "FX:EURUSD": -1}
    assert {k: leg["way"] for k, leg in legs.items()} == {"FX:AUDUSD": 1, "FX:NZDUSD": 1, "FX:GBPUSD": 1, "FX:USDJPY": -1, "FX:USDCHF": -1,
                                                          "FX:EURUSD": -1}
    assert next(r for r in g10["rows"] if r["key"] == "FX:USDCAD")["side"] == 0          # (CAD, 4th of 7: out)
    assert legs["FX:USDJPY"]["line"].startswith("AL USDJPY spot · ") and legs["FX:EURUSD"]["line"].startswith("SAT EURUSD spot · ")
    # the carry each currency has against USD, the momentum with it (carry included), the composite in their order
    rows = {r["key"]: r for r in g10["rows"]}
    for pair, spec in G10.items():
        assert rows["FX:" + pair]["carry"] == pytest.approx(spec[1], abs=1e-9), pair
    comps = [r["composite"] for r in g10["rows"]]
    assert comps == sorted(comps, reverse=True) and [r["rank"] for r in g10["rows"]] == list(range(1, 8))
    # equal risk a leg within a side (its week's σ), the two sides' dollars equal - dollar-neutral; sizes in each pair's base
    for way in (1, -1):
        risk = [leg["sigma_w"] for leg in legs.values() if leg["way"] == way]
        assert max(risk) == pytest.approx(min(risk), rel=1e-9)
    assert sum(leg["usd"] for leg in legs.values() if leg["way"] > 0) == pytest.approx(sum(leg["usd"] for leg in legs.values() if leg["way"] < 0))
    assert abs(g10["basket"]["net"]) < 1e-6 * sum(leg["usd"] for leg in legs.values())
    e = legs["FX:EURUSD"]
    assert e["k"] == pytest.approx(e["usd"] / (1e6 * e["entry"])) and legs["FX:USDJPY"]["k"] == pytest.approx(legs["FX:USDJPY"]["usd"] / 1e6)
    assert reg["FX:EURUSD"].size_text(e["k"]) in e["line"]


def test_the_vol_basket_sells_the_richest_premiums_vega_neutral_and_the_rates_baskets_are_dv01_neutral(planted):
    ctx, reg, mons, tab, sets, sigs = planted
    vol = sets["vol"]
    legs = {leg["key"]: leg["side"] for leg in vol["legs"]}
    assert legs == {"FXV:USDJPY": -1, "FXV:AUDUSD": -1, "FXV:NZDUSD": -1, "FXV:USDCAD": 1, "FXV:EURUSD": 1, "FXV:USDCHF": 1}
    assert all(leg["line"].endswith(" · 10.000 $ vega") for leg in vol["legs"]) and vol["basket"]["net"] == 0
    rows = {r["key"]: r for r in vol["rows"]}
    assert rows["FXV:USDJPY"]["carry"] == pytest.approx(rows["FXV:USDJPY"]["iv"] - rows["FXV:USDJPY"]["rv"])
    assert vol["legs"][0]["line"].startswith("vol sat ")
    # the signals' legs: as much vega bought as sold; a rates basket: as much DV01 received as paid
    vega = sum(s["direction"] * 10000.0 for sid, s in sigs.items() if sid.startswith("sira:vol:"))
    assert vega == 0 and len([s for s in sigs if s.startswith("sira:vol:")]) == 6
    for sid in ("ois", "dibs"):
        legs = [leg for s in sigs.values() if s["id"].startswith("sira:%s:" % sid) for leg in s["legs"]]
        assert legs and sum(leg["side"] * leg["dv01_usd"] for leg in legs) == pytest.approx(0.0), sid
        assert len(legs) == (4 if sid == "ois" else 6) and all(leg["dv01_usd"] == pytest.approx(1000.0) for leg in legs), sid
        assert sets[sid]["basket"]["net"] == 0


def test_the_try_ois_basket_receives_the_best_carry_and_roll_over_volatility():
    ctx, reg = market(dibs=False)
    mons, tab, sets = fit(ctx, reg)
    ois = sets["ois"]
    assert ois["ok"] and [r["key"] for r in ois["rows"]] and len(ois["rows"]) == 8
    # (the same noise a tenor, no 3-month move: the order is carry + roll's) - each tenor's from Monday's curve
    curve = qs._Curve(ctx)
    cr = {k: curve.receive(k, MONDAY) for k in ("OIS:" + t for t in qs.SHORT_OUTRIGHTS)}
    best = sorted(cr, key=lambda k: -cr[k])
    legs = {leg["key"]: leg["side"] for leg in ois["legs"]}
    assert legs == {best[0]: -1, best[1]: -1, best[-1]: 1, best[-2]: 1}                 # (receive: the down side of pay / receive)
    assert [leg["verb"] for leg in ois["legs"]] == ["receive", "receive", "pay", "pay"]
    for r in ois["rows"]:
        assert r["carry"] == pytest.approx(cr[r["key"]]) and r["mom"] == pytest.approx(0.0, abs=1e-6)


def test_carry_and_roll_of_a_tenor_from_its_close_s_curve():
    """A tenor's week for a receiver: (rate − TLREF) × 7/365 ÷ its annuity plus its roll a week down the curve."""
    days = DAYS[-5:]
    series = {"TLREF": {d: 40.0 for d in days}, "OIS:1M": {d: 41.0 for d in days}, "OIS:2M": {d: 41.0 for d in days}}
    meta = {"TLREF": {"kind": "rate"}, "OIS:1M": {"kind": "rate", "months": 1.0}, "OIS:2M": {"kind": "rate", "months": 2.0}}
    ctx = qf.Ctx(cfg(), TODAY, series, meta, {})
    curve = qs._Curve(ctx)
    a1, a2 = (1 / 12) / (1 + 0.41 / 12), (2 / 12) / (1 + 0.41 * 2 / 12)
    h = 7 / 30.4375
    assert curve.receive("OIS:2M", days[-1]) == pytest.approx(100 * 7 / 365 / a2)                       # (flat from 1M: no roll)
    assert curve.receive("OIS:1M", days[-1]) == pytest.approx(100 * 7 / 365 / a1 + (41 - (40 + (1 - h))) * 100)
    assert curve.receive("OIS:1M", "2020-01-01") is None                                                   # (no close: none)


def test_the_dibs_basket_buys_the_cheapest_against_the_curve_fit(planted):
    ctx, reg, mons, tab, sets, sigs = planted
    d = sets["dibs"]
    assert d["ok"] and len(d["rows"]) == len(BONDS)
    by_past = sorted(BONDS, key=lambda i: BONDS[i][1])                  # (the lowest residual of before: the cheapest now)
    legs = {leg["key"]: leg["side"] for leg in d["legs"]}
    assert legs == dict({"DIBS:" + i: -1 for i in by_past[:3]}, **{"DIBS:" + i: 1 for i in by_past[-3:]})
    assert all(leg["line"].startswith(("AL DİBS ", "SAT DİBS ")) and " · 1.000 $ DV01 · " in leg["line"] for leg in d["legs"])
    rows = {r["key"]: r for r in d["rows"]}
    assert all(rows["DIBS:" + i]["cheap"] > 0 for i in by_past[:3]) and all(rows["DIBS:" + i]["cheap"] < 0 for i in by_past[-3:])
    # (the yields flat at TLREF: no carry, no roll - the curve's residual is all there is)
    assert all(abs(r["carry"]) < 1e-6 for r in d["rows"])


# ================================================================================================ when
def test_the_weekly_rebalance_is_monday_s_close_or_the_week_s_first_business_day():
    days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-10", "2026-11-11", "2026-11-16", "2026-11-17"]
    hol = {dt.date(2026, 11, 9)}                                        # (Monday 9.11 a holiday: Tuesday's close)
    assert qs.rebalance_days(days, hol) == ["2026-11-02", "2026-11-10", "2026-11-16"]
    assert qs.rebalance_days(days + ["2026-11-23"], {dt.date(2026, 11, 23)}) == ["2026-11-02", "2026-11-10", "2026-11-16"]
    # the next one: this week's closed already - next Monday; a Monday before its close - today; a holiday Monday - Tuesday
    assert qs.next_rebalance(dt.date(2026, 11, 18), days) == dt.date(2026, 11, 23)
    assert qs.next_rebalance(dt.date(2026, 11, 18), days, {dt.date(2026, 11, 23)}) == dt.date(2026, 11, 24)
    assert qs.next_rebalance(dt.date(2026, 11, 23), days) == dt.date(2026, 11, 23)
    assert qs.next_rebalance(dt.date(2026, 11, 21), days) == dt.date(2026, 11, 23)                     # (a Saturday)
    # the family: on Wednesday the basket of Monday's close; on Monday before its close last Monday's, the next one today
    ctx, reg = market(dibs=False)
    _, _, sets = fit(ctx, reg)
    assert sets["g10"]["basket"]["formed"] == MONDAY and sets["g10"]["next"] == "2026-11-23" and sets["g10"]["next_text"] == "23.11.2026 (Pzt)"
    monday = dt.date(2026, 11, 16)
    ctx, reg = market(days=quant_synth.business_days(monday, 520), today=monday, dibs=False)
    _, _, sets = fit(ctx, reg)
    assert sets["g10"]["basket"]["formed"] == "2026-11-09" and sets["g10"]["next"] == "2026-11-16" and sets["ois"]["next"] == "2026-11-16"
    # a holiday Monday in the history: that week's basket at Tuesday's close
    hol_day = DAYS[-7]                                                  # (Monday 9.11)
    assert dt.date.fromisoformat(hol_day).weekday() == 0
    ctx, reg = market(days=[d for d in DAYS if d != hol_day], dibs=False, holidays={dt.date.fromisoformat(hol_day)})
    _, tab, sets = fit(ctx, reg)
    assert "2026-11-10" in {w["day"] for w in sets["g10"]["weeks"]} and hol_day not in {w["day"] for w in sets["g10"]["weeks"]}


def test_no_look_ahead_a_rebalance_s_basket_is_its_closes_alone():
    """Change every close after a cut (the spots, the points, the vols, the curve, the yields): the weeks that ended by
    then, their baskets and P&L, are the same; a history that stops at the cut makes the same last basket."""
    cut = DAYS[-90]

    def later(key, i, v):
        return v * 1.03 + 0.5 if DAYS[i] > cut else v

    full = fit(*market())[1]
    moved = fit(*market(edit=later))[1]
    past = [d for d in DAYS if d <= cut]
    cut_day = dt.date.fromisoformat(cut) + dt.timedelta(days=1)
    short = fit(*market(days=past, today=cut_day, dibs=False))[1]
    for a, b in zip(full["sets"], moved["sets"]):
        before = [w for w in a["weeks"] if w["end"] <= cut]
        assert before and before == [w for w in b["weeks"] if w["end"] <= cut], a["id"]
    for a in short["sets"]:
        if a["id"] == "dibs":
            continue
        ref = next(s for s in full["sets"] if s["id"] == a["id"])
        assert [w for w in a["weeks"]] == [w for w in ref["weeks"] if w["end"] <= a["weeks"][-1]["end"]], a["id"]
        # (its current basket: the full history's at that rebalance - the week after it is in the full run's weeks)
        formed = a["basket"]["formed"]
        week = next(w for w in ref["weeks"] if w["day"] == formed)
        assert week["text"] == " · ".join("%s %s" % (leg["verb"], leg["label"]) for leg in a["legs"]), a["id"]


# ================================================================================================ the lines
def test_the_lines_are_in_the_plan_s_format_with_their_target_stop_and_no_gate(planted):
    ctx, reg, mons, tab, sets, sigs = planted
    g10 = sets["g10"]
    leg = next(x for x in g10["legs"] if x["key"] == "FX:AUDUSD")
    sg = sigs[leg["sid"]]
    assert sg["expression"] == leg["line"] and sg["family_label"] == "Carry + momentum" and sg["info"]["model"] == "Carry + momentum · G10 spot sepeti"
    pat = (r"^AL AUDUSD spot · [\d.,]+ (mn|bin) AUD · giriş [\d.,]+ · hedef [\d.,]+ · stop [\d.,]+ · beklenen [+-][\d.,]+( bin)? USD · "
           r"isabet %\d+ \(\d+\) · model: Carry \+ momentum · G10 spot sepeti\. ")
    assert re.match(pat, sg["thesis"]), sg["thesis"]
    st = g10["backtest"]
    assert ("isabet %%%d (%d)" % (round(st["hit"] * 100), st["trades"])) in sg["thesis"] and st["trades"] >= qs.MIN_WEEKS
    # the expected week: the backtest's mean in risk units × the basket's risk now; target that gain, stop 2σ against
    b = g10["basket"]
    assert b["exp"] == pytest.approx(st["mean_r"] * b["risk"]) and b["stop"] == pytest.approx(-2.0 * b["risk"])
    assert sum(x["exp"] for x in g10["legs"]) == pytest.approx(b["exp"]) and leg["stop"] == pytest.approx(-2.0 * leg["sigma_w"])
    k = leg["k"]
    mo = sg["money"]                                                     # (an FX card's money: per 1 mn of its base)
    assert mo["total"] * k == pytest.approx(leg["exp"], rel=0.02) and mo["stop"] * k == pytest.approx(leg["stop"], rel=0.02)
    assert mo["target"] * k == pytest.approx(max(leg["exp"], 0.0), rel=0.02, abs=1e-6)
    assert sg["hold"] == 5 and sg["entry"] == pytest.approx(reg["FX:AUDUSD"].now())
    # a rates line: its money in TL at its own DV01 (the basket's share and 2σ of its week)
    rl = sets["ois"]["legs"][0]
    rs = sigs[rl["sid"]]
    assert rs["money"]["total"] == pytest.approx(rl["exp"]) and rs["money"]["stop"] == pytest.approx(rl["stop"])
    assert re.match(r"^receive \d+[MY] OIS · 1\.000 \$ DV01 · giriş %[\d.,]+ · hedef %[\d.,]+ · stop %[\d.,]+ · beklenen [+-][\d.,]+( bin)? TL · "
                    r"isabet %\d+ \(\d+\) · model: Carry \+ momentum · TRY OIS sepeti\.", rs["thesis"]), rs["thesis"]
    # every leg a line, nothing else: |sıra| 1 … 2 in the basket (2 the strongest), under 1 out of it
    for s in sets.values():
        for r in s["rows"]:
            m = next(x for x in mons if x.sid == r["sid"])
            assert (1.0 <= abs(m.z) <= 2.0) if r["side"] else abs(m.z) < 1.0, r
            assert (r["sid"] in sigs) == bool(r["side"])
    assert all(1.0 <= abs(s["z"]) <= 2.0 and s["score_name"] == "sıra" and s["entry_z"] == 1.0 for s in sigs.values())


def test_no_gate_holds_a_basket_line():
    """EUR's carry against USD is negative but its momentum puts it in the long basket: the forward premium is against
    the line, and with no expected gain to cover it another family's line would be held ("carry'yi karşılamıyor") - the
    card says so (✗), the line stays all the same (no "düşük güven")."""
    g10 = dict(G10, EURUSD=(1.10, -1.0, 0.0003, 7, 7.5, 0.0006))          # (EURUSD rising 0,06 % a day)
    ctx, reg = market(g10=g10, dibs=False)
    mons, tab, sets = fit(ctx, reg)
    eur = next(x for x in sets["g10"]["legs"] if x["key"] == "FX:EURUSD")
    assert eur["side"] == 1 and eur["way"] == 1 and eur["carry"] < 0
    m = next(x for x in mons if x.sid == eur["sid"])
    m.fcast = 0.0                                                        # (no expected gain: below the carry's buffer)
    sg = signals(ctx, [m])[m.sid]
    assert sg["gated"] == "" and sg["strength"] != "elendi" and sg["composite"] > 0
    carry_gate = next(g for g in sg["gates"] if g["name"] == "Carry")
    assert not carry_gate["ok"] and "carry'yi karşılamıyor" in carry_gate["text"]                  # (told on the card)
    m.ungated = False
    assert qf.make_signal(m, ctx.cfg, "10:00")["gated"].startswith("carry'yi karşılamıyor")       # (what it would have been held by)


def test_the_list_puts_try_ois_short_end_lines_before_the_long_end_and_none_in_offshore(monkeypatch):
    """Spreads (carry + roll held at 0: their order is the momentum's): 10Y rising half a point every three months
    makes 5Y/10Y the strongest steepener, 1Y's fifth of it the next ones - in the Sinyaller list the ≤ 2Y lines come
    first all the same; no set takes an Offshore instrument."""
    def ois(label, i):
        trend = {"10Y": 0.5, "1Y": 0.1}.get(label, 0.0) * i / 63.0
        return flat_ois(label, i) + trend

    monkeypatch.setattr(qs._Curve, "receive", lambda self, key, day: 0.0)
    ctx, reg = market(ois=ois, dibs=False)
    mons, tab, sets = fit(ctx, reg)
    sp = sets["spread"]
    keys = [leg["key"] for leg in sp["legs"]]
    assert keys[0] == "OISS:5Y/10Y" and sp["legs"][0]["verb"] == "steepener" and len(keys) == 3
    assert all(qf._TENOR_MONTHS[k.split(":")[1].split("/")[1]] <= 24 for k in keys[1:])
    sigs = list(signals(ctx, mons).values())
    live, gated = qf.rank(sigs)
    ordered = [s for s in qu.order(live, gated) if s["id"].startswith(("sira:spread:", "sira:fly:", "sira:ois:"))]
    tiers = [s["tier"] for s in ordered]
    assert "uzun" in tiers and tiers == sorted(tiers, key=lambda t: t != "≤ 2Y")
    long_line = next(s for s in ordered if s["id"] == "sira:spread:OISS:5Y/10Y")
    assert long_line["composite"] >= max(s["composite"] for s in ordered if s["tier"] == "≤ 2Y" and s["id"].startswith("sira:spread:"))
    # no Offshore instrument in a set: no line of the family in that group, every line with its group's tag ("" here)
    assert not any(r["key"].startswith(("FWD:", "FXP:", "OFF:")) for s in sets.values() for r in s["rows"])
    every = qu.order(*qf.rank(sigs))
    assert every and all(s["group"] in ("G10 spot", "G10 opsiyon", "TRY OIS", "DİBS") and s["tag"] == qu.TAGS.get(s["group"], "") for s in every)


# ================================================================================================ the backtest
def test_the_backtest_is_weekly_per_set_and_the_panel_takes_it(planted):
    ctx, reg, mons, tab, sets, sigs = planted
    bt = tab["backtest"]
    types = {t["type"] for t in bt["trades"]}
    assert types == {s["name"] for s in sets.values() if s["ok"]} and bt["first"] < bt["last"]
    for s in sets.values():
        weeks = s["weeks"]
        assert all(qs.rebalance_days([w["day"]]) and dt.date.fromisoformat(w["day"]).weekday() == 0 for w in weeks), s["id"]
        assert all(w["end"] > w["day"] and w["held"] == 5 for w in weeks[1:]), s["id"]
        st = s["backtest"]
        assert st["trades"] == len(weeks) and st["hit"] == pytest.approx(sum(1 for w in weeks if w["pnl"] > 0) / len(weeks))
        assert st["mean_r"] == pytest.approx(sum(w["r"] for w in weeks) / len(weeks))
    # the backtest's result: the family over its own span, a type a set (the refits leave the family out)
    res = {"families": {"pca": {"trades": 3}}, "trades": [], "n_trades": 7}
    qu.own_backtests(res, {"sira": tab})
    fam = res["families"]["sira"]
    assert fam["own"] and set(fam["types"]) == types and fam["trades"] == len(bt["trades"]) and res["n_trades"] == 7 + len(bt["trades"])
    assert fam["years"] == pytest.approx((dt.date.fromisoformat(bt["last"]) - dt.date.fromisoformat(bt["first"])).days / 365.0)
    assert fam["types"]["G10 spot sepeti"]["trades"] == sets["g10"]["backtest"]["trades"] and res["families"]["pca"] == {"trades": 3}
    assert qbt.bt_text(fam, fam["years"]).startswith("bu aile son 1,") and "sira" in qu.OWN_BT
    assert not [m for m in qu.monitors(ctx) if m.family == "sira"]


# ================================================================================================ the service
@pytest.fixture(scope="module")
def seeded(module_service):
    svc = module_service
    svc.quant.use_live = False
    quant_synth.seed(svc)
    return svc


def test_the_family_runs_in_the_fit_its_page_and_the_backtest_panel(seeded):
    svc = seeded
    q = svc.quant
    st = q.compute()
    assert st["ready"] and "sira" in st["timing"] and not st["errors"].get("sira"), st["errors"]
    user = svc.login("sıra okuyucu")["user"]
    page = q.view("sira", user, {})
    sets = {s["id"]: s for s in page["sira"]["sets"]}
    assert list(sets) == [s[0] for s in qs.SETS] and sets["ois"]["ok"] and sets["ois"]["legs"]
    assert "backtest" not in page["sira"] and all(s["family"] == "sira" for s in page["signals"]) and page["signals"]
    leg = sets["ois"]["legs"][0]
    assert leg["so_far_now"] == pytest.approx(leg["so_far"]) and sets["ois"]["basket"]["so_far_now"] == pytest.approx(sets["ois"]["basket"]["so_far"])
    # the Sinyaller list: the family's lines with the basket's name, in their group
    listed = [s for s in q.view("signals", user, {})["signals"] if s["family"] == "sira"]
    assert listed and all(s["info"]["model"].startswith("Carry + momentum · ") and s["group"] == "TRY OIS" for s in listed)
    res = q.run_backtest(days=120, step=20)
    fam = res["families"]["sira"]
    assert fam["own"] and "TRY OIS sepeti" in fam["types"] and fam["trades"] >= qs.MIN_WEEKS
    q.compute()
    mine = [s for s in q.view("signals", user, {})["signals"] if s["family"] == "sira"]
    assert mine and all(s["bt"]["text"].startswith("bu aile") and s["bt"]["trades"] for s in mine)
    rows = q.view("backtest", user, {})["rows"]
    assert any(r["family"] == "sira" and r["type"] == "TRY OIS sepeti" for r in rows)
    with TestClient(create_app(svc), headers=auth(svc, "Sıra HTTP")) as client:
        body = client.get("/api/quant/sira").json()
        assert body["ready"] and [s["id"] for s in body["sira"]["sets"]] == [s[0] for s in qs.SETS]
        nav = [p for p in client.get("/api/nav").json()["pages"] if p["id"] == "quant-sira"]
        assert nav and nav[0]["menu"] == "quant.sinyal" and nav[0]["tab"] == "Carry + momentum"
        assert client.get("/static/js/pages/quantsira.js").status_code == 200
