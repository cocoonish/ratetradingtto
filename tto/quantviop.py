"""VİOP: Borsa İstanbul's USDTRY futures against spot - the TRY rate they imply, whether it is a good time to buy or
to sell, where it may be bought / sold today and this week, with how much probability.  On the quant package's worker
(``tto.quant`` calls :func:`run` on a full fit, :func:`refresh` on the minute's live refresh; the page "VİOP" reads
:func:`view`).

**The implied rate** is the VİOP sheet's: ((price / spot) · (1 + USD · g/360) − 1) · 360/g, g = the expiry − the day's
spot date (T+1, the TRY holidays) in calendar days, USD the USD OIS at g (EK_VIOP's piecewise line through USSOA /
USSOC / USSOF / USSO1 for the past; the sheet's own BID / ASK rows - 13 and 25 - live).  Against it: the TRY OIS at g
(linear in days, ACT/365 → 360 as the sheet's row 77) and the offshore curve at g (the sheet's ICAP rows read it as
ACT/360).  *Buy* is buying the future: the lower the implied rate the better (cheap forward / cheap TRY funding);
*sell* is the other way.  A signal's package is the future against spot (the rate alone).

**Data** (Bloomberg, the history's normal sync): the first ``LISTED_MAX`` listed contracts (of the VİOP sheet's twelve,
L1:W1) and the ``EXPIRED_MONTHS`` monthly contracts before them - PX_LAST, PX_HIGH, PX_LOW; an expired one is asked once (its
history is complete) and never again, the sheet's ticker form first ("A1X5 Curncy") and the two-digit year only if
that one had nothing ("A1X25 Curncy"); USDTRY's PX_HIGH / PX_LOW; USD OIS 1M / 6M / 1Y beside the 3M the quant
package keeps.  Live, the last ``BAR_DAYS`` business days of 5-minute bars of the two front contracts (TRADE) and of
USDTRY (BID, ASK) - a day once, after it is over (:func:`fetch_bars`, ``provider.intraday_bars``).

**What is computed**
* each contract's implied rate day by day, its spread over OIS ("baz") and over offshore; constant-maturity series
  (30 / 61 / 91 / 182 days) through all contracts, expired ones included - two years of history whatever the front is;
* a contract's *fair* rate: the OIS at its maturity + the spread's mean at that maturity over the window; its signal
  is the spread's distance from it (z, half-life, regime as every mean-reversion family of the package);
* where the rate may go **today** (the rest of the session) and **this week** (to Friday's close): the probability
  that the ask-implied rate falls to a level (a buy order there fills) and that the bid-implied rate rises to one (a
  sell order fills) - a Brownian motion with drift through the reflection principle, the drift the pull to fair and
  the roll down the contract's curve (and a month-end effect where the history shows one), the variance the
  intraday profile of the bars (scaled to the daily variance of the history) - then calibrated on the history: the
  levels the model gave against what came;
* the calendar: the spread around month ends (and quarter ends), by weekday, near the front's expiry;
* the daily ranges of the futures and of spot (PX_HIGH / PX_LOW).
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import re
import sqlite3
import statistics
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import quantfam as qf
from . import quantmath as qm

# ---------------------------------------------------------------------------------------------- the module's frame
FAMILY = "viop"
FAMILIES = {FAMILY: ("VİOP adil değer", "mr", "quant-viop")}
PAGES = (("quant-viop", "VİOP"),)
VIEWS = {"viop": "quant-viop"}
DEFAULTS: Dict[str, Any] = {"viop_fair_window": 120}
LIMITS: Dict[str, Tuple[float, float, type]] = {"viop_fair_window": (20, 500, int)}
LABELS = {"viop_fair_window": "VİOP: adil spread ve oynaklık penceresi (gün)"}

EXPIRED_MONTHS = 24                       # monthly contracts before the listed ones: two years of history
LISTED_MAX = 6                            # listed contracts the history keeps (the far ones of the sheet's twelve hardly trade)
BAR_DAYS = 20                             # business days of 5-minute bars asked for
BAR_FRONTS = 2                            # the front contracts whose bars are asked
BAR_MINUTES = 5
SESSION = (9 * 60 + 30, 18 * 60 + 15)     # VİOP's normal session (local), the minutes a day's bars cover
BAR_PER_REFRESH = 4                       # bar requests a minute's refresh may send (the first fill: ~80, spread out)
CM_DAYS = (30, 61, 91, 182)               # constant maturities
LADDER = (0.9, 0.7, 0.5, 0.3, 0.1)        # fill probabilities of the order levels
HIST_LOOKBACK = 740                       # listed contracts, spot's high / low, USD OIS: as the quant package's series
EXPIRED_LOOKBACK = EXPIRED_MONTHS * 31 + 400    # an expired contract's whole life
SPOT_KEY = "FX:USDTRY"
USD_KEYS = (("USD:1M", 30, "USSOA Curncy", "USD OIS 1M"), ("USD:3M", 91, "USSOC Curncy", "USD OIS 3M"),
            ("USD:6M", 182, "USSOF Curncy", "USD OIS 6M"), ("USD:1Y", 365, "USSO1 Curncy", "USD OIS 1Y"))
CODES = "FGHJKMNQUVXZ"
MONTHS_TR = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara")
#: national holidays on fixed dates: a contract's expiry moves a day back only before Oct 29 or a Bayram
FIXED_HOLIDAYS = {(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)}
_TICKER = re.compile(r"^(?P<root>.+?)(?P<m>[FGHJKMNQUVXZ])(?P<y>\d{1,2})\s+(?P<yk>\S+)$")


# ---------------------------------------------------------------------------------------------- contracts
def parse_ticker(ticker: str) -> Optional[Tuple[str, int, str, str]]:
    """``"A1Z6 Curncy"`` → ``("A1", 12, "6", "Curncy")``: root, month, the year's digits, yellow key."""
    m = _TICKER.match(str(ticker or "").strip())
    if not m:
        return None
    return m.group("root"), CODES.index(m.group("m")) + 1, m.group("y"), m.group("yk")


def year_of(digits: str, near: _dt.date) -> int:
    """The year a ticker's digits stand for: two digits are 20xx; one the year ending so nearest ``near``."""
    if len(digits) == 2:
        return 2000 + int(digits)
    d = int(digits)
    return min((y for y in range(near.year - 6, near.year + 7) if y % 10 == d), key=lambda y: (abs(y - near.year), -y))


def contract_ticker(root: str, year: int, month: int, yk: str = "Curncy", two: bool = False) -> str:
    return "%s%s%s %s" % (root, CODES[month - 1], ("%02d" % (year % 100)) if two else str(year % 10), yk)


def contract_name(year: int, month: int) -> str:
    return "%s%02d" % (MONTHS_TR[month - 1], year % 100)


