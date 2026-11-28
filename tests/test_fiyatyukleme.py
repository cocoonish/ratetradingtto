"""Kâğıt Fiyat Yükleme (20.11.2026; the desk: "Bir de kağıt fiyat yükleme sekmesi açmamız gerekli. Bu sekmede BBG/İhale
olarak iki seçim olacak. ..."): ``tto/fiyatyukleme.py`` on its own - the auction text read (every line type, the lines
ignored, dd/mm/yy), each line's bond by maturity and tag, an ambiguous one unrecognised and the desk's naming used the
next time, .t1 over .t2, a bill's simple yield to its t0 price and back, a fixed coupon bond's price at T+1 to its yield to
its t0 price (against rvfair's own Newton and quantcurve's accrued interest), the spreads (defaults, a bond's own, skew,
price spreads for TLREF / TÜFE), a bill's last trade read as a price or a yield, the txt's lines to the character - and on
the replay day: the desk's list kept, one for everyone (25.11.2026: its bonds, spreads, Mid / Bid/Ask, defaults and fixed
prices; the mode, the text and the saved files each user's own; made once from the users' own lists before it), İhale's
Hesapla and the auction values kept desk-wide, the file and its second download, an edited cell's other half; BBG: the
trading list's last trade from DİBS RV without a request, a bond off it asked once (2 hits) and not again for 5 minutes, a
trade that is not today's moved from the last auction with the bond curve (Nelson-Siegel, the closes made up) or - without
that - TRY OIS, said on the row; Mid or Bid/Ask (23.11.2026): kept with the list by ISIN across a list change, "Tümü",
Mid as before, a DİBS RV bond's sides from the sheet, an off-list DİBS's
and a Eurobond's from PX_BID / PX_ASK asked only for them (the hits counted), no live order or bid = ask from the mid; the
provider's one-off request counted and kept nowhere (in process and through the helper); and the HTTP routes (last: the
client stops the service)."""
from __future__ import annotations

import datetime as dt
import json
import time

import pytest
from starlette.testclient import TestClient

import fake_blpapi
from conftest import ANON, auth, cell, make_service
from tto import bonds as bd
from tto import fiyatyukleme as fy
from tto import pricing as pr
from tto import quantcurve as qc
from tto import rvfair
from tto.marketdata import ReplayProvider
from tto.marketdata.bloomberg import BloombergProvider
from tto.server import create_app
from tto.service import ServiceError

SAMPLE = """Auction prices:
06/01/2027.t1   31.500
10/02/2027zc.t1   31.700
10/02/2027.t1   99.500
13/01/27 TLREF.t1   100.500
02/05/2029 cpi.t1   91.900
10/02/2027.t2   99.545
** Min 50 mio, Increment 1 mio
Auction starts in a minute...
"""
ZERO, BILL, FIXED, TLREF, CPI = "TRT060127T10", "TRB100227T13", "TRT100227T13", "TRT130127T11", "TRT020529T18"
REPLAY_DAY = dt.date(2026, 11, 3)


def _valid(body: str) -> str:
    """An ISIN with the check digit that makes it valid (made up)."""
    return next(body + str(d) for d in range(10) if bd.isin_valid(body + str(d)))


#: three made-up Eurobonds: a USD one (30/360, semi-annual, T+1), a EUR one (ACT/ACT, annual, T+2) whose PX_MID is empty, and
#: a USD one whose Bloomberg yield and price disagree with the street convention (the anchor flagged)
EURO1, EURO2, EURO3 = _valid("US900123ZZ1"), _valid("XS298765432"), _valid("US900123ZY2")
#: EURO1's mid: its street convention price at the mid yield 6,85 % (settled 04.11.2026) and 0,012 more - a convention
#: a little off Bloomberg's, as any will be
E1_MID = round(fy.Street(dt.date(2034, 5, 15), 7.625, 2, "30u").clean(0.0685, dt.date(2026, 11, 4)) + 0.012, 3)
EURO_FACTS = {
    EURO1: {"NAME": "TURKIYE REPUBLIC OF", "SECURITY_DES": "TURKEY 7 5/8 05/15/34", "CRNCY": "USD", "CPN": 7.625, "CPN_TYP": "FIXED",
            "CPN_FREQ": 2.0, "DAY_CNT_DES": "30/360", "MATURITY": "15.05.2034", "FIRST_CPN_DT": "15.11.2024", "PENULTIMATE_CPN_DT": "15.11.2033",
            "INT_ACC_DT": "15.05.2024", "DAYS_TO_SETTLE": 1.0, "PX_MID": E1_MID, "YLD_YTM_MID": 6.85},
    EURO2: {"NAME": "TURKIYE REPUBLIC OF", "SECURITY_DES": "TURKEY 4 1/2 07/08/29", "CRNCY": "EUR", "CPN": 4.5, "CPN_TYP": "FIXED",
            "CPN_FREQ": 1.0, "DAY_CNT_DES": "ACT/ACT", "MATURITY": "8.07.2029", "FIRST_CPN_DT": "8.07.2025", "INT_ACC_DT": "8.07.2024",
            "DAYS_TO_SETTLE": 2.0, "PX_MID": "#N/A N/A", "PX_BID": 99.8, "PX_ASK": 100.2, "YLD_YTM_MID": 4.48},
    EURO3: {"NAME": "TURKIYE REPUBLIC OF", "SECURITY_DES": "TURKEY 6 01/14/41", "CRNCY": "USD", "CPN": 6.0, "CPN_TYP": "FIXED",
            "CPN_FREQ": 2.0, "MATURITY": "14.01.2041", "PX_MID": 90.0, "YLD_YTM_MID": 6.0},
}


# ================================================================================================== the auction text
def test_parsing_the_sample_every_line_type_and_the_lines_ignored():
    got = fy.parse(SAMPLE)
    lines = got["lines"]
    assert [x["text"] for x in got["ignored"]] == ["Auction prices:", "** Min 50 mio, Increment 1 mio", "Auction starts in a minute..."]
    assert [(x["n"], x["label"], x["key"], x["date"], x["tag"], x["tn"], x["value"]) for x in lines] == [
        (2, "06/01/2027", "06/01/2027", "2027-01-06", "", 1, 31.5),
        (3, "10/02/2027zc", "10/02/2027 zc", "2027-02-10", "zc", 1, 31.7),
        (4, "10/02/2027", "10/02/2027", "2027-02-10", "", 1, 99.5),
        (5, "13/01/27 TLREF", "13/01/2027 tlref", "2027-01-13", "tlref", 1, 100.5),          # dd/mm/yy: 27 is 2027
        (6, "02/05/2029 cpi", "02/05/2029 cpi", "2029-05-02", "cpi", 1, 91.9),
        (7, "10/02/2027", "10/02/2027", "2027-02-10", "", 2, 99.545)]
    assert not any("why" in x for x in lines)
    # a line that starts with a date but cannot be read, a date that does not exist, a .t3, a comma decimal, a tag unknown
    odd = fy.parse("31/02/2027.t1 99.5\n10/02/2027.t3 99.5\n10/02/2027 99.5\n06/01/2027.t1 31,25\n15/03/2028 XYZ.t2 100\n\n  \n")
    why = [(x["n"], x.get("why", "")[:20], x.get("value"), x.get("tag")) for x in odd["lines"]]
    assert why[0][:2] == (1, "tarih geçersiz: 31/0") and why[1][:2] == (2, "valör .t3 bilinmiyor")
    assert why[2][:2] == (3, "satır okunamadı (bek") and why[3] == (4, "", 31.25, "") and why[4] == (5, "", 100.0, "xyz")
    assert odd["ignored"] == []
    assert fy.label_key(dt.date(2027, 1, 13), "tlref") == "13/01/2027 tlref"


def _pool():
    """A small catalog: a fixed coupon bond and a bill the same day, a zero alone, a TLREF floater, two CPI linkers the same
    day and a fixed coupon bond a few days from them."""
    def b(isin, kind, mat, cpn=None):
        return {"isin": isin, "kind": kind, "maturity": mat, "name": isin, "coupon": cpn}
    return [b("TRT100227T13", "fixed", "2027-02-10", 32.6), b("TRB100227T13", "bill", "2027-02-10"), b("TRT060127T10", "zero", "2027-01-06"),
            b("TRT130127T11", "float", "2027-01-13"), b("TRT080530T19", "cpi", "2030-05-08", 3.0), b("TRT080530T27", "cpi", "2030-05-08", 2.5),
            b("TRT150530T10", "fixed", "2030-05-15", 30.0)]


def test_matching_by_maturity_and_tag_ambiguous_unrecognised_and_named_once():
    pool = _pool()
    text = SAMPLE + "08/05/2030 cpi.t1 95.000\n01/01/2031.t1 99\n08/05/2030 frn.t1 99\n10/02/2027 xyz.t1 99\n"
    lines = fy.parse(text)["lines"]
    fy.match(lines, {}, pool)
    by = {x["n"]: x for x in lines}
    # no tag: the fixed coupon bond (a bill matures that day too); the bill only where no coupon bond does (a zero here)
    assert by[4]["isin"] == "TRT100227T13" and by[2]["isin"] == "TRT060127T10" and by[3]["isin"] == "TRB100227T13"
    assert by[5]["isin"] == "TRT130127T11" and all(by[n]["how"] == "vade + etiket" for n in (2, 3, 4, 5))
    assert "isin" not in by[6] and "vadeli TÜFE'ye endeksli kâğıt yok" in by[6]["why"]           # (02.05.2029: not in this pool)
    # two CPI linkers the same day: unrecognised, with the bonds near its date to pick from
    amb = next(x for x in lines if x["text"].startswith("08/05/2030 cpi"))
    assert "birden çok kâğıt" in amb["why"] and "TRT080530T19" in amb["why"] and "TRT080530T27" in amb["why"]
    assert [b["isin"] for b in amb["near"]][:3] == ["TRT080530T19", "TRT080530T27", "TRT150530T10"]
    none = next(x for x in lines if x["text"].startswith("01/01/2031"))
    assert "vadeli sabit kuponlu (yoksa bono / kuponsuz) kâğıt yok" in none["why"] and none["near"] == []
    assert "kâğıt yok" in next(x for x in lines if x["text"].startswith("08/05/2030 frn"))["why"]
    assert "etiket bilinmiyor: xyz" in next(x for x in lines if "xyz" in x["text"])["why"]
    # .t1 over .t2: the .t2 line of the same bond is read but not used; a .t2 alone is used
    assert by[4]["used"] and not by[7]["used"] and "aynı kâğıdın .t1 satırı kullanıldı (satır 4)" == by[7]["unused"]
    only2 = fy.parse("10/02/2027.t2 99.545\n")["lines"]
    fy.match(only2, {}, pool)
    assert only2[0]["used"] and only2[0]["isin"] == "TRT100227T13"
    # the desk names the ambiguous label once: from then on it is that bond, whatever the candidates
    named = {"08/05/2030 cpi": {"isin": "TRT080530T27", "by": "ayse", "at": "2026-11-20 09:00:00"}}
    again = fy.parse("08/05/2030 cpi.t1 95.000\n")["lines"]
    fy.match(again, named, pool)
    assert again[0]["isin"] == "TRT080530T27" and again[0]["how"] == "tanıtıldı (ayse)" and again[0]["used"]


# ================================================================================================== price <-> yield
def test_a_bills_simple_yield_to_its_t0_price_and_back():
    rec = {"isin": "TRB100227T13", "kind": "bill", "maturity": "2027-02-10", "name": "x"}
    bond = fy.bond_of(rec)
    t1, t0 = dt.date(2026, 11, 4), dt.date(2026, 11, 3)
    y = 0.317                                                   # the auction's 31.700
    p0 = fy.price_of(bond, y, t0)
    assert p0 == pytest.approx(100.0 / (1.0 + y * 99 / 365.0), abs=1e-12)        # 99 days from t0: (100/P − 1)·365/days
    assert fy.yield_of(bond, p0, t0) == pytest.approx(y, abs=1e-13)
    assert fy.price_of(bond, y, t1) == pytest.approx(100.0 / (1.0 + y * 98 / 365.0), abs=1e-12)
    assert fy.bond_of({"isin": "TRT060127T10", "kind": "zero", "maturity": "2027-01-06"}).kind == "bill"     # a zero alike


def test_a_fixed_coupon_bonds_price_at_t1_to_its_yield_to_its_t0_price():
    """10/02/2027.t1 99.500: the clean price at T+1, its BIST simple yield - the rate that discounts the coupons at (1 + y/f)
    a period from the dirty price (+ the accrued interest) -, the same yield at t0."""
    rec = {"isin": "TRT100227T13", "kind": "fixed", "maturity": "2027-02-10", "name": "x", "coupon": 32.6}
    bond = fy.bond_of(rec)
    t1, t0 = dt.date(2026, 11, 4), dt.date(2026, 11, 3)
    y = fy.yield_of(bond, 99.5, t1)
    # the repo's own: quantcurve's cash flows and accrued interest, rvfair's Newton (DİBS RV's / the auction sheet's)
    flows, frac = bond.flows(t1)
    acc1 = qc.accrued(bond, t1)
    assert acc1 == pytest.approx(16.3 * (1.0 - 98 / 182.0), abs=1e-12)          # c/f × the share of the period gone
    want = rvfair.coupon_yield(99.5 + acc1, [(cf, k + frac) for k, (_, cf) in enumerate(flows)], 2.0, 0.3)
    assert y == pytest.approx(want, abs=1e-12) and 0.33 < y < 0.34
    p0 = fy.price_of(bond, y, t0)
    flows0, frac0 = bond.flows(t0)
    dirty0 = sum(cf * (1.0 + y / 2.0) ** -(k + frac0) for k, (_, cf) in enumerate(flows0))
    assert p0 == pytest.approx(dirty0 - qc.accrued(bond, t0), abs=1e-10)
    assert fy.yield_of(bond, p0, t0) == pytest.approx(y, abs=1e-12)
    assert p0 < 99.5                                            # (below par: a day earlier, a little lower at the same yield)
    assert fy.bond_of(dict(rec, coupon=None)) is None and fy.bond_of(dict(rec, kind="float")) is None


# ================================================================================================== spreads
def test_spreads_defaults_a_bonds_own_skew_and_price_spreads():
    bond = fy.bond_of({"isin": "TRB100227T13", "kind": "bill", "maturity": "2027-02-10"})
    t0 = dt.date(2026, 11, 3)
    defaults = dict(fy.DEFAULTS)
    assert defaults == {"yield_bid": 5.0, "yield_ask": 5.0, "price_bid": 0.05, "price_ask": 0.05, "euro_bid": 2.0, "euro_ask": 2.0}
    sp = fy.FiyatYukleme.spreads_of({"isin": "x"}, "bill", defaults)
    assert (sp["bid"], sp["ask"], sp["unit"], sp["own_bid"]) == (5.0, 5.0, "bp", False)
    q = fy.quote("bill", bond, t0, 0.317, None, sp["bid"], sp["ask"])
    assert q["bid_yield"] == pytest.approx(31.75) and q["ask_yield"] == pytest.approx(31.65)
    assert q["bid_price"] < q["ask_price"] and q["bid_price"] == pytest.approx(fy.price_of(bond, 0.3175, t0))
    # a bond's own spread on one side, the default on the other; skew: a negative spread
    own = fy.FiyatYukleme.spreads_of({"isin": "x", "bid": -2.0, "ask": None}, "fixed", defaults)
    assert (own["bid"], own["ask"], own["own_bid"], own["own_ask"]) == (-2.0, 5.0, True, False)
    fixed = fy.bond_of({"isin": "TRT100227T13", "kind": "fixed", "maturity": "2027-02-10", "coupon": 32.6})
    q = fy.quote("fixed", fixed, t0, 0.334, None, own["bid"], own["ask"])
    assert q["bid_yield"] == pytest.approx(33.38) and q["ask_yield"] == pytest.approx(33.35)
    # TLREF / TÜFE: price spreads (price points), no yields
    for kind in ("float", "cpi", "frn"):
        p = fy.FiyatYukleme.spreads_of({"isin": "x"}, kind, defaults)
        assert p["unit"] == "price" and (p["bid"], p["ask"]) == (0.05, 0.05)
        q = fy.quote(kind, None, t0, None, 100.5, p["bid"], p["ask"])
        assert q == {"bid_yield": None, "ask_yield": None, "bid_price": pytest.approx(100.45), "ask_price": pytest.approx(100.55)}
    q = fy.quote("cpi", None, t0, None, 91.9, 0.10, -0.02)
    assert q["bid_price"] == pytest.approx(91.80) and q["ask_price"] == pytest.approx(91.88)


