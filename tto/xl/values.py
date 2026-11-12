"""Runtime value model and operators with Excel semantics.

Scalars are ``float`` (every Excel number), ``str``, ``bool``, ``None`` (empty cell) and
:class:`~tto.xl.errors.XlError`.  Multi-cell values are :class:`XlArray` (in-memory array) and
:class:`XlRange` (a live reference to cells of a sheet).
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any, Callable, List, Optional

from .errors import E_DIV0, E_NA, E_NUM, E_REF, E_VALUE, XlError

_float = float
_inf = float("inf")


class XlArray(object):
    """An in-memory 2-D array (row major)."""

    __slots__ = ("rows", "nr", "nc")

    def __init__(self, rows: List[List[Any]]):
        self.rows = rows
        self.nr = len(rows)
        self.nc = len(rows[0]) if rows else 0

    def values(self) -> List[List[Any]]:
        return self.rows

    def flat(self) -> List[Any]:
        if self.nr == 1:
            return self.rows[0]
        out: List[Any] = []
        for r in self.rows:
            out.extend(r)
        return out

    def __repr__(self):
        return "XlArray(%dx%d)" % (self.nr, self.nc)


class XlRange(object):
    """A reference to a rectangular block of cells; values are pulled lazily through the context."""

    __slots__ = ("ctx", "si", "r1", "c1", "r2", "c2", "nr", "nc")

    def __init__(self, ctx, si: int, r1: int, c1: int, r2: int, c2: int):
        if r1 > r2:
            r1, r2 = r2, r1
        if c1 > c2:
            c1, c2 = c2, c1
        self.ctx = ctx
        self.si = si
        self.r1 = r1
        self.c1 = c1
        self.r2 = r2
        self.c2 = c2
        self.nr = r2 - r1 + 1
        self.nc = c2 - c1 + 1

    def values(self) -> List[List[Any]]:
        return self.ctx.range_values(self.si, self.r1, self.c1, self.r2, self.c2)

    def flat(self) -> List[Any]:
        return self.ctx.range_flat(self.si, self.r1, self.c1, self.r2, self.c2)

    def cell(self, i: int, j: int) -> Any:
        """Value of the cell at zero-based offset (i, j)."""
        return self.ctx.cv(self.si, self.r1 + i, self.c1 + j)

    def sub(self, i1: int, j1: int, i2: int, j2: int) -> "XlRange":
        return XlRange(self.ctx, self.si, self.r1 + i1, self.c1 + j1, self.r1 + i2, self.c1 + j2)

    def __repr__(self):
        return "XlRange(%d!R%dC%d:R%dC%d)" % (self.si, self.r1, self.c1, self.r2, self.c2)


def is_multi(v: Any) -> bool:
    t = type(v)
    return t is XlArray or t is XlRange


# --------------------------------------------------------------------------- dates
_EPOCH = _dt.date(1899, 12, 30)
_EPOCH_ORD = _EPOCH.toordinal()


def serial_to_date(n: float) -> _dt.date:
    """Excel serial -> date (1900 system; serial 60, the fictitious 29-Feb-1900, maps to 28-Feb)."""
    i = int(math.floor(n))
    if i < 61:
        i += 1 if i < 60 else 0
        if i < 1:
            i = 1
        if i == 60:
            return _dt.date(1900, 2, 28)
    return _dt.date.fromordinal(_EPOCH_ORD + i)


def date_to_serial(d: _dt.date) -> float:
    n = d.toordinal() - _EPOCH_ORD
    if n < 61:
        n -= 1
    return float(n)


_DATE_DMY = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\s*$")
_DATE_ISO = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?)?\s*$")
_NUM_PLAIN = re.compile(r"^\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?\s*$")


def parse_number_text(s: str) -> Optional[float]:
    """Text -> number the way Excel coerces text in arithmetic (TR regional settings: d.m.yyyy dates).

    Returns ``None`` when the text is not numeric.
    """
    if _NUM_PLAIN.match(s):
        try:
            return float(s)
        except ValueError:
            return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("%"):
        v = parse_number_text(t[:-1])
        return None if v is None else v / 100.0
    m = _DATE_DMY.match(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000 if y < 30 else 1900
        try:
            base = date_to_serial(_dt.date(y, mo, d))
        except ValueError:
            return None
        if m.group(4) is not None:
            base += (int(m.group(4)) * 3600 + int(m.group(5)) * 60 + int(m.group(6) or 0)) / 86400.0
        return base
    m = _DATE_ISO.match(t)
    if m:
        try:
            base = date_to_serial(_dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return None
        if m.group(4) is not None:
            base += (int(m.group(4)) * 3600 + int(m.group(5)) * 60 + float(m.group(6) or 0)) / 86400.0
        return base
    # 1.234,56 (TR) or 1,234.56 (US) style numbers
    u = t.replace(" ", "")
    if re.match(r"^[+-]?\d{1,3}(\.\d{3})+(,\d+)?$", u) or re.match(r"^[+-]?\d+,\d+$", u):
        try:
            return float(u.replace(".", "").replace(",", "."))
        except ValueError:
            return None
    if re.match(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$", u):
        try:
            return float(u.replace(",", ""))
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- coercions
def to_num(v: Any) -> Any:
    """Coerce a scalar to a number for arithmetic; returns an XlError on failure."""
    t = type(v)
    if t is _float:
        return v
    if v is None:
        return 0.0
    if t is bool:
        return 1.0 if v else 0.0
    if t is str:
        n = parse_number_text(v)
        return E_VALUE if n is None else n
    if t is XlError:
        return v
    if t is int:
        return _float(v)
    if t is XlArray or t is XlRange:
        return to_num(first(v))
    return E_VALUE


def first(v: Any) -> Any:
    """Top-left element of a multi-cell value (identity for scalars)."""
    t = type(v)
    if t is XlArray:
        return v.rows[0][0] if v.nr and v.nc else None
    if t is XlRange:
        return v.cell(0, 0)
    return v


def fmt_general(x: float) -> str:
    """Number -> text as Excel's General format does when concatenating."""
    if x != x:
        return "#NUM!"
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e15:
        return "%d" % int(x)
    ax = abs(x)
    if 1e-9 <= ax < 1e15:
        s = "%.15g" % x
        if "e" in s or "E" in s:
            digits = max(0, 14 - int(math.floor(math.log10(ax))))
            s = ("%.*f" % (digits, x)).rstrip("0").rstrip(".")
        return s
    s = "%.14E" % x
    mant, exp = s.split("E")
    mant = mant.rstrip("0").rstrip(".")
    e = int(exp)
    return "%sE%s%02d" % (mant, "+" if e >= 0 else "-", abs(e))


