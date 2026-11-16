"""The universe of the systematic families: every instrument the desk trades, in its priority order, with what a
signal on it needs - and the groups and the order of the Sinyaller list.

**For the writers of the families on the universe** (Trend, Carry + momentum, Makine öğrenmesi: ``tto/quanttrend.py``,
``tto/quantsira.py``, ``tto/quantml.py`` - ``MODULES``).  A family is a function ``fn(ctx, reg, cfg) -> (monitors,
table)`` in its own module, registered with ``@quantuniv.family("trend")``: ``tto.quant`` imports the module when it
exists and runs it on every full fit after the other families, and in each refit of the backtest - nothing else to
edit (its label, kind and page are in ``FAMILIES``; ``tto.quant`` puts them into ``quantfam.FAMILIES``).  ``for inst
in reg`` walks the trade lines in the list's order (``reg.tradeable("TRY OIS")`` one group, ``reg.inputs()`` the
feature-only series - UST, DXY, Brent, CDS, EM FX, TLREF, the interpolated OIS tenors -, ``reg[key]`` any of them).
Its level: ``inst.days`` / ``inst.values`` (the closes before today), ``inst.now(live)`` (now; the fit's live values
without ``live``), ``inst.changes()`` (the daily moves in change units - bp, %, vol, puan -, a rolling series' roll
days left out), ``inst.vol()`` (their σ over the last 60), ``inst.carry_week()`` (carry + roll a week, change units)
and ``inst.carry_days()`` (FX: the carry's own history, % a year).  Every number is the *up* side's -
``inst.verbs[0]``, the position that gains when the level rises ("AL", "pay", "steepener", "vol al"; "SAT" for a
DİBS yield).  Size and money: ``inst.size_text(k)`` is k of the desk's unit ("1,4 mn EUR", "700 $ DV01", "14.000 $
vega"), ``inst.money(move, k)`` what a level move of ``move`` change units makes k units of the up side, in
``inst.ccy`` (USD for G10, TL for TRY rates, TRY for the USDTRY / EURTRY forwards and swap points).
``inst.monitor(sid, family, k=1.0, **kw)`` is the :class:`quantfam.Monitor` with the instrument's legs (DV01-weighted,
sized as today's packages are, for ``k`` units), P&L unit, FX pair and money set: give it the family's score (``zfn``
/ ``zvalues``), ``mode``, ``follows``, ``reward`` / ``risk`` / ``fcast`` / ``hold``, and ``make_signal`` writes its
card - the plain sentence, entry / target / stop in the instrument's price, the expected P&L in money (an FX card's
per 1 mn of the base) - and the list puts it in its group.  An FX level is a price (the spot, a forward): its carry is
not in it - put the holding's carry (``carry_week`` × weeks) into ``fcast``.

**The universe**, in the list's order (``GROUPS``; the plan of 16.11.2026):

1. **G10 spot**: EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF, NZDUSD - 1 mn of the base currency, P&L in USD, carry
   from the 3M forward points;
2. **G10 opsiyon**: the same seven, ATM 1M / 3M, 25D RR 1M / 3M, 25D BF 3M - 10.000 $ vega a vol point;
3. **TRY OIS**, the ≤ 2Y lines first: outrights, spreads (long − short, DV01 1:1), flies (the OIS sheet's "TÜM
   FLY'LAR", 50/50 DV01: the level body − ½ each wing, half the sheet's 2·body − wings quote), FRA 3×6 … 18×24 from
   each day's curve, the next three PPK periods (the meeting path's level after the 1st / 2nd / 3rd coming meeting,
   rolling on each meeting); then the long end - all 1.000 $ DV01, P&L in TL, carry + roll from the Carry & Roll
   engine;
4. **DİBS**: the DİBS RV list's fixed-coupon bonds - their nominal for 1.000 $ DV01, carry + roll from the curve fit;
5. **VİOP**: the listed contracts' implied TRY rate against spot (the exchange's: in the TRY group, not offshore);
6. **Offshore**: USDTRY / EURTRY forwards, swap points, the offshore curve - labelled "offshore limiti".

Their G10 series are a fixed set (``series_specs``) the history keeps whatever the desk's FX pair list: two years
once, then the new days, at its usual pace (``tto.quant.series_specs`` keeps a series of the list once).  The rest
is the history's: nothing here asks Bloomberg.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import math
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from . import fx as fxm
from . import quantcurve as qc
from . import quantfam as qf
from . import quantmath as qm
from . import quantopt as qopt
from . import quantpath as qp
from . import quantviop as qv

# ---------------------------------------------------------------------------------------------- the families on it
#: id -> (label, kind, page), as ``quantfam.FAMILIES`` (``tto.quant`` adds them there): "sys" a systematic line every
#: day - no regime or half-life gate of make_signal's (the family's own rules decide)
FAMILIES: Dict[str, Tuple[str, str, str]] = {
    "trend": ("Trend", "sys", "quant"),
    "sira": ("Carry + momentum", "carry", "quant"),
    "ml": ("Makine öğrenmesi", "model", "quant"),
}
#: the module of each family (``tto/<name>.py``), imported when it exists: it registers its function with ``family``
MODULES: Dict[str, str] = {"trend": "quanttrend", "sira": "quantsira", "ml": "quantml"}
#: id -> fn(ctx, reg, cfg) -> (monitors, table)
RUNNERS: Dict[str, Callable[..., Tuple[List[qf.Monitor], Any]]] = {}


def family(fid: str) -> Callable[[Callable], Callable]:
    """A family's function, registered (a decorator): ``@family("trend") def run(ctx, reg, cfg): ...``."""
    if fid not in FAMILIES:
        raise ValueError("bilinmeyen aile: %s" % fid)

    def deco(fn: Callable) -> Callable:
        RUNNERS[fid] = fn
        return fn

    return deco


def runners(errors: Optional[Dict[str, str]] = None) -> List[Tuple[str, Callable]]:
    """The registered families in ``FAMILIES``' order, their modules imported first (a module that is not there yet is
    no family; one that fails to import is that family's error)."""
    for fid, name in MODULES.items():
        if fid in RUNNERS:
            continue
        full = "%s.%s" % (__package__ or "tto", name)
        try:
            importlib.import_module(full)
        except ModuleNotFoundError as exc:
            if exc.name != full:
                if errors is not None:
                    errors[fid] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        except Exception as exc:  # noqa: BLE001 - a broken module is its family's error, not the fit's
            if errors is not None:
                errors[fid] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    return [(fid, RUNNERS[fid]) for fid in FAMILIES if fid in RUNNERS]


def run(ctx: qf.Ctx, reg: "Registry", mons: List[qf.Monitor], tables: Dict[str, Any], timing: Dict[str, float],
        pause: Optional[Callable[[], None]] = None) -> None:
    """``tto.quant``'s full fit: each family on the universe - its monitors join ``mons``, its table ``tables``, an
    exception is that family's error (as ``quantfam.run_all``'s steps)."""
    errors = tables.setdefault("errors", {})
    for fid, fn in runners(errors):
        t0 = time.perf_counter()
        try:
            m, t = fn(ctx, reg, ctx.cfg)
            mons.extend(m)
            tables[fid] = t
        except Exception as exc:  # noqa: BLE001 - one family failing must not take the others with it
            errors[fid] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            tables[fid] = {"ok": False, "why": errors[fid], "rows": []}
        timing[fid] = time.perf_counter() - t0
        if pause is not None:
            pause()


