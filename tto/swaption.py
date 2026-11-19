"""Swaption (19.11.2026; the desk: "Önce bir swaption sekmesi yapmanı istiyorum. Try ois için hesaplayacağız. Vadeyi
seçtiğimde günlük, yıllık bps vol ve % black vol çıkacak. Ben buraya vol girdiğimde bana delta gamma vega hesaplayacak,
veya rate opsiyonlarında ne greek'i varsa, bu vole göre implied rate vade sonunda ne olacak onu gösterecek, breakeven
rate'i hesaplayacak. Bu sadece görmek için olacak henüz buradan herhangi bir işlem yapılmayacak"): a European swaption on
a TRY OIS, to look at only - nothing is booked, nothing is stored.

* **The underlying** is the forward-start TRY OIS Fiyatlama prices (:mod:`tto.pricing`, the desk's answer: "like
  Fiyatlama"): it starts <expiry> after the OIS spot (``OIS_MAIN!B2``, T+1 on the TRY list) and matures <expiry +
  tenor> after it - both counted from the spot, so 1Y × 2Y is Fiyatlama's "TRY OIS 1Y × 3Y" -, fixed quarterly ACT/365
  against TLREF, the coupons counted back from the maturity, the short period first, one payment up to 3M
  (:func:`tto.pricing.coupons`).  The option expires on the TRY business day before the start.  F is the swap's par
  rate and A its annuity Σ τ·DF on the viewer's curve (Ayarlar → Eğri interpolasyonu: Bootstrap (Murex) or PPK
  basamak), the other curve's F and A beside them, as Fiyatlama has both.
* **The model** (the integrator's choice, the desk may change it): normal (Bachelier) on F with the annuity A - a payer
  is a call on F, a receiver a put: d = (F − K)/(σN·√T), payer = A·[(F − K)·Φ(d) + σN·√T·φ(d)], receiver =
  A·[(K − F)·Φ(−d) + σN·√T·φ(d)], a straddle both.  **% Black** is the lognormal vol that gives the same payer premium
  (solved: :func:`black_of`); a % Black vol typed is turned into σN the same way (:func:`normal_of`).
* **Vol time:** T = TRY business days from the market day to the expiry / 252 (:data:`YEAR`), so bp/year = bp/day·√252
  exactly and the daily bp vol is the daily breakeven move; the discounting stays inside the annuity (the curve's own
  ACT/365).
* **The vol shown on picking expiry × tenor** (the desk's answer): realized, from the dashboard's own daily closes -
  the sample standard deviation of the daily bp changes of the same expiry × tenor forward over the last 20 / 60 / 120 /
  250 changes, as the Realized Vol · Carry page (:mod:`tto.volcarry`; annual = daily·√252).  A past day's forward is
  dated from that day's own OIS spot and read off that day's curve, built from its closes the way Motor builds today's
  Bootstrap (:func:`day_curve`): a constant-maturity forward.  The history is on Bootstrap, as every shared calculation.
  No new Bloomberg request: the closes are the history's (``tto/history.py``).
* **Which vol prices:** realized over 60 changes by default; one typed in any unit (bp/day, bp/year or % Black)
  overrides it, and the page shows the vol used in all three.  **Strike** ATM (K = F) unless one is typed (%).
  **Notional** 100 mn TL unless typed (``100m``, ``2,5mn``: :func:`tto.inputs.parse_amount`).

Signs are the buyer's (a long option): premium paid, delta + for a payer and − for a receiver, gamma and vega +, theta −.
Rates are decimals, dates Excel serials, days of a curve calendar days from its spot.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from . import fxvol as fv
from . import ppkcurve as pk
from . import pricing as pr
from . import volcarry as vc
from .inputs import _fold, parse_amount, parse_number
from .xl.values import date_to_serial, serial_to_date

#: a vol year of business days (volcarry's): bp/year = bp/day · √252, T = business days / 252
YEAR = vc.YEAR
#: the realized windows, in daily changes; the 60 one is the vol a swaption is priced with until one is typed
WINDOWS = (20, 60, 120, 250)
DEFAULT_WINDOW = 60
#: the page's presets (both are typed as well: "18M", "2Y3M", "15")
EXPIRIES = ("1M", "3M", "6M", "9M", "1Y", "2Y", "3Y", "5Y")
TENORS = ("1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y")
DEFAULT_EXPIRY, DEFAULT_TENOR = "1Y", "2Y"
#: the TRY OIS curve ends at 10Y: expiry + tenor no longer than this many months
MAX_MONTHS = 120
DEFAULT_NOTIONAL = "100m"
#: the units a vol is typed in: bp a day, bp a year (both normal), % Black (lognormal)
DAY, ANNUAL, BLACK = "day", "year", "black"
UNITS = (DAY, ANNUAL, BLACK)
PAYER, RECEIVER, STRADDLE = "payer", "receiver", "straddle"
KINDS = (PAYER, RECEIVER, STRADDLE)
#: one basis point
BP = 1e-4
SQRT_YEAR = math.sqrt(YEAR)


class SwaptionError(ValueError):
    """What the page says of inputs it cannot price (Turkish)."""


# ================================================================================================== what is typed
def _text(query: Dict[str, Any], key: str) -> str:
    v = query.get(key)
    return "" if v is None else " ".join(str(v).split())[:40]


def _months(text: str, what: str) -> int:
    """An expiry or a tenor as typed - ``1Y``, ``18M``, ``2Y3M``, ``3A``, a bare ``15`` (months) - in months
    (:func:`tto.pricing.parse_when`)."""
    w = pr.parse_when(text)
    if w is None or w[0] == "spot":
        raise SwaptionError("%s okunamadı: %r (1M, 6M, 1Y, 18M, 2Y3M)" % (what, text))
    if w[0] != "m":
        raise SwaptionError("%s ay ya da yıl olarak yazılmalı (1M, 6M, 1Y, 18M, 2Y3M): %r" % (what, text))
    return int(w[1])


def label(months: int) -> str:
    """1M, 18M, 1Y, 2Y3M - a number of months as Fiyatlama names it."""
    return pr.when_label(("m", float(months)))


def read_inputs(query: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The page's inputs from the request (``expiry``, ``tenor``, ``strike``, ``notional``, ``vol``, ``vol_unit``):
    the texts as typed and what they are - months, the strike (``None``: ATM), the notional, the vol typed (bp for
    :data:`DAY` / :data:`ANNUAL`, a decimal for :data:`BLACK`; ``None``: the realized one).  :class:`SwaptionError` for
    what cannot be read, and for an expiry + tenor beyond 10Y."""
    q = query if isinstance(query, dict) else {}
    expiry = _text(q, "expiry") or DEFAULT_EXPIRY
    tenor = _text(q, "tenor") or DEFAULT_TENOR
    e, t = _months(expiry, "opsiyon vadesi"), _months(tenor, "swap vadesi")
    if e + t > MAX_MONTHS:
        raise SwaptionError("opsiyon vadesi + swap vadesi en çok 10 yıl olabilir - TRY OIS eğrisi 10Y'de biter (%s × %s = %s)"
                            % (label(e), label(t), label(e + t)))
    strike = _text(q, "strike")
    k = None
    if strike and _fold(strike) != "atm":
        k = pr._rate(strike)
        if k is None:
            raise SwaptionError("strike okunamadı: %r (35,10 = %%35,10; boş: ATM)" % strike)
    notional = _text(q, "notional") or DEFAULT_NOTIONAL
    n = parse_amount(notional)
    if n is None or not n > 0 or not math.isfinite(n):
        raise SwaptionError("nominal okunamadı: %r (100m, 2,5mn, 50.000.000)" % notional)
    unit = (_text(q, "vol_unit") or DAY).lower()
    if unit not in UNITS:
        raise SwaptionError("vol birimi okunamadı: %r (day: bp/gün, year: bp/yıl, black: %% Black)" % unit)
    vol = _text(q, "vol")
    typed = None
    if vol:
        x = parse_number(vol.replace("%", ""), prefer_decimal=True)
        if x is None or not x > 0 or not math.isfinite(x):
            raise SwaptionError("vol okunamadı: %r (bp/gün 5,5; bp/yıl 87; %% Black 4,2) - sıfırdan büyük olmalı" % vol)
        typed = x / 100.0 if unit == BLACK else x
    return {"expiry": expiry, "tenor": tenor, "strike": strike, "notional": notional, "vol": vol, "vol_unit": unit,
            "expiry_m": e, "tenor_m": t, "k": k, "n": n, "typed": typed}


