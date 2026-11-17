"""DİBS switch (family "dibssw"): Carry + momentum's DİBS basket turned into switches.  Once a week the trading list's
fixed-coupon bonds and bills are ranked on their carry + roll over a month and their one-month momentum, and the best of
them is bought against the worst of a similar duration, DV01-balanced - each switch a line of the Sinyaller list (group
DİBS) in the plan's format::

    AL TRT150328T24 / SAT TRT130928T38 · switch · 210 mn / 205 mn · C+R +18,0 bp/ay · 1A momentum lehte · hedef +12,0 bp ·
    stop -8,0 bp · beklenen +504 bin TL · isabet %56 (142)

Page "DİBS switch", a tab of Faiz after Eğri Adil Değeri (``tto.quant.MENU``: where the DİBS lines of DİBS adil değeri
live).

**Universe.**  The trading list's bonds (DİBS RV!A5:A54: the history's ``dibs`` series, Bloomberg's ``YLD_YTM_MID``, about
a year of closes - nothing new is asked of Bloomberg) of two kinds: fixed-coupon bonds ("S") and bills / zero-coupon
bonds ("B").  Out, each with its reason on the page (``OUT``): TLREF floaters ("T") and FRNs ("F") - their coupon follows
TLREF, the history keeps their price: a yield difference against a fixed bond is no switch level -, CPI linkers ("E") - a
real yield, not comparable with a nominal one -, a bond within ``MIN_LEFT`` days of its maturity, one whose terms are not
known.  A bond is its ISIN: a row moved on DİBS RV moves nothing.

**Yields** as the bonds' BIST simple yields (DİBS RV!S - what the sheet's SWITCH / PAIR table differences, "Getiri farkı
(basit)"): every close's in the convention its history is in (``quantcurve.detect_convention``), a compound one converted
(``quantcurve.to_simple``; a bill's from its price).  Now: the sheet's live simple yield (``DIBSS:``), else its compound
one converted, else the last close.

**When.**  As Carry + momentum (``quantsira.rebalance_days`` / ``next_rebalance``): at Monday's close - a week whose Monday
is a holiday at its first business day's close - the bonds are ranked on the closes up to that close only, and the week's
switches are held to the next rebalance's close; between the two the lines stay as they were made.

**Score** of a bond at a close, each part standardised across that close's bonds (z):

* carry + roll over a month, bp of the bond's DV01 for a holder: carry (y − f) × 30/365 ÷ its modified duration, f the
  funding to a month - the close's OIS curve at one month (TLREF at 0 months), quantcurve's path for a row without repo -;
  roll the fall of the close's fitted curve over a month down the bond's maturity (the curve: a Nelson-Siegel of the
  fixed-coupon bonds' simple yields against their years, τ the best of ``TAUS``, flat beyond the shortest and the longest
  bond; bills are read on it, not fitted - they trade far from the bonds).  Today's line tells DİBS RV's own C+R (AO over its horizon J2, per month) where the sheet
  has it;
* momentum, one month: −(y − the yield 21 closes before), bp - a falling yield is in favour of a holder.

The composite is z(C+R) + z(momentum).  **The switches**: every pair whose modified durations are within ``DUR_RATIO``
of each other (the longer at most 1,5 × the shorter: a relative value trade, not a curve trade) and whose composites
differ by at least ``MIN_GAP``: the widest gap first, no bond twice, at most ``MAX_SWITCHES`` a week - AL the higher
composite, SAT the lower.

**Size.**  The AL leg: the desk's DV01 setting (``dv01_usd``, 1.000 $ - OIS_MAIN!F2) at OIS_MAIN!D2's USDTRY, its nominal
rounded as the desk rounds a bond's (DİBS RV!AK: to OIS_MAIN!H2, "Yuvarlama TL", 5 mn TL); the SAT leg the nominal of
the same DV01 (DİBS RV!AI's DV01, of the simple yield) rounded the same way - the DV01 the rounding leaves is shown.

**Level** of a switch: its yield difference y_AL − y_SAT (bp, the SWITCH / PAIR table's "Getiri farkı"): the switch
gains as it falls.  Target and stop are moves of it, told in the trade's P&L direction ("hedef +12,0 bp": 12 bp in
favour).  A pair's monitor keeps one orientation - the shorter bond first, its level y_short − y_long - and the line's
direction is the side of it the week's ranking took.

**Backtest** (walk-forward, no look-ahead): every rebalance of the history makes its switches from the closes up to it,
held to the next rebalance's close; a switch's P&L at each close is the fall of its yield difference plus its carry +
roll pro rata (the rebalance's C+R ÷ 21 a close), bp of the AL leg's DV01, and in σ of its week - the σ of the
difference's daily moves over the 60 closes before the rebalance × √5.  Every switch a trade (quantbt's format with its
path: ``quantlevels``' contract); the record: switches, hit rate, the mean in σ, bp and TL, Sharpe, the largest drawdown.

**Levels** (``tto.quantlevels``): calibrated on those trades month by month (≥ 30 of them) - a stop k and a target m in
σ of the switch's week, Ödül / risk ≥ 1, carry in; ``tto.quant`` applies them to the lines (``make_signal``: the family
puts its book in its table), the line and the card tell the multiples, the hit rate and the expectancy.  A record that
lost money at its levels makes the line "düşük güven".  Without a calibration: target 1,5σ, stop 1σ, the expected P&L
the week's C+R - said so.

**Monitors.**  Every pair within the duration band at the week's ranking has one (its yield difference), so a pair
entering the week's switches is a new line - logged and alerted - and one leaving them is gone: "sıra" 2 for the widest
gap of the week down to 1 for the narrowest, under 1 a pair not taken.  No gate holds a switch (``ungated``, as Carry +
momentum's legs): only its levels' record can make it "düşük güven".
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quantbt as qbt
from . import quantcurve as qc
from . import quantfam as qf
from . import quantlevels as qlv
from . import quantmath as qm
from . import quantsira as qs
from . import quantuniv as qu

FAMILY = "dibssw"
#: the page (a tab of Faiz after Eğri Adil Değeri: ``tto.quant.MENU``) and the view of ``/api/quant/dibssw``
PAGES = (("quant-dibssw", "DİBS switch"),)
TAB = ("quant-dibssw", "DİBS switch")
AFTER = "quant-curve"
VIEWS = {"dibssw": "quant-dibssw"}
GROUP = "DİBS"                   # the Sinyaller list's group of every line
TYPE = "DİBS switch"             # the backtest's type
MODEL = "DİBS switch"

#: DİBS RV's kinds in the universe, and why the others are not
KINDS = {"S": "sabit kuponlu", "B": "bono / kuponsuz"}
OUT = {"T": "TLREF'e endeksli: kuponu TLREF'le değişir, tarihçe fiyatını tutar - sabit getiriyle switch seviyesi olmaz",
       "F": "FRN: değişken kupon, tarihçe fiyatını tutar - sabit getiriyle switch seviyesi olmaz",
       "E": "TÜFE'ye endeksli: reel getiri, nominal getiriyle karşılaştırılmaz"}

MOM_DAYS = 21                    # closes: the momentum's month
VOL_DAYS = 60                    # the daily moves a σ is measured over
WEEK = 5.0                       # business days a switch is held (to the next rebalance)
MONTH_DAYS = 30                  # calendar days of the carry + roll's month (quantcurve's "1m")
MONTH_CLOSES = 21.0              # closes of a month: a close's carry + roll is the month's ÷ 21
MIN_LEFT = qc.MIN_DAYS + 7       # a bond this close to its maturity at a close (days) is out
DUR_RATIO = 1.5                  # the duration band: the longer's modified duration at most this × the shorter's
MIN_GAP = 1.0                    # composites a switch's two bonds differ by at least (z units)
MAX_SWITCHES = 3                 # switches a week
MIN_BONDS = 4                    # bonds a ranking needs
CURVE_MIN = 4                    # fixed-coupon bonds a close's fitted curve needs (fewer: straight lines between them)
TAUS = (1.0, 2.0, 4.0)           # the fitted curve's τ (years): the best of them (a shorter one bends the short end on a few bonds)
T_MULT, S_MULT = 1.5, 1.0        # the own levels before a calibration: σ of the week
ROUND_TL = 5e6                   # the desk's rounding of a bond's nominal (OIS_MAIN!H2) when the workbook does not say
CR_MONTHS = 3.0                  # DİBS RV's C+R horizon (J2, months) when the workbook does not say
EDGE = 0.95                      # a pair not taken: its "sıra" at most this
STALE_DAYS = qs.STALE_DAYS
SETTINGS = {"mom_days": MOM_DAYS, "vol_days": VOL_DAYS, "hold": WEEK, "month_days": MONTH_DAYS, "dur_ratio": DUR_RATIO, "min_gap": MIN_GAP,
            "max_switches": MAX_SWITCHES, "min_bonds": MIN_BONDS, "t_mult": T_MULT, "s_mult": S_MULT, "min_left": MIN_LEFT}
NOTE = ("Haftada bir (pazartesi kapanışı) trading listesinin sabit kuponluları ve bonoları aylık carry + roll'larına ve son bir ayın "
        "getiri hareketine göre sıralanır (ikisi de kâğıtlar arasında z); bileşik skoru yüksek kâğıt alınır, süresi benzer (uzunun "
        "modifiye süresi kısanınkinin en çok 1,5 katı) skoru düşük kâğıt satılır, DV01 dengeli. Seviye: getiri farkı (AL − SAT, basit "
        "getiri, bp); switch fark daralınca kazanır. Büyüklük: AL bacağı masanın DV01'i (1.000 $), nominaller DİBS RV!AK gibi 5 mn "
        "TL'ye yuvarlı. Hedef / stop geçmiş haftalık switch'lerden ayarlı.")


def _d(iso: str) -> _dt.date:
    return _dt.date.fromisoformat(iso)


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _to_simple(bond: qc.Bond, y: Optional[float], conv: str, value: _dt.date) -> Optional[float]:
    """A yield (per cent) of ``conv`` as the bond's BIST simple one (per cent): a coupon bond's compounded ``freq``
    times a year, a bill's simple ACT/365 - a compound bill's from its price."""
    if y is None or not math.isfinite(y):
        return None
    if conv != "compound":
        return y
    if bond.kind == "bill":
        days = (bond.maturity - value).days
        if days <= 0 or y <= -100.0:
            return None
        p = 100.0 * (1.0 + y / 100.0) ** (-days / qc.YEAR)
        return (100.0 / p - 1.0) * qc.YEAR / days * 100.0
    return qc.to_simple(bond, y / 100.0, conv) * 100.0


def _g(x: float) -> float:
    return (1.0 - math.exp(-x)) / x if x > 1e-9 else 1.0 - x / 2.0


def fit_curve(pts: Sequence[Tuple[float, float]]) -> Optional[Callable[[float], float]]:
    """A close's yield curve through ``(years, yield %)``: a Nelson-Siegel - level, slope, hump - of the best τ of
    ``TAUS`` (least squares, the β linear); with fewer than ``CURVE_MIN`` points straight lines between them; ``None``
    with fewer than two.  Flat beyond the points' ends (a bill shorter than the shortest bond rolls on nothing)."""
    pts = sorted(p for p in pts if p[0] > 0)
    if len(pts) < 2:
        return None
    if len(pts) < CURVE_MIN:
        return lambda t, pts=pts: qf._interp(list(pts), t)
    best = None
    for tau in TAUS:
        rows = [[1.0, _g(t / tau), _g(t / tau) - math.exp(-t / tau)] for t, _ in pts]
        ata = [[sum(r[i] * r[j] for r in rows) + (1e-9 if i == j else 0.0) for j in range(3)] for i in range(3)]
        aty = [sum(r[i] * y for r, (_, y) in zip(rows, pts)) for i in range(3)]
        beta = qm.solve(ata, aty)
        if beta is None:
            continue
        sse = sum((sum(b * x for b, x in zip(beta, r)) - y) ** 2 for r, (_, y) in zip(rows, pts))
        if best is None or sse < best[0] - 1e-12:
            best = (sse, tau, beta)
    if best is None:
        return lambda t, pts=pts: qf._interp(list(pts), t)
    _, tau, (b0, b1, b2) = best
    lo, hi = pts[0][0], pts[-1][0]

    def curve(t: float) -> float:
        t = min(max(t, lo), hi)
        g = _g(t / tau)
        return b0 + b1 * g + b2 * (g - math.exp(-t / tau))

    return curve


