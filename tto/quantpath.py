"""The implied policy path as a mixture of discrete decisions: the "İma Patikası" page and the WIRP of the TCMB and
the Fed ("TCMB WIRP") - both on the quant package's worker (``tto.quant`` calls :func:`run` on a full fit and
:func:`refresh` on the minute's live refresh, the pages read :func:`view`).

**The idea (the desk's).**  The implied step of a meeting is an expectation over discrete decisions: the CBRT moves in
multiples of 50 bp (250 / 300 / 350 too), the Fed in multiples of 25 - each bank's grid is a desk setting.  An implied
−40 is −50 with 80 % and no change with 20 %; −40 then −60 (−100 by the second meeting) is a mix of (0, −100),
(−100, 0) and (−50, −50), whose probabilities can be anywhere in 20–60 %, 0–40 % and 0–80 %.  The instrument that
carries the timing view is the meeting-dated OIS of the period between the two meetings: priced at TLREF − 40, it
makes +10 bp received if the steps are equal, −40 if the cut comes late, +60 if it comes early; the period after the
second meeting is TLREF − 100 in all three.

**Where the path comes from.**  TRY: what the history computed day by day with the workbook's own solver (the store's
``mpc_days`` / ``mpc_values``: the TLREF level after each meeting, the base it starts from - on a decision day the
level the market prices from that decision on); the latest day is today's path (live: the history computes it again
every 15 minutes - the solver never runs on the engine thread).  The decisions that were taken: the TLREF fixing after
a meeting against the one of its day, on the grid (a change off the grid by more than a third of a step is not a
decision: TLREF left the policy rate, e.g. funding at the corridor's upper band).  USD: the FOMC table of the ``sofr``
workbook (``SOFR_FOMC!B74:K83``: meeting, the implied O/N after it; the base is the stub O/N ``B7 + B16/100``, the
Fed's upper bound ``B8``), read in one short call at the engine thread's lowest priority, and kept as a snapshot per
day in the store (``quant.path.usd``: the USD history starts the day this runs; no Bloomberg request of its own).

**Per meeting.**  The step Δ (bp) is split between the two grid multiples around it, Δ = p·lo + (1 − p)·hi; with the
cumulative move and the moves priced (cumulative ÷ grid).

**Consecutive meetings.**  The discrete paths consistent with the two steps: on the grid, monotone (no reversal from
one meeting to the next), their total one of the two grid multiples around the implied total - and if no such mix
gives the two steps (the market prices a reversal), every pair of each meeting's own two outcomes.  The probability of
each path ranges over a polytope (the mix must give both steps); its minimum and maximum are found at the polytope's
vertices (every basic feasible solution, exactly - a handful of paths).  The P&L per DV01 of receiving the
meeting-dated OIS periods under each path: Δ₁ − a₁ for the period between the meetings (against the period before it
from the second pair on), (Δ₁ + Δ₂) − (a₁ + a₂) for the period after the second.

**Kinks.**  A period's level against the average of its neighbours, d_k = C_k − (C_{k−1} + C_{k+1}) / 2 = −(Δ_{k+1} −
Δ_k) / 2 (half the second difference): + the period is cheap against an equal-step path (receive), − rich (pay).  A
zig-zag is a second difference changing sign by at least a fifth of a step from one meeting to the next.  Measured
with z against its own history (the same meeting's d on the days before); with 40 days of it, a signal (family
"İma patikası ayrıklığı": the fly +1 period k, −½ each neighbour, carry 0 - forward-starting fixed-date periods).

**Calibration.**  On the days a meeting was the next one (at most 20 business days before it): the priced probability
of the bigger of its two outcomes against what was decided.  Buckets of the priced probability with day and meeting
counts; the interval and the test count meetings, not days (the days of one meeting are one outcome).  A bias over at
least 8 meetings (calibration z = Σ (frequency − price) ÷ √Σ p(1 − p), one term a meeting) past the entry threshold
is a signal (family "İma kalibrasyonu"): the next meeting's period towards the outcome the market under-prices.

**WIRP (Bloomberg's WIRP, CME's FedWatch).**  Each meeting's step split as above, the steps taken as independent
given the expected path: the distribution after a meeting is the one after the meeting before convolved with this
meeting's two-point step - the conditional probability matrix (meetings × rate buckets), whose expected values give
the implied path back (shown as a check).  The path is in TLREF (SOFR) terms; the policy rate is mapped with today's
spread to it held constant (the one-week repo rate: the desk's setting "Politika faizi (elle)", else the rate the
desk types on Masa - ``MASA!Q155``, the workbook's own "PPK · piyasa ima vs anket" table maps it the same way; the
Fed: its upper bound ``FDTR``).  History: the next three meetings' probabilities 1 day, 1, 2 and 4 weeks ago, in the
rate buckets of today (the decisions in between from TLREF on the grid).
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import itertools
import json
import math
import time
import weakref
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf
from . import quantmath as qm

# ---------------------------------------------------------------------------------------------- settings
#: the desk's settings of this module (quant.py adds them to its own: "Masa ayarları", for everyone) - the WIRP lines'
#: two (28.11.2026, "every assumption typeable"): a line prints when |ima − anket| is at least ``wirp_min`` of the grid
#: (a quarter: 12,5 bp on the PPK's 50), its stop ``wirp_stop`` of the grid against (a half: 25 bp)
DEFAULTS: Dict[str, Any] = {"path_grid_try": 50.0, "path_grid_usd": 25.0, "path_policy": 0.0, "wirp_min": 0.25, "wirp_stop": 0.5}
LIMITS: Dict[str, Tuple[float, float, type]] = {"path_grid_try": (5.0, 500.0, float), "path_grid_usd": (5.0, 100.0, float),
                                                "path_policy": (0.0, 200.0, float), "wirp_min": (0.05, 2.0, float),
                                                "wirp_stop": (0.1, 3.0, float)}
LABELS = {"path_grid_try": "PPK adım ızgarası (bp)", "path_grid_usd": "FOMC adım ızgarası (bp)",
          "path_policy": "Politika faizi, elle (%; 0: Masa!Q155)",
          "wirp_min": "WIRP sinyali: ima − anket en az (ızgaranın payı)", "wirp_stop": "WIRP sinyali: stop (ızgaranın payı, ters)"}

#: the families of this module (quantfam.FAMILIES) and the pages that show them (what -> page id)
FAMILY_KINK, FAMILY_CAL = "imapath", "imacal"
#: the WIRP's AL / SAT lines (28.11.2026, the desk's "C 16"): a meeting's implied policy rate against the PPK survey
#: (Masa's "PPK · piyasa ima vs anket", MASA!R157:R159 dated Q157:Q159) - or a user's own "Beklentim" on the WIRP table
FAMILY_WIRP = "wirp"
VIEWS = {"path": "quant-path", "wirp": "quant-wirp"}

#: bank -> what it is called, the grid's setting, the key of its meeting-dated periods (a trade's leg), its asset
BANKS: Dict[str, Dict[str, str]] = {
    "try": {"label": "TCMB · PPK", "short": "PPK", "grid": "path_grid_try", "leg": "MPC:", "asset": "TRY OIS", "rate": "TLREF"},
    "usd": {"label": "Fed · FOMC", "short": "FOMC", "grid": "path_grid_usd", "leg": "FOMC:", "asset": "Global", "rate": "SOFR"},
}
POLICY_CELL = ("MASA", "Q155")                 # "Politika faizi %": the desk types it (the workbook's PPK vs survey table)
SURVEY_ROWS = (157, 159)                       # MASA!Q157:R159: the survey's next three meetings - "Tarih" (Q), "Anket %" (R)
SURVEY_MONTH = "S155"                          # MASA!S155: "Anket ayı" (the month of the survey typed)
#: OIS_MAIN's "MPC OIS" (A82:M99): each meeting period's start (B: the meeting's effective day), end (C: the next one's)
#: and its market rate (D, "Piyasa (bootstrap)": Bootstrap's forward of the period, simple ACT/365 - what Trades values a
#: PPK period at) beside the PPK model's own (BJ)
MPC_OIS_ROWS = (84, 99)
FOMC_SHEET = "SOFR_FOMC"
FOMC_ROWS = (74, 83)                           # SOFR_FOMC!B74:B83 - the FOMC meetings of the USD workbook
FED_RANGE = 25.0                               # bp: the width of the Fed's target range (its buckets' labels)

SHOW_MEETINGS = 16                             # meetings in the per-meeting table
PAIRS = 4                                      # consecutive pairs with their scenarios
KINK_MEETINGS = 8                              # meetings measured for kinks
WIRP_MEETINGS = 12                             # meetings of the WIRP and its matrix
WIRP_HISTORY = 3                               # next meetings whose probabilities are followed back
WIRP_CHART_DAYS = 40                           # business days of the implied steps' chart
LOOKBACKS = ((0, "bugün"), (1, "1 gün önce"), (5, "1 hafta önce"), (10, "2 hafta önce"), (20, "4 hafta önce"))
KINK_MIN_OBS = 40                              # days of a kink's own history before it can be a signal
Z_MIN_OBS = 20                                 # ... before its z is shown
CAL_WINDOW = 20                                # business days before a meeting whose pricing the calibration reads
CAL_MIN_MEETINGS = 8                           # meetings before a calibration bias can be a signal
CAL_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
WILSON_Z = 1.645                               # the calibration's intervals: 90 %
OFF_GRID = 1.0 / 3.0                           # a TLREF change this far (in steps) from the grid is not a decision
GRID_EPS = 1e-6
PROB_EPS = 1e-12
USD_KEY = "quant.path.usd"                     # the store's daily snapshots of the USD path
USD_KEEP_DAYS = 800
USD_WRITE_EVERY = 600.0                        # seconds: today's snapshot is written again at most this often


# ---------------------------------------------------------------------------------------------- small helpers
def _num(v: Any) -> Optional[float]:
    return v if type(v) is float and math.isfinite(v) else (float(v) if type(v) is int else None)


def _tr(iso: str) -> str:
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[2:4])


def _bdays(a: str, b: str) -> int:
    """Week days after ``a`` up to ``b`` (ISO days; negative when ``b`` is before ``a``)."""
    d0, d1 = _dt.date.fromisoformat(a), _dt.date.fromisoformat(b)
    sgn = 1
    if d1 < d0:
        d0, d1, sgn = d1, d0, -1
    n = 0
    while d0 < d1:
        d0 += _dt.timedelta(days=1)
        if d0.weekday() < 5:
            n += 1
    return sgn * n


def _back(day: str, n: int) -> str:
    """The week day ``n`` week days before ``day``."""
    d = _dt.date.fromisoformat(day)
    while n > 0:
        d -= _dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d.isoformat()


def _n(v: float, digits: int = 1) -> str:
    """A number as the desk writes it: whole when it is (within 0,05), else ``digits`` decimals; a decimal comma and a
    real minus sign (−40, 12,5)."""
    if abs(v - round(v)) < 0.05 or digits <= 0:
        text = "%d" % round(v)
    else:
        text = ("%.*f" % (digits, v)).replace(".", ",")
    if text.startswith("-") and not text.strip("-0,"):
        text = text[1:]                                    # no "−0"
    return text.replace("-", "−")


def _s(v: float, digits: int = 1) -> str:
    """Signed: +10, −40, 0."""
    text = _n(v, digits)
    return text if text.startswith("−") or not text.strip("0,") else "+" + text


def _pct(p: Optional[float]) -> str:
    return "—" if p is None else "%%%d" % round(p * 100.0)


# ---------------------------------------------------------------------------------------------- 1. one meeting on the grid
def bracket(step: float, grid: float) -> Dict[str, float]:
    """The two grid outcomes around an implied step and their probabilities - the pair whose mix has the step as its
    mean: −40 on a 50 grid is −50 with 80 % and 0 with 20 %; a step on the grid is that outcome for certain.  ``big``
    is the outcome further from no change (the bigger move), ``small`` the other."""
    x = step / grid
    k = round(x)
    if abs(x - k) < GRID_EPS:
        lo, f = int(k), 0.0
    else:
        lo = int(math.floor(x))
        f = x - lo
    lo_bp, hi_bp = float(lo * grid), float((lo + 1) * grid)
    p_lo, p_hi = 1.0 - f, f
    if abs(lo_bp) > abs(hi_bp):
        big, small, p_big = lo_bp, hi_bp, p_lo
    else:
        big, small, p_big = hi_bp, lo_bp, p_hi
    return {"lo": lo_bp, "hi": hi_bp, "p_lo": p_lo, "p_hi": p_hi, "k": lo, "big": big, "small": small, "p_big": p_big}


def decompose(path: Dict[str, Any], grid: float) -> List[Dict[str, Any]]:
    """Every meeting of a path (``{"base": %, "meetings": [(ISO day, level %)]}``) on the grid: its level, the step
    from the level before it (bp; the first from the base), the cumulative move, the moves priced and its bracket."""
    base = path["base"]
    prev = base
    out = []
    for meeting, level in path["meetings"]:
        step = (level - prev) * 100.0
        cum = (level - base) * 100.0
        row = {"meeting": meeting, "level": level, "step": step, "cum": cum, "moves": cum / grid}
        row.update(bracket(step, grid))
        out.append(row)
        prev = level
    return out


# ---------------------------------------------------------------------------------------------- 2. consecutive meetings
def _independent(rows: List[List[float]], rhs: List[float]) -> Optional[Tuple[List[List[float]], List[float]]]:
    """An equivalent system of independent rows (Gaussian elimination); ``None`` when it is inconsistent."""
    basis: List[Tuple[List[float], float, int]] = []
    for row, b in zip(rows, rhs):
        r, v = list(row), b
        for brow, bv, piv in basis:
            f = r[piv] / brow[piv]
            if f:
                r = [x - f * y for x, y in zip(r, brow)]
                v -= f * bv
        scale = max([abs(x) for x in row] + [abs(b), 1.0])
        piv = max(range(len(r)), key=lambda j: abs(r[j]))
        if abs(r[piv]) <= 1e-9 * scale:
            if abs(v) > 1e-7 * scale:
                return None
            continue
        basis.append((r, v, piv))
    return [b[0] for b in basis], [b[1] for b in basis]


def lp_ranges(paths: Sequence[Sequence[float]], targets: Sequence[float]) -> Optional[List[Tuple[float, float]]]:
    """The least and the greatest probability of every path in a mix of ``paths`` (steps per meeting) whose expected
    steps are ``targets`` - over the vertices of the polytope {p ≥ 0, Σ p = 1, Σ p·path = targets}, every basic
    feasible solution (a handful of paths: enumerating them is exact and fast).  ``None``: no such mix."""
    m = len(paths)
    if not m:
        return None
    rows = [[1.0] * m] + [[float(p[i]) for p in paths] for i in range(len(targets))]
    system = _independent(rows, [1.0] + [float(t) for t in targets])
    if system is None:
        return None
    a, b = system
    r = len(a)
    lo, hi = [math.inf] * m, [-math.inf] * m
    found = False
    for cols in itertools.combinations(range(m), r):
        x = qm.solve([[a[i][j] for j in cols] for i in range(r)], b)
        if x is None or min(x) < -1e-9:
            continue
        found = True
        full = [0.0] * m
        for j, v in zip(cols, x):
            full[j] = min(1.0, max(0.0, v))
        for j in range(m):
            lo[j] = min(lo[j], full[j])
            hi[j] = max(hi[j], full[j])
    return [(lo[j], hi[j]) for j in range(m)] if found else None


def _totals(total: float, grid: float) -> List[float]:
    x = total / grid
    k = round(x)
    if abs(x - k) < GRID_EPS:
        return [k * grid]
    f = math.floor(x)
    return [f * grid, (f + 1) * grid]


def pair_support(d1: float, d2: float, grid: float) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]], str]:
    """The discrete paths of two consecutive meetings consistent with their implied steps, their probability ranges
    and which support it is: ``"monoton"`` - on the grid, no reversal, the total one of the grid multiples around the
    implied total - or, when no mix of those gives both steps, ``"en yakın"`` - each meeting's own two outcomes."""
    paths: List[Tuple[float, float]] = []
    for t in _totals(d1 + d2, grid):
        n = int(round(abs(t) / grid))
        sgn = 1.0 if t > 0 else -1.0
        for j in range(n + 1):
            a1 = sgn * j * grid
            paths.append((a1 + 0.0, t - a1 + 0.0))
    ranges = lp_ranges(paths, (d1, d2))
    kind = "monoton"
    if ranges is None:
        b1, b2 = bracket(d1, grid), bracket(d2, grid)
        paths = sorted({(x, y) for x in (b1["lo"], b1["hi"]) for y in (b2["lo"], b2["hi"])})
        ranges = lp_ranges(paths, (d1, d2)) or [(0.0, 0.0)] * len(paths)
        kind = "en yakın"
    keep = [(p, r) for p, r in zip(paths, ranges) if r[1] > 1e-9]
    return [p for p, _ in keep], [r for _, r in keep], kind


