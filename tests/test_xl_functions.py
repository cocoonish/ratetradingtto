"""Excel semantics of the formula engine: operators, coercion, functions, locale."""
import pytest

from helpers import ev, mini_book, mini_engine
from tto.xl.errors import XlError

CELLS = {"A1": 1, "A2": 2, "A3": 3, "A4": "x", "B1": 10, "B2": 20, "B3": 30, "B4": 40, "C1": "apple", "C2": "avocado",
         "C3": "banana", "D1": 1, "D2": 5, "D3": 9, "E1": 4, "E2": 7, "F1": 2, "F2": 6}


def approx(a, b):
    return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


@pytest.mark.parametrize("formula, expected", [
    # ---- operators and precedence
    ("-2^2", 4.0),                       # unary minus binds tighter than ^ in Excel
    ("2^3^2", 64.0),                     # ^ is left associative
    ("10%", 0.1),
    ("1+2*3", 7.0),
    ("(1+2)*3", 9.0),
    ("5-3-1", 1.0),
    ("2*3%", 0.06),
    ('"a"&1', "a1"),
    ('1&2', "12"),
    # ---- comparisons: text is case-insensitive, numbers < text < booleans
    ('"a"="A"', True),
    ('1="1"', False),
    ("TRUE>5", True),
    ('"a">5', True),
    ('"abc"<"abd"', True),
    ("1.1+2.2=3.3", True),               # compared on 15 significant digits
    # ---- coercion in arithmetic (Turkish locale)
    ('"3"+4', 7.0),
    ('"3,5"+1', 4.5),
    ('"4.11.2026"+1', 46331.0),          # a text date (what BDP returns on the desk) is a date
    ("TRUE+1", 2.0),
    # ---- rounding
    ("ROUND(2.5,0)", 3.0),
    ("ROUND(-2.5,0)", -3.0),
    ("ROUND(1.005,2)", 1.01),            # half away from zero on the 15-digit decimal value
    ("ROUND(2.675,2)", 2.68),
    ("ROUND(1234.5,-2)", 1200.0),
    ("ROUNDUP(-1.21,1)", -1.3),
    ("ROUNDDOWN(-1.29,1)", -1.2),
    ("INT(-1.5)", -2.0),
    ("TRUNC(-1.5)", -1.0),
    ("MOD(-7,3)", 2.0),
    ("MOD(7,-3)", -2.0),
    # ---- maths
    ("POWER(2,10)", 1024.0),
    ("LOG(100)", 2.0),
    ("LOG(8,2)", 3.0),
    ("ABS(-3)", 3.0),
    ("SIGN(-2)", -1.0),
    ("SQRT(16)", 4.0),
    # ---- dates
    ("DATE(2026,11,3)", 46329.0),
    ("DATE(2026,13,1)", 46388.0),        # month overflow rolls into the next year
    ("YEAR(46329)", 2026.0),
    ("MONTH(46329)", 11.0),
    ("DAY(46329)", 3.0),
    ("EDATE(DATE(2026,1,31),1)", 46081.0),      # 28 Feb 2026
    ("EOMONTH(DATE(2026,2,10),0)", 46081.0),
    ("EOMONTH(DATE(2026,2,10),1)", 46112.0),
    ("WEEKDAY(DATE(2026,11,3))", 3.0),          # Tuesday, Sunday = 1
    ("WEEKDAY(DATE(2026,11,3),2)", 2.0),        # Monday = 1
    ("WORKDAY(DATE(2026,11,6),1)", 46335.0),    # Friday + 1 business day = Monday
    ("WORKDAY(DATE(2026,11,6),-5)", 46325.0),
    ("NETWORKDAYS(DATE(2026,11,2),DATE(2026,11,13))", 10.0),
    ("DAYS(DATE(2026,3,1),DATE(2026,1,1))", 59.0),
    ("YEARFRAC(DATE(2026,1,1),DATE(2026,7,1),0)", 0.5),
    ("YEARFRAC(DATE(2026,1,1),DATE(2026,7,1),2)", 181.0 / 360.0),
    ("YEARFRAC(DATE(2026,1,1),DATE(2026,7,1),3)", 181.0 / 365.0),
    ("TODAY()", 46329.0),
    # ---- text (Turkish locale: decimal comma, dot grouping, Turkish month names and casing)
    ('TEXT(1234.5,"#,##0.00")', "1.234,50"),
    ('TEXT(0.3555,"0.00%")', "35,55%"),
    ('TEXT(DATE(2026,11,3),"dd.mm.yyyy")', "03.11.2026"),
    ('TEXT(DATE(2026,11,3),"d mmm yy")', "3 Kas 26"),
    ('TEXT(5,"000")', "005"),
    ("FIXED(1234.567,1)", "1.234,6"),
    ('LEFT("abcdef",2)&RIGHT("abcdef",2)&MID("abcdef",3,2)', "abefcd"),
    ('LEN("ğüş")', 3.0),
    ('FIND("c","abcabc",4)', 6.0),
    ('SEARCH("C","abc")', 3.0),
    ('SUBSTITUTE("a-b-c","-","+",2)', "a-b+c"),
    ('TRIM("  a   b ")', "a b"),
    ('UPPER("ığ")', "IĞ"),
    ('TEXTJOIN("-",TRUE,"a","","b")', "a-b"),
    ('REPT("ab",3)', "ababab"),
    ('EXACT("a","A")', False),
    ('VALUE("1.234,5")', 1234.5),
    ('VALUE("35%")', 0.35),
    # ---- logic
    ("IF(TRUE,1,1/0)", 1.0),             # the branch that is not taken is not evaluated
    ('IF(1>2,"a","b")', "b"),
    ('CHOOSE(2,"a","b","c")', "b"),
    ('AND(TRUE,1,"TRUE")', True),
    ("OR(FALSE,0)", False),
    ("NOT(0)", True),
    ('N("x")', 0.0),
    ("N(TRUE)", 1.0),
    ('ISNUMBER("1")', False),
    ('ISTEXT("")', True),
    ('IFERROR(1/0,"x")', "x"),
    ("_xlfn.LET(_xlpm.x,2,_xlpm.y,_xlpm.x*3,_xlpm.x+_xlpm.y)", 8.0),
    ('SUM(1,"2",TRUE)', 4.0),            # literal arguments are coerced ...
    ('MAX(1,"5",TRUE)', 5.0),
])
def test_scalar_formulas(tr_locale, formula, expected):
    got = ev(formula)
    if isinstance(expected, float):
        assert isinstance(got, float) and approx(got, expected), (formula, got)
    else:
        assert got == expected and type(got) is type(expected), (formula, got)


