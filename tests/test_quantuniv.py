"""The universe of the systematic families (``tto/quantuniv.py``): every planned instrument in the registry with its
group, priority, unit and size; spreads, flies and FRAs from the right tenors and signs on planted levels; the PPK
period series rolling on a meeting; sizes and money; the Sinyaller list's groups and order, "offshore limiti", the
"düşük güven" lines that stay in it and never alert; the hook a family plugs in with; the G10 series in the history
and their fill order.  (The HTTP part last: leaving its client stops the module's service.)"""
from __future__ import annotations

import datetime as dt
import math

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quant as qq
from tto import quantbt as qbt
from tto import quantfam as qf
from tto import quantopt as qopt
from tto import quantuniv as qu
from tto import quantviop as qv
from tto.server import create_app

TODAY = dt.date(2026, 11, 3)
DAYS = quant_synth.business_days(TODAY, 300)
MONTHS = {"1W": 0.25, "2W": 0.5, "1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12, "15M": 15, "18M": 18, "21M": 21, "2Y": 24,
          "3Y": 36, "4Y": 48, "5Y": 60, "6Y": 72, "7Y": 84, "8Y": 96, "9Y": 108, "10Y": 120}
G10_SPOT = {"EURUSD": 1.10, "USDJPY": 150.0, "GBPUSD": 1.27, "AUDUSD": 0.66, "USDCAD": 1.37, "USDCHF": 0.88, "NZDUSD": 0.60}
ISIN = "TRT150329T15"
CONTRACTS = ("A1Z6 Curncy", "A1H7 Curncy")
# PPK: two meetings in the window (the series rolls on them), three ahead of today
PAST = (DAYS[-40], DAYS[-15])
AHEAD = ("2026-12-10", "2027-01-21", "2027-03-04")


def planted(label):
    """Each tenor's own constant over the common move: a spread / fly / FRA of them is known to the bp."""
    return 40.0 + 0.01 * MONTHS[label]


def common(i):
    return 0.5 * math.sin(i / 9.0)


def cfg(**kw):
    out = dict(qq.DEFAULTS, usdtry=42.0)
    out.update(kw)
    return out


def _level(meeting):
    """A meeting's TLREF level after it (a fraction): one step lower a meeting."""
    allm = list(PAST) + list(AHEAD)
    return 0.42 - 0.01 * (allm.index(meeting) + 1)


def mpc_of(days):
    """The meeting path of each day as the history keeps it (``store.mpc_days`` / ``mpc_values``)."""
    out = {"days": {}, "values": []}
    for d in days:
        spot = qf.business_on_or_after(dt.date.fromisoformat(d) + dt.timedelta(days=1), set()).isoformat()
        out["days"][d] = {"spot": spot, "base": 0.42, "status": "OK"}
        for m in list(PAST) + list(AHEAD):
            out["values"].append({"day": d, "meeting": m, "level": _level(m)})
    return out


def uni_ctx(today=TODAY, live=None, viop=True, mpc=None, extra=None, **kw):
    """A context with every series the universe reads: the TRY OIS tenors (planted), the G10 spots / points / vols,
    USDTRY / EURTRY and their points, the offshore curve, the global drivers, a DİBS, two VİOP contracts, the meeting
    paths - and the workbook's part (``eng``: the DİBS RV row) the registry takes."""
    series, meta = {}, {}

    def put(key, values, **m):
        series[key] = dict(zip(DAYS, values))
        meta[key] = m

    for label, mo in MONTHS.items():
        put("OIS:" + label, [planted(label) + common(i) for i in range(len(DAYS))], label=label + " OIS", kind="rate", months=float(mo))
    for label in ("1M", "3M", "1Y"):
        put("OFF:" + label, [planted(label) - 2.0 + common(i) for i in range(len(DAYS))], label="Offshore " + label, kind="rate",
            months=float(MONTHS[label]), group="off")
    for pair, s0 in G10_SPOT.items():
        put("FX:" + pair, [s0 * math.exp(0.002 * math.sin(i / 7.0)) for i in range(len(DAYS))], label=pair, kind="fx", group="G10",
            universe=pair == "NZDUSD")
        put("FXP:%s:3M" % pair, [25.0 if not pair.endswith("JPY") else -80.0] * len(DAYS), label=pair + " 3M swap puanı", kind="pts", group="G10")
        for vk, tenor in qu.G10_VOLS:
            put(qopt.key(pair, vk, tenor), [(7.0 if vk == "ATM" else 0.5) + 0.2 * math.sin(i / 5.0) for i in range(len(DAYS))],
                label=qopt.label(pair, vk, tenor), kind="vol", group="G10")
    usdtry = [42.0 * math.exp(0.0007 * i) for i in range(len(DAYS))]
    put("FX:USDTRY", usdtry, label="USDTRY", kind="fx", group="TRY")
    for tenor, days in (("1M", 30.4), ("3M", 91.25), ("6M", 182.5), ("1Y", 365.0)):
        put("FXP:USDTRY:" + tenor, [s * 0.30 * days / 365.0 * 1e4 for s in usdtry], label="USDTRY %s swap puanı" % tenor, kind="pts", group="TRY")
    eurtry = [usdtry[i] * series["FX:EURUSD"][d] for i, d in enumerate(DAYS)]
    put("FX:EURTRY", eurtry, label="EURTRY", kind="fx", group="TRY")
    put("FXP:EURTRY:3M", [s * 0.28 * 91.25 / 365.0 * 1e4 for s in eurtry], label="EURTRY 3M swap puanı", kind="pts", group="TRY")
    for key, v0 in (("UST:2Y", 3.8), ("UST:10Y", 4.3), ("DXY", 100.0), ("BRENT", 70.0), ("CDS", 280.0), ("TLREF", 39.5),
                    ("USD:1M", 4.0), ("USD:3M", 4.0), ("USD:6M", 4.0), ("USD:1Y", 4.0)):
        put(key, [v0 + 0.01 * math.sin(i / 4.0) for i in range(len(DAYS))], label=key, kind="rate" if key.startswith(("UST", "USD", "TLREF")) else "index",
            group="Global")
    put("DIBS:" + ISIN, [35.0 + 0.3 * math.sin(i / 11.0) for i in range(len(DAYS))], label=ISIN, kind="rate", group="dibs", unit="pct",
        maturity="2029-03-15", type="S", name="")
    if viop:
        hol = set()
        for t in CONTRACTS:
            _, month, digits, _ = qv.parse_ticker(t)
            exp = qv.expiry_of(qv.year_of(digits, today), month, hol)
            px = {}
            for i, d in enumerate(DAYS):
                g = qv.days_to(exp, d, hol)
                if g > 0:
                    px[d] = usdtry[i] * (1.0 + 0.40 * g / 360.0) / (1.0 + 0.04 * g / 360.0)
            series["VIOPF:" + t] = px
            meta["VIOPF:" + t] = {"label": "VİOP %s kapanış" % t, "kind": "px", "group": "VİOP"}
    eng = {"dibs": [{"isin": ISIN, "type": "S", "row": 5, "name": "", "maturity": "2029-03-15", "coupon": 30.0, "freq": 2.0,
                     "simple": 0.35, "compound": 0.38, "source": ""}]}
    for key, (values, m) in (extra or {}).items():
        series[key], meta[key] = values, m
    ctx = qf.Ctx(cfg(**kw), today, series, meta, live or {}, mpc=mpc if mpc is not None else mpc_of(DAYS[-60:] + [today.isoformat()]))
    return ctx, eng


