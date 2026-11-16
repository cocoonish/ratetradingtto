"""Temporary copies of a calculator table (``tto/copies.py``): a copy has inputs of its own, evaluated in a layer of the
engine on top of its user's calculation (``tto/xl/engine.py``, ``LayerCalc``).

The first part checks the engine's layers on tiny workbooks; the second the copies of the dashboard's real tables."""
import json
import random
import re

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell, make_service
from helpers import mini_engine
from tto import copies as cps
from tto.marketdata.base import Provider, bdp_key
from tto.server import create_app
from tto.service import ServiceError
from tto.xl.engine import LayerCalc
from tto.xl.errors import E_NA
from tto.xl.values import XlArray


# ---------------------------------------------------------------------------------------------- the engine's layers
def chain():
    return mini_engine({"A1": 10, "A2": 5, "B1": "=A1*2", "B2": "=A2+1", "C1": "=B1+B2", "D1": "=C1*10",
                        "E1": "=TODAY()", "F1": '=IF(A1>50,"büyük","küçük")'})


def test_a_layer_changes_only_its_own_results():
    """A layer's inputs (a copy's) change its own values - not its user's, not everybody's, not another user's or another
    layer's; the cells it did not type are its user's."""
    eng = chain()
    a1, a2 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2"))
    eng.declare_inputs([a1, a2])
    ali = eng.set_user_inputs("ali", {a2: 0.0})
    veli = eng.set_user_inputs("veli", {a1: 3.0})
    assert ali.value("S!D1") == 210.0 and veli.value("S!D1") == 120.0 and eng.shared.value("S!D1") == 260.0
    one = eng.layer(("ali", 1), ali, {a1: 1.0})
    two = eng.layer(("ali", 2), ali, {a1: 100.0})
    assert isinstance(one, LayerCalc) and one.parent is ali
    assert one.value("S!D1") == 30.0                       # (1*2 + 0+1) * 10: its own A1, ali's A2
    assert two.value("S!D1") == 2010.0 and two.value("S!F1") == "büyük"
    assert one.value("S!F1") == "küçük"
    # nobody else moved
    assert ali.value("S!D1") == 210.0 and veli.value("S!D1") == 120.0 and eng.shared.value("S!D1") == 260.0
    assert eng.shared.value("S!F1") == "küçük" and ali.value("S!B1") == 20.0
    # a layer's input changed again: that layer only
    eng.layer(("ali", 1), ali, {a1: 2.0})
    assert one.value("S!D1") == 50.0 and two.value("S!D1") == 2010.0 and ali.value("S!D1") == 210.0
    # its inputs gone: its user's view again
    eng.layer(("ali", 1), ali, {})
    assert one.value("S!D1") == 210.0


def test_a_layer_follows_what_changes_below_it():
    """What its user types, a shared input, the clock: reach the layer - except the cells it typed itself."""
    eng = chain()
    a1, a2 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2"))
    eng.declare_inputs([a1, a2])
    ali = eng.set_user_inputs("ali", {a2: 0.0})
    cp = eng.layer(("ali", 1), ali, {a1: 1.0})
    assert cp.value("S!D1") == 30.0 and cp.value("S!E1") == 46329.0
    eng.set_user_inputs("ali", {a2: 4.0})                   # the user's own input: the layer reads it
    assert cp.value("S!D1") == 70.0 and ali.value("S!D1") == 250.0
    eng.set_user_inputs("ali", {a2: 4.0, a1: 50.0})         # ... but not the one the layer typed itself
    assert cp.value("S!D1") == 70.0 and ali.value("S!D1") == 1050.0
    eng.set_inputs({a2: 9.0, a1: 7.0})                      # everybody's: under both of them
    assert cp.value("S!D1") == 70.0 and ali.value("S!D1") == 1050.0 and eng.shared.value("S!D1") == 240.0
    eng.set_user_inputs("ali", {})
    assert cp.value("S!D1") == 120.0 and ali.value("S!D1") == 240.0        # (1*2 + 9+1) * 10
    eng.clock.today = lambda: 46330.0
    eng.clock_tick()
    assert cp.value("S!E1") == 46330.0
    # a layer over the shared pool (a user without inputs of their own) follows the shared inputs the same way
    top = eng.layer(("zeynep", 1), eng.shared, {a2: 0.0})
    assert top.value("S!D1") == 150.0
    eng.set_inputs({a1: 1.0})
    assert top.value("S!D1") == 30.0 and eng.shared.value("S!D1") == 120.0


def test_a_layer_evaluates_only_what_follows_its_own_inputs():
    """The cost of a copy: asked for one cell, a layer evaluates that cell and what it reads that depends on the
    layer's own inputs - what its user computed already is read, and what it computes for no input of its own is kept
    where it belongs (its user's, or everybody's), so it is never computed twice."""
    cells = {"A1": 1, "A2": 2}
    cells.update({"B%d" % i: "=B%d+A2" % (i - 1) if i > 1 else "=A2*2" for i in range(1, 31)})      # 30 cells on A2
    cells.update({"C1": "=A1+B30", "C2": "=C1*2", "C3": "=B30/2"})
    eng = mini_engine(cells)
    a1, a2 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2"))
    eng.declare_inputs([a1, a2])
    ali = eng.set_user_inputs("ali", {a2: 3.0})
    assert ali.value("S!C2") == 2 * (1 + 3 * 31) and ali.value("S!C3") == 3 * 31 / 2
    shared_evals, ali_evals = eng.shared.evals, ali.evals
    cp = eng.layer(("ali", 1), ali, {a1: 5.0})
    assert cp.value("S!C2") == 2 * (5 + 3 * 31) and cp.value("S!C3") == 3 * 31 / 2
    assert cp.evals == 2                                     # C1 and C2 only: B1..B30 and C3 are ali's
    assert eng.shared.evals == shared_evals and ali.evals == ali_evals
    own = {(si, rc) for si, m in enumerate(cp.memo) for rc in m}
    assert own == {eng.model.cell_ref("S!%s" % a) for a in ("A1", "C1", "C2")}       # its input and what follows it
    # computed first by the layer, a value of no input of its own goes where it belongs: computed once
    veli = eng.set_user_inputs("veli", {a2: 1.0})
    top = eng.layer(("veli", 1), veli, {a1: 9.0})
    assert top.value("S!C2") == 2 * (9 + 31)
    assert veli.evals == 0 and veli.value("S!B30") == 31.0 and veli.evals == 0       # B1..B30 were kept as veli's
    assert eng.shared.value("S!B30") == 62.0


