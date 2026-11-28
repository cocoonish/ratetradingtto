"""Two-way tables (``tto/twoway.py``; the desk, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak
tablolar bu şekilde olmalı"): the mechanism on a small table of its own, built for these tests - a sheet ``EK_TWT`` with
two rows, bid and ask, and three ways of giving a row-side's value:

* ``x`` (C / D) in place: the page's input, its formula default 1 - or the x the typed y / z gives;
* ``y`` = 2x + base (E / F), kept in K / L;
* ``z`` = y + 100 (G / H), kept in M / N.

A desk-wide (shared) group of one cell in row 6.  What the forward quote matrices do with it: ``test_fwd_twoway.py``."""
from __future__ import annotations

import logging

import pytest

from conftest import cell, make_service
from tto import extras, views
from tto.twoway import ROW_CYCLE

SHEET = "EK_TWT"
ROWS = (3, 4)
BASE = {3: 10.0, 4: 20.0}
#: per side: (x, y, z, y's store, z's store)
SIDES = (("C", "E", "G", "K", "M"), ("D", "F", "H", "L", "N"))


def _toy(model) -> None:
    b = extras.SheetBuilder(model, SHEET)
    b.title("A1", "İKİ YÖNLÜ TEST")
    b.head("A2", ["Satır", "Taban", "x bid", "x ask", "y bid", "y ask", "z bid", "z ask"])
    b.head("K2", ["y bid (yazılan)", "y ask (yazılan)", "z bid (yazılan)", "z ask (yazılan)"])
    for r in ROWS:
        b.set("A%d" % r, "Satır %d" % r)
        b.set("B%d" % r, BASE[r])
        for x, y, z, ys, zs in SIDES:
            f = {"r": r, "x": x, "y": y, "z": z, "ys": ys, "zs": zs}
            b.input("%(x)s%(r)d" % f, '=IF(AND(ISBLANK($%(ys)s%(r)d),ISBLANK($%(zs)s%(r)d)),1,'
                                      'IF(ISBLANK($%(ys)s%(r)d),($%(zs)s%(r)d-100-$B%(r)d)/2,($%(ys)s%(r)d-$B%(r)d)/2))' % f)
            b.set("%(y)s%(r)d" % f, '=IF(ISBLANK($%(ys)s%(r)d),IF(ISBLANK($%(zs)s%(r)d),2*$%(x)s%(r)d+$B%(r)d,$%(zs)s%(r)d-100),'
                                    '$%(ys)s%(r)d)' % f)
            b.set("%(z)s%(r)d" % f, '=IF(ISBLANK($%(zs)s%(r)d),$%(y)s%(r)d+100,$%(zs)s%(r)d)' % f)
            b.input("%(ys)s%(r)d" % f, None)
            b.input("%(zs)s%(r)d" % f, None)
        b.set("P%d" % r, "=$G%d/10" % r)          # (a cell computed from the row: z bid / 10)
    # the desk's: x6 (default 5) and y6 = 2x6, kept in K6
    b.set("A6", "Masa")
    b.set("B6", 0.0)
    b.input("C6", '=IF(ISBLANK($K6),5,($K6-$B6)/2)')
    b.set("E6", '=IF(ISBLANK($K6),2*$C6+$B6,$K6)')
    b.input("K6", None)
    # free cells for the declarations that cannot be used (row 10 on, B9) and a cell a formula may read (B8)
    b.input("B8", 7.0)
    b.input("B9", 1.0)
    b.set("C10", "=1")
    b.set("E10", "=2")
    b.set("G10", "=3")
    b.set("K10", 5.0)                    # (a store that is not blank)