# ---------------------------------------------------------------------------------------------- the bonds
class Bond(object):
    """A bond of the universe: its ISIN, terms (``quantcurve.Bond``), DİBS RV's row, kind ("S" / "B"), the convention its
    history is in and its closes as simple yields (per cent)."""

    def __init__(self, isin: str, bond: qc.Bond, kind: str, row: Optional[Dict[str, Any]], conv: str, pts: Sequence[Tuple[str, float]]):
        self.isin, self.bond, self.kind, self.row, self.conv = isin, bond, kind, row, conv
        self.label = qc._bond_label(bond)
        days: List[str] = []
        ys: List[float] = []
        for d, v in pts:
            y = _to_simple(bond, v, conv, qc._value_date(_d(d), row))
            if y is not None:
                days.append(d)
                ys.append(y)
        self.days, self.ys = days, ys
        self._m: Dict[int, Optional[Dict[str, float]]] = {}

    def __repr__(self) -> str:
        return "<Bond %s>" % self.isin

    def at(self, day: str) -> Optional[int]:
        """The last close on or before ``day`` - none staler than a week."""
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0 or (_d(day) - _d(self.days[i])).days > STALE_DAYS:
            return None
        return i

    def metrics(self, i: int) -> Optional[Dict[str, float]]:
        """At close ``i``: the dirty price, modified duration and DV01 of 1 mn nominal (TL a bp: DİBS RV!AI's, of the
        simple yield) at its value date."""
        if i not in self._m:
            out = None
            day = _d(self.days[i])
            value = qc._value_date(day, self.row)
            try:
                p, dp = self.bond.price(self.ys[i] / 100.0, value, "simple")
                if p > 0 and dp < 0:
                    out = {"price": p, "dur": -dp / p, "dv01": -dp}
            except (ValueError, ZeroDivisionError, OverflowError):
                out = None
            self._m[i] = out
        return self._m[i]

    def now(self, ctx: qf.Ctx, live: Dict[str, float]) -> Optional[float]:
        """The simple yield now: the sheet's live simple one, else its compound one converted, else the last close."""
        v = _num(live.get("DIBSS:" + self.isin))
        if v is not None:
            return v
        c = _num(live.get("DIBSC:" + self.isin))
        if c is not None:
            return _to_simple(self.bond, c, "compound", qc._value_date(ctx.today, self.row))
        return self.ys[-1] if self.ys else None


