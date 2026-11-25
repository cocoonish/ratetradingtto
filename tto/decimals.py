"""Each user's own number of decimals in the tables of the workbook pages: a table's right-click menu on a selection
holding numbers - "Ondalık: 0 · 1 · 2 …", "Ondalık artır", "Ondalık azalt", "Ondalığı varsayılana döndür".

The desk, 25.11.2026: "İstediğim şeyleri seçip sağ tıklayıp decimal formatını yapabilmeliyim".

- **A display setting, each user's own** - as the columns they hide are: kept with the account (the store's key / value
  table, ``decimals.<user>``), so any browser they sign in from shows it; a reload, a restart and a new day keep it;
  nobody else's view changes.  Values, calculations, typed inputs, alarms and "Tam hassasiyetle kopyala" (the value to
  its last digit) are what they were; "Kopyala" copies what is shown.
- **Only the decimals change** (``numfmt.with_decimals``): a percent stays a percent, and so do the thousands separators,
  a scaling comma (``#,##0,,\\M``), the negatives' look and colour, a prefix or a suffix.  A cell whose format shows a
  date, a time or text is never set, and a number in it is never re-formatted.
- **Put on the answer, never on the page kept.**  A page is made once per calculation and kept - everybody without inputs
  of their own shares one (``Service.view_future``).  Each answer of a page (``Service._answer``: the page itself, the
  boxes of a launchpad, of the side drawer, of a window of its own) gets this user's cells re-formatted from the value it
  carries and the cell's own format (``Renderer.format_of``), on a copy of those cells: what is kept is never changed, so
  nothing reaches another user's answer.  The answer's ``as`` carries a mark of the user's setting (:meth:`Decimals.mark`):
  a browser whose tables are from before a change gets them whole again (``since`` holds only under the same mark) - the
  open page, its other tabs, the boxes and the user's other windows alike.
- **A place, not a row**: a setting belongs to its cell (``Sheet!A1``) and stays there when a list's rows move (a PPK /
  FOMC calendar change, a VİOP roll, a bond list: meetings.py, rowkeys.py move what was typed, never this) - decimals are
  a column's look (a rate column, a price column), whatever the list holds in it.
- **Temporary copies** (copies.py): what is set in a copy is the copy's own (the table is not changed); in its other cells
  the copy shows the table's setting - it follows the table, as its values do where nothing was typed in it; closing the
  copy drops its own.

In an answer a cell the user set is marked ``dp`` (its number of decimals) - and ``dpc`` in a copy where the copy's own
setting stands - for the menu and the cell's tooltip.
"""
from __future__ import annotations

import copy as _copy
import json
import re
import threading
import zlib
from typing import Any, Dict, List, Optional, Tuple

from .service import ServiceError
from .store import user_key
from .xl import numfmt
from .xl.model import COLS
from .xl.tokenizer import col_to_index

KEY = "decimals."                     # the store's key / value table: decimals.<user> -> {"books": ..., "copies": ...}
#: every cell one user may set (all tables, copies too), and the cells of one change
MAX_CELLS = 20000
MAX_PER_CHANGE = 5000
_ADDR = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
_LETTERS = re.compile(r"^[A-Z]{1,3}$")

#: sheet -> row -> column letters -> decimals (an answer looks at the rows its tables show only)
Cells = Dict[str, Dict[int, Dict[str, int]]]

TOO_MANY = "en fazla %d hücrenin ondalığını değiştirebilirsiniz - birkaç tablonun ondalığını varsayılana döndürün"


def _cells(sheets: Any) -> Cells:
    """The settings of a book or a copy as kept (``{"OIS_MAIN": {"B9": 3}}``), keyed for the answers."""
    out: Cells = {}
    for sheet, cells in sheets.items():
        rows: Dict[int, Dict[str, int]] = {}
        for addr, n in cells.items():
            m = _ADDR.match(addr)
            rows.setdefault(int(m.group(2)), {})[m.group(1)] = n
        out[sheet] = rows
    return out


