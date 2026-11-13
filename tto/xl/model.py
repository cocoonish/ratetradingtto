"""In-memory workbook model (formulas, constants, cached values, styles) + (de)serialisation.

A model is produced once from an ``.xlsx`` / ``.xlsm`` file by :mod:`tto.xl.importer` and stored as
gzip-compressed JSON.  Cell coordinates are packed into one int: ``rc = row * 16384 + col``
(both 1-based), see :func:`pack` / :func:`unpack`.
"""
from __future__ import annotations

import gzip
import io
import json
from typing import Any, Dict, List, Optional, Tuple

from .errors import XlError
from .tokenizer import index_to_col, col_to_index

COLS = 16384
MODEL_VERSION = 7


def pack(row: int, col: int) -> int:
    return row * COLS + col


def unpack(rc: int) -> Tuple[int, int]:
    return divmod(rc, COLS)


def a1(rc: int) -> str:
    r, c = divmod(rc, COLS)
    return "%s%d" % (index_to_col(c), r)


def parse_a1(addr: str) -> int:
    addr = addr.replace("$", "")
    i = 0
    while i < len(addr) and addr[i].isalpha():
        i += 1
    return pack(int(addr[i:]), col_to_index(addr[:i]))


def parse_range(ref: str) -> Tuple[int, int, int, int]:
    """``"B3:D10"`` -> (r1, c1, r2, c2); a single address gives a 1x1 range."""
    ref = ref.replace("$", "")
    if ":" in ref:
        a, b = ref.split(":")
    else:
        a = b = ref
    r1, c1 = unpack(parse_a1(a))
    r2, c2 = unpack(parse_a1(b))
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


class Sheet(object):
    __slots__ = ("name", "index", "state", "consts", "fml", "arr", "members", "cached", "styles",
                 "max_row", "max_col", "merges", "col_widths", "validations", "dyn", "cf", "charts",
                 "hidden_rows", "hidden_cols", "freeze", "links", "comments", "images")

    def __init__(self, name: str, index: int, state: str = "visible"):
        self.name = name
        self.index = index
        self.state = state
        self.consts: Dict[int, Any] = {}          # rc -> constant value
        self.fml: Dict[int, int] = {}             # rc -> template id
        self.arr: Dict[int, Tuple[int, int, int, int]] = {}   # anchor rc -> array ref
        self.members: Dict[int, int] = {}         # rc -> anchor rc (cells covered by an array formula)
        self.cached: Dict[int, Any] = {}          # rc -> value cached by Excel (formula & member cells)
        self.styles: Dict[int, int] = {}          # rc -> xf index
        self.max_row = 0
        self.max_col = 0
        self.merges: List[str] = []
        self.col_widths: Dict[int, float] = {}
        self.validations: List[Dict[str, Any]] = []
        self.dyn: set = set()                     # anchors flagged as dynamic arrays (cm attribute)
        self.cf: List[Dict[str, Any]] = []        # conditional-formatting rules
        self.charts: List[Dict[str, Any]] = []    # charts drawn on the sheet (series are range references)
        self.hidden_rows: List[List[int]] = []    # [first, last] runs of rows hidden in Excel
        self.hidden_cols: List[List[int]] = []    # [first, last] runs of columns hidden in Excel
        self.freeze: List[int] = [0, 0]           # frozen panes: [rows, columns]
        self.links: List[Dict[str, str]] = []     # in-workbook hyperlinks: ref, location, display
        self.comments: Dict[int, str] = {}        # rc -> cell comment
        self.images: List[Dict[str, Any]] = []    # pictures on the sheet (base64) with their anchor cells

    def col_hidden(self, col: int) -> bool:
        for a, b in self.hidden_cols:
            if a <= col <= b:
                return True
        return False

    def row_hidden(self, row: int) -> bool:
        for a, b in self.hidden_rows:
            if a <= row <= b:
                return True
        return False


