"""Kotasyon kopyala: a pricing table's prices as a quote to send a client - in Turkish or English.

A quote holds the pair / instrument, the value date and the maturity with the days, the outright, the swap points, the
TRY and the foreign rate, the amount where the table has one and the side(s) where it knows them - lined up like the RET
dialog's "Kopyala (mesaj)" (a label, two spaces past the longest, then the value; two-sided ``34,25 / 34,45``)::

    USDTRY forward 1M · 03.11.2026 · bid / ask
    Başlangıç     04.11.2026
    Vade tarihi   04.12.2026 (30 gün)
    Spot          49,9970 / 49,9975
    Swap puanı    12.663 / 12.664
    Outright      51,2633 / 51,2639
    TRY faizi %   34,38 / 34,38
    USD faizi %   3,89

A table of several rows gives, without a row, one line a row under a caption line (``Vade  Vade tarihi  Gün  Swap
puanı …``), what is the same for all of them (a cell, not a column: the spot date, the spot) above it.  Each number is
written as the cell's own format shows it, in the quote's language (Turkish 1.234,56; English 1,234.56); a date as
03.11.2026 or 03 Nov 2026.

A table opts in with ``"client_quote"`` in its page definition (how: tto/views/__init__.py); nothing here knows a table.
:func:`quote_text` reads the cells through a ``read(ref) -> (value, number format)`` the caller gives (the service: the
user's own calculation).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .inputs import _fold, parse_date
from .xl import numfmt
from .xl.values import serial_to_date

#: "Sheet!A1" -> (the cell's value, its number format)
Reader = Callable[[str], Tuple[Any, str]]


class QuoteError(ValueError):
    pass


#: the lines of a quote, in this order: (key, Turkish label, English label, how the value is written)
FIELDS = (
    ("side", "Yön", "Side", "side"),
    ("start", "Başlangıç", "Value date", "date"),
    ("end", "Vade tarihi", "Maturity", "date"),
    ("days", "Gün", "Days", "days"),
    ("spot", "Spot", "Spot", "num"),
    ("near", "Başlangıç kuru", "Near outright", "num"),
    ("points", "Swap puanı", "Swap points", "num"),
    ("outright", "Outright", "Outright", "num"),
    ("try", "TRY faizi %", "TRY rate %", "rate"),
    ("ccy", "{ccy} faizi %", "{ccy} rate %", "rate"),
    ("on", "O/N karşılığı %", "O/N equivalent %", "rate"),
    ("amount", "Tutar", "Amount", "amount"),
)
KEYS = tuple(k for k, _, _, _ in FIELDS)
#: everything a spec may say: the fields, the instrument, the rows of a table of quotes and the quotes side by side
SPEC_KEYS = frozenset(KEYS) | {"pair", "title", "title_en", "name", "rows", "label", "alt", "alt_when", "head", "head_en",
                               "parts"}
FIELD_KEYS = frozenset({"src", "label", "label_en"})
NUMERIC = ("num", "rate", "amount")

_COL = re.compile(r"^[A-Z]{1,3}$")
_CELL = re.compile(r"^(?:(.+)!)?\$?([A-Z]{1,3})\$?(\d+)$")
_ROWS = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
_BUY = {_fold(w) for w in ("B", "Al", "Alış", "Buy")}
_SELL = {_fold(w) for w in ("S", "Sat", "Satış", "Sell")}


# ---------------------------------------------------------------------------------------------- sources
def is_column(src: Any) -> bool:
    """A source that names a column ("B": that column of the quoted row) rather than a cell ("G2", "Forward!I2")."""
    return isinstance(src, str) and bool(_COL.match(src.strip()))


def ref_of(src: Any, sheet: str, row: Optional[int]) -> Optional[str]:
    """The cell a source names: a cell of the table's sheet ("G2"), of another sheet ("Forward!I2"), or the column of
    the quoted row ("B" - ``None`` without a row)."""
    s = str(src or "").strip()
    if _COL.match(s):
        return None if row is None else "%s!%s%d" % (sheet, s, row)
    m = _CELL.match(s)
    if not m:
        raise QuoteError("kaynak anlaşılamadı: %r" % (src,))
    return "%s!%s%s" % (m.group(1) or sheet, m.group(2), m.group(3))


def field(spec: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """A field of a spec as ``{"src": source or [bid, ask], "label"?, "label_en"?}`` (``None``: the table has none)."""
    v = spec.get(key)
    if v is None or v == "" or v == []:
        return None
    return dict(v) if isinstance(v, dict) else {"src": v}


def _sources(f: Dict[str, Any]) -> List[Any]:
    return list(f["src"]) if isinstance(f["src"], list) else [f["src"]]


def _per_row(f: Dict[str, Any]) -> bool:
    return any(is_column(s) for s in _sources(f))


def table_rows(spec: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """The sheet rows of a table of quotes (``"rows": "5:14"``) - ``None`` for a table that is one quote."""
    if not spec.get("rows"):
        return None
    m = _ROWS.match(str(spec["rows"]))
    if not m or int(m.group(1)) > int(m.group(2)):
        raise QuoteError("satırlar anlaşılamadı: %r (örn. \"5:14\")" % (spec["rows"],))
    return int(m.group(1)), int(m.group(2))


def parts(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The quotes of a table side by side (``"parts"``: USDTRY | EURTRY), each with what the table says for all of
    them; a table that is one quote is its own one part."""
    if not spec.get("parts"):
        return [spec]
    common = {k: v for k, v in spec.items() if k != "parts"}
    return [dict(common, **p) for p in spec["parts"]]


