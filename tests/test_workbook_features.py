"""What the workbooks have besides formulas - hidden columns, frozen panes, cell comments, hyperlinks, a
picture, data bars, drop-down lists read from a range, the end-of-day macro - and its place in the dashboard."""
import datetime as dt
import os

import pytest

from conftest import cell
from helpers import mini_book, read_xlsx
from tto.render import Renderer
from tto.service import ServiceError
from tto.views import load_views
from tto.xl import numfmt
from tto.xl.errors import XlError
from tto.xl.model import COLS, Model, parse_a1, parse_range
from tto.xlsx import XlsxBook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TR = numfmt.get_locale("tr")


@pytest.fixture(scope="module")
def models():
    """The workbooks exactly as imported (without the dashboard's own sheets)."""
    return {name: Model.load(os.path.join(ROOT, "models", name + ".json.gz")) for name in ("tto", "sofr", "borsa", "asw")}


def panel(svc, view_id, panel_id, show_hidden=False, user=None):
    return next(p for p in svc.view(user, view_id, show_hidden)["panels"] if p["id"] == panel_id)


# ---------------------------------------------------------------------------------------------- import
def test_what_excel_hides_and_pins_is_imported(models):
    tto, sofr = models["tto"], models["sofr"]
    assert tto.sheet("YP DIBS").hidden_cols == [[4, 4], [5, 5]]                 # Bid and Bid Yield
    assert tto.sheet("VIOP").hidden_cols == [[3, 3], [9, 9], [10, 10]]
    assert tto.sheet("YP DIBS").col_hidden(4) and not tto.sheet("YP DIBS").col_hidden(6)
    assert tto.sheet("OIS_MAIN").hidden_rows == [[132, 286], [288, 333], [335, 439], [441, 458]]
    assert tto.sheet("OIS_MAIN").row_hidden(200) and not tto.sheet("OIS_MAIN").row_hidden(131)
    assert len(tto.sheet("VIOP").hidden_rows) == 16
    assert tto.sheet("DİBS RV").freeze == [4, 3] and tto.sheet("MASA").freeze == [2, 0]
    assert sofr.sheet("SOFR_FOMC").freeze == [2, 1] and sofr.sheet("SOFR_FOMC").hidden_cols == [[47, 67]]
    assert tto.sheet("Calculators").freeze == [0, 0] and tto.sheet("Calculators").hidden_cols == []