def _bday(d: _dt.date, holidays: Set[_dt.date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def workday(d: _dt.date, n: int, holidays: Set[_dt.date]) -> _dt.date:
    """Excel's WORKDAY: ``n`` business days on (back when negative)."""
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += _dt.timedelta(days=step)
        if _bday(d, holidays):
            left -= 1
    return d


def expiry_of(year: int, month: int, holidays: Set[_dt.date]) -> _dt.date:
    """A month's contract expires on the month's last business day - a business day earlier when the next day is
    Republic Day or a Bayram (the VİOP sheet's row 1)."""
    nxt = _dt.date(year + (month // 12), month % 12 + 1, 1)
    last = workday(nxt, -1, holidays)
    after = last + _dt.timedelta(days=1)
    if (after.month, after.day) == (10, 29) or (after in holidays and (after.month, after.day) not in FIXED_HOLIDAYS):
        last = workday(last, -1, holidays)
    return last


def _months_back(year: int, month: int, n: int) -> Tuple[int, int]:
    k = year * 12 + (month - 1) - n
    return k // 12, k % 12 + 1


def contract_list(active: Sequence[str], today: _dt.date, months: int = EXPIRED_MONTHS) -> List[Dict[str, Any]]:
    """The listed contracts (the VİOP sheet's tickers, nearest first) and the ``months`` monthly contracts before the
    first of them: ``{ticker, alt (expired: the two-digit year), year, month, expired, name}``."""
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    first: Optional[Tuple[str, int, int, str]] = None
    for t in active:
        p = parse_ticker(t)
        if p is None or t in seen:
            continue
        root, month, digits, yk = p
        year = year_of(digits, today)
        seen.add(t)
        out.append({"ticker": t.strip(), "alt": None, "year": year, "month": month, "expired": False, "name": contract_name(year, month)})
        if first is None or (year, month) < (first[1], first[2]):
            first = (root, year, month, yk)
    if first is None:
        return out
    root, y0, m0, yk = first
    for k in range(1, months + 1):
        y, m = _months_back(y0, m0, k)
        t = contract_ticker(root, y, m, yk)
        if t in seen:
            continue
        seen.add(t)
        out.append({"ticker": t, "alt": contract_ticker(root, y, m, yk, two=True), "year": y, "month": m, "expired": True,
                    "name": contract_name(y, m)})
    return out


# ---------------------------------------------------------------------------------------------- the history's series
def series_specs() -> List[Dict[str, Any]]:
    """The fixed series beside the contracts: USD OIS 1M / 6M / 1Y (the 3M is the quant package's own) and
    USDTRY's daily high and low (its close is the package's ``FX:USDTRY``)."""
    out = [{"key": k, "label": label, "ticker": t, "kind": "rate", "group": "VİOP"} for k, _, t, label in USD_KEYS if k != "USD:3M"]
    return out


def spot_specs(spot_ticker: str) -> List[Dict[str, Any]]:
    return [{"key": "FXH:USDTRY", "label": "USDTRY gün içi en yüksek", "ticker": spot_ticker, "field": "PX_HIGH", "kind": "fx", "group": "VİOP"},
            {"key": "FXL:USDTRY", "label": "USDTRY gün içi en düşük", "ticker": spot_ticker, "field": "PX_LOW", "kind": "fx", "group": "VİOP"}]


def contract_specs(active: Sequence[str], today: _dt.date) -> List[Dict[str, Any]]:
    """Every contract's close, high and low as series of the history: an expired one asked once in full (``tail``
    "none") with its two-digit ticker held back for when the sheet's form has nothing (``alts_lazy``)."""
    out: List[Dict[str, Any]] = []
    for c in contract_list(list(active)[:LISTED_MAX], today):
        for field, prefix, what in (("PX_LAST", "VIOPF", "kapanış"), ("PX_HIGH", "VIOPH", "en yüksek"), ("PX_LOW", "VIOPL", "en düşük")):
            s = {"key": "%s:%s" % (prefix, c["ticker"]), "label": "VİOP %s %s" % (c["name"], what), "ticker": c["ticker"],
                 "field": field, "kind": "px", "group": "VİOP", "backfill": "viop",
                 "lookback": EXPIRED_LOOKBACK if c["expired"] else HIST_LOOKBACK}
            if c["expired"]:
                s.update({"alts": [c["alt"]], "tail": "none"})
            out.append(s)
    return out


# ---------------------------------------------------------------------------------------------- the workbook's part
#: the VİOP sheet: contract n (1 … 12) has its ticker in column L + n − 1 of row 1 and its numbers in column M + n − 1
VQ_ROWS = {"expiry": 9, "g_bid": 10, "spot": 11, "usd": 12, "i_bid": 13, "bid": 16, "g_ask": 22, "i_ask": 25, "ask": 28}
VQ_LAST = 511                             # the sheet's live "last price" row


def read_engine(out: Dict[str, Any], index: Dict[str, int], reader: Callable[[str], Callable[[str], Any]],
                num: Callable[[Any], Optional[float]]) -> None:
    """``quant.Quant._read_engine`` (engine thread): each listed contract as the VİOP sheet has it now - ticker,
    expiry, days, spot, USD rate, bid / ask prices and the TRY rates they imply - into ``out["viopq"]``."""
    from .xl.model import index_to_col
    from .xl.values import serial_to_date
    rows: List[Dict[str, Any]] = []
    out["viopq"] = rows
    if "VIOP" not in index:
        return
    get = reader("VIOP")
    for n in range(12):
        tcol, col = index_to_col(12 + n), index_to_col(13 + n)            # L … W, M … X (index_to_col(1) is "A")
        ticker = get("%s1" % tcol)
        if not isinstance(ticker, str) or not ticker.strip():
            continue
        r: Dict[str, Any] = {"ticker": ticker.strip(), "n": n + 1}
        for name, row in VQ_ROWS.items():
            r[name] = num(get("%s%d" % (col, row)))
        r["last"] = num(get("%s%d" % (col, VQ_LAST)))
        exp = r.pop("expiry")
        r["expiry"] = serial_to_date(exp).isoformat() if exp is not None and 20000 < exp < 80000 else None
        for k in ("i_bid", "i_ask", "usd"):                             # the sheet's rates are fractions
            if r.get(k) is not None and abs(r[k]) < 5.0:
                r[k] = r[k] * 100.0
        rows.append(r)


#: live keys: the implied rate at the bid / ask / mid (per cent), the prices, spot, the USD rate, the days
LIVE_KEYS = {"VQB": "i_bid", "VQA": "i_ask", "VQPB": "bid", "VQPA": "ask", "VQPL": "last", "VQS": "spot", "VQU": "usd", "VQG": "g_bid"}


def live_values(eng: Dict[str, Any]) -> Dict[str, float]:
    """``quant.Quant._live_values``: each listed contract's bid / ask / mid implied rate (per cent), its prices,
    spot, the USD rate and the days, as the VİOP sheet has them now."""
    out: Dict[str, float] = {}
    for r in eng.get("viopq") or []:
        t = r["ticker"]
        for prefix, field in LIVE_KEYS.items():
            if r.get(field) is not None:
                out["%s:%s" % (prefix, t)] = r[field]
        if r.get("i_bid") is not None and r.get("i_ask") is not None:
            out["VQM:" + t] = (r["i_bid"] + r["i_ask"]) / 2.0
    return out


def covers(key: str) -> bool:
    return key.startswith(("VIOPF:", "VIOPH:", "VIOPL:", "USD:", "FXH:", "FXL:")) or key == SPOT_KEY


# ---------------------------------------------------------------------------------------------- the rates
def usd_at(g: float, a: Optional[float], b: Optional[float], c: Optional[float], d: Optional[float]) -> Optional[float]:
    """EK_VIOP's USD rate for g days: flat to 30, then straight lines through 91, 182 and 365 days (1M, 3M, 6M, 1Y);
    a missing tenor is filled from its neighbours."""
    pts = [(30.0, a), (91.0, b), (182.0, c), (365.0, d)]
    known = [(x, y) for x, y in pts if y is not None]
    if not known:
        return None
    if g <= known[0][0]:
        return known[0][1]
    for (x0, y0), (x1, y1) in zip(known, known[1:]):
        if g <= x1:
            return y0 + (y1 - y0) * (g - x0) / (x1 - x0)
    return known[-1][1]


def implied(price: float, spot: float, usd: float, g: float) -> Optional[float]:
    """The TRY rate (per cent, ACT/360) a future's price implies: ((price / spot)(1 + USD g/360) − 1) 360/g."""
    if not price or not spot or g is None or g <= 0 or usd is None:
        return None
    return ((price / spot) * (1.0 + usd / 100.0 * g / 360.0) - 1.0) * 360.0 / g * 100.0


def price_of(rate: float, spot: float, usd: float, g: float) -> Optional[float]:
    """The future's price at an implied TRY rate (the inverse of :func:`implied`)."""
    if not spot or not g or g <= 0 or usd is None:
        return None
    return spot * (1.0 + rate / 100.0 * g / 360.0) / (1.0 + usd / 100.0 * g / 360.0)


def curve_at(points: Sequence[Tuple[float, float]], days: float) -> Optional[float]:
    """A curve's rate at ``days`` - straight lines in days between its tenors, flat beyond the ends."""
    pts = sorted(points)
    if not pts:
        return None
    if days <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if days <= x1:
            return y0 + (y1 - y0) * (days - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def _tenor_days(months: float) -> float:
    return float(months) * 365.0 / 12.0


# ---------------------------------------------------------------------------------------------- the daily history
class Contract(object):
    """One VİOP contract with its daily closes, highs and lows (``{day: price}``)."""

    __slots__ = ("ticker", "year", "month", "name", "expiry", "expired", "close", "high", "low")

    def __init__(self, ticker: str, year: int, month: int, expiry: _dt.date, today: _dt.date, close: Dict[str, float],
                 high: Dict[str, float], low: Dict[str, float]):
        self.ticker, self.year, self.month = ticker, year, month
        self.name = contract_name(year, month)
        self.expiry = expiry
        self.expired = expiry < today
        self.close, self.high, self.low = close, high, low


def contracts_of(ctx: qf.Ctx, eng: Optional[Dict[str, Any]] = None) -> List[Contract]:
    """Every contract the context has closes of (by expiry); the listed ones the VİOP sheet shows today join even
    without a history."""
    hol = set(ctx.holidays or ())
    out: Dict[str, Contract] = {}
    for key in ctx.meta:
        if not key.startswith("VIOPF:"):
            continue
        t = key[6:]
        p = parse_ticker(t)
        if p is None:
            continue
        year = year_of(p[2], ctx.today)
        out[t] = Contract(t, year, p[1], expiry_of(year, p[1], hol), ctx.today, dict(ctx.series.get(key) or {}),
                          dict(ctx.series.get("VIOPH:" + t) or {}), dict(ctx.series.get("VIOPL:" + t) or {}))
    for r in (eng or {}).get("viopq") or []:
        t = r["ticker"]
        p = parse_ticker(t)
        if p is None:
            continue
        year = year_of(p[2], ctx.today)
        exp = _dt.date.fromisoformat(r["expiry"]) if r.get("expiry") else expiry_of(year, p[1], hol)
        if t in out:
            out[t].expiry = exp                                  # the sheet's own (Bloomberg's last tradeable day)
            out[t].expired = exp < ctx.today
        else:
            out[t] = Contract(t, year, p[1], exp, ctx.today, {}, {}, {})
    return sorted(out.values(), key=lambda c: c.expiry)


class Curves(object):
    """The curves the implied rate is read against, by day: spot, the USD rate (EK_VIOP's line), the TRY OIS (ACT/360)
    and offshore curves - the last close on or before the day (a holiday of one market)."""

    def __init__(self, ctx: qf.Ctx):
        self.ctx = ctx
        self.spot = ctx.series.get(SPOT_KEY) or {}
        self.usd = [ctx.series.get(k) or {} for k, _, _, _ in USD_KEYS]
        self.ois = [(_tenor_days(m["months"]), k) for k, m in ctx.meta.items() if k.startswith("OIS:") and (m.get("months") or 0) >= 0.2]
        self.off = [(_tenor_days(m["months"]), k) for k, m in ctx.meta.items() if k.startswith("OFF:") and m.get("group") == "off" and m.get("months")]
        self._cache: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}

    @staticmethod
    def on(series: Dict[str, float], day: str, back: int = 5) -> Optional[float]:
        v = series.get(day)
        if v is not None:
            return v
        d = _dt.date.fromisoformat(day)
        for _ in range(back):
            d -= _dt.timedelta(days=1)
            v = series.get(d.isoformat())
            if v is not None:
                return v
        return None

    def usd_rate(self, day: str, g: float) -> Optional[float]:
        a, b, c, d = (self.on(s, day) for s in self.usd)
        return usd_at(g, a, b, c, d)

    def _points(self, which: str, day: str) -> List[Tuple[float, float]]:
        hit = self._cache.get((which, day))
        if hit is None:
            src = self.ois if which == "ois" else self.off
            hit = [(x, v) for x, k in src for v in [self.on(self.ctx.series.get(k) or {}, day, 3)] if v is not None]
            self._cache[(which, day)] = hit
        return hit

    def ois360(self, day: str, g: float) -> Optional[float]:
        pts = self._points("ois", day)
        r = curve_at(pts, g) if len(pts) >= 3 else None
        return r * 360.0 / 365.0 if r is not None else None

    def offshore(self, day: str, g: float) -> Optional[float]:
        pts = self._points("off", day)
        return curve_at(pts, g) if len(pts) >= 2 else None


def live_curve(ctx: qf.Ctx, live: Dict[str, float], which: str) -> List[Tuple[float, float]]:
    """Today's OIS (ACT/365) or offshore curve: the live quotes, else the last closes."""
    prefix = "OIS:" if which == "ois" else "OFF:"
    out = []
    for k, m in ctx.meta.items():
        if not k.startswith(prefix) or not m.get("months") or (which == "off" and m.get("group") != "off"):
            continue
        if which == "ois" and m["months"] < 0.2:
            continue
        v = ctx.cur(k, live)
        if v is not None:
            out.append((_tenor_days(m["months"]), v))
    return out


def days_to(expiry: _dt.date, day: str, holidays: Set[_dt.date]) -> int:
    """g: calendar days from the day's spot date (T+1, TRY business days) to the expiry."""
    return (expiry - workday(_dt.date.fromisoformat(day), 1, holidays)).days


def contract_rates(c: Contract, cur: Curves, holidays: Set[_dt.date]) -> List[Dict[str, Any]]:
    """A contract day by day: g, its implied rate (per cent), the OIS and offshore rates at g, the spreads (bp)."""
    rows = []
    for day in sorted(c.close):
        px, s = c.close[day], cur.on(cur.spot, day, 3)
        if not px or not s:
            continue
        g = days_to(c.expiry, day, holidays)
        if g <= 0:
            continue
        u = cur.usd_rate(day, g)
        i = implied(px, s, u, g) if u is not None else None
        if i is None:
            continue
        o, f = cur.ois360(day, g), cur.offshore(day, g)
        rows.append({"day": day, "g": g, "implied": i, "ois": o, "basis": (i - o) * 100.0 if o is not None else None,
                     "off": f, "vs_off": (i - f) * 100.0 if f is not None else None})
    return rows


def constant_maturity(by_contract: Dict[str, List[Dict[str, Any]]], grid: Sequence[int] = CM_DAYS) -> Dict[int, Dict[str, Dict[str, float]]]:
    """``{G: {day: {"implied", "basis", "vs_off"}}}``: each day the contracts' points interpolated straight at G days
    (no extrapolation: a day whose contracts do not span G has no point)."""
    per_day: Dict[str, List[Dict[str, Any]]] = {}
    for rows in by_contract.values():
        for r in rows:
            per_day.setdefault(r["day"], []).append(r)
    out: Dict[int, Dict[str, Dict[str, float]]] = {G: {} for G in grid}
    for day, rows in per_day.items():
        rows = sorted(rows, key=lambda r: r["g"])
        for G in grid:
            lo = next((r for r in reversed(rows) if r["g"] <= G), None)
            hi = next((r for r in rows if r["g"] >= G), None)
            if lo is None or hi is None:
                continue
            w = 0.0 if hi["g"] == lo["g"] else (G - lo["g"]) / float(hi["g"] - lo["g"])
            point = {}
            for k in ("implied", "basis", "vs_off"):
                a, b = lo.get(k), hi.get(k)
                if a is not None and b is not None:
                    point[k] = a + (b - a) * w
            if "implied" in point:
                out[G][day] = point
    return out


def at_maturity(cm: Dict[int, Dict[str, Dict[str, float]]], g: float, field: str) -> Dict[str, float]:
    """A field's history at g days: between the constant maturities around g (flat beyond the grid)."""
    grid = sorted(cm)
    if not grid:
        return {}
    lo = max([G for G in grid if G <= g] or [grid[0]])
    hi = min([G for G in grid if G >= g] or [grid[-1]])
    out: Dict[str, float] = {}
    for day, a in cm[lo].items():
        b = cm[hi].get(day)
        if b is None or field not in a or field not in b:
            continue
        w = 0.0 if hi == lo else (g - lo) / float(hi - lo)
        out[day] = a[field] + (b[field] - a[field]) * w
    return out


# ---------------------------------------------------------------------------------------------- the calendar
def month_end_offset(day: _dt.date, holidays: Set[_dt.date]) -> int:
    """Business days to the month's last business day: 0 on it, −1 the one before …; the first business days of a
    month +1, +2 … (counted from the previous month's last)."""
    prev_last = workday(_dt.date(day.year, day.month, 1), -1, holidays)       # the previous month's last business day
    n, d = 0, prev_last
    while d < day and n <= 3:
        d = workday(d, 1, holidays)
        n += 1
    if d == day and 1 <= n <= 3:
        return n                                           # one of the month's first three business days
    nxt = _dt.date(day.year + (day.month // 12), day.month % 12 + 1, 1)
    last = workday(nxt, -1, holidays)
    n, d = 0, day
    while d < last:
        d = workday(d, 1, holidays)
        n += 1
    return -n


def _mean_t(xs: Sequence[float]) -> Dict[str, Any]:
    n = len(xs)
    m = qm.mean(xs) if n else None
    sd = qm.stdev(xs) if n >= 3 else None
    return {"n": n, "mean": m, "sd": sd, "t": m / (sd / math.sqrt(n)) if m is not None and sd else None}


def calendar_effects(series: Dict[str, float], holidays: Set[_dt.date]) -> Dict[str, Any]:
    """The spread's day-to-day changes (bp) by business days to the month end (−5 … +3; every month and the quarter
    ends) and by weekday: mean, standard deviation, t."""
    days = sorted(series)
    ch = [(days[i], series[days[i]] - series[days[i - 1]]) for i in range(1, len(days))
          if (_dt.date.fromisoformat(days[i]) - _dt.date.fromisoformat(days[i - 1])).days <= 5]
    month: Dict[int, List[float]] = {}
    quarter: Dict[int, List[float]] = {}
    week: Dict[int, List[float]] = {}
    for day, c in ch:
        d = _dt.date.fromisoformat(day)
        k = month_end_offset(d, holidays)
        if -5 <= k <= 3:
            month.setdefault(k, []).append(c)
            ref = d if k <= 0 else workday(_dt.date(d.year, d.month, 1), -1, holidays)
            if ref.month in (3, 6, 9, 12):
                quarter.setdefault(k, []).append(c)
        week.setdefault(d.weekday(), []).append(c)
    return {"month_end": [dict(_mean_t(month.get(k, [])), k=k) for k in range(-5, 4)],
            "quarter_end": [dict(_mean_t(quarter.get(k, [])), k=k) for k in range(-5, 4)],
            "weekday": [dict(_mean_t(week.get(w, [])), w=w) for w in range(5)], "n": len(ch)}


def seasonal_drift(effects: Dict[str, Any], days: Sequence[_dt.date], holidays: Set[_dt.date], t_min: float = 2.0) -> float:
    """The spread's expected change (bp) over ``days`` from the month-end effects the history shows clearly (|t| ≥
    t_min; the quarter-end ones on a quarter's end)."""
    by_k = {r["k"]: r for r in effects.get("month_end") or []}
    by_q = {r["k"]: r for r in effects.get("quarter_end") or []}
    total = 0.0
    for d in days:
        k = month_end_offset(d, holidays)
        ref = d if k <= 0 else workday(_dt.date(d.year, d.month, 1), -1, holidays)
        row = (by_q if ref.month in (3, 6, 9, 12) else by_k).get(k)
        if row and row.get("t") is not None and abs(row["t"]) >= t_min and row.get("mean") is not None:
            total += row["mean"]
    return total


def expiry_profile(by_contract: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The implied rate's day-to-day noise by days to expiry: near the expiry a few kuruş move the rate a lot - the
    standard deviation of its daily change (bp) and of its spread over OIS."""
    buckets = ((1, 5), (6, 10), (11, 20), (21, 40), (41, 90), (91, 400))
    acc: Dict[Tuple[int, int], Tuple[List[float], List[float]]] = {b: ([], []) for b in buckets}
    for rows in by_contract.values():
        for a, b in zip(rows, rows[1:]):
            if (_dt.date.fromisoformat(b["day"]) - _dt.date.fromisoformat(a["day"])).days > 5:
                continue
            for lo, hi in buckets:
                if lo <= b["g"] <= hi:
                    acc[(lo, hi)][0].append((b["implied"] - a["implied"]) * 100.0)
                    if a.get("basis") is not None and b.get("basis") is not None:
                        acc[(lo, hi)][1].append(b["basis"] - a["basis"])
    out = []
    for lo, hi in buckets:
        imp, bas = acc[(lo, hi)]
        out.append({"from": lo, "to": hi, "n": len(imp), "sd_implied": qm.stdev(imp) if len(imp) >= 3 else None,
                    "sd_basis": qm.stdev(bas) if len(bas) >= 3 else None})
    return out


def daily_ranges(c: Contract, spot_high: Dict[str, float], spot_low: Dict[str, float], days: int = 20) -> Dict[str, Any]:
    """The future's and spot's daily high − low (price) over the last ``days`` days they have."""
    rng = [c.high[d] - c.low[d] for d in sorted(set(c.high) & set(c.low))[-days:] if c.high[d] >= c.low[d]]
    srng = [spot_high[d] - spot_low[d] for d in sorted(set(spot_high) & set(spot_low))[-days:] if spot_high[d] >= spot_low[d]]
    return {"n": len(rng), "range": qm.mean(rng) if rng else None, "range_max": max(rng) if rng else None,
            "spot_range": qm.mean(srng) if srng else None, "spot_n": len(srng)}


# ---------------------------------------------------------------------------------------------- where it may go
def _phi(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def p_min_below(x0: float, level: float, m: float, v: float) -> float:
    """P(the path's minimum ≤ level): a Brownian motion from x0 with drift m and variance v over the horizon (the
    reflection principle with drift); 1 for a level not below x0."""
    if level >= x0:
        return 1.0
    if v <= 0:
        return 1.0 if x0 + m <= level else 0.0
    s = math.sqrt(v)
    a = level - x0
    e = 2.0 * m * a / v
    second = math.exp(e) * _phi((a + m) / s) if e < 700 else 1.0
    return min(1.0, _phi((a - m) / s) + second)


def p_max_above(x0: float, level: float, m: float, v: float) -> float:
    """P(the path's maximum ≥ level): the minimum of the mirrored path."""
    return p_min_below(-x0, -level, -m, v)


def level_for(p: float, x0: float, m: float, v: float, side: str) -> Optional[float]:
    """The level a buy order (``side`` "buy": the path's minimum) or a sell order (its maximum) is reached at with
    probability p over the horizon."""
    if v <= 0 or not 0.0 < p < 1.0:
        return None
    s = math.sqrt(v)
    if side == "buy":
        lo, hi = x0 - 12.0 * s - abs(m), x0
        prob = lambda L: p_min_below(x0, L, m, v)        # noqa: E731 - rises with L
        if prob(hi - 1e-12) < p:
            return x0
    else:
        lo, hi = x0, x0 + 12.0 * s + abs(m)
        prob = lambda L: 1.0 - p_max_above(x0, L, m, v)  # noqa: E731 - rises with L
        if 1.0 - prob(lo + 1e-12) < p:
            return x0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if (prob(mid) > p) if side == "buy" else (prob(mid) > 1.0 - p):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


class Profile(object):
    """The rate's variance through a session: per 5-minute bar by half hour (per cent²) and between a close and the
    next open - scaled so that a day's total is the daily variance of the history (the bars give the shape, the
    history the size).  Without bars the day's variance is spread evenly over the session."""

    def __init__(self, daily_var: float, buckets: Optional[Dict[int, float]] = None, overnight: float = 0.0):
        self.steps = list(range(SESSION[0] + BAR_MINUTES, SESSION[1] + 1, BAR_MINUTES))      # the bars' end minutes
        if buckets:
            fill = qm.mean(list(buckets.values())) or 0.0
            raw = [buckets.get(self.bucket(t), fill) for t in self.steps]
        else:
            raw = [1.0] * len(self.steps)
            overnight = 0.0
        total = sum(raw) + max(0.0, overnight)
        k = daily_var / total if total > 0 else 0.0
        self.step_var = [r * k for r in raw]
        self.overnight = max(0.0, overnight) * k
        self.daily_var = daily_var
        self.shaped = bool(buckets)

    @staticmethod
    def bucket(minute: int) -> int:
        """The half hour a bar ending at ``minute`` belongs to (its start, minutes of the day)."""
        return (minute - 1) // 30 * 30

    def rest_of_day(self, minute: int) -> float:
        return sum(v for t, v in zip(self.steps, self.step_var) if t > minute)

    def day_share_left(self, minute: int) -> float:
        day = sum(self.step_var)
        return self.rest_of_day(minute) / day if day > 0 else 0.0


def week_days_left(today: _dt.date, holidays: Set[_dt.date]) -> List[_dt.date]:
    """The business days after ``today`` up to this week's Friday (the next week's on a weekend)."""
    ahead = (4 - today.weekday()) % 7
    if today.weekday() >= 5:
        ahead = ahead or 7
    friday = today + _dt.timedelta(days=ahead)
    out, d = [], today
    while d < friday:
        d += _dt.timedelta(days=1)
        if _bday(d, holidays):
            out.append(d)
    return out


def horizon(profile: Profile, now: _dt.datetime, holidays: Set[_dt.date], which: str) -> Tuple[float, float, List[_dt.date]]:
    """(variance, business days, the whole days ahead) from now to the end of today's session (``which`` "today")
    or of the week's."""
    minute = now.hour * 60 + now.minute
    open_today = _bday(now.date(), holidays) and minute < SESSION[1]
    v = profile.rest_of_day(max(minute, SESSION[0])) if open_today else 0.0
    n = profile.day_share_left(max(minute, SESSION[0])) if open_today else 0.0
    if open_today and minute < SESSION[0]:
        v += profile.overnight                                  # before the open: today's opening gap is still ahead
    ahead: List[_dt.date] = []
    if which == "week":
        ahead = week_days_left(now.date(), holidays)
        for _ in ahead:
            v += profile.overnight + sum(profile.step_var)
            n += 1.0
    return v, n, ahead


def ladder(x0: float, m: float, v: float, side: str, c: float = 1.0, probs: Sequence[float] = LADDER) -> List[Dict[str, Any]]:
    """The order levels a buy (the ask-implied rate's minimum) or a sell (the bid-implied rate's maximum) is reached
    at with each probability, the variance scaled by the calibration ``c`` (σ × c)."""
    vv = v * c * c
    out = []
    for p in probs:
        lvl = level_for(p, x0, m, vv, side)
        out.append({"p": p, "level": lvl, "move_bp": (lvl - x0) * 100.0 if lvl is not None else None})
    return out


def calibrate(series: Dict[str, float], fair: Dict[str, float], kappa: Optional[float], holidays: Optional[Set[_dt.date]] = None,
              sd_window: int = 60, probs: Sequence[float] = LADDER, warm: int = 60, h: int = 5) -> Dict[str, Any]:
    """How the levels held on the history: at each close (after ``warm`` days) the levels of a buy order (the minimum)
    and a sell order (the maximum) over the next ``h`` closes (a week) by the model (the pull to fair, the trailing
    daily σ, Broadie-Glasserman's shift for a minimum of closes instead of a continuous one) against the closes that
    came - the hit rate of each probability, and the σ multiplier c that brings the hit rates closest to the
    probabilities.  (A fixed week: the shift is good for a few closes, not for one or two.)"""
    days = sorted(series)
    vals = [series[d] for d in days]
    samples: List[Tuple[float, float, float, float, float, float]] = []      # x0, m, σ² h, realized min, max, σ
    for i in range(warm, len(days) - h):
        ch = [vals[j] - vals[j - 1] for j in range(max(1, i - sd_window + 1), i + 1)]
        sd = qm.stdev(ch) if len(ch) >= 20 else None
        if not sd:
            continue
        x0 = vals[i]
        f = fair.get(days[i])
        m = (f - x0) * (1.0 - math.exp(-kappa * h)) if f is not None and kappa else 0.0
        fut = vals[i + 1:i + 1 + h]
        samples.append((x0, m, sd * sd * h, min(fut), max(fut), sd))
    out: Dict[str, Any] = {"n": len(samples), "c": 1.0, "rows": []}
    if len(samples) < 20:
        return out
    shift = 0.5826                                  # a minimum of closes against a continuous one: β σ √Δt

    def hits(c: float) -> List[Tuple[float, float]]:
        # the level of probability p (level_for) was reached when the extreme that came - shifted for closes - is no more
        # likely than p by the model: one probability per sample and side instead of a level searched for every p
        ub = [p_min_below(x0, lo - shift * sd * c, m, v * c * c) for x0, m, v, lo, hi, sd in samples]
        us = [p_max_above(x0, hi + shift * sd * c, m, v * c * c) for x0, m, v, lo, hi, sd in samples]
        n = float(len(samples))
        return [(sum(1 for u in ub if u <= p) / n, sum(1 for u in us if u <= p) / n) for p in probs]

    raw = hits(1.0)
    best, best_err = 1.0, None
    for c in (0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 2.5):
        err = sum((hb - p) ** 2 + (hs - p) ** 2 for p, (hb, hs) in zip(probs, hits(c)))
        if best_err is None or err < best_err - 1e-12:
            best, best_err = c, err
    fitted = hits(best)
    out.update({"c": best, "rows": [{"p": p, "buy": rb, "sell": rs, "buy_fit": fb, "sell_fit": fs}
                                    for p, (rb, rs), (fb, fs) in zip(probs, raw, fitted)]})
    return out


# ---------------------------------------------------------------------------------------------- 5-minute bars
SPOT_BARS = "USDTRY Curncy"


class BarStore(object):
    """The 5-minute bars Bloomberg gave (open, high, low, close, volume; the bar's start, local time) in the quant
    bars' SQLite file, and the days asked of each (an empty day too: it is not asked again)."""

    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        with self._lock:
            self._db.execute("CREATE TABLE IF NOT EXISTS vbars (key TEXT NOT NULL, t TEXT NOT NULL, o REAL, h REAL, l REAL, c REAL, "
                             "v REAL, PRIMARY KEY (key, t)) WITHOUT ROWID")
            self._db.execute("CREATE TABLE IF NOT EXISTS vbar_days (key TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL, "
                             "asked TEXT NOT NULL, PRIMARY KEY (key, day)) WITHOUT ROWID")
            self._db.commit()

    def put(self, key: str, day: str, bars: Sequence[Tuple[str, float, float, float, float, float]]) -> int:
        rows = [(key, t, o, h, l, c, v) for t, o, h, l, c, v in bars if str(t).startswith(day)]
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO vbars (key, t, o, h, l, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            self._db.execute("INSERT OR REPLACE INTO vbar_days (key, day, n, asked) VALUES (?, ?, ?, ?)",
                             (key, day, len(rows), _dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
            self._db.commit()
        return len(rows)

    def asked(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            out: Dict[str, Dict[str, int]] = {}
            for k, d, n in self._db.execute("SELECT key, day, n FROM vbar_days"):
                out.setdefault(k, {})[d] = n
            return out

    def load(self, key: str, since: str = "") -> List[Tuple[str, float, float, float, float, float]]:
        with self._lock:
            return list(self._db.execute("SELECT t, o, h, l, c, v FROM vbars WHERE key = ? AND t >= ? ORDER BY t", (key, since)))

    def prune(self, before: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM vbars WHERE t < ?", (before,))
            self._db.execute("DELETE FROM vbar_days WHERE day < ?", (before,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def bar_store(quant: Any) -> Optional[BarStore]:
    """The quant worker's bar store (made once, next to the store: ``quant_bars.sqlite3``)."""
    st = getattr(quant, "_viop_bars", None)
    if st is None:
        folder = getattr(getattr(getattr(quant, "svc", None), "settings", None), "data_dir", None)
        if not folder:
            return None
        st = BarStore(os.path.join(folder, "quant_bars.sqlite3"))
        try:
            quant._viop_bars = st
        except AttributeError:
            pass
    return st


def bar_days(today: _dt.date, holidays: Set[_dt.date], n: int = BAR_DAYS) -> List[str]:
    """The ``n`` business days before today, oldest first."""
    out, d = [], today
    while len(out) < n:
        d = workday(d, -1, holidays)
        out.append(d.isoformat())
    return out[::-1]


def bar_keys(fronts: Sequence[str]) -> List[Tuple[str, str, str]]:
    """``(key, security, event)``: the front contracts' trades, USDTRY's bid and ask."""
    out = [("%s|TRADE" % t, t, "TRADE") for t in fronts]
    out += [("%s|BID" % SPOT_BARS, SPOT_BARS, "BID"), ("%s|ASK" % SPOT_BARS, SPOT_BARS, "ASK")]
    return out


def bar_plan(fronts: Sequence[str], days: Sequence[str], asked: Dict[str, Dict[str, int]]) -> List[Tuple[str, str, str, str]]:
    """What is still to ask: ``(key, security, event, day)``, the latest days first (they matter most)."""
    out = []
    for day in reversed(list(days)):
        for key, sec, ev in bar_keys(fronts):
            if day not in (asked.get(key) or {}):
                out.append((key, sec, ev, day))
    return out


def fetch_bars(quant: Any, fronts: Sequence[str], today: _dt.date, holidays: Set[_dt.date], limit: int = BAR_PER_REFRESH) -> Dict[str, Any]:
    """Live: ask Bloomberg for up to ``limit`` of the bars still missing (a whole past day of one security at a
    time, once - ``provider.intraday_bars``); nothing in replay or without the provider's bar request."""
    svc = getattr(quant, "svc", None)
    prov = getattr(svc, "provider", None)
    ask = getattr(prov, "intraday_bars", None)
    out = {"asked": 0, "bars": 0, "why": ""}
    if getattr(svc, "mode", "") != "live" or not callable(ask):
        out["why"] = "kayıtlı veri modu" if getattr(svc, "mode", "") != "live" else "Bloomberg bar isteği yok"
        return out
    store = bar_store(quant)
    if store is None:
        return out
    days = bar_days(today, holidays)
    store.prune(days[0])
    for key, sec, ev, day in bar_plan(fronts, days, store.asked())[:limit]:
        start = "%s %02d:%02d" % (day, SESSION[0] // 60, SESSION[0] % 60)
        end = "%s %02d:%02d" % (day, (SESSION[1] + BAR_MINUTES) // 60, (SESSION[1] + BAR_MINUTES) % 60)
        try:
            bars = ask(sec, start, end, BAR_MINUTES, ev, 60.0)
        except Exception as exc:  # noqa: BLE001 - a failed request is asked again later
            out["why"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
            break
        if bars is None:                                   # the limit, or no answer in time: later
            out["why"] = "Bloomberg yanıt vermedi ya da günlük sınır"
            break
        out["asked"] += 1
        out["bars"] += store.put(key, day, bars)
    return out


def bar_rates(store: BarStore, ticker: str, day: str, usd: Optional[float], g: int) -> List[Tuple[str, float, float, float]]:
    """A day's 5-minute implied rates of a contract: ``(bar start, close, low, high)`` - its trades against USDTRY's
    mid (bid + ask) / 2 of the same bar."""
    if usd is None or g <= 0:
        return []
    fut = {t: (l, h, c) for t, o, h, l, c, v in store.load("%s|TRADE" % ticker, day) if t.startswith(day)}
    bid = {t: c for t, o, h, l, c, v in store.load("%s|BID" % SPOT_BARS, day) if t.startswith(day)}
    ask = {t: c for t, o, h, l, c, v in store.load("%s|ASK" % SPOT_BARS, day) if t.startswith(day)}
    out = []
    for t in sorted(fut):
        if t in bid and t in ask:
            mid = (bid[t] + ask[t]) / 2.0
            lo, hi, c = fut[t]
            ic, il, ih = implied(c, mid, usd, g), implied(lo, mid, usd, g), implied(hi, mid, usd, g)
            if ic is not None and il is not None and ih is not None:
                out.append((t, ic, il, ih))
    return out


def _minute(t: str) -> int:
    return int(t[11:13]) * 60 + int(t[14:16])


def intraday_profile(days_rates: Dict[str, List[Tuple[str, float, float, float]]]) -> Dict[str, Any]:
    """From the bars: the variance of a bar's change by half hour (per cent²), the variance from a close to the next
    open, the average distance of each half hour from the day's mean (bp: when the rate is low or high in a day),
    and each day's range."""
    buckets: Dict[int, List[float]] = {}
    level: Dict[int, List[float]] = {}
    gaps: List[float] = []
    ranges = []
    prev_close: Optional[float] = None
    for day in sorted(days_rates):
        rows = days_rates[day]
        if len(rows) < 10:
            prev_close = rows[-1][1] if rows else prev_close
            continue
        if prev_close is not None:
            gaps.append(rows[0][1] - prev_close)
        mean = qm.mean([r[1] for r in rows]) or 0.0
        for (t0, c0, _, _), (t1, c1, _, _) in zip(rows, rows[1:]):
            buckets.setdefault(Profile.bucket(_minute(t1) + BAR_MINUTES), []).append((c1 - c0) ** 2)
        for t, c, _, _ in rows:
            level.setdefault(Profile.bucket(_minute(t) + BAR_MINUTES), []).append((c - mean) * 100.0)
        ranges.append({"day": day, "low": min(r[2] for r in rows), "high": max(r[3] for r in rows), "close": rows[-1][1],
                       "low_at": min(rows, key=lambda r: r[2])[0][11:16], "high_at": max(rows, key=lambda r: r[3])[0][11:16]})
        prev_close = rows[-1][1]
    var = {b: qm.mean(xs) for b, xs in buckets.items() if len(xs) >= 3}
    return {"buckets": var, "overnight": qm.mean([g * g for g in gaps]) if len(gaps) >= 2 else 0.0, "days": len(ranges),
            "shape": [{"from": b, "var": var.get(b), "level_bp": qm.mean(level[b]) if level.get(b) else None,
                       "n": len(buckets.get(b) or [])} for b in sorted(set(buckets) | set(level))],
            "ranges": ranges}


def intraday_calibration(days_rates: Dict[str, List[Tuple[str, float, float, float]]], profile: Profile, at: int = 11 * 60,
                         probs: Sequence[float] = LADDER) -> Dict[str, Any]:
    """The bars' days, read at ``at`` (11:00): the rest of the day's levels by the profile (no drift) against the
    lows and highs that came - the hit rate of each probability."""
    samples = []
    for day, rows in sorted(days_rates.items()):
        before = [r for r in rows if _minute(r[0]) + BAR_MINUTES <= at]
        after = [r for r in rows if _minute(r[0]) + BAR_MINUTES > at]
        if not before or len(after) < 5:
            continue
        samples.append((before[-1][1], min(r[2] for r in after), max(r[3] for r in after)))
    v = profile.rest_of_day(at)
    out: Dict[str, Any] = {"n": len(samples), "at": "%02d:%02d" % (at // 60, at % 60), "rows": []}
    if not samples or v <= 0:
        return out
    for p in probs:
        hb = sum(1 for x0, lo, hi in samples if lo <= (level_for(p, x0, 0.0, v, "buy") or x0))
        hs = sum(1 for x0, lo, hi in samples if hi >= (level_for(p, x0, 0.0, v, "sell") or x0))
        out["rows"].append({"p": p, "buy": hb / float(len(samples)), "sell": hs / float(len(samples))})
    return out


# ---------------------------------------------------------------------------------------------- the family, the page
def _slope(points: Sequence[Tuple[float, float]], g: float) -> Optional[float]:
    """The implied curve's slope at g (per cent a calendar day): between the listed contracts around it."""
    pts = sorted(points)
    if len(pts) < 2:
        return None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= g <= x1 and x1 > x0:
            return (y1 - y0) / (x1 - x0)
    (x0, y0), (x1, y1) = (pts[0], pts[1]) if g < pts[0][0] else (pts[-2], pts[-1])
    return (y1 - y0) / (x1 - x0) if x1 > x0 else None


def _size(dv01_usd: float, spot: Optional[float], usd: Optional[float], g: Optional[float]) -> Dict[str, Optional[float]]:
    """A future's size for a DV01 (USD a bp of its implied rate): the USD notional, the contracts (1.000 USD each)
    and the TRY nominal at spot.  A bp of the rate moves the price spot · g/360 · 1e-4 / (1 + USD g/360) per USD."""
    if not spot or not g or g <= 0 or usd is None:
        return {"usd": None, "contracts": None, "try_mn": None}
    per_usd = spot * g / 360.0 * 1e-4 / (1.0 + usd / 100.0 * g / 360.0)     # TRY a bp per USD of notional
    notional = dv01_usd * spot / per_usd                                    # USD a bp → TRY a bp → USD notional
    return {"usd": notional, "contracts": notional / 1000.0, "try_mn": notional * spot / 1e6}


def implied_history(ctx: qf.Ctx, eng: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every contract's implied rate day by day and the constant maturities through them: ``{"contracts", "rates",
    "cm"}`` (the family's, and the universe's VİOP lines - ``tto.quantuniv``)."""
    hol = set(ctx.holidays or ())
    contracts = contracts_of(ctx, eng)
    cur = Curves(ctx)
    rates = {c.ticker: contract_rates(c, cur, hol) for c in contracts}
    # until Bloomberg's history of a contract is in (the first live day), the VİOP history sheet's own days of it
    # (EK_VIOP: the drawn contracts, 120 days; its spread by the sheet's own formula)
    for v in getattr(ctx, "viop", None) or []:
        t = v.get("ticker")
        own = [{"day": d, "g": v["days"][d], "implied": v["imp"][d], "ois": v.get("ois360", {}).get(d),
                "basis": v.get("baz", {}).get(d), "off": None, "vs_off": None}
               for d in sorted(v.get("imp") or {}) if (v.get("days") or {}).get(d) and v["days"][d] > 0]
        if t and len(own) > len(rates.get(t) or []):
            rates[t] = own
    return {"contracts": contracts, "rates": rates, "cm": constant_maturity(rates)}


def fam_viop(ctx: qf.Ctx, eng: Dict[str, Any], bars: Optional[Dict[str, Dict[str, List[Tuple[str, float, float, float]]]]] = None
             ) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """Every contract's implied rate, the constant maturities, the calendar, the listed contracts' fair value and
    signals, and what the page computes again with the values now (``table["_build"]``: the order levels)."""
    hol = set(ctx.holidays or ())
    hist = implied_history(ctx, eng)
    contracts, rates, cm = hist["contracts"], hist["rates"], hist["cm"]
    if not contracts:
        return [], {"ok": False, "why": "VİOP kontratı yok (VİOP sayfası ve Bloomberg geçmişi)", "rows": []}
    win = int(ctx.cfg.get("viop_fair_window") or DEFAULTS["viop_fair_window"])
    listed = [c for c in contracts if not c.expired]
    live0 = ctx.derive_live(ctx.live)
    effects = calendar_effects((cm.get(30) and {d: p["basis"] for d, p in cm[30].items() if "basis" in p}) or {}, hol)
    mons: List[qf.Monitor] = []
    per: Dict[str, Dict[str, Any]] = {}
    dv01_usd, _ = ctx.dv01_size(live0) if hasattr(ctx, "dv01_size") else (1000.0, None)
    dv01_usd = dv01_usd or 1000.0
    for c in listed:
        t = c.ticker
        g_live = ctx.live.get("VQG:" + t)
        g = float(g_live) if g_live else float(days_to(c.expiry, ctx.today_iso, hol))
        if g <= 0:
            continue
        basis_hist = at_maturity(cm, g, "basis")
        implied_hist = at_maturity(cm, g, "implied")
        source = "sabit vadeli seri"
        if len(basis_hist) < max(60, ctx.min_obs() // 2):
            # too short at this maturity (no expired contracts yet): the contract's own days - its spread drifts a
            # little as it nears its expiry, the constant maturity's does not
            own = rates.get(t) or []
            basis_hist = {r["day"]: r["basis"] for r in own if r.get("basis") is not None}
            implied_hist = {r["day"]: r["implied"] for r in own}
            source = "kontratın kendi geçmişi"
        days = sorted(basis_hist)
        info: Dict[str, Any] = {"ticker": t, "name": c.name, "expiry": c.expiry.isoformat(), "g": g, "n_hist": len(rates.get(t) or []),
                                "n_cm": len(days), "source": source}
        recent = [basis_hist[d] for d in days[-win:]]
        mean_basis = qm.mean(recent) if len(recent) >= 20 else None
        # the last ``win`` daily changes (a shorter history: all of its changes - not its days against themselves)
        imp_days = sorted(implied_hist)[-win - 1:]
        ch = [implied_hist[b] - implied_hist[a] for a, b in zip(imp_days, imp_days[1:])]
        info["sd_daily"] = qm.stdev(ch) if len(ch) >= 20 else None
        info["mean_basis"] = mean_basis

        def calc(live: Dict[str, float], t: str = t, g: float = g) -> Optional[float]:
            mid = live.get("VQM:" + t)
            pts = live_curve(ctx, live, "ois")
            o = curve_at(pts, g) if len(pts) >= 3 else None
            return (mid - o * 360.0 / 365.0) * 100.0 if mid is not None and o is not None else None

        def quote(live: Dict[str, float], t: str = t, g: float = g, name: str = c.name) -> Optional[Dict[str, Any]]:
            # the contract as the desk trades it against spot: its implied TRY rate (ACT/360, %); at a zero gap the OIS of
            # its maturity on the same basis (held for the target and the stop: implied = OIS + gap exactly) - and the
            # contract's price at each, at today's spot and USD rate (the VİOP sheet's formula turned round:
            # price = spot · (1 + r · g/360) / (1 + USD · g/360), linear in r)
            if live.get("VQM:" + t) is None:
                return None
            pts = live_curve(ctx, live, "ois")
            o = curve_at(pts, g) if len(pts) >= 3 else None
            if o is None:
                return None
            fair = o * 360.0 / 365.0
            fo = qf.rate_text(fair)
            out: Dict[str, Any] = {"inst": "VİOP %s ima faizi" % name, "unit": "%", "digits": qf.RATE_DIGITS, "base": fair, "scale": 0.01,
                                   "gap": {"name": "OIS farkı", "of": "OIS'in", "at": "OIS'te"},
                                   "model": "vadesinin OIS'i (%s, ACT/360)" % fo, "note": "hedef / stop bugünkü OIS'le",
                                   "held": "Hedef ve stop vadesinin bugünkü OIS'iyle (%s, ACT/360): OIS oynarsa onlar da değişir." % fo}
            spot, usd = live.get("VQS:" + t), live.get("VQU:" + t)
            if spot and usd is not None and g > 0:
                a = spot / (1.0 + usd / 100.0 * g / 360.0)
                k = a * g / 36000.0
                out["alt"] = {"label": "fiyat", "unit": "", "digits": 4, "base": a + k * fair, "scale": k * 0.01}
                out["note"] += "; fiyat bugünkü spot ve USD faiziyle"
            return out

        spot, usd = live0.get("VQS:" + t), live0.get("VQU:" + t)
        size = _size(dv01_usd, spot, usd, g)
        info["size"] = size
        n_txt = " (%s kontrat)" % _fmt_int(size["contracts"]) if size.get("contracts") else ""
        legs = [{"key": "VQM:" + t, "name": "VİOP %s%s" % (c.name, n_txt), "weight": 1.0, "dv01_usd": dv01_usd,
                 "dv01": dv01_usd * spot if spot else None, "notional": size.get("try_mn")},
                {"key": SPOT_KEY, "name": "USDTRY spot", "weight": -1.0, "dv01_usd": 0.0, "dv01": 0.0, "notional": size.get("try_mn")}]
        mon = qf.mr_monitor(ctx, "viop:" + t, FAMILY, "VİOP", "VİOP %s ima − OIS" % c.name, "bp", 1, days, [basis_hist[d] for d in days],
                            "bp", legs, calc, explicit=True, min_share=0.5, info={"inputs": ["VQM:" + t, "VIOPF:" + t], "contract": t},
                            quote=quote, series_label="VİOP %s ima faizi − vadesinin OIS'i (bp)" % c.name,
                            note="Kontratın ima TRY faizinin aynı vadenin OIS'ine farkı (bp), sabit vadeli geçmişe göre: − ise ima faiz normalinin "
                                 "altında (vadeli almak için ucuz: Buy VİOP / Sell spot), + ise üstünde (Sell VİOP / Buy spot). Seviyeler sayfada.")
        if mon is not None:
            mons.append(mon)
            info["sid"] = mon.sid
            ou = (mon.info or {}).get("ou") or {}
            info["kappa"], info["half_life"] = ou.get("kappa"), mon.half_life
        per[t] = info
    # a contract with too few days of its own (a far month before its history is in): the daily σ of the contract
    # nearest to it by days to expiry - the page says whose
    have = [i for i in per.values() if i.get("sd_daily")]
    for info in per.values():
        if not info.get("sd_daily") and have:
            near = min(have, key=lambda i: abs(i["g"] - info["g"]))
            info["sd_daily"], info["sd_from"] = near["sd_daily"], near["name"]
    # the calibration of the week's levels: on the constant maturities' closes (30 and 91 days)
    cal: Dict[int, Dict[str, Any]] = {}
    for G in (30, 91):
        imp = {d: p["implied"] for d, p in (cm.get(G) or {}).items()}
        bas = {d: p["basis"] for d, p in (cm.get(G) or {}).items() if "basis" in p}
        days = sorted(bas)
        fair, ou = {}, qm.ou_fit([bas[d] for d in days[-win:]]) if len(days) >= 30 else None
        for i, d in enumerate(days):
            if i >= 20:
                m = qm.mean([bas[x] for x in days[max(0, i - win):i]])
                fair[d] = imp[d] - bas[d] / 100.0 + m / 100.0
        cal[G] = calibrate(imp, fair, (ou or {}).get("kappa"), hol) if len(days) >= 80 else {"n": 0, "c": 1.0, "rows": []}
    prof_daily = None
    for t in [c.ticker for c in listed]:
        sd = per.get(t, {}).get("sd_daily")
        if sd:
            prof_daily = sd
            break
    shape = intraday_profile(bars.get(listed[0].ticker) if bars and listed else {}) if bars else {"buckets": {}, "overnight": 0.0, "days": 0,
                                                                                                    "shape": [], "ranges": []}
    table: Dict[str, Any] = {
        "ok": True, "contracts": [], "cm": {str(G): len(cm.get(G) or {}) for G in CM_DAYS}, "calendar": effects,
        "expiry": expiry_profile(rates), "calibration": {str(G): cal[G] for G in cal}, "intraday": {k: shape[k] for k in ("shape", "days", "ranges")},
        "history": [{"ticker": c.ticker, "name": c.name, "expiry": c.expiry.isoformat(), "expired": c.expired, "days": len(c.close),
                     "rates": len(rates.get(c.ticker) or []), "highs": len(c.high)} for c in contracts],
        "ranges": [dict(daily_ranges(c, ctx.series.get("FXH:USDTRY") or {}, ctx.series.get("FXL:USDTRY") or {}), ticker=c.ticker, name=c.name)
                   for c in listed],
    }
    if bars and listed:
        prof = Profile((prof_daily or 0.0) ** 2, shape["buckets"], shape["overnight"]) if prof_daily else None
        if prof is not None:
            table["intraday"]["calibration"] = intraday_calibration(bars.get(listed[0].ticker) or {}, prof)

    def build(live: Dict[str, float], now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
        return _build(ctx, listed, per, effects, shape, cal, live, now or _dt.datetime.now())

    table["_build"] = build
    table["_history"] = lambda: hist                      # (the universe's VİOP lines read it: quantuniv.py)
    return mons, table


def _fmt_int(v: Optional[float]) -> str:
    return "–" if v is None else "{:,.0f}".format(v).replace(",", ".")


def _build(ctx: qf.Ctx, listed: List[Contract], per: Dict[str, Dict[str, Any]], effects: Dict[str, Any], shape: Dict[str, Any],
           cal: Dict[int, Dict[str, Any]], live: Dict[str, float], now: _dt.datetime) -> Dict[str, Any]:
    """The page's live part: each listed contract now (implied bid / ask / mid, OIS, offshore, fair, z) and its order
    levels for today and for the week, with the probabilities and the prices they stand for."""
    hol = set(ctx.holidays or ())
    ois_pts, off_pts = live_curve(ctx, live, "ois"), live_curve(ctx, live, "off")
    mids = [(float(live["VQG:" + c.ticker]), live["VQM:" + c.ticker]) for c in listed if live.get("VQG:" + c.ticker) and live.get("VQM:" + c.ticker) is not None]
    rows = []
    for c in listed:
        t = c.ticker
        info = per.get(t)
        if info is None:
            continue
        g = float(live.get("VQG:" + t) or info["g"])
        bid, ask, mid = live.get("VQB:" + t), live.get("VQA:" + t), live.get("VQM:" + t)
        o = curve_at(ois_pts, g) if len(ois_pts) >= 3 else None
        o360 = o * 360.0 / 365.0 if o is not None else None
        f = curve_at(off_pts, g) if len(off_pts) >= 2 else None
        row: Dict[str, Any] = {"ticker": t, "name": c.name, "expiry": info["expiry"], "g": g, "bid": bid, "ask": ask, "mid": mid,
                               "px_bid": live.get("VQPB:" + t), "px_ask": live.get("VQPA:" + t), "last": live.get("VQPL:" + t),
                               "spot": live.get("VQS:" + t), "usd": live.get("VQU:" + t), "ois": o360, "off": f,
                               "basis": (mid - o360) * 100.0 if mid is not None and o360 is not None else None,
                               "vs_off": (mid - f) * 100.0 if mid is not None and f is not None else None,
                               "mean_basis": info.get("mean_basis"), "sid": info.get("sid"), "half_life": info.get("half_life"),
                               "sd_daily": info.get("sd_daily"), "size": info.get("size"), "n_cm": info.get("n_cm"), "source": info.get("source")}
        fair = o360 + info["mean_basis"] / 100.0 if o360 is not None and info.get("mean_basis") is not None else None
        row["fair"] = fair
        # where the levels start: the quotes; a side without a quote from the other side, neither from the last trade
        # (a far month's book is often empty, one side of it now and then)
        last_i = implied(row["last"], row["spot"], row["usd"], g) if row["last"] and row["spot"] and row["usd"] is not None else None
        ref = mid if mid is not None else next((x for x in (bid, ask, last_i) if x is not None), None)
        x_buy, x_sell = (ask if ask is not None else ref), (bid if bid is not None else ref)
        row["ref"], row["last_implied"] = ref, last_i
        row["levels_from"] = ("kota" if bid is not None and ask is not None else "yalnız satış kotası (bid)" if bid is not None
                              else "yalnız alış kotası (ask)" if ask is not None else "son işlem fiyatı" if last_i is not None else None)
        sd = info.get("sd_daily")
        row["sd_from"] = info.get("sd_from")
        if not sd:
            row["levels_why"] = "oynaklık için geçmiş yok (%d gün)" % (info.get("n_cm") or 0)
        elif ref is None:
            row["levels_why"] = "canlı kota ve son işlem fiyatı yok"
        if sd and ref is not None:
            prof = Profile(sd * sd, shape.get("buckets") or None, shape.get("overnight") or 0.0)
            slope = _slope(mids, g)
            roll = -(slope or 0.0) * 7.0 / 5.0                      # a business day takes ~1,4 calendar days off g
            kappa = info.get("kappa") or 0.0
            c_cal = (cal.get(30) if g < 61 else cal.get(91) or {}).get("c") or 1.0
            row["calibration_c"] = c_cal
            row["roll_bp_day"] = roll * 100.0
            for which in ("today", "week"):
                v, n, ahead = horizon(prof, now, hol, which)
                # the calendar: today's effect for the part of its session still ahead (the week's horizon holds it too),
                # then the whole days ahead
                left = n - len(ahead)
                season = (left * seasonal_drift(effects, [now.date()], hol) + seasonal_drift(effects, ahead, hol)) / 100.0
                pull = (fair - ref) * (1.0 - math.exp(-kappa * n)) if fair is not None and kappa else 0.0
                m = pull + roll * n + season
                part: Dict[str, Any] = {"var": v, "days": n, "drift_bp": m * 100.0, "pull_bp": pull * 100.0, "season_bp": season * 100.0,
                                        "sigma_bp": math.sqrt(v) * c_cal * 100.0 if v > 0 else 0.0}
                if v > 0:
                    for side, x0 in (("buy", x_buy), ("sell", x_sell)):
                        if x0 is None:
                            continue
                        lad = ladder(x0, m, v, side, c_cal)
                        for step in lad:
                            step["price"] = price_of(step["level"], row["spot"], row["usd"], g) if step["level"] is not None and row["spot"] else None
                        part[side] = lad
                else:
                    part["why"] = "seans kapalı" if which == "today" else "bu haftanın seansı kalmadı"
                row[which] = part
        rows.append(row)
    return {"rows": rows, "at": now.strftime("%Y-%m-%d %H:%M"), "session": "%02d:%02d–%02d:%02d" % (SESSION[0] // 60, SESSION[0] % 60,
                                                                                                  SESSION[1] // 60, SESSION[1] % 60)}


# ---------------------------------------------------------------------------------------------- the worker's part
def _bars_of(quant: Any, listed: List[Contract], ctx: qf.Ctx) -> Dict[str, Dict[str, List[Tuple[str, float, float, float]]]]:
    """The fronts' implied rates from the stored 5-minute bars, day by day (live only: replay keeps none)."""
    if getattr(getattr(quant, "svc", None), "mode", "") != "live":
        return {}
    store = bar_store(quant)
    if store is None:
        return {}
    hol = set(ctx.holidays or ())
    cur = Curves(ctx)
    out: Dict[str, Dict[str, List[Tuple[str, float, float, float]]]] = {}
    for c in listed[:BAR_FRONTS]:
        per_day = {}
        for day in bar_days(ctx.today, hol):
            g = days_to(c.expiry, day, hol)
            prev = workday(_dt.date.fromisoformat(day), -1, hol).isoformat()      # the morning knows yesterday's USD rate
            rows = bar_rates(store, c.ticker, day, cur.usd_rate(prev, g), g)
            if rows:
                per_day[day] = rows
        out[c.ticker] = per_day
    return out


def run(quant: Any, ctx: qf.Ctx, eng: Dict[str, Any], mons: List[qf.Monitor], tables: Dict[str, Any],
        timing: Optional[Dict[str, float]] = None) -> None:
    """The full fit's part (``Quant.compute``): the family's monitors join ``mons``, the page's table ``tables["viop"]``.
    Never raises: a failure is the fit's error ``viop``."""
    t0 = time.perf_counter()
    try:
        listed = [c for c in contracts_of(ctx, eng) if not c.expired]
        m, tab = fam_viop(ctx, eng, _bars_of(quant, listed, ctx))
        mons.extend(m)
        tab["fronts"] = [c.ticker for c in listed[:BAR_FRONTS]]
        tables["viop"] = tab
        tables["regime"] = list(tables.get("regime") or []) + qf.regime_table(ctx, m)
    except Exception as exc:  # noqa: BLE001 - this module failing must not take the other families with it
        tables.setdefault("errors", {})["viop"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        tables["viop"] = {"ok": False, "why": tables["errors"]["viop"], "rows": []}
    if timing is not None:
        timing["viop"] = time.perf_counter() - t0


def refresh(quant: Any, fit: Dict[str, Any]) -> None:
    """The minute's refresh (``Quant.refresh_live``): live, a few of the missing 5-minute bars from Bloomberg."""
    tab = (fit.get("tables") or {}).get("viop") or {}
    fronts = tab.get("fronts") or []
    ctx = fit.get("ctx")
    if not fronts or ctx is None:
        return
    try:
        tab["bars_fetch"] = fetch_bars(quant, fronts, ctx.today, set(ctx.holidays or ()))
    except Exception as exc:  # noqa: BLE001 - the next minute tries again
        tab["bars_fetch"] = {"asked": 0, "bars": 0, "why": "%s: %s" % (type(exc).__name__, str(exc)[:160])}


def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "VİOP" reads: the table with its live part built now, the monitors' state, the signals."""
    from .quant import _clean
    raw = (fit.get("tables") or {}).get("viop") or {}              # the fit's own: its builder (the published copy has none)
    src = (v.get("tables") or {}).get("viop") or raw
    tab = {k: x for k, x in src.items() if not k.startswith("_")}
    tab["bars_fetch"] = raw.get("bars_fetch", tab.get("bars_fetch"))
    build = raw.get("_build")
    if callable(build):
        try:
            ctx = fit["ctx"]
            tab["live"] = build(ctx.derive_live(ctx.live))
        except Exception as exc:  # noqa: BLE001 - the page says why
            tab["live"] = {"rows": [], "why": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        for r in (tab.get("live") or {}).get("rows") or ():
            m = fit["mons"].get(r.get("sid") or "")
            if m is not None:
                r.update({"z": m.z, "level": m.level, "mean": m.mean, "sd": m.sd, "regime": (m.regime or {}).get("tag")})
    base["viop"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["page"] == VIEWS[what]]
    base["settings"] = fit["cfg"]
    base["coverage"] = [c for c in fit.get("coverage") or () if covers(c.get("key") or "")]
    base["errors"] = {k: e for k, e in ((v.get("tables") or {}).get("errors") or {}).items() if k == "viop"}
    base["mode"] = getattr(quant.svc, "mode", "")
    return _clean(base)
