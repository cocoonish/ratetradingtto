"""The Forward page's calculators two-way (the desk, 24.11.2026: "Genel olarak tablolar bu şekilde olmalı karışıklık
olmaması için", "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"): Interest 2 SP, SP 2
Interest, its all-in and Interest 2 SP · O/N (TRY, SP, All In, ON Karşılık, Günlük SP - USDTRY and EURTRY apart), the
Basit ↔ bileşik · Repo converters, Forward DV01 (Tutar and the three DV01s) and the bond carry (Carry, B/E, Px Drop and
its daily figure): any of a block's values can be typed - the one typed last stands, the others are worked out from it
with the block's own formulas and their exact inverses (``extras._tto_fwd_calc_tw``, ``extras._tto_bond_back``).  The
mechanism itself: ``test_twoway.py``."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import extras as ex
from tto.views import load_views

#: (block, its driver - the workbook's input until now -, its rows by kind)
BLOCKS = [(bid, hub, rows) for bid, _, hub, rows in ex.FX_CALC_BLOCKS]
KINDS = [k for k, _ in ex.FX_CALC_KINDS]
SIDES = (("AH", "AL"), ("AK", "AM"))
CARRY = {"Forward!V56": "TRB100227T13", "Forward!V57": "91,713", "Forward!V58": "05.11.2026", "Forward!V62": "03.02.2027"}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref if "!" in ref else "Forward!" + ref, "value": v} for ref, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def get(svc, user, ref):
    return cell(svc, "Forward!" + ref, user)


def stored(svc, user):
    return {k.split("!")[1]: v for (_, k), v in svc.store.user_inputs(user, "tto").items() if k.startswith("Forward!")}


def kinds_of(rows):
    return [k for k in KINDS if k in rows]


def market(svc, user, bid, rows, col):
    """What a block's half is priced on: spot, the USD / EUR rate, days and the day basis of its swap points."""
    basis = get(svc, user, "AH15") if (bid, col) == ("B7", "AH") else 360.0
    return [get(svc, user, "%s%d" % (col, rows[k])) for k in ("spot", "ccy", "days")] + [basis]


def block(kind, value, s, c, d, b, rows):
    """A block's members from one typed, worked out here: SP = spot·((1 + TRY·g/b)/(1 + CCY·g/b) − 1)·10000 and back,
    All In S -> E = spot + SP/10000, E -> S = spot − SP/10000, ON = 360·((1 + TRY·g/360)^(1/g) − 1) and back, Günlük = SP/g."""
    if kind in ex.FX_CALC_SP:
        sp = {"sp": value, "se": (value - s) * 1e4, "es": (s - value) * 1e4, "day": value * d}[kind]
        t = ((1 + sp / 1e4 / s) * (1 + c * d / b) - 1) * b / d
    else:
        t = value if kind == "try" else ((1 + value / 360) ** d - 1) * 360 / d
        sp = s * ((1 + t / b * d) / (1 + c / b * d) - 1) * 1e4
    out = {"try": t, "sp": sp, "se": s + sp / 1e4, "es": s - sp / 1e4, "on": 360 * ((1 + t * d / 360) ** (1 / d) - 1), "day": sp / d}
    out[kind] = value
    return {k: out[k] for k in kinds_of(rows)}


def values(svc, user, rows, col):
    return {k: get(svc, user, "%s%d" % (col, rows[k])) for k in kinds_of(rows)}