def test_a_layer_typed_cell_of_a_group_keeps_the_others_of_its_user():
    """Inputs of a group share one dependency bit: a layer that types one of them still sees the others as its user
    typed them (and everybody's where its user typed nothing)."""
    eng = mini_engine({"A1": 1, "A2": 2, "A3": 3, "B1": "=SUM(A1:A3)", "C1": "=A1*10", "D1": "=A2*10"})
    cells = [eng.model.cell_ref("S!A%d" % i) for i in (1, 2, 3)]
    eng.declare_inputs(cells, group="table")
    ali = eng.set_user_inputs("ali", {cells[1]: 20.0})
    cp = eng.layer(("ali", 1), ali, {cells[2]: 30.0})
    assert cp.value("S!A1") == 1.0 and cp.value("S!A2") == 20.0 and cp.value("S!A3") == 30.0
    assert cp.value("S!B1") == 51.0 and cp.value("S!C1") == 10.0 and cp.value("S!D1") == 200.0
    assert ali.value("S!B1") == 24.0 and eng.shared.value("S!B1") == 6.0
    eng.set_inputs({cells[0]: 7.0})
    assert cp.value("S!B1") == 57.0 and ali.value("S!B1") == 30.0


class _Bloomberg(Provider):
    """Answers BDP / BDH from a table and keeps every key asked."""

    def __init__(self):
        self.asked = []
        self.calcs = []
        self.quotes = {}

    def call(self, calc, name, si, r, c, args):
        if name != "BINTERPOL":
            self.calcs.append(calc)
        return Provider.call(self, calc, name, si, r, c, args)

    def get_bdp(self, key):
        self.asked.append(key)
        return self.quotes.get(key[1], E_NA)

    def get_bdh(self, key):
        self.asked.append(key)
        return XlArray([[float(i), 100.0 + i] for i in range(4)])


def test_a_layer_never_asks_bloomberg():
    """A cell that asks Bloomberg is its user's in a layer: evaluated once, below, with the user's arguments; a layer's
    own value of a cell that goes into the request does not reach the request (a copy keeps such inputs read-only).
    The cells of a Bloomberg array are read from below too (they never leave a wrong value in the shared pool);
    BINTERPOL is a calculation of its own and follows the layer."""
    eng = mini_engine({"A1": "XAU Curncy", "A2": 2, "A3": 1.5, "B1": '=BDP(A1,"PX_LAST")', "C1": "=B1*A2",
                       "D1": '=BDH(A1,"PX_LAST","20260101","20260105")', "F1": "=E2*A2",
                       "G1": 1, "G2": 2, "H1": 10, "H2": 20, "I1": "=BINTERPOL(G1:G2,H1:H2,A3)*A2"}, array=("D1",))
    prov = _Bloomberg()
    prov.quotes = {"XAU Curncy": 4000.0, "XAG Curncy": 50.0}
    eng.provider = prov
    si, d1 = eng.model.cell_ref("S!D1")
    eng.register_spill(si, d1, 4, 2)
    a1, a2, a3 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2", "A3"))
    eng.declare_inputs([a1, a2, a3])
    ali = eng.set_user_inputs("ali", {a2: 3.0})
    assert ali.value("S!C1") == 12000.0 and ali.value("S!F1") == 3.0 * 101.0
    asked = list(prov.asked)
    cp = eng.layer(("ali", 1), ali, {a2: 10.0, a3: 1.25})
    assert cp.value("S!C1") == 40000.0 and cp.value("S!F1") == 1010.0 and cp.value("S!E2") == 101.0
    assert cp.value("S!I1") == 12.5 * 10.0                    # BINTERPOL at the layer's x: (1.25 -> 12.5) * 10
    assert prov.asked == asked and not any(isinstance(c, LayerCalc) for c in prov.calcs)
    # the cell that goes into the request typed in the layer anyway: still no request with it
    cp = eng.layer(("ali", 1), ali, {a1: "XAG Curncy", a2: 10.0})
    assert cp.value("S!C1") == 40000.0 and cp.value("S!B1") == 4000.0
    assert ("BDP", "XAG Curncy", "PX_LAST", ()) not in prov.asked and prov.asked == asked
    assert cp.inherited > 0 and cp.refused == 0
    # asked first in a layer: evaluated below, once, with the user's arguments
    veli = eng.set_user_inputs("veli", {a2: 1.0})
    top = eng.layer(("veli", 1), veli, {a2: 5.0})
    eng.set_inputs({a1: "XAG Curncy"})                        # (the desk's ticker changed: asked again)
    before = len(prov.asked)
    assert top.value("S!C1") == 250.0 and top.value("S!F1") == 505.0
    assert len(prov.asked) - before == 2 and not any(isinstance(c, LayerCalc) for c in prov.calcs)
    assert veli.value("S!C1") == 50.0 and len(prov.asked) - before == 2
    # the array's cells in the shared pool are what the array wrote (none left empty by a layer's read)
    assert eng.shared.value("S!E2") == 101.0 and eng.shared.value("S!E4") == 103.0


