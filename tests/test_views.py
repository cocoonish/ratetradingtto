"""Page definitions are consistent with the workbooks they show."""
import pytest

from tto.books import BOOKS, load_books
from tto.service import ServiceError
from tto.views import load_views
from tto.xl.model import COLS, parse_range
from tto.xl.tokenizer import col_to_index
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS = load_views()


@pytest.fixture(scope="module")
def models():
    """The four workbooks as the dashboard loads them (with its own sheets, ``tto/extras.py``)."""
    books = load_books(os.path.join(ROOT, "models"))
    assert set(books) == {b[0] for b in BOOKS} == {"tto", "sofr", "borsa", "asw"}
    return {bid: b.model for bid, b in books.items()}


def sheets_of(view):
    """The sheets a page shows: its own and those of panels that name another one (not a "borrowed" panel:
    a few cells of another page's sheet, such as the manual spot on the Masa page)."""
    return {view["sheet"]} | {p["sheet"] for p in view["panels"] if p.get("sheet") and not p.get("borrowed")}


#: sheets without a page of their own (the sheet explorer shows them): the order of the pricing sources and the USD /
#: EUR holiday lists, which are on the settings page - and the curve between quoted tenors (Ayarlar → Eğri
#: interpolasyonu: the choice and the PPK cells the service fills, in the TRY and the ASW workbook)
NO_PAGE = {("tto", "EK_KAYNAK"), ("tto", "EK_TATIL"), ("tto", "EK_INTERP"), ("asw", "EK_INTERP")}


def test_every_sheet_of_the_workbooks_has_a_page(models):
    covered = {(v["book"], name) for v in VIEWS for name in sheets_of(v)}
    for book, model in models.items():
        for sh in model.sheets:
            if sh.name == "Günlük İşlemler":
                continue                        # has its own page (the blotter)
            if (book, sh.name) in NO_PAGE:
                assert (book, sh.name) not in covered
                continue
            assert (book, sh.name) in covered, sh.name
    assert not {"mobil", "ivir", "ypdibs", "iyix"} & {v["id"] for v in VIEWS}


def test_the_sheets_without_a_page_are_in_the_sheet_explorer(service):
    names = [s["name"] for s in service.sheets("tto")]
    for _, name in NO_PAGE:
        assert name in names
    grid = service.grid(None, "tto", "EK_KAYNAK", "A1:G6")
    assert grid["data"]["rows"][0][0]["t"]
    # a link of the desk sheet to a sheet without a page is simply not offered
    assert all(l["page"] in service.view_index or l["page"] == "blotter" for l in service.view(None, "masa")["links"])


def test_the_sheets_the_desk_does_not_use_are_taken_out(service, models):
    """MOBIL MK, YP DIBS, Ivır Zıvır and USDTRY IYIX are taken out as the TRY workbook loads: no page, not in the
    sheet explorer, none of their formulas (45 of them Bloomberg calls) is calculated.  The model file keeps them."""
    from tto.books import REMOVED_SHEETS, remove_sheets
    from tto.xl.model import Model
    gone = ("MOBIL MK", "YP DIBS", "Ivır Zıvır", "USDTRY IYIX")
    assert REMOVED_SHEETS == {"tto": gone}
    names = [s["name"] for s in service.sheets("tto")]
    assert not set(gone) & set(names) and names[:2] == ["MASA", "Günlük İşlemler"]
    for name in gone:
        assert name not in models["tto"].sheet_index
        with pytest.raises(ServiceError) as exc:
            service.grid(None, "tto", name, "A1:G6")
        assert exc.value.status == 404
    for page in ("mobil", "ivir", "ypdibs", "iyix"):
        with pytest.raises(ServiceError) as exc:
            service.view(None, page)
        assert exc.value.status == 404
    # the sheets left keep their order and are numbered again; the desk sheet's link to YP DIBS went with it
    model = models["tto"]
    assert [s.index for s in model.sheets] == list(range(len(model.sheets)))
    assert all(model.sheet_index[s.name] == s.index for s in model.sheets)
    assert not any("YP DIBS" in link["location"] for s in model.sheets for link in s.links)
    raw = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    assert set(gone) <= set(raw.sheet_index)                                  # the model file is a pure import
    calls = sum(raw.templates[t].count("_xll.BDP(") for name in gone for t in raw.sheet(name).fml.values())
    assert calls == 45
    order = [s.name for s in raw.sheets if s.name not in gone]
    assert remove_sheets("tto", raw) == sorted(gone) and [s.name for s in raw.sheets] == order
    assert remove_sheets("tto", raw) == [] and remove_sheets("sofr", raw) == []
    # a sheet that another sheet's formula refers to stays (taking it out would make those formulas #REF!)
    raw = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    raw.templates.append("`MOBIL MK!R1C1`+1")
    raw.sheet("MASA").fml[COLS * 500 + 1] = len(raw.templates) - 1
    assert remove_sheets("tto", raw) == ["Ivır Zıvır", "USDTRY IYIX", "YP DIBS"] and "MOBIL MK" in raw.sheet_index


def test_ids_are_unique():
    ids = [v["id"] for v in VIEWS]
    assert len(ids) == len(set(ids))
    for v in VIEWS:
        pids = [p["id"] for p in v["panels"]]
        assert len(pids) == len(set(pids)), v["id"]