def test_the_txt_lines_to_the_character():
    assert fy.txt_line("TRT060127T10", "zero", 94.76, 94.77, 31.55, 31.45) == "TRT060127T10,0,0,31.550,31.450"
    assert fy.txt_line("TRB100227T13", "bill", None, None, 31.75, 31.65) == "TRB100227T13,0,0,31.750,31.650"
    assert fy.txt_line("TRT100227T13", "fixed", 99.48635, 99.51128, 33.437, 33.337) == "TRT100227T13,99.486,99.511,0,0"
    assert fy.txt_line("TRT130127T11", "float", 100.45, 100.55, None, None) == "TRT130127T11,100.450,100.550,0,0"
    assert fy.txt_line("TRT020529T18", "cpi", 91.85, 91.95, None, None) == "TRT020529T18,91.850,91.950,0,0"
    assert fy.txt_line("x", "bill", 99.0, 99.1, None, 31.0) is None and fy.txt_line("x", "fixed", None, 99.1, 33.0, 32.9) is None
    assert fy.txt_line("x", "fixed", 0.0, 99.1, None, None) is None
    text = fy.txt(["A,0,0,1.000,2.000", "B,100.200,100.400,0,0"])
    assert text == "A,0,0,1.000,2.000\r\nB,100.200,100.400,0,0\r\n" and text.encode("ascii")
    assert fy.file_name(dt.date(2026, 11, 20)) == "dibs_fiyat_20261120.txt"
    assert fy.f3(100.2) == "100.200" and fy.f3(31.4999999) == "31.500"


def test_the_street_convention_of_a_eurobond_on_known_examples():
    """A US-style bond, 30/360 semi-annual: Excel's own PRICE / YIELD examples, and one worked by hand; ACT/ACT annual."""
    us = fy.Street(dt.date(2017, 11, 15), 5.75, 2, "30u")
    s = dt.date(2008, 2, 15)
    assert us.clean(0.065, s) == pytest.approx(94.63436162, abs=1e-8)                 # PRICE(…, 5,75 %, 6,5 %, 100, 2, 0)
    assert fy.Street(dt.date(2016, 11, 15), 5.75, 2, "30u").yield_of(95.04287, s) == pytest.approx(0.065, abs=1e-7)   # YIELD's
    # by hand: 6 % semi-annual to 15.11.2027, settled 04.11.2026 - the coupon before 15.05.2026 (A = 169 days by 30/360), three
    # coupons left, DSC = 180 − 169 = 11 days: P = 3/1.03^(11/180) + 3/1.03^(1 + 11/180) + 103/1.03^(2 + 11/180) − 3·169/180
    b = fy.Street(dt.date(2027, 11, 15), 6.0, 2, "30u")
    s = dt.date(2026, 11, 4)
    w = 11 / 180.0
    hand = 3 / 1.03 ** w + 3 / 1.03 ** (1 + w) + 103 / 1.03 ** (2 + w) - 3 * 169 / 180.0
    assert b.at(s)[:4] == (180.0, 169.0, 11.0, 3) and b.accrued(s) == pytest.approx(3 * 169 / 180.0)
    assert b.clean(0.06, s) == pytest.approx(hand, abs=1e-12) and b.yield_of(hand, s) == pytest.approx(0.06, abs=1e-12)
    assert b.clean(0.06, dt.date(2026, 11, 15)) == pytest.approx(100.0, abs=1e-12)    # on a coupon date at its coupon: par
    # the last coupon period: simple interest, (100 + c/f) / (1 + DSC/E · y/f)
    assert b.clean(0.07, dt.date(2027, 8, 15)) == pytest.approx(103 / (1 + 90 / 180.0 * 0.035) - 3 * 90 / 180.0, abs=1e-12)
    # ACT/ACT annual: the period's actual days (365), the days left (8.07.2026 -> 5.11.2026: 120 of 365 gone)
    eur = fy.Street(dt.date(2029, 7, 8), 4.5, 1, "act")
    s = dt.date(2026, 11, 5)
    e, a, dsc, n, cpn, _ = eur.at(s)
    assert (e, a, dsc, n, cpn) == (365.0, 120.0, 245.0, 3, 4.5)
    w = 245 / 365.0
    assert eur.clean(0.05, s) == pytest.approx(4.5 / 1.05 ** w + 4.5 / 1.05 ** (1 + w) + 104.5 / 1.05 ** (2 + w) - 4.5 * 120 / 365.0, abs=1e-12)
    # the day counts on the 31st: 30/360 US and ISMA's 30E/360
    assert fy.Street(dt.date(2030, 1, 1), 5, 2, "30u").days(dt.date(2026, 1, 31), dt.date(2026, 3, 31)) == 60.0
    assert fy.Street(dt.date(2030, 1, 1), 5, 2, "30e").days(dt.date(2026, 1, 30), dt.date(2026, 3, 31)) == 60.0
    assert fy.Street(dt.date(2030, 1, 1), 5, 2, "30u").days(dt.date(2026, 1, 15), dt.date(2026, 3, 31)) == 76.0
    assert fy.edate(dt.date(2027, 3, 31), -1) == dt.date(2027, 2, 28)
    assert fy.basis_of("ISMA-30/360", "USD")[0] == "30e" and fy.basis_of("#N/A Field Not Applicable", "EUR")[0] == "act"


def test_the_anchor_to_bloombergs_mid_and_the_yield_spreads():
    """price(y) = the convention's price(y) + (PX_MID − the convention's price at Bloomberg's mid yield): the mid is
    Bloomberg's to the digit; the sides move by the convention's slope."""
    rec, why = fy.euro_record(EURO1, EURO_FACTS[EURO1])
    assert why == "" and rec["kind"] == fy.EURO and rec["ccy"] == "USD" and rec["basis"] == "30u" and rec["freq"] == 2
    assert rec["settle_days"] == 1 and rec["maturity"] == "2034-05-15" and rec["name"] == "TURKEY 7 5/8 05/15/34"
    bond = fy.street_of(rec)
    s = dt.date(2026, 11, 4)
    anchor = fy.anchored(bond, s, 104.25, 0.0685)
    assert bond.clean(0.0685, s) + anchor == 104.25
    bid, ask = bond.clean(0.0687, s) + anchor, bond.clean(0.0683, s) + anchor
    assert bid < 104.25 < ask and (104.25 - bid) == pytest.approx(0.02 * 1e-2 * -(bond.clean(0.068501, s) - bond.clean(0.068499, s)) / 2e-6, rel=1e-3)
    # what Bloomberg's facts may not give: the day count (USD: 30/360), the lag (T+2); a TL bond, a floater, an unknown one
    r3, _ = fy.euro_record(EURO3, EURO_FACTS[EURO3])
    assert (r3["basis"], r3["settle_days"], r3["basis_text"]) == ("30u", None, "30/360 (DAY_CNT_DES yok: USD'nin)")
    assert fy.euro_record("X", dict(EURO_FACTS[EURO1], CRNCY="TRY"))[1].startswith("TL kâğıt")
    assert "değişken kuponlu" in fy.euro_record("X", dict(EURO_FACTS[EURO1], CPN_TYP="FLOATING"))[1]
    assert fy.euro_record("X", {"CRNCY": "#N/A Invalid Security", "CPN_TYP": "#N/A Invalid Security"}) == (None, "Bloomberg bu ISIN'i tanımıyor")
    # its spreads: bp of its yield, its own (tighter) default pair; its line: clean prices, yields 0
    sp = fy.FiyatYukleme.spreads_of({"isin": EURO1}, fy.EURO, dict(fy.DEFAULTS))
    assert (sp["bid"], sp["ask"], sp["unit"]) == (2.0, 2.0, "bp")
    assert fy.txt_line(EURO1, fy.EURO, 104.1234, 104.3766, 6.87, 6.83) == "%s,104.123,104.377,0,0" % EURO1


def test_a_bills_last_trade_is_read_as_a_price_or_a_yield():
    # DİBS RV!AS of a 99-day bill: 92,147 - a price (its yield 31,4 %)
    y, how = fy.bill_last(92.147, 99.0)
    assert how == "fiyat" and y == pytest.approx((100.0 / 92.147 - 1.0) * 365.0 / 99.0)
    # 31,4 as a price would be 806 %: a yield
    y, how = fy.bill_last(31.4, 99.0)
    assert y == pytest.approx(0.314) and how.startswith("getiri olarak okundu")
    # both in reach (a 2-year zero quoted 45): the reading nearer the bond's own yield
    assert fy.bill_last(45.0, 730.0, ref=0.31)[0] == pytest.approx(0.45)
    assert fy.bill_last(61.7, 730.0, ref=0.31)[1] == "fiyat"
    assert fy.bill_last(250.0, 99.0) == (None, "son işlem okunamadı: 250,000")          # neither a bill's price nor a yield


def test_the_page_is_a_tab_of_dibs_fiyatlama_in_the_tahvil_menu(module_service):
    # (the menu's reorganization of 28.11.2026, tto/navmenu.py: "Sabah fiyat dosyası", a tab of DİBS Fiyatlama)
    nav = module_service.nav(module_service.login("Yükleme Menü")["user"])
    entry = [(p["id"], p["tab"]) for p in nav if p.get("menu") == "tahvil.fiyatlama"]
    assert entry == [("kagit-fiyat", "Adil fiyat · AL/SAT"), ("manuel", "Tek kâğıt"), ("fiyat-yukleme", "Sabah fiyat dosyası"),
                     ("ihale", "İhale")]
    assert {p["group"] for p in nav if p.get("menu") == "tahvil.fiyatlama"} == {"Tahvil"}
    page = next(p for p in nav if p["id"] == "fiyat-yukleme")
    assert page["title"] == "Kâğıt Fiyat Yükleme" and page["custom"]
    assert fy.menu([{"id": "usd", "title": "USD", "group": "USD"}]) == [{"id": "usd", "title": "USD", "group": "USD"}]


# ================================================================================================== on the replay day
@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def call(svc, user, what, body=None):
    return svc.fiyat_yukleme(user, what, body or {})


def fresh(s):
    """The desk's list emptied - it is everyone's since 25.11.2026, so a test starts from none (not from another's)."""
    s.store.put(fy.KEY_DESK, {"bonds": [], "defaults": {}, "fixed": []})


def test_the_list_is_the_desks_and_stays(svc):
    """(the desk, 25.11.2026: "Kağıt fiyat yüklemedeki isin listesi tüm masa için olmalı") One list for everyone: what a
    user adds, sets or takes off is the desk's - its bonds, each one's spreads, the defaults; the mode stays each user's
    own; kept (a new instance of the module: the store's); a change is a new generation and a new revision - a page asking
    by the one it has hears "unchanged" until then."""
    fresh(svc)
    u = svc.login("Yükleme Liste")["user"]
    other = svc.login("Yükleme Başka")["user"]
    gen = svc.gen
    st = call(svc, u, "ekle", {"isins": "%s, %s\n%s %s\t%s" % (ZERO, BILL, FIXED, TLREF, CPI)})
    assert svc.gen > gen and st["rev"] >= 1 and st["desk"]["by"] == u
    assert st["added"] == [ZERO, BILL, FIXED, TLREF, CPI] and st["skipped"] == [] and st["refused"] == []
    rows = {r["isin"]: r for r in st["list"]}
    assert [r["isin"] for r in st["list"]] == [BILL, ZERO, FIXED, TLREF, CPI]          # by kind, then maturity
    assert rows[FIXED]["name"] == "TURKGB 32.6 02/10/27" and rows[FIXED]["maturity"] == "2027-02-10" and rows[FIXED]["kind_text"] == "Sabit"
    assert rows[TLREF]["spread"]["unit"] == "price" and rows[BILL]["spread"]["unit"] == "bp" and rows[BILL]["write"] == "yield"
    assert rows[FIXED]["write"] == "price" and rows[FIXED]["quoted"] == "yield"
    assert call(svc, u, "ekle", {"isins": FIXED})["skipped"] == [FIXED]
    # a bond the catalog does not have: the desk's route needs Bloomberg - offline it cannot come in
    new = next(c for c in ("TRT080931T1%d" % d for d in range(10)) if bd.isin_valid(c))
    got = call(svc, u, "ekle", {"isins": new})
    assert got["added"] == [] and "Bloomberg olmadan eklenemez" in got["refused"][0]["text"]
    # a Eurobond: its facts come from Bloomberg - offline it cannot come in either, and says why
    got = call(svc, u, "ekle", {"isins": EURO1})
    assert got["added"] == [] and got["refused"] == [{"isin": EURO1, "text": "Eurobond'un bilgileri (vade, kupon, gün sayımı) Bloomberg'den "
                                                                           "gelir: kayıtlı veriyle çalışırken eklenemez"}]
    with pytest.raises(ServiceError) as e:
        call(svc, u, "ekle", {"isins": "TRT150328T25"})
    assert "kontrol hanesi" in str(e.value)
    # the desk's: another user has the same list (and adds nothing new by adding it); it stays (a new page, a new
    # instance of the module: the store's)
    assert [r["isin"] for r in call(svc, other, "state")["list"]] == [BILL, ZERO, FIXED, TLREF, CPI]
    assert call(svc, other, "ekle", {"isins": BILL})["skipped"] == [BILL]
    again = fy.FiyatYukleme(svc).state(u)
    assert [r["isin"] for r in again["list"]] == [BILL, ZERO, FIXED, TLREF, CPI]
    # a bond's own spreads, the defaults, the mode; × takes a bond off
    st = call(svc, u, "ayar", {"spreads": {FIXED: {"bid": "7,5", "ask": ""}, TLREF: {"bid": "0,10"}}, "defaults": {"yield_ask": "4"}, "mode": "bbg"})
    rows = {r["isin"]: r for r in st["list"]}
    assert rows[FIXED]["spread"] == {"bid": 7.5, "ask": 4.0, "own_bid": True, "own_ask": False, "unit": "bp"}
    assert rows[TLREF]["spread"]["bid"] == 0.10 and rows[TLREF]["spread"]["own_bid"] and st["mode"] == "bbg"
    # ... the other user's too - not the mode: theirs
    o = call(svc, other, "state")
    assert {r["isin"]: r for r in o["list"]}[FIXED]["spread"] == rows[FIXED]["spread"] and o["defaults"]["yield_ask"] == 4.0
    assert o["mode"] == "ihale" and (o["rev"], o["desk"]["by"]) == (st["rev"], u)
    with pytest.raises(ServiceError) as e:
        call(svc, u, "ayar", {"spreads": {FIXED: {"bid": "900"}}, "mode": "ihale"})
    assert "bp" in str(e.value) and "arasında" in str(e.value) and call(svc, u, "state")["mode"] == "bbg"      # (all or nothing)
    # × by the other user: off for everyone
    st = call(svc, other, "cikar", {"isin": CPI})
    assert CPI not in [r["isin"] for r in call(svc, u, "state")["list"]] and st["desk"]["by"] == other
    with pytest.raises(ServiceError):
        call(svc, u, "cikar", {"isin": CPI})
    # asked by the revision the page has: unchanged until somebody changes the list; the mode alone is not the list's
    rev = call(svc, u, "state")["rev"]
    assert call(svc, u, "state", {"rev": rev}) == {"rev": rev, "unchanged": True}
    assert call(svc, u, "ayar", {"mode": "ihale"})["rev"] == rev and call(svc, other, "state", {"rev": str(rev)})["unchanged"]
    st = call(svc, u, "ayar", {"spreads": {FIXED: {"bid": None}}, "defaults": {"yield_ask": 5}, "mode": "ihale"})
    assert {r["isin"]: r for r in st["list"]}[FIXED]["spread"]["own_bid"] is False and st["rev"] == rev + 1
    got = call(svc, other, "state", {"rev": rev})
    assert "unchanged" not in got and got["rev"] == rev + 1 and got["defaults"]["yield_ask"] == 5.0


