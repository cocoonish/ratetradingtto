"""Every date shows as a date, and a tenor typed into any date counts from the right spot (tto/datecells.py).

* Which cells hold a date is read from the formulas (a type propagation): the rule on small workbooks of its own - a
  date plus days is a date, a date minus a date a number of days, a mix of dates and numbers left alone, a constant
  what its format says -, and on the four workbooks: it still finds exactly the cells ``datecells.SHOWN`` lists (a
  workbook imported again: this test says what moved).  Showing them as dates touches their format only - every value,
  formula and the rest of each cell's look as the file has them; each listed cell holds a date (a number of one, or a
  Bloomberg date as its text), never another number.
* The Forward DV01 table's Start (``Forward!O33 = +I2``, an accounting format in the workbook) is shown 04.11.2026 and is
  an input now, with its End (O34): "3m" there is three months from USDTRY's spot on USDTRY's calendar (a US holiday
  rolls it), "18m" in the End three half years from that Start - the pair from the formula (``=+I2``), the start from
  the workbook's own day count (``O35 = O34-O33``).  A cell made of EURTRY's spot counts from it (T+2, TRY + EUR).
* Upper and lower case are the same; "3m" in an amount cell is still 3.000.000; a number cell that is no date never
  takes a date; PPK's meeting dates keep their own rule; a scenario keeps the date, not what was typed; a pasted block
  counts cell by cell.

The service runs on the workbook's recorded market (03.11.2026: USDTRY spot 04.11, EURTRY spot 05.11) on a clock the
tests move; days planted in the desk's holiday lists make the calendars' rolling visible."""
from __future__ import annotations

import datetime as dt

import pytest

from conftest import cell
from tto import datecells as dcl
from tto.config import Settings
from tto.extras import SheetBuilder
from tto.service import EngineThread, Service
from tto.xl import numfmt
from tto.xl.engine import Clock
from tto.xl.model import COLS, Model, a1
from tto.xl.values import date_to_serial, serial_to_date

D = dt.date
RECORDED = D(2026, 11, 3)


def serial(d: dt.date) -> float:
    return float(date_to_serial(d))


def on(svc, day):
    """The dashboard on ``day`` (at noon): TODAY() and everything that follows it computed again."""
    svc.books["tto"].engine.clock.fixed = serial(day) + 0.5
    svc.et.call_at(EngineThread.WRITE, lambda: [b.engine.clock_tick() for b in svc.books.values()])
    svc.bump()


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    svc = Service(Settings(data_dir=str(tmp_path_factory.mktemp("tarihler")), mode="replay", history=False),
                  clock=Clock(serial(RECORDED) + 0.5))
    yield svc
    svc.stop()


def day(svc, ref, user=None, book="tto"):
    v = cell(svc, ref, user, book)
    return serial_to_date(v) if type(v) is float and 20000 < v < 80000 else v


def shown(svc, ref, user=None, book="tto"):
    """The cell as the page draws it (its text "t", kind "k" - "d" a date -, input kind "ik" …)."""
    b = svc.books[book]
    si, rc = b.cell(ref)
    loc = numfmt.get_locale("tr")
    return svc.et.call(lambda: svc.renderers[book].cell(svc._calc(user, b), si, *divmod(rc, COLS), loc,
                                                          svc._overlay(user, b) if user else None))


def typed(svc, user, ref, text, adhoc=False):
    """Type ``text`` into ``ref``: (the date stored - or what is -, the answer's shortcut note, the errors)."""
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": text}], allow_adhoc=adhoc)
    return day(svc, ref, user), (res.get("shortcuts") or {}).get(ref), res["errors"]


def holidays(svc, user, ccy, extra):
    """Plant days in a currency's holiday list; returns the list as it was (to put it back)."""
    items = svc.holidays()["lists"][ccy]["items"]
    svc.set_holidays(user, items + [{"date": d.strftime("%d.%m.%Y"), "name": "Deneme"} for d in extra], ccy)
    return items


# ---------------------------------------------------------------------------------------------- the rule
def _model(cells):
    """A workbook of one sheet: ``{"A1": (value or "=formula", number format)}``."""
    m = Model()
    m.xfs.append(["General", False, None, None, None, False])         # (Excel's own first style: General)
    m.numfmts.append("General")
    m.xf_flags.append(0)
    b = SheetBuilder(m, "S")
    for addr, (value, fmt) in cells.items():
        b.set(addr, value, fmt=fmt)
    return m


DATE, GEN, ACC = "dd.mm.yyyy", "General", '_-* #,##0.0000_-;\\-* #,##0.0000_-;_-* "-"??_-;_-@_-'


