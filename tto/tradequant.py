"""Trades · the quant lines (tto/quant.py): "İşleme al" - a line of the quant list as a trade of Trades, its form filled
- and the "Quant'tan" table: per family, the trades taken from its lines and what they made.

**Which lines Trades can book** (:func:`bookable`; every line of a quant answer says it - ``book: {ok, why, kind}``,
:func:`mark`): TRY OIS outright (one leg, its level the rate), spread (two legs 1:1 in DV01, opposite sides, its level long
− short in bp), fly (three legs 50/50 - the wings ½ each on one side, the body on the other -, its level body − ½ each
wing: the Trades fly's), FRA (the universe's m×n FRA, its forward rate; the FRA / PPK patikası line's FRA at its rate -
its quote, ``quantfam.inst_quote``), a PPK period (its meeting by its date; a line telling a period's rate as its quote too),
a DİBS bond alone (its yield), an FX spot (a G10 pair's, Opsiyon → spot's spot lines - USDTRY / EURTRY among them).  Not: a vol
trade, VİOP, Offshore (forwards, swap points, the offshore curve: "offshore limiti"), an FX forward, a correlation line,
a package weighted otherwise (PCA, a hedge: its level is no Trades package's), a DİBS switch or a bond hedged with OIS -
each with its reason.

**The form** (:func:`prefill`): the line as the server has it now (looked up by its id - never what a page sent):
product, structure and legs, side (a swap's receive / pay - tradevalue keeps them as "S" / "B"), the size - a rates line
its DV01 (1.000 $ of the desk's unit × the line's size), turned into a nominal on the desk's 5 mn lot as the form turns a
DV01 (``TradeBook.normalize``); an FX line 1 mn of the base × its size -, the trade price = the line's entry now (a spread's
/ fly's legs at the curve's rates, the long leg / body set so the package is the entry), target and stop = the line's (an
FX line's in prices: ``px``; a level of the model's own in the instrument's: ``quote`` - the FRA / PPK line's FRA rates),
and where it came from (``source``).  Nothing is saved: the page opens the Trades form.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import tradevalue as tv
from .service import ServiceError

_OIS = re.compile(r"^OIS:(\d{1,2})([WMY])$")
_FRA = re.compile(r"^FRA:(\d{1,2})x(\d{1,2})$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: a rates line's DV01 when its legs do not say (the desk's unit: 1.000 $)
UNIT_DV01 = 1000.0
#: an FX line's size: this much of the base currency × the line's size (``info.k``)
FX_UNIT = 1e6


def _f(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _legs(line: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [lg for lg in line.get("legs") or [] if isinstance(lg, dict)]


def _months(key: str) -> float:
    m = _OIS.match(key)
    if not m:
        return 1e9
    n = float(m.group(1))
    return n * {"W": 12.0 / 52.0, "M": 1.0, "Y": 12.0}[m.group(2)]


def _ordered(legs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A package's legs short → long, as Trades keeps them."""
    return sorted(legs, key=lambda lg: _months(str(lg.get("key") or "")))


def _shape(line: Dict[str, Any], legs: Sequence[Dict[str, Any]]) -> Optional[str]:
    """What TRY OIS legs are in Trades: an outright, a 1:1 spread, a 50/50 fly - ``None`` for any other weighting."""
    unit = line.get("unit")
    if len(legs) == 1:
        return "outright" if unit == "%" else None
    if unit != "bp":
        return None
    lg = _ordered(legs)
    w = [abs(_f(x.get("weight")) or 0.0) for x in lg]
    sd = [x.get("side") for x in lg]
    if any(s not in (1, -1) for s in sd):
        return None
    if len(lg) == 2 and all(abs(x - 1.0) < 1e-6 for x in w) and sd[0] == -sd[1]:
        return "spread"
    if len(lg) == 3 and abs(w[0] - 0.5) < 1e-6 and abs(w[1] - 1.0) < 1e-6 and abs(w[2] - 0.5) < 1e-6 and sd[0] == sd[2] == -sd[1]:
        return "fly"
    return None


