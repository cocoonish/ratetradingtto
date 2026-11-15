"""Workbook calculation engine.

:class:`Engine` owns the static workbook model plus compiled formulas; :class:`Calc` is a calculation
state (memo of cell values).  Values are pulled lazily: asking for a cell evaluates exactly the cells it
needs.

Dependency masks
----------------
Every *input* (designated input cell, market-data key, the clock) owns one bit.  While a formula is
evaluated the bits of everything it reads are OR-ed together and stored next to its value.  This gives

* precise invalidation - when inputs change only cells whose mask intersects the changed bits are
  dropped (:meth:`Engine.invalidate`);
* sharing between users - a user :class:`Calc` (with private input overrides) re-uses every value of the
  shared pool whose mask does not touch one of that user's overridden inputs, and publishes the user
  independent values it computes back into the pool.
"""
from __future__ import annotations

import datetime as _dt
import itertools
import sys
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .compiler import ADDINS, Compiler
from .errors import E_NA, E_NAME, E_NUM, E_REF, E_SPILL, E_VALUE, XlError
from .model import COLS, Model, a1
from .parser import parse_template, walk
from .values import XlArray, XlRange, date_to_serial

_MISS = object()
_SERIALS = itertools.count(1)          # every calculation's own number (a dropped user's new one is another)
DEPTH_LIMIT = 90         # nested cell evaluations before the engine unwinds and restarts bottom-up
DEEP_LIMIT = 1000         # ... on a thread started with a big stack (the calculation threads)
# Windows takes a thread stack *below* 256 MiB only (256 MiB itself is refused - for years the calculation thread ran
# on the default ~2 MB stack, where a chain of 500-700 nested cells already ends the process); a multiple of 4 KiB
BIG_STACKS = (255 << 20, 128 << 20, 64 << 20)
_RECURSION_LIMIT = 30000
_TLS = threading.local()


def set_depth_limit(limit: int) -> None:
    """How deep this thread evaluates before unwinding.  Unwinding a long chain (the Motor sheet: thousands of cells,
    each reading the one above) and restarting it from the deep end works on any stack, but it is ~7x slower than
    evaluating the chain in one go - which only a thread with a big stack can do: on the default ~2 MB stack of a
    Windows thread 500-700 nested cells end the process (a crash, not an exception).  Only the threads started by
    :func:`big_stack_thread` raise it; every other thread (the main thread, a test) keeps ``DEPTH_LIMIT``."""
    _TLS.limit = max(DEPTH_LIMIT, int(limit))


def depth_limit() -> int:
    """The depth this thread evaluates before unwinding (``DEPTH_LIMIT`` unless :func:`set_depth_limit` raised it)."""
    return getattr(_TLS, "limit", DEPTH_LIMIT)


def big_stack_thread(target: Callable, name: str, daemon: bool = False) -> threading.Thread:
    """A started thread with the largest stack of ``BIG_STACKS`` the platform takes, evaluating ``DEEP_LIMIT`` deep
    (``DEPTH_LIMIT`` when it takes none of them)."""
    old = threading.stack_size()
    big = False
    for size in BIG_STACKS:
        try:
            threading.stack_size(size)
            big = True
            break
        except (ValueError, RuntimeError):
            continue

    def run():
        if big:
            set_depth_limit(DEEP_LIMIT)
        target()

    try:
        t = threading.Thread(target=run, name=name, daemon=daemon)
        t.start()
    finally:
        try:
            threading.stack_size(old)
        except (ValueError, RuntimeError):
            pass
    return t


class _Deep(Exception):
    """Raised to unwind when the evaluation recursion gets too deep."""

    def __init__(self, cell):
        self.cell = cell


class Clock(object):
    """Source of TODAY() / NOW(); fixed clocks make calculations reproducible."""

    def __init__(self, fixed: Optional[float] = None):
        self.fixed = fixed

    def now(self) -> float:
        if self.fixed is not None:
            return self.fixed
        n = _dt.datetime.now()
        return date_to_serial(n.date()) + (n.hour * 3600 + n.minute * 60 + n.second) / 86400.0

    def today(self) -> float:
        return float(int(self.now()))


