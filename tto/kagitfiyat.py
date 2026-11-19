"""Kâğıt Fiyatlama: one fair level for every fixed coupon bond and bill of the trading list, a two-way quote around it,
the levels worth trading and how the price was built - the desk's request of 19.11.2026 ("Özellikle kâğıt tarafı zayıf
geldi" - "Hangi seviyelerin iyi olduğunu ve fiyatlamayı nasıl yapacağımı net söylemiyor").

**What a bond's yield follows.**  Asked what a bond's price should start from, the desk said "Bunu sen bul. En çok neyi
takip ediyor".  Measured on the desk's own history (a copy of its database of 17.11.2026: 16 DİBS, 14 fixed coupon and 2
bills, 10.11.2025–16.11.2026), the daily yield changes of a bond follow:

* the Nelson-Siegel curve fitted to the *other* bonds of the list (leave one out) best from 1Y on - R² .73 (1–3Y), .82
  (3–5Y), .81 (5Y+) against OIS's .50 / .54 / .47 and offshore's .39 / .40 / .27;
* at 1Y and under nothing much (R² .21 OIS, .21 offshore, .14 the neighbours).

The fair of the next day, a base plus the bond's spread to it at the previous close, missed by (sd): 23 bp at 1–3Y, 16 at
3–5Y and 16 at 5Y+ on the neighbours' curve, 37 bp at 1Y and under on OIS.  A 20 or 60 day median spread did 35–140 %
worse (the spreads drift); offshore was never the best base (the bonds move about half as much, β ≈ 0.45), so it is no
base here - the ASW FX fair values elsewhere stay as they are.

**The fair yield** (``fair_from``): each base now plus the bond's spread to it at the last close before today, blended
by the bond's years to maturity (``WEIGHTS``: 1–5Y the neighbours alone, beyond 5Y 75 % neighbours + 25 % OIS, 1Y and
under 75 % OIS + 25 % neighbours; a base that cannot be had gives its share to the other).

* **Komşu eğri** (the neighbours' curve, ``NBR``): quantcurve's fit as DİBS RV · Genel runs it live (``BondFit``,
  ``refit``; Nelson-Siegel on the fixed coupon bonds, its τ searched once - ``dibs_search`` - on the last close and held),
  refitted without the bond itself; the bond's model yield on it.  A bill is never in the fit: it reads the curve of all
  the coupon bonds.  On a past day the bonds' closes; now the other bonds' quotes on DİBS RV (the simple yields the sheet
  works out of the price in use).
* **OIS**: the TRY OIS Bootstrap's zero rate at the bond's maturity, from the OIS spot - a past day's on Motor's
  bootstrap of that day's closes (``swaption.day_curve``), today's on the workbook's (``Service._try_curves``' ``boot``).

Everything is compared on one basis, as the analysis did: the bonds' BIST compound yield (DİBS RV!T: a coupon bond's
``(1 + y/f)^f − 1``, a bill's ``(1 + y·t)^(1/t) − 1``) against zero rates compounded once a year (``(1/DF)^(365/days)
− 1``).  The fair is shown in the trading list's yields - BIST compound and simple, as DİBS RV · Genel shows them - and as a
clean price at the value date DİBS RV prices the bond on (P; DİBS Trading's), worked out as that sheet works out its own
(``Pricer``: a bill from its days, a coupon bond from its cash flows).

**Kotan**: bid / ask around the fair, the width of the bond's bucket (``WIDTH_DEFAULT``: 10 bp in total; the
administrators change it, as RET's width).  **İyi seviyeler**: "Al" at a yield ≥ fair + 2σ (a higher yield is cheap), "Sat"
≤ fair − 2σ, ±1σ noise; σ the bond's own next-day error over its last 60 closes, floored at its bucket's
(``SIGMA_FLOOR``: the analysis' 37 / 23 / 16 bp) - with the backtest on the history: of the closes beyond ±2σ, how often
the gap to fair narrowed within the next 5 closes and by how much on average (``backtest``).  **Piyasa şimdi**: the
Broker Chat board's best fresh bid / offer and the live Bloomberg bid / ask (DİBS RV!K / L), each in σ from fair; AL
where an offer is at fair + 2σ or above, SAT where a bid is at fair − 2σ or below.  **Bağlam**: the spread to the
neighbours' curve now against its 20-day median.

TLREF floaters, FRNs and CPI linkers are not priced here; their row says why.

**Threads.**  What the sheets have now is read on the engine thread (``_read``, short); the closes' part (each past
day's curves, the spreads, σ, the backtest) off it, from the store's memory (``Store.hist_many``), kept per revision of
the history and each day's curves per what they are made of - a new close builds that day again, not the year."""
from __future__ import annotations

import datetime as _dt
import math
import statistics
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import quantcurve as qc
from . import rvfair

PAGE_ID = "kagit-fiyat"
PAGE = {"id": PAGE_ID, "title": "Kâğıt Fiyatlama", "group": "Tahvil", "book": "tto", "sheet": None, "custom": True}

#: the bases: the neighbours' curve (Nelson-Siegel of the other bonds, leave one out) and TRY OIS (Bootstrap)
NBR, OIS = "nbr", "ois"
BASES = (NBR, OIS)
BASE_TEXT = {NBR: "Komşu eğri", OIS: "OIS"}
BASE_TO = {NBR: "komşu eğriye", OIS: "OIS'e"}                 # (the dative: "payı komşu eğriye geçti")
#: the maturity buckets: (key, caption, its longest years to maturity - None: no end)
BUCKETS = (("1y", "≤ 1Y", 1.0), ("3y", "1–3Y", 3.0), ("5y", "3–5Y", 5.0), ("5y+", "5Y+", None))
BUCKET_TEXT = {k: t for k, t, _ in BUCKETS}
#: each bucket's weights on the bases (the desk may change them): 1Y and under mostly OIS, 1–5Y the neighbours alone, beyond
#: 5Y mostly the neighbours - what the bonds followed best (see the module text)
WEIGHTS: Dict[str, Dict[str, float]] = {"1y": {OIS: 0.75, NBR: 0.25}, "3y": {NBR: 1.0}, "5y": {NBR: 1.0},
                                        "5y+": {NBR: 0.75, OIS: 0.25}}
