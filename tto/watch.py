"""Watching the market: each user's watch list, alarms, what fired today and the desk's notes of the day.

What is watched is a *subject*, as the desk names it, not a cell that may move:

* ``{"kind": "ois", "tenor": "2Y"}`` - a TRY OIS par rate (and TLREF, 1W, 2W);
* ``{"kind": "off", "tenor": "1M", "side": "mid"}`` - the offshore (FX swap implied) TRY rate of the Forward sheet;
* ``{"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"}`` - a VİOP USDTRY contract: OIS − VİOP (bp), the
  implied TRY rate, the O/N repo, the OIS of its dates, the price; followed by its ticker when the contracts roll;
* ``{"kind": "bond", "isin": "TRT150328T24", "metric": "asw"}`` - a bond: what DİBS RV makes of it (yield, ASW,
  cheap / rich, Z-spread, prices, ASW against FX swaps, carry), its value dates (DİBS Trading) - found by its ISIN
  wherever it stands in the list;
* ``{"kind": "masa", "key": "usdtry_mid"}`` - the desk strip (USDTRY, TLREF, the implied 1Y-end TLREF ...);
* ``{"kind": "cell", "book": "tto", "ref": "Forward!F2"}`` - any cell (right click on it; a cell of a table that
  names a bond, a VİOP contract or an OIS tenor is taken as that subject);
* ``{"kind": "expr", "text": "[OIS 2Y] - [OIS 1Y]"}`` - anything built of them: names in brackets, cell
  references, numbers, + − × ÷ and brackets.  A spread of rates is told in bp.

Every subject has a *display value* - as the desk reads it: a rate in per cent (35,55), a spread in bp, a price,
a level - and an alarm's level is typed that way.  Kept in the store's key / value table: the watch lists
(``watch.items``: user -> items), the alarms (``watch.alarms``), what fired (``watch.fired:<day>``), the opens of
the day (``watch.open:<day>``) and the notes (``desk.notes:<day>``).  The path of a day is held in memory.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import re
import threading
import time
import unicodedata
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from .xl import numfmt
from .xl.model import COLS, parse_a1

#: how a value is shown and what a change of it is: (unit after a change, × to get the change in that unit)
SHOWS = {"pct": ("bp", 100.0), "bp": ("bp", 1.0), "px": ("puan", 1.0), "fx": ("", 1.0), "raw": ("", 1.0)}
OPS = {">=": "≥", "<=": "≤", "x": "kesişir"}
MAX_ITEMS = 80          # per user
MAX_ALARMS = 300        # for the desk
MAX_PATH = 1500         # points of a day's path (thinned beyond)
#: alarms on a move: from the day's open, from the level when the alarm was set, from the watch list's reference,
#: within the last minutes - up, down, either way; and on where a level stands against its own past (z-score)
MODES = {"level": "seviye", "open": "açılıştan", "set": "kurulduğundan", "ref": "referanstan", "window": "son dakikalarda",
         "z": "z-skoru"}
DIRS = {"up": "↑", "down": "↓", "any": "±"}
Z_DAYS = (20, 60, 250)  # closes a z-score looks back on: a month, a quarter, a year
RECENT = 65 * 60        # seconds of readings kept for "within the last minutes" (an hour at most, and a margin)
RECORD_EVERY = 300.0    # seconds between two writes of the day's last values (the watch's own closes)
HEAT_EVERY = 10.0       # seconds between two readings of the heat map's points
HOLIDAYS = (361, 523)   # the desk's holidays: Motor!A361:A523 (the days the Forward sheet's value dates skip)
TR_MONTHS = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")

RV = "DİBS RV"
OIS_ROWS = {"1M": 9, "2M": 10, "3M": 11, "6M": 12, "9M": 13, "1Y": 14, "15M": 15, "18M": 16, "21M": 17, "2Y": 18,
            "3Y": 19, "4Y": 20, "5Y": 21, "6Y": 22, "7Y": 23, "8Y": 24, "9Y": 25, "10Y": 26}
OIS_EXTRA = {"TLREF": "OIS_MAIN!J2", "1W": "OIS_MAIN!AU13", "2W": "OIS_MAIN!AU14"}
OFF_ROWS = {"O/N": 6, "T/N": 7, "1W": 8, "2W": 9, "1M": 10, "2M": 11, "3M": 12, "4M": 13, "5M": 14, "6M": 15, "9M": 16,
            "12M": 17, "2Y": 18}
OFF_SIDES = {"bid": "I", "mid": "J", "ask": "K"}
#: a VİOP contract: its ticker in row 1 (L..W), its numbers one column to the right (M..X)
VIOP_TICKERS = "LMNOPQRSTUVW"
VIOP_METRICS = {"ois": ("OIS − VİOP", 18, "bp", 10000.0), "try_bid": ("ima TRY bid", 13, "pct", 100.0),
                "try_ask": ("ima TRY ask", 25, "pct", 100.0), "try_mid": ("ima TRY orta", (13, 25), "pct", 100.0),
                "repo_bid": ("O/N repo bid", 17, "pct", 100.0), "repo_ask": ("O/N repo ask", 29, "pct", 100.0),
                "ois_rate": ("OIS (vade)", 77, "pct", 100.0), "bid": ("fiyat bid", 16, "fx", 1.0),
                "ask": ("fiyat ask", 28, "fx", 1.0), "mid": ("fiyat orta", (16, 28), "fx", 1.0)}
#: a bond: (caption, sheet, column, shown as, ×) - DİBS RV's columns, DİBS Trading's value dates
BOND_METRICS = {"yield": ("getiri", RV, "T", "pct", 100.0), "asw": ("ASW", RV, "Z", "bp", 1.0),
                "asw_fit": ("ASW eğrisi", RV, "AA", "bp", 1.0), "rv": ("pahalı/ucuz", RV, "AB", "bp", 1.0),
                "zspread": ("Z-spread", RV, "AF", "bp", 1.0), "yield_ois": ("getiri − OIS", RV, "Y", "bp", 1.0),
                "price": ("temiz fiyat", RV, "O", "px", 1.0), "bid": ("BBG bid", RV, "K", "px", 1.0),
                "ask": ("BBG ask", RV, "L", "px", 1.0), "last": ("son işlem", RV, "AS", "px", 1.0),
                "asw_fx": ("ASW FX", RV, "BF", "bp", 1.0), "rv_fx": ("pahalı/ucuz FX", RV, "BH", "bp", 1.0),
                "carry": ("C+R", RV, "AO", "bp", 1.0),
                "t0_bid": ("T0 bid", "EK_DIBS", "F", "px", 1.0), "t0_ask": ("T0 ask", "EK_DIBS", "G", "px", 1.0),
                "t1_bid": ("T1 bid", "EK_DIBS", "K", "px", 1.0), "t1_ask": ("T1 ask", "EK_DIBS", "L", "px", 1.0),
                "t2_bid": ("T2 bid", "EK_DIBS", "P", "px", 1.0), "t2_ask": ("T2 ask", "EK_DIBS", "Q", "px", 1.0),
                "repo01": ("T0→T1 repo", "EK_DIBS", "W", "pct", 1.0), "repo01_tlref": ("repo − TLREF", "EK_DIBS", "Y", "bp", 1.0)}
#: the desk strip
MASA = {"usdtry_bid": ("USDTRY bid", "MASA!F2", "fx", 1.0), "usdtry_ask": ("USDTRY ask", "MASA!G2", "fx", 1.0),
        "usdtry_mid": ("USDTRY mid", "MASA!H2", "fx", 1.0), "tlref": ("TLREF", "MASA!J2", "pct", 100.0),
        "imp_1y": ("İma 1Y sonu TLREF", "MASA!L2", "pct", 100.0), "imp_12m": ("İma 12A (bp)", "MASA!M2", "bp", 1.0),
        "imp_mpc": ("İma / PPK (bp)", "MASA!N2", "bp", 1.0)}

#: ready-made groups the watch list takes in one click
PRESETS: List[Tuple[str, List[Dict[str, Any]]]] = [
    ("Masa", [{"kind": "masa", "key": k} for k in ("usdtry_mid", "tlref", "imp_1y", "imp_12m", "imp_mpc")]),
    ("TRY OIS eğrisi", [{"kind": "ois", "tenor": t} for t in ("1M", "3M", "6M", "1Y", "18M", "2Y", "3Y", "5Y", "10Y")]),
    ("Offshore (FX swap ima)", [{"kind": "off", "tenor": t, "side": "mid"} for t in ("1W", "1M", "3M", "6M", "12M")]),
    ("VİOP · OIS − VİOP (ilk 4 kontrat)", [{"kind": "viop", "position": k, "metric": "ois"} for k in (1, 2, 3, 4)]),
]


def _now() -> _dt.datetime:
    return _dt.datetime.now()


def fold(text: str) -> str:
    """A name as it is compared: no case, no Turkish dots and cedillas, single spaces."""
    t = str(text or "").replace("ı", "i").replace("İ", "I")
    for dash in ("−", "–", "—"):
        t = t.replace(dash, "-")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def value_text(v: Optional[float], show: str, loc=None) -> str:
    if type(v) is not float:
        return ""
    loc = loc or numfmt.get_locale("tr")
    fmt = {"pct": "0.00", "bp": "0.0", "px": "0.000", "fx": "0.0000"}.get(show, "0.0000")
    t = numfmt.format_value(v, fmt, loc)
    return t + ("%" if show == "pct" else (" bp" if show == "bp" else ""))


def date_text(v: Any) -> str:
    """A contract's last trading day as Bloomberg gives it: a text, or a date serial."""
    if type(v) is float and v > 20000:
        return numfmt.format_value(v, "dd.mm.yyyy", numfmt.get_locale("tr"))
    return v.strip() if isinstance(v, str) else ""


def month_label(day: str) -> str:
    """A contract by the month it ends in, as the desk says it: "Kas26" for 30.11.2026 ("" for no date)."""
    m = re.match(r"^\s*\d{1,2}\.(\d{1,2})\.(\d{4})\s*$", day or "")
    if not m or not 1 <= int(m.group(1)) <= 12:
        return ""
    return TR_MONTHS[int(m.group(1)) - 1] + m.group(2)[2:]


