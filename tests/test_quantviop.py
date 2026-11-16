"""VİOP (tto/quantviop.py): the contracts' tickers and expiries (the VİOP sheet's rules) and the history's series of
them, the implied rate (the sheet's formula) and its inverse, the USD line, the constant maturities, the calendar,
the level model (the reflection principle against a simulation, its inverse, the ladder, the calibration on a
known process), the intraday profile and the 5-minute bars (store, plan, fetch, rates; through the Bloomberg layer on
the fake terminal, with what they cost), the family on a synthetic history with its signal and the calendar's drift
of today and of the week, then the service (the VİOP sheet's twelve contracts in replay), the HTTP API and the page."""
from __future__ import annotations

import datetime as dt
import math
import random
import types

import pytest
from starlette.testclient import TestClient

from conftest import auth
from tto import quantfam as qf
from tto import quantviop as qv
from tto.quant import DEFAULTS, PAGES
from tto.server import create_app

TODAY = dt.date(2026, 11, 3)
HOL = {dt.date(2026, 10, 29), dt.date(2027, 1, 1), dt.date(2027, 10, 29)}


def D(s):
    return dt.date.fromisoformat(s)


# ====================================================================================== contracts
def test_tickers_expiries_and_the_contract_list():
    assert qv.parse_ticker("A1Z6 Curncy") == ("A1", 12, "6", "Curncy") and qv.parse_ticker("USDTRY Curncy") is None
    assert qv.year_of("6", TODAY) == 2026 and qv.year_of("5", TODAY) == 2025 and qv.year_of("4", TODAY) == 2024 and qv.year_of("25", TODAY) == 2025
    assert qv.year_of("7", TODAY) == 2027
    assert qv.contract_ticker("A1", 2025, 11) == "A1X5 Curncy" and qv.contract_ticker("A1", 2025, 11, two=True) == "A1X25 Curncy"
    # the month's last business day ...
    assert qv.expiry_of(2026, 11, HOL) == D("2026-11-30") and qv.expiry_of(2026, 12, HOL) == D("2026-12-31")
    assert qv.expiry_of(2027, 1, HOL) == D("2027-01-29") and qv.expiry_of(2026, 10, HOL) == D("2026-10-30")
    # ... a business day earlier when the next day is Republic Day (Oct 28, 2027 is the last before the long weekend)
    assert qv.expiry_of(2027, 10, HOL) == D("2027-10-27")
    # ... or a Bayram (a holiday on no fixed date); not before New Year's Day or May Day
    bayram = HOL | {D("2027-04-01")}
    assert qv.expiry_of(2027, 3, bayram) == D("2027-03-30") and qv.expiry_of(2027, 4, HOL | {D("2027-05-01")}) == D("2027-04-30")
    cs = qv.contract_list(["A1X6 Curncy", "A1Z6 Curncy", "A1F7 Curncy"], TODAY, months=3)
    assert [c["ticker"] for c in cs] == ["A1X6 Curncy", "A1Z6 Curncy", "A1F7 Curncy", "A1V6 Curncy", "A1U6 Curncy", "A1Q6 Curncy"]
    assert [c["expired"] for c in cs] == [False] * 3 + [True] * 3 and cs[3]["alt"] == "A1V26 Curncy" and cs[2]["name"] == "Oca27"
    specs = qv.contract_specs(["A1X6 Curncy", "A1Z6 Curncy"], TODAY)
    assert len(specs) == 3 * (2 + qv.EXPIRED_MONTHS)
    exp = [s for s in specs if s.get("tail") == "none"]
    assert len(exp) == 3 * qv.EXPIRED_MONTHS and all(s["alts"] and s["backfill"] == "viop" for s in exp)
    assert {s["field"] for s in specs} == {"PX_LAST", "PX_HIGH", "PX_LOW"} and specs[0]["key"] == "VIOPF:A1X6 Curncy"
    assert len(qv.contract_specs(["A1%s%d Curncy" % (c, 6) for c in "XZ"] + ["A1%s7 Curncy" % c for c in "FGHJKM"], TODAY)) == \
        3 * (qv.LISTED_MAX + qv.EXPIRED_MONTHS)                         # (the history keeps the first six listed)