def _label(isin: str, m: Dict[str, Any], kind: str) -> str:
    """A bond left out, as the desk names it ("09.01.30 TLREF"): the catalog's, else from its maturity, else its ISIN."""
    from . import bonds as bd
    cat = bd.by_isin(isin)
    tail = {"T": "float", "F": "frn", "E": "cpi", "B": "bill", "S": "fixed"}.get(kind)
    try:
        if cat:
            return bd.short_label(cat)
        if m.get("maturity"):
            return bd.short_label({"isin": isin, "maturity": m["maturity"], "kind": tail})
    except (ValueError, TypeError):
        pass
    return isin


def universe(ctx: qf.Ctx, rows: Dict[str, Dict[str, Any]]) -> Tuple[List[Bond], List[Dict[str, Any]]]:
    """The trading list's fixed-coupon bonds and bills (by maturity) and the bonds left out with their reason."""
    bonds: List[Bond] = []
    out: List[Dict[str, Any]] = []
    for key, m in ctx.meta.items():
        if not key.startswith("DIBS:"):
            continue
        isin = key[5:].upper()
        row = rows.get(isin)
        kind = str(m.get("type") or (row or {}).get("type") or "").upper()
        if kind in OUT or m.get("unit") == "px":
            kind = kind if kind in OUT else "T"
            out.append({"isin": isin, "label": _label(isin, m, kind), "kind": kind, "why": OUT[kind]})
            continue
        b = qc._bond_of(isin, m, row)
        if b is None or b.kind not in ("fixed", "bill"):
            out.append({"isin": isin, "label": _label(isin, m, kind), "kind": kind,
                        "why": "kuponu ya da vadesi bilinmiyor (DİBS RV ve kâğıt kataloğu)"})
            continue
        kind = "S" if b.kind == "fixed" else "B"
        left = (b.maturity - ctx.today).days
        if left < MIN_LEFT:
            out.append({"isin": isin, "label": qc._bond_label(b), "kind": kind,
                        "why": "vadesine %d gün kaldı (en az %d)" % (max(left, 0), MIN_LEFT)})
            continue
        conv = qc.detect_convention(ctx.last(key), qc._pct((row or {}).get("simple")), qc._pct((row or {}).get("compound")))
        bonds.append(Bond(isin, b, kind, row, conv, ctx.pts(key)))
    bonds.sort(key=lambda x: (x.bond.maturity, x.isin))
    return bonds, out


