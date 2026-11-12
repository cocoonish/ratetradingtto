"""Parsing of what users type or paste into input cells."""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, List, Optional

from .xl.values import date_to_serial

_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DMY = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$")
_YMD = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_TR_MONTHS = {"oca": 1, "şub": 2, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7, "ağu": 8, "agu": 8,
              "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
              "jan": 1, "feb": 2, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


class InputError(ValueError):
    pass


def parse_number(text: str) -> Optional[float]:
    """Number as a person writes it: ``35,55`` ``35.55`` ``1.234,56`` ``1,234.56`` ``%35`` ``35%`` ``(12,5)``.

    Returns ``None`` when the text is not a number.  A trailing / leading ``%`` divides by 100.
    """
    s = text.strip().replace(" ", "").replace(" ", "")
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
    if s.startswith("−") or s.startswith("–"):
        s = "-" + s[1:]
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):          # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                                    # 1,234.56
            s = s.replace(",", "")
    elif has_comma:
        if s.count(",") > 1 and re.match(r"^[+-]?\d{1,3}(,\d{3})+$", s):
            s = s.replace(",", "")               # 1,234,567
        else:
            s = s.replace(",", ".")              # 35,55
            if s.count(".") > 1:
                return None
    elif has_dot and s.count(".") > 1:
        if re.match(r"^[+-]?\d{1,3}(\.\d{3})+$", s):
            s = s.replace(".", "")               # 1.234.567
        else:
            return None
    if not _NUM.match(s):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    if neg:
        x = -x
    if pct:
        x /= 100.0
    return x


def parse_date(text: str) -> Optional[float]:
    """Date text -> Excel serial (``3.11.2026``, ``03/11/26``, ``2026-11-03``, ``3 Kas 2026``)."""
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
    except (ValueError, OverflowError):
        return None
    return None


def parse_input(raw: Any, percent_cell: bool = False, date_cell: bool = False, kind: str = "auto",
                options: Optional[List[str]] = None) -> Any:
    """Convert user text to the value stored in the cell.

    * empty text -> ``None`` (blank cell)
    * date cells accept dates (or serial numbers)
    * percent cells store a fraction: ``35,5`` / ``35,5%`` / ``0,355`` all give 0.355
    * anything that is not a number stays text
    """
    if raw is None:
        return None
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
    if options:
        for o in options:
            if o.casefold() == s.casefold():
                n = parse_number(o)
                return n if n is not None and re.match(r"^[+-]?[\d.,]+$", o) else o
    if date_cell or kind == "date":
        d = parse_date(s)
        if d is not None:
            return d
        n = parse_number(s)
        if n is not None and 20000 < n < 80000:
            return float(int(n))
        raise InputError("tarih anlaşılamadı: %r (örn. 03.11.2026)" % s)
    if kind == "text":
        return s
    explicit_pct = s.endswith("%") or s.startswith("%")
    n = parse_number(s)
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
    if (percent_cell or kind == "pct") and not explicit_pct and abs(n) >= 1.5:
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
