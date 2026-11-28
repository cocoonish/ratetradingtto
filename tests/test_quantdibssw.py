"""DİBS switch (``tto/quantdibssw.py``) on a synthetic market whose answers are planted: in each of two duration clusters
one bond yields the most and its yield keeps falling (the best carry + roll and momentum), one yields the least and its
yield keeps rising (the worst) - the week's switches buy the one and sell the other, never across the clusters (the
duration band), DV01-balanced at the desk's size and rounding; the weekly rebalance (Monday's close, a holiday's week its
next business day, the next one on the card), no look-ahead, the bonds left out with their reason, the levels calibrated
on the switches' paths (quantlevels: ≥ 30 trades) and applied to the lines, "düşük güven" on a losing record, the line in
the plan's format.  (The HTTP part last: leaving its client stops the module's service.)"""
from __future__ import annotations

import datetime as dt
import math
import re

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quant as qq
from tto import quantfam as qf
from tto import quantdibssw as qd
from tto import quantlevels as qlv
from tto import quantsira as qs
from tto import quantuniv as qu
from tto.server import create_app

TODAY = dt.date(2026, 11, 18)                    # a Wednesday: this week's switches were made at Monday's (16.11) close
MONDAY = "2026-11-16"
DAYS = quant_synth.business_days(TODAY, 300)     # (about the year of closes the history keeps of a bond)
FUND = 30.0                                      # TLREF and the OIS curve, flat (%)
MONTHS = {"1W": 0.25, "1M": 1, "2M": 2, "3M": 3, "6M": 6, "1Y": 12, "2Y": 24, "3Y": 36, "5Y": 60, "10Y": 120}
#: ISIN -> (maturity, its yield's offset from 30 % today, its drift a close (%, + the yield falling), DİBS RV's kind): in each
#: cluster the best (yielding the most, falling) and the worst (the least, rising), the offsets alternating along the
#: maturities (no shape of the curve to roll on); a bill, a TLREF floater and a bond about to mature
BONDS = {
    "TRT150228T11": ("2028-02-15", 1.0, 0.010, "S"),
    "TRT150428T12": ("2028-04-15", -1.0, -0.010, "S"),
    "TRT150628T13": ("2028-06-15", 0.4, 0.003, "S"),
    "TRT150828T14": ("2028-08-15", -0.4, -0.003, "S"),
    "TRT151131T15": ("2031-11-15", -1.0, -0.010, "S"),
    "TRT150532T16": ("2032-05-15", 1.0, 0.010, "S"),
    "TRT151132T17": ("2032-11-15", -0.4, -0.003, "S"),
    "TRT150533T18": ("2033-05-15", 0.4, 0.003, "S"),
    "TRB100727T19": ("2027-07-10", 0.0, 0.0, "B"),
    "TRT090130T20": ("2030-01-09", 0.0, 0.0, "T"),
    "TRT021226T21": ("2026-12-02", 0.0, 0.0, "S"),
}
SHORT = ("TRT150228T11", "TRT150428T12", "TRT150628T13", "TRT150828T14")
LONG = ("TRT151131T15", "TRT150532T16", "TRT151132T17", "TRT150533T18")


def wave(i, amp, period, phase=0.0):
    return amp * math.sin(2.0 * math.pi * i / period + phase)


def cfg(**kw):
    out = dict(qq.DEFAULTS, usdtry=42.0)
    out.update(kw)
    return out


def market(days=None, today=TODAY, bonds=None, holidays=None, edit=None, desk=None, live=None):
    """A context with the family's series - TLREF and the OIS curve (the funding), the bonds' yields (a floater's price)
    and DİBS RV's rows (terms) - and the registry on it.  ``edit(key, i, value)``: a value changed (look-ahead)."""
    days = list(days or DAYS)
    n = len(days)
    series, meta = {}, {}

    def put(key, vals, **m):
        if edit is not None:
            vals = [edit(key, i, v) for i, v in enumerate(vals)]
        series[key] = dict(zip(days, vals))
        meta[key] = m

    put("TLREF", [FUND] * n, label="TLREF", kind="rate", group="ref")
    for label, mo in MONTHS.items():
        put("OIS:" + label, [FUND] * n, label=label + " OIS", kind="rate", months=float(mo))
    series["FX:USDTRY"] = {d: 42.0 for d in days}
    meta["FX:USDTRY"] = {"label": "USDTRY", "kind": "fx", "group": "TRY"}
    rows = []
    for r, (isin, (mat, off, drift, kind)) in enumerate((bonds or BONDS).items()):
        vals = [30.0 + off - drift * (i - n + 1) + wave(i, 0.02, 7 + r, 0.7 * r) for i in range(n)]
        floater = kind == "T"
        put("DIBS:" + isin, [99.5] * n if floater else vals, label=isin, kind="index" if floater else "rate", group="dibs",
            unit="px" if floater else "pct", maturity=mat, type=kind, name="")
        rows.append({"isin": isin, "type": kind, "row": 5 + r, "name": "", "maturity": mat, "coupon": 30.0 if kind == "S" else None,
                     "freq": 2.0, "simple": None, "compound": None, "source": ""})
    ctx = qf.Ctx(cfg(), today, series, meta, live or {}, holidays=holidays or set(), desk=desk)
    return ctx, qu.Registry(ctx, {}, {"dibs": rows})