VIEW = {"id": "twt", "title": "İki yönlü test", "group": "Test", "book": "tto", "sheet": SHEET, "order": 9999,
        "inputs": [{"range": "C3:D4", "scope": "user", "group": "twt-x", "kind": "number", "label": "x"},
                   {"range": "C6", "scope": "shared", "group": "twt-sx", "kind": "number", "label": "x (masa)"},
                   {"range": "B8", "scope": "user", "group": "twt-b8", "kind": "number", "label": "B8"},
                   {"range": "B9", "scope": "user", "group": "twt-b9", "kind": "number", "label": "B9"}],
        "twoway": [{"id": "twt", "label": "TEST", "note": "Test: x, y ya da z - yazılan kalır.",
                    "members": [{"name": "x", "range": "C3:D4"},
                                {"name": "y", "range": "E3:F4", "store": "K3:L4"},
                                {"name": "z", "range": "G3:H4", "store": "M3:N4"}]},
                   {"id": "twt-masa", "scope": "shared",
                    "members": [{"name": "x", "range": "C6"}, {"name": "y", "range": "E6", "store": "K6"}]}],
        "panels": [{"id": "T1", "type": "table", "range": "A1:H4", "copyable": True},
                   {"id": "T4", "type": "table", "range": "E2:E4", "copyable": True, "title": "Yalnız y bid"},
                   {"id": "T2", "type": "table", "range": "A6:E6"},
                   {"id": "T3", "type": "table", "range": "K2:N4", "hidden": True, "keep_title": True,
                    "title": "Yardımcı · yazılanlar"}],
        "sections": [], "pinned": []}


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(extras._BUILDERS, "tto", tuple(extras._BUILDERS["tto"]) + ((SHEET, lambda model: None, _toy),))
        loaded = views.load_views()
        mp.setattr("tto.service.load_views", lambda: loaded + [dict(VIEW)])
        s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def put(svc, user, cells, adhoc=False):
    return svc.set_inputs(user, "tto", [{"ref": "%s!%s" % (SHEET, ref), "value": v} for ref, v in cells.items()], adhoc)


def row(svc, user, r, side=0):
    x, y, z, _, _ = SIDES[side]
    return [cell(svc, "%s!%s%d" % (SHEET, c, r), user) for c in (x, y, z)]


def stored(svc, user):
    return {ref.split("!")[1]: v for (_, ref), v in svc.store.user_inputs(user, "tto").items() if ref.startswith(SHEET + "!")}


def marks(svc, user, pid="T1"):
    p = next(p for p in svc.view(user, "twt", pid == "T3")["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


# ---------------------------------------------------------------------------------------------- the declaration
def test_the_groups_their_stores_and_the_pages_own(svc):
    """Every group of the pages can be used; a store is an input of the group's scope (declared here, not in the page's
    inputs), a member's cell is the group's; the in-place member keeps its input."""
    assert svc.twoway.problems == {}
    assert {"twt", "twt-masa"} <= set(svc.twoway.groups)
    book = svc.books["tto"]
    k3 = book.inputs[book.cell(SHEET + "!K3")]
    assert (k3.scope, k3.kind, k3.view) == ("user", "number", "twt") and k3.label == "TEST · y (iki yönlü: yazılan değer)"
    assert book.inputs[book.cell(SHEET + "!K6")].scope == "shared"
    assert book.cell(SHEET + "!E3") not in book.inputs and book.twoway[book.cell(SHEET + "!E3")].member.name == "y"
    h = book.twoway[book.cell(SHEET + "!M4")]
    assert h.store and h.member.name == "z" and book.ref(*h.member_cell) == SHEET + "!G4"
    assert book.inputs[book.cell(SHEET + "!C3")].group == "twt-x"                   # (in place: the page's own input)


def test_declarations_that_cannot_be_used_are_left_out_with_the_reason(svc, caplog):
    """A declaration that cannot work is left out - the reason in ``problems`` and the log -, nothing of it declared."""
    from tto.twoway import TwoWay
    book = svc.books["tto"]
    before = dict(book.inputs)

    def bad(*members, **kw):
        return dict({"id": "bad", "sheet": SHEET, "members": list(members)}, **kw)

    specs = {
        "shape": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "C10:E10", "store": "P10:R10"}),
        "store": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "C10", "store": "K10"}),
        "input": bad({"name": "a", "range": "C10"}, {"name": "b", "range": "E10", "store": "P10"}),
        "twice": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "B9"}),
        "member": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "B8", "store": "P11"}),
        "formula": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "D10", "store": "P10"}),
        "other": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "E3", "store": "P12"}),
        "one": bad({"name": "a", "range": "B8"}),
        "scope": bad({"name": "a", "range": "B8"}, {"name": "b", "range": "E10", "store": "P10"}, scope="shared"),
    }
    with caplog.at_level(logging.WARNING, logger="tto"):
        tw = TwoWay(svc, [{"id": k, "book": "tto", "sheet": SHEET, "twoway": [v]} for k, v in specs.items()])
    assert set(tw.problems) == {"%s/bad" % k for k in specs} and not tw.groups
    assert "biçimi" in tw.problems["shape/bad"] and "boş değil" in tw.problems["store/bad"]
    assert "girdisi değil" in tw.problems["input/bad"] and "en fazla bir üye" in tw.problems["twice/bad"]
    assert "iki kez" in tw.problems["member/bad"] and "formül değil" in tw.problems["formula/bad"]
    assert "başka bir iki yönlü grubun" in tw.problems["other/bad"] and "en az iki" in tw.problems["one/bad"]
    assert "user bir girdi, grup shared" in tw.problems["scope/bad"]
    assert book.inputs == before and sum("iki yönlü tablo kullanılamaz" in r.getMessage() for r in caplog.records) == len(specs)


