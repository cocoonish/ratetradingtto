"""Which formulas read a cell: a reverse index of the formulas' static references.

A formula reads cells only through what its text names - a cell, a range, whole columns / rows, a defined name, the
box ``A1:INDEX(...)`` spans; INDEX / CHOOSE / IF return references inside the ones they are given.  (The engine has
no OFFSET / INDIRECT; a workbook that had them would make the index incomplete - :attr:`RefIndex.complete` - and
nothing would be taken from it.)  So everything a cell flows into - its readers, their readers ..., with the cells an
array formula among them writes - can be told without computing anything.

The engine uses it when a constant is typed over once values are computed: the values downstream of the cell are
marked with the cell's new dependency bit instead of every value of every user being dropped.  The other way round,
:meth:`RefIndex.upstream` tells which inputs a page's table reads (``tests/test_views.py``: each table's inputs are in
its tab).
"""
from __future__ import annotations

import bisect
from typing import Any, Dict, Hashable, Iterable, List, Optional, Set, Tuple

from .model import COLS
from .parser import parse_template

DYNAMIC = ("OFFSET", "INDIRECT")      # functions whose cells are known only when computed
_BUCKET = 64                           # rows per bucket of the range index (a bucket: these rows of one column)
_TALL = 64 * 32                        # ranges taller than this are checked one by one (whole columns ...)
_WIDE = 64                             # ... and wider than this (whole rows ...)
_SHIFT = 8                             # a cell as one int: rc << _SHIFT | sheet (up to 256 sheets)

Box = Tuple[int, int, int, int, int]   # sheet, r1, c1, r2, c2