@pytest.mark.parametrize("formula, code", [
    ("1/0", "#DIV/0!"),
    ('""+1', "#VALUE!"),
    ('"abc"*2', "#VALUE!"),
    ("SQRT(-1)", "#NUM!"),
    ("LN(0)", "#NUM!"),
    ("NA()", "#N/A"),
    ('AVERAGE(1,2,"x")', "#VALUE!"),
    ("1+NA()", "#N/A"),                  # errors propagate ...
    ("SUM(1,1/0)", "#DIV/0!"),
    ("DATE(2026,1,1)-NA()", "#N/A"),
])
def test_errors(formula, code):
    got = ev(formula)
    assert type(got) is XlError and got.code == code, (formula, got)


@pytest.mark.parametrize("formula, expected", [
    ("SUM(A1:A4)", 6.0),                 # ... but text inside a range is skipped
    ("AVERAGE(A1:A4)", 2.0),
    ("COUNT(A1:A4)", 3.0),
    ("COUNTA(A1:A5)", 4.0),
    ('SUMIF(A1:A3,">1",B1:B3)', 50.0),
    ('SUMIF(C1:C3,"a*",B1:B3)', 30.0),
    ('COUNTIF(C1:C3,"<>banana")', 2.0),
    ("COUNTIF(A1:A4,2)", 1.0),
    ('SUMIFS(B1:B3,A1:A3,">=2",C1:C3,"a*")', 20.0),
    ('AVERAGEIFS(B1:B3,A1:A3,">1")', 25.0),
    ('MAXIFS(B1:B3,A1:A3,"<3")', 20.0),
    ('MINIFS(B1:B3,A1:A3,">1")', 20.0),
    ('COUNTIFS(A1:A3,">1",B1:B3,"<30")', 1.0),
    ("SUMPRODUCT((A1:A3>1)*B1:B3)", 50.0),
    ("SUMPRODUCT(A1:A3,B1:B3)", 140.0),
    ("VLOOKUP(2,A1:B3,2,FALSE)", 20.0),
    ("VLOOKUP(2.5,A1:B3,2,TRUE)", 20.0),
    ('HLOOKUP("x",A4:B4,1,FALSE)', "x"),
    ("MATCH(5,D1:D3,0)", 2.0),
    ("MATCH(6,D1:D3,1)", 2.0),
    ('MATCH("BANANA",C1:C3,0)', 3.0),
    ("INDEX(B1:B3,2)", 20.0),
    ("INDEX(A1:B3,3,2)", 30.0),
    ("SUM(INDEX(A1:B3,0,2))", 60.0),
    ("LOOKUP(6,D1:D3,B1:B3)", 20.0),
    ("LARGE(B1:B4,2)", 30.0),
    ("SMALL(B1:B4,2)", 20.0),
    ("MEDIAN(B1:B4)", 25.0),
    ("STDEV(B1:B4)", 12.909944487358056),
    ("STDEVP(B1:B4)", 11.180339887498949),
    ("SLOPE(B1:B3,A1:A3)", 10.0),
    ("INTERCEPT(B1:B3,A1:A3)", 0.0),
    ("ROWS(A1:B4)", 4.0),
    ("COLUMNS(A1:B4)", 2.0),
    ("SUM(MMULT(A1:B2,A2:B3))", 1056.0),
    ("MDETERM(E1:F2)", 10.0),            # |4 2; 7 6|
    ("INDEX(MINVERSE(E1:F2),1,1)", 0.6),
    ("INDEX(MINVERSE(E1:F2),2,1)", -0.7),
    ("SUM(TRANSPOSE(A1:B2))", 33.0),
    ("COLUMN(B5)", 2.0),
    ("ROW()", 50.0),
    ('IFERROR(VLOOKUP(9,A1:B3,2,FALSE),"yok")', "yok"),
    ("_xlfn.IFNA(MATCH(99,A1:A3,0),-1)", -1.0),
    ("ISERROR(A4+1)", True),
    ("ISNA(MATCH(99,A1:A3,0))", True),
    ("ISBLANK(Y1)", True),
    ('A4&"y"', "xy"),
])
def test_range_formulas(tr_locale, formula, expected):
    got = ev(formula, CELLS)
    if isinstance(expected, float):
        assert isinstance(got, float) and approx(got, expected), (formula, got)
    else:
        assert got == expected and type(got) is type(expected), (formula, got)


