"""Two-way tables: every value of a row can be typed - the one typed last stands, the others are worked out from it.

The desk, 24.11.2026, on FORWARD KOTASYON: "hem spread hem faizler girdi olabilsin, hangisine ben girdiysem diğerini
hesaplasın ... Genel olarak tablolar bu şekilde olmalı karışıklık olmaması için."

**What a table declares** (its page's view JSON, ``"twoway"``: tto/views/__init__.py) - a **group**: same-shaped ranges
of one sheet, its **members**, each a way of saying the same thing (FORWARD KOTASYON: a value date's spread, TRY rate,
swap points and outright, bid and ask).  The cells at the same place of every member - the same row and column of the
shape - are one **row-side** (a value date's bid; its ask is another row-side).

* A value typed into a member's cell is kept in that member's **store**: a hidden input cell of the same row (the
  member's ``"store"``, a range of its shape), blank by default - declared as an input here, not in the page's
  ``inputs``.  At most one member keeps it in its own cell (no ``"store"``, **in place**): an input of the page whose
  formula default is the value worked out from the other stores - the table's input from before, so what users typed
  there keeps its meaning with no move.
* **The last typed wins.**  A value or a formula typed into a member's cell is stored, and the row-side's other stores
  are emptied in the same write.  That member is the row-side's **anchor**: its cell shows what was typed, exactly,
  whatever the market does; the other members are worked out from it.
* **Delete** (or "Kendi girdimi sil", "formüle dön") on any cell of a row-side empties all of its stores: the row-side
  goes back to its default.
* **One write, several cells** (a block pasted from Excel): per row-side the last value in the write's order (row by
  row, left to right) is its anchor; a blank in the same write as a value of the same row-side clears nothing; a
  row-side the write only blanks goes back to its default.
* **Formulas** (``=…``, tto/inputformula.py) are taken on a member as on any input: kept on its store, refused with the
  reason where they would read themselves.  A formula reading its own row-side - a member, a store, a cell computed from
  them - is a cycle once it stands, also when what it reads holds a typed value now (the in-place member's typed value
  is emptied by the write, its formula default then reads the new store): refused as typed (:meth:`own_row_ring`).  Every
  reason - a refusal, a formula stopped with ``#CALC!`` - names the member's cell, not the store.
* Pasting, Senaryolar, "Girdilerimi sıfırla", temporary copies (copies.py: every store of the row-side of a member a
  copy shows is the copy's input, also those of members it does not show) and the page's marks go through the stores:
  a table that declares its group has nothing more to do for them.
* **What was kept at a member's own cell before it was two-way** - "Elle değer" typed over it, or the page's input it
  was then, with the formula typed into it - is that row-side's anchor: moved to the store once, the formula with it (it
  stays live; inputformula.py leaves it for this), the row-side's other stores emptied, logged - a user's values when
  they are read (:meth:`adopt`), the desk's at the start (:meth:`adopt_shared`), a temporary copy's own values when the
  copy is read (:meth:`adopt_copy`: a copy opened before the table was two-way).

**How a table adopts it** (FORWARD KOTASYON in ``extras._tto_forward`` is the example):

1. Its builder (tto/extras.py) writes the stores' cells (blank, with the members' number formats) and every member's
   cell as ``IF(ISBLANK(<own store>), <worked out>, <own store>)``: ``<worked out>`` is the member's value from whichever
   store holds one (the table's inverse formulas - one implementation for the table and its other ways back, as
   ``extras.fwd_outright`` / ``extras.fwd_rate``), else from the in-place member's cell (typed, or its default).  The
   in-place member's formula default does the same: the value the stored anchor gives, else its old default.  No
   formula ever writes a store and the in-place member's cell reads only the stores, so there is no cycle.
2. Its view declares the group (``"twoway"``); the in-place member stays among the page's ``inputs``, the other members
   are not inputs (their cells are formulas).
3. Its tests: each member typed -> the others, each the exact inverse (a computed value typed back as its own kind gives
   the same row to 1e-9), the last typed wins, Delete, a paste, a scenario saved and loaded, the values typed before
   unchanged; and if its rows move (meetings.py, rowkeys.py) the stores move with them: declared to that mechanism too.

**Limits:** a store lives on its member's sheet and scope (``"scope"``: the group's, "user" by default).  In a temporary
copy the copy's own values stand over its table's; an in-place member cannot go back to its formula default there while
the table itself holds a value typed in it (the engine's copy layer cannot unset a value of the calculation below it), so
typing another member of that row-side in the copy is refused with the reason (:meth:`copy_write`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .xl.model import COLS, a1, parse_range

log = logging.getLogger("tto")

Cell = Tuple[int, int]

#: a copy's write that would need the table's in-place value gone (see the module's "Limits")
COPY_TABLE_TYPED = ("kopyada yazılamaz: tablonun kendisinde bu satıra %s yazılmış (%s) - kopya onu formülüne döndüremez; "
                    "kopyada başka bir değer yazmak için önce tablodaki değeri silin")
#: a formula typed into a member that reads its own row-side (:meth:`TwoWay.own_row_ring`)
ROW_CYCLE = ("döngüsel başvuru: %s - formül kendi satırını okuyor (iki yönlü tablo: yazılınca satırın öbür değerleri bu "
             "formülden hesaplanır)")


_GONE = object()


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


class Member(object):
    """One way of giving a row-side's value: its cells on the page and where what is typed into them is kept."""

    __slots__ = ("k", "name", "label", "kind", "cells", "store", "own")

    def __init__(self, k: int, name: str, label: str, kind: str, cells: List[Cell], store: List[Cell], own: bool):
        self.k = k                      # its place in the group's declaration
        self.name = name                # how the page names it ("TRY %")
        self.label = label
        self.kind = kind
        self.cells = cells              # its cells, row by row (the shape's order)
        self.store = store              # where a value typed into each is kept (``cells`` itself: in place)
        self.own = own                  # in place: its cells are the page's own inputs


