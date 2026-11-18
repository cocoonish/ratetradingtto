"""Günlük İşlemler: trade entry (forward / OIS outright, spread, fly, FRA / bond), the shared blotter,
the cost of the position and the workbook's own summary tables."""
import datetime as dt

import pytest

from conftest import cell
from tto import blotter as bl
from tto.service import ServiceError


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


@pytest.fixture(scope="module")
def users(svc):
    return svc.login("Blotter A")["user"], svc.login("Blotter B")["user"]


@pytest.fixture(scope="module")
def market(svc):
    return svc.ois_market(None)


def par(market, tenor):
    return {r["tenor"]: r for r in market["tenors"]}[tenor]["par"]


def annuity(market, tenor):
    return {r["tenor"]: r for r in market["tenors"]}[tenor]["annuity"]


def expected_nominal(market, dv01, a, weight=1.0):
    """OIS_MAIN sizing rule: ROUND(w * DV01 * USDTRY / (A * 0.0001) / lot, 0) * lot."""
    raw = weight * dv01 * market["usdtry"] / (a * 0.0001) / market["lot"]
    return float(int(raw + 0.5)) * market["lot"]


# ---------------------------------------------------------------------------------------------- pure maths
def test_position_cost_is_the_break_even_of_the_net_position():
    pc = bl.position_cost([(10e6, 51.70), (5e6, 51.90)], [(6e6, 52.00)])
    assert pc["buy"] == 15e6 and pc["sell"] == 6e6 and pc["net"] == 9e6
    assert pc["buy_avg"] == pytest.approx((10 * 51.70 + 5 * 51.90) / 15)
    assert pc["sell_avg"] == 52.00
    # (A1*R1 - A2*R2) / (A1 - A2)  - the "Maliyet" of the Calculators sheet
    assert pc["cost"] == pytest.approx((15e6 * pc["buy_avg"] - 6e6 * 52.00) / 9e6)
    assert pc["realised"] == pytest.approx(6e6 * (52.00 - pc["buy_avg"]))
    flat = bl.position_cost([(5e6, 51.0)], [(5e6, 52.0)])
    assert flat["net"] == 0 and flat["cost"] is None and flat["realised"] == pytest.approx(5e6)
    only = bl.position_cost([], [(3e6, 52.0)])
    assert only["net"] == -3e6 and only["cost"] == 52.0 and only["realised"] == 0.0
    assert bl.position_cost([], [])["cost"] is None


def test_calculators_sheet_agrees_with_position_cost(service):
    """The same weighted-average table exists in the workbook (Calculators!Z37:AD58)."""
    u = service.login("Blotter Calc")["user"]
    buys = [(10e6, 51.70), (5e6, 51.90)]
    sells = [(6e6, 52.00)]
    items = []
    for i, (a, r) in enumerate(buys):
        items += [{"ref": "Calculators!Z%d" % (39 + i), "value": a}, {"ref": "Calculators!AA%d" % (39 + i), "value": r}]
    for i, (a, r) in enumerate(sells):
        items += [{"ref": "Calculators!AC%d" % (39 + i), "value": a}, {"ref": "Calculators!AD%d" % (39 + i), "value": r}]
    for row in range(39, 53):                       # clear the rest of both tables
        for col, n in (("Z", len(buys)), ("AA", len(buys)), ("AC", len(sells)), ("AD", len(sells))):
            if row - 39 >= n:
                items.append({"ref": "Calculators!%s%d" % (col, row), "value": ""})
    assert service.set_inputs(u, "tto", items)["errors"] == []
    pc = bl.position_cost(buys, sells)
    data = service.grid(u, "tto", "Calculators", "Z37:AD58")["data"]
    numbers = [c["v"] for row in data["rows"] for c in row if c.get("k") == "n"]
    assert any(v == pytest.approx(pc["cost"], rel=1e-12) for v in numbers), "break-even (Maliyet) not found in the sheet"
    assert any(v == pytest.approx(pc["net"], rel=1e-12) for v in numbers)
    service.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- OIS strategies
def test_outright(svc, market):
    q = svc.quote_ois(None, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35,60", "dv01": 5000})
    (leg,) = q["legs"]
    assert leg["tenor"] == "1Y" and leg["dir"] == "B" and leg["rate"] == pytest.approx(0.356) and leg["role"] == "outright"
    assert leg["nominal"] == expected_nominal(market, 5000, annuity(market, "1Y"))
    assert leg["dv01"] == pytest.approx(leg["nominal"] * annuity(market, "1Y") * 0.0001 / market["usdtry"], rel=1e-12)
    assert abs(leg["dv01"] - 5000) < 5000 * 0.01                    # only the lot rounding
    mid = par(market, "1Y")
    assert q["info"]["market"] == mid
    assert q["info"]["cost_bp"] == pytest.approx((0.356 - mid) * 1e4)          # paying above mid costs
    assert q["info"]["cost_usd"] == pytest.approx(q["info"]["cost_bp"] * leg["dv01"])
    assert q["info"]["cost_tl"] == pytest.approx(q["info"]["cost_usd"] * market["usdtry"])
    rec = svc.quote_ois(None, {"strategy": "outright", "side": "RECEIVE", "tenor": "1Y", "level": 0.356, "dv01": 5000})
    assert rec["legs"][0]["dir"] == "S"
    assert rec["info"]["cost_bp"] == pytest.approx(-(0.356 - mid) * 1e4)       # receiving above mid is a gain


def test_default_size_is_the_sheets_dv01_per_leg(svc, market):
    q = svc.quote_ois(None, {"strategy": "outright", "side": "PAY", "tenor": "2Y", "level": "36"})
    assert q["legs"][0]["nominal"] == expected_nominal(market, market["dv01"], annuity(market, "2Y"))


def test_nominal_can_be_given_instead_of_dv01(svc, market):
    q = svc.quote_ois(None, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "36", "nominal": "500m"})
    assert q["legs"][0]["nominal"] == 500e6
    assert q["legs"][0]["dv01"] == pytest.approx(500e6 * annuity(market, "1Y") * 0.0001 / market["usdtry"])


