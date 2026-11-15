"""Hazine İhalesi (``EK_IHALE``): the dirty price to bid from a clean price, a simple or a compound yield - with
Bloomberg's accrued interest at the auction's value date - and where each bid stands once the auction is over.

The service runs on a connected Bloomberg stand-in that answers at once.  Its answers are test values: the coupons
and maturities of the desk's bond list, accrued interest worked out with the Treasury's 182-day coupon periods,
an invented index ratio and floater coupon."""
from __future__ import annotations

import json
import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.config import Settings
from tto.marketdata.base import NOT_APPLICABLE, bdp_key
from tto.marketdata.bloomberg import NA_NA, NO_BFX, NO_RT
from tto.marketdata.replay import ReplayProvider
from tto.service import Service
from tto.xl.engine import Clock
from tto.xl.model import COLS, Model, a1, parse_range

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALOR, ON_COUPON, LATER = "20261023", "20260916", "20261118"     # value dates the stand-in knows (23.10, 16.09, 18.11.2026)


class Direct(ReplayProvider):
    """A connected Bloomberg that answers at once (and keeps what it was asked)."""
    live = True

    def __init__(self, snapshot):
        super().__init__(snapshot)
        self.asked = set()

    def _get(self, key):
        self.asked.add(key)
        v = self.snapshot.get(key)
        return NA_NA if v is None else v

    get_bdp = get_bdh = get_bds = _get

    def get_bfx(self, key):
        return NO_BFX

    def get_rt(self, key):
        return NO_RT


def _bloomberg():
    """What the stand-in answers: per ISIN the bond's own fields, and per value date what depends on it."""
    out = {}

    def bond(isin, static, dated):
        sec = isin + " ISIN"
        for field, value in static.items():
            out[bdp_key(sec, field)] = value
        for day, fields in dated.items():
            for field, value in fields.items():
                out[bdp_key(sec, field, (("SETTLE_DT", day),))] = value

    # fixed coupon, 36.80 % in two coupons a year, coupons every 182 days back from 15.03.2028
    bond("TRT150328T24", {"NAME": "TURKIYE GOVERNMENT BOND", "CPN": 36.8, "CPN_TYP": "FIXED", "MATURITY": "15.03.2028", "CPN_FREQ": 2.0,
                          "INFLATION_LINKED_INDICATOR": "N"},
         {VALOR: {"INT_ACC": 18.4 * 37 / 182, "PREV_CPN_DT": "16.09.2026", "NXT_CPN_DT": "17.03.2027", "DAYS_ACC": 37.0},
          ON_COUPON: {"INT_ACC": 0.0, "PREV_CPN_DT": "16.09.2026", "NXT_CPN_DT": "17.03.2027", "DAYS_ACC": 0.0},
          LATER: {"INT_ACC": 18.4 * 63 / 182, "PREV_CPN_DT": "16.09.2026", "NXT_CPN_DT": "17.03.2027", "DAYS_ACC": 63.0}})
    # a new issue with a long first coupon (an invented ISIN): 210 days to it, then 182-day periods to the maturity
    bond("TRT140329T11", {"NAME": "TURKIYE GOVERNMENT BOND", "CPN": 30.0, "CPN_TYP": "FIXED", "MATURITY": "14.03.2029", "CPN_FREQ": 2.0,
                          "INFLATION_LINKED_INDICATOR": "N"},
         {VALOR: {"INT_ACC": 15.0 * 65 / 210, "PREV_CPN_DT": "19.08.2026", "NXT_CPN_DT": "17.03.2027", "DAYS_ACC": 65.0}})
    # a bill: no coupon, no coupon dates (Bloomberg: field not applicable)
    bond("TRB170327T15", {"NAME": "TURKIYE T-BILL", "CPN": 0.0, "CPN_TYP": "ZERO COUPON", "MATURITY": "17.03.2027",
                          "CPN_FREQ": NOT_APPLICABLE, "INFLATION_LINKED_INDICATOR": "N"},
         {VALOR: {"INT_ACC": 0.0, "PREV_CPN_DT": NOT_APPLICABLE, "NXT_CPN_DT": NOT_APPLICABLE, "DAYS_ACC": NOT_APPLICABLE}})
    # a TLREF floater: four coupons a year, its current coupon only Bloomberg knows
    bond("TRT170528T12", {"NAME": "TURKIYE GOVERNMENT BOND", "CPN": 38.0, "CPN_TYP": "FLOATING", "MATURITY": "17.05.2028",
                          "CPN_FREQ": 4.0, "INFLATION_LINKED_INDICATOR": "N"},
         {VALOR: {"INT_ACC": 6.75, "PREV_CPN_DT": "19.08.2026", "NXT_CPN_DT": "18.11.2026", "DAYS_ACC": 65.0}})
    # an FRN: a floater whose coupon does not follow TLREF (Tüm Kâğıtlar knows it as one), two coupons a year
    bond("TRT171127T15", {"NAME": "TURKIYE GOVERNMENT BOND", "CPN": 40.1, "CPN_TYP": "FLOATING", "MATURITY": "17.11.2027",
                          "CPN_FREQ": 2.0, "INFLATION_LINKED_INDICATOR": "N"},
         {VALOR: {"INT_ACC": 7.25, "PREV_CPN_DT": "20.05.2026", "NXT_CPN_DT": "18.11.2026", "DAYS_ACC": 156.0}})
    # a CPI linker: a real coupon of 3.30 %, priced real, paid with the index ratio of the value date
    bond("TRT280628T18", {"NAME": "TURKIYE GOVERNMENT BOND", "CPN": 3.3, "CPN_TYP": "FIXED", "MATURITY": "28.06.2028", "CPN_FREQ": 2.0,
                          "INFLATION_LINKED_INDICATOR": "Y"},
         {VALOR: {"INT_ACC": 1.65 * 114 / 182, "PREV_CPN_DT": "01.07.2026", "NXT_CPN_DT": "30.12.2026", "DAYS_ACC": 114.0,
                  "IDX_RATIO": 12.5}})
    return out


