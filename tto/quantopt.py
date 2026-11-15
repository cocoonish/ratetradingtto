"""Options analytics of the FX smiles: USDTRY and EURUSD - the ATM term structure (1W - 1Y), the 25- and 10-delta risk
reversals and butterflies at 1M and 3M, their signals (skew and wings rich or cheap, the slope of the ATM term
structure) and the distribution the smile implies against the forward: the probability of a move beyond ±X % in
1M / 3M next to how often the spot ended that far from the forward over the history.  ``tto.quant`` runs it next to
the families of ``tto.quantfam`` (page "Opsiyon", family "Opsiyon smile").

**Quotes.**  Bloomberg's FX vol tickers named as the FX pages name them (``tto.fx.vol_ticker``: ``USDTRYV1M BGN
Curncy`` ATM, ``USDTRY25R1M`` / ``USDTRY10R1M`` risk reversals, ``USDTRY25B1M`` / ``USDTRY10B1M`` butterflies; the
desk's pricing source), in vol points.  ATM 3M and 25D RR 3M are the quant package's own series already; the rest
(``series_specs``) join the history's list, two years back, filled a few per sync like the package's others - and
EURUSD's 1M / 3M forward points (USDTRY's are the package's).

**The distribution.**  A tenor's five quotes make one arbitrage-free smile (``tto.fxvol``: Gatheral's SVI fitted to
ATM, 25D / 10D RR and BF with the pair's conventions - USDTRY premium-adjusted forward deltas, EURUSD spot deltas with
the EUR discount factor from its forward and USD OIS -, the butterflies repriced as market strangles, the
no-butterfly and wing conditions as penalties).  Five quotes are enough for SVI's five parameters and its density
never goes below zero: mid quotes need not be consistent among themselves (USDTRY's rarely are) and the closest
arbitrage-free smile is taken - its residuals, in vol points, are on the page.  Breeden-Litzenberger then reads
P(S_T > K) = −∂C/∂K off the smile (undiscounted prices: the forward measure, so the mean is the forward).  T is the
tenor's calendar days over 365 (1M 30.4, 3M 91.25).  Without the butterflies the smile is flat on the ATM vol
(lognormal), and the page says so.

**Carry-aware.**  The moves are measured from the forward, not from the spot: USDTRY's 3M forward is several per
cent above the spot, and "+5 % from the spot" is close to certain without saying anything about the options.
Implied: P(S_T > F·(1+X)) and P(S_T < F·(1−X)).  Realized: every day of the history with a forward of the tenor, and
the spot the tenor later (the first close on or after the delivery day, within a week): how often S_T / F − 1 was
above X or below −X.  Overlapping windows: n days are worth about n / (business days of the tenor) independent
ones; the standard error is from those.  The average of S_T / F − 1 beside it is the forward's bias over the window
(the carry trade's return).

**Signals** (``quantfam.mr_monitor``: z over the window, OU half-life, regime), in vol points as quoted: 25D RR 1M /
3M (skew rich → sell the risk reversal), 25D BF 1M / 3M and 10D BF 1M (wings rich → sell the butterfly), the ATM
slope 1Y − 1M (rich → sell 1Y / buy 1M vol).  The tables show RR / ATM and BF / ATM beside the quotes - a z of the
level that is only the ATM vol's own move shows there.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import fx as fxm
from . import fxvol as fv
from . import quantcurve as qc
from . import quantfam as qf
from . import quantmath as qm

FAMILIES = {"opt": ("Opsiyon smile", "mr", "quant-opt")}
PAGES = (("quant-opt", "Opsiyon"),)
VIEW = "opt"
TABLES = ("opt",)

PAIRS = ("USDTRY", "EURUSD")
TENORS = ("1W", "1M", "3M", "6M", "1Y")
#: the quotes kept per pair: (kind, tenor)
SURFACE = (("ATM", "1W"), ("ATM", "1M"), ("ATM", "3M"), ("ATM", "6M"), ("ATM", "1Y"), ("RR25", "1M"), ("RR25", "3M"),
           ("BF25", "1M"), ("BF25", "3M"), ("RR10", "1M"), ("RR10", "3M"), ("BF10", "1M"), ("BF10", "3M"))
#: the quotes the quant package keeps already (``quant.series_specs``): their keys there
OWN = {("ATM", "3M"): "FXV:", ("RR25", "3M"): "FXR:"}
#: forward points this module adds (USDTRY's 1M / 3M are the package's)
POINTS = (("EURUSD", "1M"), ("EURUSD", "3M"))
SMILE_TENORS = ("1M", "3M")
#: the moves (per cent from the forward) of the probability table
MOVES = {"USDTRY": {"1M": (2.0, 3.0, 5.0), "3M": (3.0, 5.0, 10.0)}, "EURUSD": {"1M": (1.0, 2.0, 3.0), "3M": (2.0, 3.0, 5.0)}}
BDAYS = {"1M": 21, "3M": 63}
#: the monitors: (sid part, kind, tenor, what it says)
SIGNALS = (("RR25:1M", "RR25", "1M"), ("RR25:3M", "RR25", "3M"), ("BF25:1M", "BF25", "1M"), ("BF25:3M", "BF25", "3M"),
           ("BF10:1M", "BF10", "1M"))
SLOPE = ("1Y", "1M")
#: the smile model of the distribution (``tto.fxvol.MODELS``)
MODEL = "svi"


def key(pair: str, kind: str, tenor: str) -> str:
    """The history key of a quote: the package's own for ATM 3M / 25D RR 3M, ``OPT:<pair>:<kind>:<tenor>`` else."""
    own = OWN.get((kind, tenor))
    return own + pair if own else "OPT:%s:%s:%s" % (pair, kind, tenor)


