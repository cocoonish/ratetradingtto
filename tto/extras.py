"""The dashboard's own additions to the workbooks.

Everything here is written as ordinary Excel formulas and added to the workbook model when it is loaded,
so the additions are calculated by the same engine as the workbook, follow its inputs and live data, show
their formula in the status bar and can be copied back into Excel.  The model files stay a pure import of
the Excel files (parity and reference tests read those).

* ``EK_FWD``  (TRY workbook)  forward quotes from OIS + spread, with separate spreads for bid and ask, and
                               the way back: the OIS spread of swap points typed by hand
* ``EK_XAU``  (TRY workbook)  gold forwards from the gold swap rate (``XAUSR…``) instead of ``BFXFORWARD``
                               (which the Bloomberg API does not offer), the VİOP gold tables and the Forward
                               gold strip fed from them, and a calculator for the VİOP XAUTRY contracts: the
                               price at a given rate and the rates a price implies, every driver of which can
                               be typed by hand (dates, spots, rates, the gold forward, the VİOP price)
* ``EK_VIOP`` (TRY workbook)  a history of the VİOP contracts for two charts: the implied TRY rate of up to six
                               contracts and their spread over OIS, day by day, with the VİOP sheet's own
                               formulas and a window of its own
* ``EK_IHALE`` (TRY workbook) the Treasury auction: the dirty price to bid for three bonds (Bloomberg's accrued
                               interest at the auction's value date) and where the bids stand once it is over
* ``EK_RET``  (TRY workbook)  the RET tenors' rates on the OIS sheet's PPK scenario curves (the fair value RET's
                               "Senaryo") and on a scenario without steps (the reference its VİOP / offshore bases move by)
* ``EK_PPK``  (TRY workbook)  the way back of the OIS sheet's meeting windows: a meeting swap's rate or an MPC spread
                               typed -> the PPK step it prices (Broker Chat's implied step); typed values go with their meeting
* ``bu``      (Borsa workbook) O/N equivalents of the implied TRY rates of the BIST swap quotes
* ``Sheet2``  (Borsa workbook) the list of quoted maturities keeps only quotes with an order behind them
* ``EK_TATIL`` (Borsa workbook) a copy of the desk's TRY holiday list and the T+1 value date on it

The last two change formulas of the workbook itself.  The workbook lists a maturity when its bid or ask size
"is a number"; over the API Bloomberg answers a size of 0 - and an old price, the same on both sides - for a
maturity nobody is quoting, where Excel's real-time link shows "#N/A N/A".  Listed by the workbook's rule, the
page was full of quotes that do not exist.  And the workbook counts the T+1 quotes' value date over weekends only:
on the eve of a TRY holiday their maturities were a day early (``bu`` Q9:Q54 count from the date on the copy now).

Two more change formulas of the TRY workbook, each for a reason given where it is done:

* ``EK_CARRY``  the carry of the Carry & Roll sheet along a TLREF path of one's choice (the Motor sheet's carry
                engine is pointed at it; the S1 cells it compounded stay for the OIS sheet's own pricing)
* ``Motor``     the curve's nodes count their days with the desk's calendar instead of Bloomberg's maturities

And one more for the value dates: ``EK_TATIL`` holds the USD and EUR holiday lists beside the workbook's TRY list,
and the USDTRY / EURTRY spot dates and the FX tenors counted from them skip the holidays of both currencies of the pair;
the TRY OIS / TLREF spot date (OIS_MAIN!B2) is the next business day of the TRY list (Bloomberg's dates beside them).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import aswfx
from .xl.model import COLS, Model, Sheet, parse_a1, parse_range
from .xl.tokenizer import index_to_col, to_template
from .xl.values import date_to_serial

NUM2 = "#,##0.00"
NUM4 = "#,##0.0000"
INT0 = "#,##0"
DATE = "dd.mm.yyyy"
INPUT_FILL = "FFF2CC"            # the workbook's own colour for cells the trader types into
HEAD_FILL = "1F3864"
NOTE_COLOR = "7F7F7F"


class SheetBuilder(object):
    """Write cells into a (new or existing) sheet of a model."""

    def __init__(self, model: Model, name: str):
        self.model = model
        if name in model.sheet_index:
            self.sheet: Sheet = model.sheet(name)
        else:
            self.sheet = model.add_sheet(name)
        self._templates: Dict[str, int] = {t: i for i, t in enumerate(model.templates)}
        self._xfs: Dict[Tuple[Any, ...], int] = {tuple(x): i for i, x in enumerate(model.xfs)}

    # ------------------------------------------------------------------ styles
    def _xf(self, fmt: Optional[str], bold: bool, color: Optional[str], fill: Optional[str], align: Optional[str]) -> int:
        key = (fmt or "General", bool(bold), color, fill, align, False)
        i = self._xfs.get(key)
        if i is None:
            i = len(self.model.xfs)
            self.model.xfs.append(list(key))
            self.model.numfmts.append(key[0])
            self.model.xf_flags.append(1 if bold else 0)
            self._xfs[key] = i
        return i

    def _template(self, formula: str, r: int, c: int) -> int:
        tpl = to_template(formula.lstrip("="), r, c)
        tid = self._templates.get(tpl)
        if tid is None:
            tid = len(self.model.templates)
            self.model.templates.append(tpl)
            self._templates[tpl] = tid
        return tid

    # ------------------------------------------------------------------ cells
    def set(self, addr: str, value: Any, fmt: Optional[str] = None, bold: bool = False, color: Optional[str] = None,
            fill: Optional[str] = None, align: Optional[str] = None, array: bool = False, like: Optional[str] = None) -> None:
        """A constant, or a formula when ``value`` is text starting with ``=`` (A1 notation, as in Excel).

        ``like`` gives the cell the look (number format, bold, colours) of an existing cell of the sheet.
        """
        rc = parse_a1(addr)
        r, c = divmod(rc, COLS)
        sh = self.sheet
        sh.consts.pop(rc, None)
        sh.fml.pop(rc, None)
        if isinstance(value, str) and value.startswith("="):
            sh.fml[rc] = self._template(value, r, c)
            if array:
                sh.arr[rc] = (r, c, r, c)
        elif value is not None:
            sh.consts[rc] = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
        xf = sh.styles.get(parse_a1(like), 0) if like else self._xf(fmt, bold, color, fill, align)
        if xf:
            sh.styles[rc] = xf
        else:
            sh.styles.pop(rc, None)
        sh.max_row = max(sh.max_row, r)
        sh.max_col = max(sh.max_col, c)

    def row(self, addr: str, values, **style) -> None:
        """Values / formulas from ``addr`` rightwards."""
        rc = parse_a1(addr)
        r, c = divmod(rc, COLS)
        for k, v in enumerate(values):
            self.set("%s%d" % (index_to_col(c + k), r), v, **style)

    def head(self, addr: str, labels) -> None:
        self.row(addr, labels, bold=True, fill=HEAD_FILL, color="FFFFFF", align="center")

    def title(self, addr: str, text: str) -> None:
        """The caption row of a block (the page lifts it out of the table as the panel title)."""
        self.set(addr, text, bold=True)

    def note(self, addr: str, text: str) -> None:
        self.set(addr, text, color=NOTE_COLOR)

    def input(self, addr: str, value: Any = None, fmt: Optional[str] = None, **style) -> None:
        """A cell the trader types into (declared as an input by the page definition)."""
        style.setdefault("fill", INPUT_FILL)
        self.set(addr, value, fmt=fmt, **style)

    def dropdown(self, addr: str, items: Sequence[str]) -> None:
        """A list validation, as Excel's "data validation / list" with literal items."""
        self.sheet.validations.append({"sqref": addr, "type": "list", "formula1": '"%s"' % ",".join(items)})

    def list_from(self, addr: str, source: str) -> None:
        """A list validation whose items are the cells of a range (``"EK_VFRA!$A$3:$A$6"``): whatever they hold now."""
        self.sheet.validations.append({"sqref": addr, "type": "list", "formula1": source})

    def recorded(self, addr: str, value: Any) -> None:
        """The value Excel saved for this (add-in) cell: offline the cell is frozen at it, like every other
        Bloomberg cell of the workbook."""
        if value is not None:
            self.sheet.cached[parse_a1(addr)] = value

    def patch(self, addr: str, formula: str) -> None:
        """Replace the formula of an existing cell, keeping its format and array flag."""
        rc = parse_a1(addr)
        r, c = divmod(rc, COLS)
        self.sheet.consts.pop(rc, None)
        self.sheet.fml[rc] = self._template(formula, r, c)

    def fill_down(self, addr: str, last: int) -> None:
        """Excel's fill down: the cell's formula (its references relative to the row move with it), constant and look,
        copied to every row below it down to ``last`` - one template for all of them, no text to read again."""
        rc0 = parse_a1(addr)
        r0, c = divmod(rc0, COLS)
        sh = self.sheet
        for r in range(r0 + 1, last + 1):
            rc = r * COLS + c
            sh.consts.pop(rc, None)
            sh.fml.pop(rc, None)
            if rc0 in sh.fml:
                sh.fml[rc] = sh.fml[rc0]
            elif rc0 in sh.consts:
                sh.consts[rc] = sh.consts[rc0]
            if rc0 in sh.styles:
                sh.styles[rc] = sh.styles[rc0]
            else:
                sh.styles.pop(rc, None)
        sh.max_row = max(sh.max_row, last)


def formula_of(model: Model, sheet: str, addr: str) -> str:
    """The A1 text (without ``=``) of an existing formula cell - to reuse a workbook formula elsewhere."""
    from .xl.unparse import to_a1
    sh = model.sheet(sheet)
    rc = parse_a1(addr)
    r, c = divmod(rc, COLS)
    return to_a1(model.templates[sh.fml[rc]], r, c)


def recorded_value(model: Model, sheet: str, addr: str) -> Any:
    """What Excel saved in a formula cell (``None`` when nothing was saved)."""
    return model.sheet(sheet).cached.get(parse_a1(addr))


_LOCAL_REF = re.compile(r"(?<![A-Za-z0-9_!$.':])\$?[A-Z]{1,3}\$?\d+(?![A-Za-z0-9_(])")


def transplant(text: str, replace: Dict[str, str]) -> str:
    """A formula of another sheet, to be used on a new sheet: the references to that sheet's own cells are
    swapped for cells of the new sheet (``replace``).  A reference that is left unqualified would silently
    point at the wrong sheet, so that is an error."""
    for old, new in replace.items():
        text = text.replace(old, new)
    kept = set(replace.values())
    left = [m.group(0) for m in _LOCAL_REF.finditer(text) if m.group(0) not in kept]
    if left:
        raise ValueError("unqualified references left in a transplanted formula: %s" % ", ".join(sorted(set(left))[:8]))
    return text


def lin(x: str, xs: str, ys: str, n: Any) -> str:
    """The workbook's own linear interpolation pattern (flat outside the nodes), as an Excel expression.
    ``n`` is the number of nodes: a number, or a cell that holds it."""
    m = "MATCH(%s,%s,1)" % (x, xs)
    return ("IF(%(x)s<=INDEX(%(xs)s,1),INDEX(%(ys)s,1),IF(%(x)s>=INDEX(%(xs)s,%(n)s),INDEX(%(ys)s,%(n)s),"
            "INDEX(%(ys)s,%(m)s)+(%(x)s-INDEX(%(xs)s,%(m)s))*(INDEX(%(ys)s,%(m)s+1)-INDEX(%(ys)s,%(m)s))"
            "/(INDEX(%(xs)s,%(m)s+1)-INDEX(%(xs)s,%(m)s))))") % {"x": x, "xs": xs, "ys": ys, "n": n, "m": m}


def apply(book_id: str, model: Model) -> List[str]:
    """Add the dashboard's own sheets / cells to a freshly loaded model.

    Each addition is written against particular cells of its workbook.  A workbook whose layout has changed
    must still load, so every addition first checks that the cells it builds on are what it expects and is
    left out otherwise.  Returns what was left out (``["EK_XAU: ..."]``; empty when everything fits).
    """
    problems: List[str] = []
    for name, check, build in _BUILDERS.get(book_id, ()):
        try:
            check(model)
        except Exception as exc:  # noqa: BLE001 - whatever is wrong: this addition does not fit this file
            problems.append("%s: %s" % (name, str(exc) or type(exc).__name__))
            continue
        build(model)
    return problems


def _need_sheets(model: Model, *names: str) -> None:
    missing = [n for n in names if n not in model.sheet_index]
    if missing:
        raise ValueError("sayfa yok: %s" % ", ".join(missing))


def _need_formula(model: Model, sheet: str, addr: str, containing: str = "") -> str:
    """The formula of a cell the addition builds on (an error when it is not the formula expected there)."""
    try:
        text = formula_of(model, sheet, addr)
    except KeyError:
        raise ValueError("%s!%s bir formül değil" % (sheet, addr)) from None
    if containing and containing.upper() not in text.upper():
        raise ValueError("%s!%s beklenen formül değil (%s yok)" % (sheet, addr, containing))
    return text


def overnight(rate: str, days: str, basis: int = 360) -> str:
    """O/N equivalent of a simple rate over ``days`` on its own day count - ACT/360 (``basis`` 360, the BIST swaps') or
    ACT/365 (365, TRY OIS: Broker Chat's ``Service._overnight``): basis·((1 + r·g/basis)^(1/g) − 1)."""
    return ('IF(AND(ISNUMBER(%(r)s),ISNUMBER(%(d)s),N(%(d)s)>0),%(b)d*((1+%(r)s*%(d)s/%(b)d)^(1/%(d)s)-1),"")'
            % {"r": rate, "d": days, "b": basis})


# ---------------------------------------------------------------------------------------------- Borsa swap
def _borsa_check(model: Model) -> None:
    _need_sheets(model, "bu")
    sh = model.sheet("bu")
    for addr, text in (("H8", "BID %"), ("M8", "ASK %"), ("U8", "BID %"), ("Z8", "ASK %")):
        if sh.consts.get(parse_a1(addr)) != text:
            raise ValueError("bu!%s başlığı '%s' değil" % (addr, text))
    for addr in ("E9", "H9", "M9", "R9", "U9", "Z9"):
        _need_formula(model, "bu", addr)


def _borsa(model: Model) -> None:
    """BIST swap quotes: O/N equivalents of the implied TRY rates, and names for the per-day point columns."""
    b = SheetBuilder(model, "bu")
    # T+0 block: E = days, H = bid %, M = ask %, I / L = points per day (no caption in the workbook)
    # T+1 block: R = days, U = bid %, Z = ask %, V / Y = points per day
    for days, bid, ask, per_bid, per_ask, on_bid, on_ask in (("E", "H", "M", "I", "L", "O", "P"),
                                                             ("R", "U", "Z", "V", "Y", "AB", "AC")):
        b.set(per_bid + "8", "BID SP / gün", like=bid + "8")
        b.set(per_ask + "8", "ASK SP / gün", like=bid + "8")
        b.set(on_bid + "8", "BID O/N", like=bid + "8")
        b.set(on_ask + "8", "ASK O/N", like=bid + "8")
        for r in range(9, 55):
            b.set("%s%d" % (on_bid, r), "=" + overnight("%s%d" % (bid, r), "%s%d" % (days, r)), like=bid + "9")
            b.set("%s%d" % (on_ask, r), "=" + overnight("%s%d" % (ask, r), "%s%d" % (days, r)), like=ask + "9")


#: Sheet2 of the Borsa workbook: rows 6-366 repeat rows 4-364 of Sheet1 when the maturity is quoted
BORSA_ROWS = (6, 366)
#: per block: (columns of both sides, bid-side columns, ask-side columns, bid size column, ask size column)
BORSA_BLOCKS = ((("B", "C", "H"), ("D", "E", "K", "L"), ("F", "G", "I", "J"), "D", "G"),        # T+0 (BFX0)
                (("N", "O", "T"), ("P", "Q", "W", "X"), ("R", "S", "U", "V"), "P", "S"))        # T+1 (BFX1)


def _borsa_filter_check(model: Model) -> None:
    _need_sheets(model, "bu", "Sheet1", "Sheet2")
    s1 = model.sheet("Sheet1")
    for addr, text in (("D3", "BID_SIZE"), ("E3", "BID"), ("F3", "ASK"), ("G3", "ASK_SIZE"),
                       ("P3", "BID_SIZE"), ("Q3", "BID"), ("R3", "ASK"), ("S3", "ASK_SIZE")):
        if s1.consts.get(parse_a1(addr)) != text:
            raise ValueError("Sheet1!%s başlığı '%s' değil" % (addr, text))
    first, last = BORSA_ROWS
    for both, bid, ask, bid_size, ask_size in BORSA_BLOCKS:
        for r in (first, last):
            for col in both + bid + ask:
                want = "Sheet1!%s%d" % (col, r - 2)
                text = _need_formula(model, "Sheet2", "%s%d" % (col, r), want)
                if "ISNUMBER(Sheet1!$%s%d)" % (bid_size, r - 2) not in text or \
                        "ISNUMBER(Sheet1!$%s%d)" % (ask_size, r - 2) not in text:
                    raise ValueError("Sheet2!%s%d beklenen süzgeç formülü değil" % (col, r))
    for addr, part in (("I9", "J9=0"), ("L9", "K9=0"), ("V9", "W9=0"), ("Y9", "X9=0")):
        _need_formula(model, "bu", addr, part)


def _borsa_filter(model: Model) -> None:
    """Only quotes with an order behind them: a side is shown when its size is above zero, a maturity is
    listed when one of its sides is."""
    s2 = SheetBuilder(model, "Sheet2")
    first, last = BORSA_ROWS
    for both, bid, ask, bid_size, ask_size in BORSA_BLOCKS:
        for r in range(first, last + 1):
            s = r - 2
            # (IF, not AND: a size may be a text such as "#N/A N/A" or, offline, an error value)
            has_bid = "IF(ISNUMBER(Sheet1!$%(c)s%(r)d),Sheet1!$%(c)s%(r)d>0,FALSE)" % {"c": bid_size, "r": s}
            has_ask = "IF(ISNUMBER(Sheet1!$%(c)s%(r)d),Sheet1!$%(c)s%(r)d>0,FALSE)" % {"c": ask_size, "r": s}
            for cols, cond in ((both, "OR(%s,%s)" % (has_bid, has_ask)), (bid, has_bid), (ask, has_ask)):
                for col in cols:
                    s2.patch("%s%d" % (col, r), '=IF(%s,Sheet1!%s%d,"")' % (cond, col, s))
    # points per day: an empty side stays empty (the workbook's ``IF(J9=0,…)`` divides a blank otherwise)
    bu = SheetBuilder(model, "bu")
    for per, points, days in (("I", "J", "E"), ("L", "K", "E"), ("V", "W", "R"), ("Y", "X", "R")):
        for r in range(9, 55):
            bu.patch("%s%d" % (per, r), '=IF(N(%s%d)=0,"",%s%d/%s%d)' % (points, r, points, r, days, r))


#: The quotes of the next business day (BFX1) start on the T+1 value date, which the Borsa workbook counts with
#: WORKDAY(TODAY(),1) - weekends only: it holds no holiday list.  The dashboard gives it a copy of the desk's TRY list on
#: a sheet of its own (the service fills it with the TRY workbook's list as it starts, the settings page writes it with
#: the other copies) and the T+1 date on that list, as the TRY OIS spot date is on the TRY workbook's (OIS_MAIN!B2):
#: the T+1 table's "Valör" counts from it.
BORSA_HOL_SHEET = "EK_TATIL"
BORSA_T1 = "B2"                          # the T+1 value date
BORSA_HOL_FIRST = 5                      # the TRY holidays (dates), this many rows: the TRY workbook's list has 163
BORSA_HOL_ROWS = 200
BORSA_HOL_LAST = BORSA_HOL_FIRST + BORSA_HOL_ROWS - 1
BORSA_LAST = 54                          # the last row of the two tables of "bu"
_BORSA_D_LAST = 'IF(ISNUMBER(E54),TODAY(),"")'       # the T+0 table's last "Valör" in the file: today, without its days


def _borsa_t1_check(model: Model) -> None:
    _need_sheets(model, "bu")
    if BORSA_HOL_SHEET in model.sheet_index:
        raise ValueError("%s sayfası zaten var" % BORSA_HOL_SHEET)
    for r in range(9, BORSA_LAST):                     # Q9:Q53: the T+1 table's "Valör" = the next weekday + its days
        _need_formula(model, "bu", "Q%d" % r, "WORKDAY(TODAY(),1)+R%d" % r)


def _borsa_t1(model: Model) -> None:
    """The T+1 table's dates on the desk's TRY holidays: the copy of the list, the T+1 date on it and every "Valör" of
    the table counted from that date - the file's last row, which has no formula there, too.  And the T+0 table's last
    "Valör", which the file counts as today, the maturity's days left out, counted as the rows above it."""
    h = SheetBuilder(model, BORSA_HOL_SHEET)
    h.title("A1", "TRY TATİLLERİ  ·  BIST swap'ın T+1 valörü (BFX1) bu listeye göre – TTO kitabının TRY tatil listesinin kopyası")
    h.set("A2", "T+1 valör", bold=True)
    h.set(BORSA_T1, "=WORKDAY(TODAY(),1,$A$%d:$A$%d)" % (BORSA_HOL_FIRST, BORSA_HOL_LAST), fmt=DATE, bold=True)
    h.note("C2", "Bugünden sonraki ilk iş günü, TTO'daki OIS spot valörü (OIS_MAIN!B2) gibi. Liste dashboard açılırken TTO kitabının "
                 "listesinden (Motor!A361:A523) gelir; Ayarlar → Tatiller listeyi üç kitaba birden yazar.")
    h.head("A4", ["TRY tatili"])
    for r in range(BORSA_HOL_FIRST, BORSA_HOL_LAST + 1):
        h.set("A%d" % r, None, fmt=DATE)
    t1 = "%s!$%s$%s" % (BORSA_HOL_SHEET, BORSA_T1[0], BORSA_T1[1:])
    bu = SheetBuilder(model, "bu")
    sh = model.sheet("bu")
    for r in range(9, BORSA_LAST + 1):
        text = '=IF(R%d="","",%s+R%d)' % (r, t1, r)
        rc = parse_a1("Q%d" % r)
        if rc in sh.fml:
            if "WORKDAY(TODAY(),1)+R%d" % r in formula_of(model, "bu", "Q%d" % r):
                bu.patch("Q%d" % r, text)
        elif rc not in sh.consts:
            bu.set("Q%d" % r, text, like="Q%d" % (r - 1))
    if parse_a1("D%d" % BORSA_LAST) in sh.fml and formula_of(model, "bu", "D%d" % BORSA_LAST) == _BORSA_D_LAST:
        bu.patch("D%d" % BORSA_LAST, '=IF(ISNUMBER(E%d),TODAY()+E%d,"")' % (BORSA_LAST, BORSA_LAST))


# ---------------------------------------------------------------------------------------------- holiday calendars
#: The desk's holiday calendars.  TRY is the workbook's own list (Motor!A361:B523: every WORKDAY of the TRY workbook
#: reads it - money market, bonds, VİOP, OIS, the meeting calendar - and DİBS ASW keeps a copy of it).  USD and EUR are
#: lists of the dashboard's own on ``EK_TATIL``, for the FX value dates, which skip the holidays of both currencies of a
#: pair (USDTRY: TRY and USD, EURTRY: TRY and EUR):
#:
#: * USD - the days New York does not settle FX: the Federal Reserve's holidays.  A holiday on a Sunday closes the
#:   Monday after; one on a Saturday does not close the Friday before.  Good Friday is a settlement day.  (Not the US
#:   bond market's SIFMA list of the USD workbook, which its SOFR / USD OIS sheets keep using.)
#: * EUR - TARGET2's closing days: 1 January, Good Friday, Easter Monday, 1 May, 25 and 26 December.
#:
#: Both start from these rules for the years ``HOL_YEARS`` - fixed, so that no row moves with today - without the days
#: that fall on a weekend, and are the desk's to edit (shared inputs, the settings page).  Between the two lists stands
#: a copy of the TRY list: a pair's joint calendar is two of the columns side by side (WORKDAY takes any block of dates
#: and leaves the empty cells out; the copy holds 0 for an empty row of the TRY list, a day long gone).
HOL_SHEET = "EK_TATIL"
HOL_FIRST = 5                            # the first row of the lists (title, notes and header above)
HOL_ROWS = 260                           # room of each list: the defaults fill 212 USD and 98 EUR rows
HOL_LAST = HOL_FIRST + HOL_ROWS - 1
HOL_YEARS = (2020, 2040)
#: where each list of the sheet is: (date column, name column)
HOL_COLS = {"USD": ("B", "A"), "EUR": ("D", "E")}
HOL_TRY_COL = "C"                        # the copy of the TRY list
TRY_HOLIDAYS = "Motor!$A$361:$A$523"     # the workbook's TRY list, as its formulas name it
TRY_HOLIDAY_ROWS = (361, 523)
#: the currencies the desk keeps a holiday list of
HOLIDAY_CCYS = ("TRY", "USD", "EUR")
#: a pair's joint calendar: the holidays of both its currencies, as the formulas name it
FX_HOLIDAYS = {"USDTRY": "%s!$B$%d:$C$%d" % (HOL_SHEET, HOL_FIRST, HOL_LAST),
               "EURTRY": "%s!$C$%d:$D$%d" % (HOL_SHEET, HOL_FIRST, HOL_LAST)}


def easter(year: int) -> _dt.date:
    """Easter Sunday of the Gregorian calendar (the anonymous algorithm: Meeus / Jones / Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return _dt.date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """The ``n``-th ``weekday`` (0 = Monday) of a month; ``n`` = -1: the last one."""
    if n < 0:
        d = _dt.date(year + month // 12, month % 12 + 1, 1) - _dt.timedelta(days=1)
        return d - _dt.timedelta(days=(d.weekday() - weekday) % 7)
    d = _dt.date(year, month, 1)
    return d + _dt.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))


def usd_holidays(first: int, last: int) -> List[Tuple[_dt.date, str]]:
    """The Federal Reserve's holidays of the years ``first`` .. ``last``, in date order: a fixed day on a Sunday is
    closed on the Monday after ("gözlenen"), one on a Saturday is not closed at all.  Juneteenth from 2022 (the Fed's
    services were open on 18.06.2021)."""
    out: List[Tuple[_dt.date, str]] = []
    for y in range(first, last + 1):
        fixed = [(_dt.date(y, 1, 1), "Yılbaşı"), (_dt.date(y, 7, 4), "Independence Day"),
                 (_dt.date(y, 11, 11), "Veterans Day"), (_dt.date(y, 12, 25), "Noel")]
        if y >= 2022:
            fixed.append((_dt.date(y, 6, 19), "Juneteenth"))
        for day, name in fixed:
            if day.weekday() == 6:
                out.append((day + _dt.timedelta(days=1), name + " (gözlenen)"))
            elif day.weekday() < 5:
                out.append((day, name))
        out += [(_nth_weekday(y, 1, 0, 3), "Martin Luther King Day"), (_nth_weekday(y, 2, 0, 3), "Presidents' Day"),
                (_nth_weekday(y, 5, 0, -1), "Memorial Day"), (_nth_weekday(y, 9, 0, 1), "Labor Day"),
                (_nth_weekday(y, 10, 0, 2), "Columbus Day"), (_nth_weekday(y, 11, 3, 4), "Thanksgiving")]
    return sorted(out)


def eur_holidays(first: int, last: int) -> List[Tuple[_dt.date, str]]:
    """TARGET2's closing days of the years ``first`` .. ``last`` that fall on a week day, in date order."""
    out: List[Tuple[_dt.date, str]] = []
    for y in range(first, last + 1):
        e = easter(y)
        for day, name in ((_dt.date(y, 1, 1), "Yılbaşı"), (e - _dt.timedelta(days=2), "Good Friday"),
                          (e + _dt.timedelta(days=1), "Easter Monday"), (_dt.date(y, 5, 1), "1 Mayıs"),
                          (_dt.date(y, 12, 25), "Noel"), (_dt.date(y, 12, 26), "Noel (26 Aralık)")):
            if day.weekday() < 5:
                out.append((day, name))
    return sorted(out)


def pair_calendar(pair: str) -> Tuple[str, ...]:
    """The holiday lists an FX value date of ``pair`` skips: those of both its currencies when the desk keeps a list of
    each (USDTRY, EURTRY, EURUSD); ``()`` for any other pair (whatever rule it had stands)."""
    a, b = str(pair)[:3].upper(), str(pair)[3:6].upper()
    return (a, b) if a != b and a in HOLIDAY_CCYS and b in HOLIDAY_CCYS else ()


def fx_holidays(model: Model, pair: str) -> str:
    """The holidays the formulas of ``pair``'s value dates skip: its joint calendar - or the TRY list in a file the
    holiday sheet does not fit (as before)."""
    return FX_HOLIDAYS[pair] if HOL_SHEET in model.sheet_index else TRY_HOLIDAYS


def _holidays_check(model: Model) -> None:
    """The TRY list the joint calendars copy is where the workbook keeps it (dates in Motor!A361:A523)."""
    _need_sheets(model, "Motor")
    sh = model.sheet("Motor")
    r1, r2 = TRY_HOLIDAY_ROWS
    if not any(type(sh.consts.get(parse_a1("A%d" % r))) is float for r in range(r1, r2 + 1)):
        raise ValueError("Motor!A%d:A%d tatil listesi değil" % (r1, r2))
    if HOL_SHEET in model.sheet_index:
        raise ValueError("%s sayfası zaten var" % HOL_SHEET)


def _tto_holidays(model: Model) -> None:
    """``EK_TATIL``: the USD and EUR holiday lists (date and name, the rules' days of ``HOL_YEARS`` to start with) and,
    between them, the copy of the TRY list that makes the joint calendars of USDTRY and EURTRY."""
    b = SheetBuilder(model, HOL_SHEET)
    b.title("A1", "TATİL TAKVİMLERİ  ·  USD (New York · Fed) ve EUR (TARGET2)  ·  FX valörleri paritenin iki para biriminin tatilini de atlar")
    b.note("A2", "USD: Fed tatilleri - pazara denk gelen tatil pazartesi kapalı, cumartesiye denk gelen tatil için cuma açık; Good "
                 "Friday USD için iş günü (SIFMA listesi değil: o USD · FOMC sayfasında, SOFR / USD OIS'te kalır). EUR: TARGET2 - 1 Ocak, "
                 "Good Friday, Easter Monday, 1 Mayıs, 25 ve 26 Aralık. Hafta sonuna düşen günler listede yok.")
    b.note("A3", "Listeler masanın ortak verisidir, Ayarlar → Tatiller'den düzenlenir. USDTRY valörleri TRY + USD (B:C), EURTRY valörleri "
                 "TRY + EUR (C:D) tatillerini atlar; C sütunu TRY listesinin (Motor!A361:A523) kopyasıdır. TRY para piyasası, tahvil, "
                 "VİOP ve OIS tarihleri yalnız TRY listesini kullanır.")
    b.head("A4", ["USD tatili", "USD tarihi", "TRY tarihi (Motor)", "EUR tarihi", "EUR tatili"])
    lists = {"USD": usd_holidays(*HOL_YEARS), "EUR": eur_holidays(*HOL_YEARS)}
    t1, t2 = TRY_HOLIDAY_ROWS
    for k in range(HOL_ROWS):
        r = HOL_FIRST + k
        for ccy, days in lists.items():
            dcol, ncol = HOL_COLS[ccy]
            day, name = days[k] if k < len(days) else (None, None)
            b.input("%s%d" % (dcol, r), float(date_to_serial(day)) if day else None, fmt=DATE)
            b.input("%s%d" % (ncol, r), name)
        if t1 + k <= t2:
            b.set("%s%d" % (HOL_TRY_COL, r), "=N(Motor!$A$%d)" % (t1 + k), fmt=DATE + ";;", color=NOTE_COLOR)


#: The FX value dates the workbook counts on the TRY list alone, moved to the pair's joint calendar.  The spot dates of
#: the Forward sheet were Bloomberg's (``SETTLE_DT``, a date of the day the file was saved when offline): they are the
#: dashboard's own now, from the desk's lists - USDTRY a business day of both TRY and USD after today, EURTRY two days
#: that are business days of both TRY and EUR - and Bloomberg's stands beside each, for comparison:
#: (spot cell, pair, business days after today, cell of Bloomberg's date, its security)
FX_SPOTS = (("I2", "USDTRY", 1, "J2", "TRY Curncy"), ("K2", "EURTRY", 2, "L2", "EURTRY Curncy"))
#: the workbook's tenor dates counted from the USDTRY spot date: MASA's forward pricing and broken date, the Forward
#: sheet's cross forwards (their USDTRY leg) and the days of its XCCY nodes when Bloomberg has none
FX_DATE_CELLS = (("MASA", "P94:P99"), ("MASA", "C171"), ("Forward", "B200:B205"), ("Forward", "K130:K134"))
FX_DATE_NAME = "FX valörleri"


def spot_date_formula(pair: str) -> str:
    """The formula of a pair's spot date: ``WORKDAY(TODAY(), lag, joint calendar)``."""
    lag = next(n for _, p, n, _, _ in FX_SPOTS if p == pair)
    return "=WORKDAY(TODAY(),%d,%s)" % (lag, FX_HOLIDAYS[pair])


def _need_spot_date(model: Model, addr: str) -> None:
    """A spot date of the Forward sheet: Bloomberg's ``SETTLE_DT`` (the file's) or the dashboard's own (``FX_SPOTS``)."""
    text = _need_formula(model, "Forward", addr).upper()
    if "SETTLE_DT" not in text and HOL_SHEET not in text:
        raise ValueError("Forward!%s spot valörü değil" % addr)


def _fx_dates_check(model: Model) -> None:
    _need_sheets(model, HOL_SHEET, "Forward", "MASA")
    fw = model.sheet("Forward")
    for spot, _, _, bbg, sec in FX_SPOTS:
        _need_formula(model, "Forward", spot, '"%s","SETTLE_DT"' % sec)
        if parse_a1(bbg) in fw.fml or parse_a1(bbg) in fw.consts:
            raise ValueError("Forward!%s boş değil" % bbg)
    for sheet, rng in FX_DATE_CELLS:
        r1, c1, r2, c2 = parse_range(rng)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                text = _need_formula(model, sheet, "%s%d" % (index_to_col(c), r), TRY_HOLIDAYS)
                if "I$2" not in text:
                    raise ValueError("%s!%s%d USDTRY spot valöründen sayılmıyor" % (sheet, index_to_col(c), r))


def _tto_fx_dates(model: Model) -> None:
    fw = SheetBuilder(model, "Forward")
    for spot, pair, _, bbg, sec in FX_SPOTS:
        fw.set(bbg, '=_xll.BDP("%s","SETTLE_DT")' % sec, fmt=DATE, color=NOTE_COLOR)
        fw.recorded(bbg, recorded_value(model, "Forward", spot))          # offline: the file's, as the spot cell had it
        fw.set(spot, spot_date_formula(pair), fmt=DATE)
    for sheet, rng in FX_DATE_CELLS:
        b = SheetBuilder(model, sheet)
        r1, c1, r2, c2 = parse_range(rng)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                addr = "%s%d" % (index_to_col(c), r)
                b.patch(addr, "=" + formula_of(model, sheet, addr).replace(TRY_HOLIDAYS, FX_HOLIDAYS["USDTRY"]))


#: The TRY OIS / TLREF spot date (OIS_MAIN!B2, the workbook's ``SPOTDATE``): the next business day of the TRY list -
#: TLREF works on a US holiday.  It was Bloomberg's USDTRY settle date (OIS_MAIN!W2, ``TRY Curncy`` ``SETTLE_DT``), an FX
#: date that skips the US holidays too (25.11.2026: 27.11, where TLREF settles on 26.11); that stands beside it now, for
#: comparison (K2:L2).  The workbook's OIS, TLREF, meeting, money market and bond dates count from B2; its FX value
#: dates from Forward!I2.
OIS_SPOT_NAME = "OIS spot valörü"
OIS_SPOT_CELLS = ("K2", "L2")            # the caption and Bloomberg's date, right of the OIS page's parameters


def _ois_spot_check(model: Model) -> None:
    _need_sheets(model, "OIS_MAIN", "Motor")
    _need_formula(model, "OIS_MAIN", "B2", "W2")
    _need_formula(model, "OIS_MAIN", "W2", '"TRY Curncy","SETTLE_DT"')
    sh = model.sheet("OIS_MAIN")
    for addr in OIS_SPOT_CELLS:
        if parse_a1(addr) in sh.fml or parse_a1(addr) in sh.consts:
            raise ValueError("OIS_MAIN!%s boş değil" % addr)


def _tto_ois_spot(model: Model) -> None:
    b = SheetBuilder(model, "OIS_MAIN")
    b.patch("B2", "=WORKDAY(TODAY(),1,%s)" % TRY_HOLIDAYS)
    caption, date = OIS_SPOT_CELLS
    b.set(caption, "Bloomberg valörü", like="A2")
    b.set(date, "=IFERROR(DATE(YEAR($W$2),MONTH($W$2),DAY($W$2)),$W$2)", fmt=DATE, color=NOTE_COLOR, align="center")


# ---------------------------------------------------------------------------------------------- TRY workbook
FWD_SHEET = "EK_FWD"
FWD_ALL = 4                              # the "Tümü" row: general spreads (bid, ask) and the spot quotes
FWD_ROWS = (5, 14)                       # 1M, 2M, 3M, 6M, 9M, 12M and four free dates
FWD_BACK = 15                            # rows of the "points -> spread" table = rows of the matrix + 15
#: rows of the "rate -> spread" table = rows of the matrix + these (USDTRY 133..142, EURTRY 147..156: below the EURTRY
#: matrix's way back, where no input ever stood - a value a user typed is kept by its cell, see ``RETIRED_INPUTS``)
FWD_RATE, FWD_EUR_RATE = 128, 43
#: curve names of the selector, in the order of the helper columns AE:AK
FWD_CURVES = ("MPC ima", "S1", "S2", "S3", "Ağırlıklı", "Bootstrap", "TLREF sabit")
#: desk-sheet cells that hold the discount factor spot -> end date of each curve (their number of days is $M$60)
FWD_DF_SOURCES = (("Y", "MPC ima", "I62"), ("Z", "S1", "I63"), ("AA", "S2", "I64"), ("AB", "S3", "I65"),
                  ("AC", "Bootstrap", "I67"), ("AD", "TLREF sabit", "I68"))


FWD_SPREAD_OWN = "Elle spread"
FWD_SPREAD_MARKET = "Piyasa spread"


def fwd_offshore(days: str, side: str) -> str:
    """The offshore (ICAP) implied TRY rate (%) of the Forward sheet ``days`` after the USDTRY spot date, its bid
    (``side`` "I") or ask ("K") - as the sheet reads it for the value date; more than a month past its last node: none."""
    xs = "Forward!$G$8:$G$21"
    return 'IF(%s>INDEX(%s,14)+%d,"",%s)' % (days, xs, FR_REACH, lin(days, xs, "Forward!$%s$8:$%s$21" % (side, side), 14))


def _forward_check(model: Model) -> None:
    _need_sheets(model, "MASA", "VIOP", "Forward", "OIS_MAIN", "Motor")
    for _, _, src in FWD_DF_SOURCES:                   # the discount factors must depend on the days in $M$60 only
        transplant(_need_formula(model, "MASA", src, "$M$60"), {"$M$60": "$X5"})
    _need_formula(model, "MASA", "M60", "OIS_MAIN!$B$2")
    _need_formula(model, "VIOP", "L99")
    _need_formula(model, "VIOP", "L100")
    _need_spot_date(model, "I2")
    _need_formula(model, "Forward", "I22", "$I$8:$I$21")         # the offshore implied curve's nodes: days in G, bid in I, ask in K
    _need_formula(model, "Forward", "K22", "$K$8:$K$21")
    _need_formula(model, "Forward", "I22", "$G$8:$G$21")


def _tto_forward(model: Model) -> None:
    """Forward quotes from OIS + spread, the spread given separately for the bid and the ask side.

    The TRY rate of a value date is the OIS rate spot -> date of the chosen curve (the discount factors are
    the desk sheet's own, MASA!I62:I68, evaluated for the date of the row) plus the spread; the forward is
    priced the way the desk sheet prices it: spot bid with the bid rate, spot ask with the ask rate, USD OIS
    mid.  Below it the way back: swap points typed by hand -> implied TRY rate -> spread over OIS.
    """
    b = SheetBuilder(model, FWD_SHEET)
    r1, r2 = FWD_ROWS
    b.title("A1", "FORWARD KOTASYON  ·  USDTRY, OIS + spread  (bid ve ask spread'i ayrı; sarı hücreler girdi)")
    b.row("A2", ["Eğri", None, None, None, None, "Spot valör", None, "OIS spot", None], bold=True)
    b.input("B2", "MPC ima", align="center")
    b.dropdown("B2", FWD_CURVES)
    b.set("G2", "=IFERROR(DATE(YEAR(Forward!$I$2),MONTH(Forward!$I$2),DAY(Forward!$I$2)),Forward!$I$2)", fmt=DATE)
    b.set("I2", "=OIS_MAIN!$B$2", fmt=DATE)
    # what the curves are: S1 / S2 / S3 are the scenarios of the OIS sheet - their names and weights are read
    # from its SENARYOLAR table (OIS_MAIN!O3:Q5), so a scenario renamed there is renamed here
    scen = 'INDEX(OIS_MAIN!$%s$3:$%s$5,MATCH("%s",OIS_MAIN!$O$3:$O$5,0))'
    b.set("C2", '=IFERROR(IF(LEFT($B$2,1)="S","= "&INDEX(OIS_MAIN!$P$3:$P$5,MATCH($B$2,OIS_MAIN!$O$3:$O$5,0)),'
                'IF($B$2="Ağırlıklı","= S1–S3 ağırlıklı","")),"")', bold=True, color=NOTE_COLOR)
    parts = ['"S%d = "&%s&" (%%"&ROUND(%s*100,0)&")"' % (k, scen % ("P", "P", "S%d" % k), scen % ("Q", "Q", "S%d" % k)) for k in (1, 2, 3)]
    b.set("K2", '=IFERROR("Eğriler: "&' + '&" · "&'.join(parts) + '&" · Ağırlıklı = S1–S3 olasılıklarıyla · MPC ima = kotaların ima ettiği PPK patikası'
                ' · Bootstrap = kotalardan doğrudan · TLREF sabit = bugünkü TLREF","")', color=NOTE_COLOR)
    b.head("A3", ["Vade", "Valör", "Gün", "Spread bid", "Spread ask", "Spot bid", "Spot ask", "Puan bid", "Puan ask", "Fwd bid",
                  "Fwd ask", "OIS %", "TRY bid %", "TRY ask %", "USD %", "P/gün bid", "P/gün ask", "RET bid %", "RET ask %",
                  "Bid − RET", "Ask − RET", "Piyasa bid (bp)", "Piyasa ask (bp)"])
    # the general row: one spread for every date (a date's own spread can be typed over it), and the spot quotes
    g = FWD_ALL
    b.set("A%d" % g, "Tümü", bold=True, align="center")
    # the spreads of the dates: one's own ("Elle spread") or the market's (offshore implied − OIS, "Piyasa spread")
    b.input("B%d" % g, FWD_SPREAD_OWN, align="center")
    b.dropdown("B%d" % g, (FWD_SPREAD_OWN, FWD_SPREAD_MARKET))
    b.set("C%d" % g, "bp →", color=NOTE_COLOR, align="right")
    b.input("D%d" % g, "=MASA!$I$60", fmt="0", align="center")      # starts from the desk sheet's single spread
    b.input("E%d" % g, "=MASA!$I$60", fmt="0", align="center")
    b.set("F%d" % g, "=VIOP!$L$99", fmt=NUM4)
    b.set("G%d" % g, "=VIOP!$L$100", fmt=NUM4)
    b.set("X2", "Yardımcı: her eğrinin spot→valör iskonto faktörü ve ACT/360 basit faizi (%)", color=NOTE_COLOR)
    b.head("X3", ["OIS gün"] + ["DF " + name for _, name, _ in FWD_DF_SOURCES] + list(FWD_CURVES))
    df_text = {col: formula_of(model, "MASA", src) for col, _, src in FWD_DF_SOURCES}
    rate_col = dict(zip(FWD_CURVES, ("AE", "AF", "AG", "AH", "AI", "AJ", "AK")))
    months = {r1: 1, r1 + 1: 2, r1 + 2: 3, r1 + 3: 6, r1 + 4: 9, r1 + 5: 12}
    usd_x, usd_y = "Forward!$U$7:$U$26", "Forward!$X$7:$X$26"
    ret_x, ret_bid, ret_ask = "Forward!$U$33:$U$47", "Forward!$W$33:$W$47", "Forward!$X$33:$X$47"
    for r in range(r1, r2 + 1):
        f = {"r": r, "g": g}
        if r in months:
            b.set("A%d" % r, "%dM" % months[r], bold=True, align="center")
            b.input("B%d" % r, "=WORKDAY(EDATE(Forward!$I$2,%d)-1,1,%s)" % (months[r], fx_holidays(model, "USDTRY")), fmt=DATE)
        else:
            b.set("A%d" % r, "serbest", align="center", color=NOTE_COLOR)
            b.input("B%d" % r, None, fmt=DATE)
        b.set("C%d" % r, '=IF(ISNUMBER($B%(r)d),$B%(r)d-Forward!$I$2,"")' % f, fmt=INT0)
        # per date; starts from the general spread - or the market's of the date
        b.input("D%d" % r, '=IF($B$%d="%s",$V%d,$D$%d)' % (g, FWD_SPREAD_MARKET, r, g), fmt="0", align="center")
        b.input("E%d" % r, '=IF($B$%d="%s",$W%d,$E$%d)' % (g, FWD_SPREAD_MARKET, r, g), fmt="0", align="center")
        b.set("F%d" % r, '=IF($C%(r)d="","",$F$%(g)d)' % f, fmt=NUM4)
        b.set("G%d" % r, '=IF($C%(r)d="","",$G$%(g)d)' % f, fmt=NUM4)
        b.set("H%d" % r, '=IFERROR(IF($C%(r)d="","",($J%(r)d-$F%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("I%d" % r, '=IFERROR(IF($C%(r)d="","",($K%(r)d-$G%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("J%d" % r, '=IFERROR(IF($C%(r)d="","",$F%(r)d*(1+$M%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("K%d" % r, '=IFERROR(IF($C%(r)d="","",$G%(r)d*(1+$N%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("L%d" % r, '=IF($C%(r)d="","",INDEX($AE%(r)d:$AK%(r)d,MATCH($B$2,$AE$3:$AK$3,0)))' % f, fmt="0.00")
        # the market's spread of the date: the offshore (ICAP) implied TRY rate − OIS, bid and ask
        for col, side in (("V", "I"), ("W", "K")):
            b.set("%s%d" % (col, r), '=IFERROR(IF($C%d="","",(%s-$L%d)*100),"")' % (r, fwd_offshore("$C%d" % r, side), r), fmt="0")
        b.set("M%d" % r, '=IFERROR(IF($C%(r)d="","",$L%(r)d+IF(ISNUMBER($D%(r)d),$D%(r)d,$D$%(g)d)/100),"")' % f, fmt="0.00")
        b.set("N%d" % r, '=IFERROR(IF($C%(r)d="","",$L%(r)d+IF(ISNUMBER($E%(r)d),$E%(r)d,$E$%(g)d)/100),"")' % f, fmt="0.00")
        b.set("O%d" % r, '=IFERROR(IF($C%d="","",%s),"")' % (r, lin("$C%d" % r, usd_x, usd_y, 20)), fmt="0.00")
        b.set("P%d" % r, '=IFERROR(IF($C%(r)d="","",$H%(r)d/$C%(r)d),"")' % f, fmt="#,##0.0")
        b.set("Q%d" % r, '=IFERROR(IF($C%(r)d="","",$I%(r)d/$C%(r)d),"")' % f, fmt="#,##0.0")
        b.set("R%d" % r, '=IFERROR(IF($C%d="","",%s*100),"")' % (r, lin("$C%d" % r, ret_x, ret_bid, 15)), fmt="0.00")
        b.set("S%d" % r, '=IFERROR(IF($C%d="","",%s*100),"")' % (r, lin("$C%d" % r, ret_x, ret_ask, 15)), fmt="0.00")
        b.set("T%d" % r, '=IFERROR(IF($C%(r)d="","",$H%(r)d-($F%(r)d*(1+$R%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)-$F%(r)d)*10000),"")' % f,
              fmt=INT0)
        b.set("U%d" % r, '=IFERROR(IF($C%(r)d="","",$I%(r)d-($G%(r)d*(1+$S%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)-$G%(r)d)*10000),"")' % f,
              fmt=INT0)
        # helpers: days from the OIS spot date, then the discount factor and the ACT/360 simple rate per curve
        b.set("X%d" % r, '=IF(ISNUMBER($B%(r)d),$B%(r)d-OIS_MAIN!$B$2,"")' % f, fmt=INT0)
        for col, name, _ in FWD_DF_SOURCES:
            b.set("%s%d" % (col, r), "=" + transplant(df_text[col], {"$M$60": "$X%d" % r}), fmt="0.000000")
            b.set("%s%d" % (rate_col[name], r), '=IFERROR((1/$%s%d-1)*360/$X%d*100,NA())' % (col, r, r), fmt="0.0000")
        # the desk sheet's "Ağırlıklı": the scenario rates weighted with the OIS_MAIN probabilities (MASA!R66)
        b.set("AI%d" % r, '=IFERROR((OIS_MAIN!$Q$3*$AF%(r)d+OIS_MAIN!$Q$4*$AG%(r)d+OIS_MAIN!$Q$5*$AH%(r)d)/SUM(OIS_MAIN!$Q$3:$Q$5),NA())' % f,
              fmt="0.0000")
    b.note("A%d" % (r2 + 1), "TRY faizi = seçilen OIS eğrisinin spot→valör ACT/360 basit faizi + spread (bp); eğriler MASA 'Tarih arası faiz' "
                             "bloğundaki iskonto faktörleriyle aynı. Spread bp; 'Tümü' satırı bütün vadelere, vade satırındaki değer yalnız o vadeye uygulanır. "
                             "Piyasa bid / ask = offshore (ICAP) ima TRY faizi − OIS: 'Tümü' satırında 'Piyasa spread' seçilince her vade onunla fiyatlanır.")
    b.note("A%d" % (r2 + 2), "Fwd bid = spot bid·(1+TRY bid·g/360)/(1+USD·g/360), ask tarafı spot ask ve TRY ask ile (Forward fiyatlama "
                             "tablosuyla aynı formül). Puan = (fwd − spot)·10000; P/gün = puan/gün. 'Bid/Ask − RET' = aynı valörde RET bid/ask faiziyle çıkan puana fark.")

    # ---- the way back: swap points typed by hand -> implied TRY rate -> spread over the chosen OIS curve
    t = r1 + FWD_BACK - 2
    b.title("A%d" % t, "PUAN → OIS SPREAD  ·  elle verilen swap puanının ima ettiği TRY faizi ve OIS'e göre spread'i")
    b.head("A%d" % (t + 1), ["Vade", "Valör", "Gün", "Elle puan bid", "Elle puan ask", "Fwd bid", "Fwd ask", "İma TRY bid %", "İma TRY ask %",
                             "OIS %", "İma spread bid (bp)", "İma spread ask (bp)", "RET bid %", "RET ask %"])
    for r in range(r1, r2 + 1):
        f = {"r": r + FWD_BACK, "s": r}
        k = r + FWD_BACK
        b.set("A%d" % k, "=$A%d" % r, bold=r in months, align="center", color=None if r in months else NOTE_COLOR)
        b.set("B%d" % k, '=IF($B%(s)d="","",$B%(s)d)' % f, fmt=DATE)
        b.set("C%d" % k, "=$C%d" % r, fmt=INT0)
        b.input("D%d" % k, None, fmt=INT0)
        b.input("E%d" % k, None, fmt=INT0)
        b.set("F%d" % k, '=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($D%(r)d))),"",$F%(s)d+$D%(r)d/10000),"")' % f, fmt=NUM4)
        b.set("G%d" % k, '=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($E%(r)d))),"",$G%(s)d+$E%(r)d/10000),"")' % f, fmt=NUM4)
        b.set("H%d" % k, '=IFERROR(IF($F%(r)d="","",(($F%(r)d/$F%(s)d)*(1+$O%(s)d/100*$C%(r)d/360)-1)*360/$C%(r)d*100),"")' % f, fmt="0.00")
        b.set("I%d" % k, '=IFERROR(IF($G%(r)d="","",(($G%(r)d/$G%(s)d)*(1+$O%(s)d/100*$C%(r)d/360)-1)*360/$C%(r)d*100),"")' % f, fmt="0.00")
        b.set("J%d" % k, '=IFERROR(IF($C%(r)d="","",$L%(s)d),"")' % f, fmt="0.00")
        b.set("K%d" % k, '=IFERROR(IF($H%(r)d="","",($H%(r)d-$J%(r)d)*100),"")' % f, fmt="0", bold=True)
        b.set("L%d" % k, '=IFERROR(IF($I%(r)d="","",($I%(r)d-$J%(r)d)*100),"")' % f, fmt="0", bold=True)
        b.set("M%d" % k, '=IFERROR(IF($C%(r)d="","",$R%(s)d),"")' % f, fmt="0.00")
        b.set("N%d" % k, '=IFERROR(IF($C%(r)d="","",$S%(s)d),"")' % f, fmt="0.00")
    b.note("A%d" % (r2 + FWD_BACK + 1), "Tarihler üstteki matristen gelir. İma TRY % = ((fwd/spot)·(1+USD·g/360) − 1)·360/g; spread = İma TRY − OIS "
                                        "(bp). Bulunan spread'i üstteki matrise yazınca aynı puan çıkar.")
    _rate_back(b, (r1, r2), FWD_RATE, "USDTRY", "USD", months)


def _rate_back(b: "SheetBuilder", rows: Tuple[int, int], off: int, pair: str, major: str, months: Dict[int, int]) -> None:
    """The way to the spread (the desk, 23.11.2026: "Spread ile forward kotasyonlarını bulduğumuz yere faizi girdiğimde de
    spreadi ve rate'leri vermesi lazım"): TRY bid / ask % typed by hand for the matrix's dates (``rows``; this table
    ``off`` rows below them) -> their spread over the matrix's OIS (bp), the points, the forward, P/gün and the RET
    comparison - the matrix's own formulas, the typed rate in place of OIS + spread: the spread found here, typed into
    the matrix, gives the same points.  USDTRY and EURTRY alike (spot, major's rate and days are the matrix row's)."""
    r1, r2 = rows
    t = r1 + off - 2
    b.title("A%d" % t, "FAİZ → SPREAD  ·  %selle verilen TRY faizinin OIS'e göre spread'i, puanı ve forward'ı"
            % ("" if pair == "USDTRY" else pair + "  ·  "))
    b.head("A%d" % (t + 1), ["Vade", "Valör", "Gün", "TRY bid %", "TRY ask %", "OIS %", "Spread bid (bp)", "Spread ask (bp)", "Puan bid",
                             "Puan ask", "Fwd bid", "Fwd ask", "P/gün bid", "P/gün ask", "RET bid %", "RET ask %", "Bid − RET", "Ask − RET"])
    for r in range(r1, r2 + 1):
        k = r + off
        b.set("A%d" % k, "=$A%d" % r, bold=r in months, align="center", color=None if r in months else NOTE_COLOR)
        b.set("B%d" % k, '=IF($B%d="","",$B%d)' % (r, r), fmt=DATE)
        b.set("C%d" % k, "=$C%d" % r, fmt=INT0)
        b.input("D%d" % k, None, fmt="0.00")
        b.input("E%d" % k, None, fmt="0.00")
        b.set("F%d" % k, '=IFERROR(IF($C%d="","",$L%d),"")' % (k, r), fmt="0.00")
        # each side: the typed rate (D bid, E ask) on the matrix's spot of that side (F / G), its major rate (O) and days (C)
        for rate, spot, sp, pts, fwd, pday, ret, diff in (("D", "F", "G", "I", "K", "M", "R", "Q"), ("E", "G", "H", "J", "L", "N", "S", "R")):
            f = {"k": k, "r": r, "x": rate, "s": spot, "p": pts, "w": fwd, "t": ret}
            f["h"] = 'OR($C%(k)d="",NOT(ISNUMBER($%(x)s%(k)d)))' % f
            b.set("%s%d" % (sp, k), '=IFERROR(IF(%(h)s,"",($%(x)s%(k)d-$F%(k)d)*100),"")' % f, fmt="0", bold=True)
            b.set("%s%d" % (fwd, k), '=IFERROR(IF(%(h)s,"",$%(s)s%(r)d*(1+$%(x)s%(k)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f,
                  fmt=NUM4)
            b.set("%s%d" % (pts, k), '=IFERROR(IF($%(w)s%(k)d="","",($%(w)s%(k)d-$%(s)s%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
            b.set("%s%d" % (pday, k), '=IFERROR(IF($%(p)s%(k)d="","",$%(p)s%(k)d/$C%(r)d),"")' % f, fmt="#,##0.0")
            b.set("%s%d" % (diff, k), ('=IFERROR(IF($%(p)s%(k)d="","",$%(p)s%(k)d-($%(s)s%(r)d*(1+$%(t)s%(r)d/100*$C%(r)d/360)/'
                                       '(1+$O%(r)d/100*$C%(r)d/360)-$%(s)s%(r)d)*10000),"")') % f, fmt=INT0)
        b.set("O%d" % k, '=IFERROR(IF($C%d="","",$R%d),"")' % (k, r), fmt="0.00")
        b.set("P%d" % k, '=IFERROR(IF($C%d="","",$S%d),"")' % (k, r), fmt="0.00")
    b.note("A%d" % (r2 + off + 1), "Tarihler üstteki matristen gelir. TRY bid / ask %%'yi yazın: spread = TRY − OIS (bp); puan, forward, P/gün ve "
                                   "RET farkı matrisin aynı formülleriyle, OIS + spread yerine yazdığınız faizle (spot, %s faizi ve gün matrisin "
                                   "satırından). Bulunan spread'i matrise yazınca aynı puan çıkar." % major)


XAU_SHEET = "EK_XAU"
XAU_CURVE = (16, 22)                     # gold swap rate curve rows: 1W, 1M, 2M, 3M, 6M, 9M, 12M
#: tenor, months from spot (None = one week), Bloomberg ticker root of the gold swap rate
XAU_TENORS = (("1W", None, "XAUSR1W"), ("1M", 1, "XAUSR1M"), ("2M", 2, "XAUSR2M"), ("3M", 3, "XAUSR3M"),
              ("6M", 6, "XAUSR6M"), ("9M", 9, "XAUSR9M"), ("12M", 12, "XAUSR12M"))
XAU_TICKER_KEY = "Curncy"                # the "yellow key" appended to a ticker root
XAU_TARGETS = (27, 35)                   # 3 VİOP XAUTRY contracts, 3 VİOP XAUUSD contracts, Forward!D2, 2 free dates
XAU_SOURCES = ("Otomatik", "Swap faizi", "BFXFORWARD")
XAU_CALC = 39                            # header row of the "price at a given rate" calculator
#: the calculator's rows below its header, in order (name -> label)
XAU_CALC_ROWS = ("d1", "d2", "n", "s", "xau", "usd", "try", "swap", "xfwd", "simp", "fwd", "sp", "spd", "teo", "vbid", "vask", "dbid", "dask",
                 "ibid", "iask", "sxt", "on", "gbid", "gask")
XAU_CALC_LABELS = ("1st Date", "2nd Date", "VKGS", "USDTRY spot", "XAUUSD spot", "USD %", "TRY %", "Altın swap % (ops.)", "XAUUSD fwd",
                   "Altın swap % (ima)", "All In S -> E (USDTRY fwd)", "SP", "Günlük SP", "XAUTRY teorik (TL/gr)", "VIOP bid", "VIOP ask",
                   "Teorik − VIOP bid", "Teorik − VIOP ask", "İma TRY % · VIOP bid", "İma TRY % · VIOP ask", "Spot XAUTRY (TL/gr)",
                   "ON karşılık (TRY %)", "İma altın swap % · VIOP bid", "İma altın swap % · VIOP ask")
GRAMS_PER_OUNCE = "31.1035"              # the VİOP sheet's own constant (VIOP!M55)
_USD_CURVE = "VIOP!$B$16:$B$25,VIOP!$F$16:$F$25"


#: the cells that hold Excel's gold forwards: (sheet, cell, side asked of BFXFORWARD)
XAU_BFX_CELLS = (("VIOP", "M58", "AskOutright"), ("VIOP", "N58", "AskOutright"), ("VIOP", "O58", "AskOutright"),
                 ("VIOP", "S58", "BidOutright"), ("VIOP", "T58", "BidOutright"), ("VIOP", "U58", "BidOutright"),
                 ("VIOP", "M68", "AskOutright"), ("VIOP", "N68", "AskOutright"), ("VIOP", "O68", "AskOutright"),
                 ("Forward", "I29", "BidOutright"), ("Forward", "J29", "AskOutright"))


def _gold_check(model: Model) -> None:
    _need_sheets(model, "VIOP", "Forward")
    for sheet, addr, side in XAU_BFX_CELLS:            # only cells that still are the BFXFORWARD calls are replaced
        text = _need_formula(model, sheet, addr, 'BFXFORWARD("XAUUSD"')
        if side.upper() not in text.upper():
            raise ValueError("%s!%s beklenen formül değil (%s yok)" % (sheet, addr, side))
    for addr in ("M46", "S46", "M48", "M49", "M50", "M51", "M52", "M57", "S57", "M61", "M63", "K3", "F16"):
        _need_formula(model, "VIOP", addr)
    for addr in ("M45", "N45", "O45", "M60", "N60", "O60"):
        if not isinstance(model.sheet("VIOP").consts.get(parse_a1(addr)), str):
            raise ValueError("VIOP!%s kontrat ticker'ı değil" % addr)


def _tto_gold(model: Model) -> None:
    """Gold forwards from the gold swap rate.

    Excel prices the gold forward with ``BFXFORWARD("XAUUSD"; date; ...)``, a function of the Bloomberg
    Excel add-in that the API does not have.  Here the forward is the spot carried at the gold swap rate
    (Bloomberg ``XAUSR1W``, ``XAUSR1M`` ...), applied directly - no USD rate is involved:

        XAUUSD fwd = spot · (1 + swap rate · g/360)                     g = value date − gold spot value date

    The curve is read from Bloomberg (ticker cells) or typed in, and interpolated linearly in days.  The cells
    of the VİOP sheet and of the Forward sheet that held the ``BFXFORWARD`` calls now read the forward chosen
    here (source ``Otomatik``: from the swap rate when spot and rates are there, otherwise ``BFXFORWARD``).
    The ``BFXFORWARD`` calls themselves moved here together with the values Excel recorded for them, so
    offline the pages still show exactly what Excel showed.
    """
    b = SheetBuilder(model, XAU_SHEET)
    # ---- spot and settings
    b.title("A1", "ALTIN  ·  spot ve forward kaynağı  (XAUUSD forward, BFXFORWARD yerine altın swap faizinden)")
    b.head("A2", ["Spot / ayar", "Bid", "Ask", "Mid", "Açıklama"])
    b.set("A3", "Spot ticker", bold=True)
    b.input("B3", "XAU Curncy")
    b.note("E3", "Bloomberg altın spot (USD/ons)")
    b.set("A4", "Spot · Bloomberg", bold=True)
    b.set("B4", '=_xll.BDP($B$3,"BID")', fmt=NUM2)
    b.set("C4", '=_xll.BDP($B$3,"ASK")', fmt=NUM2)
    b.set("D4", '=IFERROR(($B$4+$C$4)/2,"")', fmt=NUM2)
    b.set("A5", "Spot · manuel", bold=True)
    b.input("B5", None, fmt=NUM2)
    b.input("C5", None, fmt=NUM2)
    b.note("E5", "boş = Bloomberg")
    b.set("A6", "Spot · kullanılan", bold=True)
    b.set("B6", "=IF(N($B$5)>0,$B$5,$B$4)", fmt=NUM2, bold=True)
    b.set("C6", "=IF(N($C$5)>0,$C$5,$C$4)", fmt=NUM2, bold=True)
    b.set("D6", '=IFERROR(($B$6+$C$6)/2,"")', fmt=NUM2, bold=True)
    b.set("A7", "Spot valör · Bloomberg", bold=True)
    settle = '_xll.BDP($B$3,"SETTLE_DT")'
    b.set("B7", '=IFERROR(DATE(YEAR(%(s)s),MONTH(%(s)s),DAY(%(s)s)),"")' % {"s": settle}, fmt=DATE)
    b.set("A8", "Spot valör · manuel", bold=True)
    b.input("B8", None, fmt=DATE)
    b.note("E8", "boş = Bloomberg; o da yoksa USDTRY spot valörü (VIOP!K3)")
    b.set("A9", "Spot valör · kullanılan", bold=True)
    b.set("B9", "=IF(ISNUMBER($B$8),$B$8,IF(ISNUMBER($B$7),$B$7,DATE(YEAR(VIOP!$K$3),MONTH(VIOP!$K$3),DAY(VIOP!$K$3))))", fmt=DATE, bold=True)
    b.set("A10", "Faiz alanı", bold=True)
    b.input("B10", "PX_LAST")
    b.note("E10", "swap faizi ticker'larından okunan Bloomberg alanı (PX_LAST, MID, PX_MID …)")
    b.set("A11", "Kaynak", bold=True)
    b.input("B11", XAU_SOURCES[0])
    b.dropdown("B11", XAU_SOURCES)
    l1, l2 = XAU_CURVE
    nodes = "$Q$%d" % l1
    b.set("C11", ('=IF($B$11="BFXFORWARD","BFXFORWARD (seçildi)",IF(AND(ISNUMBER($D$6),%(n)s>0),"Swap faizi · "&%(n)s&" vade",'
                  'IF($B$11="Swap faizi","Swap faizi seçili: "&IF(ISNUMBER($D$6),"swap faizi","spot")&" yok",'
                  'IF(ISNUMBER($D$6),"Swap faizi yok → BFXFORWARD","Spot yok → BFXFORWARD"))))') % {"n": nodes}, bold=True)
    b.note("E11", "Otomatik = spot ve swap faizi varsa swap faizinden, yoksa BFXFORWARD")
    b.set("A12", "Ticker eki", bold=True)
    b.input("B12", XAU_TICKER_KEY)
    b.note("E12", "swap faizi ticker'ının sarı tuşu: XAUSR1M + Curncy = \"XAUSR1M Curncy\"")
    b.note("A13", "Canlıda spot ve altın swap faizi (XAUSR…) Bloomberg'den gelir; ticker'lar aşağıdaki tablodadır, faiz elle de yazılabilir. "
                  "Kayıtlı veri modunda altın spotu ve swap faizi kaydı yoktur; forward Excel'in kaydettiği BFXFORWARD değerlerinden okunur, spot "
                  "ve faizi elle girerek hesabı deneyebilirsiniz.")

    # ---- gold swap rate curve
    b.title("A14", "ALTIN  ·  swap faizi eğrisi  (XAUSR, % ACT/360; Bloomberg ticker'ı ya da manuel — sarı hücreler girdi)")
    b.head("A15", ["Vade", "Valör", "Gün", "Ticker", "Bloomberg %", "Manuel %", "Swap %", "Fwd bid", "Fwd ask", "Puan (mid)", "USD % (bilgi)",
                   "İma lease % (bilgi)"])
    b.head("N15", ["Sıra", "Gün (sıralı)", "Faiz (sıralı)", "Düğüm"])
    xs, ys = "$O$%d:$O$%d" % (l1, l2), "$P$%d:$P$%d" % (l1, l2)
    for i, (label, months, root) in enumerate(XAU_TENORS):
        r = l1 + i
        f = {"r": r, "k": i + 1, "l1": l1, "l2": l2, "usd": _USD_CURVE}
        b.set("A%d" % r, label, bold=True, align="center")
        b.set("B%d" % r, "=WORKDAY($B$9+6,1)" if months is None else "=WORKDAY(EDATE($B$9,%d)-1,1)" % months, fmt=DATE)
        b.set("C%d" % r, "=$B%(r)d-$B$9" % f, fmt=INT0)
        b.input("D%d" % r, root)
        # a ticker root gets the yellow key of B12; a full ticker (with a space) is used as it is typed
        b.set("E%d" % r, ('=IF(TRIM($D%(r)d&"")="","",_xll.BDP(IF(ISNUMBER(SEARCH(" ",TRIM($D%(r)d))),TRIM($D%(r)d),'
                          'TRIM($D%(r)d)&" "&TRIM($B$12)),$B$10))') % f, fmt="0.000")
        b.input("F%d" % r, None, fmt="0.000")
        b.set("G%d" % r, '=IF(ISNUMBER($F%(r)d),$F%(r)d,IF(ISNUMBER($E%(r)d),$E%(r)d,""))' % f, fmt="0.000", bold=True)
        b.set("H%d" % r, '=IFERROR(IF($G%(r)d="","",$B$6*(1+$G%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM2)
        b.set("I%d" % r, '=IFERROR(IF($G%(r)d="","",$C$6*(1+$G%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM2)
        b.set("J%d" % r, '=IFERROR(IF($G%(r)d="","",($H%(r)d+$I%(r)d)/2-$D$6),"")' % f, fmt=NUM2)
        # for information only: the USD OIS rate of the tenor and the lease rate the swap rate implies with it
        b.set("K%d" % r, '=_xll.BINTERPOL(%(usd)s,$C%(r)d,"LINEAR")' % f, fmt="0.000", color=NOTE_COLOR)
        b.set("L%d" % r, '=IFERROR(IF($G%(r)d="","",((1+$K%(r)d/100*$C%(r)d/360)/(1+$G%(r)d/100*$C%(r)d/360)-1)*360/$C%(r)d*100),"")' % f,
              fmt="0.000", color=NOTE_COLOR)
        # the quoted tenors only, in order (a tenor without a rate is left out of the interpolation)
        b.set("N%d" % r, '=IF(ISNUMBER($G%(r)d),COUNT($G$%(l1)d:$G%(r)d),"")' % f, fmt="0")
        b.set("O%d" % r, '=IFERROR(INDEX($C$%(l1)d:$C$%(l2)d,MATCH(%(k)d,$N$%(l1)d:$N$%(l2)d,0)),"")' % f, fmt="0")
        b.set("P%d" % r, '=IFERROR(INDEX($G$%(l1)d:$G$%(l2)d,MATCH(%(k)d,$N$%(l1)d:$N$%(l2)d,0)),"")' % f, fmt="0.000")
    b.set(nodes.replace("$", ""), "=COUNT($G$%d:$G$%d)" % (l1, l2), fmt="0")
    b.note("A%d" % (l2 + 1), "Swap % = Manuel doluysa o, değilse ticker'ın Bloomberg değeri (yüzde olarak: 0,45 = %0,45). Fwd = spot·(1 + swap·g/360): "
                             "altın faizi doğrudan uygulanır, USD faizi hesaba girmez. Aradaki günler lineer, uçlarda sabit; faizi olmayan vade "
                             "atlanır. Ticker = kök + ticker eki (boşluklu tam ticker yazılırsa aynen kullanılır). USD % ve ima lease yalnızca "
                             "bilgi içindir (lease ≈ USD − swap).")

    # ---- the dates the other sheets need
    t1, t2 = XAU_TARGETS
    b.title("A%d" % (t1 - 2), "ALTIN  ·  XAUUSD forward  (VİOP altın tablolarına ve Forward sayfasına giden değerler)")
    b.head("A%d" % (t1 - 1), ["Hedef", "Valör", "Gün", "Swap %", "Swap fwd bid", "Swap fwd ask", "BFXFORWARD bid", "BFXFORWARD ask",
                              "Kullanılan bid", "Kullanılan ask", "Kaynak", "BFX ima swap %", "Swap − BFX (mid)"])
    rate_at = "IF(%s=0,\"\",%s)" % (nodes, lin("$C%(r)d", xs, ys, nodes))
    viop_bid, viop_ask, usd_c = ("S", "T", "U"), ("M", "N", "O"), ("M", "N", "O")
    targets = []
    for i in range(3):       # VİOP XAUTRY: the BID table divides by the ask outright, the ASK table by the bid outright
        targets.append(("=VIOP!%s45" % viop_ask[i], "=VIOP!%s48" % viop_ask[i], "VIOP!%s46" % viop_bid[i], "VIOP!%s46" % viop_ask[i],
                        ("VIOP", "%s58" % viop_bid[i]), ("VIOP", "%s58" % viop_ask[i])))
    for i in range(3):       # VİOP XAUUSD: only the ask outright is used there
        targets.append(("=VIOP!%s60" % usd_c[i], "=VIOP!%s63" % usd_c[i], "VIOP!%s61" % usd_c[i], "VIOP!%s61" % usd_c[i],
                        None, ("VIOP", "%s68" % usd_c[i])))
    targets.append(("Forward tarihi (Forward!D2)", "=Forward!$D$2", "Forward!$D$2", "Forward!$D$2", ("Forward", "I29"), ("Forward", "J29")))
    for i, (label, date, bid_date, ask_date, bid_src, ask_src) in enumerate(targets):
        r = t1 + i
        b.set("A%d" % r, label, bold=True)
        b.set("B%d" % r, date, fmt=DATE)
        b.set("G%d" % r, '=_xll.BFXFORWARD("XAUUSD",%s,"BidOutright")' % bid_date, fmt=NUM4)
        b.set("H%d" % r, '=_xll.BFXFORWARD("XAUUSD",%s,"AskOutright")' % ask_date, fmt=NUM4)
        if bid_src:
            b.recorded("G%d" % r, recorded_value(model, *bid_src))
            SheetBuilder(model, bid_src[0]).patch(bid_src[1], "=%s!$I$%d" % (XAU_SHEET, r))
        if ask_src:
            b.recorded("H%d" % r, recorded_value(model, *ask_src))
            SheetBuilder(model, ask_src[0]).patch(ask_src[1], "=%s!$J$%d" % (XAU_SHEET, r))
    for r in range(t1 + len(targets), t2 + 1):
        b.set("A%d" % r, "serbest", color=NOTE_COLOR)
        b.input("B%d" % r, None, fmt=DATE)
        b.set("G%d" % r, '=IF(ISNUMBER($B%d),_xll.BFXFORWARD("XAUUSD",$B%d,"BidOutright"),"")' % (r, r), fmt=NUM4)
        b.set("H%d" % r, '=IF(ISNUMBER($B%d),_xll.BFXFORWARD("XAUUSD",$B%d,"AskOutright"),"")' % (r, r), fmt=NUM4)
    for r in range(t1, t2 + 1):
        f = {"r": r}
        b.set("C%d" % r, '=IF(ISNUMBER($B%(r)d),$B%(r)d-$B$9,"")' % f, fmt=INT0)
        b.set("D%d" % r, '=IFERROR(IF($C%d="","",%s),"")' % (r, rate_at % f), fmt="0.000")
        b.set("E%d" % r, '=IFERROR(IF(OR($C%(r)d="",$D%(r)d=""),"",$B$6*(1+$D%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("F%d" % r, '=IFERROR(IF(OR($C%(r)d="",$D%(r)d=""),"",$C$6*(1+$D%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("I%d" % r, '=IF($B$11="BFXFORWARD",$G%(r)d,IF(ISNUMBER($E%(r)d),$E%(r)d,IF($B$11="Swap faizi",NA(),$G%(r)d)))' % f, fmt=NUM4, bold=True)
        b.set("J%d" % r, '=IF($B$11="BFXFORWARD",$H%(r)d,IF(ISNUMBER($F%(r)d),$F%(r)d,IF($B$11="Swap faizi",NA(),$H%(r)d)))' % f, fmt=NUM4, bold=True)
        b.set("K%d" % r, ('=IF($C%(r)d="","",IF(AND($B$11<>"BFXFORWARD",ISNUMBER($F%(r)d)),"Swap faizi",'
                          'IF(ISNUMBER($H%(r)d),"BFXFORWARD","yok")))') % f, align="center")
        b.set("L%d" % r, '=IFERROR(IF($C%(r)d="","",((($G%(r)d+$H%(r)d)/2)/$D$6-1)*360/$C%(r)d*100),"")' % f, fmt="0.000")
        b.set("M%d" % r, '=IFERROR(($E%(r)d+$F%(r)d)/2-($G%(r)d+$H%(r)d)/2,"")' % f, fmt=NUM2)
    b.note("A%d" % (t2 + 1), "Kullanılan = Kaynak'a göre swap faizinden forward ya da BFXFORWARD; VİOP XAUTRY BID tablosu ask'ı, ASK tablosu bid'i, VİOP "
                             "XAUUSD ask'ı, Forward!I29:J29 bid/ask'ı okur. BFX ima swap = BFXFORWARD'ın (mid) spot'a göre ima ettiği swap faizi.")

    # ---- "Interest 2 SP" and "SP 2 Interest" for gold: the VİOP XAUTRY price at a given TRY / USD / gold swap
    #      rate, and the rates that a price implies.  Every driver is a cell the trader may type over; left alone
    #      it is filled from the market.  The last column is free: its second date (and its rates) are typed.
    c0 = XAU_CALC
    b.title("A%d" % (c0 - 1), "VİOP XAUTRY  ·  faizden fiyat, fiyattan faiz  (sarı hücreler girdi; boş bırakılan piyasadan dolar)")
    b.head("A%d" % c0, ["Kontrat", "=VIOP!M45", "=VIOP!N45", "=VIOP!O45", "Serbest"])
    for i, text in enumerate(XAU_CALC_LABELS):
        b.set("A%d" % (c0 + 1 + i), text, bold=True)
    rows = dict((name, c0 + 1 + k) for k, name in enumerate(XAU_CALC_ROWS))
    for i, col in enumerate("BCDE"):
        free = i == 3
        f = {"c": col, "x": XAU_SHEET, "g": GRAMS_PER_OUNCE, "usdc": _USD_CURVE}
        if not free:
            f.update({"vb": viop_ask[i], "va": viop_bid[i], "t": t1 + i})      # columns of the VİOP XAUTRY BID / ASK tables
        f.update(rows)
        f["gd"] = "(%(c)s%(d2)d-$B$9)" % f                                     # days from the gold spot value date
        f["curve"] = "IF(%s=0,NA(),%s)" % (nodes, lin(f["gd"], xs, ys, nodes))  # the swap rate curve at that many days
        b.input("%(c)s%(d1)d" % f, ("=VIOP!M47" if free else "=VIOP!%(vb)s47") % f, fmt=DATE)
        b.input("%(c)s%(d2)d" % f, None if free else "=VIOP!%(vb)s48" % f, fmt=DATE)
        b.set("%(c)s%(n)d" % f, '=IF(AND(ISNUMBER(%(c)s%(d1)d),ISNUMBER(%(c)s%(d2)d)),%(c)s%(d2)d-%(c)s%(d1)d,"")' % f, fmt=INT0)
        b.input("%(c)s%(s)d" % f, ("=VIOP!M50" if free else "=VIOP!%(vb)s50") % f, fmt=NUM4)
        b.input("%(c)s%(xau)d" % f, "=$D$6", fmt=NUM2)
        # USD rate of the calculator's own number of days (the VİOP gold tables read the same curve at theirs)
        b.input("%(c)s%(usd)d" % f, '=IFERROR(_xll.BINTERPOL(%(usdc)s,%(c)s%(n)d,"LINEAR"),"")' % f, fmt="0.000")
        # default TRY rate: what the USDTRY contract of the same expiry implies (mid of the VIOP BID / ASK tables)
        b.input("%(c)s%(try)d" % f, None if free else (
            "=IFERROR((INDEX(VIOP!$M$13:$X$13,MATCH(%(c)s%(d2)d,VIOP!$M$9:$X$9,0))"
            "+INDEX(VIOP!$M$25:$X$25,MATCH(%(c)s%(d2)d,VIOP!$M$21:$X$21,0)))/2*100,VIOP!%(vb)s52*100)") % f, fmt="0.00")
        b.input("%(c)s%(swap)d" % f, None, fmt="0.000")
        # gold forward: from the swap rate typed here; else the forward in use for the contract's own date; for any
        # other date the swap rate curve; typed over when none of them is there
        from_curve = 'IFERROR(%(c)s%(xau)d*(1+%(curve)s/100*%(gd)s/360),"")' % f
        own = from_curve if free else 'IF(%(c)s%(d2)d=$B$%(t)d,IFERROR(($I$%(t)d+$J$%(t)d)/2,""),%(fc)s)' % dict(f, fc=from_curve)
        # (no second date - the free column before one is typed - no forward: its days would count from day zero)
        b.input("%(c)s%(xfwd)d" % f, ('=IF(NOT(ISNUMBER(%(c)s%(d2)d)),"",IF(ISNUMBER(%(c)s%(swap)d),'
                                       'IFERROR(%(c)s%(xau)d*(1+%(c)s%(swap)d/100*%(gd)s/360),""),%(own)s))')
                % dict(f, own=own), fmt=NUM4, bold=True)
        b.set("%(c)s%(simp)d" % f, ('=IF(ISNUMBER(%(c)s%(swap)d),%(c)s%(swap)d,'
                                    'IFERROR((%(c)s%(xfwd)d/%(c)s%(xau)d-1)*360/%(gd)s*100,""))') % f, fmt="0.000")
        b.set("%(c)s%(fwd)d" % f, '=IFERROR(%(c)s%(s)d*(1+%(c)s%(try)d/100/360*%(c)s%(n)d)/(1+%(c)s%(usd)d/100/360*%(c)s%(n)d),"")' % f, fmt=NUM4)
        b.set("%(c)s%(sp)d" % f, '=IFERROR((%(c)s%(fwd)d-%(c)s%(s)d)*10000,"")' % f, fmt=INT0)
        b.set("%(c)s%(spd)d" % f, '=IFERROR(%(c)s%(sp)d/%(c)s%(n)d,"")' % f, fmt="#,##0.0")
        b.set("%(c)s%(teo)d" % f, '=IFERROR(%(c)s%(xfwd)d*%(c)s%(fwd)d/%(g)s,"")' % f, fmt=NUM2, bold=True)
        b.input("%(c)s%(vbid)d" % f, None if free else "=VIOP!%(vb)s57" % f, fmt=NUM2)
        b.input("%(c)s%(vask)d" % f, None if free else "=VIOP!%(va)s57" % f, fmt=NUM2)
        for side, diff, imp, gimp in (("vbid", "dbid", "ibid", "gbid"), ("vask", "dask", "iask", "gask")):
            k = dict(f, p="%s%d" % (col, rows[side]))
            b.set("%s%d" % (col, rows[diff]), '=IFERROR(IF(%(p)s="","",%(c)s%(teo)d-%(p)s),"")' % k, fmt=NUM2)
            # the way back: the USDTRY forward the price stands for, and the TRY rate that makes it
            b.set("%s%d" % (col, rows[imp]), ('=IFERROR(IF(%(p)s="","",((%(p)s*%(g)s/%(c)s%(xfwd)d)/%(c)s%(s)d'
                                              '*(1+%(c)s%(usd)d/100/360*%(c)s%(n)d)-1)*360/%(c)s%(n)d*100),"")') % k, fmt="0.00", bold=True)
            # ... or, at the TRY rate above, the gold swap rate that makes it
            b.set("%s%d" % (col, rows[gimp]), ('=IFERROR(IF(%(p)s="","",((%(p)s*%(g)s/%(c)s%(fwd)d)/%(c)s%(xau)d-1)*360/%(gd)s*100),"")') % k,
                  fmt="0.000")
        b.set("%(c)s%(sxt)d" % f, '=IFERROR(%(c)s%(xau)d*%(c)s%(s)d/%(g)s,"")' % f, fmt=NUM2)
        b.set("%(c)s%(on)d" % f, '=IFERROR(360*((1+%(c)s%(try)d/100*%(c)s%(n)d/360)^(1/%(c)s%(n)d)-1)*100,"")' % f, fmt="0.00")
    b.note("A%d" % (c0 + len(XAU_CALC_LABELS) + 1),
           "Faizden fiyat: XAUTRY teorik = XAUUSD fwd · USDTRY fwd / 31,1035; USDTRY fwd = spot·(1+TRY·VKGS/360)/(1+USD·VKGS/360). "
           "Fiyattan faiz: 'VIOP bid / ask' satırındaki fiyat (piyasa ya da üzerine yazdığın fiyat) için ima TRY % ve, TRY % satırındaki "
           "faizle aynı fiyatı veren, ima altın swap %. Her girdi piyasadan dolar; üzerine yazabilir, silerek piyasaya dönebilirsin. "
           "Altın swap % doluysa XAUUSD fwd = spot·(1+swap·g/360); boşsa kontratın kendi tarihinde üstteki 'Kullanılan' forward (mid), başka "
           "bir tarihte swap faizi eğrisi. 'Serbest' sütununda 2. tarihi ve TRY faizini sen yazarsın; Bloomberg'den altın verisi gelmiyorsa "
           "XAUUSD spot ya da XAUUSD fwd'ı da elle yaz. (VİOP tabloları bid için ask, ask için bid outright'ı kullanır; burada tek forward "
           "kullanıldığından ima faiz birkaç baz puan farklı olabilir.)")


# ---------------------------------------------------------------------------------------------- VİOP history
VH_SHEET = "EK_VIOP"
VH_SLOTS = 6                              # lines of a chart (the palette has six colours)
VH_FIRST = 12                             # first row of the history here
VH_ROWS = 260                             # rows kept for it (a BDH block of week days)
VH_MAX_DAYS = 240                         # business days that can be asked for (their week days fit the rows)
VH_DAYS = 120                             # ... and what is asked for at first
VH_LIVE = VH_FIRST + VH_ROWS              # the row after the history: today's last prices
VH_DEFAULT = (1, 2, 3, 4)                 # contracts drawn at first: the four nearest expiries
VH_SOURCE = 380                           # first history row of the VİOP sheet: the formulas taken over from it
VH_SOURCE_LIVE = 511                      # ... and its "live last price" row
_VH_HOLIDAYS = "Motor!$A$361:$A$523"
_VH_OIS = ("Y", "Z", "AA", "AB", "AC", "AD")          # TYSOA, TYSOB, TYSOC, TYSOF, TYSOI, TYSO1 on the VİOP sheet
_VH_USD = ("AE", "AF", "AG", "AH")                    # USSOA, USSOC, USSOF, USSO1
_VH_ZERO = ("AW", "AX", "AY", "AZ", "BA", "BB")       # DF 3A / 6A / 9A, zero 6A / 9A / 1Y


def _vh_columns() -> Dict[str, List[str]]:
    """Columns of the series block: A date, B spot, then one group per kind."""
    out: Dict[str, List[str]] = {}
    c = 3
    for name, n in (("px", VH_SLOTS), ("ois", len(_VH_OIS)), ("usd", len(_VH_USD)), ("zero", len(_VH_ZERO)), ("days", VH_SLOTS),
                    ("imp", VH_SLOTS), ("baz", VH_SLOTS), ("ois360", VH_SLOTS)):
        out[name] = [index_to_col(c + k) for k in range(n)]
        c += n
    return out


VH_COLS = _vh_columns()


def _viop_hist_check(model: Model) -> None:
    _need_sheets(model, "VIOP", "Motor")
    R = VH_SOURCE
    _need_formula(model, "VIOP", "K%d" % R, "BDH($S$340")
    _need_formula(model, "VIOP", "M%d" % R, "BDH(L$1")
    for col in _VH_OIS + _VH_USD:
        _need_formula(model, "VIOP", "%s%d" % (col, R), "BDH(")
    for col in _VH_ZERO:
        _need_formula(model, "VIOP", "%s%d" % (col, R), "$K%d" % R)
    text = _need_formula(model, "VIOP", "AJ%d" % R, "$M$9-WORKDAY($K%d,1,%s)" % (R, _VH_HOLIDAYS))
    for piece in ("M%d/$L%d" % (R, R), "N($AE%d)" % R, "N($AH%d)" % R, "N($Y%d)" % R, "N($BB%d)" % R, "*10000"):
        if piece not in text:
            raise ValueError("VIOP!AJ%d beklenen baz formülü değil (%s yok)" % (R, piece))
    for addr in ("K%d" % VH_SOURCE_LIVE, "M%d" % VH_SOURCE_LIVE, "AJ%d" % VH_SOURCE_LIVE, "M9"):
        _need_formula(model, "VIOP", addr)
    _need_formula(model, "VIOP", "O340", "$M$340")
    _need_formula(model, "VIOP", "Q340", "TODAY()")
    if not isinstance(model.sheet("VIOP").consts.get(parse_a1("L1")), str):
        raise ValueError("VIOP!L1 kontrat ticker'ı değil")


def _tto_viop_history(model: Model) -> None:
    """The implied TRY rate of the VİOP contracts and their spread over OIS, day by day - what two charts of
    the VİOP page draw.

    The VİOP sheet keeps a history of its own (rows 380-509: spot, the twelve contracts and the OIS tenors from
    ``BDH``) and computes the basis of every contract on every day - but only for an average and a z-score over
    the last "Geçmiş" days (20).  A chart wants more days than a z-score does, and the two must not share a
    window.  So this sheet asks for its own history, of the contracts that are drawn (up to six, chosen by their
    order: 1 = nearest expiry) and as long as its own "Geçmiş" cell says, and computes with the sheet's own
    formulas, taken over cell by cell:

        implied TRY %  = ((price / spot) · (1 + USD · g/360) − 1) · 360/g      g = expiry − (day + 1 business day)
        VİOP − OIS, bp = the sheet's "Baz" formula (``VIOP!AJ380``) on this sheet's rows
        OIS % (360)    = implied − basis: the OIS rate of the same days the formula compared it with

    The row after the history is the VİOP sheet's live row (today's last prices), so the lines end at "now".
    """
    b = SheetBuilder(model, VH_SHEET)
    slots = [index_to_col(2 + k) for k in range(VH_SLOTS)]                     # B … G: one per line (settings table)
    r0, r1, live = VH_FIRST, VH_FIRST + VH_ROWS - 1, VH_LIVE
    C = VH_COLS
    b.title("A1", "VİOP GEÇMİŞİ  ·  grafiklerde çizilen kontratlar ve geçmişin uzunluğu  (1 = en yakın vade; boş = çizilmez)")
    b.head("A2", [""] + ["Çizgi %d" % (k + 1) for k in range(VH_SLOTS)])
    for r, text in ((3, "Kontrat sırası"), (4, "Kontrat"), (5, "Vade"), (6, "Grafikteki adı"), (7, "Gün sayısı (çizilen)"),
                    (8, "Geçmiş (iş günü)")):
        b.set("A%d" % r, text, bold=True)
    for k, c in enumerate(slots):
        f = {"c": c, "imp": C["imp"][k], "a": r0, "z": r1}
        b.input("%s3" % c, VH_DEFAULT[k] if k < len(VH_DEFAULT) else None, fmt="0", align="center")
        b.dropdown("%s3" % c, [str(i) for i in range(1, 13)])
        b.set("%s4" % c, '=IF(ISNUMBER(%(c)s3),IFERROR(INDEX(VIOP!$L$1:$W$1,%(c)s3),""),"")' % f, align="center")
        b.set("%s5" % c, '=IF(ISNUMBER(%(c)s3),IFERROR(INDEX(VIOP!$M$9:$X$9,%(c)s3),""),"")' % f, fmt=DATE, align="center")
        b.set("%s6" % c, ('=IF(ISNUMBER(%(c)s5),TEXT(%(c)s5,"dd.mm.yy")&" · "&TRIM(SUBSTITUTE(%(c)s4&""," Curncy","")),"")') % f, align="center")
        b.set("%s7" % c, '=IF(ISNUMBER(%(c)s5),COUNT($%(imp)s$%(a)d:$%(imp)s$%(z)d),"")' % f, fmt="0", align="center")
    b.input("B8", VH_DAYS, fmt="0", align="center")
    b.set("C8", "Başlangıç", bold=True, align="right")
    b.set("D8", "=WORKDAY(TODAY(),-MIN(MAX(N($B$8),1),%d),%s)" % (VH_MAX_DAYS, _VH_HOLIDAYS), fmt=DATE, align="center")
    b.set("E8", "Bitiş", bold=True, align="right")
    b.set("F8", "=" + formula_of(model, "VIOP", "Q340"), fmt=DATE, align="center")       # yesterday, as the sheet's own history ends
    b.note("A9", "Grafikler kendi geçmişini okur (Bloomberg BDH, son işlem): 'Geçmiş' kaç iş günü geriye gidileceğidir (en çok %d) ve "
                 "BAZ GEÇMİŞİ tablosunun istatistik penceresinden (z-skor, ortalama) bağımsızdır. Çizgilerin son noktası bugünün canlı son "
                 "fiyatıdır. Kontratın fiyatı olmayan gün çizilmez. Kayıtlı veri modunda VİOP geçmişi kaydı yoktur: yalnızca canlı nokta "
                 "görünür." % VH_MAX_DAYS)

    head = r0 - 1
    b.head("A%d" % head, ["Tarih", "Spot"] + ["Fiyat · %d" % (k + 1) for k in range(VH_SLOTS)]
           + ["TYSOA", "TYSOB", "TYSOC", "TYSOF", "TYSOI", "TYSO1", "USSOA", "USSOC", "USSOF", "USSO1", "DF 3A", "DF 6A", "DF 9A",
              "Zero 6A %", "Zero 9A %", "Zero 1Y %"]
           + ["%s · %d" % (label, k + 1) for label in ("gün", "ima %", "baz bp", "OIS %") for k in range(VH_SLOTS)])
    window = {"$O$340": "$D$8", "$Q$340": "$F$8"}
    R = VH_SOURCE
    # ---- the history itself: the sheet's own BDH calls with this sheet's window (dates and spot, the contracts
    #      that are drawn, the OIS and USD OIS tenors).  Array formulas, as in the workbook: the block they return
    #      is written into the rows below.
    b.set("A%d" % r0, "=" + transplant(formula_of(model, "VIOP", "K%d" % R), dict(window, **{"$S$340": "VIOP!$S$340"})), fmt=DATE, array=True)
    for k, c in enumerate(C["px"]):
        b.set("%s%d" % (c, r0), "=" + transplant(formula_of(model, "VIOP", "M%d" % R), dict(window, **{"L$1": "$%s$4" % slots[k]})), fmt=NUM4, array=True)
    for src, c in zip(_VH_OIS + _VH_USD, C["ois"] + C["usd"]):
        b.set("%s%d" % (c, r0), "=" + transplant(formula_of(model, "VIOP", "%s%d" % (src, R)), window), fmt="0.000", array=True)
    usd = ("IF({g}<=30,N({a}),IF({g}<=91,N({a})+(N({b})-N({a}))*({g}-30)/61,IF({g}<=182,N({b})+(N({c})-N({b}))*({g}-91)/91,"
           "IF({g}<=365,N({c})+(N({d})-N({c}))*({g}-182)/183,N({d})))))")
    zero_text = [formula_of(model, "VIOP", "%s%d" % (col, R)) for col in _VH_ZERO]
    basis_text = formula_of(model, "VIOP", "AJ%d" % R)
    for r in range(r0, r1 + 1):
        if r > r0:
            b.sheet.styles[parse_a1("A%d" % r)] = b.sheet.styles[parse_a1("A%d" % r0)]          # the dates that spill below
        same = {"$K%d" % R: "$A%d" % r}
        same.update({"$%s%d" % (src, R): "$%s%d" % (c, r) for src, c in zip(_VH_OIS + _VH_USD + _VH_ZERO, C["ois"] + C["usd"] + C["zero"])})
        for text, c in zip(zero_text, C["zero"]):
            b.set("%s%d" % (c, r), "=" + transplant(text, same), fmt="0.0000")
        for k in range(VH_SLOTS):
            f = {"exp": "$%s$5" % slots[k], "r": r, "px": "$%s%d" % (C["px"][k], r), "g": "$%s%d" % (C["days"][k], r),
                 "imp": C["imp"][k], "baz": C["baz"][k], "hol": _VH_HOLIDAYS}
            f["usd"] = usd.format(g=f["g"], **{n: "$%s%d" % (c, r) for n, c in zip("abcd", C["usd"])})
            # days from the day's T+1 to the expiry, as the sheet counts them
            b.set("%s%d" % (C["days"][k], r), '=IF(AND(ISNUMBER(%(exp)s),ISNUMBER($A%(r)d)),%(exp)s-WORKDAY($A%(r)d,1,%(hol)s),"")' % f, fmt="0")
            # (a day without a price for the contract - not listed yet, a hole in the history - is left out: an
            #  empty cell of a spilled BDH block counts as 0, which would otherwise be drawn as a rate of -333 %)
            b.set("%s%d" % (C["imp"][k], r), ('=IFERROR(IF(AND(ISNUMBER(%(g)s),N(%(px)s)>0,N($B%(r)d)>0,N(%(g)s)>0),'
                                              '((%(px)s/$B%(r)d)*(1+%(usd)s/100*%(g)s/360)-1)*360/%(g)s*100,""),"")') % f, fmt="0.00")
            own = dict(same, **{"M%d" % R: f["px"], "$L%d" % R: "$B%d" % r, "$M$9": f["exp"]})
            b.set("%s%d" % (C["baz"][k], r), '=IF(ISNUMBER($%s%d),%s,"")' % (C["imp"][k], r, transplant(basis_text, own).lstrip("=")), fmt="0.0")
            b.set("%s%d" % (C["ois360"][k], r), '=IF(AND(ISNUMBER($%(imp)s%(r)d),ISNUMBER($%(baz)s%(r)d)),$%(imp)s%(r)d-$%(baz)s%(r)d/100,"")' % f,
                  fmt="0.00")
    # ---- today: the VİOP sheet's live row
    L = VH_SOURCE_LIVE
    b.set("A%d" % live, '=IF(ISNUMBER(VIOP!$K$%d),VIOP!$K$%d,"")' % (L, L), fmt=DATE)
    b.set("B%d" % live, '=IF(ISNUMBER(VIOP!$L$%d),VIOP!$L$%d,"")' % (L, L), fmt=NUM4)
    for k in range(VH_SLOTS):
        f = {"sel": "$%s$3" % slots[k], "exp": "$%s$5" % slots[k], "r": live, "L": L, "g": "$%s%d" % (C["days"][k], live),
             "imp": C["imp"][k], "baz": C["baz"][k], "hol": _VH_HOLIDAYS}
        f["usd"] = usd.format(g=f["g"], **{n: "VIOP!$%s$%d" % (c, L) for n, c in zip("abcd", _VH_USD)})
        f["px"] = "INDEX(VIOP!$M$%(L)d:$X$%(L)d,%(sel)s)" % f
        f["b"] = "INDEX(VIOP!$AJ$%(L)d:$AU$%(L)d,%(sel)s)" % f
        b.set("%s%d" % (C["days"][k], live), ('=IF(AND(ISNUMBER(%(exp)s),ISNUMBER(VIOP!$K$%(L)d)),'
                                             '%(exp)s-WORKDAY(VIOP!$K$%(L)d,1,%(hol)s),"")') % f, fmt="0")
        b.set("%s%d" % (C["imp"][k], live), ('=IFERROR(IF(AND(ISNUMBER(%(g)s),N(%(px)s)>0,N(VIOP!$L$%(L)d)>0,N(%(g)s)>0),'
                                            '((%(px)s/VIOP!$L$%(L)d)*(1+%(usd)s/100*%(g)s/360)-1)*360/%(g)s*100,""),"")') % f, fmt="0.00")
        b.set("%s%d" % (C["baz"][k], live), '=IFERROR(IF(AND(ISNUMBER($%(imp)s%(r)d),ISNUMBER(%(b)s)),%(b)s,""),"")' % f, fmt="0.0")
        b.set("%s%d" % (C["ois360"][k], live), '=IF(AND(ISNUMBER($%(imp)s%(r)d),ISNUMBER($%(baz)s%(r)d)),$%(imp)s%(r)d-$%(baz)s%(r)d/100,"")' % f,
              fmt="0.00")


# ---------------------------------------------------------------------------------------------- forward rates
#: The Forward page's pricing tables, on the forward quote sheet below its two matrices:
FR_USD = 44            # USDTRY at the value date: title, value date / spot / USD rates, header, 4 curves, "Elle", its settings, note
FR_EUR = 55            # EURTRY: the same without the settings ("Elle" follows the USDTRY table's)
FR_LIST = 65           # the free forward list: title, TRY curve, header, FR_FREE rows, note
FR_TENOR = 80          # the TRY curves' rates by tenor: title, header, value date, FR_TENORS, FR_FREE_DATES free dates, note
FR_FREE = 10
FR_FREE_DATES = 3
#: the TRY curves of the Forward sheet: name, the USDTRY row of its table there, its bid and its ask rate of the value date
FR_CURVES = (("Offshore", "D30", "$I$22", "$K$22"), ("OIS", "D31", "$O$25", "$P$25"), ("VİOP", "D32", "$C$18", "$E$18"),
             ("RET", "D33", "$W$48", "$X$48"))
FR_NAMES = tuple(c[0] for c in FR_CURVES)
#: the nodes of each TRY curve on the Forward sheet: days from the USDTRY spot date, the mid rate (RET: its bid and its
#: ask, averaged), the number of nodes, and what makes the rate a percentage - those the sheet reads its value date from
FR_NODES = {"Offshore": ("Forward!$G$8:$G$21", ("Forward!$J$8:$J$21",), 14, 1),
            "OIS": ("Forward!$N$6:$N$18", ("Forward!$P$6:$P$18",), 13, 1),
            "VİOP": ("Forward!$B$6:$B$17", ("Forward!$D$6:$D$17",), 12, 100),
            "RET": ("Forward!$U$33:$U$47", ("Forward!$W$33:$W$47", "Forward!$X$33:$X$47"), 15, 100)}
#: the spot date of a pair (the Forward sheet's - its joint calendar's, Bloomberg's in a file the holiday sheet does not
#: fit -, or the date typed there): a date even when it comes as a text
FR_SPOT = {pair: "IFERROR(DATE(YEAR(%(d)s),MONTH(%(d)s),DAY(%(d)s)),%(d)s)" % {"d": d}
           for pair, d in (("USDTRY", "Forward!$I$2"), ("EURTRY", "Forward!$K$2"))}
#: the OIS curve of a pair's major currency (days from the pair's spot date, mid %, nodes), as the sheet reads it
FR_MAJOR = {"USDTRY": ("Forward!$U$7:$U$26", "Forward!$X$7:$X$26", 20),
            "EURTRY": ("Forward!$AA$7:$AA$26", "Forward!$AD$7:$AD$26", 20)}
FR_REACH = 31          # a curve is read up to a month past its last node; further out it gives no rate (rather than a flat one)
#: the usual tenors from the USDTRY spot date: days, or months (then the next business day of TRY and USD)
FR_TENORS = (("1W", 7, 0), ("2W", 14, 0), ("1M", 0, 1), ("2M", 0, 2), ("3M", 0, 3), ("6M", 0, 6), ("9M", 0, 9), ("1Y", 0, 12),
             ("18M", 0, 18), ("2Y", 0, 24))

#: Input cells an earlier layout of the dashboard's own sheets had and that moved since: a value a user saved in one of
#: them is dropped when it is loaded (it would land on whatever stands there now).  {book: (range, ...)}
RETIRED_INPUTS = {"tto": ("EK_FWD!B35", "EK_FWD!D35", "EK_FWD!F35", "EK_FWD!H35", "EK_FWD!J35", "EK_FWD!L35",
                          "EK_FWD!B37:C41")}       # the value-date rates of rows 33-42, now from row FR_USD on


def _fwd_rates_check(model: Model) -> None:
    """The Forward sheet's USDTRY / EURTRY tables price from these cells (the rates of the value date), and its curves
    have their nodes where the value date's rates are read from.  The tables live on the forward quote sheet, so they
    go when that one is left out."""
    _need_sheets(model, "Forward", "Motor", FWD_SHEET)
    for _, at, bid, ask in FR_CURVES:
        _need_formula(model, "Forward", at, bid)                      # the bid side of the row uses the bid rate ...
        _need_formula(model, "Forward", "F" + at[1:], ask)            # ... the ask side the ask rate
        _need_formula(model, "Forward", at, "$Y$27")                  # USD ask on the bid side, USD bid on the ask side
        _need_formula(model, "Forward", "F" + at[1:], "$W$27")
        _need_formula(model, "Forward", "D%d" % (int(at[1:]) + 12), bid)  # EURTRY: the same TRY rate, EUR days and rates
    _need_formula(model, "Forward", "D42", "$AE$27")
    _need_formula(model, "Forward", "F42", "$AC$27")
    for addr, nodes in (("I22", "$G$8:$G$21"), ("P24", "$N$6:$N$18"), ("C18", "$B$6:$B$17"), ("W48", "$U$33:$U$47"),
                        ("W27", "$U$7:$U$26"), ("AC27", "$AA$7:$AA$26")):
        _need_formula(model, "Forward", addr, nodes)
    for addr, mid in (("J8", "AVERAGE(I8,K8)"), ("D6", "AVERAGE(C6,E6)"), ("P6", '"MID"'), ("X7", '"MID"'), ("AD7", '"MID"')):
        _need_formula(model, "Forward", addr, mid)                    # the mid rates of the curves


def fr_rate(name: str, g: str) -> str:
    """The mid rate (%, simple ACT/360 zero) of a TRY curve of the Forward sheet ``g`` days after the USDTRY spot
    date, as the sheet reads its value date: linear between the nodes, flat before the first.  More than a month past
    its last node the curve has no rate ("")."""
    xs, ys, n, scale = FR_NODES[name]
    rate = "+".join(lin(g, xs, y, n) for y in ys)
    if len(ys) > 1:
        rate = "(%s)/%d" % (rate, len(ys))
    if scale != 1:
        rate = "(%s)*%d" % (rate, scale)
    return 'IF(%s>INDEX(%s,%d)+%d,"",%s)' % (g, xs, n, FR_REACH, rate)


def fr_major(pair: str, days: str) -> str:
    """The OIS mid (%) of the pair's major currency - EUR when ``pair`` holds "EURTRY", USD otherwise - ``days`` after
    the pair's spot date: the sheet's own curve."""
    rates = {name: lin(days, xs, ys, n) for name, (xs, ys, n) in FR_MAJOR.items()}
    return 'IF(%s="EURTRY",%s,%s)' % (pair, rates["EURTRY"], rates["USDTRY"])


def _tto_fwd_rates(model: Model) -> None:
    """The Forward page's pricing tables.  Every input is a cell to type over (blank = back to the market), seen by
    whoever typed it only.

    * USDTRY and EURTRY at the sheet's value date, one below the other: each TRY curve's bid / mid / ask rate, the
      outright, the swap points and the points per day - with the sheet's own formula, the same numbers as its
      USDTRY and EURTRY tables.  The "Elle" row prices a rate of one's own: a curve, then a mid (or a spread to the
      curve's mid) and a bid / ask width.  The EURTRY table takes its TRY rates from the USDTRY one.
    * the free forward list: any start and end date; the outright at the start, the major and the minor rate of the
      period come from the curves, and the four TRY curves' simple zero rates at the end date stand beside it.
    * the four TRY curves' simple zero rates at the value date, the usual tenors and dates of one's own.
    """
    b = SheetBuilder(model, FWD_SHEET)
    pct = "0.0000"
    usd_first = FR_USD + 3
    usd_last = usd_first + len(FR_CURVES) - 1
    usd_elle, usd_set = usd_last + 1, usd_last + 2
    names = "$A$%d:$A$%d" % (usd_first, usd_last)
    # ---- USDTRY and EURTRY
    for t, pair, major, days, spot, mbid, mask in (
            (FR_USD, "USDTRY", "USD", "=Forward!$U$27", "=Forward!$F$2", "=Forward!$W$27*100", "=Forward!$Y$27*100"),
            (FR_EUR, "EURTRY", "EUR", "=Forward!$AA$27", "=Forward!$G$2", "=Forward!$AC$27*100", "=Forward!$AE$27*100")):
        usd = pair == "USDTRY"
        i = t + 1
        b.title("A%d" % t, "%s FORWARD  ·  valör faizleriyle bid / mid / ask – TRY faizini, spotu ya da %s faizini değiştirin, forward ve "
                           "puanlar hemen yeniden hesaplanır" % (pair, major))
        b.set("A%d" % i, "Valör", bold=True)
        b.set("B%d" % i, "=Forward!$D$2", fmt=DATE, bold=True)
        b.set("C%d" % i, "Gün", bold=True, align="right")
        b.set("D%d" % i, days, fmt=INT0)
        b.set("E%d" % i, "Spot", bold=True, align="right")
        b.input("F%d" % i, spot, fmt=NUM4)
        b.set("G%d" % i, major + " bid %", bold=True, align="right")
        b.input("H%d" % i, mbid, fmt=pct)
        b.set("I%d" % i, major + " mid %", bold=True, align="right")
        b.set("J%d" % i, '=IFERROR(($H%d+$L%d)/2,"")' % (i, i), fmt=pct)
        b.set("K%d" % i, major + " ask %", bold=True, align="right")
        b.input("L%d" % i, mask, fmt=pct)
        b.head("A%d" % (t + 2), ["Eğri", "TRY bid %", "TRY mid %", "TRY ask %", pair + " bid", pair + " mid", pair + " ask",
                                 "Puan bid", "Puan mid", "Puan ask", "P/gün bid", "P/gün mid", "P/gün ask"])
        if usd:
            rows = [(name, "=Forward!%s*100" % bid, "=Forward!%s*100" % ask) for name, _, bid, ask in FR_CURVES]
            # "Elle": the chosen curve's mid - or the mid typed - plus the spread, the curve's own width or the one typed
            f = {"s": usd_set, "a": usd_first, "z": usd_last, "m": "MATCH($B$%d,%s,0)" % (usd_set, names)}
            mid = "IF(ISNUMBER($D$%(s)d),$D$%(s)d,INDEX($C$%(a)d:$C$%(z)d,%(m)s)+N($F$%(s)d)/100)" % f
            width = "IF(ISNUMBER($H$%(s)d),$H$%(s)d/100,INDEX($D$%(a)d:$D$%(z)d,%(m)s)-INDEX($B$%(a)d:$B$%(z)d,%(m)s))" % f
            rows.append(("Elle", '=IFERROR(%s-(%s)/2,"")' % (mid, width), '=IFERROR(%s+(%s)/2,"")' % (mid, width)))
        else:
            # the TRY rates are the USDTRY table's (typed ones too); they can be typed over here as well
            rows = [(name, "=$B$%d" % (usd_first + k), "=$D$%d" % (usd_first + k)) for k, name in enumerate(FR_NAMES)]
            rows.append(("Elle", "=$B$%d" % usd_elle, "=$D$%d" % usd_elle))
        for k, (name, bid, ask) in enumerate(rows):
            r = t + 3 + k
            f = {"r": r, "i": i}
            b.set("A%d" % r, name, bold=True, align="center")
            b.input("B%d" % r, bid, fmt=pct)
            b.set("C%d" % r, '=IFERROR(($B%(r)d+$D%(r)d)/2,"")' % f, fmt=pct)
            b.input("D%d" % r, ask, fmt=pct)
            # the sheet's formula: bid = spot·(1 + TRY bid·g/360)/(1 + major ask·g/360), the ask side the other way round
            b.set("E%d" % r, '=IFERROR($F$%(i)d*(1+$B%(r)d/100/360*$D$%(i)d)/(1+$L$%(i)d/100/360*$D$%(i)d),"")' % f, fmt=NUM4, bold=True)
            b.set("F%d" % r, '=IFERROR(($E%(r)d+$G%(r)d)/2,"")' % f, fmt=NUM4)
            b.set("G%d" % r, '=IFERROR($F$%(i)d*(1+$D%(r)d/100/360*$D$%(i)d)/(1+$H$%(i)d/100/360*$D$%(i)d),"")' % f, fmt=NUM4, bold=True)
            for col, src in (("H", "E"), ("I", "F"), ("J", "G")):
                b.set("%s%d" % (col, r), '=IFERROR(($%s%d-$F$%d)*10000,"")' % (src, r, i), fmt=INT0)
            for col, src in (("K", "H"), ("L", "I"), ("M", "J")):
                b.set("%s%d" % (col, r), '=IFERROR($%s%d/$D$%d,"")' % (src, r, i), fmt="#,##0.0")
        last = t + 3 + len(rows)
        if usd:
            s = usd_set
            b.set("A%d" % s, "Elle ayarı", bold=True)
            b.input("B%d" % s, "RET", align="center")
            b.dropdown("B%d" % s, FR_NAMES)
            b.set("C%d" % s, "Mid %", bold=True, align="right")
            b.input("D%d" % s, None, fmt=pct)
            b.set("E%d" % s, "Spread bp", bold=True, align="right")
            b.input("F%d" % s, None, fmt="0.0")
            b.set("G%d" % s, "Genişlik bp", bold=True, align="right")
            b.input("H%d" % s, None, fmt="0.0")
            b.note("I%d" % s, "boşsa: eğrinin mid'i, spread 0, eğrinin bid / ask aralığı")
            b.note("A%d" % (s + 1), "TRY faizi: eğrinin valördeki basit ACT/360 faizi (%) – Forward sayfasının USDTRY ve EURTRY tablolarının kullandığı "
                                    "hücreler (offshore = ICAP ima eğrisi, VİOP ima eğrisi, TRY OIS ± yarım bid/ask, RET). Bid tarafı USD ask'iyle, ask tarafı USD "
                                    "bid'iyle hesaplanır (sayfanın formülü). 'Elle': eğriyi seçin, mid'i ya da mid'e spread'i (bp) yazın; mid yazılınca "
                                    "spread'e bakılmaz. Değiştirdikleriniz yalnız size görünür, silince piyasaya döner.")
        else:
            b.note("A%d" % last, "TRY faizleri (Elle dahil) USDTRY tablosundakilerdir: orada değiştirilen faiz burada da geçerli, yalnız EURTRY için "
                                 "burada ayrıca değiştirilebilir. Bid tarafı EUR ask'iyle, ask tarafı EUR bid'iyle; gün EURTRY spot valöründen.")
    # ---- the free forward list
    t = FR_LIST
    c, h = t + 1, t + 2
    b.title("A%d" % t, "SERBEST FORWARD  ·  başlangıç → bitiş: spot (başlangıçtaki kur), major ve minor faizi eğrilerden gelir; hepsinin üzerine "
                       "yazılabilir")
    b.set("A%d" % c, "TRY eğrisi", bold=True)
    b.input("B%d" % c, "RET", align="center")
    b.dropdown("B%d" % c, FR_NAMES)
    b.note("C%d" % c, "minor faizi bu eğriden, major faizi USD / EUR OIS'ten gelir · sağda: dört TRY eğrisinin bitiş tarihindeki simple zero faizi")
    b.head("A%d" % h, ["Parite", "Başlangıç", "Bitiş", "Gün", "Spot", "Major %", "Minor %", "Swap", "Forward"] + [n + " %" for n in FR_NAMES])
    b.head("O%d" % h, ["Spot valörü", "Gün başl.", "Gün bitiş", "TRY gün başl.", "TRY gün bitiş", "TRY % başl.", "TRY % bitiş",
                       "Major % başl.", "Major % bitiş", "Parite spotu", "Eğri"])
    for r in range(h + 1, h + 1 + FR_FREE):
        f = {"r": r, "c": c, "usd": FR_USD + 1, "eur": FR_EUR + 1, "names": names}
        b.input("A%d" % r, "USDTRY", align="center")
        b.dropdown("A%d" % r, ("USDTRY", "EURTRY"))
        b.input("B%d" % r, '=IF(ISNUMBER($C%(r)d),$O%(r)d,"")' % f, fmt=DATE)       # the pair's spot date
        b.input("C%d" % r, None, fmt=DATE)
        b.set("D%d" % r, '=IF(AND(ISNUMBER($B%(r)d),ISNUMBER($C%(r)d)),$C%(r)d-$B%(r)d,"")' % f, fmt=INT0)
        # the outright at the start: the pair's spot carried to it with the chosen TRY curve and the major's OIS
        b.input("E%d" % r, ('=IFERROR(IF($D%(r)d="","",IF($P%(r)d=0,$X%(r)d,$X%(r)d*(1+$T%(r)d/100*$P%(r)d/360)/(1+$V%(r)d/100*$P%(r)d/360))),"")'
                            % f), fmt=NUM4)
        # the rates of the period start -> end, from the zero rates of the two dates
        period = '=IFERROR(IF(N($D%(r)d)<=0,"",((1+$%(e)s%(r)d/100*$Q%(r)d/360)/(1+$%(s)s%(r)d/100*$P%(r)d/360)-1)*360/$D%(r)d*100),"")'
        b.input("F%d" % r, period % dict(f, e="W", s="V"), fmt=pct)
        b.input("G%d" % r, period % dict(f, e="U", s="T"), fmt=pct)
        b.set("H%d" % r, '=IFERROR(IF($I%(r)d="","",($I%(r)d-$E%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("I%d" % r, '=IFERROR(IF(N($D%(r)d)<=0,"",$E%(r)d*(1+$G%(r)d/100*$D%(r)d/360)/(1+$F%(r)d/100*$D%(r)d/360)),"")' % f,
              fmt=NUM4, bold=True)
        for k, name in enumerate(FR_NAMES):
            b.set("%s%d" % ("JKLM"[k], r), '=IFERROR(IF(ISNUMBER($S%d),%s,""),"")' % (r, fr_rate(name, "$S%d" % r)), fmt="0.00")
        # helpers: the pair's spot date, days from it (the accrual, the major's curve) and from the USDTRY spot date (the
        # TRY curves' days, as the sheet counts them for EURTRY too)
        b.set("O%d" % r, '=IF($A%d="EURTRY",%s,%s)' % (r, FR_SPOT["EURTRY"], FR_SPOT["USDTRY"]), fmt=DATE)
        b.set("P%d" % r, '=IF(ISNUMBER($B%(r)d),$B%(r)d-$O%(r)d,"")' % f, fmt=INT0)
        b.set("Q%d" % r, '=IF(ISNUMBER($C%(r)d),$C%(r)d-$O%(r)d,"")' % f, fmt=INT0)
        b.set("R%d" % r, '=IF(ISNUMBER($B%d),$B%d-%s,"")' % (r, r, FR_SPOT["USDTRY"]), fmt=INT0)
        b.set("S%d" % r, '=IF(ISNUMBER($C%d),$C%d-%s,"")' % (r, r, FR_SPOT["USDTRY"]), fmt=INT0)
        b.set("T%d" % r, '=IFERROR(IF(ISNUMBER($R%d),CHOOSE($Y%d,%s),""),"")' % (r, r, ",".join(fr_rate(n, "$R%d" % r) for n in FR_NAMES)),
              fmt=pct)
        b.set("U%d" % r, '=IFERROR(INDEX($J%(r)d:$M%(r)d,$Y%(r)d),"")' % f, fmt=pct)
        b.set("V%d" % r, '=IFERROR(IF(ISNUMBER($P%d),%s,""),"")' % (r, fr_major("$A%d" % r, "$P%d" % r)), fmt=pct)
        b.set("W%d" % r, '=IFERROR(IF(ISNUMBER($Q%d),%s,""),"")' % (r, fr_major("$A%d" % r, "$Q%d" % r)), fmt=pct)
        b.set("X%d" % r, '=IF($A%(r)d="EURTRY",$F$%(eur)d,$F$%(usd)d)' % f, fmt=NUM4)      # the tables' spot (typed too)
        b.set("Y%d" % r, '=MATCH($B$%(c)d,%(names)s,0)' % f, fmt="0")
    b.note("A%d" % (h + 1 + FR_FREE), "Bitiş tarihini yazın: başlangıç paritenin spot valörüdür (değiştirilebilir). Spot = başlangıçtaki kur (spot, "
                                      "başlangıç ileri bir tarihse seçilen TRY eğrisi ve major OIS ile o tarihe taşınır). Major % = USD / EUR OIS'in, "
                                      "minor % = seçilen TRY eğrisinin başlangıç → bitiş arası basit ACT/360 faizi (başlangıç spot ise bitişteki zero "
                                      "faiz). Forward = spot·(1 + minor·gün/360)/(1 + major·gün/360), swap = (forward − spot)·10000. Spot, major ve minor "
                                      "faizin üzerine yazılabilir; silince eğriye döner. Eğrinin son düğümünden bir aydan uzak tarihte faizi yoktur.")
    # ---- the TRY curves' rates by tenor
    t = FR_TENOR
    h = t + 1
    b.title("A%d" % t, "TRY FAİZLERİ VADELERE GÖRE  ·  simple zero (ACT/360, %) – offshore, OIS, VİOP ve RET aynı vadede")
    b.head("A%d" % h, ["Vade", "Tarih", "Gün"] + [n + " %" for n in FR_NAMES] + ["Offshore − OIS bp", "VİOP − OIS bp", "RET − OIS bp"])
    spot = FR_SPOT["USDTRY"]
    hol = fx_holidays(model, "USDTRY")
    dates = [("Valör", "=Forward!$D$2")]
    for label, n_days, months in FR_TENORS:
        if months:
            dates.append((label, "=WORKDAY(EDATE(%s,%d)-1,1,%s)" % (spot, months, hol)))
        else:
            dates.append((label, "=WORKDAY(%s+%d-1,1,%s)" % (spot, n_days, hol)))
    dates += [("serbest", None)] * FR_FREE_DATES
    for k, (label, date) in enumerate(dates):
        r = h + 1 + k
        f = {"r": r}
        if date is None:
            b.set("A%d" % r, label, align="center", color=NOTE_COLOR)
            b.input("B%d" % r, None, fmt=DATE)
        else:
            b.set("A%d" % r, label, bold=True, align="center")
            b.set("B%d" % r, date, fmt=DATE, bold=label == "Valör")
        b.set("C%d" % r, '=IF(ISNUMBER($B%d),$B%d-%s,"")' % (r, r, spot), fmt=INT0)
        for j, name in enumerate(FR_NAMES):
            b.set("%s%d" % ("DEFG"[j], r), '=IFERROR(IF(ISNUMBER($C%d),%s,""),"")' % (r, fr_rate(name, "$C%d" % r)), fmt="0.00")
        for col, src in (("H", "D"), ("I", "F"), ("J", "G")):
            b.set("%s%d" % (col, r), '=IFERROR(IF(OR($%s%d="",$E%d=""),"",($%s%d-$E%d)*100),"")' % (src, r, r, src, r, r), fmt="0")
    b.note("A%d" % (h + 1 + len(dates)), "Gün ve vadeler USDTRY spot valöründen (vade TRY ya da USD tatiline düşerse ikisinin de açık olduğu "
                                         "sonraki güne). Faizler eğrilerin mid'i, Forward "
                                         "sayfasının kendi düğümlerinden doğrusal: offshore = ICAP ima eğrisi, OIS = TRY OIS simple zero, VİOP = ima "
                                         "eğri, RET = bid / ask ortası. Fark sütunları bp. Bir eğrinin son düğümünden bir aydan uzak vadede faizi yoktur "
                                         "(VİOP yaklaşık 1 yıl, RET 2 yıl). 'serbest' satırlarına tarih yazılabilir.")


# ---------------------------------------------------------------------------------------------- EURTRY quote matrix
FWD_EUR_ALL = 103                        # the "Tümü" row of the EURTRY matrix (title, curve and header above it)
FWD_EUR_ROWS = (104, 113)                # 1M, 2M, 3M, 6M, 9M, 12M and four free dates; the way back 15 rows below


def _fwd_eur_check(model: Model) -> None:
    """The EURTRY matrix reads the EURTRY spot bid / ask of the Forward sheet's cross table, the EURTRY spot date and
    the EUR OIS curve; it lives on the forward quote sheet (built with the USDTRY matrix)."""
    _need_sheets(model, "Forward", "MASA", "OIS_MAIN", "Motor", FWD_SHEET)
    _need_formula(model, "Forward", "F198", '"EURTRY Curncy","BID"')
    _need_formula(model, "Forward", "G198", '"EURTRY Curncy","ASK"')
    _need_spot_date(model, "K2")
    _need_formula(model, "Forward", "AC27", "$AA$7:$AA$26")
    _need_formula(model, "Forward", "AD7", '"MID"')
    for _, _, src in FWD_DF_SOURCES:
        transplant(_need_formula(model, "MASA", src, "$M$60"), {"$M$60": "$X104"})


def _tto_fwd_eur(model: Model) -> None:
    """EURTRY forward quotes from OIS + spread, the spread given separately for the bid and the ask side - the twin of
    the USDTRY matrix above: the same OIS curves (the desk sheet's discount factors, for the date of the row), the
    EURTRY spot bid / ask, days from the EURTRY spot date and the EUR OIS curve.  The curve and the general spreads
    start from the USDTRY matrix's and can be set apart.  Below it the way back: EURTRY swap points typed by hand ->
    implied TRY rate -> spread over OIS."""
    b = SheetBuilder(model, FWD_SHEET)
    r1, r2 = FWD_EUR_ROWS
    g = FWD_EUR_ALL
    t, c, h = g - 3, g - 2, g - 1
    spot = FR_SPOT["EURTRY"]
    usd_spot = FR_SPOT["USDTRY"]
    b.title("A%d" % t, "FORWARD KOTASYON  ·  EURTRY, OIS + spread  (bid ve ask spread'i ayrı; sarı hücreler girdi)")
    b.row("A%d" % c, ["Eğri", None, None, None, None, "Spot valör", None, "OIS spot", None], bold=True)
    b.input("B%d" % c, "=$B$2", align="center")                       # the USDTRY matrix's curve unless set apart
    b.dropdown("B%d" % c, FWD_CURVES)
    b.set("C%d" % c, ('=IFERROR(IF(LEFT($B$%(c)d,1)="S","= "&INDEX(OIS_MAIN!$P$3:$P$5,MATCH($B$%(c)d,OIS_MAIN!$O$3:$O$5,0)),'
                      'IF($B$%(c)d="Ağırlıklı","= S1–S3 ağırlıklı","")),"")') % {"c": c}, bold=True, color=NOTE_COLOR)
    b.set("G%d" % c, "=" + spot, fmt=DATE)
    b.set("I%d" % c, "=OIS_MAIN!$B$2", fmt=DATE)
    b.note("K%d" % c, "eğri ve 'Tümü' spread'leri USDTRY matrisinden gelir; EURTRY için ayrıca seçilip yazılabilir")
    b.head("A%d" % h, ["Vade", "Valör", "Gün", "Spread bid", "Spread ask", "Spot bid", "Spot ask", "Puan bid", "Puan ask", "Fwd bid",
                       "Fwd ask", "OIS %", "TRY bid %", "TRY ask %", "EUR %", "P/gün bid", "P/gün ask", "RET bid %", "RET ask %",
                       "Bid − RET", "Ask − RET", "Piyasa bid (bp)", "Piyasa ask (bp)"])
    # the general row: the spreads (from the USDTRY matrix's) and the EURTRY spot (Bloomberg bid / ask, or typed)
    b.set("A%d" % g, "Tümü", bold=True, align="center")
    b.input("B%d" % g, "=$B$%d" % FWD_ALL, align="center")             # one's own spreads or the market's: as USDTRY unless set
    b.dropdown("B%d" % g, (FWD_SPREAD_OWN, FWD_SPREAD_MARKET))
    b.set("C%d" % g, "bp →", color=NOTE_COLOR, align="right")
    b.input("D%d" % g, "=$D$%d" % FWD_ALL, fmt="0", align="center")
    b.input("E%d" % g, "=$E$%d" % FWD_ALL, fmt="0", align="center")
    b.input("F%d" % g, "=IF(ISNUMBER(Forward!$F$198),Forward!$F$198,Forward!$G$2)", fmt=NUM4)
    b.input("G%d" % g, "=IF(ISNUMBER(Forward!$G$198),Forward!$G$198,Forward!$G$2)", fmt=NUM4)
    b.set("X%d" % c, "Yardımcı: her eğrinin spot→valör iskonto faktörü ve ACT/360 basit faizi (%), TRY eğrilerinin günü", color=NOTE_COLOR)
    b.head("X%d" % h, ["OIS gün"] + ["DF " + name for _, name, _ in FWD_DF_SOURCES] + list(FWD_CURVES) + ["TRY gün"])
    df_text = {col: formula_of(model, "MASA", src) for col, _, src in FWD_DF_SOURCES}
    rate_col = dict(zip(FWD_CURVES, ("AE", "AF", "AG", "AH", "AI", "AJ", "AK")))
    months = {r1: 1, r1 + 1: 2, r1 + 2: 3, r1 + 3: 6, r1 + 4: 9, r1 + 5: 12}
    eur_x, eur_y, eur_n = FR_MAJOR["EURTRY"]
    ret_x, ret_bid, ret_ask = "Forward!$U$33:$U$47", "Forward!$W$33:$W$47", "Forward!$X$33:$X$47"
    hol = fx_holidays(model, "EURTRY")
    for r in range(r1, r2 + 1):
        f = {"r": r, "g": g, "c": c, "h": h}
        if r in months:
            b.set("A%d" % r, "%dM" % months[r], bold=True, align="center")
            b.input("B%d" % r, "=WORKDAY(EDATE(%s,%d)-1,1,%s)" % (spot, months[r], hol), fmt=DATE)
        else:
            b.set("A%d" % r, "serbest", align="center", color=NOTE_COLOR)
            b.input("B%d" % r, None, fmt=DATE)
        b.set("C%d" % r, '=IF(ISNUMBER($B%d),$B%d-%s,"")' % (r, r, spot), fmt=INT0)     # days from the EURTRY spot date
        b.input("D%d" % r, '=IF($B$%d="%s",$V%d,$D$%d)' % (g, FWD_SPREAD_MARKET, r, g), fmt="0", align="center")
        b.input("E%d" % r, '=IF($B$%d="%s",$W%d,$E$%d)' % (g, FWD_SPREAD_MARKET, r, g), fmt="0", align="center")
        b.set("F%d" % r, '=IF($C%(r)d="","",$F$%(g)d)' % f, fmt=NUM4)
        b.set("G%d" % r, '=IF($C%(r)d="","",$G$%(g)d)' % f, fmt=NUM4)
        b.set("H%d" % r, '=IFERROR(IF($C%(r)d="","",($J%(r)d-$F%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("I%d" % r, '=IFERROR(IF($C%(r)d="","",($K%(r)d-$G%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("J%d" % r, '=IFERROR(IF($C%(r)d="","",$F%(r)d*(1+$M%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("K%d" % r, '=IFERROR(IF($C%(r)d="","",$G%(r)d*(1+$N%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("L%d" % r, '=IF($C%(r)d="","",INDEX($AE%(r)d:$AK%(r)d,MATCH($B$%(c)d,$AE$%(h)d:$AK$%(h)d,0)))' % f, fmt="0.00")
        b.set("M%d" % r, '=IFERROR(IF($C%(r)d="","",$L%(r)d+IF(ISNUMBER($D%(r)d),$D%(r)d,$D$%(g)d)/100),"")' % f, fmt="0.00")
        b.set("N%d" % r, '=IFERROR(IF($C%(r)d="","",$L%(r)d+IF(ISNUMBER($E%(r)d),$E%(r)d,$E$%(g)d)/100),"")' % f, fmt="0.00")
        b.set("O%d" % r, '=IFERROR(IF($C%d="","",%s),"")' % (r, lin("$C%d" % r, eur_x, eur_y, eur_n)), fmt="0.00")
        b.set("P%d" % r, '=IFERROR(IF($C%(r)d="","",$H%(r)d/$C%(r)d),"")' % f, fmt="#,##0.0")
        b.set("Q%d" % r, '=IFERROR(IF($C%(r)d="","",$I%(r)d/$C%(r)d),"")' % f, fmt="#,##0.0")
        # RET at the TRY curves' days (from the USDTRY spot date, as the sheet reads them for EURTRY too)
        b.set("R%d" % r, '=IFERROR(IF($C%d="","",%s*100),"")' % (r, lin("$AL%d" % r, ret_x, ret_bid, 15)), fmt="0.00")
        b.set("S%d" % r, '=IFERROR(IF($C%d="","",%s*100),"")' % (r, lin("$AL%d" % r, ret_x, ret_ask, 15)), fmt="0.00")
        b.set("T%d" % r, '=IFERROR(IF($C%(r)d="","",$H%(r)d-($F%(r)d*(1+$R%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)-$F%(r)d)*10000),"")' % f,
              fmt=INT0)
        b.set("U%d" % r, '=IFERROR(IF($C%(r)d="","",$I%(r)d-($G%(r)d*(1+$S%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)-$G%(r)d)*10000),"")' % f,
              fmt=INT0)
        for col, side in (("V", "I"), ("W", "K")):                     # the market's: offshore implied − OIS, at the TRY days
            b.set("%s%d" % (col, r), '=IFERROR(IF($C%d="","",(%s-$L%d)*100),"")' % (r, fwd_offshore("$AL%d" % r, side), r), fmt="0")
        # helpers: days from the OIS spot date, the discount factor and the ACT/360 simple rate of each curve
        b.set("X%d" % r, '=IF(ISNUMBER($B%(r)d),$B%(r)d-OIS_MAIN!$B$2,"")' % f, fmt=INT0)
        for col, name, _ in FWD_DF_SOURCES:
            b.set("%s%d" % (col, r), "=" + transplant(df_text[col], {"$M$60": "$X%d" % r}), fmt="0.000000")
            b.set("%s%d" % (rate_col[name], r), '=IFERROR((1/$%s%d-1)*360/$X%d*100,NA())' % (col, r, r), fmt="0.0000")
        b.set("AI%d" % r, '=IFERROR((OIS_MAIN!$Q$3*$AF%(r)d+OIS_MAIN!$Q$4*$AG%(r)d+OIS_MAIN!$Q$5*$AH%(r)d)/SUM(OIS_MAIN!$Q$3:$Q$5),NA())' % f,
              fmt="0.0000")
        b.set("AL%d" % r, '=IF(ISNUMBER($B%d),$B%d-%s,"")' % (r, r, usd_spot), fmt=INT0)
    b.note("A%d" % (r2 + 1), "TRY faizi = seçilen OIS eğrisinin spot→valör ACT/360 basit faizi + spread (bp), USDTRY matrisiyle aynı eğriler. "
                             "'Tümü' satırı bütün vadelere, vade satırındaki değer yalnız o vadeye uygulanır; spread'ler ve eğri başlangıçta "
                             "USDTRY matrisinindir, EURTRY için ayrıca yazılabilir. Spot: Bloomberg EURTRY bid / ask (yazılabilir). Piyasa bid / ask = "
                             "offshore (ICAP) ima TRY faizi − OIS; 'Tümü' satırında 'Piyasa spread' seçilince her vade onunla fiyatlanır.")
    b.note("A%d" % (r2 + 2), "Fwd bid = spot bid·(1+TRY bid·g/360)/(1+EUR·g/360), ask tarafı spot ask ve TRY ask ile; g = valör − EURTRY spot "
                             "valörü, EUR faizi EUR OIS eğrisinden. Puan = (fwd − spot)·10000; P/gün = puan/gün. 'Bid/Ask − RET' = aynı valörde "
                             "RET bid/ask faiziyle çıkan puana fark. Ay vadeleri TRY ya da EUR tatiline düşerse ikisinin de açık olduğu sonraki güne.")

    # ---- the way back: EURTRY swap points typed by hand -> implied TRY rate -> spread over the chosen OIS curve
    t = r1 + FWD_BACK - 2
    b.title("A%d" % t, "PUAN → OIS SPREAD  ·  EURTRY  ·  elle verilen swap puanının ima ettiği TRY faizi ve OIS'e göre spread'i")
    b.head("A%d" % (t + 1), ["Vade", "Valör", "Gün", "Elle puan bid", "Elle puan ask", "Fwd bid", "Fwd ask", "İma TRY bid %", "İma TRY ask %",
                             "OIS %", "İma spread bid (bp)", "İma spread ask (bp)", "RET bid %", "RET ask %"])
    for r in range(r1, r2 + 1):
        f = {"r": r + FWD_BACK, "s": r}
        k = r + FWD_BACK
        b.set("A%d" % k, "=$A%d" % r, bold=r in months, align="center", color=None if r in months else NOTE_COLOR)
        b.set("B%d" % k, '=IF($B%(s)d="","",$B%(s)d)' % f, fmt=DATE)
        b.set("C%d" % k, "=$C%d" % r, fmt=INT0)
        b.input("D%d" % k, None, fmt=INT0)
        b.input("E%d" % k, None, fmt=INT0)
        b.set("F%d" % k, '=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($D%(r)d))),"",$F%(s)d+$D%(r)d/10000),"")' % f, fmt=NUM4)
        b.set("G%d" % k, '=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($E%(r)d))),"",$G%(s)d+$E%(r)d/10000),"")' % f, fmt=NUM4)
        b.set("H%d" % k, '=IFERROR(IF($F%(r)d="","",(($F%(r)d/$F%(s)d)*(1+$O%(s)d/100*$C%(r)d/360)-1)*360/$C%(r)d*100),"")' % f, fmt="0.00")
        b.set("I%d" % k, '=IFERROR(IF($G%(r)d="","",(($G%(r)d/$G%(s)d)*(1+$O%(s)d/100*$C%(r)d/360)-1)*360/$C%(r)d*100),"")' % f, fmt="0.00")
        b.set("J%d" % k, '=IFERROR(IF($C%(r)d="","",$L%(s)d),"")' % f, fmt="0.00")
        b.set("K%d" % k, '=IFERROR(IF($H%(r)d="","",($H%(r)d-$J%(r)d)*100),"")' % f, fmt="0", bold=True)
        b.set("L%d" % k, '=IFERROR(IF($I%(r)d="","",($I%(r)d-$J%(r)d)*100),"")' % f, fmt="0", bold=True)
        b.set("M%d" % k, '=IFERROR(IF($C%(r)d="","",$R%(s)d),"")' % f, fmt="0.00")
        b.set("N%d" % k, '=IFERROR(IF($C%(r)d="","",$S%(s)d),"")' % f, fmt="0.00")
    b.note("A%d" % (r2 + FWD_BACK + 1), "Tarihler üstteki EURTRY matrisinden gelir. İma TRY % = ((fwd/spot)·(1+EUR·g/360) − 1)·360/g; spread = "
                                        "İma TRY − OIS (bp). Bulunan spread'i üstteki matrise yazınca aynı puan çıkar.")
    _rate_back(b, (r1, r2), FWD_EUR_RATE, "EURTRY", "EUR", months)


# ---------------------------------------------------------------------------------------------- sources
SRC_SHEET = "EK_KAYNAK"
SRC_LISTS = (("ois", "TRY OIS", 4, "GFOF", "Excel'deki ticker: kök + Curncy (BGN)"),
             ("off", "Offshore · FX swap ima", 5, "ICPL", "Excel'deki ticker: Forward!AO6:AO16 (BGN)"),
             ("xccy", "Offshore · XCCY", 6, "ICPL", "Excel'deki ticker: Forward!AO17:AO26 (BGN)"))
SRC_COLS = "BCDE"                 # up to four pricing sources per curve, tried from left to right
SRC_FIRST = 11                    # the first row of "the source in use" table
OIS_SRC_ROWS = tuple(r for r in range(9, 27) if r not in (15, 17))     # 15M and 21M are interpolated, not quoted
OFF_SRC_ROWS = tuple(range(6, 17))                                      # Forward!AO6:AO16 - FX swap implied
XCCY_SRC_ROWS = tuple(range(17, 27))                                    # Forward!AO17:AO26 - cross currency


def _sources_check(model: Model) -> None:
    """The quotes the source order takes over: the OIS page's GFOF-then-plain chain, the offshore and XCCY
    tables' single BID / ASK calls on the Forward sheet's tickers."""
    _need_sheets(model, "OIS_MAIN", "Forward")
    for r in OIS_SRC_ROWS:
        f = _need_formula(model, "OIS_MAIN", "B%d" % r, 'J%d&" GFOF Curncy","MID"' % r)
        if 'J%d&" Curncy","PX_LAST"' % r not in f:
            raise ValueError("OIS_MAIN!B%d beklenen formül değil" % r)
    for a in ("AU13", "AU14"):
        _need_formula(model, "OIS_MAIN", a, ' GFOF Curncy","MID")/100')
    for r in OFF_SRC_ROWS + (17,):
        for col, fld in (("I", "BID"), ("K", "ASK")):
            if _need_formula(model, "Forward", "%s%d" % (col, r)).replace("$", "") != '_xll.BDP(AO%d,"%s")' % (r, fld):
                raise ValueError("Forward!%s%d beklenen formül değil" % (col, r))
    for r in XCCY_SRC_ROWS:
        for col, fld in (("D", "BID"), ("F", "ASK")):
            at = "%s%d" % (col, r + 108)
            if _need_formula(model, "Forward", at).replace("$", "") != '_xll.BDP(AO%d,"%s")' % (r, fld):
                raise ValueError("Forward!%s beklenen formül değil" % at)


def _tto_sources(model: Model) -> None:
    """Which Bloomberg pricing source the live curves are read from - an ordered list per curve, shared by
    everyone and kept on the settings page: the first source that has a price is used, the workbook's own
    ticker (BGN) always comes last.  The OIS page used to try GFOF and then the ticker without a source; the
    offshore and XCCY tables read the BGN tickers only.  Now:

    * ``EK_KAYNAK!B4:E6`` - the lists (OIS: GFOF, offshore: ICPL, XCCY: ICPL by default);
    * one row per quoted tenor below: every source's price, the first that has one, its ticker - and the
      workbook's own call, which keeps the value Excel saved (offline the page shows the saved file);
    * the cells of the OIS page and of the Forward sheet that read the quotes now read the chosen ticker.

    An offshore source is taken only when it has both a bid and an ask (a row never mixes two sources)."""
    b = SheetBuilder(model, SRC_SHEET)
    b.title("A1", "VERİ KAYNAKLARI  ·  Bloomberg fiyat kaynağı sırası: soldan sağa ilk fiyat veren kaynak kullanılır, "
                  "en sonda her zaman Excel'deki ticker (BGN)")
    b.head("A3", ["Eğri", "1. kaynak", "2. kaynak", "3. kaynak", "4. kaynak", "Son yedek (her zaman)"])
    for _, title, row, first, fallback in SRC_LISTS:
        b.set("A%d" % row, title, bold=True)
        b.input("B%d" % row, first)
        for col in SRC_COLS[1:]:
            b.input("%s%d" % (col, row), None)
        b.set("F%d" % row, fallback, color=NOTE_COLOR)
    b.note("A7", "Kaynak kodu Bloomberg'in fiyat kaynağıdır (GFOF, ICPL, BGN, CMPN, TRPU …): ticker kök + kaynak + Curncy olarak sorulur. "
                 "OIS'te önce MID, yoksa PX_LAST; offshore ve XCCY'de bid ve ask'in ikisi de olan kaynak alınır. Değişiklik herkes için geçerlidir; "
                 "tarihçe de aynı sırayı kullanır (yedek kaynak yalnızca ana kaynağın boş günlerini doldurur).")
    b.title("A9", "ŞU AN KULLANILAN KAYNAK  ·  her vade için")
    b.head("A10", ["Eğri", "Vade", "Excel ticker'ı", "Kullanılan kaynak", "Kullanılan ticker", "Sıra", "Excel bid / değer",
                   "Excel ask", "Değer · bid", "Değer · ask", None, None, None, "1. kaynak", "2. kaynak", "3. kaynak",
                   "4. kaynak", "Kök"])
    k = SRC_FIRST
    rows = []                                                   # (status row, kind, list row, consumer cells)
    for label, root in (("1W", "TYSO1Z"), ("2W", "TYSO2Z")):
        rows.append((k, "ois", 4, ("OIS_MAIN", "AU%d" % (13 if label == "1W" else 14)), label, root))
        k += 1
    for r in OIS_SRC_ROWS:
        rows.append((k, "ois", 4, ("OIS_MAIN", "B%d" % r), "=OIS_MAIN!$A$%d" % r, "=OIS_MAIN!$J$%d" % r))
        k += 1
    for r in OFF_SRC_ROWS:
        rows.append((k, "off", 5, r, "=Forward!$H$%d" % r, None))
        k += 1
    for r in XCCY_SRC_ROWS:
        rows.append((k, "xccy", 6, r, "=Forward!$C$%d" % (r + 108), None))
        k += 1
    titles = {kind: title for kind, title, _, _, _ in SRC_LISTS}
    fwd = SheetBuilder(model, "Forward")
    ois = SheetBuilder(model, "OIS_MAIN")
    for k, kind, lr, where, tenor, root in rows:
        f = {"k": k, "lr": lr}
        b.set("A%d" % k, titles[kind])
        b.set("B%d" % k, tenor, bold=True, align="center")
        if kind == "ois":
            if root.startswith("="):
                b.set("R%d" % k, root)
                b.set("C%d" % k, '=$R%d&" Curncy"' % k)
            else:
                b.set("R%d" % k, root)
                b.set("C%d" % k, "%s Curncy" % root)
            for n, col in enumerate("NOPQ"):
                f["s"] = "$%s$%d" % (SRC_COLS[n], lr)
                t = '$R%(k)d&" "&TRIM(%(s)s)&" Curncy"' % f
                b.set("%s%d" % (col, k), '=IF(LEN(TRIM(%s&""))<2,"",IF(ISNUMBER(_xll.BDP(%s,"MID")),_xll.BDP(%s,"MID"),_xll.BDP(%s,"PX_LAST")))'
                      % (f["s"], t, t, t), fmt="0.0000")
            b.set("G%d" % k, '=_xll.BDP($C%d,"PX_LAST")' % k, fmt="0.0000")
            b.set("I%d" % k, '=IF($F%(k)d>4,$G%(k)d,INDEX($N%(k)d:$Q%(k)d,$F%(k)d))' % f, fmt="0.0000", bold=True)
            sheet, addr = where
            ois.patch(addr, '=LET(t,%s!$E$%d,IF(%s!$F$%d>4,_xll.BDP(t,"PX_LAST"),IF(ISNUMBER(_xll.BDP(t,"MID")),'
                            '_xll.BDP(t,"MID"),_xll.BDP(t,"PX_LAST"))))/100' % (SRC_SHEET, k, SRC_SHEET, k))
        else:
            r = where
            b.set("C%d" % k, "=Forward!$AO$%d" % r)
            b.set("R%d" % k, '=IFERROR(LEFT($C%(k)d,FIND(" ",$C%(k)d)-1),$C%(k)d)' % f)
            for n, col in enumerate("NOPQ"):
                f["s"] = "$%s$%d" % (SRC_COLS[n], lr)
                t = '$R%(k)d&" "&TRIM(%(s)s)&" Curncy"' % f
                b.set("%s%d" % (col, k), '=IF(LEN(TRIM(%s&""))<2,"",IF(AND(ISNUMBER(_xll.BDP(%s,"BID")),ISNUMBER(_xll.BDP(%s,"ASK"))),'
                                         '_xll.BDP(%s,"BID"),""))' % (f["s"], t, t, t), fmt="0.0000")
            # the workbook's own calls, with what Excel saved for them (the offline value of the page)
            bid_at, ask_at = ("I%d" % r, "K%d" % r) if kind == "off" else ("D%d" % (r + 108), "F%d" % (r + 108))
            b.set("G%d" % k, '=_xll.BDP(Forward!$AO$%d,"BID")' % r, fmt="0.0000")
            b.set("H%d" % k, '=_xll.BDP(Forward!$AO$%d,"ASK")' % r, fmt="0.0000")
            b.recorded("G%d" % k, recorded_value(model, "Forward", bid_at))
            b.recorded("H%d" % k, recorded_value(model, "Forward", ask_at))
            b.set("I%d" % k, '=IF($F%(k)d>4,$G%(k)d,_xll.BDP($E%(k)d,"BID"))' % f, fmt="0.0000", bold=True)
            b.set("J%d" % k, '=IF($F%(k)d>4,$H%(k)d,_xll.BDP($E%(k)d,"ASK"))' % f, fmt="0.0000", bold=True)
            consumers = [(bid_at, "BID", "G"), (ask_at, "ASK", "H")]
            if r == 17:                                             # 12M of the offshore table is the 1Y cross currency swap
                consumers += [("I17", "BID", "G"), ("K17", "ASK", "H")]
            for at, fld, col in consumers:
                fwd.patch(at, '=IF(%s!$F$%d>4,%s!$%s$%d,_xll.BDP(%s!$E$%d,"%s"))' % (SRC_SHEET, k, SRC_SHEET, col, k, SRC_SHEET, k, fld))
        b.set("F%d" % k, '=IF(ISNUMBER($N%(k)d),1,IF(ISNUMBER($O%(k)d),2,IF(ISNUMBER($P%(k)d),3,IF(ISNUMBER($Q%(k)d),4,5))))' % f, fmt="0")
        b.set("D%d" % k, '=IF($F%(k)d>4,"Excel (BGN)",TRIM(INDEX($B$%(lr)d:$E$%(lr)d,$F%(k)d)))' % f, bold=True)
        b.set("E%d" % k, '=IF($F%(k)d>4,$C%(k)d,$R%(k)d&" "&$D%(k)d&" Curncy")' % f)
    b.note("A%d" % (k + 2), "Sıra 1–4: listedeki kaynak; 5: Excel'deki ticker. Değer: OIS'te yüzde (sayfa /100 ile kullanır), offshore ve XCCY'de bid / ask. "
                            "Canlıda kaynak yanıt verene kadar (Requesting) bir sonraki kaynak görünür.")


# ---------------------------------------------------------------------------------------------- ASW against FX swaps
FXC_SHEET = "EK_FX"
FXC_FIRST = 6                     # first tenor row
FXC_ZERO_COL = "K"                # the zero-coupon rate of the ASW sheet's curve at each tenor
# the tenors of the ASW sheet's OIS curve (ASW!C64:R64, aswfx.TENORS) and the offshore ticker of each: the FX swap
# implied yields up to 9 months, the cross currency swaps from 1Y (TRYSAQ1: the one year XCCY, the desk's Forward
# sheet's offshore 1Y - the desk, 18.11.2026; TRYI12M had no price) - 18M none: computed off the offshore XCCY curve
# (the desk, 18.11.2026: "TRYI18M gerçek bir kotasyon değil ... 18M hesaplanacak"; aswfx.point_18m,
# Service._asw_fx_18m)
FXC_ROOTS = ("TRYI1M", "TRYI2M", "TRYI3M", "TRYI6M", "TRYI9M", "TRYSAQ1", None, "TRYSAQ2", "TRYSAQ3", "TRYSAQ4",
             "TRYSAQ5", "TRYSAQ6", "TRYSAQ7", "TRYSAQ8", "TRYSAQ9", "TRYSAQ10")
#: EK_FX's row of the computed tenor (18M): its cell the computed XCCY par is given in, in the calculation on the FX swap
#: curve (Service._asw_fx_calc; in the sheet itself #N/A - it is no quote)
FXC_CURVE_ROW = FXC_FIRST + aswfx.TENORS.index(aswfx.CURVE_TENOR)


def _asw_fx_check(model: Model) -> None:
    """The ASW sheet's curve: the OIS quotes of today in C65:R65 (16 tenors) that its discount factors are built from,
    the days to its nodes (AB65:BR65, "D0" … "D120") and their ln discount factors (BS65:DI65, "L0" … "L120") as
    ``aswfx`` reads them."""
    _need_sheets(model, "ASW")
    _need_formula(model, "ASW", "BT65", "$C65")
    for k in range(16):
        col = index_to_col(3 + k)                      # C .. R
        _need_formula(model, "ASW", "%s65" % col, 'BDP(%s$63&" GFOF Curncy","MID")' % col)
    first, last = aswfx.NODES[0], aswfx.NODES[-1]
    _need_captions(model, [("ASW", "%s64" % index_to_col(col), text) for col, text in (
        (aswfx.DAY_COL, "D%d" % first), (aswfx.LN_COL - 1, "D%d" % last), (aswfx.LN_COL, "L%d" % first),
        (aswfx.LN_COL + len(aswfx.NODES) - 1, "L%d" % last))])
    _need_formula(model, "ASW", "%s65" % index_to_col(aswfx.LN_COL + aswfx.node_of(6)), "LN((1-$F65/100*DJ65)")


def _asw_fx(model: Model) -> None:
    """The TRY curve the FX swaps imply, tenor by tenor where the ASW sheet's OIS curve has its quotes - the
    second curve of the ASW table: the dashboard prices every bond off it as well (the sheet's own formulas, each OIS
    quote of C65:R65 swapped for the par quote of the sheet's convention that gives the discount factor the FX rate
    gives by its own: ``aswfx``) and shows ASW against FX swaps next to ASW against OIS.

    Each tenor: the ticker root (typed over freely), the first of the two pricing sources that has a price - MID,
    else the middle of bid and ask -, the OIS quote of the same tenor; how the FX rate is read (by the tenor), the days
    to the tenor on the sheet's curve and the zero-coupon rate of the curve there (compounded once a year, ACT/365:
    ``DF^(−365/d) − 1``, from the sheet's ln discount factor) - OIS's here; the same cell in the dashboard's calculation
    on the FX swap curve is the FX curve's (the page's FX zero rates and chart)."""
    b = SheetBuilder(model, FXC_SHEET)
    b.title("A1", "FX SWAP İMA TRY EĞRİSİ  ·  ASW'nin ikinci eğrisi: offshore TRY faizi (9 aya kadar FX swap ima, 1Y'den "
                  "XCCY, 18A XCCY eğrisinden hesaplanan)")
    b.row("A3", ["Kaynaklar (sırayla)"], bold=True)
    b.input("B3", "ICPL")
    b.input("C3", "BGN")
    b.note("D3", "İlk fiyat veren kaynak kullanılır: önce MID, yoksa bid–ask ortası. Ticker kökü sarı hücrede (yalnız kök: TRYI1M, TRYSAQ2 …).")
    b.head("A5", ["Vade", "Ticker kökü", "Kullanılan ticker", "FX ima (%)", "OIS (%)", "FX − OIS (bp)", "1. kaynak", "2. kaynak",
                  "FX faizi nasıl okunur", "Gün", "OIS sıfır kupon (%)"])
    for k, root in enumerate(FXC_ROOTS):
        r = FXC_FIRST + k
        col = index_to_col(3 + k)
        months = aswfx.TENORS[k]
        node = aswfx.node_of(months)
        f = {"r": r, "col": col, "day": index_to_col(aswfx.DAY_COL + node), "ln": index_to_col(aswfx.LN_COL + node),
             "rule": aswfx.RULES[aswfx.kind_of(months)], "none": aswfx.RULES[aswfx.OIS],
             "label": aswfx.CURVE_LABEL % "Bootstrap / PPK basamak"}
        b.set("A%d" % r, "=ASW!%s$64" % col, bold=True, align="center")
        if root is None:
            # 18M: no ticker - computed off the offshore XCCY curve by the dashboard (Service._asw_fx_18m, on each user's
            # curve setting), its XCCY par given to D in the calculation on the FX swap curve; here (the sheet) no quote
            b.set("B%d" % r, "hesaplanan", align="center")
            b.set("G%d" % r, "=NA()", fmt="0.000")
            b.set("H%d" % r, "=NA()", fmt="0.000")
            b.set("D%d" % r, "=NA()", fmt="0.000", bold=True)
            b.set("C%d" % r, '=IF(ISNUMBER($D%(r)d),"%(label)s","yok")' % f)
        else:
            b.input("B%d" % r, root)

            def price(src: str) -> str:
                t = 'TRIM($B%(r)d)&" "&TRIM(%(s)s)&" Curncy"' % dict(f, s=src)
                return ('IF(LEN(TRIM(%(s)s&""))<2,NA(),IF(ISNUMBER(_xll.BDP(%(t)s,"MID")),_xll.BDP(%(t)s,"MID"),'
                        'IFERROR((_xll.BDP(%(t)s,"BID")+_xll.BDP(%(t)s,"ASK"))/2,NA())))') % {"s": src, "t": t}

            b.set("G%d" % r, "=" + price("$B$3"), fmt="0.000")
            b.set("H%d" % r, "=" + price("$C$3"), fmt="0.000")
            b.set("D%d" % r, '=IF(ISNUMBER($G%(r)d),$G%(r)d,IF(ISNUMBER($H%(r)d),$H%(r)d,NA()))' % f, fmt="0.000", bold=True)
            b.set("C%d" % r, '=IF(ISNUMBER($G%(r)d),TRIM($B%(r)d)&" "&TRIM($B$3)&" Curncy",IF(ISNUMBER($H%(r)d),TRIM($B%(r)d)&" "&TRIM($C$3)&" Curncy","yok"))' % f)
        b.set("E%d" % r, "=ASW!%s$65" % col, fmt="0.000")
        b.set("F%d" % r, '=IFERROR(($D%(r)d-$E%(r)d)*100,"")' % f, fmt="0.0")
        b.set("I%d" % r, '=IF(ISNUMBER($D%(r)d),"%(rule)s","%(none)s")' % f)
        b.set("J%d" % r, "=ASW!%(day)s$65" % f, fmt="0", align="center")
        b.set("%s%d" % (FXC_ZERO_COL, r), "=IFERROR((EXP(-ASW!%(ln)s$65*365/$J%(r)d)-1)*100,NA())" % f, fmt="0.000")
    b.note("A%d" % (FXC_FIRST + len(FXC_ROOTS) + 1),
           "ASW tablosundaki 'ASW FX' sütunu: kâğıt, sayfanın kendi iskonto ve annuity formülleriyle, OIS kotaları yerine bu faizlerden kurulan "
           "eğriyle fiyatlanır. Her FX faizi kendi kuralıyla okunur - tür vadeye göredir: 9 aya kadar (TRYI…) FX swap ima, tek dönem basit "
           "ACT/360 (FX swap'ın kuponu yok); 1 yıldan (TRYSAQ…; 1Y TRYSAQ1, tek kupon) XCCY (TRY sabit / USD değişken), "
           "yıllık ACT/360 par (önceki yılların iskonto "
           "faktörleri eğrinin o vadeye kadar kurulan düğümlerinden). Masanın kendi dosyası da bu ticker'ları böyle okur (Forward!AJ123:AN143, "
           "C123:K134). 18A kota değildir, hesaplanır: offshore eğrinin XCCY 1Y (TRYSAQ1) ile 2Y (TRYSAQ2) arasında 18A'daki iskonto faktörü - "
           "Ayarlar'daki eğri interpolasyonunuzla (Bootstrap: Forward'daki offshore eğri, ln DF günlere göre doğrusal; PPK basamak: offshore "
           "PPK eğrisi); faizi aynı eğride 18A XCCY par (yıllık ACT/360, kuponlar vadeden geriye: 6A, sonra 12A). Çalışma kitabının "
           "kendisinde 18A'nın faizi yoktur (#N/A): panonun EK_FX tablosu her kullanıcınınkini gösterir. "
           "Sayfaya, vadesinde aynı iskonto faktörünü veren kendi kuralındaki par faiz olarak girer (3 aya kadar tek dönem basit "
           "ACT/365, sonra çeyreklik ACT/365 par); sayfanın formülleri değişmez. Fiyatı olmayan vadede OIS kotası olduğu gibi kalır. Gün: "
           "sayfanın eğrisinde spot'tan vadeye gün; OIS sıfır kupon: sayfanın o vadedeki iskonto faktöründen yıllık bileşik ACT/365 faiz "
           "(DF^(−365/gün) − 1).")


# ---------------------------------------------------------------------------------------------- the ASW history offshore
#: what the ASW history's chart (the sheet's second chart) is drawn against - OIS (the workbook's chart), the offshore
#: curve or both (``Service._asw_hist_fx``): each user's choice, typed beside the history's other parameters (J3, L3) -
#: its caption and its cell
ASW_HIST_LABEL, ASW_HIST_PICK = "M3", "N3"
ASW_HIST_CHOICES = ("OIS", "Offshore", "İkisi")
ASW_HIST_NAME = "ASW geçmişi offshore"


def _asw_hist_check(model: Model) -> None:
    """The ASW sheet's history as ``aswfx`` / the service read it: its days and 1M quotes one BDH block (B66, its dates),
    each other tenor's quotes one (D66 … R66), the bonds' ASW in X:Z; the two cells of the choice still empty."""
    _need_sheets(model, "ASW")
    _need_captions(model, (("ASW", "I3", "Geçmiş (gün)"), ("ASW", "K3", "Fiyat alanı"), ("ASW", "B64", "Tarih"),
                           ("ASW", "X64", "ASW 1"), ("ASW", "Z64", "ASW 3")))
    _need_formula(model, "ASW", "B66", '_xll.BDH($C$63&" Curncy"')
    for k in range(1, len(aswfx.TENORS)):
        col = index_to_col(aswfx.QUOTE_COL + k)                     # D .. R
        _need_formula(model, "ASW", "%s66" % col, '_xll.BDH(%s$63&" Curncy"' % col)
    _need_formula(model, "ASW", "X66", "(FF66-FC66)/FG66")
    sh = model.sheet("ASW")
    if None in aswfx.history_anchors(sh):
        raise ValueError("ASW!C66:R66 BDH dizilerinin hücreleri değil")
    for addr in (ASW_HIST_LABEL, ASW_HIST_PICK):
        rc = parse_a1(addr)
        if rc in sh.fml or sh.consts.get(rc) not in (None, ""):
            raise ValueError("ASW!%s boş değil" % addr)


def _asw_hist(model: Model) -> None:
    """The choice of the ASW history's chart: "Geçmiş grafiği" OIS (the workbook's chart, as before) / Offshore / İkisi."""
    b = SheetBuilder(model, "ASW")
    b.set(ASW_HIST_LABEL, "Geçmiş grafiği", like="K3")
    b.set(ASW_HIST_PICK, ASW_HIST_CHOICES[0], like="L3")
    b.dropdown(ASW_HIST_PICK, ASW_HIST_CHOICES)


# ---------------------------------------------------------------------------------------------- more rows
BULK_BOND_LAST = 52               # Bulk Bond: the workbook's four rows (3..6) and these more, to row 52
BULK_SHEET = "EK_BULK"
BULK_FIRST, BULK_ROWS = 5, 100    # the bulk forward table here: 100 value dates (the Forward sheet has 20)
BULK_COLS = "CDEFGHJKNOPQ"        # the formula columns of Forward!B144:Q144 (B: date and L: manual TRY % are typed)
_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9_!$.':])\$[A-Z]{1,3}\$\d+(?::\$[A-Z]{1,3}\$\d+)?(?![A-Za-z0-9_(])")


def _bulk_bond_check(model: Model) -> None:
    _need_sheets(model, "Bulk Bond")
    _need_formula(model, "Bulk Bond", "B6", '$A6&" Corp","SECURITY_DES"')
    _need_formula(model, "Bulk Bond", "K6", '$A6&" @"&$K$1&" Corp",$K$2')
    sh = model.sheet("Bulk Bond")
    if any(rc // COLS > 6 for rc in list(sh.fml) + list(sh.consts)):
        raise ValueError("Bulk Bond: 6. satırın altı boş değil")


def _tto_bulk_bond(model: Model) -> None:
    """Room for more bonds on the Bulk Bond sheet: the row of the workbook's last bond copied down to row 52,
    each formula asking nothing while its ISIN is empty (the workbook's own four rows stay as they are)."""
    b = SheetBuilder(model, "Bulk Bond")
    sh = b.sheet
    for col in "BEFGHIJKLMNOPQRSTUV":
        rc = parse_a1("%s6" % col)
        if rc not in sh.fml:
            continue
        text = formula_of(model, "Bulk Bond", "%s6" % col)
        for r in range(7, BULK_BOND_LAST + 1):
            body = re.sub(r"(?<![A-Za-z0-9_$])(\$?[A-Z]{1,3})6(?!\d)", lambda m: "%s%d" % (m.group(1), r), text)
            b.set("%s%d" % (col, r), '=IF(TRIM($A%d&"")="","",%s)' % (r, body), like="%s6" % col)
    for col in "ACD":
        for r in range(7, BULK_BOND_LAST + 1):
            b.set("%s%d" % (col, r), None, like="%s6" % col)


def _bulk_forward_check(model: Model) -> None:
    _need_sheets(model, "Forward")
    for col in BULK_COLS:
        _need_formula(model, "Forward", "%s144" % col)
    _need_formula(model, "Forward", "N144", "ISNUMBER(L144),L144,G144")
    # the outrights the way back (R..U) inverts: USDTRY on $F$2, USD % (J) and the days (C); EURTRY on $G$2, EUR % (K) and
    # the days from the EURTRY spot date
    _need_formula(model, "Forward", "N144", "$F$2*(1+")
    _need_formula(model, "Forward", "N144", "/(1+J144/100*$C144/360)")
    _need_formula(model, "Forward", "P144", "$G$2*(1+")
    _need_formula(model, "Forward", "P144", "/(1+K144/100*($B144-$K$2)/360)")


def _tto_bulk_forward(model: Model) -> None:
    """The Forward sheet's bulk forward table with 100 rows instead of 20 - the sheet's own formulas, row by row,
    the curves and spots still read from the Forward sheet.  Every value date and manual TRY rate starts empty: the
    dates the file was saved with are nobody's choice today (as ``EMPTY_BY_DEFAULT``); what a user types is theirs.
    The page shows as many rows as are filled, one more on demand."""
    b = SheetBuilder(model, BULK_SHEET)
    b.title("B1", "TOPLU FORWARD FİYATLAMA  ·  100 valöre kadar (B sütununa valör tarihi; TRY faizi: manuel boşsa RET mid)")
    heads = [model.sheet("Forward").consts.get(parse_a1("%s143" % c)) for c in "BCDEFGHIJKLMNOPQ"]
    b.head("B4", [h if isinstance(h, str) else None for h in heads])
    templates = {}
    for col in BULK_COLS:
        text = formula_of(model, "Forward", "%s144" % col)
        templates[col] = _ABSOLUTE.sub(lambda m: "Forward!" + m.group(0), text)       # the curves stay on the Forward sheet
    # the way back (the desk, 23.11.2026: "Toplu fiyatlama kısmında da forward rate'lerden faizi de toplu olarak
    # bulabilmeliyim"): an outright typed or pasted -> the TRY rate it implies, N's / P's own formula solved for the TRY
    # rate - the same spot, USD / EUR % and days
    b.head("R4", ["USDTRY fwd (elle)", "İma TRY %", "EURTRY fwd (elle)", "İma TRY %"])
    eur_days = "($B%(r)d-Forward!$K$2)"
    for k in range(BULK_ROWS):
        r = BULK_FIRST + k
        f = {"r": r}
        b.input("B%d" % r, None, fmt=DATE)
        b.input("L%d" % r, None, fmt="0.0000")
        for col in BULK_COLS:
            body = re.sub(r"(?<![A-Za-z0-9_$!])(\$?[A-Z]{1,3})144(?!\d)", lambda m: "%s%d" % (m.group(1), r), templates[col])
            b.set("%s%d" % (col, r), "=" + body, like=None, fmt=_BULK_FMT.get(col, NUM4))
        b.input("R%d" % r, None, fmt=NUM4)
        b.set("S%d" % r, ('=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($R%(r)d))),"",(($R%(r)d/Forward!$F$2)*(1+$J%(r)d/100*$C%(r)d/360)-1)'
                          '*360/$C%(r)d*100),"")') % f, fmt="0.0000", bold=True)
        b.input("T%d" % r, None, fmt=NUM4)
        b.set("U%d" % r, ('=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($T%(r)d))),"",(($T%(r)d/Forward!$G$2)*(1+$K%(r)d/100*' + eur_days
                          + '/360)-1)*360/' + eur_days + '*100),"")') % f, fmt="0.0000", bold=True)
    b.note("B%d" % (BULK_FIRST + BULK_ROWS + 1),
           "Forward sayfasındaki toplu fiyatlama tablosunun aynı formülleri, 100 satır: eğriler, spot ve faizler Forward sayfasından. "
           "Valör ve manuel TRY faizi boş başlar; yazdıklarınız sizin kalır (Excel'den bir sütun da yapıştırabilirsiniz). "
           "Elle forward (USDTRY / EURTRY) yazın ya da yapıştırın: yanındaki İma TRY %, USDTRY / EURTRY fwd'nin tersi - aynı spot, USD / EUR "
           "faizi ve gün.")


_BULK_FMT = {"C": INT0, "D": "0.000", "E": "0.000", "F": "0.000", "G": "0.000", "H": "0.000", "J": "0.000", "K": "0.000",
             "N": NUM4, "O": INT0, "P": NUM4, "Q": INT0}


# ---------------------------------------------------------------------------------------------- Forward: points -> rate
FS_BACK_USD, FS_BACK_EUR = 181, 182    # FORWARD STARTING SWAP's way back: an FS points value typed -> the TRY fwd-fwd %
FS_BACK_BP = (("P", "E175", "bp − OIS mid"), ("Q", "E174", "bp − offshore mid"), ("R", "E177", "bp − RET mid"))
CROSS_ROWS = (200, 214)                # ÇAPRAZ FORWARD's value dates; its way back in R (typed), S (TRY %), T (bp − RET mid)
#: the cells the ways back take on the Forward sheet: empty in the workbook (``_fwd_back_check``), no input ever stood there
FWD_BACK_CELLS = (["%s%d" % (c, r) for r in (FS_BACK_USD, FS_BACK_EUR) for c in "BCDEFGHIJKLMNOPQR"]
                  + ["%s173" % c for c, _, _ in FS_BACK_BP]
                  + ["%s%d" % (c, r) for r in range(CROSS_ROWS[0] - 1, CROSS_ROWS[1] + 1) for c in "RST"])
_CCY = 'IF($C$197="","USD",UPPER(TRIM($C$197)))'           # ÇAPRAZ FORWARD's currency, as its own formulas read it


def _fwd_back_check(model: Model) -> None:
    """FORWARD STARTING SWAP's "Manuel" row and ÇAPRAZ FORWARD's manual forward (Q), whose formulas the ways back solve
    for the TRY rate; the cells they take are empty in the workbook."""
    _need_sheets(model, "Forward")
    for addr, text in (("C179", "C177"), ("G179", "G177"), ("L179", "L177"), ("F179", "IF(ISNUMBER($C$170),$C$170,F177)"),
                       ("K179", "IF(ISNUMBER($C$171),$C$171,K177)"), ("H179", "G179*(1+E179/100*$H$167/360)/(1+F179/100*$H$167/360)"),
                       ("I179", "(H179-G179)*10000"), ("O179", "(N179-L179)*10000"),
                       ("N179", "L179*(1+E179/100*MAX(0,$G$168-$F$168)/360)/(1+K179/100*MAX(0,$G$168-$F$168)/360)"),
                       ("D179", "((1+C179/100*$F$167/360)*(1+$C$169/100*$H$167/360)-1)*360/$G$167*100"),
                       ("E174", "360/$H$167*100"), ("E175", "360/$H$167*100"), ("E177", "360/$H$167*100"), ("J179", "I179/$H$167")):
        _need_formula(model, "Forward", addr, text)
    for r in CROSS_ROWS:
        for text in ("$F$2*(1+$F%d/100*$C%d/360)/(1+$G%d/100*$C%d/360)" % (r, r, r, r),
                     "$G$2*(1+$F%d/100*($B%d-$K$2)/360)/(1+$H%d/100*($B%d-$K$2)/360)" % (r, r, r, r), ")/AVERAGE(K%d,L%d)" % (r, r)):
            _need_formula(model, "Forward", "Q%d" % r, text)
    sh = model.sheet("Forward")
    for addr in FWD_BACK_CELLS:
        if parse_a1(addr) in sh.fml or sh.consts.get(parse_a1(addr)) not in (None, ""):
            raise ValueError("Forward!%s boş değil" % addr)


def _tto_fwd_back(model: Model) -> None:
    """Points and outrights the other way round on the Forward sheet (the desk, 23.11.2026, proposal #2 approved: a points
    value a broker or a client gives -> the TRY rate it implies).

    * FORWARD STARTING SWAP: an FS swap points value typed -> the TRY fwd-fwd %: the "Manuel" row's own formula solved for
      the TRY rate - the same near / far, the near outright from RET mid, the same USD (USDTRY, row 181) or EUR (EURTRY,
      row 182) fwd-fwd % (typed in C170 / C171, else the curve's); beside it its bp over OIS mid, offshore mid and RET
      mid (E175, E174, E177).
    * ÇAPRAZ FORWARD: a XXXTRY forward typed -> the TRY rate it implies, the foreign leg held: the manual forward's (Q)
      formula solved for the TRY rate - USD / EUR: their OIS % and days; another currency: Bloomberg's USDXXX forward
      (the mid of K / L), the USDTRY leg then on the USD %."""
    b = SheetBuilder(model, "Forward")
    for col, _, head in FS_BACK_BP:
        b.set("%s173" % col, head, like="O173")
    for r, label, pts, leg in ((FS_BACK_USD, "Elle puan → faiz (USDTRY)", "I", "usd"), (FS_BACK_EUR, "Elle puan → faiz (EURTRY)", "O", "eur")):
        f = {"r": r, "p": pts}
        ok = 'AND($F$169="OK",ISNUMBER($%(p)s$%(r)d))' % f
        b.set("B%d" % r, label, like="B179", bold=True)
        b.input("%s%d" % (pts, r), None, fmt="#,##0.0")
        b.set("C%d" % r, '=IF(%s,C177,"")' % ok, like="C179")
        if leg == "usd":
            # far outright = near outright + points; TRY fwd-fwd % = ((far / near)·(1 + USD·d/360) − 1)·360/d (d: the period)
            b.set("G%d" % r, '=IF(%s,G177,"")' % ok, like="G179")
            b.set("H%d" % r, '=IF(%s,G%d+I%d/10000,"")' % (ok, r, r), like="H179")
            b.set("F%d" % r, '=IF(%s,IF(ISNUMBER($C$170),$C$170,F177),"")' % ok, like="F179")
            b.set("E%d" % r, '=IFERROR(IF(%s,((H%d/G%d)*(1+F%d/100*$H$167/360)-1)*360/$H$167*100,""),"")' % (ok, r, r, r), like="E179",
                  bold=True)
            b.set("J%d" % r, '=IF(%s,I%d/$H$167,"")' % (ok, r), like="J179")
        else:
            eur = "MAX(0,$G$168-$F$168)"                    # the period on the EURTRY spot dates, as N179 counts it
            b.set("L%d" % r, '=IF(%s,L177,"")' % ok, like="L179")
            b.set("N%d" % r, '=IF(%s,L%d+O%d/10000,"")' % (ok, r, r), like="N179")
            b.set("K%d" % r, '=IF(%s,IF(ISNUMBER($C$171),$C$171,K177),"")' % ok, like="K179")
            b.set("E%d" % r, '=IFERROR(IF(%s,((N%d/L%d)*(1+K%d/100*%s/360)-1)*360/%s*100,""),"")' % (ok, r, r, r, eur, eur), like="E179",
                  bold=True)
        b.set("D%d" % r, '=IFERROR(IF(%s,((1+C%d/100*$F$167/360)*(1+E%d/100*$H$167/360)-1)*360/$G$167*100,""),"")' % (ok, r, r), like="D179")
        for col, ref, _ in FS_BACK_BP:
            b.set("%s%d" % (col, r), '=IFERROR(IF(AND(ISNUMBER(E%d),ISNUMBER(%s)),(E%d-%s)*100,""),"")' % (r, ref, r, ref), fmt="0.0")
    # ÇAPRAZ FORWARD: a XXXTRY forward typed -> the TRY rate it implies (the foreign leg held)
    r1, r2 = CROSS_ROWS
    b.set("R%d" % (r1 - 1), '=%s&"TRY fwd (elle)"' % _CCY, like="Q%d" % (r1 - 1))
    b.set("S%d" % (r1 - 1), "İma TRY %", like="Q%d" % (r1 - 1))
    b.set("T%d" % (r1 - 1), "− RET mid (bp)", like="Q%d" % (r1 - 1))
    for r in range(r1, r2 + 1):
        f = {"r": r, "c": _CCY}
        usd = "((%(x)s/$F$2)*(1+$G%(r)d/100*$C%(r)d/360)-1)*360/$C%(r)d*100"
        b.input("R%d" % r, None, fmt=NUM4)
        b.set("S%d" % r, ('=IFERROR(IF(OR($C%(r)d="",NOT(ISNUMBER($R%(r)d))),"",IF(%(c)s="USD",' + usd % {"x": "$R%(r)d", "r": r}
                          + ',IF(%(c)s="EUR",(($R%(r)d/$G$2)*(1+$H%(r)d/100*($B%(r)d-$K$2)/360)-1)*360/($B%(r)d-$K$2)*100,'
                          + usd % {"x": "$R%(r)d*AVERAGE($K%(r)d,$L%(r)d)", "r": r} + '))),"")') % f, fmt="0.0000", bold=True)
        b.set("T%d" % r, '=IFERROR(IF($S%(r)d="","",($S%(r)d-AVERAGE($D%(r)d,$E%(r)d))*100),"")' % f, fmt="0.0")


# ---------------------------------------------------------------------------------------------- OIS · PPK: rate -> PPK step
#: The way back of OIS_MAIN's meeting windows (the desk, 24.11.2026, item 2 of "1-2-3-4-5-6-7-8-11-11-13"): ``EK_PPK``.
#: 'MPC OIS' (OIS_MAIN!A82:M99) gives each window between two meetings' effective days its market rate - D, "Piyasa
#: (bootstrap)": (DF start / DF end − 1)·365 / days off the table's ln DFs (BK / BL), simple ACT/365 - and 'MPC SPREAD'
#: (A101:K117) each pair of consecutive windows' spread, (later − earlier)·10000 bp.
#:
#: * A meeting swap's rate typed for a window (G) -> the PPK step it prices at the window's meeting: the rate's overnight
#:   equivalent (ACT/365, compounded every day) − that of the market's rate for the period before the meeting - the
#:   table's own D of the window before it; for the first window the bootstrap's stub from the OIS spot (its ln DF at the
#:   window's start, BK84, against 0 at the spot).  Beside it the market's own step (the window's D the same way).
#: * An MPC spread typed for a pair (S) -> the later window's rate, the earlier window's market rate + the spread, and the
#:   step that rate prices at the later window's meeting, on the same base (the earlier window's market rate).
#:
#: This is Broker Chat's implied step of a meeting swap (``Service._mpc_implied`` / ``_overnight``) cell for cell - the same
#: period before, its rate off the same ln DFs, the same conversion: a chat line and the page give the same bp.  The market
#: is the table's: Bootstrap (Murex's MTM); a user on PPK basamak sees theirs, as the table and the chat do.  Row
#: ``PPK_FIRST + k`` is window k (OIS_MAIN row 84 + k: from meeting slot k's effective day) and pair k (row 103 + k:
#: windows k and k + 1); what is typed there goes with meeting slot k when the calendar changes or a meeting passes
#: (``meetings.TCMB``'s bands on this sheet).
PPK_SHEET = "EK_PPK"
PPK_FIRST = 3
PPK_WINDOWS = (84, 99)             # OIS_MAIN's 'MPC OIS' rows (16 windows) ...
PPK_PAIRS = (103, 117)             # ... and its 'MPC SPREAD' rows (15 pairs)
PPK_RATE, PPK_SPREAD = "G", "S"    # what is typed: a window's rate (%), a pair's spread (bp)
#: the columns of a row that are formulas (meetings.TCMB: an "Elle değer" typed over one goes with the meeting too)
PPK_COMPUTED = tuple("ABCDEFHIJKLM") + tuple("PQRTUVW")
PCT3 = "0.000%"


def _ppk_back_check(model: Model) -> None:
    """'MPC OIS' and 'MPC SPREAD' as the way back reads them: each window's dates (meeting slot k's effective day to slot
    k + 1's) and market rate off the ln DFs, the first window's start ln DF, each pair's spread of two windows."""
    _need_sheets(model, "OIS_MAIN", "Motor")
    if PPK_SHEET in model.sheet_index:
        raise ValueError("%s sayfası zaten var" % PPK_SHEET)
    _need_captions(model, (("OIS_MAIN", "A82", "MPC OIS"), ("OIS_MAIN", "B83", "Başlangıç"), ("OIS_MAIN", "C83", "Bitiş"),
                           ("OIS_MAIN", "D83", "Piyasa (bootstrap)"), ("OIS_MAIN", "A101", "MPC SPREAD – MPCk vs MPCk+1"),
                           ("OIS_MAIN", "B102", "Piyasa (bp)")))
    for k, r in enumerate(range(PPK_WINDOWS[0], PPK_WINDOWS[1] + 1)):
        for col, slot in (("B", 5 + k), ("C", 6 + k)):              # meeting slot k's effective day, and slot k + 1's
            want = "$B$2+Motor!$C$%d" % slot
            if _need_formula(model, "OIS_MAIN", "%s%d" % (col, r)) != want:
                raise ValueError("OIS_MAIN!%s%d beklenen formül değil (%s değil)" % (col, r, want))
        _need_formula(model, "OIS_MAIN", "D%d" % r, "(EXP(BK%d-BL%d)-1)*365/(C%d-B%d)" % (r, r, r, r))
    _need_formula(model, "OIS_MAIN", "BK%d" % PPK_WINDOWS[0], "B%d-SPOTDATE" % PPK_WINDOWS[0])
    for k, r in enumerate(range(PPK_PAIRS[0], PPK_PAIRS[1] + 1)):
        w = PPK_WINDOWS[0] + k
        _need_formula(model, "OIS_MAIN", "B%d" % r, "ROUND((D%d-D%d)*10000,2)" % (w + 1, w))


def _tto_ppk_back(model: Model) -> None:
    """``EK_PPK``: the windows of 'MPC OIS' with a rate typed -> its PPK step (A:M), the pairs of 'MPC SPREAD' with a spread
    typed -> the later window's rate and its step (P:W)."""
    b = SheetBuilder(model, PPK_SHEET)
    w0, p0 = PPK_WINDOWS[0], PPK_PAIRS[0]
    b.title("A1", "MPC OIS → PPK ADIMI")
    b.head("A2", ["Dönem", "Toplantı", "Başlangıç", "Bitiş", "Gün", "Piyasa (bootstrap)", "MPC OIS (elle)", "Önceki dönem",
                  "Önceki gün", "Önceki O/N", "O/N eşdeğeri", "İma PPK adımı (bp)", "Piyasanın adımı (bp)"])
    for k in range(PPK_WINDOWS[1] - w0 + 1):
        r = PPK_FIRST + k
        f = {"r": r, "w": w0 + k, "p": w0 + k - 1, "m": 10 + k, "x": PPK_RATE}       # m: meeting slot k's row of OIS_MAIN
        b.set("A%d" % r, "=OIS_MAIN!$A%(w)d" % f)
        b.set("B%d" % r, '=IF(ISNUMBER(OIS_MAIN!$P%(m)d),OIS_MAIN!$P%(m)d,"")' % f, fmt=DATE)
        b.set("C%d" % r, "=OIS_MAIN!$B%(w)d" % f, fmt=DATE)
        b.set("D%d" % r, "=OIS_MAIN!$C%(w)d" % f, fmt=DATE)
        b.set("E%d" % r, '=IFERROR($D%(r)d-$C%(r)d,"")' % f, fmt=INT0)
        b.set("F%d" % r, "=OIS_MAIN!$D%(w)d" % f, fmt=PCT3)
        b.input("%(x)s%(r)d" % f, None, fmt=PCT3)
        if k == 0:
            # the period before the first meeting: the bootstrap's stub from the OIS spot (ln DF 0 there)
            b.set("H%d" % r, '=IFERROR((EXP(-OIS_MAIN!$BK$%(w)d)-1)*365/(OIS_MAIN!$B$%(w)d-OIS_MAIN!$B$2),"")' % f, fmt=PCT3)
            b.set("I%d" % r, '=IFERROR(OIS_MAIN!$B$%(w)d-OIS_MAIN!$B$2,"")' % f, fmt=INT0)
        else:
            # ... and before any other: the window before it, at its market rate
            b.set("H%d" % r, "=OIS_MAIN!$D%(p)d" % f, fmt=PCT3)
            b.set("I%d" % r, '=IFERROR(OIS_MAIN!$C%(p)d-OIS_MAIN!$B%(p)d,"")' % f, fmt=INT0)
        b.set("J%d" % r, "=" + overnight("$H%d" % r, "$I%d" % r, 365), fmt=PCT3)
        b.set("K%d" % r, "=" + overnight("$%(x)s%(r)d" % f, "$E%d" % r, 365), fmt=PCT3)
        b.set("L%d" % r, '=IFERROR(($K%(r)d-$J%(r)d)*10000,"")' % f, fmt="0.0", bold=True)
        b.set("M%d" % r, '=IFERROR((%s-$J%d)*10000,"")' % (overnight("$F%d" % r, "$E%d" % r, 365), r), fmt="0.0")
    b.title("P1", "MPC SPREAD → PPK ADIMI")
    b.head("P2", ["Spread", "Adımın toplantısı", "Piyasa (bp)", "Elle spread (bp)", "MPCk+1 dönemi (ima)", "O/N eşdeğeri",
                  "İma PPK adımı (bp)", "Piyasanın adımı (bp)"])
    for k in range(PPK_PAIRS[1] - p0 + 1):
        # pair k: windows k (this row of A:M) and k + 1 (the next row) - the step at the later window's meeting
        r = PPK_FIRST + k
        f = {"r": r, "n": r + 1, "s": p0 + k, "x": PPK_SPREAD}
        b.set("P%d" % r, "=OIS_MAIN!$A%(s)d" % f)
        b.set("Q%d" % r, "=$B%(n)d" % f, fmt=DATE)
        b.set("R%d" % r, "=OIS_MAIN!$B%(s)d" % f, fmt="0.0")
        b.input("%(x)s%(r)d" % f, None, fmt="0.0")
        b.set("T%d" % r, '=IFERROR(IF(ISNUMBER($%(x)s%(r)d),$F%(r)d+$%(x)s%(r)d/10000,""),"")' % f, fmt=PCT3)
        b.set("U%d" % r, "=" + overnight("$T%d" % r, "$E%d" % (r + 1), 365), fmt=PCT3)
        b.set("V%d" % r, '=IFERROR(($U%(r)d-$J%(n)d)*10000,"")' % f, fmt="0.0", bold=True)
        b.set("W%d" % r, "=$M%(n)d" % f, fmt="0.0")


# ---------------------------------------------------------------------------------------------- OIS · PPK: an FRA's other leg
#: TÜM FORWARD / FRA (OIS_MAIN!A334:T438) gives the FRA two spot swaps make (S, "Gerçekleşen FRA"): (R·P − Q·O) / (P − O) -
#: Q / R the start / end leg's fill typed (blank: the market's par, I / J), O / P the annuities to the start / end month
#: (Motor's quarterly calendar; M = 0: no start leg, S = R).  The way back (the desk, 24.11.2026, item 3): a target FRA
#: typed per row (U) -> the end leg's rate that makes it with the start leg as S reads it (V: (F·(P − O) + Q·O) / P; M = 0:
#: the target itself) and the start leg's rate that makes it with the end leg as S reads it (W: (R·P − F·(P − O)) / O;
#: none when M = 0).  Either typed back into its fill makes S the target.  A row is the user's own FRA (M / N), as Q / R.
FRA_LEG_NAME = "FRA ikinci bacak"
FRA_LEG_ROWS = (336, 438)
FRA_LEG_TARGET, FRA_LEG_END, FRA_LEG_START = "U", "V", "W"
#: S's formula, the one the way back inverts (row ``r``)
FRA_LEG_S = ('IF(M%(r)d=0,IF(R%(r)d="",J%(r)d,R%(r)d),(IF(R%(r)d="",J%(r)d,R%(r)d)*P%(r)d-IF(Q%(r)d="",I%(r)d,Q%(r)d)*O%(r)d)'
             '/(P%(r)d-O%(r)d))')


def _fra_leg_check(model: Model) -> None:
    """S of every row of TÜM FORWARD / FRA is the formula inverted; the columns the way back takes are empty."""
    _need_sheets(model, "OIS_MAIN")
    h = FRA_LEG_ROWS[0] - 1
    _need_captions(model, (("OIS_MAIN", "A334", "TÜM FORWARD / FRA"), ("OIS_MAIN", "I%d" % h, "Başlangıç bacağı oranı"),
                           ("OIS_MAIN", "J%d" % h, "Bitiş bacağı oranı"), ("OIS_MAIN", "M%d" % h, "Başlangıç (ay)"),
                           ("OIS_MAIN", "O%d" % h, "A başlangıç"), ("OIS_MAIN", "P%d" % h, "A bitiş"),
                           ("OIS_MAIN", "Q%d" % h, "Başl. bacağı dolum"), ("OIS_MAIN", "R%d" % h, "Bitiş bacağı dolum"),
                           ("OIS_MAIN", "S%d" % h, "Gerçekleşen FRA")))
    for r in range(FRA_LEG_ROWS[0], FRA_LEG_ROWS[1] + 1):
        _need_formula(model, "OIS_MAIN", "S%d" % r, FRA_LEG_S % {"r": r})
    sh = model.sheet("OIS_MAIN")
    for r in range(h, FRA_LEG_ROWS[1] + 1):
        for col in (FRA_LEG_TARGET, FRA_LEG_END, FRA_LEG_START):
            rc = parse_a1("%s%d" % (col, r))
            if rc in sh.fml or sh.consts.get(rc) not in (None, ""):
                raise ValueError("OIS_MAIN!%s%d boş değil" % (col, r))


def _tto_fra_leg(model: Model) -> None:
    """TÜM FORWARD / FRA's U:W: a target FRA typed -> the end leg / the start leg it needs."""
    b = SheetBuilder(model, "OIS_MAIN")
    h = FRA_LEG_ROWS[0] - 1
    for col, text in ((FRA_LEG_TARGET, "Hedef FRA"), (FRA_LEG_END, "Gereken bitiş bacağı"), (FRA_LEG_START, "Gereken başl. bacağı")):
        b.set("%s%d" % (col, h), text, like="S%d" % h)
    for r in range(FRA_LEG_ROWS[0], FRA_LEG_ROWS[1] + 1):
        f = {"r": r, "u": FRA_LEG_TARGET}
        f["q"] = 'IF($Q%(r)d="",$I%(r)d,$Q%(r)d)' % f            # the start leg as S reads it ...
        f["e"] = 'IF($R%(r)d="",$J%(r)d,$R%(r)d)' % f            # ... and the end leg
        b.set("%(u)s%(r)d" % f, None, like="Q%d" % r)             # typed, with the fills' look
        b.set("%s%d" % (FRA_LEG_END, r), ('=IFERROR(IF(ISNUMBER($%(u)s%(r)d),IF($M%(r)d=0,$%(u)s%(r)d,'
                                          '($%(u)s%(r)d*($P%(r)d-$O%(r)d)+%(q)s*$O%(r)d)/$P%(r)d),""),"")') % f, fmt=PCT3, bold=True)
        b.set("%s%d" % (FRA_LEG_START, r), ('=IFERROR(IF(AND(ISNUMBER($%(u)s%(r)d),$M%(r)d<>0),'
                                            '(%(e)s*$P%(r)d-$%(u)s%(r)d*($P%(r)d-$O%(r)d))/$O%(r)d,""),"")') % f, fmt=PCT3, bold=True)


# ---------------------------------------------------------------------------------------------- USD · FOMC: window OIS -> step
#: The FOMC table of the USD sheet (SOFR_FOMC!A71:Z83, a meeting a row) gives each meeting's implied O/N, K: (exp((ln DF
#: start − ln DF end) / days) − 1)·36000 between its effective day and the next meeting's - ACT/360, compounded daily -
#: and the step at it, N: (K − L)·100 / B9, L the O/N before it (the previous active meeting's K; the first's: the stub
#: O/N, B7 + B16/100).  İŞLEM 1 prices the same window as an OIS: E88, (exp(ln DF start − ln DF end) − 1)·36000 / days.
#: The way back (the desk, 24.11.2026, item 13): a window's OIS rate typed per meeting (AB, %) -> its O/N - K's formula on
#: the rate's own DF ratio, ((1 + r·days/36000)^(1/days) − 1)·36000 (AC) - and the step it prices against the same L, in
#: bp (AD) and as N does, in steps of B9 (AE); beside them the market's window rate (AA: İŞLEM 1's E).  The market's own
#: window rate typed gives K and N back.  A rate typed goes with its meeting (``meetings.FED``).
FOMC_BACK_NAME = "FOMC pencere OIS'ten adım"
FOMC_BACK_ROWS = (74, 83)
FOMC_BACK_RATE = "AB"
FOMC_BACK_COLS = ("AA", "AB", "AC", "AD", "AE")
FOMC_TRADE_OFFSET = 14             # İŞLEM 1's row of a meeting: its FOMC row + 14 (E88 for row 74)


def _fomc_back_check(model: Model) -> None:
    """K, N and L of the FOMC table and İŞLEM 1's window rate, as the way back inverts them; its columns are empty."""
    _need_sheets(model, "SOFR_FOMC")
    _need_captions(model, (("SOFR_FOMC", "H73", "Gün"), ("SOFR_FOMC", "K73", "İma O/N %"), ("SOFR_FOMC", "L73", "Önceki ima %"),
                           ("SOFR_FOMC", "N73", "Toplantı adımı %"), ("SOFR_FOMC", "E87", "Piyasa fwd %")))
    r0, r1 = FOMC_BACK_ROWS
    _need_formula(model, "SOFR_FOMC", "L%d" % r0, "($B$7+$B$16/100)")
    for r in range(r0, r1 + 1):
        _need_formula(model, "SOFR_FOMC", "K%d" % r, "(EXP((I%d-J%d)/H%d)-1)*360*100" % (r, r, r))
        _need_formula(model, "SOFR_FOMC", "N%d" % r, "(K%d-L%d)*100/$B$9" % (r, r))
        _need_formula(model, "SOFR_FOMC", "E%d" % (r + FOMC_TRADE_OFFSET), "(EXP($I%d-$J%d)-1)*36000/$H%d" % (r, r, r))
        if r > r0:
            _need_formula(model, "SOFR_FOMC", "L%d" % r, "LOOKUP(2,1/($D$%d:D%d=1),$K$%d:K%d)" % (r0, r - 1, r0, r - 1))
    sh = model.sheet("SOFR_FOMC")
    for r in range(r0 - 2, r1 + 1):
        for col in FOMC_BACK_COLS:
            rc = parse_a1("%s%d" % (col, r))
            if rc in sh.fml or sh.consts.get(rc) not in (None, ""):
                raise ValueError("SOFR_FOMC!%s%d boş değil" % (col, r))


def _usd_fomc_back(model: Model) -> None:
    """The FOMC table's AA:AE: a window's OIS rate typed -> its O/N and the step it prices."""
    b = SheetBuilder(model, "SOFR_FOMC")
    r0, r1 = FOMC_BACK_ROWS
    b.set("AA%d" % (r0 - 2), "PENCERE OIS → FOMC ADIMI", bold=True)
    for col, text in zip(FOMC_BACK_COLS, ("Piyasa pencere OIS %", "Pencere OIS (elle) %", "Elle O/N %", "Elle adım (bp)",
                                          "Elle toplantı adımı %")):
        b.set("%s%d" % (col, r0 - 1), text, like="K%d" % (r0 - 1))
    for r in range(r0, r1 + 1):
        f = {"r": r, "e": r + FOMC_TRADE_OFFSET, "x": FOMC_BACK_RATE}
        b.set("AA%d" % r, "=$E%(e)d" % f, like="K%d" % r)
        b.set("%(x)s%(r)d" % f, None, like="P%d" % r)                     # typed, with the sheet's input look
        b.set("AC%d" % r, ('=IFERROR(IF(AND($D%(r)d=1,ISNUMBER($%(x)s%(r)d),N($H%(r)d)>0),'
                           '((1+$%(x)s%(r)d*$H%(r)d/36000)^(1/$H%(r)d)-1)*36000,""),"")') % f, like="K%d" % r)
        b.set("AD%d" % r, '=IFERROR(IF(ISNUMBER($AC%(r)d),($AC%(r)d-$L%(r)d)*100,""),"")' % f, fmt="0.0", bold=True)
        b.set("AE%d" % r, '=IFERROR(IF(ISNUMBER($AC%(r)d),($AC%(r)d-$L%(r)d)*100/$B$9,""),"")' % f, like="N%d" % r)


# ---------------------------------------------------------------------------------------------- live quotes
#: Is a bid / ask of Borsa İstanbul a live quote?  When no order stands, Bloomberg's ``PX_BID`` / ``PX_ASK`` of the
#: exchange's sources (ISL0 / ISL1 / ISLN) still give a price - the last trade, for a bill the last trade's yield on
#: the next value date -, bid and ask the same figure.  The size of the order tells them apart: ``BID_SIZE`` /
#: ``ASK_SIZE`` > 0 while an order stands, "#N/A N/A" (the field without a value) when none does - on a closed
#: market there is no size at all.  A source without sizes (BGN, a composite: "#N/A Field Not Applicable") and a size
#: not known yet (the recorded file, an answer on its way) tell nothing: the price is shown and used as before.
RV_SIZE = ("XR", "XS")                 # DİBS RV: the sizes of the bid and the ask of the row's own security (BT)
NO_QUOTE = "–"                         # shown instead of a price that is no live quote


def size_of(expr: str) -> str:
    """A Bloomberg size as the formulas use it: the size while an order stands (> 0), 0 when none does ("#N/A
    N/A"), "" when nothing can be told (any other answer).  ``s=0``: no live quote; ``N(s)>0``: a live one."""
    return 'LET(x,%s,IFERROR(IF(ISNUMBER(x),MAX(x,0),IF(x="#N/A N/A",0,"")),""))' % expr


def quoted(price: str, size: str) -> str:
    """A visible bid / ask: the price while it is (or may be) a live quote, "–" when its size says no order stands."""
    return '=IFERROR(IF(N({p})>0,IF({s}=0,"{x}",{p}),""),"")'.format(p=price, s=size, x=NO_QUOTE)


def _rv_quote_edits(r: int) -> Tuple[Tuple[str, str, str], ...]:
    """What changes in a row of DİBS RV: (cell, the text of its formula, what it becomes).  The visible bid / ask
    (K, L) say "–" for a price that is no live quote; the dirty bid / ask (FG, FH: the bid / ask yields, their
    difference, the bid / ask ASW) and the ALIŞ / SATIŞ price types (FF) use a side only while it may be live."""
    b, a = "$%s%d" % (RV_SIZE[0], r), "$%s%d" % (RV_SIZE[1], r)
    f = {"r": r, "b": b, "a": a, "x": NO_QUOTE}
    return (("K%d" % r, "IF(N(FD{r})>0,FD{r},".format(**f), 'IF(N(FD{r})>0,IF({b}=0,"{x}",FD{r}),'.format(**f)),
            ("L%d" % r, "IF(N(FE{r})>0,FE{r},".format(**f), 'IF(N(FE{r})>0,IF({a}=0,"{x}",FE{r}),'.format(**f)),
            ("FF%d" % r, '"ALIŞ",FD{r}>0)'.format(**f), '"ALIŞ",FD{r}>0,{b}<>0)'.format(**f)),
            ("FF%d" % r, '"SATIŞ",FE{r}>0)'.format(**f), '"SATIŞ",FE{r}>0,{a}<>0)'.format(**f)),
            ("FG%d" % r, "AND(DG{r},FD{r}>0)".format(**f), "AND(DG{r},FD{r}>0,{b}<>0)".format(**f)),
            ("FH%d" % r, "AND(DG{r},FE{r}>0)".format(**f), "AND(DG{r},FE{r}>0,{a}<>0)".format(**f)))


def _rv_quotes_check(model: Model) -> None:
    _need_sheets(model, "DİBS RV")
    sh = model.sheet("DİBS RV")
    for r in range(LIVE_FIRST, LIVE_LAST + 1):
        _need_formula(model, "DİBS RV", "BT%d" % r, '"/isin/"&$A{r}&"@"&BS{r}'.format(r=r))
        for addr, old, _ in _rv_quote_edits(r):
            if _need_formula(model, "DİBS RV", addr).count(old) != 1:
                raise ValueError("DİBS RV!%s beklenen formül değil (%s yok)" % (addr, old))
        _need_formula(model, "DİBS RV", "J%d" % r, '"Son fiyat ("')
        taken = [c for c in RV_SIZE for rr in (4, r) if parse_a1("%s%d" % (c, rr)) in sh.fml or parse_a1("%s%d" % (c, rr)) in sh.consts]
        if taken:
            raise ValueError("DİBS RV!%s%d boş değil" % (taken[0], r))


def _tto_rv_quotes(model: Model) -> None:
    """DİBS RV: the sizes of each row's bid and ask (``BID_SIZE`` / ``ASK_SIZE`` of the security the row is priced
    on).  A side that is no live quote shows "–" and stays out of what the sheet works out of the sides (bid / ask
    yields, "Alış−satış", bid / ask ASW, the ALIŞ / SATIŞ price types); "Fiyat durumu" says whether the quotes are
    live.  The clean price in use - the middle, Bloomberg's ``PX_MID`` (with no quote the last trade or the
    exchange's price for the next value date) - and everything worked out of it stay as they were: the pages show
    them soft when no live quote stands behind them."""
    b = SheetBuilder(model, "DİBS RV")
    bs, as_ = RV_SIZE
    b.set("%s4" % bs, "bsz")
    b.set("%s4" % as_, "asz")
    for r in range(LIVE_FIRST, LIVE_LAST + 1):
        for col, fld in ((bs, "BID_SIZE"), (as_, "ASK_SIZE")):
            b.set("%s%d" % (col, r), '=IF($BT{r}="","",{v})'.format(r=r, v=size_of('_xll.BDP($BT%d,"%s")' % (r, fld))))
        for addr, old, new in _rv_quote_edits(r):
            b.patch(addr, "=" + formula_of(model, "DİBS RV", addr).replace(old, new))
        f = {"r": r, "b": "$%s%d" % (bs, r), "a": "$%s%d" % (as_, r)}
        state = ('IF(AND(N({b})>0,N({a})>0),"Canlı kota",IF(N({b})>0,"Canlı: yalnız bid",IF(N({a})>0,"Canlı: yalnız ask",'
                 '"Kota yok · "&IF(N(DA{r})=TODAY(),"işlem bugün",IF(N(DA{r})>0,"son fiyat ("&DAY(DA{r})&"."&MONTH(DA{r})&"."'
                 '&YEAR(DA{r})&")",IF(N(CV{r})>0,"referans fiyat","fiyat yok"))))))').format(**f)
        # (both sizes known; otherwise - BGN, the recorded file - the sheet's own words)
        b.patch("J%d" % r, ('=IF(AND($A{r}<>"",$N{r}="",ISNUMBER({b}),ISNUMBER({a})),'
                            'IF($X$2<>"ORTA",$X$2&" · ","")&{state},{old})').format(state=state, old=formula_of(model, "DİBS RV", "J%d" % r), **f))


# ---------------------------------------------------------------------------------------------- DİBS live
LIVE_SHEET = "EK_DIBS"
LIVE_FIRST, LIVE_LAST = 5, 54          # the rows of the DİBS RV list, row for row
#: the value dates: (caption, first visible column, default Bloomberg pricing source, business days after today)
LIVE_GROUPS = (("T0", "F", "ISL0", 0), ("T1", "K", "ISL1", 1), ("T2", "P", "ISLN", 2))
LIVE_EXTRA = "U"                       # one more pricing source of the desk's choice: bid / ask (BGN to start with)
LIVE_REPO = ("W", "X", "Y")            # O/N repo implied T0 -> T1, T1 -> T2, T0 -> T1 against TLREF (bp)
LIVE_HELP = "AA"                       # the helper columns start here: securities, Bloomberg's answers, mids
_LIVE_FIELDS = ("bid", "ask", "last", "date", "vol", "acc")


def _live_cols() -> Dict[str, Any]:
    """Where everything of the EK_DIBS sheet is (column letters)."""
    from .xl.tokenizer import col_to_index
    h = col_to_index(LIVE_HELP)
    out: Dict[str, Any] = {"sec": [index_to_col(h + k) for k in range(3)], "sec_extra": index_to_col(h + 3), "raw": [],
                           "groups": []}
    at = h + 4
    for k, (cap, first, src, days) in enumerate(LIVE_GROUPS):
        out["raw"].append({f: index_to_col(at + i) for i, f in enumerate(_LIVE_FIELDS)})
        at += len(_LIVE_FIELDS)
        c = col_to_index(first)
        out["groups"].append({"cap": cap, "src": "%s2" % first, "date": "%s2" % index_to_col(c + 1), "default": src, "days": days,
                              "bid": first, "ask": index_to_col(c + 1), "last": index_to_col(c + 2),
                              "when": index_to_col(c + 3), "vol": index_to_col(c + 4)})
    out["raw_extra"] = {"bid": index_to_col(at), "ask": index_to_col(at + 1)}
    out["mid"] = [index_to_col(at + 2 + k) for k in range(3)]
    # after them (the columns above keep their places): the sizes of the quotes and the day of each value date's price
    at += 5
    out["size"] = [{"bid": index_to_col(at + 2 * k), "ask": index_to_col(at + 2 * k + 1)} for k in range(len(LIVE_GROUPS))]
    at += 2 * len(LIVE_GROUPS)
    out["size_extra"] = {"bid": index_to_col(at), "ask": index_to_col(at + 1)}
    out["day"] = [index_to_col(at + 2 + k) for k in range(len(LIVE_GROUPS))]
    out["last_help"] = out["day"][-1]
    return out


def _dibs_live_check(model: Model) -> None:
    _need_sheets(model, "DİBS RV", "Motor", "OIS_MAIN")
    _need_formula(model, "DİBS RV", "BT5", '"/isin/"&$A5&"@"&BS5')      # the security as the sheet writes it
    _need_formula(model, "DİBS RV", "BS5", "$B$2")
    for addr, has in (("K5", "FD5"), ("L5", "FE5"), ("AS5", "FX5"), ("I5", "DA5"), ("CW5", "CF5"), ("DC5", 'BS5="ISL0"'),
                      ("DC5", "Motor!$A$361:$A$523")):
        _need_formula(model, "DİBS RV", addr, has)


def _tto_dibs_live(model: Model) -> None:
    """The bonds of the DİBS RV list on the three value dates of Borsa İstanbul: per value date (T0, T1, T2 - a
    Bloomberg pricing source each, typed over freely) the bid, the ask, the last trade with its day and the
    volume; the bid / ask of one more source; and the overnight repo the prices imply between the value dates
    (dirty prices: the clean price plus the accrued interest of each value date), against TLREF.

    The value date the DİBS RV row itself is priced on is read from that sheet (the same Bloomberg call), so the
    recorded file shows it offline; the other value dates ask Bloomberg."""
    b = SheetBuilder(model, LIVE_SHEET)
    L = _live_cols()
    rv = "'DİBS RV'!"
    hol = "Motor!$A$361:$A$523"
    b.title("A1", "DİBS TRADING  ·  T0 / T1 / T2 fiyatları, son işlem, ek kaynak, ima O/N repo  (trading listesi: DİBS RV)")
    b.set("A2", "Kaynak · valör", bold=True)
    for g in L["groups"]:
        b.input(g["src"], g["default"], align="center")
        when = "TODAY()" if g["days"] == 0 else "WORKDAY(TODAY(),%d,%s)" % (g["days"], hol)
        b.set(g["date"], "=" + when, fmt=DATE, color=NOTE_COLOR)
        b.set("%s3" % g["bid"], "%s · aynı gün" % g["cap"] if g["days"] == 0 else "%s · %d iş günü sonra" % (g["cap"], g["days"]),
              bold=True)
    b.input("%s2" % LIVE_EXTRA, "BGN", align="center")
    b.set("%s3" % LIVE_EXTRA, "Ek kaynak", bold=True)
    w, x, y = LIVE_REPO
    b.set("%s2" % w, "TLREF (O/N, %)", color=NOTE_COLOR, align="right")
    b.set("%s2" % x, "=OIS_MAIN!$J$2*100", fmt="0.00", color=NOTE_COLOR)
    b.set("%s3" % w, "İma O/N repo (kirli fiyatlardan, ACT/365)", bold=True)
    heads = ["ISIN", "Kâğıt", "Tip", "Vade", "Kupon"]
    for g in L["groups"]:
        heads += ["%s bid" % g["cap"], "%s ask" % g["cap"], "%s son işlem" % g["cap"], "%s son işlem günü" % g["cap"],
                  "%s hacim" % g["cap"]]
    heads += ["Ek bid", "Ek ask", "T0→T1 repo %", "T1→T2 repo %", "T0→T1 − TLREF (bp)"]
    b.head("A4", heads)
    b.head("%s4" % LIVE_HELP, ["Menkul T0", "Menkul T1", "Menkul T2", "Menkul ek"]
           + ["%s %s" % (g["cap"], f) for g in L["groups"] for f in ("bid", "ask", "son", "gün", "hacim", "işlemiş")]
           + ["Ek bid", "Ek ask", "Orta T0", "Orta T1", "Orta T2"]
           + ["%s %s boyut" % (g["cap"], side) for g in L["groups"] for side in ("bid", "ask")]
           + ["Ek bid boyut", "Ek ask boyut"] + ["Fiyat günü %s" % g["cap"] for g in L["groups"]])

    def source(cell: str, default: str) -> str:
        """The pricing source typed in a cell (its default when the cell was emptied)."""
        return 'IF(TRIM(%s&"")="","%s",TRIM(UPPER(%s)))' % (cell, default, cell)

    def security(src: str, default: str, r: int) -> str:
        s = source(src, default)
        return ('=IF($A{r}="","",IF({rv}$N$2="/isin/","/isin/"&$A{r}&"@"&{s},$A{r}&" @"&{s}&" "&{rv}$N$2))'
                .format(r=r, rv=rv, s=s))

    def clean(ref: str) -> str:
        return '=IFERROR(IF(N(%s)>0,%s,""),"")' % (ref, ref)

    for r in range(LIVE_FIRST, LIVE_LAST + 1):
        b.set("A%d" % r, '=IF(TRIM(%s$A%d&"")="","",UPPER(TRIM(%s$A%d&"")))' % (rv, r, rv, r))
        b.set("B%d" % r, '=IF($A{r}="","",IF(ISNUMBER({rv}$E{r}),TEXT({rv}$E{r},"dd.mm.yy")&IF({rv}$D{r}="T"," TLREF",'
                         'IF({rv}$D{r}="F"," FRN",IF({rv}$D{r}="E"," TÜFE",IF({rv}$D{r}="B"," Bono","")))),'
                         '$A{r}))'.format(r=r, rv=rv), bold=True)
        b.set("C%d" % r, '=IF($A{r}="","",{rv}$D{r})'.format(r=r, rv=rv), align="center")
        b.set("D%d" % r, '=IF($A{r}="","",{rv}$E{r})'.format(r=r, rv=rv), fmt=DATE)
        b.set("E%d" % r, '=IF($A{r}="","",{rv}$G{r})'.format(r=r, rv=rv), fmt="0.00%")
        for k, g in enumerate(L["groups"]):
            sec = "$%s%d" % (L["sec"][k], r)
            raw = L["raw"][k]
            src_cell = "$%s$2" % g["src"][:-1]
            b.set("%s%d" % (L["sec"][k], r), security(src_cell, g["default"], r))
            same = 'AND($A{r}<>"",{s}={rv}$BS{r})'.format(r=r, s=source(src_cell, g["default"]), rv=rv)
            # (bid / ask: Bloomberg's figure, live quote or not - FD / FE, where DİBS RV keeps it before it says "–")
            own = {"bid": "$FD", "ask": "$FE", "last": "$AS", "date": "$I"}
            fields = {"bid": "PX_BID", "ask": "PX_ASK", "last": "LAST_PRICE", "date": "LAST_TRADE_DATE"}
            for f in ("bid", "ask", "last", "date"):
                b.set("%s%d" % (raw[f], r), '=IF($A{r}="","",IF({same},{rv}{own}{r},_xll.BDP({sec},"{fld}")))'.format(
                    r=r, same=same, rv=rv, own=own[f], sec=sec, fld=fields[f]))
            b.set("%s%d" % (raw["vol"], r), '=IF($A{r}="","",_xll.BDP({sec},"VOLUME"))'.format(r=r, sec=sec))
            b.set("%s%d" % (raw["acc"], r),
                  '=IF($A{r}="","",IF({rv}$D{r}="B",0,IF(AND({same},${d}=({rv}$DC{r})),{rv}$CW{r},'
                  '_xll.BDP({sec},"INT_ACC","SETTLE_DT",${d}))))'.format(r=r, rv=rv, same=same, sec=sec,
                                                                       d=g["date"][:-1] + "$2"))
            sz = L["size"][k]
            for side, fld, rv_col in (("bid", "BID_SIZE", RV_SIZE[0]), ("ask", "ASK_SIZE", RV_SIZE[1])):
                b.set("%s%d" % (sz[side], r), '=IF($A{r}="","",{v})'.format(r=r, v=size_of(
                    'IF({same},{rv}${c}{r},_xll.BDP({sec},"{fld}"))'.format(same=same, rv=rv, c=rv_col, r=r, sec=sec, fld=fld))),
                      fmt=INT0)
            b.set("%s%d" % (g["bid"], r), quoted("%s%d" % (raw["bid"], r), "%s%d" % (sz["bid"], r)), fmt="0.000")
            b.set("%s%d" % (g["ask"], r), quoted("%s%d" % (raw["ask"], r), "%s%d" % (sz["ask"], r)), fmt="0.000")
            b.set("%s%d" % (g["last"], r), clean("%s%d" % (raw["last"], r)), fmt="0.000", bold=True)
            d = "%s%d" % (raw["date"], r)
            b.set("%s%d" % (g["when"], r),
                  '=IFERROR(IF(ISNUMBER({d}),IF({d}>0,{d},""),IF(TRIM({d}&"")="","",DATE(VALUE(RIGHT({d},4)),'
                  'VALUE(MID({d},FIND(".",{d})+1,FIND(".",{d},FIND(".",{d})+1)-FIND(".",{d})-1)),VALUE(LEFT({d},FIND(".",{d})-1))))),"")'
                  .format(d=d), fmt=DATE)
            b.set("%s%d" % (g["vol"], r), clean("%s%d" % (raw["vol"], r)), fmt=INT0)
            # the price of the value date: the middle of its bid and ask, or - when a side is no live quote - its last
            # trade; of today while both sides are live quotes, else of the day of the last trade
            p = {"b": "%s%d" % (g["bid"], r), "a": "%s%d" % (g["ask"], r), "l": "%s%d" % (g["last"], r),
                 "bs": "%s%d" % (sz["bid"], r), "as": "%s%d" % (sz["ask"], r), "w": "%s%d" % (g["when"], r)}
            b.set("%s%d" % (L["mid"][k], r), '=IF(AND(ISNUMBER({b}),ISNUMBER({a})),({b}+{a})/2,'
                                              'IF(AND(OR({bs}=0,{as}=0),ISNUMBER({l})),{l},""))'.format(**p), fmt="0.0000")
            b.set("%s%d" % (L["day"][k], r), '=IF(AND(N({bs})>0,N({as})>0),TODAY(),{w})'.format(**p), fmt=DATE)
        # one more source
        b.set("%s%d" % (L["sec_extra"], r), security("$%s$2" % LIVE_EXTRA, "BGN", r))
        ex_bid, ex_ask = L["raw_extra"]["bid"], L["raw_extra"]["ask"]
        b.set("%s%d" % (ex_bid, r), '=IF($A{r}="","",_xll.BDP(${s}{r},"PX_BID"))'.format(r=r, s=L["sec_extra"]))
        b.set("%s%d" % (ex_ask, r), '=IF($A{r}="","",_xll.BDP(${s}{r},"PX_ASK"))'.format(r=r, s=L["sec_extra"]))
        se = L["size_extra"]
        for side, fld in (("bid", "BID_SIZE"), ("ask", "ASK_SIZE")):
            b.set("%s%d" % (se[side], r), '=IF($A{r}="","",{v})'.format(r=r, v=size_of('_xll.BDP(${s}{r},"{fld}")'.format(
                s=L["sec_extra"], r=r, fld=fld))), fmt=INT0)
        e1 = index_to_col(_col(LIVE_EXTRA) + 1)
        b.set("%s%d" % (LIVE_EXTRA, r), quoted("%s%d" % (ex_bid, r), "%s%d" % (se["bid"], r)), fmt="0.000")
        b.set("%s%d" % (e1, r), quoted("%s%d" % (ex_ask, r), "%s%d" % (se["ask"], r)), fmt="0.000")
        # the overnight repo the dirty prices of two value dates imply - only from prices of the same day (live quotes
        # on both, or the last trades of both on one day: a T0 price of two weeks ago against today's T1 implies
        # nothing); none for a CPI linker (its TL price moves with the index ratio of each value date)
        for col, (k0, k1) in ((w, (0, 1)), (x, (1, 2))):
            g0, g1 = L["groups"][k0], L["groups"][k1]
            m0, m1 = "%s%d" % (L["mid"][k0], r), "%s%d" % (L["mid"][k1], r)
            a0, a1 = "%s%d" % (L["raw"][k0]["acc"], r), "%s%d" % (L["raw"][k1]["acc"], r)
            d0, d1 = "$%s$2" % g0["date"][:-1], "$%s$2" % g1["date"][:-1]
            t0, t1 = "%s%d" % (L["day"][k0], r), "%s%d" % (L["day"][k1], r)
            b.set("%s%d" % (col, r),
                  '=IF(OR($A{r}="",{rv}$D{r}="E"),"",IFERROR(IF(AND(ISNUMBER({m0}),ISNUMBER({m1}),ISNUMBER({a0}),ISNUMBER({a1}),{d1}>{d0},'
                  'ISNUMBER({t0}),ISNUMBER({t1}),{t0}={t1}),'
                  '(({m1}+{a1})/({m0}+{a0})-1)*365/({d1}-{d0})*100,""),""))'.format(r=r, rv=rv, m0=m0, m1=m1, a0=a0, a1=a1, d0=d0, d1=d1,
                                                                                    t0=t0, t1=t1),
                  fmt="0.00", bold=col == w)
        b.set("%s%d" % (y, r), '=IF(ISNUMBER({w}{r}),({w}{r}/100-OIS_MAIN!$J$2)*10000,"")'.format(w=w, r=r), fmt="0")
    b.note("A%d" % (LIVE_LAST + 2),
           "Kâğıtlar DİBS RV listesindekilerdir (oraya eklenen buraya da gelir). Her valör bir Bloomberg fiyat kaynağıdır "
           "(ISL0 = aynı gün, ISL1 = ertesi iş günü, ISLN = iki iş günü sonra) - sarı hücreye başka kod "
           "yazılabilir. Kâğıdın DİBS RV'de fiyatlandığı kaynak o sayfadan okunur. Repo: iki valörün kirli fiyatlarından "
           "(temiz + o valördeki işlemiş faiz), (kirli2 / kirli1 − 1) · 365 / gün; tek bir fiyat adımı (0,005) bir günde "
           "~1,8 puan eder. Repo yalnız iki valörün fiyatı aynı güne aitse (son işlemleri aynı gündeyse) hesaplanır: "
           "eski bir T0 fiyatıyla bugünün T1 fiyatı bir repo söylemez. Bid / ask yalnız o tarafta emir varsa (Bloomberg "
           "BID_SIZE / ASK_SIZE > 0) fiyattır; emir yoksa \"–\" (kaynak son fiyatı tekrar eder). Fiyat: bid ve ask'ın "
           "ortası, bir taraf kotasızsa son işlem; iki taraf da canlıysa bugünün fiyatıdır.")
    b.sheet.freeze = [4, 2]


def _col(letter: str) -> int:
    from .xl.tokenizer import col_to_index
    return col_to_index(letter)


# ---------------------------------------------------------------------------------------------- every bond
UNI_SHEET = "EK_EVREN"
UNI_FIRST = 6                          # the bonds of Tüm Kâğıtlar from here, one a row: the service writes them
UNI_ROWS = 160                         # room for this many (the list has ~80; a bond past its maturity leaves its row)
UNI_LAST = UNI_FIRST + UNI_ROWS - 1
#: the kinds in the order the desk thinks of them: (kind, caption, the value date it trades on)
UNI_KINDS = (("bill", "Bono", "bill"), ("zero", "Kuponsuz", "bill"), ("fixed", "Sabit kuponlu", "bond"),
             ("float", "TLREF'e endeksli", "bond"), ("frn", "FRN", "bond"), ("cpi", "TÜFE'ye endeksli", "bond"))
#: the kind's code of a bond's row, right of Bloomberg's answers (T:Z) and of what is added next to them (AA:AB)
UNI_KIND = "AC"
#: the cells of a bond's row the service writes: ISIN, name, kind and coupon as shown, maturity, the kind's code
UNI_WRITTEN = ("A", "B", "C", "D", "E", UNI_KIND)
UNI_RAW = ("bid", "ask", "last", "date", "vol")
#: what the trading list (DİBS RV) says of a bond that is on it: (column there, caption, number format)
UNI_RV = (("T", "Getiri % (RV)", "0.00%"), ("Z", "ASW / DM (bp)", "0"), ("AC", "Sinyal", None), ("AI", "DV01 / 1mn", "0.0"))


def universe_kind(isin: str) -> str:
    """A formula's text: the kind (its code) Tüm Kâğıtlar has for the ISIN in cell ``isin`` ("" when it is not there)."""
    return ('IFERROR(INDEX(%s!$%s$%d:$%s$%d,MATCH(UPPER(TRIM(%s&"")),%s!$A$%d:$A$%d,0))&"","")'
            % (UNI_SHEET, UNI_KIND, UNI_FIRST, UNI_KIND, UNI_LAST, isin, UNI_SHEET, UNI_FIRST, UNI_LAST))


def _universe_check(model: Model) -> None:
    _dibs_live_check(model)
    for addr, has in (("T5", "DY5"), ("Z5", "EH5"), ("AC5", "FV5"), ("AI5", "ED5")):
        _need_formula(model, "DİBS RV", addr, has)


def _tto_universe(model: Model) -> None:
    """Every TRY government bond of the desk's list in one place: what it is, how long it has left, whether it is on
    the trading list (DİBS RV), its price on Borsa İstanbul (bid, ask, the last trade and its day, the volume - bills
    on their own value date, the rest on theirs) and, for a bond on the trading list, what DİBS RV says of it.

    The list is the desk's (the catalog file and the bonds added, less the ones taken off and the ones past their
    maturity): the service writes a bond's ISIN, name, kind, coupon and maturity on a row of its own (``UNI_WRITTEN``)
    and the page shows them kind by kind, by maturity.  A bond's price comes from DİBS RV when it is listed there on
    the same source (the recorded file shows it offline); the others ask Bloomberg."""
    b = SheetBuilder(model, UNI_SHEET)
    rv = "'DİBS RV'!"
    lst = "$%s$5:$%s$54"
    b.title("A1", "TÜM KÂĞITLAR  ·  TRY devlet iç borçlanma senetleri (★: trading listesinde - DİBS RV ve DİBS Trading)")
    b.set("B2", "Kaynak · bono / kuponsuz", color=NOTE_COLOR, align="right")
    b.input("C2", "ISL0", align="center")
    b.set("D2", "tahvil", color=NOTE_COLOR, align="right")
    b.input("E2", "ISL1", align="center")
    b.head("A4", ["ISIN", "Kâğıt", "Tür", "Kupon", "Vade", "Kalan gün", "Kalan yıl", "Trading", "Bid", "Ask", "Son işlem",
                  "Son işlem günü", "Hacim"] + [cap for _, cap, _ in UNI_RV] + ["Kaynak"])
    b.head("T4", ["RV satırı", "Menkul", "bid", "ask", "son", "gün", "hacim"])
    b.head("%s4" % UNI_KIND, ["tür"])
    for r in range(UNI_FIRST, UNI_LAST + 1):
        a = "$A%d" % r
        b.set("B%d" % r, None, bold=True)
        b.set("D%d" % r, None, fmt="0.00%")
        b.set("E%d" % r, None, fmt=DATE)
        b.set("F%d" % r, '=IF(ISNUMBER($E{r}),$E{r}-TODAY(),"")'.format(r=r), fmt=INT0)
        b.set("G%d" % r, '=IF(ISNUMBER($F{r}),$F{r}/365.25,"")'.format(r=r), fmt="0.00")
        b.set("H%d" % r, '=IF({a}="","",IF(ISNUMBER($T{r}),"★",""))'.format(a=a, r=r), align="center", bold=True)
        b.set("T%d" % r, '=IF({a}="","",IFERROR(MATCH({a},{rv}$A$5:$A$54,0),""))'.format(a=a, rv=rv))
        # bills and zero coupon bonds on their own value date (and source), the rest on the bonds'
        b.set("R%d" % r, '=IF({a}="","",IF(OR(${k}{r}="bill",${k}{r}="zero"),IF(TRIM($C$2&"")="","ISL0",TRIM(UPPER($C$2))),'
                         'IF(TRIM($E$2&"")="","ISL1",TRIM(UPPER($E$2)))))'.format(a=a, r=r, k=UNI_KIND),
              align="center", color=NOTE_COLOR)
        b.set("U%d" % r, '=IF({a}="","",IF({rv}$N$2="/isin/","/isin/"&{a}&"@"&$R{r},{a}&" @"&$R{r}&" "&{rv}$N$2))'.format(
            a=a, rv=rv, r=r))
        same = 'IF(ISNUMBER($T{r}),$R{r}=INDEX({rv}{bs},$T{r}),FALSE)'.format(r=r, rv=rv, bs=lst % ("BS", "BS"))
        for f, field, own in (("bid", "PX_BID", "K"), ("ask", "PX_ASK", "L"), ("last", "LAST_PRICE", "AS"), ("date", "LAST_TRADE_DATE", "I")):
            col = index_to_col(_col("V") + UNI_RAW.index(f))
            b.set("%s%d" % (col, r), '=IF({a}="","",IF({same},INDEX({rv}{own},$T{r}),_xll.BDP($U{r},"{fld}")))'.format(
                a=a, same=same, rv=rv, own=lst % (own, own), r=r, fld=field))
        vcol = index_to_col(_col("V") + UNI_RAW.index("vol"))
        b.set("%s%d" % (vcol, r), '=IF({a}="","",_xll.BDP($U{r},"VOLUME"))'.format(a=a, r=r))
        for k, (vis, raw) in enumerate(zip("IJK", ("V", "W", "X"))):
            b.set("%s%d" % (vis, r), '=IFERROR(IF(N({c}{r})>0,{c}{r},""),"")'.format(c=raw, r=r), fmt="0.000", bold=vis == "K")
        d = "Y%d" % r
        b.set("L%d" % r,
              '=IFERROR(IF(ISNUMBER({d}),IF({d}>0,{d},""),IF(TRIM({d}&"")="","",DATE(VALUE(RIGHT({d},4)),'
              'VALUE(MID({d},FIND(".",{d})+1,FIND(".",{d},FIND(".",{d})+1)-FIND(".",{d})-1)),VALUE(LEFT({d},FIND(".",{d})-1))))),"")'
              .format(d=d), fmt=DATE)
        b.set("M%d" % r, '=IFERROR(IF(N($Z{r})>0,$Z{r},""),"")'.format(r=r), fmt=INT0)
        for k, (col, _, fmt) in enumerate(UNI_RV):
            b.set("%s%d" % (index_to_col(_col("N") + k), r), '=IF(ISNUMBER($T{r}),INDEX({rv}{c},$T{r}),"")'.format(
                r=r, rv=rv, c=lst % (col, col)), fmt=fmt, bold=col == "AC")
    b.note("A%d" % (UNI_LAST + 2),
           "★ trading listesindeki (DİBS RV ve DİBS Trading) kâğıtlardır; ☆ / ★ ile eklenir, çıkarılır. Liste masanındır: "
           "+ ISIN ekle ile kâğıt eklenir (türü Bloomberg'den bulunur, kendi grubuna girer), ✕ ile çıkarılır; vadesi geçen "
           "kâğıt ertesi gün düşer. Fiyatlar Borsa İstanbul'dan (bono ve kuponsuz kendi valöründe, diğerleri ertesi gün; "
           "kaynaklar sarı hücrelerde). Getiri, ASW ve sinyal yalnızca trading listesindeki kâğıtlar için hesaplanır; FRN "
           "yalnız fiyatla izlenir.")
    b.sheet.freeze = [4, 2]


#: EK_EVREN: the sizes of a bond's bid and ask, next to Bloomberg's other answers (T:Z)
UNI_SIZE = ("AA", "AB")


def _universe_quote_rows(model: Model) -> List[int]:
    """The rows of EK_EVREN that price a bond: those that ask Bloomberg for one (a security in U)."""
    sh = model.sheet(UNI_SHEET)
    return [r for r in range(UNI_FIRST, sh.max_row + 1) if parse_a1("U%d" % r) in sh.fml]


def _universe_quote_edits(r: int) -> Tuple[Tuple[str, str, str], ...]:
    """What changes in a bond's row of EK_EVREN: (cell, the text of its formula, what it becomes).  The price from
    DİBS RV is Bloomberg's figure (FD / FE: live quote or not); the visible bid / ask (I, J) say "–" for a price that
    is no live quote."""
    f = {"r": r, "b": "$%s%d" % (UNI_SIZE[0], r), "a": "$%s%d" % (UNI_SIZE[1], r), "x": NO_QUOTE}
    return (("V%d" % r, "'DİBS RV'!$K$5:$K$54", "'DİBS RV'!$FD$5:$FD$54"),
            ("W%d" % r, "'DİBS RV'!$L$5:$L$54", "'DİBS RV'!$FE$5:$FE$54"),
            ("I%d" % r, "IF(N(V{r})>0,V{r},".format(**f), 'IF(N(V{r})>0,IF({b}=0,"{x}",V{r}),'.format(**f)),
            ("J%d" % r, "IF(N(W{r})>0,W{r},".format(**f), 'IF(N(W{r})>0,IF({a}=0,"{x}",W{r}),'.format(**f)))


def _universe_quotes_check(model: Model) -> None:
    _need_sheets(model, UNI_SHEET)
    _need_formula(model, "DİBS RV", "%s%d" % (RV_SIZE[0], LIVE_FIRST), "BID_SIZE")        # DİBS RV has its sizes
    rows = _universe_quote_rows(model)
    if not rows:
        raise ValueError("%s: kâğıt satırı yok" % UNI_SHEET)
    sh = model.sheet(UNI_SHEET)
    for r in rows:
        _need_formula(model, UNI_SHEET, "V%d" % r, "$R{r}=INDEX('DİBS RV'!$BS$5:$BS$54,$T{r})".format(r=r))
        for addr, old, _ in _universe_quote_edits(r):
            if _need_formula(model, UNI_SHEET, addr).count(old) != 1:
                raise ValueError("%s!%s beklenen formül değil (%s yok)" % (UNI_SHEET, addr, old))
        taken = [c for c in UNI_SIZE for rr in (4, r) if parse_a1("%s%d" % (c, rr)) in sh.fml or parse_a1("%s%d" % (c, rr)) in sh.consts]
        if taken:
            raise ValueError("%s!%s%d boş değil" % (UNI_SHEET, taken[0], r))


def _tto_universe_quotes(model: Model) -> None:
    """Tüm Kâğıtlar: the sizes of each bond's bid and ask (from DİBS RV for a bond priced there on the same source,
    else ``BID_SIZE`` / ``ASK_SIZE`` of its own security); a side that is no live quote shows "–"."""
    b = SheetBuilder(model, UNI_SHEET)
    b.head("%s4" % UNI_SIZE[0], ["bid boyut", "ask boyut"])
    for r in _universe_quote_rows(model):
        same = "IF(ISNUMBER($T{r}),$R{r}=INDEX('DİBS RV'!$BS$5:$BS$54,$T{r}),FALSE)".format(r=r)
        for col, fld, rv_col in ((UNI_SIZE[0], "BID_SIZE", RV_SIZE[0]), (UNI_SIZE[1], "ASK_SIZE", RV_SIZE[1])):
            b.set("%s%d" % (col, r), '=IF($A{r}="","",{v})'.format(r=r, v=size_of(
                "IF({same},INDEX('DİBS RV'!${c}$5:${c}$54,$T{r}),_xll.BDP($U{r},\"{fld}\"))".format(same=same, c=rv_col, r=r, fld=fld))),
                  fmt=INT0)
        for addr, old, new in _universe_quote_edits(r):
            b.patch(addr, "=" + formula_of(model, UNI_SHEET, addr).replace(old, new))


# ---------------------------------------------------------------------------------------------- FRN on DİBS RV
#: DİBS RV's own cells for the FRN, right of the workbook's: the kind Tüm Kâğıtlar has for the bond, what Bloomberg says
#: when the list does not have it (the floater formula, the reset index), whether the bond is an FRN
RV_FRN = {"kind": "YA", "formula": "YB", "reset": "YC", "frn": "YD"}
#: what DİBS RV works out against TLREF - the discount margin and what is made of it, the OIS par yield, the carry and
#: the roll: blank for an FRN, priced only (its coupon does not follow TLREF)
RV_FRN_BLANK = ("W", "X", "Z", "AD", "AE", "AF", "AI", "AK", "AM", "AN", "AO", "AP", "AQ")


def frn_test(kind: str, cpn_kind: str, formula: str, reset: str) -> str:
    """A formula's text: TRUE for an FRN - a floater (``cpn_kind`` is "T") that Tüm Kâğıtlar has as one (``kind``,
    its code there) or, when the list does not have it, whose floater formula Bloomberg gives without TLREF and whose
    reset index is not TLREF's (BISTREFI).  Bloomberg not answering leaves a floater a TLREF one."""
    return ('IF({t}<>"T",FALSE,IF({k}<>"",{k}="frn",AND(ISTEXT({x}),LEFT({x}&"",1)<>"#",NOT(ISNUMBER(SEARCH("BISTREF",{x}&""))),'
            'NOT(ISNUMBER(SEARCH("TLREF",IFERROR({f}&"","")))))))').format(t=cpn_kind, k=kind, x=reset, f=formula)


def _rv_frn_check(model: Model) -> None:
    _need_sheets(model, "DİBS RV", UNI_SHEET)
    _need_formula(model, "DİBS RV", "D5", "CR5")
    _need_formula(model, "DİBS RV", "G5", "TLREF+")
    _need_formula(model, "DİBS RV", "CR5", "FLOAT")
    _need_formula(model, "DİBS RV", "BR5", "$A5")
    for col in RV_FRN_BLANK:
        _need_formula(model, "DİBS RV", "%s5" % col)
    sh = model.sheet("DİBS RV")
    for col in RV_FRN.values():
        for r in range(1, 56):
            rc = parse_a1("%s%d" % (col, r))
            if rc in sh.fml or rc in sh.consts:
                raise ValueError("DİBS RV!%s%d dolu" % (col, r))


def _tto_rv_frn(model: Model) -> None:
    """DİBS RV tells an FRN from a TLREF floater (its "T" bonds): by Tüm Kâğıtlar's kind for the bond or, for a bond
    the list does not have, by what Bloomberg says (``frn_test``).  An FRN is "F" in the kind column and "FRN" in the
    coupon's, and what DİBS RV works out against TLREF (``RV_FRN_BLANK``) is blank for it."""
    b = SheetBuilder(model, "DİBS RV")
    k, f, x, frn = RV_FRN["kind"], RV_FRN["formula"], RV_FRN["reset"], RV_FRN["frn"]
    b.head("%s4" % k, ["Tür (Tüm Kâğıtlar)", "FLOATER_FORMULA", "RESET_IDX", "FRN"])
    was = {(col, r): formula_of(model, "DİBS RV", "%s%d" % (col, r)) for col in ("D", "G") + RV_FRN_BLANK for r in range(5, 55)}
    for r in range(5, 55):
        b.set("%s%d" % (k, r), '=IF($A{r}="","",{kind})'.format(r=r, kind=universe_kind("$A%d" % r)))
        ask = 'AND(CR{r}="T",{k}{r}="")'.format(r=r, k=k)
        b.set("%s%d" % (f, r), '=IF({ask},_xll.BDP(BR{r},"FLOATER_FORMULA"),"")'.format(ask=ask, r=r))
        b.set("%s%d" % (x, r), '=IF({ask},_xll.BDP(BR{r},"RESET_IDX"),"")'.format(ask=ask, r=r))
        b.set("%s%d" % (frn, r), "=" + frn_test("%s%d" % (k, r), "CR%d" % r, "%s%d" % (f, r), "%s%d" % (x, r)))
        b.patch("D%d" % r, '=IF({frn}{r},"F",{was})'.format(frn=frn, r=r, was=was[("D", r)]))
        b.patch("G%d" % r, '=IF(AND(DG{r},{frn}{r}),IF(ISNUMBER(DP{r}),"sabit %"&ROUND(DP{r},2)&" · ","")&"FRN",{was})'.format(
            frn=frn, r=r, was=was[("G", r)]))
        for col in RV_FRN_BLANK:
            b.patch("%s%d" % (col, r), '=IF({frn}{r},"",{was})'.format(frn=frn, r=r, was=was[(col, r)]))
    if model.sheet("DİBS RV").consts.get(parse_a1("D4")) == "Tip (S/T/E/B)":
        b.set("D4", "Tip (S/T/F/E/B)", like="D4")


# ---------------------------------------------------------------------------------------------- carry path
CARRY_SHEET = "EK_CARRY"
#: the TLREF path the carry engine compounds over the horizon: the value of the choice, and what it is
CARRY_PATHS = (("Bootstrap", "piyasa OIS eğrisinin (bootstrap) ima ettiği TLREF"),
               ("MPC ima", "kotaların ima ettiği PPK patikası"),
               ("S1", "S1 senaryosu"), ("S2", "S2 senaryosu"), ("S3", "S3 senaryosu"),
               ("Sabit TLREF", "bugünkü TLREF, sabit"))
CARRY_DEFAULT = "Bootstrap"
#: the meeting table of the Motor sheet: a path's TLREF after each meeting and its compounded log growth
CARRY_MEETING_PATHS = {"S1": ("H", "I"), "S2": ("N", "O"), "S3": ("P", "Q"), "MPC ima": ("K", "L")}
CARRY_ENGINE_A = (182, 197)               # Motor: the tenor engine of horizon A ...
CARRY_ENGINE_B = (201, 216)               # ... and of horizon B (the same tenors)
CARRY_PERIODS = (139, 178)                # Motor: the quarterly schedule (payment days in F)
CARRY_TENOR_ROW = 11                      # EK_CARRY: first row of the tenors' G(T)
CARRY_PERIOD_ROW = 29                     # EK_CARRY: first row of the payment days' G(t)


def carry_growth(days: str, which: str) -> str:
    """The growth factor G(d) of TLREF compounded on business days from the OIS spot date ``days`` later, along the
    path in cell ``which`` (1 = Sabit TLREF, 2-4 = S1-S3, 5 = MPC ima, 6 = Bootstrap) - the Motor sheet's own
    formula for its scenario paths, and for the bootstrapped curve 1 / its discount factor."""
    def meeting(tl: str, lng: str) -> str:
        m = "MATCH(%s,Motor!$C$4:$C$84,1)" % days
        return ("EXP(INDEX(Motor!$%(g)s$4:$%(g)s$84,%(m)s)+(%(d)s-INDEX(Motor!$C$4:$C$84,%(m)s))*LN(1+INDEX(Motor!$%(t)s$4:$%(t)s$84,%(m)s)/365)"
                "-(INDEX(Motor!$F$528:$F$4228,MIN(%(d)s,3700)+1)-INDEX(Motor!$J$4:$J$84,%(m)s))*(INDEX(Motor!$%(t)s$4:$%(t)s$84,%(m)s)/365)^2)"
                % {"g": lng, "t": tl, "m": m, "d": days})
    flat = ("EXP(%(d)s*LN(1+OIS_MAIN!$J$2/365)-INDEX(Motor!$F$528:$F$4228,MIN(%(d)s,3700)+1)*(OIS_MAIN!$J$2/365)^2)" % {"d": days})
    k = "MIN(MATCH(%s,Motor!$C$88:$C$130,1),42)" % days
    boot = ("1/EXP(INDEX(Motor!$I$88:$I$130,%(k)s)+(INDEX(Motor!$I$88:$I$130,%(k)s+1)-INDEX(Motor!$I$88:$I$130,%(k)s))*(%(d)s-INDEX(Motor!$C$88:$C$130,%(k)s))"
            "/(INDEX(Motor!$C$88:$C$130,%(k)s+1)-INDEX(Motor!$C$88:$C$130,%(k)s)))" % {"k": k, "d": days})
    paths = [flat] + [meeting(*CARRY_MEETING_PATHS[n]) for n in ("S1", "S2", "S3", "MPC ima")] + [boot]
    return "CHOOSE(%s,%s)" % (which, ",".join(paths))


def _carry_check(model: Model) -> None:
    """The carry engine of the Motor sheet compounds TLREF along the S1 path in the cells this addition re-points:
    the horizon growth (E134 / E135), each tenor's growth (F182:F216), the reinvestment of coupons paid before the
    horizon (J / K139:178, L182:L216) and the TLREF at the horizon (G134 / G135)."""
    _need_sheets(model, "Motor", "OIS_MAIN", "C & R")
    for addr in ("E134", "E135", "G134", "G135"):
        _need_formula(model, "Motor", addr, "$H$4:$H$84")
    for first, last in (CARRY_ENGINE_A, CARRY_ENGINE_B):
        for r in range(first, last + 1):
            _need_formula(model, "Motor", "F%d" % r, "$I$4:$I$84")
            _need_formula(model, "Motor", "L%d" % r, "/$G$139:$G$178")
    for r in range(CARRY_PERIODS[0], CARRY_PERIODS[1] + 1):
        _need_formula(model, "Motor", "J%d" % r, "$E$134/G%d" % r)
        _need_formula(model, "Motor", "K%d" % r, "$E$135/G%d" % r)
    for tl, lng in CARRY_MEETING_PATHS.values():                    # the meeting table holds the paths there
        _need_formula(model, "Motor", "%s5" % lng, "LN(1+(%s4)/365)" % tl)
    _need_formula(model, "Motor", "I89", "LN(G89)")                  # the bootstrapped curve's log discount factors
    if model.sheet("C & R").consts.get(parse_a1("A1")) != "CARRY & ROLL-DOWN – eğri sabit, TLREF = senaryo patikası (iş günü bileşik)":
        raise ValueError("C & R!A1 beklenen başlık değil")


def _tto_carry(model: Model) -> None:
    """The carry of the Carry & Roll sheet along a TLREF path of one's choice - today's TLREF kept flat, one of the
    three scenarios, the path the quotes imply or the bootstrapped curve (the default) - instead of the S1 scenario
    the workbook compounds.  The roll keeps the curve as it is, as the sheet does.  The S1 cells themselves stay as
    they are: the OIS sheet's own pricing reads them."""
    b = SheetBuilder(model, CARRY_SHEET)
    names = [n for n, _ in CARRY_PATHS]
    b.title("A1", "CARRY PATİKASI  ·  carry'de TLREF'in ufka kadar bileşiği (ve ufuktan önce ödenen kuponların getirisi) bu patikadan")
    b.set("A2", "Patika", bold=True)
    b.input("B2", CARRY_DEFAULT, align="center")
    b.dropdown("B2", names)
    b.set("C2", '=CHOOSE($F$7,"bugünkü TLREF, sabit","S1 senaryosu ("&OIS_MAIN!$P$3&")","S2 senaryosu ("&OIS_MAIN!$P$4&")",'
                '"S3 senaryosu ("&OIS_MAIN!$P$5&")","kotaların ima ettiği PPK patikası (MPC ima)","piyasa OIS eğrisinin (bootstrap) ima ettiği TLREF")',
          bold=True, color=NOTE_COLOR)
    b.set("A3", "Ufuk A", bold=True)
    b.set("B3", "=Motor!$C$134", fmt=DATE)
    b.set("C3", '="TLREF bileşik "&TEXT(Motor!$F$134*100,"0.00")&" % · ufuk sonu "&TEXT(Motor!$G$134*100,"0.00")&" %"', color=NOTE_COLOR)
    b.set("A4", "Ufuk B", bold=True)
    b.set("B4", "=Motor!$C$135", fmt=DATE)
    b.set("C4", '="TLREF bileşik "&TEXT(Motor!$F$135*100,"0.00")&" % · ufuk sonu "&TEXT(Motor!$G$135*100,"0.00")&" %"', color=NOTE_COLOR)
    # ---- helpers: the growth along the chosen path at the horizons, the tenors and the payment days
    b.head("A6", ["Ufuk", "Gün", "G (seçili patika)", "Ufuk sonu TLREF", None, "Patika no"])
    # which path, as a number (an unknown name: the default)
    b.set("F7", '=IF($B$2="Sabit TLREF",1,IF($B$2="S1",2,IF($B$2="S2",3,IF($B$2="S3",4,IF($B$2="MPC ima",5,6)))))', fmt="0")
    for k, (label, row) in enumerate((("A", 134), ("B", 135))):
        r = 7 + k
        b.set("A%d" % r, label, bold=True, align="center")
        b.set("B%d" % r, "=Motor!$D$%d" % row, fmt=INT0)
        b.set("C%d" % r, "=" + carry_growth("$B%d" % r, "$F$7"), fmt="0.000000000")
        # the TLREF the path stands at by the horizon: a scenario's after its last meeting, the curve's forward O/N
        tl = {n: 'INDEX(Motor!$%s$4:$%s$84,MATCH($B%d,Motor!$C$4:$C$84,1))' % (t, t, r) for n, (t, _) in CARRY_MEETING_PATHS.items()}
        boot = "(%s/%s-1)*365" % (carry_growth("($B%d+1)" % r, "6"), carry_growth("$B%d" % r, "6"))
        b.set("D%d" % r, "=CHOOSE($F$7,OIS_MAIN!$J$2,%s,%s,%s,%s,%s)" % (tl["S1"], tl["S2"], tl["S3"], tl["MPC ima"], boot), fmt="0.0000%")
    t0 = CARRY_TENOR_ROW
    b.head("A%d" % (t0 - 1), ["Vade (ay)", "T gün", "G(T) seçili"])
    for i, r in enumerate(range(t0, t0 + CARRY_ENGINE_A[1] - CARRY_ENGINE_A[0] + 1)):
        b.set("A%d" % r, "=Motor!$A$%d" % (CARRY_ENGINE_A[0] + i), fmt="0")
        b.set("B%d" % r, "=Motor!$E$%d" % (CARRY_ENGINE_A[0] + i), fmt=INT0)
        b.set("C%d" % r, "=" + carry_growth("$B%d" % r, "$F$7"), fmt="0.000000000")
    p0 = CARRY_PERIOD_ROW
    b.head("A%d" % (p0 - 1), ["Dönem", "Ödeme günü", "G(t) seçili"])
    for i, r in enumerate(range(p0, p0 + CARRY_PERIODS[1] - CARRY_PERIODS[0] + 1)):
        b.set("A%d" % r, "=Motor!$A$%d" % (CARRY_PERIODS[0] + i), fmt="0")
        b.set("B%d" % r, "=Motor!$F$%d" % (CARRY_PERIODS[0] + i), fmt=INT0)
        b.set("C%d" % r, "=" + carry_growth("$B%d" % r, "$F$7"), fmt="0.000000000")
    last_p = p0 + CARRY_PERIODS[1] - CARRY_PERIODS[0]
    b.note("A%d" % (last_p + 2), "Carry = sabit bacağın ufka kadar tahakkuku − TLREF'in ufka kadar bileşiği (iş günü, hafta sonu ve tatiller basit); "
                                 "ufuktan önce ödenen kupon ufka bu patikayla taşınır. Roll eğriyi bugünkü haliyle tutar (Carry & Roll sayfasının "
                                 "kendi hesabı). S1 – S3 ve MPC ima OIS sayfasındaki toplantı patikaları, Bootstrap piyasa eğrisinin iskonto "
                                 "faktörleri, Sabit TLREF bugünkü TLREF.")

    # ---- the Motor sheet's carry engine: from the S1 cells to the chosen path's
    m = SheetBuilder(model, "Motor")
    m.patch("E134", "=EK_CARRY!$C$7")
    m.patch("E135", "=EK_CARRY!$C$8")
    m.patch("G134", "=EK_CARRY!$D$7")
    m.patch("G135", "=EK_CARRY!$D$8")
    periods = "EK_CARRY!$C$%d:$C$%d" % (p0, last_p)
    for first, last in (CARRY_ENGINE_A, CARRY_ENGINE_B):
        for i, r in enumerate(range(first, last + 1)):
            m.patch("F%d" % r, "=EK_CARRY!$C$%d" % (t0 + i))
            m.patch("L%d" % r, "=" + formula_of(model, "Motor", "L%d" % r).replace("/$G$139:$G$178", "/" + periods))
    for i, r in enumerate(range(CARRY_PERIODS[0], CARRY_PERIODS[1] + 1)):
        for col, h_cell in (("J", "$E$134"), ("K", "$E$135")):
            text = formula_of(model, "Motor", "%s%d" % (col, r))
            m.patch("%s%d" % (col, r), "=" + text.replace("%s/G%d" % (h_cell, r), "%s/EK_CARRY!$C$%d" % (h_cell, p0 + i)))
    # the sheet says which path it is
    SheetBuilder(model, "C & R").patch("A1", '="CARRY & ROLL-DOWN – eğri sabit, TLREF = "&EK_CARRY!$C$2&" (iş günü bileşik)"')


# ---------------------------------------------------------------------------------------------- desk calendar days
DESK_DAYS = (89, 130)                     # Motor: the curve's nodes (1M ... 10Y)


def _desk_days_check(model: Model) -> None:
    """The curve's nodes count their days from Bloomberg's maturity of the generic OIS tickers (``=+R89``: maturity −
    USDTRY settlement) or, where there is no ticker, from the desk's calendar (``=B95-$B$88``)."""
    _need_sheets(model, "Motor")
    quoted = 0
    for r in range(DESK_DAYS[0], DESK_DAYS[1] + 1):
        text = _need_formula(model, "Motor", "C%d" % r).replace(" ", "")
        if text == "+R%d" % r:
            quoted += 1
        elif text != "B%d-$B$88" % r:
            raise ValueError("Motor!C%d beklenen gün formülü değil" % r)
        _need_formula(model, "Motor", "B%d" % r, "WORKDAY(EDATE(OIS_MAIN!$B$2,")
    if not quoted:
        raise ValueError("Motor!C89:C130 Bloomberg vadesini okumuyor")


def _tto_desk_days(model: Model) -> None:
    """Every node of the curve counts its days with the desk's calendar - spot + n months, the next business day
    (Motor!B) - as the nodes without a ticker already do.  On a weekday that is Bloomberg's maturity to the day; at a
    weekend Bloomberg counts the generic OIS tickers from Monday while the USDTRY settlement is Tuesday, and a tenor
    across a holiday (6M across Kurban Bayramı) shifted by days: a false "HATA" of the OIS check."""
    m = SheetBuilder(model, "Motor")
    for r in range(DESK_DAYS[0], DESK_DAYS[1] + 1):
        if formula_of(model, "Motor", "C%d" % r).replace(" ", "") == "+R%d" % r:
            m.patch("C%d" % r, "=B%d-$B$88" % r)


# ---------------------------------------------------------------------------------------------- Treasury auction
AUC_SHEET = "EK_IHALE"
AUC_DATE = "B2"                   # the auction's value date (a bond can be given its own)
AUC_FIRST = 5                     # the caption row of the first bond's block
AUC_BLOCK = 20                    # rows per bond
AUC_BONDS = 3
AUC_LINES = 5                     # bids per bond
AUC_CF = 30                       # cash flows a bond may still have for its yield (15 years of half-yearly coupons)
AUC_PART = "Asgari fiyatta · kısmi olabilir"
#: the Bloomberg answers and the yield's cash flows of a bond, on its block's information row (from column S)
AUC_INFO = ("sec", "valor", "name", "cpn_typ", "cpn", "mat", "freq", "infl", "acc", "prev", "next", "days", "idx", "kind",
            "cpn_n", "mat_d", "prev_d", "next_d", "freq_n", "acc_n", "ok", "w", "n", "fits", "g", "per", "idx_n",
            "listed", "fform", "freset", "frn")
#: what a priced row (a bid, the averages, the auction's prices) works out, from column S: the dirty price, Newton's
#: steps to the simple yield, the yields; a bid also says which of its three inputs it priced from
AUC_HELP = ("dirty", "s0", "s1", "s2", "s3", "s4", "s5", "simple", "comp", "how", "from_yield", "typed")
AUC_HELP_FIRST = 19               # column S


def auction_rows(k: int) -> Dict[str, Any]:
    """The rows of bond ``k``'s block (0, 1, 2)."""
    r = AUC_FIRST + k * AUC_BLOCK
    lines = list(range(r + 5, r + 5 + AUC_LINES))
    return {"caption": r, "info_head": r + 1, "info": r + 2, "state": r + 3, "line_head": r + 4, "lines": lines,
            "total": lines[-1] + 1, "result_head": r + 12, "min": r + 13, "avg": r + 14, "max": r + 15, "mine": r + 16,
            "summary": r + 17}


def auction_cols() -> Dict[str, Any]:
    """Helper columns: ``info`` (name -> letter), ``cf`` / ``ex`` (the cash flows and their exponents, first and
    last letter) and ``help`` (name -> letter) of a priced row."""
    info = {name: index_to_col(AUC_HELP_FIRST + i) for i, name in enumerate(AUC_INFO)}
    first_cf = AUC_HELP_FIRST + len(AUC_INFO)
    return {"info": info,
            "cf": (index_to_col(first_cf), index_to_col(first_cf + AUC_CF - 1)),
            "ex": (index_to_col(first_cf + AUC_CF), index_to_col(first_cf + 2 * AUC_CF - 1)),
            "help": {name: index_to_col(AUC_HELP_FIRST + i) for i, name in enumerate(AUC_HELP)},
            "last": index_to_col(first_cf + 2 * AUC_CF - 1)}


def _auction_check(model: Model) -> None:
    """The page prices the TRY workbook's government bonds (it reads nothing of its cells)."""
    _need_sheets(model, "DİBS RV")
    if AUC_SHEET in model.sheet_index:
        raise ValueError("%s sayfası zaten var" % AUC_SHEET)


def _date_of(x: str) -> str:
    """A date Bloomberg sends as text ("15.03.2028", "3.11.2026") or as a number, as a serial number ("" if none)."""
    return ('IF(ISNUMBER({x}),{x},IFERROR(DATE(VALUE(RIGHT({x},4)),VALUE(MID({x},FIND(".",{x})+1,FIND(".",{x},FIND(".",{x})+1)'
            '-FIND(".",{x})-1)),VALUE(LEFT({x},FIND(".",{x})-1))),""))').format(x=x)


def _tto_auction(model: Model) -> None:
    """The Treasury auction (``EK_IHALE``): the dirty price to bid for a clean price, a simple or a compound yield,
    and, once the auction is over, where each bid stands against the announced prices.

    Three bonds, five bids each.  The accrued interest is Bloomberg's at the auction's value date (``INT_ACC`` with
    ``SETTLE_DT``) - never worked out here: a value date on a coupon date, a coupon period of its own, a floater's
    current coupon are Bloomberg's to know.  The coupon dates around the value date and the days accrued come with
    it.  The yields follow the DİBS RV sheet ("BIST"): a fixed coupon bond's simple yield discounts the coupons at
    (1 + y/f) per coupon period (Newton's method from the coupon), compound = (1 + y/f)^f − 1; a bill or zero coupon
    bond: simple = (100/P − 1)·365/days, compound = (100/P)^(365/days) − 1.  CPI linkers are priced real (a TL amount
    with Bloomberg's index ratio), floaters (TLREF ones and FRNs) get their dirty price and their place in the auction, no yield."""
    b = SheetBuilder(model, AUC_SHEET)
    C = auction_cols()
    c, h = C["info"], C["help"]
    pct, px, dt = "0.000%", "0.000", DATE
    b.title("A1", "HAZİNE İHALESİ  ·  gönderilecek kirli fiyat ve ihale sonucu")
    b.set("A2", "İhale valörü", bold=True)
    b.input(AUC_DATE, None, fmt=dt, align="center")
    b.set("C2", '=IF(N($B$2)>0,"Birikmiş faiz her kâğıt için bu valörle (kâğıda kendi valörü yazılırsa onunla) Bloomberg\'den",'
                '"← Valörü yazın: gönderilecek kirli fiyat valördeki birikmiş faizle hesaplanır")', color=NOTE_COLOR)

    def text(x: str) -> str:
        return 'IFERROR(%s&"","")' % x

    for k in range(AUC_BONDS):
        R = auction_rows(k)
        i = R["info"]
        I = {name: "$%s$%d" % (col, i) for name, col in c.items()}
        cf = "$%s$%d:$%s$%d" % (C["cf"][0], i, C["cf"][1], i)
        ex = "$%s$%d:$%s$%d" % (C["ex"][0], i, C["ex"][1], i)
        lines = R["lines"]
        l1, l5 = lines[0], lines[-1]
        mn, av, mx, me, tot = ("$B$%d" % R["min"], "$B$%d" % R["avg"], "$B$%d" % R["max"], R["mine"], R["total"])
        kind, freq, acc, g = I["kind"], I["freq_n"], I["acc_n"], I["g"]

        # ---- the bond: what is typed, what Bloomberg says at the value date
        b.set("A%d" % R["caption"], '="KÂĞIT %d"&IF($C$%d="",""," · "&$C$%d&" · "&UPPER(TRIM($A$%d&"")))' % (k + 1, i, i, i),
              bold=True)
        b.head("A%d" % R["info_head"], ["ISIN (yaz)", "Valör (boşsa üstteki)", "Kâğıt", "Tür", "Kupon", "Vade", "Önceki kupon",
                                        "Sonraki kupon", "İşlemiş gün", "Dönem (gün)", "Birikmiş faiz (100)", "Kullanılan valör",
                                        "Endeks oranı (TÜFE)"])
        b.head("%s%d" % (c["sec"], R["info_head"]), list(AUC_INFO) + ["cf%d" % (j + 1) for j in range(AUC_CF)]
               + ["üs%d" % (j + 1) for j in range(AUC_CF)])
        b.input("A%d" % i, None, align="center", bold=True)
        b.input("B%d" % i, None, fmt=dt, align="center")
        f = {
            "sec": '=IF(TRIM($A{i}&"")="","",UPPER(TRIM($A{i}&""))&" ISIN")',
            "valor": '=IF({sec}="","",IF(N($B{i})>0,$B{i},IF(N($B$2)>0,$B$2,"")))',
            "name": '=IF({sec}="","",_xll.BDP({sec},"NAME"))',
            "cpn_typ": '=IF({sec}="","",_xll.BDP({sec},"CPN_TYP"))',
            "cpn": '=IF({sec}="","",_xll.BDP({sec},"CPN"))',
            "mat": '=IF({sec}="","",_xll.BDP({sec},"MATURITY"))',
            "freq": '=IF({sec}="","",_xll.BDP({sec},"CPN_FREQ"))',
            "infl": '=IF({sec}="","",_xll.BDP({sec},"INFLATION_LINKED_INDICATOR"))',
            "acc": '=IF(OR({sec}="",{valor}=""),"",_xll.BDP({sec},"INT_ACC","SETTLE_DT",{valor}))',
            "prev": '=IF(OR({sec}="",{valor}=""),"",_xll.BDP({sec},"PREV_CPN_DT","SETTLE_DT",{valor}))',
            "next": '=IF(OR({sec}="",{valor}=""),"",_xll.BDP({sec},"NXT_CPN_DT","SETTLE_DT",{valor}))',
            "days": '=IF(OR({sec}="",{valor}=""),"",_xll.BDP({sec},"DAYS_ACC","SETTLE_DT",{valor}))',
            "idx": '=IF(OR({sec}="",{valor}="",{kind}<>"E"),"",_xll.BDP({sec},"IDX_RATIO","SETTLE_DT",{valor}))',
            "kind": ('=IF(OR({sec}="",NOT(ISNUMBER({mat_d}))),"",IF(LEFT(UPPER(%s),1)="Y","E",IF(OR(ISNUMBER(SEARCH("FLOAT",%s)),'
                     'ISNUMBER(SEARCH("VARIABLE",%s)),ISNUMBER(SEARCH("FRN",%s))),"T",IF(OR(ISNUMBER(SEARCH("ZERO",%s)),'
                     'ISNUMBER(SEARCH("DISC",%s))),"B",IF(ISNUMBER({cpn_n}),"S","")))))')
                    % ((text("{infl}"),) + (text("{cpn_typ}"),) * 5),
            "cpn_n": '=IF(ISNUMBER({cpn}),{cpn},"")',
            "mat_d": "=" + _date_of("{mat}"),
            "prev_d": "=" + _date_of("{prev}"),
            "next_d": "=" + _date_of("{next}"),
            "freq_n": '=IF(ISNUMBER({freq}),IF({freq}>0,{freq},""),"")',
            "acc_n": '=IF(ISNUMBER({acc}),{acc},"")',
            "ok": ('=AND(ISNUMBER({valor}),ISNUMBER({mat_d}),N({mat_d})>N({valor}),{kind}<>"",ISNUMBER({acc_n}),'
                   'IF({kind}="B",TRUE,AND(ISNUMBER({prev_d}),ISNUMBER({next_d}),N({next_d})>N({prev_d}),ISNUMBER({freq_n}))))'),
            "w": '=IF(AND({ok},OR({kind}="S",{kind}="E")),({next_d}-{valor})/({next_d}-{prev_d}),"")',
            # the coupons left: whole periods of the calendar (364 / frequency days, DİBS RV's "takvim 182g") from the next
            # coupon to the maturity - a long or short current period does not change their number
            "n": '=IF(AND({ok},OR({kind}="S",{kind}="E")),ROUND(({mat_d}-{next_d})/ROUND(364/{freq_n},0),0)+1,"")',
            "fits": "=AND(ISNUMBER({n}),N({n})<=%d)" % AUC_CF,
            "g": '=IF({ok},{mat_d}-{valor},"")',
            "per": '=IF(AND({ok},OR({kind}="S",{kind}="E")),{cpn_n}/{freq_n},"")',
            "idx_n": '=IF(AND({kind}="E",ISNUMBER({idx})),{idx},"")',
            # a floater: a TLREF one or an FRN - Tüm Kâğıtlar's kind for it, else what Bloomberg says
            "listed": '=IF({sec}="","",%s)' % universe_kind("$A{i}"),
            "fform": '=IF(AND({kind}="T",{listed}=""),_xll.BDP({sec},"FLOATER_FORMULA"),"")',
            "freset": '=IF(AND({kind}="T",{listed}=""),_xll.BDP({sec},"RESET_IDX"),"")',
            "frn": "=" + frn_test("{listed}", "{kind}", "{fform}", "{freset}"),
        }
        for name, formula in f.items():
            b.set("%s%d" % (c[name], i), formula.format(i=i, **I), fmt=dt if name.endswith("_d") else None)
        first_cf = AUC_HELP_FIRST + len(AUC_INFO)
        for j in range(1, AUC_CF + 1):
            b.set("%s%d" % (index_to_col(first_cf + j - 1), i),
                  '=IF(AND({fits},{j}<=N({n})),{per}+IF({j}=N({n}),100,0),0)'.format(j=j, **I))
            b.set("%s%d" % (index_to_col(first_cf + AUC_CF + j - 1), i),
                  '=IF(AND({fits},{j}<=N({n})),{w}+{j}-1,0)'.format(j=j, **I))
        shown = [
            ("C", '=IF({sec}="","",IF(ISNUMBER({mat_d}),TEXT({mat_d},"dd.mm.yy")&IF({kind}="T",IF({frn}," FRN"," TLREF"),IF({kind}="E"," TÜFE",'
                  'IF({kind}="B"," Bono",""))),%s))' % text("{name}"), None),
            ("D", '=IF({kind}="S","Sabit kuponlu",IF({kind}="T",IF({frn},"FRN","TLREF"),IF({kind}="E","TÜFE",IF({kind}="B","Bono / kuponsuz",""))))',
             None),
            ("E", '=IF(AND(ISNUMBER({cpn_n}),{kind}<>"B"),{cpn_n}/100,"")', pct),
            ("F", '=IF(ISNUMBER({mat_d}),{mat_d},"")', dt),
            ("G", '=IF(ISNUMBER({prev_d}),{prev_d},"")', dt),
            ("H", '=IF(ISNUMBER({next_d}),{next_d},"")', dt),
            ("I", '=IF(ISNUMBER({days}),{days},"")', INT0),
            ("J", '=IF(AND(ISNUMBER({prev_d}),ISNUMBER({next_d})),{next_d}-{prev_d},"")', INT0),
            ("K", '=IF(ISNUMBER({acc_n}),{acc_n},"")', "0.000000"),
            ("L", '=IF(ISNUMBER({valor}),{valor},"")', dt),
            ("M", '=IF(ISNUMBER({idx_n}),{idx_n},"")', "0.000000"),
        ]
        for col, formula, fmt in shown:
            b.set("%s%d" % (col, i), formula.format(**I), fmt=fmt, bold=col in ("C", "K"), align="center" if fmt == dt else None)
        b.set("A%d" % R["state"],
              ('=IF({sec}="","← ISIN yazın",IF({valor}="","← İhale valörünü (üstte) ya da bu kâğıdın valörünü yazın",'
               'IF(ISERROR({name}),"Bloomberg yanıtı bekleniyor",IF(LEFT({name}&"",4)="#N/A","Bloomberg: "&{name},'
               'IF(NOT(ISNUMBER({acc_n})),"Bloomberg\'den valördeki birikmiş faiz bekleniyor",'
               'IF(NOT({ok}),IF(N({mat_d})>0,IF(N({mat_d})<=N({valor}),"Kâğıt valörde ya da daha önce itfa oluyor",'
               '"Bloomberg\'den kupon tarihleri bekleniyor"),"Bloomberg\'den vade bekleniyor"),'
               'IF({kind}="T",IF({frn},"FRN","TLREF")&": kirli fiyat ve ihaledeki yer; getiri hesaplanmaz",'
               'IF(AND(OR({kind}="S",{kind}="E"),NOT({fits})),"Kalan kupon %d\'dan çok: getiri hesaplanmaz",'
               'IF({kind}="E","TÜFE: reel fiyat ve reel getiri; tutar Bloomberg\'in valördeki endeks oranıyla",'
               '"Birikmiş faiz, kupon tarihleri ve işlemiş gün Bloomberg\'den, valöre göre")))))))))') .format(**I) % AUC_CF,
              color=NOTE_COLOR)

        # ---- the bids
        b.head("A%d" % R["line_head"], ["#", "Nominal", "Temiz (yaz)", "Basit % (yaz)", "Bileşik % (yaz)", "Girdi", "Temiz",
                                        "Basit %", "Bileşik %", "Kirli · gönderilecek", "Tutar (TL)", "Sonuç", "Kirli − ihale ort.",
                                        "Basit − ihale ort. (bp)", "Min–maks'ta yer", "Gerçekleşen nom. (yaz)", "Gerçekleşen nominal"])
        b.head("%s%d" % (h["dirty"], R["line_head"]), list(AUC_HELP))

        def priced(r: int, line: bool) -> None:
            """The yields of the dirty price in column ``dirty`` of row ``r`` (a bid also from a typed yield)."""
            H = {name: "%s%d" % (col, r) for name, col in h.items()}
            ref = dict(I, cf=cf, ex=ex, **H)
            for s in range(6):
                if s == 0:
                    step = ('=IF(OR(N({dirty})<=0,AND({kind}<>"S",{kind}<>"E"),NOT({fits})),"",IF(N({cpn_n})>0,{cpn_n}/100,0.3))')
                else:
                    step = ('=IF({prev}="","",IFERROR({prev}-(SUMPRODUCT({cf},(1+{prev}/{freq_n})^(-{ex}))-{dirty})/'
                            '(-SUMPRODUCT({cf},{ex},(1+{prev}/{freq_n})^(-{ex}-1))/{freq_n}),""))').replace("{prev}", H["s%d" % (s - 1)])
                b.set(H["s%d" % s], step.format(**ref))
            solved = ('IF(N({dirty})<=0,"",IF({kind}="B",IF(N({g})>0,(100/{dirty}-1)*365/{g},""),IF(ISNUMBER({s5}),'
                      'IF(ABS(SUMPRODUCT({cf},(1+{s5}/{freq_n})^(-{ex}))-{dirty})<0.000001,{s5},""),"")))')
            if line:
                simple = ('=IF(OR({how}="B",{how}="C"),IF(AND(N({dirty})>0,ISNUMBER({from_yield})),{from_yield},""),%s)' % solved)
            else:
                simple = "=" + solved
            b.set(H["simple"], simple.format(**ref))
            b.set(H["comp"], ('=IF(NOT(ISNUMBER({simple})),"",IF({kind}="B",(1+{simple}*{g}/365)^(365/{g})-1,'
                              '(1+{simple}/{freq_n})^{freq_n}-1))').format(**ref))

        for n_line, r in enumerate(lines, 1):
            H = {name: "%s%d" % (col, r) for name, col in h.items()}
            ref = dict(I, cf=cf, ex=ex, r=r, mn=mn, av=av, mx=mx, avs="$D$%d" % R["avg"], part=AUC_PART, **H)
            b.set("A%d" % r, n_line, align="center", color=NOTE_COLOR)
            b.input("B%d" % r, None, fmt=INT0)
            b.input("C%d" % r, None, fmt=px)
            b.input("D%d" % r, None, fmt=pct)
            b.input("E%d" % r, None, fmt=pct)
            b.input("P%d" % r, None, fmt=INT0)
            b.set(H["how"], '=IF(ISNUMBER($C{r}),"T",IF(ISNUMBER($D{r}),"B",IF(ISNUMBER($E{r}),"C","")))'.format(**ref))
            b.set(H["typed"], "=ISNUMBER($C{r})+ISNUMBER($D{r})+ISNUMBER($E{r})".format(**ref))
            b.set(H["from_yield"], ('=IFERROR(IF({how}="B",$D{r},IF({how}="C",IF({kind}="B",IF(N({g})>0,((1+$E{r})^({g}/365)-1)*365/{g},""),'
                                    'IF(OR({kind}="S",{kind}="E"),{freq_n}*((1+$E{r})^(1/{freq_n})-1),"")),"")),"")').format(**ref))
            b.set(H["dirty"], ('=IF(NOT({ok}),"",IFERROR(IF({how}="T",$C{r}+{acc_n},IF(AND(OR({how}="B",{how}="C"),ISNUMBER({from_yield})),'
                               'IF({kind}="B",100/(1+{from_yield}*{g}/365),IF(AND(OR({kind}="S",{kind}="E"),{fits}),'
                               'SUMPRODUCT({cf},(1+{from_yield}/{freq_n})^(-{ex})),"")),"")),""))').format(**ref))
            priced(r, True)
            row = [
                ("F", '=IF({how}="","",IF(AND({how}<>"T",{kind}="T"),IF({frn},"FRN","TLREF")&": temiz fiyat yazın",IF({how}="T","Temiz",IF({how}="B","Basit",'
                      '"Bileşik"))&IF({typed}>1," · diğerine bakılmadı","")))', None, False),
                ("G", '=IF(N({dirty})<=0,"",IF({how}="T",$C{r},{dirty}-{acc_n}))', px, False),
                ("H", '=IF(ISNUMBER({simple}),{simple},"")', pct, False),
                ("I", '=IF(ISNUMBER({comp}),{comp},"")', pct, False),
                ("J", '=IF(N({dirty})<=0,"",ROUND({dirty},3))', px, True),
                ("K", '=IF(AND(N($B{r})>0,ISNUMBER($J{r})),IF({kind}="E",IF(ISNUMBER({idx_n}),$B{r}*$J{r}/100*{idx_n},""),'
                      '$B{r}*$J{r}/100),"")', NUM2, False),
                ("L", '=IF(OR(NOT(ISNUMBER($J{r})),N({mn})<=0),"",IF($J{r}>{mn}+0.0005,"Gerçekleşti",IF($J{r}>={mn}-0.0005,"{part}",'
                      '"Gerçekleşmedi")))', None, True),
                ("M", '=IF(AND(ISNUMBER($J{r}),N({av})>0),$J{r}-{av},"")', "+0.000;-0.000;0.000", False),
                ("N", '=IF(AND(ISNUMBER($H{r}),ISNUMBER({avs})),($H{r}-{avs})*10000,"")', "+0.0;-0.0;0.0", False),
                ("O", '=IF(AND(ISNUMBER($J{r}),N({mn})>0,N({mx})>N({mn})),($J{r}-{mn})/({mx}-{mn}),"")', "0%", False),
                ("Q", '=IF($L{r}="","",IF(ISNUMBER($P{r}),$P{r},IF($L{r}="Gerçekleşmedi",0,N($B{r}))))', INT0, False),
            ]
            for col, formula, fmt, bold in row:
                b.set("%s%d" % (col, r), formula.format(**ref), fmt=fmt, bold=bold)

        # ---- all the bids together: the nominal, the average dirty price (weighted by the nominal) and its yields
        H = {name: "%s%d" % (col, tot) for name, col in h.items()}
        ref = dict(I, l1=l1, l5=l5, t=tot, **H)
        b.set("A%d" % tot, "Toplam / ort.", bold=True)
        b.set("B%d" % tot, '=IF(COUNT(B{l1}:B{l5})=0,"",SUM(B{l1}:B{l5}))'.format(**ref), fmt=INT0, bold=True)
        b.set(H["dirty"], '=IFERROR(SUMPRODUCT(B{l1}:B{l5},J{l1}:J{l5})/SUMPRODUCT(B{l1}:B{l5}*ISNUMBER(J{l1}:J{l5})),"")'.format(**ref))
        priced(tot, False)
        b.set("G%d" % tot, '=IF(N({dirty})<=0,"",{dirty}-{acc_n})'.format(**ref), fmt=px, bold=True)
        b.set("H%d" % tot, '=IF(ISNUMBER({simple}),{simple},"")'.format(**ref), fmt=pct, bold=True)
        b.set("I%d" % tot, '=IF(ISNUMBER({comp}),{comp},"")'.format(**ref), fmt=pct, bold=True)
        b.set("J%d" % tot, '=IF(N({dirty})<=0,"",{dirty})'.format(**ref), fmt=px, bold=True)
        b.set("K%d" % tot, '=IF(COUNT(K{l1}:K{l5})=0,"",SUM(K{l1}:K{l5}))'.format(**ref), fmt=NUM2, bold=True)
        b.set("Q%d" % tot, '=IF(COUNT(Q{l1}:Q{l5})=0,"",SUM(Q{l1}:Q{l5}))'.format(**ref), fmt=INT0, bold=True)

        # ---- the auction's result: the announced prices (dirty, as bid) and the average of what was won
        b.head("A%d" % R["result_head"], ["İhale sonucu", "Kirli (açıklanan, yaz)", "Temiz", "Basit %", "Bileşik %", "Kirli − ihale ort.",
                                          "Basit − ihale ort. (bp)", "Gerçekleşen nominal", "Tutar (TL)"])
        for r, label in ((R["min"], "Asgari fiyat"), (R["avg"], "Ortalama fiyat"), (R["max"], "Azami fiyat"), (me, "Benim · gerçekleşen ort.")):
            H = {name: "%s%d" % (col, r) for name, col in h.items()}
            ref = dict(I, r=r, l1=l1, l5=l5, t=tot, av=R["avg"], **H)
            b.set("A%d" % r, label, bold=True)
            if r == me:
                b.set("B%d" % r, '=IF(N($Q${t})>0,SUMPRODUCT(Q{l1}:Q{l5},J{l1}:J{l5})/$Q${t},"")'.format(**ref), fmt=px, bold=True)
                b.set(H["dirty"], '=IF(ISNUMBER($B{r}),$B{r},"")'.format(**ref))
            else:
                b.input("B%d" % r, None, fmt=px)
                b.set(H["dirty"], '=IF(AND(N($B{r})>0,{ok}),$B{r},"")'.format(**ref))
            priced(r, False)
            b.set("C%d" % r, '=IF(N({dirty})<=0,"",{dirty}-{acc_n})'.format(**ref), fmt=px)
            b.set("D%d" % r, '=IF(ISNUMBER({simple}),{simple},"")'.format(**ref), fmt=pct)
            b.set("E%d" % r, '=IF(ISNUMBER({comp}),{comp},"")'.format(**ref), fmt=pct)
            if r == me:
                b.set("F%d" % r, '=IF(AND(ISNUMBER($B{r}),N($B${av})>0),$B{r}-$B${av},"")'.format(**ref), fmt="+0.000;-0.000;0.000",
                      bold=True)
                b.set("G%d" % r, '=IF(AND(ISNUMBER($D{r}),ISNUMBER($D${av})),($D{r}-$D${av})*10000,"")'.format(**ref),
                      fmt="+0.0;-0.0;0.0", bold=True)
                b.set("H%d" % r, '=IF(N($Q${t})>0,$Q${t},"")'.format(**ref), fmt=INT0)
                b.set("I%d" % r, ('=IF(ISNUMBER($B{r}),IF({kind}="E",IF(ISNUMBER({idx_n}),$Q${t}*$B{r}/100*{idx_n},""),'
                                  '$Q${t}*$B{r}/100),"")').format(**ref), fmt=NUM2)
        ref = dict(I, l1=l1, l5=l5, mn=mn, me=me, part=AUC_PART)
        b.set("A%d" % R["summary"],
              ('=IF(N({mn})<=0,"İhale bitince açıklanan asgari, ortalama ve azami kirli fiyatı yazın: her teklifin sonucu ve yeri, '
               'gerçekleşen ortalamanız ve getirisi çıkar.",COUNTIF($L${l1}:$L${l5},"Gerçekleşti")&" teklif gerçekleşti, "'
               '&COUNTIF($L${l1}:$L${l5},"{part}")&" teklif asgari fiyatta (kısmi olabilir), "&COUNTIF($L${l1}:$L${l5},"Gerçekleşmedi")'
               '&" teklif gerçekleşmedi."&IF(AND(ISNUMBER($F${me}),ISNUMBER($G${me}))," Gerçekleşen ortalamanız ihale ortalamasından "'
               '&TEXT(ABS($F${me}),"0.000")&IF($F${me}>=0," yüksek"," düşük")&" (basit getiride "&TEXT($G${me},"+0.0;-0.0;0.0")&" bp).",""))')
              .format(**ref), color=NOTE_COLOR)
    b.sheet.freeze = [0, 1]


#: book -> (name, precondition, builder) of each addition
# ---------------------------------------------------------------------------------------------- DV01 risk: no position
#: the position cells of the DV01 risk sheet: the bucket DV01s (TL/bp) and the paste area beside them (Onshore /
#: TLREF).  The file keeps the desk's positions of the day it was saved - nobody's position today - so the sheet
#: opens at zero; each user's own (personal) position is typed or pasted over it and kept as before.
DV01_POSITIONS = ("C6:C25", "X33:Y52")


def _dv01_zero_check(model: Model) -> None:
    _need_sheets(model, "DV01_RISK")
    sh = model.sheet("DV01_RISK")
    for addr, text in (("B5", "Bucket"), ("C5", "DV01 (TL/bp)"), ("X32", "Onshore"), ("Y32", "TLREF")):
        if sh.consts.get(parse_a1(addr)) != text:
            raise ValueError("DV01_RISK!%s beklenen başlık değil (%s yok)" % (addr, text))


def _tto_dv01_zero(model: Model) -> None:
    sh = model.sheet("DV01_RISK")
    for rng in DV01_POSITIONS:
        r1, c1, r2, c2 = parse_range(rng)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                rc = r * COLS + c
                if rc not in sh.fml:                        # a formula would stay a formula (there is none today)
                    sh.consts[rc] = 0.0


# ---------------------------------------------------------------------------------------------- VİOP matrix DV01s
#: the matrix's driver rows (VIOP!K97:X108) end with two DV01s per contract, per 1 mn USD: "DV01 TRY" - the TRY
#: rate's bp, in TL - and "DV01 USD" - the USD rate's bp, but also in TL.  The desk reads them in their own
#: currency: the TRY one in TL and in USD, the USD one in USD.  Nothing in the workbook reads these two rows.
VIOP_DV01_COLS = [index_to_col(c) for c in range(13, 25)]          # M:X, the twelve contracts (L is the spot)


def _viop_dv01_check(model: Model) -> None:
    _need_sheets(model, "VIOP")
    sh = model.sheet("VIOP")
    if (sh.consts.get(parse_a1("K107")), sh.consts.get(parse_a1("K108"))) != ("DV01 TRY", "DV01 USD"):
        raise ValueError("VIOP!K107:K108 beklenen DV01 satırları değil")
    for col in VIOP_DV01_COLS:
        _need_formula(model, "VIOP", "%s107" % col, "/(1+$%s$101*$%s$98/360)" % (col, col))
        _need_formula(model, "VIOP", "%s108" % col, "-100*(($%s$99+$%s$100)/2)" % (col, col))
    taken = [a for a in ["K109"] + ["%s109" % c for c in VIOP_DV01_COLS]
             if parse_a1(a) in sh.consts or parse_a1(a) in sh.fml]
    if taken:
        raise ValueError("VIOP 109. satır boş değil: %s" % ", ".join(taken))


def _tto_viop_dv01(model: Model) -> None:
    b = SheetBuilder(model, "VIOP")
    b.set("K107", "DV01 TRY (TL)", like="K107")
    b.set("K108", "DV01 TRY (USD)", like="K108")
    b.set("K109", "DV01 USD (USD)", like="K108")
    for col in VIOP_DV01_COLS:
        # the TL of the TRY bp at the contract's own price (a value at maturity, so at that maturity's forward) ...
        b.set("%s108" % col, '=IFERROR(%s107/((%s99+%s100)/2),"")' % (col, col, col), like="%s108" % col)
        # ... and the USD bp in USD: the TL formula of the workbook without the price it was multiplied by
        b.set("%s109" % col, '=IFERROR(-100*(%s$98/360)/(1+%s$101*%s$98/360),"")' % (col, col, col), like="%s108" % col)


# ---------------------------------------------------------------------------------------------- empty by default
#: inputs the file brings filled in with the desk's choices of the day it was saved; every user starts with them
#: empty: the scenario step per meeting (S1 / S2 / S3) of the PPK ima tab - a blank step follows the scenario base
#: (OIS_MAIN!B3 / D3) -, the VİOP target table (also on the desk page), the manual USDTRY spot of the VİOP sheet
#: (shared: blank = Bloomberg's spot; the file's 49,997 / 49,9975 replaced Bloomberg's spot on every page for the
#: whole desk) and the hand calculators' values of that day: the trade of the TM OIS page, the day counter, the XAU leg's
#: dates and swap and the bond carry calculator of the Forward page, the two dates of the OIS page's date-to-date rate,
#: the TRY rates of the VİOP page's three Interest 2 SP calculators, a saved switch of DİBS RV and the own asks of the
#: Eurobond page.  What a user types stays theirs, what the desk types stays the desk's.
EMPTY_BY_DEFAULT = (("OIS_MAIN", "U10:W89"), ("VIOP", "L331:P338"), ("VIOP", "AA9:AA10"),
                    ("TM_OIS", "A10:C12"), ("Forward", "E20"), ("Forward", "E22"), ("Forward", "C59:C60"), ("Forward", "C63"),
                    ("Forward", "E61"), ("Forward", "E67"), ("Forward", "V56:V58"), ("Forward", "V61:V62"),
                    ("OIS_MAIN", "B122:B123"), ("VIOP", "M37"), ("VIOP", "P37"), ("VIOP", "S37"), ("DİBS RV", "A64:C64"),
                    ("Bulk Bond", "D3:D5"))
#: the same for the USD workbook: the FOMC scenario steps of that day (base / hawkish / dovish per meeting; a blank step
#: moves nothing)
EMPTY_BY_DEFAULT_USD = (("SOFR_FOMC", "R74:T83"),)
#: the cells the first clean-up of stored copies (``migrated.empty_defaults``) went through: every shared value kept of
#: them was a copy of the file's steps a calendar change had carried along, and went
EMPTY_FIRST = (("OIS_MAIN", "U10:W89"), ("VIOP", "L331:P338"))
#: the name of that addition (left out where the file does not fit it: the cells keep the file's values)
EMPTY_NAME = "Boş başlayan girdiler"
#: where the additions note the file's own values of the input cells they empty or give a formula default
#: ({"VIOP!AA9": 49.997, ...}, in the model's ``meta``): a shared value stored of one of them is dropped once, only when
#: it is that value (a copy, nobody's choice)
FILE_VALUES = "empty_file_values"
#: what each of those cells must be next to, for the addition to fit the file
_EMPTY_CAPTIONS = (("VIOP", "K330", "Target"), ("VIOP", "L330", "Yakın"), ("VIOP", "P330", "Hedef değer"),
                   ("VIOP", "Z8", "Manuel SP"), ("VIOP", "Z9", "Bid"), ("VIOP", "Z10", "Ask"),
                   ("TM_OIS", "A9", "Dönem başı"), ("TM_OIS", "C9", "Nominal (TL)"), ("Forward", "D20", "Start"),
                   ("Forward", "D22", "End"), ("Forward", "B59", "Start"), ("Forward", "B60", "End"), ("Forward", "B63", "Swap"),
                   ("Forward", "D61", "Customer Forward"), ("Forward", "D67", "Customer Start"), ("Forward", "U56", "ISIN"),
                   ("Forward", "U58", "Settlement"), ("Forward", "U61", "Carry"), ("Forward", "U62", "End Date"),
                   ("OIS_MAIN", "A122", "Başlangıç tarihi"), ("OIS_MAIN", "A123", "Bitiş tarihi"), ("VIOP", "L37", "TRY"),
                   ("VIOP", "O37", "TRY"), ("VIOP", "R37", "TRY"), ("DİBS RV", "A63", "Sat (ISIN)"),
                   ("DİBS RV", "C63", "Sat nominal (mn)"), ("Bulk Bond", "D2", "Ask"))


def empty_default_refs(ranges: Sequence[Tuple[str, str]] = EMPTY_BY_DEFAULT) -> List[str]:
    """The cells of ``EMPTY_BY_DEFAULT`` (or of other ``(sheet, range)`` pairs) as references ("OIS_MAIN!U10", ...)."""
    out = []
    for sheet, rng in ranges:
        r1, c1, r2, c2 = parse_range(rng)
        out += ["%s!%s%d" % (sheet, index_to_col(c), r) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
    return out


def _need_captions(model: Model, captions: Sequence[Tuple[str, str, str]]) -> None:
    for sheet, addr, text in captions:
        if model.sheet(sheet).consts.get(parse_a1(addr)) != text:
            raise ValueError("%s!%s beklenen başlık değil (%s yok)" % (sheet, addr, text))


def _empty_check(model: Model) -> None:
    _need_sheets(model, *sorted({sheet for sheet, _ in EMPTY_BY_DEFAULT}))
    _need_captions(model, _EMPTY_CAPTIONS)
    for col, step in (("X", "U"), ("Y", "V"), ("Z", "W")):           # a blank step: the scenario base decides
        _need_formula(model, "OIS_MAIN", "%s10" % col, 'IF(%s10<>"",%s10' % (step, step))
    for addr, cell in (("L99", "$AA$9"), ("L100", "$AA$10")):          # a blank manual spot: Bloomberg's
        _need_formula(model, "VIOP", addr, "IF(N(%s)>0,%s," % (cell, cell))


def _empty(model: Model, ranges: Sequence[Tuple[str, str]], first: Sequence[Tuple[str, str]] = ()) -> None:
    """Take the constants out of the cells of ``ranges`` (a formula stays) and note what the file held there
    (``FILE_VALUES``; not for the cells of ``first``, whose stored copies went all at once, long ago)."""
    kept = model.meta.setdefault(FILE_VALUES, {})
    skip = set(empty_default_refs(first))
    for sheet, rng in ranges:
        sh = model.sheet(sheet)
        r1, c1, r2, c2 = parse_range(rng)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                rc = r * COLS + c
                if rc not in sh.fml:
                    was = sh.consts.pop(rc, None)
                    ref = "%s!%s%d" % (sheet, index_to_col(c), r)
                    if was is not None and ref not in skip:
                        kept[ref] = was


def _tto_empty(model: Model) -> None:
    _empty(model, EMPTY_BY_DEFAULT, EMPTY_FIRST)


def _usd_empty_check(model: Model) -> None:
    _need_sheets(model, "SOFR_FOMC")
    _need_captions(model, (("SOFR_FOMC", "R73", "Baz adım (bp)"), ("SOFR_FOMC", "S73", "Şahin adım (bp)"),
                           ("SOFR_FOMC", "T73", "Güvercin adım (bp)")))
    _need_formula(model, "SOFR_FOMC", "U74", "R$74:R74")                  # the base path sums the steps: blank = no move


def _usd_empty(model: Model) -> None:
    _empty(model, EMPTY_BY_DEFAULT_USD)


# ---------------------------------------------------------------------------------------------- market defaults
#: hand calculators whose spot, dates and rates the file brings from the day it was saved start from the market instead
#: (a formula default: what a user types over it is theirs, Delete brings the market back), as the Forward page's own
#: calculators do: the Calculators sheet's top band (the first four calculators read its dates and spot, the swap points
#: beside it its forward) and the XAU leg of the Forward sheet's customer gold forward (its spots, and the USD / TRY rates
#: of the customer's forward date).  The TRY rate is the offshore (ICAP, FX swap implied) curve's mid - what an FX forward
#: is priced on; the USD rate the Forward sheet's USD OIS curve.
MARKET_NAME = "Hesaplayıcıların piyasa varsayılanları"


def _usd_rate(days: str) -> str:
    """The USD OIS mid (%) ``days`` after the USDTRY spot date: the Forward sheet's own curve, as it reads it."""
    xs, ys, n = FR_MAJOR["USDTRY"]
    return lin(days, xs, ys, n)


def market_defaults(gold: bool = True) -> Dict[str, str]:
    """{cell: formula} of the market defaults (``gold``: with the XAUUSD spot, which the gold sheet gives)."""
    spot_date = FR_SPOT["USDTRY"]
    g = "(Calculators!$AA$4-%s)" % spot_date
    fwd = ('=IFERROR(Calculators!$AA$9*(1+(%s)/100*%s/360)/(1+(%s)/100*%s/360),"")'
           % (fr_rate("Offshore", g), g, _usd_rate(g), g))
    out = {"Calculators!AA3": "=" + spot_date, "Calculators!AA4": "=Forward!$D$2", "Calculators!AA9": "=Forward!$F$2",
           "Calculators!AA10": fwd, "Forward!E59": "=Forward!$F$2",
           # the rates of the customer's forward date (none before a date is typed: no rate of a day before the spot)
           "Forward!E63": '=IF(N(Forward!$C$65)>0,IFERROR((%s)/100,""),"")' % _usd_rate("Forward!$C$65"),
           "Forward!E64": '=IF(N(Forward!$C$65)>0,IFERROR((%s)/100,""),"")' % fr_rate("Offshore", "Forward!$C$65")}
    if gold:
        out["Forward!C61"] = '=IF(ISNUMBER(%s!$D$6),%s!$D$6,"")' % (XAU_SHEET, XAU_SHEET)
    return out


def _market_check(model: Model) -> None:
    _need_sheets(model, "Calculators", "Forward")
    _need_captions(model, (("Calculators", "Z3", "Start Date"), ("Calculators", "Z4", "End Date"), ("Calculators", "Z9", "Spot"),
                           ("Calculators", "Z10", "Forward"), ("Forward", "B61", "Spot"), ("Forward", "D59", "USDTRY Spot"),
                           ("Forward", "D63", "USD Faiz"), ("Forward", "D64", "TRY Faiz")))
    for addr, text in (("C3", "AA3"), ("C4", "AA4"), ("C6", "AA9"), ("AA11", "AA10-AA9")):
        _need_formula(model, "Calculators", addr, text)
    _need_formula(model, "Forward", "E62", "$E$59*(1+$E$64/360*$C$65)/(1+$E$63/360*$C$65)")
    _need_formula(model, "Forward", "C65", "E61-I2")
    _need_formula(model, "Forward", "C62", "C61+C63/100")
    for ref in market_defaults(XAU_SHEET in model.sheet_index):
        sheet, addr = ref.split("!")
        if parse_a1(addr) in model.sheet(sheet).fml:
            raise ValueError("%s zaten bir formül" % ref)


def _tto_market(model: Model) -> None:
    kept = model.meta.setdefault(FILE_VALUES, {})
    for ref, formula in market_defaults(XAU_SHEET in model.sheet_index).items():   # (no gold sheet: the spot stays typed)
        sheet, addr = ref.split("!")
        was = model.sheet(sheet).consts.get(parse_a1(addr))
        if was is not None:
            kept[ref] = was
        SheetBuilder(model, sheet).patch(addr, formula)


# ---------------------------------------------------------------------------------------------- one OIS spread
#: the desk's OIS spread assumption, typed once: MASA!I60 (bp; 26 formulas of the desk sheet and the forward quote
#: matrix's general spread read it).  The workbook typed it three more times, in other units: the Forward sheet's
#: "TRY OIS w/Spread" (P58, %-points), the shift of the OIS mid at the value date (O27, a fraction) and the OIS page's
#: date-to-date rate (F122, a fraction).  These follow I60 now (a formula default each: typed over, a user's own).
OIS_SPREAD = "MASA!$I$60"
OIS_SPREAD_CELLS = (("Forward", "P58", "=%s/100" % OIS_SPREAD), ("Forward", "O27", "=%s/10000" % OIS_SPREAD),
                    ("OIS_MAIN", "F122", "=%s/10000" % OIS_SPREAD))
OIS_SPREAD_NAME = "Tek OIS spread'i"


def _ois_spread_check(model: Model) -> None:
    _need_sheets(model, "MASA", "Forward", "OIS_MAIN")
    _need_captions(model, (("MASA", "H60", "Spread (bp)"), ("Forward", "O58", "Spread"), ("OIS_MAIN", "E122", "Spread")))
    if type(model.sheet("MASA").consts.get(parse_a1("I60"))) is not float:
        raise ValueError("MASA!I60 bir sayı değil")
    _need_formula(model, "Forward", "P27", "P24+O27")                 # the shift of the OIS mid
    _need_formula(model, "Forward", "P59", "$P$58")                   # TRY OIS w/Spread
    _need_formula(model, "OIS_MAIN", "F125", "$F$122")                # the date-to-date rate with the spread
    for sheet, addr, _ in OIS_SPREAD_CELLS:
        if parse_a1(addr) in model.sheet(sheet).fml:
            raise ValueError("%s!%s zaten bir formül" % (sheet, addr))


def _tto_ois_spread(model: Model) -> None:
    kept = model.meta.setdefault(FILE_VALUES, {})
    for sheet, addr, formula in OIS_SPREAD_CELLS:
        was = model.sheet(sheet).consts.get(parse_a1(addr))
        if was is not None:
            kept["%s!%s" % (sheet, addr)] = was
        SheetBuilder(model, sheet).patch(addr, formula)


# ---------------------------------------------------------------------------------------------- VİOP contracts roll
#: the VİOP futures of the VİOP page (the desk's: shared inputs) as Bloomberg names them - USDTRY monthly (contract 1-12,
#: "A1X6 Curncy"), gold TRY and gold USD (even months: "XLZ6 Comdty", "XLTZ6 Comdty"): (cells, root, yellow key, months
#: apart).  They roll by themselves: a formula default builds the codes of the contracts trading today; what the desk
#: types over one of them still wins (Delete: back to the roll).
VIOP_ROLLS = (("L1:W1", "A1", "Curncy", 1), ("M45:O45", "XL", "Comdty", 2), ("M60:O60", "XLT", "Comdty", 2))
VIOP_ROLL_NAME = "VİOP kontratları"
VIOP_MONTHS = "FGHJKMNQUVXZ"                     # the futures month codes, January to December
_HOLIDAYS = "Motor!$A$361:$A$523"
_HOLIDAY_NAMES = "Motor!$B$361:$B$523"


def viop_expiry(day: str) -> str:
    """The expiry of the VİOP contract of ``day``'s month (an expression, ``LET`` names ``h`` / ``l`` / ``e`` - the
    holidays, the month's last business day, the expiry): its last business day - or the business day before when that
    one is a half day, the eve of 29 October or of a bayram (the workbook's contracts: 30.11.2026, 31.12.2026 ... and
    27.10.2027, where 28.10 is the eve of the 29th)."""
    return ('h,%(h)s,l,WORKDAY(EOMONTH(%(d)s,0)+1,-1,h),'
            'e,IF(OR(AND(MONTH(l+1)=10,DAY(l+1)=29),ISNUMBER(SEARCH("Bayram",IFERROR(INDEX(%(n)s,MATCH(l+1,h,0)),"")))),'
            'WORKDAY(l,-1,h),l)' % {"h": _HOLIDAYS, "n": _HOLIDAY_NAMES, "d": day})


def viop_ticker(root: str, key: str, step: int, k: int) -> str:
    """The formula of the ``k``-th (0: the nearest) contract trading today: a contract trades until its expiry (the day
    included); ``step`` 2: only the even months are listed (the gold contracts)."""
    if step == 1:
        first = "IF(t<=e,0,1)"
    else:
        first = "IF(MOD(MONTH(t),2)=1,1,IF(t<=e,0,2))"
    return ('=LET(t,TODAY(),%s,m,EDATE(EOMONTH(t,-1)+1,%s+%d),"%s"&MID("%s",MONTH(m),1)&MOD(YEAR(m),10)&" %s")'
            % (viop_expiry("t"), first, step * k, root, VIOP_MONTHS, key))


def _viop_roll_check(model: Model) -> None:
    _need_sheets(model, "VIOP", "Motor")
    sh = model.sheet("VIOP")
    for rng, root, key, _ in VIOP_ROLLS:
        r1, c1, r2, c2 = parse_range(rng)
        for c in range(c1, c2 + 1):
            rc = r1 * COLS + c
            text = sh.consts.get(rc)
            if rc in sh.fml or not isinstance(text, str) or not re.fullmatch(r"%s[%s]\d %s" % (root, VIOP_MONTHS, key), text):
                raise ValueError("VIOP!%s%d beklenen kontrat değil (%s… %s)" % (index_to_col(c), r1, root, key))
    for addr in ("L5", "M46", "M61"):                         # the expiry of the contracts: Bloomberg's, next to them
        _need_formula(model, "VIOP", addr, "LAST_TRADEABLE_DT")


def _tto_viop_roll(model: Model) -> None:
    kept = model.meta.setdefault(FILE_VALUES, {})
    b = SheetBuilder(model, "VIOP")
    for rng, root, key, step in VIOP_ROLLS:
        r1, c1, r2, c2 = parse_range(rng)
        for k, c in enumerate(range(c1, c2 + 1)):
            addr = "%s%d" % (index_to_col(c), r1)
            kept["VIOP!" + addr] = b.sheet.consts.get(parse_a1(addr))
            b.patch(addr, viop_ticker(root, key, step, k))


# ---------------------------------------------------------------------------------------------- bulk date-to-date rates
#: The desk sheet's "Tarih arası faiz" block (MASA!B59:N70) prices one start / end pair on the TRY OIS curves: the days
#: from the OIS spot to the start and the end (K60 / M60), each curve's discount factors at the two dates (H / I of rows
#: 62-68: MPC ima, S1-S3, Bootstrap, TLREF sabit; Ağırlıklı is S1-S3 weighted with the OIS sheet's probabilities) and the
#: period's rate ACT/365 (C), ACT/360 (D), O/N (E) and ACT/360 + the spread (F).  ``EK_TARIH`` ("TOPLU TARİH ARASI FAİZ",
#: the desk page's Faiz · PPK tab, right after the block) prices up to 100 pairs at once with the block's own formulas
#: carried to each row (``transplant``): a row with the block's start, end and spread gives the block's numbers, on the
#: viewer's curve setting as the block (its Bootstrap row reads Motor's nodes).  Per row: Başlangıç (blank: the OIS spot,
#: the block's own default), Bitiş, Spread (bp; blank: the general spread at the top, which starts from the desk's one OIS
#: spread MASA!I60 as the forward quote matrix's does).  Out: Gün, each curve's period rate in the basis chosen at the top
#: (ACT/360 - the desk's quote - by default, ACT/365 or O/N) and the chosen curve's ACT/360 rate + spread (the block's
#: "Dönem + spread (360)").  The rows start empty, the page shows the filled ones and one more, and a block pasted from
#: Excel (start | end | spread) lands row by row, as on EK_BULK.
TARIH_SHEET = "EK_TARIH"
TARIH_FIRST, TARIH_ROWS = 5, 100
TARIH_LAST = TARIH_FIRST + TARIH_ROWS - 1
#: the block's curves: the code the selector lists, the curve's row on MASA (Ağırlıklı's has no discount factors)
TARIH_CURVES = (("MPC ima", 62), ("S1", 63), ("S2", 64), ("S3", 65), ("Ağırlıklı", 66), ("Bootstrap", 67), ("TLREF sabit", 68))
TARIH_WEIGHTED = 66
TARIH_BASES = ("ACT/360", "ACT/365", "O/N (360)")             # the block's D, C and E
TARIH_CURVE, TARIH_BASIS, TARIH_SPREAD = "C2", "E2", "G2"      # the choices at the top (personal inputs)
TARIH_RATES = "FGHIJKL"                                         # each curve's period rate, in TARIH_CURVES' order
TARIH_PLUS = "M"                                                # the chosen curve's ACT/360 rate + spread
TARIH_HELP = "O"                                                # the helpers from here on (a table the page keeps hidden)
TARIH_PICKED = "O2"                                             # the chosen curve's number (1 = MPC ima … 7)


def _tarih_layout() -> Dict[Any, str]:
    """The helper columns: ``"ks"`` / ``"ke"`` the days from the OIS spot to the start / end (the block's K60 / M60),
    ``("df", code, 0 | 1)`` a curve's discount factor at the start / end (H / I), ``("d", code)`` its ACT/360 rate (D),
    ``("f", code)`` its ACT/360 rate + spread (F)."""
    k = _col(TARIH_HELP)
    out: Dict[Any, str] = {"ks": index_to_col(k), "ke": index_to_col(k + 1)}
    k += 2
    for code, row in TARIH_CURVES:
        if row != TARIH_WEIGHTED:
            out[("df", code, 0)], out[("df", code, 1)] = index_to_col(k), index_to_col(k + 1)
            k += 2
    for what in ("d", "f"):
        for code, _ in TARIH_CURVES:
            out[(what, code)] = index_to_col(k)
            k += 1
    return out


def _tarih_formulas(model: Model, r: int) -> Dict[Any, str]:
    """The block's formulas carried to row ``r`` of EK_TARIH (texts without ``=``): ``"E"`` the days (G60), the helpers of
    :func:`_tarih_layout`, ``("c" | "e", code)`` a curve's ACT/365 / O/N rate (C / E) and ``("w", "d")`` Ağırlıklı over
    the row's shown S1-S3 rates (the block's C66 / D66 / E66: the same weighted average in each basis).  An error when a
    formula is not the one expected: each must hold the references named, and nothing of the block but the cells swapped
    for the row's (``transplant``)."""
    lay = _tarih_layout()

    def take(addr: str, needs: Sequence[str], swap: Dict[str, str]) -> str:
        text = _need_formula(model, "MASA", addr)
        for part in needs:
            if part not in text:
                raise ValueError("MASA!%s beklenen formül değil (%s yok)" % (addr, part))
        # every cell swapped in one pass: one by one, row 60's "$C60" would be taken for the block's C60 next
        keys = re.compile(r"(?<![A-Za-z$])(?:%s)(?![0-9])" % "|".join(re.escape(k) for k in sorted(swap, key=len, reverse=True)))
        return transplant(keys.sub(lambda m: swap[m.group(0)], text), {new: new for new in swap.values()})

    out: Dict[Any, str] = {"E": take("G60", ("E60-C60",), {"E60": "$C%d" % r, "C60": "$B%d" % r}),
                           lay["ks"]: take("K60", ("C60-OIS_MAIN!$B$2",), {"C60": "$B%d" % r}),
                           lay["ke"]: take("M60", ("E60-OIS_MAIN!$B$2",), {"E60": "$C%d" % r})}
    days = "$E%d" % r
    scenarios = [code for code, k in TARIH_CURVES if code.startswith("S")]

    def weighted(cells: Sequence[str]) -> str:
        # the block's SUMPRODUCT of the probabilities and a column of three rates, written out over a row's three cells
        # (a row against the column would not multiply): the same products added in the same order
        return ('IFERROR((OIS_MAIN!$Q$3*%s+OIS_MAIN!$Q$4*%s+OIS_MAIN!$Q$5*%s)/SUM(OIS_MAIN!$Q$3:$Q$5),"")'
                % tuple("$%s%d" % (c, r) for c in cells))

    for code, k in TARIH_CURVES:
        if k == TARIH_WEIGHTED:
            # Ağırlıklı: the S1-S3 rates (rows 63-65 of the block) weighted with the OIS sheet's probabilities, in C, D, E, F
            # (checked to be just that, then written out over the row's cells)
            for col in "CDEF":
                take("%s%d" % (col, k), ("(SUMPRODUCT(OIS_MAIN!$Q$3:$Q$5,%s63:%s65)/SUM(OIS_MAIN!$Q$3:$Q$5))" % (col, col),),
                     {"%s63" % col: "$X1", "%s65" % col: "$X3"})
            out[("d", code)] = weighted([lay[("d", s)] for s in scenarios])
            out[("f", code)] = weighted([lay[("f", s)] for s in scenarios])
            out[("w", "d")] = weighted(TARIH_RATES[1:4])                   # over the row's shown S1-S3, in their basis
            continue
        start, end = "$%s%d" % (lay[("df", code, 0)], r), "$%s%d" % (lay[("df", code, 1)], r)
        out[lay[("df", code, 0)]] = take("H%d" % k, ("$K$60",), {"$K$60": "$%s%d" % (lay["ks"], r)})
        out[lay[("df", code, 1)]] = take("I%d" % k, ("$M$60",), {"$M$60": "$%s%d" % (lay["ke"], r)})
        for col in "CDE":
            out[(col.lower(), code)] = take("%s%d" % (col, k), ("H%d/I%d" % (k, k), "$G$60"),
                                            {"H%d" % k: start, "I%d" % k: end, "$G$60": days})
        out[("f", code)] = take("F%d" % k, ("D%d+$I$60/10000" % k,), {"D%d" % k: "$%s%d" % (lay[("d", code)], r), "$I$60": "$D%d" % r})
    return out


def _tarih_check(model: Model) -> None:
    _need_sheets(model, "MASA", "OIS_MAIN", "Motor")
    if TARIH_SHEET in model.sheet_index:
        raise ValueError("%s sayfası zaten var" % TARIH_SHEET)
    _need_captions(model, (("MASA", "B60", "Başlangıç"), ("MASA", "D60", "Bitiş"), ("MASA", "H60", "Spread (bp)"),
                           ("MASA", "C61", "Dönem ACT/365"), ("MASA", "D61", "Dönem ACT/360"), ("MASA", "E61", "Dönem O/N (360)"),
                           ("MASA", "F61", "Dönem + spread (360)"), ("MASA", "H61", "DF başlangıç"), ("MASA", "I61", "DF bitiş"))
                    + tuple(("MASA", "B%d" % k, code) for code, k in TARIH_CURVES if not code.startswith("S")))
    for code, k in TARIH_CURVES:
        if code.startswith("S"):                                   # the scenarios' rows: "S1 – " & their name
            _need_formula(model, "MASA", "B%d" % k, '"%s – "' % code)
    _tarih_formulas(model, TARIH_FIRST)


def _tto_tarih(model: Model) -> None:
    """The bulk date-to-date rates (``EK_TARIH``): the choices at the top, 100 rows of the desk sheet's block, the helpers."""
    b = SheetBuilder(model, TARIH_SHEET)
    lay = _tarih_layout()
    codes = [code for code, _ in TARIH_CURVES]
    b.title("B1", "TOPLU TARİH ARASI FAİZ  ·  100 tarih çiftine kadar (başlangıç boşsa OIS spot, spread boşsa genel spread; "
                  "Excel'den başlangıç | bitiş | spread yapıştırılabilir)")
    b.set("B2", "Eğri (+ spread)", bold=True, align="right")
    b.input(TARIH_CURVE, codes[0], align="center")
    b.dropdown(TARIH_CURVE, codes)
    b.set("D2", "Gün esası", bold=True, align="right")
    b.input(TARIH_BASIS, TARIH_BASES[0], align="center")
    b.dropdown(TARIH_BASIS, TARIH_BASES)
    b.set("F2", "Genel spread (bp)", bold=True, align="right")
    b.input(TARIH_SPREAD, "=" + OIS_SPREAD, fmt="0", align="center")      # the desk's one OIS spread, typed over: one's own
    b.set("H2", "OIS spot", bold=True, align="right")
    b.set("I2", "=OIS_MAIN!$B$2", fmt=DATE)
    # the curves' columns are named as the block names its rows (S1 – Baz …: the scenario's name from SENARYOLAR)
    picked = "$%s$%s" % (TARIH_PICKED[0], TARIH_PICKED[1:])
    b.head("B4", ["Başlangıç", "Bitiş", "Spread (bp)", "Gün"] + ["=MASA!$B$%d" % k for _, k in TARIH_CURVES]
           + ['=INDEX($%s$4:$%s$4,%s)&" + spread (360)"' % (TARIH_RATES[0], TARIH_RATES[-1], picked)])
    d0, d1 = lay[("d", codes[0])], lay[("d", codes[-1])]
    f0, f1 = lay[("f", codes[0])], lay[("f", codes[-1])]
    b.note("%s3" % TARIH_HELP, "Yardımcı: OIS spot'tan başlangıç / bitiş günü, eğrilerin iskonto faktörleri (MASA H / I), ACT/360 faiz "
                               "(MASA D) ve + spread (MASA F), satır satır")
    b.set(TARIH_PICKED, '=IFERROR(MATCH($%s$%s,$%s$4:$%s$4,0),1)' % (TARIH_CURVE[0], TARIH_CURVE[1:], d0, d1), fmt="0")
    b.head("%s4" % TARIH_HELP, ["Gün spot→başl.", "Gün spot→bitiş"]
           + ["DF %s %s" % (end, code) for code, k in TARIH_CURVES if k != TARIH_WEIGHTED for end in ("başl.", "bitiş")]
           + codes + ["%s + spread" % code for code in codes])
    basis = "$%s$%s" % (TARIH_BASIS[0], TARIH_BASIS[1:])
    # the first row, then filled down: every row's formulas are the first's with the row's own cells
    r = TARIH_FIRST
    fml = _tarih_formulas(model, r)
    blank = 'IF($E%d="","",' % r                                            # a row without its two dates shows nothing
    b.input("B%d" % r, '=IF(ISNUMBER($C%d),OIS_MAIN!$B$2,"")' % r, fmt=DATE)
    b.input("C%d" % r, None, fmt=DATE)
    b.input("D%d" % r, '=IF(ISNUMBER($C%d),$%s$%s,"")' % (r, TARIH_SPREAD[0], TARIH_SPREAD[1:]), fmt="0")
    b.set("E%d" % r, '=IF(AND(ISNUMBER($B%d),ISNUMBER($C%d)),%s,"")' % (r, r, fml["E"]), fmt=INT0)
    b.set("%s%d" % (lay["ks"], r), '=IF(ISNUMBER($B%d),%s,"")' % (r, fml[lay["ks"]]), fmt=INT0)
    b.set("%s%d" % (lay["ke"], r), '=IF(ISNUMBER($C%d),%s,"")' % (r, fml[lay["ke"]]), fmt=INT0)
    for i, (code, k) in enumerate(TARIH_CURVES):
        shown = "%s%d" % (TARIH_RATES[i], r)
        if k == TARIH_WEIGHTED:
            b.set(shown, "=" + blank + fml[("w", "d")] + ")", fmt="0.00%")
        else:
            for end in (0, 1):
                col = lay[("df", code, end)]
                b.set("%s%d" % (col, r), "=" + blank + fml[col] + ")", fmt="0.000000000")
            # the period's rate in the basis chosen: ACT/360 (the block's D, the helper), ACT/365 (C) or O/N (E)
            b.set(shown, '=%sIF(%s="%s",%s,IF(%s="%s",%s,$%s%d)))' % (blank, basis, TARIH_BASES[1], fml[("c", code)], basis,
                                                                    TARIH_BASES[2], fml[("e", code)], lay[("d", code)], r),
                  fmt="0.00%")
        b.set("%s%d" % (lay[("d", code)], r), "=" + blank + fml[("d", code)] + ")", fmt="0.0000%")
        b.set("%s%d" % (lay[("f", code)], r), "=" + blank + fml[("f", code)] + ")", fmt="0.0000%")
    b.set("%s%d" % (TARIH_PLUS, r), "=%sINDEX($%s%d:$%s%d,%s))" % (blank, f0, r, f1, r, picked), fmt="0.00%")
    for c in list(range(_col("B"), _col(TARIH_PLUS) + 1)) + list(range(_col(TARIH_HELP), _col(f1) + 1)):
        b.fill_down("%s%d" % (index_to_col(c), r), TARIH_LAST)
    b.note("B%d" % (TARIH_LAST + 2), "Masa'daki TARİH ARASI FAİZ bloğunun formülleri, satır satır: eğrilerin OIS spot'tan başlangıç ve "
                                     "bitişe iskonto faktörleri (MASA!H62:I68), dönem faizi (DF başl. / DF bitiş − 1)·360/gün - ACT/365'te "
                                     "·365, O/N'de 360·((DF başl. / DF bitiş)^(1/gün) − 1) -, Ağırlıklı = S1–S3, OIS · PPK olasılıklarıyla. "
                                     "Aynı tarih ve spread'le blokla aynı sayıyı verir.")
    b.note("B%d" % (TARIH_LAST + 3), "Başlangıç boşsa OIS spot valörü; spread boşsa genel spread (Masa'daki tek OIS spread'inden, MASA!I60; "
                                     "üzerine yazılabilir). Son sütun seçilen eğrinin ACT/360 basit faizi + spread (bloğun 'Dönem + spread "
                                     "(360)'ı), gün esası ne olursa olsun. Yazdıklarınız sizin kalır; satırlar boş başlar.")


# ---------------------------------------------------------------------------------------------- VİOP target: a far price
#: The target table of the VİOP sheet (VIOP!K330:Y338) goes from a target rate to the far contract's limit price: "Hedef
#: tipi" FRA+bp (OIS FRA + bp), FXswap+bp (the FX swap implied rate + bp) or Faiz % (a rate typed), "Hedef değer" its
#: value, "Hedef faiz (360)" (Q) the rate, "Uzak limit fiyatı" (S) = near limit · (1 + rate · days / 360) / USD carry -
#: the near limit the near contract's ask on a SHORT row, its bid on a LONG one (R), the days between the two contracts
#: (row 98), the USD carry (1 + USD far · days far / 360) / (1 + USD near · days near / 360) (row 101).  One more type
#: goes the other way: **Fiyat**, the far contract's price typed in "Hedef değer" (51,10).  Its target rate is the rate
#: that price implies, ((price / near limit) · USD carry − 1) · 360 / days - the exact inverse of the sheet's own far limit
#: price, in the table's own convention - and the rest of the row follows it as for the other types: the far limit (the
#: price again), the spread price, target − market, the DV01; OIS FRA stays the bootstrapped curve's, as on a Faiz % row
#: (EK_VFRA).  A price that is not above zero gives no rate.  The type's drop-down gets the item, and "Hedef değer" shows a
#: price's decimals (the file's integer format becomes General; a bp value looks as before).
VPRICE_NAME = "VİOP hedef fiyatı"
VPRICE_TYPE = "Fiyat"
VPRICE_TYPES = ("FRA+bp", "FXswap+bp", "Faiz %")              # the workbook's list of target types (VIOP!O331:O338)
VPRICE_INT = '_-* #,##0_-;\\-* #,##0_-;_-* "-"??_-;_-@_-'      # the file's number format of "Hedef değer"


def viop_near_limit(r: int) -> str:
    """The near limit of target row ``r`` as the sheet takes it (VIOP!R331 …): the near contract's ask on a SHORT row,
    its bid otherwise."""
    return ('IF($N%(r)d="SHORT",INDEX($L$100:$X$100,MATCH($L%(r)d,$L$97:$X$97,0)),INDEX($L$99:$X$99,MATCH($L%(r)d,$L$97:$X$97,0)))'
            % {"r": r})


def viop_target_days(r: int) -> str:
    """The days between the row's two contracts (row 98: each contract's days from the VİOP spot)."""
    return "(INDEX($L$98:$X$98,MATCH($M%(r)d,$L$97:$X$97,0))-INDEX($L$98:$X$98,MATCH($L%(r)d,$L$97:$X$97,0)))" % {"r": r}


def viop_usd_carry(r: int) -> str:
    """The USD leg between the row's two contracts: (1 + USD far · days far / 360) / (1 + USD near · days near / 360)."""
    return ("((1+INDEX($L$101:$X$101,MATCH($M%(r)d,$L$97:$X$97,0))*INDEX($L$98:$X$98,MATCH($M%(r)d,$L$97:$X$97,0))/360)"
            "/(1+INDEX($L$101:$X$101,MATCH($L%(r)d,$L$97:$X$97,0))*INDEX($L$98:$X$98,MATCH($L%(r)d,$L$97:$X$97,0))/360))"
            % {"r": r})


def viop_far_limit(r: int) -> str:
    """The sheet's own far limit price of target row ``r`` (VIOP!S331 …): near limit · (1 + target rate · days / 360) /
    USD carry."""
    return "%s*(1+$Q%d*%s/360)/%s" % (viop_near_limit(r), r, viop_target_days(r), viop_usd_carry(r))


def viop_price_rate(r: int) -> str:
    """Its inverse: the target rate the far price typed in "Hedef değer" implies, ((price / near limit) · USD carry − 1)
    · 360 / days."""
    return "(($P%d/%s)*%s-1)*360/%s" % (r, viop_near_limit(r), viop_usd_carry(r), viop_target_days(r))


def _vprice_anchors(r: int) -> Tuple[str, str]:
    """Where the type's branch goes in the target rate (VIOP!Q331 …): right after Faiz %'s - ``IF($O="Faiz %",$P/100,
    IF($O="FXswap+bp",FX,FRA)+$P/10000)`` - and the end of the other two."""
    return ('IF($O%(r)d="Faiz %%",$P%(r)d/100,IF($O%(r)d="FXswap+bp",' % {"r": r}, "+$P%d/10000)" % r)


def _viop_price_check(model: Model) -> None:
    _need_sheets(model, "VIOP")
    _need_captions(model, (("VIOP", "O330", "Hedef tipi"), ("VIOP", "P330", "Hedef değer"), ("VIOP", "Q330", "Hedef faiz (360)"),
                           ("VIOP", "R330", "Near limit"), ("VIOP", "S330", "Uzak limit fiyatı")))
    for r in range(VFRA_ROWS[0], VFRA_ROWS[1] + 1):
        _need_formula(model, "VIOP", "R%d" % r, viop_near_limit(r))
        _need_formula(model, "VIOP", "S%d" % r, viop_far_limit(r))             # what the type's rate is the inverse of
        q = _need_formula(model, "VIOP", "Q%d" % r, '$P%d<>""),' % r)          # (a row needs its value)
        typed, rest = _vprice_anchors(r)
        if q.count(typed) != 1 or q.count(rest) != 1 or q.count(rest + ',""),"")') != 1 or q.index(typed) > q.index(rest):
            raise ValueError("VIOP!Q%d beklenen hedef faiz formülü değil (hedef tipleri)" % r)
        if VPRICE_TYPE in q:
            raise ValueError("VIOP!Q%d zaten %s tipini okuyor" % (r, VPRICE_TYPE))
    lists = [v for v in model.sheet("VIOP").validations if v.get("sqref") == "O%d:O%d" % VFRA_ROWS]
    if len(lists) != 1 or lists[0].get("type") != "list" or lists[0].get("formula1") != '"%s"' % ",".join(VPRICE_TYPES):
        raise ValueError("VIOP!O%d:O%d hedef tipi listesi beklenen değil" % VFRA_ROWS)


def _tto_viop_price(model: Model) -> None:
    """The target type "Fiyat": its item in the list, its branch in the target rate, a price's decimals in "Hedef değer"."""
    v = SheetBuilder(model, "VIOP")
    for r in range(VFRA_ROWS[0], VFRA_ROWS[1] + 1):
        typed, rest = _vprice_anchors(r)
        price = 'IF($O%d="%s",IF(N($P%d)>0,%s,""),' % (r, VPRICE_TYPE, r, viop_price_rate(r))
        v.patch("Q%d" % r, "=" + formula_of(model, "VIOP", "Q%d" % r).replace(typed, typed.replace(",IF(", "," + price + "IF(", 1))
                .replace(rest, rest + ")"))
        rc = parse_a1("P%d" % r)
        xf = v.sheet.styles.get(rc, 0)
        if model.numfmts[xf] == VPRICE_INT:                                   # (a format the file no longer has: left alone)
            _, bold, color, fill, align = model.xfs[xf][:5]
            v.sheet.styles[rc] = v._xf("General", bool(bold), color, fill, align)
    for item in v.sheet.validations:
        if item.get("sqref") == "O%d:O%d" % VFRA_ROWS:
            item["formula1"] = '"%s"' % ",".join(VPRICE_TYPES + (VPRICE_TYPE,))


# ---------------------------------------------------------------------------------------------- VİOP target: the FRA's curve
#: The target table of the VİOP sheet (VIOP!K330:Y338) prices an "FRA+bp" target off the OIS FRA between the row's near and
#: far contract - always the bootstrapped market curve (the sheet's row 104: Motor's log discount factors BOOT_LNDF, linear
#: in days).  Each row chooses the curve now ("FRA eğrisi", VIOP!Z331:Z338, personal like the row's other inputs): the
#: bootstrapped curve - the default, today's numbers - or one of the three PPK scenarios of the OIS sheet (OIS_MAIN's
#: SENARYOLAR table: names, probabilities, steps per meeting).  A scenario's curve is the desk sheet's own discount factor
#: (MASA!I63:I65, the "Tarih arası faiz" block, built on Motor's meeting paths) evaluated at the row's two dates.  The
#: drop-down reads its items from ``EK_VFRA`` - the scenarios named from the SENARYOLAR table, so a scenario renamed there
#: is renamed in the list - and the formulas read a choice by its code (S1 / S2 / S3; anything else is the bootstrapped
#: curve), so a choice made before a rename keeps its scenario.  OIS FRA takes the row's curve and the target rate of an
#: FRA row is built from it: the far limit price, the spread price and target − market follow.  The workbook prices a row
#: as FRA+bp unless its type is FXswap+bp or Faiz % (a blank type too); a row of those two - and of the dashboard's
#: Fiyat (a far price typed, above) - keeps the bootstrapped curve whatever is chosen.  The OIS FRA column names its curve
#: (its caption: one curve for every row or "per row"), and its cells, the target rate and the choice say theirs in their
#: tooltips (``"tips"`` of the page: columns AA:AC beside it).
#: A row that cannot be priced shows no numbers and says why in its tooltips and on the desk strip ("Geçersiz"): a contract
#: kept by its date that rolled off the list (the workbook leaves that row empty already), or a period that does not end
#: after the OIS spot date (the far contract's expiry day, where the sheet's own FRA was 0 and the target −1,5 %): OIS FRA,
#: the target rate, the limits, the spread price and target − market are empty then.
VFRA_SHEET = "EK_VFRA"
VFRA_ROWS = (331, 338)                    # the target rows of the VİOP sheet ...
VFRA_FIRST = 10                           # ... and their helper rows on EK_VFRA (10 … 17)
VFRA_BOOT = "Bootstrap (piyasa)"
VFRA_LIST = "%s!$A$3:$A$6" % VFRA_SHEET   # the drop-down: the bootstrapped curve, S1, S2, S3
#: the scenarios: code, their row in OIS_MAIN's SENARYOLAR table, the desk sheet's discount factor of their curve
VFRA_SCENARIOS = (("S1", 3, "I63"), ("S2", 4, "I64"), ("S3", 5, "I65"))
VFRA_CHOICE = "Z"                         # the choice (the page shows it right after "Hedef tipi")
VFRA_TIPS = {"W": "AA", "Q": "AB", "Z": "AC"}       # the tooltip of OIS FRA, of the target rate and of the choice
VFRA_MASA = 210                           # the desk sheet's target strip: MASA row = VİOP row − 210 (121 … 128)
VFRA_OTHER_TYPES = ("Faiz %", "FXswap+bp", VPRICE_TYPE)     # the types whose target rate does not read the FRA


def vfra_other(cell: str) -> str:
    """Whether target type ``cell`` is one of ``VFRA_OTHER_TYPES`` (an Excel condition)."""
    return "OR(%s)" % ",".join('%s="%s"' % (cell, t) for t in VFRA_OTHER_TYPES)


def viop_target_fra(r: int) -> str:
    """The VİOP sheet's own OIS FRA of target row ``r`` (in VIOP!W331 …, and in the FRA+bp branch of Q331 …): the
    bootstrapped curve's log discount factors of the near and the far contract (row 104), between their dates (row 103)."""
    return ("((EXP(INDEX($L$104:$X$104,MATCH($L%(r)d,$L$97:$X$97,0))-INDEX($L$104:$X$104,MATCH($M%(r)d,$L$97:$X$97,0)))-1)"
            "*360/(INDEX($L$103:$X$103,MATCH($M%(r)d,$L$97:$X$97,0))-INDEX($L$103:$X$103,MATCH($L%(r)d,$L$97:$X$97,0))))"
            % {"r": r})


def _vfra_rows():
    """(VİOP row, EK_VFRA row, desk sheet row) of each target row."""
    return [(r, VFRA_FIRST + r - VFRA_ROWS[0], r - VFRA_MASA) for r in range(VFRA_ROWS[0], VFRA_ROWS[1] + 1)]


def _viop_fra_check(model: Model) -> None:
    _need_sheets(model, "VIOP", "MASA", "OIS_MAIN", "Motor")
    _need_captions(model, (("VIOP", "K330", "Target"), ("VIOP", "O330", "Hedef tipi"), ("VIOP", "Q330", "Hedef faiz (360)"),
                           ("VIOP", "W330", "OIS FRA"), ("VIOP", "K97", "Kontrat"), ("VIOP", "K103", "Tarih"),
                           ("OIS_MAIN", "O1", "SENARYOLAR"), ("OIS_MAIN", "P2", "Ad"), ("OIS_MAIN", "O3", "S1"),
                           ("OIS_MAIN", "O4", "S2"), ("OIS_MAIN", "O5", "S3")))
    for _, _, src in VFRA_SCENARIOS:                   # a scenario's discount factor depends on the days in $M$60 only
        transplant(_need_formula(model, "MASA", src, "$M$60"), {"$M$60": "$H%d" % VFRA_FIRST})
    for r, _, m in _vfra_rows():
        fra = viop_target_fra(r)
        _need_formula(model, "VIOP", "W%d" % r, fra)
        if _need_formula(model, "VIOP", "Q%d" % r, '$O%d="FXswap+bp"' % r).count(fra) != 1:
            raise ValueError("VIOP!Q%d beklenen hedef faiz formülü değil (OIS FRA yok)" % r)
        _need_formula(model, "MASA", "S%d" % m, 'VIOP!$O$%d&" "&VIOP!$P$%d' % (r, r))
    sh = model.sheet("VIOP")
    cols = [VFRA_CHOICE] + sorted(set(VFRA_TIPS.values()))
    taken = ["%s%d" % (c, r) for c in cols for r in range(VFRA_ROWS[0] - 1, VFRA_ROWS[1] + 1)
             if parse_a1("%s%d" % (c, r)) in sh.consts or parse_a1("%s%d" % (c, r)) in sh.fml]
    if taken:
        raise ValueError("VIOP target tablosunun yanı boş değil: %s" % ", ".join(taken))


def _tto_viop_fra(model: Model) -> None:
    """The FRA's curve per target row: the list, the helpers on ``EK_VFRA``, the choice beside the table and the OIS FRA /
    target rate / caption / tooltips / desk strip that follow it."""
    e = VFRA_SHEET
    b = SheetBuilder(model, e)
    b.title("A1", "VİOP TARGET · FRA EĞRİSİ  ·  Target tablosunun 'FRA eğrisi' listesi ve her satırın FRA'sı eğri eğri")
    b.head("A2", ["FRA eğrisi", "Eğri", "Olasılık"])
    b.set("A3", VFRA_BOOT, bold=True)
    b.note("B3", "piyasa OIS eğrisi: kotalardan bootstrap (Motor, BOOT_LNDF) - VİOP sayfasının bugünkü OIS FRA'sı, varsayılan")
    for k, (code, row, _) in enumerate(VFRA_SCENARIOS):
        r = 4 + k
        b.set("A%d" % r, '="%s · "&OIS_MAIN!$P$%d' % (code, row), bold=True)
        b.note("B%d" % r, "OIS · PPK senaryosu %s: toplantı başına adımları PPK ima sekmesinde, adı ve olasılığı SENARYOLAR "
                          "tablosunda (MASA 'Tarih arası faiz' bloğunun iskonto faktörleri)" % code)
        b.set("C%d" % r, "=OIS_MAIN!$Q$%d" % row, fmt="0%", align="center")
    b.note("A7", "Bu liste VİOP Target tablosundaki 'FRA eğrisi'nin açılır listesidir (VIOP!Z331:Z338). Senaryo adları OIS · PPK'daki "
                 "SENARYOLAR tablosundan gelir: orada değişince burada da değişir; formüller seçimi koduyla (S1 / S2 / S3) okur. "
                 "Seçim FRA+bp satırında (boş hedef tipi de FRA+bp sayılır) OIS FRA'yı ve hedef faizi belirler; FXswap+bp, "
                 "Faiz % ve Fiyat satırlarında etkisizdir (Bootstrap).")
    # ---- one helper row per target row: the choice, the dates, each curve's discount factors and FRA
    h0 = VFRA_FIRST
    b.head("A%d" % (h0 - 1), ["Satır", "Seçim", "Seçim no", "Etkin no", "Etkin eğri", "Yakın", "Uzak", "Gün yakın", "Gün uzak"]
                             + ["DF %s %s" % (code, end) for code, _, _ in VFRA_SCENARIOS for end in ("yakın", "uzak")]
                             + ["FRA Bootstrap", "FRA S1", "FRA S2", "FRA S3", "Canlı satırın eğri no", "Durum"])
    dfs = {code: formula_of(model, "MASA", src) for code, _, src in VFRA_SCENARIOS}
    on_viop = {"$L$104:$X$104": "VIOP!$L$104:$X$104", "$L$103:$X$103": "VIOP!$L$103:$X$103", "$L$97:$X$97": "VIOP!$L$97:$X$97"}
    for i, (r, h, _) in enumerate(_vfra_rows()):
        f = {"r": r, "h": h}
        b.set("A%d" % h, float(i + 1), fmt="0", align="center")
        b.set("B%d" % h, '=IF(VIOP!$Z%(r)d="","",VIOP!$Z%(r)d)' % f)
        # the choice by its code (a name renamed since keeps its scenario); anything else: the bootstrapped curve
        b.set("C%d" % h, '=IF(LEFT(VIOP!$Z%(r)d,2)="S1",2,IF(LEFT(VIOP!$Z%(r)d,2)="S2",3,IF(LEFT(VIOP!$Z%(r)d,2)="S3",4,1)))' % f,
              fmt="0", align="center")
        # the curve the row is priced off: the choice in an FRA row, the bootstrapped curve in a row of another type
        b.set("D%d" % h, '=IF(%s,1,$C%d)' % (vfra_other("VIOP!$O%d" % r), h), fmt="0", align="center")
        b.set("E%d" % h, "=INDEX($A$3:$A$6,$D%(h)d)" % f)
        # the contracts' dates as the sheet's own FRA takes them (row 103), and their days from the OIS spot date as the
        # curves count them (from 0: the sheet's row 104 does the same with MAX(0, …))
        for col, leg in (("F", "L"), ("G", "M")):
            b.set("%s%d" % (col, h), '=IFERROR(INDEX(VIOP!$L$103:$X$103,MATCH(VIOP!$%s%d,VIOP!$L$97:$X$97,0)),"")' % (leg, r), fmt=DATE)
        b.set("H%d" % h, '=IF(ISNUMBER($F%(h)d),MAX(0,$F%(h)d-OIS_MAIN!$B$2),"")' % f, fmt=INT0)
        b.set("I%d" % h, '=IF(ISNUMBER($G%(h)d),MAX(0,$G%(h)d-OIS_MAIN!$B$2),"")' % f, fmt=INT0)
        cols = iter("JKLMNO")
        for code, _, _ in VFRA_SCENARIOS:
            for days in ("$H%d" % h, "$I%d" % h):
                b.set("%s%d" % (next(cols), h), "=" + transplant(dfs[code], {"$M$60": days}), fmt="0.000000")
        # the sheet's own FRA, word for word (its cells named on their sheet): the bootstrapped curve's - today's OIS FRA
        boot = transplant(viop_target_fra(r), {**on_viop, "$L%d" % r: "VIOP!$L%d" % r, "$M%d" % r: "VIOP!$M%d" % r})
        b.set("P%d" % h, '=IFERROR(%s,"")' % boot, fmt="0.0000%")
        # a scenario's FRA: (DF near / DF far − 1) · 360 / days, as the desk sheet's block takes a period's rate
        for col, (near, far) in zip("QRS", (("J", "K"), ("L", "M"), ("N", "O"))):
            b.set("%s%d" % (col, h), '=IFERROR(($%s%d/$%s%d-1)*360/($G%d-$F%d),"")' % (near, h, far, h, h, h), fmt="0.0000%")
        b.set("T%d" % h, '=IF(ISNUMBER(VIOP!$W%(r)d),$D%(h)d,"")' % f, fmt="0", align="center")
        # why a row cannot be priced, said in so many words (the row's numbers are left empty then): a contract kept by its
        # date that is no longer listed (it expired - the contracts roll by themselves), or a period that does not end after
        # the OIS spot date (the far contract's expiry day) - the curves have nothing to price
        listed = "ISNUMBER(MATCH(VIOP!$%s%d,VIOP!$L$97:$X$97,0))"
        b.set("U%d" % h, ('=IF(OR(VIOP!$L%(r)d="",VIOP!$M%(r)d=""),"",IF(AND(%(near)s,%(far)s),IF(N($G%(h)d)<=OIS_MAIN!$B$2,'
                          '"Geçersiz: dönem OIS spot valöründen ("&TEXT(OIS_MAIN!$B$2,"dd.mm.yyyy")&") sonra bitmiyor (uzak kontratın vade '
                          'günü ya da geçmiş): satır hesaplanmıyor",""),"Geçersiz: "&IF(%(near)s,"","yakın kontrat "&VIOP!$L%(r)d'
                          '&" ")&IF(%(far)s,"","uzak kontrat "&VIOP!$M%(r)d&" ")&"VİOP kontrat listesinde yok (vadesi geçmiş olabilir): '
                          'satır hesaplanmıyor, kontratı listeden yeniden seçin"))') % dict(f, near=listed % ("L", r), far=listed % ("M", r)))
    last = h0 + VFRA_ROWS[1] - VFRA_ROWS[0]
    b.note("A%d" % (last + 2), "DF = MASA 'Tarih arası faiz' bloğunun S1 / S2 / S3 iskonto faktörü (Motor'un PPK patikası), OIS spot'tan "
                               "yakın ve uzak kontrat tarihine; FRA = (DF yakın / DF uzak − 1) · 360 / gün (ACT/360 basit). FRA Bootstrap "
                               "VİOP sayfasının kendi OIS FRA formülüdür (satır 104: BOOT_LNDF).")
    b.note("A%d" % (last + 3), "Etkin no: 1 = Bootstrap, 2–4 = S1–S3; FXswap+bp, Faiz % ve Fiyat satırında 1. OIS FRA (VIOP!W) etkin eğrinin FRA'sı, "
                               "FRA+bp hedef faizi (VIOP!Q) OIS FRA + hedef değer (bp). Durum dolu (geçersiz) satırda OIS FRA ve hedef faiz "
                               "boştur; limitler, spread fiyatı ve hedef − piyasa da onlarla boş kalır.")

    # ---- the VİOP sheet: the choice beside the table, OIS FRA and the target rate from the chosen curve
    v = SheetBuilder(model, "VIOP")
    c = VFRA_CHOICE
    v.set("%s%d" % (c, VFRA_ROWS[0] - 1), "FRA eğrisi", like="O%d" % (VFRA_ROWS[0] - 1))
    v.list_from("%s%d:%s%d" % (c, VFRA_ROWS[0], c, VFRA_ROWS[1]), VFRA_LIST)
    live = "%s!$T$%d:$T$%d" % (e, h0, last)
    v.patch("W%d" % (VFRA_ROWS[0] - 1), ('="OIS FRA · "&IF(COUNT(%(t)s)=0,%(e)s!$A$3,IF(MIN(%(t)s)=MAX(%(t)s),'
                                         'INDEX(%(e)s!$A$3:$A$6,MIN(%(t)s)),"eğri satıra göre"))') % {"t": live, "e": e})
    tip_w, tip_q, tip_z = VFRA_TIPS["W"], VFRA_TIPS["Q"], VFRA_TIPS["Z"]
    head = VFRA_ROWS[0] - 1
    v.set("%s%d" % (tip_w, head), "OIS FRA: yakın → uzak kontrat, ACT/360 basit, satırın FRA eğrisinden - Bootstrap (piyasa) = kotalardan "
                                  "kurulan piyasa eğrisi, S1–S3 = OIS · PPK senaryoları. FXswap+bp, Faiz % ve Fiyat satırlarında "
                                  "Bootstrap.")
    v.set("%s%d" % (tip_q, head), "Hedef faiz: FRA+bp = OIS FRA (satırın FRA eğrisi) + hedef değer (bp); FXswap+bp = FX swap ima + bp; "
                                  "Faiz % = yazılan faiz; Fiyat = yazılan uzak kontrat fiyatının ima ettiği faiz. Uzak limit, spread "
                                  "fiyatı ve hedef − piyasa bundan.")
    v.set("%s%d" % (tip_z, head), "FRA eğrisi: FRA+bp satırının OIS FRA'sı ve hedef faizi hangi eğriden - Bootstrap (piyasa) ya da OIS · "
                                  "PPK'daki senaryolar (adları SENARYOLAR tablosundan). FXswap+bp, Faiz % ve Fiyat satırlarında etkisiz. "
                                  "Delete: varsayılana döner.")
    for r, h, m in _vfra_rows():
        f = {"r": r, "h": h, "e": e, "list": VFRA_LIST.split(":")[0], "other": vfra_other("$O%d" % r), "price": VPRICE_TYPE}
        fra = viop_target_fra(r)
        # the default: the bootstrapped curve, shown once the row has its two contracts and is priced as an FRA
        v.set("%s%d" % (c, r), '=IF(AND($L%(r)d<>"",$M%(r)d<>"",NOT(%(other)s)),%(list)s,"")' % f, like="O%d" % r)
        # a row that cannot be priced shows no OIS FRA and no target rate - nor the limits, the spread price and target −
        # market built on it (the sheet's own FRA was 0 and the target −1,5 % on the far contract's expiry day); why it
        # cannot be priced is in its tooltips and on the desk strip
        unpriced = 'IF(%(e)s!$U$%(h)d<>"","",' % f
        v.patch("W%d" % r, "=" + unpriced + formula_of(model, "VIOP", "W%d" % r).replace(
            fra, "INDEX(%(e)s!$P%(h)d:$S%(h)d,%(e)s!$D%(h)d)" % f) + ")")
        v.patch("Q%d" % r, "=" + unpriced + formula_of(model, "VIOP", "Q%d" % r).replace(fra, "$W%d" % r) + ")")
        # the tooltips: a row that cannot be priced says why first (in all three); a scenario's FRA beside the market's
        bad = 'IF(%(e)s!$U$%(h)d<>"",%(e)s!$U$%(h)d,' % f
        v.set("%s%d" % (tip_w, r), ('=' + bad + 'IF(ISNUMBER($W%(r)d),"OIS FRA, "&%(e)s!$E$%(h)d&" eğrisinden"&IF(AND(%(e)s!$D$%(h)d>1,'
                                    'ISNUMBER(%(e)s!$P$%(h)d))," ("&%(e)s!$A$3&": "&TEXT(%(e)s!$P$%(h)d,"0.00%%")&")","")'
                                    '&IF(AND(%(e)s!$C$%(h)d>1,%(e)s!$D$%(h)d=1)," - seçilen FRA eğrisi ("&%(e)s!$B$%(h)d&") yalnız FRA+bp '
                                    'satırında geçerli",""),""))') % f)
        # (a far price typed: the rate it implies, from what)
        v.set("%s%d" % (tip_q, r), ('=' + bad + 'IF(AND(ISNUMBER($Q%(r)d),NOT(%(other)s)),"Hedef faiz = OIS FRA ("'
                                    '&%(e)s!$E$%(h)d&")"&IF($P%(r)d<0," − "," + ")&TEXT(ABS($P%(r)d),"General")&" bp",'
                                    'IF(AND(ISNUMBER($Q%(r)d),$O%(r)d="%(price)s"),"Hedef faiz = uzak kontrat fiyatı "&TEXT($P%(r)d,'
                                    '"General")&" → ima TRY faizi (yakın limit "&TEXT($R%(r)d,"0.0000")&", "&TEXT($Y%(r)d,"0")&" gün, '
                                    'ACT/360)","")))') % f)
        # (a scenario renamed since it was chosen: the choice keeps its old text, as an Excel list does, and its scenario)
        v.set("%s%d" % (tip_z, r), ('=' + bad + 'IF(AND(%(e)s!$C$%(h)d>1,%(e)s!$D$%(h)d=1),"Hedef tipi "&$O%(r)d&": FRA eğrisi bu '
                                    'satırda etkisiz (yalnız FRA+bp satırında geçerli)",IF(AND(%(e)s!$C$%(h)d>1,ISNA(MATCH($%(c)s%(r)d,'
                                    '%(e)s!$A$3:$A$6,0))),"Senaryonun adı değişti: seçim yine "&LEFT($%(c)s%(r)d,2)&", şimdiki adıyla "'
                                    '&INDEX(%(e)s!$A$3:$A$6,%(e)s!$C$%(h)d)&" (listeden yeniden seçilebilir)","")))') % dict(f, c=c))
        # the desk sheet's strip says the curve of an FRA row priced off a scenario - and a row that cannot be priced
        mf = 'VIOP!$O$%d&" "&VIOP!$P$%d' % (r, r)
        SheetBuilder(model, "MASA").patch("S%d" % m, "=" + formula_of(model, "MASA", "S%d" % m).replace(
            mf, '%s&IF(%s!$U$%d<>""," · geçersiz",IF(%s!$D$%d>1," · "&%s!$E$%d,""))' % (mf, e, h, e, h, e, h)))


# ---------------------------------------------------------------------------------------------- the fair RET's scenarios
#: The fair value RET (``tto/retfair.py``) can be read under one of the OIS sheet's three PPK scenarios instead of the
#: market ("Senaryo" of its tab, each user's own).  Its OIS base at a RET tenor is then the scenario curve's simple ACT/360
#: rate between the tenor's two dates - the desk sheet's own discount factors of that scenario (MASA!I63:I65, the "Tarih
#: arası faiz" block, Motor's meeting paths) at the two dates, so the same two dates give the block's own rate.  The
#: VİOP and offshore bases keep their basis to OIS: they move by the scenario's rate less the **reference**'s - the curve
#: of a scenario without a single step on the page's own rule (senaryo tabanı "ima yol", kaydırma 0): TLREF to the first
#: meeting, then the market's implied path.  That is no copy of the bootstrapped market curve (the OIS base of
#: "Piyasa"), so a scenario without steps gives the market's VİOP and offshore bases and the implied path's OIS.  A day
#: before the OIS spot date (the ON tenor) is carried with the OIS O/N (TLREF, 365 → 360: Forward!AD123), as the
#: market's OIS base carries it: no meeting falls there.  Every number is a formula of the user's own calculation: their
#: steps and names, the desk's calendar.
RETS_SHEET = "EK_RET"
RETS_FIRST = 10                            # the RET tenors' helper rows (10 … 24)
RETS_PATH = 30                             # the reference path's rows: Motor rows 4 … 84 on rows 30 … 110
RETS_MARKET = "Piyasa (bootstrap)"
#: the scenarios: code, their row in the SENARYOLAR table, the desk sheet's discount factor of their curve, the columns
#: of their discount factors (start, end) and of their rate on EK_RET
RETS_SCENARIOS = (("S1", 3, "I63", "G", "H", "O"), ("S2", 4, "I64", "I", "J", "P"), ("S3", 5, "I65", "K", "L", "Q"))
RETS_REF = ("M", "N", "R")                 # the reference's discount factors and rate
RETS_ON = "Forward!$AD$123"                # the OIS O/N (TLREF 365 → 360) a day before the OIS spot date is carried with


def _rets_layout(model: Model) -> List[Tuple[str, int]]:
    """The RET tenors and their rows, found by their labels as the service finds them (``Service._ret_layout``)."""
    from .service import RET_FIRST_ROW, RET_TENORS, Service
    consts = model.sheet("Forward").consts
    found: Dict[str, int] = {}
    for r in range(Service.RET_LABEL_ROWS[0], Service.RET_LABEL_ROWS[1] + 1):
        v = consts.get(parse_a1("V%d" % r))
        if isinstance(v, str) and v.strip().upper() in RET_TENORS and v.strip().upper() not in found:
            found[v.strip().upper()] = r
    return [(t, found.get(t, RET_FIRST_ROW + i)) for i, t in enumerate(RET_TENORS)]


def _rets_check(model: Model) -> None:
    _need_sheets(model, "Forward", "OIS_MAIN", "MASA", "Motor")
    _need_captions(model, (("OIS_MAIN", "O1", "SENARYOLAR"), ("OIS_MAIN", "P2", "Ad"), ("OIS_MAIN", "O3", "S1"),
                           ("OIS_MAIN", "O4", "S2"), ("OIS_MAIN", "O5", "S3"), ("Forward", "AA123", "ON"),
                           ("Forward", "AD122", "OIS"), ("Motor", "H3", "S1 TLREF"), ("Motor", "I3", "S1 ln G")))
    for _, _, src, _, _, _ in RETS_SCENARIOS:          # a scenario's discount factor depends on the days in $M$60 only
        transplant(_need_formula(model, "MASA", src, "$M$60"), {"$M$60": "$E%d" % RETS_FIRST})
    for rng in ("Motor!$I$4:$I$84", "Motor!$H$4:$H$84"):
        _need_formula(model, "MASA", "I63", rng)
    # the rule of an empty step that the reference repeats (OIS_MAIN!X10: the implied step on "ima yol") and the paths'
    # compounding (Motor!I5)
    _need_formula(model, "OIS_MAIN", "X10", "IF($B$3=1,N(R10),0)+$D$3")
    _need_formula(model, "Motor", "I5", "I4+(((C5-C4))*LN(1+(H4)/365)-((J5-J4))*((H4)/365)^2)")
    _need_formula(model, "Motor", "H4", "OIS_MAIN!$J$2")
    _need_formula(model, "Forward", "AD123", "OIS_MAIN!J2")
    labels = [lab for lab, _ in _rets_layout(model)]
    consts = model.sheet("Forward").consts
    missing = [lab for lab, r in _rets_layout(model) if str(consts.get(parse_a1("V%d" % r)) or "").strip().upper() != lab]
    if len(missing) == len(labels):
        raise ValueError("Forward sayfasında RET vadeleri bulunamadı")


def _tto_rets(model: Model) -> None:
    """The RET tenors' rates on the three scenario curves and on the reference (sheet ``EK_RET``)."""
    e = RETS_SHEET
    b = SheetBuilder(model, e)
    b.title("A1", "RET ADİL DEĞER · SENARYOLAR  ·  RET vadelerinin OIS · PPK senaryo eğrilerinden faizi (Adil değer sekmesinin 'Senaryo' seçimi)")
    b.head("A2", ["Eğri", "Nedir"])
    b.set("A3", RETS_MARKET, bold=True)
    b.note("B3", "masanın piyasa OIS mid'i (bootstrap: Borsa Swap spread'lerinin makinesi) - varsayılan, kural tabanlı RET'in bugünkü sayıları")
    for code, row, _, _, _, _ in RETS_SCENARIOS:
        b.set("A%d" % (row + 1), '="%s · "&OIS_MAIN!$P$%d' % (code, row), bold=True)
        b.note("B%d" % (row + 1), "OIS · PPK senaryosu %s: toplantı başına adımları PPK ima sekmesinde, adı SENARYOLAR tablosunda "
                                  "(MASA 'Tarih arası faiz' bloğunun iskonto faktörleri)" % code)
    b.set("A7", "Referans · ima yol", bold=True)
    b.note("B7", "hiç adımı olmayan senaryo (senaryo tabanı ima yol, kaydırma 0): TLREF ilk toplantıya kadar, sonra piyasanın ima "
                 "patikası. VİOP ve offshore tabanı senaryoda piyasa + (senaryo − referans) olur")
    # ---- the reference path: Motor's S1 columns (TLREF, ln G) for a scenario without steps (rows 30 … 110 = Motor 4 … 84)
    p0 = RETS_PATH
    b.head("A%d" % (p0 - 1), ["Motor satırı", "Toplantı", "Etkin gün", "Referans TLREF", "Referans ln G"])
    for k in range(81):
        r, m = p0 + k, 4 + k                                 # this row, Motor's row
        b.set("A%d" % r, float(m), fmt="0", align="center")
        b.set("B%d" % r, '=IF(Motor!$B%d="","",Motor!$B%d)' % (m, m), fmt=DATE)
        b.set("C%d" % r, "=Motor!$C%d" % m, fmt=INT0)
        if k == 0:
            b.set("D%d" % r, "=OIS_MAIN!$J$2", fmt="0.0000%")
            b.set("E%d" % r, 0.0, fmt="0.000000")
            continue
        o = m + 5                                            # OIS_MAIN's meeting row of Motor's row
        # OIS_MAIN!X10 on an empty step with "ima yol" and no shift: the implied step of the meeting (a meeting gone: none)
        b.set("D%d" % r, '=D%d+IF(AND(OIS_MAIN!$P%d<>"",OIS_MAIN!$P%d<OIS_MAIN!$B$2),0,N(OIS_MAIN!$R%d))/10000' % (r - 1, o, o, o),
              fmt="0.0000%")
        # Motor!I5's compounding on that path
        b.set("E%d" % r, "=E%d+(((Motor!$C%d-Motor!$C%d))*LN(1+(D%d)/365)-((Motor!$J%d-Motor!$J%d))*((D%d)/365)^2)"
              % (r - 1, m, m - 1, r - 1, m, m - 1, r - 1), fmt="0.000000")
    path = {"Motor!$I$4:$I$84": "%s!$E$%d:$E$%d" % (e, p0, p0 + 80), "Motor!$H$4:$H$84": "%s!$D$%d:$D$%d" % (e, p0, p0 + 80)}
    # ---- one row per RET tenor: its dates (the RET's own: from the USDTRY spot date, ON before it), the days from the OIS
    #      spot date, each curve's discount factors and its rate
    h0 = RETS_FIRST
    b.head("A%d" % (h0 - 1), ["Vade", "Başlangıç", "Bitiş", "Gün", "OIS spot → başl.", "OIS spot → bitiş"]
                             + ["DF %s %s" % (code, end) for code, _, _, _, _, _ in RETS_SCENARIOS for end in ("başl.", "bitiş")]
                             + ["DF ref başl.", "DF ref bitiş", "S1 %", "S2 %", "S3 %", "Referans %"])
    dfs = {code: formula_of(model, "MASA", src) for code, _, src, _, _, _ in RETS_SCENARIOS}
    curves = [(dfs[code], {}, c0, c1, rate) for code, _, _, c0, c1, rate in RETS_SCENARIOS] + \
             [(dfs["S1"], path) + RETS_REF]
    for k, (label, row) in enumerate(_rets_layout(model)):
        h = h0 + k
        b.set("A%d" % h, label, bold=True, align="center")
        if label == "ON":
            b.set("B%d" % h, '=IFERROR(Forward!$I$2-Forward!$U$%d,"")' % row, fmt=DATE)
            b.set("C%d" % h, "=Forward!$I$2", fmt=DATE)
        else:
            b.set("B%d" % h, "=Forward!$I$2", fmt=DATE)
            b.set("C%d" % h, '=IFERROR(Forward!$I$2+Forward!$U$%d,"")' % row, fmt=DATE)
        b.set("D%d" % h, '=IFERROR($C%d-$B%d,"")' % (h, h), fmt=INT0)
        b.set("E%d" % h, '=IFERROR($B%d-OIS_MAIN!$B$2,"")' % h, fmt=INT0)
        b.set("F%d" % h, '=IFERROR($C%d-OIS_MAIN!$B$2,"")' % h, fmt=INT0)
        for src, extra, c0, c1, rate in curves:
            for col, t in ((c0, "$E%d" % h), (c1, "$F%d" % h)):
                df = transplant(src, dict({"$M$60": t}, **extra))
                b.set("%s%d" % (col, h), "=IF(N(%s)<0,1+%s*(-%s)/360,%s)" % (t, RETS_ON, t, df), fmt="0.000000")
            b.set("%s%d" % (rate, h), '=IFERROR(($%s%d/$%s%d-1)*360/$D%d,"")' % (c0, h, c1, h, h), fmt="0.0000%")
    last = h0 + len(_rets_layout(model)) - 1
    b.note("A%d" % (last + 2), "DF = MASA 'Tarih arası faiz' bloğunun S1 / S2 / S3 iskonto faktörü (Motor'un PPK patikası) OIS spot'tan "
                               "tarihe; faiz = (DF başl. / DF bitiş − 1) · 360 / gün (ACT/360 basit): aynı iki tarihle Masa bloğunun "
                               "faizi. OIS spot'undan önceki gün(ler) OIS O/N'u (TLREF 365 → 360) ile.")
    b.note("A%d" % (last + 3), "Referans: aynı hesap, adımsız senaryonun patikasıyla (aşağıda). Adil değer sekmesinde senaryo seçilince "
                               "OIS tabanı senaryonun faizi; VİOP ve offshore tabanı piyasa + (senaryo − referans).")


# ---------------------------------------------------------------------------------------------- the curve between quotes
#: "Eğri interpolasyonu" (18.11.2026: "Ayarlardan da PPK basamak kısmını, tüm interpolasyonları değiştirebiliyor olmam
#: lazım"): each user chooses how the TRY curves are read between their quoted tenors - **Bootstrap (Murex)**, today's
#: curve and the default, or **PPK basamak** (tto/ppkcurve.py: TLREF flat between PPK meetings, the PPK solver's implied
#: path shifted flat between successive quoted maturities so that every quote comes back exactly).  The choice is the
#: user's own input (``INTERP_SHEET!B2``) - everybody else's numbers and the desk's (the shared calculation) stay on
#: Bootstrap.  The PPK curves come into the workbook at the source, as input cells the service fills from ppkcurve with
#: the curves read off the calculation on Bootstrap (so PPK never reads itself):
#:
#: * **Motor** - the par rate of each of the bootstrap's 42 nodes (Motor!F89:F130, the quotes linear in months) becomes
#:   ``IF(PPK, the PPK curve's par rate at that node, its own formula)``: the PPK discount factors at the nodes' days
#:   (``EK_INTERP!C11:C52``), turned into the par rates of Motor's own grid and day count, so that Motor's bootstrap gives
#:   back exactly those discount factors - its annuities, ln DFs, the quarterly copy every page reads, the per-quote
#:   bucket bumps (now around the PPK curve) and ``BOOT_PAR`` all follow, and a quoted tenor's par stays its quote.
#:   Between the nodes every reader interpolates as it does (ln DF linear in days): a broken date inside a quarter sees
#:   the PPK curve at the quarter's two nodes, not every meeting step - the exact daily PPK numbers stay in the PPK
#:   columns of OIS · PPK's FRA lists, MASA's broken-date block and Günlük İşlemler's FRA quote.
#: * **the offshore curve** (``OFF_GUN`` / ``OFF_LNDF`` / ``OFF_SL``): every one of its nodes is a quote whose discount
#:   factor PPK reprices exactly (its XCCY coupons fall on its nodes), so PPK can only show between them - on PPK the
#:   names read a node table of the PPK-shaped offshore curve (MPC ima + a flat basis between the offshore quotes) with a
#:   node at every meeting step and every quote (``EK_INTERP!I:K``), log-linear between them as before.
#: * the ASW book's curve of today (``ASW!BT65:DI65``) the same way, from its own sheet (``_asw_interp``).
#:
#: A user on PPK whose PPK curve cannot be made (no quotes, no MPC ima) is on Bootstrap and the sheet says so (C2).
INTERP_SHEET = "EK_INTERP"
INTERP_BOOT, INTERP_PPK = "Bootstrap (Murex)", "PPK basamak"
INTERP_CHOICES = (INTERP_BOOT, INTERP_PPK)
INTERP_MODE, INTERP_STATUS, INTERP_ON, INTERP_OFF_ON = "B2", "C2", "B3", "B4"
#: Motor's bootstrap nodes (0, 1, 2, 3, 6 … 120 months) and their rows on EK_INTERP (10 … 52: the node of Motor row r on
#: row r − 78); C the PPK discount factor (the service's), D Motor's accrual, E the PPK annuity, F the PPK par rate
INTERP_NODES = (88, 130)
INTERP_FIRST = 10
INTERP_SHIFT = INTERP_NODES[0] - INTERP_FIRST
#: the offshore node table: days, ln DF and slope (I, J, K) on rows OFF_FIRST … OFF_LAST - every row filled by the service
#: (the curve's nodes, then rows on its last segment far beyond the curve); the names' own ranges on Bootstrap
INTERP_OFF_FIRST, INTERP_OFF_ROWS = 10, 128
INTERP_OFF_LAST = INTERP_OFF_FIRST + INTERP_OFF_ROWS - 1
INTERP_OFF_COLS = {"OFF_GUN": "I", "OFF_LNDF": "J", "OFF_SL": "K"}
INTERP_OFF_RANGES = {"OFF_GUN": "Forward!$AK$124:$AK$143", "OFF_LNDF": "Forward!$AM$124:$AM$143",
                     "OFF_SL": "Forward!$AN$124:$AN$143"}
INTERP_NAME = "Eğri interpolasyonu"
#: the ASW book: its own EK_INTERP - the user's choice mirrored by the service (B2), and the PPK ln DF at each node of
#: today's curve (C11:C52; aswfx.NODES)
INTERP_ASW_NAME = "ASW eğri interpolasyonu"
#: "Eğri noktaları" (18.11.2026: "Bu enterpolasyon noktalarına Ayarlar'dan ekle / çıkar yapabilmeliyim ... PPK'lar her
#: zaman olmalı"): the desk's list of the points each TRY curve is built from (tto/curvepoints.py).  On the default list
#: (today's quotes) every reader reads the workbook's own formulas, as before; a curve whose list differs takes its
#: Bootstrap from the list (the PPK cells above are made from the list too):
#:
#: * ``LIST_OIS_ON`` / ``LIST_OFF_ON`` (N3 / N4) - 1 when the desk's OIS / offshore list differs from the default (the
#:   service writes them: shared); ``LIST_OIS_USE`` / ``LIST_OFF_USE`` (N5 / N6) - 1 when it does and its cells are all
#:   there (nested IFs: on the default list nothing reads the list's cells);
#: * N11:N52 - the list's par rate at each of Motor's nodes (Motor's own method on the list's points: linear in months,
#:   then its own bootstrap) - Motor's F reads it after the PPK branch: ``IF(PPK, …, IF(LIST_OIS_USE, N, own))``;
#: * Q:S rows 10 … 137 - the offshore curve's node table on the list (a node at every point, ln DF linear in days): the
#:   names read it after the PPK table;
#: * U10:U29 - the Bloomberg tickers of the list's ticker points (written once the desk confirmed the cost of the new
#:   subscription: an empty slot asks Bloomberg nothing), V:X their MID / BID / ASK, Y the rate (%: MID, else the middle).
LIST_OIS_ON, LIST_OFF_ON, LIST_OIS_USE, LIST_OFF_USE = "N3", "N4", "N5", "N6"
LIST_PAR_COL = "N"
LIST_OFF_COLS = {"OFF_GUN": "Q", "OFF_LNDF": "R", "OFF_SL": "S"}
LIST_TICKER_FIRST, LIST_TICKERS = 10, 20
LIST_TICKER_COL, LIST_VALUE_COL = "U", "Y"


def _fixed(addr: str) -> str:
    """``N3`` -> ``$N$3``."""
    m = re.match(r"^([A-Z]+)(\d+)$", addr)
    return "$%s$%s" % (m.group(1), m.group(2))


def interp_flag(count_range: str, count: int) -> str:
    """1 when the user is on PPK and the PPK cells counted are all there, else 0 - nested IFs, never AND: on Bootstrap the
    PPK cells are not even read, so whatever the service writes into them recomputes nothing of a Bootstrap user's."""
    return '=IF($B$2="%s",IF(COUNT(%s)=%d,1,0),0)' % (INTERP_PPK, count_range, count)


def _interp_check(model: Model) -> None:
    """Motor's nodes bootstrap the par rates of column F as this addition gives them back (G from F, H the annuity, D the
    accrual: 1M-3M one period, then quarterly from the 3M node on); the offshore names are the curve's own ranges."""
    _need_sheets(model, "Motor", "Forward", "OIS_MAIN")
    first, last = INTERP_NODES
    if model.sheet("Motor").consts.get(parse_a1("G%d" % first)) != 1.0:
        raise ValueError("Motor!G%d 1 değil" % first)
    for r in range(first + 1, last + 1):
        _need_formula(model, "Motor", "F%d" % r, "$B$306:$B$321")
        g, h, d = (formula_of(model, "Motor", "%s%d" % (c, r)).replace(" ", "") for c in "GHD")
        if r <= first + 3:
            ok = (g == "1/(1+F%d*D%d)" % (r, r) and h == "D%d*G%d" % (r, r) and d == "C%d/365" % r)
        else:
            ok = (g == "(1-F%d*H%d)/(1+F%d*D%d)" % (r, r - 1, r, r) and h == "H%d+D%d*G%d" % (r - 1, r, r)
                  and d == "(B%d-B%d)/365" % (r, r - 1))
        if not ok:
            raise ValueError("Motor!G%d / H%d / D%d beklenen bootstrap formülü değil" % (r, r, r))
        _need_formula(model, "Motor", "I%d" % r, "LN(G%d)" % r)
    from .xl.unparse import to_a1
    for name, rng in INTERP_OFF_RANGES.items():
        tpl = model.names.get(name)
        if tpl is None:
            raise ValueError("%s adı yok" % name)
        if to_a1(tpl, 1, 1).replace("'", "") != rng:
            raise ValueError("%s beklenen aralık değil (%s)" % (name, rng))


def _tto_interp(model: Model) -> None:
    """The curve switch of the TRY workbook (``INTERP_SHEET``): the user's choice, the PPK cells the service fills, the
    PPK par rates of Motor's nodes, Motor's par rates and the offshore names that follow the choice."""
    e = INTERP_SHEET
    b = SheetBuilder(model, e)
    first, last = INTERP_NODES
    nodes = last - first                                       # (the nodes after the spot: 42)
    k0, k1 = first + 1 - INTERP_SHIFT, last - INTERP_SHIFT     # their rows here (11 … 52)
    b.title("A1", "EĞRİ İNTERPOLASYONU  ·  kotalı vadeler arasında TRY eğrileri: Bootstrap (Murex) ya da PPK basamak "
                  "(Ayarlar → Eğri interpolasyonu; kişisel)")
    b.set("A2", INTERP_NAME, bold=True)
    b.input(INTERP_MODE, INTERP_BOOT, align="center")
    b.dropdown(INTERP_MODE, list(INTERP_CHOICES))
    b.set(INTERP_ON, interp_flag("$C$%d:$C$%d" % (k0, k1), nodes), fmt="0", align="center")
    b.set(INTERP_OFF_ON, interp_flag("$I$%d:$I$%d" % (INTERP_OFF_FIRST, INTERP_OFF_LAST), INTERP_OFF_ROWS), fmt="0", align="center")
    b.set(INTERP_STATUS, '=IF($B$3=1,"PPK basamak: TLREF toplantılar arasında sabit, kotalara aynen oturur"&IF($B$4=1,"",'
                         '" (offshore eğri kurulamadı: offshore Bootstrap)"),IF($B$2="%s","PPK basamak seçili ama PPK eğrisi '
                         'kurulamadı (kota ya da MPC ima yok): Bootstrap kullanılıyor","%s: bugünkü eğri, Murex\'in MTM\'i"))'
                         '&IF(OR(%s=1,%s=1)," · eğri noktaları masanın listesinden (Ayarlar → Eğri noktaları)","")'
                         % (INTERP_PPK, INTERP_BOOT, _fixed(LIST_OIS_ON), _fixed(LIST_OFF_ON)), bold=True, color=NOTE_COLOR)
    b.set("A3", "OIS düğümleri PPK'da (1/0)", bold=True)
    b.set("A4", "Offshore düğümleri PPK'da (1/0)", bold=True)
    b.note("A5", "Bootstrap: her okuyucu bugünkü gibi - düğümlerde Motor'un bootstrap'ı, aralarında ln DF günlere göre doğrusal. "
                 "PPK basamak: Motor'un 42 düğümünün par faizi PPK eğrisinin o düğümdeki par faizi olur (C sütunundaki iskonto "
                 "faktörlerinden, Motor'un kendi takvimi ve gün sayımıyla): Motor'un bootstrap'ı bu iskonto faktörlerini aynen "
                 "verir, kotalı vadelerin par'ı kotasıdır. Düğümler arası yine ln DF doğrusal: çeyrek içindeki kırık bir tarih "
                 "PPK eğrisini çeyreğin iki düğümünde görür, her toplantı basamağını değil - günlük PPK değerleri PPK sütunlarında.")
    b.note("A6", "Offshore eğri (OFF_GUN / OFF_LNDF / OFF_SL): düğümlerinin hepsi kota, PPK onlarda Bootstrap'la aynı - PPK'da adlar "
                 "I:K tablosunu okur: her toplantı basamağında ve her kotada düğüm (MPC ima + offshore kotalar arasında sabit baz). "
                 "C ve I:K sütunlarını dashboard doldurur (ortak, eğrinin girdileri değişince yeniden); MTM / kapanış kayıtları "
                 "ve kullanıcısız hesaplar (alarmlar, quant, tarihçe) Bootstrap'ta.")
    b.head("A%d" % (INTERP_FIRST - 1), ["Düğüm", "Gün", "DF PPK", "τ (Motor)", "Annuity PPK", "Par PPK"])
    for r in range(first, last + 1):
        k = r - INTERP_SHIFT
        b.set("A%d" % k, "=Motor!$A$%d" % r, bold=True, align="center")
        b.set("B%d" % k, "=Motor!$C$%d" % r, fmt=INT0)
        if r == first:
            b.set("C%d" % k, 1.0, fmt="0.000000000")              # (the spot: 1 both ways)
            b.set("E%d" % k, 0.0, fmt="0.000000")
            continue
        b.set("C%d" % k, None, fmt="0.000000000")                  # (the service's)
        b.set("D%d" % k, "=Motor!$D$%d" % r, fmt="0.000000")
        if r <= first + 3:
            # 1M - 3M: one period, simple ACT/365 (Motor: G = 1/(1 + F·D), H = D·G)
            b.set("E%d" % k, "=$D%d*$C%d" % (k, k), fmt="0.000000")
            b.set("F%d" % k, '=IF(ISNUMBER($C%d),(1/$C%d-1)/$D%d,"")' % (k, k, k), fmt="0.0000%")
        else:
            # quarterly par on Motor's grid (G = (1 − F·H_prev)/(1 + F·D), H = H_prev + D·G): F = (1 − DF)/(H_prev + D·DF)
            b.set("E%d" % k, "=$E%d+$D%d*$C%d" % (k - 1, k, k), fmt="0.000000")
            b.set("F%d" % k, '=IF(ISNUMBER($C%d),(1-$C%d)/$E%d,"")' % (k, k, k), fmt="0.0000%")
    b.head("H%d" % (INTERP_OFF_FIRST - 1), [None, "Offshore gün", "ln DF PPK", "Eğim"])
    for r in range(INTERP_OFF_FIRST, INTERP_OFF_LAST + 1):
        b.set("I%d" % r, None, fmt=INT0)
        b.set("J%d" % r, None, fmt="0.000000000")
        b.set("K%d" % r, None, fmt="0.0000000000")
    # ---- the desk's list of points (Ayarlar → Eğri noktaları): its flags, Motor's node pars and the offshore node table
    #      on the list, the Bloomberg tickers of its ticker points
    pc = LIST_PAR_COL
    gun, ln, sl = (LIST_OFF_COLS[k] for k in ("OFF_GUN", "OFF_LNDF", "OFF_SL"))
    b.title("M2", "EĞRİ NOKTALARI  ·  masanın listesi (Ayarlar → Eğri noktaları; dashboard yazar): varsayılandayken bu "
                  "hücreleri hiçbir formül okumaz")
    b.set("M3", "OIS listesi varsayılandan farklı (1/0)", bold=True)
    b.set("M4", "Offshore listesi varsayılandan farklı (1/0)", bold=True)
    b.set("M5", "OIS düğümleri listeden (1/0)", bold=True)
    b.set("M6", "Offshore düğümleri listeden (1/0)", bold=True)
    b.set(LIST_OIS_ON, 0.0, fmt="0", align="center")              # (the service's)
    b.set(LIST_OFF_ON, 0.0, fmt="0", align="center")
    b.set(LIST_OIS_USE, '=IF(%s=1,IF(COUNT($%s$%d:$%s$%d)=%d,1,0),0)' % (_fixed(LIST_OIS_ON), pc, k0, pc, k1, nodes),
          fmt="0", align="center")
    b.set(LIST_OFF_USE, '=IF(%s=1,IF(COUNT($%s$%d:$%s$%d)=%d,1,0),0)' % (_fixed(LIST_OFF_ON), gun, INTERP_OFF_FIRST, gun,
                                                                        INTERP_OFF_LAST, INTERP_OFF_ROWS),
          fmt="0", align="center")
    b.note("M7", "Liste farklıyken Bootstrap listeden kurulur: OIS'te Motor'un yöntemiyle (noktaların par faizi aylara göre doğrusal, "
                 "Motor'un düğümlerinde bootstrap - N sütunu Motor'un F'sine girer), offshore'da her nokta bir düğüm (Q:S, ln DF "
                 "günlere göre doğrusal). PPK basamak (C, I:K) listedeki noktalara kalibre edilir.")
    b.head("M%d" % (INTERP_FIRST - 1), ["Düğüm", "Par liste"])
    for r in range(first, last + 1):
        k = r - INTERP_SHIFT
        b.set("M%d" % k, "=$A$%d" % k, bold=True, align="center")
        b.set("%s%d" % (pc, k), None, fmt="0.0000%")               # (the service's; none at the spot)
    b.head("P%d" % (INTERP_OFF_FIRST - 1), [None, "Offshore gün (liste)", "ln DF liste", "Eğim liste"])
    for r in range(INTERP_OFF_FIRST, INTERP_OFF_LAST + 1):
        b.set("%s%d" % (gun, r), None, fmt=INT0)
        b.set("%s%d" % (ln, r), None, fmt="0.000000000")
        b.set("%s%d" % (sl, r), None, fmt="0.0000000000")
    tc = LIST_TICKER_COL
    b.head("%s%d" % (tc, LIST_TICKER_FIRST - 1), ["Ticker (liste)", "MID", "BID", "ASK", "Oran %"])
    for r in range(LIST_TICKER_FIRST, LIST_TICKER_FIRST + LIST_TICKERS):
        b.set("%s%d" % (tc, r), None)                               # (the service's: a confirmed ticker point's)
        for col, field in (("V", "MID"), ("W", "BID"), ("X", "ASK")):
            b.set("%s%d" % (col, r), '=IF(LEN(TRIM($%s%d&""))<2,"",_xll.BDP(TRIM($%s%d),"%s"))' % (tc, r, tc, r, field), fmt="0.0000")
        b.set("%s%d" % (LIST_VALUE_COL, r), '=IF(ISNUMBER($V%d),$V%d,IF(AND(ISNUMBER($W%d),ISNUMBER($X%d)),($W%d+$X%d)/2,""))'
              % (r, r, r, r, r, r), fmt="0.0000", bold=True)
    # ---- Motor's par rates follow the choice - and the list ...
    m = SheetBuilder(model, "Motor")
    for r in range(first + 1, last + 1):
        k = r - INTERP_SHIFT
        m.patch("F%d" % r, "=IF(%s!$B$3=1,%s!$F$%d,IF(%s!%s=1,%s!$%s$%d,%s))" % (
            e, e, k, e, _fixed(LIST_OIS_USE), e, pc, k, formula_of(model, "Motor", "F%d" % r)))
    # ---- ... and so do the offshore curve's names (the PPK node table, the list's, or their own ranges as before)
    for name, col in INTERP_OFF_COLS.items():
        own = LIST_OFF_COLS[name]
        text = "IF(%s!$B$4=1,%s!$%s$%d:$%s$%d,IF(%s!%s=1,%s!$%s$%d:$%s$%d,%s))" % (
            e, e, col, INTERP_OFF_FIRST, col, INTERP_OFF_LAST, e, _fixed(LIST_OFF_USE), e, own, INTERP_OFF_FIRST, own,
            INTERP_OFF_LAST, INTERP_OFF_RANGES[name])
        model.names[name] = to_template(text, 1, 1)


def _asw_interp_check(model: Model) -> None:
    """The ASW book's curve of today (row ``aswfx.ROW``): ln DF 0 at the spot, then one period up to 3M and the quarterly
    bootstrap from 6M - as aswfx reads it."""
    _need_sheets(model, "ASW")
    row, d0, l0 = aswfx.ROW, aswfx.DAY_COL, aswfx.LN_COL
    if model.sheet("ASW").consts.get(row * COLS + l0) != 0.0:
        raise ValueError("ASW!%s%d 0 değil" % (index_to_col(l0), row))
    for i, mo in enumerate(aswfx.NODES[1:], 1):
        addr = "%s%d" % (index_to_col(l0 + i), row)
        text = _need_formula(model, "ASW", addr, "LN(").replace(" ", "")
        day = "%s%d" % (index_to_col(d0 + i), row)
        if day not in text:
            raise ValueError("ASW!%s düğüm gününü (%s) okumuyor" % (addr, day))
        _need_formula(model, "ASW", day, "EDATE($T%d,%d)" % (row, mo))


def _asw_interp(model: Model) -> None:
    """The ASW book's side of the curve switch: its own ``INTERP_SHEET`` (the user's choice as the service mirrors it, the
    PPK ln DF of today's nodes the service fills) and today's ln DF nodes that follow it."""
    e = INTERP_SHEET
    b = SheetBuilder(model, e)
    row, d0, l0 = aswfx.ROW, aswfx.DAY_COL, aswfx.LN_COL
    n = len(aswfx.NODES)
    b.title("A1", "EĞRİ İNTERPOLASYONU  ·  bugünkü OIS eğrisi (ASW satır %d): Bootstrap ya da PPK basamak - TRY kitabındaki "
                  "kişisel ayarın aynısı (Ayarlar → Eğri interpolasyonu)" % row)
    b.set("A2", INTERP_NAME, bold=True)
    b.input(INTERP_MODE, INTERP_BOOT, align="center")
    b.set(INTERP_ON, interp_flag("$C$%d:$C$%d" % (INTERP_FIRST + 1, INTERP_FIRST + n - 1), n - 1), fmt="0", align="center")
    b.note("A4", "B2 kullanıcının TRY kitabındaki seçimidir (dashboard yazar). PPK'da ASW!%s%d:%s%d (ln DF) C sütununu okur: TRY "
                 "kitabının MPC ima patikası bu kitabın kotalarına (C%d:R%d) ve düğüm günlerine kalibre edilir. Geçmiş satırları "
                 "Bootstrap'ta kalır." % (index_to_col(l0 + 1), row, index_to_col(l0 + n - 1), row, row, row))
    b.head("A%d" % (INTERP_FIRST - 1), ["Ay", "Gün", "ln DF PPK"])
    for i, mo in enumerate(aswfx.NODES):
        k = INTERP_FIRST + i
        b.set("A%d" % k, float(mo), fmt="0", align="center")
        b.set("B%d" % k, "=ASW!$%s$%d" % (index_to_col(d0 + i), row), fmt=INT0)
        b.set("C%d" % k, 0.0 if i == 0 else None, fmt="0.000000000")
    a = SheetBuilder(model, "ASW")
    for i in range(1, n):
        addr = "%s%d" % (index_to_col(l0 + i), row)
        a.patch(addr, "=IF(%s!$B$3=1,%s!$C$%d,%s)" % (e, e, INTERP_FIRST + i, formula_of(model, "ASW", addr)))


_BUILDERS: Dict[str, Tuple[Tuple[str, Callable[[Model], None], Callable[[Model], None]], ...]] = {
    "borsa": (("Borsa O/N", _borsa_check, _borsa), ("Borsa süzgeç", _borsa_filter_check, _borsa_filter),
              ("Borsa T+1 valörü", _borsa_t1_check, _borsa_t1)),
    "asw": ((FXC_SHEET, _asw_fx_check, _asw_fx), (ASW_HIST_NAME, _asw_hist_check, _asw_hist),
            (INTERP_ASW_NAME, _asw_interp_check, _asw_interp)),
    # (the holiday sheet and the FX value dates first: the forward tables below date their tenors on its calendars)
    "tto": ((HOL_SHEET, _holidays_check, _tto_holidays), (FX_DATE_NAME, _fx_dates_check, _tto_fx_dates),
            (OIS_SPOT_NAME, _ois_spot_check, _tto_ois_spot),
            (FWD_SHEET, _forward_check, _tto_forward), (XAU_SHEET, _gold_check, _tto_gold),
            (VH_SHEET, _viop_hist_check, _tto_viop_history), ("EK_FWD vade faizleri", _fwd_rates_check, _tto_fwd_rates),
            ("EK_FWD EURTRY", _fwd_eur_check, _tto_fwd_eur),
            (SRC_SHEET, _sources_check, _tto_sources), ("Bulk Bond satırları", _bulk_bond_check, _tto_bulk_bond),
            (BULK_SHEET, _bulk_forward_check, _tto_bulk_forward),
            ("Forward puandan faize", _fwd_back_check, _tto_fwd_back),
            (PPK_SHEET, _ppk_back_check, _tto_ppk_back), (FRA_LEG_NAME, _fra_leg_check, _tto_fra_leg),
            ("DİBS RV canlı kota", _rv_quotes_check, _tto_rv_quotes), (LIVE_SHEET, _dibs_live_check, _tto_dibs_live),
            (UNI_SHEET, _universe_check, _tto_universe), ("Tüm Kâğıtlar canlı kota", _universe_quotes_check, _tto_universe_quotes),
            ("DİBS RV FRN", _rv_frn_check, _tto_rv_frn),
            (CARRY_SHEET, _carry_check, _tto_carry),
            ("Motor gün sayıları", _desk_days_check, _tto_desk_days), ("DV01 pozisyonu sıfır", _dv01_zero_check, _tto_dv01_zero),
            ("VİOP matris DV01'leri", _viop_dv01_check, _tto_viop_dv01),
            (AUC_SHEET, _auction_check, _tto_auction), (EMPTY_NAME, _empty_check, _tto_empty),
            (MARKET_NAME, _market_check, _tto_market), (VIOP_ROLL_NAME, _viop_roll_check, _tto_viop_roll),
            (OIS_SPREAD_NAME, _ois_spread_check, _tto_ois_spread),
            # (the bulk date-to-date rates; the target type "Fiyat" before the FRA's curve, which wraps its target rate)
            (TARIH_SHEET, _tarih_check, _tto_tarih), (VPRICE_NAME, _viop_price_check, _tto_viop_price),
            (VFRA_SHEET, _viop_fra_check, _tto_viop_fra),
            (RETS_SHEET, _rets_check, _tto_rets), (INTERP_NAME, _interp_check, _tto_interp)),
    "sofr": ((EMPTY_NAME, _usd_empty_check, _usd_empty), (FOMC_BACK_NAME, _fomc_back_check, _usd_fomc_back)),
}


__all__ = ["SheetBuilder", "apply", "formula_of", "recorded_value", "transplant", "lin", "overnight"]
