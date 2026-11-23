"""Günlük İşlemler (daily blotter): pricing helpers for trade entry and the position / cost summary.

Everything that is a market calculation is read from the workbook itself (the Forward sheet's own cells
with the value date typed into ``Forward!D2`` / the bulk-pricing row, the OIS annuities of ``Motor``), so
the numbers are the ones Excel shows.  What is new here is only bookkeeping: turning a spread / fly / FRA
into its legs and the cost ("maliyet") of the net position.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import ppkcurve as pk
from .xl.engine import Calc
from .xl.errors import XlError
from .xl.model import COLS, parse_a1
from .xl.values import date_to_serial, serial_to_date

SHEET = "Günlük İşlemler"
FWD_ROWS = (3, 200)        # A:D
OIS_ROWS = (3, 250)        # H:M  (the tenor summary reads to row 200, the counterparty pivot to row 250)
BOND_ROWS = (3, 250)       # Y:AA
OIS_TENORS = ["ON", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "15M", "18M", "21M", "2Y", "3Y", "4Y", "5Y",
              "6Y", "7Y", "8Y", "9Y", "10Y"]
TENOR_MONTHS = {"1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12, "15M": 15, "18M": 18, "21M": 21, "2Y": 24,
                "3Y": 36, "4Y": 48, "5Y": 60, "6Y": 72, "7Y": 84, "8Y": 96, "9Y": 108, "10Y": 120}
# OIS_MAIN outright table: tenor label -> row (A9:A26); Motor row = 316 + that row
OIS_ROW = {"1M": 9, "2M": 10, "3M": 11, "6M": 12, "9M": 13, "1Y": 14, "15M": 15, "18M": 16, "21M": 17, "2Y": 18,
           "3Y": 19, "4Y": 20, "5Y": 21, "6Y": 22, "7Y": 23, "8Y": 24, "9Y": 25, "10Y": 26}
FWD_BASES = ("RET_BID", "RET_MID", "RET_ASK", "TRY", "FWD", "SP")
#: the desk's OIS buckets in months - the sheet's counterparty × tenor table (Günlük İşlemler Q89:Q107: ON, 1W, 2W and
#: these; its summary P25:P38 stops at 5Y).  OIS_MAIN reads the tenors between them (15M, 21M, 27M …) between two quotes
#: and nothing trades there: a leg there (a 12x15 FRA's end, a 15M outright) is split between the two buckets around
#: it, linearly in months (15M: half 1Y, half 18M; 21M: half 18M, half 2Y; 27M: ¾ 2Y, ¼ 3Y …) - its nominal and DV01, at
#: its own rate - in the sheet, in the cost table by tenor and in OIS · PPK's FRA lists.  The trade keeps its own tenor.
BUCKET_MONTHS = (1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120)
MPC_ROWS = (84, 99)        # OIS_MAIN 'MPC OIS': A period, B start, C end, D market (bootstrap)


class TradeError(ValueError):
    pass


def _num(v: Any, what: str) -> float:
    if type(v) is float and v == v:
        return v
    raise TradeError("%s hesaplanamadı (%r)" % (what, v.code if type(v) is XlError else v))


def month_label(m: int) -> str:
    if m >= 12 and m % 12 == 0:
        return "%dY" % (m // 12)
    return "%dM" % m


def bucket_split(m: int) -> List[Tuple[int, float]]:
    """The desk's buckets of a leg ``m`` months out (months) and each one's share: the bucket itself when it is one, else
    the two around it, linearly in months (15 → 12 and 18 half each; 27 → 24 ¾, 36 ¼: :data:`BUCKET_MONTHS`); the end
    ones beyond them."""
    if m <= BUCKET_MONTHS[0] or m >= BUCKET_MONTHS[-1] or m in BUCKET_MONTHS:
        return [(min(max(m, BUCKET_MONTHS[0]), BUCKET_MONTHS[-1]), 1.0)]
    hi = next(b for b in BUCKET_MONTHS if b > m)
    lo = max(b for b in BUCKET_MONTHS if b < m)
    w = (m - lo) / float(hi - lo)
    return [(lo, 1.0 - w), (hi, w)]


def buckets(tenor: str) -> List[Tuple[str, float]]:
    """An OIS leg's tenor in the desk's buckets, with each one's share: the tenor itself when it is one (ON / 1W / 2W
    too), else the two around it (15M: [("1Y", 0.5), ("18M", 0.5)] - :func:`bucket_split`)."""
    m = _months_of(tenor)
    if m is None or m in BUCKET_MONTHS:
        return [(tenor, 1.0)]
    return [(month_label(b), w) for b, w in bucket_split(m)]


#: an OIS leg that ends on a date of its own (a broken date): named by that date, as the lists and the form show it
_DATE_TENOR = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$")


def date_tenor(serial: float) -> str:
    """A broken-date leg's name: its end day, dd.mm.yyyy."""
    return serial_to_date(serial).strftime("%d.%m.%Y")


