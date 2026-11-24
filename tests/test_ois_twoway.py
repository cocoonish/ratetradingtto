"""Two-way tables of the date-to-date and OIS group (tto/twoway.py; the desk, 24.11.2026: "Yeni açtığımız tablolar kalsın
... hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar bu şekilde olmalı karışıklık olmaması için", and
of every table: "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"):

* **Masa's TARİH ARASI FAİZ / FORWARD** (MASA B59:AB70): the block's one spread (I60) or any of its 77 values that carry
  it (each curve's period rate + spread, spot → end + spread, the TRY % of both legs, both forwards, their points, the
  forward-forward points, the period's TRY %, the end forward against RET) - the one typed last gives the spread, the
  rest follows; the spread stays the bp value its other readers (FORWARD KOTASYON's general spread, EK_TARIH, Forward,
  OIS_MAIN) follow;
* **TOPLU TARİH ARASI FAİZ** (EK_TARIH): a row's spread or its "+ spread (360)";
* **MPC OIS / MPC SPREAD → PPK ADIMI** (EK_PPK): a window's rate, its O/N equivalent or its step; a pair's spread, the
  later window's rate, its O/N or its step - with their meeting when the calendar changes;
* **TÜM FORWARD / FRA** (OIS_MAIN rows 336-438): a row's end leg fill or its FRA - an FRA typed holds the start leg (its
  fill, else its market par) and gives the end leg (the desk's "Ok", 24.11.2026);
* **OIS · Nakit Akışı** (TM_OIS): the trade rate or one of its five PVs;
* **USD · FOMC** (SOFR_FOMC): a window's OIS rate, its O/N or its step (bp, or in steps of Adım); WIRP or its difference to
  the implied O/N - with their meeting.

Every value is checked against an independent calculation (the tables' formulas written out here), and a value worked
out, typed back as its own kind, gives the same row (1e-9)."""
from __future__ import annotations

import datetime as dt

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto import meetings as mt
from tto.twoway import COPY_TABLE_TYPED
from tto.xl.values import date_to_serial

