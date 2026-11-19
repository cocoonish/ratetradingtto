"""Prop: the top bar's position-size calculator and, below it, the trader's prop risk - to look at only: nothing is
booked or sent anywhere; the one thing kept is each user's daily loss limit.

The desk, 19.11.2026: "Bir de prop trade calculation kısmı açalım, bunu üstteki panele koyabiliriz. Pariteyi, stopumu, ve
potansiyel loss'umu koyduktan sonra 1M'e yuvarlanmış şekilde bana gerçek potansiyel lossumu ve size'i söylesin."  Asked,
they chose: the size rounded **down** to 1M (never above the loss typed), the loss typed in **TRY or USD**, chosen each
time, and the prop risk in the same panel.

**The calculator** (:func:`size`): a pair of the desk's FX lists that has a price, the stop (a price level), the loss
and its currency, the entry (the live mid unless one is typed).

* The direction comes from the stop against the entry: below it long, above it short; equal is an error.
* The loss goes into the pair's quote currency at today's rates: USDTRY with a TRY loss as it is, EURUSD with a TRY loss
  over USDTRY, USDJPY with a USD loss times USDJPY (:func:`convert`).
* ``size = loss in the quote currency / |entry − stop|`` of the base currency, **rounded down to 1 000 000**.
* Shown: the real loss at that size (in the loss's currency, TL and USD), the loss of 1M, the distance (price, %, pips; a
  TL pair's in kuruş too).  Under 1M the size is 0, and the loss 1M would make is said.

**The risk** (:meth:`Prop.risk`): the open trades of a Trades tab - Kişisel (the viewer's own) or Masa (the desk's).

* **Stoplar** - each trade's loss if its stop is hit (:func:`position`), measured from the market now in the trade's own
  level unit (tradebook.level_spec) with the sensitivity of its valuation (tradevalue.value):
  - FX spot: its base amount × the rate's distance (exact);
  - TRY OIS / SOFR outright, PPK period, FRA: its DV01 (notional × annuity × 1 bp) × the bp;
  - a spread / fly: its level's DV01 - half the legs' DV01s, the long leg's / the body's when the package is DV01-weighted
    as the desk sizes it - × the level's bp;
  - a DİBS by its yield: DİBS RV's DV01 (TL a bp of 1 mn, of the simple yield) × the bp; by its price: nominal × the price
    points / 100;
  - an FX option: its stop is a premium (what Trades reads an option's levels in), so the loss is the premium's own
    distance; its delta turns that into the spot level where the stop would be ("yaklaşık (delta)").

  A stop already passed adds nothing: what lies beyond it is lost already (the MTM and the K/Z hold it) and is shown
  beside the trade.  A trade without a stop is listed apart ("stopsuz") with its DV01, its size or its delta.  The levels
  are read on Bootstrap (Murex), as the stop alarms read them.
* **Bugün K/Z** - the tab's "Günlük" as the Trades page shows it: its last "MTM yenile", on the viewer's curve
  (tradebook.listing).  None taken today: no K/Z, so no room either (the panel offers the same "MTM yenile").
* **Limit** - the user's daily loss limit, TRY or USD (``prop.limit:<user>`` in the store's kv: their own only).
* **Kalan** = limit − max(0, −K/Z) − Stoplar: a gain gives no room.

**Prices** are the valuation's market snapshot (tradevalue.market: the Forward sheet's USDTRY and EURTRY, the quant
package's FX series, crosses through USD), taken again after ``MARKET_SECONDS`` - never a Bloomberg request.  A pair it
does not price may be the cross of two it does through TL (EURUSD = EURTRY / USDTRY)."""
from __future__ import annotations

import datetime as _dt
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from . import fx as fxm
from . import tradebook as tbm
from . import tradevalue as tv
from .inputs import parse_amount, parse_number