def path_name(a1: float, a2: float) -> str:
    if abs(a1 - a2) < GRID_EPS:
        return "eşit adım"
    return "önden yüklü" if abs(a1) > abs(a2) else "ertelenmiş"


def reading(a1: float, a2: float, pnl1: float, pnl2: float) -> str:
    """One sentence: what the view of a path says about the two periods (receive P&L per DV01)."""
    parts = []
    for label, pnl in (("1. dönem", pnl1), ("2. dönem", pnl2)):
        if abs(pnl) < 0.05:
            continue
        parts.append("%s %s bp %s → %s" % (label, _n(abs(pnl)), "ucuz" if pnl > 0 else "pahalı", "receive" if pnl > 0 else "pay"))
    view = "%s (%s/%s) görüşü" % (path_name(a1, a2), _n(a1), _n(a2))
    return view + ": " + ("; ".join(parts) if parts else "dönemler doğru fiyatlı")


def pair_table(rows: List[Dict[str, Any]], k: int, grid: float) -> Dict[str, Any]:
    """Meetings ``k`` and ``k + 1`` (0-based) of a decomposed path: the consistent paths, their probability ranges,
    the receive P&L per DV01 of the period between them and of the period after the second, a reading of each."""
    r1, r2 = rows[k], rows[k + 1]
    d1, d2 = r1["step"], r2["step"]
    paths, ranges, kind = pair_support(d1, d2, grid)
    end = rows[k + 2]["meeting"] if k + 2 < len(rows) else None
    out = []
    for (a1, a2), (lo, hi) in zip(paths, ranges):
        pnl1, pnl2 = d1 - a1, (d1 + d2) - (a1 + a2)
        out.append({"a1": a1, "a2": a2, "name": path_name(a1, a2), "p_min": lo, "p_max": hi, "pnl1": pnl1, "pnl2": pnl2,
                    "fly": 0.5 * (d1 - d2) - 0.5 * (a1 - a2), "reading": reading(a1, a2, pnl1, pnl2)})
    # the total nearest the implied one first; in a total the equal steps, then the late move, then the early one
    out.sort(key=lambda p: (round(abs(p["a1"] + p["a2"] - d1 - d2), 6), 0 if p["name"] == "eşit adım" else 1, abs(p["a1"])))
    return {"first": r1["meeting"], "second": r2["meeting"], "end": end, "d1": d1, "d2": d2, "total": d1 + d2, "support": kind,
            "against_previous": k > 0, "paths": out}


# ---------------------------------------------------------------------------------------------- 3. kinks
def kinks(rows: List[Dict[str, Any]], grid: float, count: int = KINK_MEETINGS) -> List[Dict[str, Any]]:
    """Every meeting with a meeting after it: its period's level against the average of its neighbours (bp; the first
    against the base and the second), the second difference of the steps, and whether the path zig-zags there."""
    cums = [0.0] + [r["cum"] for r in rows]
    out = []
    for k in range(1, min(count, len(rows) - 1) + 1):
        d = cums[k] - (cums[k - 1] + cums[k + 1]) / 2.0
        s = rows[k]["step"] - rows[k - 1]["step"]
        out.append({"meeting": rows[k - 1]["meeting"], "next": rows[k]["meeting"], "prev": rows[k - 2]["meeting"] if k >= 2 else None,
                    "index": k, "d": d, "second": s, "zigzag": False})
    for a, b in zip(out, out[1:]):
        if a["second"] * b["second"] < 0 and min(abs(a["second"]), abs(b["second"])) >= grid / 5.0:
            b["zigzag"] = True
    return out


def kink_series(paths: Dict[str, Dict[str, Any]], grid: float, before: str) -> Dict[str, List[Tuple[str, float]]]:
    """The kink of every meeting day by day (days before ``before``): ``{meeting: [(day, d)]}``."""
    out: Dict[str, List[Tuple[str, float]]] = {}
    for day in sorted(paths):
        if day >= before:
            continue
        for k in kinks(decompose(paths[day], grid), grid, count=10 ** 6):
            out.setdefault(k["meeting"], []).append((day, k["d"]))
    return out


# ---------------------------------------------------------------------------------------------- 4. what was decided, calibration
def decisions_from(fixings: Dict[str, float], meetings: Sequence[str], grid: float, scale: float = 100.0,
                   strict: bool = False) -> Dict[str, Dict[str, Any]]:
    """What each meeting decided, read from a rate fixed every day (TLREF, %; the Fed's upper bound): the first fixing
    after the meeting against the last one of its day (``strict``: of the day before it - a rate that may already
    carry the decision on the day), on the grid.  ``clean`` is False when the change is off the grid by more than a
    third of a step (the rate left the policy rate; not counted)."""
    days = sorted(fixings)
    out: Dict[str, Dict[str, Any]] = {}
    for m in meetings:
        before = next((d for d in reversed(days) if d < m or (d == m and not strict)), None)
        after = next((d for d in days if d > m), None)
        if before is None or after is None or (_dt.date.fromisoformat(after) - _dt.date.fromisoformat(m)).days > 10:
            continue
        change = (fixings[after] - fixings[before]) * scale
        decided = round(change / grid) * grid
        out[m] = {"meeting": m, "before": fixings[before], "after": fixings[after], "change": change, "decided": decided + 0.0,
                  "clean": abs(change - decided) <= OFF_GRID * grid}
    return out


