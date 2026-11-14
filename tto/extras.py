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
* ``bu``      (Borsa workbook) O/N equivalents of the implied TRY rates of the BIST swap quotes
* ``Sheet2``  (Borsa workbook) the list of quoted maturities keeps only quotes with an order behind them

The last one changes formulas of the workbook itself.  The workbook lists a maturity when its bid or ask size
"is a number"; over the API Bloomberg answers a size of 0 - and an old price, the same on both sides - for a
maturity nobody is quoting, where Excel's real-time link shows "#N/A N/A".  Listed by the workbook's rule, the
page was full of quotes that do not exist.

Two more change formulas of the TRY workbook, each for a reason given where it is done:

* ``EK_CARRY``  the carry of the Carry & Roll sheet along a TLREF path of one's choice (the Motor sheet's carry
                engine is pointed at it; the S1 cells it compounded stay for the OIS sheet's own pricing)
* ``Motor``     the curve's nodes count their days with the desk's calendar instead of Bloomberg's maturities
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .xl.model import COLS, Model, Sheet, parse_a1, parse_range
from .xl.tokenizer import index_to_col, to_template

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


def overnight(rate: str, days: str) -> str:
    """O/N equivalent (360) of a simple ACT/360 rate over ``days``: 360·((1 + r·g/360)^(1/g) − 1)."""
    return ('IF(AND(ISNUMBER(%(r)s),ISNUMBER(%(d)s),N(%(d)s)>0),360*((1+%(r)s*%(d)s/360)^(1/%(d)s)-1),"")'
            % {"r": rate, "d": days})


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


# ---------------------------------------------------------------------------------------------- TRY workbook
FWD_SHEET = "EK_FWD"
FWD_ALL = 4                              # the "Tümü" row: general spreads (bid, ask) and the spot quotes
FWD_ROWS = (5, 14)                       # 1M, 2M, 3M, 6M, 9M, 12M and four free dates
FWD_BACK = 15                            # rows of the "points -> spread" table = rows of the matrix + 15
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
    _need_formula(model, "Forward", "I2", "SETTLE_DT")
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
            b.input("B%d" % r, "=WORKDAY(EDATE(Forward!$I$2,%d)-1,1,Motor!$A$361:$A$523)" % months[r], fmt=DATE)
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
#: the spot date of a pair (Bloomberg's SETTLE_DT, or the date typed there) - a date even when it comes as a text
FR_SPOT = {pair: "IFERROR(DATE(YEAR(%(d)s),MONTH(%(d)s),DAY(%(d)s)),%(d)s)" % {"d": d}
           for pair, d in (("USDTRY", "Forward!$I$2"), ("EURTRY", "Forward!$K$2"))}
#: the OIS curve of a pair's major currency (days from the pair's spot date, mid %, nodes), as the sheet reads it
FR_MAJOR = {"USDTRY": ("Forward!$U$7:$U$26", "Forward!$X$7:$X$26", 20),
            "EURTRY": ("Forward!$AA$7:$AA$26", "Forward!$AD$7:$AD$26", 20)}
FR_REACH = 31          # a curve is read up to a month past its last node; further out it gives no rate (rather than a flat one)
#: the usual tenors from the USDTRY spot date: days, or months (then the next business day)
FR_TENORS = (("1W", 7, 0), ("2W", 14, 0), ("1M", 0, 1), ("2M", 0, 2), ("3M", 0, 3), ("6M", 0, 6), ("9M", 0, 9), ("1Y", 0, 12),
             ("18M", 0, 18), ("2Y", 0, 24))