def test_dropping_a_user_drops_their_layers():
    eng = chain()
    a1, a2 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2"))
    eng.declare_inputs([a1, a2])
    ali = eng.set_user_inputs("ali", {a2: 0.0})
    eng.layer(("ali", 1), ali, {a1: 1.0})
    eng.layer(("zeynep", 1), eng.shared, {a1: 2.0})
    assert len(ali.children) == 1 and len(eng.shared.children) == 1
    eng.drop_user("ali")
    assert list(eng.layers) == [("zeynep", 1)]
    # made again over a new calculation of the user: the old one is not read
    ali2 = eng.set_user_inputs("ali", {a2: 1.0})
    cp = eng.layer(("ali", 1), ali2, {a1: 1.0})
    assert cp.parent is ali2 and cp.value("S!D1") == 40.0
    old = eng.layers[("zeynep", 1)]
    again = eng.layer(("zeynep", 1), ali2, {a1: 2.0})         # (another parent: another calculation)
    assert again is not old and old not in eng.shared.children and again.value("S!D1") == 60.0
    eng.drop_layer(("zeynep", 1))
    assert again not in ali2.children and ("zeynep", 1) not in eng.layers


def _random_book(rnd):
    """Inputs A1:A8 (two of them grouped), constants C1:C4, and 40 formulas reading earlier cells and ranges."""
    cells = {"A%d" % i: float(rnd.randint(1, 9)) for i in range(1, 9)}
    cells.update({"C%d" % i: float(rnd.randint(1, 5)) for i in range(1, 5)})
    names = ["A%d" % i for i in range(1, 9)] + ["C%d" % i for i in range(1, 5)]
    for i in range(1, 41):
        a, b = rnd.choice(names), rnd.choice(names)
        kind = rnd.random()
        if kind < 0.3:
            f = "=%s+%s*2" % (a, b)
        elif kind < 0.5:
            f = "=IF(%s>%s,%s,%s-1)" % (a, b, a, b)
        elif kind < 0.7 and i > 3:
            f = "=SUM(B%d:B%d)+%s" % (max(1, i - 3), i - 1, a)
        elif kind < 0.85:
            f = "=%s/(1+ABS(%s))" % (a, b)
        else:
            f = "=TODAY()-%s" % a
        cells["B%d" % i] = f
        names.append("B%d" % i)
    return cells


def test_layers_match_a_calculation_from_scratch_at_random():
    """Shared values, users' and layers' own values, values typed over formulas and constants later and the clock, in
    random order: after every step every layer's every cell is what a fresh calculation of its user's inputs with its own
    over them gives, and every user's and the shared pool's cells are what they would be without any layer (nothing a
    layer computed leaked into them)."""
    for seed in range(8):
        rnd = random.Random(seed)
        cells = _random_book(rnd)
        eng = mini_engine(cells)
        ref = eng.model.cell_ref
        inputs = [ref("S!A%d" % i) for i in range(1, 9)]
        eng.declare_inputs(inputs[:6])
        eng.declare_inputs(inputs[6:], group="g")
        declared = list(inputs)
        shared_vals = {}
        users = {"ali": {}, "veli": {}, "zeynep": {}}
        layers = {("ali", 1): {}, ("ali", 2): {}, ("veli", 1): {}, ("zeynep", 1): {}}
        today = [46329.0]
        formula_cells = ["B%d" % i for i in range(1, 41)]

        def place(key):
            # as the service does: on the user's calculation, or on everybody's when the user typed nothing
            name = key[0]
            parent = eng.set_user_inputs(name, users[name]) if users[name] else eng.shared
            return eng.layer(key, parent, layers[key])

        for key in layers:
            place(key)
        for step in range(70):
            op = rnd.random()
            if op < 0.18:
                c = rnd.choice(declared)
                shared_vals[c] = float(rnd.randint(0, 20))
                eng.set_inputs({c: shared_vals[c]})
            elif op < 0.25 and shared_vals:
                c = rnd.choice(list(shared_vals))
                del shared_vals[c]
                eng.clear_inputs([c])
            elif op < 0.45:
                name = rnd.choice(list(users))
                ov = dict(users[name])
                c = rnd.choice(declared)
                if c in ov and rnd.random() < 0.4:
                    del ov[c]
                else:
                    ov[c] = float(rnd.randint(-5, 30))
                users[name] = ov
                eng.set_user_inputs(name, ov)
            elif op < 0.7:
                key = rnd.choice(list(layers))
                ov = dict(layers[key])
                c = rnd.choice(declared)
                if c in ov and rnd.random() < 0.4:
                    del ov[c]
                else:
                    ov[c] = float(rnd.randint(-5, 30))
                layers[key] = ov
            elif op < 0.8:
                c = ref("S!" + rnd.choice(formula_cells + ["C1", "C2", "C3", "C4"]))
                if c not in declared:
                    eng.declare_inputs([c], group="adhoc")
                    declared.append(c)
            elif op < 0.9:
                today[0] += 1
                eng.clock.today = (lambda t: (lambda: t))(today[0])
                eng.clock_tick()
            calcs = {key: place(key) for key in layers}
            # read a random part, layers first (what they compute for no input of their own goes below them)
            for key, calc in calcs.items():
                for a in rnd.sample(formula_cells, 12):
                    calc.value("S!" + a)
            for calc in [eng.shared] + [eng.user(n) for n in users]:
                for a in rnd.sample(formula_cells, 8):
                    calc.value("S!" + a)
            fresh = mini_engine(cells, today=today[0])
            fresh.declare_inputs(inputs[:6])
            fresh.declare_inputs(inputs[6:], group="g")
            fresh.declare_inputs([c for c in declared if c not in inputs], group="adhoc")
            fresh.set_inputs(dict(shared_vals))
            for name in [None] + list(users):
                mine = eng.shared if name is None else eng.user(name)
                theirs = fresh.shared if name is None else fresh.set_user_inputs(name, users[name])
                for a in formula_cells:
                    assert mine.value("S!" + a) == theirs.value("S!" + a), (seed, step, name, a)
            for key, calc in calcs.items():
                theirs = fresh.set_user_inputs("%s/%s" % key, {**users[key[0]], **layers[key]})
                for a in formula_cells:
                    assert calc.value("S!" + a) == theirs.value("S!" + a), (seed, step, key, a)


