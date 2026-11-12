"""Formula tokenizers.

Two lexers live here:

* :func:`tokenize_a1` reads formulas exactly as stored in an ``.xlsx`` file (A1 notation,
  US syntax) and is used once, at import time.
* :func:`to_template` rewrites such a formula into a *position independent template*: every
  cell / range reference is replaced by a back-tick token in relative R1C1 form, e.g.
  ``=A1*$B$2`` hosted in ``C3`` becomes ``=`R[-2]C[-2]`*`R2C2```.  All cells that were filled
  down / across from one formula therefore share one template, which is parsed and compiled once.
* :func:`tokenize_template` lexes a template for the parser.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

MAX_ROW = 1048576
MAX_COL = 16384

_ERRORS = r"\#N/A|\#DIV/0!|\#VALUE!|\#REF!|\#NAME\?|\#NUM!|\#NULL!|\#GETTING_DATA|\#SPILL!|\#CALC!"
_IDENT_START = r"A-Za-z_\\À-￿"
_IDENT_CONT = r"\w.\\À-￿"

_A1_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<err>%(err)s)
  | (?P<sheet>(?:'(?:[^']|'')+'|[%(s)s][%(c)s]*)!)
  | (?P<colrange>\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}(?![%(c)s(!]))
  | (?P<rowrange>\$?\d{1,7}:\$?\d{1,7}(?![%(c)s]))
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?)
  | (?P<cell>\$?[A-Za-z]{1,3}\$?\d{1,7}(?![%(c)s(]))
  | (?P<func>[%(s)s][%(c)s]*\()
  | (?P<name>[%(s)s][%(c)s]*)
  | (?P<op><=|>=|<>|[-+*/^&=<>%%,;:(){}@])
    """
    % {"err": _ERRORS, "s": _IDENT_START, "c": _IDENT_CONT},
    re.X,
)

Token = Tuple[str, str]


class FormulaSyntaxError(ValueError):
    pass


def tokenize_a1(formula: str) -> List[Token]:
    """Tokenize an A1-notation formula (with or without the leading ``=``)."""
    pos = 1 if formula.startswith("=") else 0
    out: List[Token] = []
    n = len(formula)
    match = _A1_RE.match
    while pos < n:
        m = match(formula, pos)
        if m is None:
            raise FormulaSyntaxError("cannot tokenize %r at %d: %r" % (formula, pos, formula[pos:pos + 20]))
        kind = m.lastgroup
        out.append((kind, m.group()))
        pos = m.end()
    return out


def col_to_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def index_to_col(n: int) -> str:
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


_CELL_PARTS = re.compile(r"(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})$")


def split_cell(text: str) -> Tuple[bool, int, bool, int]:
    """``$B$12`` -> (col_abs, col, row_abs, row)."""
    m = _CELL_PARTS.match(text)
    if m is None:
        raise FormulaSyntaxError("bad cell reference %r" % text)
    return bool(m.group(1)), col_to_index(m.group(2)), bool(m.group(3)), int(m.group(4))


def is_valid_cell(text: str) -> bool:
    m = _CELL_PARTS.match(text)
    if m is None:
        return False
    return col_to_index(m.group(2)) <= MAX_COL and 1 <= int(m.group(4)) <= MAX_ROW


def _rel(abs_: bool, value: int, base: int, letter: str) -> str:
    if abs_:
        return "%s%d" % (letter, value)
    d = value - base
    return letter if d == 0 else "%s[%d]" % (letter, d)


def _cell_r1c1(text: str, row: int, col: int) -> str:
    cabs, c, rabs, r = split_cell(text)
    return _rel(rabs, r, row, "R") + _rel(cabs, c, col, "C")


def unquote_sheet(tok: str) -> str:
    name = tok[:-1]
    if name.startswith("'"):
        name = name[1:-1].replace("''", "'")
    return name


