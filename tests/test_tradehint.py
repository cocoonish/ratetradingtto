"""Fiyattan işlem: a price right-clicked on a page as a trade ("İşlem gir").  The views' "trade" hints (every one checked
against its workbook) and what Günlük İşlemler's form is filled with, per kind of table: a forward quote matrix (each
row's own value date), a single-date forward table (the table's date; its RET row on the RET curve), the RET curve
(dated by tenor from the spot), the calculators (a date in another table), OIS (a tenor; a meeting swap's own two
days), bonds (the row's ISIN; a yield at its own price), a VİOP contract (no form: why).  The side by the column;
cells that are no price; the row's own cells, not its place; the HTTP end point."""
import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import tradehint as th
from tto.server import create_app
from tto.service import ServiceError
from tto.views import load_views
from tto.xl.model import parse_range
from tto.xl.tokenizer import col_to_index
from tto.xl.values import serial_to_date

VIEWS = load_views()
HINTED = [(v, p) for v in VIEWS for p in v["panels"] if p.get("trade")]


def day(serial):
    return serial_to_date(serial).strftime("%d.%m.%Y")


def go(svc, view, panel, ref, text, user="Fiyat İşlem", label=""):
    """The spec "İşlem gir" on ``ref`` ("H7", the table's own sheet) fills the form with."""
    col = "".join(ch for ch in ref if ch.isalpha())
    return svc.trade_prefill(user, {"view": view, "panel": panel, "row": int(ref[len(col):]), "col": col, "text": text,
                                    "label": label})["spec"]


def refused(svc, view, panel, ref, text="1", **kw):
    with pytest.raises(ServiceError) as exc:
        go(svc, view, panel, ref, text, **kw)
    return exc.value


# ---------------------------------------------------------------------------------------------- the page definitions
@pytest.mark.parametrize("vp", HINTED, ids=["%s/%s" % (v["id"], p["id"]) for v, p in HINTED])
def test_every_trade_hint_is_well_formed(service, vp):
    """A hint parses, names cells of its own table (columns it shows), and the cells it reads exist."""
    v, p = vp
    hint = p["trade"]
    assert th.check(hint) == [], (v["id"], p["id"])
    model = service.books[v["book"]].model
    sheet = p.get("sheet", v["sheet"])
    r1, c1, r2, c2 = parse_range(p["range"])
    shown = p.get("cols")
    for key in hint.get("cells") or {}:
        col = "".join(ch for ch in key if ch.isalpha())
        assert c1 <= col_to_index(col) <= c2 and (not shown or col in shown), (p["id"], key)
        if key != col:
            assert r1 <= int(key[len(col):]) <= r2, (p["id"], key)
    assert r1 <= hint.get("first", r1) <= hint.get("last", r2) <= r2, p["id"]
    for k in ("date_col", "tenor_col", "start_col", "end_col", "isin_col"):
        if hint.get(k):
            assert c1 <= col_to_index(hint[k]) <= c2, (p["id"], k)
    for side, col in (hint.get("yield_price") or {}).items():
        assert side in th.SIDES and c1 <= col_to_index(col) <= c2, p["id"]
    if hint.get("date"):
        model.cell_ref(hint["date"] if "!" in hint["date"] else "%s!%s" % (sheet, hint["date"]))
    # the header's "İşlem gir" dialog (forward tables): a pair, the rows' label and both sides' swap points
    if hint.get("bid") or hint.get("ask"):
        assert hint.get("pair") and hint.get("label") and hint.get("bid") and hint.get("ask"), p["id"]


def test_the_tables_that_take_part():
    """The forward tables of Masa and Forward, the RET rows, the calculators, OIS quotes, the bond lists, VİOP."""
    names = {"%s/%s" % (v["id"], p["id"]) for v, p in HINTED}
    assert names == {"masa/EKS", "masa/EKSE", "masa/B3", "masa/B8", "masa/B10", "masa/B15", "masa/B22", "forward/FR1",
                     "forward/FR2", "forward/EKF1", "forward/EKF5", "forward/B19", "forward/BK1", "ois/B3", "ois/B13", "dibs/B3",
                     "dibslive/L1", "kagitlar/U1", "asw/tbl", "manuel/B12"}            # (Manuel Tahvil's quote ticket: 28.11.2026)
    with pytest.raises(ValueError):
        th.parse("sp mid")
    assert th.parse("try ask") == ("try", "ask") and th.parse("ois") == ("ois", None)
    assert th.check({"cells": {"H": "sp bid"}}) == ["forward valörü: date, date_col ya da tenor_col (yalnız biri)"]
    assert th.check({"cells": {"h1": "ois"}, "tenor_col": "A"})[0].startswith("hücre anahtarı")
    assert th.check({"cells": {"D": "none"}}) == ["karşılığı olmayan fiyat: why gerekli"]
    assert th.check({"cells": {"U": "yield bid"}, "isin_col": "A"}) == ["getirinin fiyat sütunu yok (yield_price): U"]


