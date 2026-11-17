"""Trades · valuation and carry (``tto/tradevalue.py``): every number against a hand calculation on a market made here,
the conventions against the workbooks' own bootstrap (a swap at the workbook's quote is worth nothing), and the
snapshot read without a single Bloomberg request."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from tto import fxvol as fv
from tto import tradevalue as tv

D = dt.date
TODAY = D(2026, 11, 3)                  # a Tuesday
N = 100e6


# ---------------------------------------------------------------------------------------------- a market by hand
def bootstrap(spot, quotes, hol=()):
    """The TRY OIS curve as Motor!B88:K130 builds it, by hand: nodes every 3 months (1M, 2M, 3M first) on
    WORKDAY(EDATE(spot, n) − 1, 1, TRY), the par of each node linear in months between the quotes, a single payment up
    to 3M (DF = 1 / (1 + F·τ)), then quarterly coupons (DF = (1 − F·H) / (1 + F·τ), H the annuity of the nodes before)."""
    from tto.fx import week_day_on_or_after
    from tto.history import add_months
    qs = sorted(quotes.items())

    def par(m):
        if m <= qs[0][0]:
            return qs[0][1]
        if m >= qs[-1][0]:
            return qs[-1][1]
        for (m0, r0), (m1, r1) in zip(qs, qs[1:]):
            if m0 <= m <= m1:
                return r0 + (r1 - r0) * (m - m0) / (m1 - m0)
    days, lndf = [0.0], [0.0]
    h, prev = 0.0, spot
    for m in [1, 2, 3] + list(range(6, 121, 3)):
        d = week_day_on_or_after(add_months(spot, m), hol)
        F = par(m)
        if m <= 3:
            tau = (d - spot).days / 365.0
            df = 1.0 / (1.0 + F * tau)
            if m == 3:
                h = tau * df
        else:
            tau = (d - prev).days / 365.0
            df = (1.0 - F * h) / (1.0 + F * tau)
            h += tau * df
        if m >= 3:
            prev = d
        days.append(float((d - spot).days))
        lndf.append(math.log(df))
    return tv.Curve(spot, days, lndf, None, 365.0, "lndf", "BOOT")


QUOTES = {1: 0.40, 2: 0.395, 3: 0.39, 6: 0.38, 9: 0.37, 12: 0.36, 18: 0.35, 24: 0.345, 36: 0.34, 60: 0.33, 120: 0.31}


def hand_market(cal=None, curve=None, fix_try=None, fix_sofr=None, today=TODAY, **kw):
    """A small market: flat curves (TRY 40 % overnight, SOFR 4 %), FX spots, USD / EUR OIS flat, an offshore TRY curve
    flat at 30 %, the USDJPY 3M forward, vol quotes, two bonds of DİBS RV."""
    m = tv.Market(today, cal=cal or {}, usdtry=42.0, on_rates={"TRY": 30.0, "USD": 4.0, "EUR": 2.0},
                  spots={"USDTRY": 42.0, "EURTRY": 48.3, "EURUSD": 1.15, "USDJPY": 150.0},
                  rates={"USD": [(1.0, 4.0), (3650.0, 4.0)], "EUR": [(1.0, 2.0), (3650.0, 2.0)]},
                  meetings={"ois": ["2026-12-10", "2027-01-21", "2027-03-18"], "sofr": ["2026-12-09", "2027-01-27"]},
                  vols={"USDTRY": {"1M": {"ATM": 12.0, "RR25": 4.0, "BF25": 1.2, "RR10": 8.0, "BF10": 4.0},
                                   "3M": {"ATM": 14.0, "RR25": 5.0, "BF25": 1.5, "RR10": 10.0, "BF10": 5.0}, "1Y": {"ATM": 17.0}},
                        "USDJPY": {"1M": {"ATM": 9.0, "RR25": -1.0}, "3M": {"ATM": 9.5, "RR25": -1.2, "BF25": 0.3}}},
                  bonds={"TRT150328T24": {"isin": "TRT150328T24", "where": "DİBS RV", "kind": "fixed", "type": "S",
                                          "maturity": "2028-03-15", "coupon": 36.8, "freq": 2.0, "clean": 100.1125,
                                          "value_date": "2026-11-04", "source": "ISL1", "dv01_mn": 101.766},
                         "TRB100227T13": {"isin": "TRB100227T13", "where": "DİBS RV", "kind": "bill", "type": "B",
                                          "maturity": "2027-02-10", "coupon": 0.0, "freq": 0.0, "clean": 92.22,
                                          "value_date": "2026-11-03", "source": "ISL0", "dv01_mn": 23.067}}, **kw)
    s_try, s_usd = m.spot_date("ois"), m.spot_date("sofr")
    m.curves = {"ois": curve or tv.Curve.flat(s_try, 0.40, 365.0), "sofr": tv.Curve.flat(s_usd, 0.04, 360.0, interp="zero")}
    m.fixings = {"ois": fix_try or tv.Fixings({}, 0.40, m.hol("TRY"), 365.0, "TLREF"),
                 "sofr": fix_sofr or tv.Fixings({}, 0.04, m.hol("SIFMA"), 360.0, "SOFR")}
    m.off = tv.Curve.flat(m.fx_spot_date("USDTRY"), 0.30, 360.0)
    jpy_f = 150.0 * (1 + 0.005 * 91 / 360.0) / (1 + 0.04 * 91 / 360.0)
    m.points = {"USDJPY": [(91.0, jpy_f)]}
    return m


def ois(**kw):
    t = {"product": "ois", "side": "receive", "notional": N, "trade_date": TODAY.isoformat()}
    t.update(kw)
    return t


def business_days(a, b, hol=()):
    d, out = a, []
    while d < b:
        if d.weekday() < 5 and d not in hol:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def compounded(fixings, a, b, basis, hol=()):
    """Π (1 + r·n/basis) over the business days from a to b, each fixing over the days to the next business day."""
    days = business_days(a, b, hol)
    f = 1.0
    for i, d in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else b
        f *= 1.0 + fixings[d] * (nxt - d).days / basis
    return f


# ---------------------------------------------------------------------------------------------- the workbooks' conventions
def test_swaps_at_the_workbooks_quotes_are_worth_nothing(service):
    """The conventions are the workbooks' own: a spot-starting OIS at OIS_MAIN's quote (TRY: ACT/365, one payment to 3M
    then quarterly coupons, ``BOOT``) and a SOFR swap at SOFR_FOMC's (ACT/360, one payment to 1Y then annual coupons
    back from the end, modified following on SIFMA) price to zero on the dashboard's curves, every tenor."""
    m = tv.market(service)
    td = m.today.isoformat()
    for ten in ("1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y", "10Y"):
        r = tv.value(ois(price=m.quotes["ois"][ten], tenor=ten, trade_date=td), m)
        assert r["ok"] and abs(r["mtm"]) < 1e-3, (ten, r)
        assert r["price_text"] == "%s OIS %s%%" % (ten, tv._tr(m.quotes["ois"][ten], 2))
    for ten in ("1M", "6M", "1Y", "15M", "18M", "21M", "2Y", "3Y"):
        r = tv.value({"product": "sofr", "side": "pay", "notional": N, "trade_date": td, "tenor": ten, "price": m.quotes["sofr"][ten]}, m)
        assert r["ok"] and abs(r["mtm"]) < 1e-3, (ten, r)
        assert r["ccy"] == "USD" and abs(r["mtm_try"] - r["mtm"] * m.usdtry) < 1e-6
    # DİBS RV's bond at its own price and value date: nothing; the meeting periods by date
    isin = next(i for i, b in m.bonds.items() if b.get("type") == "S" and b.get("clean"))
    row = m.bonds[isin]
    r = tv.value({"product": "dibs", "isin": isin, "side": "B", "notional": 10e6, "price": row["clean"], "trade_date": td,
                  "settle_date": row["value_date"]}, m)
    assert r["ok"] and abs(r["mtm"]) < 1e-9 and r["accrued"] == 0.0
    assert r["inputs"]["source"] == "DİBS RV" and abs(r["inputs"]["accrued_now"] - row["accrued"]) < 1e-9
    periods = tv.defaults("ois", mkt_or_svc=m)["mpc_periods"]
    assert periods and all(p["value_date"] > m.today.isoformat() for p in periods)
    assert periods[0]["mpc_date"] in m.meetings["ois"]


