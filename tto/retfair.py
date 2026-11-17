"""Fair value RET ("adil RET"): a rule-based TRY RET curve the desk publishes from, beside the RET it publishes today.

Every RET tenor has its own row, keyed by its label ("1M") - never by a row of the RET table:

* **Taban** (base): OIS mid, VİOP mid or offshore mid - or a blend of them with weights chosen with it;
* **Tabana spread** (offset, bp): the trader's, per tenor or for many at once;
* **Akış ayarı** (flow adjustment, bp): a flow suggestion someone accepted - shown apart from the offset, kept until it
  is removed (``retflow.suggest``);
* **Genişlik** (bid–ask width, bp, a multiple of 5): changed in "Ekstra ayarlar" only (administrators);
* **Tabana göre** (anchor): which quote base + offset + flow sets - the **Mid** (the default), the **Bid** or the **Ask**.

Mid: RET mid = base + offset + flow, the bid put on the 5 bp grid from mid − width / 2, ask = bid + width.  Bid: the bid
= base + offset + flow on the grid, ask = bid + width.  Ask: the ask = base + offset + flow on the grid, bid = ask −
width.  The value shown ("Şimdiki") follows the raw one with a hysteresis on the anchored side (the bid for Mid, as
before): it moves only when that raw value has crossed a rounding step (2.5 bp off the shown one) by more than
``hysteresis`` bp (2) - a base moving 3 bp across a step moves it, 1 bp does not, back and forth does not make it flap.
A person's change (an offset, a base, an anchor, a width, a flow adjustment) moves it at once.  "Yayınlanan" is the
desk's RET as it is (the shared RET cells, Forward!W:X, however they were written); "Kopyala ve yayınla" writes the
shown curve there - with the RET's history and its "loaded today" mark - so everything that reads the RET follows.

**Senaryo** (each user's own view, remembered): "Piyasa" - the market bases above, the desk's Şimdiki - or one of the
OIS sheet's three PPK scenarios, evaluated in the user's own calculation (their steps and names; ``extras.RETS_SHEET``):
the OIS base is the scenario curve's rate between the tenor's two dates (Masa's "Tarih arası faiz" with those dates),
the VİOP and offshore bases move by (scenario − reference) - the reference being a scenario without steps on the
implied path - and a blend takes each part's scenario value.  A scenario view has no hysteresis: its raw values are put
on the grid as they are (the same inputs give the same numbers); the desk's settings stay the desk's.

**Day count** is the RET's own: simple ACT/360 from the USDTRY spot date (Forward!I2) over the RET table's days
(Forward!U33:U47) - how the Forward sheet prices from it (Forward!D33: spot·(1 + RET·g/360)/(1 + USD·g/360), the RET
read at g in a straight line between its tenors, W48 / X48).  ON runs from the spot − its days to the spot, every other
tenor from the spot.  Each base is a rate over those same two dates:

* **OIS mid / offshore mid**: the TRY workbook's OIS and offshore mid zero curves between them, simple ACT/360 - the
  Borsa Swap spreads' machinery (``borsaspread.read_curves`` / ``Curve.zero``: ln DF linear in days, a day before a
  curve's spot carried with its O/N - TLREF 365 → 360, the offshore O/N mid);
* **VİOP mid**: the VİOP sheet's implied TRY rate of each listed contract - ((price / spot)(1 + USD·g/360) − 1)·360/g at
  its bid and at its ask, g = its expiry − the USDTRY spot (rows 13 and 25, read as the VİOP page reads them:
  ``quantviop.read_engine``) - the mid of the two, read at the tenor's end date in a straight line (in days) between the
  two contracts whose expiries are around it.  Before the first expiry or after the last there is none (no
  extrapolation): the short tenors usually have no VİOP base.

No Bloomberg request of its own: everything is read from the workbook as the desk's calculation has it (nobody's
personal inputs).  The settings are the desk's (shared); every change is written to a log with who and when.
"""
from __future__ import annotations

import datetime as _dt
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import borsaspread as bsp
from . import extras as ex
from . import retflow as rf
from .xl.model import COLS, parse_a1
from .xl.tokenizer import col_to_index
from .xl.values import date_to_serial, serial_to_date

BASES = ("ois", "viop", "off")
BASE_NAMES = {"ois": "OIS mid", "viop": "VİOP mid", "off": "offshore mid", "blend": "karma"}
SHORT = {"ois": "OIS", "viop": "VİOP", "off": "Offshore"}
CHOICES = BASES + ("blend",)
#: which quote base + offset + flow sets ("Tabana göre"): the mid (the default), the bid or the ask
ANCHORS = ("mid", "bid", "ask")
ANCHOR_NAMES = {"mid": "Mid", "bid": "Bid", "ask": "Ask"}
#: the views of the fair value ("Senaryo"): the market, or a PPK scenario of the OIS sheet by its code
MARKET = "piyasa"
SCENARIOS = tuple(code for code, _, _, _, _, _ in ex.RETS_SCENARIOS)
GRID = 5.0                                   # bp: the RET's step
#: the administrators' settings and their defaults: hysteresis (bp), flow sensitivity (bp per 100 mn USD of today's net
#: above its normal), lookback (business days), minimum margin over cost (bp), the blend's default weights (%)
DEFAULTS: Dict[str, Any] = {"hysteresis": 2.0, "sensitivity": 5.0, "lookback": 10, "margin": 5.0,
                            "blend": {"ois": 50.0, "viop": 25.0, "off": 25.0}}
LIMITS: Dict[str, Tuple[float, float, type]] = {"hysteresis": (0.0, 10.0, float), "sensitivity": (0.0, 1000.0, float),
                                                 "lookback": (1, 60, int), "margin": (0.0, 500.0, float)}
LABELS = {"hysteresis": "histerezis", "sensitivity": "akış hassasiyeti", "lookback": "geriye bakış", "margin": "asgari marj"}
WIDTH_MAX = 1000
DEFAULT_WIDTH = 20                           # bp: a tenor whose published RET has no width to start from
OFFSET_MAX = 5000.0                          # bp either way
SUMMARY_EVERY = 10.0                         # s: how old the header's "RET güncellemesi var" may get before it is made again
LOG_LIMIT = 40


# ---------------------------------------------------------------------------------------------- the numbers
def grid_round(bp: float) -> float:
    """A rate in bp on the 5 bp grid, a half up (34,275 % → 34,30 %)."""
    return GRID * math.floor(round(bp, 6) / GRID + 0.5)