# ====================================================================================== the rates
def test_the_implied_rate_is_the_viop_sheets():
    # ((price / spot)(1 + USD g/360) − 1) 360/g
    want = ((42.9 / 42.0) * (1.0 + 0.04 * 30 / 360.0) - 1.0) * 360.0 / 30 * 100.0
    assert qv.implied(42.9, 42.0, 4.0, 30) == pytest.approx(want, abs=1e-12)
    assert qv.price_of(qv.implied(42.9, 42.0, 4.0, 30), 42.0, 4.0, 30) == pytest.approx(42.9, abs=1e-12)
    assert qv.implied(42.9, 42.0, 4.0, 0) is None and qv.implied(0.0, 42.0, 4.0, 30) is None
    # EK_VIOP's USD line: flat to 30 days, then straight through 91, 182, 365
    a, b, c, d = 4.0, 4.2, 4.5, 5.0
    assert qv.usd_at(10, a, b, c, d) == a and qv.usd_at(60, a, b, c, d) == pytest.approx(a + (b - a) * 30 / 61.0)
    assert qv.usd_at(200, a, b, c, d) == pytest.approx(c + (d - c) * 18 / 183.0) and qv.usd_at(500, a, b, c, d) == d
    assert qv.usd_at(60, a, None, c, d) == pytest.approx(a + (c - a) * 30 / 152.0)          # a missing tenor: its neighbours
    assert qv.curve_at([(30, 40.0), (90, 41.0)], 60) == pytest.approx(40.5) and qv.curve_at([(30, 40.0)], 5) == 40.0


def test_constant_maturities_interpolate_without_extrapolating():
    rows = {"A": [{"day": "2026-10-01", "g": 20, "implied": 40.0, "basis": 100.0, "vs_off": 50.0}],
            "B": [{"day": "2026-10-01", "g": 50, "implied": 43.0, "basis": 130.0, "vs_off": 80.0}]}
    cm = qv.constant_maturity(rows, (30, 91))
    assert cm[30]["2026-10-01"]["implied"] == pytest.approx(41.0) and cm[30]["2026-10-01"]["basis"] == pytest.approx(110.0)
    assert cm[91] == {}                                                   # no contract beyond 50 days: no 91-day point
    assert qv.at_maturity({30: cm[30], 61: {"2026-10-01": {"implied": 44.0, "basis": 140.0}}}, 45.5, "basis")["2026-10-01"] == pytest.approx(125.0)


# ====================================================================================== the calendar
def test_month_end_offsets_and_a_planted_month_end_effect():
    assert qv.month_end_offset(D("2026-11-30"), HOL) == 0 and qv.month_end_offset(D("2026-11-27"), HOL) == -1
    assert qv.month_end_offset(D("2026-12-01"), HOL) == 1 and qv.month_end_offset(D("2026-12-02"), HOL) == 2
    rnd = random.Random(3)
    series, v, d = {}, 100.0, D("2024-01-02")
    while d < D("2026-10-30"):
        if qv._bday(d, HOL):
            v += rnd.gauss(0.0, 2.0) + (12.0 if qv.month_end_offset(d, HOL) == 0 else 0.0) - (12.0 if qv.month_end_offset(d, HOL) == 1 else 0.0)
            series[d.isoformat()] = v
        d += dt.timedelta(days=1)
    eff = qv.calendar_effects(series, HOL)
    me = {r["k"]: r for r in eff["month_end"]}
    assert me[0]["mean"] == pytest.approx(12.0, abs=1.5) and me[0]["t"] > 10 and me[1]["mean"] == pytest.approx(-12.0, abs=1.5)
    assert abs(me[-3]["t"]) < 3 and len(eff["weekday"]) == 5 and eff["n"] > 600
    # the seasonal drift of a week that holds the month end: its significant days only
    week = [D("2026-11-30"), D("2026-12-01"), D("2026-12-02")]
    assert qv.seasonal_drift(eff, week, HOL) == pytest.approx(me[0]["mean"] + me[1]["mean"] + (me[2]["mean"] if abs(me[2]["t"] or 0) >= 2 else 0.0))


