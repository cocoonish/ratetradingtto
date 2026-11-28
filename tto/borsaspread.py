"""Borsa Swap against the TRY workbook's mid curves: each BIST swap quote's BID % / ASK % next to the OIS and the
offshore mid curve's zero rate between the same two dates, and how far it is from each, in bp.

The swap tables live in the Borsa workbook, the curves in the TRY workbook: the page's two tables get six columns of
the dashboard's own on their right (``"append": "borsa_spread"`` in the page definition), worked out every time the
table is made.  The rows are the quotes of the moment (only those with an order behind them): nothing is kept of
them.  A row runs from its start - its maturity (the "Valör" column) less its days (VKGS): today for T+0, the next
business day of the desk's TRY holiday list for T+1 (``extras.BORSA_HOL_SHEET``: the day the TRY OIS spot is) - to its
maturity, and gets

* **OIS mid zero %** - the bootstrapped TLREF OIS curve (``BOOT_GUN`` / ``BOOT_LNDF``: Motor!C88:C130 / I88:I130), built
  from the OIS par quotes of OIS_MAIN!B9:B26 - each tenor's MID from the first pricing source that has one (PX_LAST
  where a source gives no MID; no bid or ask enters it).  ln DF at its nodes, days from the OIS spot date ``SPOTDATE``,
  linear in days between them and past the last one along the last segment: the "Bootstrap" row of Masa's 'TARİH
  ARASI FAİZ' and of OIS_MAIN's 'İKİ TARİH ARASI SIMPLE RATE' (MASA!H67:I67, OIS_MAIN!D129:E129).  At a node its rate
  is ORANLAR's "OIS zero" (Motor!M89 …).  Its first node after the spot is 1M: here - for these spreads only, the
  curve itself and Masa's rows stay as they are - the 1W and 2W points ORANLAR reads its 1W / 2W "OIS zero" from come
  before it (the 1W / 2W OIS quotes - MID, else PX_LAST - as the Forward sheet's "TRY OIS · basit zero" holds them:
  Forward!N6:P7, days and simple ACT/360 %), so a row of up to a month runs between spot, 1W, 2W and 1M;
* **Offshore mid zero %** - the offshore TRY discount curve (``OFF_GUN`` / ``OFF_LNDF``: Forward!AK124:AK143 /
  AM124:AM143, Forward!AJ122): the mids (bid–ask average) of the FX swap implied TRY rates up to 9M - its short points
  1W, 2W and 1M (TRYI1W, TRYI2W, TRYI1M) among them -, then the XCCY bootstrap of the XCCY mids from 1Y; days from the
  USDTRY spot date (Forward!I2); the same interpolation (MASA!BL179, DİBS RV's FX swap ASW).

Both simple ACT/360 - the basis of BID % / ASK % -: (DF(start) / DF(end) − 1) · 360 / days.  A start before a curve's
spot date (T+0: a day, over a weekend three, before it) is carried to the spot with the curve's own O/N, simple: ORANLAR's
ON row, which reads it from the Forward sheet's comparison table (Forward!AC123:AD123) - TLREF for OIS (OIS_MAIN!J2,
365 → 360), the offshore O/N implied mid for the offshore curve.  The spreads are the swap's own sides against the mid:
BID % − mid zero and ASK % − mid zero, in bp; a side without a quote has none.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .inputs import parse_date
from .xl import numfmt
from .xl.model import COLS, parse_a1, parse_range
from .xl.parser import parse_template
from .xl.tokenizer import index_to_col

SHEET = "bu"
#: the two swap tables of the Borsa workbook's sheet, by the first column of a page's range of them: what the spreads
#: read - the maturity ("Valör"), its days from the start ("VKGS"), BID % and ASK % - and the caption of each column
TABLES = {"D": (("D", "Valör"), ("E", "VKGS"), ("H", "BID %"), ("M", "ASK %")),        # T+0 (BFX0): from today
          "Q": (("Q", "Valör"), ("R", "VKGS"), ("U", "BID %"), ("Z", "ASK %"))}        # T+1 (BFX1): from the next day

#: the TRY workbook's mid curves: key, the defined names of their nodes (days from the spot date, ln DF), the spot date
#: (a name or a cell) and the O/N a day before the spot is carried with (simple ACT/360), with its name in a tip
CURVES = (("ois", "BOOT_GUN", "BOOT_LNDF", "SPOTDATE", "Forward!AD123", "TLREF, 365 → 360"),
          ("off", "OFF_GUN", "OFF_LNDF", "Forward!I2", "Forward!AC123", "offshore O/N mid"))
#: the captions the O/N cells stand under: the ON row of the comparison table, its OIS and offshore columns (the offshore
#: one reads "Offshore" since 28.11.2026 - the curve's one name, extras.NAMES_NAME -, "ICAP" where that addition is left out)
ON_CAPTIONS = (("Forward!AA123", ("ON",)), ("Forward!AD122", ("OIS",)), ("Forward!AC122", ("Offshore", "ICAP")))
#: the OIS curve's short points before its first node (1M), for these spreads: ORANLAR's 1W and 2W "OIS zero" - the Forward
#: sheet's "TRY OIS · basit zero" (days, simple ACT/360 %) - and the caption of the tenor each stands beside
OIS_SHORT = (("Forward!N6", "Forward!P6", "Forward!O6", "1W"), ("Forward!N7", "Forward!P7", "Forward!O7", "2W"))

PCT = "0.00%"                            # BID % / ASK %'s own format
BP = "#,##0"

#: the columns added on the right of each table: caption and what it is (the caption's tip)
HEADS = (("OIS mid zero %", "TLREF OIS mid eğrisinin (bootstrap: OIS par kotalarının MID'i) satırın başlangıcı → Valör arası "
                            "zero faizi, basit ACT/360 – Masa'nın 'Tarih arası faiz' Bootstrap satırıyla aynı hesap. Başlangıç: "
                            "T+0'da bugün, T+1'de ertesi iş günü (TRY tatilleri atlanır). 1A'dan kısa vadede eğrinin 1A "
                            "düğümünden önce 1W ve 2W OIS kotaları (ORANLAR'ın 1W / 2W OIS zero'su) düğüm olarak girer. OIS "
                            "spot'undan önceki gün(ler) TLREF ile (ORANLAR'ın ON satırı)"),
         ("Offshore mid zero %", "Offshore TRY mid eğrisinin (≤9A FX swap ima faizlerinin bid–ask ortası, 1Y'den XCCY "
                                 "ortalarının bootstrap'ı) aynı tarihler arası zero faizi, basit ACT/360. USDTRY spot'undan "
                                 "önceki gün(ler) offshore O/N mid ile (ORANLAR'ın ON satırı)"),
         ("BID − OIS mid (bp)", "BID % − OIS mid zero % (bp): + ise swap'ın bid faizi OIS mid'in üstünde"),
         ("ASK − OIS mid (bp)", "ASK % − OIS mid zero % (bp): + ise swap'ın ask faizi OIS mid'in üstünde"),
         ("BID − Off mid (bp)", "BID % − Offshore mid zero % (bp): + ise swap'ın bid faizi offshore mid'in üstünde"),
         ("ASK − Off mid (bp)", "ASK % − Offshore mid zero % (bp): + ise swap'ın ask faizi offshore mid'in üstünde"))


class Curve(object):
    """A zero curve as the TRY workbook reads one: ln DF at nodes ``days`` after the spot date ``spot`` (an Excel
    serial), linear in days between them and past the last one along the last segment; a day before the spot is one
    O/N period at ``on`` (simple ACT/360) away from it.  ``why``: what is missing when the curve cannot be read at all;
    ``on_name``: what the O/N is (a cell's tip)."""

    __slots__ = ("spot", "days", "lndf", "on", "why", "on_name")

    def __init__(self, spot: Any, days: Sequence[Any], lndf: Sequence[Any], on: Any = None, why: str = "",
                 on_name: str = "O/N"):
        self.spot = spot if type(spot) is float else None
        self.days = list(days)
        self.lndf = list(lndf)
        self.on = on if type(on) is float else None
        self.why = why or ("" if self.spot is not None else "eğrinin spot valörü okunamadı")
        self.on_name = on_name

    def lndf_at(self, t: float) -> Optional[float]:
        """ln DF ``t`` ≥ 0 days after the spot: between the last node at or before ``t`` and the one after it - the
        workbook's MATCH(t, days, 1), the last segment past the last node (a node without a number is passed over as
        LOOKUP does).  ``None`` when either end of that segment has no number."""
        days, lndf = self.days, self.lndf
        n = min(len(days), len(lndf))
        k = None
        for i in range(n):
            d = days[i]
            if type(d) is not float:
                continue
            if d > t:
                break
            k = i
        if k is None or n < 2:
            return None
        k = min(k, n - 2)
        d0, d1, l0, l1 = days[k], days[k + 1], lndf[k], lndf[k + 1]
        if not all(type(x) is float for x in (d0, d1, l0, l1)) or not d1 > d0:
            return None
        return l0 + (l1 - l0) * (t - d0) / (d1 - d0)

    def df(self, day: float) -> Optional[float]:
        """The discount factor of a day (Excel serial) at the spot date: 1 at the spot, below 1 after it; a day before
        it 1 + O/N · days / 360 (money of that day is worth that much at the spot)."""
        if self.why:
            return None
        t = day - self.spot
        if t >= 0:
            x = self.lndf_at(t)
            return math.exp(x) if x is not None else None
        return 1.0 + self.on * -t / 360.0 if self.on is not None else None

    def zero(self, start: float, end: float) -> Optional[float]:
        """The curve's simple ACT/360 zero rate from ``start`` to ``end`` (Excel serials): (DF(start)/DF(end) − 1)·360/days."""
        if not end > start:
            return None
        a, b = self.df(start), self.df(end)
        if a is None or b is None or not b > 0:
            return None
        return (a / b - 1.0) * 360.0 / (end - start)


# ---------------------------------------------------------------------------------------------- reading the curves
def _cell(book, calc, ref: str) -> Any:
    si, rc = book.cell(ref)
    return calc.get(si, *divmod(rc, COLS))


#: the conditions of names defined as IF(condition, reference, reference), compiled: (book, name, branch path) -> function
_CONDITIONS: Dict[Tuple[str, str, str], Any] = {}


def _branch(book, calc, name: str, node) -> Any:
    """A name defined as ``IF(condition, reference, reference)`` (the offshore curve's names follow the user's curve
    setting: ``extras.INTERP_OFF_COLS``): the reference its condition picks in ``calc`` - evaluated there, so what it read
    counts as read; any other name as it is."""
    from .render import calc_value
    path = ""
    while node[0] == "func" and node[1] == "IF" and len(node[2]) == 3:
        key = (book.id, name, path)
        fn = _CONDITIONS.get(key)
        if fn is None:
            fn = _CONDITIONS[key] = book.engine.compiler.compile_node(node[2][0])
        took = calc_value(calc, fn, 0, 1, 1)
        first = took is True or (type(took) is float and took != 0.0)
        node = node[2][1] if first else node[2][2]
        path += "1" if first else "2"
    return node


def _named(book, calc, name: str) -> Optional[List[Any]]:
    """The values of a defined name of the workbook - a cell or a block, row by row (one defined as an IF between two:
    the one its condition picks in ``calc``); ``None`` when the workbook has no such name (or it is no plain reference)."""
    text = book.model.names.get(name)
    if not text:
        return None
    try:
        node = _branch(book, calc, name, parse_template(text))
    except Exception:  # noqa: BLE001 - a name that cannot be read names no curve
        return None
    if node[0] == "cell" and node[2] and node[4]:
        r1 = r2 = node[3]
        c1 = c2 = node[5]
    elif node[0] == "range" and all(node[k] for k in (2, 4, 6, 8)):
        r1, c1, r2, c2 = node[3], node[5], node[7], node[9]
    else:
        return None
    si = book.model.sheet_index.get(node[1])
    if si is None:
        return None
    return [v for row in calc.get_range(si, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)) for v in row]