# ---------------------------------------------------------------------------------------------- the engine
class Engine(object):
    """The family on one context: the bonds, each close's funding and fitted curve, a bond's score parts at a close,
    the ranking and switches of a rebalance, a pair's yield difference, the walk forward."""

    def __init__(self, ctx: qf.Ctx, rows: Dict[str, Dict[str, Any]]):
        self.ctx = ctx
        self.rows = rows
        self.bonds, self.out = universe(ctx, rows)
        self.by = {b.isin: b for b in self.bonds}
        self.calendar = sorted({d for b in self.bonds for d in b.days})
        self.ois = qs._Curve(ctx)
        self._curves: Dict[str, Optional[Callable[[float], float]]] = {}
        self._fund: Dict[str, Optional[float]] = {}
        self._feats: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
        self._pairs: Dict[Tuple[str, str], qs._Ser] = {}

    # ---- a close's market
    def fund(self, day: str) -> Optional[float]:
        """The funding to a month at ``day``'s close (%): the OIS curve at one month (TLREF at 0 months)."""
        if day not in self._fund:
            pts = self.ois.points(day)[1]
            self._fund[day] = qf._interp(pts, 1.0) if pts else None
        return self._fund[day]

    def curve(self, day: str) -> Optional[Callable[[float], float]]:
        """``day``'s fitted curve of the fixed-coupon bonds' simple yields against their years."""
        if day not in self._curves:
            pts = []
            dd = _d(day)
            for b in self.bonds:
                if b.kind != "S":
                    continue
                i = b.at(day)
                left = (b.bond.maturity - dd).days
                if i is not None and left >= MIN_LEFT:
                    pts.append((left / qc.YEAR, b.ys[i]))
            self._curves[day] = fit_curve(pts)
        return self._curves[day]

    def feats(self, b: Bond, day: str) -> Optional[Dict[str, Any]]:
        """A bond's score parts at ``day``'s close (its closes up to it only): yield, carry, roll and C+R a month (bp of
        its DV01, a holder's), momentum (bp), duration, DV01 - ``None`` without a month of closes, a funding or a
        price."""
        key = (b.isin, day)
        if key in self._feats:
            return self._feats[key]
        out = None
        i = b.at(day)
        left = (b.bond.maturity - _d(day)).days
        if i is not None and i >= MOM_DAYS and left >= MIN_LEFT:
            m = b.metrics(i)
            f = self.fund(day)
            if m is not None and f is not None and m["dur"] > 0:
                y = b.ys[i]
                h = MONTH_DAYS / qc.YEAR
                carry = (y - f) * 100.0 * h / m["dur"]
                cv = self.curve(day)
                t = left / qc.YEAR
                roll = (cv(t) - cv(max(t - h, 1e-6))) * 100.0 if cv is not None else 0.0
                out = {"isin": b.isin, "y": y, "f": f, "carry": carry, "roll": roll, "cr": carry + roll,
                       "mom": -(y - b.ys[i - MOM_DAYS]) * 100.0, "dur": m["dur"], "dv01": m["dv01"], "years": t, "close": b.days[i]}
        self._feats[key] = out
        return out

    # ---- a pair
    def pair(self, a: Bond, b: Bond) -> qs._Ser:
        """The yield difference y_a − y_b (bp) on the closes both have, with its daily moves."""
        key = (a.isin, b.isin)
        hit = self._pairs.get(key)
        if hit is None:
            ib = {d: i for i, d in enumerate(b.days)}
            pts = [(d, (y - b.ys[ib[d]]) * 100.0) for d, y in zip(a.days, a.ys) if d in ib]
            hit = self._pairs[key] = qs._ser(pts, lambda x, y: y - x)
        return hit

    # ---- a rebalance
    def rank(self, day: str) -> Optional[Dict[str, Any]]:
        """The ranking at ``day``'s close and its switches: every bond's parts, z's and composite, every pair within the
        duration band (its AL / SAT and gap), the switches taken - the widest gap first, no bond twice."""
        rows = [f for f in (self.feats(b, day) for b in self.bonds) if f is not None]
        if len(rows) < MIN_BONDS:
            return None
        rows = [dict(r) for r in rows]
        for r, zc, zm in zip(rows, qs._z([r["cr"] for r in rows]), qs._z([r["mom"] for r in rows])):
            r.update(z_cr=zc, z_mom=zm, comp=zc + zm)
        rows.sort(key=lambda r: (-r["comp"], r["isin"]))
        for k, r in enumerate(rows):
            r["rank"] = k + 1
        pairs = []
        for k, ra in enumerate(rows):
            for rb in rows[k + 1:]:
                lo, hi = sorted((ra["dur"], rb["dur"]))
                if lo <= 0 or hi / lo > DUR_RATIO + 1e-12:
                    continue
                # (the rows by composite: the first of the two the higher - AL)
                pairs.append({"al": ra, "sat": rb, "gap": ra["comp"] - rb["comp"], "key": pair_key(self.by[ra["isin"]], self.by[rb["isin"]])})
        pairs.sort(key=lambda p: (-p["gap"], p["al"]["isin"], p["sat"]["isin"]))
        used: set = set()
        chosen: List[Dict[str, Any]] = []
        for p in pairs:
            if len(chosen) >= MAX_SWITCHES or p["gap"] < MIN_GAP:
                break
            if p["al"]["isin"] in used or p["sat"]["isin"] in used:
                continue
            sw = self.switch(p, day)
            if sw is None:
                continue
            chosen.append(sw)
            used.update((p["al"]["isin"], p["sat"]["isin"]))
        n = len(chosen)
        for k, sw in enumerate(chosen):
            sw["rank"] = k + 1
            sw["sira"] = 2.0 - k / (n - 1.0) if n > 1 else 2.0
        edge = max(MIN_GAP, min((sw["gap"] for sw in chosen), default=MIN_GAP))
        taken = {sw["key"]: sw for sw in chosen}
        for p in pairs:
            first = self.by[p["key"][0]]
            way = -1 if p["al"]["isin"] == first.isin else 1        # (the shorter bond bought: its difference falling)
            sw = taken.get(p["key"])
            p["z"] = way * sw["sira"] if sw is not None else way * EDGE * min(1.0, max(p["gap"], 0.0) / edge)
            p["taken"] = sw is not None
        side = {}
        for sw in chosen:
            side[sw["al"].isin], side[sw["sat"].isin] = "AL", "SAT"
        for r in rows:
            r["side"] = side.get(r["isin"], "")
        return {"day": day, "rows": rows, "pairs": pairs, "switches": chosen, "edge": edge}

    def switch(self, p: Dict[str, Any], day: str) -> Optional[Dict[str, Any]]:
        """A pair taken: AL / SAT, the yield difference (y_AL − y_SAT) at the close and its daily σ over the 60 before -
        ``None`` without enough of them."""
        al, sat = self.by[p["al"]["isin"]], self.by[p["sat"]["isin"]]
        ser = self.pair(al, sat)
        i = ser.at(day)
        if i is None:
            return None
        sd = ser.sigma(i, VOL_DAYS)
        if sd is None:
            return None
        return {"al": al, "sat": sat, "fa": p["al"], "fs": p["sat"], "gap": p["gap"], "key": p["key"], "level": ser.vals[i], "sd": sd,
                "sigma": sd * math.sqrt(WEEK), "cr": p["al"]["cr"] - p["sat"]["cr"], "mom": p["al"]["mom"] - p["sat"]["mom"], "day": day}

    def path(self, sw: Dict[str, Any], day: str, end: str) -> List[float]:
        """The switch's P&L at every close after ``day``'s up to ``end``'s (bp of the AL leg's DV01): the fall of its yield
        difference plus its carry + roll pro rata."""
        ser = self.pair(sw["al"], sw["sat"])
        i0 = ser.at(day)
        if i0 is None:
            return []
        c0, c1 = bisect.bisect_right(self.calendar, day), bisect.bisect_right(self.calendar, end)
        out = []
        for j in range(c0, c1):
            k = ser.at(self.calendar[j])
            move = -(ser.vals[k] - ser.vals[i0]) if k is not None else 0.0
            out.append(move + sw["cr"] * (j - c0 + 1) / MONTH_CLOSES)
        return out

    def walk(self, holidays: Optional[set], tl: Optional[float]) -> Dict[str, Any]:
        """Every rebalance of the history: its switches held to the next one's close (each a trade with its path), every
        pair's "sıra" then (``z``: day -> pair -> sıra) and the last rebalance's ranking - this week's."""
        rebal = qs.rebalance_days(self.calendar, holidays)
        trades: List[Dict[str, Any]] = []
        weeks: List[Dict[str, Any]] = []
        zs: Dict[str, Dict[Tuple[str, str], float]] = {}
        for day, end in zip(rebal, rebal[1:]):
            r = self.rank(day)
            if r is None:
                continue
            zs[day] = {p["key"]: p["z"] for p in r["pairs"]}
            tot = 0.0
            done = []
            for sw in r["switches"]:
                p = self.path(sw, day, end)
                if not p:
                    continue
                pnl = p[-1]
                tot += pnl
                done.append(sw)
                ser = self.pair(sw["al"], sw["sat"])
                k = ser.at(end)
                text = "AL %s / SAT %s" % (sw["al"].isin, sw["sat"].isin)
                trades.append({"sid": "%s:%s/%s" % (FAMILY, sw["al"].isin, sw["sat"].isin), "family": FAMILY, "type": TYPE, "group": GROUP,
                               "entry_day": day, "exit_day": end, "end_day": end, "dir": -1, "entry": sw["level"],
                               "exit": ser.vals[k] if k is not None else None, "outcome": "süre", "held": len(p), "pnl": pnl, "unit": "bp",
                               "pnl_sigma": pnl / sw["sigma"], "pnl_try": pnl * tl if tl else None, "expression": text,
                               "path_sigma": [x / sw["sigma"] for x in p], "sigma": sw["sigma"], "sigma_closes": WEEK, "carry_sigma": 0.0,
                               "carry_in": True, "try": tl, "cr": sw["cr"], "gap": sw["gap"]})
            weeks.append({"day": day, "end": end, "n": len(done), "pnl": tot, "pnl_try": tot * tl if tl else None,
                          "text": " · ".join("AL %s / SAT %s" % (sw["al"].label, sw["sat"].label) for sw in done)})
        cur = self.rank(rebal[-1]) if rebal else None
        if cur is not None:
            zs[cur["day"]] = {p["key"]: p["z"] for p in cur["pairs"]}
        return {"rebal": rebal, "trades": trades, "weeks": weeks, "z": zs, "current": cur}