# ====================================================================================== the level model
def test_the_reflection_principle_against_a_simulation_and_its_inverse():
    assert qv.p_min_below(10.0, 9.5, 0.0, 0.25) == pytest.approx(2.0 * qv._phi(-1.0), abs=1e-12)      # driftless: 2 Φ((L − x0)/σ)
    rnd = random.Random(1)
    for m in (0.3, -0.3):
        hit = 0
        for _ in range(3000):
            x, lo = 10.0, 10.0
            for _ in range(300):
                x += m / 300 + rnd.gauss(0.0, math.sqrt(0.25 / 300))
                lo = min(lo, x)
            hit += lo <= 9.5
        assert abs(qv.p_min_below(10.0, 9.5, m, 0.25) - hit / 3000.0) < 0.03
    for p in qv.LADDER:
        b, s = qv.level_for(p, 10.0, 0.1, 0.25, "buy"), qv.level_for(p, 10.0, 0.1, 0.25, "sell")
        assert qv.p_min_below(10.0, b, 0.1, 0.25) == pytest.approx(p, abs=1e-6) and qv.p_max_above(10.0, s, 0.1, 0.25) == pytest.approx(p, abs=1e-6)
    lad = qv.ladder(10.0, 0.0, 0.25, "buy")
    assert [r["p"] for r in lad] == list(qv.LADDER) and all(a["level"] > b["level"] for a, b in zip(lad, lad[1:]))   # less likely: lower
    assert qv.ladder(10.0, 0.0, 0.25, "buy", c=2.0)[1]["level"] < lad[1]["level"]                                   # a larger σ: further


def test_the_calibration_finds_a_known_process_calibrated():
    """An OU process the model knows: the week's levels are hit about as often as their probabilities, c near 1;
    a process twice as wild as the trailing σ says (jumps) wants a larger c."""
    rnd = random.Random(7)
    series, fair, x, d = {}, {}, 40.0, D("2024-06-03")
    while len(series) < 500:
        if qv._bday(d, HOL):
            x += 0.05 * (40.0 - x) + rnd.gauss(0.0, 0.2)
            series[d.isoformat()], fair[d.isoformat()] = x, 40.0
        d += dt.timedelta(days=1)
    cal = qv.calibrate(series, fair, -math.log(0.95), HOL)
    assert cal["n"] > 300 and 0.8 <= cal["c"] <= 1.2
    for r in cal["rows"]:
        assert abs(r["buy_fit"] - r["p"]) < 0.12 and abs(r["sell_fit"] - r["p"]) < 0.12
    assert qv.calibrate(dict(list(series.items())[:50]), fair, 0.05, HOL) == {"n": 0, "c": 1.0, "rows": []}


def test_the_profile_and_the_horizons():
    prof = qv.Profile(0.04, {qv.Profile.bucket(10 * 60 + 5): 4.0, qv.Profile.bucket(17 * 60 + 5): 2.0}, overnight=3.0)
    assert sum(prof.step_var) + prof.overnight == pytest.approx(0.04) and prof.shaped
    flat = qv.Profile(0.04)
    assert flat.rest_of_day(qv.SESSION[0]) == pytest.approx(0.04) and flat.rest_of_day(qv.SESSION[1]) == 0.0
    assert flat.day_share_left(14 * 60) == pytest.approx(sum(1 for t in flat.steps if t > 14 * 60) / float(len(flat.steps)))
    wed = dt.datetime(2026, 11, 4, 14, 0)
    v, n, ahead = qv.horizon(flat, wed, HOL, "today")
    assert v == pytest.approx(flat.rest_of_day(14 * 60)) and ahead == []
    v2, n2, ahead2 = qv.horizon(flat, wed, HOL, "week")
    assert ahead2 == [D("2026-11-05"), D("2026-11-06")] and v2 == pytest.approx(v + 2 * 0.04) and n2 == pytest.approx(n + 2)
    assert qv.horizon(flat, dt.datetime(2026, 11, 4, 19, 0), HOL, "today")[0] == 0.0                  # the session is over
    assert qv.week_days_left(D("2026-11-07"), HOL)[-1] == D("2026-11-13")                          # a Saturday: next week's