@pytest.mark.parametrize("view", VIEWS, ids=[v["id"] for v in VIEWS])
def test_panels_and_inputs_point_at_real_cells(models, view):
    model = models[view["book"]]
    assert view["sheet"] in model.sheet_index
    assert view["title"] and view["group"]
    for p in view["panels"]:
        assert p["type"] in ("table", "notes", "chart", "generated")
        if p["type"] == "generated":
            assert p.get("source") in ("dibs_tape", "dibs_trading") and p.get("title"), (view["id"], p)   # a table of the dashboard's own
            continue
        sheet = model.sheet(p.get("sheet", view["sheet"]))          # a panel may show another sheet of the book
        if p["type"] == "chart":
            if "spec" in p:
                for s in p["spec"]["series"]:
                    for ref in (s["val"], s.get("cat"), s.get("name_ref")):
                        if ref:
                            model.range_ref(ref.replace("$", ""))
            elif p.get("ppk") == "interp":
                assert view["id"] == "ois" and p.get("title"), p     # a chart of the dashboard's own (tto/interpchart.py)
            else:
                assert 0 <= p["chart"] < len(sheet.charts), (view["id"], p)
            continue
        r1, c1, r2, c2 = parse_range(p["range"])
        assert 1 <= r1 <= sheet.max_row and 1 <= c1 <= sheet.max_col, (view["id"], p["id"], p["range"])
        assert p.get("title"), (view["id"], p["id"])
        for col, src in (p.get("tips") or {}).items():    # tooltips from the workbook: a column the table shows, a text column
            assert c1 <= col_to_index(col) <= c2 and (not p.get("cols") or col in p["cols"]), (view["id"], p["id"], col)
            assert col_to_index(src) >= 1 and src != col, (view["id"], p["id"], src)
        for key in ("note_ref", "title_ref"):                       # explanations read from a cell: a text cell
            if p.get(key):
                ref = p[key] if "!" in p[key] else "%s!%s" % (sheet.name, p[key])
                si, rc = model.cell_ref(ref)
                assert isinstance(model.sheets[si].consts.get(rc), str), (view["id"], p["id"], key)
    for inp in view["inputs"]:
        assert inp.get("scope", "user") in ("user", "shared")
        ref = inp["range"]
        if "!" in ref:
            model.range_ref(ref)
        else:
            parse_range(ref)


def test_an_input_declared_a_date_holds_a_date(models):
    """A cell declared a date takes nothing but a date ("tarih anlaşılamadı"): the ad-hoc forward list's spot and rates,
    the XAU leg's spot, swap and rates, the bond carry's ISIN, price and rate, Masa's manual TRY % ... were declared
    dates and could not be typed at all.  Every cell declared a date holds a date (or nothing) in its workbook."""
    from tto.inputs import parse_date
    bad = []
    for v in VIEWS:
        model = models[v["book"]]
        for inp in v["inputs"]:
            if inp.get("kind") != "date":
                continue
            sheet, _, addr = inp["range"].rpartition("!")
            sh = model.sheet(sheet.strip("'") or v["sheet"])
            r1, c1, r2, c2 = parse_range(addr)
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    x = sh.consts.get(r * COLS + c)
                    if x is None or (type(x) is float and 20000 < x < 80000) or (isinstance(x, str) and parse_date(x)):
                        continue
                    bad.append((v["id"], sh.name, r, c, x))
    assert bad == []
    kinds = {(v["id"], i["range"]): i["kind"] for v in VIEWS for i in v["inputs"]}
    assert kinds[("forward", "B25:C27")] == "date" and kinds[("forward", "D25:D27")] == "number"
    assert kinds[("forward", "G25:H27")] == kinds[("forward", "E63")] == kinds[("forward", "V78")] == "pct"
    assert kinds[("forward", "V56")] == "text" and kinds[("masa", "W94:W99")] == "number"
    assert kinds[("calc", "C54")] == kinds[("calc", "I54")] == "number"


def test_ret_curve_is_a_shared_desk_input():
    fwd = next(v for v in VIEWS if v["id"] == "forward")
    ret = [i for i in fwd["inputs"] if i.get("group") == "ret"]
    assert sorted(i["range"] for i in ret) == ["W33:W47", "X33:X47"]
    assert all(i["scope"] == "shared" and i["kind"] == "pct" for i in ret)
    assert any(i["range"] == "D2" and i.get("scope", "user") == "user" for i in fwd["inputs"])


def test_workbook_charts_are_all_shown(models):
    total = 0
    for v in VIEWS:
        sheet = models[v["book"]].sheet(v["sheet"])
        shown = {p["chart"] for p in v["panels"] if p["type"] == "chart" and "chart" in p}
        assert shown == set(range(len(sheet.charts))), v["id"]
        total += len(shown)
    assert total == 16                           # 14 in the TRY workbook, 2 in the ASW workbook


@pytest.mark.parametrize("view", VIEWS, ids=[v["id"] for v in VIEWS])
def test_every_input_can_be_reached_on_its_page(view):
    """A cell the trader may type into must be inside one of the page's tables (shown or among the helpers)."""
    boxes = {}
    for p in view["panels"]:
        if p["type"] in ("table", "notes"):
            boxes.setdefault(p.get("sheet", view["sheet"]), []).append(parse_range(p["range"]))
    for inp in view["inputs"]:
        sheet, _, addr = inp["range"].rpartition("!")
        sheet = sheet.strip("'") or view["sheet"]
        r1, c1, r2, c2 = parse_range(addr)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                assert any(a <= r <= b2 and b <= c <= d for a, b, b2, d in boxes.get(sheet, [])), (view["id"], inp["range"])