FR_HOLIDAYS = "Motor!$A$361:$A$523"

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
    dates = [("Valör", "=Forward!$D$2")]
    for label, n_days, months in FR_TENORS:
        if months:
            dates.append((label, "=WORKDAY(EDATE(%s,%d)-1,1,%s)" % (spot, months, FR_HOLIDAYS)))
        else:
            dates.append((label, "=WORKDAY(%s+%d-1,1,%s)" % (spot, n_days, FR_HOLIDAYS)))
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
    b.note("A%d" % (h + 1 + len(dates)), "Gün ve vadeler USDTRY spot valöründen (ay vadeleri sonraki iş gününe). Faizler eğrilerin mid'i, Forward "
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
    _need_formula(model, "Forward", "K2", "SETTLE_DT")
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
    for r in range(r1, r2 + 1):
        f = {"r": r, "g": g, "c": c, "h": h}
        if r in months:
            b.set("A%d" % r, "%dM" % months[r], bold=True, align="center")
            b.input("B%d" % r, "=WORKDAY(EDATE(%s,%d)-1,1,%s)" % (spot, months[r], FR_HOLIDAYS), fmt=DATE)
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
                             "RET bid/ask faiziyle çıkan puana fark.")

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
# the tenors of the ASW sheet's OIS curve (ASW!C64:R64) and the offshore ticker of each: the FX swap implied yields
# up to 18 months, the cross currency swaps after
FXC_ROOTS = ("TRYI1M", "TRYI2M", "TRYI3M", "TRYI6M", "TRYI9M", "TRYI12M", "TRYI18M", "TRYSAQ2", "TRYSAQ3", "TRYSAQ4",
             "TRYSAQ5", "TRYSAQ6", "TRYSAQ7", "TRYSAQ8", "TRYSAQ9", "TRYSAQ10")


def _asw_fx_check(model: Model) -> None:
    """The ASW sheet's curve: the OIS quotes of today in C65:R65 (16 tenors) that its discount factors are built from."""
    _need_sheets(model, "ASW")
    _need_formula(model, "ASW", "BT65", "$C65")
    for k in range(16):
        col = index_to_col(3 + k)                      # C .. R
        _need_formula(model, "ASW", "%s65" % col, 'BDP(%s$63&" GFOF Curncy","MID")' % col)


def _asw_fx(model: Model) -> None:
    """The TRY curve the FX swaps imply, tenor by tenor where the ASW sheet's OIS curve has its quotes - the
    second curve of the ASW table: the dashboard prices every bond off it as well (the sheet's own formulas, the
    OIS quotes of C65:R65 swapped for these) and shows ASW against FX swaps next to ASW against OIS.

    Each tenor: the ticker root (typed over freely), the first of the two pricing sources that has a price - MID,
    else the middle of bid and ask -, and the OIS quote of the same tenor."""
    b = SheetBuilder(model, FXC_SHEET)
    b.title("A1", "FX SWAP İMA TRY EĞRİSİ  ·  ASW'nin ikinci eğrisi: offshore TRY faizi (18 aya kadar FX swap ima, sonra XCCY)")
    b.row("A3", ["Kaynaklar (sırayla)"], bold=True)
    b.input("B3", "ICPL")
    b.input("C3", "BGN")
    b.note("D3", "İlk fiyat veren kaynak kullanılır: önce MID, yoksa bid–ask ortası. Ticker kökü sarı hücrede (yalnız kök: TRYI1M, TRYSAQ2 …).")
    b.head("A5", ["Vade", "Ticker kökü", "Kullanılan ticker", "FX ima (%)", "OIS (%)", "FX − OIS (bp)", "1. kaynak", "2. kaynak"])
    for k, root in enumerate(FXC_ROOTS):
        r = FXC_FIRST + k
        col = index_to_col(3 + k)
        f = {"r": r, "col": col}
        b.set("A%d" % r, "=ASW!%s$64" % col, bold=True, align="center")
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
    b.note("A%d" % (FXC_FIRST + len(FXC_ROOTS) + 1),
           "ASW tablosundaki 'ASW FX' sütunu: kâğıt, OIS kotaları yerine bu faizlerle kurulan eğriyle (sayfanın kendi iskonto ve annuity formülleriyle) "
           "fiyatlanır. Fiyatı olmayan vadede OIS kotası kullanılır. FX ima faizleri basit TRY para piyasası faizi, XCCY'ler TRY sabit / USD değişken "
           "swap faizidir; OIS gibi par faiz olarak kullanılır.")


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