def test_the_browser_gets_the_price_cells_with_the_table(service):
    """``data.trade``: the page, the table, the rows and the cells (""; a price without a form: why).  The header's
    dialog (``trade`` of the panel) stays the forward tables' with swap points; a launchpad's part keeps the cells."""
    masa = {p["id"]: p for p in service.view(None, "masa")["panels"]}
    assert masa["EKS"]["data"]["trade"] == {"view": "masa", "panel": "EKS", "first": 5, "last": 14,
                                            "cells": dict.fromkeys(["H", "I", "J", "K", "M", "N"], "")}
    assert masa["B15"]["data"]["trade"]["cells"] == {"D": "VİOP kontratı – Günlük İşlemler'de VİOP yok",
                                                     "E": "VİOP kontratı – Günlük İşlemler'de VİOP yok"}
    assert "trade" not in masa["EKS"] and "trade" not in masa["B2"]["data"]
    fr1 = next(p for p in service.view(None, "forward")["panels"] if p["id"] == "FR1")
    assert fr1["trade"]["bid"] == "H" and fr1["data"]["trade"]["cells"]["B50"] == ""
    got = service.panels(None, [{"view": "masa", "panel": "EKS", "cols": ["A", "B", "I"]}])["panels"]["masa/EKS"]
    assert got["entry"]["data"]["c"] == ["A", "B", "I"] and got["entry"]["data"]["trade"]["panel"] == "EKS"


# ---------------------------------------------------------------------------------------------- forwards
def test_a_forward_quote_row_with_its_own_value_date(service):
    """Masa's quote matrix: the row's own value date (column B), the pair of the table, the price as clicked; at the
    bid the desk buys the currency, at the ask it sells.  Points, outright and TRY rate each their pricing."""
    d7 = day(cell(service, "EK_FWD!B7"))
    spec = go(service, "masa", "EKS", "I7", "39.049", label="3M · Puan ask")
    assert spec == {"kind": "fwd", "pair": "USDTRY", "dir": "S", "date": d7, "basis": "SP", "value": "39.049",
                    "note": "Fiyat: 3M · Puan ask (Masa · FORWARD KOTASYON)"}
    assert (go(service, "masa", "EKS", "H7", "39.048")["dir"], go(service, "masa", "EKS", "J7", "53,9018")["basis"]) == ("B", "FWD")
    m = go(service, "masa", "EKS", "M7", "34,90")
    assert (m["basis"], m["dir"], m["value"]) == ("TRY", "B", "34,90")
    k = go(service, "masa", "EKS", "K10", "66,5144")
    assert (k["basis"], k["dir"], k["date"]) == ("FWD", "S", day(cell(service, "EK_FWD!B10")))
    e = go(service, "masa", "EKSE", "H106", "46.026")
    assert (e["pair"], e["date"], e["dir"]) == ("EURTRY", day(cell(service, "EK_FWD!B106")), "B")
    assert go(service, "forward", "EKF1", "S7", "35,50")["basis"] == "RET_ASK"          # the Forward page's own matrix


def test_a_single_date_table_and_its_ret_row(service):
    """The Forward page's USDTRY / EURTRY tables: the table's value date (Forward!D2, its B45); a curve's mid leaves the
    side to the user; the RET row is the RET curve's own pricing (RET bid / mid / ask), nothing typed."""
    d = day(cell(service, "EK_FWD!B45"))
    assert go(service, "forward", "FR1", "J47", "95.150") == {"kind": "fwd", "pair": "USDTRY", "dir": "S", "date": d,
                                                              "basis": "SP", "value": "95.150", "note": "Fiyat: (Forward · USDTRY FORWARD)"}
    mid = go(service, "forward", "FR1", "C48", "37,9598")
    assert (mid["basis"], mid["dir"], mid["value"]) == ("TRY", None, "37,9598")
    ret = go(service, "forward", "FR1", "B50", "35,9196")
    assert (ret["basis"], ret["dir"], ret["value"]) == ("RET_BID", "B", "")
    assert go(service, "forward", "FR1", "C50", "36,3435")["basis"] == "RET_MID"
    eur = go(service, "forward", "FR2", "D61", "36,7674")
    assert (eur["pair"], eur["basis"], eur["dir"], eur["date"]) == ("EURTRY", "RET_ASK", "S", day(cell(service, "EK_FWD!B56")))


