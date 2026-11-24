"""Konsensüs: the instruments on which three or more families' confident lines agree now - one line each, at the top of
the Sinyaller list (the group "Konsensüs" before the others)::

    AL USDJPY spot · 3 aile (Makine öğrenmesi, Trend, Opsiyon → spot) · birleşik 1,2 mn USD · hedef 152,630 · stop 148,350
    (seviyeler: Makine öğrenmesi, en iyi örneklem dışı kayıt) · aile isabetleri %58 / %55 / %57

**A view of existing lines.**  It is made from the list's live lines (``quant.Quant._publish``: the ones no gate holds -
a "düşük güven" line is not counted) each time the list is: it appears and disappears as they do, has no log and no
alarm of its own (the families alert themselves), and is no family of the backtest.

**The same instrument.**  Lines compare on what they trade (``instrument`` and ``asset`` of the signal, and the legs
they are made of - their keys and how each leg stands to the others): FX lines with FX lines of the same pair and
instrument, rates lines with the same package - never across instruments (a 2Y outright is not a 1Y/2Y spread, a spot is
not a forward).  The direction is the side of the instrument's first leg (by key).  At least ``MIN_FAMILIES`` different
families on one side and none on the other: a family on the other side makes it no consensus, as one family with lines
on both sides does.

**The line.**  The families named best record first; **levels**: the calibrated levels of the family with the best
out-of-sample record among them (``quantlevels``: out-of-sample before in-sample, then the expectancy a trade, then
the hit rate) - entry, target and stop as that family's line has them, the line says whose; **size**: the median of the
families' sizes (each in the instrument's desk unit: 1 mn of the base, 1.000 $ DV01 …) - a size one of the families
takes itself; their sum would stack three lines' risk on one instrument, and each family's own line is still there for
whoever takes it.  Each family's hit rate (its levels' record, the trade count) in the same order.  The card (a click)
is that family's, with the consensus told above it.
"""
from __future__ import annotations

import copy
import math
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import quantfam as qf

GROUP = "Konsensüs"
SLUG = "konsensus"
PREFIX = "konsensus:"
MIN_FAMILIES = 3
PRIORITY = 0                     # before every group of the list (quantuniv.PRIORITY: G10 spot's 1 …)


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def ident(sg: Dict[str, Any]) -> Tuple[Optional[Tuple[Any, ...]], int]:
    """What a line trades and which way: ``((asset, instrument, ((leg key, its side against the first leg's) …)), the
    first leg's side)`` - the first leg by key - or ``(None, 0)`` for a line without legs."""
    legs = [l for l in sg.get("legs") or () if l.get("key")]
    if not legs:
        return None, 0
    ref = min(legs, key=lambda l: l["key"])
    side = int(qf.sign(ref.get("side") or 0))
    if not side:
        return None, 0
    shape = tuple(sorted((l["key"], int(qf.sign(l.get("side") or 0)) * side) for l in legs))
    return (sg.get("asset") or "", sg.get("instrument") or "", shape), side


def record_key(sg: Dict[str, Any]) -> Tuple[int, int, float, float]:
    """A line's levels' record, best first: calibrated, out of sample, the expectancy a trade (σ), the hit rate."""
    lv = sg.get("levels") or {}
    ok = bool(lv.get("ok"))
    exp, hit = _num(lv.get("exp")), _num(lv.get("hit"))
    return (1 if ok else 0, 1 if ok and lv.get("oos") else 0, exp if ok and exp is not None else -1e9, hit if ok and hit is not None else -1.0)


def _k(sg: Dict[str, Any]) -> float:
    """A line's size in its instrument's desk unit (a universe line's ``info["k"]``; any other the unit itself)."""
    k = _num((sg.get("info") or {}).get("k"))
    return k if k and k > 0 else 1.0


def _hit(sg: Dict[str, Any]) -> str:
    lv = sg.get("levels") or {}
    if lv.get("ok") and _num(lv.get("hit")) is not None:
        return "%%%s" % qf._g(lv["hit"] * 100.0, 0)
    return "—"