def next_shown(raw_bp: float, prev_bp: Optional[float], hysteresis: float) -> float:
    """The bid shown (bp, on the grid) for the raw bid ``raw_bp``, after ``prev_bp`` was shown: it stays until the raw
    bid is more than half a step + ``hysteresis`` away from it, then it is the raw one rounded."""
    plain = grid_round(raw_bp)
    if prev_bp is None or abs(raw_bp - prev_bp) > GRID / 2.0 + max(0.0, hysteresis) + 1e-9:
        return plain
    return float(prev_bp)


def raw_bid_of(anchor: str, raw_bp: float, width: float) -> float:
    """The raw bid (bp) of a tenor whose rule gives ``raw_bp`` for its anchored side: the mid less half the width, the
    bid itself, or the ask less the width."""
    if anchor == "bid":
        return raw_bp
    if anchor == "ask":
        return raw_bp - width
    return raw_bp - width / 2.0


def quote(anchor: str, raw_bp: float, width: float, prev_bid: Optional[float], hysteresis: float) -> float:
    """The bid shown (bp, on the grid) of a tenor whose rule gives ``raw_bp`` for its anchored side, after ``prev_bid``
    was shown: the hysteresis works on the anchored side - the bid for Mid (as it always did) and Bid, the ask for Ask
    (the bid = the ask shown − the width)."""
    if anchor == "ask":
        prev = prev_bid + width if prev_bid is not None else None
        return next_shown(raw_bp, prev, hysteresis) - width
    return next_shown(raw_bid_of(anchor, raw_bp, width), prev_bid, hysteresis)


def grid_bid(anchor: str, raw_bp: float, width: float) -> float:
    """The bid (bp) of a raw anchored value on the grid, without a hysteresis."""
    if anchor == "ask":
        return grid_round(raw_bp) - width
    return grid_round(raw_bid_of(anchor, raw_bp, width))


def interp_dates(points: Sequence[Tuple[float, float]], day: float) -> Optional[float]:
    """A rate at ``day`` (serial) from rates at dates ``[(serial, rate)]``: in a straight line between the two dates
    around it; ``None`` before the first or after the last."""
    pts = sorted((d, r) for d, r in points if type(d) is float and type(r) is float)
    if not pts or day < pts[0][0] - 1e-9 or day > pts[-1][0] + 1e-9:
        return None
    if day <= pts[0][0] + 1e-9:
        return pts[0][1]
    for (d0, r0), (d1, r1) in zip(pts, pts[1:]):
        if day <= d1 + 1e-9:
            return r1 if d1 <= d0 else r0 + (r1 - r0) * (day - d0) / (d1 - d0)
    return pts[-1][1]


def blend_mid(mids: Dict[str, Optional[float]], weights: Dict[str, Any]) -> Tuple[Optional[float], str]:
    """The weighted average of the bases with a weight above 0 (the weights need not add up to 100) - none when one of
    them has no rate (and why)."""
    used = [(b, float(weights.get(b) or 0.0)) for b in BASES if float(weights.get(b) or 0.0) > 0.0]
    if not used:
        return None, "karma: ağırlık yok"
    missing = [BASE_NAMES[b] for b, _ in used if mids.get(b) is None]
    if missing:
        return None, "karma: %s yok" % ", ".join(missing)
    total = sum(w for _, w in used)
    return sum(mids[b] * w for b, w in used) / total, ""


def tenor_dates(label: str, days: float, spot: float) -> Tuple[float, float]:
    """The two dates of a RET tenor (serials): ON from the spot − its days to the spot, every other one from the spot."""
    if label == "ON":
        return spot - days, spot
    return spot, spot + days


def weights_text(w: Dict[str, Any]) -> str:
    return " · ".join("%s %s" % (SHORT[b], ("%g" % float(w.get(b) or 0)).replace(".", ","))
                      for b in BASES if float(w.get(b) or 0) > 0)


def _bp(x: float) -> str:
    return ("%g" % round(x, 1)).replace(".", ",")


def formula_text(base: str, weights: Optional[Dict[str, Any]], offset: Optional[float], flow: float,
                 anchor: str = "mid") -> str:
    """How the RET is made, as the desk reads it: "OIS mid − 60 + 5 (akış)" (the mid), "Bid = OIS mid − 60 + 5 (akış)"
    (the bid set from the base), "Ask = …"."""
    name = BASE_NAMES.get(base, base) if base != "blend" else "karma (%s)" % weights_text(weights or {})
    text = name[0].upper() + name[1:]
    if anchor in ("bid", "ask"):
        text = "%s = %s" % (ANCHOR_NAMES[anchor], text)
    if offset is None:
        return text + " + ? (tabana spread yok)"
    if offset:
        text += " %s %s" % ("+" if offset > 0 else "−", _bp(abs(offset)))
    if flow:
        text += " %s %s (akış)" % ("+" if flow > 0 else "−", _bp(abs(flow)))
    return text


# ---------------------------------------------------------------------------------------------- the market
class Market(object):
    """What the fair value reads of the workbook: the USDTRY spot date (serial), the RET tenors (``label``, ``row``,
    ``days``, the published ``bid`` / ``ask`` as fractions), the OIS and offshore mid curves, the VİOP mids at their
    expiries (``[(serial, fraction, name)]``)."""

    __slots__ = ("spot", "tenors", "curves", "viop", "viop_why")

    def __init__(self, spot: Optional[float], tenors: List[Dict[str, Any]], curves: Dict[str, Any],
                 viop: List[Tuple[float, float, str]], viop_why: str = ""):
        self.spot = spot if type(spot) is float else None
        self.tenors = tenors
        self.curves = curves
        self.viop = viop
        self.viop_why = viop_why


def read_market(book, calc, layout: Sequence[Tuple[str, int]]) -> Market:
    """The market of the fair value from the TRY workbook ``book`` as ``calc`` has it (the desk's: no personal inputs)."""
    from . import quantviop as qv

    def cell(ref: str) -> Any:
        si, rc = book.cell(ref)
        return calc.get(si, *divmod(rc, COLS))

    def num(v: Any) -> Optional[float]:
        return v if type(v) is float and math.isfinite(v) else None

    try:
        spot = bsp._date(cell("Forward!I2"))
    except Exception:  # noqa: BLE001 - no spot date: no fair value (said on the page)
        spot = None
    tenors = []
    for label, row in layout:
        tenors.append({"label": label, "row": row, "days": num(cell("Forward!U%d" % row)),
                       "bid": num(cell("Forward!W%d" % row)), "ask": num(cell("Forward!X%d" % row))})
    curves = bsp.read_curves(book, calc)
    rows: Dict[str, Any] = {}
    index = book.model.sheet_index

    def reader(sheet: str) -> Callable[[str], Any]:
        si = index[sheet]
        return lambda ref: calc.get(si, *divmod(parse_a1(ref), COLS))

    viop: List[Tuple[float, float, str]] = []
    why = ""
    try:
        qv.read_engine(rows, index, reader, num)
        for r in rows.get("viopq") or []:
            if r.get("expiry") and r.get("i_bid") is not None and r.get("i_ask") is not None:
                d = float(date_to_serial(_dt.date.fromisoformat(r["expiry"])))
                viop.append((d, (r["i_bid"] + r["i_ask"]) / 200.0, str(r.get("ticker") or "")))
        if not viop:
            why = "VİOP sayfasında iki taraflı kotası olan kontrat yok"
    except Exception as exc:  # noqa: BLE001 - the VİOP sheet cannot be read: no VİOP base (said why)
        why = "VİOP okunamadı: %s" % str(exc)[:120]
    return Market(spot if type(spot) is float else None, tenors, curves, sorted(viop), why)