@pytest.fixture(scope="module")
def reg():
    ctx, eng = uni_ctx()
    return qu.Registry(ctx, None, eng)


# ================================================================================================ the instruments
def test_every_planned_instrument_is_in_the_registry_with_its_group_priority_and_unit(reg):
    keys = [i.key for i in reg]
    assert not reg.missing, reg.missing
    g10 = ["FX:" + p for p in qu.G10_PAIRS]
    vols = [qopt.key(p, k, t) for p in qu.G10_PAIRS for k, t in qu.G10_VOLS]
    assert [i.key for i in reg.tradeable("G10 spot")] == g10 and [i.key for i in reg.tradeable("G10 opsiyon")] == vols
    assert len(vols) == 35 and "FXV:EURUSD" in vols and "OPT:NZDUSD:BF25:3M" in vols and "OPT:USDJPY:RR25:1M" in vols
    ois = reg.tradeable("TRY OIS")
    short = [i.key for i in ois if i.tier == qu.SHORT]
    long_ = [i.key for i in ois if i.tier == qu.LONG]
    assert short == (["OIS:" + t for t in ("1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y")]
                     + ["OISS:%s/%s" % s for s in qu.SPREADS[:10]] + ["OISF:%s/%s/%s" % f for f in qu.FLIES[:8]]
                     + ["FRA:%dx%d" % f for f in qu.FRAS] + ["PPK:1", "PPK:2", "PPK:3"])
    assert long_ == ["OIS:3Y", "OIS:5Y", "OIS:10Y"] + ["OISS:%s/%s" % s for s in qu.SPREADS[10:]] + ["OISF:%s/%s/%s" % f for f in qu.FLIES[8:]]
    assert len(short) == 8 + 10 + 8 + 6 + 3 and len(long_) == 3 + 4 + 3
    assert [i.key for i in reg.tradeable("DİBS")] == ["DIBS:" + ISIN]
    assert [i.key for i in reg.tradeable("VİOP")] == ["VIOP:" + t for t in CONTRACTS]
    assert [i.key for i in reg.tradeable("Offshore")] == (["FWD:USDTRY:1M", "FWD:USDTRY:3M", "FWD:USDTRY:6M", "FWD:USDTRY:1Y", "FWD:EURTRY:3M",
                                                           "FXP:USDTRY:1M", "FXP:USDTRY:3M", "FXP:USDTRY:6M", "FXP:USDTRY:1Y", "FXP:EURTRY:3M",
                                                           "OFF:1M", "OFF:3M", "OFF:1Y"])
    # the list's order: the groups' priorities never go back, TRY OIS's short end before its long end
    pr = [i.priority for i in reg]
    assert pr == sorted(pr) and pr[0] == 1 and pr[-1] == 7
    assert {i.group for i in reg} == set(qu.GROUPS[:-1]) and qu.priority("TRY OIS", qu.SHORT) < qu.priority("TRY OIS", qu.LONG) < qu.priority("DİBS")
    # the inputs: read, never traded - nor walked with the lines
    ins = {i.key for i in reg.inputs()}
    assert {"UST:2Y", "UST:10Y", "DXY", "BRENT", "CDS", "TLREF", "OIS:15M", "OIS:21M", "OIS:4Y", "OIS:9Y"} <= ins and not ins & set(keys)
    assert all(not i.tradeable for i in reg.inputs()) and "OIS:15M" in reg and reg["OIS:15M"].group == "Girdi"
    # units, sizes, verbs, money currency - the desk's words
    e = reg["FX:EURUSD"]
    assert (e.label, e.unit, e.kind, e.size_text(), e.ccy, e.verbs, e.digits) == ("EURUSD spot", "", "fx", "1 mn EUR", "USD", ("AL", "SAT"), 5)
    assert reg["FX:USDJPY"].size_text() == "1 mn USD" and reg["FX:USDJPY"].digits == 3
    v = reg["OPT:EURUSD:ATM:1M"]
    assert (v.label, v.unit, v.size_text(), v.ccy, v.verbs) == ("EURUSD ATM 1A vol", "vol", "10.000 $ vega", "USD", ("vol al", "vol sat"))
    assert reg["FXR:GBPUSD"].label == "GBPUSD 25D RR 3A" and reg["FXR:GBPUSD"].verbs == ("RR al", "RR sat")
    assert reg["OPT:AUDUSD:BF25:3M"].label == "AUDUSD 25D BF 3A" and reg["OPT:AUDUSD:BF25:3M"].verbs == ("BF al", "BF sat")
    o = reg["OIS:2Y"]
    assert (o.label, o.unit, o.size_text(), o.ccy, o.verbs, o.group, o.tier) == ("2Y OIS", "%", "1.000 $ DV01", "TL", ("pay", "receive"), "TRY OIS", "≤ 2Y")
    assert reg["OISS:1Y/2Y"].verbs == ("steepener", "flattener") and reg["OISS:1Y/2Y"].unit == "bp"
    assert reg["OISF:6M/1Y/2Y"].verbs == ("gövde pay / kanatlar receive", "gövde receive / kanatlar pay")
    assert reg["FRA:3x6"].label == "3×6 FRA" and reg["PPK:1"].label == "PPK 1. dönem (10.12.26–21.01.27)"
    d = reg["DIBS:" + ISIN]
    assert d.label == "DİBS 15.03.29" and d.verbs == ("SAT", "AL") and d.ccy == "TL" and d.size_text().startswith("1.000 $ DV01 · ")
    assert d.size_text().endswith(" mn TL nominal")
    vi = reg["VIOP:A1Z6 Curncy"]
    assert vi.label == "VİOP Ara26" and vi.verbs == ("AL", "SAT") and vi.group == "VİOP" and " kontrat" in vi.size_text()
    f = reg["FWD:USDTRY:1M"]
    assert (f.label, f.size_text(), f.ccy, f.tag) == ("USDTRY 1A forward", "1 mn USD", "TRY", "offshore limiti")
    assert reg["FXP:USDTRY:3M"].label == "USDTRY 3A swap puanı" and reg["FXP:USDTRY:3M"].verbs == ("pay", "receive")
    assert reg["OFF:3M"].label == "Offshore 3M" and all(i.tag == "offshore limiti" for i in reg.tradeable("Offshore"))
    assert not any(i.tag for i in reg if i.group != "Offshore")
    assert reg["OIS:2Y"].line(-1, 0.7) == "receive 2Y OIS · 700 $ DV01" and f.line(1) == "AL USDTRY 1A forward · 1 mn USD · offshore limiti"
    # every line has its closes, a live level and a daily σ (none for a planted spread / fly that never moves)
    for i in reg:
        assert len(i.pts()) >= 40 and i.now() is not None, i.key
        assert i.vol() is not None or max(abs(c) for c in i.changes()) < 1e-9, i.key


