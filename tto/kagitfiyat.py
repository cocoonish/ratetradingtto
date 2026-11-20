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

**Öngörülen** (the desk, the same evening: "Bu adil fiyat bir süre sonra ulaşmasını tahmin ettiğimiz fiyat gibi de olmalı.
Bir adil fiyat, bir de öngörülen fiyat olacak yani, OIS ve FX swap curve'üne göre fiyatları da ayrıca gösterilsin"): the
yield and price the bond is expected to reach 5, 10 or 20 closes on (``HORIZONS``; the page's switch), by the model the
desk's history chose for its bucket and the horizon (``PROJECTION``, measured out of sample - docs/desk-decisions.md):
M0 no change, M1 the spread to the neighbours' curve back toward its mean (AR(1)), M2 the roll-down alone ("eğri ve fark
değişmezse"), M3 both, M4 M3 plus β × the OIS forward's move (``project``).  The rule fixed before measuring (``choose``):
the lowest RMSE where it beats no change by 5 %; else M2, and the page says no model beat no change there.  Its price is
the clean price at the horizon's value date; its record shown beside it (``record_text``).

**OIS'e göre / FX swap'a göre**: DİBS Trading's fair yield and price of the bond on DİBS RV's OIS ASW curve and on DİBS
ASW's FX swap one - ``rvfair``'s, with the trading summary's own cells (``asw_side``), not worked out again.

**Eğri fiyatı - the main table** (the desk, 20.11.2026: "Kağıt fiyatlama kısmını çok anlayamadım, curve'e göre fiyatı
olmayanların da fiyatını bulmak içindi asıl"): every fixed coupon bond, bill and zero coupon bond of the desk's list (and
the trading list's), not only the trading list (``_universe``): today's market price - a two-sided quote's middle, else
today's last trade (``market_of``; DİBS RV's for the trading list, Tüm Kâğıtlar's for the rest) -, the curve (the
Nelson-Siegel of the quotes now, at the bond's own cash flows; the fit without the bond for a bond in it) and the answer
with its label (``_curve_row``): "piyasa", else "eğri + son fark <day>" (the curve + the bond's spread to it at its last
close - a bond off the list: when the history kept its series, ``_off_closes`` / ``_off_spreads``), else "eğri".  Kâğıt
Fiyat Yükleme takes the answer without the market for a row that would get no price (``curve_quotes``).  The trading
list's rows above are the main table's details (▸), unchanged; floaters, CPI linkers and FRNs are counted, not priced.

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

#: Eğri fiyatı (the desk, 20.11.2026: "Kağıt fiyatlama kısmını çok anlayamadım, curve'e göre fiyatı olmayanların da fiyatını
#: bulmak içindi asıl"): the kinds of the desk's bond list priced off the curve - fixed coupon bonds, bills, zero coupon bonds
CURVE_KINDS = ("fixed", "bill", "zero")
#: the labels of a bond's price (the main table's "Fiyat"): its market's; the curve plus its last known spread to the curve
#: (the desk's history: the bond's last spread is the best predictor); the curve alone
PIYASA, EGRI_FARK, EGRI = "piyasa", "eğri + son fark", "eğri"
#: a bond with no price and no history of its own: its bucket's base + the median spread to it of today's market-priced
#: bonds of its bucket and kind group (the coordinator's fix of 20.11.2026: a bill read off the coupon curve's short end
#: alone was 136–255 bp too high in yield)
EGRI_AKRAN = "eğri + akran farkı"
#: the kind groups peers are taken from: bills and zero coupon bonds together, fixed coupon bonds apart
GROUP_TEXT = {"B": "bono / kuponsuz", "S": "sabit kuponlu"}
#: the catalog's kinds not priced off a nominal curve (one line under the table, with their counts)
OTHER_KINDS = (("float", "TLREF'e endeksli"), ("cpi", "TÜFE'ye endeksli"), ("frn", "FRN"))
OTHERS_WHY = "kuponları değişken ya da reel: nominal eğriye göre fiyatlanmaz"

#: Öngörülen - the horizons a projection is made for (closes: TRY business days) and their captions on the switch
HORIZONS: Tuple[Tuple[int, str], ...] = ((5, "1 hafta"), (10, "2 hafta"), (20, "1 ay"))
#: the models measured on the desk's history (``project``); each on the bond's spread to the neighbours' curve
M0, M1, M2, M3, M4 = "M0", "M1", "M2", "M3", "M4"
MODEL_TEXT = {M0: "değişmez", M1: "fark ortalamasına döner", M2: "eğri ve fark değişmezse",
              M3: "fark ortalamasına döner + vade kısalır", M4: "fark ortalamasına döner + vade kısalır + OIS forward'ı"}
AR_WINDOWS = (60, 120)                # the closes an AR(1) / β is fitted on (rolling)
AR_MIN = 20                           # pairs of consecutive closes an AR(1) / β needs in its window
MOVE_MIN = 5.0                        # bp: a projection "says the yield moves" (the hit rate's calls) from this far on
BEAT = 0.05                           # a model is used where its RMSE beats no change (M0) by this share or more


def _rec(model: str, window: int, rmse: float, m0: float, hit: Optional[float], calls: int, n: int, beat: bool, best: str,
         gain: float, m2: Tuple[float, Optional[float], int]) -> Dict[str, Any]:
    return {"model": model, "window": window, "rmse": rmse, "m0": m0, "hit": hit, "calls": calls, "n": n, "beat": beat,
            "best": best, "gain": gain, "m2": {"rmse": m2[0], "hit": m2[1], "calls": m2[2]}}


#: Öngörülen's model by bucket and horizon and its record - measured on the desk's history (a backup copy of its
#: database of 19.11.2026: 16 DİBS, 14 fixed coupon and 2 bills, 10.11.2025–16.11.2026; every forecast out of sample,
#: its parameters from the bond's closes up to the forecast day; one sample for every model: from a bond's 120th close
#: on; docs/desk-decisions.md).  The rule, fixed before measuring: the model with the lowest RMSE where it beats no change
#: (M0) by ``BEAT`` or more (``beat``); where none does, M2 - "eğri ve fark değişmezse" - and the page says so.  Each:
#: the model and its window (closes), its RMSE and M0's (bp of the compound yield), the hit rate of its calls (a move of
#: ``MOVE_MIN`` or more said: did the yield go that way), the calls, the forecasts, the best model and its gain over M0
#: (%), and M2's own RMSE / hit rate / calls (shown when a bond cannot have the model now)
PROJECTION: Dict[str, Dict[int, Dict[str, Any]]] = {
    "1y": {5: _rec(M2, 0, 84.4, 86.1, 0.689, 151, 235, False, "M2", 1.9, (84.4, 0.689, 151)),
           10: _rec(M2, 0, 120.1, 123.6, 0.672, 183, 216, False, "M2", 2.8, (120.1, 0.672, 183)),
           20: _rec(M4, 120, 165.8, 179.0, 0.706, 177, 181, True, "M4/120", 7.4, (169.9, 0.732, 168))},
    "3y": {5: _rec(M2, 0, 86.7, 86.6, 0.125, 8, 322, False, "M4/60", 0.4, (86.7, 0.125, 8)),
           10: _rec(M2, 0, 120.1, 120.0, 0.536, 97, 312, False, "M4/60", 1.4, (120.1, 0.536, 97)),
           20: _rec(M4, 60, 149.0, 163.8, 0.637, 259, 276, True, "M4/60", 9.0, (165.8, 0.498, 221))},
    "5y": {5: _rec(M2, 0, 77.6, 77.5, 0.0, 2, 315, False, "M4/60", -0.0, (77.6, 0.0, 2)),
           10: _rec(M2, 0, 101.4, 101.4, 0.408, 142, 308, False, "M2", -0.0, (101.4, 0.408, 142)),
           20: _rec(M2, 0, 133.4, 132.2, 0.477, 279, 279, False, "M2", -0.9, (133.4, 0.477, 279))},
    "5y+": {5: _rec(M2, 0, 70.9, 71.0, None, 0, 362, False, "M2", 0.1, (70.9, None, 0)),
            10: _rec(M2, 0, 94.5, 94.7, None, 0, 349, False, "M2", 0.3, (94.5, None, 0)),
            20: _rec(M2, 0, 121.6, 122.0, 0.5, 38, 323, False, "M2", 0.3, (121.6, 0.5, 38))},
}
#: the horizon the page opens on: the best gain over M0, pooled over the buckets (each its own model): 1 ay +4,6 %
#: (1 hafta +0,4 %, 2 hafta +0,7 %)
DEFAULT_H = 20
RECORD_TEXT = "masanın geçmişi 10.11.2025–16.11.2026, 16 kâğıt, örnek dışı"


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


def market_of(bid: Any, ask: Any, last: Any, day: Optional[_dt.date], today: _dt.date) -> Optional[Tuple[float, str]]:
    """Today's market clean price of a bond and what it is: the middle of a two-sided quote (both sides a price - a side
    where no order stands is "–" on DİBS RV and Tüm Kâğıtlar), else today's last trade; else none."""
    b = bid if type(bid) is float and bid > 0 else None
    a = ask if type(ask) is float and ask > 0 else None
    if b is not None and a is not None:
        return (b + a) / 2.0, "bid / ask ortası"
    if type(last) is float and last > 0 and day == today:
        return last, "son işlem (bugün)"
    return None


def base_of(bucket: str, ns: Optional[float], ois: Optional[float]) -> Tuple[Optional[float], Dict[str, float]]:
    """The base of a bond with no price, by its bucket, with the fair model's constants (``WEIGHTS``): 1Y and under 75 % the
    OIS zero rate + 25 % the Nelson-Siegel curve, 1–5Y the curve, beyond 5Y 75 % the curve + 25 % OIS - what the desk's
    history found the bonds follow (a base that cannot be had gives its share to the other): ``(base, weights)``."""
    vals = {NBR: ns, OIS: ois}
    w = weights_of(bucket, [b for b in BASES if vals[b] is not None])
    if not w:
        return None, {}
    return sum(x * vals[b] for b, x in w.items()), w


def base_text(w: Dict[str, float]) -> str:
    """A base's make-up in words: "OIS %75 + eğri %25", "eğri"."""
    if len(w) == 1:
        return "eğri" if NBR in w else "OIS"
    return " + ".join("%s %%%d" % ("eğri" if b == NBR else "OIS", int(round(x * 100))) for b, x in sorted(w.items(), key=lambda kv: -kv[1]))


def peer_spread(peers: Sequence[Tuple[str, float]], exclude: str = "") -> Tuple[Optional[float], int]:
    """The median of the peers' spreads to their bases (decimal) - the bond itself left out - and how many peers."""
    xs = [s for code, s in peers if code != exclude]
    return (statistics.median(xs), len(xs)) if xs else (None, 0)


def validate(items: Sequence[Tuple[qc.Bond, _dt.date, float, str]], nss0: qc.Nss, cands: Sequence[Dict[str, Any]]
             ) -> Dict[str, Dict[str, Any]]:
    """Each market-priced bond priced as if it had no price and no history, leave one out - itself out of the curve's fit
    (the fit of ``items``: the quotes now, the model and τ of ``nss0`` held) and out of its peers, each peer's curve fitted
    without the bond and without the peer -: ``before`` the Nelson-Siegel curve alone at its cash flows, ``after`` its
    bucket's base (``base_of``) + the median spread of its peers (same bucket, same kind group) to their bases; against its
    market yield (decimals, compound).  ``cands``: ``{"isin", "bond", "value", "market", "ois", "bucket", "group"}``."""
    fit_in = qc.BondFit(items)
    at = {fit_in.bonds[i].isin: i for i in fit_in.fitted}
    full = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)["nss"]
    kept: Dict[frozenset, Optional[qc.Nss]] = {frozenset(): full}

    def curve_without(codes: Sequence[str]) -> Optional[qc.Nss]:
        drop = frozenset(at[c] for c in codes if c in at)
        if drop not in kept:
            idx = [i for i in fit_in.fitted if i not in drop]
            if len(idx) < qc.MIN_BONDS:
                kept[drop] = None
            else:
                def make(t1: float, t2: float, idx: List[int] = idx) -> Tuple[Any, Any]:
                    return fit_in._fn(idx, t1, t2), (lambda k=qc.NSS: list(full.beta[:k]))
                kept[drop] = qc.refit(make, full, full.beta, iters=8)["nss"]
        return kept[drop]

    def ns_of(c: Dict[str, Any], curve: Optional[qc.Nss]) -> Optional[float]:
        return yield_on(c["bond"], curve, c["value"], "compound", c["market"]) if curve is not None else None

    out: Dict[str, Dict[str, Any]] = {}
    for x in cands:
        ns_x = ns_of(x, curve_without([x["isin"]]))
        base_x, w = base_of(x["bucket"], ns_x, x["ois"])
        spreads = []
        for p in cands:
            if p["isin"] == x["isin"] or p["bucket"] != x["bucket"] or p["group"] != x["group"]:
                continue
            base_p, _ = base_of(p["bucket"], ns_of(p, curve_without([x["isin"], p["isin"]])), p["ois"])
            if base_p is not None:
                spreads.append(p["market"] - base_p)
        after = None if base_x is None else base_x + (statistics.median(spreads) if spreads else 0.0)
        out[x["isin"]] = {"market": x["market"], "before": ns_x, "after": after, "base": base_x, "weights": w, "peers": len(spreads),
                          "bucket": x["bucket"], "group": x["group"],
                          "err_before": (ns_x - x["market"]) * BP if ns_x is not None else None,
                          "err_after": (after - x["market"]) * BP if after is not None else None}
    return out


def validation_table(res: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``validate``'s errors per bucket and kind group: how many bonds, the median and the largest absolute error (bp),
    before (the curve alone) and after (the base + the peers' spread)."""
    out = []
    for key, _, _ in BUCKETS:
        for g in ("B", "S"):
            xs = [r for r in res.values() if r["bucket"] == key and r["group"] == g]
            if not xs:
                continue
            row: Dict[str, Any] = {"bucket": key, "bucket_text": BUCKET_TEXT[key], "group": g, "group_text": GROUP_TEXT[g], "n": len(xs),
                                   "no_peer": sum(1 for r in xs if not r["peers"])}
            for k in ("before", "after"):
                errs = [abs(r["err_" + k]) for r in xs if r["err_" + k] is not None]
                row[k] = {"median": statistics.median(errs) if errs else None, "max": max(errs) if errs else None}
            out.append(row)
    return out


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
def yield_on(b: qc.Bond, nss: qc.Nss, value: _dt.date, conv: str, guess: Optional[float]) -> Optional[float]:
    """The bond's compound yield on a curve at a value date: its cash flows after that date discounted on the curve (their
    times counted from it), the yield of that price read in ``conv`` and compounded."""
    flows, _ = b.flows(value)
    if not flows:
        return None
    pm = sum(cf * nss.df((d - value).days / qc.YEAR) for d, cf in flows)
    ym = b.yield_of(pm, value, conv, guess)
    if ym is None or not math.isfinite(ym):
        return None
    return to_compound(b, ym, value, conv)


def neighbours(items: Sequence[Tuple[qc.Bond, _dt.date, float, str]], nss0: qc.Nss,
               extra: Sequence[Tuple[qc.Bond, _dt.date]] = (),
               ahead: Optional[Dict[str, Dict[int, _dt.date]]] = None) -> Dict[str, Any]:
    """Each bond against the curve of the others: the Nelson-Siegel curve of the fixed coupon bonds of ``items`` (bond,
    value date, yield, its convention) - quantcurve's fit, the model and τ of ``nss0`` held, the β from it - fitted again
    without the bond (leave one out), the bond's model yield on it compounded (``nbr``: ISIN -> decimal).  A bill (never
    in the fit) and the bonds of ``extra`` (bond, value date: no yield of their own) on the curve of all of them.  Too few
    coupon bonds to leave one out: ``{"nbr": {}, "why"}``.

    ``ahead`` (ISIN -> {horizon: a later value date}): the roll-down - the bond's yield on the same curve at that value
    date, the curve unchanged and the bond that much shorter (``roll``: ISIN -> {horizon: decimal})."""
    fit_in = qc.BondFit(items)
    out: Dict[str, Any] = {"nbr": {}, "n_fit": fit_in.n_fit, "n": len(fit_in), "roll": {}}
    if fit_in.n_fit < qc.MIN_BONDS + 1:
        out["why"] = "en az %d sabit kuponlu kâğıdın getirisi gerekli (%d var)" % (qc.MIN_BONDS + 1, fit_in.n_fit)
        return out
    full = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)
    nss = full["nss"]
    out["nss"] = nss
    fitted = set(fit_in.fitted)

    def on(b: qc.Bond, curve: qc.Nss, value: _dt.date, conv: str, guess: Optional[float]) -> None:
        y = yield_on(b, curve, value, conv, guess)
        if y is None:
            return
        out["nbr"][b.isin] = y
        for h, later in ((ahead or {}).get(b.isin) or {}).items():
            if (b.maturity - later).days >= 1:
                got = yield_on(b, curve, later, conv, guess)
                if got is not None:
                    out["roll"].setdefault(b.isin, {})[h] = got

    for j, b in enumerate(fit_in.bonds):
        curve = nss
        if j in fitted:
            idx = [i for i in fit_in.fitted if i != j]

            def make(t1: float, t2: float, idx: List[int] = idx) -> Tuple[Any, Any]:
                return fit_in._fn(idx, t1, t2), (lambda k=qc.NSS: list(nss.beta[:k]))

            curve = qc.refit(make, nss, nss.beta, iters=8)["nss"]
        on(b, curve, fit_in.value[j], fit_in.conv[j], fit_in.y[j])
    for b, value in extra:
        if b.isin in out["nbr"] or (b.maturity - value).days < qc.MIN_DAYS:
            continue
        on(b, nss, value, "compound", nss.zero(max((b.maturity - value).days / qc.YEAR, 0.01)))
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
    # Öngörülen's parameters: each window's AR(1) of the spread and β on OIS, from the last closes
    out["windows"] = {w: fit_window(recs, pos, len(recs) - 1, w) for w in AR_WINDOWS}
    return out


# ---------------------------------------------------------------------------------------------- Öngörülen: the models
def ar1(spreads: Sequence[float], linked: Sequence[bool]) -> Optional[Tuple[float, float]]:
    """The AR(1) of a bond's spread over a window of its closes: μ the window's mean, φ the OLS slope of s[k+1] − μ on
    s[k] − μ over the pairs of consecutive closes (``linked[k]``: close k+1 is the history's next day after close k), held
    within [0, 1] (1: no reversion, 0: all of it at once).  None with fewer than ``AR_MIN`` pairs."""
    n = len(spreads)
    if n < 2:
        return None
    mu = sum(spreads) / n
    num = den = 0.0
    pairs = 0
    for k in range(n - 1):
        if not linked[k]:
            continue
        a, b = spreads[k] - mu, spreads[k + 1] - mu
        num += a * b
        den += a * a
        pairs += 1
    if pairs < AR_MIN or den <= 0:
        return None
    return mu, min(1.0, max(0.0, num / den))


def beta_of(dy: Sequence[float], dx: Sequence[float]) -> Optional[float]:
    """The OLS slope of a bond's daily yield changes ``dy`` on its OIS base's ``dx`` (pairs of consecutive closes); None
    with fewer than ``AR_MIN`` of them."""
    n = len(dy)
    if n < AR_MIN or n != len(dx):
        return None
    mx, my = sum(dx) / n, sum(dy) / n
    sxx = sum((x - mx) ** 2 for x in dx)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(dx, dy)) / sxx


def fit_window(recs: Sequence[Dict[str, Any]], pos: Dict[str, int], end: int, w: int) -> Dict[str, Any]:
    """A model's parameters from a bond's last ``w`` closes up to ``recs[end]`` (included; out of sample for anything
    after it): ``ar`` the AR(1) of its spread to the neighbours' curve (:func:`ar1`), ``beta`` its yield's daily changes
    on its OIS base's (:func:`beta_of`), ``n`` the closes in the window."""
    win = list(recs[max(0, end - w + 1):end + 1])
    sp = [r for r in win if r.get(NBR) is not None]
    linked = [pos.get(b["day"], -9) - pos.get(a["day"], -9) == 1 for a, b in zip(sp, sp[1:])]
    dy, dx = [], []
    for a, b in zip(win, win[1:]):
        if pos.get(b["day"], -9) - pos.get(a["day"], -9) == 1 and a.get(OIS) is not None and b.get(OIS) is not None:
            dy.append(b["y"] - a["y"])
            dx.append(b[OIS] - a[OIS])
    return {"ar": ar1([r["y"] - r[NBR] for r in sp], linked), "beta": beta_of(dy, dx), "n": len(win)}


def ois_move(curve: Any, spot: float, mat: float, days: float) -> Optional[float]:
    """The market-implied move of the OIS base ``days`` (calendar) ahead: the OIS forward zero rate from then to the
    maturity ``mat`` (serial) less today's zero rate for the same remaining life (what an unchanged curve gives it then -
    the roll-down the other models have already), both compounded once a year (ACT/365)."""
    t, h = mat - spot, float(days)
    if curve is None or h < 0 or t - h <= 0:
        return None
    df_h, df_t, df_r = curve.df(h), curve.df(t), curve.df(t - h)
    if df_h <= 0 or df_t <= 0 or df_r <= 0:
        return None
    return (df_h / df_t) ** (365.0 / (t - h)) - df_r ** (-365.0 / (t - h))


def project(model: str, h: int, y: float, nbr: Optional[float], roll: Optional[float], ar: Optional[Tuple[float, float]],
            beta: Optional[float], move: Optional[float]) -> Optional[float]:
    """The compound yield (decimal) ``model`` says the bond reaches ``h`` closes on, from its yield ``y`` now and its
    spread to the neighbours' curve now ``s = y − nbr``:

    * M0 no change: ``y``;
    * M1 the spread back toward its mean: ``nbr + μ + (s − μ)·φ^h``;
    * M2 the roll-down only: ``roll + s`` (``roll``: the curve now at the bond's maturity less h - :func:`neighbours`'
      ``roll``);
    * M3 M1 with the roll-down: ``roll + μ + (s − μ)·φ^h``;
    * M4 M3 plus the OIS forward's move: ``+ β × move`` (:func:`ois_move`).

    None when the model lacks a part."""
    if model == M0:
        return y
    if nbr is None:
        return None
    s = y - nbr
    if model == M2:
        return roll + s if roll is not None else None
    if ar is None:
        return None
    mu, phi = ar
    spread = mu + (s - mu) * phi ** h
    if model == M1:
        return nbr + spread
    if roll is None:
        return None
    if model == M3:
        return roll + spread
    if model == M4 and beta is not None and move is not None:
        return roll + spread + beta * move
    return None


def choose(rmse: Dict[str, float], m0: float) -> Tuple[str, bool]:
    """The rule the measurement fixed before it ran (``PROJECTION``): of the models' out-of-sample RMSEs at a bucket and
    horizon (name -> bp; M0's ``m0`` apart), the lowest - used where it beats no change by ``BEAT`` or more (True); where
    none does, M2, shown as "eğri ve fark değişmezse" (False)."""
    best = min(rmse, key=lambda k: (rmse[k], k))
    if m0 > 0 and 1.0 - rmse[best] / m0 >= BEAT - 1e-12:
        return best, True
    return M2, False


def workday(day: _dt.date, n: int, hol: frozenset) -> _dt.date:
    """The ``n``-th TRY business day after ``day`` (week days not in ``hol``, the holidays as serials)."""
    from .xl.values import date_to_serial
    while n > 0:
        day += _dt.timedelta(days=1)
        if day.weekday() < 5 and float(date_to_serial(day)) not in hol:
            n -= 1
    return day


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


def _gain(rmse: float, m0: float) -> str:
    """An RMSE against no change's: "değişmezse'ye göre %9,0 daha iyi" / "… %0,9 daha kötü"."""
    g = round((1.0 - rmse / m0) * 100.0, 1) if m0 else 0.0
    return "değişmezse'ye göre %%%s daha %s" % (_n(abs(g), 1), "kötü" if g < 0 else "iyi")


def _hit(hit: Optional[float], calls: int) -> str:
    return "yön isabeti %%%d (%d)" % (int(round(hit * 100)), calls) if hit is not None else "yön isabeti – (%d)" % calls


def record_text(rec: Dict[str, Any], used: str) -> str:
    """The record of the model shown, in a line: "geri test: RMSE 149 bp, değişmezse'ye göre %9,0 daha iyi, yön isabeti %64
    (259)".  Where no model beat no change by ``BEAT`` it says so first, then M2's own record; M2 shown in the place of a
    model the bond cannot have now: M2's own record."""
    if used == rec["model"] and rec["beat"]:
        return "geri test: RMSE %d bp, %s, %s" % (int(round(rec["rmse"])), _gain(rec["rmse"], rec["m0"]), _hit(rec["hit"], rec["calls"]))
    m2 = rec["m2"]
    own = "RMSE %d bp (değişmez %d bp), %s" % (int(round(m2["rmse"])), int(round(rec["m0"])), _hit(m2["hit"], m2["calls"]))
    if not rec["beat"]:
        return "geri test: hiçbir model değişmezse'yi %%%d yenemedi (en iyisi %s, %s%%%s) · eğri ve fark değişmezse: %s" % (
            int(round(BEAT * 100)), rec["best"], "−" if rec["gain"] < 0 else "+", _n(abs(rec["gain"]), 1), own)
    return "geri test (eğri ve fark değişmezse): " + own


def _tl(v: float) -> str:
    """A signed TL amount with the thousands dotted: "+12.345", "−980"."""
    r = int(round(v))
    return ("+" if r >= 0 else "−") + "{:,}".format(abs(r)).replace(",", ".")


def proj_line(e: Dict[str, Any], p: Dict[str, Any]) -> str:
    """How a projection was made, in a line ("1 ay (valör 18.12) · eğri ve fark değişmezse: komşu eğri 37,62, vade kısalınca
    −12 bp · fark +8 bp sabit → 37,58 (ekrandan −12 bp) · fiyat 98,452 · K/Z +1.234 TL / 1 mn").  ``e``: a horizon's entry,
    ``p``: the bond's projection."""
    spread = (p["y"] - p["nbr"]) * 100.0
    bits = ["%s (valör %s) · %s%s" % (e["text"], _day(e["value_date"]), "" if e["model"] == M2 else e["model"] + " ", e["model_text"])]
    curve = "komşu eğri %s" % _n(p["nbr"], 2)
    if e.get("roll") is not None:
        curve += ", vade kısalınca %s bp" % _bp(e["roll"])
    bits.append(curve)
    if e.get("ar"):
        a = e["ar"]
        bits.append("fark %s bp, son %d kapanışta ortalaması %s bp, φ %s → %d kapanışta %s bp" % (
            _bp(spread), a.get("n") or 0, _bp(a["mu"]), _n(a["phi"], 2), e["h"], _bp(a["to"])))
    else:
        bits.append("fark %s bp sabit" % _bp(spread))
    if e.get("ois"):
        o = e["ois"]
        bits.append("β %s × OIS forward'ı %s bp = %s bp" % (_n(o["beta"], 2), _bp(o["move"]), _bp(o["bp"])))
    tail = "%s (%s %s bp)" % (_n(e["yield"], 2), "ekrandan" if p["from"] == "ekran" else "şimdiden", _bp(e["bp"]))
    if e.get("clean") is not None:
        tail += " · fiyat %s" % _n(e["clean"], 3)
    if e.get("pnl") is not None:
        tail += " · K/Z %s TL / 1 mn" % _tl(e["pnl"])
    return ": ".join([bits[0], " · ".join(bits[1:])]) + " → " + tail


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


def asw_side(f: Dict[str, Any], cells: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A bond on one of the fitted ASW curves as DİBS Trading shows it ("OIS'e göre" / "FX swap'a göre": ``rvfair.fair``'s
    side and the trading summary's two cells of it, ``Service._fair_cells``): the fair yield (%) and clean price, the
    cells' text, soft where the curve is read outside the bonds fitted, how it was made (the tip) - or why there is none."""
    y, p = cells
    if "yield" not in f:
        return {"why": y.get("tip") or f.get("why") or "", "t": [y.get("t", "–"), p.get("t", "–")]}
    return {"yield": f["yield"] * 100.0, "price": f["price"], "t": [y["t"], p["t"]], "soft": "soft" in (y.get("cls") or ""),
            "bill": bool(f.get("bill")), "tip": y.get("tip") or ""}


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
        from . import bonds as bd
        code = rvfair.isin_of(isin) if isin is not None else None
        bonds = self._bonds(got)
        uni = self._universe(got, bonds, [code] if code else ())
        why = None
        if code is not None and not any(line["isin"] == code for line in got["lines"]) and not any(u["isin"] == code for u in uni):
            rec = bd.by_isin(code) if code else None
            if rec is None:
                raise KagitError("kâğıt masanın listesinde yok: %s" % (code or str(isin).strip() or "—"))
            why = "%s: %s" % (bd.KINDS.get(rec.get("kind"), rec.get("kind") or "türü bilinmiyor"), OTHERS_WHY)
        panel = self.closes(got)
        hdays = self.horizon_days(got)
        now = self.now_fit(got, panel, hdays)
        widths = self.widths()
        curve_rows = [r for r in self._curve_rows(uni, got, panel, now) if code is None or r["isin"] == code]
        order_c = {k: i for i, (k, _) in enumerate(KINDS)}
        curve_rows.sort(key=lambda r: (order_c.get(r["kind"], 9), r.get("maturity") or "9999", r["isin"]))
        rows = []
        for line in got["lines"]:
            if code is not None and line["isin"] != code:
                continue
            row = self._row(line, got, panel, now, widths, bonds)
            row["asw"] = line.get("asw") or {}
            bond = bonds.get(line["isin"])
            if row["priced"] and bond is not None:
                row["proj"] = self._projection(line, bond, got, panel["stats"].get(line["isin"]) or {}, now, hdays)
            rows.append(row)
        order = {k: i for i, (k, _) in enumerate(KINDS)}
        rows.sort(key=lambda r: (order.get(r["kind"], 9), r.get("maturity") or "9999", r["isin"]))
        hist = {k: panel.get(k) for k in ("first", "last", "days", "tau", "tau_day", "ms", "ois_days", "why", "built")}
        listed = bd.listed(got["today"])
        others = [{"kind": k, "text": t, "n": sum(1 for b in listed if b.get("kind") == k)} for k, t in OTHER_KINDS]
        counts = {lab: sum(1 for r in curve_rows if (r.get("price") or {}).get("kind") == lab) for lab in ("market", "spread", "peer", "curve")}
        return {"ok": True, "rows": rows, "curve_rows": curve_rows, "others": [x for x in others if x["n"]], "others_why": OTHERS_WHY,
                "counts": counts, "why": why, "kinds": [{"kind": k, "title": t} for k, t in KINDS], "widths": widths,
                "admin": svc._is_admin(key), "log": self.log() if svc._is_admin(key) else [], "history": hist,
                "fit": {k: now.get(k) for k in ("ok", "why", "n_fit", "n", "tau_from")},
                "rules": {"weights": WEIGHTS, "floor": SIGMA_FLOOR, "buckets": [{"key": k, "text": t, "top": top} for k, t, top in BUCKETS],
                          "band": BAND, "noise": NOISE, "revert": REVERT, "window": SIGMA_WINDOW, "min": SIGMA_MIN,
                          "median": MEDIAN_DAYS},
                "projection": {"default": DEFAULT_H, "horizons": [{"h": h, "text": t, "day": hdays[h].isoformat()} for h, t in HORIZONS],
                               "models": MODEL_TEXT, "table": PROJECTION, "source": RECORD_TEXT, "beat": BEAT, "move_min": MOVE_MIN},
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
                          "board": said.get(code), "last": raw("AS", r), "last_day": raw("I", r), "source": raw("BS", r)})
        # Tüm Kâğıtlar (EK_EVREN): every bond of the desk's list - the bid / ask / last trade it already asks Bloomberg for (a
        # bond of the trading list: DİBS RV's), its value date's source by kind (C2: bills and zero coupon, E2: the rest)
        uni: Dict[str, Dict[str, Any]] = {}
        srcs = ("ISL0", "ISL1")
        usi = index.get(ex.UNI_SHEET)
        if usi is not None:
            got_src = [raw(c, 2, usi) for c in ("C", "E")]
            srcs = tuple((s.strip().upper() if isinstance(s, str) and s.strip() else d) for s, d in zip(got_src, srcs))
            for r in range(ex.UNI_FIRST, ex.UNI_LAST + 1):
                code = rvfair.isin_of(raw("A", r, usi))
                if code and code not in uni:
                    uni[code] = {"bid": raw("I", r, usi), "ask": raw("J", r, usi), "last": raw("K", r, usi), "last_day": raw("L", r, usi),
                                 "source": raw("R", r, usi)}
        n2 = raw("N", 2)
        if user:
            # "OIS'e göre" / "FX swap'a göre": what DİBS Trading shows of each bond on the two fitted ASW curves - rvfair's
            # fair yield and clean price, with the trading summary's own cells (their text and how each is made)
            from .xl import numfmt
            loc = numfmt.get_locale(svc.settings.locale)
            fx = svc._fx_curve(user)
            fits = rvfair.read_fits(calc, si, fx)
            for line in lines:
                r = line["row"]
                f = rvfair.fair(calc, si, r, fits, fx)
                valor, own = raw("P", r), raw("T", r)
                line["asw"] = {side: asw_side(f[side], svc._fair_cells(f[side], side, fits, valor, own, loc)) for side in ("ois", "fx")}
        return {"lines": lines, "quant": eng.get("dibs") or [], "live": qc.live_values(eng), "today": svc.history.today(),
                "mk": mk, "boot": boot, "gen": svc.gen, "uni": uni, "src": srcs,
                "how": n2.strip() if isinstance(n2, str) and n2.strip() else "ISIN"}

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
        # the desk's other bonds (off the trading list) whose closes the history kept - a bond once on the list
        off = self._off_closes(got, bonds, conv, start, before)
        mark = (svc.history.rev, before, static, node_months, quote_months, hash(hol), tuple(sorted(defs)),
                tuple(sorted((code, x[2]) for code, x in off.items())))
        with self._lock:
            hit = self._panel
            if hit is not None and hit[0] == mark:
                return hit[1]
            t0 = time.perf_counter()
            res = self._build(bonds, rows, conv, closes, ois, node_months, quote_months, hol, today)
            res["off"] = self._off_spreads(off)
            res["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
            res["built"] = _dt.datetime.now().strftime("%H:%M:%S")
            self._panel = (mark, res)
            return res

    def _off_closes(self, got: Dict[str, Any], bonds: Dict[str, qc.Bond], conv: Dict[str, str], start: str, before: str
                    ) -> Dict[str, Tuple[qc.Bond, Dict[str, Any], str, str, float]]:
        """The bonds of the desk's list off the trading list that have closes in the history (a bond once on the list: its
        series as DİBS RV named it - "<ISIN> @<source> <ISIN>" and the plain "<ISIN> ISIN", the history's yield field): ISIN
        -> (its bond, the row it is read with - its source -, its last close's day before today, its convention, the close
        %).  The convention is the trading list's bonds' of its kind (most of them; quantcurve's ``detect_convention`` -
        there is no yield of its own on a sheet to tell it)."""
        from . import bonds as bd
        from .history import SeriesDef
        svc = self.svc
        field = str(svc.history.settings().get("dibs_field") or "YLD_YTM_MID")
        bounds = svc.store.hist_bounds()
        how = got.get("how") or "ISIN"
        src = got.get("src") or ("ISL0", "ISL1")
        kinds: Dict[str, List[str]] = {}
        for code, b in bonds.items():
            kinds.setdefault(b.kind, []).append(conv.get(code, "simple"))
        out: Dict[str, Tuple[qc.Bond, Dict[str, Any], str, str, float]] = {}
        for rec in bd.listed(got["today"]):
            code = rec["isin"]
            if code in bonds or rec.get("kind") not in CURVE_KINDS:
                continue
            s = src[0] if rec.get("kind") in ("bill", "zero") else src[1]
            main = "/isin/%s@%s" % (code, s) if how.lower() == "/isin/" else "%s @%s %s" % (code, s, how)
            plain = "%s %s" % (code, how)
            if not any("%s|%s" % (t, field) in bounds for t in (main, plain)):
                continue
            b = qc._bond_of(code, {}, None)
            if b is None:
                continue
            d = SeriesDef("dibs", code, main, field, [plain])
            points = {k: v for k, v in d.pick(svc.store.hist_many(d.ids(), start))[1].items() if k < before}
            if not points:
                continue
            day = max(points)
            votes = kinds.get(b.kind) or []
            c = max(set(votes), key=votes.count) if votes else "simple"
            out[code] = (b, {"source": s}, day, c, points[day])
        return out

    def _off_spreads(self, off: Dict[str, Tuple[qc.Bond, Dict[str, Any], str, str, float]]) -> Dict[str, Dict[str, Any]]:
        """Each such bond's spread to the curve at its last close: its close (compounded) − its yield on that day's curve of
        the trading list's bonds (the day's fit, kept with the day: the bond read on it, as a bond off the list is now)."""
        from .xl.values import date_to_serial
        out: Dict[str, Dict[str, Any]] = {}
        for code, (b, row, day, conv, close) in off.items():
            hit = self._days.get(day)
            nss = (hit[1].get("nss") if hit is not None else None)
            if nss is None:
                continue
            value = qc._value_date(_dt.date.fromisoformat(day), row)
            if (b.maturity - value).days < qc.MIN_DAYS:
                continue
            y = to_compound(b, close / 100.0, value, conv)
            curve = yield_on(b, nss, value, "compound", y)
            if curve is None:
                continue
            # (and to that day's OIS zero at its maturity, when the day had the OIS curve: the bucket's base is a blend)
            spreads = {NBR: y - curve}
            oc = hit[1].get("ois_curve")
            z = zero_rate(oc[1], oc[0], float(date_to_serial(b.maturity))) if oc else None
            if z is not None:
                spreads[OIS] = y - z
            out[code] = {"day": day, "spread": spreads, "y": y, "curve": curve, "conv": conv}
        return out

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
                res = {"nbr": {}, "ois": {}, "nss": None}
                if nss0 is not None:
                    nb = neighbours(items, nss0)
                    res["nbr"] = nb["nbr"]
                    res["nss"] = nb.get("nss")              # (the day's curve of all of them: a bond off the list is read on it)
                if full:
                    try:
                        spot, curve = sw.day_curve(float(date_to_serial(_dt.date.fromisoformat(iso))), quotes, node_months, hol)
                    except ValueError:
                        curve = None
                    if curve is not None:
                        res["ois_curve"] = (spot, curve)   # (a bond off the list: its OIS zero that day)
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
    def horizon_days(self, got: Dict[str, Any]) -> Dict[int, _dt.date]:
        """Öngörülen's horizons as days: today + 5 / 10 / 20 TRY business days (the workbook's TRY holidays, as the
        history dates the past days)."""
        mk = got["mk"]
        hol = self.svc._swaption_closes(mk)[2] if mk is not None else frozenset()
        return {h: workday(got["today"], h, hol) for h, _ in HORIZONS}

    def now_fit(self, got: Dict[str, Any], panel: Dict[str, Any], hdays: Optional[Dict[int, _dt.date]] = None) -> Dict[str, Any]:
        """The neighbours' curve at each bond now (``neighbours`` on DİBS RV's yields now, the history's τ held - or
        searched on them when the history has none), and each bond's roll-down on it to the value date of each of
        ``hdays`` (the horizons), kept per what it is made of."""
        from .dibsgenel import bond_inputs
        today = got["today"]
        items, _ = bond_inputs(got["quant"], got["live"], today)
        have = {b.isin for b, _, _, _ in items}
        rows = {r["isin"]: r for r in got["quant"]}
        bonds = self._bonds(got)
        extra = [(b, qc._value_date(today, rows.get(code))) for code, b in sorted(bonds.items()) if code not in have]
        ahead = {code: {h: qc._value_date(d, rows.get(code)) for h, d in (hdays or {}).items()} for code in bonds}
        nss0 = panel.get("nss0")
        tau_from = "geçmiş" if nss0 is not None else "şimdi"
        key = (tuple((b.isin, v.isoformat(), y, c) for b, v, y, c in items), tuple((b.isin, v.isoformat()) for b, v in extra),
               (nss0.tau1, nss0.tau2, tuple(nss0.beta)) if nss0 is not None else None,
               tuple(sorted((code, tuple(sorted((h, d.isoformat()) for h, d in x.items()))) for code, x in ahead.items())))
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
            res = neighbours(items, nss0, extra, ahead)
            res["ok"] = "why" not in res
            res["tau_from"] = tau_from
            res["full"] = res.pop("nss", None)             # (the curve of all of them now: the desk's other bonds are read on it)
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

    @staticmethod
    def pricer_at(line: Dict[str, Any], bond: qc.Bond, value: _dt.date) -> Pricer:
        """The bond priced at a later value date (a horizon's): its own cash flows then, by BIST's rules (quantcurve's
        ``Bond``, as DİBS RV prices a bond it has no row of), the accrued interest then."""
        if line["kind"] == "B":
            return Pricer("bill", value, float((bond.maturity - value).days), line["freq"], [], 0.0, bond, line["guess"])
        return Pricer("fixed", value, None, line["freq"], [], qc.accrued(bond, value), bond, line["guess"])

    def _projection(self, line: Dict[str, Any], bond: qc.Bond, got: Dict[str, Any], st: Dict[str, Any], now: Dict[str, Any],
                    hdays: Dict[int, _dt.date]) -> Dict[str, Any]:
        """Öngörülen: the yield and price each horizon's model (``PROJECTION``, the bond's bucket now) says the bond
        reaches - from its yield now (DİBS RV!T; without one, the neighbours' curve now plus the spread at the last close),
        the neighbours' curve now and its roll-down to the horizon's value date (``now_fit``), the model's window of the
        closes (``bond_closes``' ``windows``) and the OIS Bootstrap's forwards (``ois_move``).  A model the bond cannot
        have now gives way to M2, said.  ``{"from", "y", "h": {horizon: ...}}`` or ``{"why"}``."""
        from .xl.values import date_to_serial
        today = got["today"]
        code = line["isin"]
        bucket = bucket_of((bond.maturity - today).days / qc.YEAR)
        nbr = (now.get("nbr") or {}).get(code)
        roll = (now.get("roll") or {}).get(code) or {}
        if nbr is None:
            return {"why": "komşu eğri şimdi kurulamadı" + (": " + now["why"] if now.get("why") else "")}
        last = st.get("last") or {}
        y0, start = line["compound"], "ekran"
        if y0 is None:
            sp = (last.get("spread") or {}).get(NBR)
            if sp is None:
                return {"why": "kâğıdın şimdiki getirisi yok ve son kapanışta komşu eğriye farkı yok"}
            y0, start = nbr + sp, "kapanış"
        mk, boot = got["mk"], got["boot"]
        mat = float(date_to_serial(bond.maturity))
        windows = st.get("windows") or {}
        rows = {r["isin"]: r for r in got["quant"]}
        out: Dict[str, Any] = {"from": start, "y": y0 * 100.0, "nbr": nbr * 100.0, "h": {}}
        for h, text in HORIZONS:
            rec = PROJECTION[bucket][h]
            day = hdays[h]
            value = qc._value_date(day, rows.get(code))
            move = ois_move(boot, mk.ois_spot, mat, (day - today).days) if mk is not None and boot is not None else None
            model, w = rec["model"], rec["window"]
            p = windows.get(w) or {}
            y = project(model, h, y0, nbr, roll.get(h), p.get("ar"), p.get("beta"), move)
            why = None
            if y is None and model != M2:
                why = self._why_not(model, w, p, move, roll.get(h))
                model, w, p = M2, 0, {}
                y = project(M2, h, y0, nbr, roll.get(h), None, None, None)
            entry: Dict[str, Any] = {"h": h, "text": text, "day": day.isoformat(), "value_date": value.isoformat(), "bucket": bucket,
                                     "model": model, "model_text": MODEL_TEXT[model], "window": w, "rule": rec["model"],
                                     "beat": rec["beat"], "record": record_text(rec, model), "why": why}
            if y is None:
                entry["why"] = "kâğıdın vadesi ufuktan önce" if (bond.maturity - value).days < 1 else "eğride vadesi kısalınca getirisi bulunamadı"
                out["h"][str(h)] = entry
                continue
            pricer = self.pricer_at(line, bond, value)
            c, c0, s = pricer.clean(y), pricer.clean(y0), pricer.simple(y)
            entry.update({"yield": y * 100.0, "simple": s * 100.0 if s is not None else None, "clean": c,
                          "bp": (y - y0) * BP, "pnl": (c - c0) * 1e4 if c is not None and c0 is not None else None,
                          "roll": (roll[h] - nbr) * BP if roll.get(h) is not None else None})
            if p.get("ar") is not None:
                entry["ar"] = {"mu": p["ar"][0] * BP, "phi": p["ar"][1], "n": p.get("n"), "to": (p["ar"][0] + (y0 - nbr - p["ar"][0]) * p["ar"][1] ** h) * BP}
            if model == M4:
                entry["ois"] = {"beta": p["beta"], "move": move * BP, "bp": p["beta"] * move * BP}
            entry["line"] = proj_line(entry, out)
            out["h"][str(h)] = entry
        return out

    @staticmethod
    def _why_not(model: str, w: int, p: Dict[str, Any], move: Optional[float], roll: Optional[float]) -> str:
        """Why a bond cannot have its bucket's model now (M2 shown in its place)."""
        if roll is None:
            return "%s kurulamadı: eğride vadesi kısalınca getirisi yok" % model
        if p.get("ar") is None:
            return "%s kurulamadı: son %d kapanışta farkın ortalamaya dönüşü ölçülemedi (en az %d ardışık kapanış gerekir; %d kapanış var)" % (
                model, w, AR_MIN + 1, p.get("n") or 0)
        if model == M4 and p.get("beta") is None:
            return "%s kurulamadı: son %d kapanışta OIS'le birlikte hareketi (β) ölçülemedi (OIS kapanışı az)" % (model, w)
        if model == M4 and move is None:
            return "%s kurulamadı: OIS Bootstrap eğrisi şimdi yok" % model
        return "%s kurulamadı" % model

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

    # ------------------------------------------------------------------ Eğri fiyatı: every bond of the desk's list
    def _universe(self, got: Dict[str, Any], bonds: Dict[str, qc.Bond], extra: Sequence[str] = ()) -> List[Dict[str, Any]]:
        """The bonds the main table prices: every fixed coupon bond, bill and zero coupon bond of the desk's list (Tüm
        Kâğıtlar: the catalog less the bonds taken off and the matured ones), the trading list's own and the catalog's of
        ``extra`` (ISINs asked for: the upload's) - each with its bond (the trading list's as DİBS RV has it, the others' from
        the catalog, by BIST's rules), its value date (DİBS RV's; else Tüm Kâğıtlar's source by kind) and its DİBS RV row."""
        from . import bonds as bd
        today = got["today"]
        lines = {x["isin"]: x for x in got["lines"] if x["kind"] in ("S", "B")}
        rows = {r["isin"]: r for r in got["quant"]}
        src = got.get("src") or ("ISL0", "ISL1")
        recs = [r for r in bd.listed(today) if r.get("kind") in CURVE_KINDS]
        seen = {r["isin"] for r in recs}
        for code, line in lines.items():
            if code not in seen:
                recs.append(bd.by_isin(code) or {"isin": code, "kind": "bill" if line["kind"] == "B" else "fixed", "name": line["label"],
                                                 "maturity": line["maturity"].isoformat() if line["maturity"] else None})
                seen.add(code)
        for code in extra:
            rec = bd.by_isin(code) if code not in seen else None
            if rec is not None and rec.get("kind") in CURVE_KINDS:
                recs.append(rec)
                seen.add(code)
        out = []
        for rec in recs:
            code, kind = rec["isin"], rec.get("kind")
            line = lines.get(code)
            if line is not None and bonds.get(code) is not None:
                bond = bonds[code]
                value = line["value"] or qc._value_date(today, rows.get(code))
            else:
                bond = qc._bond_of(code, {}, None)
                value = qc._value_date(today, {"source": src[0] if kind in ("bill", "zero") else src[1]})
            if bond is not None and bond.maturity <= today:
                continue
            out.append({"isin": code, "rec": rec, "line": line, "listed": line is not None, "kind": "B" if kind in ("bill", "zero") else "S",
                        "cat_kind": kind, "bond": bond, "value": value})
        return out

    def _curve_rows(self, uni: Sequence[Dict[str, Any]], got: Dict[str, Any], panel: Dict[str, Any], now: Dict[str, Any]
                    ) -> List[Dict[str, Any]]:
        """The main table's rows (``_curve_row`` each): first every bond's market, curve and base, then the peers' spreads -
        today's market-priced bonds of each bucket and kind group, to their bases - and each bond's answer (``_answer``)."""
        pre = [self._curve_row(u, got, panel, now) for u in uni]
        peers: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}
        for r in pre:
            if r.get("market") is not None and r.get("curve") is not None and r.get("bucket"):
                peers.setdefault((r["bucket"], r["kind"]), []).append((r["isin"], (r["market"]["yield"] - r["curve"]["yield"]) / 100.0))
        for r in pre:
            self._answer(r, peers)
            for k in ("_level", "_own", "_vtext"):
                r.pop(k, None)
        return pre

    def _curve_row(self, u: Dict[str, Any], got: Dict[str, Any], panel: Dict[str, Any], now: Dict[str, Any]) -> Dict[str, Any]:
        """A bond of the main table, before its answer: its market price today (Piyasa: DİBS RV's bid / ask / last for the
        trading list, Tüm Kâğıtlar's for the rest) and the curve (Eğri: its bucket's base - ``base_of``: the Nelson-Siegel
        fitted now to the bonds with prices, at the bond's own cash flows and on the fit without it when it is in it, with
        the OIS zero rate at its maturity, by the fair model's weights) - and its own last spread to that base when its
        history has one."""
        from . import bonds as bd
        from .fiyatyukleme import date_said
        from .xl.values import date_to_serial
        today = got["today"]
        code, bond, line, rec, value = u["isin"], u["bond"], u["line"], u["rec"], u["value"]
        mat = bond.maturity if bond is not None else (_dt.date.fromisoformat(rec["maturity"]) if rec.get("maturity") else None)
        label = line["label"] if line is not None else (bd.short_label(rec) if rec.get("maturity") else code)
        years = (mat - today).days / qc.YEAR if mat else None
        out: Dict[str, Any] = {"isin": code, "label": label, "name": rec.get("name") or "", "kind": u["kind"], "cat_kind": u["cat_kind"],
                               "maturity": mat.isoformat() if mat else None, "years": years, "listed": u["listed"],
                               "value_date": value.isoformat() if value else None,
                               "bucket": bucket_of(years) if years is not None and years > 0 else None,
                               "market": None, "curve": None, "price": None, "alt": None, "diff": None}
        if bond is None:
            out["why"] = "kuponu bilinmiyor: eğride fiyatlanamaz" if u["cat_kind"] == "fixed" else "vadesi bilinmiyor"
            return out
        if line is not None:
            pricer = self._pricer(line, bond, today)
        else:
            pricer = self.pricer_at({"kind": u["kind"], "freq": float(bond.freq), "guess": 0.3}, bond, value)

        def level(yc: float) -> Dict[str, Any]:
            s, c = pricer.simple(yc), pricer.clean(yc)
            return {"yield": yc * 100.0, "simple": s * 100.0 if s is not None else None, "clean": c}

        out["_level"] = level
        out["_vtext"] = "valör %s" % _day(out["value_date"]) if out["value_date"] else ""
        # Piyasa: today's two-sided quote's middle, else today's last trade - the cells the pages already ask for
        q = line if line is not None else ((got.get("uni") or {}).get(code) or {})
        m = market_of(q.get("bid"), q.get("ask"), q.get("last"), date_said(q.get("last_day")), today)
        if m is not None:
            ym = pricer.yield_of(m[0])
            if ym is not None and math.isfinite(ym):
                out["market"] = dict(level(ym), clean=m[0], source="%s %s" % ("DİBS RV" if line is not None else "Tüm Kâğıtlar", m[1]))
        # Eğri: the bucket's base - the Nelson-Siegel now at the bond's cash flows (the trading list's: as Kâğıt Fiyatlama's
        # neighbours' curve has it, the fit without the bond) blended with the OIS Bootstrap zero rate at its maturity
        in_fit = line is not None and bond.kind == "fixed" and ("DIBSS:" + code) in (got.get("live") or {})
        ns = (now.get("nbr") or {}).get(code)
        full = now.get("full")
        if ns is None and full is not None and (bond.maturity - value).days >= qc.MIN_DAYS:
            ns = yield_on(bond, full, value, "compound", full.zero(max((bond.maturity - value).days / qc.YEAR, 0.01)))
        mk, boot = got.get("mk"), got.get("boot")
        ois = zero_rate(boot, mk.ois_spot, float(date_to_serial(bond.maturity))) if mk is not None and boot is not None else None
        fit_text = "Nelson-Siegel, %d sabit kuponluya şimdi uydurulan%s" % (
            now.get("n_fit") or 0, "; kâğıt dışarıda bırakılarak" if in_fit else ("; bono / kuponsuz eğride okunur" if bond.kind == "bill"
                                                                                  else "; kâğıt uydurmada değil"))
        base, w = base_of(out["bucket"], ns, ois) if ns is not None and out["bucket"] else (None, {})
        if base is None:
            out["curve_why"] = (("eğri kurulamadı: " + now["why"]) if now.get("why") else
                                ("vadesine %d günden az kaldı" % qc.MIN_DAYS if (bond.maturity - value).days < qc.MIN_DAYS else "eğride getirisi bulunamadı"))
            return out
        out["curve"] = dict(level(base), loo=in_fit, fit=fit_text, ns=ns * 100.0, ois=ois * 100.0 if ois is not None else None,
                            weights=w, base=base_text(w))
        # the bond's own last spread to that base: the trading list's at its last close (Kâğıt Fiyatlama's closes, to each
        # base), another bond's at its own last close when the history kept it - blended as the fair model blends them
        sp: Dict[str, float] = {}
        day = None
        if line is not None:
            last = ((panel.get("stats") or {}).get(code) or {}).get("last") or {}
            sp, day = last.get("spread") or {}, last.get("day")
        else:
            o = (panel.get("off") or {}).get(code)
            if o is not None:
                sp, day = o["spread"], o["day"]
        now_b = {NBR: ns, OIS: ois}
        wh = weights_of(out["bucket"], [b for b in BASES if now_b[b] is not None and b in sp])
        if wh:
            y = sum(x * (now_b[b] + sp[b]) for b, x in wh.items())
            out["_own"] = {"y": y, "day": day, "spread": y - sum(x * now_b[b] for b, x in wh.items()), "weights": wh}
        else:
            out["_own"] = {"why": "geçmiş kapanışı yok" if not sp else "son kapanışta taban kurulamadı"}
        return out

    @staticmethod
    def _answer(out: Dict[str, Any], peers: Dict[Tuple[str, str], List[Tuple[str, float]]]) -> None:
        """A row's answer (Fiyat, in place): the market's ("piyasa"); else its base + its own last spread ("eğri + son fark
        <day>"); else its base + the median spread of today's market-priced bonds of its bucket and kind group to their
        bases ("eğri + akran farkı", the bond itself left out); else its base alone ("eğri", said: no peer priced).
        ``alt``: the answer without the market (Kâğıt Fiyat Yükleme's), ``tag`` its short name there."""
        cv, level = out.get("curve"), out.get("_level")
        vtext = out.get("_vtext") or ""
        if cv is not None:
            base = cv["yield"] / 100.0
            parts = []
            if cv["base"] != "eğri":
                parts.append("eğri %%%s" % _n(cv["ns"], 2))
                if cv.get("ois") is not None:
                    parts.append("OIS %%%s" % _n(cv["ois"], 2))
            parts.append(cv["fit"])
            head = "%s %%%s (%s)" % (cv["base"], _n(cv["yield"], 2), "; ".join(parts))
            own = out.get("_own") or {}
            med, n = peer_spread(peers.get((out["bucket"], out["kind"])) or [], out["isin"])

            def px(a: Dict[str, Any]) -> str:
                return _n(a["clean"], 3) if a.get("clean") is not None else "–"

            if "y" in own:
                y = own["y"]
                alt = dict(level(y), kind="spread", label="%s %s" % (EGRI_FARK, _day(own["day"])), tag="son fark", day=own["day"],
                           spread=own["spread"] * BP)
                alt["how"] = "%s + son fark %s bp (%s kapanışı) = %%%s · temiz %s (%s)" % (
                    head, _bp(own["spread"] * BP), _day(own["day"]), _n(y * 100.0, 2), px(alt), vtext)
            elif med is not None:
                y = base + med
                alt = dict(level(y), kind="peer", label=EGRI_AKRAN, tag="akran farkı", spread=med * BP, peers=n)
                alt["how"] = ("%s + akran farkı %s bp (%d %s: bugün piyasa fiyatlı, aynı vade kovasında - %s -, tabana farklarının "
                              "medyanı) = %%%s · temiz %s (%s) · kendi son farkı yok: %s") % (
                    head, _bp(med * BP), n, GROUP_TEXT[out["kind"]], BUCKET_TEXT.get(out["bucket"], ""), _n(y * 100.0, 2), px(alt), vtext,
                    own.get("why") or "geçmiş kapanışı yok")
            else:
                alt = dict(level(base), kind="curve", label=EGRI, tag=None, peers=0)
                alt["how"] = "%s · temiz %s (%s) · uyarı: kendi son farkı yok (%s) ve bu kovada (%s) piyasa fiyatlı %s akran yok - taban tek başına" % (
                    head, px(alt), vtext, own.get("why") or "geçmiş kapanışı yok", BUCKET_TEXT.get(out["bucket"], ""), GROUP_TEXT[out["kind"]])
            out["alt"] = alt
        if out.get("market") is not None:
            mk = out["market"]
            out["price"] = dict(mk, kind="market", label=PIYASA)
            if cv is not None:
                out["diff"] = (mk["yield"] - cv["yield"]) * 100.0
            tail = " · eğri (%s) %%%s, fark %s bp" % (cv["base"], _n(cv["yield"], 2), _bp(out["diff"])) if out["diff"] is not None else ""
            out["price"]["how"] = "piyasa: %s %s → %%%s (%s)%s" % (mk["source"], _n(mk["clean"], 3), _n(mk["yield"], 2), vtext, tail)
        elif out.get("alt") is not None:
            out["price"] = dict(out["alt"])
        elif not out.get("why"):
            out["why"] = out.get("curve_why") or "fiyatı yok"

    def validation(self, user: Optional[str]) -> Dict[str, Any]:
        """The rule checked on the quotes now (``validate``): every market-priced bond priced as if it had no price and no
        history, leave one out - the per-bond errors and the table per bucket and kind group."""
        from .dibsgenel import bond_inputs
        key = self.svc.require_user(user)
        got = self.svc.et.call(self._read, key)
        panel = self.closes(got)
        now = self.now_fit(got, panel, self.horizon_days(got))
        nss0 = panel.get("nss0") or (self._now_tau[1] if self._now_tau else None)
        uni = self._universe(got, self._bonds(got))
        rows = {r["isin"]: r for r in self._curve_rows(uni, got, panel, now)}
        cands = []
        for u in uni:
            r = rows.get(u["isin"]) or {}
            cv = r.get("curve") or {}
            if r.get("market") is not None and r.get("bucket") and u["bond"] is not None:
                cands.append({"isin": u["isin"], "bond": u["bond"], "value": u["value"], "market": r["market"]["yield"] / 100.0,
                              "ois": cv["ois"] / 100.0 if cv.get("ois") is not None else None, "bucket": r["bucket"], "group": r["kind"]})
        items, _ = bond_inputs(got["quant"], got["live"], got["today"])
        res = validate(items, nss0, cands) if nss0 is not None else {}
        return {"bonds": res, "table": validation_table(res)}

    def curve_quotes(self, user: Optional[str], isins: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """Eğri fiyatı for Kâğıt Fiyat Yükleme's rows that would get no price: each of ``isins`` - a fixed coupon bond, bill
        or zero coupon bond of the catalog - as the main table prices it without the market (its "Fiyat" when that is not
        "piyasa": its bucket's base + its own last spread, else + its peers' median spread, else the base alone; the peers
        the whole list's, as on the main table): ISIN -> ``{"kind", "label", "tag", "yield", "simple", "clean",
        "value_date", "how"}`` (per cent: compound and BIST simple at the bond's value date; ``tag`` the upload's mark)."""
        key = self.svc.require_user(user)
        got = self.svc.et.call(self._read, key)
        if got is None:
            return {}
        panel = self.closes(got)
        now = self.now_fit(got, panel, self.horizon_days(got))
        want = {rvfair.isin_of(x) for x in isins}
        out: Dict[str, Dict[str, Any]] = {}
        for row in self._curve_rows(self._universe(got, self._bonds(got), sorted(want)), got, panel, now):
            if row["isin"] in want and row.get("alt") is not None:
                out[row["isin"]] = dict(row["alt"], value_date=row["value_date"])
        return out