def _date(v: Any) -> Any:
    """A date as the workbook holds one: a serial - or a text Bloomberg gave ("4.11.2026")."""
    if isinstance(v, str) and v.strip():
        return parse_date(v)
    return v


def with_short_points(days: Sequence[Any], lndf: Sequence[Any], points: Sequence[Tuple[Any, Any]]) -> Tuple[List[Any], List[Any]]:
    """A curve's nodes (``days`` from its spot - the first one the spot itself -, ``lndf``) with short points put in before
    its first node after the spot: ``points`` are (days, simple ACT/360 zero rate), each a node of ln DF −ln(1 + r·days/360).
    A point without a number, not between the spot and that node, or of a day another point has, is left out."""
    days, lndf = list(days), list(lndf)
    if len(days) < 2 or days[0] != 0.0 or type(days[1]) is not float:
        return days, lndf
    extra: Dict[float, float] = {}
    for d, r in points:
        if type(d) is float and type(r) is float and 0.0 < d < days[1] and d not in extra and 1.0 + r * d / 360.0 > 0:
            extra[d] = -math.log(1.0 + r * d / 360.0)
    put = sorted(extra.items())
    return [days[0]] + [d for d, _ in put] + days[1:], [lndf[0]] + [x for _, x in put] + lndf[1:]