def test_nothing_the_workbooks_compute_is_missing_from_the_pages(service, models):
    """Every formula and every value of every sheet is inside a table of its page (shown, or among the
    helper tables), or is the caption / remark of a panel.  Checked twice: with the service's own
    bookkeeping and by walking the formulas of the models."""
    for v in service.views:
        assert service._leftover_cells(v) == [], v["id"]
    total = 0
    for v in VIEWS:
        model = models[v["book"]]
        for name in sheets_of(v):
            sh = model.sheet(name)
            boxes = [parse_range(p["range"]) for p in v["panels"]
                     if p["type"] in ("table", "notes") and p.get("sheet", v["sheet"]) == name]
            for rc in sh.fml:
                r, c = divmod(rc, COLS)
                assert any(r1 <= r <= r2 and c1 <= c <= c2 for r1, c1, r2, c2 in boxes), (v["id"], name, rc)
                total += 1
    blotter = len(models["tto"].sheet("Günlük İşlemler").fml)             # shown by the blotter page instead
    unused = sum(len(models[b].sheet(name).fml) for b, name in NO_PAGE)   # no page: the sheet explorer has them
    assert unused > 100
    assert total + blotter + unused == sum(len(sh.fml) for m in models.values() for sh in m.sheets) > 215000


def test_a_cell_outside_every_table_would_be_listed_on_its_page(service):
    """Should a page definition ever miss a cell, the page lists it under "Diğer hücreler" (with the helper
    tables): address, value and formula - here: the VİOP page without its calendar-spread table."""
    from tto.xl import numfmt
    v = dict(service.view_index["viop"])
    v["id"] = "viop-eksik"
    v["panels"] = [p for p in v["panels"] if p["id"] != "B11b"]
    left = service._leftover_cells(v)
    assert left == [("VIOP", [(62, 18), (62, 19), (63, 21), (64, 21)])]             # R62, S62, U63, U64
    book = service.books["tto"]
    data = service.et.call(lambda: service.renderers["tto"].cells_table(book.engine.shared, "VIOP", left[0][1],
                                                                       numfmt.get_locale("tr"), None))
    assert [c["t"] for c in data["rows"][0]] == ["Hücre", "Değer", "Formül"]
    assert [row[0]["t"] for row in data["rows"][1:]] == ["R62", "S62", "U63", "U64"]
    assert [row[2]["t"] for row in data["rows"][1:]] == ["=+N57-S57", "=+T57-M57", "", "=+U63+418"]
    assert data["rows"][3][1]["v"] == 6405.0 and "i" not in data["rows"][3][1]


def test_forward_sheets_manual_calculators_are_shown_in_full():
    """The hand calculators on the right of the Forward sheet (AG:AK) - both the USDTRY and the EURTRY
    halves - are visible tables of the Forward page."""
    fwd = next(v for v in VIEWS if v["id"] == "forward")
    shown = [parse_range(p["range"]) for p in fwd["panels"] if p["type"] == "table" and not p.get("hidden")]
    # (the USDTRY daily swap points, H35:J39, are in the USDTRY table of the "Forward fiyatları" tab: EK_FWD, columns K:M)
    for rng in ("AG4:AK16", "AG18:AK30", "AG32:AK44", "AG46:AK58", "AG60:AK68", "F8:F21"):
        r1, c1, r2, c2 = parse_range(rng)
        assert any(a <= r1 and b <= c1 and c >= r2 and d >= c2 for a, b, c, d in shown), rng


TABBED = [v for v in VIEWS if v["sections"]]


def test_the_big_pages_come_in_tabs():
    assert {v["id"] for v in TABBED} == {"masa", "ois", "forward", "viop", "carry", "dv01", "usd", "calc", "motor"}
    for v in VIEWS:
        if len([p for p in v["panels"] if not p.get("hidden")]) > 12:
            assert v["sections"], v["id"]                       # a long page is never one long list


@pytest.mark.parametrize("view", TABBED, ids=[v["id"] for v in TABBED])
def test_tabs_name_real_panels_and_leave_none_out(view):
    """Every table that is shown belongs to a tab or is pinned above them; a tab lists only panels that exist and
    are shown (the helper tables get a tab of their own when they are asked for)."""
    by_id = {p["id"]: p for p in view["panels"]}
    shown = {pid for pid, p in by_id.items() if not p.get("hidden")}
    ids = [s["id"] for s in view["sections"]]
    assert len(ids) == len(set(ids)) and "aux" not in ids and "*" not in ids
    listed = set()
    for s in view["sections"]:
        assert s["title"] and s["panels"], (view["id"], s["id"])
        assert len(s["panels"]) == len(set(s["panels"])), (view["id"], s["id"])
        for pid in s["panels"]:
            assert pid in shown, (view["id"], s["id"], pid)
        listed.update(s["panels"])
    pinned = set(view["pinned"])
    assert pinned <= shown and not (pinned & listed), view["id"]
    assert listed | pinned == shown, (view["id"], sorted(shown - listed - pinned))


def test_layout_of_a_page():
    from tto.views import layout
    v = {"pinned": ["P"], "sections": [{"id": "a", "title": "A", "panels": ["x", "y"], "note": "n"}, {"id": "b", "title": "B", "panels": ["z", "x"]}]}
    assert layout(v, ["P", "x", "y", "z"]) == {"pinned": ["P"], "sections": [
        {"id": "a", "title": "A", "note": "n", "panels": ["x", "y"]}, {"id": "b", "title": "B", "note": None, "panels": ["z", "x"]}]}
    # panels that are sent but listed nowhere (helper tables, a picture) are gathered at the end; a tab none of
    # whose panels is sent is left out, and so is a pinned panel that is not there
    out = layout(v, ["x", "h1", "rest"])
    assert out["pinned"] == [] and [(s["id"], s["panels"]) for s in out["sections"]] == [("a", ["x"]), ("b", ["x"]), ("aux", ["h1", "rest"])]
    assert layout({"pinned": [], "sections": []}, ["x", "y"]) == {"pinned": [], "sections": []}
    assert layout({}, ["x"]) == {"pinned": [], "sections": []}