class Engine(object):
    def __init__(self, model: Model, provider=None, clock: Optional[Clock] = None):
        if sys.getrecursionlimit() < _RECURSION_LIMIT:
            sys.setrecursionlimit(_RECURSION_LIMIT)
        self.model = model
        self.compiler = Compiler(model)
        self.provider = provider
        self.clock = clock or Clock()
        n = len(model.sheets)
        self.nsheets = n
        self.consts = [s.consts for s in model.sheets]
        self.fml = [s.fml for s in model.sheets]
        self.arr = [s.arr for s in model.sheets]
        self.members = [s.members for s in model.sheets]
        self.max_row = [s.max_row for s in model.sheets]
        self.max_col = [s.max_col for s in model.sheets]
        self._code: List[Dict[int, Any]] = [dict() for _ in range(n)]
        # --- inputs & dependency bits
        self._bits: Dict[Any, int] = {}
        self._nbits = 0
        self.input_mask: List[Dict[int, int]] = [dict() for _ in range(n)]     # designated input cells
        self._bit_cells: Dict[int, List[Tuple[int, int]]] = {}                 # input bit -> its cells
        self.input_value: List[Dict[int, Any]] = [dict() for _ in range(n)]    # shared overrides of inputs
        self.pins: List[Dict[int, Any]] = [dict() for _ in range(n)]           # pinned (formula) cells
        self.spill_zone: List[Dict[int, Tuple[int, ...]]] = [dict() for _ in range(n)]  # rc -> anchors
        self.spill_anchors: List[Dict[int, Tuple[int, int]]] = [dict() for _ in range(n)]
        # dynamic arrays whose room is cut short by other content: a larger result is #SPILL!
        self.spill_blocked: List[set] = [set() for _ in range(n)]
        self._mask_pool: Dict[int, int] = {}
        self.circular: List[str] = []
        self._refs = None                                 # RefIndex (ref_index)
        self._refs_lock = threading.Lock()
        self.marked = 0                                   # late declarations followed by the references (not a reset)
        # increases whenever masks change without a value changing (a reset, an input declared): what remembered
        # the masks of what it read (a page's panel) has to read again
        self.layout = 0
        self.shared = Calc(self, None, None)
        self.users: Dict[str, "Calc"] = {}
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ addressing helpers
    def ref(self, ref: str) -> Tuple[int, int]:
        return self.model.cell_ref(ref)

    def addr(self, si: int, rc: int) -> str:
        return "%s!%s" % (self.model.sheets[si].name, a1(rc))

    # ------------------------------------------------------------------ bits
    def bit(self, key) -> int:
        b = self._bits.get(key)
        if b is None:
            b = 1 << self._nbits
            self._nbits += 1
            self._bits[key] = b
        return b

    def intern_mask(self, k: int) -> int:
        return self._mask_pool.setdefault(k, k)

    # ------------------------------------------------------------------ compiled code
    def code(self, si: int, rc: int, tid: int):
        fn = self._code[si].get(rc)
        if fn is None:
            fn = self.compiler.function(tid, rc in self.arr[si])
            self._code[si][rc] = fn
        return fn

    # ------------------------------------------------------------------ inputs
    def declare_inputs(self, cells: Iterable[Tuple[int, int]], group: Optional[str] = None) -> None:
        """Mark cells as inputs (they may later be overridden per user or globally).

        Cells declared with the same ``group`` share one dependency bit (e.g. a whole pasted table).

        A formula cell declared once values are computed (a value typed over it - "elle değer") gets a bit of its
        own without dropping anything: whatever read the cell carries every bit of the mask the cell was computed
        with, so the values that carry them all - the cell's dependents and a few more - are marked with the new
        bit and kept.  Dropping every value of every user instead made the next page compute the whole workbook
        again (a ~20 s pause for everybody).  A cell whose dependents cannot be told that way (a constant, or one
        that depends on no input) is followed through the formulas that name it (:mod:`.refs`): the values
        downstream of it are marked the same way.  Only when that cannot be told either (a workbook with OFFSET /
        INDIRECT, a cell an array formula writes into) is everything computed again.

        Before anything is computed (since the last reset) nothing has to be dropped or marked: the cell gets its bit
        the way a reset would give it, nothing is computed (a formula gets its own bit with its value).  The service
        declares every input it knows of - the pages', and every cell a user typed over or keeps in a scenario -
        at that point.
        """
        pristine = self._pristine()
        late: List[Tuple[int, int, int]] = []
        seeded = []
        for si, rc in cells:
            if rc in self.input_mask[si]:
                continue
            self.layout += 1
            if pristine:
                if rc in self.fml[si] and rc not in self.pins[si] and rc not in self.input_value[si]:
                    self._set_input(si, rc, self.bit(("cell", si, rc)))     # (the bit comes with the value: _eval)
                else:
                    self._set_input(si, rc, self.bit(("group", group) if group else ("cell", si, rc)))
                    seeded.append((si, rc))
                continue
            mask = self._computed_mask(si, rc)
            if mask:
                b = self.bit(("cell", si, rc))             # its own bit: what follows the cell is found exactly
                self._set_input(si, rc, b)
                self._mark_dependents(si, rc, mask, b)
                continue
            key = ("group", group) if group else ("cell", si, rc)
            b = self.bit(key)
            self._set_input(si, rc, b)
            late.append((si, rc, b))
        if late and not self._mark_downstream(late):
            self.reset()
        elif seeded:
            # what a reset gives an input cell: its bit, and a value (empty when the workbook holds none)
            shared = self.shared
            for si, rc in seeded:
                if rc not in shared.memo[si]:
                    shared.memo[si][rc] = None
                shared._mark(si, rc, self.input_mask[si][rc])
            for calc in self.users.values():
                calc._seed_overlay()

    def ref_index(self):
        """The reverse index of the formulas' references (:class:`.refs.RefIndex`), built on first use (~4 s for the
        TRY workbook - the service builds it ahead, in the background)."""
        with self._refs_lock:
            if self._refs is None:
                from .refs import RefIndex
                self._refs = RefIndex(self)
            return self._refs

    def _mark_downstream(self, late: List[Tuple[int, int, int]]) -> bool:
        """Cells declared once values are computed whose dependents no mask tells - ``[(sheet, rc, bit)]``, constants
        mostly: every computed value downstream of them (by the formulas' references) is marked with the bit, as if it
        had been computed after the declaration.  Nothing is dropped.  False: that cannot be told (the caller resets)."""
        for si, rc, _ in late:
            if rc in self.spill_zone[si] or rc in self.members[si]:
                return False                             # a cell an array formula writes into
        idx = self.ref_index()
        if not idx.complete:
            return False
        by_bit: Dict[int, List[Tuple[int, int]]] = {}
        for si, rc, b in late:
            by_bit.setdefault(b, []).append((si, rc))
        intern = self.intern_mask
        calcs = [self.shared] + list(self.users.values())
        for b, cells in by_bit.items():
            down = idx.downstream(cells)
            down.update(c for c in cells if c[1] in self.fml[c[0]])        # a formula's own value (it read no input)
            for calc in calcs:
                memo, maskd = calc.memo, calc.maskd
                for si, rc in down:
                    if rc in memo[si]:
                        calc._mark(si, rc, intern(maskd[si].get(rc, 0) | b))
        for calc in calcs:
            calc.rcache = {}                             # a range read does not know the cells' new bit: read again
        shared = self.shared
        for si, rc, b in late:
            if rc in self.fml[si] and rc not in self.input_value[si] and rc not in self.pins[si]:
                continue                                 # (a formula default carries its bit with its value)
            if rc not in shared.memo[si]:
                shared.memo[si][rc] = None
            shared._mark(si, rc, b)
        for calc in self.users.values():
            calc._seed_overlay()
        self.marked += 1
        return True

    def _pristine(self) -> bool:
        """Nothing computed since the last reset: no calculation evaluated a formula (nothing holds a value read from
        another cell)."""
        shared = getattr(self, "shared", None)
        if shared is None or shared.evals != shared._evals0:
            return False
        return all(c.evals == c._evals0 for c in self.users.values())

    def _set_input(self, si: int, rc: int, b: int) -> None:
        self.input_mask[si][rc] = b
        self._bit_cells.setdefault(b, []).append((si, rc))

    def _computed_mask(self, si: int, rc: int) -> int:
        """The dependency mask the shared calculation has for a formula cell - computing the cell first when it has
        not been yet (0: not a formula, or it depends on no input, or before anything is computed)."""
        shared = getattr(self, "shared", None)
        if shared is None or rc not in self.fml[si] or not any(shared.memo):
            return 0
        if rc not in shared.memo[si]:
            try:
                shared.get(si, *divmod(rc, COLS))        # (get, not cv: a long chain is unwound and restarted)
            except Exception:  # noqa: BLE001 - a cell that cannot be computed now: the safe way, everything again
                return 0
        return shared.maskd[si].get(rc, 0)

    def _mark_dependents(self, si: int, rc: int, mask: int, b: int) -> None:
        """Add bit ``b`` to every computed value - of every calculation - that read the formula cell (si, rc): what
        carries all of the mask the cell was computed with.  That is the shared value's ``mask``, and in a user's
        calculation also the mask of the user's own value of the cell - a user who typed over something upstream
        computed it (and what read it) with other bits: those values do not carry all of the shared mask."""
        intern = self.intern_mask
        for calc in [self.shared] + list(self.users.values()):
            masks = [mask]
            own = calc.maskd[si].get(rc) if calc.parent is not None else None
            if own and own != mask:
                masks.append(own)
            groups = calc.groups
            for m in masks:
                for k in [k for k in groups if k & m == m]:
                    nk = intern(k | b)
                    if nk == k:
                        continue
                    for gsi, rcs in groups.pop(k).items():
                        md = calc.maskd[gsi]
                        moved = [x for x in rcs if md.get(x) == k]
                        for x in moved:
                            md[x] = nk
                        if moved:
                            calc._group(nk, gsi).extend(moved)
            for key, ent in list(calc.rcache.items()):
                if any(ent[2] & m == m for m in masks):
                    calc.rcache[key] = (ent[0], ent[1], intern(ent[2] | b))

    def is_input(self, si: int, rc: int) -> bool:
        return rc in self.input_mask[si]

    def set_inputs(self, values: Dict[Tuple[int, int], Any]) -> None:
        """Set shared (all users) values of input cells and invalidate what depends on them."""
        self.declare_inputs(values.keys())
        changed = 0
        for (si, rc), v in values.items():
            old = self.input_value[si].get(rc, _MISS)
            if old is _MISS:
                old = self.base_value(si, rc)
            if old != v or type(old) is not type(v):
                changed |= self.input_mask[si][rc]
            self.input_value[si][rc] = v
        if changed:
            self.invalidate(changed)

    def clear_inputs(self, cells: Iterable[Tuple[int, int]]) -> None:
        """Remove shared overrides: the cells fall back to what the workbook itself holds."""
        changed = 0
        for si, rc in cells:
            if rc in self.input_value[si]:
                del self.input_value[si][rc]
                changed |= self.input_mask[si][rc]
        if changed:
            self.invalidate(changed)

    def base_value(self, si: int, rc: int) -> Any:
        """The workbook's own constant in a cell (None when empty or a formula)."""
        return self.consts[si].get(rc)

    def set_pins(self, pins: Dict[Tuple[int, int], Any]) -> None:
        """Replace formula cells by fixed values (replay of cached add-in results)."""
        for (si, rc), v in pins.items():
            self.pins[si][rc] = v
        self.reset()

    def clear_pins(self) -> None:
        self.pins = [dict() for _ in range(self.nsheets)]
        self.reset()

    # ------------------------------------------------------------------ invalidation
    def reset(self) -> None:
        """Drop every computed value."""
        self.layout += 1
        self.shared._reset()
        for calc in self.users.values():
            calc._reset()

    def invalidate(self, changed: int) -> None:
        """Drop the values that depend on any input whose bit is set in ``changed``."""
        if not changed:
            return
        self.shared._invalidate(changed)
        for calc in self.users.values():
            calc._invalidate(changed)

    def market_changed(self, keys: Iterable[Any]) -> int:
        mask = 0
        for k in keys:
            b = self._bits.get(("md", k))
            if b:
                mask |= b
        self.invalidate(mask)
        return mask

    def clock_tick(self) -> None:
        mask = self._bits.get(("clock", "now"), 0)
        today = self.clock.today()
        if getattr(self, "_last_today", None) != today:
            self._last_today = today
            mask |= self._bits.get(("clock", "today"), 0)
        self.invalidate(mask)

    # ------------------------------------------------------------------ user calcs
    def user(self, name: str) -> "Calc":
        calc = self.users.get(name)
        if calc is None:
            calc = Calc(self, self.shared, {})
            self.users[name] = calc
        return calc

    def set_user_inputs(self, name: str, overlay: Dict[Tuple[int, int], Any]) -> "Calc":
        self.declare_inputs(overlay.keys())
        calc = self.user(name)
        calc.set_overlay(overlay)
        return calc

    def drop_user(self, name: str) -> None:
        self.users.pop(name, None)

    # ------------------------------------------------------------------ spill anchors
    def register_spill(self, si: int, anchor_rc: int, max_rows: int, max_cols: int, reset: bool = True) -> None:
        """Declare that the formula at ``anchor_rc`` may write an array over the cells below / right (``reset``:
        False when the caller resets once after registering many)."""
        self.spill_anchors[si][anchor_rc] = (max_rows, max_cols)
        r0, c0 = divmod(anchor_rc, COLS)
        zone = self.spill_zone[si]
        fml = self.fml[si]
        for r in range(r0, r0 + max_rows):
            base = r * COLS
            for c in range(c0, c0 + max_cols):
                rc = base + c
                if rc == anchor_rc or rc in fml:
                    continue
                prev = zone.get(rc)
                zone[rc] = (anchor_rc,) if prev is None else prev + (anchor_rc,)
        if reset:
            self.reset()