def base_mids(market: Market, t: Dict[str, Any]) -> Tuple[Dict[str, Optional[float]], Dict[str, str], Optional[Tuple[float, float]]]:
    """Each base's mid at a tenor (fractions), why one has none, and the tenor's two dates."""
    mids: Dict[str, Optional[float]] = {b: None for b in BASES}
    why: Dict[str, str] = {}
    if market.spot is None or t.get("days") is None or not t["days"] > 0:
        for b in BASES:
            why[b] = "spot valörü ya da vadenin gün sayısı okunamadı"
        return mids, why, None
    start, end = tenor_dates(t["label"], t["days"], market.spot)
    for key in ("ois", "off"):
        c = market.curves.get(key)
        z = c.zero(start, end) if c is not None else None
        mids[key] = z
        if z is None:
            why[key] = (c.why if c is not None and c.why else "eğrinin bu tarihlerde değeri yok")
    if market.viop:
        v = interp_dates([(d, r) for d, r, _ in market.viop], end)
        mids["viop"] = v
        if v is None:
            first, last = market.viop[0][0], market.viop[-1][0]
            why["viop"] = ("VİOP: ilk kontratın vadesinden (%s) kısa" % serial_to_date(first).strftime("%d.%m.%Y")) if end < first \
                else ("VİOP: son kontratın vadesinden (%s) uzun" % serial_to_date(last).strftime("%d.%m.%Y"))
    else:
        why["viop"] = market.viop_why or "VİOP kontratı yok"
    return mids, why, (start, end)


def tenor_cfg(desk: Dict[str, Any], label: str) -> Dict[str, Any]:
    cfg = dict((desk.get("tenors") or {}).get(label) or {})
    cfg.setdefault("base", "ois")
    if cfg["base"] not in CHOICES:
        cfg["base"] = "ois"
    cfg.setdefault("offset", None)
    cfg["flow"] = float(cfg.get("flow") or 0.0)
    if cfg.get("anchor") not in ANCHORS:
        cfg["anchor"] = "mid"
    return cfg


def scenario_bases(mids: Dict[str, Optional[float]], why: Dict[str, str], s: Optional[Dict[str, Any]]) -> None:
    """A tenor's bases under a scenario (in place): the OIS base is the scenario curve's rate, VİOP and offshore move by
    the scenario's rate less the reference's (``s``: ``{"ois", "delta", "why"}``)."""
    s = s or {}
    mids["ois"] = s.get("ois")
    if mids["ois"] is None:
        why["ois"] = s.get("why") or "senaryo eğrisinin bu vadede değeri yok"
    for b in ("viop", "off"):
        if mids[b] is None:
            continue
        if s.get("delta") is None:
            mids[b] = None
            why[b] = s.get("why") or "senaryonun bu vadede farkı yok"
        else:
            mids[b] = mids[b] + s["delta"]


