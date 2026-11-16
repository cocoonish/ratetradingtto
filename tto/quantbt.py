"""Walk-forward backtest of the quant families: the very rules the live signals follow, run on the history as if each day
were today.

At a refit day T every family is fitted on the closes up to T only (a :class:`tto.quantfam.Ctx` whose "today" is the
day after T); then, day by day until the next refit, its monitors are scored with that day's closes as the live values
and :func:`tto.quantfam.make_signal` decides - the same thresholds and gates.  A monitor that becomes a signal (it was
none the day before) opens a trade at that day's close; the trade keeps the monitor it was opened with and closes at
its target, its stop or after its holding (the signal's own, at most the desk's log days), on the closes of the days
after - nothing after a day is used to decide on it.

Per family and signal type: trades, hit rate, average P&L in σ (the signal's own, as the live log counts it) and in its
unit (bp, %, vol; carry + roll in it where the history has it: an FX trade's excess return carries its carry, a rate
package's history has no carry engine - its move only), TRY (a rate package with the desk's package DV01, an FX trade
per 1 mn of the base currency), Sharpe (mean / σ of the trades' P&L in σ, × √ trades a year) and the largest drawdown
of the cumulative P&L in σ.
"""
from __future__ import annotations

import datetime as _dt
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import quantfam as qf

BT_STEP = 10                   # business days between two refits (every family fitted again)
BT_DAYS = 250                  # the days tested: the last year (the year before it is the first fits' window)
BT_KEEP = 300                  # trades kept for the page


def bt_type(m: qf.Monitor) -> str:
    """The signal type within a family a backtest reports apart: the version of a fly / spread, FX against the rest."""
    v = m.info.get("version")
    if v:
        return v
    if m.fx:
        return "FX"
    return m.asset or ""


def _pnl_try(sg: Dict[str, Any], pnl: float, cfg: Dict[str, Any]) -> Optional[float]:
    unit = sg.get("pnl_unit")
    if unit == "bp":                                      # bp of the package's main-leg DV01: USD a bp × USDTRY of the fit
        usd, fx = cfg.get("dv01_usd"), cfg.get("usdtry")
        return pnl * float(usd) * float(fx) if usd and fx else None
    fx = sg.get("fx") or {}
    if unit == "%" and fx.get("spot") and fx.get("try_per_quote"):
        return pnl / 100.0 * 1e6 * fx["spot"] * fx["try_per_quote"]
    return None


def summarize(trades: Sequence[Dict[str, Any]], first: Optional[str], last: Optional[str]) -> Dict[str, Any]:
    """Trades, hits, averages, Sharpe and the largest drawdown of a list of closed trades."""
    n = len(trades)
    if not n:
        return {"trades": 0, "hits": 0, "hit": None, "avg_sigma": None, "avg": None, "unit": None, "avg_try": None, "sharpe": None, "max_dd": None}
    sig = [t["pnl_sigma"] for t in trades if t.get("pnl_sigma") is not None]
    units = {t.get("unit") for t in trades}
    unit = units.pop() if len(units) == 1 else None
    tries = [t["pnl_try"] for t in trades if t.get("pnl_try") is not None]
    hits = sum(1 for t in trades if (t.get("pnl") or 0.0) > 0)
    years = max((_dt.date.fromisoformat(last) - _dt.date.fromisoformat(first)).days / 365.0, 1.0 / 12.0) if first and last else 1.0
    sharpe = None
    if len(sig) >= 2:
        m = sum(sig) / len(sig)
        sd = math.sqrt(sum((x - m) ** 2 for x in sig) / (len(sig) - 1))
        sharpe = m / sd * math.sqrt(len(sig) / years) if sd > 0 else None
    cum, peak, dd = 0.0, 0.0, 0.0
    for t in sorted(trades, key=lambda x: (x["exit_day"], x["sid"])):
        cum += t.get("pnl_sigma") or 0.0
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"trades": n, "hits": hits, "hit": hits / n, "avg_sigma": sum(sig) / len(sig) if sig else None,
            "avg": sum(t["pnl"] for t in trades) / n if unit else None, "unit": unit, "avg_try": sum(tries) / len(tries) if tries else None,
            "sharpe": sharpe, "max_dd": dd}