# ---------------------------------------------------------------------------------------------- the declaration
def test_the_calculators_are_two_way_groups_with_a_store_for_every_member(svc):
    """Every block's half, the three converters, Forward DV01, the bond carry, TRY OIS w/Spread and the OIS mid's shift
    are groups; the calculators' members all keep what is typed in a store (copyable blocks: twoway.py's limit), personal
    inputs on cells no input stood on, inside the page's hidden helper tables; the drivers (the inputs until now) are
    inputs no more; the bond carry's Carry and the two spreads keep what is typed in their own cells, as before (those
    tables are not copyable)."""
    assert svc.twoway.problems == {} and svc.books["tto"].left_out == []
    book = svc.books["tto"]
    view = next(v for v in load_views() if v["id"] == "forward")
    declared = set()
    for i in view["inputs"]:
        declared.update(book.cells_of(i["range"], "Forward"))
    groups = {g.id: g for g in svc.twoway.groups.values() if g.view == "forward" and g.id.startswith("fwdcalc-")}
    assert len(groups) == 15
    for gid, cell_ in (("fwdcalc-carry", "V61"), ("fwdcalc-ois-spread", "P58"), ("fwdcalc-ois-shift", "O27")):
        own = [m for m in groups[gid].members if m.own]
        assert len(own) == 1 and book.ref(*own[0].cells[0]) == "Forward!" + cell_ and book.cell("Forward!" + cell_) in declared
    assert all(not m.own for gid, g in groups.items() if gid not in ("fwdcalc-carry", "fwdcalc-ois-spread", "fwdcalc-ois-shift")
               for m in g.members)
    for bid, hub, rows in BLOCKS:
        for (col, store), tag in zip(SIDES, ("usd", "eur")):
            g = groups["fwdcalc-%s-%s" % (bid.lower(), tag)]
            assert [m.name for m in g.members] == [dict(ex.FX_CALC_KINDS)[k] for k in kinds_of(rows)]
            assert [book.ref(*m.cells[0]) for m in g.members] == ["Forward!%s%d" % (col, rows[k]) for k in kinds_of(rows)]
            assert [book.ref(*m.store[0]) for m in g.members] == ["Forward!%s%d" % (store, rows[k]) for k in kinds_of(rows)]
    stores = [c for g in groups.values() for m in g.members if not m.own for c in m.store]
    assert len(stores) == 2 * (5 + 6 + 6 + 5) + 6 + 4 + 3 + 10 + 1
    assert all(book.inputs[c].scope == "user" and c not in declared for c in stores)
    assert book.inputs[book.cell("Forward!Q45")].kind == "amount" and book.inputs[book.cell("Forward!AL10")].kind == "pct"
    for ref in ("AH10", "AK10", "AH25", "AK25", "AH40", "AK40", "AH56", "AK56", "AH60", "AH65", "AK63", "O45"):
        assert book.cell("Forward!" + ref) not in declared, ref
    helpers = {p["id"]: p for p in view["panels"] if p["id"] in ("IY1", "IY2", "IY3")}
    assert all(p["hidden"] and p["title"].startswith("Yardımcı · ") for p in helpers.values()) and len(helpers) == 3


def test_nothing_typed_every_number_is_the_workbooks(svc):
    """With nothing typed each block shows what the workbook computes - its driver the workbook's own value, the others
    its formulas (checked cell for cell against the commit before: none of the Forward sheet's values moved); the bond
    carry's Carry is empty and costs nothing."""
    u = svc.login("hy boş")["user"]
    assert [get(svc, u, a) for a in ("AH10", "AK10", "AH25", "AK25", "AH40", "AK40", "AH56", "AK56")] == \
        [0.36, 0.346, 3520.0, 22119.0 - 2540.0, 50.039, 75.07, 0.3445, 0.338]
    for bid, hub, rows in BLOCKS:
        for col, _ in SIDES:
            s, c, d, b = market(svc, u, bid, rows, col)
            want = block(hub, get(svc, u, "%s%d" % (col, rows[hub])), s, c, d, b, rows)
            assert values(svc, u, rows, col) == pytest.approx(want, rel=1e-12), (bid, col)
    assert (get(svc, u, "AH60"), get(svc, u, "AH65"), get(svc, u, "AK63"), get(svc, u, "O45")) == (0.47, 0.4885, 0.3835, 1e6)
    assert get(svc, u, "V61") == "" and get(svc, u, "V65") == 0.0