def _tto_bulk_forward(model: Model) -> None:
    """The Forward sheet's bulk forward table with 100 rows instead of 20 - the sheet's own formulas, row by row,
    the curves and spots still read from the Forward sheet.  The first 20 value dates and manual TRY rates are
    the Forward sheet's (typed over freely); the page shows as many rows as are filled, one more on demand."""
    b = SheetBuilder(model, BULK_SHEET)
    b.title("B1", "TOPLU FORWARD FİYATLAMA  ·  100 valöre kadar (B sütununa valör tarihi; TRY faizi: manuel boşsa RET mid)")
    heads = [model.sheet("Forward").consts.get(parse_a1("%s143" % c)) for c in "BCDEFGHIJKLMNOPQ"]
    b.head("B4", [h if isinstance(h, str) else None for h in heads])
    templates = {}
    for col in BULK_COLS:
        text = formula_of(model, "Forward", "%s144" % col)
        templates[col] = _ABSOLUTE.sub(lambda m: "Forward!" + m.group(0), text)       # the curves stay on the Forward sheet
    for k in range(BULK_ROWS):
        r = BULK_FIRST + k
        src = 144 + k
        if k < 20:
            b.input("B%d" % r, '=IF(ISNUMBER(Forward!$B$%d),Forward!$B$%d,"")' % (src, src), fmt=DATE)
            b.input("L%d" % r, '=IF(ISNUMBER(Forward!$L$%d),Forward!$L$%d,"")' % (src, src), fmt="0.0000")
        else:
            b.input("B%d" % r, None, fmt=DATE)
            b.input("L%d" % r, None, fmt="0.0000")
        for col in BULK_COLS:
            body = re.sub(r"(?<![A-Za-z0-9_$!])(\$?[A-Z]{1,3})144(?!\d)", lambda m: "%s%d" % (m.group(1), r), templates[col])
            b.set("%s%d" % (col, r), "=" + body, like=None, fmt=_BULK_FMT.get(col, NUM4))
    b.note("B%d" % (BULK_FIRST + BULK_ROWS + 1),
           "Forward sayfasındaki toplu fiyatlama tablosunun aynı formülleri, 100 satır: eğriler, spot ve faizler Forward sayfasından. İlk 20 "
           "satırın valörü ve manuel TRY faizi Forward sayfasındakidir; üzerine yazabilir, silerek ona dönebilirsiniz.")