def fit(ctx, reg):
    return qd.run(ctx, reg, ctx.cfg)


def signals(ctx, mons, tab, levels=None):
    """The family's lines as tto.quant publishes them: its table's calibrated levels on each monitor, make_signal."""
    book = qlv.Book.from_json(levels if levels is not None else tab["levels"])
    qf.score_all(ctx, mons, ctx.live)
    out = {}
    for m in mons:
        m.levels = book.line(qlv.group_of(m))
        sg = qf.make_signal(m, ctx.cfg, "10:00")
        if sg is not None:
            out[m.sid] = sg
    return out


@pytest.fixture(scope="module")
def planted():
    ctx, reg = market()
    mons, tab = fit(ctx, reg)
    return ctx, reg, mons, tab, signals(ctx, mons, tab)


def ratio(a, b):
    return max(a, b) / min(a, b)


# ================================================================================================ the switches
def test_a_planted_carry_and_momentum_order_gives_the_right_switches(planted):
    ctx, reg, mons, tab, sigs = planted
    assert tab["ok"] and tab["formed"] == MONDAY and tab["next"] == "2026-11-23"
    # in each cluster the best bond bought, the worst sold - the two widest gaps of the week
    pairs = [(s["al"], s["sat"]) for s in tab["switches"]]
    assert set(pairs[:2]) == {("TRT150228T11", "TRT150428T12"), ("TRT150532T16", "TRT151131T15")} and len(pairs) <= qd.MAX_SWITCHES
    bonds = {b["isin"]: b for b in tab["bonds"]}
    for al, sat in pairs:
        assert bonds[al]["side"] == "AL" and bonds[sat]["side"] == "SAT" and bonds[al]["comp"] - bonds[sat]["comp"] >= qd.MIN_GAP
    assert len({x for p in pairs for x in p}) == 2 * len(pairs)                           # (no bond twice)
    # each part as the module says: carry (y − f) × 30/365 ÷ duration, momentum −(y − y 21 closes before), each a z
    # across the bonds, the composite their sum; the planted order in both parts
    for isin in ("TRT150228T11", "TRT150532T16"):
        b = bonds[isin]
        assert b["carry"] == pytest.approx((b["y"] - FUND) * 100.0 * 30.0 / 365.0 / b["dur"]) and b["f"] == pytest.approx(FUND)
        assert b["mom"] == pytest.approx(BONDS[isin][2] * 21 * 100.0, abs=6.0)          # (+ its noise's month)
        assert b["comp"] == pytest.approx(b["z_cr"] + b["z_mom"]) and b["cr"] == pytest.approx(b["carry"] + b["roll"])
    for cluster, best, worst in ((SHORT, "TRT150228T11", "TRT150428T12"), (LONG, "TRT150532T16", "TRT151131T15")):
        assert max(cluster, key=lambda i: bonds[i]["cr"]) == best and min(cluster, key=lambda i: bonds[i]["cr"]) == worst
        assert max(cluster, key=lambda i: bonds[i]["mom"]) == best and min(cluster, key=lambda i: bonds[i]["mom"]) == worst
    comps = [b["comp"] for b in tab["bonds"]]
    assert comps == sorted(comps, reverse=True) and [b["rank"] for b in tab["bonds"]] == list(range(1, len(comps) + 1))
    # the switches are the widest gaps of the band, the widest first
    gaps = [s["gap"] for s in tab["switches"]]
    assert gaps == sorted(gaps, reverse=True)


