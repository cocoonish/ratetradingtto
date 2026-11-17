"""Trades: trades the desk or a trader enters to follow on their own - their MTM and P&L, apart from the desk's position.

Two lists (``scope``): **Masa** ("desk": everybody sees them and may enter one; the one who entered a trade or an
administrator changes, closes or deletes it) and **Kişisel** ("personal": its owner's only - nobody else reaches it,
an administrator neither: every way in goes through :meth:`TradeBook._visible`).  Products: TRY OIS (outright, a
meeting's period, spread, fly, FRA), SOFR the same, DİBS, FX spot, FX option.  Nothing of the desk's reads them: the
blotter, its positions, the DV01 risk and the RET flow read the ``trades`` table, never ``tradebook`` (store.py).  A
trade names its instrument by ISIN, pair, dates and a meeting's date - never by a row of a page.

The valuation is tto/tradevalue.py's (``market`` once, then ``value`` per trade).  It runs only when asked - "MTM
yenile", a trade closed - and once a day at the desk's close (``trades_close`` of the desk's settings, 17:30), when the
value of every open trade is kept (``tradebook_closes``).  A close missed while the dashboard was off is taken at its
next start, dated the day it was missed; a day is never taken twice.

P&L periods, each split into carry and price effect (:func:`pnl_periods`):

* **Günlük** - now against the last close (a trade dealt since: against its inception);
* **Haftalık** - against the last close of the week before;
* **Toplam** - against the inception: 0 for a linear trade (dealt at its price), the premium for an option.

The value at a moment is ``mtm + accrued`` (the cash the trade has paid / received since it started); a trade closed
in the period counts with its realised value.  The **carry** of a period: each close's carry per calendar day
(``carry_1d``) times the days to the next close, and the last close's pro rata to now (before its first close a trade
earns at its first known carry); the **price effect** is the rest.  Spreads, flies and FRAs are worked out leg by leg
too (a FRA's legs are the attribution of its single value: what they leave over is shown).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import shortcuts
from . import tradevalue as tv
from .inputs import _fold, parse_amount, parse_date, parse_number
from .service import ServiceError
from .xl.values import serial_to_date

SCOPES = ("desk", "personal")
SCOPE_TEXT = {"desk": "Masa", "personal": "Kişisel"}
PRODUCT_TEXT = {"ois": "TRY OIS", "sofr": "SOFR", "dibs": "DİBS", "fxspot": "FX spot", "fxopt": "FX opsiyon"}
STRUCTURE_TEXT = {"outright": "Outright", "mpc": "PPK", "spread": "Spread", "fly": "Fly", "fra": "FRA"}
#: how many legs a package has
LEGS = {"spread": 2, "fly": 3}
#: a package's side, as the desk says it: what it sets its legs to (short → long)
PACKAGE_SIDES = {"spread": {"steepener": ("receive", "pay"), "flattener": ("pay", "receive")},
                 "fly": {"rec_body": ("pay", "receive", "pay"), "pay_body": ("receive", "pay", "receive")}}
PACKAGE_SIDE_TEXT = {"steepener": "steepener", "flattener": "flattener", "rec_body": "REC gövde", "pay_body": "PAY gövde"}
#: the legs' DV01 per unit of the package's when the valuation does not say (tradevalue.defaults ``weights``)
WEIGHTS = {"spread": [1.0, 1.0], "fly": [0.5, 1.0, 0.5]}
SIDE_TEXT = {"receive": "RECEIVE", "pay": "PAY", "B": "ALIŞ", "S": "SATIŞ"}
#: the currency of an OIS / SOFR / DİBS trade (FX: the pair's first currency)
FIXED_CCY = {"ois": "TRY", "sofr": "USD", "dibs": "TRY"}
#: the holiday lists of a product's dates (FX: the pair's, extras.pair_calendar)
CALENDARS = {"ois": ("TRY",), "sofr": ("USD",), "dibs": ("TRY",)}
NOTE_MAX, BOOK_MAX = 300, 60
#: a nominal worked out from a DV01: to the nearest 5 mn of its currency, never less
ROUND_TO = 5e6
#: the DV01 a nominal is asked for to learn the DV01 per unit of nominal (linear: any rounding is lost in it)
PROBE_DV01 = 1e6
DEFAULT_CLOSE = "17:30"
#: a close missed while the dashboard was off is taken this many seconds after the start (the market data first)
CATCH_UP = 180.0
#: a close that failed is tried again after this many seconds
RETRY = 600.0
#: a form's market (defaults, DV01 sizing) is taken again after this many seconds
FORM_MARKET_SECONDS = 30.0
#: what of a trade does not change its value: a change of these keeps its close values
META_KEYS = ("note", "book", "manual_price", "closing", "close_date", "close_price")
KEYS = ("ccy", "try", "usd")
_FRA = re.compile(r"^\s*(\d{1,3})\s*[xX×*]\s*(\d{1,3})\s*$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PAIR = re.compile(r"[^A-Za-z]")


# ---------------------------------------------------------------------------------------------- text
def _tr(x: float, digits: int = 2) -> str:
    """A number as the desk reads it (1.234.567,89)."""
    s = "{:,.{d}f}".format(x, d=digits)
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _rate(x: Optional[float]) -> str:
    """A rate in percent: two decimals at least, four at most (38,50 · 38,125)."""
    if x is None:
        return "—"
    s = ("%.4f" % x).rstrip("0")
    if len(s.split(".")[1]) < 2:
        s = "%.2f" % x
    return _tr(float(s), len(s.split(".")[1]))


def _short(x: Optional[float]) -> str:
    """An amount as the desk says it: 100m, 2,5m, 500k, 1mr."""
    if x is None:
        return "—"
    a = abs(x)
    for unit, div in (("mr", 1e9), ("m", 1e6), ("k", 1e3)):
        if a >= div:
            return ("%.3f" % (x / div)).rstrip("0").rstrip(".").replace(".", ",") + unit
    return _tr(x, 0)


def _day_text(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    y, m, d = iso.split("-")
    return "%s.%s.%s" % (d, m, y)


def tenor_of(shortcut: Tuple[str, int]) -> Optional[str]:
    """The tenor a date shortcut says ("2Y", "18M", "3W") - ``None`` for the others (ay sonu, IMM, +5 …)."""
    kind, n = shortcut
    if kind == "M":
        return "%dY" % (n // 12) if n % 12 == 0 else "%dM" % n
    if kind == "W":
        return "%dW" % n
    return None


def pair_of(text: Any) -> Optional[str]:
    """"usdtry" / "USD/TRY" / "gbp" (against TRY) -> the pair's code; ``None`` when it is not one."""
    s = _PAIR.sub("", str(text or "")).upper()
    if len(s) == 3 and s != "TRY":
        return s + "TRY"
    if len(s) == 6 and s[:3] != s[3:]:
        return s
    return None


def package_label(t: Dict[str, Any]) -> str:
    """A spread's / fly's name by its legs' tenors: 2s5s, 2s5s10s - or the tenors / end dates one by one."""
    legs = t.get("legs") or []
    tenors = [str(lg.get("tenor") or "") for lg in legs]
    if tenors and all(re.match(r"^\d+Y$", x) for x in tenors):
        return "s".join(x[:-1] for x in tenors) + "s"
    return "/".join(x or _day_text(lg.get("end_date"))[:-4] + _day_text(lg.get("end_date"))[-2:] for x, lg in zip(tenors, legs))


def package_side(t: Dict[str, Any]) -> Optional[str]:
    """A package's side by its legs (short → long): steepener / flattener, REC gövde / PAY gövde."""
    sides = tuple(lg.get("side") for lg in t.get("legs") or [])
    for side, legs in PACKAGE_SIDES.get(t.get("structure") or "", {}).items():
        if legs == sides:
            return side
    return None


def package_level(legs: Sequence[Dict[str, Any]]) -> Optional[float]:
    """A spread's / fly's level in bp from its legs' rates (short → long): long − short; 2 × body − wings."""
    r = [lg.get("price") for lg in legs]
    if any(not isinstance(x, (int, float)) for x in r):
        return None
    if len(r) == 2:
        return round((r[1] - r[0]) * 100.0, 6)
    if len(r) == 3:
        return round((2 * r[1] - r[0] - r[2]) * 100.0, 6)
    return None


def price_text(t: Dict[str, Any], price: Optional[float] = None) -> str:
    """A trade's price in its own unit: %38,50 · −35,0 bp · 98,750 / %38,10 getiri · 42,1500 · 150.000 TRY."""
    p = t.get("price") if price is None else price
    product, st = t.get("product"), t.get("structure") or "outright"
    if product in ("ois", "sofr"):
        if st in ("spread", "fly"):
            return "—" if p is None else ("+" if p > 0 else "") + _tr(p, 1) + " bp"
        return "%" + _rate(p)
    if product == "dibs":
        if t.get("price_kind") == "yield" and price is None:
            return "%" + _rate(t.get("yield")) + " getiri"
        return "—" if p is None else _tr(p, 3)
    if product == "fxspot":
        return "—" if p is None else _tr(p, 4)
    if product == "fxopt":
        return "—" if p is None else _tr(p, 2) + " " + str(t.get("premium_ccy") or "")
    return "—" if p is None else _tr(p, 4)


def leg_text(lg: Dict[str, Any], t: Dict[str, Any]) -> str:
    """A leg as the desk says it: RECEIVE 2Y 100m @ %38,50."""
    when = lg.get("tenor") or "→ " + _day_text(lg.get("end_date"))
    return "%s %s %s @ %%%s" % (SIDE_TEXT.get(lg.get("side"), "?"), when, _short(lg.get("notional")), _rate(lg.get("price")))


