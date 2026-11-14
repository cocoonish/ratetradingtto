"""Excel worksheet functions (the subset used by the desk workbooks) with Excel semantics.

Every function receives already evaluated arguments.  Parameter kinds (see :data:`FUNCS`):

* ``v``  value: a scalar; inside array formulas the compiler lifts the function over arrays
* ``r``  reference / array passed through untouched (aggregators, lookups)
* ``a``  like ``r`` but the argument expression is evaluated in array mode (SUMPRODUCT & friends)
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import numfmt
from .errors import E_CALC, E_DIV0, E_NA, E_NAME, E_NUM, E_REF, E_VALUE, XlError
from .values import (XlArray, XlRange, as_rows, compare, date_to_serial, deref, first, fmt_general, intersect,
                     is_multi, num_eq, parse_number_text, serial_to_date, to_bool, to_num, to_text)

_float = float


class _Err(Exception):
    """Internal: carries an XlError out of a nested loop."""

    def __init__(self, err):
        self.err = err


def _sum(xs) -> float:
    """Plain left-to-right double summation (what Excel does; ``sum()`` is compensated since 3.12)."""
    s = 0.0
    for x in xs:
        s += x
    return s


# --------------------------------------------------------------------------- argument helpers
def _nums(args: Sequence[Any]) -> List[float]:
    """Numbers of a SUM-like argument list (text / logicals / blanks inside ranges are ignored)."""
    out: List[float] = []
    add = out.append
    for a in args:
        t = type(a)
        if t is _float:
            add(a)
        elif t is XlRange or t is XlArray:
            for v in a.flat():
                tv = type(v)
                if tv is _float:
                    add(v)
                elif tv is XlError:
                    raise _Err(v)
        elif a is None:
            continue
        elif t is bool:
            add(1.0 if a else 0.0)
        elif t is str:
            n = parse_number_text(a)
            if n is None:
                raise _Err(E_VALUE)
            add(n)
        elif t is XlError:
            raise _Err(a)
        elif t is int:
            add(_float(a))
    return out


def _int(v: Any) -> Any:
    """Truncate a numeric argument toward zero (index / count parameters)."""
    x = to_num(v)
    if type(x) is XlError:
        return x
    return int(x)


def _flat(v: Any) -> List[Any]:
    t = type(v)
    if t is XlRange or t is XlArray:
        return v.flat()
    return [v]


# --------------------------------------------------------------------------- aggregates
def F_SUM(*args):
    try:
        s = 0.0
        for a in args:
            t = type(a)
            if t is _float:
                s += a
            elif t is XlRange or t is XlArray:
                for v in a.flat():
                    tv = type(v)
                    if tv is _float:
                        s += v
                    elif tv is XlError:
                        return v
            else:
                for x in _nums((a,)):
                    s += x
        return s
    except _Err as e:
        return e.err


def F_AVERAGE(*args):
    try:
        xs = _nums(args)
    except _Err as e:
        return e.err
    if not xs:
        return E_DIV0
    return _sum(xs) / len(xs)


def F_MIN(*args):
    try:
        xs = _nums(args)
    except _Err as e:
        return e.err
    return min(xs) if xs else 0.0


def F_MAX(*args):
    try:
        xs = _nums(args)
    except _Err as e:
        return e.err
    return max(xs) if xs else 0.0


def F_COUNT(*args):
    n = 0
    for a in args:
        t = type(a)
        if t is _float:
            n += 1
        elif t is XlRange or t is XlArray:
            for v in a.flat():
                if type(v) is _float:
                    n += 1
        elif t is bool:
            n += 1
        elif t is str:
            if parse_number_text(a) is not None:
                n += 1
    return _float(n)


def F_COUNTA(*args):
    n = 0
    for a in args:
        t = type(a)
        if t is XlRange or t is XlArray:
            for v in a.flat():
                if v is not None:
                    n += 1
        elif a is not None:
            n += 1
    return _float(n)


def F_STDEV(*args):
    try:
        xs = _nums(args)
    except _Err as e:
        return e.err
    n = len(xs)
    if n < 2:
        return E_DIV0
    m = _sum(xs) / n
    ss = 0.0
    for x in xs:
        d = x - m
        ss += d * d
    return math.sqrt(ss / (n - 1))


def F_STDEVP(*args):
    try:
        xs = _nums(args)
    except _Err as e:
        return e.err
    n = len(xs)
    if n < 1:
        return E_DIV0
    m = _sum(xs) / n
    return math.sqrt(_sum([(x - m) * (x - m) for x in xs]) / n)


def F_MEDIAN(*args):
    try:
        xs = sorted(_nums(args))
    except _Err as e:
        return e.err
    n = len(xs)
    if not n:
        return E_NUM
    if n % 2:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def F_SUMPRODUCT(*args):
    if not args:
        return E_VALUE
    mats = [as_rows(a) for a in args]
    nr = len(mats[0])
    nc = len(mats[0][0]) if nr else 0
    for m in mats[1:]:
        if len(m) != nr or (len(m[0]) if m else 0) != nc:
            return E_VALUE
    total = 0.0
    if len(mats) == 1:
        for row in mats[0]:
            for v in row:
                tv = type(v)
                if tv is _float:
                    total += v
                elif tv is XlError:
                    return v
        return total
    for i in range(nr):
        rows = [m[i] for m in mats]
        for j in range(nc):
            p = 1.0
            for row in rows:
                v = row[j]
                tv = type(v)
                if tv is _float:
                    p *= v
                elif tv is XlError:
                    return v
                else:
                    p = 0.0
            total += p
    return total


def _large_small(arr, k, largest: bool):
    try:
        xs = _nums((arr,))
    except _Err as e:
        return e.err
    kk = to_num(k)
    if type(kk) is XlError:
        return kk
    kk = int(math.ceil(kk)) if kk != int(kk) else int(kk)
    if kk < 1 or kk > len(xs):
        return E_NUM
    xs.sort(reverse=largest)
    return xs[kk - 1]


def F_LARGE(arr, k):
    return _large_small(arr, k, True)


def _percentile(xs: List[float], p: float, exclusive: bool):
    """PERCENTILE.INC / PERCENTILE.EXC of sorted numbers."""
    n = len(xs)
    if n == 0 or not (0.0 <= p <= 1.0):
        return E_NUM
    if exclusive:
        pos = p * (n + 1)
        if pos < 1 or pos > n:
            return E_NUM
        pos -= 1
    else:
        pos = p * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def F_AGGREGATE(fnum, options, *args):
    """AGGREGATE(function_num, options, ref1 [, ref2 ...])  /  AGGREGATE(function_num, options, array, k).

    Options 2, 3, 6 and 7 leave error values out (the reason the function is used); hidden rows play no
    role here - nothing is hidden inside the engine.
    """
    f, o = to_num(fnum), to_num(options)
    if type(f) is XlError:
        return f
    if type(o) is XlError:
        return o
    f, o = int(f), int(o)
    if not 1 <= f <= 19 or not 0 <= o <= 7 or not args:
        return E_VALUE
    skip_errors = o in (2, 3, 6, 7)
    k = None
    if f >= 14:
        if len(args) < 2:
            return E_VALUE
        k = to_num(first(args[1]) if type(args[1]) in (XlRange, XlArray) else args[1])
        if type(k) is XlError:
            return k
        args = args[:1]
    xs: List[float] = []
    filled = 0
    for a in args:
        vals = a.flat() if type(a) in (XlRange, XlArray) else [a]
        for v in vals:
            tv = type(v)
            if tv is XlError:
                if skip_errors:
                    continue
                return v
            if v is not None and v != "":
                filled += 1
            if tv is _float:
                xs.append(v)
    n = len(xs)
    if f == 2:
        return float(n)
    if f == 3:
        return float(filled)
    if f == 9:
        return _sum(xs)
    if f == 6:
        p = 1.0
        for x in xs:
            p *= x
        return p if n else 0.0
    if f in (4, 5):
        return (max(xs) if f == 4 else min(xs)) if n else 0.0
    if f == 1:
        return _sum(xs) / n if n else E_DIV0
    if f in (7, 8, 10, 11):
        sample = f in (7, 10)
        if n < (2 if sample else 1):
            return E_DIV0
        m = _sum(xs) / n
        ss = _sum([(x - m) * (x - m) for x in xs]) / (n - 1 if sample else n)
        return math.sqrt(ss) if f in (7, 8) else ss
    if n == 0:
        return E_NUM
    xs.sort()
    if f == 12:
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0
    if f == 13:
        best, count = None, 1
        seen: Dict[float, int] = {}
        for x in xs:
            seen[x] = seen.get(x, 0) + 1
        for x in xs:                                   # the smallest of the most frequent values
            if seen[x] > count:
                best, count = x, seen[x]
        return best if best is not None else E_NA
    if f in (14, 15):
        kk = int(math.ceil(k)) if k != int(k) else int(k)
        if kk < 1 or kk > n:
            return E_NUM
        return xs[n - kk] if f == 14 else xs[kk - 1]
    if f in (16, 18):
        return _percentile(xs, k, f == 18)
    quart = int(k)                                     # 17 / 19: QUARTILE.INC / QUARTILE.EXC
    if f == 17 and 0 <= quart <= 4:
        return _percentile(xs, quart / 4.0, False)
    if f == 19 and 1 <= quart <= 3:
        return _percentile(xs, quart / 4.0, True)
    return E_NUM


def F_FILTER(arr, include, if_empty=None):
    """FILTER(array, include, [if_empty]): the rows (or columns) of ``array`` whose ``include`` entry is true."""
    rows = as_rows(arr)
    if type(include) is XlError:
        return include
    inc = as_rows(include)
    nr = len(rows)
    nc = len(rows[0]) if nr else 0
    by_rows = len(inc) == nr and (len(inc[0]) if inc else 0) == 1
    by_cols = not by_rows and len(inc) == 1 and len(inc[0]) == nc
    if not (by_rows or by_cols):
        return E_VALUE
    flags = []
    for v in ([row[0] for row in inc] if by_rows else inc[0]):
        tv = type(v)
        if tv is XlError:
            return v
        if tv is bool:
            flags.append(v)
        elif tv is _float:
            flags.append(v != 0.0)
        elif v is None:
            flags.append(False)
        else:
            return E_VALUE
    if by_rows:
        kept = [list(rows[i]) for i in range(nr) if flags[i]]
    else:
        cols = [j for j in range(nc) if flags[j]]
        kept = [[row[j] for j in cols] for row in rows] if cols else []
    if not kept:
        return E_CALC if if_empty is None else if_empty
    return XlArray(kept)


def F_SMALL(arr, k):
    return _large_small(arr, k, False)


def F_SLOPE(ys, xs):
    fy, fx = _flat(ys), _flat(xs)
    if len(fy) != len(fx):
        return E_NA
    px: List[float] = []
    py: List[float] = []
    for y, x in zip(fy, fx):
        if type(y) is XlError:
            return y
        if type(x) is XlError:
            return x
        if type(y) is _float and type(x) is _float:
            px.append(x)
            py.append(y)
    n = len(px)
    if n < 2:
        return E_DIV0
    mx = _sum(px) / n
    my = _sum(py) / n
    sxx = 0.0
    sxy = 0.0
    for x, y in zip(px, py):
        sxx += (x - mx) * (x - mx)
        sxy += (x - mx) * (y - my)
    if sxx == 0.0:
        return E_DIV0
    return sxy / sxx


def F_INTERCEPT(ys, xs):
    b = F_SLOPE(ys, xs)
    if type(b) is XlError:
        return b
    pairs = [(x, y) for y, x in zip(_flat(ys), _flat(xs)) if type(y) is _float and type(x) is _float]
    n = len(pairs)
    return _sum([p[1] for p in pairs]) / n - b * _sum([p[0] for p in pairs]) / n


# --------------------------------------------------------------------------- criteria functions
_WILD = re.compile(r"[*?~]")


def _wild_regex(pattern: str):
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "~" and i + 1 < n:
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z", re.I | re.S)


def make_criteria(crit: Any) -> Callable[[Any], bool]:
    """Build the predicate of a COUNTIF / SUMIF style criterion."""
    t = type(crit)
    if t is XlRange or t is XlArray:
        crit = first(crit)
        t = type(crit)
    if crit is None:
        crit, t = 0.0, _float
    if t is XlError:
        return lambda v: v is crit
    if t is bool:
        return lambda v: type(v) is bool and v == crit
    if t is _float or t is int:
        c = _float(crit)

        def eq_num(v):
            tv = type(v)
            if tv is _float:
                return v == c
            if tv is str:
                return parse_number_text(v) == c
            return False
        return eq_num
    s = crit
    op = "="
    for cand in ("<>", "<=", ">=", "<", ">", "="):
        if s.startswith(cand):
            op = cand
            s = s[len(cand):]
            break
    num = parse_number_text(s) if s != "" else None
    up = s.upper()
    if num is None and up in ("TRUE", "FALSE"):
        b = up == "TRUE"
        if op == "=":
            return lambda v: type(v) is bool and v == b
        if op == "<>":
            return lambda v: not (type(v) is bool and v == b)
    if num is not None:
        c = num
        if op == "=":
            def f(v):
                tv = type(v)
                if tv is _float:
                    return v == c
                if tv is str:
                    return parse_number_text(v) == c
                return False
            return f
        if op == "<>":
            def f(v):
                tv = type(v)
                if tv is _float:
                    return v != c
                if tv is str:
                    return parse_number_text(v) != c
                return True
            return f
        if op == "<":
            return lambda v: type(v) is _float and v < c
        if op == ">":
            return lambda v: type(v) is _float and v > c
        if op == "<=":
            return lambda v: type(v) is _float and v <= c
        return lambda v: type(v) is _float and v >= c
    # text criterion
    if s == "":
        if op == "=":
            return lambda v: v is None or v == ""
        if op == "<>":
            return lambda v: v is not None and v != ""
    if op in ("=", "<>"):
        if _WILD.search(s):
            rx = _wild_regex(s)
            if op == "=":
                return lambda v: type(v) is str and rx.match(v) is not None
            return lambda v: not (type(v) is str and rx.match(v) is not None)
        if op == "=":
            return lambda v: type(v) is str and v.upper() == up
        return lambda v: not (type(v) is str and v.upper() == up)
    if op == "<":
        return lambda v: type(v) is str and v.upper() < up
    if op == ">":
        return lambda v: type(v) is str and v.upper() > up
    if op == "<=":
        return lambda v: type(v) is str and v.upper() <= up
    return lambda v: type(v) is str and v.upper() >= up


def _criteria_mask(pairs: Sequence[Any]) -> Any:
    """Indices that satisfy every (range, criterion) pair; returns a list of flat indices or XlError."""
    idx: Optional[List[int]] = None
    size = None
    for k in range(0, len(pairs), 2):
        rng, crit = pairs[k], pairs[k + 1]
        if type(crit) is XlError:
            return crit
        vals = _flat(rng)
        if size is None:
            size = len(vals)
        elif len(vals) != size:
            return E_VALUE
        pred = make_criteria(crit)
        if idx is None:
            idx = [i for i, v in enumerate(vals) if pred(v)]
        else:
            idx = [i for i in idx if pred(vals[i])]
        if not idx:
            return []
    return idx if idx is not None else []


def F_COUNTIF(rng, crit):
    if type(crit) is XlError:
        return crit
    pred = make_criteria(crit)
    n = 0
    for v in _flat(rng):
        if pred(v):
            n += 1
    return _float(n)


def F_COUNTIFS(*pairs):
    idx = _criteria_mask(pairs)
    if type(idx) is XlError:
        return idx
    return _float(len(idx))


def F_SUMIF(rng, crit, sum_rng=None):
    if type(crit) is XlError:
        return crit
    pred = make_criteria(crit)
    vals = _flat(rng)
    if sum_rng is None:
        svals = vals
    else:
        if type(sum_rng) is XlRange and (sum_rng.nr != dims_of(rng)[0] or sum_rng.nc != dims_of(rng)[1]):
            nr, nc = dims_of(rng)
            sum_rng = XlRange(sum_rng.ctx, sum_rng.si, sum_rng.r1, sum_rng.c1, sum_rng.r1 + nr - 1, sum_rng.c1 + nc - 1)
        svals = _flat(sum_rng)
    s = 0.0
    for i, v in enumerate(vals):
        if pred(v) and i < len(svals):
            x = svals[i]
            if type(x) is _float:
                s += x
            elif type(x) is XlError:
                return x
    return s


def dims_of(v):
    t = type(v)
    if t is XlRange or t is XlArray:
        return v.nr, v.nc
    return 1, 1


def F_SUMIFS(sum_rng, *pairs):
    idx = _criteria_mask(pairs)
    if type(idx) is XlError:
        return idx
    vals = _flat(sum_rng)
    s = 0.0
    for i in idx:
        x = vals[i]
        if type(x) is _float:
            s += x
        elif type(x) is XlError:
            return x
    return s


def F_AVERAGEIFS(avg_rng, *pairs):
    idx = _criteria_mask(pairs)
    if type(idx) is XlError:
        return idx
    vals = _flat(avg_rng)
    xs = []
    for i in idx:
        x = vals[i]
        if type(x) is _float:
            xs.append(x)
        elif type(x) is XlError:
            return x
    if not xs:
        return E_DIV0
    return _sum(xs) / len(xs)


def _minmaxifs(rng, pairs, fn):
    idx = _criteria_mask(pairs)
    if type(idx) is XlError:
        return idx
    vals = _flat(rng)
    xs = []
    for i in idx:
        x = vals[i]
        if type(x) is _float:
            xs.append(x)
        elif type(x) is XlError:
            return x
    return fn(xs) if xs else 0.0


def F_MINIFS(rng, *pairs):
    return _minmaxifs(rng, pairs, min)


def F_MAXIFS(rng, *pairs):
    return _minmaxifs(rng, pairs, max)


# --------------------------------------------------------------------------- logical / information
def F_AND(*args):
    res = True
    seen = False
    for a in args:
        t = type(a)
        if t is XlRange or t is XlArray:
            for v in a.flat():
                tv = type(v)
                if tv is bool:
                    seen = True
                    res = res and v
                elif tv is _float:
                    seen = True
                    res = res and v != 0.0
                elif tv is XlError:
                    return v
        else:
            if a is None:
                continue
            b = to_bool(a)
            if type(b) is XlError:
                return b
            seen = True
            res = res and b
    return res if seen else E_VALUE


def F_OR(*args):
    res = False
    seen = False
    for a in args:
        t = type(a)
        if t is XlRange or t is XlArray:
            for v in a.flat():
                tv = type(v)
                if tv is bool:
                    seen = True
                    res = res or v
                elif tv is _float:
                    seen = True
                    res = res or v != 0.0
                elif tv is XlError:
                    return v
        else:
            if a is None:
                continue
            b = to_bool(a)
            if type(b) is XlError:
                return b
            seen = True
            res = res or b
    return res if seen else E_VALUE


def F_NOT(v):
    b = to_bool(v)
    if type(b) is XlError:
        return b
    return not b


def F_ISNUMBER(v):
    return type(v) is _float


def F_ISTEXT(v):
    return type(v) is str


def F_ISBLANK(v):
    return v is None


def F_ISERROR(v):
    return type(v) is XlError


def F_ISNA(v):
    return v is E_NA


def F_ISERR(v):
    return type(v) is XlError and v is not E_NA


def F_ISLOGICAL(v):
    return type(v) is bool


def F_N(v):
    t = type(v)
    if t is _float:
        return v
    if t is bool:
        return 1.0 if v else 0.0
    if t is XlError:
        return v
    return 0.0


def IF3(cond, a, b):
    """Scalar IF with lazily evaluated branches."""
    t = type(cond)
    if t is bool:
        return a() if cond else b()
    c = to_bool(cond)
    if type(c) is XlError:
        return c
    return a() if c else b()


def IFA(cond, a, b):
    """IF inside an array formula: element-wise when the condition is an array."""
    t = type(cond)
    if t is not XlArray and t is not XlRange:
        return IF3(cond, a, b)
    crow = as_rows(cond)
    need_a = need_b = False
    flags = []
    for row in crow:
        fr = []
        for v in row:
            c = to_bool(v)
            fr.append(c)
            if type(c) is XlError:
                continue
            if c:
                need_a = True
            else:
                need_b = True
        flags.append(fr)
    va = as_rows(deref(a())) if need_a else None
    vb = as_rows(deref(b())) if need_b else None
    nr = len(flags)
    nc = len(flags[0]) if nr else 0
    for m in (va, vb):
        if m is not None:
            nr = max(nr, len(m))
            nc = max(nc, len(m[0]) if m else 0)

    def pick(m, i, j):
        n1, n2 = len(m), len(m[0])
        ii = 0 if n1 == 1 else i
        jj = 0 if n2 == 1 else j
        if ii >= n1 or jj >= n2:
            return E_NA
        return m[ii][jj]

    out = []
    for i in range(nr):
        row = []
        for j in range(nc):
            c = pick(flags, i, j)
            if type(c) is XlError:
                row.append(c)
            elif c:
                row.append(pick(va, i, j))
            else:
                row.append(pick(vb, i, j))
        out.append(row)
    return XlArray(out)


def IFE(value, alt):
    if type(value) is XlError:
        return alt()
    return value


def IFEA(value, alt):
    t = type(value)
    if t is XlArray or t is XlRange:
        rows = as_rows(value)
        if not any(type(v) is XlError for row in rows for v in row):
            return value
        altv = as_rows(deref(alt()))
        n1, n2 = len(altv), len(altv[0]) if altv else 0

        def pick(i, j):
            ii = 0 if n1 == 1 else i
            jj = 0 if n2 == 1 else j
            if ii >= n1 or jj >= n2:
                return E_NA
            return altv[ii][jj]
        return XlArray([[pick(i, j) if type(v) is XlError else v for j, v in enumerate(row)]
                        for i, row in enumerate(rows)])
    if t is XlError:
        return alt()
    return value


def IFNA(value, alt):
    if value is E_NA:
        return alt()
    return value


def CHOOSE(index, thunks):
    i = _int(index)
    if type(i) is XlError:
        return i
    if i < 1 or i > len(thunks):
        return E_VALUE
    return thunks[i - 1]()


# --------------------------------------------------------------------------- math
def F_ABS(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    return abs(x)


def F_EXP(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    try:
        return math.exp(x)
    except OverflowError:
        return E_NUM


def F_LN(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    if x <= 0.0:
        return E_NUM
    return math.log(x)


def F_LOG10(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    if x <= 0.0:
        return E_NUM
    return math.log10(x)


def F_LOG(x, base=10.0):
    x = to_num(x)
    if type(x) is XlError:
        return x
    b = to_num(base)
    if type(b) is XlError:
        return b
    if x <= 0.0 or b <= 0.0:
        return E_NUM
    if b == 1.0:
        return E_DIV0
    return math.log(x) / math.log(b)


def F_SQRT(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    if x < 0.0:
        return E_NUM
    return math.sqrt(x)


def F_POWER(x, y):
    from .values import _pow
    return _pow(x, y)


def F_INT(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    return _float(math.floor(x))


def F_MOD(n, d):
    n = to_num(n)
    if type(n) is XlError:
        return n
    d = to_num(d)
    if type(d) is XlError:
        return d
    if d == 0.0:
        return E_DIV0
    return n - d * math.floor(n / d)


def _round_half_away(y: float) -> float:
    """Round y to an integer, halves away from zero, on Excel's 15 significant digits."""
    ay = abs(y)
    if ay >= 4503599627370496.0:      # 2**52: already integral
        return y
    f = _float("%.15g" % ay)
    r = math.floor(f + 0.5)
    return -r if y < 0 else r


