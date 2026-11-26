"""Düzen (layout) of the pages, the app-wide mechanisms (the desk, 27.11.2026: "Düzen: sayfalar tek tek" in
docs/desk-decisions.md): a view's ``freeze``, ``limit`` and ``fit``, a column of panels in its tabs, a two-way group's
note said once on the screen.  How the browser lays them out is checked by the browser test (``duzenL1``)."""
import io
import json
import os

import pytest

from tto import views
from tto.service import _freeze_columns
from tto.views import check_view, flat_ids, layout, load_views, normalize
from tto.xl import numfmt


def raw_views():
    out = {}
    for name in sorted(os.listdir(views.HERE)):
        if name.endswith(".json"):
            with io.open(os.path.join(views.HERE, name), encoding="utf-8") as fh:
                v = json.load(fh)
            out[v["id"]] = v
    return out


# ---------------------------------------------------------------------------------------------- the views' options
def test_every_pages_layout_options_are_well_formed():
    """freeze / limit / fit and the columns of panels of every page as written (the lists in its tabs too)."""
    raw = raw_views()
    problems = []
    for v in load_views():
        problems += check_view(v, raw.get(v["id"]))
    assert problems == []


def test_check_view_says_what_is_wrong():
    v = {"id": "x",
         "panels": [{"id": "A", "type": "table", "freeze": -1, "limit": {"rows": 0}, "fit": "evet"},
                    {"id": "B", "type": "chart", "freeze": 1, "limit": {"rows": 3}},
                    {"id": "C", "type": "table", "freeze": True, "limit": 5},
                    {"id": "D", "type": "generated", "freeze": 2, "limit": {"rows": 24}, "fit": True}],
         "sections": [{"id": "s", "title": "S", "panels": ["A", ["B"], ["C", ["D"]], "Z", "A"]}], "pinned": [["D", "C"]]}
    out = check_view(v)
    said = "\n".join(out)
    for want in ("x/A: freeze bir sütun sayısı", "x/A: limit", "x/A: fit true ya da false", "x/B: freeze yalnız tabloda",
                 "x/B: limit yalnız tabloda", "x/C: freeze bir sütun sayısı", "x/C: limit", "x/sekme s: bir sütun en az iki panel",
                 "x/sekme s: panel adı yazı olur", "x/sekme s: böyle bir panel yok: Z", "x/sekme s: A iki kez"):
        assert want in said, (want, out)
    assert not any(line.startswith("x/D") or "pinned" in line for line in out), out          # (D and the pinned column: right)
    good = {"id": "y", "panels": [{"id": "A", "type": "table", "freeze": 0, "limit": {"rows": 1}, "fit": False},
                                  {"id": "B", "type": "table"}],
            "sections": [{"id": "s", "title": "S", "panels": [["A", "B"]]}], "pinned": []}
    assert check_view(good) == []


def test_a_column_of_panels_in_a_tab_is_flat_with_its_columns_beside(monkeypatch, tmp_path):
    """``["A", ["B", "C"], "D"]`` in a tab: its ids in order (what the tests, the menu's search and the launchpad read),
    the column in ``stacks``; one panel alone in a list is a panel; the pinned ones the same way."""
    assert flat_ids(["A", ["B", "C"], "D", ["E"], 7, [["F"]]]) == (["A", "B", "C", "D", "E"], [["B", "C"]])
    page = {"id": "dz", "title": "Düzen", "group": "Test", "book": "tto", "sheet": "MASA",
            "panels": [{"id": p, "type": "table", "range": "A1:B2"} for p in ("P", "Q", "A", "B", "C", "D")],
            "sections": [{"id": "s1", "title": "Bir", "panels": ["A", ["B", "C"], "D"]},
                         {"id": "s2", "title": "İki", "panels": [["D", "A"], "B"]}],
            "pinned": [["P", "Q"]]}
    (tmp_path / "99_dz.json").write_text(json.dumps(page), encoding="utf-8")
    monkeypatch.setattr(views, "HERE", str(tmp_path))
    v = views.load_views()[0]
    assert v["sections"][0]["panels"] == ["A", "B", "C", "D"] and v["sections"][0]["stacks"] == [["B", "C"]]
    assert v["sections"][1]["panels"] == ["D", "A", "B"] and v["sections"][1]["stacks"] == [["D", "A"]]
    assert v["pinned"] == ["P", "Q"] and v["pinned_stacks"] == [["P", "Q"]]
    assert check_view(v, page) == []
    flat = normalize({"id": "n", "sections": [{"id": "s", "title": "S", "panels": ["A", "B"]}]})
    assert "stacks" not in flat["sections"][0] and "pinned_stacks" not in flat and flat["pinned"] == []