def test_calculators_are_easy_to_reach():
    """What the desk asked for: the hand calculators of the Forward sheet are the first thing on its page."""
    fwd = next(v for v in VIEWS if v["id"] == "forward")
    first = fwd["sections"][0]
    assert first["title"] == "Hesaplayıcılar" and first["panels"][:5] == ["B7", "B8", "B9", "B10", "B11"]
    titles = {p["id"]: p.get("title", "") for p in fwd["panels"]}
    assert titles["B7"].startswith("Interest 2 SP") and titles["B8"].startswith("SP 2 Interest")
    assert fwd["pinned"] == ["B1"]                                   # the value date they all read stays in sight
    viop = next(v for v in VIEWS if v["id"] == "viop")
    assert [s["title"] for s in viop["sections"]][:3] == ["Kontratlar", "Hesaplayıcılar", "Altın"]
    # the copies on the Calculators sheet are told apart by name
    calc = next(v for v in VIEWS if v["id"] == "calc")
    names = [p.get("title", "") for p in calc["panels"] if not p.get("hidden")]
    assert len(names) == len(set(names)), [n for n in names if names.count(n) > 1]


def test_each_calculator_has_one_home():
    """Duplicated calculators each have one home; the copies are helper tables (the workbook's cells stay in a table):
    Interest 2 SP / SP 2 Interest and the repo converter on the Forward page (the Calculators sheet's B1-B4 and B12-B22
    and the VİOP page's B8 are copies), Forward DV01 on the Forward page (Calculators B10), the date-to-date rate on the
    desk page (OIS B17, Forward B25), and the Calculators sheet's exact copies (B21, B22, B29, B30, B34).  The desk page's
    forward quote matrices moved to the Forward page's "Kotasyon" tab - the desk page keeps a summary - and its
    near-copy of the cross forward (B14) retired."""
    by = {v["id"]: v for v in VIEWS}

    def panel(view, pid):
        return next(p for p in by[view]["panels"] if p["id"] == pid)

    def tabs(view):
        return {pid for s in by[view]["sections"] for pid in s["panels"]}

    copies = {"calc": ["B%d" % k for k in (1, 2, 3, 4, 10) + tuple(range(12, 23)) + (29, 30, 34)], "viop": ["B8"],
              "ois": ["B17"], "forward": ["B25"], "masa": ["B14"]}
    for view, ids in copies.items():
        for pid in ids:
            p = panel(view, pid)
            assert p["hidden"] and p["title"].startswith("Yardımcı · ") and pid not in tabs(view), (view, pid)
    homes = {"forward": ["B7", "B8", "B9", "B10", "B11", "B18"], "masa": ["B9"]}
    for view, ids in homes.items():
        for pid in ids:
            assert not panel(view, pid).get("hidden") and pid in tabs(view), (view, pid)
    assert [s["id"] for s in by["calc"]["sections"]] == ["conv", "pos", "bond"] and by["calc"]["sections"][0]["panels"][0] == "B7"
    # the quote matrices: the Forward page's own sheet now, a summary (borrowed) on the desk page
    kot = next(s for s in by["forward"]["sections"] if s["id"] == "kot")
    assert kot["title"] == "Kotasyon" and kot["panels"] == ["EKF1", "EKF5", "EKF2", "EKF8", "EKF6", "EKF9"]
    assert not any(p.get("sheet") == "EK_FWD" and not p.get("borrowed") for p in by["masa"]["panels"])
    eks = panel("masa", "EKS")
    assert eks["borrowed"] and eks["sheet"] == "EK_FWD" and eks["range"] == "A2:N14"       # (row 2: the matrix's curve)
    # each spread with the TRY rate it makes beside it (M / N: OIS + spread), the rest as the sheet has them
    assert eks["cols"] == ["A", "B", "C", "D", "M", "E", "N", "F", "G", "H", "I", "J", "K"]
    # EURTRY's summary below it: the same columns of the EURTRY matrix (curve row 101, header 102, "Tümü" 103, dates
    # 104-113)
    ekse = panel("masa", "EKSE")
    assert ekse["borrowed"] and ekse["sheet"] == "EK_FWD" and ekse["range"] == "A101:N113" and ekse["cols"] == eks["cols"]
    assert "EURTRY" in ekse["title"] and "EURTRY" not in eks["title"]
    # the date-to-date forward's dates and spread right above it: the row of the desk sheet's date-to-date inputs
    assert panel("masa", "B10D")["range"] == "B60:N60" and not panel("masa", "B10D").get("hidden")
    assert next(s for s in by["masa"]["sections"] if s["id"] == "fwd")["panels"] == ["EKS", "EKSE", "B10D", "B10", "B22"]
    assert not any(i["range"].startswith("EK_FWD!") for i in by["masa"]["inputs"])
    assert {"EK_FWD!B2", "EK_FWD!D4:E4", "EK_FWD!D20:E29", "EK_FWD!D119:E128"} <= {i["range"] for i in by["forward"]["inputs"]}
    # the hidden limit table of the Calculators sheet takes no input any more
    assert not {"X63", "X64", "X65", "X66"} & {i["range"] for i in by["calc"]["inputs"]}


