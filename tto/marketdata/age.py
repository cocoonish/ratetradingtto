"""How old a quote is: when the price each market cell shows last changed, and which have not moved for a while in
market hours (the desk, 28.11.2026: proposal C4, "Kotanın yaşı" - the "BAYAT VERİ" badge catches only the whole feed).

* **Kept in memory** by the provider (``Provider.quote_times``): when each price quote's value last changed - its
  answer, a tick of its subscription, a poll that brought another value (``bloomberg.py`` ``_Item.at``; in the helper
  process's case the values as they reach the dashboard, ``bbg_process.py``).  Nothing is asked of Bloomberg for it:
  its own ``LAST_UPDATE`` would be a request per quote.  Replay has none (nothing moves there): no age is shown.
* **A market cell** is a cell whose formula calls Bloomberg for a price (``BDP`` of a bid, an ask, a mid or a last price,
  no overrides: ``bloomberg.PRICE_FIELDS``), by itself or in a chain (``IFERROR(BDP(<GFOF> "MID"), BDP(<BGN> "PX_LAST"))``).
  Its time (:meth:`CellQuotes.at`) is that of the quote whose value it shows - else, a cell that works one out of
  several (a mid of a bid and an ask), the latest of them.  The page gets it as the cell's ``qa`` (epoch seconds,
  tto/render.py); the cell's tooltip says "son değişim 10:42 (37 dk)" (``static/js/quoteage.js``).
* **Old** (:func:`is_old`): in market hours (the desk's days, ``ops`` ``market_open`` – ``market_close``) a quote whose
  value has not changed for ``quote_old`` minutes (a desk setting, ``ops.DEFAULTS``; 0: never) of today's market -
  counted from today's opening when it last changed before it: a quote that did not move overnight is not old at 09:01.
  The page fades such a cell; the data status counts them (``ops.Ops.quotes``).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .bloomberg import PRICE_FIELDS, RT_FIELDS
from .replay import _KeyCapture, _NoDeps

_CAPTURE = _KeyCapture()
_NODEPS = _NoDeps()


def is_price(key: Any) -> bool:
    """A key of a price quote: ``("BDP", security, FIELD, ())`` with a price field and no overrides."""
    return (type(key) is tuple and len(key) == 4 and key[0] == "BDP" and not key[3]
            and RT_FIELDS.get(str(key[2]).upper()) in PRICE_FIELDS)


def market_minutes(at: float, now: _dt.datetime, opening: _dt.time) -> float:
    """Minutes of today's market since ``at`` (epoch seconds) - from today's ``opening`` when ``at`` is earlier."""
    start = _dt.datetime.combine(now.date(), opening).timestamp()
    return max(0.0, now.timestamp() - max(float(at), start)) / 60.0


def is_old(at: Optional[float], now: _dt.datetime, minutes: int, opening: _dt.time, in_market: bool) -> bool:
    """Whether a quote that last changed at ``at`` is old now: in market hours, unchanged ``minutes`` market minutes."""
    return bool(in_market and minutes and minutes > 0 and at and market_minutes(at, now, opening) >= minutes)


class CellQuotes(object):
    """The price quotes of a workbook's market cells, and when the one a cell shows last changed (:meth:`at`).  Lives with
    the book's renderer (``Renderer.quotes``); used on the calculation thread, as the page is made."""

    def __init__(self, book, provider):
        self.book = book
        self.provider = provider
        self._cells: Optional[Set[Tuple[int, int]]] = None
        self._calls: Dict[int, List[Tuple[str, List[Optional[Callable]]]]] = {}

    def cells(self) -> Set[Tuple[int, int]]:
        """The cells of the book whose formula calls an add-in (worked out once: formulas do not change)."""
        if self._cells is None:
            from ..xl.engine import addin_cells
            self._cells = set(addin_cells(self.book.model))
        return self._cells

    def _compiled(self, tid: int) -> List[Tuple[str, List[Optional[Callable]]]]:
        """A formula's add-in calls, each with its arguments compiled (once per formula: shared by its cells)."""
        got = self._calls.get(tid)
        if got is None:
            from ..xl.compiler import ADDINS
            from ..xl.parser import parse_template, walk
            got = []
            try:
                compiler = self.book.engine.compiler
                for nd in walk(parse_template(self.book.model.templates[tid])):
                    if nd[0] == "func" and (nd[3] or nd[1] in ADDINS) and nd[1] != "BINTERPOL":
                        got.append((nd[1], [compiler.compile_node(a) if a[0] != "missing" else None for a in nd[2]]))
            except Exception:  # noqa: BLE001 - a formula that cannot be read shows no quote of ours
                got = []
            self._calls[tid] = got
        return got

    def keys(self, calc, si: int, r: int, c: int) -> List[Tuple]:
        """The price quotes a cell's formula asks for, its arguments as ``calc`` has them (the user's own source)."""
        from ..xl.model import COLS
        tid = self.book.model.sheets[si].fml.get(r * COLS + c)
        if tid is None:
            return []
        out = []
        for name, fns in self._compiled(tid):
            try:
                key = _CAPTURE.call(_NODEPS, name, si, r, c, [fn(calc, si, r, c) if fn is not None else None for fn in fns])
            except Exception:  # noqa: BLE001
                continue
            if is_price(key) and key not in out:
                out.append(key)
        return out

    def at(self, calc, si: int, r: int, c: int, value: Any) -> Optional[float]:
        """When the price the cell shows last changed (epoch seconds): the quote whose value is the cell's, else the
        latest of its quotes; ``None`` for no market cell, or a quote with no time (replay, no answer yet)."""
        keys = self.keys(calc, si, r, c)
        if not keys:
            return None
        try:
            times = self.provider.quote_times(keys)
        except Exception:  # noqa: BLE001 - an age is a hint: never a page that fails
            return None
        if not times:
            return None
        shown = [t for t, v in times.values() if v == value]
        return max(shown or [t for t, _v in times.values()])