# ---------------------------------------------------------------------------------------------- typing
def test_each_member_typed_gives_the_others_and_stands(svc):
    """A value typed into any member is its row-side's anchor: shown exactly, the others worked out from it; the other
    side and the other row keep their own; typed back as its own kind, a computed value gives the same row."""
    u = svc.login("tw üye")["user"]
    assert row(svc, u, 3) == [1.0, 12.0, 112.0]                                     # nothing typed: x's default
    put(svc, u, {"E3": "30"})                                                       # y bid
    assert row(svc, u, 3) == [10.0, 30.0, 130.0] and row(svc, u, 3, 1) == [1.0, 12.0, 112.0] and row(svc, u, 4) == [1.0, 22.0, 122.0]
    put(svc, u, {"H4": "250"})                                                      # z ask of the other row
    assert row(svc, u, 4, 1) == [65.0, 150.0, 250.0] and stored(svc, u) == {"K3": 30.0, "N4": 250.0}
    for ref, value in (("C3", 7.5), ("E3", 99.0), ("G3", -40.0)):
        put(svc, u, {ref: value})
        got = row(svc, u, 3)
        for c, v in zip("CEG", got):
            put(svc, u, {"%s3" % c: v})                                             # each computed value typed back
            assert row(svc, u, 3) == pytest.approx(got, abs=1e-9), (ref, c)
    assert row(svc, u, 3, 1) == [1.0, 12.0, 112.0]


def test_the_last_typed_wins(svc):
    """Typing a member empties its row-side's other stores (the in-place member's own value too): one value per
    row-side, the one typed last."""
    u = svc.login("tw son")["user"]
    put(svc, u, {"C3": "4"})
    assert stored(svc, u) == {"C3": 4.0} and row(svc, u, 3) == [4.0, 18.0, 118.0]
    put(svc, u, {"G3": "200"})
    assert stored(svc, u) == {"M3": 200.0} and row(svc, u, 3) == [45.0, 100.0, 200.0]
    put(svc, u, {"E3": "50"})
    assert stored(svc, u) == {"K3": 50.0} and row(svc, u, 3) == [20.0, 50.0, 150.0]
    res = put(svc, u, {"C3": "6"})
    assert stored(svc, u) == {"C3": 6.0} and res["applied"] == 1 and res["errors"] == []
    # a value refused leaves the row-side as it was
    res = put(svc, u, {"G3": "9" * 2001})
    assert res["errors"] == [SHEET + "!G3: girdi çok uzun"] and stored(svc, u) == {"C3": 6.0}


def test_delete_on_any_cell_of_a_row_side_takes_it_back_to_its_default(svc):
    """Delete on the anchor - or on a member worked out from it -, "Kendi girdimi sil" / "formüle dön" (a reset of any of
    its cells) and "Girdilerimi sıfırla": the row-side's stores are emptied, its default shows."""
    u = svc.login("tw sil")["user"]
    for typed, deleted in (("E3", "E3"), ("E3", "C3"), ("C3", "G3"), ("G3", "E3")):
        put(svc, u, {typed: "40"})
        res = put(svc, u, {deleted: ""})
        assert stored(svc, u) == {} and row(svc, u, 3) == [1.0, 12.0, 112.0] and res["applied"] == 1, (typed, deleted)
    put(svc, u, {"G3": "300", "F4": "70"})
    res = svc.reset_inputs(u, "tto", [SHEET + "!C3"])                               # a member worked out from z
    assert res["reset"] == 1 and stored(svc, u) == {"L4": 70.0}
    res = svc.reset_inputs(u, "tto", [SHEET + "!K4:L4"])                            # a store itself (the helper table)
    assert res["reset"] == 1 and stored(svc, u) == {}
    put(svc, u, {"G3": "300", "F4": "70"})
    assert svc.reset_inputs(u, "tto")["reset"] == 2 and stored(svc, u) == {}