# ---------------------------------------------------------------------------------------------- each member typed
@pytest.mark.parametrize("bid,hub,rows", BLOCKS, ids=[b[0] for b in BLOCKS])
def test_each_member_typed_gives_the_others(svc, bid, hub, rows):
    """TRY, SP, an all-in, the O/N equivalent or the daily SP typed into a block's half: that one exactly, the others worked
    out from it (USDTRY on its own spot, USD rate and Gün Bazı, EURTRY on its own); the other half keeps its own."""
    u = svc.login("hy üye %s" % bid)["user"]
    try:
        for col, store in SIDES:
            s, c, d, b = market(svc, u, bid, rows, col)
            other = values(svc, u, rows, "AK" if col == "AH" else "AH")
            typed = {"try": 0.4012, "sp": 9876.5, "se": round(s + 1.2345, 4), "es": round(s - 0.4321, 4), "on": 0.3333, "day": 41.25}
            for kind in kinds_of(rows):
                put(svc, u, {"%s%d" % (col, rows[kind]): typed[kind]})
                got = values(svc, u, rows, col)
                assert got[kind] == typed[kind], (bid, col, kind)
                assert got == pytest.approx(block(kind, typed[kind], s, c, d, b, rows), rel=1e-10), (bid, col, kind)
                assert stored(svc, u) == {"%s%d" % (store, rows[kind]): typed[kind]}             # (one typed value)
            assert values(svc, u, rows, "AK" if col == "AH" else "AH") == other
            svc.reset_inputs(u, "tto")
    finally:
        svc.reset_inputs(u, "tto")


@pytest.mark.parametrize("bid,hub,rows", BLOCKS, ids=[b[0] for b in BLOCKS])
def test_a_computed_value_typed_back_gives_the_same_block(svc, bid, hub, rows):
    """Round trips: one member typed, each value it gives typed back as its own kind - the same block (1e-9)."""
    u = svc.login("hy gidiş dönüş %s" % bid)["user"]
    try:
        for col, _ in SIDES:
            s = get(svc, u, "%s%d" % (col, rows["spot"]))
            for start, value in (("try", 0.4123), ("sp", 12345.6), ("se", round(s + 0.75, 4)), ("on", 0.29)):
                put(svc, u, {"%s%d" % (col, rows[start]): value})
                want = values(svc, u, rows, col)
                for kind in kinds_of(rows):
                    put(svc, u, {"%s%d" % (col, rows[kind]): want[kind]})
                    assert values(svc, u, rows, col) == pytest.approx(want, rel=1e-9, abs=1e-9), (bid, col, start, kind)
            svc.reset_inputs(u, "tto")
    finally:
        svc.reset_inputs(u, "tto")


def test_the_last_typed_wins_and_delete_goes_back_to_the_default(svc):
    """Typing a member empties its block's other typed value; Delete on the typed member or on a computed one, and a reset
    of a cell of the block, take it back to the workbook's driver; the other half and the other blocks keep theirs."""
    u = svc.login("hy son yazılan")["user"]
    try:
        put(svc, u, {"AH10": "40"})
        assert stored(svc, u) == {"AL10": 0.4}
        put(svc, u, {"AH11": "5000"})
        assert stored(svc, u) == {"AL11": 5000.0} and get(svc, u, "AH11") == 5000.0 and get(svc, u, "AH10") != 0.4
        put(svc, u, {"AK14": "30", "AH26": "51,5"})                                    # the EURTRY half, SP 2 Interest
        assert stored(svc, u) == {"AL11": 5000.0, "AM14": 0.3, "AL26": 51.5}
        res = put(svc, u, {"AH12": ""})                                                 # Delete on a computed member
        assert stored(svc, u) == {"AM14": 0.3, "AL26": 51.5} and res["applied"] == 1 and get(svc, u, "AH10") == 0.36
        put(svc, u, {"AK14": ""})                                                       # Delete on the typed one
        assert stored(svc, u) == {"AL26": 51.5} and get(svc, u, "AK10") == 0.346
        assert svc.reset_inputs(u, "tto", ["Forward!AH30"])["reset"] == 1 and stored(svc, u) == {}      # "Kendi girdimi sil"
        assert get(svc, u, "AH25") == 3520.0
    finally:
        svc.reset_inputs(u, "tto")