# ---------------------------------------------------------------------------------------------- the dashboard's copies
#: the calculators that may be copied: page -> tables (``"copyable": true`` in tto/views)
COPYABLE = {
    "masa": {"B22", "B9", "B10", "B17"},
    "forward": {"B7", "B8", "B9", "B10", "B11", "B13", "B18", "B21", "B34"},
    "viop": {"B33", "XAU4"},
    "calc": {"B5", "B6", "B8", "B9", "B23", "B24", "B26", "B27", "B28", "B31", "B32", "B33"},
}


def login(svc, name):
    return svc.login(name)["user"]


def act(svc, user, what, **data):
    return svc.copy_action(user, what, data)


def entry(res, pid):
    return next(p for p in res["panels"] if p["id"] == pid)


def at(ent, ref):
    """The cell of a table's entry as the browser draws it (its own table, or one of its strips of inputs)."""
    sheet, _, a = ref.partition("!")
    m = re.match(r"([A-Z]+)(\d+)$", a)
    for d in [ent["data"]] + [x["data"] for x in ent.get("lead") or []]:
        if d and d.get("sheet") == sheet and m.group(1) in d["c"] and int(m.group(2)) in d["r"]:
            return d["rows"][d["r"].index(int(m.group(2)))][d["c"].index(m.group(1))]
    raise KeyError(ref)


def copy_value(svc, user, cid, ref):
    """Raw value of a cell as a temporary copy of the user's has it."""
    def run():
        cp = svc.copies.find(user, cid)
        return svc.copies.calc(user, cp).value(ref)
    return svc.et.call(run)


def close_all(svc, user):
    for c in svc.copies.items(user):
        act(svc, user, "close", copy=c.id)


def test_the_copyable_tables_are_calculators_whose_inputs_are_personal(module_service):
    """The tables marked ``"copyable": true`` are the calculators (Masa's broken-date calculator, TARİH ARASI FAİZ /
    FORWARD, the VİOP target; Forward's and Hesaplayıcılar' calculators; VİOP's gold calculator): every input of each is
    personal, none feeds a Bloomberg request, none lies in a row that moves (a meeting's row, a holiday list) - what a
    copy keeps by cell stays the same cell's.  A table with a desk input, a hidden one, one without inputs is refused."""
    from tto import meetings as mt
    from tto.views import __doc__ as views_doc
    svc = module_service
    cp = svc.copies
    assert cp.problems == {}
    got = {}
    for v, p in cp.tables:
        got.setdefault(v, set()).add(p)
    assert got == COPYABLE
    for (vid, pid), t in cp.tables.items():
        book = t.book
        assert t.cells and all(book.inputs[c].scope == "user" for c in t.cells), (vid, pid)
        ro = svc.et.call(cp.readonly, t)
        assert ro == {}, (vid, pid, ro)                         # (no input of these feeds a request)
        for si, rc in t.cells:
            assert mt.place(book, si, rc) is None and not svc._holiday_cell(book, si, rc), (vid, pid, book.ref(si, rc))
    # TARİH ARASI FORWARD is computed from the dates in the row above it: they come with its copy
    assert [lp["id"] for lp in cp.tables[("masa", "B10")].leads] == ["B10D"]
    masa = svc.view_index["masa"]
    by_id = {p["id"]: p for p in masa["panels"]}
    assert cp._check(masa, dict(by_id["B20"], copyable=True)) == "ortak girdisi var (MASA!C156)"     # the desk's tickers
    assert cp._check(masa, dict(by_id["B24"], copyable=True)) == "bir sayfa aralığının görünen tablosu değil"   # hidden
    assert cp._check(masa, dict(by_id["B3"], copyable=True)) == "kişisel girdisi yok"
    assert cp._check(masa, dict(by_id["B10"], copy_with=["XX"])) == "copy_with: XX bu sayfanın tablosu değil"
    assert '"copyable": true' in views_doc and '"copy_with"' in views_doc
    # a copy's panel id is its table's and its own
    assert cps.copy_pid("B22.k0123abcd") == ("B22", "k0123abcd") and cps.copy_pid("B22") is None and cps.copy_pid("x.y") is None


