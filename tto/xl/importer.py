"""Import an ``.xlsx`` / ``.xlsm`` workbook into a :class:`tto.xl.model.Model`.

Only the standard library is used (``zipfile`` + ``xml.etree``) so that importing a new version of the
workbook works on any machine.  Everything the engine and the dashboard need is extracted:

* constants, formulas (as position independent templates), array-formula ranges, dynamic-array flags
* the values Excel cached at the last save (used for parity tests and as replay market data)
* number formats / bold flags per cell, merged cells, column widths, list validations
* defined names
"""
from __future__ import annotations

import datetime as _dt
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from .errors import XlError
from .model import COLS, Model, Sheet, pack, parse_range
from .tokenizer import FormulaSyntaxError, col_to_index, to_template

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"

BUILTIN_NUMFMTS = {
    0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00",
    12: "# ?/?", 13: "# ??/??", 14: "dd.mm.yyyy", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy",
    18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "dd.mm.yyyy h:mm",
    37: "#,##0 ;(#,##0)", 38: "#,##0 ;[Red](#,##0)", 39: "#,##0.00;(#,##0.00)", 40: "#,##0.00;[Red](#,##0.00)",
    45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0", 48: "##0.0E+0", 49: "@",
}

_ADDR = re.compile(r"([A-Z]{1,3})(\d+)$")


def _rc(addr: str) -> int:
    m = _ADDR.match(addr)
    return pack(int(m.group(2)), col_to_index(m.group(1)))


def _shared_strings(zf: zipfile.ZipFile) -> List[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    out: List[str] = []
    root = ET.fromstring(raw)
    for si in root.iter(NS_MAIN + "si"):
        parts: List[str] = []
        for child in si:
            if child.tag == NS_MAIN + "t":
                parts.append(child.text or "")
            elif child.tag == NS_MAIN + "r":
                for t in child.iter(NS_MAIN + "t"):
                    parts.append(t.text or "")
        out.append("".join(parts))
    return out


def _styles(zf: zipfile.ZipFile) -> Tuple[List[str], List[int]]:
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except KeyError:
        return ["General"], [0]
    custom: Dict[int, str] = {}
    nf = root.find(NS_MAIN + "numFmts")
    if nf is not None:
        for el in nf:
            custom[int(el.get("numFmtId"))] = el.get("formatCode") or "General"
    bold_fonts: List[bool] = []
    fonts = root.find(NS_MAIN + "fonts")
    if fonts is not None:
        for f in fonts:
            b = f.find(NS_MAIN + "b")
            bold_fonts.append(b is not None and b.get("val", "1") not in ("0", "false"))
    fmts: List[str] = []
    flags: List[int] = []
    xfs = root.find(NS_MAIN + "cellXfs")
    if xfs is not None:
        for xf in xfs:
            fid = int(xf.get("numFmtId", "0"))
            fmts.append(custom.get(fid) or BUILTIN_NUMFMTS.get(fid, "General"))
            font = int(xf.get("fontId", "0"))
            flags.append(1 if font < len(bold_fonts) and bold_fonts[font] else 0)
    if not fmts:
        fmts, flags = ["General"], [0]
    return fmts, flags


def _workbook(zf: zipfile.ZipFile):
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.iter(NS_PKG + "Relationship")}
    sheets = []
    for el in root.find(NS_MAIN + "sheets"):
        rid = el.get(NS_REL + "id")
        target = targets[rid]
        path = target[1:] if target.startswith("/") else "xl/" + target
        sheets.append((el.get("name"), el.get("state", "visible"), path))
    names = []
    dn = root.find(NS_MAIN + "definedNames")
    if dn is not None:
        for el in dn:
            names.append((el.get("name"), el.get("localSheetId"), el.text or ""))
    pr = root.find(NS_MAIN + "workbookPr")
    date1904 = pr is not None and pr.get("date1904") in ("1", "true")
    return sheets, names, date1904


def _value(t: Optional[str], vtext: Optional[str], is_el, sst: List[str]) -> Any:
    """Decode a <c> cell value; returns ``None`` when there is no value at all."""
    if t == "inlineStr":
        if is_el is None:
            return ""
        return "".join(x.text or "" for x in is_el.iter(NS_MAIN + "t"))
    if vtext is None:
        return None
    if t is None or t == "n":
        return float(vtext)
    if t == "s":
        return sst[int(vtext)]
    if t == "str":
        return vtext
    if t == "b":
        return vtext in ("1", "true", "TRUE")
    if t == "e":
        return XlError(vtext)
    if t == "d":
        d = _dt.datetime.fromisoformat(vtext)
        return (d - _dt.datetime(1899, 12, 30)).total_seconds() / 86400.0
    return vtext