# ================================================================================================== the dates
def dated(expiry_m: int, tenor_m: int, mk: pr.Market) -> Tuple[pr.Deal, float]:
    """The underlying - Fiyatlama's TRY OIS from <expiry> to <expiry + tenor>, both from ``mk``'s OIS spot
    (:func:`tto.pricing.swap_deal`) - and the option's expiry: the TRY business day before its start."""
    deal = pr.swap_deal(pr.OIS, ("m", float(expiry_m)), ("m", float(expiry_m + tenor_m)), mk)
    return deal, expiry_of(deal.start, mk.holidays["TRY"])


def expiry_of(start: float, hol: FrozenSet[float]) -> float:
    """The last TRY business day before ``start``."""
    d = float(int(start)) - 1.0
    while not pr.is_business(d, hol):
        d -= 1.0
    return d


def business_days(after: float, upto: float, hol: FrozenSet[float]) -> int:
    """TRY business days ``d`` with ``after`` < d ≤ ``upto``: the daily moves from the market day's close to the
    expiry's."""
    n = 0
    d = float(int(after)) + 1.0
    while d <= upto:
        if pr.is_business(d, hol):
            n += 1
        d += 1.0
    return n


# ================================================================================================== the model
def premiums(F: float, K: float, s: float) -> Tuple[float, float]:
    """Bachelier's payer (a call on F) and receiver (a put) per unit of annuity - forward premiums, rates - for the
    standard deviation ``s`` = σN·√T of F at the expiry; ``s`` 0: the intrinsic values."""
    if not s > 0.0:
        return max(F - K, 0.0), max(K - F, 0.0)
    d = (F - K) / s
    nd = fv.npdf(d)
    return (F - K) * fv.ncdf(d) + s * nd, (K - F) * fv.ncdf(-d) + s * nd


