"""Fiyatlama (18.11.2026; the desk: "Kırık vade fiyatlamayı da açalım. Bir fiyatlama sekmesi olsun, buradan asseti ve
vadeyi seçtiğimde fiyat, DV01'lar bucket bucket olarak, fiyat girdiğimde de NPV'yi vermeli."): one instrument, at any
start and maturity, priced on the desk's TRY curves both ways (:mod:`tto.ppkcurve`: Bootstrap (Murex) and PPK basamak) -
its mid, its DV01 bucket by bucket and, with a price typed, its NPV.

* **TRY OIS** (spot or forward start) and **FRA** (an OIS forward: start × end, both from the OIS spot): fixed against
  TLREF compounded, ACT/365; up to 3M one payment, longer quarterly - the coupons counted back from the maturity, the
  short period first, as MASA's broken-date block's helper has them (``BL192:BP233``: "valörden geriye 3M, ilk dönem
  kısa").  A tenor from the spot is Motor's own quarterly calendar (``Motor!F139:F178``): an FRA on it is the FRA lists'
  (``OIS_MAIN!B336``), a quoted tenor its quote.  Days from the OIS spot (``OIS_MAIN!B2``), the TRY holidays (Motor's).
* **XCCY**: TRY fixed, annual ACT/360, against USD floating at par (the offshore TRY curve is the cross currency curve):
  the coupons counted back from the maturity in 12 months, the short period first - 18M is 6M then 12M, 2Y3M is 3M, 12M
  and 12M (the desk: "18 ayda 6 ay + 12 ay olarak kupon ödemesi yapılıyor, sondan başlayıp"; the block's helper
  ``BU192:BY203``).  On the offshore curve (days from the FX spot, ``Forward!I2``).
* **FX forward** (USDTRY, EURTRY): F = S · DF_TRY(spot) / DF_TRY(value date) / (1 + r·d/360) - the offshore curve and the
  USD (EUR) OIS rate at the date, linear in days between the Forward sheet's tenors, as the broken-date block prices its
  forward (``MASA!F173``: spot ``MASA!H2``, the USD rate ``BL178``); points = (F − S)·10 000.

Every number comes on both curves, the user's own setting first (Ayarlar → Eğri interpolasyonu).  **DV01** (TL and $
per bp; + = the position gains when the rates rise: the payer's, USD bought forward - Günlük İşlemler's and DV01 Risk's
sign) bucket by bucket: each pillar's quote +1 bp, the curve built again on the same method and the position valued
again - **Bootstrap**: Motor's own bucket bump (``Motor!T86``, "her kota +1bp bootstrap": the par rates at Motor's
nodes linear in months again, Motor's bootstrap again, ln DF linear in days); **PPK basamak**: the calibration solved
again (MPC ima as it is; the flat overnight shift of the bumped quote's stretch and of every later one solved again);
**offshore**: the FX swap / XCCY bootstrap again (Bootstrap), the offshore calibration again (PPK).  The total is the
sum of the buckets.  **NPV** of the position at the typed price on each curve (+ = in the trader's favour, as Günlük
İşlemler's "Mid'e göre"), and the price's distance from mid.

**The ways back** (the desk, 24.11.2026: "1-2-3-4-5-6-7-8-11-11-13" - 4 was "type an NPV (TL or $) or an upfront in bp and
get the fixed rate; a box that prices a list of tenors at once"): the price box holds what ``price_kind`` says - a swap's
rate, or an NPV in TL or $ or an upfront in bp of the nominal; an FX forward's outright or points, or an NPV in TL or $.
An NPV (an upfront: NPV = nominal · bp / 10 000) gives the level that prices to it - :func:`level_for`, :func:`value`'s
exact inverse - on the user's own curve, the other curve's beside it; every number (NPV, DV01 buckets, price − mid) is
then at that level.  **Toplu** (:func:`bulk`): every line of a box - a maturity, a start × end, two dates; a price after
it - priced as the page prices its instrument, off the same curves (nothing built again for a line).

Days are calendar days from a curve's spot, rates decimals, dates Excel serials.  :func:`read` takes what is not in the
curves (:func:`tto.ppkcurve.read` and the service's offshore curve) from the workbook through a cell getter; the rest
knows no workbook.
"""
from __future__ import annotations

import bisect
import math
import re
from typing import Any, Callable, Dict, FrozenSet, List, NamedTuple, Optional, Sequence, Tuple

from . import extras as ex
from . import ppkcurve as pk
from .blotter import _round_half_away
from .history import add_months
from .inputs import _fold, parse_amount, parse_date, parse_number
from .xl.values import date_to_serial, serial_to_date, to_num

#: one basis point; the bump of a pillar's quote
BP = 1e-4
BOOT, PPK = "boot", "ppk"
METHODS = (BOOT, PPK)
METHOD_TEXT = {BOOT: "Bootstrap (Murex)", PPK: "PPK basamak"}
OIS, FRA, XCCY, FX = "ois", "fra", "xccy", "fx"
ASSETS = (OIS, FRA, XCCY, FX)
ASSET_TEXT = {OIS: "TRY OIS", FRA: "FRA", XCCY: "XCCY", FX: "FX forward"}
PAIRS = ("USDTRY", "EURTRY")
#: the sides: OIS, FRA and XCCY by the fixed leg, an FX forward by the currency bought or sold
RATE_SIDES, FX_SIDES = ("PAY", "RECEIVE"), ("AL", "SAT")
#: the curve families: the onshore OIS curve and the offshore one (FX swap ≤ 9M + XCCY 1Y–10Y)
ON, OFF = "ois", "off"
#: the desk's OIS buckets the curve has no pillar at (its bootstrap starts at the 1M quote; Günlük İşlemler Q89:Q91)
SHORT_BUCKETS = ("ON", "1W", "2W")
#: what the price box holds (``price_kind``, kept per asset; the first: what it held before 24.11.2026): a swap's fixed
#: rate, or the NPV (TL, $) or the upfront (bp of the nominal) its rate is solved from; an FX forward's outright or points,
#: or the NPV (TL, $) its outright is solved from
RATE_KINDS = ("rate", "npv_tl", "npv_usd", "upfront")
FX_KINDS = ("outright", "points", "npv_tl", "npv_usd")
NPV_KINDS = ("npv_tl", "npv_usd", "upfront")
KIND_TEXT = {"rate": "Faiz", "outright": "Outright", "points": "Puan", "npv_tl": "NPV TL", "npv_usd": "NPV $",
             "upfront": "Peşin bp"}
#: the Toplu box: the lines priced (the rest are counted, not priced) and the text kept, at most
BULK_LINES, BULK_CHARS = 100, 8000

# where the TRY workbook keeps what the curves do not hold (1-based rows / columns)
#: the EURTRY spot date (Forward!K2: T+2 on TRY + EUR)
EUR_SPOT = ("Forward", 2, 11)
#: the USDTRY TL turn into $ with (OIS_MAIN!D2: the blotter's OIS sizing) and the lot a nominal is rounded to (H2)
USDTRY_RATE, LOT = ("OIS_MAIN", 2, 4), ("OIS_MAIN", 2, 8)
#: the forwards' spots: USDTRY the broken-date block's (MASA!H2, the desk's source mid - the block's N171 untyped);
#: EURTRY the Forward sheet's cross table bid / ask (F198 / G198), Bloomberg's mid (G2) without them
USD_SPOT, EUR_BID, EUR_ASK, EUR_MID = ("MASA", 2, 8), ("Forward", 198, 6), ("Forward", 198, 7), ("Forward", 2, 7)
#: the USD and EUR OIS curves of the Forward sheet (rows 7 … 26): days (U / AA), mid % (X / AD)
RATE_ROWS, USD_DAY, USD_MID, EUR_DAY, EUR_MID_COL = (7, 26), 21, 24, 27, 30
#: Motor's bootstrap nodes: E months, C days (rows 88 … 130); the quotes' copy it reads (A months, B rate)
NODE_MONTH, NODE_DAY = pk.BOOT_MONTH, pk.BOOT_DAY


class PricingError(ValueError):
    """What the page says of inputs it cannot price (Turkish)."""


def _num(v: Any) -> Optional[float]:
    return float(v) if type(v) in (float, int) and v == v else None


# ================================================================================================== the calendar
def is_business(serial: float, holidays: FrozenSet[float]) -> bool:
    """A week day not in ``holidays`` (serials; serial % 7: 0 Saturday, 1 Sunday)."""
    return int(serial) % 7 > 1 and serial not in holidays


def roll(serial: float, holidays: FrozenSet[float]) -> float:
    """The first business day from ``serial`` on (WORKDAY(x − 1, 1, holidays))."""
    d = float(int(serial))
    while not is_business(d, holidays):
        d += 1.0
    return d


def edate(serial: float, months: int) -> float:
    """Excel's EDATE."""
    return date_to_serial(add_months(serial_to_date(serial), int(months)))