@pytest.mark.parametrize("formula", ["VLOOKUP(9,A1:B3,2,FALSE)", "MATCH(6,D1:D3,-1)", "LOOKUP(0,D1:D3,B1:B3)"])
def test_lookups_that_find_nothing(formula):
    got = ev(formula, CELLS)
    assert type(got) is XlError and got.code == "#N/A"


def test_zero_snapping_matches_excel():
    """Excel sets a final + / - to exactly 0 when the result is negligible against the operands,
    but not when the expression is wrapped in parentheses (documented examples)."""
    assert ev("0.1+0.2-0.3") == 0.0
    assert ev("(0.1+0.2-0.3)") == 5.551115123125783e-17
    assert ev("(4/3-1)*3-1") == 0.0                          # W. Kahan's example
    assert ev("((4/3-1)*3-1)") == -2.220446049250313e-16
    assert ev("1-0.9-0.1") == -2.7755575615628914e-17        # Microsoft KB 78113: not snapped
    assert ev("100*1.1-110") == 0.0


def test_implicit_intersection_and_array_formulas():
    cells = dict(CELLS)
    cells["H2"] = "=A1:A3"                    # ordinary formula: the cell of the same row
    cells["H9"] = "=A1:A3"                    # no row in common
    cells["I1"] = "=MAX(A1:A3*2)"             # entered with Ctrl+Shift+Enter
    cells["I2"] = "=MAX(A1:A3*2)"             # entered normally
    eng = mini_engine(cells, array=("I1",))
    assert eng.shared.value("S!H2") == 2.0
    assert eng.shared.value("S!H9").code == "#VALUE!"
    assert eng.shared.value("S!I1") == 6.0
    assert eng.shared.value("S!I2") == 4.0    # implicit intersection picks A2