def test_a_pasted_block(svc):
    """A block pasted (Excel): the cells of a row-side are one value - the last one of the write (left to right) is its
    anchor, a blank beside it clears nothing; a row-side with blanks only goes back to its default; the stores, never
    shown, take nothing directly from a paste that does not reach them."""
    u = svc.login("tw yapıştır")["user"]
    put(svc, u, {"C4": "9", "F3": "44"})
    res = svc.paste(u, "tto", SHEET + "!C3", "2\t\t30\t\t\t\n\t\t\t\t\t")
    # row 3: x bid 2, then y bid 30 -> y wins; ask: nothing but blanks -> back to default; row 4: only blanks
    assert stored(svc, u) == {"K3": 30.0} and row(svc, u, 3) == [10.0, 30.0, 130.0] and row(svc, u, 3, 1) == [1.0, 12.0, 112.0]
    assert row(svc, u, 4) == [1.0, 22.0, 122.0] and res["errors"] == [] and res["rows"] == 2
    # a column pasted into one member: each row's anchor
    svc.paste(u, "tto", SHEET + "!G3", "150\n160")
    assert stored(svc, u) == {"M3": 150.0, "M4": 160.0} and row(svc, u, 4) == [20.0, 60.0, 160.0]


def test_formulas_on_a_member(svc):
    """A formula typed into a member: kept on its store, the cell shows ƒ and its text; it follows what it reads; one
    that reads its own row-side is a cycle, refused with the member's cells named (not the store's)."""
    u = svc.login("tw formül")["user"]
    res = put(svc, u, {"E4": "=B8*10"})
    assert res["errors"] == [] and row(svc, u, 4) == [25.0, 70.0, 170.0]
    assert svc.store.user_formulas(u)[("tto", SHEET + "!K4")] == "=B8*10"
    _, m = marks(svc, u)
    assert m["E4"]["ff"] == "=B8*10" and m["E4"]["an"] == "x, z" and "ff" not in m["G4"]
    put(svc, u, {"B8": "8"})
    assert row(svc, u, 4) == [30.0, 80.0, 180.0]
    res = put(svc, u, {"G3": "=C3+1"})
    assert res["applied"] == 0 and len(res["errors"]) == 1 and stored(svc, u).get("M3") is None
    err = res["errors"][0]
    assert err.startswith(SHEET + "!G3: döngüsel başvuru:") and SHEET + "!C3" in err and "!M3" not in err, err
    # another side's member is no cycle: bid = ask - 5
    res = put(svc, u, {"E3": "=F3-5"})
    assert res["errors"] == [] and row(svc, u, 3)[1] == 7.0
    info = svc.cell_info(u, "tto", SHEET + "!E3")
    assert info["input"]["formula"] == "=F3-5" and info["input"]["twoway"] == {"group": "TEST", "member": "y",
                                                                             "anchor": {"member": "y", "ref": SHEET + "!E3"}}
    put(svc, u, {"C3": "2"})                                                         # a value over it: the formula goes
    assert ("tto", SHEET + "!K3") not in svc.store.user_formulas(u) and row(svc, u, 3) == [2.0, 14.0, 114.0]


def test_a_formula_reading_its_own_row_is_refused_as_typed(svc):
    """A formula typed into a member that reads its own row-side is a cycle once it stands (the row's other members are
    then worked out from it): refused as typed, the reason naming the members' cells - also when what it reads is the
    in-place member holding a typed value now (the write empties it; its formula default then reads the new store), and
    when it reads a cell computed from the row (P = z / 10).  The other side and the other row may be read."""
    u = svc.login("tw kendi satırı")["user"]
    put(svc, u, {"C3": "4"})                                                         # x typed: the row's value
    res = put(svc, u, {"E3": "=C3*3"})
    assert res["applied"] == 0 and res["errors"] == [
        SHEET + "!E3: " + ROW_CYCLE % " → ".join([SHEET + "!E3", SHEET + "!C3", SHEET + "!E3"])]
    assert stored(svc, u) == {"C3": 4.0} and row(svc, u, 3) == [4.0, 18.0, 118.0]   # the row as it was
    for text, read in (("=P3*2", "P3"), ("=G3-100", "G3"), ("=M3+1", "G3")):        # (a store said as its member)
        res = put(svc, u, {"E3": text})
        assert len(res["errors"]) == 1 and res["errors"][0].startswith(SHEET + "!E3: döngüsel başvuru: ")
        assert "%s!%s" % (SHEET, read) in res["errors"][0] and "!K3" not in res["errors"][0] and "!M3" not in res["errors"][0], res
    assert stored(svc, u) == {"C3": 4.0}
    res = put(svc, u, {"E3": "=D3*3+C4"})                                            # the ask side, another row: fine
    assert res["errors"] == [] and row(svc, u, 3)[1] == 4.0 and stored(svc, u) == {"K3": 4.0}