def test_the_desks_list_is_made_once_from_the_users_own_lists(tmp_path):
    """Before 25.11.2026 each user had a list of their own: the first time the desk's list is asked for, it is made from
    them - every bond and every fixed price anyone had, by ISIN; a bond two users had with different settings, and the
    defaults: the latest user's (the newest stamp in their records: a bond added, a fixed price set, a file saved); a
    fixed price two had: the one set last.  Each user's mode and text stay theirs, their old keys as they were; made once
    (a bond taken off later does not come back)."""
    s = make_service(tmp_path)
    try:
        a, b = s.login("Liste Eski")["user"], s.login("Liste Yeni")["user"]
        old_a = {"bonds": [{"isin": FIXED, "bid": 7.0, "ask": None, "base": "bidask", "at": "2026-11-20 09:00:00"},
                           {"isin": TLREF, "bid": 0.1, "ask": None, "at": "2026-11-20 09:01:00"}],
                 "defaults": dict(fy.DEFAULTS, yield_bid=6.0),
                 "fixed": [{"isin": BILL, "bid": 31.4, "ask": 31.3, "at": "2026-11-20 09:05:00"},
                           {"isin": CPI, "bid": 91.0, "ask": 92.0, "at": "2026-11-24 10:00:00"}],
                 "mode": "bbg", "text": "06/01/2027.t1   31.500\n"}
        old_b = {"bonds": [{"isin": FIXED, "bid": 8.0, "ask": 3.0, "at": "2026-11-21 10:00:00"},
                           {"isin": ZERO, "bid": None, "ask": None, "at": "2026-11-21 10:00:00"}],
                 "defaults": {"yield_bid": 4.0, "price_ask": 0.07},
                 "fixed": [{"isin": BILL, "bid": 31.5, "ask": 31.35, "at": "2026-11-21 11:00:00"},
                           {"isin": CPI, "bid": 90.0, "ask": 91.0, "at": "2026-11-21 11:00:00"}],
                 "mode": "ihale", "text": ""}
        s.store.put(fy.KEY_LIST % a, old_a)
        s.store.put(fy.KEY_LIST % b, old_b)
        s.store.put(fy.KEY_SAVED % b, {"2026-11-25": [{"at": "2026-11-25 08:30:00", "name": "x.txt", "text": "", "n": 0}]})  # (b: the latest)
        sa, sb = call(s, a, "state"), call(s, b, "state")
        assert [r["isin"] for r in sa["list"]] == [r["isin"] for r in sb["list"]] == [ZERO, FIXED, TLREF]       # every bond anyone had
        rows = {r["isin"]: r for r in sa["list"]}
        # a bond both had: the latest user's settings (b's spreads, b's Mid - not a's Bid/Ask); a's own one as it was
        assert (rows[FIXED]["spread"]["bid"], rows[FIXED]["spread"]["ask"], rows[FIXED]["base"]) == (8.0, 3.0, "mid")
        assert rows[TLREF]["spread"]["bid"] == 0.1 and rows[TLREF]["spread"]["own_bid"]
        # the defaults: the latest user's (the ones b had not set: the page's own)
        assert sa["defaults"] == sb["defaults"] == dict(fy.DEFAULTS, yield_bid=4.0, price_ask=0.07)
        # every fixed price; one both had: the one set last (a's CPI, set after b's; b's bill)
        assert {r["isin"]: (r["bid"], r["ask"]) for r in sb["fixed"]} == {BILL: (31.5, 31.35), CPI: (91.0, 92.0)}
        # each one's own: the mode and the text
        assert (sa["mode"], sa["text"], sb["mode"], sb["text"]) == ("bbg", old_a["text"], "ihale", "")
        merged = s.store.get(fy.KEY_DESK)["merged"]
        assert (merged["users"], merged["clash"], merged["clash_fixed"], merged["defaults"]) == ([a, b], [FIXED], [BILL, CPI], b)
        # the old keys as they were; once: a bond taken off does not come back (a new instance of the module either)
        assert s.store.get(fy.KEY_LIST % a) == old_a and s.store.get(fy.KEY_LIST % b) == old_b
        call(s, a, "cikar", {"isin": TLREF})
        assert TLREF not in [r["isin"] for r in fy.FiyatYukleme(s).state(b)["list"]]
        # a mode set later: in the user's key, its old fields with it as they were
        call(s, a, "ayar", {"mode": "ihale"})
        assert s.store.get(fy.KEY_LIST % a) == dict(old_a, mode="ihale")
    finally:
        s.stop()


def test_ihale_on_the_replay_day_and_the_values_kept(svc):
    fresh(svc)
    u = svc.login("Yükleme İhale")["user"]
    call(svc, u, "ekle", {"isins": " ".join((ZERO, BILL, FIXED, TLREF, CPI, "TRT150328T24"))})
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": SAMPLE})
    assert res["today"] == "2026-11-03" and res["t0"] == "2026-11-03" and res["file"] == "dibs_fiyat_20261103.txt"
    p = res["parse"]
    assert (p["recognised"], p["unrecognised"], p["stored"], len(p["ignored"])) == (6, 0, 6, 3)
    vd = {ln["n"]: ln["value_date"] for ln in p["lines"]}
    assert vd[4] == "2026-11-04" and vd[7] == "2026-11-05"                       # T+1, T+2 (TRY business days)
    rows = {r["isin"]: r for r in res["rows"]}
    t0 = REPLAY_DAY
    # the bill / zero: the auction's simple yield is t0's, its price at t0
    z = rows[ZERO]
    assert z["priced"] and z["t0"]["yield"] == pytest.approx(31.5) and z["write"] == "yield"
    assert z["t0"]["price"] == pytest.approx(100.0 / (1.0 + 0.315 * 64 / 365.0))
    assert z["bid"]["yield"] == pytest.approx(31.55) and z["ask"]["yield"] == pytest.approx(31.45)
    # the fixed coupon bond: its price at T+1 -> its yield -> the same yield at t0
    bond = fy.bond_of(bd.by_isin(FIXED))
    y = fy.yield_of(bond, 99.5, dt.date(2026, 11, 4))
    f = rows[FIXED]
    assert f["t0"]["yield"] == pytest.approx(y * 100.0) and f["t0"]["price"] == pytest.approx(fy.price_of(bond, y, t0))
    assert f["bid"]["price"] == pytest.approx(fy.price_of(bond, y + 0.0005, t0)) and f["ask"]["price"] == pytest.approx(fy.price_of(bond, y - 0.0005, t0))
    assert "10/02/2027.t1 99,500 (valör 04.11.2026)" in f["how"]
    # TLREF / TÜFE: the auction's clean price is t0's, price spreads
    assert rows[TLREF]["t0"] == {"yield": None, "price": 100.5} and rows[TLREF]["bid"]["price"] == pytest.approx(100.45)
    assert rows[CPI]["ask"]["price"] == pytest.approx(91.95) and "t0 fiyatı olarak" in rows[CPI]["how"]
    # a bond of the list not in the text: no price of its own - its curve price (Kâğıt Fiyatlama's, 20.11.2026): its base
    # now + its spread at its most recent point, DİBS RV's last trade today (on the curve now), said with its typical error
    c = rows["TRT150328T24"]
    assert c["priced"] and c["source"] == "eğri" and c["curve"]["label"] == "eğri + son fark (son işlem 03.11, bugün)" and "why" not in c
    assert c["curve"]["mark"] == "eğri fiyatı (son fark, son işlem 03.11)" and res["curve"] == 1
    assert c["how"].startswith("eğri fiyatı (son fark, son işlem 03.11): bugünkü ihale listesinde yok → eğri %") and "tipik hata" in c["how"]
    assert "DİBS RV 100,200 (valör 04.11; temiz fiyat)" in c["how"] and "şimdiki eğriye göre (bugünkü nokta)" in c["how"]
    assert c["t0"]["yield"] == pytest.approx(c["curve"]["simple"]) and c["bid"]["yield"] == pytest.approx(c["curve"]["simple"] + 0.05)
    # the day's values, desk-wide, per ISIN (date, label, value, .t1 / .t2)
    kept = svc.store.get(fy.KEY_AUCTIONS)
    assert [(a["day"], a["label"], a["value"], a["tn"], a["value_date"]) for a in kept[FIXED]] == [
        ("2026-11-03", "10/02/2027", 99.5, 1, "2026-11-04"), ("2026-11-03", "10/02/2027", 99.545, 2, "2026-11-05")]
    assert fy.last_auction(kept[FIXED])["tn"] == 1 and kept[ZERO][0]["by"] == u
    # pasted again the same day: replaced, not doubled
    call(svc, u, "hesapla", {"mode": "ihale", "text": SAMPLE.replace("99.500", "99.600")})
    assert [a["value"] for a in svc.store.get(fy.KEY_AUCTIONS)[FIXED]] == [99.6, 99.545]
    # no text: a reason
    with pytest.raises(ServiceError) as e:
        call(svc, u, "hesapla", {"mode": "ihale", "text": "  "})
    assert "yapıştırın" in str(e.value)


def test_an_unrecognised_line_is_named_once_and_known_after(svc):
    fresh(svc)
    u = svc.login("Yükleme Tanıt")["user"]
    other = svc.login("Yükleme Tanıt İki")["user"]
    call(svc, u, "ekle", {"isins": "TRT080530T27"})
    text = "08/05/2030 cpi.t1 95.000\n"                       # two CPI linkers mature on 08.05.2030
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": text})
    ln = res["parse"]["lines"][0]
    assert res["parse"]["unrecognised"] == 1 and "birden çok kâğıt" in ln["why"] and ln["key"] == "08/05/2030 cpi"
    assert {"TRT080530T19", "TRT080530T27"} <= {b["isin"] for b in ln["near"]}
    assert res["rows"][0]["why"] == "bugünkü ihale listesinde yok"
    got = call(svc, u, "tanit", {"label": "08/05/2030 cpi", "isin": "TRT080530T27"})
    assert [(x["key"], x["isin"], x["by"]) for x in got["labels"]] == [("08/05/2030 cpi", "TRT080530T27", u)]
    # known from then on - for everyone (desk-wide), with dd/mm/yy too
    res = call(svc, other, "hesapla", {"mode": "ihale", "text": "08/05/30 CPI.t1 95.000\n"})
    ln = res["parse"]["lines"][0]
    assert ln["isin"] == "TRT080530T27" and ln["how"].startswith("tanıtıldı") and res["parse"]["recognised"] == 1
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": text})
    assert res["rows"][0]["priced"] and res["rows"][0]["t0"]["price"] == 95.0
    with pytest.raises(ServiceError) as e:
        call(svc, u, "tanit", {"label": "08/05/2030 cpi", "isin": "TRT080530T28"})
    assert "kontrol hanesi" in str(e.value)
    with pytest.raises(ServiceError) as e:
        call(svc, u, "tanit", {"label": "satır değil", "isin": "TRT080530T27"})
    assert "etiket okunamadı" in str(e.value)
    # listed, and forgotten (anyone may - as the bond list)
    assert call(svc, other, "state")["labels"][0]["key"] == "08/05/2030 cpi"
    assert call(svc, other, "tanit", {"label": "08/05/2030 cpi.t1", "isin": ""})["labels"] == []
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": text})
    assert res["parse"]["unrecognised"] == 1


def test_kaydet_writes_the_desks_file_and_keeps_it_for_today(svc):
    fresh(svc)
    u = svc.login("Yükleme Kaydet")["user"]
    other = svc.login("Yükleme Kaydet İki")["user"]
    call(svc, u, "ekle", {"isins": " ".join((ZERO, BILL, FIXED, TLREF, CPI, "TRT150328T24"))})
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": SAMPLE})
    rows = [{"isin": r["isin"], "bid_price": r["bid"]["price"], "ask_price": r["ask"]["price"], "bid_yield": r["bid"]["yield"],
             "ask_yield": r["ask"]["yield"]} for r in res["rows"]]
    out = call(svc, u, "kaydet", {"rows": rows})
    f = next(r for r in res["rows"] if r["isin"] == FIXED)
    c = next(r for r in res["rows"] if r["isin"] == "TRT150328T24")                  # (not in the text: its curve price)
    assert out["name"] == "dibs_fiyat_20261103.txt" and c["source"] == "eğri"
    assert out["lines"] == ["TRB100227T13,0,0,31.750,31.650", "TRT060127T10,0,0,31.550,31.450",
                            "TRT100227T13,%.3f,%.3f,0,0" % (f["bid"]["price"], f["ask"]["price"]),
                            "TRT150328T24,%.3f,%.3f,0,0" % (c["bid"]["price"], c["ask"]["price"]),
                            "TRT130127T11,100.450,100.550,0,0", "TRT020529T18,91.850,91.950,0,0"]
    assert out["text"] == "".join(x + "\r\n" for x in out["lines"])
    assert out["left_out"] == [] and out["crossed"] == []
    # an edited cell (the bill's bid yield) is written as edited; a crossed quote is named, not refused
    rows[0]["bid_yield"], rows[0]["ask_yield"] = 31.6, 31.7
    out2 = call(svc, u, "kaydet", {"rows": rows})
    assert out2["lines"][0] == "TRB100227T13,0,0,31.600,31.700" and out2["crossed"] == [BILL]
    # the day's last file again: ASCII, CRLF; the saves kept per user and day (the list is the desk's, the files each one's)
    raw, name = call(svc, u, "dosya")
    assert name == "dibs_fiyat_20261103.txt" and raw == out2["text"].encode("ascii") and raw.count(b"\r\n") == 6
    assert [x["n"] for x in call(svc, u, "state")["saved"]] == [6, 6]
    kept = svc.store.get(fy.KEY_SAVED % u)
    assert list(kept) == ["2026-11-03"] and len(kept["2026-11-03"]) == 2
    with pytest.raises(ServiceError) as e:
        call(svc, other, "dosya")
    assert "bugün kaydedilmiş dosya yok" in str(e.value) and call(svc, other, "state")["saved"] == []
    assert call(svc, other, "kaydet", {"rows": rows})["text"] == out2["text"]                  # (the same list: the same file)
    assert [x["n"] for x in call(svc, other, "state")["saved"]] == [6] and len(call(svc, u, "state")["saved"]) == 2
    with pytest.raises(ServiceError) as e:
        call(svc, u, "kaydet", {"rows": [{"isin": "TRT150328T24"}]})
    assert "yazılacak fiyat yok" in str(e.value)
    with pytest.raises(ServiceError) as e:
        call(svc, other, "kaydet", {"rows": [dict(rows[0], isin="TRT080530T27")]})
    assert "listede değil" in str(e.value)


