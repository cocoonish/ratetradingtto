"""Turn workbook ranges into display data (text as Excel formats it, raw values, colours, input flags)."""
from __future__ import annotations

import colorsys
from typing import Any, Dict, List, Optional, Tuple

from .books import Book
from .xl import numfmt
from .xl.errors import XlError
from .xl.model import COLS, a1, parse_range
from .xl.tokenizer import index_to_col
from .xl.values import compare, to_bool

# fills the workbook uses for cells the trader types into
INPUT_FILLS = {"FFF2CC", "FFCC99", "FFFF00", "FCD5B5", "FAC090", "FFC000", "FFE699", "FFEB9C"}
HEADER_FILLS = {"1F3864", "1F497D", "215968", "17375E", "203764", "305496", "0F243E", "244062"}


def tone(hex6: Optional[str]) -> Optional[str]:
    """Map a workbook font colour to a semantic tone the UI themes itself (neg / pos / info / warn / mute)."""
    if not hex6:
        return None
    try:
        r, g, b = (int(hex6[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.18:
        if 0.35 < l < 0.75:
            return "mute"
        return None
    deg = h * 360.0
    if deg < 20 or deg >= 335:
        return "neg"
    if deg < 50:
        return "warn"
    if deg < 75:
        return "warn"
    if deg < 170:
        return "pos"
    if deg < 265:
        return "info"
    return "accent"


def fill_tone(hex6: Optional[str]) -> Optional[str]:
    if not hex6:
        return None
    h = hex6.upper()
    if h in INPUT_FILLS:
        return "in"
    if h in HEADER_FILLS:
        return "hd"
    if h in ("FFFFFF", "000000"):
        return None
    try:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return None
    hh, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.12:
        return "sub" if l < 0.93 else None
    deg = hh * 360.0
    if l < 0.45:
        return "hd"
    if deg < 20 or deg >= 335:
        return "bad"
    if deg < 70:
        return "note"
    if deg < 170:
        return "good"
    if deg < 265:
        return "sub"
    return "sub"


class _CfIndex(object):
    """Conditional-format rules of one sheet, searchable by cell."""

    def __init__(self, book: Book, si: int):
        self.book = book
        self.si = si
        self.rules: List[Tuple[List[Tuple[int, int, int, int]], Dict[str, Any], List[Any]]] = []
        sheet = book.model.sheets[si]
        for rule in sorted(sheet.cf, key=lambda r: r.get("priority", 0)):
            ranges = []
            for part in (rule.get("sqref") or "").split():
                try:
                    ranges.append(parse_range(part))
                except Exception:  # noqa: BLE001
                    continue
            fns = []
            for tpl in rule.get("formulas", []):
                try:
                    fns.append(book.engine.compiler.compile_expression(tpl, False))
                except Exception:  # noqa: BLE001
                    fns.append(None)
            self.rules.append((ranges, rule, fns))
        self._scale_stats: Dict[int, Tuple[float, float]] = {}

    def applicable(self, r1: int, c1: int, r2: int, c2: int):
        out = []
        for i, (ranges, rule, fns) in enumerate(self.rules):
            for (a, b, c, d) in ranges:
                if a <= r2 and c >= r1 and b <= c2 and d >= c1:
                    out.append(i)
                    break
        return out

    def evaluate(self, idx: int, calc, r: int, c: int, value: Any, cache: Dict[int, Any]) -> Optional[Dict[str, Any]]:
        ranges, rule, fns = self.rules[idx]
        if not any(a <= r <= cc and b <= c <= d for (a, b, cc, d) in ranges):
            return None
        kind = rule.get("type")
        dxfs = self.book.model.dxfs
        style = dxfs[rule["dxf"]] if rule.get("dxf") is not None and rule["dxf"] < len(dxfs) else {}
        try:
            if kind == "expression":
                if not fns or fns[0] is None:
                    return None
                res = to_bool(calc_value(calc, fns[0], self.si, r, c))
                return style if res is True else None
            if kind == "cellIs":
                if type(value) is not float or not fns or fns[0] is None:
                    return None
                x = calc_value(calc, fns[0], self.si, r, c)
                cmp = compare(value, x)
                if type(cmp) is XlError:
                    return None
                op = rule.get("op")
                if op == "between" and len(fns) > 1 and fns[1] is not None:
                    y = calc_value(calc, fns[1], self.si, r, c)
                    c2 = compare(value, y)
                    ok = type(c2) is not XlError and cmp >= 0 and c2 <= 0
                else:
                    ok = {"lessThan": cmp < 0, "lessThanOrEqual": cmp <= 0, "greaterThan": cmp > 0,
                          "greaterThanOrEqual": cmp >= 0, "equal": cmp == 0, "notEqual": cmp != 0}.get(op, False)
                return style if ok else None
            if kind == "colorScale":
                if type(value) is not float:
                    return None
                sc = rule.get("scale") or {}
                colors = sc.get("colors") or []
                if len(colors) < 2:
                    return None
                stats = cache.get(idx)
                if stats is None:
                    nums = []
                    for (a, b, cc, d) in ranges:
                        for rr in range(a, cc + 1):
                            for col in range(b, d + 1):
                                v = calc.get(self.si, rr, col)
                                if type(v) is float:
                                    nums.append(v)
                    stats = (min(nums), max(nums)) if nums else (0.0, 0.0)
                    cache[idx] = stats
                lo, hi = stats
                if len(colors) == 3:
                    mid = 0.0
                    cf = sc.get("cfvo") or []
                    if len(cf) > 1 and cf[1][0] == "num" and cf[1][1] is not None:
                        try:
                            mid = float(cf[1][1])
                        except ValueError:
                            mid = (lo + hi) / 2.0
                    else:
                        mid = (lo + hi) / 2.0
                    if value <= mid:
                        t = 0.0 if mid == lo else max(0.0, min(1.0, (value - lo) / (mid - lo)))
                        return {"heat": _mix(colors[0], colors[1], t)}
                    t = 0.0 if hi == mid else max(0.0, min(1.0, (value - mid) / (hi - mid)))
                    return {"heat": _mix(colors[1], colors[2], t)}
                t = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
                return {"heat": _mix(colors[0], colors[1], t)}
        except Exception:  # noqa: BLE001 - a broken rule must never break rendering
            return None
        return None


def _mix(a: str, b: str, t: float) -> str:
    out = []
    for i in (0, 2, 4):
        x, y = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append("%02X" % int(round(x + (y - x) * t)))
    return "".join(out)


def calc_value(calc, fn, si: int, r: int, c: int) -> Any:
    """Evaluate an ad-hoc compiled formula in the context of ``calc`` for host cell (r, c)."""
    from .xl.values import intersect
    calc.depth = 0
    v = fn(calc, si, r, c)
    return intersect(v, r, c)


class Renderer(object):
    def __init__(self, book: Book):
        self.book = book
        self._cf: Dict[int, _CfIndex] = {}

    def cf(self, si: int) -> _CfIndex:
        idx = self._cf.get(si)
        if idx is None:
            idx = _CfIndex(self.book, si)
            self._cf[si] = idx
        return idx

    # ------------------------------------------------------------------ single cell
    def cell(self, calc, si: int, r: int, c: int, loc: numfmt.Locale, overlay=None, cf_rules=(), cf_cache=None,
             shared_values=None) -> Dict[str, Any]:
        book = self.book
        model = book.model
        sheet = model.sheets[si]
        rc = r * COLS + c
        try:
            v = calc.get(si, r, c)
        except Exception as exc:  # noqa: BLE001
            return {"t": "#ERR", "k": "e", "tip": "%s: %s" % (type(exc).__name__, str(exc)[:120])}
        out: Dict[str, Any] = {}
        xf_i = sheet.styles.get(rc, 0)
        xf = model.xfs[xf_i] if xf_i < len(model.xfs) else model.xfs[0]
        fmt = xf[0]
        tv = type(v)
        color = None
        if v is None:
            out["t"] = ""
            out["k"] = ""
        elif tv is float:
            text, color = numfmt.render(v, fmt, loc, general_digits=10)
            out["t"] = text.strip()
            out["v"] = v
            out["k"] = "d" if numfmt.is_date_format(fmt) else "n"
        elif tv is str:
            text, color = numfmt.render(v, fmt, loc)
            # padding added by the number format ("_-@_-") is not content
            out["t"] = text.strip() if v == v.strip() else text
            out["k"] = "s"
        elif tv is bool:
            out["t"] = "TRUE" if v else "FALSE"
            out["v"] = v
            out["k"] = "b"
        elif tv is XlError:
            out["t"] = v.code
            out["k"] = "e"
        else:
            out["t"] = str(v)
            out["k"] = "s"
        if xf[1]:
            out["b"] = 1
        if xf[5]:
            out["it"] = 1
        tn = tone(xf[2]) if not color else {"red": "neg", "green": "pos", "blue": "info"}.get(color, None)
        ft = fill_tone(xf[3])
        if xf[4] in ("center", "right", "left"):
            out["al"] = xf[4][0]
        for i in cf_rules:
            st = self.cf(si).evaluate(i, calc, r, c, v, cf_cache if cf_cache is not None else {})
            if st is None:
                continue
            if "heat" in st:
                out["heat"] = st["heat"]
                continue
            if st.get("color"):
                tn = tone(st["color"]) or tn
            if st.get("fill"):
                cft = fill_tone(st["fill"])
                if cft == "in":
                    cft = "note"                   # Excel's yellow "neutral" highlight, not an input cell
                ft = cft or ft
            if st.get("bold"):
                out["b"] = 1
        if tn:
            out["c"] = tn
        if ft:
            out["f"] = ft
        d = book.inputs.get((si, rc))
        if d is not None:
            out["i"] = "s" if d.scope == "shared" else "u"
            opts = book.options_for(si, rc)
            if opts:
                out["o"] = opts
            if overlay is not None and (si, rc) in overlay:
                out["m"] = 1                       # modified by this user
            elif shared_values is not None and rc in shared_values[si]:
                out["m"] = 2                       # shared value differs from the workbook
            if numfmt.is_percent_format(fmt):
                out["ik"] = "pct"
            elif out.get("k") == "d" or d.kind == "date":
                out["ik"] = "date"
            elif d.kind not in ("auto", ""):
                out["ik"] = d.kind
        if rc in sheet.fml:
            out["fx"] = 1
        return out

    # ------------------------------------------------------------------ ranges
    def table(self, calc, sheet: str, rng: str, loc: numfmt.Locale, overlay=None, trim: bool = True) -> Dict[str, Any]:
        book = self.book
        si = book.model.sheet_index[sheet]
        r1, c1, r2, c2 = parse_range(rng)
        cfi = self.cf(si)
        rules = cfi.applicable(r1, c1, r2, c2)
        cache: Dict[int, Any] = {}
        shared_values = book.engine.input_value
        rows = []
        for r in range(r1, r2 + 1):
            rows.append([self.cell(calc, si, r, c, loc, overlay, rules, cache, shared_values)
                         for c in range(c1, c2 + 1)])
        sh = book.model.sheets[si]
        # merged cells: mark the span on the anchor, blank the covered ones
        spans = {}
        for m in sh.merges:
            try:
                a, b, c, d = parse_range(m)
            except Exception:  # noqa: BLE001
                continue
            if a > r2 or c < r1 or b > c2 or d < c1:
                continue
            if r1 <= a <= r2 and c1 <= b <= c2:
                spans[(a, b)] = (min(c, r2) - a + 1, min(d, c2) - b + 1)
                for rr in range(a, min(c, r2) + 1):
                    for cc in range(b, min(d, c2) + 1):
                        if (rr, cc) != (a, b):
                            rows[rr - r1][cc - c1] = {"sk": 1}
        for (a, b), (rs, cs) in spans.items():
            cell = rows[a - r1][b - c1]
            if rs > 1:
                cell["rs"] = rs
            if cs > 1:
                cell["cs"] = cs
        row_nums = list(range(r1, r2 + 1))
        col_nums = list(range(c1, c2 + 1))
        if trim:
            def empty(cell):
                return (cell.get("t", "") == "" and "i" not in cell) or cell.get("sk")
            keep_r = [i for i, row in enumerate(rows) if not all(empty(c) for c in row)]
            keep_c = [j for j in range(len(col_nums)) if not all(empty(row[j]) for row in rows)]
            if keep_r and keep_c:
                # drop leading / trailing blank rows; a run of blank rows inside (they separate sub-tables)
                # shrinks to a single one
                filled = set(keep_r)
                keep_r = [i for i in range(keep_r[0], keep_r[-1] + 1) if i in filled or (i - 1) in filled]
                rows = [[rows[i][j] for j in keep_c] for i in keep_r]
                row_nums = [row_nums[i] for i in keep_r]
                col_nums = [col_nums[j] for j in keep_c]
        return {"sheet": sheet, "rows": rows, "r": row_nums, "c": [index_to_col(c) for c in col_nums]}

    def values(self, calc, sheet: str, rng: str) -> List[List[Any]]:
        si = self.book.model.sheet_index[sheet]
        r1, c1, r2, c2 = parse_range(rng)
        return calc.get_range(si, r1, c1, r2, c2)

    def chart(self, calc, chart: Dict[str, Any], loc: numfmt.Locale) -> Dict[str, Any]:
        """Resolve a chart imported from the workbook into category labels and numeric series."""
        book = self.book

        def split(ref: str) -> Tuple[str, str]:
            sheet, _, addr = ref.rpartition("!")
            return sheet.strip("'"), addr.replace("$", "")

        cats: List[str] = []
        series: List[Dict[str, Any]] = []
        slots: Dict[Any, int] = {}
        for s in chart["series"]:
            sh, addr = split(s["val"])
            vals = [v for row in self.values(calc, sh, addr) for v in row]
            name = s.get("name") or ""
            if s.get("name_ref"):
                nsh, naddr = split(s["name_ref"])
                nv = self.values(calc, nsh, naddr)
                name = str(nv[0][0]) if nv and nv[0] and nv[0][0] is not None else name
            if not cats and s.get("cat"):
                csh, caddr = split(s["cat"])
                si = book.model.sheet_index[csh]
                r1, c1, r2, c2 = parse_range(caddr)
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        cats.append(self.cell(calc, si, r, c, loc).get("t", ""))
            entry = {"name": name, "kind": s.get("kind", "line"), "stacked": bool(s.get("stacked")),
                     "data": [v if type(v) is float else None for v in vals]}
            if s.get("dash"):
                entry["dash"] = 1
            if s.get("noline"):
                entry["noline"] = 1
            # series drawn in one colour in the workbook are one entity (e.g. the two edges of a band)
            src = s.get("color")
            if src:
                if src not in slots:
                    slots[src] = len(slots)
                entry["slot"] = slots[src]
            else:
                entry["slot"] = len(slots)
                slots[("auto", len(series))] = entry["slot"]
            series.append(entry)
        if not cats and series:
            cats = [str(i + 1) for i in range(len(series[0]["data"]))]
        # drop trailing categories for which no series has data
        n = len(cats)
        while n > 0 and all(n - 1 >= len(s["data"]) or s["data"][n - 1] is None for s in series) and not cats[n - 1]:
            n -= 1
        out = {"title": chart.get("title") or "", "kind": chart.get("kind", "line"), "cats": cats[:n],
               "series": [dict(s, data=s["data"][:n]) for s in series], "axis": chart.get("axis_titles") or []}
        fmt = chart.get("value_format") or ""
        if "%" in fmt:
            out["unit"] = "pct"
        for key in ("ymin", "ymax"):
            if chart.get(key) is not None:
                out[key] = chart[key]
        return out
