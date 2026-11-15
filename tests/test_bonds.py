"""TRY government bonds: the catalog of the desk's Bloomberg list, bonds added to a page's list by ISIN, the broker
chat's bond quotes ("15/3/28 550/575", "Jan30 tlref 98.650/750", auction prices) read against the DİBS RV screen and
shown next to it, and the tables that grow (Bulk Bond, the 100-row bulk forward)."""
from __future__ import annotations

import datetime as dt
import re

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell, make_service
from tto import bonds as bd
from tto import brokerchat as bc
from tto import extras as ex
from tto.marketdata.base import NOT_APPLICABLE, bdp_key
from tto.server import create_app
from tto.service import ServiceError
from tto.store import user_key

TODAY = dt.date(2026, 11, 13)

# where the bonds stand in the tests of the parser alone (clean prices; a bill at its yield)
SCREEN = {"DIBS:TRT150328T24": 100.56, "DIBS:TRT160431T35": 94.40, "DIBS:TRT050527T33": 102.925, "DIBS:TRT110930T36": 97.575,
          "DIBS:TRB100227T13": 34.80}

# the desk's sample, shortened: an auction list under its heading, then the brokers' ways of quoting a bond
CHAT = """AKTAN ACIKGOZ
08:46:28 Gunaydin...
09:14:59 Auction prices:
06/01/2027.t1   31.450
10/02/2027zc.t1   31.400
10/02/2027.t1   99.445
15/03/2028.t1   100.650
16/04/2031.t1   93.950
09:43:31 15/3/28 any int?
10:10:59 15/3/28 550 bid
10:25:28 15/3/28 550/575
11:16:19 16/4/31 100/200
11:49:56 11/9/30 tlref  675/800 tdy
13:12:50 5/5/27 000/150 bid f50 tom
13:18:40 15/3/28 550 bidim refledi
13:21:38 15/3/28 550 traded
13:27:16 16/4/31 100 given
13:36:12 13/10/27 tlref  100.650/.800
16:32:04 Sw int 9/1/30 775 offer vs  3/7/30 775 bid
HAKAN DIKMEN
09:51:39 Jan30 tlref 98.650/750 nl
14:05:26 mar28 .400/475
ONDER TURKER
10:22:33 feb27 99.450 offer
14:13:22 mar28 given
17:29:21 jan28 tlref .725 trading
"""


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def ref(q):
    return SCREEN.get(q["key"])


def one(text, where=ref):
    quotes = bc.parse_message(text, where)
    assert len(quotes) == 1, (text, quotes)
    return quotes[0]


# ---------------------------------------------------------------------------------------------- the catalog
def test_an_isin_is_checked_and_a_turkish_one_carries_its_maturity():
    assert bd.isin_valid("TRT150328T24") and bd.isin_valid(" trt150328t24 ") and bd.isin_valid("US0378331005")
    assert not any(bd.isin_valid(x) for x in ("TRT150328T25", "TRT15032", "", None, "TRT150328T2X", "1RT150328T24"))
    assert bd.maturity_of("TRT150328T24") == dt.date(2028, 3, 15)
    assert bd.maturity_of("TRB100227T13") == dt.date(2027, 2, 10)                   # a bill
    assert bd.maturity_of("US0378331005") is None and bd.maturity_of("TRT310228T11") is None   # no 31 February


def test_the_catalog_is_the_desks_list_of_try_government_bonds():
    cat = bd.catalog()
    assert len(cat) == 77 and len({b["isin"] for b in cat}) == 77
    assert all(bd.isin_valid(b["isin"]) and bd.maturity_of(b["isin"]).isoformat() == b["maturity"] for b in cat)
    assert [b["maturity"] for b in cat] == sorted(b["maturity"] for b in cat)
    kinds = {k: sum(1 for b in cat if b["kind"] == k) for k in bd.KINDS}
    assert kinds == {"bill": 2, "zero": 2, "fixed": 26, "cpi": 24, "float": 23}
    b = bd.by_isin("trt150328t24")
    assert (b["kind"], b["coupon"], bd.short_label(b), bd.quoted_in_yield(b)) == ("fixed", 36.8, "15.03.28", False)
    assert bd.short_label(bd.by_isin("TRT090130T12")) == "09.01.30 TLREF"
    assert bd.short_label(bd.by_isin("TRB100227T13")) == "10.02.27 Bono" and bd.quoted_in_yield(bd.by_isin("TRB100227T13"))
    assert bd.by_isin("TRT050527T33")["coupon"] == 41.0 and bd.by_isin("XS0000000000") is None
    # what a chat line can mean: a month's plain bonds, its floater, the bill of a day
    assert [c["isin"] for c in bd.candidates(month="2028-03")] == ["TRT080328T15", "TRT150328T24"]
    assert [c["isin"] for c in bd.candidates(month="2028-03", kind="float")] == ["TRT010328T12"]
    assert [c["isin"] for c in bd.candidates(date="2027-02-10", kind="zc")] == ["TRB100227T13"]
    assert [c["isin"] for c in bd.candidates(date="2027-02-10")] == ["TRB100227T13", "TRT100227T13"]
    assert [c["isin"] for c in bd.candidates(month="2027-02", kind="fixed")] == ["TRT100227T13", "TRT240227T17"]   # not the bill
    assert bd.candidates(month="2029-06", kind="fixed") == []                         # a CPI linker and a floater only
    assert bd.candidates() == [] and bd.candidates(month="2045-01") == []


# ---------------------------------------------------------------------------------------------- the chat, line by line
def test_a_bond_is_named_the_ways_the_brokers_write_it():
    q = one("15/3/28 550/575")
    assert (q["product"], q["key"], q["isin"], q["label"], q["unit"], q["bid"], q["ask"]) == (
        "DIBS", "DIBS:TRT150328T24", "TRT150328T24", "15.03.28", "px", 100.55, 100.575)
    assert q["flags"] == ["abbr"] and q["bond_kind"] == "fixed"
    assert one("16/4/31 100/200")[("bid")] == 94.1 and one("16/4/31 100/200")["ask"] == 94.2
    assert (one("apr31 94.125 bid")["bid"], one("April 31 100/125")["ask"]) == (94.125, 94.125)
    q = one("Sep 34 625/700 for 50 mio")                                            # not on this screen: as typed, and said so
    assert (q["isin"], q["bid"], q["ask"], q["note"]) == ("TRT270934T18", 0.625, 0.7, "50") and "no-ref" in q["flags"]
    q = one("13/10/27 tlref 100.650/.800")
    assert (q["isin"], q["label"], q["bid"], q["ask"], q["bond_kind"]) == ("TRT131027T10", "13.10.27 TLREF", 100.65, 100.8, "float")
    q = one("11/9/30 tlref  675/800 tdy")
    assert (q["isin"], q["bid"], q["ask"], q["settle"], q["note"]) == ("TRT110930T36", 97.675, 97.8, "T0", "")
    q = one("5/5/27 000/150 bid f50 tom")
    assert (q["isin"], q["bid"], q["ask"], q["settle"], q["note"], q["product"]) == ("TRT050527T33", 103.0, 103.15, "T1", "f50", "DIBS")
    q = one("02/05/2029 cpi.t1 92.050")
    assert (q["isin"], q["event"], q["price"], q["settle"], q["unit"], q["bond_kind"]) == ("TRT020529T18", "level", 92.05, "T1", "px", "cpi")
    # a bill or a zero coupon bond trades on its yield
    q = one("10/02/2027zc.t1   31.400")
    assert (q["isin"], q["unit"], q["event"], q["price"], q["settle"]) == ("TRB100227T13", "yld", "level", 31.4, "T1")
    # a month that has more than one bond: the benchmark (highest coupon), flagged
    q = one("mar28 .400/475")
    assert (q["isin"], q["bid"], q["ask"], q["alts"]) == ("TRT150328T24", 100.4, 100.475, ["TRT080328T15"]) and "bond?" in q["flags"]
    q = one("Jan30 tlref 98.650/750 nl")
    assert (q["bond_kind"], q["ask"], q["note"]) == ("float", 98.75, "nl") and "bond?" in q["flags"] and len(q["alts"]) == 1