# ====================================================================================== the bars
def _bars(day, base, step, seed):
    rnd = random.Random(seed)
    out, x = [], base
    for i in range(102):
        t = dt.datetime.combine(D(day), dt.time(9, 30)) + dt.timedelta(minutes=5 * i)
        o = x
        x += rnd.gauss(0.0, step)
        out.append((t.strftime("%Y-%m-%d %H:%M"), o, max(o, x) + step / 2, min(o, x) - step / 2, x, 10.0))
    return out


def test_the_bar_store_the_plan_and_the_fetch(tmp_path):
    st = qv.BarStore(str(tmp_path / "b.sqlite3"))
    assert st.put("A1Z6 Curncy|TRADE", "2026-11-02", _bars("2026-11-02", 43.0, 0.01, 1)) == 102
    assert st.put("A1Z6 Curncy|TRADE", "2026-10-30", []) == 0                      # an empty day is remembered too
    assert st.asked() == {"A1Z6 Curncy|TRADE": {"2026-11-02": 102, "2026-10-30": 0}} and len(st.load("A1Z6 Curncy|TRADE", "2026-11-02")) == 102
    days = qv.bar_days(TODAY, HOL, 3)
    assert days == ["2026-10-28", "2026-10-30", "2026-11-02"]                         # (Oct 29 a holiday)
    plan = qv.bar_plan(["A1Z6 Curncy"], days, st.asked())
    assert plan[0][3] == "2026-11-02" and ("A1Z6 Curncy|TRADE", "A1Z6 Curncy", "TRADE", "2026-11-02") not in plan
    assert ("USDTRY Curncy|BID", "USDTRY Curncy", "BID", "2026-11-02") in plan and len(plan) == 3 * 3 - 2
    st.prune("2026-11-01")
    assert st.asked() == {"A1Z6 Curncy|TRADE": {"2026-11-02": 102}}
    st.close()
    # the fetch: live, a few at a time, an answer that does not come stops it; replay asks nothing
    calls = []

    def bars(sec, start, end, interval, event, timeout):
        calls.append((sec, start, end, interval, event))
        return [] if len(calls) < 3 else None

    svc = types.SimpleNamespace(mode="live", provider=types.SimpleNamespace(intraday_bars=bars), settings=types.SimpleNamespace(data_dir=str(tmp_path)))
    quant = types.SimpleNamespace(svc=svc)
    out = qv.fetch_bars(quant, ["A1Z6 Curncy"], TODAY, HOL, limit=4)
    assert out["asked"] == 2 and "yanıt" in out["why"] and calls[0][1:] == ("2026-11-02 09:30", "2026-11-02 18:20", 5, "TRADE")
    svc.mode = "replay"
    assert qv.fetch_bars(quant, ["A1Z6 Curncy"], TODAY, HOL)["why"] == "kayıtlı veri modu" and len(calls) == 3
    quant._viop_bars.close()