class _State(object):
    """One user's settings, ready for the answers: by book, by copy; ``mark`` tells one setting from another."""

    __slots__ = ("books", "copies", "mark", "count")

    def __init__(self, raw: Dict[str, Any]):
        """``raw``: as kept, tidied (:func:`_tidy`)."""
        self.books: Dict[str, Cells] = {bid: _cells(s) for bid, s in (raw.get("books") or {}).items()}
        self.copies: Dict[str, Cells] = {cid: _cells(s) for cid, s in (raw.get("copies") or {}).items()}
        self.count = sum(len(c) for part in raw.values() for sheets in part.values() for c in sheets.values())
        text = json.dumps(raw, sort_keys=True, ensure_ascii=False)
        self.mark = "~%x" % (zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF)


def _tidy(raw: Any) -> Dict[str, Any]:
    """As kept: without what is not a setting, nor the sheets, books and copies left empty."""
    out: Dict[str, Any] = {}
    for part in ("books", "copies"):
        owners = raw.get(part) if isinstance(raw, dict) else None
        kept = {}
        for owner, sheets in owners.items() if isinstance(owners, dict) else ():
            s = {}
            for sheet, cells in sheets.items() if isinstance(sheets, dict) else ():
                c = {a: n for a, n in cells.items() if isinstance(a, str) and _ADDR.match(a) and type(n) is int
                     and 0 <= n <= numfmt.MAX_DECIMALS} if isinstance(cells, dict) else {}
                if c:
                    s[sheet] = c
            if s:
                kept[owner] = s
        if kept:
            out[part] = kept
    return out