def pair_key(a: Bond, b: Bond) -> Tuple[str, str]:
    """A pair in its one orientation: the shorter bond first (the ISIN breaks a tie)."""
    x, y = sorted((a, b), key=lambda o: (o.bond.maturity, o.isin))
    return x.isin, y.isin


def _zhist(days: Sequence[str], zs: Dict[str, Dict[Tuple[str, str], float]], key: Tuple[str, str]) -> List[Optional[float]]:
    """A pair's "sıra" day by day: the last rebalance's up to that close (None where it was no pair of the band)."""
    rebal = sorted(zs)
    out: List[Optional[float]] = []
    for d in days:
        i = bisect.bisect_right(rebal, d) - 1
        out.append(zs[rebal[i]].get(key) if i >= 0 else None)
    return out


# ---------------------------------------------------------------------------------------------- the size
def round_tl(ctx: qf.Ctx) -> float:
    """The desk's rounding of a bond's nominal (TL): OIS_MAIN!H2 "Yuvarlama TL", else 5 mn."""
    v = _num((ctx.desk or {}).get("round_tl"))
    return v if v and v > 0 else ROUND_TL


def sizes(ctx: qf.Ctx, dv_al: float, dv_sat: float) -> Optional[Dict[str, Any]]:
    """The two legs' nominals (TL): the AL leg the desk's DV01 (``dv01_usd`` at USDTRY: TL a bp) rounded as DİBS RV!AK
    rounds it, the SAT leg the same DV01 rounded the same way (``dv_*``: TL a bp of 1 mn nominal); their DV01s."""
    usd, tl = ctx.dv01_size()
    if not tl or not dv_al or not dv_sat:
        return None
    r = round_tl(ctx)
    n_al = max(1, round(tl / dv_al * 1e6 / r)) * r
    n_sat = max(1, round(n_al * dv_al / dv_sat / r)) * r
    fx = tl / usd if usd else None
    d_al, d_sat = n_al / 1e6 * dv_al, n_sat / 1e6 * dv_sat
    return {"al": n_al, "sat": n_sat, "dv01_al": d_al, "dv01_sat": d_sat, "usd_al": d_al / fx if fx else None, "usd_sat": d_sat / fx if fx else None,
            "gap": (d_al - d_sat) / d_al if d_al else None, "round": r, "tl": tl, "usd": usd}


def mn_text(v: float) -> str:
    """A nominal as the desk says it: "210 mn", "7,5 mn"."""
    x = v / 1e6
    return "%s mn" % qf._th(x, 0 if abs(x - round(x)) < 0.05 else 1)