@pytest.fixture(scope="module")
def auction(module_service, tmp_path_factory):
    today = module_service.books["tto"].engine.clock.today()
    snapshot = dict(module_service.provider.snapshot)
    snapshot.update(_bloomberg())
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    provider = Direct(snapshot)
    live = Service(Settings(data_dir=str(tmp_path_factory.mktemp("ihale")), mode="live"), provider=provider, clock=clock)
    user = live.login("İhale Masası")["user"]
    yield live, user, provider
    live.stop()


def page_inputs():
    with open(os.path.join(ROOT, "tto", "views", "63_ihale.json"), encoding="utf-8") as fh:
        view = json.load(fh)
    refs = []
    for inp in view["inputs"]:
        r1, c1, r2, c2 = parse_range(inp["range"])
        refs += [a1(r * COLS + c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
    return view, refs


def fill(svc, user, values):
    """Empty every input of the page, then type ``values`` ({"C10": "100,70", ...})."""
    _, refs = page_inputs()
    res = svc.set_inputs(user, "tto", [{"ref": "EK_IHALE!" + r, "value": None} for r in refs])
    assert not res["errors"]
    if values:
        res = svc.set_inputs(user, "tto", [{"ref": "EK_IHALE!" + r, "value": v} for r, v in values.items()])
        assert not res["errors"], res["errors"]


def get(svc, ref):
    return cell(svc, "EK_IHALE!" + ref)


def bist_simple(dirty, coupon, w, n, freq=2):
    """The DİBS RV ("BIST") simple yield, found by bisection: the coupons discounted at (1 + y/f) per period."""
    def pv(y):
        return sum((coupon / freq + (100 if i == n else 0)) * (1 + y / freq) ** -(w + i - 1) for i in range(1, n + 1))
    lo, hi = -0.5, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if pv(mid) > dirty else (lo, mid)
    return lo, pv


# ---------------------------------------------------------------------------------------------- before the auction
def test_a_bid_is_priced_from_a_clean_price_a_simple_or_a_compound_yield(auction):
    svc, user, _ = auction
    fill(svc, user, {"B2": "23.10.2026", "A7": "trt150328t24", "B10": "35000000", "C10": "100,70", "B11": "50000000", "D11": "35,86",
                     "B12": "50000000", "E12": "39,05", "C13": "100,75", "D13": "36"})
    # the bond as Bloomberg sees it at the value date
    assert [get(svc, c + "7") for c in "CDEFGHIJKL"] == ["15.03.28", "Sabit kuponlu", 0.368, 46827.0, 46281.0, 46463.0, 37.0, 182.0,
                                                         pytest.approx(18.4 * 37 / 182), 46318.0]
    assert get(svc, "A5") == "KÂĞIT 1 · 15.03.28 · TRT150328T24"
    assert get(svc, "A8") == "Birikmiş faiz, kupon tarihleri ve işlemiş gün Bloomberg'den, valöre göre"
    acc = 18.4 * 37 / 182
    w, n = (46463 - 46318) / 182, 3                   # the rest of the current period; coupons 17.03.27, 15.09.27, 15.03.28
    # a clean price: the dirty price to bid is clean + accrued, rounded to three decimals
    simple, pv = bist_simple(100.7 + acc, 36.8, w, n)
    assert [get(svc, c + "10") for c in "FG"] == ["Temiz", 100.7]
    assert get(svc, "H10") == pytest.approx(simple, abs=1e-10)
    assert get(svc, "I10") == pytest.approx((1 + simple / 2) ** 2 - 1, abs=1e-10)
    assert get(svc, "J10") == 104.441 and get(svc, "K10") == pytest.approx(35e6 * 104.441 / 100)
    # a simple yield: the price that discounts to it
    assert get(svc, "F11") == "Basit" and get(svc, "H11") == pytest.approx(0.3586)
    assert get(svc, "G11") == pytest.approx(pv(0.3586) - acc, abs=1e-10) and get(svc, "J11") == round(pv(0.3586), 3)
    assert get(svc, "I11") == pytest.approx(1.1793 ** 2 - 1)
    # a compound yield: its simple yield, then the price
    s12 = 2 * (1.3905 ** 0.5 - 1)
    assert get(svc, "F12") == "Bileşik" and get(svc, "I12") == pytest.approx(0.3905) and get(svc, "H12") == pytest.approx(s12)
    assert get(svc, "G12") == pytest.approx(pv(s12) - acc, abs=1e-10)
    # two inputs on one line: the clean price wins, and the line says so
    assert get(svc, "F13") == "Temiz · diğerine bakılmadı" and get(svc, "G13") == 100.75 and get(svc, "J13") == round(100.75 + acc, 3)
    # all the bids: the nominal, the average dirty price weighted by it, its clean price and yields, the amount
    dirty = [get(svc, "J%d" % r) for r in (10, 11, 12)]
    avg = (35 * dirty[0] + 50 * dirty[1] + 50 * dirty[2]) / 135
    assert get(svc, "B15") == 135e6 and get(svc, "J15") == pytest.approx(avg) and get(svc, "G15") == pytest.approx(avg - acc)
    assert get(svc, "H15") == pytest.approx(bist_simple(avg, 36.8, w, n)[0], abs=1e-10)
    assert get(svc, "K15") == pytest.approx(sum(get(svc, "K%d" % r) for r in (10, 11, 12)))
    # nothing of the auction's result yet
    assert [get(svc, c + "10") for c in "LMNOQ"] == [""] * 5
    assert get(svc, "A22").startswith("İhale bitince açıklanan asgari")


def test_a_long_current_coupon_period_does_not_change_the_number_of_coupons(auction):
    """A new issue with a long first coupon: the coupons left are counted in periods of the calendar (364 / 2 days, as
    DİBS RV counts them), not in the length of the current period - which would leave one out."""
    svc, user, _ = auction
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT140329T11", "B10": "10000000", "D10": "30"})
    acc = 15.0 * 65 / 210
    w, n = (46463 - 46318) / 210, 5                   # coupons 17.03.27, 15.09.27, 14.03.28, 12.09.28, 14.03.29
    pv = bist_simple(100.0, 30.0, w, n)[1]
    assert get(svc, "J10") == round(pv(0.30), 3) and get(svc, "G10") == pytest.approx(pv(0.30) - acc, abs=1e-10)


def test_the_auction_says_which_bids_won_and_where_they_stand(auction):
    svc, user, _ = auction
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT150328T24", "B10": "35000000", "C10": "100,70", "B11": "50000000", "C11": "100,725",
                     "B12": "50000000", "C12": "100,75", "B13": "20000000", "C13": "100,709",
                     "B18": "104,450", "B19": "104,470", "B20": "104,520"})
    acc = 18.4 * 37 / 182
    w, n = (46463 - 46318) / 182, 3
    # the announced prices are dirty, as bid: their clean prices and yields
    for r, dirty in ((18, 104.45), (19, 104.47), (20, 104.52)):
        assert get(svc, "C%d" % r) == pytest.approx(dirty - acc)
        assert get(svc, "D%d" % r) == pytest.approx(bist_simple(dirty, 36.8, w, n)[0], abs=1e-10)
    # 104.441 < the lowest accepted price; 104.450 is at it (may be filled in part); the others are above it
    assert [get(svc, "J%d" % r) for r in (10, 11, 12, 13)] == [104.441, 104.466, 104.491, 104.45]
    assert [get(svc, "L%d" % r) for r in (10, 11, 12, 13)] == ["Gerçekleşmedi", "Gerçekleşti", "Gerçekleşti", ex.AUC_PART]
    assert get(svc, "M11") == pytest.approx(104.466 - 104.47) and get(svc, "O12") == pytest.approx((104.491 - 104.45) / 0.07)
    assert get(svc, "N12") == pytest.approx((get(svc, "H12") - get(svc, "D19")) * 1e4)
    # what was won: at its own price (a multiple-price auction); at the lowest price the whole bid until told otherwise
    assert [get(svc, "Q%d" % r) for r in (10, 11, 12, 13)] == [0.0, 50e6, 50e6, 20e6] and get(svc, "Q15") == 120e6
    mine = (50 * 104.466 + 50 * 104.491 + 20 * 104.45) / 120
    assert get(svc, "B21") == pytest.approx(mine) and get(svc, "C21") == pytest.approx(mine - acc)
    assert get(svc, "D21") == pytest.approx(bist_simple(mine, 36.8, w, n)[0], abs=1e-10)
    assert get(svc, "F21") == pytest.approx(mine - 104.47) and get(svc, "G21") == pytest.approx((get(svc, "D21") - get(svc, "D19")) * 1e4)
    assert get(svc, "H21") == 120e6 and get(svc, "I21") == pytest.approx(120e6 * mine / 100)
    assert get(svc, "A22").startswith("2 teklif gerçekleşti, 1 teklif asgari fiyatta (kısmi olabilir), 1 teklif gerçekleşmedi. "
                                      "Gerçekleşen ortalamanız ihale ortalamasından ")
    # the nominal allotted at the lowest price, typed when it is known
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT150328T24", "B12": "50000000", "C12": "100,75", "B13": "20000000", "C13": "100,709",
                     "P13": "8000000", "B18": "104,450", "B19": "104,470", "B20": "104,520"})
    assert get(svc, "Q13") == 8e6 and get(svc, "Q15") == 58e6
    assert get(svc, "B21") == pytest.approx((50 * 104.491 + 8 * 104.45) / 58)