def test_the_desks_forward_summary_shows_each_spreads_try_rate_beside_it(service):
    """Masa's forward quote summary: Spread bid, TRY bid %, Spread ask, TRY ask % side by side - the spreads still
    the sheet's own inputs (a spread typed on Masa moves the TRY rate beside it: OIS + spread)."""
    from conftest import cell
    from tto.service import _pick_columns
    user = service.login("forward özeti")["user"]
    eks = next(p for p in service.view(user, "masa")["panels"] if p.get("id") == "EKS")
    d = eks["data"]
    assert d["c"] == ["A", "B", "C", "D", "M", "E", "N", "F", "G", "H", "I", "J", "K"]
    assert [c.get("t") for c in d["rows"][d["r"].index(3)]][3:7] == ["Spread bid", "TRY bid %", "Spread ask", "TRY ask %"]
    one = d["rows"][d["r"].index(5)]                                     # 1M
    assert [col for col, c in zip(d["c"], one) if "i" in c] == ["B", "D", "E"]
    # the curve the TRY rates are read from (MPC ima, a scenario, bootstrap ...): the matrix's own input, above it
    curve = d["rows"][0]
    assert d["r"][0] == 2 and curve[0]["t"] == "Eğri" and curve[1]["i"] == "u" and curve[1]["t"] == "MPC ima"
    service.set_inputs(user, "tto", [{"ref": "EK_FWD!D5", "value": "25"}])     # 1M bid spread: +25 bp over OIS
    try:
        eks = next(p for p in service.view(user, "masa")["panels"] if p.get("id") == "EKS")
        d = eks["data"]
        row = d["rows"][d["r"].index(5)]
        cells = dict(zip(d["c"], row))
        assert cells["D"]["t"] == "25" and cell(service, "EK_FWD!M5", user) == pytest.approx(cell(service, "EK_FWD!L5", user) + 0.25, abs=1e-9)
        assert float(cells["M"]["t"].replace(",", ".")) == pytest.approx(cell(service, "EK_FWD!M5", user), abs=0.006)
    finally:
        service.set_inputs(user, "tto", [{"ref": "EK_FWD!D5", "value": ""}])
    # EURTRY: the same columns from its own matrix; a spread typed on Masa goes into the EURTRY matrix's cell
    ekse = next(p for p in service.view(user, "masa")["panels"] if p.get("id") == "EKSE")
    d = ekse["data"]
    assert d["c"] == ["A", "B", "C", "D", "M", "E", "N", "F", "G", "H", "I", "J", "K"]
    assert [c.get("t") for c in d["rows"][d["r"].index(102)]][3:7] == ["Spread bid", "TRY bid %", "Spread ask", "TRY ask %"]
    assert d["r"][0] == 101 and d["rows"][0][0]["t"] == "Eğri" and d["rows"][0][1]["i"] == "u"        # its own curve
    one = d["rows"][d["r"].index(104)]                                   # 1M
    assert one[0]["t"] == "1M" and [col for col, c in zip(d["c"], one) if "i" in c] == ["B", "D", "E"]
    service.set_inputs(user, "tto", [{"ref": "EK_FWD!E104", "value": "-40"}])    # 1M ask spread: 40 bp under OIS
    try:
        ekse = next(p for p in service.view(user, "masa")["panels"] if p.get("id") == "EKSE")
        cells = dict(zip(ekse["data"]["c"], ekse["data"]["rows"][ekse["data"]["r"].index(104)]))
        assert cells["E"]["t"] == "-40" and cell(service, "EK_FWD!N104", user) == pytest.approx(cell(service, "EK_FWD!L104", user) - 0.40, abs=1e-9)
        assert float(cells["N"]["t"].replace(",", ".")) == pytest.approx(cell(service, "EK_FWD!N104", user), abs=0.006)
        assert cell(service, "EK_FWD!K104", user) > cell(service, "EK_FWD!G104", user) > 0      # an EURTRY forward above its spot
    finally:
        service.set_inputs(user, "tto", [{"ref": "EK_FWD!E104", "value": ""}])
    # the date-to-date forward's inputs: start, end and spread are the desk sheet's (C60, E60, I60), typed above it
    strip = next(p for p in service.view(user, "masa")["panels"] if p.get("id") == "B10D")
    d = strip["data"]
    assert d["r"] == [60] and [col for col, c in zip(d["c"], d["rows"][0]) if c.get("i")] == ["C", "E", "I"]
    before = cell(service, "MASA!T62", user)                            # B10: the forward at the end date (MPC ima)
    service.set_inputs(user, "tto", [{"ref": "MASA!C60", "value": "01.12.2026"}, {"ref": "MASA!E60", "value": "01.03.2027"}])
    try:
        assert cell(service, "MASA!G60", user) == 90.0                  # the days between them
        assert cell(service, "MASA!T62", user) > before                 # a later end date than spot + 3 months: a higher forward
    finally:
        service.set_inputs(user, "tto", [{"ref": "MASA!C60", "value": ""}, {"ref": "MASA!E60", "value": ""}])
    # the helper: a column the table does not have is skipped, the order otherwise kept, spans across columns dropped
    data = {"c": ["A", "B", "C"], "r": [1], "rows": [[{"t": "a", "cs": 2}, {"t": "b"}, {"t": "c"}]], "fz": 1}
    _pick_columns(data, ["C", "Z", "A"])
    assert data["c"] == ["C", "A"] and [x["t"] for x in data["rows"][0]] == ["c", "a"] and "cs" not in data["rows"][0][1] and "fz" not in data