def test_an_edited_cells_other_half(svc):
    u = svc.login("Yükleme Çevir")["user"]
    got = call(svc, u, "cevir", {"isin": FIXED, "field": "yield", "value": "33,5"})
    bond = fy.bond_of(bd.by_isin(FIXED))
    assert got["price"] == pytest.approx(fy.price_of(bond, 0.335, REPLAY_DAY)) and got["value_date"] == "2026-11-03"
    back = call(svc, u, "cevir", {"isin": FIXED, "field": "price", "value": got["price"]})
    assert back["yield"] == pytest.approx(33.5, abs=1e-9)
    bill = call(svc, u, "cevir", {"isin": BILL, "field": "price", "value": "92,08"})
    assert bill["yield"] == pytest.approx((100.0 / 92.08 - 1.0) * 365.0 / 99.0 * 100.0)
    assert call(svc, u, "cevir", {"isin": TLREF, "field": "price", "value": 100.4}) == {"isin": TLREF, "price": 100.4, "yield": None,
                                                                                      "value_date": "2026-11-03"}
    with pytest.raises(ServiceError) as e:
        call(svc, u, "cevir", {"isin": TLREF, "field": "yield", "value": 30})
    assert "fiyatla kote edilir" in str(e.value)
    with pytest.raises(ServiceError) as e:
        call(svc, u, "cevir", {"isin": FIXED, "field": "yield", "value": "abc"})
    assert "sayı" in str(e.value)


# ================================================================================================== Sabit fiyat
def fixed_of(svc, user):
    return {r["isin"]: r for r in call(svc, user, "state")["fixed"]}


def test_fixed_prices_are_the_desks_in_the_txts_unit_and_stay(svc):
    """(the desk, 20.11.2026: "Bir de sabit fiyat kısmı açmalıyız, bazı kağıtları direkt bu şekilde yüklenecek diye girip
    bırakabilmeliyim") A bond's fixed bid / ask, typed in the unit the txt writes it in (a bill's yields, the others'
    clean prices, a Turkish comma read), kept with the desk's list (25.11.2026: everyone's) until changed or taken off."""
    fresh(svc)
    u = svc.login("Sabit Fiyat")["user"]
    other = svc.login("Sabit Fiyat İki")["user"]
    call(svc, u, "sabit", {"isin": BILL, "bid": "31,40", "ask": "31,30"})
    call(svc, u, "sabit", {"isin": FIXED, "bid": "99,250", "ask": 99.75})
    call(svc, u, "sabit", {"isin": TLREF, "bid": "100,25", "ask": "100,75"})
    got = call(svc, u, "sabit", {"isin": CPI, "bid": "91", "ask": "92"})
    f = {r["isin"]: r for r in got["fixed"]}
    assert [r["isin"] for r in got["fixed"]] == [BILL, FIXED, TLREF, CPI]                # (by kind, then maturity)
    assert (f[BILL]["unit"], f[BILL]["bid"], f[BILL]["ask"]) == ("yield", 31.4, 31.3)      # a bill: its simple yields
    assert all(f[c]["unit"] == "price" for c in (FIXED, TLREF, CPI)) and (f[FIXED]["bid"], f[FIXED]["ask"]) == (99.25, 99.75)
    assert f[FIXED]["name"] == "TURKGB 32.6 02/10/27" and f[FIXED]["maturity"] == "2027-02-10" and not f[FIXED]["listed"]
    # changed: the same bond again; taken off; another user has the same ones; kept (a new instance of the module: the store's)
    call(svc, u, "sabit", {"isin": BILL, "bid": "31,5", "ask": "31,35"})
    assert (fixed_of(svc, u)[BILL]["bid"], fixed_of(svc, u)[BILL]["ask"], len(fixed_of(svc, u))) == (31.5, 31.35, 4)
    assert call(svc, u, "sabit-sil", {"isin": TLREF})["fixed_removed"] == TLREF and TLREF not in fixed_of(svc, u)
    with pytest.raises(ServiceError) as e:
        call(svc, u, "sabit-sil", {"isin": TLREF})
    assert "sabit fiyatı yok" in str(e.value)
    assert fixed_of(svc, other) == fixed_of(svc, u) and list(fixed_of(svc, other)) == [BILL, FIXED, CPI]
    assert [r["isin"] for r in fy.FiyatYukleme(svc).state(u)["fixed"]] == [BILL, FIXED, CPI]
    assert call(svc, other, "sabit", {"isin": FIXED, "bid": "99,3", "ask": "99,7"})["desk"]["by"] == other         # (anyone's)
    assert (fixed_of(svc, u)[FIXED]["bid"], fixed_of(svc, u)[FIXED]["ask"]) == (99.3, 99.7)
    # what cannot be fixed: no figures, a price out of reach
    with pytest.raises(ServiceError) as e:
        call(svc, u, "sabit", {"isin": FIXED, "bid": "", "ask": "99"})
    assert "sayı olarak" in str(e.value)
    with pytest.raises(ServiceError) as e:
        call(svc, u, "sabit", {"isin": FIXED, "bid": "0", "ask": "99"})
    assert "temiz fiyat olarak girilir" in str(e.value)
    # no catalog and no Bloomberg needed: a Eurobond whose facts are not held here is fixed all the same (in price)
    e1 = {r["isin"]: r for r in call(svc, u, "sabit", {"isin": EURO1, "bid": "99", "ask": "100"})["fixed"]}[EURO1]
    assert (e1["unit"], e1["name"], e1["maturity"], e1["line"]) == ("price", "", None, "%s,99.000,100.000,0,0" % EURO1)
    call(svc, u, "sabit-sil", {"isin": EURO1})
    # a crossed quote is kept, and said
    assert call(svc, u, "sabit", {"isin": CPI, "bid": "92,5", "ask": "92"})["crossed"] is True


def test_a_bond_with_no_price_gets_its_curve_price_in_both_modes(svc, monkeypatch):
    """(the desk, 20.11.2026: "curve'e göre fiyatı olmayanların da fiyatını bulmak içindi asıl") A yield-quoted bond that
    would get no price - missing from today's auction text (İhale), no trade and no auction kept (BBG) - gets Kâğıt
    Fiyatlama's curve price (its "Fiyat" when not the market's: here, no closes, a fixed coupon bond's curve alone, a zero
    coupon bond's bucket base + the median spread of the market-priced bills), its simple yield at its value date as t0's,
    the row's own spreads on it, marked "eğri fiyatı" / "eğri fiyatı (akran farkı)" - "(son fark)" on its own last spread -
    with how and its typical error; a price-quoted bond does not (no price, why); a fixed price still wins; the file takes
    the curve rows as any yield-quoted ones."""
    fresh(svc)
    u = svc.login("Yükleme Eğri")["user"]
    off, zero2, fixed_one = "TRT090627T12", "TRT210427T18", "TRT110827T16"
    kept = svc.store.get(fy.KEY_AUCTIONS) or {}
    book = {k: v for k, v in kept.items() if k not in (off, zero2, TLREF)}
    svc.store.put(fy.KEY_AUCTIONS, book)
    try:
        call(svc, u, "ekle", {"isins": " ".join((off, zero2, fixed_one, TLREF))})
        call(svc, u, "ayar", {"spreads": {off: {"bid": "7", "ask": "3"}}})
        call(svc, u, "sabit", {"isin": fixed_one, "bid": "88,5", "ask": "88,9"})
        quotes = svc.kagitfiyat.curve_quotes(u, [off, zero2])
        assert (quotes[off]["label"], quotes[zero2]["label"]) == ("eğri", "eğri + akran farkı") and quotes[zero2]["value_date"] == "2026-11-03"
        assert (quotes[off]["tag"], quotes[zero2]["tag"]) == (None, "akran farkı") and "bono / kuponsuz" in quotes[zero2]["how"]
        assert all("tipik hata ±" in quotes[k]["how"] for k in (off, zero2))
        marks = {off: "eğri fiyatı", zero2: "eğri fiyatı (akran farkı)"}
        for mode in ("ihale", "bbg"):
            res = call(svc, u, "hesapla", {"mode": mode, "text": "06/01/2027.t1   31.500\n"})
            rows = {r["isin"]: r for r in res["rows"]}
            for code in (off, zero2):
                r, q = rows[code], quotes[code]
                assert r["priced"] and r["source"] == "eğri" and r["curve"]["label"] == q["label"] and "why" not in r, (mode, code, r)
                assert r["t0"]["yield"] == pytest.approx(q["simple"]) and r["curve"]["mark"] == marks[code], (mode, r["curve"])
                assert r["how"].startswith(marks[code] + ": ") and q["how"] in r["how"] and r["curve"]["err"] == q["err"], (mode, r["how"])
            o = rows[off]
            assert ("bugünkü ihale listesinde yok" if mode == "ihale" else "kayıtlı ihale fiyatı yok") in o["how"]
            assert o["bid"]["yield"] == pytest.approx(quotes[off]["simple"] + 0.07) and o["ask"]["yield"] == pytest.approx(quotes[off]["simple"] - 0.03)
            bond = fy.bond_of(bd.by_isin(off))
            assert o["bid"]["price"] == pytest.approx(fy.price_of(bond, (quotes[off]["simple"] + 0.07) / 100.0, REPLAY_DAY))
            z = rows[zero2]
            assert z["write"] == "yield" and z["bid"]["yield"] == pytest.approx(quotes[zero2]["simple"] + 0.05)
            # a price-quoted bond: no curve price - no price, why
            assert not rows[TLREF]["priced"] and rows[TLREF].get("source") != "eğri" and rows[TLREF]["why"], mode
            # a fixed price wins over the curve
            assert rows[fixed_one]["fixed"] and rows[fixed_one]["source"] == "sabit" and rows[fixed_one]["bid"]["price"] == 88.5
            assert res["curve"] == 2, mode
        out = call(svc, u, "kaydet", {"rows": [{"isin": r["isin"], "bid_price": r["bid"]["price"], "ask_price": r["ask"]["price"],
                                               "bid_yield": r["bid"]["yield"], "ask_yield": r["ask"]["yield"]} for r in res["rows"]]})
        assert "%s,%.3f,%.3f,0,0" % (off, o["bid"]["price"], o["ask"]["price"]) in out["lines"]
        assert "%s,0,0,%.3f,%.3f" % (zero2, z["bid"]["yield"], z["ask"]["yield"]) in out["lines"]
        # the mark says which: "(son fark)" a bond's own last spread, none the bucket's base alone (no peer priced)
        real = svc.kagitfiyat.curve_quotes
        monkeypatch.setattr(svc.kagitfiyat, "curve_quotes", lambda key, isins: {
            k: dict(v, tag={off: "son fark", zero2: None}[k]) for k, v in real(key, isins).items()})
        rows = {r["isin"]: r for r in call(svc, u, "hesapla", {"mode": "ihale", "text": "06/01/2027.t1   31.500\n"})["rows"]}
        assert rows[off]["curve"]["mark"] == "eğri fiyatı (son fark)" and rows[off]["how"].startswith("eğri fiyatı (son fark): ")
        assert rows[zero2]["curve"]["mark"] == "eğri fiyatı" and rows[zero2]["how"].startswith("eğri fiyatı: ")
    finally:
        svc.store.put(fy.KEY_AUCTIONS, dict(svc.store.get(fy.KEY_AUCTIONS) or {}, **{k: v for k, v in kept.items() if k in (off, zero2, TLREF)}))


def test_fixed_bonds_go_as_they_are_in_both_modes_over_the_computed(svc):
    fresh(svc)
    u = svc.login("Sabit Hesap")["user"]
    call(svc, u, "ekle", {"isins": "%s %s %s" % (ZERO, FIXED, TLREF)})
    call(svc, u, "sabit", {"isin": FIXED, "bid": "99,25", "ask": "99,75"})               # in the list too: fixed wins
    call(svc, u, "sabit", {"isin": BILL, "bid": "31,4", "ask": "31,3"})                  # fixed only
    call(svc, u, "sabit", {"isin": CPI, "bid": "91", "ask": "92"})
    t0 = REPLAY_DAY
    for mode in ("ihale", "bbg"):
        res = call(svc, u, "hesapla", {"mode": mode, "text": SAMPLE})
        rows = {r["isin"]: r for r in res["rows"]}
        assert [r["isin"] for r in res["rows"]] == [BILL, ZERO, FIXED, TLREF, CPI] and res["fixed"] == 3, mode
        f = rows[FIXED]
        bond = fy.bond_of(bd.by_isin(FIXED))
        assert f["fixed"] and f["source"] == "sabit" and (f["bid"]["price"], f["ask"]["price"]) == (99.25, 99.75), mode
        assert f["bid"]["yield"] == pytest.approx(fy.yield_of(bond, 99.25, t0) * 100.0) and f["note"].startswith("listede de var")
        b = rows[BILL]
        assert (b["bid"]["yield"], b["ask"]["yield"]) == (31.4, 31.3) and "note" not in b
        assert b["bid"]["price"] == pytest.approx(fy.price_of(fy.bond_of(bd.by_isin(BILL)), 0.314, t0))
        assert rows[CPI]["bid"] == {"price": 91.0, "yield": None} and "sabit fiyat" in rows[CPI]["how"].lower()
        assert not rows[ZERO].get("fixed") and rows[ZERO]["source"] in ("ihale", "ihale+eğri", None)       # (computed as before)
    # the txt: the fixed ones as they are, the others as computed
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": SAMPLE})
    rows = [{"isin": r["isin"], "bid_price": r["bid"]["price"], "ask_price": r["ask"]["price"], "bid_yield": r["bid"]["yield"],
             "ask_yield": r["ask"]["yield"]} for r in res["rows"]]
    out = call(svc, u, "kaydet", {"rows": rows})
    assert out["lines"] == ["TRB100227T13,0,0,31.400,31.300", "TRT060127T10,0,0,31.550,31.450", "TRT100227T13,99.250,99.750,0,0",
                            "TRT130127T11,100.450,100.550,0,0", "TRT020529T18,91.000,92.000,0,0"]
    # an edit of a fixed row is that file's alone: the stored figures stay
    conv = call(svc, u, "cevir", {"isin": FIXED, "field": "yield", "value": "33"})
    rows[2]["bid_price"], rows[2]["bid_yield"] = conv["price"], 33.0
    assert call(svc, u, "kaydet", {"rows": rows})["lines"][2] == "TRT100227T13,%.3f,99.750,0,0" % conv["price"]
    assert (fixed_of(svc, u)[FIXED]["bid"], fixed_of(svc, u)[FIXED]["ask"]) == (99.25, 99.75)
    # "Sabitle": a computed row's figures as they are (the zero's yields) become its fixed ones
    z = next(r for r in res["rows"] if r["isin"] == ZERO)
    call(svc, u, "sabit", {"isin": ZERO, "bid": z["bid"]["yield"], "ask": z["ask"]["yield"]})
    res = call(svc, u, "hesapla", {"mode": "bbg"})
    z2 = {r["isin"]: r for r in res["rows"]}[ZERO]
    assert z2["fixed"] and (z2["bid"]["yield"], z2["ask"]["yield"]) == (pytest.approx(31.55), pytest.approx(31.45))
    # only fixed bonds (or Eurobonds) in İhale mode: nothing needs the text
    fresh(svc)
    only = svc.login("Sabit Yalnız")["user"]
    call(svc, only, "sabit", {"isin": TLREF, "bid": "100", "ask": "101"})
    res = call(svc, only, "hesapla", {"mode": "ihale", "text": ""})
    assert [(r["isin"], r["fixed"]) for r in res["rows"]] == [(TLREF, True)] and "parse" not in res


#: the desk's sheet (20.11.2026): FX-denominated DİBS - its lower block, the one copied (ISIN | Bid | | Offer), and the upper one
#: (ISIN | Bid | Bid Yield | Offer | T1 Yield | Stok), as Excel copies them (tabs)
LOWER = "USD\nTRT191127F19\t99.483\t\t99.726\nTRT030327F17\t99.951\t\t100.152\nEUR\nTRT030227F18\t100.105\t\t100.310\n"
UPPER_CF = "TRT191127F19\t99.482\t4.74\t99.725\n"
UPPER_CH = "TRT191127F19\t99.482\t4.74\t99.725\t4.49%\t42,000\n"