def _price(sg: Dict[str, Any], which: str) -> str:
    """A line's entry / target / stop as it says it: an FX line's in its price, a level of the model's own in the traded
    instrument's (the FRA's rate, ``quote``) with the model's gap beside it, any other's in its level."""
    px = sg.get("px")
    if px:
        v = px.get(which)
        return qf._th(v, px.get("digits") or 4) if v is not None else "—"
    q = sg.get("quote")
    if q:
        return "%s (%s)" % (qf.quote_text(q, q.get(which)), qf.gap_text(q, sg.get(which))) if q.get(which) is not None else "—"
    return qf._level_text(sg.get(which), sg.get("unit") or "", sg.get("digits") or 2) + qf.sheet_text(sg, sg.get(which))


def _size_text(best: Dict[str, Any], k: float, reg: Any) -> str:
    """The combined size in the desk's words: the instrument's own (the universe's ``size_text``), else the best line's
    size scaled."""
    key = (best.get("info") or {}).get("universe")
    inst = reg.get(key) if reg is not None and key else None
    if inst is not None:
        try:
            return inst.size_text(k)
        except Exception:  # noqa: BLE001 - a size that cannot be said is said as a multiple
            pass
    return "%s × %s" % (qf._g(k, 2), (best.get("info") or {}).get("size") or "1 birim")


def _scaled(best: Dict[str, Any], r: float) -> Dict[str, Any]:
    """The best line at the combined size (``r`` × its own): its legs' DV01 and nominal, a rates or linear money's TL
    - an FX line's money stays per 1 mn of the base, its expectancy at the size."""
    sg = copy.deepcopy(best)
    for leg in sg.get("legs") or ():
        for k in ("dv01", "dv01_usd", "notional"):
            if _num(leg.get(k)) is not None:
                leg[k] = leg[k] * r
    for p in sg.get("packages") or ():
        for leg in p.get("legs") or ():
            for k in ("dv01", "dv01_usd", "notional"):
                if _num(leg.get(k)) is not None:
                    leg[k] = leg[k] * r
    mo = sg.get("money")
    if isinstance(mo, dict) and not sg.get("px"):
        for k in ("per_bp", "per_unit", "total", "carry", "move", "target", "stop"):
            if _num(mo.get(k)) is not None:
                mo[k] = mo[k] * r
        if _num(sg.get("pnl_try")) is not None:
            sg["pnl_try"] = sg["pnl_try"] * r
        lv = sg.get("levels")
        if isinstance(lv, dict) and _num(lv.get("money")) is not None:
            lv["money"] = lv["money"] * r
    if _num(sg.get("exp_try")) is not None:
        sg["exp_try"] = sg["exp_try"] * r
    return sg


def lines(live: Sequence[Dict[str, Any]], reg: Any = None) -> List[Dict[str, Any]]:
    """The consensus lines of the list's live lines (no gate holding them): one per instrument with at least
    ``MIN_FAMILIES`` families on one side and none on the other - most families first, then the expected P&L."""
    by: Dict[Tuple[Any, ...], Dict[str, Dict[int, List[Dict[str, Any]]]]] = {}
    for sg in live:
        if sg.get("gated") or str(sg.get("id") or "").startswith(PREFIX):
            continue
        key, side = ident(sg)
        if key is None:
            continue
        by.setdefault(key, {}).setdefault(sg["family"], {}).setdefault(side, []).append(sg)
    out: List[Dict[str, Any]] = []
    for key, fams in by.items():
        sides = {s for f in fams.values() for s in f}
        if len(sides) != 1 or len(fams) < MIN_FAMILIES:
            continue                                    # (a family the other way - or both ways - is no consensus)
        side = sides.pop()
        # each family's line: its best record if it has several on the instrument
        picks = [max(f[side], key=record_key) for f in fams.values()]
        picks.sort(key=lambda s: (tuple(-x for x in record_key(s)), s["family"]))
        out.append(_line(picks, side, reg))
    out.sort(key=lambda s: (-s["consensus"]["n"], -(s.get("exp_try") if _num(s.get("exp_try")) is not None else -1e18), s["id"]))
    return out


