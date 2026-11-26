"""Turn workbook ranges into display data (text as Excel formats it, raw values, colours, input flags)."""
from __future__ import annotations

import colorsys
from typing import Any, Dict, List, Optional, Tuple

from . import twoway
from .books import Book
from .xl import numfmt
from .xl.errors import E_NUM, XlError
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

    def _numbers(self, calc, ranges) -> List[float]:
        nums = []
        for (a, b, cc, d) in ranges:
            for rr in range(a, cc + 1):
                for col in range(b, d + 1):
                    v = calc.get(self.si, rr, col)
                    if type(v) is float:
                        nums.append(v)
        return nums

    @staticmethod
    def _cfvo(cfvo, i: int, nums: List[float], calc, r: int, c: int) -> float:
        """Threshold ``i`` (0 = low end, 1 = high end) of a data bar / colour scale."""
        kind, val = (cfvo[i] if cfvo and i < len(cfvo) else (("min", "max")[i], None))
        try:
            x = float(val) if val is not None else None
        except (TypeError, ValueError):
            x = None
        if not nums:
            return x if x is not None else 0.0
        lo, hi = min(nums), max(nums)
        if kind in ("num", "formula") and x is not None:
            return x
        if kind == "percent" and x is not None:
            return lo + (hi - lo) * x / 100.0
        if kind == "percentile" and x is not None:
            ordered = sorted(nums)
            pos = (len(ordered) - 1) * x / 100.0
            k = int(pos)
            return ordered[k] + (ordered[min(k + 1, len(ordered) - 1)] - ordered[k]) * (pos - k)
        if kind in ("max", "autoMax"):
            return hi
        if kind in ("min", "autoMin"):
            return lo
        return lo if i == 0 else hi

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
            if kind == "dataBar":
                bar = rule.get("bar") or {}
                if type(value) is not float:
                    return None
                stats = cache.get(idx)
                if stats is None:
                    nums = self._numbers(calc, ranges)
                    stats = (self._cfvo(bar.get("cfvo"), 0, nums, calc, r, c), self._cfvo(bar.get("cfvo"), 1, nums, calc, r, c))
                    cache[idx] = stats
                lo, hi = stats
                t = 0.0 if hi <= lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
                # Excel draws the shortest bar at `min` % and the longest at `max` % of the cell width
                a, b = float(bar.get("min", 10)), float(bar.get("max", 90))
                return {"bar": round(a + (b - a) * t, 1), "bar_color": bar.get("color")}
            if kind == "colorScale":
                if type(value) is not float:
                    return None
                sc = rule.get("scale") or {}
                colors = sc.get("colors") or []
                if len(colors) < 2:
                    return None
                stats = cache.get(idx)
                if stats is None:
                    nums = self._numbers(calc, ranges)
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
    if calc.track is not None:
        calc.track |= calc.cm                       # (what a conditional format read counts as read by the page)
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

    def xf_of(self, si: int, rc: int) -> List[Any]:
        """A cell's look - [number format, bold, font colour, fill, alignment, italic] - as the model has it (the
        workbook's, and what the dashboard's own sheets set at the start).  The one place a cell's own format is read:
        a user's own number of decimals (tto/decimals.py) sits on top of it."""
        model = self.book.model
        xf_i = model.sheets[si].styles.get(rc, 0)
        return model.xfs[xf_i] if xf_i < len(model.xfs) else model.xfs[0]

    def format_of(self, si: int, rc: int) -> str:
        """A cell's own number format (see :meth:`xf_of`)."""
        return self.xf_of(si, rc)[0]

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
        xf = self.xf_of(si, rc)
        fmt = xf[0]
        tv = type(v)
        if tv is float and v - v != 0.0:
            v, tv = E_NUM, XlError                 # infinity / NaN (not a computed value: those are #NUM! already)
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
        if v is None and rc not in sheet.fml:
            # an empty cell is only formatted for what may arrive in it: no colours, no weight
            tn = ft = None
            out.pop("b", None)
            out.pop("it", None)
        if xf[4] in ("center", "right", "left"):
            out["al"] = xf[4][0]
        cf_fmt = None
        for i in cf_rules:
            st = self.cf(si).evaluate(i, calc, r, c, v, cf_cache if cf_cache is not None else {})
            if st is None:
                continue
            if "heat" in st:
                out["heat"] = st["heat"]
                continue
            if "bar" in st:
                out["bar"] = st["bar"]
                out["bc"] = tone(st.get("bar_color")) or "info"
                continue
            if st.get("fmt") and cf_fmt is None and tv is float:
                # a conditional format's number format (the dashboard's own: extras.SheetBuilder.number_format_if): the
                # number reads in it - the first rule that holds, Excel's order; the value ("v") and the input are untouched
                cf_fmt = st["fmt"]
                text, color = numfmt.render(v, cf_fmt, loc, general_digits=10)
                out["t"] = text.strip()
                out["k"] = "d" if numfmt.is_date_format(cf_fmt) else "n"
                if color:
                    tn = {"red": "neg", "green": "pos", "blue": "info"}.get(color, tn)
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
        tw = book.twoway.get((si, rc)) if book.twoway else None
        key = (si, rc)
        if tw is not None and not tw.store:
            # a member of a two-way table (tto/twoway.py): an input whose value is kept in its store
            key = tw.store_cell
            d = book.inputs.get(key)
        else:
            tw = None
        if d is not None and d.group == "adhoc" and not (overlay is not None and (si, rc) in overlay):
            d = None                               # typed over by hand ("elle değer"): an input only for whoever did
        if d is not None and d.kind == "check" and not out.get("t"):
            # a tick box that reads nothing - hidden by its conditional number format while its block is switched off
            # (OIS · PPK's normalization tenors) - is no box on the page: an empty cell, which an empty column drops
            d = None
        if d is not None:
            out["i"] = "s" if d.scope == "shared" else "u"
            opts = book.options_for(si, rc, calc)
            if opts:
                out["o"] = opts
            if overlay is not None and key in overlay and (tw is None or overlay[key] is not None):
                out["m"] = 1                       # modified by this user (a two-way member: its store holds a value)
            elif shared_values is not None and key[1] in shared_values[key[0]] and (tw is None or shared_values[key[0]][key[1]] is not None):
                out["m"] = 2                       # shared value differs from the workbook
            if tw is not None:
                twoway.mark(book, tw, overlay, shared_values, out)
            if numfmt.is_percent_format(fmt):
                out["ik"] = "pct"
            elif out.get("k") == "d" or d.kind == "date":
                out["ik"] = "date"
            elif d.kind not in ("auto", ""):
                out["ik"] = d.kind
        if rc in sheet.fml:
            out["fx"] = 1
        note = sheet.comments.get(rc)
        if note:
            out["n"] = note
        return out

    # ------------------------------------------------------------------ ranges
    def table(self, calc, sheet: str, rng: str, loc: numfmt.Locale, overlay=None, trim: bool = True,
              show_hidden: bool = True) -> Dict[str, Any]:
        """Cells of a range as the browser draws them.

        ``trim`` drops rows and columns that are completely empty; ``show_hidden=False`` also leaves out the
        columns that are hidden in the workbook (they are helpers the trader does not look at in Excel either).
        ``fz`` in the result is the number of leading columns that Excel keeps in view (frozen panes).
        """
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
        keep_r = list(range(len(row_nums)))
        keep_c = list(range(len(col_nums)))
        hidden_count = 0
        if not show_hidden and sh.hidden_cols:
            visible = [j for j in keep_c if not sh.col_hidden(col_nums[j])]
            if visible:                                  # a range that is hidden as a whole is shown as it is
                hidden_count = len(keep_c) - len(visible)
                keep_c = visible
        if trim:
            def empty(cell):
                return (cell.get("t", "") == "" and "i" not in cell) or cell.get("sk")
            used_r = [i for i in keep_r if not all(empty(rows[i][j]) for j in keep_c)]
            used_c = [j for j in keep_c if not all(empty(row[j]) for row in rows)]
            if used_r and used_c:
                # drop leading / trailing blank rows; a run of blank rows inside (they separate sub-tables)
                # shrinks to a single one
                filled = set(used_r)
                keep_r = [i for i in range(used_r[0], used_r[-1] + 1) if i in filled or (i - 1) in filled]
                keep_c = used_c
        if len(keep_c) != len(col_nums) or len(keep_r) != len(row_nums):
            kept_c, kept_r = set(keep_c), set(keep_r)
            # a merged cell keeps only the columns / rows that are still there
            for (a, b), (rs, cs) in spans.items():
                cell = rows[a - r1][b - c1]
                if cs > 1:
                    left = sum(1 for j in range(b - c1, b - c1 + cs) if j in kept_c)
                    if left > 1:
                        cell["cs"] = left
                    else:
                        cell.pop("cs", None)
                if rs > 1:
                    left = sum(1 for i in range(a - r1, a - r1 + rs) if i in kept_r)
                    if left > 1:
                        cell["rs"] = left
                    else:
                        cell.pop("rs", None)
            rows = [[rows[i][j] for j in keep_c] for i in keep_r]
            row_nums = [row_nums[i] for i in keep_r]
            col_nums = [col_nums[j] for j in keep_c]
        out = {"sheet": sheet, "rows": rows, "r": row_nums, "c": [index_to_col(c) for c in col_nums]}
        if hidden_count:
            out["hc"] = hidden_count                     # columns of the range that Excel hides (left out)
        frozen = sh.freeze[1] if len(sh.freeze) > 1 else 0
        if frozen and col_nums and col_nums[0] <= frozen:
            n = sum(1 for c in col_nums if c <= frozen)
            if 0 < n < len(col_nums):
                out["fz"] = n
        return out

    def cells_table(self, calc, sheet: str, cells: List[Tuple[int, int]], loc: numfmt.Locale, overlay=None) -> Dict[str, Any]:
        """A list of single cells as a three-column table: address, value, formula.

        Used for the cells of a sheet that belong to no table of its page (scratch calculations), so that
        nothing the workbook computes is left out.
        """
        from .books import formula_text
        book = self.book
        si = book.model.sheet_index[sheet]
        head = [{"t": "Hücre", "k": "s", "b": 1, "f": "hd"}, {"t": "Değer", "k": "s", "b": 1, "f": "hd"},
                {"t": "Formül", "k": "s", "b": 1, "f": "hd"}]
        rows = [head]
        for r, c in cells:
            rc = r * COLS + c
            cell = self.cell(calc, si, r, c, loc, overlay)
            cell.pop("i", None)                           # listed for reference; edited in its own table
            cell.pop("o", None)
            rows.append([{"t": a1(rc), "k": "s", "c": "mute"}, cell, {"t": formula_text(book, si, rc) or "", "k": "s"}])
        return {"sheet": sheet, "rows": rows}

    def values(self, calc, sheet: str, rng: str) -> List[List[Any]]:
        si = self.book.model.sheet_index[sheet]
        r1, c1, r2, c2 = parse_range(rng)
        return calc.get_range(si, r1, c1, r2, c2)

    def chart(self, calc, chart: Dict[str, Any], loc: numfmt.Locale) -> Dict[str, Any]:
        """Resolve a chart of the workbook into what the browser draws.

        Values follow Excel's plotting rules: a number is plotted; an empty cell leaves a gap (or zero / a
        connecting line, as the chart says); ``#N/A`` is skipped with the line running on - unless the chart
        shows #N/A as empty; text (even ``""``) counts as zero.  In the data ``None`` is a gap and ``"c"``
        a skipped point the line passes over.
        """
        book = self.book

        def split(ref: str) -> Tuple[str, str]:
            sheet, _, addr = ref.rpartition("!")
            return sheet.strip("'"), addr.replace("$", "")

        blanks = chart.get("blanks") or "gap"
        empty = None if blanks == "gap" else (0.0 if blanks == "zero" else "c")
        missing = empty if chart.get("na_gap") else "c"
        text_gap = chart.get("text") == "gap"

        def plot_value(v: Any) -> Any:
            tv = type(v)
            if tv is float:
                return v if v == v and abs(v) != float("inf") else missing
            if v is None:
                return empty
            if tv is XlError:
                return missing
            if tv is bool:
                return 0.0
            if text_gap:
                return empty                            # a chart of the dashboard's own: "" means "no value here"
            return 0.0                                  # text is plotted as zero

        def style_of(s: Dict[str, Any], entry: Dict[str, Any]) -> None:
            for key in ("dash", "noline", "marker", "smooth"):
                if s.get(key):
                    entry[key] = 1
            if s.get("color"):
                entry["color"] = s["color"]
            if s.get("alpha") is not None:
                entry["alpha"] = s["alpha"]
            if s.get("legend") is False:
                entry["legend"] = 0

        def name_of(s: Dict[str, Any]) -> str:
            name = s.get("name") or ""
            if s.get("name_ref"):
                nsh, naddr = split(s["name_ref"])
                nv = self.values(calc, nsh, naddr)
                name = str(nv[0][0]) if nv and nv[0] and nv[0][0] is not None else name
            return name

        def axis_format(out: Dict[str, Any]) -> None:
            fmt = chart.get("value_format") or ""
            if "%" in fmt:
                out["unit"] = "pct"
            first = fmt.split(";")[0]
            if first and first != "General":
                point = first.find(".")
                decimals = 0
                if point >= 0:
                    k = point + 1
                    while k < len(first) and first[k] in "0#?":
                        decimals += 1
                        k += 1
                out["decimals"] = decimals
            for key in ("ymin", "ymax", "major_unit", "label_skip", "aspect", "gap_width", "x_title", "y_title", "auto", "updown"):
                if chart.get(key) is not None:
                    out[key] = chart[key]

        if chart.get("x_axis") == "value" or chart.get("kind") == "scatter":
            # an XY chart: every series has its own x values; a point without a numeric x is not drawn
            points: List[Dict[str, Any]] = []
            for s in chart["series"]:
                sh, addr = split(s["val"])
                ys = [v for row in self.values(calc, sh, addr) for v in row]
                if s.get("cat"):
                    csh, caddr = split(s["cat"])
                    xvals = [v for row in self.values(calc, csh, caddr) for v in row]
                else:
                    xvals = [float(i + 1) for i in range(len(ys))]
                labels: List[Any] = []
                if s.get("labels_ref"):
                    lsh, laddr = split(s["labels_ref"])
                    lsi = book.model.sheet_index[lsh]
                    r1, c1, r2, c2 = parse_range(laddr)
                    labels = [self.cell(calc, lsi, r, c, loc).get("t", "") for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]
                px: List[float] = []
                py: List[Any] = []
                pl: List[str] = []
                for i, y in enumerate(ys):
                    x = xvals[i] if i < len(xvals) else None
                    if type(x) is not float or x - x != 0.0:
                        continue                        # (NaN and infinity have no place on an axis)
                    px.append(x)
                    py.append(plot_value(y))
                    pl.append(labels[i] if i < len(labels) else "")
                if s.get("optional") and not any(type(y) is float for y in py):
                    continue                            # a line of the dashboard's own that has nothing to draw (no contract chosen)
                entry = {"name": name_of(s), "kind": "scatter", "stacked": False, "x": px, "data": py}
                if labels:
                    entry["labels"] = pl
                style_of(s, entry)
                points.append(entry)
            out = {"title": chart.get("title") or "", "kind": "scatter", "scatter": 1, "cats": [], "series": points,
                   "axis": chart.get("axis_titles") or []}
            axis_format(out)
            xfmt = (chart.get("x_format") or "").replace("\\", "")
            is_date = bool(xfmt) and xfmt != "General" and any(ch in xfmt.lower() for ch in "dmy") and "0" not in xfmt
            xaxis: Dict[str, Any] = {"type": "date" if is_date else "value"}
            if xfmt and xfmt != "General":
                xaxis["format"] = xfmt
            for key, name in (("xmin", "min"), ("xmax", "max"), ("x_major_unit", "major_unit")):
                if chart.get(key) is not None:
                    xaxis[name] = chart[key]
            out["xaxis"] = xaxis
            return out

        cats: List[str] = []
        xs: List[Any] = []
        series: List[Dict[str, Any]] = []
        for s in chart["series"]:
            sh, addr = split(s["val"])
            vals = [v for row in self.values(calc, sh, addr) for v in row]
            name = name_of(s)
            if not cats and s.get("cat"):
                csh, caddr = split(s["cat"])
                si = book.model.sheet_index[csh]
                r1, c1, r2, c2 = parse_range(caddr)
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        cell = self.cell(calc, si, r, c, loc)
                        cats.append(cell.get("t", ""))
                        xs.append(cell.get("v") if cell.get("k") in ("n", "d") else None)
            entry: Dict[str, Any] = {"name": name, "kind": s.get("kind", "line"), "stacked": bool(s.get("stacked")),
                                     "data": [plot_value(v) for v in vals]}
            style_of(s, entry)
            series.append(entry)
        if not cats and series:
            cats = [str(i + 1) for i in range(len(series[0]["data"]))]
            xs = [None] * len(cats)
        # drop trailing categories that have neither a label nor a value in any series
        n = len(cats)
        while n > 0 and not cats[n - 1] and all(n - 1 >= len(s["data"]) or type(s["data"][n - 1]) is not float for s in series):
            n -= 1
        out: Dict[str, Any] = {"title": chart.get("title") or "", "kind": chart.get("kind", "line"), "cats": cats[:n],
                               "series": [dict(s, data=s["data"][:n]) for s in series],
                               "axis": chart.get("axis_titles") or []}
        axis_format(out)
        # a date axis places the points in proportion to their dates and labels months, not points
        if chart.get("x_axis") == "date" and n > 1 and all(type(x) is float for x in xs[:n]) \
                and all(xs[i] < xs[i + 1] for i in range(n - 1)):
            out["x"] = {"type": "date", "values": xs[:n], "format": (chart.get("x_format") or "").replace("\\", "")}
        return out