def test_inputs_typed_beside_a_table_are_its_own(service):
    """The strips of input cells put right before the tables are the tables' own inputs (another page's cells: the same
    inputs, typed in either place).  On the desk page's VİOP tab DEALS' contract limit and a VİOP target; on the OIS
    page its parameters pinned above the tabs - the DV01 per leg typed with the best trades open sizes them; DV01's
    parameters pinned as well, the C & R page's OIS row with the C+R nominal and direction, the USD page's inputs in
    each tab that reads them."""
    from conftest import cell
    user = service.login("girdi yanında")["user"]
    page = service.view(user, "masa")
    tabs = {s["id"]: s["panels"] for s in page["sections"]}
    assert tabs["viop"] == ["B15", "B16D", "B16", "B17D", "B17"]
    assert tabs["sig"] == ["B18D", "B18", "B19D", "B19", "B23D", "B23"]
    strips = {p["id"]: p["data"] for p in page["panels"] if p.get("id") in ("B16D", "B17D", "B19D", "B23D")}
    assert strips["B16D"]["r"] == [321] and [c.get("i") for c in strips["B16D"]["rows"][0]] == [None, "u"]
    assert strips["B17D"]["c"] == ["L", "M", "N", "O", "Z", "P"] and strips["B17D"]["r"] == list(range(330, 339))   # Z: FRA eğrisi
    assert all(c.get("i") == "u" for row in strips["B17D"]["rows"][1:] for c in row)
    assert strips["B19D"]["c"] == ["I", "J", "O", "P", "W", "X", "Y", "Z"]      # horizon, threshold, price type, repo
    assert [c.get("i") for c in strips["B19D"]["rows"][0]] == [None, "u", None, "u", None, "u", None, "u"]
    assert strips["B23D"]["rows"][0][1]["t"] == "Bootstrap" and strips["B23D"]["rows"][0][1]["i"] == "u"
    service.set_inputs(user, "tto", [{"ref": "VIOP!W321", "value": "1"},              # DEALS: the first contract only
                                     {"ref": "VIOP!L331", "value": "Spot"}, {"ref": "VIOP!M331", "value": "31.12.2026"},
                                     {"ref": "VIOP!N331", "value": "LONG"}, {"ref": "VIOP!O331", "value": "Faiz %"},
                                     {"ref": "VIOP!P331", "value": "34"}])
    try:
        got = {p["id"]: p["data"] for p in service.view(user, "masa")["panels"] if p.get("id") in ("B16", "B17")}
        deals, target = got["B16"], got["B17"]
        assert [c.get("t") for c in deals["rows"][deals["r"].index(111)]][1:3] == ["Spot", "30.11.2026"]
        assert not any(c.get("t") for c in deals["rows"][deals["r"].index(112)][1:])               # no second one
        first = [c.get("t") for c in target["rows"][target["r"].index(121)]]
        assert first[:5] == ["Spot", "31.12.2026", "LONG", "Faiz % 34", "34,00%"]
        assert cell(service, "MASA!AB121", user) == 57.0                                 # days to the far leg
    finally:
        service.reset_inputs(user, "tto", ["VIOP!W321"] + ["VIOP!%s331" % c for c in "LMNOP"])
    # the OIS page: its parameters above every tab; the DV01 per leg typed there sizes the best trades of their tab
    ois = service.view(user, "ois")
    assert ois["pinned"] == ["B1"] and not any("B1" in s["panels"] for s in ois["sections"])
    nominal = cell(service, "OIS_MAIN!F30", user)                                # the best spread's long nominal
    service.set_inputs(user, "tto", [{"ref": "OIS_MAIN!F2", "value": "2000"}])
    try:
        assert nominal > 0 and cell(service, "OIS_MAIN!F30", user) == pytest.approx(2 * nominal, rel=0.02)
    finally:
        service.reset_inputs(user, "tto", ["OIS_MAIN!F2"])
    assert cell(service, "OIS_MAIN!F2", user) == 1000.0
    assert service.view(user, "dv01")["pinned"] == ["B2"]
    carry = next(p for p in service.view(user, "carry")["panels"] if p["id"] == "CP2")["data"]
    on = {(r, col) for r, row in zip(carry["r"], carry["rows"]) for col, c in zip(carry["c"], row) if c.get("i")}
    assert {(2, "F"), (2, "H"), (3, "H"), (3, "J"), (4, "B"), (4, "D"), (4, "F")} <= on   # DV01, lot, C+R, horizons
    usd = {s["id"]: s["panels"] for s in service.view(user, "usd")["sections"]}
    assert "inp" in usd["top"] and all(usd[t][0] == "inp" for t in ("fomc", "curve", "trades"))