@pytest.mark.parametrize("formula, kind", [
    ("=A1", dcl.D), ("=+A1", dcl.D), ("=A1+7", dcl.D), ("=7+A1", dcl.D), ("=A1-2", dcl.D), ("=N(A1)", dcl.D),
    ("=ROUND(A1,0)", dcl.D), ("=A2-A1", dcl.N), ("=(A2-A1)/365", dcl.N), ("=A1*1", dcl.N), ("=-A1", dcl.N),
    ("=A1+A2", dcl.U), ("=EDATE(A1,3)", dcl.D), ("=EDATE(A1,3)-A1", dcl.N), ("=WORKDAY(A1,1)", dcl.D),
    ("=EOMONTH(A1,0)", dcl.D), ("=DATE(2027,1,4)", dcl.D), ("=TODAY()", dcl.D), ("=NOW()", dcl.U),
    ("=YEARFRAC(A1,A2)", dcl.N), ("=YEAR(A1)", dcl.N), ("=TEXT(A1,\"dd.mm.yy\")", dcl.X),
    ('=IF(B1="","",A1+7)', dcl.D), ("=IF(B1,A1,A2)", dcl.D), ("=IF(B1,A1,0)", dcl.U), ("=IF(B1,A1,B2)", dcl.U),
    ("=IFERROR(A1,\"\")", dcl.D), ("=MAX(A1,A2)", dcl.D), ("=MAX(A1,0)", dcl.U), ("=MIN(A1:A2)", dcl.D),
    ("=CHOOSE(B1,A1,A2)", dcl.D), ("=INDEX(A1:A2,B1)", dcl.D), ("=INDEX(A1:B2,1,2)", dcl.N),
    ("=VLOOKUP(B1,A1:B2,1,FALSE)", dcl.D), ("=VLOOKUP(B1,A1:B2,2,FALSE)", dcl.N), ("=B2", dcl.N),
    ("=C1", dcl.D), ("=C2", dcl.N), ('=_xll.BDP("TRY Curncy","SETTLE_DT")', dcl.D),
    ('=_xll.BDP("X Corp","MATURITY")', dcl.D), ('=_xll.BDP("X Corp","PX_LAST")', dcl.U),
    ("=LET(x,A1,x+7)", dcl.D), ("=LET(x,A1,y,A2,y-x)", dcl.N),
])
def test_what_the_rule_calls_a_date(formula, kind):
    """A1 / A2 dates, B1 / B2 numbers (B2 46000: a number, whatever its size), C1 a General cell holding =A1 (a date by
    its formula), C2 a constant 46000 in a General cell (a number)."""
    m = _model({"A1": (46330.0, DATE), "A2": (46422.0, DATE), "B1": (1.0, GEN), "B2": (46000.0, GEN),
                "C1": ("=A1", GEN), "C2": (46000.0, GEN), "E1": (formula, ACC)})
    assert dcl.DateCells(m).kind(0, m.cell_ref("S!E1")[1]) == kind, formula


def test_a_cycle_a_long_chain_and_a_wide_array_are_not_guessed():
    m = _model({"A1": ("=A2+1", GEN), "A2": ("=A1+1", GEN), "B1": (46330.0, DATE)})
    sb = SheetBuilder(m, "S")
    for r in range(2, 3002):                                     # 3 000 cells, each the one above plus a day
        sb.set("B%d" % r, "=B%d+1" % (r - 1), fmt=GEN)
    sh = m.sheet("S")
    dc = dcl.DateCells(m)
    assert dc.kind(0, m.cell_ref("S!A1")[1]) == dcl.U
    assert dc.kind(0, m.cell_ref("S!B3001")[1]) == dcl.D
    # an array of several columns (Bloomberg's cash flows: a date, an amount, an amount): its cells are not known
    sb.set("F1", '=_xll.BDS("X Corp","DES_CASH_FLOW")', fmt=DATE, array=True)
    sh.arr[m.cell_ref("S!F1")[1]] = (1, 6, 3, 8)
    for addr in ("G1", "H1", "F2"):
        sh.members[m.cell_ref("S!" + addr)[1]] = m.cell_ref("S!F1")[1]
        sh.consts[m.cell_ref("S!" + addr)[1]] = 1000000.0
    assert [dcl.DateCells(m).kind(0, m.cell_ref("S!" + a)[1]) for a in ("F1", "G1", "H1", "F2")] == [dcl.D, dcl.U, dcl.U, dcl.U]


