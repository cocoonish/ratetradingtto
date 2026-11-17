# STUB - replaced by the trades-deger branch.
"""The valuation of the Trades page's trades (tto/tradebook.py): the interface the core codes against.

This file is a stand-in with the interface only - every trade is "not valued yet".  The real module comes from the
``trades-deger`` branch; the core (tradebook.py), its tests and the page never need more than what is written here.

A trade, as the core hands it over (dates ISO ``YYYY-MM-DD``; numbers as numbers)::

    {"id", "scope": "desk" | "personal", "owner", "product", "trade_date", "settle_date", "value_date", "side",
     "notional", "notional_ccy", "price", "status": "open" | "closed",
     # optional, by product:
     "structure", "end_date", "tenor", "mpc_date", "mpc_end", "fra", "legs", "dv01", "dv01_ccy", "sized_by",
     "weights", "isin", "price_kind", "yield", "pair", "quote_amount", "amount_typed", "call_put", "strike",
     "expiry", "delivery", "premium_ccy", "premium_date", "manual_price", "close_date", "close_price", "note", "book"}

* ``price`` - the trade price: an OIS / SOFR fixed rate in percent (38.5 = %38,50; an MPC period's rate, a FRA's rate
  too); a spread / fly its package level in bp from its legs' rates (long − short; the fly's body − ½ each wing); DİBS
  the clean price per 100 (or, ``price_kind`` "yield", absent with ``yield`` in percent); FX spot the rate; an FX
  option the premium amount in ``premium_ccy``.
* ``settle_date`` - the settlement (valör).  OIS / SOFR: ``value_date`` is the start (effective) date, ``settle_date``
  defaults to it.  DİBS, FX spot: ``value_date`` = ``settle_date``.  FX option: ``settle_date`` is the premium's
  settlement; ``premium_date`` = ``value_date`` = ``settle_date``.
* ``side`` - OIS / SOFR "receive" / "pay" as the form sends it; :func:`check` keeps it as the blotter's code ("S"
  receives the fixed rate, "B" pays it) - the core reads either.  DİBS, FX: "B" / "S" (buy / sell the bond, the pair's
  first currency, the option).  A spread's / fly's own side is its long leg's / body's (it gains when the level rises
  when that leg is paid).
* ``structure`` (ois / sofr) - one of :data:`STRUCTURES`: ``outright`` (``end_date``, or ``tenor`` - its end date by the
  product's convention); ``mpc`` (``mpc_date``: the meeting's date - never a row of the calendar; ``mpc_end`` the
  next one's; ``value_date`` / ``end_date`` the period when known); ``fra`` (``fra`` "3x6", or ``value_date`` /
  ``end_date``); ``spread`` (2 legs) and ``fly`` (3 legs), short → long: ``legs`` = ``[{"side", "end_date" | "tenor",
  "notional", "dv01"?, "dv01_ccy"?, "sized_by", "price"}]`` (each starts at the trade's ``value_date``; ``price`` its
  fixed rate in percent).
* ``sized_by`` - "dv01" when a DV01 was typed (``dv01``, per bp in ``dv01_ccy``: "USD" or "TRY") and the nominal was
  worked out from it, "notional" when the nominal was typed.
* ``status`` "closed": ``close_date`` and ``close_price`` (in ``price``'s unit); the core passes ``manual_price`` =
  ``close_price`` and ``asof`` = ``close_date`` too: its value is its realised value.

What :func:`value` returns, and how the core reads it (tradebook.py works out the P&L periods from it):

* ``mtm`` - what the trade is worth now (``asof``) against what it cost: 0 at inception for a trade dealt at the
  market; an option's value net of the premium paid or received.  ``mtm_try`` / ``mtm_usd`` the same in TL and USD.
* ``carry_1d`` (and ``_try`` / ``_usd``) - what one day passing earns with the market unchanged, to the next business
  day: ``inputs["carry_days"]`` calendar days (3 over a weekend); the core spreads it over those days.
* ``accrued`` - the cash the trade has paid or received since it started (a swap's settled periods, a bond's
  coupons), in ``ccy``; ``None`` is 0.  A period's P&L is the change of ``mtm`` + ``accrued``.
* ``legs`` (spread, fly, FRA): ``[{"label", "mtm", "mtm_try", "mtm_usd", "carry_1d", "carry_1d_try", "carry_1d_usd",
  "price_now", "price_text"}]``; a FRA is valued as one instrument and its legs are the attribution (the core shows
  what they leave over).
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, Optional

PRODUCTS = ("ois", "sofr", "dibs", "fxspot", "fxopt")
#: the shapes of an OIS / SOFR trade
STRUCTURES = ("outright", "mpc", "spread", "fly", "fra")
#: a nominal worked out from a DV01 is rounded to the desk's lot (5 mn of its currency) - and is never less
ROUND_TO = 5e6


def check(trade: Dict[str, Any], mkt: Any = None, strict: bool = True) -> Dict[str, Any]:
    """The trade with its fields normalised (a tenor's end date, a yield's price, the side's code …); ``ValueError``
    with a Turkish reason when the valuation cannot take it.  ``mkt``: a market, a service or nothing; ``strict``
    False: a stored trade being valued (its dates need not be business days).  (Stub: as given.)"""
    return dict(trade)


def market(svc: Any) -> Any:
    """One snapshot of what the valuation needs, from the shared (desk) view - on the calculation thread.  Nothing is
    asked of Bloomberg: the valuation reads what the engine already has.  (Stub: nothing.)"""
    return None


def value(trade: Dict[str, Any], mkt: Any, asof: Optional[str] = None) -> Dict[str, Any]:
    """The trade's value (see the module's text)::

        {"ok": bool, "why": str|None, "ccy": str, "mtm": float, "mtm_try": float, "mtm_usd": float,
         "carry_1d": float, "carry_1d_try": float, "carry_1d_usd": float, "accrued": float|None,
         "price_now": float|None, "price_text": str, "greeks": dict|None, "inputs": dict, "legs": [...]?}
    """
    return {"ok": False, "why": "değerleme henüz yok"}


def defaults(product: str, pair: Optional[str] = None, trade_date: Optional[str] = None, mkt_or_svc: Any = None,
             **given: Any) -> Dict[str, Any]:
    """Field -> default value of a new trade of ``product`` (by the desk's conventions and holiday lists): the trade
    date (today), the settle and start dates (the product's spot), the currencies (``notional_ccy``, ``premium_ccy``:
    the quote currency), an option's delivery (``expiry`` + the pair's spot lag), an FRA's dates (``fra`` "3x6") - and
    for OIS / SOFR ``mpc_periods`` (``[{"mpc_date", "mpc_end", "value_date", "end_date", "label"}]``, the meeting
    periods to pick) and ``weights`` (the legs' DV01 per unit of the package's: spread 1:1, fly 50/50).  ``given``: what
    the form knows already (``isin``, ``expiry``, ``tenor``, ``fra``, ``structure``).  (Stub: today.)"""
    return {"trade_date": _dt.date.today().isoformat()}


def notional_for_dv01(trade_or_leg: Dict[str, Any], dv01: Any, dv01_ccy: Any = "USD", mkt: Any = None) -> Dict[str, Any]:
    """The nominal (in the trade's / leg's ``notional_ccy``) whose DV01 is ``dv01`` per bp in ``dv01_ccy``:
    ``{"notional": on the desk's lot (the nearest 5 mn, never below one), "raw": before rounding, "dv01_check": the
    DV01 the rounded nominal gives, "ccy", "lot"}``.  ``trade_or_leg``: the instrument (a leg as a trade of its own).
    (Stub: DV01 × 10.000, rounded the same way.)"""
    raw = float(dv01) * 1e4
    n = max(ROUND_TO, math.floor(raw / ROUND_TO + 0.5) * ROUND_TO)
    return {"notional": n, "raw": raw, "dv01_check": n / 1e4, "ccy": (trade_or_leg or {}).get("notional_ccy") or "TRY",
            "lot": ROUND_TO}