# ------------------------------------------------------------------------------- inputs beside their tables
#: inputs a table may read without showing them in its tab: the desk's reference and set-up data, each typed in a home
#: of its own (book -> sheet ranges)
REFERENCE = {
    "tto": [
        # holiday lists: TR (Motor → Tatiller), USD and EUR (Ayarlar · Toplantı takvimi)
        "Motor!A361:B523", "EK_TATIL!A5:E264",
        # how the TRY curves are read between quoted tenors, each user's own (Ayarlar → Eğri interpolasyonu): every
        # curve reader reads it
        "EK_INTERP!B2",
        # Bloomberg: the order of the pricing sources, tickers, fields and suffixes, the bonds' sources
        "EK_KAYNAK!B4:E6", "OIS_MAIN!J9:J26", "Forward!AO6:AR26", "VIOP!L1:W1", "VIOP!C16:C35", "VIOP!C43:C52",
        "VIOP!C58:C69", "VIOP!M45:O45", "VIOP!S340", "MASA!C156:C163", "MASA!U155", "MASA!S171", "Motor!O89",
        "Motor!O130", "EK_XAU!B3", "EK_XAU!B10", "EK_XAU!B12", "EK_XAU!D16:D22", "DİBS RV!B2", "DİBS RV!N2",
        "DİBS RV!B5:B54",
        # the window of VİOP's basis history (how much history Bloomberg is asked for: VİOP → Geçmiş · baz)
        "VIOP!M340",
        # the trading list of bonds (★ on Tüm Kâğıtlar) and the floaters' fixing lag
        "DİBS RV!A5:A54", "DİBS RV!V2",
        # the MPC meetings: dates and labels (OIS → PPK ima)
        "OIS_MAIN!O10:P89",
        # the engine's set-up (Motor): tenors of the bootstrap, the quotes and the tenor universe, quoted flags, the
        # solver's codes
        "Motor!E88:E130", "Motor!A306:A321", "Motor!A325:C342", "Motor!F4305:F4390", "Motor!H4305:H4390",
        "Motor!D4306:D4390", "Motor!B4395:B4396", "Motor!B4445:E4462", "Motor!A4476:A4560",
        # the OIS curve: the solver's settings, the scenarios (base, shift, names, probabilities, steps per meeting)
        # and the list of FRAs - typed on the OIS page
        "OIS_MAIN!F3", "OIS_MAIN!J4", "OIS_MAIN!AU6:AU15", "OIS_MAIN!V444:V457", "OIS_MAIN!B3", "OIS_MAIN!D3",
        "OIS_MAIN!P3:Q5", "OIS_MAIN!U10:W89", "OIS_MAIN!M336:N438",
        # the desk's shared RET curve (Forward → RET) and day-count conventions
        "Forward!W33:X47", "Forward!U37", "Forward!U6", "VIOP!B44", "VIOP!R353", "DV01_RISK!H6:I25",
        # spot value dates (formula defaults: T+1 / T+2 past the holidays)
        "Forward!I2", "Forward!K2", "VIOP!K3",
        # market data typed by hand: today's TLREF, the manual spot, gold's spot, value date, swap rates and source
        "OIS_MAIN!J2", "VIOP!AA9:AA10", "EK_XAU!B5:C5", "EK_XAU!B8", "EK_XAU!B11", "EK_XAU!F16:F22",
    ],
    "sofr": [
        # SIFMA holidays, the FOMC meetings and their decision flags, the scenario view (FOMC tab), the quotes typed by
        # hand and those the curve includes (Eğri tab), WIRP typed by hand
        "SOFR_FOMC!BO4:BO70", "SOFR_FOMC!B74:C83", "SOFR_FOMC!R72:T83", "SOFR_FOMC!D49:D68", "SOFR_FOMC!F49:F68",
        "SOFR_FOMC!P74:P83",
    ],
    "asw": ["ASW!LR2:LR200"],                                   # holidays
    # the first tenor of the BIST swap quote lists (the tickers asked of Bloomberg are built from it), USD OIS tickers,
    # the copy of the TRY holidays (the T+1 value date; Ayarlar → Tatiller)
    "borsa": ["Sheet1!B4", "Sheet1!N4", "Sheet1!AD6:AD15", "EK_TATIL!A5:A204"],
}

#: inputs a table reads that cannot sit beside it - a big table of inputs of their own (the pasted position, the bonds'
#: table) or what an engine page computes with: the note of the table or of its tab names where they are typed.
#: (page, panel) -> [(what the note names, sheet ranges)]
_POSITION = ("Pozisyon", ["DV01_RISK!C6:C25", "DV01_RISK!K6:K25", "DV01_RISK!Q6:Q25"])    # bucket DV01s, pivots, rates
_HEDGE = ("Hedge", ["DV01_RISK!C85:G85", "DV01_RISK!C88:E102"])                           # the hedge instruments
NAMED = {
    ("masa", "B19"): [("DİBS RV", ["DİBS RV!H5:H54", "DİBS RV!N5:N54", "DİBS RV!AL5:AL54"])],
    ("kagitlar", "U1"): [("DİBS RV", ["DİBS RV!H5:H54", "DİBS RV!N5:N54"])],
    ("dv01", "B9"): [_POSITION, _HEDGE],
    ("dv01", "B10"): [_POSITION, _HEDGE],
    **{("dv01", pid): [_POSITION] for pid in ("B2", "B11", "B13", "B14", "B16", "B17", "B18")},
    **{("motor", pid): [("C & R", ["OIS_MAIN!B4:F4", "EK_CARRY!B2"])] for pid in ("B4", "B5", "B6", "B7")},
}

#: inputs a table reads only in passing: (page, panel) -> sheet ranges
INCIDENTAL = {
    # Masa's "Yön (model)" copies the OIS outright's direction, whose threshold scales with the nominal sized by the
    # DV01 per leg (which cancels out - the rounding stays)
    ("masa", "B3"): ["OIS_MAIN!F2:H2"],
    # DİBS live: a bond's name comes from its DİBS RV row, filled while DİBS RV prices the bond (price type, manual
    # clean price, known coupon)
    ("dibslive", "L1"): ["DİBS RV!X2", "DİBS RV!H5:H54", "DİBS RV!N5:N54"],
}

#: the desk's status row: it checks every page's data
STATUS = {("masa", "B2")}


def _tabs(view):
    """A page's tabs as (id, note, the panels shown in it - each pinned one too); a page without tabs is one tab."""
    if not view["sections"]:
        return [("", "", [p["id"] for p in view["panels"] if not p.get("hidden")])]
    return [(s["id"], s.get("note") or "", list(view["pinned"]) + list(s["panels"])) for s in view["sections"]]


