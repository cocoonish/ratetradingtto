"""The interpolation chart of OIS · PPK (18.11.2026).  The desk: "İnterpolasyonların nasıl değiştiğini gösteren, hem
normal interpolasyonla hem de bu sistemde nasıl olur, bana curve de çiz bir yere" - the TRY curve between its quoted
tenors both ways (:mod:`tto.ppkcurve`: Bootstrap, what Murex marks with, and PPK basamak), drawn:

* the **overnight forward**, day by day from the spot, as step lines - the one-day simple rate (DF(t) / DF(t + 1) − 1) ·
  basis.  **Bootstrap** keeps ln DF linear in days between Motor's nodes (0, 1, 2, 3, 6 … 120 months): flat between two
  nodes, it steps at each.  **PPK basamak** keeps TLREF flat between PPK meetings with a flat calibration shift between
  two quoted maturities: it steps at a meeting's effective day and at a quoted maturity;
* the **3-month FRA strip** both ways (0x3, 3x6 …: Motor's quarterly calendar and OIS_MAIN!B336's formula - the FRA
  lists' market and "PPK basamak" columns), each FRA flat over its quarter, and their difference (bp) in a table under
  the chart and in its tooltip;
* the quoted tenors - where both curves reprice the same quote - as light lines over the plot, the meetings as ticks.

Over 1Y / 3Y / 10Y from the spot, OIS or offshore: the Forward sheet's offshore curve (FX swap implied ≤9M, XCCY 1Y–10Y,
ln DF linear) against ppkcurve's offshore PPK curve (MPC ima with a flat basis between the offshore quotes), on the
offshore quotes' ACT/360.  Every way is made at once - a few hundred points - and the page switches between them
(:func:`panel`).  Days are calendar days from a curve's spot, x values Excel serials (the chart's date axis), rates
decimals.  Nothing here changes either curve: both are read as :func:`tto.ppkcurve.read` and the sheet have them.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import ppkcurve as pk
from .xl import numfmt
from .xl.values import serial_to_date, to_num

#: the horizons the chart is drawn over - months from the spot: the quarterly calendar's day at that month ends it - and
#: the curves; the way a page opens with
HORIZONS: Tuple[Tuple[str, int], ...] = (("1Y", 12), ("3Y", 36), ("10Y", 120))
CURVES = ("OIS", "Offshore")
DEFAULT = ("3Y", "OIS")
#: the offshore curve as the Forward sheet has it (OFF_GUN / OFF_LNDF, Forward!AJ123:AN143): AK its nodes' days from the
#: FX spot, AM their ln DF - the spot first
OFF_ROWS, OFF_DAY, OFF_LNDF = (124, 143), 37, 39
#: Motor's meeting table beside the effective day the path steps on (ppkcurve.PATH_DAY): A the meeting's name, B its date;
#: the day of a row without a meeting
MEET_LABEL, MEET_DATE, NO_MEETING = 1, 2, 99999.0
#: the two ways' colours (the workbook's OIS blue, the orange of the FX swap curve; the dashboard draws its tone of each)
BOOT_COLOR, PPK_COLOR = "1F3864", "C55A11"
#: what the lines are called on each curve: the two ways and the strip
NAMES = {"OIS": ("Bootstrap (Murex)", "PPK basamak", "3A FRA"),
         "Offshore": ("Bootstrap (offshore)", "PPK basamak (offshore)", "3A forward")}

#: a stretch of a line: (from, to: days; the value there; what it is - an FRA's months)
Segment = Tuple[float, float, Optional[float], str]


def _num(v: Any) -> Optional[float]:
    return float(v) if type(v) in (float, int) and v == v else None


def _date(serial: float) -> str:
    return serial_to_date(serial).strftime("%d.%m.%Y")


# ================================================================================================== the workbook
def offshore_curve(get: Callable[[str, int, int], Any]) -> Optional[pk.LogLinear]:
    """The offshore TRY curve as the Forward sheet has it (Forward!AK124:AK143 days from the FX spot, AM124:AM143 ln DF;
    a tenor without a rate is no node) - the curve MASA's broken-date block and DİBS RV's FX swap ASW read.  ``None``
    with fewer than two nodes."""
    rows = range(OFF_ROWS[0], OFF_ROWS[1] + 1)
    try:
        return pk.LogLinear([get("Forward", r, OFF_DAY) for r in rows], [get("Forward", r, OFF_LNDF) for r in rows])
    except ValueError:
        return None


def meetings(get: Callable[[str, int, int], Any]) -> List[Tuple[float, str, Optional[float]]]:
    """The PPK meetings ahead, from Motor's meeting table (rows 5 … 84; C the effective day - the first business day
    after the meeting, days from the OIS spot: the day the path steps on): ``[(day, name, the meeting's date)]``.  A
    meeting gone by (day 0) and a row without one (99999) are left out."""
    out = []
    for r in range(pk.PATH_ROWS[0] + 1, pk.PATH_ROWS[1] + 1):
        day = _num(get("Motor", r, pk.PATH_DAY))
        if day is None or not 0.0 < day < NO_MEETING:
            continue
        name = get("Motor", r, MEET_LABEL)
        out.append((day, name.strip() if isinstance(name, str) else "", _num(get("Motor", r, MEET_DATE))))
    return out


# ================================================================================================== the lines
def boot_overnight(curve: pk.LogLinear, end: float, basis: float) -> List[Segment]:
    """The bootstrap's overnight forward from the spot to ``end``: (DF(t) / DF(t + 1) − 1) · ``basis``.  ln DF is linear
    between two nodes, so the rate is flat there - (e^(−slope) − 1) · basis, slope the stretch's ln DF per day - and steps
    at each node; past the last node the last stretch goes on, as the curve does."""
    d, v = curve.days, curve.lndf
    out: List[Segment] = []
    for i in range(len(d) - 1):
        if d[i + 1] <= 0.0:
            continue
        a = max(d[i], 0.0)
        if a >= end:
            break
        b = end if i == len(d) - 2 else min(d[i + 1], end)
        out.append((a, b, (math.exp(-(v[i + 1] - v[i]) / (d[i + 1] - d[i])) - 1.0) * basis, ""))
    return out


def ppk_overnight(curve: pk.StepCurve, end: float, scale: float = 1.0) -> List[Segment]:
    """PPK basamak's overnight rate - TLREF and the calibration's shift; ``scale`` times (360 / 365: on ACT/360) - from the
    spot to ``end``: flat between the days it changes (a meeting's effective day, a quoted maturity), stepping there."""
    steps = [(d, r) for d, r in curve.steps() if d < end]
    return [(d, steps[k + 1][0] if k + 1 < len(steps) else end, r * scale, "") for k, (d, r) in enumerate(steps)]


def ois_strip(curve, grid: pk.Grid, months: int) -> List[Segment]:
    """The 3M FRAs 0x3, 3x6 … up to ``months`` on Motor's quarterly calendar (:func:`tto.ppkcurve.fra`: OIS_MAIN!B336's
    formula - the FRA lists' market on the bootstrap, their "PPK basamak" column on the PPK curve)."""
    return [(grid.days[k - 1] if k else 0.0, grid.days[k], pk.fra(curve, grid, 3 * k, 3 * k + 3), "%dx%d" % (3 * k, 3 * k + 3))
            for k in range(months // 3)]


def offshore_strip(curve, grid: pk.Grid, months: int, shift: float) -> List[Segment]:
    """An offshore curve's 3M forward rates on the same quarters (days from the FX spot: the calendar's day less
    ``shift``, the FX spot − the OIS spot; the first from the FX spot), simple ACT/360 - the offshore quotes' own."""
    out: List[Segment] = []
    for k in range(months // 3):
        a, b = (grid.days[k - 1] - shift if k else 0.0), grid.days[k] - shift
        out.append((a, b, pk.forward(curve, a, b, 360.0) if b > a else None, "%dx%d" % (3 * k, 3 * k + 3)))
    return out


def points(segments: Sequence[Segment], origin: float) -> Tuple[List[float], List[Optional[float]], List[str]]:
    """Segments as a step line's points (x: ``origin`` + the day): each value from its own day, a closing point where a
    run of adjacent segments ends and a gap (``None``) before one that does not follow on; one without a value is left
    out.  The third list says what each point is (an FRA's months)."""
    x: List[float] = []
    y: List[Optional[float]] = []
    what: List[str] = []
    end: Optional[float] = None
    for a, b, v, name in segments:
        if v is None:
            continue
        if end is not None and a != end:
            x += [origin + end, origin + end]
            y += [y[-1], None]
            what += [what[-1], ""]
        x.append(origin + a)
        y.append(v)
        what.append(name)
        end = b
    if end is not None:
        x.append(origin + end)
        y.append(y[-1])
        what.append(what[-1])
    return x, y, what


def _series(name: str, segments: Sequence[Segment], origin: float, color: str, dash: bool = False) -> Dict[str, Any]:
    x, y, what = points(segments, origin)
    s: Dict[str, Any] = {"name": name, "kind": "scatter", "stacked": False, "x": x, "data": y, "step": 1, "color": color}
    if dash:
        s["dash"] = 1
    if any(what):
        s["tips"] = what                        # (the tooltip names the FRA the pointer is on)
    return s


# ================================================================================================== one way of drawing it
def _signed(v: float, loc) -> str:
    text = numfmt.format_value(v, "0.0", loc)
    return ("+" + text if v > 0 else text) if any(ch in "123456789" for ch in text) else numfmt.format_value(0.0, "0.0", loc)


def _strip_table(fb: Sequence[Segment], fp: Sequence[Segment], names: Tuple[str, str, str], origin: float, curve: str,
                 loc) -> Dict[str, Any]:
    """The strip under the chart, an FRA a column: both ways (%) and PPK − Bootstrap (bp; + green, − red)."""
    hd = {"k": "s", "b": 1, "f": "hd"}
    if curve == "OIS":
        how = ("3 aylık FRA, Motor'un çeyreklik takvimi ve gün sayımıyla (OIS_MAIN!B336'nın formülü): Bootstrap satırı FRA "
               "listelerinin Piyasa'sı, PPK basamak satırı listelerin PPK basamak sütunu")
    else:
        how = "3 aylık forward faiz, iki offshore eğride aynı çeyreklerle: basit ACT/360 (offshore kotaların kuralı)"
    head = [dict(hd, t=names[2] + (" (ACT/360)" if curve == "Offshore" else ""), tip=how)]
    rows = [[{"t": names[0], "k": "s", "b": 1}], [{"t": names[1], "k": "s", "b": 1}],
            [{"t": "PPK − Bootstrap (bp)", "k": "s", "b": 1}]]
    for (a, b, vb, label), (_, _, vp, _) in zip(fb, fp):
        m1, m2 = (int(x) for x in label.split("x"))
        desk = (pk.tenor_label(m1) if m1 else "Spot") + pk.tenor_label(m2 - m1)        # (the FRA list's name: "1Y3M")
        head.append(dict(hd, t=label, al="r", tip="%s · %s → %s (%d gün)" % (
            desk, _date(origin + a), _date(origin + b), int(round(b - a)))))
        for row, v in ((rows[0], vb), (rows[1], vp)):
            row.append({"t": numfmt.format_value(v, "0.000%", loc), "v": v, "k": "n"} if v is not None else {"t": "", "k": ""})
        if vb is None or vp is None:
            rows[2].append({"t": "", "k": ""})
            continue
        bp = (vp - vb) * 1e4
        cell = {"t": _signed(bp, loc), "v": bp, "k": "n"}
        if cell["t"][0] in "+-":
            cell["c"] = "pos" if bp > 0 else "neg"
        rows[2].append(cell)
    return {"sheet": "", "rows": [head] + rows}


def _line(fb: Sequence[Segment], fp: Sequence[Segment], horizon: str, curve: str, names: Tuple[str, str, str],
          quotes: Sequence[pk.Quote], stop: float, origin: float, loc) -> str:
    """What the strip shows, in a line: where the two ways part most, where they are the same - and, past the last quote
    (offshore: the XCCY quotes may stop early), that both lines only go on there."""
    diffs = [(lab, (vp - vb) * 1e4) for (_, _, vb, lab), (_, _, vp, _) in zip(fb, fp) if vb is not None and vp is not None]
    if not diffs:
        return ""
    same = [lab for lab, d in diffs if abs(d) < 0.05]
    big = [x for x in sorted(diffs, key=lambda x: -abs(x[1])) if abs(x[1]) >= 0.05][:3]
    text = "%s · %s · %s farkı (PPK basamak − Bootstrap): " % (horizon, curve, names[2])
    text += ("en çok " + " · ".join("%s %s bp" % (lab, _signed(d, loc)) for lab, d in big)) if big else "her çeyrekte aynı"
    if same and big:
        text += "; aynı (iki ucu da kotalı vade): " + ", ".join(same)
    last = max(quotes, key=lambda q: q.end, default=None)
    if last is not None and last.end < stop:
        text += ". Son kota %s (%s): sonrası iki eğride de uzatma" % (last.name, _date(origin + last.end))
    return text


def view(cv: Dict[str, Any], off_boot: Optional[pk.LogLinear], meets: Sequence[Tuple[float, str, Optional[float]]],
         spot: Optional[float], horizon: str, curve: str, loc) -> Dict[str, Any]:
    """One way of drawing it: ``horizon`` ("1Y", "3Y", "10Y"), ``curve`` ("OIS", "Offshore").  ``cv``: the curves as
    :func:`tto.ppkcurve.read` makes them, ``off_boot`` the offshore curve as the sheet has it (:func:`offshore_curve`),
    ``meets`` the meetings ahead (:func:`meetings`), ``spot`` the OIS spot (serial).  Returns ``{"data": the chart,
    "strip": the FRA strip's table, "line": what it shows in a line}`` - without the curves a chart with nothing to draw,
    the reason in ``line``."""
    months = dict(HORIZONS)[horizon]
    names = NAMES[curve]
    grid = cv.get("grid")
    if curve == "OIS":
        boot, ppk, quotes, shift, basis = cv.get("boot"), cv.get("ppk"), cv.get("quotes") or [], 0.0, pk.BASIS
    else:
        boot, ppk, quotes, shift, basis = off_boot, cv.get("off_ppk"), cv.get("off_quotes") or [], cv.get("fx_shift"), 360.0
    data: Dict[str, Any] = {"title": "%s · O/N forward ve %s · %s" % (curve, names[2], horizon), "kind": "scatter", "scatter": 1,
                            "cats": [], "series": [], "axis": [], "unit": "pct", "decimals": 1, "auto": "fit", "aspect": 0.42,
                            "y_title": "%", "xaxis": {"type": "date", "format": "mmm yy"}}
    if boot is None or ppk is None or grid is None or len(grid.days) < months // 3 or spot is None or shift is None:
        why = "; ".join(cv.get("errors") or []) or "eğri kurulamadı"
        return {"data": data, "strip": None, "line": "%s · %s: çizilemedi (%s)" % (horizon, curve, why)}
    origin = spot + shift
    end = grid.days[months // 3 - 1]                       # (OIS days: the calendar's day at the horizon)
    stop = end - shift
    data["y_title"] = "%%, ACT/%d" % int(basis)
    if curve == "OIS":
        fb, fp = ois_strip(boot, grid, months), ois_strip(ppk, grid, months)
    else:
        fb, fp = offshore_strip(boot, grid, months, shift), offshore_strip(ppk, grid, months, shift)
    data["series"] = [_series("O/N · " + names[0], boot_overnight(boot, stop, basis), origin, BOOT_COLOR),
                      _series("O/N · " + names[1], ppk_overnight(ppk, stop, basis / pk.BASIS), origin, PPK_COLOR),
                      _series("%s · %s" % (names[2], names[0]), fb, origin, BOOT_COLOR, dash=True),
                      _series("%s · %s" % (names[2], names[1]), fp, origin, PPK_COLOR, dash=True)]
    # the differences the tooltip adds at the pointer's day, and the quoted tenors / meetings it names there
    data["tipdiff"] = [{"a": 1, "b": 0, "name": "O/N · PPK − Bootstrap", "scale": 1e4, "digits": 1, "unit": "bp"},
                       {"a": 3, "b": 2, "name": "%s · PPK − Bootstrap" % names[2], "scale": 1e4, "digits": 1, "unit": "bp"}]
    marks = [{"x": origin + q.end, "t": q.name.split(" ")[-1],
              "tip": "%s kotası (%s): iki eğri de aynen fiyatlar" % (q.name, _date(origin + q.end))}
             for q in quotes if 0.0 < q.end <= stop]
    marks += [{"x": spot + day, "k": "tick", "color": PPK_COLOR,
               "tip": "%s toplantısı%s · TLREF %s'den" % (name or "PPK", " " + _date(date) if date else "", _date(spot + day))}
              for day, name, date in meets if day < end]
    data["vmarks"] = sorted(marks, key=lambda m: m["x"])
    return {"data": data, "strip": _strip_table(fb, fp, names, origin, curve, loc),
            "line": _line(fb, fp, horizon, curve, names, quotes, stop, origin, loc)}


# ================================================================================================== the panel
def panel(cv: Optional[Dict[str, Any]], get: Callable[[str, int, int], Any], loc) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The chart's panel out of the curves (``cv``: :func:`tto.ppkcurve.read`'s, the user's own calculation) and the
    workbook (``get(sheet, row, column)`` through the same calculation): every way at once - ``choice``: the page's
    selectors (``groups``) and each way by "horizon|curve" (``items``, :func:`view`) - and the chart the page opens with
    (what a launchpad or the side drawer draws)."""
    if cv is None:                                         # (a workbook without the TRY curves' sheets: nothing to read)
        cv, off_boot, meets, spot = {"errors": ["TRY eğrileri bu çalışma kitabında yok"]}, None, [], None
    else:
        # the offshore Bootstrap the curves were read with (Service._try_curves: the names - the desk's list of points'
        # curve when its list differs from the default), else the Forward sheet's own
        off_boot = cv["off_boot"] if cv.get("off_boot") is not None else offshore_curve(get)
        meets, spot = meetings(get), _num(to_num(get(*pk.OIS_SPOT)))
    items ={"%s|%s" % (h, c): view(cv, off_boot, meets, spot, h, c, loc) for h, _ in HORIZONS for c in CURVES}
    choice = {"groups": [{"id": "ufuk", "title": "Ufuk: spot'tan 1, 3 ya da 10 yıl", "options": [h for h, _ in HORIZONS],
                          "default": DEFAULT[0]},
                         {"id": "egri", "title": "OIS eğrisi (ACT/365) ya da offshore eğri (FX swap ≤9M + XCCY; ACT/360)",
                          "options": list(CURVES), "default": DEFAULT[1]}],
              "items": items}
    return items["|".join(DEFAULT)]["data"], choice