def test_par_swap_is_zero_and_a_bp_shift_is_its_dv01():
    """On the hand bootstrap (Motor's formula): an OIS at its quote is worth nothing; every quote 1 bp higher moves a
    receiver by −DV01 (notional × annuity × 1e-4)."""
    m = hand_market()
    spot = m.spot_date("ois")
    m.curves["ois"] = bootstrap(spot, QUOTES)
    for ten, mon in (("3M", 3), ("1Y", 12), ("2Y", 24), ("5Y", 60)):
        t = ois(price=QUOTES[mon] * 100.0, tenor=ten)
        r = tv.value(t, m)
        assert abs(r["mtm"]) < 1e-5 * N / 1e6, (ten, r["mtm"])
        dv01 = r["inputs"]["dv01"]
        m.curves["ois"] = bootstrap(spot, {k: v + 1e-4 for k, v in QUOTES.items()})
        moved = tv.value(t, m)["mtm"]
        m.curves["ois"] = bootstrap(spot, QUOTES)
        assert moved < 0 and abs(moved + dv01) < 0.01 * dv01, (ten, moved, dv01)


def test_spread_at_its_levels_is_zero_and_dv01_neutral_spread_shrugs_off_a_shift():
    m = hand_market()
    spot = m.spot_date("ois")
    m.curves["ois"] = bootstrap(spot, QUOTES)
    a2 = tv.value(ois(price=QUOTES[24] * 100, tenor="2Y"), m)["inputs"]["annuity"]
    a5 = tv.value(ois(price=QUOTES[60] * 100, tenor="5Y"), m)["inputs"]["annuity"]
    legs = [{"tenor": "2Y", "side": "receive", "notional": N, "price": QUOTES[24] * 100},
            {"tenor": "5Y", "side": "pay", "notional": N * a2 / a5, "price": QUOTES[60] * 100}]
    t = ois(structure="spread", legs=legs)
    r = tv.value(t, m)
    assert r["ok"] and abs(r["mtm"]) < 1e-3 and len(r["legs"]) == 2
    assert abs(r["mtm"] - sum(lg["mtm"] for lg in r["legs"])) < 1e-9
    assert abs(r["price_now"] - (QUOTES[60] - QUOTES[24]) * 1e4) < 1e-6 and r["price_text"].startswith("2s5s ")
    assert abs(r["inputs"]["dv01_net"]) < 1e-6 * r["inputs"]["legs_dv01"][0]
    m.curves["ois"] = bootstrap(spot, {k: v + 1e-4 for k, v in QUOTES.items()})
    moved = tv.value(t, m)
    # the same shift moves each leg by its DV01 (~N·a2·1e-4); the DV01-neutral package by almost nothing
    assert abs(moved["legs"][0]["mtm"]) > 0.9 * N * a2 * 1e-4
    assert abs(moved["mtm"]) < 0.02 * N * a2 * 1e-4


def test_fly_level_in_both_conventions():
    m = hand_market()
    m.curves["ois"] = bootstrap(m.spot_date("ois"), QUOTES)
    legs = [{"tenor": "1Y", "side": "receive", "notional": N / 2, "price": 36.0},
            {"tenor": "2Y", "side": "pay", "notional": N, "price": 34.5},
            {"tenor": "5Y", "side": "receive", "notional": N / 2, "price": 33.0}]
    r = tv.value(ois(structure="fly", legs=legs), m)
    p1, p2, p5 = (lg["price_now"] for lg in r["legs"])
    level = (p2 - 0.5 * (p1 + p5)) * 100.0
    assert abs(r["price_now"] - level) < 1e-9 and abs(r["inputs"]["sheet_bp"] - 2.0 * level) < 1e-9
    assert r["price_text"] == "1s2s5s %s bp (OIS sayfasında %s)" % (tv._tr(level, 1), tv._tr(2.0 * level, 1))
    assert abs(r["inputs"]["traded_bp"] - (34.5 - 0.5 * (36.0 + 33.0)) * 100) < 1e-9
    assert abs(r["mtm"] - sum(lg["mtm"] for lg in r["legs"])) < 1e-6
    checked = tv.check(ois(structure="fly", legs=legs), m)
    assert checked["side"] == "B" and abs(checked["price"] - (34.5 - 34.5) * 100) < 1e-9


def test_fra_alone_equals_its_replicating_legs():
    """A 3x6 FRA valued as one forward-starting swap; its attribution - receive OIS to its end, pay OIS to its start,
    from the trade's settlement, same notional and rate - adds up to it (the residual is what is left)."""
    m = hand_market()
    m.curves["ois"] = bootstrap(m.spot_date("ois"), QUOTES)
    t = ois(structure="fra", fra="3x6", price=38.0)
    r = tv.value(t, m)
    assert r["ok"] and len(r["legs"]) == 2 and r["price_text"].startswith("3x6 FRA ")
    res = r["inputs"]["residual"]
    assert abs(r["mtm"] - sum(lg["mtm"] for lg in r["legs"]) - res["mtm"]) < 1e-6
    assert abs(r["carry_1d"] - sum(lg["carry_1d"] for lg in r["legs"]) - res["carry"]) < 1e-6
    assert abs(res["mtm"]) < 1e-6 * N and abs(res["carry"]) < 1e-6 * N        # (a 3x6 on the grid replicates exactly)
    assert r["legs"][0]["label"].startswith("Receive OIS") and r["legs"][1]["label"].startswith("Pay OIS")
    # the FRA's own value: its forward period discounted on the curve
    c = m.curves["ois"]
    s, e = tv._day(tv.check(t, m)["value_date"]), tv._day(tv.check(t, m)["end_date"])
    tau = (e - s).days / 365.0
    df0 = c.df(TODAY)
    hand = N * (0.38 * tau * c.df(e) / df0 - (c.df(s) - c.df(e)) / df0)
    assert abs(r["mtm"] - hand) < 1e-6
    fwd = (c.df(s) / c.df(e) - 1.0) / tau * 100.0
    assert abs(r["price_now"] - fwd) < 1e-9
    # an FRA that does not sit on the grid of its settlement: a residual, reported
    off = tv.value(ois(structure="fra", value_date="2027-01-15", end_date="2027-07-15", price=38.0), m)
    assert off["ok"] and abs(off["mtm"] - sum(lg["mtm"] for lg in off["legs"]) - off["inputs"]["residual"]["mtm"]) < 1e-6
    # "3x6" typed over a form that still holds the default value date (the spot): the FRA's dates win
    form = tv.check(ois(structure="fra", fra="3x6", value_date="2026-11-04", end_date="", price=38.0), m)
    assert (form["value_date"], form["end_date"]) == ("2027-02-04", "2027-05-04")
    assert tv.value(dict(t, product=" OIS "), m)["mtm"] == r["mtm"]