def move_text(v: Optional[float], show: str, loc=None) -> str:
    """A change as the desk tells it: +16,0 bp (a rate, a spread), −0,250 (a price), +0,0150 (FX)."""
    if type(v) is not float:
        return ""
    loc = loc or numfmt.get_locale("tr")
    bp = SHOWS.get(show, SHOWS["raw"])[0] == "bp"
    t = numfmt.format_value(abs(v), "0.0" if bp else ("0.000" if show == "px" else "0.0000"), loc)
    return ("+" if v > 0 else ("−" if v < 0 else "")) + t + (" bp" if bp else "")


def z_text(z: Optional[float], loc=None) -> str:
    if type(z) is not float:
        return ""
    return ("−" if z < 0 else "") + numfmt.format_value(abs(z), "0.00", loc or numfmt.get_locale("tr"))


def short_text(v: Optional[float], show: str, loc=None) -> str:
    """A level without its unit (a cell of the heat map)."""
    if type(v) is not float:
        return ""
    fmt = {"pct": "0.00", "bp": "0.0", "px": "0.000", "fx": "0.0000"}.get(show, "0.0000")
    return numfmt.format_value(v, fmt, loc or numfmt.get_locale("tr"))


def min_closes(days: int) -> int:
    """Closes a z-score needs at least: 15 of a month, 20 of anything longer."""
    return 15 if days <= 20 else 20


class ExprError(ValueError):
    pass


_TOKEN = re.compile(r"\s*(?:(\[[^\]]+\])|('(?:[^']|'')+'![A-Za-z]{1,3}\$?\d+|[A-Za-z_][\w.]*![A-Za-z]{1,3}\$?\d+)|"
                    r"(\d+(?:[.,]\d+)?)|([-+*/()×÷]))")


def parse_expr(text: str) -> Any:
    """``[OIS 2Y] - [OIS 1Y]``, ``('DİBS RV'!Z8 + [TRT160431T35 ASW]) / 2`` -> a tree of ``("num", v)``, ``("name", t)``,
    ``("ref", t)``, ``("neg", x)`` and ``(op, a, b)``."""
    s = str(text or "").strip()
    toks: List[Tuple[str, str]] = []
    k = 0
    while k < len(s):
        m = _TOKEN.match(s, k)
        if not m or m.end() == k:
            raise ExprError("anlaşılmadı: %s" % s[k:k + 20])
        name, ref, num, op = m.groups()
        toks.append(("name", name[1:-1].strip()) if name else ("ref", ref) if ref else ("num", num.replace(",", ".")) if num
                    else ("op", {"×": "*", "÷": "/"}.get(op, op)))
        k = m.end()
    if not toks:
        raise ExprError("boş ifade")
    pos = [0]

    def peek() -> Optional[Tuple[str, str]]:
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take() -> Tuple[str, str]:
        t = peek()
        if t is None:
            raise ExprError("ifade yarım kaldı")
        pos[0] += 1
        return t

    def atom() -> Any:
        t = take()
        if t == ("op", "-"):
            return ("neg", atom())
        if t == ("op", "+"):
            return atom()
        if t == ("op", "("):
            x = expr()
            if take() != ("op", ")"):
                raise ExprError("parantez kapanmadı")
            return x
        if t[0] == "num":
            return ("num", float(t[1]))
        if t[0] in ("name", "ref"):
            return t
        raise ExprError("beklenmeyen: %s" % t[1])

    def term() -> Any:
        x = atom()
        while peek() in (("op", "*"), ("op", "/")):
            x = (take()[1], x, atom())
        return x

    def expr() -> Any:
        x = term()
        while peek() in (("op", "+"), ("op", "-")):
            x = (take()[1], x, term())
        return x

    tree = expr()
    if peek() is not None:
        raise ExprError("fazladan: %s" % peek()[1])
    return tree