def test_comments_hyperlinks_picture_and_data_bars_are_imported(models):
    tto, sofr = models["tto"], models["sofr"]
    notes = tto.sheet("OIS_MAIN").comments
    assert {a for a in ("B3", "D3", "H3", "J3", "F4", "H4")} == {"%s%d" % (chr(64 + rc % COLS), rc // COLS) for rc in notes}
    assert notes[parse_a1("B3")] == "1 = OIS ima patikası, 0 = TLREF sabit"
    assert tto.sheet("VIOP").comments[parse_a1("K107")].endswith("1M USD için")
    assert sum(len(sh.comments) for sh in tto.sheets) == 7
    links = tto.sheet("MASA").links
    assert len(links) == 30 and links[0] == {"ref": "P1", "location": "'OIS_MAIN'!A7", "display": "Outright"}
    assert sum(len(sh.links) for sh in tto.sheets) == 30
    (img,) = tto.sheet("Ivır Zıvır").images
    assert img["mime"] == "image/png" and img["anchor"] == [66, 8, 71, 21] and img["width"] == 1366 and img["height"] == 93
    bars = [r for r in sofr.sheet("SOFR_FOMC").cf if r["type"] == "dataBar"]
    assert sorted(r["sqref"] for r in bars) == ["L20:L29", "L34:L43", "L5:L14", "M74:M83"]
    assert bars[0]["bar"]["cfvo"] == [["num", "0"], ["max", None]] and bars[0]["bar"]["min"] == 10 and bars[0]["bar"]["max"] == 90
    assert not any(r["type"] == "dataBar" for sh in tto.sheets for r in sh.cf)


def test_a_model_round_trips_the_new_fields(models, tmp_path):
    path = str(tmp_path / "copy.json.gz")
    models["tto"].save(path)
    again = Model.load(path)
    for name in ("MASA", "OIS_MAIN", "VIOP", "YP DIBS", "Ivır Zıvır", "DİBS RV"):
        a, b = models["tto"].sheet(name), again.sheet(name)
        for field in ("hidden_rows", "hidden_cols", "freeze", "links", "comments", "images", "charts"):
            assert getattr(a, field) == getattr(b, field), (name, field)


# ---------------------------------------------------------------------------------------------- hidden columns
def test_columns_hidden_in_excel_are_left_out_until_asked_for(service):
    # the USD OIS table of the VİOP sheet: Excel hides its ticker column (C)
    curve = panel(service, "viop", "B2")["data"]
    assert curve["c"] == ["B", "D", "E", "F", "G"] and curve["hc"] == 1
    assert [c["t"] for c in curve["rows"][0] if c.get("t")] == ["Maturity", "Bid", "Mid", "Ask"]
    full = panel(service, "viop", "B2", show_hidden=True)["data"]
    assert full["c"] == ["B", "C", "D", "E", "F", "G"] and "hc" not in full
    assert "Ticker" in [c.get("t") for c in full["rows"][0]] and full["rows"][1][1]["t"] == "USSO1Z"
    # tables without hidden columns are untouched
    outright = panel(service, "ois", "B3")["data"]
    assert outright["c"][:3] == ["A", "B", "C"] and "hc" not in outright
    # the explorer and the single-range API always show everything
    assert service.grid(None, "tto", "VIOP", "B14:G35")["data"]["c"] == ["B", "C", "D", "E", "F", "G"]


def test_hidden_columns_shrink_merged_cells_and_keep_a_fully_hidden_range():
    book = mini_book({"A1": "başlık", "A2": 1, "B2": 2, "C2": 3, "D2": 4}, hidden_cols=[[2, 3]], merges=["A1:D1"])
    R = Renderer(book)
    t = R.table(book.engine.shared, "S", "A1:D2", TR, None, show_hidden=False)
    assert t["c"] == ["A", "D"] and t["hc"] == 2
    assert t["rows"][0][0]["cs"] == 2 and t["rows"][0][1] == {"sk": 1}          # the caption now spans what is left
    assert [c["t"] for c in t["rows"][1]] == ["1", "4"]
    t = R.table(book.engine.shared, "S", "A1:D2", TR, None)                     # default: everything
    assert t["c"] == ["A", "B", "C", "D"] and t["rows"][0][0]["cs"] == 4 and "hc" not in t
    # a range that lies in hidden columns as a whole is a helper table: shown as it is
    t = R.table(book.engine.shared, "S", "B2:C2", TR, None, show_hidden=False)
    assert t["c"] == ["B", "C"] and "hc" not in t


def test_a_merged_caption_keeps_its_span_when_an_empty_column_is_trimmed():
    book = mini_book({"A1": "başlık", "A2": 1, "C2": 3}, merges=["A1:C1"])
    t = Renderer(book).table(book.engine.shared, "S", "A1:C2", TR, None)
    assert t["c"] == ["A", "C"] and t["rows"][0][0]["cs"] == 2


# ---------------------------------------------------------------------------------------------- frozen panes
def test_frozen_columns_are_reported_for_the_tables_that_contain_them(service):
    assert panel(service, "dibs", "B3")["data"]["fz"] == 3                      # A:C of the bond table
    assert panel(service, "dibs", "B3")["data"]["c"][:3] == ["A", "B", "C"]
    fomc = panel(service, "usd", "fomc")["data"]
    assert fomc["c"][0] == "A" and fomc["fz"] == 1
    assert "fz" not in panel(service, "usd", "spr")["data"]                    # starts right of the frozen column
    masa = [p["data"] for p in service.view(None, "masa")["panels"] if p["type"] == "table"]
    assert masa and not any("fz" in d for d in masa)                           # rows only: header rows are sticky anyway


def test_frozen_column_count_follows_what_is_shown():
    cells = {"A1": "a", "B1": "b", "C1": "c", "D1": "d"}
    book = mini_book(cells, freeze=[0, 2])
    R = Renderer(book)
    assert R.table(book.engine.shared, "S", "A1:D1", TR, None)["fz"] == 2
    assert "fz" not in R.table(book.engine.shared, "S", "C1:D1", TR, None)
    assert "fz" not in R.table(book.engine.shared, "S", "A1:B1", TR, None)      # nothing left to scroll
    book = mini_book(cells, freeze=[0, 2], hidden_cols=[[2, 2]])
    assert Renderer(book).table(book.engine.shared, "S", "A1:D1", TR, None, show_hidden=False)["fz"] == 1


# ---------------------------------------------------------------------------------------------- comments / bars
def test_cell_comments_travel_with_the_cell(service):
    params = panel(service, "ois", "B1")["data"]
    notes = {(params["c"][j] + str(params["r"][i])): c["n"] for i, row in enumerate(params["rows"])
             for j, c in enumerate(row) if c.get("n")}
    assert set(notes) == {"B3", "D3", "H3", "J3", "F4", "H4"}
    assert notes["J3"] == "Carry & roll: 1 receive, −1 pay"
    assert service.cell_info(None, "tto", "VIOP!K107")["cell"]["n"].endswith("1M USD için")
    assert "n" not in service.cell_info(None, "tto", "VIOP!K108")["cell"]


def test_data_bars_measure_the_value_between_the_rules_limits(service):
    best = panel(service, "usd", "top")["data"]                                # F3:N14, bars on L5:L14 (0 ... max)
    col = best["c"].index("L")
    cells = [row[col] for i, row in enumerate(best["rows"]) if 5 <= best["r"][i] <= 14]
    assert len(cells) == 10 and all("bar" in c and c["bc"] == "pos" for c in cells)
    values = [c["v"] for c in cells]
    top = max(values)
    for c in cells:
        expect = 10 + 80 * max(0.0, c["v"]) / top                              # 10 % for the smallest bar, 90 % for the largest
        assert c["bar"] == pytest.approx(expect, abs=0.06)
    assert max(c["bar"] for c in cells) == 90.0
    steps = panel(service, "usd", "fomc")["data"]
    col = steps["c"].index("M")
    bars = [row[col] for i, row in enumerate(steps["rows"]) if 74 <= steps["r"][i] <= 83]
    assert all(c["bc"] == "info" and 10 <= c["bar"] <= 90 for c in bars)
    assert "bar" not in best["rows"][2][0]


def test_data_bar_limits():
    cells = {"A1": 0, "A2": 5, "A3": 10, "A4": -4, "A5": "metin"}
    rule = {"sqref": "A1:A5", "type": "dataBar", "op": None, "priority": 1, "dxf": None, "text": None, "anchor": parse_a1("A1"),
            "formulas": [], "stop": False, "bar": {"cfvo": [["min", None], ["max", None]], "color": "63BE7B", "min": 10, "max": 90}}
    book = mini_book(cells, cf=[rule])
    t = Renderer(book).table(book.engine.shared, "S", "A1:A5", TR, None)
    bars = [row[0].get("bar") for row in t["rows"]]
    assert bars == [pytest.approx(10 + 80 * 4 / 14, abs=0.06), pytest.approx(10 + 80 * 9 / 14, abs=0.06), 90.0, 10.0, None]
    rule["bar"]["cfvo"] = [["num", "0"], ["num", "20"]]                         # fixed limits: below the low end = shortest bar
    book = mini_book(cells, cf=[rule])
    bars = [row[0].get("bar") for row in Renderer(book).table(book.engine.shared, "S", "A1:A5", TR, None)["rows"]]
    assert bars == [10.0, 30.0, 50.0, 10.0, None]
    rule["bar"]["cfvo"] = [["percent", "50"], ["max", None]]
    book = mini_book(cells, cf=[rule])
    bars = [row[0].get("bar") for row in Renderer(book).table(book.engine.shared, "S", "A1:A5", TR, None)["rows"]]
    assert bars[2] == 90.0 and bars[0] == 10.0 and bars[1] == pytest.approx(10 + 80 * 2 / 7, abs=0.06)


# ---------------------------------------------------------------------------------------------- shortcuts / picture
def test_the_workbooks_go_to_links_become_shortcuts_to_page_and_panel(service):
    links = service.view(None, "masa")["links"]
    assert len(links) == 29                               # 30 in the workbook; the one to YP DIBS went with that sheet
    by = {l["label"]: l for l in links}
    assert (by["Outright"]["page"], by["Outright"]["panel"]) == ("ois", "B3")
    assert (by["MPC ima"]["page"], by["MPC ima"]["panel"]) == ("ois", "B4")
    assert (by["Matrisler"]["page"], by["Matrisler"]["panel"]) == ("viop", "B17")
    assert (by["Blotter"]["page"], by["Blotter"]["panel"]) == ("blotter", None)
    assert by["Makro"]["page"] == "masa" and "YP DİBS" not in by
    assert by["DİBS RV"]["page"] == "dibs" and by["DİBS RV"]["ref"].startswith("'DİBS RV'!")
    views = {v["id"]: v for v in load_views()}
    pages = {p["id"] for p in service.nav()}
    for l in links:
        assert l["page"] in pages, l
        if l["page"] != "blotter":
            target = next(p for p in views[l["page"]]["panels"] if p["id"] == l["panel"])
            assert target["type"] in ("table", "notes") and not target.get("hidden"), l       # a panel the page really shows
            sheet, _, addr = l["ref"].rpartition("!")
            assert views[l["page"]]["sheet"] == sheet.strip("'")
    assert "links" not in service.view(None, "ois")                             # only the desk sheet has them


def test_a_picture_on_a_sheet_is_served(service, models, monkeypatch):
    """The workbook's only picture was on the "Ivır Zıvır" sheet, which the dashboard takes out as it loads: no
    picture is left.  A sheet with one would have it served (here the picture is put on MASA for the test; a
    page that showed a sheet with pictures would list them as panels)."""
    assert not any(sh.images for sh in service.books["tto"].model.sheets)
    assert not any(p["type"] == "image" for v in service.views for p in service.view(None, v["id"])["panels"])
    monkeypatch.setattr(service.books["tto"].model.sheet("MASA"), "images", list(models["tto"].sheet("Ivır Zıvır").images))
    raw, mime = service.image("tto", "MASA", 0)
    assert mime == "image/png" and raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) > 5000
    for args in (("tto", "MASA", 1), ("tto", "MASA", -1), ("tto", "Yok", 0), ("tto", "Ivır Zıvır", 0), ("tto", "VIOP", 0)):
        with pytest.raises(ServiceError) as exc:
            service.image(*args)
        assert exc.value.status == 404


def test_groups_collapsed_in_excel_start_collapsed(models):
    """A table whose rows Excel keeps folded away (an outline group, collapsed) opens on request here too."""
    checked = 0
    for v in load_views():
        model = models[v["book"]]
        for p in v["panels"]:
            if p["type"] != "table" or p.get("hidden") or p.get("sheet", v["sheet"]) not in model.sheet_index:
                continue                                                        # (a sheet the dashboard added itself)
            sheet = model.sheet(p.get("sheet", v["sheet"]))
            r1, _, r2, _ = parse_range(p["range"])
            rows = r2 - r1 + 1
            folded = sum(1 for r in range(r1, r2 + 1) if sheet.row_hidden(r))
            if rows > 2 and folded >= rows - 2:
                assert p.get("collapsed"), (v["id"], p["id"])
                checked += 1
    assert checked == 20                                                        # OIS: 4 lists, VİOP: 15 matrices + BFX check


# ---------------------------------------------------------------------------------------------- drop-down lists
def test_every_drop_down_of_the_workbooks_is_a_menu(service):
    missing = []
    for bid, book in service.books.items():
        calc = book.engine.shared
        for si, sh in enumerate(book.model.sheets):
            for v in sh.validations:
                if v.get("type") != "list":
                    continue
                for part in v["sqref"].split():
                    r1, c1, r2, c2 = parse_range(part)
                    for rc in (r1 * COLS + c1, r2 * COLS + c2):
                        if (si, rc) not in book.inputs or not service.et.call(book.options_for, si, rc, calc):
                            missing.append((bid, sh.name, part))
    assert missing == []


def test_a_list_read_from_a_range_offers_the_cells_of_that_range(service):
    pivot = service.cell_info(None, "tto", "DV01_RISK!F3")["cell"]            # list: =$B$6:$B$25
    assert pivot["o"][:4] == ["ON", "SN", "1W", "2W"] and pivot["t"] in pivot["o"] and len(pivot["o"]) == 20
    near = service.cell_info(None, "tto", "VIOP!L331")["cell"]                # list: =$L$97:$X$97
    assert near["o"][0] == "Spot" and len(near["o"]) == 13
    assert service.cell_info(None, "tto", "MASA!Q100")["cell"]["o"][:2] == ["USD", "EUR"]      # literal lists as before


# ---------------------------------------------------------------------------------------------- paste
def test_a_block_from_excel_skips_what_is_not_an_input(module_service):
    svc = module_service
    u = svc.login("Yapıştır")["user"]
    # B16:D17 of VIOP as Excel copies it: days (formula) | Ticker (hidden input) | Maturity (input)
    items = [{"ref": "VIOP!%s%d" % (col, row), "value": val}
             for row, vals in ((16, ["7", "USSO2Z", "2W"]), (17, ["14", "USSO1Z", "1W"]))
             for col, val in zip("BCD", vals)]
    res = svc.set_inputs(u, "tto", items, False, "tr", True)
    assert (res["applied"], res["skipped"], res["errors"]) == (4, 2, [])
    assert cell(svc, "VIOP!C16", u) == "USSO2Z" and cell(svc, "VIOP!D17", u) == "1W"
    assert cell(svc, "VIOP!C16") == "USSO1Z"                                     # other users are untouched
    # typing into a cell that is not an input is still an error
    res = svc.set_inputs(u, "tto", [{"ref": "VIOP!B16", "value": "1"}])
    assert res["applied"] == 0 and "skipped" not in res and "girdi hücresi değil" in res["errors"][0]


# ---------------------------------------------------------------------------------------------- end-of-day archive
def test_xlsx_writer_round_trip():
    wb = XlsxBook()
    ws = wb.add_sheet("Günlük İşlemler")
    ws.set(1, 1, "Başlık & <özet>", bold=True)
    ws.set(2, 1, 1234.5, fmt="#,##0.00")
    ws.set(2, 2, 0.355, fmt="0.00%")
    ws.set(3, 1, True)
    ws.set(3, 2, XlError("#N/A"))
    ws.set(4, 1, 46402.0, fmt="dd.mm.yyyy", align="center")
    ws.set(5, 1, 7)
    ws.set(6, 1, None)                                                          # nothing to write
    ws.set(6, 2, "a\x07b")                                                      # control characters cannot be stored
    ws.merges = ["A1:B1"]
    ws.freeze = (2, 1)
    ws.widths = {1: 20.0}
    other = wb.add_sheet("a/b:c*d?e[f]")
    other.row(1, 1, ["x", 2.0, None, "y"], fill="E7E6E6")
    other.autosize()
    assert wb.add_sheet("günlük işlemler").name == "günlük işlemler (2)"         # names are unique without regard to case
    book = read_xlsx(wb.to_bytes())
    assert list(book) == ["Günlük İşlemler", "a b c d e f", "günlük işlemler (2)"]
    s = book["Günlük İşlemler"]
    assert s["A1"] == "Başlık & <özet>" and s["A2"] == 1234.5 and s["B2"] == 0.355 and s["A3"] is True and s["B3"] == "#N/A"
    assert s["A4"] == 46402.0 and s["A5"] == 7.0 and "A6" not in s and s["B6"] == "ab"
    assert s["!formats"]["A2"] == "#,##0.00" and s["!formats"]["B2"] == "0.00%" and s["!formats"]["A4"] == "dd.mm.yyyy"
    assert s["!formats"]["A1"] == "General" and s["!merges"] == ["A1:B1"] and s["!pane"] == "B3"
    assert book["a b c d e f"]["A1"] == "x" and book["a b c d e f"]["D1"] == "y" and "C1" not in book["a b c d e f"]
    assert read_xlsx(XlsxBook().to_bytes()) == {"Sayfa1": {"!formats": {}, "!merges": [], "!pane": None}}


@pytest.fixture(scope="module")
def blotter(module_service):
    svc = module_service
    a, b = svc.login("Arşiv A")["user"], svc.login("Arşiv B")["user"]
    f1 = svc.add_forward(a, {"dir": "B", "amount": "10m", "value_date": "15.12.2026", "basis": "RET_MID", "cpt": "ABC", "note": "ilk"})
    f2 = svc.add_forward(b, {"dir": "S", "amount": 4e6, "value_date": "15.12.2026", "basis": "TRY", "manual": "36,5"})
    o = svc.add_ois(b, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": "25", "dv01": 1000, "cpt": "XYZ"})
    svc.add_bond(a, {"instrument": "TRT150328T24", "dir": "B", "amount": "50m", "price": "98,25"})
    return svc, a, b, f1, f2, o


def test_the_days_blotter_downloads_as_the_macro_saved_it(blotter):
    svc, a, b, f1, f2, o = blotter
    today = dt.date.today()
    raw, name = svc.blotter_export(a)
    assert name == "Blotter_%s.xlsx" % today.strftime("%Y.%m.%d")              # the macro's own file name
    book = read_xlsx(raw)
    assert list(book) == ["Günlük İşlemler", "İşlem listesi"]
    sheet = book["Günlük İşlemler"]
    # the sheet in Excel's own layout: captions, the three input lists, every computed cell - as values
    assert sheet["B1"] == "USDTRY Forward" and sheet["A2"] == "Yön" and sheet["Y2"] == "Enstrüman"
    assert (sheet["A3"], sheet["B3"], sheet["C3"], sheet["D3"]) == ("B", 10e6, f1["try_rate"], f1["value_date"])
    assert (sheet["A4"], sheet["B4"], sheet["C4"]) == ("S", 4e6, 0.365)
    assert sheet["L3"] == "1Y" and sheet["M3"] == "XYZ" and sheet["Y3"] == "TRT150328T24" and sheet["AA3"] == 98.25
    for ref in ("E3", "F3", "F4", "Q20", "S20", "P20", "U20", "Q44", "R44"):
        v = cell(svc, "Günlük İşlemler!" + ref)
        assert sheet[ref] == pytest.approx(v, rel=1e-12), ref
    assert sheet["P20"] == 6e6 and sheet["Q44"] == 50e6                         # net USD bought, bond bought
    assert sheet["!pane"] == "A3" and "B1:D1" in sheet["!merges"] and len(sheet["!merges"]) == 16
    fm = sheet["!formats"]
    assert fm["C3"] == "0.00%" and "yyyy" in fm["D3"] and fm["B3"].startswith("#,##0")
    assert fm["B4"] == fm["B3"] and fm["D4"] == fm["D3"]                        # list rows look like the list's first row
    # no formula anywhere: every cell is a value
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert b"<f>" not in zf.read("xl/worksheets/sheet1.xml") and b"<f " not in zf.read("xl/worksheets/sheet1.xml")
    # the trade list: who, when, what - and the cost of the net positions
    lst = book["İşlem listesi"]
    assert lst["A1"] == "Günlük İşlemler · %s" % today.strftime("%d.%m.%Y") and "Arşiv A" in lst["A2"]
    assert lst["A4"] == "Forward" and lst["B6"] == "Arşiv A" and lst["C6"] == "ALIŞ" and lst["D6"] == 10e6
    assert (lst["P5"], lst["P6"], lst["P7"]) == ("Parite", "USDTRY", "USDTRY")       # the pair comes after the columns that were there
    assert lst["H6"] == f1["forward"] and lst["I6"] == f1["tl"] and lst["J6"] == "RET mid" and lst["K6"] == "ABC" and lst["L6"] == "ilk"
    assert lst["B7"] == "Arşiv B" and lst["C7"] == "SATIŞ" and lst["J7"] == "TRY faizi" and lst["G7"] == 0.365
    texts = [v for k, v in lst.items() if isinstance(v, str)]
    assert o["label"] in texts and "Kısa" in texts and "Uzun" in texts and "TRT150328T24" in texts
    assert "Forward · pozisyon ve maliyet" in texts and "OIS · pozisyon ve maliyet" in texts
    assert lst["!formats"]["D6"] == "#,##0" and lst["!formats"]["E6"] == "dd.mm.yyyy" and lst["!formats"]["G6"] == "0.000%"


def test_the_archive_works_without_a_user_and_refuses_a_bad_date(blotter):
    svc = blotter[0]
    raw, name = svc.blotter_export(None, dt.date.today().isoformat())
    assert "Dışa aktarım" in read_xlsx(raw)["İşlem listesi"]["A2"] and name.startswith("Blotter_")
    with pytest.raises(ServiceError):
        svc.blotter_export(None, "dün")


def test_a_past_day_is_archived_from_what_was_saved_that_day(blotter):
    svc, a, b, f1, f2, o = blotter
    today = dt.date.today().isoformat()
    svc.blotter(a)                                                              # the day's snapshot is written on view
    snap = svc.store.blotter_snapshot(today)
    assert {(r, c): v for r, c, v in snap["cells"]}[(3, 2)] == 10e6 and len(snap["cells"]) > 400
    # move the day into the past: same trades, same snapshot, another date
    svc.store._x("UPDATE trades SET trade_date='2026-02-03' WHERE trade_date=?", (today,))
    svc.store._x("UPDATE blotter_snapshots SET trade_date='2026-02-03' WHERE trade_date=?", (today,))
    try:
        svc._sync_blotter() if hasattr(svc, "_sync_blotter") else None
        assert svc.blotter(a)["trades"] == [] and cell(svc, "Günlük İşlemler!A3") is None       # today starts empty
        raw, name = svc.blotter_export(a, "2026-02-03")
        assert name == "Blotter_2026.02.03.xlsx"
        book = read_xlsx(raw)
        sheet = book["Günlük İşlemler"]
        assert (sheet["A3"], sheet["B3"], sheet["A4"], sheet["B4"]) == ("B", 10e6, "S", 4e6)
        assert sheet["P20"] == 6e6 and sheet["Q44"] == 50e6 and sheet["E3"] == f1["days"]
        assert book["İşlem listesi"]["A1"] == "Günlük İşlemler · 03.02.2026" and book["İşlem listesi"]["D6"] == 10e6
        # a day saved before whole-sheet snapshots existed: captions, the trades and the saved summary tables
        old = dict(snap)
        old.pop("cells")
        old.pop("snapshot_at", None)
        svc.store.save_blotter_snapshot("2026-02-03", old)
        legacy = read_xlsx(svc.blotter_export(a, "2026-02-03")[0])["Günlük İşlemler"]
        assert (legacy["A3"], legacy["B3"], legacy["D3"], legacy["Y3"]) == ("B", 10e6, f1["value_date"], "TRT150328T24")
        assert legacy["B1"] == "USDTRY Forward" and legacy["P20"] == 6e6 and legacy["Q44"] == 50e6
        assert "E3" not in legacy                                               # per-trade formulas were not saved then
    finally:
        svc.store._x("UPDATE trades SET trade_date=? WHERE trade_date='2026-02-03'", (today,))
        svc.store._x("DELETE FROM blotter_snapshots WHERE trade_date='2026-02-03'")
        svc.et.call(svc._sync_blotter)


def test_the_snapshot_is_written_only_when_something_changed(blotter):
    svc, a = blotter[0], blotter[1]
    today = dt.date.today().isoformat()
    svc.blotter(a)
    first = svc.store.blotter_snapshot(today)["snapshot_at"]
    writes = []
    original = svc.store.save_blotter_snapshot
    svc.store.save_blotter_snapshot = lambda *args: (writes.append(args[0]), original(*args))[1]
    try:
        svc.blotter(a)
        svc.blotter(None)
        assert writes == []
        svc.add_bond(a, {"instrument": "TRT150328T24", "dir": "S", "amount": "1m", "price": "98,50"})
        svc.blotter(a)
        assert writes == [today]
    finally:
        svc.store.save_blotter_snapshot = original
    assert svc.store.blotter_snapshot(today)["snapshot_at"] >= first


# ---------------------------------------------------------------------------------------------- panel texts
def test_captions_and_remarks_kept_in_cells_reach_their_panels(service):
    """The workbook explains its charts and tables in cells next to them: the caption above becomes the
    panel title, the remark below its note."""
    masa = {p["id"]: p for p in service.view(None, "masa")["panels"]}
    assert masa["chart4"]["title"] == "FRA EĞRİSİ · TRY OIS 3M (bootstrap) · oran ACT/365 ve O/N eşleniği 360"      # MASA!B72
    assert masa["chart5"]["title"].startswith("FRA EĞRİSİ · OFFSHORE 1Y (XCCY)")                                    # MASA!P72
    assert masa["chart4"]["note"].startswith("OIS 3M FRA = (DF_a/DF_b − 1)/τ")                                       # MASA!B90
    assert masa["chart0"]["title"] == "Oranlar (360 basit)" and not masa["chart0"]["note"]                           # the chart's own title
    dv01 = {p["id"]: p for p in service.view(None, "dv01")["panels"]}
    assert dv01["B18"]["note"].startswith("Birinci derece; büyük hareketli günlerde konveksite")                     # DV01_RISK!B145
    usd = service.view(None, "usd")["panels"][0]
    assert usd["type"] == "notes" and [c["t"] for c in usd["data"]["rows"][0] if c.get("t")] == [
        "USD OIS · FOMC ima patikası ve işlem seçici", "Bootstrap forward (WIRP mantığı) · senaryo görüşü → işlem önerisi"]


def test_long_helper_tables_show_their_first_rows_and_point_to_the_explorer(service):
    shown = {p["id"]: p for p in service.view(None, "borsa")["panels"]}
    assert "d0" not in shown                                                            # helper tables come on request
    helpers = {p["id"]: p for p in service.view(None, "borsa", True)["panels"]}
    d0 = helpers["d0"]
    assert d0["data"]["sheet"] == "Sheet1" and d0["data"]["r"][0] == 2 and d0["data"]["r"][-1] == 61
    assert d0["note"] == "İlk 60 satır gösteriliyor (toplam 403). Tamamı: Sayfa gezgini → Sheet1!A2:L404"
    assert helpers["t0"]["note"].startswith("BID % / ASK %")                             # a short table keeps its own note
    # the explorer serves the whole block
    full = service.grid(None, "borsa", "Sheet1", "A2:L404")["data"]
    assert full["r"][-1] == 404 and len(full["rows"]) == 403


def test_workbooks_without_recorded_data_say_so_offline(service):
    assert service.books["tto"].recorded and service.books["sofr"].recorded
    assert not service.books["borsa"].recorded and not service.books["asw"].recorded
    assert not service.books["borsa"].replay and service.books["tto"].replay           # only recorded values are frozen
    assert "ÖRNEK" in service.view(None, "borsa")["note"]
    assert "DİBS RV" in service.view(None, "asw")["note"] and "canlı" in service.view(None, "asw")["note"]
    assert service.view(None, "masa")["note"] is None


# ---------------------------------------------------------------------------------------------- password to open
def test_a_workbook_with_a_password_to_open_is_imported_with_that_password(tmp_path):
    """BBG_Borsa_Swap.xlsx is saved with a password to open: such a file is an encrypted container, opened in
    memory when the password is given - and refused with a clear message otherwise."""
    pytest.importorskip("msoffcrypto")
    from msoffcrypto.format.ooxml import OOXMLFile
    from tto.xl.importer import WorkbookLocked, import_workbook, open_workbook
    wb = XlsxBook()
    ws = wb.add_sheet("Kota")
    ws.set(1, 1, "Vade")
    ws.set(2, 1, 7)
    ws.set(2, 2, 0.345, fmt="0.00%")
    # (the encrypting side of the library wants whole 4096-byte segments: pad the archive with a comment)
    import io
    import zipfile
    raw = io.BytesIO(wb.to_bytes())
    with zipfile.ZipFile(raw, "a") as zf:
        zf.comment = b" " * ((-len(raw.getvalue())) % 4096)
    assert len(raw.getvalue()) % 4096 == 0
    plain = tmp_path / "acik.xlsx"
    plain.write_bytes(raw.getvalue())
    locked = tmp_path / "sifreli.xlsx"
    with open(plain, "rb") as src, open(locked, "wb") as dst:
        OOXMLFile(src).encrypt("s1nama-şifresi", dst)
    assert locked.read_bytes()[:4] == b"\xd0\xcf\x11\xe0" and not locked.read_bytes().startswith(b"PK")
    model = import_workbook(str(locked), password="s1nama-şifresi")
    sh = model.sheet("Kota")
    assert sh.consts[parse_a1("A1")] == "Vade" and sh.consts[parse_a1("A2")] == 7.0 and sh.consts[parse_a1("B2")] == 0.345
    assert model.numfmts[sh.styles[parse_a1("B2")]] == "0.00%"
    assert import_workbook(str(plain), password="gereksiz").sheet("Kota").consts == sh.consts      # an open file ignores it
    with pytest.raises(WorkbookLocked) as exc:
        import_workbook(str(locked))
    assert "--password" in str(exc.value)
    with pytest.raises(WorkbookLocked) as exc:
        open_workbook(str(locked), "yanlış")
    assert "açılamadı" in str(exc.value)
    assert sorted(os.listdir(tmp_path)) == ["acik.xlsx", "sifreli.xlsx"]                # nothing was decrypted to disk