# ---------------------------------------------------------------------------------------------- the lines
def sheet_cr(eng_rows: Dict[str, Dict[str, Any]], months: Optional[float], isin: str) -> Optional[float]:
    """A bond's C+R a month as DİBS RV has it now (AO, bp over its horizon J2, ÷ the horizon's months)."""
    v = _num((eng_rows.get(isin) or {}).get("cr_bp"))
    h = months if months and months > 0 else CR_MONTHS
    return v / h if v is not None else None


class Line(object):
    """A pair of the week's ranking: its two bonds in their orientation, the side the ranking took, its sizes, C+R and
    momentum, its yield difference's history and its "sıra"."""

    def __init__(self, eng: Engine, p: Dict[str, Any], cur: Dict[str, Any], sw: Optional[Dict[str, Any]], walk: Dict[str, Any],
                 cr_months: Optional[float], stats: Dict[str, Any], nxt: _dt.date):
        self.eng = eng
        self.ctx = eng.ctx
        self.first, self.second = eng.by[p["key"][0]], eng.by[p["key"][1]]
        self.key = p["key"]
        self.sid = "%s:%s/%s" % (FAMILY, self.first.isin, self.second.isin)
        self.al, self.sat = eng.by[p["al"]["isin"]], eng.by[p["sat"]["isin"]]
        self.fa, self.fs = p["al"], p["sat"]
        self.way = 1 if self.al is self.second else -1           # (the side of y_first − y_second the switch is)
        self.z = p["z"]
        self.taken = bool(p["taken"])
        self.gap = p["gap"]
        self.sw = sw
        self.formed = cur["day"]
        self.next = nxt
        self.stats = stats
        self.ser = eng.pair(self.first, self.second)
        last = eng.calendar[-1] if eng.calendar else cur["day"]
        # carry + roll a month (bp, of the switch): DİBS RV's own now where it has both bonds', else the history's at the last
        # close (else at the ranking's)
        live_cr = [sheet_cr(eng.rows, cr_months, b.isin) for b in (self.al, self.sat)]
        hist = [eng.feats(b, last) or f for b, f in ((self.al, self.fa), (self.sat, self.fs))]
        self.cr_hist = hist[0]["cr"] - hist[1]["cr"]
        self.cr_sheet = live_cr[0] - live_cr[1] if None not in live_cr else None
        self.cr = self.cr_sheet if self.cr_sheet is not None else self.cr_hist
        self.mom = self.fa["mom"] - self.fs["mom"]
        dv_al, dv_sat = (eng.feats(self.al, last) or self.fa)["dv01"], (eng.feats(self.sat, last) or self.fs)["dv01"]
        self.size = sizes(self.ctx, dv_al, dv_sat)
        self.size_text = "%s / %s" % (mn_text(self.size["al"]), mn_text(self.size["sat"])) if self.size else "—"
        lv = self.ser.vals
        self.dsd = self.ser.sigma(len(lv) - 1, VOL_DAYS) if lv else None
        self.level_formed = (self.ser.vals[self.ser.at(self.formed)] if self.ser.at(self.formed) is not None else None)

    def level(self, live: Dict[str, float]) -> Optional[float]:
        a, b = self.first.now(self.ctx, live), self.second.now(self.ctx, live)
        return (a - b) * 100.0 if a is not None and b is not None else None

    def legs(self) -> List[Dict[str, Any]]:
        """The AL leg first (its DV01 the package's), then the SAT leg - weights ±1 of y_first − y_second."""
        out = []
        for b, n, dv, usd in ((self.al, "al", "dv01_al", "usd_al"), (self.sat, "sat", "dv01_sat", "usd_sat")):
            w = 1.0 if b is self.first else -1.0
            leg = {"key": "DIBS:" + b.isin, "name": "%s (%s)" % (b.isin, b.label), "weight": w}
            if self.size:
                leg.update({"dv01": w * self.size[dv], "dv01_usd": w * self.size[usd] if self.size[usd] is not None else None,
                            "notional": self.size[n] / 1e6})
            out.append(leg)
        return out


def _monitor(line: Line, cfg: Dict[str, Any], walk: Dict[str, Any]) -> qf.Monitor:
    """The pair's monitor: its yield difference (bp, y_first − y_second), "sıra" now, the switch's legs and size; its own
    levels until the calibrated ones come (1,5σ / 1σ of the week, the week's C+R expected), no gate."""
    sig_h = line.dsd * math.sqrt(WEEK) if line.dsd else None
    days, vals = list(line.ser.days), list(line.ser.vals)
    info = {"version": TYPE, "model": MODEL, "group": GROUP, "tier": None, "priority": qu.priority(GROUP), "tag": "", "size": line.size_text,
            "k": 1.0, "al": line.al.isin, "sat": line.sat.isin, "formed": line.formed, "next": line.next.isoformat(), "rank": (line.sw or {}).get("rank"),
            "of": None, "gap": line.gap, "cr": line.cr, "mom": line.mom,
            "inputs": ["DIBSS:" + line.first.isin, "DIBSC:" + line.first.isin, "DIBSS:" + line.second.isin, "DIBSC:" + line.second.isin]}
    # (the level rising - the second bond bought, the first sold - is the up side: its C+R a week is the switch's when
    # the ranking bought the second, its negative when it bought the first)
    m = qf.Monitor(line.sid, FAMILY, "DİBS", "%s / %s switch" % (line.first.isin, line.second.isin), "bp", 1, days, vals, line.legs(),
                   line.level, zfn=lambda lv, live, z=line.z: z, zvalues=_zhist(days, walk["z"], line.key), mode="drift", follows=True,
                   entry=1.0, score_name="sıra", ungated=True, hold=WEEK, dsd=line.dsd, pnl=("bp", 1.0), pkg="bond", explicit=True,
                   carry_up=line.way * line.cr * WEEK / MONTH_CLOSES, fcast=0.0,
                   reward=T_MULT * sig_h if sig_h else None, risk=S_MULT * sig_h if sig_h else None, note=NOTE, info=info,
                   regime={"tag": None}, series_label="getiri farkı %s − %s (basit getiri, bp)" % (line.first.label, line.second.label))
    m.finish = lambda sg: _finish(line, sg)
    m.dibssw = line
    return m