def test_a_copy_has_inputs_of_its_own(module_service):
    """Typed into a copy, a value changes that copy's numbers only - not the table's, not the user's other copy, not
    another user's.  The copy is right under its table (its tab), "… · kopya 2" / "kopya 3"; it starts with what the user
    typed in the table and is apart from it from then on; a cell typed in neither follows the table."""
    svc = module_service
    u, other = login(svc, "Kopya Sahibi"), login(svc, "Kopya Komşu")
    try:
        assert svc.set_inputs(u, "tto", [{"ref": "MASA!J171", "value": "45"}])["errors"] == []
        res = svc.view(u, "masa")
        assert entry(res, "B22").get("copyable") is True and "copyable" not in entry(res, "B3")
        e171, f173 = cell(svc, "MASA!E171", u), cell(svc, "MASA!F173", u)
        one = act(svc, u, "open", view="masa", panel="B22")["copy"]
        two = act(svc, u, "open", view="masa", panel="B22")["copy"]
        assert (one["n"], two["n"]) == (2, 3) and one["pid"] == "B22." + one["id"]
        assert svc.store.get("copies." + u)["items"][0]["values"] == {"MASA!J171": 45.0}       # (what the table has typed)
        put = act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!C171", "value": "15.06.2027"}])
        assert put["applied"] == 1 and put["errors"] == []
        res = svc.view(u, "masa")
        fwd = next(s for s in res["sections"] if s["id"] == "fwd")["panels"]
        assert fwd[fwd.index("B22"):fwd.index("B22") + 3] == ["B22", one["pid"], two["pid"]]
        c1, c2, orig = entry(res, one["pid"]), entry(res, two["pid"]), entry(res, "B22")
        assert c1["title"].endswith("· kopya 2") and c2["title"].endswith("· kopya 3")
        assert c1["copy"] == {"id": one["id"], "of": "B22", "n": 2} and "copyable" not in c1
        assert at(c1, "MASA!C171")["t"] == "15.06.2027" and at(c1, "MASA!C171")["m"] == 1 and at(c1, "MASA!C171")["i"] == "u"
        assert copy_value(svc, u, one["id"], "MASA!E171") != e171 and copy_value(svc, u, one["id"], "MASA!F173") != f173
        assert at(c1, "MASA!E171")["v"] == copy_value(svc, u, one["id"], "MASA!E171")
        # the table, the other copy, the other user: as they were
        assert cell(svc, "MASA!E171", u) == e171 and cell(svc, "MASA!F173", u) == f173
        assert at(orig, "MASA!E171")["v"] == e171 and at(orig, "MASA!C171").get("m") is None
        assert copy_value(svc, u, two["id"], "MASA!E171") == e171 and at(c2, "MASA!E171")["v"] == e171
        assert cell(svc, "MASA!E171", other) == e171 and not any("." in p["id"] for p in svc.view(other, "masa")["panels"])
        # apart from the table: the table's value changes, the copy keeps its own; a cell typed in neither follows it
        assert svc.set_inputs(u, "tto", [{"ref": "MASA!J171", "value": "50"}, {"ref": "MASA!L171", "value": "33"}])["errors"] == []
        assert copy_value(svc, u, one["id"], "MASA!J171") == 45.0 and cell(svc, "MASA!J171", u) == 50.0
        assert copy_value(svc, u, one["id"], "MASA!N171") == 33.0 == cell(svc, "MASA!N171", u)        # (the spot follows)
        # Delete over a cell with a formula default: the table's value again; over a plain one: the copy's own blank
        act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!C171", "value": ""}, {"ref": "MASA!L171", "value": ""}])
        assert copy_value(svc, u, one["id"], "MASA!C171") == cell(svc, "MASA!C171", u)
        assert copy_value(svc, u, one["id"], "MASA!L171") is None and copy_value(svc, u, one["id"], "MASA!N171") != 33.0
        assert svc.copies.find(u, one["id"]).values == {"MASA!J171": 45.0, "MASA!L171": None}
        # the copy's own reset (a cell's, then all): the table's values again
        assert act(svc, u, "reset", copy=one["id"], refs=["MASA!L171"])["reset"] == 1
        assert copy_value(svc, u, one["id"], "MASA!N171") == 33.0
        assert act(svc, u, "reset", copy=one["id"])["reset"] == 1
        assert copy_value(svc, u, one["id"], "MASA!J171") == 50.0
    finally:
        close_all(svc, u)
        svc.reset_inputs(u, "tto")


def test_a_copy_with_its_strip_of_inputs(module_service):
    """TARİH ARASI FORWARD's dates and spread stand in the row above it (B10D): its copy shows that row too, as inputs
    of the copy - the copy's forward follows its own dates, the table's its own."""
    svc = module_service
    u = login(svc, "Kopya Şerit")
    cols = ["P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z", "AA", "AB"]
    try:
        one = act(svc, u, "open", view="masa", panel="B10")["copy"]
        before = {ref: cell(svc, ref, u) for ref in ("MASA!%s%d" % (c, r) for c in cols for r in range(59, 71))}
        act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!E60", "value": "15.06.2027"}])
        ent = entry(svc.view(u, "masa"), one["pid"])
        assert ent["lead"][0]["title"] and at(ent, "MASA!E60")["t"] == "15.06.2027" and at(ent, "MASA!E60")["m"] == 1
        assert ent["lead"][0]["data"]["r"] == [60] and set(ent["data"]["c"]) <= set(cols)
        changed = [ref for ref in before if copy_value(svc, u, one["id"], ref) != before[ref]]
        assert changed and all(cell(svc, ref, u) == v for ref, v in before.items())
        assert cell(svc, "MASA!E60", u) != copy_value(svc, u, one["id"], "MASA!E60")
    finally:
        close_all(svc, u)


def test_what_is_refused_in_a_copy(module_service):
    """Not copyable: a table with a desk input, one without inputs, an unknown one, a copy of a copy.  In a copy: a formula
    (its inputs are values; the reason says so), a cell that is no input of its table ("Elle değer" too), an unknown
    copy."""
    svc = module_service
    u = login(svc, "Kopya Ret")
    try:
        for view, panel in (("masa", "B20"), ("masa", "B3"), ("masa", "nope"), ("nope", "B22"), ("masa", "B22.k0123abcd")):
            with pytest.raises(ServiceError) as exc:
                act(svc, u, "open", view=view, panel=panel)
            assert exc.value.status == 400 and str(exc.value) == cps.NOT_COPYABLE
        one = act(svc, u, "open", view="masa", panel="B22")["copy"]
        got = act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!J171", "value": "=1+1"},
                                                             {"ref": "MASA!F173", "value": "1"}, {"ref": "MASA!S171", "value": "x"},
                                                             {"ref": "YOK!A1", "value": "1"}])
        assert got["applied"] == 0 and len(got["errors"]) == 4
        assert got["errors"][0] == "MASA!J171: " + cps.FORMULA and got["errors"][1] == "MASA!F173: " + cps.NOT_HERE
        assert got["errors"][2] == "MASA!S171: " + cps.NOT_HERE and "hücre bulunamadı" in got["errors"][3]
        # a block pasted (lenient): the cells that are no input of the copy are skipped and counted
        got = act(svc, u, "inputs", copy=one["id"], lenient=True, items=[{"ref": "MASA!J171", "value": "41"}, {"ref": "MASA!K171", "value": "x"}])
        assert got["applied"] == 1 and got["errors"] == [] and got["skipped"] == 1
        for what in ("inputs", "reset", "close"):
            with pytest.raises(ServiceError) as exc:
                act(svc, u, what, copy="k0123abcd", items=[])
            assert exc.value.status == 404 and str(exc.value) == cps.GONE
        with pytest.raises(ServiceError):
            act(svc, u, "nope")
    finally:
        close_all(svc, u)


