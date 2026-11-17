"""Which cells hold a date - read from the formulas -, shown as dates; and where a date typed into one counts from.

The workbooks format their dates as dates, nearly all of them.  Some hold a date in a cell formatted as a number: the
Forward DV01 table's Start is ``=+I2`` - the USDTRY spot date - in an accounting format (``46.344,0000`` on the page,
as in Excel), DİBS RV's value dates are ``WORKDAY(…)`` in General cells.  Which cells hold a date is a property of their
formulas - a type propagation over the workbook (:class:`DateCells`):

* a cell formatted as a date is a date; ``TODAY()``, ``DATE``, ``EDATE``, ``EOMONTH``, ``WORKDAY`` give one, and so does
  a Bloomberg field that is a date (``SETTLE_DT``, ``MATURITY``, ``LAST_TRADE_DATE`` … - a text "04.11.2026" live);
* a reference passes its cell's kind on (``=+I2``, ``=SPOTDATE``); ``ROUND`` / ``INT`` / ``N`` … their argument's;
* a date plus or minus a number is a date - a date minus a date is a number of days, ``*`` / ``/`` give numbers;
* ``IF`` / ``IFERROR`` / ``CHOOSE``, ``MIN`` / ``MAX`` / ``SMALL`` …, ``INDEX`` / ``VLOOKUP`` / ``LOOKUP`` / ``FILTER``
  a date when every value they may give is one (or a blank, a text, an error: ``IF(A1="","",A1+7)``) - a mix of dates
  and numbers is left as it is;
* a constant is what its format says (a number in a number cell is a number, whatever its size); any other Bloomberg
  field, an ``OFFSET``, a cycle, an array of several columns (a date, an amount, an amount) are not known.

Such a cell is shown as ``dd.mm.yyyy`` - its bold / colour / fill / alignment kept, its value untouched
(:func:`show_dates`).  Day counts (``O35 = O34-O33``), year fractions and every other number stay numbers.  Reading the
whole workbook takes seconds (every formula parsed), too long for every start: :data:`SHOWN` lists the cells the rule
finds - ``tests/test_datecells.py`` checks that it still finds exactly these (a workbook imported again: the test says
what moved; ``python -m tto.datecells`` prints the new list) - and as the model loads each listed cell is shown as a
date once the rule, asked for that cell alone, says it is one (:func:`apply`).  An input the page definition declares a
date is shown as one too (:func:`show_inputs`: the empty rows at the end of a holiday list).

The same reading says how a date typed as a tenor ("3m", "18M": tto/shortcuts.py) counts in a cell the page definition
says nothing about (:meth:`DateCells.context`): its **pair** is that of the first date along what its formula is made of
(:meth:`DateCells.leads`) that has one - the spot dates (``Forward!I2`` USDTRY, ``K2`` EURTRY, ``OIS_MAIN!B2`` the TRY
money market) and the inputs the page definition gives a pair (the Forward page's value date ``D2``: USDTRY); its
**start** is the date the workbook counts its days from (``O35 = O34-O33``: the End counts from the Start), else the
pair's spot date.
"""
from __future__ import annotations

import bisect
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .xl import numfmt
from .xl.model import COLS, Model, a1, parse_range
from .xl.tokenizer import index_to_col
from .xl.parser import parse_template

#: the format a date is shown in (as the workbook's own dates)
DATE = "dd.mm.yyyy"

#: kinds of a value: a date, a number, nothing that decides (a blank, a text, a logical, an error), not known / mixed
D, N, X, U = "d", "n", "x", "?"

Key = Tuple[int, int]                      # (sheet index, rc)

#: functions whose result is a day
_DATE_FUNCS = frozenset(("TODAY", "DATE", "EDATE", "EOMONTH", "WORKDAY", "WORKDAY.INTL", "DATEVALUE"))
#: functions whose result is of the kind of their first argument
_FIRST = frozenset(("ROUND", "ROUNDUP", "ROUNDDOWN", "INT", "TRUNC", "N", "ABS", "VALUE", "SINGLE", "FLOOR", "CEILING",
                    "MROUND", "TRANSPOSE", "SMALL", "LARGE", "MINIFS", "MAXIFS", "SORT", "UNIQUE"))