def test_spreads_flies_and_fras_from_the_right_tenors_and_signs(reg):
    sp, fl = reg["OISS:1Y/2Y"], reg["OISF:6M/1Y/2Y"]
    # the planted constants: 1Y/2Y = 2Y − 1Y, 6M/1Y/2Y = 1Y − ½ (6M + 2Y), in bp, every day (the common move cancels)
    assert all(abs(v - (planted("2Y") - planted("1Y")) * 100.0) < 1e-9 for v in sp.values)
    assert all(abs(v - (planted("1Y") - 0.5 * (planted("6M") + planted("2Y"))) * 100.0) < 1e-9 for v in fl.values)
    assert reg["OISS:5Y/10Y"].values[-1] == pytest.approx((planted("10Y") - planted("5Y")) * 100.0)
    assert reg["OISF:2Y/5Y/10Y"].values[-1] == pytest.approx((planted("5Y") - 0.5 * (planted("2Y") + planted("10Y"))) * 100.0)
    # the signs: the long end 10 bp up steepens the spread (the up side: steepener) and drops the fly by 5 bp
    last = {k: reg.ctx.last(k) for k in reg.ctx.meta if k.startswith("OIS:")}
    live = dict(last, **{"OIS:2Y": last["OIS:2Y"] + 0.10})
    assert sp.now(live) - sp.last() == pytest.approx(10.0) and fl.now(live) - fl.last() == pytest.approx(-5.0)
    assert sp.verb(1) == "steepener" and sp.money(10.0) == pytest.approx(10.0 * 1000.0 * reg.ctx.usdtry())
    # the trade: steepener pays the long leg, receives the short one (DV01 1:1); the fly's body against ½ each wing
    m = sp.monitor("t:sp", "trend", zfn=lambda lv, lv2: 2.5, mode="drift", follows=True, reward=2.0, risk=2.0)
    qf.score_all(reg.ctx, [m], {})
    sg = qf.make_signal(m, cfg(), "10:00")
    assert sg["expression"] == "Steepener 1Y/2Y spread" and [(l["key"], l["action"], l["weight"]) for l in sg["legs"]] == [
        ("OIS:2Y", "Pay", 1.0), ("OIS:1Y", "Receive", 1.0)]
    assert sg["legs"][0]["dv01_usd"] == 1000.0 and sg["legs"][0]["notional"] > 0
    assert {l["key"]: l["weight"] for l in fl.legs()} == {"OIS:1Y": 1.0, "OIS:6M": -0.5, "OIS:2Y": -0.5}
    # FRA: a flat curve's 3×6 … 15×18 are its rate to the bp (one quarter each), 18×24 compounds two quarters
    hol = set()
    day = TODAY
    flat = {m: 40.0 for m in (1, 2, 3, 6, 9, 12, 15, 18, 21, 24)}
    out = reg._fra_curve(day, flat)
    for name in ("FRA:3x6", "FRA:6x9", "FRA:9x12", "FRA:12x15", "FRA:15x18"):
        assert out[name] == pytest.approx(40.0, abs=1e-9), name
    spot = qf.business_on_or_after(day + dt.timedelta(days=1), hol)
    q = [qf.tenor_end(spot, m, hol) for m in (18, 21, 24)]
    t1, t2 = (q[1] - q[0]).days / 365.0, (q[2] - q[1]).days / 365.0
    assert out["FRA:18x24"] == pytest.approx(((1 + 0.4 * t1) * (1 + 0.4 * t2) - 1) / (t1 + t2) * 100.0)
    # ... and every day's FRAs are the FRA family's bootstrap (quantfam.curve_dfs), also without a quarter's quote
    d = DAYS[-7]
    quotes = {int(MONTHS[k[4:]]): reg.ctx.series[k][d] for k in reg.ctx.series if k.startswith("OIS:") and MONTHS[k[4:]] >= 1
              and float(MONTHS[k[4:]]).is_integer() and MONTHS[k[4:]] <= 24}
    spot = qf.business_on_or_after(dt.date.fromisoformat(d) + dt.timedelta(days=1), hol)
    dfs = qf.curve_dfs(spot, quotes, hol)
    for m1, m2 in qu.FRAS:
        a, b = qf.tenor_end(spot, m1, hol), qf.tenor_end(spot, m2, hol)
        ref = (qf.curve_df(spot, [], a, dfs) / qf.curve_df(spot, [], b, dfs) - 1.0) * 365.0 / (b - a).days * 100.0
        assert reg.fra_history()["FRA:%dx%d" % (m1, m2)][d] == pytest.approx(ref, abs=1e-9)
    gap = reg._fra_curve(dt.date.fromisoformat(d), {k: v for k, v in quotes.items() if k != 15})
    assert abs(gap["FRA:12x15"] - reg.fra_history()["FRA:12x15"][d]) < 5.0              # (curve_dfs between the quotes)
    # the far tenor up raises the FRA ending there, not the ones before it; its legs pay the far tenor, receive the near
    fr = reg["FRA:18x24"]
    up = reg.fra_now(dict(last, **{"OIS:2Y": last["OIS:2Y"] + 0.10}))
    base = reg.fra_now(last)
    assert (up["FRA:18x24"] - base["FRA:18x24"]) * 100.0 > 20.0 and up["FRA:3x6"] == pytest.approx(base["FRA:3x6"])
    legs = {l["key"]: l["weight"] for l in fr.legs()}
    assert set(legs) == {"OIS:2Y", "OIS:18M"} and legs["OIS:2Y"] > 1.0 and legs["OIS:18M"] < 0 and sum(legs.values()) == pytest.approx(1.0)


