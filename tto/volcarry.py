"""Realized volatility of anything typed the way a broker writes it, and carry measured against it.

The history is the dashboard's own store of daily closes (``tto/history.py``): the TRY OIS tenors, the
cross-currency swaps and the offshore implied rates.  What is typed is read by the broker-chat parser:

    18m             an outright                       level in per cent, changes in bp
    1y5y, 1v5y      a spread (long − short)           basis points
    2y3y4y          a fly (2·body − wings)            basis points
    9x12, 1y1y      a forward / FRA                   per cent, from the par curve of each day
    5y x, xccy 2y5y the same on the cross-currency curve
    TRT150328T24    a bond by its ISIN                its yield in per cent (a floater: its price)

Realized volatility here is the standard deviation of the daily changes in basis points (the sample one, as
Excel's STDEV) over the last n changes; "annual" is that times √252.  A change is taken between two days on
which every leg has a close of its own - a holiday is not a day without a move.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import brokerchat as bc

WINDOWS = (10, 20, 60, 120, 250)
Z_WINDOWS = (60, 120, 250)  # z-score of the level: ~3 months, ~6 months, a year of closes
MIN_Z = 20                  # closes a z-score needs at least
YEAR = 252.0
MIN_CHANGES = 5            # fewer changes than this are no volatility
PRODUCTS = ("OIS", "XCCY", "DIBS")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


# ---------------------------------------------------------------------------------------------- what is typed
def parse_items(text: Any) -> List[Dict[str, Any]]:
    """The instruments of a typed list (one per line, or separated by commas): what the broker-chat parser reads
    of each - product, kind, tenors.  Something it cannot read is kept with ``ok`` false."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in re.split(r"[\n;,]+", str(text or "")):
        raw = " ".join(raw.split())
        if not raw:
            continue
        isin = raw.replace(" ", "").upper()
        if _ISIN.match(isin) and any(ch.isdigit() for ch in isin[2:-1]):
            if "DIBS:" + isin not in seen:
                seen.add("DIBS:" + isin)
                out.append({"raw": raw, "ok": True, "product": "DIBS", "kind": "outright", "tenors": [isin], "months": [None],
                            "label": isin, "key": "DIBS:outright:" + isin, "unit": "pct"})
            continue
        q = bc.parse_quote(raw)
        if q is None:
            out.append({"raw": raw, "ok": False, "error": "enstrüman anlaşılamadı (örn. 18m, 1y5y, 2y3y4y, 9x12)"})
            continue
        if q["key"] in seen:
            continue
        seen.add(q["key"])
        out.append({"raw": raw, "ok": True, "product": q["product"], "kind": q["kind"], "tenors": q["tenors"], "months": q["months"],
                    "label": q["label"], "key": q["key"], "unit": q["unit"]})
    return out


def item_of(kind: str, tenors: Sequence[str], product: str = "OIS") -> Dict[str, Any]:
    """An instrument that is not typed but listed (the flies of the carry table)."""
    tenors = [t.strip().upper() for t in tenors]
    return {"raw": "/".join(tenors), "ok": True, "product": product, "kind": kind, "tenors": tenors,
            "months": [bc._label_months(t) for t in tenors], "label": bc.instrument_label(kind, tenors),
            "key": bc.instrument_key(product, kind, tenors), "unit": "bp" if kind in ("spread", "fly") else "pct"}