def part_name(spec: Dict[str, Any], k: int) -> str:
    """What a part is called in the menu: its ``name``, else its pair."""
    p = parts(spec)[k]
    pair = p.get("pair")
    return str(p.get("name") or (pair if isinstance(pair, str) else "") or "#%d" % (k + 1))


def sources(spec: Dict[str, Any], sheet: str) -> List[str]:
    """Every cell a spec reads (a column at the first row of its table) - for checking that they exist."""
    out: List[str] = []
    first = (table_rows(spec) or (None, None))[0]
    for p in parts(spec):
        rows = table_rows(p)
        row = rows[0] if rows else first
        for key in KEYS:
            f = field(p, key)
            for s in _sources(f) if f else []:
                ref = ref_of(s, sheet, row)
                if ref:
                    out.append(ref)
        for key in ("label", "alt"):
            if p.get(key):
                out.append(ref_of(p[key], sheet, row) or "")
        pair = p.get("pair")
        if isinstance(pair, dict):
            out.append(ref_of(pair.get("src"), sheet, row) or "")
    return [r for r in out if r]


# ---------------------------------------------------------------------------------------------- values
def _loc(lang: str) -> numfmt.Locale:
    return numfmt.LOCALES["en" if lang == "en" else "tr"]


def day_text(d: _dt.date, lang: str) -> str:
    """A date as the quote writes it: 03.11.2026 (Turkish), 03 Nov 2026 (English)."""
    if lang == "en":
        return "%02d %s %d" % (d.day, numfmt.EN.months[d.month - 1], d.year)
    return d.strftime("%d.%m.%Y")


def _decimals(fmt: str) -> int:
    m = re.search(r"\.(0+)", (fmt or "").split(";")[0])
    return len(m.group(1)) if m else 0


def number_text(v: Any, fmt: str, lang: str) -> str:
    """A number as its cell's format shows it, in the quote's language - the digits, the separators and the sign only (no
    currency sign, no %: a rate is written in per cent either way, the label says so)."""
    if type(v) is not float or v != v:
        return ""
    loc = _loc(lang)
    if not fmt or fmt == "General" or numfmt.is_date_format(fmt):
        text = numfmt.general(v, loc, 10)
    else:
        text = numfmt.render(v, fmt, loc)[0]
    s = re.sub(r"[^0-9.,()+\-]", "", text.replace("−", "-"))
    if not re.search(r"\d", s):                    # ("-" for a zero, as an accounting format writes it)
        s = numfmt.format_fixed(v, _decimals(fmt), True, loc)
    return s