def test_the_caps(module_service):
    """At most 5 copies of a table and 20 in all, per user; a number freed is taken again."""
    svc = module_service
    u = login(svc, "Kopya Sınır")
    try:
        ns = [act(svc, u, "open", view="masa", panel="B22")["copy"]["n"] for _ in range(cps.MAX_PER_TABLE)]
        assert ns == [2, 3, 4, 5, 6]
        with pytest.raises(ServiceError) as exc:
            act(svc, u, "open", view="masa", panel="B22")
        assert str(exc.value) == cps.TOO_MANY_TABLE % 5
        third = next(c for c in svc.copies.items(u) if c.n == 3)
        act(svc, u, "close", copy=third.id)
        assert act(svc, u, "open", view="masa", panel="B22")["copy"]["n"] == 3
        tables = [(v, p) for v, p in sorted(svc.copies.tables) if (v, p) != ("masa", "B22")]
        k = 0
        while len(svc.copies.items(u)) < cps.MAX_PER_USER:
            act(svc, u, "open", view=tables[k][0], panel=tables[k][1])
            k += 1
        with pytest.raises(ServiceError) as exc:
            act(svc, u, "open", view=tables[k][0], panel=tables[k][1])
        assert str(exc.value) == cps.TOO_MANY_USER % 20
        assert len(svc.copies_of(u)["copies"]) == 20 and svc.copies_of(u)["max_per_table"] == 5
    finally:
        close_all(svc, u)


def test_live_data_and_the_desk_reach_a_copy(module_service, monkeypatch):
    """What moves under a copy reaches it as it reaches its table: a market quote (the gold spot - the gold calculator's
    XAUUSD spot follows the market where the copy has no value of its own), a desk input (the manual gold spot), a value
    the user types in the table; the copy's own values stay.  (A page of the user's own follows the market at most every
    few seconds, the table and its copies alike: not waited for here.)"""
    svc = module_service
    monkeypatch.setattr(svc.settings, "private_refresh", 0.0)
    u, desk = login(svc, "Kopya Canlı"), login(svc, "Kopya Masa")
    keys = [bdp_key("XAU Curncy", "BID"), bdp_key("XAU Curncy", "ASK")]
    try:
        gold = act(svc, u, "open", view="viop", panel="XAU4")["copy"]
        act(svc, u, "inputs", copy=gold["id"], items=[{"ref": "EK_XAU!B46", "value": "41"}])          # its own TRY %
        svc.et.call(svc._apply_market, svc.provider.update({keys[0]: 3960.0, keys[1]: 3961.0}))
        before = copy_value(svc, u, gold["id"], "EK_XAU!B44")
        assert before == cell(svc, "EK_XAU!B44", u) == 3960.5
        svc.view(u, "viop")
        svc.et.call(svc._apply_market, svc.provider.update({keys[0]: 3970.0, keys[1]: 3971.0}))
        svc.bump(market=True)
        assert copy_value(svc, u, gold["id"], "EK_XAU!B44") == 3970.5 == cell(svc, "EK_XAU!B44", u)
        page = svc.view(u, "viop")
        assert at(entry(page, gold["pid"]), "EK_XAU!B44")["v"] == 3970.5 == at(entry(page, "XAU4"), "EK_XAU!B44")["v"]
        assert copy_value(svc, u, gold["id"], "EK_XAU!B46") == 41.0 != cell(svc, "EK_XAU!B46", u)
        # the desk's manual gold spot (everybody's), then a value the user types in the table (theirs)
        assert svc.set_inputs(desk, "tto", [{"ref": "EK_XAU!B5", "value": "3980"}, {"ref": "EK_XAU!C5", "value": "3981"}])["errors"] == []
        assert copy_value(svc, u, gold["id"], "EK_XAU!B44") == 3980.5 == cell(svc, "EK_XAU!B44", u)
        assert at(entry(svc.view(u, "viop"), gold["pid"]), "EK_XAU!B44")["v"] == 3980.5
        assert svc.set_inputs(u, "tto", [{"ref": "EK_XAU!B45", "value": "4,5"}])["errors"] == []
        assert copy_value(svc, u, gold["id"], "EK_XAU!B45") == 4.5 and copy_value(svc, u, gold["id"], "EK_XAU!B46") == 41.0
        assert at(entry(svc.view(u, "viop"), gold["pid"]), "EK_XAU!B45")["v"] == 4.5
    finally:
        close_all(svc, u)
        svc.reset_inputs(u, "tto")
        svc.reset_inputs(desk, "tto", ["EK_XAU!B5", "EK_XAU!C5"], shared=True)
        for k in keys:
            svc.provider.snapshot.pop(k, None)
        svc.et.call(svc._apply_market, keys)


