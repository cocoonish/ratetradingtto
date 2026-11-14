"""Spot / FX and FX Vol İzleme (``tto/fx.py``): ticker names, the pairs' conventions, forwards (USDTRY from the
offshore curve exactly as the Forward page prices it, the others from Bloomberg's points, a TRY cross from its USD
legs), the surface of a pair with its distribution and probability matrix, quotes of one's own, the vol monitor's
statistics (the workbook's macro block), the history of the vols, the desk's own tickers, and the HTTP layer.

The service runs on the workbook's recorded data; the FX quotes are made up by formula and put into the replay
provider (they are not market data)."""
from __future__ import annotations

import datetime as _dt
import math

import pytest

from conftest import auth, cell, make_service
from tto import extras as ex
from tto import fx
from tto.marketdata.base import bdp_key


def usdtry_quotes(tenor):
    """A USDTRY-like surface: calls far richer than puts, the ATM vol rising with the tenor (made up)."""
    atm = {"1W": 3.0, "2W": 4.0, "1M": 5.0, "2M": 7.0, "3M": 9.0, "6M": 12.0, "9M": 14.0, "1Y": 16.0, "18M": 18.0, "2Y": 20.0}[tenor]
    return {"ATM": atm, "RR25": 1.0 + 0.7 * atm, "BF25": 0.15 * atm, "RR10": 2.0 * (1.0 + 0.7 * atm), "BF10": 0.5 * atm}


def eurusd_quotes(tenor):
    months = {"1W": 0.25, "2W": 0.5}.get(tenor) or (12 * int(tenor[:-1]) if tenor.endswith("Y") else int(tenor[:-1]))
    return {"ATM": 6.0 + 0.1 * months, "RR25": -0.4, "BF25": 0.2, "RR10": -0.8, "BF10": 0.6}


def put_quotes(svc, pair, make, source="BGN"):
    for t in fx.TENORS:
        for kind, v in make(t).items():
            svc.provider.set(bdp_key(fx.vol_ticker(pair, kind, t, source), "PX_LAST"), v)


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("fx"))
    put_quotes(s, "USDTRY", usdtry_quotes)
    put_quotes(s, "EURUSD", eurusd_quotes)
    s.provider.set(bdp_key("EURUSD Curncy", "PX_LAST"), 1.10)
    for i, t in enumerate(fx.TENORS):
        tk = fx.points_ticker(s.fx.pair("EURUSD"), t)
        s.provider.set(bdp_key(tk, "PX_LAST"), 10.0 * (i + 1))               # +0.0010 a tenor
        s.provider.set(bdp_key(tk, "FWD_SCALE"), 4.0)
    yield s
    s.stop()


def user(svc, name):
    return svc.login(name)["user"]


# ---------------------------------------------------------------------------------------------- names and conventions
def test_ticker_names_as_bloomberg_has_them():
    assert fx.vol_ticker("USDTRY", "ATM", "1M") == "USDTRYV1M BGN Curncy"
    assert fx.vol_ticker("USDTRY", "RR25", "3M") == "USDTRY25R3M BGN Curncy"
    assert fx.vol_ticker("USDTRY", "BF25", "1Y") == "USDTRY25B1Y BGN Curncy"
    assert fx.vol_ticker("EURUSD", "RR10", "18M", "CMPN") == "EURUSD10R18M CMPN Curncy"
    assert fx.vol_ticker("USDTRY", "ATM", "1M", "") == "USDTRYV1M Curncy"           # the workbook's own spelling
    pairs = {p.code: p for p in fx.PAIRS}
    assert fx.points_ticker(pairs["USDTRY"], "1Y") == "TRY12M Curncy"               # a year in months
    assert fx.points_ticker(pairs["EURUSD"], "1M") == "EUR1M Curncy"
    assert fx.points_ticker(pairs["USDJPY"], "2W") == "JPY2W Curncy"
    assert fx.points_ticker(pairs["EURJPY"], "1M") == "EURJPY1M Curncy"             # a cross: the pair itself
    assert fx.spot_ticker(pairs["GBPUSD"]) == "GBPUSD Curncy"