def _short_points(book, calc) -> List[Tuple[Any, Any]]:
    """The OIS curve's short points the spreads read (``OIS_SHORT``): (days, rate) each - none where a tenor's caption is
    not the one expected (the sheet's layout changed)."""
    out: List[Tuple[Any, Any]] = []
    for days_ref, rate_ref, caption_ref, tenor in OIS_SHORT:
        try:
            si, rc = book.cell(caption_ref)
        except (KeyError, ValueError):
            continue
        if str(book.model.sheets[si].consts.get(rc) or "").strip() != tenor:
            continue
        rate = _cell(book, calc, rate_ref)
        out.append((_cell(book, calc, days_ref), rate / 100.0 if type(rate) is float else None))
    return out


def read_curves(book, calc) -> Dict[str, Curve]:
    """The OIS and the offshore mid curve of the TRY workbook ``book`` as ``calc`` has them (a user's own inputs there
    apply): ``{"ois": Curve, "off": Curve}`` - one that cannot be read says why (``Curve.why``)."""
    on_ok = True
    for ref, caption in ON_CAPTIONS:
        try:
            si, rc = book.cell(ref)
        except (KeyError, ValueError):
            on_ok = False
            break
        on_ok = on_ok and str(book.model.sheets[si].consts.get(rc) or "").strip() in caption
    out: Dict[str, Curve] = {}
    for key, days_name, lndf_name, spot_ref, on_ref, on_name in CURVES:
        days, lndf = _named(book, calc, days_name), _named(book, calc, lndf_name)
        if days is None or lndf is None:
            out[key] = Curve(None, [], [], why="TTO çalışma kitabında %s / %s adı yok" % (days_name, lndf_name))
            continue
        try:
            spot = _cell(book, calc, spot_ref) if "!" in spot_ref else (_named(book, calc, spot_ref) or [None])[0]
        except (KeyError, ValueError):
            spot = None
        if key == "ois":
            days, lndf = with_short_points(days, lndf, _short_points(book, calc))
        on = _cell(book, calc, on_ref) if on_ok else None
        out[key] = Curve(_date(spot), days, lndf, on, on_name=on_name)
    return out


