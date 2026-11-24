"""Hesaplayıcılar and DV01 Risk's scenario P&L, two-way (the desk, 24.11.2026: "hangisine ben girdiysem diğerini
hesaplasın ... Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"): any value of a calculator
can be typed - the one typed last stands, the others are worked out from it with the block's own formulas and their exact
inverses (``extras.TW_HUBS``; the mechanism itself: ``test_twoway.py``).  Each calculator is checked here against a
calculation of its own: each member typed gives the others, each value typed back as its own kind gives the same row,
the last typed wins, Delete, a paste, a scenario, a temporary copy, the values typed before."""
from __future__ import annotations

import math
import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.views import load_views
from tto.xl.model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALC = "Calculators"


def _move(c):
    r = math.sqrt(c["O37"] / c["O38"])
    s = c["O36"]
    fwd = lambda v: {"O39": v, "O40": r * v, "O41": (1 + r * v) * s, "O42": (1 - r * v) * s, "O43": s * r * v * 10000}
    inv = {"O40": lambda x: x / r, "O41": lambda x: (x / s - 1) / r, "O42": lambda x: (1 - x / s) / r,
           "O43": lambda x: x / (s * 10000) / r}
    return fwd, inv


def _basit(c):
    b, d = c["O13"], c["O14"]
    fwd = lambda s: {"O12": s, "O15": (1 + s * d / b) ** (b / d) - 1}
    return fwd, {"O15": lambda x: ((1 + x) ** (d / b) - 1) * b / d}


def _bilesik(c):
    b, d = c["R13"], c["R14"]
    fwd = lambda x: {"R12": x, "R15": ((x + 1) ** (1 / (b / d)) - 1) * (b / d)}
    return fwd, {"R15": lambda s: (1 + s * d / b) ** (b / d) - 1}


def _df(c):
    t = (c["R37"] - c["R36"]) / c["R41"]
    fwd = lambda df: {"R38": df, "R39": (1 / df - 1) / t, "R40": -math.log(df) / t}
    return fwd, {"R39": lambda x: 1 / (1 + x * t), "R40": lambda x: math.exp(-x * t)}


def _exp(c):
    fwd = lambda i: {"O8": i, "O9": c["O7"] * math.exp(i * c["O6"] / 360)}
    return fwd, {"O9": lambda f: math.log(f / c["O7"]) * 360 / c["O6"]}


def _exp_back(c):
    fwd = lambda f: {"R9": f, "R8": math.log(f / c["R7"]) * 360 / c["R6"]}
    return fwd, {"R8": lambda i: c["R7"] * math.exp(i * c["R6"] / 360)}


def _simple(c):
    fwd = lambda i: {"U8": i, "U9": c["U7"] + c["U7"] * i * c["U6"] / 360}
    return fwd, {"U9": lambda f: (f / c["U7"] - 1) * 360 / c["U6"]}


def _simple_back(c):
    fwd = lambda f: {"X9": f, "X8": (f - c["X7"]) / c["X7"] * 360 / c["X6"]}
    return fwd, {"X8": lambda i: c["X7"] * (1 + i * c["X6"] / 360)}


def _tlref(c):
    fwd = lambda p: {"C54": p, "C56": (100 - p) / 100 * 365 / c["C55"] * 10000}
    return fwd, {"C56": lambda x: 100 - x * c["C55"] / 36500}


def _fwdvol(c):
    a, e, v0 = c["F52"], c["F53"], c["F54"]
    fwd = lambda v1: {"F55": v1, "F56": math.sqrt((v1 ** 2 * e - v0 ** 2 * a) / (e - a))}
    return fwd, {"F56": lambda x: math.sqrt((x ** 2 * (e - a) + v0 ** 2 * a) / e)}


def _yield(c):
    fwd = lambda y: {"O56": y, "O57": c["O55"] * y / 360 * c["O53"] + c["O55"]}
    return fwd, {"O57": lambda f: (f / c["O55"] - 1) * 360 / c["O53"]}