def to_text(v: Any) -> Any:
    t = type(v)
    if t is str:
        return v
    if v is None:
        return ""
    if t is _float:
        return fmt_general(v)
    if t is bool:
        return "TRUE" if v else "FALSE"
    if t is XlError:
        return v
    if t is int:
        return str(v)
    if t is XlArray or t is XlRange:
        return to_text(first(v))
    return str(v)


def to_bool(v: Any) -> Any:
    """Coerce a scalar to a logical (for IF / AND / OR / NOT); XlError passes through."""
    t = type(v)
    if t is bool:
        return v
    if t is _float:
        return v != 0.0
    if v is None:
        return False
    if t is str:
        u = v.upper()
        if u == "TRUE":
            return True
        if u == "FALSE":
            return False
        return E_VALUE
    if t is XlError:
        return v
    if t is int:
        return v != 0
    if t is XlArray or t is XlRange:
        return to_bool(first(v))
    return E_VALUE


# --------------------------------------------------------------------------- broadcasting
def dims(v: Any):
    t = type(v)
    if t is XlArray or t is XlRange:
        return v.nr, v.nc
    return 1, 1


def as_rows(v: Any) -> List[List[Any]]:
    t = type(v)
    if t is XlArray:
        return v.rows
    if t is XlRange:
        return v.values()
    return [[v]]


def broadcast2(fn: Callable[[Any, Any], Any], a: Any, b: Any) -> Any:
    """Apply a scalar binary operator element-wise with Excel's array broadcasting rules."""
    ra, rb = as_rows(a), as_rows(b)
    na, ma = len(ra), (len(ra[0]) if ra else 0)
    nb, mb = len(rb), (len(rb[0]) if rb else 0)
    nr = na if na > nb else nb
    nc = ma if ma > mb else mb
    out = []
    for i in range(nr):
        if na == 1:
            rowa = ra[0]
        elif i < na:
            rowa = ra[i]
        else:
            rowa = None
        if nb == 1:
            rowb = rb[0]
        elif i < nb:
            rowb = rb[i]
        else:
            rowb = None
        row = []
        for j in range(nc):
            if rowa is None or rowb is None:
                row.append(E_NA)
                continue
            if ma == 1:
                x = rowa[0]
            elif j < ma:
                x = rowa[j]
            else:
                row.append(E_NA)
                continue
            if mb == 1:
                y = rowb[0]
            elif j < mb:
                y = rowb[j]
            else:
                row.append(E_NA)
                continue
            row.append(fn(x, y))
        out.append(row)
    return XlArray(out)


