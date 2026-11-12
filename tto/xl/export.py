"""Write a workbook model (optionally with frozen values) back to a plain ``.xlsx`` file.

Two uses:

* ``tools/lo_reference.py`` exports the model with all Bloomberg cells frozen and lets LibreOffice
  recalculate it - an independent reference for cells Excel never calculated;
* the dashboard can hand out the current state of any sheet as a workbook.
"""
from __future__ import annotations

import zipfile
from typing import Any, Dict, Optional, Tuple
from xml.sax.saxutils import escape

from .errors import XlError
from .model import COLS, Model, a1
from .tokenizer import index_to_col
from .unparse import to_a1

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
%s</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _cell_xml(addr: str, v: Any) -> str:
    t = type(v)
    if t is float or t is int:
        return '<c r="%s"><v>%r</v></c>' % (addr, float(v))
    if t is bool:
        return '<c r="%s" t="b"><v>%d</v></c>' % (addr, 1 if v else 0)
    if t is XlError:
        return '<c r="%s" t="e"><v>%s</v></c>' % (addr, escape(v.code))
    if t is str:
        return '<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (addr, _xml_text(v))
    return ""


def _xml_text(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if o < 32 and ch not in "\t\n\r":
            continue
        out.append(ch)
    return escape("".join(out))


def export_xlsx(model: Model, path: str, pins: Optional[Dict[Tuple[int, int], Any]] = None,
                values: Optional[Dict[Tuple[int, int], Any]] = None, formulas: bool = True,
                today: Optional[float] = None, now: Optional[float] = None,
                portable: bool = False) -> None:
    """Write ``model`` to ``path``.

    ``pins``      cells written as constants instead of their formula
    ``values``    when ``formulas`` is False: the value of every formula cell (a values-only snapshot)
    ``portable``  rewrite constructs unknown to older spreadsheet programs (LET inlined, @ removed,
                  TODAY()/NOW() replaced by ``today`` / ``now``)
    """
    pins = pins or {}
    opts = dict(xlfn=True)
    if portable:
        opts.update(inline_let=True, strip_single=True, today=today, now=now)
    sheet_xml = []
    for s in model.sheets:
        si = s.index
        rows: Dict[int, Dict[int, str]] = {}
        for rc, v in s.consts.items():
            r, c = divmod(rc, COLS)
            rows.setdefault(r, {})[c] = _cell_xml(a1(rc), pins.get((si, rc), v))
        for rc, tid in s.fml.items():
            r, c = divmod(rc, COLS)
            addr = a1(rc)
            if (si, rc) in pins:
                rows.setdefault(r, {})[c] = _cell_xml(addr, pins[(si, rc)])
                continue
            if not formulas:
                if values is not None and (si, rc) in values:
                    rows.setdefault(r, {})[c] = _cell_xml(addr, values[(si, rc)])
                continue
            text = escape(to_a1(model.templates[tid], r, c, **opts))
            ref = s.arr.get(rc)
            if ref is not None:
                rng = "%s%d:%s%d" % (index_to_col(ref[1]), ref[0], index_to_col(ref[3]), ref[2])
                rows.setdefault(r, {})[c] = '<c r="%s"><f t="array" ref="%s">%s</f></c>' % (addr, rng, text)
            else:
                rows.setdefault(r, {})[c] = '<c r="%s"><f>%s</f></c>' % (addr, text)
        for rc in s.members:
            key = (si, rc)
            src = pins if key in pins else (values if (values is not None and not formulas) else None)
            if src is not None and key in src:
                r, c = divmod(rc, COLS)
                rows.setdefault(r, {})[c] = _cell_xml(a1(rc), src[key])
        parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for r in sorted(rows):
            cells = rows[r]
            parts.append('<row r="%d">%s</row>' % (r, "".join(cells[c] for c in sorted(cells))))
        parts.append("</sheetData></worksheet>")
        sheet_xml.append("".join(parts))

    names = []
    for name, tpl in model.names.items():
        try:
            names.append('<definedName name="%s">%s</definedName>' % (escape(name), escape(to_a1(tpl, 1, 1))))
        except Exception:  # noqa: BLE001 - a broken name must not block the export
            continue
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    overrides = []
    for i, s in enumerate(model.sheets, 1):
        wb.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(s.name, {'"': "&quot;"}), i, i))
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i))
        overrides.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-'
                         'officedocument.spreadsheetml.worksheet+xml"/>\n' % i)
    wb.append("</sheets>")
    if names:
        wb.append("<definedNames>%s</definedNames>" % "".join(names))
    wb.append('<calcPr fullCalcOnLoad="1"/></workbook>')
    rels.append("</Relationships>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CT % "".join(overrides))
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("xl/workbook.xml", "".join(wb))
        zf.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        for i, xml in enumerate(sheet_xml, 1):
            zf.writestr("xl/worksheets/sheet%d.xml" % i, xml)