# ---------------------------------------------------------------------------------------------- levels through time
def bootstrap_forward(pars: Dict[float, float], start: int, end: int) -> Optional[float]:
    """The forward par rate (per cent) between two month counts from the par rates of one day (months -> per
    cent), the way the blotter prices a FRA: (R_end·A_end − R_start·A_start)/(A_end − A_start) on a quarterly
    grid.  The grid's par rates are read off the quoted ones (linear in months), discount factors are bootstrapped
    with quarters of a year: close enough for how much a forward moves, not a price."""
    if start < 0 or end <= start or start % 3 or end % 3:
        return None
    known = sorted((m, r) for m, r in pars.items() if r is not None and m >= 1)
    if not known or known[-1][0] < end:
        return None

    def par(m: float) -> float:
        if m <= known[0][0]:
            return known[0][1]
        for (m0, r0), (m1, r1) in zip(known, known[1:]):
            if m0 <= m <= m1:
                return r0 + (r1 - r0) * (m - m0) / (m1 - m0)
        return known[-1][1]

    annuity = a_start = r_start = 0.0
    r = 0.0
    for m in range(3, end + 1, 3):
        r = par(m) / 100.0
        df = (1.0 - r * annuity) / (1.0 + r * 0.25)
        annuity += 0.25 * df
        if m == start:
            a_start, r_start = annuity, r
    if start == 0:
        return r * 100.0
    if annuity - a_start <= 0:
        return None
    return (r * annuity - r_start * a_start) / (annuity - a_start) * 100.0


def series_of(item: Dict[str, Any], curve: Dict[str, Dict[str, float]], months: Dict[str, float]) -> Tuple[List[str], List[float], str]:
    """The level of an instrument on every day all its legs closed: ``(days, levels, why not)``.

    ``curve`` is the history of one product: tenor label -> {ISO day: close in per cent}; ``months`` the length
    of each tenor.  Levels are in the instrument's own unit (per cent, or bp for a spread and a fly)."""
    kind, tenors = item["kind"], item["tenors"]
    if kind in ("outright", "spread", "fly"):
        legs = [curve.get(t) or {} for t in tenors]
        missing = [t for t, s in zip(tenors, legs) if not s]
        if missing:
            return [], [], "geçmişi yok: " + ", ".join(missing)
        days = sorted(set(legs[0]).intersection(*legs[1:]))
        weights = {"outright": (1.0,), "spread": (-100.0, 100.0), "fly": (-100.0, 200.0, -100.0)}[kind]
        return days, [sum(w * s[d] for w, s in zip(weights, legs)) for d in days], ""
    m = [bc._label_months(t) for t in tenors]
    if None in m or len(m) != 2:
        return [], [], "forward için ay / yıl vadeleri gerekir"
    start, end = (m[0], m[1]) if kind == "fra" else (m[0], m[0] + m[1])
    if start % 3 or end % 3 or end <= start:
        return [], [], "forward ayları 3'ün katı olmalı (örn. 9x12, 1y1y)"
    quoted = {t: s for t, s in curve.items() if s and months.get(t) and months[t] >= 1}
    reach = min((months[t] for t in quoted if months[t] >= end), default=None)
    if reach is None:
        return [], [], "eğrinin geçmişi %d aya kadar yok" % end
    quoted = {t: s for t, s in quoted.items() if months[t] <= reach}
    # a tenor that closes now and then would leave few days in common: the curve is the tenors that close daily
    most = max(len(s) for s in quoted.values())
    daily = {t: s for t, s in quoted.items() if len(s) >= 0.8 * most}
    if not any(months[t] >= end for t in daily):
        return [], [], "eğrinin geçmişi %d aya kadar yok" % end
    days = sorted(set.intersection(*[set(s) for s in daily.values()]))
    out_days: List[str] = []
    levels: List[float] = []
    for d in days:
        v = bootstrap_forward({months[t]: s[d] for t, s in daily.items()}, int(start), int(end))
        if v is not None:
            out_days.append(d)
            levels.append(v)
    return out_days, levels, "" if levels else "forward hesaplanamadı"