def test_the_rule_still_finds_exactly_the_listed_cells():
    """What ``datecells.SHOWN`` lists is what the rule finds in the four workbooks (as the dashboard loads them) - no
    more, no less.  A workbook imported again that moves a date: this fails with what moved; ``python -m tto.datecells``
    prints the new list."""
    for book_id in ("tto", "sofr", "borsa", "asw"):
        model = dcl.model_of(book_id)
        assert model is not None, book_id
        got, want = dcl.found(model), list(dcl.SHOWN.get(book_id, ()))
        cells_got, cells_want = set(dcl.cells_of(model, got)), set(dcl.cells_of(model, want))
        new = dcl.compact(model, cells_got - cells_want)
        gone = dcl.compact(model, cells_want - cells_got)
        assert not new and not gone, "%s: yeni tarih %s; artık tarih değil %s" % (book_id, new, gone)


def test_the_listed_cells():
    """The list itself, pinned: the Forward DV01 table's Start, the Forward sheet's settlement dates (Bloomberg's
    SETTLE_DT), DİBS RV's maturities / coupon / value dates, VİOP's contract dates, the auction's dates, DİBS ASW's
    maturities - 1 263 cells."""
    n = {}
    for book_id, boxes in dcl.SHOWN.items():
        model = dcl.model_of(book_id)
        n[book_id] = len(dcl.cells_of(model, boxes))
    assert n == {"tto": 1213, "asw": 50}
    tto = dcl.SHOWN["tto"]
    for box in ("Forward!O33", "Forward!V75", "Forward!F8:F21", "DİBS RV!DC5:DC54", "DİBS RV!DE5:DE54",
                "DİBS RV!CT5:CT54", "EK_IHALE!T7", "VIOP!L5:W5", "OIS_MAIN!W2"):
        assert box in tto, box
    assert dcl.SHOWN["asw"] == ("ASW!AT7:AT56",)


def test_showing_them_as_dates_changes_their_format_and_nothing_else():
    """Every value, formula, array, recorded value of the workbook stays; a listed cell keeps its bold, colours, fill
    and alignment - only its number format becomes dd.mm.yyyy; no other cell's look changes."""
    model = dcl.model_of("tto")
    looks = {(s.index, rc): list(model.xfs[x]) for s in model.sheets for rc, x in s.styles.items()}
    before = [(dict(s.consts), dict(s.fml), dict(s.arr), dict(s.members), dict(s.cached)) for s in model.sheets]
    templates = list(model.templates)
    dates, moved = dcl.apply("tto", model)
    assert moved == [] and isinstance(dates, dcl.DateCells)
    assert [(dict(s.consts), dict(s.fml), dict(s.arr), dict(s.members), dict(s.cached)) for s in model.sheets] == before
    assert model.templates == templates
    listed = set(dcl.cells_of(model, dcl.SHOWN["tto"]))
    changed = set()
    for s in model.sheets:
        for rc, x in s.styles.items():
            now = list(model.xfs[x])
            was = looks.get((s.index, rc), ["General", 0, None, None, None, 0])
            if now != was:
                changed.add((s.index, rc))
                assert now[0] == "dd.mm.yyyy" and now[1:] == was[1:], (s.name, a1(rc), was, now)
    assert changed == {k for k in listed if not numfmt.is_date_format(looks.get(k, ["General"])[0])}


def test_each_listed_cell_holds_a_date_and_is_drawn_as_one(desk):
    """A number in a listed cell is a date (a serial of 1954 - 2119) and is drawn dd.mm.yyyy; a text (Bloomberg's
    date as it sends it, VİOP's "Spot") stays as it is; nothing else."""
    svc = desk
    on(svc, RECORDED)
    loc = numfmt.get_locale("tr")
    for book_id, boxes in dcl.SHOWN.items():
        b = svc.books[book_id]
        r = svc.renderers[book_id]

        def run():
            out = []
            for si, rc in dcl.cells_of(b.model, boxes):
                v = b.engine.shared.get(si, *divmod(rc, COLS))
                out.append((si, rc, v, r.cell(b.engine.shared, si, *divmod(rc, COLS), loc)))
            return out

        for si, rc, v, drawn in svc.et.call(run):
            where = "%s!%s" % (b.model.sheets[si].name, a1(rc))
            assert type(v) in (str, type(None)) or type(v).__name__ == "XlError" or 20000 < v < 80000, (where, v)
            if type(v) is float:
                assert drawn["t"] == serial_to_date(v).strftime("%d.%m.%Y") and drawn["k"] == "d", (where, drawn)