def test_bills_floaters_and_cpi_linkers(auction):
    svc, user, _ = auction
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRB170327T15", "B10": "10000000", "C10": "88,50", "D11": "40", "E12": "45",
                     "A27": "TRT170528T12", "B30": "10000000", "C30": "101,20", "D31": "40",
                     "A47": "TRT280628T18", "B50": "10000000", "C50": "102,40"})
    # a bill: no accrued interest (Bloomberg's 0), yields from the price and the days to maturity
    g = 46463 - 46318
    assert [get(svc, c + "7") for c in "DEGHIK"] == ["Bono / kuponsuz", "", "", "", "", 0.0]
    assert get(svc, "J10") == 88.5 and get(svc, "H10") == pytest.approx((100 / 88.5 - 1) * 365 / g)
    assert get(svc, "I10") == pytest.approx((100 / 88.5) ** (365 / g) - 1)
    assert get(svc, "G11") == pytest.approx(100 / (1 + 0.4 * g / 365)) and get(svc, "H11") == pytest.approx(0.4)
    assert get(svc, "G12") == pytest.approx(100 / 1.45 ** (g / 365)) and get(svc, "I12") == pytest.approx(0.45)
    # a TLREF floater: the dirty price with Bloomberg's accrued, no yield - a yield typed for it prices nothing
    assert get(svc, "D27") == "TLREF" and get(svc, "A28") == "TLREF: kirli fiyat ve ihaledeki yer; getiri hesaplanmaz"
    assert get(svc, "J30") == round(101.2 + 6.75, 3) and [get(svc, c + "30") for c in "HI"] == ["", ""]
    assert get(svc, "F31") == "TLREF: temiz fiyat yazın" and get(svc, "J31") == ""
    # a CPI linker: the real price and real yield; the TL amount with the index ratio of the value date
    acc = 1.65 * 114 / 182
    assert get(svc, "D47") == "TÜFE" and get(svc, "M47") == 12.5
    assert get(svc, "J50") == round(102.4 + acc, 3)
    w, n = (46386 - 46318) / 182, 4                    # coupons 30.12.26, 30.06.27, 29.12.27, 28.06.28
    assert get(svc, "H50") == pytest.approx(bist_simple(102.4 + acc, 3.3, w, n)[0], abs=1e-10)
    assert get(svc, "K50") == pytest.approx(10e6 * get(svc, "J50") / 100 * 12.5)