def test_the_pages_answer_carries_the_columns_of_the_panels_sent():
    """layout(): each column with its panels that are sent (a temporary copy right under its table, in the column too),
    a column left with one panel is no column; the lists of a tab as written are read as well."""
    v = {"pinned": ["P", "Q"], "pinned_stacks": [["P", "Q"]],
         "sections": [{"id": "a", "title": "A", "panels": ["x", "y", "z", "w"], "stacks": [["y", "z"]]},
                      {"id": "b", "title": "B", "panels": ["w", ["x", "q"]]},
                      {"id": "c", "title": "C", "panels": [["z", "w"]]}]}
    out = layout(v, ["P", "Q", "x", "y", "y.c1", "z", "w"], {"y": ["y.c1"]})
    assert out["pinned"] == ["P", "Q"] and out["pinned_stacks"] == [["P", "Q"]]
    a, b, c = out["sections"]
    assert a == {"id": "a", "title": "A", "note": None, "panels": ["x", "y", "y.c1", "z", "w"], "stacks": [["y", "y.c1", "z"]]}
    assert b == {"id": "b", "title": "B", "note": None, "panels": ["w", "x"]}                 # (q is not sent: no column)
    assert c["panels"] == ["z", "w"] and c["stacks"] == [["z", "w"]]
    assert "pinned_stacks" not in layout({"pinned": ["P"], "sections": [{"id": "a", "title": "A", "panels": ["x"]}]}, ["P", "x"])


# ---------------------------------------------------------------------------------------------- freeze
def _table(cols, fz=None):
    d = {"sheet": "S", "rows": [[{"t": str(c)} for c in cols], [{"t": "1"} for _ in cols]], "r": [1, 2], "c": list(cols)}
    if fz:
        d["fz"] = fz
    return d


def test_freeze_counts_the_columns_as_the_panel_shows_them():
    d = _table("ABCDE", 3)
    _freeze_columns(d, 1)
    assert d["fz"] == 1                                    # (in place of the workbook's three)
    d = _table("ABCDE", 3)
    _freeze_columns(d, 0)
    assert "fz" not in d                                   # 0: none
    d = _table("ABCDE")
    _freeze_columns(d, 5)
    assert "fz" not in d                                   # nothing to scroll past
    d = _table("ABCDE")
    _freeze_columns(d, 2, lambda c: c == "B")
    assert d["fz"] == 3                                    # B is one Excel hides, shown: not counted
    d = _table(["A", "Broker bid", "C", "D"])
    _freeze_columns(d, 2, lambda c: c in ("A", "Broker bid"))
    assert d["fz"] == 3                                    # (a column the dashboard adds is never one Excel hides)
    for bad in (True, "2", None, 1.5):
        d = _table("ABC", 2)
        _freeze_columns(d, bad)
        assert d["fz"] == 2
    _freeze_columns(None, 1)
    _freeze_columns({"rows": []}, 1)


def _panel(svc, p, view="viop", show_hidden=False):
    """One panel of a page made as its page makes it (the shared calculation)."""
    v = svc.view_index[view]
    book = svc.books[v["book"]]

    def run():
        calc = svc._calc(None, book)
        loc = numfmt.get_locale(svc.settings.locale)
        return svc._panel(p, v, book, calc, svc.renderers[book.id], loc, None, None, p.get("sheet", v["sheet"]), [],
                          show_hidden, False)

    return svc.et.call(run)