def test_a_bulk_row_of_either_pair(service):
    """TOPLU FORWARD (the desk, 24.11.2026: "3 ekle"): USDTRY and EURTRY side by side - each price is its own column's
    pair (the hint's ``"pairs"``): USDTRY fwd / puan, the typed USDTRY fwd and its implied TRY % are USDTRY's, the
    EURTRY ones EURTRY's; the value date is the row's own (B); mid or typed prices, so no side.  A row without a valör,
    a rate that is no forward's price (RET mid %), the header row: refused."""
    u = service.login("Toplu Fiyat")["user"]
    try:
        assert service.set_inputs(u, "tto", [{"ref": "EK_BULK!B7", "value": "15.03.2027"},
                                             {"ref": "EK_BULK!R7", "value": "53,1"}, {"ref": "EK_BULK!T7", "value": "60,2"}])["errors"] == []
        note = "Fiyat: (Forward · TOPLU FORWARD FİYATLAMA · 100 valöre kadar)"
        got = {c: go(service, "forward", "BK1", c + "7", t, user=u) for c, t in (("N", "53,0632"), ("O", "4.213"), ("P", "59,5801"),
                                                                              ("Q", "3.456"), ("R", "53,1"), ("S", "41,2345"),
                                                                              ("T", "60,2"), ("U", "40,9876"))}
        assert got["N"] == {"kind": "fwd", "pair": "USDTRY", "dir": None, "date": "15.03.2027", "basis": "FWD", "value": "53,0632",
                            "note": note}
        assert {c: (s["pair"], s["basis"], s["dir"], s["date"]) for c, s in got.items()} == {
            "N": ("USDTRY", "FWD", None, "15.03.2027"), "O": ("USDTRY", "SP", None, "15.03.2027"),
            "P": ("EURTRY", "FWD", None, "15.03.2027"), "Q": ("EURTRY", "SP", None, "15.03.2027"),
            "R": ("USDTRY", "FWD", None, "15.03.2027"), "S": ("USDTRY", "TRY", None, "15.03.2027"),
            "T": ("EURTRY", "FWD", None, "15.03.2027"), "U": ("EURTRY", "TRY", None, "15.03.2027")}
        assert got["Q"]["value"] == "3.456" and got["U"]["value"] == "40,9876"
        assert "valör tarihi yok" in str(refused(service, "forward", "BK1", "P8", "59,5", user=u))
        assert "fiyat değil" in str(refused(service, "forward", "BK1", "G7", "41,0", user=u))
        # (nor its ON karşılık %, Spread (bp) or P/gün, 26.11.2026 - no forward's price: İşleme al books the rate they give,
        # as the value-date tables' P/gün is no price either)
        for ref, text in (("M7", "33,39"), ("I7", "25,0"), ("AO7", "425,8"), ("AP7", "501,4")):
            assert "fiyat değil" in str(refused(service, "forward", "BK1", ref, text, user=u)), ref
        assert "fiyat değil" in str(refused(service, "forward", "BK1", "N4", "1", user=u))
        # the browser gets its price cells with the table, the pairs stay the server's
        bk = next(p for p in service.view(u, "forward")["panels"] if p["id"] == "BK1")
        assert bk["data"]["trade"] == {"view": "forward", "panel": "BK1", "first": 5, "last": 104,
                                       "cells": dict.fromkeys("NOPQRSTU", "")} and "trade" not in bk
    finally:
        service.reset_inputs(u, "tto")
    # the per-cell pair: a key of a forward price, a pair that is one; elsewhere the table's pair
    hint = {"pair": "USDTRY", "date_col": "B", "cells": {"N": "fwd", "P": "fwd", "P9": "sp"}, "pairs": {"P": "EURTRY", "P9": "GBPTRY"}}
    assert th.check(hint) == [] and [th.pair_at(hint, 7, c) for c in "NP"] == ["USDTRY", "EURTRY"] and th.pair_at(hint, 9, "P") == "GBPTRY"
    assert th.check(dict(hint, pairs={"Q": "EURTRY"})) == ["pairs: 'Q' bir forward fiyat hücresinin anahtarı değil"]
    assert th.check(dict(hint, pairs={"P": "LIRA"})) == ["pairs: parite anlaşılamadı: 'LIRA' (örn. EURTRY, GBP)"]
    assert th.check(dict(hint, pairs={"P": ""})) == ["pairs: parite yok: 'P'"]
    assert th.check(dict(hint, pairs=[])) == ["pairs bir nesne olmalı"]
    assert th.check({"tenor_col": "A", "cells": {"B": "ois"}, "pairs": {"B": "EURTRY"}}) == [
        "pairs: 'B' bir forward fiyat hücresinin anahtarı değil"]