def test_a_month_and_a_year_alone_are_the_fixed_coupon_bond():
    """"mar28", "feb27", "Sep 34": the desk names a fixed coupon bond by its month alone - a floater, a CPI linker or a
    bill is said to be one ("jan30 tlref", "jun29 cpi", "feb27 bono").  A month without a fixed coupon bond can mean
    its other bonds ("jan30" for its floater): a floater first, then a CPI linker, then a bill - flagged.  A kind said
    is that kind only."""
    q = one("feb27 99.450 offer")
    assert (q["isin"], q["bond_kind"], q["alts"]) == ("TRT100227T13", "fixed", ["TRT240227T17"])        # the bill of the month is not a candidate
    # no fixed coupon bond in June 2029 or in January 2030: the month's floater, the others as candidates
    q = one("jun29 99.50/99.70")
    assert (q["isin"], q["bond_kind"], q["alts"], q["unit"]) == ("TRT130629T30", "float", ["TRT130629T14"], "px")
    assert {"bond?", "notfixed"} <= set(q["flags"]) and "nobond" not in q["flags"]
    q = one("jan30 98.650/750")
    assert (q["isin"], q["alts"], q["bid"], q["ask"]) == ("TRT020130T19", ["TRT090130T12"], 98.65, 98.75) and "notfixed" in q["flags"]
    assert "notfixed" not in one("mar28 .400/475")["flags"] and "notfixed" not in one("Jan30 tlref 98.650/750")["flags"]
    assert "nobond" in one("mar28 zc 36.50")["flags"] and "nobond" in one("dec29 tlref 99.00")["flags"]  # a kind said: that kind only
    assert (one("jun29 cpi 92.050")["isin"], one("jun29 tlref 98.650")["isin"]) == ("TRT130629T14", "TRT130629T30")
    q = one("feb27 bono 31.40")
    assert (q["isin"], q["unit"], q["price"]) == ("TRB100227T13", "yld", 31.4) and q["flags"] == []
    assert "nobond" in one("dec26 31.40")["flags"]
    # a date says which bond matures then, of whatever kind (the kind word, if any, chooses)
    assert one("13/6/29 92.050")["isin"] == "TRT130629T14" and one("13/6/29 tlref 98.650")["isin"] == "TRT130629T30"
    # in a switch each bond takes the kind said next to it
    q = one("jan30 tlref vs jul30 -10/-5")
    assert [(leg["isin"], leg["bond_kind"]) for leg in q["legs"]] == [("TRT020130T19", "float"), ("TRT100730T13", "fixed")]
    q = one("mar28 vs jun29 cpi switch 210/220")
    assert [leg["isin"] for leg in q["legs"]] == ["TRT150328T24", "TRT130629T14"] and "nobond" not in q["flags"]
    q = one("jan30 700 vs jul30 750 switch trading")
    assert [leg["isin"] for leg in q["legs"]] == ["TRT020130T19", "TRT100730T13"] and "notfixed" in q["flags"] and q["unit"] == "px"


def test_zc_is_a_zero_coupon_one_quoted_on_its_yield():
    """"zc" (or "bono", "kuponsuz"): a bill or a zero coupon bond, quoted on its yield - never a coupon bond instead.
    In yield the bid is the higher number: "31.45/40" is 31.45 / 31.40, not crossed."""
    assert bd.candidates(date="2028-03-15", kind="zc") == [] and bd.candidates(month="2027-02", kind="zc")[0]["isin"] == "TRB100227T13"
    for text, isin, settle in (("feb27 zc 31.40", "TRB100227T13", None), ("feb27zc 31.40", "TRB100227T13", None),
                               ("feb27zc.t1 31.40", "TRB100227T13", "T1"), ("jan27 zc 31.45", "TRT060127T10", None),
                               ("6/1/27 kuponsuz 31.45", "TRT060127T10", None), ("10/2/27 zc 31.40", "TRB100227T13", None)):
        q = one(text)
        assert (q["isin"], q["unit"], q.get("settle")) == (isin, "yld", settle), text
    # no zero coupon one then: not the coupon bond of the day, and still a yield
    q = one("15/3/28 zc 36.50")
    assert (q.get("isin"), q["label"], q["unit"], q["price"]) == (None, "15.03.28 ZC", "yld", 36.5) and "nobond" in q["flags"]
    q = one("mar28 zc 36.50")
    assert (q.get("isin"), q["label"], q["unit"]) == (None, "Mar28 ZC", "yld") and "nobond" in q["flags"]
    # bid and ask in yield: the bid is the higher one; a short ask completes below it, a crossing one into the figure below
    for text, bid, ask in (("feb27 zc 31.45/40", 31.45, 31.40), ("feb27 zc 45/40", 34.45, 34.40), ("feb27 zc 05/95", 35.05, 34.95),
                           ("feb27 zc 34.45/40", 34.45, 34.40), ("feb27 zc 34.90 bid, 80 offer", 34.90, 34.80)):
        q = one(text)
        assert (q["bid"], q["ask"]) == (pytest.approx(bid), pytest.approx(ask)) and "crossed" not in q["flags"], text
    assert "crossed" in one("feb27 zc 31.40/31.45")["flags"] and "crossed" not in one("15/3/28 100.550/100.575")["flags"]


def test_the_other_side_after_a_comma_is_the_same_bond():
    """"15/3/28 550 bid, 575 offer": the offer is the same bond's - completed from its screen, or from the side said in
    full just before it when the bond has no screen."""
    q = one("15/3/28 550 bid, 575 offer")
    assert (q["isin"], q["bid"], q["ask"]) == ("TRT150328T24", 100.55, 100.575)
    q = one("jan30 tlref 98.650 bid, 750 offer")
    assert (q["bid"], q["ask"]) == (98.65, 98.75) and "crossed" not in q["flags"]
    q = one("18m ois 35.03 bid, 23 offer", lambda r: None)                           # no curve: the side said before
    assert (q["bid"], q["ask"]) == (35.03, 35.23)

def test_trades_refs_and_interest_on_a_bond_in_english_and_turkish():
    assert (one("15/3/28 550 traded")["event"], one("15/3/28 550 traded")["price"]) == ("trade", 100.55)
    q = one("16/4/31 100 given")
    assert (q["event"], q["side"], q["price"]) == ("trade", "bid", 94.1)
    q = one("Dec28 tlref 100.050 trading")
    assert (q["event"], q["price"], q["isin"]) == ("trade", 100.05, "TRT061228T16")
    q = one("15/3/28 550 bidim refledi")
    assert (q["event"], q["side"]) == ("ref", "bid")
    assert (one("15/3/28 any int?")["event"], one("15/3/28 any int?")["note"]) == ("interest", "")
    assert (one("15/3/28 550 bidim")["bid"], one("15/3/28 575 offerim")["ask"]) == (100.55, 100.575)
    q = one("16/4/31 100 aldi")
    assert (q["event"], q["side"], q["price"]) == ("trade", "ask", 94.1)
    assert one("feb27 99.450 offer")["ask"] == 99.45 and one("feb27 99.450 offer")["isin"] == "TRT100227T13"
    # a switch of two bonds is a switch (below); of three, the line stays as it was written
    assert bc.parse_quote("mar28 vs jun29 vs jan30 10/20") is None


def test_switches_of_two_bonds():
    # written leg by leg: each bond with its level (completed as its own quote would be), the line's words the event
    q = bc.parse_quote("Sw int 9/1/30 775 offer vs 3/7/30 775 bid")
    assert (q["product"], q["kind"], q["event"], q["unit"], q["by_legs"]) == ("DIBS", "switch", "interest", "px", True)
    assert [(leg["isin"], leg["level"], leg["side"]) for leg in q["legs"]] == [("TRT090130T12", 99.775, "ask"), ("TRT030730T12", 99.775, "bid")]
    assert q["label"] == "09.01.30 TLREF / 03.07.30 TLREF" and q["key"] == "DIBS:switch:TRT090130T12/TRT030730T12" and q["price"] is None
    q = bc.parse_quote("jul30 750 vs mar28 200 switch trading", lambda r: {"TRT150328T24": 100.1, "TRT100730T13": 93.5}.get(r.get("isin")))
    assert q["event"] == "trade" and q["unit"] == "bp" and [leg["label"] for leg in q["legs"]] == ["15.03.28", "10.07.30"]   # shorter first
    assert [leg["level"] for leg in q["legs"]] == [100.2, 93.75]
    # quoted as the spread of the two yields: the longer bond's − the shorter one's, in bp, in any order and joined any way
    for text in ("mar28 vs jul30 switch -45/-40", "jul30 v mar28 -45/-40", "mar28/jul30 sw -45/-40", "15/3/28-10/7/30 -45/-40",
                 "mar28 into jul30 -45 bid -40 offer"):
        q = bc.parse_quote(text)
        assert (q["kind"], q["unit"], q["bid"], q["ask"], q["label"], q["note"]) == ("switch", "bp", -45.0, -40.0, "15.03.28 / 10.07.30", ""), text
        assert [leg["isin"] for leg in q["legs"]] == ["TRT150328T24", "TRT100730T13"] and "by_legs" not in q
    q = bc.parse_quote("mar28/jul30 trd -42")
    assert (q["event"], q["price"]) == ("trade", -42.0)
    # the other side said after a comma, and the switch on the board
    rows = bc.parse_chat("10:00:00 mar28/jul30 -45 bid, -40 offer\n10:05:00 mar28 vs jul30 -41 bid", lambda q: None, TODAY)
    assert [(q["bid"], q["ask"]) for q in rows] == [(-45.0, -40.0), (-41.0, None)]
    row = bc.board(rows)[0]
    assert (row["kind"], row["bid"], row["ask"], [leg["isin"] for leg in row["legs"]]) == ("switch", -41.0, -40.0, ["TRT150328T24", "TRT100730T13"])