def test_schedules_of_a_tenor_and_of_a_broken_date():
    usd, try_ = tv.CONVS["sofr"], tv.CONVS["ois"]
    # USD: a tenor's coupons as the SOFR book dates them - EDATE(start, m − 12k), modified following (15M: at 3M) ...
    assert tv.schedule(D(2026, 11, 5), D(2028, 2, 7), usd, (), months=15) == [(D(2026, 11, 5), D(2027, 2, 5)),
                                                                             (D(2027, 2, 5), D(2028, 2, 7))]
    # ... a broken end date's back from the end, the first period short
    assert tv.schedule(D(2026, 6, 17), D(2028, 6, 30), usd, ()) == [(D(2026, 6, 17), D(2026, 6, 30)),
                                                                     (D(2026, 6, 30), D(2027, 6, 30)), (D(2027, 6, 30), D(2028, 6, 30))]
    # TRY: one payment up to 3M, then every 3 months from the start, the last period to the end date
    assert tv.schedule(D(2026, 11, 4), D(2027, 2, 4), try_, ()) == [(D(2026, 11, 4), D(2027, 2, 4))]
    assert tv.schedule(D(2026, 11, 4), D(2027, 4, 20), try_, ()) == [(D(2026, 11, 4), D(2027, 2, 4)), (D(2027, 2, 4), D(2027, 4, 20))]


def test_a_swap_closed_inside_a_period():
    """Unwound six weeks into a quarter: the swap's own accrual up to the close, the fixed difference after it."""
    start, close = D(2026, 8, 4), D(2026, 9, 15)
    days = business_days(start, TODAY)
    fix = tv.Fixings({d.isoformat(): 40.0 for d in days}, 0.40, (), 365.0, "TLREF")
    m = hand_market(fix_try=fix)
    t = ois(price=41.0, trade_date="2026-08-03", settle_date=start.isoformat(), tenor="1Y", status="closed", close_price=39.0,
            close_date=close.isoformat())
    r = tv.value(t, m)
    c = m.curves["ois"]
    periods = tv.schedule(start, D(2027, 8, 4), tv.CONVS["ois"], (), months=12)
    assert periods[0] == (start, D(2026, 11, 4))
    hand = 0.0
    for a, b in periods:
        d_b = c.df(b) / c.df(TODAY)
        if a < close < b:
            i_ac = compounded({d: 0.40 for d in business_days(a, close)}, a, close, 365.0)
            pay = N * (0.41 * (close - a).days / 365.0 - (i_ac - 1.0)) + N * 0.02 * (b - close).days / 365.0
        else:
            pay = N * 0.02 * (b - a).days / 365.0
        hand += pay * d_b
    assert abs(r["mtm"] - hand) < 1e-6 and r["carry_1d"] == 0.0 and r["accrued"] == 0.0


def test_sides_in_words_or_in_the_blotters_codes():
    """The form sends "receive" / "pay", the blotter's codes are "S" (receives the fixed rate) / "B" (pays it): check()
    takes either and writes the code, the same trade values the same, and every leg says its side in words."""
    m = hand_market()
    m.curves["ois"] = bootstrap(m.spot_date("ois"), QUOTES)
    for words, code in (("receive", "S"), ("pay", "B")):
        assert tv.check(ois(side=words, price=35.0, tenor="2Y"), m)["side"] == code
        a, b = tv.value(ois(side=words, price=35.0, tenor="2Y"), m), tv.value(ois(side=code, price=35.0, tenor="2Y"), m)
        assert a == b and a["side"] == code and a["side_text"] == words
    legs_w = [{"tenor": "1Y", "side": "receive", "notional": N / 2, "price": 36.0}, {"tenor": "2Y", "side": "pay", "notional": N, "price": 34.5},
              {"tenor": "5Y", "side": "receive", "notional": N / 2, "price": 33.0}]
    legs_c = [dict(lg, side={"receive": "S", "pay": "B"}[lg["side"]]) for lg in legs_w]
    a, b = tv.value(ois(structure="fly", legs=legs_w), m), tv.value(ois(structure="fly", legs=legs_c), m)
    assert a == b and [(lg["side"], lg["side_text"]) for lg in a["legs"]] == [("S", "receive"), ("B", "pay"), ("S", "receive")]
    assert a["legs"][1]["label"] == "Pay 2Y OIS" and a["side"] == "B"
    fra = tv.value(ois(structure="fra", fra="3x6", side="receive", price=38.0), m)
    assert [(lg["side"], lg["side_text"]) for lg in fra["legs"]] == [("S", "receive"), ("B", "pay")]
    # what a form is offered: the codes with their words, a package's legs for each side of it
    d = tv.defaults("ois", mkt_or_svc=m)
    assert d["sides"] == [{"side": "S", "side_text": "receive"}, {"side": "B", "side_text": "pay"}]
    assert [lg["side_text"] for lg in d["weights"]["spread"]["legs"]["B"]] == ["receive", "pay"]       # (pay the spread: the long leg)
    assert [lg["side"] for lg in d["weights"]["fly"]["legs"]["S"]] == ["B", "S", "B"]                   # (receive the body)
    assert tv.defaults("fxspot", "USDTRY", mkt_or_svc=m)["sides"][0] == {"side": "B", "side_text": "buy"}
    with pytest.raises(ValueError):
        tv.check(ois(side="buy", price=35.0, tenor="2Y"), m)


def test_mpc_trade_is_keyed_by_its_meeting_date():
    m = hand_market()
    t = tv.check(ois(structure="mpc", mpc_date="2027-01-21", price=37.0), m)
    assert (t["value_date"], t["end_date"], t["mpc_end"]) == ("2027-01-22", "2027-03-19", "2027-03-18")
    before = tv.value(t, m)
    # the calendar moves: a meeting is added before it and one between it and the next - the rows all shift
    m.meetings["ois"] = ["2026-11-20", "2026-12-10", "2027-01-21", "2027-02-25", "2027-03-18"]
    again = tv.check(t, m)
    assert (again["value_date"], again["end_date"]) == ("2027-01-22", "2027-03-19")
    after = tv.value(t, m)
    assert after["mtm"] == before["mtm"] and after["price_text"] == before["price_text"] == \
        "MPC 22.01.27–19.03.27 %s%%" % tv._tr(before["price_now"], 2)
    # a new trade on the same meeting takes the calendar as it is now
    assert tv.check(ois(structure="mpc", mpc_date="2027-01-21", price=37.0), m)["end_date"] == "2027-02-26"