def _pair(code: str) -> fxm.Pair:
    return fxm._pair(code, "FX", 4)


def label(pair: str, kind: str, tenor: str) -> str:
    """As the package names its own: "USDTRY ATM 3M vol", "USDTRY 25D RR 3M"."""
    return "%s ATM %s vol" % (pair, tenor) if kind == "ATM" else "%s %s %s" % (pair, fxm.KIND_LABEL[kind], tenor)


def series_specs(source: str = fxm.DEFAULT_SOURCE) -> List[Dict[str, str]]:
    """The tickers this module adds to the package's list (``quant.series_specs``): ``{key, label, ticker, kind, group}``."""
    out: List[Dict[str, str]] = []
    for pair in PAIRS:
        for kind, tenor in SURFACE:
            if (kind, tenor) in OWN:
                continue
            out.append({"key": key(pair, kind, tenor), "label": label(pair, kind, tenor), "ticker": fxm.vol_ticker(pair, kind, tenor, source),
                        "kind": "vol", "group": "FX"})
    for pair, tenor in POINTS:
        out.append({"key": "FXP:%s:%s" % (pair, tenor), "label": "%s %s swap puanı" % (pair, tenor),
                    "ticker": fxm.points_ticker(_pair(pair), tenor), "kind": "pts", "group": "FX"})
    return out


def covers(k: str) -> bool:
    """The series the page's data-coverage table lists."""
    if k.startswith("OPT:") or k == "USD:3M":
        return True
    for pair in PAIRS:
        if k in ("FX:" + pair, "FXV:" + pair, "FXR:" + pair) or k in ("FXP:%s:%s" % (pair, t) for t in SMILE_TENORS):
            return True
    return False


# ---------------------------------------------------------------------------------------------- smiles
_lock = threading.Lock()
_smiles: Dict[Tuple, Tuple[Any, Dict[str, Any]]] = {}


def _moved(smile: Any, info: Dict[str, Any], F: float) -> Tuple[Any, Dict[str, Any]]:
    """A smile carried to another forward: its shape in moneyness is the same (every condition of the fit depends on
    the strikes only through K/F)."""
    if abs(F / smile.F - 1.0) < 1e-14:
        return smile, info
    if isinstance(smile, fv.SviSmile):
        return fv.SviSmile(F, smile.T, smile.a, smile.b, smile.rho, smile.m, smile.s), info
    return fv.FlatSmile(F, smile.T, smile.vol(smile.F)), info


def smile_of(pair: str, tenor: str, q: fv.Quotes) -> Tuple[Any, Dict[str, Any]]:
    """The fitted smile of a tenor's quotes, kept by its quotes (not its forward) - the live refresh does not fit it
    again while the vols stand still."""
    k = (pair, tenor, round(q.T, 10), round(q.atm, 8), q.rr25 and round(q.rr25, 8), q.bf25 and round(q.bf25, 8),
         q.rr10 and round(q.rr10, 8), q.bf10 and round(q.bf10, 8), q.premium, round(q.df, 10))
    with _lock:
        hit = _smiles.get(k)
    if hit is not None:
        return _moved(hit[0], hit[1], q.F)
    smile, info = fv.build_smile(q, MODEL)
    with _lock:
        if len(_smiles) > 64:
            _smiles.clear()
        _smiles[k] = (smile, info)
    return smile, info


