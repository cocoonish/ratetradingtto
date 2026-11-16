"""Each user's own calc sheets ("Kişisel hesap tablosu"): small Excel-like grids on a launchpad, in the side drawer or
in a window of their own, whose cells hold numbers, texts or formulas linked to the dashboard's live cells -
``=MASA!I60+25`` stays live as the desk's spread moves.

A sheet is kept with the account (``calc.<user>`` in the store's key / value table: all of the user's sheets); a
launchpad or drawer item names it (``{"type": "calc", "sheet": "<id>"}``), so one sheet may stand on a launchpad, in the
drawer and in a pop-out window at once.  An exported launchpad carries its sheets' cells; an imported one makes sheets
of the importing user's own of them.  A sheet no item names any more goes some days after its last change.

Formulas are the workbook engine's (``tto/xl``): Excel's syntax with English function names, ``,`` (or Turkish Excel's
``;``) between arguments.  A formula refers to the sheet's own cells (``A1``, ``$B$2``, ``A1:A5``), to the desk
workbook's cells by sheet name (``MASA!I60``, ``'C & R'!B5``, the workbook's names: ``SPOTDATE``) and to the other
workbooks' with the book in brackets (``[sofr]SOFR_FOMC!B9``, ``'[asw]ASW'!C5``; books: tto, sofr, borsa, asw).  It is
compiled once and evaluated on the calculation thread against the user's own calculation of each workbook - their inputs
and "Elle değer" values apply, exactly what their pages show.  The browser asks again on each generation, like the
table boxes; a sheet is evaluated again only when something it read changed since (the engine's dependency masks).

Nothing here asks Bloomberg (the daily data limit is a hard rule): a formula calling BDP, BDH, BDS, BFXFORWARD or any
other add-in function (``_xll.``) is refused as it is typed; the workbook cells a formula reads are those the pages
compute anyway.  A sheet only an administrators' page shows (Motor) is the administrators' here too.
"""
from __future__ import annotations

import collections
import datetime as _dt
import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import layout as lay
from .inputs import parse_date, parse_number
from .service import EngineThread, ServiceError, _done, _then
from .store import now_iso
from .xl import numfmt
from .xl.compiler import ADDINS, Compiler
from .xl.errors import E_CALC, E_NAME, E_NUM, E_REF, E_VALUE, XlError
from .xl.functions import FUNCS
from .xl.model import COLS
from .xl.parser import parse_template, walk
from .xl.tokenizer import col_to_index, index_to_col, to_template
from .xl.unparse import Unparser
from .xl.values import XlArray, XlRange

#: a sheet's size as it is made, and at most (it grows as it is typed or pasted into, up to the cap)
DEFAULT_ROWS, DEFAULT_COLS = 8, 6
MAX_ROWS, MAX_COLS = 50, 12
MAX_RAW = 1000                    # characters one cell holds - a formula too
MAX_NESTING = 64                  # brackets inside one another in a formula (Excel's own limit)
MAX_SIGNS = 30                    # + / - signs in a row
MAX_SHEETS = 30                   # sheets one user keeps
MAX_SHEET_BYTES = 96 * 1024
MAX_USER_BYTES = 768 * 1024
MIN_WIDTH, MAX_WIDTH = 40, 600    # a column's width (px)
EVAL_SECONDS = 2.0                # one sheet's evaluation on the calculation thread (it is shared by everybody)
JOB_SECONDS = 4.0                 # one request's sheets: those not begun by then are answered on the next request
MAX_READS = 200000                # workbook cells one evaluation reads
MAX_RANGE = 100000                # cells of one workbook range
MAX_EVAL_ITEMS = 40               # sheets one request brings up to date
ORPHAN_DAYS = 7                   # a sheet no item names is dropped this long after its last change
RESULTS_KEPT = 300                # evaluations kept (per user, sheet, number format)
CODE_KEPT = 5000                  # compiled formulas kept