def black_of(F: float, K: float, T: float, sigma_n: float) -> Optional[float]:
    """The lognormal (Black) vol that gives the normal vol ``sigma_n``'s payer premium (decimals a year); ``None``
    where there is none - F or K not above 0, a premium Black cannot reach.  Payer less receiver is F − K in both
    models, so the vol of the same payer premium is the vol of the same receiver premium: it is solved on the out of the
    money side, all time value (deep in the money the payer's time value is lost in its intrinsic value)."""
    if not (F > 0.0 and K > 0.0 and T > 0.0 and sigma_n > 0.0):
        return None
    call = K >= F
    target = premiums(F, K, sigma_n * math.sqrt(T))[0 if call else 1]
    if not 0.0 < target < (F if call else K):
        return None

    def miss(v: float) -> float:
        return fv.black(F, K, v, T, call) - target

    hi = 1.0
    while miss(hi) < 0.0:
        hi *= 2.0
        if hi > 1e3:
            return None
    try:
        return fv.brent(miss, 1e-9, hi, xtol=1e-15)
    except fv.MATH_ERRORS:
        return None


def normal_of(F: float, K: float, T: float, sigma_b: float) -> Optional[float]:
    """The normal vol (decimal a year) whose payer premium is the Black vol ``sigma_b``'s - solved on the out of the
    money side as :func:`black_of`; ``None`` where there is none (F or K not above 0)."""
    if not (F > 0.0 and K > 0.0 and T > 0.0 and sigma_b > 0.0):
        return None
    call = K >= F
    target = fv.black(F, K, sigma_b, T, call)
    if not target > 0.0:
        return None
    root = math.sqrt(T)

    def miss(sigma: float) -> float:
        return premiums(F, K, sigma * root)[0 if call else 1] - target

    hi = max(1e-4, 2.0 * target * fv.SQRT2PI / root)
    while miss(hi) < 0.0:
        hi *= 2.0
        if hi > 10.0:
            return None
    try:
        return fv.brent(miss, 1e-12, hi, xtol=1e-16)
    except fv.MATH_ERRORS:
        return None