def test_the_bars_on_the_fake_terminal_and_what_they_cost(tmp_path):
    """The 5-minute bars through the Bloomberg layer (``provider.intraday_bars``, the fake terminal's 09:30 - 18:00
    bars): the two front contracts' trades and USDTRY's bid and ask for the last 20 business days - 80 requests, one
    hit each, four a minute's refresh, every day once; the next day four (the day that ended), the oldest day dropped;
    the bars give a day's implied rates, a profile and its calibration."""
    import fake_blpapi
    from tto.marketdata.bloomberg import BloombergProvider
    server = fake_blpapi.Server()
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    provider.start()
    try:
        svc = types.SimpleNamespace(mode="live", provider=provider, settings=types.SimpleNamespace(data_dir=str(tmp_path)))
        quant = types.SimpleNamespace(svc=svc)
        fronts = ["A1X6 Curncy", "A1Z6 Curncy"]
        rounds = []
        for _ in range(30):                                                # a minute's refresh each
            out = qv.fetch_bars(quant, fronts, TODAY, HOL)
            if not out["asked"]:
                break
            rounds.append(out)
        asked = [r for r in server.requests if r["op"] == "IntradayBarRequest"]
        days = qv.bar_days(TODAY, HOL)
        hits = provider.status()["hits_today"]
        assert [r["asked"] for r in rounds] == [qv.BAR_PER_REFRESH] * 20 and len(asked) == 80 == 4 * len(days)
        assert hits == server.hits() == 80                                                             # one hit a request
        assert sorted({(r["securities"][0], r["options"]["eventType"]) for r in asked}) == [
            ("A1X6 Curncy", "TRADE"), ("A1Z6 Curncy", "TRADE"), ("USDTRY Curncy", "ASK"), ("USDTRY Curncy", "BID")]
        store = quant._viop_bars
        per_day = 102                                                      # 09:30 - 18:00: the fake terminal's session
        assert sum(r["bars"] for r in rounds) == 80 * per_day and {n for k in store.asked().values() for n in k.values()} == {per_day}
        g = qv.days_to(qv.expiry_of(2026, 11, HOL), days[-1], HOL)
        rates = {d: qv.bar_rates(store, "A1X6 Curncy", d, 4.0, g) for d in days}
        assert all(len(r) == per_day for r in rates.values())
        prof = qv.intraday_profile(rates)
        assert prof["days"] == 20 and [r["from"] for r in prof["shape"]] == list(range(9 * 60 + 30, 18 * 60, 30))      # the half hours 09:30 … 17:30
        assert qv.intraday_calibration(rates, qv.Profile(0.01, prof["buckets"], prof["overnight"]))["n"] == 20
        # the next day: only the day that ended, four requests; the oldest day leaves the store
        nxt = qv.fetch_bars(quant, fronts, TODAY + dt.timedelta(days=1), HOL)
        hits1 = provider.status()["hits_today"] - hits
        assert (nxt["asked"], nxt["bars"], hits1) == (4, 4 * per_day, 4) and qv.fetch_bars(quant, fronts, TODAY + dt.timedelta(days=1), HOL)["asked"] == 0
        assert min(min(k) for k in store.asked().values()) == qv.bar_days(TODAY + dt.timedelta(days=1), HOL)[0] > days[0]
        print("bars: %d requests, %d hits, %d bars the first time (%d refreshes of four), then %d requests (%d hits) a day"
              % (len(asked), hits, sum(r["bars"] for r in rounds), len(rounds), nxt["asked"], hits1))
        store.close()
    finally:
        provider.stop()


def test_bar_rates_the_intraday_profile_and_its_calibration(tmp_path):
    st = qv.BarStore(str(tmp_path / "b.sqlite3"))
    days = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-30", "2026-11-02"]
    for k, day in enumerate(days):
        st.put("A1Z6 Curncy|TRADE", day, _bars(day, 43.2, 0.004, k))
        st.put("USDTRY Curncy|BID", day, _bars(day, 42.0, 0.003, 100 + k))
        st.put("USDTRY Curncy|ASK", day, [(t, o + 0.002, h + 0.002, l + 0.002, c + 0.002, v) for t, o, h, l, c, v in _bars(day, 42.0, 0.003, 100 + k)])
    rates = {day: qv.bar_rates(st, "A1Z6 Curncy", day, 4.0, 59) for day in days}
    t, c, lo, hi = rates["2026-11-02"][10]
    assert len(rates["2026-11-02"]) == 102 and lo <= c <= hi
    f = {x[0]: x for x in st.load("A1Z6 Curncy|TRADE", "2026-11-02")}[t]
    b = {x[0]: x for x in st.load("USDTRY Curncy|BID", "2026-11-02")}[t]
    assert c == pytest.approx(qv.implied(f[4], b[4] + 0.001, 4.0, 59))
    prof = qv.intraday_profile(rates)
    assert prof["days"] == 5 and prof["buckets"] and prof["overnight"] > 0 and {r["day"] for r in prof["ranges"]} == set(days)
    cal = qv.intraday_calibration(rates, qv.Profile(0.01, prof["buckets"], prof["overnight"]))
    assert cal["n"] == 5 and [r["p"] for r in cal["rows"]] == list(qv.LADDER)
    st.close()