def test_a_copy_never_asks_bloomberg(module_service, monkeypatch):
    """No request comes from a copy: its cells that ask Bloomberg are its user's - asked below, with the user's
    arguments -, whatever is typed into it.  An input that goes into a request (a value date or a ticker the workbook's
    BDP / BDH cells are computed from) is read-only in a copy: greyed with the reason, and refused if sent anyway."""
    svc = module_service
    u = login(svc, "Kopya Bloomberg")
    calls = []
    real = svc.provider.call

    def spy(calc, name, si, r, c, args):
        calls.append((type(calc).__name__, name))
        return real(calc, name, si, r, c, args)

    monkeypatch.setattr(svc.provider, "call", spy)
    book = svc.books["tto"]
    try:
        layers = []
        for view, panel, ref, value in (("masa", "B22", "MASA!C171", "15.06.2027"), ("viop", "XAU4", "EK_XAU!B40", "20.11.2026"),
                                        ("viop", "XAU4", "EK_XAU!B43", "35")):
            svc.view(u, view)
            one = act(svc, u, "open", view=view, panel=panel)["copy"]
            del calls[:]
            assert act(svc, u, "inputs", copy=one["id"], items=[{"ref": ref, "value": value}])["errors"] == []
            ent = entry(svc.view(u, view), one["pid"])
            assert at(ent, ref)["m"] == 1
            assert {name for kind, name in calls if kind == "LayerCalc"} <= {"BINTERPOL"}, calls      # (a calculation, no request)
            layers.append(book.engine.layers[(u, one["id"])])
            assert layers[-1].refused == 0
        assert layers[0].inherited > 0                  # (the broken-date calculator's Bloomberg cells: read from below)
        # a table whose inputs go into requests (Forward's value date and spot dates), copied anyway: those read-only
        fwd = svc.view_index["forward"]
        t = svc.copies._check(fwd, next(p for p in fwd["panels"] if p["id"] == "B1"))
        svc.copies.tables[("forward", "B1")] = t
        ro = svc.et.call(svc.copies.readonly, t)
        assert sorted(book.ref(*c) for c in ro) == ["Forward!D2", "Forward!I2", "Forward!K2"]
        assert all(why.startswith("bu girdi bir Bloomberg isteğine giriyor (") for why in ro.values())
        one = act(svc, u, "open", view="forward", panel="B1")["copy"]
        got = act(svc, u, "inputs", copy=one["id"], items=[{"ref": "Forward!D2", "value": "15.06.2027"}, {"ref": "Forward!F2", "value": "36"}])
        assert got["applied"] == 1 and got["errors"] == ["Forward!D2: " + ro[book.cell("Forward!D2")]]
        ent = entry(svc.view(u, "forward"), one["pid"])
        assert "i" not in at(ent, "Forward!D2") and at(ent, "Forward!D2")["ro"] == ro[book.cell("Forward!D2")]
        assert at(ent, "Forward!F2")["i"] == "u" and at(ent, "Forward!F2")["m"] == 1
        assert not any(kind == "LayerCalc" and name != "BINTERPOL" for kind, name in calls)
    finally:
        close_all(svc, u)
        svc.copies.tables.pop(("forward", "B1"), None)


def test_a_copy_evaluates_only_what_follows_its_own_inputs(module_service):
    """The cost of a copy is bounded by its table: typed into, the copy evaluates the cells of its table that follow its
    own inputs and what they read that follows them - nothing of everybody's or its user's is computed again, nothing
    of theirs is dropped, and the page's other tables are not made again."""
    svc = module_service
    u = login(svc, "Kopya Maliyet")
    book = svc.books["tto"]
    eng = book.engine
    try:
        one = act(svc, u, "open", view="masa", panel="B22")["copy"]
        first = svc.view(u, "masa")
        shared = eng.shared.evals
        layer = eng.layers[(u, one["id"])]
        evals = layer.evals
        act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!C171", "value": "15.06.2027"}])
        again = [p["id"] for p in svc.view(u, "masa", since=first["gen"])["panels"]]
        assert one["pid"] in again and "B22" not in again                 # (the copy was made again, its table was not)
        assert eng.layers[(u, one["id"])] is layer and layer.parent is eng.shared
        assert eng.shared.evals == shared                                   # nothing of everybody's computed again
        own = set(layer.overlay)
        down = svc.et.call(lambda: eng.ref_index().downstream(own) | own)
        held = {(si, rc) for si, m in enumerate(layer.memo) for rc in m}
        assert held <= down and 0 < layer.evals - evals <= len(held) < 1000    # its own cells only: a few hundred
    finally:
        close_all(svc, u)


def test_the_rest_of_the_workbook_reads_the_table_not_a_copy(module_service):
    """Calc sheets, input formulas, scenarios and "Girdilerimi sıfırla" are the table's: a calc sheet's reference reads
    the table's value; an input formula of the table is the user's and a copy follows it where it has no value of its
    own; a scenario keeps the user's inputs, never a copy's; resetting the table leaves the copy's own values."""
    svc = module_service
    u = login(svc, "Kopya Kalan")
    try:
        one = act(svc, u, "open", view="masa", panel="B22")["copy"]
        act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!C171", "value": "15.06.2027"}, {"ref": "MASA!J171", "value": "47"}])
        sheet = svc.calcsheets.save_future(u, {"sheet": "kopya", "cells": {"A1": "=MASA!E171", "A2": "=MASA!J171"}}, "tr").result()
        assert sheet["cells"]["A1"]["v"] == cell(svc, "MASA!E171", u) != copy_value(svc, u, one["id"], "MASA!E171")
        assert sheet["cells"]["A2"]["v"] == cell(svc, "MASA!J171", u) != 47.0
        # an input formula of the table: the copy follows it where it has no value of its own
        assert svc.set_inputs(u, "tto", [{"ref": "MASA!L171", "value": "=I60+30"}])["errors"] == []
        assert copy_value(svc, u, one["id"], "MASA!L171") == cell(svc, "MASA!L171", u) == cell(svc, "MASA!I60", u) + 30
        ent = entry(svc.view(u, "masa"), one["pid"])
        assert at(ent, "MASA!L171")["ff"] == "=I60+30" and "ff" not in at(ent, "MASA!J171")
        assert svc.set_inputs(u, "tto", [{"ref": "MASA!I60", "value": "-80"}])["errors"] == []
        svc.et.call(svc.formulas.settle)
        assert copy_value(svc, u, one["id"], "MASA!L171") == -50.0 == cell(svc, "MASA!L171", u)
        # a scenario: the user's inputs only
        svc.save_scenario(u, "kopyasız")
        values, formulas = svc.store.scenario(u, "kopyasız")
        assert set(values) == {("tto", "MASA!I60"), ("tto", "MASA!L171")} and formulas == {("tto", "MASA!L171"): "=I60+30"}
        # the table reset: the copy keeps its own values (46553 = 15.06.2027)
        assert svc.reset_inputs(u, "tto")["reset"] == 2
        assert copy_value(svc, u, one["id"], "MASA!J171") == 47.0 and copy_value(svc, u, one["id"], "MASA!L171") is None
        assert svc.copies.find(u, one["id"]).values == {"MASA!C171": 46553.0, "MASA!J171": 47.0}
        svc.load_scenario(u, "kopyasız")
        assert svc.copies.find(u, one["id"]).values == {"MASA!C171": 46553.0, "MASA!J171": 47.0}
        assert cell(svc, "MASA!I60", u) == -80.0
    finally:
        close_all(svc, u)
        svc.reset_inputs(u, "tto")
        svc.delete_scenario(u, "kopyasız")