def date_value_text(v: Any, lang: str) -> str:
    """A date cell (a serial, or a day kept as text: VİOP's "31.12.2026"); other text ("Spot") as it is."""
    if type(v) is float and 20000 < v < 80000:
        return day_text(serial_to_date(v), lang)
    if isinstance(v, str):
        s = v.strip()
        x = parse_date(s) if s else None
        return day_text(serial_to_date(x), lang) if x is not None else s
    return ""


def _side_text(v: Any, lang: str, base: Optional[str]) -> str:
    if not isinstance(v, str) or not v.strip():
        return ""
    t = _fold(v.strip())
    if t in _BUY:
        return ("Buy " + base if lang == "en" else base + " alış") if base else ("Buy" if lang == "en" else "Alış")
    if t in _SELL:
        return ("Sell " + base if lang == "en" else base + " satış") if base else ("Sell" if lang == "en" else "Satış")
    return v.strip()


def _value_text(kind: str, v: Any, fmt: str, lang: str, base: Optional[str]) -> str:
    if kind == "date":
        return date_value_text(v, lang)
    if kind == "days":
        return "%d" % round(v) if type(v) is float and v == v else ""
    if kind == "side":
        return _side_text(v, lang, base)
    if kind == "amount":
        if type(v) is not float or v != v:
            return ""
        s = numfmt.format_fixed(v, 0 if v == int(v) else 2, True, _loc(lang))
        return s + (" " + base if base else "")
    return number_text(v, fmt, lang)


def _base(pair: str) -> Optional[str]:
    """The currency a pair is quoted in units of (USDTRY: USD) - the foreign rate's and the amount's."""
    words = [w for w in re.split(r"[^A-Za-z]+", pair or "") if len(w) == 6]
    return words[-1][:3].upper() if words else None


class _Quote(object):
    """One quote (a table's, a row's or a part's) as it is read."""

    def __init__(self, spec: Dict[str, Any], read: Reader, sheet: str, lang: str):
        self.spec, self.read, self.sheet, self.lang = spec, read, sheet, lang

    def cell(self, src: Any, row: Optional[int]) -> Tuple[Any, str]:
        ref = ref_of(src, self.sheet, row)
        if ref is None:
            return None, "General"
        return self.read(ref)

    def pair(self, row: Optional[int]) -> str:
        p = self.spec.get("pair")
        if isinstance(p, dict):
            if row is None and is_column(p.get("src")):
                return ""
            v, _ = self.cell(p.get("src"), row)
            return v.strip().upper() if isinstance(v, str) else ""
        return str(p or "")

    def texts(self, f: Dict[str, Any], kind: str, row: Optional[int], base: Optional[str]) -> List[str]:
        out = []
        for s in _sources(f):
            v, fmt = self.cell(s, row)
            out.append(_value_text(kind, v, fmt, self.lang, base))
        return out

    def label(self, f: Dict[str, Any], tr: str, en: str, base: Optional[str]) -> str:
        if self.lang == "en":
            text = f.get("label_en") or (en if not f.get("label") else f["label"])
        else:
            text = f.get("label") or tr
        return text.replace("{ccy}", base or ("Foreign" if self.lang == "en" else "Döviz"))

    def row_label(self, row: Optional[int]) -> str:
        src = self.spec.get("label")
        if not src or row is None:
            return ""
        text = self._cell_text(src, row)
        alt, when = self.spec.get("alt"), self.spec.get("alt_when")
        if alt and (not text or (when and _fold(text) == _fold(str(when)))):
            text = self._cell_text(alt, row) or text
        return text

    def _cell_text(self, src: Any, row: Optional[int]) -> str:
        v, fmt = self.cell(src, row)
        if type(v) is float:
            return date_value_text(v, self.lang) if numfmt.is_date_format(fmt) else number_text(v, fmt, self.lang)
        return v.strip() if isinstance(v, str) else ""

    def heading(self, pair: str, label: str, today: _dt.date, two: bool) -> str:
        title = self.spec.get("title_en") if self.lang == "en" and self.spec.get("title_en") else self.spec.get("title", "")
        name = " ".join(x for x in (pair, title, label) if x)
        return " · ".join(x for x in (name, day_text(today, self.lang), "bid / ask" if two else "") if x)