def test_the_pairs_and_their_conventions():
    pairs = {p.code: p for p in fx.PAIRS}
    assert list(pairs)[:2] == ["USDTRY", "EURTRY"]
    assert {c for c, p in pairs.items() if p.group == "G10"} == {"EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
                                                                "USDNOK", "USDSEK"}
    t = pairs["USDTRY"]
    assert t.premium and not t.spot_delta("1W") and not t.spot_delta("1M")        # premium-adjusted forward deltas throughout
    e = pairs["EURUSD"]
    assert not e.premium and e.spot_delta("1Y") and not e.spot_delta("18M")       # spot deltas up to a year
    assert pairs["USDJPY"].premium and pairs["EURJPY"].premium and pairs["EURGBP"].premium
    assert pairs["USDJPY"].scale == 2 and pairs["EURUSD"].scale == 4
    assert "primli" in fx.convention_text(t) and "forward" in fx.convention_text(t)


# ---------------------------------------------------------------------------------------------- forwards
def test_usdtry_forward_is_the_forward_pages_offshore_forward(svc):
    """Each tenor's forward is the one the free forward list prices with the offshore curve to that tenor's date."""
    u = user(svc, "FX Forward")
    cur = svc.fx.curve(u, svc.fx.pair("USDTRY"))
    assert cur["source"] == "offshore" and cur["spot"] == cell(svc, "EK_FWD!F%d" % (ex.FR_USD + 1))
    r = ex.FR_LIST + 3                                                   # the first row of the free forward list
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % (ex.FR_LIST + 1), "value": "Offshore"}])
    seen = 0
    for i, (label, _, _) in enumerate(ex.FR_TENORS):
        row = cur["tenors"][label]
        tenor_row = ex.FR_TENOR + 3 + i
        assert row["date"] == fx._as_date(cell(svc, "EK_FWD!B%d" % tenor_row)) and row["days"] == cell(svc, "EK_FWD!C%d" % tenor_row)
        if "fwd" not in row:
            continue
        svc.set_inputs(u, "tto", [{"ref": "EK_FWD!C%d" % r, "value": cell(svc, "EK_FWD!B%d" % tenor_row)}])
        assert row["fwd"] == pytest.approx(cell(svc, "EK_FWD!I%d" % r, u), rel=1e-12), label
        seen += 1
    assert seen == len(ex.FR_TENORS)
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!C%d" % r, "value": ""}])


def test_a_typed_spot_moves_the_forwards_of_its_owner_only(svc):
    u = user(svc, "FX Spot Yazan")
    other = user(svc, "FX Spot Bakan")
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!F%d" % (ex.FR_USD + 1), "value": "60"}])
    mine = svc.fx.curve(u, svc.fx.pair("USDTRY"))
    theirs = svc.fx.curve(other, svc.fx.pair("USDTRY"))
    assert mine["spot"] == 60.0 and theirs["spot"] != 60.0
    assert mine["tenors"]["1M"]["fwd"] / theirs["tenors"]["1M"]["fwd"] == pytest.approx(60.0 / theirs["spot"], rel=1e-12)
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!F%d" % (ex.FR_USD + 1), "value": ""}])


