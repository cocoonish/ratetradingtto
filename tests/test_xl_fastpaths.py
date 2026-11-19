"""The formula engine's fast paths give what its general paths give, bit for bit.

``broadcast2`` (the element-wise operators of array formulas), SUMPRODUCT, COUNTIF and MMULT take a fast path in the
common case (numbers, blanks, logicals; shapes that line up) and keep their general path for everything else.  Each fast
path is compared here with its general path: same type, same float bits (-0.0 apart from 0.0, NaN as NaN), the very
same error object - on edge values, mixed and error inputs, every shape, random arrays, and whole formulas evaluated
by the engine with the fast paths switched off.
"""
import math
import random

import pytest

from helpers import mini_engine
from tto.xl import functions as xf
from tto.xl import values as xv
from tto.xl.errors import E_DIV0, E_NA, E_NUM, E_VALUE, XlError

OPS = (xv._add, xv._sub, xv._mul, xv._div, xv._pow, xv._cat, xv._eq, xv._ne, xv._lt, xv._gt, xv._le, xv._ge)
#: values the fast paths meet or must leave alone: numbers at the edges, near-equal pairs (num_eq), blanks, logicals,
#: texts that read as numbers or dates, other text, errors, an int
EDGE = [0.0, -0.0, 1.0, -1.0, 0.1, 0.2, 0.3, 0.1 + 0.2, 1e-300, -1e-300, 1e300, -1e300, 1e308, float("inf"),
        float("-inf"), float("nan"), 3.0, 2.5, 46329.0, None, True, False, "", "3", "3,5", "4.11.2026", "abc", "TRUE",
        E_NA, E_DIV0, E_VALUE, 7]


def same(a, b):
    """Bit for bit: type, float bits, the same error object, the same shape."""
    ta, tb = type(a), type(b)
    if ta is not tb:
        return False
    if ta is float:
        if a != a:
            return b != b
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    if ta is xv.XlArray:
        return (a.nr, a.nc) == (b.nr, b.nc) and len(a.rows) == len(b.rows) and all(
            len(ra) == len(rb) and all(same(x, y) for x, y in zip(ra, rb)) for ra, rb in zip(a.rows, b.rows))
    if ta is XlError:
        return a is b
    return a == b


