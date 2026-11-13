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