def test_a_stored_formula_reading_its_own_row_stops_naming_the_members(svc):
    """A formula kept on a store that reads its own row-side (a scenario saved before it was refused): taken, it
    stops with #CALC! (its value keeps moving) - the reason names the members' cells, never the store."""
    u = svc.login("tw durdu")["user"]
    svc.store.save_scenario(u, "eski formül", {("tto", SHEET + "!K3"): 50.0}, {("tto", SHEET + "!K3"): "=C3*3"})
    svc.load_scenario(u, "eski formül")
    v = cell(svc, SHEET + "!E3", u)
    err = svc.cell_info(u, "tto", SHEET + "!E3")["input"].get("error") or ""
    assert getattr(v, "code", None) == "#CALC!" and err.startswith(
        "Döngüsel başvuru: %s!E3 → %s!C3 → %s!E3 - formül durduruldu" % (SHEET, SHEET, SHEET)) and "!K3" not in err, (v, err)
    _, m = marks(svc, u)
    assert "!K3" not in m["E3"]["fe"] and "%s!E3" % SHEET in m["E3"]["fe"]


def test_a_formula_typed_into_a_cell_that_became_a_member_stays_live(svc, caplog):
    """An input formula typed into a cell before the cell became a two-way member (kept at that cell): not dropped as
    "no input any more" - moved with its value to the member's store when the user's values are read (logged), the
    row-side's other values emptied, and live there: what it reads changes, the row follows; ƒ on the member."""
    u = svc.login("tw eski formül")["user"]
    svc.store.set_user_inputs(u, "tto", {SHEET + "!E4": 70.0, SHEET + "!C4": 3.0}, {SHEET + "!E4": "=B8*10"})
    with caplog.at_level(logging.INFO, logger="tto"):
        svc.et.call(svc._reload_user, u)
    assert stored(svc, u) == {"K4": 70.0} and svc.store.user_formulas(u) == {("tto", SHEET + "!K4"): "=B8*10"}
    assert any("%s!E4 → %s!K4 (formülüyle)" % (SHEET, SHEET) in r.getMessage() for r in caplog.records)
    assert not any("girdi formülü kaldırıldı" in r.getMessage() and "!E4" in r.getMessage() for r in caplog.records)
    put(svc, u, {"B8": "9"})
    assert row(svc, u, 4) == [35.0, 90.0, 190.0]
    _, m = marks(svc, u)
    assert m["E4"]["ff"] == "=B8*10" and m["E4"]["an"] == "x, z"


def test_a_copy_opened_before_its_table_was_two_way(svc, caplog):
    """Temporary copies are kept on the server, by cell: one opened before its table was two-way holds a value at a
    member's own cell (the input it was then).  Read again, it is the copy's value of its row - into the member's store,
    the row's other stores the copy's own empty values, an in-place value of the copy the table's again -, saved so,
    logged; a store the copy holds already stands (the old value goes)."""
    u = svc.login("tw eski kopya")["user"]
    cid = svc.copy_action(u, "open", {"view": "twt", "panel": "T1"})["copy"]["id"]
    key = "copies." + u
    kept = svc.store.get(key)
    kept["items"][0]["values"] = {SHEET + "!E3": 50.0, SHEET + "!D4": 2.0, SHEET + "!H4": 300.0, SHEET + "!E4": 70.0,
                                  SHEET + "!M4": 150.0}
    svc.store.put(key, kept)
    svc.copies._items.pop(u, None)                                                   # (read again, as after a restart)
    with caplog.at_level(logging.INFO, logger="tto"):
        values = next(c for c in svc.copies.items(u) if c.id == cid).values
    assert values == {SHEET + "!K3": 50.0, SHEET + "!M3": None,                     # row 3 bid: y
                      SHEET + "!N4": 300.0, SHEET + "!L4": None,                    # row 4 ask: z (the copy's x the table's)
                      SHEET + "!M4": 150.0}                                        # row 4 bid: its store stands, E4 goes
    assert svc.store.get(key)["items"][0]["values"] == values
    assert any("geçici kopyası %s" % cid in r.getMessage() for r in caplog.records)
    pane = next(p for p in svc.view(u, "twt")["panels"] if (p.get("copy") or {}).get("id") == cid)["data"]
    cells = {"%s%d" % (c, r): x["t"] for r, line in zip(pane["r"], pane["rows"]) for c, x in zip(pane["c"], line)}
    assert [cells[c] for c in ("C3", "E3", "G3", "C4", "E4", "G4", "D4", "F4", "H4")] == [
        "20", "50", "150", "15", "50", "150", "90", "200", "300"]
    assert row(svc, u, 3) == [1.0, 12.0, 112.0]                                     # the table's own
    svc.copy_action(u, "close", {"copy": cid})