def _two(texts: List[str]) -> str:
    return " / ".join(t or "–" for t in texts) if len(texts) == 2 else texts[0]


def _lined(pairs: Sequence[Tuple[str, str]]) -> List[str]:
    """Label · value lines, the values lined up two spaces past the longest label (the RET message's layout)."""
    w = max((len(label) for label, _ in pairs), default=0)
    return [(label.ljust(w + 2) + value).rstrip() for label, value in pairs]


def _one(spec: Dict[str, Any], read: Reader, sheet: str, lang: str, today: _dt.date, row: Optional[int]) -> str:
    """One quote: the heading, then a line a field."""
    q = _Quote(spec, read, sheet, lang)
    pair = q.pair(row)
    base = _base(pair)
    end = field(spec, "end")
    days = q.texts(field(spec, "days"), "days", row, base)[0] if field(spec, "days") else ""
    lines: List[Tuple[str, str]] = []
    two = numbers = False
    for key, tr, en, kind in FIELDS:
        f = field(spec, key)
        if not f or (key == "days" and end):
            continue
        texts = q.texts(f, kind, row, base)
        if not any(texts):
            continue
        two = two or len(texts) == 2
        # (a row of a table of quotes has a price of its own, not only what all rows share)
        numbers = numbers or (kind in NUMERIC and (row is None or _per_row(f)))
        text = _two(texts)
        if key == "end" and days:
            text += " (%s %s)" % (days, "days" if lang == "en" else "gün")
        lines.append((q.label(f, tr, en, base), text))
    if not numbers:
        raise QuoteError("kotasyon verecek fiyat yok: tablonun girdilerini doldurun" if row is None
                         else "bu satırda kotasyon verecek fiyat yok (satır %d)" % row)
    return "\n".join([q.heading(pair, q.row_label(row), today, two)] + _lined(lines))