def test_the_duration_band_keeps_a_switch_to_bonds_of_a_similar_duration(planted, monkeypatch):
    ctx, reg, mons, tab, sigs = planted
    dur = {b["isin"]: b["dur"] for b in tab["bonds"]}
    assert all(ratio(dur[s["al"]], dur[s["sat"]]) <= qd.DUR_RATIO for s in tab["switches"])
    # a monitor for every pair of the band - and only for those: no short bond against a long one
    keys = [tuple(m.sid.split(":", 1)[1].split("/")) for m in mons]
    assert keys and all(ratio(dur[a], dur[b]) <= qd.DUR_RATIO for a, b in keys)
    assert not any((a in SHORT and b in LONG) or (a in LONG and b in SHORT) for a, b in keys)
    every = [(a, b) for i, a in enumerate(dur) for b in list(dur)[i + 1:]]
    assert len(keys) == sum(1 for a, b in every if ratio(dur[a], dur[b]) <= qd.DUR_RATIO) == tab["pairs"]
    # each pair in one orientation - the week's AL (the higher composite) first, its level y_AL − y_SAT (28.11.2026: one
    # sign convention - the list, the card, the table and the log alike)
    comp = {b["isin"]: b["comp"] for b in tab["bonds"]}
    assert all(comp[a] >= comp[b] for a, b in keys)
    for m in mons:
        a, b = m.sid.split(":", 1)[1].split("/")
        ya, yb = ctx.series["DIBS:" + a], ctx.series["DIBS:" + b]
        last = max(set(ya) & set(yb))
        assert m.values[-1] == pytest.approx((ya[last] - yb[last]) * 100.0) and m.level == pytest.approx(m.values[-1]), m.sid
        assert m.info["al"] == a and m.info["sat"] == b and (m.z or 0.0) <= 0.0          # (the side taken: AL − SAT falling)
    # a wider band takes in the pairs across the clusters
    monkeypatch.setattr(qd, "DUR_RATIO", 5.0)
    wide, _ = fit(*market())
    assert len(wide) == len(every) > len(keys)


def test_the_switch_is_dv01_balanced_at_the_desk_s_size_and_rounding(planted):
    ctx, reg, mons, tab, sigs = planted
    usd, tl = ctx.dv01_size()
    assert usd == 1000.0 and tl == pytest.approx(42000.0)
    for s in tab["switches"]:
        z = s["size"]
        assert z["round"] == qd.ROUND_TL and z["al"] % 5e6 == 0 and z["sat"] % 5e6 == 0
        dv_al, dv_sat = z["dv01_al"] / (z["al"] / 1e6), z["dv01_sat"] / (z["sat"] / 1e6)          # (TL a bp a 1 mn)
        # the AL leg the desk's DV01 within half a rounding unit; the SAT leg the AL leg's DV01 within half a unit
        assert abs(z["dv01_al"] - tl) <= 2.5 * dv_al + 1e-6 and abs(z["dv01_sat"] - z["dv01_al"]) <= 2.5 * dv_sat + 1e-6
        assert abs(z["gap"]) < 0.03 and s["size_text"] == "%s / %s" % (qd.mn_text(z["al"]), qd.mn_text(z["sat"]))
        sg = sigs[s["sid"]]
        legs = {l["key"]: l for l in sg["legs"]}
        al, sat = legs["DIBS:" + s["al"]], legs["DIBS:" + s["sat"]]
        assert al["action"] == "Buy" and sat["action"] == "Sell" and sg["legs"][0]["key"] == "DIBS:" + s["al"]
        assert al["notional"] == pytest.approx(z["al"] / 1e6) and sat["notional"] == pytest.approx(z["sat"] / 1e6)
        assert al["dv01"] == pytest.approx(z["dv01_al"]) and sat["dv01"] == pytest.approx(z["dv01_sat"])
        assert sg["money"]["per_bp"] == pytest.approx(z["dv01_al"])                      # (the P&L: bp of the AL leg's DV01)
    # the desk's rounding as the workbook says it (OIS_MAIN!H2)
    ctx2, reg2 = market(desk={"usdtry": 42.0, "round_tl": 1e6})
    _, tab2 = fit(ctx2, reg2)
    assert all(s["size"]["al"] % 1e6 == 0 and s["size"]["round"] == 1e6 for s in tab2["switches"])


