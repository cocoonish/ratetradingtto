"""USDTRY forward pricing equals the workbook's own cells, Excel's saved values and an independent
re-implementation of the formulas (interest parity, simple ACT/360, linear interpolation in days)."""
import pytest

from conftest import cell
from tto import blotter as bl
from tto.inputs import parse_date
from tto.xl.model import COLS

USER = "forward test"
DATES = ["05.11.2026", "06.11.2026", "11.11.2026", "04.12.2026", "15.12.2026", "04.02.2027", "07.06.2027", "03.11.2027",
         "04.05.2028", "06.11.2028", "15.03.2030"]


def column(svc, col, r1, r2, user=None):
    return [cell(svc, "Forward!%s%d" % (col, r), user) for r in range(r1, r2 + 1)]


def interpolate(xs, ys, x):
    """The sheet's rule: flat outside the nodes, linear in days between (MATCH type 1)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    k = max(i for i in range(len(xs)) if xs[i] <= x)
    return ys[k] + (x - xs[k]) * (ys[k + 1] - ys[k]) / (xs[k + 1] - xs[k])


@pytest.fixture(scope="module")
def svc(service):
    service.login(USER)
    return service


def set_date(svc, text):
    res = svc.set_inputs(USER, "tto", [{"ref": "Forward!D2", "value": text}])
    assert res["errors"] == []


@pytest.mark.parametrize("date", DATES)
def test_ret_outrights_match_an_independent_calculation(svc, date):
    set_date(svc, date)
    u = "forward test"
    spot = cell(svc, "Forward!F2", u)
    days = cell(svc, "Forward!U27", u)
    assert days == parse_date(date) - parse_date(cell(svc, "Forward!J2", u) or cell(svc, "OIS_MAIN!W2", u))
    ret_days = column(svc, "U", 33, 47, u)
    ret_bid, ret_ask = column(svc, "W", 33, 47, u), column(svc, "X", 33, 47, u)
    usd_days = column(svc, "U", 7, 26, u)
    usd_bid, usd_ask = column(svc, "W", 7, 26, u), column(svc, "Y", 7, 26, u)
    try_bid, try_ask = interpolate(ret_days, ret_bid, days), interpolate(ret_days, ret_ask, days)
    # the USD OIS table is quoted in percent, the TRY RET table as a fraction
    ub, ua = interpolate(usd_days, usd_bid, days) / 100, interpolate(usd_days, usd_ask, days) / 100
    assert cell(svc, "Forward!W48", u) == pytest.approx(try_bid, rel=1e-13)
    assert cell(svc, "Forward!X48", u) == pytest.approx(try_ask, rel=1e-13)
    assert cell(svc, "Forward!W27", u) == pytest.approx(ub, rel=1e-13)
    assert cell(svc, "Forward!Y27", u) == pytest.approx(ua, rel=1e-13)
    bid = spot * (1 + try_bid / 360 * days) / (1 + ua / 360 * days)          # TRY bid against USD ask
    ask = spot * (1 + try_ask / 360 * days) / (1 + ub / 360 * days)          # TRY ask against USD bid
    assert cell(svc, "Forward!D33", u) == pytest.approx(bid, rel=1e-13)
    assert cell(svc, "Forward!F33", u) == pytest.approx(ask, rel=1e-13)
    assert cell(svc, "Forward!E33", u) == pytest.approx((bid + ask) / 2, rel=1e-13)
    assert cell(svc, "Forward!D39", u) == pytest.approx((bid - spot) * 10000, rel=1e-11)
    assert cell(svc, "Forward!F39", u) == pytest.approx((ask - spot) * 10000, rel=1e-11)


@pytest.mark.parametrize("date", DATES)
def test_blotter_pricing_is_the_sheet(svc, date):
    """Trade entry prices with the very same cells (value date typed into Forward!D2)."""
    set_date(svc, date)
    u = "forward test"
    for basis, ref in (("RET_BID", "D33"), ("RET_MID", "E33"), ("RET_ASK", "F33")):
        q = svc.quote_forward(u, {"value_date": date, "basis": basis, "amount": 10e6})
        assert q["forward"] == cell(svc, "Forward!" + ref, u)
        assert q["tl"] == 10e6 * q["forward"]
        assert q["days"] == cell(svc, "Forward!U27", u)
        assert q["spot"] == cell(svc, "Forward!F2", u)
        assert q["points"] == pytest.approx((q["forward"] - q["spot"]) * 10000, rel=1e-12)
    q = svc.quote_forward(u, {"value_date": date, "basis": "RET_MID"})
    for name, row in (("ICAP", 30), ("OIS", 31), ("VIOP", 32), ("RET", 33)):
        for side, col in (("bid", "D"), ("mid", "E"), ("ask", "F")):
            v = cell(svc, "Forward!%s%d" % (col, row), u)
            assert q["table"][name][side] == (v if isinstance(v, float) else None)


@pytest.mark.parametrize("date", ["11.11.2026", "15.12.2026", "07.06.2027", "04.05.2028"])
@pytest.mark.parametrize("rate", [0.25, 0.365, 0.4275])
def test_manual_try_rate_and_implied_rate_are_inverse(svc, date, rate):
    u = "forward test"
    q = svc.quote_forward(u, {"value_date": date, "basis": "TRY", "manual": rate})
    days, spot, usd = q["days"], q["spot"], q["usd_rate"]
    # the bulk-pricing row interpolates the quoted USD OIS mids (column X, percent) in days
    usd_days = column(svc, "U", 7, 26, u)
    assert usd == pytest.approx(interpolate(usd_days, column(svc, "X", 7, 26, u), days) / 100, rel=1e-13)
    assert q["forward"] == pytest.approx(spot * (1 + rate * days / 360) / (1 + usd * days / 360), rel=1e-13)
    assert q["try_rate"] == rate
    back = svc.quote_forward(u, {"value_date": date, "basis": "FWD", "manual": q["forward"]})
    assert back["forward"] == q["forward"]
    assert back["try_rate"] == pytest.approx(rate, rel=1e-12)


def test_rates_can_be_typed_as_percent_or_fraction(svc):
    u = "forward test"
    a = svc.quote_forward(u, {"value_date": "15.12.2026", "basis": "TRY", "manual": "36,5"})
    b = svc.quote_forward(u, {"value_date": "15.12.2026", "basis": "TRY", "manual": "0,365"})
    c = svc.quote_forward(u, {"value_date": "2026-12-15", "basis": "TRY", "manual": "%36.5"})
    assert a["try_rate"] == b["try_rate"] == c["try_rate"] == 0.365
    assert a["forward"] == b["forward"] == c["forward"]


def test_pricing_respects_my_personal_ret_independent_inputs(svc):
    """Another user's value date does not leak into my quote."""
    other = svc.login("forward other")["user"]
    svc.set_inputs(other, "tto", [{"ref": "Forward!D2", "value": "03.11.2027"}])
    set_date(svc, "15.12.2026")
    mine = svc.quote_forward("forward test", {"value_date": "04.02.2027", "basis": "RET_MID"})
    theirs = svc.quote_forward(other, {"value_date": "04.02.2027", "basis": "RET_MID"})
    assert mine["forward"] == theirs["forward"]                       # same date -> same price ...
    assert cell(svc, "Forward!D2", "forward test") == parse_date("15.12.2026")    # ... and nobody's sheet moved
    assert cell(svc, "Forward!D2", other) == parse_date("03.11.2027")