#: the size's step, rounded down to (the desk: "1M'e yuvarlanmış"; asked which way: down, never above the loss typed)
LOT = 1e6
#: what a loss and a limit are typed in
CCYS = ("TRY", "USD")
#: the market snapshot is taken again after this many seconds (the calculator asks as the user types)
MARKET_SECONDS = 5.0
#: each user's daily loss limit, in the store's kv
LIMIT_KEY = "prop.limit:"
#: a size is rounded down with this much room (relative) for float noise: 400k over 44,55 − 44,35 is 2M, not 1,999…M
_EPS = 1e-9
DIRECTION_TEXT = {"long": "LONG · AL", "short": "SHORT · SAT"}
STATE_TEXT = {"open": "stop önde", "passed": "stop geçildi", "nostop": "stopsuz", "unvalued": "değerlenemedi",
              "unknown": "seviye okunamadı"}


class PropError(ValueError):
    """What cannot be worked out, said in Turkish (an HTTP 400)."""


# ---------------------------------------------------------------------------------------------- reading what is typed
def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _f(v: Any) -> Optional[float]:
    """A finite number, or ``None``."""
    return tbm._f(v)


def read_ccy(v: Any, what: str = "Döviz") -> str:
    s = str(v or "").strip().upper()
    s = "TRY" if s in ("TL", "₺") else s
    if s not in CCYS:
        raise PropError("%s TRY ya da USD olmalı" % what)
    return s


def read_pair(v: Any) -> str:
    """"usdtry" / "USD/TRY" / "gbp" (against TL) -> the pair's code (tradebook.pair_of)."""
    if _blank(v):
        raise PropError("parite yazın (örn. USDTRY)")
    pair = tbm.pair_of(v)
    if pair is None:
        raise PropError("parite anlaşılamadı: %s" % str(v).strip())
    return pair


def read_price(v: Any, what: str, lang: str = "tr") -> float:
    """A price level as the user types it, in their number format ("44,55"; a lone "44.550" is a decimal too)."""
    if _blank(v):
        raise PropError("%s gerekli" % what)
    x = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else parse_number(str(v), lang, prefer_decimal=True)
    if x is None or not math.isfinite(x):
        raise PropError("%s anlaşılamadı: %s" % (what, str(v).strip()))
    if x <= 0:
        raise PropError("%s sıfırdan büyük olmalı" % what)
    return x


def read_amount(v: Any, what: str, lang: str = "tr") -> float:
    """An amount with the dashboard's shorthand: "500k", "1mn", "2,5mn" (inputs.parse_amount)."""
    if _blank(v):
        raise PropError("%s gerekli" % what)
    x = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else parse_amount(str(v), lang)
    if x is None or not math.isfinite(x):
        raise PropError("%s anlaşılamadı: %s (örn. 500k, 1mn, 2,5mn)" % (what, str(v).strip()))
    if x <= 0:
        raise PropError("%s sıfırdan büyük olmalı" % what)
    return x


# ---------------------------------------------------------------------------------------------- prices
def spot_of(mkt: Any, pair: str) -> Tuple[Optional[float], str]:
    """A pair's price on the market snapshot and where it comes from: the Forward sheet's USDTRY / EURTRY, the quant
    package's FX series, crosses through USD (tradevalue.Market.spot) - else the cross of two TL prices."""
    pair = pair.upper()
    v = mkt.spot(pair)
    if v:
        if pair in mkt.spots:
            how = "Forward sayfası" if pair in ("USDTRY", "EURTRY") else "quant FX verisi"
        elif pair[3:] + pair[:3] in mkt.spots:
            how = "ters kur"
        else:
            how = "çapraz kur (USD üzerinden)"
        return v, how
    a, b = mkt.try_per(pair[:3]), mkt.try_per(pair[3:])
    if a and b:
        return a / b, "çapraz kur (%sTRY / %sTRY)" % (pair[:3], pair[3:])
    return None, "fiyat yok"