def test_a_bond_nobody_priced_takes_its_figure_from_the_one_next_to_it():
    # the floater of January 2028 has no screen price: the October 2027 floater of the same chat gives the figure
    rows = bc.parse_chat("13:36:12 13/10/27 tlref  100.650/.800\n17:29:21 jan28 tlref .725 trading", lambda q: None, TODAY)
    q = rows[-1]
    assert (q["isin"], q["price"], q["ref_from"]) == ("TRT190128T14", 100.725, "13.10.27 TLREF") and "near" in q["flags"]
    # ... or one the service knows (the day's chat, the screen); the nearest maturity of the same kind wins
    near = [{"isin": "TRT090130T12", "kind": "float", "months": 361.0, "unit": "px", "value": 98.25, "label": "09.01.30 TLREF"},
            {"isin": "TRT010328T12", "kind": "float", "months": 339.0, "unit": "px", "value": 98.40, "label": "01.03.28 TLREF"},
            {"isin": "TRT150328T24", "kind": "fixed", "months": 337.0, "unit": "px", "value": 100.11, "label": "15.03.28"}]
    q = bc.parse_chat("jan28 tlref .725 trading", lambda q: None, TODAY, nearby=lambda q: near)[-1]
    assert q["price"] == 98.725 and q["ref_from"] == "01.03.28 TLREF"                # not the fixed coupon bond, though nearer
    q = bc.parse_chat("jan28 tlref .725 trading", lambda q: None, TODAY, nearby=lambda q: near[:1])[-1]
    assert q["price"] == 99.725 and "par" in q["flags"]                               # two years away: too far to tell
    # nobody near: a floater trades about par (flagged); a fixed coupon bond stays as typed
    q = bc.parse_chat("jan28 tlref .725 trading", lambda q: None, TODAY)[-1]
    assert q["price"] == 99.725 and "par" in q["flags"]
    q = bc.parse_chat("8/3/28 550 bid", lambda q: None, TODAY)[-1]
    assert q["bid"] == 0.55 and "no-ref" in q["flags"]
    assert bc.near_level({"bond_kind": "fixed", "months": [339.0], "unit": "px"}, near) is None
    # a price written in full needs nothing: no flag
    q = bc.parse_chat("13/10/27 tlref 100.650/100.800", lambda q: None, TODAY)[-1]
    assert (q["bid"], q["ask"], q["flags"]) == (100.65, 100.8, [])


def test_the_lines_under_a_heading_are_its_message():
    msgs = bc.split_messages(CHAT, TODAY)
    auction = [m for m in msgs if m.get("head") == "Auction prices"]
    assert [m["text"].split()[0] for m in auction] == ["06/01/2027.t1", "10/02/2027zc.t1", "10/02/2027.t1", "15/03/2028.t1", "16/04/2031.t1"]
    assert {m["time"] for m in auction} == {"09:14:59"} and {m["sender"] for m in auction} == {"AKTAN ACIKGOZ"}
    rows = bc.parse_chat(CHAT, ref, TODAY)
    levels = [q for q in rows if q.get("note") == "Auction prices"]
    assert [(q["label"], q["unit"], q["price"]) for q in levels] == [
        ("06.01.27 Kuponsuz", "yld", 31.45), ("10.02.27 Bono", "yld", 31.4), ("10.02.27", "px", 99.445), ("15.03.28", "px", 100.65),
        ("16.04.31", "px", 93.95)]
    # the auction's level is what the later "550" is completed from (same chat), not the screen
    later = next(q for q in rows if q.get("time") == "10:10:59")
    assert later["bid"] == 100.55
    # an empty line or another sender ends the message: the line under it has no time of its own
    m = bc.split_messages("09:00:00 15/3/28 550/575\n\n16/4/31 100/200\n09:01:00 a\nEVREN: b", TODAY)
    assert [(x["time"], x["sender"]) for x in m] == [("09:00:00", ""), (None, ""), ("09:01:00", ""), (None, "EVREN")]


# ---------------------------------------------------------------------------------------------- the service
def test_the_desks_bond_chat_is_read_against_the_screen(svc):
    u = svc.login("Tahvil Chat")["user"]
    res = svc.broker_parse(u, CHAT, TODAY.isoformat())
    bonds = [q for q in res["rows"] if q.get("product") == "DIBS"]
    texts = [q["raw"] for q in res["rows"] if not q.get("ok")]
    assert texts == ["Gunaydin...", "Auction prices"]
    # the switch of two floaters: each leg completed from its own screen price, the switch the difference of the two
    sw = next(q for q in bonds if q.get("kind") == "switch")
    assert (sw["event"], sw["unit"], [(leg["isin"], leg["side"]) for leg in sw["legs"]]) == (
        "interest", "px", [("TRT090130T12", "ask"), ("TRT030730T12", "bid")])
    assert sw["price"] == pytest.approx(sw["legs"][1]["level"] - sw["legs"][0]["level"]) and sw["model"] is not None
    by = {(q["time"], q["label"]): q for q in bonds}
    q = by[("10:25:28", "15.03.28")]
    assert (q["bid"], q["ask"], q["model"]) == (100.55, 100.575, pytest.approx(100.1125))
    # the yield a price stands for: the screen's yield moved by the price difference over the duration
    imp = q["implied"]
    assert imp["kind"] == "bond" and imp["bid"] > imp["ask"] and imp["screen"] == pytest.approx(100.1125)
    assert imp["bid"] == pytest.approx(imp["screen_yield"] - (100.55 - imp["screen"]) / (imp["screen"] * imp["mod_dur"]) * 100.0)
    # the screen settles a month of two bonds when the level is near one of them and the other cannot be it
    assert "bond?" not in by[("14:05:26", "15.03.28")]["flags"] and "bond?" not in by[("10:22:33", "10.02.27")]["flags"]
    assert "bond?" in by[("09:51:39", "09.01.30 TLREF")]["flags"]                    # two floaters of January 2030 near par
    # completed from the screen: the floater of September 2030, the 5.5.27 with its value date
    assert (by[("11:49:56", "11.09.30 TLREF")]["bid"], by[("11:49:56", "11.09.30 TLREF")]["settle"]) == (97.675, "T0")
    assert (by[("13:12:50", "05.05.27")]["bid"], by[("13:12:50", "05.05.27")]["ask"]) == (103.0, 103.15)
    # the floater nobody priced: from the October 2027 floater of the same chat
    q = by[("17:29:21", "19.01.28 TLREF")]
    assert (q["event"], q["price"], q["ref_from"]) == ("trade", 100.725, "13.10.27 TLREF")
    # "mar28 given": a trade at the bid that stood
    q = by[("14:13:22", "15.03.28")]
    assert (q["event"], q["side"], q["price"]) == ("trade", "bid", 100.4) and "standing" in q["flags"]


AGE = r"(şimdi|\d+ dk|\d+ sa \d+ dk)"