def test_spread(svc, market):
    q = svc.quote_ois(None, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": "25", "dv01": 1000})
    short, long_ = q["legs"]
    assert (short["tenor"], short["dir"], short["role"]) == ("1Y", "B", "short")           # flattener pays the short leg
    assert (long_["tenor"], long_["dir"], long_["role"]) == ("2Y", "S", "long")            # ... and receives the long one
    assert short["rate"] == par(market, "1Y")
    assert long_["rate"] == pytest.approx(short["rate"] + 25 / 1e4)
    assert short["nominal"] == expected_nominal(market, 1000, annuity(market, "1Y"))
    assert long_["nominal"] == expected_nominal(market, 1000, annuity(market, "2Y"))
    mkt = (par(market, "2Y") - par(market, "1Y")) * 1e4
    assert q["info"]["market"] == pytest.approx(mkt)
    assert q["info"]["cost_bp"] == pytest.approx(mkt - 25)          # receiving the long leg 'mkt - 25' bp below mid
    steep = svc.quote_ois(None, {"strategy": "spread", "side": "STEEPENER", "short": "1Y", "long": "2Y", "level": 25, "dv01": 1000})
    assert [l["dir"] for l in steep["legs"]] == ["S", "B"]
    assert steep["info"]["cost_bp"] == pytest.approx(25 - mkt)
    own = svc.quote_ois(None, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": 25,
                               "short_rate": "35,40", "dv01": 1000})
    assert own["legs"][0]["rate"] == pytest.approx(0.354) and own["legs"][1]["rate"] == pytest.approx(0.3565)


def test_fly(svc, market):
    q = svc.quote_ois(None, {"strategy": "fly", "side": "REC GÖVDE", "wing1": "1Y", "body": "2Y", "wing2": "3Y", "level": "20",
                             "dv01": 1000})
    w1, body, w2 = q["legs"]
    assert [l["role"] for l in q["legs"]] == ["wing1", "body", "wing2"]
    assert [l["dir"] for l in q["legs"]] == ["B", "S", "B"]                      # receive the body, pay the wings
    assert w1["rate"] == par(market, "1Y") and w2["rate"] == par(market, "3Y")
    assert 2 * body["rate"] - w1["rate"] - w2["rate"] == pytest.approx(20 / 1e4, abs=1e-15)
    assert body["nominal"] == expected_nominal(market, 1000, annuity(market, "2Y"))
    assert w1["nominal"] == expected_nominal(market, 1000, annuity(market, "1Y"), 0.5)      # wings carry half
    assert w2["nominal"] == expected_nominal(market, 1000, annuity(market, "3Y"), 0.5)
    mkt = (2 * par(market, "2Y") - par(market, "1Y") - par(market, "3Y")) * 1e4
    assert q["info"]["market"] == pytest.approx(mkt)
    assert q["info"]["cost_bp"] == pytest.approx(mkt - 20)
    assert q["info"]["cost_usd"] == pytest.approx(q["info"]["cost_bp"] * body["dv01"] / 2)
    pay = svc.quote_ois(None, {"strategy": "fly", "side": "PAY GÖVDE", "wing1": "1Y", "body": "2Y", "wing2": "3Y", "level": 20})
    assert [l["dir"] for l in pay["legs"]] == ["S", "B", "S"]
    assert pay["info"]["cost_bp"] == pytest.approx(20 - mkt)


def test_fra(svc, market):
    q = svc.quote_ois(None, {"strategy": "fra", "side": "RECEIVE", "start_months": 3, "end_months": 6, "level": "35,10", "dv01": 2000})
    start, end = q["legs"]
    assert (start["tenor"], start["dir"], start["role"]) == ("3M", "B", "start")
    assert (end["tenor"], end["dir"], end["role"]) == ("6M", "S", "end")
    assert start["nominal"] == end["nominal"]                                    # one nominal on both swaps
    a1, a2 = start["annuity"], end["annuity"]
    # what the two swaps lock in between month 3 and month 6 is exactly the traded level
    assert (end["rate"] * a2 - start["rate"] * a1) / (a2 - a1) == pytest.approx(0.351, rel=1e-13)
    assert end["dv01"] - start["dv01"] == pytest.approx(2000, rel=0.01)          # net risk = the requested DV01
    assert q["info"]["cost_bp"] == pytest.approx((q["info"]["market"] - 0.351) * 1e4)
    spot = svc.quote_ois(None, {"strategy": "fra", "side": "PAY", "start_months": 0, "end_months": 12, "level": "35,7", "dv01": 1000})
    assert len(spot["legs"]) == 1 and spot["legs"][0]["tenor"] == "1Y" and spot["legs"][0]["dir"] == "B"
    assert spot["info"]["market"] == pytest.approx(par(market, "1Y"), rel=1e-9)   # spot-start FRA = the par swap


@pytest.mark.parametrize("payload, message", [
    ({"strategy": "outright", "side": "PAY", "tenor": "1Y"}, "seviye"),
    ({"strategy": "outright", "side": "BUY", "tenor": "1Y", "level": 0.35}, "PAY ya da RECEIVE"),
    ({"strategy": "outright", "side": "PAY", "tenor": "13M", "level": 0.35}, "geçersiz vade"),
    ({"strategy": "spread", "side": "FLATTENER", "short": "2Y", "long": "1Y", "level": 10}, "kısa vade"),
    ({"strategy": "spread", "side": "PAY", "short": "1Y", "long": "2Y", "level": 10}, "FLATTENER"),
    ({"strategy": "fly", "side": "REC GÖVDE", "wing1": "2Y", "body": "1Y", "wing2": "3Y", "level": 10}, "kanat < gövde"),
    ({"strategy": "fra", "side": "PAY", "start_months": 2, "end_months": 6, "level": 0.35}, "3'ün katı"),
    ({"strategy": "fra", "side": "PAY", "start_months": 6, "end_months": 6, "level": 0.35}, "3'ün katı"),
    ({"strategy": "swaption", "side": "PAY", "level": 0.35}, "bilinmeyen strateji"),
])
def test_bad_ois_requests_are_explained(svc, payload, message):
    with pytest.raises(ServiceError) as exc:
        svc.quote_ois(None, payload)
    assert message in str(exc.value)