#: functions whose result is one of their arguments' values (a date when all of them are)
_SAME = frozenset(("MIN", "MAX", "MEDIAN", "AVERAGE"))
#: AGGREGATE's functions that give one of the values (AVERAGE, MAX, MIN, MEDIAN, LARGE, SMALL)
_AGG_SAME = frozenset((1.0, 4.0, 5.0, 12.0, 14.0, 15.0))
#: functions whose result is not known from the formula: Bloomberg's, a reference made at run time, a date-time
_UNKNOWN = frozenset(("OFFSET", "INDIRECT", "NOW", "BDP", "BDH", "BDS", "BFXFORWARD", "RTGET", "BINTERPOL"))
#: functions of a day count: (end argument, start argument)
_DAY_COUNTS = {"DAYS": (0, 1), "YEARFRAC": (1, 0), "NETWORKDAYS": (1, 0), "DATEDIF": (1, 0)}
#: a subtraction in a template whose operands may be cells (a reference token or a bracket on either side of the "-")
_MINUS = re.compile(r"[`)]\s*-\s*[`(A-Za-z_]")


def is_date_field(field: str) -> bool:
    """A Bloomberg field that is a date (``SETTLE_DT``, ``MATURITY``, ``LAST_TRADE_DATE`` …: the names Bloomberg gives
    its dates, as tto/marketdata reads them)."""
    f = field.upper()
    return f == "MATURITY" or "_DT" in f or "DATE" in f


def combine(kinds: Iterable[str]) -> str:
    """The kind of one of several values: a date when every value that decides is a date."""
    seen = set(kinds)
    seen.discard(X)
    if not seen:
        return X
    if len(seen) == 1:
        return seen.pop()
    return U


def _plus(a: str, b: str) -> str:
    if U in (a, b):
        return U
    if D in (a, b):
        return U if a == b else D            # a date and a number (or a blank); two dates: not a date
    return N


def _minus(a: str, b: str) -> str:
    if U in (a, b):
        return U
    if a == D:
        return N if b == D else D            # date - date: days; date - number: a date
    return N


