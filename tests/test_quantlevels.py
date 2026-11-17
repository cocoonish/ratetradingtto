"""Levels calibrated on what past trades actually did (``tto/quantlevels.py``): planted paths whose best stop and
target are known, the closes corrected for what they miss (a stop resting all day is hit between them - paths drawn
in fine steps, checked on their closes -, and the stop leaves the floor where that matters), Ödül / risk at least 1
whatever the paths, no look-ahead (a month's levels from the trades that had ended before it - in the layer and
through the backtest's recorded paths), a line whose levels lost money "düşük güven" with its reason and still in the
list, a group with few trades taking its family's levels, the walk-forward kept (a second calibration of the same
trades chooses nothing), make_signal's target / stop / Ödül / risk / İsabet / Beklenen K/Z from them, the families
that keep their own levels.  (Trend's trailing stop, Carry + momentum's basket levels and ML's are in their own test
files.)"""
from __future__ import annotations

import datetime as dt
import math
import random

import pytest

import quant_synth
from tto import quantbt as qbt
from tto import quantfam as qf
from tto import quantlevels as qlv
from tto import quantuniv as qu
from tto.quant import DEFAULTS

TODAY = "2026-11-17"


def cfg(**kw):
    out = dict(DEFAULTS, usdtry=42.0)
    out.update(kw)
    return out


def days_from(start, n):
    """``n`` week days from ``start`` (ISO), oldest first."""
    d = dt.date.fromisoformat(start)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def trade(path, entry, group="TRY OIS", family="pca", fair=None, carry=0.0, sid="x"):
    days = days_from((dt.date.fromisoformat(entry) + dt.timedelta(days=1)).isoformat(), len(path))
    return {"family": family, "group": group, "sid": sid, "entry_day": entry, "days": days, "end_day": days[-1], "path_sigma": list(path),
            "carry_sigma": carry, "carry_in": bool(carry), "fair_sigma": fair}


def planted(n_win=60, n_lose=40, start="2025-01-06"):
    """Winners dip by 0,3 … 1,1 σ (evenly) then go to +2σ; losers fall to −2,5σ past −1,3σ on their second close."""
    out = []
    entries = days_from(start, n_win + n_lose)
    for i in range(n_win):
        d = 0.3 + 0.8 * i / (n_win - 1)
        out.append(trade([-d, -d / 2, 0.5, 1.5, 2.0], entries[i], sid="w%d" % i))
    for j in range(n_lose):
        out.append(trade([-0.5, -1.3, -2.0, -2.4, -2.5], entries[n_win + j], sid="l%d" % j))
    return out


# ================================================================================================ known answers
BS5 = qlv.BETA / math.sqrt(5)                                            # (the correction's shift of a five-close path: 0,26σ)


def test_planted_paths_give_the_stop_where_the_winners_never_went_and_the_target_they_reached(monkeypatch):
    ts = [qlv.Trade(r) for r in planted()]
    ch = qlv.choose(ts, "fixed")
    # the stop: the winners' MAE's 90th percentile (0,3 … 1,1 evenly: 1,02) beyond what the closes miss (+ β σ a close:
    # 0,26σ) - nearer ones stop winners, the losers go through any of them on their second close (−1,3)
    dips = sorted(0.3 + 0.8 * i / 59 for i in range(60))
    p90 = qlv._q(dips, 0.9)
    k = math.ceil((p90 + BS5) * 100.0 - 1e-6) / 100.0
    assert ch["rule"] == "fixed" and ch["k"] == pytest.approx(k) == 1.29
    # the target: the winners close at +2σ, which reaches no target past 2 − 0,26 (a touch is not a fill): the best
    # is to hold them to their last close - a target they never reach
    assert ch["m"] + BS5 > 2.0
    stopped = [d for d in dips if d >= k - BS5]                              # (stopped at the stop: their closes stay above it)
    want = ((60 - len(stopped)) * 2.0 - len(stopped) * k - 40 * 1.3) / 100.0
    assert ch["exp"] == pytest.approx(want) and ch["hit"] == pytest.approx((60 - len(stopped)) / 100.0) and ch["n"] == 100
    assert ch["rr"] == pytest.approx(ch["m"] / ch["k"]) and ch["rr"] >= 1.0
    # one trade played at those levels: held to its last close; a loser's stop at the close through it; none at 3σ
    w, l = qlv.Trade(planted()[0]), qlv.Trade(planted()[-1])
    assert qlv.play_fixed(w, ch["k"], ch["m"]) == (2.0, True, 5, "süre")
    assert qlv.play_fixed(l, ch["k"], ch["m"]) == (-1.3, False, 2, "stop")
    assert qlv.play_fixed(l, 3.0, 4.0) == (-2.5, False, 5, "süre")
    # the correction on one path: a close 0,8σ down is within 0,26σ of a 1σ stop - stopped, at the stop; a close at the
    # target is no fill - one 0,26σ past it is (at the target)
    near = qlv.Trade(trade([-0.8, 0.5, 1.2, 1.5, 1.7], "2026-03-02"))
    assert qlv.play_fixed(near, 1.0, 1.5) == (-1.0, False, 1, "stop")
    assert qlv.play_fixed(w, 1.0, 2.0) == (2.0, True, 5, "süre") and qlv.play_fixed(w, 1.0, 1.7) == (1.7, True, 5, "hedef")
    assert qlv.play_fixed(w, 0.5, 2.0) == (-0.5, False, 1, "stop")      # (its first close, 0,3σ down: within 0,26σ of a 0,5σ stop)
    # without it (the closes taken as they are): the old answer - the stop at the 90th percentile, the target at +2σ
    monkeypatch.setattr(qlv, "BETA", 0.0)
    raw = qlv.choose([qlv.Trade(r) for r in planted()], "fixed")
    assert (raw["k"], raw["m"]) == (pytest.approx(round(p90, 2)), pytest.approx(2.0)) and raw["k"] < ch["k"]
    assert qlv.play_fixed(qlv.Trade(trade([-0.8, 0.5, 1.2, 1.5, 1.7], "2026-03-02")), 1.0, 1.5) == (1.5, True, 4, "hedef")


