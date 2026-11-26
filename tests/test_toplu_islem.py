"""TOPLU FORWARD → işlem ("İşleme al"; the desk, 24.11.2026: "3 ekle"): the bulk forward table's rows as trades.

The new inputs (Parite, Yön, Tutar, Karşı taraf) on cells no input ever stood on; the rows as the paste Excel'den
yapıştır reads (``entry.bulk_forward_paste``: the price each row shows, the rows left out, the error rows); the booked
forward equal to the row's own - USDTRY at its TRY rate (the workbook's own bulk row prices it: the same formula),
EURTRY and a typed forward at the outright; the save in one go, with notes saying where each trade came from; the Tutar
emptied after it as the browser does (the kept rows' Tutar cells reset), so that a second press finds them no more; a row
whose typed value is its ON karşılık % (26.11.2026) at the TRY rate it gives; over HTTP."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import entry
from tto import extras as ex
from tto.server import create_app
from tto.views import load_views
from tto.xl.model import COLS, parse_a1
from tto.xl.values import date_to_serial

FIRST = ex.BULK_FIRST
NEW = {"EK_BULK!V5:V104": ("list", "Parite"), "EK_BULK!W5:W104": ("list", "Yön"), "EK_BULK!X5:X104": ("amount", "Tutar"),
       "EK_BULK!Y5:Y104": ("text", "Karşı taraf")}


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()])
    assert res["errors"] == [], res["errors"]


def bulk(col, k):
    """The cell of the table's k-th row (1..100) in a column."""
    return "%s!%s%d" % (ex.BULK_SHEET, col, FIRST + k - 1)


def serial(text):
    d, m, y = (int(x) for x in text.split("."))
    import datetime as dt
    return float(date_to_serial(dt.date(y, m, d)))