def _finish(line: Line, sg: Dict[str, Any]) -> None:
    """make_signal's line made the plan's: "AL … / SAT … · switch · 210 mn / 205 mn · C+R +18,0 bp/ay · 1A momentum lehte ·
    hedef +12,0 bp · stop -8,0 bp · beklenen +504 bin TL · isabet %56 (142)" - target and stop moves of the yield
    difference in the trade's favour; the card's sentence."""
    s = int(sg.get("direction") or 0)
    if s and s != line.way:
        return                                              # (a side the week's ranking did not take: told as it is)
    lv = sg.get("levels") or {}
    cal = bool(lv.get("ok"))
    entry = sg.get("entry")
    t_bp = abs(sg["target"] - entry) if sg.get("target") is not None and entry is not None else None
    s_bp = abs(sg["stop"] - entry) if sg.get("stop") is not None and entry is not None else None
    mo = sg.get("money") or {}
    hit, n = (lv.get("hit"), int(lv.get("n") or 0)) if cal else (line.stats.get("hit"), int(line.stats.get("trades") or 0))
    mom = "lehte" if line.mom > 0 else ("aleyhte" if line.mom < 0 else "nötr")
    head = "AL %s / SAT %s · switch · %s" % (line.al.isin, line.sat.isin, line.size_text)
    parts = [head, "C+R %s bp/ay" % qf._sg(line.cr, 1), "1A momentum %s" % mom,
             "hedef +%s bp" % qf._g(t_bp, 1) if t_bp is not None else "hedef —", "stop -%s bp" % qf._g(s_bp, 1) if s_bp is not None else "stop —",
             "beklenen " + qf._money(mo.get("total"), "TL"), ("isabet %%%s (%d)" % (qf._g((hit or 0.0) * 100.0, 0), n)) if n else "isabet — (0)"]
    text = " · ".join(parts)
    sg["expression"] = sg["line"] = text
    lvl = sg.get("level")
    now = "%s / %s getiri farkı (AL − SAT, basit getiri) şimdi %s" % (line.al.label, line.sat.label, qf._sg(-line.way * lvl, 1) + " bp" if lvl is not None else "—")
    rr = ("hedefte %s, stopta %s" % (qf._money(mo.get("target"), "TL"), qf._money(mo.get("stop"), "TL"))) if mo.get("target") is not None else ""
    size = ""
    if line.size:
        size = (" AL bacağı masanın DV01'i (%s $, %s TL/bp), SAT bacağı aynı DV01; nominaller %s TL'ye yuvarlı (DİBS RV!AK gibi), DV01 farkı %%%s."
                % (qf._th(line.size["usd"], 0), qf._th(line.size["dv01_al"], 0), mn_text(line.size["round"]),
                   qf._g(abs(line.size["gap"] or 0.0) * 100.0, 1)))
    cr_src = "DİBS RV'nin C+R'ı, AO aylık" if line.cr_sheet is not None else "tarihçeden: fonlama 1 aylık OIS, eğride yuvarlanma"
    lv_txt = ("Seviyeler geçmiş haftalık switch'lerden: %s." % lv.get("text") if cal and lv.get("text")
              else "Seviyeler: kalibrasyon yok (%s) - hedef %sσ, stop %sσ (haftanın σ'sı), beklenen haftanın C+R'ı." % (
                  lv.get("why") or "geçmiş işlem az", qf._g(T_MULT, 1), qf._g(S_MULT, 0)))
    sg["plain"] = ("DİBS switch: %s'i al, %s'i sat (%s). Bileşik skor farkı %s: aylık carry + roll farkı %s bp (%s), son bir ayda getiri "
                   "farkı %s bp %s. %s. Hedefe %s bp, stopa %s bp (getiri farkının işlem yönündeki hareketi); bir haftalık beklenen %s%s.%s %s" % (
                       line.al.label, line.sat.label, line.size_text, qf._g(line.gap, 2), qf._sg(line.cr, 1), cr_src, qf._sg(line.mom, 1), mom,
                       now, qf._g(t_bp, 1), qf._g(s_bp, 1), qf._money(mo.get("total"), "TL"), (" - " + rr) if rr else "", size, lv_txt))
    sg["thesis"] = "DİBS switch: %s. Sonraki dengeleme %s kapanışı." % (text, qs._day_tr(line.next))
    sg["dibssw"] = {"al": line.al.isin, "sat": line.sat.isin, "al_label": line.al.label, "sat_label": line.sat.label, "size": line.size,
                    "cr": line.cr, "cr_sheet": line.cr_sheet, "cr_hist": line.cr_hist, "mom": line.mom, "gap": line.gap, "target_bp": t_bp,
                    "stop_bp": s_bp, "formed": line.formed, "next": line.next.isoformat()}


# ---------------------------------------------------------------------------------------------- the family
def _stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    first = min((t["entry_day"] for t in trades), default=None)
    last = max((t["exit_day"] for t in trades), default=None)
    st = qbt.summarize(trades, first, last)
    st.update({"first": first, "last": last, "weeks": len({t["entry_day"] for t in trades})})
    return st


def _bond_row(r: Dict[str, Any], eng: Engine, cr_months: Optional[float]) -> Dict[str, Any]:
    b = eng.by[r["isin"]]
    return {"isin": b.isin, "label": b.label, "kind": b.kind, "kind_text": KINDS.get(b.kind, ""), "maturity": b.bond.maturity.isoformat(),
            "years": r["years"], "dur": r["dur"], "dv01": r["dv01"], "y": r["y"], "f": r["f"], "carry": r["carry"], "roll": r["roll"],
            "cr": r["cr"], "cr_sheet": sheet_cr(eng.rows, cr_months, b.isin), "mom": r["mom"], "z_cr": r["z_cr"], "z_mom": r["z_mom"],
            "comp": r["comp"], "rank": r["rank"], "side": r["side"], "n": len(b.days), "conv": b.conv}