def test_a_mean_reversion_s_fair_value_target_and_its_stop_at_most_as_far():
    """Every trade knows its distance to the window's mean: the target there, the stop k σ but never farther than it -
    Ödül / risk ≥ 1 on every trade; the planted reversion (through the mean on the third close after a 0,4σ dip, then
    back where it came from) takes it over any fixed target."""
    out = []
    entries = days_from("2025-02-03", 80)
    rnd = random.Random(5)
    for i, e in enumerate(entries):
        f = 1.0 + rnd.random()                                          # the mean 1 … 2σ away
        if i % 5:
            out.append(trade([-0.4, f * 0.6, f + 0.4, f * 0.3, 0.0], e, fair=f, sid="r%d" % i))
        else:
            out.append(trade([-0.6, -1.5, -2.0, -2.2, -2.2], e, fair=f, sid="r%d" % i))
    ts = [qlv.Trade(r) for r in out]
    ch = qlv.choose(ts, "fixed")
    assert ch["rule"] == "fair" and ch["rr"] >= 1.0
    for t in ts:
        x, hit, h, how = qlv.play_fair(t, ch["k"])
        assert how in ("hedef", "stop") and (x == pytest.approx(t.fair) if how == "hedef" else x <= -min(ch["k"], t.fair))
    # a reversion that only closes at the mean does not reach it (a touch is not a fill): held to its last close
    t = qlv.Trade(trade([-0.4, 0.9, 1.5, 0.45, 0.0], "2026-03-02", fair=1.5))
    assert qlv.play_fair(t, 1.0) == (0.0, False, 5, "süre")


# ================================================================================================ closes only
def _fine(n_paths, closes, steps, seed, mus=(0.0,)):
    """Paths in σ of the holding drawn in ``steps`` fine steps a close: (the closes, every fine step) - the day between
    two closes is in the fine steps only."""
    rnd = random.Random(seed)
    sd = 1.0 / math.sqrt(closes * steps)
    out = []
    for i in range(n_paths):
        mu = mus[i % len(mus)] / (closes * steps)
        x, fine, at = 0.0, [], []
        for _ in range(closes):
            for _ in range(steps):
                x += mu + rnd.gauss(0.0, sd)
                fine.append(x)
            at.append(x)
        out.append((at, fine))
    return out