def to_template(formula: str, row: int, col: int) -> str:
    """Rewrite an A1 formula hosted at (row, col) into its relative template string."""
    toks = tokenize_a1(formula)
    out: List[str] = []
    i = 0
    n = len(toks)
    while i < n:
        kind, text = toks[i]
        sheet: Optional[str] = None
        if kind == "sheet":
            sheet = unquote_sheet(text)
            i += 1
            if i >= n:
                raise FormulaSyntaxError("dangling sheet prefix in %r" % formula)
            kind, text = toks[i]
            if kind not in ("cell", "colrange", "rowrange", "name", "err"):
                raise FormulaSyntaxError("unsupported token after sheet prefix in %r" % formula)
        if kind == "cell" and is_valid_cell(text):
            ref = _cell_r1c1(text, row, col)
            # A1:B2 (second corner may not carry a sheet prefix)
            if i + 2 < n and toks[i + 1] == ("op", ":") and toks[i + 2][0] == "cell" and is_valid_cell(toks[i + 2][1]):
                ref += ":" + _cell_r1c1(toks[i + 2][1], row, col)
                i += 2
            out.append("`%s%s`" % ((sheet.replace("`", "") + "!") if sheet is not None else "", ref))
        elif kind == "colrange":
            a, b = text.split(":")
            ca = a.startswith("$")
            cb = b.startswith("$")
            ref = _rel(ca, col_to_index(a.lstrip("$")), col, "C") + ":" + _rel(cb, col_to_index(b.lstrip("$")), col, "C")
            out.append("`%s%s`" % ((sheet + "!") if sheet is not None else "", ref))
        elif kind == "rowrange":
            a, b = text.split(":")
            ra = a.startswith("$")
            rb = b.startswith("$")
            ref = _rel(ra, int(a.lstrip("$")), row, "R") + ":" + _rel(rb, int(b.lstrip("$")), row, "R")
            out.append("`%s%s`" % ((sheet + "!") if sheet is not None else "", ref))
        elif sheet is not None:
            if kind == "err":       # Sheet!#REF!
                out.append("#REF!")
            else:                   # sheet-scoped defined name
                out.append("`%s!%s`" % (sheet, "N:" + text))
        elif kind == "ws":
            pass
        elif kind == "cell":        # looks like a cell but out of the grid -> it is a name (e.g. LOG10, ABC99999999)
            out.append(text)
        else:
            out.append(text)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- template lexer
_TPL_RE = re.compile(
    r"""
    (?P<ref>`[^`]*`)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<err>%(err)s)
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?)
  | (?P<func>[%(s)s][%(c)s]*\()
  | (?P<name>[%(s)s][%(c)s]*)
  | (?P<op><=|>=|<>|[-+*/^&=<>%%,;:(){}@])
    """
    % {"err": _ERRORS, "s": _IDENT_START, "c": _IDENT_CONT},
    re.X,
)


def tokenize_template(template: str) -> List[Token]:
    out: List[Token] = []
    pos = 0
    n = len(template)
    match = _TPL_RE.match
    while pos < n:
        m = match(template, pos)
        if m is None:
            raise FormulaSyntaxError("cannot tokenize template %r at %d" % (template, pos))
        out.append((m.lastgroup, m.group()))
        pos = m.end()
    return out


_RC_PART = re.compile(r"R(\[-?\d+\]|\d+)?C(\[-?\d+\]|\d+)?$")
_R_ONLY = re.compile(r"R(\[-?\d+\]|\d+)?$")
_C_ONLY = re.compile(r"C(\[-?\d+\]|\d+)?$")


def _coord(part: Optional[str]) -> Tuple[bool, int]:
    """'[−3]' -> (False, -3) relative ; '12' -> (True, 12) absolute ; None -> (False, 0)."""
    if part is None or part == "":
        return (False, 0)
    if part.startswith("["):
        return (False, int(part[1:-1]))
    return (True, int(part))


def parse_ref_token(tok: str):
    """Decode a back-tick reference token.

    Returns ``(sheet, kind, payload)`` where kind is

    * ``"cell"``  payload = (row_abs, row, col_abs, col)
    * ``"range"`` payload = (ra1, r1, ca1, c1, ra2, r2, ca2, c2)
    * ``"cols"``  payload = (ca1, c1, ca2, c2)      whole columns
    * ``"rows"``  payload = (ra1, r1, ra2, r2)      whole rows
    * ``"name"``  payload = name                    sheet-scoped defined name
    """
    body = tok[1:-1]
    sheet = None
    bang = body.rfind("!")
    if bang >= 0:
        sheet = body[:bang]
        body = body[bang + 1:]
    if body.startswith("N:"):
        return sheet, "name", body[2:]
    if ":" in body:
        a, b = body.split(":")
        ma, mb = _RC_PART.match(a), _RC_PART.match(b)
        if ma and mb:
            ra1, r1 = _coord(ma.group(1))
            ca1, c1 = _coord(ma.group(2))
            ra2, r2 = _coord(mb.group(1))
            ca2, c2 = _coord(mb.group(2))
            return sheet, "range", (ra1, r1, ca1, c1, ra2, r2, ca2, c2)
        ma, mb = _C_ONLY.match(a), _C_ONLY.match(b)
        if ma and mb:
            ca1, c1 = _coord(ma.group(1))
            ca2, c2 = _coord(mb.group(1))
            return sheet, "cols", (ca1, c1, ca2, c2)
        ma, mb = _R_ONLY.match(a), _R_ONLY.match(b)
        if ma and mb:
            ra1, r1 = _coord(ma.group(1))
            ra2, r2 = _coord(mb.group(1))
            return sheet, "rows", (ra1, r1, ra2, r2)
        raise FormulaSyntaxError("bad range token %r" % tok)
    m = _RC_PART.match(body)
    if not m:
        raise FormulaSyntaxError("bad ref token %r" % tok)
    ra, r = _coord(m.group(1))
    ca, c = _coord(m.group(2))
    return sheet, "cell", (ra, r, ca, c)