class Watch(object):
    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self.day = ""
        # (user, key of the subject) -> {"open", "high", "low", "last", "moved", "path": [(time, value)],
        # "recent": [(epoch seconds, value)] of the last hour}; user "" is the market (the heat map)
        self.days: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._defs: Optional[Tuple[Any, Dict[Tuple[str, str], Any]]] = None
        self._hist: Dict[Tuple[str, str, int], Tuple[Dict[str, float], str]] = {}
        self._recorded_at = 0.0
        self._heat_at = 0.0
        # the day the heat map was first opened: its points are read (and kept) from then on only - every point
        # of it is a live Bloomberg request, not to be made all day for a page no one looks at
        self._heat_day = ""
        self._shut: Tuple[str, frozenset] = ("", frozenset())      # (day read, the desk's holidays as ISO days)

    # ================================================================== the market's days
    def holidays(self) -> frozenset:
        """The desk's holidays (the workbook's Motor!A361:A523, as ISO days), read once a day."""
        today = self.svc.today_iso()
        if self._shut[0] != today:
            days = set()
            try:
                rd = self._Reader(self, None)
                for r in range(HOLIDAYS[0], HOLIDAYS[1] + 1):
                    v = rd.get("Motor!A%d" % r)
                    if type(v) is float and v > 20000:
                        days.add((_dt.date(1899, 12, 30) + _dt.timedelta(days=int(v))).isoformat())
            except (KeyError, ValueError):
                pass                                       # no calendar in the book: Saturdays and Sundays only
            self._shut = (today, frozenset(days))
        return self._shut[1]

    def market_open(self, day: str) -> bool:
        """Whether the market trades on a day (ISO): a week day that is not one of the desk's holidays.  On any
        other day nothing moves - no close is kept for it, and none is a "previous close"."""
        try:
            return _dt.date.fromisoformat(day).weekday() < 5 and day not in self.holidays()
        except ValueError:
            return False

    def last_open_day(self, before: str) -> Optional[str]:
        """The last day before ``before`` (ISO) the market traded."""
        d = _dt.date.fromisoformat(before)
        for _ in range(30):
            d -= _dt.timedelta(days=1)
            if self.market_open(d.isoformat()):
                return d.isoformat()
        return None

    def shut_day(self, today: str) -> Optional[str]:
        """On a Saturday or a Sunday, when no market trades: the last day the market did, whose close stands
        (None on a week day - a holiday of the desk's included: offshore still trades in London then)."""
        return self.last_open_day(today) if _dt.date.fromisoformat(today).weekday() >= 5 else None

    # ================================================================== subjects
    @staticmethod
    def key(subject: Dict[str, Any]) -> str:
        """The same subject is the same key (a VİOP contract by its ticker or its place in the table)."""
        k = subject.get("kind")
        if k == "cell":
            return "cell|%s|%s" % (subject.get("book") or "tto", subject.get("ref"))
        if k == "expr":
            return "expr|%s" % " ".join(str(subject.get("text") or "").split())
        parts = [k] + ["%s=%s" % (f, subject.get(f)) for f in sorted(subject) if f not in ("kind",)]
        return "|".join(str(p) for p in parts)

    def _book(self, book_id: str = "tto"):
        book = self.svc.books.get(book_id)
        if book is None:
            raise KeyError("çalışma kitabı yok: %s" % book_id)
        return book

    class _Reader(object):
        """Cell values of one user's calculation, the bonds of the trading list by ISIN, the VİOP contracts by
        ticker - read once for a whole round."""

        def __init__(self, watch: "Watch", user: Optional[str]):
            from .store import user_key
            self.w = watch
            self.user = user
            self.calcs: Dict[str, Any] = {}
            self.uk = user_key(user) if user else None
            self._rows: Optional[Dict[str, int]] = None
            self._viop: Optional[Dict[str, int]] = None
            self._uni: Optional[Dict[str, int]] = None
            self.names: Optional[Dict[str, Dict[str, Any]]] = None

        def calc(self, book_id: str = "tto"):
            c = self.calcs.get(book_id)
            if c is None:
                c = self.calcs[book_id] = self.w.svc._calc(self.uk, self.w._book(book_id))
            return c

        def get(self, ref: str, book_id: str = "tto") -> Any:
            book = self.w._book(book_id)
            si, rc = book.cell(ref)
            return self.calc(book_id).get(si, *divmod(rc, COLS))

        def rows(self) -> Dict[str, int]:
            """ISIN -> its row in the trading list (DİBS RV A5:A54)."""
            if self._rows is None:
                self._rows = {}
                for r in range(5, 55):
                    try:
                        v = self.get("%s!A%d" % (RV, r))
                    except (KeyError, ValueError):
                        break
                    if isinstance(v, str) and v.strip():
                        self._rows.setdefault("".join(v.split()).upper(), r)
            return self._rows

        def universe(self) -> Dict[str, int]:
            """ISIN -> its row on Tüm Kâğıtlar (prices of a bond that is not on the trading list)."""
            if self._uni is None:
                self._uni = {}
                from . import extras as ex
                for r, b, _ in ex.universe_rows():
                    if b:
                        self._uni[b["isin"]] = r
            return self._uni

        def viop(self) -> Dict[str, int]:
            """Ticker -> the column (index) of its numbers; position "1".."12" too."""
            if self._viop is None:
                self._viop = {}
                for k, col in enumerate(VIOP_TICKERS):
                    try:
                        t = self.get("VIOP!%s1" % col)
                    except (KeyError, ValueError):
                        break
                    data_col = parse_a1("%s1" % col) % COLS + 1
                    if isinstance(t, str) and t.strip():
                        self._viop[" ".join(t.split()).upper()] = data_col
                    self._viop[str(k + 1)] = data_col
            return self._viop

        def at(self, col_index: int, row: int) -> Any:
            book = self.w._book("tto")
            si = book.model.sheet_index["VIOP"]
            return self.calc().get(si, row, col_index)

    def resolve(self, subject: Dict[str, Any], rd: "Watch._Reader") -> Tuple[Optional[float], str, str]:
        """``(display value, shown as, the cell's own text or "")`` of a subject now (``None``: no value)."""
        k = subject.get("kind")

        def num(v: Any, scale: float) -> Optional[float]:
            return v * scale if type(v) is float else None

        try:
            if k == "cell":
                book = self._book(subject.get("book") or "tto")
                si, rc = book.cell(subject["ref"])
                v = rd.calc(book.id).get(si, *divmod(rc, COLS))
                x = book.model.sheets[si].styles.get(rc, 0)
                fmt = book.model.numfmts[x] if x < len(book.model.numfmts) else "General"
                pct = numfmt.is_percent_format(fmt)
                show = subject.get("show") or ("pct" if pct else "raw")
                scale = ({"pct": 100.0, "bp": 10000.0}.get(show, 1.0)) if pct else 1.0      # 0,3555 in a cell in %
                text = numfmt.format_value(v, fmt, numfmt.get_locale(self.svc.settings.locale)) if type(v) is float else ""
                return num(v, scale), show, text if show == ("pct" if pct else "raw") else ""
            if k == "ois":
                t = str(subject.get("tenor") or "").upper()
                ref = OIS_EXTRA.get(t) or ("OIS_MAIN!B%d" % OIS_ROWS[t] if t in OIS_ROWS else None)
                if ref is None:
                    raise KeyError(t)
                return num(rd.get(ref), 100.0), "pct", ""
            if k == "off":
                t = str(subject.get("tenor") or "").upper()
                side = OFF_SIDES.get(subject.get("side") or "mid", "J")
                return num(rd.get("Forward!%s%d" % (side, OFF_ROWS[t])), 1.0), "pct", ""
            if k == "masa":
                _, ref, show, scale = MASA[subject["key"]]
                return num(rd.get(ref), scale), show, ""
            if k == "viop":
                ticker = " ".join(str(subject.get("ticker") or "").split()).upper()
                cols = rd.viop()
                col = cols.get(ticker) or cols.get(ticker + " CURNCY") or cols.get(str(subject.get("position") or ""))
                if col is None:
                    return None, VIOP_METRICS[subject["metric"]][2], ""
                _, row, show, scale = VIOP_METRICS[subject["metric"]]
                if isinstance(row, tuple):
                    a, b = rd.at(col, row[0]), rd.at(col, row[1])
                    v = (a + b) / 2.0 if type(a) is float and type(b) is float else None
                else:
                    v = rd.at(col, row)
                return num(v, scale), show, ""
            if k == "bond":
                isin = "".join(str(subject.get("isin") or "").split()).upper()
                _, sheet, col, show, scale = BOND_METRICS[subject["metric"]]
                r = rd.rows().get(isin)
                if r is None and subject["metric"] in ("bid", "ask", "last"):
                    u = rd.universe().get(isin)                   # off the trading list: Tüm Kâğıtlar has its price
                    if u is not None:
                        return num(rd.get("EK_EVREN!%s%d" % ({"bid": "I", "ask": "J", "last": "K"}[subject["metric"]], u)), 1.0), show, ""
                if r is None:
                    return None, show, ""
                v = rd.get("'%s'!%s%d" % (sheet, col, r) if " " in sheet else "%s!%s%d" % (sheet, col, r))
                return num(v, scale), show, ""
            if k == "expr":
                v, show = self._eval(parse_expr(subject.get("text") or ""), self._live_leaf(rd))
                return v, show, ""
        except (KeyError, ValueError, IndexError):
            return None, subject.get("show") or "raw", ""
        return None, "raw", ""

    def _leaf_subject(self, kind: str, text: str, rd: "Watch._Reader") -> Dict[str, Any]:
        """What a name in brackets or a cell reference of an expression stands for."""
        if kind == "name":
            if rd.names is None:
                rd.names = self.names(rd)
            subj = rd.names.get(fold(text))
            if subj is None:
                raise ExprError("bilinmeyen ad: [%s]" % text)
            return subj
        return self.anchor("tto", text, rd) or {"kind": "cell", "book": "tto", "ref": text}

    def _live_leaf(self, rd: "Watch._Reader") -> Callable[[str, str], Tuple[Optional[float], str]]:
        def leaf(kind: str, text: str) -> Tuple[Optional[float], str]:
            v, show, _ = self.resolve(self._leaf_subject(kind, text, rd), rd)
            return v, show
        return leaf

    def _eval(self, tree: Any, leaf: Callable[[str, str], Tuple[Optional[float], str]]) -> Tuple[Optional[float], str]:
        """The value of an expression and how it is shown.  A sum of rates in per cent whose weights add up to
        nothing (a spread, a fly: ``[OIS 2Y] - [OIS 1Y]``) is told in bp; one whose weights do not (an average)
        stays a rate; spreads in bp stay in bp; a product or a ratio of two quotes, or a mix of units, is a plain
        number."""
        RAW = {"show": "raw", "w": 0.0, "lin": False, "const": False}

        def ev(t: Any) -> Tuple[Optional[float], Dict[str, Any]]:
            kind = t[0]
            if kind == "num":
                return t[1], {"show": None, "w": 0.0, "lin": True, "const": True}
            if kind == "neg":
                v, i = ev(t[1])
                return (-v if v is not None else None), dict(i, w=-i["w"])
            if kind in ("name", "ref"):
                v, show = leaf(kind, t[1])
                return v, {"show": show, "w": 1.0, "lin": show != "raw", "const": False}
            (a, ia), (b, ib) = ev(t[1]), ev(t[2])
            v: Optional[float] = None
            if a is not None and b is not None:
                v = a + b if kind == "+" else a - b if kind == "-" else a * b if kind == "*" else (a / b if b else None)
            if not (ia["lin"] and ib["lin"]):
                return v, RAW
            if kind in ("+", "-"):
                if ia["show"] and ib["show"] and ia["show"] != ib["show"]:
                    return v, RAW                                          # a rate and a spread: a number
                w = ia["w"] + ib["w"] if kind == "+" else ia["w"] - ib["w"]
                return v, {"show": ia["show"] or ib["show"], "w": w, "lin": True, "const": ia["const"] and ib["const"]}
            if kind == "*" and (ia["const"] or ib["const"]):
                k, i = (a, ib) if ia["const"] else (b, ia)
                return v, dict(i, w=i["w"] * (k or 0.0), const=ia["const"] and ib["const"])
            if kind == "/" and ib["const"] and b:
                return v, dict(ia, w=ia["w"] / b)
            return v, RAW

        v, info = ev(tree)
        show = info["show"] if info["lin"] else "raw"
        if show is None:
            return v, "raw"
        if show == "pct" and abs(info["w"]) < 1e-9:
            return (v * 100.0 if v is not None else None), "bp"
        return v, show

    def names(self, rd: Optional["Watch._Reader"] = None) -> Dict[str, Dict[str, Any]]:
        """Every name an expression may use (folded) -> its subject."""
        from . import bonds as bd
        out: Dict[str, Dict[str, Any]] = {}
        for t in list(OIS_ROWS) + list(OIS_EXTRA):
            out[fold("OIS %s" % t)] = {"kind": "ois", "tenor": t}
        out[fold("TLREF")] = {"kind": "ois", "tenor": "TLREF"}
        for t in OFF_ROWS:
            out[fold("Offshore %s" % t)] = {"kind": "off", "tenor": t, "side": "mid"}
            for side in OFF_SIDES:
                out[fold("Offshore %s %s" % (t, side))] = {"kind": "off", "tenor": t, "side": side}
        for key, (label, _, _, _) in MASA.items():
            out[fold(label)] = out[fold(label.replace(" (bp)", ""))] = {"kind": "masa", "key": key}
        rd = rd or self._Reader(self, None)
        tickers = [t for t in rd.viop() if not t.isdigit()]
        for m, (label, _, _, _) in VIOP_METRICS.items():
            for pos in range(1, len(VIOP_TICKERS) + 1):
                out[fold("VİOP %d %s" % (pos, label))] = out[fold("VİOP %d. kontrat %s" % (pos, label))] = \
                    {"kind": "viop", "position": pos, "metric": m}
            for t in tickers:
                short = t.replace(" CURNCY", "")
                out[fold("VİOP %s %s" % (short, label))] = {"kind": "viop", "ticker": t, "metric": m}
        listed = list(rd.rows())
        for isin in [b["isin"] for b in bd.catalog() if b["isin"] not in rd.rows()] + listed:   # (a listed one wins a name)
            b = bd.by_isin(isin)
            for m, (label, _, _, _, _) in BOND_METRICS.items():
                out[fold("%s %s" % (isin, label))] = {"kind": "bond", "isin": isin, "metric": m}
                if b:
                    out[fold("%s %s" % (bd.short_label(b), label))] = {"kind": "bond", "isin": isin, "metric": m}
        return out

    def label(self, subject: Dict[str, Any]) -> str:
        """How the desk calls a subject: "OIS 2Y", "VİOP A1Z6 OIS − VİOP", "15.03.28 ASW"."""
        from . import bonds as bd
        k = subject.get("kind")
        if k == "ois":
            return "OIS %s" % subject.get("tenor") if subject.get("tenor") != "TLREF" else "TLREF"
        if k == "off":
            side = subject.get("side") or "mid"
            return "Offshore %s%s" % (subject.get("tenor"), "" if side == "mid" else " " + side)
        if k == "masa":
            return MASA[subject["key"]][0]
        if k == "viop":
            who = str(subject.get("ticker") or "").replace(" Curncy", "").replace(" CURNCY", "") or "%s. kontrat" % subject.get("position")
            return "VİOP %s %s" % (who, VIOP_METRICS[subject["metric"]][0])
        if k == "bond":
            b = bd.by_isin(subject.get("isin") or "")
            return "%s %s" % (bd.short_label(b) if b else subject.get("isin"), BOND_METRICS[subject["metric"]][0])
        if k == "expr":
            return " ".join(str(subject.get("text") or "").split())[:60]
        return str(subject.get("ref") or "")

    def explain(self, subject: Dict[str, Any], rd: "Watch._Reader", value: Optional[float]) -> str:
        """A word on a subject: the contract a VİOP position is now, the due date of a contract, why there is no
        value (a bond off the trading list, a contract gone, an expression that no longer reads)."""
        k = subject.get("kind")
        try:
            if k == "viop":
                cols = rd.viop()
                ticker = " ".join(str(subject.get("ticker") or "").split()).upper()
                col = cols.get(ticker) or cols.get(str(subject.get("position") or ""))
                if col is None:
                    return "kontrat VİOP tablosunda yok (vadesi geçmiş olabilir)"
                t, due = rd.at(col - 1, 1), rd.at(col - 1, 5)
                head = ("şu an %s" % str(t).replace(" Curncy", "")) if subject.get("position") else ""
                return ", ".join(x for x in (head, "vade %s" % date_text(due) if date_text(due) else "") if x)
            if k == "bond":
                isin = subject.get("isin") or ""
                listed = isin in rd.rows()
                if value is None and not listed and subject.get("metric") not in ("bid", "ask", "last"):
                    return "%s trading listesinde değil (Tüm Kâğıtlar'da ☆ ile ekleyin)" % isin
                return isin + ("" if listed else " · trading listesi dışında")
            if k == "expr" and value is None:
                try:
                    self._eval(parse_expr(subject.get("text") or ""), self._live_leaf(rd))
                except ExprError as exc:
                    return str(exc)
            if k == "cell":
                return "%s · %s" % (subject.get("book") or "tto", subject.get("ref"))
        except (KeyError, ValueError, IndexError):
            return ""
        return ""

    def check(self, subject: Dict[str, Any]) -> Dict[str, Any]:
        """A subject as it is kept (unknown kinds, metrics and malformed expressions refused)."""
        if not isinstance(subject, dict):
            raise ValueError("izlenecek şey belli değil")
        k = subject.get("kind")
        out: Dict[str, Any] = {"kind": k}
        if k == "cell":
            book = self._book(str(subject.get("book") or "tto"))
            si, rc = book.cell(str(subject.get("ref") or ""))
            out.update(book=book.id, ref=book.ref(si, rc))
            anchored = self.anchor(book.id, out["ref"])
            if anchored is not None:
                return self.check(anchored)
        elif k == "ois":
            t = str(subject.get("tenor") or "").upper()
            if t not in OIS_ROWS and t not in OIS_EXTRA:
                raise ValueError("OIS vadesi yok: %s" % t)
            out["tenor"] = t
        elif k == "off":
            t = str(subject.get("tenor") or "").upper()
            if t not in OFF_ROWS:
                raise ValueError("offshore vadesi yok: %s" % t)
            out.update(tenor=t, side=subject.get("side") if subject.get("side") in OFF_SIDES else "mid")
        elif k == "masa":
            if subject.get("key") not in MASA:
                raise ValueError("bilinmeyen: %s" % subject.get("key"))
            out["key"] = subject["key"]
        elif k == "viop":
            if subject.get("metric") not in VIOP_METRICS:
                raise ValueError("VİOP ölçüsü yok: %s" % subject.get("metric"))
            out["metric"] = subject["metric"]
            if subject.get("ticker"):
                out["ticker"] = " ".join(str(subject["ticker"]).split()).upper().replace(" CURNCY", "") + " Curncy"
            elif str(subject.get("position") or "").isdigit():
                out["position"] = int(subject["position"])
            else:
                raise ValueError("VİOP kontratı seçilmedi")
        elif k == "bond":
            from . import bonds as bd
            isin = "".join(str(subject.get("isin") or "").split()).upper()
            if not bd.isin_valid(isin):
                raise ValueError("ISIN değil: %s" % isin)
            if subject.get("metric") not in BOND_METRICS:
                raise ValueError("kâğıt ölçüsü yok: %s" % subject.get("metric"))
            out.update(isin=isin, metric=subject["metric"])
        elif k == "expr":
            text = " ".join(str(subject.get("text") or "").split())
            tree = parse_expr(text)
            names = self.names()

            def walk(t: Any) -> None:
                if t[0] == "name" and fold(t[1]) not in names:
                    raise ExprError("bilinmeyen ad: [%s] - listeden seçin ya da hücre adresi yazın" % t[1])
                if t[0] == "ref":
                    self._book("tto").cell(t[1])
                for x in t[1:]:
                    if isinstance(x, tuple):
                        walk(x)

            walk(tree)
            out["text"] = text
        else:
            raise ValueError("bilinmeyen tür: %s" % k)
        if k == "cell" and subject.get("show") in SHOWS:
            out["show"] = subject["show"]
        return out

    def anchor(self, book_id: str, ref: str, rd: Optional["Watch._Reader"] = None) -> Optional[Dict[str, Any]]:
        """A cell of a table that names something: the thing, not the cell (a bond's row of DİBS RV follows the
        bond when the list changes; a VİOP column the contract when they roll; an OIS row its tenor)."""
        if book_id != "tto" or "!" not in ref:
            return None
        sheet, addr = ref.rsplit("!", 1)
        sheet = sheet.strip("'")
        rc = parse_a1(addr.replace("$", ""))
        r, c = divmod(rc, COLS)
        col = addr.rstrip("0123456789").replace("$", "")
        rd = rd or self._Reader(self, None)
        if sheet in (RV, "EK_DIBS") and 5 <= r <= 54:
            isin = rd.get("%s!A%d" % ("'%s'" % sheet if " " in sheet else sheet, r))
            metric = next((m for m, x in BOND_METRICS.items() if x[1] == sheet and x[2] == col), None)
            if isinstance(isin, str) and isin.strip() and metric:
                return {"kind": "bond", "isin": "".join(isin.split()).upper(), "metric": metric}
        if sheet == "EK_EVREN" and r >= 6 and col in ("N", "O"):              # Tüm Kâğıtlar: DİBS RV's yield, ASW
            isin = rd.get("EK_EVREN!A%d" % r)
            if isinstance(isin, str) and isin.strip():
                return {"kind": "bond", "isin": "".join(isin.split()).upper(), "metric": "yield" if col == "N" else "asw"}
        if sheet == "VIOP":
            metric = next((m for m, x in VIOP_METRICS.items() if not isinstance(x[1], tuple) and x[1] == r), None)
            ticker_col = c - 1
            if metric and 0 <= ticker_col - parse_a1("L1") % COLS < len(VIOP_TICKERS):
                t = rd.get("VIOP!%s1" % VIOP_TICKERS[ticker_col - parse_a1("L1") % COLS])
                if isinstance(t, str) and t.strip():
                    return {"kind": "viop", "ticker": " ".join(t.split()), "metric": metric}
        if sheet == "OIS_MAIN" and col == "B":
            tenor = next((t for t, row in OIS_ROWS.items() if row == r), None)
            if tenor:
                return {"kind": "ois", "tenor": tenor}
        if sheet == "Forward" and col in ("I", "J", "K"):
            tenor = next((t for t, row in OFF_ROWS.items() if row == r), None)
            if tenor:
                return {"kind": "off", "tenor": tenor, "side": {v: k for k, v in OFF_SIDES.items()}[col]}
        return None

    def catalog(self) -> Dict[str, Any]:
        """What the "Ekle" window offers: OIS tenors, offshore tenors, the desk strip, the VİOP contracts and
        their measures, the bonds (the trading list first) and theirs, the units and conditions."""
        from . import bonds as bd
        rd = self._Reader(self, None)
        listed = list(rd.rows())
        contracts = []
        for k, col in enumerate(VIOP_TICKERS):
            try:
                t = rd.get("VIOP!%s1" % col)
                due = rd.get("VIOP!%s5" % col)
            except (KeyError, ValueError):
                break
            if isinstance(t, str) and t.strip():
                contracts.append({"ticker": " ".join(t.split()), "position": k + 1, "short": t.replace(" Curncy", ""),
                                  "due": date_text(due)})
        bonds = []
        for isin in listed + [b["isin"] for b in bd.catalog() if b["isin"] not in listed]:
            b = bd.by_isin(isin)
            bonds.append({"isin": isin, "label": bd.short_label(b) if b else isin, "listed": isin in listed})
        return {"ois": list(OIS_EXTRA) + list(OIS_ROWS), "off": list(OFF_ROWS), "off_sides": list(OFF_SIDES),
                "masa": [{"key": k, "label": v[0]} for k, v in MASA.items()], "viop": contracts,
                "viop_metrics": [{"id": k, "label": v[0], "show": v[2]} for k, v in VIOP_METRICS.items()],
                "bonds": bonds, "bond_metrics": [{"id": k, "label": v[0], "show": v[3], "listed_only": k not in ("bid", "ask", "last")}
                                                 for k, v in BOND_METRICS.items()],
                "presets": [{"group": g, "items": [self.label(s) for s in p]} for g, p in PRESETS],
                "shows": {k: v[0] for k, v in SHOWS.items()}, "ops": OPS}

    def preview(self, user: Optional[str], subject: Dict[str, Any]) -> Dict[str, Any]:
        s = self.check(subject)
        rd = self._Reader(self, user)
        v, show, text = self.resolve(s, rd)
        name = "%s %s" % (s["isin"], BOND_METRICS[s["metric"]][0]) if s["kind"] == "bond" else self.label(s)
        unit_name, k = SHOWS.get(show, SHOWS["raw"])
        zs = {}
        for n in Z_DAYS:
            try:
                zi = self.zinfo(s, v, n, rd)
            except Exception:  # noqa: BLE001
                zi = {"z": None, "n": 0, "need": min_closes(n)}
            zs[str(n)] = {"z": zi.get("z"), "z_text": z_text(zi.get("z")), "n": zi.get("n"), "need": zi.get("need"),
                          "pct": zi.get("pct"), "source": zi.get("source")}
        opened = self.day_open(user or "", self.key(s))
        since = (v - opened) * k if type(v) is float and opened is not None else None
        return {"subject": s, "label": self.label(s), "name": name, "value": v, "show": show, "text": text or value_text(v, show),
                "detail": self.explain(s, rd, v), "unit": {"pct": "%", "bp": "bp"}.get(show, ""),
                "move_unit": "bp" if unit_name == "bp" else unit_name, "z": zs, "since_open": since,
                "since_open_text": move_text(since, "bp" if unit_name == "bp" else show)}

    # ================================================================== the past: daily closes, z-scores
    def _hist_defs(self) -> Dict[Tuple[str, str], Any]:
        """(group, tenor) -> the market history's series of it: the OIS tenors, TLREF, the offshore implied rates
        (their closes are the same quantity as the pages' level).  Read once a day, or when the history grew."""
        hist = getattr(self.svc, "history", None)
        if hist is None:
            return {}
        mark = (hist.rev, self.svc.today_iso())
        if self._defs is not None and self._defs[0] == mark:
            return self._defs[1]
        out: Dict[Tuple[str, str], Any] = {}
        try:
            for d in hist.snapshot().get("defs") or []:
                if d.group in ("ois", "off", "ref"):
                    out[(d.group, d.label.strip().upper())] = d
        except Exception:  # noqa: BLE001 - no history is no z-score, not an error
            out = {}
        self._defs = (mark, out)
        return out

    def _market_def(self, subject: Dict[str, Any]) -> Any:
        k = subject.get("kind")
        defs = self._hist_defs()
        if (k == "ois" and subject.get("tenor") == "TLREF") or (k == "masa" and subject.get("key") == "tlref"):
            return defs.get(("ref", "TLREF"))
        if k == "ois":
            return defs.get(("ois", str(subject.get("tenor") or "").upper()))
        if k == "off" and (subject.get("side") or "mid") == "mid":
            return defs.get(("off", str(subject.get("tenor") or "").upper()))
        return None

    def history(self, subject: Dict[str, Any], rd: Optional["Watch._Reader"] = None) -> Tuple[Dict[str, float], str]:
        """The daily closes of a subject before today, in its own unit: ``({day: value}, where from)``.  The
        market history's own closes where it keeps the same thing (OIS, TLREF, offshore); an expression's from
        the closes of its parts; filled in with the closes the watch kept itself of anything watched (a VİOP
        spread, an ASW ...: from the day it was first watched)."""
        today = self.svc.today_iso()
        hist = getattr(self.svc, "history", None)
        mark = (self.key(subject), today, hist.rev if hist is not None else 0)
        hit = self._hist.get(mark)
        if hit is not None:
            return hit
        rd = rd or self._Reader(self, None)
        start = (_dt.date.fromisoformat(today) - _dt.timedelta(days=420)).isoformat()
        out: Dict[str, float] = {}
        source = []
        d = self._market_def(subject)
        if d is not None:
            try:
                out = {day: v for day, v in d.merged(self.svc.store.hist_many(d.ids(), start))[1].items() if day < today}
            except Exception:  # noqa: BLE001
                out = {}
            if out:
                source.append("tarihçe")
        elif subject.get("kind") == "expr":
            try:
                out = {day: v for day, v in self._expr_history(subject, rd).items() if day < today}
            except (ExprError, KeyError, ValueError):
                out = {}
            if out:
                source.append("tarihçe")
        own = self.svc.store.closes([self.key(subject)], start).get(self.key(subject)) or {}
        # only the days the market traded: a value kept on a Saturday, a Sunday or a holiday is no close
        extra = {day: v for day, v in own.items() if day < today and day not in out and self.market_open(day)}
        if extra:
            out.update(extra)
            source.append("kayıt")
        res = (out, " + ".join(source))
        if len(self._hist) > 2000:
            self._hist = {}
        self._hist[mark] = res
        return res

    def _expr_history(self, subject: Dict[str, Any], rd: "Watch._Reader") -> Dict[str, float]:
        """An expression's value on every past day all its parts have a close: the same arithmetic (and the
        same unit) as now."""
        tree = parse_expr(subject.get("text") or "")
        leaves: Dict[Tuple[str, str], Dict[str, Any]] = {}

        def walk(t: Any) -> None:
            if t[0] in ("name", "ref"):
                leaves[(t[0], t[1])] = self._leaf_subject(t[0], t[1], rd)
            for x in t[1:]:
                if isinstance(x, tuple):
                    walk(x)

        walk(tree)
        if not leaves:
            return {}
        series: Dict[Tuple[str, str], Dict[str, float]] = {}
        shows: Dict[Tuple[str, str], str] = {}
        for lk, subj in leaves.items():
            if subj.get("kind") == "expr":
                return {}
            series[lk] = self.history(subj, rd)[0]
            shows[lk] = self.resolve(subj, rd)[1]
            if not series[lk]:
                return {}
        days = set.intersection(*[set(x) for x in series.values()])
        out: Dict[str, float] = {}
        for day in sorted(days):
            v, _ = self._eval(tree, lambda kind, text, day=day: (series[(kind, text)].get(day), shows[(kind, text)]))
            if type(v) is float:
                out[day] = v
        return out

    def stats(self, subject: Dict[str, Any], days: int, rd: Optional["Watch._Reader"] = None) -> Dict[str, Any]:
        """The last ``days`` closes before today: their mean, standard deviation (sample), low and high."""
        closes, source = self.history(subject, rd)
        keys = sorted(closes)[-days:]
        vals = [closes[k] for k in keys]
        out: Dict[str, Any] = {"days": days, "n": len(vals), "need": min_closes(days), "source": source,
                               "first": keys[0] if keys else None, "last": keys[-1] if keys else None}
        if len(vals) >= min_closes(days):
            mean = sum(vals) / len(vals)
            sd = math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
            out.update(mean=mean, sd=sd, min=min(vals), max=max(vals), sorted=sorted(vals))
        return out

    def zinfo(self, subject: Dict[str, Any], value: Optional[float], days: int, rd: Optional["Watch._Reader"] = None) -> Dict[str, Any]:
        """Where a level stands against its own past: z-score, the share of closes below it (per cent), the band."""
        st = self.stats(subject, days, rd)
        out = {k: v for k, v in st.items() if k != "sorted"}
        out["z"] = out["pct"] = None
        if type(value) is float and st.get("sd"):
            out["z"] = (value - st["mean"]) / st["sd"]
            out["pct"] = 100.0 * bisect.bisect_left(st["sorted"], value) / len(st["sorted"])
        return out

    def record(self, force: bool = False) -> int:
        """Keep the day's last value of everything watched (the market's: no one's personal scenario) - the
        closes a z-score and the heat map's "previous close" use where the market history has none.  Not on a
        day the market is shut: a Saturday's value is Friday's again, and no "previous close"."""
        epoch = time.time()
        if not force and epoch - self._recorded_at < RECORD_EVERY:
            return 0
        self._recorded_at = epoch
        if not self.market_open(self.svc.today_iso()):
            return 0
        subjects: Dict[str, Dict[str, Any]] = {}
        for items in self._items_all().values():
            for i in items or []:
                subjects[self.key(i["subject"])] = i["subject"]
        for a in self.alarms():
            subjects[self.key(a["subject"])] = a["subject"]
        rd = self._Reader(self, None)
        try:
            for subj in (self.heat_subjects(rd) if self._heat_day == self.svc.today_iso() else ()):
                subjects.setdefault(self.key(subj), subj)
        except Exception:  # noqa: BLE001
            pass
        today = self.svc.today_iso()
        rows = []
        for key, subj in subjects.items():
            try:
                v = self.resolve(subj, rd)[0]
            except Exception:  # noqa: BLE001
                continue
            if type(v) is float:
                rows.append((key, today, v))
        return self.svc.store.close_upsert(rows)

    # ================================================================== the heat map
    HEAT_TENORS = ("O/N", "T/N", "1W", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "15M", "18M", "21M", "2Y",
                   "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y")

    def heat_layout(self, rd: "Watch._Reader") -> List[Dict[str, Any]]:
        """The tables of the heat map: OIS, offshore and their difference by tenor; the VİOP contracts; the bonds
        of the trading list by maturity.  Each cell is a subject (None: nothing at that tenor)."""
        from . import bonds as bd
        cols = list(self.HEAT_TENORS)
        off_at = {"1Y": "12M"}

        def ois(c: str) -> Optional[Dict[str, Any]]:
            if c == "O/N":
                return {"kind": "ois", "tenor": "TLREF"}
            return {"kind": "ois", "tenor": c} if c in OIS_ROWS or c in ("1W", "2W") else None

        def off(c: str) -> Optional[Dict[str, Any]]:
            t = off_at.get(c, c)
            return {"kind": "off", "tenor": t, "side": "mid"} if t in OFF_ROWS else None

        def basis(c: str) -> Optional[Dict[str, Any]]:
            a, b = off(c), ois(c)
            if a is None or b is None:
                return None
            return {"kind": "expr", "text": "[%s] - [%s]" % (self.label(a), self.label(b))}

        out = [{"id": "curve", "title": "TRY OIS · offshore (FX swap ima) · fark", "cols": [{"id": c, "label": c} for c in cols],
                "rows": [{"name": "OIS", "cells": [ois(c) for c in cols]},
                         {"name": "Offshore", "cells": [off(c) for c in cols]},
                         {"name": "Offshore − OIS", "cells": [basis(c) for c in cols]}]}]
        contracts = []
        for k, col in enumerate(VIOP_TICKERS):
            try:
                t = rd.get("VIOP!%s1" % col)
            except (KeyError, ValueError):
                break
            if isinstance(t, str) and t.strip():
                due = date_text(rd.get("VIOP!%s5" % col))
                contracts.append((" ".join(t.split()), t.replace(" Curncy", "").strip(), due))
        if contracts:
            out.append({"id": "viop", "title": "VİOP USDTRY kontratları",
                        "cols": [{"id": c[0], "label": month_label(c[2]) or c[1], "tip": c[1] + (" · vade " + c[2] if c[2] else "")}
                                 for c in contracts],
                        "rows": [{"name": "OIS − VİOP", "cells": [{"kind": "viop", "ticker": c[0], "metric": "ois"} for c in contracts]},
                                 {"name": "ima TRY", "cells": [{"kind": "viop", "ticker": c[0], "metric": "try_mid"} for c in contracts]}]})
        listed = []
        for isin in rd.rows():
            b = bd.by_isin(isin)
            listed.append((b.get("maturity") if b else "9999", isin, bd.short_label(b) if b else isin))
        listed.sort()
        if listed:
            out.append({"id": "dibs", "title": "DİBS · trading listesi (vadeye göre)",
                        "cols": [{"id": isin, "label": label, "tip": isin} for _, isin, label in listed],
                        "rows": [{"name": name, "cells": [{"kind": "bond", "isin": isin, "metric": m} for _, isin, _ in listed]}
                                 for name, m in (("getiri", "yield"), ("ASW", "asw"), ("pahalı/ucuz", "rv"))]})
        return out

    def heat_subjects(self, rd: "Watch._Reader") -> List[Dict[str, Any]]:
        return [c for p in self.heat_layout(rd) for row in p["rows"] for c in row["cells"] if c is not None]

    def _heat_refs(self) -> Dict[str, Any]:
        v = self.svc.store.get("heat.ref:%s" % self.svc.today_iso(), {})
        return v if isinstance(v, dict) else {}

    def heat_ref(self, user: str) -> Dict[str, Any]:
        """The levels now, as this user's reference for the day (the morning meeting)."""
        rd = self._Reader(self, None)
        values = {}
        for subj in self.heat_subjects(rd):
            v = self.resolve(subj, rd)[0]
            if type(v) is float:
                values[self.key(subj)] = v
        refs = self._heat_refs()
        refs[user] = {"at": _now().strftime("%H:%M:%S"), "values": values}
        self.svc.store.put("heat.ref:%s" % self.svc.today_iso(), refs)
        return {"at": refs[user]["at"], "count": len(values)}

    def heat(self, user: str, basis: str, loc) -> Dict[str, Any]:
        """The heat map: every point's change against the previous close, the day's open or the user's
        reference - in bp for rates and spreads."""
        basis = basis if basis in ("close", "open", "ref") else "close"
        rd = self._Reader(self, None)
        ref = self._heat_refs().get(user) if basis == "ref" else None
        today = self.svc.today_iso()
        # a Saturday, a Sunday: the market is shut - its last day's close stands and nothing has moved since (a
        # value read now may still differ from that close, e.g. a yield priced to another value date: no move)
        shut = self.shut_day(today)
        if self._heat_day != today:
            self._heat_day = today                       # opened today: its points are read from now on
            self._heat_at = 0.0
        panels = []
        moves: List[float] = []
        for p in self.heat_layout(rd):
            rows = []
            for row in p["rows"]:
                cells: List[Optional[Dict[str, Any]]] = []
                for subj in row["cells"]:
                    if subj is None:
                        cells.append(None)
                        continue
                    key = self.key(subj)
                    v, show, _ = self.resolve(subj, rd)
                    base, base_day = None, None
                    if basis == "open":
                        base = (self.days.get(("", key)) or {}).get("open")
                    elif basis == "ref":
                        base = ((ref or {}).get("values") or {}).get(key)
                    else:
                        closes = self.history(subj, rd)[0]
                        prev = max((d for d in closes if d < today), default=None)
                        base, base_day = (closes[prev], prev) if prev else (None, None)
                        if shut and prev == shut:
                            v = base
                    k = SHOWS.get(show, SHOWS["raw"])[1]
                    chg = (v - base) * k if type(v) is float and type(base) is float else None
                    if chg is not None:
                        moves.append(abs(chg))
                    cells.append({"subject": subj, "label": self.label(subj), "show": show, "now": v,
                                  "now_text": short_text(v, show, loc), "base": base, "base_text": value_text(base, show, loc),
                                  "base_day": base_day, "chg": chg, "chg_text": move_text(chg, "bp" if SHOWS.get(show, SHOWS["raw"])[0] == "bp" else show, loc)})
                rows.append({"name": row["name"], "cells": cells})
            panels.append({"id": p["id"], "title": p["title"], "cols": p["cols"], "rows": rows})
        top = max(moves) if moves else 0.0
        cap = next((c for c in (5, 10, 15, 20, 25, 50, 75, 100, 150, 200, 300, 500) if top <= c), 1000)
        return {"basis": basis, "bases": {"close": "önceki kapanış", "open": "açılış", "ref": "referans"}, "panels": panels,
                "cap": cap, "time": _now().strftime("%H:%M:%S"), "ref_at": (ref or {}).get("at"), "day": today, "closed": shut}

    # ================================================================== what is kept
    def _items_all(self) -> Dict[str, List[Dict[str, Any]]]:
        v = self.svc.store.get("watch.items", {})
        v = v if isinstance(v, dict) else {}
        return {u: [self._item(i) for i in items or []] for u, items in v.items()}

    @staticmethod
    def _item(i: Dict[str, Any]) -> Dict[str, Any]:
        """An item of an earlier version (a cell and its unit) as one of this."""
        if "subject" not in i:
            i = dict(i)
            i["subject"] = {"kind": "cell", "book": i.get("book") or "tto", "ref": i.get("ref")}
            if i.get("unit") in ("bp", "px", "fx", "pct"):
                i["subject"]["show"] = i["unit"]
            if numfmt.is_percent_format(i.get("fmt") or "General") and type(i.get("base")) is float:
                i["base"] = i["base"] * 100.0                         # kept as the cell's fraction, now as shown
        return i

    def items(self, user: str) -> List[Dict[str, Any]]:
        return list(self._items_all().get(user) or [])

    def _put_items(self, user: str, items: List[Dict[str, Any]]) -> None:
        with self._lock:
            allv = self._items_all()
            allv[user] = items
            self.svc.store.put("watch.items", allv)

    def alarms(self, user: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every alarm (``user`` None), or one user's own; the desk's alarms are the market's: user ``""``."""
        v = self.svc.store.get("watch.alarms", [])
        v = [self._alarm(a) for a in v if isinstance(a, dict)] if isinstance(v, list) else []
        return [a for a in v if user is None or a.get("user") == user]

    def desk_list(self) -> List[Dict[str, Any]]:
        """The desk's alarms: set by an administrator for everyone, read on the market's values (deskalarms.py)."""
        return [a for a in self.alarms("") if a.get("desk")]

    @staticmethod
    def _alarm(a: Dict[str, Any]) -> Dict[str, Any]:
        if "subject" not in a:
            a = dict(a)
            a["subject"] = {"kind": "cell", "book": a.get("book") or "tto", "ref": a.get("ref")}
            pct = numfmt.is_percent_format(a.get("fmt") or "General")
            if pct:                                                   # kept as the cell's fraction, now as shown
                for f in ("level", "last", "fired_value"):
                    if type(a.get(f)) is float:
                        a[f] = a[f] * 100.0
            a["show"] = "pct" if pct else {"frac": "pct"}.get(a.get("unit"), a.get("unit") if a.get("unit") in SHOWS else "raw")
            if a["show"] != "raw" and not pct:
                a["subject"]["show"] = a["show"]
        return a

    def _put_alarms(self, alarms: List[Dict[str, Any]]) -> None:
        self.svc.store.put("watch.alarms", alarms[-MAX_ALARMS:])

    def fired(self, day: Optional[str] = None) -> List[Dict[str, Any]]:
        v = self.svc.store.get("watch.fired:%s" % (day or self.svc.today_iso()), [])
        return v if isinstance(v, list) else []

    # ------------------------------------------------------------------ the watch list
    def add(self, user: str, subject: Dict[str, Any], label: str = "", hint: str = "") -> Dict[str, Any]:
        """``label``: the name the user gave; ``hint``: the name of a cell as its table tells it (row and column) -
        used only when the cell is watched as a cell (one that shows a bond, a contract, a tenor is named as the
        desk calls that)."""
        s = self.check(subject)
        label = label or (hint if s["kind"] == "cell" else "")
        items = self.items(user)
        if any(self.key(i["subject"]) == self.key(s) for i in items):
            return {"added": False, "items": items}
        if len(items) >= MAX_ITEMS:
            raise ValueError("izleme listesi dolu (%d)" % MAX_ITEMS)
        item = {"id": uuid.uuid4().hex[:10], "subject": s, "label": (label or self.label(s)).strip()[:60], "base": None, "base_at": None}
        items.append(item)
        self._put_items(user, items)
        return {"added": True, "item": item, "items": items}

    def add_preset(self, user: str, group: str) -> Dict[str, Any]:
        found = next((p for g, p in PRESETS if g == group), None)
        if found is None:
            raise ValueError("hazır grup yok: %s" % group)
        n = 0
        for s in found:
            try:
                n += 1 if self.add(user, s)["added"] else 0
            except (KeyError, ValueError):
                continue
        return {"added": n}

    def remove(self, user: str, item_id: str) -> int:
        items = self.items(user)
        keep = [i for i in items if i["id"] != item_id]
        self._put_items(user, keep)
        return len(items) - len(keep)

    def update(self, user: str, item_id: str, label: Optional[str] = None, unit: Optional[str] = None,
               move: Optional[int] = None) -> None:
        items = self.items(user)
        k = next((n for n, i in enumerate(items) if i["id"] == item_id), None)
        if k is None:
            raise KeyError(item_id)
        if label is not None and label.strip():
            items[k]["label"] = label.strip()[:60]
        if unit is not None and unit in SHOWS and items[k]["subject"].get("kind") == "cell":
            items[k]["subject"] = dict(items[k]["subject"], show=unit)        # (a cell does not say what it holds)
        if move:
            j = max(0, min(len(items) - 1, k + int(move)))
            items.insert(j, items.pop(k))
        self._put_items(user, items)

    def set_base(self, user: str, item_id: Optional[str] = None) -> int:
        """The reference a change is also told against ("since the morning meeting"): the level now - of one
        item, or of every item (``item_id`` ``None``)."""
        items = self.items(user)
        rd = self._Reader(self, user)
        at = _now().strftime("%H:%M:%S")
        n = 0
        for i in items:
            if item_id is not None and i["id"] != item_id:
                continue
            v, _, _ = self.resolve(i["subject"], rd)
            if type(v) is float:
                i["base"], i["base_at"] = v, self.svc.today_iso() + " " + at
                n += 1
        self._put_items(user, items)
        return n

    # ------------------------------------------------------------------ alarms
    def add_alarm(self, user: str, subject: Dict[str, Any], op: str, level: float, label: str = "", note: str = "",
                  mode: str = "level", minutes: Optional[int] = None, days: Optional[int] = None,
                  desk_by: Optional[str] = None) -> Dict[str, Any]:
        """An alarm on a subject.  ``mode``: ``level`` (``op`` ≥ / ≤ / crossing ``level``, as shown); a move of
        ``level`` (bp for rates and spreads, else its own unit) ``op`` up / down / either way - from the day's
        ``open``, from the level when it is ``set``, from the watch list's ``ref``erence, or within the last
        ``minutes`` (``window``); ``z``: the z-score over ``days`` closes ≥ / ≤ / crossing ``level``.
        ``desk_by``: the desk's alarm, set by that administrator for everyone (``user`` is then ``""``: the market)."""
        if desk_by is not None:
            user = ""
        mode = mode or "level"
        if mode not in MODES:
            raise ValueError("alarm türü yok: %s" % mode)
        if type(level) is not float:
            raise ValueError("seviye bir sayı olmalı")
        if mode in ("level", "z"):
            if op not in OPS:
                raise ValueError("koşul: ≥, ≤ ya da kesişir")
        else:
            if op not in DIRS:
                raise ValueError("yön: yukarı, aşağı ya da iki yön")
            if level <= 0:
                raise ValueError("hareket sıfırdan büyük olmalı")
        if mode == "window":
            try:
                minutes = int(minutes or 0)
            except (TypeError, ValueError):
                minutes = 0
            if not 1 <= minutes <= 60:
                raise ValueError("dakika 1 – 60 arasında olmalı")
        if mode == "z":
            try:
                days = int(days or 60)
            except (TypeError, ValueError):
                days = 0
            if days not in Z_DAYS:
                raise ValueError("z-skoru penceresi 20, 60 ya da 250 gün")
        s = self.check(subject)
        rd = self._Reader(self, user)
        v, show, _ = self.resolve(s, rd)
        alarms = self.alarms()
        if len(alarms) >= MAX_ALARMS:
            raise ValueError("alarm listesi dolu (%d)" % MAX_ALARMS)
        a = {"id": uuid.uuid4().hex[:10], "user": user, "subject": s, "mode": mode, "op": op, "level": level, "show": show,
             "label": (label or self.label(s)).strip()[:60], "note": (note or "").strip()[:200], "active": True,
             "created": _now().strftime("%Y-%m-%d %H:%M:%S"), "fired_at": None, "fired_value": None, "last": v}
        if desk_by is not None:
            a["desk"], a["by"] = True, desk_by
        if mode == "window":
            a["minutes"] = minutes
        if mode == "z":
            a["days"] = days
        if mode == "set":
            if type(v) is not float:
                raise ValueError("şu an değeri yok: kurulduğu seviye alınamadı")
            a["base"], a["base_at"] = v, _now().strftime("%H:%M:%S")
        measure, already = (None, False)
        if type(v) is float:
            if mode == "open":
                self._first_seen(user, self.key(s), v)
            measure, already = self._alarm_state(a, v, user, rd)
            if mode == "z":
                a["last_z"] = measure
        alarms.append(a)
        self._put_alarms(alarms)
        if mode == "level":
            already = v is not None and ((op == ">=" and v >= level) or (op == "<=" and v <= level))
        return {"alarm": a, "already": bool(already), "value": v, "text": value_text(v, show), "measure": measure,
                "condition": self.cond_text(a)}

    def remove_alarm(self, user: str, alarm_id: str) -> int:
        alarms = self.alarms()
        keep = [a for a in alarms if not (a["id"] == alarm_id and a.get("user") == user)]
        self._put_alarms(keep)
        return len(alarms) - len(keep)

    def rearm(self, user: str, alarm_id: str, level: Optional[float] = None) -> Dict[str, Any]:
        """Armed again (a new level, if given); one on a move from the level when it was set starts from now."""
        alarms = self.alarms()
        a = next((x for x in alarms if x["id"] == alarm_id and x.get("user") == user), None)
        if a is None:
            raise KeyError(alarm_id)
        a["active"], a["fired_at"], a["fired_value"] = True, None, None
        if type(level) is float:
            if (a.get("mode") or "level") not in ("level", "z") and level <= 0:
                raise ValueError("hareket sıfırdan büyük olmalı")
            a["level"] = level
        if a.get("mode") == "set":
            v = self.resolve(a["subject"], self._Reader(self, user))[0]
            if type(v) is float:
                a["base"], a["base_at"] = v, _now().strftime("%H:%M:%S")
        self._put_alarms(alarms)
        return a

    def _alarm_state(self, a: Dict[str, Any], v: float, user: str, rd: "Watch._Reader",
                     epoch: Optional[float] = None) -> Tuple[Optional[float], bool]:
        """An alarm's measure now - the level, the move (bp for rates and spreads), the z-score - and whether
        its condition holds."""
        mode = a.get("mode") or "level"
        op, level = a.get("op"), a["level"]
        eps = 1e-9 * max(1.0, abs(level))

        def crossed(prev: Any, now: float) -> bool:
            return type(prev) is float and ((prev < level <= now) or (prev > level >= now))

        if mode == "level":
            return v, (op == ">=" and v >= level) or (op == "<=" and v <= level) or (op == "x" and crossed(a.get("last"), v))
        if mode == "z":
            z = self.zinfo(a["subject"], v, int(a.get("days") or 60), rd).get("z")
            if z is None:
                return None, False
            return z, (op == ">=" and z >= level) or (op == "<=" and z <= level) or (op == "x" and crossed(a.get("last_z"), z))
        k = SHOWS.get(a.get("show") or "raw", SHOWS["raw"])[1]
        d = self.days.get((user, self.key(a["subject"]))) or {}
        if mode == "window":
            epoch = epoch if epoch is not None else _now().timestamp()
            start = epoch - 60.0 * int(a.get("minutes") or 10)
            pts = d.get("recent") or []
            vals = [p[1] for p in pts if p[0] >= start]
            before = [p[1] for p in pts if p[0] < start]
            if before:
                vals.append(before[-1])                       # the level the window began with
            vals.append(v)
            up, down = (v - min(vals)) * k, (max(vals) - v) * k
            if op == "up":
                return up, up >= level - eps
            if op == "down":
                return -down, down >= level - eps
            return (up if up >= down else -down), max(up, down) >= level - eps
        if mode == "open":
            base = self.day_open(user, self.key(a["subject"]))
        elif mode == "set":
            base = a.get("base")
        else:
            item = next((i for i in self.items(user) if self.key(i["subject"]) == self.key(a["subject"])), None)
            base = item.get("base") if item else None
        if type(base) is not float:
            return None, False
        mv = (v - base) * k
        return mv, (op == "up" and mv >= level - eps) or (op == "down" and mv <= -level + eps) or (op == "any" and abs(mv) >= level - eps)

    def _first_seen(self, user: str, key: str, v: float) -> None:
        """A subject not read yet today: the value now is the first one seen - its open (kept for a restart)."""
        if (user, key) in self.days or self.day_open(user, key) is not None:
            return
        today = self.svc.today_iso()
        self.days[(user, key)] = {"open": v, "high": v, "low": v, "last": None, "moved": None, "path": [], "recent": []}
        opened = self.svc.store.get("watch.open:%s" % today, {})
        opened = opened if isinstance(opened, dict) else {}
        opened["%s#%s" % (user, key)] = v
        self.svc.store.put("watch.open:%s" % today, opened)

    def day_open(self, user: str, key: str) -> Optional[float]:
        """The day's open of a subject: the market's (read from the first round of the day, the heat map's points
        among them) where there is one, else the first value seen of it for this user."""
        v = (self.days.get(("", key)) or {}).get("open")
        if type(v) is float:
            return v
        v = (self.days.get((user, key)) or {}).get("open")
        return v if type(v) is float else None

    def cond_text(self, a: Dict[str, Any], loc=None) -> str:
        """The condition as the list says it: "≥ 35,80%", "açılıştan ± 15,0 bp", "10 dk içinde ↑ 5,0 bp", "z(60g) ≥ 2,00"."""
        mode = a.get("mode") or "level"
        show = a.get("show") or "raw"
        if mode == "level":
            return "%s %s" % (OPS.get(a.get("op"), a.get("op")), value_text(a["level"], show, loc))
        if mode == "z":
            return "z(%sg) %s %s" % (a.get("days") or 60, OPS.get(a.get("op"), a.get("op")), z_text(a["level"], loc))
        size = move_text(a["level"], "bp" if SHOWS.get(show, SHOWS["raw"])[0] == "bp" else show, loc).lstrip("+")
        head = {"open": "açılıştan", "ref": "referanstan", "window": "%s dk içinde" % a.get("minutes"),
                "set": "kurulduğundan (%s)" % value_text(a.get("base"), show, loc)}.get(mode, mode)
        return "%s %s %s" % (head, DIRS.get(a.get("op"), a.get("op")), size)

    def measure_text(self, a: Dict[str, Any], measure: Optional[float], loc=None) -> str:
        mode = a.get("mode") or "level"
        show = a.get("show") or "raw"
        if mode == "level":
            return value_text(measure, show, loc)
        if mode == "z":
            return z_text(measure, loc)
        return move_text(measure, "bp" if SHOWS.get(show, SHOWS["raw"])[0] == "bp" else show, loc)

    # ------------------------------------------------------------------ the tick (calculation thread)
    def tick(self) -> List[Dict[str, Any]]:
        """Read every watched subject, every armed alarm's and (every few seconds) the heat map's; keep the day's
        open, high, low, path and last hour; fire the alarms whose condition holds.  Returns what fired now."""
        today = self.svc.today_iso()
        now_dt = _now()
        now = now_dt.strftime("%H:%M:%S")
        epoch = now_dt.timestamp()
        if today != self.day:
            self.day = today
            self.days = {}
            opened = self.svc.store.get("watch.open:%s" % today, {})
            for key, v in (opened.items() if isinstance(opened, dict) else ()):
                user, _, subj = key.partition("#")
                if subj and type(v) is float:
                    self.days[(user, subj)] = {"open": v, "high": v, "low": v, "last": v, "moved": None, "path": [], "recent": []}
        readers: Dict[str, Watch._Reader] = {}
        values: Dict[Tuple[str, str], Optional[float]] = {}

        def reader(user: str) -> "Watch._Reader":
            rd = readers.get(user)
            if rd is None:
                rd = readers[user] = self._Reader(self, user or None)
            return rd

        def value(user: str, subject: Dict[str, Any]) -> Optional[float]:
            key = (user, self.key(subject))
            if key not in values:
                try:
                    values[key] = self.resolve(subject, reader(user))[0]
                except Exception:  # noqa: BLE001 - a subject that cannot be read is not watched this time
                    values[key] = None
            return values[key]

        tracked: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for user, items in self._items_all().items():
            for i in items or []:
                tracked[(user, self.key(i["subject"]))] = i["subject"]
        alarms = self.alarms()
        for a in alarms:
            if a.get("active"):
                tracked.setdefault((a.get("user") or "", self.key(a["subject"])), a["subject"])
        if self._heat_day == today and epoch - self._heat_at >= HEAT_EVERY:
            self._heat_at = epoch
            try:
                for subj in self.heat_subjects(reader("")):
                    tracked.setdefault(("", self.key(subj)), subj)
            except Exception:  # noqa: BLE001 - the heat map is not worth a failed round
                pass
        new_opens: Dict[str, float] = {}
        cutoff = epoch - RECENT
        # the last hour's readings: only of what an armed "within the last minutes" alarm looks at (a live market
        # moves every second: an hour of it, of every point, is not worth its memory)
        windowed = {(a.get("user") or "", self.key(a["subject"])) for a in alarms if a.get("active") and a.get("mode") == "window"}
        for (user, key), subj in tracked.items():
            v = value(user, subj)
            if type(v) is not float:
                continue
            d = self.days.get((user, key))
            if d is None:
                d = self.days[(user, key)] = {"open": v, "high": v, "low": v, "last": None, "moved": None, "path": [], "recent": []}
                new_opens["%s#%s" % (user, key)] = v
            if d["last"] is not None and v != d["last"]:
                d["moved"] = now
            if user and (d["last"] is None or v != d["last"] or not d["path"]):
                d["path"].append((now, v))
                if len(d["path"]) > MAX_PATH:
                    d["path"] = d["path"][:1] + d["path"][1::2]          # thinned: the open stays
            recent = d.setdefault("recent", [])
            if (user, key) in windowed:
                if not recent or recent[-1][1] != v:
                    recent.append((epoch, v))
                while len(recent) >= 2 and recent[1][0] <= cutoff:
                    recent.pop(0)                                     # (the level the hour began with stays)
            elif recent:
                d["recent"] = []
            d["last"] = v
            d["high"], d["low"] = max(d["high"], v), min(d["low"], v)
        if new_opens:
            opened = self.svc.store.get("watch.open:%s" % today, {})
            opened = opened if isinstance(opened, dict) else {}
            opened.update(new_opens)
            self.svc.store.put("watch.open:%s" % today, opened)
        fired: List[Dict[str, Any]] = []
        changed = False
        desk = getattr(self.svc, "desk_alarms", None)
        for a in alarms:
            if not a.get("active"):
                continue
            user = a.get("user") or ""
            v = value(user, a["subject"])
            if type(v) is not float:
                continue
            try:
                measure, hit = self._alarm_state(a, v, user, reader(user), epoch)
            except Exception:  # noqa: BLE001
                continue
            if v != a.get("last"):
                a["last"] = v
                changed = True
            if (a.get("mode") or "level") == "z" and measure is not None and measure != a.get("last_z"):
                a["last_z"] = measure
                changed = True
            if hit:
                a["active"], a["fired_at"], a["fired_value"] = False, today + " " + now, v
                show = a.get("show") or "raw"
                fired.append({"id": a["id"], "user": a.get("user"), "label": a["label"], "subject": a["subject"], "op": a["op"],
                              "mode": a.get("mode") or "level", "level": a["level"], "value": v, "measure": measure, "time": now,
                              "note": a.get("note", ""), "level_text": value_text(a["level"], show) if (a.get("mode") or "level") == "level"
                              else self.cond_text(a), "value_text": value_text(v, show), "condition": self.cond_text(a),
                              "measure_text": self.measure_text(a, measure), "desk": bool(a.get("desk")), "by": a.get("by")})
                changed = True
        if changed:
            self._put_alarms(alarms)
        mine = [e for e in fired if not e["desk"]]
        if mine:
            log = self.fired(today)
            seq = max([int(e.get("seq") or 0) for e in log] or [0])
            for e in mine:
                seq += 1
                e["seq"] = seq
            self.svc.store.put("watch.fired:%s" % today, (log + mine)[-500:])
        ours = [e for e in fired if e["desk"]]
        if ours and desk is not None:
            desk.fired(ours)                # the desk's: into the day's log of the desk alarms, for everyone
        try:
            self.record()
        except Exception:  # noqa: BLE001 - the closes are kept at the next round
            pass
        return fired

    # ------------------------------------------------------------------ what the page shows
    def alarm_rows(self, alarms: List[Dict[str, Any]], user: str, rd: "Watch._Reader", loc) -> List[Dict[str, Any]]:
        """Alarms as the page lists them: the value now, the measure (move, z), the condition, what is left to it."""
        out = []
        for a in alarms:
            v, show, _ = self.resolve(a["subject"], rd)
            show = a.get("show") or show
            name, k = SHOWS.get(show, SHOWS["raw"])
            mode = a.get("mode") or "level"
            measure = None
            if type(v) is float:
                try:
                    measure = self._alarm_state(a, v, user, rd)[0]
                except Exception:  # noqa: BLE001
                    measure = None
            if mode == "level":
                distance = (a["level"] - v) * k if type(v) is float else None
                dist_text = move_text(distance, "bp" if name == "bp" else show, loc) if distance is not None else ""
            elif mode == "z":
                distance = a["level"] - measure if type(measure) is float else None
                dist_text = ("%s z" % z_text(distance, loc)) if distance is not None else ""
            else:
                left = None
                if type(measure) is float:
                    left = a["level"] - (abs(measure) if a.get("op") == "any" else (measure if a.get("op") == "up" else -measure))
                distance = left
                dist_text = move_text(left, "bp" if name == "bp" else show, loc).lstrip("+") if left is not None else ""
            out.append(dict(a, mode=mode, now=v, unit_name=name, what=self.label(a["subject"]), detail=self.explain(a["subject"], rd, v),
                            now_text=value_text(v, show, loc), measure=measure, measure_text=self.measure_text(a, measure, loc),
                            condition=self.cond_text(a, loc), level_text=value_text(a["level"], show, loc) if mode == "level" else self.cond_text(a, loc),
                            fired_text=value_text(a.get("fired_value"), show, loc), distance=distance, distance_text=dist_text))
        return out

    def desk_rows(self, loc) -> List[Dict[str, Any]]:
        """The desk's alarms as the page lists them (read on the market's values)."""
        return self.alarm_rows(self.desk_list(), "", self._Reader(self, None), loc)

    def snapshot(self, user: str, loc, days: int = 60) -> Dict[str, Any]:
        days = days if days in Z_DAYS else 60
        rd = self._Reader(self, user)
        out_items = []
        for i in self.items(user):
            v, show, text = self.resolve(i["subject"], rd)
            d = dict(self.days.get((user, self.key(i["subject"]))) or {})
            opened = self.day_open(user, self.key(i["subject"]))
            if opened is not None:
                d["open"] = opened
                if type(d.get("high")) is float:
                    d["high"], d["low"] = max(d["high"], opened), min(d["low"], opened)
            name, k = SHOWS.get(show, SHOWS["raw"])

            def chg(a: Any) -> Optional[float]:
                return (v - a) * k if type(v) is float and type(a) is float else None

            def txt(x: Any) -> str:
                return value_text(x, show, loc)

            try:
                zi = self.zinfo(i["subject"], v, days, rd)
            except Exception:  # noqa: BLE001 - no past is no z-score
                zi = {"z": None, "pct": None, "n": 0, "need": min_closes(days), "days": days, "source": ""}
            z = dict(zi, mean_text=txt(zi.get("mean")), min_text=txt(zi.get("min")), max_text=txt(zi.get("max")),
                     sd_text=move_text(zi["sd"] * k, "bp" if name == "bp" else show, loc).lstrip("+") if zi.get("sd") is not None else "",
                     z_text=z_text(zi.get("z"), loc))
            out_items.append(dict(i, now=text or txt(v), value=v, show=show, open=d.get("open"), high=d.get("high"),
                                  low=d.get("low"), open_text=txt(d.get("open")), high_text=txt(d.get("high")),
                                  low_text=txt(d.get("low")), base_text=txt(i.get("base")), moved=d.get("moved"),
                                  change=chg(d.get("open")), since_base=chg(i.get("base")), unit_name=name,
                                  what=self.label(i["subject"]), detail=self.explain(i["subject"], rd, v),
                                  path=[p[1] for p in d.get("path") or []][-240:], z=z))
        alarms = self.alarm_rows(self.alarms(user), user, rd, loc)
        notes = self.svc.store.get("desk.notes:%s" % self.svc.today_iso(), {})
        return {"items": out_items, "alarms": alarms, "fired": [e for e in self.fired() if e.get("user") == user],
                "notes": notes if isinstance(notes, dict) else {}, "presets": [{"group": g, "items": [self.label(s) for s in p]} for g, p in PRESETS],
                "shows": {k: v[0] for k, v in SHOWS.items()}, "ops": OPS, "modes": MODES, "dirs": DIRS, "z_days": list(Z_DAYS),
                "days": days, "day": self.svc.today_iso()}