def test_a_copy_showing_one_member_of_a_row_holds_the_whole_row(svc):
    """A copy of a table that shows only some of a row's members (T4: y bid alone): every store of the row-side is the
    copy's input - a value the table holds in another member (z) is the copy's to begin with, a member typed in the copy
    clears it in the copy's layer (it no longer shows through), Delete follows the table again."""
    u = svc.login("tw kopya tek sütun")["user"]
    put(svc, u, {"G3": "200"})                                                       # z bid typed in the table
    cid = svc.copy_action(u, "open", {"view": "twt", "panel": "T4"})["copy"]["id"]
    book = svc.books["tto"]
    assert {book.ref(*c) for c in svc.copies.tables[("twt", "T4")].cells} == {
        "%s!%s" % (SHEET, c) for c in ("C3", "K3", "M3", "C4", "K4", "M4")}

    def own():
        return next(c for c in svc.copies.items(u) if c.id == cid).values

    def in_copy(ref):
        return svc.cell_info(u, "tto", SHEET + "!" + ref, copy=cid)["cell"].get("v")

    assert own() == {SHEET + "!M3": 200.0} and [in_copy(c) for c in ("C3", "E3", "G3")] == [45.0, 100.0, 200.0]
    res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": SHEET + "!E3", "value": "50"}]})
    assert res["errors"] == [] and own() == {SHEET + "!K3": 50.0, SHEET + "!M3": None}
    assert [in_copy(c) for c in ("C3", "E3", "G3")] == [20.0, 50.0, 150.0]          # z from the copy's y, not 200
    assert row(svc, u, 3) == [45.0, 100.0, 200.0]                                   # the table's own
    svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": SHEET + "!E3", "value": ""}]})
    assert own() == {} and in_copy("G3") == 200.0 and in_copy("E3") == 100.0
    svc.copy_action(u, "close", {"copy": cid})


def test_the_page_marks_the_typed_value_and_says_what_the_table_does(svc):
    """The page: every member an input (``i``); the anchor ``m`` and ``an`` (the members worked out from it), the others
    ``ao`` (the anchor's name and cell); a row-side with nothing typed has no mark; the group's note under the table;
    "Girdilerim" lists a member typed by its own cell."""
    u = svc.login("tw işaret")["user"]
    put(svc, u, {"G4": "180"})
    p, m = marks(svc, u)
    assert p["note"] == "Test: x, y ya da z - yazılan kalır."
    assert all(m[c]["i"] == "u" for c in ("C3", "D3", "E3", "F3", "G3", "H3", "C4", "H4"))
    assert m["G4"]["m"] == 1 and m["G4"]["an"] == "x, y" and "ao" not in m["G4"]
    assert m["C4"]["ao"] == "z · G4" and m["E4"]["ao"] == "z · G4" and "m" not in m["E4"] and "an" not in m["C4"]
    assert not any(k in m[c] for c in ("C3", "E3", "G3", "H4") for k in ("m", "an", "ao"))
    put(svc, u, {"C4": "3"})
    _, m = marks(svc, u)
    assert m["C4"]["an"] == "y, z" and m["C4"]["m"] == 1 and m["G4"]["ao"] == "x · C4"
    # (Girdilerim's own fields since 28.11.2026 - when typed, the pages it shows on: A6 / A7 - aside)
    core = lambda xs: [{k: v for k, v in x.items() if k not in ("at", "pages", "market", "old", "hand")} for x in xs]  # noqa: E731
    mine = [x for x in svc.my_inputs(u)["inputs"] if x["ref"].startswith(SHEET)]
    assert core(mine) == [{"book": "tto", "ref": SHEET + "!C4", "value": 3.0, "label": "x"}] and mine[0]["at"]
    put(svc, u, {"F3": "33"})
    mine = [x for x in svc.my_inputs(u)["inputs"] if x["ref"].startswith(SHEET + "!F")]
    assert core(mine) == [{"book": "tto", "ref": SHEET + "!F3", "store": SHEET + "!L3", "value": 33.0,
                           "label": "TEST · y (iki yönlü: yazılan değer)"}]
    _, helper = marks(svc, u, "T3")                                                 # the stores, in the helper table
    assert helper["L3"]["i"] == "u" and helper["L3"]["m"] == 1 and "an" not in helper["L3"]