class DateCells(object):
    """The kinds of a model's cells (:meth:`kind`), worked out as they are asked and kept."""

    def __init__(self, model: Model):
        self.model = model
        self.kinds: Dict[Key, str] = {}
        self._asts: Dict[int, Any] = {}
        self._names: Dict[str, Any] = {}
        self._rows: Dict[int, Dict[int, List[int]]] = {}      # sheet -> column -> sorted rows of its filled cells
        self._starts: Dict[int, Dict[int, List[Key]]] = {}      # sheet -> a date (rc) -> the dates its days count from

    # ------------------------------------------------------------------ cells
    def fmt(self, si: int, rc: int) -> str:
        m = self.model
        xf = m.sheets[si].styles.get(rc, 0)
        return m.xfs[xf][0] if xf < len(m.xfs) else "General"

    def ast(self, tid: int):
        tree = self._asts.get(tid)
        if tree is None:
            try:
                tree = parse_template(self.model.templates[tid])
            except Exception:  # noqa: BLE001 - a formula that cannot be read is not known
                tree = ("func", "INDIRECT", [], False)
            self._asts[tid] = tree
        return tree

    def _name(self, name: str):
        if name not in self._names:
            tpl = self.model.names.get(name)
            try:
                self._names[name] = parse_template(tpl) if tpl else None
            except Exception:  # noqa: BLE001
                self._names[name] = None
        return self._names[name]

    def _sheet_of(self, sheet: Optional[str], si: int) -> Optional[int]:
        if sheet is None:
            return si
        return self.model.sheet_index.get(sheet.strip("'"))

    def _filled(self, si: int) -> Dict[int, List[int]]:
        cols = self._rows.get(si)
        if cols is None:
            sh = self.model.sheets[si]
            cols = {}
            for rc in set(sh.consts) | set(sh.fml) | set(sh.members):
                r, c = divmod(rc, COLS)
                cols.setdefault(c, []).append(r)
            for rows in cols.values():
                rows.sort()
            self._rows[si] = cols
        return cols

    def _box(self, nd, si: int, r: int, c: int) -> Optional[Tuple[int, int, int, int, int]]:
        """(sheet, r1, c1, r2, c2) of a reference node of a formula of (r, c); ``None``: not a reference of this book."""
        k = nd[0]
        s = self._sheet_of(nd[1], si) if k in ("cell", "range", "cols", "rows") else None
        if s is None:
            return None
        if k == "cell":
            rr, cc = (nd[3] if nd[2] else r + nd[3]), (nd[5] if nd[4] else c + nd[5])
            return s, rr, cc, rr, cc
        if k == "range":
            r1, c1 = (nd[3] if nd[2] else r + nd[3]), (nd[5] if nd[4] else c + nd[5])
            r2, c2 = (nd[7] if nd[6] else r + nd[7]), (nd[9] if nd[8] else c + nd[9])
            return s, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)
        if k == "cols":
            c1, c2 = (nd[3] if nd[2] else c + nd[3]), (nd[5] if nd[4] else c + nd[5])
            return s, 1, min(c1, c2), 1048576, max(c1, c2)
        r1, r2 = (nd[3] if nd[2] else r + nd[3]), (nd[5] if nd[4] else r + nd[5])
        return s, min(r1, r2), 1, max(r1, r2), 16384

    def _cells(self, box) -> List[Key]:
        """The filled cells of a box (a blank cell decides nothing)."""
        s, r1, c1, r2, c2 = box
        if r1 == r2 and c1 == c2:
            return [(s, r1 * COLS + c1)]
        out = []
        for c, rows in self._filled(s).items():
            if c1 <= c <= c2:
                for r in rows[bisect.bisect_left(rows, r1):bisect.bisect_right(rows, r2)]:
                    out.append((s, r * COLS + c))
        return out

    # ------------------------------------------------------------------ kinds
    def kind(self, si: int, rc: int) -> str:
        """The kind of a cell: :data:`D` (a date), :data:`N` (a number), :data:`X` (nothing that decides), :data:`U`."""
        key = (si, rc)
        got = self.kinds.get(key)
        if got is not None:
            return got
        # depth first without recursion (a chain of thousands of cells): a cell is worked out once what it reads is
        busy = {key}
        stack: List[Tuple[Key, Optional[List[Key]]]] = [(key, None)]
        while stack:
            k, deps = stack[-1]
            if k in self.kinds:
                stack.pop()
                busy.discard(k)
                continue
            if deps is None:
                deps = self._deps(k)
                stack[-1] = (k, deps)
                more = [d for d in deps if d not in self.kinds and d not in busy]
                if more:
                    for d in more:
                        busy.add(d)
                        stack.append((d, None))
                    continue
            self.kinds[k] = self._own(k)         # (a cell still being worked out - a cycle - reads as not known)
            stack.pop()
            busy.discard(k)
        return self.kinds[key]

    def _get(self, key: Key) -> str:
        return self.kinds.get(key, U)

    def _deps(self, key: Key) -> List[Key]:
        si, rc = key
        if numfmt.is_date_format(self.fmt(si, rc)):
            return []
        sh = self.model.sheets[si]
        tid = sh.fml.get(rc)
        if tid is None:
            anchor = self._anchor(si, rc)
            if anchor is None:
                return []
            tid, rc = sh.fml[anchor], anchor
        out: List[Key] = []
        r, c = divmod(rc, COLS)
        self._walk(self.ast(tid), si, r, c, out, set())
        return out

    def _anchor(self, si: int, rc: int) -> Optional[int]:
        """The formula of an array a cell is one of - only an array of one column: a member of a wider one may be any
        of its columns (Bloomberg's cash flows: a date, an amount, an amount)."""
        sh = self.model.sheets[si]
        anchor = sh.members.get(rc)
        if anchor is None or anchor == rc or anchor not in sh.fml:
            return None
        box = sh.arr.get(anchor)
        return anchor if box is None or box[1] == box[3] else None

    def _walk(self, nd, si: int, r: int, c: int, out: List[Key], local: set) -> None:
        """The cells whose kinds the value of ``nd`` depends on (only those: an IF's condition does not matter)."""
        k = nd[0]
        if k in ("cell", "range", "cols", "rows"):
            box = self._box(nd, si, r, c)
            if box is not None:
                out.extend(self._cells(box))
        elif k == "name":
            if nd[1] in local:
                return
            tree = self._name(nd[1])
            if tree is not None:
                self._walk(tree, si, r, c, out, local)
        elif k in ("paren", "pos", "single"):
            self._walk(nd[1], si, r, c, out, local)
        elif k == "bin" and nd[1] in ("+", "-", ":"):
            self._walk(nd[2], si, r, c, out, local)
            self._walk(nd[3], si, r, c, out, local)
        elif k == "func":
            for a in self._value_args(nd, local):
                self._walk(a, si, r, c, out, local)

    @staticmethod
    def _value_args(nd, local: set) -> Sequence[Any]:
        """The arguments of a function whose kinds its value's kind depends on."""
        name, args = nd[1], nd[2]
        if name == "IF":
            return args[1:3]
        if name in ("IFERROR", "IFNA"):
            return args[:2]
        if name == "CHOOSE":
            return args[1:]
        if name == "IFS":
            return args[1::2]
        if name == "SWITCH":
            return args[2::2] + ([args[-1]] if len(args) % 2 == 0 else [])
        if name in _SAME:
            return args
        if name in _FIRST or name == "INDEX":
            return args[:1]
        if name == "FILTER":
            return args[:1] + args[2:3]
        if name in ("VLOOKUP", "HLOOKUP"):
            return args[1:2]
        if name == "LOOKUP":
            return args[2:3] or args[1:2]
        if name == "XLOOKUP":
            return [args[i] for i in (2, 3) if i < len(args)]
        if name == "AGGREGATE":
            return args[2:3]
        if name == "LET":
            local.update(a[1] for a in args[:-1:2] if a[0] == "name")
            return args[1::2] + args[-1:]
        return ()

    def _own(self, key: Key) -> str:
        """A cell's kind once the kinds of what it reads are known."""
        si, rc = key
        if numfmt.is_date_format(self.fmt(si, rc)):
            return D
        sh = self.model.sheets[si]
        tid = sh.fml.get(rc)
        if tid is None:
            if rc in sh.members:
                anchor = self._anchor(si, rc)
                if anchor is None:
                    return U
                tid, rc = sh.fml[anchor], anchor          # (the array's formula, as its anchor holds it)
            else:
                v = sh.consts.get(rc)
                return N if type(v) is float else X
        r, c = divmod(rc, COLS)
        return self._eval(self.ast(tid), si, r, c, {})

    def _eval(self, nd, si: int, r: int, c: int, env: Dict[str, str]) -> str:
        k = nd[0]
        if k == "num":
            return N
        if k in ("str", "bool", "err", "missing"):
            return X
        if k in ("cell", "range", "cols", "rows"):
            box = self._box(nd, si, r, c)
            return U if box is None else combine(self._get(x) for x in self._cells(box))
        if k == "name":
            if nd[1] in env:
                return env[nd[1]]
            tree = self._name(nd[1])
            return U if tree is None else self._eval(tree, si, r, c, env)
        if k in ("paren", "pos", "single"):
            return self._eval(nd[1], si, r, c, env)
        if k in ("neg", "pct"):
            return N
        if k == "array":
            return combine(N if x[0] == "num" else X for row in nd[1] for x in row)
        if k == "bin":
            op = nd[1]
            if op in ("+", "-"):
                a, b = self._eval(nd[2], si, r, c, env), self._eval(nd[3], si, r, c, env)
                return _plus(a, b) if op == "+" else _minus(a, b)
            if op == ":":
                return U
            return N if op in ("*", "/", "^") else X
        if k != "func":
            return U
        name, args = nd[1], nd[2]
        ev = (lambda a: self._eval(a, si, r, c, env))
        if name in _DATE_FUNCS:
            return D
        if name == "BDP" and len(args) > 1 and args[1][0] == "str" and is_date_field(args[1][1]):
            return D                                 # (a text "04.11.2026" live: a date cell shows it as it is)
        if name in _UNKNOWN or nd[3]:
            return U
        if name == "IF":
            return combine([ev(a) for a in args[1:3]] + ([X] if len(args) < 3 else []))
        if name in ("IFERROR", "IFNA", "CHOOSE", "IFS", "SWITCH", "XLOOKUP", "LOOKUP"):
            return combine(ev(a) for a in self._value_args(nd, set()))
        if name in _SAME:
            return combine(ev(a) for a in args)
        if name in _FIRST:
            return ev(args[0]) if args else U
        if name == "AGGREGATE":
            f = args[0][1] if args and args[0][0] == "num" else None
            return ev(args[2]) if f in _AGG_SAME and len(args) > 2 else (U if f is None else N)
        if name in ("INDEX", "VLOOKUP", "HLOOKUP", "FILTER"):
            return self._lookup(nd, si, r, c, env)
        if name == "LET":
            inner = dict(env)
            for i in range(0, len(args) - 1, 2):
                if args[i][0] == "name":
                    inner[args[i][1]] = self._eval(args[i + 1], si, r, c, inner)
            return self._eval(args[-1], si, r, c, inner) if args else U
        if name in ("NA",):
            return X
        return _RESULT.get(name, N)

    def _lookup(self, nd, si: int, r: int, c: int, env: Dict[str, str]) -> str:
        """INDEX / VLOOKUP / HLOOKUP / FILTER: the kinds of what they may give - the column (row) a literal names."""
        name, args = nd[1], nd[2]
        src = args[1] if name in ("VLOOKUP", "HLOOKUP") else (args[0] if args else ("missing",))
        while src[0] == "paren":
            src = src[1]
        box = self._box(src, si, r, c) if src[0] in ("cell", "range") else None
        if box is None:
            alt = [self._eval(args[2], si, r, c, env)] if name == "FILTER" and len(args) > 2 else []
            return combine([self._eval(src, si, r, c, env)] + alt)
        s, r1, c1, r2, c2 = box

        def lit(i: int) -> Optional[int]:
            a = args[i] if i < len(args) else ("missing",)
            return int(a[1]) if a[0] == "num" and a[1] >= 1 else None

        if name == "VLOOKUP" and lit(2):
            c1 = c2 = c1 + lit(2) - 1
        elif name == "HLOOKUP" and lit(2):
            r1 = r2 = r1 + lit(2) - 1
        elif name == "INDEX":
            if r1 == r2 and lit(1) and c1 != c2 and len(args) == 2:
                c1 = c2 = c1 + lit(1) - 1               # INDEX(row, k): the k-th cell of the row
            else:
                if lit(2):
                    c1 = c2 = c1 + lit(2) - 1
                if lit(1) and (len(args) > 2 or c1 == c2):
                    r1 = r2 = r1 + lit(1) - 1
        kinds = [self._get(x) for x in self._cells((s, r1, c1, r2, c2))]
        if name == "FILTER" and len(args) > 2:
            kinds.append(self._eval(args[2], si, r, c, env))
        return combine(kinds)

    # ------------------------------------------------------------------ where a date counts from
    def leads(self, si: int, rc: int) -> List[Key]:
        """The dates a date formula is made from: ``=+I2`` → I2, ``=WORKDAY(EDATE(C60,3)-1,1,…)`` → C60,
        ``=IF(A5="","",B5+7)`` → B5, ``=DATE(YEAR(K2),MONTH(K2),DAY(K2))`` → K2, ``=IF(A68="EURTRY",K2,I2)`` → K2 and I2;
        none for a constant, ``TODAY()``, a Bloomberg field."""
        tid = self.model.sheets[si].fml.get(rc)
        out: List[Key] = []
        if tid is not None:
            r, c = divmod(rc, COLS)
            self._leads(self.ast(tid), si, r, c, out, 0)
        return out

    def _ref(self, nd, si: int, r: int, c: int) -> Optional[Key]:
        """The cell a node names, unwrapped (``(A1)``, ``+A1``, ``N(A1)``) - ``None`` when it names no single cell."""
        while nd[0] in ("paren", "pos") or (nd[0] == "func" and nd[1] == "N" and len(nd[2]) == 1):
            nd = nd[1] if nd[0] != "func" else nd[2][0]
        if nd[0] == "name":
            tree = self._name(nd[1])
            return None if tree is None else self._ref(tree, si, r, c)
        if nd[0] != "cell":
            return None
        box = self._box(nd, si, r, c)
        return None if box is None else (box[0], box[1] * COLS + box[2])

    def _leads(self, nd, si: int, r: int, c: int, out: List[Key], depth: int) -> None:
        if depth > 40:
            return
        k = nd[0]
        if k in ("cell", "name"):
            key = self._ref(nd, si, r, c)
            if key is not None:
                if self.kind(*key) == D and key not in out:
                    out.append(key)
                return
            tree = self._name(nd[1]) if k == "name" else None
            if tree is not None:
                self._leads(tree, si, r, c, out, depth + 1)
            return
        if k in ("paren", "pos", "single"):
            self._leads(nd[1], si, r, c, out, depth + 1)
        elif k == "bin" and nd[1] in ("+", "-"):
            self._leads(nd[2], si, r, c, out, depth + 1)
            if nd[1] == "+":                             # (a date minus a number: the date)
                self._leads(nd[3], si, r, c, out, depth + 1)
        elif k == "func":
            name, args = nd[1], nd[2]
            if name in ("EDATE", "EOMONTH", "WORKDAY", "WORKDAY.INTL"):
                args = args[:1]                          # (the start date; the holidays are no start)
            elif name not in ("DATE", "YEAR", "MONTH", "DAY"):
                args = self._value_args(nd, set())       # (DATE(YEAR(K2),MONTH(K2),DAY(K2)): every argument)
            for a in args:
                self._leads(a, si, r, c, out, depth + 1)

    def pair(self, si: int, rc: int, known: Callable[[Key], Optional[str]]) -> Optional[str]:
        """The pair a date belongs to: that of the dates along what it is made of (:meth:`leads`, from the cell itself
        on) that ``known`` names one for - a spot date (Forward!I2 USDTRY, K2 EURTRY, OIS_MAIN!B2 the TRY money market),
        an input the page definition gives a pair; ``None`` when there is none (a constant, TODAY()) or more than one
        (a row's spot date that is USDTRY's or EURTRY's as the row says)."""
        found = set()
        seen = set()
        stack = [(si, rc)]
        while stack:
            key = stack.pop()
            if key in seen:
                continue
            seen.add(key)
            got = known(key)
            if got:
                found.add(got)
            else:
                stack.extend(self.leads(*key))
        return found.pop() if len(found) == 1 else None

    def start(self, si: int, rc: int, spots: Iterable[Key] = ()) -> Optional[Key]:
        """The date the workbook counts a date's days from - its start: ``O35 = O34-O33`` makes O33 the start of O34
        (also ``DAYS``, ``YEARFRAC``, ``NETWORKDAYS``, ``DATEDIF``), on the date's own sheet.  A spot date (``spots``) is
        no start - from the spot is where a date counts anyway (MASA!E60 counts its days from C60 and, to discount, from
        the OIS spot date).  ``None`` when there is none, or more than one."""
        spots = set(spots)
        found = [k for k in self._day_counts(si).get(rc, ()) if k not in spots]
        return found[0] if len(found) == 1 else None

    def context(self, si: int, rc: int, known: Callable[[Key], Optional[str]],
                spots: Iterable[Key] = ()) -> Tuple[Optional[str], Optional[Key]]:
        """How a date typed as a tenor counts in a cell, as the formulas say: (its pair - :meth:`pair`, else its start's -,
        its :meth:`start`)."""
        start = self.start(si, rc, spots)
        pair = self.pair(si, rc, known) or (self.pair(start[0], start[1], known) if start is not None else None)
        return pair, start

    def _day_counts(self, si: int) -> Dict[int, List[Key]]:
        """The sheet's day counts: end (rc) -> its starts.  Worked out on first use, once per sheet."""
        got = self._starts.get(si)
        if got is not None:
            return got
        got = {}
        sh = self.model.sheets[si]
        for rc, tid in sh.fml.items():
            text = self.model.templates[tid]
            if not _MINUS.search(text) and not any(f in text for f in _DAY_COUNTS):
                continue                                 # (no subtraction of a reference or a bracket: no day count)
            r, c = divmod(rc, COLS)
            stack = [self.ast(tid)]
            while stack:
                nd = stack.pop()
                k = nd[0]
                pair = None
                if k == "bin":
                    if nd[1] == "-":
                        pair = (nd[2], nd[3])
                    stack.extend((nd[2], nd[3]))
                elif k == "func":
                    if nd[1] in _DAY_COUNTS and len(nd[2]) >= 2:
                        e, s = _DAY_COUNTS[nd[1]]
                        pair = (nd[2][e], nd[2][s])
                    stack.extend(nd[2])
                elif k in ("paren", "pos", "neg", "pct", "single"):
                    stack.append(nd[1])
                if pair is None:
                    continue
                end, start = self._ref(pair[0], si, r, c), self._ref(pair[1], si, r, c)
                if end is None or start is None or end == start or end[0] != si:
                    continue
                if self.kind(*end) == D and self.kind(*start) == D:
                    lst = got.setdefault(end[1], [])
                    if start not in lst:
                        lst.append(start)
        self._starts[si] = got
        return got

    # ------------------------------------------------------------------ the whole model
    def dates(self) -> List[Key]:
        """Every formula cell (and cell of an array formula) that holds a date, in sheet and address order."""
        out = []
        for sh in self.model.sheets:
            for rc in sorted(set(sh.fml) | set(sh.members)):
                if self.kind(sh.index, rc) == D:
                    out.append((sh.index, rc))
        return out

    def hidden_dates(self) -> List[Key]:
        """The cells that hold a date but are not formatted as one (what :func:`show_dates` shows as dates)."""
        return [k for k in self.dates() if not numfmt.is_date_format(self.fmt(*k))]