# ---------------------------------------------------------------------------------------------- fixings
def test_started_ois_uses_the_fixings():
    """A receiver started two weeks ago: its float leg is the TLREF fixings so far, then the curve; the period's net
    settlement and the day's accrual by hand."""
    start, end = D(2026, 10, 20), D(2026, 11, 20)
    days = business_days(start, TODAY)
    fixings = {d: 0.45 for d in days}
    fix = tv.Fixings({d.isoformat(): 45.0 for d in days}, 0.40, (), 365.0, "TLREF")
    m = hand_market(fix_try=fix)
    t = ois(price=41.0, trade_date="2026-10-19", settle_date="2026-10-20", end_date=end.isoformat())
    r = tv.value(t, m)
    c = m.curves["ois"]
    i_real = compounded(fixings, start, TODAY, 365.0)
    d_e = c.df(end) / c.df(TODAY)
    hand = N * (0.41 * (end - start).days / 365.0 * d_e - (i_real - d_e))
    assert abs(r["mtm"] - hand) < 1e-6 and r["inputs"]["fixings"] == {"fix": len(days)}
    # the same trade with the fixings at the overnight: the difference is the realised part alone
    flat = tv.value(t, hand_market())
    assert abs((flat["mtm"] - r["mtm"]) - N * (i_real - compounded({d: 0.40 for d in days}, start, TODAY, 365.0))) < 1e-6
    assert flat["inputs"]["notes"] and "TLREF fixingleri tarihçede yok" in flat["inputs"]["notes"][0]
    # carry: fixed against today's overnight on the compounded notional (1 day: Tuesday → Wednesday); no roll on a flat curve
    assert abs(r["inputs"]["carry_accrual"] - N * (0.41 - i_real * 0.40) / 365.0) < 1e-6
    assert abs(r["inputs"]["roll_1d"]) < 1e-4 and abs(r["carry_1d"] - r["inputs"]["carry_accrual"]) < 1e-4
    # a period paid: its net settlement is accrued, not MTM
    t2 = ois(price=41.0, trade_date="2026-09-01", settle_date="2026-09-02", end_date="2026-10-02")
    fx2 = {d: 0.42 for d in business_days(D(2026, 9, 2), D(2026, 10, 2))}
    m2 = hand_market(fix_try=tv.Fixings({d.isoformat(): 42.0 for d in fx2}, 0.40, (), 365.0, "TLREF"))
    r2 = tv.value(t2, m2)
    assert r2["mtm"] == 0.0
    assert abs(r2["accrued"] - N * (0.41 * 30 / 365.0 - (compounded(fx2, D(2026, 9, 2), D(2026, 10, 2), 365.0) - 1.0))) < 1e-6


def test_started_sofr_uses_its_fixings_or_says_so():
    start, end = D(2026, 10, 15), D(2027, 1, 15)
    days = business_days(start, TODAY)
    fix = tv.Fixings({d.isoformat(): 5.0 for d in days}, 0.04, (), 360.0, "SOFR")
    m = hand_market(fix_sofr=fix)
    t = {"product": "sofr", "side": "pay", "notional": N, "price": 4.1, "trade_date": "2026-10-13", "settle_date": "2026-10-15",
         "end_date": end.isoformat()}
    r = tv.value(t, m)
    c = m.curves["sofr"]
    i_real = compounded({d: 0.05 for d in days}, start, TODAY, 360.0)
    d_e = c.df(end) / c.df(TODAY)
    hand = -N * (0.041 * (end - start).days / 360.0 * d_e - (i_real - d_e))
    assert r["ok"] and r["ccy"] == "USD" and abs(r["mtm"] - hand) < 1e-6
    assert abs(r["mtm_try"] - r["mtm"] * 42.0) < 1e-6 and abs(r["mtm_usd"] - r["mtm"]) < 1e-9
    assert abs(r["inputs"]["carry_accrual"] + N * (0.041 - i_real * 0.04) / 360.0) < 1e-6
    # no SOFR in the history: the current fixing stands for the days already fixed, and the trade says so
    bare = tv.value(t, hand_market())
    assert bare["ok"] and any("SOFR fixingleri tarihçede yok" in n for n in bare["inputs"]["notes"])


# ---------------------------------------------------------------------------------------------- bonds
def _bist_accrued(maturity, coupon, value, freq=2):
    """DİBS RV's accrued by hand: c/f × days since the last coupon / the period (round(364/f) days back from the maturity)."""
    period = int(round(364.0 / freq))
    d = maturity
    while d > value:
        d -= dt.timedelta(days=period)
    return coupon / freq * (value - d).days / period


def test_bond_at_its_price_and_its_coupons():
    m = hand_market()
    t = {"product": "dibs", "isin": "TRT150328T24", "side": "B", "notional": 10e6, "price": 100.1125, "trade_date": TODAY.isoformat()}
    r = tv.value(t, m)
    assert r["ok"] and abs(r["mtm"]) < 1e-9 and r["accrued"] == 0.0 and r["price_text"] == "TRT150328T24 " + tv._tr(100.1125, 3)
    assert tv.check(t, m)["settle_date"] == "2026-11-04"             # (ISL1: the next TRY business day)
    # bought in August: the September coupon is accrued; MTM = dirty now − dirty paid
    t = dict(t, price=99.0, trade_date="2026-08-03", settle_date="2026-08-04")
    r = tv.value(t, m)
    mat = D(2028, 3, 15)
    dirty_now = 100.1125 + _bist_accrued(mat, 36.8, D(2026, 11, 4))
    dirty_paid = 99.0 + _bist_accrued(mat, 36.8, D(2026, 8, 4))
    assert abs(r["mtm"] - 10e6 / 100 * (dirty_now - dirty_paid)) < 1e-6
    assert abs(r["accrued"] - 10e6 / 100 * 18.4) < 1e-9 and abs(r["inputs"]["accrued_now"] - 4.953846153846) < 1e-9
    sold = tv.value(dict(t, side="S"), m)
    assert abs(sold["mtm"] + r["mtm"]) < 1e-9 and abs(sold["accrued"] + r["accrued"]) < 1e-9


def test_yield_entered_bond_converts_with_the_same_math():
    m = hand_market()
    # the bill at its simple yield ((100/P − 1)·365/days) and its compound one ((100/P)^(365/days) − 1)
    days = (D(2027, 2, 10) - TODAY).days
    y_s, y_c = (100 / 92.22 - 1) * 365 / days, (100 / 92.22) ** (365.0 / days) - 1
    for y, conv in ((y_s, "basit"), (y_c, "bileşik")):
        r = tv.value({"product": "dibs", "isin": "TRB100227T13", "side": "B", "notional": 10e6, "yield": y * 100, "yield_conv": conv,
                      "trade_date": TODAY.isoformat()}, m)
        assert r["ok"] and abs(r["mtm"]) < 1e-6 and abs(r["inputs"]["clean_paid"] - 92.22) < 1e-10, conv
    # the coupon bond at the sheet's compound yield: its dirty price (BIST: f-times compounded, the first period fractional)
    r = tv.value({"product": "dibs", "isin": "TRT150328T24", "side": "B", "notional": 10e6, "yield": 39.702755562957237,
                  "trade_date": TODAY.isoformat()}, m)
    assert abs(r["inputs"]["dirty_paid"] - 105.06634615384735) < 1e-8 and abs(r["mtm"]) < 1e-4
    assert tv.check({"product": "dibs", "isin": "TRB100227T13", "side": "B", "notional": 1e6, "yield": "31,1",
                     "trade_date": TODAY.isoformat()}, m)["yield_conv"] == "bileşik"         # (the default)