@pytest.mark.parametrize("payload, message", [
    ({"value_date": "03.11.2026", "basis": "RET_MID"}, "spot"),          # not after spot
    ({"value_date": "yarın", "basis": "RET_MID"}, "anlaşılamadı"),
    ({"basis": "RET_MID"}, "gerekli"),
    ({"value_date": "15.12.2026", "basis": "TRY"}, "girilmedi"),
    ({"value_date": "15.12.2026", "basis": "FWD"}, "girilmedi"),
    ({"value_date": "15.12.2026", "basis": "XXX"}, "bilinmeyen"),
])
def test_bad_forward_requests_are_explained(svc, payload, message):
    from tto.service import ServiceError
    with pytest.raises(ServiceError) as exc:
        svc.quote_forward("forward test", payload)
    assert message in str(exc.value)


def test_default_value_date_reproduces_excels_saved_forwards(service):
    """With the workbook's own inputs the engine gives Excel's saved outrights digit for digit."""
    for ref in ("D30", "E30", "F30", "D31", "E31", "F31", "D32", "E32", "F32", "D33", "E33", "F33", "D39", "E39", "F39"):
        info = service.cell_info(None, "tto", "Forward!" + ref)
        assert isinstance(info["excel_cached"], float)
        assert info["cell"]["v"] == pytest.approx(info["excel_cached"], rel=1e-13), ref


def test_forward_formula_text_is_the_workbooks(service):
    info = service.cell_info(None, "tto", "Forward!D33")
    assert info["formula"] == "=$F$2*(1+$W$48/360*$U$27)/(1+$Y$27/360*$U$27)"
    info = service.cell_info(None, "tto", "Forward!F33")
    assert info["formula"] == "=$F$2*(1+$X$48/360*$U$27)/(1+$W$27/360*$U$27)"