def convert(mkt: Any, amount: Optional[float], frm: str, to: str) -> Optional[float]:
    """``amount`` of ``frm`` in ``to`` at today's rates (the pair ``frm``+``to`` as the market prices it: direct, inverse
    or through USD); ``None`` when there is no rate."""
    if amount is None:
        return None
    if frm == to:
        return amount
    r = mkt.spot(frm + to)
    return amount * r if r else None


def decimals_of(pair: str) -> int:
    known = next((p.decimals for p in fxm.PAIRS if p.code == pair), None)
    return known if known is not None else (3 if pair.endswith("JPY") else 4)


# ---------------------------------------------------------------------------------------------- the calculator
def size(mkt: Any, pair: str, stop: float, loss: float, loss_ccy: str, entry: Optional[float] = None) -> Dict[str, Any]:
    """The position that loses at most ``loss`` (``loss_ccy``) when ``pair`` goes from the entry to ``stop``: its
    direction, the distance, the size rounded down to 1M of the base currency, the real loss at that size and the loss
    of 1M - each amount in the quote currency, the loss's, TL and USD."""
    pair = pair.upper()
    base, quote = pair[:3], pair[3:]
    mid, how = spot_of(mkt, pair)
    if mid is None:
        raise PropError("%s: canlı fiyat yok (panoda bu paritenin fiyatı yok)" % pair)
    e = mid if entry is None else float(entry)
    if stop == e:
        raise PropError("stop girişe eşit olamaz: yön stoptan okunur (girişin altında long, üstünde short)")
    direction = "long" if stop < e else "short"
    dist = abs(e - stop)
    loss_q = convert(mkt, loss, loss_ccy, quote)
    if loss_q is None:
        raise PropError("kayıp %s'den %s'ye çevrilemedi: kur yok" % (loss_ccy, quote))
    raw = loss_q / dist
    x = raw / LOT
    lots = int(math.floor(x + _EPS * max(1.0, x)))

    def money(q: float) -> Dict[str, Optional[float]]:
        return {"quote": q, "ccy": convert(mkt, q, quote, loss_ccy), "try": convert(mkt, q, quote, "TRY"),
                "usd": convert(mkt, q, quote, "USD")}

    pip = tbm.pip_of(pair)
    out: Dict[str, Any] = {
        "pair": pair, "base": base, "quote": quote, "decimals": decimals_of(pair), "mid": mid, "mid_how": how,
        "entry": e, "entry_typed": entry is not None, "stop": stop, "direction": direction,
        "direction_text": DIRECTION_TEXT[direction], "distance": dist, "distance_pct": dist / e * 100.0,
        "pip": pip, "pips": dist / pip, "kurus": dist * 100.0 if quote == "TRY" else None,
        "loss": loss, "loss_ccy": loss_ccy, "loss_quote": loss_q, "size_raw": raw, "lots": lots, "size": lots * LOT,
        "under_1m": lots == 0, "per_1m": money(LOT * dist), "real_loss": money(lots * LOT * dist) if lots else None,
        "usdtry": mkt.spot("USDTRY")}
    per = out["per_1m"]["ccy"]
    if lots:
        out["note"] = "%s %dM %s · gerçek kayıp %s %s" % (DIRECTION_TEXT[direction], lots, base,
                                                          tbm._tr(out["real_loss"]["ccy"] or 0.0, 0), loss_ccy)
    else:
        out["note"] = "1M bile %s %s kaybı aşıyor: 1M'de kayıp %s %s" % (tbm._tr(loss, 0), loss_ccy,
                                                                       tbm._tr(per or 0.0, 0), loss_ccy)
    return out


# ---------------------------------------------------------------------------------------------- one trade's risk
def _money(mkt: Any, amount: Optional[float], ccy: str) -> Dict[str, Any]:
    return {"ccy": ccy, "amount": amount, "try": convert(mkt, amount, ccy, "TRY"), "usd": convert(mkt, amount, ccy, "USD")}