def options(F: float, K: float, sigma_n: float, days: int, A: float, N: float,
            sigma_b: Optional[float]) -> Dict[str, Dict[str, Any]]:
    """Payer, receiver and straddle on ``N`` (TL) of the swap with annuity ``A``, at the normal vol ``sigma_n`` for
    ``days`` business days (T = days / 252), the buyer's view:

    * premium - ``running_bp`` (the forward premium p, bp), ``upfront_bp`` (A·p, bp of the notional), ``tl`` (N·A·p);
    * ``delta_tl`` TL per bp of F (N·A·Φ(d)·1e-4; a receiver −N·A·Φ(−d)·1e-4) and ``delta`` (Φ(d), −Φ(−d));
    * ``gamma_tl`` - the change of that delta for 1 bp (N·A·φ(d)/(σN√T)·1e-8);
    * ``vega_tl`` TL per 1 bp of normal vol (N·A·√T·φ(d)·1e-4) and ``vega_black_tl`` per 1 % of Black vol (Black's own
      vega, N·A·F·√T·φ(d1)·0.01; none without a Black vol);
    * ``theta_tl`` TL per business day: the premium one business day nearer the expiry, at the same F, σN and A, less
      today's;
    * ``breakeven`` at the expiry: payer K + p, receiver K − p, straddle K ∓ (p_payer + p_receiver) (``low`` / ``high``)."""
    T = days / YEAR
    s = sigma_n * math.sqrt(T)
    d = (F - K) / s
    nd, up, down = fv.npdf(d), fv.ncdf(d), fv.ncdf(-d)
    pay, rec = premiums(F, K, s)
    pay1, rec1 = premiums(F, K, sigma_n * math.sqrt(max(days - 1, 0) / YEAR))
    bvega = fv.vega(F, K, sigma_b, T) if sigma_b else None
    out: Dict[str, Dict[str, Any]] = {}
    for kind, p, p1, delta, legs in ((PAYER, pay, pay1, up, 1.0), (RECEIVER, rec, rec1, -down, 1.0),
                                     (STRADDLE, pay + rec, pay1 + rec1, up - down, 2.0)):
        out[kind] = {"running_bp": p / BP, "upfront_bp": A * p / BP, "tl": N * A * p,
                     "delta": delta, "delta_tl": N * A * delta * BP,
                     "gamma_tl": N * A * legs * nd / s * BP * BP,
                     "vega_tl": N * A * legs * math.sqrt(T) * nd * BP,
                     "vega_black_tl": N * A * legs * bvega * 0.01 if bvega is not None else None,
                     "theta_tl": N * A * (p1 - p)}
    out[PAYER]["breakeven"] = K + pay
    out[RECEIVER]["breakeven"] = K - rec
    out[STRADDLE]["breakeven"] = {"low": K - (pay + rec), "high": K + (pay + rec)}
    out["d"] = {"d": d, "s": s}
    return out