def _wilson(p: float, n: int, z: float = WILSON_Z) -> Tuple[Optional[float], Optional[float]]:
    if n <= 0:
        return None, None
    den = 1.0 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4.0 * n * n))) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def calibration(paths: Dict[str, Dict[str, Any]], decided: Dict[str, Dict[str, Any]], grid: float,
                window: int = CAL_WINDOW) -> Dict[str, Any]:
    """On the days a meeting was the next one (at most ``window`` business days before it), the priced probability of
    its bigger outcome against what was decided: buckets, the meetings one by one, the bias and its z."""
    obs: Dict[str, List[Dict[str, Any]]] = {}
    outside = 0
    for day in sorted(paths):
        p = paths[day]
        if not p["meetings"]:
            continue
        m, level = p["meetings"][0]
        dec = decided.get(m)
        if dec is None or not dec["clean"]:
            continue
        bd = _bdays(day, m)
        if not 1 <= bd <= window:
            continue
        b = bracket((level - p["base"]) * 100.0, grid)
        a = dec["decided"]
        toward = 1.0 if b["big"] > b["small"] else -1.0
        y = 1 if toward * (a - b["big"]) >= -GRID_EPS else 0
        inside = abs(a - b["lo"]) < GRID_EPS or abs(a - b["hi"]) < GRID_EPS
        outside += 0 if inside else 1
        obs.setdefault(m, []).append({"day": day, "bd": bd, "step": (level - p["base"]) * 100.0, "big": b["big"], "small": b["small"],
                                      "p": b["p_big"], "y": y, "inside": inside})
    buckets = []
    for lo, hi in zip(CAL_EDGES, CAL_EDGES[1:]):
        last = hi >= CAL_EDGES[-1]
        per = []
        n_days = 0
        for m, items in obs.items():
            sel = [o for o in items if lo <= round(o["p"], 9) < hi or (last and round(o["p"], 9) >= hi)]
            if sel:
                n_days += len(sel)
                per.append((sum(o["p"] for o in sel) / len(sel), sum(o["y"] for o in sel) / len(sel)))
        n = len(per)
        freq = sum(y for _, y in per) / n if n else None
        a, b = _wilson(freq, n) if n else (None, None)
        buckets.append({"lo": lo, "hi": hi, "days": n_days, "meetings": n, "priced": sum(p for p, _ in per) / n if n else None,
                        "freq": freq, "ci_lo": a, "ci_hi": b})
    meetings = []
    e_sum = v_sum = 0.0
    for m in sorted(obs):
        items = obs[m]
        last = items[-1]
        pm = sum(o["p"] for o in items) / len(items)
        e = sum(o["y"] - o["p"] for o in items) / len(items)
        v = sum(o["p"] * (1 - o["p"]) for o in items) / len(items)
        e_sum += e
        v_sum += v
        meetings.append({"meeting": m, "days": len(items), "last_day": last["day"], "last_step": last["step"], "big": last["big"],
                         "small": last["small"], "p_last": last["p"], "p_mean": pm, "decided": decided[m]["decided"],
                         "change": decided[m]["change"], "hit": last["y"], "inside": last["inside"], "excess": e})
    n = len(meetings)
    z = e_sum / math.sqrt(v_sum) if n and v_sum > PROB_EPS else None
    return {"buckets": buckets, "meetings": meetings, "n": n, "days": sum(len(v) for v in obs.values()), "outside": outside,
            "bias": e_sum / n if n else None, "z": z, "window": window, "min_meetings": CAL_MIN_MEETINGS}


# ---------------------------------------------------------------------------------------------- 5. WIRP
def convolve(dist: Dict[int, float], b: Dict[str, float]) -> Dict[int, float]:
    """The distribution after a meeting: the one before it (grid steps from today -> probability) convolved with the
    meeting's two-point step."""
    out: Dict[int, float] = {}
    for k, p in dist.items():
        for kk, q in ((b["k"], b["p_lo"]), (b["k"] + 1, b["p_hi"])):
            if q > PROB_EPS:
                out[kk + k] = out.get(kk + k, 0.0) + p * q
    return {k: p for k, p in out.items() if p > PROB_EPS}


def wirp(rows: List[Dict[str, Any]], grid: float, count: int = WIRP_MEETINGS) -> List[Dict[str, Any]]:
    """The WIRP of a decomposed path: after each meeting the distribution of the cumulative move (grid steps), the
    probabilities of a lower / the same / a higher rate than today's, the expected move (the implied one: the check)."""
    dist: Dict[int, float] = {0: 1.0}
    out = []
    for r in rows[:count]:
        dist = convolve(dist, r)
        expected = sum(k * p for k, p in dist.items()) * grid
        out.append({"meeting": r["meeting"], "level": r["level"], "step": r["step"], "cum": r["cum"], "moves": r["moves"],
                    "lo": r["lo"], "hi": r["hi"], "p_lo": r["p_lo"], "p_hi": r["p_hi"],
                    "ease": sum(p for k, p in dist.items() if k < 0), "hold": dist.get(0, 0.0), "hike": sum(p for k, p in dist.items() if k > 0),
                    "expected": expected, "check": expected - r["cum"], "dist": dict(sorted(dist.items()))})
    return out


def wirp_buckets(items: List[Dict[str, Any]], least: float = 5e-4) -> List[int]:
    """The rate buckets (grid steps from today) worth a column: every one some meeting gives at least ``least``, and
    today's (the axis reads from where the rate is)."""
    keys = {k for it in items for k, p in it["dist"].items() if p >= least} | {0}
    return list(range(min(keys), max(keys) + 1))