def test_copies_are_kept_until_closed(tmp_path):
    """A copy stays - with its values - across page loads and a restart, on a launchpad and in the drawer as any table;
    closed (×), it is gone with its values and off the launchpads and the drawer.  An unreadable entry of the store is
    dropped, the database opens.  Over HTTP: ``/api/copies`` and ``/api/cell?copy=``."""
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Kopya Kalıcı")
        one = act(svc, u, "open", view="masa", panel="B22")["copy"]
        act(svc, u, "inputs", copy=one["id"], items=[{"ref": "MASA!C171", "value": "15.06.2027"}])
        days = copy_value(svc, u, one["id"], "MASA!E171")
        svc.set_layout(u, {"launchpads": [{"name": "Kopyalar", "items": [{"type": "table", "view": "masa", "panel": one["pid"]}]}],
                           "drawer": [{"type": "table", "view": "masa", "panel": one["pid"]}, {"type": "table", "view": "masa", "panel": "B22"}]})
        got = svc.panels(u, [{"view": "masa", "panel": one["pid"]}])["panels"]["masa/" + one["pid"]]
        assert got["entry"]["copy"]["id"] == one["id"] and at(got["entry"], "MASA!E171")["v"] == days and got["tab"] == "Forward fiyatlama"
        raw, _ = svc.export_launchpad(u, "Kopyalar")
        assert json.loads(raw)["items"][0]["panel"] == "B22"                # (a copy is its owner's: the table goes)
    finally:
        svc.stop()
    other = {"items": [{"id": "kffffffff", "view": "masa", "panel": "B3", "n": 2, "values": {}}, "bozuk",
                       {"id": "k0", "view": "masa", "panel": "B22", "n": 2}]}
    svc = make_service(tmp_path)
    try:
        svc.store.put("copies." + login(svc, "Kopya Eski"), other)
        assert svc.copies_of("kopya eski")["copies"] == [] and svc.store.get("copies.kopya eski") == {"items": []}
        assert [c["id"] for c in svc.copies_of(u)["copies"]] == [one["id"]]
        ent = entry(svc.view(u, "masa"), one["pid"])
        assert at(ent, "MASA!C171")["t"] == "15.06.2027" and at(ent, "MASA!E171")["v"] == days
        res = act(svc, u, "close", copy=one["id"])
        assert res["layout"] == 2
        layout = svc.layout(u)
        assert layout["launchpads"][0]["items"] == [] and [x["panel"] for x in layout["drawer"]] == ["B22"]
        assert svc.copies_of(u)["copies"] == [] and svc.store.get("copies." + u) == {"items": []}
        assert not any("." in p["id"] for p in svc.view(u, "masa")["panels"])
        assert svc.panels(u, [{"view": "masa", "panel": one["pid"]}])["panels"]["masa/" + one["pid"]]["missing"] is True
        assert not any(k[0] == u for k in svc.books["tto"].engine.layers)
        # over HTTP
        client = TestClient(create_app(service=svc))              # (no "with": the service stays up until stopped below)
        h = auth(svc, "Kopya Kalıcı")
        r = client.post("/api/copies/open", json={"view": "masa", "panel": "B22"}, headers=h)
        assert r.status_code == 200 and r.json()["copy"]["n"] == 2
        cid = r.json()["copy"]["id"]
        r = client.post("/api/copies/inputs", json={"copy": cid, "items": [{"ref": "MASA!C171", "value": "15.06.2027"}]}, headers=h)
        assert r.json()["applied"] == 1
        assert client.get("/api/copies", headers=h).json()["copies"][0]["values"] == 1
        info = client.get("/api/cell", params={"book": "tto", "ref": "MASA!C171", "copy": cid}, headers=h).json()
        assert info["input"]["copy"] == 2 and info["input"]["own"] is True and info["cell"]["t"] == "15.06.2027"
        assert client.get("/api/cell", params={"book": "tto", "ref": "MASA!C171"}, headers=h).json()["cell"]["t"] != "15.06.2027"
        r = client.post("/api/copies/inputs", json={"copy": cid, "items": [{"ref": "MASA!J171", "value": "=1"}]}, headers=h).json()
        assert r["errors"] == ["MASA!J171: " + cps.FORMULA]
        assert client.post("/api/copies/open", json={"view": "masa", "panel": "B20"}, headers=h).status_code == 400
        assert client.post("/api/copies/reset", json={"copy": cid}, headers=h).json()["reset"] == 1
        page = client.get("/api/view/masa", headers=h).json()
        assert any(p["id"] == "B22." + cid for p in page["panels"])
        assert client.post("/api/copies/close", json={"copy": cid}, headers=h).json()["closed"] == cid
        assert client.post("/api/copies/close", json={"copy": cid}, headers=h).status_code == 404
    finally:
        svc.stop()