def test_a_stop_resting_all_day_is_hit_between_the_closes_more_often_than_they_show(monkeypatch):
    """Driftless paths of five closes drawn in fifty steps each: a stop 0,8σ away is touched by the fine steps far more
    often than the closes go through it; with the correction the closes count about as many - and a target as many or
    fewer (a touch is not a fill)."""
    paths = _fine(3000, 5, 50, 7)
    k = 0.8
    touched = sum(1 for _, fine in paths if min(fine) <= -k) / len(paths)

    def rates(beta):
        monkeypatch.setattr(qlv, "BETA", beta)
        stops = targets = 0
        for at, _ in paths:
            t = qlv.Trade(trade(at, "2026-03-02"))
            stops += qlv.play_fixed(t, k, qlv.M_MAX)[3] == "stop"
            targets += qlv.play_fixed(t, 3.0, k)[3] == "hedef"
        return stops / len(paths), targets / len(paths)

    raw_stop, raw_target = rates(0.0)
    stop, target = rates(0.5826)
    assert raw_stop < touched - 0.05                                     # (the closes alone: a fourth of the touches missed)
    assert stop > raw_stop and abs(stop - touched) < 0.05 and abs(stop - touched) < abs(raw_stop - touched)
    assert target < raw_target


def test_the_stop_leaves_the_floor_where_the_closes_hide_the_dips_and_trades_better_intraday(monkeypatch):
    """Winners whose closes come within 0,1 – 0,2σ of a 0,5σ stop: on the closes as they are, the floor (0,5σ) is the
    best stop; corrected, a stop beyond what the closes miss.  On paths drawn in fine steps (a mix of trends up and
    down, five closes a trade), the levels chosen with the correction do better when a stop and a target rest all day."""
    planted_ = []
    entries = days_from("2025-01-06", 100)
    for i in range(60):
        d = 0.3 + 0.1 * i / 59
        planted_.append(trade([-d, 0.2, 0.7, 1.2, 1.5], entries[i], sid="w%d" % i))
    for j in range(40):
        planted_.append(trade([-0.7, -1.0, -1.3, -1.5, -1.6], entries[60 + j], sid="l%d" % j))
    sims = _fine(600, 5, 50, 11, mus=(1.2, 1.2, -0.6))
    entries = days_from("2025-01-06", len(sims))

    def chosen(beta):
        monkeypatch.setattr(qlv, "BETA", beta)
        return (qlv.choose([qlv.Trade(r) for r in planted_], "fixed"),
                qlv.choose([qlv.Trade(trade(at, entries[i], sid="s%d" % i)) for i, (at, _) in enumerate(sims)], "fixed"))

    def intraday(ch):                                                    # (the first fine step at the target or the stop: filled there)
        tot = 0.0
        for _, fine in sims:
            x = fine[-1]
            for v in fine:
                if v >= ch["m"] or v <= -ch["k"]:
                    x = ch["m"] if v >= ch["m"] else -ch["k"]
                    break
            tot += x
        return tot / len(sims)

    raw_p, raw_s = chosen(0.0)
    cor_p, cor_s = chosen(0.5826)
    assert raw_p["k"] == qlv.K_RANGE[0] and cor_p["k"] > qlv.K_RANGE[0] + 0.1 and cor_p["m"] < raw_p["m"]
    assert raw_s["k"] == qlv.K_RANGE[0] and cor_s["k"] > qlv.K_RANGE[0] + 0.1
    assert intraday(cor_s) > intraday(raw_s)
    assert cor_s["exp"] < intraday(cor_s)                                  # (the record shown: on the safe side of the intraday one)


# ================================================================================================ the ratio, the pool, the cache
def test_odul_risk_is_at_least_one_whatever_the_paths():
    rnd = random.Random(17)
    for seed in range(12):
        rnd.seed(seed)
        recs = []
        for i, e in enumerate(days_from("2025-01-06", 120)):
            drift = rnd.gauss(0.0, 0.2)
            x, path = 0.0, []
            for _ in range(rnd.randint(3, 15)):
                x += drift + rnd.gauss(0.0, 0.45)
                path.append(x)
            recs.append(trade(path, e, group=("TRY OIS", "G10 spot")[i % 2], fair=abs(rnd.gauss(1.2, 0.5)) + 0.05 if seed % 2 else None,
                              sid="s%d" % i))
        book = qlv.calibrate(recs, "pca", TODAY)
        for g, gd in book.groups.items():
            for M, ch in gd["months"].items():
                assert ch["rr"] >= 1.0 - 1e-9 and qlv.K_RANGE[0] <= ch["k"] <= qlv.K_RANGE[1], (seed, g, M, ch)
                if ch["rule"] == "fixed":
                    assert ch["k"] <= ch["m"] <= qlv.M_MAX