#: the kinds of the other functions' results (anything not here gives a number)
_RESULT: Dict[str, str] = {n: X for n in (
    "TEXT", "TRIM", "SUBSTITUTE", "MID", "LEFT", "RIGHT", "UPPER", "LOWER", "CONCAT", "CONCATENATE", "TEXTJOIN",
    "FIXED", "REPT", "AND", "OR", "NOT", "ISNUMBER", "ISTEXT", "ISBLANK", "ISERROR", "ISERR", "ISNA", "ISLOGICAL",
    "EXACT", "TRUE", "FALSE")}


def show_dates(model: Model, cells: Iterable[Key]) -> int:
    """Show ``cells`` as dates (``dd.mm.yyyy``): each keeps its bold, colours, fill and alignment.  Returns how many."""
    by_xf: Dict[int, int] = {}
    n = 0
    for si, rc in cells:
        sh = model.sheets[si]
        xf = sh.styles.get(rc, 0)
        new = by_xf.get(xf)
        if new is None:
            look = list(model.xfs[xf]) if xf < len(model.xfs) else ["General", 0, None, None, None, 0]
            look[0] = DATE
            new = next((i for i, x in enumerate(model.xfs) if list(x) == look), None)
            if new is None:
                new = len(model.xfs)
                model.xfs.append(look)
                model.numfmts.append(DATE)
                model.xf_flags.append(model.xf_flags[xf] if xf < len(model.xf_flags) else 0)
            by_xf[xf] = new
        sh.styles[rc] = new
        n += 1
    return n