def describe(t: Dict[str, Any], meeting_word: Optional[str] = None) -> str:
    """The trade in the desk's words."""
    product = t.get("product")
    if product in ("ois", "sofr"):
        cur = "TRY OIS" if product == "ois" else "SOFR"
        st = t.get("structure") or "outright"
        if st in ("spread", "fly"):
            side = package_side(t)
            return "%s %s%s %s" % (package_label(t), PACKAGE_SIDE_TEXT[side] + " " if side else "", cur, price_text(t))
        if st == "mpc":
            what = "%s %s" % (meeting_word or ("PPK" if product == "ois" else "FOMC"), _day_text(t.get("meeting")))
        elif st == "fra":
            what = "%s FRA" % (t.get("fra") or "%s→%s" % (_day_text(t.get("value_date")), _day_text(t.get("end_date"))))
        else:
            what = t.get("tenor") or "→ " + _day_text(t.get("end_date"))
        return "%s %s %s %s @ %%%s" % (SIDE_TEXT.get(t.get("side"), "?"), what, cur, _short(t.get("notional")), _rate(t.get("price")))
    side = SIDE_TEXT.get(t.get("side"), "?")
    if product == "dibs":
        from . import bonds as bd
        bond = bd.by_isin(t.get("isin") or "")
        name = "%s (%s)" % (bd.short_label(bond), t.get("isin")) if bond else str(t.get("isin"))
        return "%s %s %s @ %s" % (side, name, _short(t.get("notional")), price_text(t))
    if product == "fxspot":
        return "%s %s %s %s @ %s" % (side, t.get("pair"), _short(t.get("notional")), t.get("notional_ccy") or "", price_text(t))
    if product == "fxopt":
        return "%s %s %s %s %s %s · vade %s · prim %s" % (
            side, t.get("pair"), _tr(t.get("strike") or 0.0, 4).rstrip("0").rstrip(","), str(t.get("call_put") or "").upper(),
            _short(t.get("notional")), t.get("notional_ccy") or "", _day_text(t.get("expiry")), price_text(t))
    return str(product)