def test_the_ppk_period_series_rolls_on_a_meeting(reg):
    p1, p2 = reg["PPK:1"], reg["PPK:2"]
    s1 = dict(p1.pts())
    # before the first meeting the 1st period is the one after it; on the meeting day (its spot past it) the next one's
    before = DAYS[DAYS.index(PAST[0]) - 1]
    assert s1[before] == pytest.approx(_level(PAST[0]) * 100.0) and s1[PAST[0]] == pytest.approx(_level(PAST[1]) * 100.0)
    assert s1[PAST[1]] == pytest.approx(_level(AHEAD[0]) * 100.0) and dict(p2.pts())[PAST[1]] == pytest.approx(_level(AHEAD[1]) * 100.0)
    assert p1.rolls() == {PAST[0], PAST[1]} and p2.rolls() == {PAST[0], PAST[1]}
    # the roll is no move of the market: the series is flat between meetings, its daily changes are all 0
    assert len(p1.changes()) == len(p1.pts()) - 1 - 2 and all(abs(c) < 1e-9 for c in p1.changes())
    # today: today's path - the period after the next meeting, its leg the meeting-dated OIS of that period, carry 0
    assert p1.now() == pytest.approx(_level(AHEAD[0]) * 100.0) and p1.meeting() == (AHEAD[0], AHEAD[1])
    leg = p1.legs()[0]
    assert leg["key"] == "MPC:" + AHEAD[0] and leg["name"] == "PPK 10.12.26–21.01.27 dönemi" and leg["dv01_usd"] == 1000.0 and leg["notional"] > 0
    assert p1.carry_week() == 0.0 and reg["PPK:3"].meeting() == (AHEAD[2], None) and reg["PPK:3"].label == "PPK 3. dönem (04.03.27 sonrası)"


def test_sizes_and_money(reg):
    tl = 1000.0 * reg.ctx.usdtry()                                       # (the context's USDTRY: its last close)
    e, j = reg["FX:EURUSD"], reg["FX:USDJPY"]
    s, sj = e.now(), j.now()
    assert e.money(1.0) == pytest.approx(1e6 * s * (math.exp(0.01) - 1.0))              # 1 mn EUR, a 1 % move, in USD
    assert j.money(1.0) == pytest.approx(1e6 * sj * (math.exp(0.01) - 1.0) / sj)        # 1 mn USD of USDJPY: the yen in USD
    assert e.money(-1.0, k=1.4) == pytest.approx(-1.4 * 1e6 * s * (1.0 - math.exp(-0.01)))
    assert e.size_text(1.4) == "1,4 mn EUR" and e.size_text(0.7) == "700 bin EUR"
    v = reg["FXV:EURUSD"]
    assert v.money(1.5) == pytest.approx(15000.0) and v.size_text(1.4) == "14.000 $ vega"
    assert reg["OIS:2Y"].money(3.0) == pytest.approx(3.0 * tl) and reg["OIS:2Y"].size_text(0.7) == "700 $ DV01"
    assert reg["OISF:6M/1Y/2Y"].money(2.0) == pytest.approx(2.0 * tl) and reg["FRA:6x9"].money(1.0) == pytest.approx(tl)
    d = reg["DIBS:" + ISIN]
    assert d.per_cu == pytest.approx(1.0) and d.money(1.0) == pytest.approx(tl)        # (the sheet's simple yield: its own DV01)
    nom = d.nominal()
    from tto import quantcurve as qc
    bond = qc.Bond(ISIN, "", "fixed", dt.date(2029, 3, 15), 30.0, 2)
    value = qc.next_weekday(TODAY)
    p, _ = bond.price(d.now() / 100.0, value, "simple")
    assert nom == pytest.approx(tl / qc.desk_dv01(bond, value, p)) and d.legs()[0]["notional"] == pytest.approx(nom)
    f = reg["FWD:USDTRY:1M"]
    assert f.money(1.0) == pytest.approx(1e6 * f.now() * (math.exp(0.01) - 1.0))       # TRY, 1 mn USD
    assert f.carry_week() < 0                                                           # (a long forward's points roll down)
    pts = reg["FXP:USDTRY:3M"]
    assert pts.money(100.0) == pytest.approx(10000.0) and pts.carry_week() < 0          # 100 points = 0,01 TRY a USD of 1 mn
    vi = reg["VIOP:A1Z6 Curncy"]
    assert vi.now() == pytest.approx(40.0, abs=0.02) and vi.money(1.0) == pytest.approx(tl)   # (priced at 40 % against USD ~4 %)
    legs = vi.legs()
    assert legs[0]["key"] == "VQM:A1Z6 Curncy" and legs[1]["key"] == "FX:USDTRY" and legs[0]["dv01_usd"] == 1000.0
    # the card: an option line's money in USD (10.000 $ vega a vol point), a rates line's in TL, a G10 spot's per 1 mn EUR
    m = v.monitor("t:v", "trend", zfn=lambda lv, live: -2.5, mode="drift", follows=True, reward=1.0, risk=0.5, fcast=-0.6, hold=10.0)
    qf.score_all(reg.ctx, [m], {})
    sg = qf.make_signal(m, cfg(), "10:00")
    assert sg["expression"] == "Sell EURUSD ATM 3A vol" and sg["money"]["ccy"] == "USD" and sg["money"]["total"] == pytest.approx(6000.0)
    assert sg["money"]["target"] == pytest.approx(10000.0) and sg["money"]["stop"] == pytest.approx(-5000.0)
    assert "≈ +6,0 bin USD (10.000 $ vega)" in sg["plain"] and "Hedefte ~10 bin USD kâr, stopta ~5,0 bin USD zarar." in sg["plain"]
    assert sg["pnl_try"] == pytest.approx(6000.0 * 42.0) and qf.exp_text(sg) == "+0,60 vol ≈ +6,0 bin USD"
    m = e.monitor("t:e", "trend", zfn=lambda lv, live: 2.5, mode="drift", follows=True, reward=0.01, risk=0.01, fcast=0.005, hold=10.0)
    qf.score_all(reg.ctx, [m], {})
    sg = qf.make_signal(m, cfg(), "10:00")
    assert sg["px"]["inst"] == "EURUSD spot" and sg["money"]["ccy"] == "USD" and sg["money"]["base"] == "EUR" and sg["trade_tr"] == "EURUSD spot al"
    assert sg["plain"].startswith("Şimdi spot EURUSD alıp ~10 iş günü tutarsan")
    assert sg["money"]["total"] == pytest.approx(1e6 * 0.005, rel=0.02)
    # a line sized by the family (k of the desk's unit: Trend's risk-equal sizes): its legs and its card's money at k
    for key, k in (("OIS:2Y", 0.7), ("OISS:1Y/2Y", 0.7), ("FRA:6x9", 0.7), ("DIBS:" + ISIN, 0.7), ("PPK:1", 0.7), ("OFF:3M", 0.7)):
        inst = reg[key]
        m = inst.monitor("t:k:" + key, "trend", k=k, zfn=lambda lv, live: 2.5, mode="drift", follows=True, reward=0.05, risk=0.05, fcast=0.02, hold=5.0)
        qf.score_all(reg.ctx, [m], {})
        sg = qf.make_signal(m, cfg(), "10:00")
        assert sg["legs"][0]["dv01_usd"] == pytest.approx(700.0 * abs(inst.legs()[0]["weight"]), rel=1e-9), key
        assert sg["money"]["per_bp"] == pytest.approx(0.7 * tl) and sg["money"]["dv01_usd"] == pytest.approx(700.0), key
        assert sg["info"]["size"].startswith("700 $ DV01") and "Ana bacak 700 $ DV01" in sg["plain"], key
    assert reg["DIBS:" + ISIN].legs(None, 0.7)[0]["notional"] == pytest.approx(0.7 * nom)
    m = v.monitor("t:k:v", "trend", k=1.4, zfn=lambda lv, live: -2.5, mode="drift", follows=True, reward=1.0, risk=0.5, fcast=-0.6, hold=10.0)
    qf.score_all(reg.ctx, [m], {})
    sg = qf.make_signal(m, cfg(), "10:00")
    assert sg["money"]["total"] == pytest.approx(1.4 * 6000.0) and "(14.000 $ vega)" in sg["plain"]