def import_workbook(path: str, label: Optional[str] = None) -> Model:
    """Read ``path`` and return the workbook model."""
    model = Model()
    tpl_index: Dict[str, int] = {}

    def intern(tpl: str) -> int:
        i = tpl_index.get(tpl)
        if i is None:
            i = len(model.templates)
            model.templates.append(tpl)
            tpl_index[tpl] = i
        return i

    problems: List[str] = []
    with zipfile.ZipFile(path) as zf:
        sst = _shared_strings(zf)
        model.numfmts, model.xf_flags = _styles(zf)
        sheet_defs, names, model.date1904 = _workbook(zf)
        for name, state, part in sheet_defs:
            sh = model.add_sheet(name, state)
            _read_sheet(zf, part, sh, sst, intern, problems)

    for name, local, text in names:
        text = (text or "").strip()
        if not text or name.startswith("_xlnm.") or "#REF!" in text or "#NAME?" in text:
            continue
        try:
            tpl = to_template(text, 1, 1)
        except FormulaSyntaxError as exc:
            problems.append("name %s: %s" % (name, exc))
            continue
        if local is None:
            model.names[name.upper()] = tpl
        else:
            model.local_names[(int(local), name.upper())] = tpl

    model.meta = {
        "source": label or path.replace("\\", "/").rsplit("/", 1)[-1],
        "problems": problems,
        "formulas": model.formula_count(),
        "templates": len(model.templates),
    }
    return model


def _read_sheet(zf, part: str, sh: Sheet, sst: List[str], intern, problems: List[str]) -> None:
    shared: Dict[str, int] = {}          # si -> template id
    array_refs: List[Tuple[int, Tuple[int, int, int, int]]] = []
    plain_values: Dict[int, Any] = {}
    max_row = max_col = 0
    c_tag, f_tag, v_tag, is_tag = NS_MAIN + "c", NS_MAIN + "f", NS_MAIN + "v", NS_MAIN + "is"
    row_tag = NS_MAIN + "row"
    with zf.open(part) as fh:
        for event, el in ET.iterparse(fh, events=("end",)):
            tag = el.tag
            if tag == c_tag:
                addr = el.get("r")
                rc = _rc(addr)
                row, col = divmod(rc, COLS)
                style = el.get("s")
                t = el.get("t")
                f_el = el.find(f_tag)
                v_el = el.find(v_tag)
                value = _value(t, v_el.text if v_el is not None else None, el.find(is_tag), sst)
                if t == "str" and v_el is not None and v_el.text is None:
                    value = ""
                has_content = f_el is not None or value is not None
                if has_content:
                    if row > max_row:
                        max_row = row
                    if col > max_col:
                        max_col = col
                    if style is not None and style != "0":
                        sh.styles[rc] = int(style)
                if f_el is not None:
                    ft = f_el.get("t")
                    text = f_el.text or ""
                    tid = None
                    try:
                        if ft == "shared":
                            si = f_el.get("si")
                            if text:
                                tid = intern(to_template(text, row, col))
                                shared[si] = tid
                            else:
                                tid = shared.get(si)
                                if tid is None:
                                    problems.append("%s!%s: shared formula without master" % (sh.name, addr))
                        elif ft == "dataTable":
                            problems.append("%s!%s: data table formulas are not supported" % (sh.name, addr))
                        elif not text.strip():
                            tid = None                      # an empty <f/> is not a formula
                        else:
                            tid = intern(to_template(text, row, col))
                            if ft == "array":
                                ref = parse_range(f_el.get("ref") or addr)
                                sh.arr[rc] = ref
                                if ref[0] != ref[2] or ref[1] != ref[3]:
                                    array_refs.append((rc, ref))
                                if el.get("cm"):
                                    sh.dyn.add(rc)
                    except FormulaSyntaxError as exc:
                        problems.append("%s!%s: %s" % (sh.name, addr, exc))
                    if tid is not None:
                        sh.fml[rc] = tid
                        if value is not None:
                            sh.cached[rc] = value
                    elif value is not None:
                        sh.consts[rc] = value
                elif value is not None:
                    plain_values[rc] = value
                el.clear()
            elif tag == row_tag:
                el.clear()
            elif tag == NS_MAIN + "mergeCell":
                sh.merges.append(el.get("ref"))
            elif tag == NS_MAIN + "col":
                w = el.get("width")
                if w is not None:
                    for c in range(int(el.get("min")), min(int(el.get("max")), 400) + 1):
                        sh.col_widths[c] = float(w)
            elif tag == NS_MAIN + "dataValidation":
                f1 = el.find(NS_MAIN + "formula1")
                sh.validations.append({
                    "sqref": el.get("sqref"), "type": el.get("type"),
                    "formula1": f1.text if f1 is not None else None,
                })
    # cells that only hold a value but sit inside a multi-cell array formula are array members
    for anchor, (r1, c1, r2, c2) in array_refs:
        for r in range(r1, r2 + 1):
            base = r * COLS
            for c in range(c1, c2 + 1):
                rc = base + c
                if rc == anchor:
                    continue
                sh.members[rc] = anchor
                if rc in plain_values:
                    sh.cached[rc] = plain_values.pop(rc)
    sh.consts.update(plain_values)
    sh.max_row, sh.max_col = max_row, max_col