_BULK_FMT = {"C": INT0, "D": "0.000", "E": "0.000", "F": "0.000", "G": "0.000", "H": "0.000", "J": "0.000", "K": "0.000",
             "N": NUM4, "O": INT0, "P": NUM4, "Q": INT0}


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
    out["last_help"] = index_to_col(at + 4)
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
           + ["Ek bid", "Ek ask", "Orta T0", "Orta T1", "Orta T2"])

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
                         'IF({rv}$D{r}="E"," TÜFE",IF({rv}$D{r}="B"," Bono",""))),$A{r}))'.format(r=r, rv=rv), bold=True)
        b.set("C%d" % r, '=IF($A{r}="","",{rv}$D{r})'.format(r=r, rv=rv), align="center")
        b.set("D%d" % r, '=IF($A{r}="","",{rv}$E{r})'.format(r=r, rv=rv), fmt=DATE)
        b.set("E%d" % r, '=IF($A{r}="","",{rv}$G{r})'.format(r=r, rv=rv), fmt="0.00%")
        for k, g in enumerate(L["groups"]):
            sec = "$%s%d" % (L["sec"][k], r)
            raw = L["raw"][k]
            src_cell = "$%s$2" % g["src"][:-1]
            b.set("%s%d" % (L["sec"][k], r), security(src_cell, g["default"], r))
            same = 'AND($A{r}<>"",{s}={rv}$BS{r})'.format(r=r, s=source(src_cell, g["default"]), rv=rv)
            own = {"bid": "$K", "ask": "$L", "last": "$AS", "date": "$I"}
            fields = {"bid": "PX_BID", "ask": "PX_ASK", "last": "LAST_PRICE", "date": "LAST_TRADE_DATE"}
            for f in ("bid", "ask", "last", "date"):
                b.set("%s%d" % (raw[f], r), '=IF($A{r}="","",IF({same},{rv}{own}{r},_xll.BDP({sec},"{fld}")))'.format(
                    r=r, same=same, rv=rv, own=own[f], sec=sec, fld=fields[f]))
            b.set("%s%d" % (raw["vol"], r), '=IF($A{r}="","",_xll.BDP({sec},"VOLUME"))'.format(r=r, sec=sec))
            b.set("%s%d" % (raw["acc"], r),
                  '=IF($A{r}="","",IF({rv}$D{r}="B",0,IF(AND({same},${d}=({rv}$DC{r})),{rv}$CW{r},'
                  '_xll.BDP({sec},"INT_ACC","SETTLE_DT",${d}))))'.format(r=r, rv=rv, same=same, sec=sec,
                                                                       d=g["date"][:-1] + "$2"))
            b.set("%s%d" % (g["bid"], r), clean("%s%d" % (raw["bid"], r)), fmt="0.000")
            b.set("%s%d" % (g["ask"], r), clean("%s%d" % (raw["ask"], r)), fmt="0.000")
            b.set("%s%d" % (g["last"], r), clean("%s%d" % (raw["last"], r)), fmt="0.000", bold=True)
            d = "%s%d" % (raw["date"], r)
            b.set("%s%d" % (g["when"], r),
                  '=IFERROR(IF(ISNUMBER({d}),IF({d}>0,{d},""),IF(TRIM({d}&"")="","",DATE(VALUE(RIGHT({d},4)),'
                  'VALUE(MID({d},FIND(".",{d})+1,FIND(".",{d},FIND(".",{d})+1)-FIND(".",{d})-1)),VALUE(LEFT({d},FIND(".",{d})-1))))),"")'
                  .format(d=d), fmt=DATE)
            b.set("%s%d" % (g["vol"], r), clean("%s%d" % (raw["vol"], r)), fmt=INT0)
            b.set("%s%d" % (L["mid"][k], r), '=IF(AND(ISNUMBER({b}{r}),ISNUMBER({a}{r})),({b}{r}+{a}{r})/2,"")'.format(
                b=g["bid"], a=g["ask"], r=r), fmt="0.0000")
        # one more source
        b.set("%s%d" % (L["sec_extra"], r), security("$%s$2" % LIVE_EXTRA, "BGN", r))
        ex_bid, ex_ask = L["raw_extra"]["bid"], L["raw_extra"]["ask"]
        b.set("%s%d" % (ex_bid, r), '=IF($A{r}="","",_xll.BDP(${s}{r},"PX_BID"))'.format(r=r, s=L["sec_extra"]))
        b.set("%s%d" % (ex_ask, r), '=IF($A{r}="","",_xll.BDP(${s}{r},"PX_ASK"))'.format(r=r, s=L["sec_extra"]))
        e1 = index_to_col(_col(LIVE_EXTRA) + 1)
        b.set("%s%d" % (LIVE_EXTRA, r), clean("%s%d" % (ex_bid, r)), fmt="0.000")
        b.set("%s%d" % (e1, r), clean("%s%d" % (ex_ask, r)), fmt="0.000")
        # the overnight repo the dirty prices of two value dates imply - only from prices of the same day (the last
        # trades of both value dates on one day: a T0 price of two weeks ago against today's T1 implies nothing);
        # none for a CPI linker (its TL price moves with the index ratio of each value date)
        for col, (k0, k1) in ((w, (0, 1)), (x, (1, 2))):
            g0, g1 = L["groups"][k0], L["groups"][k1]
            m0, m1 = "%s%d" % (L["mid"][k0], r), "%s%d" % (L["mid"][k1], r)
            a0, a1 = "%s%d" % (L["raw"][k0]["acc"], r), "%s%d" % (L["raw"][k1]["acc"], r)
            d0, d1 = "$%s$2" % g0["date"][:-1], "$%s$2" % g1["date"][:-1]
            t0, t1 = "%s%d" % (g0["when"], r), "%s%d" % (g1["when"], r)
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
           "eski bir T0 fiyatıyla bugünün T1 fiyatı bir repo söylemez.")
    b.sheet.freeze = [4, 2]


