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


_INDEXED = [
    "000000", "FFFFFF", "FF0000", "00FF00", "0000FF", "FFFF00", "FF00FF", "00FFFF", "000000", "FFFFFF", "FF0000",
    "00FF00", "0000FF", "FFFF00", "FF00FF", "00FFFF", "800000", "008000", "000080", "808000", "800080", "008080",
    "C0C0C0", "808080", "9999FF", "993366", "FFFFCC", "CCFFFF", "660066", "FF8080", "0066CC", "CCCCFF", "000080",
    "FF00FF", "FFFF00", "00FFFF", "800080", "800000", "008080", "0000FF", "00CCFF", "CCFFFF", "CCFFCC", "FFFF99",
    "99CCFF", "FF99CC", "CC99FF", "FFCC99", "3366FF", "33CCCC", "99CC00", "FFCC00", "FF9900", "FF6600", "666699",
    "969696", "003366", "339966", "003300", "333300", "993300", "993366", "333399", "333333",
]
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _theme_colors(zf: zipfile.ZipFile) -> List[str]:
    """Theme palette in the order Excel indexes it (lt1, dk1, lt2, dk2, accent1..6, hlink, folHlink)."""
    default = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
               "0563C1", "954F72"]
    try:
        root = ET.fromstring(zf.read("xl/theme/theme1.xml"))
    except KeyError:
        return default
    scheme = root.find(".//" + NS_A + "clrScheme")
    if scheme is None:
        return default
    vals: Dict[str, str] = {}
    for el in scheme:
        tag = el.tag.replace(NS_A, "")
        for ch in el:
            v = ch.get("lastClr") or ch.get("val")
            if v:
                vals[tag] = v.upper()
    order = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink",
             "folHlink"]
    return [vals.get(k, d) for k, d in zip(order, default)]


