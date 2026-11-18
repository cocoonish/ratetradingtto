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


def test_a_formula_typed_over_later_drops_no_computed_value():
    """A formula declared an input once values are computed ("elle değer"): what read it carries every bit of its
    mask, so those values are marked and nothing is dropped - the first value typed over a formula used to drop
    every value of every user (the next page computed the whole workbook again)."""
    eng = chain()
    a1, a2, b1 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2", "B1"))
    eng.declare_inputs([a1, a2])
    assert eng.shared.value("S!D1") == 260.0 and eng.shared.value("S!B2") == 6.0 and eng.shared.value("S!F1") == "küçük"
    veli = eng.set_user_inputs("veli", {a2: 0.0})
    assert veli.value("S!D1") == 210.0
    before = eng.shared.evals
    eng.declare_inputs([b1], group="adhoc")                        # B1 = A1*2, typed over by ali
    ali = eng.set_user_inputs("ali", {b1: 100.0})
    assert ali.value("S!D1") == 1060.0 and ali.value("S!B2") == 6.0          # (100 + 6) * 10
    assert ali.evals == 2                                          # C1 and D1 only: B2 came from the shared pool
    assert eng.shared.value("S!D1") == 260.0 and eng.shared.evals == before  # nothing dropped, nothing computed again
    assert veli.value("S!D1") == 210.0 and eng.user("veli").value("S!B1") == 20.0
    # a second value: what reads it follows; a shared change underneath reaches the others
    eng.set_user_inputs("ali", {b1: 50.0})
    assert ali.value("S!D1") == 560.0
    eng.set_inputs({a1: 100.0})
    assert eng.shared.value("S!D1") == 2060.0 and ali.value("S!D1") == 560.0 and veli.value("S!D1") == 2010.0
    eng.set_user_inputs("ali", {})
    assert eng.user("ali").value("S!D1") == 2060.0


def test_a_formula_typed_over_later_reaches_the_values_of_a_user_who_changed_what_it_reads():
    """A user who typed over a formula upstream (B1) computed the cells below with masks of their own: the shared
    mask of C1 ({A1, B1}) is not all in them.  Typed over later, C1 must still reach that user's values (regression:
    the user's own value typed into C1 left D1 at its old value)."""
    eng = mini_engine({"A1": 10, "B1": "=A1*2", "C1": "=B1+1", "D1": "=C1*10"})
    a1, b1, c1 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "B1", "C1"))
    eng.declare_inputs([a1])
    eng.declare_inputs([b1])
    ali = eng.set_user_inputs("ali", {b1: 100.0})
    assert ali.value("S!D1") == 1010.0 and eng.shared.value("S!D1") == 210.0
    eng.declare_inputs([c1], group="adhoc")
    ali = eng.set_user_inputs("ali", {b1: 100.0, c1: 5.0})
    assert ali.value("S!D1") == 50.0 and eng.shared.value("S!D1") == 210.0
    eng.set_inputs({c1: 7.0})                               # ... and a shared value of it reaches the others
    veli = eng.set_user_inputs("veli", {b1: 1.0})
    assert veli.value("S!D1") == 70.0 and eng.shared.value("S!D1") == 70.0 and ali.value("S!D1") == 50.0


def test_a_formula_at_the_end_of_a_long_chain_typed_over_later_drops_nothing():
    """The cell is computed first when it has not been - through the guard that unwinds long chains (300 deep here),
    which must not end in dropping everything."""
    cells = {"A1": 1, "B1": 5, "C1": "=B1*2"}
    cells.update({"A%d" % i: "=A%d+1" % (i - 1) for i in range(2, 301)})
    eng = mini_engine(cells)
    a1, b1, a300 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "B1", "A300"))
    c1 = eng.model.cell_ref("S!C1")
    eng.declare_inputs([a1, b1])
    assert eng.shared.value("S!C1") == 10.0
    eng.declare_inputs([a300], group="adhoc")
    assert eng.shared.memo[c1[0]].get(c1[1]) == 10.0                      # C1 kept: nothing was dropped
    ali = eng.set_user_inputs("ali", {a300: 0.0})
    assert ali.value("S!A300") == 0.0 and eng.shared.value("S!A300") == 300.0
    eng.set_inputs({a1: 2.0})
    assert eng.shared.value("S!A300") == 301.0 and ali.value("S!A300") == 0.0