# ---------------------------------------------------------------------------------------------- the blotter
def test_trades_are_shared_summarised_and_feed_the_workbook(svc, users, market):
    a, b = users
    today = dt.date.today().isoformat()
    assert svc.blotter(a)["trades"] == []
    f1 = svc.add_forward(a, {"dir": "B", "amount": "10m", "value_date": "15.12.2026", "basis": "RET_MID", "cpt": "ABC", "note": "ilk"})
    f2 = svc.add_forward(b, {"dir": "S", "amount": 4e6, "value_date": "15.12.2026", "basis": "TRY", "manual": "36,5"})
    assert f1["tl"] == 10e6 * f1["forward"] and f1["dir"] == "B" and f1["days"] == 41.0
    assert f2["try_rate"] == 0.365 and f2["amount"] == 4e6
    o1 = svc.add_ois(a, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35,60", "dv01": 5000, "cpt": "XYZ"})
    o2 = svc.add_ois(b, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": "25", "dv01": 1000})
    svc.add_bond(a, {"instrument": "TRT150328T24", "dir": "B", "amount": "50m", "price": "98,25"})
    svc.add_bond(b, {"instrument": "TRT150328T24", "dir": "S", "amount": 20e6, "price": 98.75})

    for user in (a, b, None):                                   # everybody gets the same blotter
        data = svc.blotter(user)
        assert data["date"] == today and data["is_today"]
        kinds = [t["kind"] for t in data["trades"]]
        assert kinds == ["fwd", "fwd", "ois", "ois", "ois", "bond", "bond"]
        assert [t["created_by"] for t in data["trades"]] == [a, b, a, b, b, a, b]
    trades = svc.blotter(b)["trades"]
    assert trades[0]["cpt"] == "ABC" and trades[0]["note"] == "ilk"
    assert trades[3]["package"] == trades[4]["package"] and trades[2]["package"] is None
    assert trades[3]["label"].startswith("FLATTENER 1Y/2Y")

    cost = svc.blotter(a)["cost"]
    (fw,) = cost["fwd"]
    assert fw["buy"] == 10e6 and fw["sell"] == 4e6 and fw["net"] == 6e6
    assert fw["cost"] == pytest.approx((10e6 * f1["forward"] - 4e6 * f2["forward"]) / 6e6, rel=1e-13)
    assert fw["realised"] == pytest.approx(4e6 * (f2["forward"] - f1["forward"]), rel=1e-12)
    by_tenor = {r["key"]: r for r in cost["ois"]}
    pay_1y = [o1["legs"][0], o2["legs"][0]]                     # both pay 1Y
    dv = sum(l["dv01"] for l in pay_1y)
    assert by_tenor["1Y"]["buy"] == pytest.approx(dv) and by_tenor["1Y"]["sell"] == 0
    assert by_tenor["1Y"]["cost"] == pytest.approx(sum(l["dv01"] * l["rate"] for l in pay_1y) / dv)
    assert by_tenor["2Y"]["net"] == pytest.approx(-o2["legs"][1]["dv01"])
    (bond,) = cost["bond"]
    assert bond["net"] == 30e6 and bond["cost"] == pytest.approx((50e6 * 98.25 - 20e6 * 98.75) / 30e6)
    assert bond["realised"] == pytest.approx(20e6 * 0.5 / 100)

    # the workbook's own "Günlük İşlemler" sheet received the trades and its summaries agree
    assert cell(svc, "Günlük İşlemler!A3") == "B" and cell(svc, "Günlük İşlemler!B3") == 10e6
    assert cell(svc, "Günlük İşlemler!C3") == f1["try_rate"] and cell(svc, "Günlük İşlemler!D3") == f1["value_date"]
    assert cell(svc, "Günlük İşlemler!A4") == "S" and cell(svc, "Günlük İşlemler!A5") is None
    # the O/N equivalent listed with each forward is the sheet's own column F: 360·((1+faiz·gün/365)^(1/gün) − 1)
    for i, t in enumerate(svc.blotter(a)["trades"][:2]):
        days, rate = cell(svc, "Günlük İşlemler!E%d" % (3 + i)), cell(svc, "Günlük İşlemler!C%d" % (3 + i))
        assert days == t["days"] and rate == t["try_rate"]
        assert t["on_rate"] == pytest.approx(cell(svc, "Günlük İşlemler!F%d" % (3 + i)), rel=1e-13)
        assert t["on_rate"] == pytest.approx(360 * ((1 + rate * days / 365) ** (1 / days) - 1), rel=1e-13)
        assert 0.25 < t["on_rate"] < rate
    assert all("on_rate" not in t for t in svc.blotter(a)["trades"] if t["kind"] != "fwd")
    assert bl.overnight_equivalent(0.36, 0) is None and bl.overnight_equivalent(None, 30) is None
    assert bl.overnight_equivalent(0.365, 1) == pytest.approx(0.36)                     # one day: only the day basis changes
    assert cell(svc, "Günlük İşlemler!L3") == "1Y" and cell(svc, "Günlük İşlemler!J3") == "B"
    assert cell(svc, "Günlük İşlemler!M3") == "XYZ" and cell(svc, "Günlük İşlemler!Y3") == "TRT150328T24"
    sheet = {p["id"]: p for p in svc.blotter(a)["sheet"]}
    assert set(sheet) == {"fwd", "ois", "bond", "cpt"} and all("data" in p for p in sheet.values())
    fwd_total = sheet["fwd"]["data"]["rows"][-1]
    assert [c.get("v") for c in fwd_total if c.get("k") == "n"][:1] == [6e6]             # net USD
    assert 10e6 in [c.get("v") for c in fwd_total] and 4e6 in [c.get("v") for c in fwd_total]
    ois_rows = {row[1].get("t"): row for row in sheet["ois"]["data"]["rows"]}
    one_year = [c.get("v") for c in ois_rows["1Y"] if c.get("k") == "n"]
    assert sum(l["nominal"] for l in pay_1y) in one_year                                  # pay nominal 1Y
    assert any(v == pytest.approx(dv, rel=1e-9) for v in one_year)                         # pay DV01 1Y


def test_delete_removes_the_whole_package_for_everyone(svc, users):
    a, b = users
    trades = svc.blotter(a)["trades"]
    spread_leg = [t for t in trades if t["kind"] == "ois" and t["package"]][1]
    res = svc.delete_trade(a, spread_leg["id"])                 # anyone may correct the blotter
    assert len(res["deleted"]) == 2
    left = svc.blotter(b)["trades"]
    assert [t["kind"] for t in left] == ["fwd", "fwd", "ois", "bond", "bond"]
    assert cell(svc, "Günlük İşlemler!L4") is None             # the sheet follows
    with pytest.raises(ServiceError) as exc:
        svc.delete_trade(a, spread_leg["id"])
    assert exc.value.status == 404


def test_past_days_are_kept_with_their_summary(svc, users):
    a, _ = users
    today = dt.date.today().isoformat()
    svc.store.add_trade("2026-01-05", "fwd", {"dir": "B", "amount": 1e6, "value_date": 46100.0, "basis": "RET_MID", "days": 30.0,
                                                "spot": 43.0, "usd_rate": 0.04, "try_rate": 0.4, "forward": 44.3, "points": 13000.0,
                                                "tl": 44.3e6, "cpt": "", "note": ""}, a)
    old = svc.blotter(a, "2026-01-05")
    assert old["is_today"] is False and len(old["trades"]) == 1 and old["cost"]["fwd"][0]["net"] == 1e6
    assert {d["date"] for d in old["dates"]} == {today, "2026-01-05"}
    assert svc.blotter(a, today)["is_today"] is True
    with pytest.raises(ServiceError):
        svc.blotter(a, "dün")


@pytest.mark.parametrize("payload, message", [
    ({"dir": "X", "amount": 1e6, "value_date": "15.12.2026"}, "yön"),
    ({"dir": "B", "amount": 0, "value_date": "15.12.2026"}, "tutar"),
    ({"dir": "B", "amount": "abc", "value_date": "15.12.2026"}, "tutar"),
    ({"dir": "B", "amount": 1e6}, "valör"),
])
def test_bad_forward_trades_are_refused(svc, users, payload, message):
    with pytest.raises(ServiceError) as exc:
        svc.add_forward(users[0], payload)
    assert message in str(exc.value)


def test_trades_need_a_logged_in_user(svc):
    with pytest.raises(ServiceError) as exc:
        svc.add_forward("yabancı", {"dir": "B", "amount": 1e6, "value_date": "15.12.2026"})
    assert exc.value.status == 401
    with pytest.raises(ServiceError):
        svc.add_bond(None, {"instrument": "X", "amount": 1, "price": 1})


def test_bond_validation(svc, users):
    a = users[0]
    for payload in ({"instrument": "", "amount": 1e6, "price": 99}, {"instrument": "X", "amount": 0, "price": 99},
                    {"instrument": "X", "amount": 1e6, "price": 0}):
        with pytest.raises(ServiceError):
            svc.add_bond(a, payload)


# ---------------------------------------------------------------------------------------------- DV01
def test_forward_dv01_is_the_sheets_own_block(service):
    """The workbook has a 'Forward DV01' block (Forward!N31:P49) for 1 mn USD at the RET mid forward of the
    value date in D2: the quote of that trade shows the same numbers, scaled by the amount and signed by the side."""
    u = service.login("DV01 fwd")["user"]
    d2 = cell(service, "Forward!D2")
    q = service.quote_forward(u, {"dir": "B", "amount": "10m", "value_date": d2, "basis": "RET_MID"})
    assert cell(service, "Forward!O44") == "B" and cell(service, "Forward!O45") == 1e6 and q["forward"] == cell(service, "Forward!O46")
    assert q["dv01"]["tl"] == pytest.approx(10 * cell(service, "Forward!O48"), rel=1e-12)             # DV01_TRY
    assert q["dv01"]["usd"] == pytest.approx(10 * cell(service, "Forward!O49"), rel=1e-12)            # TRY_USD_DV01
    assert q["dv01"]["usd_leg"] == pytest.approx(10 * cell(service, "Forward!O47"), rel=1e-12)        # DV01_USD
    assert q["dv01"]["tl"] > 0 > q["dv01"]["usd_leg"] and q["dv01"]["amount"] == 10e6
    assert q["df_try"] == cell(service, "Forward!O37") and q["df_usd"] == cell(service, "Forward!O42")
    # the other side has the other sign; without an amount the quote is per 1 mn USD
    s = service.quote_forward(u, {"dir": "S", "amount": "10m", "value_date": d2, "basis": "RET_MID"})["dv01"]
    assert s["tl"] == pytest.approx(-q["dv01"]["tl"]) and s["usd_leg"] == pytest.approx(-q["dv01"]["usd_leg"])
    one = service.quote_forward(u, {"dir": "B", "value_date": d2, "basis": "RET_MID"})
    assert "amount" not in one and one["dv01"]["amount"] == 1e6 and one["dv01"]["tl"] == pytest.approx(cell(service, "Forward!O48"), rel=1e-12)
    assert one["dv01_1m"]["tl"] == one["dv01"]["tl"]
    # another date: T, the forward and the discount factors of that date (the sheet's formula, by hand)
    q2 = service.quote_forward(u, {"dir": "B", "amount": "4m", "value_date": "15.01.2027", "basis": "TRY", "manual": "36,5"})
    t = q2["days"] / 360.0
    assert q2["dv01"]["tl"] == pytest.approx(4e6 * q2["forward"] * t * q2["df_try"] / 10000, rel=1e-12)
    assert q2["dv01"]["usd"] == pytest.approx(q2["dv01"]["tl"] / q2["spot"], rel=1e-12)
    assert q2["dv01"]["usd_leg"] == pytest.approx(-4e6 * t * q2["df_usd"] / 10000, rel=1e-12)
    assert 0.9 < q2["df_try"] < 1.0 and q2["df_try"] < q2["df_usd"] < 1.0


def test_forward_dv01_helper():
    r = bl.forward_dv01("B", 1e6, 52.0, 90.0, 50.0, 0.92, 0.99)
    assert r == {"tl": pytest.approx(1e6 * 52.0 * 0.25 * 0.92 / 1e4), "usd": pytest.approx(1e6 * 52.0 * 0.25 * 0.92 / 1e4 / 50.0),
                 "usd_leg": pytest.approx(-1e6 * 0.25 * 0.99 / 1e4)}
    # a trade stored without discount factors: its own simple rates stand in
    own = bl.forward_dv01("S", 2e6, 52.0, 90.0, 50.0, None, None, 0.36, 0.04)
    assert own["tl"] == pytest.approx(-2e6 * 52.0 * 0.25 / (1 + 0.36 * 0.25) / 1e4) and own["usd_leg"] == pytest.approx(2e6 * 0.25 / 1.01 / 1e4)
    assert bl.forward_dv01("B", None, 52.0, 90.0, 50.0, 0.9, 0.9) == {"tl": None, "usd": None, "usd_leg": None}
    assert bl.forward_dv01("B", 1e6, 52.0, 90.0, None, 0.9, 0.9)["usd"] is None


def test_ois_quote_has_the_net_and_gross_dv01(svc, market):
    q = svc.quote_ois(None, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": 0.37, "dv01": 5000.0})
    assert q["dv01"]["net"] == pytest.approx(q["legs"][0]["dv01"]) and q["dv01"]["gross"] == q["dv01"]["net"] > 0
    r = svc.quote_ois(None, {"strategy": "outright", "side": "RECEIVE", "tenor": "1Y", "level": 0.37, "dv01": 5000.0})
    assert r["dv01"]["net"] == pytest.approx(-q["dv01"]["net"]) and r["dv01"]["gross"] == pytest.approx(q["dv01"]["gross"])
    # a DV01-neutral spread: the legs cancel (but for the rounding to lots), the gross is both
    sp = svc.quote_ois(None, {"strategy": "spread", "side": "STEEPENER", "short": "1Y", "long": "2Y", "level": -125.0, "dv01": 5000.0})
    assert abs(sp["dv01"]["net"]) < 50 and sp["dv01"]["gross"] > 9900
    assert sp["dv01"]["gross"] == pytest.approx(sum(lg["dv01"] for lg in sp["legs"]))
    assert sp["dv01"]["net"] == pytest.approx(sp["legs"][1]["dv01"] - sp["legs"][0]["dv01"])          # pays the long leg


def test_bond_dv01_comes_from_the_rv_table(service):
    u = service.login("DV01 tahvil")["user"]
    q = service.quote_bond(u, {"instrument": " trt150328t24 ", "dir": "B", "amount": "50m"})
    row = q["info"]["row"]
    assert q["known"] and q["info"]["isin"] == "TRT150328T24" == cell(service, "DİBS RV!A%d" % row)
    per_mn = cell(service, "DİBS RV!AI%d" % row)
    assert cell(service, "DİBS RV!AI4").startswith("DV01 TL / 1mn") and per_mn > 50
    assert q["info"]["dv01_mn"] == per_mn and q["info"]["mod_dur"] == cell(service, "DİBS RV!AG%d" % row)
    assert q["info"]["clean"] == cell(service, "DİBS RV!O%d" % row) and q["info"]["name"] == cell(service, "DİBS RV!C%d" % row)
    assert q["dv01_tl"] == pytest.approx(-50 * per_mn) and q["dv01"] == pytest.approx(-50 * per_mn / q["usdtry"])    # a purchase loses
    assert service.quote_bond(u, {"instrument": "TRT150328T24", "dir": "S", "amount": "50m"})["dv01_tl"] == pytest.approx(50 * per_mn)
    one = service.quote_bond(u, {"instrument": "TRT150328T24"})                    # no amount yet: per 1 mn nominal
    assert one["amount"] is None and one["per"] == 1e6 and one["dv01_tl"] == pytest.approx(-per_mn)
    miss = service.quote_bond(u, {"instrument": "XS0000000000", "amount": "5m"})
    assert not miss["known"] and miss["info"] is None and miss["dv01"] is None and miss["dv01_tl"] is None
    with pytest.raises(ServiceError):
        service.quote_bond(u, {"instrument": "  "})
    assert bl.bond_dv01(1e6, None, 50.0) == {"tl": None, "usd": None}
    assert bl.bond_dv01(2e6, {"dv01_mn": 100.0}, None) == {"tl": -200.0, "usd": None}


@pytest.fixture()
def desk(tmp_path):
    """A blotter of its own: trades on three days."""
    from conftest import make_service
    svc = make_service(tmp_path)
    u = svc.login("Aralık A")["user"]
    yield svc, u
    svc.stop()


def test_a_leg_between_the_desks_buckets_is_split_between_the_two_around_it(desk):
    """(18.11.2026, the desk: a 12x15 FRA "15M bucket'ı arıyor"; then "yarısını 1Y, yarısını 18M bucket'ına atması
    gerekmiyor muydu") The desk's OIS buckets have no 15M / 21M - the sheet's summary (P25:P38) and its counterparty ×
    tenor table (Q89:Q107): OIS_MAIN reads those rows between quoted tenors.  A 12x15 FRA's 15M leg goes half to 1Y's
    bucket, half to 18M's - its nominal and DV01, at its own rate; in the sheet and in the cost table by tenor -, a 21M
    outright half to 18M, half to 2Y; the trades keep their own tenors."""
    svc, u = desk
    summary = {cell(svc, "Günlük İşlemler!P%d" % r): r for r in range(25, 39)}
    pivot = {cell(svc, "Günlük İşlemler!Q%d" % r): r for r in range(89, 108)}
    for tenors in (summary, pivot):
        assert "15M" not in tenors and "21M" not in tenors and "18M" in tenors and "2Y" in tenors
    fra = svc.add_ois(u, {"strategy": "fra", "side": "RECEIVE", "start_months": 12, "end_months": 15, "level": "35,10",
                          "dv01": 2000, "cpt": "XYZ"})
    out = svc.add_ois(u, {"strategy": "outright", "side": "PAY", "tenor": "21M", "level": "35,60", "dv01": 1000})
    start, end = fra["legs"]
    o = out["legs"][0]
    assert (start["tenor"], start["dir"], end["tenor"], end["dir"]) == ("1Y", "B", "15M", "S")
    trades = svc.blotter(u)["trades"]
    assert [t["tenor"] for t in trades] == ["1Y", "15M", "21M"]                         # the trades as entered
    g = lambda col, r: cell(svc, "Günlük İşlemler!%s%d" % (col, r))                  # noqa: E731
    # the sheet's rows: the start leg whole, the 15M leg as two halves (1Y, 18M), the 21M leg as two (18M, 2Y)
    assert [g("L", r) for r in range(3, 9)] == ["1Y", "1Y", "18M", "18M", "2Y", None]
    assert [g("I", r) for r in range(3, 8)] == pytest.approx([start["dv01"], end["dv01"] / 2, end["dv01"] / 2, o["dv01"] / 2, o["dv01"] / 2])
    assert [g("H", r) for r in range(4, 6)] == pytest.approx([end["nominal"] / 2] * 2) and [g("K", r) for r in (4, 5)] == [end["rate"]] * 2
    # the summary: 1Y pays the start and receives half the 15M leg, 18M receives the other half and pays half the 21M
    assert g("S", summary["1Y"]) == pytest.approx(start["dv01"]) and g("V", summary["1Y"]) == pytest.approx(end["dv01"] / 2)
    assert g("T", summary["18M"]) == pytest.approx(end["nominal"] / 2) and g("V", summary["18M"]) == pytest.approx(end["dv01"] / 2)
    assert g("U", summary["18M"]) == pytest.approx(end["rate"])
    assert g("S", summary["18M"]) == pytest.approx(o["dv01"] / 2) and g("S", summary["2Y"]) == pytest.approx(o["dv01"] / 2)
    assert g("Q", summary["2Y"]) == pytest.approx(o["nominal"] / 2)
    # the counterparty × tenor table: XYZ's 1Y line pays the start's DV01 (R) and receives half the 15M's (T), 18M the rest
    assert g("P", 89) == "XYZ"
    assert g("R", pivot["1Y"]) == pytest.approx(start["dv01"]) and g("T", pivot["1Y"]) == pytest.approx(end["dv01"] / 2)
    assert g("T", pivot["18M"]) == pytest.approx(end["dv01"] / 2)
    # the cost table by tenor: 1Y, 18M, 2Y - no 15M / 21M row
    cost = {x["key"]: x for x in svc.blotter(u)["cost"]["ois"]}
    assert list(cost) == ["1Y", "18M", "2Y"]
    assert cost["1Y"]["buy"] == pytest.approx(start["dv01"]) and cost["1Y"]["sell"] == pytest.approx(end["dv01"] / 2)
    assert cost["18M"]["sell"] == pytest.approx(end["dv01"] / 2) and cost["18M"]["buy"] == pytest.approx(o["dv01"] / 2)
    assert cost["2Y"]["buy"] == pytest.approx(o["dv01"] / 2)
    assert bl.buckets("15M") == [("1Y", 0.5), ("18M", 0.5)] and bl.buckets("18M") == [("18M", 1.0)] and bl.buckets("7Y") == [("7Y", 1.0)]
    assert [bl.buckets(t) for t in ("27M", "33M", "63M", "ON", "1W")] == [[("2Y", 0.75), ("3Y", 0.25)], [("2Y", 0.25), ("3Y", 0.75)],
                                                                        [("5Y", 0.75), ("6Y", 0.25)], [("ON", 1.0)], [("1W", 1.0)]]


def test_dv01_is_kept_with_the_trade_and_summed(desk):
    svc, u = desk
    f1 = svc.add_forward(u, {"dir": "B", "amount": "10m", "value_date": "07.06.2027", "basis": "RET_MID"})
    f2 = svc.add_forward(u, {"dir": "S", "amount": "5m", "value_date": "15.01.2027", "basis": "RET_BID"})
    assert f1["dv01_tl"] > 0 > f2["dv01_tl"] and f1["dv01"] == pytest.approx(f1["dv01_tl"] / f1["spot"])
    assert f1["usd_dv01"] < 0 < f2["usd_dv01"] and 0 < f1["df_try"] < 1
    pay = svc.add_ois(u, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "37,25", "dv01": 5000})
    rec = svc.add_ois(u, {"strategy": "outright", "side": "RECEIVE", "tenor": "2Y", "level": "34", "dv01": 2000})
    b1 = svc.add_bond(u, {"instrument": "TRT150328T24", "dir": "B", "amount": "50m", "price": "100,10"})
    b2 = svc.add_bond(u, {"instrument": "LISTEDE YOK", "dir": "S", "amount": "5m", "price": "99"})
    assert b1["dv01_tl"] < 0 and b1["dv01"] == pytest.approx(b1["dv01_tl"] / cell(svc, "OIS_MAIN!D2")) and b1["name"]
    assert b2["dv01"] is None and b2["dv01_tl"] is None and b2["name"] is None
    day = svc.blotter(u)
    by_id = {t["id"]: t for t in day["trades"]}
    assert by_id[f1["id"]]["dv01"] == f1["dv01"] and by_id[b1["id"]]["dv01_tl"] == b1["dv01_tl"]
    risk = day["risk"]
    assert risk["fwd"] == pytest.approx(f1["dv01"] + f2["dv01"]) and risk["fwd_tl"] == pytest.approx(f1["dv01_tl"] + f2["dv01_tl"])
    assert risk["ois"] == pytest.approx(pay["legs"][0]["dv01"] - rec["legs"][0]["dv01"])           # pay − receive
    assert risk["ois_gross"] == pytest.approx(pay["legs"][0]["dv01"] + rec["legs"][0]["dv01"])
    assert risk["bond"] == pytest.approx(b1["dv01"]) and risk["unknown"] == 1
    assert risk["total"] == pytest.approx(risk["fwd"] + risk["ois"] + risk["bond"])
    assert svc.blotter(u, "2020-01-01")["risk"]["total"] == 0.0
    # a forward stored before the DV01 was kept gets one from its own rates
    old = {k: v for k, v in f1.items() if k not in ("id", "dv01", "dv01_tl", "usd_dv01", "df_try", "df_usd")}
    svc.store.add_trade("2026-02-03", "fwd", old, u)
    (t,) = svc.blotter(u, "2026-02-03")["trades"]
    own = bl.forward_dv01("B", 10e6, f1["forward"], f1["days"], f1["spot"], None, None, f1["try_rate"], f1["usd_rate"])
    assert t["dv01_tl"] == pytest.approx(own["tl"]) and t["dv01"] == pytest.approx(own["usd"]) and abs(t["dv01_tl"] / f1["dv01_tl"] - 1) < 0.05


def test_a_period_lists_the_trades_of_every_day_in_it(desk):
    svc, u = desk
    today = dt.date.today()
    days = [(today - dt.timedelta(days=k)).isoformat() for k in (9, 4, 0)]
    f = svc.add_forward(u, {"dir": "B", "amount": "3m", "value_date": "07.06.2027", "basis": "RET_MID"})
    rec = {k: v for k, v in f.items() if k != "id"}
    svc.store.add_trade(days[0], "fwd", dict(rec, amount=1e6, tl=1e6 * rec["forward"]), u)
    svc.store.add_trade(days[1], "fwd", dict(rec, dir="S", amount=2e6, tl=2e6 * rec["forward"], dv01=-rec["dv01"], dv01_tl=-rec["dv01_tl"]), u)
    svc.store.add_trade(days[1], "bond", {"instrument": "TRT150328T24", "amount": 5e6, "price": 100.0, "note": ""}, u)
    one = svc.blotter(u, days[1])
    assert not one["ranged"] and one["to"] == days[1] and len(one["trades"]) == 2 and not one["is_today"]
    per = svc.blotter(u, days[0], None, days[2])
    assert per["ranged"] and (per["date"], per["to"]) == (days[0], days[2]) and per["days"] == 3 and not per["is_today"]
    assert [t["trade_date"] for t in per["trades"]] == [days[0], days[1], days[1], days[2]] and per["sheet"] == []
    # cost and risk are those of the whole period: 1 + 3 mn bought, 2 mn sold at the same forward
    (bucket,) = per["cost"]["fwd"]
    assert (bucket["buy"], bucket["sell"], bucket["net"]) == (4e6, 2e6, 2e6)
    assert per["risk"]["fwd"] == pytest.approx(rec["dv01"] + f["dv01"] - rec["dv01"])
    assert per["risk"]["unknown"] == 1                                             # the bond row above carries no DV01
    # the ends may be given in either order; a period of one day is that day; today alone is still today
    assert svc.blotter(u, days[2], None, days[0])["trades"] == per["trades"]
    assert not svc.blotter(u, days[1], None, days[1])["ranged"]
    assert svc.blotter(u, days[2], None, days[2])["is_today"] and svc.blotter(u)["is_today"]
    assert svc.blotter(u, "2019-01-01", None, "2019-12-31")["trades"] == []
    with pytest.raises(ServiceError):
        svc.blotter(u, days[0], None, "yarın")
    assert svc.store.trades(days[1], days[1]) == svc.store.trades(days[1]) and len(svc.store.trades(days[0], days[1])) == 3


def test_the_desks_chat_trades_are_reconciled_with_the_blotter(desk):
    """The desk's own trades said in the broker chat next to the blotter: entered (the same instrument and level within
    a quarter of an hour, or entered from the line with "İşlem gir"), not entered (the menu's count, the list), and what
    is decided by hand - a pair made, a pair taken apart, a line ignored, each undone."""
    from tto import brokerchat as bc
    svc, u = desk
    today = dt.date.today().isoformat()
    # typed without a time: said now.  Ours ("Biz") and a broker's - only ours count
    svc.broker_add(u, "18m ois paid 35.14\n2y ois given at 35.50\n7y ois trades 33.10\n1yr x 38.60 paid", None, "", True, "biz")
    svc.broker_add(u, "3y ois paid 35.30", None, "Tullett", True, "broker")
    svc.broker_add(u, "00:00:01 1y ois paid 35.00", None, "", True, "biz")
    assert svc.status()["chat_missing"] == 4 and svc.broker(u)["unbooked"] == 4
    rec = svc.add_ois(u, {"strategy": "outright", "side": "PAY", "tenor": "18M", "level": "35,14"})
    other = svc.add_ois(u, {"strategy": "outright", "side": "RECEIVE", "tenor": "2Y", "level": "35,55"})       # not the 35.50 said
    line = next(q for q in svc.broker(u)["rows"] if q["raw"] == "1y ois paid 35.00")
    linked = svc.add_ois(u, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35", "note": bc.chat_note(line)})
    data = svc.broker_recon(u)
    items = {x["raw"]: x for x in data["items"]}
    assert set(items) == {"18m ois paid 35.14", "2y ois given at 35.50", "7y ois trades 33.10", "1yr x 38.60 paid", "1y ois paid 35.00"}
    assert (items["18m ois paid 35.14"]["state"], items["18m ois paid 35.14"]["entry"]["id"]) == ("auto", rec["ids"][0])
    assert abs(items["18m ois paid 35.14"]["gap"]) < 120 and items["18m ois paid 35.14"]["entry"]["label"] == rec["label"]
    assert items["1y ois paid 35.00"]["state"] == "linked" and items["1y ois paid 35.00"]["entry"]["id"] == linked["ids"][0]
    assert (items["2y ois given at 35.50"]["state"], items["7y ois trades 33.10"]["state"], items["1yr x 38.60 paid"]["state"]) == \
        ("missing", "missing", "noform")
    assert data["missing"] == 2 == svc.status()["chat_missing"] and (data["date"], data["to"], data["ranged"]) == (today, today, False)
    assert [e["id"] for e in data["entries"]] == [rec["ids"][0], other["ids"][0], linked["ids"][0]]
    assert [e["taken"] for e in data["entries"]] == [True, False, True]
    two, seven, eighteen = (items[k]["id"] for k in ("2y ois given at 35.50", "7y ois trades 33.10", "18m ois paid 35.14"))
    # by hand, for everyone: the 2Y line is the 35.55 trade after all; the 7Y one will not be entered
    res = svc.broker_recon_set(u, two, "match", other["ids"][0])
    assert {x["id"]: x["state"] for x in res["items"]}[two] == "manual" and res["missing"] == 1
    gen = svc.gen
    res = svc.broker_recon_set(u, seven, "ignore")
    assert {x["id"]: (x["state"], x["by"]) for x in res["items"]}[seven] == ("ignored", u) and res["missing"] == 0 and svc.gen > gen
    assert svc.status()["chat_missing"] == 0 and svc.broker(u)["unbooked"] == 0
    # a pair taken apart: the 18M line is not entered any more - until it is undone
    res = svc.broker_recon_set(u, eighteen, "reject", rec["ids"][0])
    assert {x["id"]: x["state"] for x in res["items"]}[eighteen] == "missing" and res["missing"] == 1
    res = svc.broker_recon_set(u, eighteen, "undo")
    assert {x["id"]: x["state"] for x in res["items"]}[eighteen] == "auto" and res["missing"] == 0
    # deleting the trade a line was matched with brings the line back
    svc.delete_trade(u, other["ids"][0])
    assert {x["id"]: x["state"] for x in svc.broker_recon(u)["items"]}[two] == "missing" and svc.status()["chat_missing"] == 1
    # what cannot be done
    for args, status in (((two, "nonsense"), 400), ((two, "match", 999999), 404), ((123456, "ignore"), 404),
                         ((next(q["id"] for q in svc.broker(u)["rows"] if q["raw"] == "3y ois paid 35.30"), "ignore"), 200)):
        if status == 200:
            svc.broker_recon_set(u, *args)                  # a broker's trade line can be decided on too (it is not listed)
            continue
        with pytest.raises(ServiceError) as err:
            svc.broker_recon_set(u, *args)
        assert err.value.status == status, args
    with pytest.raises(ServiceError) as err:
        svc.broker_recon_set(None, two, "ignore")
    assert err.value.status == 401
    old = svc.store.add_trade("2026-02-03", "ois", {"strategy": "outright", "tenor": "2Y", "level": 0.355, "role": "outright"}, u)
    with pytest.raises(ServiceError):
        svc.broker_recon_set(u, two, "match", old)       # a trade of another day
    assert svc.broker_recon(u, "2026-02-03")["items"] == []


def test_a_period_downloads_as_one_list(desk):
    from helpers import read_xlsx
    svc, u = desk
    today = dt.date.today()
    first = today - dt.timedelta(days=6)
    f = svc.add_forward(u, {"dir": "B", "amount": "3m", "value_date": "07.06.2027", "basis": "RET_MID", "note": "bugün"})
    svc.add_bond(u, {"instrument": "TRT150328T24", "dir": "B", "amount": "50m", "price": "100,10"})
    svc.store.add_trade(first.isoformat(), "fwd", dict({k: v for k, v in f.items() if k != "id"}, note="geçen hafta"), u)
    raw, name = svc.blotter_export(u, first.isoformat(), None, today.isoformat())
    assert name == "Blotter_%s-%s.xlsx" % (first.strftime("%Y.%m.%d"), today.strftime("%Y.%m.%d"))
    book = read_xlsx(raw)
    assert list(book) == ["İşlem listesi"]                                       # Excel's layout of the sheet is one day's
    lst = book["İşlem listesi"]
    assert lst["A1"] == "Günlük İşlemler · %s – %s" % (first.strftime("%d.%m.%Y"), today.strftime("%d.%m.%Y"))
    assert lst["A5"] == "Tarih" and lst["B5"] == "Saat" and "yyyy" in lst["!formats"]["A6"]
    from tto.xl.values import date_to_serial
    assert (lst["A6"], lst["A7"]) == (date_to_serial(first), date_to_serial(today)) and lst["E6"] == 3e6 == lst["E7"]
    texts = [v for v in lst.values() if isinstance(v, str)]
    assert "geçen hafta" in texts and "bugün" in texts and "TRT150328T24" in texts
    assert any(t.startswith("DV01 özeti") for t in texts) and "DV01 (TL)" in texts
    # one day: the file the macro wrote, with the DV01 at the end of each row
    day = read_xlsx(svc.blotter_export(u)[0])
    assert list(day) == ["Günlük İşlemler", "İşlem listesi"]
    one = day["İşlem listesi"]
    assert one["A5"] == "Saat" and one["N5"] == "DV01 (TL)" and one["O5"] == "DV01 ($)"
    assert one["N6"] == pytest.approx(f["dv01_tl"]) and one["O6"] == pytest.approx(f["dv01"])
