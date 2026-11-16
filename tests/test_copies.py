"""Temporary copies of a calculator table (``tto/copies.py``): a copy has inputs of its own, evaluated in a layer of the
engine on top of its user's calculation (``tto/xl/engine.py``, ``LayerCalc``).

The first part checks the engine's layers on tiny workbooks; the second the copies of the dashboard's real tables."""
import random

import pytest

from helpers import mini_engine
from tto.marketdata.base import Provider
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