def test_a_group_with_few_trades_takes_its_family_s_pooled_levels():
    recs = planted()
    few = [trade([0.4, 1.0, 1.5, 2.1, 2.2], e, group="G10 spot", sid="g%d" % i) for i, e in enumerate(days_from("2025-03-03", 8))]
    book = qlv.calibrate(recs + few, "pca", TODAY)
    ois, g10 = book.line("TRY OIS"), book.line("G10 spot")
    fam = qlv.choose([qlv.Trade(r) for r in recs + few], "fixed")
    assert ois["ok"] and ois["scope"] == "grup" and g10["ok"] and g10["scope"] == "aile"
    assert (g10["k"], g10["m"]) == (fam["k"], fam["m"]) != (None, None)
    # fewer than 30 in the family too: no levels, and the line says why
    alone = qlv.calibrate(few, "pca", TODAY)
    lv = alone.line("G10 spot")
    assert not lv["ok"] and "en az %d" % qlv.MIN_TRADES in lv["why"] and "8 işlem" in lv["why"]
    assert not alone.line("DİBS")["ok"]


def test_the_calibrations_are_kept_by_family_group_and_month():
    qlv.reset()
    recs = planted()
    c0 = dict(qlv.STATS)
    a = qlv.calibrate(recs, "pca", TODAY)
    chosen = qlv.STATS["chosen"] - c0["chosen"]
    assert chosen > 0
    b = qlv.calibrate(recs, "pca", TODAY)                                 # the same trades: nothing chosen again
    assert qlv.STATS["chosen"] - c0["chosen"] == chosen and a.to_json() == b.to_json()
    # a revised close of one trade: only the months that saw it are chosen again; another family is its own
    moved = [dict(r, path_sigma=[x + (0.01 if r["sid"] == "w59" else 0.0) for x in r["path_sigma"]]) for r in recs]
    qlv.calibrate(moved, "pca", TODAY)
    again = qlv.STATS["chosen"] - c0["chosen"] - chosen
    end = next(r["end_day"] for r in recs if r["sid"] == "w59")
    assert 0 < again <= sum(1 for M in qlv.months_back(qlv.month_of(TODAY), qlv.WINDOW_MONTHS) if M > end)
    qlv.calibrate(recs, "rv", TODAY)
    assert qlv.STATS["chosen"] - c0["chosen"] > chosen + again


# ================================================================================================ no look-ahead
def test_a_month_s_levels_are_chosen_on_the_trades_that_had_ended_before_it():
    rnd = random.Random(3)
    recs = []
    for i, e in enumerate(days_from("2025-09-01", 260)):
        x, path = 0.0, []
        for _ in range(5):
            x += 0.12 + rnd.gauss(0.0, 0.5)
            path.append(x)
        recs.append(trade(path, e, sid="t%d" % i))
    book = qlv.calibrate(recs, "pca", TODAY)
    cut = "2026-06-01"
    # every path that ends on or after the cut rewritten (its sign turned): the months up to the cut keep their levels
    later = [dict(r, path_sigma=[-x for x in r["path_sigma"]]) if r["end_day"] >= cut else r for r in recs]
    book2 = qlv.calibrate(later, "pca", TODAY)
    months = book.groups["TRY OIS"]["months"]
    months2 = book2.groups["TRY OIS"]["months"]
    early = [M for M in months if M <= cut]
    assert early and all(months[M] == months2.get(M) for M in early)
    assert any(months[M] != months2.get(M) for M in months if M > cut)           # (the rewrite does reach the later ones)
    # the out-of-sample record: each month's trades at that month's levels - a trade entered in a month is never
    # played at levels chosen on it
    for M, ch in months.items():
        used = [r for r in recs if r["end_day"] < M]
        assert ch["n"] == len(used)


def _bt_inputs(n=420, seed=61, k=8):
    """``k`` mean-reverting series (bp, AR(1) 0,8: a half-life of ~3 days), each a "pca" monitor of the TRY OIS group."""
    rnd = random.Random(seed)
    days = quant_synth.business_days(dt.date(2026, 11, 3), n)
    series, meta = {}, {}
    for j in range(k):
        x, ou = 0.0, []
        for _ in range(n):
            x = 0.8 * x + rnd.gauss(0, 0.05)
            ou.append(x * 100.0)
        series["OU%d" % j] = dict(zip(days, ou))
        meta["OU%d" % j] = {"label": "OU%d" % j, "kind": "bp"}

    def make_ctx(T, series=series):
        return qf.Ctx(cfg(), dt.date.fromisoformat(T) + dt.timedelta(days=1), series, {k: dict(v) for k, v in meta.items()})

    def runner(ctx):
        out = []
        for key in sorted(meta):
            pts = ctx.pts(key)
            m = qf.mr_monitor(ctx, "pca:" + key, "pca", "TRY OIS", key, "bp", 1, [d for d, _ in pts], [v for _, v in pts], "bp",
                              [{"key": "OIS:2Y", "name": key, "weight": 1.0}], lambda live, ctx=ctx, key=key: ctx.cur(key, live), pkg="rate")
            if m is not None:
                out.append(m)
        return out

    return days, series, make_ctx, runner