def _shown_cells(book, view, p):
    """The cells a table shows on its page: its range (its first ``max_rows`` rows) without the columns Excel hides
    (unless it hides them all) - only the ``cols`` named, when they are."""
    sheet = book.model.sheet(p.get("sheet", view["sheet"]))
    r1, c1, r2, c2 = parse_range(p["range"])
    if p.get("max_rows"):
        r2 = min(r2, r1 + int(p["max_rows"]) - 1)
    cols = [c for c in range(c1, c2 + 1) if not sheet.col_hidden(c)] or list(range(c1, c2 + 1))
    if p.get("cols"):
        named = {col_to_index(x) for x in p["cols"]}
        cols = [c for c in cols if c in named]
    return [(sheet.index, r * COLS + c) for r in range(r1, r2 + 1) for c in cols]


def _inputs_away_from_their_tables(service, views=None, reference=None):
    """``{(page, tab, panel): [cells]}``: the inputs each visible table reads - its formulas followed through the
    workbook down to the inputs (``RefIndex.upstream``) - that its tab does not show and none of the lists above
    (``reference``: instead of REFERENCE) lets it read elsewhere."""
    views = views or service.views
    reference_of = REFERENCE if reference is None else reference
    tables = {v["id"]: {p["id"]: p for p in v["panels"] if p["type"] in ("table", "notes") and not p.get("hidden")}
              for v in views}
    shown, reads = {}, {}
    for bid in sorted({v["book"] for v in views}):
        book = service.books[bid]
        groups = {(v["id"], pid): _shown_cells(book, v, p) for v in views if v["book"] == bid
                  for pid, p in tables[v["id"]].items()}
        shown.update(groups)
        # the inputs the pages (and the service) declare - not a cell somebody typed a value over ("elle değer")
        inputs = [c for c, d in book.inputs.items() if d.group not in ("adhoc", "adhoc-shared")]

        def walk(book=book, groups=groups, inputs=inputs):
            return book.engine.ref_index().upstream(groups, inputs)

        reads.update(service.et.call(walk))
    out = {}
    for v in views:
        book = service.books[v["book"]]

        def within(refs, model=book.model):
            boxes = [model.range_ref(ref) for ref in refs]
            return lambda c: any(si == c[0] and r1 <= c[1] // COLS <= r2 and c1 <= c[1] % COLS <= c2
                                 for si, r1, c1, r2, c2 in boxes)

        is_reference = within(reference_of.get(v["book"], []))
        for tab, note, ids in _tabs(v):
            here = {c for pid in ids if (v["id"], pid) in shown for c in shown[(v["id"], pid)]}
            for pid in ids:
                p = tables[v["id"]].get(pid)
                if p is None or (v["id"], pid) in STATUS:
                    continue
                said = " ".join((p.get("title") or "", p.get("note") or "", note))
                allowed = [within(refs) for what, refs in NAMED.get((v["id"], pid), []) if what in said]
                allowed.append(within(INCIDENTAL.get((v["id"], pid), [])))
                away = [c for c in reads[(v["id"], pid)] - here
                        if not is_reference(c) and not any(ok(c) for ok in allowed)]
                if away:
                    out[(v["id"], tab, pid)] = sorted(book.ref(*c) for c in away)
    return out


def test_every_table_has_the_inputs_it_reads_in_its_tab(service):
    """What the desk found on the desk page - the date-to-date forward had nowhere to type its dates and spread: they
    were in another tab's table - checked for every visible table of every page.  The inputs a table's formulas read
    (followed through the workbook down to the inputs) are shown in its tab: in the table itself, in a strip of input
    cells right before it (another page's cells borrowed when they live there), in a panel pinned above the tabs.  Only
    the desk's reference and set-up data is read from its own home (REFERENCE); a big table of inputs on another tab or
    page is named in a note (NAMED); a few inputs are read only in passing (INCIDENTAL)."""
    assert _inputs_away_from_their_tables(service) == {}


def test_a_table_away_from_its_inputs_is_found(service):
    """The check above finds today's problem should a page change bring it back: without the strip of its dates and
    spread the desk page's date-to-date forward reads them in another tab; the forward quote summary without the row of
    its curve; a tab whose note no longer names where the pasted position is; the RET curve once it is no reference."""
    import copy
    masa = copy.deepcopy(service.view_index["masa"])
    next(s for s in masa["sections"] if s["id"] == "fwd")["panels"].remove("B10D")
    next(p for p in masa["panels"] if p["id"] == "EKS")["range"] = "A3:N14"
    assert _inputs_away_from_their_tables(service, [masa]) == {
        ("masa", "fwd", "B10"): ["MASA!C60", "MASA!E60", "MASA!I60"], ("masa", "fwd", "EKS"): ["EK_FWD!B2"]}
    dv01 = copy.deepcopy(service.view_index["dv01"])
    next(s for s in dv01["sections"] if s["id"] == "risk").pop("note")
    away = _inputs_away_from_their_tables(service, [dv01])
    # (the parameters pinned above the tabs as well: their pivot check reads the position's pivots)
    assert set(away) == {("dv01", "risk", pid) for pid in ("B2", "B9", "B10", "B11", "B13")}
    assert "DV01_RISK!C6" in away[("dv01", "risk", "B9")] and "DV01_RISK!C85" in away[("dv01", "risk", "B9")]
    assert away[("dv01", "risk", "B2")] == ["DV01_RISK!K%d" % r for r in sorted(range(6, 26), key=str)]
    no_ret = dict(REFERENCE, tto=[ref for ref in REFERENCE["tto"] if ref != "Forward!W33:X47"])
    away = _inputs_away_from_their_tables(service, [service.view_index["masa"]], no_ret)
    assert "Forward!W33" in away[("masa", "over", "B8")] and ("masa", "fwd", "B10") in away