def compact(model: Model, cells: Iterable[Key]) -> List[str]:
    """Cells as the fewest ``Sheet!A1:B2`` boxes that cover them exactly (rows of a column, then columns side by side
    with the same rows), in sheet order."""
    by_sheet: Dict[int, Dict[int, List[int]]] = {}
    for si, rc in cells:
        r, c = divmod(rc, COLS)
        by_sheet.setdefault(si, {}).setdefault(c, []).append(r)
    out = []
    for si in sorted(by_sheet):
        runs: Dict[Tuple[int, int], List[int]] = {}           # (first row, last row) -> its columns
        for c, rows in by_sheet[si].items():
            rows.sort()
            a = b = rows[0]
            for r in rows[1:] + [None]:
                if r is not None and r == b + 1:
                    b = r
                    continue
                runs.setdefault((a, b), []).append(c)
                if r is not None:
                    a = b = r
        boxes = []
        for (a, b), cols in runs.items():
            cols.sort()
            c1 = c2 = cols[0]
            for c in cols[1:] + [None]:
                if c is not None and c == c2 + 1:
                    c2 = c
                    continue
                boxes.append((c1, a, c2, b))
                if c is not None:
                    c1 = c2 = c
        name = model.sheets[si].name
        for c1, a, c2, b in sorted(boxes):
            first, last = "%s%d" % (index_to_col(c1), a), "%s%d" % (index_to_col(c2), b)
            out.append("%s!%s" % (name, first if first == last else first + ":" + last))
    return out


