"""What a user typed, read for the shell (the desk, 28.11.2026): on which page each typed cell is, the values typed over
a formula ("elle değer": the top bar's personal-state badge, A6) and the market levels typed on an earlier day (A7:
"Dünden kalan yazılmış değerler işaretli" - "Girdilerim" with each value's day, a page's "N girdi dünden · temizle").

A market level is a value typed for today's market - a spot, a spread, a meeting's rate, a quote, a pasted position -
that goes stale overnight; a setting (a curve chosen, a horizon, a date, a list's choice) is not one, wherever it
stands.  :data:`MARKET` names them by place (a range, or a sheet of the dashboard's own whose inputs are all market
levels); of those, only numbers count - a text (the forward matrix's spread source) or a date (its value dates) is a
setting.  ``tests/test_toplu_kabuk.py`` checks that every range named is an input of its page, so a place that moves is
found.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .xl.model import COLS, parse_a1, parse_range
from .xl import numfmt

#: the market levels a user (or the desk) types: (book, "Sheet!A1:B2" or a whole "Sheet", what it is) - the first that
#: holds a cell names it
MARKET: Tuple[Tuple[str, str, str], ...] = (
    ("tto", "VIOP!AA9:AA10", "Manuel spot (ortak)"),
    ("tto", "Forward!F2:G2", "Forward spot (elle)"),
    ("tto", "EK_FWD!D4:E14", "Forward kotasyon spread'i"),
    ("tto", "EK_FWD!D103:E113", "Forward kotasyon spread'i (EURTRY)"),
    ("tto", "EK_FWD", "Forward kotasyon / valör faizi (elle)"),
    ("tto", "EK_PPK!G3:G18", "MPC OIS (elle)"),
    ("tto", "EK_PPK!S3:S17", "Elle spread (bp)"),
    ("tto", "EK_PPK", "PPK adımı (elle)"),
    ("sofr", "SOFR_FOMC!P74:P83", "WIRP (manuel)"),
    ("sofr", "SOFR_FOMC!AB74:AB83", "Pencere OIS (elle)"),
    ("sofr", "SOFR_FOMC!D49:D68", "Manuel kota (%)"),
    ("tto", "EK_TARIH!N5:N104", "Kote %"),
    ("tto", "EK_TARIH!C110", "Kote %"),
    ("tto", "DV01_RISK!C6:C25", "Pozisyon DV01 (yapıştırılan)"),
    ("tto", "DV01_RISK!X33:Y52", "VaR · Onshore / TLREF DV01 (yapıştırılan)"),
    ("tto", "DV01_RISK!AA33:AA52", "VaR · Offshore DV01 (yapıştırılan)"),
)
#: input kinds that are settings, whatever their place (views/__init__.py: "kind")
SETTING_KINDS = ("date", "text", "list", "check")


def _split(ref: str) -> Tuple[str, str]:
    sheet, _, addr = ref.rpartition("!")
    return sheet.strip("'"), addr


def _places() -> List[Tuple[str, str, Optional[Tuple[int, int, int, int]], str]]:
    out = []
    for book, where, label in MARKET:
        if "!" in where:
            sheet, addr = _split(where)
            rng = parse_range(addr if ":" in addr else "%s:%s" % (addr, addr))
        else:
            sheet, rng = where, None
        out.append((book, sheet, rng, label))
    return out


_PLACES = _places()


def market_label(book_id: str, ref: str) -> Optional[str]:
    """What a typed cell is when it is one of the market levels (:data:`MARKET`), else ``None``."""
    sheet, addr = _split(ref)
    try:
        rc = parse_a1(addr)
    except (ValueError, KeyError):
        return None
    r, c = divmod(rc, COLS)
    for book, sh, rng, label in _PLACES:
        if book != book_id or sh != sheet:
            continue
        if rng is None or (rng[0] <= r <= rng[2] and rng[1] <= c <= rng[3]):
            return label
    return None


def is_level(value: Any, kind: Optional[str], fmt: Optional[str]) -> bool:
    """Whether a typed value reads as a market level: a number, of an input that is no setting (a date, a text, a list's
    choice, a tick box) and not shown as a date."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if kind in SETTING_KINDS:
        return False
    return not (fmt and numfmt.is_date_format(fmt))


class PageIndex(object):
    """Which pages (and tables) show a cell: every table / notes panel of every view, by book and sheet."""

    def __init__(self, views: List[Dict[str, Any]]) -> None:
        self.by: Dict[Tuple[str, str], List[Tuple[int, int, int, int, str, str, bool]]] = {}
        for v in views:
            for p in v.get("panels", []):
                if p.get("type") not in ("table", "notes") or not p.get("range"):
                    continue
                sheet = p.get("sheet") or v.get("sheet")
                try:
                    r1, c1, r2, c2 = parse_range(p["range"])
                except (ValueError, KeyError):
                    continue
                self.by.setdefault((v["book"], sheet), []).append((r1, c1, r2, c2, v["id"], p.get("id"), bool(p.get("hidden"))))
        for lst in self.by.values():
            lst.sort(key=lambda x: x[6])                 # (a table on screen before a helper table)

    def pages(self, book_id: str, ref: str, skip: Optional[set] = None) -> List[Dict[str, str]]:
        """The pages showing a cell, ``[{"view", "panel"}]`` - a page once (its first table that shows it); ``skip``:
        pages the user does not get."""
        sheet, addr = _split(ref)
        try:
            r, c = divmod(parse_a1(addr), COLS)
        except (ValueError, KeyError):
            return []
        out, seen = [], set()
        for r1, c1, r2, c2, vid, pid, _ in self.by.get((book_id, sheet), ()):
            if r1 <= r <= r2 and c1 <= c <= c2 and vid not in seen and not (skip and vid in skip):
                seen.add(vid)
                out.append({"view": vid, "panel": pid})
        return out