def test_a_date_input_of_the_page_definitions_is_shown_as_one(desk):
    """The empty rows at the end of a holiday list (DİBS ASW's copy of the TRY list, the SOFR book's US list) were
    General: a day typed there showed 46.000-odd.  A list of days kept as text (VİOP Target's contracts) keeps its own."""
    svc = desk
    for book_id, ref in (("asw", "ASW!LR154"), ("asw", "ASW!LR200"), ("sofr", "SOFR_FOMC!BO70")):
        b = svc.books[book_id]
        si, rc = b.cell(ref)
        assert numfmt.is_date_format(b.model.xfs[b.model.sheets[si].styles.get(rc, 0)][0]), ref
    b = svc.books["tto"]
    si, rc = b.cell("VIOP!M331")
    assert not numfmt.is_date_format(b.model.xfs[b.model.sheets[si].styles.get(rc, 0)][0])


# ---------------------------------------------------------------------------------------------- where a typed date counts
def test_the_formulas_say_where_a_date_counts_from(desk):
    """The pair of the dates a cell is made of, its start from the workbook's own day count - a spot date is no start
    (MASA!E60 counts its days from C60 and from the OIS spot date: C60)."""
    svc = desk
    b = svc.books["tto"]

    def ctx(ref):
        pair, start = svc.et.call(svc._date_context, b, *b.cell(ref))
        return pair, (None if start is None else "%s!%s" % (b.model.sheets[start[0]].name, a1(start[1])))

    assert ctx("Forward!O33") == ("USDTRY", None)                  # =+I2
    assert ctx("Forward!O34") == ("USDTRY", "Forward!O33")         # =+D2 (USDTRY's value date); O35 = O34-O33
    assert ctx("EK_FWD!G101") == ("EURTRY", None)                  # =DATE(YEAR(Forward!$K$2) …)
    assert ctx("Forward!AK6") == ("EURTRY", "Forward!AK5")          # (as its page definition says too)
    assert ctx("MASA!E60") == ("USDTRY", "MASA!C60")
    assert ctx("DV01_RISK!C112") == ("TRY", None)                   # =WORKDAY(SPOTDATE,-2,…)
    assert ctx("EK_FWD!O68")[0] is None                             # USDTRY's or EURTRY's spot, as the row says


def test_the_start_is_shown_as_a_date_and_takes_tenors_from_usdtrys_spot(desk):
    """The trader's table: Start shown 04.11.2026 (it was 46.330,0000); "3m" there is USDTRY's spot + 3 months on
    USDTRY's calendar - 04.02.2027, planted a US holiday: the next business day, 05.02.2027 (the TRY money market would
    stay on the 4th) -, "18m" in the End counts from that Start: 05.08.2028 is a Saturday, 07.08.2028; N follows."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Tarih Start")["user"]
    usd = holidays(svc, u, "USD", [D(2027, 2, 4)])
    try:
        before = shown(svc, "Forward!O33", u)
        assert before["t"] == "04.11.2026" and before["k"] == "d" and before["ik"] == "date" and before["i"] == "u"
        assert shown(svc, "Forward!O35", u)["k"] == "n"                     # N: a number of days, as before
        got, note, errors = typed(svc, u, "Forward!O33", "3m")
        assert errors == [] and got == D(2027, 2, 5)
        assert note == {"typed": "3m", "date": serial(D(2027, 2, 5)), "text": "05.02.2027"}
        assert shown(svc, "Forward!O33", u)["t"] == "05.02.2027"
        got, note, errors = typed(svc, u, "Forward!O34", "18m")
        assert errors == [] and got == D(2028, 8, 7) and note["text"] == "07.08.2028"
        assert cell(svc, "Forward!O35", u) == (D(2028, 8, 7) - D(2027, 2, 5)).days == 549
        # the TRY money market's own cell does not see the US holiday
        assert typed(svc, u, "OIS_MAIN!B123", "3m")[0] == D(2027, 2, 4)
        # blanked: back to the formulas (the spot date, the value date)
        svc.set_inputs(u, "tto", [{"ref": "Forward!O33", "value": ""}, {"ref": "Forward!O34", "value": ""}])
        assert day(svc, "Forward!O33", u) == D(2026, 11, 4) and day(svc, "Forward!O34", u) == day(svc, "Forward!D2", u)
    finally:
        svc.set_holidays(u, usd, "USD")
        svc.reset_inputs(u, "tto")


def test_a_us_holiday_in_the_way_of_the_start(desk):
    """Friday 23.10.2026, USDTRY spot Monday 26.10: one month on is Thanksgiving - the Start takes Friday 27.11 (a TRY
    money market date stays on Thursday the 26th)."""
    svc = desk
    u = svc.login("Tarih Thanksgiving")["user"]
    try:
        on(svc, D(2026, 10, 23))
        assert day(svc, "Forward!O33", u) == D(2026, 10, 26)
        assert typed(svc, u, "Forward!O33", "1m")[0] == D(2026, 11, 27)
        assert typed(svc, u, "OIS_MAIN!B123", "1m")[0] == D(2026, 11, 26)
    finally:
        svc.reset_inputs(u, "tto")
        on(svc, RECORDED)


def test_a_cell_made_of_eurtrys_spot_counts_from_it(desk):
    """EK_FWD!G101 (the EURTRY matrix's spot date, typed over: "Elle değer") is made of Forward!K2: "6m" is EURTRY's
    spot 05.11.2026 + 6 months, 05.05.2027 - planted a TARGET2 holiday, 06.05.2027; the matrix's dated row (declared
    EURTRY) the same."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Tarih EURTRY")["user"]
    eur = holidays(svc, u, "EUR", [D(2027, 5, 5)])
    try:
        got, note, errors = typed(svc, u, "EK_FWD!G101", "6m", adhoc=True)
        assert errors == [] and got == D(2027, 5, 6) and note["typed"] == "6m"
        assert typed(svc, u, "EK_FWD!B104", "6M")[0] == D(2027, 5, 6)
        assert typed(svc, u, "Forward!O33", "6m")[0] == D(2027, 5, 4)      # USDTRY: its own spot, the EUR day no holiday
    finally:
        svc.set_holidays(u, eur, "EUR")
        svc.reset_inputs(u, "tto")