# ---------------------------------------------------------------------------------------------- volatility
def stdev(values: Sequence[float]) -> Optional[float]:
    """Sample standard deviation (Excel's STDEV); ``None`` for fewer than two values."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    return math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))


def changes_bp(levels: Sequence[float], unit: str) -> List[float]:
    k = 100.0 if unit == "pct" else 1.0
    return [(b - a) * k for a, b in zip(levels, levels[1:])]


def realized(levels: Sequence[float], unit: str, windows: Sequence[int] = WINDOWS) -> Dict[int, Optional[Dict[str, Any]]]:
    """Daily realized volatility in bp over the last n changes, for each n: ``{"d": bp a day, "n": changes used,
    "full": the window is complete}``; ``None`` where there are too few changes to say."""
    moves = changes_bp(levels, unit)
    out: Dict[int, Optional[Dict[str, Any]]] = {}
    for n in windows:
        part = moves[-n:]
        sd = stdev(part) if len(part) >= MIN_CHANGES else None
        out[n] = None if sd is None else {"d": sd, "n": len(part), "full": len(part) == n}
    return out


def rolling(levels: Sequence[float], unit: str, window: int) -> List[Optional[float]]:
    """The realized volatility of the ``window`` changes ending on each day (``None`` until there are that many)."""
    moves = changes_bp(levels, unit)
    out: List[Optional[float]] = [None] * len(levels)
    for i in range(window, len(moves) + 1):
        out[i] = stdev(moves[i - window:i])
    return out


def describe(item: Dict[str, Any], curve: Dict[str, Dict[str, float]], months: Dict[str, float], window: int = 20,
             keep: int = 260) -> Dict[str, Any]:
    """Everything the page shows of one instrument: level, last move, volatility per window, and the last
    ``keep`` days of level and rolling volatility for the chart."""
    row = dict(item)
    days, levels, why = series_of(item, curve, months)
    if not levels:
        row.update({"ok": False, "error": why or "geçmişi yok"})
        return row
    moves = changes_bp(levels, item["unit"])
    roll = rolling(levels, item["unit"], window)
    row.update({"level": levels[-1], "day": days[-1], "first": days[0], "n": len(moves),
                "change": moves[-1] if moves else None, "vols": {str(n): v for n, v in realized(levels, item["unit"]).items()},
                "days": days[-keep:], "levels": levels[-keep:], "roll": roll[-keep:]})
    sd = row["vols"].get(str(window))
    row["sigma"] = moves[-1] / sd["d"] if moves and sd and sd["d"] > 0 else None        # the last move in its own volatility
    return row


# ---------------------------------------------------------------------------------------------- carry against it
def week_days(start: Any, end: Any) -> int:
    """Week days after ``start`` up to ``end`` (two dates): how many daily moves a horizon holds."""
    n = 0
    d = start
    while d < end:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def zscores(levels: Sequence[float], now: Optional[float], windows: Sequence[int] = Z_WINDOWS) -> Dict[str, Optional[float]]:
    """Where the level stands against its own past: (now − mean) / standard deviation of the last n closes, for
    each n (``None`` with fewer than :data:`MIN_Z` closes or no spread at all).  ``now`` is today's level - the
    market's when there is one, else the last close."""
    out: Dict[str, Optional[float]] = {}
    if now is None and levels:
        now = levels[-1]
    for n in windows:
        part = list(levels[-n:])
        sd = stdev(part) if len(part) >= MIN_Z else None
        out[str(n)] = None if now is None or not sd else (now - sum(part) / len(part)) / sd
    return out


def carry_row(item: Dict[str, Any], market: Optional[float], carry: Dict[str, Optional[float]], horizons: Dict[str, int],
              curve: Dict[str, Dict[str, float]], months: Dict[str, float], window: int) -> Dict[str, Any]:
    """One trade of the carry table next to its volatility: carry + roll over each horizon (bp, as the sheet
    has it), the realized volatility a day and over the horizon (a day's times √days), and their ratio."""
    days, levels, why = series_of(item, curve, months)
    vol = realized(levels, item["unit"], (window,))[window] if levels else None
    row: Dict[str, Any] = {"label": item["label"], "tenors": item["tenors"], "kind": item["kind"], "market": market,
                           "vol": vol["d"] if vol else None, "n": vol["n"] if vol else 0, "full": bool(vol and vol["full"]),
                           "error": "" if vol else (why or "geçmiş kısa"),
                           "z": zscores(levels, market if type(market) is float else None), "closes": len(levels)}
    for name, cr in carry.items():
        h = horizons.get(name) or 0
        over = vol["d"] * math.sqrt(h) if vol and h > 0 else None
        row["cr_" + name] = cr
        row["vol_" + name] = over
        row["ratio_" + name] = cr / over if cr is not None and over else None
    return row
