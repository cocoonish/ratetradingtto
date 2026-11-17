"""Trades · valuation and carry: what a trade of the desk's book is worth now, what one more day earns, the cash it has
paid or received since it started and its price as the desk reads it - for the Trades page (its storage, close
snapshots and P&L periods are the page's own), on demand only.

The interface - the page calls nothing else:

* :data:`PRODUCTS` - ``ois`` (TRY OIS, TLREF float), ``sofr`` (USD OIS, SOFR float), ``dibs`` (TRY government
  bonds), ``fxspot``, ``fxopt``;
* :func:`check` - a trade's fields normalised and validated (:class:`TradeError`, a ``ValueError``, in Turkish);
* :func:`defaults` - the fields a new trade takes from the desk's conventions (dates on the desk's holiday lists, the
  meeting periods, an FRA's dates, a package's weights);
* :func:`market` - one snapshot of everything valuation needs, read once per refresh from the shared (desk)
  calculation and the history: never a Bloomberg request, nobody's personal inputs;
* :func:`value` - MTM in the trade's currency, TL and USD, carry over one day, cash accrued since the start, the price
  now, the greeks of an option, a package's legs;
* :func:`notional_for_dv01` - the nominal of a DV01, on the desk's 5 mn lot.

**Instruments are named by what they are** - a swap by its dates, a meeting period by the meeting's date, a bond by its
ISIN, FX by its pair - never by a row: a calendar edit, a roll or a new bond in a list moves nothing.

**MTM + accrued = the trade's whole value change.**  ``mtm`` is what the position is worth now against what it cost
(the market value of the cash flows still to come; for a bond and FX the price difference); ``accrued`` is the cash
the trade has paid or received since it started that MTM no longer holds (a swap's settled periods, a bond's coupons).
A period's P&L is the change of the two together.

**Carry** (``carry_1d``) is what one day passing earns with the market unchanged, over the period to the next business
day of the trade's calendar (d calendar days: 1, 3 over a weekend - as TLREF accrues Friday's fixing over the
weekend); ``inputs["carry_days"]`` says how many.

Per product (each one's market, conventions and the numbers that went in are in ``inputs``):

* **ois / sofr** (``structure``: outright, mpc, spread, fly, fra).
  *MTM* = fixed leg − float leg (receive; pay is minus), the cash flows still to come discounted to today on the
  dashboard's bootstrapped curve - TRY: ``BOOT_GUN`` / ``BOOT_LNDF`` (Motor!C88:C130 / I88:I130: ln DF linear in days
  from the OIS spot ``SPOTDATE``), USD: the SOFR book's (SOFR_FOMC!K48:M68, its "Zero lineer" interpolation, from its
  T+2 spot); a day before the curve's spot is the overnight away (TLREF ACT/365, SOFR ACT/360).  The float leg is the
  overnight compounded: the days already fixed from the history's fixings (TLREF: ``BISTTREF Index``; SOFR when the
  history holds it, else the current fixing - said in ``inputs["notes"]``), the rest from the curve.  Conventions are
  the workbooks' own: TRY ACT/365, a single payment up to 3 months, then quarterly coupons counted from the start
  (Motor!B88: ``WORKDAY(EDATE(start, n) − 1, 1, TRY)``); USD ACT/360, single payment up to 1 year, then annual coupons
  counted back from the end (a short first period, as SOFR_FOMC!AV64), modified following on the SIFMA list.
  *Accrued* = the net settlement of every period paid by today.  *Carry* = **the day's net accrual** - fixed against
  today's overnight on the period's compounded notional, sign × N × (K − I × r_ON) × days / basis (nothing before the
  start) - **plus the one-day roll-down**: the trade tomorrow on the curve rolled a day (the same zero rate for the
  same days from its spot, today's overnight fixed) against the trade tomorrow when today's forwards come true (its
  value grown a day at the curve's overnight): what the curve keeping its shape earns - nothing on a flat curve.  Both
  parts are in ``inputs`` (``carry_accrual``, ``roll_1d``).  A spread and a fly are the sums of their legs (level: long
  − short; the fly's body − ½ each wing beside the OIS sheet's 2·body − wings); an FRA is valued as one
  forward-starting swap, its two replicating swaps (to its end, and the opposite way to its start, from the trade's
  own settlement, same notional and rate) as the attribution - whatever they do not reproduce is ``inputs["residual"]``.
  A meeting period (``mpc``) runs from a meeting's effective day (the business day after it) to the next one's, its
  dates fixed when the trade is entered.  Closed (``status`` "closed", ``close_price``): only the fixed difference on
  the periods after the close is left (the floats cancel), no carry.
* **dibs** - *MTM* = (dirty price now − dirty price paid) × nominal / 100: the clean price of DİBS RV ("Kullanılan
  temiz"; Tüm Kâğıtlar's bid / ask mid, or its last trade, for a bond not on it; ``manual_price`` otherwise) plus
  accrued interest at its value date, against the trade's clean price (or yield - BIST compound by default, ``yield_conv``
  "basit" for the simple one) plus accrued at its settlement - DİBS RV's BIST rule (``quantcurve.Bond``: coupon c/f
  every round(364/f) days back from the maturity, yields compounded f times a year, a bill's simple; accrued c/f × days
  since the last coupon / the period's days).  A TLREF floater / FRN by its price, its accrued at the current coupon
  (approximate); a CPI-linked bond is not valued (no index ratio).  *Accrued* = the coupons (and the redemption) paid
  since settlement.  *Carry* = at an unchanged simple yield, the next value date's dirty price plus a coupon paid in
  between, less today's dirty price funded at TLREF over the days between (a floater: its coupon's accrual less the
  funding).
* **fxspot** - *MTM* = (spot now − trade rate) × base amount, in the quote currency (``manual_price``: the spot when the
  dashboard has none); *carry* = rolling the position from its spot date to the next one at the two currencies'
  overnight rates (the Forward sheet's: TRY offshore O/N, SOFR, €STR; else the pair's forward curve):
  −base × (F − S).  No accrued.
* **fxopt** - Garman-Kohlhagen on the forward to delivery, discounted in the quote currency (the vol clock: days to
  expiry / 365); the vol at the strike from the dashboard's smile (USDTRY / EURUSD: the Opsiyon page's SVI fit with the
  pair's delta conventions; G10: the quant universe's ATM / 25D RR / 25D BF through Vanna-Volga, ``fxvol``), the
  quotes interpolated to the expiry (ATM in total variance, RR / BF in vol points, flat beyond the quoted tenors);
  ``manual_price`` is a vol (points) typed by hand.  *MTM* = option value − premium (signed: bought +, sold −; the
  premium in its currency at today's spot).  *Carry* = theta over the day(s): the same spot, vol and rates, the
  expiry and the forward's days that much shorter.  Greeks: delta (base currency amount, spot delta), gamma (the
  delta's change for a 1 % rise of the spot), vega (a vol point, quote currency), theta (one calendar day, quote
  currency).
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import fx as fxm
from . import fxvol as fv
from . import quantcurve as qc
from .history import add_months

PRODUCTS = ("ois", "sofr", "dibs", "fxspot", "fxopt")
STRUCTURES = ("outright", "mpc", "spread", "fly", "fra")
RATES = ("ois", "sofr")
#: the desk's lot: a nominal from a DV01 is rounded to it (OIS_MAIN!H2 for TRY; 5 mn USD for SOFR)
LOT = 5000000.0
#: a package's DV01 weights, as the desk sizes them: a spread 1:1, a fly 50/50 (wings ½ each)
WEIGHTS = {"spread": (1.0, 1.0), "fly": (0.5, 1.0, 0.5)}
#: a trade's side as :func:`check` writes it: the blotter's codes - an OIS / SOFR "B" pays the fixed rate and "S" receives
#: it, as the workbook's own list and the desk's stored trades have it (``entry.OIS_SIDES_WORDS``); a bond or FX "B" buys,
#: "S" sells.  Either the code or the word is taken (the interface's "receive" / "pay" included).
_SIDES = {"ois": ("S", "B"), "sofr": ("S", "B"), "dibs": ("B", "S"), "fxspot": ("B", "S"), "fxopt": ("B", "S")}
#: what a side code means, in words (``side_text``: what a page shows beside the code)
SIDE_TEXT = {"rates": {"S": "receive", "B": "pay"}, "other": {"B": "buy", "S": "sell"}}
_RATE_SIDES = {"receive": "S", "rec": "S", "r": "S", "receiver": "S", "received": "S", "s": "S",
               "pay": "B", "p": "B", "payer": "B", "paid": "B", "ode": "B", "öde": "B", "b": "B"}
_BS_SIDES = {"b": "B", "buy": "B", "al": "B", "alis": "B", "alış": "B", "alim": "B", "alım": "B", "bought": "B", "long": "B",
             "s": "S", "sell": "S", "sat": "S", "satis": "S", "satış": "S", "sold": "S", "short": "S"}
#: currencies the dashboard keeps a rate or a USD pair of (FX it can price, crosses included)
FX_CCYS = ("TRY", "USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD", "NOK", "SEK")
#: the smile model per pair: the Opsiyon page's SVI for its pairs, Vanna-Volga through 25P / ATM / 25C for G10
SVI_PAIRS = ("USDTRY", "EURUSD")
#: vol pillars' times as the Opsiyon page counts them (calendar days of the tenor, a year 365)
_VOL_DAYS = {"1W": 7.0, "2W": 14.0, "1M": 365.0 / 12.0, "2M": 365.0 / 6.0, "3M": 91.25, "6M": 182.5, "9M": 273.75,
             "1Y": 365.0, "18M": 547.5, "2Y": 730.0}
_KINDS = ("ATM", "RR25", "BF25", "RR10", "BF10")


class TradeError(ValueError):
    """A trade the dashboard cannot take as it is: the reason, in Turkish."""


# ---------------------------------------------------------------------------------------------- small helpers
def _num(v: Any) -> Optional[float]:
    if type(v) is int:
        return float(v)
    return v if type(v) is float and math.isfinite(v) else None


def _day(v: Any) -> Optional[_dt.date]:
    """A date as a trade or a sheet holds one: ISO text, Turkish text ("3.11.2026"), a date, an Excel serial."""
    from .inputs import parse_date
    from .xl.values import serial_to_date
    if v is None or v == "":
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    if type(v) in (int, float) and not isinstance(v, bool) and 20000 < v < 80000:
        return serial_to_date(float(v))
    if isinstance(v, str):
        s = v.strip()
        try:
            return _dt.date.fromisoformat(s[:10])
        except ValueError:
            pass
        x = parse_date(s)
        return serial_to_date(x) if x is not None else None
    return None


def _iso(d: Optional[_dt.date]) -> Optional[str]:
    return d.isoformat() if d is not None else None


def _short(d: _dt.date) -> str:
    return d.strftime("%d.%m.%y")


def _tr(v: float, d: int = 2) -> str:
    """A number Turkish style: 38,45 · 41,8020 · 1.250.000 · −35,0."""
    s = "%.*f" % (d, abs(v))
    whole, _, frac = s.partition(".")
    out = "{:,}".format(int(whole)).replace(",", ".") + ("," + frac if frac else "")
    return ("−" if v < 0 and any(c in "123456789" for c in s) else "") + out


def _plain(v: float) -> str:
    """A strike as typed: 42 · 42,5 · 1,0850."""
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _round_half_away(x: float) -> float:
    f = float("%.15g" % abs(x))
    r = math.floor(f + 0.5)
    return -r if x < 0 else r


# ---------------------------------------------------------------------------------------------- calendars and tenors
def _is_bd(d: _dt.date, hol: Any) -> bool:
    return d.weekday() < 5 and d not in hol


def _following(d: _dt.date, hol: Any) -> _dt.date:
    return fxm.week_day_on_or_after(d, hol)


def _preceding(d: _dt.date, hol: Any) -> _dt.date:
    while not _is_bd(d, hol):
        d -= _dt.timedelta(days=1)
    return d


def _modfol(d: _dt.date, hol: Any) -> _dt.date:
    """Modified following: the next business day, the one before when that is in the next month (SOFR_FOMC!J49)."""
    f = _following(d, hol)
    return f if f.month == d.month else _preceding(d, hol)


def _add_bd(d: _dt.date, n: int, hol: Any) -> _dt.date:
    return fxm.add_week_days(d, n, hol) if n > 0 else d


def parse_tenor(text: Any) -> Optional[Tuple[str, int]]:
    """A tenor as the desk types it - the dashboard's date shortcuts (``2Y``, ``18M``, ``3A``, ``1H``, ``2W``):
    ``("M", months)`` or ``("W", weeks)``; ``None`` for anything else."""
    from .shortcuts import date_shortcut
    sc = date_shortcut(text) if isinstance(text, str) else None
    if sc is None or sc[0] not in ("M", "W") or sc[1] <= 0:
        return None
    return sc


def tenor_label(months: Optional[int] = None, weeks: Optional[int] = None) -> str:
    """The OIS sheet's names: 1W, 1M, 6M, 1Y, 18M, 2Y."""
    if weeks:
        return "%dW" % weeks
    if months is None:
        return ""
    return "%dY" % (months // 12) if months % 12 == 0 else "%dM" % months


def _tenor_tr(tenor: str) -> str:
    """An FX tenor as the FX pages say it: 1H, 3A, 1Y."""
    sc = parse_tenor(tenor)
    if sc is None:
        return str(tenor)
    kind, n = sc
    if kind == "W":
        return "%dH" % n
    return "%dY" % (n // 12) if n % 12 == 0 else "%dA" % n


class Conv(object):
    """A rate product's conventions, as its workbook has them."""

    __slots__ = ("product", "ccy", "basis", "single", "coupon", "roll", "anchor", "cal", "lag", "float_name", "label",
                 "meetings_name")

    def __init__(self, product: str, ccy: str, basis: float, single: int, coupon: int, roll: str, anchor: str,
                 cal: Tuple[str, ...], lag: int, float_name: str, label: str, meetings_name: str):
        self.product, self.ccy, self.basis = product, ccy, basis
        self.single, self.coupon = single, coupon       # months: one payment up to ``single``, then every ``coupon``
        self.roll, self.anchor = roll, anchor           # "following" / "modfol"; coupons counted from "start" / "end"
        self.cal, self.lag = cal, lag                   # holiday lists; the spot lag in business days
        self.float_name, self.label, self.meetings_name = float_name, label, meetings_name


#: TRY OIS (Motor!B88:K130, OIS_MAIN!B2 = WORKDAY(TODAY(),1,TRY)) and USD SOFR OIS (SOFR_FOMC!B5, J49, L64)
CONVS = {"ois": Conv("ois", "TRY", 365.0, 3, 3, "following", "start", ("TRY",), 1, "TLREF", "OIS", "MPC"),
         "sofr": Conv("sofr", "USD", 360.0, 12, 12, "modfol", "end", ("SIFMA",), 2, "SOFR", "SOFR", "FOMC")}


def _roll(conv: Conv, d: _dt.date, hol: Any) -> _dt.date:
    return _modfol(d, hol) if conv.roll == "modfol" else _following(d, hol)


def tenor_end(start: _dt.date, tenor: Any, conv: Conv, hol: Any) -> Optional[_dt.date]:
    """The end of a tenor from ``start`` by the product's rule (TRY: the next business day on or after EDATE, USD:
    modified following)."""
    sc = parse_tenor(tenor)
    if sc is None:
        return None
    kind, n = sc
    raw = add_months(start, n) if kind == "M" else start + _dt.timedelta(days=7 * n)
    return _roll(conv, raw, hol)


def tenor_months(tenor: Any) -> Optional[int]:
    sc = parse_tenor(tenor)
    return sc[1] if sc is not None and sc[0] == "M" else None


def schedule(start: _dt.date, end: _dt.date, conv: Conv, hol: Any, months: Optional[int] = None) -> List[Tuple[_dt.date, _dt.date]]:
    """The periods of a fixed-for-overnight swap from ``start`` to ``end`` (payment at each period's end): one up to
    ``conv.single`` months, else every ``conv.coupon`` months - TRY from the start forward (the last period ends at the
    end date), USD back from the end (the first one short).  ``months``: the tenor, when the trade was entered as one."""
    if not end > start:
        return []
    first = _roll(conv, add_months(start, conv.single), hol)
    if (months is not None and months <= conv.single) or (months is None and end <= first):
        return [(start, end)]
    dates: List[_dt.date] = []
    if conv.anchor == "start":
        k = 1
        while k < 2000:
            d = _roll(conv, add_months(start, conv.coupon * k), hol)
            if d >= end:
                break
            if d > start:
                dates.append(d)
            k += 1
    else:
        # a tenor's coupons as the SOFR book dates them (SOFR_FOMC!AV64: EDATE(spot, m − 12k), modified following);
        # a broken end date's back from the end itself (the first period short)
        k = 1
        while k < 200:
            raw = add_months(start, months - conv.coupon * k) if months is not None else add_months(end, -conv.coupon * k)
            if raw <= start:
                break
            d = _roll(conv, raw, hol)
            if start < d < end:
                dates.append(d)
            k += 1
        dates = sorted(set(dates))
    dates.append(end)
    out, prev = [], start
    for d in dates:
        out.append((prev, d))
        prev = d
    return out


# ---------------------------------------------------------------------------------------------- curves and fixings
class Curve(object):
    """A discount curve as the workbooks hold one: ln DF at nodes ``days`` after ``spot``; ``interp`` "lndf" - linear in
    days between the nodes and past the last one along the last segment (BOOT, the offshore curve) - or "zero" - the
    continuous zero rate linear in days, flat before the first node, along the last two past the last (SOFR_FOMC!AY64,
    "Zero lineer").  A day before the spot is one overnight at ``on`` (a decimal rate on ``basis``) away from it."""

    __slots__ = ("spot", "nodes", "on", "basis", "interp", "name")

    def __init__(self, spot: _dt.date, days: Sequence[Any], lndf: Sequence[Any], on: Optional[float] = None,
                 basis: float = 365.0, interp: str = "lndf", name: str = ""):
        self.spot = spot
        seen: Dict[float, float] = {}
        for t, x in zip(days, lndf):
            t, x = _num(t), _num(x)
            if t is not None and x is not None and t >= 0 and t not in seen:
                seen[t] = x
        if 0.0 not in seen:
            seen[0.0] = 0.0
        self.nodes = sorted(seen.items())
        self.on = on
        self.basis = basis
        self.interp = interp
        self.name = name

    @classmethod
    def flat(cls, spot: _dt.date, rate: float, basis: float = 365.0, years: int = 12, on: Optional[float] = None,
             interp: str = "lndf") -> "Curve":
        """A flat curve: the overnight ``rate`` (simple, on ``basis``) compounded every day - DF(t) = (1 + r/basis)^−t -,
        and that overnight before the spot (hand cases, tests)."""
        days = [0.0] + [30.0 * k for k in range(1, 12 * years + 1)]
        step = math.log(1.0 + rate / basis)
        return cls(spot, days, [-step * t for t in days], rate if on is None else on, basis, interp)

    def ok(self) -> bool:
        return len(self.nodes) >= 2

    def lndf_at(self, t: float) -> float:
        nodes = self.nodes
        if self.interp == "zero":
            pos = [(d, x) for d, x in nodes if d > 0]
            if not pos:
                return 0.0
            if t <= pos[0][0]:
                return pos[0][1] * t / pos[0][0]
            k = bisect.bisect_right([d for d, _ in pos], t) - 1
            k = max(0, min(k, len(pos) - 2))
            if len(pos) < 2:
                return pos[0][1] * t / pos[0][0]
            (d0, x0), (d1, x1) = pos[k], pos[k + 1]
            z0, z1 = -x0 / d0, -x1 / d1
            return -t * (z0 + (t - d0) * (z1 - z0) / (d1 - d0))
        ds = [d for d, _ in nodes]
        k = bisect.bisect_right(ds, t) - 1
        k = max(0, min(k, len(nodes) - 2))
        (d0, x0), (d1, x1) = nodes[k], nodes[k + 1]
        return x0 + (x1 - x0) * (t - d0) / (d1 - d0)

    def df(self, d: _dt.date) -> float:
        """The discount factor of a day at the curve's spot: 1 at the spot; before it 1 + O/N × days / basis."""
        t = float((d - self.spot).days)
        if t >= 0:
            return math.exp(self.lndf_at(t))
        on = self.on if self.on is not None else -self.lndf_at(1.0) * self.basis
        return 1.0 + on * -t / self.basis

    def zero_simple(self, a: _dt.date, b: _dt.date, basis: Optional[float] = None) -> Optional[float]:
        """The simple rate from ``a`` to ``b`` (decimal): (DF(a) / DF(b) − 1) × basis / days."""
        if not b > a:
            return None
        return (self.df(a) / self.df(b) - 1.0) * (basis or self.basis) / float((b - a).days)

    def rolled(self, spot: _dt.date) -> "Curve":
        """The same curve from another spot: the same zero rate for the same days from it (the curve keeps its shape)."""
        c = Curve(spot, [], [], self.on, self.basis, self.interp, self.name)
        c.nodes = list(self.nodes)
        return c

    def shifted(self, bp: float) -> "Curve":
        """Every zero rate ``bp`` higher (continuous, ACT/365) - for a sensitivity."""
        c = Curve(self.spot, [], [], self.on, self.basis, self.interp, self.name)
        c.nodes = [(d, x - bp * 1e-4 * d / 365.0) for d, x in self.nodes]
        if self.on is not None:
            c.on = self.on + bp * 1e-4
        return c


class Fixings(object):
    """The overnight index's fixings (``points``: ISO day -> % - the fixing of a day is the rate from it to the next
    business day) and the latest one (``live``, decimal: today's when it is fixed, else the last).  A day without a
    fixing takes the one before it; a day of today or later takes ``live``."""

    __slots__ = ("points", "days", "live", "hol", "basis", "name", "source")

    def __init__(self, points: Optional[Dict[str, float]], live: Optional[float], hol: Any, basis: float, name: str,
                 source: str = ""):
        self.points = {d: float(v) for d, v in (points or {}).items() if _num(v) is not None}
        self.days = sorted(self.points)
        self.live = live
        self.hol = frozenset(hol or ())
        self.basis = basis
        self.name = name
        self.source = source

    def with_days(self, extra: Dict[_dt.date, float]) -> "Fixings":
        pts = dict(self.points)
        pts.update({d.isoformat(): r * 100.0 for d, r in extra.items()})
        return Fixings(pts, self.live, self.hol, self.basis, self.name, self.source)

    def rate(self, d: _dt.date, today: _dt.date) -> Tuple[Optional[float], str]:
        iso = d.isoformat()
        if iso in self.points:
            return self.points[iso] / 100.0, "fix"
        if d >= today and self.live is not None:
            return self.live, "live"
        k = bisect.bisect_left(self.days, iso)
        if k > 0:
            return self.points[self.days[k - 1]] / 100.0, "prev"
        if self.live is not None:
            return self.live, "none"
        return None, "none"

    def compound(self, a: _dt.date, b: _dt.date, today: _dt.date, tally: Optional[Dict[str, int]] = None) -> Optional[float]:
        """Π (1 + r × n / basis) over the business days from ``a`` up to ``b`` - each fixing over the days to the next
        business day (a Friday's over the weekend) -, ``None`` when a day has no rate at all."""
        f = 1.0
        d = a
        while d < b:
            nxt = _add_bd(d, 1, self.hol)
            n = (min(nxt, b) - d).days
            r, how = self.rate(d, today)
            if r is None:
                return None
            if tally is not None:
                tally[how] = tally.get(how, 0) + 1
            f *= 1.0 + r * n / self.basis
            d = nxt
        return f


# ---------------------------------------------------------------------------------------------- the market
class Market(object):
    """One snapshot of what valuation needs (see :func:`market`); tests make their own with the same fields.

    ``curves`` / ``fixings`` / ``quotes`` / ``meetings`` by rate product ("ois", "sofr"); ``cal`` the holiday lists
    ("TRY" - Motor -, "USD" / "EUR" - EK_TATIL -, "SIFMA" - SOFR_FOMC!BO); ``spots`` FX by pair; ``rates`` the USD and
    EUR OIS (Forward!U:X, AA:AD: (days, simple ACT/360 %)); ``off`` the offshore TRY curve (OFF_GUN / OFF_LNDF);
    ``points`` outright forwards by pair ((days from its spot date, forward)); ``vols`` vol quotes by pair and tenor
    (vol points); ``bonds`` DİBS RV / Tüm Kâğıtlar by ISIN; ``usdtry`` the desk's USDTRY (OIS_MAIN!D2: DV01 in USD)."""

    def __init__(self, today: Any, curves: Optional[Dict[str, Curve]] = None, fixings: Optional[Dict[str, Fixings]] = None,
                 cal: Optional[Dict[str, Any]] = None, quotes: Optional[Dict[str, Dict[str, float]]] = None,
                 meetings: Optional[Dict[str, List[str]]] = None, spots: Optional[Dict[str, float]] = None,
                 rates: Optional[Dict[str, List[Tuple[float, float]]]] = None, off: Optional[Curve] = None,
                 points: Optional[Dict[str, List[Tuple[float, float]]]] = None,
                 vols: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None, bonds: Optional[Dict[str, Dict[str, Any]]] = None,
                 usdtry: Optional[float] = None, lot: Optional[float] = None, notes: Optional[List[str]] = None,
                 sources: Optional[Dict[str, str]] = None, on_rates: Optional[Dict[str, float]] = None):
        self.today = _day(today)
        #: overnight rates by currency (simple ACT/360, %): the Forward sheet's - TRY offshore O/N (ICAP, AC123), SOFR
        #: (X6), €STR (AD6) - what rolling an FX position one day costs or earns
        self.on_rates = {k: float(v) for k, v in (on_rates or {}).items() if _num(v) is not None}
        self.curves = dict(curves or {})
        self.fixings = dict(fixings or {})
        self.cal = {k: frozenset(v) for k, v in (cal or {}).items()}
        self.quotes = dict(quotes or {})
        self.meetings = {k: [m for m in v if m] for k, v in (meetings or {}).items()}
        self.spots = {k.upper(): v for k, v in (spots or {}).items() if _num(v) is not None and v > 0}
        self.rates = {k: sorted((float(d), float(r)) for d, r in v if _num(d) is not None and _num(r) is not None)
                      for k, v in (rates or {}).items()}
        self.off = off
        self.points = {k.upper(): sorted(v) for k, v in (points or {}).items()}
        self.vols = dict(vols or {})
        self.bonds = dict(bonds or {})
        self.usdtry = usdtry if _num(usdtry) else self.spots.get("USDTRY")
        self.lot = lot if _num(lot) and lot > 0 else LOT
        self.notes = list(notes or [])
        self.sources = dict(sources or {})

    # ---- calendars
    def hol(self, *keys: str) -> frozenset:
        out: set = set()
        for k in keys:
            out |= self.cal.get(k, frozenset())
        return frozenset(out)

    def pair_hol(self, pair: str) -> frozenset:
        from . import extras as ex
        return self.hol(*ex.pair_calendar(pair))

    def fx_spot_date(self, pair: str, day: Optional[_dt.date] = None) -> _dt.date:
        """The pair's spot date: its spot lag (USDTRY one, the others two) in business days of both its currencies
        (the dashboard's FX value dates: ``fx.SPOT_LAG``, ``extras.pair_calendar``)."""
        return _add_bd(day or self.today, fxm.SPOT_LAG.get(pair, 2), self.pair_hol(pair))

    def spot_date(self, prod: str, day: Optional[_dt.date] = None) -> _dt.date:
        conv = CONVS[prod]
        return _add_bd(day or self.today, conv.lag, self.hol(*conv.cal))

    # ---- FX
    def _direct(self, pair: str) -> Optional[float]:
        v = self.spots.get(pair)
        if v:
            return v
        inv = self.spots.get(pair[3:] + pair[:3])
        return 1.0 / inv if inv else None

    def spot(self, pair: str) -> Optional[float]:
        """A pair's spot: the desk's (USDTRY, EURTRY from the Forward sheet), the quant's G10 - its inverse, or the cross
        through USD."""
        pair = pair.upper()
        if pair[:3] == pair[3:]:
            return 1.0
        v = self._direct(pair)
        if v:
            return v
        a, b = pair[:3], pair[3:]
        if a != "USD" and b != "USD":
            x, y = self._direct(a + "USD"), self._direct("USD" + b)
            if x and y:
                return x * y
        return None

    def try_per(self, ccy: str) -> Optional[float]:
        return 1.0 if ccy == "TRY" else self.spot(ccy + "TRY")

    def usd_per(self, ccy: str) -> Optional[float]:
        return 1.0 if ccy == "USD" else self.spot(ccy + "USD")

    def _usd_rate(self, ccy: str, g: float) -> Optional[float]:
        pts = self.rates.get(ccy)
        if not pts:
            return None
        return fxm._lin(g, [d for d, _ in pts], [r for _, r in pts]) / 100.0

    def forward(self, pair: str, delivery: _dt.date) -> Tuple[Optional[float], str]:
        """The outright forward of ``pair`` for ``delivery`` and how it was made: USDTRY from the offshore TRY curve and
        the USD OIS (the Forward sheet's ``spot·(1 + TRY·g/360)/(1 + USD·g/360)``), a pair with forward points from them
        (the log premium linear in days, its rate held beyond the last), EURUSD else from the EUR and USD OIS, a cross
        from its USD legs."""
        pair = pair.upper()
        S = self.spot(pair)
        if not S:
            return None, "spot yok"
        sd = self.fx_spot_date(pair)
        g = float((delivery - sd).days)
        if g <= 0:
            return S, "spot"
        a, b = pair[:3], pair[3:]
        if pair == "USDTRY":
            r_usd = self._usd_rate("USD", g)
            if self.off is not None and self.off.ok() and r_usd is not None:
                r_try = self.off.zero_simple(sd, delivery, 360.0)
                if r_try is not None:
                    return S * (1.0 + r_try * g / 360.0) / (1.0 + r_usd * g / 360.0), "offshore eğri + USD OIS"
        pts = self.points.get(pair)
        if pts:
            xs = [0.0] + [d for d, _ in pts]
            ys = [0.0] + [math.log(f / S) for _, f in pts]
            if g >= xs[-1]:
                lp = ys[-1] * g / xs[-1]
            else:
                lp = fxm._lin(g, xs, ys)
            return S * math.exp(lp), "forward puanları"
        if a in self.rates and b in self.rates:
            ra, rb = self._usd_rate(a, g), self._usd_rate(b, g)
            if ra is not None and rb is not None:
                return S * (1.0 + rb * g / 360.0) / (1.0 + ra * g / 360.0), "OIS eğrileri"
        if "USD" not in (a, b):
            f1, w1 = self.forward(a + "USD", delivery)
            f2, w2 = self.forward("USD" + b, delivery)
            s1, s2 = self.spot(a + "USD"), self.spot("USD" + b)
            if f1 and f2 and s1 and s2:
                return S * (f1 / s1) * (f2 / s2), "çapraz (%s, %s)" % (w1, w2)
        inv = b + a
        if inv in self.points or inv == "USDTRY":
            f, why = self.forward(inv, delivery)
            if f:
                return 1.0 / f, why
        return None, "forward yok"

    def df_quote(self, pair: str, delivery: _dt.date) -> Tuple[Optional[float], str]:
        """The quote currency's discount factor from the pair's spot date to ``delivery``: TRY on the offshore curve, USD
        and EUR on their OIS (simple ACT/360), any other through its USD pair's forward (covered interest parity)."""
        pair = pair.upper()
        q = pair[3:]
        sd = self.fx_spot_date(pair)
        g = float((delivery - sd).days)
        if g <= 0:
            return 1.0, ""
        if q == "TRY" and self.off is not None and self.off.ok():
            return self.off.df(delivery) / self.off.df(sd), "offshore TRY"
        r = self._usd_rate(q, g)
        if r is not None:
            return 1.0 / (1.0 + r * g / 360.0), "%s OIS" % q
        r_usd = self._usd_rate("USD", g)
        if r_usd is None:
            return None, "USD OIS yok"
        df_usd = 1.0 / (1.0 + r_usd * g / 360.0)
        f, _ = self.forward("USD" + q, delivery)
        s = self.spot("USD" + q)
        if f and s:
            return df_usd * s / f, "USD OIS + USD%s forward" % q
        return None, "%s iskontosu yok" % q


# ---------------------------------------------------------------------------------------------- reading the dashboard
#: the calendars :func:`check` uses when it is given no market: the last ones :func:`market` / :func:`defaults` read
_LAST: Dict[str, Any] = {}
_LAST_LOCK = threading.Lock()


def _remember(mkt: Market) -> None:
    with _LAST_LOCK:
        _LAST.clear()
        _LAST.update({"cal": dict(mkt.cal), "meetings": dict(mkt.meetings), "today": mkt.today, "bonds": dict(mkt.bonds),
                      "spots": dict(mkt.spots), "lot": mkt.lot})


def _calendars_market(today: Optional[_dt.date] = None) -> Market:
    """A market of the remembered calendars only (what :func:`check` needs without one)."""
    with _LAST_LOCK:
        last = dict(_LAST)
    m = Market(today or last.get("today") or _dt.date.today(), cal=last.get("cal"), meetings=last.get("meetings"),
               bonds=last.get("bonds"), spots=last.get("spots"), lot=last.get("lot"))
    return m


def _ticker_in(book, ref: str, fallback: str) -> str:
    """The security a cell's own BDP call names (``=BDP("BISTTREF Index","PX_LAST")/100``)."""
    from .books import formula_text
    try:
        si, rc = book.cell(ref)
        m = re.search(r'BDP\(\s*"([^"]+)"', formula_text(book, si, rc) or "")
        return m.group(1) if m else fallback
    except Exception:  # noqa: BLE001 - a sheet that is not in this file
        return fallback


def _history(svc, ticker: str, field: str = "PX_LAST") -> Tuple[Dict[str, float], str]:
    """A series' closes as the dashboard's history holds them (the database; offline the replay's recorded closes)."""
    pts: Dict[str, float] = {}
    try:
        pts = {d: v for d, v in svc.store.hist_series("%s|%s" % (ticker, field)) if _num(v) is not None}
    except Exception:  # noqa: BLE001 - no history is no fixings (said)
        pts = {}
    if pts:
        return pts, "tarihçe"
    rec = getattr(getattr(svc, "provider", None), "recorded_history", None)
    if isinstance(rec, dict):
        rows = rec.get((ticker, field)) or []
        pts = {d: float(v) for d, v in rows if _num(v) is not None}
        if pts:
            return pts, "kayıtlı tarihçe"
    return {}, ""


def _quant_values(svc, today: _dt.date) -> Tuple[Dict[str, float], Dict[str, int], str]:
    """The quant package's values of its FX series (spots, forward points, vol quotes, USD OIS 3M): the last fit's -
    live, else the last close -, or the history's last closes when it has not fitted yet.  No Bloomberg request."""
    q = getattr(svc, "quant", None)
    fit = getattr(q, "_fit", None) if q is not None else None
    ctx = fit.get("ctx") if isinstance(fit, dict) else None
    want = ("FX:", "FXP:", "FXV:", "FXR:", "OPT:", "USD:3M")
    if ctx is not None:
        out: Dict[str, float] = {}
        for k in set(ctx.series) | set(ctx.live):
            if k.startswith(want):
                v = _num(ctx.cur(k))
                if v is not None:
                    out[k] = v
        return out, dict(getattr(ctx, "fwd_scale", {}) or {}), "quant"
    try:
        from . import quant as qm
        try:
            source = svc.fx.source()
        except Exception:  # noqa: BLE001
            source = fxm.DEFAULT_SOURCE
        specs = [s for s in qm.series_specs(source, qm.fx_pair_list(svc.store)) if s["key"].startswith(want)]
    except Exception:  # noqa: BLE001 - a store without the settings: nothing of the quant's
        return {}, {}, ""
    ids = {s["key"]: "%s|%s" % (s["ticker"], s.get("field", "PX_LAST")) for s in specs}
    try:
        data = svc.store.hist_many(sorted(set(ids.values())), (today - _dt.timedelta(days=21)).isoformat(), today.isoformat())
    except Exception:  # noqa: BLE001
        return {}, {}, ""
    out = {}
    for k, sid in ids.items():
        pts = data.get(sid) or {}
        if pts:
            v = _num(pts[max(pts)])
            if v is not None:
                out[k] = v
    return out, {}, "tarihçe" if out else ""


def _outright(pair: str, spot: float, quote: float, scales: Dict[str, int]) -> Optional[float]:
    """A forward quote as an outright (``quantfam.Ctx.forward``): near the spot already one, else points of
    10^-FWD_SCALE (2 for the yen, 4 else)."""
    if 0.8 * spot <= quote <= 1.25 * spot:
        return quote
    scale = scales.get(pair, 2 if pair.endswith("JPY") else 4)
    f = spot + quote * 10.0 ** (-scale)
    return f if f > 0 else None


def market(svc) -> Market:
    """One snapshot of what valuation needs, read from the shared (desk) calculation of the workbooks on the engine
    thread (run there; already there, at once) and from the history: the TRY OIS curve and its quotes, the SOFR curve,
    the fixings, the holiday lists and meeting calendars, the FX spots / curves / forward points / vol quotes, the bond
    prices.  Nothing here asks Bloomberg: the cells are the workbooks' own (asked for already), the rest the history's
    and the quant package's last values."""
    raw = svc.et.call(_read_engine, svc)
    today = raw["today"]
    notes: List[str] = list(raw["notes"])
    tl_pts, tl_src = _history(svc, raw["tlref_ticker"])
    if not tl_pts:
        notes.append("TLREF fixingleri tarihçede yok: başlamış OIS'in gerçekleşen kısmı bugünkü TLREF ile")
    sofr_pts, sofr_src = _history(svc, raw["sofr_ticker"]) if raw.get("sofr_ticker") else ({}, "")
    if raw.get("sofr_ticker") and not sofr_pts:
        notes.append("SOFR fixingleri tarihçede yok: başlamış SOFR swap'ın gerçekleşen kısmı bugünkü SOFR fixing'iyle")
    qv, scales, qsrc = _quant_values(svc, today)
    cal = raw["cal"]
    fixings = {"ois": Fixings(tl_pts, raw["tlref"], cal.get("TRY"), 365.0, "TLREF", tl_src),
               "sofr": Fixings(sofr_pts, raw.get("sofr_on"), cal.get("SIFMA"), 360.0, raw.get("sofr_name") or "SOFR", sofr_src)}
    spots = dict(raw["spots"])
    for k, v in qv.items():
        if k.startswith("FX:"):
            spots.setdefault(k[3:], v)
    mkt = Market(today, curves=raw["curves"], fixings=fixings, cal=cal, quotes=raw["quotes"], meetings=raw["meetings"],
                 spots=spots, rates=raw["rates"], off=raw.get("off"), bonds=raw["bonds"], usdtry=raw.get("usdtry"),
                 lot=raw.get("lot"), notes=notes, sources={"quant": qsrc, "tlref": tl_src, "sofr": sofr_src},
                 on_rates=raw.get("on_rates"))
    # forward points (G10 3M, EURUSD 1M / 3M): outright forwards at their delivery days from the pair's spot date
    pts: Dict[str, List[Tuple[float, float]]] = {}
    for k, v in qv.items():
        if not k.startswith("FXP:"):
            continue
        _, pair, tenor = k.split(":")
        if pair == "USDTRY":
            continue                                       # (USDTRY: the TRY workbook's offshore curve)
        s = mkt.spot(pair)
        f = _outright(pair, s, v, scales) if s else None
        if f is None or tenor not in fxm.TENOR_SPEC:
            continue
        sd = mkt.fx_spot_date(pair)
        day = fxm.delivery(sd, tenor, mkt.pair_hol(pair))
        pts.setdefault(pair, []).append((float((day - sd).days), f))
    mkt.points = {p: sorted(v) for p, v in pts.items()}
    # vol quotes: the Opsiyon page's (USDTRY, EURUSD) and the G10 universe's, by pair and tenor (vol points)
    from . import quantopt as qopt
    vols: Dict[str, Dict[str, Dict[str, float]]] = {}
    for pair in set(SVI_PAIRS) | {k.split(":")[1] for k in qv if k.startswith(("FXV:", "FXR:", "OPT:"))}:
        for tenor in _VOL_DAYS:
            for kind in _KINDS:
                v = qv.get(qopt.key(pair, kind, tenor))
                if v is not None:
                    vols.setdefault(pair, {}).setdefault(tenor, {})[kind] = v
    mkt.vols = vols
    _remember(mkt)
    return mkt


def _read_engine(svc) -> Dict[str, Any]:
    """The workbooks' part of :func:`market` (engine thread): cells of the shared calculation only."""
    from . import borsaspread as bsp
    from . import meetings as mt
    from .xl.model import COLS
    from .xl.values import serial_to_date
    out: Dict[str, Any] = {"curves": {}, "quotes": {}, "meetings": {}, "spots": {}, "rates": {}, "bonds": {}, "notes": [],
                           "cal": {}, "tlref": None, "tlref_ticker": "BISTTREF Index", "today": _dt.date.today()}
    book = svc.books.get("tto")
    if book is None:
        out["notes"].append("TRY çalışma kitabı yok")
        return out
    calc = book.engine.shared
    today = serial_to_date(book.engine.clock.today())
    out["today"] = today
    idx = book.model.sheet_index

    def cell(ref: str, b=book, c=calc) -> Any:
        try:
            si, rc = b.cell(ref)
            return c.get(si, *divmod(rc, COLS))
        except Exception:  # noqa: BLE001 - a sheet that is not in this file
            return None

    def day(v: Any) -> Optional[_dt.date]:
        return serial_to_date(v) if type(v) is float and 20000 < v < 80000 else (_day(v) if isinstance(v, str) else None)

    # ---- holiday lists: the desk's (TRY: Motor; USD / EUR: EK_TATIL) and the USD book's SIFMA list
    for ccy in ("TRY", "USD", "EUR"):
        try:
            out["cal"][ccy] = frozenset(serial_to_date(float(s)) for s in svc._calendar_serials((ccy,)))
        except Exception:  # noqa: BLE001 - a workbook without the list: weekends only
            out["cal"][ccy] = frozenset()
    # ---- TRY OIS: BOOT, the OIS spot, TLREF, the quotes, the meetings
    spot = day(cell("OIS_MAIN!B2"))
    gun, lndf = bsp._named(book, calc, "BOOT_GUN"), bsp._named(book, calc, "BOOT_LNDF")
    tl = _num(cell("OIS_MAIN!J2"))
    out["tlref"] = tl
    out["tlref_ticker"] = _ticker_in(book, "OIS_MAIN!J2", "BISTTREF Index")
    if spot and gun and lndf:
        out["curves"]["ois"] = Curve(spot, gun, lndf, tl, 365.0, "lndf", "BOOT")
    else:
        out["notes"].append("TRY OIS eğrisi (BOOT) okunamadı")
    quotes: Dict[str, float] = {}
    for r in range(9, 27):
        lab, v = cell("OIS_MAIN!A%d" % r), _num(cell("OIS_MAIN!B%d" % r))
        if isinstance(lab, str) and lab.strip() and v is not None:
            quotes[lab.strip().upper()] = v * 100.0
    for lab, ref in (("1W", "OIS_MAIN!AU13"), ("2W", "OIS_MAIN!AU14")):
        v = _num(cell(ref))
        if v is not None:
            quotes[lab] = v * 100.0
    out["quotes"]["ois"] = quotes
    try:
        out["meetings"]["ois"] = [d for d in mt.slot_dates(book, mt.TCMB, calc) if d]
    except Exception:  # noqa: BLE001
        out["meetings"]["ois"] = []
    out["usdtry"] = _num(cell("OIS_MAIN!D2"))
    lot = _num(cell("OIS_MAIN!H2"))
    out["lot"] = lot if lot and lot > 0 else LOT
    # ---- FX: the desk's spots, the USD / EUR OIS of the Forward sheet, the offshore TRY curve
    for pair, ref in (("USDTRY", "Forward!F2"), ("EURTRY", "Forward!G2")):
        v = _num(cell(ref))
        if v and v > 0:
            out["spots"][pair] = v
    for ccy, dcol, rcol in (("USD", "U", "X"), ("EUR", "AA", "AD")):
        pts = []
        for r in range(7, 27):
            d, v = _num(cell("Forward!%s%d" % (dcol, r))), _num(cell("Forward!%s%d" % (rcol, r)))
            if d is not None and v is not None and d > 0:
                pts.append((d, v))
        if pts:
            out["rates"][ccy] = pts
    on: Dict[str, float] = {}
    for ccy, ref, scale in (("TRY", "Forward!AC123", 100.0), ("USD", "Forward!X6", 1.0), ("EUR", "Forward!AD6", 1.0)):
        v = _num(cell(ref))
        if v is not None:
            on[ccy] = v * scale
    out["on_rates"] = on
    try:
        off = bsp.read_curves(book, calc).get("off")
        if off is not None and not off.why and off.spot is not None:
            out["off"] = Curve(serial_to_date(off.spot), off.days, off.lndf, off.on, 360.0, "lndf", "offshore")
    except Exception:  # noqa: BLE001 - no offshore curve: USDTRY forwards from nothing else (said on the trade)
        pass
    # ---- bonds: DİBS RV's rows and Tüm Kâğıtlar's, by ISIN
    out["bonds"] = _read_bonds(cell, day, idx)
    # ---- the USD book: SOFR curve, its fixing, quotes, SIFMA and FOMC lists
    sofr = svc.books.get("sofr")
    if sofr is not None and "SOFR_FOMC" in sofr.model.sheet_index:
        sc = sofr.engine.shared

        def scell(ref: str) -> Any:
            return cell(ref, sofr, sc)

        sifma = set()
        for r in range(4, 71):
            d = day(scell("SOFR_FOMC!BO%d" % r))
            if d:
                sifma.add(d)
        out["cal"]["SIFMA"] = frozenset(sifma)
        sspot = day(scell("SOFR_FOMC!B5"))
        interp = "lndf" if str(scell("SOFR_FOMC!B10") or "").strip().lower().startswith("düz") else "zero"
        on = _num(scell("SOFR_FOMC!B6"))
        days, ln = [], []
        for r in range(48, 69):
            use, t, x = scell("SOFR_FOMC!G%d" % r), _num(scell("SOFR_FOMC!K%d" % r)), _num(scell("SOFR_FOMC!M%d" % r))
            if use in (1.0, True) and t is not None and x is not None:
                days.append(t)
                ln.append(x)
        if sspot and len(days) >= 2:
            out["curves"]["sofr"] = Curve(sspot, days, ln, on / 100.0 if on is not None else None, 360.0, interp, "SOFR")
        else:
            out["notes"].append("SOFR eğrisi okunamadı")
        sq: Dict[str, float] = {}
        for r in range(49, 69):
            lab, v = scell("SOFR_FOMC!A%d" % r), _num(scell("SOFR_FOMC!E%d" % r))
            if isinstance(lab, str) and lab.strip() and v is not None:
                sq[lab.strip().upper()] = v
        out["quotes"]["sofr"] = sq
        out["sofr_on"] = on / 100.0 if on is not None else None
        ff = str(scell("SOFR_FOMC!B11") or "").strip().upper() == "FF OIS"
        out["sofr_ticker"] = "FEDL01 Index" if ff else "SOFRRATE Index"
        out["sofr_name"] = "Fed funds" if ff else "SOFR"
        try:
            out["meetings"]["sofr"] = [d for d in mt.slot_dates(sofr, mt.FED, sc) if d]
        except Exception:  # noqa: BLE001
            out["meetings"]["sofr"] = []
    else:
        out["notes"].append("USD SOFR çalışma kitabı yok")
    return out


#: DİBS RV's columns read per bond (row 5 to 54): the trading list's own numbers
_RV = (("source", "BS"), ("name", "C"), ("type", "D"), ("maturity", "E"), ("clean", "O"), ("value_date", "P"), ("accrued", "Q"),
       ("dirty", "R"), ("simple", "S"), ("compound", "T"), ("dv01_mn", "AI"), ("coupon", "CS"), ("freq", "CU"))
_RV_KIND = {"S": "fixed", "B": "bill", "T": "float", "F": "frn", "E": "cpi"}


def _read_bonds(cell: Callable[[str], Any], day: Callable[[Any], Optional[_dt.date]], idx: Dict[str, int]) -> Dict[str, Dict[str, Any]]:
    from . import extras as ex
    out: Dict[str, Dict[str, Any]] = {}
    if "DİBS RV" in idx:
        for r in range(5, 55):
            isin = cell("DİBS RV!A%d" % r)
            if not isinstance(isin, str) or not isin.strip():
                continue
            row: Dict[str, Any] = {"isin": isin.strip().upper(), "where": "DİBS RV"}
            for f, col in _RV:
                v = cell("DİBS RV!%s%d" % (col, r))
                if f in ("maturity", "value_date"):
                    d = day(v)
                    row[f] = d.isoformat() if d else None
                elif f in ("source", "name", "type"):
                    row[f] = v.strip() if isinstance(v, str) else ""
                else:
                    row[f] = _num(v)
            row["kind"] = _RV_KIND.get(row["type"].upper()) if row.get("type") else None
            out[row["isin"]] = row
    if ex.UNI_SHEET in idx:
        sh = ex.UNI_SHEET
        for r in range(ex.UNI_FIRST, ex.UNI_LAST + 1):
            isin = cell("%s!A%d" % (sh, r))
            if not isinstance(isin, str) or not isin.strip():
                continue
            code = isin.strip().upper()
            bid, ask, last = (_num(cell("%s!%s%d" % (sh, c, r))) for c in ("I", "J", "K"))
            clean = (bid + ask) / 2.0 if bid and ask else (last if last else None)
            kind = cell("%s!%s%d" % (sh, ex.UNI_KIND, r))
            src = cell("%s!R%d" % (sh, r))
            mat = day(cell("%s!E%d" % (sh, r)))
            cpn = _num(cell("%s!D%d" % (sh, r)))
            uni = {"isin": code, "where": "Tüm Kâğıtlar", "name": cell("%s!B%d" % (sh, r)) or "", "kind": kind if isinstance(kind, str) and kind else None,
                   "maturity": mat.isoformat() if mat else None, "coupon": cpn * 100.0 if cpn is not None and cpn < 1.5 else cpn,
                   "clean": clean, "price_how": "bid / ask ortası" if bid and ask else ("son işlem" if last else ""),
                   "source": src.strip().upper() if isinstance(src, str) else ""}
            have = out.get(code)
            if have is None:
                out[code] = uni
            else:
                have.setdefault("uni", uni)
                if have.get("clean") is None and clean is not None:
                    have["clean"], have["where"] = clean, "Tüm Kâğıtlar"
    return out


# ---------------------------------------------------------------------------------------------- the meeting periods
def effective_day(decision: _dt.date, hol: Any) -> _dt.date:
    """A decision's effective day: the business day after it (Motor!C5: ``Sonraki iş günü`` of the decision + 1)."""
    return _add_bd(decision, 1, hol)


def meeting_periods(mkt: Market, prod: str) -> List[Dict[str, Any]]:
    """The meeting periods of a rate product, keyed by date: from each meeting's effective day to the next one's
    (TCMB's list for TRY, the FOMC's for USD) - those that start at the spot or later."""
    conv = CONVS[prod]
    hol = mkt.hol(*conv.cal)
    dates = sorted({_day(d) for d in mkt.meetings.get(prod) or [] if _day(d)})
    spot = mkt.spot_date(prod)
    out = []
    for a, b in zip(dates, dates[1:]):
        s, e = effective_day(a, hol), effective_day(b, hol)
        if s < spot:
            continue
        out.append({"mpc_date": a.isoformat(), "mpc_end": b.isoformat(), "value_date": s.isoformat(), "end_date": e.isoformat(),
                    "label": "%s %s–%s" % (conv.meetings_name, _short(s), _short(e))})
        if len(out) >= MEETING_PERIODS:
            break
    return out


#: how many meeting periods :func:`defaults` offers (about two years of TCMB meetings)
MEETING_PERIODS = 16


# ---------------------------------------------------------------------------------------------- rates: one swap
class _Leg(object):
    """One fixed-for-overnight swap: ``sign`` +1 receives the fixed rate (decimal), −1 pays it; ``close_date`` /
    ``close_rate``: unwound then at that rate - from there on only the fixed difference is left (the floats cancel)."""

    __slots__ = ("start", "end", "rate", "notional", "sign", "months", "label", "close_date", "close_rate")

    def __init__(self, start: _dt.date, end: _dt.date, rate: float, notional: float, sign: float, months: Optional[int] = None,
                 label: str = "", close_date: Optional[_dt.date] = None, close_rate: Optional[float] = None):
        self.start, self.end, self.rate, self.notional, self.sign = start, end, rate, notional, sign
        self.months, self.label = months, label
        self.close_date, self.close_rate = close_date, close_rate


def _swap_pv(mkt: Market, prod: str, leg: _Leg, asof: _dt.date, curve: Optional[Curve] = None,
             fix: Optional[Fixings] = None, tally: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """A fixed-for-overnight swap at ``asof``: MTM (fixed − float, signed), the cash of its settled periods, the
    annuity of the periods to come (Σ τ × DF, today) and their float leg's value - on ``curve`` (the market's)."""
    conv = CONVS[prod]
    hol = mkt.hol(*conv.cal)
    curve = curve or mkt.curves.get(prod)
    fix = fix or mkt.fixings.get(prod)
    if curve is None or not curve.ok():
        raise TradeError("%s eğrisi yok" % conv.label)
    N, K = leg.notional, leg.rate
    closed, Kc = leg.close_date, leg.close_rate
    dfa = curve.df(asof)
    pv_fix = pv_flt = ann = acc = 0.0

    def grown(x: _dt.date, y: _dt.date) -> float:
        """The overnight compounded from x to y: the fixings up to today, the curve after it."""
        if y <= asof:
            f = fix.compound(x, y, asof, tally) if fix is not None else None
        elif x >= asof:
            f = curve.df(x) / curve.df(y)
        else:
            f0 = fix.compound(x, asof, asof, tally) if fix is not None else None
            f = f0 * curve.df(asof) / curve.df(y) if f0 is not None else None
        if f is None:
            raise TradeError("%s fixing'i yok (%s)" % (conv.float_name, _short(x)))
        return f

    def unwound(a: _dt.date, b: _dt.date) -> float:
        """A period's payment once the swap is unwound at ``closed``: the swap's own up to the close, the fixed
        difference after it (the floats cancel)."""
        if a >= closed:
            return N * (K - Kc) * (b - a).days / conv.basis
        return N * (K * (closed - a).days / conv.basis - (grown(a, closed) - 1.0)) + N * (K - Kc) * (b - closed).days / conv.basis

    for a, b in schedule(leg.start, leg.end, conv, hol, leg.months):
        tau = (b - a).days / conv.basis
        after = closed is not None and b > closed
        if b <= asof:
            acc += unwound(a, b) if after else N * (K * tau - (grown(a, b) - 1.0))
            continue
        d_b = curve.df(b) / dfa
        ann += tau * d_b
        if after:
            pv_fix += unwound(a, b) * d_b
            continue
        pv_fix += N * K * tau * d_b
        if a >= asof:
            pv_flt += N * (curve.df(a) / dfa - d_b)
        else:
            f = fix.compound(a, asof, asof, tally) if fix is not None else None
            if f is None:
                raise TradeError("%s fixing'i yok (%s)" % (conv.float_name, _short(a)))
            pv_flt += N * (f - d_b)
    s = leg.sign
    return {"mtm": s * (pv_fix - pv_flt) + 0.0, "accrued": s * acc + 0.0, "annuity": ann, "float": pv_flt,
            "par": pv_flt / (N * ann) if ann > 0 and N else None}


def _swap(mkt: Market, prod: str, leg: _Leg, asof: _dt.date) -> Dict[str, Any]:
    """A swap's MTM, accrued and carry over the day (to the next business day, ``carry_days`` calendar days):

    * the **accrual** - the fixed rate against today's overnight on the period's compounded notional:
      sign × N × (K − I × r_ON) × days / basis, I the period's overnight compounded so far (none before the start);
    * the **roll-down** - what the curve keeping its shape earns over the forwards coming true: the trade tomorrow on
      the curve rolled to tomorrow's spot (the same zero rate for the same days from it, today's overnight fixed),
      less what it is worth tomorrow when today's forwards realise (today's value grown at the curve's overnight).
      Nothing on a flat curve."""
    conv = CONVS[prod]
    hol = mkt.hol(*conv.cal)
    tally: Dict[str, int] = {}
    base = _swap_pv(mkt, prod, leg, asof, tally=tally)
    curve, fix = mkt.curves[prod], mkt.fixings.get(prod)
    nxt = _add_bd(asof, 1, hol)
    days = (nxt - asof).days
    on = curve.on if curve.on is not None else (fix.live if fix is not None else None)
    accrual = 0.0
    lo, hi = max(asof, leg.start), min(nxt, leg.end)
    acc_days = max(0, (hi - lo).days)
    if on is not None and acc_days and leg.close_date is None:
        comp = 1.0
        if leg.start < asof and fix is not None:
            cur = next(((a, b) for a, b in schedule(leg.start, leg.end, conv, hol, leg.months) if a <= asof < b), None)
            if cur is not None and cur[0] < asof:
                comp = fix.compound(cur[0], asof, asof) or 1.0
        accrual = leg.sign * leg.notional * (leg.rate - comp * on) * acc_days / conv.basis
    spot1 = _add_bd(nxt, conv.lag, hol)
    extra = {asof + _dt.timedelta(days=k): on for k in range(days)} if on is not None else {}
    fix1 = fix.with_days(extra) if fix is not None else None
    tomorrow = _swap_pv(mkt, prod, leg, nxt, curve=curve.rolled(spot1), fix=fix1)
    growth = curve.df(asof) / curve.df(nxt)
    roll = (tomorrow["mtm"] + tomorrow["accrued"]) - (base["mtm"] * growth + base["accrued"])
    dv01 = leg.notional * base["annuity"] * 1e-4
    return {"mtm": base["mtm"], "accrued": base["accrued"], "carry": accrual + roll, "carry_accrual": accrual, "roll": roll,
            "carry_days": days, "annuity": base["annuity"], "dv01": dv01, "par": base["par"], "tally": tally, "on": on}


def _par_rate(mkt: Market, prod: str, start: _dt.date, end: _dt.date, months: Optional[int] = None) -> Optional[float]:
    """The curve's par rate (decimal) of a swap from ``start`` (the spot when it is past) to ``end``."""
    s = max(start, mkt.spot_date(prod))
    if not end > s:
        return None
    try:
        res = _swap_pv(mkt, prod, _Leg(s, end, 0.0, 1.0, 1.0, months if s == start else None), mkt.today)
    except TradeError:
        return None
    return res["par"]


# ---------------------------------------------------------------------------------------------- rates: the trade
def _rate_label(prod: str, start: _dt.date, end: _dt.date, months: Optional[int], spot: _dt.date) -> str:
    """A swap as the desk names it: by its tenor while it starts at today's spot ("2Y OIS"), else by its end date (a
    started or forward-starting one: its rate is the curve's to that date, "OIS 06.11.28")."""
    conv = CONVS[prod]
    if months and start == spot:
        return "%s %s" % (tenor_label(months), conv.label)
    return "%s %s" % (conv.label, _short(end))


def _pkg_name(labels: Sequence[str]) -> str:
    """A package as the quant names one: "2s5s", "2s5s10s" for years, "6M/1Y" otherwise (quantfam's head)."""
    if labels and all(x.upper().endswith("Y") for x in labels):
        return "".join("%ss" % x[:-1] for x in labels)
    return "/".join(x.upper() for x in labels)


def _leg_months(lg: Dict[str, Any], start: _dt.date, end: _dt.date) -> Optional[int]:
    m = lg.get("tenor_months")
    if m:
        return int(m)
    return tenor_months(lg.get("tenor")) if lg.get("tenor") else None


def _value_rates(t: Dict[str, Any], mkt: Market, asof: _dt.date) -> Dict[str, Any]:
    prod = t["product"]
    conv = CONVS[prod]
    if prod not in mkt.curves:
        raise TradeError("%s eğrisi yok" % conv.label)
    structure = t.get("structure") or "outright"
    spot = mkt.spot_date(prod)
    ccy = conv.ccy
    closed = t.get("status") == "closed" and _num(t.get("close_price")) is not None
    out_legs: List[Dict[str, Any]] = []
    inputs: Dict[str, Any] = {"curve": mkt.curves[prod].name, "spot": _iso(mkt.curves[prod].spot), "basis": "ACT/%d" % conv.basis,
                              "float": conv.float_name, "structure": structure}

    def run(lg: _Leg) -> Dict[str, Any]:
        r = _swap(mkt, prod, lg, asof)
        par_now = _par_rate(mkt, prod, lg.start, lg.end, lg.months)
        r["price_now"] = par_now * 100.0 if par_now is not None else None
        if lg.close_date is not None:
            r["carry"] = r["carry_accrual"] = r["roll"] = 0.0          # (unwound: nothing left to earn)
        return r

    def closing(src: Dict[str, Any]) -> Tuple[Optional[_dt.date], Optional[float]]:
        if src.get("status", t.get("status")) == "closed" and _num(src.get("close_price")) is not None:
            return (_day(src.get("close_date") or t.get("close_date")) or asof), float(src["close_price"]) / 100.0
        return None, None

    start = _day(t.get("value_date") or t.get("settle_date"))
    sign = 1.0 if t.get("side") == "S" else -1.0                 # (S receives the fixed rate, B pays it)
    if structure in ("outright", "mpc", "fra"):
        end = _day(t.get("end_date"))
        months = int(t["tenor_months"]) if t.get("tenor_months") else (tenor_months(t.get("tenor")) if t.get("tenor") else None)
        K = float(t["price"]) / 100.0
        cd, cr = closing(t)
        main = _Leg(start, end, K, float(t["notional"]), sign, months if structure == "outright" else None, "", cd, cr)
        res = run(main)
        if closed:
            inputs["closed"] = {"date": _iso(cd), "rate": t["close_price"], "note": "kapanış faiziyle: kalan dönemlerde sabit faiz farkı"}
        if structure == "mpc":
            label = "%s %s–%s" % (conv.meetings_name, _short(start), _short(end))
        elif structure == "fra":
            label = _fra_label(t, start, end) + " FRA"
        else:
            label = _rate_label(prod, start, end, months, spot)
        price = res["price_now"]
        total = {"mtm": res["mtm"], "accrued": res["accrued"], "carry": res["carry"], "price_now": price,
                 "price_text": "%s %s%%" % (label, _tr(price, 2)) if price is not None else label}
        inputs.update({"start": _iso(start), "end": _iso(end), "rate": t["price"], "par_now": price, "annuity": res["annuity"],
                       "dv01": res["dv01"], "carry_accrual": res["carry_accrual"], "roll_1d": res["roll"],
                       "carry_days": res["carry_days"], "overnight": res["on"] * 100.0 if res["on"] is not None else None,
                       "fixings": res["tally"], "notes": _fixing_notes(conv, res["tally"], mkt.fixings.get(prod))})
        if structure == "fra" and cd is None:
            # the attribution: the two swaps that replicate it, from the trade's own settlement - to its end the
            # FRA's way, to its start the other way, the same notional and rate
            settle = _day(t.get("settle_date")) or start
            if start > settle:
                a = _Leg(settle, end, K, float(t["notional"]), sign)
                b = _Leg(settle, start, K, float(t["notional"]), -sign)
                parts = []
                for lg, code in ((a, t["side"]), (b, "B" if t["side"] == "S" else "S")):
                    parts.append((lg, run(lg), code))
                for lg, r, code in parts:
                    out_legs.append(_leg_out(mkt, ccy, "%s %s %s" % (side_text(prod, code).capitalize(), conv.label, _short(lg.end)), r,
                                             "%s %s %s%%" % (conv.label, _short(lg.end), _tr(r["price_now"], 2)) if r["price_now"] is not None else "",
                                             prod, code))
                inputs["residual"] = {"mtm": res["mtm"] - sum(r["mtm"] for _, r, _ in parts),
                                      "carry": res["carry"] - sum(r["carry"] for _, r, _ in parts),
                                      "accrued": res["accrued"] - sum(r["accrued"] for _, r, _ in parts)}
        return _finish(mkt, t, ccy, total, inputs, out_legs)
    # ---- spread / fly: the sum of the legs
    legs = t.get("legs") or []
    results = []
    for lg in legs:
        lstart = _day(lg.get("value_date")) or start
        lend = _day(lg.get("end_date"))
        months = _leg_months(lg, lstart, lend)
        K = float(lg["price"]) / 100.0
        lsign = 1.0 if lg.get("side") == "S" else -1.0
        cd, cr = closing(lg)                               # (a package closes leg by leg: each leg's close price)
        L = _Leg(lstart, lend, K, float(lg["notional"]), lsign, months, "", cd, cr)
        r = run(L)
        name = _rate_label(prod, lstart, lend, months, spot)
        results.append((lg, L, r, name, months))
    tenor_names = [tenor_label(m) if m else _short(L.end) for _, L, _, _, m in results]
    pars = [r["price_now"] for _, _, r, _, _ in results]
    level = None
    sheet = None
    if all(p is not None for p in pars):
        if structure == "spread":
            level = (pars[1] - pars[0]) * 100.0            # long − short, bp
        elif len(pars) == 3:
            level = (pars[1] - 0.5 * (pars[0] + pars[2])) * 100.0   # body − ½ each wing: the 50/50 package's
            sheet = 2.0 * level                            # the OIS sheet's 2·body − wings quote
    traded = [float(lg["price"]) for lg, _, _, _, _ in results]
    if structure == "spread":
        traded_level = (traded[1] - traded[0]) * 100.0
    else:
        traded_level = (traded[1] - 0.5 * (traded[0] + traded[2])) * 100.0
    pkg = _pkg_name(tenor_names) + (" fly" if structure == "fly" and not all(x.upper().endswith("Y") for x in tenor_names) else "")
    if level is None:
        text = pkg
    elif structure == "fly":
        text = "%s %s bp (%s sayfasında %s)" % (pkg, _tr(level, 1), conv.label, _tr(sheet, 1))
    else:
        text = "%s %s bp" % (pkg, _tr(level, 1))
    for lg, L, r, name, _ in results:
        verb = side_text(prod, lg.get("side")).capitalize()
        out_legs.append(_leg_out(mkt, ccy, "%s %s" % (verb, name), r,
                                 "%s %s%%" % (name, _tr(r["price_now"], 2)) if r["price_now"] is not None else name, prod, lg.get("side")))
    total = {"mtm": sum(r["mtm"] for _, _, r, _, _ in results), "accrued": sum(r["accrued"] for _, _, r, _, _ in results),
             "carry": sum(r["carry"] for _, _, r, _, _ in results), "price_now": level, "price_text": text}
    tally: Dict[str, int] = {}
    for _, _, r, _, _ in results:
        for k, v in r["tally"].items():
            tally[k] = tally.get(k, 0) + v
    inputs.update({"level_bp": level, "traded_bp": traded_level, "sheet_bp": sheet,
                   "traded_sheet_bp": 2.0 * traded_level if structure == "fly" else None,
                   "dv01_net": sum(-r["dv01"] if L.sign > 0 else r["dv01"] for _, L, r, _, _ in results),
                   "carry_days": results[0][2]["carry_days"] if results else None,
                   "carry_accrual": sum(r["carry_accrual"] for _, _, r, _, _ in results),
                   "roll_1d": sum(r["roll"] for _, _, r, _, _ in results),
                   "legs_dv01": [r["dv01"] for _, _, r, _, _ in results], "fixings": tally,
                   "notes": _fixing_notes(conv, tally, mkt.fixings.get(prod))})
    return _finish(mkt, t, ccy, total, inputs, out_legs)


def _fixing_notes(conv: Conv, tally: Dict[str, int], fix: Optional[Fixings]) -> List[str]:
    """What the realised part of the float leg was made of, when it was not all fixings."""
    out = []
    if tally.get("none"):
        out.append("%s fixingleri tarihçede yok: gerçekleşen %d gün bugünkü %s ile (eğri değil, yaklaşık)"
                   % (conv.float_name, tally["none"], conv.float_name))
    if tally.get("prev"):
        out.append("%d günün %s fixing'i yok: önceki fixing'le" % (tally["prev"], conv.float_name))
    return out


def _fra_label(t: Dict[str, Any], start: _dt.date, end: _dt.date) -> str:
    spec = str(t.get("fra") or "").strip().lower()
    if re.match(r"^\d{1,3}\s*x\s*\d{1,3}$", spec):
        return spec.replace(" ", "")
    return "%s–%s" % (_short(start), _short(end))


def _money(mkt: Market, ccy: str, v: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if v is None:
        return None, None
    tp, up = mkt.try_per(ccy), mkt.usd_per(ccy)
    return (v * tp if tp else None), (v * up if up else None)


def side_text(prod: str, side: Any) -> str:
    """A side code in words: an OIS / SOFR "S" "receive", "B" "pay"; a bond's / FX "B" "buy", "S" "sell"."""
    return SIDE_TEXT["rates" if prod in RATES else "other"].get(str(side or ""), "")


def _leg_out(mkt: Market, ccy: str, label: str, r: Dict[str, Any], text: str, prod: str = "", side: Any = None) -> Dict[str, Any]:
    m_try, m_usd = _money(mkt, ccy, r["mtm"])
    c_try, c_usd = _money(mkt, ccy, r["carry"])
    return {"label": label, "side": side, "side_text": side_text(prod, side), "mtm": r["mtm"], "mtm_try": m_try, "mtm_usd": m_usd,
            "carry_1d": r["carry"], "carry_1d_try": c_try, "carry_1d_usd": c_usd, "price_now": r.get("price_now"), "price_text": text}


def _finish(mkt: Market, t: Dict[str, Any], ccy: str, total: Dict[str, Any], inputs: Dict[str, Any],
            legs: Optional[List[Dict[str, Any]]] = None, greeks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    m_try, m_usd = _money(mkt, ccy, total["mtm"])
    c_try, c_usd = _money(mkt, ccy, total["carry"])
    out = {"ok": True, "why": None, "ccy": ccy, "mtm": total["mtm"], "mtm_try": m_try, "mtm_usd": m_usd,
           "carry_1d": total["carry"], "carry_1d_try": c_try, "carry_1d_usd": c_usd, "accrued": total.get("accrued"),
           "price_now": total.get("price_now"), "price_text": total.get("price_text") or "", "greeks": greeks, "inputs": inputs,
           "side": t.get("side"), "side_text": side_text(t.get("product", ""), t.get("side"))}
    if legs:
        out["legs"] = legs
    return out


# ---------------------------------------------------------------------------------------------- bonds
def _bond_of(mkt: Market, isin: str) -> Tuple[Optional[qc.Bond], Dict[str, Any], str]:
    """A bond as DİBS RV prices it (BIST rule): static data from its row, Tüm Kâğıtlar or the catalog."""
    from . import bonds as bd
    row = mkt.bonds.get(isin) or {}
    uni = row.get("uni") or (row if row.get("where") == "Tüm Kâğıtlar" else {})
    cat = bd.by_isin(isin) or {}
    kind = row.get("kind") or uni.get("kind") or cat.get("kind")
    mat = row.get("maturity") or uni.get("maturity") or cat.get("maturity")
    if not mat:
        m = bd.maturity_of(isin)
        mat = m.isoformat() if m else None
    if not kind or not mat:
        return None, row, "kâğıt bilinmiyor (tür / vade yok)"
    coupon = row.get("coupon") if _num(row.get("coupon")) is not None else (uni.get("coupon") if _num(uni.get("coupon")) is not None else cat.get("coupon"))
    freq = row.get("freq") or 2
    name = row.get("name") or uni.get("name") or cat.get("name") or isin
    plain = "bill" if kind in ("bill", "zero") else "fixed"
    if plain == "fixed" and not _num(coupon):
        return None, row, "kuponu bilinmiyor"
    return qc.Bond(isin, str(name), plain, _dt.date.fromisoformat(mat), float(coupon or 0.0), int(freq) if freq and freq >= 1 else 2), \
        dict(row, kind=kind), ""


def _value_code(src: str) -> int:
    """A Borsa source's settlement lag: ISL0 the same day, ISL1 the next business day, ISLN / ISL2 two."""
    s = (src or "").strip().upper()
    if s == "ISL0":
        return 0
    if s in ("ISLN", "ISL2"):
        return 2
    return 1


def bond_settle(mkt: Market, isin: str, day: _dt.date) -> _dt.date:
    """A bond's settlement as the desk trades it on ``day``: DİBS RV's value date rule (``IF(B="ISL0", TODAY(),
    WORKDAY(TODAY(), 1, TRY))``), Tüm Kâğıtlar's sources (bills and zero coupons ISL0, the rest ISL1) for the others."""
    from . import bonds as bd
    row = mkt.bonds.get(isin) or {}
    src = row.get("source") or (row.get("uni") or {}).get("source")         # (DİBS RV!BS, else Tüm Kâğıtlar!R)
    if not src:
        kind = row.get("kind") or (bd.by_isin(isin) or {}).get("kind")
        src = "ISL0" if kind in ("bill", "zero") else "ISL1"
    return _add_bd(day, _value_code(src), mkt.hol("TRY"))


def _coupons(bond: qc.Bond, after: _dt.date, upto: _dt.date) -> float:
    """What a holder receives per 100 between two value dates: the coupons dated after ``after`` up to ``upto`` (the
    redemption with the last)."""
    if bond.kind == "bill":
        return 100.0 if after < bond.maturity <= upto else 0.0
    flows, _ = bond.flows(after)
    return sum(cf for d, cf in flows if after < d <= upto)


def _value_dibs(t: Dict[str, Any], mkt: Market, asof: _dt.date) -> Dict[str, Any]:
    isin = t["isin"]
    bond, row, why = _bond_of(mkt, isin)
    if bond is None:
        raise TradeError(why)
    kind = row.get("kind")
    if kind == "cpi":
        raise TradeError("TÜFE'ye endeksli kâğıt değerlenmiyor: endeks oranı (IDX_RATIO) panoda yok")
    floater = kind in ("float", "frn")
    sign = 1.0 if t.get("side") == "B" else -1.0
    N = float(t["notional"])
    s0 = _day(t.get("settle_date") or t.get("value_date"))
    ai0 = qc.accrued(bond, s0) if s0 < bond.maturity else 0.0
    notes = []
    conv = _yield_conv(t.get("yield_conv"))
    if _num(t.get("price")) is not None:
        clean0 = float(t["price"])
        dirty0 = clean0 + ai0
    elif _num(t.get("yield")) is not None:
        if floater:
            raise TradeError("değişken kuponlu kâğıt getiriyle girilemez")
        dirty0 = bond.price(float(t["yield"]) / 100.0, s0, conv)[0]
        clean0 = dirty0 - ai0
    else:
        raise TradeError("fiyat ya da getiri gerekli")
    # ---- the price now
    manual = _num(t.get("manual_price"))
    closed = t.get("status") == "closed" and _num(t.get("close_price")) is not None
    if closed:
        clean1 = float(t["close_price"])
        v1 = _day(t.get("close_settle")) or bond_settle(mkt, isin, _day(t.get("close_date")) or asof)
        where = "kapanış fiyatı"
    elif row.get("clean") is not None and row.get("where") == "DİBS RV":
        clean1, where = row["clean"], "DİBS RV"
        v1 = _day(row.get("value_date")) or bond_settle(mkt, isin, asof)
    elif row.get("clean") is not None:
        clean1, where = row["clean"], "Tüm Kâğıtlar (%s)" % (row.get("price_how") or "fiyat")
        v1 = bond_settle(mkt, isin, asof)
    elif manual is not None:
        clean1, where = manual, "elle fiyat"
        v1 = bond_settle(mkt, isin, asof)
    else:
        raise TradeError("fiyat yok: kâğıt DİBS RV / Tüm Kâğıtlar'da fiyatlanmıyor - elle fiyat (manual_price) yazın")
    matured = v1 >= bond.maturity
    ai1 = 0.0 if matured else qc.accrued(bond, v1)
    if floater and row.get("accrued") is not None and where == "DİBS RV" and _day(row.get("value_date")) == v1:
        ai1 = row["accrued"]
        notes.append("değişken kupon: işlemiş faiz DİBS RV'den, işlem günündeki bugünkü kupon oranıyla (yaklaşık)")
    dirty1 = 0.0 if matured else clean1 + ai1
    paid = _coupons(bond, s0, v1) if v1 > s0 else 0.0
    mtm = sign * N / 100.0 * (dirty1 - dirty0)
    accrued = sign * N / 100.0 * paid + 0.0
    # ---- carry: the yield unchanged one value date on, less the dirty price funded at TLREF
    hol = mkt.hol("TRY")
    v2 = _add_bd(v1, 1, hol)
    d = (v2 - v1).days
    tl = mkt.fixings.get("ois").live if mkt.fixings.get("ois") is not None else None
    if tl is None and mkt.curves.get("ois") is not None:
        tl = mkt.curves["ois"].on
    carry = 0.0
    y_simple = None
    if not matured and not closed:
        if floater:
            per_day = bond.coupon / bond.freq / bond.period
            carry = sign * N / 100.0 * (per_day * d - dirty1 * (tl or 0.0) * d / 365.0)
        else:
            y_simple = row.get("simple") if where == "DİBS RV" and row.get("simple") is not None else bond.yield_of(dirty1, v1, "simple")
            if y_simple is not None:
                p1 = bond.price(y_simple, v1, "simple")[0]
                p2 = bond.price(y_simple, v2, "simple")[0] if v2 < bond.maturity else 0.0
                carry = sign * N / 100.0 * (p2 + _coupons(bond, v1, v2) - p1 * (1.0 + (tl or 0.0) * d / 365.0))
    dv01_mn = row.get("dv01_mn") if where == "DİBS RV" else None
    if dv01_mn is None and not matured and not floater:
        dv01_mn = qc.desk_dv01(bond, v1, dirty1)
    total = {"mtm": mtm, "accrued": accrued, "carry": carry, "price_now": None if matured else clean1,
             "price_text": "%s %s" % (isin, _tr(clean1, 3)) if not matured else "%s itfa" % isin}
    inputs = {"source": where, "clean_now": clean1, "accrued_now": ai1, "dirty_now": dirty1, "value_date": _iso(v1),
              "clean_paid": clean0, "accrued_paid": ai0, "dirty_paid": dirty0, "settle_date": _iso(s0), "coupons_paid": paid,
              "kind": kind, "coupon": bond.coupon, "freq": bond.freq, "maturity": _iso(bond.maturity), "yield_now": y_simple * 100.0 if y_simple is not None else None,
              "yield_compound_now": row.get("compound") * 100.0 if where == "DİBS RV" and row.get("compound") is not None else None,
              "dv01_mn": dv01_mn, "dv01": N / 1e6 * dv01_mn if dv01_mn else None, "carry_days": d,
              "funding": tl * 100.0 if tl is not None else None, "notes": notes}
    return _finish(mkt, t, "TRY", total, inputs)


def _yield_conv(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in ("basit", "simple", "s"):
        return "simple"
    return "compound"


# ---------------------------------------------------------------------------------------------- FX spot
def _base_amount(t: Dict[str, Any], rate: float) -> float:
    pair = t["pair"]
    N = float(t["notional"])
    return N / rate if (t.get("notional_ccy") or pair[:3]) == pair[3:] else N


def _value_fxspot(t: Dict[str, Any], mkt: Market, asof: _dt.date) -> Dict[str, Any]:
    pair = t["pair"]
    K = float(t["price"])
    N = _base_amount(t, K)
    sign = 1.0 if t.get("side") == "B" else -1.0
    closed = t.get("status") == "closed" and _num(t.get("close_price")) is not None
    S, where = (float(t["close_price"]), "kapanış kuru") if closed else (mkt.spot(pair), "piyasa")
    if not S and _num(t.get("manual_price")) is not None:
        S, where = float(t["manual_price"]), "elle kur"
    if not S:
        raise TradeError("%s spot'u yok - elle kur (manual_price) yazın" % pair)
    mtm = sign * N * (S - K)
    sd = mkt.fx_spot_date(pair, asof)
    sd1 = _add_bd(sd, 1, mkt.pair_hol(pair))
    F1, how = fx_roll(mkt, pair, sd, sd1) if not closed else (S, "")
    carry = -sign * N * (F1 - S) if F1 is not None else 0.0
    dec = next((p.decimals for p in fxm.PAIRS if p.code == pair), 4)
    nxt = _add_bd(asof, 1, mkt.pair_hol(pair))
    total = {"mtm": mtm, "accrued": None, "carry": carry, "price_now": S, "price_text": "%s %s" % (pair, _tr(S, dec))}
    inputs = {"spot": S, "spot_source": where, "base_amount": N, "rate": K, "spot_date": _iso(sd), "next_spot_date": _iso(sd1),
              "forward_next": F1, "forward_how": how, "carry_days": (nxt - asof).days}
    if F1 is None and not closed:
        inputs["notes"] = ["forward yok: carry 0"]
    return _finish(mkt, t, pair[3:], total, inputs)


def fx_roll(mkt: Market, pair: str, sd: _dt.date, sd1: _dt.date) -> Tuple[Optional[float], str]:
    """The forward of rolling a spot position from its spot date to the next one: the overnight rates of both
    currencies when the Forward sheet has them (TRY offshore O/N - ICAP -, SOFR, €STR: ``S·(1 + r_q·g/360)/(1 +
    r_b·g/360)``, a cross through USD), else the pair's forward curve for those days."""
    S = mkt.spot(pair)
    if not S:
        return None, "spot yok"
    g = float((sd1 - sd).days)
    a, b = pair[:3], pair[3:]
    ra, rb = mkt.on_rates.get(a), mkt.on_rates.get(b)
    if ra is not None and rb is not None:
        return S * (1.0 + rb / 100.0 * g / 360.0) / (1.0 + ra / 100.0 * g / 360.0), "O/N faizleri (%s %s, %s %s)" % (
            a, _tr(ra, 2), b, _tr(rb, 2))
    f, how = mkt.forward(pair, sd1)
    if f is None:
        return None, how
    f0, _ = mkt.forward(pair, sd)
    return S * f / f0 if f0 else f, how


# ---------------------------------------------------------------------------------------------- FX options
def gk(S: float, K: float, T: float, sigma: float, df_q: float, df_b: float, call: bool) -> float:
    """Garman-Kohlhagen per unit of the base currency, in the quote currency: DF_q × Black(F = S·DF_b/DF_q)."""
    F = S * df_b / df_q
    return df_q * fv.black(F, K, sigma, T, call)


def gk_greeks(S: float, K: float, T: float, sigma: float, df_q: float, df_b: float, call: bool) -> Dict[str, float]:
    """Per unit of the base currency: delta (spot, base units), gamma (d delta / d S), vega (d / d vol, a unit of vol),
    the price."""
    F = S * df_b / df_q
    sd = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    n1 = fv.npdf(d1)
    delta = df_b * (fv.ncdf(d1) if call else fv.ncdf(d1) - 1.0)
    gamma = df_b * n1 / (S * sd)
    vega = df_b * S * n1 * math.sqrt(T)
    return {"price": gk(S, K, T, sigma, df_q, df_b, call), "delta": delta, "gamma": gamma, "vega": vega}


_SMILES: Dict[Tuple, Tuple[Any, Dict[str, Any]]] = {}
_SMILE_LOCK = threading.Lock()


def _interp_quotes(table: Dict[str, Dict[str, float]], days: float) -> Optional[Dict[str, Optional[float]]]:
    """A pair's quotes (vol points) at ``days`` from its tenors: the ATM in total variance linear in time (flat vol
    beyond the tenors), the risk reversals and butterflies linear in time, flat beyond the tenors that have them."""
    rows = sorted((_VOL_DAYS[t], q) for t, q in table.items() if t in _VOL_DAYS)
    atm = [(d, q["ATM"]) for d, q in rows if _num(q.get("ATM")) and q["ATM"] > 0]
    if not atm:
        return None
    if days <= atm[0][0]:
        a = atm[0][1]
    elif days >= atm[-1][0]:
        a = atm[-1][1]
    else:
        xs = [d for d, _ in atm]
        ws = [v * v * d for d, v in atm]
        w = fxm._lin(days, xs, ws)
        a = math.sqrt(max(w, 1e-12) / days)
    out: Dict[str, Optional[float]] = {"ATM": a}
    for kind in _KINDS[1:]:
        pts = [(d, q[kind]) for d, q in rows if _num(q.get(kind)) is not None]
        out[kind] = fxm._lin(days, [d for d, _ in pts], [v for _, v in pts]) if pts else None
    return out


def smile_vol(mkt: Market, pair: str, K: float, days: float, F: float, df_b: float) -> Tuple[Optional[float], Dict[str, Any]]:
    """The vol (decimal) at strike ``K`` for an expiry ``days`` away: the pair's quotes interpolated to it, a smile
    fitted through them with the pair's delta conventions - SVI (the Opsiyon page's) for USDTRY / EURUSD, Vanna-Volga
    for the others -, read at the strike."""
    table = mkt.vols.get(pair)
    if not table:
        return None, {"why": "%s vol kotası yok" % pair}
    q = _interp_quotes(table, days)
    if q is None:
        return None, {"why": "%s ATM vol yok" % pair}
    p = next((x for x in fxm.PAIRS if x.code == pair), None) or fxm._pair(pair, "", 4)
    T = days / 365.0
    spot_delta = T <= p.spot_until + 1e-9
    pct = lambda v: v / 100.0 if v is not None else None      # noqa: E731
    has25 = q["RR25"] is not None and q["BF25"] is not None
    quotes = fv.Quotes(F, T, q["ATM"] / 100.0, pct(q["RR25"]) if has25 else None, pct(q["BF25"]) if has25 else None,
                       pct(q["RR10"]) if has25 and q["RR10"] is not None and q["BF10"] is not None else None,
                       pct(q["BF10"]) if has25 and q["RR10"] is not None and q["BF10"] is not None else None,
                       premium=p.premium, df=df_b if spot_delta else 1.0)
    model = "svi" if pair in SVI_PAIRS else "vv"
    key = (pair, model, round(T, 8), round(quotes.atm, 8), quotes.rr25 and round(quotes.rr25, 8), quotes.bf25 and round(quotes.bf25, 8),
           quotes.rr10 and round(quotes.rr10, 8), quotes.bf10 and round(quotes.bf10, 8), round(quotes.df, 8), quotes.premium)
    with _SMILE_LOCK:
        hit = _SMILES.get(key)
    if hit is not None:
        smile, info = hit
        if abs(smile.F / F - 1.0) > 1e-14:
            from .quantopt import _moved
            smile, info = _moved(smile, info, F)
    else:
        try:
            smile, info = fv.build_smile(quotes, model)
        except fv.MATH_ERRORS as exc:
            return None, {"why": "smile kurulamadı: %s" % exc}
        with _SMILE_LOCK:
            if len(_SMILES) > 256:
                _SMILES.clear()
            _SMILES[key] = (smile, info)
    try:
        v = smile.vol(K)
    except fv.MATH_ERRORS as exc:
        return None, {"why": "smile'dan vol okunamadı: %s" % exc}
    return v, {"model": info.get("model"), "quotes": q, "atm": q["ATM"], "delta": "spot" if spot_delta else "forward",
               "premium_adjusted": p.premium, "fit": {k: (x * 100.0 if x is not None else None) for k, x in (info.get("fit") or {}).items()}}


def _in_quote(mkt: Market, amount: float, ccy: str, pair: str, S: float) -> float:
    """An amount of ``ccy`` in the pair's quote currency at today's rates (the base at the pair's spot)."""
    base, quote = pair[:3], pair[3:]
    if ccy == quote:
        return amount
    if ccy == base:
        return amount * S
    a, b = mkt.try_per(ccy), mkt.try_per(quote)
    if not a or not b:
        raise TradeError("prim dövizi çevrilemedi: %s" % ccy)
    return amount * a / b


def _value_fxopt(t: Dict[str, Any], mkt: Market, asof: _dt.date) -> Dict[str, Any]:
    pair = t["pair"]
    base, quote = pair[:3], pair[3:]
    call = t.get("call_put") == "call"
    K = float(t["strike"])
    expiry, delivery = _day(t.get("expiry")), _day(t.get("delivery"))
    N = float(t["notional"]) if (t.get("notional_ccy") or base) == base else float(t["notional"]) / K
    sign = 1.0 if t.get("side") == "B" else -1.0
    S = mkt.spot(pair)
    if not S:
        raise TradeError("%s spot'u yok" % pair)
    if t.get("status") == "closed" and _num(t.get("close_price")) is not None:
        # unwound: the premium of the close (received for a bought option, paid for a sold one) against the opening
        # one, both in the premium's currency at today's spot; nothing left to carry
        pccy = (t.get("premium_ccy") or quote).upper()
        opened, shut = _in_quote(mkt, float(t["price"]), pccy, pair, S), _in_quote(mkt, float(t["close_price"]), pccy, pair, S)
        total = {"mtm": sign * (shut - opened), "accrued": None, "carry": 0.0, "price_now": None,
                 "price_text": "%s %s %s kapandı" % (pair, _plain(K), "call" if call else "put")}
        return _finish(mkt, t, quote, total, {"premium": t["price"], "close_premium": t["close_price"], "premium_ccy": pccy})
    notes: List[str] = []
    expired = expiry <= asof
    days = float((expiry - asof).days)
    F, f_how = mkt.forward(pair, delivery)
    df_q, q_how = mkt.df_quote(pair, delivery)
    if F is None or df_q is None:
        raise TradeError("%s forward / iskonto yok (%s)" % (pair, f_how if F is None else q_how))
    df_b = df_q * F / S
    vinfo: Dict[str, Any] = {}
    if expired:
        sigma = 0.0
    elif _num(t.get("manual_price")) is not None:
        sigma = float(t["manual_price"]) / 100.0
        vinfo = {"model": "elle vol"}
    else:
        sigma, vinfo = smile_vol(mkt, pair, K, days, F, df_b)
        if sigma is None:
            raise TradeError("%s - elle vol (manual_price, vol puanı) yazın" % vinfo.get("why"))
    T = days / 365.0
    if expired:
        unit = max(0.0, (S - K) if call else (K - S)) * df_q
        g = {"price": unit, "delta": 0.0, "gamma": 0.0, "vega": 0.0}
        notes.append("vadesi geçti: içsel değer bugünkü spot'la")
    else:
        g = gk_greeks(S, K, T, sigma, df_q, df_b, call)
    value_q = sign * N * g["price"]
    # ---- the premium, in its currency at today's spot
    prem = float(t["price"])
    pccy = (t.get("premium_ccy") or quote).upper()
    prem_q = _in_quote(mkt, prem, pccy, pair, S)
    mtm = value_q - sign * prem_q
    # ---- theta: the same spot, vol and rates, a day (and the days to the next business day) later
    nxt = _add_bd(asof, 1, mkt.pair_hol(pair))
    cdays = (nxt - asof).days

    def later(n: int) -> float:
        if expired:
            return value_q
        t2 = max(T - n / 365.0, 0.0)
        tq = max(float((delivery - mkt.fx_spot_date(pair, asof)).days), 1.0)
        rq, rb = -math.log(df_q) / tq, -math.log(df_b) / tq
        k = max(tq - n, 0.0)
        dq2, db2 = math.exp(-rq * k), math.exp(-rb * k)
        if t2 <= 0:
            return sign * N * dq2 * max(0.0, (S * db2 / dq2 - K) if call else (K - S * db2 / dq2))
        return sign * N * gk(S, K, t2, sigma, dq2, db2, call)

    theta1 = later(1) - value_q
    carry = later(cdays) - value_q
    greeks = {"delta": sign * N * g["delta"], "delta_ccy": base, "gamma": sign * N * g["gamma"] * S * 0.01,
              "vega": sign * N * g["vega"] * 0.01, "theta": theta1, "ccy": quote}
    vol_pts = sigma * 100.0
    tenor = t.get("tenor")
    when = _tenor_tr(tenor) if tenor else _short(expiry)
    text = "%s %s %s %s vol %s" % (pair, when, _plain(K), "call" if call else "put", _tr(vol_pts, 1))
    total = {"mtm": mtm, "accrued": None, "carry": carry, "price_now": vol_pts, "price_text": text}
    inputs = {"spot": S, "forward": F, "forward_how": f_how, "df_quote": df_q, "df_base": df_b, "discount_how": q_how,
              "vol": vol_pts, "vol_how": vinfo, "T": T, "expiry": _iso(expiry), "delivery": _iso(delivery), "base_amount": N,
              "value": value_q, "premium": prem, "premium_ccy": pccy, "premium_quote": prem_q, "unit_price": g["price"],
              "carry_days": cdays, "notes": notes}
    return _finish(mkt, t, quote, total, inputs, greeks=greeks)


# ---------------------------------------------------------------------------------------------- value
def value(trade: Dict[str, Any], mkt: Market, asof: Any = None) -> Dict[str, Any]:
    """A trade's value now (see the module text): ``{ok, why, ccy, mtm, mtm_try, mtm_usd, carry_1d, carry_1d_try,
    carry_1d_usd, accrued, price_now, price_text, greeks, inputs}`` and ``legs`` for a package.  Never raises: a trade
    that cannot be valued is ``ok`` False with the reason in ``why``."""
    day = _day(asof) or (mkt.today if mkt is not None else None) or _dt.date.today()
    prod = str((trade or {}).get("product") or "").strip().lower() if isinstance(trade, dict) else ""
    try:
        if mkt is None:
            raise TradeError("piyasa yok")
        t = check(trade, mkt, strict=False)
        prod = t["product"]
        if prod in RATES:
            return _value_rates(t, mkt, day)
        if prod == "dibs":
            return _value_dibs(t, mkt, day)
        if prod == "fxspot":
            return _value_fxspot(t, mkt, day)
        if prod == "fxopt":
            return _value_fxopt(t, mkt, day)
        raise TradeError("ürün bilinmiyor: %s" % prod)
    except ValueError as exc:                       # (TradeError: the reason as it is)
        return _failed(prod, str(exc) or type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - a trade that cannot be valued is said so, the list goes on
        return _failed(prod, "değerlenemedi: %s: %s" % (type(exc).__name__, str(exc)[:160]))


def _failed(prod: str, why: str) -> Dict[str, Any]:
    ccy = {"ois": "TRY", "sofr": "USD", "dibs": "TRY"}.get(prod, "")
    return {"ok": False, "why": why, "ccy": ccy, "mtm": None, "mtm_try": None, "mtm_usd": None, "carry_1d": None,
            "carry_1d_try": None, "carry_1d_usd": None, "accrued": None, "price_now": None, "price_text": "",
            "greeks": None, "inputs": {}}


# ---------------------------------------------------------------------------------------------- notional for a DV01
def notional_for_dv01(trade_or_leg: Dict[str, Any], dv01: Any, dv01_ccy: Any, mkt: Market) -> Dict[str, Any]:
    """The nominal that gives ``dv01`` (a bp, in USD - the desk's "1.000 $ DV01" - or TL) at today's curve or price:
    ``raw`` exactly, ``notional`` rounded to the nearest lot (5 mn of the trade's currency; never under one lot), and
    ``dv01_check`` - the DV01 the rounded nominal gives, in ``dv01_ccy``.  OIS_MAIN's rule
    ``ROUND(w·DV01·USDTRY/(annuity·0,0001)/lot)·lot`` and DİBS RV!AK's for a bond.  A spread / fly as a whole: the
    weights first (DV01 1:1, 50/50), then each leg rounded - ``legs`` beside the main leg's numbers."""
    x = _num(dv01) if not isinstance(dv01, str) else _parse_amount(dv01)
    if x is None or not x > 0:
        raise TradeError("DV01 pozitif bir sayı olmalı")
    unit = str(dv01_ccy or "USD").strip().upper()
    unit = "TRY" if unit in ("TL", "TRY") else unit
    if unit not in ("USD", "TRY"):
        raise TradeError("DV01 dövizi USD ya da TL olmalı")
    t = dict(trade_or_leg or {})
    prod = str(t.get("product") or "ois").lower()
    if prod in RATES and t.get("structure") in ("spread", "fly") and t.get("legs"):
        w = WEIGHTS[t["structure"]]
        legs = []
        for i, lg in enumerate(t["legs"]):
            one = dict(lg, product=prod, structure="outright")
            one.setdefault("value_date", t.get("value_date") or t.get("settle_date"))
            one.setdefault("settle_date", t.get("settle_date"))
            one.setdefault("trade_date", t.get("trade_date"))
            legs.append(notional_for_dv01(one, x * w[i % len(w)], unit, mkt))
        main = legs[1] if len(legs) > 1 else legs[0]                 # (the long leg / the body: the package's DV01)
        return dict(main, legs=legs)
    ccy, per_unit = _dv01_per_unit(t, prod, mkt)
    fx = mkt.usdtry if mkt.usdtry else mkt.try_per("USD")
    if ccy == unit:
        target = x
    elif unit == "USD" and ccy == "TRY":
        if not fx:
            raise TradeError("USDTRY yok")
        target = x * fx
    elif unit == "TRY" and ccy == "USD":
        if not fx:
            raise TradeError("USDTRY yok")
        target = x / fx
    else:
        raise TradeError("DV01 dövizi çevrilemedi")
    raw = target / per_unit
    lot = mkt.lot if ccy == "TRY" else LOT
    n = max(1.0, _round_half_away(raw / lot)) * lot
    check_ccy = n * per_unit
    back = check_ccy if ccy == unit else (check_ccy / fx if unit == "USD" else check_ccy * fx)
    return {"notional": n, "raw": raw, "dv01_check": back, "ccy": ccy, "lot": lot}


def _dv01_per_unit(t: Dict[str, Any], prod: str, mkt: Market) -> Tuple[str, float]:
    """A unit nominal's DV01 (trade currency per bp): a swap's annuity × 1e-4, a bond's DİBS RV!AI per 1 mn ÷ 1e6."""
    if prod in RATES:
        conv = CONVS[prod]
        start, end, months = _rate_dates(t, prod, mkt)
        res = _swap_pv(mkt, prod, _Leg(start, end, 0.0, 1.0, 1.0, months), mkt.today)
        if not res["annuity"] > 0:
            raise TradeError("annuity hesaplanamadı")
        return conv.ccy, res["annuity"] * 1e-4
    if prod == "dibs":
        isin = str(t.get("isin") or "").strip().upper()
        bond, row, why = _bond_of(mkt, isin)
        if bond is None:
            raise TradeError(why)
        per_mn = row.get("dv01_mn") if row.get("where") == "DİBS RV" else None
        if not per_mn:
            v = bond_settle(mkt, isin, mkt.today)
            price = row.get("clean") if row.get("clean") is not None else _num(t.get("manual_price") or t.get("price"))
            if price is None:
                raise TradeError("fiyat yok: DV01 hesaplanamadı")
            per_mn = qc.desk_dv01(bond, v, price + qc.accrued(bond, v))
        if not per_mn:
            raise TradeError("DV01 hesaplanamadı")
        return "TRY", per_mn / 1e6
    raise TradeError("DV01 ile yalnız OIS, SOFR ve DİBS girilir")


def _rate_dates(t: Dict[str, Any], prod: str, mkt: Market) -> Tuple[_dt.date, _dt.date, Optional[int]]:
    """A swap's start, end and tenor (months) from what a form has so far: its dates, an FRA's "3x6", a meeting's date,
    a tenor - from the settlement (the product's spot of the trade date, today's when there is none)."""
    conv = CONVS[prod]
    hol = mkt.hol(*conv.cal)
    td = _day(t.get("trade_date")) or mkt.today
    settle = _day(t.get("settle_date")) or _add_bd(td, conv.lag, hol)
    start, end = _day(t.get("value_date")), _day(t.get("end_date"))
    months = int(t["tenor_months"]) if t.get("tenor_months") else (tenor_months(t.get("tenor")) if t.get("tenor") else None)
    spec = re.match(r"^(\d{1,3})x(\d{1,3})$", str(t.get("fra") or "").strip().lower().replace(" ", ""))
    if spec and (start is None or end is None):
        start = _roll(conv, add_months(settle, int(spec.group(1))), hol)
        end = _roll(conv, add_months(settle, int(spec.group(2))), hol)
        months = None
    elif t.get("mpc_date") and (start is None or end is None):
        md = _day(t["mpc_date"])
        start = effective_day(md, hol) if md else None
        me = _day(t.get("mpc_end"))
        if me is None and md is not None:
            me = next((d for d in sorted({_day(x) for x in mkt.meetings.get(prod) or [] if _day(x)}) if d > md), None)
        end = effective_day(me, hol) if me else None
        months = None
    start = start or settle
    if end is None and t.get("tenor"):
        end = tenor_end(start, t["tenor"], conv, hol)
    if end is None or not end > start:
        raise TradeError("vade (bitiş tarihi ya da tenor) gerekli")
    return start, end, months if t.get("structure") in (None, "", "outright") else None


def _parse_amount(v: Any) -> Optional[float]:
    from .inputs import parse_amount, parse_number
    if isinstance(v, str):
        s = v.strip()
        return parse_amount(s) if parse_amount(s) is not None else parse_number(s)
    return _num(v)


# ---------------------------------------------------------------------------------------------- defaults
def defaults(product: str, pair: Optional[str] = None, trade_date: Any = None, mkt_or_svc: Any = None, **given: Any) -> Dict[str, Any]:
    """The fields of a new trade with a desk default: ``trade_date`` (today), ``settle_date`` (TRY OIS the OIS spot -
    OIS_MAIN!B2 = WORKDAY(TODAY(),1,TRY); SOFR T+2 on the SIFMA list - SOFR_FOMC!B5; a bond DİBS RV's value date - T+0
    for an ISL0 bill, else the next TRY business day; FX the pair's spot), ``notional_ccy``; for a rate product the
    meeting periods (by date), an FRA's dates (``fra="3x6"``), a tenor's end (``tenor="2Y"``) and the packages'
    weights (with the legs' sides for a package side); for an option ``delivery`` (``expiry`` + the pair's spot lag),
    ``premium_ccy`` (the quote currency) and ``premium_date``.  ``sides``: the side codes :func:`check` writes and what
    each means in words (``side_text``).  ``given``: what the form knows already (``isin``, ``expiry``, ``tenor``,
    ``fra``, ``structure``)."""
    prod = str(product or "").strip().lower()
    if prod not in PRODUCTS:
        raise TradeError("ürün bilinmiyor: %s" % product)
    mkt = _market_of(mkt_or_svc)
    td = _day(trade_date) or mkt.today
    out: Dict[str, Any] = {"product": prod, "trade_date": td.isoformat(),
                           "sides": [{"side": c, "side_text": side_text(prod, c)} for c in _SIDES[prod]]}
    if prod in RATES:
        conv = CONVS[prod]
        hol = mkt.hol(*conv.cal)
        settle = _add_bd(td, conv.lag, hol)
        out.update({"settle_date": settle.isoformat(), "value_date": settle.isoformat(), "notional_ccy": conv.ccy,
                    "structure": given.get("structure") or "outright", "structures": list(STRUCTURES),
                    "weights": {"spread": {"weights": list(WEIGHTS["spread"]), "sides": "kısa ve uzun bacak ters yönde",
                                           "note": "DV01 1:1", "legs": _package_sides(prod, 2)},
                                "fly": {"weights": list(WEIGHTS["fly"]), "sides": "gövde kanatların tersi",
                                        "note": "50/50 DV01: gövde 1, kanatlar ½", "legs": _package_sides(prod, 3)}},
                    "mpc_periods": meeting_periods(mkt, prod), "lot": mkt.lot if prod == "ois" else LOT})
        if given.get("tenor"):
            e = tenor_end(settle, given["tenor"], conv, hol)
            if e is not None:
                out["end_date"] = e.isoformat()
        spec = str(given.get("fra") or "").strip().lower().replace(" ", "")
        m = re.match(r"^(\d{1,3})x(\d{1,3})$", spec)
        if m and int(m.group(2)) > int(m.group(1)):
            out["fra"] = spec
            out["value_date"] = _roll(conv, add_months(settle, int(m.group(1))), hol).isoformat()
            out["end_date"] = _roll(conv, add_months(settle, int(m.group(2))), hol).isoformat()
        return out
    if prod == "dibs":
        isin = str(given.get("isin") or "").strip().upper()
        settle = bond_settle(mkt, isin, td) if isin else _add_bd(td, 1, mkt.hol("TRY"))
        out.update({"settle_date": settle.isoformat(), "value_date": settle.isoformat(), "notional_ccy": "TRY",
                    "lot": mkt.lot, "yield_conv": "bileşik"})
        return out
    code = str(pair or given.get("pair") or "").replace("/", "").strip().upper()
    if len(code) != 6:
        raise TradeError("parite gerekli (örn. USDTRY)")
    sd = mkt.fx_spot_date(code, td)
    out.update({"pair": code, "settle_date": sd.isoformat(), "value_date": sd.isoformat(), "notional_ccy": code[:3]})
    if prod == "fxopt":
        out.update({"premium_ccy": code[3:], "premium_date": sd.isoformat()})
        exp = _day(given.get("expiry"))
        if exp is not None:
            out["expiry"] = exp.isoformat()
            out["delivery"] = mkt.fx_spot_date(code, exp).isoformat()
        elif given.get("tenor"):
            dates = fx_tenor_dates(mkt, code, td, str(given["tenor"]))
            if dates is not None:
                out["expiry"], out["delivery"] = dates[0].isoformat(), dates[1].isoformat()
    return out


def _package_sides(prod: str, n: int) -> Dict[str, List[Dict[str, str]]]:
    """A package's legs (shortest first) for each side of the package: "B" (pay) pays the long leg / the body - it gains
    when the level (long − short, body − ½ wings) rises -, "S" (receive) the other way."""
    out = {}
    for pkg in ("B", "S"):
        other = "S" if pkg == "B" else "B"
        codes = [other, pkg] if n == 2 else [other, pkg, other]
        out[pkg] = [{"side": c, "side_text": side_text(prod, c)} for c in codes]
    return out


def _market_of(x: Any) -> Market:
    """A market from what the caller has: a :class:`Market` as it is; a service - its calendars, meetings and bonds,
    read on the engine thread (a light read: no curve); nothing - the last calendars read."""
    if isinstance(x, Market):
        return x
    if x is not None and hasattr(x, "et") and hasattr(x, "books"):
        raw = x.et.call(_read_calendars, x)
        m = Market(raw["today"], cal=raw["cal"], meetings=raw["meetings"], bonds=raw["bonds"], spots=raw["spots"], lot=raw["lot"])
        with _LAST_LOCK:
            _LAST.update({"cal": dict(m.cal), "meetings": dict(m.meetings), "today": m.today, "bonds": dict(m.bonds),
                          "spots": dict(m.spots), "lot": m.lot})
        return m
    return _calendars_market()


def _read_calendars(svc) -> Dict[str, Any]:
    """The light part of :func:`_read_engine`: today, the holiday lists, the meeting calendars, the bonds' rows."""
    from . import meetings as mt
    from .xl.model import COLS
    from .xl.values import serial_to_date
    out: Dict[str, Any] = {"today": _dt.date.today(), "cal": {}, "meetings": {}, "bonds": {}, "spots": {}, "lot": LOT}
    book = svc.books.get("tto")
    if book is None:
        return out
    calc = book.engine.shared
    out["today"] = serial_to_date(book.engine.clock.today())

    def cell(ref: str, b=book, c=calc) -> Any:
        try:
            si, rc = b.cell(ref)
            return c.get(si, *divmod(rc, COLS))
        except Exception:  # noqa: BLE001
            return None

    def day(v: Any) -> Optional[_dt.date]:
        return serial_to_date(v) if type(v) is float and 20000 < v < 80000 else (_day(v) if isinstance(v, str) else None)

    for ccy in ("TRY", "USD", "EUR"):
        try:
            out["cal"][ccy] = frozenset(serial_to_date(float(s)) for s in svc._calendar_serials((ccy,)))
        except Exception:  # noqa: BLE001
            out["cal"][ccy] = frozenset()
    try:
        out["meetings"]["ois"] = [d for d in mt.slot_dates(book, mt.TCMB, calc) if d]
    except Exception:  # noqa: BLE001
        out["meetings"]["ois"] = []
    lot = _num(cell("OIS_MAIN!H2"))
    out["lot"] = lot if lot and lot > 0 else LOT
    out["bonds"] = _read_bonds(cell, day, book.model.sheet_index)
    for pair, ref in (("USDTRY", "Forward!F2"), ("EURTRY", "Forward!G2")):
        v = _num(cell(ref))
        if v and v > 0:
            out["spots"][pair] = v
    sofr = svc.books.get("sofr")
    if sofr is not None and "SOFR_FOMC" in sofr.model.sheet_index:
        sc = sofr.engine.shared
        out["cal"]["SIFMA"] = frozenset(d for d in (day(cell("SOFR_FOMC!BO%d" % r, sofr, sc)) for r in range(4, 71)) if d)
        try:
            out["meetings"]["sofr"] = [d for d in mt.slot_dates(sofr, mt.FED, sc) if d]
        except Exception:  # noqa: BLE001
            out["meetings"]["sofr"] = []
    return out


# ---------------------------------------------------------------------------------------------- check
_PAIR = re.compile(r"^[A-Z]{6}$")


def _side(v: Any, prod: str, what: str = "yön") -> str:
    s = str(v or "").strip()
    words = _RATE_SIDES if prod in RATES else _BS_SIDES
    w = words.get(s.lower(), words.get(s.casefold()))
    if w is None or w not in _SIDES[prod]:
        raise TradeError("%s anlaşılamadı: %r (%s)" % (what, v, " / ".join(_SIDES[prod])))
    return w


def _positive(v: Any, what: str) -> float:
    x = _parse_amount(v)
    if x is None or not x > 0:
        raise TradeError("%s pozitif bir sayı olmalı" % what)
    return float(x)


def _number(v: Any, what: str) -> float:
    from .inputs import parse_number
    x = parse_number(v.strip()) if isinstance(v, str) else _num(v)
    if x is None:
        raise TradeError("%s sayı olmalı" % what)
    return float(x)


def _date_field(t: Dict[str, Any], key: str, what: str, required: bool = True) -> Optional[_dt.date]:
    v = t.get(key)
    if v in (None, ""):
        if required:
            raise TradeError("%s gerekli" % what)
        return None
    d = _day(v)
    if d is None:
        raise TradeError("%s tarih değil: %r" % (what, v))
    t[key] = d.isoformat()
    return d


#: whether the dates of the trade being checked must be business days of its calendars (a new trade: yes; a stored one
#: being valued: no - a holiday added to a list later must not stop its valuation)
_STRICT = threading.local()


def _business(d: _dt.date, hol: Any, what: str, cal: str) -> None:
    if getattr(_STRICT, "on", True) and not _is_bd(d, hol):
        raise TradeError("%s (%s) %s iş günü değil" % (what, d.strftime("%d.%m.%Y"), cal))


def pricable(pair: str) -> bool:
    """A pair the dashboard can price: both currencies with a rate or a USD pair of their own (crosses included)."""
    return bool(_PAIR.match(pair or "")) and pair[:3] != pair[3:] and pair[:3] in FX_CCYS and pair[3:] in FX_CCYS


def check(trade: Dict[str, Any], mkt: Any = None, strict: bool = True) -> Dict[str, Any]:
    """The trade's fields normalised (dates ISO, sides, amounts, a tenor as its end date, the defaults the desk's
    conventions give) and validated: required fields, dates in order and on the product's calendars, an instrument the
    dashboard knows (or ``manual_price``), sides, positive amounts.  ``mkt``: a :class:`Market`, a service or nothing
    (the calendars last read).  ``strict`` False: the dates need not be business days (a stored trade being valued).
    :class:`TradeError` (a ``ValueError``) with the reason in Turkish."""
    if not isinstance(trade, dict):
        raise TradeError("işlem bir sözlük olmalı")
    t = dict(trade)
    prod = str(t.get("product") or "").strip().lower()
    if prod not in PRODUCTS:
        raise TradeError("ürün bilinmiyor: %r (%s)" % (t.get("product"), ", ".join(PRODUCTS)))
    t["product"] = prod
    m = _market_of(mkt)
    before = getattr(_STRICT, "on", True)
    _STRICT.on = bool(strict)
    try:
        td = _date_field(t, "trade_date", "işlem tarihi")
        if t.get("manual_price") not in (None, ""):
            t["manual_price"] = _number(t["manual_price"], "elle fiyat")
        if t.get("status") in (None, ""):
            t["status"] = "open"
        if t.get("close_date") not in (None, ""):
            cd = _date_field(t, "close_date", "kapanış tarihi")
            if cd < td:
                raise TradeError("kapanış tarihi işlem tarihinden önce olamaz")
        if t.get("close_price") not in (None, ""):
            t["close_price"] = _number(t["close_price"], "kapanış fiyatı")
        if prod in RATES:
            return _check_rates(t, m, td)
        if prod == "dibs":
            return _check_dibs(t, m, td)
        return _check_fx(t, m, td)
    finally:
        _STRICT.on = before


def _settle(t: Dict[str, Any], default: _dt.date, td: _dt.date, hol: Any, cal: str) -> _dt.date:
    """The trade's settlement (valör): ``settle_date`` - a bond's / FX trade's ``value_date`` stands for it (a swap's is
    its start, a forward one's later) -, else the desk's default."""
    sd = _date_field(t, "settle_date", "valör", required=False)
    if sd is None and t.get("product") not in RATES:
        sd = _date_field(t, "value_date", "valör", required=False)       # (a bond's / FX value date is its settlement)
    if sd is None:
        sd = default
    if sd < td:
        raise TradeError("valör (%s) işlem tarihinden önce olamaz" % sd.strftime("%d.%m.%Y"))
    _business(sd, hol, "valör", cal)
    t["settle_date"] = sd.isoformat()
    return sd


def _check_rates(t: Dict[str, Any], m: Market, td: _dt.date) -> Dict[str, Any]:
    prod = t["product"]
    conv = CONVS[prod]
    hol = m.hol(*conv.cal)
    cal = "TRY" if prod == "ois" else "ABD (SIFMA)"
    structure = str(t.get("structure") or "outright").strip().lower()
    if structure not in STRUCTURES:
        raise TradeError("yapı bilinmiyor: %r (%s)" % (t.get("structure"), ", ".join(STRUCTURES)))
    t["structure"] = structure
    t["notional_ccy"] = (t.get("notional_ccy") or conv.ccy).upper()
    if t["notional_ccy"] in ("TL",):
        t["notional_ccy"] = "TRY"
    if t["notional_ccy"] != conv.ccy:
        raise TradeError("%s nominali %s olmalı" % (conv.label, conv.ccy))
    settle = _settle(t, _add_bd(td, conv.lag, hol), td, hol, cal)
    if structure in ("spread", "fly"):
        if t.get("side") not in (None, ""):
            t["side"] = _side(t["side"], prod)
        legs = t.get("legs")
        need = 2 if structure == "spread" else 3
        if not isinstance(legs, list) or len(legs) != need:
            raise TradeError("%s %d bacak ister" % ("spread" if structure == "spread" else "fly", need))
        start = _day(t.get("value_date")) or settle
        if start < settle:
            raise TradeError("başlangıç valörden önce olamaz")
        t["value_date"] = start.isoformat()
        out_legs = []
        for i, lg in enumerate(legs):
            if not isinstance(lg, dict):
                raise TradeError("bacak %d bir sözlük olmalı" % (i + 1))
            L = dict(lg)
            L["side"] = _side(L.get("side"), prod, "bacak %d yönü" % (i + 1))
            if L.get("price") in (None, ""):
                raise TradeError("bacak %d fiyatı (sabit faiz %%) gerekli" % (i + 1))
            L["price"] = _number(L["price"], "bacak %d fiyatı" % (i + 1))
            end = _leg_end(L, start, conv, hol, "bacak %d" % (i + 1))
            if not end > start:
                raise TradeError("bacak %d bitişi başlangıçtan sonra olmalı" % (i + 1))
            _business(end, hol, "bacak %d bitişi" % (i + 1), cal)
            if L.get("notional") in (None, "") and L.get("dv01") not in (None, "") and isinstance(m, Market) and prod in m.curves:
                L["notional"] = notional_for_dv01(dict(L, product=prod, value_date=start.isoformat()), L["dv01"],
                                                  L.get("dv01_ccy") or "USD", m)["notional"]
            if L.get("notional") in (None, ""):
                raise TradeError("bacak %d nominali gerekli" % (i + 1))
            L["notional"] = _positive(L["notional"], "bacak %d nominali" % (i + 1))
            if L.get("close_price") not in (None, ""):
                L["close_price"] = _number(L["close_price"], "bacak %d kapanış faizi" % (i + 1))
            out_legs.append(L)
        ends = [_day(L["end_date"]) for L in out_legs]
        if any(b <= a for a, b in zip(ends, ends[1:])):
            raise TradeError("bacaklar vadeye göre sıralı olmalı (kısa → uzun)")
        sides = [L["side"] for L in out_legs]
        if structure == "spread" and sides[0] == sides[1]:
            raise TradeError("spread'in bacakları ters yönde olmalı")
        if structure == "fly" and not (sides[0] == sides[2] != sides[1]):
            raise TradeError("fly'da kanatlar aynı, gövde ters yönde olmalı")
        t["legs"] = out_legs
        t["notional"] = out_legs[1]["notional"]
        # the package's level as traded (bp): long − short; the fly's 50/50 body − ½ each wing
        rates = [L["price"] for L in out_legs]
        level = (rates[1] - rates[0]) * 100.0 if structure == "spread" else (rates[1] - 0.5 * (rates[0] + rates[2])) * 100.0
        if t.get("price") in (None, ""):
            t["price"] = level
        # the package's own side: "B" (pay) gains when its level goes up (pays the long leg / the body)
        t["side"] = out_legs[1]["side"]
        t["end_date"] = out_legs[-1]["end_date"]
        return t
    t["side"] = _side(t.get("side"), prod)
    if t.get("price") in (None, ""):
        raise TradeError("fiyat (sabit faiz %) gerekli")
    t["price"] = _number(t["price"], "fiyat")
    if not -50.0 < t["price"] < 500.0:
        raise TradeError("sabit faiz yüzde olarak yazılmalı (örn. 38,45)")
    strict = getattr(_STRICT, "on", True)
    if structure == "mpc":
        # a meeting period is the meeting's: its dates are fixed when the trade is entered (the effective day of the
        # meeting to that of the next one) and kept - a later edit of the calendar moves nothing
        md = _date_field(t, "mpc_date", "toplantı tarihi (mpc_date)")
        start = _date_field(t, "value_date", "başlangıç", required=False) if t.get("end_date") not in (None, "") else None
        end = _date_field(t, "end_date", "bitiş", required=False)
        if start is None:
            start = effective_day(md, hol)
        if end is None and t.get("mpc_end") not in (None, ""):
            end = effective_day(_date_field(t, "mpc_end", "bitiş toplantısı"), hol)
        if end is None:
            dates = sorted({_day(d) for d in m.meetings.get(prod) or [] if _day(d)})
            nxt = next((d for d in dates if d > md), None)
            if nxt is None:
                raise TradeError("%s takviminde %s'ten sonraki toplantı yok: bitiş tarihini yazın" % (conv.meetings_name, md.strftime("%d.%m.%Y")))
            t["mpc_end"] = nxt.isoformat()
            end = effective_day(nxt, hol)
        if strict and start < settle:
            raise TradeError("toplantının etkin günü (%s) valörden önce" % start.strftime("%d.%m.%Y"))
        t["value_date"], t["end_date"] = start.isoformat(), end.isoformat()
    elif structure == "fra":
        spec = str(t.get("fra") or "").strip().lower().replace(" ", "")
        mm = re.match(r"^(\d{1,3})x(\d{1,3})$", spec)
        if mm:
            a, b = int(mm.group(1)), int(mm.group(2))
            if not b > a:
                raise TradeError("FRA'nın bitişi başlangıcından sonra olmalı (örn. 3x6)")
            t["fra"] = spec
            # a new trade takes its dates from "3x6" (a form's value date may still be the spot of a default); a stored
            # one keeps the dates it was entered with
            if strict or t.get("value_date") in (None, "") or t.get("end_date") in (None, ""):
                t["value_date"] = _roll(conv, add_months(settle, a), hol).isoformat()
                t["end_date"] = _roll(conv, add_months(settle, b), hol).isoformat()
        start = _date_field(t, "value_date", "FRA başlangıcı")
        if strict and not start > settle:
            raise TradeError("FRA başlangıcı valörden sonra olmalı")
        end = _leg_end(t, start, conv, hol, "FRA")
    else:
        start = _day(t.get("value_date")) or settle
        if start < settle:
            raise TradeError("başlangıç valörden önce olamaz")
        t["value_date"] = start.isoformat()
        end = _leg_end(t, start, conv, hol, "işlem")
    for d, what in ((start, "başlangıç"), (end, "bitiş")):
        _business(d, hol, what, cal)
    if not end > start:
        raise TradeError("bitiş başlangıçtan sonra olmalı")
    if t.get("notional") in (None, "") and t.get("dv01") not in (None, "") and isinstance(m, Market) and prod in m.curves:
        t["notional"] = notional_for_dv01(t, t["dv01"], t.get("dv01_ccy") or "USD", m)["notional"]
    t["notional"] = _positive(t.get("notional"), "nominal")
    return t


def _leg_end(L: Dict[str, Any], start: _dt.date, conv: Conv, hol: Any, what: str) -> _dt.date:
    end = _day(L.get("end_date")) if L.get("end_date") not in (None, "") else None
    if end is None and L.get("end_date") not in (None, ""):
        raise TradeError("%s bitişi tarih değil: %r" % (what, L.get("end_date")))
    if end is None and L.get("tenor") not in (None, ""):
        end = tenor_end(start, str(L["tenor"]), conv, hol)
        if end is None:
            raise TradeError("%s vadesi anlaşılamadı: %r (örn. 2Y, 18M, 3A)" % (what, L["tenor"]))
        L["tenor"] = str(L["tenor"]).strip().upper()
        m = tenor_months(L["tenor"])
        if m:
            L["tenor_months"] = m
    if end is None:
        raise TradeError("%s bitiş tarihi ya da vadesi gerekli" % what)
    L["end_date"] = end.isoformat()
    return end


def _check_dibs(t: Dict[str, Any], m: Market, td: _dt.date) -> Dict[str, Any]:
    from . import bonds as bd
    isin = "".join(str(t.get("isin") or "").upper().split())
    if not isin:
        raise TradeError("ISIN gerekli")
    t["isin"] = isin
    known = isin in m.bonds or bd.by_isin(isin) is not None
    if not known and t.get("manual_price") in (None, ""):
        raise TradeError("kâğıt bilinmiyor: %s (DİBS RV / Tüm Kâğıtlar'da yok) - elle fiyat (manual_price) yazın" % isin)
    if not known and not bd.isin_valid(isin):
        raise TradeError("ISIN geçersiz: %s" % isin)
    t["side"] = _side(t.get("side"), "dibs")
    if t.get("notional") in (None, "") and t.get("dv01") not in (None, "") and isinstance(m, Market) and known:
        t["notional"] = notional_for_dv01(t, t["dv01"], t.get("dv01_ccy") or "USD", m)["notional"]
    t["notional"] = _positive(t.get("notional"), "nominal")
    t["notional_ccy"] = "TRY"
    hol = m.hol("TRY")
    settle = _settle(t, bond_settle(m, isin, td), td, hol, "TRY")
    t["value_date"] = settle.isoformat()
    has_price = t.get("price") not in (None, "")
    has_yield = t.get("yield") not in (None, "")
    if not has_price and not has_yield:
        raise TradeError("fiyat (temiz) ya da getiri gerekli")
    if has_price:
        t["price"] = _number(t["price"], "fiyat")
        if not 0 < t["price"] < 1000:
            raise TradeError("temiz fiyat 100 nominal başına olmalı (örn. 98,45)")
    if has_yield:
        t["yield"] = _number(t["yield"], "getiri")
        t["yield_conv"] = "basit" if _yield_conv(t.get("yield_conv")) == "simple" else "bileşik"
    mat = None
    row = m.bonds.get(isin) or {}
    cat = bd.by_isin(isin) or {}
    mat = _day(row.get("maturity") or cat.get("maturity")) or bd.maturity_of(isin)
    if mat is not None and not settle < mat:
        raise TradeError("valör kâğıdın vadesinden (%s) önce olmalı" % mat.strftime("%d.%m.%Y"))
    return t


def _check_fx(t: Dict[str, Any], m: Market, td: _dt.date) -> Dict[str, Any]:
    prod = t["product"]
    pair = str(t.get("pair") or "").replace("/", "").strip().upper()
    if not _PAIR.match(pair) or pair[:3] == pair[3:]:
        raise TradeError("parite anlaşılamadı: %r (örn. USDTRY)" % t.get("pair"))
    if not pricable(pair) and t.get("manual_price") in (None, ""):
        raise TradeError("%s fiyatlanamıyor - elle fiyat (manual_price) yazın" % pair)
    t["pair"] = pair
    t["side"] = _side(t.get("side"), prod)
    t["notional"] = _positive(t.get("notional"), "nominal")
    nc = str(t.get("notional_ccy") or pair[:3]).strip().upper()
    nc = "TRY" if nc == "TL" else nc
    if nc not in (pair[:3], pair[3:]):
        raise TradeError("nominal dövizi %s ya da %s olmalı" % (pair[:3], pair[3:]))
    t["notional_ccy"] = nc
    hol = m.pair_hol(pair)
    cal = " + ".join(_cal_names(pair)) or "hafta içi"
    settle = _settle(t, m.fx_spot_date(pair, td), td, hol, cal)
    t["value_date"] = settle.isoformat()
    if t.get("price") in (None, ""):
        raise TradeError("fiyat gerekli" if prod == "fxspot" else "prim tutarı (price) gerekli")
    if prod == "fxspot":
        t["price"] = _positive(t["price"], "kur")
        return t
    t["price"] = _number(t["price"], "prim")
    if t["price"] < 0:
        raise TradeError("prim eksi olamaz")
    cp = str(t.get("call_put") or "").strip().lower()
    cp = {"c": "call", "call": "call", "p": "put", "put": "put"}.get(cp)
    if cp is None:
        raise TradeError("call / put gerekli")
    t["call_put"] = cp
    t["strike"] = _positive(t.get("strike"), "kullanım fiyatı (strike)")
    exp = _date_field(t, "expiry", "vade (expiry)", required=False)
    if exp is None and t.get("tenor") not in (None, ""):
        dates = fx_tenor_dates(m, pair, td, str(t["tenor"]))
        if dates is None:
            raise TradeError("vade anlaşılamadı: %r (örn. 1A, 3M, 1Y)" % t["tenor"])
        exp, dl0 = dates
        t["expiry"] = exp.isoformat()
        t.setdefault("delivery", dl0.isoformat())
    if exp is None:
        raise TradeError("vade (expiry) gerekli")
    if not exp > td:
        raise TradeError("vade işlem tarihinden sonra olmalı")
    _business(exp, hol, "vade", cal)
    dl = _date_field(t, "delivery", "teslim", required=False) or m.fx_spot_date(pair, exp)
    if dl < exp:
        raise TradeError("teslim vadeden önce olamaz")
    t["delivery"] = dl.isoformat()
    pc = str(t.get("premium_ccy") or pair[3:]).strip().upper()
    pc = "TRY" if pc == "TL" else pc
    if pc not in (pair[:3], pair[3:], "TRY", "USD"):
        raise TradeError("prim dövizi %s, %s, TRY ya da USD olmalı" % (pair[:3], pair[3:]))
    t["premium_ccy"] = pc
    pd = _date_field(t, "premium_date", "prim valörü", required=False) or settle
    if pd < td:
        raise TradeError("prim valörü işlem tarihinden önce olamaz")
    t["premium_date"] = pd.isoformat()
    return t


def fx_tenor_dates(mkt: Market, pair: str, day: _dt.date, tenor: str) -> Optional[Tuple[_dt.date, _dt.date]]:
    """An option's expiry and delivery for a tenor traded on ``day``, as the FX pages count tenors: the delivery is the
    spot date plus the tenor (``fx.delivery``: the next business day of both currencies), the expiry the business day
    whose spot date that is (the spot lag back)."""
    sc = parse_tenor(tenor)
    if sc is None:
        return None
    hol = mkt.pair_hol(pair)
    sd = mkt.fx_spot_date(pair, day)
    key = str(tenor).strip().upper()
    if key in fxm.TENOR_SPEC:
        dl = fxm.delivery(sd, key, hol)
    else:
        dl = _following(add_months(sd, sc[1]) if sc[0] == "M" else sd + _dt.timedelta(days=7 * sc[1]), hol)
    exp = dl
    for _ in range(fxm.SPOT_LAG.get(pair, 2)):
        exp = _preceding(exp - _dt.timedelta(days=1), hol)
    return max(exp, day + _dt.timedelta(days=1)), dl


def _cal_names(pair: str) -> List[str]:
    from . import extras as ex
    return list(ex.pair_calendar(pair))
