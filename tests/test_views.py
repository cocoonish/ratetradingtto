"""Page definitions are consistent with the workbooks they show."""
import pytest

from tto.books import BOOKS, load_books
from tto.service import ServiceError
from tto.views import load_views
from tto.xl.model import COLS, parse_range
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


#: sheets without a page of their own (the sheet explorer shows them): the order of the pricing sources, which is on
#: the settings page
NO_PAGE = {("tto", "EK_KAYNAK")}


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
            else:
                assert 0 <= p["chart"] < len(sheet.charts), (view["id"], p)
            continue
        r1, c1, r2, c2 = parse_range(p["range"])
        assert 1 <= r1 <= sheet.max_row and 1 <= c1 <= sheet.max_col, (view["id"], p["id"], p["range"])
        assert p.get("title"), (view["id"], p["id"])
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
    assert kot["title"] == "Kotasyon" and kot["panels"] == ["EKF1", "EKF5", "EKF2", "EKF6"]
    assert not any(p.get("sheet") == "EK_FWD" and not p.get("borrowed") for p in by["masa"]["panels"])
    eks = panel("masa", "EKS")
    assert eks["borrowed"] and eks["sheet"] == "EK_FWD" and eks["range"] == "A3:K14"
    assert next(s for s in by["masa"]["sections"] if s["id"] == "fwd")["panels"] == ["EKS", "B10", "B22"]
    assert not any(i["range"].startswith("EK_FWD!") for i in by["masa"]["inputs"])
    assert {"EK_FWD!B2", "EK_FWD!D4:E4", "EK_FWD!D20:E29", "EK_FWD!D119:E128"} <= {i["range"] for i in by["forward"]["inputs"]}
    # the hidden limit table of the Calculators sheet takes no input any more
    assert not {"X63", "X64", "X65", "X66"} & {i["range"] for i in by["calc"]["inputs"]}