@qu.family(FAMILY, own_backtest=True)
def run(ctx: qf.Ctx, reg: qu.Registry, cfg: Dict[str, Any]) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """The walk forward over the history, this week's ranking and switches, a monitor for every pair of the band; the
    table of the page with the family's calibrated levels and its trades (the backtest)."""
    t0 = time.perf_counter()
    rows = {str(r.get("isin") or "").upper(): r for r in (reg.eng.get("dibs") or []) if r.get("isin")}
    cr_months = _num(reg.eng.get("dibs_cr_months"))
    eng = Engine(ctx, rows)
    usd, tl = ctx.dv01_size()
    walk = eng.walk(ctx.holidays, tl)
    t_walk = time.perf_counter()
    trades = walk["trades"]
    stats = _stats(trades)
    levels = qlv.calibrate(trades, FAMILY, ctx.today_iso)
    lv = levels.line(GROUP)
    nxt = qs.next_rebalance(ctx.today, eng.calendar, ctx.holidays)
    cur = walk["current"]
    table: Dict[str, Any] = {"ok": cur is not None, "today": ctx.today_iso, "settings": dict(SETTINGS, round_tl=round_tl(ctx), dv01_usd=usd, tl=tl,
                                                                                        cr_months=cr_months or CR_MONTHS),
                             "next": nxt.isoformat(), "next_text": qs._day_tr(nxt), "note": NOTE,
                             "out": eng.out, "bonds": [], "switches": [], "pairs": 0,
                             "backtest": {"trades": trades, "first": stats["first"], "last": stats["last"]}, "stats": stats,
                             "levels": levels.to_json(), "level_line": {k: lv.get(k) for k in ("ok", "k", "m", "rr", "hit", "exp", "n", "oos", "scope", "why")},
                             "weeks": walk["weeks"][-26:]}
    table["level_line"]["text"] = qf.levels_text(lv)
    mons: List[qf.Monitor] = []
    if cur is None:
        n = len(eng.bonds)
        table["why"] = ("DİBS geçmişi yok: trading listesinde sabit kuponlu ya da bono yok" if not n else
                        "geçmiş yetersiz: en az %d kâğıdın %d kapanışı ve fonlama gerekli (%d kâğıt var)" % (MIN_BONDS, MOM_DAYS + 1, n))
    else:
        table.update({"formed": cur["day"], "formed_text": qs._day_tr(_d(cur["day"])), "pairs": len(cur["pairs"]),
                      "bonds": [_bond_row(r, eng, cr_months) for r in cur["rows"]]})
        taken = {sw["key"]: sw for sw in cur["switches"]}
        for p in cur["pairs"]:
            line = Line(eng, p, cur, taken.get(p["key"]), walk, cr_months, stats, nxt)
            if line.dsd is None:
                continue
            mons.append(_monitor(line, cfg, walk))
            sw = taken.get(p["key"])
            if sw is None:
                continue
            sig_h = line.dsd * math.sqrt(WEEK)
            k, m_ = (float(lv["k"]), float(lv["m"])) if lv.get("ok") else (S_MULT, T_MULT)
            table["switches"].append({"sid": line.sid, "rank": sw["rank"], "z": line.z, "al": line.al.isin, "sat": line.sat.isin,
                                      "al_label": line.al.label, "sat_label": line.sat.label, "al_kind": line.al.kind, "sat_kind": line.sat.kind,
                                      "dur_al": line.fa["dur"], "dur_sat": line.fs["dur"], "gap": sw["gap"], "cr": line.cr, "cr_sheet": line.cr_sheet,
                                      "cr_hist": line.cr_hist, "mom": line.mom, "level": sw["level"], "sigma_h": sig_h, "target_bp": m_ * sig_h,
                                      "stop_bp": k * sig_h, "size": line.size, "size_text": line.size_text, "way": line.way,
                                      "level_formed": -line.way * line.level_formed if line.level_formed is not None else None})
    table["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    table["timing"] = {"walk_ms": round((t_walk - t0) * 1000.0, 1), "bonds": len(eng.bonds), "closes": len(eng.calendar),
                       "rebalances": len(walk["rebal"]), "trades": len(trades)}
    return mons, table


# ---------------------------------------------------------------------------------------------- the page
def coverage_keys(ctx_meta: Dict[str, Any]) -> set:
    """The series the page's coverage table lists: TLREF and the OIS curve (the funding); the bonds' closes are in its
    own table."""
    return {"TLREF"} | {k for k in ctx_meta if k.startswith("OIS:")}


def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    """What the page "DİBS switch" reads: this week's ranking and switches - each with its line now (level, target,
    stop, money, the P&L since the rebalance) -, the bonds left out, the backtest's record and weeks, the family's lines."""
    from .quant import _clean
    raw = (fit.get("tables") or {}).get(FAMILY) or {}
    tab = {k: x for k, x in raw.items() if k not in ("backtest", "levels")}
    sigs = {s["id"]: s for s in v["signals"] + v["gated"] if s["family"] == FAMILY}
    out = []
    for sw in raw.get("switches") or ():
        sw = dict(sw)
        m = fit["mons"].get(sw["sid"])
        sg = sigs.get(sw["sid"])
        now = m.level if m is not None else None
        if now is not None:
            # (the yield difference AL − SAT now, and the P&L since the rebalance: its fall, bp of the AL leg's DV01)
            sw["now"] = -sw["way"] * now
            if sw.get("level_formed") is not None:
                sw["so_far"] = -(sw["now"] - sw["level_formed"])
        if sg is not None:
            mo = sg.get("money") or {}
            sw.update({"line": sg.get("line") or sg.get("expression"), "exp_try": mo.get("total"), "target_try": mo.get("target"),
                       "stop_try": mo.get("stop"), "rr": sg.get("rr"), "gated": sg.get("gated") or "", "levels": sg.get("levels"),
                       "target_bp": (sg.get("dibssw") or {}).get("target_bp", sw.get("target_bp")),
                       "stop_bp": (sg.get("dibssw") or {}).get("stop_bp", sw.get("stop_bp"))})
        out.append(sw)
    tab["switches"] = out
    base["dibssw"] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["family"] == FAMILY]
    base["settings"] = fit["cfg"]
    keys = coverage_keys((fit.get("ctx").meta if fit.get("ctx") is not None else {}))
    base["coverage"] = [c for c in fit.get("coverage") or () if c.get("key") in keys]
    base["errors"] = {k: e for k, e in ((v.get("tables") or {}).get("errors") or {}).items() if k == FAMILY}
    return _clean(base)