def test_fixed_prices_pasted_from_excel_are_read_cell_by_cell():
    """(the desk: "Sabitlemeyi de tablo olarak atacağım excelden kopyalayıp [...] Burada bid ve offer'ı ve ISIN'i
    kopyalayacağım") The ISIN the first cell like one, the bid the first number after it, the offer the next number
    within ±10 % of the bid - the empty column, a yield (4.74, 4.49%), a stock (42,000) skipped."""
    def unit(isin):
        return "yield" if isin.startswith("TRB") else "price"
    got = fy.parse_fixed(LOWER, unit)
    assert [(r["isin"], r["bid"], r["ask"]) for r in got["rows"]] == [("TRT191127F19", 99.483, 99.726), ("TRT030327F17", 99.951, 100.152),
                                                                     ("TRT030227F18", 100.105, 100.31)]
    assert got["bad"] == [] and [x["text"] for x in got["ignored"]] == ["USD", "EUR"]
    for text in (UPPER_CF, UPPER_CH):                                                   # C:F and C:H of the upper block
        assert [(r["isin"], r["bid"], r["ask"]) for r in fy.parse_fixed(text, unit)["rows"]] == [("TRT191127F19", 99.482, 99.725)]
    # Turkish decimals; spaces instead of tabs; a cell with both marks (the last is the decimal)
    assert [(r["bid"], r["ask"]) for r in fy.parse_fixed("TRT191127F19\t99,483\t\t99,726", unit)["rows"]] == [(99.483, 99.726)]
    assert [(r["bid"], r["ask"]) for r in fy.parse_fixed("TRT191127F19    99.483    99.726", unit)["rows"]] == [(99.483, 99.726)]
    assert [fy.cell_num(x) for x in ("99.483", "99,483", "1.234,5", "42,000.5", "4.49%", "", "abc")] == [99.483, 99.483, 1234.5, 42000.5,
                                                                                                         4.49, None, None]
    # a line that cannot be read says why; a bill's offer is a lower yield
    bad = fy.parse_fixed("TRT191127F19\t99.483\nTRT191127F19\t99.726\t\t99.483\nX123\t1\t2\nTRT191127F18\t99\t99.5\n"
                         "TRB150727T13\t31.1\t31.2\nTRB150727T13\t31.2\t31.1\n", unit)
    assert [(b["n"], b["why"]) for b in bad["bad"]] == [
        (1, "offer yok: bid'in ±%10'u içinde ikinci sayı yok"), (2, "offer bid'den küçük"), (3, "ISIN yok"),
        (4, "ISIN'in kontrol hanesi tutmuyor: TRT191127F18"), (5, "offer getirisi bid'inkinden büyük")]
    assert [(r["n"], r["bid"], r["ask"]) for r in bad["rows"]] == [(6, 31.2, 31.1)]


def test_fixed_prices_pasted_need_no_catalog_and_go_to_the_file(svc):
    """Only the ISIN, bid and offer: an FX-denominated DİBS (not in the catalog, by the desk's rule) is "döviz DİBS", its
    maturity read from its ISIN (TRT191127F19: 19.11.2027), in price; a "TRB…" one a bill, in yield; a catalog bond its
    own.  Pasted again: updated."""
    fresh(svc)
    u = svc.login("Sabit Yapıştır")["user"]
    bill = _valid("TRB150727T1")
    got = call(svc, u, "sabit-yapistir", {"text": LOWER + "%s\t31,2\t\t31,1\n%s\t30.9\t30.8\nbozuk satır\t1\n" % (bill, ZERO)})
    p = got["pasted"]
    assert sorted(p["added"]) == sorted(["TRT191127F19", "TRT030327F17", "TRT030227F18", bill, ZERO]) and p["updated"] == []
    assert [b["why"] for b in p["bad"]] == ["ISIN yok"] and p["ignored"] == 2
    f = {r["isin"]: r for r in got["fixed"]}
    assert (f["TRT191127F19"]["name"], f["TRT191127F19"]["maturity"], f["TRT191127F19"]["unit"], f["TRT191127F19"]["kind_text"]) == (
        "döviz DİBS", "2027-11-19", "price", "Döviz DİBS")
    assert f["TRT030227F18"]["maturity"] == "2027-02-03" and f["TRT030327F17"]["maturity"] == "2027-03-03"
    assert (f[bill]["unit"], f[bill]["maturity"], f[ZERO]["unit"], f[ZERO]["name"]) == ("yield", "2027-07-15", "yield", "TURKGB 0 01/06/27")
    assert f["TRT191127F19"]["line"] == "TRT191127F19,99.483,99.726,0,0" and f["TRT030327F17"]["line"] == "TRT030327F17,99.951,100.152,0,0"
    assert f[bill]["line"] == "%s,0,0,31.200,31.100" % bill
    # pasted again (the upper block's C:H this time): updated, not doubled
    again = call(svc, u, "sabit-yapistir", {"text": UPPER_CH})
    assert again["pasted"]["updated"] == ["TRT191127F19"] and again["pasted"]["added"] == [] and len(again["fixed"]) == 5
    assert {r["isin"]: r for r in again["fixed"]}["TRT191127F19"]["line"] == "TRT191127F19,99.482,99.725,0,0"
    # Hesapla (no auction text: only fixed bonds) and the file
    res = call(svc, u, "hesapla", {"mode": "ihale", "text": ""})
    rows = {r["isin"]: r for r in res["rows"]}
    assert rows["TRT191127F19"]["fixed"] and "kataloğunda değil" in rows["TRT191127F19"]["how"] and rows[bill]["bid"]["price"] > 0
    out = call(svc, u, "kaydet", {"rows": [{"isin": r["isin"], "bid_price": r["bid"]["price"], "ask_price": r["ask"]["price"],
                                           "bid_yield": r["bid"]["yield"], "ask_yield": r["ask"]["yield"]} for r in res["rows"]]})
    assert "TRT191127F19,99.482,99.725,0,0" in out["lines"] and "TRT030327F17,99.951,100.152,0,0" in out["lines"]
    assert "%s,0,0,31.200,31.100" % bill in out["lines"] and "TRT060127T10,0,0,30.900,30.800" in out["lines"]
    with pytest.raises(ServiceError) as e:
        call(svc, u, "sabit-yapistir", {"text": "  "})
    assert "yapıştırın" in str(e.value)


# ================================================================================================== BBG
def trading(svc, user):
    """The bonds of DİBS RV's trading list as the page reads them (ISIN -> its row's last trade)."""
    return svc.et.call(svc.fiyatyukleme._read, user, [b["isin"] for b in bd.catalog()])["rv"]


def market(svc) -> pr.Market:
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def run():
        calc = svc.interp.boot_of(book, svc._calc(None, book))
        return pr.read(lambda s, r, c: calc.get(idx[s], r, c))
    return svc.et.call(run)


def weekdays_back(day: dt.date, n: int) -> dt.date:
    while n > 0:
        day -= dt.timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


@pytest.fixture(scope="module")
def closes(svc):
    """Made-up closes: the trading list's bonds on one day (5 week days before the replay day), each 50 bp above the yield
    the sheet has now (simple, as the history's convention reads them); every OIS tenor and TLREF on another day (40
    days before), 40 bp above the quotes now - and no bond close that early."""
    snap = svc.history.snapshot()
    d_nbr = weekdays_back(REPLAY_DAY, 5)
    d_ois = REPLAY_DAY - dt.timedelta(days=40)
    while d_ois.weekday() >= 5:
        d_ois -= dt.timedelta(days=1)
    n = 0
    for d in snap["defs"]:
        if d.group == "dibs" and d.unit == "pct":
            s = cell(svc, "DİBS RV!S%d" % d.info["row"])
            if type(s) is float:
                svc.store.hist_upsert(d.id, [(d_nbr.isoformat(), s * 100.0 + 0.5)])
                n += 1
    mk = market(svc)
    ids = {float(x.months): x.id for x in snap["defs"] if x.group == "ois" and x.months and x.months >= 1}
    for m, q in dict(mk.ois_quotes).items():
        svc.store.hist_upsert(ids[m], [(d_ois.isoformat(), q * 100.0 + 0.40)])
    ref = next(x for x in snap["defs"] if x.group == "ref")
    svc.store.hist_upsert(ref.id, [(d_ois.isoformat(), 39.5)])
    svc.history.rev += 1
    assert n >= 13
    return {"nbr": d_nbr, "ois": d_ois}


def put_auction(svc, isin: str, day: dt.date, value: float, label: str):
    """The bond's auction values: that day's .t1 alone (an earlier test's of today gone)."""
    book = svc.store.get(fy.KEY_AUCTIONS) or {}
    vd = fy.workday(day, 1, frozenset(svc.holiday_dates(("TRY",))))
    book[isin] = [{"day": day.isoformat(), "label": label, "value": value, "tn": 1, "value_date": vd.isoformat(), "by": "test", "at": "x"}]
    svc.store.put(fy.KEY_AUCTIONS, book)


def test_bbg_in_replay_the_trading_list_from_dibs_rv_the_rest_from_the_last_auction_and_the_curve(svc, closes):
    fresh(svc)
    u = svc.login("Yükleme BBG")["user"]
    rv = trading(svc, u)
    off_fixed = next(b["isin"] for b in bd.catalog() if b["kind"] == "fixed" and b["isin"] not in rv and "2027-03-01" < b["maturity"] < "2029-01-01")
    today_trade = next(code for code, r in rv.items() if fy.date_said(r["date"]) == REPLAY_DAY and bd.by_isin(code)["kind"] == "bill")
    old_trade = next(code for code, r in rv.items() if fy.date_said(r["date"]) not in (None, REPLAY_DAY) and bd.by_isin(code)["kind"] == "fixed")
    no_auction = next(b["isin"] for b in bd.catalog() if b["kind"] == "fixed" and b["isin"] not in rv and b["isin"] != off_fixed
                      and b["maturity"] > "2027-01-01")
    assert ZERO not in rv and TLREF not in rv
    put_auction(svc, ZERO, closes["nbr"], 31.5, "06/01/2027")                    # the curve's day: the Nelson-Siegel move
    put_auction(svc, off_fixed, closes["ois"], 100.0, "x")                         # before any bond close: TRY OIS's move
    put_auction(svc, TLREF, closes["nbr"], 100.25, "13/01/27 TLREF")               # price-quoted: the auction's price kept
    for code in (today_trade, old_trade):
        book = svc.store.get(fy.KEY_AUCTIONS) or {}
        book.pop(code, None)
        svc.store.put(fy.KEY_AUCTIONS, book)
    call(svc, u, "ekle", {"isins": " ".join((today_trade, old_trade, ZERO, off_fixed, TLREF, no_auction))})
    called = []
    svc.provider.reference = lambda *a, **k: called.append(a) or {}                # (replay: never asked)
    try:
        res = call(svc, u, "hesapla", {"mode": "bbg"})
    finally:
        del svc.provider.reference
    assert called == [] and res["bbg"]["asked"] == 0 and "Bloomberg yok" in res["bbg"]["why"] and res["mode"] == "bbg"
    rows = {r["isin"]: r for r in res["rows"]}
    # the trading list: DİBS RV's last trade (today's), a bill's price read as its simple yield at its value date
    r = rows[today_trade]
    last = rv[today_trade]["last"]
    mat = dt.date.fromisoformat(bd.by_isin(today_trade)["maturity"])
    days = (mat - REPLAY_DAY).days if str(rv[today_trade]["source"]).upper() == "ISL0" else (mat - dt.date(2026, 11, 4)).days
    assert r["source"] == "bbg" and r["t0"]["yield"] == pytest.approx((100.0 / last - 1.0) * 365.0 / days * 100.0)
    assert "DİBS RV son işlem 03.11.2026" in r["how"] and "fiyat" in r["how"] and "note" not in r
    # a trade that is not today's and no auction kept: that trade, moved with the curve since its day (the desk, 20.11.2026:
    # "dün işlem olmasına rağmen son işlem dün diyor ve göstermiyor")
    ot = rows[old_trade]
    tday = fy.date_said(rv[old_trade]["date"])
    assert ot["priced"] and ot["source"] == "bbg+eğri" and ("DİBS RV son işlem %s" % fy.tr_day(tday)) in ot["how"], ot
    # neither a trade (nothing asked in replay) nor an auction: its curve price (Kâğıt Fiyatlama's), why said in its how
    na = rows[no_auction]
    assert na["priced"] and na["source"] == "eğri" and "kayıtlı ihale fiyatı yok" in na["how"] and na["how"].startswith("eğri fiyatı: ")
    assert "tipik hata" in na["how"]                                    # (a fixed coupon bond, no closes: the curve alone)
    assert "Bloomberg yok" in na["note"] and res["curve"] >= 1
    # off the list, no Bloomberg: the last auction + the bond curve's move since that day's close (the coupon bonds' closes 50 bp
    # higher then: the curve's short end, where no coupon bond is, moves less - test_the_curves_move_measured_directly)
    z = rows[ZERO]
    assert z["source"] == "ihale+eğri" and -50.0 < z["move_bp"] < -25.0, z
    assert z["t0"]["yield"] == pytest.approx(31.5 + z["move_bp"] / 100.0) and "Nelson-Siegel" in z["how"]
    assert "Bloomberg yok" in z["note"]
    # without the curve that day (no bond close then): TRY OIS's zero rate change (quotes 40 bp higher then), said
    o = rows[off_fixed]
    assert o["source"] == "ihale+eğri" and -48.0 < o["move_bp"] < -20.0 and "TRY OIS" in o["how"] and "TRY OIS değişimi kullanıldı" in o["note"]
    bond = fy.bond_of(bd.by_isin(off_fixed))
    y_a = fy.yield_of(bond, 100.0, fy.workday(closes["ois"], 1, frozenset(svc.holiday_dates(("TRY",)))))
    assert o["t0"]["yield"] == pytest.approx((y_a * 100.0) + o["move_bp"] / 100.0)
    # price-quoted: the last auction's price as it is
    t = rows[TLREF]
    assert t["t0"] == {"yield": None, "price": 100.25} and t["bid"]["price"] == pytest.approx(100.20) and "son ihale fiyatı" in t["note"]


def test_bloombergs_last_trades_are_kept_per_isin_for_the_curve_price(svc, closes, monkeypatch):
    """BBG mode: each Bloomberg answer of a bond's last trade (LAST_PRICE, LAST_TRADE_DATE) kept per ISIN in the store,
    beyond the 5 minutes the answer itself is kept - a later trade replaces it, an earlier one does not -; Kâğıt
    Fiyatlama's last known spread takes it: the bond missing from an auction text is priced at its bucket's base now +
    its spread at that trade, on that day's close curve ("eğri fiyatı (son fark, son işlem <day>)")."""
    from tto import kagitfiyat as kf
    fresh(svc)
    u = svc.login("Yükleme Son İşlem")["user"]
    rv = trading(svc, u)
    code = "TRT110827T16"
    assert code not in rv and bd.by_isin(code)["kind"] == "fixed"
    tday = closes["nbr"]
    said = {"day": tday}
    fyk = svc.fiyatyukleme
    monkeypatch.setattr(fyk, "ask_bloomberg", lambda secs, fields=fy.BBG_FIELDS: (
        {s: {"LAST_PRICE": 96.5, "LAST_TRADE_DATE": said["day"].strftime("%d.%m.%Y")} for s in secs}, len(secs), None))
    saved = svc.store.get(fy.KEY_TRADES)
    try:
        call(svc, u, "ekle", {"isins": code})
        res = call(svc, u, "hesapla", {"mode": "bbg"})
        row = next(r for r in res["rows"] if r["isin"] == code)
        assert row["source"] == "bbg+eğri"                                     # (BBG mode: that trade moved with the curve, as before)
        kept = svc.store.get(fy.KEY_TRADES)[code]
        assert (kept["day"], kept["price"], kept["source"]) == (tday.isoformat(), 96.5, "ISL1")
        said["day"] = tday - dt.timedelta(days=7)                               # (an earlier trade does not replace it)
        call(svc, u, "hesapla", {"mode": "bbg"})
        assert svc.store.get(fy.KEY_TRADES)[code]["day"] == tday.isoformat()
        # missing from an auction text: Kâğıt Fiyatlama's price from that trade - its base now + its spread that day
        res = call(svc, u, "hesapla", {"mode": "ihale", "text": "06/01/2027.t1   31.500\n"})
        c = next(r for r in res["rows"] if r["isin"] == code)
        dd = tday.strftime("%d.%m")
        assert c["curve"]["mark"] == "eğri fiyatı (son fark, son işlem %s)" % dd and c["curve"]["label"].startswith("eğri + son fark (son işlem %s, " % dd)
        assert "Bloomberg 96,500" in c["how"] and "o günün kapanış eğrisine göre" in c["how"]
        q = svc.kagitfiyat.curve_quotes(u, [code])[code]
        assert q["src"] == "trade" and q["day"] == tday.isoformat() and q["yield"] == c["curve"]["yield"]
        assert q["age"] == kf.business_days(tday, REPLAY_DAY, svc._swaption_closes(market(svc))[2])
    finally:
        svc.store.put(fy.KEY_TRADES, saved if saved is not None else {})