def _yield_back(c):
    fwd = lambda last: {"O66": last, "O65": (last - c["O64"]) / c["O64"] * 365 / c["O62"]}
    return fwd, {"O65": lambda y: c["O64"] * (1 + y * c["O62"] / 365)}


def _band(c):
    fwd = lambda f: {"AA10": f, "AA11": f - c["AA9"], "AA12": (f - c["AA9"]) * 10000}
    return fwd, {"AA11": lambda x: c["AA9"] + x, "AA12": lambda x: c["AA9"] + x / 10000}


#: group -> (its table, the block's inputs it is computed from, the model, a value per member to type)
CALCS = {
    "calc-move": ("B23", ("O36", "O37", "O38"), _move, {"O39": 0.23, "O40": 0.081, "O41": 42.0, "O42": 35.25, "O43": 31234.5}),
    "calc-basit": ("B8", ("O13", "O14"), _basit, {"O12": 0.4125, "O15": 0.52}),
    "calc-bilesik": ("B9", ("R13", "R14"), _bilesik, {"R12": 0.48, "R15": 0.39}),
    "calc-df": ("B24", ("R36", "R37", "R41"), _df, {"R38": 0.81, "R39": 0.375, "R40": 0.33}),
    "calc-exp": ("B5", ("O6", "O7"), _exp, {"O8": 0.41, "O9": 61.5}),
    "calc-exp-back": ("B5", ("R6", "R7"), _exp_back, {"R9": 58.25, "R8": 0.37}),
    "calc-simple": ("B6", ("U6", "U7"), _simple, {"U8": 0.41, "U9": 71.5}),
    "calc-simple-back": ("B6", ("X6", "X7"), _simple_back, {"X9": 66.125, "X8": 0.43}),
    "calc-tlref": ("B27", ("C55",), _tlref, {"C54": 97.25, "C56": 55.5}),
    "calc-fwdvol": ("B28", ("F52", "F53", "F54"), _fwdvol, {"F55": 0.31, "F56": 0.35}),
    "calc-yield": ("B31", ("O53", "O55"), _yield, {"O56": 0.31, "O57": 51.25}),
    "calc-yield-back": ("B32", ("O62", "O64"), _yield_back, {"O66": 49.5, "O65": 0.42}),
    "calc-band": ("B7", ("AA9",), _band, {"AA10": 52.75, "AA11": 1.125, "AA12": 9876.5}),
}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells, sheet=CALC):
    res = svc.set_inputs(user, "tto", [{"ref": "%s!%s" % (sheet, ref), "value": v} for ref, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def got(svc, user, cells, sheet=CALC):
    return {c: cell(svc, "%s!%s" % (sheet, c), user) for c in cells}


def stored(svc, user, sheet=CALC):
    return {k.split("!")[1]: v for (_, k), v in svc.store.user_inputs(user, "tto").items() if k.startswith(sheet + "!")}


def model_of(svc, user, gid):
    """The calculator's own calculation on the block's inputs as the user's sheet has them."""
    _, inputs, make, _ = CALCS[gid]
    return make(got(svc, user, inputs, "DV01_RISK" if gid.startswith("dv01") else CALC))


def members(svc, gid):
    return [svc.books["tto"].ref(*m.cells[0]).split("!")[1] for m in svc.twoway.groups[gid].members]


def panel(svc, user, view, pid, hidden=False):
    p = next(p for p in svc.view(user, view, hidden)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


# ---------------------------------------------------------------------------------------------- the declarations
def test_the_calculators_are_two_way_groups(svc):
    """Every calculator of Hesaplayıcılar is a group: its hub and the values computed from it, each kept in a store of
    its own (the top band's Forward and DV01's shocks in place, inputs as before); the stores are personal inputs on
    cells no input ever stood on, inside a hidden helper table of their page."""
    assert svc.twoway.problems == {} and svc.books["tto"].left_out == []
    book = svc.books["tto"]
    views = {v["id"]: v for v in load_views()}
    retired = set()
    for x in ex.RETIRED_INPUTS.get("tto", ()):
        retired.update(book.cells_of(x))
    for gid in list(CALCS) + ["dv01-scenario"]:
        g = svc.twoway.groups[gid]
        view = views["dv01" if gid.startswith("dv01") else "calc"]
        declared = set()
        for i in view["inputs"]:
            declared.update(book.cells_of(i["range"], view["sheet"]))
        own = {"calc-band": "AA10", "dv01-scenario": "E69"}.get(gid)
        for m in g.members:
            first = book.ref(*m.cells[0]).split("!")[1]
            if first == own:
                assert m.own and all(c in book.inputs and book.inputs[c].scope == "user" for c in m.cells), gid
                continue
            assert not m.own and all(c not in book.inputs for c in m.cells), (gid, m.name)
            assert all(book.inputs[c].scope == "user" and book.inputs[c].kind == "number" for c in m.store), (gid, m.name)
            assert not set(m.store) & (declared | retired), (gid, m.name)
    # the hubs that were the page's inputs are not any more (their stores are): one per calculator
    calc_inputs = {i["range"] for i in views["calc"]["inputs"]}
    assert not {"O8", "R9", "U8", "X9", "O12", "R12", "R38", "O39", "C54", "F55", "O56", "O66"} & calc_inputs
    assert {"AA10", "O36", "O37", "O38", "O44", "O46", "O48"} <= calc_inputs
    assert [m.name for m in svc.twoway.groups["calc-move"].members] == ["Volatilite", "Implied Move", "Upper Bound",
                                                                         "Lower Bound", "Move By Pips"]


def test_nothing_typed_the_calculators_show_what_they_showed(svc):
    """With nothing typed every calculator shows the file's values as before: its hub the workbook's own value (the top
    band's Forward the market's), each member its workbook formula's."""
    u = svc.login("hy varsayılan")["user"]
    raw = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    sh = raw.sheet(CALC)
    from tto.xl.model import parse_a1
    for gid, (_, _, _, sample) in CALCS.items():
        if gid == "calc-band":
            continue
        hub = members(svc, gid)[0]
        assert cell(svc, "%s!%s" % (CALC, hub), u) == sh.consts[parse_a1(hub)], gid
        fwd, _ = model_of(svc, u, gid)
        want = fwd(sh.consts[parse_a1(hub)])
        assert got(svc, u, want) == pytest.approx(want, rel=1e-12, abs=1e-12), gid
    assert cell(svc, CALC + "!AA10", u) == pytest.approx(cell(svc, "Forward!E30", u), rel=1e-6)          # (the market's)


# ---------------------------------------------------------------------------------------------- typing
@pytest.mark.parametrize("gid", sorted(CALCS))
def test_each_value_typed_gives_the_others(svc, gid):
    """Any member typed: that value exactly, the others the block's formulas of the hub it gives (the formula solved for
    the hub) - and back: each value typed again as its own kind gives the same calculator (1e-9)."""
    u = svc.login("hy " + gid)["user"]
    _, _, _, sample = CALCS[gid]
    cells = members(svc, gid)
    try:
        for m, x in sample.items():
            put(svc, u, {m: x})
            fwd, inv = model_of(svc, u, gid)
            want = fwd(x if m == cells[0] else inv[m](x))
            now = got(svc, u, cells)
            assert now[m] == x and now == pytest.approx(want, rel=1e-9, abs=1e-9), (gid, m)
            for k in cells:                                               # each value typed back as its own kind
                put(svc, u, {k: now[k]})
                assert got(svc, u, cells) == pytest.approx(now, rel=1e-9, abs=1e-9), (gid, m, k)
                store = svc.books["tto"].twoway[svc.books["tto"].cell("%s!%s" % (CALC, k))].store_cell
                assert list(stored(svc, u)) == [svc.books["tto"].ref(*store).split("!")[1]], (gid, m, k)
    finally:
        svc.reset_inputs(u, "tto")


def test_implied_move_from_a_breakeven_and_the_desks_typing(svc):
    """Implied Move: a straddle's upper breakeven typed gives its vol and the lower breakeven at that vol; typed as the
    desk types them (a %, a level, pips with thousands); the way back's own boxes (O44 / O46 / O48) stay beside it and
    agree with it."""
    u = svc.login("hy implied")["user"]
    try:
        put(svc, u, {"O41": "42,3125"})
        spot = cell(svc, CALC + "!O36", u)
        vol = cell(svc, CALC + "!O39", u)
        assert vol == pytest.approx((42.3125 / spot - 1) / math.sqrt(90 / 360), rel=1e-12)
        assert cell(svc, CALC + "!O42", u) == pytest.approx(2 * spot - 42.3125, rel=1e-12)
        put(svc, u, {"O46": "42,3125"})                                   # the 24.11 box: the same vol
        assert cell(svc, CALC + "!O47", u) == pytest.approx(vol, rel=1e-12)
        put(svc, u, {"O40": "9,5"})
        assert cell(svc, CALC + "!O40", u) == 0.095 and cell(svc, CALC + "!O39", u) == pytest.approx(0.19, rel=1e-12)
        put(svc, u, {"O43": "36.717,5"})
        assert cell(svc, CALC + "!O43", u) == 36717.5 and cell(svc, CALC + "!O39", u) == pytest.approx(0.19, rel=1e-12)
        # the spot, days and basis are the block's inputs still: the typed value stays, the vol follows them
        put(svc, u, {"O37": "30"})
        assert cell(svc, CALC + "!O43", u) == 36717.5 and cell(svc, CALC + "!O39", u) == pytest.approx(0.095 / math.sqrt(30 / 360))
    finally:
        svc.reset_inputs(u, "tto")


def test_the_last_typed_wins_and_delete_goes_back_to_the_default(svc):
    """Typing one value of a calculator clears the one typed before; Delete on the typed value or on a computed one, a
    reset of a cell ("Kendi girdimi sil") and "Girdilerimi sıfırla": the calculator shows its default again."""
    u = svc.login("hy son")["user"]
    put(svc, u, {"O39": "25"})
    assert stored(svc, u) == {"AP39": 0.25}
    put(svc, u, {"O42": "33"})
    assert stored(svc, u) == {"AP42": 33.0} and cell(svc, CALC + "!O42", u) == 33.0
    put(svc, u, {"O43": "20000", "R39": "40"})                            # (another calculator: its own)
    assert stored(svc, u) == {"AP43": 20000.0, "AK39": 0.4}
    res = put(svc, u, {"O40": ""})                                         # Delete on a computed value
    assert res["applied"] == 1 and stored(svc, u) == {"AK39": 0.4} and cell(svc, CALC + "!O39", u) == 0.19
    put(svc, u, {"R39": ""})                                               # Delete on the typed value itself
    assert stored(svc, u) == {} and cell(svc, CALC + "!R38", u) == 0.706695
    put(svc, u, {"C56": "75"})
    assert svc.reset_inputs(u, "tto", [CALC + "!C54"])["reset"] == 1 and stored(svc, u) == {}
    put(svc, u, {"C56": "75", "F56": "30"})
    assert svc.reset_inputs(u, "tto")["reset"] == 2 and stored(svc, u) == {}
    # the top band's Forward is kept in place: typed there it is the input it was, its difference and points follow
    put(svc, u, {"AA12": "15000"})
    assert stored(svc, u) == {"AH12": 15000.0}
    assert cell(svc, CALC + "!AA10", u) == pytest.approx(cell(svc, CALC + "!AA9", u) + 1.5, abs=1e-12)
    put(svc, u, {"AA10": "53"})
    assert stored(svc, u) == {"AA10": 53.0} and cell(svc, CALC + "!AA12", u) == pytest.approx((53 - cell(svc, CALC + "!AA9", u)) * 1e4)
    put(svc, u, {"AA11": ""})
    assert stored(svc, u) == {} and cell(svc, CALC + "!AA10", u) == pytest.approx(cell(svc, "Forward!E30", u), rel=1e-6)


def test_a_pasted_column_and_a_scenario(svc):
    """A column pasted over one calculator: one row-side - the last value of the paste stands (here the pips); a scenario
    saved with typed values of several calculators loads back as it was."""
    u = svc.login("hy yapıştır")["user"]
    try:
        res = svc.paste(u, "tto", CALC + "!O39", "20\n0,1\n\n\n25000")
        assert res["errors"] == [] and stored(svc, u) == {"AP43": 25000.0}
        assert cell(svc, CALC + "!O43", u) == 25000.0
        put(svc, u, {"O15": "45", "R40": "30", "F56": "28"})
        want = got(svc, u, ["O12", "O15", "R38", "R39", "R40", "F55", "F56", "O39", "O43"])
        svc.save_scenario(u, "hesap iki yönlü")
        svc.reset_inputs(u, "tto")
        assert stored(svc, u) == {}
        svc.load_scenario(u, "hesap iki yönlü")
        assert stored(svc, u) == {"AP43": 25000.0, "AI15": 0.45, "AK40": 0.3, "AR56": 0.28}
        assert got(svc, u, list(want)) == want
    finally:
        svc.reset_inputs(u, "tto")


def test_values_typed_before_keep_their_meaning(svc):
    """What users typed before this change: a hub typed when it was the page's input (Volatilite, Basit, the DF ...) is
    its calculator's typed value now - moved to its store once, reading the same; a value typed over a computed cell
    ("Elle değer") likewise; one typed as an input formula keeps its value (the formula goes: the cell is no input of
    its own any more - inputformula's rule, said in the log); the top band's Forward and DV01's shocks, in place, read as
    they did."""
    u = svc.login("hy eski")["user"]
    svc.store.set_user_inputs(u, "tto", {CALC + "!O39": 0.27, CALC + "!O12": 0.5, CALC + "!R38": 0.9, CALC + "!O15": 0.66,
                                         CALC + "!AA10": 55.5, "DV01_RISK!E70": 7.0, CALC + "!C54": 99.0},
                              {CALC + "!C54": "=Calculators!O36+60.35"})
    svc._reload_user(u)
    # (Basit and Bileşik both typed over: the one declared later - Bileşik - is the calculator's)
    assert stored(svc, u) == {"AP39": 0.27, "AI15": 0.66, "AK38": 0.9, "AA10": 55.5, "AQ54": 99.0}
    assert stored(svc, u, "DV01_RISK") == {"E70": 7.0}
    assert cell(svc, CALC + "!O39", u) == 0.27 and cell(svc, CALC + "!O40", u) == pytest.approx(0.27 * 0.5)
    assert cell(svc, CALC + "!R38", u) == 0.9 and cell(svc, CALC + "!O15", u) == 0.66 and cell(svc, CALC + "!C54", u) == 99.0
    assert cell(svc, CALC + "!AA10", u) == 55.5 and cell(svc, "DV01_RISK!E70", u) == 7.0
    assert ("tto", CALC + "!AQ54") not in svc.store.user_formulas(u)
    _, m = panel(svc, u, "calc", "B23")
    assert m["O39"]["an"] == "Implied Move, Upper Bound, Lower Bound, Move By Pips" and m["O39"]["m"] == 1
    assert m["O41"]["ao"] == "Volatilite · O39" and m["O41"]["i"] == "u"
    book = svc.books["tto"]
    assert book.cell(CALC + "!O39") not in book.inputs                                   # (no "Elle değer" declared)
    svc.reset_inputs(u, "tto")


def test_the_page_marks_the_typed_value_and_says_how(svc):
    """The page: every member of a calculator an input (``i``), the typed one marked (``an``), the others worked out from
    it (``ao``); the note under each calculator says it is two-way; the stores in their helper table."""
    u = svc.login("hy sayfa")["user"]
    try:
        put(svc, u, {"O57": "51", "R15": "40"})
        p, m = panel(svc, u, "calc", "B31")
        assert p["note"].startswith("İki yönlü: Ann. Yield ya da Forward - hangisini yazarsanız o kalır, diğerleri ondan hesaplanır")
        assert m["O57"]["an"] == "Ann. Yield" and m["O56"]["ao"] == "Forward · O57" and m["O55"]["i"] == "u"
        p, m = panel(svc, u, "calc", "B9")
        assert m["R15"]["an"] == "Bileşik" and m["R12"]["ao"] == "Basit · R15" and "hangisini yazarsanız" in p["note"]
        p, m = panel(svc, u, "calc", "B23")
        assert p["note"].startswith("Tersi (hareketten vol)") and "İki yönlü: Volatilite, Implied Move" in p["note"]
        assert all(m["O%d" % r]["i"] == "u" for r in range(39, 44)) and not any("an" in m["O%d" % r] for r in range(39, 44))
        p, m = panel(svc, u, "calc", "B36", True)
        assert m["AS57"]["i"] == "u" and m["AS57"]["m"] == 1 and m["AS1"]["t"] == "Yıllık getiriden forward (yazılan)"
        mine = {x["ref"]: x for x in svc.my_inputs(u)["inputs"] if x["ref"].startswith(CALC)}
        assert mine[CALC + "!O57"]["store"] == CALC + "!AS57" and mine[CALC + "!O57"]["value"] == 51.0
    finally:
        svc.reset_inputs(u, "tto")


def test_a_calculator_in_a_temporary_copy(svc):
    """Implied Move in a temporary copy: a breakeven typed there is the copy's (its store the copy's own, the others the
    copy's empty values), the table keeps its own typed vol; Delete in the copy follows the table again.  Every member
    has a store, so nothing is refused in a copy."""
    u = svc.login("hy kopya")["user"]
    try:
        put(svc, u, {"O39": "21"})
        cid = svc.copy_action(u, "open", {"view": "calc", "panel": "B23"})["copy"]["id"]

        def copy_put(cells):
            return svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": CALC + "!" + k, "value": v} for k, v in cells.items()]})

        def copy_cell(ref):
            def run():
                cp = svc.copies.find(u, cid)
                return svc.copies.calc(u, cp).value(CALC + "!" + ref)
            return svc.et.call(run)

        assert copy_cell("O39") == 0.21                                   # (it starts with the table's typed values)
        res = copy_put({"O41": "43"})
        assert res["errors"] == [] and copy_cell("O41") == 43.0
        spot = cell(svc, CALC + "!O36", u)
        assert copy_cell("O39") == pytest.approx((43 / spot - 1) / 0.5, rel=1e-12)
        assert cell(svc, CALC + "!O39", u) == 0.21 and stored(svc, u) == {"AP39": 0.21}       # the table's own
        own = next(c for c in svc.copies.items(u) if c.id == cid).values
        assert own[CALC + "!AP41"] == 43.0 and own.get(CALC + "!AP39", "gone") is None
        res = copy_put({"O40": ""})                                       # Delete in the copy: the table's again
        assert res["applied"] == 1 and copy_cell("O39") == 0.21
        svc.copy_action(u, "close", {"copy": cid})
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- DV01's scenario P&L
def test_dv01_scenario_pnl_from_the_shock_and_back(svc):
    """DV01 Risk's scenario P&L: each shock (bp, in place - the input it was) gives its P&L as before; a P&L typed gives
    the shock that makes it (the block's own formula solved); the last typed wins per row; a column of P&Ls pasted."""
    u = svc.login("hy dv01")["user"]
    try:
        position = {"DV01_RISK!C%d" % r: str(1000 * (r - 5) * (-1) ** r) for r in range(6, 26)}
        res = svc.set_inputs(u, "tto", [{"ref": k, "value": v} for k, v in position.items()])
        assert res["errors"] == []
        put(svc, u, {"E69": "1", "E70": "1", "E71": "1"}, "DV01_RISK")
        per = got(svc, u, ["C69", "C70", "C71"], "DV01_RISK")                 # the P&L of 1 bp, row by row
        assert all(isinstance(x, float) and x != 0 for x in per.values())
        for pnl, shock, rows in (("C69", "E69", 69), ("C70", "E70", 70), ("C71", "E71", 71)):
            put(svc, u, {pnl: -2500000}, "DV01_RISK")
            assert cell(svc, "DV01_RISK!" + pnl, u) == -2500000.0
            assert cell(svc, "DV01_RISK!" + shock, u) == pytest.approx(-2500000 / per[pnl], rel=1e-12)
            assert "E%d" % rows not in stored(svc, u, "DV01_RISK") and stored(svc, u, "DV01_RISK")["G%d" % rows] == -2500000.0
            back = cell(svc, "DV01_RISK!" + shock, u)
            put(svc, u, {shock: back}, "DV01_RISK")                           # the shock found, typed: the same P&L
            assert cell(svc, "DV01_RISK!" + pnl, u) == pytest.approx(-2500000, rel=1e-9)
            assert "G%d" % rows not in stored(svc, u, "DV01_RISK")
        put(svc, u, {"E69": "", "E70": "", "E71": ""}, "DV01_RISK")
        assert got(svc, u, ["E69", "E70", "E71"], "DV01_RISK") == {"E69": 25.0, "E70": 10.0, "E71": 10.0}
        res = svc.paste(u, "tto", "DV01_RISK!C69", "100000\n-200000\n300000")
        assert res["errors"] == [] and {k: v for k, v in stored(svc, u, "DV01_RISK").items() if k.startswith("G")} == {
            "G69": 100000.0, "G70": -200000.0, "G71": 300000.0}
        assert cell(svc, "DV01_RISK!E71", u) == pytest.approx(300000 / per["C71"], rel=1e-12)
        _, m = panel(svc, u, "dv01", "B11")
        assert m["C71"]["an"] == "Şok (bp)" and m["E71"]["ao"] == "P&L (TL) · C71" and m["E71"]["i"] == "u"
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the workbooks
def test_a_calculator_the_workbook_changed_is_left_out_by_itself():
    """Each calculator checks the block its formulas solve: one written otherwise (or a store's cell taken) leaves that
    calculator as the workbook has it - the others stay two-way."""
    path = os.path.join(ROOT, "models", "tto.json.gz")
    tto = Model.load(path)
    ex.SheetBuilder(tto, CALC).patch("R39", "=((1/R38)-1)/((R37-R36)/360)")              # DF to Rate on 360 days
    ex.SheetBuilder(tto, CALC).set("AT65", 1.0)                                             # a store's cell taken
    out = ex.apply("tto", tto)
    assert out == ["DF to Rate iki yönlü: Calculators!R39 beklenen formül değil (((1/R38)-1)/((R37-R36)/R41) yok)",
                   "İki fiyat arası yıllık getiri iki yönlü: Calculators!AT65 boş değil"]
    assert ex.formula_of(tto, CALC, "R39") == "((1/R38)-1)/((R37-R36)/360)" and parse(tto, "R38") == 0.706695
    assert ex.formula_of(tto, CALC, "O40").startswith("IF(ISBLANK($AP$40),")


def parse(model, addr):
    from tto.xl.model import parse_a1
    return model.sheet(CALC).consts.get(parse_a1(addr))