def test_a_constant_typed_over_later_is_followed_through_the_formulas_that_name_it():
    """A constant carries no dependency bit, so no mask tells what read it: the formulas that name it - directly, in a
    range, through a defined name, inside the box A1:INDEX(..) spans, and what those write and their readers - are
    followed instead, and their values are marked with the new bit.  Nothing is dropped or computed again (it used to
    drop every value of every user: ~10 s for everybody)."""
    eng = mini_engine({"A1": 10, "A2": 5, "A3": 7, "A4": 1, "B1": "=A2*2", "B2": "=SUM(A1:A3)", "B3": "=Q+1",
                       "B4": "=SUM(A1:INDEX(A1:A9,2))", "B5": "=B1+B2+B3+B4", "B6": "=A4*3", "C1": "=TODAY()+B5"},
                      names={"Q": "`S!R2C1`"})
    a1, a2, a4 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "A2", "A4"))
    eng.declare_inputs([a1])
    shared = eng.shared
    assert shared.value("S!C1") == 46329.0 + 10 + 22 + 6 + 15
    assert shared.value("S!B6") == 3.0
    evals, memo = shared.evals, sum(len(m) for m in shared.memo)
    eng.declare_inputs([a2], group="adhoc")                        # A2: read by B1 (cell), B2 (range), B3 (name), B4 (box)
    assert eng.marked == 1 and sum(len(m) for m in shared.memo) >= memo  # nothing dropped
    ali = eng.set_user_inputs("ali", {a2: 0.0})
    assert ali.value("S!B1") == 0.0 and ali.value("S!B2") == 17.0 and ali.value("S!B3") == 1.0 and ali.value("S!B4") == 10.0
    assert ali.value("S!C1") == 46329.0 + 0 + 17 + 1 + 10 and ali.value("S!B6") == 3.0
    assert shared.value("S!C1") == 46329.0 + 53 and shared.evals == evals          # everybody else: as it was
    # a group's second cell (the same bit), and a shared change underneath
    eng.declare_inputs([a4], group="adhoc")
    eng.set_user_inputs("veli", {a4: 2.0})
    assert eng.user("veli").value("S!B6") == 6.0 and shared.value("S!B6") == 3.0 and shared.evals == evals
    eng.set_inputs({a1: 20.0})
    assert ali.value("S!C1") == 46329.0 + 0 + 27 + 1 + 20 and shared.value("S!C1") == 46329.0 + 10 + 32 + 6 + 25


def test_a_constant_an_array_formula_writes_into_still_computes_everything_again():
    """A cell inside the area a formula spills into is the formula's to fill: typed over later, every value is
    computed again (the safe way, as before)."""
    from helpers import mini_book
    book = mini_book({"A1": 1.0, "A2": 2.0, "A3": 3.0, "C1": "=FILTER(A1:A3,A1:A3>0)", "D1": "=C2*10"}, dynamic=("C1",))
    eng = book.engine
    assert eng.shared.value("S!D1") == 20.0
    c2 = eng.model.cell_ref("S!C2")
    assert c2[1] in eng.spill_zone[c2[0]]
    resets = []
    real = eng.reset
    eng.reset = lambda: (resets.append(1), real())
    eng.declare_inputs([c2], group="adhoc")
    assert eng.marked == 0 and resets == [1]
    ali = eng.set_user_inputs("ali", {c2: 7.0})
    assert ali.value("S!D1") == 70.0


