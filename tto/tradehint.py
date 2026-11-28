"""A price on a page as a trade (*fiyattan işlem*): the views' ``"trade"`` hint, and what Günlük İşlemler's entry form
is filled with when a price cell is right-clicked ("İşlem gir").

A table opts in with ``"trade"`` in its page definition (the grammar is in :mod:`tto.views`).  The browser gets the
table's price cells with the table (:func:`client`): which cells offer "İşlem gir", and for a price there is no form for
(a VİOP contract) why not.  A click asks the server (:func:`prefill`).  The instrument and the dates come from the
clicked row's own cells as the user sees them now - a tenor, a value date, a meeting's two days, an ISIN - never from
the row's place, which moves (the PPK calendar, the VİOP roll, the bond lists); the pair is the table's, or the clicked
column's own in a table of two pairs (TOPLU FORWARD's USDTRY and EURTRY columns: ``"pairs"``).  The price is the one
clicked, as it was on screen.  The side follows the column, as the desk quotes it: at its bid the desk buys (the currency forward, the
bond; an OIS rate: PAY - Broker Chat's rule for a quote of ours), at its ask it sells; a mid leaves the side to the
user.  The answer is what ``ctx.openTrade`` (the browser) takes: nothing is saved until the user saves.

The OIS lists (the desk, 28.11.2026: "A - Yildizlilari yap", A1): an OIS price is an outright, a spread, a fly, a FRA, a
meeting swap or a meeting spread - each named in its row the way OIS · PPK's lists name it (:func:`ois_name`: "2Y",
"1M / 18M", "2M/3M/6M", "18M6M" / "Spot3M", "MPC1 / MPC2"); ``"strategy": "auto"`` takes the strategy from the name
itself (Masa's signals: spreads, flies and FRAs in one table), ``"tenor_cols"`` a price's own name column.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import blotter as bl
from .inputs import parse_date, parse_number
from .xl.values import serial_to_date

#: what a price cell holds -> (the form's product, a forward's pricing basis)
WHATS = {"sp": ("fwd", "SP"), "fwd": ("fwd", "FWD"), "try": ("fwd", "TRY"), "ret": ("fwd", "RET"),
         "ois": ("ois", None), "price": ("bond", None), "yield": ("bond", None), "none": (None, None)}
SIDES = ("bid", "ask")
#: the OIS strategies a price can be filled as, with their [buy, sell] sides: the buyer pays the rate - a spread's buyer
#: pays the long leg (a steepener), a fly's the body, a meeting spread's the later window ("PAY K+1 / REC K", OIS_MAIN's
#: own word for it, kept upper case as the form keeps it)
OIS_SIDES = {"outright": ("PAY", "RECEIVE"), "mpc": ("PAY", "RECEIVE"), "fra": ("PAY", "RECEIVE"),
             "spread": ("STEEPENER", "FLATTENER"), "fly": ("PAY GÖVDE", "REC GÖVDE"),
             "mpcspread": bl.MPC_SPREAD_SIDES}
#: the strategies whose instrument is named in a row's cell (``tenor_col``); "auto": the name says which (:func:`ois_name`)
NAMED = ("outright", "spread", "fly", "fra", "mpcspread", "auto")
#: OIS_MAIN's MPC OIS table: the k-th meeting period from B(83 + k) to C(83 + k) - where a meeting spread "MPCk / MPCk+1"
#: of MPC SPREAD finds its three days (the meetings as the table has them now, as the row's own name says them)
MPC_TABLE = ("OIS_MAIN", 84, 99)
_KEY = re.compile(r"^[A-Z]{1,3}\d*$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_TENOR = re.compile(r"^\d{1,3}[WMY]$")
_FRA = re.compile(r"^(SPOT|\d{1,3}[MY])(\d{1,3}[MY])$")
_MPC = re.compile(r"^MPC(\d{1,2})$")


class HintError(ValueError):
    """A price that cannot be filled as a trade - said to the user."""


def _months(tenor: str) -> int:
    return int(tenor[:-1]) * (12 if tenor[-1] == "Y" else 1)


def ois_name(text: Any) -> Tuple[str, Dict[str, Any]]:
    """An OIS instrument as OIS · PPK's lists name it -> ``(strategy, what the form takes)``: "2Y" an outright
    (``tenors``), "1M / 18M" a spread (short / long), "2M/3M/6M" a fly (wing / body / wing), "18M6M" / "Spot3M" / "1Y1Y"
    a FRA - its start and its length (``months``: [start, end] from the OIS spot) -, "MPC1 / MPC2" a meeting spread
    (``mpc``: [k, k + 1], meetings counted as OIS_MAIN's MPC table counts them).  :class:`HintError` for a name that is
    none of them, or a tenor the entry form does not list."""
    s = " ".join(str(text if text is not None else "").split()).upper()
    parts = [p.strip() for p in s.split("/")] if s else []
    if len(parts) == 2 and all(_MPC.match(p) for p in parts):
        k1, k2 = (int(_MPC.match(p).group(1)) for p in parts)
        if k1 < 1 or k2 != k1 + 1:
            raise HintError("%s: ardışık iki toplantı değil" % s)
        return "mpcspread", {"mpc": [k1, k2]}
    if len(parts) == 1:
        m = _FRA.match(parts[0])
        if m:
            start = 0 if m.group(1) == "SPOT" else _months(m.group(1))
            end = start + _months(m.group(2))
            if start % 3 or end % 3 or end > 120:
                raise HintError("%s: FRA ayları 3'ün katı olmalı (bitiş en çok 120 ay)" % s)
            return "fra", {"months": [start, end]}
    if 1 <= len(parts) <= 3 and all(parts):
        missing = [p for p in parts if p not in bl.OIS_TENORS]
        if missing:
            raise HintError("%s: OIS vadesi değil" % ", ".join(missing))
        return ("outright", "spread", "fly")[len(parts) - 1], {"tenors": parts}
    raise HintError("%s: OIS enstrümanı okunamadı" % (s or "ad yok"))


def parse(text: Any) -> Tuple[str, Optional[str]]:
    """A cell's entry in the hint: ``"sp bid"`` -> ``("sp", "bid")``, ``"ois"`` -> ``("ois", None)`` (a mid)."""
    parts = str(text or "").split()
    if not parts or parts[0] not in WHATS or len(parts) > 2 or (len(parts) == 2 and parts[1] not in SIDES):
        raise ValueError("fiyat hücresi anlaşılamadı: %r" % (text,))
    return parts[0], parts[1] if len(parts) == 2 else None


def _ois_entry(text: Any) -> bool:
    try:
        return parse(text)[0] == "ois"
    except ValueError:
        return False


def check(hint: Any) -> List[str]:
    """What is wrong with a table's hint (``[]``: nothing) - every page definition is checked with it."""
    if not isinstance(hint, dict):
        return ["trade bir nesne olmalı"]
    cells = hint.get("cells")
    if cells is None:
        return []                                        # (the header's "İşlem gir" dialog only: no price cells)
    if not isinstance(cells, dict) or not cells:
        return ["cells boş"]
    out: List[str] = []
    whats = set()
    for key, text in cells.items():
        if not isinstance(key, str) or not _KEY.match(key):
            out.append("hücre anahtarı bir sütun (H) ya da hücre (F173) olmalı: %r" % (key,))
        try:
            what, side = parse(text)
        except ValueError as exc:
            out.append(str(exc))
            continue
        whats.add(what)
        if what == "yield" and (side is None or not (hint.get("yield_price") or {}).get(side)):
            out.append("getirinin fiyat sütunu yok (yield_price): %s" % key)
    for k in ("first", "last"):
        if k in hint and (isinstance(hint[k], bool) or not isinstance(hint[k], int)):
            out.append("%s bir satır numarası olmalı" % k)
    pairs = hint.get("pairs")
    if pairs is not None:
        if not isinstance(pairs, dict) or not pairs:
            out.append("pairs bir nesne olmalı")
            pairs = {}
        for key, pair in pairs.items():
            try:
                forward = key in cells and WHATS[parse(cells[key])[0]][0] == "fwd"
            except ValueError:
                forward = True                           # (the cell's own entry says what is wrong with it)
            if not forward:
                out.append("pairs: %r bir forward fiyat hücresinin anahtarı değil" % (key,))
            try:
                if not isinstance(pair, str) or not pair.strip():
                    raise bl.TradeError("parite yok: %r" % (key,))
                bl.pair_of(pair)
            except bl.TradeError as exc:
                out.append("pairs: %s" % exc)
    if whats & {"sp", "fwd", "try", "ret"}:
        try:
            bl.pair_of(hint.get("pair") or "USDTRY")
        except bl.TradeError as exc:
            out.append(str(exc))
        if len([k for k in ("date", "date_col", "tenor_col") if hint.get(k)]) != 1:
            out.append("forward valörü: date, date_col ya da tenor_col (yalnız biri)")
    names = hint.get("tenor_cols")
    if names is not None:
        if not isinstance(names, dict) or not names:
            out.append("tenor_cols bir nesne olmalı")
            names = {}
        for key, col in names.items():
            try:
                ois = key in cells and parse(cells[key])[0] == "ois"
            except ValueError:
                ois = True                               # (the cell's own entry says what is wrong with it)
            if not ois:
                out.append("tenor_cols: %r bir OIS fiyat hücresinin anahtarı değil" % (key,))
            if not isinstance(col, str) or not re.match(r"^[A-Z]{1,3}$", col):
                out.append("tenor_cols: %r bir sütun olmalı" % (col,))
    if "ois" in whats:
        strategy = hint.get("strategy") or "outright"
        if strategy not in OIS_SIDES and strategy != "auto":
            out.append("OIS stratejisi: %r" % strategy)
        elif strategy in NAMED and not hint.get("tenor_col") and not all(
                k in (names or {}) for k, t in cells.items() if _ois_entry(t)):
            out.append("OIS %s: tenor_col gerekli (enstrümanın adı satırın hangi sütununda)" % strategy)
        elif strategy == "mpc" and not (hint.get("start_col") and hint.get("end_col")):
            out.append("OIS MPC: start_col ve end_col gerekli")
    if whats & {"price", "yield"} and not hint.get("isin_col"):
        out.append("tahvil: isin_col gerekli")
    if "none" in whats and not hint.get("why"):
        out.append("karşılığı olmayan fiyat: why gerekli")
    return out


def client(hint: Any, view_id: str, panel_id: str) -> Optional[Dict[str, Any]]:
    """What the browser gets with the table (``data.trade``): its page and table, and its price cells -
    ``{key: ""}`` a trade, ``{key: why}`` a price there is no form for - with the rows a column's entry holds for
    (``first`` / ``last``, the sheet's row numbers).  ``None``: the table has no price cells."""
    cells = hint.get("cells") if isinstance(hint, dict) else None
    if not cells:
        return None
    why = hint.get("why") or ""
    out: Dict[str, Any] = {"view": view_id, "panel": panel_id,
                           "cells": {k: why if parse(t)[0] == "none" else "" for k, t in cells.items()}}
    for k in ("first", "last"):
        if isinstance(hint.get(k), int):
            out[k] = hint[k]
    return out


def lookup(hint: Dict[str, Any], row: int, col: str) -> Optional[Tuple[str, Optional[str]]]:
    """The hint's entry for a cell (``row``: the sheet's row number, ``col``: the column's letters): an entry of the
    cell itself (``"F173"``), else its column's for a row from ``first`` to ``last``.  ``None``: no price."""
    cells = hint.get("cells") or {}
    text = cells.get("%s%d" % (col, row))
    if text is None:
        text = cells.get(col)
        if text is None or row < hint.get("first", row) or row > hint.get("last", row):
            return None
    return parse(text)


def pair_at(hint: Dict[str, Any], row: int, col: str) -> str:
    """The currency pair of a forward price cell: its own in ``"pairs"`` (keyed as ``cells`` is: the cell, else its
    column - a table of both pairs, TOPLU FORWARD's USDTRY and EURTRY columns), else the table's ``"pair"``."""
    pairs = hint.get("pairs") or {}
    return bl.pair_of(pairs.get("%s%d" % (col, row)) or pairs.get(col) or hint.get("pair") or "USDTRY")


def _date(v: Any) -> Optional[float]:
    if type(v) is float and v > 0:
        return v
    if isinstance(v, str) and v.strip():
        d = parse_date(v)
        return float(d) if d is not None else None
    return None


def _text(v: Any) -> str:
    return " ".join(str(v if v is not None else "").split())


def prefill(hint: Dict[str, Any], row: int, col: str, text: Any, read: Callable[[str], Any],
            tenor_date: Callable[[str, str], Optional[float]], lang: str = "tr", note: str = "") -> Dict[str, Any]:
    """The trade a price cell is: what Günlük İşlemler's form is filled with (the spec ``ctx.openTrade`` takes).

    ``row`` / ``col``: the cell (the sheet's row number and the column's letters); ``text``: the price as the user saw
    it - the form takes it as typed; ``read(ref)``: a cell's value as the user sees it (``"B45"`` on the table's sheet,
    ``"MASA!E60"`` on another); ``tenor_date(tenor, pair)``: a tenor's value date from the pair's spot; ``note``: where
    the price came from (the form's "Not").  Raises :class:`HintError` for a cell that is no price, or a row without
    what the trade needs."""
    hit = lookup(hint, row, col)
    if hit is None:
        raise HintError("bu hücre bir fiyat değil")
    what, side = hit
    product, basis = WHATS[what]
    if product is None:
        raise HintError(hint.get("why") or "bu fiyatın Günlük İşlemler'de karşılığı yok")
    value = _text(text)
    if parse_number(value, lang, prefer_decimal=basis != "SP") is None:
        raise HintError("fiyat okunamadı: %r" % value)
    note = note[:200]

    def cell(c: str) -> Any:
        return read("%s%d" % (c, row))

    buy = None if side is None else side == "bid"
    if product == "fwd":
        pair = pair_at(hint, row, col)
        if hint.get("tenor_col"):
            tenor = _text(cell(hint["tenor_col"])).upper()
            when = tenor_date(tenor, pair) if _TENOR.match(tenor) else None
            if when is None:
                raise HintError("%s: forward valörü değil" % (tenor or "vade yok"))
        else:
            when = _date(read(hint["date"]) if hint.get("date") else cell(hint["date_col"]))
            if when is None:
                raise HintError("satırda valör tarihi yok")
        if basis == "RET":
            # the RET curve prices the forward itself: its bid / mid / ask at the value date (the rate clicked, on a node)
            basis, value = {True: "RET_BID", False: "RET_ASK", None: "RET_MID"}[buy], ""
        return {"kind": "fwd", "pair": pair, "dir": {True: "B", False: "S", None: None}[buy],
                "date": serial_to_date(when).strftime("%d.%m.%Y"), "basis": basis, "value": value, "note": note}
    if product == "ois":
        strategy = hint.get("strategy") or "outright"
        out: Dict[str, Any] = {"kind": "ois", "level": value, "note": note}
        if strategy == "mpc":
            start, end = _date(cell(hint["start_col"])), _date(cell(hint["end_col"]))
            if start is None or end is None or end <= start:
                raise HintError("satırda toplantı tarihleri yok")
            out.update({"start": start, "end": end})
        else:
            # the instrument as the row names it ("2Y", "1M / 18M", "2M/3M/6M", "18M6M", "MPC1 / MPC2"): the price's
            # own name column, else the table's
            names = hint.get("tenor_cols") or {}
            name = _text(cell(names.get("%s%d" % (col, row)) or names.get(col) or hint["tenor_col"]))
            if strategy == "outright" and name.upper() not in bl.OIS_TENORS:
                raise HintError("%s: OIS vadesi değil" % (name or "vade yok"))
            got, fields = ois_name(name)
            if strategy != "auto" and got != strategy:
                raise HintError("%s: %s değil" % (name, {"outright": "vade", "spread": "spread", "fly": "fly", "fra": "FRA",
                                                        "mpcspread": "MPC spread"}.get(strategy, strategy)))
            strategy = got
            if strategy == "mpcspread":
                # the three days of the two meeting periods, as OIS_MAIN's MPC OIS table has them now
                sheet, first, last = MPC_TABLE
                k1 = fields["mpc"][0]
                if first + k1 > last:
                    raise HintError("%s: MPC OIS tablosunda yok" % name)
                days = [_date(read("%s!B%d" % (sheet, first + k1 - 1))), _date(read("%s!C%d" % (sheet, first + k1 - 1))),
                        _date(read("%s!C%d" % (sheet, first + k1)))]
                if any(d is None for d in days) or not days[0] < days[1] < days[2]:
                    raise HintError("%s: toplantı tarihleri yok" % name)
                out.update({"start": days[0], "mid": days[1], "end": days[2]})
            else:
                out.update(fields)
        out["strategy"] = strategy
        out["side"] = None if buy is None else OIS_SIDES[strategy][0 if buy else 1]
        return out
    isin = "".join(_text(cell(hint["isin_col"])).split()).upper()
    if not _ISIN.match(isin):
        raise HintError("satırda kâğıt (ISIN) yok")
    if what == "yield":
        # a yield is dealt at its own price: the same side's price of the row
        px = cell(hint["yield_price"][side])
        if type(px) is not float or px <= 0:
            raise HintError("getirinin fiyatı yok")
        note = (note + " · " if note else "") + "getiri " + value
        value = "%.3f" % px if lang == "en" else ("%.3f" % px).replace(".", ",")
    return {"kind": "bond", "dir": {True: "B", False: "S", None: None}[buy], "instrument": isin, "price": value,
            "note": note[:200]}
