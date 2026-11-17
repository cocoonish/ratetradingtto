"""DİBS Trading in groups of columns, with each bond's fair yield and price on DİBS RV's fitted ASW curves - OIS and the FX
swap curve (``tto/rvfair.py``) - and the bond lists shown as the trading list has them: DİBS Trading's value dates and the
DİBS ASW table without the rows that hold no bond, the ASW table kind by kind, by maturity (display only)."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import bonds as bd
from tto import extras as ex
from tto import rvfair
from tto.store import user_key
from tto.xl.tokenizer import col_to_index, index_to_col

FIXED, BILL, TLREF, NO_PRICE, LONG = "TRT150328T24", "TRB100227T13", "TRT090130T12", "TRT081128T15", "TRT051033T12"
#: the columns of the summary by their letter (kept from before the groups; the fair values are new ones)
OIS_YIELD, OIS_PRICE, FX_ASW, FX_YIELD, FX_PRICE, FX_RICH, FX_SIGNAL = "Y", "Z", "AA", "AB", "AC", "AD", "AE"


def rv(s, col, r, user=None):
    return cell(s, "DİBS RV!%s%d" % (col, r), user)


def row_of(s, isin):
    return next(r for r in range(5, 55) if rv(s, "A", r) == isin)


def summary(s, user):
    return next(p for p in s.view(user, "dibslive")["panels"] if p["id"] == "L0")["data"]


def line_of(d, isin):
    return next(row for row in d["rows"] if len(row) > 2 and row[2].get("t") == isin)


def at(d, line, col):
    return line[d["c"].index(col)]


def by_hand_yield(s, r, dirty):
    """A coupon bond's BIST compound yield at a dirty price - bisection on the sheet's own cash flows and their periods."""
    f = rv(s, "CU", r)
    flows = [(rv(s, index_to_col(col_to_index("ID") + k), r), rv(s, index_to_col(col_to_index("LV") + k), r)) for k in range(24)]
    flows = [(cf, x) for cf, x in flows if cf]
    lo, hi = 0.0, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if sum(cf * (1 + mid / f) ** -x for cf, x in flows) > dirty:
            lo = mid
        else:
            hi = mid
    return (1 + lo / f) ** f - 1


def test_the_fair_yield_and_price_of_a_fixed_coupon_bond_and_a_bill(service):
    """At the fitted curve's ASW (a + b·t + c·t² at the bond's years): the dirty price at the OIS spot is PV − ASW ×
    annuity / 100, at the value date that ÷ the funding factor, the clean one that − the accrued interest; the yield is
    the screen's BIST compound yield of that price.  By hand, from the sheet's own columns: a fixed coupon bond (on the
    curve: its fitted ASW is the sheet's) and a bill (not on it: read off the curve), on OIS and on the FX swap curve."""
    s = service
    u = s.login("Adil Değer")["user"]
    d = summary(s, u)
    for side, (a, b, c), pv, ann, fitted, ycol, pcol in (
            ("OIS", ("CA", "CB", "CC"), "EG", "EE", "FU", OIS_YIELD, OIS_PRICE),
            ("FX", ("XO", "XP", "XQ"), "WX", "WY", "XD", FX_YIELD, FX_PRICE)):
        coef = [rv(s, x, 3) for x in (a, b, c)]
        r = row_of(s, FIXED)
        t = rv(s, "FW", r)
        asw = coef[0] + coef[1] * t + coef[2] * t ** 2
        assert asw == pytest.approx(rv(s, fitted, r), abs=1e-9), side                 # the sheet's own fitted ASW
        dirty = (rv(s, pv, r) - asw * rv(s, ann, r) / 100) / rv(s, "DD", r)
        line = line_of(d, FIXED)
        assert at(d, line, pcol)["v"] == pytest.approx(dirty - rv(s, "CW", r), abs=1e-9), side
        assert at(d, line, ycol)["v"] == pytest.approx(by_hand_yield(s, r, dirty), abs=1e-9), side
        assert at(d, line, ycol)["t"].endswith("%") and "eğri ASW" in at(d, line, ycol)["tip"] and "soft" not in (at(d, line, ycol).get("cls") or "")
        # a bill: read off the curve at its years
        r = row_of(s, BILL)
        t = rv(s, "FW", r)
        assert rv(s, fitted, r) == ""                                                   # (not in the curve)
        dirty = (rv(s, pv, r) - (coef[0] + coef[1] * t + coef[2] * t ** 2) * rv(s, ann, r) / 100) / rv(s, "DD", r)
        line = line_of(d, BILL)
        assert at(d, line, pcol)["v"] == pytest.approx(dirty, abs=1e-9) and rv(s, "CW", r) == 0.0, side
        assert at(d, line, ycol)["v"] == pytest.approx((100 / dirty) ** (365 / rv(s, "DR", r)) - 1, abs=1e-12), side
        assert at(d, line, ycol)["tip"].startswith("Bono eğriye girmez"), side
    # cheap against the curve (ASW above the fitted one): its fair price is above the screen's, its fair yield below
    line = line_of(d, FIXED)
    assert at(d, line, "M")["v"] > 0 and at(d, line, OIS_PRICE)["v"] > rv(s, "O", row_of(s, FIXED))
    assert at(d, line, OIS_YIELD)["v"] < rv(s, "T", row_of(s, FIXED))


def test_at_its_own_asw_a_bond_is_worth_its_price(service):
    """The arithmetic is the sheet's own turned around: at the bond's own ASW the dirty price at the spot is the sheet's,
    and the yield the solver finds at the bond's dirty price is the screen's yield."""
    s = service
    r = row_of(s, FIXED)
    assert rv(s, "EG", r) - rv(s, "EH", r) * rv(s, "EE", r) / 100 == pytest.approx(rv(s, "DI", r), abs=1e-9)
    flows = [(rv(s, index_to_col(col_to_index("ID") + k), r), rv(s, index_to_col(col_to_index("LV") + k), r)) for k in range(24)]
    flows = [(cf, x) for cf, x in flows if cf]
    simple = rvfair.coupon_yield(rv(s, "DH", r), flows, rv(s, "CU", r), 0.25)
    assert simple == pytest.approx(rv(s, "S", r), abs=1e-10)                           # BIST basit getiri
    assert (1 + simple / rv(s, "CU", r)) ** rv(s, "CU", r) - 1 == pytest.approx(rv(s, "T", r), abs=1e-10)
    assert rvfair.bill_yield(100.0, 91.0) == 0.0 and rvfair.bill_yield(0.0, 91.0) is None
    assert rvfair.curve_asw((-300.0, 80.0, -7.0), 2.0) == pytest.approx(-168.0)


def test_every_trading_bond_has_its_fair_values_or_why_not(service, tmp_path):
    """The fair-value columns are there for every bond of the trading list: a value, or a dash whose tip says why - a TLREF
    floater (no curve for its DM), a bond DİBS RV does not price, a bond the FX swap curve does not reach; with no fitted
    curve, none (the reason given).  The card says the same."""
    s = service
    u = s.login("Adil Değer Yok")["user"]
    d = summary(s, u)
    tops = [c.get("t") for c in d["rows"][0] if not c.get("sk")]
    assert tops == ["", "Fiyat", "OIS'e göre", "FX swap'a göre", "Risk", "Carry", "Broker", ""]
    heads = [c["t"] for c in d["rows"][1]]
    assert heads[:12] == ["★", "Kâğıt", "ISIN", "Vade", "Kalan yıl", "Valör", "Bid", "Ask", "Son işlem", "Ne zaman", "Getiri %", "ASW / DM"]
    assert heads[12:21] == ["Adil getiri %", "Adil fiyat", "Pahalı / ucuz", "Sinyal", "ASW FX", "Adil getiri %", "Adil fiyat",
                            "Pahalı / ucuz", "Sinyal"]
    assert heads[21:26] == ["Mod. süre", "DV01 / 1mn", s.USD_DV01_HEAD, "C+R (bp)", "T0→T1 repo %"] and heads[-1] == "Kart"
    assert d["c"][:12] == list("ABCDEFGHIJKL") and d["c"][12:21] == ["Y", "Z", "M", "N", "AA", "AB", "AC", "AD", "AE"]
    lines = [row for row in d["rows"][2:] if row[-1].get("t") == "▸"]
    assert len(lines) == len([v for v in s._list_values(u, "tto", "DİBS RV!A5:A54") if v]) >= 15
    for line in lines:
        for col in (OIS_YIELD, OIS_PRICE, FX_YIELD, FX_PRICE):
            got = at(d, line, col)
            assert type(got.get("v")) is float or (got["t"] == "–" and "adil değer yok" in got["tip"]), (line[2]["t"], col, got)
    why = {isin: at(d, line_of(d, isin), OIS_YIELD).get("tip") for isin in (TLREF, NO_PRICE)}
    assert "TLREF'e endeksli" in why[TLREF] and "Fiyat yok" in why[NO_PRICE]
    assert "bu vadeye uzanmıyor" in at(d, line_of(d, LONG), FX_YIELD)["tip"] and type(at(d, line_of(d, LONG), OIS_YIELD)["v"]) is float
    # the FX side's own columns are DİBS RV's
    r = row_of(s, FIXED)
    line = line_of(d, FIXED)
    assert (at(d, line, FX_ASW)["v"], at(d, line, FX_RICH)["v"], at(d, line, FX_SIGNAL)["t"]) == (rv(s, "BF", r), rv(s, "BH", r), rv(s, "BI", r))
    # the card: the same numbers
    card = {x["name"]: x for x in s.bond_card(u, FIXED)["rv"]}
    assert card["Adil getiri (OIS eğrisi)"]["t"] == at(d, line, OIS_YIELD)["t"] and card["Adil fiyat (FX swap eğrisi)"]["t"] == at(d, line, FX_PRICE)["t"]
    assert card["Adil fiyat (OIS eğrisi)"]["tip"] == at(d, line, OIS_PRICE)["tip"]
    assert {x["name"]: x for x in s.bond_card(u, TLREF)["rv"]}["Adil fiyat (OIS eğrisi)"]["t"] == "–"
    # no fitted curve (here: its coefficient typed over by hand), no fair value - and the reason
    other = s.login("Eğrisiz Masa")["user"]
    assert s.set_inputs(other, "tto", [{"ref": "DİBS RV!CA3", "value": "yok"}], allow_adhoc=True)["errors"] == []
    d2 = summary(s, other)
    assert all(at(d2, line, OIS_YIELD)["t"] == "–" for line in d2["rows"][2:] if line[-1].get("t") == "▸")
    for isin in (FIXED, BILL):
        assert "OIS ASW eğrisi uydurulamadı" in at(d2, line_of(d2, isin), OIS_YIELD)["tip"]
    assert type(at(d2, line_of(d2, FIXED), FX_YIELD)["v"]) is float                   # (the FX curve is still there)
    s.reset_inputs(other, "tto")
    assert cell(s, "DİBS RV!CA3", user_key(other)) == rv(s, "CA", 3)