def test_other_pairs_take_bloombergs_points_and_a_try_cross_its_usd_legs(svc):
    u = user(svc, "FX Puan")
    eur = svc.fx.curve(u, svc.fx.pair("EURUSD"))
    assert eur["source"] == "bbg" and eur["spot"] == 1.10
    assert eur["tenors"]["1M"]["fwd"] == pytest.approx(1.10 + 30.0 / 10000)
    assert eur["tenors"]["1M"]["ticker"] == "EUR1M Curncy"
    spot_date = _dt.date.fromisoformat(svc.fx.quotes(u, svc.fx.pair("EURUSD"))["spot_date"])
    assert spot_date.weekday() < 5 and spot_date > svc.fx.today()
    assert eur["tenors"]["1M"]["date"] == fx.delivery(spot_date, "1M")
    cross = svc.fx.curve(u, svc.fx.pair("EURTRY"))
    usd = svc.fx.curve(u, svc.fx.pair("USDTRY"))
    assert cross["source"] == "cross" and cross["legs"] == ["EURUSD", "USDTRY"]
    assert cross["spot"] == pytest.approx(1.10 * usd["spot"])
    assert cross["tenors"]["3M"]["fwd"] == pytest.approx(eur["tenors"]["3M"]["fwd"] * usd["tenors"]["3M"]["fwd"])
    jpy = svc.fx.curve(u, svc.fx.pair("USDJPY"))
    assert "fwd" not in jpy["tenors"]["1M"] and jpy["tenors"]["1M"]["why"] == "veri yok"     # nothing put in: no forward


def test_delivery_dates():
    fri = _dt.date(2026, 11, 13)
    assert fx.add_week_days(fri, 2) == _dt.date(2026, 11, 17)
    assert fx.delivery(_dt.date(2026, 11, 17), "1W") == _dt.date(2026, 11, 24)
    assert fx.delivery(_dt.date(2026, 1, 31), "1M") == _dt.date(2026, 3, 2)                 # Feb 28 is a Saturday
    assert fx.delivery(_dt.date(2026, 11, 17), "1Y") == _dt.date(2027, 11, 17)


# ---------------------------------------------------------------------------------------------- the surface
def test_usdtry_surface_smile_distribution_and_matrix(svc):
    u = user(svc, "FX Yüzey")
    res = svc.fx_surface(u, "USDTRY", "svi", [45, 50, 55, 60, 70])
    assert res["pair"] == "USDTRY" and res["forward_source"] == "offshore" and res["model"] == "svi"
    rows = {r["tenor"]: r for r in res["rows"]}
    assert list(rows) == list(fx.TENORS)
    for t, r in rows.items():
        assert r["ATM"] == usdtry_quotes(t)["ATM"] and r["ATM_ticker"] == "USDTRYV%s BGN Curncy" % t
        assert "error" not in r, (t, r.get("error"))
        assert not r["check"]["arbitrage"] and abs(r["check"]["mean_error"]) < (1e-4 if t not in ("18M", "2Y") else 1e-3), t
        assert r["delta"] == "forward" and r["df"] == 1.0                    # USDTRY: forward deltas at every tenor
        # (made-up quotes need not be free of arbitrage among themselves: the 10-delta ones may be missed by a vol point)
        assert abs(r["fit"]["ATM"]) < 0.05 and max(abs(r["fit"][k]) for k in ("RR25", "BF25")) < 0.5, (t, r["fit"])
        qs = [r["q"]["%g" % p] for p in res["quantiles"]]
        assert all(b > a for a, b in zip(qs, qs[1:]))
        assert qs[0] < r["fwd"] < qs[-1]
    # skew: the 99th percentile further above the median than the 1st below it
    one = rows["1Y"]["q"]
    assert one["0.99"] - one["0.5"] > 1.5 * (one["0.5"] - one["0.01"])
    assert res["levels"] == [45.0, 50.0, 55.0, 60.0, 70.0]
    for m in res["matrix"]:
        a = m["above"]
        assert all(0 <= x <= 1 for x in a) and all(y <= x + 1e-12 for x, y in zip(a, a[1:])), m["tenor"]
    # the forward drifts up: the probability of ending above a level grows with the tenor
    by = {m["tenor"]: m["above"] for m in res["matrix"]}
    assert by["1Y"][res["levels"].index(55.0)] > by["1M"][res["levels"].index(55.0)]