KINDS = ex.TARIH_TW_KINDS                              # F N Q R S T U V W X Y
ROWS = tuple(range(ex.TARIH_TW_ROWS[0], ex.TARIH_TW_ROWS[1] + 1))
AVG = ex.TARIH_WEIGHTED                                # the weighted row (66)
STORES = {k: s for k, (s, _) in ex._tarih_tw_cols().items()}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells, book="tto"):
    res = svc.set_inputs(user, book, [{"ref": ref, "value": value} for ref, value in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def stored(svc, user, sheet, book="tto"):
    """A user's typed values on one sheet: {cell: value}."""
    return {ref.split("!", 1)[1]: v for (_, ref), v in svc.store.user_inputs(user, book).items() if ref.startswith(sheet + "!")}


def marks(svc, user, view, pid):
    p = next(p for p in svc.view(user, view, True)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


def close(a, b, tol=1e-9):
    return isinstance(a, float) and isinstance(b, float) and abs(a - b) <= tol * max(1.0, abs(b))


# ============================================================================== the declarations
def test_the_groups_their_stores_and_their_in_place_members(svc):
    """Every group of the group's pages can be used; a store is a personal input declared by its group, a member's cell a
    formula of the group; the old inputs (the block's spread, a row's spread, the window's rate, the pair's spread, the
    trade rate, the window OIS, WIRP) stay where they were, inputs in place."""
    assert svc.twoway.problems == {}
    assert {"masa-spread", "tarih-row", "ppk-window", "ppk-spread", "fra-leg", "tmois-rate", "fomc-window", "fomc-wirp"} <= set(svc.twoway.groups)
    tto, sofr = svc.books["tto"], svc.books["sofr"]
    g = svc.twoway.groups["masa-spread"]
    assert g.shape == (1, 1) and len(g.members) == 1 + len(KINDS) * len(ROWS)
    assert [m.name for m in g.members if m.own] == ["Spread (bp)"] and tto.inputs[tto.cell("MASA!I60")].group == "masa-2"
    for book, ref, member in ((tto, "MASA!CT62", "F62"), (tto, "MASA!DD68", "Y68"), (tto, "EK_TARIH!AT5", "M5"),
                              (tto, "EK_PPK!Z18", "L18"), (tto, "EK_PPK!AC17", "V17"), (tto, "TM_OIS!P4", "J5"),
                              (tto, "OIS_MAIN!%s438" % ex.FRA_TW, "S438"),
                              (sofr, "SOFR_FOMC!AI83", "AE83"), (sofr, "SOFR_FOMC!AJ74", "Q74")):
        d = book.inputs[book.cell(ref)]
        h = book.twoway[book.cell(ref)]
        assert d.scope == "user" and d.group.startswith("twoway:") and h.store and book.ref(*h.member_cell).endswith("!" + member), ref
        assert book.cell(book.ref(*h.member_cell)) not in book.inputs
    for book, ref in ((tto, "EK_TARIH!D5"), (tto, "EK_PPK!G3"), (tto, "EK_PPK!S17"), (tto, "OIS_MAIN!R336"), (tto, "TM_OIS!D3"), (sofr, "SOFR_FOMC!AB74"),
                      (sofr, "SOFR_FOMC!P83")):
        assert book.twoway[book.cell(ref)].member.own and book.inputs[book.cell(ref)].group != "adhoc", ref
    # the stores go with their meeting (typed per meeting); the members' cells stay computed
    for book, ref, kind in ((tto, "EK_PPK!Y3", "typed"), (tto, "EK_PPK!AC17", "typed"), (tto, "EK_PPK!K3", "computed"),
                            (sofr, "SOFR_FOMC!AG74", "typed"), (sofr, "SOFR_FOMC!AJ83", "typed"), (sofr, "SOFR_FOMC!Q74", "computed")):
        assert mt.place(book, *book.cell(ref))[1].kind == kind, ref


# ============================================================================== Masa: the date-to-date block
def block_parts(svc, user):
    """What the block's values are made of - none of it reads the spread: the dates' days, the spot, the USD rates at the
    two dates and the RET mid, each curve row's ACT/360 rates (D: the period, L: spot → end) and discount factors."""
    m = lambda a: cell(svc, "MASA!" + a, user)                                     # noqa: E731
    x = {a: m(a) for a in ("K60", "M60", "G60", "Q60", "U60", "W60", "Z60")}
    rows = {r: {c: m("%s%d" % (c, r)) for c in "DLHI"} for r in ROWS}
    x["w"] = [cell(svc, "OIS_MAIN!Q%d" % k, user) for k in (3, 4, 5)]
    return x, rows


def block_at(x, rows, s):
    """The block at the spread ``s`` (bp), its formulas written out: {(kind, row): value}."""
    K, M, Q60, U60, W60, Z60, w = x["K60"], x["M60"], x["Q60"], x["U60"], x["W60"], x["Z60"], x["w"]
    out = {}

    def avg(vals):
        return sum(a * b for a, b in zip(w, vals)) / sum(w)

    for r in ROWS:
        if r == AVG:
            continue
        D, L, H, I = (rows[r][c] for c in "DLHI")
        out[("F", r)], out[("N", r)] = D + s / 1e4, L + s / 1e4
        out[("Q", r)] = ((1 / H - 1) * 360 / K) * 100 + s / 100 if K > 0 else ""
        out[("R", r)] = ((1 / I - 1) * 360 / M) * 100 + s / 100
        out[("X", r)] = out[("F", r)] * 100
    for k in "FNRX":
        out[(k, AVG)] = avg([out[(k, r)] for r in (63, 64, 65)])
    out[("Q", AVG)] = avg([out[("Q", r)] for r in (63, 64, 65)]) if K > 0 else ""
    for r in ROWS:
        q, rr = out[("Q", r)], out[("R", r)]
        S = Q60 if K <= 0 else Q60 * (1 + q / 100 * K / 360) / (1 + U60 / 100 * K / 360)
        T = Q60 * (1 + rr / 100 * M / 360) / (1 + W60 / 100 * M / 360)
        out[("S", r)], out[("T", r)] = S, T
        out[("U", r)], out[("V", r)], out[("W", r)] = (S - Q60) * 1e4, (T - Q60) * 1e4, (T - S) * 1e4
        out[("Y", r)] = (T - Q60 * (1 + Z60 / 100 * M / 360) / (1 + W60 / 100 * M / 360)) * 1e4
    return out


def block(svc, user):
    return {(k, r): cell(svc, "MASA!%s%d" % (k, r), user) for k in KINDS for r in ROWS}


def same_block(got, want, tol=1e-9):
    bad = {key: (got[key], want[key]) for key in want if not (got[key] == want[key] == "" or close(got[key], want[key], tol))}
    return bad


DATES = {"MASA!C60": "15.12.2026", "MASA!E60": "15.06.2027"}              # a forward start: both legs depend on the spread


def test_the_block_with_nothing_typed_is_the_workbooks(svc):
    """Nothing typed: every value of the block is the workbook's formula at the desk's spread (the file's −150 bp) - at the
    OIS spot start and at a forward start; the period's TRY % (X) is the same number as before, F · 100, to the bit."""
    u = svc.login("TA iki yönlü boş")["user"]
    try:
        assert cell(svc, "MASA!I60", u) == -150.0 and stored(svc, u, "MASA") == {}
        for dates in ({}, DATES):
            put(svc, u, dates) if dates else None
            x, rows = block_parts(svc, u)
            got = block(svc, u)
            assert same_block(got, block_at(x, rows, -150.0), 1e-12) == {}
            assert all(got[("X", r)] == got[("F", r)] * 100 for r in ROWS if r != AVG)
        assert x["K60"] > 0 and isinstance(got[("Q", 62)], float)
    finally:
        svc.reset_inputs(u, "tto")


def test_any_value_typed_gives_the_spread_and_the_whole_block(svc):
    """Each of the 77 values, on every curve row, typed as the value it has at a spread of −87,5 bp: the block's spread is
    −87,5 (1e-9) and every value of the block is the formulas' at that spread; the value typed stands exactly, kept in its
    own store alone (the last typed wins)."""
    u = svc.login("TA iki yönlü her değer")["user"]
    try:
        put(svc, u, DATES)
        x, rows = block_parts(svc, u)
        want = block_at(x, rows, -87.5)
        for k in KINDS:
            for r in ROWS:
                put(svc, u, {"MASA!%s%d" % (k, r): want[(k, r)]})
                assert close(cell(svc, "MASA!I60", u), -87.5), (k, r, cell(svc, "MASA!I60", u))
                assert cell(svc, "MASA!%s%d" % (k, r), u) == want[(k, r)]
                assert stored(svc, u, "MASA") == dict({"%s%d" % (STORES[k], r): want[(k, r)]}, C60=x_date(DATES, "C60"),
                                                      E60=x_date(DATES, "E60")), (k, r)
                assert same_block(block(svc, u), want) == {}, (k, r)
    finally:
        svc.reset_inputs(u, "tto")


def x_date(dates, a):
    d = dt.datetime.strptime(dates["MASA!" + a], "%d.%m.%Y").date()
    return float(date_to_serial(d))


def test_a_value_worked_out_typed_back_gives_the_same_block(svc):
    """The forward-forward points typed (1 500 under the market's): the spread they give; then every value of the block, as
    shown, typed back as its own kind gives the same block (1e-9) - round trips through every inverse."""
    u = svc.login("TA iki yönlü geri")["user"]
    try:
        put(svc, u, DATES)
        w67 = cell(svc, "MASA!W67", u)
        put(svc, u, {"MASA!W67": w67 - 1500})
        x, rows = block_parts(svc, u)
        s = cell(svc, "MASA!I60", u)
        slope = (x["Q60"] / (1 + x["W60"] / 100 * x["M60"] / 360) * x["M60"]
                 - x["Q60"] / (1 + x["U60"] / 100 * x["K60"] / 360) * x["K60"]) / 360       # dW / d spread
        assert close(s, -150 - 1500 / slope, 1e-9) and s < -150
        first = block(svc, u)
        assert same_block(first, block_at(x, rows, s)) == {}
        for k in KINDS:
            for r in (62, AVG, 68):
                put(svc, u, {"MASA!%s%d" % (k, r): first[(k, r)]})
                assert close(cell(svc, "MASA!I60", u), s), (k, r)
                assert same_block(block(svc, u), first) == {}, (k, r)
        put(svc, u, {"MASA!I60": s})                                               # the spread itself, typed
        assert stored(svc, u, "MASA")["I60"] == s and same_block(block(svc, u), first) == {}
    finally:
        svc.reset_inputs(u, "tto")


def test_the_last_typed_wins_and_delete_goes_back_to_the_workbooks_spread(svc):
    """The spread typed, then a rate of the block: the spread typed goes (the rate stands, the spread is the one it gives);
    another value: the first goes.  Delete on the value typed - or on any cell of the block - takes the block back to the
    workbook's spread (−150: what was typed in I60 before went with the first value typed in the block)."""
    u = svc.login("TA iki yönlü son")["user"]
    try:
        put(svc, u, {"MASA!I60": "-120"})
        assert stored(svc, u, "MASA") == {"I60": -120.0}
        put(svc, u, {"MASA!F67": "38,5"})
        assert stored(svc, u, "MASA") == {"CT67": 0.385}
        assert close(cell(svc, "MASA!I60", u), (0.385 - cell(svc, "MASA!D67", u)) * 1e4)
        put(svc, u, {"MASA!R62": "39"})
        assert stored(svc, u, "MASA") == {"CW62": 39.0} and cell(svc, "MASA!F67", u) != 0.385
        for typed, deleted in (("V64", "V64"), ("X66", "F62"), ("N68", "I60"), ("Y63", "T65")):
            put(svc, u, {"MASA!" + typed: cell(svc, "MASA!" + typed, u)})
            res = put(svc, u, {"MASA!" + deleted: ""})
            assert stored(svc, u, "MASA") == {} and cell(svc, "MASA!I60", u) == -150.0 and res["applied"] == 1, (typed, deleted)
        put(svc, u, {"MASA!W62": "60000"})
        assert svc.reset_inputs(u, "tto", ["MASA!S68"])["reset"] == 1                # "Kendi girdimi sil" on another cell
        assert stored(svc, u, "MASA") == {} and cell(svc, "MASA!I60", u) == -150.0
    finally:
        svc.reset_inputs(u, "tto")


def test_a_column_pasted_into_the_block(svc):
    """The block is one row-side: a column of rates pasted (three curves' period rates + spread) - the last one stands and
    gives the spread; the others are worked out from it."""
    u = svc.login("TA iki yönlü yapıştır")["user"]
    try:
        res = svc.paste(u, "tto", "MASA!F62", "36,5\n37\n37,5")
        assert res["errors"] == [] and stored(svc, u, "MASA") == {"CT64": 0.375}
        assert close(cell(svc, "MASA!I60", u), (0.375 - cell(svc, "MASA!D64", u)) * 1e4)
        assert close(cell(svc, "MASA!F62", u), cell(svc, "MASA!D62", u) + cell(svc, "MASA!I60", u) / 1e4)
    finally:
        svc.reset_inputs(u, "tto")


def test_the_spreads_readers_follow_a_value_typed_in_the_block(svc):
    """The spread stays a plain bp value: what reads it - FORWARD KOTASYON's general spread (EK_FWD!D4:E4), TOPLU TARİH
    ARASI FAİZ's general spread and a row without its own, the Forward sheet's spread (P58, O27), OIS_MAIN's date-to-date
    spread (F122) - follows the spread a rate typed in the block gives (and moves with the curve, as it does)."""
    u = svc.login("TA iki yönlü izleyen")["user"]
    try:
        put(svc, u, {"MASA!F67": "36", "EK_TARIH!C5": "15.03.2027"})
        s = cell(svc, "MASA!I60", u)
        assert isinstance(s, float) and s != -150.0
        assert cell(svc, "EK_FWD!D4", u) == cell(svc, "EK_FWD!E4", u) == s
        assert cell(svc, "EK_TARIH!G2", u) == cell(svc, "EK_TARIH!D5", u) == s
        assert cell(svc, "Forward!P58", u) == s / 100 and cell(svc, "Forward!O27", u) == s / 10000
        assert cell(svc, "OIS_MAIN!F122", u) == s / 10000
        # the curve moves (a scenario step for MPC ima's path is not the curve; Bootstrap: TLREF typed moves its stub):
        # the typed rate stands, the spread and its readers follow
        put(svc, u, {"MASA!F68": "36"})                                           # TLREF sabit's row: TLREF typed moves it
        before = cell(svc, "MASA!I60", u)
        put(svc, u, {"OIS_MAIN!J2": cell(svc, "OIS_MAIN!J2", u) + 0.01})
        after = cell(svc, "MASA!I60", u)
        assert cell(svc, "MASA!F68", u) == 0.36 and after < before - 50
        assert cell(svc, "EK_FWD!D4", u) == cell(svc, "EK_TARIH!G2", u) == after
    finally:
        svc.reset_inputs(u, "tto")


def test_a_start_leg_typed_at_the_spot_gives_no_spread(svc):
    """At the OIS spot start (K60 = 0, the block's own default) the start leg does not depend on the spread (its forward is
    the spot): a start leg's TRY %, forward or points typed there gives no spread - the block and the spread show nothing,
    the value typed stands; a forward start typed then gives it its spread; Delete: the workbook's spread again."""
    u = svc.login("TA iki yönlü spot")["user"]
    try:
        assert cell(svc, "MASA!K60", u) == 0.0 and cell(svc, "MASA!Q62", u) == ""
        assert cell(svc, "MASA!S67", u) == cell(svc, "MASA!Q60", u) and cell(svc, "MASA!U67", u) == 0.0
        put(svc, u, {"MASA!S67": cell(svc, "MASA!Q60", u) + 0.02})
        assert cell(svc, "MASA!I60", u) == "" and cell(svc, "MASA!F62", u) == "" and cell(svc, "MASA!W67", u) == ""
        assert cell(svc, "MASA!S67", u) == cell(svc, "MASA!Q60", u) + 0.02
        assert cell(svc, "EK_FWD!D4", u) == "" and cell(svc, "EK_TARIH!G2", u) == ""
        put(svc, u, {"MASA!C60": DATES["MASA!C60"]})
        x, rows = block_parts(svc, u)
        s = cell(svc, "MASA!I60", u)
        assert isinstance(s, float) and same_block(block(svc, u), block_at(x, rows, s)) == {}
        put(svc, u, {"MASA!U67": ""})
        assert cell(svc, "MASA!I60", u) == -150.0
    finally:
        svc.reset_inputs(u, "tto")


def test_values_typed_before_keep_their_meaning(svc):
    """A spread typed before stays the block's spread (kept where it always was); a value typed over a block's cell before it
    was two-way ("Elle değer") becomes the block's typed value - its store, the spread typed dropped (once, logged)."""
    u = svc.login("TA iki yönlü eski")["user"]
    try:
        svc.store.set_user_inputs(u, "tto", {"MASA!I60": -95.0})
        svc._reload_user(u)
        assert cell(svc, "MASA!I60", u) == -95.0 and stored(svc, u, "MASA") == {"I60": -95.0}
        svc.store.set_user_inputs(u, "tto", {"MASA!W67": 50000.0})
        svc._reload_user(u)
        assert stored(svc, u, "MASA") == {"DB67": 50000.0} and cell(svc, "MASA!W67", u) == 50000.0
        assert cell(svc, "MASA!I60", u) != -95.0
        book = svc.books["tto"]
        assert book.cell("MASA!W67") not in book.inputs
    finally:
        svc.reset_inputs(u, "tto")


def test_a_scenario_keeps_the_value_typed(svc):
    u = svc.login("TA iki yönlü senaryo")["user"]
    try:
        put(svc, u, dict(DATES, **{"MASA!T66": "61"}))
        want = (cell(svc, "MASA!I60", u), block(svc, u))
        svc.save_scenario(u, "tarih iki yönlü")
        put(svc, u, {"MASA!I60": "-10"})
        svc.load_scenario(u, "tarih iki yönlü")
        assert stored(svc, u, "MASA")["CY66"] == 61.0 and "I60" not in stored(svc, u, "MASA")
        assert cell(svc, "MASA!I60", u) == want[0] and block(svc, u) == want[1]
    finally:
        svc.reset_inputs(u, "tto")


def test_the_page_marks_the_value_typed(svc):
    """On the page: the block's cells are inputs; the one typed is marked (``an``: the others come from it), the others say
    where they come from (``ao``: its name and cell); the group's note under both tables."""
    u = svc.login("TA iki yönlü sayfa")["user"]
    try:
        put(svc, u, {"MASA!W67": "70000"})
        p9, m9 = marks(svc, u, "masa", "B9")
        p10, m10 = marks(svc, u, "masa", "B10")
        assert m10["W67"]["an"].startswith("Spread (bp), MPC ima · Dönem + spread") and m10["W67"]["m"] == 1
        assert m9["F62"]["ao"] == "Bootstrap · Fwd-fwd puan · W67" and m9["F62"]["i"] == "u" and "an" not in m9["F62"]
        assert m9["I60"]["ao"] == "Bootstrap · Fwd-fwd puan · W67"
        assert m10["T62"]["ao"] == "Bootstrap · Fwd-fwd puan · W67"
        for p in (p9, p10):
            assert "hangisini yazarsanız o kalır" in p["note"], p["id"]
        info = svc.cell_info(u, "tto", "MASA!N66")
        assert info["input"]["twoway"] == {"group": "TARİH ARASI FAİZ / FORWARD", "member": "Ağırlıklı · Spot→bitiş + spread",
                                           "anchor": {"member": "Bootstrap · Fwd-fwd puan", "ref": "MASA!W67"}}
        put(svc, u, {"MASA!W67": ""})
        _, m10 = marks(svc, u, "masa", "B10")
        assert not any(k in m10["W67"] for k in ("an", "ao", "m"))
    finally:
        svc.reset_inputs(u, "tto")


def test_a_copy_of_the_forward_table(svc):
    """A temporary copy of TARİH ARASI FORWARD: a value typed there gives the copy's spread and block - the table stays its
    own; Delete in the copy follows the table again.  With a spread typed in the table itself, another value cannot be
    typed in a copy (the copy cannot take the table's typed spread back to its formula): refused with the reason."""
    u = svc.login("TA iki yönlü kopya")["user"]
    try:
        put(svc, u, DATES)
        cid = svc.copy_action(u, "open", {"view": "masa", "panel": "B10"})["copy"]["id"]

        def copy_put(cells):
            return svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": k, "value": v} for k, v in cells.items()]})

        def copy_value(ref):
            return svc.et.call(lambda: svc.copies.calc(u, svc.copies.find(u, cid)).value(ref))

        table = block(svc, u)
        w = table[("W", 67)] + 2000
        res = copy_put({"MASA!W67": w})
        assert res["errors"] == [] and copy_value("MASA!W67") == w
        s = copy_value("MASA!I60")
        assert isinstance(s, float) and s > -150 and cell(svc, "MASA!I60", u) == -150.0 and block(svc, u) == table
        assert close(copy_value("MASA!F62"), cell(svc, "MASA!D62", u) + s / 1e4)
        res = copy_put({"MASA!W67": ""})
        assert res["applied"] == 1 and copy_value("MASA!I60") == -150.0
        put(svc, u, {"MASA!I60": "-130"})
        res = copy_put({"MASA!T62": "60"})
        assert res["errors"] == ["MASA!T62: " + COPY_TABLE_TYPED % ("Spread (bp)", "MASA!I60")]
        res = copy_put({"MASA!I60": "-110"})                                      # the spread itself: fine
        assert res["errors"] == [] and copy_value("MASA!I60") == -110.0 and cell(svc, "MASA!I60", u) == -130.0
        svc.copy_action(u, "close", {"copy": cid})
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== TOPLU TARİH ARASI FAİZ
def test_a_bulk_rows_spread_or_its_plus_spread(svc):
    """A row's "+ spread (360)" typed: the row's spread is the one it gives over the chosen curve's ACT/360 rate (whatever
    basis the table shows; Ağırlıklı's the S1-S3 average); the spread typed back gives the same "+ spread"; a column of them
    pasted - each row its own; Delete - the general spread again; the row's quote (Kote %) is a reading apart."""
    u = svc.login("Toplu iki yönlü")["user"]
    try:
        put(svc, u, {"EK_TARIH!C5": "15.03.2027", "EK_TARIH!B6": "15.12.2026", "EK_TARIH!C6": "15.06.2027",
                     "EK_TARIH!C7": "15.12.2027", "OIS_MAIN!U10": "-50", "OIS_MAIN!V10": "100"})
        e = lambda a: cell(svc, "EK_TARIH!" + a, u)                               # noqa: E731
        put(svc, u, {"EK_TARIH!M5": "36,25"})
        assert e("M5") == 0.3625 and close(e("D5"), (0.3625 - e("AF5")) * 1e4) and stored(svc, u, "EK_TARIH")["AT5"] == 0.3625
        d5 = e("D5")
        put(svc, u, {"EK_TARIH!D5": d5})
        assert stored(svc, u, "EK_TARIH").get("AT5") is None and close(e("M5"), 0.3625, 1e-12)
        # another curve, another basis shown: the ACT/360 rate of the chosen curve is the base
        put(svc, u, {"EK_TARIH!C2": "Ağırlıklı", "EK_TARIH!E2": "ACT/365", "EK_TARIH!M6": "0,37"})
        q = [cell(svc, "OIS_MAIN!Q%d" % k, u) for k in (3, 4, 5)]
        avg360 = sum(a * b for a, b in zip(q, (e("AG6"), e("AH6"), e("AI6")))) / sum(q)
        assert close(e("D6"), (0.37 - avg360) * 1e4) and e("M6") == 0.37 and e("J6") != avg360
        # a column pasted: each row its own
        res = svc.paste(u, "tto", "EK_TARIH!M5", "0,35\n0,355\n0,36")
        assert res["errors"] == [] and {k: v for k, v in stored(svc, u, "EK_TARIH").items() if k.startswith("AT")} == {
            "AT5": 0.35, "AT6": 0.355, "AT7": 0.36}
        for r, v in ((5, 0.35), (6, 0.355), (7, 0.36)):
            assert e("M%d" % r) == v and close(e("D%d" % r), (v - e("AJ%d" % r)) * 1e4), r
        # Kote %: a reading, not the row's spread
        put(svc, u, {"EK_TARIH!C2": "", "EK_TARIH!E2": "", "EK_TARIH!N5": "0,365"})
        assert e("M5") == 0.35 and close(e("O5"), (0.365 - e("F5")) * 1e4)
        put(svc, u, {"EK_TARIH!N5": e("M5")})
        assert close(e("O5"), e("D5"))                                          # (ACT/360: Kote − curve = the row's spread)
        put(svc, u, {"EK_TARIH!M6": ""})
        assert e("D6") == e("G2") == -150.0 and stored(svc, u, "EK_TARIH").get("AT6") is None
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== OIS · PPK: MPC OIS / MPC SPREAD -> PPK step
def on365(r, d):
    return 365.0 * ((1.0 + r * d / 365.0) ** (1.0 / d) - 1.0)


def rate365(on, d):
    return ((1.0 + on / 365.0) ** d - 1.0) * 365.0 / d


WINDOWS = ex.PPK_WINDOWS[1] - ex.PPK_WINDOWS[0] + 1
PAIRS = ex.PPK_PAIRS[1] - ex.PPK_PAIRS[0] + 1


def test_a_windows_rate_its_overnight_or_its_step(svc):
    """MPC OIS → PPK ADIMI, every window: a step typed -> the O/N = the period before's O/N + the step -> the rate; an O/N
    typed -> the rate and the step; the rate typed back gives the same row (1e-9 bp); the step of the rate found is Broker
    Chat's for that rate (the chat's line at it)."""
    u = svc.login("PPK iki yönlü pencere")["user"]
    p = lambda c, r: cell(svc, "EK_PPK!%s%d" % (c, r), u)                        # noqa: E731
    try:
        last = {}
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            j, e = p("J", r), p("E", r)
            put(svc, u, {"EK_PPK!L%d" % r: "-37,5"})
            assert p("L", r) == -37.5 and close(p("K", r), j - 0.00375, 1e-13) and close(p("G", r), rate365(j - 0.00375, e), 1e-13), k
            row = [p(c, r) for c in "GKL"]
            put(svc, u, {"EK_PPK!K%d" % r: p("K", r) + 0.001})
            assert close(p("G", r), rate365(row[1] + 0.001, e), 1e-13) and close(p("L", r), -27.5, 1e-9), k
            for c, v in zip("GKL", row):                                         # each typed back: the same row
                put(svc, u, {"EK_PPK!%s%d" % (c, r): v})
                assert all(close(p(x, r), y, 1e-9) for x, y in zip("GKL", row)), (k, c)
            last["Z%d" % r] = row[2]                                             # (the step, typed last: its store alone)
            assert stored(svc, u, "EK_PPK") == last, k
        # the chat's step for a line at the rate found
        put(svc, u, {"EK_PPK!L4": "-50"})
        rate = p("G", 4)
        lines = svc.broker_parse(u, "10:00:00 jan27 mpc %.6f/%.6f" % (rate * 100, rate * 100 + 0.2), "2026-01-15")["rows"]
        imp = next(q for q in lines if (q.get("mpc") or {}).get("start"))["implied"]
        assert abs(imp["bid"] + 50) < 1e-3                                       # (the line's rate has six decimals)
    finally:
        svc.reset_inputs(u, "tto")


def test_a_pairs_spread_its_later_rate_its_overnight_or_its_step(svc):
    """MPC SPREAD → PPK ADIMI, every pair: the later window's rate, its O/N or its step typed -> the spread (later rate −
    the earlier window's market rate) and the rest; each typed back gives the same row; the last typed wins."""
    u = svc.login("PPK iki yönlü çift")["user"]
    p = lambda c, r: cell(svc, "EK_PPK!%s%d" % (c, r), u)                        # noqa: E731
    try:
        for k in range(PAIRS):
            r, n = ex.PPK_FIRST + k, ex.PPK_FIRST + k + 1
            f, jn, en = p("F", r), p("J", n), p("E", n)
            put(svc, u, {"EK_PPK!V%d" % r: "25"})
            assert p("V", r) == 25.0 and close(p("U", r), jn + 0.0025, 1e-13), k
            assert close(p("T", r), rate365(jn + 0.0025, en), 1e-13) and close(p("S", r), (p("T", r) - f) * 1e4, 1e-9), k
            row = [p(c, r) for c in "STUV"]
            for c, v in zip("STUV", row):
                put(svc, u, {"EK_PPK!%s%d" % (c, r): v})
                assert all(close(p(x, r), y, 1e-9) for x, y in zip("STUV", row)), (k, c)
            put(svc, u, {"EK_PPK!T%d" % r: "36"})
            assert p("T", r) == 0.36 and close(p("S", r), (0.36 - f) * 1e4, 1e-9) and close(p("U", r), on365(0.36, en), 1e-13)
        mine = stored(svc, u, "EK_PPK")
        assert mine == {"AA%d" % (ex.PPK_FIRST + k): 0.36 for k in range(PAIRS)}
        put(svc, u, {"EK_PPK!S3": "-40"})                                         # the spread typed: the later rate's store goes
        assert stored(svc, u, "EK_PPK").get("AA3") is None and stored(svc, u, "EK_PPK")["S3"] == -40.0
        put(svc, u, {"EK_PPK!U3": ""})                                            # Delete: nothing typed in the row
        assert p("S", 3) == "" and p("T", 3) == "" and p("V", 3) == "" and "S3" not in stored(svc, u, "EK_PPK")
    finally:
        svc.reset_inputs(u, "tto")


def test_what_is_typed_in_the_ppk_tables_moves_with_its_meeting(tmp_path):
    """A PPK calendar change and the roll: an O/N, a step or a later rate typed (their stores) stays with the meeting that
    starts its row's window, as the rate and the spread do; one whose meeting leaves is set aside; an "Elle değer" typed over
    a step before this became two-way is that row's typed value, and moves the same way."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        book = svc.books["tto"]
        a = svc.login("PPK iki yönlü takvim")["user"]
        mine = lambda: stored(svc, a, "EK_PPK")                                   # noqa: E731
        put(svc, a, {"EK_PPK!K3": "37", "EK_PPK!L4": "-25", "EK_PPK!V5": "50", "EK_PPK!T6": "33"})
        assert mine() == {"Y3": 0.37, "Z4": -25.0, "AC5": 50.0, "AA6": 0.33}
        svc.store.set_user_inputs(a, "tto", {"EK_PPK!L7": 12.5})                 # (an "Elle değer" of an earlier version)
        svc._reload_user(a)
        assert mine() == {"Y3": 0.37, "Z4": -25.0, "AC5": 50.0, "AA6": 0.33, "Z7": 12.5}
        start = h.meetings()
        res = h.set_calendar(a, ["11.02.2027"] + start[:-1])                     # a meeting before 18.03.2027: the later ones a row down
        assert res["parked"]["meetings"] == []
        assert mine() == {"Y3": 0.37, "Z4": -25.0, "AC6": 50.0, "AA7": 0.33, "Z8": 12.5}
        assert cell(svc, "EK_PPK!L4", a) == -25.0 and cell(svc, "EK_PPK!V6", a) == 50.0 and cell(svc, "EK_PPK!L8", a) == 12.5
        assert cell(svc, "EK_PPK!V5", a) == "" and cell(svc, "EK_PPK!T7", a) == 0.33
        assert cell(svc, "EK_PPK!B8", a) == cell(svc, "OIS_MAIN!P15", a)

        def move_spot():
            book.declare("OIS_MAIN!B2", scope="shared", group="test-spot")
            book.engine.set_inputs({book.cell("OIS_MAIN!B2"): float(date_to_serial(dt.date(2026, 12, 14)))})
        svc.et.call(move_spot)
        svc.bump()
        res = h.roll_calendar(a)                                                  # 10.12.2026 has passed
        assert res["rolled"] == ["2026-12-10"] and res["parked"]["meetings"] == ["2026-12-10"]
        assert mine() == {"Z3": -25.0, "AC5": 50.0, "AA6": 0.33, "Z7": 12.5}
        assert mt.parked(svc.store)["tcmb"]["2026-12-10"]["user"] == {a: {"EK_PPK!Y": 0.37}}
        assert cell(svc, "EK_PPK!L3", a) == -25.0 and isinstance(cell(svc, "EK_PPK!G3", a), float)
    finally:
        svc.stop()


# ============================================================================== OIS · PPK: TÜM FORWARD / FRA
FRA_SAMPLE = (336, 337, 338, 344, 350, 371, 402, 438)                       # a spot start, 3x6, … the last row


def fra_parts(svc, user, r):
    """A row's start leg's market par (I), end leg's (J), months (M) and annuities (O, P), and its start fill (Q)."""
    return {c: cell(svc, "OIS_MAIN!%s%d" % (c, r), user) for c in "IJMOPQ"}


def fra_of(p, end):
    """S's formula: the FRA two legs make, a blank start fill its market par (I); a spot start: the end leg."""
    q = p["I"] if p["Q"] is None else p["Q"]
    return end if p["M"] == 0 else (end * p["P"] - q * p["O"]) / (p["P"] - p["O"])


def end_of(p, fra):
    """Its inverse: the end leg that makes the FRA with the start leg held (its fill, else its market par)."""
    q = p["I"] if p["Q"] is None else p["Q"]
    return fra if p["M"] == 0 else (fra * (p["P"] - p["O"]) + q * p["O"]) / p["P"]


def test_an_fra_typed_gives_the_end_leg_the_start_leg_held(svc):
    """TÜM FORWARD / FRA (the desk's "Ok", 24.11.2026: "when you type the FRA, the start leg stays - your fill, or the market
    par if blank - and the end leg is computed"): nothing typed - the table's FRA of the market's pars, the end leg's fill
    blank; an FRA typed stands and the end leg's fill is the one that makes it (a spot start: the FRA itself); the start leg
    held is the market par when its fill is blank, the fill when typed - typed while the FRA stands, it moves the end leg;
    each value worked out, typed back as its own kind, gives the same row (1e-9)."""
    u = svc.login("FRA iki yönlü")["user"]
    o = lambda c, r: cell(svc, "OIS_MAIN!%s%d" % (c, r), u)                     # noqa: E731
    try:
        for r in FRA_SAMPLE:
            p = fra_parts(svc, u, r)
            assert p["Q"] is None and o("R", r) == "" and close(o("S", r), fra_of(p, p["J"]), 1e-12), r       # (as before)
            put(svc, u, {"OIS_MAIN!S%d" % r: "35"})
            assert o("S", r) == 0.35 and close(o("R", r), end_of(p, 0.35), 1e-12), r                        # (the market par held)
            assert stored(svc, u, "OIS_MAIN") == {"%s%d" % (ex.FRA_TW, r): 0.35}, r
            end = o("R", r)
            put(svc, u, {"OIS_MAIN!R%d" % r: end})                                 # the end leg typed back: the same FRA
            assert close(o("S", r), 0.35, 1e-9) and stored(svc, u, "OIS_MAIN") == {"R%d" % r: end}, r
            back = o("S", r)
            put(svc, u, {"OIS_MAIN!S%d" % r: back})                                # ... and the FRA typed back
            assert o("S", r) == back and close(o("R", r), end, 1e-9), r
            if p["M"] != 0:
                put(svc, u, {"OIS_MAIN!Q%d" % r: "36,8"})                          # the start leg's fill: the end leg moves
                p["Q"] = 36.8 / 100
                assert o("S", r) == back and close(o("R", r), end_of(p, back), 1e-12), r
                assert abs(o("R", r) - end) > 1e-6, r
            svc.reset_inputs(u, "tto")
        p = fra_parts(svc, u, 336)
        assert p["M"] == 0 and p["I"] == ""                                       # (a spot start: no start leg)
        put(svc, u, {"OIS_MAIN!S336": "37"})
        assert o("R", 336) == 0.37 and o("S", 336) == 0.37
    finally:
        svc.reset_inputs(u, "tto")


def test_the_fra_rows_last_typed_wins_delete_and_a_paste(svc):
    """The end leg's fill typed, then the FRA: the fill typed goes (the FRA stands, the fill is the one it needs); the fill
    again: the FRA typed goes.  Delete on either - back to the market's (nothing typed).  A column of FRAs pasted: each row
    its own.  The Hedef FRA columns stay as they were (against the legs as the FRA reads them)."""
    u = svc.login("FRA iki yönlü son")["user"]
    o = lambda c, r: cell(svc, "OIS_MAIN!%s%d" % (c, r), u)                     # noqa: E731
    tw = ex.FRA_TW
    try:
        p = fra_parts(svc, u, 337)
        market = o("S", 337)
        pct = lambda x: x / 100                                                   # noqa: E731 - "36,2" in a % cell
        put(svc, u, {"OIS_MAIN!R337": "36,2"})
        assert stored(svc, u, "OIS_MAIN") == {"R337": pct(36.2)} and close(o("S", 337), fra_of(p, pct(36.2)), 1e-12)
        put(svc, u, {"OIS_MAIN!S337": "34,5"})
        assert stored(svc, u, "OIS_MAIN") == {tw + "337": pct(34.5)} and close(o("R", 337), end_of(p, pct(34.5)), 1e-12)
        put(svc, u, {"OIS_MAIN!R337": "36,2"})
        assert stored(svc, u, "OIS_MAIN") == {"R337": pct(36.2)}
        for typed, deleted in (("S337", "S337"), ("S337", "R337"), ("R337", "S337")):
            put(svc, u, {"OIS_MAIN!" + typed: "35,5"})
            res = put(svc, u, {"OIS_MAIN!" + deleted: ""})
            assert stored(svc, u, "OIS_MAIN") == {} and o("R", 337) == "" and o("S", 337) == market and res["applied"] == 1, (typed, deleted)
        res = svc.paste(u, "tto", "OIS_MAIN!S337", "34\n34,5\n35")
        assert res["errors"] == [] and stored(svc, u, "OIS_MAIN") == {tw + "337": pct(34), tw + "338": pct(34.5), tw + "339": pct(35)}
        for r, v in ((337, pct(34)), (338, pct(34.5)), (339, pct(35))):
            assert o("S", r) == v and close(o("R", r), end_of(fra_parts(svc, u, r), v), 1e-12), r
        # Hedef FRA: as before - the legs as the FRA reads them (the end leg the one the FRA typed needs)
        put(svc, u, {"OIS_MAIN!U337": "33"})
        assert close(o("V", 337), end_of(p, pct(33)), 1e-12)
        assert close(o("W", 337), (o("R", 337) * p["P"] - pct(33) * (p["P"] - p["O"])) / p["O"], 1e-12)
        assert svc.reset_inputs(u, "tto", ["OIS_MAIN!R338"])["reset"] == 1 and o("S", 338) != pct(34.5)
    finally:
        svc.reset_inputs(u, "tto")


def test_fills_typed_before_keep_their_meaning_and_the_page_marks_the_fra(svc):
    """An end leg's fill typed before stays where it was (the FRA reads it, as before); an FRA typed over before it was two-way
    ("Elle değer") is that row's typed FRA.  On the page the FRA typed is marked, the end leg says it comes from it; the
    table's note says what is held."""
    u = svc.login("FRA iki yönlü eski")["user"]
    o = lambda c, r: cell(svc, "OIS_MAIN!%s%d" % (c, r), u)                     # noqa: E731
    try:
        svc.store.set_user_inputs(u, "tto", {"OIS_MAIN!R340": 0.361, "OIS_MAIN!S341": 0.333})
        svc._reload_user(u)
        assert stored(svc, u, "OIS_MAIN") == {"R340": 0.361, ex.FRA_TW + "341": 0.333}
        assert close(o("S", 340), fra_of(fra_parts(svc, u, 340), 0.361), 1e-12) and o("S", 341) == 0.333
        assert close(o("R", 341), end_of(fra_parts(svc, u, 341), 0.333), 1e-12)
        book = svc.books["tto"]
        assert book.cell("OIS_MAIN!S341") not in book.inputs
        p, m = marks(svc, u, "ois", "B21")
        assert m["S341"]["an"] == "Bitiş bacağı dolum" and m["R341"]["ao"] == "Gerçekleşen FRA · S341" and m["S341"]["m"] == 1
        # (an end leg's fill typed is its row's typed value too: the FRA worked out from it)
        assert m["R340"]["m"] == 1 and m["R340"]["an"] == "Gerçekleşen FRA" and m["S340"]["ao"] == "Bitiş bacağı dolum · R340"
        assert "boşsa piyasa par" in p["note"] and "hangisini yazarsanız o kalır" in p["note"]
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== OIS · Nakit Akışı: rate <-> PV
SCHEDULE = (("24.02.2027", "24.05.2027"), ("24.05.2027", "24.08.2027"), ("24.08.2027", "24.11.2027"))


def tmois_schedule(svc, user):
    spot = cell(svc, "OIS_MAIN!B2", user)
    first = dt.date(1899, 12, 30) + dt.timedelta(days=int(spot))
    cells = {"TM_OIS!A10": first.strftime("%d.%m.%Y"), "TM_OIS!B10": SCHEDULE[0][0], "TM_OIS!C10": "100m"}
    for k, (a, b) in enumerate(SCHEDULE):
        cells.update({"TM_OIS!A%d" % (11 + k): a, "TM_OIS!B%d" % (11 + k): b, "TM_OIS!C%d" % (11 + k): "50m"})
    # the scenarios differ (their first step): S1 −50, S2 +100, S3 −250 bp
    cells.update({"OIS_MAIN!U10": "-50", "OIS_MAIN!V10": "100", "OIS_MAIN!W10": "-250"})
    put(svc, user, cells)


def tmois_legs(svc, user):
    """Per curve (piyasa, S1, S2, S3): (Σ float, Σ over the periods with a rate of their own of D·N·τ·DF, Σ N·τ·DF over
    the others) - read from the sheet's own legs (none of them reads the trade rate)."""
    t = lambda a: cell(svc, "TM_OIS!" + a, user)                                 # noqa: E731
    out = []
    for fl, ann in (("H", "I"), ("P", "Q"), ("U", "V"), ("Z", "AA")):
        own = sum(t("D%d" % r) * t("%s%d" % (ann, r)) for r in range(10, 35) if t("D%d" % r) is not None)
        rest = sum(t("%s%d" % (ann, r)) for r in range(10, 35) if t("D%d" % r) is None)
        out.append((sum(t("%s%d" % (fl, r)) for r in range(10, 35)), own, rest))
    return out


def test_the_trade_rate_or_any_pv(svc):
    """OIS · Nakit Akışı: the trade rate typed -> the four PVs (market, S1-S3) and the expected one, as the sheet's formula
    gives them; any PV typed -> the rate that gives it on its own curve (the expected through the probabilities), the PV
    typed standing exactly, the others rounded to 1 TL as the sheet shows them; the rate found typed back gives the PV
    typed (to the TL); a period with a rate of its own is held; Delete: the par again."""
    u = svc.login("Nakit iki yönlü")["user"]
    t = lambda a: cell(svc, "TM_OIS!" + a, u)                                    # noqa: E731
    try:
        tmois_schedule(svc, u)
        put(svc, u, {"TM_OIS!D12": "40"})                                         # a period with a rate of its own
        legs = tmois_legs(svc, u)
        q = [cell(svc, "OIS_MAIN!Q%d" % k, u) for k in (3, 4, 5)]
        side = t("B3")

        def pv(k, rate):
            fl, own, rest = legs[k]
            return side * (rate * rest + own - fl)

        put(svc, u, {"TM_OIS!D3": "37"})
        pvs = [round(pv(k, 0.37)) for k in range(4)]
        assert [t(c) for c in ("B5", "D5", "F5", "H5")] == pvs and t("B6") == 0.37
        assert t("J5") == round(sum(a * b for a, b in zip(q, pvs[1:])) / sum(q))
        assert len(set(pvs)) == 4
        for cell_, k in (("B5", 0), ("D5", 1), ("F5", 2), ("H5", 3)):
            put(svc, u, {"TM_OIS!" + cell_: "1,25m"})
            fl, own, rest = legs[k]
            want = (1.25e6 / side + fl - own) / rest
            assert t(cell_) == 1.25e6 and close(t("D3"), want, 1e-12) and t("B6") == t("D3"), cell_
            others = [c for c in ("B5", "D5", "F5", "H5") if c != cell_]
            assert all(t(c) == round(pv(("B5", "D5", "F5", "H5").index(c), t("D3"))) for c in others), cell_
            rate = t("D3")
            put(svc, u, {"TM_OIS!D3": rate})                                      # the rate typed back: the same PV, to the TL
            assert t(cell_) == 1.25e6 and stored(svc, u, "TM_OIS").get("D3") == rate
        put(svc, u, {"TM_OIS!J5": "-400k"})
        num = -4e5 * sum(q) / side + sum(w * (legs[k][0] - legs[k][1]) for w, k in zip(q, (1, 2, 3)))
        want = num / sum(w * legs[k][2] for w, k in zip(q, (1, 2, 3)))
        assert t("J5") == -4e5 and close(t("D3"), want, 1e-12)
        assert stored(svc, u, "TM_OIS")["P4"] == -4e5 and "D3" not in stored(svc, u, "TM_OIS")
        put(svc, u, {"TM_OIS!F5": ""})                                            # Delete on another PV: the par
        assert t("D3") == "" and t("B6") == t("B4") and not any(k in stored(svc, u, "TM_OIS") for k in ("L4", "M4", "N4", "O4", "P4"))
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== USD · FOMC
def test_a_fomc_windows_rate_its_overnight_or_its_step(svc):
    """USD · FOMC, every active meeting: the window's O/N typed -> its OIS rate (the O/N's own day count, ACT/360, inverted),
    the step against Önceki ima; a step in bp or in steps of Adım typed -> the O/N = Önceki ima + the step -> the rate; each
    typed back gives the same row (1e-9); a meeting without a decision gives nothing."""
    u = svc.login("FOMC iki yönlü")["user"]
    f = lambda a: cell(svc, "SOFR_FOMC!" + a, u, book="sofr")                     # noqa: E731
    try:
        active = [r for r in range(ex.FOMC_BACK_ROWS[0], ex.FOMC_BACK_ROWS[1] + 1) if f("D%d" % r) == 1]
        assert len(active) >= 5
        for r in active:
            h, prev, step = f("H%d" % r), f("L%d" % r), f("B9")
            put(svc, u, {"SOFR_FOMC!AD%d" % r: "-25"}, book="sofr")
            on = prev - 0.25
            # (the O/N shown is the rate's own, worked back from the rate: the daily compounding costs ~1e-12)
            assert close(f("AC%d" % r), on, 1e-11) and close(f("AB%d" % r), ((1 + on / 36000) ** h - 1) * 36000 / h, 1e-13), r
            assert close(f("AE%d" % r), -25 / step, 1e-9)
            row = [f(c + str(r)) for c in ("AB", "AC", "AD", "AE")]
            for c, v in zip(("AB", "AC", "AD", "AE"), row):
                put(svc, u, {"SOFR_FOMC!%s%d" % (c, r): v}, book="sofr")
                assert all(close(f(x + str(r)), y, 1e-9) for x, y in zip(("AB", "AC", "AD", "AE"), row)), (r, c)
            put(svc, u, {"SOFR_FOMC!AE%d" % r: "-200"}, book="sofr")              # two steps cut (a % cell: −200 %)
            assert close(f("AC%d" % r), prev - 2 * step / 100, 1e-11) and close(f("AD%d" % r), -2 * step, 1e-9), r
        assert stored(svc, u, "SOFR_FOMC", "sofr") == {"AI%d" % r: -2.0 for r in active}
        r = active[1]
        put(svc, u, {"SOFR_FOMC!C%d" % r: "0"}, book="sofr")                      # no decision at that meeting: nothing
        assert f("D%d" % r) == 0 and f("AB%d" % r) == "" and f("AC%d" % r) == "" and f("AD%d" % r) == "" and f("AE%d" % r) == -2.0
    finally:
        svc.reset_inputs(u, "sofr")


def test_wirp_or_its_difference(svc):
    """WIRP (manuel) or "Fark WIRP (bp)" = (İma O/N − WIRP)·100: the difference typed gives WIRP = İma O/N − fark/100 (and the
    curve's WIRP column reads it); WIRP typed back gives the same difference; Delete: none."""
    u = svc.login("WIRP iki yönlü")["user"]
    f = lambda a: cell(svc, "SOFR_FOMC!" + a, u, book="sofr")                     # noqa: E731
    try:
        put(svc, u, {"SOFR_FOMC!Q76": "12"}, book="sofr")
        assert f("Q76") == 12.0 and close(f("P76"), f("K76") - 0.12, 1e-13) and f("BB76") == f("P76")
        assert isinstance(f("Q49"), float)                                       # (the curve's WIRP column: a WIRP is typed)
        p = f("P76")
        put(svc, u, {"SOFR_FOMC!P76": p}, book="sofr")
        assert close(f("Q76"), 12.0, 1e-9) and stored(svc, u, "SOFR_FOMC", "sofr") == {"P76": p}
        put(svc, u, {"SOFR_FOMC!Q76": ""}, book="sofr")
        assert f("P76") == "" and f("Q76") == "" and f("Q49") == ""
    finally:
        svc.reset_inputs(u, "sofr")


def test_what_is_typed_in_the_fomc_table_moves_with_its_meeting(tmp_path):
    """A pasted FOMC list without the first meeting: an O/N, a step or a WIRP difference typed (their stores) goes with its
    meeting; the meeting that left takes its values aside."""
    svc = make_service(tmp_path)
    try:
        a = svc.login("FOMC iki yönlü takvim")["user"]
        put(svc, a, {"SOFR_FOMC!AC74": "3,9", "SOFR_FOMC!AD76": "-25", "SOFR_FOMC!Q77": "5"}, book="sofr")
        assert stored(svc, a, "SOFR_FOMC", "sofr") == {"AG74": 3.9, "AH76": -25.0, "AJ77": 5.0}
        old = [cell(svc, "SOFR_FOMC!B%d" % r, book="sofr") for r in range(74, 84)]
        new = ["17.03.2027", "28.04.2027", "09.06.2027", "28.07.2027", "15.09.2027", "27.10.2027", "08.12.2027",
               "26.01.2028", "15.03.2028", "26.04.2028"]
        res = svc.paste(a, "sofr", "SOFR_FOMC!B74", "\n".join(new))
        assert res["errors"] == [] and res["calendar"]["parked"]["meetings"] == ["2026-12-09"]
        moved = stored(svc, a, "SOFR_FOMC", "sofr")
        assert moved == {"AH74": -25.0, "AJ75": 5.0}, (moved, old)
        assert mt.parked(svc.store)["fed"]["2026-12-09"]["user"] == {a: {"SOFR_FOMC!AG": 3.9}}
        f = lambda ref: cell(svc, "SOFR_FOMC!" + ref, a, book="sofr")            # noqa: E731
        assert f("AD74") == -25.0 and close(f("AC74"), f("L74") - 0.25, 1e-11) and f("Q75") == 5.0
    finally:
        svc.stop()


# ============================================================================== HTTP (last: the test client stops the service)
def test_the_http_api(svc):
    """``/api/inputs`` on a member, ``/api/cell``'s two-way info and ``/api/reset`` of the row-side."""
    from starlette.testclient import TestClient

    from conftest import auth
    from tto.server import create_app
    h = auth(svc, "TA iki yönlü http")
    u = svc.login("TA iki yönlü http")["user"]
    with TestClient(create_app(svc)) as client:
        res = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "EK_PPK!L5", "value": "-25"}]}, headers=h).json()
        assert res["applied"] == 1 and res["errors"] == []
        got = client.get("/api/cell", params={"book": "tto", "ref": "EK_PPK!G5"}, headers=h).json()
        assert got["input"]["twoway"]["anchor"] == {"member": "İma PPK adımı", "ref": "EK_PPK!L5"} and got["cell"]["ao"] == "İma PPK adımı · L5"
        assert client.post("/api/reset", json={"book": "tto", "refs": ["EK_PPK!K5"]}, headers=h).json()["reset"] == 1
        assert stored(svc, u, "EK_PPK") == {}
