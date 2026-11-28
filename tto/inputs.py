"""Parsing of what users type or paste into input cells."""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional, Tuple

from .xl.values import date_to_serial, serial_to_date

_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DMY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$")
_YMD = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
#: a day and its month without a year: "26/12", "26.12", "26-12" (the desk, 28.11.2026)
_DM = re.compile(r"^(\d{1,2})[./-](\d{1,2})$")
_TR_MONTHS = {"oca": 1, "şub": 2, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7, "ağu": 8, "agu": 8,
              "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
              "jan": 1, "feb": 2, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


class InputError(ValueError):
    pass


_GROUP_DOT = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+$")
_GROUP_COMMA = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")
_ONE_GROUP_DOT = re.compile(r"^[+-]?[1-9]\d{0,2}\.\d{3}$")
_ONE_GROUP_COMMA = re.compile(r"^[+-]?[1-9]\d{0,2},\d{3}$")


def parse_number(text: str, lang: str = "tr", prefer_decimal: bool = False) -> Optional[float]:
    """Number as a person writes it: ``35,55`` ``35.55`` ``1.234,56`` ``1,234.56`` ``%35`` ``35%`` ``(12,5)``.

    Returns ``None`` when the text is not a number.  A trailing / leading ``%`` divides by 100.

    ``lang`` is the number format the user works in (the same one the dashboard displays and copies in):
    with ``"tr"`` a lone ``12.345`` is twelve thousand ..., exactly as Turkish Excel reads it, and with
    ``"en"`` a lone ``12,345`` is.  Everything that cannot be a grouped integer (``35.55``, ``0.355``,
    ``1234.5``) is read as a decimal in either language.  ``prefer_decimal`` (rates, prices) switches the
    grouped-integer reading off.
    """
    s = text.strip().replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    if not s:
        return None
    pct = False
    if s.endswith("%"):
        pct, s = True, s[:-1]
    elif s.startswith("%"):
        pct, s = True, s[1:]
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("\u2212") or s.startswith("\u2013"):
        s = "-" + s[1:]
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):          # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                    # 1,234.56
            s = s.replace(",", "")
    elif has_comma:
        if s.count(",") > 1:
            if not _GROUP_COMMA.match(s):
                return None
            s = s.replace(",", "")               # 1,234,567
        elif lang == "en" and not prefer_decimal and _ONE_GROUP_COMMA.match(s):
            s = s.replace(",", "")               # 12,345 in an English workbook
        else:
            s = s.replace(",", ".")              # 35,55
    elif has_dot:
        if s.count(".") > 1:
            if not _GROUP_DOT.match(s):
                return None
            s = s.replace(".", "")               # 1.234.567
        elif lang != "en" and not prefer_decimal and _ONE_GROUP_DOT.match(s):
            s = s.replace(".", "")               # 12.345 in a Turkish workbook
    if not _NUM.match(s):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    if neg:
        x = -x
    if pct:
        x /= 100.0
    return x


_AMOUNT = re.compile(r"^\s*([+-]?[\d.,\s]+?)\s*(k|bin|m|mn|mln|mio|milyon|b|bn|mr|mlr|milyar)?\s*$", re.IGNORECASE)
_UNITS = {"k": 1e3, "bin": 1e3, "m": 1e6, "mn": 1e6, "mln": 1e6, "mio": 1e6, "milyon": 1e6,
          "b": 1e9, "bn": 1e9, "mr": 1e9, "mlr": 1e9, "milyar": 1e9}


def parse_amount(text: str, lang: str = "tr") -> Optional[float]:
    """A trade size as a trader types it: ``10m``, ``2,5 mio``, ``500k``, ``2mr``, ``1.000.000`` - the number in either
    decimal convention, as :func:`parse_number` reads it in ``lang`` (``1,5mn`` and ``1.5mn`` are both 1.500.000)."""
    m = _AMOUNT.match(text or "")
    if not m:
        return None
    x = parse_number(m.group(1), lang)
    if x is None:
        return None
    return x * _UNITS.get((m.group(2) or "").lower(), 1.0)


def as_day(when: Any) -> _dt.date:
    """A day given as a date (a datetime's day), an Excel serial or an ISO text ("2026-11-28")."""
    if isinstance(when, _dt.datetime):
        return when.date()
    if isinstance(when, _dt.date):
        return when
    if isinstance(when, (int, float)) and not isinstance(when, bool):
        return serial_to_date(float(when))
    return _dt.date.fromisoformat(str(when).strip()[:10])