def outcome(fn, *args):
    """The value, or the exception's type (a malformed array fails the same way on both paths)."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        return ("raised", type(exc))


def same_outcome(a, b):
    if type(a) is tuple and type(b) is tuple:
        return a == b
    return same(a, b)


def arr(rows):
    return xv.XlArray([list(r) for r in rows])


def rand_rows(rng, nr, nc, pool):
    return [[rng.choice(pool) for _ in range(nc)] for _ in range(nr)]


def rand_floats(rng, nr, nc):
    return [[rng.choice((rng.uniform(-1e6, 1e6), rng.uniform(-1, 1), float(rng.randint(-5, 5)), 0.1 * rng.randint(0, 9)))
             for _ in range(nc)] for _ in range(nr)]


# --------------------------------------------------------------------------- broadcast2
def general_broadcast(fn, a, b):
    return xv._broadcast_rows(fn, xv.as_rows(a), xv.as_rows(b))


SHAPES = [((5, 1), (5, 1)), ((5, 1), (1, 1)), ((1, 1), (5, 1)), ((1, 6), (1, 6)), ((1, 6), (1, 1)), ((4, 3), (4, 3)),
          ((4, 3), (1, 3)), ((1, 3), (4, 3)), ((4, 3), (4, 1)), ((4, 1), (4, 3)), ((4, 1), (1, 3)), ((1, 3), (4, 1)),
          ((1, 1), (1, 1)), ((4, 3), (1, 1)),
          # shapes that do not line up: the general path pads with #N/A
          ((3, 1), (5, 1)), ((2, 3), (2, 4)), ((3, 2), (2, 3))]


@pytest.mark.parametrize("fn", OPS, ids=lambda f: f.__name__)
def test_broadcast_every_shape_and_value_kind_matches_the_general_path(fn):
    rng = random.Random(hash(fn.__name__) & 0xFFFF)
    for (na, ma), (nb, mb) in SHAPES:
        for _ in range(12):
            a = arr(rand_rows(rng, na, ma, EDGE))
            b = arr(rand_rows(rng, nb, mb, EDGE))
            assert same_outcome(outcome(xv.broadcast2, fn, a, b), outcome(general_broadcast, fn, a, b)), (fn.__name__, a.rows, b.rows)


@pytest.mark.parametrize("fn", OPS, ids=lambda f: f.__name__)
def test_broadcast_every_pair_of_edge_values(fn):
    xs = [[x] for x in EDGE for _ in EDGE]
    ys = [[y] for _ in EDGE for y in EDGE]
    pairs = [(arr(xs), arr(ys))]
    for y in EDGE:                                                   # a single value against a column / a row
        pairs += [(arr([[x] for x in EDGE]), y), (y, arr([EDGE]))]
    for a, b in pairs:
        # (an infinity joined to a text fails on both paths alike: fmt_general)
        assert same_outcome(outcome(xv.broadcast2, fn, a, b), outcome(general_broadcast, fn, a, b)), (fn.__name__, b)


@pytest.mark.parametrize("fn", (xv._add, xv._sub, xv._mul, xv._div, xv._eq, xv._lt, xv._gt, xv._le, xv._ge, xv._ne),
                         ids=lambda f: f.__name__)
def test_broadcast_random_numbers_and_logicals(fn):
    rng = random.Random(7)
    for _ in range(150):
        nr, nc = rng.choice(((40, 1), (1, 81), (15, 15), (198, 1), (3, 7)))
        a = arr(rand_floats(rng, nr, nc))
        if rng.random() < 0.5:                                       # comparisons' results multiplied, as in DV01
            a = arr([[v > 0 for v in r] for r in a.rows])
        b = arr(rand_floats(rng, nr, nc)) if rng.random() < 0.7 else rng.uniform(-2, 2)
        if rng.random() < 0.2:                                       # one element of another kind
            rows = a.rows
            rows[rng.randrange(nr)][rng.randrange(nc)] = rng.choice(("", None, "2", E_NA, True, "x"))
        assert same(xv.broadcast2(fn, a, b), general_broadcast(fn, a, b))


def test_broadcast_of_numbers_that_15_digits_call_equal():
    a = arr([[0.1 + 0.2], [0.3], [1.0000000000000002], [1e-20], [-0.0]])
    for y in (0.3, 0.30000000000000004, 1.0, 0.0, -0.0):
        for fn in (xv._eq, xv._ne, xv._lt, xv._gt, xv._le, xv._ge):
            assert same(xv.broadcast2(fn, a, y), general_broadcast(fn, a, y)), (fn.__name__, y)
    assert xv.broadcast2(xv._eq, a, 0.3).rows[0][0] is True             # (0.1+0.2 = 0.3 on 15 digits)


def test_broadcast_division_by_zero_and_errors_in_their_place():
    got = xv.broadcast2(xv._div, arr([[1.0], [2.0], ["a"], [E_NA], [None]]), arr([[0.0], [-0.0], [1.0], [0.0], [2.0]]))
    assert got.rows == [[E_DIV0], [E_DIV0], [E_VALUE], [E_NA], [0.0]]
    assert got.rows[0][0] is E_DIV0 and got.rows[3][0] is E_NA


def test_broadcast_of_ranges_empty_and_ragged_arrays():
    eng = mini_engine({"A1": 1, "A2": "x", "A3": None, "B1": 2, "B2": 3, "B3": True})
    x = eng.shared
    a, b = xv.XlRange(x, 0, 1, 1, 3, 1), xv.XlRange(x, 0, 1, 2, 3, 2)
    for fn in OPS:
        assert same(xv.broadcast2(fn, a, b), general_broadcast(fn, a, b))
        assert same(xv.broadcast2(fn, xv.XlRange(x, 0, 1, 1, 3, 2), 2.0), general_broadcast(fn, xv.XlRange(x, 0, 1, 1, 3, 2), 2.0))
    empty = xv.XlArray([])
    assert same(xv.broadcast2(xv._mul, empty, 1.0), general_broadcast(xv._mul, empty, 1.0))
    for rows in ([[1.0], [2.0, 3.0]], [[1.0, 2.0], [3.0]], [[1.0, 2.0], [3.0, 4.0, 5.0]], [[1.0], []]):
        ragged = xv.XlArray(rows)
        for other in (1.0, arr([[1.0], [2.0]]), arr([[1.0, 2.0], [3.0, 4.0]])):
            assert same_outcome(outcome(xv.broadcast2, xv._mul, ragged, other), outcome(general_broadcast, xv._mul, ragged, other))


# --------------------------------------------------------------------------- SUMPRODUCT
def general_sumproduct(*args):
    if not args:
        return E_VALUE
    mats = [xv.as_rows(a) for a in args]
    nr = len(mats[0])
    nc = len(mats[0][0]) if nr else 0
    for m in mats[1:]:
        if len(m) != nr or (len(m[0]) if m else 0) != nc:
            return E_VALUE
    return xf._sumproduct_general(mats, nr, nc)


def test_sumproduct_matches_the_general_path():
    rng = random.Random(11)
    for _ in range(400):
        k = rng.choice((1, 1, 2, 2, 3))
        nr, nc = rng.choice(((40, 1), (20, 1), (1, 81), (15, 81), (1, 1), (3, 4)))
        mixed = rng.random() < 0.35
        args = [arr(rand_rows(rng, nr, nc, EDGE) if mixed else rand_floats(rng, nr, nc)) for _ in range(k)]
        assert same(xf.F_SUMPRODUCT(*args), general_sumproduct(*args)), [a.rows for a in args]


def test_sumproduct_signed_zeros_infinities_errors_and_shapes():
    cases = [
        ([[-0.0], [-0.0]],), ([[-0.0]], [[1.0]]), ([[1.0], ["x"]], [[2.0], [float("inf")]]),     # 0 * inf after a text
        ([[float("inf")], [1.0]], [[0.0], [1.0]]), ([[1e308], [1e308]], [[10.0], [10.0]]),
        ([[1.0], [E_NA]], [[E_DIV0], [2.0]]), ([[1.0, 2.0]], [[3.0, 4.0]], [[5.0, 6.0]]),
        ([[1.0], [2.0]], [[1.0, 2.0]]), ([[1.0], [2.0]], [[1.0], [2.0], [3.0]]), ([],), ([[]], [[]]),
        ([[True], [2.0]], [[3.0], [4.0]]), ([[None], [2.0]],), ([[7], [2.0]], [[3.0], [4.0]]),
    ]
    for rows in cases:
        args = [xv.XlArray([list(r) for r in m]) for m in rows]
        assert same(xf.F_SUMPRODUCT(*args), general_sumproduct(*args)), rows
    assert xf.F_SUMPRODUCT() is E_VALUE
    assert xf.F_SUMPRODUCT(arr([[0.1]] * 10)) == 0.9999999999999999          # added left to right, as Excel


# --------------------------------------------------------------------------- COUNTIF
CRITERIA = [0.0, 1.0, 3.0, -0.0, 46329.0, float("nan"), 7, None, True, False, "", "3", "=3", ">2", "<>3", "abc", "a*",
            "?bc", "=", "<>", E_NA, arr([[3.0]]), arr([[None]]), arr([[E_NA]]), xv.XlArray([])]


def test_countif_matches_the_general_path():
    rng = random.Random(5)
    mixed = EDGE + ["0", " 3 ", "3.0", "abcd", "ABC", 3.0, 3.0, 0.0]
    numbers = [0.0, -0.0, 3.0, 3.0, 1.0, 46329.0, float("nan"), None, None]       # (the header strip's ranges)
    texts = ["", "", "", "0", "3", " 3 ", "3,0", "abc", "4.11.2026", None]          # (Günlük İşlemler')
    for crit in CRITERIA:
        for pool in (mixed, numbers, texts):
            for _ in range(25):
                nr, nc = rng.choice(((164, 1), (21, 1), (1, 12), (6, 4)))
                rng_arr = arr(rand_rows(rng, nr, nc, pool))
                assert same(xf.F_COUNTIF(rng_arr, crit), xf._countif_general(rng_arr, crit)), (crit, rng_arr.rows)
    nan = float("nan")
    same_nan = arr([[nan], [nan], [1.0]])                       # (the very same NaN object: not counted, as ==)
    assert xf.F_COUNTIF(same_nan, nan) == xf._countif_general(same_nan, nan) == 0.0


def test_countif_over_a_range_of_the_engine():
    eng = mini_engine({"A1": 0, "A2": "0", "A3": "", "A4": None, "A5": True, "A6": "x", "A7": 0, "B1": "=A1*0"})
    rg = xv.XlRange(eng.shared, 0, 1, 1, 7, 1)
    for crit in (None, 0.0, 0, "0", "", "x", True):
        assert same(xf.F_COUNTIF(rg, crit), xf._countif_general(rg, crit)), crit
    assert xf.F_COUNTIF(rg, None) == 3.0                    # a blank criterion counts zeros: 0, "0", 0


# --------------------------------------------------------------------------- MMULT
def test_mmult_matches_the_general_path():
    rng = random.Random(3)
    for _ in range(120):
        n, k, m = rng.choice(((18, 45, 86), (86, 86, 18), (1, 20, 1), (15, 81, 1), (3, 3, 3), (1, 1, 1), (2, 5, 3)))
        a, b = arr(rand_floats(rng, n, k)), arr(rand_floats(rng, k, m))
        assert same(xf.F_MMULT(a, b), xf._mmult_general(a, b))


def test_mmult_errors_text_shapes_and_signed_zeros():
    a, b = arr([[1.0, 2.0], [3.0, 4.0]]), arr([[5.0], [6.0]])
    cases = [(a, b), (a, arr([[5.0, 6.0]])), (arr([[1.0, "x"]]), b), (arr([[1.0, E_NA]]), arr([[E_DIV0], [1.0]])),
             (arr([[1.0, 2.0]]), arr([[E_DIV0], [1.0]])), (arr([[None, 2.0]]), b), (arr([[True, 2.0]]), b),
             (xv.XlArray([]), b), (a, xv.XlArray([])), (arr([[-0.0, -0.0]]), arr([[1.0], [1.0]])),
             (arr([[0.0, -0.0]]), arr([[-1.0], [1.0]])), (arr([[float("inf"), 1.0]]), arr([[0.0], [1.0]])),
             (2.0, 3.0), (xv.XlArray([[1.0, 2.0], [3.0]]), b), (a, xv.XlArray([[5.0], [6.0, 7.0]]))]
    for x, y in cases:
        assert same_outcome(outcome(xf.F_MMULT, x, y), outcome(xf._mmult_general, x, y)), (x, y)
    assert xf.F_MMULT(arr([[1.0, E_NA]]), b) is E_NA and xf.F_MMULT(arr([[1.0, "x"]]), b) is E_VALUE


# --------------------------------------------------------------------------- whole formulas, fast paths on and off
FORMULAS = [
    "=SUMPRODUCT((A1:A12>=2)*(A1:A12<9)*B1:B12)", "=SUMPRODUCT((A1:A12>2)*(A1:A12<=9)*(B1:B12-C1))",
    "=SUMPRODUCT(B1:B12,C1:C12)", "=SUMPRODUCT(B1:B12*C1:C12/2)", "=SUMPRODUCT((D1:D12=\"USD\")*B1:B12)",
    "=SUMPRODUCT(--(D1:D12<>\"\"))", "=SUMPRODUCT((A1:A12+B1:B12)^2)", "=SUMPRODUCT(B1:B12/A1:A12)",
    "=COUNTIF(A1:A12,3)", "=COUNTIF(D1:D12,\"USD\")", "=COUNTIF(E1:E12,E1)", "=COUNTIF(A1:A12,\">4\")",
    "=SUM(MMULT(TRANSPOSE(B1:B12),C1:C12))", "=INDEX(MMULT(F1:G2,F1:G2),2,1)", "=SUM(TRANSPOSE(A1:A12)*2)",
    "=MAX((A1:A12-B1:B12)*(D1:D12=\"EUR\"))", "=SUM(IF(A1:A12>5,B1:B12,0))",
    # numbers only: the fast paths all the way
    "=SUMPRODUCT((H1:H12>=0.5)*(H1:H12<5)*I1:I12)", "=SUMPRODUCT(H1:H12,I1:I12)", "=SUMPRODUCT(H1:H12)",
    "=SUM(MMULT(TRANSPOSE(H1:H12),I1:I12))", "=SUM(MMULT(H1:I12,TRANSPOSE(H1:I12)))", "=COUNTIF(H1:H12,H3)",
    "=SUM((H1:H12-I1:I12)/(I1:I12+10))",
]
NUMBERS_ONLY = 7                 # the last formulas: numbers in, a number out


def _cells():
    rng = random.Random(9)
    cells = {}
    for i in range(1, 13):
        cells["A%d" % i] = rng.choice((1, 2, 3, 4.5, 9, 12, "", None, "3"))
        cells["B%d" % i] = rng.choice((0.1, -2.5, 3, 1e6, None, True, 0))
        cells["C%d" % i] = rng.choice((1.5, -0.0, 2, 0.3, None))
        cells["D%d" % i] = rng.choice(("USD", "EUR", "", None))
        cells["E%d" % i] = rng.choice((0, "", None, "0", 1))
        cells["H%d" % i] = rng.choice((0.1, 0.5, 2.25, 4.0, 1e-9, -3.5, 7.125))
        cells["I%d" % i] = rng.uniform(-100, 100)
    cells.update({"F1": 1.5, "G1": 2.0, "F2": -3.0, "G2": 0.25})
    return cells


def test_whole_formulas_give_the_same_values_with_the_fast_paths_off(monkeypatch):
    cells = _cells()
    for i, f in enumerate(FORMULAS):
        cells["Z%d" % (i + 1)] = f
    arrays = tuple("Z%d" % (i + 1) for i, f in enumerate(FORMULAS) if "IF(" in f or f.startswith(("=MAX", "=SUM((")))
    fast = mini_engine(cells, array=arrays).shared
    want = [fast.value("S!Z%d" % (i + 1)) for i in range(len(FORMULAS))]
    monkeypatch.setattr(xv, "_broadcast_fast", lambda fn, ra, rb: None)
    monkeypatch.setattr(xf, "_sumproduct_numbers", lambda mats, nr, nc: None)
    monkeypatch.setattr(xf, "_number_criterion", lambda crit: None)
    monkeypatch.setattr(xf, "_number_block", lambda rows: False)
    slow = mini_engine(cells, array=arrays).shared
    got = [slow.value("S!Z%d" % (i + 1)) for i in range(len(FORMULAS))]
    for f, w, g in zip(FORMULAS, want, got):
        assert same(w, g), (f, w, g)
    assert all(type(w) is float for w in want[-NUMBERS_ONLY:]), list(zip(FORMULAS, want))
    assert want[13] == -5.25                                          # (row 2 of the 2x2 MMULT squared)