def test_summation_is_left_to_right_like_excel():
    # a compensated sum would give exactly 1.0 here
    cells = {"A%d" % i: 0.1 for i in range(1, 11)}
    assert ev("SUM(A1:A10)", cells) == 0.9999999999999999
    assert ev("SUM(A1:A10)=1", cells) is True          # ... yet equal on 15 significant digits


def test_workday_with_holidays():
    cells = {"A1": 46335.0}                    # Monday 9 Nov 2026 is a holiday
    assert ev("WORKDAY(DATE(2026,11,6),1,A1:A1)", cells) == 46336.0


def test_empty_cells_count_as_zero_or_empty_text():
    assert ev("Y1+1") == 1.0
    assert ev('Y1&"a"') == "a"
    assert ev("Y1=0") is True
    assert ev('Y1=""') is True
    assert ev("ISBLANK(Y1)") is True
    eng = mini_engine({"A1": "=Y1"})           # a formula that returns an empty cell shows 0
    assert eng.shared.value("S!A1") == 0.0


# ---------------------------------------------------------------------------------------------- dynamic arrays
FILTER_CELLS = {"A1": 1, "A2": 2, "A3": 3, "A4": 4, "B1": "a", "B2": "b", "B3": "c", "B4": "d",
                "C1": True, "C2": False, "C3": 1, "C4": 0, "D1": 5, "D2": "=NA()", "D3": 7, "D4": "x"}


def spilled(calc, anchor, rows, cols=1):
    from tto.xl.model import COLS, a1, parse_a1
    r0, c0 = divmod(parse_a1(anchor), COLS)
    out = [[calc.value("S!" + a1((r0 + i) * COLS + c0 + j)) for j in range(cols)] for i in range(rows)]
    return [row[0] for row in out] if cols == 1 else out


def test_filter_spills_the_rows_whose_flag_is_true():
    """FILTER lists the quoted maturities on the Borsa swap sheet: true / non-zero keeps a row, the result
    spills below the formula and the cells after it stay empty."""
    cells = dict(FILTER_CELLS, F1="=FILTER(A1:B4,C1:C4)", I1="=FILTER(A1:A4,A1:A4>2)", A6=1, B6=0, C6=1, D6=0,
                 K1="=FILTER(A1:D1,A6:D6)", P1="=SUM(FILTER(A1:A4,A1:A4>1))")
    calc = mini_book(cells, dynamic=("F1", "I1", "K1")).engine.shared
    assert spilled(calc, "F1", 4, 2) == [[1.0, "a"], [3.0, "c"], [None, None], [None, None]]
    assert spilled(calc, "I1", 4) == [3.0, 4.0, None, None]             # the flags may be computed in place
    assert [calc.value("S!K1"), calc.value("S!L1"), calc.value("S!M1")] == [1.0, True, None]     # a row of flags picks columns
    assert calc.value("S!P1") == 9.0                                     # usable inside another function


def test_filter_without_a_match_and_with_a_wrong_shape():
    cells = dict(FILTER_CELLS, K1='=FILTER(A1:A4,B1:B4="z","yok")', L1='=FILTER(A1:A4,B1:B4="z")', M1="=FILTER(A1:A4,C1:C3)",
                 N1="=FILTER(A1:A4,D1:D4)")
    calc = mini_book(cells, dynamic=("K1", "L1", "M1", "N1")).engine.shared
    assert calc.value("S!K1") == "yok"                                   # if_empty
    assert calc.value("S!L1").code == "#CALC!"                           # nothing left and no if_empty
    assert calc.value("S!M1").code == "#VALUE!"                          # flags of another size
    assert calc.value("S!N1").code == "#N/A"                             # an error among the flags is the result