#: the number formats a cell may be given (the toolbar's: decimals, thousands, percent; dates)
DATE_FMT = "dd\\.mm\\.yyyy"
_FMT = re.compile(r"^(General|(?:#,##0|0)(?:\.0{1,10})?%?|dd\\\.mm\\\.yyyy|dd\\\.mm\\\.yy|yyyy-mm-dd|"
                  r"dd\\\.mm\\\.yyyy hh:mm|hh:mm)$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ADDR = re.compile(r"^([A-Z]{1,2})([1-9][0-9]{0,2})$")
_COL = re.compile(r"^[A-Z]{1,2}$")
_BOOKED = re.compile(r"^\[([^\]]*)\](.*)$", re.S)
_BOOK_SHEET = re.compile(r"\[([A-Za-z][\w.]*)\]([A-Za-z_À-￿][\w.À-￿]*)!")
_BOOK_ONLY = re.compile(r"\[([A-Za-z][\w.]*)\]$")
_DATE_LIKE = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$|^\d{4}-\d{1,2}-\d{1,2}$")

BLOOMBERG = ("%s Bloomberg'den veri ister: hesap tablosunda Bloomberg işlevleri kullanılamaz (günlük veri limiti). "
             "Değeri dashboard'daki hücresinden alın, örn. =MASA!I60")
UNREADABLE = ("formül okunamadı - parantezleri, tırnakları ve ayırıcıları denetleyin (işlev adları İngilizce: SUM, IF, "
              "ROUND …; bağımsız değişkenler virgülle ya da noktalı virgülle ayrılır)")
TIME_NOTE = "Hesap süresi sınırı aşıldı (%g sn) - formül çok büyük bir aralığı ya da çok uzun bir zinciri okuyor"
READS_NOTE = "Çok fazla hücre okunuyor (bir hesapta en fazla %d çalışma kitabı hücresi)"
RANGE_NOTE = "Aralık çok büyük (bir aralıkta en fazla %d hücre)"
ADMIN_NOTE = "%s sayfası yalnızca yöneticilere açık"

#: what an error value says, in the desk's words (the cell shows the engine's own code, as the pages do)
TIPS = {"#DIV/0!": "Sıfıra bölme", "#VALUE!": "Değer uygun türde değil (sayı yerine metin?)", "#REF!": "Geçersiz başvuru",
        "#NAME?": "Bilinmeyen işlev ya da ad (işlev adları İngilizce: SUM, IF, ROUND …)",
        "#N/A": "Değer yok (aranan bulunamadı ya da veri henüz gelmedi)", "#NUM!": "Geçersiz sayı",
        "#NULL!": "Kesişmeyen aralıklar", "#CALC!": "Hesaplanamadı", "#SPILL!": "Dizi sonucu sığmadı",
        "#GETTING_DATA": "Veri bekleniyor"}

#: functions whose result takes the number format of their first argument (as Excel's does: =ROUND(A1;2) of a %)
_LEAD_FUNCS = ("SUM", "MIN", "MAX", "AVERAGE", "MEDIAN", "ROUND", "ROUNDUP", "ROUNDDOWN", "ABS", "IFERROR", "IFNA",
               "INT", "TRUNC")
#: functions whose result is a day (shown as a date; Excel itself leaves a few of them a number - the desk wants the day)
_DATE_FUNCS = ("TODAY", "NOW", "DATE", "EDATE", "EOMONTH", "WORKDAY")
_MISS = object()


class CalcError(ValueError):
    """What was sent is not a change of a sheet (the service answers 400 with the message)."""


class _Stop(BaseException):
    """Ends an evaluation that went over a limit (time, cells read).  Not an Exception: no function of the engine takes
    it for an error of its own."""

    def __init__(self, text: str):
        BaseException.__init__(self, text)
        self.text = text


# ---------------------------------------------------------------------------------------------- cells and their values
def cell_name(r: int, c: int) -> str:
    return index_to_col(c) + str(r)


def parse_cell(a: Any) -> Tuple[int, int]:
    """``"B12"`` -> (12, 2); refused outside the largest sheet."""
    m = _ADDR.match(a) if isinstance(a, str) else None
    if m is None:
        raise CalcError("hücre adresi geçersiz: %s" % str(a)[:20])
    r, c = int(m.group(2)), col_to_index(m.group(1))
    if r > MAX_ROWS or c > MAX_COLS:
        raise CalcError("hesap tablosu en fazla %d satır × %d sütun (A–%s): %s" % (MAX_ROWS, MAX_COLS, index_to_col(MAX_COLS), a))
    return r, c


def parse_block(a: Any) -> Tuple[int, int, int, int]:
    """``"B2:C5"`` (or one cell) -> (top, left, bottom, right)."""
    if not isinstance(a, str):
        raise CalcError("aralık geçersiz")
    x, _, y = a.partition(":")
    r1, c1 = parse_cell(x)
    r2, c2 = parse_cell(y) if y else (r1, c1)
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def _is_formula(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("=")


def _const(v: Any) -> Any:
    """The value of a constant cell as kept: a text that starts with = or ' is kept behind a ' (as Excel shows it)."""
    if isinstance(v, str):
        return v[1:] if v.startswith("'") else v
    if isinstance(v, bool):
        return v
    return float(v)


def _keep_text(s: str) -> str:
    return "'" + s if s.startswith(("=", "'")) else s


def _fold(text: str) -> str:
    """A name compared without case - the Turkish dotted / dotless i included ("dibs rv" is "DİBS RV")."""
    return text.casefold().replace("̇", "").replace("ı", "i")


def typed(raw: str, lang: str = "tr") -> Tuple[Any, Optional[str]]:
    """What a person typed into a cell -> (the value kept, the number format it brings or None).

    ``=…`` a formula (checked: refused when it cannot be read or asks Bloomberg); ``'…`` a text as it is; a number in
    the user's number format (``1.234,5`` / ``1,234.5``; ``25%`` is 0,25 shown as a percentage); a date (``15.12.2026``,
    shown as one); TRUE / FALSE (DOĞRU / YANLIŞ); anything else a text."""
    s = raw.strip()
    if not s:
        return None, None
    if len(s) > MAX_RAW:
        raise CalcError("bir hücre en fazla %d karakter alır" % MAX_RAW)
    if s.startswith("="):
        check_formula(s)
        return s, None
    if s.startswith("'"):
        return _keep_text(s[1:]), None
    n = parse_number(s, lang)
    if n is not None:
        if "%" in s:
            return n, ("0.00%" if re.search(r"[.,]\d", s) else "0%")
        return n, None
    if _DATE_LIKE.match(s):
        d = parse_date(s)
        if d is not None:
            return d, DATE_FMT
    up = s.upper()
    if up in ("TRUE", "DOĞRU"):
        return True, None
    if up in ("FALSE", "YANLIŞ"):
        return False, None
    return _keep_text(s), None


def _looks_typed(s: str, lang: str) -> bool:
    """Whether a text would be read as something else when typed again (a ' keeps it a text)."""
    if s.startswith(("=", "'")) or parse_number(s, lang) is not None:
        return True
    if _DATE_LIKE.match(s.strip()) and parse_date(s.strip()) is not None:
        return True
    return s.strip().upper() in ("TRUE", "FALSE", "DOĞRU", "YANLIŞ")


# ---------------------------------------------------------------------------------------------- formulas
def _split(text: str) -> List[Tuple[str, str]]:
    """A formula in parts: ``("s", '"…"')`` a text, ``("q", "'…'")`` a quoted sheet name, ``("o", …)`` the rest."""
    out: List[Tuple[str, str]] = []
    buf: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n:
                if text[j] == ch:
                    if j + 1 < n and text[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            if buf:
                out.append(("o", "".join(buf)))
                buf = []
            out.append(("s" if ch == '"' else "q", text[i:j + 1]))
            i = j + 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        out.append(("o", "".join(buf)))
    return out


def normalise(text: str) -> str:
    """A formula as the engine reads it.  Turkish Excel's ``;`` between arguments is a ``,`` (and its decimal comma a
    point: ``=ROUND(1,25;1)``); ``[sofr]SOFR_FOMC!B9`` is ``'[sofr]SOFR_FOMC'!B9`` (the book in the quoted name)."""
    parts = _split(text)
    depth = 0
    semis = False
    for kind, t in parts:
        if kind != "o":
            continue
        for ch in t:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ";" and depth <= 0:
                semis = True
    if semis:
        depth = 0
        conv = []
        for kind, t in parts:
            if kind != "o":
                conv.append((kind, t))
                continue
            out = []
            for ch in t:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                if depth <= 0 and ch == ",":
                    ch = "."
                elif depth <= 0 and ch == ";":
                    ch = ","
                out.append(ch)
            conv.append((kind, "".join(out)))
        parts = conv
    out: List[str] = []
    k = 0
    while k < len(parts):
        kind, t = parts[k]
        if kind == "o":
            t = _BOOK_SHEET.sub(lambda m: "'[%s]%s'!" % (m.group(1), m.group(2)), t)
            m = _BOOK_ONLY.search(t)
            if (m and k + 2 < len(parts) and parts[k + 1][0] == "q" and parts[k + 2][0] == "o"
                    and parts[k + 2][1].startswith("!")):
                # [sofr]'SOFR FOMC'!B9: the book goes into the quoted name
                out.append(t[:m.start()])
                out.append("'[%s]%s" % (m.group(1), parts[k + 1][1][1:]))
                k += 2
                continue
        out.append(t)
        k += 1
    return "".join(out)


def _nesting(text: str) -> Tuple[int, int]:
    """(deepest brackets, longest run of + / - signs) outside texts: the parser takes a step of its own for each."""
    deep = depth = signs = run = 0
    for kind, t in _split(text):
        if kind != "o":
            run = 0
            continue
        for ch in t:
            if ch in "({":
                depth += 1
                deep = max(deep, depth)
            elif ch in ")}":
                depth -= 1
            if ch in "+-":
                run += 1
                signs = max(signs, run)
            elif not ch.isspace():
                run = 0
    return deep, signs


def _bloomberg(ast) -> Optional[str]:
    for nd in walk(ast):
        if nd[0] == "func" and (nd[3] or nd[1] in ADDINS):
            return nd[1]
    return None


def check_formula(text: str, bloomberg: str = BLOOMBERG):
    """A formula as typed -> its tree.  Refused: too long or too deep, unreadable, or one that would ask Bloomberg
    (``bloomberg``: what is said then - the input cells' formulas say it their way, inputformula.py)."""
    if len(text) > MAX_RAW:
        raise CalcError("formül en fazla %d karakter olabilir" % MAX_RAW)
    norm = normalise(text)
    deep, signs = _nesting(norm)
    if deep > MAX_NESTING:
        raise CalcError("formülde iç içe en fazla %d parantez olabilir" % MAX_NESTING)
    if signs > MAX_SIGNS:
        raise CalcError(UNREADABLE)
    try:
        ast = parse_template(to_template(norm, 1, 1))
    except Exception:  # noqa: BLE001 - whatever the tokenizer or the parser says: not a formula
        raise CalcError(UNREADABLE)
    bbg = _bloomberg(ast)
    if bbg:
        raise CalcError(bloomberg % bbg)
    return ast


def _clip(nd, r: int, c: int):
    """A formula's tree with the references that fall off the sheet (copied up / left past row 1, column A) as #REF!."""
    k = nd[0]
    if k in ("cell", "range", "cols", "rows"):
        if k == "cell":
            corners = [(nd[2], nd[3], nd[4], nd[5])]
        elif k == "range":
            corners = [(nd[2], nd[3], nd[4], nd[5]), (nd[6], nd[7], nd[8], nd[9])]
        elif k == "cols":
            corners = [(True, 1, nd[2], nd[3]), (True, 1, nd[4], nd[5])]
        else:
            corners = [(nd[2], nd[3], True, 1), (nd[4], nd[5], True, 1)]
        for ra, rr, ca, cc in corners:
            row = rr if ra else r + rr
            col = cc if ca else c + cc
            if not (1 <= row <= 1048576 and 1 <= col <= 16384):
                return ("err", "#REF!")
        return nd
    if k == "func":
        return (k, nd[1], [_clip(a, r, c) for a in nd[2]], nd[3])
    if k == "bin":
        return (k, nd[1], _clip(nd[2], r, c), _clip(nd[3], r, c))
    if k in ("neg", "pos", "pct", "single", "paren"):
        return (k, _clip(nd[1], r, c))
    return nd


def shift_formula(text: str, r0: int, c0: int, r1: int, c1: int) -> str:
    """A formula of (r0, c0) copied to (r1, c1): its relative references move with it (``=A1*2`` of B1 is ``=A2*2`` in
    B2), ``$`` ones stay - as Excel copies."""
    tree = parse_template(to_template(normalise(text), r0, c0))
    return "=" + Unparser(r1, c1).text(_clip(tree, r1, c1))


def _lead(ast, names: Dict[str, str]) -> Optional[Tuple]:
    """What a formula's result takes its number format from (``=Forward!D2+7`` is a date, as in Excel): the reference
    it leads with - the first operand of a sum, of SUM / ROUND …, a workbook name's cells - ``("ref", sheet, row_abs,
    row, col_abs, col)``; or a date function's own (``=TODAY()``, ``=WORKDAY(…)``) - ``("fmt", code)``."""
    nd = ast
    for _ in range(32):
        k = nd[0]
        if k in ("paren", "neg", "pos"):
            nd = nd[1]
        elif k == "bin" and nd[1] in ("+", "-"):
            nd = nd[2]
        elif k == "func" and nd[1] in _DATE_FUNCS:
            return ("fmt", DATE_FMT + " hh:mm" if nd[1] == "NOW" else DATE_FMT)
        elif k == "func" and nd[1] in _LEAD_FUNCS and nd[2] and nd[2][0][0] != "missing":
            nd = nd[2][0]
        elif k == "name" and nd[1] in names:
            try:
                nd = parse_template(names[nd[1]])
            except Exception:  # noqa: BLE001
                return None
        elif k in ("cell", "range"):
            return ("ref", nd[1], nd[2], nd[3], nd[4], nd[5])
        else:
            return None
    return None


def _split_book(name: str) -> Tuple[str, str]:
    """``"[sofr]SOFR_FOMC"`` -> ("sofr", "SOFR_FOMC"); a sheet without a book is the desk workbook's."""
    m = _BOOKED.match(name)
    if m is None:
        return "tto", name
    book = re.sub(r"\.xls[xmb]?$", "", m.group(1).strip(), flags=re.I).lower()
    return book or "tto", m.group(2)


class _Compiler(Compiler):
    """The workbook's compiler with a calc formula's sheets: no sheet - the calc sheet itself (``S``); a workbook's sheet
    - its slot (sheets of every book numbered together, see CalcSheets._tables)."""

    def __init__(self, model, resolve):
        Compiler.__init__(self, model)
        self._resolve = resolve

    def _sheet(self, sheet: Optional[str]) -> Optional[str]:
        if sheet is None:
            return "S"
        slot = self._resolve(sheet)
        return None if slot is None else str(slot)


class _NoNames(object):
    names: Dict[str, str] = {}
    sheet_index: Dict[str, int] = {}
    templates: List[str] = []


# ---------------------------------------------------------------------------------------------- what is kept
def _empty() -> Dict[str, Any]:
    return {"rows": DEFAULT_ROWS, "cols": DEFAULT_COLS, "cells": {}, "fmt": {}, "widths": {}, "rev": 0}


EMPTY = _empty()


def _sheet_id(v: Any) -> str:
    if not isinstance(v, str) or not _ID.match(v):
        raise CalcError("hesap tablosu geçersiz")
    return v


def _stored_cell(a: str, v: Any, strict: bool) -> Any:
    """A cell's value as a file or the store holds it, checked (``strict``: a formula is read, refused as typed)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):
            raise CalcError("%s: geçersiz sayı" % a)
        return x
    if isinstance(v, str) and v and len(v) <= MAX_RAW:
        if strict and v.startswith("="):
            try:
                check_formula(v)
            except CalcError as exc:
                raise CalcError("%s: %s" % (a, exc))
        return v
    raise CalcError("%s: geçersiz değer" % a)


def _clean(d: Any, strict: bool) -> Dict[str, Any]:
    """A sheet as kept, checked.  ``strict`` (a file being imported): anything wrong refuses it; otherwise (what the
    store holds, written by this or another version) what does not pass is left out."""
    if not isinstance(d, dict):
        if strict:
            raise CalcError("hesap tablosu geçersiz")
        d = {}
    out = _empty()
    for k, cap in (("rows", MAX_ROWS), ("cols", MAX_COLS)):
        v = d.get(k, out[k])
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= cap:
            if strict:
                raise CalcError("satır / sütun sayısı geçersiz")
            v = out[k]
        out[k] = v
    for part in ("cells", "fmt", "widths"):
        v = d.get(part) or {}
        if not isinstance(v, dict):
            if strict:
                raise CalcError("hesap tablosu geçersiz")
            v = {}
        if len(v) > MAX_ROWS * MAX_COLS and strict:
            raise CalcError("hesap tablosu çok büyük")
        for a, x in v.items():
            try:
                if part == "widths":
                    if not isinstance(a, str) or not _COL.match(a) or col_to_index(a) > MAX_COLS:
                        raise CalcError("sütun geçersiz: %s" % str(a)[:4])
                    if isinstance(x, bool) or not isinstance(x, int) or not MIN_WIDTH <= x <= MAX_WIDTH:
                        raise CalcError("sütun genişliği %d–%d piksel olmalı" % (MIN_WIDTH, MAX_WIDTH))
                    out["widths"][a] = x
                    continue
                r, c = parse_cell(a)
                if part == "fmt":
                    if not isinstance(x, str) or not _FMT.match(x):
                        raise CalcError("%s: sayı biçimi geçersiz" % a)
                    out["fmt"][a] = x
                else:
                    out["cells"][a] = _stored_cell(a, x, strict)
                out["rows"], out["cols"] = max(out["rows"], r), max(out["cols"], c)
            except CalcError:
                if strict:
                    raise
    rev = d.get("rev")
    out["rev"] = rev if isinstance(rev, int) and not isinstance(rev, bool) and rev >= 0 else 0
    if isinstance(d.get("at"), str):
        out["at"] = d["at"][:32]
    return out


def _kept(v: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    sheets = v.get("sheets") if isinstance(v, dict) else None
    for sid, sh in (sheets.items() if isinstance(sheets, dict) else ()):
        if isinstance(sid, str) and _ID.match(sid):
            out[sid] = _clean(sh, strict=False)
    return out


def _extent(cells: Dict[str, Any]) -> Tuple[int, int]:
    r = c = 1
    for a in cells:
        rr, cc = parse_cell(a)
        r, c = max(r, rr), max(c, cc)
    return r, c


def _changed(cur: Dict[str, Any], data: Dict[str, Any], lang: str, sheets: Dict[str, Dict[str, Any]],
             sid: str) -> Dict[str, Any]:
    """``cur`` with what ``data`` changes - a new sheet (``cur`` itself when nothing changed):

    * ``cells``: ``{"A1": "what was typed" | ""}`` (``""``: cleared - its number format stays, as Excel's Delete);
    * ``copy``: ``{"sheet", "from": "B1:C2", "to": "B3" | "B3:C8"}`` - cells of a sheet (this one or another of the
      user's) pasted with their formulas moved along; over a block that is a multiple of them, repeated (Ctrl+D);
    * ``fmt``: ``{"A1": "0.00" | ""}``; ``widths``: ``{"A": 120 | null}``; ``rows`` / ``cols``: the size."""
    cells = dict(cur["cells"])
    fmt = dict(cur["fmt"])
    widths = dict(cur["widths"])
    rows, cols = cur["rows"], cur["cols"]
    sent_fmt = data.get("fmt")
    if sent_fmt is not None and not isinstance(sent_fmt, dict):
        raise CalcError("sayı biçimleri geçersiz")
    cp = data.get("copy")
    if cp is not None:
        if not isinstance(cp, dict):
            raise CalcError("kopyalama geçersiz")
        src_id = _sheet_id(cp.get("sheet", sid))
        src = cur if src_id == sid else (sheets.get(src_id) or EMPTY)
        r1, c1, r2, c2 = parse_block(cp.get("from"))
        t1, u1, t2, u2 = parse_block(cp.get("to"))
        hgt, wid = r2 - r1 + 1, c2 - c1 + 1
        th, tw = t2 - t1 + 1, u2 - u1 + 1
        if th % hgt or tw % wid:
            th, tw = hgt, wid                          # (not a multiple of the block: pasted once, at the top left)
        if t1 + th - 1 > MAX_ROWS or u1 + tw - 1 > MAX_COLS:
            raise CalcError("yapıştırılan alan hesap tablosuna sığmıyor (en fazla %d satır × %d sütun)" % (MAX_ROWS, MAX_COLS))
        writes: Dict[str, Any] = {}
        forms: Dict[str, Optional[str]] = {}
        for i in range(th):
            for j in range(tw):
                sr, sc = r1 + i % hgt, c1 + j % wid
                tr, tc = t1 + i, u1 + j
                v = src["cells"].get(cell_name(sr, sc))
                if _is_formula(v):
                    try:
                        v = shift_formula(v, sr, sc, tr, tc)
                    except Exception:  # noqa: BLE001 - a formula that cannot be read again: copied as it is
                        pass
                    if len(v) > MAX_RAW:
                        raise CalcError("%s: formül en fazla %d karakter olabilir" % (cell_name(tr, tc), MAX_RAW))
                writes[cell_name(tr, tc)] = v
                forms[cell_name(tr, tc)] = src["fmt"].get(cell_name(sr, sc))
        for a, v in writes.items():
            if v is None:
                cells.pop(a, None)
            else:
                cells[a] = v
        for a, f in forms.items():
            if f:
                fmt[a] = f
            else:
                fmt.pop(a, None)
        rows, cols = max(rows, t1 + th - 1), max(cols, u1 + tw - 1)
    sent = data.get("cells")
    if sent is not None:
        if not isinstance(sent, dict) or len(sent) > MAX_ROWS * MAX_COLS:
            raise CalcError("hücreler geçersiz")
        for a, raw in sent.items():
            r, c = parse_cell(a)
            if raw is None or raw == "":
                cells.pop(a, None)
                continue
            if isinstance(raw, bool) or isinstance(raw, (int, float)):
                value, auto = _stored_cell(a, raw, True), None
            elif isinstance(raw, str):
                try:
                    value, auto = typed(raw, lang)
                except CalcError as exc:
                    raise CalcError("%s: %s" % (a, exc))
            else:
                raise CalcError("%s: geçersiz değer" % a)
            if value is None:
                cells.pop(a, None)
                continue
            cells[a] = value
            if auto and fmt.get(a, "General") == "General" and not (sent_fmt and a in sent_fmt):
                fmt[a] = auto                          # (25% typed: shown as a percentage, a date as a date)
            rows, cols = max(rows, r), max(cols, c)
    if sent_fmt:
        if len(sent_fmt) > MAX_ROWS * MAX_COLS:
            raise CalcError("sayı biçimleri geçersiz")
        for a, f in sent_fmt.items():
            r, c = parse_cell(a)
            if f is None or f == "" or f == "General":
                fmt.pop(a, None)
            elif isinstance(f, str) and _FMT.match(f):
                fmt[a] = f
            else:
                raise CalcError("%s: sayı biçimi geçersiz" % a)
            rows, cols = max(rows, r), max(cols, c)
    sent_w = data.get("widths")
    if sent_w is not None:
        if not isinstance(sent_w, dict) or len(sent_w) > MAX_COLS:
            raise CalcError("sütun genişlikleri geçersiz")
        for col, w in sent_w.items():
            if not isinstance(col, str) or not _COL.match(col) or col_to_index(col) > MAX_COLS:
                raise CalcError("sütun geçersiz: %s" % str(col)[:4])
            if w is None:
                widths.pop(col, None)
            elif isinstance(w, bool) or not isinstance(w, int) or not MIN_WIDTH <= w <= MAX_WIDTH:
                raise CalcError("sütun genişliği %d–%d piksel olmalı" % (MIN_WIDTH, MAX_WIDTH))
            else:
                widths[col] = w
    for k, cap in (("rows", MAX_ROWS), ("cols", MAX_COLS)):
        v = data.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= cap:
            raise CalcError("hesap tablosu en fazla %d satır × %d sütun" % (MAX_ROWS, MAX_COLS))
        need = _extent(cells)[0 if k == "rows" else 1]
        if v < need:
            raise CalcError("son %s dolu hücreler var - önce onları silin" % ("satırlarda" if k == "rows" else "sütunlarda"))
        if k == "rows":
            rows = v
        else:
            cols = v
    fmt = {a: f for a, f in fmt.items() if parse_cell(a)[0] <= rows and parse_cell(a)[1] <= cols}
    widths = {col: w for col, w in widths.items() if col_to_index(col) <= cols}
    new = dict(cur, cells=cells, fmt=fmt, widths=widths, rows=rows, cols=cols)
    if all(new[k] == cur[k] for k in ("cells", "fmt", "widths", "rows", "cols")):
        return cur
    if len(json.dumps(new, ensure_ascii=False)) > MAX_SHEET_BYTES:
        raise CalcError("hesap tablosu çok büyüdü (en fazla %d KB)" % (MAX_SHEET_BYTES // 1024))
    return new


def _age_days(at: Any) -> float:
    try:
        return (_dt.datetime.now() - _dt.datetime.fromisoformat(str(at)[:19])).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return 1e9


def _requests(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ServiceError("items listesi gerekli")
    if len(items) > MAX_EVAL_ITEMS:
        raise ServiceError("bir istekte en fazla %d hesap tablosu istenebilir" % MAX_EVAL_ITEMS)
    out: List[Dict[str, Any]] = []
    keys = set()
    for x in items:
        if not isinstance(x, dict):
            raise ServiceError("hesap tablosu isteği geçersiz")
        try:
            sid = _sheet_id(x.get("sheet"))
        except CalcError as exc:
            raise ServiceError(str(exc))
        key = x.get("key", sid)
        if not isinstance(key, str) or not 0 < len(key) <= 60 or key in keys:
            raise ServiceError("hesap tablosu isteğinin anahtarı geçersiz")
        keys.add(key)
        num = lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None      # noqa: E731
        out.append({"key": key, "sheet": sid, "since": num(x.get("since")), "rev": num(x.get("rev"))})
    return out


def _answer(ent: Dict[str, Any], r: Dict[str, Any]) -> Dict[str, Any]:
    """What the browser gets of an evaluation: ``unchanged`` when it has this revision of the sheet and nothing it shows
    changed since the generation it has."""
    if r.get("since") is not None and r.get("rev") == ent["rev"] and ent["content"] <= r["since"]:
        return {"gen": ent["checked"], "rev": ent["rev"], "unchanged": True}
    return dict(ent["answer"], gen=ent["checked"], rev=ent["rev"])


# ---------------------------------------------------------------------------------------------- display
def _plain(v: Any) -> Any:
    """A formula's result as a cell holds it (an array / range: its first value; empty: 0, as Excel shows)."""
    t = type(v)
    if t is float:
        return v if v - v == 0.0 else E_NUM
    if t is str or t is bool or t is XlError:
        return v
    if v is None:
        return 0.0
    if t is int:
        return float(v)
    if t is XlRange:
        return _plain(v.cell(0, 0))
    if t is XlArray:
        return _plain(v.rows[0][0] if v.rows and v.rows[0] else None)
    return E_VALUE


def _show(v: Any, fmt: Optional[str], loc) -> Dict[str, Any]:
    t = type(v)
    if v is None:
        return {"t": "", "k": ""}
    if t is bool:
        return {"t": "TRUE" if v else "FALSE", "k": "b"}
    if t is XlError:
        return {"t": v.code, "k": "e"}
    if t is str:
        return {"t": numfmt.render(v, fmt or "General", loc)[0], "k": "s"}
    text, color = numfmt.render(v, fmt or "General", loc, general_digits=10)
    out = {"t": text.strip(), "k": "d" if fmt and numfmt.is_date_format(fmt) else "n", "v": v}
    tone = {"red": "neg", "green": "pos", "blue": "info"}.get(color or "")
    if tone:
        out["c"] = tone
    return out


def _edit_text(v: Any, fmt: Optional[str], loc) -> str:
    """A constant as the formula bar shows it - and as it reads back when typed again."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if fmt and numfmt.is_date_format(fmt):
            return numfmt.render(v, fmt, loc)[0]
        if fmt and numfmt.is_percent_format(fmt):
            return numfmt.general(v * 100.0, loc, 15) + "%"
        return numfmt.general(v, loc, 15)
    s = str(v)
    return "'" + s if _looks_typed(s, loc.code) else s


# ---------------------------------------------------------------------------------------------- evaluation
class _Ctx(object):
    """What a compiled formula of a calc sheet reads through (``X`` of ``f(X, S, r, c)``): the sheet's own cells (sheet
    0) and the workbooks' (a slot each), every workbook through the user's own calculation of it - the masks of what is
    read are collected there (``Calc.track``), so that the next request knows whether anything changed since."""

    def __init__(self, owner: "CalcSheets", user: str, sheet: Dict[str, Any], admin: bool):
        self.owner = owner
        self.user = user
        self.cells = sheet["cells"]
        self.fmt = sheet["fmt"]
        self.nrows, self.ncols = sheet["rows"], sheet["cols"]
        self.admin = admin
        self.memo: Dict[Tuple[int, int], Any] = {}
        self.stack: List[Tuple[int, int]] = []          # own cells being evaluated (a cycle is found on it)
        self.busy: set = set()
        self.notes: Dict[Tuple[int, int], str] = {}     # own cell -> what its error means
        self.calcs: Dict[str, List[Any]] = {}           # book -> [calc, its track before, (serial, layout, epoch)]
        self.extra: Dict[str, int] = {}                 # book -> bits read outside Calc.get (the clock)
        self.books: Dict[int, Tuple[Any, int]] = {}     # slot -> (calc or None: not this user's, sheet index)
        self.reads = 0
        self.deadline = time.monotonic() + EVAL_SECONDS

    # ------------------------------------------------------------------ the limits
    def _tick(self) -> None:
        if time.monotonic() > self.deadline:
            raise _Stop(TIME_NOTE % EVAL_SECONDS)

    def _read(self, n: int) -> None:
        before = self.reads
        self.reads += n
        if self.reads > MAX_READS:
            raise _Stop(READS_NOTE % MAX_READS)
        if (before >> 8) != (self.reads >> 8):
            self._tick()

    def _note(self, text: str) -> None:
        if self.stack:
            self.notes.setdefault(self.stack[-1], text)

    # ------------------------------------------------------------------ the workbooks
    def _acquire(self, bid: str):
        got = self.calcs.get(bid)
        if got is None:
            calc = self.owner.svc._calc(self.user, self.owner.svc.books[bid])
            got = self.calcs[bid] = [calc, calc.track, (calc.serial, calc.engine.layout, calc.epoch)]
            calc.track = 0
        return got[0]

    def _book(self, si: int) -> Tuple[Any, int]:
        got = self.books.get(si)
        if got is None:
            bid, wsi = self.owner._slot_of[si]
            calc = None if ((bid, wsi) in self.owner._admin_only and not self.admin) else self._acquire(bid)
            got = self.books[si] = (calc, wsi)
        if got[0] is None:
            bid, wsi = self.owner._slot_of[si]
            self._note(ADMIN_NOTE % self.owner.svc.books[bid].model.sheets[wsi].name)
        return got

    def release(self) -> Dict[str, Tuple[int, int, int, int]]:
        """What was read, book by book: (calculation, layout, epoch, mask) - and every calculation's tracking as it was."""
        metas = {}
        for bid, (calc, before, (serial, layout, epoch)) in self.calcs.items():
            mask = (calc.track or 0) | self.extra.get(bid, 0)
            calc.track = before
            metas[bid] = (serial, layout, epoch, mask)
        self.calcs = {}
        return metas

    # ------------------------------------------------------------------ what compiled formulas call
    def cv(self, si: int, r: int, c: int) -> Any:
        if si == 0:
            return self.own(r, c)
        calc, wsi = self._book(si)
        if calc is None:
            return E_REF
        self._read(1)
        try:
            return calc.get(wsi, r, c)
        except Exception:  # noqa: BLE001 - a workbook cell that cannot be computed: an error of this one
            return E_CALC

    def rg(self, si: int, r1: int, c1: int, r2: int, c2: int) -> XlRange:
        return XlRange(self, si, r1, c1, r2, c2)

    def cols(self, si: int, c1: int, c2: int) -> XlRange:
        if si == 0:
            return XlRange(self, si, 1, c1, self.nrows, c2)
        bid, wsi = self.owner._slot_of[si]
        return XlRange(self, si, 1, c1, max(self.owner.svc.books[bid].engine.max_row[wsi], 1), c2)

    def rows(self, si: int, r1: int, r2: int) -> XlRange:
        if si == 0:
            return XlRange(self, si, r1, 1, r2, self.ncols)
        bid, wsi = self.owner._slot_of[si]
        return XlRange(self, si, r1, 1, r2, max(self.owner.svc.books[bid].engine.max_col[wsi], 1))

    def range_values(self, si: int, r1: int, c1: int, r2: int, c2: int) -> List[List[Any]]:
        if si == 0:
            return [[self.own(r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
        n = (r2 - r1 + 1) * (c2 - c1 + 1)
        if n > MAX_RANGE:
            raise _Stop(RANGE_NOTE % MAX_RANGE)
        calc, wsi = self._book(si)
        if calc is None:
            return [[E_REF] * (c2 - c1 + 1) for _ in range(r2 - r1 + 1)]
        self._read(n)
        try:
            return calc.get_range(wsi, r1, c1, r2, c2)
        except Exception:  # noqa: BLE001
            return [[E_CALC] * (c2 - c1 + 1) for _ in range(r2 - r1 + 1)]

    def range_flat(self, si: int, r1: int, c1: int, r2: int, c2: int) -> List[Any]:
        rows = self.range_values(si, r1, c1, r2, c2)
        if len(rows) == 1:
            return list(rows[0])
        if c1 == c2:
            return [row[0] for row in rows]
        return [x for row in rows for x in row]

    def _clock(self, which: str) -> float:
        bid = "tto" if "tto" in self.owner.svc.books else next(iter(self.owner.svc.books))
        eng = self._acquire(bid).engine
        self.extra[bid] = self.extra.get(bid, 0) | eng.bit(("clock", which))
        return eng.clock.today() if which == "today" else eng.clock.now()

    def today(self) -> float:
        return self._clock("today")

    def now(self) -> float:
        return self._clock("now")

    def addin(self, name: str, si: int, r: int, c: int, args) -> Any:
        # (refused as it is typed: never compiled; a sheet kept by another version that has one answers this)
        self._note(BLOOMBERG % name)
        return E_NAME

    # ------------------------------------------------------------------ the sheet's own cells
    def top(self, r: int, c: int) -> Any:
        try:
            return self.own(r, c)
        except _Stop as stop:
            self.stack = []
            self.busy = set()
            self.notes[(r, c)] = stop.text
            return E_CALC

    def own(self, r: int, c: int) -> Any:
        key = (r, c)
        v = self.memo.get(key, _MISS)
        if v is not _MISS:
            return v
        raw = self.cells.get(cell_name(r, c)) if 1 <= r <= MAX_ROWS and 1 <= c <= MAX_COLS else None
        if raw is None:
            return None
        if not _is_formula(raw):
            v = self.memo[key] = _const(raw)
            return v
        if key in self.busy:
            ring = self.stack[self.stack.index(key):]
            text = "Döngüsel başvuru: " + " → ".join(cell_name(*k) for k in ring + [key])
            for k in ring:
                self.notes.setdefault(k, text)
            return E_CALC
        self._tick()
        self.stack.append(key)
        self.busy.add(key)
        try:
            v = self.owner._run(self, raw, r, c)
        except _Stop:
            raise
        except Exception as exc:  # noqa: BLE001 - a function that failed: this cell's error, the others go on
            self.notes.setdefault(key, "Hesaplanamadı: %s" % (str(exc)[:120] or type(exc).__name__))
            v = E_VALUE
        finally:
            self.stack.pop()
            self.busy.discard(key)
        v = self.memo[key] = _plain(v)
        return v


class CalcSheets(object):
    """Every user's calc sheets: kept, checked, evaluated (see the module's doc).  ``Service.calcsheets``."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()                   # (one change of the sheets at a time)
        self._tlock = threading.Lock()
        self._users: Dict[str, Dict[str, Dict[str, Any]]] = {}       # user -> sheet id -> sheet, as kept
        self._results: "collections.OrderedDict" = collections.OrderedDict()   # evaluations, see _entry
        self._rlock = threading.Lock()
        self._code: "collections.OrderedDict" = collections.OrderedDict()      # (formula, row, col) -> compiled
        self._compiler: Optional[_Compiler] = None
        self._slots: Optional[Dict[Tuple[str, int], int]] = None
        self._slot_of: List[Any] = []
        self._sheet_names: Dict[str, Dict[str, int]] = {}
        self._admin_only: set = set()

    # ------------------------------------------------------------------ the requests
    def post(self, what: str, user: Optional[str], data: Dict[str, Any], locale: Optional[str] = None,
             role: Optional[str] = None):
        """``POST /api/calc/<what>``, as a future of the answer: ``eval`` brings sheets up to date (the boxes on screen,
        in one request), ``save`` changes one and answers it evaluated."""
        if what == "eval":
            return self.eval_future(user, data.get("items"), locale, role)
        if what == "save":
            return self.save_future(user, data, locale, role)
        raise ServiceError("bilinmeyen işlem: %s" % str(what)[:40], 404)

    def eval_future(self, user: Optional[str], items: Any, locale: Optional[str] = None, role: Optional[str] = None):
        """``items``: ``[{"key", "sheet", "since"?, "rev"?}]`` -> ``{"gen", "sheets": {key: answer}}``; an answer is the
        sheet evaluated (``rows``, ``cols``, ``widths``, ``fmt``, ``cells``: ``{"A1": {"t", "k", "v"?, "f"?, "x"?, "tip"?,
        "fm"?}}``, ``gen``, ``rev``) or ``{"unchanged": true}`` (see _answer).  A sheet nobody wrote yet is empty."""
        key = self.svc.require_user(user)
        reqs = _requests(items)
        sheets = self._sheets(key)
        loc = locale or self.svc.settings.locale
        admin = (role == "admin") if role is not None else self.svc._is_admin(key)
        gen = self.svc.gen
        out: Dict[str, Any] = {}
        todo = []
        for r in reqs:
            sheet = sheets.get(r["sheet"]) or EMPTY
            ent = self._result((key, r["sheet"], loc, admin))
            if ent is not None and ent["rev"] == sheet["rev"] and ent["checked"] == gen:
                out[r["key"]] = _answer(ent, r)
            else:
                todo.append((r, sheet))
        if not todo:
            return _done({"gen": gen, "sheets": out})
        job = self.svc.et.submit_at(EngineThread.VIEW, self._eval_job, key, todo, loc, gen, admin)
        return _then(job, lambda res: {"gen": gen, "sheets": dict(out, **res)})

    def save_future(self, user: Optional[str], data: Any, locale: Optional[str] = None, role: Optional[str] = None):
        """Change one of the user's sheets (``{"sheet", "cells"?, "copy"?, "fmt"?, "widths"?, "rows"?, "cols"?}``, see
        _changed; all of it or - a cell refused, with what is wrong - nothing) and answer it evaluated."""
        key = self.svc.require_user(user)
        if not isinstance(data, dict):
            raise ServiceError("geçersiz istek")
        loc = locale or self.svc.settings.locale
        try:
            sid = _sheet_id(data.get("sheet"))
            with self._lock:
                sheets = self._load(key)
                cur = sheets.get(sid) or _empty()
                new = _changed(cur, data, loc, sheets, sid)
                if new is not cur:
                    new["rev"] = cur["rev"] + 1
                    new["at"] = now_iso()
                    every = dict(sheets)
                    every[sid] = new
                    self._put(key, self._pruned(key, every, (sid,)))
        except CalcError as exc:
            raise ServiceError(str(exc))
        admin = (role == "admin") if role is not None else self.svc._is_admin(key)
        req = {"key": "s", "sheet": sid, "since": None, "rev": None}
        job = self.svc.et.submit_at(EngineThread.WRITE, self._eval_job, key, [(req, new)], loc, self.svc.gen, admin)
        return _then(job, lambda res: res["s"])

    # ------------------------------------------------------------------ the launchpad as a file
    def exported(self, user: Optional[str], lp: Dict[str, Any]) -> Dict[str, Any]:
        """A launchpad going out as a file: each calc item carries its sheet's cells (``data``)."""
        if not any(it.get("type") == "calc" for it in lp.get("items", [])):
            return lp
        sheets = self._sheets(self.svc.require_user(user))
        items = []
        for it in lp["items"]:
            if it.get("type") == "calc":
                sh = sheets.get(it.get("sheet")) or EMPTY
                it = dict(it, data={k: sh[k] for k in ("rows", "cols", "cells", "fmt", "widths")})
            items.append(it)
        return dict(lp, items=items)

    def imported(self, user: Optional[str], data: Any) -> Any:
        """A launchpad file coming in: each calc item's cells (``data``) a new sheet of the importing user's own - checked
        as typed ones are (a Bloomberg function refuses the file) - and the item naming it."""
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return data
        if not any(isinstance(x, dict) and x.get("type") == "calc" for x in data["items"]):
            return data
        key = self.svc.require_user(user)
        made: Dict[str, Dict[str, Any]] = {}
        items = []
        try:
            for x in data["items"]:
                if isinstance(x, dict) and x.get("type") == "calc":
                    sheet = _clean(x.get("data") if x.get("data") is not None else {}, strict=True)
                    if len(json.dumps(sheet, ensure_ascii=False)) > MAX_SHEET_BYTES:
                        raise CalcError("hesap tablosu çok büyük")
                    sheet["rev"], sheet["at"] = 1, now_iso()
                    sid = uuid.uuid4().hex[:12]
                    made[sid] = sheet
                    x = {k: v for k, v in x.items() if k != "data"}
                    x["sheet"] = sid
                items.append(x)
            with self._lock:
                every = dict(self._load(key))
                every.update(made)
                self._put(key, self._pruned(key, every, tuple(made)))
        except CalcError as exc:
            raise ServiceError("içe aktarılan hesap tablosu: %s" % exc)
        return dict(data, items=items)

    # ------------------------------------------------------------------ kept with the account
    def _load(self, key: str) -> Dict[str, Dict[str, Any]]:
        got = self._users.get(key)
        if got is None:
            got = self._users[key] = _kept(self.svc.store.get("calc." + key))
        return got

    def _sheets(self, key: str) -> Dict[str, Dict[str, Any]]:
        """The user's sheets as kept (a snapshot: a change replaces the sheet, never alters it)."""
        got = self._users.get(key)
        if got is None:
            with self._lock:
                got = self._load(key)
        return got

    def _put(self, key: str, sheets: Dict[str, Dict[str, Any]]) -> None:
        if len(json.dumps(sheets, ensure_ascii=False)) > MAX_USER_BYTES:
            raise CalcError("hesap tablolarınız çok büyüdü - birkaçını boşaltın ya da kaldırın")
        self.svc.store.put("calc." + key, {"sheets": sheets})
        self._users[key] = sheets

    def _referenced(self, key: str) -> set:
        """The sheets the user's launchpads and drawer name."""
        layout = lay.stored(self.svc.store.get("layout." + key))
        items = list(layout["drawer"]) + [it for lp in layout["launchpads"] for it in lp["items"]]
        return {it.get("sheet") for it in items if it.get("type") == "calc"}

    def _pruned(self, key: str, sheets: Dict[str, Dict[str, Any]], keep: Tuple[str, ...]) -> Dict[str, Dict[str, Any]]:
        """Sheets no item names any more go some days after their last change; over the cap, the oldest of them first."""
        used = self._referenced(key) | set(keep)
        out = {sid: sh for sid, sh in sheets.items() if sid in used or _age_days(sh.get("at")) <= ORPHAN_DAYS}
        if len(out) > MAX_SHEETS:
            loose = sorted((sid for sid in out if sid not in used), key=lambda s: out[s].get("at") or "")
            for sid in loose[:len(out) - MAX_SHEETS]:
                del out[sid]
        if len(out) > MAX_SHEETS:
            raise CalcError("en fazla %d hesap tablosu olabilir - birini kaldırın" % MAX_SHEETS)
        return out

    # ------------------------------------------------------------------ evaluations kept
    def _result(self, ck: Tuple) -> Optional[Dict[str, Any]]:
        with self._rlock:
            return self._results.get(ck)

    def _keep(self, ck: Tuple, ent: Dict[str, Any]) -> None:
        with self._rlock:
            self._results.pop(ck, None)
            self._results[ck] = ent
            while len(self._results) > RESULTS_KEPT:
                self._results.popitem(last=False)

    def _eval_job(self, key: str, todo, loc: str, gen: int, admin: bool) -> Dict[str, Any]:
        """Calculation thread: the sheets asked for, each as of ``gen`` - as many as JOB_SECONDS allow (at least one):
        the thread is everybody's, a sheet left out is answered when the browser asks again."""
        t0 = time.monotonic()
        out: Dict[str, Any] = {}
        for r, sheet in todo:
            if out and time.monotonic() - t0 > JOB_SECONDS:
                break
            out[r["key"]] = _answer(self._entry(key, r["sheet"], sheet, loc, gen, admin), r)
        return out

    def _entry(self, key: str, sid: str, sheet: Dict[str, Any], loc: str, gen: int, admin: bool) -> Dict[str, Any]:
        """The sheet evaluated as of ``gen``: the one kept when this revision of it was evaluated and nothing it read
        changed since, or evaluated again.  ``content``: the generation its answer last changed in."""
        ck = (key, sid, loc, admin)
        old = self._result(ck)
        if old is not None and old["rev"] == sheet["rev"]:
            if old["checked"] == gen:
                return old
            if self._still(key, old["metas"]):
                ent = dict(old, checked=gen)
                self._keep(ck, ent)
                return ent
        answer, metas = self._evaluate(key, sheet, loc, admin)
        same = old is not None and old["answer"] == answer
        ent = {"rev": sheet["rev"], "metas": metas, "answer": answer, "content": old["content"] if same else gen,
               "checked": gen}
        self._keep(ck, ent)
        return ent

    def _still(self, key: str, metas: Dict[str, Tuple[int, int, int, int]]) -> bool:
        """Whether nothing a sheet read changed since it was evaluated: the same calculation of each book (the user's own,
        or everybody's), no invalidation since that meets the masks of what was read."""
        for bid, (serial, layout, epoch, mask) in metas.items():
            book = self.svc.books.get(bid)
            if book is None:
                return False
            calc = self.svc._calc(key, book)
            if calc.serial != serial or calc.engine.layout != layout:
                return False
            m = calc.changed_since(epoch)
            if m is None or m & mask:
                return False
        return True

    # ------------------------------------------------------------------ compiling, evaluating (calculation thread)
    def _tables(self) -> None:
        """The workbooks' sheets numbered together (a compiled reference names its slot), their names without case, and
        the sheets only an administrators' page shows."""
        if self._slots is not None:
            return
        with self._tlock:
            if self._slots is not None:
                return
            slots: Dict[Tuple[str, int], int] = {}
            slot_of: List[Any] = [None]                 # (slot 0: the calc sheet itself)
            for bid, book in self.svc.books.items():
                names = {}
                for s in book.model.sheets:
                    slots[(bid, s.index)] = len(slot_of)
                    slot_of.append((bid, s.index))
                    names.setdefault(_fold(s.name), s.index)
                self._sheet_names[bid] = names
            shown, admin = set(), set()
            for v in self.svc.views:
                book = self.svc.books.get(v["book"])
                if book is None:
                    continue
                for name in {v.get("sheet")} | {p.get("sheet") for p in v.get("panels", []) if p.get("sheet")}:
                    if name in book.model.sheet_index:
                        (admin if v.get("admin") else shown).add((v["book"], book.model.sheet_index[name]))
            self._admin_only = admin - shown
            self._slot_of = slot_of
            self._slots = slots

    def _resolve(self, name: str) -> Optional[int]:
        """A sheet named in a formula -> its slot (None: no such book or sheet)."""
        self._tables()
        bid, sheet = _split_book(name)
        names = self._sheet_names.get(bid)
        si = names.get(_fold(sheet.strip())) if names is not None else None
        return None if si is None else self._slots[(bid, si)]

    def _compiler_now(self) -> _Compiler:
        comp = self._compiler
        if comp is None or comp._nconst > 5000:          # (array constants pile up in its namespace)
            tto = self.svc.books.get("tto")
            comp = self._compiler = _Compiler(tto.model if tto is not None else _NoNames(), self._resolve)
        return comp

    def _compile(self, text: str, r: int, c: int):
        """A formula of the cell (r, c) -> (function or None, notes, lead): compiled once (references are relative)."""
        ck = (text, r, c)
        hit = self._code.get(ck)
        if hit is not None:
            self._code.move_to_end(ck)
            return hit
        fn = None
        notes: Dict[str, Any] = {}
        tree = None
        try:
            tpl = to_template(normalise(text), r, c)
            tree = parse_template(tpl)
        except Exception:  # noqa: BLE001 - kept by another version: said in the cell
            notes["bad"] = True
        if tree is not None:
            notes = self._notes(tree)
            if not notes.get("bloomberg"):
                comp = self._compiler_now()
                try:
                    space: Dict[str, Any] = {}
                    exec(compile(comp.source(tpl), "<calc>", "exec"), comp.ns, space)
                    fn = space["f"]
                except Exception:  # noqa: BLE001
                    notes["bad"] = True
        hit = (fn, notes, _lead(tree, self._names()) if tree is not None else None)
        self._code[ck] = hit
        while len(self._code) > CODE_KEPT:
            self._code.popitem(last=False)
        return hit

    def _names(self) -> Dict[str, str]:
        """The desk workbook's names (``SPOTDATE`` …): a formula may use them."""
        tto = self.svc.books.get("tto")
        return tto.model.names if tto is not None else {}

    def _notes(self, tree) -> Dict[str, Any]:
        """What a formula names that is not there: a function, a name, a sheet or book (said in the cell's error)."""
        names = self._names()
        lets = set()
        for nd in walk(tree):
            if nd[0] == "func" and nd[1] == "LET":
                lets.update(a[1] for a in nd[2][0:-1:2] if a[0] == "name")
        out: Dict[str, Any] = {}
        for nd in walk(tree):
            k = nd[0]
            if k == "func":
                if nd[3] or nd[1] in ADDINS:
                    out.setdefault("bloomberg", nd[1])
                elif nd[1] not in FUNCS and not hasattr(Compiler, "_f_" + nd[1].replace(".", "_")):
                    out.setdefault("function", nd[1])
            elif k == "name":
                if nd[1] not in lets and nd[1] not in names:
                    out.setdefault("name", nd[1])
            elif k in ("cell", "range", "cols", "rows") and nd[1] is not None and self._resolve(nd[1]) is None:
                out.setdefault("sheet", nd[1])
        return out

    def _run(self, ctx: _Ctx, text: str, r: int, c: int) -> Any:
        fn, notes, _ = self._compile(text, r, c)
        if fn is None:
            ctx._note(BLOOMBERG % notes["bloomberg"] if notes.get("bloomberg") else "Formül okunamadı")
            return E_NAME
        return fn(ctx, 0, r, c)

    def _tip(self, text: str, r: int, c: int, v: XlError) -> str:
        """What a formula's error means: what it names that is not there, or the error's own meaning."""
        _, notes, _ = self._compile(text, r, c)
        if v is E_NAME and notes.get("function"):
            return "Bilinmeyen işlev: %s (işlev adları İngilizce: SUM, IF, ROUND …)" % notes["function"]
        if v is E_NAME and notes.get("name"):
            return "Bilinmeyen ad: %s" % notes["name"]
        if v is E_REF and notes.get("sheet"):
            bid, sheet = _split_book(notes["sheet"])
            if bid not in self.svc.books:
                return "Böyle bir kitap yok: [%s] (kitaplar: %s)" % (bid, ", ".join(self.svc.books))
            return "Böyle bir sayfa yok: %s%s" % (sheet, "" if bid == "tto" else " ([%s] kitabında)" % bid)
        return TIPS.get(v.code, "")

    def _fmt_of(self, ctx: _Ctx, r: int, c: int, depth: int = 0) -> Optional[str]:
        """A cell's number format: its own, or - a formula's - that of the reference it leads with (``=Forward!D2`` is
        shown as the date it is, ``=MASA!I60+25`` as the spread is)."""
        a = cell_name(r, c)
        if ctx.fmt.get(a):
            return ctx.fmt[a]
        raw = ctx.cells.get(a)
        if not _is_formula(raw) or depth > 8:
            return None
        lead = self._compile(raw, r, c)[2]
        if lead is None:
            return None
        if lead[0] == "fmt":
            return lead[1]
        _, sheet, ra, rr, ca, cc = lead
        row, col = (rr if ra else r + rr), (cc if ca else c + cc)
        if sheet is None:
            return self._fmt_of(ctx, row, col, depth + 1) if 1 <= row <= MAX_ROWS and 1 <= col <= MAX_COLS else None
        slot = self._resolve(sheet)
        if slot is None:
            return None
        bid, si = self._slot_of[slot]
        model = self.svc.books[bid].model
        xi = model.sheets[si].styles.get(row * COLS + col, 0)
        fmt = model.xfs[xi][0] if xi < len(model.xfs) else None
        return fmt if fmt and fmt != "General" else None

    def _evaluate(self, key: str, sheet: Dict[str, Any], loc_code: str, admin: bool):
        """Every cell of the sheet, evaluated as the user's pages are -> (answer, what it read of each book)."""
        self._tables()
        loc = numfmt.get_locale(loc_code)
        ctx = _Ctx(self, key, sheet, admin)
        order = sorted((parse_cell(a), a) for a in sheet["cells"])
        values: Dict[str, Any] = {}
        try:
            for (r, c), a in order:
                values[a] = ctx.top(r, c)
        finally:
            metas = ctx.release()
        cells: Dict[str, Any] = {}
        for (r, c), a in order:
            raw = sheet["cells"][a]
            own = sheet["fmt"].get(a)
            fmt = own or (self._fmt_of(ctx, r, c) if _is_formula(raw) else None)
            v = values[a]
            out = _show(v, fmt, loc)
            if _is_formula(raw):
                out["f"] = raw
            else:
                out["x"] = _edit_text(_const(raw), fmt, loc)
            if fmt and not own:
                out["fm"] = fmt
            if type(v) is XlError:
                tip = ctx.notes.get((r, c)) or (self._tip(raw, r, c, v) if _is_formula(raw) else "")
                if tip:
                    out["tip"] = tip
            cells[a] = out
        return ({"rows": sheet["rows"], "cols": sheet["cols"], "widths": dict(sheet["widths"]), "fmt": dict(sheet["fmt"]),
                 "cells": cells}, metas)