def test_the_backtest_records_every_trade_s_path_and_its_levels_see_no_future():
    days, series, make_ctx, runner = _bt_inputs()
    res = qbt.backtest(days[-250:], make_ctx, runner, series, cfg(), step=10)
    paths = [p for p in res["paths"] if p["family"] == "pca"]
    done = [p for p in paths if not p["open"]]
    # a path a trade: its whole holding (whatever its own target or stop did), in σ of the holding as known at the entry
    assert len(paths) == res["n_trades"] + res["open"] and len(done) >= 45
    by_entry = {(t["sid"], t["entry_day"]): t for t in res["trades"]}
    seen = 0
    for p in done:
        t = by_entry.get((p["sid"], p["entry_day"]))
        if t is None:
            continue                                                     # (the page keeps the last trades only)
        seen += 1
        assert p["entry_day"] == t["entry_day"] and p["end_day"] >= t["exit_day"] and p["group"] == "TRY OIS" and p["sigma"] > 0
        if t["outcome"] == "süre":
            assert len(p["path_sigma"]) == t["held"] and p["end_day"] == t["exit_day"]
            assert p["path_sigma"][-1] * p["sigma"] == pytest.approx(t["pnl"], rel=1e-4)        # (a path kept to 5 decimals of σ)
        else:                                                            # (its target or stop came first: the path goes on)
            assert len(p["path_sigma"]) >= t["held"]
        assert p["fair_sigma"] is not None and p["fair_sigma"] > 0          # (a mean reversion: its distance to the mean)
    assert seen >= 30
    lv = res["levels"]["families"]["pca"]
    assert lv["groups"]["TRY OIS"]["months"] and lv["month"] == qlv.month_of(qlv_today(days))
    # the future rewritten after a cut: the paths ended by then and the levels of the months up to it are the same
    cut = days[-40]
    later = {k: {d: (v + 50.0 if d > cut else v) for d, v in pts.items()} for k, pts in series.items()}
    _, _, make2, run2 = _bt_inputs()
    res2 = qbt.backtest(days[-250:], lambda T: make2(T, later), run2, later, cfg(), step=10)
    before = lambda r: sorted((p["sid"], p["entry_day"], p["end_day"], tuple(p["path_sigma"])) for p in r["paths"] if not p["open"] and p["end_day"] <= cut)
    assert before(res) and before(res) == before(res2)
    m1 = res["levels"]["families"]["pca"]["groups"]["TRY OIS"]["months"]
    m2 = res2["levels"]["families"]["pca"]["groups"]["TRY OIS"]["months"]
    early = [M for M in m1 if M <= cut]
    assert early and all(m1[M] == m2.get(M) for M in early)
    assert res["paths"] != res2["paths"]                                  # (the rewrite did reach the paths after the cut)


def qlv_today(days):
    return (dt.date.fromisoformat(days[-1]) + dt.timedelta(days=1)).isoformat()