def monitors(ctx: qf.Ctx, pause: Optional[Callable[[], None]] = None) -> List[qf.Monitor]:
    """The families on the universe for one refit of the backtest: a registry of the context alone (no workbook part:
    no carry engine, no DİBS fit), their monitors."""
    out: List[qf.Monitor] = []
    regs = runners()
    if not regs:
        return out
    reg = Registry(ctx)
    for _, fn in regs:
        try:
            out.extend(fn(ctx, reg, ctx.cfg)[0])
        except Exception:  # noqa: BLE001 - a family that cannot run on a day has no trades that day
            pass
        if pause is not None:
            pause()
    return out


# ---------------------------------------------------------------------------------------------- groups and order
#: the list's groups, in their order (the buttons above it); "Diğer": the existing families' lines on what is none of
#: them (EM FX, global drivers, USD rates)
GROUPS = ("G10 spot", "G10 opsiyon", "TRY OIS", "DİBS", "VİOP", "Offshore", "Diğer")
SLUGS = {"G10 spot": "g10-spot", "G10 opsiyon": "g10-opsiyon", "TRY OIS": "try-ois", "DİBS": "dibs", "VİOP": "viop",
         "Offshore": "offshore", "Diğer": "diger"}
SHORT, LONG = "≤ 2Y", "uzun"
#: the order of the lines: TRY OIS's short end before its long end
PRIORITY = {("G10 spot", None): 1, ("G10 opsiyon", None): 2, ("TRY OIS", SHORT): 3, ("TRY OIS", LONG): 4, ("DİBS", None): 5,
            ("VİOP", None): 6, ("Offshore", None): 7, ("Diğer", None): 8}
#: what an Offshore line carries: the desk can do little offshore (its limits)
TAGS = {"Offshore": "offshore limiti"}
SHORT_MONTHS = 24.0


def priority(group: str, tier: Optional[str] = None) -> int:
    return PRIORITY.get((group, tier if group == "TRY OIS" else None), PRIORITY[("Diğer", None)])


def _months(key: str) -> Optional[float]:
    """A TRY tenor's months from its key (OIS:2Y, OFF:3M); a meeting-dated period (MPC:) is the short end."""
    if key.startswith("MPC:") or key == "TLREF":
        return 0.0
    if key.startswith(("OIS:", "OFF:")):
        return qf._TENOR_MONTHS.get(key.split(":", 1)[1].upper())
    return None


def _pair_of(key: str) -> Optional[str]:
    """The FX pair a key is of: FX:EURUSD, FXV:EURUSD, OPT:EURUSD:ATM:1M, FXP:USDTRY:3M, FWD:…, XR:…"""
    head, _, rest = key.partition(":")
    if head in ("FX", "FXV", "FXR", "OPT", "FXP", "FWD", "XR", "FXH", "FXL") and len(rest) >= 6:
        return rest[:6].upper()
    return None


def classify(sg: Dict[str, Any]) -> Dict[str, Any]:
    """A signal's place in the list: ``group``, ``tier`` (TRY OIS: "≤ 2Y" / "uzun"), ``priority``, ``tag`` - a
    signal of the universe's families from its instrument (``info["group"]``), the existing families' from their main
    leg: TRY OIS, DİBS, VİOP, Offshore as their asset; an FX pair's line a TRY pair's in Offshore (its forwards, swap
    points and options are offshore business), a G10 pair's in G10 spot / G10 opsiyon; the rest "Diğer"."""
    info = sg.get("info") or {}
    group, tier = info.get("group"), info.get("tier")
    if group not in GROUPS:
        legs = sg.get("legs") or []
        key = (legs[0].get("key") if legs else "") or ""
        asset = sg.get("asset") or ""
        pair = ((sg.get("px") or {}).get("pair") or (sg.get("fx") or {}).get("pair") or _pair_of(key) or "")
        if asset in ("TRY OIS", "DİBS", "VİOP", "Offshore"):
            group = asset
        elif key.startswith(("OIS:", "MPC:", "SLOPE:")) or key == "TLREF":
            group = "TRY OIS"
        elif key.startswith("DIBS:"):
            group = "DİBS"
        elif key.startswith(("VIOP", "VQ")):
            group = "VİOP"
        elif key.startswith("OFF:") or "TRY" in pair:
            group = "Offshore"
        elif pair in G10_PAIRS:
            group = "G10 opsiyon" if asset == "FX vol" or key.startswith(("FXV:", "FXR:", "OPT:")) else "G10 spot"
        else:
            group = "Diğer"
        if group == "TRY OIS":
            months = [m for m in (_months(l.get("key") or "") for l in legs) if m is not None]
            # (a hedged package is its main leg's; a spread / fly / FRA its longest leg's)
            ref = (months[0] if sg.get("packages") else max(months)) if months else None
            tier = SHORT if ref is not None and ref <= SHORT_MONTHS else LONG
    if group != "TRY OIS":
        tier = None
    sg.update({"group": group, "tier": tier, "priority": priority(group, tier), "tag": TAGS.get(group, "")})
    return sg