# ================================================================================================ rows that move
def test_the_ppk_periods_follow_the_meetings_by_date_through_a_calendar_edit():
    """OIS_MAIN's meeting rows move when the calendar is edited (a meeting added, a date corrected): the history's days
    before the edit keep the old list until it computes them again (or for good, outside its window).  Each day's k-th
    period is its own k-th meeting by date, the day it changes is a roll - no other meeting's level runs on as a
    market move -, the rows of a day in any order."""
    days = DAYS[-30:] + [TODAY.isoformat()]
    edit = DAYS[-12]
    old = ["2026-12-10", "2027-01-21", "2027-03-04"]
    new = ["2026-12-10", "2026-12-31", "2027-01-22", "2027-03-04"]         # 31.12 added, 21.01 corrected to 22.01
    base = {"2026-12-10": 0.39, "2026-12-31": 0.385, "2027-01-21": 0.38, "2027-01-22": 0.38, "2027-03-04": 0.37}
    mpc = {"days": {}, "values": []}
    for i, d in enumerate(days):
        spot = qf.business_on_or_after(dt.date.fromisoformat(d) + dt.timedelta(days=1), set()).isoformat()
        mpc["days"][d] = {"spot": spot, "base": 0.42, "status": "OK"}
        for m in reversed(old if d < edit else new):                          # (a day's rows in any order)
            mpc["values"].append({"day": d, "meeting": m, "level": base[m] + 0.0001 * i})     # the market: +1 bp a day
    ctx, eng = uni_ctx(mpc=mpc)
    reg = qu.Registry(ctx, None, eng)
    p1, p2, p3 = reg["PPK:1"], reg["PPK:2"], reg["PPK:3"]
    for k, inst in ((1, p1), (2, p2), (3, p3)):
        own = dict(inst.pts())
        for i, d in enumerate(days[:-1]):
            m = (old if d < edit else new)[k - 1]
            assert own[d] == pytest.approx((base[m] + 0.0001 * i) * 100.0), (k, d)      # that day's k-th meeting, by date
    assert p1.rolls() == set() and p2.rolls() == {edit} and p3.rolls() == {edit}
    # the edit's jump (2nd: 21.01 → 31.12, +50 bp; 3rd: 04.03 → 22.01, +100 bp) is no move: every move is the market's 1 bp
    for inst in (p1, p2, p3):
        assert all(c == pytest.approx(1.0) for c in inst.changes()) and len(inst.changes()) == len(inst.pts()) - 1 - len(inst.rolls())
        adj = inst.adjusted()                     # (a roll day's own move cannot be told from its jump: 0 that day)
        assert all(b - a == pytest.approx(0.0 if d in inst.rolls() else 0.01) for (_, a), (d, b) in zip(adj, adj[1:]))
        assert adj[-1] == inst.pts()[-1] and [d for d, _ in adj] == inst.days
    # today: the edited calendar's periods, their legs the meeting-dated OIS of those dates
    assert p2.meeting() == ("2026-12-31", "2027-01-22") and p2.label == "PPK 2. dönem (31.12.26–22.01.27)"
    assert p2.legs()[0]["key"] == "MPC:2026-12-31" and p3.legs()[0]["key"] == "MPC:2027-01-22"
    assert p2.now() == pytest.approx((base["2026-12-31"] + 0.0001 * (len(days) - 1)) * 100.0)


