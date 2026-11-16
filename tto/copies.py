"""Temporary copies of a calculator table ("Geçici kopya aç").

A table of a page whose inputs are the user's own - marked ``"copyable": true`` in its page's definition (tto/views) -
can be opened again, as copies: "… · kopya 2", "… · kopya 3", right under it on its page, and like any table on a
launchpad, in the side drawer, in a window of its own.  Each copy has inputs of its own: a value typed into a copy
changes that copy's numbers only - never the table's, another copy's, another page's or another user's.  Two or three
trades are priced side by side that way (the broken-date calculator for two value dates ...).

How a copy is computed: a layer of the engine (``xl.engine.LayerCalc``) on top of its user's calculation - the copy's
own inputs over the user's.  It holds only the values that follow its own inputs and reads everything else from its
user's (or everybody's) calculation, so what the market, the desk or the user changes reaches it as it reaches the
table; asked for its table, it evaluates that table and what the table reads that follows its own inputs, nothing else.
The rest of the workbook - the other pages, the calc sheets, the inputs typed as formulas, the scenarios, the watch
lists and alarms - reads the user's calculation: the table itself, never a copy.

A copy's inputs: the input cells of its table - and of the strip of inputs it is shown with (``"copy_with"``: the dates
of "TARİH ARASI FORWARD" stand in a row of their own above it) - all of them the user's own; a table with an input of
the desk (a shared one) is never copyable - a copy of a desk-wide setting would mislead.  Read-only in a copy, greyed
with the reason: an input whose value goes into a Bloomberg request (a value date or a ticker the workbook's BDP / BDH /
BFXFORWARD cells are computed from - a copy would need a request of its own, and the daily data limit counts every
one; the engine never asks Bloomberg for a layer either), a cell of a meeting's row (it moves with the calendar) and a
cell of a holiday list (its save writes the list again in date order).

A copy starts with the values typed in its table (the user's own; a cell holding an input formula keeps following it):
from then on the two are apart.  A cell typed in neither follows the table - its formula, the market.  A value cleared in
a copy (``Delete``) goes back to the table's where the cell has a formula default, and is an empty value of the copy's
where it has none - as in the table; "Sıfırla" (and the cell's own "→ tablonun değerine dön") takes the copy's values
away: it shows the table's again.  A formula is refused in a copy (its inputs are values; a formula stays in the table,
whose values the copy follows where it was not typed), and so is "Elle değer".

Kept with the account until it is closed (×) - the store's key / value table, ``copies.<user>``: a page switch, a reload
and a restart keep it.  Closing throws its values away and takes it off the user's launchpads and drawer.  At most
``MAX_PER_TABLE`` copies of a table and ``MAX_PER_USER`` in all, per user.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from . import layout as lay
from .inputs import InputError, parse_input
from .service import ServiceError, _from_json, _to_json
from .store import now_iso
from .xl import numfmt
from .xl.model import COLS, parse_range
from .xl.tokenizer import col_to_index

#: copies of one table a user may have open at once, and copies in all
MAX_PER_TABLE = 5
MAX_PER_USER = 20
KEY = "copies."                            # the store's key / value table: copies.<user> -> {"items": [...]}
_ID = re.compile(r"^k[0-9a-f]{8}$")

NOT_COPYABLE = ("bu tablonun geçici kopyası açılamaz: yalnızca girdileri kişisel olan hesaplayıcılar kopyalanır "
                "(ortak girdinin kopyası masanın ayarını değiştiriyormuş gibi gösterirdi)")
NO_INPUTS = "bu tablonun kopyada değiştirilebilecek girdisi yok: bütün girdileri bir Bloomberg isteğine giriyor"
TOO_MANY_TABLE = "bir tablonun en fazla %d geçici kopyası açık olabilir - kullanmadığınızı kapatın (×)"
TOO_MANY_USER = "en fazla %d geçici kopya açık olabilir - kullanmadıklarınızı kapatın (×)"
GONE = "geçici kopya bulunamadı (kapatılmış olabilir)"
FORMULA = ("geçici kopyaya formül yazılamaz: kopyanın girdileri değerdir - formül tablonun kendisinde kalır (kopya, "
           "yazmadığınız hücrelerde tablonun değerini izler)")
NOT_HERE = "bu hücre kopyanın girdisi değil (kopyada yalnız tablonun kişisel girdileri yazılır; \"Elle değer\" kopyada yok)"
FEEDS = ("bu girdi bir Bloomberg isteğine giriyor (%s): kopyada değiştirilemez - kopya kendi isteğini açmaz (günlük veri "
         "limiti); tablonun kendisinde değiştirin")
FEEDS_UNKNOWN = "bu girdinin bir Bloomberg isteğine girip girmediği bilinemiyor: kopyada değiştirilemez"
MOVES = "toplantı takvimiyle kayan satırın hücresi: kopyada değiştirilemez"
HOLIDAY = "tatil listesinin hücresi: kopyada değiştirilemez"
log = logging.getLogger("tto")


class Copy(object):
    """One temporary copy of a table: its id, its table (page / panel), its number in the title, its own values."""

    __slots__ = ("id", "view", "panel", "n", "at", "values")

    def __init__(self, cid: str, view: str, panel: str, n: int, at: str, values: Dict[str, Any]):
        self.id = cid
        self.view = view
        self.panel = panel
        self.n = n
        self.at = at
        self.values = values                 # "Sheet!A1" -> its value as the store keeps it (JSON)

    @property
    def pid(self) -> str:
        """Its panel id on its page (and the key of a launchpad's item): ``<table>.<id>``."""
        return "%s.%s" % (self.panel, self.id)

    def stored(self) -> Dict[str, Any]:
        return {"id": self.id, "view": self.view, "panel": self.panel, "n": self.n, "at": self.at, "values": dict(self.values)}

    def info(self) -> Dict[str, Any]:
        return {"id": self.id, "view": self.view, "panel": self.panel, "pid": self.pid, "n": self.n, "at": self.at,
                "values": len(self.values)}


class _Table(object):
    """A copyable table: its page, its panel, the strips of inputs it is shown with, and its input cells."""

    __slots__ = ("view", "panel", "book", "leads", "cells", "ro")

    def __init__(self, view: Dict[str, Any], panel: Dict[str, Any], book, leads: List[Dict[str, Any]],
                 cells: List[Tuple[int, int]]):
        self.view = view
        self.panel = panel
        self.book = book
        self.leads = leads
        self.cells = frozenset(cells)
        self.ro: Optional[Dict[Tuple[int, int], str]] = None      # read-only ones: why (worked out on first use)


def copy_pid(pid: str) -> Optional[Tuple[str, str]]:
    """(the table's panel id, the copy's id) of a copy's panel id - ``None`` for any other panel id."""
    base, _, cid = pid.rpartition(".")
    return (base, cid) if base and _ID.match(cid) else None


class Copies(object):
    """The temporary copies of every user (``Service.copies``).  What changes them runs on the calculation thread."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self._items: Dict[str, List[Copy]] = {}
        self.tables: Dict[Tuple[str, str], _Table] = {}
        self.problems: Dict[Tuple[str, str], str] = {}            # tables marked copyable that are not (said in the log)
        for v in svc.views:
            for p in v.get("panels", []):
                if p.get("copyable"):
                    self._table(v, p)

    # ------------------------------------------------------------------ which tables
    def _table(self, v: Dict[str, Any], p: Dict[str, Any]) -> None:
        key = (v["id"], p.get("id"))
        why = self._check(v, p)
        if isinstance(why, str):
            self.problems[key] = why
            log.warning("geçici kopya: %s/%s kopyalanamaz - %s", v["id"], p.get("id"), why)
            return
        self.tables[key] = why

    def _check(self, v: Dict[str, Any], p: Dict[str, Any]):
        """The table as a copyable one (``_Table``), or why it is not (a text)."""
        book = self.svc.books.get(v.get("book"))
        if book is None:
            return "çalışma kitabı yok"
        if v.get("admin"):
            return "yöneticilerin sayfası"
        if p.get("type") != "table" or not p.get("range") or p.get("hidden") or p.get("append") or p.get("source"):
            return "bir sayfa aralığının görünen tablosu değil"
        by_id = {x.get("id"): x for x in v.get("panels", [])}
        leads = []
        for lid in p.get("copy_with") or []:
            lp = by_id.get(lid)
            if lp is None or lp.get("type") != "table" or not lp.get("range"):
                return "copy_with: %s bu sayfanın tablosu değil" % lid
            leads.append(lp)
        cells: List[Tuple[int, int]] = []
        for q in [p] + leads:
            try:
                found = self._range_cells(book, v, q)
            except (KeyError, ValueError):
                return "%s: aralık okunamadı" % q.get("id")
            for cell in found:
                d = book.inputs.get(cell)
                if d is None or d.group in ("adhoc", "adhoc-shared"):
                    continue
                if d.scope == "shared":
                    return "ortak girdisi var (%s)" % book.ref(*cell)
                cells.append(cell)
        if not cells:
            return "kişisel girdisi yok"
        return _Table(v, p, book, leads, cells)

    @staticmethod
    def _range_cells(book, v: Dict[str, Any], p: Dict[str, Any]) -> List[Tuple[int, int]]:
        """The cells a table shows: its range, only the columns it picks (``"cols"``)."""
        sheet = p.get("sheet", v.get("sheet"))
        si = book.model.sheet_index[sheet]
        r1, c1, r2, c2 = parse_range(p["range"])
        cols = {col_to_index(x) for x in p["cols"]} if p.get("cols") else None
        return [(si, r * COLS + c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1) if cols is None or c in cols]

    def offered(self, view_id: str, pid: Optional[str]) -> bool:
        """Whether a table of a page can be copied ("Geçici kopya aç" in its menu)."""
        return (view_id, pid) in self.tables

    def prepare(self) -> None:
        """Every copyable table's read-only inputs worked out ahead (calculation thread, at its lowest priority, once the
        formulas' reverse references are built): the first copy opened does not wait for them."""
        for t in list(self.tables.values()):
            try:
                self.readonly(t)
            except Exception:  # noqa: BLE001 - worked out when first needed instead
                continue

    def readonly(self, t: _Table) -> Dict[Tuple[int, int], str]:
        """The inputs of a copyable table that stay read-only in its copies: cell -> why (calculation thread)."""
        if t.ro is None:
            from . import meetings as mt
            book = t.book
            eng = book.engine
            asks = eng.request_cells()
            idx = eng.ref_index()
            ro: Dict[Tuple[int, int], str] = {}
            for si, rc in sorted(t.cells):
                if mt.place(book, si, rc) is not None:
                    ro[(si, rc)] = MOVES
                elif self.svc._holiday_cell(book, si, rc):
                    ro[(si, rc)] = HOLIDAY
                elif not idx.complete:
                    ro[(si, rc)] = FEEDS_UNKNOWN
                else:
                    hits = sorted(c for c in idx.downstream([(si, rc)]) if c in asks)
                    if hits:
                        ro[(si, rc)] = FEEDS % book.ref(*hits[0])
            t.ro = ro
        return t.ro

    # ------------------------------------------------------------------ what is kept
    def _load(self, user: str) -> List[Copy]:
        got = self._items.get(user)
        if got is not None:
            return got
        try:
            raw = self.svc.store.get(KEY + user)
        except (TypeError, ValueError):
            raw = None                                       # (not ours to read: as if there were none)
        items: List[Copy] = []
        seen = set()
        dropped = False
        for x in (raw.get("items") if isinstance(raw, dict) else None) or []:
            try:
                cp = Copy(str(x["id"]), str(x["view"]), str(x["panel"]), int(x["n"]), str(x.get("at") or ""),
                          dict(x.get("values") or {}))
            except (KeyError, TypeError, ValueError, AttributeError):
                dropped = True
                continue
            if not _ID.match(cp.id) or cp.id in seen or (cp.view, cp.panel) not in self.tables:
                dropped = True                               # (its table is not copyable in this version: gone)
                continue
            seen.add(cp.id)
            items.append(cp)
        self._items[user] = items
        if dropped:
            self._save(user, items)
        return items

    def _save(self, user: str, items: List[Copy]) -> None:
        self._items[user] = items
        self.svc.store.put(KEY + user, {"items": [c.stored() for c in items]})

    def items(self, user: str) -> List[Copy]:
        with self._lock:
            return list(self._load(user))

    def has(self, user: Optional[str]) -> bool:
        return bool(user) and bool(self.items(user))

    def users(self) -> set:
        """The users who keep a copy open (their pages are their own)."""
        out = set()
        for key, v in self.svc.store.kv_prefixed(KEY).items():
            if isinstance(v, dict) and v.get("items"):
                out.add(key[len(KEY):])
        return out

    def of_view(self, user: Optional[str], view_id: str) -> Dict[str, List[Copy]]:
        """The user's copies of the tables of a page: table -> its copies, by their number."""
        out: Dict[str, List[Copy]] = {}
        if not user:
            return out
        for cp in self.items(user):
            if cp.view == view_id:
                out.setdefault(cp.panel, []).append(cp)
        for lst in out.values():
            lst.sort(key=lambda c: c.n)
        return out

    def find(self, user: str, cid: Any) -> Copy:
        if isinstance(cid, str):
            for cp in self.items(user):
                if cp.id == cid:
                    return cp
        raise ServiceError(GONE, 404)

    # ------------------------------------------------------------------ the engine
    def overlay(self, t: _Table, cp: Copy) -> Dict[Tuple[int, int], Any]:
        """The copy's own values as the engine takes them (a cell that is no input of the copy any more is left out)."""
        book = t.book
        ro = self.readonly(t)
        out: Dict[Tuple[int, int], Any] = {}
        for ref, v in cp.values.items():
            try:
                cell = book.cell(ref)
            except (KeyError, ValueError):
                continue
            if cell in t.cells and cell not in ro:
                out[cell] = _from_json(v)
        return out

    def calc(self, user: str, cp: Copy, parent=None):
        """The copy's calculation: a layer on top of the user's (calculation thread)."""
        t = self.tables[(cp.view, cp.panel)]
        if parent is None:
            parent = self.svc._calc(user, t.book)
        return t.book.engine.layer((user, cp.id), parent, self.overlay(t, cp))

    def drop(self, user: str, cid: Optional[str] = None) -> None:
        """The engine's layers of the user's copies (one of them: ``cid``) given back (calculation thread)."""
        for book in self.svc.books.values():
            for key in [k for k in book.engine.layers if k[0] == user and (cid is None or k[1] == cid)]:
                book.engine.drop_layer(key)

    # ------------------------------------------------------------------ what the browser asks (calculation thread)
    def open(self, user: str, view_id: Any, pid: Any) -> Dict[str, Any]:
        t = self.tables.get((view_id, pid)) if isinstance(view_id, str) and isinstance(pid, str) else None
        if t is None:
            raise ServiceError(NOT_COPYABLE, 400)
        ro = self.readonly(t)
        if all(c in ro for c in t.cells):
            raise ServiceError(NO_INPUTS, 400)
        book = t.book
        # it starts with the values typed in the table (the user's own - not a formula's: that one goes on following)
        ov = self.svc._overlay(user, book)
        fx = self.svc.formulas
        values = {}
        for cell in sorted(t.cells):
            if cell in ro or cell not in ov:
                continue
            if fx is not None and fx.entry(user, book.id, *cell) is not None:
                continue
            values[book.ref(*cell)] = _to_json(ov[cell])
        with self._lock:
            items = list(self._load(user))
            mine = [c for c in items if (c.view, c.panel) == (view_id, pid)]
            if len(mine) >= MAX_PER_TABLE:
                raise ServiceError(TOO_MANY_TABLE % MAX_PER_TABLE, 400)
            if len(items) >= MAX_PER_USER:
                raise ServiceError(TOO_MANY_USER % MAX_PER_USER, 400)
            taken = {c.n for c in mine}
            n = next(k for k in range(2, MAX_PER_TABLE + 3) if k not in taken)
            cid = "k" + uuid.uuid4().hex[:8]
            while any(c.id == cid for c in items):
                cid = "k" + uuid.uuid4().hex[:8]
            cp = Copy(cid, view_id, pid, n, now_iso(), values)
            items.append(cp)
            self._save(user, items)
        self.svc._note_private(user)
        return {"copy": cp.info()}

    def close(self, user: str, cid: Any) -> Dict[str, Any]:
        cp = self.find(user, cid)
        with self._lock:
            items = [c for c in self._load(user) if c.id != cp.id]
            self._save(user, items)
        self.drop(user, cp.id)
        # what showed it elsewhere goes with it: the user's launchpads and drawer
        removed = 0
        with self.svc._layout_lock:
            cur = lay.stored(self.svc.store.get("layout." + user))

            def keep(it: Dict[str, Any]) -> bool:
                return not (it.get("type", "table") == "table" and it.get("view") == cp.view and it.get("panel") == cp.pid)

            pads = [dict(lp, items=[it for it in lp["items"] if keep(it)]) for lp in cur["launchpads"]]
            drawer = [it for it in cur["drawer"] if keep(it)]
            removed = sum(len(lp["items"]) for lp in cur["launchpads"]) + len(cur["drawer"]) \
                - sum(len(lp["items"]) for lp in pads) - len(drawer)
            if removed:
                self.svc._put_layout(user, lay.change(cur, {"launchpads": pads, "drawer": drawer}))
        self.svc._note_private(user)
        return {"closed": cp.id, "layout": removed}

    def set_inputs(self, user: str, cid: Any, items: Any, lang: Optional[str] = None, lenient: bool = False) -> Dict[str, Any]:
        """Values typed into a copy: ``items`` [{"ref", "value"}] as ``Service.set_inputs`` takes them - into the copy's
        inputs only, each refused with the reason where it may not go (a read-only cell, a formula, no input of the copy).
        ``lenient`` (a block pasted): cells that are no input of the copy are skipped and counted."""
        if not isinstance(items, list):
            raise ServiceError("items listesi gerekli")
        if len(items) > 5000:
            raise ServiceError("çok fazla hücre")
        cp = self.find(user, cid)
        t = self.tables[(cp.view, cp.panel)]
        book = t.book
        ro = self.readonly(t)
        calc = self.calc(user, cp)
        lang = lang or self.svc.settings.locale
        values = dict(cp.values)
        errors: List[str] = []
        applied = skipped = 0
        for it in items:
            ref = it.get("ref") if isinstance(it, dict) else None
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError, AttributeError, TypeError):
                errors.append("%s: hücre bulunamadı" % ref)
                continue
            raw = it.get("value")
            if (si, rc) not in t.cells or (si, rc) in ro:
                if lenient:
                    skipped += 1
                else:
                    errors.append("%s: %s" % (ref, ro.get((si, rc)) or NOT_HERE))
                continue
            if isinstance(raw, str) and raw.strip().startswith("="):
                errors.append("%s: %s" % (ref, FORMULA))
                continue
            d = book.inputs[(si, rc)]
            sheet = book.model.sheets[si]
            xf = sheet.styles.get(rc, 0)
            fmt = book.model.numfmts[xf] if xf < len(book.model.numfmts) else "General"
            try:
                val = parse_input(raw, numfmt.is_percent_format(fmt), numfmt.is_date_format(fmt), d.kind,
                                  book.options_for(si, rc, calc), lang, d.aliases)
            except InputError as exc:
                errors.append("%s: %s" % (ref, exc))
                continue
            key = book.ref(si, rc)
            if val is None and rc in sheet.fml:
                values.pop(key, None)                    # a formula default: the table's value again
            else:
                values[key] = _to_json(val)
            applied += 1
        if values != cp.values:
            self._put_values(user, cp, values)
        res: Dict[str, Any] = {"applied": applied, "errors": errors}
        if lenient:
            res["skipped"] = skipped
        return res

    def reset(self, user: str, cid: Any, refs: Any = None) -> Dict[str, Any]:
        """The copy's own values taken away (all of them, or those of ``refs``): it shows the table's again."""
        cp = self.find(user, cid)
        t = self.tables[(cp.view, cp.panel)]
        if isinstance(refs, list) and refs:
            gone = set()
            for ref in refs:
                try:
                    gone.update(t.book.ref(*c) for c in t.book.cells_of(ref))
                except (KeyError, ValueError, AttributeError, TypeError):
                    continue
            values = {k: v for k, v in cp.values.items() if k not in gone}
        else:
            values = {}
        n = len(cp.values) - len(values)
        if n:
            self._put_values(user, cp, values)
        return {"reset": n}

    def _put_values(self, user: str, cp: Copy, values: Dict[str, Any]) -> None:
        with self._lock:
            items = list(self._load(user))
            for i, c in enumerate(items):
                if c.id == cp.id:
                    items[i] = Copy(c.id, c.view, c.panel, c.n, c.at, values)
                    cp = items[i]
            self._save(user, items)
        # the layer follows at once - what the values change only; its panel is made again by what it read (the page's
        # other tables are not: they read nothing of the copy's)
        self.calc(user, cp)

    # ------------------------------------------------------------------ how a copy is drawn (calculation thread)
    def entry(self, p: Dict[str, Any], v: Dict[str, Any], cp: Copy, book, layer, R, loc, user: str, sheet: str,
              charts, show_hidden: bool, explorer: bool) -> Dict[str, Any]:
        """A copy's panel as the browser draws it: the table's own, out of the copy's calculation - its id
        ``<table>.<copy>``, "… · kopya n", ``copy`` {id, of, n}, the inputs of the copy editable and the read-only ones
        greyed with their reason (``ro``), the strips of inputs it is shown with (``lead``)."""
        svc = self.svc
        t = self.tables[(cp.view, cp.panel)]
        ro = self.readonly(t)
        own = layer.overlay
        entry = svc._panel(p, v, book, layer, R, loc, own, user, sheet, charts, show_hidden, explorer)
        base = entry.get("title") or p.get("title") or p.get("id")
        entry.update(id=cp.pid, title="%s · kopya %d" % (base, cp.n), copy={"id": cp.id, "of": p.get("id"), "n": cp.n})
        entry.pop("copyable", None)
        entry.pop("action", None)
        self._cells(entry.get("data"), book, sheet, user, t, ro, own)
        leads = []
        for lp in t.leads:
            lsheet = lp.get("sheet", v.get("sheet"))
            le = svc._panel(lp, v, book, layer, R, loc, own, user, lsheet, charts, show_hidden, explorer)
            self._cells(le.get("data"), book, lsheet, user, t, ro, own)
            leads.append({"title": le.get("title") or lp.get("title") or "", "data": le.get("data"), "error": le.get("error")})
        if leads:
            entry["lead"] = leads
        return entry

    def _cells(self, data: Optional[Dict[str, Any]], book, sheet: str, user: str, t: _Table,
               ro: Dict[Tuple[int, int], str], own: Dict[Tuple[int, int], Any]) -> None:
        """The marks of a copy's cells: its inputs (a read-only one greyed with the reason), the user's input formulas
        only where the copy follows the table."""
        if not data or not data.get("rows") or not data.get("r") or not data.get("c"):
            return
        si = book.model.sheet_index.get(sheet)
        for row in data["rows"]:
            for cell in row:
                if isinstance(cell, dict):
                    cell.pop("ff", None)
                    cell.pop("fe", None)
        self.svc._mark_formulas(data, book, sheet, user)
        letter = re.compile(r"^[A-Z]{1,3}$")
        for i, row in enumerate(data["rows"]):
            r = data["r"][i] if i < len(data["r"]) else None
            for j, cell in enumerate(row):
                if not isinstance(cell, dict) or "i" not in cell or cell.get("sk"):
                    continue
                col = data["c"][j] if j < len(data["c"]) else None
                if not isinstance(r, int) or not isinstance(col, str) or not letter.match(col) or si is None:
                    continue
                key = (si, r * COLS + col_to_index(col))
                why = ro.get(key) if key in t.cells else NOT_HERE
                if why:
                    for k in ("i", "o", "m", "ik", "ff", "fe"):
                        cell.pop(k, None)
                    cell["ro"] = why
                elif key in own:
                    cell.pop("ff", None)                 # (the copy's own value: no formula of the table's)
                    cell.pop("fe", None)