# ---------------------------------------------------------------------------------------------- FX
def test_fx_spot_pnl_and_conversion():
    m = hand_market()
    r = tv.value({"product": "fxspot", "pair": "EURUSD", "side": "B", "notional": 1e6, "price": 1.10, "trade_date": TODAY.isoformat()}, m)
    assert r["ccy"] == "USD" and abs(r["mtm"] - 50000.0) < 1e-6
    assert abs(r["mtm_usd"] - 50000.0) < 1e-6 and abs(r["mtm_try"] - 50000.0 * 42.0) < 1e-4
    assert r["price_text"] == "EURUSD 1,15000"
    r = tv.value({"product": "fxspot", "pair": "USDJPY", "side": "S", "notional": 1e6, "price": 148.0, "trade_date": TODAY.isoformat()}, m)
    assert r["ccy"] == "JPY" and abs(r["mtm"] + 2e6) < 1e-6
    assert abs(r["mtm_usd"] + 2e6 / 150.0) < 1e-6 and abs(r["mtm_try"] + 2e6 / 150.0 * 42.0) < 1e-4
    # a notional in the quote currency: the base amount at the trade's rate
    r = tv.value({"product": "fxspot", "pair": "USDTRY", "side": "B", "notional": 41e6, "notional_ccy": "TRY", "price": 41.0,
                  "trade_date": TODAY.isoformat()}, m)
    assert abs(r["mtm"] - 1e6 * (42.0 - 41.0)) < 1e-6 and r["price_text"] == "USDTRY 42,0000"
    # carry: rolling the position a day at the overnight rates (TRY offshore O/N 30 %, USD 4 %)
    f1 = 42.0 * (1 + 0.30 / 360) / (1 + 0.04 / 360)
    assert abs(r["carry_1d"] + 1e6 * (f1 - 42.0)) < 1e-6 and r["inputs"]["carry_days"] == 1


def test_option_garman_kohlhagen_and_put_call_parity():
    # the closed form: S = K = 100, a year, no rates, 20 vol -> 100·(2·N(0.1) − 1)
    assert abs(tv.gk(100.0, 100.0, 1.0, 0.2, 1.0, 1.0, True) - 100.0 * (2 * fv.ncdf(0.1) - 1.0)) < 1e-12
    for K in (90.0, 100.0, 115.0):
        c = tv.gk(100.0, K, 0.75, 0.15, 0.97, 0.995, True)
        p = tv.gk(100.0, K, 0.75, 0.15, 0.97, 0.995, False)
        assert abs((c - p) - (100.0 * 0.995 - K * 0.97)) < 1e-10
    # a trade at a vol typed by hand: value − premium, the forward and discounting of the market
    m = hand_market()
    t = {"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": 500000.0, "trade_date": TODAY.isoformat(),
         "call_put": "call", "strike": 45.0, "expiry": "2027-02-03", "manual_price": 15.0}
    r = tv.value(t, m)
    dl = D(2027, 2, 4)
    sd = m.fx_spot_date("USDTRY")
    g = (dl - sd).days
    dq = m.off.df(dl) / m.off.df(sd)
    F = 42.0 * (m.off.df(sd) / m.off.df(dl)) / (1 + 0.04 * g / 360.0)
    T = (D(2027, 2, 3) - TODAY).days / 365.0
    sd1 = 0.15 * math.sqrt(T)
    d1 = (math.log(F / 45.0) + 0.5 * sd1 * sd1) / sd1
    hand = dq * (F * fv.ncdf(d1) - 45.0 * fv.ncdf(d1 - sd1))
    assert abs(r["inputs"]["forward"] - F) < 1e-9 and abs(r["mtm"] - (1e6 * hand - 500000.0)) < 1e-4
    assert r["ccy"] == "TRY" and r["price_text"] == "USDTRY 03.02.27 45 call vol 15,0"
    put = tv.value(dict(t, call_put="put", price=0.0), m)
    call = tv.value(dict(t, price=0.0), m)
    assert abs((call["mtm"] - put["mtm"]) - 1e6 * dq * (F - 45.0)) < 1e-4
    sold = tv.value(dict(t, side="S"), m)
    assert abs(sold["mtm"] + r["mtm"]) < 1e-6


def test_smile_vol_at_the_money_is_the_atm_vol():
    m = hand_market()
    for pair, model in (("USDTRY", "svi"), ("USDJPY", "vv")):
        p = next(x for x in tv.fxm.PAIRS if x.code == pair)
        for days in (30.0, 61.0, 91.25):
            q = tv._interp_quotes(m.vols[pair], days)
            F = m.spot(pair) * 1.01
            K = fv.atm_strike(F, q["ATM"] / 100.0, days / 365.0, p.premium)
            v, info = tv.smile_vol(m, pair, K, days, F, 0.99)
            assert info["model"] == model and abs(v * 100.0 - q["ATM"]) < 1e-4, (pair, days, v, q["ATM"])
    # the ATM between tenors in total variance: 2M between 1M 12 and 3M 14
    q = tv._interp_quotes(m.vols["USDTRY"], 61.0)
    t1, t3 = 365.0 / 12, 91.25
    w = 0.12 ** 2 * t1 + (0.14 ** 2 * t3 - 0.12 ** 2 * t1) * (61.0 - t1) / (t3 - t1)
    assert abs(q["ATM"] - 100.0 * math.sqrt(w / 61.0)) < 1e-12
    # no quotes for a pair: no vol (the option says so)
    v, info = tv.smile_vol(m, "EURTRY", 50.0, 91.0, 50.0, 1.0)
    assert v is None and "vol kotası yok" in info["why"]


def test_greeks_by_finite_difference():
    S, K, T, s, dq, db = 42.0, 44.0, 0.5, 0.16, 0.86, 0.98
    g = tv.gk_greeks(S, K, T, s, dq, db, True)
    h = 1e-4
    up, dn = tv.gk(S + h, K, T, s, dq, db, True), tv.gk(S - h, K, T, s, dq, db, True)
    assert abs(g["delta"] - (up - dn) / (2 * h)) < 1e-7
    assert abs(g["gamma"] - (up - 2 * g["price"] + dn) / (h * h)) < 1e-4
    assert abs(g["vega"] - (tv.gk(S, K, T, s + h, dq, db, True) - tv.gk(S, K, T, s - h, dq, db, True)) / (2 * h)) < 1e-6
    put = tv.gk_greeks(S, K, T, s, dq, db, False)
    assert abs((g["delta"] - put["delta"]) - db) < 1e-12              # (parity: Δcall − Δput = DF_base)
    # the trade's greeks: delta in base currency (USD), vega a vol point, gamma the delta's move for +1 % spot, theta a day
    m = hand_market()
    t = {"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 2e6, "price": 0.0, "trade_date": TODAY.isoformat(),
         "call_put": "put", "strike": 41.0, "expiry": "2027-02-03", "manual_price": 14.0}
    base = tv.value(t, m)
    gr = base["greeks"]
    bump = 0.01

    def mtm_at(spot, vol=14.0):
        mm = hand_market()
        mm.spots["USDTRY"] = spot
        return tv.value(dict(t, manual_price=vol), mm)["mtm"]
    assert abs(gr["delta"] - (mtm_at(42.0 + bump) - mtm_at(42.0 - bump)) / (2 * bump)) < 1e-3 * abs(gr["delta"])
    assert abs(gr["vega"] - (mtm_at(42.0, 14.01) - mtm_at(42.0, 13.99)) / 0.02) < 1e-3 * abs(gr["vega"])
    d_up = tv.value(t, _spot(m, 42.0 * 1.0001))["greeks"]["delta"]
    d_dn = tv.value(t, _spot(m, 42.0 * 0.9999))["greeks"]["delta"]
    assert abs(gr["gamma"] - (d_up - d_dn) / 0.0002 * 0.01) < 1e-3 * abs(gr["gamma"])
    assert gr["delta_ccy"] == "USD" and gr["ccy"] == "TRY" and gr["delta"] < 0 and gr["vega"] > 0
    # (theta holds the spot: USDTRY's forward falls towards it a day on - the TRY carry - and a put's value rises)
    assert gr["theta"] > 0 and tv.value(dict(t, call_put="call", strike=44.0), m)["greeks"]["theta"] < 0