def map1(fn: Callable[[Any], Any], a: Any) -> Any:
    return XlArray([[fn(x) for x in row] for row in as_rows(a)])


# --------------------------------------------------------------------------- arithmetic
def _add(a, b):
    x = to_num(a)
    if type(x) is XlError:
        return x
    y = to_num(b)
    if type(y) is XlError:
        return y
    return x + y


def _sub(a, b):
    x = to_num(a)
    if type(x) is XlError:
        return x
    y = to_num(b)
    if type(y) is XlError:
        return y
    return x - y


def _mul(a, b):
    x = to_num(a)
    if type(x) is XlError:
        return x
    y = to_num(b)
    if type(y) is XlError:
        return y
    return x * y


def _div(a, b):
    x = to_num(a)
    if type(x) is XlError:
        return x
    y = to_num(b)
    if type(y) is XlError:
        return y
    if y == 0.0:
        return E_DIV0
    return x / y


def _pow(a, b):
    x = to_num(a)
    if type(x) is XlError:
        return x
    y = to_num(b)
    if type(y) is XlError:
        return y
    if x == 0.0:
        if y == 0.0:
            return E_NUM
        if y < 0.0:
            return E_DIV0
        return 0.0
    try:
        r = x ** y
    except (OverflowError, ZeroDivisionError):
        return E_NUM
    if type(r) is complex:
        # Excel accepts odd roots of negative numbers only when the exponent is an exact 1/odd
        if y != 0.0:
            inv = 1.0 / y
            if inv == math.floor(inv) and int(inv) % 2 != 0:
                return -((-x) ** y)
        return E_NUM
    if r != r or r == _inf or r == -_inf:
        return E_NUM
    return r


def ADD(a, b):
    if type(a) is _float and type(b) is _float:
        return a + b
    if is_multi(a) or is_multi(b):
        return broadcast2(_add, a, b)
    return _add(a, b)


def SUB(a, b):
    if type(a) is _float and type(b) is _float:
        return a - b
    if is_multi(a) or is_multi(b):
        return broadcast2(_sub, a, b)
    return _sub(a, b)


_EPS = 2.220446049250313e-16


def ADDT(a, b):
    """``+`` as the *last* operation of a formula.

    Excel sets the result of a final addition / subtraction to exactly 0 when it is negligible against
    the operands (below one unit in the last place), e.g. ``=0.1+0.2-0.3`` is 0 while
    ``=(0.1+0.2-0.3)`` is 5.55E-17.
    """
    if type(a) is _float and type(b) is _float:
        r = a + b
        if r != 0.0:
            big = a if a >= 0.0 else -a
            ob = b if b >= 0.0 else -b
            if ob > big:
                big = ob
            if (r if r >= 0.0 else -r) <= big * _EPS:
                return 0.0
        return r
    return ADD(a, b)


def SUBT(a, b):
    """``-`` as the last operation of a formula (see :func:`ADDT`)."""
    if type(a) is _float and type(b) is _float:
        r = a - b
        if r != 0.0:
            big = a if a >= 0.0 else -a
            ob = b if b >= 0.0 else -b
            if ob > big:
                big = ob
            if (r if r >= 0.0 else -r) <= big * _EPS:
                return 0.0
        return r
    return SUB(a, b)


def MUL(a, b):
    if type(a) is _float and type(b) is _float:
        return a * b
    if is_multi(a) or is_multi(b):
        return broadcast2(_mul, a, b)
    return _mul(a, b)


def DIV(a, b):
    if type(a) is _float and type(b) is _float:
        if b == 0.0:
            return E_DIV0
        return a / b
    if is_multi(a) or is_multi(b):
        return broadcast2(_div, a, b)
    return _div(a, b)


def POW(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_pow, a, b)
    return _pow(a, b)


def _neg(a):
    x = to_num(a)
    if type(x) is XlError:
        return x
    return -x


def NEG(a):
    if type(a) is _float:
        return -a
    if is_multi(a):
        return map1(_neg, a)
    return _neg(a)


def _pos(a):
    return a


def POS(a):
    return a


def _pct(a):
    x = to_num(a)
    if type(x) is XlError:
        return x
    return x / 100.0


def PCT(a):
    if is_multi(a):
        return map1(_pct, a)
    return _pct(a)


def _cat(a, b):
    x = to_text(a)
    if type(x) is XlError:
        return x
    y = to_text(b)
    if type(y) is XlError:
        return y
    return x + y