def test_the_inputs_a_group_of_cells_reads_are_found_through_the_formulas():
    """RefIndex.upstream, the other way round: which inputs a group of cells (a page's table) reads - through a cell, a
    range, a defined name, the box A1:INDEX(..) spans and the area an array formula spills into.  A chain ends at an
    input (what its own default formula reads is not followed); a chain thousands of cells long is walked without
    recursion; the groups share one walk."""
    from helpers import mini_book
    cells = {"A1": 10, "A2": 5, "A3": 7, "A4": 1, "A5": 2, "B1": "=A2*2", "B2": "=SUM(A1:A3)", "B3": "=Q+1",
             "B4": "=SUM(A1:INDEX(A1:A9,2))", "B6": "=A4*3", "B7": "=A5+B6", "C1": "=B7*2", "C2": "=B1+B3",
             "D1": "=FILTER(A1:A3,A1:A3>0)", "E1": "=D2*10", "F1": "=A1"}
    for i in range(2, 3001):
        cells["F%d" % i] = "=F%d+1" % (i - 1)
    book = mini_book(cells, dynamic=("D1",))
    book.model.names["Q"] = "`S!R4C1`"                          # Q = S!A4
    eng = book.engine
    idx = eng.ref_index()
    ref = eng.model.cell_ref
    a1, a2, a4, b7 = (ref("S!" + a) for a in ("A1", "A2", "A4", "B7"))   # the inputs (B7: one with a default formula)
    assert idx.reads(*ref("S!B2")) == [(0, 1, 1, 3, 1)] and idx.reads(*ref("S!A3")) == []
    groups = {name: [ref("S!" + a) for a in addrs] for name, addrs in {
        "cell": ["B1"], "range": ["B2"], "name": ["B3"], "box": ["B4"], "default": ["C1"], "two": ["C2", "A3"],
        "spill": ["E1"], "chain": ["F3000"], "constant": ["A3"], "input": ["A1"]}.items()}
    got = idx.upstream(groups, [a1, a2, a4, b7])
    assert got == {"cell": {a2}, "range": {a1, a2}, "name": {a4}, "box": {a1, a2, a4}, "default": {b7}, "two": {a2, a4},
                   "spill": {a1, a2}, "chain": {a1}, "constant": set(), "input": {a1}}
    assert eng.shared.value("S!F3000") == 3009.0                  # (nothing computed or changed by the walk)


def test_inputs_declared_before_anything_is_computed_cost_nothing():
    """The service declares every input it knows of before the first value is computed: nothing is dropped (there
    is nothing yet) and nothing is computed to find a formula's dependents - a formula gets its own bit, which comes
    with its value."""
    eng = chain()
    a1, b1, f1 = (eng.model.cell_ref("S!%s" % a) for a in ("A1", "B1", "F1"))
    resets = []
    real = eng.reset
    eng.reset = lambda: (resets.append(1), real())
    eng.declare_inputs([a1, b1, f1], group="g")
    assert resets == [] and eng.shared.evals == 0
    assert eng.input_mask[b1[0]][b1[1]] != eng.input_mask[a1[0]][a1[1]]            # the formula: a bit of its own
    assert eng.shared.value("S!D1") == 260.0 and eng.shared.maskd[b1[0]][b1[1]] & eng.input_mask[b1[0]][b1[1]]
    ali = eng.set_user_inputs("ali", {a1: 1.0})
    veli = eng.set_user_inputs("veli", {b1: 100.0})
    assert ali.value("S!D1") == 80.0 and veli.value("S!D1") == 1060.0 and ali.value("S!F1") == "küçük"
    assert resets == []


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


# ---------------------------------------------------------------------------------------------- overflow
def test_an_overflow_is_num_not_infinity():
    """Arithmetic past the largest float gives Python's infinity; Excel shows #NUM!.  JSON has no infinity: one such
    value used to fail the whole page (a 500).  Whatever reads the cell sees #NUM! as well."""
    from tto.xl.errors import E_NUM
    eng = mini_engine({"A1": 1e308, "B1": "=A1*10", "B2": "=A1+A1", "B3": "=-A1*10", "B4": "=A1/1E-10",
                       "B5": "=(A1*10)-(A1*10)", "B6": "=SUM(A1,A1)", "C1": "=ISERROR(B1)", "C2": "=IFERROR(B2,7)",
                       "D1": "=A1*2/4", "D2": "=A1-1"})
    calc = eng.shared
    for ref in ("B1", "B2", "B3", "B4", "B5", "B6"):
        assert calc.value("S!" + ref) is E_NUM, ref
    assert calc.value("S!C1") is True and calc.value("S!C2") == 7.0
    assert calc.value("S!D2") == 1e308                   # large but finite stays a number
    # (the elements of an array result are stored one by one, through the same place)


def test_an_infinity_that_reaches_the_renderer_is_shown_as_num():
    """A value that never passed through a calculation (a pinned add-in result, a constant of the file) is not cleaned
    by the engine: the renderer shows it as #NUM! too, and a chart leaves the point out."""
    from helpers import mini_book
    from tto.render import Renderer
    from tto.xl import numfmt
    from tto.xl.model import COLS, parse_a1
    book = mini_book({"A1": 1.0, "A2": 2.0})
    calc = book.engine.shared
    rc = parse_a1("A2")
    calc.memo[0][rc] = float("inf")
    cell = Renderer(book).cell(calc, 0, *divmod(rc, COLS), numfmt.get_locale("tr"))
    assert cell["t"] == "#NUM!" and cell["k"] == "e" and "v" not in cell