# ================================================================================================ when
def test_the_weekly_rebalance_is_monday_s_close_or_the_week_s_first_business_day():
    # on Monday before its close: last Monday's switches, the next ones today
    monday = dt.date(2026, 11, 16)
    ctx, reg = market(days=quant_synth.business_days(monday, 300), today=monday)
    _, tab = fit(ctx, reg)
    assert tab["formed"] == "2026-11-09" and tab["next"] == "2026-11-16" and tab["next_text"] == "16.11.2026 (Pzt)"
    # a holiday Monday in the history: that week's switches at Tuesday's close, held to the next rebalance
    hol = DAYS[-7]
    assert dt.date.fromisoformat(hol).weekday() == 0
    ctx, reg = market(days=[d for d in DAYS if d != hol], holidays={dt.date.fromisoformat(hol)})
    _, tab = fit(ctx, reg)
    days = {t["entry_day"] for t in tab["backtest"]["trades"]}
    assert "2026-11-10" in days and hol not in days
    assert all(dt.date.fromisoformat(d).weekday() == 0 for d in days - {"2026-11-10"})
    assert all(t["held"] == 5 and t["exit_day"] > t["entry_day"] for t in tab["backtest"]["trades"] if t["entry_day"] < "2026-11-02")


def test_no_look_ahead_a_week_s_switches_are_its_closes_alone():
    """Change every close after a cut: the switches that ended by then, their P&L and paths, are the same."""
    cut = DAYS[-60]

    def later(key, i, v):
        return v * 1.02 + 0.3 if DAYS[i] > cut else v

    full = fit(*market())[1]["backtest"]["trades"]
    moved = fit(*market(edit=later))[1]["backtest"]["trades"]
    before = [t for t in full if t["exit_day"] <= cut]
    assert before and before == [t for t in moved if t["exit_day"] <= cut]


# ================================================================================================ the universe
def test_the_universe_is_the_fixed_coupon_bonds_and_bills_the_others_say_why(planted):
    ctx, reg, mons, tab, sigs = planted
    kinds = {b["isin"]: b["kind"] for b in tab["bonds"]}
    assert kinds["TRB100727T19"] == "B" and all(kinds[i] == "S" for i in SHORT + LONG)
    out = {o["isin"]: o for o in tab["out"]}
    assert set(out) == {"TRT090130T20", "TRT021226T21"}
    assert out["TRT090130T20"]["why"] == qd.OUT["T"] and out["TRT090130T20"]["label"] == "09.01.30 TLREF"
    assert out["TRT021226T21"]["why"].startswith("vadesine 14 gün kaldı")
    # a TLREF floater, an FRN, a CPI linker: each its reason, none in a pair
    assert {"T", "F", "E"} <= set(qd.OUT) and not any("TRT090130T20" in m.sid for m in mons)


# ================================================================================================ the levels and the line
def test_the_levels_are_calibrated_on_the_switches_paths_and_applied_to_the_lines(planted):
    ctx, reg, mons, tab, sigs = planted
    trades = tab["backtest"]["trades"]
    assert len(trades) >= qlv.MIN_TRADES and all(t["group"] == "DİBS" and len(t["path_sigma"]) == t["held"] for t in trades)
    # a path: the fall of the yield difference plus the C+R pro rata, in σ of the switch's week; its last the trade's P&L
    for t in trades[:20]:
        assert t["path_sigma"][-1] == pytest.approx(t["pnl_sigma"]) and t["pnl"] == pytest.approx(t["pnl_sigma"] * t["sigma"])
        assert t["pnl_try"] == pytest.approx(t["pnl"] * 42000.0) and t["carry_in"] and t["sigma_closes"] == qd.WEEK
    book = qlv.Book.from_json(tab["levels"])
    lv = book.line("DİBS")
    assert book.family == "dibssw" and lv["ok"] and lv["rr"] >= 1.0 and lv["n"] >= qlv.MIN_OOS and tab["level_line"]["k"] == lv["k"]
    assert tab["stats"]["trades"] == len(trades) and tab["stats"]["hit"] > 0.5                        # (the planted switches win)
    for s in tab["switches"]:
        sg = sigs[s["sid"]]
        m = next(x for x in mons if x.sid == s["sid"])
        sig_h = m.dsd * math.sqrt(qd.WEEK)
        assert sg["levels"]["ok"] and sg["gated"] == "" and sg["rr"] == pytest.approx(lv["m"] / lv["k"])
        assert abs(sg["target"] - sg["entry"]) == pytest.approx(lv["m"] * sig_h) and abs(sg["stop"] - sg["entry"]) == pytest.approx(lv["k"] * sig_h)
        assert sg["exp_pnl"] == pytest.approx(lv["exp"] * sig_h)
        # the trade's side: the AL bond's yield falling against the SAT bond's - the difference AL − SAT down, the level
        # itself AL − SAT (the table's "Giriş → şimdi" and the card's sentence say the same number: 28.11.2026)
        assert sg["direction"] == -1 and sg["target"] < sg["entry"] < sg["stop"]
        assert sg["entry"] == pytest.approx(m.level) and "şimdi %s bp" % qf._sg(m.level, 1) in sg["plain"]