def quotes_now(ctx: qf.Ctx, pair: str, tenor: str, live: Dict[str, float]) -> Tuple[Optional[fv.Quotes], Dict[str, Any]]:
    """A tenor's quotes now as ``fxvol.Quotes`` (vol units, the forward, T, the pair's delta conventions) and what
    went into them; ``None`` without a forward or an ATM vol."""
    p = _pair(pair)
    vols = {kind: ctx.cur(key(pair, kind, tenor), live) for kind in fxm.KINDS}
    F = ctx.cur("FWD:%s:%s" % (pair, tenor), live)
    S = ctx.cur("FX:" + pair, live)
    days = qf._tenor_days(tenor)
    info: Dict[str, Any] = {"F": F, "S": S, "days": days, "T": days / 365.0, "vols": vols, "premium": p.premium}
    if not F or not vols.get("ATM"):
        info["why"] = "forward yok" if not F else "ATM vol yok"
        return None, info
    df, delta = 1.0, "forward"
    if p.spot_delta(tenor):
        usd = ctx.cur("USD:3M", live)
        if S and usd is not None:
            df = F / S / (1.0 + usd / 100.0 * days / 360.0)
            delta = "spot"
        else:
            info["note"] = "faiz yok: forward delta"
    info.update({"df": df, "delta": delta})
    pct = lambda k: vols[k] / 100.0 if vols.get(k) is not None else None   # noqa: E731
    return fv.Quotes(F, days / 365.0, vols["ATM"] / 100.0, pct("RR25"), pct("BF25"), pct("RR10"), pct("BF10"), premium=p.premium, df=df), info


def implied(ctx: qf.Ctx, pair: str, tenor: str, live: Dict[str, float], moves: Sequence[float]) -> Dict[str, Any]:
    """Today's smile of a tenor and the probabilities of the moves from the forward: ``{F, S, fwd_pct, T, model, fit
    (residuals, vol points), arbitrage, q (quantiles as % from F), up / down per move}``."""
    q, info = quotes_now(ctx, pair, tenor, live)
    out: Dict[str, Any] = {"tenor": tenor, "F": info.get("F"), "S": info.get("S"), "T": info.get("T"), "delta": info.get("delta"),
                           "note": info.get("note") or ""}
    if info.get("F") and info.get("S"):
        out["fwd_pct"] = (info["F"] / info["S"] - 1.0) * 100.0
    if q is None:
        out["why"] = info.get("why")
        return out
    try:
        smile, si = smile_of(pair, tenor, q)
    except fv.MATH_ERRORS as exc:
        out["why"] = "smile kurulamadı: %s" % exc
        return out
    dist = fv.Distribution(smile)
    chk = dist.check()
    out.update({"model": si.get("model"), "fit": {k: (v * 100.0 if v is not None else None) for k, v in (si.get("fit") or {}).items()},
                "arbitrage": chk["arbitrage"], "mean_error": chk["mean_error"],
                "q": {"%g" % p: (v / q.F - 1.0) * 100.0 if v else None for p, v in fv.quantiles(dist, (0.05, 0.25, 0.5, 0.75, 0.95)).items()},
                "up": [], "down": []})
    for x in moves:
        try:
            out["up"].append(min(1.0, max(0.0, dist.above(q.F * (1.0 + x / 100.0)))))
            out["down"].append(min(1.0, max(0.0, dist.cdf(q.F * (1.0 - x / 100.0)))))
        except fv.MATH_ERRORS:
            out["up"].append(None)
            out["down"].append(None)
    return out


# ---------------------------------------------------------------------------------------------- the realized side
def realized(spot: Sequence[Tuple[str, float]], fwd: Dict[str, float], days: int) -> List[Tuple[str, float]]:
    """``(day, S_T / F − 1)`` for every day with a forward and a spot close ``days`` calendar days later (the first on
    or after that day, at most a week after it)."""
    ds = [d for d, _ in spot]
    vs = [v for _, v in spot]
    out = []
    for d, f in sorted(fwd.items()):
        if not f or f <= 0:
            continue
        target = _dt.date.fromisoformat(d) + _dt.timedelta(days=days)
        i = bisect.bisect_left(ds, target.isoformat())
        if i >= len(ds):
            break
        if (_dt.date.fromisoformat(ds[i]) - target).days > 7:
            continue
        out.append((d, vs[i] / f - 1.0))
    return out


