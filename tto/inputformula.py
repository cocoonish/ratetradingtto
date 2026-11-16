"""Formulas typed into the input cells of the workbook pages, as in Excel: ``=`` and a click on another cell puts its
address in (``=C60+7`` in a value date) - over the dashboard's live cells.

An input keeps its formula beside its value (the store's ``formula`` column: the same scope and key).  The value is the
formula's result, set exactly as a typed value is: the engine, the other pages, the launchpads, the number formats see a
value.  A personal input's formula (yellow) is that user's and reads their own view - their inputs, their "Elle değer"
values; a shared input's (green) is everybody's and reads what everybody sees.  A reference without a sheet is the
input's own sheet (``=P60`` on MASA is ``MASA!P60``); the others as in the calc sheets (calc.py, whose compiler and
evaluation this uses): ``Forward!D2``, ``'C & R'!B5``, ``[sofr]SOFR_FOMC!B9``, the workbook's names.

Live, on the calculation thread: a formula is evaluated again when something it read may have changed - after inputs
were written, after the market or the clock moved (each new generation), at the start (a user's own once their
calculation is made again: back from away, a scenario loaded).  What it read is known by the engine's dependency masks:
a formula nothing it read changed is not evaluated, and its value is set only when it changed.  Nobody with a formula:
nothing is done.

Refused as typed, with the reason: a Bloomberg function (the daily data limit, ``calc.check_formula``), a formula that
cannot be read or names what is not there, a cycle (the formula reads - through the workbook's formulas or other
formula inputs - the cell it is typed into: the engine's masks tell that a read depends on an input, the formulas'
references tell it exactly when inputs share a bit), a cell whose typed values are restricted (a list, "Elle değer", a
cell the meeting calendar moves - its value goes with its meeting, a formula's references would not -, a key of a list:
an ISIN of a list of bonds, a VİOP contract code - what is kept by it would not follow a key a formula changes), a shared formula
reading an administrators' page (Motor: a shared formula is everybody's, it reads with nobody's rights), and a formula
reading live data (prices, NOW()) into a cell that goes into a Bloomberg request: a new request on every tick.

What never spins or sticks: a cycle that appears later (an input it reads went back to its own default) - the formulas
still changing after a round per formula are stopped, their value #CALC!, the reason on the cell; a formula over the
evaluation's time limit (a cold calculation after a restart) is tried again later, with a growing pause, and stopped only
after several times in a row.  A stopped formula is tried again when its owner writes an input (once at once, then after
a growing pause) or types it again.  Where its value goes into a Bloomberg request it keeps its last good value instead
of an error: an error value there would be a request with an empty argument (``marketdata.base.override_pairs``).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import calc as _calc
from .calc import BLOOMBERG, UNREADABLE, CalcError, _Ctx, _plain, _Stop, check_formula, normalise
from .service import EngineThread
from .xl.engine import addin_cells
from .xl.errors import E_CALC, E_NAME, E_REF, E_VALUE, XlError
from .xl.model import COLS
from .xl.parser import parse_template, walk
from .xl.tokenizer import to_template

SHARED = ""                            # the scope of the desk's (shared) inputs; a user's own: their key

BLOOMBERG_INPUT = BLOOMBERG.replace("hesap tablosunda", "girdi formüllerinde")
LIST = "bu hücre listeden bir değer alır (%s): formül yazılamaz"
MEETING = "toplantı tarihleri takvimden değişir (Ayarlar → Toplantı takvimi): formül yazılamaz"
CALENDAR = ("toplantı takvimiyle kayan hücre: formül yazılamaz (takvim değişince değeri toplantısıyla taşınır, formülün "
            "başvuruları taşınmaz)")
NOT_INPUT = "formül yalnızca girdi hücrelerine (sarı / yeşil) yazılır - \"Elle değer\" bir sabittir"
CYCLE = "döngüsel başvuru: %s - formül yazıldığı hücreyi okuyor"
LIVE = ("bu hücrenin değeri bir Bloomberg isteğine girer (%s): canlı fiyat ya da NOW() okuyan bir formül her değişimde "
        "yeni bir istek doğurur (günlük veri limiti) - canlı olmayan hücreleri kullanın ya da değeri elle yazın")
STOPPED_CYCLE = "Döngüsel başvuru: %s - formül durduruldu (#CALC!); formülü düzeltin ya da yeniden yazın"
STOPPED_LIVE = ("formül canlı veri okumaya başladı; bu hücrenin değeri bir Bloomberg isteğine girdiği için durduruldu "
                "(günlük veri limiti) - formülü yeniden yazın")
STOPPED_RESTLESS = "formülün değeri her hesapta değişiyor - durduruldu (#CALC!); formülü yeniden yazın"
STOPPED_SLOW = "%s - %d kez üst üste; formül durduruldu, yeniden yazınca denenir"
RETRYING = "%s - biraz sonra yeniden denenecek"
KEPT = " · Bloomberg isteğine giren hücre: son iyi değeri kaldı"
DYNAMIC = ("OFFSET", "INDIRECT")      # functions whose cells are known only when computed (the engine has none)

_MISS = object()
_HERE = (0, 0)                         # where the notes of an evaluation land (calc's context keys them by own cell)
_NOTHING = {"cells": {}, "fmt": {}, "rows": 1, "cols": 1}
log = logging.getLogger("tto")


class FormulaError(ValueError):
    """A formula refused as typed (the message says why, in the desk's words)."""


class _Entry(object):
    """One input typed as a formula: where it is, its text, what it read when last evaluated."""

    __slots__ = ("scope", "bid", "si", "rc", "r", "c", "ref", "text", "metas", "boxes", "note", "error", "frozen",
                 "stopped", "timed_out", "denied", "feeds", "good", "timeouts", "retry_at", "retry_round", "freezes",
                 "thaw_after")

    def __init__(self, scope: str, book, si: int, rc: int, text: str):
        self.scope = scope
        self.bid = book.id
        self.si, self.rc = si, rc
        self.r, self.c = divmod(rc, COLS)
        self.ref = book.ref(si, rc)
        self.text = text
        self.metas: Optional[Dict[str, Tuple[int, int, int, int]]] = None   # book -> what was read (calc._Ctx.release)
        self.boxes: Any = _MISS            # the cells its text names, [(book, sheet, r1, c1, r2, c2)] (None: unknown)
        self.note: Optional[str] = None    # what its error value means
        self.error: Optional[str] = None   # why it was stopped
        self.frozen = False
        self.stopped = False               # over a hard limit of the evaluation (cells read, a range's size)
        self.timed_out = False             # over the evaluation's time limit (tried again later)
        self.denied = False                # read a sheet that is not its owner's to read
        self.feeds: Optional[str] = None   # what Bloomberg request its value goes into ("" none; None: not looked at)
        self.good: Any = _MISS             # its value before the round under way (kept where it feeds Bloomberg)
        self.timeouts = 0                  # time-outs in a row
        self.retry_at = 0.0                # (monotonic) not evaluated before this - after a time-out
        self.retry_round = -1              # the round it timed out in: not tried again in that round
        self.freezes = 0                   # times stopped in a row
        self.thaw_after = 0.0              # (monotonic) an owner's write tries it again from this time on

    @property
    def key(self) -> Tuple[str, int, int]:
        return self.bid, self.si, self.rc


class InputFormulas(object):
    """Every input typed as a formula (``Service.formulas``).  Its state is the calculation thread's; the store tells it
    of any write of the inputs (``Store.on_inputs``) from any thread."""

    #: pauses (seconds) before a formula over the time limit is tried again: after the 1st time-out, the 2nd ...
    BACKOFF = (2.0, 10.0, 30.0)
    #: time-outs in a row that stop a formula
    STOP_AFTER = 4
    #: a stopped formula is tried again at its owner's next write; stopped again, after this pause (doubling each time)
    THAW_BASE = 30.0
    THAW_MAX = 900.0

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self._scopes: Dict[str, Dict[Tuple[str, int, int], _Entry]] = {}   # scope -> cell -> entry
        self._stale: set = set()               # scopes a writer changed in the store: read again
        self._roles: set = set()               # users whose role changed: their formulas evaluated again
        self.pending: set = set()              # users whose calculation was made again: evaluated before it is read
        self._busy: set = set()                # scopes being evaluated now (no evaluation of them inside)
        self._queued = False
        self._rounds = 0
        self._timer: Optional[threading.Timer] = None
        self._timer_at = 0.0
        self._down: Dict[Tuple[str, int, int], Optional[frozenset]] = {}
        self._addins: Dict[str, frozenset] = {}
        self._live: Dict[str, Tuple[int, int]] = {}
        self.jobs = 0                          # evaluation rounds queued after a new generation (tests)
        self.evaluations = 0                   # formulas evaluated (tests)

    # ------------------------------------------------------------------ what there is
    def start(self) -> None:
        """Calculation thread, as the service starts: every formula kept, the desk's evaluated (a user's own when their
        calculation is made: :meth:`catch_up`)."""
        rows: Dict[str, Dict[Tuple[str, str], str]] = {SHARED: self.svc.store.shared_formulas()}
        for user in self.svc.store.formula_users():
            rows[user] = self.svc.store.user_formulas(user)
        for scope, got in rows.items():
            self._take(scope, got)
        self.svc.store.on_inputs = self._noted
        self._settle_scope(SHARED)

    @property
    def active(self) -> bool:
        return bool(self._scopes) or bool(self._stale)

    def has(self, user: Optional[str]) -> bool:
        return bool(user) and user in self._scopes

    def entry(self, user: Optional[str], bid: str, si: int, rc: int) -> Optional[_Entry]:
        """The formula of an input as ``user`` sees it: theirs, or the desk's."""
        for scope in ((user, SHARED) if user else (SHARED,)):
            e = self._scopes.get(scope, {}).get((bid, si, rc))
            if e is not None:
                return e
        return None

    def marks(self, user: Optional[str], bid: str, si: int) -> Dict[Tuple[int, int], _Entry]:
        """The formula inputs of one sheet as ``user`` sees them: (row, col) -> entry."""
        out: Dict[Tuple[int, int], _Entry] = {}
        for scope in ((SHARED, user) if user else (SHARED,)):
            for e in self._scopes.get(scope, {}).values():
                if e.bid == bid and e.si == si:
                    out[(e.r, e.c)] = e
        return out

    def _noted(self, user: Optional[str], formulas: bool) -> None:
        """The store wrote inputs (any thread): their scope is read again before it is next used."""
        scope = SHARED if user is None else user
        with self._lock:
            if scope == "*":
                self._stale.update(list(self._scopes))
            elif formulas or scope in self._scopes:
                self._stale.add(scope)

    def role_changed(self, user: str) -> None:
        """An account's role changed (any thread): its formulas are evaluated again with the role it has now."""
        with self._lock:
            if user in self._scopes:
                self._roles.add(user)
        if user in self._scopes:
            self.schedule()

    def _sync(self) -> None:
        if self._roles:
            with self._lock:
                roles = set(self._roles)
                self._roles.clear()
            for user in roles:
                for e in self._scopes.get(user, {}).values():
                    e.metas = None                    # (what it may read changed: evaluated again)
                    if e.frozen:
                        self._thaw(e)
                self.svc._formulas_changed(user)
        if not self._stale:
            return
        with self._lock:
            stale = set(self._stale)
            self._stale.clear()
        store = self.svc.store
        for scope in stale:
            self._take(scope, store.shared_formulas() if scope == SHARED else store.user_formulas(scope))

    def _take(self, scope: str, rows: Dict[Tuple[str, str], str]) -> None:
        """A scope's formulas as the store keeps them: an entry whose text is the same is kept (with what it read).  One
        in a cell the meeting calendar moves (an earlier version took it) goes: its value stays, the log says so."""
        old = self._scopes.get(scope, {})
        new: Dict[Tuple[str, int, int], _Entry] = {}
        moved: List[Tuple[str, str, str]] = []
        keys: List[Tuple[str, str, str]] = []
        for (bid, ref), text in rows.items():
            book = self.svc.books.get(bid)
            if book is None or not isinstance(text, str):
                continue
            try:
                si, rc = book.cell(ref)
            except (KeyError, ValueError):
                continue
            if self.svc._meeting_date_cell(book, si, rc) or self.svc._moved_by_calendar(book, si, rc):
                moved.append((bid, ref, text))
                continue
            if self.svc.rowkeys.key_cell(book, si, rc):
                keys.append((bid, ref, text))          # (a list's key: an ISIN, a VİOP contract code - rowkeys.py)
                continue
            d = book.inputs.get((si, rc))
            if d is None or (d.scope == "shared") != (scope == SHARED) or d.group in ("adhoc", "adhoc-shared"):
                continue                               # (no longer an input of this scope: its value stays a value)
            e = old.get((bid, si, rc))
            if e is None or e.text != text:
                try:
                    check_formula(text, BLOOMBERG_INPUT)
                except CalcError:
                    continue                           # (kept by another version and not read now: a value)
                e = _Entry(scope, book, si, rc, text)
            new[(bid, si, rc)] = e
        if moved:
            self.svc.store.drop_formulas(scope or None, [(bid, ref) for bid, ref, _ in moved])
            for bid, ref, text in moved:
                log.warning("girdi formülü kaldırıldı (toplantı takvimiyle kayan hücre; değeri kaldı): %s %s!%s %s",
                            scope or "ortak", bid, ref, text)
        if keys:
            self.svc.store.drop_formulas(scope or None, [(bid, ref) for bid, ref, _ in keys])
            for bid, ref, text in keys:
                log.warning("girdi formülü kaldırıldı (listenin anahtar hücresi: ISIN / kontrat kodu; değeri kaldı): %s %s!%s %s",
                            scope or "ortak", bid, ref, text)
        with self._lock:
            if new:
                self._scopes[scope] = new
            else:
                self._scopes.pop(scope, None)
        if set(old) != set(new) or any(old[k].text != new[k].text for k in new if k in old):
            self.svc._formulas_changed(scope)

    # ------------------------------------------------------------------ typed
    def accept(self, user: str, book, si: int, rc: int, d, text: str, calc, batch: List[_Entry]) -> Tuple[Any, _Entry]:
        """A formula typed into an input (calculation thread) -> (its value, its entry); :class:`FormulaError` says why
        it is refused.  ``batch``: the formulas accepted before it in the same write (a cycle among them is one)."""
        text = text.strip()
        if self.svc._meeting_date_cell(book, si, rc):
            raise FormulaError(MEETING)
        if self.svc._moved_by_calendar(book, si, rc):
            raise FormulaError(CALENDAR)
        if d is None or d.group in ("adhoc", "adhoc-shared"):
            raise FormulaError(NOT_INPUT)
        keyed = self.svc.rowkeys.key_cell(book, si, rc)
        if keyed:
            raise FormulaError(keyed)                  # (a list's key: an ISIN, a VİOP contract code - rowkeys.py)
        opts = book.options_for(si, rc, calc)
        if d.kind == "list" or opts:
            raise FormulaError(LIST % ", ".join((opts or [])[:8]))
        try:
            check_formula(text, BLOOMBERG_INPUT)
        except CalcError as exc:
            raise FormulaError(str(exc))
        scope = SHARED if d.scope == "shared" else user
        e = _Entry(scope, book, si, rc, text)
        cs = self.svc.calcsheets
        cs._tables()
        fn, notes, _ = cs._compile(text, e.r, e.c)
        if fn is None or notes.get("bad"):
            raise FormulaError(UNREADABLE)
        if notes.get("function") or notes.get("name"):
            raise FormulaError(cs._tip(text, e.r, e.c, E_NAME))
        if notes.get("sheet"):
            raise FormulaError(cs._tip(text, e.r, e.c, E_REF))
        # the scope's formulas brought up to date first: what they read decides whether this one closes a cycle
        self._sync()
        self._settle_scope(scope, wake=True)
        value = self._run(e)
        if e.denied:
            raise FormulaError(e.note or "erişim yok")
        if e.stopped or e.timed_out:
            raise FormulaError(e.note or "formül hesaplanamadı")
        ring = self._ring(e, [x for x in batch if x.scope == scope])
        if ring:
            raise FormulaError(CYCLE % " → ".join(ring))
        if self._reads_live(e):
            feeds = self._feeds(e)
            if feeds:
                raise FormulaError(LIVE % feeds)
        return value, e

    def wrote(self, book, scope: str, values: Dict[Tuple[int, int], Any], cleared: List[Tuple[int, int]],
              entries: Dict[Tuple[int, int], _Entry]) -> None:
        """Inputs of a scope were written (``_set_inputs``, ``_reset_inputs``): a cell written or cleared loses its formula
        unless it got one now (``entries``); what was stopped in the scope is tried again (its owner wrote an input)."""
        cur = dict(self._scopes.get(scope, {}))
        changed = False
        for k in list(values) + list(cleared):
            if (book.id,) + k in cur and k not in entries:
                del cur[(book.id,) + k]
                changed = True
        for k, e in entries.items():
            old = cur.get((book.id,) + k)
            cur[(book.id,) + k] = e
            changed = changed or old is None or old.text != e.text
        now = time.monotonic()
        for e in cur.values():
            if e.frozen and now >= e.thaw_after:
                self._thaw(e)
                changed = True                     # (its cell's reason goes: drawn again)
        with self._lock:
            if cur:
                self._scopes[scope] = cur
            else:
                self._scopes.pop(scope, None)
        if changed:
            self.svc._formulas_changed(scope)

    def cleared(self, scope: str, book, cells: Optional[List[Tuple[int, int]]]) -> None:
        """Inputs of a scope were cleared in a workbook (``cells``: these; None: all of the scope's there)."""
        cur = self._scopes.get(scope)
        if not cur:
            return
        keep = {k: e for k, e in cur.items()
                if k[0] != book.id or (cells is not None and (k[1], k[2]) not in cells)}
        thawed = False
        now = time.monotonic()
        for e in keep.values():
            if e.frozen and now >= e.thaw_after:
                self._thaw(e)
                thawed = True
        if len(keep) != len(cur) or thawed:
            with self._lock:
                if keep:
                    self._scopes[scope] = keep
                else:
                    self._scopes.pop(scope, None)
            self.svc._formulas_changed(scope)

    @staticmethod
    def _thaw(e: _Entry) -> None:
        """A stopped formula tried again (its owner wrote an input, its role changed)."""
        e.frozen, e.error, e.metas = False, None, None
        e.timeouts, e.retry_at = 0, 0.0

    # ------------------------------------------------------------------ live
    def schedule(self) -> None:
        """A new generation (any thread): the formulas looked at on the calculation thread, ahead of the pages."""
        with self._lock:
            if self._queued:
                return
            self._queued = True
        try:
            self.svc.et.submit_at(EngineThread.WRITE, self._job)
        except BaseException:
            with self._lock:
                self._queued = False               # (not queued after all: the next generation asks again)
            raise
        self.jobs += 1

    def _job(self) -> None:
        with self._lock:
            self._queued = False
        try:
            changed = self.settle()
        except Exception as exc:  # noqa: BLE001 - the next generation tries again (and the log says what failed)
            self.svc.ops.failure("girdi formülleri", exc)
            return
        if changed:
            # values that followed what they read - the market, the clock, an input whose own write told the desk
            # already: a market move for the pages kept (an entry or a change of a formula is a desk change itself)
            self.svc.bump(market=True)

    def settle(self) -> bool:
        """Calculation thread: every formula whose reads changed evaluated again - the desk's first (a user's own may read
        them), a user's while their calculation is there.  True: a value changed."""
        self._sync()
        changed = False
        for scope in [SHARED] + sorted(s for s in self._scopes if s):
            changed = self._settle_scope(scope) or changed
        return changed

    def catch_up(self, user: str) -> None:
        """The user's calculation was made again (``Service._calc``): their formulas evaluated before it is read."""
        if user in self._busy:
            return
        self.pending.discard(user)
        self._sync()
        if self._settle_scope(user):
            self.svc.bump(market=True)

    def _later(self, delay: float) -> None:
        """A round of evaluation when a formula's pause after a time-out is over (none comes with a generation then)."""
        at = time.monotonic() + delay
        with self._lock:
            if self._timer is not None and self._timer_at <= at:
                return                                 # (one coming sooner already)
            if self._timer is not None:
                self._timer.cancel()
            t = self._timer = threading.Timer(delay + 0.05, self._wake)
            self._timer_at = at
        t.daemon = True
        t.start()

    def _wake(self) -> None:
        with self._lock:
            self._timer = None
        if not self.svc._stop.is_set():
            self.schedule()

    def _settle_scope(self, scope: str, wake: bool = False) -> bool:
        if scope in self._busy:
            return False
        ents = list(self._scopes.get(scope, {}).values())
        if scope and not wake:
            ents = [e for e in ents if (scope, e.bid) in self.svc._overlays]       # (a user away: when they are back)
        ents = [e for e in ents if not e.frozen]
        if not ents:
            return False
        self._busy.add(scope)
        self._rounds += 1
        round_ = self._rounds
        start = time.monotonic()
        for e in ents:
            e.good = self._current(e)                  # (what a cell Bloomberg reads keeps when the formula is stopped)
        changed = False
        try:
            for _ in range(len(ents) + 2):
                dirty = [e for e in ents if not e.frozen and e.retry_round != round_ and e.retry_at <= start
                         and not self._fresh(e)]
                if not dirty:
                    return changed
                sets: Dict[str, Dict[Tuple[int, int], Any]] = {}
                for e in dirty:
                    v = self._run(e)
                    if e.timed_out:
                        self._slow(e, round_, sets)
                        continue
                    e.timeouts, e.retry_at = 0, 0.0
                    if e.stopped or e.denied:
                        self._freeze(e, e.note or "formül hesaplanamadı", sets)
                        continue
                    if self._reads_live(e) and self._feeds(e):
                        self._freeze(e, STOPPED_LIVE, sets)
                        continue
                    if type(v) is XlError:
                        # an error read back through its own cell (a cycle settled on #CALC! after a retry): the cycle
                        ring = self._ring(e, [])
                        if ring:
                            self._freeze(e, STOPPED_CYCLE % " → ".join(ring), sets)
                            continue
                    e.freezes = 0
                    if not _same(v, self._current(e)):
                        sets.setdefault(e.bid, {})[(e.si, e.rc)] = v
                if sets:
                    self._apply(scope, sets)
                    changed = True
            # still changing after a round per formula: what reads itself is stopped (never spins)
            stuck = [e for e in ents if not e.frozen and e.retry_round != round_ and e.retry_at <= start
                     and not self._fresh(e)]
            if stuck:
                sets = {}
                found = [(e, self._ring(e, [])) for e in stuck]
                ringed = [(e, ring) for e, ring in found if ring]
                for e, ring in ringed or found:
                    self._freeze(e, STOPPED_CYCLE % " → ".join(ring) if ring else STOPPED_RESTLESS, sets)
                self._apply(scope, sets)
                changed = True
            return changed
        finally:
            self._busy.discard(scope)

    def _slow(self, e: _Entry, round_: int, sets: Dict[str, Dict[Tuple[int, int], Any]]) -> None:
        """Over the time limit (a calculation cold after a restart, a busy moment): tried again after a pause - its value
        stays meanwhile -, stopped after several times in a row."""
        e.timeouts += 1
        e.retry_round = round_
        why = e.note or "Hesap süresi sınırı aşıldı"
        if e.timeouts >= self.STOP_AFTER:
            self._freeze(e, STOPPED_SLOW % (why, e.timeouts), sets)
            return
        delay = self.BACKOFF[min(e.timeouts, len(self.BACKOFF)) - 1]
        e.retry_at = time.monotonic() + delay
        e.note = RETRYING % why
        self._later(delay)

    def _freeze(self, e: _Entry, why: str, sets: Dict[str, Dict[Tuple[int, int], Any]]) -> None:
        """Stopped: its value #CALC! with the reason on the cell - or, where the value goes into a Bloomberg request, the
        value it had before this round (an error there would be a new request with an empty argument)."""
        e.frozen = True
        e.freezes += 1
        now = time.monotonic()
        e.thaw_after = now if e.freezes == 1 else now + min(self.THAW_BASE * 2 ** (e.freezes - 2), self.THAW_MAX)
        cur = self._current(e)
        if self._feeds(e):
            keep = e.good if e.good is not _MISS else cur
            e.error = why + KEPT
            if keep is not _MISS and not _same(keep, cur):
                sets.setdefault(e.bid, {})[(e.si, e.rc)] = keep
        else:
            e.error = why
            if not _same(E_CALC, cur):
                sets.setdefault(e.bid, {})[(e.si, e.rc)] = E_CALC
        self.svc._formulas_changed(e.scope)

    def _current(self, e: _Entry) -> Any:
        if e.scope == SHARED:
            return self.svc.books[e.bid].engine.input_value[e.si].get(e.rc, _MISS)
        return self.svc._overlays.get((e.scope, e.bid), {}).get((e.si, e.rc), _MISS)

    def _apply(self, scope: str, sets: Dict[str, Dict[Tuple[int, int], Any]]) -> None:
        """New values of formula inputs, as typed ones are set (not written to the store: the formula is, its value is
        worked out again at the start)."""
        svc = self.svc
        for bid, vals in sets.items():
            if not vals:
                continue
            book = svc.books[bid]
            if scope == SHARED:
                eng = book.engine
                typed = eng.input_changes
                eng.set_inputs(vals)
                # (followed, not typed: for the pages kept of users with inputs of their own, as the market's moves are)
                eng.input_changes = typed
            else:
                ov = dict(svc._overlay(scope, book))
                ov.update(vals)
                svc._overlays[(scope, bid)] = ov
                book.engine.set_user_inputs(scope, ov)

    def _fresh(self, e: _Entry) -> bool:
        """Whether nothing the formula read was invalidated since it was evaluated."""
        return e.metas is not None and self.svc.calcsheets._still(e.scope or None, e.metas)

    def _run(self, e: _Entry, again: bool = True) -> Any:
        """The formula evaluated over its scope's view (its user's own, or everybody's) -> its value; what it read is kept.
        A shared formula reads with nobody's rights (an administrators' page is not everybody's), a user's with the role
        they have now.  Over the time limit it is tried once more at once (what it read is computed by then)."""
        cs = self.svc.calcsheets
        cs._tables()
        fn, notes, _ = cs._compile(e.text, e.r, e.c)
        self.evaluations += 1
        e.note, e.stopped, e.timed_out, e.denied = None, False, False, False
        if fn is None:
            e.metas = {}
            e.note = BLOOMBERG_INPUT % notes["bloomberg"] if notes.get("bloomberg") else UNREADABLE
            return E_NAME
        admin = e.scope != SHARED and self.svc._is_admin(e.scope)
        ctx = _Ctx(cs, e.scope or None, _NOTHING, admin)
        ctx.stack.append(_HERE)
        try:
            v = _plain(fn(ctx, cs._slots[(e.bid, e.si)], e.r, e.c))
        except _Stop as stop:
            v, e.note = E_CALC, stop.text
            if stop.text == _calc.TIME_NOTE % _calc.EVAL_SECONDS:
                e.timed_out = True
            else:
                e.stopped = True                       # (too many cells read, a range too big: the formula's own size)
        except Exception as exc:  # noqa: BLE001 - a function that failed: this formula's error
            v, e.note = E_VALUE, "Hesaplanamadı: %s" % (str(exc)[:120] or type(exc).__name__)
        finally:
            metas = ctx.release()
        # (cut short by the time limit: what it read so far is no evaluation - it stays to be evaluated)
        e.metas = None if e.timed_out else metas
        if e.timed_out and again:
            return self._run(e, False)
        e.denied = any(calc is None for calc, _ in ctx.books.values())
        if e.note is None:
            e.note = ctx.notes.get(_HERE)
        if e.note is None and type(v) is XlError:
            e.note = cs._tip(e.text, e.r, e.c, v) or None
        return v

    # ------------------------------------------------------------------ cycles
    def _ring(self, x: _Entry, batch: List[_Entry]) -> List[str]:
        """The way from ``x`` round to it, as the cells it passes (``["MASA!C60", "MASA!C171", "MASA!C60"]``: C60 reads
        C171, which reads C60) - ``[]``: none.  Through the workbook's formulas and the scope's other formula inputs."""
        nodes = [e for e in self._scopes.get(x.scope, {}).values() if e.key != x.key and not e.frozen]
        nodes += [e for e in batch if e.key != x.key]
        nodes.append(x)
        parent: Dict[Tuple[str, int, int], Optional[Tuple[_Entry, str]]] = {x.key: None}
        stack = [x]
        while stack:
            n = stack.pop()
            for m in nodes:
                via = self._via(n, m)
                if via is None:
                    continue
                if m.key == x.key:
                    hops = [(n, via)]
                    while parent[hops[-1][0].key] is not None:
                        hops.append(parent[hops[-1][0].key])
                    out: List[str] = []
                    for node, v in reversed(hops):
                        out.append(node.ref)
                        if v:
                            out.append(v)
                    return out + [x.ref]
                if m.key not in parent:
                    parent[m.key] = (n, via)
                    stack.append(m)
        return []

    def _via(self, n: _Entry, m: _Entry) -> Optional[str]:
        """Whether what ``n`` read depends on the input ``m`` is typed into: the masks of what it read carry m's bit (a
        bit a group of inputs shares, too) and a cell its text names is m's cell or one computed from it.  None: it does
        not; "": it reads m's cell (or what it reads is not told); else the cell computed from m's that it reads."""
        meta = (n.metas or {}).get(m.bid)
        if meta is None:
            return None
        bit = self.svc.books[m.bid].engine.input_mask[m.si].get(m.rc, 0)
        if not bit or not meta[3] & bit:
            return None
        boxes = self._boxes(n)
        if boxes is None:
            return ""                                  # (cells known only when computed: taken as read)
        mine = [b for b in boxes if b[0] == m.bid]
        for _, s, r1, c1, r2, c2 in mine:
            if s == m.si and r1 <= m.r <= r2 and c1 <= m.c <= c2:
                return ""
        if not mine:
            return None
        down = self._downstream(m)
        if down is None:
            return ""
        hits = []
        for s, rc in down:
            r, c = divmod(rc, COLS)
            for _, bs, r1, c1, r2, c2 in mine:
                if bs == s and r1 <= r <= r2 and c1 <= c <= c2:
                    hits.append((s, rc))
                    break
        return self.svc.books[m.bid].ref(*min(hits)) if hits else None

    def _downstream(self, e: _Entry) -> Optional[frozenset]:
        """The cells computed from the input's cell (the formulas' references; None: that cannot be told)."""
        got = self._down.get(e.key, _MISS)
        if got is _MISS:
            idx = self.svc.books[e.bid].engine.ref_index()
            got = frozenset(idx.downstream([(e.si, e.rc)])) if idx.complete else None
            self._down[e.key] = got
        return got

    def _boxes(self, e: _Entry) -> Optional[List[Tuple[str, int, int, int, int, int]]]:
        """The cells the formula's text names (its names' too), as boxes: [(book, sheet, r1, c1, r2, c2)] - None when it
        reads cells it works out (OFFSET / INDIRECT)."""
        if e.boxes is not _MISS:
            return e.boxes
        cs = self.svc.calcsheets
        cs._tables()
        out: List[Tuple[str, int, int, int, int, int]] = []
        try:
            ok = self._collect(parse_template(to_template(normalise(e.text), e.r, e.c)), e, out, set())
        except Exception:  # noqa: BLE001 - refused as typed already; kept by another version: not told
            ok = False
        e.boxes = out if ok else None
        return e.boxes

    def _collect(self, tree, e: _Entry, out: List, seen: set) -> bool:
        cs = self.svc.calcsheets
        names = cs._names()
        for nd in walk(tree):
            k = nd[0]
            if k == "func" and nd[1] in DYNAMIC:
                return False
            if k == "bin" and nd[1] == ":":
                # A1:INDEX(B1:B9,n) reads the box the two sides span
                parts: List = []
                if not (self._collect(nd[2], e, parts, seen) and self._collect(nd[3], e, parts, seen)):
                    return False
                same = [p for p in parts if p[:2] == parts[0][:2]] if parts else []
                if parts and len(same) == len(parts):
                    out.append(parts[0][:2] + (min(p[2] for p in parts), min(p[3] for p in parts),
                                               max(p[4] for p in parts), max(p[5] for p in parts)))
                out.extend(parts)
            elif k in ("cell", "range", "cols", "rows"):
                box = self._box(nd, e)
                if box is not None:
                    out.append(box)
            elif k == "name" and nd[1] in names and nd[1] not in seen:
                try:
                    sub = parse_template(names[nd[1]])
                except Exception:  # noqa: BLE001
                    continue
                if not self._collect(sub, e, out, seen | {nd[1]}):
                    return False
        return True

    def _box(self, nd, e: _Entry) -> Optional[Tuple[str, int, int, int, int, int]]:
        cs = self.svc.calcsheets
        if nd[1] is None:
            bid, si = e.bid, e.si
        else:
            slot = cs._resolve(nd[1])
            if slot is None:
                return None                            # (a sheet that is not there: #REF!)
            bid, si = cs._slot_of[slot]
        eng = self.svc.books[bid].engine
        r, c = e.r, e.c
        k = nd[0]
        if k == "cell":
            rr = nd[3] if nd[2] else r + nd[3]
            cc = nd[5] if nd[4] else c + nd[5]
            return bid, si, rr, cc, rr, cc
        if k == "range":
            r1 = nd[3] if nd[2] else r + nd[3]
            c1 = nd[5] if nd[4] else c + nd[5]
            r2 = nd[7] if nd[6] else r + nd[7]
            c2 = nd[9] if nd[8] else c + nd[9]
            return bid, si, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)
        if k == "cols":
            c1 = nd[3] if nd[2] else c + nd[3]
            c2 = nd[5] if nd[4] else c + nd[5]
            return bid, si, 1, min(c1, c2), max(eng.max_row[si], 1), max(c1, c2)
        r1 = nd[3] if nd[2] else r + nd[3]
        r2 = nd[5] if nd[4] else r + nd[5]
        return bid, si, min(r1, r2), 1, max(r1, r2), max(eng.max_col[si], 1)

    # ------------------------------------------------------------------ Bloomberg
    def _reads_live(self, e: _Entry) -> bool:
        """Whether what the formula read moves with the market or the clock's time (NOW): a new value at any tick."""
        for bid, meta in (e.metas or {}).items():
            if meta[3] & self._live_mask(bid):
                return True
        return False

    def _live_mask(self, bid: str) -> int:
        eng = self.svc.books[bid].engine
        bits = eng._bits
        got = self._live.get(bid)
        if got is None or got[0] != len(bits):
            mask = 0
            for key, b in list(bits.items()):
                if isinstance(key, tuple) and (key[0] == "md" or key == ("clock", "now")):
                    mask |= b
            got = self._live[bid] = (len(bits), mask)
        return got[1]

    def _feeds(self, e: _Entry) -> str:
        """The Bloomberg request the input's value goes into (a formula of the workbook calling BDP, BDH, BFXFORWARD …
        computed from the cell) - its cell, or "" when none."""
        if e.feeds is None:
            book = self.svc.books[e.bid]
            adds = self._addins.get(e.bid)
            if adds is None:
                adds = self._addins[e.bid] = frozenset(addin_cells(book.model))
            down = self._downstream(e)
            if down is None:
                e.feeds = "bilinmiyor"
            else:
                hit = sorted(c for c in down if c in adds)
                e.feeds = book.ref(*hit[0]) if hit else ""
        return e.feeds


def _same(a: Any, b: Any) -> bool:
    """The same cell value (a change of type is a change; an error is the same error)."""
    if a is _MISS or b is _MISS or type(a) is not type(b):
        return False
    if type(a) is float and a != a:
        return b != b
    return a == b