# ---------------------------------------------------------------------------------------------- the inputs
def test_the_new_inputs_stand_where_no_input_ever_stood(service):
    """Users' typed values are kept by cell: the four new columns (right after the way back's R..U) are personal inputs
    on cells that held nothing in any layout - not another input's, none retired (EK_BULK's inputs were B, L, R and T
    only) - each with its head, the amount an amount ("10m"), the side and the pair a list of their own."""
    view = next(v for v in load_views() if v["id"] == "forward")
    inputs = {i["range"]: i for i in view["inputs"] if "range" in i}
    assert set(NEW) <= set(inputs)
    for rng, (kind, head) in NEW.items():
        assert (inputs[rng]["kind"], inputs[rng]["scope"]) == (kind, "user"), rng
        assert cell(service, "EK_BULK!%s4" % rng.split("!")[1][0]) == head
    assert inputs["EK_BULK!V5:V104"]["options"] == ["USDTRY", "EURTRY"] and inputs["EK_BULK!W5:W104"]["options"] == ["AL", "SAT"]
    assert [ex.BULK_PAIR, ex.BULK_DIR, ex.BULK_AMOUNT, ex.BULK_CPT] == ["V", "W", "X", "Y"]

    def cells(rng):
        sh, a = rng.split("!") if "!" in rng else ("Forward", rng)
        a1, _, a2 = a.partition(":")
        (r1, c1), (r2, c2) = divmod(parse_a1(a1), COLS), divmod(parse_a1(a2 or a1), COLS)
        return {(sh, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}

    mine = set().union(*(cells(x) for x in NEW))
    others = set().union(*(cells(x) for x in inputs if x not in NEW))
    retired = set().union(*(cells(x) for x in ex.RETIRED_INPUTS["tto"]))
    assert not mine & others and not mine & retired
    # nothing in the workbook's layout of the sheet stood there: the builder writes them empty, a style only
    sheet = service.books["tto"].model.sheet(ex.BULK_SHEET)
    for _, r, c in mine:
        rc = r * COLS + c
        assert rc not in sheet.fml and sheet.consts.get(rc) is None
    # each typed as the desk says it: "eur" is EURTRY, "Satış" / "s" SAT, "2,5mn" 2.500.000; anything else refused
    u = service.login("Toplu Girdi")["user"]
    try:
        put(service, u, {bulk("V", 1): "eur", bulk("W", 1): "Satış", bulk("W", 2): "b", bulk("X", 1): "2,5mn", bulk("Y", 1): "GARANTI"})
        assert [cell(service, bulk(c, 1), u) for c in "VWXY"] == ["EURTRY", "SAT", 2.5e6, "GARANTI"]
        assert cell(service, bulk("W", 2), u) == "AL"
        bad = service.set_inputs(u, "tto", [{"ref": bulk("V", 2), "value": "GBPTRY"}, {"ref": bulk("W", 3), "value": "pay"},
                                            {"ref": bulk("X", 3), "value": "on milyon"}])["errors"]
        assert len(bad) == 3 and "listede yok" in bad[0] and "tutar anlaşılamadı" in bad[2]
        # the panel takes them in: the range to Y, "İşleme al" in its header
        bk = next(p for p in service.view(u, "forward")["panels"] if p["id"] == "BK1")
        assert bk["range"] == "B1:Y106" and bk["action"] == "toplu-islem"
    finally:
        service.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- rows -> the paste
D1, D2 = serial("15.01.2027"), serial("15.04.2027")


def row(n, **kw):
    out = {"n": n, "ref": bulk("X", n), "date": None, "ret_mid": "", "manual": None, "eur_fwd": "", "usd_typed": None,
           "eur_typed": None, "pair": None, "dir": None, "amount": None, "cpt": None}
    out.update(kw)
    return out


ROWS = [row(1, date=D1, ret_mid=41.0712345678901, eur_fwd=59.58010914957011, dir="AL", amount=10e6, cpt="GARANTI"),
        row(2, date=D2, ret_mid=40.5, manual=41.25, eur_fwd=61.1234567890123, pair="EURTRY", dir="SAT", amount=2.5e6),
        row(3, date=D1, ret_mid=41.0, usd_typed=53.1, eur_typed=60.0, dir="SAT", amount=1234567.5),
        row(4, date=D2, ret_mid=41.0, manual=40.0, eur_fwd=61.0, usd_typed=53.2, pair="EURTRY", dir="AL", amount=1e6),
        row(5, date=D1, ret_mid=41.0, dir="AL", cpt="BEKLER"),                 # no Tutar: left out, counted
        row(6, dir="AL", amount=3e6),                                           # a Tutar without a valör: an error row
        row(7),                                                                 # an empty row: no row
        row(8, date=D2, ret_mid=41.0, amount=4e6),                              # no Yön: an error row
        row(9, ret_mid="", amount="")]                                          # (an amount cleared: no row)


def test_the_rows_as_a_paste():
    """Every row with a Tutar, a line each: the table's row, Parite (blank: USDTRY), Yön, Tutar, Valör, the price the
    row shows to its last digit (USDTRY: TRY faizi - Manuel TRY %, else RET mid %; EURTRY: its EURTRY fwd; a forward
    typed in the pair's own column: Forward kur), Karşı taraf, where it came from.  A row priced without a Tutar is left
    out and counted; one with a Tutar and no valör or Yön goes as it is - the dialog says what is missing."""
    p = entry.bulk_forward_paste(ROWS, "tr")
    lines = p["text"].split("\n")
    assert lines[0] == "Satır\tParite\tYön\tTutar\tValör\tTRY faizi\tForward kur\tKarşı taraf\tNot"
    assert lines[1:] == [
        "1\tUSDTRY\tAL\t10.000.000\t15.01.2027\t41,0712345678901%\t\tGARANTI\tTOPLU FORWARD · RET mid %",
        "2\tEURTRY\tSAT\t2.500.000\t15.04.2027\t\t61,1234567890123\t\tTOPLU FORWARD · Manuel TRY %",
        "3\tUSDTRY\tSAT\t1.234.567,5\t15.01.2027\t\t53,1\t\tTOPLU FORWARD · elle forward",
        "4\tEURTRY\tAL\t1.000.000\t15.04.2027\t\t61,0\t\tTOPLU FORWARD · Manuel TRY %",       # (R is USDTRY's: not this pair's)
        "6\tUSDTRY\tAL\t3.000.000\t\t\t\t\tTOPLU FORWARD · RET mid %",
        "8\tUSDTRY\t\t4.000.000\t15.04.2027\t41,0%\t\t\tTOPLU FORWARD · RET mid %"]
    assert (p["kind"], p["taken"], p["skipped"], p["row_title"]) == ("fwd", 6, 1, "Satır")
    assert p["amounts"] == {str(n): bulk("X", n) for n in (1, 2, 3, 4, 6, 8)}
    assert "Tutar'ı yazılı 6 satır · Tutar'ı boş 1 satır alınmadı" in p["said"]
    assert entry.bulk_forward_price(ROWS[0]) == ("try_rate", 41.0712345678901, "RET mid %")
    assert entry.bulk_forward_price(ROWS[1]) == ("forward", 61.1234567890123, "Manuel TRY %")
    # an ON karşılık % typed (anchor M; 26.11.2026) is no booking price: USDTRY at the Manuel TRY % it gives, EURTRY at
    # its EURTRY fwd - the note names the ON
    assert entry.bulk_forward_price(row(10, date=D1, ret_mid=41.0, manual=35.4246085717721, anchor="M")) == (
        "try_rate", 35.4246085717721, "ON karşılık %")
    assert entry.bulk_forward_price(row(11, date=D2, ret_mid=41.0, manual=35.4, eur_fwd=62.048, pair="EURTRY", anchor="M")) == (
        "forward", 62.048, "ON karşılık %")
    # English numbers for a user who works in English
    en = entry.bulk_forward_paste(ROWS[:3], "en")["text"].split("\n")
    assert en[1].split("\t")[3:6] == ["10,000,000", "15.01.2027", "41.0712345678901%"] and en[3].split("\t")[3] == "1,234,567.5"
    # the dialog reads it back as it is: the header found, "Satır" a column it does not read, each line the form's payload
    paste = entry.read_paste(p["text"], "fwd")
    assert paste["header"] and [c["field"] for c in paste["columns"]] == [None, "pair", "dir", "amount", "value_date", "try_rate",
                                                                         "forward", "cpt", "note"] and not paste["problems"]
    one = entry.row_payload("fwd", paste["columns"], paste["rows"][0]["cells"])
    assert one == {"pair": "USDTRY", "dir": "B", "value_date": "15.01.2027", "amount": "10.000.000", "manual": "41,0712345678901%",
                   "basis": "TRY", "cpt": "GARANTI", "note": "TOPLU FORWARD · RET mid %"}
    two = entry.row_payload("fwd", paste["columns"], paste["rows"][1]["cells"])
    assert (two["pair"], two["dir"], two["basis"], two["manual"]) == ("EURTRY", "S", "FWD", "61,1234567890123")
    for k, why in ((4, "valör yok"), (5, "yön yok")):
        with pytest.raises(entry.EntryError) as exc:
            entry.row_payload("fwd", paste["columns"], paste["rows"][k]["cells"])
        assert why in str(exc.value)
    # nothing to take: no text, and why
    none = entry.bulk_forward_paste([ROWS[4], ROWS[6]], "tr")
    assert (none["text"], none["taken"], none["skipped"]) == ("", 0, 1) and "Tutar'ı yazılı satır yok (valörü olan 1 satırın" in none["said"]


# ---------------------------------------------------------------------------------------------- the service
@pytest.fixture(scope="module")
def desk(module_service):
    """A user's table: USDTRY at RET mid / a manual rate / a typed forward, EURTRY at RET mid / a manual rate / a typed
    forward, a row priced and not to be booked, a Tutar without a valör, one without a Yön."""
    svc = module_service
    u = svc.login("Toplu İşlem")["user"]
    dates = ["15.01.2027", "15.03.2027", "15.06.2027", "15.02.2027", "14.05.2027", "15.09.2027", "15.12.2027", "", "17.01.2028"]
    cells = {bulk("B", k): d for k, d in enumerate(dates, 1) if d}
    cells.update({bulk("L", 2): "41,25", bulk("L", 5): "40,10"})
    cells.update({bulk("V", k): "EURTRY" for k in (4, 5, 6)})
    cells.update({bulk("W", k): w for k, w in enumerate(["AL", "SAT", "AL", "S", "Alış", "SAT", "AL", "AL"], 1)})
    cells.update({bulk("X", k): a for k, a in enumerate(["10m", "5.000.000", "2,5mn", "3m", "1m", "4m", "", "6m", "7m"], 1)})
    cells.update({bulk("Y", 1): "GARANTI", bulk("Y", 4): "AKBANK", bulk("Y", 7): "BEKLER"})
    put(svc, u, cells)
    # a forward typed in each pair's own column (and one in the other pair's: not this row's price)
    put(svc, u, {bulk("R", 3): cell(svc, bulk("N", 3), u) + 0.0125, bulk("T", 6): cell(svc, bulk("P", 6), u) - 0.02,
                 bulk("R", 4): 99.0})
    return svc, u


def test_each_row_books_at_the_price_it_shows(desk):
    """The dialog's own preview prices every line as the form does; each forward is the row's to 1e-9: USDTRY at its
    TRY rate gives the row's USDTRY fwd (the blotter's TRY-rate pricing is the workbook's bulk row, the same formula),
    EURTRY at its EURTRY fwd, a typed forward at itself.  The trade's TRY rate is the row's (EURTRY: backed out on the
    blotter's EUR rate, the middle of the EUR bid / ask - in the replay file every EUR MID is that middle, so it is the
    row's rate too)."""
    svc, u = desk
    src = svc.bulk_from_forward(u)
    assert (src["taken"], src["skipped"]) == (8, 1) and src["amounts"]["9"] == bulk("X", 9)
    p = svc.bulk_preview(u, "fwd", src["text"])
    assert (p["valid"], p["invalid"]) == (6, 2) and p["header"]
    by_row = {int(r["cells"][0]): r for r in p["rows"]}
    assert set(by_row) == {1, 2, 3, 4, 5, 6, 8, 9}
    assert "valör yok" in by_row[8]["error"] and "yön yok" in by_row[9]["error"]
    want = {1: ("USDTRY", "B", "N", "G", "TRY", "RET mid %"), 2: ("USDTRY", "S", "N", "L", "TRY", "Manuel TRY %"),
            3: ("USDTRY", "B", "R", None, "FWD", "elle forward"), 4: ("EURTRY", "S", "P", "G", "FWD", "RET mid %"),
            5: ("EURTRY", "B", "P", "L", "FWD", "Manuel TRY %"), 6: ("EURTRY", "S", "T", None, "FWD", "elle forward")}
    for k, (pair, side, fwd_col, rate_col, basis, source) in want.items():
        t = by_row[k]["trade"]
        assert (t["pair"], t["dir"], t["basis"], t["value_date"]) == (pair, side, basis, cell(svc, bulk("B", k), u)), k
        assert t["forward"] == pytest.approx(cell(svc, bulk(fwd_col, k), u), abs=1e-9), k
        if rate_col:
            assert t["try_rate"] * 100 == pytest.approx(cell(svc, bulk(rate_col, k), u), abs=1e-9), k
        assert t["note"] == "TOPLU FORWARD · " + source and t["amount"] == cell(svc, bulk("X", k), u)
    assert by_row[1]["trade"]["cpt"] == "GARANTI" and by_row[4]["trade"]["cpt"] == "AKBANK"
    # USDTRY's TRY-rate route is the table's own formula: the forward to the last bits, not only to 1e-9
    assert abs(by_row[1]["trade"]["forward"] - cell(svc, bulk("N", 1), u)) < 1e-12
    assert by_row[1]["trade"]["manual"] * 100 == pytest.approx(cell(svc, bulk("G", 1), u), abs=1e-12)
    # the other pair's typed forward is not this row's price (row 4: R typed, EURTRY row)
    assert by_row[4]["trade"]["forward"] != 99.0


def test_the_rows_kept_are_saved_in_one_go_and_their_tutar_emptied(desk):
    """"N satırı kaydet": the valid lines in one transaction, into today's book; the error lines never.  Then what the
    browser does: the Tutar of the lines kept - by their "Satır" - reset; the valör, rates, Parite, Yön and Karşı taraf
    stay, and a second press finds only the rows still to fix."""
    svc, u = desk
    src = svc.bulk_from_forward(u)
    p = svc.bulk_preview(u, "fwd", src["text"])
    before = len(svc.blotter(u)["trades"])
    res = svc.bulk_save(u, "fwd", src["text"], rows=[r["n"] for r in p["rows"] if r["ok"]])
    assert res["saved"] == 6 and len(res["left"]) == 2
    trades = svc.blotter(u)["trades"]
    assert len(trades) == before + 6
    mine = [t for t in trades[before:] if str(t.get("note", "")).startswith("TOPLU FORWARD · ")]
    assert len(mine) == 6 and {t["trade_date"] for t in mine} == {svc.today_iso()}
    # the browser's part: the kept lines' "Satır" -> their Tutar cells, reset
    k = p["head"].index(src["row_title"])
    refs = [src["amounts"][r["cells"][k]] for r in p["rows"] if r["n"] in res["rows"]]
    assert sorted(refs) == sorted(bulk("X", n) for n in range(1, 7))
    assert svc.reset_inputs(u, "tto", refs)["reset"] == 6
    assert [cell(svc, bulk("X", n), u) for n in range(1, 10)] == [None] * 6 + [None, 6e6, 7e6]
    assert [cell(svc, bulk(c, 1), u) for c in "VWY"] == [None, "AL", "GARANTI"] and cell(svc, bulk("B", 1), u) == serial("15.01.2027")
    assert (cell(svc, bulk("L", 2), u), cell(svc, bulk("V", 4), u)) == (41.25, "EURTRY")
    # a second press: only the two rows still to fix; the booked ones are priced rows without a Tutar now
    again = svc.bulk_from_forward(u)
    assert (again["taken"], again["skipped"], sorted(again["amounts"])) == (2, 7, ["8", "9"])


def test_a_row_whose_typed_value_is_its_on_books_the_try_rate_it_gives(module_service):
    """An ON karşılık % typed (the desk, 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek
    istiyorum"; the table is two-way): an ON is no booking price - the USDTRY row books the TRY rate the row shows, its
    Manuel TRY % worked out from the ON (the blotter prices the row's own USDTRY fwd from it, to the last bits; that rate's
    ON over the row's Gün is the ON typed), the EURTRY row its EURTRY fwd as before; the note: "· ON karşılık %"."""
    svc = module_service
    u = svc.login("Toplu ON")["user"]
    try:
        put(svc, u, {bulk("B", 1): "15.03.2027", bulk("B", 2): "15.06.2027", bulk("V", 2): "EURTRY", bulk("W", 1): "AL",
                     bulk("W", 2): "SAT", bulk("X", 1): "5m", bulk("X", 2): "2m"})
        put(svc, u, {bulk("M", 1): "33,75", bulk("M", 2): "34,125"})
        src = svc.bulk_from_forward(u)
        assert (src["taken"], src["skipped"]) == (2, 0)
        lines = {x.split("\t")[0]: x.split("\t") for x in src["text"].split("\n")[1:]}
        assert lines["1"][5:7] == [entry._plain(cell(svc, bulk("L", 1), u), "tr") + "%", ""]
        assert lines["2"][5:7] == ["", entry._plain(cell(svc, bulk("P", 2), u), "tr")]
        assert lines["1"][8] == lines["2"][8] == "TOPLU FORWARD · ON karşılık %"
        p = svc.bulk_preview(u, "fwd", src["text"])
        assert (p["valid"], p["invalid"]) == (2, 0), p
        by_row = {int(r["cells"][0]): r["trade"] for r in p["rows"]}
        one, two = by_row[1], by_row[2]
        assert (one["pair"], one["dir"], one["basis"], one["note"]) == ("USDTRY", "B", "TRY", "TOPLU FORWARD · ON karşılık %")
        assert one["try_rate"] * 100 == pytest.approx(cell(svc, bulk("L", 1), u), abs=1e-12)
        assert abs(one["forward"] - cell(svc, bulk("N", 1), u)) < 1e-12
        days = cell(svc, bulk("C", 1), u)
        assert 36000 * ((1 + one["try_rate"] * days / 360) ** (1 / days) - 1) == pytest.approx(33.75, abs=1e-9)
        assert (two["pair"], two["dir"], two["basis"], two["note"]) == ("EURTRY", "S", "FWD", "TOPLU FORWARD · ON karşılık %")
        assert two["forward"] == pytest.approx(cell(svc, bulk("P", 2), u), abs=1e-9)
    finally:
        svc.reset_inputs(u, "tto")


def test_over_http(desk):
    """The table's rows for the dialog: a signed-in user's own (in their number format); nobody else's, nothing without a
    session.  (Last: the HTTP part.)"""
    svc, u = desk
    client = TestClient(create_app(service=svc))                     # (no "with": the module's service stays up)
    h = auth(svc, "Toplu İşlem")
    r = client.get("/api/blotter/bulk/toplu-forward", headers=h)
    assert r.status_code == 200 and r.json()["taken"] == 2 and r.json()["text"].startswith("Satır\tParite\tYön\tTutar")
    en = client.get("/api/blotter/bulk/toplu-forward?lang=en", headers=h).json()["text"].split("\n")
    assert en[1].split("\t")[3] == "6,000,000"
    other = client.get("/api/blotter/bulk/toplu-forward", headers=auth(svc, "Toplu Başkası")).json()
    assert other["taken"] == 0 and other["text"] == ""
    assert client.get("/api/blotter/bulk/toplu-forward", headers=ANON).status_code == 401