def test_a_scenario_keeps_the_typed_values(svc):
    """Senaryolar: saved with the stores, loaded back as they were - the anchors and the values they give."""
    u = svc.login("tw senaryo")["user"]
    put(svc, u, {"E3": "40", "D3": "2", "G4": "130"})
    want = [row(svc, u, 3), row(svc, u, 3, 1), row(svc, u, 4)]
    svc.save_scenario(u, "iki yönlü")
    put(svc, u, {"C3": "1", "H3": "500", "G4": ""})
    svc.load_scenario(u, "iki yönlü")
    assert stored(svc, u) == {"K3": 40.0, "D3": 2.0, "M4": 130.0}
    assert [row(svc, u, 3), row(svc, u, 3, 1), row(svc, u, 4)] == want


def test_a_value_typed_over_a_member_before_becomes_its_row_sides_typed_value(svc):
    """A value an earlier version kept at a member's own cell ("Elle değer" over a formula): read as that row-side's
    anchor - moved to its store with its formula, the row-side's other stores emptied, once."""
    u = svc.login("tw eski")["user"]
    put(svc, u, {"C3": "3", "D4": "5"})
    svc.store.set_user_inputs(u, "tto", {SHEET + "!E3": 60.0, SHEET + "!H4": 300.0, SHEET + "!G3": 1.0})
    svc.et.call(svc._reload_user, u)
    # (row 3's bid had y and z typed over: the later member, z, is its value; row 4's ask, z)
    assert stored(svc, u) == {"M3": 1.0, "N4": 300.0} and row(svc, u, 3) == [-54.5, -99.0, 1.0]
    assert row(svc, u, 4, 1) == [90.0, 200.0, 300.0]
    book = svc.books["tto"]
    assert book.cell(SHEET + "!E3") not in book.inputs and book.cell(SHEET + "!H4") not in book.inputs   # (no "Elle değer")
    _, m = marks(svc, u)
    assert m["G3"]["an"] == "x, y" and m["H4"]["an"] == "x, y"


def test_a_temporary_copy(svc):
    """A copy of the table: a member typed there is the copy's row-side value - its store the copy's own, the others the
    copy's own empty values -; the table stays as it is; Delete in the copy follows the table again.  The in-place member
    cannot go back to its formula in a copy while the table holds a value typed there: refused, with the reason."""
    u = svc.login("tw kopya")["user"]
    opened = svc.copy_action(u, "open", {"view": "twt", "panel": "T1"})["copy"]
    cid = opened["id"]

    def copy_put(cells):
        return svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": SHEET + "!" + k, "value": v} for k, v in cells.items()]})

    def own():
        return next(c for c in svc.copies.items(u) if c.id == cid).values

    res = copy_put({"E3": "50", "G4": "170"})
    assert res["errors"] == [] and own() == {SHEET + "!K3": 50.0, SHEET + "!M3": None, SHEET + "!M4": 170.0, SHEET + "!K4": None}
    assert row(svc, u, 3) == [1.0, 12.0, 112.0]                                     # the table's own
    copy = svc.view(u, "twt")["panels"]
    pane = next(p for p in copy if (p.get("copy") or {}).get("id") == cid)
    d = pane["data"]
    cells = {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}
    assert cells["E3"]["t"] == "50" and cells["C3"]["t"] == "20" and cells["G3"]["t"] == "150" and cells["E3"]["an"] == "x, z"
    assert cells["C4"]["t"] == "25" and "ro" not in cells["E3"]
    res = copy_put({"C3": ""})                                                      # Delete: the table's row again
    assert SHEET + "!K3" not in own() and res["applied"] == 1
    # the table's typed x (in place) cannot be taken back to its formula in the copy
    put(svc, u, {"C4": "9"})
    res = copy_put({"E4": "1"})
    assert res["errors"] == [SHEET + "!E4: kopyada yazılamaz: tablonun kendisinde bu satıra x yazılmış (%s!C4) - kopya onu "
                             "formülüne döndüremez; kopyada başka bir değer yazmak için önce tablodaki değeri silin" % SHEET]
    res = copy_put({"C4": "12"})                                                    # the in-place member itself: fine
    assert res["errors"] == [] and own()[SHEET + "!C4"] == 12.0 and own()[SHEET + "!M4"] is None
    svc.copy_action(u, "close", {"copy": cid})