def bookable(line: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Whether Trades can book a quant line as one trade: ``(ok, why not, kind)`` - kind "outright", "spread", "fly",
    "fra", "mpc", "dibs" or "fxspot"."""
    legs = _legs(line)
    keys = [str(lg.get("key") or "") for lg in legs]
    uni = str((line.get("info") or {}).get("universe") or "")
    asset, fam, unit = str(line.get("asset") or ""), str(line.get("family") or ""), str(line.get("unit") or "")

    def no(why: str) -> Tuple[bool, str, Optional[str]]:
        return False, why, None

    if not legs or line.get("direction") not in (1, -1):
        return no("işlemin bacağı / yönü yok")
    if fam == "corr" or unit == "ρ":
        return no("korelasyon işlemi: Trades'te karşılığı yok")
    if asset == "FX vol" or any(k.startswith(("FXV:", "FXR:", "FXB:", "OPT:")) for k in keys):
        return no("vol işlemi (opsiyon stratejisi): Trades'e tek işlem olarak girilmez")
    if asset == "VİOP" or any(k.startswith(("VIOP", "VQM:")) for k in keys):
        return no("VİOP: Trades'te VİOP ürünü yok")
    if len(keys) == 1 and re.match(r"^FX:[A-Z]{6}$", keys[0]):
        px = line.get("px") or {}
        inst = str(px.get("inst") or legs[0].get("name") or "")
        if inst.endswith(" spot") and _f(px.get("entry")) is not None:
            return True, "", "fxspot"
        return no("%s: Trades'te FX forward yok - yalnızca spot" % (inst or "FX forward"))
    if asset == "Offshore" or any(k.startswith(("OFF:", "FXP:", "FWD:")) for k in keys):
        return no("offshore (offshore limiti): Trades'te offshore ürünü yok")
    if _FRA.match(uni) and unit == "%":
        return True, "", "fra"
    # a level of the model's own told in the traded instrument's (quantfam.inst_quote): the FRA / PPK line is its FRA at its
    # rate, a meeting's period line its period at its rate - booked as the universe's lines are
    quote = line.get("quote") if isinstance(line.get("quote"), dict) else {}
    if quote.get("unit") == "%" and _FRA.match("FRA:" + str(quote.get("fra") or "")) and keys and all(_OIS.match(k) for k in keys):
        return True, "", "fra"
    if len(keys) == 1 and keys[0].startswith("MPC:") and _ISO.match(keys[0][4:]) and (unit == "%" or quote.get("unit") == "%"):
        return True, "", "mpc"
    if keys and all(k.startswith("DIBS:") for k in keys):
        if len(keys) == 1 and unit == "%":
            return True, "", "dibs"
        return no("DİBS paketi (switch / hedge'li): Trades'e tek işlem olarak girilmez")
    if keys and all(_OIS.match(k) for k in keys):
        shape = _shape(line, legs)
        if shape:
            return True, "", shape
        return no("paket Trades'in spread (1:1) / fly (50/50) yapısında değil (PCA ya da hedge ağırlıklı): bacakları ayrı girin")
    if any(k.startswith("DIBS:") for k in keys):
        return no("kâğıt + OIS hedge'li paket: Trades'e tek işlem olarak girilmez")
    return no("Trades bu enstrümanı giremez")


def book_of(line: Dict[str, Any]) -> Dict[str, Any]:
    ok, why, kind = bookable(line)
    return {"ok": ok, "why": why, "kind": kind}


def mark(out: Any) -> Any:
    """A quant answer's lines, each with whether Trades can book it (``book``) - the lists of a page, of a box and the
    card of one line (in place; the answer is the view's own copy)."""
    if not isinstance(out, dict):
        return out
    for key in ("signals", "gated", "list"):
        for s in out.get(key) or ():
            if isinstance(s, dict) and "legs" in s and "family" in s:
                s["book"] = book_of(s)
    sig = out.get("signal")
    if isinstance(sig, dict) and "legs" in sig:
        sig["book"] = book_of(sig)
    return out


def find_line(svc: Any, line_id: str) -> Optional[Dict[str, Any]]:
    """A line of the quant list as the server has it now (its last fit with the minute's live values)."""
    view = getattr(getattr(svc, "quant", None), "_view", None) or {}
    for key in ("list", "signals", "gated"):
        for s in view.get(key) or ():
            if isinstance(s, dict) and s.get("id") == line_id:
                return s
    return None


# ---------------------------------------------------------------------------------------------- the form
def _r(v: Any, digits: int) -> Optional[float]:
    x = _f(v)
    return round(x, digits) if x is not None else None


def _dv01(lg: Dict[str, Any]) -> float:
    d = _f(lg.get("dv01_usd"))
    return float(round(d)) if d else UNIT_DV01


def _side_word(s: Any) -> str:
    """A rates leg's side: the quant's +1 is its up verb (pay), −1 receive."""
    return "pay" if s == 1 else "receive"


def _par(book: Any, mkt: Any, tenor: str, today: str, settle: Optional[str]) -> Optional[float]:
    """The curve's rate now of a TRY OIS from the spot to a tenor (what MTM reads its par as)."""
    probe = {"product": "ois", "structure": "outright", "trade_date": today, "settle_date": settle, "value_date": settle,
             "side": "S", "tenor": tenor, "end_date": None, "notional": 1e6, "price": 0.0}
    try:
        v = tv.value(probe, mkt)
    except Exception:  # noqa: BLE001
        return None
    return _f(v.get("price_now")) if v.get("ok") else None


def _conv(mkt: Any, isin: str, level: Optional[float]) -> str:
    """A DİBS line's yield convention by DİBS RV's two yields now: "basit" or "bileşik" (the closer one)."""
    row = (getattr(mkt, "bonds", None) or {}).get(isin) or {}
    simple, compound = _f(row.get("simple")), _f(row.get("compound"))
    if level is None or simple is None or compound is None:
        return "bileşik"
    return "bileşik" if abs(level - compound * 100.0) <= abs(level - simple * 100.0) else "basit"


def raw_form(book: Any, user: str, line: Dict[str, Any], scope: str, kind: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The Trades form of a bookable line, as the page would send it, and its ``source``."""
    legs = _legs(line)
    info = line.get("info") or {}
    today = book._today().isoformat()
    s = 1 if line.get("direction") == 1 else -1
    raw: Dict[str, Any] = {"scope": scope, "trade_date": today}
    entry, target, stop = _f(line.get("entry")), _f(line.get("target")), _f(line.get("stop"))
    quote = line.get("quote") if isinstance(line.get("quote"), dict) and kind in ("fra", "mpc") else None
    if quote is not None and quote.get("unit") == "%":
        # (a level of the model's own: the instrument's rate - the FRA's, its target and stop the rates where the model's
        # gap is theirs on today's model value, quantfam.inst_quote)
        entry, target, stop = _f(quote.get("entry")), _f(quote.get("target")), _f(quote.get("stop"))
    if kind == "fxspot":
        px = line.get("px") or {}
        pair = str(px.get("pair") or legs[0]["key"][3:]).upper()
        d = int(px.get("digits") or 4)
        entry, target, stop = _r(px.get("entry"), d), _r(px.get("target"), d), _r(px.get("stop"), d)
        k = _f(info.get("k")) or 1.0
        dflt = book.defaults(user, "fxspot", pair=pair, trade_date=today)
        raw.update(product="fxspot", pair=pair, side="B" if s > 0 else "S", amount_typed="base",
                   notional=max(0.1, round(k, 1)) * FX_UNIT, price=entry, settle_date=dflt.get("settle_date"))
    elif kind == "dibs":
        isin = legs[0]["key"][5:].upper()
        entry, target, stop = _r(entry, 4), _r(target, 4), _r(stop, 4)
        dflt = book.defaults(user, "dibs", isin=isin, trade_date=today)
        mkt = book._form_market()
        # (the quant's up side sells the bond: it gains when the yield rises)
        raw.update(product="dibs", isin=isin, side="S" if legs[0].get("side") == 1 else "B", price_kind="yield", price=entry,
                   yield_conv=_conv(mkt, isin, entry), sized_by="dv01", dv01=_dv01(legs[0]), dv01_ccy="USD",
                   settle_date=dflt.get("settle_date"))
    else:
        structure = {"outright": "outright", "spread": "spread", "fly": "fly", "fra": "fra", "mpc": "mpc"}[kind]
        q: Dict[str, Any] = {"structure": structure, "trade_date": today}
        if kind == "fra":
            m = _FRA.match(str(info.get("universe") or "")) or _FRA.match("FRA:" + str((quote or {}).get("fra") or ""))
            q["fra"] = "%sx%s" % (m.group(1), m.group(2))
        dflt = book.defaults(user, "ois", **q)
        raw.update(product="ois", structure=structure, settle_date=dflt.get("settle_date"))
        if kind in ("outright", "fra", "mpc"):
            entry, target, stop = _r(entry, 4), _r(target, 4), _r(stop, 4)
            if kind == "fra":
                dv = abs(sum((lg.get("side") or 0) * (_f(lg.get("dv01_usd")) or 0.0) for lg in legs)) or UNIT_DV01
                raw.update(fra=q["fra"], side=_side_word(s), dv01=float(round(dv)))
            else:
                raw.update(side=_side_word(legs[0].get("side")), dv01=_dv01(legs[0]))
                if kind == "outright":
                    raw.update(end_date=legs[0]["key"][4:], value_date=dflt.get("value_date") or dflt.get("settle_date"))
                else:
                    raw["mpc_date"] = legs[0]["key"][4:]
            raw.update(sized_by="dv01", dv01_ccy="USD", price=entry)
        else:
            entry, target, stop = _r(entry, 2), _r(target, 2), _r(stop, 2)
            lg = _ordered(legs)
            settle = dflt.get("value_date") or dflt.get("settle_date")
            mkt = book._form_market()
            rates = [_par(book, mkt, x["key"][4:], today, settle) for x in lg]
            if any(r is None for r in rates) or entry is None:
                raise ServiceError("bacakların eğrideki oranı bulunamadı: formu elle doldurun")
            # the legs at the curve's rates, the long leg / the body set so that the package is the line's entry
            if kind == "spread":
                rates[1] = rates[0] + entry / 100.0
            else:
                rates[1] = entry / 100.0 + 0.5 * (rates[0] + rates[2])
            raw.update(value_date=settle, dv01=max(_dv01(x) for x in lg), dv01_ccy="USD",
                       weights=[1.0, 1.0] if kind == "spread" else [0.5, 1.0, 0.5],
                       legs=[{"side": _side_word(x.get("side")), "end_date": x["key"][4:], "sized_by": "dv01", "dv01": _dv01(x),
                              "dv01_ccy": "USD", "price": round(r, 4)} for x, r in zip(lg, rates)])
    raw["target"], raw["stop"] = target, stop
    source = {"kind": "quant", "family": str(line.get("family") or ""), "family_label": str(line.get("family_label") or ""),
              "line_id": str(line.get("id") or ""), "at": book.now().strftime("%Y-%m-%d %H:%M"),
              "instrument": str((quote or {}).get("inst") or line.get("instrument") or ""), "entry": entry, "target": target, "stop": stop,
              "unit": str((line.get("px") or {}).get("unit") or (quote or {}).get("unit") or line.get("unit") or "")}
    raw["source"] = source
    return raw, source


def prefill(svc: Any, user: Optional[str], line_id: Any, scope: Any = "personal", lang: str = "tr") -> Dict[str, Any]:
    """"İşleme al": the Trades form of a quant line - ``{ok, trade, text, fields (what does not read), source, scope,
    line}``; nothing is saved (the page opens the form with it)."""
    from .tradebook import describe
    book = svc.tradebook
    user = book._user(user)
    scope = book._scope(scope or "personal")
    line = find_line(svc, str(line_id or ""))
    if line is None:
        raise ServiceError("sinyal listede yok (liste yenilenmiş olabilir): %s" % str(line_id)[:80], 404)
    ok, why, kind = bookable(line)
    if not ok:
        raise ServiceError("bu sinyal Trades'e alınamaz: %s" % why)
    raw, source = raw_form(book, user, line, scope, kind)
    t, f = book.normalize(raw, lang)
    trade = t if not f.errors else dict(raw, **{k: v for k, v in t.items() if v is not None})
    trade.pop("scope", None)
    word = "PPK" if trade.get("product") == "ois" else "FOMC"
    return {"ok": not f.errors, "trade": trade, "fields": f.errors, "text": describe(t, word) if not f.errors else "",
            "source": source, "scope": scope, "kind": kind,
            "line": {"id": line.get("id"), "family": line.get("family"), "family_label": line.get("family_label"),
                     "text": line.get("line") or line.get("expression") or "", "instrument": line.get("instrument")}}


# ---------------------------------------------------------------------------------------------- "Quant'tan"
def table(book: Any, user: Optional[str]) -> Dict[str, Any]:
    """The trades taken from the quant lines that the user sees - the desk's and their own -, per family: how many (the
    desk's / their own), open and closed, the P&L in TL (an open one's since its inception, valued now; a closed one's
    realised) - total and average -, and how the closed ones ended: at the target, at the stop, otherwise."""
    from .tradebook import hit_of, on_curve, _f as num
    user = book._user(user)
    rows = [r for r in book.store.tb_list("desk") + book.store.tb_list("personal", user)
            if (r.get("source") or {}).get("kind") == "quant"]
    open_rows = [r for r in rows if r["status"] != "closed"]
    closed_rows = [r for r in rows if r["status"] == "closed"]
    now = book.now()
    curve = book.curve_of(user)                   # (the trades as the viewer sees them: their curve setting)

    def run() -> Dict[int, Dict[str, Any]]:
        mkt = tv.market(book.svc, curve) if curve != "boot" else tv.market(book.svc)
        return {r["id"]: book._value(book.for_value(r), mkt) for r in open_rows}

    vals = book._engine(run) if open_rows else {}
    res = book._results(open_rows, vals, now, curve=curve) if open_rows else {}
    todo = [r for r in closed_rows if "realized" not in (on_curve(r.get("closing") or {}, curve)[0] or {})]
    closed_res = book._results(todo, {}, now, only_closed=True, curve=curve) if todo else {}
    try:
        from . import quantfam as qf
        labels = {k: v[0] for k, v in qf.FAMILIES.items()}
    except Exception:  # noqa: BLE001
        labels = {}

    def blank(fam: str, label: str) -> Dict[str, Any]:
        return {"family": fam, "label": label, "count": 0, "desk": 0, "personal": 0, "open": 0, "closed": 0, "pnl_try": 0.0,
                "known": 0, "target": 0, "stop": 0, "other": 0}

    by: Dict[str, Dict[str, Any]] = {}
    every = blank("", "Toplam")
    for r in rows:
        src = r.get("source") or {}
        fam = str(src.get("family") or "?")
        row = by.setdefault(fam, blank(fam, labels.get(fam) or src.get("family_label") or fam))
        if r["status"] == "closed":
            c = on_curve(r.get("closing") or {}, curve)[0] or {}
            per = c.get("realized") if "realized" in c else ((closed_res.get(r["id"]) or {}).get("periods") or {}).get("total")
            hit = hit_of(r) or "other"
        else:
            per = ((res.get(r["id"]) or {}).get("periods") or {}).get("total")
            hit = None
        pnl = num(((per or {}).get("pnl") or {}).get("try"))
        for acc in (row, every):
            acc["count"] += 1
            acc[r["scope"]] += 1
            acc["closed" if r["status"] == "closed" else "open"] += 1
            if pnl is not None:
                acc["pnl_try"] += pnl
                acc["known"] += 1
            if hit:
                acc[hit] += 1
    out = []
    for acc in sorted(by.values(), key=lambda x: (-x["count"], x["label"])) + [every]:
        acc["avg_try"] = acc["pnl_try"] / acc["known"] if acc["known"] else None
        acc["pnl_try"] = acc["pnl_try"] if acc["known"] else None
        acc["hit_rate"] = acc["target"] / acc["closed"] if acc["closed"] else None
        out.append(acc)
    return {"families": out[:-1], "all": out[-1], "at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "ids": [r["id"] for r in rows], "curve": curve}