def yearless(text: Any) -> Optional[Tuple[int, int]]:
    """(day, month) of a date typed without its year - ``26/12``, ``26.12``, ``26-12``, ``26 Ara``, ``26 Aralık`` -;
    ``None`` for any other text (a date with its year, a number, a tenor)."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    m = _DM.match(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    parts = re.split(r"[\s.\-/]+", s)
    if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 2 and _fold(parts[1])[:3] in _TR_MONTHS:
        return int(parts[0]), _TR_MONTHS[_fold(parts[1])[:3]]
    return None


def day_month(day: int, month: int, today: Any, past: bool = False, after: Any = None) -> Optional[_dt.date]:
    """The day ``day``.``month`` the desk means when it types no year (the desk, 28.11.2026: "26/12 yazdigimda otomatik
    2026, 1/2 yazdigimda otomatik 2027"): the first one from ``today`` on - and from ``after`` on, when it is later (the
    end of a period counts from its start: "1/3" after a start of 15.06.2027 is 01.03.2028) -; with ``past`` (a cell
    that asks about the past: yesterday's date, a trade's day) the last one up to ``today``.  29 February is the nearest
    one there is that way (29.02.2028 from 28.11.2026; 29.02.2024 back); a day no year has (31.04, 30.02, 0.5, 1.13) is
    ``None``."""
    t = as_day(today)
    if not past and after is not None:
        t = max(t, as_day(after))
    step = -1 if past else 1
    for k in range(9):                       # (two 29 Februaries are at most eight years apart: 2096 → 2104)
        try:
            d = _dt.date(t.year + step * k, month, day)
        except (ValueError, OverflowError):
            if month == 2 and day == 29:
                continue                     # (not a leap year: the next one)
            return None
        if (d <= t) if past else (d >= t):
            return d
    return None


def parse_date(text: str, today: Any = None, past: bool = False, after: Any = None) -> Optional[float]:
    """Date text -> Excel serial (``3.11.2026``, ``03/11/26``, ``2026-11-03``, ``3 Kas 2026``).

    A day and month without a year (``26/12``, ``26.12``, ``26-12``, ``26 Ara``: :func:`yearless`) is read only when
    ``today`` is given - a date a user types, where the caller knows the day and which way the input looks: the next
    such day from ``today`` on (from ``after`` on when that is later), ``past`` the last one (:func:`day_month`).  A value
    read from a workbook or a store always has its year and is never given one."""
    s = text.strip()
    m = _DMY.match(s)
    try:
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            return date_to_serial(_dt.date(y, mo, d))
        m = _YMD.match(s)
        if m:
            return date_to_serial(_dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        parts = re.split(r"[\s.\-/]+", s)
        if len(parts) == 3 and parts[1][:3].lower() in _TR_MONTHS:
            y = int(parts[2])
            if y < 100:
                y += 2000
            return date_to_serial(_dt.date(y, _TR_MONTHS[parts[1][:3].lower()], int(parts[0])))
        if today is not None:
            dm = yearless(s)
            if dm is not None:
                d = day_month(dm[0], dm[1], today, past, after)
                return date_to_serial(d) if d is not None else None
    except (ValueError, OverflowError):
        return None
    return None


def _fold(text: str) -> str:
    """Text compared without case - the Turkish dotted / dotless i included ("viop" is "VİOP")."""
    return text.casefold().replace("\u0307", "").replace("\u0131", "i")


#: what a tick box (``"kind": "check"``) takes besides 1 and 0: the words for ticked / not ticked (folded, as typed or pasted)
CHECK_WORDS = {_fold(w): 1.0 for w in ("evet", "doğru", "true", "x", "✓", "✔")}
CHECK_WORDS.update({_fold(w): 0.0 for w in ("hayır", "yanlış", "false")})
CHECK_REFUSED = "tik kutusu: 1 (seçili) ya da 0 (seçili değil)"


def parse_check(raw: Any, lang: str = "tr") -> Optional[float]:
    """A tick box's value: 1.0 ticked, 0.0 not - a click writes "1" / "0"; typed or pasted also "evet" / "hayır", TRUE /
    FALSE, "x" / "✓".  Empty text is ``None`` (the cell back to its default); anything else is refused."""
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        if raw in (0, 1):
            return float(raw)
        raise InputError(CHECK_REFUSED)
    s = str(raw).strip()
    if s == "":
        return None
    n = parse_number(s, lang)
    if n in (0.0, 1.0):
        return float(n)
    if _fold(s) in CHECK_WORDS:
        return CHECK_WORDS[_fold(s)]
    raise InputError("%s: %r" % (CHECK_REFUSED, s))


def parse_input(raw: Any, percent_cell: bool = False, date_cell: bool = False, kind: str = "auto",
                options: Optional[List[str]] = None, lang: str = "tr", aliases: Optional[Dict[str, str]] = None,
                today: Any = None, past: bool = False, after: Any = None) -> Any:
    """Convert user text to the value stored in the cell.

    * empty text -> ``None`` (blank cell)
    * date cells accept dates (or serial numbers) - a day and month without a year too ("26/12": the next such day from
      ``today`` - the computer's day when the caller gives none - on, from ``after`` on when that is later; ``past``: the
      last one - :func:`parse_date`); a list of days kept as text takes such a day as its item
    * percent cells store a fraction: ``35,5`` / ``35,5%`` / ``0,355`` all give 0.355 (Excel's automatic
      percent entry: a typed number of 1 or more is a percentage, a smaller one is the fraction itself)
    * amount cells (a nominal, a trade size: declared ``"kind": "amount"`` in the page definition - a number format
      cannot tell them, swap points are ``#,##0`` too) take the desk's shorthand as well: ``100m``, ``2,5 mn``, ``500k``,
      ``2mr`` - and nothing else, so that a size that was not understood cannot quietly empty the totals
    * a date typed as a tenor ("1A", "ay sonu", "IMM", "+5") is the service's to resolve before this (it needs the
      cell's start and calendar: tto/shortcuts.py); here it is not a date
    * list cells (``kind="list"``) take one of their ``options`` (or a word ``aliases`` maps to one: "Sat" is "S") and
      nothing else - a cell whose formulas test for one item would otherwise take any other text for the other
    * tick boxes (``kind="check"``) take 1 or 0 (:func:`parse_check`) and nothing else
    * anything that is not a number stays text
    """
    if raw is None:
        return None
    if kind == "check":
        return parse_check(raw, lang)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        x = float(raw)
        if x != x or x in (float("inf"), float("-inf")):
            raise InputError("geçersiz sayı")
        return x
    s = str(raw).strip()
    if s == "":
        return None
    if len(s) > 2000:
        raise InputError("girdi çok uzun")
    if today is None:
        today = _dt.date.today()                 # (what a user types: a day without its year counts from today)
    if aliases:
        typed = _fold(s)
        for word, item in aliases.items():
            if _fold(word) == typed:
                s = item
                break
    if options:
        typed = _fold(s)
        for o in options:
            if _fold(o) == typed:
                n = parse_number(o, lang)
                return n if n is not None and re.match(r"^[+-]?[\d.,]+$", o) else o
        # a list of days kept as text (VİOP contracts "30.11.2026", matched by the formulas as text): a day typed
        # another way ("30.11.26", "30/11/2026", "30/11") is that item - never a date number the list does not hold
        day = parse_date(s, today, past, after)
        if day is not None:
            for o in options:
                if parse_date(o) == day:
                    return o
        if kind == "list":
            raise InputError("listede yok: %r (%s)" % (s, ", ".join(options)))
    if kind == "amount":
        n = parse_amount(s, lang)
        if n is None:
            n = parse_number(s, lang)
        if n is None:
            raise InputError("tutar anlaşılamadı: %r (örn. 100m, 2,5mn, 500k, 100.000.000)" % s)
        return n
    if date_cell or kind == "date":
        d = parse_date(s, today, past, after)
        if d is not None:
            return d
        n = parse_number(s, lang)
        if n is not None and 20000 < n < 80000:
            return float(int(n))
        raise InputError("tarih anlaşılamadı: %r (örn. 03.11.2026)" % s)
    if kind == "text":
        return s
    explicit_pct = s.endswith("%") or s.startswith("%")
    pct_cell = percent_cell or kind == "pct"
    n = parse_number(s, lang, prefer_decimal=pct_cell)
    if n is None:
        d = parse_date(s) if re.search(r"\d[./-]\d{1,2}[./-]\d{2,4}$", s) else None
        if d is not None:
            return d
        up = s.upper()
        if up in ("TRUE", "DOĞRU"):
            return True
        if up in ("FALSE", "YANLIŞ"):
            return False
        return s
    if pct_cell and not explicit_pct and abs(n) >= 1.0:
        n /= 100.0                      # typed as 35,5 meaning 35,5 %
    return n


def parse_clipboard(text: str) -> List[List[str]]:
    """Tab separated clipboard text (as Excel copies cells) -> matrix of strings."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    rows = [line.split("\t") for line in text.split("\n")]
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]