def fingerprint(t: Dict[str, Any]) -> str:
    """What a trade's value depends on, hashed: a close value kept under another one is of a trade since changed."""
    keep = {k: v for k, v in t.items() if k not in META_KEYS and k not in ("id", "status", "created_by", "created_at",
                                                                             "updated_by", "updated_at", "owner_name")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------- the P&L
def _f(v: Any) -> Optional[float]:
    """A finite number, or ``None``."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def rates(v: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """TL and USD per unit of a valuation's currency, as the valuation converted its own numbers."""
    ccy = str(v.get("ccy") or "").upper()

    def ratio(a: str, b: str) -> Optional[float]:
        x, y = _f(v.get(a)), _f(v.get(b))
        return x / y if x is not None and y else None

    fx_try = 1.0 if ccy == "TRY" else (ratio("mtm_try", "mtm") or ratio("carry_1d_try", "carry_1d"))
    fx_usd = 1.0 if ccy == "USD" else (ratio("mtm_usd", "mtm") or ratio("carry_1d_usd", "carry_1d"))
    return fx_try, fx_usd


def point_of(v: Optional[Dict[str, Any]], t: _dt.datetime, leg: bool = False) -> Optional[Dict[str, Any]]:
    """A valuation (or a leg of one) as a point of the P&L: its time, its value (``mtm`` + ``accrued``) and its carry per
    calendar day in its currency, TL and USD - ``None`` when it has no value."""
    if not v or (not leg and not v.get("ok")):
        return None
    mtm = _f(v.get("mtm"))
    if mtm is None:
        return None
    acc = 0.0 if leg else (_f(v.get("accrued")) or 0.0)
    fx_try, fx_usd = rates(v) if acc else (None, None)

    def plus(x: Optional[float], fx: Optional[float]) -> Optional[float]:
        if x is None:
            return None
        if not acc:
            return x
        return x + acc * fx if fx is not None else None

    return {"t": t, "V": {"ccy": mtm + acc, "try": plus(_f(v.get("mtm_try")), fx_try), "usd": plus(_f(v.get("mtm_usd")), fx_usd)},
            "c": {"ccy": _f(v.get("carry_1d")), "try": _f(v.get("carry_1d_try")), "usd": _f(v.get("carry_1d_usd"))}}


def inception_point(trade: Dict[str, Any], ref: Optional[Dict[str, Any]], t: _dt.datetime) -> Dict[str, Any]:
    """The value a trade starts with: 0 for a linear trade (dealt at its price); an option's premium, plus when it was
    bought and minus when sold - in the valuation's currency, TL and USD at the rates of ``ref`` (a valuation of it)."""
    zero = {"t": t, "V": {"ccy": 0.0, "try": 0.0, "usd": 0.0}, "c": None}
    if trade.get("product") != "fxopt":
        return zero
    prem = _f(trade.get("price"))
    if prem is None:
        return {"t": t, "V": {k: None for k in KEYS}, "c": None}
    prem *= 1.0 if trade.get("side") == "B" else -1.0
    out = {"ccy": None, "try": None, "usd": None}
    if ref:
        ccy = str(ref.get("ccy") or "").upper()
        fx_try, fx_usd = rates(ref)
        pc = str(trade.get("premium_ccy") or "").upper()
        in_ccy = prem if pc == ccy else (prem / fx_try if pc == "TRY" and fx_try else (prem / fx_usd if pc == "USD" and fx_usd else None))
        if in_ccy is not None:
            out = {"ccy": in_ccy, "try": in_ccy * fx_try if fx_try is not None else None,
                   "usd": in_ccy * fx_usd if fx_usd is not None else None}
    return {"t": t, "V": out, "c": None}


def carry_between(points: Sequence[Dict[str, Any]], a: _dt.datetime, b: _dt.datetime, key: str) -> Optional[float]:
    """The carry earned from ``a`` to ``b``: each point's carry per calendar day from its time to the next point's (the
    first one's back to ``a`` as well, the last one's on to ``b``)."""
    if b <= a:
        return 0.0
    pts = sorted(points, key=lambda p: p["t"])
    if not pts:
        return None
    total = 0.0
    for i, p in enumerate(pts):
        lo = a if i == 0 else max(a, p["t"])
        hi = b if i == len(pts) - 1 else min(b, pts[i + 1]["t"])
        if hi <= lo:
            continue
        rate = (p["c"] or {}).get(key)
        if rate is None:
            return None
        total += rate * (hi - lo).total_seconds() / 86400.0
    return total


def _empty(why: Optional[str], base: Optional[str], frm: Optional[str]) -> Dict[str, Any]:
    none = {k: None for k in KEYS}
    return {"pnl": dict(none), "carry": dict(none), "price": dict(none), "from": frm, "basis": base, "why": why, "out": False}


def _span(start: Dict[str, Any], end: Dict[str, Any], timeline: Sequence[Dict[str, Any]], base: str,
          frm: Optional[str]) -> Dict[str, Any]:
    out = _empty(None, base, frm)
    for k in KEYS:
        a, b = start["V"][k], end["V"][k]
        if a is None or b is None:
            continue
        pnl = b - a
        carry = carry_between(timeline, start["t"], end["t"], k)
        out["pnl"][k] = pnl
        out["carry"][k] = carry
        out["price"][k] = pnl - carry if carry is not None else None
    return out


def _one(trade: Dict[str, Any], name: str, base_day: Optional[str], first: _dt.date, end: Optional[Dict[str, Any]],
         end_why: Optional[str], snaps: Dict[str, Dict[str, Any]], state: Dict[str, str], inc: Dict[str, Any],
         timeline: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """One period of one series (the trade, or a leg)."""
    closed_on = trade.get("close_date") if trade.get("status") == "closed" else None
    if name != "total" and closed_on and base_day and closed_on <= base_day:
        out = _empty(None, None, base_day)                       # closed before the period: nothing in it
        for part in ("pnl", "carry", "price"):
            out[part] = {k: 0.0 for k in KEYS}
        out["out"] = True
        return out
    if end is None:
        return _empty(end_why or "değer yok", None, base_day)
    td = trade.get("trade_date") or ""
    if name == "total":
        start, base = inc, "inception"
    elif base_day is None:
        if td < first.isoformat():
            return _empty("henüz kapanış kaydı yok", None, None)
        start, base = inc, "inception"
    elif td > base_day:
        start, base = inc, "inception"                            # dealt after that close
    elif base_day in snaps:
        start, base = snaps[base_day], "close"
    elif state.get(base_day) == "bad":
        return _empty("%s kapanışında değerlenemedi" % _day_text(base_day), "close", base_day)
    elif state.get(base_day) == "changed":
        return _empty("işlem %s kapanışından sonra değiştirildi" % _day_text(base_day), "close", base_day)
    elif td == base_day:
        start, base = inc, "inception"                            # dealt that day, after its close was taken
    else:
        return _empty("%s kapanışında kaydı yok" % _day_text(base_day), "close", base_day)
    if base == "inception" and all(start["V"][k] is None for k in KEYS):
        return _empty("işlemin ilk değeri bilinmiyor (prim değerlemenin dövizine çevrilemedi)", base, td)
    return _span(start, end, timeline, base, base_day if base == "close" else td)


def monday_of(day: _dt.date) -> _dt.date:
    return day - _dt.timedelta(days=day.weekday())


def pnl_periods(trade: Dict[str, Any], end_val: Optional[Dict[str, Any]], end_t: _dt.datetime,
                snaps: Sequence[Tuple[str, _dt.datetime, Dict[str, Any]]], inception_t: _dt.datetime, today: _dt.date,
                last_close: Optional[str], week_close: Optional[str]) -> Dict[str, Any]:
    """A trade's daily, weekly and total P&L, each as carry + price effect, in its currency, TL and USD - and its legs'.

    ``end_val``: its valuation now (an open trade) or when it was closed (its realised value), at ``end_t``;
    ``snaps``: its close values ``(day, close moment, values)`` - those kept under another fingerprint are of the
    trade before a change and are not used; ``inception_t``: when it starts (its trade date's close); ``last_close`` /
    ``week_close``: the day of the last close and of the last close of the week before (``None``: none taken)."""
    fp = fingerprint(trade)
    end = point_of(end_val, end_t)
    end_why = (end_val or {}).get("why") if end is None else None
    ok: Dict[str, Dict[str, Any]] = {}
    vals: Dict[str, Dict[str, Any]] = {}
    state: Dict[str, str] = {}
    for day, at, v in snaps:
        if v.get("fp") != fp:
            state[day] = "changed"
            continue
        p = point_of(v, at)
        state[day] = "ok" if p else "bad"
        if p:
            ok[day], vals[day] = p, v
    timeline = [ok[d] for d in sorted(ok)] + ([end] if end else [])
    ref = end_val if end else (vals[max(vals)] if vals else None)
    inc = inception_point(trade, ref, inception_t)
    plan =(("day", last_close, today), ("week", week_close, monday_of(today)), ("total", None, today))
    out: Dict[str, Any] = {name: _one(trade, name, b, first, end, end_why, ok, state, inc, timeline) for name, b, first in plan}
    # the legs: each a series of its own (the same number of legs at both ends), its inception 0
    legs_now = (end_val or {}).get("legs") if end else None
    if isinstance(legs_now, list) and legs_now:
        n = len(legs_now)
        legs_out = []
        for i in range(n):
            lend = point_of(legs_now[i], end_t, leg=True)
            lsnaps: Dict[str, Dict[str, Any]] = {}
            lstate = dict(state)
            for day, v in vals.items():
                lv = v.get("legs")
                p = point_of(lv[i], ok[day]["t"], leg=True) if isinstance(lv, list) and len(lv) == n else None
                if p:
                    lsnaps[day] = p
                else:
                    lstate[day] = "bad"
            ltl = [lsnaps[d] for d in sorted(lsnaps)] + ([lend] if lend else [])
            linc = {"t": inception_t, "V": {k: 0.0 for k in KEYS}, "c": None}
            row = {"label": str(legs_now[i].get("label") or "%d. bacak" % (i + 1)),
                   "mtm": _f(legs_now[i].get("mtm")), "mtm_try": _f(legs_now[i].get("mtm_try")),
                   "mtm_usd": _f(legs_now[i].get("mtm_usd")), "price_now": _f(legs_now[i].get("price_now")),
                   "price_text": str(legs_now[i].get("price_text") or "")}
            for name, b, first in plan:
                row[name] = _one(trade, name, b, first, lend, "bacak değeri yok", lsnaps, lstate, linc, ltl)
            legs_out.append(row)
        out["legs"] = legs_out
        # what the legs leave over of the whole (a FRA's single value against its legs' attribution; cash)
        resid = {}
        for name, _, _ in plan:
            r = {}
            for part in ("pnl", "carry", "price"):
                r[part] = {}
                for k in KEYS:
                    whole = out[name][part][k]
                    parts = [lg[name][part][k] for lg in legs_out]
                    r[part][k] = whole - sum(parts) if whole is not None and all(x is not None for x in parts) else None
            resid[name] = r
        out["residual"] = resid
    return out


def _add(acc: Dict[str, Any], key: str, x: Optional[float]) -> None:
    if x is None:
        acc["missing"][key] = acc["missing"].get(key, 0) + 1
    else:
        acc[key] = (acc.get(key) or 0.0) + x


def totals(open_rows: Sequence[Dict[str, Any]], open_vals: Dict[int, Dict[str, Any]], closed_rows: Sequence[Dict[str, Any]],
           closed_vals: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """Per product and over all, in TL and USD: the open trades' MTM and daily / weekly / total P&L (carry + price
    effect) - the trades closed in a day / week counted in it with their realised value -, and the closed trades'
    realised P&L.  ``missing``: per column, the trades whose number is not known (left out of the sum)."""
    def blank() -> Dict[str, Any]:
        return {"count": 0, "closed": 0, "missing": {}}

    by: Dict[str, Dict[str, Any]] = {}
    every = blank()

    def put(product: str, key: str, x: Optional[float]) -> None:
        for acc in (by.setdefault(product, blank()), every):
            _add(acc, key, x)

    def periods(product: str, v: Dict[str, Any], names: Sequence[str], as_name: Optional[str] = None) -> None:
        for name in names:
            per = (v.get("periods") or {}).get(name)
            if not per:
                for part in ("pnl", "carry", "price"):
                    for ccy in ("try", "usd"):
                        put(product, "%s.%s.%s" % (as_name or name, part, ccy), None)
                continue
            if per.get("out"):
                continue
            for part in ("pnl", "carry", "price"):
                for ccy in ("try", "usd"):
                    put(product, "%s.%s.%s" % (as_name or name, part, ccy), per[part][ccy])

    for r in open_rows:
        p = r["product"]
        by.setdefault(p, blank())["count"] += 1
        every["count"] += 1
        v = open_vals.get(r["id"]) or {}
        put(p, "mtm.try", _f(v.get("mtm_try")) if v.get("ok") else None)
        put(p, "mtm.usd", _f(v.get("mtm_usd")) if v.get("ok") else None)
        periods(p, v, ("day", "week", "total"))
    for r in closed_rows:
        p = r["product"]
        by.setdefault(p, blank())["closed"] += 1
        every["closed"] += 1
        v = closed_vals.get(r["id"]) or {}
        periods(p, v, ("day", "week"))
        periods(p, v, ("total",), "realized")
    order = [p for p in tv.PRODUCTS if p in by] + [p for p in by if p not in tv.PRODUCTS]
    return {"products": [dict(by[p], product=p, label=PRODUCT_TEXT.get(p, p)) for p in order], "all": every}


# ---------------------------------------------------------------------------------------------- reading a form
class _Form(object):
    """A form's fields as typed, read one by one: what does not read goes to ``errors`` (field -> reason)."""

    def __init__(self, raw: Dict[str, Any], lang: str, today: _dt.date, holidays: Callable[[Tuple[str, ...]], Any]):
        self.raw = raw if isinstance(raw, dict) else {}
        self.lang = lang if lang in ("tr", "en") else "tr"
        self.today = today
        self.holidays = holidays
        self.errors: Dict[str, str] = {}
        self.echo: Dict[str, str] = {}
        self.leg_order: Optional[List[int]] = None          # a package's legs as typed, in the order they are kept

    def fail(self, key: str, why: str) -> None:
        self.errors.setdefault(key, why)

    @staticmethod
    def _blank(v: Any) -> bool:
        return v is None or (isinstance(v, str) and not v.strip())

    def text(self, key: str, limit: int, src: Optional[Dict[str, Any]] = None) -> Optional[str]:
        v = (src or self.raw).get(key)
        if self._blank(v):
            return None
        s = " ".join(str(v).split())
        if len(s) > limit:
            self.fail(key, "en fazla %d karakter" % limit)
            return None
        return s

    def number(self, key: str, what: str, src: Optional[Dict[str, Any]] = None, err: Optional[str] = None,
               required: bool = False, positive: bool = False, amount: bool = False, rate: bool = False) -> Optional[float]:
        """A number of the form: an amount as the desk types it ("5m", "250k") or a number in the user's format; a
        rate in percent ("38,50" or "%38,50": 38.5)."""
        err = err or key
        v = (src or self.raw).get(key)
        if self._blank(v):
            if required:
                self.fail(err, "%s gerekli" % what)
            return None
        if isinstance(v, bool):
            x = None
        elif isinstance(v, (int, float)):
            x = float(v)
        else:
            s = str(v).strip()
            if rate:
                s = s.replace("%", "")
            x = parse_amount(s, self.lang) if amount else parse_number(s, self.lang, prefer_decimal=True)
        if x is None or not math.isfinite(x):
            self.fail(err, "%s anlaşılamadı: %s" % (what, v))
            return None
        if positive and x <= 0:
            self.fail(err, "%s sıfırdan büyük olmalı" % what)
            return None
        return x

    def date(self, key: str, what: str, start: Optional[_dt.date], cal: Tuple[str, ...],
             src: Optional[Dict[str, Any]] = None, err: Optional[str] = None,
             required: bool = False) -> Tuple[Optional[_dt.date], Optional[str]]:
        """A date: as a date ("18.11.2026", "2026-11-18") or a shortcut of the dashboard ("2Y", "1A", "ay sonu", "+2" -
        tto/shortcuts.py) counted from ``start`` on the business days of ``cal``; with the tenor it says ("2Y")."""
        err = err or key
        v = (src or self.raw).get(key)
        if self._blank(v):
            if required:
                self.fail(err, "%s gerekli" % what)
            return None, None
        s = str(v).strip()
        if _ISO.match(s):
            try:
                return _dt.date.fromisoformat(s), None
            except ValueError:
                self.fail(err, "%s anlaşılamadı: %s" % (what, s))
                return None, None
        sc = shortcuts.date_shortcut(s)
        if sc is not None:
            if start is None:
                self.fail(err, "%s: kısayolun başlangıcı yok (önce tarihi girin)" % what)
                return None, None
            day = shortcuts.resolve(sc, start, self.today, self.holidays(cal))
            tenor = tenor_of(sc)
            self.echo[err] = "%s → %s" % (s, day.strftime("%d.%m.%Y"))
            return day, tenor
        serial = parse_date(s)
        if serial is None:
            self.fail(err, "%s anlaşılamadı: %s" % (what, s))
            return None, None
        return serial_to_date(serial), None

    def choice(self, key: str, options: Sequence[str], what: str, src: Optional[Dict[str, Any]] = None,
               err: Optional[str] = None, required: bool = True, default: Optional[str] = None) -> Optional[str]:
        err = err or key
        v = (src or self.raw).get(key)
        if self._blank(v):
            if required and default is None:
                self.fail(err, "%s seçin" % what)
            return default
        s = str(v).strip()
        folded = {_fold(o): o for o in options}
        if _fold(s) not in folded:
            self.fail(err, "%s anlaşılamadı: %s" % (what, s))
            return None
        return folded[_fold(s)]


def _iso(d: Optional[_dt.date]) -> Optional[str]:
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------------------------- the book
class TradeBook(object):
    def __init__(self, svc: Any):
        self.svc = svc
        self.store = svc.store
        self.now: Callable[[], _dt.datetime] = _dt.datetime.now
        started = getattr(svc, "started_at", None)
        self.started: _dt.datetime = _dt.datetime.fromtimestamp(started) if started else _dt.datetime.now()
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._retry_after = 0.0
        self._seq: Dict[str, int] = {}                       # "desk" / a user: how many times their lists changed
        self._mtm: Dict[Tuple[str, str], Dict[str, Any]] = {}     # (scope, owner or "") -> the last "MTM yenile"
        self._form_mkt: Optional[Tuple[float, Any]] = None

    # ------------------------------------------------------------------ who
    def _user(self, user: Optional[str]) -> str:
        return self.svc.require_user(user)

    def _admin(self, user: str) -> bool:
        return (self.store.account(user) or {}).get("role") == "admin"

    def _names(self) -> Dict[str, str]:
        return {u["name"]: u["display"] for u in self.store.users()}

    @staticmethod
    def _scope(scope: Any) -> str:
        s = str(scope or "desk").strip().lower()
        if s in ("masa",):
            s = "desk"
        if s in ("kisisel", "kişisel", "own"):
            s = "personal"
        if s not in SCOPES:
            raise ServiceError("kapsam 'desk' ya da 'personal' olmalı")
        return s

    def _visible(self, user: str, tid: Any) -> Dict[str, Any]:
        """A trade the user may see: the desk's, or their own.  Another trader's own trade is not there for anybody else
        - an administrator neither: the same answer as a trade that does not exist."""
        try:
            n = int(tid)
        except (TypeError, ValueError):
            raise ServiceError("işlem bulunamadı", 404)
        row = self.store.tb_get(n)
        if row is None or (row["scope"] == "personal" and row["owner"] != user):
            raise ServiceError("işlem bulunamadı", 404)
        return row

    def _may_change(self, user: str, row: Dict[str, Any]) -> bool:
        if row["scope"] == "personal":
            return row["owner"] == user
        return row["created_by"] == user or self._admin(user)

    def _mine(self, user: str, tid: Any) -> Dict[str, Any]:
        row = self._visible(user, tid)
        if not self._may_change(user, row):
            raise ServiceError("masanın işlemini yalnızca giren ya da bir yönetici değiştirebilir", 403)
        return row

    # ------------------------------------------------------------------ live
    def counter(self, user: Optional[str]) -> int:
        """How many times the user's lists changed (the desk's and their own) - the live stream carries it: nobody
        learns of another trader's own trades."""
        with self._lock:
            return self._seq.get("desk", 0) + (self._seq.get("u:" + user, 0) if user else 0)

    def _changed(self, scope: str, owner: str) -> None:
        key = "desk" if scope == "desk" else "u:" + owner
        with self._lock:
            self._seq[key] = self._seq.get(key, 0) + 1
            hit = self._mtm.get((scope, "" if scope == "desk" else owner))
            if hit is not None:
                hit["stale"] = True
        nudge = getattr(self.svc, "nudge", None)
        if nudge is not None:
            nudge()

    # ------------------------------------------------------------------ the engine
    def _engine(self, fn: Callable, *args: Any) -> Any:
        """On the calculation thread (what reads the engine's values must): the valuation's market and values."""
        et = getattr(self.svc, "et", None)
        return et.call(fn, *args) if et is not None else fn(*args)

    def _holidays(self, ccys: Tuple[str, ...]) -> Any:
        try:
            return self.svc.holiday_dates(ccys)
        except Exception:  # noqa: BLE001 - weekends only
            return frozenset()

    def _today(self) -> _dt.date:
        return self.now().date()

    @staticmethod
    def _value(trade: Dict[str, Any], mkt: Any, asof: Optional[str] = None) -> Dict[str, Any]:
        """tradevalue.value, never raising: a trade the valuation cannot take says why."""
        try:
            v = tv.value(trade, mkt, asof)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "why": "değerleme hatası: %s" % (str(exc)[:200] or type(exc).__name__)}
        return v if isinstance(v, dict) else {"ok": False, "why": "değerleme sonucu okunamadı"}

    @staticmethod
    def _keep(v: Dict[str, Any], greeks: bool = True) -> Dict[str, Any]:
        """What of a valuation is kept / sent: its numbers, texts and legs (not its inputs)."""
        out: Dict[str, Any] = {"ok": bool(v.get("ok")), "why": v.get("why")}
        for k in ("mtm", "mtm_try", "mtm_usd", "carry_1d", "carry_1d_try", "carry_1d_usd", "accrued", "price_now"):
            out[k] = _f(v.get(k))
        out["ccy"] = str(v.get("ccy") or "") or None
        out["price_text"] = str(v.get("price_text") or "")
        if greeks and isinstance(v.get("greeks"), dict):
            out["greeks"] = {str(k): _f(x) for k, x in v["greeks"].items() if _f(x) is not None}
        legs = v.get("legs")
        if isinstance(legs, list):
            out["legs"] = [{"label": str(lg.get("label") or ""), "mtm": _f(lg.get("mtm")), "mtm_try": _f(lg.get("mtm_try")),
                            "mtm_usd": _f(lg.get("mtm_usd")), "carry_1d": _f(lg.get("carry_1d")),
                            "carry_1d_try": _f(lg.get("carry_1d_try")), "carry_1d_usd": _f(lg.get("carry_1d_usd")),
                            "price_now": _f(lg.get("price_now")), "price_text": str(lg.get("price_text") or "")}
                           for lg in legs if isinstance(lg, dict)]
        return out

    @staticmethod
    def for_value(row: Dict[str, Any], as_open: bool = False) -> Dict[str, Any]:
        """The trade as tradevalue takes it."""
        t = {k: v for k, v in row.items() if k not in ("closing", "created_by", "created_at", "updated_by", "updated_at")}
        if as_open:
            t["status"] = "open"
            for k in ("close_date", "close_price"):
                t.pop(k, None)
        elif t.get("status") == "closed" and t.get("close_price") is not None:
            t["manual_price"] = t["close_price"]          # (a closed trade: its value at the price it was closed at)
        return t

    # ------------------------------------------------------------------ the desk's close
    def close_time(self) -> _dt.time:
        text = DEFAULT_CLOSE
        ops = getattr(self.svc, "ops", None)
        if ops is not None:
            try:
                text = str(ops.settings().get("trades_close") or DEFAULT_CLOSE)
            except Exception:  # noqa: BLE001
                text = DEFAULT_CLOSE
        try:
            h, m = (int(x) for x in text.split(":"))
            return _dt.time(h, m)
        except ValueError:
            return _dt.time(17, 30)

    def _business(self, day: _dt.date) -> bool:
        """A day the desk's market trades: a week day that is not one of its holidays."""
        if day.weekday() >= 5:
            return False
        ops = getattr(self.svc, "ops", None)
        if ops is not None and hasattr(ops, "market_day"):
            try:
                return bool(ops.market_day(day.isoformat()))
            except Exception:  # noqa: BLE001
                return True
        return True

    def close_due(self, now: Optional[_dt.datetime] = None) -> Optional[Tuple[str, bool]]:
        """The close to take now: the last business day whose close time has come, unless it was taken - ``(day,
        late)``.  A close missed while the dashboard was off (``late``) waits ``CATCH_UP`` seconds after the start
        (the market data first) and is then dated the day it was missed."""
        now = now or self.now()
        t = self.close_time()
        day = now.date() if now.time() >= t else now.date() - _dt.timedelta(days=1)
        for _ in range(15):
            if self._business(day):
                break
            day -= _dt.timedelta(days=1)
        else:
            return None
        if self.store.tb_close_day(day.isoformat()) is not None:
            return None
        late = self.started > _dt.datetime.combine(day, t)
        if late and (now - self.started).total_seconds() < CATCH_UP:
            return None
        return day.isoformat(), late

    def look(self, now: Optional[_dt.datetime] = None) -> Optional[Dict[str, Any]]:
        """One look of the desk's loop (tto/ops.py, every 15 s): the day's close when it is due."""
        if time.monotonic() < self._retry_after:
            return None
        now = now or self.now()
        due = self.close_due(now)
        if due is None:
            return None
        try:
            return self.take_close(due[0], due[1])
        except Exception:
            self._retry_after = time.monotonic() + RETRY
            raise

    def take_close(self, day: str, late: bool = False) -> Optional[Dict[str, Any]]:
        """Every trade open at ``day``'s close (the desk's and every trader's own), valued and kept with the day - once:
        ``None`` when the day was taken already."""
        with self._close_lock:
            if self.store.tb_close_day(day) is not None:
                return None
            rows = [r for r in self.store.tb_dealt_by(day)
                    if r["status"] == "open" or (r.get("close_date") or "") > day]

            def run() -> List[Tuple[int, Dict[str, Any]]]:
                mkt = tv.market(self.svc)
                out = []
                for r in rows:
                    v = self._keep(self._value(self.for_value(r, as_open=True), mkt, day), greeks=False)
                    v["fp"] = fingerprint(r)
                    out.append((r["id"], v))
                return out

            values = self._engine(run) if rows else []
            at = "%s %s" % (day, self.close_time().strftime("%H:%M"))
            if not self.store.tb_put_close(day, at, late, values):
                return None
        with self._lock:
            for k in list(self._seq):
                self._seq[k] += 1                            # (the pages show the last close)
        nudge = getattr(self.svc, "nudge", None)
        if nudge is not None:
            nudge()
        return {"day": day, "at": at, "late": late, "trades": len(values), "valued": sum(1 for _, v in values if v.get("ok"))}

    def close_info(self) -> Dict[str, Any]:
        days = self.store.tb_close_days(1)
        last = days[0] if days else None
        return {"time": self.close_time().strftime("%H:%M"),
                "last": {"day": last["day"], "at": last["at"], "taken_at": last["taken_at"], "late": bool(last["late"])} if last else None}

    # ------------------------------------------------------------------ reading a trade
    def _calendar(self, product: str, pair: Optional[str]) -> Tuple[str, ...]:
        if product in CALENDARS:
            return CALENDARS[product]
        from .extras import pair_calendar
        return pair_calendar(pair or "") or ("TRY",)

    def _sized(self, f: _Form, src: Dict[str, Any], prefix: str, ccy: str, what: str = "Nominal") -> Dict[str, Any]:
        """A nominal or a DV01 (``sized_by``: which one was typed): the DV01 per bp in USD or TL."""
        typed = str(src.get("sized_by") or "").strip().lower()
        notional = f.number("notional", what, src, prefix + "notional", positive=True, amount=True)
        dv01 = f.number("dv01", "DV01", src, prefix + "dv01", positive=True, amount=True)
        dccy = f.choice("dv01_ccy", ("USD", "TRY"), "DV01 dövizi", src, prefix + "dv01_ccy", default="USD")
        if typed not in ("dv01", "notional"):
            typed = "dv01" if dv01 is not None and notional is None else "notional"
        out: Dict[str, Any] = {"notional": notional, "notional_ccy": ccy, "sized_by": typed}
        if typed == "dv01":
            if dv01 is None:
                f.fail(prefix + "dv01", "DV01 gerekli")
            out.update(dv01=dv01, dv01_ccy=dccy or "USD")
        elif notional is None:
            f.fail(prefix + "notional", "%s gerekli (ya da DV01)" % what)
        return out

    def normalize(self, raw: Dict[str, Any], lang: str = "tr", sizing: bool = True) -> Tuple[Dict[str, Any], _Form]:
        """A trade as the form sends it -> its fields as kept (dates ISO, numbers as numbers), and the form's errors
        and echoes.  ``sizing``: a nominal not given is worked out from its DV01 (the valuation's market)."""
        f = _Form(raw, lang, self._today(), self._holidays)
        product = f.choice("product", tv.PRODUCTS, "Ürün")
        t: Dict[str, Any] = {"product": product}
        if product is None:
            return t, f
        pair = None
        if product in ("fxspot", "fxopt"):
            pair = pair_of(f.raw.get("pair"))
            if pair is None:
                f.fail("pair", "parite gerekli (örn. USDTRY)" if f._blank(f.raw.get("pair")) else "parite anlaşılamadı: %s" % f.raw.get("pair"))
            t["pair"] = pair
        cal = self._calendar(product, pair)
        today = self._today()
        td, _ = f.date("trade_date", "İşlem tarihi", today, cal, required=True)
        if td is not None and td > today:
            f.fail("trade_date", "işlem tarihi bugünden ileri olamaz")
        t["trade_date"] = _iso(td)
        sd, _ = f.date("settle_date", "Valör", td, cal)
        if product in ("ois", "sofr"):
            self._read_ois(f, t, td, sd, cal, product)
        else:
            if sd is None:
                f.fail("settle_date", "valör gerekli")
            elif td is not None and sd < td:
                f.fail("settle_date", "valör işlem tarihinden önce olamaz")
            t["settle_date"] = t["value_date"] = _iso(sd)
            if product == "dibs":
                self._read_dibs(f, t)
            elif product == "fxspot":
                self._read_fxspot(f, t, pair)
            else:
                self._read_fxopt(f, t, pair, td, cal)
        mp = f.number("manual_price", "Elle fiyat")
        if mp is not None:
            t["manual_price"] = mp
        for key, limit in (("book", BOOK_MAX), ("note", NOTE_MAX)):
            v = f.text(key, limit)
            if v:
                t[key] = v
        if sizing and not f.errors:
            self._size_missing(t, f)
        if not f.errors:
            try:
                t = dict(tv.check(t))
            except ValueError as exc:
                f.fail("_", str(exc))
        return t, f

    def _read_ois(self, f: _Form, t: Dict[str, Any], td: Optional[_dt.date], sd: Optional[_dt.date], cal: Tuple[str, ...],
                  product: str) -> None:
        st = f.choice("structure", tv.STRUCTURES, "Yapı", default="outright")
        t["structure"] = st
        ccy = FIXED_CCY[product]
        start, _ = f.date("value_date", "Başlangıç", sd or td, cal)
        fra = None
        fra_typed = st == "fra" and not f._blank(f.raw.get("fra"))
        if fra_typed:
            m = _FRA.match(str(f.raw.get("fra")))
            if not m or int(m.group(1)) >= int(m.group(2)):
                f.fail("fra", "FRA '3x6' gibi yazılır (başlangıç ay x bitiş ay)")
            elif (sd or td) is None:
                f.fail("fra", "FRA'nın tarihleri valörden sayılır: önce valörü girin")
            else:
                spot = sd or td
                hol = f.holidays(cal)
                start = shortcuts.resolve(("M", int(m.group(1))), spot, f.today, hol)
                fra_end = shortcuts.resolve(("M", int(m.group(2))), spot, f.today, hol)
                fra = (m.group(1) + "x" + m.group(2), fra_end)
                f.echo["fra"] = "%s → %s – %s" % (fra[0], start.strftime("%d.%m.%Y"), fra_end.strftime("%d.%m.%Y"))
        # the settle date of an OIS is its start by default (and the other way round)
        if sd is None and start is not None and st != "fra":
            sd = start
        if start is None and st not in ("mpc",):
            start = sd
        if sd is None:
            f.fail("settle_date", "valör gerekli")
        elif td is not None and sd < td:
            f.fail("settle_date", "valör işlem tarihinden önce olamaz")
        t["settle_date"] = _iso(sd)
        t["value_date"] = _iso(start)
        if st in ("outright", "mpc", "fra"):
            t["side"] = f.choice("side", ("receive", "pay"), "Yön")
            t.update(self._sized(f, f.raw, "", ccy))
            t["price"] = f.number("price", "Oran (%)", required=True, rate=True)
        if st == "outright":
            end, tenor = f.date("end_date", "Vade", start, cal, required=True)
            if end is not None and start is not None and end <= start:
                f.fail("end_date", "vade başlangıçtan sonra olmalı")
            t["end_date"] = _iso(end)
            if tenor:
                t["tenor"] = tenor
        elif st == "mpc":
            mt = f.raw.get("meeting")
            if f._blank(mt):
                f.fail("meeting", "toplantı seçin")
            else:
                day, _ = f.date("meeting", "Toplantı", None, cal)
                t["meeting"] = _iso(day)
            end, _ = f.date("end_date", "Bitiş", start, cal)
            if end is not None:
                t["end_date"] = _iso(end)
        elif st == "fra":
            if fra is not None:
                t["fra"] = fra[0]
                end = fra[1]
            elif fra_typed:
                end = None                                        # (said on the "3x6" itself)
            else:
                end, _ = f.date("end_date", "Bitiş", start, cal, required=True)
                if start is None:
                    f.fail("value_date", "FRA'nın başlangıcı gerekli")
            if end is not None and start is not None and end <= start:
                f.fail("end_date", "bitiş başlangıçtan sonra olmalı")
            t["end_date"] = _iso(end)
        elif st in ("spread", "fly"):
            want = LEGS[st]
            legs = f.raw.get("legs")
            if not isinstance(legs, list) or len(legs) != want:
                f.fail("legs", "%s %d bacaklıdır" % (STRUCTURE_TEXT[st], want))
                legs = (legs if isinstance(legs, list) else [])[:want]
                legs += [{}] * (want - len(legs))
            # the package's side as the form had it (steepener …): what its legs say is what counts
            side = _fold(str(f.raw.get("side") or "").strip())
            out = []
            for i, raw_leg in enumerate(legs):
                src = raw_leg if isinstance(raw_leg, dict) else {}
                p = "legs.%d." % i
                lg: Dict[str, Any] = {"side": f.choice("side", ("receive", "pay"), "Bacağın yönü", src, p + "side")}
                end, tenor = f.date("end_date", "Bacağın vadesi", start, cal, src, p + "end_date", required=True)
                if end is not None and start is not None and end <= start:
                    f.fail(p + "end_date", "vade başlangıçtan sonra olmalı")
                lg["end_date"] = _iso(end)
                if tenor:
                    lg["tenor"] = tenor
                lg.update(self._sized(f, src, p, ccy, "Bacağın nominali"))
                lg["price"] = f.number("price", "Bacağın oranı (%)", src, p + "price", required=True, rate=True)
                out.append(lg)
            # kept short → long; the form's order is remembered for its DV01 boxes (``size``)
            order = sorted(range(len(out)), key=lambda i: out[i].get("end_date") or "9999")
            f.leg_order = order
            out = [out[i] for i in order]
            t["legs"] = out
            if side in PACKAGE_SIDES[st]:
                t["side"] = side
            dv = f.number("dv01", "Paket DV01", amount=True, positive=True)
            if dv is not None:
                t["dv01"] = dv
                t["dv01_ccy"] = f.choice("dv01_ccy", ("USD", "TRY"), "DV01 dövizi", default="USD")
            w = f.raw.get("weights")
            if isinstance(w, list) and len(w) == want and all(_f(x) is not None for x in w):
                t["weights"] = [float(x) for x in w]
            t["notional_ccy"] = ccy
            t["price"] = package_level(out)

    def _read_dibs(self, f: _Form, t: Dict[str, Any]) -> None:
        from . import bonds as bd
        code = "".join(str(f.raw.get("isin") or "").split()).upper()
        if not code:
            f.fail("isin", "ISIN gerekli")
        elif not bd.isin_valid(code):
            f.fail("isin", "ISIN değil ya da kontrol hanesi tutmuyor: %s" % code)
        elif bd.by_isin(code) is None:
            f.fail("isin", "%s masanın kâğıt listesinde yok (Tüm Kâğıtlar)" % code)
        t["isin"] = code
        t["side"] = f.choice("side", ("B", "S"), "Yön")
        t.update(self._sized(f, f.raw, "", "TRY", "Nominal"))
        kind = f.choice("price_kind", ("price", "yield"), "Fiyat tipi", default="price")
        t["price_kind"] = kind
        if kind == "yield":
            t["yield"] = f.number("price", "Getiri (%)", required=True, rate=True)
        else:
            t["price"] = f.number("price", "Temiz fiyat", required=True, positive=True)

    def _read_fxspot(self, f: _Form, t: Dict[str, Any], pair: Optional[str]) -> None:
        t["side"] = f.choice("side", ("B", "S"), "Yön")
        rate = f.number("price", "Kur", required=True, positive=True)
        t["price"] = rate
        typed = "quote" if str(f.raw.get("amount_typed") or "").lower() == "quote" else "base"
        base = (pair or "XXX")[:3]
        quote = (pair or "XXXXXX")[3:]
        t["notional_ccy"] = base
        t["amount_typed"] = typed
        if typed == "quote":
            q = f.number("quote_amount", "Tutar (%s)" % quote, positive=True, amount=True, required=True)
            t["quote_amount"] = q
            t["notional"] = q / rate if q is not None and rate else None
        else:
            t["notional"] = f.number("notional", "Tutar (%s)" % base, positive=True, amount=True, required=True)

    def _read_fxopt(self, f: _Form, t: Dict[str, Any], pair: Optional[str], td: Optional[_dt.date],
                    cal: Tuple[str, ...]) -> None:
        t["call_put"] = f.choice("call_put", ("call", "put"), "Call / put")
        t["side"] = f.choice("side", ("B", "S"), "Yön")
        t["strike"] = f.number("strike", "Strike", required=True, positive=True)
        exp, _ = f.date("expiry", "Vade (expiry)", td, cal, required=True)
        if exp is not None and td is not None and exp < td:
            f.fail("expiry", "vade işlem tarihinden önce olamaz")
        t["expiry"] = _iso(exp)
        dl, _ = f.date("delivery", "Teslim", exp, cal, required=True)
        if dl is not None and exp is not None and dl < exp:
            f.fail("delivery", "teslim vadeden önce olamaz")
        t["delivery"] = _iso(dl)
        base, quote = (pair or "XXXXXX")[:3], (pair or "XXXXXX")[3:]
        t["notional"] = f.number("notional", "Nominal (%s)" % base, positive=True, amount=True, required=True)
        t["notional_ccy"] = base
        t["price"] = f.number("price", "Prim tutarı", positive=True, amount=True, required=True)
        pc = str(f.raw.get("premium_ccy") or quote).strip().upper()
        if not re.match(r"^[A-Z]{3}$", pc):
            f.fail("premium_ccy", "prim dövizi anlaşılamadı: %s" % pc)
        t["premium_ccy"] = pc
        t["premium_date"] = t.get("settle_date")

    # ------------------------------------------------------------------ DV01 → nominal
    @staticmethod
    def _rounded(x: float) -> float:
        """To the nearest 5 mn - a half up (12,5 mn is 15 mn) -, never below 5 mn."""
        return max(ROUND_TO, math.floor(x / ROUND_TO + 0.5) * ROUND_TO)

    @staticmethod
    def _notional_for(inst: Dict[str, Any], dv01: float, ccy: str, mkt: Any) -> float:
        got = tv.notional_for_dv01(inst, dv01, ccy, mkt)
        if isinstance(got, dict):
            got = got.get("notional")
        x = _f(got)
        if x is None or x <= 0:
            raise ValueError("DV01'den nominal bulunamadı")
        return x

    def _units(self, t: Dict[str, Any]) -> List[Tuple[Optional[int], Dict[str, Any], Dict[str, Any]]]:
        """What of a trade is sized by a nominal: ``(leg or None, the instrument as tradevalue takes it, its sizing)``."""
        if t.get("product") not in ("ois", "sofr", "dibs"):
            return []
        if t.get("structure") in ("spread", "fly"):
            out = []
            for i, lg in enumerate(t.get("legs") or []):
                inst = {"product": t["product"], "structure": "outright", "trade_date": t.get("trade_date"),
                        "settle_date": t.get("settle_date"), "value_date": t.get("value_date"), "end_date": lg.get("end_date"),
                        "tenor": lg.get("tenor"), "side": lg.get("side"), "price": lg.get("price"),
                        "notional_ccy": t.get("notional_ccy")}
                out.append((i, inst, lg))
            return out
        return [(None, {k: v for k, v in t.items() if k not in ("legs",)}, t)]

    def _form_market(self) -> Any:
        hit = self._form_mkt
        if hit is not None and time.monotonic() - hit[0] < FORM_MARKET_SECONDS:
            return hit[1]
        mkt = self._engine(tv.market, self.svc)
        self._form_mkt = (time.monotonic(), mkt)
        return mkt

    def _size_missing(self, t: Dict[str, Any], f: _Form) -> None:
        """The nominals of a trade sized by DV01 that the form did not work out (a script, an old page): from the
        valuation, rounded as the form rounds them."""
        need = [(i, inst, s) for i, inst, s in self._units(t) if s.get("sized_by") == "dv01" and s.get("notional") is None
                and s.get("dv01") is not None]
        if not need:
            return
        try:
            mkt = self._form_market()
        except Exception as exc:  # noqa: BLE001
            f.fail("dv01", "DV01'den nominal bulunamadı: %s" % (str(exc)[:200] or type(exc).__name__))
            return
        for i, inst, s in need:
            try:
                s["notional"] = self._rounded(self._notional_for(inst, s["dv01"], s.get("dv01_ccy") or "USD", mkt))
            except Exception as exc:  # noqa: BLE001
                f.fail(("legs.%d." % i if i is not None else "") + "notional",
                       "DV01'den nominal bulunamadı: %s" % (str(exc)[:200] or type(exc).__name__))

    def size(self, user: Optional[str], raw: Dict[str, Any], lang: str = "tr") -> Dict[str, Any]:
        """The form's DV01 boxes: per unit (the trade, or each leg) its nominal from the DV01 typed - by the valuation,
        rounded to the nearest 5 mn, never below - and the DV01 that nominal gives; or, a nominal typed, its DV01 (to
        be read only).  ``raw``: the form; ``raw["size"]`` the units asked for, ``[{"leg": i | null, "dv01" | "notional",
        "dv01_ccy"}]``."""
        self._user(user)
        raw = raw if isinstance(raw, dict) else {}
        t, f = self.normalize(raw, lang, sizing=False)
        units = {i: (inst, s) for i, inst, s in self._units(t)}
        asked = raw.get("size") if isinstance(raw.get("size"), list) else []
        mkt = self._form_market() if asked else None
        out = []
        for a in asked[:5]:
            if not isinstance(a, dict):
                continue
            leg = a.get("leg")
            leg = int(leg) if isinstance(leg, (int, float)) and not isinstance(leg, bool) else None
            # (``leg``: the form's row; the legs are kept short → long)
            at = f.leg_order.index(leg) if leg is not None and f.leg_order and leg in f.leg_order else leg
            hit = units.get(at)
            ccy = "TRY" if str(a.get("dv01_ccy") or "").upper() in ("TRY", "TL") else "USD"
            row: Dict[str, Any] = {"leg": leg, "dv01_ccy": ccy, "notional": None, "dv01": None, "why": None}
            if hit is None:
                row["why"] = "ürün DV01 ile girilmez"
                out.append(row)
                continue
            inst = hit[0]
            g = _Form(a, lang, self._today(), self._holidays)
            dv01 = g.number("dv01", "DV01", positive=True, amount=True)
            notional = g.number("notional", "Nominal", positive=True, amount=True)
            try:
                per = PROBE_DV01 / self._notional_for(inst, PROBE_DV01, ccy, mkt)
                if dv01 is not None:
                    n = self._rounded(self._notional_for(inst, dv01, ccy, mkt))
                    row.update(notional=n, dv01=n * per, sized_by="dv01")
                elif notional is not None:
                    row.update(notional=notional, dv01=notional * per, sized_by="notional")
                else:
                    row["why"] = "DV01 ya da nominal girin"
            except Exception as exc:  # noqa: BLE001
                row["why"] = str(exc)[:200] or "DV01 hesaplanamadı"
            if g.errors:
                row["why"] = next(iter(g.errors.values()))
            out.append(row)
        return {"units": out, "errors": f.errors}

    # ------------------------------------------------------------------ the form's defaults
    def meetings(self, product: str) -> List[str]:
        """The meetings ahead by date (TCMB for TRY OIS, the Fed for SOFR) - the calendar's dates, never its rows."""
        from . import meetings as mt
        cal = mt.TCMB if product == "ois" else mt.FED
        book = getattr(self.svc, "books", {}).get(cal.book)
        if book is None:
            return []
        try:
            dates = self._engine(mt.slot_dates, book, cal)
        except Exception:  # noqa: BLE001
            return []
        today = self._today().isoformat()
        return sorted({d for d in dates if d and d >= today})

    def defaults(self, user: Optional[str], product: Any, pair: Any = None, trade_date: Any = None,
                 expiry: Any = None) -> Dict[str, Any]:
        """The fields of a new trade that have a default, from the valuation (tradevalue.defaults: the desk's
        conventions in one place): the trade date, the settle and start dates, the currencies, an option's delivery
        (its expiry's spot: the pair's spot lag from the expiry), the meetings of an MPC trade and the legs' weights."""
        self._user(user)
        product = str(product or "").strip().lower()
        if product not in tv.PRODUCTS:
            raise ServiceError("ürün bilinmiyor: %s" % product)
        code = pair_of(pair) if pair else None
        td = str(trade_date).strip() if trade_date and _ISO.match(str(trade_date).strip()) else None
        try:
            got = self._engine(tv.defaults, product, code, td, self.svc)
        except Exception:  # noqa: BLE001 - the form opens without them
            got = {}
        out: Dict[str, Any] = dict(got) if isinstance(got, dict) else {}
        if product == "fxopt" and code and expiry and _ISO.match(str(expiry).strip()):
            try:
                spot = self._engine(tv.defaults, "fxspot", code, str(expiry).strip(), self.svc)
                day = (spot or {}).get("settle_date") or (spot or {}).get("value_date")
                if day:
                    out["delivery"] = day
            except Exception:  # noqa: BLE001
                pass
        if product in FIXED_CCY:
            out.setdefault("notional_ccy", FIXED_CCY[product])
        if code:
            out.setdefault("notional_ccy", code[:3])
        if product in ("ois", "sofr"):
            out.setdefault("weights", {k: list(v) for k, v in WEIGHTS.items()})
            if not out.get("meetings"):
                word = "PPK" if product == "ois" else "FOMC"
                out["meetings"] = [{"meeting": d, "label": "%s %s" % (word, _day_text(d))} for d in self.meetings(product)]
        return out

    # ------------------------------------------------------------------ the lists
    def _item(self, r: Dict[str, Any], user: str, admin: bool, names: Dict[str, str]) -> Dict[str, Any]:
        fields = {k: v for k, v in r.items() if k not in ("closing",)}
        word = "PPK" if r.get("product") == "ois" else "FOMC"
        out = {"id": r["id"], "scope": r["scope"], "owner": r["owner"], "owner_name": names.get(r["owner"], r["owner"]),
               "created_by": r["created_by"], "created_by_name": names.get(r["created_by"], r["created_by"]),
               "created_at": r["created_at"], "updated_by": r.get("updated_by"),
               "updated_by_name": names.get(r.get("updated_by") or "", r.get("updated_by")), "updated_at": r.get("updated_at"),
               "product": r["product"], "product_text": PRODUCT_TEXT.get(r["product"], r["product"]),
               "structure": r.get("structure"), "text": describe(r, word), "trade_date": r["trade_date"],
               "settle_date": r.get("settle_date"), "price": r.get("price"), "price_text": price_text(r),
               "status": r["status"], "close_date": r.get("close_date"), "close_price": r.get("close_price"),
               "close_price_text": price_text(r, r.get("close_price")) if r.get("close_price") is not None else None,
               "legs": [{"text": leg_text(lg, r)} for lg in r.get("legs") or []],
               "can_edit": r["scope"] == "personal" or r["created_by"] == user or admin, "fields": fields}
        if r.get("product") == "fxopt":
            out["greeks_wanted"] = True
        return out

    def listing(self, user: Optional[str], scope: Any = "desk") -> Dict[str, Any]:
        """A tab of the page: the desk's trades or the user's own, open and closed - and the last "MTM yenile" of that
        tab (nothing is valued here)."""
        user = self._user(user)
        scope = self._scope(scope)
        rows = self.store.tb_list(scope, None if scope == "desk" else user)
        names = self._names()
        admin = self._admin(user)
        items = [self._item(r, user, admin, names) for r in rows]
        closed_rows = [r for r in rows if r["status"] == "closed"]
        realized = self._results(closed_rows, {}, self.now(), only_closed=True) if closed_rows else {}
        for it in items:
            if it["status"] == "closed":
                it["realized"] = realized.get(it["id"])
        with self._lock:
            mtm = self._mtm.get((scope, "" if scope == "desk" else user))
            mtm = dict(mtm) if mtm else None
        if mtm:
            mtm["by_name"] = names.get(mtm.get("by") or "", mtm.get("by"))
        return {"scope": scope, "today": self._today().isoformat(), "me": user, "admin": admin, "close": self.close_info(),
                "open": [it for it in items if it["status"] != "closed"], "closed": [it for it in items if it["status"] == "closed"],
                "mtm": mtm, "products": PRODUCT_TEXT, "structures": STRUCTURE_TEXT}

    def _close_days(self) -> Tuple[Dict[str, _dt.datetime], Optional[str], Optional[str]]:
        """The closes taken: day -> its close moment; the last one; the last one of the week before."""
        today = self._today()
        days = self.store.tb_close_days(400)
        at = {}
        for d in days:
            try:
                at[d["day"]] = _dt.datetime.strptime(d["at"], "%Y-%m-%d %H:%M")
            except ValueError:
                at[d["day"]] = _dt.datetime.combine(_dt.date.fromisoformat(d["day"]), self.close_time())
        mon = monday_of(today).isoformat()
        last = next((d["day"] for d in days if d["day"] <= today.isoformat()), None)
        week = next((d["day"] for d in days if d["day"] < mon), None)
        return at, last, week

    def _closed_at(self, r: Dict[str, Any]) -> _dt.datetime:
        """When a closed trade left the book: its close day's close - or, closed on that day before it, when it was
        closed."""
        day = _dt.date.fromisoformat(r["close_date"])
        at = _dt.datetime.combine(day, self.close_time())
        when = (r.get("closing") or {}).get("closed_at")
        if when:
            try:
                return min(at, _dt.datetime.strptime(when, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pass
        return at

    def _results(self, rows: Sequence[Dict[str, Any]], vals: Dict[int, Dict[str, Any]], now: _dt.datetime,
                 only_closed: bool = False) -> Dict[int, Dict[str, Any]]:
        """Each trade's valuation (now, or a closed one's realised) with its P&L periods."""
        if not rows:
            return {}
        at, last, week = self._close_days()
        snaps = self.store.tb_closes([r["id"] for r in rows])
        today = self._today()
        ctime = self.close_time()
        out = {}
        for r in rows:
            closed = r["status"] == "closed"
            if only_closed and not closed:
                continue
            if closed:
                v = r.get("closing") or {"ok": False, "why": "kapanış değeri henüz hesaplanmadı (MTM yenile)"}
                end_t = self._closed_at(r)
            else:
                v = vals.get(r["id"]) or {"ok": False, "why": "değer yok"}
                end_t = now
            mine = sorted(((d, at[d], s) for d, s in (snaps.get(r["id"]) or {}).items() if d in at), key=lambda x: x[0])
            if closed:
                mine = [x for x in mine if x[0] < r["close_date"]]
            inc_t = _dt.datetime.combine(_dt.date.fromisoformat(r["trade_date"]), ctime)
            res = dict(self._keep(v))
            res["periods"] = pnl_periods(r, v, end_t, mine, inc_t, today, last, week)
            out[r["id"]] = res
        return out

    def mtm(self, user: Optional[str], scope: Any = "desk") -> Dict[str, Any]:
        """"MTM yenile": every trade of the tab valued now (the valuation's market once, on the calculation thread - it
        reads what the engine has; nothing is asked of Bloomberg), with its daily / weekly / total P&L; the closed
        trades without a realised value get theirs.  Kept as the tab's last refresh."""
        user = self._user(user)
        scope = self._scope(scope)
        rows = self.store.tb_list(scope, None if scope == "desk" else user)
        open_rows = [r for r in rows if r["status"] != "closed"]
        closed_rows = [r for r in rows if r["status"] == "closed"]
        todo = [r for r in closed_rows if not (r.get("closing") or {}).get("ok")]

        def run() -> Tuple[Dict[int, Dict[str, Any]], Dict[int, Dict[str, Any]]]:
            mkt = tv.market(self.svc)
            now_vals = {r["id"]: self._value(self.for_value(r), mkt) for r in open_rows}
            closings = {r["id"]: self._value(self.for_value(r), mkt, r["close_date"]) for r in todo}
            return now_vals, closings

        now_vals, closings = self._engine(run) if (open_rows or todo) else ({}, {})
        for r in todo:
            c = dict(self._keep(closings[r["id"]]), closed_at=(r.get("closing") or {}).get("closed_at"),
                     valued_at=self.now().strftime("%Y-%m-%d %H:%M:%S"))
            r["closing"] = c
            payload = {k: v for k, v in r.items() if k not in self.store.TB_COLS}
            self.store.tb_set_payload(r["id"], payload)
        now = self.now()
        open_res = self._results(open_rows, now_vals, now)
        closed_res = self._results(closed_rows, {}, now, only_closed=True)
        at, last, week = self._close_days()
        out = {"scope": scope, "at": now.strftime("%Y-%m-%d %H:%M:%S"), "by": user, "stale": False,
               "last_close": last, "week_close": week,
               "values": {str(k): v for k, v in open_res.items()}, "closed": {str(k): v for k, v in closed_res.items()},
               "totals": totals(open_rows, open_res, closed_rows, closed_res)}
        with self._lock:
            self._mtm[(scope, "" if scope == "desk" else user)] = out
        names = self._names()
        return dict(out, by_name=names.get(user, user))

    # ------------------------------------------------------------------ changes
    def check(self, user: Optional[str], raw: Any, lang: str = "tr") -> Dict[str, Any]:
        """The form read as saving would read it - nothing is saved: the trade in the desk's words, the dates its
        shortcuts stand for, or what does not read (field by field)."""
        self._user(user)
        t, f = self.normalize(raw if isinstance(raw, dict) else {}, lang)
        if f.errors:
            # (what did read goes back too: the form's defaults follow a pair, a trade date or an expiry typed)
            return {"ok": False, "fields": f.errors, "echo": f.echo, "trade": t}
        word = "PPK" if t.get("product") == "ois" else "FOMC"
        return {"ok": True, "trade": t, "text": describe(t, word), "price_text": price_text(t),
                "legs": [leg_text(lg, t) for lg in t.get("legs") or []], "echo": f.echo}

    def _read(self, raw: Any, lang: str) -> Dict[str, Any]:
        t, f = self.normalize(raw if isinstance(raw, dict) else {}, lang)
        if f.errors:
            key, why = next(iter(f.errors.items()))
            raise ServiceError(why, 400, {"fields": f.errors})
        return t

    def add(self, user: Optional[str], raw: Any, lang: str = "tr") -> Dict[str, Any]:
        """A new trade: the desk's (``scope`` "desk": everybody sees it) or the user's own ("personal")."""
        user = self._user(user)
        raw = raw if isinstance(raw, dict) else {}
        scope = self._scope(raw.get("scope"))
        t = self._read(raw, lang)
        word = "PPK" if t.get("product") == "ois" else "FOMC"
        payload = {k: v for k, v in t.items() if k not in self.store.TB_COLS}
        tid = self.store.tb_add(scope, user, t["product"], t["trade_date"], payload, user,
                                {"text": describe(t, word), "trade": payload})
        self._changed(scope, user)
        return {"id": tid, "text": describe(t, word), "scope": scope}

    def edit(self, user: Optional[str], tid: Any, raw: Any, lang: str = "tr") -> Dict[str, Any]:
        """An open trade changed (by whoever may change it; its list stays its own)."""
        user = self._user(user)
        row = self._mine(user, tid)
        if row["status"] == "closed":
            raise ServiceError("kapanmış işlem değiştirilmez: önce kapanışını geri alın")
        raw = raw if isinstance(raw, dict) else {}
        if raw.get("scope") not in (None, "", row["scope"]):
            raise ServiceError("işlemin listesi (Masa / Kişisel) sonradan değişmez: silip yeniden girin")
        if raw.get("product") not in (None, "", row["product"]):
            raise ServiceError("işlemin ürünü sonradan değişmez: silip yeniden girin")
        t = self._read(dict(raw, product=row["product"]), lang)
        skip = ("id", "scope", "owner", "status", "created_by", "created_at", "updated_by", "updated_at", "closing")
        before = {k: v for k, v in row.items() if k not in skip}
        changes = [[k, before.get(k), t.get(k)] for k in sorted(set(before) | set(t))
                   if k not in skip and before.get(k) != t.get(k)]
        if not changes:
            return {"id": row["id"], "changed": False}
        word = "PPK" if t.get("product") == "ois" else "FOMC"
        after = {k: v for k, v in t.items() if k not in self.store.TB_COLS}
        self.store.tb_update(row["id"], after, "open", t["trade_date"], user, "edit",
                             {"text": describe(t, word), "changes": changes})
        self._changed(row["scope"], row["owner"])
        return {"id": row["id"], "changed": True, "text": describe(t, word)}

    def close(self, user: Optional[str], tid: Any, close_date: Any, close_price: Any, lang: str = "tr") -> Dict[str, Any]:
        """Close a trade at a price on a day: it goes to the closed list, valued at that price (its realised P&L)."""
        user = self._user(user)
        row = self._mine(user, tid)
        if row["status"] == "closed":
            raise ServiceError("işlem zaten kapanmış")
        f = _Form({"close_date": close_date, "close_price": close_price}, lang, self._today(), self._holidays)
        cal = self._calendar(row["product"], row.get("pair"))
        day, _ = f.date("close_date", "Kapanış tarihi", self._today(), cal, required=True)
        price = f.number("close_price", "Kapanış fiyatı", required=True,
                         rate=row["product"] in ("ois", "sofr") or row.get("price_kind") == "yield")
        if day is not None and day > self._today():
            f.fail("close_date", "kapanış tarihi bugünden ileri olamaz")
        if day is not None and day.isoformat() < row["trade_date"]:
            f.fail("close_date", "kapanış tarihi işlem tarihinden önce olamaz")
        if f.errors:
            raise ServiceError(next(iter(f.errors.values())), 400, {"fields": f.errors})
        payload = {k: v for k, v in row.items() if k not in self.store.TB_COLS}
        payload.update(close_date=day.isoformat(), close_price=price,
                       closing={"ok": False, "why": "kapanış değeri hesaplanıyor",
                                "closed_at": self.now().strftime("%Y-%m-%d %H:%M:%S")})
        text = describe(row)
        self.store.tb_update(row["id"], payload, "closed", row["trade_date"], user, "close",
                             {"text": text, "close_date": day.isoformat(), "close_price": price,
                              "close_price_text": price_text(row, price)})
        closed = dict(row, **payload, status="closed")
        try:
            v = self._engine(lambda: self._value(self.for_value(closed), tv.market(self.svc), day.isoformat()))
        except Exception as exc:  # noqa: BLE001 - the close stands; "MTM yenile" values it again
            v = {"ok": False, "why": "değerleme hatası: %s" % str(exc)[:200]}
        payload["closing"] = dict(self._keep(v), closed_at=payload["closing"]["closed_at"],
                                  valued_at=self.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.store.tb_set_payload(row["id"], payload)
        self._changed(row["scope"], row["owner"])
        return {"id": row["id"], "closing": payload["closing"]}

    def reopen(self, user: Optional[str], tid: Any) -> Dict[str, Any]:
        """A closed trade back among the open ones (its close taken back)."""
        user = self._user(user)
        row = self._mine(user, tid)
        if row["status"] != "closed":
            raise ServiceError("işlem kapanmış değil")
        payload = {k: v for k, v in row.items() if k not in self.store.TB_COLS and k not in ("close_date", "close_price", "closing")}
        self.store.tb_update(row["id"], payload, "open", row["trade_date"], user, "reopen",
                             {"text": describe(row), "close_date": row.get("close_date"), "close_price": row.get("close_price")})
        self._changed(row["scope"], row["owner"])
        return {"id": row["id"]}

    def remove(self, user: Optional[str], tid: Any) -> Dict[str, Any]:
        """Delete a trade (its log stays)."""
        user = self._user(user)
        row = self._mine(user, tid)
        self.store.tb_delete(row["id"], user, {"text": describe(row), "status": row["status"]})
        self._changed(row["scope"], row["owner"])
        return {"deleted": row["id"]}

    # ------------------------------------------------------------------ the log
    ACTIONS = {"create": "girdi", "edit": "değiştirdi", "close": "kapattı", "reopen": "kapanışı geri aldı", "delete": "sildi"}

    def _log_rows(self, rows: List[Dict[str, Any]], names: Dict[str, str]) -> List[Dict[str, Any]]:
        out = []
        for e in rows:
            d = e["detail"] or {}
            out.append({"id": e["id"], "ts": e["ts"], "user": e["user"], "user_name": names.get(e["user"], e["user"]),
                        "trade": e["trade"], "scope": e["scope"], "action": e["action"],
                        "action_text": self.ACTIONS.get(e["action"], e["action"]), "text": d.get("text") or "",
                        "changes": d.get("changes") or [], "close_date": d.get("close_date"),
                        "close_price_text": d.get("close_price_text")})
        return out

    def log(self, user: Optional[str], tid: Any) -> Dict[str, Any]:
        """Who did what to a trade, and when (oldest first)."""
        user = self._user(user)
        row = self._visible(user, tid)
        return {"id": row["id"], "entries": self._log_rows(self.store.tb_log(trade=row["id"]), self._names())}

    def recent(self, user: Optional[str], scope: Any = "desk", limit: int = 200) -> Dict[str, Any]:
        """The latest changes of a tab (newest first): the desk's trades, or the user's own."""
        user = self._user(user)
        scope = self._scope(scope)
        rows = self.store.tb_log(scope=scope, owner=None if scope == "desk" else user, limit=max(1, min(int(limit or 200), 500)))
        return {"scope": scope, "entries": self._log_rows(rows, self._names())}