#: σ's floor by bucket (bp of the compound yield): the analysis' next-day error of the best base at each maturity
SIGMA_FLOOR: Dict[str, float] = {"1y": 37.0, "3y": 23.0, "5y": 16.0, "5y+": 16.0}
#: the quote's width by bucket (bp of the compound yield, bid to ask) until the administrators set one
WIDTH_DEFAULT: Dict[str, float] = {"1y": 10.0, "3y": 10.0, "5y": 10.0, "5y+": 10.0}
WIDTH_MAX = 200.0
SIGMA_WINDOW = 60                     # next-day errors σ is measured over (the last closes)
SIGMA_MIN = 20                        # errors σ needs before it is measured (fewer: the floor alone)
BAND = 2.0                            # the good levels: fair ± BAND σ
NOISE = 1.0                           # the noise band: fair ± NOISE σ
REVERT = 5                            # the backtest: closes after a signal its gap to fair is measured at
MEDIAN_DAYS = 20                      # Bağlam: the spread to the neighbours' curve against its median over these closes
HISTORY_DAYS = 370                    # the closes read (calendar days back from today: the history's own window)
DAYS_KEPT = 600                       # past days' curves kept (each by what it is made of)
NOW_KEPT = 8                          # fits of the quotes now kept
WARM_DELAY, WARM_EVERY = 60.0, 60.0   # seconds: the closes' part made ahead after the start, then looked at again
#: the kinds of DİBS RV (column D) in the order the page lists them, as DİBS Trading's summary groups them
KINDS = (("B", "Bono · kuponsuz"), ("S", "Sabit kuponlu"), ("T", "TLREF'e endeksli"), ("F", "FRN"), ("E", "TÜFE'ye endeksli"))
#: why a kind is not priced here
NOT_PRICED = {"T": "TLREF'e endeksli: kuponu TLREF'le değişir, getiri eğrisine göre fiyatlanmaz (DM'i DİBS RV'de)",
              "F": "FRN: değişken kupon, yalnız fiyatla izlenir - getiri eğrisine göre fiyatlanmaz",
              "E": "TÜFE'ye endeksli: reel getiri, nominal eğrilere göre fiyatlanmaz"}
#: where the administrators' widths and their log are kept (the store's key / value table)
KEY_WIDTHS, KEY_LOG = "kagitfiyat.widths", "kagitfiyat.log"
LOG_MAX = 50
BP = 1e4


class KagitError(ValueError):
    """A request the page cannot answer: the reason, in Turkish (the service's 400)."""