def _zero(ccy: str) -> Dict[str, Any]:
    return {"ccy": ccy, "amount": 0.0, "try": 0.0, "usd": 0.0}


def sensitivity(t: Dict[str, Any], v: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the trade's value does for one unit of its level (tradebook.level_spec): ``per`` (unsigned) in ``ccy``,
    ``kind`` ("dv01" / "nominal" / "size" / "premium"), ``dv01`` (a bp, rates and bonds) - from its valuation."""
    p, st = t.get("product"), t.get("structure") or "outright"
    inputs = v.get("inputs") or {}
    ccy = str(v.get("ccy") or "")
    if p in ("ois", "sofr"):
        if st in ("spread", "fly"):
            legs = [abs(x) for x in (inputs.get("legs_dv01") or []) if _f(x) is not None]
            if not legs:
                return None
            dv01 = 0.5 * sum(legs)                               # (the level's: the long leg's / body's, DV01-weighted)
            return {"kind": "dv01", "per": dv01, "dv01": dv01, "ccy": ccy, "what": "seviyenin DV01'i (bacakların yarı toplamı)"}
        dv01 = _f(inputs.get("dv01"))
        if dv01 is None:
            return None
        return {"kind": "dv01", "per": abs(dv01) * 100.0, "dv01": abs(dv01), "ccy": ccy, "what": "DV01"}
    if p == "dibs":
        dv01 = _f(inputs.get("dv01"))
        if t.get("price_kind") == "yield":
            if dv01 is None:
                return None
            return {"kind": "dv01", "per": abs(dv01) * 100.0, "dv01": abs(dv01), "ccy": "TRY", "what": "DİBS RV DV01'i (basit getiri)"}
        n = _f(t.get("notional"))
        if n is None:
            return None
        return {"kind": "nominal", "per": abs(n) / 100.0, "dv01": abs(dv01) if dv01 is not None else None, "ccy": "TRY",
                "what": "nominal / 100 (fiyat puanı)"}
    if p == "fxspot":
        base = _f(inputs.get("base_amount"))
        if base is None:
            return None
        return {"kind": "size", "per": abs(base), "ccy": ccy, "base": str(t.get("pair") or "")[:3],
                "what": "tutar (%s)" % str(t.get("pair") or "")[:3]}
    if p == "fxopt":
        pccy = str(inputs.get("premium_ccy") or t.get("premium_ccy") or ccy)
        return {"kind": "premium", "per": 1.0, "ccy": pccy, "what": "prim tutarı"}
    return None


def _spot_at_stop(t: Dict[str, Any], v: Dict[str, Any], stop: float, now: float) -> Optional[float]:
    """An FX option's spot where its premium would be the stop, from its delta (first order: vol and time held)."""
    inputs, greeks = v.get("inputs") or {}, v.get("greeks") or {}
    S, delta = _f(inputs.get("spot")), _f(greeks.get("delta"))
    prem, prem_q = _f(inputs.get("premium")), _f(inputs.get("premium_quote"))
    if S is None or not delta or not prem or not prem_q:
        return None
    sign = 1.0 if t.get("side") == "B" else -1.0
    slope = sign * delta * prem / prem_q                     # (the premium's change in its currency for 1 of the spot)
    if abs(slope) < 1e-12:
        return None
    return S + (stop - now) / slope


def exposure(t: Dict[str, Any], v: Dict[str, Any], mkt: Any, sens: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What a trade without a stop is exposed to: its DV01 (a bp), its size (FX spot) or its delta (an option, approximate)."""
    p = t.get("product")
    if p == "fxopt":
        d = _f((v.get("greeks") or {}).get("delta"))
        base = str(t.get("pair") or "")[:3]
        if d is None:
            return None
        return dict(_money(mkt, d, base), kind="delta", what="delta (yaklaşık)", approx=True)
    if p == "fxspot":
        base = _f((v.get("inputs") or {}).get("base_amount"))
        if base is None:
            return None
        sign = 1.0 if t.get("side") == "B" else -1.0
        return dict(_money(mkt, sign * base, str(t.get("pair") or "")[:3]), kind="size", what="tutar")
    if sens is not None and sens.get("dv01") is not None:
        return dict(_money(mkt, sens["dv01"], sens["ccy"]), kind="dv01", what="DV01 (1 bp)")
    if p == "dibs" and _f(t.get("notional")) is not None:
        return dict(_money(mkt, _f(t.get("notional")), "TRY"), kind="nominal", what="nominal")
    return None


def position(t: Dict[str, Any], v: Dict[str, Any], mkt: Any) -> Dict[str, Any]:
    """One open trade against its stop: the level now and the stop in its own unit, the distance (``to_stop``,
    tradebook.levels_of: positive while still ahead), the sensitivity, and ``loss`` - what hitting the stop would lose
    (``state`` "open"), nothing for a stop already passed ("passed": ``beyond``, what lies past it, is lost already) -
    in the trade's currency, TL and USD; a trade without a stop ("nostop") its ``exposure``."""
    spec = tbm.level_spec(t) or {}
    stop = _f(t.get("stop"))
    out: Dict[str, Any] = {"id": t.get("id"), "product": t.get("product"), "product_text": tbm.PRODUCT_TEXT.get(t.get("product"), ""),
                           "stop": stop, "target": _f(t.get("target")), "level_what": spec.get("what"),
                           "level_short": spec.get("short"), "unit": spec.get("unit"), "digits": spec.get("digits")}
    if not v.get("ok"):
        out.update(state="unvalued", why=str(v.get("why") or "değer yok"))
        return out
    now = tbm.level_now(t, v)
    sens = sensitivity(t, v)
    out.update(now=now, sens=sens)
    if stop is None:
        out.update(state="nostop", exposure=exposure(t, v, mkt, sens))
        return out
    up = tbm.gains_up(t)
    if now is None or up is None or sens is None:
        out.update(state="unknown", why="seviyesi ya da duyarlılığı okunamadı")
        return out
    gap = (now - stop) * (1.0 if up else -1.0)               # (level units: > 0 the stop is still ahead)
    lv = tbm.levels_of(t, now) or {}
    out["to_stop"] = lv.get("to_stop")
    amount = sens["per"] * abs(gap)
    if gap > 0:
        out.update(state="open", loss=_money(mkt, amount, sens["ccy"]))
    else:
        out.update(state="passed", loss=_zero(sens["ccy"]), beyond=_money(mkt, amount, sens["ccy"]))
    if t.get("product") == "fxopt":
        out["spot_at_stop"] = _spot_at_stop(t, v, stop, now)
        out["approx"] = "yaklaşık (delta)"
    return out


def room(limit: Optional[float], pnl: Optional[float], stops: Optional[float]) -> Optional[float]:
    """limit − max(0, −K/Z) − loss at the stops, in one currency: a gain gives no room; ``None`` without any of them."""
    if limit is None or pnl is None or stops is None:
        return None
    return limit - max(0.0, -pnl) - stops


# ---------------------------------------------------------------------------------------------- the service's part
class Prop(object):
    """The panel's answers for a signed-in user (one per service)."""

    def __init__(self, svc: Any):
        self.svc = svc
        self._mkt: Optional[Tuple[float, Any]] = None

    # ------------------------------------------------------------------ the market
    def market(self) -> Any:
        """The valuation's market snapshot (tradevalue.market, Bootstrap), at most ``MARKET_SECONDS`` old."""
        hit = self._mkt
        if hit is not None and time.monotonic() - hit[0] < MARKET_SECONDS:
            return hit[1]
        mkt = tv.market(self.svc)
        self._mkt = (time.monotonic(), mkt)
        return mkt

    def desk_pairs(self) -> List[str]:
        """The desk's FX pairs: the quant setting's list (quant.fx_pair_list), then the Spot / FX board's others."""
        from . import quant as qm
        out = list(qm.fx_pair_list(self.svc.store))
        fx = getattr(self.svc, "fx", None)
        for p in (fx.pairs() if fx is not None else fxm.PAIRS):
            if p.code not in out:
                out.append(p.code)
        return out

    # ------------------------------------------------------------------ the calculator
    def state(self, user: Optional[str]) -> Dict[str, Any]:
        """What the panel opens with: the desk's pairs that have a price (each with its mid), the user's limit."""
        key = self.svc.require_user(user)
        mkt = self.market()
        pairs = []
        for code in self.desk_pairs():
            mid, how = spot_of(mkt, code)
            if mid:
                pairs.append({"pair": code, "mid": mid, "how": how, "decimals": decimals_of(code), "pip": tbm.pip_of(code)})
        return {"pairs": pairs, "limit": self.limit(key), "lot": LOT, "ccys": list(CCYS),
                "today": mkt.today.isoformat() if getattr(mkt, "today", None) else None}

    def calc(self, user: Optional[str], query: Optional[Dict[str, Any]], lang: str = "tr") -> Dict[str, Any]:
        """The calculator's answer for what the panel holds (``pair``, ``stop``, ``loss``, ``ccy``, ``entry``)."""
        self.svc.require_user(user)
        q = query or {}
        pair = read_pair(q.get("pair"))
        if pair not in self.desk_pairs():
            raise PropError("%s masanın FX listesinde yok (Spot / FX ve quant pariteleri)" % pair)
        stop = read_price(q.get("stop"), "Stop", lang)
        loss = read_amount(q.get("loss"), "Kayıp", lang)
        ccy = read_ccy(q.get("ccy"), "Kaybın dövizi")
        entry = None if _blank(q.get("entry")) else read_price(q.get("entry"), "Giriş", lang)
        return size(self.market(), pair, stop, loss, ccy, entry)

    # ------------------------------------------------------------------ the limit
    def limit(self, key: str) -> Optional[Dict[str, Any]]:
        """The user's daily loss limit ``{amount, ccy, at}`` (``None``: none)."""
        v = self.svc.store.get(LIMIT_KEY + key)
        if not isinstance(v, dict) or _f(v.get("amount")) is None or v.get("ccy") not in CCYS:
            return None
        return {"amount": float(v["amount"]), "ccy": v["ccy"], "at": v.get("at")}

    def set_limit(self, user: Optional[str], amount: Any, ccy: Any, lang: str = "tr") -> Dict[str, Any]:
        """The user's own daily loss limit, typed ("1mn", "250k") with its currency; empty: none."""
        key = self.svc.require_user(user)
        if _blank(amount):
            self.svc.store.put(LIMIT_KEY + key, None)
            return {"limit": None}
        x = read_amount(amount, "Günlük kayıp limiti", lang)
        c = read_ccy(ccy, "Limitin dövizi")
        self.svc.store.put(LIMIT_KEY + key, {"amount": x, "ccy": c, "at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        return {"limit": self.limit(key)}

    # ------------------------------------------------------------------ the risk
    def risk(self, user: Optional[str], scope: Any = None) -> Dict[str, Any]:
        """The prop risk of a Trades tab (``scope``: "personal" - the default - or "desk"): every open trade against its
        stop, the tab's "Günlük" K/Z as the page shows it, the user's limit and the room left, in TL and USD."""
        key = self.svc.require_user(user)
        book = self.svc.tradebook
        listing = book.listing(key, scope or "personal")        # (the Trades page's own answer: who sees what, its MTM)
        mkt = self.market()
        rows = []
        for it in listing["open"]:
            t = tbm.TradeBook.for_value(it["fields"])
            try:
                v = tv.value(t, mkt)
            except Exception as exc:  # noqa: BLE001 - one trade that cannot be valued leaves the others
                v = {"ok": False, "why": "değerleme hatası: %s" % (str(exc)[:200] or type(exc).__name__)}
            row = position(t, v, mkt)
            row["text"] = it.get("text") or tbm.describe(t)
            rows.append(row)
        # Stoplar: the stops still ahead (a stop passed adds nothing); a trade with a stop that could not be measured is
        # counted as unknown - the sum leaves it out and says so
        stops: Dict[str, Any] = {"try": 0.0, "usd": 0.0, "count": 0, "passed": 0, "unknown": 0}
        for r in rows:
            if r["state"] == "open" and r["loss"]["try"] is not None and r["loss"]["usd"] is not None:
                stops["count"] += 1
                stops["try"] += r["loss"]["try"]
                stops["usd"] += r["loss"]["usd"]
            elif r["state"] == "passed":
                stops["passed"] += 1
            elif r["state"] != "nostop" and r.get("stop") is not None:
                stops["unknown"] += 1
        pnl = self._pnl(listing, book)
        for k in ("try", "usd"):
            pnl["used_" + k] = max(0.0, -pnl[k]) if pnl[k] is not None else None
        lim = self.limit(key)
        limit = None
        if lim is not None:
            limit = dict(lim, **{"try": convert(mkt, lim["amount"], lim["ccy"], "TRY"),
                                 "usd": convert(mkt, lim["amount"], lim["ccy"], "USD")})
        left: Dict[str, Any] = {"try": None, "usd": None, "why": None}
        if limit is None:
            left["why"] = "günlük kayıp limiti yok"
        elif pnl["try"] is None:
            left["why"] = pnl["why"]
        else:
            for k in ("try", "usd"):
                left[k] = room(limit[k], pnl[k], stops[k])
        order = {"open": 0, "passed": 1, "unknown": 2, "unvalued": 3, "nostop": 4}
        rows.sort(key=lambda r: (order.get(r["state"], 9), -((r.get("loss") or {}).get("try") or 0.0)))
        return {"scope": listing["scope"], "scope_text": tbm.SCOPE_TEXT[listing["scope"]], "today": pnl["today"],
                "limit": limit, "pnl": pnl, "stops": stops, "room": left,
                "trades": [r for r in rows if r["state"] != "nostop"], "nostop": [r for r in rows if r["state"] == "nostop"],
                "usdtry": mkt.spot("USDTRY"), "curve": "Bootstrap (Murex)",
                "at": _dt.datetime.now().strftime("%H:%M:%S")}

    @staticmethod
    def _pnl(listing: Dict[str, Any], book: Any) -> Dict[str, Any]:
        """The tab's "Günlük" (TL, USD) as the Trades page shows it: the totals of its last "MTM yenile" (the viewer's
        curve) - when that was today."""
        today = book.now().date().isoformat()
        snap = listing.get("mtm")
        out: Dict[str, Any] = {"try": None, "usd": None, "today": today, "at": None, "why": None, "missing": 0, "stale": False}
        if not snap:
            out["why"] = "bu sekmede \"MTM yenile\" yapılmadı: bugünkü K/Z bilinmiyor"
            return out
        at = str(snap.get("at") or "")
        out.update(at=at, stale=bool(snap.get("stale")), by_name=snap.get("by_name"), curve_text=snap.get("curve_text"))
        if at[:10] != today:
            out["why"] = "son \"MTM yenile\" bugünün değil (%s): bugünkü K/Z bilinmiyor" % tbm._day_text(at[:10])
            return out
        every = (snap.get("totals") or {}).get("all") or {}
        missing = every.get("missing") or {}
        n = int(every.get("count") or 0) + int(every.get("closed") or 0)
        for k in ("try", "usd"):
            x = _f(every.get("day.pnl." + k))
            out[k] = x if x is not None else (0.0 if not missing.get("day.pnl." + k) else None)
        out["missing"] = int(missing.get("day.pnl.try") or 0)
        if out["try"] is None:
            out["why"] = "sekmenin hiçbir işleminin günlük K/Z'ı bilinmiyor" if n else None
        return out