def test_a_family_s_own_walk_forward_trades_in_quantbt_s_format_are_calibrated_with_no_code_of_its_own():
    """A family that walks forward on its own (``own_backtest``: Opsiyon → spot's kind) gives its trades in its table's
    ``backtest`` in quantbt's format with ``path_sigma`` (its whole horizon, whatever its exit), ``sigma``, quantbt's
    ``carry`` (the P&L the carry made over the closes held), ``horizon`` - no group, no path end: the group comes from
    the line's key, the path's last close is taken no earlier than the truth; ``calibrate_tables`` puts its levels in
    its table."""
    rnd = random.Random(23)
    trades = []
    for i, e in enumerate(days_from("2025-05-05", 160)):
        pair = ("EURUSD", "USDTRY")[i % 2]
        path = []
        x = 0.0
        for _ in range(5):
            x += 0.15 + rnd.gauss(0.0, 0.5)
            path.append(round(x, 5))
        out = next(((k, "hedef") for k, v in enumerate(path, 1) if v >= 1.25), None) or next(((k, "stop") for k, v in enumerate(path, 1) if v <= -1.0), (5, "süre"))
        held, how = out
        sig = 0.8
        trades.append({"sid": "optspot:FX:" + pair, "family": "optspot", "type": pair + " spot", "entry_day": e, "exit_day": days_from(e, held + 1)[-1],
                       "dir": 1, "entry": 1.1, "exit": 1.1, "outcome": how, "held": held, "pnl": path[held - 1] * sig + 0.01 * held, "unit": "%",
                       "pnl_sigma": path[held - 1], "pnl_try": (path[held - 1] * sig + 0.01 * held) * 4.2e5, "sigma": sig, "target_sigma": 1.25,
                       "stop_sigma": 1.0, "horizon": 5, "path_sigma": path, "mae_sigma": max(0.0, -min(path)), "mfe_sigma": max(0.0, max(path)),
                       "carry": 0.01 * held})
    tables = {"optspot": {"backtest": {"trades": trades}}, "sira": {"backtest": {"trades": [dict(trades[0])]}}, "pca": {"rows": []}}
    assert qlv.calibrate_tables(tables, TODAY) == ["optspot"] and "levels" not in tables["sira"]       # (sira: its own, in OWN)
    book = qlv.Book.from_json(tables["optspot"]["levels"])
    assert set(book.groups) == {"G10 spot", "Offshore"} and book.line("G10 spot")["ok"] and book.line("Offshore")["ok"]
    t = qlv.Trade(trades[0])
    assert t.group == "G10 spot" and qlv.Trade(trades[1]).group == "Offshore"
    assert t.c == pytest.approx(0.01 / 0.8) and t.try_ == pytest.approx(4.2e5) and t.carry_in and t.mae == trades[0]["mae_sigma"]
    # its path's last close: never earlier than five closes after the entry (weekends, a holiday or two)
    assert t.end >= days_from(trades[0]["entry_day"], 6)[-1] and t.end >= trades[0]["exit_day"]
    # a month's levels see no path that was still running when it began
    for M, ch in book.groups["G10 spot"]["months"].items():
        assert ch["n"] == sum(1 for r in trades if r["sid"].endswith("EURUSD") and qlv.Trade(r).end < M) or ch["scope"] == "aile"


# ================================================================================================ a trailing stop
TRAIL = {"ok": True, "rule": "trail", "k": 1.0, "m": None, "rr": 1.5, "avg_win": 1.5, "hit": 0.4, "exp": 0.3, "n": 40, "oos": True,
         "scope": "grup", "held": 10.0, "carry_in": False, "family": "trend", "group": "TRY OIS", "sigma": 1.0}


def _trail_mon(ctx, key="X"):
    """A Trend-like daily line on ``key``: always long, its levels a trailing stop 1 × σ (σ 1 level unit)."""
    pts = ctx.pts(key)
    return qf.Monitor("trend:" + key, "trend", "TRY OIS", key, "bp", 1, [d for d, _ in pts], [v for _, v in pts],
                      [{"key": "OIS:2Y", "name": key, "weight": 1.0}], lambda live: ctx.cur(key, live), zfn=lambda lv, live: 1.0,
                      mode="drift", follows=True, entry=1e-9, pnl=("bp", 1.0), regime={"tag": None}, levels=dict(TRAIL),
                      finish=lambda sg: sg.update(daily=True, new=True))


class _Svc(object):
    """Just what the log needs of the service."""

    def __init__(self):
        from tto.store import Store
        self.store = Store(":memory:")
        self.mode = "replay"

    def require_user(self, user):
        return user

    def nudge(self):
        pass

    def bump(self):
        pass