def frequencies(moves: Sequence[Tuple[str, float]], xs: Sequence[float], bdays: int) -> Dict[str, Any]:
    """How often the move was beyond +X / −X (per cent), with the standard error of n / ``bdays`` independent
    windows."""
    r = [v for _, v in moves]
    n = len(r)
    n_eff = n / float(bdays) if bdays else float(n)
    out: Dict[str, Any] = {"n": n, "n_eff": n_eff, "up": [], "down": [], "up_se": [], "down_se": [], "first": moves[0][0] if moves else None,
                           "last": moves[-1][0] if moves else None, "mean": sum(r) / n * 100.0 if n else None,
                           "sd": (qm.stdev(r) or 0.0) * 100.0 if n > 2 else None}
    for x in xs:
        for side, hit in (("up", lambda v, x=x: v > x / 100.0), ("down", lambda v, x=x: v < -x / 100.0)):
            if not n:
                out[side].append(None)
                out[side + "_se"].append(None)
                continue
            p = sum(1 for v in r if hit(v)) / float(n)
            out[side].append(p)
            out[side + "_se"].append(math.sqrt(p * (1.0 - p) / max(n_eff, 1.0)))
    return out


# ---------------------------------------------------------------------------------------------- the family
def fam_opt(ctx: qf.Ctx) -> Tuple[List[qf.Monitor], Dict[str, Any]]:
    """The smile signals of every pair, the realized side of the probability table and the window's statistics of
    each quote; the live part (the surface now, the smiles and their probabilities) is built by the table's
    ``build``."""
    win = ctx.window()
    mons: List[qf.Monitor] = []
    by_sid: Dict[str, qf.Monitor] = {}
    stats: Dict[str, Tuple[float, float, int]] = {}
    real: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for pair in PAIRS:
        for kind, tenor in SURFACE:
            k = key(pair, kind, tenor)
            vals = [v for _, v in ctx.pts(k)][-win:]
            if len(vals) >= 20:
                mean, sd = qf.window_stats(vals)
                if sd:
                    stats[k] = (mean, sd, len(vals))
        for part, kind, tenor in SIGNALS:
            k = key(pair, kind, tenor)
            pts = ctx.pts(k)
            name = "%s %s %s" % (pair, tenor, fxm.KIND_LABEL[kind])
            what = "skew" if kind.startswith("RR") else "kanatlar"
            mon = qf.mr_monitor(ctx, "opt:%s:%s" % (pair, part), "opt", "FX vol", name, "vol", 2, [d for d, _ in pts], [v for _, v in pts],
                                "vol", [{"key": k, "name": name, "weight": 1.0}], lambda live, k=k: ctx.cur(k, live), pkg="vol",
                                info={"inputs": [k], "kind": kind, "tenor": tenor},
                                note="%s (vol puanı) kendi penceresine göre: + z ise %s pahalı (sat), − ise ucuz (al). %s"
                                     % (name, what, "Risk reversal: call vol − put vol (USDTRY'de yukarı kuyruk)." if what == "skew"
                                        else "Butterfly: kanat (strangle) vol − ATM vol, piyasa strangle'ı olarak."))
            if mon is not None:
                mons.append(mon)
                by_sid[mon.sid] = mon
        long_k, short_k = key(pair, "ATM", SLOPE[0]), key(pair, "ATM", SLOPE[1])
        days, (a, b) = qf.aligned(ctx, [long_k, short_k])
        name = "%s ATM vol eğimi %s−%s" % (pair, SLOPE[0], SLOPE[1])
        mon = qf.mr_monitor(ctx, "opt:%s:SLOPE" % pair, "opt", "FX vol", name, "vol", 2, days, [x - y for x, y in zip(a, b)], "vol",
                            [{"key": long_k, "name": "%s %s ATM vol" % (pair, SLOPE[0]), "weight": 1.0},
                             {"key": short_k, "name": "%s %s ATM vol" % (pair, SLOPE[1]), "weight": -1.0}],
                            lambda live, long_k=long_k, short_k=short_k: _diff(ctx.cur(long_k, live), ctx.cur(short_k, live)), pkg="spread",
                            info={"inputs": [long_k, short_k]},
                            note="ATM vol vade yapısının eğimi (%s − %s, vol puanı): + z ise uzun vade vol'ü kısaya göre pahalı (eğimi sat: %s sat / "
                                 "%s al), − ise ucuz." % (SLOPE[0], SLOPE[1], SLOPE[0], SLOPE[1]))
        if mon is not None:
            mons.append(mon)
            by_sid[mon.sid] = mon
        spot = ctx.pts("FX:" + pair)
        for tenor in SMILE_TENORS:
            fwd = ctx.series.get("FWD:%s:%s" % (pair, tenor)) or {}
            moves = realized(spot, fwd, int(round(qf._tenor_days(tenor))))
            real[(pair, tenor)] = frequencies(moves, MOVES[pair][tenor], BDAYS[tenor])

    def zof(k: str, v: Optional[float]) -> Optional[float]:
        s = stats.get(k)
        return (v - s[0]) / s[1] if s is not None and v is not None else None

    def build(live: Dict[str, float]) -> Dict[str, Any]:
        out = []
        for pair in PAIRS:
            surface = []
            for tenor in TENORS:
                row: Dict[str, Any] = {"tenor": tenor}
                atm = ctx.cur(key(pair, "ATM", tenor), live)
                for kind in fxm.KINDS:
                    if (kind, tenor) not in SURFACE:
                        continue
                    k = key(pair, kind, tenor)
                    v = ctx.cur(k, live)
                    row[kind] = v
                    row[kind + "_z"] = zof(k, v)
                    row[kind + "_n"] = (stats.get(k) or (0, 0, len(ctx.pts(k))))[2]
                    row[kind + "_live"] = k in live
                    if kind != "ATM" and v is not None and atm:
                        row[kind + "_atm"] = v / atm
                for part, kind, t in SIGNALS:
                    if t == tenor:
                        m = by_sid.get("opt:%s:%s" % (pair, part))
                        if m is not None:
                            row[kind + "_sid"] = m.sid
                            row[kind + "_hl"] = m.half_life
                surface.append(row)
            slopes = []
            for a, b in (("3M", "1M"), ("1Y", "3M"), ("1Y", "1M"), ("1M", "1W")):
                va, vb = ctx.cur(key(pair, "ATM", a), live), ctx.cur(key(pair, "ATM", b), live)
                m = by_sid.get("opt:%s:SLOPE" % pair) if (a, b) == SLOPE else None
                v = _diff(va, vb)
                slopes.append({"name": "%s−%s" % (a, b), "value": v, "z": m.zof(v) if m is not None and v is not None else None,
                               "sid": m.sid if m is not None else None, "half_life": m.half_life if m is not None else None})
            smiles = []
            for tenor in SMILE_TENORS:
                xs = MOVES[pair][tenor]
                imp = implied(ctx, pair, tenor, live, xs)
                rl = real.get((pair, tenor)) or {}
                none = [None] * len(xs)
                cols = {"up": imp.pop("up", None) or none, "down": imp.pop("down", None) or none,
                        "up_real": rl.get("up") or none, "down_real": rl.get("down") or none,
                        "up_se": rl.get("up_se") or none, "down_se": rl.get("down_se") or none}
                imp["probs"] = [dict({"x": x}, **{name: col[i] for name, col in cols.items()}) for i, x in enumerate(xs)]
                imp["realized"] = {k: rl.get(k) for k in ("n", "n_eff", "mean", "sd", "first", "last")}
                smiles.append(imp)
            out.append({"pair": pair, "spot": ctx.cur("FX:" + pair, live), "spot_live": ("FX:" + pair) in live, "surface": surface,
                        "slopes": slopes, "smiles": smiles, "convention": fxm.convention_text(_pair(pair))})
        return {"ok": True, "pairs": out, "moves": {p: {t: list(x) for t, x in m.items()} for p, m in MOVES.items()}, "model": MODEL}

    return mons, {"ok": True, "build": build}


def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return a - b if a is not None and b is not None else None


# ---------------------------------------------------------------------------------------------- run, live tables
def run(ctx: qf.Ctx, eng: Dict[str, Any], mons: List[qf.Monitor], tables: Dict[str, Any], timing: Dict[str, float],
        pause: Optional[Callable[[], None]] = None) -> None:
    """``quant.Quant.compute``: this module's family after quantfam's (see ``quantcurve.run``)."""
    qc.run_step("opt", lambda: fam_opt(ctx), mons, tables, timing, pause, ctx)


def live_tables(t: Dict[str, Any], ctx: qf.Ctx) -> None:
    """``quant.Quant._tables``: the surface, the smiles and their probabilities with the values now."""
    qc.build_tables(t, ctx, TABLES)


def read_engine(out: Dict[str, Any], index: Dict[str, int], reader: Callable[[str], Callable[[str], Any]],
                num: Callable[[Any], Optional[float]]) -> None:
    """Nothing of the workbook: the quotes come through the package's live values."""


def live_values(eng: Dict[str, Any]) -> Dict[str, float]:
    return {}
