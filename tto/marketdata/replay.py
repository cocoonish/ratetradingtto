"""Replay provider: serves a frozen snapshot (no Bloomberg connection needed).

Used for the offline demo and for tests.  The snapshot is a plain dict ``key -> value`` (see
:mod:`tto.marketdata.base` for the key shapes); :func:`snapshot_from_model` rebuilds one from the values
Excel cached in the workbook at its last save.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..xl.errors import E_NA, XlError
from ..xl.values import XlArray
from .base import Provider, bdp_key


class ReplayProvider(Provider):
    live = False

    def __init__(self, snapshot: Optional[Dict[Tuple, Any]] = None, label: str = ""):
        self.snapshot: Dict[Tuple, Any] = dict(snapshot or {})
        self.label = label
        self.missing: Dict[Tuple, int] = {}

    def _get(self, key):
        v = self.snapshot.get(key)
        if v is None:
            self.missing[key] = self.missing.get(key, 0) + 1
            return E_NA
        return v

    get_bdp = _get
    get_bdh = _get
    get_bds = _get
    get_bfx = _get
    get_rt = _get

    def set(self, key: Tuple, value: Any) -> None:
        self.snapshot[key] = value

    def update(self, values: Dict[Tuple, Any]) -> List[Tuple]:
        """Merge values; returns the keys whose value changed."""
        changed = []
        for k, v in values.items():
            if self.snapshot.get(k) != v:
                self.snapshot[k] = v
                changed.append(k)
        return changed

    def status(self) -> Dict[str, Any]:
        return {"mode": "replay", "connected": False, "label": self.label, "items": len(self.snapshot)}

    def load_quotes(self, path: str) -> None:
        """Load ``{"TICKER|FIELD": value}`` JSON (keys starting with "_" are comments)."""
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for k, v in data.items():
            if k.startswith("_"):
                continue
            sec, _, fld = k.partition("|")
            self.snapshot[bdp_key(sec.strip(), fld.strip() or "PX_LAST")] = float(v) if isinstance(v, (int, float)) else v


class _KeyCapture(Provider):
    """Returns the normalised key of a call instead of its value."""

    def get_bdp(self, key):
        return key

    get_bdh = get_bds = get_bfx = get_rt = get_bdp


class _NoDeps(object):
    def depend_on_market(self, key):
        pass


def snapshot_from_model(engine) -> Dict[Tuple, Any]:
    """Rebuild ``key -> value`` from the workbook: every cell that is exactly one add-in call and has a
    cached value tells what Bloomberg returned for that call at the last save."""
    from ..xl.compiler import ADDINS
    from ..xl.engine import addin_cells
    from ..xl.model import COLS
    from ..xl.parser import parse_template

    model = engine.model
    calc = engine.shared
    capture = _KeyCapture()
    nodeps = _NoDeps()
    snap: Dict[Tuple, Any] = {}
    ast_cache: Dict[int, Any] = {}
    for si, rc in addin_cells(model):
        sh = model.sheets[si]
        if rc not in sh.cached:
            continue
        tid = sh.fml[rc]
        root = ast_cache.get(tid)
        if root is None:
            try:
                root = parse_template(model.templates[tid])
            except Exception:  # noqa: BLE001
                root = ("num", 0.0)
            while root[0] == "paren":
                root = root[1]
            ast_cache[tid] = root
        if root[0] != "func" or not (root[3] or root[1] in ADDINS) or root[1] == "BINTERPOL":
            continue
        r, c = divmod(rc, COLS)
        try:
            args = [engine.compiler.compile_node(a)(calc, si, r, c) if a[0] != "missing" else None for a in root[2]]
            key = capture.call(nodeps, root[1], si, r, c, args)
        except Exception:  # noqa: BLE001
            continue
        if type(key) is not tuple:
            continue
        value = sh.cached[rc]
        if root[1] in ("BDH", "BDS"):
            # the block the call filled: its saved array range, or the area reserved for it below / right
            # (the cells an add-in writes into are plain value cells in the file)
            ref = sh.arr.get(rc)
            zone = engine.spill_anchors[si].get(rc)
            if ref is not None and (ref[0] != ref[2] or ref[1] != ref[3]):
                r1, c1, r2, c2 = ref
            elif zone is not None and (zone[0] > 1 or zone[1] > 1):
                r1, c1, r2, c2 = r, c, r + zone[0] - 1, c + zone[1] - 1
            else:
                r1 = None
            if r1 is not None:
                rows = []
                for rr in range(r1, r2 + 1):
                    rows.append([sh.cached.get(rr * COLS + cc, sh.consts.get(rr * COLS + cc)) for cc in range(c1, c2 + 1)])
                while len(rows) > 1 and all(x is None for x in rows[-1]):
                    rows.pop()
                width = max((max((j + 1 for j, x in enumerate(row) if x is not None), default=1) for row in rows), default=1)
                rows = [row[:width] for row in rows]
                if len(rows) > 1 or width > 1:
                    value = XlArray(rows)
        snap[key] = value
    return snap