def backtest(days: Sequence[str], make_ctx: Callable[[str], qf.Ctx], runner: Callable[[qf.Ctx], List[qf.Monitor]],
             closes: Dict[str, Dict[str, float]], cfg: Dict[str, Any], step: int = BT_STEP,
             pause: Optional[Callable[[], None]] = None, deadline: Optional[float] = None) -> Dict[str, Any]:
    """The walk-forward run over ``days`` (business days, oldest first): ``make_ctx(T)`` gives the context fitted on the
    closes up to T, ``runner(ctx)`` its monitors, ``closes`` every key's closes (the "live" values of each day)."""
    t0 = time.perf_counter()
    days = list(days)
    positions: Dict[str, Dict[str, Any]] = {}
    trades: List[Dict[str, Any]] = []
    prev_live: set = set()
    refits = 0
    log_days = int(cfg.get("log_days") or 20)
    stopped = False
    for i in range(0, len(days), max(1, step)):
        if deadline is not None and time.perf_counter() > deadline:
            stopped = True
            break
        ctx = make_ctx(days[i])
        mons = runner(ctx)
        refits += 1
        for t in days[i:i + max(1, step)]:
            today = _dt.date.fromisoformat(t)
            live = {k: v[t] for k, v in closes.items() if t in v}
            # what is open first, each with the monitor (and the fit) it was opened with
            for sid, pos in list(positions.items()):
                pc = pos["ctx"]
                pc.today, pc.today_iso = today, t
                try:
                    lvl = pos["m"].calc(pc.derive_live(live))
                except Exception:  # noqa: BLE001 - a level that cannot be read today: tomorrow
                    lvl = None
                if lvl is None:
                    continue
                pos["held"] += 1
                s = pos["s"]
                outcome = None
                if pos["target"] is not None and s * (lvl - pos["target"]) >= 0:
                    outcome = "hedef"
                elif pos["stop"] is not None and s * (lvl - pos["stop"]) <= 0:
                    outcome = "stop"
                elif pos["held"] >= pos["hold"]:
                    outcome = "süre"
                if outcome:
                    move = s * (lvl - pos["entry"])
                    pnl = move * pos["factor"] + (pos["carry_day"] * pos["held"] if pos["carry_day"] is not None else 0.0)
                    tr = {"sid": sid, "family": pos["family"], "type": pos["type"], "entry_day": pos["day"], "exit_day": t, "dir": s,
                          "entry": pos["entry"], "exit": lvl, "outcome": outcome, "held": pos["held"], "pnl": pnl, "unit": pos["unit"],
                          "pnl_sigma": move / pos["scale"] if pos["scale"] else None, "expression": pos["expression"]}
                    tr["pnl_try"] = _pnl_try(pos["sg"], pnl, cfg)
                    trades.append(tr)
                    del positions[sid]
            ctx.today, ctx.today_iso = today, t
            qf.score_all(ctx, mons, live)
            live_now = set()
            for m in mons:
                sg = qf.make_signal(m, cfg, "bt")
                if sg is None or sg["gated"]:
                    continue
                live_now.add(m.sid)
                if m.sid in prev_live or m.sid in positions:
                    continue
                unit, factor = m.pnl or (None, None)
                hold = int(round(sg.get("hold") or float(cfg.get("horizon") or 20)))
                carry_day = None
                if not m.fx and sg.get("carry_week") is not None:
                    carry_day = sg["carry_week"] / 5.0
                positions[m.sid] = {"m": m, "ctx": ctx, "s": sg["direction"], "entry": m.level, "target": sg["target"], "stop": sg["stop"],
                                    "scale": sg["scale"], "hold": max(1, min(hold, log_days)), "held": 0, "day": t, "factor": factor or 1.0,
                                    "unit": unit, "carry_day": carry_day, "family": m.family, "type": bt_type(m), "sg": sg,
                                    "expression": sg["expression"]}
            prev_live = live_now
        if pause is not None:
            pause()
    first, last = (days[0], days[-1]) if days else (None, None)
    fams: Dict[str, Dict[str, Any]] = {}
    for fam in sorted({t["family"] for t in trades}):
        mine = [t for t in trades if t["family"] == fam]
        row = summarize(mine, first, last)
        row["types"] = {ty: summarize([t for t in mine if t["type"] == ty], first, last) for ty in sorted({t["type"] for t in mine})}
        fams[fam] = row
    return {"families": fams, "trades": trades[-BT_KEEP:], "n_trades": len(trades), "open": len(positions), "first": first, "last": last,
            "refits": refits, "step": step, "days": len(days), "ms": round((time.perf_counter() - t0) * 1000.0, 1), "complete": not stopped}


def bt_text(stats: Optional[Dict[str, Any]], years: Optional[float] = None) -> str:
    """"bu aile son 2 yılda 41 işlem, %58 isabet, ort. +0,4σ" - what a signal carries of its family's backtest."""
    if not stats or not stats.get("trades"):
        return "geri testte işlem yok"
    span = "son %s yılda" % qf._g(years, 0 if years and abs(years - round(years)) < 0.05 else 1) if years else "geri testte"
    return "bu aile %s %d işlem, %%%s isabet, ort. %sσ" % (span, stats["trades"], qf._g((stats.get("hit") or 0.0) * 100.0, 0),
                                                          qf._sg(stats.get("avg_sigma"), 1))


def bt_gate(stats: Optional[Dict[str, Any]], cfg: Dict[str, Any]) -> Optional[str]:
    """The desk's floor on a family's backtest (``bt_mute``): the reason a signal is held back, ``None`` if it is not."""
    if str(cfg.get("bt_mute") or "kapalı") != "açık" or not stats:
        return None
    if (stats.get("trades") or 0) < int(cfg.get("bt_min_trades") or 10):
        return None
    hit, sharpe = stats.get("hit"), stats.get("sharpe")
    if hit is not None and hit < float(cfg.get("bt_min_hit") or 0.0):
        return "geri testte zayıf: isabet %%%s < %%%s" % (qf._g(hit * 100.0, 0), qf._g(float(cfg["bt_min_hit"]) * 100.0, 0))
    if sharpe is not None and sharpe < float(cfg.get("bt_min_sharpe") or 0.0):
        return "geri testte zayıf: Sharpe %s < %s" % (qf._g(sharpe, 2), qf._g(float(cfg["bt_min_sharpe"]), 2))
    return None