# ---------------------------------------------------------------------------------------------- depth
def _long_chain(n: int):
    """A chain of ``n`` cells, each reading the one above, with a side branch and a range every 50 cells."""
    cells = {"A1": 1, "B1": 2}
    for i in range(2, n + 1):
        cells["A%d" % i] = "=A%d+B1" % (i - 1) if i % 50 else "=SUM(A%d:A%d)/10" % (i - 3, i - 1)
    cells["C1"] = "=A%d*2" % n
    return mini_engine(cells)


def test_a_thread_with_a_big_stack_evaluates_long_chains_without_unwinding():
    """The calculation threads (a 255 MiB stack) evaluate ~1000 nested cells in one go; any other thread unwinds at
    DEPTH_LIMIT and restarts the chain from its deep end - ~7x slower on the Motor sheet, with the same values."""
    from tto.xl.engine import DEEP_LIMIT, DEPTH_LIMIT, depth_limit, run_with_big_stack
    assert depth_limit() == DEPTH_LIMIT                                # this (the main) thread
    assert run_with_big_stack(depth_limit) == DEEP_LIMIT
    small = _long_chain(600)
    b1 = small.model.cell_ref("S!B1")
    small.declare_inputs([b1])
    v_small = small.shared.value("S!C1")
    assert small.shared.restarts > 0                                  # unwound (and restarted) on this thread
    big = _long_chain(600)
    big.declare_inputs([big.model.cell_ref("S!B1")])
    assert run_with_big_stack(big.shared.value, "S!C1") == v_small
    assert big.shared.restarts == 0                                   # in one go
    # the same values and dependency masks either way
    assert big.shared.memo == small.shared.memo
    assert big.shared.maskd == small.shared.maskd
    # deeper than DEEP_LIMIT still unwinds (and works) on the big stack
    deep = _long_chain(3000)
    assert run_with_big_stack(deep.shared.value, "S!A3000") == deep.shared.value("S!A3000")


# ---------------------------------------------------------------------------------------------- invalidation, at random
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


def _check_groups(calc):
    for si, md in enumerate(calc.maskd):
        for rc, k in md.items():
            assert rc in calc.groups.get(k, {}).get(si, ()), (si, rc)


def test_an_array_formula_given_an_array_writes_it_into_its_cells():
    """An array formula declared an input (a Bloomberg history block's, the ASW history offshore) and given an array in a
    calculation of its own - a user's, a layer: its result typed over as a whole.  The cells it covers take the elements
    as the formula's own result writes them (the rows of its area it leaves out: empty), what reads them is computed
    again there and nobody else's values move; the elements stay while other inputs change (they are not written again)
    and follow the array when it changes or goes."""
    from helpers import mini_book
    from tto.xl.values import XlArray
    book = mini_book({"A1": 1.0, "A2": 2.0, "A3": 3.0, "A5": 7.0, "C1": "=FILTER(A1:A3,A1:A3>0)", "D1": "=C2*10",
                      "D2": "=SUM(C1:C3)+A5", "D3": "=COUNT(C1:C3)"}, dynamic=("C1",))
    eng = book.engine
    c1, a1, a5 = (eng.model.cell_ref("S!" + a) for a in ("C1", "A1", "A5"))
    eng.declare_inputs([c1, a1, a5])
    shared = eng.shared
    assert [shared.value("S!" + a) for a in ("C2", "D1", "D2", "D3")] == [2.0, 20.0, 13.0, 3.0]
    block = XlArray([[5.0], [6.0], [8.0]])
    ali = eng.set_user_inputs("ali", {c1: block})
    assert [ali.value("S!" + a) for a in ("C1", "C2", "C3", "D1", "D2", "D3")] == [5.0, 6.0, 8.0, 60.0, 26.0, 3.0]
    assert [shared.value("S!" + a) for a in ("C2", "D1", "D2")] == [2.0, 20.0, 13.0]          # nobody else's
    _check_groups(ali)
    # another input of the user's, a shared one: the block's cells are not written again - what reads them follows
    stores = []
    real = ali._spill
    ali._spill = lambda *a, **k: (stores.append(1), real(*a, **k))
    eng.set_user_inputs("ali", {c1: block, a5: 1.0})
    eng.set_inputs({a1: 4.0})
    assert stores == [] and [ali.value("S!" + a) for a in ("C2", "D2")] == [6.0, 20.0]
    assert [shared.value("S!" + a) for a in ("C1", "D2")] == [4.0, 16.0]
    # a shorter block: the cells of its area it leaves out are empty, as the formula's own shorter result leaves them
    eng.set_user_inputs("ali", {c1: XlArray([[9.0], [4.0]]), a5: 1.0})
    assert stores == [1] and ali.value("S!C3") is None and [ali.value("S!" + a) for a in ("D1", "D2", "D3")] == [40.0, 14.0, 2.0]
    _check_groups(ali)
    # a layer over it, with a block of its own; the user's block gone: the formula's result again
    layer = eng.layer(("ali", "x"), ali, {c1: XlArray([[1.0], [2.0], [3.0]])})
    assert [layer.value("S!" + a) for a in ("D1", "D2", "D3")] == [20.0, 7.0, 3.0] and ali.value("S!D2") == 14.0
    eng.set_user_inputs("ali", {a5: 1.0})
    assert [ali.value("S!" + a) for a in ("C1", "C2", "D2")] == [4.0, 2.0, 10.0] and layer.value("S!D2") == 7.0