def test_automatic_levels_and_other_models(svc):
    u = user(svc, "FX Seviye")
    res = svc.fx_surface(u, "USDTRY", "svi", None)
    lv = res["levels"]
    assert 5 <= len(lv) <= 20 and lv == sorted(lv)
    steps = {round(b - a, 9) for a, b in zip(lv, lv[1:])}
    assert len(steps) == 1                                                       # evenly spaced round levels
    sabr = svc.fx_surface(u, "USDTRY", "sabr", None)
    assert sabr["model"] == "sabr" and sabr["rows"][2]["model"] == "sabr"
    assert sabr["rows"][2]["params"]["rho"] is not None
    assert svc.fx_surface(u, "USDTRY", "nonsense", None)["model"] == "svi"


def test_eurusd_surface_uses_spot_deltas_with_the_rates_of_the_curves(svc):
    u = user(svc, "FX EUR")
    res = svc.fx_surface(u, "EURUSD", "svi", [1.05, 1.10, 1.15])
    rows = {r["tenor"]: r for r in res["rows"]}
    one = rows["1M"]
    assert one["delta"] == "spot" and 0.99 < one["df"] < 1.0                     # EUR's discount factor from F/S·DF(USD)
    assert rows["18M"]["delta"] == "forward" and rows["18M"]["df"] == 1.0
    assert max(abs(v) for v in one["fit"].values()) < 0.001                       # a G10 smile: to the quote
    assert one["points"] == 30.0 and one["fwd"] == pytest.approx(1.103)


def test_quotes_of_ones_own(svc):
    u = user(svc, "FX Elle")
    other = user(svc, "FX Başkası")
    svc.fx_override(u, "USDTRY", "1M", "ATM", 8.0)
    svc.fx_override(u, "USDTRY", "1M", "FWD", 60.0)
    mine = {r["tenor"]: r for r in svc.fx_surface(u, "USDTRY", "svi", [55])["rows"]}
    theirs = {r["tenor"]: r for r in svc.fx_surface(other, "USDTRY", "svi", [55])["rows"]}
    assert mine["1M"]["ATM"] == 8.0 and mine["1M"]["ATM_bbg"] == 5.0 and set(mine["1M"]["own"]) == {"ATM", "FWD"}
    assert mine["1M"]["fwd"] == 60.0 and theirs["1M"]["ATM"] == 5.0 and theirs["1M"]["own"] == []
    svc.fx_override(u, "USDTRY", "1M", "ATM", "")                                  # empty: back to Bloomberg
    assert svc.fx.overrides(u) == {"USDTRY": {"1M": {"FWD": 60.0}}}
    svc.fx_override_clear(u, "USDTRY")
    assert svc.fx.overrides(u) == {}
    from tto.service import ServiceError
    for bad in (("USDTRY", "5Y", "ATM", 1), ("USDTRY", "1M", "XX", 1), ("USDTRY", "1M", "ATM", -1), ("XXXYYY", "1M", "ATM", 1),
                ("USDTRY", "1M", "RR25", "abc")):
        with pytest.raises(ServiceError):
            svc.fx_override(u, *bad)


def test_the_board(svc):
    u = user(svc, "FX Tablo")
    res = svc.fx_board(u)
    rows = {r["pair"]: r for r in res["rows"]}
    assert list(rows)[:2] == ["USDTRY", "EURTRY"] and len(rows) == len(fx.PAIRS)
    t = rows["USDTRY"]
    assert t["spot"] == cell(svc, "EK_FWD!F%d" % (ex.FR_USD + 1)) and t["ATM_1M"] == 5.0 and t["RR25_1M"] == 4.5
    assert t["move_1m"] == pytest.approx(t["spot"] * 0.05 * math.sqrt(30 / 365))
    assert rows["USDJPY"]["spot"] is None and rows["USDJPY"]["spot_why"] == "veri yok"
    assert rows["EURTRY"]["spot"] == pytest.approx(1.10 * t["spot"])            # its USD legs, as the page prices it