def test_an_frn_is_priced_as_a_floater_under_its_own_name(auction):
    """An FRN - a floater whose coupon does not follow TLREF - is priced as a TLREF floater is (its dirty price with
    Bloomberg's accrued, its place in the auction, no yield), under its own name."""
    svc, user, _ = auction
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT171127T15", "B10": "10000000", "C10": "99,80", "D11": "40"})
    assert [get(svc, c + "7") for c in "CD"] == ["17.11.27 FRN", "FRN"] and get(svc, "A5") == "KÂĞIT 1 · 17.11.27 FRN · TRT171127T15"
    assert get(svc, "A8") == "FRN: kirli fiyat ve ihaledeki yer; getiri hesaplanmaz"
    assert get(svc, "J10") == round(99.8 + 7.25, 3) and [get(svc, c + "10") for c in "HI"] == ["", ""]
    assert get(svc, "F11") == "FRN: temiz fiyat yazın" and get(svc, "J11") == ""


def test_the_accrued_interest_is_bloombergs_at_the_value_date(auction):
    svc, user, provider = auction
    # no value date: nothing is priced
    fill(svc, user, {"A7": "TRT150328T24", "C10": "100,70"})
    assert get(svc, "A8") == "← İhale valörünü (üstte) ya da bu kâğıdın valörünü yazın" and get(svc, "J10") == ""
    # the auction's value date, or the bond's own: Bloomberg is asked at that date
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT150328T24", "B7": "18.11.2026", "C10": "100,70"})
    assert get(svc, "L7") == 46344.0 and get(svc, "I7") == 63.0
    assert get(svc, "K7") == pytest.approx(18.4 * 63 / 182) and get(svc, "J10") == round(100.7 + 18.4 * 63 / 182, 3)
    asked = {k[3] for k in provider.asked if k[0] == "BDP" and k[1] == "TRT150328T24 ISIN" and k[2] == "INT_ACC"}
    assert (("SETTLE_DT", LATER),) in asked and () not in asked             # never without the value date
    # a value date on a coupon date: Bloomberg's accrued is 0 and the next coupon is a whole period away
    fill(svc, user, {"B2": "16.09.2026", "A7": "TRT150328T24", "C10": "100,70"})
    assert get(svc, "K7") == 0.0 and get(svc, "I7") == 0.0 and get(svc, "J10") == 100.7
    assert get(svc, "H10") == pytest.approx(bist_simple(100.7, 36.8, 1.0, 3)[0], abs=1e-10)
    # a value date Bloomberg has not answered for: no accrued is worked out instead - nothing is priced
    fill(svc, user, {"B2": "24.10.2026", "A7": "TRT150328T24", "C10": "100,70"})
    assert get(svc, "K7") == "" and get(svc, "J10") == ""
    assert get(svc, "A8") == "Bloomberg'den valördeki birikmiş faiz bekleniyor"
    # an ISIN Bloomberg does not know
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT000000T00"})
    assert get(svc, "A8").startswith("Bloomberg: #N/A") and get(svc, "C7") == "#N/A N/A"


