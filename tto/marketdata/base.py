"""Provider base class: turns add-in function calls of the workbook into market-data lookups.

The workbook formulas call ``BDP`` / ``BDH`` / ``BDS`` / ``BFXFORWARD`` / ``BINTERPOL`` / ``RTGET``.  The
engine forwards every call to :meth:`Provider.call`, which normalises the arguments into a hashable *key*
and asks the concrete provider for the value.  Each lookup also records the dependency of the formula on
that key, so that a later change of the item invalidates exactly the cells that used it.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..xl.errors import E_NA, E_VALUE, XlError
from ..xl.values import XlArray, XlRange, date_to_serial, first, parse_number_text, serial_to_date, to_text

REQUESTING = "#N/A Requesting Data..."
NOT_APPLICABLE = "#N/A Field Not Applicable"
INVALID_SECURITY = "#N/A Invalid Security"
INVALID_FIELD = "#N/A Invalid Field"

#: override names whose value is a date (Excel serial numbers are sent to Bloomberg as YYYYMMDD)
_DATE_OVERRIDE_HINTS = ("_DT", "_DATE", "DATE_OVERRIDE")


def _scalar(v: Any) -> Any:
    t = type(v)
    if t is XlRange or t is XlArray:
        return first(v)
    return v


def _text(v: Any) -> Optional[str]:
    v = _scalar(v)
    if v is None or type(v) is XlError:
        return None
    s = to_text(v)
    if type(s) is XlError:
        return None
    return s.strip()


def yyyymmdd(v: Any) -> Optional[str]:
    """Excel date (serial number / text date / YYYYMMDD) -> 'YYYYMMDD'."""
    v = _scalar(v)
    if v is None or type(v) is XlError:
        return None
    if type(v) is str:
        s = v.strip()
        if len(s) == 8 and s.isdigit():
            return s
        n = parse_number_text(s)
        if n is None:
            return None
        v = n
    if type(v) is bool:
        return None
    x = float(v)
    if 19000101 <= x <= 99991231 and x == int(x):
        return "%d" % x
    if x <= 0 or x > 2958465:
        return None
    return serial_to_date(x).strftime("%Y%m%d")


def override_pairs(args: Sequence[Any]) -> Tuple[Tuple[str, str], ...]:
    """BDP optional arguments -> sorted ((NAME, value), ...).

    Excel accepts ``"NAME", value`` pairs as well as ``"NAME=value"`` strings, in any mix.
    """
    out: List[Tuple[str, str]] = []
    i = 0
    n = len(args)
    while i < n:
        a = _scalar(args[i])
        if a is None:
            i += 1
            continue
        if type(a) is str and "=" in a:
            name, _, val = a.partition("=")
            out.append((name.strip().upper(), val.strip()))
            i += 1
            continue
        name = _text(a)
        val = _scalar(args[i + 1]) if i + 1 < n else None
        i += 2
        if not name:
            continue
        name = name.upper()
        if type(val) is float and any(h in name for h in _DATE_OVERRIDE_HINTS) and 20000 < val < 80000:
            sval = serial_to_date(val).strftime("%Y%m%d")
        elif type(val) is str and any(h in name for h in _DATE_OVERRIDE_HINTS):
            sval = yyyymmdd(val) or val.strip()
        elif type(val) is float:
            sval = ("%d" % val) if val == int(val) and abs(val) < 1e15 else repr(val)
        elif val is None:
            sval = ""
        else:
            t = to_text(val)
            sval = "" if type(t) is XlError else t
        out.append((name, sval))
    return tuple(sorted(out))


def bdp_key(security: str, field: str, overrides: Tuple[Tuple[str, str], ...] = ()) -> Tuple:
    return ("BDP", security, field.upper(), overrides)


def bds_key(security: str, field: str, overrides: Tuple[Tuple[str, str], ...] = ()) -> Tuple:
    return ("BDS", security, field.upper(), overrides)


def bdh_key(security: str, field: str, start: str, end: str, options: Tuple[Tuple[str, str], ...]) -> Tuple:
    return ("BDH", security, field.upper(), start, end, options)


def bdh_options(args: Sequence[Any]) -> Tuple[Tuple[str, str], ...]:
    """'Days=W', 'Fill=P', 'Dates=H' ... -> sorted ((NAME, VALUE), ...) with canonical names."""
    canon = {"DTS": "DATES", "DATES": "DATES", "DAYS": "DAYS", "FILL": "FILL", "PER": "PER", "PERIOD": "PER",
             "SORT": "SORT", "DIR": "DIR", "DIRECTION": "DIR", "CDR": "CDR", "FX": "FX", "POINTS": "POINTS",
             "QUOTE": "QUOTE", "QUOTETYPE": "QUOTETYPE", "USEDPDF": "USEDPDF"}
    out = []
    i = 0
    n = len(args)
    while i < n:
        a = _text(args[i])
        if a and "=" in a:
            k, _, v = a.partition("=")
            out.append((canon.get(k.strip().upper(), k.strip().upper()), v.strip().upper()))
            i += 1
        elif a and i + 1 < n:
            v = _text(args[i + 1]) or ""
            out.append((canon.get(a.upper(), a.upper()), v.upper()))
            i += 2
        else:
            i += 1
    return tuple(sorted(out))


def binterpol(xs: Any, ys: Any, x: Any, method: Any = "LINEAR") -> Any:
    """Bloomberg ``BInterpol``: interpolate y at x through the points (xs, ys) - linear."""
    fx = xs.flat() if type(xs) in (XlRange, XlArray) else [xs]
    fy = ys.flat() if type(ys) in (XlRange, XlArray) else [ys]
    x = _scalar(x)
    if type(x) is XlError:
        return x
    if type(x) is not float:
        n = parse_number_text(x) if type(x) is str else None
        if n is None:
            return E_VALUE
        x = n
    pts = sorted((a, b) for a, b in zip(fx, fy) if type(a) is float and type(b) is float)
    if len(pts) < 2:
        return E_NA
    if x <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    elif x >= pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
    else:
        lo, hi = 0, len(pts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pts[mid][0] <= x:
                lo = mid
            else:
                hi = mid
        (x0, y0), (x1, y1) = pts[lo], pts[hi]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def tr_date_text(d: _dt.date) -> str:
    """Date as the desk's Excel shows BDP dates (Turkish short date: 4.11.2026 / 4.01.2027)."""
    return "%d.%02d.%d" % (d.day, d.month, d.year)