# ---------------------------------------------------------------------------------------------- statistics
def _weekdays(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= _dt.timedelta(days=1)
    return out[::-1]


def test_stats_as_the_workbooks_macro_block():
    today = _dt.date(2026, 11, 16)                                      # a Monday: the last close is Friday's
    days = _weekdays(today - _dt.timedelta(days=3), 261)
    closes = {d.isoformat(): 10.0 + 0.01 * i + (0.5 if i % 7 == 0 else 0.0) for i, d in enumerate(days)}
    st = fx.stats(closes, 13.2, today, 250)
    series = [closes[d.isoformat()] for d in fx.closes_axis(today) if d.isoformat() in closes]
    assert st["d1"] == pytest.approx(13.2 - series[-1]) and st["w1"] == pytest.approx(13.2 - series[-5])
    assert st["m1"] == pytest.approx(13.2 - series[-21])
    s3 = series[-63:]
    m3 = sum(s3) / 63
    sd3 = math.sqrt(sum((x - m3) ** 2 for x in s3) / 62)
    assert st["avg3m"] == pytest.approx(m3) and st["z3m"] == pytest.approx((13.2 - m3) / sd3)
    win = series[-250:]
    m = sum(win) / len(win)
    sd = math.sqrt(sum((x - m) ** 2 for x in win) / (len(win) - 1))
    assert st["z"] == pytest.approx((13.2 - m) / sd) and st["window"] == 250
    assert st["pct"] == pytest.approx(sum(1 for x in win if x <= 13.2) / 250)
    assert (st["min"], st["max"]) == (min(win), max(win))
    # no live value: the last close stands in; a gap of a day is filled with the close before it (Fill=P)
    gap = dict(closes)
    gap.pop(days[-1].isoformat())
    st2 = fx.stats(gap, None, today, 63)
    assert st2["last"] == closes[days[-2].isoformat()] and st2["d1"] == 0.0 and st2["window"] == 63
    assert fx.stats({}, 5.0, today)["z"] is None


def test_realized_vol():
    flat = [("2026-01-%02d" % (i + 1), 100.0 * math.exp(0.001 * i)) for i in range(30)]
    rv = fx.realized(flat, 21)
    assert rv[20][1] is None and rv[21][1] == pytest.approx(0.0, abs=1e-9)
    zig = [("d%02d" % i, 100.0 * (1.01 if i % 2 else 1.0)) for i in range(25)]
    r = math.log(1.01)
    rets = [r if i % 2 else -r for i in range(1, 25)][-21:]
    m = sum(rets) / 21
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / 20)
    assert fx.realized(zig, 21)[-1][1] == pytest.approx(sd * math.sqrt(252) * 100)


def test_nice_levels():
    lv = fx.nice_levels(47.3, 71.9, 50.0)
    assert lv[0] <= 47.3 and lv[-1] >= 70 and all(abs((b - a) - (lv[1] - lv[0])) < 1e-9 for a, b in zip(lv, lv[1:]))
    assert fx.nice_levels(1.05, 1.16, 1.10)[1] - fx.nice_levels(1.05, 1.16, 1.10)[0] == pytest.approx(0.01)
    assert fx.nice_levels(40.0, 62.0, 50.0)[1] - fx.nice_levels(40.0, 62.0, 50.0)[0] == pytest.approx(2.0)
    assert fx.nice_levels(5, 1, 3) == []


