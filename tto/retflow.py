"""The desk's own FX forwards per RET tenor (Günlük İşlemler): how much TRY was sold and bought, at what rate, against
its normal, what the flow earns against today's curve - and the RET move a heavy one-way flow suggests.

One aggregation, two readers: the fair value part of the RET dialog (the flow suggestions, ``retfair.py``) and the
"Pozisyon ve maliyet" panel of Günlük İşlemler.  The source is the blotter's own trades (``Store.trades``) and nothing
else - never Broker Chat, never a BIST swap quote.  OIS and bond trades sell or buy no TRY: forwards only.

In the desk's words:

* a forward the desk **bought** USD in (Alış, ``B``) is **TRY sold** ("TRY sattık" - TRY against USD): it is dealt on
  the RET **bid** and pays the TRY rate (payer, DV01 +);
* one it **sold** USD in (Satış, ``S``) is **TRY bought** ("TRY aldık"): dealt on the RET **ask**, receives the rate.

Amounts are USD (another currency against TRY at its USD equivalent, as the sheet's own tables take it).  A forward's
tenor is its days from its spot to its value date, spread over the two RET tenors around it linearly - the way the
sheet's forward buckets spread an amount (``blotter.split_weights``; the buckets are the RET tenors without TN,
Günlük İşlemler!O6:P19).  The cost ("maliyet") of a tenor's flow is the volume-weighted average TRY rate of the side
its net is on; the P&L against a curve is, trade by trade, its DV01 (TL, payer +) × (the curve's rate at the trade's own
days − the rate it was dealt at): + when the desk dealt better than the curve stands now.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import blotter as bl

#: the RET tenor that is no bucket of the sheet's forward summary (its days are the ON's)
NOT_A_BUCKET = ("TN",)
#: a net flow (USD) smaller than this is no flow (what is left of rounding)
EPS = 0.5


# ---------------------------------------------------------------------------------------------- the trades
def forwards(trades: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The forwards of a list of blotter trades that sell or buy TRY: ``{id, day, dir, usd, rate, days, dv01_tl}``.
    Left out: OIS and bond trades, a pair that is not against TRY, a trade without its TRY rate, days or amount."""
    out: List[Dict[str, Any]] = []
    for t in trades:
        if t.get("kind") != "fwd" or t.get("dir") not in ("B", "S") or not bl.in_summary(t):
            continue
        usd, rate, days = bl.usd_equivalent(t), t.get("try_rate"), t.get("days")
        if type(usd) is not float or not usd > 0 or type(rate) is not float or type(days) is not float or not days > 0:
            continue
        dv = t.get("dv01_tl")
        if type(dv) is not float:
            # a trade stored before its DV01 was kept: from its own rates (as the blotter's list does)
            dv = bl.forward_dv01(t["dir"], t.get("amount"), t.get("forward"), days, t.get("spot"), t.get("df_try"),
                                 t.get("df_usd"), rate, t.get("usd_rate")).get("tl")
        out.append({"id": t.get("id"), "day": t.get("trade_date"), "dir": t["dir"], "usd": usd, "rate": rate, "days": days,
                    "dv01_tl": dv if type(dv) is float else None})
    return out


def buckets_of(tenors: Sequence[Tuple[str, Any]]) -> List[Tuple[str, float]]:
    """The forward buckets of the sheet from the RET tenors ``[(label, days)]``: TN left out, days known."""
    return [(lab, float(d)) for lab, d in tenors if lab not in NOT_A_BUCKET and type(d) is float and d > 0]