def tenor_date(anchor: float, months: int, holidays: FrozenSet[float]) -> float:
    """The workbook's own rule for a tenor: WORKDAY(EDATE(anchor, months) − 1, 1, holidays)."""
    return roll(edate(anchor, months), holidays)


# ================================================================================================== what is typed
_TENOR = re.compile(r"^(?:(\d{1,3})\s*(?:y|yil|year|years))?\s*(?:(\d{1,4})\s*(?:m|a|ay|month|months))?$")
_WEEKS = re.compile(r"^(\d{1,2})\s*(?:w|h|hafta|week|weeks)$")
_PAIR = re.compile(r"^(.+?)\s*[x×*]\s*(.+)$")


def parse_when(text: Any) -> Optional[Tuple[str, float]]:
    """A start or a maturity as typed: ``("spot", 0)`` - empty, "spot" -, ``("m", months)`` - "1Y", "18M", "2Y3M", "3A",
    "1 yıl 6 ay", a bare "12" (an FRA's months) -, ``("w", weeks)`` - "2W", "2H" - or ``("d", serial)`` - a date
    ("04.05.2028", "2028-05-04", "4 May 2028"); ``None`` when it is none of them."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return ("m", float(int(text))) if float(text) == int(text) and 0 < text < 1000 else None
    s = " ".join(_fold(str(text or "")).split())
    if s in ("", "spot", "s", "0"):
        return ("spot", 0.0)
    if s.isdigit():
        return ("m", float(int(s))) if 0 < int(s) < 1000 else None
    m = _WEEKS.match(s)
    if m:
        return ("w", float(int(m.group(1)))) if int(m.group(1)) > 0 else None
    m = _TENOR.match(s.replace(" ", ""))
    if m and (m.group(1) or m.group(2)):
        months = int(m.group(1) or 0) * 12 + int(m.group(2) or 0)
        return ("m", float(months)) if 0 < months < 1000 else None
    d = parse_date(str(text))
    return ("d", d) if d is not None else None


def split_pair(text: Any) -> Optional[Tuple[str, str]]:
    """An FRA typed in one box: "12x15", "1Y×15M", "3 x 6" -> ("12", "15"); ``None`` otherwise."""
    m = _PAIR.match(" ".join(str(text or "").split()))
    if not m or parse_when(m.group(1)) is None or parse_when(m.group(2)) is None:
        return None
    return m.group(1).strip(), m.group(2).strip()


def when_label(when: Tuple[str, float]) -> str:
    """How a start / maturity is named: "Spot", "2Y3M", "18M", "2W", "04.05.2028"."""
    kind, x = when
    if kind == "spot":
        return "Spot"
    if kind == "w":
        return "%dW" % x
    if kind == "d":
        return serial_to_date(x).strftime("%d.%m.%Y")
    m = int(x)
    if m < 12 or (m < 24 and m % 12):
        return "%dM" % m
    return ("%dY" % (m // 12)) + ("%dM" % (m % 12) if m % 12 else "")


def resolve(when: Tuple[str, float], anchor: float, holidays: FrozenSet[float]) -> float:
    """The date (serial) of a start / maturity counted from ``anchor`` (the curve's spot), on a business day."""
    kind, x = when
    if kind == "spot":
        return anchor
    if kind == "m":
        return tenor_date(anchor, int(x), holidays)
    if kind == "w":
        return roll(anchor + 7.0 * x, holidays)
    return roll(x, holidays)


def coupons(start: float, end: Tuple[str, float], anchor: float, step: int, holidays: FrozenSet[float]) -> List[float]:
    """The payment dates (serials) of a swap from ``start`` to the maturity ``end`` paying every ``step`` months, counted
    back from the maturity - the short period first.  A tenor (months from ``anchor``): the k-th payment back is the
    tenor date of (months − k·step) from the anchor, so a quoted tenor from the spot falls on the workbook's own calendar
    (Motor's quarters, the XCCY years); a date: k·step months back from it (MASA's helper:
    ``WORKDAY(EDATE(T, −3k) − 1, 1, Motor!A361:A523)``); a number of weeks: one payment.  Only payments after ``start``;
    the first period runs from ``start``."""
    kind, x = end
    last = resolve(end, anchor, holidays)
    if kind not in ("m", "d"):
        return [last] if last > start else []
    out: List[float] = []
    for k in range(0, 2000):
        if kind == "m":
            if x - k * step <= 0:
                break
            d = tenor_date(anchor, int(x) - k * step, holidays)
        else:
            d = last if k == 0 else roll(edate(x, -k * step), holidays)
        if d <= start:
            break
        out.append(d)
    return sorted(set(out))


# ================================================================================================== the workbook
class Market(NamedTuple):
    """What pricing needs beside the curves, read from the TRY workbook (:func:`read`)."""
    ois_spot: float                                  # OIS_MAIN!B2: the OIS curve's day 0
    fx_spot: float                                   # Forward!I2: the USDTRY spot date, the offshore curve's day 0
    eur_spot: Optional[float]                        # Forward!K2: the EURTRY spot date
    holidays: Dict[str, FrozenSet[float]]            # "TRY" (Motor's), "USDTRY", "EURTRY" (EK_TATIL's joint lists)
    ois_quotes: Tuple[Tuple[float, float], ...]      # Motor!A306:B321: (months, rate) - what Motor bootstraps
    nodes: Tuple[Tuple[float, float], ...]           # Motor!E88:E130 / C88:C130: (months, days) of its nodes
    usdtry: Optional[float]                          # OIS_MAIN!D2: TL → $
    lot: float                                       # OIS_MAIN!H2: a nominal sized from a DV01 is rounded to it
    spots: Dict[str, Optional[float]]                # the forwards' spot rates: "USDTRY", "EURTRY"
    ccy_rates: Dict[str, Tuple[Tuple[float, float], ...]]   # "USD", "EUR": (days, mid %) of the Forward sheet


def read(get: Callable[[str, int, int], Any]) -> Market:
    """:class:`Market` from the TRY workbook, ``get(sheet, row, column)`` reading its cells (a user's calculation on
    Bootstrap: their own inputs count).  A sheet that is not there (EK_TATIL: the TRY list for the FX calendars) is left
    out; a spot date missing raises :class:`PricingError`."""
    def at(sheet: str, r: int, c: int) -> Optional[float]:
        try:
            return _num(to_num(get(sheet, r, c)))
        except KeyError:
            return None

    ois_spot, fx_spot = at(*pk.OIS_SPOT), at(*pk.FX_SPOT)
    if ois_spot is None or fx_spot is None:
        raise PricingError("spot tarihi yok (OIS_MAIN!B2 / Forward!I2)")
    r1, r2 = ex.TRY_HOLIDAY_ROWS
    hol_try = frozenset(d for d in (at("Motor", r, 1) for r in range(r1, r2 + 1)) if d)
    joint = {}
    for pair, cols in (("USDTRY", (2, 3)), ("EURTRY", (3, 4))):
        days = {d for r in range(ex.HOL_FIRST, ex.HOL_LAST + 1) for d in (at(ex.HOL_SHEET, r, c) for c in cols) if d}
        joint[pair] = frozenset(days) if days else hol_try        # (a workbook without the lists: the TRY one)
    quotes = tuple((m, r) for m, r in ((at("Motor", r, pk.QUOTE_MONTH), at("Motor", r, pk.QUOTE_RATE))
                                       for r in range(pk.QUOTE_ROWS[0], pk.QUOTE_ROWS[1] + 1)) if m is not None and r is not None)
    nodes = tuple((m, d) for m, d in ((at("Motor", r, NODE_MONTH), at("Motor", r, NODE_DAY))
                                      for r in range(pk.BOOT_ROWS[0], pk.BOOT_ROWS[1] + 1)) if m is not None and d is not None)
    lot = at(*LOT)
    bid, ask = at(*EUR_BID), at(*EUR_ASK)
    eur = (bid + ask) / 2.0 if bid and ask else at(*EUR_MID)

    def table(day_col: int, mid_col: int) -> Tuple[Tuple[float, float], ...]:
        rows = ((at("Forward", r, day_col), at("Forward", r, mid_col)) for r in range(RATE_ROWS[0], RATE_ROWS[1] + 1))
        return tuple((d, x) for d, x in rows if d is not None and x is not None)

    return Market(ois_spot=ois_spot, fx_spot=fx_spot, eur_spot=at(*EUR_SPOT),
                  holidays={"TRY": hol_try, "USDTRY": joint["USDTRY"], "EURTRY": joint["EURTRY"]},
                  ois_quotes=quotes, nodes=nodes, usdtry=at(*USDTRY_RATE), lot=lot if lot and lot > 0 else 1.0,
                  spots={"USDTRY": at(*USD_SPOT), "EURTRY": eur},
                  ccy_rates={"USD": table(USD_DAY, USD_MID), "EUR": table(EUR_DAY, EUR_MID_COL)})


def ccy_rate(days: float, table: Sequence[Tuple[float, float]]) -> Optional[float]:
    """The USD (EUR) OIS rate at ``days`` as the broken-date block reads the Forward sheet's curve (``MASA!BL178``):
    linear in days between its tenors, flat before the first and after the last; a decimal."""
    pts = sorted(table)
    if not pts:
        return None
    if days <= pts[0][0]:
        return pts[0][1] / 100.0
    if days >= pts[-1][0]:
        return pts[-1][1] / 100.0
    i = bisect.bisect_right([d for d, _ in pts], days) - 1
    (d0, r0), (d1, r1) = pts[i], pts[i + 1]
    return (r0 + (days - d0) * (r1 - r0) / (d1 - d0)) / 100.0


# ================================================================================================== the curves again
def motor_curve(quotes: Sequence[Tuple[float, float]], nodes: Sequence[Tuple[float, float]]) -> pk.LogLinear:
    """Motor's bootstrap (``Motor!C88:I130``) from the OIS quotes ``(months, rate)`` (``Motor!A306:B321``) at its nodes
    ``(months, days)``: each node's par the quotes linear in months, flat beyond the first and the last (``F89:F130``);
    up to 3M one period, DF = 1 / (1 + F·τ) (τ = days / 365); from 6M quarterly from the 3M node on, DF = (1 − F·H) /
    (1 + F·τ), H the annuity so far (``H91 = τ·DF`` of the 3M node, then + τ·DF); ln DF linear in days between the nodes
    (``BOOT_GUN`` / ``BOOT_LNDF``).  A quote bumped is Motor's own bucket bump (``Motor!T86``: the quote +1 bp, linear in
    months again - the "tent" between its neighbours)."""
    qs = sorted((float(m), float(r)) for m, r in quotes)
    if not qs:
        raise ValueError("OIS kotası yok")
    qm = [m for m, _ in qs]

    def par(m: float) -> float:
        if m <= qm[0]:
            return qs[0][1]
        if m >= qm[-1]:
            return qs[-1][1]
        i = bisect.bisect_right(qm, m) - 1
        (m0, r0), (m1, r1) = qs[i], qs[i + 1]
        return r0 + (r1 - r0) * (m - m0) / (m1 - m0)

    days, lndf = [0.0], [0.0]
    h = 0.0
    prev = 0.0
    for m, d in sorted((float(m), float(d)) for m, d in nodes if m > 0):
        f = par(m)
        if m <= 3.0:
            tau = d / 365.0
            g = 1.0 / (1.0 + f * tau)
            h = tau * g
        else:
            tau = (d - prev) / 365.0
            g = (1.0 - f * h) / (1.0 + f * tau)
            h += tau * g
        if not g > 0.0:
            raise ValueError("bootstrap negatif iskonto faktörü verdi (%g ay)" % m)
        days.append(d)
        lndf.append(math.log(g))
        prev = d
    return pk.LogLinear(days, lndf)


def quote_curve(quotes: Sequence[pk.Quote]) -> pk.LogLinear:
    """The offshore curve from its quotes (``Forward!AJ123:AN143``, :func:`tto.ppkcurve.offshore_quotes`): a node at each
    quote's maturity - a one period quote (TRYI, the XCCY 1Y) ln DF = −ln(1 + r·τ); a par swap (XCCY n: annual ACT/360,
    its earlier coupons on earlier nodes) DF = (1 − r·Σ τ·DF) / (1 + r·τ_last) (``Forward!G126:G134``); ln DF linear
    in days, the last segment going on."""
    days, lndf = [0.0], [0.0]
    for q in sorted(quotes, key=lambda x: x.end):
        if len(q.pays) == 1:
            g = 1.0 / (1.0 + q.rate * q.accruals[0])
        else:
            so_far = pk.LogLinear(days, lndf) if len(days) > 1 else None
            ann = sum(a * (so_far.df(t) if so_far is not None else 1.0) for t, a in zip(q.pays[:-1], q.accruals[:-1]))
            g = (1.0 - q.rate * ann) / (1.0 + q.rate * q.accruals[-1])
        if not g > 0.0 or q.end <= days[-1]:
            break
        days.append(q.end)
        lndf.append(math.log(g))
    return pk.LogLinear(days, lndf)


def _par_with(shape: pk.StepCurve, shifts: List[Tuple[float, float]], q: pk.Quote, add: float) -> float:
    """``q``'s par on ``shape`` with ``shifts`` and ``add`` on its own stretch (read no further than its maturity)."""
    return pk.par(shape.with_shifts(shifts + [(q.end, add)], q.end), q.pays, q.accruals)


def slopes(shape: pk.StepCurve, quotes: Sequence[pk.Quote], base: pk.StepCurve) -> List[float]:
    """How each quote's par moves with its own stretch's shift on ``base`` (per unit of shift, in maturity order): the
    first step of :func:`recalibrated` - a 1 bp bump moves every shift a little, the par is nearly linear in it."""
    qs = sorted(quotes, key=lambda q: q.end)
    out = []
    for k, q in enumerate(qs):
        a = base.shifts[k][1]
        out.append((_par_with(shape, list(base.shifts[:k]), q, a + BP) - _par_with(shape, list(base.shifts[:k]), q, a)) / BP)
    return out


def recalibrated(shape: pk.StepCurve, quotes: Sequence[pk.Quote], base: pk.StepCurve, j: int, bump: float = BP,
                 slope: Optional[Sequence[float]] = None) -> pk.StepCurve:
    """:func:`tto.ppkcurve.calibrate`'s curve of ``quotes`` (``base``) with the ``j``-th of them (in maturity order) ``bump``
    higher: the shifts of the stretches before it as they are - a quote depends only on its own stretch and the ones before
    it - and the rest solved again, each from its shift in ``base`` (a Newton step on :func:`slopes` first), by
    calibrate's secant until the quote comes back within :data:`tto.ppkcurve.TOLERANCE` (1e-12: 1e-8 bp)."""
    qs = sorted(quotes, key=lambda q: q.end)
    shifts = list(base.shifts[:j])
    for k in range(j, len(qs)):
        q = qs[k]
        rate = q.rate + (bump if k == j else 0.0)
        a0 = base.shifts[k][1]
        f0 = _par_with(shape, shifts, q, a0) - rate
        if abs(f0) <= pk.TOLERANCE * 1e-3:
            shifts.append((q.end, a0))
            continue
        s = slope[k] if slope else 0.0
        a1 = a0 - f0 / s if s else a0 + bump
        f1 = _par_with(shape, shifts, q, a1) - rate
        for _ in range(pk.STEPS):
            if abs(f1) <= pk.TOLERANCE or f1 == f0:
                break
            a0, a1 = a1, a1 - f1 * (a1 - a0) / (f1 - f0)
            f0, f1 = f1, _par_with(shape, shifts, q, a1) - rate
        if not abs(f1) <= pk.TOLERANCE:
            raise ValueError("%s kotasına oturulamadı" % q.name)
        shifts.append((q.end, a1))
    return shape.with_shifts(shifts)


#: bump sets kept by what they are made of (:class:`Curves` ``kept``): a market tick elsewhere makes none again
KEPT = 8


def _quotes_key(quotes: Sequence[pk.Quote]) -> Tuple:
    return tuple((q.name, q.rate, q.pays, q.accruals) for q in quotes)


def _shape_key(shape: Optional[pk.StepCurve]) -> Tuple:
    if shape is None:
        return ()
    return tuple(shape.knots), tuple(shape.rates), tuple(shape.pcum) if shape.pcum else None


class Curves(object):
    """The curves of a calculation both ways (``cv``: :func:`tto.ppkcurve.read`'s with the service's ``off_boot``) and
    ``mk`` (:func:`read`) - and each with every pillar bumped, made when first asked for.  ``kept`` (the service's, any
    dict): the bump sets by what they are made of - the quotes, Motor's nodes, MPC ima, the FX spot's shift - so a refresh
    of the page after a tick of anything else makes none again.

    The mids are read off the curves as the pages have them (Bootstrap: Motor's ``BOOT_GUN`` / ``BOOT_LNDF`` and the
    offshore names; PPK basamak: ppkcurve's); a DV01 is the difference between a bumped curve and the same method's base
    built the same way (Bootstrap: :func:`motor_curve` / :func:`quote_curve` from the quotes - the sheet's curve to the
    last digit -, PPK: the calibrated curve and :func:`recalibrated`).  A curve whose desk's list of points differs from
    the default (Ayarlar → Eğri noktaları: ``cv["ois_nodes"]`` / ``cv["off_listed"]``) has the list's points as its
    pillars - those that carry a rate and are on - and its Bootstrap bumps built the list's way
    (:func:`tto.ppkcurve.list_ois_curve` / :func:`tto.ppkcurve.bootstrap`)."""

    def __init__(self, cv: Dict[str, Any], mk: Market, kept: Optional[Dict[Tuple, Any]] = None):
        self.cv, self.mk = cv, mk
        self.kept = kept if kept is not None else {}
        self._made: Dict[Tuple[str, str], Optional[Tuple[Any, List[Tuple[str, Any]]]]] = {}
        self.errors: List[str] = list(cv.get("errors") or [])

    def curve(self, family: str, method: str) -> Any:
        """The curve the mid is read on (``None``: it could not be made)."""
        key = ("boot" if method == BOOT else "ppk") if family == ON else ("off_boot" if method == BOOT else "off_ppk")
        return self.cv.get(key)

    def pillars(self, family: str) -> List[Tuple[str, float]]:
        """The pillars of a family, in maturity order: (name, its maturity in days) - the quotes the curve is built from
        (the desk's list of points when it differs from the default: its points that carry a rate and are on - no
        computed point, no PPK meeting)."""
        if family == ON and self.cv.get("ois_nodes") is not None:
            return [(q.name, q.end) for q in sorted(self.cv.get("quotes") or [], key=lambda q: q.end)]
        if family == ON:
            node = {int(round(m)): d for m, d in self.mk.nodes}
            return [(pk.tenor_label(int(round(m))), node.get(int(round(m)), m * 30.4375)) for m, _ in sorted(self.mk.ois_quotes)]
        return [(q.name, q.end) for q in sorted(self.cv.get("off_quotes") or [], key=lambda q: q.end)]

    def bumped(self, family: str, method: str) -> Optional[Tuple[Any, List[Tuple[str, Any]]]]:
        """``(base, [(pillar, curve with that pillar's quote +1 bp)])`` of a family on a method; ``None`` when it cannot
        be made (no quotes, no PPK curve - :attr:`errors` says why)."""
        key = (family, method)
        if key not in self._made:
            made = self.kept.get(self._source(family, method))
            if made is None:
                try:
                    made = self._bump(family, method)
                except ValueError as exc:
                    self.errors.append("%s %s kova kaydırması: %s" % ("OIS" if family == ON else "offshore",
                                                                     METHOD_TEXT[method], exc))
                    made = None
                if made is not None:
                    self.kept[self._source(family, method)] = made
                    while len(self.kept) > KEPT:
                        self.kept.pop(next(iter(self.kept)))
            self._made[key] = made
        return self._made[key]

    def _source(self, family: str, method: str) -> Tuple:
        """What a family's bump set on a method is made of."""
        cv, mk = self.cv, self.mk
        quotes = _quotes_key(sorted((cv.get("quotes") if family == ON else cv.get("off_quotes")) or [], key=lambda q: q.end))
        if family == ON and method == BOOT:
            if cv.get("ois_nodes") is not None:                  # (the desk's list: its points on Motor's nodes)
                return family, method, "list", quotes, cv["ois_nodes"]
            return family, method, mk.ois_quotes, mk.nodes
        if method == BOOT:
            return (family, method, quotes) + (("list",) if family == OFF and cv.get("off_listed") else ())
        return family, method, quotes, _shape_key(cv.get("shape")), cv.get("fx_shift") if family == OFF else None

    def _bump(self, family: str, method: str) -> Optional[Tuple[Any, List[Tuple[str, Any]]]]:
        cv, mk = self.cv, self.mk
        if family == ON and method == BOOT and cv.get("ois_nodes") is not None:
            # the desk's list of points (tto/curvepoints.py): each point +1 bp, the list's Bootstrap built again
            # (ppkcurve.list_ois_curve: Motor's method on the points, an off-grid point its own node)
            nodes = cv["ois_nodes"]
            qs = sorted(cv.get("quotes") or [], key=lambda q: q.end)
            if not qs:
                return None
            build = lambda x: pk.list_ois_curve(x, nodes)[1]          # noqa: E731
            return build(qs), [(q.name, build(qs[:i] + [q._replace(rate=q.rate + BP)] + qs[i + 1:])) for i, q in enumerate(qs)]
        if family == ON and method == BOOT:
            qs = sorted(mk.ois_quotes)
            if not qs or not mk.nodes:
                return None
            base = motor_curve(qs, mk.nodes)
            return base, [(pk.tenor_label(int(round(m))), motor_curve(qs[:i] + [(m, r + BP)] + qs[i + 1:], mk.nodes))
                          for i, (m, r) in enumerate(qs)]
        quotes = sorted((cv.get("quotes") if family == ON else cv.get("off_quotes")) or [], key=lambda q: q.end)
        if not quotes:
            return None
        if method == BOOT:
            # (the desk's offshore list: a node at every point, a coupon between nodes read off the curve - ppkcurve's)
            build = pk.bootstrap if family == OFF and cv.get("off_listed") else quote_curve
            base = build(quotes)
            return base, [(q.name, build(quotes[:i] + [q._replace(rate=q.rate + BP)] + quotes[i + 1:]))
                          for i, q in enumerate(quotes)]
        base = cv.get("ppk") if family == ON else cv.get("off_ppk")
        shape = cv.get("shape")
        if base is None or shape is None:
            return None
        if family == OFF:
            if cv.get("fx_shift") is None:
                return None
            shape = shape.rebased(cv["fx_shift"])
        slope = slopes(shape, quotes, base)
        return base, [(q.name, recalibrated(shape, quotes, base, i, slope=slope)) for i, q in enumerate(quotes)]


# ================================================================================================== the instruments
class Leg(NamedTuple):
    """A period of a swap: its dates (serials), its days and accrual."""
    start: float
    pay: float
    days: float
    tau: float


class Deal(NamedTuple):
    """An instrument as priced: ``family`` the curve it is on (its day 0 ``spot``); a swap its ``legs`` (``start`` /
    ``end`` serials); an FX forward its value date ``end``, the pair's spot date ``start``, spot rate, the currency's
    rate and the days between."""
    asset: str
    pair: str
    family: str
    spot: float
    start: float
    end: float
    legs: Tuple[Leg, ...]
    basis: float
    fx_rate: Optional[float]
    ccy_rate: Optional[float]
    label: str


def swap_deal(asset: str, start_when: Tuple[str, float], end_when: Tuple[str, float], mk: Market) -> Deal:
    """An OIS / FRA (OIS spot, quarterly, ACT/365) or XCCY (FX spot, annual, ACT/360) between two typed dates."""
    if asset == XCCY:
        spot, step, basis = mk.fx_spot, 12, 360.0
    else:
        spot, step, basis = mk.ois_spot, 3, 365.0
    hol = mk.holidays["TRY"]
    start = resolve(start_when, spot, hol)
    if start < spot:
        raise PricingError("başlangıç spot'tan (%s) önce olamaz" % serial_to_date(spot).strftime("%d.%m.%Y"))
    if end_when[0] == "spot":
        raise PricingError("vade yazın (1Y, 18M, 2Y3M ya da tarih)")
    end = resolve(end_when, spot, hol)
    if end <= start:
        raise PricingError("vade başlangıçtan sonra olmalı")
    pays = coupons(start, end_when, spot, step, hol)
    if not pays:
        raise PricingError("vade başlangıçtan sonra olmalı")
    legs = []
    prev = start
    for d in pays:
        legs.append(Leg(prev, d, d - prev, (d - prev) / basis))
        prev = d
    if asset == FRA:
        if start_when[0] == "spot":
            raise PricingError("FRA'nın başlangıcı spot'tan sonra olmalı (12x15 gibi; spot başlangıç: TRY OIS)")
        label = "FRA %sx%s" % (_fra_part(start_when), _fra_part(end_when))
    else:
        name = "TRY OIS" if asset == OIS else "XCCY"
        label = name + " " + ("" if start_when[0] == "spot" else when_label(start_when) + " × ") + when_label(end_when)
    return Deal(asset, "", OFF if asset == XCCY else ON, spot, start, pays[-1], tuple(legs), basis, None, None, label)


def _fra_part(when: Tuple[str, float]) -> str:
    return "%d" % when[1] if when[0] == "m" else when_label(when)


def fx_deal(pair: str, end_when: Tuple[str, float], mk: Market) -> Deal:
    """An FX forward of ``pair`` to a typed value date: a tenor from the pair's spot date on its joint calendar (the
    Forward sheet's rule; USDTRY ``WORKDAY(EDATE(Forward!I2, n) − 1, 1, EK_TATIL!B:C)``, MASA!C171's)."""
    pair_spot = mk.fx_spot if pair == "USDTRY" else mk.eur_spot
    if pair_spot is None:
        raise PricingError("%s spot tarihi yok" % pair)
    if end_when[0] == "spot":
        raise PricingError("valör yazın (1Y, 18M ya da tarih)")
    end = resolve(end_when, pair_spot, mk.holidays[pair])
    if end <= pair_spot:
        raise PricingError("valör spot tarihinden (%s) sonra olmalı" % serial_to_date(pair_spot).strftime("%d.%m.%Y"))
    s = mk.spots.get(pair)
    if not s:
        raise PricingError("%s spotu yok" % pair)
    r = ccy_rate(end - pair_spot, mk.ccy_rates["USD" if pair == "USDTRY" else "EUR"])
    if r is None:
        raise PricingError("%s faiz eğrisi yok (Forward)" % ("USD" if pair == "USDTRY" else "EUR"))
    days = end - pair_spot
    return Deal(FX, pair, OFF, mk.fx_spot, pair_spot, end, (Leg(pair_spot, end, days, days / 360.0),), 360.0, s, r,
                "%s %s" % (pair, when_label(end_when)))


def annuity(deal: Deal, curve: Any) -> float:
    """Σ τ·DF of a swap's payments on ``curve``."""
    sp = deal.spot
    return sum(lg.tau * curve.df(lg.pay - sp) for lg in deal.legs)


def mid(deal: Deal, curve: Any) -> float:
    """A swap's par rate, (DF(start) − DF(end)) / Σ τ·DF (:func:`tto.ppkcurve.par`); an FX forward's outright."""
    sp = deal.spot
    if deal.asset == FX:
        return forward(deal, curve)
    return (curve.df(deal.start - sp) - curve.df(deal.end - sp)) / annuity(deal, curve)


def forward(deal: Deal, curve: Any) -> float:
    """F = S · DF(spot date) / DF(value date) / (1 + r·d/360) on the offshore curve (days from the USDTRY spot)."""
    sp = deal.spot
    g = 1.0 + deal.ccy_rate * (deal.end - deal.start) / 360.0
    return deal.fx_rate * curve.df(deal.start - sp) / curve.df(deal.end - sp) / g


def value(deal: Deal, curve: Any, side: int, size: float, level: float) -> float:
    """The position's value (TL, as of the curve's spot) at ``level`` - a swap's fixed rate, an FX forward's outright -
    for ``side`` +1 (PAY the fixed rate / AL the currency) or −1: + in the holder's favour.  A swap: side · N ·
    ((DF(start) − DF(end)) − K·Σ τ·DF); an FX forward: side · A · (F − K) · DF(value date)."""
    sp = deal.spot
    if deal.asset == FX:
        return side * size * (forward(deal, curve) - level) * curve.df(deal.end - sp)
    return side * size * ((curve.df(deal.start - sp) - curve.df(deal.end - sp)) - level * annuity(deal, curve))


def level_for(deal: Deal, curve: Any, side: int, size: float, npv: float) -> float:
    """:func:`value`'s inverse: the level - a swap's fixed rate, an FX forward's outright - at which the position (``side``,
    ``size``) is worth ``npv`` (TL, + in the holder's favour) on ``curve``.  A swap: K = ((DF(start) − DF(end)) − NPV /
    (side · N)) / Σ τ·DF; an FX forward: K = F − NPV / (side · A · DF(value date)) - the same terms :func:`value` reads, so
    ``value(level_for(v)) = v`` to the last digits."""
    sp = deal.spot
    if deal.asset == FX:
        return forward(deal, curve) - npv / (side * size * curve.df(deal.end - sp))
    return ((curve.df(deal.start - sp) - curve.df(deal.end - sp)) - npv / (side * size)) / annuity(deal, curve)


def npv_of(kind: str, x: float, size: float, usdtry: float) -> float:
    """The NPV in TL an NPV or upfront typed stands for (``kind``, :data:`NPV_KINDS`): TL as it is; $ at USDTRY
    (``OIS_MAIN!D2``, what the page turns its NPV into $ with); an upfront in bp of the nominal, NPV = N · bp / 10 000 -
    + in the trader's favour, as the NPV."""
    if kind == "npv_usd":
        return x * usdtry
    if kind == "upfront":
        return size * x / 10000.0
    return x


def unit_dv01(deal: Deal, curve: Any) -> float:
    """TL per bp of one unit of size on ``curve`` - what a DV01 is sized on: a swap's annuity · 1 bp (OIS_MAIN's rule,
    the blotter's), an FX forward's F · d/360 · DF_simple · DF (the forward's change for 1 bp on the TRY simple rate,
    valued today)."""
    if deal.asset == FX:
        sp = deal.spot
        f = forward(deal, curve)
        simple = curve.df(deal.end - sp) / curve.df(deal.start - sp)
        return f * (deal.end - deal.start) / 360.0 * simple * curve.df(deal.end - sp) * BP
    return annuity(deal, curve) * BP


#: a nominal sized from a DV01 is rounded to the lot as OIS_MAIN (and Günlük İşlemler) round it: half away from zero
round_half_away = _round_half_away


# ================================================================================================== the inputs
#: what the page starts with, per asset (each user's own are kept per asset: switching back finds them)
DEFAULTS: Dict[str, Dict[str, str]] = {
    OIS: {"start": "", "end": "1Y", "side": "PAY", "size_kind": "dv01", "size": "1000", "price": "", "price_kind": "rate",
          "bulk": ""},
    FRA: {"start": "12", "end": "15", "side": "PAY", "size_kind": "dv01", "size": "1000", "price": "", "price_kind": "rate",
          "bulk": ""},
    XCCY: {"start": "", "end": "2Y3M", "side": "RECEIVE", "size_kind": "dv01", "size": "1000", "price": "",
           "price_kind": "rate", "bulk": ""},
    FX: {"start": "", "end": "18M", "side": "AL", "size_kind": "amount", "size": "10m", "price": "", "price_kind": "outright",
         "pair": "USDTRY", "bulk": ""},
}
TEXT_KEYS = ("start", "end", "size", "price")


def clean_inputs(raw: Any, kept: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A user's inputs as stored: ``{"asset", "by": {asset: {start, end, side, size_kind, size, price, price_kind,
    pair, bulk}}}`` - what was typed (texts, read when priced) over what was kept (``kept``) over the defaults.  A field
    of ``raw`` is the asset's (``raw["asset"]``, else the one kept).  Inputs kept before a field was there take its
    default: a price kept before 24.11.2026 is a rate (an FX forward's: as kept), the Toplu box empty."""
    out = {"asset": OIS, "by": {a: dict(DEFAULTS[a]) for a in ASSETS}}
    for src in (kept or {}, raw if isinstance(raw, dict) else {}):
        if not isinstance(src, dict):
            continue
        if src.get("asset") in ASSETS:
            out["asset"] = src["asset"]
        for a, fields in (src.get("by") or {}).items():
            if a in ASSETS and isinstance(fields, dict):
                _merge(out["by"][a], fields, a)
    if isinstance(raw, dict):
        _merge(out["by"][out["asset"]], raw, out["asset"])
    return out


def _merge(into: Dict[str, Any], fields: Dict[str, Any], asset: str) -> None:
    for k in TEXT_KEYS:
        if k in fields and fields[k] is not None:
            into[k] = str(fields[k]).strip()[:40]
    for k in ("start", "end"):
        both = split_pair(into.get(k)) if asset != FX else None
        if both is not None:                      # (an FRA typed in one box, "12x15": its two boxes)
            into["start"], into["end"] = both
    side = str(fields.get("side") or "").upper()
    if side in (FX_SIDES if asset == FX else RATE_SIDES):
        into["side"] = side
    kind = str(fields.get("size_kind") or "")
    if kind in (("amount", "dv01") if asset == FX else ("nominal", "dv01")):
        into["size_kind"] = kind
    if str(fields.get("price_kind") or "") in (FX_KINDS if asset == FX else RATE_KINDS):
        into["price_kind"] = str(fields["price_kind"])
    if fields.get("bulk") is not None:
        into["bulk"] = bulk_text(fields["bulk"])
    if asset == FX:
        if str(fields.get("pair") or "").upper() in PAIRS:
            into["pair"] = str(fields["pair"]).upper()


def bulk_text(raw: Any) -> str:
    """The Toplu box's text as kept: its lines as typed or pasted (Windows line ends, blanks at their ends and empty
    lines at the end off), at most :data:`BULK_CHARS` characters."""
    lines = [s.rstrip() for s in str(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)[:BULK_CHARS]


def price_kind(asset: str, f: Dict[str, Any]) -> str:
    """What the price box of ``asset`` holds (:data:`RATE_KINDS` / :data:`FX_KINDS`); none kept: a rate, an outright."""
    kinds = FX_KINDS if asset == FX else RATE_KINDS
    k = f.get("price_kind")
    return k if k in kinds else kinds[0]


def _rate(text: str) -> Optional[float]:
    """A rate as typed: "35,10" or "%35,10" is 35,10 % (a number of 1 or more without "%": per cent), "0,351" 35,1 %."""
    x = parse_number(text, prefer_decimal=True)
    if x is not None and "%" not in text and abs(x) >= 1.0:
        x /= 100.0
    return x


# ================================================================================================== pricing
def instrument(asset: str, f: Dict[str, Any], mk: Market) -> Deal:
    """The page's instrument from what was typed (``f``: the asset's inputs) - :class:`PricingError` for what does not
    read."""
    if asset == FX:
        end_when = parse_when(f["end"])
        if end_when is None:
            raise PricingError("valör okunamadı: %r (1Y, 18M, 2Y3M ya da gg.aa.yyyy)" % f["end"])
        return fx_deal(f["pair"], end_when, mk)
    start_text, end_text = f["start"], f["end"]
    both = split_pair(start_text) if asset == FRA else None
    if both is not None:
        start_text, end_text = both
    start_when, end_when = parse_when(start_text), parse_when(end_text)
    if start_when is None:
        raise PricingError("başlangıç okunamadı: %r (Spot, 1Y, 12, 18M ya da gg.aa.yyyy)" % start_text)
    if end_when is None:
        raise PricingError("vade okunamadı: %r (1Y, 18M, 2Y3M, 15 ya da gg.aa.yyyy)" % end_text)
    return swap_deal(asset, start_when, end_when, mk)


def read_price(kind: str, text: str, deal: Deal) -> Optional[float]:
    """The price typed, read in its kind (``None``: nothing typed): a swap's rate as a decimal ("35,10" is 35,10 %); an
    FX forward's outright, or the outright its points give (spot + points / 10 000); an NPV in TL or $ ("1.000.000",
    "-250k", "2,5m"); an upfront in bp of the nominal ("25", "-12,5"; "%0,5" of the nominal is 50 bp).
    :class:`PricingError` for what does not read."""
    text = text or ""
    if not text.strip():
        return None
    if kind in ("npv_tl", "npv_usd"):
        x = parse_amount(text.replace("−", "-").replace("–", "-"))
        if x is None:
            raise PricingError("NPV okunamadı: %r (1.000.000, -250k, 2,5m)" % text)
        return x
    if kind == "upfront":
        x = parse_number(text, prefer_decimal=True)
        if x is None:
            raise PricingError("peşin okunamadı: %r (bp: 25, -12,5; nominalin yüzdesi: %%0,5)" % text)
        return x * 10000.0 if "%" in text else x
    if deal.asset == FX:
        x = parse_number(text, prefer_decimal=True)
        if x is None:
            raise PricingError("fiyat okunamadı: %r" % text)
        level = deal.fx_rate + x / 10000.0 if kind == "points" else x
        if not level > 0:
            raise PricingError("forward kur pozitif olmalı")
        return level
    level = _rate(text)
    if level is None:
        raise PricingError("fiyat okunamadı: %r (35,10 = %%35,10)" % text)
    return level


def sized(deal: Deal, f: Dict[str, Any], mk: Market, unit: float, usdtry: float) -> Tuple[float, float, str]:
    """The position's size, ``(typed, size, rule)``: a nominal (an FX forward's amount in its currency) as typed, or one
    from a DV01 in $ on ``unit`` (:func:`unit_dv01` on the user's curve), rounded as ``rule`` says."""
    size_text = f.get("size") or ""
    typed = parse_amount(size_text) if size_text else None
    if typed is None or not typed > 0:
        raise PricingError("büyüklük okunamadı: %r (10m, 250k, 1.000)" % size_text if size_text else "büyüklük yazın")
    if f["size_kind"] != "dv01":
        return typed, typed, ""
    raw = typed * usdtry / unit
    if deal.asset == FX:
        size = round(raw / 1000.0) * 1000.0
        rule = "tutar = DV01 · USDTRY / (F · gün/360 · DF_basit · DF · 0,0001), 1.000'e yuvarlı"
    else:
        size = round_half_away(raw / mk.lot) * mk.lot
        rule = "nominal = DV01 · USDTRY / (annuity · 0,0001), %s TL'ye yuvarlı (OIS_MAIN'in kuralı)" % _int_text(mk.lot)
    if not size > 0:
        raise PricingError("DV01 bu vadede sıfır nominale yuvarlanıyor: daha büyük yazın")
    return typed, size, rule


def leveled(deal: Deal, kind: str, typed: Optional[float], side: int, size: float, base: Dict[str, Any], method: str,
            usdtry: float) -> Tuple[Optional[float], Optional[Dict[str, Optional[float]]]]:
    """The level the position is priced at, ``(level, implied)``: a rate / outright typed as it is (``implied`` None); an
    NPV or upfront typed: the level that prices to it on each curve (:func:`level_for`), the user's curve's (``method``)
    the level.  Nothing typed: ``(None, None)``."""
    if typed is None:
        return None, None
    if kind not in NPV_KINDS:
        return typed, None
    v = npv_of(kind, typed, size, usdtry)
    implied = {m: (level_for(deal, base[m], side, size, v) if base[m] is not None else None) for m in METHODS}
    level = implied[method]
    if deal.asset == FX and not (level is not None and level > 0):
        raise PricingError("bu NPV'yi veren forward kur pozitif değil (%s)" % (_fx_text(level) if level is not None else "-"))
    return level, implied


def _fx_text(x: float) -> str:
    return ("%.4f" % x).replace(".", ",")


def npv_block(deal: Deal, base: Dict[str, Any], side: int, size: float, level: float, mids: Dict[str, Optional[float]],
              usdtry: float, kind: str, typed: Optional[float], implied: Optional[Dict[str, Optional[float]]],
              method: str) -> Dict[str, Any]:
    """The position at ``level`` on each curve: its NPV in TL and $ (+ in the trader's favour), a swap's upfront (NPV /
    nominal, bp), the level's distance from each curve's mid - and, the level solved from an NPV or upfront typed
    (``implied``), what was typed and each curve's level for it (``from``)."""
    tl = {m: (value(deal, base[m], side, size, level) if base[m] is not None else None) for m in METHODS}
    scale = 10000.0
    out = {"level": level, "tl": tl, "usd": {m: (v / usdtry if v is not None else None) for m, v in tl.items()},
           "dist": {m: ((level - mids[m]) * scale if mids[m] is not None else None) for m in METHODS},
           "unit": "puan" if deal.asset == FX else "bp"}
    if deal.asset != FX:
        out["upfront"] = {m: (v / size * scale if v is not None else None) for m, v in tl.items()}
    if implied is not None:
        out["from"] = {"kind": kind, "text": KIND_TEXT[kind], "typed": typed, "method": method, "level": implied}
    return out


def price(inputs: Dict[str, Any], curves: Curves, method: str) -> Dict[str, Any]:
    """The page's numbers for the user's inputs (:func:`clean_inputs`) on ``curves``, ``method`` the user's own curve
    setting (shown first; the other beside).  :class:`PricingError` for inputs it cannot price."""
    mk = curves.mk
    asset = inputs["asset"]
    f = inputs["by"][asset]
    methods = [method] + [m for m in METHODS if m != method]
    deal = instrument(asset, f, mk)
    family = deal.family
    base = {m: curves.curve(family, m) for m in METHODS}
    if base[method] is None:
        if base[BOOT] is None:
            raise PricingError("eğri kurulamadı: %s" % ("; ".join(curves.errors) or "kota yok"))
        method = BOOT
        methods = [BOOT, PPK]
    mids = {m: (mid(deal, base[m]) if base[m] is not None else None) for m in METHODS}
    side = 1 if f["side"] in ("PAY", "AL") else -1
    usdtry = mk.usdtry
    if not usdtry:
        raise PricingError("USDTRY yok (OIS_MAIN!D2)")
    # the price typed, in its kind: a swap's rate, an FX forward's outright (or points on the spot) - or an NPV / upfront
    kind = price_kind(asset, f)
    typed_price = read_price(kind, f.get("price") or "", deal)
    # the size: a nominal (an FX forward's amount in its currency) or a DV01 in $ sized on the user's curve
    unit = unit_dv01(deal, base[method])
    typed, size, rule = sized(deal, f, mk, unit, usdtry)
    # the level: the one typed, or the one that gives the NPV typed - on the user's curve (the other's beside)
    level, implied = leveled(deal, kind, typed_price, side, size, base, method, usdtry)
    # the DV01 of the position at the price typed (at mid without one): every pillar bumped on each method
    rows: Dict[str, Dict[str, Optional[float]]] = {}
    totals: Dict[str, Optional[float]] = {}
    for m in METHODS:
        got = curves.bumped(family, m) if base[m] is not None else None
        if got is None:
            totals[m] = None
            continue
        b0, bumps = got
        k = level if level is not None else mid(deal, b0)
        v0 = value(deal, b0, side, size, k)
        tot = 0.0
        for name, c in bumps:
            dv = (value(deal, c, side, size, k) - v0) / usdtry
            rows.setdefault(name, {})[m] = dv
            tot += dv
        totals[m] = tot
    pillars = curves.pillars(family)
    bucket_rows = []
    if family == ON:
        named = {n for n, _ in pillars}                       # (a point of the desk's list at 1W: its own bucket)
        bucket_rows += [{"name": b, "pillar": False, "day": None, "dv01": {m: None for m in METHODS}} for b in SHORT_BUCKETS
                        if b not in named]
    for name, day in pillars:
        got = rows.get(name, {})
        bucket_rows.append({"name": name, "pillar": True, "day": day, "dv01": {m: got.get(m) for m in METHODS}})
    # the NPV at the price typed (or solved for) and its distance from mid
    npv = None
    if level is not None:
        npv = npv_block(deal, base, side, size, level, mids, usdtry, kind, typed_price, implied, method)
    out: Dict[str, Any] = {
        "asset": asset, "label": deal.label, "family": family, "method": method, "methods": methods,
        "price_kind": kind, "price_kind_text": KIND_TEXT[kind],
        "side": f["side"], "spot": deal.spot, "start": deal.start, "end": deal.end, "days": deal.end - deal.start,
        "mid": mids, "diff": ((mids[PPK] - mids[BOOT]) * 10000.0 if mids[PPK] is not None and mids[BOOT] is not None else None),
        "size": {"kind": f["size_kind"], "typed": typed, "size": size, "rule": rule,
                 "unit_dv01": unit / usdtry, "dv01": size * unit / usdtry},
        "buckets": {"rows": bucket_rows, "total": totals, "family": family},
        "npv": npv, "usdtry": usdtry, "errors": list(curves.errors),
    }
    if asset == FX:
        out["fx"] = {"pair": deal.pair, "spot": deal.fx_rate, "spot_date": deal.start, "ccy_rate": deal.ccy_rate,
                     "points": {m: ((mids[m] - deal.fx_rate) * 10000.0 if mids[m] is not None else None) for m in METHODS},
                     "df": {m: (base[m].df(deal.end - deal.spot) if base[m] is not None else None) for m in METHODS},
                     "ccy": "USD" if deal.pair == "USDTRY" else "EUR"}
    else:
        sp = deal.spot
        out["schedule"] = [{"start": lg.start, "pay": lg.pay, "days": lg.days, "tau": lg.tau,
                            "df": {m: (base[m].df(lg.pay - sp) if base[m] is not None else None) for m in METHODS}}
                           for lg in deal.legs]
        out["annuity"] = {m: (annuity(deal, base[m]) if base[m] is not None else None) for m in METHODS}
    out["notes"] = notes(deal, curves)
    out["texts"] = {"conventions": CONVENTIONS[asset], "dv01": DV01_TEXT, "npv": NPV_TEXT,
                    "short": SHORT_TEXT if family == ON else "", "price": PRICE_TEXT[FX if asset == FX else OIS]}
    return out


def _int_text(x: float) -> str:
    return "{:,.0f}".format(x).replace(",", ".")


def notes(deal: Deal, curves: Curves) -> List[str]:
    """What the page says under the numbers: where the maturity is against the curve's quotes."""
    out = []
    pillars = curves.pillars(deal.family)
    far = deal.end - deal.spot
    day = lambda d: serial_to_date(deal.spot + d).strftime("%d.%m.%Y")          # noqa: E731
    if pillars and far > pillars[-1][1] + 0.5:
        out.append("Vade eğrinin son kotasından (%s, %s) uzun: ötesi son dilimin eğimiyle uzatılır." % (pillars[-1][0],
                                                                                                    day(pillars[-1][1])))
    # a swap a few days off a quote's own day (the offshore curve's XCCY quotes on Bloomberg's days, a weekend not rolled;
    # a maturity typed as a date): its mid is not that quote
    for name, d in (pillars if deal.asset != FX else ()):
        if 0.5 < abs(far - d) <= 3.5:
            out.append("Vade %s kotasının gününe (%s) %d gün uzak: eğri o kotayı kendi gününde fiyatlar, bu yüzden mid kotadan "
                       "biraz farklı." % (name, day(d), abs(far - d)))
    return out


#: what the page says of each asset's conventions
CONVENTIONS = {
    OIS: "TRY OIS: sabit ↔ TLREF (günlük bileşik), ACT/365. 3 aya kadar tek ödeme, daha uzunda çeyreklik: kuponlar vadeden "
         "geriye sayılır, kısa dönem başta (Masa'nın kırık vade bloğunun takvimi; spot'tan kotalı vade Motor'un çeyreklik "
         "takvimi, kota olduğu gibi). Başlangıç ve vade OIS spot'undan (OIS_MAIN!B2), TRY tatilleriyle. Par = (DF(başlangıç) − "
         "DF(vade)) / Σ τ·DF.",
    FRA: "FRA = OIS forward'ı: başlangıç × bitiş, ikisi de OIS spot'undan ay (12x15, 1Yx18M) ya da tarih. Takvim TRY OIS'inki: "
         "3 aya kadar tek dönem, daha uzunda çeyreklik, bitişten geriye; çeyreklik takvimde OIS · PPK'nın FRA listeleriyle aynı "
         "sayı. ACT/365, TLREF; par = (DF(başlangıç) − DF(bitiş)) / Σ τ·DF.",
    XCCY: "XCCY: TRY sabit, yıllık ACT/360 ↔ USD değişken (par'da: offshore TRY eğrisi çapraz kur eğrisidir). Kuponlar vadeden "
          "geriye 12'şer ay, kısa dönem başta: 18M = 6A + 12A, 2Y3M = 3A + 12A + 12A (Masa'nın kırık vade bloğunun takvimi). "
          "Başlangıç ve vade FX spot'undan (Forward!I2), TRY tatilleriyle. Offshore eğri: FX swap ima ≤9A (tek dönem basit ACT/360) "
          "+ XCCY 1Y–10Y (yıllık ACT/360 par) bootstrap'ı; par = (DF(başlangıç) − DF(vade)) / Σ τ·DF.",
    FX: "FX forward: F = S · DF_TRY(spot) / DF_TRY(valör) / (1 + r · gün/360) - offshore TRY eğrisi ve USD (EUR) OIS faizi, "
        "valöre günlere göre doğrusal (Forward!U:X, AA:AD); puan = (F − S) · 10.000. Spot USDTRY'de Masa'nın spotu (MASA!H2), "
        "EURTRY'de Forward'ın EURTRY spotu; valör spot'tan, paritenin ortak takviminde (TRY + USD / EUR). Masa'nın kırık vade "
        "bloğunun forward satırı.",
}
#: how the DV01 is made
DV01_TEXT = ("DV01 ($/bp; TL, USDTRY OIS_MAIN!D2 ile $): her kotanın +1 bp'sinde pozisyonun bugünkü değerinin değişimi; + = faizler "
             "yükselince kazanır (pay, döviz alış - Günlük İşlemler'in ve DV01 Risk'in işareti). Bootstrap (Murex): Motor'un kendi "
             "kova kaydırması (Motor!T86: kota +1 bp, düğümlerin par'ı aylara göre doğrusal yeniden, bootstrap yeniden); PPK basamak: "
             "kota +1 bp, MPC ima aynı, kalibrasyon yeniden (o kotanın ve sonrakilerin aralık kaydırmaları yeniden çözülür); offshore: "
             "FX swap / XCCY bootstrap'ı (PPK'da offshore kalibrasyonu) yeniden. Fiyat yazılıysa o fiyattaki, yoksa mid'deki "
             "pozisyonun. Toplam = kovaların toplamı.")
#: the desk's buckets the OIS curve has no quote at
SHORT_TEXT = "ON / 1W / 2W: eğrinin orada kotası yok (bootstrap 1A kotasından başlar) - bu vadelerin riski 1A kovasındadır."
#: what the NPV is
NPV_TEXT = ("NPV: pozisyonun yazılan fiyattaki bugünkü değeri (eğrinin spot'una iskontolu), + = lehine (Günlük İşlemler'in "
            "\"Mid'e göre\"si gibi: mid'in altında PAY, üstünde RECEIVE; FX'te mid'in altında AL, üstünde SAT).")
#: what the price box can hold, and how a level is found from an NPV / upfront (by the swaps', by an FX forward's)
PRICE_TEXT = {
    OIS: "Fiyat tipi: Faiz (sabit oran; 35,10 = %35,10), NPV TL, NPV $ ya da Peşin bp (nominalin bp'si; %0,5 = 50 bp). NPV ya da "
         "peşin yazılınca o NPV'yi veren sabit faiz eğrinizde çözülür - NPV'nin tam tersi: K = ((DF(başlangıç) − DF(vade)) − NPV / "
         "(yön · N)) / Σ τ·DF, yön PAY +1, RECEIVE −1 - ve her sayı (NPV, DV01 kovaları, Fiyat − mid) o faizdedir; öbür eğrinin aynı "
         "NPV için faizi yanında. Peşin = NPV / nominal · 10.000, NPV gibi + = lehine (swap'ın size değeri: karşılığında bu tutarı "
         "siz ödersiniz). NPV $, OIS_MAIN!D2'deki USDTRY ile TL'dir.",
    FX: "Fiyat tipi: Outright, Puan (forward = spot + puan / 10.000), NPV TL ya da NPV $. NPV yazılınca o NPV'yi veren forward kur "
        "eğrinizde çözülür - NPV'nin tam tersi: K = F − NPV / (yön · tutar · DF(valör)), yön AL +1, SAT −1 -; öbür eğrininki "
        "yanında. NPV $, OIS_MAIN!D2'deki USDTRY ile TL'dir.",
}
#: what the Toplu box does
BULK_TEXT = ("Toplu fiyatlama: her satır bir enstrüman - vade (2Y3M, 18M, 15, tarih), başlangıç × bitiş (12x15, 1Yx18M) ya da iki "
             "tarih (04.05.2027 04.05.2028); FX forward'da valör - ve satırın sonunda isteğe bağlı fiyat, yukarıdaki Fiyat tipiyle "
             "(2Y 38,50; NPV TL'de 2Y -1m). Yön ve büyüklük yukarıdaki gibi (DV01 yazılıysa her satırın nominali o DV01'den). Satırlar "
             "sayfanın eğrileriyle fiyatlanır, satır için eğri yeniden kurulmaz: TRY OIS ve FRA OIS eğrisinde, XCCY ve FX forward "
             "offshore eğride. DV01 büyüklüğün DV01'idir (N · annuity · 0,0001 / USDTRY, OIS_MAIN'in kuralı; FX'te forward'ın 1 bp'si; "
             "+ = faizler yükselince kazanır) - kova kova DV01 için satırı yukarıda fiyatlayın. En çok %d satır." % BULK_LINES)
#: how a line of the Toplu box is written, by the swaps' and by an FX forward's
LINE_HINT = {OIS: "2Y3M, 15, 12x15, 1Yx18M ya da iki tarih; fiyat satırın sonunda",
             FX: "valör: 1Y, 18M ya da tarih; fiyat satırın sonunda"}


# ================================================================================================== Toplu
#: what may stand between a line's parts: a tab, ";", "|", a dash between spaces, an arrow
_LINE_GAPS = re.compile(r"[\t;|]+|\s+[-–—]\s+|\s*→\s*")
#: what joins a start and an end ("12x15", "1Y × 18M")
_PAIR_MARKS = ("x", "×", "*")


def parse_line(text: str, asset: str) -> Tuple[Tuple[str, float], Tuple[str, float], str]:
    """A line of the Toplu box: ``(start, maturity, price text)``.  The instrument - a maturity from the spot ("2Y3M",
    "18M", "15", "04.05.2028"; the whole line first, so "2Y 3M" is 2Y3M and "1 yıl 6 ay" 18M), a start × end ("12x15",
    "1Y × 18M"; not an FX forward's) or two dates ("04.05.2027 04.05.2028"; a tab, ";" or " - " between them as well) -
    then, after a space, the price in the page's price kind ("2Y 38,50", "12x15 -1m"): one word, so a bare number after a
    maturity is its price, not months.  :class:`PricingError` for a line it cannot read."""
    flat = " ".join(_LINE_GAPS.sub(" ", str(text or "")).split())
    tokens: List[str] = []
    for tok in flat.split(" ") if flat else []:
        low = tok.lower()
        if tokens and (low in _PAIR_MARKS or low[0] in _PAIR_MARKS or tokens[-1].lower()[-1] in _PAIR_MARKS):
            tokens[-1] += tok                          # ("12 x 15", "1Y ×18M": one word)
        else:
            tokens.append(tok)
    for k in (len(tokens), len(tokens) - 1):
        if k <= 0:
            break
        got = _line_instrument(tokens[:k], asset)
        if got is not None:
            return got[0], got[1], " ".join(tokens[k:])
    raise PricingError("satır okunamadı: %r (%s)" % (str(text or "").strip(), LINE_HINT[FX if asset == FX else OIS]))


def _line_instrument(tokens: List[str], asset: str) -> Optional[Tuple[Tuple[str, float], Tuple[str, float]]]:
    """The start and maturity ``tokens`` say (:func:`parse_line`); ``None`` when they are not an instrument."""
    if asset != FX and len(tokens) == 1:
        both = split_pair(tokens[0].replace("X", "x"))
        if both is not None:
            return parse_when(both[0]), parse_when(both[1])
    if asset != FX and len(tokens) == 2:
        a, b = parse_when(tokens[0]), parse_when(tokens[1])
        if a is not None and b is not None and a[0] == "d" and b[0] == "d":
            return a, b
    w = parse_when(" ".join(tokens))
    return (("spot", 0.0), w) if w is not None else None


def bulk(inputs: Dict[str, Any], curves: Curves, method: str) -> Dict[str, Any]:
    """Toplu fiyatlama: every line of the asset's Toplu box (``bulk``, :func:`parse_line`) priced as :func:`price` prices
    the page's instrument - its side, size and price kind - off the same curves: the page's ``curves`` are read for each
    line and nothing is built for it (no bootstrap, no bump: its DV01 is the size's, by the annuity rule).  Each instrument
    on its own curve: TRY OIS and FRA on OIS, XCCY and FX forwards offshore.  A line that cannot be priced says why
    (``error``); the others are priced.  ``rows``: per line ``{n, line, label, start, end, days, spot, mid, diff, size,
    dv01, annuity | points, price, npv}`` - ``dv01`` signed as the page's (+ = gains when rates rise), ``npv`` as
    :func:`price`'s (none without a price)."""
    mk = curves.mk
    asset = inputs["asset"]
    f = inputs["by"][asset]
    kind = price_kind(asset, f)
    family = OFF if asset in (XCCY, FX) else ON
    base = {m: curves.curve(family, m) for m in METHODS}
    if base[method] is None:
        method = BOOT
    lines = [s.strip() for s in (f.get("bulk") or "").split("\n")]
    lines = [s for s in lines if s]
    out: Dict[str, Any] = {"rows": [], "lines": len(lines), "left_out": max(0, len(lines) - BULK_LINES), "asset": asset,
                           "family": family, "kind": kind, "kind_text": KIND_TEXT[kind], "side": f["side"],
                           "size_kind": f["size_kind"], "size": f.get("size") or "", "method": method,
                           "methods": [method] + [m for m in METHODS if m != method], "text": BULK_TEXT,
                           "hint": LINE_HINT[FX if asset == FX else OIS]}
    side = 1 if f["side"] in ("PAY", "AL") else -1
    for n, line in enumerate(lines[:BULK_LINES], 1):
        try:
            if base[BOOT] is None:
                raise PricingError("eğri kurulamadı: %s" % ("; ".join(curves.errors) or "kota yok"))
            if not mk.usdtry:
                raise PricingError("USDTRY yok (OIS_MAIN!D2)")
            row = _bulk_row(asset, f, kind, line, mk, base, method, side)
        except PricingError as exc:
            row = {"line": line, "error": str(exc)}
        except (ValueError, ZeroDivisionError, OverflowError) as exc:      # (a number that cannot be: said on its line)
            row = {"line": line, "error": "hesaplanamadı: %s" % exc}
        row["n"] = n
        out["rows"].append(row)
    return out


def _bulk_row(asset: str, f: Dict[str, Any], kind: str, line: str, mk: Market, base: Dict[str, Any], method: str,
              side: int) -> Dict[str, Any]:
    """One line of the Toplu box, priced (:func:`bulk`)."""
    usdtry = mk.usdtry
    start_when, end_when, price_text = parse_line(line, asset)
    deal = fx_deal(f["pair"], end_when, mk) if asset == FX else swap_deal(asset, start_when, end_when, mk)
    mids = {m: (mid(deal, base[m]) if base[m] is not None else None) for m in METHODS}
    typed_price = read_price(kind, price_text, deal)
    _, size, _ = sized(deal, f, mk, unit_dv01(deal, base[method]), usdtry)
    level, implied = leveled(deal, kind, typed_price, side, size, base, method, usdtry)
    row: Dict[str, Any] = {
        "line": line, "label": deal.label, "start": deal.start, "end": deal.end, "days": deal.end - deal.start,
        "spot": deal.spot, "mid": mids,
        "diff": ((mids[PPK] - mids[BOOT]) * 10000.0 if mids[PPK] is not None and mids[BOOT] is not None else None),
        "size": size, "dv01": {m: (side * size * unit_dv01(deal, base[m]) / usdtry if base[m] is not None else None) for m in METHODS},
        "price": price_text,
        "npv": npv_block(deal, base, side, size, level, mids, usdtry, kind, typed_price, implied, method) if level is not None else None}
    if asset == FX:
        row["points"] = {m: ((mids[m] - deal.fx_rate) * 10000.0 if mids[m] is not None else None) for m in METHODS}
    else:
        row["annuity"] = {m: (annuity(deal, base[m]) if base[m] is not None else None) for m in METHODS}
    return row
