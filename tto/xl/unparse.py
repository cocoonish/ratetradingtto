"""AST -> A1 formula text (the inverse of the import step).

Used to show the original Excel formula of a cell in the dashboard and to export a model back to a
plain ``.xlsx`` (see :mod:`tto.xl.export`).
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from .parser import parse_template
from .tokenizer import index_to_col

_XLFN = {"MINIFS", "MAXIFS", "TEXTJOIN", "LET", "SINGLE", "CONCAT", "IFS", "SWITCH", "XLOOKUP", "XMATCH",
         "FILTER", "SORT", "UNIQUE", "SEQUENCE", "STDEV.S", "STDEV.P", "IFNA", "DAYS", "LAMBDA"}
_PLAIN_SHEET = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def quote_sheet(name: str) -> str:
    if _PLAIN_SHEET.match(name) and not re.match(r"^[A-Za-z]{1,3}\d+$", name):
        return name + "!"
    return "'" + name.replace("'", "''") + "'!"


class Unparser(object):
    def __init__(self, row: int, col: int, inline_let: bool = False, strip_single: bool = False,
                 xlfn: bool = False, today: Optional[float] = None, now: Optional[float] = None,
                 names: Optional[Dict[str, str]] = None):
        self.row = row
        self.col = col
        self.inline_let = inline_let
        self.strip_single = strip_single
        self.xlfn = xlfn
        self.today = today
        self.now = now
        self.env: Dict[str, object] = {}

    def _r(self, abs_: bool, v: int) -> str:
        return ("$%d" % v) if abs_ else str(self.row + v)

    def _c(self, abs_: bool, v: int) -> str:
        return ("$" + index_to_col(v)) if abs_ else index_to_col(self.col + v)

    def _sheet(self, sheet) -> str:
        return "" if sheet is None else quote_sheet(sheet)

    def text(self, nd) -> str:
        k = nd[0]
        if k == "num":
            v = nd[1]
            return ("%d" % v) if v == int(v) and abs(v) < 1e15 else repr(v)
        if k == "str":
            return '"' + nd[1].replace('"', '""') + '"'
        if k == "bool":
            return "TRUE" if nd[1] else "FALSE"
        if k == "err":
            return nd[1]
        if k == "missing":
            return ""
        if k == "cell":
            return self._sheet(nd[1]) + self._c(nd[4], nd[5]) + self._r(nd[2], nd[3])
        if k == "range":
            return (self._sheet(nd[1]) + self._c(nd[4], nd[5]) + self._r(nd[2], nd[3]) + ":" +
                    self._c(nd[8], nd[9]) + self._r(nd[6], nd[7]))
        if k == "cols":
            return self._sheet(nd[1]) + self._c(nd[2], nd[3]) + ":" + self._c(nd[4], nd[5])
        if k == "rows":
            return self._sheet(nd[1]) + self._r(nd[2], nd[3]) + ":" + self._r(nd[4], nd[5])
        if k == "name":
            if nd[1] in self.env:
                return "(" + self.text(self.env[nd[1]]) + ")"
            return self._sheet(nd[2]) + nd[1]
        if k == "paren":
            return "(" + self.text(nd[1]) + ")"
        if k == "neg":
            return "-" + self.text(nd[1])
        if k == "pos":
            return "+" + self.text(nd[1])
        if k == "pct":
            return self.text(nd[1]) + "%"
        if k == "single":
            return self.text(nd[1]) if self.strip_single else "@" + self.text(nd[1])
        if k == "bin":
            return self.text(nd[2]) + nd[1] + self.text(nd[3])
        if k == "array":
            return "{" + ";".join(",".join(self.text(x) for x in row) for row in nd[1]) + "}"
        if k == "func":
            name, args, addin = nd[1], nd[2], nd[3]
            if name == "LET" and self.inline_let and len(args) >= 3:
                saved = dict(self.env)
                try:
                    for i in range(0, len(args) - 1, 2):
                        self.env[args[i][1]] = _Frozen(self.text(args[i + 1]))
                    return "(" + self.text(args[-1]) + ")"
                finally:
                    self.env = saved
            if name == "SINGLE" and self.strip_single and len(args) == 1:
                return self.text(args[0])
            if name == "TODAY" and self.today is not None:
                return "%d" % self.today
            if name == "NOW" and self.now is not None:
                return repr(self.now)
            prefix = ""
            if addin:
                prefix = "_xll."
            elif self.xlfn and name in _XLFN:
                prefix = "_xlfn."
            return prefix + name + "(" + ",".join(self.text(a) for a in args) + ")"
        raise ValueError("cannot unparse %r" % (k,))


class _Frozen(tuple):
    """An already rendered LET binding (rendered once, in the scope where it was defined)."""

    def __new__(cls, text):
        return tuple.__new__(cls, ("frozen", text))


_orig_text = Unparser.text


def _text(self, nd):
    if nd[0] == "frozen":
        return nd[1]
    return _orig_text(self, nd)


Unparser.text = _text


def to_a1(template: str, row: int, col: int, **options) -> str:
    """Render a formula template as A1 text for the host cell (row, col); no leading ``=``."""
    return Unparser(row, col, **options).text(parse_template(template))