# ---------------------------------------------------------------------------------------------- the vol monitor
def test_monitor_with_history_and_the_desks_own_tickers(svc):
    u = user(svc, "FX İzleme")
    today = svc.fx.today()
    days = _weekdays(today - _dt.timedelta(days=1), 260)
    tk = fx.vol_ticker("USDTRY", "ATM", "1M")
    svc.store.hist_upsert(fx.series_id(tk), [(d.isoformat(), 4.0 + 0.003 * i) for i, d in enumerate(days)])
    svc.store.hist_upsert(fx.series_id("USDTRY Curncy"), [(d.isoformat(), 40.0 * math.exp(0.0005 * i + (0.002 if i % 2 else 0)))
                                                         for i, d in enumerate(days)])
    res = svc.fx_monitor(u, 250)
    assert res["window"] == 250 and len(res["rows"]) == len(fx.PAIRS)
    c = res["cells"]["USDTRY|ATM|1M"]
    assert c["last"] == 5.0 and c["live"] and c["n"] == 260 and c["pct"] == 1.0 and c["z"] > 1.5
    assert c["d1"] == pytest.approx(5.0 - (4.0 + 0.003 * 259))
    assert res["cells"]["USDTRY|RR25|3M"]["last"] == pytest.approx(1.0 + 0.7 * 9.0) and res["cells"]["USDTRY|RR25|3M"]["n"] == 0
    row = next(r for r in res["rows"] if r["pair"] == "USDTRY")
    assert row["iv1m"] == 5.0 and row["rv1m"] is not None and len(row["spark"]) == 52
    assert svc.fx_monitor(u, "63")["window"] == 63 and svc.fx_monitor(u, "7")["window"] == 250
    # the desk's own: a pair (its vols join every table) and any ticker
    from tto.service import ServiceError
    added = svc.fx_ticker_add(u, "usd/zar")["added"]
    assert added["kind"] == "pair" and added["text"] == "USDZAR"
    with pytest.raises(ServiceError):
        svc.fx_ticker_add(u, "USDZAR")
    with pytest.raises(ServiceError):
        svc.fx_ticker_add(u, "EURUSD")                                           # one of the built-in pairs
    with pytest.raises(ServiceError):
        svc.fx_ticker_add(u, "VIX")                                              # no yellow key
    vix = svc.fx_ticker_add(u, "vix index", "Korku endeksi")["added"]
    assert vix["text"] == "VIX Index" and vix["label"] == "Korku endeksi"
    svc.provider.set(bdp_key("VIX Index", "PX_LAST"), 17.5)
    res = svc.fx_monitor(u, 250)
    assert [p["code"] for p in res["pairs"]][-1] == "USDZAR" and res["pairs"][-1]["added"]
    assert "USDZAR|ATM|1M" in res["cells"] and res["cells"]["USDZAR|ATM|1M"]["ticker"] == "USDZARV1M BGN Curncy"
    own = res["own"][0]
    assert own["ticker"] == "VIX Index" and own["last"] == 17.5 and own["label"] == "Korku endeksi"
    assert svc.fx.pair("USDZAR").premium and svc.fx.pair("USDZAR").spot_until == 0.0      # an EM pair
    svc.fx_ticker_remove(u, added["id"])
    svc.fx_ticker_remove(u, vix["id"])
    assert svc.fx_tickers(u)["items"] == []
    with pytest.raises(ServiceError):
        svc.fx_ticker_remove(u, "nope")


def test_the_pricing_source_is_the_desks(svc):
    u = user(svc, "FX Kaynak")
    from tto.service import ServiceError
    assert svc.fx_tickers(u)["settings"]["source"] == "BGN"
    svc.fx_set_settings(u, "cmpn")
    try:
        assert svc.fx.quotes(u, svc.fx.pair("USDTRY"))["rows"][2]["ATM_ticker"] == "USDTRYV1M CMPN Curncy"
        with pytest.raises(ServiceError):
            svc.fx_set_settings(u, "BG N!")
    finally:
        svc.fx_set_settings(u, "BGN")