def _spot(m, s):
    mm = hand_market()
    mm.spots["USDTRY"] = s
    return mm


# ---------------------------------------------------------------------------------------------- carry
def test_carry_per_product_by_hand():
    m = hand_market()
    # OIS / SOFR not started yet on a flat curve: nothing accrues, nothing rolls
    r = tv.value(ois(price=40.0, tenor="2Y"), m)
    assert r["inputs"]["carry_accrual"] == 0.0 and abs(r["carry_1d"]) < 1e-6
    # ... on a sloped curve the roll-down: the trade on the curve rolled a day against the forwards realised
    m.curves["ois"] = bootstrap(m.spot_date("ois"), QUOTES)
    r = tv.value(ois(price=QUOTES[12] * 100, tenor="1Y"), m)
    assert r["inputs"]["carry_accrual"] == 0.0 and r["carry_1d"] == r["inputs"]["roll_1d"] != 0.0
    # DİBS: the bill at its yield a day on, less the dirty price funded a day at TLREF (40 %)
    m = hand_market()
    r = tv.value({"product": "dibs", "isin": "TRB100227T13", "side": "B", "notional": 10e6, "price": 92.22, "trade_date": TODAY.isoformat()}, m)
    days = (D(2027, 2, 10) - TODAY).days
    y = (100 / 92.22 - 1) * 365 / days
    p2 = 100 / (1 + y * (days - 1) / 365)
    assert abs(r["carry_1d"] - 10e6 / 100 * (p2 - 92.22 * (1 + 0.40 / 365))) < 1e-6
    # the coupon bond: the BIST price at its simple yield a value date on, less funding
    r = tv.value({"product": "dibs", "isin": "TRT150328T24", "side": "B", "notional": 10e6, "price": 100.1125,
                  "trade_date": TODAY.isoformat()}, m)
    from tto import quantcurve as qc
    b = qc.Bond("TRT150328T24", "", "fixed", D(2028, 3, 15), 36.8, 2)
    v1, v2 = D(2026, 11, 4), D(2026, 11, 5)
    dirty = 100.1125 + _bist_accrued(D(2028, 3, 15), 36.8, v1)
    ys = b.yield_of(dirty, v1, "simple")
    assert abs(r["carry_1d"] - 10e6 / 100 * (b.price(ys, v2, "simple")[0] - dirty * (1 + 0.40 / 365))) < 1e-6
    # FX option: theta over the day - the same spot, vol and rates a day later
    t = {"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": 0.0, "trade_date": TODAY.isoformat(),
         "call_put": "call", "strike": 44.0, "expiry": "2027-02-03", "manual_price": 15.0}
    r = tv.value(t, m)
    i = r["inputs"]
    tq = float((D(2027, 2, 4) - m.fx_spot_date("USDTRY")).days)
    rq, rb = -math.log(i["df_quote"]) / tq, -math.log(i["df_base"]) / tq
    later = 1e6 * tv.gk(42.0, 44.0, i["T"] - 1 / 365.0, 0.15, math.exp(-rq * (tq - 1)), math.exp(-rb * (tq - 1)), True)
    assert abs(r["carry_1d"] - (later - i["value"])) < 1e-6 and r["greeks"]["theta"] == r["carry_1d"]


def test_carry_over_a_weekend_and_a_holiday():
    """A Friday's carry runs to Monday (three days, as TLREF's Friday fixing does); a TRY holiday on Monday makes it four."""
    fri = D(2026, 11, 6)
    m = hand_market(today=fri, cal={"TRY": {D(2026, 11, 9)}})
    t = ois(price=41.0, trade_date="2026-11-02", settle_date="2026-11-03", end_date="2027-01-04")
    r = tv.value(t, m)
    assert r["inputs"]["carry_days"] == 4
    i_real = compounded({d: 0.40 for d in business_days(D(2026, 11, 3), fri)}, D(2026, 11, 3), fri, 365.0)
    assert abs(r["inputs"]["carry_accrual"] - N * (0.41 - i_real * 0.40) * 4 / 365.0) < 1e-6


# ---------------------------------------------------------------------------------------------- what is missing
def test_results_are_plain_json():
    """What :func:`value` returns is kept as it is in the close snapshots: plain JSON, every product and package."""
    import json
    m = hand_market()
    m.curves["ois"] = bootstrap(m.spot_date("ois"), QUOTES)
    td = TODAY.isoformat()
    trades = [ois(price=35.0, tenor="2Y"), ois(structure="fra", fra="3x6", price=38.0),
              ois(structure="mpc", mpc_date="2026-12-10", price=39.0),
              ois(structure="spread", legs=[{"tenor": "1Y", "side": "pay", "notional": N, "price": 36},
                                            {"tenor": "2Y", "side": "receive", "notional": N, "price": 34.5}]),
              {"product": "sofr", "side": "pay", "notional": N, "price": 4.0, "tenor": "2Y", "trade_date": td},
              {"product": "dibs", "isin": "TRT150328T24", "side": "B", "notional": 1e6, "price": 99.0, "trade_date": td},
              {"product": "fxspot", "pair": "EURTRY", "side": "S", "notional": 1e6, "price": 48.0, "trade_date": td},
              {"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": 1e5, "trade_date": td,
               "call_put": "call", "strike": 45.0, "tenor": "3M"},
              {"product": "fxopt", "pair": "USDJPY", "side": "S", "notional": 1e6, "price": 1e4, "premium_ccy": "USD",
               "trade_date": td, "call_put": "put", "strike": 148.0, "expiry": "2027-01-05"}]
    for t in trades:
        r = tv.value(t, m)
        assert r["ok"], (t, r["why"])
        back = json.loads(json.dumps(r, allow_nan=False))
        assert back["mtm"] == r["mtm"] and set(back) >= {"ok", "why", "ccy", "mtm", "mtm_try", "mtm_usd", "carry_1d", "carry_1d_try",
                                                         "carry_1d_usd", "accrued", "price_now", "price_text", "greeks", "inputs"}
    assert tv.value({"product": "ois"}, m)["ok"] is False and tv.value(None, m)["ok"] is False