def test_bbg_the_newer_of_the_last_trade_and_the_last_auction_is_the_reference(svc, closes):
    """(the desk, 20.11.2026: "dün işlem olmasına rağmen son işlem dün diyor ve göstermiyor") A last trade not of today:
    a trade newer than every auction kept is the reference, moved with the curve since its day; an auction kept on the
    trade's day or later stays the reference ("son trade bugün değilse, son ihale fiyatından itibaren")."""
    fresh(svc)
    u = svc.login("Yükleme Yenisi")["user"]
    rv = trading(svc, u)
    code = next(c for c, r in rv.items() if fy.date_said(r["date"]) not in (None, REPLAY_DAY) and bd.by_isin(c)["kind"] == "fixed")
    tday = fy.date_said(rv[code]["date"])
    call(svc, u, "ekle", {"isins": code})

    def row():
        return {x["isin"]: x for x in call(svc, u, "hesapla", {"mode": "bbg"})["rows"]}[code]

    try:
        put_auction(svc, code, tday - dt.timedelta(days=7), 99.0, "x")              # an older auction: the trade wins
        r = row()
        assert r["source"] == "bbg+eğri" and ("son işlem %s" % fy.tr_day(tday)) in r["how"] and "son ihale" not in r["how"], r
        put_auction(svc, code, tday, 99.0, "x")                                       # an auction on the trade's day: the auction
        r = row()
        assert r["source"] == "ihale+eğri" and ("son ihale %s" % fy.tr_day(tday)) in r["how"], r
    finally:
        book = svc.store.get(fy.KEY_AUCTIONS) or {}
        book.pop(code, None)
        svc.store.put(fy.KEY_AUCTIONS, book)


# ------------------------------------------------------------------ Mid or Bid/Ask (the desk, 23.11.2026)
def test_mid_or_bid_ask_is_kept_with_the_desks_list_by_isin_across_a_list_change(svc):
    """(the desk, 23.11.2026: "Kağıt fiyat yükleme listesinde bloomberg'te kağıt kağıt bid'i ve ask'i mid'den mi, bid/asktan mı
    almasını istediğimi de seçebilmeliyim. Default mid") Each bond's choice is kept with the list by its ISIN - the
    desk's list (25.11.2026: everyone sees it): Mid until set; bonds coming in before it (its row moves) or going leave it
    as it is; "Tümü" sets every bond; Mid again leaves the list's entry as it was before any choice."""
    fresh(svc)
    u = svc.login("Yükleme Taraf")["user"]
    other = svc.login("Yükleme Taraf Başka")["user"]
    bond = "TRT150328T24"
    st = call(svc, u, "ekle", {"isins": "%s %s" % (FIXED, bond)})
    before = [dict(b) for b in svc.store.get(fy.KEY_DESK)["bonds"]]
    assert [(r["isin"], r["base"]) for r in st["list"]] == [(FIXED, "mid"), (bond, "mid")]
    assert st["bases"] == [{"id": "mid", "text": "Mid"}, {"id": "bidask", "text": "Bid/Ask"}]
    st = call(svc, u, "ayar", {"bases": {bond.lower(): "bidask"}})
    assert [(r["isin"], r["base"]) for r in st["list"]] == [(FIXED, "mid"), (bond, "bidask")]
    assert [(r["isin"], r["base"]) for r in call(svc, other, "state")["list"]] == [(FIXED, "mid"), (bond, "bidask")]      # (the desk's)
    # the list changes: bonds sorting before it come in (its row moves down), one goes - the choice stays with its ISIN
    st = call(svc, u, "ekle", {"isins": "%s %s" % (ZERO, BILL)})
    assert [(r["isin"], r["base"]) for r in st["list"]] == [(BILL, "mid"), (ZERO, "mid"), (FIXED, "mid"), (bond, "bidask")]
    st = call(svc, u, "cikar", {"isin": FIXED})
    assert [(r["isin"], r["base"]) for r in st["list"]] == [(BILL, "mid"), (ZERO, "mid"), (bond, "bidask")]
    assert [(r["isin"], r["base"]) for r in fy.FiyatYukleme(svc).state(u)["list"]][-1] == (bond, "bidask")     # (the store's)
    # "Tümü": every bond at once, either way; Mid again: the entry as before any choice
    assert {r["base"] for r in call(svc, u, "ayar", {"base_all": "bidask"})["list"]} == {"bidask"}
    assert {r["base"] for r in call(svc, u, "ayar", {"base_all": "mid"})["list"]} == {"mid"}
    kept = svc.store.get(fy.KEY_DESK)["bonds"]
    assert all("base" not in b for b in kept) and [b for b in kept if b["isin"] == bond] == [b for b in before if b["isin"] == bond]
    for body, said in (({"bases": {bond: "bid"}}, "Mid ya da Bid/Ask olmalı: bid"), ({"base_all": ""}, "Mid ya da Bid/Ask olmalı: (boş)"),
                       ({"bases": {FIXED: "bidask"}}, "kâğıt listede değil: %s" % FIXED)):
        with pytest.raises(ServiceError) as e:
            call(svc, u, "ayar", body)
        assert str(e.value) == said


def test_bid_ask_on_the_trading_list_from_dibs_rvs_own_bid_and_ask(svc):
    """Bid/Ask, a bond of DİBS RV's trading list: its sides from the sheet's bid / ask (K / L - nothing asked of Bloomberg),
    each read as the last trade is (a coupon bond's price at its value date -> its simple yield, the same at t0; a TLREF's
    price as it is), the spreads each on its own side - at 0 the screen's own; a bill whose bid equals its ask (no order
    stands: the last trade on both sides) from the mid as Mid prices it, said on the row; the summary counts them."""
    fresh(svc)
    u = svc.login("Yükleme Bid Ask")["user"]
    rv = trading(svc, u)

    def quoted(r):
        return all(isinstance(r[s], float) and r[s] > 0 for s in ("bid", "ask"))

    two = next(c for c, r in rv.items() if bd.by_isin(c)["kind"] == "fixed" and quoted(r) and r["bid"] < r["ask"])
    tl = next(c for c, r in rv.items() if bd.by_isin(c)["kind"] in ("float", "frn") and quoted(r) and r["bid"] < r["ask"])
    same = next(c for c, r in rv.items() if bd.by_isin(c)["kind"] == "bill" and quoted(r) and r["bid"] == r["ask"])
    call(svc, u, "ekle", {"isins": " ".join((two, tl, same))})
    called = []
    svc.provider.reference = lambda *a, **k: called.append(a) or {}                # (DİBS RV's own figures: never asked)
    try:
        mid = {r["isin"]: r for r in call(svc, u, "hesapla", {"mode": "bbg"})["rows"]}
        call(svc, u, "ayar", {"base_all": "bidask"})
        res = call(svc, u, "hesapla", {"mode": "bbg"})
        call(svc, u, "ayar", {"spreads": {two: {"bid": "0", "ask": "0"}, tl: {"bid": "0", "ask": "0"}}})
        at0 = {r["isin"]: r for r in call(svc, u, "hesapla", {"mode": "bbg"})["rows"]}
    finally:
        del svc.provider.reference
    assert called == [] and res["bbg"]["hits"] == 0
    assert res["bbg"]["bidask"] == {"n": 3, "from_sides": 2, "asked": 0, "cached": 0, "why": None}
    rows = {r["isin"]: r for r in res["rows"]}
    # a coupon bond (ISL1: value T+1): each side's price -> its simple yield at that value date, the same at t0, ± 5 bp
    vd = fy.workday(REPLAY_DAY, 1, frozenset(svc.holiday_dates(("TRY",))))
    bond = fy.bond_of(bd.by_isin(two))
    yb, ya = fy.yield_of(bond, rv[two]["bid"], vd), fy.yield_of(bond, rv[two]["ask"], vd)
    r = rows[two]
    assert (r["source"], r["base"], r["priced"]) == ("bbg-bidask", "bidask", True) and "note" not in r
    assert r["bid"]["yield"] == pytest.approx(yb * 100.0 + 0.05, abs=1e-12) and r["ask"]["yield"] == pytest.approx(ya * 100.0 - 0.05, abs=1e-12)
    assert r["bid"]["price"] == pytest.approx(fy.price_of(bond, yb + 5e-4, REPLAY_DAY), abs=1e-12)
    assert r["ask"]["price"] == pytest.approx(fy.price_of(bond, ya - 5e-4, REPLAY_DAY), abs=1e-12)
    assert r["t0"]["yield"] == pytest.approx((yb + ya) * 50.0, abs=1e-12) and r["bid"]["price"] < rv[two]["bid"] < rv[two]["ask"] < r["ask"]["price"]
    assert r["how"].startswith("Bid/Ask: DİBS RV bid %s / ask %s (valör %s) → basit getiri" % (fy._n(rv[two]["bid"]), fy._n(rv[two]["ask"]), fy.tr_day(vd)))
    # at 0: the screen's own - the coupon bond's yields at its value date, the floater's prices to the digit
    assert at0[two]["bid"]["yield"] == pytest.approx(yb * 100.0, abs=1e-12) and at0[two]["ask"]["yield"] == pytest.approx(ya * 100.0, abs=1e-12)
    t = rows[tl]
    assert t["source"] == "bbg-bidask" and t["bid"]["price"] == pytest.approx(rv[tl]["bid"] - 0.05) and t["ask"]["price"] == pytest.approx(rv[tl]["ask"] + 0.05)
    assert (at0[tl]["bid"]["price"], at0[tl]["ask"]["price"]) == (rv[tl]["bid"], rv[tl]["ask"])
    assert at0[tl]["t0"] == {"yield": None, "price": pytest.approx((rv[tl]["bid"] + rv[tl]["ask"]) / 2.0)} and at0[tl]["how"].endswith("spread'ler kendi tarafına")
    # bid = ask: no order stands - the row from the mid, as Mid prices it, and it says so
    s = rows[same]
    assert s["note"] == "Bid/Ask seçili; bid = ask (%s): canlı emir yok, Bloomberg iki tarafa da son fiyatı veriyor: mid'den" % fy._n(rv[same]["bid"])
    assert s["base"] == "bidask" and {k: v for k, v in s.items() if k not in ("base", "note")} == mid[same] and "note" not in mid[same]


def test_the_curves_move_measured_directly(svc, closes):
    """The move on its own: the Nelson-Siegel fit of the trading list's yields now (DİBS RV · Genel's) minus the same fit -
    its τ held - of the auction day's closes, each bond's cash flows from t0 on both curves.  The closes were made 50 bp
    above the yields now: a coupon bond in the fit moves ~50 bp; a bill or zero, on the short end no coupon bond reaches,
    less (the curve there is the fit's, not the bills')."""
    u = svc.login("Yükleme Eğri")["user"]
    fyk = svc.fiyatyukleme
    got = svc.et.call(fyk._read, u, [])
    today, t0 = REPLAY_DAY, REPLAY_DAY
    ctx = {"got": got, "today": today, "t0": t0, "hol": frozenset(svc.holiday_dates(("TRY",)))}
    now = svc.dibsgenel.fit(got["quant"], got["live"], today)
    items = []
    for r in got["quant"]:
        b = qc._bond_of(r["isin"], {}, r)
        if b is not None and r.get("simple") is not None:
            items.append((b, qc._value_date(closes["nbr"], r), r["simple"] + 0.005, "simple"))
    fit_in = qc.BondFit(items)
    assert fit_in.n_fit >= 13
    then = qc.refit(fit_in.make, now["tau"], now["tau"].beta, iters=8)["nss"]
    for isin in ("TRT150328T24", "TRB100227T13", ZERO):
        bond = fy.bond_of(bd.by_isin(isin))
        want = fy.model_yield(bond, now["nss"], t0) - fy.model_yield(bond, then, t0)
        d, text, warn = fyk.move(bond, closes["nbr"], 0.30, ctx)
        assert d == pytest.approx(want, abs=1e-9) and warn is None and "Nelson-Siegel, 27.10.2026 kapanışından şimdiye" in text, (isin, d)
        assert (-56.0 < d * 1e4 < -44.0) if bond.kind == "fixed" else (-50.0 < d * 1e4 < -25.0), (isin, d)
    assert fyk.move(fy.bond_of(bd.by_isin(ZERO)), today, 0.30, ctx)[:2] == (0.0, "(ihale bugün: eğri hareketi yok)")


# ------------------------------------------------------------------ BBG on a connected Bloomberg (a provider that answers at once)
class _Live(ReplayProvider):
    """A connected Bloomberg: the recorded file's values, and one-off requests answered from ``answers`` (logged)."""
    live = True

    def __init__(self, snapshot, answers):
        super().__init__(snapshot)
        self.answers = answers
        self.calls = []

    def _get(self, key):
        v = self.snapshot.get(key)
        return "#N/A N/A" if v is None else v

    get_bdp = get_bdh = get_bds = _get

    def reference(self, securities, fields, timeout=30.0):
        self.calls.append((list(securities), list(fields)))
        return {s: {f: (self.answers.get(s) or {}).get(f, "#N/A N/A") for f in fields} for s in securities}


@pytest.fixture(scope="module")
def live(tmp_path_factory, module_service):
    from tto.config import Settings
    from tto.service import Service
    from tto.xl.engine import Clock
    today = module_service.books["tto"].engine.clock.today()
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    answers = {"TRT060127T10 @ISL0 ISIN": {"LAST_PRICE": 94.75, "LAST_TRADE_DATE": "3.11.2026 14:05:00"},
               "TRT130127T11 @ISL1 ISIN": {"LAST_PRICE": 100.4, "LAST_TRADE_DATE": "2.11.2026"}}
    answers.update({isin + " ISIN": facts for isin, facts in EURO_FACTS.items()})          # (Eurobonds: by DİBS RV's N2 style)
    snapshot = dict(module_service.provider.snapshot)
    # (DİBS RV's own LAST_PRICE / LAST_TRADE_DATE of two of its bonds, as the terminal streams them: replay pins those cells)
    from tto.marketdata.base import bdp_key
    for sec, last in (("TRB100227T13 @ISL0 ISIN", 92.147), ("TRT150328T24 @ISL1 ISIN", 100.2)):
        snapshot[bdp_key(sec, "LAST_PRICE")] = last
        snapshot[bdp_key(sec, "LAST_TRADE_DATE")] = "3.11.2026"
    provider = _Live(snapshot, answers)
    s = Service(Settings(data_dir=str(tmp_path_factory.mktemp("live")), mode="live", history=False), provider=provider, clock=clock)
    yield s, provider
    s.stop()