def test_viop_and_dibs_lines_are_their_ticker_and_isin_whatever_the_sheets_order():
    """A VİOP contract by its ticker, a bond by its ISIN - not by the VİOP sheet's column or the DİBS RV row: the
    sheet's columns shifting at a roll, a bond added above the others, a bond maturing - no line takes another's
    history, its live value or its size."""
    new_isin = "TRT100128T10"
    extra = {"DIBS:" + new_isin: ({d: 34.0 + 0.2 * math.cos(i / 9.0) for i, d in enumerate(DAYS)},
                                  {"label": new_isin, "kind": "rate", "group": "dibs", "unit": "pct", "maturity": "2028-01-10", "type": "S", "name": ""}),
             "DIBS:TRT201126T11": ({d: 33.0 for d in DAYS},                     # (matures within 30 days: no line)
                                   {"label": "TRT201126T11", "kind": "rate", "group": "dibs", "unit": "pct", "maturity": "2026-11-20", "type": "S", "name": ""})}
    live = {"VQM:A1Z6 Curncy": 41.0, "VQM:A1H7 Curncy": 42.5, "VQM:A1M7 Curncy": 43.0}
    ctx1, eng1 = uni_ctx(live=live)
    eng1["viopq"] = [{"ticker": "A1Z6 Curncy", "n": 1}, {"ticker": "A1H7 Curncy", "n": 2}]
    ctx2, eng2 = uni_ctx(live=live, extra=extra)
    # the VİOP sheet after a roll: its first column the March contract, a new June one beside it; the DİBS RV list with a
    # new bond on top (every row below it one down) and a short one
    eng2["viopq"] = [{"ticker": "A1H7 Curncy", "n": 1}, {"ticker": "A1M7 Curncy", "n": 2}]
    eng2["dibs"] = ([{"isin": new_isin, "type": "S", "row": 5, "name": "", "maturity": "2028-01-10", "coupon": 25.0, "freq": 2.0,
                      "simple": 0.34, "compound": 0.37, "source": ""}]
                    + [dict(r, row=6) for r in eng1["dibs"]]
                    + [{"isin": "TRT201126T11", "type": "S", "row": 7, "name": "", "maturity": "2026-11-20", "coupon": 20.0, "freq": 2.0,
                        "simple": 0.33, "compound": 0.35, "source": ""}])
    r1, r2 = qu.Registry(ctx1, None, eng1), qu.Registry(ctx2, None, eng2)
    assert [i.key for i in r1.tradeable("VİOP")] == ["VIOP:A1Z6 Curncy", "VIOP:A1H7 Curncy"]
    assert [i.key for i in r2.tradeable("VİOP")] == ["VIOP:A1Z6 Curncy", "VIOP:A1H7 Curncy", "VIOP:A1M7 Curncy"]
    for key in ("VIOP:A1Z6 Curncy", "VIOP:A1H7 Curncy"):
        a, b = r1[key], r2[key]
        assert a.label == b.label and a.pts() == b.pts() and a.now() == b.now() == live["VQM:" + key[5:]], key
        assert a.legs()[0]["key"] == b.legs()[0]["key"] == "VQM:" + key[5:]
    assert r2["VIOP:A1M7 Curncy"].label == "VİOP Haz27" and r2["VIOP:A1M7 Curncy"].now() == 43.0
    assert [i.key for i in r1.tradeable("DİBS")] == ["DIBS:" + ISIN] and [i.key for i in r2.tradeable("DİBS")] == ["DIBS:" + new_isin, "DIBS:" + ISIN]
    a, b = r1["DIBS:" + ISIN], r2["DIBS:" + ISIN]
    assert (a.label, a.pts(), a.now(), a.nominal(), a.size_text()) == (b.label, b.pts(), b.now(), b.nominal(), b.size_text())
    assert r2["DIBS:" + new_isin].label == "DİBS 10.01.28" and r2["DIBS:" + new_isin].values[-1] != a.values[-1]
    assert "DIBS:TRT201126T11" not in r2                                     # (inside 30 days of its maturity: no line)


# ================================================================================================ the list
def _sg(sid, asset, legs, z=3.0, composite=None, gated="", fam="pca", **kw):
    out = {"id": sid, "family": fam, "asset": asset, "legs": [{"key": k, "side": 1} for k in legs], "z": z, "agree": 0,
           "composite": 0.0 if gated else (abs(z) if composite is None else composite), "gated": gated, "info": {}, "packages": []}
    out.update(kw)
    return out


def test_the_list_is_ordered_by_group_then_strength_and_offshore_says_its_limit():
    live = [_sg("ois-2s10s", "TRY OIS", ["OIS:2Y", "OIS:10Y"], composite=3.5), _sg("ois-6m", "TRY OIS", ["OIS:6M"], composite=2.1),
            _sg("ois-2y-pca", "TRY OIS", ["OIS:2Y", "OIS:18M", "OIS:3Y"], composite=2.0, packages=[{"name": "Paket"}]),
            _sg("eurusd", "FX", ["FX:EURUSD"], composite=2.2, px={"pair": "EURUSD"}), _sg("eurusd-vol", "FX vol", ["FXV:EURUSD"], composite=2.6),
            _sg("usdtry-fwd", "FX", ["FX:USDTRY"], composite=3.9, px={"pair": "USDTRY"}), _sg("usdzar", "FX", ["FX:USDZAR"], composite=2.4),
            _sg("dibs", "DİBS", ["DIBS:" + ISIN], composite=2.3), _sg("viop", "VİOP", ["VQM:A1Z6 Curncy"], composite=2.05),
            _sg("off", "Offshore", ["OFF:3M", "OIS:3M"], composite=2.15), _sg("ust", "Global", ["UST:10Y"], composite=3.0),
            _sg("ppk", "TRY OIS", ["MPC:2026-12-10"], composite=2.5)]
    gated = [_sg("ois-1y-low", "TRY OIS", ["OIS:1Y"], z=4.2, gated="rejim trend"), _sg("eurusd-low", "FX", ["FX:EURUSD"], z=2.1, gated="carry"),
             _sg("off-low", "Offshore", ["OFF:1Y", "OIS:1Y"], z=5.0, gated="yarı ömür")]
    out = qu.order(live, gated)
    assert [s["id"] for s in out] == ["eurusd", "eurusd-low",                   # G10 spot: the confident, then "düşük güven"
                                      "eurusd-vol",                              # G10 opsiyon
                                      "ppk", "ois-6m", "ois-2y-pca", "ois-1y-low",     # TRY OIS ≤ 2Y (a hedged 2Y: its main leg)
                                      "ois-2s10s",                               # ... the long end after it, however strong
                                      "dibs", "viop",
                                      "usdtry-fwd", "off", "off-low",            # Offshore: USDTRY's forwards too
                                      "ust", "usdzar"]                           # Diğer
    by = {s["id"]: s for s in out}
    assert by["ois-2s10s"]["tier"] == "uzun" and by["ois-6m"]["tier"] == "≤ 2Y" and by["eurusd"]["tier"] is None
    assert [by[k]["tag"] for k in ("usdtry-fwd", "off", "off-low")] == ["offshore limiti"] * 3 and not by["eurusd"]["tag"]
    assert by["eurusd-vol"]["group"] == "G10 opsiyon" and by["usdzar"]["group"] == "Diğer" and by["ust"]["priority"] == 8
    counts = {g["id"]: (g["n"], g["live"]) for g in qu.group_counts(out)}
    assert counts == {"G10 spot": (2, 1), "G10 opsiyon": (1, 1), "TRY OIS": (5, 4), "DİBS": (1, 1), "VİOP": (1, 1), "Offshore": (3, 2), "Diğer": (2, 2)}
    assert [g["id"] for g in qu.group_counts(out)] == list(qu.GROUPS) and qu.GROUPS[:6] == ("G10 spot", "G10 opsiyon", "TRY OIS", "DİBS", "VİOP", "Offshore")
    # a line of the universe's families is placed by its instrument
    s = qu.classify(_sg("x", "FX", ["FX:USDTRY"], info={"group": "TRY OIS", "tier": "uzun"}))
    assert (s["group"], s["tier"], s["priority"]) == ("TRY OIS", "uzun", 4)