def _tint(hex6: str, tint: float) -> str:
    import colorsys
    r, g, b = (int(hex6[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    if tint < 0:
        l = l * (1.0 + tint)
    else:
        l = l * (1.0 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), sat)
    return "%02X%02X%02X" % (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def _color(el, theme: List[str]) -> Optional[str]:
    if el is None:
        return None
    rgb = el.get("rgb")
    if rgb:
        return rgb[-6:].upper()
    th = el.get("theme")
    if th is not None:
        idx = int(th)
        base = theme[idx] if idx < len(theme) else "000000"
        t = el.get("tint")
        return _tint(base, float(t)) if t else base
    ix = el.get("indexed")
    if ix is not None:
        i = int(ix)
        if i < len(_INDEXED):
            return _INDEXED[i]
    return None


def _font(el, theme) -> Tuple[bool, Optional[str], bool]:
    if el is None:
        return False, None, False
    b = el.find(NS_MAIN + "b")
    i = el.find(NS_MAIN + "i")
    bold = b is not None and b.get("val", "1") not in ("0", "false")
    ital = i is not None and i.get("val", "1") not in ("0", "false")
    return bold, _color(el.find(NS_MAIN + "color"), theme), ital


def _fill(el, theme, dxf: bool = False) -> Optional[str]:
    if el is None:
        return None
    pf = el.find(NS_MAIN + "patternFill")
    if pf is None:
        return None
    if dxf:
        # differential formats (conditional formatting): no patternType means solid, colour is in bgColor
        if pf.get("patternType") == "none":
            return None
        return _color(pf.find(NS_MAIN + "bgColor"), theme) or _color(pf.find(NS_MAIN + "fgColor"), theme)
    if pf.get("patternType") in (None, "none"):
        return None
    return _color(pf.find(NS_MAIN + "fgColor"), theme) or _color(pf.find(NS_MAIN + "bgColor"), theme)


def _styles(zf: zipfile.ZipFile):
    """-> (xfs, dxfs): xfs[i] = [numFmt, bold, font colour, fill colour, h-align, italic]."""
    theme = _theme_colors(zf)
    try:
        root = ET.fromstring(zf.read("xl/styles.xml"))
    except KeyError:
        return [["General", 0, None, None, None, 0]], []
    custom: Dict[int, str] = {}
    nf = root.find(NS_MAIN + "numFmts")
    if nf is not None:
        for el in nf:
            custom[int(el.get("numFmtId"))] = el.get("formatCode") or "General"
    fonts = [_font(f, theme) for f in (root.find(NS_MAIN + "fonts") or [])]
    fills = [_fill(f, theme) for f in (root.find(NS_MAIN + "fills") or [])]
    xfs: List[List[Any]] = []
    cx = root.find(NS_MAIN + "cellXfs")
    if cx is not None:
        for xf in cx:
            fid = int(xf.get("numFmtId", "0"))
            fmt = custom.get(fid) or BUILTIN_NUMFMTS.get(fid, "General")
            fi = int(xf.get("fontId", "0"))
            bold, fcol, ital = fonts[fi] if fi < len(fonts) else (False, None, False)
            li = int(xf.get("fillId", "0"))
            fill = fills[li] if li < len(fills) else None
            al = xf.find(NS_MAIN + "alignment")
            xfs.append([fmt, 1 if bold else 0, fcol, fill, al.get("horizontal") if al is not None else None,
                        1 if ital else 0])
    if not xfs:
        xfs = [["General", 0, None, None, None, 0]]
    dxfs: List[Dict[str, Any]] = []
    dx = root.find(NS_MAIN + "dxfs")
    if dx is not None:
        for d in dx:
            bold, fcol, ital = _font(d.find(NS_MAIN + "font"), theme)
            dxfs.append({"color": fcol, "fill": _fill(d.find(NS_MAIN + "fill"), theme, dxf=True), "bold": bold})
    return xfs, dxfs


NS_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
NS_XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"


def _rels(zf: zipfile.ZipFile, part: str) -> Dict[str, str]:
    """Relationship id -> absolute part name for ``part``."""
    folder, _, name = part.rpartition("/")
    rel_path = "%s/_rels/%s.rels" % (folder, name)
    try:
        root = ET.fromstring(zf.read(rel_path))
    except KeyError:
        return {}
    out = {}
    for r in root.iter(NS_PKG + "Relationship"):
        target = r.get("Target") or ""
        if target.startswith("/"):
            path = target[1:]
        else:
            parts = (folder + "/" + target).split("/")
            stack: List[str] = []
            for p in parts:
                if p == "..":
                    if stack:
                        stack.pop()
                elif p and p != ".":
                    stack.append(p)
            path = "/".join(stack)
        out[r.get("Id")] = path
    return out


def _chart(zf: zipfile.ZipFile, part: str) -> Optional[Dict[str, Any]]:
    try:
        root = ET.fromstring(zf.read(part))
    except KeyError:
        return None
    plot = root.find(".//" + NS_C + "plotArea")
    if plot is None:
        return None

    def text_of(el) -> str:
        if el is None:
            return ""
        return "".join(t.text or "" for t in el.iter(NS_A + "t")).strip()

    title = text_of(root.find(NS_C + "chart/" + NS_C + "title"))
    series = []
    kinds = []
    for grp in plot:
        tag = grp.tag.replace(NS_C, "")
        if not tag.endswith("Chart"):
            continue
        kind = {"lineChart": "line", "barChart": "bar", "areaChart": "area", "scatterChart": "scatter",
                "pieChart": "pie"}.get(tag, "line")
        grouping = grp.find(NS_C + "grouping")
        stacked = grouping is not None and grouping.get("val") in ("stacked", "percentStacked")
        kinds.append(kind)
        for ser in grp.findall(NS_C + "ser"):
            def ref(path):
                el = ser.find(path)
                return el.text if el is not None else None
            name_ref = ref(NS_C + "tx/" + NS_C + "strRef/" + NS_C + "f")
            name_lit = ser.find(NS_C + "tx/" + NS_C + "v")
            cat = ref(NS_C + "cat/" + NS_C + "strRef/" + NS_C + "f") or ref(NS_C + "cat/" + NS_C + "numRef/" + NS_C + "f") \
                or ref(NS_C + "xVal/" + NS_C + "numRef/" + NS_C + "f") or ref(NS_C + "xVal/" + NS_C + "strRef/" + NS_C + "f")
            val = ref(NS_C + "val/" + NS_C + "numRef/" + NS_C + "f") or ref(NS_C + "yVal/" + NS_C + "numRef/" + NS_C + "f")
            if val is None:
                continue
            entry = {"name_ref": name_ref, "name": name_lit.text if name_lit is not None else None,
                     "cat": cat, "val": val, "kind": kind, "stacked": stacked}
            sp = ser.find(NS_C + "spPr")
            if sp is not None:
                ln = sp.find(NS_A + "ln")
                clr = None
                if ln is not None:
                    if ln.find(NS_A + "noFill") is not None:
                        entry["noline"] = True
                    clr = ln.find(NS_A + "solidFill/" + NS_A + "srgbClr")
                    dash = ln.find(NS_A + "prstDash")
                    if dash is not None and dash.get("val") not in (None, "solid"):
                        entry["dash"] = True
                if clr is None:
                    clr = sp.find(NS_A + "solidFill/" + NS_A + "srgbClr")
                if clr is not None and clr.get("val"):
                    entry["color"] = clr.get("val").upper()
            series.append(entry)
    axes = [text_of(ax.find(NS_C + "title")) for ax in plot if ax.tag in (NS_C + "catAx", NS_C + "valAx", NS_C + "dateAx")]
    out = {"title": title, "kind": kinds[0] if kinds else "line", "series": series,
           "axis_titles": [a for a in axes if a]}
    val_ax = plot.find(NS_C + "valAx")
    if val_ax is not None:
        for key in ("min", "max"):
            el = val_ax.find(NS_C + "scaling/" + NS_C + key)
            if el is not None and el.get("val") is not None:
                try:
                    out["y" + key] = float(el.get("val"))
                except ValueError:
                    pass
        nf = val_ax.find(NS_C + "numFmt")
        if nf is not None and nf.get("formatCode"):
            out["value_format"] = nf.get("formatCode")
    return out


def _sheet_charts(zf: zipfile.ZipFile, sheet_part: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rid, target in _rels(zf, sheet_part).items():
        if "/drawings/drawing" not in target:
            continue
        try:
            root = ET.fromstring(zf.read(target))
        except KeyError:
            continue
        drels = _rels(zf, target)
        for anchor in root:
            frm = anchor.find(NS_XDR + "from")
            to = anchor.find(NS_XDR + "to")
            cref = None
            for el in anchor.iter(NS_C + "chart"):
                cref = el.get(NS_REL + "id")
            if cref is None or cref not in drels or frm is None:
                continue
            ch = _chart(zf, drels[cref])
            if ch is None:
                continue
            ch["anchor"] = [int(frm.find(NS_XDR + "row").text) + 1, int(frm.find(NS_XDR + "col").text) + 1,
                            (int(to.find(NS_XDR + "row").text) + 1) if to is not None else 0,
                            (int(to.find(NS_XDR + "col").text) + 1) if to is not None else 0]
            out.append(ch)
    out.sort(key=lambda c: (c["anchor"][0], c["anchor"][1]))
    return out


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
        model.xfs, model.dxfs = _styles(zf)
        model.numfmts = [x[0] for x in model.xfs]
        model.xf_flags = [x[1] for x in model.xfs]
        sheet_defs, names, model.date1904 = _workbook(zf)
        for name, state, part in sheet_defs:
            sh = model.add_sheet(name, state)
            _read_sheet(zf, part, sh, sst, intern, problems)
            try:
                sh.charts = _sheet_charts(zf, part)
            except Exception as exc:  # noqa: BLE001 - charts are decoration, never block an import
                problems.append("%s: charts not imported (%s)" % (name, exc))

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
            elif tag == NS_MAIN + "conditionalFormatting":
                sqref = el.get("sqref") or ""
                first = sqref.split()[0].split(":")[0] if sqref else "A1"
                arc = _rc(first.replace("$", ""))
                ar, ac = divmod(arc, COLS)
                for rule in el.findall(NS_MAIN + "cfRule"):
                    entry: Dict[str, Any] = {
                        "sqref": sqref, "type": rule.get("type"), "op": rule.get("operator"),
                        "priority": int(rule.get("priority", "0")), "dxf": rule.get("dxfId"),
                        "text": rule.get("text"), "anchor": arc, "formulas": [], "stop": rule.get("stopIfTrue") == "1",
                    }
                    for fe in rule.findall(NS_MAIN + "formula"):
                        try:
                            entry["formulas"].append(to_template(fe.text or "", ar, ac))
                        except FormulaSyntaxError as exc:
                            problems.append("%s CF %s: %s" % (sh.name, sqref, exc))
                    cs = rule.find(NS_MAIN + "colorScale")
                    if cs is not None:
                        entry["scale"] = {
                            "cfvo": [[v.get("type"), v.get("val")] for v in cs.findall(NS_MAIN + "cfvo")],
                            "colors": [(c.get("rgb") or "FFFFFF")[-6:] for c in cs.findall(NS_MAIN + "color")],
                        }
                    if entry["dxf"] is not None:
                        entry["dxf"] = int(entry["dxf"])
                    sh.cf.append(entry)
                el.clear()
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