def menu(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The nav's pages with Kâğıt Fiyatlama first in the Tahvil menu - when DİBS RV is there (a dashboard without the TRY
    workbook has no bond to price)."""
    if not any(p["id"] == "dibs" for p in pages):
        return pages
    at = next((i for i, p in enumerate(pages) if p.get("group") == "Tahvil"), len(pages))
    return pages[:at] + [dict(PAGE)] + pages[at:]


# ---------------------------------------------------------------------------------------------- buckets and weights
def bucket_of(years: float) -> str:
    """The bucket of a bond with ``years`` to maturity."""
    for key, _, top in BUCKETS:
        if top is None or years <= top + 1e-12:
            return key
    return BUCKETS[-1][0]


def weights_of(bucket: str, have: Sequence[str]) -> Dict[str, float]:
    """The bucket's weights on the bases in ``have``: a base that is not there gives its share to the others (none left:
    no weights)."""
    w = {b: x for b, x in WEIGHTS[bucket].items() if x > 0 and b in have}
    total = sum(w.values())
    return {b: x / total for b, x in w.items()} if total > 0 else {}


def zero_rate(curve: Any, spot: float, mat: float) -> Optional[float]:
    """A curve's zero rate to the day ``mat`` (serial) from its day 0 ``spot``, compounded once a year (ACT/365):
    ``(1/DF)^(365/days) − 1``."""
    t = mat - spot
    if curve is None or t <= 0:
        return None
    df = curve.df(t)
    return df ** (-365.0 / t) - 1.0 if df > 0 else None


def to_compound(bond: qc.Bond, y: float, value: _dt.date, conv: str) -> float:
    """A yield (decimal) of ``conv`` as BIST's compound one (DİBS RV!T): a coupon bond's ``(1 + y/f)^f − 1``, a bill's
    ``(1 + y·t)^(1/t) − 1``, t its years from the value date."""
    if conv == "compound":
        return y
    if bond.kind == "bill":
        t = (bond.maturity - value).days / qc.YEAR
        return (1.0 + y * t) ** (1.0 / t) - 1.0 if t > 0 else y
    f = float(bond.freq)
    return (1.0 + y / f) ** f - 1.0


# ---------------------------------------------------------------------------------------------- the neighbours' curve
def _price_on(fit_in: qc.BondFit, j: int, nss: qc.Nss) -> float:
    return sum(cf * nss.df(t) for t, cf in fit_in.flows[j])


def neighbours(items: Sequence[Tuple[qc.Bond, _dt.date, float, str]], nss0: qc.Nss,
               extra: Sequence[Tuple[qc.Bond, _dt.date]] = ()) -> Dict[str, Any]:
    """Each bond against the curve of the others: the Nelson-Siegel curve of the fixed coupon bonds of ``items`` (bond,
    value date, yield, its convention) - quantcurve's fit, the model and τ of ``nss0`` held, the β from it - fitted again
    without the bond (leave one out), the bond's model yield on it compounded (``nbr``: ISIN -> decimal).  A bill (never
    in the fit) and the bonds of ``extra`` (bond, value date: no yield of their own) on the curve of all of them.  Too few
    coupon bonds to leave one out: ``{"nbr": {}, "why"}``."""
    fit_in = qc.BondFit(items)
    out: Dict[str, Any] = {"nbr": {}, "n_fit": fit_in.n_fit, "n": len(fit_in)}
    if fit_in.n_fit < qc.MIN_BONDS + 1:
        out["why"] = "en az %d sabit kuponlu kâğıdın getirisi gerekli (%d var)" % (qc.MIN_BONDS + 1, fit_in.n_fit)
        return out
    full = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)
    nss = full["nss"]
    out["nss"] = nss
    fitted = set(fit_in.fitted)
    for j, b in enumerate(fit_in.bonds):
        if j in fitted:
            idx = [i for i in fit_in.fitted if i != j]

            def make(t1: float, t2: float, idx: List[int] = idx) -> Tuple[Any, Any]:
                return fit_in._fn(idx, t1, t2), (lambda k=qc.NSS: list(nss.beta[:k]))

            pm = _price_on(fit_in, j, qc.refit(make, nss, nss.beta, iters=8)["nss"])
        else:
            pm = _price_on(fit_in, j, nss)
        ym = b.yield_of(pm, fit_in.value[j], fit_in.conv[j], fit_in.y[j])
        if ym is not None and math.isfinite(ym):
            out["nbr"][b.isin] = to_compound(b, ym, fit_in.value[j], fit_in.conv[j])
    for b, value in extra:
        if b.isin in out["nbr"] or (b.maturity - value).days < qc.MIN_DAYS:
            continue
        flows, _ = b.flows(value)
        if not flows:
            continue
        pm = sum(cf * nss.df((d - value).days / qc.YEAR) for d, cf in flows)
        ym = b.yield_of(pm, value, "compound", nss.zero(max((b.maturity - value).days / qc.YEAR, 0.01)))
        if ym is not None and math.isfinite(ym):
            out["nbr"][b.isin] = ym
    return out


# ---------------------------------------------------------------------------------------------- a bond's closes
def fair_from(prev: Dict[str, Any], rec: Dict[str, Any], bucket: str) -> Optional[Tuple[float, Dict[str, float]]]:
    """The fair yield at ``rec`` (each base there plus the bond's spread to it at ``prev``), blended by ``bucket``'s
    weights over the bases both have: ``(fair, weights)``, or None."""
    have = [b for b in BASES if rec.get(b) is not None and prev.get(b) is not None]
    w = weights_of(bucket, have)
    if not w:
        return None
    return sum(x * (rec[b] + prev["y"] - prev[b]) for b, x in w.items()), w


def errors_of(recs: Sequence[Dict[str, Any]], pos: Dict[str, int]) -> List[Tuple[int, float, Dict[str, float]]]:
    """The next-day errors of a bond's closes (``recs``, by day): at each close whose previous one is the day before on
    the history's axis (``pos``: day -> place), its yield − the fair from the bases that day and the spreads the day
    before, bp - ``(index of the close, error, weights)``."""
    out = []
    for k in range(1, len(recs)):
        a, r = recs[k - 1], recs[k]
        if pos.get(r["day"], -9) - pos.get(a["day"], -9) != 1:
            continue
        got = fair_from(a, r, bucket_of(r["t"]))
        if got is not None:
            out.append((k, (r["y"] - got[0]) * BP, got[1]))
    return out


def sigma_of(errors: Sequence[float], floor: float) -> Dict[str, Any]:
    """σ of the last ``SIGMA_WINDOW`` next-day errors (bp; sd as the analysis measured it), floored at ``floor``; with
    fewer than ``SIGMA_MIN`` of them the floor alone."""
    last = list(errors)[-SIGMA_WINDOW:]
    sd = statistics.pstdev(last) if len(last) >= SIGMA_MIN else None
    used = max(floor, sd) if sd is not None else floor
    return {"sigma": used, "sd": sd, "n": len(last), "floor": floor, "floored": sd is None or sd < floor, "short": sd is None}


def backtest(recs: Sequence[Dict[str, Any]], errs: Sequence[Tuple[int, float, Dict[str, float]]]) -> Dict[str, Any]:
    """Every close of the history beyond ±``BAND``σ of its fair (σ as known then: the errors before it, floored at its
    bucket's): did the gap to fair narrow by the ``REVERT``-th close after it?  The gap there is measured against the fair
    of the signal's own spreads (the day before it) and weights - the bond against its bases, what a trade against them
    earns, bp.  ``{"n", "hits", "hit" (share), "avg" (bp toward fair), "cheap": {...}, "rich": {...}}``."""
    moves: Dict[str, List[float]] = {"cheap": [], "rich": []}
    for i, (k, e, w) in enumerate(errs):
        prior = [x[1] for x in errs[max(0, i - SIGMA_WINDOW):i]]
        sigma = sigma_of(prior, SIGMA_FLOOR[bucket_of(recs[k]["t"])])["sigma"]
        if abs(e) < BAND * sigma:
            continue
        j = k + REVERT
        if j >= len(recs):
            continue
        prev, later = recs[k - 1], recs[j]
        if any(later.get(b) is None for b in w):
            continue
        gap = (later["y"] - sum(x * (later[b] + prev["y"] - prev[b]) for b, x in w.items())) * BP
        moves["cheap" if e > 0 else "rich"].append((e - gap) if e > 0 else (gap - e))

    def stats(ms: List[float]) -> Dict[str, Any]:
        n = len(ms)
        hits = sum(1 for m in ms if m > 0)
        return {"n": n, "hits": hits, "hit": hits / n if n else None, "avg": sum(ms) / n if n else None}

    out = stats(moves["cheap"] + moves["rich"])
    out.update(cheap=stats(moves["cheap"]), rich=stats(moves["rich"]))
    return out


def bond_closes(recs: Sequence[Dict[str, Any]], pos: Dict[str, int], bucket_now: str) -> Dict[str, Any]:
    """What a bond's closes say for its price now: the last close (its day, yield, each base and the spread to it), σ,
    the backtest and the spread to the neighbours' curve over its last ``MEDIAN_DAYS`` closes."""
    out: Dict[str, Any] = {"n": len(recs)}
    if not recs:
        return out
    last = recs[-1]
    out["last"] = {"day": last["day"], "y": last["y"],
                   "spread": {b: last["y"] - last[b] for b in BASES if last.get(b) is not None},
                   "base": {b: last[b] for b in BASES if last.get(b) is not None}}
    errs = errors_of(recs, pos)
    out["sigma"] = sigma_of([e for _, e, _ in errs], SIGMA_FLOOR[bucket_now])
    out["backtest"] = backtest(recs, errs)
    spreads = [(r["y"] - r[NBR]) * BP for r in recs if r.get(NBR) is not None][-MEDIAN_DAYS:]
    if spreads:
        out["median"] = {"bp": statistics.median(spreads), "n": len(spreads)}
    return out


# ---------------------------------------------------------------------------------------------- DİBS RV's own price <-> yield
class Pricer(object):
    """A bond priced as DİBS RV prices it at its value date (P): a bill from its days (DR), a coupon bond from its cash
    flows (ID:JA) at their times in coupon periods (LV:MS), ``freq`` a year (CU), less the accrued interest (CW).  Its
    yields are BIST's: compound (DİBS RV!T) and simple (S).  Without the sheet's cash flows (no price on the row) the
    bond's own (quantcurve's ``Bond``, the same BIST rules) at the value date."""

    __slots__ = ("kind", "value", "days", "freq", "flows", "acc", "bond", "guess")

    def __init__(self, kind: str, value: Optional[_dt.date], days: Optional[float], freq: float, flows: Sequence[Tuple[float, float]],
                 acc: float, bond: Optional[qc.Bond] = None, guess: float = 0.3):
        self.kind, self.value, self.days, self.freq = kind, value, days, float(freq or 2.0)
        self.flows, self.acc, self.bond, self.guess = list(flows), float(acc or 0.0), bond, guess

    @property
    def ok(self) -> bool:
        if self.value is None:
            return False
        if self.kind == "bill":
            return bool(self.days and self.days > 0)
        return bool(self.flows) or self.bond is not None

    def dirty(self, yc: float) -> Optional[float]:
        """The dirty price at the compound yield ``yc`` (decimal)."""
        if not self.ok or yc <= -0.99:
            return None
        if self.kind == "bill":
            return 100.0 / (1.0 + yc) ** (self.days / 365.0)
        if self.flows:
            g = 1.0 + self.simple(yc) / self.freq
            return sum(cf * g ** -x for cf, x in self.flows)
        return self.bond.price(yc, self.value, "compound")[0]

    def clean(self, yc: float) -> Optional[float]:
        d = self.dirty(yc)
        return d - self.acc if d is not None else None

    def simple(self, yc: float) -> Optional[float]:
        """BIST's simple yield of the compound one: a coupon bond's ``f((1 + y)^(1/f) − 1)``, a bill's ``((1 + y)^t − 1)/t``."""
        if self.kind == "bill":
            t = (self.days or 0.0) / 365.0
            return ((1.0 + yc) ** t - 1.0) / t if t > 0 else None
        return self.freq * ((1.0 + yc) ** (1.0 / self.freq) - 1.0)

    def yield_of(self, clean: float) -> Optional[float]:
        """The compound yield (decimal) of a clean price, as the sheet works out its own (rvfair's)."""
        if not self.ok or clean is None or clean + self.acc <= 0:
            return None
        dirty = clean + self.acc
        if self.kind == "bill":
            return rvfair.bill_yield(dirty, self.days)
        if self.flows:
            ys = rvfair.coupon_yield(dirty, self.flows, self.freq, self.guess)
            return (1.0 + ys / self.freq) ** self.freq - 1.0 if ys is not None else None
        return self.bond.yield_of(dirty, self.value, "compound", self.guess)


# ---------------------------------------------------------------------------------------------- the text
def _n(v: float, d: int) -> str:
    return ("%.*f" % (d, v)).replace(".", ",")


def _bp(v: float) -> str:
    """A signed bp figure: "+8", "−42"."""
    r = int(round(v))
    return ("+%d" % r) if r >= 0 else ("−%d" % -r)


def _day(iso: str) -> str:
    return "%s.%s" % (iso[8:10], iso[5:7])


def previous_weekday(d: _dt.date) -> _dt.date:
    d -= _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d


def how_line(parts: Sequence[Dict[str, Any]], fair: float, clean: Optional[float], value: Optional[str], today: _dt.date) -> str:
    """How a fair was built, in a line: each base, the spread at the last close, the weights, the fair and the price
    ("Komşu eğri 37,62 + dünkü fark +8 bp = 37,70 · OIS 38,10 − 42 bp = 37,68 · %75 / %25 → adil 37,69 · fiyat 98,452
    (valör 20.11)").  ``parts``: ``{"base", "now", "spread", "day", "weight"}`` (per cent, bp)."""
    yesterday = previous_weekday(today).isoformat()
    bits = []
    for k, p in enumerate(parts):
        sp = p["spread"]
        if k == 0:                                         # the first says what the spread is: the last close's
            what = "dünkü fark" if p["day"] == yesterday else "%s kapanışındaki fark" % _day(p["day"])
            spread = "+ %s %s bp" % (what, _bp(sp))
        else:
            spread = "%s %d bp" % ("+" if round(sp) >= 0 else "−", abs(int(round(sp))))
        bits.append("%s %s %s = %s" % (BASE_TEXT[p["base"]], _n(p["now"], 2), spread, _n(p["now"] + sp / 100.0, 2)))
    weights = " / ".join("%%%d" % int(round(p["weight"] * 100)) for p in parts)
    tail = "adil %s" % _n(fair, 2)
    if clean is not None:
        tail += " · fiyat %s" % _n(clean, 3) + (" (valör %s)" % _day(value) if value else "")
    return " · ".join(bits) + " · %s → %s" % (weights, tail)


# ---------------------------------------------------------------------------------------------- the service's part
class KagitFiyat(object):
    """The page's data (``GET /api/kagit-fiyat``) and the administrators' widths (``POST /api/kagit-fiyat/genislik``)."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()                                     # one build of the closes' part at a time
        self._panel: Optional[Tuple[Any, Dict[str, Any]]] = None           # (what it was built of, the result)
        self._days: Dict[str, Tuple[Any, Dict[str, Any]]] = {}             # a past day's bases, by what they are made of
        self._tau: Optional[Tuple[Any, qc.Nss]] = None                     # (the day and bonds searched on, the τ)
        self._now_lock = threading.Lock()
        self._now: List[Tuple[Any, Dict[str, Any]]] = []                   # fits of the quotes now (the latest last)
        self._now_tau: Optional[Tuple[Any, Optional[qc.Nss]]] = None        # (the bonds and day, the τ) without a history

    # ------------------------------------------------------------------ the widths (administrators)
    def widths(self) -> Dict[str, Any]:
        out: Dict[str, Any] = dict(WIDTH_DEFAULT)
        saved = self.svc.store.get(KEY_WIDTHS)
        if isinstance(saved, dict):
            out.update({k: float(v) for k, v in saved.items() if k in WIDTH_DEFAULT and isinstance(v, (int, float))})
            out.update({k: saved[k] for k in ("by", "at") if k in saved})
        return out

    def set_widths(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """The administrators' widths by bucket (bp, bid to ask): ``{"widths": {"1y": 10, ...}}``; every change logged."""
        key = self.svc.require_admin(user)
        raw = (body or {}).get("widths") if isinstance(body, dict) else None
        if not isinstance(raw, dict) or not raw:
            raise KagitError("genişlikler anlaşılamadı")
        cur = self.widths()
        parts = []
        for name, v in raw.items():
            if name not in WIDTH_DEFAULT:
                raise KagitError("bilinmeyen vade kovası: %r" % name)
            try:
                x = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                raise KagitError("%s genişliği bir sayı olmalı" % BUCKET_TEXT[name])
            if not (math.isfinite(x) and 0.0 <= x <= WIDTH_MAX):
                raise KagitError("%s genişliği 0 – %g bp arasında olmalı" % (BUCKET_TEXT[name], WIDTH_MAX))
            x = round(x, 1)
            if x != cur[name]:
                parts.append("%s %s → %s bp" % (BUCKET_TEXT[name], _n(cur[name], 1), _n(x, 1)))
            cur[name] = x
        stamp = _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
        self.svc.store.put(KEY_WIDTHS, dict({k: cur[k] for k in WIDTH_DEFAULT}, by=key, at=stamp))
        if parts:
            log = (self.svc.store.get(KEY_LOG) or []) + [{"at": stamp, "by": key, "text": "Kotasyon genişliği: " + "; ".join(parts)}]
            self.svc.store.put(KEY_LOG, log[-LOG_MAX:])
        self.svc.bump()
        return {"widths": self.widths(), "log": self.log()}

    def log(self, limit: int = 10) -> List[Dict[str, Any]]:
        return list(reversed((self.svc.store.get(KEY_LOG) or [])[-limit:]))

    # ------------------------------------------------------------------ made ahead (the dashboard's own server)
    def warm(self) -> None:
        """The closes' part made ahead, in a thread of its own: ``WARM_DELAY`` after the start (the first pages come
        first), then whenever the history has changed (looked at every ``WARM_EVERY``) - the first trader of the day does
        not wait for a year of curves.  An optimisation only: a page builds what is not there."""
        stop = self.svc._stop
        if stop.wait(WARM_DELAY):
            return
        while not stop.is_set():
            try:
                et = self.svc.et
                got = et.call_at(et.BACKGROUND, self._read, None)
                if got is not None:
                    self.closes(got)
            except Exception:  # noqa: BLE001 - a page builds it when asked
                pass
            if stop.wait(WARM_EVERY):
                return

    # ------------------------------------------------------------------ the page
    def view(self, user: Optional[str], isin: Optional[str] = None) -> Dict[str, Any]:
        """Every bond of the trading list priced (``isin``: that one alone - the bond card's block; one not on the list
        is a 400 with the reason)."""
        svc = self.svc
        key = svc.require_user(user)
        t0 = time.perf_counter()
        got = svc.et.call(self._read, key)
        if got is None:
            return {"ok": False, "why": "DİBS RV sayfası yok", "gen": svc.gen}
        code = rvfair.isin_of(isin) if isin is not None else None
        if isin is not None and not any(line["isin"] == code for line in got["lines"]):
            raise KagitError("kâğıt trading listesinde değil: %s" % (code or str(isin).strip() or "—"))
        panel = self.closes(got)
        now = self.now_fit(got, panel)
        widths = self.widths()
        bonds = self._bonds(got)
        rows = []
        for line in got["lines"]:
            if code is not None and line["isin"] != code:
                continue
            rows.append(self._row(line, got, panel, now, widths, bonds))
        order = {k: i for i, (k, _) in enumerate(KINDS)}
        rows.sort(key=lambda r: (order.get(r["kind"], 9), r.get("maturity") or "9999", r["isin"]))
        hist = {k: panel.get(k) for k in ("first", "last", "days", "tau", "tau_day", "ms", "ois_days", "why", "built")}
        return {"ok": True, "rows": rows, "kinds": [{"kind": k, "title": t} for k, t in KINDS], "widths": widths,
                "admin": svc._is_admin(key), "log": self.log() if svc._is_admin(key) else [], "history": hist,
                "fit": {k: now.get(k) for k in ("ok", "why", "n_fit", "n", "tau_from")},
                "rules": {"weights": WEIGHTS, "floor": SIGMA_FLOOR, "buckets": [{"key": k, "text": t, "top": top} for k, t, top in BUCKETS],
                          "band": BAND, "noise": NOISE, "revert": REVERT, "window": SIGMA_WINDOW, "min": SIGMA_MIN,
                          "median": MEDIAN_DAYS},
                "today": got["today"].isoformat(), "time": _dt.datetime.now().strftime("%H:%M:%S"), "gen": got["gen"],
                "ms": round((time.perf_counter() - t0) * 1000.0, 1)}

    # ------------------------------------------------------------------ the engine thread: what the sheets have now
    def _read(self, user: str) -> Optional[Dict[str, Any]]:
        from . import bonds as bd
        from . import extras as ex
        from . import pricing as pr
        from .xl.model import COLS, parse_a1
        from .xl.values import serial_to_date
        svc = self.svc
        book = svc.books.get("tto")
        if book is None or "DİBS RV" not in book.model.sheet_index:
            return None
        index = book.model.sheet_index
        si = index["DİBS RV"]
        calc = svc._calc(user, book)
        live_sheet = index.get(ex.LIVE_SHEET)

        def raw(c: str, r: int, s: int = si) -> Any:
            return calc.get(s, r, parse_a1("%s1" % c) % COLS)

        eng: Dict[str, Any] = {}

        def reader(sheet: str):
            s = index[sheet]
            return lambda ref: calc.get(s, *divmod(parse_a1(ref), COLS))

        qc.read_engine(eng, index, reader, lambda v: v if type(v) is float and math.isfinite(v) else None)
        mk, boot = None, None
        if all(s in index for s in ("Motor", "OIS_MAIN", "Forward")):
            base = svc.interp.boot_of(book, calc)               # (the true Bootstrap whatever the user's setting)
            try:
                mk = pr.read(lambda sheet, r, c: base.get(index[sheet], r, c))
            except pr.PricingError:
                mk = None
            cv = svc._try_curves(book, calc)
            boot = (cv or {}).get("boot")
        said = svc._board_bonds(user) if user else {}
        cf0, x0, nflows = rvfair._col(rvfair.FLOWS[0]), rvfair._col(rvfair.FLOWS[1]), rvfair.FLOWS[2]
        lines: List[Dict[str, Any]] = []
        for r in range(rvfair.FIRST, rvfair.LAST + 1):
            code = rvfair.isin_of(raw("A", r))
            if not code:
                continue
            known = bd.by_isin(code)
            kind = {"bill": "B", "zero": "B", "fixed": "S", "float": "T", "frn": "F", "cpi": "E"}.get((known or {}).get("kind")) or raw("D", r)
            kind = kind if kind in dict(KINDS) else "S"
            mat = raw("E", r)
            maturity = serial_to_date(mat) if type(mat) is float and 20000 < mat < 80000 else (
                _dt.date.fromisoformat(known["maturity"]) if known and known.get("maturity") else None)
            label = raw("B", r, live_sheet) if live_sheet is not None else ""
            if not isinstance(label, str) or label.strip() in ("", code):
                label = bd.short_label(known) if known else code
            value, freq, acc, days, guess = raw("P", r), raw("CU", r), raw("CW", r), raw("DR", r), raw("DX", r)
            flows = []
            for k in range(nflows):
                cf, x = calc.get(si, r, cf0 + k), calc.get(si, r, x0 + k)
                if type(cf) is float and type(x) is float and cf != 0.0:
                    flows.append((cf, x))
            q = svc._rv_quote(calc, si, r)
            bid, ask = raw("K", r), raw("L", r)
            lines.append({"isin": code, "kind": kind, "label": label.strip(), "maturity": maturity, "row": r,
                          "value": serial_to_date(value) if type(value) is float and 20000 < value < 80000 else None,
                          "freq": freq if type(freq) is float and freq > 0 else 2.0, "acc": acc if type(acc) is float else 0.0,
                          "days": days if type(days) is float else None, "flows": flows if kind == "S" else [],
                          "guess": guess if type(guess) is float else 0.3,
                          "simple": raw("S", r) if type(raw("S", r)) is float else None,
                          "compound": raw("T", r) if type(raw("T", r)) is float else None,
                          "bid": bid if type(bid) is float else None, "ask": ask if type(ask) is float else None,
                          "bid_text": bid if isinstance(bid, str) else "", "ask_text": ask if isinstance(ask, str) else "",
                          "quote": {k: q[k] for k in ("bid", "ask", "stale", "status", "tip")},
                          "board": said.get(code)})
        return {"lines": lines, "quant": eng.get("dibs") or [], "live": qc.live_values(eng), "today": svc.history.today(),
                "mk": mk, "boot": boot, "gen": svc.gen}

    # ------------------------------------------------------------------ the closes' part (off the engine thread)
    def _bonds(self, got: Dict[str, Any]) -> Dict[str, qc.Bond]:
        """The bonds priced here (fixed coupon and bills of DİBS RV, not matured): ISIN -> quantcurve's ``Bond``."""
        out: Dict[str, qc.Bond] = {}
        for row in got["quant"]:
            b = qc._bond_of(row["isin"], {}, row)
            if b is not None and b.maturity > got["today"]:
                out[row["isin"]] = b
        return out

    def closes(self, got: Dict[str, Any]) -> Dict[str, Any]:
        """The closes' part of every bond (kept per revision of the history, the bonds and the OIS calendar): the history's
        axis, the τ, each bond's records - its compound yield and each base at every close before today - and what they
        say now (``bond_closes``)."""
        svc = self.svc
        today = got["today"]
        before = today.isoformat()
        bonds = self._bonds(got)
        rows = {r["isin"]: r for r in got["quant"]}
        snap = svc.history.snapshot()
        defs = {}
        for d in snap["defs"]:
            if d.group == "dibs" and d.unit == "pct":
                code = rvfair.isin_of(d.info.get("isin") or d.label)
                if code in bonds and code not in defs:
                    defs[code] = d
        start = (today - _dt.timedelta(days=HISTORY_DAYS)).isoformat()
        data = svc.store.hist_many([i for d in defs.values() for i in d.ids()], start)
        closes: Dict[str, Dict[str, float]] = {}
        conv: Dict[str, str] = {}
        for code, d in defs.items():
            points = d.pick(data)[1]
            row = rows.get(code) or {}
            last = points[max(points)] if points else None
            conv[code] = qc.detect_convention(last, qc._pct(row.get("simple")), qc._pct(row.get("compound")))
            closes[code] = {k: v for k, v in points.items() if k < before}
        mk = got["mk"]
        ois: Dict[float, Dict[str, float]] = {}
        hol: frozenset = frozenset()
        node_months: Tuple[float, ...] = ()
        quote_months: Tuple[float, ...] = ()
        if mk is not None:
            _, ois, hol, _ = svc._swaption_closes(mk)
            node_months = tuple(float(m) for m, _ in mk.nodes)
            quote_months = tuple(sorted(float(m) for m, _ in mk.ois_quotes))
        static = tuple(sorted((code, b.kind, b.maturity.isoformat(), b.coupon, b.freq, str(rows.get(code, {}).get("source") or ""),
                               conv.get(code, "simple")) for code, b in bonds.items()))
        mark = (svc.history.rev, before, static, node_months, quote_months, hash(hol), tuple(sorted(defs)))
        with self._lock:
            hit = self._panel
            if hit is not None and hit[0] == mark:
                return hit[1]
            t0 = time.perf_counter()
            res = self._build(bonds, rows, conv, closes, ois, node_months, quote_months, hol, today)
            res["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            res["built"] = _dt.datetime.now().strftime("%H:%M:%S")
            self._panel = (mark, res)
            return res

    def _build(self, bonds: Dict[str, qc.Bond], rows: Dict[str, Dict[str, Any]], conv: Dict[str, str],
               closes: Dict[str, Dict[str, float]], ois: Dict[float, Dict[str, float]], node_months: Sequence[float],
               quote_months: Sequence[float], hol: frozenset, today: _dt.date) -> Dict[str, Any]:
        from . import swaption as sw
        from .xl.values import date_to_serial
        days = sorted({d for s in closes.values() for d in s})
        out: Dict[str, Any] = {"recs": {}, "stats": {}, "first": days[0] if days else None, "last": days[-1] if days else None,
                               "days": len(days), "tau": None, "tau_day": None, "ois_days": 0}
        if not days:
            out["why"] = "kâğıtların geçmiş kapanışı yok (tarihçe dolunca gelir)"
            return out

        def items_of(iso: str) -> List[Tuple[qc.Bond, _dt.date, float, str]]:
            day = _dt.date.fromisoformat(iso)
            return [(b, qc._value_date(day, rows.get(code)), closes[code][iso] / 100.0, conv.get(code, "simple"))
                    for code, b in sorted(bonds.items()) if iso in closes.get(code, {}) and b.maturity > day]

        # the τ: searched once on the last close with enough coupon bonds to leave one out, then held for every day (and
        # for the quotes now) - each day's curves measured with one model
        good = None
        for iso in reversed(days):
            items = items_of(iso)
            fit_in = qc.BondFit(items)
            if fit_in.n_fit >= qc.MIN_BONDS + 1:
                good = (iso, items, tuple(sorted(fit_in.bonds[i].isin for i in fit_in.fitted)))
                break
        nss0 = None
        if good is not None:
            tau_key = good[0], good[2]
            if self._tau is not None and self._tau[0] == tau_key:
                nss0 = self._tau[1]
            else:
                found = qc.dibs_search(qc.BondFit(good[1]))
                if found is not None:
                    nss0 = found["nss"]
                    self._tau = (tau_key, nss0)
            out["tau"] = {"tau1": nss0.tau1, "model": nss0.model} if nss0 is not None else None
            out["tau_day"] = good[0]
            out["nss0"] = nss0
        else:
            out["why_nbr"] = "geçmişte komşu eğri kurulamadı: bir günde en az %d sabit kuponlu kâğıdın kapanışı gerekli" % (qc.MIN_BONDS + 1)
        listed = [m for m in quote_months if m in ois]
        kept = {}
        for iso in days:
            items = items_of(iso)
            quotes = tuple((m, ois[m][iso] / 100.0) for m in listed if iso in ois[m])
            full = len(quotes) == len(quote_months) and quotes
            sig = (tuple((b.isin, v.isoformat(), y, c) for b, v, y, c in items), quotes if full else None,
                   (nss0.tau1, nss0.tau2, nss0.k, tuple(nss0.beta)) if nss0 is not None else None, tuple(node_months), hash(hol))
            hit = self._days.get(iso)
            if hit is not None and hit[0] == sig:
                res = hit[1]
            else:
                res = {"nbr": {}, "ois": {}}
                if nss0 is not None:
                    res["nbr"] = neighbours(items, nss0)["nbr"]
                if full:
                    try:
                        spot, curve = sw.day_curve(float(date_to_serial(_dt.date.fromisoformat(iso))), quotes, node_months, hol)
                    except ValueError:
                        curve = None
                    if curve is not None:
                        for b, _, _, _ in items:
                            z = zero_rate(curve, spot, float(date_to_serial(b.maturity)))
                            if z is not None:
                                res["ois"][b.isin] = z
            kept[iso] = (sig, res)
            if res["ois"]:
                out["ois_days"] += 1
            day = _dt.date.fromisoformat(iso)
            for b, value, y, c in items:
                rec = {"day": iso, "t": (b.maturity - day).days / qc.YEAR, "y": to_compound(b, y, value, c),
                       NBR: res["nbr"].get(b.isin), OIS: res["ois"].get(b.isin)}
                if rec[NBR] is None and rec[OIS] is None:
                    continue
                out["recs"].setdefault(b.isin, []).append(rec)
        self._days = dict(list(kept.items())[-DAYS_KEPT:])
        pos = {d: i for i, d in enumerate(days)}
        for code, recs in out["recs"].items():
            b = bonds[code]
            out["stats"][code] = bond_closes(recs, pos, bucket_of((b.maturity - today).days / qc.YEAR))
        return out

    # ------------------------------------------------------------------ the quotes now
    def now_fit(self, got: Dict[str, Any], panel: Dict[str, Any]) -> Dict[str, Any]:
        """The neighbours' curve at each bond now (``neighbours`` on DİBS RV's yields now, the history's τ held - or
        searched on them when the history has none), kept per what it is made of."""
        from .dibsgenel import bond_inputs
        today = got["today"]
        items, _ = bond_inputs(got["quant"], got["live"], today)
        have = {b.isin for b, _, _, _ in items}
        rows = {r["isin"]: r for r in got["quant"]}
        extra = [(b, qc._value_date(today, rows.get(code))) for code, b in sorted(self._bonds(got).items()) if code not in have]
        nss0 = panel.get("nss0")
        tau_from = "geçmiş" if nss0 is not None else "şimdi"
        key = (tuple((b.isin, v.isoformat(), y, c) for b, v, y, c in items), tuple((b.isin, v.isoformat()) for b, v in extra),
               (nss0.tau1, nss0.tau2, tuple(nss0.beta)) if nss0 is not None else None)
        with self._now_lock:
            for k, res in self._now:
                if k == key:
                    return res
        if nss0 is None:
            # no history: the τ searched on the quotes now - again only when the bonds or the day change (as Genel's)
            fit_in = qc.BondFit(items)
            bonds_key = (today.isoformat(), tuple(sorted(fit_in.bonds[i].isin for i in fit_in.fitted)))
            hit = self._now_tau
            if hit is not None and hit[0] == bonds_key:
                nss0 = hit[1]
            elif fit_in.n_fit >= qc.MIN_BONDS + 1:
                found = qc.dibs_search(fit_in)
                nss0 = found["nss"] if found is not None else None
                self._now_tau = (bonds_key, nss0)
        if nss0 is None:
            res = {"ok": False, "nbr": {}, "why": "komşu eğri kurulamadı: en az %d sabit kuponlu kâğıdın getirisi gerekli" % (qc.MIN_BONDS + 1),
                   "n_fit": qc.BondFit(items).n_fit, "n": len(items), "tau_from": tau_from}
        else:
            res = neighbours(items, nss0, extra)
            res["ok"] = "why" not in res
            res["tau_from"] = tau_from
            res.pop("nss", None)
        with self._now_lock:
            self._now = [x for x in self._now if x[0] != key][-(NOW_KEPT - 1):] + [(key, res)]
        return res

    # ------------------------------------------------------------------ a bond's row
    def _pricer(self, line: Dict[str, Any], bond: Optional[qc.Bond], today: _dt.date) -> Pricer:
        kind = "bill" if line["kind"] == "B" else "fixed"
        value = line["value"] or (qc._value_date(today, None) if bond is not None else None)
        days = line["days"]
        if kind == "bill" and not days and bond is not None and value is not None:
            days = float((bond.maturity - value).days)
        acc = line["acc"] if line["flows"] or kind == "bill" else (qc.accrued(bond, value) if bond is not None and value else line["acc"])
        return Pricer(kind, value, days, line["freq"], line["flows"], acc, bond, line["guess"])

    def _row(self, line: Dict[str, Any], got: Dict[str, Any], panel: Dict[str, Any], now: Dict[str, Any],
             widths: Dict[str, Any], bonds: Dict[str, qc.Bond]) -> Dict[str, Any]:
        today = got["today"]
        code = line["isin"]
        mat = line["maturity"]
        years = (mat - today).days / qc.YEAR if mat else None
        out: Dict[str, Any] = {"isin": code, "kind": line["kind"], "label": line["label"], "maturity": mat.isoformat() if mat else None,
                               "years": years, "priced": False}
        if years is not None:
            out["bucket"] = bucket_of(years)
            out["bucket_text"] = BUCKET_TEXT[out["bucket"]]
        if line["kind"] in NOT_PRICED:
            out["why"] = NOT_PRICED[line["kind"]]
            return out
        if mat is None or years is None or years <= 0:
            out["why"] = "vadesi bilinmiyor ya da geçmiş"
            return out
        bond = bonds.get(code)
        if bond is None:
            out["why"] = "DİBS RV kâğıdı hesaplamıyor (vade / kupon bilinmiyor)"
            return out
        bucket = out["bucket"]
        pricer = self._pricer(line, bond, today)
        out["value_date"] = pricer.value.isoformat() if pricer.value else None
        if line["compound"] is not None:
            out["yield"] = line["compound"] * 100.0
        st = panel["stats"].get(code) or {}
        last = st.get("last")
        # each base now
        now_base: Dict[str, Optional[float]] = {NBR: now.get("nbr", {}).get(code), OIS: None}
        mk, boot = got["mk"], got["boot"]
        if mk is not None and boot is not None:
            from .xl.values import date_to_serial
            now_base[OIS] = zero_rate(boot, mk.ois_spot, float(date_to_serial(mat)))
        out["bases"] = {b: {"name": BASE_TEXT[b], "now": now_base[b] * 100.0 if now_base[b] is not None else None,
                            "weight": WEIGHTS[bucket].get(b, 0.0)} for b in BASES}
        if last is None:
            out["why"] = ("son kapanışta farkı yok: kâğıdın geçmiş kapanışı yok (tarihçe dolunca gelir)" if not st
                          else "son kapanışta hiçbir taban kurulamadı")
            if panel.get("why") and not st:
                out["why"] = "adil getiri kurulamadı: " + panel["why"]
            return out
        have = [b for b in BASES if now_base[b] is not None and b in last["spread"]]
        w = weights_of(bucket, have)
        for b in BASES:
            x = out["bases"][b]
            if b in last["spread"]:
                x["spread"] = last["spread"][b] * BP
                x["close"] = last["base"][b] * 100.0
            x["day"] = last["day"]
            x["used"] = w.get(b, 0.0)
            if WEIGHTS[bucket].get(b, 0.0) > 0 and b not in w:
                x["why"] = ("şimdi kurulamadı" + (": " + now["why"] if b == NBR and now.get("why") else "")) if now_base[b] is None \
                    else "son kapanışta (%s) kurulamadı" % _day(last["day"])
        if not w:
            out["why"] = "tabanlar kurulamadı: " + "; ".join("%s %s" % (BASE_TEXT[b], out["bases"][b].get("why") or "yok")
                                                           for b in BASES if WEIGHTS[bucket].get(b, 0.0) > 0)
            return out
        missing = [b for b in BASES if WEIGHTS[bucket].get(b, 0.0) > 0 and b not in w]
        if missing:
            out["note"] = " · ".join("%s payı (%%%d) %s geçti: %s %s" % (BASE_TEXT[b], int(round(WEIGHTS[bucket][b] * 100)),
                                                                     " ve ".join(BASE_TO[x] for x in w), BASE_TEXT[b],
                                                                     out["bases"][b].get("why") or "yok") for b in missing)
        fair = sum(x * (now_base[b] + last["spread"][b]) for b, x in w.items())
        sigma = st["sigma"]["sigma"]
        width = float(widths.get(bucket, WIDTH_DEFAULT[bucket]))

        def level(yc: float) -> Dict[str, Any]:
            s, c = pricer.simple(yc), pricer.clean(yc)
            return {"yield": yc * 100.0, "simple": s * 100.0 if s is not None else None, "clean": c}

        out["priced"] = True
        out["fair"] = level(fair)
        out["quote"] = {"width": width, "bid": level(fair + width / 2.0 / BP), "ask": level(fair - width / 2.0 / BP)}
        out["levels"] = {"buy": level(fair + BAND * sigma / BP), "sell": level(fair - BAND * sigma / BP),
                         "noise": [level(fair - NOISE * sigma / BP), level(fair + NOISE * sigma / BP)]}
        out["sigma"] = dict(st["sigma"], bucket_floor=SIGMA_FLOOR[bucket])
        out["backtest"] = st["backtest"]
        out["closes"] = st["n"]
        parts = [{"base": b, "now": now_base[b] * 100.0, "spread": last["spread"][b] * BP, "day": last["day"], "weight": w[b]}
                 for b in BASES if b in w]
        out["line"] = how_line(parts, fair * 100.0, out["fair"]["clean"], out["value_date"], today)
        if line["compound"] is not None:
            out["z"] = (line["compound"] - fair) * BP / sigma
        # Bağlam: the spread to the neighbours' curve now against its 20-day median
        if now_base[NBR] is not None and line["compound"] is not None:
            ctx = {"now": (line["compound"] - now_base[NBR]) * BP}
            if st.get("median"):
                ctx.update(median=st["median"]["bp"], n=st["median"]["n"])
            out["context"] = ctx
        out["market"] = self._market(line, pricer, fair, sigma)
        return out

    @staticmethod
    def _market(line: Dict[str, Any], pricer: Pricer, fair: float, sigma: float) -> List[Dict[str, Any]]:
        """The market now against fair: the Broker Chat board's best fresh bid / offer and the live Bloomberg bid / ask
        (DİBS RV!K / L), each as a compound yield, its distance from fair in σ and AL (an offer at fair + 2σ or above) /
        SAT (a bid at fair − 2σ or below)."""
        out = []

        def add(src: str, side: str, y: Optional[float], price: Optional[float], **extra: Any) -> None:
            if y is None:
                return
            z = (y - fair) * BP / sigma
            sig = "AL" if side == "ask" and z >= BAND - 1e-9 else ("SAT" if side == "bid" and z <= -BAND + 1e-9 else "")
            out.append(dict({"src": src, "side": side, "yield": y * 100.0, "price": price, "z": z, "signal": sig}, **extra))

        q = line.get("board") or {}
        unit = q.get("unit") or "px"
        for side in ("bid", "ask"):
            v = q.get("best_" + side)
            if type(v) is not float:
                continue
            extra = {"who": q.get("best_%s_by" % side) or "", "age": q.get("best_%s_age" % side)}
            if unit == "yld":
                add("broker", side, v / 100.0, None, **extra)
            else:
                add("broker", side, pricer.yield_of(v), v, **extra)
        qt = line.get("quote") or {}
        for side in ("bid", "ask"):
            px = line.get(side)
            size = qt.get(side)
            if type(px) is not float or (type(size) is float and size <= 0):
                continue                                  # (no order stands on that side: "–" on DİBS RV)
            add("bbg", side, pricer.yield_of(px), px, size=size if type(size) is float else None)
        return out