# ---------------------------------------------------------------------------------------------- per tenor
def aggregate(fwds: Iterable[Dict[str, Any]], buckets: Sequence[Tuple[str, float]],
              ref_ret: Optional[Callable[[float], Optional[float]]] = None,
              ref_ois: Optional[Callable[[float], Optional[float]]] = None) -> Dict[str, Dict[str, Any]]:
    """Per bucket: TRY sold (USD) and its average rate, TRY bought and its, the net (sold − bought: + net TRY sold), the
    cost (the average rate of the side the net is on) and the P&L (TL) against ``ref_ret`` / ``ref_ois`` - a curve's
    rate at a number of days (``None``: no P&L; one trade without a rate of the curve leaves the bucket's P&L empty)."""
    labels = [b[0] for b in buckets]
    nodes = [b[1] for b in buckets]
    acc = {lab: {"sold": 0.0, "sold_x": 0.0, "bought": 0.0, "bought_x": 0.0, "pnl_ret": 0.0, "pnl_ois": 0.0,
                 "ret_gap": False, "ois_gap": False, "trades": set()} for lab in labels}
    if not nodes:
        return {}
    for f in fwds:
        refs = ((ref_ret(f["days"]) if ref_ret else None), (ref_ois(f["days"]) if ref_ois else None))
        for k, w in bl.split_weights(f["days"], nodes):
            a = acc[labels[k]]
            amt = f["usd"] * w
            side = "sold" if f["dir"] == "B" else "bought"
            a[side] += amt
            a[side + "_x"] += amt * f["rate"]
            a["trades"].add(f["id"])
            for key, ref in (("ret", refs[0]), ("ois", refs[1])):
                if ref is None or f["dv01_tl"] is None:
                    a[key + "_gap"] = True
                else:
                    a["pnl_" + key] += w * f["dv01_tl"] * (ref - f["rate"]) * 10000.0
    out: Dict[str, Dict[str, Any]] = {}
    for lab in labels:
        a = acc[lab]
        if not a["trades"]:
            continue
        sold_avg = a["sold_x"] / a["sold"] if a["sold"] > EPS else None
        bought_avg = a["bought_x"] / a["bought"] if a["bought"] > EPS else None
        net = a["sold"] - a["bought"]
        side = "sold" if net > EPS else ("bought" if net < -EPS else None)
        out[lab] = {"sold": a["sold"], "sold_avg": sold_avg, "bought": a["bought"], "bought_avg": bought_avg,
                    "net": net, "side": side, "cost": sold_avg if side == "sold" else (bought_avg if side == "bought" else None),
                    "trades": len(a["trades"]),
                    "pnl_ret": None if (ref_ret is None or a["ret_gap"]) else a["pnl_ret"],
                    "pnl_ois": None if (ref_ois is None or a["ois_gap"]) else a["pnl_ois"]}
    return out


def daily_nets(fwds: Iterable[Dict[str, Any]], buckets: Sequence[Tuple[str, float]]) -> Dict[str, Dict[str, float]]:
    """``{day: {bucket: net TRY sold (USD)}}`` - each day's net flow per tenor."""
    labels = [b[0] for b in buckets]
    nodes = [b[1] for b in buckets]
    out: Dict[str, Dict[str, float]] = {}
    if not nodes:
        return out
    for f in fwds:
        d = out.setdefault(str(f["day"]), {})
        sign = 1.0 if f["dir"] == "B" else -1.0
        for k, w in bl.split_weights(f["days"], nodes):
            d[labels[k]] = d.get(labels[k], 0.0) + sign * f["usd"] * w
    return out


def normal(nets: Dict[str, Dict[str, float]], days: Sequence[str], label: str) -> float:
    """A tenor's normal flow: the average size (USD, either way) of its daily net over ``days`` - a day without a
    trade counts as nothing.  0 when there are no days or no flow."""
    if not days:
        return 0.0
    return sum(abs((nets.get(d) or {}).get(label, 0.0)) for d in days) / float(len(days))


def curve_at(points: Sequence[Tuple[float, float]], days: float) -> Optional[float]:
    """A rate curve given at tenors ``[(days, rate)]`` read at ``days``: straight lines between them, flat beyond the
    ends - how the Forward sheet reads the RET at a value date (Forward!W48 / X48).  Of tenors with the same days the
    later one counts (Excel's MATCH)."""
    pts: Dict[float, float] = {}
    for d, r in points:
        if type(d) is float and type(r) is float:
            pts[d] = r
    if not pts:
        return None
    xs = sorted(pts)
    if days <= xs[0]:
        return pts[xs[0]]
    for x0, x1 in zip(xs, xs[1:]):
        if days <= x1:
            return pts[x0] + (pts[x1] - pts[x0]) * (days - x0) / (x1 - x0)
    return pts[xs[-1]]


# ---------------------------------------------------------------------------------------------- the suggestions
def _num(x: float, digits: int) -> str:
    text = "%.*f" % (digits, x)
    return text.replace(".", ",")


def mn_text(usd: float) -> str:
    """An amount in millions as the desk says it: 240, 12,5, 0,4."""
    x = round(abs(usd) / 1e6, 1)
    return ("%d" % x) if x == int(x) else _num(x, 1)


def pct_text(rate: float) -> str:
    return _num(rate * 100.0, 2)


def times_text(x: float) -> str:
    x = round(x, 1)
    return ("%d" % x) if x == int(x) else _num(x, 1)


def bp_text(x: float) -> str:
    """A signed number of bp: +5, −10."""
    return ("+" if x > 0 else "−" if x < 0 else "") + ("%d" % abs(int(round(x))))


def _grid(bp: float) -> float:
    return 5.0 * math.floor(bp / 5.0 + 0.5 + 1e-9)