def test_the_dibs_rv_table_shows_the_days_broker_chat(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Tahvil Masa")["user"]
        s.broker_settings(u, 1440)                            # the morning's chat is fresh whenever this runs (staleness: below)
        s.broker_add(u, CHAT, s.today_iso(), source="ICAP")
        board = {r["isin"]: r for r in s.broker(u)["board"] if r.get("isin")}
        assert (board["TRT150328T24"]["bid"], board["TRT150328T24"]["ask"], board["TRT150328T24"]["last"]) == (100.4, 100.475, 100.4)
        # the board's best: "mar28 given" hit the 100.400 bid - it no longer stands
        assert (board["TRT150328T24"]["best_bid"], board["TRT150328T24"]["best_ask"], board["TRT150328T24"]["best_ask_by"]) == (None, 100.475, "ICAP")
        panel = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")
        data = panel["data"]
        assert data["c"][-7:] == ["Broker bid", "Broker ask", "Son işlem", "Kimde · yaş", "Broker getiri %", "Broker − ekran (bp)", "Kart"]
        assert data["added"] == 7 and panel["action"] == "add-isin" and panel["add"]["ref"] == "DİBS RV!A5:A54" and panel["card"] == "bond"
        rows = {row[0]["t"]: [c.get("t") for c in row[-7:-1]] for row, r in zip(data["rows"], data["r"]) if 5 <= r <= 54 and row[0].get("t")}
        assert all(row[-1]["t"] == "▸" and row[-1]["tip"] == "Kâğıt kartı: " + row[0]["t"]
                   for row, r in zip(data["rows"], data["r"]) if 5 <= r <= 54 and row[0].get("t"))
        assert rows["TRT150328T24"][:3] == ["", "100,475", "100,400"] and re.fullmatch("ICAP · " + AGE, rows["TRT150328T24"][3])
        assert rows["TRT160431T35"][:3] == ["", "94,200", "94,100"]               # "16/4/31 100 given": the bid went with the trade
        assert rows["TRB100227T13"][2:4] == ["31,40", "09:14"]                    # an auction level, not a trade: no quote, its time
        gap = next(c for row, r in zip(data["rows"], data["r"]) if row[0].get("t") == "TRT150328T24" for c in row[-2:-1])
        imp = board["TRT150328T24"]["implied"]
        assert gap["v"] == pytest.approx((imp["best_ask"] - imp["screen_yield"]) * 100.0)          # of the fresh offer alone
        assert all(not any(v) for k, v in rows.items() if k not in {b for b in board})   # bonds nobody spoke of: empty
        # the export keeps to the sheet's own columns
        hdr = auth(s, u)
        with TestClient(create_app(s)) as client:
            assert client.get("/api/view/dibs", headers=hdr).status_code == 200
    finally:
        s.stop()


def test_bonds_are_added_to_a_pages_list_by_isin(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Liste Ekleyen")["user"]
        cat = s.bond_catalog(u)
        assert len(cat["bonds"]) == 77 and cat["lists"]["dibs"] >= 15 and cat["kinds"]["float"] == "TLREF"
        listed = {b["isin"] for b in cat["bonds"] if "dibs" in b["lists"]}
        new = next(b["isin"] for b in cat["bonds"] if b["kind"] == "float" and b["isin"] not in listed)
        before = s._list_values(u, "tto", "DİBS RV!A5:A54")
        res = s.list_add(u, "tto", "DİBS RV!A5:A54", [new, "trt150328t24", new])
        # below the list's last bond: the empty rows the desk keeps between its groups stay empty
        last = max(k for k, v in enumerate(before) if v)
        assert res["added"] == [new] and res["skipped"] == ["TRT150328T24"] and res["cells"] == ["DİBS RV!A%d" % (5 + last + 1)]
        assert before.index("") < last
        assert res["free"] == before.count("") - 1
        # the DİBS RV list is the desk's: everyone sees the bond added
        other = s.login("Öbür Kullanıcı")["user"]
        assert new in s._list_values(other, "tto", "DİBS RV!A5:A54")
        assert new in {b["isin"] for b in s.bond_catalog(other)["bonds"] if "dibs" in b["lists"]}
        for bad in (["TRT150328T25"], ["XS123"]):
            with pytest.raises(ServiceError):
                s.list_add(u, "tto", "DİBS RV!A5:A54", bad)
        with pytest.raises(ServiceError):
            s.list_add(u, "tto", "DİBS RV!C5:C10", ["TRT150328T24"])              # not a list of the page
        with pytest.raises(ServiceError):
            s.list_add(u, "tto", "DİBS RV!A5:A54", [b["isin"] for b in cat["bonds"]])   # more than there is room for
        # the Bulk Bond list is each user's own; a row below the workbook's four asks nothing while it is empty
        model = s.books["tto"].model
        assert ex.formula_of(model, "Bulk Bond", "B7").startswith('IF(TRIM($A7&"")="","",') and cell(s, "Bulk Bond!B7") == ""
        res = s.list_add(u, "tto", "Bulk Bond!A3:A52", "TRT150328T24 TRT160431T35".split())
        assert res["cells"] == ["Bulk Bond!A6", "Bulk Bond!A7"]
        assert cell(s, "Bulk Bond!A7", user=user_key(u)) == "TRT160431T35" and cell(s, "Bulk Bond!A7") is None
        # over HTTP
        hdr = auth(s, u)
        with TestClient(create_app(s)) as client:
            got = client.get("/api/bonds/catalog", headers=hdr).json()
            assert len(got["bonds"]) == 77 and new in {b["isin"] for b in got["bonds"] if "dibs" in b["lists"]}
            res = client.post("/api/list/add", json={"book": "tto", "list": "Bulk Bond!A3:A52", "values": ["TRT050527T33"]}, headers=hdr)
            assert res.status_code == 200 and res.json()["cells"] == ["Bulk Bond!A8"]
            assert client.post("/api/list/add", json={"book": "tto", "list": "Bulk Bond!A3:A52", "values": ["NOPE"]},
                               headers=hdr).status_code == 400
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------- tables that grow
def test_the_bulk_forward_table_has_a_hundred_rows_of_the_sheets_own_formulas(svc):
    # every value date and manual TRY rate starts empty (the file's dates of the day it was saved are nobody's today),
    # and an empty row prices nothing
    for k in range(ex.BULK_ROWS):
        for col in "BL":
            assert cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST + k)) is None, (col, k)
    assert all(cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST)) in (None, "") for col in "NPQ")
    # the Forward sheet's own table (its first rows) and the same value dates typed here - in its first row and in a
    # row the sheet does not have - give the same prices: the sheet's formulas, row by row
    u = svc.login("Toplu Forward")["user"]
    for k, r in ((0, ex.BULK_FIRST), (3, ex.BULK_FIRST + 60)):
        typed = [{"ref": "%s!%s%d" % (ex.BULK_SHEET, col, r), "value": cell(svc, "Forward!%s%d" % (col, 144 + k))}
                 for col in "BL" if cell(svc, "Forward!%s%d" % (col, 144 + k)) not in (None, "")]
        assert typed and not svc.set_inputs(u, "tto", typed)["errors"]
        for col in ex.BULK_COLS:
            a, b = cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, r), user=user_key(u)), cell(svc, "Forward!%s%d" % (col, 144 + k))
            assert a == b or (type(a) is float and type(b) is float and a == pytest.approx(b, abs=1e-9)), (col, k, a, b)
    # the page shows the rows in use and one more; the panel says how
    view = svc.view(u, "forward")
    bk = next(p for p in view["panels"] if p["id"] == "BK1")
    assert bk["grow"] == {"key": "B", "first": ex.BULK_FIRST, "extra": 1, "last": ex.BULK_FIRST + ex.BULK_ROWS - 1}
    assert len(bk["data"]["rows"]) >= ex.BULK_ROWS
    bulk = next(p for p in svc.view(u, "bulk")["panels"] if p["id"] == "B1")
    assert bulk["grow"]["last"] == ex.BULK_BOND_LAST and bulk["action"] == "add-isin" and bulk["add"]["catalog"] is False