def test_closed_trades_keep_what_the_close_locked_in():
    m = hand_market()
    td = TODAY.isoformat()
    # a swap unwound at 38 %: the fixed difference on the periods left, no carry
    t = ois(price=40.0, tenor="2Y")
    a = tv.value(t, m)["inputs"]["annuity"]
    r = tv.value(dict(t, status="closed", close_price=38.0, close_date=td), m)
    assert abs(r["mtm"] - N * 0.02 * a) < 1e-6 and r["carry_1d"] == 0.0
    # FX spot and a bond at their close price, whatever the market does since
    r = tv.value({"product": "fxspot", "pair": "EURUSD", "side": "B", "notional": 1e6, "price": 1.10, "trade_date": td,
                  "status": "closed", "close_price": 1.12, "close_date": td}, m)
    assert abs(r["mtm"] - 20000.0) < 1e-6 and r["carry_1d"] == 0.0
    r = tv.value({"product": "dibs", "isin": "TRT150328T24", "side": "B", "notional": 10e6, "price": 99.0, "trade_date": td,
                  "status": "closed", "close_price": 100.0, "close_date": td}, m)
    assert abs(r["mtm"] - 10e6 / 100 * 1.0) < 1e-6 and r["carry_1d"] == 0.0 and r["inputs"]["source"] == "kapanış fiyatı"
    # an option sold back: the close premium against the opening one
    r = tv.value({"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": 100000.0, "trade_date": td,
                  "call_put": "call", "strike": 45.0, "expiry": "2027-02-03", "status": "closed", "close_price": 150000.0,
                  "close_date": td}, m)
    assert abs(r["mtm"] - 50000.0) < 1e-9 and r["carry_1d"] == 0.0 and r["greeks"] is None


def test_manual_price_fallbacks():
    m = hand_market()
    td = TODAY.isoformat()
    # a bond the catalog knows but no list prices
    t = {"product": "dibs", "isin": "TRT081128T15", "side": "B", "notional": 5e6, "price": 99.0, "trade_date": td}
    r = tv.value(t, m)
    assert not r["ok"] and "elle fiyat" in r["why"] and r["mtm"] is None
    r = tv.value(dict(t, manual_price=101.5), m)
    assert r["ok"] and r["price_now"] == 101.5 and r["inputs"]["source"] == "elle fiyat"
    # a pair without a spot
    t = {"product": "fxspot", "pair": "USDCAD", "side": "B", "notional": 1e6, "price": 1.35, "trade_date": td}
    r = tv.value(t, m)
    assert not r["ok"] and "USDCAD" in r["why"]
    r = tv.value(dict(t, manual_price=1.40), m)
    assert r["ok"] and abs(r["mtm"] - 1e6 * 0.05) < 1e-6 and r["inputs"]["spot_source"] == "elle kur"
    # an option without vol quotes: a vol typed by hand
    t = {"product": "fxopt", "pair": "EURTRY", "side": "S", "notional": 1e6, "price": 100000.0, "trade_date": td, "call_put": "C",
         "strike": 50.0, "expiry": "2027-02-03"}
    r = tv.value(t, m)
    assert not r["ok"] and "vol" in r["why"]
    r = tv.value(dict(t, manual_price=16.0), m)
    assert r["ok"] and r["inputs"]["vol_how"] == {"model": "elle vol"} and r["ccy"] == "TRY"


def test_check_says_what_is_wrong():
    m = hand_market(cal={"TRY": {D(2026, 11, 9)}})
    td = TODAY.isoformat()
    cases = [
        ({"product": "swap"}, "ürün bilinmiyor"),
        (ois(side="long", price=40.0, tenor="2Y"), "yön anlaşılamadı"),
        (ois(notional=0, price=40.0, tenor="2Y"), "nominal pozitif"),
        (ois(price=40.0), "bitiş tarihi ya da vadesi gerekli"),
        (ois(tenor="2Y"), "fiyat (sabit faiz %) gerekli"),
        (ois(price=40.0, tenor="2Y", trade_date=None), "işlem tarihi gerekli"),
        (ois(price=40.0, tenor="2Y", settle_date="2026-11-02"), "işlem tarihinden önce"),
        (ois(price=40.0, end_date="2026-11-09", settle_date="2026-11-04"), "iş günü değil"),
        (ois(price=40.0, tenor="2X"), "vadesi anlaşılamadı"),
        (ois(price=40.0, end_date="2026-11-04"), "bitiş başlangıçtan sonra"),
        (ois(structure="fra", fra="6x3", price=40.0), "FRA'nın bitişi"),
        (ois(structure="spread", legs=[{"tenor": "2Y", "side": "receive", "notional": N, "price": 40}]), "2 bacak"),
        (ois(structure="fly", legs=[{"tenor": t, "side": "pay", "notional": N, "price": 40} for t in ("1Y", "2Y", "5Y")]),
         "kanatlar aynı"),
        (ois(structure="mpc", price=40.0), "toplantı tarihi"),
        ({"product": "dibs", "isin": "TRT010199T11", "side": "B", "notional": 1e6, "price": 99, "trade_date": td}, "kâğıt bilinmiyor"),
        ({"product": "dibs", "isin": "TRT150328T24", "side": "B", "notional": 1e6, "trade_date": td}, "fiyat (temiz) ya da getiri"),
        ({"product": "dibs", "isin": "TRT150328T24", "side": "receive", "notional": 1e6, "price": 99, "trade_date": td}, "yön"),
        ({"product": "fxspot", "pair": "USDXYZ", "side": "B", "notional": 1e6, "price": 1, "trade_date": td}, "fiyatlanamıyor"),
        ({"product": "fxspot", "pair": "USD", "side": "B", "notional": 1e6, "price": 1, "trade_date": td}, "parite anlaşılamadı"),
        ({"product": "fxspot", "pair": "EURUSD", "side": "B", "notional": 1e6, "notional_ccy": "GBP", "price": 1.1,
          "trade_date": td}, "nominal dövizi"),
        ({"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": 1, "trade_date": td, "strike": 44,
          "expiry": "2027-02-03"}, "call / put"),
        ({"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": 1, "trade_date": td, "call_put": "call",
          "strike": 44, "expiry": "2026-11-02"}, "vade işlem tarihinden sonra"),
        ({"product": "fxopt", "pair": "USDTRY", "side": "B", "notional": 1e6, "price": -1, "trade_date": td, "call_put": "call",
          "strike": 44, "expiry": "2027-02-03"}, "prim eksi"),
    ]
    for trade, why in cases:
        with pytest.raises(ValueError) as e:
            tv.check(trade, m)
        assert why in str(e.value), (trade, str(e.value))
    # what check() normalises: a tenor to its end, Turkish numbers and amounts, sides, the desk's settlement
    t = tv.check({"product": "ois", "side": "Rec", "notional": "100m", "price": "38,45", "tenor": "2y", "trade_date": "3.11.2026"}, m)
    assert (t["side"], t["notional"], t["price"], t["trade_date"], t["settle_date"], t["end_date"], t["tenor_months"]) == \
        ("S", 100e6, 38.45, "2026-11-03", "2026-11-04", "2028-11-06", 24)
    t = tv.check({"product": "fxopt", "pair": "usd/try", "side": "al", "notional": "1mn", "price": 250000, "trade_date": td,
                  "call_put": "C", "strike": "44,5", "tenor": "3M"}, m)
    assert (t["pair"], t["side"], t["call_put"], t["strike"], t["premium_ccy"], t["premium_date"]) == \
        ("USDTRY", "B", "call", 44.5, "TRY", "2026-11-04")
    assert t["delivery"] == "2027-02-04" and t["expiry"] == "2027-02-03"
    # a stored trade whose settlement became a holiday later is still valued (only a new one is refused)
    stored = ois(price=40.0, tenor="2Y", settle_date="2026-11-09", trade_date="2026-11-03")
    with pytest.raises(ValueError):
        tv.check(stored, m)
    assert tv.value(stored, m)["ok"]


