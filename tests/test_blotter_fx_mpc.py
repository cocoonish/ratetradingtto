"""Blotter: forwards in any pair (EURTRY with the sheet's own table, others by hand), swap points, meeting-dated OIS,
and the sign of a DV01 - payer is plus, everywhere."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import cell
from helpers import read_xlsx
from tto import blotter as bl
from tto.inputs import parse_date
from tto.server import create_app
from tto.service import ServiceError
from tto.xl.values import date_to_serial

VALUE = "15.12.2026"
VALUE_SERIAL = float(date_to_serial(dt.date(2026, 12, 15)))


@pytest.fixture(scope="module")
def desk(module_service):
    svc = module_service
    user = svc.login("FX Masa")["user"]
    svc.set_inputs(user, "tto", [{"ref": "Forward!D2", "value": VALUE}])       # the sheet's tables at the value date, to compare with
    return svc, user


def quote(svc, user, **kw):
    kw.setdefault("value_date", VALUE)
    return svc.quote_forward(user, kw)


# ---------------------------------------------------------------------------------------------- pairs
def test_which_pair():
    assert [bl.pair_of(x) for x in (None, "", "usdtry", "EURTRY", "eur", "gbp", "GBP/TRY", " chf try ", "eurusd")] == [
        "USDTRY", "USDTRY", "USDTRY", "EURTRY", "EURTRY", "GBPTRY", "GBPTRY", "CHFTRY", "EURUSD"]
    for bad in ("try", "TRYTRY", "x", "euro", "EURTRYX"):
        with pytest.raises(bl.TradeError):
            bl.pair_of(bad)


def test_eurtry_is_priced_with_the_sheets_own_table(desk):
    svc, u = desk
    spot, days, eur_mid = cell(svc, "Forward!G2", u), cell(svc, "Forward!AA27", u), cell(svc, "Forward!AD27", u)
    ret_bid, ret_ask = cell(svc, "Forward!W48", u), cell(svc, "Forward!X48", u)
    for basis, col, rate in (("RET_BID", "D", ret_bid), ("RET_MID", "E", (ret_bid + ret_ask) / 2), ("RET_ASK", "F", ret_ask)):
        q = quote(svc, u, pair="EURTRY", basis=basis)
        assert q["forward"] == pytest.approx(cell(svc, "Forward!%s45" % col, u), rel=1e-13), basis      # the 'RET' row of the EURTRY table
        assert q["points"] == pytest.approx(cell(svc, "Forward!%s51" % col, u), rel=1e-12)              # its swap point row
        assert q["try_rate"] == pytest.approx(rate, rel=1e-13)
        assert (q["pair"], q["base"], q["quote"], q["spot"], q["days"]) == ("EURTRY", "EUR", "TRY", spot, days)
    q = quote(svc, u, pair="eur", basis="RET_MID")
    assert q["usd_rate"] == pytest.approx(eur_mid) and q["usd_mid"] == pytest.approx(eur_mid)             # the currency's own rate
    assert q["table"]["OIS"]["mid"] == pytest.approx(cell(svc, "Forward!E43", u)) and set(q["table"]) == {"ICAP", "OIS", "VIOP", "RET"}
    k2 = cell(svc, "Forward!K2", u)                                           # EURTRY's own spot date (a text date offline)
    assert q["days"] == VALUE_SERIAL - (parse_date(k2) if isinstance(k2, str) else k2)
    # the USDTRY forward of the same date is still the USDTRY table's
    usd = quote(svc, u, basis="RET_MID")
    assert usd["forward"] == pytest.approx(cell(svc, "Forward!E33", u), rel=1e-13) and usd["pair"] == "USDTRY"
    assert usd["spot"] == cell(svc, "Forward!F2", u) != spot


def test_eurtry_from_a_try_rate_is_the_sheets_cross_formula(desk):
    svc, u = desk
    # the sheet's cross block with EUR, the date and a TRY rate typed in: its "fwd (manuel)" cell
    svc.set_inputs(u, "tto", [{"ref": "Forward!C197", "value": "EUR"}, {"ref": "Forward!B200", "value": VALUE},
                              {"ref": "Forward!F200", "value": "36"}])
    q = quote(svc, u, pair="EURTRY", basis="TRY", manual="36")
    assert q["forward"] == pytest.approx(cell(svc, "Forward!Q200", u), rel=1e-13) and q["try_rate"] == 0.36
    # an outright back to the rate it implies, and forth
    back = quote(svc, u, pair="EURTRY", basis="FWD", manual=q["forward"])
    assert back["try_rate"] == pytest.approx(0.36, abs=1e-12) and back["forward"] == q["forward"]
    for missing in ("TRY", "FWD", "SP"):
        with pytest.raises(ServiceError):
            quote(svc, u, pair="EURTRY", basis=missing)


def test_swap_points(desk):
    svc, u = desk
    spot, days, usd = cell(svc, "Forward!F2", u), cell(svc, "Forward!U27", u), None
    q = quote(svc, u, basis="SP", manual="17.400")                           # thousands the Turkish way
    assert q["forward"] == pytest.approx(spot + 1.74) and q["points"] == pytest.approx(17400.0) and q["basis"] == "SP"
    usd = q["usd_rate"]
    assert q["try_rate"] == pytest.approx(((q["forward"] / spot) * (1 + usd * days / 360) - 1) * 360 / days, rel=1e-13)
    assert quote(svc, u, basis="SP", manual="17400")["forward"] == q["forward"] == quote(svc, u, basis="SP", manual=17400)["forward"]
    assert svc.quote_forward(u, {"value_date": VALUE, "basis": "SP", "manual": "17,400"}, "en")["forward"] == q["forward"]
    assert quote(svc, u, basis="FWD", manual=q["forward"])["try_rate"] == pytest.approx(q["try_rate"], rel=1e-12)
    # points of the RET forward give the RET forward back
    ret = quote(svc, u, basis="RET_MID")
    again = quote(svc, u, basis="SP", manual=ret["points"])
    assert again["forward"] == pytest.approx(ret["forward"], rel=1e-13) and again["try_rate"] == pytest.approx(ret["try_rate"], abs=2e-5)
    e = quote(svc, u, pair="EURTRY", basis="SP", manual="22.500")
    assert e["forward"] == pytest.approx(cell(svc, "Forward!G2", u) + 2.25) and e["try_rate"] > ret["try_rate"]
    negative = quote(svc, u, basis="SP", manual="-500")
    assert negative["forward"] == pytest.approx(spot - 0.05) and negative["try_rate"] < negative["usd_rate"]     # points below zero: TRY under USD
    with pytest.raises(ServiceError):
        quote(svc, u, basis="SP", manual="-600.000")                         # a forward below zero


def test_a_pair_the_workbook_has_no_curve_for(desk):
    svc, u = desk
    df = cell(svc, "Forward!O37", u)
    q = quote(svc, u, pair="gbp", basis="FWD", manual="65,10", amount="2m")
    assert (q["pair"], q["forward"], q["spot"], q["points"], q["try_rate"], q["usd_rate"]) == ("GBPTRY", 65.10, None, None, None, None)
    assert q["tl"] == pytest.approx(2e6 * 65.10) and q["days"] == cell(svc, "Forward!U27", u)
    # the TRY side of it is still TRY risk: amount · forward · T · DF_TRY
    assert q["dv01"]["tl"] == pytest.approx(2e6 * 65.10 * q["days"] / 360 * df / 1e4) and q["dv01"]["usd_leg"] is None
    assert q["dv01"]["usd"] == pytest.approx(q["dv01"]["tl"] / cell(svc, "Forward!F2", u))
    sp = quote(svc, u, pair="GBPTRY", basis="SP", manual="20.000", spot="63,00")
    assert (sp["forward"], sp["spot"], sp["points"]) == (65.0, 63.0, pytest.approx(20000.0))
    out = quote(svc, u, pair="GBPTRY", basis="FWD", manual="65", spot="63")
    assert out["points"] == pytest.approx(20000.0)
    with pytest.raises(ServiceError) as err:
        quote(svc, u, pair="GBPTRY", basis="SP", manual="20.000")            # points on what?
    assert "spot" in str(err.value)
    for basis in ("RET_MID", "RET_BID", "TRY"):
        with pytest.raises(ServiceError) as err:
            quote(svc, u, pair="CHF", basis=basis, manual="36")
        assert "elle" in str(err.value)
    with pytest.raises(ServiceError):
        quote(svc, u, pair="lira", basis="FWD", manual="1")
    # a pair that is not against TRY: an amount in its second currency, no TRY risk
    x = quote(svc, u, pair="EURUSD", basis="FWD", manual="1,0850", amount="5m")
    assert (x["quote"], x["tl"]) == ("USD", pytest.approx(5e6 * 1.085)) and x["dv01"] == {"tl": None, "usd": None, "usd_leg": None, "amount": 5e6, "dir": "B"}


def test_the_dv01_of_a_forward_payer_is_plus(desk):
    svc, u = desk
    usdtry, df = cell(svc, "Forward!F2", u), cell(svc, "Forward!O37", u)
    for pair in ("USDTRY", "EURTRY"):
        q = quote(svc, u, pair=pair, basis="RET_MID", amount="10m", dir="B")
        tl = 10e6 * q["forward"] * q["days"] / 360 * df / 1e4
        assert q["dv01"]["tl"] == pytest.approx(tl) and q["dv01"]["tl"] > 0       # buying the currency forward pays the TRY rate
        assert q["dv01"]["usd"] == pytest.approx(tl / usdtry)                      # in USD at the USDTRY spot, whatever the pair
        assert q["dv01"]["usd_leg"] < 0
        s = quote(svc, u, pair=pair, basis="RET_MID", amount="10m", dir="S")["dv01"]
        assert (s["tl"], s["usd"], s["usd_leg"]) == (pytest.approx(-tl), pytest.approx(-tl / usdtry), pytest.approx(-q["dv01"]["usd_leg"]))
    # USDTRY: the numbers of the sheet's own 'Forward DV01' block for 1 mn
    one = quote(svc, u, basis="RET_MID")
    assert one["dv01"]["amount"] == 1e6 and one["dv01"]["tl"] == pytest.approx(1e6 * one["forward"] * one["days"] / 360 * df / 1e4)


@pytest.fixture(scope="module")
def book_of_trades(desk):
    """A day with forwards in four pairs, a tenor OIS and two meeting-dated ones."""
    svc, u = desk
    m = svc.ois_market(u)["mpc"]
    trades = {
        "usd": svc.add_forward(u, {"dir": "B", "amount": "10m", "value_date": VALUE, "basis": "RET_MID"}),
        "eur": svc.add_forward(u, {"pair": "EURTRY", "dir": "B", "amount": "5m", "value_date": VALUE, "basis": "RET_MID"}),
        "eur2": svc.add_forward(u, {"pair": "EURTRY", "dir": "S", "amount": "3m", "value_date": VALUE, "basis": "SP", "manual": "22.500"}),
        "gbp": svc.add_forward(u, {"pair": "gbp", "dir": "S", "amount": "2m", "value_date": VALUE, "basis": "SP", "manual": "20.000",
                                   "spot": "63", "cpt": "ABC"}),
        "eurusd": svc.add_forward(u, {"pair": "EURUSD", "dir": "B", "amount": "1m", "value_date": VALUE, "basis": "FWD", "manual": "1,085"}),
        "ois": svc.add_ois(u, {"strategy": "outright", "side": "RECEIVE", "tenor": "1Y", "level": "35,60", "dv01": "2000"}),
        "mpc": svc.add_ois(u, {"strategy": "mpc", "side": "PAY", "start": m["dates"][0]["date"], "end": m["dates"][1]["date"],
                               "level": "35,90"}),
        "stub": svc.add_ois(u, {"strategy": "mpc", "side": "RECEIVE", "start": m["spot"], "end": m["dates"][2]["text"],
                                "level": "36", "nominal": "500m", "cpt": "XYZ"}),
    }
    return svc, u, trades, m


def test_forwards_are_kept_with_their_pair(book_of_trades):
    svc, u, t, _ = book_of_trades
    assert [(t[k]["pair"], t[k]["basis"]) for k in ("usd", "eur", "eur2", "gbp", "eurusd")] == [
        ("USDTRY", "RET_MID"), ("EURTRY", "RET_MID"), ("EURTRY", "SP"), ("GBPTRY", "SP"), ("EURUSD", "FWD")]
    assert t["eur"]["tl"] == pytest.approx(5e6 * t["eur"]["forward"]) and t["eur2"]["points"] == pytest.approx(22500.0)
    assert (t["gbp"]["forward"], t["gbp"]["spot"], t["gbp"]["try_rate"], t["gbp"]["cpt"]) == (65.0, 63.0, None, "ABC")
    assert t["eur"]["dv01"] > 0 > t["eur2"]["dv01"] and t["gbp"]["dv01"] < 0 and t["eurusd"]["dv01"] is None
    data = svc.blotter(u)
    kept = {x["id"]: x for x in data["trades"] if x["kind"] == "fwd"}
    assert [kept[t[k]["id"]]["pair"] for k in ("usd", "eur", "gbp")] == ["USDTRY", "EURTRY", "GBPTRY"]
    assert kept[t["gbp"]["id"]]["on_rate"] is None and kept[t["eur"]["id"]]["on_rate"] == pytest.approx(
        bl.overnight_equivalent(t["eur"]["try_rate"], t["eur"]["days"]))
    # position and cost: by pair and value date, USDTRY first
    cost = data["cost"]["fwd"]
    assert [(c["pair"], c["key"]) for c in cost] == [("USDTRY", VALUE_SERIAL), ("EURTRY", VALUE_SERIAL), ("EURUSD", VALUE_SERIAL),
                                                    ("GBPTRY", VALUE_SERIAL)]
    eur = cost[1]
    assert (eur["buy"], eur["sell"], eur["net"]) == (5e6, 3e6, 2e6)
    assert eur["realised"] == pytest.approx(3e6 * (t["eur2"]["forward"] - t["eur"]["forward"]))
    assert eur["cost"] == pytest.approx((5e6 * t["eur"]["forward"] - 3e6 * t["eur2"]["forward"]) / 2e6)
    # risk: every forward against TRY counts, in USD; the one that is not is named as unknown
    risk = data["risk"]
    assert risk["fwd"] == pytest.approx(sum(t[k]["dv01"] for k in ("usd", "eur", "eur2", "gbp"))) and risk["unknown"] == 1


def test_the_workbooks_own_sheet_takes_every_trade_against_try(book_of_trades):
    svc, u, t, m = book_of_trades
    data = svc.blotter(u)
    g = lambda ref: cell(svc, "Günlük İşlemler!" + ref)                                      # noqa: E731
    # forwards: USDTRY as it is; EURTRY at its USD amount (the trade's spot and USDTRY) with its own TRY rate - the TL cost;
    # GBPTRY by hand without a TRY rate and EURUSD (no TRY leg) stay out.  Column G: each one's DV01 ($)
    assert (g("A3"), g("B3"), g("C3"), g("D3"), g("G3")) == ("B", 10e6, t["usd"]["try_rate"], VALUE_SERIAL, t["usd"]["dv01"])
    eur, eur2 = t["eur"], t["eur2"]
    assert (g("A4"), g("C4"), g("G4")) == ("B", eur["try_rate"], eur["dv01"]) and g("B4") == pytest.approx(5e6 * eur["spot"] / eur["usdtry"])
    assert (g("A5"), g("C5")) == ("S", eur2["try_rate"]) and g("B5") == pytest.approx(3e6 * eur2["spot"] / eur2["usdtry"])
    assert g("A6") is None and g("B6") is None
    assert g("P20") == pytest.approx(10e6 + g("B4") - g("B5"))                         # net USD bought, every pair in USD
    # the summary as the page shows it: the sheet's buckets with their DV01 ($) on the right - buys, sells, net
    fwd = next(p for p in data["sheet"] if p["id"] == "fwd")["data"]
    assert fwd["c"][-3:] == ["DV01 B", "DV01 S", "DV01 N"]
    total = fwd["rows"][fwd["r"].index(20)]
    assert total[-3]["v"] == pytest.approx(t["usd"]["dv01"] + eur["dv01"]) and total[-2]["v"] == pytest.approx(eur2["dv01"])
    assert total[-1]["v"] == pytest.approx(t["usd"]["dv01"] + eur["dv01"] + eur2["dv01"])
    per_bucket = [fwd["rows"][i][-1].get("v") or 0.0 for i, r in enumerate(fwd["r"]) if 6 <= r <= 19]
    assert sum(per_bucket) == pytest.approx(total[-1]["v"])                             # split between buckets, nothing lost
    # OIS: the 1Y as it is, then the two meeting-dated swaps spread over the main tenors
    assert (g("L3"), g("J3"), g("K3")) == ("1Y", "S", pytest.approx(0.356))
    rows = []
    r = 4
    while g("L%d" % r):
        rows.append((g("L%d" % r), g("J%d" % r), g("I%d" % r), g("H%d" % r), g("K%d" % r)))
        r += 1
    mpc, stub = t["mpc"]["legs"][0], t["stub"]["legs"][0]
    # PAY 11.12.26–22.01.27 = PAY to 22.01.27 (between 2M and 3M) + RECEIVE to 11.12.26 (between 1M and 2M)
    assert [(x[0], x[1]) for x in rows[:4]] == [("2M", "B"), ("3M", "B"), ("1M", "S"), ("2M", "S")]
    assert sum(x[2] for x in rows[:2]) - sum(x[2] for x in rows[2:4]) == pytest.approx(mpc["dv01"])     # its own DV01, exactly
    assert rows[0][3] + rows[1][3] == pytest.approx(rows[2][3] + rows[3][3])                              # one nominal for both
    # ... at rates that make the two legs the traded rate: R_E·A_E − R_S·A_S = R·(A_E − A_S), A ~ DV01
    d_e, d_s = rows[0][2] + rows[1][2], rows[2][2] + rows[3][2]
    assert rows[0][4] * d_e - rows[2][4] * d_s == pytest.approx(mpc["rate"] * (d_e - d_s), rel=1e-9)
    # RECEIVE from the spot to the third meeting: one spot swap, the trade itself, between the two tenors around its end
    assert [x[1] for x in rows[4:]] == ["S", "S"] and sum(x[2] for x in rows[4:]) == pytest.approx(stub["dv01"])
    assert sum(x[3] for x in rows[4:]) == pytest.approx(stub["nominal"]) and {x[4] for x in rows[4:]} == {stub["rate"]}
    # the sheet's tenor summary: pay DV01 − receive DV01 over every tenor = the day's OIS risk
    net = sum((g("S%d" % k) or 0.0) - (g("V%d" % k) or 0.0) for k in range(25, 39))
    assert net == pytest.approx(mpc["dv01"] - stub["dv01"] - t["ois"]["legs"][0]["dv01"])


# ---------------------------------------------------------------------------------------------- meeting-dated OIS
def test_the_meeting_dates_are_the_sheets(desk):
    svc, u = desk
    m = svc.ois_market(u)["mpc"]
    assert m["spot"] == cell(svc, "OIS_MAIN!B2", u) and m["spot_text"] == "04.11.2026"
    assert len(m["dates"]) == 17 and [d["k"] for d in m["dates"]] == list(range(1, 18))
    for k in range(16):
        row = 84 + k
        assert m["dates"][k]["date"] == cell(svc, "OIS_MAIN!B%d" % row, u) and m["dates"][k + 1]["date"] == cell(svc, "OIS_MAIN!C%d" % row, u)
        assert m["dates"][k]["market"] == cell(svc, "OIS_MAIN!D%d" % row, u)       # the period that starts on the date
    assert m["dates"][0]["text"] == "11.12.2026" and m["dates"][16]["market"] is None
    assert all(a["date"] < b["date"] for a, b in zip(m["dates"], m["dates"][1:])) and m["dates"][0]["date"] > m["spot"]


def test_a_meeting_dated_swap_is_priced_as_the_sheet_prices_it(desk):
    svc, u = desk
    m = svc.ois_market(u)["mpc"]
    usdtry = cell(svc, "OIS_MAIN!D2", u)
    for k in (0, 1, 5, 15):
        d1, d2 = m["dates"][k]["date"], m["dates"][k + 1]["date"]
        q = svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": d1, "end": d2, "level": "35,90"})
        row = 84 + k
        assert q["info"]["market"] == pytest.approx(cell(svc, "OIS_MAIN!D%d" % row, u), rel=1e-12)       # 'Piyasa (bootstrap)'
        leg = q["legs"][0]
        assert leg["nominal"] == cell(svc, "OIS_MAIN!G%d" % row, u)                # the sheet's 'Nominal' for the default DV01
        assert (leg["dir"], leg["role"], leg["rate"]) == ("B", "mpc", 0.359) and leg["mpc"] == {"start": d1, "end": d2, "days": d2 - d1}
        assert leg["dv01"] == pytest.approx(leg["nominal"] * leg["annuity"] * 1e-4 / usdtry)
        assert q["info"]["cost_bp"] == pytest.approx((0.359 - q["info"]["market"]) * 1e4)
        assert q["dv01"] == {"net": pytest.approx(leg["dv01"]), "gross": pytest.approx(leg["dv01"])}      # paying is plus
        assert q["info"]["cost_usd"] == pytest.approx(q["info"]["cost_bp"] * leg["dv01"])
    first = svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": m["dates"][0]["date"], "end": m["dates"][1]["date"], "level": "35,90"})
    assert first["label"] == "PAY MPC 11.12.26–22.01.27 @ 35,9000%" and first["legs"][0]["tenor"] == "MPC 11.12.26–22.01.27"
    rec = svc.quote_ois(u, {"strategy": "mpc", "side": "RECEIVE", "start": "11.12.2026", "end": "22.01.2027", "level": 35.9})
    assert rec["dv01"]["net"] == pytest.approx(-first["dv01"]["net"]) and rec["info"]["cost_bp"] == pytest.approx(-first["info"]["cost_bp"])
    assert rec["legs"][0]["dir"] == "S" and rec["info"]["market"] == first["info"]["market"]


def test_any_two_dates_and_a_nominal(desk):
    svc, u = desk
    m = svc.ois_market(u)["mpc"]
    spot, end = m["spot"], m["dates"][2]["date"]
    # the sheet's own calculator with the two dates typed in
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B122", "value": m["spot_text"]}, {"ref": "OIS_MAIN!B123", "value": m["dates"][2]["text"]}])
    market, df = cell(svc, "OIS_MAIN!B129", u), cell(svc, "OIS_MAIN!E125", u)
    q = svc.quote_ois(u, {"strategy": "mpc", "side": "RECEIVE", "start": spot, "end": end, "level": "36", "nominal": "500m"})
    leg = q["legs"][0]
    assert q["info"]["market"] == pytest.approx(market, rel=1e-12) and q["info"]["implied"] == pytest.approx(cell(svc, "OIS_MAIN!B125", u))
    assert leg["nominal"] == 500e6 and leg["annuity"] == pytest.approx((end - spot) / 365 * df)
    assert leg["dv01"] == pytest.approx(500e6 * (end - spot) / 365 * df * 1e-4 / cell(svc, "OIS_MAIN!D2", u))
    assert q["dv01"]["net"] == pytest.approx(-leg["dv01"]) and q["info"]["cost_bp"] == pytest.approx((market - 0.36) * 1e4)
    # a longer span is the product of its periods
    a = svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": m["dates"][0]["date"], "end": m["dates"][1]["date"], "level": "36"})["info"]["market"]
    b = svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": m["dates"][1]["date"], "end": m["dates"][2]["date"], "level": "36"})["info"]["market"]
    ab = svc.quote_ois(u, {"strategy": "mpc", "side": "PAY", "start": m["dates"][0]["date"], "end": m["dates"][2]["date"], "level": "36"})["info"]["market"]
    t1, t2 = m["dates"][1]["date"] - m["dates"][0]["date"], m["dates"][2]["date"] - m["dates"][1]["date"]
    assert (1 + ab * (t1 + t2) / 365) == pytest.approx((1 + a * t1 / 365) * (1 + b * t2 / 365), rel=1e-9)
    for bad in ({"start": end, "end": spot}, {"start": spot, "end": spot}, {"start": spot - 10, "end": end}, {"start": spot}, {"end": end},
                {"start": "dün", "end": end}):
        with pytest.raises(ServiceError):
            svc.quote_ois(u, dict({"strategy": "mpc", "side": "PAY", "level": "36"}, **bad))
    with pytest.raises(ServiceError):
        svc.quote_ois(u, {"strategy": "mpc", "side": "FLATTENER", "start": spot, "end": end, "level": "36"})


def test_meeting_dated_trades_in_the_blotter(book_of_trades):
    svc, u, t, m = book_of_trades
    data = svc.blotter(u)
    legs = {x["id"]: x for x in data["trades"] if x["kind"] == "ois"}
    mpc, stub, ois = legs[t["mpc"]["ids"][0]], legs[t["stub"]["ids"][0]], legs[t["ois"]["ids"][0]]
    assert (mpc["tenor"], mpc["role"], mpc["strategy"], mpc["dir"]) == ("MPC 11.12.26–22.01.27", "mpc", "mpc", "B")
    assert mpc["mpc"] == {"start": m["dates"][0]["date"], "end": m["dates"][1]["date"], "days": m["dates"][1]["date"] - m["dates"][0]["date"]}
    assert (stub["tenor"], stub["dir"], stub["nominal"], stub["cpt"]) == ("MPC 04.11.26–19.03.27", "S", 500e6, "XYZ")
    assert mpc["package"] is None and mpc["market"] == pytest.approx(cell(svc, "OIS_MAIN!D84", u))
    # cost by what was traded: the tenors first, the meeting-dated ones by their start
    assert [c["key"] for c in data["cost"]["ois"]] == ["1Y", "MPC 04.11.26–19.03.27", "MPC 11.12.26–22.01.27"]
    by = {c["key"]: c for c in data["cost"]["ois"]}
    assert by["MPC 11.12.26–22.01.27"]["net"] == pytest.approx(mpc["dv01"]) and by["MPC 04.11.26–19.03.27"]["net"] == pytest.approx(-stub["dv01"])
    # risk: payer plus, receiver minus
    risk = data["risk"]
    assert risk["ois"] == pytest.approx(mpc["dv01"] - stub["dv01"] - ois["dv01"]) and risk["ois_gross"] == pytest.approx(mpc["dv01"] + stub["dv01"] + ois["dv01"])
    assert risk["total"] == pytest.approx(risk["fwd"] + risk["ois"] + risk["bond"])


def test_the_days_file_has_the_pair_the_points_and_signed_dv01(book_of_trades):
    svc, u, t, _ = book_of_trades
    lst = read_xlsx(svc.blotter_export(u)[0])["İşlem listesi"]
    assert lst["A4"] == "Forward" and [lst[c + "5"] for c in "ADNOPQ"] == ["Saat", "Tutar (döviz)", "DV01 (TL)", "DV01 ($)", "Parite", "Swap puanı"]
    assert [lst["P%d" % r] for r in range(6, 11)] == ["USDTRY", "EURTRY", "EURTRY", "GBPTRY", "EURUSD"]
    assert lst["Q8"] == pytest.approx(22500.0) and lst["H9"] == 65.0 and lst["J9"] == "Swap puanı" and "G9" not in lst and "N10" not in lst
    cells = {v: k for k, v in lst.items() if isinstance(v, str)}
    head = int(cells["OIS"][1:]) + 1                                             # the OIS table: its header row
    assert lst["I%d" % head] == "DV01 ($)" and lst["F%d" % head] == "Vade"
    rows = {lst["F%d" % r]: lst["I%d" % r] for r in range(head + 1, head + 4)}
    assert rows["1Y"] < 0 < rows["MPC 11.12.26–22.01.27"] and rows["MPC 04.11.26–19.03.27"] < 0      # payer +, receiver −
    assert rows["1Y"] == pytest.approx(-t["ois"]["legs"][0]["dv01"])
    costs = int(cells["Forward · pozisyon ve maliyet"][1:]) + 1
    assert lst["I%d" % costs] == "Parite" and [lst["I%d" % r] for r in range(costs + 1, costs + 5)] == ["USDTRY", "EURTRY", "EURUSD", "GBPTRY"]


def test_over_http(desk):
    from urllib.parse import quote as q
    svc, u = desk
    with TestClient(create_app(svc)) as client:
        hdr = {"X-TTO-User": q(u)}
        res = client.post("/api/blotter/quote/forward", json={"pair": "EURTRY", "value_date": VALUE, "basis": "SP", "manual": "22.500"}, headers=hdr)
        assert res.status_code == 200 and res.json()["forward"] == pytest.approx(cell(svc, "Forward!G2", u) + 2.25) and res.json()["pair"] == "EURTRY"
        assert client.post("/api/blotter/quote/forward", json={"pair": "zz", "value_date": VALUE, "basis": "FWD", "manual": "1"},
                           headers=hdr).status_code == 400
        m = client.get("/api/blotter/ois-market", headers=hdr).json()["mpc"]
        assert len(m["dates"]) == 17
        res = client.post("/api/blotter/quote/ois", json={"strategy": "mpc", "side": "PAY", "start": m["dates"][3]["date"],
                                                           "end": m["dates"][4]["date"], "level": "34,50"}, headers=hdr)
        assert res.status_code == 200 and res.json()["info"]["market"] == pytest.approx(m["dates"][3]["market"], rel=1e-12)
        assert client.post("/api/blotter/quote/ois", json={"strategy": "mpc", "side": "PAY", "start": m["dates"][4]["date"],
                                                            "end": m["dates"][3]["date"], "level": "34,50"}, headers=hdr).status_code == 400