def test_pair_detail(svc):
    u = user(svc, "FX Detay")
    today = svc.fx.today()
    days = _weekdays(today - _dt.timedelta(days=1), 30)
    for t in fx.TENORS:
        tk = fx.vol_ticker("USDTRY", "ATM", t)
        svc.store.hist_upsert(fx.series_id(tk), [(d.isoformat(), usdtry_quotes(t)["ATM"] - 1.0) for d in days])
    res = svc.fx_pair(u, "USDTRY", "3M")
    atm = res["structure"]["ATM"]
    assert atm["now"] == [usdtry_quotes(t)["ATM"] for t in fx.TENORS]
    assert atm["w1"] == [usdtry_quotes(t)["ATM"] - 1.0 for t in fx.TENORS] and atm["m1"] == atm["w1"]
    assert res["structure"]["RR25"]["w1"] == [None] * len(fx.TENORS)               # no history of the risk reversals
    # a week ago only the ATM vol is known: no smile is drawn for that day (a flat one would claim there was no skew)
    assert res["smiles"]["now"]["ATM"] == pytest.approx(9.0, abs=0.05) and res["smiles"]["w1"] is None
    assert res["tenor"] == "3M" and "25D RR 1M" in res["series"]


class _HistoryProvider(object):
    """Wraps the replay provider: answers ``history`` with made-up closes, counts what is asked."""

    def __init__(self, inner):
        self.inner = inner
        self.asked = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def history(self, items, start, end, timeout=60.0):
        self.asked.append((tuple(items), start, end))
        a = _dt.datetime.strptime(start, "%Y%m%d").date()
        b = _dt.datetime.strptime(end, "%Y%m%d").date()
        out = {}
        for sec, fld in items:
            if sec.startswith("NOHIST"):
                continue
            out[(sec, fld)] = [(d.isoformat(), 1.0) for d in _weekdays(b, 400) if d >= a]
        return out


def test_history_is_fetched_a_year_back_then_only_its_tail(tmp_path):
    s = make_service(tmp_path / "h")
    try:
        prov = _HistoryProvider(s.provider)
        s.provider = prov
        tk = fx.vol_ticker("EURUSD", "ATM", "1M")
        s.fx.want_history([tk, "NOHIST Index"], force=True)
        for _ in range(200):
            if prov.asked and s.fx.hist_state["phase"] == "idle" and not s.fx.hist_state["pending"]:
                break
            import time
            time.sleep(0.05)
        today = s.fx.today()
        first = prov.asked[0]
        assert first[1] == (today - _dt.timedelta(days=fx.LOOKBACK_DAYS)).strftime("%Y%m%d")
        assert first[2] == (today - _dt.timedelta(days=1)).strftime("%Y%m%d")
        b = s.store.hist_bounds()[fx.series_id(tk)]
        assert b[1] < today.isoformat() and b[2] > 200
        n = len(prov.asked)
        s.fx._fetch([tk])                                                   # known now: only the last ten days
        assert prov.asked[n][1] == (today - _dt.timedelta(days=10)).strftime("%Y%m%d")
        assert fx.series_id("NOHIST Index") in s.fx._hist_empty
        s.fx.want_history([tk])                                             # replay, not forced: nothing is asked
        assert len(prov.asked) == n + 1
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------- HTTP
def test_http(svc):
    from starlette.testclient import TestClient
    from tto.server import create_app
    client = TestClient(create_app(service=svc))
    u = user(svc, "FX HTTP")
    h = auth(svc, u)                                   # a signed-in session (the old user header signs nobody in)
    nav = client.get("/api/nav", headers=h).json()["pages"]
    fxp = [p for p in nav if p["group"] == "FX"]
    assert [p["id"] for p in fxp] == ["fx", "fxvol"] and fxp[0]["title"] == "Spot / FX"
    r = client.post("/api/fx/surface", json={"pair": "USDTRY", "model": "svi", "levels": [50, 60]}, headers=h)
    assert r.status_code == 200 and r.json()["levels"] == [50.0, 60.0] and len(r.json()["rows"]) == len(fx.TENORS)
    assert client.post("/api/fx/surface", json={"pair": "ABCDEF"}, headers=h).status_code == 400
    assert client.post("/api/fx/override", json={"pair": "USDTRY", "tenor": "1M", "kind": "ATM", "value": 6}, headers=h).json() \
        == {"overrides": {"1M": {"ATM": 6.0}}}
    assert client.post("/api/fx/override", json={"pair": "USDTRY", "clear": True}, headers=h).json() == {"overrides": {}}
    assert client.get("/api/fx/board", headers=h).json()["rows"][0]["pair"] == "USDTRY"
    assert client.get("/api/fx/monitor?window=126", headers=h).json()["window"] == 126
    assert client.get("/api/fx/pair?pair=EURUSD&tenor=1Y", headers=h).json()["tenor"] == "1Y"
    assert client.get("/api/fx/series?ticker=USDTRYV1M%20BGN%20Curncy", headers=h).json()["ticker"] == "USDTRYV1M BGN Curncy"
    added = client.post("/api/fx/tickers", json={"text": "DXY Curncy"}, headers=h).json()["added"]
    assert client.get("/api/fx/tickers", headers=h).json()["items"][0]["text"] == "DXY Curncy"
    assert client.post("/api/fx/tickers", json={"remove": added["id"]}, headers=h).json() == {"items": []}
    assert client.post("/api/fx/history", json={}, headers=h).status_code == 200
    assert client.get("/api/fx/board").status_code == 401                          # no session, no data