# ================================================================================================ the history
def test_the_g10_series_are_kept_whatever_the_pair_list_and_filled_last():
    specs = qq.series_specs()
    keys = [s["key"] for s in specs]
    tickers = [(s["ticker"], s.get("field", "PX_LAST")) for s in specs]
    assert len(tickers) == len(set(tickers)) and len(keys) == len(set(keys))           # no series asked twice
    mine = qu.series_specs()
    assert len(mine) == 7 + 7 + 35 and {s["ticker"] for s in mine} >= {"NZDUSD Curncy", "NZD3M Curncy", "JPY3M Curncy", "NZDUSDV1M BGN Curncy",
                                                                       "USDJPY25R1M BGN Curncy", "GBPUSD25B3M BGN Curncy", "EURUSDV3M BGN Curncy",
                                                                       "USDCHF25R3M BGN Curncy", "AUDUSDV3M BGN Curncy"}
    assert qu.series_specs("CMPN")[-1]["ticker"] == "NZDUSD25B3M CMPN Curncy"         # (the FX pages' pricing source)
    # the default list keeps six of the seven pairs and EURUSD's options already: the universe adds what it lacks
    new = [s for s in specs if s.get("universe")]
    assert [s["key"] for s in new] == (["FX:NZDUSD", "FXP:NZDUSD:3M"] + ["OPT:%s:ATM:1M" % p for p in qu.G10_PAIRS if p != "EURUSD"] + ["FXV:NZDUSD"]
                                       + ["OPT:%s:RR25:1M" % p for p in qu.G10_PAIRS if p != "EURUSD"] + ["FXR:NZDUSD"]
                                       + ["OPT:%s:BF25:3M" % p for p in qu.G10_PAIRS if p != "EURUSD"])
    assert len(new) == 22 and all(s["group"] == "G10" for s in new)
    # in the history: the universe's own last, in their order (the spots, the points, then the vols tenor by tenor);
    # two years once, new days every sync - as the package's other series
    defs = [d for d in qq.history_defs() if d.group == "Quant"]
    order = [d.info["key"] for d in defs]
    assert order[-len(new):] == [s["key"] for s in new] and all(d.info["backfill"] is True and "tail" not in d.info for d in defs[-len(new):])
    assert all(d.info["lookback"] == qq.HISTORY_DAYS for d in defs[-len(new):])
    # a list without the G10 pairs: the universe keeps all seven - its spots, points, ATM / RR 3M too
    few = {s["key"]: s for s in qq.series_specs(pairs=["USDTRY", "USDZAR"])}
    assert all(("FX:" + p) in few and few["FX:" + p].get("universe") for p in qu.G10_PAIRS)
    assert few["FXV:EURUSD"]["ticker"] == "EURUSDV3M BGN Curncy" and few["FXV:EURUSD"].get("universe") and "FX:USDZAR" in few
    assert sum(1 for s in few.values() if s.get("universe")) == 7 + 7 + 35 - 4      # (EURUSD's 1M ATM / RR, 3M BF, 3M points: the Opsiyon page's)
    # the FX analyses keep to the desk's list: a pair only the universe keeps is not theirs
    ctx, _ = uni_ctx()
    assert "NZDUSD" not in ctx.fx_pairs() and "EURUSD" in ctx.fx_pairs() and "FX:NZDUSD" in qu.Registry(ctx)


# ================================================================================================ the hook, the service
@pytest.fixture(scope="module")
def seeded(module_service):
    svc = module_service
    svc.quant.use_live = False
    days, _ = quant_synth.seed(svc)
    # (EURUSD's 3M points too: a G10 line's carry is its forward's)
    d = next(x for x in svc.history.snapshot()["defs"] if x.group == "Quant" and x.info.get("key") == "FXP:EURUSD:3M")
    svc.store.hist_upsert(d.id, [(day, 35.0) for day in days])
    svc.history.rev += 1
    return svc


#: the plugged test family's scores, by instrument (what a family reads its own way)
PLUG = {"z": 0.5}
PICKS = ("FX:EURUSD", "OIS:2Y", "OISS:2Y/5Y", "FWD:USDTRY:3M")


def _plugged(ctx, reg, cfg_):
    """A family on the universe as the three will be: a line per instrument, its own score and decision."""
    mons = []
    for key in PICKS:
        inst = reg.get(key)
        if inst is None or len(inst.pts()) < 40:
            continue
        sd = inst.vol() or 1.0
        lvl = inst.now() or 1.0
        unit_move = sd / 100.0 if inst.kind == "rate" else (sd / 100.0 * lvl if inst.kind == "fx" else sd)     # (a σ in level units)
        bad = key == "OIS:2Y"                                       # (this one expects a loss: "beklenen kâr yok" - düşük güven)
        mons.append(inst.monitor("trend:" + key, "trend", zfn=lambda lv, live: PLUG["z"], mode="drift", follows=True, reward=4 * unit_move,
                                 risk=2 * unit_move, fcast=-unit_move if bad else 3 * unit_move, hold=10.0))
    return mons, {"ok": True, "n": len(mons)}


@pytest.fixture()
def plugged():
    qu.RUNNERS["trend"] = _plugged
    try:
        yield
    finally:
        qu.RUNNERS.pop("trend", None)


