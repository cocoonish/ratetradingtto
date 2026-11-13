"""Dependency tracking, invalidation and per-user overlays of the calculation engine."""
from helpers import mini_engine


def chain():
    return mini_engine({"A1": 10, "A2": 5, "B1": "=A1*2", "B2": "=A2+1", "C1": "=B1+B2", "D1": "=C1*10",
                        "E1": "=TODAY()", "F1": '=IF(A1>50,"büyük","küçük")'})


def test_values_and_lazy_evaluation():
    eng = chain()
    calc = eng.shared
    assert calc.value("S!D1") == 260.0
    before = calc.evals
    assert calc.value("S!D1") == 260.0
    assert calc.evals == before                      # memoised: nothing is evaluated twice


def test_shared_inputs_recalculate_only_dependants():
    eng = chain()
    a1 = eng.model.cell_ref("S!A1")
    a2 = eng.model.cell_ref("S!A2")
    eng.declare_inputs([a1, a2])
    calc = eng.shared
    assert calc.value("S!D1") == 260.0 and calc.value("S!B2") == 6.0
    before = calc.evals
    eng.set_inputs({a1: 100.0})
    assert calc.value("S!D1") == 2060.0
    assert calc.value("S!F1") == "büyük"
    assert calc.value("S!B2") == 6.0
    # B1, C1, D1 and F1 were recalculated - B2 (depends on A2 only) and E1 were not
    assert calc.evals - before == 4
    eng.clear_inputs([a1])
    assert calc.value("S!D1") == 260.0


def test_user_overlays_are_isolated():
    eng = chain()
    a1 = eng.model.cell_ref("S!A1")
    a2 = eng.model.cell_ref("S!A2")
    eng.declare_inputs([a1, a2])
    assert eng.shared.value("S!D1") == 260.0
    ali = eng.set_user_inputs("ali", {a1: 1.0})
    veli = eng.set_user_inputs("veli", {a2: 0.0})
    assert ali.value("S!D1") == 80.0                 # (1*2 + 6) * 10
    assert veli.value("S!D1") == 210.0               # (20 + 1) * 10
    assert eng.shared.value("S!D1") == 260.0         # nobody else is affected
    # a shared change reaches the users, each on top of their own input
    eng.set_inputs({a2: 9.0})
    assert eng.shared.value("S!D1") == 300.0
    assert ali.value("S!D1") == 120.0
    assert veli.value("S!D1") == 210.0               # veli overrides A2 personally
    eng.set_user_inputs("ali", {})
    assert eng.user("ali").value("S!D1") == 300.0


def test_user_calc_reuses_shared_results():
    eng = chain()
    a1 = eng.model.cell_ref("S!A1")
    a2 = eng.model.cell_ref("S!A2")
    eng.declare_inputs([a1, a2])
    eng.shared.value("S!D1")
    ali = eng.set_user_inputs("ali", {a1: 1.0})
    ali.value("S!D1")
    # only the cells that depend on A1 were evaluated for the user (B1, C1, D1); B2 came from the shared pool
    assert ali.evals == 3


def test_input_group_shares_one_dependency_bit():
    eng = mini_engine({"A1": 1, "A2": 2, "A3": 3, "B1": "=SUM(A1:A3)", "C1": "=A1"})
    cells = [eng.model.cell_ref("S!A%d" % i) for i in (1, 2, 3)]
    eng.declare_inputs(cells, group="table")
    assert eng.shared.value("S!B1") == 6.0
    eng.set_inputs({cells[2]: 30.0})
    assert eng.shared.value("S!B1") == 33.0