def compute(market: Market, desk: Dict[str, Any], admin: Dict[str, Any], shown: Dict[str, Any],
            scen: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every tenor's fair value: ``(rows, shown)`` - the rows for the page, the shown bids (bp) after this reading.
    ``scen``: the bases of a scenario per tenor (:func:`scenario_bases`; ``None``: the market's)."""
    h = float(admin.get("hysteresis", DEFAULTS["hysteresis"]))
    widths = admin.get("widths") or {}
    blend_default = admin.get("blend") or DEFAULTS["blend"]
    new_shown: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    for t in market.tenors:
        label = t["label"]
        cfg = tenor_cfg(desk, label)
        anchor = cfg["anchor"]
        mids, why, dates = base_mids(market, t)
        market_mids = None
        if scen is not None:
            market_mids = dict(mids)
            scenario_bases(mids, why, scen.get(label))
        weights = cfg.get("weights") or blend_default
        if cfg["base"] == "blend":
            base_mid, base_why = blend_mid(mids, weights)
        else:
            base_mid, base_why = mids.get(cfg["base"]), why.get(cfg["base"], "")
        w = widths.get(label)
        offset, flow = cfg["offset"], cfg["flow"]
        row: Dict[str, Any] = {"tenor": label, "days": t["days"], "base": cfg["base"],
                               "weights": dict(weights) if cfg["base"] == "blend" else None, "mids": mids, "why": why,
                               "base_mid": base_mid, "base_why": base_why, "offset": offset, "flow": flow,
                               "flow_log": list(cfg.get("flow_log") or []), "width": w,
                               "formula": formula_text(cfg["base"], weights, offset, flow, anchor), "anchor": anchor,
                               "pub": {"bid": t["bid"], "ask": t["ask"]}, "now": None, "now_why": "", "update": False,
                               "start": serial_to_date(dates[0]).isoformat() if dates else None,
                               "end": serial_to_date(dates[1]).isoformat() if dates else None}
        if market_mids is not None:
            row["market_mids"] = market_mids
        if offset is None:
            row["now_why"] = "tabana spread yazılmadı"
        elif base_mid is None:
            row["now_why"] = base_why or "taban yok"
        elif w is None:
            row["now_why"] = "genişlik yok"
        else:
            raw = base_mid * 10000.0 + offset + flow               # the anchored side, raw
            raw_bid = raw_bid_of(anchor, raw, w)
            prev = (shown.get(label) or {}).get("bid")
            bid = quote(anchor, raw, w, prev if type(prev) in (int, float) else None, h)
            new_shown[label] = {"bid": bid, "raw": round(raw_bid, 4)}
            if anchor == "mid":
                row["raw_mid"] = raw / 10000.0
            row["raw"] = raw / 10000.0
            row["raw_bid"] = raw_bid / 10000.0
            row["now"] = {"bid": round(bid / 10000.0, 8), "ask": round((bid + w) / 10000.0, 8)}
            pb, pa = t["bid"], t["ask"]
            if type(pb) is float and type(pa) is float:
                db, da = (row["now"]["bid"] - pb) * 10000.0, (row["now"]["ask"] - pa) * 10000.0
                row["diff"] = {"bid": round(db, 2), "ask": round(da, 2)}
                row["update"] = abs(db) >= 0.01 or abs(da) >= 0.01
            else:
                row["diff"] = None
                row["update"] = True
        # "Neredeyim": the published side the rule sets (the bid for Mid, as always) against every base; the RET each
        # base would give with this offset
        side = "ask" if anchor == "ask" else "bid"
        pb = t[side]
        row["where"] = {b: (round((pb - mids[b]) * 10000.0, 2) if type(pb) is float and mids[b] is not None else None) for b in BASES}
        row["where_side"] = side
        whatif: Dict[str, Any] = {}
        if offset is not None and w is not None:
            for b in BASES + ("blend",):
                m = mids[b] if b != "blend" else blend_mid(mids, weights)[0]
                if m is None:
                    whatif[b] = None
                    continue
                bid = grid_round(m * 10000.0 + offset + flow - w / 2.0) if anchor == "mid" else \
                    grid_bid(anchor, m * 10000.0 + offset + flow, w)
                whatif[b] = {"bid": round(bid / 10000.0, 8), "ask": round((bid + w) / 10000.0, 8)}
        row["whatif"] = whatif
        rows.append(row)
    return rows, new_shown


# ---------------------------------------------------------------------------------------------- the business days
def lookback_days(today: _dt.date, n: int, holidays: set) -> List[str]:
    """The ``n`` business days before ``today`` (weekdays that are no TRY holiday), latest first, as ISO dates."""
    out: List[str] = []
    d = today
    guard = 0
    while len(out) < n and guard < 400:
        d -= _dt.timedelta(days=1)
        guard += 1
        if d.weekday() < 5 and d not in holidays:
            out.append(d.isoformat())
    return out


# ---------------------------------------------------------------------------------------------- the service's part
class RetFair(object):
    """The fair value RET of the service: its settings (kv ``retfair.*``, the desk's), its log (``ret_fair_log``), the
    state for the page, the changes, "Kopyala ve yayınla" and the "Pozisyon ve maliyet" panel."""

    KEY_DESK, KEY_ADMIN, KEY_SHOWN, KEY_ACCEPTED = "retfair.desk", "retfair.admin", "retfair.shown", "retfair.accepted"
    KEY_VIEW = "retfair.view."                   # + the user: their own "Senaryo" ({"scenario": "S2"})

    def __init__(self, svc):
        self.svc = svc
        self.store = svc.store
        self._lock = threading.RLock()
        self._summary: Dict[str, Any] = {"updates": [], "at": None}
        self._summary_t = 0.0
        self._pending = None
        # what reads the workbook's market (tests put a market of their own here)
        self.read_market: Callable[..., Market] = read_market

    # ------------------------------------------------------------------ the stored parts
    def desk(self) -> Dict[str, Any]:
        d = self.store.get(self.KEY_DESK) or {}
        d.setdefault("tenors", {})
        return d

    def admin(self) -> Dict[str, Any]:
        a = dict(DEFAULTS)
        a["blend"] = dict(DEFAULTS["blend"])
        stored = self.store.get(self.KEY_ADMIN) or {}
        a.update({k: v for k, v in stored.items() if v is not None})
        a.setdefault("widths", {})
        return a

    def _log(self, user: Optional[str], kind: str, text: str) -> None:
        self.store.add_ret_fair_log(user, kind, text)

    def log(self, limit: int = LOG_LIMIT) -> List[Dict[str, Any]]:
        return self.store.ret_fair_log(limit)

    # ------------------------------------------------------------------ reading (the calculation thread)
    def _book(self):
        return self.svc._book("tto")

    def _market(self) -> Market:
        book = self._book()
        return self.read_market(book, book.engine.shared, self.svc._ret_layout(book))

    def _ensure_widths(self, market: Market, admin: Dict[str, Any]) -> Dict[str, Any]:
        """A tenor without a width takes the published RET's (ask − bid), on the 5 bp grid - once; said in the log,
        with the widths that were no multiple of 5."""
        widths = dict(admin.get("widths") or {})
        new, odd = [], []
        for t in market.tenors:
            if t["label"] in widths:
                continue
            if type(t["bid"]) is float and type(t["ask"]) is float:
                raw = (t["ask"] - t["bid"]) * 10000.0
                w = int(grid_round(raw))
                if abs(raw - w) > 0.01:
                    odd.append("%s %s → %d" % (t["label"], _bp(raw), w))
            else:
                w = DEFAULT_WIDTH
            widths[t["label"]] = max(0, min(WIDTH_MAX, w))
            new.append("%s %d" % (t["label"], widths[t["label"]]))
        if not new:
            return admin
        stored = self.store.get(self.KEY_ADMIN) or {}
        stored["widths"] = widths
        if odd:
            stored["width_notes"] = list(stored.get("width_notes") or []) + odd
        self.store.put(self.KEY_ADMIN, stored)
        self._log(None, "genislik", "Genişlikler yayınlanan RET'ten alındı (bp): " + ", ".join(new)
                  + ("; 5 bp'nin katı olmayanlar yuvarlandı: " + ", ".join(odd) if odd else ""))
        admin = dict(admin)
        admin["widths"] = widths
        if odd:
            admin["width_notes"] = stored["width_notes"]
        return admin

    def _evaluate(self, market: Optional[Market] = None) -> Tuple[Market, Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        """Read and compute (the calculation thread): the market, the desk's and the administrators' settings, the rows -
        the shown bids kept when they moved, the header's summary made again."""
        with self._lock:
            market = market or self._market()
            admin = self._ensure_widths(market, self.admin())
            desk = self.desk()
            shown = self.store.get(self.KEY_SHOWN) or {}
            rows, new_shown = compute(market, desk, admin, shown)
            # kept when a shown bid moved (a tenor without a value now keeps its last one; a raw value that moved
            # within the hysteresis changes nothing that is kept)
            moved = False
            keep = dict(shown)
            for k, v in new_shown.items():
                old = shown.get(k) or {}
                if old.get("bid") != v["bid"]:
                    v["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    keep[k] = v
                    moved = True
            if moved:
                self.store.put(self.KEY_SHOWN, keep)
            self._summary = {"updates": [r["tenor"] for r in rows if r["update"] and r["now"]],
                             "at": time.strftime("%H:%M:%S")}
            self._summary_t = time.monotonic()
            return market, desk, admin, rows

    def _reset_shown(self, labels: Sequence[str]) -> None:
        """A person changed these tenors: their shown value follows at once (no hysteresis from before)."""
        shown = self.store.get(self.KEY_SHOWN) or {}
        if any(lab in shown for lab in labels):
            for lab in labels:
                shown.pop(lab, None)
            self.store.put(self.KEY_SHOWN, shown)

    def summary(self) -> Dict[str, Any]:
        """The header's "RET güncellemesi var": the tenors whose shown fair value differs from the published RET - as
        last worked out; made again in the background when older than ``SUMMARY_EVERY`` (never waited for)."""
        stopping = getattr(self.svc, "_stop", None)
        if time.monotonic() - self._summary_t >= SUMMARY_EVERY and (self._pending is None or self._pending.done()) \
                and not (stopping is not None and stopping.is_set()):
            self._summary_t = time.monotonic()          # (one at a time, even if it fails)
            try:
                et = self.svc.et
                self._pending = et.submit_at(et.BACKGROUND, self._tick)
            except Exception:  # noqa: BLE001 - no engine (stopping): the last summary stays
                pass
        return dict(self._summary)

    def _tick(self) -> None:
        try:
            self._evaluate()
        except Exception as exc:  # noqa: BLE001 - the header's summary must never take the service down
            self.svc.ops.failure("RET adil değer", exc)

    # ------------------------------------------------------------------ the flows
    def _flows(self, market: Market, admin: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Today's and the last days' forwards per RET tenor, their normal and cost, and the suggestions."""
        svc = self.svc
        today = _dt.date.fromisoformat(svc.today_iso())
        n = int(admin.get("lookback") or DEFAULTS["lookback"])
        holidays = {serial_to_date(s) for s in svc._calendar_serials(("TRY",))}
        days = lookback_days(today, n, holidays)
        first = days[-1] if days else today.isoformat()
        fwds = rf.forwards(svc.store.trades(first, today.isoformat()))
        buckets = rf.buckets_of([(t["label"], t["days"]) for t in market.tenors])
        ref_ret, ref_ois = self._refs(market)
        today_iso = today.isoformat()
        todays = [f for f in fwds if f["day"] == today_iso]
        agg_today = rf.aggregate(todays, buckets, ref_ret, ref_ois)
        agg_window = rf.aggregate(fwds, buckets, ref_ret, ref_ois)          # the lookback days and today
        nets = rf.daily_nets([f for f in fwds if f["day"] in days], buckets)
        normals = {lab: rf.normal(nets, days, lab) for lab, _ in buckets}
        curve = {}
        for r in rows:
            cur = r["now"] or r["pub"]
            curve[r["tenor"]] = {"pub_bid": r["pub"]["bid"], "pub_ask": r["pub"]["ask"],
                                 "cur_bid": cur.get("bid"), "cur_ask": cur.get("ask")}
        acc = self.store.get(self.KEY_ACCEPTED) or {}
        accepted = acc.get("ids") or {} if acc.get("day") == today_iso else {}
        sugg = rf.suggest(agg_today, normals, [t["label"] for t in market.tenors], curve,
                          float(admin.get("sensitivity") or 0.0), float(admin.get("margin") or 0.0), accepted, len(days))
        by_tenor = {r["tenor"]: r for r in rows}
        table = []
        for lab, d in buckets:
            a, wnd = agg_today.get(lab), agg_window.get(lab)
            if not a and not wnd:
                continue
            r = by_tenor.get(lab) or {}
            entry: Dict[str, Any] = {"tenor": lab, "days": d, "today": a, "window": wnd, "normal": normals.get(lab, 0.0)}
            entry["ratio"] = (abs(a["net"]) / entry["normal"]) if a and entry["normal"] > rf.EPS else None
            cost = (a or {}).get("cost") if a and a.get("cost") is not None else (wnd or {}).get("cost")
            side = (a or {}).get("side") if a and a.get("side") else (wnd or {}).get("side")
            entry["cost"], entry["side"] = cost, side
            # the cost against the RET (the side the flow is dealt on) and against every base, bp
            if cost is not None:
                ret = r.get("pub", {}).get("bid" if side == "sold" else "ask")
                entry["vs_ret"] = (ret - cost) * 10000.0 if type(ret) is float else None
                entry["vs"] = {b: ((r.get("mids") or {}).get(b) - cost) * 10000.0 if (r.get("mids") or {}).get(b) is not None else None
                               for b in BASES}
            table.append(entry)
        return {"today": today_iso, "days": days, "lookback": n, "table": table, "suggestions": sugg,
                "accepted": accepted}

    def _refs(self, market: Market) -> Tuple[Optional[Callable[[float], Optional[float]]], Optional[Callable[[float], Optional[float]]]]:
        """The curves a flow's P&L is read against, at a trade's own days: the published RET's mid (in a straight line
        between its tenors, as the Forward sheet reads it) and the OIS mid zero rate from the spot."""
        pts = [(t["days"], (t["bid"] + t["ask"]) / 2.0) for t in market.tenors
               if type(t["days"]) is float and type(t["bid"]) is float and type(t["ask"]) is float]
        ref_ret = (lambda d: rf.curve_at(pts, d)) if pts else None
        ois, spot = market.curves.get("ois"), market.spot
        ref_ois = (lambda d: ois.zero(spot, spot + d)) if ois is not None and spot is not None and not ois.why else None
        return ref_ret, ref_ois

    # ------------------------------------------------------------------ the scenarios (each user's own view)
    def choice(self, user: Optional[str]) -> str:
        """The user's "Senaryo": a scenario's code, or ``MARKET``."""
        got = (self.store.get(self.KEY_VIEW + user) or {}).get("scenario") if user else None
        return got if got in SCENARIOS else MARKET

    def set_view(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """``{"scenario": "S2" | "piyasa"}``: the user's own view of the fair value (kept by the scenario's code - a
        renamed scenario is the same one)."""
        key = self.svc.require_user(user)
        raw = str((body or {}).get("scenario") or MARKET).strip()
        code = raw.upper() if raw.upper() in SCENARIOS else raw.lower()
        if code not in SCENARIOS and code != MARKET:
            raise self._error("senaryo Piyasa, %s olmalı" % ", ".join(SCENARIOS))
        self.store.put(self.KEY_VIEW + key, {"scenario": code})
        return self.svc.et.call(self._state, key)

    def _scenario_rates(self, user: Optional[str]) -> Dict[str, Any]:
        """The RET tenors' rates on each scenario curve and on the reference, and the scenarios' names - from the
        workbook's own formulas (``extras.RETS_SHEET``) in the user's calculation: their steps, their names."""
        book = self._book()
        si = book.model.sheet_index.get(ex.RETS_SHEET)
        out: Dict[str, Any] = {"names": {code: code for code in SCENARIOS}, "rates": {code: {} for code in SCENARIOS},
                               "ref": {}, "why": ""}
        if si is None:
            out["why"] = "senaryo tablosu (%s) bu çalışma kitabında yok" % ex.RETS_SHEET
            return out
        calc = self.svc._calc(user, book)

        def num(v: Any) -> Optional[float]:
            return v if type(v) is float and math.isfinite(v) else None

        for code, row, _, _, _, _ in ex.RETS_SCENARIOS:
            v = calc.get(si, row + 1, 1)
            out["names"][code] = v if isinstance(v, str) and v.strip() else code
        cols = [(code, col_to_index(rate)) for code, _, _, _, _, rate in ex.RETS_SCENARIOS]
        ref_col = col_to_index(ex.RETS_REF[2])
        for r in range(ex.RETS_FIRST, ex.RETS_PATH - 1):
            label = calc.get(si, r, 1)
            if not isinstance(label, str) or not label.strip():
                break
            for code, c in cols:
                out["rates"][code][label] = num(calc.get(si, r, c))
            out["ref"][label] = num(calc.get(si, r, ref_col))
        return out

    @staticmethod
    def _scenario_map(rates: Dict[str, Any], code: str, labels: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """A scenario's bases per tenor for :func:`compute`: its OIS rate and its difference to the reference."""
        out: Dict[str, Dict[str, Any]] = {}
        mine = rates["rates"].get(code) or {}
        for label in labels:
            rate, ref = mine.get(label), rates["ref"].get(label)
            ok = rate is not None and ref is not None
            out[label] = {"ois": rate, "delta": (rate - ref) if ok else None,
                          "why": "" if ok else (rates.get("why") or "senaryo eğrisinin bu vadede değeri yok")}
        return out

    def _views(self, user: Optional[str], market: Market, desk: Dict[str, Any], admin: Dict[str, Any],
               rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """The user's view: the rows of their scenario (the market's: the desk's own rows), the scenarios with their names,
        and every tenor under the market and each scenario side by side (no hysteresis in a scenario: plain grid)."""
        code = self.choice(user)
        rates = self._scenario_rates(user)
        labels = [t["label"] for t in market.tenors]
        per: Dict[str, List[Dict[str, Any]]] = {}
        for c in SCENARIOS:
            per[c] = compute(market, desk, admin, {}, self._scenario_map(rates, c, labels))[0]
        names = rates["names"]
        compare = []
        for k, r in enumerate(rows):
            entry: Dict[str, Any] = {"tenor": r["tenor"], "pub": r["pub"], MARKET: r["now"]}
            for c in SCENARIOS:
                sr = per[c][k]
                entry[c] = sr["now"]
                if not sr["now"]:
                    entry.setdefault("why", {})[c] = sr["now_why"]
            compare.append(entry)
        return {"code": code, "name": ex.RETS_MARKET if code == MARKET else names[code],
                "rows": rows if code == MARKET else per[code],
                "scenarios": [{"code": MARKET, "name": ex.RETS_MARKET}] + [{"code": c, "name": names[c]} for c in SCENARIOS],
                "compare": compare, "why": rates["why"]}

    # ------------------------------------------------------------------ the state of the page
    def state(self, user: Optional[str]) -> Dict[str, Any]:
        self.svc.require_user(user)
        return self.svc.et.call(self._state, user)

    def _state(self, user: Optional[str]) -> Dict[str, Any]:
        market, desk, admin, rows = self._evaluate()
        flows = self._flows(market, admin, rows)
        meta = self.svc.ret_meta()
        view = self._views(user, market, desk, admin, rows)
        shown = view["rows"]
        return {"rows": shown, "updates": [r["tenor"] for r in shown if r["update"] and r["now"]],
                "settings": {k: admin.get(k) for k in ("hysteresis", "sensitivity", "lookback", "margin", "blend", "widths")},
                "width_notes": admin.get("width_notes") or [],
                "spot": serial_to_date(market.spot).isoformat() if market.spot is not None else None,
                "viop": [{"expiry": serial_to_date(d).isoformat(), "mid": r, "ticker": n} for d, r, n in market.viop],
                "flows": flows, "log": self.log(), "meta": meta, "admin": self.svc._is_admin(user),
                "defaults": {k: DEFAULTS[k] for k in DEFAULTS}, "gen": self.svc.gen,
                # the user's own view: their scenario (its name now), the scenarios to choose from, the comparison
                "scenario": {"code": view["code"], "name": view["name"], "why": view["why"]},
                "scenarios": view["scenarios"], "compare": view["compare"],
                "market_updates": [r["tenor"] for r in rows if r["update"] and r["now"]]}

    # ------------------------------------------------------------------ the trader's changes
    def _labels(self, market: Market, tenors: Any) -> List[str]:
        known = [t["label"] for t in market.tenors]
        if tenors == "all":
            return known
        if not isinstance(tenors, list) or not tenors:
            raise self._error("vade seçilmedi")
        out = []
        for x in tenors:
            lab = str(x or "").strip().upper()
            if lab not in known:
                raise self._error("bilinmeyen RET vadesi: %r" % x)
            if lab not in out:
                out.append(lab)
        return out

    def _error(self, text: str, status: int = 400):
        from .service import ServiceError
        return ServiceError(text, status)

    @staticmethod
    def _number(v: Any, what: str, lo: float = -OFFSET_MAX, hi: float = OFFSET_MAX) -> float:
        from .inputs import parse_number
        x = parse_number(v, "tr", prefer_decimal=True) if isinstance(v, str) else (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
        if x is None or not math.isfinite(x) or not lo <= x <= hi:
            from .service import ServiceError
            raise ServiceError("%s anlaşılamadı: %r" % (what, v))
        return x

    def change(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """A change of the desk's per-tenor settings: ``{"tenors": [...] | "all"}`` with one of ``"offset"`` (a number;
        ``null`` clears it), ``"shift"`` (bp added to the offsets that are set), ``"from_published": true`` (the offset
        that gives the published RET's anchored side now), ``"base"`` (+ ``"weights"`` for "blend"), ``"anchor"``
        ("bid" / "mid" / "ask": which quote base + offset + flow sets)."""
        key = self.svc.require_user(user)
        out = self.svc.et.call_at(self.svc.et.WRITE, self._change, key, body)
        self.svc.bump()
        return out

    def _change(self, user: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            market, desk, admin, rows = self._evaluate()
            labels = self._labels(market, body.get("tenors"))
            by = {r["tenor"]: r for r in rows}
            tenors = desk.setdefault("tenors", {})
            changed: List[str] = []
            text = ""
            if "offset" in body:
                val = None if body["offset"] in (None, "") else round(self._number(body["offset"], "tabana spread"), 1)
                for lab in labels:
                    cfg = tenors.setdefault(lab, {})
                    if cfg.get("offset") != val:
                        cfg["offset"] = val
                        changed.append(lab)
                text = "%s: tabana spread %s" % (", ".join(changed), "silindi" if val is None else _bp(val) + " bp")
            elif "shift" in body:
                d = round(self._number(body["shift"], "kaydırma"), 1)
                skipped = []
                for lab in labels:
                    cfg = tenors.setdefault(lab, {})
                    if cfg.get("offset") is None:
                        skipped.append(lab)
                        continue
                    if d:
                        cfg["offset"] = round(float(cfg["offset"]) + d, 1)
                        changed.append(lab)
                text = "%s: tabana spread %s%s bp kaydırıldı" % (", ".join(changed), "+" if d > 0 else "", _bp(d)) + (
                    " (spread'i olmayan: %s)" % ", ".join(skipped) if skipped else "")
                if skipped and not changed:
                    raise self._error("seçilen vadelerin tabana spread'i yok: önce yazın ya da 'Yayınlanandan al'")
            elif body.get("from_published"):
                # the offset that gives the published RET's anchored side now (the market's base: the offset is the desk's)
                parts, skipped = [], []
                for lab in labels:
                    r = by[lab]
                    pb, pa = r["pub"]["bid"], r["pub"]["ask"]
                    if r["base_mid"] is None or type(pb) is not float or type(pa) is not float:
                        skipped.append(lab)
                        continue
                    anchor = r.get("anchor") or "mid"
                    if anchor == "mid":
                        val = float(round((pb + pa) / 2.0 * 10000.0 - r["base_mid"] * 10000.0 - r["flow"]))
                    else:
                        val = float(round((pb if anchor == "bid" else pa) * 10000.0 - r["base_mid"] * 10000.0 - r["flow"]))
                    cfg = tenors.setdefault(lab, {})
                    cfg["offset"] = val
                    changed.append(lab)
                    parts.append("%s %s" % (lab, _bp(val)))
                text = "Tabana spread yayınlanan RET'ten alındı (bp): " + ", ".join(parts) + (
                    " · tabanı ya da RET'i olmayan: " + ", ".join(skipped) if skipped else "")
                if not changed:
                    raise self._error("seçilen vadelerin tabanı ya da yayınlanan RET'i yok")
            elif "base" in body:
                base = str(body.get("base") or "").strip().lower()
                if base not in CHOICES:
                    raise self._error("taban OIS, VİOP, offshore ya da karma olmalı")
                weights = None
                if base == "blend":
                    weights = self._weights(body.get("weights") or admin.get("blend") or DEFAULTS["blend"])
                for lab in labels:
                    cfg = tenors.setdefault(lab, {})
                    before = tenor_cfg(desk, lab)
                    if before["base"] != base or (base == "blend" and before.get("weights") != weights):
                        cfg["base"] = base
                        if weights is not None:
                            cfg["weights"] = weights
                        changed.append(lab)
                text = "%s: taban %s" % (", ".join(changed), BASE_NAMES[base] + (" (%s)" % weights_text(weights) if weights else ""))
            elif "anchor" in body:
                anchor = str(body.get("anchor") or "").strip().lower()
                if anchor not in ANCHORS:
                    raise self._error("tabana göre Bid, Mid ya da Ask olmalı")
                for lab in labels:
                    if tenor_cfg(desk, lab)["anchor"] != anchor:
                        cfg = tenors.setdefault(lab, {})
                        if anchor == "mid":
                            cfg.pop("anchor", None)             # (the default: nothing kept)
                        else:
                            cfg["anchor"] = anchor
                        changed.append(lab)
                text = "%s: tabana göre %s (%s = taban + spread + akış)" % (", ".join(changed), ANCHOR_NAMES[anchor], ANCHOR_NAMES[anchor])
            else:
                raise self._error("değişiklik anlaşılamadı")
            if changed:
                self.store.put(self.KEY_DESK, desk)
                self._reset_shown(changed)
                self._log(user, "tenor", text)
            return self._state(user)

    @staticmethod
    def _weights(raw: Any) -> Dict[str, float]:
        from .service import ServiceError
        if not isinstance(raw, dict):
            raise ServiceError("karma ağırlıkları anlaşılamadı")
        out = {}
        for b in BASES:
            v = raw.get(b, 0)
            x = RetFair._number(v if v not in (None, "") else 0, "ağırlık", 0.0, 1000.0)
            out[b] = round(x, 2)
        if sum(out.values()) <= 0:
            raise ServiceError("karma ağırlıklarından en az biri 0'dan büyük olmalı")
        return out

    # ------------------------------------------------------------------ the administrators' settings
    def set_settings(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        key = self.svc.require_admin(user)
        out = self.svc.et.call_at(self.svc.et.WRITE, self._set_settings, key, body)
        self.svc.bump()
        return out

    def _set_settings(self, user: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            market = self._market()
            before = self._ensure_widths(market, self.admin())
            stored = self.store.get(self.KEY_ADMIN) or {}
            parts: List[str] = []
            reset: List[str] = []
            known = [t["label"] for t in market.tenors]
            for name, (lo, hi, kind) in LIMITS.items():
                if name not in body or body[name] in (None, ""):
                    continue
                x = self._number(body[name], LABELS[name], lo, hi)
                x = int(round(x)) if kind is int else round(x, 2)
                if x != before.get(name):
                    parts.append("%s %s → %s" % (LABELS[name], _bp(float(before.get(name))), _bp(float(x))))
                stored[name] = x
            if body.get("blend") is not None:
                w = self._weights(body["blend"])
                if w != before.get("blend"):
                    parts.append("varsayılan karma %s → %s" % (weights_text(before.get("blend") or {}), weights_text(w)))
                stored["blend"] = w
            if body.get("widths") is not None:
                if not isinstance(body["widths"], dict):
                    raise self._error("genişlikler anlaşılamadı")
                widths = dict(before.get("widths") or {})
                for lab, v in body["widths"].items():
                    lab = str(lab).strip().upper()
                    if lab not in known:
                        raise self._error("bilinmeyen RET vadesi: %r" % lab)
                    x = self._number(v, "%s genişliği" % lab, 0, WIDTH_MAX)
                    if abs(x - round(x)) > 1e-9 or int(round(x)) % 5:
                        raise self._error("%s genişliği 5 bp'nin katı olmalı (%s)" % (lab, _bp(x)))
                    x = int(round(x))
                    if widths.get(lab) != x:
                        parts.append("%s genişlik %s → %d bp" % (lab, widths.get(lab), x))
                        reset.append(lab)
                    widths[lab] = x
                stored["widths"] = widths
            self.store.put(self.KEY_ADMIN, stored)
            if reset:
                self._reset_shown(reset)
            if parts:
                self._log(user, "ayar", "Ekstra ayarlar: " + "; ".join(parts))
            return self._state(user)

    # ------------------------------------------------------------------ the flow adjustments
    def flow(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """``{"accept": <suggestion id>}`` adds the suggestion's moves as flow adjustments; ``{"remove": <tenor>}`` takes
        a tenor's away (one click each)."""
        key = self.svc.require_user(user)
        out = self.svc.et.call_at(self.svc.et.WRITE, self._flow, key, body)
        self.svc.bump()
        return out

    def _flow(self, user: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            market, desk, admin, rows = self._evaluate()
            tenors = desk.setdefault("tenors", {})
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            if body.get("accept"):
                flows = self._flows(market, admin, rows)
                sid = str(body["accept"])
                s = next((x for x in flows["suggestions"] if x["id"] == sid), None)
                if s is None or not s.get("ok"):
                    raise self._error("bu öneri artık yok (akış ya da RET değişti): sayfa yenilendi", 409)
                for lab, bp in s["moves"].items():
                    cfg = tenors.setdefault(lab, {})
                    cfg["flow"] = round(float(cfg.get("flow") or 0.0) + bp, 1)
                    cfg["flow_log"] = list(cfg.get("flow_log") or []) + [{"bp": bp, "at": stamp, "by": user, "why": s["text"]}]
                acc = self.store.get(self.KEY_ACCEPTED) or {}
                if acc.get("day") != flows["today"]:
                    acc = {"day": flows["today"], "ids": {}}
                acc["ids"][sid] = int(acc["ids"].get(sid) or 0) + int(s["steps"])
                self.store.put(self.KEY_ACCEPTED, acc)
                self.store.put(self.KEY_DESK, desk)
                self._reset_shown(list(s["moves"]))
                self._log(user, "akis", "Akış önerisi kabul edildi: " + s["text"])
            elif body.get("remove"):
                lab = str(body["remove"]).strip().upper()
                cfg = tenors.get(lab) or {}
                had = float(cfg.get("flow") or 0.0)
                if not had:
                    raise self._error("%s vadesinde akış ayarı yok" % lab)
                cfg["flow"] = 0.0
                cfg["flow_log"] = []
                tenors[lab] = cfg
                self.store.put(self.KEY_DESK, desk)
                self._reset_shown([lab])
                self._log(user, "akis", "%s: akış ayarı (%s bp) kaldırıldı" % (lab, ("+" if had > 0 else "") + _bp(had)))
            else:
                raise self._error("akış işlemi anlaşılamadı")
            return self._state(user)

    # ------------------------------------------------------------------ "Kopyala ve yayınla"
    def publish(self, user: Optional[str], rows: Any, scenario: Any = None) -> Dict[str, Any]:
        """The curve the page copied, written as the desk's RET: the shared RET cells (every table that reads the RET
        follows), the RET's history (who, when, what, from which scenario) and its "loaded today" mark.  What is written
        is exactly what was copied - the page sends what it put on the clipboard (``scenario``: the user's view it was
        copied from, a scenario's code; the market otherwise).  Says which tenors moved and by how much (bp)."""
        key = self.svc.require_user(user)
        if not isinstance(rows, list) or not rows:
            raise self._error("yayınlanacak eğri yok")
        code = str(scenario or "").strip().upper()
        if code and code not in SCENARIOS:
            code = ""
        clean = []
        for r in rows:
            if not isinstance(r, dict):
                raise self._error("eğri satırı anlaşılamadı")
            lab = str(r.get("tenor") or "").strip().upper()
            bid, ask = r.get("bid"), r.get("ask")
            if type(bid) is int:
                bid = float(bid)
            if type(ask) is int:
                ask = float(ask)
            if type(bid) is not float or type(ask) is not float or not (0.0 < bid < 5.0 and 0.0 < ask < 5.0) or ask < bid:
                raise self._error("%s: bid / ask anlaşılamadı" % (lab or "?"))
            clean.append({"tenor": lab, "bid": round(bid, 8), "ask": round(ask, 8)})
        name = self.svc.et.call(lambda: self._scenario_rates(key)["names"][code]) if code else ""
        before = {r["tenor"]: r for r in self.svc.ret()["rows"]}
        res = self.svc.set_ret(key, clean)
        if res.get("errors"):
            raise self._error("; ".join(res["errors"]))
        # what moved against the RET published before (as the RET's history counts it: a hundredth of a bp is no move)
        from .service import ret_changes
        deltas = ret_changes(list(before.values()), clean)
        moved = []
        new = {r["tenor"]: r for r in clean}
        for d in deltas:
            b, r = before.get(d["tenor"]) or {}, new[d["tenor"]]
            both = type(b.get("bid")) is float and type(b.get("ask")) is float
            was = ("%s / %s" % (rf.pct_text(b["bid"]), rf.pct_text(b["ask"]))) if both else "—"
            moved.append("%s %s / %s (önce %s)" % (r["tenor"], rf.pct_text(r["bid"]), rf.pct_text(r["ask"]), was))
        source = ("%s senaryosundan" % name) if code else ""
        self._log(key, "yayin", "Kopyala ve yayınla" + (" (%s)" % source if source else "") + ": "
                  + ("; ".join(moved) if moved else "eğri değişmeden yeniden yayınlandı"))
        if res.get("ret_history"):
            self.store.note_ret_history(res["ret_history"], {"source": "Adil değer · Kopyala ve yayınla" + (" · " + source if source else "")})
        out = self.state(key)
        out["published"] = len(clean)
        out["moved"] = deltas
        out["source"] = source
        return out

    # ------------------------------------------------------------------ "Pozisyon ve maliyet" (Günlük İşlemler)
    def position(self, user: Optional[str]) -> Dict[str, Any]:
        self.svc.require_user(user)
        return self.svc.et.call(self._position)

    def _position(self) -> Dict[str, Any]:
        market = self._market()
        admin = self.admin()
        rows = [{"tenor": t["label"], "now": None, "pub": {"bid": t["bid"], "ask": t["ask"]}, "mids": {}} for t in market.tenors]
        flows = self._flows(market, admin, rows)
        total = {"today": self._total([e["today"] for e in flows["table"] if e["today"]]),
                 "window": self._total([e["window"] for e in flows["table"] if e["window"]])}
        return {"today": flows["today"], "days": flows["days"], "lookback": flows["lookback"],
                "rows": [{k: e[k] for k in ("tenor", "days", "today", "window")} for e in flows["table"]], "total": total}

    @staticmethod
    def _total(parts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not parts:
            return None
        out: Dict[str, Any] = {"sold": sum(p["sold"] for p in parts), "bought": sum(p["bought"] for p in parts)}
        out["net"] = out["sold"] - out["bought"]
        for key in ("pnl_ret", "pnl_ois"):
            vals = [p[key] for p in parts]
            out[key] = None if any(v is None for v in vals) else sum(vals)
        return out