def test_invalidation_matches_a_calculation_from_scratch_at_random():
    """Shared values, users' own values, values typed over formulas and constants later and the clock, in random order:
    after every step every user's every cell is what a fresh calculation of the same inputs gives (one that knew every
    input from the start), and each computed value is listed under its mask (an invalidation tests the masks)."""
    import random
    for seed in range(6):
        rnd = random.Random(seed)
        cells = _random_book(rnd)
        eng = mini_engine(cells)
        ref = eng.model.cell_ref
        inputs = [ref("S!A%d" % i) for i in range(1, 7)]
        eng.declare_inputs(inputs[:4])
        eng.declare_inputs(inputs[4:], group="g")
        declared = list(inputs)
        shared_vals = {}
        users = {"ali": {}, "veli": {}}
        today = [46329.0]
        formula_cells = ["B%d" % i for i in range(1, 41)]
        for step in range(60):
            op = rnd.random()
            if op < 0.25:
                c = rnd.choice(declared)
                shared_vals[c] = float(rnd.randint(0, 20))
                eng.set_inputs({c: shared_vals[c]})
            elif op < 0.35 and shared_vals:
                c = rnd.choice(list(shared_vals))
                del shared_vals[c]
                eng.clear_inputs([c])
            elif op < 0.65:
                name = rnd.choice(list(users))
                ov = dict(users[name])
                c = rnd.choice(declared)
                if c in ov and rnd.random() < 0.3:
                    del ov[c]
                else:
                    ov[c] = float(rnd.randint(-5, 30))
                users[name] = ov
                eng.set_user_inputs(name, ov)
            elif op < 0.8:
                # a value typed over a formula or over a constant, later
                c = ref("S!" + rnd.choice(formula_cells + ["C1", "C2", "C3", "C4", "A7", "A8"]))
                if c not in declared:
                    eng.declare_inputs([c], group="adhoc")
                    declared.append(c)
            elif op < 0.9:
                today[0] += 1
                eng.clock.today = (lambda t: (lambda: t))(today[0])
                eng.clock_tick()
            # read a random part (not everything is computed all the time)
            for calc in [eng.shared] + [eng.user(n) for n in users]:
                for a in rnd.sample(formula_cells, 12):
                    calc.value("S!" + a)
                _check_groups(calc)
            # ... and compare with a calculation from scratch
            fresh = mini_engine(cells, today=today[0])
            fresh.declare_inputs(inputs[:4])
            fresh.declare_inputs(inputs[4:], group="g")
            fresh.declare_inputs([c for c in declared if c not in inputs], group="adhoc")
            fresh.set_inputs(dict(shared_vals))
            for name in [None] + list(users):
                mine = eng.shared if name is None else eng.user(name)
                theirs = fresh.shared if name is None else fresh.set_user_inputs(name, users[name])
                for a in formula_cells:
                    assert mine.value("S!" + a) == theirs.value("S!" + a), (seed, step, name, a)