def _table(spec: Dict[str, Any], read: Reader, sheet: str, lang: str, today: _dt.date) -> str:
    """A table of quotes: the heading, what is the same for all rows (a cell) as lines, then a caption line and a line
    for every row that has a price (an empty "serbest" row, a Target row not filled in, stays out)."""
    q = _Quote(spec, read, sheet, lang)
    r1, r2 = table_rows(spec)
    pair_spec = spec.get("pair")
    pair_per_row = isinstance(pair_spec, dict) and is_column(pair_spec.get("src"))
    pair = q.pair(None)
    base = _base(pair)
    top: List[Tuple[str, str, str, str, Dict[str, Any]]] = []
    cols: List[Tuple[str, str, str, str, Dict[str, Any]]] = []
    for key, tr, en, kind in FIELDS:
        f = field(spec, key)
        if f:
            (cols if _per_row(f) else top).append((key, tr, en, kind, f))
    two = False
    head_lines: List[Tuple[str, str]] = []
    top_end = any(k == "end" for k, _, _, _, _ in top)
    top_days = next((q.texts(f, "days", None, base)[0] for k, _, _, _, f in top if k == "days"), "")
    for key, tr, en, kind, f in top:
        if key == "days" and top_end:
            continue
        texts = q.texts(f, kind, None, base)
        if not any(texts):
            continue
        two = two or len(texts) == 2
        text = _two(texts)
        if key == "end" and top_days:
            text += " (%s %s)" % (top_days, "days" if lang == "en" else "gün")
        head_lines.append((q.label(f, tr, en, base), text))
    # the columns: the row's name, its pair (when each row says its own), then the fields of the row
    en_ = lang == "en"
    columns: List[Tuple[str, str]] = []               # (caption, how it is lined up: "text" / "num" / "two")
    if spec.get("label"):
        columns.append((spec.get("head_en") if en_ and spec.get("head_en") else spec.get("head", ""), "text"))
    if pair_per_row:
        columns.append(("Pair" if en_ else "Parite", "text"))
    for key, tr, en, kind, f in cols:
        n = len(_sources(f))
        two = two or n == 2
        columns.append((q.label(f, tr, en, None if pair_per_row else base),
                        "two" if n == 2 else ("text" if kind in ("date", "side") else "num")))
    lines: List[List[Any]] = []
    for r in range(r1, r2 + 1):
        line: List[Any] = []
        if spec.get("label"):
            line.append(q.row_label(r))
        row_pair = q.pair(r) if pair_per_row else pair
        if pair_per_row:
            line.append(row_pair)
        priced = False
        for key, tr, en, kind, f in cols:
            texts = q.texts(f, kind, r, _base(row_pair))
            priced = priced or (kind in NUMERIC and any(texts))
            line.append(texts if len(texts) == 2 else texts[0])
        if priced:
            lines.append(line)
    if not lines:
        raise QuoteError("tabloda kotasyon verilecek dolu satır yok")
    # a two-sided column lines its bids up on the right and its asks on the left of the " / "; numbers (and their
    # captions) stand on the right of their column, text on the left
    cells: List[List[str]] = [[c for c, _ in columns]] + [[""] * len(columns) for _ in lines]
    for j, (caption, how) in enumerate(columns):
        if how == "two":
            bw = max(len(line[j][0] or "–") for line in lines)
            aw = max(len(line[j][1] or "–") for line in lines)
            for i, line in enumerate(lines):
                b, a = line[j]
                cells[i + 1][j] = (b or "–").rjust(bw) + " / " + (a or "–").ljust(aw) if (b or a) else ""
        else:
            for i, line in enumerate(lines):
                cells[i + 1][j] = line[j]
    widths = [max(len(row[j]) for row in cells) for j in range(len(columns))]
    table = ["  ".join(row[j].ljust(widths[j]) if columns[j][1] == "text" else row[j].rjust(widths[j])
                       for j in range(len(columns))).rstrip() for row in cells]
    out = [q.heading(pair, "", today, two)] + _lined(head_lines)
    return "\n".join(out + [""] + table)


def quote_text(spec: Dict[str, Any], read: Reader, sheet: str, lang: str, today: _dt.date,
               row: Optional[int] = None, part: Optional[int] = None) -> str:
    """The quote text of a table (``spec``: its ``client_quote``; ``sheet``: the sheet its sources without one are on).

    ``row``: one row of a table of quotes - all of its rows that have a price without it; ``part``: one of the quotes
    side by side - all of them, a blank line between, without it (a part without a price is left out).  ``lang`` "en"
    writes it in English, anything else in Turkish.  Raises :class:`QuoteError` when there is nothing to quote."""
    lang = "en" if lang == "en" else "tr"
    if spec.get("parts"):
        every = parts(spec)
        if part is not None:
            if not 0 <= part < len(every):
                raise QuoteError("böyle bir kotasyon yok: %r" % (part,))
            return _one(every[part], read, sheet, lang, today, None)
        texts = []
        for p in every:
            try:
                texts.append(_one(p, read, sheet, lang, today, None))
            except QuoteError:
                continue
        if not texts:
            raise QuoteError("kotasyon verecek fiyat yok: tablonun girdilerini doldurun")
        return "\n\n".join(texts)
    rows = table_rows(spec)
    if rows is None:
        return _one(spec, read, sheet, lang, today, None)
    if row is None:
        return _table(spec, read, sheet, lang, today)
    if not rows[0] <= row <= rows[1]:
        raise QuoteError("satır %d kotasyon satırlarından değil (%d–%d)" % (row, rows[0], rows[1]))
    return _one(spec, read, sheet, lang, today, row)