# ---------------------------------------------------------------------------------------------- the page
def test_the_auction_page(auction, service):
    svc, user, _ = auction
    view, refs = page_inputs()
    assert (view["id"], view["group"], view["sheet"]) == ("ihale", "Tahvil", ex.AUC_SHEET)
    assert {i["scope"] for i in view["inputs"]} == {"shared"}                     # the desk's bids, for everyone
    rows = [ex.auction_rows(k) for k in range(ex.AUC_BONDS)]
    assert [r["info"] for r in rows] == [7, 27, 47] and [r["lines"][0] for r in rows] == [10, 30, 50]
    assert {"B2", "A7", "B7", "C10", "D10", "E10", "P14", "B18", "B20", "A47", "E54", "B60"} <= set(refs)
    assert ex.auction_cols()["last"] == "DE" and ex.AUC_CF == 30                    # (the floater's kind: 4 cells more)
    fill(svc, user, {"B2": "23.10.2026", "A7": "TRT150328T24", "C10": "100,70"})
    page = svc.view(user, "ihale")
    titles = {p["id"]: p["title"] for p in page["panels"]}
    assert titles["H1"] == "KÂĞIT 1 · 15.03.28 · TRT150328T24" and titles["H2"] == "KÂĞIT 2"
    assert "ihale" in {p["id"] for p in svc.nav()}
    # offline the page is there, empty-handed: Bloomberg answers nothing recorded
    assert service.view(None, "ihale")["panels"][0]["id"] == "H0"
    assert cell(service, "EK_IHALE!A8") == "← ISIN yazın"
    # an addition for the TRY workbook only
    sofr = Model.load(os.path.join(ROOT, "models", "sofr.json.gz"))
    with pytest.raises(ValueError):
        ex._auction_check(sofr)