# ====================================================================================== the family
TENORS = (("1M", 1.0), ("2M", 2.0), ("3M", 3.0), ("6M", 6.0), ("9M", 9.0), ("1Y", 12.0))


def _ois_at(level, g):
    """The synthetic OIS curve (level + 0,1 a month) at g days, as the module reads a curve: straight lines in days
    between the tenors, flat beyond them."""
    return qv.curve_at([(qv._tenor_days(m), level + 0.1 * m) for _, m in TENORS], g)


def _history(n=300, seed=5):
    """A synthetic history: four expired and three listed contracts, spot, the USD and TRY OIS curves, offshore."""
    rnd = random.Random(seed)
    days, d = [], TODAY
    while len(days) < n:
        d -= dt.timedelta(days=1)
        if qv._bday(d, HOL):
            days.append(d.isoformat())
    days = days[::-1]
    series, meta = {}, {}
    spot, ois, basis = {}, {}, {}
    s, o, b = 40.0, 40.0, 150.0
    for day in days:
        s *= math.exp(rnd.gauss(0.0, 0.004))
        o += rnd.gauss(0.0, 0.05)
        b += 0.1 * (150.0 - b) + rnd.gauss(0.0, 8.0)
        spot[day], ois[day], basis[day] = s, o, b
    series["FX:USDTRY"] = dict(spot)
    meta["FX:USDTRY"] = {"label": "USDTRY", "kind": "fx", "group": "TRY"}
    for k, _, _, label in qv.USD_KEYS:
        series[k] = {day: 4.0 for day in days}
        meta[k] = {"label": label, "kind": "rate", "group": "Global"}
    for label, months in (("1M", 1.0), ("2M", 2.0), ("3M", 3.0), ("6M", 6.0), ("9M", 9.0), ("1Y", 12.0)):
        series["OIS:" + label] = {day: ois[day] + 0.1 * months for day in days}
        meta["OIS:" + label] = {"label": label + " OIS", "kind": "rate", "months": months, "group": "ois"}
        series["OFF:" + label] = {day: ois[day] + 1.0 for day in days}
        meta["OFF:" + label] = {"label": "Offshore " + label, "kind": "rate", "months": months, "group": "off"}
    contracts = [(2026, m) for m in range(5, 11)] + [(2026, 11), (2026, 12), (2027, 1)]
    for year, month in contracts:
        t = qv.contract_ticker("A1", year, month)
        exp = qv.expiry_of(year, month, HOL)
        closes = {}
        for day in days:
            g = qv.days_to(exp, day, HOL)
            if g <= 0 or g > 200:
                continue
            rate = _ois_at(ois[day], g) * 360.0 / 365.0 + basis[day] / 100.0          # OIS at g (ACT/360) + the spread
            closes[day] = qv.price_of(rate, spot[day], 4.0, g)
        series["VIOPF:" + t] = closes
        series["VIOPH:" + t] = {day: v * 1.001 for day, v in closes.items()}
        series["VIOPL:" + t] = {day: v * 0.999 for day, v in closes.items()}
        meta["VIOPF:" + t] = {"label": "VİOP", "kind": "px", "group": "VİOP", "ticker": t}
    return days, series, meta, spot, ois, basis