def CAT(a, b):
    if type(a) is str and type(b) is str:
        return a + b
    if is_multi(a) or is_multi(b):
        return broadcast2(_cat, a, b)
    return _cat(a, b)


# --------------------------------------------------------------------------- comparisons
def _sig15(x: float) -> float:
    return _float("%.15g" % x)


def num_eq(a: float, b: float) -> bool:
    """Excel compares numbers on 15 significant digits."""
    if a == b:
        return True
    d = a - b
    if d < 0:
        d = -d
    m = a if a > 0 else -a
    n = b if b > 0 else -b
    if n > m:
        m = n
    if d > m * 1e-14:
        return False
    return _sig15(a) == _sig15(b)


def _rank(v) -> int:
    t = type(v)
    if t is _float or t is int:
        return 0
    if t is str:
        return 1
    if t is bool:
        return 2
    return 3


def compare(a, b) -> Any:
    """Three-way compare with Excel ordering (numbers < text < logicals); returns -1/0/1 or XlError."""
    ta, tb = type(a), type(b)
    if ta is XlError:
        return a
    if tb is XlError:
        return b
    if a is None:
        if b is None:
            return 0
        if tb is str:
            a = ""
        elif tb is bool:
            a = False
        else:
            a = 0.0
        ta = type(a)
    elif b is None:
        if ta is str:
            b = ""
        elif ta is bool:
            b = False
        else:
            b = 0.0
        tb = type(b)
    if ta is _float and tb is _float:
        if num_eq(a, b):
            return 0
        return -1 if a < b else 1
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 1:
        x, y = a.upper(), b.upper()
        if x == y:
            return 0
        return -1 if x < y else 1
    if ra == 2:
        if a == b:
            return 0
        return -1 if (not a and b) else 1
    x, y = _float(a), _float(b)
    if num_eq(x, y):
        return 0
    return -1 if x < y else 1


def _eq(a, b):
    c = compare(a, b)
    if type(c) is XlError:
        return c
    return c == 0


def _ne(a, b):
    c = compare(a, b)
    if type(c) is XlError:
        return c
    return c != 0


def _lt(a, b):
    c = compare(a, b)
    if type(c) is XlError:
        return c
    return c < 0


def _gt(a, b):
    c = compare(a, b)
    if type(c) is XlError:
        return c
    return c > 0


def _le(a, b):
    c = compare(a, b)
    if type(c) is XlError:
        return c
    return c <= 0


def _ge(a, b):
    c = compare(a, b)
    if type(c) is XlError:
        return c
    return c >= 0


def EQ(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_eq, a, b)
    return _eq(a, b)


def NE(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_ne, a, b)
    return _ne(a, b)


def LT(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_lt, a, b)
    return _lt(a, b)


def GT(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_gt, a, b)
    return _gt(a, b)


def LE(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_le, a, b)
    return _le(a, b)


def GE(a, b):
    if is_multi(a) or is_multi(b):
        return broadcast2(_ge, a, b)
    return _ge(a, b)


# --------------------------------------------------------------------------- references
def range_union(a: Any, b: Any) -> Any:
    """The ``:`` operator applied to two references -> bounding rectangle."""
    if type(a) is not XlRange or type(b) is not XlRange or a.si != b.si:
        return E_REF
    return XlRange(a.ctx, a.si, min(a.r1, b.r1), min(a.c1, b.c1), max(a.r2, b.r2), max(a.c2, b.c2))


def intersect(v: Any, row: int, col: int) -> Any:
    """Implicit intersection of ``v`` with the formula cell at (row, col)."""
    t = type(v)
    if t is XlRange:
        if v.nr == 1 and v.nc == 1:
            return v.cell(0, 0)
        if v.nc == 1:
            if v.r1 <= row <= v.r2:
                return v.ctx.cv(v.si, row, v.c1)
            return E_VALUE
        if v.nr == 1:
            if v.c1 <= col <= v.c2:
                return v.ctx.cv(v.si, v.r1, col)
            return E_VALUE
        if v.r1 <= row <= v.r2 and v.c1 <= col <= v.c2:
            return v.ctx.cv(v.si, row, col)
        return E_VALUE
    if t is XlArray:
        return v.rows[0][0] if v.nr and v.nc else None
    return v


def deref(v: Any) -> Any:
    """Turn a single-cell reference into its value; multi-cell references into arrays of values."""
    t = type(v)
    if t is XlRange:
        if v.nr == 1 and v.nc == 1:
            return v.cell(0, 0)
        return XlArray(v.values())
    return v