def test_a_pasted_column_and_a_row(svc):
    """A column pasted over a block's half is one value - the last of it stands (the cells of a block are one row-side); a
    row pasted over both halves gives each half its own; a scenario keeps them."""
    u = svc.login("hy yapıştır")["user"]
    try:
        res = svc.paste(u, "tto", "Forward!AH10", "40\n\n59,5")                        # TRY, SP (blank), All In S -> E
        assert res["errors"] == [] and stored(svc, u) == {"AL12": 59.5}
        assert get(svc, u, "AH12") == 59.5 and get(svc, u, "AH11") == pytest.approx((59.5 - get(svc, u, "AH8")) * 1e4, rel=1e-15)
        svc.paste(u, "tto", "Forward!AH24", "35\t\t\t36")                              # SP 2 Interest's TRY, both halves
        assert stored(svc, u) == {"AL12": 59.5, "AL24": 0.35, "AM24": 0.36}
        want = {r: (get(svc, u, "AH%d" % r), get(svc, u, "AK%d" % r)) for r in (10, 11, 12, 24, 25, 28)}
        svc.save_scenario(u, "iki yönlü hesaplayıcı")
        svc.reset_inputs(u, "tto")
        assert stored(svc, u) == {}
        svc.load_scenario(u, "iki yönlü hesaplayıcı")
        assert stored(svc, u) == {"AL12": 59.5, "AL24": 0.35, "AM24": 0.36}
        assert {r: (get(svc, u, "AH%d" % r), get(svc, u, "AK%d" % r)) for r in (10, 11, 12, 24, 25, 28)} == want
    finally:
        svc.reset_inputs(u, "tto")


def test_what_was_typed_into_the_drivers_before_reads_as_before(svc):
    """A TRY, SP, all-in, O/N, converter rate or Tutar typed into the calculators' inputs before this (kept at their own
    cells), a scenario saved with one, a formula typed into one: the block's typed value - moved once to its store, the
    numbers as before; the formula (its cell is no input now) goes, its value stays, the log says so."""
    u = svc.login("hy eski")["user"]
    try:
        # (and an "Elle değer" over a member that was a formula, SP 2 Interest's EURTRY E -> S: of the two typed in its
        # block, the member declared later is its typed value - twoway.TwoWay.adopt)
        before = {"Forward!AH10": 0.4, "Forward!AK25": 20000.0, "Forward!AH40": 52.5, "Forward!AK56": 0.31,
                  "Forward!AH60": 0.45, "Forward!AK63": 0.37, "Forward!O45": 3e6, "Forward!AK27": 55.5}
        svc.store.set_user_inputs(u, "tto", before, {})
        svc._reload_user(u)
        assert stored(svc, u) == {"AL10": 0.4, "AL40": 52.5, "AM56": 0.31, "AL60": 0.45, "AM63": 0.37, "Q45": 3e6, "AM27": 55.5}
        assert get(svc, u, "AK25") == pytest.approx((get(svc, u, "AK22") - 55.5) * 1e4, rel=1e-12)
        for ref, v in before.items():
            if ref != "Forward!AK25":                                                     # (its row's typed value: AK27)
                assert cell(svc, ref, u) == v, ref
        rows = BLOCKS[0][2]                                                             # Interest 2 SP: TRY 40 %
        s, c, d, b = market(svc, u, "B7", rows, "AH")
        assert values(svc, u, rows, "AH") == pytest.approx(block("try", 0.4, s, c, d, b, rows), rel=1e-12)
        _, m = panel(svc, u, "B7")
        assert m["AH10"]["an"] == "SP, All In S -> E, ON Karşılık, Günlük SP" and m["AH11"]["ao"] == "TRY · AH10"
        svc.reset_inputs(u, "tto")
        # a scenario saved before: loaded, its values are the blocks' typed values
        svc.store.save_scenario(u, "eski", {("tto", "Forward!AH25"): 4000.0, ("tto", "Forward!AH56"): 0.33}, {})
        svc.load_scenario(u, "eski")
        assert stored(svc, u) == {"AL25": 4000.0, "AL56": 0.33} and get(svc, u, "AH25") == 4000.0 and get(svc, u, "AH56") == 0.33
        svc.reset_inputs(u, "tto")
        # a formula typed into the TRY before: its value stays, as the typed TRY
        svc.store.set_user_inputs(u, "tto", {"Forward!AH10": 0.42}, {"Forward!AH10": "=0.42"})
        svc._reload_user(u)
        assert ("tto", "Forward!AH10") not in svc.store.user_formulas(u) and stored(svc, u) == {"AL10": 0.42}
        assert get(svc, u, "AH10") == 0.42
    finally:
        svc.reset_inputs(u, "tto")