# ---------------------------------------------------------------------------------------------- DİBS Canlı
def test_the_live_table_reads_each_value_date_and_the_repo_it_implies(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Canlı Masa")["user"]
        L = ex._live_cols()
        assert [g["cap"] for g in L["groups"]] == ["T0", "T1", "T2"] and [g["default"] for g in L["groups"]] == ["ISL0", "ISL1", "ISLN"]
        # the value dates: today, the next business day and the one after (the workbook's holidays)
        assert [cell(s, "EK_DIBS!%s" % g["date"]) for g in L["groups"]] == [46329.0, 46330.0, 46331.0]
        # the bonds of the DİBS RV list, row for row, with the security Bloomberg is asked for on each value date
        assert [cell(s, "EK_DIBS!%s8" % c) for c in "ABCD"] == ["TRT150328T24", "15.03.28", "S", 46827.0]
        assert [cell(s, "EK_DIBS!%s8" % c) for c in L["sec"] + [L["sec_extra"]]] == [
            "TRT150328T24 @ISL0 ISIN", "TRT150328T24 @ISL1 ISIN", "TRT150328T24 @ISLN ISIN", "TRT150328T24 @BGN ISIN"]
        assert cell(s, "EK_DIBS!B5") == "10.02.27 Bono" and cell(s, "EK_DIBS!B26") == "09.01.30 TLREF"
        # the value date the DİBS RV row is priced on comes from that sheet (offline: the file's values) ...
        t1 = L["groups"][1]
        assert [cell(s, "EK_DIBS!%s8" % t1[f]) for f in ("bid", "ask", "last", "when")] == [
            cell(s, "DİBS RV!K8"), cell(s, "DİBS RV!L8"), cell(s, "DİBS RV!AS8"), cell(s, "DİBS RV!I8")] == [100.1, 100.125, 100.2, 46329.0]
        t0 = L["groups"][0]
        assert cell(s, "EK_DIBS!%s5" % t0["bid"]) == cell(s, "DİBS RV!K5") == 92.22          # a bill: priced on T0
        # ... the others ask Bloomberg, which the recorded file cannot answer: empty, not an error
        assert [cell(s, "EK_DIBS!%s8" % t0[f]) for f in ("bid", "ask", "last", "when", "vol")] == ["", "", "", "", ""]
        assert cell(s, "EK_DIBS!%s8" % L["raw"][0]["bid"]) is not None
        # the repo two value dates imply: dirty prices (clean + the accrued interest of each value date), ACT/365
        raw0 = L["raw"][0]
        res = s.set_inputs(u, "tto", [{"ref": "EK_DIBS!%s8" % raw0["bid"], "value": 100.0}, {"ref": "EK_DIBS!%s8" % raw0["ask"], "value": 100.03},
                                      {"ref": "EK_DIBS!%s8" % raw0["acc"], "value": 4.86},
                                      {"ref": "EK_DIBS!%s8" % raw0["date"], "value": 46315.0}], allow_adhoc=True)
        assert not res["errors"]
        uk = user_key(u)
        dirty0, dirty1 = 100.015 + 4.86, cell(s, "DİBS RV!M8") + cell(s, "DİBS RV!CW8")
        w, x, y = ex.LIVE_REPO
        # ... only from prices of the same day: a T0 price of two weeks before against T1's implies nothing
        assert cell(s, "EK_DIBS!%s8" % t0["when"], user=uk) == 46315.0 and cell(s, "EK_DIBS!%s8" % w, user=uk) == ""
        card = s.bond_card(u, "TRT150328T24")
        assert card["repo_note"] == ("T0 ve T1 fiyatları aynı güne ait değil (T0 son işlem: 20.10.2026 · T1 son işlem: 03.11.2026): "
                                     "repo hesaplanmadı") and not card["repo"][0]["t"]
        summary = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L0")["data"]["rows"]
        heads = [c["t"] for c in summary[0]]
        line = next(row for row in summary if any(c.get("t") == "TRT150328T24" for c in row))
        repo_cell = line[heads.index("T0→T1 repo %")]
        assert repo_cell["t"] == "–" and repo_cell["tip"] == card["repo_note"]
        s.set_inputs(u, "tto", [{"ref": "EK_DIBS!%s8" % raw0["date"], "value": 46329.0}], allow_adhoc=True)     # the same day
        assert s.bond_card(u, "TRT150328T24")["repo_note"] == ""
        assert cell(s, "EK_DIBS!%s8" % w, user=uk) == pytest.approx((dirty1 / dirty0 - 1) * 365 * 100)
        assert cell(s, "EK_DIBS!%s8" % y, user=uk) == pytest.approx((cell(s, "EK_DIBS!%s8" % w, user=uk) / 100 - cell(s, "OIS_MAIN!J2")) * 1e4)
        assert cell(s, "EK_DIBS!%s8" % x, user=uk) == "" and cell(s, "EK_DIBS!%s8" % w) == ""     # T2 not priced; others unchanged
        # no repo for a CPI linker (its TL price moves with each value date's index ratio)
        cpi_row = next(r for r in range(5, 55) if cell(s, "DİBS RV!D%d" % r) == "E") if any(
            cell(s, "DİBS RV!D%d" % r) == "E" for r in range(5, 55)) else None
        if cpi_row:
            assert cell(s, "EK_DIBS!%s%d" % (w, cpi_row)) == ""
        # a source is the desk's to choose: T1 on ISL0 asks for "@ISL0" (offline the bill keeps its file values)
        s.set_inputs(u, "tto", [{"ref": "EK_DIBS!K2", "value": "isl0"}])
        assert cell(s, "EK_DIBS!%s8" % L["sec"][1]) == "TRT150328T24 @ISL0 ISIN" and cell(s, "EK_DIBS!K8") == ""
        assert cell(s, "EK_DIBS!K5") == 92.22
        s.set_inputs(u, "tto", [{"ref": "EK_DIBS!K2", "value": None}])               # emptied: the default source
        assert cell(s, "EK_DIBS!K2") is None and cell(s, "EK_DIBS!%s8" % L["sec"][1]) == "TRT150328T24 @ISL1 ISIN"
        assert cell(s, "EK_DIBS!K8") == 100.1
        s.reset_inputs(u, "tto", ["EK_DIBS!K2"], shared=True)
        assert cell(s, "EK_DIBS!K2") == "ISL1"
        # the page: the table with a card per bond, the day's tape, the helper columns behind
        view = s.view(u, "dibslive")
        assert [p["id"] for p in view["panels"]] == ["L0", "L1", "L3"] and view["title"] == "DİBS Trading"
        main = view["panels"][1]
        assert main["title"] == "Valörler · T0 / T1 / T2"
        assert main["card"] == "bond" and main["add"]["ref"] == "DİBS RV!A5:A54" and main["add"]["name"] == "dibs"
        assert main["data"]["c"][-5:] == ["Broker bid", "Broker ask", "Son işlem", "Kimde · yaş", "Kart"]
        assert [p["id"] for p in s.view(u, "dibslive", show_hidden=True)["panels"]] == ["L0", "L1", "L3", "L2"]
    finally:
        s.stop()


class _Prices(object):
    """A provider's answers that the test moves."""

    def __init__(self, values):
        self.values = values

    def __call__(self, key):
        return self.values.get((key[1], key[2]), "#N/A")


def test_a_trade_the_dashboard_sees_shows_its_time(tmp_path, monkeypatch):
    s = make_service(tmp_path)
    try:
        u = s.login("Canlı İşlem")["user"]
        sec = "TRT150328T24 @ISL1 ISIN"
        prices = _Prices({(sec, "LAST_PRICE"): 100.2, (sec, "VOLUME"): 5e6})
        monkeypatch.setattr(s.provider, "get_bdp", prices, raising=False)
        keys = [("BDP", sec, "LAST_PRICE", ()), ("BDP", sec, "VOLUME", ())]
        s._note_trades(keys)
        assert s.trades_seen(sec) is None                         # the first answer of the day is no trade
        prices.values[(sec, "VOLUME")] = 7e6                      # a trade at the same price: the volume grew
        s._note_trades(keys[1:])
        seen = s.trades_seen(sec)
        assert seen["by"] == "VOLUME" and seen["volume"] == 2e6 and len(seen["time"]) == 8
        prices.values[(sec, "LAST_PRICE")] = 100.25
        s._note_trades(keys[:1])
        assert s.trades_seen(sec)["by"] == "LAST_PRICE" and s.trades_seen(sec)["price"] == 100.25
        s._trades_seen[sec]["time"] = "10:41:07"
        prices.values[(sec, "VOLUME")] = 1e6                      # a smaller volume (a new count) is no trade
        s._note_trades(keys[1:])
        assert s.trades_seen(sec)["time"] == "10:41:07"
        s._note_trades([("BDP", sec, "PX_BID", ()), ("BDH", sec, "PX_LAST", "", "", ())])   # other fields: nothing
        assert s.trades_seen("TRT150328T24 @ISL0 ISIN") is None
        s.bump()
        # the page: the T1 last trade at the moment it was seen, Bloomberg's day in the tip; the tape has it
        summary, main, tape = s.view(u, "dibslive")["panels"][:3]
        line = next(r for r in summary["data"]["rows"] if r[2].get("t") == "TRT150328T24")
        assert line[9]["t"] == "bugün 10:41:07" and line[9]["cls"] == "fresh"                # the summary says it too
        d = main["data"]
        j = d["c"].index(ex._live_cols()["groups"][1]["when"])
        row = next(r for r, n in zip(d["rows"], d["r"]) if n == 8)
        assert row[j]["t"] == "bugün 10:41:07" and row[j]["cls"] == "fresh" and "100,250" in row[j]["tip"] and "03.11.2026" in row[j]["tip"]
        other = next(r for r, n in zip(d["rows"], d["r"]) if n == 13)
        assert other[j]["t"] == "03.11.2026"                      # no trade seen: Bloomberg's day of the last one
        lines = [[c.get("t") for c in r] for r in tape["data"]["rows"]]
        assert lines[0][:3] == ["Saat", "Kâğıt", "ISIN"]
        assert ["10:41:07", "15.03.28", "TRT150328T24", "100,250", "", "", "T1", "Bloomberg · ISL1", "son fiyat değişti", "▸"] in lines
        # a new day starts afresh
        s._trades_day = "2000-01-01"
        assert s.trades_seen(sec) is None
    finally:
        s.stop()


def test_the_bond_card_has_everything_on_one_bond(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Kâğıt Kartı")["user"]
        s.broker_settings(u, 1440)                            # the morning's chat is fresh whenever this runs (staleness: below)
        s.broker_add(u, CHAT, s.today_iso(), source="ICAP")
        card = s.bond_card(u, " trt150328t24 ")
        assert (card["isin"], card["label"], card["kind_text"], card["coupon"], card["maturity"], card["known"]) == (
            "TRT150328T24", "15.03.28", "Sabit", 36.8, "2028-03-15", True)
        assert card["days"] == (dt.date(2028, 3, 15) - dt.date.fromisoformat(s.today_iso())).days
        rv = {x["name"]: x["t"] for x in card["rv"]}
        assert rv["Sinyal"] in ("UCUZ", "PAHALI", "–") and rv["Kupon"] == "36,80%" and "BIST bileşik getiri" in rv and "DV01 TL / 1mn (T: spread)" in rv
        assert [(g["cap"], g["src"], g["bid"], g["ask"]) for g in card["live"]] == [
            ("T0", "ISL0", "", ""), ("T1", "ISL1", "100,100", "100,125"), ("T2", "ISLN", "", "")]
        assert [x["name"] for x in card["repo"]] == ["T0→T1 repo %", "T1→T2 repo %", "T0→T1 − TLREF (bp)"] and card["extra"]["src"] == "BGN"
        # the board by its rules: the bid hit ("mar28 given") is gone, the offer stands - with its broker and age
        board = card["board"]
        assert (board["bid"], board["ask"], board["last"]) == ("", "100,475", "100,400") and re.fullmatch("ICAP · " + AGE, board["who"])
        assert board["stale"] == {"bid": False, "ask": False, "last": False, "who": False} and "En iyi offer: ICAP · 14:05:26" in board["tips"]["ask"]
        assert set(board["implied"]) == {"ask", "screen_yield", "last"} and board["implied"]["ask"] < board["implied"]["screen_yield"] + 5
        said = [(q["time"], q["event"]) for q in card["chat"]]
        assert said[0] == ("09:14:59", "level") and ("13:21:38", "trade") in said and all(q["who"].startswith("ICAP") for q in card["chat"])
        # each quote line: still standing (its offer: "geçerli"), or gone - said again later, withdrawn, traded away
        state = {q["time"]: (q["state"], q["age"]) for q in card["chat"]}
        assert state["14:05:26"][0] == "fresh" and re.fullmatch(AGE, state["14:05:26"][1])
        assert state["10:25:28"] == ("gone", "") and state["10:10:59"] == ("gone", "") and state["13:21:38"] == (None, "")
        assert [(x["time"], x["price"]) for x in card["tape"]] == [("14:13:22", 100.4), ("13:21:38", 100.55)]
        # a bond off the list: what the catalog knows, and nothing else
        off = s.bond_card(u, "TRT280432T14")
        assert (off["label"], off["kind_text"], off["rv"], off["live"], off["board"], off["chat"]) == ("28.04.32", "Sabit", [], [], None, [])
        assert s.bond_card(u, "XS2010030836")["known"] is False
        with pytest.raises(ServiceError):
            s.bond_card(u, " ")
        hdr = auth(s, u)
        with TestClient(create_app(s)) as client:
            got = client.get("/api/bond/TRT160431T35", headers=hdr).json()
            assert got["label"] == "16.04.31" and got["board"]["last"] == "94,100"
    finally:
        s.stop()


def test_the_bond_pages_show_the_broker_board_by_its_rules(tmp_path):
    """DİBS RV, DİBS Trading (the summary and the value dates), Tüm Kâğıtlar and the bond card show the Broker Chat
    board by its rules: the brokers' best fresh bid and offer with their broker and age; a stale quote never looks
    current - greyed, "bayat" with its broker and age - and the broker's yield and distance from the screen are of
    fresh quotes only; a quote withdrawn, traded away or said before a reset is gone."""
    s = make_service(tmp_path)
    try:
        u = s.login("Bayat Kâğıt")["user"]
        today = s.today_iso()
        early = dt.datetime.now() - dt.timedelta(minutes=30)
        if early.date().isoformat() != today:
            pytest.skip("just after midnight there was no half an hour ago today")
        at = early.strftime("%H:%M:%S")
        # 16/4/31: one quote, half an hour old - stale by the desk's 10 minutes; 15/3/28: a fresh one and a better stale one
        s.broker_add(u, "%s 16/4/31 94.000/94.200" % at, today, "BGC")
        s.broker_add(u, "%s 15/3/28 100.520/100.560" % at, today, "TULLETT")
        s.broker_add(u, "15/3/28 100.500/100.600", today, "ICAP")
        assert s.broker(u)["stale_minutes"] == 10

        def rv(isin):
            """DİBS RV's broker columns of a bond: bid, ask, last trade, whose and how old, yield, broker − screen."""
            data = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")["data"]
            return next(r for r in data["rows"] if r[0].get("t") == isin)[-7:-1]

        def board_cells(view, panel, isin):
            """The four board columns of a bond on another page."""
            data = next(p for p in s.view(u, view)["panels"] if p["id"] == panel)["data"]
            row = next(r for r in data["rows"] if any(c.get("t") == isin for c in r[:3]))
            first = data["c"].index("Broker bid") if "Broker bid" in data["c"] else len(row) - 5
            return row[first:first + 4]

        old = rv("TRT160431T35")
        assert (old[0]["t"], old[1]["t"]) == ("94,000", "94,200") and all("stale" in old[k]["cls"] for k in (0, 1))
        assert re.fullmatch(r"bayat · BGC · 3\d dk", old[3]["t"]) and "stale" in old[3]["cls"]
        assert old[0]["tip"].startswith("Bayat, en iyi sayılmaz: BGC 94,000")
        assert (old[4]["t"], old[5]["t"]) == ("bayat", "")                       # no yield, no distance from the screen of a stale quote
        new = rv("TRT150328T24")
        assert (new[0]["t"], new[1]["t"]) == ("100,500", "100,600") and not any("stale" in (new[k].get("cls") or "") for k in (0, 1, 3))
        assert re.fullmatch(r"ICAP · (şimdi|\d dk)", new[3]["t"])               # TULLETT's better quote is stale: not the best
        imp = {r["isin"]: r for r in s.broker(u)["board"] if r.get("isin")}["TRT150328T24"]["implied"]
        assert new[5]["v"] == pytest.approx(((imp["best_bid"] + imp["best_ask"]) / 2 - imp["screen_yield"]) * 100.0)
        # the same on DİBS Trading (the summary, the value dates) and on Tüm Kâğıtlar
        for view, panel in (("dibslive", "L0"), ("dibslive", "L1"), ("kagitlar", "U1")):
            got = board_cells(view, panel, "TRT160431T35")
            assert [c.get("t") for c in got[:2]] == ["94,000", "94,200"] and "stale" in got[0]["cls"], (view, panel, got)
            assert re.fullmatch(r"bayat · BGC · 3\d dk", got[3]["t"]), (view, panel, got)
            assert [c.get("t") for c in board_cells(view, panel, "TRT150328T24")[:2]] == ["100,500", "100,600"], (view, panel)
        # the card: the board, and each quote line - standing and fresh, standing but stale, gone
        card = s.bond_card(u, "TRT160431T35")
        assert (card["board"]["bid"], card["board"]["stale"]["bid"], card["board"]["implied"]) == ("94,000", True, {})
        assert [(q["state"], bool(re.fullmatch(r"3\d dk", q["age"]))) for q in card["chat"]] == [("stale", True)]
        card = s.bond_card(u, "TRT150328T24")
        assert {q["raw"]: q["state"] for q in card["chat"]} == {"15/3/28 100.520/100.560": "stale", "15/3/28 100.500/100.600": "fresh"}
        assert {"bid", "ask"} <= set(card["board"]["implied"])
        # traded away: the offer lifted at 100.600 takes every offer at or under it - ICAP's and TULLETT's stale one
        s.broker_add(u, "15/3/28 100.600 paid", today, "ICAP")
        new = rv("TRT150328T24")
        assert (new[0]["t"], new[1]["t"], new[2]["t"]) == ("100,500", "", "100,600") and re.fullmatch(r"ICAP · (şimdi|\d dk)", new[3]["t"])
        # withdrawn: BGC takes its quote off - nothing of it stands, nothing stale is shown; the line is gone on the card
        s.broker_add(u, "16/4/31 ref", today, "BGC")
        old = rv("TRT160431T35")
        assert [old[k].get("t") for k in (0, 1, 4)] == ["", "", ""] and re.fullmatch(r"\d\d:\d\d", old[3]["t"])
        assert [q["state"] for q in s.bond_card(u, "TRT160431T35")["chat"] if q["event"] == "quote"] == ["gone"]
        # a reset of the bond: what was said before it is gone everywhere
        s.broker_reset(u, today, "DIBS:TRT150328T24")
        assert not any(c.get("t") for c in rv("TRT150328T24"))
        card = s.bond_card(u, "TRT150328T24")
        assert card["board"] is None and {q["state"] for q in card["chat"] if q["event"] == "quote"} == {"gone"}
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------- live quote or not
def _answers(s, values):
    """Bloomberg's answers the recorded file does not have (the sizes of the orders, another source's quote), handed
    over as the live provider does: the cells that use them are calculated again and the pages see it."""
    s.et.call(s._apply_market, s.provider.update({bdp_key(sec, fld): v for (sec, fld), v in values.items()}))
    s.bump()


def _summary(s, u, isin):
    """The trading summary's header and the line of a bond."""
    rows = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L0")["data"]["rows"]
    return [c["t"] for c in rows[0]], next(row for row in rows if any(c.get("t") == isin for c in row))


def test_a_bid_or_ask_without_an_order_is_no_live_quote(tmp_path):
    """Borsa İstanbul's sources repeat a price as bid and ask when no order stands (the last trade; a bill's at its
    yield on the next value date).  The size of the order tells a live quote from it: with no order ("#N/A N/A") the
    side is "–" with Bloomberg's figure in the tip, nothing is worked out of it, and what is worked out of the price
    in use is soft; a live quote has its size in the tip and on the card.  A size that tells nothing (the recorded
    file, a source without sizes such as BGN) leaves everything as it was."""
    s = make_service(tmp_path)
    try:
        u = s.login("Kota Bakan")["user"]
        uk = user_key(u)
        s.broker_settings(u, 1440)                            # the morning's chat is fresh whenever this runs
        s.broker_add(u, CHAT, s.today_iso(), source="ICAP")
        sec, old = "TRT150328T24 @ISL1 ISIN", "TRT100730T13 @ISL1 ISIN"     # DİBS RV rows 8 and 23, priced on ISL1
        assert (cell(s, "DİBS RV!BT8"), cell(s, "DİBS RV!BT23")) == (sec, old)
        # the recorded file has no sizes: everything as it was
        cols = ("K", "L", "M", "O", "T", "U", "V", "W", "Z", "AB", "AC", "AD", "AE")
        before = {c: cell(s, "DİBS RV!%s8" % c) for c in cols}
        assert (before["K"], before["L"], before["W"], cell(s, "DİBS RV!J8")) == (100.1, 100.125, 2.5, "Canlı")
        assert (cell(s, "DİBS RV!XR8"), cell(s, "DİBS RV!XS8"), cell(s, "DİBS RV!J23")) == ("", "", "Son fiyat (26.10.2026)")

        # no order on either side (a closed market): "#N/A N/A"
        _answers(s, {(x, f): "#N/A N/A" for x in (sec, old) for f in ("BID_SIZE", "ASK_SIZE")})
        assert [cell(s, "DİBS RV!%s8" % c) for c in ("XR", "XS", "K", "L")] == [0.0, 0.0, "–", "–"]
        assert [cell(s, "DİBS RV!%s8" % c) for c in ("U", "V", "W", "AD", "AE")] == ["", "", "", "", ""]   # nothing of the sides
        kept = ("M", "O", "T", "Z", "AB", "AC")                    # the price in use and what is worked out of it
        assert {c: cell(s, "DİBS RV!%s8" % c) for c in kept} == {c: before[c] for c in kept}
        assert (cell(s, "DİBS RV!J8"), cell(s, "DİBS RV!J23")) == ("Kota yok · işlem bugün", "Kota yok · son fiyat (26.10.2026)")
        # the trading summary
        heads, line = _summary(s, u, "TRT150328T24")
        bid, ask = line[heads.index("Bid")], line[heads.index("Ask")]
        assert (bid["t"], bid["cls"], ask["t"], ask["cls"]) == ("–", "soft", "–", "soft")
        assert bid["tip"] == "Kota yok: bid tarafında emir yok (BID_SIZE boş) · Bloomberg'in tekrar ettiği fiyat 100,100, canlı değil"
        assert "ASK_SIZE" in ask["tip"] and "100,125" in ask["tip"]
        for h in ("Getiri %", "ASW / DM", "Pahalı / ucuz", "Sinyal"):
            got = line[heads.index(h)]
            assert "soft" in got["cls"] and got["tip"] == "Fiyat durumu: Kota yok · işlem bugün · iki taraflı canlı kota yok, değer bu fiyattan", h
        assert "soft" not in (line[heads.index("Mod. süre")].get("cls") or "")
        heads, other = _summary(s, u, "TRT160431T35")             # a bond whose sizes are not known: as before
        assert other[heads.index("Bid")]["t"] == "94,380" and "soft" not in (other[heads.index("Getiri %")].get("cls") or "")
        # the DİBS RV page: its bid / ask, the values of the price in use, the broker's distance from the screen
        d = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")["data"]
        row = next(r for r, n in zip(d["rows"], d["r"]) if n == 8)
        k, t, g = d["c"].index("K"), d["c"].index("T"), d["c"].index("G")
        assert (row[k]["t"], row[k]["cls"]) == ("–", "soft") and "soft" in row[t]["cls"] and "soft" not in (row[g].get("cls") or "")
        gap = row[d["c"].index("Broker − ekran (bp)")]
        assert "soft" in gap["cls"] and gap["tip"] == "Ekranda iki taraflı canlı kota yok (Kota yok · işlem bugün): ekran getirisi bu fiyattan"
        row13 = next(r for r, n in zip(d["rows"], d["r"]) if n == 13)
        assert type(row13[k]["v"]) is float and "soft" not in (row13[d["c"].index("Broker − ekran (bp)")].get("cls") or "")
        # DİBS Trading's value dates: T1 says no quote; its price for the repo is the last trade, of that trade's day
        L = ex._live_cols()
        g1 = L["groups"][1]
        d = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L1")["data"]
        row = next(r for r, n in zip(d["rows"], d["r"]) if n == 8)
        got = row[d["c"].index(g1["bid"])]
        assert (got["t"], got["cls"]) == ("–", "soft") and "100,100" in got["tip"]
        assert cell(s, "EK_DIBS!%s8" % L["mid"][1]) == 100.2 and cell(s, "EK_DIBS!%s8" % L["day"][1]) == cell(s, "EK_DIBS!%s8" % g1["when"])
        # the card
        card = s.bond_card(u, "TRT150328T24")
        t1 = card["live"][1]
        assert (t1["cap"], t1["bid"], t1["ask"], t1["bid_size"], t1["ask_size"]) == ("T1", "–", "–", "", "")
        assert t1["bid_tip"] == bid["tip"] and "100,125" in t1["ask_tip"]
        rv = {x["name"]: x for x in card["rv"]}
        assert rv["Fiyat durumu"]["t"] == "Kota yok · işlem bugün" and not rv["Fiyat durumu"].get("soft")
        assert rv["BIST bileşik getiri"]["soft"] and rv["Sinyal"]["soft"] and rv["BIST bileşik getiri"]["tip"] == line[heads.index("Getiri %")]["tip"]
        assert not rv["Kupon"].get("soft") and not any(name.startswith("Alış−satış") for name in rv)
        # Tüm Kâğıtlar
        d = s.view(u, "kagitlar")["panels"][0]["data"]
        row = next(r for r in d["rows"] if r[0].get("t") == "TRT150328T24")
        at = {c: d["c"].index(c) for c in "IJNOPQ"}
        assert (row[at["I"]]["t"], row[at["I"]]["cls"], row[at["J"]]["t"]) == ("–", "soft", "–") and "100,100" in row[at["I"]]["tip"]
        assert all("soft" in row[at[c]]["cls"] for c in "NOP") and "soft" not in (row[at["Q"]].get("cls") or "")        # (DV01)
        # the ALIŞ price type uses the bid only while it is a live quote: the middle now
        w = s.login("Alış Fiyatı")["user"]
        s.set_inputs(w, "tto", [{"ref": "DİBS RV!X2", "value": "ALIŞ"}])
        assert cell(s, "DİBS RV!O8", user=user_key(w)) == before["M"] and cell(s, "DİBS RV!J8", user=user_key(w)) == "ALIŞ · Kota yok · işlem bugün"

        # live quotes on both sides: the sheet as it was, the sizes in the tips and on the card
        _answers(s, {(sec, "BID_SIZE"): 5e6, (sec, "ASK_SIZE"): 2.5e6})
        assert {c: cell(s, "DİBS RV!%s8" % c) for c in cols} == before and cell(s, "DİBS RV!J8") == "Canlı kota"
        assert cell(s, "DİBS RV!O8", user=user_key(w)) == 100.1                             # ALIŞ: the live bid
        heads, line = _summary(s, u, "TRT150328T24")
        bid = line[heads.index("Bid")]
        assert (bid["t"], bid.get("cls"), bid["tip"]) == ("100,100", None, "Bid boyutu: 5.000.000")
        assert line[heads.index("Ask")]["tip"] == "Ask boyutu: 2.500.000" and "soft" not in (line[heads.index("Sinyal")].get("cls") or "")
        t1 = s.bond_card(u, "TRT150328T24")["live"][1]
        assert (t1["bid"], t1["ask"], t1["bid_size"], t1["ask_size"], t1["bid_tip"]) == ("100,100", "100,125", "5.000.000", "2.500.000", "")

        # one side: the bid stands, the ask does not
        _answers(s, {(sec, "ASK_SIZE"): "#N/A N/A"})
        assert [cell(s, "DİBS RV!%s8" % c) for c in ("K", "L", "V", "W", "AE", "J")] == [100.1, "–", "", "", "", "Canlı: yalnız bid"]
        assert (cell(s, "DİBS RV!U8"), cell(s, "DİBS RV!AD8")) == (before["U"], before["AD"])
        heads, line = _summary(s, u, "TRT150328T24")
        assert "Canlı: yalnız bid" in line[heads.index("Getiri %")]["tip"] and line[heads.index("Bid")]["t"] == "100,100"

        # another source without sizes (BGN): its quote as it is
        bgn = "TRT150328T24 @BGN ISIN"
        _answers(s, {(bgn, "PX_BID"): 100.377, (bgn, "PX_ASK"): 100.597, (bgn, "BID_SIZE"): NOT_APPLICABLE, (bgn, "ASK_SIZE"): NOT_APPLICABLE})
        assert [cell(s, "EK_DIBS!%s8" % c) for c in (ex.LIVE_EXTRA, "V")] == [100.377, 100.597]
        extra = s.bond_card(u, "TRT150328T24")["extra"]
        assert {k: extra[k] for k in ("src", "bid", "ask", "bid_size", "bid_tip")} == {"src": "BGN", "bid": "100,377", "ask": "100,597",
                                                                                          "bid_size": "", "bid_tip": ""}

        # the repo: live quotes are prices of today - T0 last traded on 20.10, but its live quotes and T1's make a repo
        _answers(s, {(sec, "ASK_SIZE"): 2.5e6})
        raw0, size0, wcol = L["raw"][0], L["size"][0], ex.LIVE_REPO[0]
        res = s.set_inputs(u, "tto", [{"ref": "EK_DIBS!%s8" % raw0["bid"], "value": 100.0}, {"ref": "EK_DIBS!%s8" % raw0["ask"], "value": 100.03},
                                      {"ref": "EK_DIBS!%s8" % raw0["acc"], "value": 4.86},
                                      {"ref": "EK_DIBS!%s8" % raw0["date"], "value": 46315.0}], allow_adhoc=True)
        assert not res["errors"]
        assert cell(s, "EK_DIBS!%s8" % wcol, user=uk) == ""                     # T0's sizes not known: the day of its last trade
        assert s.bond_card(u, "TRT150328T24")["repo_note"] == (
            "T0 ve T1 fiyatları aynı güne ait değil (T0 son işlem: 20.10.2026 · T1 canlı kota: 03.11.2026): repo hesaplanmadı")
        res = s.set_inputs(u, "tto", [{"ref": "EK_DIBS!%s8" % size0[side], "value": 3e6} for side in ("bid", "ask")], allow_adhoc=True)
        assert not res["errors"]
        assert cell(s, "EK_DIBS!%s8" % L["day"][0], user=uk) == cell(s, "EK_DIBS!%s8" % L["day"][1], user=uk) == 46329.0     # today
        dirty0, dirty1 = 100.015 + 4.86, cell(s, "DİBS RV!M8") + cell(s, "DİBS RV!CW8")
        assert cell(s, "EK_DIBS!%s8" % wcol, user=uk) == pytest.approx((dirty1 / dirty0 - 1) * 365 * 100)
        assert s.bond_card(u, "TRT150328T24")["repo_note"] == ""
    finally:
        s.stop()


def test_on_a_closed_market_no_bid_or_ask_is_shown_as_a_quote(tmp_path):
    """A Sunday: Bloomberg has no size for any bond on Borsa İstanbul's sources (and BGN none at all).  No page shows
    a bid or ask of the exchange as a quote, every bond of the trading list says so ("Kota yok · …"), and the
    yields, ASW and signals are still there - soft."""
    s = make_service(tmp_path)
    try:
        u = s.login("Pazar Masa")["user"]
        L = ex._live_cols()
        listed = [r for r in range(ex.LIVE_FIRST, ex.LIVE_LAST + 1) if cell(s, "DİBS RV!A%d" % r)]
        secs = {cell(s, "EK_DIBS!%s%d" % (c, r)) for r in listed for c in L["sec"] + [L["sec_extra"]]}
        secs |= {cell(s, "EK_EVREN!U%d" % r) for r, b, _ in ex.universe_rows() if b}
        assert len(listed) >= 15 and len(secs) > 100
        _answers(s, {(x, f): NOT_APPLICABLE if "@BGN" in x else "#N/A N/A" for x in secs for f in ("BID_SIZE", "ASK_SIZE")})
        assert all(str(cell(s, "DİBS RV!J%d" % r)).startswith("Kota yok · ") for r in listed)
        assert not any(type(cell(s, "DİBS RV!%s%d" % (c, r))) is float for r in listed for c in ("K", "L", "W"))
        assert sum(1 for r in listed if cell(s, "DİBS RV!K%d" % r) == "–") >= 15
        heads, _ = _summary(s, u, "TRT150328T24")
        rows = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L0")["data"]["rows"]
        bonds = [row for row in rows[1:] if row[-1].get("t") == "▸"]
        assert len(bonds) == len(listed)
        assert all(row[heads.index(h)]["t"] in ("–", "") for row in bonds for h in ("Bid", "Ask"))
        priced = [row[heads.index("Getiri %")] for row in bonds if row[heads.index("Getiri %")]["t"]]
        assert len(priced) >= 15 and all("soft" in c["cls"] for c in priced)
        quotes = [g[side] for g in L["groups"] for side in ("bid", "ask")]
        assert not any(type(cell(s, "EK_DIBS!%s%d" % (c, r))) is float for r in listed for c in quotes)
        assert not any(type(cell(s, "EK_EVREN!%s%d" % (c, r))) is float for r, b, _ in ex.universe_rows() if b for c in "IJ")
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------- every bond, the trading list
def test_every_bond_is_in_one_place_kind_by_kind(svc):
    rows = ex.universe_rows()
    captions = [c for _, b, c in rows if b is None]
    assert captions == ["Bono · 2 kâğıt", "Kuponsuz · 2 kâğıt", "Sabit kuponlu · 26 kâğıt", "TLREF'e endeksli · 23 kâğıt",
                        "TÜFE'ye endeksli · 24 kâğıt"]
    listed = [b for _, b, _ in rows if b is not None]
    assert len(listed) == 77 and rows[0][0] == ex.UNI_FIRST
    for kind in ("fixed", "float"):
        mats = [b["maturity"] for b in listed if b["kind"] == kind]
        assert mats == sorted(mats)
    at = {b["isin"]: r for r, b, _ in rows if b is not None}
    r = at["TRT150328T24"]
    assert [cell(svc, "EK_EVREN!%s%d" % (c, r)) for c in "ABCDE"] == ["TRT150328T24", "15.03.28", "Sabit", 0.368, 46827.0]
    assert cell(svc, "EK_EVREN!F%d" % r) == 46827.0 - 46329.0 and cell(svc, "EK_EVREN!G%d" % r) == pytest.approx(498 / 365.25)
    # on the trading list: ★, its price from DİBS RV on the same source, what DİBS RV makes of it
    assert cell(svc, "EK_EVREN!H%d" % r) == "★" and cell(svc, "EK_EVREN!R%d" % r) == "ISL1"
    assert [cell(svc, "EK_EVREN!%s%d" % (c, r)) for c in "IJKL"] == [100.1, 100.125, 100.2, 46329.0]
    assert cell(svc, "EK_EVREN!N%d" % r) == cell(svc, "DİBS RV!T8") and cell(svc, "EK_EVREN!P%d" % r) == cell(svc, "DİBS RV!AC8")
    # bills on their own value date
    rb = at["TRB100227T13"]
    assert (cell(svc, "EK_EVREN!R%d" % rb), cell(svc, "EK_EVREN!I%d" % rb), cell(svc, "EK_EVREN!D%d" % rb)) == ("ISL0", 92.22, "iskontolu")
    # off the list: no mark, Bloomberg asked (nothing offline), nothing of DİBS RV
    rf = at["TRT130127T11"]
    assert [cell(svc, "EK_EVREN!%s%d" % (c, rf)) for c in "CDHIKNP"] == ["TLREF", "TLREF", "", "", "", "", ""]
    assert cell(svc, "EK_EVREN!U%d" % rf) == "TRT130127T11 @ISL1 ISIN"
    rc = at["TRT070727T13"]
    assert cell(svc, "EK_EVREN!D%d" % rc) == "reel %2,90" and cell(svc, "EK_EVREN!B%d" % rc) == "07.07.27 TÜFE"
    # the desk's own (a new issue): the label and the maturity from a Turkish ISIN
    u = svc.login("Evren Ekleyen")["user"]
    res = svc.list_add(u, "tto", "EK_EVREN!A6:A20", ["TRT280432T14"])
    assert res["cells"] == ["EK_EVREN!A6"]
    assert [cell(svc, "EK_EVREN!%s6" % c) for c in "ABCE"] == ["TRT280432T14", "28.04.32", "liste dışı", 48332.0]
    assert cell(svc, "EK_EVREN!H6") == "" and cell(svc, "EK_EVREN!U6") == "TRT280432T14 @ISL1 ISIN"
    svc.set_inputs(u, "tto", [{"ref": "EK_EVREN!A6", "value": None}])
    # the page: ☆ / ★ to click, today's board and the card on the right; the own rows grow
    view = svc.view(u, "kagitlar")
    panel = view["panels"][0]
    assert (panel["flags"], panel["card"], panel["grow"]["first"], panel["add"]["ref"]) == ("dibs", "bond", 6, "EK_EVREN!A6:A20")
    d = panel["data"]
    j = d["c"].index("H")
    marks = {row[0]["t"]: row[j] for row, n in zip(d["rows"], d["r"]) if n >= ex.UNI_FIRST and len(row[0].get("t") or "") == 12}
    assert len(marks) == 77
    assert marks["TRT150328T24"]["t"] == "★" and "on" in marks["TRT150328T24"]["cls"] and marks["TRT150328T24"]["tip"].endswith("TRT150328T24")
    assert marks["TRT130127T11"]["t"] == "☆" and "on" not in marks["TRT130127T11"]["cls"]
    assert d["c"][-5:] == ["Broker bid", "Broker ask", "Son işlem", "Kimde · yaş", "Kart"]


def test_a_star_puts_a_bond_on_the_trading_list_and_takes_it_off(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Yıldız Koyan")["user"]
        other = s.login("Öbür Masa")["user"]
        before = s._list_values(u, "tto", "DİBS RV!A5:A54")
        last = max(k for k, v in enumerate(before) if v)
        res = s.bond_flag(u, "trt190128t14", True)
        assert res == {"isin": "TRT190128T14", "on": True, "added": True, "cells": ["DİBS RV!A%d" % (5 + last + 1)], "gen": res["gen"]}
        r = 5 + last + 1
        assert s.bond_flag(u, "TRT190128T14", True)["added"] is False                   # already there
        assert s._list_values(other, "tto", "DİBS RV!A5:A54")[last + 1] == "TRT190128T14"  # for everyone
        # the page of every bond marks it, the trading summary has it under its kind
        rows = {b["isin"]: n for n, b, _ in ex.universe_rows() if b}
        assert cell(s, "EK_EVREN!H%d" % rows["TRT190128T14"]) == "★"
        summary = s.view(u, "dibslive")["panels"][0]
        assert (summary["id"], summary["flags"], summary["card"]) == ("L0", "dibs", "bond")
        lines = [[c.get("t") for c in row] for row in summary["data"]["rows"]]
        assert lines[0][:4] == ["★", "Kâğıt", "ISIN", "Vade"] and lines[0][-1] == "Kart"
        groups = [x[0] for x in lines if x[0] != "★" and x[0] != lines[0][0]]
        assert groups == ["Bono · kuponsuz · 2", "Sabit kuponlu · 14", "TLREF'e endeksli · 4"]
        floaters = [x for x in lines if x[2] in ("TRT190128T14", "TRT090130T12", "TRT030730T12", "TRT110930T36")]
        assert [x[1] for x in floaters] == ["19.01.28 TLREF", "09.01.30 TLREF", "03.07.30 TLREF", "11.09.30 TLREF"]   # by maturity
        t8 = next(x for x in lines if x[2] == "TRT150328T24")
        assert t8[5:10] == ["ISL1", "100,100", "100,125", "100,200", "03.11.2026"] and t8[13] in ("UCUZ", "PAHALI", "–")
        # what goes with a row: the desk's source and everyone's own values for it
        s.set_inputs(u, "tto", [{"ref": "DİBS RV!B%d" % r, "value": "ISL0"}, {"ref": "DİBS RV!N%d" % r, "value": 100.5}])
        s.set_inputs(other, "tto", [{"ref": "DİBS RV!AL%d" % r, "value": 40.0}])
        assert cell(s, "DİBS RV!N%d" % r, user=user_key(u)) == 100.5
        res = s.bond_flag(u, "TRT190128T14", False)
        assert (res["on"], res["removed"]) == (False, 1)
        assert cell(s, "DİBS RV!A%d" % r) is None and cell(s, "DİBS RV!B%d" % r) is None
        assert cell(s, "DİBS RV!N%d" % r, user=user_key(u)) is None and cell(s, "DİBS RV!AL%d" % r, user=user_key(other)) is None
        assert s.store.user_inputs(user_key(other), "tto").get(("tto", "DİBS RV!AL%d" % r)) is None
        assert cell(s, "EK_EVREN!H%d" % rows["TRT190128T14"]) == ""
        assert s.bond_flag(u, "TRT190128T14", False)["removed"] == 0
        with pytest.raises(ServiceError):
            s.bond_flag(u, "TRT190128T15", True)                                        # the check digit
        hdr = auth(s, u)
        with TestClient(create_app(s)) as client:
            got = client.post("/api/bonds/flag", json={"isin": "TRT130127T11", "on": True}, headers=hdr)
            assert got.status_code == 200 and got.json()["added"] is True
            assert client.post("/api/bonds/flag", json={"isin": "TRT130127T11", "on": False}, headers=hdr).json()["removed"] == 1
            assert client.post("/api/bonds/flag", json={"isin": "X", "on": True}, headers=hdr).status_code == 400
    finally:
        s.stop()