def cells_of(model: Model, boxes: Iterable[str]) -> List[Key]:
    """``["Sheet!A1:B2", …]`` -> the cells (a sheet the model does not have: nothing)."""
    out = []
    for box in boxes:
        sheet, _, addr = box.rpartition("!")
        si = model.sheet_index.get(sheet)
        if si is None:
            continue
        r1, c1, r2, c2 = parse_range(addr)
        out.extend((si, r * COLS + c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))
    return out


def apply(book_id: str, model: Model) -> Tuple[DateCells, List[str]]:
    """Show the cells of :data:`SHOWN` the rule still finds dates as dates.  Returns the model's :class:`DateCells` (kept
    with the book: what it worked out serves the shortcuts) and what was listed but is no date by the rule any more (a
    workbook imported again: ``tests/test_datecells.py`` says what moved)."""
    dc = DateCells(model)
    show, gone = [], []
    for si, rc in cells_of(model, SHOWN.get(book_id, ())):
        if numfmt.is_date_format(dc.fmt(si, rc)):
            continue
        if dc.kind(si, rc) == D:
            show.append((si, rc))
        else:
            gone.append("%s!%s" % (model.sheets[si].name, a1(rc)))
    show_dates(model, show)
    return dc, (["tarih olarak listelenen hücre artık tarih değil: %s" % ", ".join(gone[:12])] if gone else [])


