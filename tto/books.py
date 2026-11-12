"""Workbooks loaded into the dashboard: model + engine + input registry."""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .xl.compiler import ADDINS
from .xl.engine import Clock, Engine, cached_pins
from .xl.errors import XlError
from .xl.model import COLS, Model, a1, parse_a1, parse_range
from .xl.parser import parse_template, walk

MAX_SPILL_ROWS = 800
MAX_SPILL_COLS = 12


class InputDef(object):
    """One declared input cell."""

    __slots__ = ("scope", "group", "kind", "label", "options", "view")

    def __init__(self, scope: str = "user", group: Optional[str] = None, kind: str = "auto",
                 label: str = "", options: Optional[List[str]] = None, view: str = ""):
        self.scope = scope            # "user" (personal / scenario) or "shared" (whole desk)
        self.group = group
        self.kind = kind              # auto | number | pct | date | text | list
        self.label = label
        self.options = options
        self.view = view


class Book(object):
    def __init__(self, book_id: str, title: str, model: Model, provider=None, clock: Optional[Clock] = None,
                 replay: bool = False):
        self.id = book_id
        self.title = title
        self.model = model
        self.replay = replay
        self.engine = Engine(model, provider=provider, clock=clock)
        self.inputs: Dict[Tuple[int, int], InputDef] = {}
        self._validation: Dict[Tuple[int, int], List[str]] = {}
        self._index_validations()
        self._register_spills()
        if replay:
            self.engine.set_pins(cached_pins(model))

    # ------------------------------------------------------------------ addressing
    def cell(self, ref: str) -> Tuple[int, int]:
        return self.model.cell_ref(ref)

    def ref(self, si: int, rc: int) -> str:
        return "%s!%s" % (self.model.sheets[si].name, a1(rc))

    def cells_of(self, ref: str, default_sheet: Optional[str] = None) -> List[Tuple[int, int]]:
        """``"Forward!W33:X47"`` (or ``"W33:X47"`` with a default sheet) -> list of (sheet, rc)."""
        sheet, _, addr = ref.rpartition("!")
        sheet = sheet.strip("'") or default_sheet
        si = self.model.sheet_index[sheet]
        r1, c1, r2, c2 = parse_range(addr)
        return [(si, r * COLS + c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]

    # ------------------------------------------------------------------ inputs
    def declare(self, ref: str, default_sheet: Optional[str] = None, **kw) -> List[Tuple[int, int]]:
        cells = self.cells_of(ref, default_sheet)
        d = InputDef(**kw)
        fresh = [c for c in cells if c not in self.inputs]
        for c in cells:
            self.inputs[c] = d
        if fresh:
            self.engine.declare_inputs(fresh, group=("%s:%s" % (d.scope, d.group)) if d.group else None)
        return cells

    def input_def(self, si: int, rc: int) -> Optional[InputDef]:
        return self.inputs.get((si, rc))

    def options_for(self, si: int, rc: int) -> Optional[List[str]]:
        d = self.inputs.get((si, rc))
        if d is not None and d.options:
            return d.options
        return self._validation.get((si, rc))

    def _index_validations(self) -> None:
        """Drop-down lists defined in the workbook (data validation of type list with literal items)."""
        for s in self.model.sheets:
            for v in s.validations:
                f1 = v.get("formula1")
                if v.get("type") != "list" or not f1 or not f1.startswith('"'):
                    continue
                items = [x.strip() for x in f1.strip('"').split(",")]
                for part in (v.get("sqref") or "").split():
                    try:
                        r1, c1, r2, c2 = parse_range(part)
                    except Exception:  # noqa: BLE001
                        continue
                    if (r2 - r1 + 1) * (c2 - c1 + 1) > 5000:
                        continue
                    for r in range(r1, r2 + 1):
                        for c in range(c1, c2 + 1):
                            self._validation[(s.index, r * COLS + c)] = items

    # ------------------------------------------------------------------ spills (BDH / BDS / dynamic arrays)
    def _register_spills(self) -> None:
        """Formulas that write an array below / right of their own cell (Bloomberg history, bulk data and
        dynamic arrays): reserve the area they may cover so readers always wait for the fresh array."""
        model = self.model
        roots: Dict[int, Any] = {}
        for s in model.sheets:
            for rc, tid in s.fml.items():
                root = roots.get(tid)
                if root is None:
                    try:
                        root = parse_template(model.templates[tid])
                    except Exception:  # noqa: BLE001
                        root = ("num", 0.0)
                    while root[0] == "paren":
                        root = root[1]
                    roots[tid] = root
                is_bulk = root[0] == "func" and root[1] in ("BDH", "BDS")
                ref = s.arr.get(rc)
                multi = ref is not None and (ref[0] != ref[2] or ref[1] != ref[3])
                if not (is_bulk or (multi and rc in s.dyn)):
                    continue
                r0, c0 = divmod(rc, COLS)
                if multi:
                    width = ref[3] - ref[1] + 1
                elif root[1] == "BDH":
                    opts = " ".join(str(a[1]).upper() for a in root[2] if a[0] == "str")
                    width = 1 if ("DATES=H" in opts or "DTS=H" in opts) else 2
                else:
                    width = 1
                    while width < MAX_SPILL_COLS and (r0 * COLS + c0 + width) not in s.fml:
                        if (r0 * COLS + c0 + width) not in s.consts and width >= 3:
                            break
                        width += 1
                height = 1
                limit = min(s.max_row + 1, r0 + MAX_SPILL_ROWS)
                r = r0 + 1
                while r <= limit:
                    blocked = False
                    for c in range(c0, c0 + width):
                        k = r * COLS + c
                        if k in s.fml:
                            blocked = True
                            break
                        v = s.consts.get(k)
                        if type(v) is str and k not in s.members and not is_bulk:
                            blocked = True
                            break
                    if blocked:
                        break
                    height += 1
                    r += 1
                if multi:
                    height = max(height, ref[2] - ref[0] + 1)
                self.engine.register_spill(s.index, rc, height, width)


def formula_text(book: Book, si: int, rc: int) -> Optional[str]:
    """The Excel formula of a cell in A1 notation (``None`` for constants)."""
    from .xl.unparse import to_a1
    s = book.model.sheets[si]
    tid = s.fml.get(rc)
    if tid is None:
        return None
    r, c = divmod(rc, COLS)
    try:
        return "=" + to_a1(book.model.templates[tid], r, c)
    except Exception:  # noqa: BLE001
        return "=" + book.model.templates[tid]


def load_books(models_dir: str, provider=None, clock: Optional[Clock] = None, replay: bool = False) -> Dict[str, Book]:
    books: Dict[str, Book] = {}
    for book_id, title, fname in (("tto", "TRY masa", "tto.json.gz"), ("sofr", "USD SOFR / FOMC", "sofr.json.gz")):
        path = os.path.join(models_dir, fname)
        if not os.path.exists(path):
            continue
        books[book_id] = Book(book_id, title, Model.load(path), provider=provider, clock=clock, replay=replay)
    return books


def snapshot_today(model: Model) -> Optional[float]:
    """The date on which the workbook was last calculated (cached value of a plain ``=TODAY()`` cell)."""
    for s in model.sheets:
        for rc, tid in s.fml.items():
            if model.templates[tid].upper() == "TODAY()" and rc in s.cached:
                v = s.cached[rc]
                if type(v) is float:
                    return v
    return None