def tenor_date_of(tenor: Any) -> Optional[float]:
    """The end (serial) of a leg named by its date ("04.11.2027": :func:`date_tenor`); ``None`` for a tenor of the lists."""
    m = _DATE_TENOR.match(str(tenor or "").strip())
    if not m:
        return None
    try:
        return float(date_to_serial(_dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------- FX forward
def pair_of(text: Any) -> str:
    """The currency pair of a forward as typed: "EURTRY", "eur/try"; a currency alone ("gbp") is against TRY."""
    s = "".join(ch for ch in str(text or "") if ch.isalpha()).upper()
    if not s:
        return "USDTRY"
    if len(s) == 3 and s != "TRY":
        return s + "TRY"
    if len(s) == 6 and s[:3] != s[3:]:
        return s
    raise TradeError("parite anlaşılamadı: %r (örn. EURTRY, GBP)" % (text,))


def price_forward(book, base_overlay: Dict[Tuple[int, int], Any], value_date: float, basis: str,
                  manual: Optional[float] = None, pair: str = "USDTRY", spot: Optional[float] = None,
                  spot_date: Optional[float] = None) -> Dict[str, Any]:
    """Price a forward for ``value_date`` exactly as the Forward sheet does.

    ``pair``   USDTRY and EURTRY are priced with the sheet's own tables (the value date typed into
               ``Forward!D2``); any other pair has no curve in the workbook: its forward is what is typed.
    ``basis``  RET_BID / RET_MID / RET_ASK -> the 'RET' row of the outright table (Forward!D33:F33, D45:F45)
               TRY  -> ``manual`` is a TRY simple ACT/360 rate (fraction); bulk-pricing formula (Forward!N)
               FWD  -> ``manual`` is the forward outright; the implied TRY rate is backed out
               SP   -> ``manual`` is the swap point (forward − spot, ×10.000): forward = spot + points
    ``spot``   the spot to use for a pair the workbook has none for
    ``spot_date``  the spot date (serial) of such a pair when it has one of its own (EURUSD: two business days of
               USD and EUR): its days count from it - from the USDTRY spot date of the sheet otherwise
    """
    if basis not in FWD_BASES:
        raise TradeError("bilinmeyen fiyatlama tipi: %r" % basis)
    pair = pair_of(pair)
    base_ccy, quote_ccy = pair[:3], pair[3:]
    eng = book.engine
    cell = book.cell
    overlay = dict(base_overlay)
    overlay[cell("Forward!D2")] = float(value_date)
    if pair == "USDTRY":
        overlay[cell("Forward!B163")] = float(value_date)
        overlay[cell("Forward!L163")] = (manual * 100.0) if (basis == "TRY" and manual is not None) else None
    elif pair != "EURTRY" and quote_ccy == "TRY":
        overlay[cell("Forward!C197")] = base_ccy             # the sheet's cross block: spot = USDTRY ÷ USDXXX
        overlay[cell("Forward!B200")] = float(value_date)
    calc = Calc(eng, eng.shared, overlay)

    def v(ref: str) -> Any:
        si, rc = cell(ref)
        r, c = divmod(rc, COLS)
        return calc.get(si, r, c)

    def need_manual(what: str) -> float:
        if manual is None or (basis == "FWD" and manual <= 0):
            raise TradeError("%s girilmedi" % what)
        return float(manual)

    usdtry = v("Forward!F2")
    ret_bid, ret_ask = v("Forward!W48"), v("Forward!X48")
    df_try = v("Forward!O37")                                # 'Forward DV01' block: TRY OIS discount factor to the value date
    out: Dict[str, Any] = {"pair": pair, "base": base_ccy, "quote": quote_ccy, "value_date": float(value_date), "basis": basis,
                           "usdtry": usdtry if type(usdtry) is float else None,
                           "ret_bid": ret_bid, "ret_ask": ret_ask,
                           "ret_mid": (ret_bid + ret_ask) / 2.0 if type(ret_bid) is float and type(ret_ask) is float else None}
    rate: Optional[float] = None
    foreign: Any = None
    df_foreign: Any = None
    if pair in ("USDTRY", "EURTRY"):
        usd = pair == "USDTRY"
        # days from the pair's own spot value date; the currency's OIS curve at the value date (bid / mid / ask)
        days = _num(v("Forward!U27" if usd else "Forward!AA27"), "gün sayısı")
        if days <= 0:
            raise TradeError("valör spot tarihinden sonra olmalı")
        spot_px = _num(v("Forward!F2" if usd else "Forward!G2"), "spot")
        f_bid, f_mid, f_ask = (v("Forward!W27"), v("Forward!X27"), v("Forward!Y27")) if usd else \
            (v("Forward!AC27"), v("Forward!AD27"), v("Forward!AE27"))
        first = 30 if usd else 42
        table = {}
        for k, name in enumerate(("ICAP", "OIS", "VIOP", "RET")):
            table[name] = {"bid": v("Forward!D%d" % (first + k)), "mid": v("Forward!E%d" % (first + k)), "ask": v("Forward!F%d" % (first + k))}
        out["table"] = {k: {s: (x if type(x) is float else None) for s, x in d.items()} for k, d in table.items()}
        out.update({"usd_bid": f_bid, "usd_mid": f_mid, "usd_ask": f_ask})
        if basis == "RET_BID":
            fwd = _num(table["RET"]["bid"], "RET bid forward")
            rate = _num(ret_bid, "RET bid")
            foreign = f_ask
        elif basis == "RET_ASK":
            fwd = _num(table["RET"]["ask"], "RET ask forward")
            rate = _num(ret_ask, "RET ask")
            foreign = f_bid
        elif basis == "RET_MID":
            fwd = _num(table["RET"]["mid"], "RET mid forward")
            foreign = f_mid
            rate = (_num(ret_bid, "RET bid") + _num(ret_ask, "RET ask")) / 2.0      # the sheet's 'RET MID'
        else:
            # the currency's mid rate, as the bulk row (Forward!J163) and the cross block (Forward!Q200) use it
            foreign = _num(v("Forward!J163"), "USD faiz") / 100.0 if usd else _num(f_mid, "EUR faiz")
            if basis == "TRY":
                rate = need_manual("TRY faizi")
                fwd = _num(v("Forward!N163"), "forward") if usd else \
                    spot_px * (1.0 + rate * days / 360.0) / (1.0 + foreign * days / 360.0)
            else:
                fwd = need_manual("forward kur") if basis == "FWD" else spot_px + need_manual("swap puanı") / 10000.0
                if fwd <= 0:
                    raise TradeError("forward kur pozitif olmalı")
                rate = ((fwd / spot_px) * (1.0 + foreign * days / 360.0) - 1.0) * 360.0 / days
        df_foreign = v("Forward!O42") if usd else (1.0 / (1.0 + foreign * days / 360.0) if type(foreign) is float else None)
    else:
        # a pair without a curve in the workbook: the forward is the one typed, as an outright or as points on a spot
        if basis not in ("FWD", "SP"):
            raise TradeError("%s için fiyat elle girilir: forward kur ya da swap puanı" % pair)
        days = float(value_date) - spot_date if type(spot_date) is float else _num(v("Forward!U27"), "gün sayısı")
        if days <= 0:
            raise TradeError("valör spot tarihinden sonra olmalı")
        cross_bid, cross_ask = (v("Forward!L198"), v("Forward!M198")) if quote_ccy == "TRY" else (None, None)
        market = (cross_bid + cross_ask) / 2.0 if type(cross_bid) is float and type(cross_ask) is float else None
        out["spot_market"] = market
        spot_px = float(spot) if type(spot) is float and spot > 0 else market
        if basis == "FWD":
            fwd = need_manual("forward kur")
        else:
            if spot_px is None:
                raise TradeError("%s spotu yok: swap puanıyla girmek için spot da yazın" % pair)
            fwd = spot_px + need_manual("swap puanı") / 10000.0
        if fwd <= 0:
            raise TradeError("forward kur pozitif olmalı")
        m_bid, m_ask = (v("Forward!M200"), v("Forward!N200")) if quote_ccy == "TRY" else (None, None)
        out["table"] = {"BBG": {"bid": m_bid if type(m_bid) is float else None, "ask": m_ask if type(m_ask) is float else None,
                                "mid": (m_bid + m_ask) / 2.0 if type(m_bid) is float and type(m_ask) is float else None}}
        out.update({"usd_bid": None, "usd_mid": None, "usd_ask": None})
    points = (fwd - spot_px) * 10000.0 if spot_px is not None else None      # an outright typed for a pair without a spot
    out.update({
        "days": days, "spot": spot_px, "forward": fwd, "try_rate": rate, "usd_rate": foreign if type(foreign) is float else None,
        "points": points, "daily_points": points / days if points is not None else None,
        "on_equiv": 360.0 * ((1.0 + rate * days / 360.0) ** (1.0 / days) - 1.0) if rate is not None and rate > -1 else None,
        "df_try": df_try if type(df_try) is float and quote_ccy == "TRY" else None,
        "df_usd": df_foreign if type(df_foreign) is float else None,
    })
    # per 1 mn bought, so that the form can show the risk before an amount is typed
    out["dv01_1m"] = forward_dv01("B", 1e6, fwd, days, out["usdtry"], out["df_try"], out["df_usd"],
                                  rate if quote_ccy == "TRY" else None, out["usd_rate"])
    return out


def forward_dv01(direction: str, amount: float, forward: float, days: float, spot: Optional[float],
                 df_try: Optional[float] = None, df_usd: Optional[float] = None, try_rate: Optional[float] = None,
                 usd_rate: Optional[float] = None) -> Dict[str, Optional[float]]:
    """DV01 of an FX forward as the Forward sheet's 'Forward DV01' block has it (Forward!N31:P49).

    ``tl``   TL for +1 bp on the TRY rate  = ±amount·forward·T·DF_TRY/10000   (+ for a purchase of the currency:
             the buyer of the forward pays the TRY rate - payer is plus)
    ``usd``  the same in USD at the USDTRY ``spot``                            (the sheet's TRY_USD_DV01)
    ``usd_leg``  in the currency bought, for +1 bp on its own rate = ∓amount·T·DF/10000

    T = days/360.  Without the sheet's discount factors (a trade stored before they were kept) the trade's
    own simple rates stand in for them; a pair that is not against TRY has no TRY risk.
    """
    try:
        t = float(days) / 360.0
        sign = 1.0 if direction == "B" else -1.0
        if type(df_try) is not float and type(try_rate) is float:
            df_try = 1.0 / (1.0 + try_rate * t)
        if type(df_usd) is not float and type(usd_rate) is float:
            df_usd = 1.0 / (1.0 + usd_rate * t)
        tl = sign * float(amount) * float(forward) * t * df_try / 10000.0 if type(df_try) is float else None
        usd_leg = -sign * float(amount) * t * df_usd / 10000.0 if type(df_usd) is float else None
    except (TypeError, ValueError, ZeroDivisionError):
        return {"tl": None, "usd": None, "usd_leg": None}
    usd = tl / spot if tl is not None and type(spot) is float and spot > 0 else None
    return {"tl": tl, "usd": usd, "usd_leg": usd_leg}


#: currencies without a minor unit (ISO 4217): an amount worked out in one of them is a whole number
WHOLE_UNITS = ("JPY", "KRW", "CLP", "ISK", "VND")


def ccy_round(x: float, ccy: str) -> float:
    """An amount worked out in ``ccy`` to the unit it settles in: cents (whole yen) - half away from zero."""
    k = 1.0 if ccy in WHOLE_UNITS else 100.0
    return _round_half_away(x * k) / k


def typed_amount(payload: Dict[str, Any]) -> Optional[Tuple[str, float]]:
    """The amount a forward was entered with: ``("base", x)`` in the pair's first currency (USD of USDTRY - the
    blotter's amount), ``("quote", x)`` in its second (TRY of USDTRY, USD of EURUSD: a minor-currency entry); ``None``
    when neither is there.  Both at once, or one that is not above zero: :class:`TradeError`."""
    base, quote = payload.get("amount"), payload.get("quote_amount")
    if type(base) is float and type(quote) is float:
        raise TradeError("tutar ya dövizde ya karşı parada yazılır: ikisinden birini boş bırakın")
    if type(quote) is float:
        if not quote > 0:
            raise TradeError("karşı tutar pozitif bir sayı olmalı")
        return "quote", quote
    if type(base) is float:
        if not base > 0:
            raise TradeError("tutar pozitif bir sayı olmalı")
        return "base", base
    return None


def forward_amounts(typed: Tuple[str, float], forward: float, base_ccy: str) -> Tuple[float, float]:
    """(amount in the pair's first currency, amount in its second) of a forward entered with ``typed``
    (:func:`typed_amount`) at the all-in ``forward``: the side typed is kept as it is; the other follows from the rate -
    a first-currency amount worked out is rounded to its currency's unit (:func:`ccy_round`)."""
    side, x = typed
    if side == "quote":
        return ccy_round(x / forward, base_ccy), x
    return x, x * forward


def forward_trade(book, overlay, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + price a forward trade as typed in the entry form; returns the record to store.

    The amount is typed in either currency of the pair: ``amount`` in the first (the blotter's own), ``quote_amount``
    in the second - the record is a trade of the first currency all the same (``amount``; ``tl`` is the second
    currency's amount), with the side typed and its amount beside it (``typed``, ``typed_amount``)."""
    direction = str(payload.get("dir", "")).upper()
    if direction not in ("B", "S"):
        raise TradeError("yön B (alış) ya da S (satış) olmalı")
    typed = typed_amount(payload)
    if typed is None:
        raise TradeError("tutar pozitif bir sayı olmalı")
    vd = payload.get("value_date")
    if type(vd) is not float:
        raise TradeError("valör tarihi gerekli")
    basis = str(payload.get("basis", "RET_MID")).upper()
    manual = payload.get("manual")
    spot = payload.get("spot")
    own = payload.get("spot_date")
    p = price_forward(book, overlay, vd, basis, manual if type(manual) is float else None, payload.get("pair") or "USDTRY",
                      spot if type(spot) is float else None, own if type(own) is float else None)
    amount, counter = forward_amounts(typed, p["forward"], p["base"])
    if not amount > 0:
        raise TradeError("karşı tutar %s tutarına çevrilemeyecek kadar küçük" % p["base"])
    rec = {
        "pair": p["pair"], "dir": direction, "amount": amount, "value_date": vd, "basis": basis,
        "manual": manual if type(manual) is float else None,
        "days": p["days"], "spot": p["spot"], "usd_rate": p["usd_rate"], "try_rate": p["try_rate"],
        "forward": p["forward"], "points": p["points"], "tl": counter,
        "df_try": p.get("df_try"), "df_usd": p.get("df_usd"), "usdtry": p.get("usdtry"),
        "cpt": str(payload.get("cpt") or "").strip()[:40], "note": str(payload.get("note") or "").strip()[:200],
        "typed": typed[0], "typed_amount": typed[1],
    }
    risk = forward_dv01(direction, amount, p["forward"], p["days"], p.get("usdtry"), p.get("df_try"), p.get("df_usd"),
                        p["try_rate"] if p["quote"] == "TRY" else None, p["usd_rate"])
    rec.update({"dv01_tl": risk["tl"], "dv01": risk["usd"], "usd_dv01": risk["usd_leg"]})
    return rec


def entered_as(t: Dict[str, Any]) -> Tuple[str, Optional[float], str]:
    """How a stored forward was entered: (side, amount typed, its currency) - a trade of an earlier version was typed
    in the pair's first currency."""
    pair = str(t.get("pair") or "USDTRY").upper()
    if t.get("typed") == "quote" and type(t.get("typed_amount")) is float:
        return "quote", t["typed_amount"], pair[3:]
    amount = t.get("amount")
    return "base", amount if type(amount) is float else None, pair[:3]


# ---------------------------------------------------------------------------------------------- OIS
class OisMarket(object):
    """Par rates and annuities of the TRY OIS curve, read from OIS_MAIN / Motor through the engine."""

    def __init__(self, book, calc, overlay: Optional[Dict[Tuple[int, int], Any]] = None,
                 curves: Optional[Callable[[], Optional[Dict[str, Any]]]] = None):
        self.book = book
        self.calc = calc
        self.overlay = dict(overlay or {})      # the user's own inputs, for what is priced with a date typed in
        self._fn_cache: Dict[str, Any] = {}
        self._mpc: Optional[Dict[str, Any]] = None
        self._curves_of = curves                # the TRY curves both ways as the service keeps them (none: read here)
        self._curves: Optional[Dict[str, Any]] = None
        self._pricing: Any = None               # Fiyatlama's market (tto/pricing.py): the OIS spot, the TRY holidays
        self._broken: Dict[float, Dict[str, float]] = {}

    def value(self, ref: str) -> Any:
        si, rc = self.book.cell(ref)
        r, c = divmod(rc, COLS)
        return self.calc.get(si, r, c)

    def formula(self, text: str) -> Any:
        """Evaluate an ad-hoc Excel formula against the workbook."""
        from .render import calc_value
        from .xl.tokenizer import to_template
        fn = self._fn_cache.get(text)
        if fn is None:
            fn = self.book.engine.compiler.compile_expression(to_template(text, 1, 1), False)
            self._fn_cache[text] = fn
        return calc_value(self.calc, fn, 0, 1, 1)

    @property
    def usdtry(self) -> float:
        return _num(self.value("OIS_MAIN!D2"), "USDTRY")

    @property
    def lot(self) -> float:
        v = self.value("OIS_MAIN!H2")
        return v if type(v) is float and v > 0 else 1.0

    @property
    def default_dv01(self) -> float:
        v = self.value("OIS_MAIN!F2")
        return v if type(v) is float and v > 0 else 1000.0

    def pricing_market(self) -> Any:
        """Fiyatlama's market (:func:`tto.pricing.read`) out of this calculation: the OIS spot, Motor's TRY holidays."""
        if self._pricing is None:
            from . import pricing as pr          # (pricing imports this module)
            idx = self.book.model.sheet_index
            try:
                self._pricing = pr.read(lambda sheet, r, c: self.calc.get(idx[sheet], r, c))
            except pr.PricingError as exc:
                raise TradeError(str(exc))
        return self._pricing

    def broken(self, end: float) -> Dict[str, float]:
        """A TRY OIS from the OIS spot to a date of its own - a broken date - priced as Fiyatlama prices one (the existing
        broken-date handling, :func:`tto.pricing.swap_deal`): one payment up to 3M, else quarterly coupons counted back
        from the maturity, the short period first (MASA!BL193: ``WORKDAY(EDATE(end, −3k) − 1, 1, TRY)``; the desk,
        19.11.2026), ACT/365, on the true Bootstrap (Motor's ``BOOT_GUN`` / ``BOOT_LNDF``, the desk's records' curve).
        ``{"start", "end"}`` (the end rolled to a business day), ``"par"``, ``"annuity"`` (Σ τ·DF per unit nominal, as
        Motor's column I) and ``"df"`` at the end."""
        key = float(end)
        got = self._broken.get(key)
        if got is None:
            from . import pricing as pr
            boot = (self.curves() or {}).get("boot")
            if boot is None:
                raise TradeError("kırık vade fiyatlanamadı: Bootstrap eğrisi yok")
            try:
                deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("d", key), self.pricing_market())
            except pr.PricingError as exc:
                raise TradeError("kırık vade %s: %s" % (date_tenor(key), exc))
            got = {"start": deal.start, "end": deal.end, "par": pr.mid(deal, boot), "annuity": pr.annuity(deal, boot),
                   "df": boot.df(deal.end - deal.spot)}
            self._broken[key] = got
        return got

    def par(self, tenor: str) -> Optional[float]:
        end = tenor_date_of(tenor)
        if end is not None:                     # a broken date (dd.mm.yyyy)
            try:
                return self.broken(end)["par"]
            except TradeError:
                return None
        row = OIS_ROW.get(tenor)
        if row is not None:
            v = self.value("OIS_MAIN!B%d" % row)
            return v if type(v) is float else None
        if tenor == "1W":
            v = self.value("OIS_MAIN!AU13")
            return v if type(v) is float else None
        if tenor == "2W":
            v = self.value("OIS_MAIN!AU14")
            return v if type(v) is float else None
        if tenor == "ON":
            v = self.value("OIS_MAIN!J2")
            return v if type(v) is float else None
        return None

    def annuity(self, tenor: str) -> float:
        """PV of 1 bp-year of fixed leg per unit nominal (Motor!I for quoted tenors; a broken date: :meth:`broken`)."""
        end = tenor_date_of(tenor)
        if end is not None:
            return self.broken(end)["annuity"]
        row = OIS_ROW.get(tenor)
        if row is not None:
            return _num(self.value("Motor!I%d" % (316 + row)), "annuity " + tenor)
        days = {"ON": 1.0, "1W": 7.0, "2W": 14.0}.get(tenor)
        if days is None:
            raise TradeError("bilinmeyen vade: %r" % tenor)
        r = self.par(tenor) or 0.0
        return (days / 365.0) / (1.0 + r * days / 365.0)

    def annuity_months(self, months: int) -> float:
        """Annuity of the spot swap to ``months`` on Motor's quarterly grid (OIS_MAIN columns O / P)."""
        if months <= 0:
            return 0.0
        return _num(self.formula("SUMPRODUCT((Motor!$A$139:$A$178*3<=%d)*Motor!$D$139:$D$178*Motor!$O$139:$O$178)"
                                 % months), "annuity %dM" % months)

    def df_months(self, months: int) -> float:
        if months <= 0:
            return 1.0
        return _num(self.formula("INDEX(Motor!$O$139:$O$178,%d)" % (months // 3)), "DF %dM" % months)

    def fra_months(self, start: int, end: int) -> Optional[float]:
        """The curve's forward par rate between two month counts on Motor's quarterly grid (multiples of 3,
        0 ≤ start < end ≤ 120): (R_end·A_end − R_start·A_start)/(A_end − A_start); ``None`` off the grid."""
        if start < 0 or end <= start or start % 3 or end % 3 or end > 120:
            return None
        a2 = self.annuity_months(end)
        end_par = (1.0 - self.df_months(end)) / a2
        if start == 0:
            return end_par
        a1 = self.annuity_months(start)
        start_par = (1.0 - self.df_months(start)) / a1
        return (end_par * a2 - start_par * a1) / (a2 - a1)

    def curves(self) -> Optional[Dict[str, Any]]:
        """The TRY curves both ways (:func:`tto.ppkcurve.read`): the service's kept ones, or read here once."""
        if self._curves is None:
            if self._curves_of is not None:
                self._curves = self._curves_of() or {}
            else:
                idx = self.book.model.sheet_index
                self._curves = pk.read(lambda sheet, r, c: self.calc.get(idx[sheet], r, c)) if "Motor" in idx else {}
        return self._curves or None

    def fra_ppk(self, start: int, end: int) -> Optional[float]:
        """:meth:`fra_months` on the PPK step curve (TLREF flat between PPK meetings, on every OIS quote): the same
        quarterly calendar and day count, another curve.  ``None`` without one, or off the grid."""
        cv = self.curves() or {}
        if cv.get("ppk") is None or cv.get("grid") is None:
            return None
        return pk.fra(cv["ppk"], cv["grid"], start, end)

    def mpc_dates(self) -> Dict[str, Any]:
        """The OIS spot date and the effective dates of the coming meetings (the day after each decision), as the
        'MPC OIS' table of OIS_MAIN has them: its period k runs from date k to date k+1."""
        spot = self.value("OIS_MAIN!B2")
        dates: List[float] = []
        market: List[Optional[float]] = []
        for r in range(MPC_ROWS[0], MPC_ROWS[1] + 1):
            start, end = self.value("OIS_MAIN!B%d" % r), self.value("OIS_MAIN!C%d" % r)
            if type(start) is not float or type(end) is not float:
                break
            if not dates:
                dates.append(start)
            dates.append(end)
            level = self.value("OIS_MAIN!D%d" % r)
            market.append(level if type(level) is float else None)
        return {"spot": spot if type(spot) is float else None, "dates": dates, "market": market}

    def mpc_table(self) -> Dict[str, Any]:
        """The 'MPC OIS' table of OIS_MAIN as days and discount factors: the OIS spot (B2) and, for every meeting it
        covers, its decision day (the workbook's list, P10…) and effective day (B / C), with the bootstrap ln
        discount factor of each day (BK / BL; 0 at the spot).  ``{"spot", "meetings": [(decision, effective)],
        "lndf": {day: ln DF}}`` (Excel serials).  Read once per market object: what :meth:`mpc_span` prices with."""
        if self._mpc is not None:
            return self._mpc
        spot = self.value("OIS_MAIN!B2")
        out: Dict[str, Any] = {"spot": spot if type(spot) is float else None, "meetings": [], "lndf": {}}
        if out["spot"] is not None:
            out["lndf"][spot] = 0.0
        for k, r in enumerate(range(MPC_ROWS[0], MPC_ROWS[1] + 1)):
            start, end = self.value("OIS_MAIN!B%d" % r), self.value("OIS_MAIN!C%d" % r)
            a, b = self.value("OIS_MAIN!BK%d" % r), self.value("OIS_MAIN!BL%d" % r)
            if not all(type(x) is float for x in (start, end, a, b)):
                break
            if k == 0:
                first = self.value("OIS_MAIN!P%d" % (10 + k))
                out["meetings"].append((first if type(first) is float else start - 1.0, start))
                out["lndf"][start] = a
            decision = self.value("OIS_MAIN!P%d" % (11 + k))
            out["meetings"].append((decision if type(decision) is float else end - 1.0, end))
            out["lndf"][end] = b
        self._mpc = out
        return out

    def mpc_span(self, start: float, end: float) -> Optional[float]:
        """The bootstrap rate (simple ACT/365) of a swap between two days of the 'MPC OIS' table - the OIS spot or a
        meeting's effective day: (DF(start) / DF(end) − 1) · 365 / days, with the table's own discount factors (what
        :meth:`between` gives for those days, without a calculation of its own).  ``None`` for any other day."""
        lndf = self.mpc_table()["lndf"]
        if start not in lndf or end not in lndf or end <= start:
            return None
        return (math.exp(lndf[start] - lndf[end]) - 1.0) * 365.0 / (end - start)

    def between(self, start: float, end: float) -> Dict[str, Any]:
        """A swap from one date to another, paid once at the end - how a meeting-dated OIS trades.  The numbers
        are those of OIS_MAIN's 'İKİ TARİH ARASI SIMPLE RATE' block with the two dates typed into it: the
        market level is its bootstrap row (simple ACT/365), the annuity the year fraction times the discount
        factor of the MPC-implied curve (what the sheet's own 'Nominal' column of the MPC table uses)."""
        spot = self.value("OIS_MAIN!B2")
        if type(spot) is float and start < spot:
            raise TradeError("başlangıç OIS spot tarihinden önce olamaz")
        if end <= start:
            raise TradeError("bitiş başlangıçtan sonra olmalı")
        cell = self.book.cell
        overlay = dict(self.overlay)
        overlay[cell("OIS_MAIN!B122")] = float(start)
        overlay[cell("OIS_MAIN!B123")] = float(end)
        eng = self.book.engine
        calc = Calc(eng, eng.shared, overlay)

        def v(ref: str) -> Any:
            si, rc = cell(ref)
            return calc.get(si, *divmod(rc, COLS))

        days = float(end) - float(start)
        df_end = _num(v("OIS_MAIN!E125"), "iskonto faktörü")
        implied = v("OIS_MAIN!B125")
        return {"start": float(start), "end": float(end), "days": days, "market": _num(v("OIS_MAIN!B129"), "piyasa seviyesi"),
                "implied": implied if type(implied) is float else None, "df_end": df_end,
                "annuity": days / 365.0 * df_end}

    def nominal(self, dv01_usd: float, annuity: float, weight: float = 1.0) -> float:
        """OIS_MAIN sizing rule: ROUND(w*DV01*USDTRY/(A*0.0001)/lot,0)*lot."""
        lot = self.lot
        raw = weight * dv01_usd * self.usdtry / (annuity * 0.0001)
        return _round_half_away(raw / lot) * lot

    def dv01_usd(self, nominal: float, annuity: float) -> float:
        return nominal * annuity * 0.0001 / self.usdtry


def _round_half_away(x: float) -> float:
    f = float("%.15g" % abs(x))
    r = math.floor(f + 0.5)
    return -r if x < 0 else r


def mpc_label(start: float, end: float) -> str:
    """How a meeting-dated swap is named in the lists: by its two dates (the number of a meeting changes when
    one passes; its date does not)."""
    return "MPC %s–%s" % (serial_to_date(start).strftime("%d.%m.%y"), serial_to_date(end).strftime("%d.%m.%y"))


def ois_legs(mkt: OisMarket, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Expand an OIS trade (outright / spread / fly / FRA) into the outright legs booked in the blotter.

    Conventions (same as OIS_MAIN): RECEIVE = receive fixed; spread = long − short in bp, FLATTENER =
    receive the long leg / pay the short leg; fly = 2·body − wings in bp, "REC GÖVDE" = receive the body;
    FRA start→end is traded as the two spot swaps with one nominal sized on the forward annuity; "mpc" is one
    swap between two dates (meeting to meeting, or spot to a meeting), paid once at its end.
    Size is given per leg as DV01 in USD (fly wings carry half) or as TL nominal.
    """
    strategy = str(payload.get("strategy", "outright")).lower()
    side = str(payload.get("side", "")).upper()
    level = payload.get("level")
    dv01 = payload.get("dv01")
    nominal_in = payload.get("nominal")
    cpt = str(payload.get("cpt") or "").strip()[:40]
    if type(level) is not float:
        raise TradeError("seviye (faiz ya da bp) gerekli")
    if type(dv01) is not float or dv01 <= 0:
        if type(nominal_in) is float and nominal_in > 0:
            dv01 = None
        else:
            dv01 = mkt.default_dv01
    legs: List[Dict[str, Any]] = []
    comma = str(payload.get("_lang") or "tr") != "en"

    def fmt(x: float, digits: int) -> str:
        text = "%.*f" % (digits, x)
        return text.replace(".", ",") if comma else text

    def leg(tenor: str, receive: bool, rate: float, weight: float, role: str, annuity: Optional[float] = None,
            nominal: Optional[float] = None):
        a = annuity if annuity is not None else mkt.annuity(tenor)
        if nominal is None:
            if dv01 is not None:
                nominal = mkt.nominal(dv01, a, weight)
            else:
                nominal = float(nominal_in) * weight
        legs.append({"tenor": tenor, "dir": "S" if receive else "B", "rate": rate, "nominal": nominal,
                     "dv01": mkt.dv01_usd(nominal, a), "role": role, "cpt": cpt, "annuity": a})

    def tenor_of(key: str) -> str:
        t = str(payload.get(key) or "").upper().strip()
        if t in OIS_TENORS:
            return t
        end = tenor_date_of(t)
        if end is None:
            raise TradeError("geçersiz vade: %r" % t)
        return date_tenor(mkt.broken(end)["end"])          # a broken date: the business day it ends on

    def before(a: str, b: str) -> bool:
        """Whether leg ``a`` ends before leg ``b`` (a tenor of the lists, or a broken date)."""
        if a in OIS_TENORS and b in OIS_TENORS:
            return OIS_TENORS.index(a) < OIS_TENORS.index(b)
        spot = mkt.value("OIS_MAIN!B2")
        if type(spot) is not float:
            raise TradeError("OIS spot tarihi yok")
        end = lambda t: tenor_date_of(t) if t not in OIS_TENORS else tenor_end(spot, t)      # noqa: E731
        return end(a) < end(b)

    def market(t: str) -> float:
        p = mkt.par(t)
        if p is None:
            raise TradeError("%s için piyasa kotası yok" % t)
        return p

    label = ""
    if strategy == "outright":
        if side not in ("PAY", "RECEIVE"):
            raise TradeError("yön PAY ya da RECEIVE olmalı")
        t = tenor_of("tenor")
        leg(t, side == "RECEIVE", level, 1.0, "outright")
        label = "%s %s @ %s%%" % (side, t, fmt(level * 100.0, 4))
        mid = mkt.par(t)
        info = {"market": mid, "cost_bp": None if mid is None else
                ((mid - level) if side == "RECEIVE" else (level - mid)) * 10000.0}
    elif strategy == "spread":
        if side not in ("FLATTENER", "STEEPENER"):
            raise TradeError("yön FLATTENER ya da STEEPENER olmalı")
        ts, tl = tenor_of("short"), tenor_of("long")
        if not before(ts, tl):
            raise TradeError("kısa vade uzun vadeden önce olmalı")
        rs = payload.get("short_rate")
        rs = rs if type(rs) is float else market(ts)
        rl = rs + level / 10000.0
        flat = side == "FLATTENER"
        leg(ts, not flat, rs, 1.0, "short")
        leg(tl, flat, rl, 1.0, "long")
        label = "%s %s/%s @ %s bp" % (side, ts, tl, fmt(level, 2))
        mkt_level = (market(tl) - market(ts)) * 10000.0
        info = {"market": mkt_level, "cost_bp": (mkt_level - level) if flat else (level - mkt_level)}
    elif strategy == "fly":
        if side not in ("REC GÖVDE", "PAY GÖVDE", "REC GOVDE", "PAY GOVDE"):
            raise TradeError("yön REC GÖVDE ya da PAY GÖVDE olmalı")
        t1, tb, t2 = tenor_of("wing1"), tenor_of("body"), tenor_of("wing2")
        if not (before(t1, tb) and before(tb, t2)):
            raise TradeError("vadeler kanat < gövde < kanat sırasında olmalı")
        r1 = payload.get("wing1_rate")
        r1 = r1 if type(r1) is float else market(t1)
        r2 = payload.get("wing2_rate")
        r2 = r2 if type(r2) is float else market(t2)
        rb = (level / 10000.0 + r1 + r2) / 2.0
        rec_body = side.startswith("REC")
        leg(t1, not rec_body, r1, 0.5, "wing1")
        leg(tb, rec_body, rb, 1.0, "body")
        leg(t2, not rec_body, r2, 0.5, "wing2")
        label = "%s %s/%s/%s @ %s bp" % ("REC GÖVDE" if rec_body else "PAY GÖVDE", t1, tb, t2, fmt(level, 2))
        mkt_level = (2.0 * market(tb) - market(t1) - market(t2)) * 10000.0
        info = {"market": mkt_level, "cost_bp": (mkt_level - level) if rec_body else (level - mkt_level)}
    elif strategy == "fra" and (type(payload.get("start_date")) is float or type(payload.get("end_date")) is float):
        # a FRA between two dates of its own (a day gone by's FRA reversed: its own start and end) - the two spot swaps
        # to its dates as broken dates (:meth:`OisMarket.broken`), one nominal on the forward annuity; from the spot
        # (start Spot) the swap to its end alone
        if side not in ("PAY", "RECEIVE"):
            raise TradeError("yön PAY ya da RECEIVE olmalı")
        d1, d2 = payload.get("start_date"), payload.get("end_date")
        if type(d2) is not float:
            raise TradeError("FRA'nın bitiş tarihi gerekli")
        if type(d1) is not float and payload.get("start_months") not in (None, 0.0):
            raise TradeError("FRA'nın iki ucu da ay ya da ikisi de tarih olmalı (başlangıç Spot olabilir)")
        e = mkt.broken(d2)
        s = mkt.broken(d1) if type(d1) is float else None
        if s is not None and s["end"] >= e["end"]:
            raise TradeError("FRA'nın bitişi başlangıcından sonra olmalı")
        a1, a2 = (s["annuity"] if s else 0.0), e["annuity"]
        fwd_annuity = a2 - a1
        if fwd_annuity <= 0:
            raise TradeError("forward annuity hesaplanamadı")
        nominal = mkt.nominal(dv01, fwd_annuity, 1.0) if dv01 is not None else float(nominal_in)
        rec = side == "RECEIVE"
        n2 = date_tenor(e["end"])
        if s is None:
            n1 = "Spot"
            leg(n2, rec, level, 1.0, "end", annuity=a2, nominal=nominal)
            mkt_level = e["par"]
        else:
            n1 = date_tenor(s["end"])
            q = payload.get("start_rate")
            q = q if type(q) is float else s["par"]
            leg(n1, not rec, q, 1.0, "start", annuity=a1, nominal=nominal)
            leg(n2, rec, (level * fwd_annuity + q * a1) / a2, 1.0, "end", annuity=a2, nominal=nominal)
            mkt_level = (e["par"] * a2 - s["par"] * a1) / fwd_annuity
        label = "%s FRA %s→%s @ %s%%" % (side, n1, n2, fmt(level * 100.0, 4))
        info = {"market": mkt_level, "cost_bp": ((mkt_level - level) if rec else (level - mkt_level)) * 10000.0}
    elif strategy == "fra":
        if side not in ("PAY", "RECEIVE"):
            raise TradeError("yön PAY ya da RECEIVE olmalı")
        m1, m2 = payload.get("start_months"), payload.get("end_months")
        if type(m1) is not float or type(m2) is not float:
            raise TradeError("başlangıç ve bitiş (ay) gerekli")
        m1, m2 = int(m1), int(m2)
        if m1 < 0 or m2 <= m1 or m1 % 3 or m2 % 3 or m2 > 120:
            raise TradeError("FRA ayları 3'ün katı olmalı (0 ≤ başlangıç < bitiş ≤ 120)")
        a1, a2 = mkt.annuity_months(m1), mkt.annuity_months(m2)
        fwd_annuity = a2 - a1
        if fwd_annuity <= 0:
            raise TradeError("forward annuity hesaplanamadı")
        if dv01 is not None:
            nominal = mkt.nominal(dv01, fwd_annuity, 1.0)
        else:
            nominal = float(nominal_in)
        end_par = (1.0 - mkt.df_months(m2)) / a2
        rec = side == "RECEIVE"
        if m1 == 0:
            leg(month_label(m2), rec, level, 1.0, "end", annuity=a2, nominal=nominal)
            mkt_level = end_par
        else:
            start_par = (1.0 - mkt.df_months(m1)) / a1
            q = payload.get("start_rate")
            q = q if type(q) is float else start_par
            # achieved FRA = (R·A2 − Q·A1)/(A2 − A1)  =>  R = (FRA·(A2 − A1) + Q·A1)/A2
            r_end = (level * fwd_annuity + q * a1) / a2
            leg(month_label(m1), not rec, q, 1.0, "start", annuity=a1, nominal=nominal)
            leg(month_label(m2), rec, r_end, 1.0, "end", annuity=a2, nominal=nominal)
            mkt_level = (end_par * a2 - start_par * a1) / fwd_annuity
        label = "%s FRA %s→%s @ %s%%" % (side, "Spot" if m1 == 0 else month_label(m1), month_label(m2), fmt(level * 100.0, 4))
        info = {"market": mkt_level, "cost_bp": ((mkt_level - level) if rec else (level - mkt_level)) * 10000.0}
        # the second view: the mid on the PPK step curve and the cost against it (same sign as cost_bp: + paid away)
        ppk = mkt.fra_ppk(m1, m2)
        if ppk is not None:
            info["market_ppk"] = ppk
            info["cost_bp_ppk"] = ((ppk - level) if rec else (level - ppk)) * 10000.0
    elif strategy == "mpc":
        if side not in ("PAY", "RECEIVE"):
            raise TradeError("yön PAY ya da RECEIVE olmalı")
        d1, d2 = payload.get("start"), payload.get("end")
        if type(d1) is not float or type(d2) is not float:
            raise TradeError("başlangıç ve bitiş tarihi gerekli")
        span = mkt.between(d1, d2)
        name = mpc_label(d1, d2)
        leg(name, side == "RECEIVE", level, 1.0, "mpc", annuity=span["annuity"])
        legs[-1]["mpc"] = {"start": d1, "end": d2, "days": span["days"]}
        label = "%s %s @ %s%%" % (side, name, fmt(level * 100.0, 4))
        info = {"market": span["market"], "implied": span["implied"],
                "cost_bp": ((span["market"] - level) if side == "RECEIVE" else (level - span["market"])) * 10000.0}
    else:
        raise TradeError("bilinmeyen strateji: %r" % strategy)
    # cost versus market mid in money terms: the bp given away on the leg that carries the price
    if strategy == "fra":
        risk_dv01 = abs(legs[-1]["dv01"] - (legs[0]["dv01"] if len(legs) > 1 else 0.0))
    elif strategy == "fly":
        risk_dv01 = legs[1]["dv01"] / 2.0          # the body rate moves by half the fly level
    else:
        risk_dv01 = legs[-1]["dv01"]
    cost_bp = info.get("cost_bp")
    info["cost_usd"] = None if cost_bp is None else cost_bp * risk_dv01
    info["cost_tl"] = None if cost_bp is None else cost_bp * risk_dv01 * mkt.usdtry
    # + = pays fixed (gains when rates rise), as the blotter sheet's "Net" column: pay − receive
    net = sum(lg["dv01"] if lg["dir"] == "B" else -lg["dv01"] for lg in legs)
    return {"strategy": strategy, "side": side, "level": level, "label": label, "legs": legs, "info": info,
            "usdtry": mkt.usdtry, "dv01": {"net": net, "gross": sum(lg["dv01"] for lg in legs)}}


# ---------------------------------------------------------------------------------------------- bonds
BOND_SHEET = "DİBS RV"
BOND_ROWS_RV = (5, 54)
_BOND_COLUMNS = {"isin": "ISIN", "name": "Ad", "maturity": "Vade", "clean": "Kullanılan temiz", "mod_dur": "Mod. süre",
                 "dv01_mn": "DV01 TL / 1mn", "yield": "BIST bileşik getiri", "rv": "Pahalı/ucuz (bp"}


def bond_info(book, calc, instrument: str) -> Optional[Dict[str, Any]]:
    """What the DİBS RV table knows about a bond typed into the blotter (by ISIN): name, maturity, the clean
    price in use, modified duration and DV01 in TL per 1 mn nominal.  ``None`` when the bond is not listed."""
    key = "".join(str(instrument or "").upper().split())
    if not key or BOND_SHEET not in book.model.sheet_index:
        return None
    si = book.model.sheet_index[BOND_SHEET]
    sh = book.model.sheets[si]
    cols: Dict[str, int] = {}
    for c in range(1, sh.max_col + 1):
        text = sh.consts.get(4 * COLS + c)
        if isinstance(text, str):
            for name, label in _BOND_COLUMNS.items():
                if name not in cols and text.strip().startswith(label):
                    cols[name] = c
    if "isin" not in cols or "dv01_mn" not in cols:
        return None
    for r in range(BOND_ROWS_RV[0], BOND_ROWS_RV[1] + 1):
        isin = calc.get(si, r, cols["isin"])
        if not isinstance(isin, str) or not isin.strip():
            continue
        code = "".join(isin.upper().split())
        if code == key or (len(key) >= 6 and (key in code or code in key)):
            out: Dict[str, Any] = {"isin": isin.strip(), "row": r}
            for name in ("name", "maturity", "clean", "mod_dur", "dv01_mn", "yield", "rv"):
                v = calc.get(si, r, cols[name]) if name in cols else None
                out[name] = v if type(v) in (float, str) else None
            return out
    return None


def bond_dv01(amount: float, info: Optional[Dict[str, Any]], usdtry: Optional[float]) -> Dict[str, Optional[float]]:
    """DV01 of a bond trade for +1 bp of yield: a purchase loses, so it is negative (TL, and USD at spot)."""
    per_mn = info.get("dv01_mn") if info else None
    if type(per_mn) is not float:
        return {"tl": None, "usd": None}
    tl = -float(amount) / 1e6 * per_mn
    return {"tl": tl, "usd": tl / usdtry if type(usdtry) is float and usdtry > 0 else None}


# ---------------------------------------------------------------------------------------------- risk of the day
def risk_summary(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """DV01 of the listed trades in USD for +1 bp on TRY rates.  Payer is plus, everywhere: a currency bought
    forward and fixed paid are positive, a currency sold forward, fixed received and bonds bought are negative.
    Trades without a DV01 (a bond the DİBS table does not list, a forward that is not against TRY) are counted
    in ``unknown``."""
    out: Dict[str, Any] = {"fwd": 0.0, "fwd_tl": 0.0, "ois": 0.0, "ois_gross": 0.0, "bond": 0.0, "bond_tl": 0.0, "unknown": 0}
    for t in trades:
        k = t.get("kind")
        if k == "fwd":
            if type(t.get("dv01")) is float:
                out["fwd"] += t["dv01"]
                out["fwd_tl"] += t.get("dv01_tl") or 0.0
            else:
                out["unknown"] += 1
        elif k == "ois":
            d = t.get("dv01")
            if type(d) is float:
                out["ois"] += d if t.get("dir") == "B" else -d
                out["ois_gross"] += d
        elif k == "bond":
            if type(t.get("dv01")) is float:
                out["bond"] += t["dv01"]
                out["bond_tl"] += t.get("dv01_tl") or 0.0
            else:
                out["unknown"] += 1
    out["total"] = out["fwd"] + out["ois"] + out["bond"]
    return out


# ---------------------------------------------------------------------------------------------- cost of position
def position_cost(buys: List[Tuple[float, float]], sells: List[Tuple[float, float]]) -> Dict[str, Any]:
    """'Maliyet' as on the Calculators sheet: break-even level of the net position.

    ``buys`` / ``sells`` are (size, level) pairs.  Net = ΣA_buy − ΣA_sell, cost = (A₁R₁ − A₂R₂)/(A₁ − A₂),
    realised = min(A₁, A₂)·(R₂ − R₁).
    """
    a1 = sum(a for a, _ in buys)
    a2 = sum(a for a, _ in sells)
    r1 = sum(a * r for a, r in buys) / a1 if a1 else None
    r2 = sum(a * r for a, r in sells) / a2 if a2 else None
    net = a1 - a2
    cost = None
    if a1 and a2:
        if net != 0:
            cost = (a1 * r1 - a2 * r2) / net
    elif a1:
        cost = r1
    elif a2:
        cost = r2
    realised = min(a1, a2) * (r2 - r1) if (a1 and a2) else 0.0
    return {"buy": a1, "buy_avg": r1, "sell": a2, "sell_avg": r2, "net": net, "cost": cost, "realised": realised}


def summarise(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Position and cost per forward (pair and value date), OIS bucket (the leg's tenor; one between the desk's buckets
    split between the two around it: :func:`buckets`) or meeting-dated period and bond."""
    fwd: Dict[Tuple[str, float], Dict[str, List[Tuple[float, float]]]] = {}
    spans: Dict[str, float] = {}
    ois: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    bonds: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    for t in trades:
        k = t.get("kind")
        if k == "fwd":
            d = fwd.setdefault((t.get("pair") or "USDTRY", t["value_date"]), {"B": [], "S": []})
            d[t["dir"]].append((t["amount"], t["forward"]))
        elif k == "ois":
            if t.get("mpc"):
                ois.setdefault(t["tenor"], {"B": [], "S": []})[t["dir"]].append((t["dv01"], t["rate"]))
                spans[t["tenor"]] = t["mpc"].get("start") or 0.0
            else:
                end = tenor_date_of(t["tenor"])
                if end is not None:
                    spans[t["tenor"]] = end                  # (a broken date: its own row, in the order of its day)
                for b, w in buckets(t["tenor"]):
                    ois.setdefault(b, {"B": [], "S": []})[t["dir"]].append((t["dv01"] * w, t["rate"]))
        elif k == "bond":
            d = bonds.setdefault(t["instrument"], {"B": [], "S": []})
            if t["amount"] >= 0:
                d["B"].append((t["amount"], t["price"]))
            else:
                d["S"].append((-t["amount"], t["price"]))
    out: Dict[str, Any] = {"fwd": [], "ois": [], "bond": []}
    for pair, vd in sorted(fwd, key=lambda x: (x[0] != "USDTRY", x[0], x[1])):
        pc = position_cost(fwd[(pair, vd)]["B"], fwd[(pair, vd)]["S"])
        pc["key"] = vd
        pc["pair"] = pair
        # forwards: realised P&L in TL = matched amount × (sell forward − buy forward)
        out["fwd"].append(pc)
    order = {t: i for i, t in enumerate(OIS_TENORS)}
    for tenor in sorted(ois, key=lambda x: (order.get(x, 999), spans.get(x, 0.0), x)):
        # pay = "B" (buy the rate), receive = "S"; realised in USD = matched DV01 × (receive − pay) in bp
        pc = position_cost(ois[tenor]["B"], ois[tenor]["S"])
        pc["key"] = tenor
        pc["realised"] = pc["realised"] * 10000.0
        out["ois"].append(pc)
    for inst in sorted(bonds):
        pc = position_cost(bonds[inst]["B"], bonds[inst]["S"])
        pc["key"] = inst
        pc["realised"] = pc["realised"] / 100.0
        out["bond"].append(pc)
    return out


def _months_of(tenor: Any) -> Optional[int]:
    """The months of a tenor of the lists: "9M" 9, "1Y" 12, "27M" 27 (``None`` for "ON", "1W" ...)."""
    m = re.match(r"^(\d+)([MY])$", str(tenor or ""))
    return int(m.group(1)) * (12 if m.group(2) == "Y" else 1) if m else None


def _size(v: Any) -> str:
    """An amount as the desk says it: 10m, 2,5m, 500k, 1bn."""
    if type(v) is not float:
        return "–"
    a = abs(v)
    for unit, k in (("bn", 1e9), ("m", 1e6), ("k", 1e3)):
        if a >= k:
            return ("%g" % round(a / k, 3)).replace(".", ",") + unit
    return ("%g" % a).replace(".", ",")


def trade_entries(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The blotter's trades as they were entered - an OIS spread, fly or FRA is one entry of its legs (its package) -
    each with its instrument as the broker chat names it (``sig``: see ``brokerchat.booked_as``), its level in the
    chat's unit (per cent for an outright, a FRA and a meeting swap; bp for a spread and a fly; swap points; a bond's
    price), when it was entered (``at``), its day, its note and a label to show.  ``id``: the first leg's."""
    out: List[Dict[str, Any]] = []
    packages: Dict[str, List[Dict[str, Any]]] = {}
    for t in trades:
        kind = t.get("kind")
        base = {"id": t["id"], "ids": [t["id"]], "kind": kind, "at": t.get("created_at"), "date": t.get("trade_date"),
                "note": t.get("note") or "", "by": t.get("created_by")}
        if kind == "ois":
            packages.setdefault(t.get("package") or "#%d" % t["id"], []).append(t)
        elif kind == "fwd":
            pair = t.get("pair") or "USDTRY"
            points = t.get("points") if type(t.get("points")) is float else None
            days = t.get("days") if type(t.get("days")) is float else None
            out.append(dict(base, sig=("fwd", pair), level=points, days=days,
                            label="%s %s %s · %s gün · %s puan" % ("Alış" if t.get("dir") == "B" else "Satış", pair, _size(t.get("amount")),
                                                                   "%d" % days if days is not None else "?", "%g" % points if points is not None else "?")))
        elif kind == "bond":
            inst = "".join(str(t.get("instrument") or "").split()).upper()
            amount, price = t.get("amount"), t.get("price")
            out.append(dict(base, sig=("bond", inst), level=price if type(price) is float else None,
                            label="%s %s %s @ %s" % ("Alış" if type(amount) is float and amount > 0 else "Satış", t.get("name") or inst,
                                                    _size(abs(amount) if type(amount) is float else None),
                                                    ("%.3f" % price).replace(".", ",") if type(price) is float else "?")))
    for legs in packages.values():
        legs.sort(key=lambda x: x["id"])
        first = legs[0]
        role = {lg.get("role"): lg for lg in legs}
        strategy = first.get("strategy")
        level = first.get("level") if type(first.get("level")) is float else None
        sig: Optional[Tuple[Any, ...]] = None
        if strategy == "outright":
            sig = ("ois", "outright", first.get("tenor"))
        elif strategy == "spread" and "short" in role and "long" in role:
            sig = ("ois", "spread", role["short"].get("tenor"), role["long"].get("tenor"))
        elif strategy == "fly" and all(k in role for k in ("wing1", "body", "wing2")):
            sig = ("ois", "fly", role["wing1"].get("tenor"), role["body"].get("tenor"), role["wing2"].get("tenor"))
        elif strategy == "fra" and "end" in role:
            sig = ("ois", "fra", _months_of(role["start"].get("tenor")) if "start" in role else 0, _months_of(role["end"].get("tenor")))
        elif strategy == "mpc" and first.get("mpc"):
            sig = ("ois", "mpc", serial_to_date(first["mpc"]["start"]).isoformat(), serial_to_date(first["mpc"]["end"]).isoformat())
        if level is not None and strategy in ("outright", "fra", "mpc"):
            level *= 100.0                                   # per cent, as the chat says it
        out.append({"id": first["id"], "ids": [lg["id"] for lg in legs], "kind": "ois", "sig": sig, "level": level,
                    "at": first.get("created_at"), "date": first.get("trade_date"), "note": first.get("note") or "",
                    "by": first.get("created_by"), "label": first.get("label") or "", "cpt": first.get("cpt") or ""})
    return sorted(out, key=lambda e: e["id"])


# ---------------------------------------------------------------------------------------------- a trade edited
#: the row's own columns of a stored trade (``Store.trades``): not part of its record
ROW_KEYS = ("id", "kind", "package", "trade_date", "created_by", "created_at", "updated_by", "updated_at")
#: how many of its edits a trade keeps with itself (``edits``: the last ones)
EDITS_KEPT = 20


def same(a: Any, b: Any) -> bool:
    """Two values of a record that are one: equal, or two numbers apart by rounding alone (a rate sent back as the text
    it was shown as, a leg struck again on the same curve)."""
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return a == b or abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


def edited(old: Dict[str, Any], rec: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A stored trade (a row of ``Store.trades``) and what an edit makes of it (``rec``: the values it sets): (the record
    to keep - those values over the old record, one that moved by rounding alone kept as it was -, what changed:
    ``{key: the value before}``).  The trade's list of its edits (``edits``) stays as it was: the caller adds this one."""
    new = {k: v for k, v in old.items() if k not in ROW_KEYS}
    was: Dict[str, Any] = {}
    for k, v in rec.items():
        if k in ROW_KEYS or k == "edits" or same(new.get(k), v):
            continue
        was[k] = new.get(k)
        new[k] = v
    return new, was


def cost_vs_mid(strategy: str, side: Any, level: Any, mid: Any) -> Optional[float]:
    """The cost of an OIS trade against a mid, by :func:`ois_legs`'s rule: bp, + worse than mid (paid).  A receiver
    (RECEIVE, FLATTENER, REC GÖVDE) is worse below mid, a payer above it; ``level`` and ``mid`` are fractions (bp for a
    spread and a fly).  ``None`` without a mid."""
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (mid, level)):
        return None
    receives = str(side or "").upper().replace("GOVDE", "GÖVDE") in ("RECEIVE", "FLATTENER", "REC GÖVDE")
    gap = float(mid - level) if receives else float(level - mid)
    return gap if strategy in ("spread", "fly") else gap * 10000.0


def risk_dv01(strategy: str, legs: Sequence[Dict[str, Any]]) -> float:
    """The DV01 the cost against mid is counted on in money (:func:`ois_legs`'s rule): a FRA's net, a fly's body halved
    (its rate moves by half the level), else the last leg's."""
    if strategy == "fra":
        return abs(legs[-1]["dv01"] - (legs[0]["dv01"] if len(legs) > 1 else 0.0))
    if strategy == "fly":
        return legs[1]["dv01"] / 2.0
    return legs[-1]["dv01"]


#: the legs of an OIS strategy in :func:`ois_legs`'s order (a FRA's: :func:`legs_in_order`)
LEG_ROLES = {"outright": ("outright",), "spread": ("short", "long"), "fly": ("wing1", "body", "wing2"), "mpc": ("mpc",)}


def leg_weight(strategy: str, role: Any) -> float:
    """The weight of a leg's nominal in its package (:func:`ois_legs`): a fly's wings half, any other leg one (a FRA's
    two legs: one nominal)."""
    return 0.5 if strategy == "fly" and role in ("wing1", "wing2") else 1.0


def legs_in_order(strategy: str, legs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A stored OIS trade's legs in :func:`ois_legs`'s order of roles (a FRA: start - when it does not start at spot -,
    end); :class:`TradeError` when they are not that strategy's."""
    by_role = {lg.get("role"): lg for lg in legs}
    roles = LEG_ROLES.get(strategy) or (("start", "end") if "start" in by_role else ("end",))
    if len(by_role) != len(legs) or set(by_role) != set(roles):
        raise TradeError("işlemin bacakları %s stratejisinin değil" % strategy)
    return [by_role[r] for r in roles]


def ois_instrument(strategy: str, legs: Sequence[Dict[str, Any]]) -> Tuple[Any, ...]:
    """What an OIS trade is, from its legs as stored: its tenors (outright, spread, fly), its FRA's months, its meeting
    swap's two days - what an edit compares with :func:`typed_instrument` (the side apart)."""
    by_role = {lg.get("role"): lg for lg in legs}
    if strategy == "fra":
        start = by_role.get("start")
        point = lambda t: t if tenor_date_of(t) is not None else _months_of(t)            # noqa: E731 (a date: its name)
        return (point(start["tenor"]) if start else 0, point((by_role.get("end") or {}).get("tenor")))
    if strategy == "mpc":
        m = legs[0].get("mpc") or {}
        return (m.get("start"), m.get("end"))
    return tuple((by_role.get(r) or {}).get("tenor") for r in LEG_ROLES.get(strategy, ()))


def typed_instrument(strategy: str, payload: Dict[str, Any]) -> Tuple[Any, ...]:
    """The same of an OIS trade as the form sends it, read as :func:`ois_legs` reads it."""
    if strategy == "fra":
        out: List[Any] = []
        for m, d in (("start_months", "start_date"), ("end_months", "end_date")):
            if type(payload.get(d)) is float:                    # (a FRA between dates: each by its day's name)
                out.append(date_tenor(payload[d]))
            else:
                out.append(int(payload[m]) if type(payload.get(m)) is float else payload.get(m))
        return tuple(out)
    if strategy == "mpc":
        return (payload.get("start"), payload.get("end"))
    keys = {"outright": ("tenor",), "spread": ("short", "long"), "fly": ("wing1", "body", "wing2")}.get(strategy, ())
    return tuple(str(payload.get(k) or "").upper().strip() for k in keys)


def restrike(strategy: str, legs: Sequence[Dict[str, Any]], level: float, rates: Optional[Dict[str, float]] = None,
             nominal: Optional[float] = None, dv01: Optional[float] = None, lot: float = 1.0) -> List[Dict[str, Any]]:
    """An OIS trade's legs at a new ``level`` and size on the curve it was entered on - not today's: every leg keeps its
    annuity / USDTRY of then in its DV01 per nominal.  The size: a ``nominal`` (TL; a fly's wings half of it) is exact, a
    ``dv01`` ($/bp) is sized by OIS_MAIN's rule on that curve (a FRA on its forward annuity), neither keeps the legs'
    nominals - and a leg whose nominal stays keeps its DV01.  ``rates``: a leg's own rate by role ("short", "wing1",
    "wing2", "start"), else the one it has.  Returns the legs (in :func:`legs_in_order`) with their new ``rate``,
    ``nominal`` and ``dv01``; :class:`TradeError` when a leg does not say its curve (no nominal)."""
    legs = legs_in_order(strategy, legs)
    try:
        per = [float(lg["dv01"]) / float(lg["nominal"]) for lg in legs]       # annuity · 0,0001 / USDTRY, at the trade
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        per = []
    if len(per) != len(legs) or not all(math.isfinite(x) and x > 0 for x in per):
        raise TradeError("işlemin bacaklarında eğrisi kayıtlı değil: silip yeniden girin")
    if nominal is not None:
        nominals = [nominal * leg_weight(strategy, lg.get("role")) for lg in legs]
    elif dv01 is not None:
        if strategy == "fra":                       # one nominal, sized on the forward annuity: end's − start's
            one = _round_half_away(dv01 / (per[-1] - (per[0] if len(legs) > 1 else 0.0)) / lot) * lot
            nominals = [one] * len(legs)
        else:
            nominals = [_round_half_away(leg_weight(strategy, lg.get("role")) * dv01 / x / lot) * lot for lg, x in zip(legs, per)]
    else:
        nominals = [lg["nominal"] for lg in legs]
    rates = rates or {}

    def own(role: str, lg: Dict[str, Any]) -> float:
        v = rates.get(role)
        return v if type(v) is float else lg["rate"]

    if strategy == "spread":
        short = own("short", legs[0])
        new = [short, short + level / 10000.0]
    elif strategy == "fly":
        w1, w2 = own("wing1", legs[0]), own("wing2", legs[2])
        new = [w1, (level / 10000.0 + w1 + w2) / 2.0, w2]
    elif strategy == "fra" and len(legs) == 2:
        start = own("start", legs[0])
        k = per[0] / per[1]                         # A1 / A2: the two spot swaps' annuities at the trade
        new = [start, level * (1.0 - k) + start * k]
    else:
        new = [level] * len(legs)
    return [dict(lg, rate=r, nominal=n, dv01=lg["dv01"] if n == lg["nominal"] else n * x)
            for lg, n, x, r in zip(legs, nominals, per, new)]


def forward_restruck(t: Dict[str, Any], direction: str, typed: Tuple[str, float]) -> Dict[str, Any]:
    """A stored forward with another side or amount at its own rates - the forward, the TRY rate, the spot and the
    discount factors it was priced with: its two amounts and its DV01 again, nothing priced (:func:`forward_trade`'s
    rules)."""
    pair = str(t.get("pair") or "USDTRY").upper()
    if type(t.get("forward")) is not float or type(t.get("days")) is not float:
        raise TradeError("işlemin kayıtlı kuru yok: silip yeniden girin")
    amount, counter = forward_amounts(typed, t["forward"], pair[:3])
    if not amount > 0:
        raise TradeError("karşı tutar %s tutarına çevrilemeyecek kadar küçük" % pair[:3])
    usdtry = t.get("usdtry") if type(t.get("usdtry")) is float else (t.get("spot") if pair == "USDTRY" else None)
    risk = forward_dv01(direction, amount, t["forward"], t["days"], usdtry, t.get("df_try"), t.get("df_usd"),
                        t.get("try_rate") if pair[3:] == "TRY" else None, t.get("usd_rate"))
    return {"dir": direction, "amount": amount, "tl": counter, "typed": typed[0], "typed_amount": typed[1],
            "dv01_tl": risk["tl"], "dv01": risk["usd"], "usd_dv01": risk["usd_leg"]}


# ---------------------------------------------------------------------------------------------- a trade copied
#: "Benzerini gir" (the trade again: its terms, a new trade) and "Ters işlem" (the trade that offsets it) - the desk,
#: 23.11.2026: "one click fills the entry form from that trade, either as a new trade or with the side reversed, for
#: repeats and unwinds"
COPY_MODES = ("benzer", "ters")
_OIS_FLIP = {"PAY": "RECEIVE", "RECEIVE": "PAY", "STEEPENER": "FLATTENER", "FLATTENER": "STEEPENER",
             "REC GÖVDE": "PAY GÖVDE", "PAY GÖVDE": "REC GÖVDE"}


def _serial(iso: str) -> float:
    return float(date_to_serial(_dt.date.fromisoformat(iso)))


def leg_end(trade_date: str, tenor: Any, holidays: Any) -> Optional[float]:
    """The day an OIS leg of the blotter ends: a broken date its own; a tenor of the lists from the OIS spot of the day
    it was entered (``WORKDAY(day, 1, TRY)``) on the workbook's calendar - months as Motor's (``WORKDAY(EDATE(spot, m)
    − 1, 1, TRY)``: :func:`tto.pricing.tenor_date`), ON / 1W / 2W one / seven / fourteen days on, to a business day."""
    from . import pricing as pr
    end = tenor_date_of(tenor)
    if end is not None:
        return end
    spot = pr.roll(_serial(trade_date) + 1.0, holidays)
    m = _months_of(tenor)
    if m is not None:
        return pr.tenor_date(spot, m, holidays)
    days = {"ON": 1.0, "1W": 7.0, "2W": 14.0}.get(str(tenor or ""))
    return pr.roll(spot + days, holidays) if days is not None else None


def fwd_tenor(t: Dict[str, Any]) -> Optional[str]:
    """The tenor a forward's value date is from its own spot date (``value_date − days``): "3M" when it is a whole number
    of months on (rolled to a business day: up to four days after the date), "2W" for whole weeks; ``None`` for a date of
    its own."""
    vd, days = t.get("value_date"), t.get("days")
    if type(vd) is not float or type(days) is not float or days <= 0:
        return None
    from .history import add_months
    spot = serial_to_date(vd - days)
    for m in range(1, 121):
        d = float(date_to_serial(add_months(spot, m)))
        if 0.0 <= vd - d <= 4.0:
            return "%dM" % m
        if d > vd:
            break
    if days in (7.0, 14.0, 21.0):
        return "%dW" % int(days // 7)
    return None


def copy_specs(legs: Sequence[Dict[str, Any]], cal: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """What "Benzerini gir" and "Ters işlem" fill the entry form with from a trade (``legs``: an OIS package's legs, any
    other trade alone), by mode (:data:`COPY_MODES`): ``{"spec"}`` - the form's spec (``blotter.js`` ``fillForm``: its
    amounts and sizes as numbers, the page writes them in the user's format) - with ``how`` (what moved, in words), or
    ``{"why"}`` when that one makes no sense for the trade.  Nothing is saved; the form prices it on today's market as a
    new trade: no price, rate or level of the trade comes along.

    * **Benzerini gir**: the trade's terms - product, structure, side, size (as it was typed: a forward's amount in its
      currency, an OIS's nominal or DV01), counterparty, note -, its instrument as it was entered: a tenor from today's
      spot, a date its date; a day gone by's forward its tenor again from today's spot (:func:`fwd_tenor`), a meeting
      swap whose start has passed from today's spot.
    * **Ters işlem**: the other side, the same size (a forward's first-currency amount, an OIS's nominal - a spread / fly
      sized by DV01 that DV01 -, a bond's nominal), the same end - value date, maturity, ISIN, meeting -; a start that
      has passed is today's spot: a day gone by's TRY OIS is a broken date to its own maturity (each leg of a package,
      a FRA started a spot swap to its end).  A trade that has run off has no offset.

    ``cal``: ``today`` (ISO), ``ois_spot`` (today's OIS spot, serial), ``holidays`` (TRY, serials), ``fx_spot(pair)``
    (today's spot date of a pair)."""
    t = legs[0]
    kind = t.get("kind")
    past = t.get("trade_date") != cal["today"]
    if kind == "fwd":
        return {m: _copy_fwd(t, m, past, cal) for m in COPY_MODES}
    if kind == "bond":
        return {m: _copy_bond(t, m) for m in COPY_MODES}
    if kind == "ois":
        out = {}
        for m in COPY_MODES:
            try:
                out[m] = _copy_ois(legs, m, past, cal)
            except (TradeError, KeyError, TypeError, ValueError) as exc:
                out[m] = {"why": "formda açılamıyor: %s" % (str(exc) or type(exc).__name__)}
        return out
    return {m: {"why": "bu ürün formda yok"} for m in COPY_MODES}


def _copy_fwd(t: Dict[str, Any], mode: str, past: bool, cal: Dict[str, Any]) -> Dict[str, Any]:
    pair = str(t.get("pair") or "USDTRY").upper()
    vd = t.get("value_date")
    if type(vd) is not float or t.get("dir") not in ("B", "S"):
        return {"why": "işlemin valörü ya da yönü yok"}
    spot = cal["fx_spot"](pair)
    spec: Dict[str, Any] = {"kind": "fwd", "pair": pair, "dir": t["dir"], "basis": t.get("basis") if t.get("basis") in FWD_BASES else "RET_MID",
                            "value": "", "spot": "", "cpt": t.get("cpt") or "", "note": t.get("note") or ""}
    if mode == "ters":
        if type(spot) is float and vd <= spot:
            return {"why": "valörü geldi (%s): kapatılacak forward kalmadı" % date_tenor(vd)}
        spec.update(dir="S" if t["dir"] == "B" else "B", amount=t.get("amount"), date=date_tenor(vd))
        how = "Ters yön, aynı %s tutarı ve valör (%s)" % (pair[:3], date_tenor(vd))
        if t.get("typed") == "quote":
            how += " - karşı parada girilmişti: %s tutarı tam kapansın diye dövizde" % pair[:3]
        return {"spec": spec, "how": how}
    side, amount, ccy = entered_as(t)
    spec["quote_amount" if side == "quote" else "amount"] = amount
    if not past:
        spec["date"] = date_tenor(vd)
        return {"spec": spec, "how": "Aynı valör (%s), bugünkü piyasayla" % date_tenor(vd)}
    tenor = fwd_tenor(t)
    if tenor is not None:
        spec["date"] = tenor
        return {"spec": spec, "how": "Spot'u geçti: aynı vade (%s) bugünkü spot'tan" % tenor}
    days = t.get("days") if type(t.get("days")) is float else None
    if type(spot) is float and days:
        spec["date"] = date_tenor(spot + days)
        return {"spec": spec, "how": "Spot'u geçti: aynı gün sayısı (%d) bugünkü spot'tan" % days}
    spec["date"] = date_tenor(vd)
    return {"spec": spec, "how": "Aynı valör (%s)" % date_tenor(vd)}


def _copy_bond(t: Dict[str, Any], mode: str) -> Dict[str, Any]:
    amount = t.get("amount")
    if type(amount) is not float or not t.get("instrument"):
        return {"why": "işlemin kâğıdı ya da tutarı yok"}
    buy = amount >= 0
    if mode == "ters":
        buy = not buy
    spec = {"kind": "bond", "dir": "B" if buy else "S", "instrument": t["instrument"], "amount": abs(amount), "price": "",
            "note": t.get("note") or ""}
    return {"spec": spec, "how": ("Ters yön, aynı kâğıt ve nominal" if mode == "ters" else "Aynı kâğıt, yön ve nominal")
            + ": fiyatı yazın"}


def _ois_size(strategy: str, role: Dict[str, Dict[str, Any]], t: Dict[str, Any]) -> Tuple[str, Optional[float]]:
    """An OIS trade's size as the form takes it (``editSpec``'s rule): a spread / fly by the nominal of its leg of weight
    one when every leg has that nominal (a fly's wings half), else by the DV01 it was typed with (none: the sheet's); any
    other strategy by its nominal - exact."""
    if strategy in ("spread", "fly"):
        one = role["long"] if strategy == "spread" else role["body"]
        others = [role["short"]] if strategy == "spread" else [role["wing1"], role["wing2"]]
        w = 1.0 if strategy == "spread" else 0.5
        by_nominal = t.get("size_mode") == "nominal" if t.get("size_mode") else \
            all(abs(x["nominal"] - w * one["nominal"]) < 0.5 for x in others)
        if by_nominal:
            return "nominal", one["nominal"]
        typed = t.get("size_typed") if t.get("size_mode") else float(round(one["dv01"]))
        return "dv01", typed if type(typed) is float else None
    return "nominal", (role.get("end") or t)["nominal"]


def _copy_ois(legs: Sequence[Dict[str, Any]], mode: str, past: bool, cal: Dict[str, Any]) -> Dict[str, Any]:
    t = legs[0]
    role = {lg.get("role"): lg for lg in legs}
    st = str(t.get("strategy") or "outright")
    side = str(t.get("side") or "").upper().replace("GOVDE", "GÖVDE")
    if side not in _OIS_FLIP:
        return {"why": "işlemin yönü yok"}
    spot = cal["ois_spot"]
    if type(spot) is not float:
        return {"why": "OIS spot tarihi yok"}
    hol = cal["holidays"]
    ters = mode == "ters"
    spec: Dict[str, Any] = {"kind": "ois", "strategy": st, "side": _OIS_FLIP[side] if ters else side, "level": "",
                            "cpt": t.get("cpt") or "", "note": t.get("note") or ""}
    spec["sizeMode"], spec["size"] = _ois_size(st, role, t)
    if spec["size"] is None:
        del spec["size"]                                       # (the sheet's DV01, as it was entered)
    ran_off = "vadesi geldi (%s): kapatılacak swap kalmadı"
    if st == "mpc":
        m = t.get("mpc") or {}
        s, e = m.get("start"), m.get("end")
        if type(s) is not float or type(e) is not float:
            return {"why": "işlemin tarihleri yok"}
        if e <= spot:
            return {"why": "dönemi bitti (%s)" % date_tenor(e)}
        spec.update(start=max(s, spot), end=e)
        how = "Aynı toplantı tarihleri" if s >= spot else "Başlangıcı geçti: bugünkü spot'tan (%s) aynı bitişe (%s)" % (
            date_tenor(spot), date_tenor(e))
        return {"spec": spec, "how": how + (", ters yön" if ters else "")}
    if st == "fra":
        start, end = role.get("start"), role.get("end")
        if end is None:
            return {"why": "işlemin bitiş bacağı yok"}
        point = lambda lg: lg["tenor"] if tenor_date_of(lg["tenor"]) is not None else _months_of(lg["tenor"])     # noqa: E731
        months = [point(start) if start else 0, point(end)]
        if not ters or not past:
            spec["months"] = months
            return {"spec": spec, "how": "Aynı FRA" + (" bugünkü spot'tan" if past else "") + (", ters yön" if ters else "")}
        e = leg_end(t["trade_date"], end["tenor"], hol)
        s = leg_end(t["trade_date"], start["tenor"], hol) if start else None
        if e is None or e <= spot:
            return {"why": ran_off % date_tenor(e) if e is not None else "işlemin vadesi okunamadı"}
        if s is None or s <= spot:
            spec["months"] = [0, date_tenor(e)]
            return {"spec": spec, "how": "Başlangıcı geçti: bugünkü spot'tan (%s) FRA'nın bitişine (%s) kırık vade, ters yön"
                    % (date_tenor(spot), date_tenor(e))}
        spec["months"] = [date_tenor(s), date_tenor(e)]
        return {"spec": spec, "how": "Aynı tarihler (%s → %s), ters yön" % (date_tenor(s), date_tenor(e))}
    order = LEG_ROLES.get(st)
    if not order or any(r not in role for r in order):
        return {"why": "işlemin bacakları %s stratejisinin değil" % st}
    tenors = [role[r]["tenor"] for r in order]
    if not ters or not past:
        for x in tenors:                                       # (a broken date of its own: still to come)
            end = tenor_date_of(x)
            if end is not None and end <= spot:
                return {"why": "vadesi geldi (%s)" % x}
        spec["tenors"] = tenors
        return {"spec": spec, "how": ("Aynı vade" if len(tenors) == 1 else "Aynı vadeler") + (" bugünkü spot'tan" if past else "")
                + (", ters yön" if ters else "")}
    # a day gone by's: each leg from today's spot to its own maturity - broken dates
    ends = [leg_end(t["trade_date"], x, hol) for x in tenors]
    if any(e is None for e in ends):
        return {"why": "işlemin vadesi okunamadı"}
    if any(e <= spot for e in ends):
        return {"why": ran_off % date_tenor(min(ends))}
    spec["tenors"] = [date_tenor(e) for e in ends]
    return {"spec": spec, "how": "Başlangıcı geçti: bugünkü spot'tan (%s) işlemin vadesine kırık vade (%s), ters yön"
            % (date_tenor(spot), " / ".join(spec["tenors"]))}


def overnight_equivalent(rate: Any, days: Any) -> Optional[float]:
    """O/N equivalent (360) of a forward trade's TRY rate, as column F of the blotter sheet computes it:
    ``360*((1+rate*days/365)^(1/days)-1)``."""
    try:
        r, d = float(rate), float(days)
    except (TypeError, ValueError):
        return None
    if d <= 0 or 1.0 + r * d / 365.0 <= 0:
        return None
    return 360.0 * ((1.0 + r * d / 365.0) ** (1.0 / d) - 1.0)


# ---------------------------------------------------------------------------------------------- sheet sync
# the main tenors of the sheet's OIS summary ('OIS · vade özeti', P25:P38): where a meeting-dated swap is spread
SUMMARY_TENORS = ("ON", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y")


def tenor_end(spot: float, tenor: str) -> float:
    """The end (serial date) of a spot swap of a quoted tenor."""
    days = {"ON": 1.0, "1W": 7.0, "2W": 14.0}.get(tenor)
    if days is not None:
        return spot + days
    d = serial_to_date(spot)
    m = d.month - 1 + TENOR_MONTHS[tenor]
    y, m = d.year + m // 12, m % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return float(date_to_serial(_dt.date(y, m, min(d.day, last))))


def split_weights(x: float, nodes: Sequence[float]) -> List[Tuple[int, float]]:
    """A point spread over the two nodes around it, linearly (all of it on the end node outside them) - the way
    the sheet's own forward buckets spread an amount: ``[(node index, weight)]``."""
    if x <= nodes[0]:
        return [(0, 1.0)]
    if x >= nodes[-1]:
        return [(len(nodes) - 1, 1.0)]
    k = bisect.bisect_right(nodes, x) - 1
    if x == nodes[k] or nodes[k + 1] == nodes[k]:
        return [(k, 1.0)]
    w = (x - nodes[k]) / (nodes[k + 1] - nodes[k])
    return [(k, 1.0 - w), (k + 1, w)]


def mpc_summary_rows(mkt: "OisMarket", t: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A meeting-dated swap on the summary's main tenors.  The swap from S to E is the spot swap to E with the
    opposite spot swap to S, on one nominal - the one that makes their DV01s add up to the trade's (from the spot
    itself: only the first, the trade as it is); each of the two goes to the two main tenors around its date,
    split by days as the sheet splits a forward.  The rate of the leg to S is the curve's (spot to S), the leg
    to E's is what makes the two together the traded rate: (R·(A_E − A_S) + R_S·A_S) / A_E."""
    info = t.get("mpc") or {}
    start, end = info.get("start"), info.get("end")
    spot = mkt.value("OIS_MAIN!B2")
    nominal, rate, d, dv01 = t.get("nominal"), t.get("rate"), t.get("dir"), t.get("dv01")
    if type(spot) is not float or type(start) is not float or type(end) is not float or type(nominal) is not float \
            or type(rate) is not float or type(dv01) is not float or d not in ("B", "S"):
        return []
    nodes = [tenor_end(spot, x) for x in SUMMARY_TENORS]
    legs = [(end, d, dv01, rate, nominal)]                  # from the spot: one spot swap, the trade itself
    if start > spot + 0.5:
        try:
            long_leg, short = mkt.between(spot, end), mkt.between(spot, start)
            a_e, a_s, r_s = long_leg["annuity"], short["annuity"], short["market"]
            d_e, d_s = mkt.dv01_usd(nominal, a_e), mkt.dv01_usd(nominal, a_s)
            if d_e <= d_s:
                raise ZeroDivisionError
            # one nominal for both legs, chosen so that they add up to the trade's own DV01 exactly
            k = dv01 / (d_e - d_s)
            legs = [(end, d, d_e * k, (rate * (a_e - a_s) + r_s * a_s) / a_e, nominal * k),
                    (start, "S" if d == "B" else "B", d_s * k, r_s, nominal * k)]
        except (TradeError, ZeroDivisionError):
            pass                                            # no curve to split it with: all of it at its end
    rows = []
    for when, direction, dv, r, n in legs:
        for k, w in split_weights(when, nodes):
            rows.append({"nominal": n * w, "dv01": dv * w, "dir": direction, "rate": r, "tenor": SUMMARY_TENORS[k],
                         "cpt": t.get("cpt")})
    return rows


def usd_equivalent(t: Dict[str, Any]) -> Optional[float]:
    """The USD amount a forward of another currency against TRY stands for (its amount at the trade's spot,
    turned into USD at the USDTRY of the trade); ``None`` when it is not against TRY."""
    pair = str(t.get("pair") or "USDTRY").upper()
    if pair == "USDTRY":
        return float(t["amount"])
    spot, usdtry = t.get("spot"), t.get("usdtry")
    if not pair.endswith("TRY") or type(spot) is not float or type(usdtry) is not float or usdtry <= 0:
        return None
    return float(t["amount"]) * spot / usdtry


def in_summary(t: Dict[str, Any]) -> bool:
    """Whether the sheet's summary tables take the trade (a forward needs a TRY leg)."""
    return t.get("kind") != "fwd" or (usd_equivalent(t) is not None and type(t.get("try_rate")) is float)


def forward_dv01_buckets(book, calc, trades: List[Dict[str, Any]]) -> Dict[int, Tuple[float, float]]:
    """DV01 ($) of the day's forwards in the sheet's forward buckets (rows 6..19), split between the two buckets
    around the value date as the sheet splits the amounts: ``{row: (buys, sells)}``, the total under row 20."""
    si = book.model.sheet_index[SHEET]

    def v(addr: str) -> Any:
        return calc.get(si, *divmod(parse_a1(addr), COLS))

    nodes = [v("O%d" % r) for r in range(6, 20)]
    today = v("X1")                                  # the sheet's day (Forward!I2 - a date written as text, as Excel reads it)
    if isinstance(today, str):
        from .inputs import InputError, parse_date
        try:
            today = parse_date(today)
        except (InputError, ValueError):
            today = None
    out: Dict[int, List[float]] = {r: [0.0, 0.0] for r in range(6, 21)}
    if any(type(x) is not float for x in nodes) or type(today) is not float:
        return {}
    for t in trades:
        if t.get("kind") != "fwd" or type(t.get("dv01")) is not float or type(t.get("value_date")) is not float:
            continue
        if not in_summary(t):
            continue
        side = 0 if t.get("dir") == "B" else 1
        for k, w in split_weights(t["value_date"] - today, nodes):
            out[6 + k][side] += t["dv01"] * w
            out[20][side] += t["dv01"] * w
    return {r: (a, b) for r, (a, b) in out.items()}


def sheet_values(book, trades: List[Dict[str, Any]], left_out: Optional[Dict[str, int]] = None) -> Dict[Tuple[int, int], Any]:
    """Cell values of the three input lists of the 'Günlük İşlemler' sheet for the given trades.

    The sheet was made for USDTRY forwards and OIS of a quoted tenor.  A forward of another currency against
    TRY goes in at its USD amount (its TRY rate as it is: the TL cost); a meeting-dated OIS goes in spread over
    the main tenors (see :func:`mpc_summary_rows`); an OIS leg between the desk's buckets (15M, 21M, 27M …) as two rows,
    its nominal and DV01 split between the two buckets around it at its own rate (:func:`buckets` - the sheet's tables
    have no row for its tenor).  Column G holds each forward's DV01 ($).  ``left_out`` (a dict): counts by kind the
    trades the lists had no row left for (:data:`FWD_ROWS`, :data:`OIS_ROWS`, :data:`BOND_ROWS`)."""
    si = book.model.sheet_index[SHEET]
    vals: Dict[Tuple[int, int], Any] = {}

    def put(col: str, row: int, v: Any):
        vals[(si, parse_a1("%s%d" % (col, row)))] = v

    for r in range(FWD_ROWS[0], FWD_ROWS[1] + 1):
        for col in "ABCDG":
            put(col, r, None)
    for r in range(OIS_ROWS[0], OIS_ROWS[1] + 1):
        for col in "HIJKLM":
            put(col, r, None)
    for r in range(BOND_ROWS[0], BOND_ROWS[1] + 1):
        for col in ("Y", "Z", "AA"):
            put(col, r, None)
    rf, ro, rb = FWD_ROWS[0], OIS_ROWS[0], BOND_ROWS[0]
    mkt = None
    for t in trades:
        k = t.get("kind")
        if k == "fwd" and not in_summary(t):
            continue                                        # no TRY leg: nothing for the TRY tables
        if left_out is not None and {"fwd": rf > FWD_ROWS[1], "ois": ro > OIS_ROWS[1], "bond": rb > BOND_ROWS[1]}.get(k):
            left_out[k] = left_out.get(k, 0) + 1
        if k == "ois" and t.get("mpc"):
            if mkt is None:
                mkt = OisMarket(book, book.engine.shared)
            for leg in mpc_summary_rows(mkt, t):
                if ro > OIS_ROWS[1]:
                    break
                put("H", ro, float(leg["nominal"]))
                put("I", ro, float(leg["dv01"]))
                put("J", ro, leg["dir"])
                put("K", ro, float(leg["rate"]))
                put("L", ro, leg["tenor"])
                put("M", ro, leg.get("cpt") or None)
                ro += 1
            continue
        if k == "fwd" and rf <= FWD_ROWS[1]:
            put("A", rf, t["dir"])
            put("B", rf, float(usd_equivalent(t)))
            put("C", rf, float(t["try_rate"]))
            put("D", rf, float(t["value_date"]))
            put("G", rf, float(t["dv01"]) if type(t.get("dv01")) is float else None)
            rf += 1
        elif k == "ois" and ro <= OIS_ROWS[1]:
            parts = buckets(t["tenor"])
            end = tenor_date_of(t["tenor"])
            if end is not None:
                # a broken date (a spot swap to a day of its own): the two main tenors around its end, by days - as a
                # meeting-dated swap from the spot (:func:`mpc_summary_rows`)
                if mkt is None:
                    mkt = OisMarket(book, book.engine.shared)
                spot = mkt.value("OIS_MAIN!B2")
                if type(spot) is float:
                    nodes = [tenor_end(spot, x) for x in SUMMARY_TENORS]
                    parts = [(SUMMARY_TENORS[i], w) for i, w in split_weights(end, nodes)]
            for b, w in parts:
                if ro > OIS_ROWS[1]:
                    break
                put("H", ro, float(t["nominal"]) * w if t.get("nominal") else None)
                put("I", ro, float(t["dv01"]) * w)
                put("J", ro, t["dir"])
                put("K", ro, float(t["rate"]))
                put("L", ro, b)
                put("M", ro, t.get("cpt") or None)
                ro += 1
        elif k == "bond" and rb <= BOND_ROWS[1]:
            put("Y", rb, t["instrument"])
            put("Z", rb, float(t["amount"]))
            put("AA", rb, float(t["price"]))
            rb += 1
    return vals


def input_ranges() -> List[str]:
    return ["%s!A%d:D%d" % (SHEET, FWD_ROWS[0], FWD_ROWS[1]), "%s!G%d:G%d" % (SHEET, FWD_ROWS[0], FWD_ROWS[1]),
            "%s!H%d:M%d" % (SHEET, OIS_ROWS[0], OIS_ROWS[1]), "%s!Y%d:AA%d" % (SHEET, BOND_ROWS[0], BOND_ROWS[1])]