class Decimals(object):
    """Every user's own decimals (``Service.decimals``).  Read once at the start, kept in memory: an answer of a page -
    on the web server's own thread or the calculation thread - never waits for the database."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self._raw: Dict[str, Dict[str, Any]] = {}             # user -> as kept
        self._states: Dict[str, _State] = {}                  # user -> for the answers (users with a setting only)
        try:
            kept = svc.store.kv_prefixed(KEY)
        except Exception:  # noqa: BLE001 - a store that cannot list them: nobody has one (a change keeps it again)
            kept = {}
        for key, raw in kept.items():
            if isinstance(raw, dict):
                self._keep(key[len(KEY):], raw)

    def _keep(self, user: str, raw: Dict[str, Any]) -> None:
        raw = _tidy(raw)
        self._raw[user] = raw
        st = _State(raw)
        if st.count:
            self._states[user] = st
        else:
            self._states.pop(user, None)

    def _state(self, user: Optional[str]) -> Optional[_State]:
        return self._states.get(user_key(user)) if user else None

    # ------------------------------------------------------------------ what the answers carry
    def mark(self, user: Optional[str]) -> str:
        """What the answer's ``as`` carries of the user's setting (``""``: none): a browser holding tables of another
        mark gets them whole (Service._answer)."""
        st = self._state(user)
        return st.mark if st is not None else ""

    def apply(self, user: Optional[str], book_id: Optional[str], locale: Optional[str],
              entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The panels of an answer (as the page keeps them) with the user's cells re-formatted: a new list, a new panel,
        table, row and cell wherever one changed - what the page keeps is never touched."""
        st = self._state(user)
        book = self.svc.books.get(book_id) if st is not None and book_id else None
        if book is None:
            return entries
        R = self.svc.renderers[book.id]
        loc = numfmt.get_locale(locale)
        cells = st.books.get(book.id) or {}
        out = []
        for e in entries:
            cp = e.get("copy") if isinstance(e, dict) else None
            own = st.copies.get(cp.get("id")) if isinstance(cp, dict) else None
            out.append(self._entry(e, book, R, cells, own or {}, loc) if cells or own else e)
        return out

    def _entry(self, e: Dict[str, Any], book, R, cells: Cells, own: Cells, loc) -> Dict[str, Any]:
        data = _table(e.get("data"), book, R, cells, own, loc)
        lead = e.get("lead")
        leads = None
        for k, ld in enumerate(lead if isinstance(lead, list) else ()):
            d = _table(ld.get("data") if isinstance(ld, dict) else None, book, R, cells, own, loc)
            if isinstance(ld, dict) and d is not ld.get("data"):
                leads = leads if leads is not None else list(lead)
                leads[k] = dict(ld, data=d)
        if data is e.get("data") and leads is None:
            return e
        e = dict(e, data=data) if data is not e.get("data") else dict(e)
        if leads is not None:
            e["lead"] = leads
        return e

    # ------------------------------------------------------------------ what the browser asks
    def listing(self, user: Optional[str]) -> Dict[str, Any]:
        """``{"cells": {book: {"Sheet!A1": n}}, "copies": {copy: {"Sheet!A1": n}}, "max": MAX_DECIMALS}``."""
        key = self.svc.require_user(user)
        raw = self._raw.get(key) or {}

        def flat(sheets):
            return {"%s!%s" % (sh, a): n for sh, cells in sheets.items() for a, n in cells.items()}

        return {"cells": {bid: flat(s) for bid, s in (raw.get("books") or {}).items()},
                "copies": {cid: flat(s) for cid, s in (raw.get("copies") or {}).items()},
                "max": numfmt.MAX_DECIMALS}

    def change(self, user: Optional[str], book_id: Any, copy: Any = None, set_: Any = None,
               reset: Any = None) -> Dict[str, Any]:
        """Set (``set_``: ``{"Sheet!A1": n, ...}``) or take back (``reset``: ``["Sheet!A1", ...]``, after the sets) the
        user's decimals of cells of a book - of a temporary copy of theirs (``copy``: its id) instead of the table.  A
        cell whose format shows a date, a time or text is not set (counted: ``skipped``).  ``{"set", "reset", "skipped",
        "mark"}``."""
        key = self.svc.require_user(user)
        book = self.svc.books.get(book_id) if isinstance(book_id, str) else None
        if book is None:
            raise ServiceError("çalışma kitabı bulunamadı: %s" % str(book_id)[:40], 404)
        cid = None
        if copy is not None:
            cp = self.svc.copies.find(key, copy)                # (gone: 404)
            t = self.svc.copies.tables.get((cp.view, cp.panel))
            if t is None or t.book is not book:
                raise ServiceError("geçici kopya bu çalışma kitabının tablosu değil")
            cid = cp.id
        if set_ is None:
            set_ = {}
        if reset is None:
            reset = []
        if not isinstance(set_, dict) or not isinstance(reset, list):
            raise ServiceError("set bir {hücre: ondalık} sözlüğü, reset bir hücre listesi olmalı")
        if len(set_) + len(reset) > MAX_PER_CHANGE:
            raise ServiceError("bir seferde en fazla %d hücrenin ondalığı değiştirilir" % MAX_PER_CHANGE)
        R = self.svc.renderers[book.id]
        sets: List[Tuple[str, str, int, bool]] = []
        for ref, n in set_.items():
            sheet, addr, si, rc = self._cell(book, ref)
            if type(n) is not int or not 0 <= n <= numfmt.MAX_DECIMALS:
                raise ServiceError("ondalık sayısı 0 ile %d arasında bir tam sayı olmalı: %s" % (numfmt.MAX_DECIMALS, ref))
            sets.append((sheet, addr, n, numfmt.is_number_format(R.format_of(si, rc))))
        resets = [self._cell(book, ref)[:2] for ref in reset]
        with self._lock:
            raw = _copy.deepcopy(self._raw.get(key) or {})
            part, owner = ("copies", cid) if cid else ("books", book.id)
            place = raw.setdefault(part, {}).setdefault(owner, {})
            done = skipped = gone = 0
            for sheet, addr, n, number in sets:
                if not number:
                    skipped += 1                                 # (a date, a time, text: never re-formatted)
                    continue
                place.setdefault(sheet, {})[addr] = n
                done += 1
            for sheet, addr in resets:
                if addr in place.get(sheet, {}):
                    del place[sheet][addr]
                    gone += 1
            # (a copy closed meanwhile, or gone with an update, takes its settings with it)
            mine = {c.id for c in self.svc.copies.items(key)}
            raw["copies"] = {c: s for c, s in (raw.get("copies") or {}).items() if c in mine}
            raw = _tidy(raw)
            if _State(raw).count > MAX_CELLS:
                raise ServiceError(TOO_MANY % MAX_CELLS)
            if raw != self._raw.get(key, {}):
                self.svc.store.put(KEY + key, raw)
                self._keep(key, raw)
        return {"set": done, "reset": gone, "skipped": skipped, "mark": self.mark(key)}

    @staticmethod
    def _cell(book, ref: Any) -> Tuple[str, str, int, int]:
        """(sheet, address, sheet index, cell) of ``"Sheet!A1"`` - one cell of a sheet of the book, or a 400."""
        sheet, _, addr = ref.rpartition("!") if isinstance(ref, str) else ("", "", "")
        m = _ADDR.match(addr)
        si = book.model.sheet_index.get(sheet)
        if not m or si is None:
            raise ServiceError("hücre bulunamadı: %s" % str(ref)[:80])
        return sheet, addr, si, int(m.group(2)) * COLS + col_to_index(m.group(1))

    def drop_copy(self, user: str, cid: str) -> None:
        """A temporary copy closed: its own settings go with it."""
        key = user_key(user)
        with self._lock:
            raw = self._raw.get(key) or {}
            if cid not in (raw.get("copies") or {}):
                return
            raw = _copy.deepcopy(raw)
            del raw["copies"][cid]
            raw = _tidy(raw)
            self.svc.store.put(KEY + key, raw)
            self._keep(key, raw)