# ================================================================================================== the history
def needed_months(expiry_m: int, tenor_m: int, node_months: Sequence[float], quote_months: Sequence[float]) -> List[int]:
    """The OIS tenors (months) a day must have closed for this forward: Motor's node pars are its quotes linear in
    months, so every quote up to the first one at or beyond the node the maturity reads (the first node at or after
    expiry + tenor)."""
    m = expiry_m + tenor_m
    nodes = sorted(int(round(x)) for x in node_months if x > 0)
    quotes = sorted(int(round(x)) for x in quote_months)
    if not nodes or not quotes:
        return []
    hi = next((x for x in nodes if x >= m), nodes[-1])
    top = next((q for q in quotes if q >= hi), quotes[-1])
    return [q for q in quotes if q <= top]


def day_curve(day: float, quotes: Sequence[Tuple[float, float]], node_months: Sequence[float],
              hol: FrozenSet[float]) -> Tuple[float, pk.LogLinear]:
    """A past day's Bootstrap, built the way Motor builds today's: its OIS spot - the next TRY business day
    (``OIS_MAIN!B2 = WORKDAY(TODAY(), 1)``) -, Motor's nodes counted from it (``Motor!B88:C130``: node m on
    ``WORKDAY(EDATE(spot, m) − 1, 1)``) and Motor's bootstrap of that day's closes ``(months, rate)`` on them
    (:func:`tto.pricing.motor_curve`).  ``(spot, curve)``."""
    spot = pr.roll(day + 1.0, hol)
    nodes = [(m, (pr.tenor_date(spot, int(round(m)), hol) - spot) if m > 0 else 0.0) for m in node_months]
    return spot, pr.motor_curve(quotes, nodes)


def forward_history(closes: Dict[float, Dict[str, float]], expiry_m: int, tenor_m: int, mk: pr.Market,
                    hol: FrozenSet[float], kept: Optional[Dict[str, Any]] = None,
                    keep: int = WINDOWS[-1] + 1) -> Dict[str, Any]:
    """The forward's level (%) on the last ``keep`` days that closed every tenor it needs (:func:`needed_months`),
    oldest first: each day's own expiry × tenor - Fiyatlama's dating from that day's OIS spot - on that day's curve
    (:func:`day_curve`, every Motor tenor that closed that day).  ``closes``: months -> {ISO day: close %}; ``hol``:
    the TRY holidays of the past days too; ``kept`` (any dict): each day's curve by what it is made of, so another
    expiry × tenor, or the same asked again, builds none again.  ``{"days", "levels", "need", "missing"}`` (``missing``:
    the tenors needed that have no close at all)."""
    kept = kept if kept is not None else {}
    node_months = [float(m) for m, _ in mk.nodes]
    quote_months = sorted(float(m) for m, _ in mk.ois_quotes)
    need = needed_months(expiry_m, tenor_m, node_months, quote_months)
    have = {float(m): closes.get(float(m)) or {} for m in need}
    missing = [m for m in need if not have[float(m)]]
    out: Dict[str, Any] = {"days": [], "levels": [], "need": need, "missing": missing}
    if missing or not need:
        return out
    days = sorted(set.intersection(*[set(s) for s in have.values()]))
    listed = [m for m in quote_months if m in closes]
    base = mk._replace(holidays=dict(mk.holidays, TRY=hol))
    mark = (tuple(node_months), hash(hol))
    got: List[Tuple[str, float]] = []
    for iso in reversed(days):
        if len(got) >= keep:
            break
        quotes = tuple((m, closes[m][iso] / 100.0) for m in listed if iso in closes[m])
        sig = (quotes, mark)
        hit = kept.get(iso)
        if hit is None or hit[0] != sig:
            try:
                spot, curve = day_curve(float(date_to_serial(_dt.date.fromisoformat(iso))), quotes, node_months, hol)
            except ValueError:
                spot, curve = None, None                       # (closes no bootstrap takes: no level that day)
            hit = kept[iso] = (sig, spot, curve)
        _, spot, curve = hit
        if curve is None:
            continue
        deal = pr.swap_deal(pr.OIS, ("m", float(expiry_m)), ("m", float(expiry_m + tenor_m)), base._replace(ois_spot=spot))
        got.append((iso, pr.mid(deal, curve) * 100.0))
    got.reverse()
    out["days"] = [d for d, _ in got]
    out["levels"] = [x for _, x in got]
    return out