def test_a_desk_wide_group(svc):
    """A shared group: a member typed is the desk's - everyone sees the value and its anchor; the last typed wins for
    everyone; a reset of the desk's value takes the row back to its default."""
    a, b = svc.login("tw masa a")["user"], svc.login("tw masa b")["user"]
    assert cell(svc, SHEET + "!C6", b) == 5.0
    put(svc, a, {"E6": "30"})
    assert cell(svc, SHEET + "!C6", b) == 15.0 and cell(svc, SHEET + "!E6") == 30.0
    _, m = marks(svc, b, "T2")
    assert m["E6"]["i"] == "s" and m["E6"]["an"] == "x" and m["C6"]["ao"] == "y · E6"
    put(svc, b, {"C6": "4"})
    assert cell(svc, SHEET + "!E6", a) == 8.0 and svc.store.shared_inputs("tto").get(("tto", SHEET + "!K6")) is None
    svc.reset_inputs(a, "tto", [SHEET + "!E6"], shared=True)
    assert cell(svc, SHEET + "!C6") == 5.0 and cell(svc, SHEET + "!E6") == 10.0


def test_a_desk_value_kept_at_a_member_before(svc):
    """The desk's value (a shared input) kept at a member's own cell from before the table was two-way, with its
    formula: moved to the member's store at the start (``adopt_shared``), the row's other stores emptied."""
    a = svc.login("tw masa eski")["user"]
    svc.store.set_shared_inputs("tto", {SHEET + "!E6": 30.0, SHEET + "!C6": 4.0}, a, {SHEET + "!E6": "=B6+30"})
    svc.twoway.adopt_shared(svc.books["tto"])
    shared = {ref: v for (_, ref), v in svc.store.shared_inputs("tto").items() if ref.startswith(SHEET)}
    assert shared == {SHEET + "!K6": 30.0} and svc.store.shared_formulas("tto") == {("tto", SHEET + "!K6"): "=B6+30"}
    svc.reset_inputs(a, "tto", [SHEET + "!E6"], shared=True)
    assert {ref for (_, ref) in svc.store.shared_inputs("tto") if ref.startswith(SHEET)} == set()


def test_the_http_api(svc):
    """``/api/inputs``, ``/api/paste``, ``/api/reset`` and ``/api/cell`` on a member (last: the test client stops the
    service)."""
    from starlette.testclient import TestClient

    from conftest import auth
    from tto.server import create_app
    h = auth(svc, "tw http")
    u = svc.login("tw http")["user"]
    with TestClient(create_app(svc)) as client:
        res = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": SHEET + "!G3", "value": "150"}]}, headers=h).json()
        assert res["applied"] == 1 and res["errors"] == []
        got = client.get("/api/cell", params={"book": "tto", "ref": SHEET + "!G3"}, headers=h).json()
        assert got["input"]["twoway"]["anchor"] == {"member": "z", "ref": SHEET + "!G3"} and got["cell"]["an"] == "x, y"
        res = client.post("/api/paste", json={"book": "tto", "anchor": SHEET + "!E3", "text": "44"}, headers=h).json()
        assert res["applied"] == 1 and stored(svc, u) == {"K3": 44.0}
        assert client.post("/api/reset", json={"book": "tto", "refs": [SHEET + "!C3"]}, headers=h).json()["reset"] == 1
        assert stored(svc, u) == {}