def test_the_line_is_in_the_plan_s_format(planted):
    ctx, reg, mons, tab, sigs = planted
    lv = qlv.Book.from_json(tab["levels"]).line("DİBS")
    s = tab["switches"][0]
    sg = sigs[s["sid"]]
    # (the bonds by the desk's names - "15.02.28" -, not their ISINs: 28.11.2026; the ISINs in the table's tooltip)
    pat = (r"^AL (\d\d\.\d\d\.\d\d(?: Bono)?) / SAT (\d\d\.\d\d\.\d\d(?: Bono)?) · switch · \d+ mn / \d+ mn · C\+R [+-][\d,]+ bp/ay · "
           r"1A momentum (lehte|aleyhte) · hedef \+[\d,]+ bp · stop -[\d,]+ bp · beklenen [+-][\d.,]+( bin| mn)? TL · isabet %\d+ \(\d+\)$")
    m = re.match(pat, sg["line"])
    assert m and (m.group(1), m.group(2)) == (s["al_label"], s["sat_label"]) and sg["expression"] == sg["line"], sg["line"]
    assert "TRT" not in sg["line"] and "TRT" not in sg["instrument"] and all("TRT" not in l["name"] for l in sg["legs"])
    assert sg["trade_line"] == "AL %s / SAT %s · switch · %s" % (s["al_label"], s["sat_label"], s["size_text"])
    assert all("TRT" not in t["expression"] for t in tab["backtest"]["trades"]) and all("TRT" not in w["text"] for w in tab["weeks"])
    assert m.group(3) == "lehte" and s["size_text"] in sg["line"] and "isabet %%%d (%d)" % (round(lv["hit"] * 100), lv["n"]) in sg["line"]
    assert "hedef +%s bp" % qf._g(abs(sg["target"] - sg["entry"]), 1) in sg["line"] and "stop -%s bp" % qf._g(abs(sg["stop"] - sg["entry"]), 1) in sg["line"]
    assert "beklenen %s" % qf._money(sg["money"]["total"], "TL") in sg["line"]
    assert sg["info"]["model"] == "DİBS switch" and sg["family_label"] == "DİBS switch" and qu.classify(sg)["group"] == "DİBS"
    assert sg["plain"].startswith("DİBS switch: ") and "Seviyeler geçmiş haftalık switch'lerden" in sg["plain"]
    # "sıra": 2 the widest of the week … 1 the narrowest; a pair not taken under 1 (no line)
    taken = {x["sid"] for x in tab["switches"]}
    for mon in mons:
        assert (1.0 <= abs(mon.z) <= 2.0) if mon.sid in taken else abs(mon.z) < 1.0, mon.sid
        assert (mon.sid in sigs) == (mon.sid in taken)
    assert abs(next(x for x in mons if x.sid == tab["switches"][0]["sid"]).z) == 2.0


def test_one_sign_convention_in_the_list_the_card_the_table_and_the_page(planted):
    """28.11.2026: the same switch read −6,2 in the list, +6,2 in the card's sentence and −10,0 → +6,2 in the table - one
    convention now, the yield difference AL − SAT everywhere: the list's entry (the monitor's level), the card's "şimdi",
    the table's "Giriş → şimdi" (at the rebalance, now) and the P&L since (its fall); the series the card draws too."""
    ctx, reg, mons, tab, sigs = planted
    by = {m.sid: m for m in mons}
    v = {"signals": list(sigs.values()), "gated": [], "tables": {}}
    fit = {"tables": {"dibssw": tab}, "mons": by, "cfg": ctx.cfg, "ctx": ctx, "coverage": []}
    page = {s["sid"]: s for s in qd.view(None, "dibssw", {}, v, fit)["dibssw"]["switches"]}
    for s in tab["switches"]:
        m, sg, row = by[s["sid"]], sigs[s["sid"]], page[s["sid"]]
        a, b = ctx.series["DIBS:" + s["al"]], ctx.series["DIBS:" + s["sat"]]
        formed = (a[tab["formed"]] - b[tab["formed"]]) * 100.0
        assert s["level_formed"] == pytest.approx(formed) and m.values[m.days.index(tab["formed"])] == pytest.approx(formed)
        assert sg["entry"] == pytest.approx(m.level) and row["now"] == pytest.approx(m.level)
        assert row["so_far"] == pytest.approx(-(m.level - formed)) and "şimdi %s bp" % qf._sg(m.level, 1) in sg["plain"]
        assert m.series_label.startswith("getiri farkı AL − SAT: %s − %s" % (s["al_label"], s["sat_label"]))
        assert m.name == "%s / %s switch" % (s["al_label"], s["sat_label"])