def xl_round(x: float, digits: int) -> float:
    if digits == 0:
        return _round_half_away(x)
    if digits > 0:
        if digits > 15:
            return x
        m = 10.0 ** digits
        return _round_half_away(x * m) / m
    m = 10.0 ** (-digits)
    return _round_half_away(x / m) * m


def F_ROUND(x, digits=0.0):
    x = to_num(x)
    if type(x) is XlError:
        return x
    d = _int(digits)
    if type(d) is XlError:
        return d
    return xl_round(x, d)


def F_ROUNDUP(x, digits=0.0):
    x = to_num(x)
    if type(x) is XlError:
        return x
    d = _int(digits)
    if type(d) is XlError:
        return d
    m = 10.0 ** d
    y = _float("%.15g" % (abs(x) * m))
    r = math.ceil(y) / m
    return -r if x < 0 else r


def F_ROUNDDOWN(x, digits=0.0):
    x = to_num(x)
    if type(x) is XlError:
        return x
    d = _int(digits)
    if type(d) is XlError:
        return d
    m = 10.0 ** d
    y = _float("%.15g" % (abs(x) * m))
    r = math.floor(y) / m
    return -r if x < 0 else r


def F_TRUNC(x, digits=0.0):
    return F_ROUNDDOWN(x, digits)


