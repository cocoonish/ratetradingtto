"""TRY government bonds: the catalog of the desk's Bloomberg list, bonds added to a page's list by ISIN, the broker
chat's bond quotes ("15/3/28 550/575", "Jan30 tlref 98.650/750", auction prices) read against the DİBS RV screen and
shown next to it, and the tables that grow (Bulk Bond, the 100-row bulk forward)."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import cell, make_service
from tto import bonds as bd
from tto import brokerchat as bc
from tto import extras as ex
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
    # "tom" by a bond is its value date, not an FX swap; a switch of two bonds stays as it was written
    assert bc.parse_quote("Sw int 9/1/30 775 offer vs 3/7/30 775 bid") is None
    assert bc.parse_quote("jan30 700 vs jul30 750 switch trading") is None


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
    assert texts == ["Gunaydin...", "Auction prices", "Sw int 9/1/30 775 offer vs  3/7/30 775 bid"]
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


def test_the_dibs_rv_table_shows_the_days_broker_chat(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Tahvil Masa")["user"]
        s.broker_add(u, CHAT, s.today_iso(), source="ICAP")
        board = {r["isin"]: r for r in s.broker(u)["board"] if r.get("isin")}
        assert (board["TRT150328T24"]["bid"], board["TRT150328T24"]["ask"], board["TRT150328T24"]["last"]) == (100.4, 100.475, 100.4)
        panel = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")
        data = panel["data"]
        assert data["c"][-6:] == ["Broker bid", "Broker ask", "Son işlem", "Saat", "Broker getiri %", "Broker − ekran (bp)"]
        assert data["added"] == 6 and panel["action"] == "add-isin" and panel["add"]["ref"] == "DİBS RV!A5:A54"
        rows = {row[0]["t"]: [c.get("t") for c in row[-6:]] for row, r in zip(data["rows"], data["r"]) if 5 <= r <= 54 and row[0].get("t")}
        assert rows["TRT150328T24"][:4] == ["100,400", "100,475", "100,400", "14:13"]
        assert rows["TRT160431T35"][:3] == ["94,100", "94,200", "94,100"]
        assert rows["TRB100227T13"][2:4] == ["31,40", "09:14"]                    # an auction level, not a trade
        gap = next(c for row, r in zip(data["rows"], data["r"]) if row[0].get("t") == "TRT150328T24" for c in row[-1:])
        imp = board["TRT150328T24"]["implied"]
        assert gap["v"] == pytest.approx(((imp["bid"] + imp["ask"]) / 2 - imp["screen_yield"]) * 100.0)
        assert all(not any(v) for k, v in rows.items() if k not in {b for b in board})   # bonds nobody spoke of: empty
        # the export keeps to the sheet's own columns
        with TestClient(create_app(s)) as client:
            hdr = {"X-TTO-User": u}
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
        assert res["added"] == [new] and res["skipped"] == ["TRT150328T24"] and res["cells"] == ["DİBS RV!A%d" % (5 + before.index(""))]
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
        with TestClient(create_app(s)) as client:
            hdr = {"X-TTO-User": u}
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
    # the first twenty rows are the Forward sheet's table, value for value
    for k in range(20):
        for col in ex.BULK_COLS:
            a, b = cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST + k)), cell(svc, "Forward!%s%d" % (col, 144 + k))
            assert a == b or (type(a) is float and type(b) is float and a == pytest.approx(b, abs=1e-9)), (col, k, a, b)
        for col in "BL":
            a, b = cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST + k)), cell(svc, "Forward!%s%d" % (col, 144 + k))
            assert a == (b if b is not None else "")
    # a value date typed in a row the Forward sheet does not have is priced like the others
    u = svc.login("Toplu Forward")["user"]
    r = ex.BULK_FIRST + 60
    typed = [{"ref": "%s!%s%d" % (ex.BULK_SHEET, col, r), "value": cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST))}
             for col in "BL" if cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST)) not in (None, "")]
    assert typed and not svc.set_inputs(u, "tto", typed)["errors"]
    for col in ex.BULK_COLS:
        assert cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, r), user=user_key(u)) == pytest.approx(
            cell(svc, "%s!%s%d" % (ex.BULK_SHEET, col, ex.BULK_FIRST)), abs=1e-9), col
    # the page shows the rows in use and one more; the panel says how
    view = svc.view(u, "forward")
    bk = next(p for p in view["panels"] if p["id"] == "BK1")
    assert bk["grow"] == {"key": "B", "first": ex.BULK_FIRST, "extra": 1, "last": ex.BULK_FIRST + ex.BULK_ROWS - 1}
    assert len(bk["data"]["rows"]) >= ex.BULK_ROWS
    bulk = next(p for p in svc.view(u, "bulk")["panels"] if p["id"] == "B1")
    assert bulk["grow"]["last"] == ex.BULK_BOND_LAST and bulk["action"] == "add-isin" and bulk["add"]["catalog"] is False