def test_a_trailing_stop_follows_the_best_level_in_the_backtest_and_in_the_log():
    days = quant_synth.business_days(dt.date(2026, 11, 3), 40)
    vals = [100.0] * 5 + [100.0 + j for j in range(11)] + [109.5, 109.2, 108.8] + [108.0] * 21     # (110 on the 16th close)
    series = {"X": dict(zip(days, vals))}
    meta = {"X": {"label": "X", "kind": "bp"}}

    def make_ctx(T):
        return qf.Ctx(cfg(), dt.date.fromisoformat(T) + dt.timedelta(days=1), series, {k: dict(v) for k, v in meta.items()})

    res = qbt.backtest(days[5:], make_ctx, lambda ctx: [_trail_mon(ctx)], series, cfg(), step=100)
    tr = [t for t in res["trades"] if t["sid"] == "trend:X"]
    # opened at 100, its stop 99 then 1 behind the best close: 110 → 109; out at the first close through it (108,8)
    assert len(tr) == 1 and tr[0]["entry"] == 100.0 and tr[0]["outcome"] == "stop" and tr[0]["exit"] == 108.8
    assert tr[0]["exit_day"] == days[18] and tr[0]["pnl"] == pytest.approx(8.8) and res["open"] == 0
    assert not res["paths"]                                              # (Trend calibrates on its own walk: no path recorded)
    # the live log: the same trailing stop behind the best level since the entry
    q = __import__("tto.quant", fromlist=["Quant"]).Quant(_Svc())
    c = cfg()
    ctx = make_ctx(days[-1])
    m = _trail_mon(ctx)

    def look(day, signals):
        q._track({"cfg": c, "today": day, "mons": {m.sid: m}}, signals)

    m.score({}, {})
    look("2026-11-02", [])                                               # (the first look: nothing is new yet)
    m.level = 100.0
    sg = qf.make_signal(m, c, "10:00")
    assert sg["trail"] == pytest.approx(1.0) and sg["stop"] == pytest.approx(99.0) and sg["target"] is None
    look("2026-11-03", [sg])
    m.level = 103.0
    look("2026-11-04", [])
    e = q._log()[0]
    assert e["status"] == "open" and e["best"] == 103.0 and e["stop"] == pytest.approx(102.0)
    m.level = 101.9
    look("2026-11-05", [])
    e = q._log()[0]
    assert e["status"] == "stop" and e["pnl"] == pytest.approx(1.9) and e["closed_level"] == 101.9


# ================================================================================================ the line
def _mon(z=2.6, family="pca", mode="mr", levels=None, carry=None):
    days = quant_synth.business_days(dt.date(2026, 11, 3), 200)
    values = [math.sin(i / 7.0) for i in range(200)]
    m = qf.Monitor("x:" + family, family, "TRY OIS", "2Y OIS", "bp", 1, days, values, [{"key": "OIS:2Y", "name": "2Y OIS", "weight": 1.0}],
                   lambda live: 0.0, mean=0.0, sd=1.0, half_life=5.0, regime={"tag": "MR"}, pkg="rate", mode=mode, dsd=0.2,
                   pnl=("bp", 1.0), carry_up=carry, levels=levels)
    m.zfn = lambda level, live, z=z: z
    m.score({}, {})
    m.level = z
    return m


def _lv(rule="fixed", k=1.0, m=1.5, exp=0.25, hit=0.6, n=48, oos=True, **kw):
    return dict({"ok": True, "rule": rule, "k": k, "m": m, "rr": (m / k if m else None), "hit": hit, "exp": exp, "n": n, "oos": oos,
                 "scope": "grup", "held": 4.0, "carry_in": False, "family": "pca", "group": "TRY OIS", "month": "2026-11-01"}, **kw)


def test_a_line_s_target_and_stop_are_the_multiples_of_its_holding_s_sigma_now():
    c = cfg()
    m = _mon(levels=_lv())
    sg = qf.make_signal(m, c, "10:00")
    hold = qf.hold_of(m)
    h = max(1, min(int(round(hold)), int(c["log_days"])))
    sig = 0.2 * math.sqrt(h)                                              # (dsd 0,2 bp a day × √ the holding: bp, a bp a P&L bp)
    s = sg["direction"]
    assert s == -1 and sg["entry"] == pytest.approx(2.6)
    assert sg["target"] == pytest.approx(2.6 + s * 1.5 * sig) and sg["stop"] == pytest.approx(2.6 - s * 1.0 * sig)
    assert sg["rr"] == pytest.approx(1.5) and sg["reward"] == pytest.approx(1.5 * sig) and sg["risk"] == pytest.approx(sig)
    # the expected P&L: the record's expectancy × σ (a rates line: the carry engine's carry over the record's holding too)
    assert sg["exp_pnl"] == pytest.approx(0.25 * sig) and not sg["gated"]
    lv = sg["levels"]
    assert lv["ok"] and lv["hit"] == 0.6 and lv["n"] == 48 and lv["money"] == pytest.approx(sg["money"]["total"])
    assert "stop 1,00σ · hedef 1,50σ · ödül / risk 1,50 · isabet %60 (48 işlem, örneklem dışı) · işlem başına +0,25σ" == lv["text"]
    assert "Seviyeler geçmiş işlemlerden" in sg["plain"] and any(g["name"] == "Seviyeler" and g["ok"] for g in sg["gates"])
    carry = qf.make_signal(_mon(levels=_lv(), carry=-2.0), c, "10:00")       # (receive: +2 bp a week of carry + roll)
    assert carry["exp_pnl"] == pytest.approx(0.25 * sig + 2.0 * 4.0 / 5.0) and carry["carry_h"] == pytest.approx(2.0 * 4.0 / 5.0)
    # a fair-value target: the mean; the stop at most as far as it - Ödül / risk ≥ 1
    f = qf.make_signal(_mon(levels=_lv(rule="fair", k=3.0, m=None)), c, "10:00")
    assert f["target"] == pytest.approx(0.0) and f["stop"] == pytest.approx(2.6 + min(3.0 * sig, 2.6)) and f["rr"] == pytest.approx(2.6 / min(3.0 * sig, 2.6))
    assert f["rr"] >= 1.0
    # a trailing stop: no target
    t = qf.make_signal(_mon(levels=_lv(rule="trail", k=2.0, m=None, rr=1.8)), c, "10:00")
    assert t["target"] is None and t["stop"] == pytest.approx(2.6 + 2.0 * sig) and t["rr"] == pytest.approx(1.8) and t["trail"] == pytest.approx(2.0 * sig)