# ---------------------------------------------------------------------------------------------- the columns
def _day(v: float, loc) -> str:
    return numfmt.format_value(v, "dd.mm.yyyy", loc)


def _zero_cell(curve: Curve, z: Optional[float], start: float, end: float, loc) -> Dict[str, Any]:
    """A curve's zero rate of a row, the dates (and the O/N of the days before the spot) in its tip."""
    span = "%s → %s · %d gün" % (_day(start, loc), _day(end, loc), int(round(end - start)))
    if z is None:
        if curve.why:
            why = curve.why
        elif start < curve.spot and curve.on is None:
            why = "spot öncesi günler için O/N faizi (%s) yok" % curve.on_name
        else:
            why = "eğrinin bu vadede değeri yok"
        return {"t": "", "k": "", "tip": "%s: %s" % (span, why)}
    tip = span
    if start < curve.spot:
        tip += "\nSpot öncesi %s → %s (%d gün): O/N %s (%s) ile, basit ACT/360" % (
            _day(start, loc), _day(curve.spot, loc), int(round(curve.spot - start)),
            numfmt.format_value(curve.on, PCT, loc), curve.on_name)
    return {"t": numfmt.format_value(z, PCT, loc), "v": z, "k": "n", "al": "c", "tip": tip}


def _bp_cell(rate: Any, z: Optional[float], loc) -> Dict[str, Any]:
    """A side's rate − the mid zero rate, in bp (signed; + above the mid); empty without a quote on that side."""
    if type(rate) is not float or z is None:
        return {"t": "", "k": ""}
    v = (rate - z) * 10000.0
    whole = math.floor(abs(v) + 0.5)
    if not whole:
        return {"t": "0", "v": v, "k": "n", "al": "c"}
    return {"t": ("+" if v > 0 else "-") + numfmt.format_value(whole, BP, loc), "v": v, "k": "n", "al": "c",
            "c": "pos" if v > 0 else "neg"}