def _table(data: Any, book, R, cells: Cells, own: Cells, loc) -> Any:
    """A table's cells the user set, re-formatted - the table itself when it holds none (or is no table of a sheet)."""
    if not isinstance(data, dict):
        return data
    sheet = data.get("sheet")
    want, mine = cells.get(sheet), own.get(sheet)
    rows, rnums, cols = data.get("rows"), data.get("r"), data.get("c")
    if not (want or mine) or not rows or not rnums or not cols:
        return data
    si = book.model.sheet_index.get(sheet)
    if si is None:
        return data
    at_c = {c: j for j, c in enumerate(cols) if isinstance(c, str) and _LETTERS.match(c)}    # (a named column: its own)
    hits: Dict[Tuple[int, int], Tuple[int, bool, int, str]] = {}
    for i, r in enumerate(rnums):
        if type(r) is not int or r <= 0:
            continue                                                     # (row 0: a caption row of the dashboard's)
        for src, in_copy in ((want, False), (mine, True)):          # (the copy's own after the table's: it stands)
            for c, n in ((src or {}).get(r) or {}).items():
                j = at_c.get(c)
                if j is not None:
                    hits[(i, j)] = (n, in_copy, r, c)
    if not hits:
        return data
    rows = list(rows)
    for (i, j), (n, in_copy, r, c) in hits.items():
        line = rows[i] if i < len(rows) else None
        cell = line[j] if isinstance(line, list) and j < len(line) else None
        if not isinstance(cell, dict) or cell.get("sk"):
            continue
        cell = dict(cell, dp=n)
        if in_copy:
            cell["dpc"] = 1
        if cell.get("k") == "n" and type(cell.get("v")) is float:
            fmt = numfmt.with_decimals(R.format_of(si, r * COLS + col_to_index(c)), n)
            cell["t"] = numfmt.render(cell["v"], fmt, loc, general_digits=10)[0].strip()
        if rows[i] is data["rows"][i]:
            rows[i] = list(line)
        rows[i][j] = cell
    return dict(data, rows=rows)