# ---------------------------------------------------------------------------------------------- the inputs
def try_paths(mpc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Every day's TRY path the history computed (``{"days": {day: meta}, "values": [rows]}`` as the quant snapshot
    reads them), the days it does not stand behind left out: ``{day: {"day", "spot", "base" %, "fixing" %, "decision",
    "meetings": [(meeting, level %)]}}``."""
    from .history import UNRELIABLE, day_flag
    days = mpc.get("days") or {}
    by_day: Dict[str, List[Tuple[str, float]]] = {}
    for r in mpc.get("values") or []:
        if _num(r.get("level")) is not None:
            by_day.setdefault(r["day"], []).append((r["meeting"], r["level"] * 100.0))
    out: Dict[str, Dict[str, Any]] = {}
    for day, meta in days.items():
        flag = meta.get("flag")
        if flag is None:
            flag = day_flag(meta)
        if flag in UNRELIABLE or _num(meta.get("base")) is None or not meta.get("spot"):
            continue
        rows = sorted(x for x in by_day.get(day, ()) if x[0] >= meta["spot"])
        if rows:
            out[day] = {"day": day, "spot": meta["spot"], "base": meta["base"] * 100.0, "fixing": _num(meta.get("tlref")),
                        "decision": bool(meta.get("decision")), "meetings": rows}
    return out


def read_engine(svc) -> Dict[str, Any]:
    """Engine thread, short: the FOMC table of the USD workbook (``SOFR_FOMC``), the policy rate and the PPK survey the
    desk types on Masa (``MASA!Q155``, ``Q157:R159``, the survey's month ``S155``) and the meeting periods' rates of
    "MPC OIS" (``OIS_MAIN!B84:D99`` and ``BJ``: values the workbook has already) - nothing the solver computes here."""
    from .xl.model import COLS, parse_a1
    from .xl.values import serial_to_date
    out: Dict[str, Any] = {"usd": None, "policy": None, "survey": [], "survey_month": None, "mpc_ois": []}

    def iso(v: Any) -> Optional[str]:
        return serial_to_date(v).isoformat() if type(v) is float and 20000 < v < 80000 else None

    book = svc.books.get("tto")
    if book is not None and POLICY_CELL[0] in book.model.sheet_index:
        tcalc = svc._calc(None, book)
        si = book.model.sheet_index[POLICY_CELL[0]]

        def tget(sheet: int, ref: str) -> Any:
            return tcalc.get(sheet, *divmod(parse_a1(ref), COLS))

        v = _num(tget(si, POLICY_CELL[1]))
        out["policy"] = v if v is not None and 0.0 < v < 200.0 else None
        for r in range(SURVEY_ROWS[0], SURVEY_ROWS[1] + 1):
            day, rate = iso(tget(si, "Q%d" % r)), _num(tget(si, "R%d" % r))
            if day and rate is not None and 0.0 < rate < 200.0:
                out["survey"].append({"row": r, "meeting": day, "rate": rate})
        out["survey_month"] = iso(tget(si, SURVEY_MONTH))
        if "OIS_MAIN" in book.model.sheet_index:
            so = book.model.sheet_index["OIS_MAIN"]
            for r in range(MPC_OIS_ROWS[0], MPC_OIS_ROWS[1] + 1):
                start, end, mkt = iso(tget(so, "B%d" % r)), iso(tget(so, "C%d" % r)), _num(tget(so, "D%d" % r))
                if start and end and mkt is not None:
                    model = _num(tget(so, "BJ%d" % r))
                    out["mpc_ois"].append({"row": r, "start": start, "end": end, "rate": mkt * 100.0,
                                           "model": model * 100.0 if model is not None else None})
    book = svc.books.get("sofr")
    if book is None or FOMC_SHEET not in book.model.sheet_index:
        return out
    calc = svc._calc(None, book)
    si = book.model.sheet_index[FOMC_SHEET]

    def get(ref: str) -> Any:
        return calc.get(si, *divmod(parse_a1(ref), COLS))

    implied, spot = _num(get("B7")), iso(get("B5"))
    if implied is None or spot is None:
        return out
    meetings = []
    for r in range(FOMC_ROWS[0], FOMC_ROWS[1] + 1):
        day, active, level = iso(get("B%d" % r)), _num(get("D%d" % r)), _num(get("K%d" % r))
        if not day or active != 1.0:
            continue                                                       # held already, or not a decision meeting
        if level is None:
            break                                                          # (a step after a gap would be measured wrongly)
        meetings.append((day, level))
    status = get("B24")
    out["usd"] = {"day": iso(get("B4")), "spot": spot, "base": implied + (_num(get("B16")) or 0.0) / 100.0, "fixing": _num(get("B6")),
                  "upper": _num(get("B8")), "meetings": sorted(meetings), "status": status if isinstance(status, str) else ""}
    return out


def usd_paths(store) -> Dict[str, Dict[str, Any]]:
    """The daily snapshots of the USD path kept in the store."""
    saved = store.get(USD_KEY)
    days = saved.get("days") if isinstance(saved, dict) else None
    out = {}
    for day, x in (days or {}).items():
        try:
            out[day] = {"day": day, "spot": x["spot"], "base": float(x["base"]), "fixing": x.get("fixing"), "upper": x.get("upper"),
                        "meetings": [(m, float(v)) for m, v in x["meetings"]], "decision": False}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def keep_usd(store, path: Dict[str, Any], state: Optional["State"] = None, now: Optional[float] = None) -> bool:
    """Today's USD path into the store's daily snapshots: one entry a day - the last read of the day, written again
    when it changed, at most every ``USD_WRITE_EVERY`` seconds (``state`` remembers the last write).  True: written."""
    day = path.get("day")
    if not day or not path.get("meetings"):
        return False
    entry = {"spot": path["spot"], "base": round(path["base"], 6), "fixing": path.get("fixing"), "upper": path.get("upper"),
             "meetings": [[m, round(v, 6)] for m, v in path["meetings"]]}
    digest = hashlib.sha1(json.dumps([day, entry], sort_keys=True).encode()).hexdigest()       # (a new day is written at once)
    now = time.time() if now is None else now
    if state is not None:
        last_day, last_t, last_digest = state.kept
        if last_digest == digest or (last_day == day and now - last_t < USD_WRITE_EVERY):
            return False
    saved = store.get(USD_KEY)
    days = dict(saved.get("days") or {}) if isinstance(saved, dict) else {}
    entry["at"] = _dt.datetime.fromtimestamp(now).strftime("%H:%M")
    days[day] = entry
    for old in sorted(days)[:-USD_KEEP_DAYS]:
        days.pop(old, None)
    store.put(USD_KEY, {"v": 1, "days": days})
    if state is not None:
        state.kept = (day, now, digest)
    return True


# ---------------------------------------------------------------------------------------------- the state between fits
class State(object):
    """What this module keeps on a quant service between its fit and its minute's refreshes."""

    def __init__(self):
        self.kept: Tuple[Optional[str], float, Optional[str]] = (None, 0.0, None)    # the last USD snapshot written
        self.policy: Optional[float] = None          # MASA!Q155, as last read
        self.usd: Optional[Dict[str, Any]] = None    # the USD path as last read (the engine)
        self.usd_at: Optional[str] = None
        self.engine_ms: Optional[float] = None
        self.fixed: Dict[str, Dict[str, Any]] = {}   # bank -> what its history gave (kink series, calibration, paths)
        self.now: Dict[str, Dict[str, Any]] = {}     # bank -> today's tables
        self.mons: Dict[str, qf.Monitor] = {}        # sid -> this module's monitors
        self.survey: List[Dict[str, Any]] = []       # MASA!Q157:R159 as last read: [{row, meeting, rate}]
        self.survey_month: Optional[str] = None      # MASA!S155
        self.mpc_ois: List[Dict[str, Any]] = []      # OIS_MAIN's MPC OIS periods as last read: [{start, end, rate, model}]
        self.ctx: Optional[qf.Ctx] = None            # the last fit's context (a WIRP line's size, a user's own lines)
        self.wirp_sig: Optional[str] = None          # what the WIRP lines were made of (the survey, the policy rate, the meetings)


_STATES: "weakref.WeakKeyDictionary[Any, State]" = weakref.WeakKeyDictionary()


def state_of(quant: Any) -> State:
    st = _STATES.get(quant)
    if st is None:
        st = _STATES[quant] = State()
    return st


def _read(quant: Any, st: State) -> None:
    """The engine's part (one short call at the lowest priority): the USD path, the policy rate on Masa."""
    t0 = time.perf_counter()
    try:
        svc = quant.svc
        got = svc.et.call_at(svc.et.BACKGROUND, read_engine, svc)
    except Exception:  # noqa: BLE001 - no workbook read is the history's path alone
        got = {"usd": None, "policy": None}
    st.engine_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    st.policy = got.get("policy")
    st.survey = list(got.get("survey") or [])
    st.survey_month = got.get("survey_month")
    st.mpc_ois = list(got.get("mpc_ois") or [])
    if got.get("usd") is not None:
        st.usd = got["usd"]
        st.usd_at = _dt.datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------------------------- one bank
def policy_of(bank: str, cfg: Dict[str, Any], st: State, path: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The policy rate the WIRP's buckets are read in and where it comes from; its spread to the path's base (bp)."""
    rate, source = None, ""
    if bank == "try":
        manual = _num(cfg.get("path_policy")) or 0.0
        if manual > 0.0:
            rate, source = manual, "masa ayarı (elle)"
        elif st.policy is not None:
            rate, source = st.policy, "Masa!Q155 (Politika faizi %)"
    elif path is not None and _num(path.get("upper")) is not None:
        rate, source = path["upper"], "SOFR_FOMC!B8 (FDTR Index, üst bant)"
    spread = None
    if rate is not None and path is not None:
        mid = rate - FED_RANGE / 200.0 if bank == "usd" else rate
        spread = (mid - path["base"]) * 100.0
    return {"rate": rate, "source": source, "spread": spread, "base": path["base"] if path else None,
            "fixing": path.get("fixing") if path else None}


def _bucket(bank: str, k: int, grid: float, policy: Dict[str, Any]) -> Dict[str, Any]:
    rate = policy["rate"]
    out = {"k": k, "change": k * grid, "rate": None if rate is None else rate + k * grid / 100.0}
    if rate is None:
        out["label"] = _s(k * grid) + " bp"
    elif bank == "usd":
        up = (rate + k * grid / 100.0) * 100.0
        out["label"] = "%s–%s" % (_n(up - FED_RANGE), _n(up))
    else:
        out["label"] = ("%.2f" % out["rate"]).replace(".", ",")
    return out


def wirp_table(bank: str, path: Dict[str, Any], hist: Dict[str, Dict[str, Any]], grid: float, policy: Dict[str, Any]) -> Dict[str, Any]:
    """The WIRP of one bank: per meeting, the matrix, and the history of the next meetings."""
    rows = decompose(path, grid)
    items = wirp(rows, grid)
    keys = wirp_buckets(items)
    buckets = [_bucket(bank, k, grid, policy) for k in keys]
    rate = policy["rate"]
    for it in items:
        it["rate"] = None if rate is None else rate + it["cum"] / 100.0
        it["matrix"] = [it["dist"].get(k, 0.0) for k in keys]
        it["dist"] = [{"k": k, "p": p} for k, p in it["dist"].items()]
    # ---- history: the next meetings' distributions some days back, in today's buckets
    now_day = path["day"]
    days = sorted(d for d in hist if d < now_day)
    back = []
    nxt = [r["meeting"] for r in rows[:WIRP_HISTORY]]
    for meeting in nxt:
        for lb, label in LOOKBACKS:
            if lb == 0:
                day, p = now_day, path
            else:
                target = _back(now_day, lb)
                slack = min(5, max(1, lb // 2))                            # a holiday's gap, not another lookback's day
                day = next((d for d in reversed(days) if d <= target and _bdays(d, target) <= slack), None)
                p = hist.get(day) if day else None
            if p is None:
                back.append({"meeting": meeting, "lookback": label, "day": None})
                continue
            prow = decompose(p, grid)
            idx = next((i for i, r in enumerate(prow) if r["meeting"] == meeting), None)
            if idx is None:
                back.append({"meeting": meeting, "lookback": label, "day": day})
                continue
            shift = int(round((p["base"] - path["base"]) * 100.0 / grid))       # the decisions between that day and today
            dist: Dict[int, float] = {shift: 1.0}
            for r in prow[:idx + 1]:
                dist = convolve(dist, r)
            back.append({"meeting": meeting, "lookback": label, "day": day, "step": prow[idx]["step"], "p_lo": prow[idx]["p_lo"],
                         "lo": prow[idx]["lo"], "hi": prow[idx]["hi"], "p_hi": prow[idx]["p_hi"],
                         "cum": shift * grid + prow[idx]["cum"], "rate": None if rate is None else rate + (shift * grid + prow[idx]["cum"]) / 100.0,
                         "dist": [{"k": k, "p": q} for k, q in sorted(dist.items())]})
    hk = sorted({x["k"] for b in back for x in b.get("dist") or () if x["p"] >= 5e-4} | ({0} if back else set()))
    hbuckets = [_bucket(bank, k, grid, policy) for k in (range(hk[0], hk[-1] + 1) if hk else [])]
    for b in back:
        dd = {x["k"]: x["p"] for x in b.get("dist") or ()}
        b["matrix"] = [dd.get(x["k"], 0.0) for x in hbuckets] if b.get("dist") else None
    # ---- the implied steps of the next meetings, day by day (the chart)
    chart_days = [d for d in days if _bdays(d, now_day) <= WIRP_CHART_DAYS] + [now_day]
    series = {m: [] for m in nxt}
    for d in chart_days:
        p = path if d == now_day else hist[d]
        steps = {r["meeting"]: r["step"] for r in decompose(p, grid)}
        for m in nxt:
            series[m].append(steps.get(m))
    return {"rows": items, "buckets": buckets, "check": max((abs(it["check"]) for it in items), default=None),
            "history": back, "history_buckets": hbuckets, "chart": {"days": chart_days, "series": [{"meeting": m, "steps": series[m]} for m in nxt]}}


def bank_fixed(bank: str, paths: Dict[str, Dict[str, Any]], fixings: Dict[str, float], grid: float, today: str) -> Dict[str, Any]:
    """What a bank's history gives (days before today): the kink series, the decisions and the calibration.  The
    decisions: TLREF's fixing of the meeting day does not carry its decision yet; the Fed's upper bound of a snapshot
    taken on the day may."""
    held = sorted({p["meetings"][0][0] for p in paths.values() if p["meetings"] and p["meetings"][0][0] < today})
    decided = decisions_from(fixings, held, grid, 100.0, strict=bank == "usd")
    hist = {d: p for d, p in paths.items() if d < today}
    return {"paths": paths, "kinks": kink_series(paths, grid, today), "decided": decided, "calibration": calibration(hist, decided, grid),
            "fixings": len(fixings), "first": min(paths) if paths else None, "last": max(paths) if paths else None}


def bank_now(bank: str, path: Optional[Dict[str, Any]], fixed: Dict[str, Any], cfg: Dict[str, Any], st: State,
             live: bool) -> Dict[str, Any]:
    """Today's tables of one bank: per meeting, the consecutive pairs, the kinks against their history, the WIRP."""
    info = BANKS[bank]
    grid = float(cfg[info["grid"]])
    out: Dict[str, Any] = {"bank": bank, "label": info["label"], "grid": grid, "ok": False, "live": live}
    if path is None or not path.get("meetings"):
        out["why"] = ("PPK fiyatlama geçmişi yok: tarihçenin toplantı fiyatlama hesabı gerekli (Ayarlar → Tarihçe)" if bank == "try"
                      else "USD çalışma kitabının FOMC tablosu okunamadı (SOFR_FOMC)")
        return out
    rows = decompose(path, grid)
    hist = {d: p for d, p in fixed["paths"].items() if d < path["day"]}
    window = int(cfg.get("lookback") or 250)
    ks = kinks(rows, grid)
    for k in ks:
        pts = [v for _, v in (fixed["kinks"].get(k["meeting"]) or [])][-window:]
        k["n"] = len(pts)
        k["z"] = qm.zscore(k["d"], pts) if len(pts) >= Z_MIN_OBS else None
        k["mean"] = sum(pts) / len(pts) if pts else None
    pol = policy_of(bank, cfg, st, path)
    out.update({"ok": True, "day": path["day"], "spot": path["spot"], "base": path["base"], "fixing": path.get("fixing"),
                "decision": path.get("decision"), "status": path.get("status") or "", "rows": rows[:SHOW_MEETINGS], "meetings": len(rows),
                "pairs": [pair_table(rows, k, grid) for k in range(min(PAIRS, len(rows) - 1))], "kinks": ks,
                "calibration": fixed["calibration"], "policy": pol, "wirp": wirp_table(bank, path, hist, grid, pol)})
    return out


# ---------------------------------------------------------------------------------------------- the signals
def _period(bank: str, meeting: str, nxt: Optional[str]) -> str:
    return "%s %s%s dönemi" % (BANKS[bank]["short"], _tr(meeting), "–" + _tr(nxt) if nxt else "")


def _kink_note(bank: str, k: Dict[str, Any], pair: Optional[Dict[str, Any]]) -> str:
    """The thesis (one sentence), the scenario P&L of the fly and its carry - what a kink signal carries."""
    d = k["d"]
    side = "ucuz → receive" if d > 0 else "pahalı → pay"
    text = ("%s komşu dönemlerin ortalamasına göre %s bp %s (z %s): adımlar eşitlenirse (ikinci fark %s bp → 0) kazandırır." % (
        _period(bank, k["meeting"], k["next"]), _n(abs(d), 1), side, _s(k["z"], 1) if k.get("z") is not None else "—", _s(k["second"], 1)))
    if pair and pair.get("paths"):
        scen = "; ".join("%s (%s/%s) %s bp [%s–%s]" % (p["name"], _n(p["a1"]), _n(p["a2"]), _s(p["fly"], 1), _pct(p["p_min"]), _pct(p["p_max"]))
                         for p in pair["paths"])
        text += " Senaryolar (fly receive, bp / DV01): " + scen + "."
    return text + " Taşıma 0: dönemler ileri başlangıçlı, tarihleri sabit."


def _legs(bank: str, rows: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    """The fly of meeting-dated periods behind kink ``k`` (1-based): +1 the period after meeting k, −½ each neighbour
    (the first one's neighbour before it is the stub up to the first meeting: nearly fixed, left out)."""
    pref = BANKS[bank]["leg"]

    def leg(i: int, w: float) -> Dict[str, Any]:
        m = rows[i]["meeting"]
        nxt = rows[i + 1]["meeting"] if i + 1 < len(rows) else None
        return {"key": pref + m, "name": _period(bank, m, nxt), "weight": w}

    legs = [leg(k - 1, 1.0), leg(k, -0.5)]
    if k >= 2:
        legs.append(leg(k - 2, -0.5))
    return legs


def kink_monitors(ctx: qf.Ctx, bank: str, now: Dict[str, Any], fixed: Dict[str, Any], st: State) -> List[qf.Monitor]:
    mons: List[qf.Monitor] = []
    if not now.get("ok"):
        return mons
    rows = decompose({"base": now["base"], "meetings": [(r["meeting"], r["level"]) for r in now["rows"]]}, now["grid"])
    pairs = {p["first"]: p for p in now["pairs"]}
    marker = "PATH:" + bank.upper()
    for k in now["kinks"]:
        pts = (fixed["kinks"].get(k["meeting"]) or [])
        if len(pts) < KINK_MIN_OBS or k["index"] >= len(rows):
            continue
        sid = "%s:%s:%s" % (FAMILY_KINK, bank.upper(), k["meeting"])

        def calc(live: Dict[str, float], bank=bank, meeting=k["meeting"]) -> Optional[float]:
            cur = next((x for x in (st.now.get(bank) or {}).get("kinks") or () if x["meeting"] == meeting), None)
            return cur["d"] if cur else None

        mon = qf.mr_monitor(ctx, sid, FAMILY_KINK, BANKS[bank]["asset"], "%s (komşu dönemlere karşı)" % _period(bank, k["meeting"], k["next"]),
                            "bp", 1, [d for d, _ in pts], [v for _, v in pts], "bp", _legs(bank, rows, k["index"]), calc,
                            min_share=KINK_MIN_OBS / max(KINK_MIN_OBS, ctx.min_obs()), pkg="rate", carry_up=0.0,
                            info={"inputs": [marker], "bank": bank, "meeting": k["meeting"], "second": k["second"],
                                  "scenarios": (pairs.get(k["meeting"]) or {}).get("paths") or []},
                            note=_kink_note(bank, k, pairs.get(k["meeting"])))
        if mon is not None:
            mons.append(mon)
    return mons


def cal_monitor(ctx: qf.Ctx, bank: str, now: Dict[str, Any], st: State) -> Optional[qf.Monitor]:
    """A bias of the priced bigger move over enough meetings: the next meeting's period towards the outcome the
    market under-prices (a drift signal: target the expected excess, stop the loss if the other outcome comes)."""
    cal = now.get("calibration") or {}
    z, bias = cal.get("z"), cal.get("bias")
    if not now.get("ok") or z is None or bias is None or cal.get("n", 0) < CAL_MIN_MEETINGS or not now.get("rows"):
        return None
    first = now["rows"][0]
    grid = now["grid"]
    toward, away, p_toward = (first["big"], first["small"], first["p_big"]) if bias > 0 else (first["small"], first["big"], 1.0 - first["p_big"])
    if abs(toward - away) < GRID_EPS:
        return None
    score = abs(z) * (1.0 if toward > away else -1.0)
    nxt = now["rows"][1]["meeting"] if len(now["rows"]) > 1 else None
    name = _period(bank, first["meeting"], nxt)
    sid = "%s:%s" % (FAMILY_CAL, bank.upper())

    def calc(live: Dict[str, float], bank=bank) -> Optional[float]:
        rows = (st.now.get(bank) or {}).get("rows") or []
        return rows[0]["cum"] if rows else None

    def quote(live: Dict[str, float], bank=bank, name=name) -> Optional[Dict[str, Any]]:
        # the period as the desk trades it: its meeting-dated OIS's level, the policy rate the path prices for it (%); at
        # a zero gap the path's base (TLREF / SOFR where it starts) - held for the target and the stop: level = base + the
        # move priced, exactly (``decompose``)
        cur = st.now.get(bank) or {}
        if not cur.get("rows") or _num(cur.get("base")) is None:
            return None
        rate = BANKS[bank]["rate"]
        fb = qf.rate_text(cur["base"])
        return {"inst": name, "unit": "%", "digits": qf.RATE_DIGITS, "base": cur["base"], "scale": 0.01,
                "gap": {"name": "fiyatlanan hareket", "of": "patika tabanının", "at": "patika tabanında"},
                "model": "patikanın tabanı (%s %s)" % (rate, fb), "note": "hedef / stop bugünkü patikanın tabanıyla",
                "held": "Hedef ve stop bugünkü patikanın tabanıyla (%s %s): dönemin seviyesi = taban + fiyatlanan hareket; taban "
                        "değişirse onlar da değişir." % (rate, fb)}

    pts = [(d, (p["meetings"][0][1] - p["base"]) * 100.0) for d, p in sorted(now.get("_hist", {}).items())
           if p["meetings"] and p["meetings"][0][0] == first["meeting"]]
    days = [d for d, _ in pts] or [now["day"]]
    values = [v for _, v in pts] or [first["cum"]]
    note = ("Büyük adım %d toplantıda ortalama %s puan %s fiyatlandı (kalibrasyon z %s): sıradaki toplantıda %s bp tarafına yaslan. "
            "Senaryolar (%s, bp / DV01): %s %s, %s %s. Taşıma 0: dönem ileri başlangıçlı." % (
                cal["n"], _n(abs(bias) * 100.0), "düşük" if bias > 0 else "yüksek", _s(z, 1), _n(toward),
                "receive" if toward < away else "pay", _n(toward), _s((1.0 - p_toward) * grid, 1), _n(away), _s(-p_toward * grid, 1)))
    mon = qf.Monitor(sid, FAMILY_CAL, BANKS[bank]["asset"], name + " (kalibrasyon)", "bp", 1, days, values,
                     [{"key": BANKS[bank]["leg"] + first["meeting"], "name": name, "weight": 1.0}], calc, zfn=lambda level, live, score=score: score,
                     follows=True, mode="drift", reward=abs(bias) * grid, risk=p_toward * grid, hold=float(max(1, _bdays(now["day"], first["meeting"]))),
                     regime={"tag": None}, carry_up=0.0, pkg="rate", note=note, quote=quote,
                     series_label="%s: fiyatlanan hareket (patika tabanına göre, bp)" % name,
                     info={"inputs": ["PATH:" + bank.upper()], "bank": bank, "n": cal["n"], "bias": bias, "cal_z": z,
                           "scenarios": [{"outcome": toward, "pnl": (1.0 - p_toward) * grid}, {"outcome": away, "pnl": -p_toward * grid}]})
    mon.zvalues = [None] * len(values)
    return mon


# ---------------------------------------------------------------------------------------------- 6. the WIRP's AL / SAT lines
# The desk (28.11.2026, "C - 2-3-4-5-8-10-12-13-16"): "Quant: PPK anketine (ya da kendi görüşüme) karşı WIRP'ten AL/SAT
# satırları" - a meeting whose implied policy rate (WIRP's "İma faiz %") is at least a quarter of the grid away from the
# survey (MASA!R157:R159, its meeting by MASA!Q157:Q159) - or from what a user typed in the WIRP table's "Beklentim" - is
# a line: the meeting's period (the meeting-dated OIS from its effective day to the next meeting's) received when the
# market prices a higher rate than the survey, paid when a lower; entry its market rate now (MPC OIS's "Piyasa
# (bootstrap)", what Trades values a PPK period at), target its rate if the policy rate after the meeting is the survey's
# (the period's O/N moves by the gap, its rate by the window's sensitivity), stop half the grid against, the expected
# P&L the gap (the survey is an expectation: under it the period earns the gap) at the desk's DV01 (1.000 $).  A PPK
# period is what Trades books: "İşleme al" works.  The survey's lines are everybody's (Sinyaller, the log, the alarms);
# a user's own lines are theirs alone, on the WIRP page.
#: each user's own "Beklentim": {user: {bank: {meeting ISO: policy rate %}}} - by the meeting's date (a roll moves nothing; a
#: corrected date is followed, :func:`align_mine`), kept until ``MINE_KEEP_DAYS`` after the meeting
MINE_KEY = "quant.wirp.mine"
MINE_KEEP_DAYS = 30
#: where a line's expectation comes from: (the word, "…'nin", "…'de", the gap's name, the model's name)
SOURCES = {"anket": ("anket", "anketin", "ankette", "anket farkı", "TCMB WIRP · anket"),
           "mine": ("beklentim", "beklentimin", "beklentimde", "beklenti farkı", "TCMB WIRP · beklentim")}
MATCH_DAYS = 3                                 # a survey date this near a meeting is that meeting (the day typed a day off)
WIRP_BANK = "try"                              # the survey is the TCMB's (and Trades books PPK periods, not FOMC ones)


#: the possessive after a number as it is read (its last word): by its last digit, else by its tens, else "yüz"
_POSS_UNITS = {"1": "i", "2": "si", "3": "ü", "4": "ü", "5": "i", "6": "sı", "7": "si", "8": "i", "9": "u"}
_POSS_TENS = {"1": "u", "2": "si", "3": "u", "4": "ı", "5": "si", "6": "ı", "7": "i", "8": "i", "9": "ı"}


def _share(x: float) -> str:
    """A share of the grid as the desk says it: "dörtte biri", "yarısı", else "%30'u", "%20'si", "%12,5'i"."""
    words = {0.25: "dörtte biri", 0.5: "yarısı", 0.75: "dörtte üçü", 1.0: "tamamı"}
    for k, w in words.items():
        if abs(x - k) < 1e-9:
            return w
    text = _n(x * 100.0, 1)
    whole, _, frac = text.partition(",")
    last = (frac or whole).lstrip("−-")
    if last[-1] != "0":
        suffix = _POSS_UNITS[last[-1]]
    elif len(last) > 1 and last[-2] != "0":
        suffix = _POSS_TENS[last[-2]]
    else:
        suffix = "ü"                                           # (yüz, iki yüz)
    return "%%%s'%s" % (text, suffix)


def _effective(day: str, holidays: set) -> _dt.date:
    """A meeting's effective day: the business day after it (TRY's list) - its period's start, as MPC OIS and Trades."""
    return qf.business_on_or_after(_dt.date.fromisoformat(day) + _dt.timedelta(days=1), holidays)


def window_term(start: _dt.date, end: _dt.date, holidays: set) -> Tuple[int, float]:
    """A window's calendar days and its weekend / holiday term W = Σ g(g − 1)/2 over the gaps g between its business
    days (``ppkcurve.growth``'s: TLREF compounds on business days - a weekend's three days in one step)."""
    w, prev, d = 0.0, start, start + _dt.timedelta(days=1)
    while d <= end:
        if d == end or (d.weekday() < 5 and d not in holidays):
            g = (d - prev).days
            w += g * (g - 1) / 2.0
            prev = d
        d += _dt.timedelta(days=1)
    return (end - start).days, w


def period_of(rows: List[Dict[str, Any]], k: int, mpc_ois: Sequence[Dict[str, Any]], holidays: set) -> Optional[Dict[str, Any]]:
    """The period after the k-th meeting of a WIRP table (its rows: ``meeting``, ``level`` - the path's O/N after it):
    from its effective day to the next meeting's; its rate now - MPC OIS's market rate of the period
    (``mpc_ois``: the row starting on its effective day), else the PPK model's window rate of the path's O/N -, and the
    sensitivity of the window's rate to its O/N (bp a bp: the O/N compounds over the window).  ``None`` for the last
    meeting (no next one: no period)."""
    from . import ppkcurve as pc
    if k + 1 >= len(rows):
        return None
    meeting, nxt = rows[k]["meeting"], rows[k + 1]["meeting"]
    start, end = _effective(meeting, holidays), _effective(nxt, holidays)
    on = _num(rows[k].get("level"))
    days, term = window_term(start, end, holidays)
    if days <= 0:
        return None
    mkt = next((p for p in mpc_ois if p.get("start") and 0 <= (_dt.date.fromisoformat(p["start"]) - start).days <= 4
                and p.get("end") and abs((_dt.date.fromisoformat(p["end"]) - end).days) <= 4), None)
    model = pc.window_rate(on / 100.0, days, term) * 100.0 if on is not None else None
    sens = 1.0
    if on is not None:
        # (bp of the window's rate a bp of its O/N: the O/N compounds over the window - about 1,04 at 35 % over six weeks)
        sens = (pc.window_rate(on / 100.0, days, term) - pc.window_rate((on - 0.01) / 100.0, days, term)) * 1e4
    rate = mkt["rate"] if mkt is not None else model
    if rate is None:
        return None
    return {"meeting": meeting, "next": nxt, "start": start.isoformat(), "end": end.isoformat(), "days": days, "term": term,
            "rate": rate, "source": "MPC OIS piyasa (bootstrap)" if mkt is not None else "PPK modeli (patikanın O/N'ı)",
            "market": mkt["rate"] if mkt is not None else None,
            "model": mkt["model"] if mkt is not None and mkt.get("model") is not None else model, "row": (mkt or {}).get("row"), "on": on,
            "sens": sens}


def survey_of(meetings: Sequence[str], survey: Sequence[Dict[str, Any]], spot: str) -> Dict[str, Dict[str, Any]]:
    """The survey's rows by the WIRP's meetings: a survey date on a meeting (or ``MATCH_DAYS`` from it: the day typed
    a day off) - a meeting already held (before the path's spot) has none."""
    out: Dict[str, Dict[str, Any]] = {}
    for s in survey:
        day = s.get("meeting")
        if not day or day < spot:
            continue
        best = min(meetings, key=lambda m: abs((_dt.date.fromisoformat(m) - _dt.date.fromisoformat(day)).days), default=None)
        if best is not None and abs((_dt.date.fromisoformat(best) - _dt.date.fromisoformat(day)).days) <= MATCH_DAYS and best not in out:
            out[best] = dict(s)
    return out


def attach_wirp(now: Dict[str, Any], st: State, holidays: set) -> None:
    """Today's TCMB WIRP table with the survey beside each meeting (its rate, its date, ima − anket bp) and each
    meeting's period (:func:`period_of`) - what the lines and the page read."""
    w = now.get("wirp") or {}
    rows = w.get("rows") or []
    if not now.get("ok") or not rows:
        return
    spot = now.get("spot") or now.get("day") or ""
    by = survey_of([r["meeting"] for r in rows], st.survey, spot)
    for k, r in enumerate(rows):
        r["period"] = period_of(rows, k, st.mpc_ois, holidays)
        s = by.get(r["meeting"])
        if s is not None:
            r["survey"] = s["rate"]
            r["survey_day"] = s["meeting"]
            r["survey_gap"] = (r["rate"] - s["rate"]) * 100.0 if _num(r.get("rate")) is not None else None
    w["survey"] = {"rows": [dict(s) for s in st.survey], "month": st.survey_month, "cells": "MASA!Q%d:R%d" % SURVEY_ROWS,
                   "matched": len(by)}


def _row(now: Optional[Dict[str, Any]], meeting: str) -> Optional[Dict[str, Any]]:
    return next((r for r in ((now or {}).get("wirp") or {}).get("rows") or () if r["meeting"] == meeting), None)


def _gap_history(st: State, meeting: str, expect: float, grid: float, policy: float, base: float, window: int) -> Tuple[List[str], List[float]]:
    """The gap of a meeting day by day (its implied policy rate in today's terms - today's policy rate, the decisions
    since that day on the grid and that day's cumulative move to the meeting, as WIRP's history reads it - less the
    expectation, bp): the series the card draws."""
    paths = (st.fixed.get(WIRP_BANK) or {}).get("paths") or {}
    today = (st.now.get(WIRP_BANK) or {}).get("day") or ""
    days, vals = [], []
    for d in sorted(paths):
        if d >= today:
            continue
        p = paths[d]
        lv = next((v for m, v in p["meetings"] if m == meeting), None)
        if lv is None:
            continue
        shift = int(round((p["base"] - base) * 100.0 / grid))
        implied = policy + (shift * grid + (lv - p["base"]) * 100.0) / 100.0
        days.append(d)
        vals.append((implied - expect) * 100.0)
    return days[-window:], vals[-window:]


def wirp_monitor(ctx: qf.Ctx, st: State, meeting: str, source: str, expect: float, sid: Optional[str] = None) -> Optional[qf.Monitor]:
    """A meeting's line against an expectation of its policy rate (``source`` "anket" - the survey - or "mine", a
    user's own): its level the gap ima − expectation (bp, live: WIRP's table now), its score the gap in grids (a line
    from ``wirp_min``), the meeting's period received (the market prices more than expected) or paid, told in the
    period's own rate (``quote``); ``None`` without the meeting's period or the policy rate."""
    now = st.now.get(WIRP_BANK) or {}
    row = _row(now, meeting)
    if not now.get("ok") or row is None or not row.get("period") or _num(row.get("rate")) is None:
        return None
    cfg = ctx.cfg
    grid = float(now["grid"])
    per = row["period"]
    word, of, at, gname, model = SOURCES[source]
    name = _period(WIRP_BANK, meeting, per["next"])
    pol = now.get("policy") or {}
    # (the closes before today; the card adds today's level - the monitor's - itself)
    days, vals = _gap_history(st, meeting, expect, grid, float(pol.get("rate") or 0.0), float(now["base"]), int(cfg.get("lookback") or 250))
    gap_now = (row["rate"] - expect) * 100.0
    usd, tl = ctx.dv01_size()
    t = per["days"] / 365.0
    leg = {"key": BANKS[WIRP_BANK]["leg"] + meeting, "name": name, "weight": 1.0, "dv01_usd": usd or None, "dv01": tl,
           "notional": tl / (t / (1.0 + per["rate"] / 100.0 * t) * 1e-4) / 1e6 if tl and t > 0 else None}
    stop_share = float(cfg.get("wirp_stop") or DEFAULTS["wirp_stop"])

    def calc(live: Dict[str, float], meeting=meeting, expect=expect) -> Optional[float]:
        r = _row(st.now.get(WIRP_BANK), meeting)
        return (r["rate"] - expect) * 100.0 if r is not None and _num(r.get("rate")) is not None else None

    def quote(live: Dict[str, float], meeting=meeting, expect=expect) -> Optional[Dict[str, Any]]:
        # the period as the desk trades it: its rate now; at a zero gap the rate it has when the policy rate after the meeting
        # is the expectation (the O/N of the period moves by the gap, its rate by the window's sensitivity) - the map is
        # exact to first order, the market rate held
        r = _row(st.now.get(WIRP_BANK), meeting)
        if r is None or not r.get("period") or _num(r.get("rate")) is None:
            return None
        p = r["period"]
        gap = (r["rate"] - expect) * 100.0
        k = p["sens"] / 100.0
        return {"inst": name, "unit": "%", "digits": qf.RATE_DIGITS, "base": p["rate"] - k * gap, "scale": k,
                "gap": {"name": gname, "of": of, "at": at},
                "model": "dönemin %s faizi (%s)" % (p["source"], qf.rate_text(p["rate"])),
                "note": "hedef: politika faizi %s olursa (%s)" % ("ankete gelirse" if source == "anket" else "beklentine gelirse", qf.rate_text(expect)),
                "held": "Giriş dönemin %s faizi; hedef politika faizi %s (%s) olursa dönemin faizi - O/N'ı fark kadar iner, faizi ×%s "
                        "(O/N dönem boyunca bileşik); stop ızgaranın %s ters. Piyasa faizi değişirse hepsi onunla kayar." % (
                            p["source"], word, qf.rate_text(expect), qf._g(p["sens"], 3), _share(stop_share))}

    def zfn(level: Optional[float], live: Dict[str, float]) -> Optional[float]:
        # (its levels move with the gap: the target the gap closed, the stop the grid's share against, the expectation's
        # mean - under it the period earns the gap)
        if level is None:
            return None
        m.reward, m.risk, m.fcast = abs(level), stop_share * grid, -level
        return level / grid

    if source == "anket":
        cell = next((s["row"] for s in st.survey if s.get("meeting") == row.get("survey_day")), SURVEY_ROWS[0])
        whose = "Anket (Masa'daki PPK · piyasa ima vs anket, MASA!R%d%s):" % (cell, ", %s.%s anketi" % (st.survey_month[5:7], st.survey_month[:4])
                                                                            if st.survey_month else "")
    else:
        whose = "Beklentin (WIRP tablosunda yazdığın, yalnız sende):"
    note = ("%s %s toplantısı sonrası politika faizi %s; WIRP %s fiyatlıyor (ima − %s %s bp). Fark ızgaranın (%s bp) en az %s "
            "olunca satır: piyasa beklenenden yüksek fiyatlıyorsa dönem receive, düşük fiyatlıyorsa pay. Taşıma 0: dönem ileri "
            "başlangıçlı, tarihleri sabit." % (whose, _tr(meeting), qf.rate_text(expect), qf.rate_text(row["rate"]), word, _s(gap_now, 1),
                                                _n(grid), _share(float(cfg.get("wirp_min") or DEFAULTS["wirp_min"]))))
    m = qf.Monitor(sid or "%s:%s:%s" % (FAMILY_WIRP, WIRP_BANK.upper(), meeting) + (":mine" if source == "mine" else ""), FAMILY_WIRP,
                   BANKS[WIRP_BANK]["asset"], name, "bp", 1, days, vals, [leg], calc, zfn=zfn, zvalues=[v / grid for v in vals],
                   entry=float(cfg.get("wirp_min") or DEFAULTS["wirp_min"]), follows=False, mode="drift", pnl=("bp", per["sens"]),
                   hold=float(max(1, _bdays(now["day"], meeting))), regime={"tag": None}, carry_up=0.0, pkg="rate", note=note, quote=quote,
                   score_name="ızgara payı", series_label="%s: ima politika faizi − %s (bp)" % (_tr(meeting), word),
                   info={"inputs": ["PATH:" + WIRP_BANK.upper()], "bank": WIRP_BANK, "meeting": meeting, "source": source, "expect": expect,
                         "model": model, "period": dict(per), "survey_day": row.get("survey_day"), "survey_month": st.survey_month,
                         "size": "%s $ DV01" % qf._th(usd, 0) if usd else None})
    m.finish = lambda sg: _wirp_finish(m, sg, source, expect, grid)
    return m


def _wirp_finish(m: qf.Monitor, sg: Dict[str, Any], source: str, expect: float, grid: float) -> None:
    """make_signal's line in the desk's words (the plan's format): "Receive PPK 10.12–21.01 dönemi · 1.000 $ DV01 · giriş
    %35,761 · hedef %35,610 (anket %35,000) · stop %36,021 · beklenen +745 bin TL · ankete göre" - and its sentence."""
    word = SOURCES[source][0]
    q = sg.get("quote") or {}
    mo = sg.get("money") or {}
    info = sg.get("info") or {}
    per = info.get("period") or {}
    size = info.get("size") or ""
    f = lambda v: qf.rate_text(v) if v is not None else "—"                       # noqa: E731
    head = "%s · %s" % (sg["expression"], size) if size else sg["expression"]
    rr = sg.get("rr")
    parts = [head, "giriş " + f(q.get("entry")), "hedef %s (%s %s)" % (f(q.get("target")), word, qf.rate_text(expect)),
             "stop " + f(q.get("stop")), "beklenen " + qf._money(mo.get("total"), "TL"), "%s göre" % ("ankete" if source == "anket" else "beklentime")]
    sg["line"] = " · ".join(parts)
    sg["trade_line"] = head
    gap = float(sg.get("level") or 0.0)
    side = "receive" if sg["direction"] < 0 else "pay"
    comes = "ankete gelirse" if source == "anket" else "beklentine gelirse"
    implied = qf.rate_text(expect + gap / 100.0)
    why = "%s toplantısı sonrası piyasa politika faizini %s fiyatlıyor, %s %s: fark %s bp (eşik ızgaranın %s, %s bp)." % (
        _tr(info.get("meeting") or ""), implied, word, qf.rate_text(expect), _s(gap, 1), _share(float(m.entry or 0.0)),
        _n(float(m.entry or 0.0) * grid, 1))
    what = "%s dönemini %s et: giriş %s (%s), hedef %s (politika faizi %s), stop %s (ızgaranın %s, %s bp ters)." % (
        m.name.replace(" dönemi", ""), side, f(q.get("entry")), per.get("source") or "", f(q.get("target")), comes, f(q.get("stop")),
        _share(float(m.risk or 0.0) / grid), _n(float(m.risk or 0.0), 1))
    money = "%s ile %s %s, stopta %s%s; toplantıya %s iş günü. Taşıma 0: dönem ileri başlangıçlı." % (
        size or "masanın DV01'i", comes, qf._money(mo.get("target"), "TL"), qf._money(mo.get("stop"), "TL"),
        (" (ödül / risk %s)" % qf._g(rr, 2)) if rr is not None else "", qf._g(sg.get("hold"), 0))
    sg["plain"] = " ".join([why, what, money])
    sg["thesis"] = "TCMB WIRP · %s: %s" % ("ankete göre" if source == "anket" else "beklentime göre", sg["line"])
    if source == "mine":
        sg["personal"] = True                                  # (a user's own: their WIRP page alone - no log, no alarm)


def wirp_monitors(ctx: qf.Ctx, st: State) -> List[qf.Monitor]:
    """The survey's lines: a monitor for every meeting the survey names (a line when its gap is past the threshold)."""
    out = []
    for r in ((st.now.get(WIRP_BANK) or {}).get("wirp") or {}).get("rows") or ():
        if _num(r.get("survey")) is None:
            continue
        m = wirp_monitor(ctx, st, r["meeting"], "anket", float(r["survey"]))
        if m is not None:
            out.append(m)
    return out


def _wirp_sig(st: State) -> str:
    """What the survey's lines are made of: the meetings, the survey, the policy rate (the minute's refresh makes them
    again when one moved - the survey typed on Masa during the day)."""
    now = st.now.get(WIRP_BANK) or {}
    return json.dumps([[r["meeting"] for r in (now.get("wirp") or {}).get("rows") or ()], st.survey, st.policy,
                       sorted(p.get("start") or "" for p in st.mpc_ois)], sort_keys=True, default=str)


# ---- each user's own expectation
def _rate_in(v: Any) -> Optional[float]:
    """A typed policy rate (%): "35", "35,25", "%35.25" - ``None`` for an empty box; ValueError for anything else."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
    else:
        text = str(v).strip().replace("%", "").replace(" ", "").replace(",", ".")
        if not text:
            return None
        try:
            x = float(text)
        except ValueError:
            raise ValueError("politika faizi bir sayı olmalı (örn. 35,25): %s" % str(v)[:20])
    if not (math.isfinite(x) and 0.0 < x < 200.0):
        raise ValueError("politika faizi %0 – %200 arasında bir sayı olmalı")
    return x


def mine_of(store: Any, user: str) -> Dict[str, Dict[str, float]]:
    """A user's typed expectations: {bank: {meeting ISO: rate %}}."""
    saved = store.get(MINE_KEY)
    mine = saved.get(user) if isinstance(saved, dict) else None
    return {b: dict(v) for b, v in (mine or {}).items() if isinstance(v, dict)}


def set_mine(store: Any, user: str, bank: str, meeting: str, rate: Any, today: str) -> Dict[str, Dict[str, float]]:
    """A user's expectation of the policy rate after a meeting typed (``rate`` empty: taken back); the ones past their
    meeting by more than ``MINE_KEEP_DAYS`` dropped."""
    if bank not in BANKS:
        raise ValueError("bilinmeyen banka: %s" % str(bank)[:20])
    try:
        _dt.date.fromisoformat(str(meeting))
    except ValueError:
        raise ValueError("toplantı tarihi anlaşılamadı: %s" % str(meeting)[:20])
    x = _rate_in(rate)
    saved = store.get(MINE_KEY)
    saved = saved if isinstance(saved, dict) else {}
    mine = saved.setdefault(user, {})
    b = mine.setdefault(bank, {})
    if x is None:
        b.pop(str(meeting), None)
    else:
        b[str(meeting)] = round(x, 6)
    floor = (_dt.date.fromisoformat(today) - _dt.timedelta(days=MINE_KEEP_DAYS)).isoformat()
    for k in [k for k in b if k < floor]:
        b.pop(k, None)
    store.put(MINE_KEY, saved)
    return mine_of(store, user)


def align_mine(mine: Dict[str, float], meetings: Sequence[str]) -> Dict[str, Tuple[float, str]]:
    """A user's expectations on today's meetings: {meeting: (rate, the date it was typed for)} - by date; a typed date
    no meeting has any more follows the meeting whose date was corrected (``history.align_meetings``: the same meeting
    within 45 days, between the dates both lists have) - a meeting already held is never paired with the next one."""
    from .history import align_meetings
    out = {m: (mine[m], m) for m in meetings if m in mine}
    first = min(meetings) if meetings else None
    gone = sorted(d for d in mine if d not in out and first is not None and d >= first)
    if gone:
        old = sorted(set(gone) | set(out))
        al = align_meetings(old, list(meetings))
        for i, d in enumerate(old):
            j = al.get(i)
            if d in gone and j is not None and meetings[j] not in out:
                out[meetings[j]] = (mine[d], d)
    return out


def mine_lines(quant: Any, fit: Dict[str, Any], user: str, aligned: Dict[str, Tuple[float, str]]) -> List[Dict[str, Any]]:
    """A user's own lines now: their typed expectation against WIRP, made and scored as the survey's (never in the
    desk's list, the log or the alarms)."""
    from . import quantlevels as qlv
    from . import quantuniv as qu
    st = state_of(quant)
    ctx = fit.get("ctx") or st.ctx
    if ctx is None:
        return []
    stamp = _dt.datetime.now().strftime("%H:%M")
    out = []
    for meeting, (rate, _) in sorted(aligned.items()):
        m = wirp_monitor(ctx, st, meeting, "mine", rate)
        if m is None:
            continue
        m.levels = {"ok": False, "own": True, "family": FAMILY_WIRP, "why": qlv.KEEP.get(FAMILY_WIRP, "")}
        m.score(ctx.live or {}, {})
        sg = qf.make_signal(m, fit["cfg"], stamp)
        if sg is not None:
            sg["day"] = fit.get("today")
            qu.classify(sg)
            out.append(sg)
    return out


def mine_monitor(quant: Any, user: str, sid: str) -> Optional[qf.Monitor]:
    """A user's own line's monitor by its id ("wirp:TRY:<meeting>:mine"), scored now - its card."""
    from . import quantlevels as qlv
    parts = str(sid or "").split(":")
    if len(parts) != 4 or parts[0] != FAMILY_WIRP or parts[3] != "mine":
        return None
    st = state_of(quant)
    now = st.now.get(WIRP_BANK) or {}
    aligned = align_mine(mine_of(quant.store, user).get(WIRP_BANK) or {}, [r["meeting"] for r in (now.get("wirp") or {}).get("rows") or ()])
    hit = aligned.get(parts[2])
    if hit is None or st.ctx is None:
        return None
    m = wirp_monitor(st.ctx, st, parts[2], "mine", hit[0])
    if m is None:
        return None
    m.levels = {"ok": False, "own": True, "family": FAMILY_WIRP, "why": qlv.KEEP.get(FAMILY_WIRP, "")}
    m.score(st.ctx.live or {}, {})
    return m


# ---------------------------------------------------------------------------------------------- the quant worker's part
def _fixings_try(ctx: qf.Ctx) -> Dict[str, float]:
    return dict(ctx.series.get("TLREF") or {})


def _fixings_usd(paths: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    return {d: p["upper"] for d, p in paths.items() if _num(p.get("upper")) is not None}


def _build(quant: Any, ctx: qf.Ctx, st: State, refit: bool) -> None:
    """Both banks' tables from the state's inputs (with ``refit`` also what their history gives)."""
    cfg = ctx.cfg
    today = ctx.today_iso
    if refit:
        tp = try_paths(ctx.mpc or {})
        st.fixed["try"] = bank_fixed("try", tp, _fixings_try(ctx), float(cfg["path_grid_try"]), today)
    up = usd_paths(quant.store)
    if st.usd is not None and st.usd.get("day"):
        up[st.usd["day"]] = dict(st.usd, decision=False)
    if refit or "usd" not in st.fixed:
        st.fixed["usd"] = bank_fixed("usd", up, _fixings_usd(up), float(cfg["path_grid_usd"]), today)
    else:
        st.fixed["usd"]["paths"] = up
    use_live = getattr(quant, "use_live", True)
    for bank in BANKS:
        fixed = st.fixed[bank]
        paths = fixed["paths"]
        last = max(paths) if paths else None
        path = paths.get(last) if last else None
        live = bool(use_live and path is not None and (bank == "usd" and st.usd is not None or path["day"] >= today))
        now = bank_now(bank, path, fixed, cfg, st, live)
        now["_hist"] = {d: p for d, p in paths.items() if d < (path or {}).get("day", today)}
        if bank == WIRP_BANK:
            attach_wirp(now, st, ctx.holidays)                 # (the survey beside each meeting, each meeting's period)
        st.now[bank] = now
    st.ctx = ctx


def _publish_tables(quant: Any, ctx: qf.Ctx, st: State, tables: Dict[str, Any], raw_live: Dict[str, float]) -> None:
    banks = {b: {k: v for k, v in st.now[b].items() if k not in ("wirp", "_hist")} for b in BANKS}
    wirps = {}
    for b in BANKS:
        n = st.now[b]
        w = dict(n.get("wirp") or {})
        w.update({"bank": b, "label": n["label"], "ok": n.get("ok"), "why": n.get("why"), "grid": n["grid"], "day": n.get("day"),
                  "policy": n.get("policy"), "base": n.get("base"), "live": n.get("live")})
        wirps[b] = w
    usd = st.fixed["usd"]
    tr = st.fixed["try"]
    coverage = [
        {"key": "mpc", "label": "PPK fiyatlama geçmişi (tarihçe)", "group": "TCMB", "ticker": "mpc_days / mpc_values", "n": len(tr["paths"]),
         "first": tr["first"], "last": tr["last"], "live": banks["try"].get("live"), "state": "var" if tr["paths"] else "geçmiş yok"},
        {"key": "TLREF", "label": "TLREF fixingleri (kararlar)", "group": "TCMB", "ticker": "BISTTREF Index", "n": tr["fixings"],
         "first": min(_fixings_try(ctx)) if tr["fixings"] else None, "last": max(_fixings_try(ctx)) if tr["fixings"] else None,
         "live": False, "state": "var" if tr["fixings"] else "geçmiş yok"},
        {"key": "usd", "label": "USD ima patikası (günlük anlık görüntü)", "group": "Fed", "ticker": "SOFR_FOMC · " + USD_KEY,
         "n": len(usd["paths"]), "first": usd["first"], "last": usd["last"], "live": banks["usd"].get("live"),
         "state": "var" if len(usd["paths"]) > 1 else ("birikiyor" if usd["paths"] else "geçmiş yok")},
    ]
    common = {"today": ctx.today_iso, "engine_ms": st.engine_ms, "usd_at": st.usd_at, "coverage": coverage,
              "settings": {k: ctx.cfg.get(k) for k in DEFAULTS}}
    tables["imapath"] = dict(common, banks=banks)
    tables["wirp"] = dict(common, banks=wirps)
    for b in BANKS:
        if banks[b].get("live"):
            raw_live["PATH:" + b.upper()] = 1.0


def run(quant: Any, ctx: qf.Ctx, mons: List[qf.Monitor], tables: Dict[str, Any], raw_live: Dict[str, float],
        timing: Optional[Dict[str, float]] = None) -> None:
    """The full fit's part (``Quant.compute``, the quant worker's thread): the engine's short read, today's USD
    snapshot, both banks' history and today's tables (``tables["imapath"]`` and ``tables["wirp"]``), the monitors.
    Never raises: a failure is the fit's error ``imapath`` and the other families stand."""
    t0 = time.perf_counter()
    st = state_of(quant)
    try:
        _read(quant, st)
        if st.usd is not None:
            keep_usd(quant.store, st.usd, st)
        _build(quant, ctx, st, refit=True)
        own: List[qf.Monitor] = []
        for bank in BANKS:
            own.extend(kink_monitors(ctx, bank, st.now[bank], st.fixed[bank], st))
            m = cal_monitor(ctx, bank, st.now[bank], st)
            if m is not None:
                own.append(m)
        own.extend(wirp_monitors(ctx, st))                     # the WIRP's lines against the survey (C16, 28.11.2026)
        st.wirp_sig = _wirp_sig(st)
        st.mons = {m.sid: m for m in own}
        mons.extend(own)
        _publish_tables(quant, ctx, st, tables, raw_live)
    except Exception as exc:  # noqa: BLE001 - this module failing must not take the other families with it
        tables.setdefault("errors", {})["imapath"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        tables["imapath"] = {"banks": {}, "why": tables["errors"]["imapath"], "coverage": []}
        tables["wirp"] = {"banks": {}, "why": tables["errors"]["imapath"], "coverage": []}
    if timing is not None:
        timing["imapath"] = time.perf_counter() - t0


def refresh(quant: Any, fit: Dict[str, Any], raw_live: Dict[str, float]) -> None:
    """The minute's live refresh (``Quant.refresh_live``): the USD path and the policy rate read again, today's USD
    snapshot, today's tables of both banks again; the monitors' notes follow."""
    st = state_of(quant)
    if not st.fixed or "try" not in st.fixed:
        return
    ctx: qf.Ctx = fit["ctx"]
    tables = fit["tables"]
    try:
        _read(quant, st)
        if st.usd is not None:
            keep_usd(quant.store, st.usd, st)
        _build(quant, ctx, st, refit=False)
        for m in st.mons.values():
            bank = m.info.get("bank")
            now = st.now.get(bank) or {}
            if m.family == FAMILY_KINK:
                k = next((x for x in now.get("kinks") or () if x["meeting"] == m.info.get("meeting")), None)
                pair = next((p for p in now.get("pairs") or () if p["first"] == m.info.get("meeting")), None)
                if k is not None:
                    m.note = _kink_note(bank, k, pair)
                    m.info["scenarios"] = (pair or {}).get("paths") or []
        # the survey's lines made again when what they are made of moved (the survey typed on Masa, the policy rate, the
        # meetings): the fit's monitors are this module's again (the next publish sets their levels, scores them)
        sig = _wirp_sig(st)
        if sig != st.wirp_sig:
            for sid in [s for s, m in fit["mons"].items() if m.family == FAMILY_WIRP]:
                del fit["mons"][sid]
                st.mons.pop(sid, None)
            fresh = wirp_monitors(ctx, st)
            fit["mons"].update({m.sid: m for m in fresh})
            st.mons.update({m.sid: m for m in fresh})
            st.wirp_sig = sig
        _publish_tables(quant, ctx, st, tables, raw_live)
        (tables.get("errors") or {}).pop("imapath", None)
    except Exception as exc:  # noqa: BLE001 - the last fit's tables stand
        tables.setdefault("errors", {})["imapath"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])


def view(quant: Any, what: str, base: Dict[str, Any], v: Dict[str, Any], fit: Dict[str, Any], user: Optional[str] = None) -> Dict[str, Any]:
    """What the pages "İma Patikası" (``path``) and "TCMB WIRP" (``wirp``) read: the published tables, the kinks'
    z of their monitors now, this page's signals, the settings, the coverage and the mode (a note in replay) - on WIRP
    for ``user`` also their own "Beklentim" beside each meeting (its gap) and their own lines after the survey's."""
    from .quant import _clean
    name = "imapath" if what == "path" else "wirp"
    tab = copy.deepcopy((v.get("tables") or {}).get(name) or {})
    if name == "imapath":
        for b in (tab.get("banks") or {}).values():
            for k in b.get("kinks") or ():
                m = fit["mons"].get("%s:%s:%s" % (FAMILY_KINK, str(b.get("bank", "")).upper(), k["meeting"]))
                if m is not None:
                    k["sid"] = m.sid
                    k["z"] = m.z
                    k["half_life"] = m.half_life
    page = VIEWS[what]
    base[what] = tab
    base["signals"] = [s for s in v["signals"] + v["gated"] if s["page"] == page]
    if name == "wirp":
        bk = (tab.get("banks") or {}).get(WIRP_BANK) or {}
        for r in bk.get("rows") or ():
            m = fit["mons"].get("%s:%s:%s" % (FAMILY_WIRP, WIRP_BANK.upper(), r["meeting"]))
            if m is not None:
                r["sid"] = m.sid                               # (a row with a survey line: its card)
        if user and bk.get("ok"):
            aligned = align_mine(mine_of(quant.store, user).get(WIRP_BANK) or {}, [r["meeting"] for r in bk.get("rows") or ()])
            for r in bk.get("rows") or ():
                hit = aligned.get(r["meeting"])
                if hit is not None:
                    r["mine"], r["mine_day"] = hit
                    r["mine_gap"] = (r["rate"] - hit[0]) * 100.0 if _num(r.get("rate")) is not None else None
                    r["mine_sid"] = "%s:%s:%s:mine" % (FAMILY_WIRP, WIRP_BANK.upper(), r["meeting"])
            try:
                base["signals"] = base["signals"] + mine_lines(quant, fit, user, aligned)
            except Exception as exc:  # noqa: BLE001 - a user's own lines are not worth the page
                base.setdefault("errors", {})["beklentim"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    base["settings"] = fit["cfg"]
    base["coverage"] = tab.get("coverage") or []
    base["errors"] = dict({k: e for k, e in ((v.get("tables") or {}).get("errors") or {}).items() if k == "imapath"}, **(base.get("errors") or {}))
    base["mode"] = getattr(quant.svc, "mode", "")
    return _clean(base)


def act_mine(quant: Any, user: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """``POST /api/quant/wirp-mine`` {bank, meeting, rate}: a user's expectation typed (an empty rate takes it back) -
    their WIRP page answered again with it."""
    from . import tradequant as tq
    today = (getattr(quant, "_fit", None) or {}).get("today") or _dt.date.today().isoformat()
    set_mine(quant.store, user, str(data.get("bank") or WIRP_BANK), str(data.get("meeting") or ""), data.get("rate"), today)
    return tq.mark(quant.view("wirp", user, {}))              # (every line says whether Trades can book it, as a GET's)


def book_mine(quant: Any, user: str, line_id: str, scope: str = "personal", lang: str = "tr") -> Dict[str, Any]:
    """"İşleme al" for a user's own line - Trades' form of it, as ``tradequant.prefill`` makes it for the desk's lines
    (which it finds in the desk's list: a user's own line is in none) - the line made again here, now, from the user's
    own expectation (never what a page sent)."""
    from . import tradequant as tq
    from .service import ServiceError
    from .tradebook import describe
    m = mine_monitor(quant, user, line_id)
    fit = getattr(quant, "_fit", None)
    sg = qf.make_signal(m, fit["cfg"], _dt.datetime.now().strftime("%H:%M")) if m is not None and fit else None
    if sg is None:
        raise ServiceError("sinyal yok (beklentin ile ima arasındaki fark eşiğin altında ya da beklenti silinmiş): %s" % str(line_id)[:80], 404)
    ok, why, kind = tq.bookable(sg)
    if not ok:
        raise ServiceError("bu sinyal Trades'e alınamaz: %s" % why)
    book = quant.svc.tradebook
    user = book._user(user)
    scope = book._scope(scope or "personal")
    raw, source = tq.raw_form(book, user, sg, scope, kind)
    t, f = book.normalize(raw, lang)
    trade = t if not f.errors else dict(raw, **{k: v for k, v in t.items() if v is not None})
    trade.pop("scope", None)
    return {"ok": not f.errors, "trade": trade, "fields": f.errors, "text": describe(t, "PPK") if not f.errors else "", "source": source,
            "scope": scope, "kind": kind, "line": {"id": sg.get("id"), "family": sg.get("family"), "family_label": sg.get("family_label"),
                                                   "text": sg.get("line") or sg.get("expression") or "", "instrument": sg.get("instrument")}}