def test_ret_rows_are_dated_by_their_tenor(service):
    """The RET curve (Forward's TRY RET, Masa's ORANLAR and RET band): the tenor's value date from the USDTRY spot,
    as the form dates a tenor; ON / TN are no forward."""
    one_m = day(service.et.call(service._tenor_date, "1M", "USDTRY"))
    spec = go(service, "forward", "B19", "W38", "34,45%")
    assert spec == {"kind": "fwd", "pair": "USDTRY", "dir": "B", "date": one_m, "basis": "RET_BID", "value": "",
                    "note": "Fiyat: (Forward · TRY RET)"}
    assert go(service, "forward", "B19", "X45", "39,20%")["date"] == day(service.et.call(service._tenor_date, "1Y", "USDTRY"))
    assert go(service, "masa", "B3", "D10", "34,45%")["date"] == one_m
    assert go(service, "masa", "B8", "R47", "34,65%")["basis"] == "RET_ASK"
    assert "fiyat değil" in str(refused(service, "forward", "B19", "W33", "35,55%"))          # ON


def test_calculators_take_their_dates_from_their_own_cells(service):
    """TARİH ARASI FORWARD: the end date typed in the table beside it (MASA!E60); KIRIK VADE: its value date (C171);
    both mid - the side is the user's."""
    end = day(cell(service, "MASA!E60"))
    t = go(service, "masa", "B10", "T62", "53,9021")
    assert (t["basis"], t["date"], t["dir"], t["value"]) == ("FWD", end, None, "53,9021")
    assert (go(service, "masa", "B10", "R66", "34,88")["basis"], go(service, "masa", "B10", "V67", "39.039")["basis"]) == ("TRY", "SP")
    assert "fiyat değil" in str(refused(service, "masa", "B10", "W62"))                    # a forward-forward: no form
    kv = day(cell(service, "MASA!C171"))
    assert [(s["basis"], s["date"], s["dir"]) for s in (go(service, "masa", "B22", "F173", "79,0537"),
                                                        go(service, "masa", "B22", "G174", "253.492"),
                                                        go(service, "masa", "B22", "G175", "40,000%"))] == \
        [("FWD", kv, None), ("SP", kv, None), ("TRY", kv, None)]
    assert "fiyat değil" in str(refused(service, "masa", "B22", "F176"))                    # ACT/365: no pricing for it


# ---------------------------------------------------------------------------------------------- OIS
def test_ois_quotes(service):
    """An OIS par is a mid: an outright of the row's tenor at it, no side.  A MPC OIS row: the form's MPC strategy with
    the row's own two days (days the form offers), however the calendar moved the rows."""
    spec = go(service, "ois", "B3", "B14", "35,55%", label="1Y · PİYASA par")
    assert spec == {"kind": "ois", "strategy": "outright", "side": None, "tenors": ["1Y"], "level": "35,55%",
                    "note": "Fiyat: 1Y · PİYASA par (OIS · PPK · OUTRIGHT)"}
    assert go(service, "ois", "B3", "B15", "35,45%")["tenors"] == ["15M"]
    assert go(service, "masa", "B3", "C15", "35,55%")["tenors"] == ["1Y"]                  # Masa's ORANLAR: OIS kota
    mpc = go(service, "ois", "B13", "D85", "35,45%")
    assert (mpc["strategy"], mpc["side"], mpc["start"], mpc["end"]) == \
        ("mpc", None, cell(service, "OIS_MAIN!B85"), cell(service, "OIS_MAIN!C85"))
    days = [d["date"] for d in service.ois_market(None)["mpc"]["dates"]]
    assert mpc["start"] in days and mpc["end"] in days
    # a quote of ours with a side (no OIS table has one yet): at its bid the desk pays the rate (Broker Chat's rule)
    hint = {"tenor_col": "A", "cells": {"B": "ois bid", "C": "ois ask"}}
    read = {"A9": "1M"}.get
    assert [th.prefill(hint, 9, c, "36,37", read, None)["side"] for c in "BC"] == ["PAY", "RECEIVE"]


