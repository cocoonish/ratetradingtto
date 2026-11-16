"""Workbooks loaded into the dashboard: model + engine + input registry."""
from __future__ import annotations

import logging
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

    __slots__ = ("scope", "group", "kind", "label", "options", "view", "aliases", "tenor")

    def __init__(self, scope: str = "user", group: Optional[str] = None, kind: str = "auto",
                 label: str = "", options: Optional[List[str]] = None, view: str = "",
                 aliases: Optional[Dict[str, str]] = None, tenor: Optional[Dict[str, str]] = None):
        self.scope = scope            # "user" (personal / scenario) or "shared" (whole desk)
        self.group = group
        self.kind = kind              # auto | number | amount | pct | date | text | list (one of the options only)
        self.label = label
        self.options = options
        self.view = view
        self.aliases = aliases        # words that mean an option ({"Sat": "S"})
        self.tenor = tenor            # a date typed as a tenor ("1A"): its pair / calendar and start (tto/shortcuts.py)


class Book(object):
    def __init__(self, book_id: str, title: str, model: Model, provider=None, clock: Optional[Clock] = None,
                 replay: bool = False):
        self.id = book_id
        self.title = title
        self.model = model
        self.replay = replay
        self.recorded = True                      # the workbook file holds recorded Bloomberg values
        self.left_out: List[str] = []             # additions of the dashboard that do not fit this file
        self.engine = Engine(model, provider=provider, clock=clock)
        self.inputs: Dict[Tuple[int, int], InputDef] = {}
        self._validation: Dict[Tuple[int, int], List[str]] = {}
        self._validation_ranges: Dict[Tuple[int, int], Tuple[int, int, int, int, int]] = {}
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
        return self.declare_cells(self.cells_of(ref, default_sheet), **kw)

    def declare_cells(self, cells: List[Tuple[int, int]], **kw) -> List[Tuple[int, int]]:
        """Inputs of one definition (scope, group ...), declared to the engine at once."""
        d = InputDef(**kw)
        fresh = [c for c in cells if c not in self.inputs]
        for c in cells:
            self.inputs[c] = d
        if fresh:
            self.engine.declare_inputs(fresh, group=("%s:%s" % (d.scope, d.group)) if d.group else None)
        return cells

    def input_def(self, si: int, rc: int) -> Optional[InputDef]:
        return self.inputs.get((si, rc))

    def options_for(self, si: int, rc: int, calc=None) -> Optional[List[str]]:
        """Items of the cell's drop-down list.  A list that Excel reads from a range ("=$B$6:$B$25") needs
        ``calc`` - its items are whatever those cells hold right now."""
        d = self.inputs.get((si, rc))
        if d is not None and d.options:
            return d.options
        items = self._validation.get((si, rc))
        if items is None and calc is not None:
            src = self._validation_ranges.get((si, rc))
            if src is not None:
                items = self._range_items(calc, src)
        return items

    @staticmethod
    def _range_items(calc, src: Tuple[int, int, int, int, int]) -> Optional[List[str]]:
        ssi, r1, c1, r2, c2 = src
        out: List[str] = []
        try:
            rows = calc.get_range(ssi, r1, c1, r2, c2)
        except Exception:  # noqa: BLE001 - a list that cannot be read is simply not offered
            return None
        for row in rows:
            for v in row:
                if v is None or v == "" or type(v) is XlError:
                    continue
                if type(v) is float:
                    text = str(int(v)) if v == int(v) else repr(v)
                elif type(v) is bool:
                    text = "TRUE" if v else "FALSE"
                else:
                    text = str(v)
                if text not in out:
                    out.append(text)
        return out[:300] or None

    def _index_validations(self) -> None:
        """Drop-down lists defined in the workbook: data validation of type list, with literal items
        ("USD,EUR") or with a range of cells that holds the items."""
        for s in self.model.sheets:
            for v in s.validations:
                f1 = (v.get("formula1") or "").strip()
                if v.get("type") != "list" or not f1:
                    continue
                items = None
                src = None
                if f1.startswith('"'):
                    items = [x.strip() for x in f1.strip('"').split(",")]
                else:
                    sheet_name, _, addr = f1.lstrip("=").rpartition("!")
                    sheet_name = sheet_name.strip("'") or s.name
                    try:
                        r1, c1, r2, c2 = parse_range(addr.replace("$", ""))
                        src = (self.model.sheet_index[sheet_name], r1, c1, r2, c2)
                    except Exception:  # noqa: BLE001 - a named list or a formula: no menu, typing still works
                        continue
                    if (r2 - r1 + 1) * (c2 - c1 + 1) > 2000:
                        continue
                for part in (v.get("sqref") or "").split():
                    try:
                        r1, c1, r2, c2 = parse_range(part)
                    except Exception:  # noqa: BLE001
                        continue
                    if (r2 - r1 + 1) * (c2 - c1 + 1) > 5000:
                        continue
                    for r in range(r1, r2 + 1):
                        for c in range(c1, c2 + 1):
                            if items is not None:
                                self._validation[(s.index, r * COLS + c)] = items
                            else:
                                self._validation_ranges[(s.index, r * COLS + c)] = src

    # ------------------------------------------------------------------ spills (BDH / BDS / dynamic arrays)
    def _register_spills(self) -> None:
        """Formulas that write an array below / right of their own cell (Bloomberg history, bulk data and
        dynamic arrays): reserve the area they may cover so readers always wait for the fresh array."""
        model = self.model
        roots: Dict[int, Any] = {}
        registered = False
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
                # a dynamic-array function decides its own size: FILTER can return as much as it is given,
                # whatever the single cell Excel happened to save for it
                shape = None
                if rc in s.dyn and root[0] == "func" and root[1] == "FILTER" and root[2]:
                    shape = _range_shape(root[2][0], *divmod(rc, COLS))
                if not (is_bulk or (multi and rc in s.dyn) or shape is not None):
                    continue
                r0, c0 = divmod(rc, COLS)
                if shape is not None:
                    width = max(shape[1], ref[3] - ref[1] + 1 if multi else 1)
                elif multi:
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
                if shape is not None:
                    limit = r0 + min(shape[0], MAX_SPILL_ROWS) - 1
                    # the cells right of the anchor must be free as well
                    for c in range(c0 + 1, c0 + width):
                        k = r0 * COLS + c
                        if k in s.fml or (type(s.consts.get(k)) is str and k not in s.members):
                            width = c - c0
                            self.engine.spill_blocked[s.index].add(rc)
                            break
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
                        if shape is not None:
                            self.engine.spill_blocked[s.index].add(rc)      # more than this is #SPILL!
                        break
                    height += 1
                    r += 1
                if multi:
                    height = max(height, ref[2] - ref[0] + 1)
                self.engine.register_spill(s.index, rc, height, width, reset=False)
                registered = True
        if registered:
            self.engine.reset()                           # once, not after each of the ~150 areas