class RefIndex(object):
    def __init__(self, engine):
        self.engine = engine
        model = engine.model
        self.model = model
        self.complete = True
        self.dynamic: List[str] = []                   # cells of formulas that make the index incomplete (a few)
        self._specs: Dict[int, Optional[List[Any]]] = {}
        self._names: Dict[Tuple[Optional[int], str], Optional[List[Any]]] = {}
        n = len(model.sheets)
        if n > (1 << _SHIFT):
            self.complete = False                      # (a cell is encoded with its sheet in _SHIFT bits)
            n = 0
        # the formulas that name a cell, encoded (rc << _SHIFT | sheet): one int, or a list of them
        self.point: List[Dict[int, Any]] = [dict() for _ in range(n)]
        self._boxes: List[Dict[Tuple[int, int, int, int], List[int]]] = [dict() for _ in range(n)]
        self.buckets: List[Dict[int, List[Tuple[int, int, int, int, List[int]]]]] = [dict() for _ in range(n)]
        self.tall: List[List[Tuple[int, int, int, int, List[int]]]] = [[] for _ in range(n)]
        self.formulas = 0
        for s in model.sheets[:n]:
            for rc, tid in s.fml.items():
                self._add(s.index, rc, tid)
        self._specs = {}
        self._names = {}
        for si, boxes in enumerate(self._boxes):
            b = self.buckets[si]
            for (r1, c1, r2, c2), hosts in boxes.items():
                ent = (r1, c1, r2, c2, hosts)
                if r2 - r1 >= _TALL or c2 - c1 >= _WIDE:
                    self.tall[si].append(ent)
                    continue
                for k in range(r1 // _BUCKET, r2 // _BUCKET + 1):
                    for c in range(c1, c2 + 1):
                        key = k * COLS + c
                        lst = b.get(key)
                        if lst is None:
                            b[key] = [ent]
                        else:
                            lst.append(ent)
        self._boxes = []

    # ------------------------------------------------------------------ building
    def _add(self, si: int, rc: int, tid: int) -> None:
        specs = self._template_specs(tid)
        self.formulas += 1
        if specs is None:
            self.complete = False
            if len(self.dynamic) < 20:
                self.dynamic.append("%s!%d" % (self.model.sheets[si].name, rc))
            return
        r, c = divmod(rc, COLS)
        host = rc << _SHIFT | si
        for box in self._resolve(specs, si, r, c):
            bs, r1, c1, r2, c2 = box
            if r1 == r2 and c1 == c2:
                point = self.point[bs]
                key = r1 * COLS + c1
                got = point.get(key)
                if got is None:
                    point[key] = host
                elif type(got) is int:
                    if got != host:
                        point[key] = [got, host]
                elif got[-1] != host:
                    got.append(host)
            else:
                boxes = self._boxes[bs]
                lst = boxes.get((r1, c1, r2, c2))
                if lst is None:
                    boxes[(r1, c1, r2, c2)] = [host]
                elif lst[-1] != host:
                    lst.append(host)

    def _template_specs(self, tid: int) -> Optional[List[Any]]:
        """The references of a template, unresolved (``None``: it reads cells it computes at run time)."""
        if tid in self._specs:
            return self._specs[tid]
        try:
            specs = self._node_specs(parse_template(self.model.templates[tid]), set())
        except Exception:  # noqa: BLE001 - a template the parser does not read compiles to an error: it reads nothing
            specs = []
        self._specs[tid] = specs
        return specs

    def _node_specs(self, root, names_seen: Set[str]) -> Optional[List[Any]]:
        out: List[Any] = []
        stack = [root]
        while stack:
            nd = stack.pop()
            kind = nd[0]
            if kind in ("cell", "range", "cols", "rows"):
                out.append(nd)
            elif kind == "name":
                sub = self._name_specs(nd[1], nd[2], names_seen)
                if sub is None:
                    return None
                out.extend(sub)
            elif kind == "func":
                if nd[1] in DYNAMIC:
                    return None
                stack.extend(nd[2])
            elif kind == "bin":
                if nd[1] == ":":
                    a = self._node_specs(nd[2], names_seen)
                    b = self._node_specs(nd[3], names_seen)
                    if a is None or b is None:
                        return None
                    out.append(("union", a, b))         # the box the two span (A1:INDEX(B1:B9,n))
                stack.append(nd[2])
                stack.append(nd[3])
            elif kind in ("neg", "pos", "pct", "single", "paren"):
                stack.append(nd[1])
        return out

    def _name_specs(self, name: str, sheet: Optional[str], seen: Set[str]) -> Optional[List[Any]]:
        model = self.model
        si = model.sheet_index.get(sheet) if sheet else None
        key = (si, name)
        if key in self._names:
            return self._names[key]
        text = None
        if si is not None:
            text = getattr(model, "local_names", {}).get((si, name))
        if text is None:
            text = model.names.get(name)
        if text is None or name in seen:
            specs: Optional[List[Any]] = []             # an unknown name is #NAME? (a LET's own name: its value)
        else:
            try:
                specs = self._node_specs(parse_template(text), seen | {name})
            except Exception:  # noqa: BLE001
                specs = []
        self._names[key] = specs
        return specs

    def _resolve(self, specs: List[Any], si: int, r: int, c: int) -> List[Box]:
        out: List[Box] = []
        eng = self.engine
        idx = self.model.sheet_index
        for nd in specs:
            kind = nd[0]
            if kind == "union":
                a = self._resolve(nd[1], si, r, c)
                b = self._resolve(nd[2], si, r, c)
                parts = a + b
                if parts and all(p[0] == parts[0][0] for p in parts):
                    out.append((parts[0][0], min(p[1] for p in parts), min(p[2] for p in parts),
                                max(p[3] for p in parts), max(p[4] for p in parts)))
                else:
                    out.extend(parts)
                continue
            bs = si if nd[1] is None else idx.get(nd[1])
            if bs is None:
                continue                                 # a sheet that is not there: #REF!
            if kind == "cell":
                rr = nd[3] if nd[2] else r + nd[3]
                cc = nd[5] if nd[4] else c + nd[5]
                out.append((bs, rr, cc, rr, cc))
            elif kind == "range":
                r1 = nd[3] if nd[2] else r + nd[3]
                c1 = nd[5] if nd[4] else c + nd[5]
                r2 = nd[7] if nd[6] else r + nd[7]
                c2 = nd[9] if nd[8] else c + nd[9]
                out.append((bs, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)))
            elif kind == "cols":
                c1 = nd[3] if nd[2] else c + nd[3]
                c2 = nd[5] if nd[4] else c + nd[5]
                out.append((bs, 1, min(c1, c2), max(eng.max_row[bs], 1), max(c1, c2)))
            elif kind == "rows":
                r1 = nd[3] if nd[2] else r + nd[3]
                r2 = nd[5] if nd[4] else r + nd[5]
                out.append((bs, min(r1, r2), 1, max(r1, r2), max(eng.max_col[bs], 1)))
        return out

    # ------------------------------------------------------------------ queries
    def reads(self, si: int, rc: int) -> Optional[List[Box]]:
        """The boxes of cells the formula in (si, rc) names - ``[]`` for a constant, ``None`` for a formula whose cells
        are known only when computed (OFFSET / INDIRECT)."""
        tid = self.engine.fml[si].get(rc)
        if tid is None:
            return []
        specs = self._template_specs(tid)
        if specs is None:
            return None
        return self._resolve(specs, si, *divmod(rc, COLS))

    def upstream(self, groups: Dict[Hashable, Iterable[Tuple[int, int]]],
                 stop: Iterable[Tuple[int, int]]) -> Dict[Hashable, Set[Tuple[int, int]]]:
        """For each group of cells, the cells of ``stop`` its values follow from: what the formulas of the group name,
        what those name ..., a cell an array formula writes through that formula - each chain ending at a cell of
        ``stop`` (the inputs: whatever is typed into one ends it; what an input's own default formula reads is not
        followed).  A box a formula names is walked through the cells in it that hold something to follow.

        The groups share one walk (a page's tables read much of the same).  A formula whose cells are known only when
        computed (OFFSET / INDIRECT: an incomplete index) adds nothing; in a circular chain a cell being walked counts
        once."""
        eng = self.engine
        stop = set(stop)
        order = sorted(stop)
        bit = {cell: 1 << i for i, cell in enumerate(order)}
        keys: Dict[int, List[int]] = {}

        def inside(si: int, r1: int, c1: int, r2: int, c2: int) -> List[int]:
            got = keys.get(si)
            if got is None:
                got = keys[si] = sorted(set(eng.fml[si]) | set(eng.members[si]) | set(eng.spill_zone[si])
                                        | {rc for s, rc in stop if s == si})
            lo = bisect.bisect_left(got, r1 * COLS + c1)
            hi = bisect.bisect_right(got, r2 * COLS + c2)
            return [rc for rc in got[lo:hi] if c1 <= rc % COLS <= c2]

        def follow(node):
            """What a node reads: a cell (sheet, rc) - its formula's boxes, or the formula that writes it -, a box
            (sheet, r1, c1, r2, c2) - its cells."""
            if len(node) == 2:
                si, rc = node
                if rc in eng.fml[si]:
                    for box in self.reads(si, rc) or ():
                        bs, r1, c1, r2, c2 = box
                        yield (bs, r1 * COLS + c1) if r1 == r2 and c1 == c2 else box
                    return
                anchor = eng.members[si].get(rc)
                if anchor is not None:
                    yield si, anchor
                for anchor in eng.spill_zone[si].get(rc, ()):
                    yield si, anchor
                return
            si = node[0]
            for rc in inside(*node):
                yield si, rc

        memo: Dict[Any, int] = {}
        out: Dict[Hashable, Set[Tuple[int, int]]] = {}
        for key, cells in groups.items():
            mask = 0
            for start in cells:
                start = tuple(start)
                if start in bit:
                    mask |= bit[start]
                    continue
                if start not in memo:
                    # depth first without recursion (chains run thousands of cells deep): [node, what it reads, mask]
                    stack = [[start, follow(start), 0]]
                    walking = {start}
                    while stack:
                        top = stack[-1]
                        for nxt in top[1]:
                            b = bit.get(nxt)
                            if b is not None:
                                top[2] |= b
                                continue
                            got = memo.get(nxt)
                            if got is not None:
                                top[2] |= got
                            elif nxt not in walking:
                                walking.add(nxt)
                                stack.append([nxt, follow(nxt), 0])
                                break
                        else:
                            stack.pop()
                            walking.discard(top[0])
                            memo[top[0]] = top[2]
                            if stack:
                                stack[-1][2] |= top[2]
                mask |= memo[start]
            out[key] = {cell for cell in order if mask & bit[cell]}
        self._specs = {}                                 # (as after building: the templates' references are not kept)
        self._names = {}
        return out

    def readers(self, si: int, rc: int) -> List[Tuple[int, int]]:
        """The formula cells whose references take in (si, rc)."""
        out: List[int] = []
        got = self.point[si].get(rc)
        if got is not None:
            out.extend((got,) if type(got) is int else got)
        r, c = divmod(rc, COLS)
        for r1, c1, r2, c2, hosts in self.buckets[si].get(r // _BUCKET * COLS + c, ()):
            if r1 <= r <= r2 and c1 <= c <= c2:
                out.extend(hosts)
        for r1, c1, r2, c2, hosts in self.tall[si]:
            if r1 <= r <= r2 and c1 <= c <= c2:
                out.extend(hosts)
        low = (1 << _SHIFT) - 1
        return [(h & low, h >> _SHIFT) for h in out]

    def written_by(self, si: int, rc: int) -> List[int]:
        """The cells a formula writes besides its own: an array formula's range, a spilling formula's area."""
        eng = self.engine
        out: List[int] = []
        r0, c0 = divmod(rc, COLS)
        ref = eng.arr[si].get(rc)
        if ref is not None and (ref[0] != ref[2] or ref[1] != ref[3]):
            out.extend(r * COLS + c for r in range(ref[0], ref[2] + 1) for c in range(ref[1], ref[3] + 1))
        room = eng.spill_anchors[si].get(rc)
        if room is not None:
            out.extend(r * COLS + c for r in range(r0, r0 + room[0]) for c in range(c0, c0 + room[1]))
        return [x for x in out if x != rc]

    def downstream(self, cells: Iterable[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        """Every cell whose value follows from ``cells``: their readers, the readers of those ... and what an array
        formula among them writes (the cells themselves are not included)."""
        shift = _SHIFT
        low = (1 << shift) - 1
        start = {rc << shift | si for si, rc in cells}
        seen: Set[int] = set()
        fired: Set[int] = set()                        # ranges whose readers are in already: each range once
        queue = list(start)
        point, buckets, tall = self.point, self.buckets, self.tall
        arr, anchors = self.engine.arr, self.engine.spill_anchors

        def reach(hosts) -> None:
            for h in hosts:
                if h in seen:
                    continue
                seen.add(h)
                queue.append(h)
                hsi, hrc = h & low, h >> shift
                if hrc in arr[hsi] or hrc in anchors[hsi]:
                    for w in self.written_by(hsi, hrc):
                        k = w << shift | hsi
                        if k not in seen:
                            seen.add(k)
                            queue.append(k)

        while queue:
            key = queue.pop()
            si, rc = key & low, key >> shift
            got = point[si].get(rc)
            if got is not None:
                reach((got,) if type(got) is int else got)
            r, c = divmod(rc, COLS)
            for ent in buckets[si].get(r // _BUCKET * COLS + c, ()):
                if ent[0] <= r <= ent[2] and ent[1] <= c <= ent[3] and id(ent) not in fired:
                    fired.add(id(ent))
                    reach(ent[4])
            for ent in tall[si]:
                if ent[0] <= r <= ent[2] and ent[1] <= c <= ent[3] and id(ent) not in fired:
                    fired.add(id(ent))
                    reach(ent[4])
        return {(k & low, k >> shift) for k in seen - start}