def suggest(today: Dict[str, Dict[str, Any]], normals: Dict[str, float], order: Sequence[str],
            curve: Dict[str, Dict[str, Any]], sensitivity: float, margin: float, accepted: Optional[Dict[str, int]] = None,
            quiet_days: int = 0) -> List[Dict[str, Any]]:
    """The RET moves today's flows suggest - suggestions only, applied by nobody but a person.

    ``today``: :func:`aggregate` of today's forwards; ``normals``: each tenor's normal (:func:`normal`); ``order``: the
    RET tenors in order; ``curve``: per tenor ``{"pub_bid", "pub_ask", "cur_bid", "cur_ask"}`` - the published RET and
    the RET as it would be now (the fair value, else the published), fractions; ``sensitivity``: bp per 100 mn USD of
    today's net above its normal; ``margin``: the desk's minimum margin over cost (bp); ``accepted``: steps of today's
    suggestions accepted already (``{id: steps}``); ``quiet_days``: the days the normal is over (for the words).

    A tenor whose net today is above its normal moves by 5 bp for every full (5 / sensitivity) × 100 mn USD of the
    excess: up when TRY was sold (on the bid: the ask named, "ask +5"), down when TRY was bought (on the ask: "bid −5").
    The next tenor out (up) or in (down) moves by half of it, rounded up to a 5 bp step, so the curve does not kink.
    A move down never takes a tenor's ask below its flow's cost + the margin: it is cut to what is left, or dropped."""
    accepted = accepted or {}
    out: List[Dict[str, Any]] = []
    for label in order:
        agg = today.get(label)
        if not agg or agg.get("side") is None or sensitivity <= 0:
            continue
        sold = agg["side"] == "sold"
        sign = 1 if sold else -1
        net = abs(agg["net"])
        norm = max(0.0, float(normals.get(label) or 0.0))
        excess = net - norm
        if excess <= EPS:
            continue
        steps = int(math.floor(excess / 1e8 * sensitivity / 5.0 + 1e-9))
        sid = "%s:%s" % (label, "+" if sold else "-")
        steps -= int(accepted.get(sid) or 0)
        if steps < 1:
            continue
        i = order.index(label)
        moves: List[Tuple[str, int]] = [(label, steps)]
        j = i + 1 if sold else i - 1
        if 0 <= j < len(order):
            moves.append((order[j], int(math.ceil(steps / 2.0))))
        cost = agg["cost"]
        blocked: List[str] = []
        if not sold:
            # down: no ask below the flow's cost + margin (each tenor with its own flow's cost; the trigger's for itself)
            kept = []
            for lab, k in moves:
                c = cost if lab == label else ((today.get(lab) or {}).get("bought_avg") if (today.get(lab) or {}).get("side") == "bought" else None)
                ask = (curve.get(lab) or {}).get("cur_ask")
                if c is not None and type(ask) is float:
                    room = int(math.floor(((ask - c) * 10000.0 - margin) / 5.0 + 1e-9))
                    if room < k:
                        blocked.append(lab)
                        k = max(0, room)
                if k > 0:
                    kept.append((lab, k))
                elif lab == label:
                    kept = []
                    break
            moves = kept
        c = curve.get(label) or {}
        ref_side = "bid" if sold else "ask"
        ref = c.get("pub_" + ref_side)
        ref_text = ""
        if type(ref) is float and cost is not None:
            gap = int(round((ref - cost) * 10000.0))
            ref_text = "RET %s %s %s" % (ref_side, pct_text(ref), ("maliyetin %d bp %s" % (abs(gap), "üstünde" if gap > 0 else "altında"))
                                         if gap else "maliyetle aynı")
        heavy = ("normalin %s katı" % times_text(net / norm)) if norm > EPS else (
            "önceki %d iş gününde akış yok" % quiet_days if quiet_days else "normali yok")
        head = "%s'de bugün net %s mn USD TRY %s (%s)" % (label, mn_text(net), "sattık" if sold else "aldık", heavy)
        if cost is not None:
            head += ", ortalama %s ile" % pct_text(cost)
        side_word = "ask" if sold else "bid"
        item: Dict[str, Any] = {"id": sid, "tenor": label, "dir": sign, "steps": steps, "net": agg["net"], "normal": norm,
                                "ratio": (net / norm) if norm > EPS else None, "cost": cost, "excess": excess,
                                "side": side_word, "blocked": blocked}
        if not moves:
            item.update({"moves": {}, "ok": False,
                         "text": head + ("; " + ref_text if ref_text else "") + " → öneri yok: %s ask'ı maliyet + %s bp marjın altına iner"
                         % (label, _num(margin, 0) if margin == int(margin) else _num(margin, 1))})
            out.append(item)
            continue
        sizes = {lab: 5 * k * sign for lab, k in moves}
        if len(set(sizes.values())) == 1:
            what = "%s %s %s bp" % (" / ".join(lab for lab, _ in moves), side_word, bp_text(sizes[label]))
        else:
            what = ", ".join("%s %s %s bp" % (lab, side_word, bp_text(sizes[lab])) for lab, _ in moves)
        text = head + ("; " + ref_text if ref_text else "") + " → öneri " + what
        if blocked:
            text += " (maliyet + marj sınırıyla)"
        item.update({"moves": sizes, "ok": True, "text": text})
        out.append(item)
    return out