def _col(letter: str) -> int:
    from .xl.tokenizer import col_to_index
    return col_to_index(letter)


# ---------------------------------------------------------------------------------------------- every bond
UNI_SHEET = "EK_EVREN"
UNI_OWN = (6, 20)                      # the bonds the desk adds that the list does not have (a new issue): ISIN typed
UNI_FIRST = 22                         # the desk's list of TRY government bonds from here, kind by kind
#: the kinds in the order the desk thinks of them: (catalog kind, caption, the value date it trades on)
UNI_KINDS = (("bill", "Bono", "bill"), ("zero", "Kuponsuz", "bill"), ("fixed", "Sabit kuponlu", "bond"),
             ("float", "TLREF'e endeksli", "bond"), ("cpi", "TÜFE'ye endeksli", "bond"))
UNI_RAW = ("bid", "ask", "last", "date", "vol")
#: what the trading list (DİBS RV) says of a bond that is on it: (column there, caption, number format)
UNI_RV = (("T", "Getiri % (RV)", "0.00%"), ("Z", "ASW / DM (bp)", "0"), ("AC", "Sinyal", None), ("AI", "DV01 / 1mn", "0.0"))


def universe_rows() -> List[Tuple[int, Optional[Dict[str, Any]], Optional[str]]]:
    """The rows of the EK_EVREN sheet below the desk's own: ``(row, bond, caption)`` - a caption row per kind
    (bond ``None``), then its bonds by maturity."""
    from . import bonds as bd
    out: List[Tuple[int, Optional[Dict[str, Any]], Optional[str]]] = []
    r = UNI_FIRST
    for kind, caption, _ in UNI_KINDS:
        group = [b for b in bd.catalog() if b.get("kind") == kind]
        if not group:
            continue
        out.append((r, None, "%s · %d kâğıt" % (caption, len(group))))
        r += 1
        for b in sorted(group, key=lambda x: x["maturity"]):
            out.append((r, b, None))
            r += 1
    return out


def _universe_check(model: Model) -> None:
    _dibs_live_check(model)
    for addr, has in (("T5", "DY5"), ("Z5", "EH5"), ("AC5", "FV5"), ("AI5", "ED5")):
        _need_formula(model, "DİBS RV", addr, has)


