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


#: sheets of the TRY workbook that have no page any more (the desk does not use them); their cells are still
#: calculated and can be looked at in the sheet explorer
NO_PAGE = {("tto", "MOBIL MK"), ("tto", "Ivır Zıvır"), ("tto", "YP DIBS")}


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
    assert not {"mobil", "ivir", "ypdibs"} & {v["id"] for v in VIEWS}


def test_the_sheets_without_a_page_are_still_in_the_sheet_explorer(service):
    names = [s["name"] for s in service.sheets("tto")]
    for _, name in NO_PAGE:
        assert name in names
    grid = service.grid(None, "tto", "MOBIL MK", "A1:G6")
    assert grid["data"]["rows"][0][0]["t"] and grid["dims"][0] > 20
    with pytest.raises(ServiceError) as exc:
        service.view(None, "ivir")
    assert exc.value.status == 404
    # a link of the desk sheet to a sheet without a page is simply not offered
    assert all(l["page"] in service.view_index or l["page"] == "blotter" for l in service.view(None, "masa")["links"])


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
        assert p["type"] in ("table", "notes", "chart")
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
    for rng in ("AG4:AK16", "AG18:AK30", "AG32:AK44", "AG46:AK58", "AG60:AK68", "H35:J39", "F8:F21"):
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