def test_freeze_limit_and_fit_of_a_views_table(service):
    """``"freeze": n`` sets the frozen columns as the panel shows them - the columns Excel hides shown as well, n still
    names the same ones -, 0 none; ``limit`` and ``fit`` go to the browser as they are; a table of the dashboard's own
    (DİBS Trading's summary) takes ``freeze`` too.  No cell changes."""
    base = {"id": "F", "type": "table", "range": "B14:G35"}             # VİOP's USD OIS curve: Excel hides its column C
    plain = _panel(service, dict(base))
    two = _panel(service, dict(base, freeze=2, limit={"rows": 5}, fit=True))
    assert plain["data"]["c"] == two["data"]["c"] == ["B", "D", "E", "F", "G"]
    assert two["data"]["fz"] == 2 and two["limit"] == {"rows": 5} and two["fit"] is True
    assert "limit" not in plain and "fit" not in plain
    assert two["data"]["rows"] == plain["data"]["rows"]                  # (nothing but the frozen columns)
    shown = _panel(service, dict(base, freeze=2), show_hidden=True)
    assert shown["data"]["c"][:3] == ["B", "C", "D"] and shown["data"]["fz"] == 3
    assert "fz" not in _panel(service, dict(base, freeze=0))["data"]
    rv = {"id": "R", "type": "table", "range": "A4:BQ54"}               # DİBS RV: the workbook freezes its first columns
    wb = _panel(service, dict(rv), "dibs")["data"]
    one = _panel(service, dict(rv, freeze=1), "dibs")["data"]
    assert wb.get("fz", 0) > 1 and one["fz"] == 1 and one["rows"] == wb["rows"]
    gen = _panel(service, {"id": "L", "type": "generated", "source": "dibs_trading", "title": "Özet", "freeze": 2}, "dibslive")
    if gen["data"]["rows"] and len(gen["data"]["rows"][0]) > 2:
        assert gen["data"]["fz"] == 2
    else:                                                             # (an empty trading list: nothing to freeze)
        assert "fz" not in gen["data"]


def test_the_page_answer_with_columns_of_panels_and_the_options(service):
    """A page whose tab has a column of panels: the answer's tab lists its panels flat and the column in ``stacks``; each
    panel's options on its entry."""
    fix = normalize({"id": "dz-test", "title": "Düzen test", "group": "Test", "book": "tto", "sheet": "VIOP", "order": 9998,
                     "panels": [{"id": "F1", "type": "table", "range": "B14:G35", "freeze": 1, "limit": {"rows": 4},
                                 "fit": True, "title": "Bir"},
                                {"id": "F2", "type": "table", "range": "B14:G20", "title": "İki"},
                                {"id": "F3", "type": "table", "range": "B21:G27", "title": "Üç"}],
                     "sections": [{"id": "s", "title": "S", "panels": ["F1", ["F2", "F3"]]},
                                  {"id": "t", "title": "T", "panels": ["F3"]}]})
    service.view_index[fix["id"]] = fix
    try:
        page = service.view(None, fix["id"])
    finally:
        del service.view_index[fix["id"]]
    assert page["sections"][0] == {"id": "s", "title": "S", "note": None, "panels": ["F1", "F2", "F3"], "stacks": [["F2", "F3"]]}
    assert page["sections"][1] == {"id": "t", "title": "T", "note": None, "panels": ["F3"]}
    p = {x["id"]: x for x in page["panels"]}
    assert p["F1"]["data"]["fz"] == 1 and p["F1"]["limit"] == {"rows": 4} and p["F1"]["fit"] is True
    assert "limit" not in p["F2"] and "fit" not in p["F2"]


# ---------------------------------------------------------------------------------------------- the two-way notes
def test_a_two_way_note_comes_with_its_groups_named_for_the_page_to_say_it_once(service):
    """The note under a two-way table is what it was (the table's own words, then the groups' notes); ``tw`` names those
    groups' notes one by one, so that the page says one only under the first table on screen that shows it (Manuel
    Tahvil's four tables of one group: once).  A table of no group has none."""
    page = service.view(None, "manuel")
    p = {x["id"]: x for x in page["panels"]}
    group = next(g for g in service.twoway.groups.values() if g.id == "manuel")
    with_note = [pid for pid in ("B2", "B3", "B4", "B5") if p[pid].get("tw")]
    assert len(with_note) >= 2
    for pid in with_note:
        assert p[pid]["tw"] == [group.note] and p[pid]["note"].endswith(group.note)
        assert p[pid]["note"].count(group.note) == 1
    calc = {x["id"]: x for x in service.view(None, "calc")["panels"]}
    # (two groups of one text on one table: the text once, as before)
    assert calc["B5"]["tw"] == [calc["B5"]["tw"][0]] and calc["B5"]["note"].count(calc["B5"]["tw"][0]) == 1
    fwd = {x["id"]: x for x in service.view(None, "forward")["panels"]}
    assert "tw" not in fwd["B1"] and fwd["FR1"]["tw"] and fwd["FR2"]["tw"] and fwd["FR1"]["tw"] != fwd["FR2"]["tw"]
