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
* ``bu``      (Borsa workbook) O/N equivalents of the implied TRY rates of the BIST swap quotes
* ``Sheet2``  (Borsa workbook) the list of quoted maturities keeps only quotes with an order behind them

The last one changes formulas of the workbook itself, which nothing else here does.  The workbook lists a
maturity when its bid or ask size "is a number"; over the API Bloomberg answers a size of 0 - and an old
price, the same on both sides - for a maturity nobody is quoting, where Excel's real-time link shows
"#N/A N/A".  Listed by the workbook's rule, the page was full of quotes that do not exist.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .xl.model import COLS, Model, Sheet, parse_a1
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


def _forward_check(model: Model) -> None:
    _need_sheets(model, "MASA", "VIOP", "Forward", "OIS_MAIN", "Motor")
    for _, _, src in FWD_DF_SOURCES:                   # the discount factors must depend on the days in $M$60 only
        transplant(_need_formula(model, "MASA", src, "$M$60"), {"$M$60": "$X5"})
    _need_formula(model, "MASA", "M60", "OIS_MAIN!$B$2")
    _need_formula(model, "VIOP", "L99")
    _need_formula(model, "VIOP", "L100")
    _need_formula(model, "Forward", "I2", "SETTLE_DT")


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
                  "Bid − RET", "Ask − RET"])
    # the general row: one spread for every date (a date's own spread can be typed over it), and the spot quotes
    g = FWD_ALL
    b.set("A%d" % g, "Tümü", bold=True, align="center")
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
        b.input("D%d" % r, "=$D$%d" % g, fmt="0", align="center")     # per date; starts from the general spread
        b.input("E%d" % r, "=$E$%d" % g, fmt="0", align="center")
        b.set("F%d" % r, '=IF($C%(r)d="","",$F$%(g)d)' % f, fmt=NUM4)
        b.set("G%d" % r, '=IF($C%(r)d="","",$G$%(g)d)' % f, fmt=NUM4)
        b.set("H%d" % r, '=IFERROR(IF($C%(r)d="","",($J%(r)d-$F%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("I%d" % r, '=IFERROR(IF($C%(r)d="","",($K%(r)d-$G%(r)d)*10000),"")' % f, fmt=INT0, bold=True)
        b.set("J%d" % r, '=IFERROR(IF($C%(r)d="","",$F%(r)d*(1+$M%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("K%d" % r, '=IFERROR(IF($C%(r)d="","",$G%(r)d*(1+$N%(r)d/100*$C%(r)d/360)/(1+$O%(r)d/100*$C%(r)d/360)),"")' % f, fmt=NUM4)
        b.set("L%d" % r, '=IF($C%(r)d="","",INDEX($AE%(r)d:$AK%(r)d,MATCH($B$2,$AE$3:$AK$3,0)))' % f, fmt="0.00")
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
                             "bloğundaki iskonto faktörleriyle aynı. Spread bp; 'Tümü' satırı bütün vadelere, vade satırındaki değer yalnız o vadeye uygulanır.")
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


#: book -> (name, precondition, builder) of each addition
# ---------------------------------------------------------------------------------------------- forward rates
FR_FIRST = 33                     # title row of the block "the TRY rates of the value date, to change and price with"
FR_CURVES = (("ICAP", "D30", "$I$22", "$K$22"), ("OIS", "D31", "$O$25", "$P$25"), ("VİOP", "D32", "$C$18", "$E$18"),
             ("RET", "D33", "$W$48", "$X$48"))


def _fwd_rates_check(model: Model) -> None:
    """The Forward sheet's USDTRY / EURTRY tables price from these cells (the rates of the value date).  The block
    lives on the forward quote sheet, so it goes when that one is left out."""
    _need_sheets(model, "Forward", FWD_SHEET)
    for _, at, bid, ask in FR_CURVES:
        _need_formula(model, "Forward", at, bid)                      # the bid side of the row uses the bid rate ...
        _need_formula(model, "Forward", "F" + at[1:], ask)            # ... the ask side the ask rate
        _need_formula(model, "Forward", at, "$Y$27")                  # USD ask on the bid side, USD bid on the ask side
        _need_formula(model, "Forward", "F" + at[1:], "$W$27")
        _need_formula(model, "Forward", "D%d" % (int(at[1:]) + 12), bid)  # EURTRY: the same TRY rate, EUR days and rates
    _need_formula(model, "Forward", "D42", "$AE$27")
    _need_formula(model, "Forward", "F42", "$AC$27")


def _tto_fwd_rates(model: Model) -> None:
    """The TRY rates the Forward sheet's tables price the value date with - ICAP, OIS, VİOP and RET, bid and ask -
    side by side, each one a cell that can be typed over: the USDTRY and EURTRY forwards and their points follow
    at once (with the sheet's own formula), and blanking a rate takes it back to its curve."""
    b = SheetBuilder(model, FWD_SHEET)
    t = FR_FIRST
    b.title("A%d" % t, "VADE FAİZLERİYLE FORWARD  ·  Forward sayfasının valörü için her eğrinin bid / ask TRY faizi – faizi değiştirin, "
                       "forward ve puan hemen yeniden hesaplanır")
    b.row("A%d" % (t + 1), ["Valör", None, "Gün USDTRY", None, "Gün EURTRY"], bold=True)
    b.set("B%d" % (t + 1), "=Forward!$D$2", fmt=DATE, bold=True)
    b.set("D%d" % (t + 1), "=Forward!$U$27", fmt=INT0)
    b.set("F%d" % (t + 1), "=Forward!$AA$27", fmt=INT0)
    s = t + 2                                                        # spots and the currencies' rates
    b.row("A%d" % s, ["USDTRY spot", None, "USD bid %", None, "USD ask %", None, "EURTRY spot", None, "EUR bid %", None, "EUR ask %"], bold=True)
    b.input("B%d" % s, "=Forward!$F$2", fmt=NUM4)
    b.input("D%d" % s, "=Forward!$W$27*100", fmt="0.0000")
    b.input("F%d" % s, "=Forward!$Y$27*100", fmt="0.0000")
    b.input("H%d" % s, "=Forward!$G$2", fmt=NUM4)
    b.input("J%d" % s, "=Forward!$AC$27*100", fmt="0.0000")
    b.input("L%d" % s, "=Forward!$AE$27*100", fmt="0.0000")
    b.head("A%d" % (s + 1), ["Eğri", "TRY bid %", "TRY ask %", "USDTRY bid", "USDTRY mid", "USDTRY ask", "Puan bid", "Puan mid", "Puan ask",
                             "P/gün bid", "P/gün ask", "EURTRY bid", "EURTRY ask", "EUR puan bid", "EUR puan ask"])
    first = s + 2
    rows = [(name, "=Forward!%s*100" % bid, "=Forward!%s*100" % ask) for name, _, bid, ask in FR_CURVES]
    ret = first + len(FR_CURVES) - 1
    rows.append(("Elle", "=$B$%d" % ret, "=$C$%d" % ret))            # a row of one's own: starts from RET
    f = {"s": s, "d": t + 1}
    for k, (name, bid, ask) in enumerate(rows):
        r = first + k
        f["r"] = r
        b.set("A%d" % r, name, bold=True, align="center")
        b.input("B%d" % r, bid, fmt="0.0000")
        b.input("C%d" % r, ask, fmt="0.0000")
        # the sheet's own formula: bid side = spot·(1 + TRY bid·g/360)/(1 + USD ask·g/360), ask side the other way round
        b.set("D%d" % r, '=IFERROR($B$%(s)d*(1+$B%(r)d/100/360*$D$%(d)d)/(1+$F$%(s)d/100/360*$D$%(d)d),"")' % f, fmt=NUM4, bold=True)
        b.set("F%d" % r, '=IFERROR($B$%(s)d*(1+$C%(r)d/100/360*$D$%(d)d)/(1+$D$%(s)d/100/360*$D$%(d)d),"")' % f, fmt=NUM4, bold=True)
        b.set("E%d" % r, '=IFERROR(($D%(r)d+$F%(r)d)/2,"")' % f, fmt=NUM4)
        b.set("G%d" % r, '=IFERROR(($D%(r)d-$B$%(s)d)*10000,"")' % f, fmt=INT0)
        b.set("H%d" % r, '=IFERROR(($E%(r)d-$B$%(s)d)*10000,"")' % f, fmt=INT0)
        b.set("I%d" % r, '=IFERROR(($F%(r)d-$B$%(s)d)*10000,"")' % f, fmt=INT0)
        b.set("J%d" % r, '=IFERROR($G%(r)d/$D$%(d)d,"")' % f, fmt="#,##0.0")
        b.set("K%d" % r, '=IFERROR($I%(r)d/$D$%(d)d,"")' % f, fmt="#,##0.0")
        b.set("L%d" % r, '=IFERROR($H$%(s)d*(1+$B%(r)d/100/360*$F$%(d)d)/(1+$L$%(s)d/100/360*$F$%(d)d),"")' % f, fmt=NUM4, bold=True)
        b.set("M%d" % r, '=IFERROR($H$%(s)d*(1+$C%(r)d/100/360*$F$%(d)d)/(1+$J$%(s)d/100/360*$F$%(d)d),"")' % f, fmt=NUM4, bold=True)
        b.set("N%d" % r, '=IFERROR(($L%(r)d-$H$%(s)d)*10000,"")' % f, fmt=INT0)
        b.set("O%d" % r, '=IFERROR(($M%(r)d-$H$%(s)d)*10000,"")' % f, fmt=INT0)
    b.note("A%d" % (first + len(rows)), "TRY faizi: eğrinin bu valördeki basit ACT/360 faizi (%) – Forward sayfasının USDTRY ve EURTRY tablolarının kullandığı hücreler "
                                         "(ICAP ve VİOP ima eğrileri, TRY OIS ± yarım bid/ask, RET). Bid tarafı USD (EUR) ask'iyle, ask tarafı USD (EUR) bid'iyle hesaplanır "
                                         "(sayfanın formülü). Değiştirdiğiniz faiz, spot ve döviz faizi yalnız size görünür; silince piyasaya döner. 'Elle' satırı RET'ten başlar.")


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


_BUILDERS: Dict[str, Tuple[Tuple[str, Callable[[Model], None], Callable[[Model], None]], ...]] = {
    "borsa": (("Borsa O/N", _borsa_check, _borsa), ("Borsa süzgeç", _borsa_filter_check, _borsa_filter)),
    "asw": ((FXC_SHEET, _asw_fx_check, _asw_fx),),
    "tto": ((FWD_SHEET, _forward_check, _tto_forward), (XAU_SHEET, _gold_check, _tto_gold),
            (VH_SHEET, _viop_hist_check, _tto_viop_history), ("EK_FWD vade faizleri", _fwd_rates_check, _tto_fwd_rates),
            (SRC_SHEET, _sources_check, _tto_sources), ("Bulk Bond satırları", _bulk_bond_check, _tto_bulk_bond),
            (BULK_SHEET, _bulk_forward_check, _tto_bulk_forward)),
}


__all__ = ["SheetBuilder", "apply", "formula_of", "recorded_value", "transplant", "lin", "overnight"]
