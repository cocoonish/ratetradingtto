# STUB - replaced by the trades-deger branch.
"""The valuation of the Trades page's trades (tto/tradebook.py): the interface the core codes against.

This file is a stand-in with the interface only - every trade is "not valued yet".  The real module comes from the
``trades-deger`` branch; the core (tradebook.py), its tests and the page never need more than what is written here.

A trade, as the core hands it over (dates ISO ``YYYY-MM-DD``; numbers as numbers)::

    {"id", "scope": "desk" | "personal", "owner", "product", "trade_date", "settle_date", "value_date", "side",
     "notional", "notional_ccy", "price", "status": "open" | "closed",
     # optional, by product:
     "structure", "end_date", "tenor", "meeting", "fra", "legs", "dv01", "dv01_ccy", "sized_by", "weights",
     "isin", "price_kind", "yield", "pair", "quote_amount", "amount_typed", "call_put", "strike", "expiry",
     "delivery", "premium_ccy", "premium_date", "manual_price", "close_date", "close_price", "note", "book"}

* ``price`` - the trade price: an OIS / SOFR fixed rate in percent (38.5 = %38,50; an MPC period's rate, a FRA's rate
  too); a spread / fly its package level in bp (worked out from its legs' rates); DİBS the clean price per 100 (or,
  ``price_kind`` "yield", absent with ``yield`` in percent); FX spot the rate; an FX option the premium amount in
  ``premium_ccy``.
* ``settle_date`` - the settlement (valör).  OIS / SOFR: ``value_date`` is the start (effective) date, ``settle_date``
  defaults to it.  DİBS, FX spot: ``value_date`` = ``settle_date``.  FX option: ``settle_date`` is the premium's
  settlement; ``premium_date`` = ``value_date`` = ``settle_date`` (kept so that either name reads).
* ``structure`` (ois / sofr) - one of :data:`STRUCTURES`: ``outright``; ``mpc`` (``meeting``: the meeting's date, ISO -
  never a row of the calendar; ``value_date`` / ``end_date`` the period when known); ``fra`` (``value_date`` /
  ``end_date``, ``fra`` the "3x6" it was typed as); ``spread`` (2 legs) and ``fly`` (3 legs): ``legs`` =
  ``[{"side", "end_date", "tenor"?, "notional", "dv01"?, "dv01_ccy"?, "sized_by", "price"}]`` (each leg starts at the
  trade's ``value_date``; ``price`` its fixed rate in percent), ``side`` the package's ("steepener" / "flattener",
  "rec_body" / "pay_body").
* ``sized_by`` - "dv01" when a DV01 was typed (``dv01``, per bp in ``dv01_ccy``: "USD" or "TRY") and the nominal was
  worked out from it, "notional" when the nominal was typed.
* ``side`` - OIS / SOFR "receive" / "pay" (the fixed rate); DİBS, FX spot, FX option "B" / "S" (the bond, the pair's
  first currency, the option).
* ``status`` "closed": ``close_date`` and ``close_price`` (the price it was closed at, in ``price``'s unit).

What :func:`value` returns, and how the core reads it (tradebook.py works out the P&L periods from it):

* ``mtm`` - the trade's value in ``ccy`` now (``asof``): 0 at inception for a trade dealt at the market; for an option
  its value, plus when bought and minus when sold (the core takes the premium as the option's inception value).
  ``mtm_try`` / ``mtm_usd`` the same in TL and USD.
* ``carry_1d`` (and ``_try`` / ``_usd``) - what one **calendar** day earns at today's market (the core multiplies it by
  the days between two closes; a weekend is three).
* ``accrued`` - the cash the trade has paid or received since it started (coupons, fixings), in ``ccy``; ``None`` is 0.
  The core adds its change to the change of ``mtm``; the option premium is not in it.
* a closed trade (``status`` "closed", ``close_date``, ``close_price``; the core also passes ``manual_price`` =
  ``close_price`` and ``asof`` = ``close_date``): its value when it was closed at ``close_price`` - its realised value.
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
#: a nominal worked out from a DV01 is rounded to this (5 mn of its currency) - and is never less
ROUND_TO = 5e6


def check(trade: Dict[str, Any]) -> Dict[str, Any]:
    """The trade with its fields normalised (a tenor's end date, a yield's price …); ``ValueError`` with a Turkish
    reason when the valuation cannot take it.  (Stub: as given.)"""
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


def defaults(product: str, pair: Optional[str] = None, trade_date: Optional[str] = None,
             mkt_or_svc: Any = None) -> Dict[str, Any]:
    """Field -> default value of a new trade of ``product`` (by the desk's conventions and holiday lists): the trade
    date (today), the settle and start dates (the product's spot), an option's delivery (expiry + the pair's spot lag),
    the currencies (``notional_ccy``, ``premium_ccy``: the quote currency) - and for OIS / SOFR ``meetings``
    (``[{"meeting": ISO, "start": ISO, "end": ISO, "label": str}]``, the MPC periods to pick) and ``weights``
    (``{"spread": [1, 1], "fly": [0.5, 1, 0.5]}``: the legs' DV01 per unit of the package's).  (Stub: today.)"""
    return {"trade_date": _dt.date.today().isoformat()}


def notional_for_dv01(trade: Dict[str, Any], dv01: float, dv01_ccy: str = "USD", mkt: Any = None) -> float:
    """The nominal (in the trade's / leg's ``notional_ccy``) whose DV01 is ``dv01`` per bp in ``dv01_ccy``, rounded to
    the nearest 5 mn (never below 5 mn).  ``trade``: the instrument (a leg as a trade of its own).  (Stub: DV01 ×
    10.000, rounded the same way.)"""
    return max(ROUND_TO, math.floor(float(dv01) * 1e4 / ROUND_TO + 0.5) * ROUND_TO)