def _live(series, ois_now, basis_now, spot_now):
    live = {"FX:USDTRY": spot_now}
    for label, months in (("1M", 1.0), ("2M", 2.0), ("3M", 3.0), ("6M", 6.0), ("9M", 9.0), ("1Y", 12.0)):
        live["OIS:" + label] = ois_now + 0.1 * months
        live["OFF:" + label] = ois_now + 1.0
    rows = []
    for year, month in ((2026, 11), (2026, 12), (2027, 1)):
        t = qv.contract_ticker("A1", year, month)
        exp = qv.expiry_of(year, month, HOL)
        g = qv.days_to(exp, TODAY.isoformat(), HOL)
        mid = _ois_at(ois_now, g) * 360.0 / 365.0 + basis_now / 100.0
        rows.append({"ticker": t, "expiry": exp.isoformat(), "g_bid": float(g), "spot": spot_now, "usd": 4.0, "i_bid": mid - 0.05,
                     "i_ask": mid + 0.05, "bid": qv.price_of(mid - 0.05, spot_now, 4.0, g), "ask": qv.price_of(mid + 0.05, spot_now, 4.0, g)})
    eng = {"viopq": rows}
    live.update(qv.live_values(eng))
    return live, eng


def test_the_family_on_a_synthetic_history_and_its_signal():
    days, series, meta, spot, ois, basis = _history()
    live, eng = _live(series, ois[days[-1]], 150.0 - 60.0, spot[days[-1]])           # the spread 60 bp under its normal
    ctx = qf.Ctx(dict(DEFAULTS), TODAY, series, meta, live=live, holidays=HOL)
    mons, tab = qv.fam_viop(ctx, eng)
    assert tab["ok"] and {r["ticker"] for r in tab["history"] if not r["expired"]} == {"A1X6 Curncy", "A1Z6 Curncy", "A1F7 Curncy"}
    assert all(int(tab["cm"][k]) > 100 for k in ("30", "61", "91"))
    # the implied spreads the history gives back are the planted ones
    cur = qv.Curves(ctx)
    c = next(x for x in qv.contracts_of(ctx, eng) if x.ticker == "A1X6 Curncy")
    r = qv.contract_rates(c, cur, HOL)[-1]
    assert r["basis"] == pytest.approx(basis[r["day"]], abs=1.0)
    front = next(m for m in mons if m.sid == "viop:A1X6 Curncy")
    front.score(live, live)
    assert front.level == pytest.approx(90.0, abs=2.0) and front.z < -2.0
    s = qf.make_signal(front, ctx.cfg, "10:00")
    assert s["family"] == "viop" and s["page"] == "quant-viop" and s["expression"].startswith("Buy VİOP Kas26") and "Sell USDTRY spot" in s["expression"]
    assert "kontrat" in s["legs"][0]["name"] and s["legs"][0]["dv01_usd"] == pytest.approx(1000.0)
    built = tab["_build"](live, dt.datetime(2026, 11, 3, 11, 0))
    row = next(x for x in built["rows"] if x["ticker"] == "A1X6 Curncy")
    assert row["basis"] == pytest.approx(90.0, abs=2.0) and row["fair"] > row["mid"]                     # cheap: fair above
    for which in ("today", "week"):
        part = row[which]
        buy, sell = part["buy"], part["sell"]
        assert all(b["level"] <= row["ask"] + 1e-9 for b in buy) and all(x["level"] >= row["bid"] - 1e-9 for x in sell)
        assert all(a["level"] >= b["level"] for a, b in zip(buy, buy[1:])) and buy[0]["price"] < row["px_ask"] + 1e-9
    assert row["week"]["drift_bp"] > 0 and row["week"]["var"] > row["today"]["var"]                     # pulled up toward fair
    assert row["size"]["contracts"] > 0 and row["size"]["try_mn"] > 0


def test_the_calendar_drift_of_today_and_of_the_week(monkeypatch):
    """The calendar's part of the drift: today's effect for the share of its session still ahead - in the week's
    horizon too, which holds the rest of today - and every whole day ahead in full; none of today once it is over."""
    days, series, meta, spot, ois, basis = _history()
    live, eng = _live(series, ois[days[-1]], 150.0 - 60.0, spot[days[-1]])
    _, tab = qv.fam_viop(qf.Ctx(dict(DEFAULTS), TODAY, series, meta, live=live, holidays=HOL), eng)
    monkeypatch.setattr(qv, "seasonal_drift", lambda effects, days, holidays, t_min=2.0: 10.0 * len(days))      # 10 bp a day
    for hour, share in ((14, None), (19, 0.0)):                          # a Wednesday: Thursday and Friday ahead
        row = next(x for x in tab["_build"](live, dt.datetime(2026, 11, 4, hour, 0))["rows"] if x["ticker"] == "A1X6 Curncy")
        left = row["today"]["days"]
        assert (0.0 < left < 1.0) if share is None else left == share
        assert row["today"]["season_bp"] == pytest.approx(10.0 * left) and row["week"]["season_bp"] == pytest.approx(10.0 * (left + 2))


