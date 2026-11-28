"""Excel number-format rendering (``0.00%``, ``#,##0;\\-#,##0;0``, ``dd\\.mm\\.yyyy`` ...).

Used by the ``TEXT`` / ``FIXED`` worksheet functions and by the dashboard to show every cell the way
the workbook formats it.  The separators and month / day names come from a :class:`Locale`; the desk's
Excel runs with Turkish regional settings, so :data:`TR` is the default.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .errors import XlError
from .values import fmt_general, serial_to_date


class Locale(object):
    def __init__(self, code, dec, grp, months, months_long, days, days_long):
        self.code = code
        self.dec = dec
        self.grp = grp
        self.months = months
        self.months_long = months_long
        self.days = days            # index 0 = Monday
        self.days_long = days_long


TR = Locale(
    "tr", ",", ".",
    ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"],
    ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"],
    ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"],
    ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"],
)
EN = Locale(
    "en", ".", ",",
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"],
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
)
LOCALES = {"tr": TR, "en": EN}

#: locale used by the TEXT / FIXED worksheet functions (the workbook's Excel is Turkish)
ENGINE_LOCALE = TR


def set_engine_locale(code: str) -> None:
    global ENGINE_LOCALE
    ENGINE_LOCALE = LOCALES[code]


def get_locale(code: Optional[str]) -> Locale:
    if code is None:
        return ENGINE_LOCALE
    return LOCALES.get(code, ENGINE_LOCALE)


# --------------------------------------------------------------------------- format parsing
class _Section(object):
    __slots__ = ("tokens", "kind", "int_ph", "frac_ph", "group", "scale", "pct", "exp", "color", "has_at",
                 "explicit_sign")

    def __init__(self):
        self.tokens: List[Tuple[str, Any]] = []
        self.kind = "num"           # num | date | text | general
        self.int_ph = ""
        self.frac_ph = ""
        self.group = False
        self.scale = 0
        self.pct = 0
        self.exp: Optional[Tuple[str, int]] = None
        self.color: Optional[str] = None
        self.has_at = False
        self.explicit_sign = False


_DATE_CHARS = "dmyhsDMYHS"
_CACHE: Dict[str, List[_Section]] = {}


def _split_sections(fmt: str) -> List[str]:
    out, cur = [], []
    i, n = 0, len(fmt)
    while i < n:
        ch = fmt[i]
        if ch == '"':
            j = fmt.find('"', i + 1)
            j = n - 1 if j < 0 else j
            cur.append(fmt[i:j + 1])
            i = j + 1
            continue
        if ch == "\\" and i + 1 < n:
            cur.append(fmt[i:i + 2])
            i += 2
            continue
        if ch == "[":
            j = fmt.find("]", i)
            j = n - 1 if j < 0 else j
            cur.append(fmt[i:j + 1])
            i = j + 1
            continue
        if ch == ";":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _parse_section(text: str) -> _Section:
    sec = _Section()
    toks = sec.tokens
    i, n = 0, len(text)
    if text.strip().lower() == "general":
        sec.kind = "general"
        return sec
    seen_dec = False
    is_date = False
    while i < n:
        ch = text[i]
        if ch == '"':
            j = text.find('"', i + 1)
            j = n if j < 0 else j
            toks.append(("lit", text[i + 1:j]))
            i = j + 1
        elif ch == "\\" and i + 1 < n:
            toks.append(("lit", text[i + 1]))
            if text[i + 1] in "+-":
                sec.explicit_sign = True
            i += 2
        elif ch == "_" and i + 1 < n:
            toks.append(("lit", " "))
            i += 2
        elif ch == "*" and i + 1 < n:
            i += 2
        elif ch == "[":
            j = text.find("]", i)
            j = n - 1 if j < 0 else j
            body = text[i + 1:j]
            low = body.lower()
            if low.startswith("$"):
                cur = body[1:].split("-")[0]
                if cur:
                    toks.append(("lit", cur))
            elif low in ("h", "hh", "m", "mm", "s", "ss"):
                toks.append(("elapsed", low))
                is_date = True
            elif low.startswith("color") or low in ("red", "blue", "green", "black", "white", "yellow", "magenta", "cyan"):
                sec.color = {"color10": "green"}.get(low, low)
            i = j + 1
        elif ch in "0#?":
            j = i
            while j < n and text[j] in "0#?":
                j += 1
            run = text[i:j]
            toks.append(("dig", (run, seen_dec)))
            if seen_dec:
                sec.frac_ph += run
            else:
                sec.int_ph += run
            i = j
        elif ch == ".":
            if not seen_dec and not is_date and _digits_follow_or_precede(text, i):
                seen_dec = True
                toks.append(("dec", None))
            else:
                toks.append(("lit", "."))
            i += 1
        elif ch == ",":
            # between digit placeholders -> grouping ; directly after the last placeholder -> scaling
            j = i
            while j < n and text[j] == ",":
                j += 1
            nxt = text[j] if j < n else ""
            if nxt in "0#?" and nxt != "":
                sec.group = True
            elif toks and toks[-1][0] in ("dig", "dec"):
                sec.scale += j - i
            else:
                toks.append(("lit", ","))
            i = j
        elif ch == "%":
            sec.pct += 1
            toks.append(("lit", "%"))
            i += 1
        elif ch in "eE" and i + 1 < n and text[i + 1] in "+-":
            j = i + 2
            while j < n and text[j] in "0#?":
                j += 1
            sec.exp = (text[i + 1], j - i - 2)
            toks.append(("exp", None))
            i = j
        elif ch == "@":
            sec.has_at = True
            toks.append(("at", None))
            i += 1
        elif ch in _DATE_CHARS:
            j = i
            while j < n and text[j].lower() == ch.lower():
                j += 1
            toks.append(("dt", text[i:j].lower()))
            is_date = True
            i = j
        elif text[i:i + 5].upper() == "AM/PM":
            toks.append(("ampm", None))
            is_date = True
            i += 5
        else:
            if ch in "+-":
                sec.explicit_sign = True
            toks.append(("lit", ch))
            i += 1
    if is_date and not sec.int_ph:
        sec.kind = "date"
    elif sec.has_at and not sec.int_ph:
        sec.kind = "text"
    elif not sec.int_ph and not sec.frac_ph:
        sec.kind = "literal"
    return sec


def _digits_follow_or_precede(text: str, i: int) -> bool:
    before = text[i - 1] if i > 0 else ""
    after = text[i + 1] if i + 1 < len(text) else ""
    return before in "0#?" or after in "0#?"


def _sections(fmt: str) -> List[_Section]:
    secs = _CACHE.get(fmt)
    if secs is None:
        secs = [_parse_section(s) for s in _split_sections(fmt)]
        if len(_CACHE) > 2000:
            _CACHE.clear()
        _CACHE[fmt] = secs
    return secs


# --------------------------------------------------------------------------- rendering
def _round_half_away(x: float, digits: int) -> float:
    m = 10.0 ** digits
    y = float("%.15g" % (abs(x) * m))
    r = math.floor(y + 0.5) / m
    return -r if x < 0 else r


def _group(digits: str, sep: str) -> str:
    if len(digits) <= 3:
        return digits
    head = len(digits) % 3
    parts = [digits[:head]] if head else []
    parts.extend(digits[k:k + 3] for k in range(head, len(digits), 3))
    return sep.join(parts)


def _fmt_number(x: float, sec: _Section, loc: Locale, auto_sign: bool) -> str:
    v = abs(x)
    if sec.pct:
        v *= 100.0 ** sec.pct
    if sec.scale:
        v /= 1000.0 ** sec.scale
    nfrac = len(sec.frac_ph)
    exp_txt = ""
    if sec.exp is not None:
        if v == 0:
            e = 0
        else:
            e = int(math.floor(math.log10(v)))
            v = v / (10.0 ** e)
            if float("%.*f" % (nfrac, v)) >= 10.0:
                v /= 10.0
                e += 1
        exp_txt = "E%s%0*d" % ("-" if e < 0 else ("+" if sec.exp[0] == "+" else ""), sec.exp[1], abs(e))
    v = _round_half_away(v, nfrac)
    s = "%.*f" % (nfrac, v)
    if nfrac:
        ipart, fpart = s.split(".")
    else:
        ipart, fpart = s, ""
    min_int = sec.int_ph.count("0")
    if ipart == "0" and min_int == 0:
        ipart = ""
    elif len(ipart) < min_int:
        ipart = "0" * (min_int - len(ipart)) + ipart
    if sec.group:
        ipart = _group(ipart, loc.grp)
    # optional (#) trailing fraction digits are dropped when zero
    if fpart:
        keep = len(fpart)
        ph = sec.frac_ph
        while keep > 0 and ph[keep - 1] == "#" and fpart[keep - 1] == "0":
            keep -= 1
        fpart = fpart[:keep]
    negative = x < 0 and (float(s) != 0.0)
    out: List[str] = []
    int_done = False
    frac_done = False
    for kind, val in sec.tokens:
        if kind == "lit":
            out.append(val)
        elif kind == "dig":
            run, is_frac = val
            if is_frac:
                if not frac_done:
                    out.append(fpart)
                    frac_done = True
            elif not int_done:
                out.append(ipart)
                int_done = True
        elif kind == "dec":
            if fpart or "0" in sec.frac_ph or sec.frac_ph == "":
                out.append(loc.dec)
        elif kind == "exp":
            out.append(exp_txt)
    text = "".join(out)
    if negative and auto_sign:
        text = "-" + text
    return text


def _fmt_date(x: float, sec: _Section, loc: Locale) -> str:
    if x < 0:
        return "#" * 8
    day = math.floor(x)
    secs = int(round((x - day) * 86400.0))
    if secs >= 86400:
        secs -= 86400
        day += 1
    d = serial_to_date(day)
    hh, rem = divmod(secs, 3600)
    mi, ss = divmod(rem, 60)
    toks = sec.tokens
    has_ampm = any(t[0] == "ampm" for t in toks)
    out: List[str] = []
    for idx, (kind, val) in enumerate(toks):
        if kind == "lit":
            out.append(val)
        elif kind == "ampm":
            out.append("AM" if hh < 12 else "PM")
        elif kind == "elapsed":
            total = int(round(x * 86400.0))
            if val.startswith("h"):
                out.append("%0*d" % (len(val), total // 3600))
            elif val.startswith("m"):
                out.append("%0*d" % (len(val), total // 60))
            else:
                out.append("%0*d" % (len(val), total))
        elif kind == "dt":
            c = val[0]
            ln = len(val)
            if c == "y":
                out.append("%04d" % d.year if ln > 2 else "%02d" % (d.year % 100))
            elif c == "d":
                if ln == 1:
                    out.append(str(d.day))
                elif ln == 2:
                    out.append("%02d" % d.day)
                elif ln == 3:
                    out.append(loc.days[d.weekday()])
                else:
                    out.append(loc.days_long[d.weekday()])
            elif c == "h":
                h = hh
                if has_ampm:
                    h = hh % 12 or 12
                out.append("%02d" % h if ln > 1 else str(h))
            elif c == "s":
                out.append("%02d" % ss if ln > 1 else str(ss))
            elif c == "m":
                # minutes when next to hours / seconds, otherwise month
                prev = next((t for t in reversed(toks[:idx]) if t[0] in ("dt", "elapsed")), None)
                nxt = next((t for t in toks[idx + 1:] if t[0] in ("dt", "elapsed")), None)
                is_min = (prev is not None and prev[1][0] == "h") or (nxt is not None and nxt[1][0] == "s")
                if is_min and ln <= 2:
                    out.append("%02d" % mi if ln > 1 else str(mi))
                elif ln == 1:
                    out.append(str(d.month))
                elif ln == 2:
                    out.append("%02d" % d.month)
                elif ln == 3:
                    out.append(loc.months[d.month - 1])
                elif ln == 4:
                    out.append(loc.months_long[d.month - 1])
                else:
                    out.append(loc.months_long[d.month - 1][0])
    return "".join(out)


def _fmt_text(s: str, sec: _Section) -> str:
    out = []
    for kind, val in sec.tokens:
        if kind == "lit":
            out.append(val)
        elif kind == "at":
            out.append(s)
    return "".join(out)


def general(x: float, loc: Locale, digits: int = 15) -> str:
    """General format; ``digits`` = maximum significant digits (Excel cells show 11, text conversion 15)."""
    if digits < 15 and x != 0 and x == x:
        ax = abs(x)
        mag = int(math.floor(math.log10(ax))) if ax > 0 else 0
        if -5 <= mag < digits:
            x = float("%.*g" % (digits, x))
            s = fmt_general(x)
        else:
            s = ("%.*E" % (max(digits - 6, 2), x)).replace("E+0", "E+").replace("E-0", "E-")
    else:
        s = fmt_general(x)
    if loc.dec != ".":
        s = s.replace(".", loc.dec)
    return s


def render(value: Any, fmt: str, loc: Optional[Locale] = None, general_digits: int = 15,
           excel: bool = False) -> Tuple[str, Optional[str]]:
    """Format ``value`` with the Excel format ``fmt``; returns (text, colour name or None).  ``excel``: Excel's text to the
    letter, a negative shown as "-0" too (the formulas' TEXT); the pages' text never says "-0" (:func:`_rounds_to_zero`)."""
    if loc is None:
        loc = ENGINE_LOCALE
    if value is None:
        return "", None
    t = type(value)
    if t is XlError:
        return value.code, None
    if t is bool:
        return ("TRUE" if value else "FALSE"), None
    secs = _sections(fmt or "General")
    if t is str:
        if len(secs) >= 4:
            return _fmt_text(value, secs[3]), secs[3].color
        if secs[0].kind == "text":
            return _fmt_text(value, secs[0]), secs[0].color
        return value, None
    x = float(value)
    if x != x or x in (float("inf"), float("-inf")):
        return "#NUM!", None
    nsec = len(secs)
    if x < 0 and nsec >= 2 and not excel and _rounds_to_zero(x, secs[1]):
        # a negative its own section shows as zero is a zero (the zero section, or the positive one): never "-0", "-0,0"
        # or a red "(0)" - the desk, 28.11.2026 (a single section already writes no sign then: _fmt_number)
        x = 0.0
    auto_sign = False
    if nsec == 1:
        sec = secs[0]
        auto_sign = True
    elif nsec == 2:
        sec = secs[0] if x >= 0 else secs[1]
    else:
        sec = secs[0] if x > 0 else (secs[1] if x < 0 else secs[2])
        if x < 0 and sec.kind in ("num",) and not sec.explicit_sign and not _has_paren(sec):
            auto_sign = False
    if sec.kind == "general":
        return general(x if (nsec == 1 or x >= 0) else -x, loc, general_digits), sec.color
    if sec.kind == "date":
        return _fmt_date(x, sec, loc), sec.color
    if sec.kind == "text":
        return _fmt_text(general(x, loc, general_digits), sec), sec.color
    if sec.kind == "literal":
        return "".join(v for k, v in sec.tokens if k == "lit"), sec.color
    return _fmt_number(x, sec, loc, auto_sign), sec.color


def _rounds_to_zero(x: float, sec: _Section) -> bool:
    """Whether a number section shows ``x`` as zero: its digits after the percent / thousands scaling, rounded to the
    section's decimals (not a date, a text, General or a scientific section)."""
    if sec.kind != "num" or sec.exp is not None:
        return False
    v = abs(x) * (100.0 ** sec.pct) / (1000.0 ** sec.scale)
    return _round_half_away(v, len(sec.frac_ph)) == 0.0


def _has_paren(sec: _Section) -> bool:
    return any(k == "lit" and "(" in v for k, v in sec.tokens)


def format_value(value: Any, fmt: str, loc: Optional[Locale] = None, excel: bool = False) -> str:
    return render(value, fmt, loc, excel=excel)[0]


def format_fixed(x: float, decimals: int, commas: bool, loc: Optional[Locale] = None) -> str:
    if loc is None:
        loc = ENGINE_LOCALE
    s = "%.*f" % (decimals, abs(x))
    if decimals:
        ipart, fpart = s.split(".")
    else:
        ipart, fpart = s, ""
    if commas:
        ipart = _group(ipart, loc.grp)
    out = ipart + (loc.dec + fpart if fpart else "")
    if x < 0 and float(s) != 0.0:
        out = "-" + out
    return out


def is_date_format(fmt: str) -> bool:
    secs = _sections(fmt or "General")
    return secs[0].kind == "date"


def is_percent_format(fmt: str) -> bool:
    secs = _sections(fmt or "General")
    return secs[0].pct > 0


def is_number_format(fmt: str) -> bool:
    """Whether a number in a cell of this format is shown as a number (General, ``0.00%``, ``#,##0" bp"`` ...) - not as
    a date or a time, not as text (``@``), not as a fixed text (``"-"``)."""
    return _sections(fmt or "General")[0].kind in ("num", "general")


#: the most decimals a user's own number of decimals may ask for (a double holds 15-17 significant digits)
MAX_DECIMALS = 10
_DEC_CACHE: Dict[Tuple[str, int], str] = {}


def with_decimals(fmt: str, n: int) -> str:
    """``fmt`` showing ``n`` decimals - Excel's "Increase / Decrease Decimal": only the decimals change, the rest of the
    format stays as it is: a percent stays a percent, the thousands separators, a scaling comma (``#,##0,,\\M``), the
    negatives' section and its colour or brackets, a prefix or a suffix, an exponent's own digits.  Each number section
    gets exactly ``n`` decimal zeros (``0.0#`` too).  A date, time or text section stays; so does a zero section that
    shows no digit for zero (the accounting format's ``"-"??``: a dash has no decimals).  General becomes ``0.00…``
    (no grouping, as General has none)."""
    n = max(0, min(int(n), MAX_DECIMALS))
    key = (fmt or "General", n)
    hit = _DEC_CACHE.get(key)
    if hit is not None:
        return hit
    parts = _split_sections(key[0])
    out = [_section_with_decimals(part, n, zero=(k == 2)) for k, part in enumerate(parts)]
    res = ";".join(out)
    if len(_DEC_CACHE) > 2000:
        _DEC_CACHE.clear()
    _DEC_CACHE[key] = res
    return res


def _section_with_decimals(text: str, n: int, zero: bool) -> str:
    """One section of a format (as ``_split_sections`` gives it) with ``n`` decimals; anything but a number section as it
    is.  ``zero``: the third section (the one a zero takes)."""
    sec = _parse_section(text)
    if sec.kind == "general":
        return "0" + ("." + "0" * n if n else "")
    if sec.kind != "num" or (zero and "0" not in sec.int_ph + sec.frac_ph):
        return text
    # the section's own pieces, each with its text as written: what is not a digit of the number is kept verbatim
    toks: List[Tuple[str, str]] = []
    i, size = 0, len(text)
    seen_dec = False
    while i < size:
        ch = text[i]
        if ch == '"':
            j = text.find('"', i + 1)
            j = size - 1 if j < 0 else j
            toks.append(("lit", text[i:j + 1]))
            i = j + 1
        elif ch in "\\_*" and i + 1 < size:
            toks.append(("lit", text[i:i + 2]))           # an escaped character, a padding or a fill character
            i += 2
        elif ch == "[":
            j = text.find("]", i)
            j = size - 1 if j < 0 else j
            toks.append(("lit", text[i:j + 1]))           # a colour, a currency [$₺-41F], a condition
            i = j + 1
        elif ch in "eE" and i + 1 < size and text[i + 1] in "+-":
            j = i + 2
            while j < size and text[j] in "0#?":
                j += 1
            toks.append(("lit", text[i:j]))               # the exponent and its own digits
            i = j
        elif ch in "0#?":
            j = i
            while j < size and text[j] in "0#?":
                j += 1
            toks.append(("frac" if seen_dec else "int", text[i:j]))
            i = j
        elif ch == "." and not seen_dec and _digits_follow_or_precede(text, i):
            seen_dec = True
            toks.append(("dec", "."))
            i += 1
        else:
            toks.append(("lit", ch))                      # a grouping / scaling comma, %, a sign, a space ...
            i += 1
    point = "." + "0" * n if n else ""
    at = next((k for k, t in enumerate(toks) if t[0] == "dec"), None)
    if at is None:
        ints = [k for k, t in enumerate(toks) if t[0] == "int"]
        if not ints:
            return text
        at = ints[-1] + 1                                  # right after the integer digits (before a scaling comma)
    else:
        toks = toks[:at] + [t for t in toks[at:] if t[0] not in ("dec", "frac")]      # (the point and its digits go)
    return "".join(t[1] for t in toks[:at]) + point + "".join(t[1] for t in toks[at:])
