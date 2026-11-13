"""A small .xlsx writer (values and basic formats only, standard library only).

Used for the end-of-day blotter archive: what the workbook's ``GunSonuArsivle`` macro saved as
``Blotter_yyyy.mm.dd.xlsx`` - the sheet as values, without formulas.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from .xl.errors import XlError
from .xl.tokenizer import index_to_col

_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_BAD_NAME = re.compile(r"[\[\]:*?/\\]")


def _text(s: str) -> str:
    return escape(_BAD_XML.sub("", s))


class XlsxSheet(object):
    def __init__(self, book: "XlsxBook", name: str):
        self.book = book
        self.name = name
        self.cells: Dict[Tuple[int, int], Tuple[Any, int]] = {}
        self.widths: Dict[int, float] = {}
        self.merges: List[str] = []
        self.freeze: Tuple[int, int] = (0, 0)        # rows, columns

    def set(self, row: int, col: int, value: Any, fmt: Optional[str] = None, bold: bool = False,
            align: Optional[str] = None, fill: Optional[str] = None) -> None:
        """Put a value (number, text, bool, XlError or None) at 1-based ``row`` / ``col``."""
        style = self.book.style(fmt, bold, align, fill)
        if value is None and style == 0:
            return
        self.cells[(row, col)] = (value, style)

    def row(self, row: int, col: int, values: List[Any], **style) -> None:
        for k, v in enumerate(values):
            self.set(row, col + k, v, **style)

    def autosize(self, lo: float = 6.0, hi: float = 48.0) -> None:
        """Column widths from the longest text in each column (unless a width was given)."""
        longest: Dict[int, int] = {}
        spanned = set()
        for m in self.merges:
            a, _, b = m.partition(":")
            if b:
                spanned.add(a)
        for (r, c), (v, _) in self.cells.items():
            if "%s%d" % (index_to_col(c), r) in spanned:
                continue
            if isinstance(v, float):
                n = len("%.4f" % v) if v != int(v) else len("{:,}".format(int(v)))
            else:
                n = len(str(v)) if v is not None else 0
            if n > longest.get(c, 0):
                longest[c] = n
        for c, n in longest.items():
            self.widths.setdefault(c, max(lo, min(hi, n * 1.15 + 2)))

    def xml(self) -> str:
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        rows, cols = self.freeze
        if rows or cols:
            top_left = "%s%d" % (index_to_col(cols + 1), rows + 1)
            pane = '<pane%s%s topLeftCell="%s" activePane="%s" state="frozen"/>' % (
                ' xSplit="%d"' % cols if cols else "", ' ySplit="%d"' % rows if rows else "", top_left,
                "bottomRight" if rows and cols else ("bottomLeft" if rows else "topRight"))
            out.append('<sheetViews><sheetView workbookViewId="0">%s</sheetView></sheetViews>' % pane)
        if self.widths:
            out.append("<cols>")
            for c in sorted(self.widths):
                out.append('<col min="%d" max="%d" width="%.2f" customWidth="1"/>' % (c, c, self.widths[c]))
            out.append("</cols>")
        out.append("<sheetData>")
        by_row: Dict[int, List[Tuple[int, Any, int]]] = {}
        for (r, c), (v, s) in self.cells.items():
            by_row.setdefault(r, []).append((c, v, s))
        for r in sorted(by_row):
            out.append('<row r="%d">' % r)
            for c, v, s in sorted(by_row[r], key=lambda x: x[0]):
                ref = "%s%d" % (index_to_col(c), r)
                st = ' s="%d"' % s if s else ""
                if v is None:
                    out.append('<c r="%s"%s/>' % (ref, st))
                elif isinstance(v, bool):
                    out.append('<c r="%s"%s t="b"><v>%d</v></c>' % (ref, st, 1 if v else 0))
                elif isinstance(v, (int, float)):
                    f = float(v)
                    if f != f or f in (float("inf"), float("-inf")):
                        out.append('<c r="%s"%s t="e"><v>#NUM!</v></c>' % (ref, st))
                    else:
                        out.append('<c r="%s"%s><v>%s</v></c>' % (ref, st, repr(f) if f != int(f) or abs(f) >= 1e15 else str(int(f))))
                elif isinstance(v, XlError):
                    out.append('<c r="%s"%s t="e"><v>%s</v></c>' % (ref, st, _text(v.code)))
                else:
                    out.append('<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, st, _text(str(v))))
            out.append("</row>")
        out.append("</sheetData>")
        if self.merges:
            out.append('<mergeCells count="%d">' % len(self.merges))
            out.extend('<mergeCell ref="%s"/>' % m for m in self.merges)
            out.append("</mergeCells>")
        out.append("</worksheet>")
        return "".join(out)


class XlsxBook(object):
    def __init__(self):
        self.sheets: List[XlsxSheet] = []
        self._styles: Dict[Tuple[Any, ...], int] = {(None, False, None, None): 0}
        self._order: List[Tuple[Any, ...]] = [(None, False, None, None)]

    def style(self, fmt: Optional[str], bold: bool, align: Optional[str], fill: Optional[str]) -> int:
        if fmt in ("General", ""):
            fmt = None
        key = (fmt, bool(bold), align, fill.upper() if fill else None)
        i = self._styles.get(key)
        if i is None:
            i = len(self._order)
            self._styles[key] = i
            self._order.append(key)
        return i

    def add_sheet(self, name: str) -> XlsxSheet:
        clean = _BAD_NAME.sub(" ", name).strip()[:31] or "Sayfa%d" % (len(self.sheets) + 1)
        # Excel compares sheet names without regard to case - the Turkish dotted / dotless i included
        fold = lambda t: t.casefold().replace("\u0307", "").replace("ı", "i")           # noqa: E731
        taken = {fold(s.name) for s in self.sheets}
        base, n = clean, 2
        while fold(clean) in taken:
            clean = "%s (%d)" % (base[:27], n)
            n += 1
        sh = XlsxSheet(self, clean)
        self.sheets.append(sh)
        return sh

    def _styles_xml(self) -> str:
        fmts: Dict[str, int] = {}
        fills: Dict[str, int] = {}
        xfs = []
        for fmt, bold, align, fill in self._order:
            fmt_id = 0
            if fmt:
                fmt_id = fmts.setdefault(fmt, 164 + len(fmts))
            fill_id = 0
            if fill:
                fill_id = fills.setdefault(fill, 2 + len(fills))
            attrs = 'numFmtId="%d" fontId="%d" fillId="%d" borderId="0" xfId="0"' % (fmt_id, 1 if bold else 0, fill_id)
            if fmt_id:
                attrs += ' applyNumberFormat="1"'
            if bold:
                attrs += ' applyFont="1"'
            if fill_id:
                attrs += ' applyFill="1"'
            if align in ("left", "center", "right"):
                xfs.append('<xf %s applyAlignment="1"><alignment horizontal="%s"/></xf>' % (attrs, align))
            else:
                xfs.append("<xf %s/>" % attrs)
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        if fmts:
            out.append('<numFmts count="%d">' % len(fmts))
            for code, i in sorted(fmts.items(), key=lambda kv: kv[1]):
                out.append('<numFmt numFmtId="%d" formatCode="%s"/>' % (i, _text(code).replace('"', "&quot;")))
            out.append("</numFmts>")
        out.append('<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>')
        out.append('<fills count="%d"><fill><patternFill patternType="none"/></fill>'
                   '<fill><patternFill patternType="gray125"/></fill>' % (2 + len(fills)))
        for rgb, _ in sorted(fills.items(), key=lambda kv: kv[1]):
            out.append('<fill><patternFill patternType="solid"><fgColor rgb="FF%s"/><bgColor indexed="64"/></patternFill></fill>' % rgb)
        out.append("</fills>")
        out.append('<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>')
        out.append('<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>')
        out.append('<cellXfs count="%d">%s</cellXfs>' % (len(xfs), "".join(xfs)))
        out.append('<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>')
        out.append("</styleSheet>")
        return "".join(out)

    def to_bytes(self) -> bytes:
        if not self.sheets:
            self.add_sheet("Sayfa1")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            overrides = "".join(
                '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(len(self.sheets)))
            zf.writestr("[Content_Types].xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                        '<Default Extension="xml" ContentType="application/xml"/>'
                        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                        'spreadsheetml.sheet.main+xml"/>'
                        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                        'spreadsheetml.styles+xml"/>%s</Types>' % overrides)
            zf.writestr("_rels/.rels",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                        'officeDocument" Target="xl/workbook.xml"/></Relationships>')
            sheets_xml = "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (_text(s.name).replace('"', "&quot;"), i + 1, i + 1)
                                 for i, s in enumerate(self.sheets))
            zf.writestr("xl/workbook.xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                        '<sheets>%s</sheets></workbook>' % sheets_xml)
            rels = "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                           'worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(self.sheets)))
            rels += ('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                     'styles" Target="styles.xml"/>' % (len(self.sheets) + 1))
            zf.writestr("xl/_rels/workbook.xml.rels",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % rels)
            zf.writestr("xl/styles.xml", self._styles_xml())
            for i, s in enumerate(self.sheets):
                zf.writestr("xl/worksheets/sheet%d.xml" % (i + 1), s.xml())
        return buf.getvalue()