def panel(svc, user, pid, view="forward"):
    p = next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


def test_the_page_marks_the_typed_value_and_says_what_the_blocks_do(svc):
    """Every member an input; the one typed bold with ✎ (``an``: the members worked out from it), the others ``ao``; the
    note under each block; a formula typed into a member follows what it reads, and one reading its own block is a
    cycle, refused with the block's cells named."""
    u = svc.login("hy sayfa")["user"]
    try:
        put(svc, u, {"AK53": "100000"})
        for pid, cells in (("B7", "AH10 AH11 AH12 AH14 AH16 AK10 AK16"), ("B8", "AH24 AH25 AH26 AH27 AH28 AH30"),
                           ("B9", "AK38 AK39 AK40 AK41 AK42 AK44"), ("B10", "AH52 AH53 AH54 AH56 AH58"),
                           ("B11", "AH60 AH63 AH65 AH68 AK60 AK63"), ("B18", "O45 O47 O48 O49")):
            p, m = panel(svc, u, pid)
            assert all(m[c]["i"] == "u" for c in cells.split()), pid
            assert "hangisini yazarsanız o kalır, diğerleri ondan hesaplanır" in p["note"] or "diğeri ondan hesaplanır" in p["note"], pid
        _, m = panel(svc, u, "B10")
        assert m["AK53"]["an"] == "TRY, All In S -> E, ON Karşılık, Günlük SP" and m["AK53"]["m"] == 1
        assert m["AK56"]["ao"] == "SP · AK53" and "an" not in m["AH53"] and "ao" not in m["AH53"]
        # a formula: the EURTRY TRY of Interest 2 SP 25 bp under the USDTRY one (another group); one reading its own block
        put(svc, u, {"AK10": "=Forward!AH10-0.0025"})
        assert get(svc, u, "AK10") == pytest.approx(0.36 - 0.0025, abs=1e-15)
        put(svc, u, {"AH11": "4000"})
        assert get(svc, u, "AK10") == pytest.approx(get(svc, u, "AH10") - 0.0025, abs=1e-15)
        res = svc.set_inputs(u, "tto", [{"ref": "Forward!AH12", "value": "=Forward!AH11/10000+50"}])
        assert len(res["errors"]) == 1 and "döngüsel başvuru" in res["errors"][0] and "Forward!AL" not in res["errors"][0]
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- a temporary copy
def test_a_copy_of_a_calculator(svc):
    """A copy of Interest 2 SP: a member typed there is the copy's own - also where the table itself has another member
    typed (every member has a store: nothing is refused) -; the table stays as it is; Delete in the copy follows the
    table again."""
    u = svc.login("hy kopya")["user"]
    try:
        put(svc, u, {"AH10": "40"})                                                    # the table's own TRY
        cid = svc.copy_action(u, "open", {"view": "forward", "panel": "B7"})["copy"]["id"]

        def copy_put(cells):
            return svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "Forward!" + k, "value": v} for k, v in cells.items()]})

        def copy_value(ref):
            def run():
                cp = svc.copies.find(u, cid)
                return svc.copies.calc(u, cp).value("Forward!" + ref)
            return svc.et.call(run)

        assert copy_value("AH10") == 0.4                                               # (it starts with the table's)
        res = copy_put({"AH11": "5000"})
        assert res["errors"] == [] and copy_value("AH11") == 5000.0
        rows = BLOCKS[0][2]
        s, c, d, b = (copy_value("AH8"), copy_value("AH9"), copy_value("AH7"), copy_value("AH15"))
        want = block("sp", 5000.0, s, c, d, b, rows)
        assert {k: copy_value("AH%d" % rows[k]) for k in kinds_of(rows)} == pytest.approx(want, rel=1e-10)
        assert get(svc, u, "AH10") == 0.4 and stored(svc, u) == {"AL10": 0.4}           # the table's own
        page = svc.view(u, "forward")["panels"]
        pane = next(p for p in page if (p.get("copy") or {}).get("id") == cid)
        d_ = pane["data"]
        shown = {"%s%d" % (cc, r): x for r, line in zip(d_["r"], d_["rows"]) for cc, x in zip(d_["c"], line)}
        assert shown["AH11"]["an"] and shown["AH10"]["ao"] == "SP · AH11" and "ro" not in shown["AH11"]
        res = copy_put({"AH10": ""})                                                    # Delete: the table's block again
        assert res["applied"] == 1 and copy_value("AH10") == 0.4 and copy_value("AH11") == pytest.approx(get(svc, u, "AH11"))
        svc.copy_action(u, "close", {"copy": cid})
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- Basit ↔ bileşik · Repo
def test_the_converters(svc):
    """Each converter's two rates: the simple rate of the period from a rate compounded daily, and back - each typed, the
    other from it; typed back, the same (1e-12)."""
    u = svc.login("hy çevirici")["user"]
    try:
        # (the driver - the input until now -, its store, the other rate, the Gün Basis, the Gün, whether the driver is
        # the rate compounded daily)
        for driver, store, other, basis, days, daily in (("AH60", "AL60", "AH63", "AH61", "AH62", True),
                                                         ("AH65", "AL65", "AH68", "AH66", "AH67", False),
                                                         ("AK63", "AM63", "AK60", "AK61", "AK62", False)):
            b, n = get(svc, u, basis), get(svc, u, days)

            def simple(r):                                                             # the period's simple rate of a daily one
                return ((1 + r / b) ** n - 1) * b / n

            def daily_of(r):                                                           # the daily rate of a simple one
                return b * ((1 + r * n / b) ** (1 / n) - 1)

            put(svc, u, {other: "41"})
            assert get(svc, u, other) == 0.41
            assert get(svc, u, driver) == pytest.approx(daily_of(0.41) if daily else simple(0.41), rel=1e-12), driver
            back = get(svc, u, driver)
            put(svc, u, {driver: back})
            assert stored(svc, u) == {store: back} and get(svc, u, other) == pytest.approx(0.41, rel=1e-12), driver
            svc.reset_inputs(u, "tto")
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- Forward DV01
def test_forward_dv01(svc):
    """Tutar, DV01_USD, DV01_TRY or TRY_USD_DV01: a DV01 typed is read as its size (the absolute value), its sign the B/S
    row's - S a positive USD DV01 and a negative TRY one, B the other way round -; Tutar from it, the others from Tutar
    with the block's own formulas; the desk's shorthand in Tutar; typed back, the same."""
    u = svc.login("hy dv01")["user"]
    try:
        g = {k: get(svc, u, k) for k in ("O32", "O37", "O42", "O43", "O46")}
        per_usd, per_tl = g["O43"] * g["O42"] / 1e4, g["O46"] * g["O43"] * g["O37"] / 1e4
        for side, su, st in (("B", -1, 1), ("S", 1, -1)):
            put(svc, u, {"O44": side})
            for ref, typed in (("O47", 250.0), ("O47", -250.0), ("O48", -12000.0), ("O49", 240.0)):
                put(svc, u, {ref: typed})
                size = {"O47": abs(typed) / per_usd, "O48": abs(typed) / per_tl, "O49": abs(typed * g["O32"]) / per_tl}[ref]
                assert get(svc, u, "O45") == pytest.approx(size, rel=1e-12), (side, ref)
                want = {"O47": su * size * per_usd, "O48": st * size * per_tl, "O49": st * size * per_tl / g["O32"]}
                got = {k: get(svc, u, k) for k in want}
                assert got == pytest.approx(want, rel=1e-12) and got[ref] == (su if ref == "O47" else st) * abs(typed), (side, ref)
                tutar = get(svc, u, "O45")
                put(svc, u, {"O45": tutar})                                              # typed back: the same
                assert {k: get(svc, u, k) for k in want} == pytest.approx(got, rel=1e-12)
        put(svc, u, {"O45": "3m"})
        assert get(svc, u, "O45") == 3e6 and stored(svc, u)["Q45"] == 3e6
        put(svc, u, {"O45": ""})
        assert get(svc, u, "O45") == 1e6
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the bond carry
def test_the_bond_carry(svc):
    """Carry (in its own cell, as before), B/E, Px Drop or its daily figure: each typed, the others from it - a B/E typed
    gives the repo "İma repo" reads of that price; Delete takes Carry back to empty (Carry Maliyet 0, as a blank Carry
    was); "Fwd temiz fiyat (elle)" → "İma repo" stays as it was."""
    u = svc.login("hy carry")["user"]
    try:
        put(svc, u, CARRY)
        assert get(svc, u, "V61") == "" and get(svc, u, "V65") == 0.0
        n, clean, coupon, dirty = (get(svc, u, a) for a in ("V63", "V57", "V66", "V60"))
        assert n == 90.0
        put(svc, u, {"V61": "36"})
        be = get(svc, u, "V67")
        assert be == pytest.approx(clean - coupon + dirty * 0.36 / 365 * n, rel=1e-12) and stored(svc, u)["V61"] == 0.36
        assert get(svc, u, "V70") == pytest.approx(clean - be) and get(svc, u, "W70") == pytest.approx((clean - be) / n)
        for ref, typed in (("V67", round(be + 0.5, 3)), ("V70", -1.25), ("W70", -0.02)):
            put(svc, u, {ref: typed})
            want_be = {"V67": typed, "V70": clean - typed, "W70": clean - typed * n}[ref]
            assert get(svc, u, ref) == typed and get(svc, u, "V67") == pytest.approx(want_be, rel=1e-12), ref
            repo = get(svc, u, "V61")
            assert repo == pytest.approx((want_be - clean + coupon) * 365 / (dirty * n), rel=1e-12), ref
            assert "V61" not in stored(svc, u)
            put(svc, u, {"V71": want_be})                                                 # the way back of 24.11 agrees
            assert get(svc, u, "V72") == pytest.approx(repo, rel=1e-12)
            put(svc, u, {"V61": repo})                                                    # the repo typed back: the same B/E
            assert get(svc, u, "V67") == pytest.approx(want_be, rel=1e-12, abs=1e-9) and stored(svc, u)["V61"] == repo
        put(svc, u, {"V67": ""})
        assert get(svc, u, "V61") == "" and get(svc, u, "V65") == 0.0 and get(svc, u, "V67") == pytest.approx(clean - coupon, rel=1e-12)
        _, m = panel(svc, u, "B24")
        assert all(m[c]["i"] == "u" for c in ("V61", "V67", "V70", "W70")) and "i" not in m["V68"] and "i" not in m["V69"]
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- TRY OIS + spread
def test_try_ois_w_spread_and_the_shifted_mid(svc):
    """TRY OIS w/Spread: a tenor's rate typed gives the Spread (rate − OIS) and the other tenors from it - one value for
    the column; the Spread typed stands as before; Delete on any of them: the desk's spread (MASA!I60) again.  The OIS mid
    at the value date: its shifted rate typed gives the shift.  The chart data reading the Spread follows it."""
    u = svc.login("hy ois spread")["user"]
    try:
        desk = get(svc, u, "P58")
        assert desk == cell(svc, "MASA!I60", u) / 100
        ois = {r: get(svc, u, "P%d" % (r - 53)) for r in range(59, 69)}
        typed = round(ois[63] - 0.85, 2)                                                # 3M, 85 bp under OIS
        put(svc, u, {"P63": typed})
        spread = typed - ois[63]
        assert get(svc, u, "P63") == typed and get(svc, u, "P58") == pytest.approx(spread, abs=1e-12) and stored(svc, u) == {"Q63": typed}
        assert [get(svc, u, "P%d" % r) for r in range(59, 69)] == pytest.approx([ois[r] + spread for r in range(59, 69)], abs=1e-12)
        assert get(svc, u, "AE123") == pytest.approx(get(svc, u, "AD123") + spread / 100, abs=1e-12)
        _, m = panel(svc, u, "B23")
        assert m["P63"]["an"].startswith("Spread, 1W") and m["P58"]["ao"] == "3M · P63" and m["P66"]["ao"] == "3M · P63"
        put(svc, u, {"P66": get(svc, u, "P66")})                                         # another tenor typed back: the same
        assert get(svc, u, "P58") == pytest.approx(spread, abs=1e-12) and stored(svc, u) == {"Q66": pytest.approx(ois[66] + spread)}
        put(svc, u, {"P58": "-2"})                                                       # the Spread itself, as before
        assert stored(svc, u) == {"P58": -2.0} and get(svc, u, "P63") == pytest.approx(ois[63] - 2, abs=1e-12)
        put(svc, u, {"P61": "35"})
        res = put(svc, u, {"P66": ""})                                                   # Delete on any tenor
        assert stored(svc, u) == {} and get(svc, u, "P58") == desk and res["applied"] == 1
        # the OIS mid at the value date, shifted
        p24 = get(svc, u, "P24")
        put(svc, u, {"P27": "36,5"})
        assert get(svc, u, "P27") == 0.365 and get(svc, u, "O27") == pytest.approx(0.365 - p24, abs=1e-15) and stored(svc, u) == {"Q27": 0.365}
        put(svc, u, {"O27": "-1"})
        assert stored(svc, u) == {"O27": -0.01} and get(svc, u, "P27") == pytest.approx(p24 - 0.01, abs=1e-15)
        put(svc, u, {"P27": ""})
        assert stored(svc, u) == {} and get(svc, u, "O27") == cell(svc, "MASA!I60", u) / 10000
        p, _ = panel(svc, u, "B4")
        assert "hangisini yazarsanız o kalır, diğeri ondan hesaplanır" in p["note"]
    finally:
        svc.reset_inputs(u, "tto")