def test_bbg_asks_bloomberg_only_for_bonds_off_the_trading_list_once_in_five_minutes(live):
    s, provider = live
    fresh(s)
    assert s.mode == "live"
    u = s.login("Yükleme Canlı")["user"]
    rv = trading(s, u)
    on_list = [c for c in ("TRB100227T13", "TRT150328T24") if c in rv]
    assert len(on_list) == 2
    call(s, u, "ekle", {"isins": " ".join(on_list)})
    res = call(s, u, "hesapla", {"mode": "bbg"})
    assert provider.calls == [] and res["bbg"]["asked"] == 0 and res["bbg"]["why"] is None     # the trading list: DİBS RV, no request
    assert all(r["source"] == "bbg" for r in res["rows"])
    # two bonds off the list: one request, 2 fields each (4 hits), by Tüm Kâğıtlar's names of them
    call(s, u, "ekle", {"isins": "%s %s" % (ZERO, TLREF)})
    res = call(s, u, "hesapla", {"mode": "bbg"})
    assert provider.calls == [(["TRT060127T10 @ISL0 ISIN", "TRT130127T11 @ISL1 ISIN"], ["LAST_PRICE", "LAST_TRADE_DATE"])]
    assert (res["bbg"]["asked"], res["bbg"]["hits"], res["bbg"]["cached"]) == (2, 4, 0)
    rows = {r["isin"]: r for r in res["rows"]}
    # today's trade (a time after the date): the zero's price at its value date (ISL0: today) -> its simple yield
    z = rows[ZERO]
    assert z["source"] == "bbg" and z["t0"]["yield"] == pytest.approx((100.0 / 94.75 - 1.0) * 365.0 / 64 * 100.0)
    assert z["t0"]["price"] == pytest.approx(94.75) and "Bloomberg son işlem 03.11.2026 94,750" in z["how"]
    # yesterday's trade of a price-quoted bond and no auction kept here: that trade's price (the desk, 20.11.2026)
    t = rows[TLREF]
    assert t["priced"] and t["source"] == "bbg" and t["t0"] == {"yield": None, "price": 100.4}, t
    assert "Bloomberg son işlem 02.11.2026 100,400" in t["how"] and t["note"] == "fiyatla kote edilir: son işlem fiyatı"
    # within 5 minutes: not asked again
    res = call(s, u, "hesapla", {"mode": "bbg"})
    assert len(provider.calls) == 1 and (res["bbg"]["asked"], res["bbg"]["cached"]) == (0, 2)
    # 5 minutes on: asked again
    fyk = s.fiyatyukleme
    fyk._asked = {k: (t - fy.CACHE_SECONDS - 1, v) for k, (t, v) in fyk._asked.items()}
    res = call(s, u, "hesapla", {"mode": "bbg"})
    assert len(provider.calls) == 2 and res["bbg"]["asked"] == 2
    # no answer (the limit, a time-out): said, and the rows fall back
    provider.reference = lambda *a, **k: None
    fyk._asked = {}
    try:
        res = call(s, u, "hesapla", {"mode": "bbg"})
    finally:
        del provider.reference
    assert "yanıt vermedi" in res["bbg"]["why"] and "yanıt vermedi" in {r["isin"]: r for r in res["rows"]}[ZERO]["note"]


def test_a_bond_off_the_catalog_comes_in_by_the_desks_route_with_bloomberg(live, monkeypatch):
    s, _ = live
    fresh(s)
    u = s.login("Yükleme Yeni")["user"]
    asked = []

    def add(user, values):
        asked.append(values)
        return {"added": [], "skipped": [], "waiting": [], "refused": [{"isin": values[0], "why": "unknown", "text": "Bloomberg bu ISIN'i tanımıyor"}]}
    monkeypatch.setattr(s, "bond_list_add", add)
    new = next(c for c in ("TRT010136T1%d" % d for d in range(10)) if bd.isin_valid(c))
    got = call(s, u, "ekle", {"isins": new + " " + FIXED})
    assert asked == [[new]] and got["added"] == [FIXED] and got["refused"] == [{"isin": new, "text": "Bloomberg bu ISIN'i tanımıyor"}]


def test_a_eurobond_comes_in_with_its_facts_asked_once_never_into_the_dibs_catalog(live):
    s, provider = live
    fresh(s)
    u = s.login("Yükleme Eurobond")["user"]
    other = s.login("Yükleme Eurobond İki")["user"]
    n0 = len(provider.calls)
    got = call(s, u, "ekle", {"isins": "%s\n%s, %s" % (EURO1, EURO2, EURO3)})
    assert got["added"] == [EURO1, EURO2, EURO3] and got["refused"] == []
    assert provider.calls[n0:] == [(sorted(x + " ISIN" for x in (EURO1, EURO2, EURO3)), list(fy.EURO_FACTS))]       # once, all of them
    rows = {r["isin"]: r for r in got["list"]}
    assert (rows[EURO1]["kind_text"], rows[EURO1]["ccy"], rows[EURO1]["name"], rows[EURO1]["maturity"], rows[EURO1]["label"]) == (
        "Eurobond", "USD", "TURKEY 7 5/8 05/15/34", "2034-05-15", "15.05.34 USD")
    assert rows[EURO2]["ccy"] == "EUR" and rows[EURO1]["spread"]["unit"] == "bp" and rows[EURO1]["write"] == "price"
    assert [r["isin"] for r in got["list"]][-3:] == [EURO2, EURO1, EURO3]                # (Eurobonds last, by maturity)
    # its facts kept desk-wide: taken off the list and added again (by another user) without asking again; never in the
    # DİBS catalog
    call(s, u, "cikar", {"isin": EURO1})
    assert call(s, other, "ekle", {"isins": EURO1})["added"] == [EURO1] and len(provider.calls) == n0 + 1
    assert bd.by_isin(EURO1) is None and EURO1 in s.store.get(fy.KEY_EURO)
    # one Bloomberg does not know: why
    bad = _valid("XS111111111")
    got = call(s, u, "ekle", {"isins": bad})
    assert got["added"] == [] and got["refused"] == [{"isin": bad, "text": "Bloomberg kâğıdın bilgilerini vermedi"}]


def test_a_eurobond_is_priced_from_bloombergs_mid_whatever_the_switch(live):
    s, provider = live
    fresh(s)
    u = s.login("Yükleme Eurobond Fiyat")["user"]
    call(s, u, "ekle", {"isins": "%s %s %s %s" % (EURO1, EURO2, EURO3, FIXED)})
    fyk = s.fiyatyukleme
    fyk._asked = {}
    n0 = len(provider.calls)
    res = call(s, u, "hesapla", {"mode": "ihale", "text": SAMPLE})
    names = sorted(x + " ISIN" for x in (EURO1, EURO2, EURO3))
    # the mid of all three (2 hits each), the sides of the one whose PX_MID is empty (2 more)
    assert provider.calls[n0:] == [(names, ["PX_MID", "YLD_YTM_MID"]), ([EURO2 + " ISIN"], ["PX_BID", "PX_ASK"])]
    assert res["euro"] == {"asked": 3, "hits": 8, "cached": 0, "sides": 1, "why": None}
    rows = {r["isin"]: r for r in res["rows"]}
    assert rows[FIXED]["source"] == "ihale"                                              # (a DİBS: the auction's)
    e1 = rows[EURO1]
    rec = fyk.record(EURO1)
    bond = fy.street_of(rec)
    settle = dt.date(2026, 11, 4)                                                       # T+1 on the USD calendar
    anchor = E1_MID - bond.clean(0.0685, settle)
    assert e1["source"] == "bbg-mid" and e1["settle"] == "2026-11-04" and e1["anchor"] == pytest.approx(anchor, abs=1e-12)
    assert 0.0115 <= e1["anchor"] <= 0.0125 and "note" not in e1                       # (within 0,05: not flagged)
    assert e1["t0"] == {"yield": pytest.approx(6.85), "price": E1_MID}
    assert e1["bid"]["yield"] == pytest.approx(6.87) and e1["ask"]["yield"] == pytest.approx(6.83)
    assert e1["bid"]["price"] == pytest.approx(bond.clean(0.0687, settle) + anchor, abs=1e-12)
    assert e1["ask"]["price"] == pytest.approx(bond.clean(0.0683, settle) + anchor, abs=1e-12)
    assert "T+1 USD takvimiyle (Bloomberg DAYS_TO_SETTLE)" in e1["how"] and "Bloomberg mid PX_MID" in e1["how"] and "çapa farkı +0,01" in e1["how"]
    # PX_MID empty: the middle of PX_BID / PX_ASK, said; EUR, T+2 on TARGET2
    e2 = rows[EURO2]
    assert e2["t0"]["price"] == pytest.approx(100.0) and "(PX_BID + PX_ASK)/2 (PX_MID boş)" in e2["how"] and e2["settle"] == "2026-11-05"
    # Bloomberg's yield and price far from the street convention's: the anchor shown and flagged; the defaults said
    e3 = rows[EURO3]
    assert abs(e3["anchor"]) > 5 and "> 0,05" in e3["note"] and "varsayılan: Bloomberg DAYS_TO_SETTLE vermedi" in e3["how"]
    assert e3["bid"]["price"] < 90.0 < e3["ask"]["price"]
    # BBG mode: the same prices, from the answers of the last 5 minutes (no new request)
    n1 = len(provider.calls)
    res2 = call(s, u, "hesapla", {"mode": "bbg"})
    rows2 = {r["isin"]: r for r in res2["rows"]}
    assert res2["euro"]["asked"] == 0 and res2["euro"]["cached"] == 3 and all("PX_MID" not in c[1] for c in provider.calls[n1:])
    assert rows2[EURO1]["bid"] == e1["bid"] and rows2[EURO1]["ask"] == e1["ask"] and rows2[EURO2]["t0"] == e2["t0"]
    # a bond's own yield spread (bp; skew allowed)
    call(s, u, "ayar", {"spreads": {EURO1: {"bid": "1", "ask": "-0,5"}}})
    e1b = {r["isin"]: r for r in call(s, u, "hesapla", {"mode": "bbg"})["rows"]}[EURO1]
    assert e1b["bid"]["yield"] == pytest.approx(6.86) and e1b["ask"]["yield"] == pytest.approx(6.855)
    # an edited cell: the same anchored convention at the same settlement
    got = call(s, u, "cevir", {"isin": EURO1, "field": "yield", "value": "6,9", "settle": e1["settle"], "anchor": e1["anchor"]})
    assert got["price"] == pytest.approx(bond.clean(0.069, settle) + anchor, abs=1e-12) and got["value_date"] == "2026-11-04"
    back = call(s, u, "cevir", {"isin": EURO1, "field": "price", "value": got["price"], "settle": e1["settle"], "anchor": e1["anchor"]})
    assert back["yield"] == pytest.approx(6.9, abs=1e-9)
    with pytest.raises(ServiceError) as err:
        call(s, u, "cevir", {"isin": EURO1, "field": "yield", "value": 6.9})
    assert "önce Hesapla" in str(err.value)
    # the txt: clean prices, yields 0
    out = call(s, u, "kaydet", {"rows": [{"isin": EURO1, "bid_price": e1["bid"]["price"], "ask_price": e1["ask"]["price"],
                                          "bid_yield": e1["bid"]["yield"], "ask_yield": e1["ask"]["yield"]}]})
    assert out["lines"] == ["%s,%.3f,%.3f,0,0" % (EURO1, e1["bid"]["price"], e1["ask"]["price"])]


def test_a_fixed_bond_costs_no_bloomberg_request(live):
    """A fixed bond off the trading list (a zero, a Eurobond): no LAST_PRICE / PX_MID asked in BBG mode - it is not computed."""
    s, provider = live
    fresh(s)
    u = s.login("Sabit Canlı")["user"]
    call(s, u, "ekle", {"isins": EURO1})                                                # (its facts: once, kept)
    call(s, u, "sabit", {"isin": ZERO, "bid": "31,6", "ask": "31,4"})
    call(s, u, "sabit", {"isin": EURO1, "bid": "104,1", "ask": "104,4"})              # in the list too: fixed wins
    s.fiyatyukleme._asked = {}
    n0 = len(provider.calls)
    res = call(s, u, "hesapla", {"mode": "bbg"})
    assert provider.calls[n0:] == [] and res["bbg"]["asked"] == 0 and "euro" not in res
    rows = {r["isin"]: r for r in res["rows"]}
    assert rows[ZERO]["fixed"] and (rows[ZERO]["bid"]["yield"], rows[ZERO]["ask"]["yield"]) == (31.6, 31.4)
    e = rows[EURO1]
    assert e["fixed"] and (e["bid"]["price"], e["ask"]["price"]) == (104.1, 104.4) and e["anchor"] == 0.0 and e["settle"] == "2026-11-04"
    bond = fy.street_of(s.fiyatyukleme.record(EURO1))
    assert e["bid"]["yield"] == pytest.approx(bond.yield_of(104.1, dt.date(2026, 11, 4)) * 100.0) and "çapasız" in e["how"]
    assert call(s, u, "kaydet", {"rows": [{"isin": EURO1, "bid_price": 104.1, "ask_price": 104.4}]})["lines"] == ["%s,104.100,104.400,0,0" % EURO1]


def test_mid_is_the_default_and_prices_and_asks_as_before(live):
    """Mid, every bond's default: nothing new asked (the others' last trade, a Eurobond's mid and an empty mid's sides, as
    before; the trading list's bonds from DİBS RV), no new field on a row or in the summary; a list switched to Bid/Ask and
    back to Mid ("Tümü") is stored as it was and prices to the digit as it did."""
    s, provider = live
    fresh(s)
    u = s.login("Yükleme Mid")["user"]
    fyk = s.fiyatyukleme
    call(s, u, "ekle", {"isins": "%s %s %s %s %s" % (ZERO, TLREF, "TRT150328T24", EURO1, EURO2)})
    entries = [dict(b) for b in s.store.get(fy.KEY_DESK)["bonds"]]

    def run():
        fyk._asked = {}
        n = len(provider.calls)
        res = call(s, u, "hesapla", {"mode": "bbg"})
        res.pop("time")
        return res, provider.calls[n:]

    res, calls = run()
    assert calls == [(["TRT060127T10 @ISL0 ISIN", "TRT130127T11 @ISL1 ISIN"], ["LAST_PRICE", "LAST_TRADE_DATE"]),
                     (sorted(x + " ISIN" for x in (EURO1, EURO2)), ["PX_MID", "YLD_YTM_MID"]), ([EURO2 + " ISIN"], ["PX_BID", "PX_ASK"])]
    assert (res["bbg"]["hits"], res["euro"]["hits"]) == (4, 6) and "bidask" not in res["bbg"] and "bidask" not in res["euro"]
    assert len(res["rows"]) == 5 and not any("base" in r for r in res["rows"])
    call(s, u, "ayar", {"base_all": "bidask"})
    call(s, u, "ayar", {"base_all": "mid"})
    assert s.store.get(fy.KEY_DESK)["bonds"] == entries
    again, calls2 = run()
    assert calls2 == calls and again == res