# ---------------------------------------------------------------------------------------------- defaults and DV01
def test_defaults_on_the_desks_holiday_lists():
    thu = D(2026, 11, 5)
    cal = {"TRY": {D(2026, 11, 6)}, "SIFMA": {D(2026, 11, 6)}, "USD": {D(2026, 11, 9), D(2027, 2, 5)}, "EUR": {D(2026, 11, 6)}}
    m = hand_market(cal=cal)
    d = tv.defaults("ois", trade_date=thu, mkt_or_svc=m)
    assert d["settle_date"] == "2026-11-09" and d["notional_ccy"] == "TRY" and d["trade_date"] == "2026-11-05"
    assert tv.defaults("sofr", trade_date=thu, mkt_or_svc=m)["settle_date"] == "2026-11-10"
    assert tv.defaults("dibs", trade_date=thu, mkt_or_svc=m, isin="TRT150328T24")["settle_date"] == "2026-11-09"
    assert tv.defaults("dibs", trade_date=thu, mkt_or_svc=m, isin="TRB100227T13")["settle_date"] == "2026-11-05"
    assert tv.defaults("fxspot", "USDTRY", thu, m)["settle_date"] == "2026-11-10"     # TRY Friday, USD Monday
    assert tv.defaults("fxspot", "EURUSD", thu, m)["settle_date"] == "2026-11-11"     # EUR Friday, USD Monday: T+2
    assert tv.defaults("fxspot", "EURTRY", thu, m)["settle_date"] == "2026-11-10"     # TRY / EUR Friday: Mon, Tue
    assert tv.defaults("fxspot", "USDJPY", thu, m)["notional_ccy"] == "USD"
    opt = tv.defaults("fxopt", "USDTRY", TODAY, m, expiry="2027-02-04")
    assert (opt["delivery"], opt["premium_ccy"], opt["premium_date"]) == ("2027-02-08", "TRY", "2026-11-04")
    assert tv.defaults("fxopt", "EURUSD", TODAY, m, expiry="2027-02-03")["delivery"] == "2027-02-08"
    fra = tv.defaults("ois", trade_date=TODAY, mkt_or_svc=m, fra="3x6")
    assert (fra["value_date"], fra["end_date"]) == ("2027-02-04", "2027-05-04")
    assert tv.defaults("ois", trade_date=TODAY, mkt_or_svc=m, tenor="2Y")["end_date"] == "2028-11-06"
    assert tv.defaults("ois", mkt_or_svc=m)["weights"]["fly"]["weights"] == [0.5, 1.0, 0.5]
    periods = tv.defaults("ois", mkt_or_svc=m)["mpc_periods"]
    assert [p["mpc_date"] for p in periods] == ["2026-12-10", "2027-01-21"]
    assert periods[0]["value_date"] == "2026-12-11" and periods[0]["label"] == "MPC 11.12.26–22.01.27"


def test_notional_for_a_dv01():
    m = hand_market()
    m.curves["ois"] = bootstrap(m.spot_date("ois"), QUOTES)
    t = ois(tenor="2Y")
    a = tv.value(dict(t, price=34.5), m)["inputs"]["annuity"]
    res = tv.notional_for_dv01(t, 1000, "USD", m)
    raw = 1000 * 42.0 / (a * 1e-4)
    assert abs(res["raw"] - raw) < 1e-6 and res["notional"] == round(raw / 5e6) * 5e6
    assert abs(res["dv01_check"] - res["notional"] * a * 1e-4 / 42.0) < 1e-9
    assert abs(res["dv01_check"] - 1000) <= 5e6 * a * 1e-4 / 42.0 / 2 + 1e-9
    assert tv.notional_for_dv01(t, "42.000", "TL", m)["notional"] == res["notional"]         # TL at USDTRY 42
    assert tv.notional_for_dv01(t, 1, "USD", m)["notional"] == 5e6                           # never under a lot
    s = tv.notional_for_dv01({"product": "sofr", "tenor": "2Y", "trade_date": TODAY.isoformat()}, 42000, "TL", m)
    assert s["ccy"] == "USD" and abs(s["dv01_check"] - 42000) < 5e6 * 2 * 1e-4 * 42 / 2
    b = tv.notional_for_dv01({"product": "dibs", "isin": "TRT150328T24"}, 1000, "USD", m)
    assert abs(b["raw"] - 1000 * 42.0 / (101.766 / 1e6)) < 1e-6 and b["notional"] % 5e6 == 0
    # entered as a DV01: check() sizes it the same way (a swap, a bond)
    assert tv.check(ois(price=34.5, tenor="2Y", notional=None, dv01=1000), m)["notional"] == res["notional"]
    assert tv.check({"product": "dibs", "isin": "TRT150328T24", "side": "B", "price": 100.0, "dv01": 1000, "trade_date": TODAY.isoformat()},
                    m)["notional"] == b["notional"]
    pkg = tv.notional_for_dv01(ois(structure="fly", legs=[{"tenor": "1Y"}, {"tenor": "2Y"}, {"tenor": "5Y"}]), 1000, "USD", m)
    assert [round(lg["dv01_check"], 0) > 0 for lg in pkg["legs"]] == [True] * 3
    assert abs(pkg["legs"][0]["raw"] * 2 - tv.notional_for_dv01(ois(tenor="1Y"), 1000, "USD", m)["raw"]) < 1e-6
    with pytest.raises(ValueError):
        tv.notional_for_dv01({"product": "fxspot", "pair": "USDTRY"}, 1000, "USD", m)


# ---------------------------------------------------------------------------------------------- no Bloomberg request
def test_market_asks_bloomberg_nothing(service, tmp_path_factory):
    """``market()`` on a live service with the fake terminal (answering what the workbooks recorded), once the start has
    asked for everything: not one request or subscription more - and a valuation from it neither."""
    import time
    import fake_blpapi
    from helpers import complete_snapshot, server_from_snapshot
    from tto.config import Settings
    from tto.marketdata.bloomberg import BloombergProvider
    from tto.service import Service
    from tto.xl.engine import Clock
    snapshot = complete_snapshot(service)
    today = service.books["tto"].engine.clock.today()
    server = server_from_snapshot(snapshot)
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    provider.start()
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    live = Service(Settings(data_dir=str(tmp_path_factory.mktemp("tv-live")), mode="live", history=False), provider=provider, clock=clock)
    def asked():
        """Every (operation, security, field) the terminal was asked for and every topic subscribed - a key asked again
        on the provider's own schedule (a derived field a minute on) is no new request."""
        keys = {(r["op"], s, f) for r in list(server.requests) for s in r["securities"] for f in (r["fields"] or [""])}
        return keys, {topic for topic, _ in list(server.subscriptions)}

    try:
        for _ in range(10):
            if not live.warmup()["items"]:
                break
        time.sleep(0.3)
        before = asked()
        m = tv.market(live)
        for ten in ("1M", "2Y"):
            assert tv.value(ois(price=m.quotes["ois"][ten], tenor=ten, trade_date=m.today.isoformat()), m)["ok"]
        tv.defaults("ois", mkt_or_svc=live)
        time.sleep(0.5)
        after = asked()
        assert after[0] - before[0] == set() and after[1] - before[1] == set()
        assert m.curves["ois"].ok() and m.curves["sofr"].ok() and m.spots.get("USDTRY")
    finally:
        live.stop()
        provider.stop()