def _tto_universe(model: Model) -> None:
    """Every TRY government bond of the desk's Bloomberg list in one place, kind by kind, by maturity: what it is,
    how long it has left, whether it is on the trading list (DİBS RV), its price on Borsa İstanbul (bid, ask,
    the last trade and its day, the volume - bills on their own value date, the rest on theirs) and, for a bond on
    the trading list, what DİBS RV says of it.  On top, the bonds the desk adds that the list does not have yet.
    A bond's price comes from DİBS RV when it is listed there on the same source (the recorded file shows it
    offline); the others ask Bloomberg."""
    import datetime as _dt
    from .xl.values import date_to_serial
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
    b.set("A%d" % (UNI_OWN[0] - 1), "Kendi eklediklerimiz · listede olmayan kâğıtlar (yeni ihraç: ISIN yazın)", bold=True)

    def row(r: int, src: str) -> None:
        a = "$A%d" % r
        b.set("F%d" % r, '=IF(ISNUMBER($E{r}),$E{r}-TODAY(),"")'.format(r=r), fmt=INT0)
        b.set("G%d" % r, '=IF(ISNUMBER($F{r}),$F{r}/365.25,"")'.format(r=r), fmt="0.00")
        b.set("H%d" % r, '=IF({a}="","",IF(ISNUMBER($T{r}),"★",""))'.format(a=a, r=r), align="center", bold=True)
        b.set("T%d" % r, '=IF({a}="","",IFERROR(MATCH({a},{rv}$A$5:$A$54,0),""))'.format(a=a, rv=rv))
        b.set("R%d" % r, '=IF({a}="","",IF(TRIM({s}&"")="","{d}",TRIM(UPPER({s}))))'.format(
            a=a, s=src, d="ISL0" if src == "$C$2" else "ISL1"), align="center", color=NOTE_COLOR)
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

    # the desk's own: an ISIN typed; what a Turkish ISIN says of its maturity
    for r in range(UNI_OWN[0], UNI_OWN[1] + 1):
        b.input("A%d" % r, None)
        mat = 'DATE(2000+VALUE(MID($A{r},8,2)),VALUE(MID($A{r},6,2)),VALUE(MID($A{r},4,2)))'.format(r=r)
        b.set("B%d" % r, '=IF($A{r}="","",IF(LEFT($A{r},2)="TR",IFERROR(TEXT({m},"dd.mm.yy"),$A{r}),$A{r}))'.format(r=r, m=mat), bold=True)
        b.set("C%d" % r, '=IF($A{r}="","","liste dışı")'.format(r=r), color=NOTE_COLOR)
        b.set("E%d" % r, '=IF(LEFT($A{r},2)="TR",IFERROR({m},""),"")'.format(r=r, m=mat), fmt=DATE)
        row(r, "$E$2")
    # the list, kind by kind
    trades_on = {kind: on for kind, _, on in UNI_KINDS}
    for r, bond, caption in universe_rows():
        if bond is None:
            b.set("A%d" % r, caption, bold=True)
            continue
        kind = bond.get("kind")
        b.set("A%d" % r, bond["isin"])
        from . import bonds as bd
        b.set("B%d" % r, bd.short_label(bond), bold=True)
        b.set("C%d" % r, bd.KINDS.get(kind, kind))
        cpn = bond.get("coupon")
        if kind == "fixed" and isinstance(cpn, (int, float)):
            b.set("D%d" % r, float(cpn) / 100.0, fmt="0.00%")
        elif kind == "cpi" and isinstance(cpn, (int, float)):
            b.set("D%d" % r, "reel %%%s" % ("%.2f" % cpn).replace(".", ","))
        else:
            b.set("D%d" % r, {"float": "TLREF", "bill": "iskontolu", "zero": "iskontolu"}.get(kind, ""))
        b.set("E%d" % r, date_to_serial(_dt.date.fromisoformat(bond["maturity"])), fmt=DATE)
        row(r, "$C$2" if trades_on.get(kind) == "bill" else "$E$2")
    last = universe_rows()[-1][0] if universe_rows() else UNI_FIRST
    b.note("A%d" % (last + 2),
           "★ trading listesindeki (DİBS RV ve DİBS Trading) kâğıtlardır; ☆ / ★ ile eklenir, çıkarılır. Fiyatlar Borsa İstanbul'dan "
           "(bono ve kuponsuz kendi valöründe, diğerleri ertesi gün; kaynaklar sarı hücrelerde). Getiri, ASW ve sinyal yalnızca "
           "trading listesindeki kâğıtlar için hesaplanır.")
    b.sheet.freeze = [4, 2]


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
            "cpn_n", "mat_d", "prev_d", "next_d", "freq_n", "acc_n", "ok", "w", "n", "fits", "g", "per", "idx_n")
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
    with Bloomberg's index ratio), TLREF floaters get their dirty price and their place in the auction, no yield."""
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
            ("C", '=IF({sec}="","",IF(ISNUMBER({mat_d}),TEXT({mat_d},"dd.mm.yy")&IF({kind}="T"," TLREF",IF({kind}="E"," TÜFE",'
                  'IF({kind}="B"," Bono",""))),%s))' % text("{name}"), None),
            ("D", '=IF({kind}="S","Sabit kuponlu",IF({kind}="T","TLREF",IF({kind}="E","TÜFE",IF({kind}="B","Bono / kuponsuz",""))))',
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
               'IF({kind}="T","TLREF: kirli fiyat ve ihaledeki yer; getiri hesaplanmaz",'
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
                ("F", '=IF({how}="","",IF(AND({how}<>"T",{kind}="T"),"TLREF: temiz fiyat yazın",IF({how}="T","Temiz",IF({how}="B","Basit",'
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
#: (OIS_MAIN!B3 / D3) - and the VİOP target table (also on the desk page).  What a user types stays theirs.
EMPTY_BY_DEFAULT = (("OIS_MAIN", "U10:W89"), ("VIOP", "L331:P338"))
#: the name of that addition (left out where the file does not fit it: the cells keep the file's values)
EMPTY_NAME = "Boş başlayan girdiler"


def empty_default_refs() -> List[str]:
    """The cells of ``EMPTY_BY_DEFAULT`` as references ("OIS_MAIN!U10", ...)."""
    out = []
    for sheet, rng in EMPTY_BY_DEFAULT:
        r1, c1, r2, c2 = parse_range(rng)
        out += ["%s!%s%d" % (sheet, index_to_col(c), r) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
    return out


def _empty_check(model: Model) -> None:
    _need_sheets(model, "OIS_MAIN", "VIOP")
    v = model.sheet("VIOP")
    for addr, text in (("K330", "Target"), ("L330", "Yakın"), ("P330", "Hedef değer")):
        if v.consts.get(parse_a1(addr)) != text:
            raise ValueError("VIOP!%s beklenen başlık değil (%s yok)" % (addr, text))
    for col, step in (("X", "U"), ("Y", "V"), ("Z", "W")):           # a blank step: the scenario base decides
        _need_formula(model, "OIS_MAIN", "%s10" % col, 'IF(%s10<>"",%s10' % (step, step))


def _tto_empty(model: Model) -> None:
    for sheet, rng in EMPTY_BY_DEFAULT:
        sh = model.sheet(sheet)
        r1, c1, r2, c2 = parse_range(rng)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                rc = r * COLS + c
                if rc not in sh.fml:
                    sh.consts.pop(rc, None)


_BUILDERS: Dict[str, Tuple[Tuple[str, Callable[[Model], None], Callable[[Model], None]], ...]] = {
    "borsa": (("Borsa O/N", _borsa_check, _borsa), ("Borsa süzgeç", _borsa_filter_check, _borsa_filter)),
    "asw": ((FXC_SHEET, _asw_fx_check, _asw_fx),),
    "tto": ((FWD_SHEET, _forward_check, _tto_forward), (XAU_SHEET, _gold_check, _tto_gold),
            (VH_SHEET, _viop_hist_check, _tto_viop_history), ("EK_FWD vade faizleri", _fwd_rates_check, _tto_fwd_rates),
            ("EK_FWD EURTRY", _fwd_eur_check, _tto_fwd_eur),
            (SRC_SHEET, _sources_check, _tto_sources), ("Bulk Bond satırları", _bulk_bond_check, _tto_bulk_bond),
            (BULK_SHEET, _bulk_forward_check, _tto_bulk_forward), (LIVE_SHEET, _dibs_live_check, _tto_dibs_live),
            (UNI_SHEET, _universe_check, _tto_universe), (CARRY_SHEET, _carry_check, _tto_carry),
            ("Motor gün sayıları", _desk_days_check, _tto_desk_days), ("DV01 pozisyonu sıfır", _dv01_zero_check, _tto_dv01_zero),
            ("VİOP matris DV01'leri", _viop_dv01_check, _tto_viop_dv01),
            (AUC_SHEET, _auction_check, _tto_auction), (EMPTY_NAME, _empty_check, _tto_empty)),
}


__all__ = ["SheetBuilder", "apply", "formula_of", "recorded_value", "transplant", "lin", "overnight"]