def test_bid_ask_off_the_trading_list_asks_px_bid_and_px_ask_only_for_those(live):
    """Bid/Ask on a connected Bloomberg: an off-list DİBS's sides from PX_BID / PX_ASK, asked on Hesapla only for the bonds
    set so, in one request of their own (2 hits a bond, in the summary's hits; kept 5 minutes like the others), each side
    read as the last trade is, the spreads each on its own side - at 0 the screen's prices; a bond whose bid equals its ask
    (no order stands) and a DİBS RV bond whose order sizes say no order stands ("–") from the mid as Mid prices them, said."""
    s, provider = live
    fresh(s)
    u = s.login("Yükleme Bid Ask Canlı")["user"]
    zsec, tsec, on_list = "TRT060127T10 @ISL0 ISIN", "TRT130127T11 @ISL1 ISIN", "TRT150328T24"
    saved = {k: provider.answers[k] for k in (zsec, tsec)}
    provider.answers[zsec] = dict(saved[zsec], PX_BID=94.70, PX_ASK=94.80)
    provider.answers[tsec] = dict(saved[tsec], PX_BID=100.35, PX_ASK=100.35)          # (bid = ask: the last trade on both sides)
    fyk = s.fiyatyukleme
    try:
        call(s, u, "ekle", {"isins": "%s %s %s" % (ZERO, TLREF, on_list)})
        fyk._asked = {}
        n0 = len(provider.calls)
        mid = {r["isin"]: r for r in call(s, u, "hesapla", {"mode": "bbg"})["rows"]}
        assert provider.calls[n0:] == [([zsec, tsec], ["LAST_PRICE", "LAST_TRADE_DATE"])]                      # (Mid: as before)
        call(s, u, "ayar", {"base_all": "bidask"})
        n1 = len(provider.calls)
        res = call(s, u, "hesapla", {"mode": "bbg"})
        # the last trades from the last 5 minutes; the sides of the two off the list in a request of their own: 2 hits each
        assert provider.calls[n1:] == [([zsec, tsec], ["PX_BID", "PX_ASK"])]
        assert (res["bbg"]["asked"], res["bbg"]["hits"], res["bbg"]["cached"]) == (0, 4, 2)
        assert res["bbg"]["bidask"] == {"n": 3, "from_sides": 1, "asked": 2, "cached": 0, "why": None}
        rows = {r["isin"]: r for r in res["rows"]}
        # the zero (ISL0: value today, t0): each side's price -> its simple yield, ± 5 bp
        z = rows[ZERO]
        yb, ya = (100.0 / 94.70 - 1.0) * 365.0 / 64, (100.0 / 94.80 - 1.0) * 365.0 / 64
        assert (z["source"], z["base"]) == ("bbg-bidask", "bidask") and "note" not in z
        assert z["bid"]["yield"] == pytest.approx(yb * 100.0 + 0.05) and z["ask"]["yield"] == pytest.approx(ya * 100.0 - 0.05)
        assert z["how"].startswith("Bid/Ask: Bloomberg bid 94,700 / ask 94,800 (valör 03.11.2026) → basit getiri")
        # bid = ask, and DİBS RV's "–": from the mid, as Mid prices them, said first on the row
        for code, why in ((TLREF, "bid = ask (100,350): canlı emir yok, Bloomberg iki tarafa da son fiyatı veriyor"),
                          (on_list, "DİBS RV'de canlı emir yok (bid ve ask –)")):
            r, m = rows[code], mid[code]
            assert r["note"] == " · ".join(["Bid/Ask seçili; %s: mid'den" % why] + ([m["note"]] if m.get("note") else [])), r
            assert {k: v for k, v in r.items() if k not in ("base", "note")} == {k: v for k, v in m.items() if k != "note"}
        # within 5 minutes: nothing asked again
        res = call(s, u, "hesapla", {"mode": "bbg"})
        assert len(provider.calls) == n1 + 1 and res["bbg"]["hits"] == 0 and res["bbg"]["bidask"]["cached"] == 2
        # at 0 spreads: the screen's own prices
        call(s, u, "ayar", {"spreads": {ZERO: {"bid": "0", "ask": "0"}}})
        z0 = {r["isin"]: r for r in call(s, u, "hesapla", {"mode": "bbg"})["rows"]}[ZERO]
        assert z0["bid"]["price"] == pytest.approx(94.70, abs=1e-9) and z0["ask"]["price"] == pytest.approx(94.80, abs=1e-9)
    finally:
        provider.answers.update(saved)


def test_a_eurobond_set_to_bid_ask_starts_its_sides_from_px_bid_and_px_ask(live):
    """A Eurobond set to Bid/Ask (either mode: priced from Bloomberg whatever the switch says): PX_BID / PX_ASK asked with an
    empty mid's in one request (2 hits a bond, in the Eurobonds' hits), each side's yield by the street convention anchored
    as the mid is (the convention's yield of the price − the anchor), the yield spreads each on its own side - at 0 bp
    Bloomberg's prices to the digit; one without sides on Bloomberg from the mid, said."""
    s, provider = live
    fresh(s)
    u = s.login("Yükleme Eurobond Bid Ask")["user"]
    esec = EURO1 + " ISIN"
    saved = provider.answers[esec]
    provider.answers[esec] = dict(saved, PX_BID=E1_MID - 0.25, PX_ASK=E1_MID + 0.25)
    fyk = s.fiyatyukleme
    try:
        call(s, u, "ekle", {"isins": "%s %s %s" % (EURO1, EURO2, EURO3)})
        call(s, u, "ayar", {"bases": {EURO1: "bidask", EURO3: "bidask"}})
        fyk._asked = {}
        n0 = len(provider.calls)
        res = call(s, u, "hesapla", {"mode": "ihale", "text": SAMPLE})
        names = sorted(x + " ISIN" for x in (EURO1, EURO2, EURO3))
        # the mids (2 hits each); the sides of the one whose PX_MID is empty and of the two set to Bid/Ask, one request
        assert provider.calls[n0:] == [(names, ["PX_MID", "YLD_YTM_MID"]), (names, ["PX_BID", "PX_ASK"])]
        assert res["euro"] == {"asked": 3, "hits": 12, "cached": 0, "sides": 1, "why": None, "bidask": {"n": 2, "from_sides": 1}}
        rows = {r["isin"]: r for r in res["rows"]}
        e1 = rows[EURO1]
        bond = fy.street_of(fyk.record(EURO1))
        settle = dt.date(2026, 11, 4)
        anchor = E1_MID - bond.clean(0.0685, settle)
        yb, ya = bond.yield_of(E1_MID - 0.25 - anchor, settle), bond.yield_of(E1_MID + 0.25 - anchor, settle)
        assert (e1["source"], e1["base"]) == ("bbg-bidask", "bidask") and e1["anchor"] == pytest.approx(anchor, abs=1e-12)
        assert e1["t0"] == {"yield": pytest.approx(6.85), "price": E1_MID} and "note" not in e1           # (the mid: Bloomberg's)
        assert e1["bid"]["yield"] == pytest.approx(yb * 100.0 + 0.02, abs=1e-9) and e1["ask"]["yield"] == pytest.approx(ya * 100.0 - 0.02, abs=1e-9)
        assert e1["bid"]["price"] == pytest.approx(bond.clean(yb + 2e-4, settle) + anchor, abs=1e-9)
        assert e1["ask"]["price"] == pytest.approx(bond.clean(ya - 2e-4, settle) + anchor, abs=1e-9)
        assert e1["how"].startswith("Bid/Ask: Bloomberg bid %s / ask %s → getirileri" % (fy._n(E1_MID - 0.25), fy._n(E1_MID + 0.25)))
        # none on Bloomberg: from the mid, said; Mid's row as before
        e3 = rows[EURO3]
        assert e3["source"] == "bbg-mid" and e3["note"].startswith("Bid/Ask seçili; Bloomberg'de bid / ask yok: mid'den · sokak kuralı")
        assert e3["bid"]["yield"] == pytest.approx(6.02) and rows[EURO2]["source"] == "bbg-mid" and "base" not in rows[EURO2]
        # at 0 bp: Bloomberg's bid and ask to the digit (BBG mode the same, from the answers of the last 5 minutes)
        call(s, u, "ayar", {"spreads": {EURO1: {"bid": "0", "ask": "0"}}})
        n1 = len(provider.calls)
        e1z = {r["isin"]: r for r in call(s, u, "hesapla", {"mode": "bbg"})["rows"]}[EURO1]
        assert len(provider.calls) == n1 and e1z["source"] == "bbg-bidask"
        assert e1z["bid"]["price"] == pytest.approx(E1_MID - 0.25, abs=1e-9) and e1z["ask"]["price"] == pytest.approx(E1_MID + 0.25, abs=1e-9)
    finally:
        provider.answers[esec] = saved


# ------------------------------------------------------------------ the provider's one-off request
def test_a_one_off_reference_request_is_counted_and_kept_nowhere():
    srv = fake_blpapi.Server()
    srv.ref[("/isin/TRT060127T10@ISL0", "LAST_PRICE", ())] = 94.75
    srv.ref[("/isin/TRT060127T10@ISL0", "LAST_TRADE_DATE", ())] = dt.date(2026, 11, 3)
    srv.ref[("/isin/TRT130127T11@ISL1", "LAST_PRICE", ())] = 100.4
    srv.invalid.add("/isin/TRT999999T19@ISL1")
    p = BloombergProvider(blpapi_module=fake_blpapi.module(srv), max_hits_per_day=7)
    p.start()
    try:
        got = p.reference(["TRT060127T10 @ISL0 ISIN", "TRT130127T11 @ISL1 ISIN"], ["LAST_PRICE", "last_trade_date"], timeout=10)
        assert got == {"TRT060127T10 @ISL0 ISIN": {"LAST_PRICE": 94.75, "LAST_TRADE_DATE": "3.11.2026"},
                       "TRT130127T11 @ISL1 ISIN": {"LAST_PRICE": 100.4, "LAST_TRADE_DATE": "#N/A N/A"}}
        assert len(srv.requests) == 1 and srv.hits() == 4 and p.hits == 4              # securities × fields, counted
        assert not p._items and not p._values and not p._queue and not p._subs           # nothing kept, refreshed or streamed
        time.sleep(0.6)
        assert len(srv.requests) == 1
        bad = p.reference(["TRT999999T19 @ISL1 ISIN"], ["LAST_PRICE"], timeout=10)
        assert bad["TRT999999T19 @ISL1 ISIN"]["LAST_PRICE"].startswith("#N/A") and p.hits == 5
        assert p.reference(["TRT060127T10 @ISL0 ISIN"], ["LAST_PRICE", "LAST_TRADE_DATE"], timeout=10) is not None and p.hits == 7
        assert p.reference(["TRT060127T10 @ISL0 ISIN"], ["LAST_PRICE"], timeout=10) is None             # the daily limit
        assert len(srv.requests) == 3 and p.reference([], ["LAST_PRICE"]) == {}
    finally:
        p.stop()


def test_the_helper_process_asks_for_the_dashboard_and_counts(monkeypatch, tmp_path):
    from tto.marketdata.bbg_process import IsolatedBloombergProvider
    monkeypatch.setenv("TTO_FAKE_BBG", json.dumps({"securities": 1, "stats": str(tmp_path / "stats.json")}))
    p = IsolatedBloombergProvider(blpapi_name="fake_blpapi_live", reconnect_wait=0.2)
    p.start()
    try:
        got = p.reference(["USDTRY Curncy"], ["PX_LAST", "BID"], timeout=10)
        assert got == {"USDTRY Curncy": {"PX_LAST": 49.9973, "BID": 49.997}}
        t0 = time.time()
        while time.time() - t0 < 10 and p.status()["hits_today"] != 2:
            time.sleep(0.05)
        assert p.status()["hits_today"] == 2
    finally:
        p.stop()


# ================================================================================================== over HTTP (last: the client stops the service)
def test_the_routes(svc):
    fresh(svc)
    with TestClient(create_app(svc)) as c:
        assert c.get("/api/fiyat-yukleme", headers=ANON).status_code == 401
        assert c.post("/api/fiyat-yukleme/hesapla", headers=ANON, json={"mode": "ihale"}).status_code == 401
        assert c.get("/api/fiyat-yukleme/dosya", headers=ANON).status_code == 401
        h = auth(svc, "Yükleme HTTP")
        st = c.get("/api/fiyat-yukleme", headers=h)
        assert st.status_code == 200 and st.json()["list"] == [] and st.json()["mode"] == "ihale" and st.json()["defaults"] == fy.DEFAULTS
        bad = c.post("/api/fiyat-yukleme/ekle", headers=h, json={"isins": "TRT150328T25"})
        assert bad.status_code == 400 and "kontrol hanesi tutmuyor" in bad.json()["error"]
        bad = c.post("/api/fiyat-yukleme/hesapla", headers=h, json={"mode": "ihale", "text": ""})
        assert bad.status_code == 400 and bad.json()["error"] == "İhale fiyatlarını yapıştırın"
        bad = c.get("/api/fiyat-yukleme/dosya", headers=h)
        assert bad.status_code == 400 and "kaydedilmiş dosya yok" in bad.json()["error"]
        assert c.post("/api/fiyat-yukleme/yok", headers=h, json={}).status_code == 404
        assert c.post("/api/fiyat-yukleme/ayar", headers=h, json={"mode": "x"}).status_code == 400
        assert c.post("/api/fiyat-yukleme/ekle", headers=h, json={"isins": "%s\n%s" % (FIXED, TLREF)}).json()["added"] == [FIXED, TLREF]
        res = c.post("/api/fiyat-yukleme/hesapla", headers=h, json={"mode": "ihale", "text": SAMPLE}).json()
        rows = [{"isin": r["isin"], "bid_price": r["bid"]["price"], "ask_price": r["ask"]["price"], "bid_yield": r["bid"]["yield"],
                 "ask_yield": r["ask"]["yield"]} for r in res["rows"]]
        saved = c.post("/api/fiyat-yukleme/kaydet", headers=h, json={"rows": rows}).json()
        assert saved["lines"][1] == "TRT130127T11,100.450,100.550,0,0"
        got = c.get("/api/fiyat-yukleme/dosya", headers=h)
        assert got.status_code == 200 and got.content == saved["text"].encode("ascii") and b"\r\n" in got.content
        assert got.headers["content-disposition"] == 'attachment; filename="dibs_fiyat_20261103.txt"'
        assert c.get("/static/js/pages/fiyatyukleme.js").status_code == 200
        # the page asks on a new generation by the list's revision: unchanged - a short answer; changed - the state
        rev = c.get("/api/fiyat-yukleme", headers=h).json()["rev"]
        assert c.get("/api/fiyat-yukleme?rev=%d" % rev, headers=h).json() == {"rev": rev, "unchanged": True}
        c.post("/api/fiyat-yukleme/ayar", headers=h, json={"spreads": {FIXED: {"bid": "6"}}})
        assert c.get("/api/fiyat-yukleme?rev=%d" % rev, headers=h).json()["rev"] == rev + 1
        # Sabit fiyat: a session needed; a Turkish reason for what cannot be kept
        assert c.post("/api/fiyat-yukleme/sabit", headers=ANON, json={"isin": FIXED, "bid": "99", "ask": "100"}).status_code == 401
        assert c.post("/api/fiyat-yukleme/sabit-sil", headers=ANON, json={"isin": FIXED}).status_code == 401
        bad = c.post("/api/fiyat-yukleme/sabit", headers=h, json={"isin": FIXED, "bid": "abc", "ask": "100"})
        assert bad.status_code == 400 and bad.json()["error"] == "bid ve ask'i sayı olarak girin"
        bad = c.post("/api/fiyat-yukleme/sabit-sil", headers=h, json={"isin": FIXED})
        assert bad.status_code == 400 and bad.json()["error"] == "sabit fiyatı yok: %s" % FIXED
        assert c.post("/api/fiyat-yukleme/sabit-yapistir", headers=ANON, json={"text": LOWER}).status_code == 401
        bad = c.post("/api/fiyat-yukleme/sabit-yapistir", headers=h, json={"text": ""})
        assert bad.status_code == 400 and bad.json()["error"] == "Excel'den ISIN, bid ve offer'ı kopyalayıp yapıştırın"
        ok = c.post("/api/fiyat-yukleme/sabit", headers=h, json={"isin": FIXED, "bid": "99,1", "ask": "99,9"})
        assert ok.status_code == 200 and ok.json()["fixed"][0]["bid"] == 99.1 and ok.json()["fixed"][0]["listed"]