def order(live: List[Dict[str, Any]], gated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The Sinyaller list: the groups in their order (TRY OIS's short end first), within a group the confident lines
    by strength (the composite, as ``quantfam.rank`` has them), then the ones a gate holds ("düşük güven") by |z|."""
    for s in live + gated:
        classify(s)
    conf = sorted(live, key=lambda s: (s["priority"], -s["composite"], -s["agree"], -abs(s["z"])))
    low = sorted(gated, key=lambda s: (s["priority"], -abs(s["z"])))
    return sorted(conf + low, key=lambda s: (s["priority"], 1 if s["gated"] else 0))         # (stable: each part's order kept)


def group_counts(signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every group with its lines (``n``) and confident ones (``live``): the buttons above the list."""
    out = []
    for g in GROUPS:
        mine = [s for s in signals if s.get("group") == g]
        out.append({"id": g, "label": g, "slug": SLUGS[g], "n": len(mine), "live": sum(1 for s in mine if not s.get("gated")),
                    "tag": TAGS.get(g, "")})
    return out


# ---------------------------------------------------------------------------------------------- the G10 series
G10_PAIRS = ("EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD")
#: the quotes kept per G10 pair: (kind, tenor) of ``tto.fx`` - ATM 1M / 3M, 25D RR 1M / 3M, 25D BF 3M
G10_VOLS = (("ATM", "1M"), ("ATM", "3M"), ("RR25", "1M"), ("RR25", "3M"), ("BF25", "3M"))


def _fx_pair(code: str) -> fxm.Pair:
    return next((p for p in fxm.PAIRS if p.code == code), None) or fxm._pair(code, "G10", 3 if code.endswith("JPY") else 5)


def series_specs(source: str = fxm.DEFAULT_SOURCE) -> List[Dict[str, Any]]:
    """The G10 universe's series (``{key, label, ticker, kind, group, universe}``), as the quant package names its own -
    its spots, 3M forward points and ATM 3M / 25D RR 3M (``FX:``, ``FXP:``, ``FXV:``, ``FXR:``), the Opsiyon page's
    other quotes (``OPT:<pair>:<kind>:<tenor>``) - in the order of their first fill: the spots, the points (with the
    spots, every pair's carry), then the vols tenor by tenor.  ``tto.quant.series_specs`` keeps the ones its list has
    already (the desk's pairs, EURUSD's options) once."""
    out: List[Dict[str, Any]] = []
    for code in G10_PAIRS:
        out.append({"key": "FX:" + code, "label": code, "ticker": fxm.spot_ticker(_fx_pair(code)), "kind": "fx", "group": "G10", "universe": True})
    for code in G10_PAIRS:
        out.append({"key": "FXP:%s:3M" % code, "label": "%s 3M swap puanı" % code, "ticker": fxm.points_ticker(_fx_pair(code), "3M"),
                    "kind": "pts", "group": "G10", "universe": True})
    for kind, tenor in G10_VOLS:
        for code in G10_PAIRS:
            out.append({"key": qopt.key(code, kind, tenor), "label": qopt.label(code, kind, tenor), "ticker": fxm.vol_ticker(code, kind, tenor, source),
                        "kind": "vol", "group": "G10", "universe": True})
    return out


# ---------------------------------------------------------------------------------------------- TRY OIS, as the plan lists it
OUTRIGHTS = ("1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y", "10Y")
SPREADS = (("1M", "3M"), ("3M", "6M"), ("3M", "1Y"), ("6M", "9M"), ("6M", "1Y"), ("9M", "1Y"), ("1Y", "18M"), ("1Y", "2Y"),
           ("18M", "2Y"), ("6M", "2Y"), ("2Y", "3Y"), ("2Y", "5Y"), ("3Y", "5Y"), ("5Y", "10Y"))
FLIES = (("1M", "2M", "3M"), ("2M", "3M", "6M"), ("3M", "6M", "9M"), ("3M", "6M", "1Y"), ("6M", "9M", "1Y"), ("6M", "1Y", "18M"),
         ("6M", "1Y", "2Y"), ("1Y", "18M", "2Y"), ("1Y", "2Y", "3Y"), ("2Y", "3Y", "5Y"), ("2Y", "5Y", "10Y"))
#: forward-starting OIS on the desk's 3-month grid (months)
FRAS = ((3, 6), (6, 9), (9, 12), (12, 15), (15, 18), (18, 24))
PPK_PERIODS = 3
#: the TRY tenors that are inputs only (interpolated, or between the lines the desk trades): never a trade line
OIS_INPUTS = ("1W", "2W", "15M", "21M", "4Y", "6Y", "7Y", "8Y", "9Y")
#: the feature-only series: never a trade line
INPUTS = ("UST:2Y", "UST:10Y", "DXY", "BRENT", "CDS", "EMFX", "TLREF", "USD:3M", "FX:USDTRY")
#: the offshore forwards and swap points: USDTRY's term structure and EURTRY's 3M
OFFSHORE_FWD = (("USDTRY", "1M"), ("USDTRY", "3M"), ("USDTRY", "6M"), ("USDTRY", "1Y"), ("EURTRY", "3M"))

VOL_DAYS = 60                   # the closes a daily volatility is measured over
VEGA_USD = 10000.0              # an option line's size: $ vega a vol point
FX_NOTIONAL = qf.FX_NOTIONAL    # an FX line's size: 1 mn of the base currency
FLY_WING = 0.5                  # a fly's wings, each, in DV01 of its body (50/50)
QUARTERS = (3, 6, 9, 12, 15, 18, 21, 24)    # the quarters of the FRA grid's curve (15M and 21M: the interpolated inputs)
DIBS_MIN_DAYS = qc.MIN_DAYS     # a bond this close to its maturity is no line


def _tenor_tr(tenor: str) -> str:
    return qf._tenor_en(tenor)


def _num(v: Any) -> Optional[float]:
    return v if type(v) is float and math.isfinite(v) else (float(v) if type(v) is int else None)


def _amount(v: float) -> str:
    """An amount the desk's way, without a sign: "1,4 mn", "700 bin", "950"."""
    a = abs(v)
    if a >= 1e6 - 0.5:
        x = a / 1e6
        return "%s mn" % (qf._th(x, 0) if abs(x - round(x)) < 0.05 else qf._th(x, 1))
    if a >= 1e3:
        x = a / 1e3
        return "%s bin" % (qf._th(x, 0) if abs(x - round(x)) < 0.05 or x >= 100 else qf._th(x, 1))
    return qf._th(a, 0)


# ---------------------------------------------------------------------------------------------- an instrument
class Instrument(object):
    """One line of the universe: what it is, how the desk trades it, its level.  Subclasses say what differs."""

    tradeable = True
    kind = "rate"                 # how its level moves (quantfam.change): rate (%) in bp, bp, fx (a price) in %, vol, pts
    unit = "%"                    # the level's unit as shown
    digits = 2
    asset = "TRY OIS"             # quantfam.ASSETS: the list's asset filter
    ccy = "TL"                    # what its money is in
    pkg = "rate"                  # quantfam.PKG_VERBS: how its expression is said (None: by its legs)
    explicit = False              # its expression names every leg
    per_cu = 1.0                  # P&L units (bp of the package's DV01, %, vol, puan) a change unit of the level makes
    fx: Optional[str] = None      # the FX pair whose price the level is (its trade told in that price)
    inst_name: Optional[str] = None
    inst_days: Optional[float] = None

    def __init__(self, reg: "Registry", key: str, group: str, label: str, verbs: Tuple[str, str], tier: Optional[str] = None,
                 info: Optional[Dict[str, Any]] = None):
        self.reg = reg
        self.ctx = reg.ctx
        self.key = key
        self.group = group
        self.tier = tier
        self.priority = priority(group, tier)
        self.tag = TAGS.get(group, "")
        self.label = label
        self.verbs = verbs
        self.info: Dict[str, Any] = dict(info or {})
        self._pts: Optional[List[Tuple[str, float]]] = None
        self._rolls: set = set()

    def __repr__(self) -> str:
        return "<%s %s>" % (type(self).__name__, self.key)

    # ---- the level
    def _series(self) -> Dict[str, float]:
        return dict(self.ctx.series.get(self.key) or {})

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        return live.get(self.key)

    def pts(self) -> List[Tuple[str, float]]:
        """The closes before today, oldest first: ``[(ISO day, level)]``."""
        if self._pts is None:
            self._pts = sorted((d, v) for d, v in self._series().items() if d < self.ctx.today_iso and _num(v) is not None)
        return self._pts

    @property
    def days(self) -> List[str]:
        return [d for d, _ in self.pts()]

    @property
    def values(self) -> List[float]:
        return [v for _, v in self.pts()]

    def last(self) -> Optional[float]:
        p = self.pts()
        return p[-1][1] if p else None

    def now(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """The level now: from the live values (the fit's when none are given), else the last close."""
        try:
            v = self._now(self.reg.live if live is None else live)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError, KeyError):
            v = None
        return v if _num(v) is not None else self.last()

    def rolls(self) -> set:
        """The days a rolling series moved to its next contract / period (their move is no market move)."""
        self.pts()
        return self._rolls

    def changes(self, n: Optional[int] = None) -> List[float]:
        """The daily moves of the level in change units (bp, %, vol, puan), the roll days left out; the last ``n``."""
        p = self.pts()
        rolls = self.rolls()
        out = []
        for (_, a), (d, b) in zip(p, p[1:]):
            if d in rolls:
                continue
            c = qf.change(self.kind, a, b)
            if c is not None:
                out.append(c)
        return out[-n:] if n else out

    def vol(self, n: int = VOL_DAYS) -> Optional[float]:
        """The σ of the last ``n`` daily moves (change units); ``None`` with fewer than ten."""
        ch = self.changes(n)
        return qm.stdev(ch) if len(ch) >= 10 else None

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """Carry + roll a week of the up side, change units (``None``: not known)."""
        return None

    def carry_days(self) -> Dict[str, float]:
        """The carry's own history where there is one (FX: % a year of a long, from that day's forwards)."""
        return {}

    # ---- the trade
    def verb(self, side: int) -> str:
        return self.verbs[0] if side > 0 else self.verbs[1]

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        """The package of the up side, DV01-weighted (``quantfam``'s legs: ``{key, name, weight}``), for ``k`` of the
        desk's unit: sized where the families' scoring cannot size them (``quantfam.size_legs`` sizes a TRY OIS leg at
        the desk's 1.000 $ DV01)."""
        return [{"key": self.key, "name": self.label, "weight": 1.0}]

    def _ois_sized(self, legs: List[Dict[str, Any]], k: float, live: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        """TRY OIS legs as ``quantfam.size_legs`` sizes them, for ``k`` × the package DV01 (k = 1: left to it)."""
        if k == 1.0:
            return legs
        usd, tl = self.reg.dv01()
        for leg in legs:
            w = float(leg.get("weight", 1.0))
            ann = self.ctx.ois_annuity(leg["key"], live)
            leg.update({"dv01_usd": w * usd * k, "dv01": w * tl * k if tl else None,
                        "notional": abs(w) * tl * k / (ann * 1e-4) / 1e6 if tl and ann else None})
        return legs

    def pnl(self) -> Tuple[str, Optional[float]]:
        """``Monitor.pnl``: the P&L unit and what a move of the level (its own units) is in it."""
        if self.kind == "rate":
            return "bp", 100.0 * self.per_cu
        return "bp", self.per_cu

    def per_unit(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """Money (``ccy``) a P&L unit of the desk's unit makes - a rates line: TL a bp of its 1.000 $ DV01."""
        return self.reg.dv01()[1]

    def money(self, move: Optional[float], k: float = 1.0, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        """What a move of the level by ``move`` change units makes ``k`` of the desk's units of the up side, in
        ``ccy`` (the down side: its negative)."""
        per = self.per_unit(live)
        if move is None or per is None:
            return None
        return move * self.per_cu * per * k

    def size(self) -> Dict[str, Any]:
        """The desk's unit: ``{amount, unit, text}`` - 1.000 $ DV01 for a rates line."""
        usd = self.reg.dv01()[0]
        return {"amount": usd, "unit": "$ DV01", "text": "%s $ DV01" % qf._th(usd, 0)}

    def size_text(self, k: float = 1.0) -> str:
        """``k`` of the desk's unit as the desk says it: "1,4 mn EUR", "700 $ DV01", "14.000 $ vega"."""
        s = self.size()
        return "%s %s" % (qf._th(s["amount"] * k, 0), s["unit"])

    def line(self, side: int, k: float = 1.0) -> str:
        """The trade in one line: "receive 2Y OIS · 700 $ DV01", "SAT USDTRY 1A forward · 1 mn USD · offshore limiti"."""
        return " · ".join(x for x in ("%s %s" % (self.verb(side), self.label), self.size_text(k), self.tag) if x)

    def cash(self) -> Optional[Tuple[str, float]]:
        """``Monitor.cash``: (currency, money a P&L unit) for a line whose card has no money of its own (vol, points)."""
        return None

    def monitor(self, sid: str, family: str, days: Optional[List[str]] = None, values: Optional[List[float]] = None,
                k: float = 1.0, **kw: Any) -> qf.Monitor:
        """The :class:`quantfam.Monitor` of a signal on this instrument: its legs, P&L unit, carry, FX pair, money and
        place in the list set - the family gives its score and decision (``zfn`` / ``zvalues``, ``mode``,
        ``follows``, ``reward``, ``risk``, ``fcast``, ``hold`` …; anything given here wins).  ``k``: the line's size
        in the desk's unit (Trend's risk-equal "700 $ DV01"): its legs and its card's money are of that size - but an
        FX card's money, which stays per 1 mn of the base currency (``money(move, k)`` has it at k)."""
        if days is None or values is None:
            days, values = self.days, self.values
        lv = list(values)
        win = self.ctx.window()
        rolls = self.rolls()
        diffs = [b - a for a, b, d in zip(lv, lv[1:], days[1:]) if d not in rolls][-win:]
        k = float(k or 1.0)
        legs = self.legs(None, k)
        info = {"universe": self.key, "group": self.group, "tier": self.tier, "priority": self.priority, "tag": self.tag,
                "size": self.size_text(k), "k": k, "verbs": list(self.verbs),
                "inputs": [l["key"] for l in legs] + list(self.info.get("inputs") or ())}
        info.update(kw.pop("info", None) or {})
        cw = self.carry_week()
        opts: Dict[str, Any] = {"pnl": self.pnl(), "dsd": qm.stdev(diffs) if len(diffs) >= 2 else None, "pkg": self.pkg,
                                "explicit": self.explicit, "info": info}
        if self.fx:
            opts.update({"fx": self.fx, "price": "level", "inst": self.inst_name, "inst_days": self.inst_days})
        elif cw is not None:
            opts["carry_up"] = cw * self.per_cu
        cash = self.cash()
        if cash is not None:
            opts["cash"] = (cash[0], cash[1] * k)
        opts.update(kw)
        return qf.Monitor(sid, family, self.asset, self.label, self.unit, self.digits, list(days), lv, legs, self.now, **opts)

    def row(self, live: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """What the universe's table says of it."""
        p = self.pts()
        cw = self.carry_week(live)
        return {"key": self.key, "group": self.group, "tier": self.tier, "priority": self.priority, "tag": self.tag, "label": self.label,
                "kind": self.kind, "unit": self.unit, "digits": self.digits, "verbs": list(self.verbs), "size": self.size_text(),
                "ccy": self.ccy, "n": len(p), "first": p[0][0] if p else None, "last": p[-1][0] if p else None, "level": self.now(live),
                "vol": self.vol(), "carry_week": cw, "money_1": self.money(1.0, 1.0, live), "tradeable": self.tradeable,
                "legs": [{"key": l["key"], "name": l["name"], "weight": l.get("weight", 1.0)} for l in self.legs(live)],
                "rolls": len(self.rolls())}


# ---------------------------------------------------------------------------------------------- G10
class FxSpot(Instrument):
    """A G10 pair's spot: 1 mn of the base currency, P&L in USD, carry from its 3M forward points."""

    kind, unit, asset, ccy, pkg = "fx", "", "FX", "USD", "fx"

    def __init__(self, reg: "Registry", pair: str, group: str = "G10 spot", **kw: Any):
        super().__init__(reg, "FX:" + pair, group, "%s spot" % pair, ("AL", "SAT"), **kw)
        self.pair = pair
        self.fx = pair
        self.inst_name = "%s spot" % pair
        last = reg.ctx.last(self.key)
        self.digits = qf.fx_digits(last) if last else 5

    def pnl(self) -> Tuple[str, Optional[float]]:
        return qf.pnl_scale("fx", self.now())

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        c = self.ctx.fx_carry(self.pair, self.reg.live if live is None else live)
        return c * 7.0 / 365.0 if c is not None else None

    def carry_days(self) -> Dict[str, float]:
        return self.ctx.fx_carry_days(self.pair)

    def usd_per_quote(self, level: Optional[float]) -> Optional[float]:
        quote = self.pair[3:]
        if quote == "USD":
            return 1.0
        if self.pair[:3] == "USD" and level:
            return 1.0 / level
        return None

    def per_unit(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        return None

    def money(self, move: Optional[float], k: float = 1.0, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        p = self.now(live)
        conv = self.usd_per_quote(p)
        if move is None or not p or conv is None:
            return None
        return FX_NOTIONAL * k * p * (math.exp(move / 100.0) - 1.0) * conv

    def size(self) -> Dict[str, Any]:
        return {"amount": FX_NOTIONAL, "unit": self.pair[:3], "text": "1 mn %s" % self.pair[:3]}

    def size_text(self, k: float = 1.0) -> str:
        return "%s %s" % (_amount(FX_NOTIONAL * k), self.pair[:3])

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        return [{"key": "FX:" + self.pair, "name": self.inst_name, "weight": 1.0}]


class FxVol(Instrument):
    """A G10 option quote (ATM, 25D RR, 25D BF): 10.000 $ vega a vol point - a straddle ("vol al / sat"), a risk
    reversal ("RR al / sat"), a butterfly ("BF al / sat")."""

    kind, unit, asset, ccy, pkg = "vol", "vol", "FX vol", "USD", "vol"
    VERBS = {"ATM": ("vol al", "vol sat"), "RR25": ("RR al", "RR sat"), "BF25": ("BF al", "BF sat")}

    def __init__(self, reg: "Registry", pair: str, vkind: str, tenor: str, **kw: Any):
        label = ("%s ATM %s vol" % (pair, _tenor_tr(tenor)) if vkind == "ATM" else "%s %s %s" % (pair, fxm.KIND_LABEL[vkind], _tenor_tr(tenor)))
        super().__init__(reg, qopt.key(pair, vkind, tenor), "G10 opsiyon", label, self.VERBS[vkind], **kw)
        self.pair, self.vkind, self.tenor = pair, vkind, tenor

    def pnl(self) -> Tuple[str, Optional[float]]:
        return "vol", 1.0

    def per_unit(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        return VEGA_USD

    def cash(self) -> Optional[Tuple[str, float]]:
        return "USD", VEGA_USD

    def size(self) -> Dict[str, Any]:
        return {"amount": VEGA_USD, "unit": "$ vega", "text": "%s $ vega" % qf._th(VEGA_USD, 0)}


# ---------------------------------------------------------------------------------------------- TRY OIS
class OisPackage(Instrument):
    """An outright, a spread or a fly of TRY OIS: the level ``Σ weight × rate`` (an outright's rate %, a spread's and a
    fly's bp), the trade its DV01 legs (1.000 $ on the main leg; a fly's body, its wings ½ each).  A fly's level is its
    50/50 package's - body − ½ each wing, as the PCA / RV page's classic flies -: half the OIS sheet's 2·body − wings
    quote, a bp of it a bp of the package's DV01."""

    def __init__(self, reg: "Registry", key: str, label: str, verbs: Tuple[str, str], quote: Dict[str, float],
                 dv01: Dict[str, float], kind: str, pkg: str, **kw: Any):
        super().__init__(reg, key, "TRY OIS", label, verbs, **kw)
        self.quote, self.dv01w = quote, dv01
        self.kind = kind
        self.unit = "%" if kind == "rate" else "bp"
        self.digits = 2 if kind == "rate" else 1
        self.pkg = pkg
        if kind == "bp":
            # (the quote's bp in the package's: a spread's 1, a fly's ½)
            self.per_cu = sum(abs(w) for w in dv01.values()) / sum(abs(w) for w in quote.values())

    def _value(self, rates: Dict[str, Optional[float]]) -> Optional[float]:
        if any(rates.get(k) is None for k in self.quote):
            return None
        v = sum(w * rates[k] for k, w in self.quote.items())
        return v * 100.0 if self.kind == "bp" else v

    def _series(self) -> Dict[str, float]:
        if len(self.quote) == 1:
            return dict(self.ctx.series.get(self.key) or {})
        sets = [self.ctx.series.get(k) or {} for k in self.quote]
        days = set(sets[0]).intersection(*sets[1:]) if sets else set()
        return {d: self._value({k: s[d] for k, s in zip(self.quote, sets)}) for d in days}

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        return self._value({k: self.ctx.cur(k, live) for k in self.quote})

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        total = 0.0
        for k, w in self.dv01w.items():
            c = self.ctx.carry_week(k)
            if c is None:
                return None
            total += w * c
        return total / self.per_cu

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        return self._ois_sized([{"key": key, "name": qf._ois_name(self.ctx, key), "weight": w} for key, w in self.dv01w.items()], k, live)


class Fra(Instrument):
    """A forward-starting OIS of the desk's 3-month grid (m1 × m2 months): each day's curve - the quotes bootstrapped in
    the desk's convention, as the FRA / PPK family reads them -, receive / pay as its two OIS legs, DV01-weighted by
    their annuities (the forward's DV01 1.000 $)."""

    def __init__(self, reg: "Registry", m1: int, m2: int, near: str, far: str, **kw: Any):
        super().__init__(reg, "FRA:%dx%d" % (m1, m2), "TRY OIS", "%d×%d FRA" % (m1, m2), ("pay", "receive"), tier=SHORT, **kw)
        self.m1, self.m2, self.near, self.far = m1, m2, near, far

    def _series(self) -> Dict[str, float]:
        return dict(self.reg.fra_history().get(self.key) or {})

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        return self.reg.fra_now(live).get(self.key)

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        a_far, a_near = self.ctx.ois_annuity(self.far, live), self.ctx.ois_annuity(self.near, live)
        span = (a_far - a_near) if a_far and a_near else 0.0
        w_far, w_near = (a_far / span, -a_near / span) if span > 0 else (1.0, -1.0)
        return self._ois_sized([{"key": self.far, "name": qf._ois_name(self.ctx, self.far), "weight": w_far},
                                {"key": self.near, "name": qf._ois_name(self.ctx, self.near), "weight": w_near}], k, live)

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        total = 0.0
        for leg in self.legs(live):
            c = self.ctx.carry_week(leg["key"])
            if c is None:
                return None
            total += leg["weight"] * c
        return total


class PpkPeriod(Instrument):
    """The k-th coming PPK period: the meeting path's TLREF level after the k-th meeting still ahead (each day's path
    the history computed - the PPK Fiyatlama Geçmişi -, its meetings after the day's spot), a meeting-dated OIS: it
    rolls to the next period on each meeting day; carry 0 (forward-starting, fixed dates)."""

    def __init__(self, reg: "Registry", k: int, **kw: Any):
        super().__init__(reg, "PPK:%d" % k, "TRY OIS", "PPK %d. dönem" % k, ("pay", "receive"), tier=SHORT, **kw)
        self.k = k
        cur = self.meeting()
        if cur is not None:
            self.label = "PPK %d. dönem (%s)" % (k, "%s–%s" % (qp._tr(cur[0]), qp._tr(cur[1])) if cur[1] else qp._tr(cur[0]) + " sonrası")

    def _rows(self) -> List[Tuple[str, str, float, Optional[str]]]:
        """``(day, meeting, level %, next meeting)`` of every day's path that has a k-th meeting ahead."""
        out = []
        for day, p in sorted(self.reg.paths().items()):
            ms = p["meetings"]
            if len(ms) >= self.k:
                m, lv = ms[self.k - 1]
                out.append((day, m, lv, ms[self.k][0] if len(ms) > self.k else None))
        return out

    def _series(self) -> Dict[str, float]:
        out, prev = {}, None
        self._rolls = set()
        for day, m, lv, _ in self._rows():
            if day >= self.ctx.today_iso:
                continue
            if prev is not None and m != prev:
                self._rolls.add(day)                     # (the day after a meeting: the next period's level)
            out[day] = lv
            prev = m
        return out

    def _row(self, today: bool) -> Optional[Tuple[str, str, float, Optional[str]]]:
        """Today's path's row (``today``), else the last close's."""
        rows = [r for r in self._rows() if (r[0] == self.ctx.today_iso if today else r[0] < self.ctx.today_iso)]
        return rows[-1] if rows else None

    def meeting(self) -> Optional[Tuple[str, Optional[str]]]:
        """The period now: (its meeting, the next one) - today's path's, else the last close's."""
        r = self._row(True) or self._row(False)
        return (r[1], r[3]) if r else None

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        r = self._row(True)
        return r[2] if r else None

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        return 0.0

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        mt = self.meeting()
        if mt is None:
            return [{"key": "MPC:", "name": self.label, "weight": 1.0}]
        m, nxt = mt
        usd, tl = self.reg.dv01()
        leg = {"key": "MPC:" + m, "name": qp._period("try", m, nxt), "weight": 1.0, "dv01_usd": usd * k, "dv01": tl * k if tl else None}
        lv = self.now(live)
        if nxt and tl and lv is not None:
            t = max(1, (_dt.date.fromisoformat(nxt) - _dt.date.fromisoformat(m)).days) / 365.0
            leg["notional"] = tl * k / (t / (1.0 + lv / 100.0 * t) * 1e-4) / 1e6
        return [leg]


# ---------------------------------------------------------------------------------------------- DİBS
class Dibs(Instrument):
    """A fixed-coupon DİBS of the DİBS RV list: its yield (the history's convention), "kâğıdı al / sat" - SAT gains
    when the yield rises -, its nominal for 1.000 $ DV01 (DV01 as DİBS RV!AI), carry + roll from the curve fit."""

    asset, pkg = "DİBS", "bond"

    def __init__(self, reg: "Registry", isin: str, bond: qc.Bond, row: Optional[Dict[str, Any]], conv: str, **kw: Any):
        super().__init__(reg, "DIBS:" + isin, "DİBS", "DİBS %s" % qc._bond_label(bond), ("SAT", "AL"), **kw)
        self.isin, self.bond, self.rv_row, self.conv = isin, bond, row, conv            # (rv_row: its DİBS RV row)
        self.info["inputs"] = ["DIBSS:" + isin, "DIBSC:" + isin]
        self.info["maturity"] = bond.maturity.isoformat()
        self._dv = self._dv01s()
        own, desk = self._dv
        if own and desk:
            self.per_cu = own / desk

    def _dv01s(self) -> Tuple[Optional[float], Optional[float]]:
        """The bond's DV01 a 1 mn nominal (TL a bp): in its series' convention and as the desk has it (DİBS RV!AI)."""
        y = self.now()
        if y is None:
            return None, None
        value = qc._value_date(self.ctx.today, self.rv_row)
        try:
            p, dp = self.bond.price(y / 100.0, value, self.conv)
            return (-dp if dp < 0 else None), qc.desk_dv01(self.bond, value, p, y / 100.0)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None, None

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        return live.get(("DIBSC:" if self.conv == "compound" else "DIBSS:") + self.isin)

    def nominal(self, k: float = 1.0) -> Optional[float]:
        """mn TRY of nominal for ``k`` × 1.000 $ DV01."""
        tl = self.reg.dv01()[1]
        desk = self._dv[1]
        return k * tl / desk if tl and desk else None

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        c = (self.reg.dibs_carry().get(self.isin) or {}).get("total_1w")
        return -c if c is not None else None

    def size_text(self, k: float = 1.0) -> str:
        nom = self.nominal(k)
        base = super().size_text(k)
        return base + (" · %s mn TL nominal" % qf._th(nom, 1) if nom is not None else "")

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        usd, tl = self.reg.dv01()
        return [{"key": self.key, "name": self.label[5:], "weight": 1.0, "dv01_usd": usd * k, "dv01": tl * k if tl else None,
                 "notional": self.nominal(k)}]


# ---------------------------------------------------------------------------------------------- VİOP
class Viop(Instrument):
    """A listed VİOP contract's implied TRY rate against spot (the VİOP family's package: the future against spot, the
    rate alone): AL - buy the future, sell spot - gains when the implied rate rises; its history the constant
    maturities at the contract's days to expiry (expired contracts in them), else its own days; 1.000 $ DV01."""

    asset, pkg, explicit = "VİOP", None, True

    def __init__(self, reg: "Registry", contract: Any, **kw: Any):
        super().__init__(reg, "VIOP:" + contract.ticker, "VİOP", "VİOP %s" % contract.name, ("AL", "SAT"), **kw)
        self.c = contract
        self.ticker = contract.ticker
        hol = set(self.ctx.holidays or ())
        g_live = self.ctx.live.get("VQG:" + contract.ticker)
        self.g = float(g_live) if g_live else float(qv.days_to(contract.expiry, self.ctx.today_iso, hol))
        self.info.update({"inputs": ["VQM:" + contract.ticker, "VIOPF:" + contract.ticker], "contract": contract.ticker,
                          "expiry": contract.expiry.isoformat(), "g": self.g})

    def _series(self) -> Dict[str, float]:
        hist = self.reg.viop_history()
        cm = hist.get("cm") or {}
        out = qv.at_maturity(cm, self.g, "implied") if self.g > 0 else {}
        if len(out) < max(60, self.ctx.min_obs() // 2):
            own = {r["day"]: r["implied"] for r in (hist.get("rates") or {}).get(self.ticker) or ()}
            if len(own) > len(out):
                out = own
        return out

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        return live.get("VQM:" + self.ticker)

    def _size(self) -> Dict[str, Optional[float]]:
        live = self.reg.live
        spot = live.get("VQS:" + self.ticker) or self.ctx.cur("FX:USDTRY", live)
        usd = live.get("VQU:" + self.ticker)
        if usd is None:
            usd = qv.usd_at(self.g, *[self.ctx.cur(k, live) for k, _, _, _ in qv.USD_KEYS])
        return qv._size(self.reg.dv01()[0], spot, usd, self.g)

    def size_text(self, k: float = 1.0) -> str:
        n = self._size().get("contracts")
        return super().size_text(k) + (" · %s kontrat" % qf._th(n * k, 0) if n else "")

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        usd, tl = self.reg.dv01()
        size = self._size()
        nom = size["try_mn"] * k if size.get("try_mn") else None
        n = " (%s kontrat)" % qf._th(size["contracts"] * k, 0) if size.get("contracts") else ""
        return [{"key": "VQM:" + self.ticker, "name": "VİOP %s%s" % (self.c.name, n), "weight": 1.0, "dv01_usd": usd * k,
                 "dv01": tl * k if tl else None, "notional": nom},
                {"key": qv.SPOT_KEY, "name": "USDTRY spot", "weight": -1.0, "dv01_usd": 0.0, "dv01": 0.0, "notional": nom}]


# ---------------------------------------------------------------------------------------------- Offshore
class FxForward(FxSpot):
    """An offshore forward (USDTRY 1M … 1Y, EURTRY 3M), as the desk trades it: 1 mn of the base currency at the
    forward's own price, P&L in TRY; carry: its points rolling down towards spot (a long loses them)."""

    asset, ccy = "Offshore", "TRY"

    def __init__(self, reg: "Registry", pair: str, tenor: str, **kw: Any):
        Instrument.__init__(self, reg, "FWD:%s:%s" % (pair, tenor), "Offshore", "%s %s forward" % (pair, _tenor_tr(tenor)), ("AL", "SAT"), **kw)
        self.pair, self.tenor = pair, tenor
        self.fx = pair
        self.inst_name = self.label
        self.inst_days = qf._tenor_days(tenor)
        self.digits = 4

    def _now(self, live: Dict[str, float]) -> Optional[float]:
        if self.key in live:
            return live[self.key]
        s, q = live.get("FX:" + self.pair), live.get("FXP:%s:%s" % (self.pair, self.tenor))
        if s is None and q is None:
            return None
        return self.ctx.forward(self.pair, s if s is not None else self.ctx.last("FX:" + self.pair),
                                q if q is not None else self.ctx.last("FXP:%s:%s" % (self.pair, self.tenor)))

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        live = self.reg.live if live is None else live
        f, s = self.now(live), self.ctx.cur("FX:" + self.pair, live)
        if not f or not s or f <= 0 or s <= 0:
            return None
        return -(math.log(f) - math.log(s)) * 100.0 * 7.0 / self.inst_days

    def carry_days(self) -> Dict[str, float]:
        return {}

    def usd_per_quote(self, level: Optional[float]) -> Optional[float]:
        return 1.0                                           # (TRY: the money is in the quote currency itself)

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        return [{"key": "FX:" + self.pair, "name": self.label, "weight": 1.0}]


class SwapPoints(Instrument):
    """An offshore swap: USDTRY's (EURTRY's) forward points - "pay" (sell / buy the base: pay the points) gains when they
    rise; 1 mn of the base currency, a point is 10^-scale of the quote; carry: the points of a fixed date rolling down."""

    kind, unit, digits, asset, ccy, pkg = "pts", "puan", 0, "Offshore", "TRY", None

    def __init__(self, reg: "Registry", pair: str, tenor: str, **kw: Any):
        super().__init__(reg, "FXP:%s:%s" % (pair, tenor), "Offshore", "%s %s swap puanı" % (pair, _tenor_tr(tenor)), ("pay", "receive"), **kw)
        self.pair, self.tenor = pair, tenor
        self.days_t = qf._tenor_days(tenor)

    def scale(self) -> int:
        s = self.ctx.fwd_scale.get(self.pair)
        return s if s is not None else (2 if self.pair.endswith("JPY") else 4)

    def pnl(self) -> Tuple[str, Optional[float]]:
        return "puan", 1.0

    def per_unit(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        return FX_NOTIONAL * 10.0 ** (-self.scale())

    def cash(self) -> Optional[Tuple[str, float]]:
        return self.ccy, FX_NOTIONAL * 10.0 ** (-self.scale())

    def carry_week(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        p = self.now(live)
        return -p * 7.0 / self.days_t if p is not None else None

    def size(self) -> Dict[str, Any]:
        return {"amount": FX_NOTIONAL, "unit": self.pair[:3], "text": "1 mn %s" % self.pair[:3]}

    def size_text(self, k: float = 1.0) -> str:
        return "%s %s" % (_amount(FX_NOTIONAL * k), self.pair[:3])


class OffRate(Instrument):
    """An offshore TRY rate (the Forward sheet's implied yields): "pay / receive", 1.000 $ DV01 - its nominal a single
    payment's (an FX swap's) -, P&L in TL."""

    asset = "Offshore"

    def __init__(self, reg: "Registry", key: str, months: float, **kw: Any):
        super().__init__(reg, key, "Offshore", "Offshore %s" % key.split(":", 1)[1], ("pay", "receive"), **kw)
        self.months = months

    def legs(self, live: Optional[Dict[str, float]] = None, k: float = 1.0) -> List[Dict[str, Any]]:
        usd, tl = self.reg.dv01()
        r = self.now(live)
        t = self.months / 12.0
        leg = {"key": self.key, "name": self.label, "weight": 1.0, "dv01_usd": usd * k, "dv01": tl * k if tl else None}
        if tl and r is not None and t > 0:
            leg["notional"] = tl * k / (t / (1.0 + r / 100.0 * t) * 1e-4) / 1e6
        return [leg]


# ---------------------------------------------------------------------------------------------- inputs
class Input(Instrument):
    """A series the families read and never trade: UST, DXY, Brent, CDS, EM FX, TLREF, the interpolated OIS tenors."""

    tradeable = False

    def __init__(self, reg: "Registry", key: str, **kw: Any):
        meta = reg.ctx.meta.get(key) or {}
        super().__init__(reg, key, "Girdi", meta.get("label") or key, ("", ""), **kw)
        self.kind = meta.get("kind") or "rate"
        self.unit = qf.level_unit(self.kind)
        self.asset = "Global"

    def per_unit(self, live: Optional[Dict[str, float]] = None) -> Optional[float]:
        return None


# ---------------------------------------------------------------------------------------------- the registry
class Registry(object):
    """The universe on one context (a full fit's, or a backtest's refit): the instruments in the list's order and
    the inputs.  Cheap to build; each series is made the first time it is read and kept."""

    def __init__(self, ctx: qf.Ctx, tables: Optional[Dict[str, Any]] = None, eng: Optional[Dict[str, Any]] = None):
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.tables = tables or {}
        self.eng = eng or {}
        self.live = ctx.derive_live(ctx.live)
        self._memo: Dict[str, Any] = {}
        self.missing: Dict[str, str] = {}
        self.items: List[Instrument] = []
        self.extra: List[Instrument] = []
        self._build()
        self.by_key = {i.key: i for i in self.items + self.extra}

    # ---- reading
    def __iter__(self) -> Iterator[Instrument]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, key: str) -> Instrument:
        return self.by_key[key]

    def __contains__(self, key: str) -> bool:
        return key in self.by_key

    def get(self, key: str, default: Any = None) -> Any:
        return self.by_key.get(key, default)

    def tradeable(self, group: Optional[str] = None) -> List[Instrument]:
        """The trade lines in the list's order (of one group)."""
        return [i for i in self.items if group is None or i.group == group]

    def inputs(self) -> List[Instrument]:
        """The feature-only series."""
        return list(self.extra)

    def dv01(self) -> Tuple[float, Optional[float]]:
        """A rates line's size: USD and TL a bp (the setting's 1.000 $, at the fit's USDTRY)."""
        hit = self._memo.get("dv01")
        if hit is None:
            hit = self._memo["dv01"] = self.ctx.dv01_size()
        return hit

    def table(self, live: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """The universe as a table: every line and input with its level, σ, carry, size and money of a unit move."""
        live = self.live if live is None else live
        return {"rows": [i.row(live) for i in self.items], "inputs": [i.row(live) for i in self.extra], "missing": dict(self.missing),
                "groups": [{"id": g, "n": sum(1 for i in self.items if i.group == g)} for g in GROUPS[:-1]]}

    # ---- what several instruments share
    def ois_key(self, label: str) -> Optional[str]:
        """The history's key of a TRY OIS tenor ("2Y" → "OIS:2Y"), when it keeps one."""
        k = "OIS:" + label.upper()
        return k if (self.ctx.meta.get(k) or {}).get("months") is not None else None

    def paths(self) -> Dict[str, Dict[str, Any]]:
        """Every day's TRY meeting path the history computed (``quantpath.try_paths``: its meetings after the day's spot)."""
        hit = self._memo.get("paths")
        if hit is None:
            hit = self._memo["paths"] = qp.try_paths(self.ctx.mpc or {})
        return hit

    def _fra_curve(self, day: _dt.date, quotes: Dict[int, float]) -> Dict[str, float]:
        """One day's FRA rates (%) from its quotes (months -> %), in the desk's convention (``quantfam.curve_dfs``: ≤ 3M
        one payment, quarterly coupons beyond, the spot the next business day).  With every quarter quoted the
        bootstrap is exact in one pass - each quarter's DF from the ones before it, what curve_dfs converges to -;
        a missing quarter, curve_dfs itself."""
        hol = self.ctx.holidays
        spot = qf.business_on_or_after(day + _dt.timedelta(days=1), hol)
        ends = {m: qf.tenor_end(spot, m, hol) for m in QUARTERS}
        df: Dict[int, Optional[float]] = {}
        if all(m in quotes for m in QUARTERS):
            ann, prev = 0.0, spot
            for m in QUARTERS:
                tau = (ends[m] - prev).days / 365.0
                r = quotes[m] / 100.0
                df[m] = (1.0 - r * ann) / (1.0 + r * tau)
                ann += tau * df[m]
                prev = ends[m]
        else:
            dfs = qf.curve_dfs(spot, quotes, hol)
            df = {m: qf.curve_df(spot, [], ends[m], dfs) for m in QUARTERS}
        out: Dict[str, float] = {}
        for m1, m2 in FRAS:
            ca, cb = df.get(m1), df.get(m2)
            a, b = ends[m1], ends[m2]
            if ca and cb and b > a:
                out["FRA:%dx%d" % (m1, m2)] = (ca / cb - 1.0) * 365.0 / (b - a).days * 100.0
        return out

    def _fra_keys(self) -> Dict[int, str]:
        return {int(m["months"]): k for k, m in self.ctx.meta.items()
                if k.startswith("OIS:") and m.get("months") and m["months"] >= 1 and float(m["months"]).is_integer() and m["months"] <= FRAS[-1][1]}

    def fra_history(self) -> Dict[str, Dict[str, float]]:
        """Each FRA's rate day by day: the day's quotes of every tenor up to 2Y (15M and 21M among them) bootstrapped."""
        hit = self._memo.get("fra")
        if hit is not None:
            return hit
        keys = self._fra_keys()
        out: Dict[str, Dict[str, float]] = {}
        far = keys.get(FRAS[-1][1])
        if far:
            for d in sorted(self.ctx.series.get(far) or {}):
                quotes = {m: self.ctx.series[k][d] for m, k in keys.items() if d in (self.ctx.series.get(k) or {})}
                if len(quotes) < 4:
                    continue
                for name, v in self._fra_curve(_dt.date.fromisoformat(d), quotes).items():
                    out.setdefault(name, {})[d] = v
        self._memo["fra"] = out
        return out

    def fra_now(self, live: Dict[str, float]) -> Dict[str, float]:
        """Today's FRA rates from the quotes now (live where there are) - one bootstrap for all six, kept per values."""
        keys = self._fra_keys()
        quotes = {m: self.ctx.cur(k, live) for m, k in keys.items()}
        quotes = {m: v for m, v in quotes.items() if v is not None}
        sig = tuple(sorted(quotes.items()))
        hit = self._memo.get("fra_now")
        if hit is not None and hit[0] == sig:
            return hit[1]
        val = self._fra_curve(self.ctx.today, quotes) if len(quotes) >= 4 else {}
        self._memo["fra_now"] = (sig, val)
        return val

    def dibs_carry(self) -> Dict[str, Dict[str, Any]]:
        """Each bond's carry + roll (its yield convention's bp) from the DİBS curve fit, when the fit ran (not in a
        backtest's refit)."""
        hit = self._memo.get("dibs_carry")
        if hit is None:
            fn = (self.tables.get("dibsfv") or {}).get("carry") if isinstance(self.tables.get("dibsfv"), dict) else None
            try:
                hit = fn(self.live) if callable(fn) else {}
            except Exception:  # noqa: BLE001 - no carry is a line without carry
                hit = {}
            self._memo["dibs_carry"] = hit
        return hit

    def viop_history(self) -> Dict[str, Any]:
        """Every VİOP contract's implied rate and the constant maturities (the VİOP family's, else made here)."""
        hit = self._memo.get("viop")
        if hit is None:
            tab = self.tables.get("viop")
            fn = tab.get("_history") if isinstance(tab, dict) else None
            try:
                hit = fn() if callable(fn) else qv.implied_history(self.ctx, self.eng)
            except Exception:  # noqa: BLE001 - no history is a line without history
                hit = {}
            self._memo["viop"] = hit
        return hit

    # ---- the lines
    def _add(self, inst: Instrument) -> None:
        self.items.append(inst)

    def _build(self) -> None:
        ctx = self.ctx
        meta = ctx.meta
        # 1-2. G10 spot and options
        for pair in G10_PAIRS:
            if "FX:" + pair in meta:
                self._add(FxSpot(self, pair))
            else:
                self.missing["FX:" + pair] = "seri yok"
        for pair in G10_PAIRS:
            for vkind, tenor in G10_VOLS:
                k = qopt.key(pair, vkind, tenor)
                if k in meta:
                    self._add(FxVol(self, pair, vkind, tenor))
                else:
                    self.missing[k] = "seri yok"
        # 3. TRY OIS: the short end, then the long end
        tiers: Dict[str, List[Instrument]] = {SHORT: [], LONG: []}

        def months(label: str) -> float:
            return qf._TENOR_MONTHS.get(label, 999.0)

        def tier(labels: Sequence[str]) -> str:
            return SHORT if max(months(t) for t in labels) <= SHORT_MONTHS else LONG

        for t in OUTRIGHTS:
            k = self.ois_key(t)
            if k is None:
                self.missing["OIS:" + t] = "vade yok"
                continue
            tiers[tier([t])].append(OisPackage(self, k, "%s OIS" % t, ("pay", "receive"), {k: 1.0}, {k: 1.0}, "rate", "rate", tier=tier([t])))
        for short, long_ in SPREADS:
            ks, kl = self.ois_key(short), self.ois_key(long_)
            key = "OISS:%s/%s" % (short, long_)
            if ks is None or kl is None:
                self.missing[key] = "vade yok"
                continue
            tiers[tier([short, long_])].append(OisPackage(self, key, "%s/%s spread" % (short, long_), ("steepener", "flattener"),
                                                          {kl: 1.0, ks: -1.0}, {kl: 1.0, ks: -1.0}, "bp", "slope", tier=tier([short, long_])))
        for w1, b, w2 in FLIES:
            k1, kb, k2 = self.ois_key(w1), self.ois_key(b), self.ois_key(w2)
            key = "OISF:%s/%s/%s" % (w1, b, w2)
            if None in (k1, kb, k2):
                self.missing[key] = "vade yok"
                continue
            fly = {kb: 1.0, k1: -FLY_WING, k2: -FLY_WING}
            tiers[tier([w1, b, w2])].append(OisPackage(self, key, "%s/%s/%s fly" % (w1, b, w2),
                                                       ("gövde pay / kanatlar receive", "gövde receive / kanatlar pay"),
                                                       fly, fly, "bp", "rate", tier=tier([w1, b, w2])))
        fk = self._fra_keys()
        for m1, m2 in FRAS:
            if m1 in fk and m2 in fk:
                tiers[SHORT].append(Fra(self, m1, m2, fk[m1], fk[m2]))
            else:
                self.missing["FRA:%dx%d" % (m1, m2)] = "vade yok"
        for k in range(1, PPK_PERIODS + 1):
            tiers[SHORT].append(PpkPeriod(self, k))
        self.items.extend(tiers[SHORT] + tiers[LONG])
        # 4. DİBS: the RV list's fixed-coupon bonds, by maturity
        rows = {r["isin"]: r for r in self.eng.get("dibs") or []}
        bonds = []
        for key, m in meta.items():
            if not key.startswith("DIBS:") or m.get("unit") == "px" or str(m.get("type") or "").upper() not in ("S",):
                continue
            isin = key[5:].upper()
            row = rows.get(isin)
            b = qc._bond_of(isin, m, row)
            if b is None or b.kind != "fixed" or (b.maturity - ctx.today).days < DIBS_MIN_DAYS:
                continue
            conv = qc.detect_convention(ctx.last(key), qc._pct((row or {}).get("simple")), qc._pct((row or {}).get("compound")))
            bonds.append((b.maturity, isin, b, row, conv))
        for _, isin, b, row, conv in sorted(bonds):
            self._add(Dibs(self, isin, b, row, conv))
        # 5. VİOP: the listed contracts
        try:
            listed = [c for c in qv.contracts_of(ctx, self.eng) if not c.expired][:qv.LISTED_MAX]
        except Exception:  # noqa: BLE001 - no contracts, no VİOP lines
            listed = []
        for c in listed:
            self._add(Viop(self, c))
        # 6. Offshore: the forwards, the swap points, the offshore curve
        for pair, tenor in OFFSHORE_FWD:
            if "FXP:%s:%s" % (pair, tenor) in meta and "FX:" + pair in meta:
                self._add(FxForward(self, pair, tenor))
        for pair, tenor in OFFSHORE_FWD:
            if "FXP:%s:%s" % (pair, tenor) in meta:
                self._add(SwapPoints(self, pair, tenor))
        off = sorted((m.get("months") or 0.0, k) for k, m in meta.items() if k.startswith("OFF:") and m.get("months"))
        for mo, k in off:
            self._add(OffRate(self, k, mo))
        # the inputs
        for k in INPUTS + tuple("OIS:" + t for t in OIS_INPUTS):
            if k in meta or k in ctx.series:
                self.extra.append(Input(self, k))