@pytest.mark.parametrize("lower, upper", [
    ("3m", "3M"), ("3a", "3A"), ("18m", "18M"), ("1y", "1Y"), ("2w", "2W"), ("2h", "2H"), ("on", "ON"), ("tn", "TN"),
    ("sn", "SN"), ("ay sonu", "AY SONU"), ("imm", "IMM"), ("+5", "+5"),
])
def test_lower_and_upper_case_are_the_same(desk, lower, upper):
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Tarih Harf")["user"]
    try:
        a, b = typed(svc, u, "Forward!O33", lower), typed(svc, u, "Forward!O33", upper)
        assert a[2] == b[2] == [] and a[0] == b[0] and type(a[0]) is D, (lower, a, b)
    finally:
        svc.reset_inputs(u, "tto")


def test_3m_in_an_amount_is_three_million_and_a_number_never_a_date(desk):
    """The DV01 table's Tutar takes "3m" as 3.000.000, as ever; its N (a number of days) typed over with "3m" keeps the
    text - it is no date -, and so does a rate."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Tarih Tutar")["user"]
    try:
        assert typed(svc, u, "Forward!O45", "3m") == (3e6, None, [])
        assert typed(svc, u, "Forward!O45", "3M") == (3e6, None, [])
        assert typed(svc, u, "Forward!O35", "3m", adhoc=True) == ("3m", None, [])
        assert typed(svc, u, "Forward!AH9", "3m") == ("3m", None, [])
    finally:
        svc.reset_inputs(u, "tto")


def test_meeting_dates_keep_their_own_rule(desk):
    """A PPK meeting's date is the calendar's: "3m" there is refused as before - no meeting moves; no newly dated cell
    is a cell that moves with its meeting."""
    from tto import meetings as mt
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Tarih PPK")["user"]
    try:
        before = cell(svc, "OIS_MAIN!P10", u)
        res = svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!P10", "value": "3m"}])
        assert res["errors"] and "shortcuts" not in res and cell(svc, "OIS_MAIN!P10", u) == before
    finally:
        svc.reset_inputs(u, "tto")
    for book_id, boxes in dcl.SHOWN.items():
        b = svc.books[book_id]
        for si, rc in dcl.cells_of(b.model, boxes):
            assert mt.place(b, si, rc) is None, (book_id, a1(rc))


def test_a_scenario_keeps_the_date_and_a_pasted_block_counts_cell_by_cell(desk):
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Tarih Senaryo")["user"]
    try:
        res = svc.paste(u, "tto", "Forward!O33", "3m\r\n18m\r\n")
        assert res["errors"] == [] and set(res["shortcuts"]) == {"Forward!O33", "Forward!O34"}
        assert day(svc, "Forward!O33", u) == D(2027, 2, 4) and day(svc, "Forward!O34", u) == D(2028, 8, 4)
        svc.save_scenario(u, "tarih")
        svc.reset_inputs(u, "tto")
        assert day(svc, "Forward!O33", u) == D(2026, 11, 4)
        svc.load_scenario(u, "tarih")
        assert cell(svc, "Forward!O33", u) == serial(D(2027, 2, 4)) and day(svc, "Forward!O34", u) == D(2028, 8, 4)
    finally:
        svc.reset_inputs(u, "tto")