def show_inputs(book) -> List[Key]:
    """The inputs a page definition declares dates (``"kind": "date"``) that are not formatted as dates, shown as dates
    (the empty rows at the end of a holiday list: a day typed there is a date) - but a list of days kept as text (VİOP
    Target's contracts: their drop-down holds texts).  Returns them."""
    model = book.model
    cells = [k for k, d in book.inputs.items() if d.kind == "date" and not numfmt.is_date_format(_fmt(model, *k))
             and not book.has_list(*k)]
    show_dates(model, cells)
    return sorted(cells)


def _fmt(model: Model, si: int, rc: int) -> str:
    xf = model.sheets[si].styles.get(rc, 0)
    return model.xfs[xf][0] if xf < len(model.xfs) else "General"


#: The cells shown as dates (:func:`apply`): every formula cell the rule finds a date that is not formatted as one -
#: generated (``python -m tto.datecells``) and checked against the rule by ``tests/test_datecells.py``
SHOWN: Dict[str, Tuple[str, ...]] = {
    'tto': (
        'OIS_MAIN!W2', 'VIOP!L5:W5', 'VIOP!L112:L122', 'VIOP!L126:L136', 'VIOP!L140:L150', 'VIOP!L154:L164',
        'VIOP!L168:L178', 'VIOP!L182:L192', 'VIOP!L196:L206', 'VIOP!L210:L220', 'VIOP!L224:L234', 'VIOP!L238:L248',
        'VIOP!L252:L262', 'VIOP!L266:L276', 'VIOP!L280:L290', 'VIOP!L294:L304', 'VIOP!L308:L318', 'VIOP!M7:X7',
        'VIOP!M19:X19', 'VIOP!M46:O46', 'VIOP!M61:O61', 'VIOP!M71:X71', 'VIOP!M84:X84', 'VIOP!M97:X97',
        'VIOP!M110:X110', 'VIOP!M124:X124', 'VIOP!M138:X138', 'VIOP!M152:X152', 'VIOP!M166:X166', 'VIOP!M180:X180',
        'VIOP!M194:X194', 'VIOP!M208:X208', 'VIOP!M222:X222', 'VIOP!M236:X236', 'VIOP!M250:X250', 'VIOP!M264:X264',
        'VIOP!M278:X278', 'VIOP!M292:X292', 'VIOP!M306:X306', 'VIOP!M322:N324', 'VIOP!M326:N328', 'VIOP!M341:X341',
        'VIOP!M367:X367', 'VIOP!S46:U46', 'VIOP!Z112:Z123', 'Forward!F8:F21', 'Forward!O33', 'Forward!V75',
        'DİBS RV!BX5:BX54', 'DİBS RV!CB5:CB54', 'DİBS RV!CG5:CG54', 'DİBS RV!CT5:CT54', 'DİBS RV!CZ5:DA54',
        'DİBS RV!DC5:DC54', 'DİBS RV!DE5:DE54', 'EK_DIBS!AH5:AH54', 'EK_DIBS!AN5:AN54', 'EK_DIBS!AT5:AT54',
        'EK_EVREN!Y6:Y165', 'EK_IHALE!T7', 'EK_IHALE!T27', 'EK_IHALE!T47', 'EK_IHALE!X7', 'EK_IHALE!X27',
        'EK_IHALE!X47', 'EK_IHALE!AB7:AC7', 'EK_IHALE!AB27:AC27', 'EK_IHALE!AB47:AC47',
    ),
    'asw': (
        'ASW!AT7:AT56',
    ),
}