def test_a_line_whose_levels_lost_money_stays_in_the_list_as_dusuk_guven_with_its_reason():
    c = cfg()
    good = qf.make_signal(_mon(z=2.6, levels=_lv(exp=0.2)), c, "10:00")
    bad = qf.make_signal(_mon(z=-3.0, family="rv", levels=_lv(exp=-0.15, family="rv")), c, "10:00")
    assert not good["gated"] and bad["gated"] == qlv.LOSS == "bu kurulum bu seviyelerle geçmişte zarar ettirdi"
    assert bad["strength"] == "elendi" and bad["composite"] == 0.0 and "zarar ettirdi" in bad["plain"]
    assert any(g["name"] == "Seviyeler" and not g["ok"] for g in bad["gates"])
    live, gated = qf.rank([good, bad])
    listed = qu.order(live, gated)
    assert [s["id"] for s in listed] == [good["id"], bad["id"]] and listed[1]["gated"] == qlv.LOSS
    # a family with no gate of its own (Carry + momentum's legs): its levels' record holds it all the same
    un = _mon(z=2.6, family="sira", levels=_lv(rule="given", exp=-0.3, family="sira"))
    un.ungated = True
    assert qf.make_signal(un, c, "10:00")["gated"] == qlv.LOSS


def test_each_group_is_sorted_by_its_lines_expectancy():
    c = cfg()
    sigs = []
    for i, (e, z) in enumerate(((0.1, 2.2), (0.4, 2.1), (0.25, 3.2), (None, 2.9))):
        m = _mon(z=z, levels=_lv(exp=e) if e is not None else {"ok": False, "why": "geri testte 4 işlem (en az 30)"})
        m.sid = "x%d" % i
        sigs.append(qf.make_signal(m, c, "10:00"))
    live, gated = qf.rank(sigs)
    ids = [s["id"] for s in qu.order(live, gated)]
    # by the expectancy in TRY (the higher first) whatever the strength (x2 is the strongest); a line without levels: its
    # own expected P&L (here the window mean's reversion, larger than the others' records)
    exp = {s["id"]: s["exp_try"] for s in sigs}
    assert ids == sorted(ids, key=lambda i: -exp[i]) == ["x3", "x1", "x2", "x0"]
    none = next(s for s in sigs if s["id"] == "x3")
    assert not none["levels"]["ok"] and "en az 30" in none["levels"]["text"] and "Seviyeler: geri testte 4 işlem" in none["plain"]


def test_the_families_that_keep_their_own_levels_say_so():
    for fam in ("viop", "imacal", "izscore", "corr"):
        m = _mon(family=fam)
        lv = qlv.line_for(m, {})
        assert not lv["ok"] and lv["own"] and lv["why"] == qlv.KEEP[fam]
        m.levels = lv
        sg = qf.make_signal(m, cfg(), "10:00")
        assert sg["target"] == pytest.approx(0.0) and sg["stop"] == pytest.approx(3.5)      # (its own: the window's mean, |z| 3,5)
        assert sg["levels"]["why"] == qlv.KEEP[fam] and not sg["gated"]
    # before the first backtest, and a family the backtest had no trade of
    m = _mon(family="pca")
    assert "henüz yok" in qlv.line_for(m, None)["why"] and "işlemi yok" in qlv.line_for(m, {})["why"]
    # the stored backtest's books, as a JSON round trip
    book = qlv.calibrate(planted(), "pca", TODAY)
    doc = {"families": {"pca": book.to_json()}}
    lv = qlv.line_for(m, qlv.books_of(doc))
    assert lv["ok"] and lv == book.line("TRY OIS")