class Calc(object):
    """A calculation state: memoised cell values (+ dependency masks) for one set of inputs."""

    def __init__(self, engine: Engine, parent: Optional["Calc"], overlay: Optional[Dict[Tuple[int, int], Any]]):
        self.engine = engine
        self.parent = parent
        n = engine.nsheets
        self.memo: List[Dict[int, Any]] = [dict() for _ in range(n)]
        self.maskd: List[Dict[int, int]] = [dict() for _ in range(n)]
        # the cells of maskd grouped by their mask: mask -> {sheet: [rc, ...]}.  ~150 000 values share ~4 500 masks,
        # so an invalidation tests each mask once instead of every value.  Every (sheet, rc) of maskd is listed under
        # its mask; a listed cell whose mask is another by now (or that is gone) is "stale" and skipped.
        self.groups: Dict[int, Dict[int, List[int]]] = {}
        self._stale = 0
        self.rcache: Dict[Tuple[int, int, int, int, int], Tuple[Any, Any, int]] = {}
        self.overlay: Dict[Tuple[int, int], Any] = dict(overlay or {})
        self.omask = 0
        self.cm = 0
        self.depth = 0
        self.busy: List[set] = [set() for _ in range(n)]
        self.evals = 0
        self.restarts = 0                     # chains unwound at the depth limit and restarted from their deep end
        # what changed, for those who remember what they read (a page's panel): every invalidation's mask, numbered
        self.serial = next(_SERIALS)
        self.epoch = 0
        self._log: List[Tuple[int, int]] = []
        self._floor = 0                       # invalidations up to this epoch are no longer in the log
        self.track: Optional[int] = None      # not None: the masks of the cells read through get() are OR-ed in
        self._reset()

    # ------------------------------------------------------------------ what changed
    LOG_MAX = 512

    def changed_since(self, epoch: int) -> Optional[int]:
        """The masks of what was invalidated after ``epoch`` OR-ed together (0: nothing; None: reset since, or too
        long ago to tell)."""
        if epoch < self._floor:
            return None
        m = 0
        for e, k in reversed(self._log):
            if e <= epoch:
                break
            m |= k
        return m

    def _logged(self, changed: Optional[int]) -> None:
        self.epoch += 1
        if changed is None:                   # (a reset: everything)
            self._log = []
            self._floor = self.epoch
            return
        self._log.append((self.epoch, changed))
        if len(self._log) > self.LOG_MAX:
            drop = len(self._log) - self.LOG_MAX // 2
            self._floor = self._log[drop - 1][0]
            del self._log[:drop]

    # ------------------------------------------------------------------ state management
    def _reset(self) -> None:
        eng = self.engine
        n = eng.nsheets
        self.rcache = {}
        self.cm = 0
        self.depth = 0
        self.busy = [set() for _ in range(n)]
        self._evals0 = self.evals                   # (nothing evaluated since: Engine._pristine)
        self._logged(None)
        if self.parent is None:
            self.memo = []
            self.maskd = []
            for si in range(n):
                m = dict(eng.consts[si])
                zone = eng.spill_zone[si]
                if zone:
                    for rc in zone:
                        m.pop(rc, None)
                m.update(eng.pins[si])
                m.update(eng.input_value[si])
                self.memo.append(m)
                # every input cell carries its dependency bit - also when it is empty.  Inputs whose
                # default is a formula get the bit when that formula is evaluated (see _eval).
                md: Dict[int, int] = {}
                fml = eng.fml[si]
                iv = eng.input_value[si]
                pins = eng.pins[si]
                for rc, b in eng.input_mask[si].items():
                    if rc in fml and rc not in iv and rc not in pins:
                        continue
                    if rc not in m:
                        m[rc] = None
                    md[rc] = b
                self.maskd.append(md)
            self._rebuild_groups()
        else:
            self.memo = [dict() for _ in range(n)]
            self.maskd = [dict() for _ in range(n)]
            self.groups = {}
            self._stale = 0
            self._seed_overlay()

    # ------------------------------------------------------------------ masks grouped
    def _group(self, k: int, si: int) -> List[int]:
        g = self.groups.get(k)
        if g is None:
            g = self.groups[k] = {}
        lst = g.get(si)
        if lst is None:
            lst = g[si] = []
        return lst

    def _mark(self, si: int, rc: int, k: int) -> None:
        """Give a cell the mask ``k`` (listing it under ``k``)."""
        md = self.maskd[si]
        old = md.get(rc)
        if old != k:
            md[rc] = k
            self._group(k, si).append(rc)
            if old is not None:
                self._stale += 1

    def _rebuild_groups(self) -> None:
        groups: Dict[int, Dict[int, List[int]]] = {}
        for si, md in enumerate(self.maskd):
            for rc, k in md.items():
                g = groups.get(k)
                if g is None:
                    groups[k] = {si: [rc]}
                else:
                    lst = g.get(si)
                    if lst is None:
                        g[si] = [rc]
                    else:
                        lst.append(rc)
        self.groups = groups
        self._stale = 0

    #: stale entries of the groups (cells listed under a mask they no longer have) before they are rebuilt
    STALE_MAX = 20000

    def _seed_overlay(self) -> None:
        eng = self.engine
        self.omask = 0
        for (si, rc), v in self.overlay.items():
            bit = eng.input_mask[si].get(rc)
            if bit is None:
                continue
            self.memo[si][rc] = v
            self._mark(si, rc, bit)
            self.omask |= bit

    def set_overlay(self, overlay: Dict[Tuple[int, int], Any]) -> None:
        """Replace this user's private input values."""
        eng = self.engine
        changed = 0
        keys = set(self.overlay) | set(overlay)
        for key in keys:
            old = self.overlay.get(key, _MISS)
            new = overlay.get(key, _MISS)
            if old is _MISS or new is _MISS or old != new or type(old) is not type(new):
                bit = eng.input_mask[key[0]].get(key[1])
                if bit:
                    changed |= bit
        self.overlay = dict(overlay)
        if changed:
            self._invalidate(changed)
            # overlay cells removed / changed must be re-seeded
            for (si, rc) in keys:
                self.memo[si].pop(rc, None)
                if self.maskd[si].pop(rc, None) is not None:
                    self._stale += 1
        self._seed_overlay()

    def _invalidate(self, changed: int) -> None:
        eng = self.engine
        shared = self.parent is None
        self._logged(changed)
        if self._stale > self.STALE_MAX:
            self._rebuild_groups()
        groups = self.groups
        overlay = self.overlay
        for k in [k for k in groups if k & changed]:
            keep: List[Tuple[int, int]] = []
            for si, rcs in groups.pop(k).items():
                md = self.maskd[si]
                memo = self.memo[si]
                inputs = eng.input_mask[si]
                fml = eng.fml[si]
                iv = eng.input_value[si]
                for rc in rcs:
                    if md.get(rc) != k:
                        continue                         # stale: dropped, or stored again with another mask
                    if rc in inputs:
                        # an input keeps its value unless it is a formula default that must be recomputed
                        if shared:
                            if not (rc in fml and rc not in iv):
                                keep.append((si, rc))
                                continue
                        elif (si, rc) in overlay:
                            keep.append((si, rc))
                            continue
                    del md[rc]
                    memo.pop(rc, None)
            for si, rc in dict.fromkeys(keep):          # (still under k)
                self._group(k, si).append(rc)
        if shared:
            consts = eng.consts
            for bit, cells in eng._bit_cells.items():
                if not bit & changed:
                    continue
                for si, rc in cells:
                    v = eng.input_value[si].get(rc, _MISS)
                    if v is _MISS:
                        if rc in eng.fml[si]:
                            # an input holding a default formula: recompute it (it keeps its input bit)
                            self.memo[si].pop(rc, None)
                            if self.maskd[si].pop(rc, None) is not None:
                                self._stale += 1
                            continue
                        v = consts[si].get(rc)
                    self.memo[si][rc] = v
                    self._mark(si, rc, bit)
        if self.rcache:
            self.rcache = {k: e for k, e in self.rcache.items() if not (e[2] & changed)}
        if not shared:
            self._seed_overlay()

    # ------------------------------------------------------------------ public API
    def get(self, si: int, r: int, c: int) -> Any:
        """Value of one cell (top-level entry: handles deep dependency chains)."""
        stack = [(si, r, c)]
        v = None
        guard = 0
        while stack:
            s, rr, cc = stack[-1]
            self.depth = 0
            self.cm = 0
            try:
                v = self.cv(s, rr, cc)
                stack.pop()
            except _Deep as d:
                for b in self.busy:
                    b.clear()
                stack.append(d.cell)
                self.restarts += 1
                guard += 1
                if guard > 2000000:
                    raise RuntimeError("evaluation does not converge")
        if self.track is not None:
            self.track |= self.cm                # (the mask of the cell asked for)
        return v

    def value(self, ref: str) -> Any:
        si, rc = self.engine.model.cell_ref(ref)
        r, c = divmod(rc, COLS)
        return self.get(si, r, c)

    def values(self, ref: str) -> List[List[Any]]:
        si, r1, c1, r2, c2 = self.engine.model.range_ref(ref)
        return self.get_range(si, r1, c1, r2, c2)

    def get_range(self, si: int, r1: int, c1: int, r2: int, c2: int) -> List[List[Any]]:
        get = self.get
        return [[get(si, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]

    # ------------------------------------------------------------------ evaluation core
    def cv(self, si: int, r: int, c: int) -> Any:
        rc = r * COLS + c
        v = self.memo[si].get(rc, _MISS)
        if v is not _MISS:
            k = self.maskd[si].get(rc)
            if k:
                self.cm |= k
            return v
        return self._load(si, rc, r, c)

    def _load(self, si: int, rc: int, r: int, c: int) -> Any:
        parent = self.parent
        eng = self.engine
        if parent is not None:
            pv = parent.memo[si].get(rc, _MISS)
            if pv is not _MISS:
                k = parent.maskd[si].get(rc)
                if not k:
                    return pv
                if not (k & self.omask):
                    self.cm |= k
                    return pv
                if rc in eng.input_mask[si] and (rc not in eng.fml[si] or rc in eng.input_value[si] or rc in eng.pins[si]):
                    # An input this user did not type into, although it shares its dependency bit with cells
                    # the user did type into (a group of inputs, e.g. one column of scenario steps): the value
                    # everybody sees stands - and whatever is computed from it depends on that group.
                    self.cm |= k
                    return pv
        tid = eng.fml[si].get(rc)
        if tid is not None:
            return self._eval(si, rc, r, c, tid)
        anchor = eng.members[si].get(rc)
        if anchor is not None:
            ar, ac = divmod(anchor, COLS)
            self.cv(si, ar, ac)
            v = self._peek(si, rc)
            if v is _MISS:
                return self._store(si, rc, None, 0)
            return v
        zone = eng.spill_zone[si].get(rc)
        if zone is not None:
            saved = self.cm
            self.cm = 0
            for anchor in zone:
                ar, ac = divmod(anchor, COLS)
                self.cv(si, ar, ac)
            v = self._peek(si, rc)
            k = self.cm
            self.cm = saved | k
            if v is _MISS:
                v = eng.consts[si].get(rc) if eng.provider is None or not getattr(eng.provider, "live", False) else None
                return self._store(si, rc, v, k)
            return v
        return None

    def _peek(self, si: int, rc: int) -> Any:
        """Memo lookup (own, then shared pool) that also accumulates the dependency mask."""
        v = self.memo[si].get(rc, _MISS)
        if v is not _MISS:
            k = self.maskd[si].get(rc)
            if k:
                self.cm |= k
            return v
        parent = self.parent
        if parent is not None:
            pv = parent.memo[si].get(rc, _MISS)
            if pv is not _MISS:
                k = parent.maskd[si].get(rc)
                if not k:
                    return pv
                if not (k & self.omask):
                    self.cm |= k
                    return pv
        return _MISS

    def _store(self, si: int, rc: int, v: Any, k: int) -> Any:
        if type(v) is float and v - v != 0.0:
            # an overflow (1E308*10) or what follows from one (inf - inf): Excel shows #NUM! - and JSON has no
            # infinity, a page holding one could not be sent at all
            v = E_NUM
        parent = self.parent
        target = self if (parent is None or (k & self.omask)) else parent
        target.memo[si][rc] = v
        if k:
            k = self.engine.intern_mask(k)
            md = target.maskd[si]
            old = md.get(rc)
            if old != k:
                md[rc] = k
                g = target.groups.get(k)
                if g is None:
                    target.groups[k] = {si: [rc]}
                else:
                    lst = g.get(si)
                    if lst is None:
                        g[si] = [rc]
                    else:
                        lst.append(rc)
                if old is not None:
                    target._stale += 1
        return v

    def _eval(self, si: int, rc: int, r: int, c: int, tid: int) -> Any:
        busy = self.busy[si]
        if rc in busy:
            eng = self.engine
            if len(eng.circular) < 200:
                eng.circular.append(eng.addr(si, rc))
            return 0.0
        if self.depth >= DEPTH_LIMIT and self.depth >= depth_limit():
            raise _Deep((si, r, c))
        eng = self.engine
        fn = eng._code[si].get(rc)
        if fn is None:
            fn = eng.code(si, rc, tid)
        saved = self.cm
        self.cm = 0
        self.depth += 1
        busy.add(rc)
        try:
            v = fn(self, si, r, c)
        finally:
            busy.discard(rc)
            self.depth -= 1
        self.evals += 1
        k = self.cm
        ib = eng.input_mask[si].get(rc)
        if ib:
            k |= ib
        self.cm = saved | k
        if v is None:
            v = 0.0                     # a formula that yields an empty cell shows 0
        tv = type(v)
        if tv is float or tv is str or tv is bool or tv is XlError:
            ref = eng.arr[si].get(rc)
            if ref is not None and (ref[0] != ref[2] or ref[1] != ref[3]):
                self._spill(si, rc, r, c, [[v]], k, ref, True)
            elif rc in eng.spill_anchors[si]:
                self._spill(si, rc, r, c, [[v]], k, None, False)
            return self._store(si, rc, v, k)
        if tv is XlRange:
            saved2 = self.cm
            self.cm = 0
            rows = v.values()
            k |= self.cm
            self.cm = saved2 | k
        elif tv is XlArray:
            rows = v.rows
        elif tv is int:
            return self._store(si, rc, float(v), k)
        else:
            return self._store(si, rc, E_VALUE, k)
        ref = eng.arr[si].get(rc)
        if rc in eng.spill_blocked[si]:
            room = eng.spill_anchors[si].get(rc)
            if room is not None and (len(rows) > room[0] or (len(rows[0]) if rows else 0) > room[1]):
                # Excel refuses to write a dynamic array over cells that are in use
                self._spill(si, rc, r, c, [[None]], k, None, False)
                return self._store(si, rc, E_SPILL, k)
        if ref is not None and (ref[0] != ref[2] or ref[1] != ref[3]):
            self._spill(si, rc, r, c, rows, k, ref, rc not in self.engine.model.sheets[si].dyn)
        elif rc in eng.spill_anchors[si]:
            self._spill(si, rc, r, c, rows, k, None, False)
        top = rows[0][0] if rows and rows[0] else None
        if top is None:
            top = 0.0
        elif type(top) is int:
            top = float(top)
        return self._store(si, rc, top, k)

    def _spill(self, si: int, rc: int, r: int, c: int, rows, k: int, ref, cse: bool) -> None:
        """Write the elements of an array result into the cells it covers."""
        eng = self.engine
        nr = len(rows)
        nc = len(rows[0]) if nr else 0
        fml = eng.fml[si]
        store = self._store
        if ref is not None and cse:
            r1, c1, r2, c2 = ref
            for rr in range(r1, r2 + 1):
                i = rr - r1
                for cc in range(c1, c2 + 1):
                    j = cc - c1
                    if rr == r and cc == c:
                        continue
                    ii = 0 if nr == 1 else i
                    jj = 0 if nc == 1 else j
                    v = rows[ii][jj] if (ii < nr and jj < nc) else E_NA
                    if v is None:
                        v = 0.0
                    elif type(v) is int:
                        v = float(v)
                    store(si, rr * COLS + cc, v, k)
            return
        # dynamic spill: the result decides the size; cells of the saved range beyond it become empty
        max_r, max_c = eng.spill_anchors[si].get(rc, (nr, nc))
        if ref is not None:
            max_r = max(max_r, ref[2] - ref[0] + 1)
            max_c = max(max_c, ref[3] - ref[1] + 1)
        for i in range(max(nr, max_r) if ref is not None or rc in eng.spill_anchors[si] else nr):
            rr = r + i
            base = rr * COLS
            for j in range(max(nc, max_c)):
                cc = c + j
                if i == 0 and j == 0:
                    continue
                if i >= max_r or j >= max_c:
                    continue
                tgt = base + cc
                if tgt in fml:
                    continue
                if i < nr and j < nc:
                    v = rows[i][j]
                    if v is None:
                        v = 0.0
                    elif type(v) is int:
                        v = float(v)
                else:
                    v = None
                store(si, tgt, v, k)

    # ------------------------------------------------------------------ ranges
    def rg(self, si: int, r1: int, c1: int, r2: int, c2: int) -> XlRange:
        return XlRange(self, si, r1, c1, r2, c2)

    def cols(self, si: int, c1: int, c2: int) -> XlRange:
        return XlRange(self, si, 1, c1, max(self.engine.max_row[si], 1), c2)

    def rows(self, si: int, r1: int, r2: int) -> XlRange:
        return XlRange(self, si, r1, 1, r2, max(self.engine.max_col[si], 1))

    def _range_entry(self, key):
        ent = self.rcache.get(key)
        if ent is None:
            parent = self.parent
            if parent is not None:
                ent = parent.rcache.get(key)
                if ent is not None and (ent[2] & self.omask):
                    ent = None
            if ent is None:
                si, r1, c1, r2, c2 = key
                saved = self.cm
                self.cm = 0
                cv = self.cv
                rows = [[cv(si, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
                k = self.cm
                self.cm = saved
                if len(rows) == 1:
                    flat = rows[0]
                elif c1 == c2:
                    flat = [row[0] for row in rows]
                else:
                    flat = [x for row in rows for x in row]
                ent = (rows, flat, self.engine.intern_mask(k) if k else 0)
                target = self if (parent is None or (k & self.omask)) else parent
                target.rcache[key] = ent
        if ent[2]:
            self.cm |= ent[2]
        return ent

    def range_values(self, si: int, r1: int, c1: int, r2: int, c2: int):
        return self._range_entry((si, r1, c1, r2, c2))[0]

    def range_flat(self, si: int, r1: int, c1: int, r2: int, c2: int):
        return self._range_entry((si, r1, c1, r2, c2))[1]

    # ------------------------------------------------------------------ volatile & add-in functions
    def today(self) -> float:
        eng = self.engine
        self.cm |= eng.bit(("clock", "today"))
        return eng.clock.today()

    def now(self) -> float:
        eng = self.engine
        self.cm |= eng.bit(("clock", "now"))
        return eng.clock.now()

    def addin(self, name: str, si: int, r: int, c: int, args: Sequence[Any]) -> Any:
        eng = self.engine
        prov = eng.provider
        if prov is None:
            return E_NA
        return prov.call(self, name, si, r, c, args)

    def depend_on_market(self, key) -> None:
        """Record that the formula being evaluated depends on the market-data item ``key``."""
        self.cm |= self.engine.bit(("md", key))


# ---------------------------------------------------------------------------------------------- helpers
def formula_has_addin(model: Model, tid: int, _cache: Dict[int, bool] = {}) -> bool:
    """True when the template calls a Bloomberg / Refinitiv add-in function."""
    key = (id(model), tid)
    hit = _cache.get(key)
    if hit is None:
        hit = False
        try:
            for nd in walk(parse_template(model.templates[tid])):
                if nd[0] == "func" and (nd[3] or nd[1] in ADDINS):
                    hit = True
                    break
        except Exception:
            hit = False
        _cache[key] = hit
    return hit


def addin_cells(model: Model) -> List[Tuple[int, int]]:
    """All formula cells that call an add-in function."""
    out = []
    flags: Dict[int, bool] = {}
    for s in model.sheets:
        for rc, tid in s.fml.items():
            f = flags.get(tid)
            if f is None:
                f = formula_has_addin(model, tid)
                flags[tid] = f
            if f:
                out.append((s.index, rc))
    return out


def cached_pins(model: Model, include_members: bool = True) -> Dict[Tuple[int, int], Any]:
    """Pins that freeze every add-in cell (and the arrays they spilled) at the value Excel cached."""
    pins: Dict[Tuple[int, int], Any] = {}
    for si, rc in addin_cells(model):
        s = model.sheets[si]
        if rc in s.cached:
            pins[(si, rc)] = s.cached[rc]
            if include_members and rc in s.arr:
                r1, c1, r2, c2 = s.arr[rc]
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        m = r * COLS + c
                        if m != rc and m in s.members and m in s.cached:
                            pins[(si, m)] = s.cached[m]
    return pins


def run_with_big_stack(fn: Callable, *args, **kwargs):
    """Run ``fn`` in a thread with a large stack (deep formula chains recurse deeply)."""
    result: Dict[str, Any] = {}

    def target():
        try:
            result["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
            result["error"] = exc

    t = big_stack_thread(target, "tto-engine")
    t.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