def columns(book, calc, rng: str, data: Dict[str, Any], loc, curves: Dict[str, Curve]) -> None:
    """The six columns on the right of a BIST swap table of the Borsa workbook (``rng``: the page's range of it, its
    first row the captions; ``calc``: the page's calculation of the workbook): per quoted row the OIS and the offshore
    mid curve's zero rate between the row's start and maturity, and BID % / ASK % − each, in bp.  A table this does not
    know - or whose captions moved - is left as it is."""
    rows, rnums = data.get("rows") or [], data.get("r") or []
    r1, c1, r2, _ = parse_range(rng)
    spec = TABLES.get(index_to_col(c1))
    if not rows or spec is None or SHEET not in book.model.sheet_index:
        return
    si = book.model.sheet_index[SHEET]
    consts = book.model.sheets[si].consts
    if any(str(consts.get(parse_a1("%s%d" % (col, r1))) or "").strip() != caption for col, caption in spec):
        return
    cols = [parse_a1("%s1" % col) % COLS for col, _ in spec]
    ois, off = curves["ois"], curves["off"]
    heads = []
    for k, (caption, tip) in enumerate(HEADS):
        why = ois.why if k in (0, 2, 3) else off.why
        heads.append({"t": caption, "k": "s", "b": 1, "al": "c", "tip": tip + ("\nŞu an hesaplanamıyor: " + why if why else "")})
    for i, r in enumerate(rnums):
        if r == r1:
            rows[i].extend(dict(h) for h in heads)
            continue
        mat = days = bid = ask = None
        if r1 < r <= r2:
            mat, days, bid, ask = (calc.get(si, r, c) for c in cols)
        if type(mat) is not float or type(days) is not float or not days > 0:
            rows[i].extend({"t": "", "k": ""} for _ in HEADS)
            continue
        start, end = mat - days, mat
        zo, zf = ois.zero(start, end), off.zero(start, end)
        rows[i].extend([_zero_cell(ois, zo, start, end, loc), _zero_cell(off, zf, start, end, loc),
                        _bp_cell(bid, zo, loc), _bp_cell(ask, zo, loc), _bp_cell(bid, zf, loc), _bp_cell(ask, zf, loc)])
    data["c"] = list(data.get("c") or []) + [h for h, _ in HEADS]
    data["added"] = int(data.get("added") or 0) + len(HEADS)       # columns that are no cells of the sheet