# ====================================================================================== the service
def test_the_page_in_replay_and_over_http(module_service):
    svc = module_service
    assert ("quant-viop", "VİOP") in PAGES
    svc.quant.compute()
    user = svc.login("vi̇op okuyucu")["user"]
    v = svc.quant.view("viop", user, {})
    assert "viop" in v and v["mode"] == "replay" and "viop" not in (v.get("errors") or {})
    # the VİOP sheet's twelve contracts (tickers L1:W1, numbers M:X) with the TRY rates their live bid and ask imply - the
    # sheet's rows 13 and 25 -; replay has no Bloomberg history of them: no fair value, no levels
    rows = v["viop"]["live"]["rows"]
    assert len(rows) == 12 and (rows[0]["ticker"], rows[0]["expiry"], rows[0]["g"]) == ("A1X6 Curncy", "2026-11-30", 26)
    assert (rows[-1]["ticker"], rows[-1]["name"], rows[-1]["expiry"]) == ("A1V7 Curncy", "Eki27", "2027-10-27")
    assert rows[0]["bid"] == pytest.approx(33.5815, abs=1e-4) and rows[0]["ask"] == pytest.approx(33.8315, abs=1e-4)
    assert all(r["bid"] < r["ask"] and r.get("fair") is None and not r.get("today") for r in rows)
    with TestClient(create_app(svc), headers=auth(svc, "VİOP HTTP")) as client:
        r = client.get("/api/quant/viop")
        assert r.status_code == 200 and r.json()["ready"] and "viop" in r.json()
        assert client.get("/static/js/pages/quantviop.js").status_code == 200
        nav = client.get("/api/nav").json()["pages"]
        assert "quant-viop" in [p["id"] for p in nav if p["group"] == "Quant"]


def test_before_bloombergs_history_the_viop_sheets_own_days_serve():
    """The first live day, before the contracts' history is in: the VİOP history sheet's days of its drawn contracts
    (EK_VIOP: implied rate, days, its spread) give the fair value and the levels at once."""
    days, series, meta, spot, ois, basis = _history()
    live, eng = _live(series, ois[days[-1]], 150.0 - 60.0, spot[days[-1]])
    full = qf.Ctx(dict(DEFAULTS), TODAY, series, meta, live=live, holidays=HOL)
    cur = qv.Curves(full)
    sheet = []
    for c in qv.contracts_of(full, eng):
        rows = qv.contract_rates(c, cur, HOL)
        if c.expired or not rows:
            continue
        sheet.append({"ticker": c.ticker, "name": c.name, "expiry": c.expiry.isoformat(), "imp": {r["day"]: r["implied"] for r in rows},
                      "days": {r["day"]: r["g"] for r in rows}, "baz": {r["day"]: r["basis"] for r in rows},
                      "ois360": {r["day"]: r["ois"] for r in rows}})
    bare = {k: v for k, v in series.items() if not k.startswith(("VIOPF:", "VIOPH:", "VIOPL:"))}
    ctx = qf.Ctx(dict(DEFAULTS), TODAY, bare, {k: v for k, v in meta.items() if not k.startswith("VIOPF:")}, live=live, holidays=HOL, viop=sheet)
    mons, tab = qv.fam_viop(ctx, eng)
    assert any(m.sid == "viop:A1X6 Curncy" for m in mons)
    row = next(x for x in tab["_build"](live, dt.datetime(2026, 11, 3, 11, 0))["rows"] if x["ticker"] == "A1X6 Curncy")
    assert row["fair"] is not None and row["week"]["buy"] and row["today"]["sell"]