def test_a_spill_that_has_no_room_is_an_error():
    cells = dict(FILTER_CELLS, F1="=FILTER(A1:B4,C1:C4)", F2="dolu", I1="=FILTER(A1:B4,A1:A4=4)", I2="dolu")
    calc = mini_book(cells, dynamic=("F1", "I1")).engine.shared
    assert calc.value("S!F1").code == "#SPILL!" and calc.value("S!G1") is None and calc.value("S!F2") == "dolu"
    assert [calc.value("S!I1"), calc.value("S!J1")] == [4.0, "d"]         # one row fits above the occupied cell
    assert calc.value("S!I2") == "dolu"


@pytest.mark.parametrize("formula, expected", [
    ("AGGREGATE(9,6,D1:D4)", 12.0),                  # options 6: errors are left out (5, #N/A, 7, text)
    ("AGGREGATE(1,6,D1:D4)", 6.0),
    ("AGGREGATE(2,6,D1:D4)", 2.0),                   # COUNT
    ("AGGREGATE(3,6,D1:D4)", 3.0),                   # COUNTA
    ("AGGREGATE(4,6,D1:D4)", 7.0),
    ("AGGREGATE(5,6,D1:D4)", 5.0),
    ("AGGREGATE(6,6,A1:A4)", 24.0),
    ("AGGREGATE(9,6,A1:A2,A3:A4)", 10.0),            # reference form takes several ranges
    ("AGGREGATE(12,6,A1:A4)", 2.5),                  # MEDIAN
    ("AGGREGATE(14,6,A1:A4,2)", 3.0),                # LARGE
    ("AGGREGATE(15,6,A1:A4,1)", 1.0),                # SMALL
    ("AGGREGATE(16,6,A1:A4,0.9)", 3.7),              # PERCENTILE.INC
    ("AGGREGATE(17,6,A1:A4,1)", 1.75),               # QUARTILE.INC
    ("AGGREGATE(18,6,A1:A4,0.25)", 1.25),            # PERCENTILE.EXC
    ("AGGREGATE(19,6,A1:A4,2)", 2.5),                # QUARTILE.EXC
    ("AGGREGATE(16,6,D1:D4/1,0.5)", 6.0),            # array form: errors made by the calculation are left out too
    ("AGGREGATE(7,6,A1:A4)", 1.2909944487358056),    # STDEV.S
    ("AGGREGATE(8,6,A1:A4)", 1.118033988749895),     # STDEV.P
    ("AGGREGATE(10,6,A1:A4)", 1.6666666666666667),   # VAR.S
    ("AGGREGATE(11,6,A1:A4)", 1.25),                 # VAR.P
])
def test_aggregate(formula, expected):
    assert approx(ev(formula, FILTER_CELLS), expected)


@pytest.mark.parametrize("formula, code", [
    ("AGGREGATE(9,4,D1:D4)", "#N/A"),                # options 4: errors are not ignored
    ("AGGREGATE(13,6,A1:A4)", "#N/A"),               # MODE without a repeated value
    ("AGGREGATE(14,6,A1:A4,9)", "#NUM!"),            # k beyond the data
    ("AGGREGATE(18,6,A1:A4,0.1)", "#NUM!"),          # PERCENTILE.EXC outside 1/(n+1) … n/(n+1)
    ("AGGREGATE(1,6,B1:B4)", "#DIV/0!"),             # no numbers
    ("AGGREGATE(20,6,A1:A4)", "#VALUE!"),            # no such function number
    ("AGGREGATE(14,6,A1:A4)", "#VALUE!"),            # LARGE needs k
])
def test_aggregate_errors(formula, code):
    assert ev(formula, FILTER_CELLS).code == code