def realized(days: Sequence[str], levels: Sequence[float], F: float, K: float, T: float) -> List[Dict[str, Any]]:
    """The realized vol of each window (:data:`WINDOWS`): bp a day (:func:`tto.volcarry.realized`: the sample standard
    deviation of the last n daily changes), a year (× √252) and as % Black at today's F and the strike; the changes
    used, whether the window is full, the first and last day it reads.  A window with fewer than
    ``volcarry.MIN_CHANGES`` changes has none."""
    got = vc.realized(list(levels), "pct", WINDOWS)
    rows = []
    for n in WINDOWS:
        r = got.get(n)
        if r is None:
            rows.append({"window": n, "n": max(len(levels) - 1, 0), "full": False, "first": None, "last": None,
                         "day": None, "year": None, "black": None})
            continue
        k = r["n"]
        year = r["d"] * SQRT_YEAR
        rows.append({"window": n, "n": k, "full": r["full"], "first": days[-(k + 1)], "last": days[-1], "day": r["d"],
                     "year": year, "black": black_of(F, K, T, year * BP)})
    return rows


# ================================================================================================== the page
def price(inputs: Dict[str, Any], cv: Dict[str, Any], mk: pr.Market, method: str, today: float,
          history: Dict[str, Any]) -> Dict[str, Any]:
    """The page's numbers: the underlying on both curves (``method``, the viewer's own, first), the option's dates and
    T, the realized vols (``history``: :func:`forward_history`'s), the vol used in its three units and payer, receiver
    and straddle on the viewer's curve.  :class:`SwaptionError` / :class:`tto.pricing.PricingError` for what cannot be
    priced; without a vol (no realized one, none typed) the options are left out and ``vol`` says why."""
    e, t = inputs["expiry_m"], inputs["tenor_m"]
    deal, expiry = dated(e, t, mk)
    hol = mk.holidays["TRY"]
    curves = pr.Curves(cv, mk)
    base = {m: curves.curve(pr.ON, m) for m in pr.METHODS}
    if base[method] is None:
        if base[pr.BOOT] is None:
            raise SwaptionError("eğri kurulamadı: %s" % ("; ".join(curves.errors) or "kota yok"))
        method = pr.BOOT
    methods = [method] + [m for m in pr.METHODS if m != method]
    fwd = {m: (pr.mid(deal, base[m]) if base[m] is not None else None) for m in pr.METHODS}
    ann = {m: (pr.annuity(deal, base[m]) if base[m] is not None else None) for m in pr.METHODS}
    F, A = fwd[method], ann[method]
    K = inputs["k"] if inputs["k"] is not None else F
    N = inputs["n"]
    days = business_days(today, expiry, hol)
    if days < 1:
        raise SwaptionError("opsiyon vadesi (%s) bugünden sonra olmalı" % _date_text(expiry))
    T = days / YEAR
    rows = realized(history.get("days") or [], history.get("levels") or [], F, K, T)
    # the vol used: the one typed, in its unit, else the realized 60 changes'
    unit, typed = inputs["vol_unit"], inputs["typed"]
    vol: Dict[str, Any] = {"source": "typed" if typed is not None else "realized", "unit": unit if typed is not None else DAY,
                           "window": None if typed is not None else DEFAULT_WINDOW, "day": None, "year": None,
                           "black": None, "n": None, "full": None, "why": ""}
    if typed is not None:
        if unit == BLACK:
            sigma = normal_of(F, K, T, typed)
            if sigma is None:
                raise SwaptionError("%% Black vol bu forward ve strike'ta normal vol'e çevrilemiyor (F ve K sıfırdan büyük olmalı)")
            vol.update(year=sigma / BP, black=typed)
        else:
            vol["year"] = typed if unit == ANNUAL else typed * SQRT_YEAR
    else:
        row = next(r for r in rows if r["window"] == DEFAULT_WINDOW)
        if row["day"] is not None:
            vol.update(year=row["year"], n=row["n"], full=row["full"])
        else:
            vol["why"] = _no_vol_text(history)
    if vol["year"] is not None:
        vol["day"] = vol["year"] / SQRT_YEAR
        if vol["black"] is None:
            vol["black"] = black_of(F, K, T, vol["year"] * BP)
    sigma_n = vol["year"] * BP if vol["year"] is not None else None
    opts = options(F, K, sigma_n, days, A, N, vol["black"]) if sigma_n else None
    sd = sigma_n * math.sqrt(T) if sigma_n else None
    sp = deal.spot
    out: Dict[str, Any] = {
        "curve": method, "methods": methods, "curve_text": pr.METHOD_TEXT[method],
        "inputs": {k: inputs[k] for k in ("expiry", "tenor", "strike", "notional", "vol", "vol_unit")},
        "expiry_m": e, "tenor_m": t, "label": "%s × %s" % (label(e), label(t)), "underlying": deal.label,
        "today": today, "spot": sp, "expiry": expiry, "start": deal.start, "end": deal.end,
        "bdays": days, "T": T, "cdays": expiry - today,
        "forward": fwd, "annuity": ann, "diff": ((fwd[pr.PPK] - fwd[pr.BOOT]) / BP
                                                  if fwd[pr.PPK] is not None and fwd[pr.BOOT] is not None else None),
        "F": F, "A": A, "strike": K, "atm": inputs["k"] is None, "moneyness_bp": (K - F) / BP, "notional": N,
        "dv01": N * A * BP, "vol": vol, "options": opts,
        "range": ({"sd_bp": sd / BP, "F": F, "down1": F - sd, "up1": F + sd, "down2": F - 2.0 * sd, "up2": F + 2.0 * sd}
                  if sd else None),
        "realized": {"rows": rows, "need": [pk.tenor_label(m) for m in history.get("need") or []],
                     "missing": [pk.tenor_label(m) for m in history.get("missing") or []],
                     "days": len(history.get("days") or []),
                     "first": (history.get("days") or [None])[0], "last": (history.get("days") or [None])[-1],
                     "default": DEFAULT_WINDOW, "windows": list(WINDOWS)},
        "schedule": [{"start": lg.start, "pay": lg.pay, "days": lg.days, "tau": lg.tau,
                      "df": {m: (base[m].df(lg.pay - sp) if base[m] is not None else None) for m in pr.METHODS}}
                     for lg in deal.legs],
        "presets": {"expiry": list(EXPIRIES), "tenor": list(TENORS)}, "max_months": MAX_MONTHS, "year": YEAR,
        "errors": list(curves.errors), "texts": TEXTS,
    }
    return out