def test_a_plugged_family_lists_by_group_keeps_its_low_confidence_lines_and_alerts_only_the_confident(seeded, plugged):
    svc = seeded
    q = svc.quant
    user = svc.login("evren okuyucu")["user"]
    q.set_subscription(user, {"on": True, "families": ["trend"], "groups": ["Offshore", "G10 spot"], "min": "Zayıf"})
    PLUG["z"] = 0.5
    q.compute()                                                         # (below the threshold: nothing yet)
    PLUG["z"] = 3.0
    st = q.compute()                                                    # ... crossed: a signal, logged and alerted
    assert st["ready"] and "trend" in st["timing"] and not st["errors"].get("trend")
    v = q.view("signals", user, {})
    sigs = v["signals"]
    pri = [s["priority"] for s in sigs]
    assert pri == sorted(pri) and all(s["group"] in qu.GROUPS for s in sigs)
    for p in set(pri):                                                   # in each group (TRY OIS: each end) the confident lines by
        flags = [bool(s["gated"]) for s in sigs if s["priority"] == p]   # their strength, then the "düşük güven" ones
        assert flags == sorted(flags), p
        conf = [s["composite"] for s in sigs if s["priority"] == p and not s["gated"]]
        assert conf == sorted(conf, reverse=True), p
    mine = {s["id"]: s for s in sigs if s["family"] == "trend"}
    assert set(mine) == {"trend:" + k for k in PICKS}
    assert mine["trend:FX:EURUSD"]["group"] == "G10 spot" and mine["trend:OIS:2Y"]["tier"] == "≤ 2Y" and mine["trend:OISS:2Y/5Y"]["tier"] == "uzun"
    off = mine["trend:FWD:USDTRY:3M"]
    assert off["group"] == "Offshore" and off["tag"] == "offshore limiti" and off["family_label"] == "Trend"
    low = mine["trend:OIS:2Y"]
    assert low["gated"].startswith("beklenen kâr yok") and low["strength"] == "elendi" and low["id"] in {s["id"] for s in v["gated"]}
    assert {s["id"] for s in sigs} >= {s["id"] for s in v["gated"]}                   # (every gated line is in the list)
    # the group buttons: every group, its lines and its confident ones; one group alone
    groups = {g["id"]: g for g in v["groups"]}
    assert list(groups) == list(qu.GROUPS) and sum(g["n"] for g in v["groups"]) == len(sigs)
    assert groups["Offshore"]["tag"] == "offshore limiti" and groups["TRY OIS"]["n"] > groups["TRY OIS"]["live"]
    only = q.view("signals", user, {"group": "TRY OIS"})["signals"]
    assert only and all(s["group"] == "TRY OIS" for s in only) and "trend:OIS:2Y" in {s["id"] for s in only}
    box = q.view("box", user, {"of": "signals", "group": "Offshore"})
    assert box["signals"] == q.view("signals", user, {"group": "Offshore"})["signals"] and box["groups"] == list(qu.GROUPS)
    # the subscriptions know the three families; the log and the alerts only the confident lines - of the chosen groups
    sub = q.subscription(user)
    assert [f["label"] for f in sub["all_families"] if f["id"] in ("trend", "sira", "ml")] == ["Trend", "Carry + momentum", "Makine öğrenmesi"]
    assert [g["id"] for g in sub["all_groups"]] == list(qu.GROUPS) and sub["groups"] == ["Offshore", "G10 spot"]
    logged = {e["sid"]: e for e in q.log_view()["entries"] if e["family"] == "trend"}
    assert set(logged) == {"trend:FX:EURUSD", "trend:OISS:2Y/5Y", "trend:FWD:USDTRY:3M"} and logged["trend:FWD:USDTRY:3M"]["group"] == "Offshore"
    got = q.alerts(user, 0)["alerts"]
    assert {a["sid"] for a in got} == {"trend:FX:EURUSD", "trend:FWD:USDTRY:3M"} and all(a["group"] in ("Offshore", "G10 spot") for a in got)
    q.set_subscription(user, {"on": True, "families": [], "groups": [], "min": "Zayıf"})
    assert {"trend:OISS:2Y/5Y"} <= {a["sid"] for a in q.alerts(user, 0)["alerts"]}
    # the backtest runs the families on the universe too (a registry of each refit's context) - by group
    ctx = q._fit["ctx"]
    mons = qu.monitors(ctx)
    assert {m.sid for m in mons} == {"trend:" + k for k in PICKS} and {qbt.bt_type(m) for m in mons} == {"G10 spot", "TRY OIS", "Offshore"}


def test_a_family_s_module_is_imported_when_it_is_there_and_its_failure_is_its_own(monkeypatch):
    import importlib
    seen = []

    def fake(name):
        seen.append(name)
        if name.endswith("quantml"):
            raise RuntimeError("bozuk")
        raise ModuleNotFoundError("no", name=name)

    monkeypatch.setattr(importlib, "import_module", fake)
    monkeypatch.setattr(qu, "RUNNERS", {})                    # (none registered yet: a family module tto.quant imports is)
    errors = {}
    assert qu.runners(errors) == [] and seen == ["tto.quanttrend", "tto.quantsira", "tto.quantml"]
    assert list(errors) == ["ml"] and "bozuk" in errors["ml"]
    with pytest.raises(ValueError):
        qu.family("yok")


def test_universe_and_groups_over_http(seeded):
    svc = seeded
    if not svc.quant.status()["ready"]:
        svc.quant.compute()
    with TestClient(create_app(svc), headers=auth(svc, "Evren HTTP")) as client:
        u = client.get("/api/quant/universe").json()
        assert u["ready"] and not u.get("why") and [g["id"] for g in u["groups"]] == list(qu.GROUPS[:-1])
        rows = {r["key"]: r for r in u["rows"]}
        assert rows["OIS:2Y"]["group"] == "TRY OIS" and rows["OIS:2Y"]["size"] == "1.000 $ DV01" and rows["OIS:2Y"]["n"] > 200
        assert rows["FWD:USDTRY:3M"]["tag"] == "offshore limiti" and {r["key"] for r in u["inputs"]} >= {"UST:10Y", "DXY", "CDS"}
        assert [f["id"] for f in u["families"]] == ["trend", "sira", "ml"]
        s = client.get("/api/quant/signals", params={"group": "TRY OIS"}).json()
        assert s["group"] == "TRY OIS" and all(x["group"] == "TRY OIS" for x in s["signals"]) and [g["id"] for g in s["groups"]] == list(qu.GROUPS)
        res = client.post("/api/quant/subscription", json={"on": True, "families": ["trend", "yok"], "groups": ["VİOP", "yok"], "min": "Orta"})
        assert res.status_code == 200 and res.json()["families"] == ["trend"] and res.json()["groups"] == ["VİOP"]
        # (what is kept is the group's name, nothing a row or a position: a group's place may change, its name not)
        kept = svc.store.get(qq.Quant.SUBS_KEY)
        assert any(v.get("groups") == ["VİOP"] for v in kept.values())
