"""What a row of a list of bonds holds belongs to its bond, not to the row.

A bond's row of a list - DİBS RV's (and with it DİBS Trading's), DİBS ASW's, each user's own Eurobond Kotaları, Tüm
Kâğıtlar - holds what was typed for that bond: the desk's pricing source, each user's manual clean price, known coupon,
repo, curve flag, an "Elle değer" over any cell of the row.  It is kept by the bond's ISIN, not by the row: when a list
changes - an ISIN typed or pasted over another, a bond moved, ☆ / ★, "+ ISIN ekle", a reset, a bond past its maturity, a
workbook file with another list - what a row holds goes with its bond to the bond's new row, for everybody (the desk's
values and the saved scenarios too), or - the bond off the list - goes with it.  A value typed on a row with no bond goes
when a bond takes the row.  All of it is one transaction with the key cells written (``Store.move_values``).

The store keeps the values by cell (every reader of an input reads a cell) and, for each list, the ISIN each row's values
belong to (``rowkeys.<list>``; a user's own list: ``rowkeys.<list>:<user>``; Tüm Kâğıtlar: its row map, ``bonds.rows``): a
change by any way is a change against those.  The first start of this version takes the rows as they are: what each row
holds is its bond's now.

Some rows are a form, not a bond, and keep their values: Eurobond Kotaları's own bid / ask (each user's own quote on that
row of their own list), the Hazine İhalesi blocks, Manuel Tahvil's periods.  VİOP's columns are the places of its
contracts ("1. kontrat" ...): what is typed for a place stays with the place when the contracts roll - but each user's own
VİOP bid / ask typed into the gold calculator for a contract is that contract's price, and goes when another contract
takes the column (:meth:`RowKeys.roll`).

The key cells - the lists' ISINs, VİOP's contract codes the watch follows a contract by - take no formula
(:meth:`RowKeys.key_cell`): a formula would change a key by itself, past all of this.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import extras as ex
from .xl.errors import XlError
from .xl.model import COLS, parse_a1
from .xl.tokenizer import col_to_index

log = logging.getLogger("tto")

_ALL = 16384                                     # (Excel's last column)
_A1 = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")
_MISS = object()

ISIN_KEY = ("%s listesinin ISIN hücresi: formül yazılamaz - satırdaki değerler kâğıda ISIN'iyle bağlıdır, kendiliğinden "
            "değişen bir ISIN onları kâğıdından ayırırdı; ISIN'i yazın")
CODE_KEY = ("VİOP kontrat kodu: formül yazılamaz - izleme ve alarmlar kontratı koduyla izler; kodu yazın ya da silin "
            "(boşken bugünün kontratı)")


class RowList(object):
    """A list of bonds: its ISINs (the ``key`` column, rows ``first`` to ``last``), whose list it is (``scope``: "shared"
    the desk's, "user" each user's own, "service" the dashboard writes it) and what of a row goes with its bond (``band``:
    sheet -> (first column, last column, columns that stay with the row)); ``scenarios``: the saved scenarios' values of
    its rows follow too (a user's own list is in their scenarios with its values: a scenario keeps its own)."""

    __slots__ = ("id", "book", "sheet", "key", "first", "last", "scope", "name", "band", "scenarios")

    def __init__(self, lid: str, book: str, sheet: str, key: str, first: int, last: int, scope: str, name: str,
                 band: Dict[str, Tuple[int, int, Tuple[int, ...]]], scenarios: bool = True):
        self.id, self.book, self.sheet, self.key = lid, book, sheet, key
        self.first, self.last, self.scope, self.name = first, last, scope, name
        self.band, self.scenarios = band, scenarios


def _col(letters: str) -> int:
    return col_to_index(letters)


#: the lists of bonds.  DİBS RV's rows run on in DİBS Trading's (EK_DIBS: the same rows); DİBS ASW's are B:U and its
#: helper columns (LR there is the holiday list); Eurobond Kotaları's own bid / ask (C, D) stay with their row
LISTS: Tuple[RowList, ...] = (
    RowList("dibs", "tto", "DİBS RV", "A", 5, 54, "shared", "DİBS RV", {"DİBS RV": (2, _ALL, ()), "EK_DIBS": (1, _ALL, ())}),
    RowList("asw", "asw", "ASW", "B", 7, 56, "shared", "DİBS ASW", {"ASW": (_col("C"), _col("EF"), ())}),
    RowList("bulk", "tto", "Bulk Bond", "A", 3, 52, "user", "Eurobond Kotaları",
            {"Bulk Bond": (2, _ALL, (_col("C"), _col("D")))}, scenarios=False),
    RowList("evren", "tto", ex.UNI_SHEET, "A", ex.UNI_FIRST, ex.UNI_LAST, "service", "Tüm Kâğıtlar",
            {ex.UNI_SHEET: (2, _ALL, ())}),
)
#: VİOP's contract codes, the desk's (by today's date unless typed): USDTRY 1-12, gold-TRY, gold-USD
VIOP_CODES = (("L1", "W1"), ("M45", "O45"), ("M60", "O60"))
#: the gold-TRY contracts and each user's own VİOP bid / ask typed for them in the gold calculator (a column a contract)
GOLD = ("M45", "O45")
GOLD_PRICES = ("EK_XAU", ("B", "C", "D"), (54, 55))
GOLD_KEY = "rowkeys.xau"


def isin_of(v: Any) -> str:
    """A key cell's value as the key it is ("" for none)."""
    return "".join(v.split()).upper() if isinstance(v, str) else ""


def _code(v: Any) -> str:
    return " ".join(v.split()) if isinstance(v, str) and "#" not in v else ""


def _plain(v: Any) -> Any:
    """A stored value as the engine takes it (numbers are floats)."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    return float(v) if isinstance(v, (int, float)) else v


def _json(v: Any) -> Any:
    return v.code if type(v) is XlError else v


def plan(old: Sequence[str], new: Sequence[str]) -> Dict[int, Optional[int]]:
    """Where what each place of a list holds goes when its keys change from ``old`` to ``new``: place -> its new place,
    or ``None`` (it goes).  A place whose key changed holds its old key's values: they follow the key to a place that
    took it now (the key listed twice: to the place it stays on); a key that left the list - or none, values typed on an
    empty row - takes them with it.  A place whose key did not change is not in it."""
    out: Dict[int, Optional[int]] = {}
    for k, (o, n) in enumerate(zip(old, new)):
        if o == n:
            continue
        if not o:
            out[k] = None
            continue
        took = [j for j, (a, b) in enumerate(zip(old, new)) if b == o and a != o]
        stays = [j for j, (a, b) in enumerate(zip(old, new)) if b == o and a == o]
        out[k] = (took + stays + [None])[0]
    return out


class RowKeys(object):
    """The lists' rows kept by their bonds (``Service.rowkeys``).  Everything here runs on the calculation thread."""

    def __init__(self, svc):
        self.svc = svc
        self._roll_seen: Optional[Tuple[str, Tuple[Any, ...]]] = None   # (day, the gold codes the desk typed) last looked at

    # ------------------------------------------------------------------ the lists
    def lists(self, book_id: str) -> List[RowList]:
        book = self.svc.books.get(book_id)
        return [x for x in LISTS if x.book == book_id and book is not None and x.sheet in book.model.sheet_index]

    @staticmethod
    def _store_key(lst: RowList, user: Optional[str] = None) -> str:
        return "rowkeys.%s" % lst.id + (":%s" % user if lst.scope == "user" else "")

    def _kept(self, lst: RowList, user: Optional[str] = None) -> Optional[List[str]]:
        """The ISINs each row's values belong to, as kept (None: not kept yet)."""
        got = self.svc.store.get(self._store_key(lst, user))
        if not isinstance(got, dict):
            return None
        return [isin_of(got.get(str(r))) for r in range(lst.first, lst.last + 1)]

    @staticmethod
    def _kept_form(lst: RowList, isins: Sequence[str]) -> Dict[str, str]:
        return {str(lst.first + k): v for k, v in enumerate(isins) if v}

    @staticmethod
    def _cells(lst: RowList, book) -> List[Tuple[int, int]]:
        si = book.model.sheet_index[lst.sheet]
        c = col_to_index(lst.key)
        return [(si, r * COLS + c) for r in range(lst.first, lst.last + 1)]

    def _now(self, lst: RowList, book, user: Optional[str] = None) -> List[str]:
        """The list's ISINs now: a user's own over the desk's over the workbook's own."""
        eng = book.engine
        mine = self.svc._overlay(user, book) if lst.scope == "user" and user else {}
        out = []
        for si, rc in self._cells(lst, book):
            v = mine.get((si, rc), _MISS)
            if v is _MISS:
                v = eng.input_value[si].get(rc, _MISS)
            if v is _MISS:
                v = eng.base_value(si, rc)
            out.append(isin_of(v))
        return out

    def _stored_now(self, lst: RowList, book, desk: Dict[Tuple[str, str], Any], mine: Dict[Tuple[str, str], Any]) -> List[str]:
        """The same from the store's values (the start: before the engine has them)."""
        out = []
        for si, rc in self._cells(lst, book):
            key = (book.id, book.ref(si, rc))
            v = mine.get(key, _MISS)
            if v is _MISS:
                v = desk.get(key, _MISS)
            if v is _MISS:
                v = book.engine.base_value(si, rc)
            out.append(isin_of(v))
        return out

    def _default(self, lst: RowList, book, cell: Tuple[int, int]) -> Any:
        """What a key cell holds once its value is cleared: the desk's (for a user's own list), else the workbook's."""
        si, rc = cell
        if lst.scope == "user":
            v = book.engine.input_value[si].get(rc, _MISS)
            if v is not _MISS:
                return v
        return book.engine.base_value(si, rc)

    # ------------------------------------------------------------------ a list changes
    def before_write(self, user: Optional[str], book, shared_vals: Dict[Tuple[int, int], Any],
                     shared_clear: Sequence[Tuple[int, int]], user_vals: Dict[Tuple[int, int], Any],
                     user_clear: Sequence[Tuple[int, int]]) -> Optional[Dict[str, Any]]:
        """A write (``_set_inputs``, ``_reset_inputs``) about to change the ISINs of a list: what each row held follows its
        bond - in one transaction with the ISINs written - before the write's own values go in (a value typed or pasted
        with the list lands on its row as typed).  Returns what moved and what went (for the one who wrote it), or None."""
        notes = []
        for lst in self.lists(book.id):
            if lst.scope == "service":
                continue
            cells = self._cells(lst, book)
            at = {c: k for k, c in enumerate(cells)}
            sets, clears = (shared_vals, shared_clear) if lst.scope == "shared" else (user_vals, user_clear)
            sets = {c: v for c, v in sets.items() if c in at}
            clears = [c for c in clears if c in at and c not in sets]
            if not sets and not clears:
                continue
            who = user if lst.scope == "user" else None
            now = self._now(lst, book, who)
            new = list(now)
            for c, v in sets.items():
                new[at[c]] = isin_of(v)
            for c in clears:
                new[at[c]] = isin_of(self._default(lst, book, c))
            kept = self._kept(lst, who)
            note = self._follow(lst, book, kept if kept is not None else now, new, who, kept is None,
                                keys={book.ref(*c): _json(v) for c, v in sets.items()},
                                key_clears=[book.ref(*c) for c in clears], by=user)
            if note:
                notes.append(note)
        return merge_notes(notes)

    def start(self) -> None:
        """As the service starts, before the engine has the desk's values: each list's rows against the ISINs they were
        kept for - a list changed meanwhile (another workbook file, an earlier version) moves what its rows hold; a list
        never kept is taken as it is (the first start of this version: what a row holds is its bond's now)."""
        store = self.svc.store
        for lst in LISTS:
            book = self.svc.books.get(lst.book)
            if book is None or lst.scope == "service" or lst.sheet not in book.model.sheet_index:
                continue
            desk = store.shared_inputs(book.id)
            whose: List[Optional[str]] = [None] if lst.scope == "shared" else [u["name"] for u in store.users()]
            for who in whose:
                mine = store.user_inputs(who, book.id) if who else {}
                kept = self._kept(lst, who)
                if who and kept is None and not mine:
                    continue                    # (nothing of theirs here: kept when they first write their list)
                now = self._stored_now(lst, book, desk, mine)
                if kept is None:
                    store.put(self._store_key(lst, who), self._kept_form(lst, now))
                    continue
                note = self._follow(lst, book, kept, now, who, stored=lambda ref, desk=desk: (book.id, ref) in desk)
                if note:
                    log.warning("kâğıt listesi açılışta değişmiş bulundu%s: %s", " (%s)" % who if who else "", note["text"])

    def loaded(self, user: str) -> None:
        """A scenario loaded: the user's own lists are as it had them, and so are their rows' values (nothing moves)."""
        for lst in LISTS:
            book = self.svc.books.get(lst.book)
            if lst.scope != "user" or book is None or lst.sheet not in book.model.sheet_index:
                continue
            self.svc.store.put(self._store_key(lst, user), self._kept_form(lst, self._now(lst, book, user)))

    def universe(self, book, before: Dict[str, int], after: Dict[str, int]) -> Optional[Dict[str, Any]]:
        """Tüm Kâğıtlar's rows changed (``Service._sync_universe``): what was typed on the row of a bond that left it goes
        with it (a bond keeps its row; a row is taken again only when no unused one is left)."""
        lst = next(x for x in LISTS if x.id == "evren")
        n = lst.last - lst.first + 1
        old, new = [""] * n, [""] * n
        for side, rows in ((old, before), (new, after)):
            for isin, r in rows.items():
                if lst.first <= r <= lst.last:
                    side[r - lst.first] = isin_of(isin)
        return self._follow(lst, book, old, new)

    def _follow(self, lst: RowList, book, old: List[str], new: List[str], who: Optional[str] = None,
                missing: bool = False, keys: Optional[Dict[str, Any]] = None, key_clears: Sequence[str] = (),
                by: Optional[str] = None, stored: Optional[Callable[[str], bool]] = None) -> Optional[Dict[str, Any]]:
        moves = plan(old, new)
        put = [] if lst.scope == "service" else [(self._store_key(lst, who), self._kept_form(lst, new))]
        if not moves:
            if missing and put:
                self.svc.store.put(*put[0])
            return None
        seed, blank = self._file_values(lst, book, moves, stored)
        res = self.svc.store.move_values(book.id, self._where(lst, moves), users=[who] if lst.scope == "user" else None,
                                         shared=lst.scope != "user", scenarios=lst.scenarios, keys=keys or None,
                                         key_clears=key_clears, key_user=who, by=by, put=put, seed=seed, blank=blank)
        self._engine(book, res)
        return self._told(lst, old, moves, res)

    @staticmethod
    def _file_values(lst: RowList, book, moves: Dict[int, Optional[int]],
                     stored: Optional[Callable[[str], bool]] = None) -> Tuple[Dict[str, Any], set]:
        """The workbook's own values in the desk's cells of the rows whose bond changed (a pricing source the file has for
        the bond on its row): the bond's like a value typed - they go with it (``seed``); and those cells, a blank once
        their value went (``blank``: the file's value was the bond's that left, not the next one's)."""
        if lst.scope == "user" or not moves:
            return {}, set()
        if stored is None:
            def stored(ref: str) -> bool:
                si, rc = book.cell(ref)
                return rc in book.engine.input_value[si]
        seed: Dict[str, Any] = {}
        blank = set()
        for (si, rc), d in book.inputs.items():
            if d.scope != "shared":
                continue
            band = lst.band.get(book.model.sheets[si].name)
            r, c = divmod(rc, COLS)
            if band is None or (r - lst.first) not in moves or not band[0] <= c <= band[1] or c in band[2]:
                continue
            v = book.engine.base_value(si, rc)
            if v is None:
                continue
            ref = book.ref(si, rc)
            blank.add(ref)
            if not stored(ref):
                seed[ref] = v
        return seed, blank

    @staticmethod
    def _where(lst: RowList, moves: Dict[int, Optional[int]]) -> Callable[[str], Any]:
        """Where a stored cell's value goes when the rows move (``moves``): its new cell, None (it goes) or False (it
        stays: a cell of no row of the list, a column that stays with its row)."""
        def where(ref: str) -> Any:
            sheet, _, addr = ref.rpartition("!")
            band = lst.band.get(sheet.strip("'"))
            m = _A1.match(addr) if band is not None else None
            if m is None:
                return False
            k = int(m.group(2)) - lst.first
            if k not in moves:
                return False
            c = col_to_index(m.group(1))
            if not band[0] <= c <= band[1] or c in band[2]:
                return False
            t = moves[k]
            return None if t is None else "%s!%s%d" % (sheet, m.group(1), lst.first + t)
        return where

    def _engine(self, book, res: Dict[str, Any]) -> None:
        """The engine and the users' values in memory as the store has them now."""
        svc = self.svc

        def cell(ref: str) -> Optional[Tuple[int, int]]:
            try:
                return book.cell(ref)
            except (KeyError, ValueError):
                return None

        out = [cell(c) for u, c in res["dropped"] if u is None] + [cell(c) for u, c, _, _ in res["moved"] if u is None]
        put = {cell(c): _plain(v) for u, _, c, v in res["moved"] if u is None}
        put.update({cell(c): None for c in res.get("blanked") or ()})
        out = [k for k in out if k is not None]
        put = {k: v for k, v in put.items() if k is not None}
        if out:
            book.engine.clear_inputs(out)
        if put:
            for k in put:
                if k not in book.inputs:
                    book.declare(book.ref(*k), scope="shared", group="adhoc-shared")
            book.engine.set_inputs(put)
        users = {u for u, _ in res["dropped"] if u} | {u for u, _, _, _ in res["moved"] if u}
        for u in users:
            ov = svc._overlays.get((u, book.id))
            if ov is None:
                continue                        # (read from the store when they are next here)
            ov = dict(ov)
            for uu, c in res["dropped"]:
                if uu == u:
                    ov.pop(cell(c), None)
            for uu, c, _, _ in res["moved"]:
                if uu == u:
                    ov.pop(cell(c), None)
            for uu, _, c, v in res["moved"]:
                k = cell(c) if uu == u else None
                if k is not None:
                    if k not in book.inputs:
                        book.declare(c, scope="user", group="adhoc")
                    ov[k] = _plain(v)
            svc._overlays[(u, book.id)] = ov
            if u in book.engine.users:
                book.engine.set_user_inputs(u, ov)
        if users or out or put:
            svc._note_private()

    @staticmethod
    def _told(lst: RowList, old: List[str], moves: Dict[int, Optional[int]], res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """What the one who changed the list is told: each bond whose row's values moved or went, how many and where."""
        def place(ref: str) -> Optional[int]:
            m = _A1.match(ref.rpartition("!")[2])
            return int(m.group(2)) - lst.first if m else None

        moved: Dict[Optional[int], int] = {}
        gone: Dict[Optional[int], int] = {}
        for _, c, _, _ in res["moved"]:
            moved[place(c)] = moved.get(place(c), 0) + 1
        for _, c in res["dropped"]:
            gone[place(c)] = gone.get(place(c), 0) + 1
        for c in res.get("scenario_cells_moved") or ():
            moved[place(c)] = moved.get(place(c), 0) + 1
        for c in res.get("scenario_cells_dropped") or ():
            gone[place(c)] = gone.get(place(c), 0) + 1
        out_moved, out_gone, parts = [], [], []
        for k in sorted(moves):
            m, g = moved.get(k, 0), gone.get(k, 0)
            row, t = lst.first + k, moves[k]
            if m and t is not None:
                out_moved.append({"isin": old[k], "from": row, "to": lst.first + t, "values": m})
                parts.append("%s satır %d → %d (%d değer taşındı)" % (old[k], row, lst.first + t, m))
            if g:
                out_gone.append({"isin": old[k], "row": row, "values": g})
                if t is not None:
                    parts.append("%s: %d değer yeni satırında zaten vardı, silindi" % (old[k], g))
                elif old[k]:
                    parts.append("%s listeden çıktı: satır %d, %d değer silindi" % (old[k], row, g))
                else:
                    parts.append("satır %d kâğıtsızken yazılmış %d değer silindi" % (row, g))
        if not parts:
            return None
        text = "%s · kâğıt satırlarının değerleri kâğıtla gider: %s" % (lst.name, "; ".join(parts))
        if res.get("scenarios"):
            text += " · %d senaryo da" % res["scenarios"]
        return {"lists": [lst.id], "moved": out_moved, "cleared": out_gone, "scenarios": res.get("scenarios") or 0, "text": text}

    # ------------------------------------------------------------------ VİOP: the gold contracts' own prices
    def roll_due(self) -> bool:
        """Whether the gold contracts may have changed since last looked at (any thread): a new day, or the desk typed
        or cleared a code (the codes follow today's date by themselves otherwise)."""
        book = self.svc.books.get("tto")
        if book is None or "VIOP" not in book.model.sheet_index:
            return False
        si = book.model.sheet_index["VIOP"]
        r, c1 = divmod(parse_a1(GOLD[0]), COLS)
        c2 = parse_a1(GOLD[1]) % COLS
        typed = tuple(book.engine.input_value[si].get(r * COLS + c) for c in range(c1, c2 + 1))
        mark = (self.svc.today_iso(), typed)
        if mark == self._roll_seen:
            return False
        self._roll_seen = mark
        return True

    def roll(self) -> Optional[Dict[str, Any]]:
        """VİOP's gold-TRY contracts (``VIOP!M45:O45``) now against the ones kept: a column whose contract changed - it
        expired, or the desk typed another - loses each user's own VİOP bid / ask typed for the contract it had
        (``EK_XAU!B54:D55``; in the saved scenarios too).  The other values typed per column stay with the column."""
        book = self.svc.books.get("tto")
        sheet, cols, rows = GOLD_PRICES
        if book is None or "VIOP" not in book.model.sheet_index or sheet not in book.model.sheet_index:
            return None
        si = book.model.sheet_index["VIOP"]
        r, c1 = divmod(parse_a1(GOLD[0]), COLS)
        c2 = parse_a1(GOLD[1]) % COLS
        calc = book.engine.shared
        now = [_code(calc.get(si, r, c)) for c in range(c1, c2 + 1)]
        store = self.svc.store
        kept = store.get(GOLD_KEY)
        if not isinstance(kept, list) or len(kept) != len(now):
            store.put(GOLD_KEY, now)
            return None
        gone = [k for k, (a, b) in enumerate(zip(kept, now)) if a and b and a != b]
        keep = [b or a for a, b in zip(kept, now)]
        if not gone:
            if keep != kept:
                store.put(GOLD_KEY, keep)
            return None
        drop = {cols[k] for k in gone if k < len(cols)}

        def where(ref: str) -> Any:
            s, _, addr = ref.rpartition("!")
            m = _A1.match(addr)
            return None if s.strip("'") == sheet and m and m.group(1) in drop and int(m.group(2)) in rows else False

        res = store.move_values(book.id, where, shared=False, scenarios=True, put=[(GOLD_KEY, keep)])
        self._engine(book, res)
        if res["dropped"] or res["scenario_dropped"]:
            log.info("VİOP altın kontratı değişti (%s): kendi VİOP fiyatları silindi - %d değer, %d senaryo",
                     ", ".join("%s → %s" % (kept[k], now[k]) for k in gone), len(res["dropped"]), res["scenarios"])
        return res

    # ------------------------------------------------------------------ the key cells
    def key_cell(self, book, si: int, rc: int) -> Optional[str]:
        """Why a cell takes no formula as a key of a list (its ISINs, VİOP's contract codes) - None: it is no key."""
        sheet = book.model.sheets[si].name
        r, c = divmod(rc, COLS)
        for lst in LISTS:
            if lst.scope != "service" and lst.book == book.id and lst.sheet == sheet and c == col_to_index(lst.key) \
                    and lst.first <= r <= lst.last:
                return ISIN_KEY % lst.name
        if book.id == "tto" and sheet == "VIOP":
            for a, b in VIOP_CODES:
                ra, ca = divmod(parse_a1(a), COLS)
                cb = parse_a1(b) % COLS
                if r == ra and ca <= c <= cb:
                    return CODE_KEY
        return None


def merge_notes(notes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What several lists' changes moved / took, told as one (the trading list and the ASW list a ☆ changes both)."""
    if not notes:
        return None
    if len(notes) == 1:
        return notes[0]
    return {"lists": [x for n in notes for x in n["lists"]], "moved": [x for n in notes for x in n["moved"]],
            "cleared": [x for n in notes for x in n["cleared"]], "scenarios": sum(n["scenarios"] for n in notes),
            "text": " · ".join(n["text"] for n in notes)}