GROUPS = ["fwdcalc-%s-%s" % (b, s) for b in ("b7", "b8", "b9", "b10") for s in ("usd", "eur")] + [
    "fwdcalc-b11-basit", "fwdcalc-b11-bilesik", "fwdcalc-b11-repo", "fwdcalc-dv01", "fwdcalc-carry", "fwdcalc-ois-spread",
    "fwdcalc-ois-shift"]


@pytest.mark.parametrize("gid", GROUPS)
def test_every_group_types_deletes_and_reads_back(svc, gid):
    """Every group of the page: its last member typed is the block's typed value (kept in its store, shown exactly, marked);
    the first member typed after it takes its place; Delete on a member worked out from it takes the block back to its
    default, every member as before; a value kept before at the member's own cell reads as that typed value."""
    g = svc.twoway.groups[gid]
    book = svc.books["tto"]
    u = svc.login("hy grup %s" % gid)["user"]
    first, last = g.members[0], g.members[-1]
    refs = [book.ref(*m.cells[0]) for m in g.members]
    key = lambda m: book.ref(*m.store[0]).split("!")[1]                                # noqa: E731 - where its value is kept
    try:
        if gid == "fwdcalc-carry":
            put(svc, u, CARRY)                                                         # (a bond, its price and dates)
        base = stored(svc, u)
        before = [cell(svc, r, u) for r in refs]
        v = before[-1] * 1.001 if isinstance(before[-1], float) and before[-1] else 1.25
        res = svc.set_inputs(u, "tto", [{"ref": refs[-1], "value": v}])
        assert res["errors"] == [] and res["applied"] == 1
        assert cell(svc, refs[-1], u) == v and stored(svc, u) == dict(base, **{key(last): v}), gid
        tables = [x for x in svc.view(u, "forward")["panels"] if (x.get("data") or {}).get("sheet") == "Forward"]
        shown = next(_cells_of(x) for x in tables if refs[-1].split("!")[1] in _cells_of(x))
        assert shown[refs[-1].split("!")[1]].get("an"), gid
        w = cell(svc, refs[0], u)
        svc.set_inputs(u, "tto", [{"ref": refs[0], "value": w}])                       # the first one typed: it stands
        assert stored(svc, u) == dict(base, **{key(first): w}), gid
        res = svc.set_inputs(u, "tto", [{"ref": refs[-1], "value": ""}])                # Delete on one worked out from it
        assert res["errors"] == [] and stored(svc, u) == base and [cell(svc, r, u) for r in refs] == before, gid
        # a value kept at the last member's own cell by an earlier version ("Elle değer"): that block's typed value
        svc.store.set_user_inputs(u, "tto", {refs[-1]: v}, {})
        svc._reload_user(u)
        assert stored(svc, u) == dict(base, **{key(last): v}) and cell(svc, refs[-1], u) == v, gid
    finally:
        svc.reset_inputs(u, "tto")


def _cells_of(p):
    d = p["data"]
    return {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}