def test_the_sheet_s_live_c_and_r_is_the_line_s(planted):
    """DİBS RV's own C+R (AO over its horizon J2) is what today's line tells; the history's beside it on the page."""
    ctx, reg, mons, tab, sigs = planted
    s = tab["switches"][0]
    rows = reg.eng["dibs"]
    for r in rows:
        r["cr_bp"] = {s["al"]: 30.0, s["sat"]: 6.0}.get(r["isin"])
    reg.eng["dibs_cr_months"] = 3.0
    try:
        mons2, tab2 = fit(ctx, reg)
    finally:
        for r in rows:
            r.pop("cr_bp", None)
        reg.eng.pop("dibs_cr_months", None)
    s2 = next(x for x in tab2["switches"] if x["sid"] == s["sid"])
    assert s2["cr_sheet"] == pytest.approx(8.0) and s2["cr"] == pytest.approx(8.0) and s2["cr_hist"] == pytest.approx(s["cr_hist"])
    sg = signals(ctx, mons2, tab2)[s["sid"]]
    assert "C+R +8,0 bp/ay" in sg["line"] and sg["carry_week"] == pytest.approx(8.0 * qd.WEEK / qd.MONTH_CLOSES)


def test_a_losing_record_makes_every_line_low_confidence(planted):
    """The same switches in a market that went against each of them (every path the other way): the calibrated levels
    lose money all the same - each line stays in the list, "düşük güven", with the reason."""
    ctx, reg, mons, tab, sigs = planted
    lost = [dict(t, path_sigma=[-x for x in t["path_sigma"]], pnl_sigma=-t["pnl_sigma"], pnl=-t["pnl"]) for t in tab["backtest"]["trades"]]
    book = qlv.calibrate(lost, qd.FAMILY, ctx.today_iso)
    lv = book.line("DİBS")
    assert lv["ok"] and lv["exp"] < 0
    low = signals(ctx, mons, tab, levels=book.to_json())
    assert low and all(sg["gated"] == qlv.LOSS and sg["strength"] == "elendi" for sg in low.values())
    live, gated = qf.rank(list(low.values()))
    assert not live and len(gated) == len(low)


# ================================================================================================ the service
@pytest.fixture(scope="module")
def seeded(module_service):
    svc = module_service
    svc.quant.use_live = False
    quant_synth.seed(svc)
    return svc


def test_the_family_runs_in_the_fit_its_page_and_the_menu(seeded):
    svc = seeded
    q = svc.quant
    st = q.compute()
    assert st["ready"] and "dibssw" in st["timing"] and not st["errors"].get("dibssw"), st["errors"]
    user = svc.login("switch okuyucu")["user"]
    page = q.view("dibssw", user, {})
    tab = page["dibssw"]
    assert "backtest" not in tab and "levels" not in tab and isinstance(tab["out"], list)
    # (the recorded month is too short for a ranking: the table says why; the floaters are out with their reason)
    assert tab["ok"] or tab["why"]
    assert all(o["why"] for o in tab["out"]) and all(s["family"] == "dibssw" for s in page["signals"])
    fams = [f["id"] for f in q.view("signals", user, {})["families"]]
    assert fams[-1] == "dibssw" and "dibssw" in qu.RUNNERS and "dibssw" in qu.OWN_BT
    with TestClient(create_app(svc), headers=auth(svc, "Switch HTTP")) as client:
        body = client.get("/api/quant/dibssw").json()
        assert body["ready"] and "dibssw" in body
        nav = [p for p in client.get("/api/nav").json()["pages"] if p.get("menu") == "quant.faiz"]
        ids = [p["id"] for p in nav]
        assert ids[ids.index("quant-curve") + 1] == "quant-dibssw" and nav[ids.index("quant-dibssw")]["tab"] == "DİBS switch"
        assert client.get("/static/js/pages/quantdibssw.js").status_code == 200
