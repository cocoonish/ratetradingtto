"""A date typed the way the desk says it: a tenor, a month end, an IMM date or a number of business days.

Amounts take the desk's shorthand in :func:`tto.inputs.parse_amount` ("5m", "250k", "1,5mn", "2mr"); this module is
the dates - of input cells formatted as dates (or declared ``"kind": "date"``) and of Günlük İşlemler's value date.

=================  ======================================================================================================
``1A`` ``1M``      months (ay / month) from the start: the same day so many months on (Excel's EDATE), then - a weekend
``3A`` ``6A``      or a holiday of the calendar - the next business day: the workbook's own rule for its tenors,
``18M``            ``WORKDAY(EDATE(spot, n) - 1, 1, holidays)``
``1Y`` ``2Y``      years (yıl / year): twelve months each
``2H`` ``2W``      weeks (hafta / week): seven days each, rolled the same way
``ON``             overnight: the business day after today (``O/N``)
``TN``             tom-next: two business days after today (``T/N``)
``SN``             spot-next: the business day after the start (``S/N``)
``ay sonu``        the last business day of the start's month - of the next month when the start is that day or after it
                   (``aysonu``, ``EOM``)
``IMM``            the next IMM date after the start: the third Wednesday of March, June, September or December (the
                   business day after it if that is a holiday)
``+5``             five business days after the start
=================  ======================================================================================================

Case, the Turkish dotted / dotless i and spaces do not matter ("3m" is "3M").  "The start" is the cell's natural start,
the caller's to say: the row's spot / value date where the page definition names one (``"tenor"`` of an input,
tto/views/__init__.py) or the cell's formulas do (tto/datecells.py: the date the workbook counts its days from), else
today's spot.  The business days are those of the calendar the caller gives (the desk's holiday lists of both
currencies of the pair: :func:`tto.extras.pair_calendar`).  Text that starts with "=" is a formula, never a shortcut;
anything that is no shortcut here (a date, a number) is parsed as it always was.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional, Tuple

from .fx import add_week_days, week_day_on_or_after
from .history import add_months
from .inputs import _fold

#: a shortcut: (kind, n) - "M" months, "W" weeks, "BD" business days, "ON" / "TN" / "SN", "EOM", "IMM"
Shortcut = Tuple[str, int]

_TENOR = re.compile(r"^(\d{1,3})\s*(a|ay|m|y|yil|h|w)$")
_UNIT = {"a": ("M", 1), "ay": ("M", 1), "m": ("M", 1), "y": ("M", 12), "yil": ("M", 12), "h": ("W", 1), "w": ("W", 1)}
_NEXT = {"on": "ON", "o/n": "ON", "tn": "TN", "t/n": "TN", "sn": "SN", "s/n": "SN"}
_BUSINESS = re.compile(r"^\+\s*(\d{1,3})$")
_MONTH_END = re.compile(r"^(ay\s*sonu|eom)$")


def date_shortcut(text: Any) -> Optional[Shortcut]:
    """What a typed text means as a date shortcut - ``None`` when it is none (a date, a number, a formula, anything)."""
    if not isinstance(text, str):
        return None
    s = " ".join(_fold(text).split())
    if not s or s.startswith("="):
        return None
    m = _TENOR.match(s)
    if m:
        kind, k = _UNIT[m.group(2)]
        return kind, int(m.group(1)) * k
    if s in _NEXT:
        return _NEXT[s], 0
    m = _BUSINESS.match(s)
    if m:
        return "BD", int(m.group(1))
    if _MONTH_END.match(s):
        return "EOM", 0
    if s == "imm":
        return "IMM", 0
    return None


def _last_business_day(year: int, month: int, holidays: Any) -> _dt.date:
    d = _dt.date(year + month // 12, month % 12 + 1, 1) - _dt.timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d -= _dt.timedelta(days=1)
    return d


def _third_wednesday(year: int, month: int) -> _dt.date:
    first = _dt.date(year, month, 1)
    return first + _dt.timedelta(days=(2 - first.weekday()) % 7 + 14)


def next_imm(after: _dt.date) -> _dt.date:
    """The first IMM date (third Wednesday of March, June, September, December) after ``after``."""
    y, m = after.year, after.month
    while True:
        if m % 3 == 0:
            d = _third_wednesday(y, m)
            if d > after:
                return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def resolve(shortcut: Shortcut, start: _dt.date, today: _dt.date, holidays: Any = ()) -> _dt.date:
    """The date a shortcut stands for: counted from ``start`` (ON / TN from ``today``), on the business days of
    ``holidays`` (dates; weekends are never business days)."""
    kind, n = shortcut
    if kind == "M":
        return week_day_on_or_after(add_months(start, n), holidays)
    if kind == "W":
        return week_day_on_or_after(start + _dt.timedelta(days=7 * n), holidays)
    if kind == "ON":
        return add_week_days(today, 1, holidays)
    if kind == "TN":
        return add_week_days(today, 2, holidays)
    if kind == "SN":
        return add_week_days(start, 1, holidays)
    if kind == "BD":
        return add_week_days(start, n, holidays)
    if kind == "EOM":
        d = _last_business_day(start.year, start.month, holidays)
        return d if d > start else _last_business_day(start.year + start.month // 12, start.month % 12 + 1, holidays)
    if kind == "IMM":
        return week_day_on_or_after(next_imm(start), holidays)
    raise ValueError("bilinmeyen kısayol: %r" % (shortcut,))