def test_a_user_who_types_into_one_cell_of_a_group_keeps_the_other_cells():
    """Cells of a group share one dependency bit; typing into one of them must not blank the others for that
    user (regression: they read as empty, and what was computed from them leaked to everybody)."""
    eng = mini_engine({"A1": 1, "A2": 2, "A3": 3, "B1": "=SUM(A1:A3)", "C1": "=A1*10", "D1": "=A2*10", "E1": '=IF(A2="","boş","dolu")'})
    cells = [eng.model.cell_ref("S!A%d" % i) for i in (1, 2, 3)]
    eng.declare_inputs(cells, group="table")
    ali = eng.set_user_inputs("ali", {cells[2]: 30.0})
    # the user asks first: nothing is in the shared pool yet
    assert ali.value("S!C1") == 10.0 and ali.value("S!D1") == 20.0 and ali.value("S!E1") == "dolu"
    assert ali.value("S!A1") == 1.0 and ali.value("S!A2") == 2.0 and ali.value("S!A3") == 30.0
    assert ali.value("S!B1") == 33.0
    # ... and what was computed for the user did not reach the others
    assert eng.shared.value("S!B1") == 6.0 and eng.shared.value("S!C1") == 10.0 and eng.shared.value("S!E1") == "dolu"
    veli = eng.set_user_inputs("veli", {cells[0]: 100.0})
    assert veli.value("S!B1") == 105.0 and veli.value("S!C1") == 1000.0 and veli.value("S!D1") == 20.0
    # a shared change of a cell the user left alone reaches the user; the user's own cell stays
    eng.set_inputs({cells[1]: 7.0})
    assert eng.shared.value("S!B1") == 11.0 and ali.value("S!B1") == 38.0 and ali.value("S!D1") == 70.0
    assert veli.value("S!B1") == 110.0
    eng.set_inputs({cells[2]: 9.0})
    assert ali.value("S!B1") == 38.0 and veli.value("S!B1") == 116.0 and eng.shared.value("S!B1") == 17.0
    # a blank typed by the user is a blank; without the user's input the shared view is back
    eng.set_user_inputs("ali", {cells[1]: None})
    assert eng.user("ali").value("S!E1") == "boş" and eng.user("ali").value("S!B1") == 10.0 and eng.shared.value("S!E1") == "dolu"
    eng.set_user_inputs("ali", {})
    assert eng.user("ali").value("S!B1") == 17.0 and eng.user("ali").value("S!C1") == 10.0


def test_grouped_inputs_with_a_formula_default_are_computed_for_the_user():
    eng = mini_engine({"A1": 2, "A2": "=A1*10", "A3": 5, "B1": "=A2+A3"})
    cells = [eng.model.cell_ref("S!A%d" % i) for i in (1, 2, 3)]
    eng.declare_inputs(cells, group="g")
    assert eng.shared.value("S!B1") == 25.0
    u = eng.set_user_inputs("ali", {cells[0]: 3.0})           # A2 is still its formula - on the user's A1
    assert u.value("S!A2") == 30.0 and u.value("S!A3") == 5.0 and u.value("S!B1") == 35.0
    assert eng.shared.value("S!B1") == 25.0
    eng.set_inputs({cells[1]: 1.0})                           # a shared value typed over the formula: everybody's
    assert u.value("S!B1") == 6.0 and eng.shared.value("S!B1") == 6.0


def test_empty_input_cell_can_be_filled_per_user():
    """A blank input still carries a dependency: filling it must recalculate (regression)."""
    eng = mini_engine({"A1": None, "B1": '=IF(A1="","",A1*2)'})
    a1 = eng.model.cell_ref("S!A1")
    eng.declare_inputs([a1])
    assert eng.shared.value("S!B1") == ""
    u = eng.set_user_inputs("ali", {a1: 21.0})
    assert u.value("S!B1") == 42.0
    assert eng.shared.value("S!B1") == ""


def test_input_with_a_formula_default_follows_its_precedents():
    eng = mini_engine({"A1": 2, "B1": "=A1*10", "C1": "=B1+1"})
    a1, b1 = eng.model.cell_ref("S!A1"), eng.model.cell_ref("S!B1")
    eng.declare_inputs([a1, b1])
    assert eng.shared.value("S!C1") == 21.0
    eng.set_inputs({a1: 3.0})
    assert eng.shared.value("S!C1") == 31.0          # B1 still is its formula
    u = eng.set_user_inputs("ali", {b1: 5.0})        # the user types over the formula
    assert u.value("S!C1") == 6.0
    eng.set_inputs({a1: 4.0})
    assert u.value("S!C1") == 6.0 and eng.shared.value("S!C1") == 41.0


def test_clock_tick_invalidates_today():
    eng = chain()
    assert eng.shared.value("S!E1") == 46329.0
    eng.clock.today = lambda: 46330.0
    eng.clock_tick()
    assert eng.shared.value("S!E1") == 46330.0


def test_deep_dependency_chain_does_not_overflow_the_stack():
    cells = {"A1": 1}
    for i in range(2, 4001):
        cells["A%d" % i] = "=A%d+1" % (i - 1)
    eng = mini_engine(cells)
    assert eng.shared.value("S!A4000") == 4000.0