class Provider(object):
    """Base class.  Concrete providers implement the ``get_*`` methods."""

    #: True when the provider delivers live data (stale workbook values must then never be shown)
    live = False

    # ------------------------------------------------------------------ to be implemented
    def get_bdp(self, key: Tuple) -> Any:
        return E_NA

    def get_bdh(self, key: Tuple) -> Any:
        return E_NA

    def get_bds(self, key: Tuple) -> Any:
        return E_NA

    def get_bfx(self, key: Tuple) -> Any:
        return E_NA

    def get_rt(self, key: Tuple) -> Any:
        return E_NA

    def status(self) -> Dict[str, Any]:
        return {"mode": "none", "connected": False}

    def history(self, items: Sequence[Tuple[str, str]], start: str, end: str,
                timeout: float = 60.0) -> Dict[Tuple[str, str], List[Tuple[str, float]]]:
        """Daily closes of ``(security, FIELD)`` items between two dates (``YYYYMMDD``), outside of any
        workbook formula: ``{(security, FIELD): [("yyyy-mm-dd", value), ...]}`` in date order, trading days
        only.  Items without history are left out.  May block for up to ``timeout`` seconds - never call it
        on the calculation thread."""
        return {}

    # ------------------------------------------------------------------ dispatch
    def call(self, calc, name: str, si: int, r: int, c: int, args: Sequence[Any]) -> Any:
        if name == "BDP":
            return self._bdp(calc, args)
        if name == "BDH":
            return self._bdh(calc, args)
        if name == "BDS":
            return self._bds(calc, args)
        if name == "BINTERPOL":
            if len(args) < 3:
                return E_VALUE
            return binterpol(args[0], args[1], args[2], args[3] if len(args) > 3 else "LINEAR")
        if name == "BFXFORWARD":
            return self._bfx(calc, args)
        if name == "RTGET":
            return self._rt(calc, args)
        return E_NA

    def _bdp(self, calc, args):
        if len(args) < 2:
            return E_VALUE
        sec = _text(args[0])
        fld = _text(args[1])
        if not sec:
            return INVALID_SECURITY
        if not fld:
            return INVALID_FIELD
        key = bdp_key(sec, fld, override_pairs(args[2:]))
        calc.depend_on_market(key)
        return self.get_bdp(key)

    def _bds(self, calc, args):
        if len(args) < 2:
            return E_VALUE
        sec = _text(args[0])
        fld = _text(args[1])
        if not sec:
            return INVALID_SECURITY
        if not fld:
            return INVALID_FIELD
        key = bds_key(sec, fld, override_pairs(args[2:]))
        calc.depend_on_market(key)
        return self.get_bds(key)

    def _bdh(self, calc, args):
        if len(args) < 3:
            return E_VALUE
        sec = _text(args[0])
        fld = _text(args[1])
        start = yyyymmdd(args[2])
        end = yyyymmdd(args[3]) if len(args) > 3 and _scalar(args[3]) not in (None, "") else start
        if not sec:
            return INVALID_SECURITY
        if not fld:
            return INVALID_FIELD
        if start is None or end is None:
            return E_NA
        key = bdh_key(sec, fld, start, end, bdh_options(args[4:]))
        calc.depend_on_market(key)
        return self.get_bdh(key)

    def _bfx(self, calc, args):
        if len(args) < 2:
            return E_VALUE
        pair = _text(args[0])
        date = yyyymmdd(args[1])
        kind = (_text(args[2]) if len(args) > 2 else None) or "MidOutright"
        if not pair or date is None:
            return E_NA
        key = ("BFX", pair.upper().replace(" ", ""), date, kind.upper())
        calc.depend_on_market(key)
        return self.get_bfx(key)

    def _rt(self, calc, args):
        if len(args) < 3:
            return E_VALUE
        src, ric, fld = _text(args[0]), _text(args[1]), _text(args[2])
        if not ric or not fld:
            return E_NA
        key = ("RT", src or "", ric, fld.upper())
        calc.depend_on_market(key)
        return self.get_rt(key)