def model_of(book_id: str, models_dir: Optional[str] = None) -> Optional[Model]:
    """A workbook's model as the dashboard loads it (its sheets the desk does not use taken out, its own additions in) -
    before anything is shown as a date.  ``None`` when the model file is not there."""
    import os
    from .books import BOOKS, remove_sheets
    from . import extras
    folder = models_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
    fname = next((f for b, _, f, _ in BOOKS if b == book_id), None)
    if fname is None or not os.path.exists(os.path.join(folder, fname)):
        return None
    model = Model.load(os.path.join(folder, fname))
    remove_sheets(book_id, model)
    extras.apply(book_id, model)
    return model


def found(model: Model) -> List[str]:
    """What the rule finds in a model: its cells that hold a date but are not formatted as one, as boxes."""
    return compact(model, DateCells(model).hidden_dates())


def main() -> None:
    """Print :data:`SHOWN` as the rule finds it in the model files (after the dashboard's own additions)."""
    from .books import BOOKS
    print("SHOWN: Dict[str, Tuple[str, ...]] = {")
    for book_id, _, _, _ in BOOKS:
        model = model_of(book_id)
        boxes = found(model) if model is not None else []
        if not boxes:
            continue
        print("    %r: (" % book_id)
        line = ""
        for box in boxes:
            item = "%r," % box
            if line and len(line) + 1 + len(item) > 112:
                print("        " + line)
                line = ""
            line = (line + " " + item) if line else item
        print("        " + line)
        print("    ),")
    print("}")


if __name__ == "__main__":
    main()