class Group(object):
    """Same-shaped members of one sheet: the cells at one place of each are a row-side."""

    __slots__ = ("id", "view", "book", "sheet", "si", "shape", "members", "note", "label", "scope", "box")

    def __init__(self, gid: str, view: str, book, sheet: str, si: int, shape: Tuple[int, int], members: List[Member],
                 note: Optional[str], label: str, scope: str):
        self.id = gid
        self.view = view
        self.book = book
        self.sheet = sheet
        self.si = si
        self.shape = shape
        self.members = members
        self.note = note
        self.label = label
        self.scope = scope
        rows = [rc // COLS for m in members for _, rc in m.cells]
        cols = [rc % COLS for m in members for _, rc in m.cells]
        self.box = (min(rows), min(cols), max(rows), max(cols))      # the members' cells (not the stores)

    def stores(self, pos: int) -> List[Cell]:
        """The stores of a row-side (``pos``: its place in the shape), one per member."""
        return [m.store[pos] for m in self.members]

    def held(self, cell: Cell, overlay: Optional[Dict[Cell, Any]], shared: Any) -> bool:
        """Whether a store of the group holds a value typed (``overlay``: the user's own values - or a copy's -,
        ``shared``: the desk's, ``engine.input_value``)."""
        si, rc = cell
        if self.scope == "shared":
            return shared is not None and shared[si].get(rc) is not None
        return overlay is not None and overlay.get(cell) is not None

    def anchor(self, pos: int, overlay: Optional[Dict[Cell, Any]], shared: Any) -> Optional[Member]:
        """The member whose store holds the row-side's typed value - its anchor; ``None``: nothing is typed there, the
        row-side shows its default."""
        for m in self.members:
            if self.held(m.store[pos], overlay, shared):
                return m
        return None


class Hit(object):
    """A cell of a group: a member's own cell (``store`` False) or a store's (True - typed there, in a helper table or
    the sheet explorer, it is its member's)."""

    __slots__ = ("group", "member", "pos", "store")

    def __init__(self, group: Group, member: Member, pos: int, store: bool):
        self.group = group
        self.member = member
        self.pos = pos
        self.store = store

    @property
    def store_cell(self) -> Cell:
        return self.member.store[self.pos]

    @property
    def member_cell(self) -> Cell:
        return self.member.cells[self.pos]

    @property
    def redirected(self) -> bool:
        """A member's cell whose value is kept elsewhere (its store): the cell itself is a formula."""
        return not self.store and not self.member.own

    def siblings(self) -> List[Cell]:
        """The row-side's other stores: emptied when this member is typed."""
        return [m.store[self.pos] for m in self.group.members if m is not self.member]


class TwoWay(object):
    """Every two-way group of the pages (``Service.twoway``); each book's cells of them in ``Book.twoway``
    (cell -> :class:`Hit`).  Built once the pages' inputs are declared - it declares the stores."""

    def __init__(self, svc, views: Optional[List[Dict[str, Any]]] = None):
        self.svc = svc
        self.groups: Dict[str, Group] = {}
        self.problems: Dict[str, str] = {}         # declarations that cannot be used (said in the log): "view/id" -> why
        self._said: Dict[str, Tuple[Any, Dict[str, str]]] = {}
        for book in svc.books.values():
            if not hasattr(book, "twoway") or book.twoway is None:
                book.twoway = {}
        for v in (svc.views if views is None else views):
            for spec in v.get("twoway") or ():
                gid = spec.get("id") if isinstance(spec, dict) else None
                try:
                    g = self._group(v, spec)
                except (KeyError, ValueError, TypeError, AttributeError) as exc:
                    key = "%s/%s" % (v.get("id"), gid or "?")
                    self.problems[key] = str(exc)
                    log.warning("iki yönlü tablo kullanılamaz: %s - %s", key, exc)
                    continue
                self._take(g)

    # ------------------------------------------------------------------ the declarations
    @staticmethod
    def _cells(book, si: int, sheet: str, rng: Any) -> Tuple[List[Cell], Tuple[int, int]]:
        if not isinstance(rng, str) or not rng:
            raise ValueError("aralık yok")
        where, _, addr = rng.rpartition("!")
        if where and where.strip("'") != sheet:
            raise ValueError("%s: grubun sayfasında değil (%s)" % (rng, sheet))
        r1, c1, r2, c2 = parse_range(addr)
        cells = [(si, r * COLS + c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
        return cells, (r2 - r1 + 1, c2 - c1 + 1)

    def _group(self, v: Dict[str, Any], spec: Any) -> Group:
        if not isinstance(spec, dict):
            raise ValueError("tanım bir sözlük değil")
        gid = spec.get("id")
        if not isinstance(gid, str) or not gid:
            raise ValueError("id yok")
        if gid in self.groups:
            raise ValueError("bu id başka bir grubun (%s)" % gid)
        book = self.svc.books.get(v.get("book"))
        if book is None:
            raise ValueError("çalışma kitabı yok: %s" % v.get("book"))
        sheet = spec.get("sheet") or v.get("sheet")
        if sheet not in book.model.sheet_index:
            raise ValueError("sayfa yok: %s" % sheet)
        si = book.model.sheet_index[sheet]
        sh = book.model.sheets[si]
        scope = spec.get("scope", "user")
        if scope not in ("user", "shared"):
            raise ValueError("scope 'user' ya da 'shared' olur: %r" % scope)
        raw = spec.get("members")
        if not isinstance(raw, list) or len(raw) < 2:
            raise ValueError("en az iki üye gerekir")
        label = str(spec.get("label") or gid)
        members: List[Member] = []
        shape: Optional[Tuple[int, int]] = None
        taken: Dict[Cell, str] = {}

        def claim(cells: List[Cell], what: str) -> None:
            for c in cells:
                if c in taken:
                    raise ValueError("%s: %s iki kez kullanılmış (%s)" % (what, book.ref(*c), taken[c]))
                if c in book.twoway:
                    raise ValueError("%s: %s başka bir iki yönlü grubun (%s)" % (what, book.ref(*c), book.twoway[c].group.id))
                taken[c] = what

        for k, m in enumerate(raw):
            if not isinstance(m, dict):
                raise ValueError("üye %d bir sözlük değil" % (k + 1))
            name = str(m.get("name") or "")
            if not name:
                raise ValueError("üye %d: adı yok" % (k + 1))
            cells, mshape = self._cells(book, si, sheet, m.get("range"))
            if shape is None:
                shape = mshape
            elif mshape != shape:
                raise ValueError("%s: biçimi (%dx%d) ilk üyeninkinden (%dx%d) farklı" % (name, mshape[0], mshape[1], shape[0], shape[1]))
            claim(cells, name)
            if m.get("store"):
                store, sshape = self._cells(book, si, sheet, m["store"])
                if sshape != shape:
                    raise ValueError("%s: deposunun biçimi üyeninkinden farklı" % name)
                claim(store, name + " deposu")
                for c in store:
                    if c in book.inputs:
                        raise ValueError("%s: depo hücresi %s zaten bir girdi" % (name, book.ref(*c)))
                    if c[1] in sh.fml or c[1] in sh.consts:
                        raise ValueError("%s: depo hücresi %s boş değil" % (name, book.ref(*c)))
                for c in cells:
                    if c in book.inputs:
                        raise ValueError("%s: %s sayfanın girdisi - depolu üyenin hücresi bir formüldür" % (name, book.ref(*c)))
                    if c[1] not in sh.fml:
                        raise ValueError("%s: %s bir formül değil (deposunu ya da hesaplananı gösterir)" % (name, book.ref(*c)))
                own = False
            else:
                for c in cells:
                    d = book.inputs.get(c)
                    if d is None or d.group in ("adhoc", "adhoc-shared"):
                        raise ValueError("%s: %s sayfanın girdisi değil (deposu olmayan üye kendi girdisini tutar)" % (name, book.ref(*c)))
                    if d.scope != scope:
                        raise ValueError("%s: %s %s bir girdi, grup %s" % (name, book.ref(*c), d.scope, scope))
                store = cells
                own = True
            mlabel = str(m.get("label") or "%s · %s (iki yönlü: yazılan değer)" % (label, name))
            members.append(Member(k, name, mlabel, str(m.get("kind") or "number"), cells, store, own))
        if sum(1 for m in members if m.own) > 1:
            raise ValueError("en fazla bir üye değerini kendi hücresinde tutar (ötekilerin deposu olur)")
        note = spec.get("note")
        return Group(gid, str(v.get("id") or ""), book, sheet, si, shape or (0, 0), members,
                     note if isinstance(note, str) and note.strip() else None, label, scope)

    def _take(self, g: Group) -> None:
        book = g.book
        for m in g.members:
            if not m.own:
                book.declare_cells(m.store, scope=g.scope, group="twoway:%s:%d" % (g.id, m.k), kind=m.kind,
                                   label=m.label, view=g.view)
        for m in g.members:
            for pos, c in enumerate(m.cells):
                book.twoway[c] = Hit(g, m, pos, False)
            if not m.own:
                for pos, c in enumerate(m.store):
                    book.twoway[c] = Hit(g, m, pos, True)
        self.groups[g.id] = g
        self._said.pop(book.id, None)

    # ------------------------------------------------------------------ writes
    def expand(self, book, items: List[Any]) -> Tuple[List[Tuple[Any, Optional[Hit], Any]], List[Cell], int]:
        """A write's items (``[{"ref", "value"}]``) as the groups take them -> ``(items, clears, blanked)``:

        * ``items``: ``(item, hit, said)`` in order - an item of no group as it is (``hit`` None); a two-way one with its
          ref turned to the member's store (``hit``: the member, ``said``: the ref that was sent, for the messages), and
          only the last value of its row-side (a blank beside a value of the same row-side is dropped);
        * ``clears``: the stores of the row-sides this write only blanks (back to their default);
        * ``blanked``: the items of those row-sides (the cells the user emptied, as the answer counts them).

        The row-side's other stores are emptied once the item's value is taken (:attr:`Hit.siblings`) - a value refused
        (not a number, a formula that reads itself) leaves the row-side as it was."""
        idx = getattr(book, "twoway", None)
        if not idx:
            return [(it, None, None) for it in items], [], 0
        hits: List[Optional[Hit]] = []
        last: Dict[Tuple[str, int], int] = {}
        blanks: Dict[Tuple[str, int], List[Hit]] = {}
        for n, it in enumerate(items):
            h = None
            if isinstance(it, dict):
                try:
                    h = idx.get(book.cell(it.get("ref")))
                except (KeyError, ValueError, AttributeError, TypeError):
                    h = None
            hits.append(h)
            if h is None:
                continue
            key = (h.group.id, h.pos)
            if _blank(it.get("value")):
                blanks.setdefault(key, []).append(h)
            else:
                last[key] = n
        out: List[Tuple[Any, Optional[Hit], Any]] = []
        for n, it in enumerate(items):
            h = hits[n]
            if h is None:
                out.append((it, None, None))
            elif last.get((h.group.id, h.pos)) == n:
                out.append((dict(it, ref=book.ref(*h.store_cell)), h, it.get("ref")))
        clears: List[Cell] = []
        blanked = 0
        for key, hs in blanks.items():
            if key not in last:
                clears.extend(hs[0].group.stores(hs[0].pos))
                blanked += len(hs)
        return out, clears, blanked

    def widen(self, book, cells: Iterable[Cell]) -> List[Cell]:
        """Cells taken back to their default (``/api/reset``: "Kendi girdimi sil", "formüle dön"): a two-way cell stands
        for its row-side - every store of it."""
        idx = getattr(book, "twoway", None)
        if not idx:
            return list(cells)
        out: List[Cell] = []
        seen = set()
        for c in cells:
            h = idx.get(c)
            for x in (h.group.stores(h.pos) if h is not None else (c,)):
                if x not in seen:
                    seen.add(x)
                    out.append(x)
        return out

    def said(self, book, text: str) -> str:
        """A message (a formula's cycle ...) with each store's cell said as its member's - the cell that was typed into."""
        got = self._said.get(book.id)
        if got is None:
            names = {book.ref(*h.store_cell): book.ref(*h.member_cell)
                     for c, h in getattr(book, "twoway", {}).items() if h.store}
            rx = re.compile("(?:%s)(?![0-9])" % "|".join(re.escape(r) for r in sorted(names, key=len, reverse=True))) if names else None
            got = self._said[book.id] = (rx, names)
        rx, names = got
        return rx.sub(lambda m: names[m.group(0)], text) if rx is not None and text else text

    # ------------------------------------------------------------------ values kept from before a table was two-way
    @staticmethod
    def _legacy(book, refs: Iterable[str]) -> Tuple[Dict[Tuple[str, int], Tuple[Hit, str]], List[str]]:
        """Refs kept at a member's own cell from before it was two-way - a value typed over it ("Elle değer"), or the
        page's input it was then: ``({(group, pos): (hit, ref)}, [every such ref])`` - per row-side the member declared
        later wins."""
        idx = getattr(book, "twoway", None) or {}
        found: Dict[Tuple[str, int], Tuple[Hit, str]] = {}
        legacy: List[str] = []
        for ref in refs:
            try:
                h = idx.get(book.cell(ref))
            except (KeyError, ValueError, AttributeError, TypeError):
                continue
            if h is None or not h.redirected:
                continue
            legacy.append(ref)
            key = (h.group.id, h.pos)
            if key not in found or h.member.k > found[key][0].member.k:
                found[key] = (h, ref)
        return found, legacy

    def adopt(self, user: str, book, rows: Dict[Tuple[str, str], Any]) -> Tuple[Dict[Tuple[str, str], Any], bool]:
        """A user's values as the store keeps them (``rows``: {(book, ref): value}), with a value kept at a member's own
        cell from before it was two-way - "Elle değer" typed over it, or the page's input it was then, with the formula
        typed into it (inputformula.py leaves that one to this) - taken as its row-side's anchor: moved to the member's
        store, the row-side's other stores emptied, once, in the store (the log says so).  Two such in one row-side: the
        member declared later wins.  Returns the rows as they are now and whether a formula moved."""
        if not getattr(book, "twoway", None):
            return rows, False
        found, legacy = self._legacy(book, [ref for (bid, ref) in rows if bid == book.id])
        if not legacy:
            return rows, False
        store = self.svc.store
        texts = store.user_formulas(user, book.id)
        put: Dict[str, Any] = {}
        forms: Dict[str, str] = {}
        drop = set(legacy)
        for h, ref in found.values():
            at = book.ref(*h.store_cell)
            put[at] = rows[(book.id, ref)]
            if isinstance(texts.get((book.id, ref)), str):
                forms[at] = texts[(book.id, ref)]
            drop.update(book.ref(*c) for c in h.siblings())
        drop = sorted(r for r in drop - set(put) if (book.id, r) in rows)
        if drop:
            store.clear_user_inputs(user, book.id, drop)
        store.set_user_inputs(user, book.id, put, forms)
        log.info("iki yönlü tablo: %s'nin önceden yazdığı değerler satırlarının yazılan değeri oldu: %s", user,
                 ", ".join("%s → %s%s" % (ref, book.ref(*h.store_cell), " (formülüyle)" if book.ref(*h.store_cell) in forms else "")
                           for h, ref in found.values()))
        return store.user_inputs(user, book.id), bool(forms)

    def adopt_shared(self, book) -> None:
        """The desk's values (shared inputs) kept at a member's own cell from before it was two-way: as :meth:`adopt` -
        moved to the store with their formula, the row-side's other stores emptied - once, at the start (logged)."""
        if not getattr(book, "twoway", None):
            return
        store = self.svc.store
        rows = store.shared_inputs(book.id)
        found, legacy = self._legacy(book, [ref for (bid, ref) in rows if bid == book.id])
        if not legacy:
            return
        texts = store.shared_formulas(book.id)
        put: Dict[str, Any] = {}
        forms: Dict[str, str] = {}
        drop = set(legacy)
        for h, ref in found.values():
            at = book.ref(*h.store_cell)
            put[at] = rows[(book.id, ref)]
            if isinstance(texts.get((book.id, ref)), str):
                forms[at] = texts[(book.id, ref)]
            drop.update(book.ref(*c) for c in h.siblings())
        drop = sorted(r for r in drop - set(put) if (book.id, r) in rows)
        if drop:
            store.clear_shared_inputs(book.id, drop)
        store.set_shared_inputs(book.id, put, None, forms)
        log.info("iki yönlü tablo: masanın önceden yazılmış değerleri satırlarının yazılan değeri oldu: %s",
                 ", ".join("%s → %s" % (ref, book.ref(*h.store_cell)) for h, ref in found.values()))

    def adopt_copy(self, book, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A temporary copy's own values (copies.py, ``{ref: value}``) with one kept at a member's own cell from before
        the table was two-way (the page's input it was when the copy was opened) taken as the copy's value of its
        row-side: into the member's store, the row-side's other stores the copy's own empty values (a store of its own
        cell - the in-place member - the table's again).  A store the copy holds already stands; the old value goes.
        Returns the new values (``None``: nothing to adopt)."""
        if not getattr(book, "twoway", None):
            return None
        found, legacy = self._legacy(book, list(values))
        if not legacy:
            return None
        out = {k: v for k, v in values.items() if k not in set(legacy)}
        for h, ref in found.values():
            sheet = book.model.sheets[h.group.si]
            hidden = [book.ref(*c) for c in h.group.stores(h.pos) if c[1] not in sheet.fml]
            if any(r in out for r in hidden):
                continue                                   # (a value typed in the copy since: it stands)
            out[book.ref(*h.store_cell)] = values[ref]
            for c in h.siblings():
                if c[1] in sheet.fml:
                    out.pop(book.ref(*c), None)            # (the in-place member: the table's again)
                else:
                    out[book.ref(*c)] = None
        return out

    # ------------------------------------------------------------------ formulas typed into a member
    def own_row_ring(self, book, h: Hit, boxes: Any) -> Optional[List[str]]:
        """A formula typed into a member, by the cells its text names (``boxes``: [(book, sheet, r1, c1, r2, c2)] -
        ``None``: cells it works out, OFFSET / INDIRECT, which the engine's check covers): whether it reads its own
        row-side - a member or a store of it, or a cell the workbook's formulas compute from those stores.  Once it
        stands, the row-side's other members are worked out from it: a cycle - also when the cell read holds a value
        typed now (the in-place member's typed value is emptied by this very write, its formula default then reads the
        formula's store).  Returns the ring as the members' cells say it (``[typed into, read, typed into]``) or None."""
        if not boxes:
            return None
        g = h.group
        stores = [m.store[h.pos] for m in g.members]
        row = {c for m in g.members for c in (m.cells[h.pos], m.store[h.pos])}
        try:
            row |= set(book.engine.ref_index().downstream(stores))
        except Exception:  # noqa: BLE001 - the references cannot be told: the row-side's own cells still are
            pass
        hits = []
        for bid, si, r1, c1, r2, c2 in boxes:
            if bid != book.id:
                continue
            hits.extend(c for c in row if c[0] == si and r1 <= c[1] // COLS <= r2 and c1 <= c[1] % COLS <= c2)
        if not hits:
            return None
        idx = book.twoway
        # (a member or store of the row-side first, said as its member's cell; else the cell computed from it)
        own = sorted(c for c in hits if c in idx and idx[c].group is g and idx[c].pos == h.pos)
        read = book.ref(*idx[own[0]].member_cell) if own else book.ref(*min(hits))
        typed = book.ref(*h.member_cell)
        return [typed, read, typed]

    # ------------------------------------------------------------------ a temporary copy's values (copies.py)
    def copy_write(self, book, h: Hit, value: Any, values: Dict[str, Any], table: Dict[Cell, Any]) -> Optional[str]:
        """A member typed in a copy: ``value`` (as the copy keeps it) into its store among ``values`` (the copy's own, by
        ref), the row-side's other stores the copy's own empty values - a store of its own cell (the in-place member, a
        formula default) by taking the copy's value away (the table's default shows).  That cannot be done while the
        table itself holds a value typed there (``table``: the user's own values): then the reason, ``values`` as it was."""
        sheet = book.model.sheets[h.group.si]
        for c in h.siblings():
            if c[1] in sheet.fml and h.group.held(c, table, book.engine.input_value):
                m = next(x for x in h.group.members if x.store[h.pos] == c)
                return COPY_TABLE_TYPED % (m.name, book.ref(*m.cells[h.pos]))
        values[book.ref(*h.store_cell)] = value
        for c in h.siblings():
            ref = book.ref(*c)
            if c[1] in sheet.fml:
                values.pop(ref, None)
            else:
                values[ref] = None
        return None

    def copy_clear(self, book, cells: Iterable[Cell], values: Dict[str, Any]) -> int:
        """Two-way cells blanked or reset in a copy: their row-sides' stores taken out of the copy's own ``values`` - the
        row-side follows its table again.  Returns how many were taken out."""
        n = 0
        for c in self.widen(book, cells):
            if values.pop(book.ref(*c), _GONE) is not _GONE:
                n += 1
        return n

    # ------------------------------------------------------------------ the page
    def note_for(self, book, sheet: str, rng: str) -> Optional[str]:
        """The notes of the groups whose members a table of ``sheet`` / ``rng`` shows (``None``: none)."""
        try:
            r1, c1, r2, c2 = parse_range(rng)
        except Exception:  # noqa: BLE001 - a range that cannot be read shows no note
            return None
        notes = []
        for g in self.groups.values():
            if g.book is book and g.sheet == sheet and g.note:
                a, b, c, d = g.box
                if not (a > r2 or c < r1 or b > c2 or d < c1):
                    notes.append(g.note)
        return " ".join(dict.fromkeys(notes)) or None


def mark(book, h: Hit, overlay: Optional[Dict[Cell, Any]], shared: Any, out: Dict[str, Any]) -> None:
    """The page's marks of a member's cell (tto/render.py): ``an`` - the row-side's anchor, the names of the members
    worked out from it; ``ao`` - a member worked out from the anchor ("TRY % · M5": its name and cell)."""
    a = h.group.anchor(h.pos, overlay, shared)
    if a is None:
        return
    if a is h.member:
        out["an"] = ", ".join(m.name for m in h.group.members if m is not a)
    else:
        out["ao"] = "%s · %s" % (a.name, a1(a.cells[h.pos][1]))