def F_SIGN(x):
    x = to_num(x)
    if type(x) is XlError:
        return x
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def F_PI():
    return math.pi


# --------------------------------------------------------------------------- matrices
def _matrix(v) -> Any:
    rows = as_rows(v)
    out = []
    for row in rows:
        r = []
        for x in row:
            if type(x) is XlError:
                raise _Err(x)
            if type(x) is not _float:
                raise _Err(E_VALUE)
            r.append(x)
        out.append(r)
    return out


def F_MMULT(a, b):
    try:
        A, B = _matrix(a), _matrix(b)
    except _Err as e:
        return e.err
    n, k = len(A), len(A[0]) if A else 0
    if k != len(B) or not B:
        return E_VALUE
    m = len(B[0])
    cols = [[B[t][j] for t in range(k)] for j in range(m)]
    out = []
    for i in range(n):
        ai = A[i]
        row = []
        for j in range(m):
            cj = cols[j]
            s = 0.0
            for t in range(k):
                s += ai[t] * cj[t]
            row.append(s)
        out.append(row)
    return XlArray(out)


def F_MINVERSE(a):
    try:
        A = _matrix(a)
    except _Err as e:
        return e.err
    n = len(A)
    if n == 0 or any(len(r) != n for r in A):
        return E_VALUE
    M = [list(A[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for col in range(n):
        piv = col
        best = abs(M[col][col])
        for r in range(col + 1, n):
            v = abs(M[r][col])
            if v > best:
                best, piv = v, r
        if best == 0.0:
            return E_NUM
        if piv != col:
            M[col], M[piv] = M[piv], M[col]
        prow = M[col]
        p = prow[col]
        for j in range(col, 2 * n):
            prow[j] /= p
        for r in range(n):
            if r != col:
                row = M[r]
                f = row[col]
                if f != 0.0:
                    for j in range(col, 2 * n):
                        row[j] -= f * prow[j]
    return XlArray([row[n:] for row in M])


def F_MDETERM(a):
    try:
        A = [list(r) for r in _matrix(a)]
    except _Err as e:
        return e.err
    n = len(A)
    if n == 0 or any(len(r) != n for r in A):
        return E_VALUE
    det = 1.0
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(A[r][col]))
        if A[piv][col] == 0.0:
            return 0.0
        if piv != col:
            A[col], A[piv] = A[piv], A[col]
            det = -det
        det *= A[col][col]
        for r in range(col + 1, n):
            f = A[r][col] / A[col][col]
            if f != 0.0:
                for j in range(col, n):
                    A[r][j] -= f * A[col][j]
    return det


def F_TRANSPOSE(a):
    rows = as_rows(a)
    if not rows:
        return a
    return XlArray([list(col) for col in zip(*rows)])


# --------------------------------------------------------------------------- lookup & reference
def _match_exact(lookup, vals: List[Any]) -> int:
    t = type(lookup)
    if t is _float:
        for i, v in enumerate(vals):
            if type(v) is _float and v == lookup:
                return i
        return -1
    if t is str:
        if _WILD.search(lookup):
            rx = _wild_regex(lookup)
            for i, v in enumerate(vals):
                if type(v) is str and rx.match(v) is not None:
                    return i
            return -1
        up = lookup.upper()
        for i, v in enumerate(vals):
            if type(v) is str and v.upper() == up:
                return i
        return -1
    if t is bool:
        for i, v in enumerate(vals):
            if type(v) is bool and v == lookup:
                return i
        return -1
    return -1


def _same_class(lookup):
    t = type(lookup)
    if t is _float:
        return _float
    if t is str:
        return str
    if t is bool:
        return bool
    return None


def _match_le(lookup, vals: List[Any]) -> int:
    """Binary search for the last element <= lookup among elements of the same type (ascending data)."""
    cls = _same_class(lookup)
    if cls is None:
        return -1
    if cls is str:
        key = lookup.upper()
        idx = [i for i, v in enumerate(vals) if type(v) is str]
        get = lambda i: vals[i].upper()
    else:
        key = lookup
        idx = [i for i, v in enumerate(vals) if type(v) is cls]
        get = lambda i: vals[i]
    lo, hi, res = 0, len(idx) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if get(idx[mid]) <= key:
            res = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return idx[res] if res >= 0 else -1


def _match_ge(lookup, vals: List[Any]) -> int:
    """Descending data: last element >= lookup."""
    cls = _same_class(lookup)
    if cls is None:
        return -1
    if cls is str:
        key = lookup.upper()
        idx = [i for i, v in enumerate(vals) if type(v) is str]
        get = lambda i: vals[i].upper()
    else:
        key = lookup
        idx = [i for i, v in enumerate(vals) if type(v) is cls]
        get = lambda i: vals[i]
    lo, hi, res = 0, len(idx) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if get(idx[mid]) >= key:
            res = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return idx[res] if res >= 0 else -1


def F_MATCH(lookup, arr, mtype=1.0):
    if type(lookup) is XlError:
        return lookup
    if type(mtype) is XlError:
        return mtype
    t = type(arr)
    if t is XlRange or t is XlArray:
        if arr.nr != 1 and arr.nc != 1:
            return E_NA
        vals = arr.flat()
    else:
        vals = [arr]
    if lookup is None:
        return E_NA
    mt = to_num(mtype)
    if type(mt) is XlError:
        return mt
    if mt == 0.0:
        i = _match_exact(lookup, vals)
    elif mt > 0.0:
        i = _match_le(lookup, vals)
    else:
        i = _match_ge(lookup, vals)
    if i < 0:
        return E_NA
    return _float(i + 1)


def F_INDEX(arr, row=None, col=None, area=None):
    """INDEX in reference form: returns an XlRange when ``arr`` is a range."""
    t = type(arr)
    if t is XlError:
        return arr
    r = 0 if row is None else _int(row)
    if type(r) is XlError:
        return r
    c = 0 if col is None else _int(col)
    if type(c) is XlError:
        return c
    if t is not XlRange and t is not XlArray:
        if r in (0, 1) and c in (0, 1):
            return arr
        return E_REF
    nr, nc = arr.nr, arr.nc
    if col is None and row is not None and nr == 1 and nc > 1:
        r, c = 0, r           # INDEX(row_vector, n)
    if r < 0 or c < 0 or r > nr or c > nc:
        return E_REF
    if t is XlRange:
        if r == 0 and c == 0:
            return arr
        if r == 0:
            return arr.sub(0, c - 1, nr - 1, c - 1) if nr > 1 else arr.sub(0, c - 1, 0, c - 1)
        if c == 0:
            return arr.sub(r - 1, 0, r - 1, nc - 1)
        return arr.sub(r - 1, c - 1, r - 1, c - 1)
    rows = arr.rows
    if r == 0 and c == 0:
        return arr
    if r == 0:
        if nr == 1:
            return rows[0][c - 1]
        return XlArray([[rw[c - 1]] for rw in rows])
    if c == 0:
        if nc == 1:
            return rows[r - 1][0]
        return XlArray([list(rows[r - 1])])
    return rows[r - 1][c - 1]


def INDEX_S(X, hr, hc, arr, row=None, col=None, area=None):
    """INDEX where a scalar is wanted (the common case): avoids building a reference object."""
    t = type(arr)
    if t is XlRange:
        r = 0 if row is None else _int(row)
        if type(r) is XlError:
            return r
        c = 0 if col is None else _int(col)
        if type(c) is XlError:
            return c
        nr, nc = arr.nr, arr.nc
        if col is None and row is not None and nr == 1 and nc > 1:
            r, c = 0, r
        if r < 0 or c < 0 or r > nr or c > nc:
            return E_REF
        if r == 0 and nr == 1:
            r = 1
        if c == 0 and nc == 1:
            c = 1
        if r > 0 and c > 0:
            return arr.ctx.cv(arr.si, arr.r1 + r - 1, arr.c1 + c - 1)
    return intersect(F_INDEX(arr, row, col, area), hr, hc)


def F_LOOKUP(lookup, vec, res=None):
    if type(lookup) is XlError:
        return lookup
    vt = type(vec)
    if vt is XlRange or vt is XlArray:
        if res is None and vec.nr > 1 and vec.nc > 1:
            rows = vec.values() if vt is XlRange else vec.rows
            if vec.nc > vec.nr:
                keys, outs = rows[0], rows[-1]
            else:
                keys, outs = [r[0] for r in rows], [r[-1] for r in rows]
        else:
            keys = vec.flat()
            outs = keys if res is None else _flat(res)
    else:
        keys = [vec]
        outs = keys if res is None else _flat(res)
    if lookup is None:
        return E_NA
    i = _match_le(lookup, keys)
    if i < 0:
        return E_NA
    if i >= len(outs):
        return E_NA
    return outs[i]


def F_VLOOKUP(lookup, table, col, approx=True):
    if type(lookup) is XlError:
        return lookup
    c = _int(col)
    if type(c) is XlError:
        return c
    t = type(table)
    if t is not XlRange and t is not XlArray:
        return E_NA
    if c < 1:
        return E_VALUE
    if c > table.nc:
        return E_REF
    rows = table.values() if t is XlRange else table.rows
    keys = [r[0] for r in rows]
    ap = to_bool(approx) if approx is not None else False
    if type(ap) is XlError:
        return ap
    if lookup is None:
        return E_NA
    i = _match_le(lookup, keys) if ap else _match_exact(lookup, keys)
    if i < 0:
        return E_NA
    return rows[i][c - 1]


def F_HLOOKUP(lookup, table, row, approx=True):
    if type(lookup) is XlError:
        return lookup
    r = _int(row)
    if type(r) is XlError:
        return r
    t = type(table)
    if t is not XlRange and t is not XlArray:
        return E_NA
    if r < 1:
        return E_VALUE
    if r > table.nr:
        return E_REF
    rows = table.values() if t is XlRange else table.rows
    keys = rows[0]
    ap = to_bool(approx) if approx is not None else False
    if type(ap) is XlError:
        return ap
    i = _match_le(lookup, keys) if ap else _match_exact(lookup, keys)
    if i < 0:
        return E_NA
    return rows[r - 1][i]


def F_ROWS(v):
    t = type(v)
    if t is XlRange or t is XlArray:
        return _float(v.nr)
    if t is XlError:
        return v
    return 1.0


def F_COLUMNS(v):
    t = type(v)
    if t is XlRange or t is XlArray:
        return _float(v.nc)
    if t is XlError:
        return v
    return 1.0


def F_ROW(v):
    if type(v) is XlRange:
        if v.nr == 1:
            return _float(v.r1)
        return XlArray([[_float(v.r1 + i)] for i in range(v.nr)])
    return E_VALUE


def F_COLUMN(v):
    if type(v) is XlRange:
        if v.nc == 1:
            return _float(v.c1)
        return XlArray([[_float(v.c1 + j) for j in range(v.nc)]])
    return E_VALUE


# --------------------------------------------------------------------------- text
def _txt(v):
    return to_text(v)


def F_TRIM(v):
    s = _txt(v)
    if type(s) is XlError:
        return s
    if "  " not in s:
        return s.strip(" ")
    return " ".join(p for p in s.split(" ") if p)


def F_SUBSTITUTE(text, old, new, instance=None):
    s = _txt(text)
    if type(s) is XlError:
        return s
    o = _txt(old)
    if type(o) is XlError:
        return o
    n = _txt(new)
    if type(n) is XlError:
        return n
    if o == "":
        return s
    if instance is None:
        return s.replace(o, n)
    k = _int(instance)
    if type(k) is XlError:
        return k
    if k < 1:
        return E_VALUE
    pos = -1
    start = 0
    for _ in range(k):
        pos = s.find(o, start)
        if pos < 0:
            return s
        start = pos + len(o)
    return s[:pos] + n + s[pos + len(o):]


def F_FIND(find, within, start=1.0):
    f = _txt(find)
    if type(f) is XlError:
        return f
    w = _txt(within)
    if type(w) is XlError:
        return w
    st = _int(start)
    if type(st) is XlError:
        return st
    if st < 1 or st > len(w) + 1:
        return E_VALUE
    i = w.find(f, st - 1)
    if i < 0:
        return E_VALUE
    return _float(i + 1)


def F_SEARCH(find, within, start=1.0):
    f = _txt(find)
    if type(f) is XlError:
        return f
    w = _txt(within)
    if type(w) is XlError:
        return w
    st = _int(start)
    if type(st) is XlError:
        return st
    if st < 1 or st > len(w) + 1:
        return E_VALUE
    if _WILD.search(f):
        out = []
        i = 0
        while i < len(f):
            ch = f[i]
            if ch == "~" and i + 1 < len(f):
                out.append(re.escape(f[i + 1]))
                i += 2
                continue
            out.append(".*?" if ch == "*" else ("." if ch == "?" else re.escape(ch)))
            i += 1
        m = re.compile("".join(out), re.I | re.S).search(w, st - 1)
        if m is None:
            return E_VALUE
        return _float(m.start() + 1)
    i = w.upper().find(f.upper(), st - 1)
    if i < 0:
        return E_VALUE
    return _float(i + 1)


def F_MID(text, start, count):
    s = _txt(text)
    if type(s) is XlError:
        return s
    st = _int(start)
    if type(st) is XlError:
        return st
    n = _int(count)
    if type(n) is XlError:
        return n
    if st < 1 or n < 0:
        return E_VALUE
    return s[st - 1:st - 1 + n]


def F_LEFT(text, count=1.0):
    s = _txt(text)
    if type(s) is XlError:
        return s
    n = _int(count)
    if type(n) is XlError:
        return n
    if n < 0:
        return E_VALUE
    return s[:n]


def F_RIGHT(text, count=1.0):
    s = _txt(text)
    if type(s) is XlError:
        return s
    n = _int(count)
    if type(n) is XlError:
        return n
    if n < 0:
        return E_VALUE
    return s[len(s) - n:] if n else ""


def F_LEN(text):
    s = _txt(text)
    if type(s) is XlError:
        return s
    return _float(len(s))


def F_UPPER(text):
    s = _txt(text)
    if type(s) is XlError:
        return s
    return s.upper()


def F_LOWER(text):
    s = _txt(text)
    if type(s) is XlError:
        return s
    return s.lower()


def F_VALUE(text):
    t = type(text)
    if t is _float:
        return text
    if t is XlError:
        return text
    if text is None:
        return 0.0
    if t is str:
        n = parse_number_text(text)
        return E_VALUE if n is None else n
    return E_VALUE


def F_TEXT(value, fmt):
    if type(value) is XlError:
        return value
    f = _txt(fmt)
    if type(f) is XlError:
        return f
    return numfmt.format_value(value, f)


def F_FIXED(number, decimals=2.0, no_commas=False):
    x = to_num(number)
    if type(x) is XlError:
        return x
    d = 2 if decimals is None else _int(decimals)
    if type(d) is XlError:
        return d
    nc = to_bool(no_commas) if no_commas is not None else False
    if type(nc) is XlError:
        return nc
    x = xl_round(x, d)
    return numfmt.format_fixed(x, max(d, 0), not nc)


def F_TEXTJOIN(delim, ignore_empty, *texts):
    d = _txt(delim)
    if type(d) is XlError:
        return d
    ig = to_bool(ignore_empty)
    if type(ig) is XlError:
        return ig
    parts = []
    for a in texts:
        for v in _flat(a):
            if type(v) is XlError:
                return v
            s = to_text(v)
            if ig and s == "":
                continue
            parts.append(s)
    return d.join(parts)


def F_CONCATENATE(*texts):
    out = []
    for a in texts:
        s = _txt(a)
        if type(s) is XlError:
            return s
        out.append(s)
    return "".join(out)


def F_CONCAT(*texts):
    out = []
    for a in texts:
        for v in _flat(a):
            if type(v) is XlError:
                return v
            out.append(to_text(v))
    return "".join(out)


def F_EXACT(a, b):
    x = _txt(a)
    if type(x) is XlError:
        return x
    y = _txt(b)
    if type(y) is XlError:
        return y
    return x == y


def F_REPT(text, n):
    s = _txt(text)
    if type(s) is XlError:
        return s
    k = _int(n)
    if type(k) is XlError:
        return k
    if k < 0:
        return E_VALUE
    return s * k


# --------------------------------------------------------------------------- dates
def _serial(v) -> Any:
    x = to_num(v)
    if type(x) is XlError:
        return x
    if x < 0:
        return E_NUM
    return x


def F_DATE(y, m, d):
    yy = _int(y)
    if type(yy) is XlError:
        return yy
    mm = _int(m)
    if type(mm) is XlError:
        return mm
    dd = _int(d)
    if type(dd) is XlError:
        return dd
    if 0 <= yy < 1900:
        yy += 1900
    months = yy * 12 + (mm - 1)
    year, month = divmod(months, 12)
    month += 1
    if year < 1900 or year > 9999:
        return E_NUM
    import datetime as _dt
    base = date_to_serial(_dt.date(year, month, 1))
    return base + (dd - 1)


def F_YEAR(v):
    s = _serial(v)
    if type(s) is XlError:
        return s
    return _float(serial_to_date(s).year)


def F_MONTH(v):
    s = _serial(v)
    if type(s) is XlError:
        return s
    return _float(serial_to_date(s).month)


def F_DAY(v):
    s = _serial(v)
    if type(s) is XlError:
        return s
    if int(s) == 60:
        return 29.0
    return _float(serial_to_date(s).day)


def F_EDATE(start, months):
    s = _serial(start)
    if type(s) is XlError:
        return s
    k = _int(months)
    if type(k) is XlError:
        return k
    d = serial_to_date(s)
    total = d.year * 12 + (d.month - 1) + k
    year, month = divmod(total, 12)
    month += 1
    if year < 1900 or year > 9999:
        return E_NUM
    import calendar
    import datetime as _dt
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date_to_serial(_dt.date(year, month, day))


def F_EOMONTH(start, months):
    s = _serial(start)
    if type(s) is XlError:
        return s
    k = _int(months)
    if type(k) is XlError:
        return k
    d = serial_to_date(s)
    total = d.year * 12 + (d.month - 1) + k
    year, month = divmod(total, 12)
    month += 1
    import calendar
    import datetime as _dt
    return date_to_serial(_dt.date(year, month, calendar.monthrange(year, month)[1]))


def F_WEEKDAY(v, kind=1.0):
    s = _serial(v)
    if type(s) is XlError:
        return s
    k = 1 if kind is None else _int(kind)
    if type(k) is XlError:
        return k
    sunday1 = (int(math.floor(s)) - 1) % 7 + 1          # 1 = Sunday ... 7 = Saturday
    if k == 1 or k == 17:
        return _float(sunday1)
    if k == 2 or k == 11:
        return _float((sunday1 + 5) % 7 + 1)             # 1 = Monday
    if k == 3:
        return _float((sunday1 + 5) % 7)                 # 0 = Monday
    if 12 <= k <= 16:
        first_day = k - 10                                # 12 -> Tuesday(=2 in Monday-1 scale)
        mon1 = (sunday1 + 5) % 7 + 1
        return _float((mon1 - first_day) % 7 + 1)
    return E_NUM


def _holidays(h) -> Any:
    out = set()
    if h is None:
        return out
    for v in _flat(h):
        tv = type(v)
        if tv is _float:
            out.add(int(math.floor(v)))
        elif tv is XlError:
            return v
        elif tv is str:
            n = parse_number_text(v)
            if n is None:
                return E_VALUE
            out.add(int(math.floor(n)))
    return out


_HOLIDAY_CACHE: Dict[int, Any] = {}


def F_WORKDAY(start, days, holidays=None):
    s = _serial(start)
    if type(s) is XlError:
        return s
    n = _int(days)
    if type(n) is XlError:
        return n
    if type(holidays) is XlRange:
        flat = holidays.flat()
        hol = _HOLIDAY_CACHE.get(id(flat))
        if hol is None or hol[0] is not flat:
            hs = _holidays(holidays)
            _HOLIDAY_CACHE[id(flat)] = (flat, hs)
            if len(_HOLIDAY_CACHE) > 64:
                _HOLIDAY_CACHE.clear()
                _HOLIDAY_CACHE[id(flat)] = (flat, hs)
        else:
            hs = hol[1]
    else:
        hs = _holidays(holidays)
    if type(hs) is XlError:
        return hs
    d = int(math.floor(s))
    if n == 0:
        return _float(d)
    step = 1 if n > 0 else -1
    left = abs(n)
    while left:
        d += step
        wd = d % 7                    # 0 = Saturday, 1 = Sunday
        if wd > 1 and d not in hs:
            left -= 1
    return _float(d)


def F_NETWORKDAYS(start, end, holidays=None):
    s = _serial(start)
    if type(s) is XlError:
        return s
    e = _serial(end)
    if type(e) is XlError:
        return e
    hs = _holidays(holidays)
    if type(hs) is XlError:
        return hs
    a, b = int(math.floor(s)), int(math.floor(e))
    sign = 1.0
    if a > b:
        a, b = b, a
        sign = -1.0
    n = 0
    for d in range(a, b + 1):
        if d % 7 > 1 and d not in hs:
            n += 1
    return sign * n


def F_DAYS(end, start):
    e = to_num(end)
    if type(e) is XlError:
        return e
    s = to_num(start)
    if type(s) is XlError:
        return s
    return _float(math.floor(e) - math.floor(s))


def F_YEARFRAC(start, end, basis=0.0):
    s = _serial(start)
    if type(s) is XlError:
        return s
    e = _serial(end)
    if type(e) is XlError:
        return e
    b = 0 if basis is None else _int(basis)
    if type(b) is XlError:
        return b
    if s > e:
        s, e = e, s
    if b == 2:
        return (e - s) / 360.0
    if b == 3:
        return (e - s) / 365.0
    d1, d2 = serial_to_date(s), serial_to_date(e)
    import calendar
    import datetime as _dt

    def last_of_feb(d):
        return d.month == 2 and d.day == calendar.monthrange(d.year, 2)[1]

    if b in (0, 4):
        dd1, dd2 = d1.day, d2.day
        if b == 4:
            dd1, dd2 = min(dd1, 30), min(dd2, 30)
        elif dd1 == 31:                       # US 30/360 as Excel applies it - the end of February included
            dd1 = 30
            if dd2 == 31:
                dd2 = 30
        elif dd1 == 30 and dd2 == 31:
            dd2 = 30
        elif last_of_feb(d1):
            dd1 = 30
            if last_of_feb(d2):
                dd2 = 30
        return ((d2.year - d1.year) * 360 + (d2.month - d1.month) * 30 + (dd2 - dd1)) / 360.0
    # basis 1: actual/actual - a year at most apart: 366 days when a 29 February lies in the period
    if d1.year == d2.year:
        return (e - s) / (366.0 if calendar.isleap(d1.year) else 365.0)
    if d2.year == d1.year + 1 and (d1.month, d1.day) >= (d2.month, d2.day):
        leap = any(calendar.isleap(y) and d1 <= _dt.date(y, 2, 29) <= d2 for y in (d1.year, d2.year))
        return (e - s) / (366.0 if leap else 365.0)
    years = d2.year - d1.year + 1
    days = sum(366 if calendar.isleap(y) else 365 for y in range(d1.year, d2.year + 1))
    return (e - s) / (days / years)


# --------------------------------------------------------------------------- lifting (array formulas)
def LIFT(fn, vpos, args):
    """Call ``fn`` element-wise over the array arguments found at the value positions ``vpos``."""
    multi = None
    for i in vpos:
        if i < len(args):
            t = type(args[i])
            if t is XlArray or t is XlRange:
                if multi is None:
                    multi = {}
                multi[i] = as_rows(args[i])
    if multi is None:
        return fn(*args)
    nr = nc = 1
    for m in multi.values():
        if len(m) > nr:
            nr = len(m)
        if m and len(m[0]) > nc:
            nc = len(m[0])
    out = []
    call = list(args)
    for i in range(nr):
        row = []
        for j in range(nc):
            bad = False
            for k, m in multi.items():
                n1 = len(m)
                n2 = len(m[0]) if m else 0
                ii = 0 if n1 == 1 else i
                jj = 0 if n2 == 1 else j
                if ii >= n1 or jj >= n2:
                    bad = True
                    break
                call[k] = m[ii][jj]
            if bad:
                row.append(E_NA)
            else:
                res = fn(*call)
                tr = type(res)
                if tr is XlRange or tr is XlArray:
                    res = first(res)
                row.append(res)
        out.append(row)
    return XlArray(out)


# --------------------------------------------------------------------------- registry
class FuncSpec(object):
    __slots__ = ("name", "fn", "kinds", "rest", "multi", "pyname")

    def __init__(self, name: str, fn, kinds: str, rest: str = "", multi: bool = False):
        self.name = name
        self.fn = fn
        self.kinds = kinds          # one letter per leading parameter
        self.rest = rest            # repeating pattern for the remaining parameters
        self.multi = multi          # may return a reference / array
        self.pyname = fn.__name__

    def kind(self, i: int) -> str:
        if i < len(self.kinds):
            return self.kinds[i]
        if self.rest:
            return self.rest[(i - len(self.kinds)) % len(self.rest)]
        return "v"


FUNCS: Dict[str, FuncSpec] = {}


def _reg(name, fn, kinds="", rest="", multi=False):
    FUNCS[name] = FuncSpec(name, fn, kinds, rest, multi)


_reg("SUM", F_SUM, "", "r")
_reg("AVERAGE", F_AVERAGE, "", "r")
_reg("MIN", F_MIN, "", "r")
_reg("MAX", F_MAX, "", "r")
_reg("COUNT", F_COUNT, "", "r")
_reg("COUNTA", F_COUNTA, "", "r")
_reg("STDEV", F_STDEV, "", "r")
_reg("STDEV.S", F_STDEV, "", "r")
_reg("STDEVP", F_STDEVP, "", "r")
_reg("STDEV.P", F_STDEVP, "", "r")
_reg("MEDIAN", F_MEDIAN, "", "r")
_reg("SUMPRODUCT", F_SUMPRODUCT, "", "a")
_reg("LARGE", F_LARGE, "av")
_reg("AGGREGATE", F_AGGREGATE, "vv", "a")
_reg("FILTER", F_FILTER, "aav", multi=True)
_reg("SMALL", F_SMALL, "av")
_reg("SLOPE", F_SLOPE, "aa")
_reg("INTERCEPT", F_INTERCEPT, "aa")
_reg("COUNTIF", F_COUNTIF, "rv")
_reg("COUNTIFS", F_COUNTIFS, "", "rv")
_reg("SUMIF", F_SUMIF, "rvr")
_reg("SUMIFS", F_SUMIFS, "r", "rv")
_reg("AVERAGEIFS", F_AVERAGEIFS, "r", "rv")
_reg("MINIFS", F_MINIFS, "r", "rv")
_reg("MAXIFS", F_MAXIFS, "r", "rv")
_reg("AND", F_AND, "", "r")
_reg("OR", F_OR, "", "r")
_reg("NOT", F_NOT, "v")
_reg("ISNUMBER", F_ISNUMBER, "v")
_reg("ISTEXT", F_ISTEXT, "v")
_reg("ISBLANK", F_ISBLANK, "v")
_reg("ISERROR", F_ISERROR, "v")
_reg("ISERR", F_ISERR, "v")
_reg("ISNA", F_ISNA, "v")
_reg("ISLOGICAL", F_ISLOGICAL, "v")
_reg("N", F_N, "v")
_reg("ABS", F_ABS, "v")
_reg("EXP", F_EXP, "v")
_reg("LN", F_LN, "v")
_reg("LOG10", F_LOG10, "v")
_reg("LOG", F_LOG, "vv")
_reg("SQRT", F_SQRT, "v")
_reg("POWER", F_POWER, "vv")
_reg("INT", F_INT, "v")
_reg("MOD", F_MOD, "vv")
_reg("ROUND", F_ROUND, "vv")
_reg("ROUNDUP", F_ROUNDUP, "vv")
_reg("ROUNDDOWN", F_ROUNDDOWN, "vv")
_reg("TRUNC", F_TRUNC, "vv")
_reg("SIGN", F_SIGN, "v")
_reg("PI", F_PI, "")
_reg("MMULT", F_MMULT, "aa", multi=True)
_reg("MINVERSE", F_MINVERSE, "a", multi=True)
_reg("MDETERM", F_MDETERM, "a")
_reg("TRANSPOSE", F_TRANSPOSE, "a", multi=True)
_reg("MATCH", F_MATCH, "vrv")
_reg("INDEX", F_INDEX, "avvv", multi=True)
_reg("LOOKUP", F_LOOKUP, "vaa")
_reg("VLOOKUP", F_VLOOKUP, "vrvv")
_reg("HLOOKUP", F_HLOOKUP, "vrvv")
_reg("ROWS", F_ROWS, "r")
_reg("COLUMNS", F_COLUMNS, "r")
_reg("TRIM", F_TRIM, "v")
_reg("SUBSTITUTE", F_SUBSTITUTE, "vvvv")
_reg("FIND", F_FIND, "vvv")
_reg("SEARCH", F_SEARCH, "vvv")
_reg("MID", F_MID, "vvv")
_reg("LEFT", F_LEFT, "vv")
_reg("RIGHT", F_RIGHT, "vv")
_reg("LEN", F_LEN, "v")
_reg("UPPER", F_UPPER, "v")
_reg("LOWER", F_LOWER, "v")
_reg("VALUE", F_VALUE, "v")
_reg("TEXT", F_TEXT, "vv")
_reg("FIXED", F_FIXED, "vvv")
_reg("TEXTJOIN", F_TEXTJOIN, "vv", "r")
_reg("CONCATENATE", F_CONCATENATE, "", "v")
_reg("CONCAT", F_CONCAT, "", "r")
_reg("EXACT", F_EXACT, "vv")
_reg("REPT", F_REPT, "vv")
_reg("DATE", F_DATE, "vvv")
_reg("YEAR", F_YEAR, "v")
_reg("MONTH", F_MONTH, "v")
_reg("DAY", F_DAY, "v")
_reg("EDATE", F_EDATE, "vv")
_reg("EOMONTH", F_EOMONTH, "vv")
_reg("WEEKDAY", F_WEEKDAY, "vv")
_reg("WORKDAY", F_WORKDAY, "vvr")
_reg("NETWORKDAYS", F_NETWORKDAYS, "vvr")
_reg("DAYS", F_DAYS, "vv")
_reg("YEARFRAC", F_YEARFRAC, "vvv")