def _line(picks: List[Dict[str, Any]], side: int, reg: Any) -> Dict[str, Any]:
    """One instrument's consensus line from its families' lines (best record first): the best's line at the combined
    size, its levels, the families and their hit rates."""
    best = picks[0]
    ks = [_k(s) for s in picks]
    k = statistics.median(ks)
    r = k / _k(best)
    sg = _scaled(best, r)
    names = [s["family_label"] for s in picks]
    size = _size_text(best, k, reg)
    inst = best.get("instrument") or ""
    info = best.get("info") or {}
    verbs = info.get("verbs")
    verb = (verbs[0] if best["direction"] > 0 else verbs[1]) if isinstance(verbs, (list, tuple)) and len(verbs) == 2 else ""
    head = ("%s %s" % (verb, inst)).strip() if verb else (best.get("trade_tr") or best.get("expression") or inst)
    lv = best.get("levels") or {}
    whose = ("seviyeler: %s, en iyi örneklem dışı kayıt" if lv.get("ok") and lv.get("oos") else
             "seviyeler: %s, en iyi kayıt (örneklem içi)" if lv.get("ok") else "seviyeler: %s, kendi kuralı - hiçbirinin ayarlı seviyesi yok") % names[0]
    hits = " / ".join(_hit(s) for s in picks)
    text = " · ".join([head, "%d aile (%s)" % (len(picks), ", ".join(names)), "birleşik %s" % size, "hedef %s" % _price(best, "target"),
                       "stop %s (%s)" % (_price(best, "stop"), whose), "aile isabetleri %s" % hits])
    fams = [{"family": s["family"], "label": s["family_label"], "sid": s["id"], "k": _k(s), "size": (s.get("info") or {}).get("size"),
             "hit": (s.get("levels") or {}).get("hit") if (s.get("levels") or {}).get("ok") else None,
             "n": (s.get("levels") or {}).get("n") if (s.get("levels") or {}).get("ok") else None,
             "exp": (s.get("levels") or {}).get("exp") if (s.get("levels") or {}).get("ok") else None,
             "oos": bool((s.get("levels") or {}).get("oos")), "z": s.get("z"), "line": s.get("line") or s.get("expression")} for s in picks]
    told = ", ".join("%s (isabet %s%s)" % (f["label"], _hit(s), " · %d işlem" % f["n"] if f["n"] else "") for f, s in zip(fams, picks))
    ref = (info.get("universe") or inst or best["id"])
    sg.update({"id": PREFIX + str(ref), "family": "konsensus", "family_label": GROUP, "families": [s["family"] for s in picks],
               "group": GROUP, "tier": None, "priority": PRIORITY, "tag": "", "gated": "", "line": text, "expression": text,
               "agree": len(picks), "agree_with": names, "conflict": 0, "conflict_with": [], "live": any(s.get("live") for s in picks),
               "info": dict(info, model="%s · %d aile" % (GROUP, len(picks)), size=size, k=k),
               "consensus": {"n": len(picks), "side": side, "ref": best["id"], "best": best["family"], "k": k, "size": size, "families": fams}})
    sg["plain"] = ("Konsensüs: %d aile aynı yönde - %s. Seviyeler: %s (en iyi kayıt: %s); birleşik büyüklük ailelerin büyüklüklerinin "
                   "medyanı (%s): toplamları aynı enstrümanda riski katlardı, her ailenin kendi satırı listede duruyor. %s" % (
                       len(picks), told, names[0], qf.levels_text(lv) or "ayarlı seviyesi yok", size, best.get("plain") or ""))
    sg["thesis"] = "Konsensüs: %s." % text
    return sg


def group_count(signals: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The group's button above the list: its lines (all live: a consensus is never "düşük güven")."""
    n = sum(1 for s in signals if s.get("group") == GROUP)
    return {"id": GROUP, "label": GROUP, "slug": SLUG, "n": n, "live": n, "tag": ""}