def test_a_spot_tick_moves_the_smile_without_fitting_it_again(svc):
    """Every condition of the fit depends on the strikes only through K/F: the smile fitted at one forward is, moved to
    another, exactly the one a new fit would give - so a ticking spot costs no new calibration."""
    from tto import fxvol as fv
    pair = svc.fx.pair("USDTRY")
    args = (0.25, 0.09, 0.073, 0.0135, 0.146, 0.045)
    s1, i1 = svc.fx._smile(pair, "spot-tick", "svi", fv.Quotes(50.0, *args, premium=True))
    q2 = fv.Quotes(50.5, *args, premium=True)
    s2, i2 = svc.fx._smile(pair, "spot-tick", "svi", q2)
    assert s2.F == 50.5 and s2 is not s1
    for K in (45.0, 50.0, 55.0):
        assert s2.vol(K * 1.01) == pytest.approx(s1.vol(K), rel=1e-12)
    again = fv.residuals(q2, s2)
    assert all(abs(again[k] - i1["fit"][k]) < 1e-9 for k in again)
    assert i2["points"]["25C"][0] == pytest.approx(i1["points"]["25C"][0] * 1.01, rel=1e-12)


def test_check_fx_asks_once_for_a_pairs_tickers():
    """``python -m tto check-fx``: one reference request for the surface's tickers, a table of what came back."""
    import fake_blpapi
    server = fake_blpapi.Server()
    for t in fx.TENORS:
        for kind, v in usdtry_quotes(t).items():
            server.ref[(fx.vol_ticker("USDTRY", kind, t), "PX_LAST", ())] = v
        server.ref[(fx.points_ticker(fx.PAIRS[0], t), "PX_LAST", ())] = 1000.0
        server.ref[(fx.points_ticker(fx.PAIRS[0], t), "FWD_SCALE", ())] = 4.0
    server.ref[("USDTRY Curncy", "PX_LAST", ())] = 50.0
    server.invalid.add("USDTRY10B2Y BGN Curncy")
    lines = []
    assert fx.check_fx("usdtry", blpapi_module=fake_blpapi.module(server), out=lines.append) == 0
    text = "\n".join(lines)
    assert "USDTRY25R3M BGN Curncy" in text and "TRY12M Curncy" in text and "Spot USDTRY Curncy: 50.0000" in text
    row = next(x for x in lines if x.startswith("2Y"))
    assert "yok" in row and "20.0000" in row
    assert len(server.requests) <= 3                           # batched: one request per field set
    server.invalid.add("USDTRYV1W BGN Curncy")
    assert fx.check_fx("USDTRY", blpapi_module=fake_blpapi.module(server), out=lines.append) == 2
    assert fx.check_fx("US/D", out=lines.append) == 1
