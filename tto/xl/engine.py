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
import sys
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .compiler import ADDINS, Compiler
from .errors import E_NA, E_NAME, E_REF, E_VALUE, XlError
from .model import COLS, Model, a1
from .parser import parse_template, walk
from .values import XlArray, XlRange, date_to_serial

_MISS = object()
DEPTH_LIMIT = 90          # nested cell evaluations before the engine unwinds and restarts bottom-up
_RECURSION_LIMIT = 30000


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
        self.input_value: List[Dict[int, Any]] = [dict() for _ in range(n)]    # shared overrides of inputs
        self.pins: List[Dict[int, Any]] = [dict() for _ in range(n)]           # pinned (formula) cells
        self.spill_zone: List[Dict[int, Tuple[int, ...]]] = [dict() for _ in range(n)]  # rc -> anchors
        self.spill_anchors: List[Dict[int, Tuple[int, int]]] = [dict() for _ in range(n)]
        self._mask_pool: Dict[int, int] = {}
        self.circular: List[str] = []
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
        """
        fresh = False
        for si, rc in cells:
            if rc not in self.input_mask[si]:
                key = ("group", group) if group else ("cell", si, rc)
                self.input_mask[si][rc] = self.bit(key)
                fresh = True
        if fresh:
            self.reset()

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
    def register_spill(self, si: int, anchor_rc: int, max_rows: int, max_cols: int) -> None:
        """Declare that the formula at ``anchor_rc`` may write an array over the cells below / right."""
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
        self.reset()


class Calc(object):
    """A calculation state: memoised cell values (+ dependency masks) for one set of inputs."""

    def __init__(self, engine: Engine, parent: Optional["Calc"], overlay: Optional[Dict[Tuple[int, int], Any]]):
        self.engine = engine
        self.parent = parent
        n = engine.nsheets
        self.memo: List[Dict[int, Any]] = [dict() for _ in range(n)]
        self.maskd: List[Dict[int, int]] = [dict() for _ in range(n)]
        self.rcache: Dict[Tuple[int, int, int, int, int], Tuple[Any, Any, int]] = {}
        self.overlay: Dict[Tuple[int, int], Any] = dict(overlay or {})
        self.omask = 0
        self.cm = 0
        self.depth = 0
        self.busy: List[set] = [set() for _ in range(n)]
        self.evals = 0
        self._reset()

    # ------------------------------------------------------------------ state management
    def _reset(self) -> None:
        eng = self.engine
        n = eng.nsheets
        self.rcache = {}
        self.cm = 0
        self.depth = 0
        self.busy = [set() for _ in range(n)]
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
        else:
            self.memo = [dict() for _ in range(n)]
            self.maskd = [dict() for _ in range(n)]
            self._seed_overlay()

    def _seed_overlay(self) -> None:
        eng = self.engine
        self.omask = 0
        for (si, rc), v in self.overlay.items():
            bit = eng.input_mask[si].get(rc)
            if bit is None:
                continue
            self.memo[si][rc] = v
            self.maskd[si][rc] = bit
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
                self.maskd[si].pop(rc, None)
        self._seed_overlay()

    def _invalidate(self, changed: int) -> None:
        eng = self.engine
        shared = self.parent is None
        for si in range(eng.nsheets):
            md = self.maskd[si]
            if not md:
                continue
            memo = self.memo[si]
            inputs = eng.input_mask[si]
            fml = eng.fml[si]
            iv = eng.input_value[si]
            overlay = self.overlay
            dead = []
            for rc, k in md.items():
                if k & changed:
                    if rc in inputs:
                        # an input keeps its value unless it is a formula default that must be recomputed
                        if shared:
                            if not (rc in fml and rc not in iv):
                                continue
                        elif (si, rc) in overlay:
                            continue
                    dead.append(rc)
            for rc in dead:
                del md[rc]
                memo.pop(rc, None)
            if shared:
                fml = eng.fml[si]
                for rc, bit in inputs.items():
                    if bit & changed:
                        v = eng.input_value[si].get(rc, _MISS)
                        if v is _MISS:
                            if rc in fml:
                                # an input holding a default formula: recompute it (it keeps its input bit)
                                memo.pop(rc, None)
                                md.pop(rc, None)
                                continue
                            v = eng.consts[si].get(rc)
                        memo[rc] = v
                        md[rc] = bit
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
                guard += 1
                if guard > 2000000:
                    raise RuntimeError("evaluation does not converge")
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
        if parent is not None:
            pv = parent.memo[si].get(rc, _MISS)
            if pv is not _MISS:
                k = parent.maskd[si].get(rc)
                if not k:
                    return pv
                if not (k & self.omask):
                    self.cm |= k
                    return pv
        eng = self.engine
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
        parent = self.parent
        target = self if (parent is None or (k & self.omask)) else parent
        target.memo[si][rc] = v
        if k:
            target.maskd[si][rc] = self.engine.intern_mask(k)
        return v

    def _eval(self, si: int, rc: int, r: int, c: int, tid: int) -> Any:
        busy = self.busy[si]
        if rc in busy:
            eng = self.engine
            if len(eng.circular) < 200:
                eng.circular.append(eng.addr(si, rc))
            return 0.0
        if self.depth >= DEPTH_LIMIT:
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

    old = threading.stack_size()
    try:
        threading.stack_size(256 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass
    try:
        t = threading.Thread(target=target, name="tto-engine")
        t.start()
    finally:
        try:
            threading.stack_size(old)
        except (ValueError, RuntimeError):
            pass
    t.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")