def _range_shape(node, r0: int, c0: int) -> Optional[Tuple[int, int]]:
    """(rows, columns) of a range / cell reference node for a formula hosted at (r0, c0)."""
    while node[0] == "paren":
        node = node[1]
    if node[0] == "cell":
        return 1, 1
    if node[0] != "range":
        return None
    ra1, r1, ca1, c1, ra2, r2, ca2, c2 = node[2:10]
    row1, row2 = (r1 if ra1 else r0 + r1), (r2 if ra2 else r0 + r2)
    col1, col2 = (c1 if ca1 else c0 + c1), (c2 if ca2 else c0 + c2)
    return abs(row2 - row1) + 1, abs(col2 - col1) + 1


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


#: the workbooks of the dashboard: id, title, model file, "the file holds the Bloomberg values of its last
#: calculation".  A workbook saved without a Bloomberg connection has nothing recorded: offline it is
#: calculated from what the other workbooks recorded (and the offline quote files) instead of being frozen.
BOOKS = (("tto", "TRY masa", "tto.json.gz", True), ("sofr", "USD SOFR / FOMC", "sofr.json.gz", True),
         ("borsa", "Borsa İstanbul swap", "borsa.json.gz", False), ("asw", "DİBS ASW (TLREF OIS)", "asw.json.gz", False))


#: sheets of a workbook the desk does not use: taken out of the model as it loads - nothing of them is calculated or
#: asked of Bloomberg and the sheet explorer does not list them.  The Excel file and the model file keep them (a
#: workbook imported again is still a pure import); no other sheet refers to them.
REMOVED_SHEETS: Dict[str, Tuple[str, ...]] = {"tto": ("MOBIL MK", "YP DIBS", "Ivır Zıvır", "USDTRY IYIX")}


def remove_sheets(book_id: str, model: Model) -> List[str]:
    """Take the sheets :data:`REMOVED_SHEETS` names for ``book_id`` out of ``model``: the others keep their order
    and are numbered again, and a hyperlink to a sheet taken out goes with it.  Returns the names taken out.

    A sheet that a formula of another sheet or a defined name refers to (a workbook imported again with another
    layout) stays, with a warning: taking it out would turn those formulas into ``#REF!``."""
    gone = {name for name in REMOVED_SHEETS.get(book_id, ()) if name in model.sheet_index}
    used = set()
    for name in gone:
        mark = "`%s!" % name                       # a template's reference to another sheet: `OIS_MAIN!R2C10`
        if any(mark in text for text in model.names.values()) or any(
                mark in model.templates[tid] for s in model.sheets if s.name not in gone for tid in set(s.fml.values())):
            used.add(name)
            logging.getLogger("tto").warning("%s: '%s' sayfasına başka formüller başvuruyor, sayfa kaldırılmadı", book_id, name)
    gone -= used
    if not gone:
        return []
    keep = [s for s in model.sheets if s.name not in gone]
    number = {s.index: i for i, s in enumerate(keep)}
    for s in keep:
        s.index = number[s.index]
        s.links = [link for link in s.links
                   if str(link.get("location") or "").rpartition("!")[0].strip("'") not in gone]
    model.sheets = keep
    model.sheet_index = {s.name: s.index for s in keep}
    model.local_names = {(number[i], name): text for (i, name), text in model.local_names.items() if i in number}
    return sorted(gone)


def load_books(models_dir: str, provider=None, clock: Optional[Clock] = None, replay: bool = False,
               extras: bool = True) -> Dict[str, Book]:
    """Load the workbook models, without the sheets the desk does not use (:data:`REMOVED_SHEETS`).  ``extras``
    adds the dashboard's own sheets (``tto.extras``) to them - calculations that are not in the Excel files but
    are written as ordinary Excel formulas."""
    books: Dict[str, Book] = {}
    for book_id, title, fname, recorded in BOOKS:
        path = os.path.join(models_dir, fname)
        if not os.path.exists(path):
            continue
        model = Model.load(path)
        remove_sheets(book_id, model)
        left_out: List[str] = []
        if extras:
            from . import extras as _extras
            left_out = _extras.apply(book_id, model)
        books[book_id] = Book(book_id, title, model, provider=provider, clock=clock, replay=replay and recorded)
        books[book_id].recorded = recorded
        books[book_id].left_out = left_out
        for text in left_out:
            logging.getLogger("tto").warning("%s: dashboard eki dosyaya uymadığı için dışarıda bırakıldı - %s", fname, text)
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