# ---------------------------------------------------------------------------------------------- bonds and VİOP
def test_bonds(service):
    """A bond's price: the row's ISIN, bought at the bid, sold at the ask; a yield at its own side's price (the yield in
    the note); the last trade or the price in use is a mid.  A row without a bond is no trade."""
    isin = cell(service, "DİBS RV!A8")
    spec = go(service, "dibs", "B3", "K8", "100,100")
    assert spec == {"kind": "bond", "dir": "B", "instrument": isin, "price": "100,100",
                    "note": "Fiyat: (DİBS RV · DİBS göreli değer tablosu)"}
    assert go(service, "dibs", "B3", "L8", "100,125")["dir"] == "S"
    y = go(service, "dibs", "B3", "V8", "36,38%")
    assert (y["dir"], y["price"]) == ("S", ("%.3f" % cell(service, "DİBS RV!L8")).replace(".", ","))
    assert y["note"].endswith("getiri 36,38%")
    assert go(service, "dibs", "B3", "O8", "100,113")["dir"] is None
    assert (go(service, "dibslive", "L1", "G5", "92,220")["instrument"], go(service, "dibslive", "L1", "L5", "92,220")["dir"]) == \
        (cell(service, "EK_DIBS!A5"), "S")
    assert go(service, "kagitlar", "U1", "I6", "92,220")["instrument"] == cell(service, "EK_EVREN!A6")
    asw = go(service, "asw", "tbl", "L7", "92,220")
    assert (asw["instrument"], asw["dir"]) == (cell(service, "ASW!B7", book="asw"), None)
    assert "ISIN" in str(refused(service, "dibs", "B3", "K7", "100,100"))                   # an empty row of the list


def test_a_price_without_a_form_and_cells_that_are_no_price(service):
    """A VİOP contract says why; a caption, the days of a tenor, a row outside the prices, a table or page without
    prices, a text that is no number - each refused with a word."""
    assert str(refused(service, "masa", "B15", "D110", "51,067")) == "VİOP kontratı – Günlük İşlemler'de VİOP yok"
    assert "fiyat değil" in str(refused(service, "masa", "EKS", "C7", "92"))
    assert "fiyat değil" in str(refused(service, "masa", "EKS", "H4", "1"))                 # "Tümü": the spreads' row
    assert refused(service, "masa", "B2", "C3").status == 404                               # no prices in the table
    assert refused(service, "yok", "EKS", "H7").status == 404
    assert "okunamadı" in str(refused(service, "masa", "EKS", "H7", "–"))
    with pytest.raises(ServiceError) as exc:
        service.trade_prefill("Fiyat İşlem", {"view": "masa", "panel": "EKS", "row": "7", "col": "H", "text": "1"})
    assert exc.value.status == 400


def test_the_rows_own_cells_not_their_place(service):
    """What the row says now: a value date typed over a row's own (a user's input) is the trade's, a free row's date
    too; the next user still has the workbook's."""
    u = service.login("Fiyat Kayan")["user"]
    try:
        assert service.set_inputs(u, "tto", [{"ref": "EK_FWD!B7", "value": "15.03.2027"},
                                             {"ref": "EK_FWD!B11", "value": "20.04.2027"}])["errors"] == []
        assert go(service, "masa", "EKS", "I7", "40.100", user=u)["date"] == "15.03.2027"
        assert go(service, "masa", "EKS", "J11", "56,1000", user=u)["date"] == "20.04.2027"
        assert go(service, "masa", "EKS", "I7", "39.049")["date"] == day(cell(service, "EK_FWD!B7"))
    finally:
        service.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- over HTTP
def test_over_http(service):
    client = TestClient(create_app(service=service))                          # (no "with": the shared service stays up)
    h = auth(service, "Fiyat Http")
    body = {"view": "ois", "panel": "B3", "row": 14, "col": "B", "text": "35,55%", "label": "1Y · PİYASA par"}
    r = client.post("/api/trade/prefill", json=body, headers=h)
    assert r.status_code == 200 and r.json()["spec"]["tenors"] == ["1Y"] and r.json()["spec"]["level"] == "35,55%"
    r = client.post("/api/trade/prefill?lang=en", json=dict(body, view="masa", panel="EKS", row=7, col="I", text="39,049"), headers=h)
    assert r.status_code == 200 and r.json()["spec"]["value"] == "39,049"                   # (the user's number format)
    r = client.post("/api/trade/prefill", json=dict(body, view="masa", panel="B15", row=110, col="D"), headers=h)
    assert r.status_code == 400 and "VİOP" in r.json()["error"]
    assert client.post("/api/trade/prefill", json=dict(body, panel="B9"), headers=h).status_code == 404
    assert client.post("/api/trade/prefill", json=body, headers=ANON).status_code == 401