def _date_text(serial: float) -> str:
    return serial_to_date(serial).strftime("%d.%m.%Y")


def _no_vol_text(history: Dict[str, Any]) -> str:
    missing = [pk.tenor_label(m) for m in history.get("missing") or []]
    if missing:
        return "Gerçekleşen vol yok: geçmişte %s kapanışı yok. Vol yazın." % ", ".join(missing)
    n = max(len(history.get("levels") or []) - 1, 0)
    return ("Gerçekleşen vol yok: forward'ın %d günlük değişimi var (en az %d gerekir). Vol yazın." % (n, vc.MIN_CHANGES))


#: what the page says of how it works (Turkish)
TEXTS = {
    "underlying": "Dayanak: Fiyatlama'nın ileri başlangıçlı TRY OIS'i - başlangıç OIS spot'undan (OIS_MAIN!B2, TRY listesiyle "
                  "T+1) <opsiyon vadesi> sonra, vade spot'tan <opsiyon vadesi + swap vadesi> sonra (1Y × 2Y = Fiyatlama'da TRY "
                  "OIS 1Y × 3Y); sabit ↔ TLREF, ACT/365, 3 aya kadar tek ödeme, sonra çeyreklik - kuponlar vadeden geriye, kısa "
                  "dönem başta. Opsiyon başlangıçtan önceki TRY iş günü sona erer. F = swap'ın par'ı, A = annuity (Σ τ·DF).",
    "model": "Model: normal (Bachelier), forward swap faizi F üzerinde, annuity A ile. Payer = F üzerine call, receiver = put: "
             "d = (F − K) / (σN·√T); payer = A·[(F − K)·Φ(d) + σN·√T·φ(d)], receiver = A·[(K − F)·Φ(−d) + σN·√T·φ(d)]; "
             "straddle ikisi. % Black: aynı payer primini veren lognormal vol (çözülür); yazılan % Black vol da aynı yolla "
             "σN'e çevrilir.",
    "time": "Vol zamanı: T = piyasa gününden opsiyon vadesine TRY iş günü / 252 - bp/yıl = bp/gün · √252, günlük bp vol günlük "
            "başabaş hareketidir. İskonto annuity'nin içinde (eğrinin kendi ACT/365'i).",
    "vol": "Vol: varsayılan, 60 değişimlik gerçekleşen vol; herhangi bir birimde (bp/gün, bp/yıl, % Black) yazılan vol onun "
           "yerine geçer ve kullanılan vol üç birimde de gösterilir.",
    "realized": "Gerçekleşen vol: aynı opsiyon vadesi × swap vadesi forward'ının günlük bp değişimlerinin örneklem standart "
                "sapması (son 20 / 60 / 120 / 250 değişim, Realized Vol · Carry sayfası gibi), yıllık = günlük · √252. Geçmiş "
                "bir günün forward'ı o günün OIS spot'undan tarihlenir ve o günün kapanışlarından Motor'un yöntemiyle kurulan "
                "Bootstrap eğrisinden okunur (sabit vadeli forward); geçmiş her zaman Bootstrap'tadır. Bir gün, forward'ın "
                "ihtiyaç duyduğu bütün vadeler o gün kapandıysa sayılır. % Black bugünkü F ve strike'ta. Yeni Bloomberg isteği "
                "yok: kapanışlar tarihçenin.",
    "curve": "Eğri: Ayarlar → Eğri interpolasyonu (Bootstrap (Murex) / PPK basamak) önde, öbür eğrinin forward'ı ve annuity'si "
             "yanında - Fiyatlama gibi. Opsiyon sayıları sizin eğrinizde.",
    "signs": "İşaretler alıcının (uzun opsiyon): prim ödenir; delta payer'da +, receiver'da −; gamma ve vega +; teta −. Delta "
             "TL/bp: N·A·Φ(d)·0,0001; gamma: o deltanın 1 bp'lik değişimi; vega: 1 bp normal vol ve %1 Black vol için; teta: "
             "aynı F, σN ve A ile bir iş günü sonraki prim − bugünkü. Prim: bp peşin = A·p, bp running = p (forward prim), "
             "TL = N·A·p. Dayanak DV01 = N·A·0,0001 (payer +).",
    "range": "Vadede faiz: normal modelde F (beklenen), F ± σN·√T (±1σ, ~%68) ve F ± 2σN·√T (±2σ, ~%95).",
    "breakeven": "Başabaş (vadede): payer K + p, receiver K − p, straddle K ± (p_payer + p_receiver); p = running prim.",
    "strike": "Strike: boşsa ATM (K = F, sizin eğrinizde); yazılırsa % (35,10 = %35,10). Nominal: varsayılan 100 mn TL "
              "(100m, 2,5mn, 50.000.000).",
    "view": "Yalnızca görmek için: buradan işlem yapılmaz, hiçbir şey saklanmaz (son girdiler yalnız bu tarayıcıda kalır).",
}