class Model(object):
    def __init__(self):
        self.sheets: List[Sheet] = []
        self.sheet_index: Dict[str, int] = {}
        self.templates: List[str] = []
        self.names: Dict[str, str] = {}                    # UPPER name -> template (global)
        self.local_names: Dict[Tuple[int, str], str] = {}  # (sheet idx, UPPER name) -> template
        self.numfmts: List[str] = []                       # xf index -> number format code
        self.xf_flags: List[int] = []                      # xf index -> bit flags (1 = bold)
        self.xfs: List[List[Any]] = []                     # xf index -> [fmt, bold, font colour, fill, align, italic]
        self.dxfs: List[Dict[str, Any]] = []               # differential styles used by conditional formats
        self.date1904 = False
        self.meta: Dict[str, Any] = {}

    # ------------------------------------------------------------------ helpers
    def sheet(self, name: str) -> Sheet:
        return self.sheets[self.sheet_index[name]]

    def add_sheet(self, name: str, state: str = "visible") -> Sheet:
        sh = Sheet(name, len(self.sheets), state)
        self.sheets.append(sh)
        self.sheet_index[name] = sh.index
        return sh

    def cell_ref(self, ref: str) -> Tuple[int, int]:
        """``"Forward!D2"`` -> (sheet index, rc)."""
        sheet, _, addr = ref.rpartition("!")
        sheet = sheet.strip("'")
        return self.sheet_index[sheet], parse_a1(addr)

    def range_ref(self, ref: str) -> Tuple[int, int, int, int, int]:
        sheet, _, addr = ref.rpartition("!")
        sheet = sheet.strip("'")
        r1, c1, r2, c2 = parse_range(addr)
        return self.sheet_index[sheet], r1, c1, r2, c2

    def formula_count(self) -> int:
        return sum(len(s.fml) for s in self.sheets)

    # ------------------------------------------------------------------ (de)serialisation
    def to_json(self) -> Dict[str, Any]:
        sheets = []
        for s in self.sheets:
            sheets.append({
                "name": s.name, "state": s.state, "max_row": s.max_row, "max_col": s.max_col,
                "consts": _enc_map(s.consts),
                "fml": [list(s.fml.keys()), list(s.fml.values())],
                "arr": [[k, list(v)] for k, v in s.arr.items()],
                "members": [list(s.members.keys()), list(s.members.values())],
                "cached": _enc_map(s.cached),
                "styles": [list(s.styles.keys()), list(s.styles.values())],
                "merges": s.merges,
                "col_widths": [[k, v] for k, v in s.col_widths.items()],
                "validations": s.validations,
                "dyn": sorted(s.dyn),
                "cf": s.cf,
                "charts": s.charts,
                "hidden_rows": s.hidden_rows,
                "hidden_cols": s.hidden_cols,
                "freeze": s.freeze,
                "links": s.links,
                "comments": [[k, v] for k, v in sorted(s.comments.items())],
                "images": s.images,
            })
        return {
            "version": MODEL_VERSION,
            "meta": self.meta,
            "date1904": self.date1904,
            "templates": self.templates,
            "names": self.names,
            "local_names": [[k[0], k[1], v] for k, v in self.local_names.items()],
            "xfs": self.xfs,
            "dxfs": self.dxfs,
            "sheets": sheets,
        }

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "Model":
        if data.get("version") != MODEL_VERSION:
            raise ValueError("unsupported model version %r (expected %d) - re-import the workbook"
                             % (data.get("version"), MODEL_VERSION))
        m = cls()
        m.meta = data.get("meta", {})
        m.date1904 = bool(data.get("date1904"))
        m.templates = list(data["templates"])
        m.names = dict(data["names"])
        m.local_names = {(int(a), b): c for a, b, c in data.get("local_names", [])}
        m.xfs = [list(x) for x in data["xfs"]]
        m.dxfs = list(data.get("dxfs", []))
        m.numfmts = [x[0] for x in m.xfs]
        m.xf_flags = [x[1] for x in m.xfs]
        for sd in data["sheets"]:
            s = m.add_sheet(sd["name"], sd.get("state", "visible"))
            s.max_row = sd["max_row"]
            s.max_col = sd["max_col"]
            s.consts = _dec_map(sd["consts"])
            s.fml = dict(zip(sd["fml"][0], sd["fml"][1]))
            s.arr = {int(k): tuple(v) for k, v in sd["arr"]}
            s.members = dict(zip(sd["members"][0], sd["members"][1]))
            s.cached = _dec_map(sd["cached"])
            s.styles = dict(zip(sd["styles"][0], sd["styles"][1]))
            s.merges = list(sd.get("merges", []))
            s.col_widths = {int(k): v for k, v in sd.get("col_widths", [])}
            s.validations = list(sd.get("validations", []))
            s.dyn = set(sd.get("dyn", []))
            s.cf = list(sd.get("cf", []))
            s.charts = list(sd.get("charts", []))
            s.hidden_rows = [list(x) for x in sd.get("hidden_rows", [])]
            s.hidden_cols = [list(x) for x in sd.get("hidden_cols", [])]
            s.freeze = list(sd.get("freeze", [0, 0]))
            s.links = list(sd.get("links", []))
            s.comments = {int(k): v for k, v in sd.get("comments", [])}
            s.images = list(sd.get("images", []))
        return m

    def save(self, path: str) -> None:
        raw = json.dumps(self.to_json(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # mtime=0 keeps the archive byte-identical for identical input (stable git diffs)
        with open(path, "wb") as fh:
            with gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) as gz:
                gz.write(raw)

    @classmethod
    def load(cls, path: str) -> "Model":
        with gzip.open(path, "rb") as fh:
            data = json.load(io.TextIOWrapper(fh, encoding="utf-8"))
        return cls.from_json(data)


def _enc_val(v: Any) -> Any:
    if type(v) is XlError:
        return {"e": v.code}
    return v


def _dec_val(v: Any) -> Any:
    if type(v) is dict:
        return XlError(v["e"])
    if type(v) is int and type(v) is not bool:
        return float(v)
    return v


def _enc_map(d: Dict[int, Any]) -> List[List[Any]]:
    return [list(d.keys()), [_enc_val(v) for v in d.values()]]


def _dec_map(pair: List[List[Any]]) -> Dict[int, Any]:
    return dict(zip(pair[0], [_dec_val(v) for v in pair[1]]))
