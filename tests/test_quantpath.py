"""The implied path as a mixture of discrete decisions (tto/quantpath.py): a step on its grid, the paths two meetings
allow and their probability ranges (the desk's −40 / −60 among them, checked against a brute-force search), the P&L
of the meeting-dated OIS periods, kinks and zig-zags, the decisions read from TLREF, the calibration on a planted
bias, the WIRP's convolution and its check, the policy rate's mapping, the USD snapshots - then the service on a
synthetic year of meeting pricing (signals of both families), the real solver's output of the recorded month, the
HTTP API and the pages' registration."""
from __future__ import annotations

import datetime as dt
import itertools
import math
import random

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth, make_service
from tto import quantfam as qf
from tto import quantpath as qp
from tto.quant import DEFAULTS, PAGES
from tto.server import create_app

TODAY = dt.date(2026, 11, 3)                         # the day the workbook was saved (the replay service's today)
FUTURE = ("2026-12-10", "2027-01-21", "2027-03-18", "2027-04-22", "2027-06-10", "2027-07-22")


def path_of(base, steps, meetings=None):
    """A path from a base (%) and steps (bp) per meeting."""
    meetings = meetings or ["2027-%02d-01" % (i + 1) for i in range(len(steps))]
    out, level = [], base
    for m, s in zip(meetings, steps):
        level += s / 100.0
        out.append((m, level))
    return {"day": "2026-11-03", "spot": "2026-11-04", "base": base, "meetings": out}


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ================================================================================================ one meeting
def test_a_step_is_a_mix_of_its_two_grid_outcomes():
    b = qp.bracket(-40.0, 50.0)
    assert (b["lo"], b["hi"]) == (-50.0, 0.0) and close(b["p_lo"], 0.8) and close(b["p_hi"], 0.2)
    assert b["big"] == -50.0 and b["small"] == 0.0 and close(b["p_big"], 0.8)
    on = qp.bracket(-50.0 + 1e-9, 50.0)                                   # on the grid: that outcome for certain
    assert on["lo"] == -50.0 and on["p_lo"] == 1.0 and on["p_hi"] == 0.0
    assert qp.bracket(0.0, 50.0)["p_big"] == 0.0 and qp.bracket(0.0, 50.0)["p_lo"] == 1.0
    up = qp.bracket(10.0, 25.0)                                           # the Fed's grid: a hike priced at 40 %
    assert (up["lo"], up["hi"], up["big"]) == (0.0, 25.0, 25.0) and close(up["p_big"], 0.4)
    deep = qp.bracket(-275.0, 50.0)                                       # between two cuts: −300 / −250 half each
    assert (deep["lo"], deep["hi"], deep["big"]) == (-300.0, -250.0, -300.0) and close(deep["p_lo"], 0.5)
    rows = qp.decompose(path_of(40.0, [-40.0, -60.0, -10.0]), 50.0)
    assert [round(r["step"], 6) for r in rows] == [-40.0, -60.0, -10.0] and [round(r["cum"], 6) for r in rows] == [-40.0, -100.0, -110.0]
    assert [round(r["moves"], 6) for r in rows] == [-0.8, -2.0, -2.2]
    assert (rows[1]["lo"], rows[1]["hi"]) == (-100.0, -50.0) and close(rows[1]["p_lo"], 0.2)
    for r in rows:                                                        # the mix gives the step back
        assert close(r["p_lo"] * r["lo"] + r["p_hi"] * r["hi"], r["step"], 1e-6)


# ================================================================================================ consecutive meetings
def test_the_desk_s_example_minus_40_then_minus_60():
    rows = qp.decompose(path_of(40.0, [-40.0, -60.0, -50.0]), 50.0)
    t = qp.pair_table(rows, 0, 50.0)
    assert t["support"] == "monoton" and close(t["total"], -100.0, 1e-9) and not t["against_previous"]
    got = {(p["a1"], p["a2"]): p for p in t["paths"]}
    assert set(got) == {(-50.0, -50.0), (0.0, -100.0), (-100.0, 0.0)}
    ranges = {k: (round(p["p_min"], 9), round(p["p_max"], 9)) for k, p in got.items()}
    assert ranges == {(-50.0, -50.0): (0.0, 0.8), (0.0, -100.0): (0.2, 0.6), (-100.0, 0.0): (0.0, 0.4)}
    # the meeting-dated OIS of the period between the meetings priced at TLREF − 40: +10 / −40 / +60 received; the
    # period after the second meeting is TLREF − 100 in all three
    assert {k: round(p["pnl1"], 9) for k, p in got.items()} == {(-50.0, -50.0): 10.0, (0.0, -100.0): -40.0, (-100.0, 0.0): 60.0}
    assert all(abs(p["pnl2"]) < 1e-9 for p in got.values())
    assert got[(-50.0, -50.0)]["reading"] == "eşit adım (−50/−50) görüşü: 1. dönem 10 bp ucuz → receive"
    assert got[(0.0, -100.0)]["reading"] == "ertelenmiş (0/−100) görüşü: 1. dönem 40 bp pahalı → pay"
    assert got[(-100.0, 0.0)]["reading"] == "önden yüklü (−100/0) görüşü: 1. dönem 60 bp ucuz → receive"
    assert [p["name"] for p in t["paths"]] == ["eşit adım", "ertelenmiş", "önden yüklü"]
    # the second pair is read against the period before it
    second = qp.pair_table(rows, 1, 50.0)
    assert second["against_previous"] and second["first"] == rows[1]["meeting"]


def _brute_ranges(paths, targets, step=0.01):
    """Least / greatest probability of each path by a search over the polytope's free coordinates (independent of
    the vertex enumeration): every mix on a grid of the first paths, the rest solved."""
    m = len(paths)
    rows = [[1.0] * m] + [[p[i] for p in paths] for i in range(len(targets))]
    rhs = [1.0] + list(targets)
    best = [[math.inf, -math.inf] for _ in range(m)]
    for basis in itertools.combinations(range(m), len(rows)):
        a = [[rows[i][j] for j in basis] for i in range(len(rows))]
        if qp.qm.solve(a, [1.0] * len(rows)) is None:
            continue                                                      # singular: the next basis
        free = [j for j in range(m) if j not in basis]
        n = int(round(1 / step))
        for combo in itertools.product(range(n + 1), repeat=len(free)):
            if sum(combo) > n:
                continue
            fixed = {j: c * step for j, c in zip(free, combo)}
            b = [rhs[i] - sum(rows[i][j] * v for j, v in fixed.items()) for i in range(len(rows))]
            x = qp.qm.solve(a, b)
            if x is None or min(x) < -1e-9:
                continue
            full = dict(fixed)
            full.update(zip(basis, x))
            for j in range(m):
                best[j][0] = min(best[j][0], full[j])
                best[j][1] = max(best[j][1], full[j])
        return best                                                       # one nonsingular basis parametrises the polytope
    return best


def test_feasible_ranges_agree_with_a_brute_force_search():
    # the total −85 is not on the grid: totals −50 (30 %) and −100 (70 %), five monotone paths
    paths, ranges, kind = qp.pair_support(-40.0, -45.0, 50.0)
    assert kind == "monoton" and set(paths) == {(0.0, -100.0), (-50.0, -50.0), (-100.0, 0.0), (0.0, -50.0), (-50.0, 0.0)}
    brute = _brute_ranges(paths, (-40.0, -45.0), step=0.005)
    for (lo, hi), (blo, bhi) in zip(ranges, brute):
        assert abs(lo - blo) < 0.011 and abs(hi - bhi) < 0.011, (paths, ranges, brute)
    by = dict(zip(paths, ranges))
    assert close(by[(-50.0, -50.0)][1], 0.7, 1e-9) and close(by[(-100.0, 0.0)][1], 0.4, 1e-9) and close(by[(-50.0, 0.0)][1], 0.3, 1e-9)
    # every vertex of the polytope gives both steps back (and the totals' 30 / 70)
    for p_min, p_max in ranges:
        assert 0.0 <= p_min <= p_max <= 1.0
    # an implied path the monotone paths cannot give (a cut, then a hike priced): each meeting's own two outcomes
    paths, ranges, kind = qp.pair_support(-40.0, 10.0, 50.0)
    assert kind == "en yakın" and set(paths) == {(-50.0, 0.0), (-50.0, 50.0), (0.0, 0.0), (0.0, 50.0)}
    by = dict(zip(paths, ranges))
    assert close(by[(-50.0, 0.0)][0], 0.6, 1e-9) and close(by[(-50.0, 0.0)][1], 0.8, 1e-9) and close(by[(0.0, 50.0)][1], 0.2, 1e-9)
    # equal steps on the grid are a 50 / 50 mix of the early and the late move just as well
    paths, ranges, _ = qp.pair_support(-50.0, -50.0, 50.0)
    assert dict(zip(paths, [round(h, 9) for _, h in ranges])) == {(0.0, -100.0): 0.5, (-50.0, -50.0): 1.0, (-100.0, 0.0): 0.5}
    assert qp.lp_ranges([(0.0, 0.0)], (-10.0, 0.0)) is None              # no mix: none


# ================================================================================================ kinks
def test_kinks_measure_a_period_against_its_neighbours_and_find_zigzags():
    rows = qp.decompose(path_of(40.0, [-40.0, -60.0, -40.0, -60.0, -40.0]), 50.0)
    ks = qp.kinks(rows, 50.0)
    assert [round(k["d"], 9) for k in ks] == [10.0, -10.0, 10.0, -10.0]                 # d = −(Δ_k+1 − Δ_k) / 2
    assert [round(k["second"], 9) for k in ks] == [-20.0, 20.0, -20.0, 20.0]
    assert [k["zigzag"] for k in ks] == [False, True, True, True]
    smooth = qp.kinks(qp.decompose(path_of(40.0, [-50.0] * 5), 50.0), 50.0)
    assert all(abs(k["d"]) < 1e-9 and not k["zigzag"] for k in smooth)
    small = qp.kinks(qp.decompose(path_of(40.0, [-50.0, -52.0, -50.0, -52.0]), 50.0), 50.0)
    assert not any(k["zigzag"] for k in small)                            # below a fifth of the grid: no zig-zag
    # day by day, the kink of a meeting stays with its meeting (its neighbours are the same meetings)
    paths = {}
    for i, day in enumerate(("2026-10-01", "2026-10-02", "2026-10-05")):
        paths[day] = path_of(40.0, [-40.0, -45.0 + i, -55.0 - i], meetings=list(FUTURE[:3]))
    series = qp.kink_series(paths, 50.0, "2026-10-05")
    assert [round(v, 9) for _, v in series[FUTURE[1]]] == [5.0, 6.0] and FUTURE[2] not in series


# ================================================================================================ decisions, calibration
def test_decisions_are_read_from_the_fixings_on_the_grid():
    fix = {"2026-10-21": 36.85, "2026-10-22": 36.877, "2026-10-23": 35.85, "2026-12-10": 35.80, "2026-12-11": 35.10,
           "2027-01-21": 35.10, "2027-01-22": 35.10}
    dec = qp.decisions_from(fix, ["2026-10-22", "2026-12-10", "2027-01-21", "2027-03-18"], 50.0)
    assert dec["2026-10-22"]["decided"] == -100.0 and dec["2026-10-22"]["clean"] and close(dec["2026-10-22"]["change"], -102.7, 1e-6)
    assert dec["2026-12-10"]["decided"] == -50.0 and not dec["2026-12-10"]["clean"]            # −70: off the grid, not a decision
    assert dec["2027-01-21"]["decided"] == 0.0 and dec["2027-01-21"]["clean"]
    assert "2027-03-18" not in dec                                                             # not held yet: no fixing after it
    upper = {"2026-12-09": 4.00, "2026-12-10": 3.75}
    assert "2026-12-10" not in qp.decisions_from(upper, ["2026-12-10"], 25.0, strict=True)    # (no fixing after the meeting)
    same_day = {"2026-12-08": 4.00, "2026-12-09": 3.75, "2026-12-10": 3.75}                  # the snapshot of the day carries it
    assert qp.decisions_from(same_day, ["2026-12-09"], 25.0, strict=True)["2026-12-09"]["decided"] == -25.0
    assert qp.decisions_from(same_day, ["2026-12-09"], 25.0)["2026-12-09"]["decided"] == 0.0


def synthetic_year(days, held, cut_at, front_step=-10.0, today_kink=None, seed=3):
    """A year of meeting pricing: ``held`` meetings (each the next one for the 25 days before it, priced at
    ``front_step``), the decisions ``cut_at`` (−50, else 0) in a TLREF series, then the six meetings ahead whose
    period levels each carry a mean-reverting noise of their own (AR(1), b 0.7); on the last day only the second of
    them is off its neighbours, by ``today_kink`` bp.  Returns (paths, fixings)."""
    rnd = random.Random(seed)
    tl, level = {}, 45.0
    decided = {m: (-50.0 if i in cut_at else 0.0) for i, m in enumerate(held)}
    smooth = [-40.0, -50.0, -50.0, -50.0, -50.0, -50.0]
    paths = {}
    u = [0.0] * len(FUTURE)
    for i, d in enumerate(days):
        tl[d] = level + rnd.gauss(0, 0.02)
        if d in decided:
            level += decided[d] / 100.0
            continue                                                      # a decision day: no pricing of its own here
        ahead = [m for m in held if m > d]
        u = [0.7 * x + rnd.gauss(0, 2.0) for x in u]
        if i == len(days) - 1 and today_kink is not None:
            u = [0.0, today_kink, 0.0, 0.0, 0.0, 0.0]
        steps = [front_step] * len(ahead) + [s + u[j] - (u[j - 1] if j else 0.0) for j, s in enumerate(smooth)]
        paths[d] = path_of(tl[d], steps, meetings=ahead + list(FUTURE))
        paths[d]["day"] = d
        paths[d]["spot"] = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
    return paths, tl


def test_calibration_finds_a_bias_and_says_when_the_sample_is_small():
    days = quant_synth.business_days(TODAY, 260)
    held = [days[i] for i in range(25, 260, 25)]                          # ten meetings held
    # the bigger move (−50) priced at 20 % every day, decided at six of the ten meetings: under-priced
    paths, tl = synthetic_year(days, held, cut_at={0, 1, 3, 4, 6, 8})
    dec = qp.decisions_from(tl, held, 50.0)
    assert [dec[m]["decided"] for m in held] == [-50.0, -50.0, 0.0, -50.0, -50.0, 0.0, -50.0, 0.0, -50.0, 0.0]
    cal = qp.calibration(paths, dec, 50.0)
    assert cal["n"] == 10 and cal["days"] == 10 * qp.CAL_WINDOW and cal["outside"] == 0
    low = cal["buckets"][1]                                               # 20 % sits in the 20–40 % bucket
    assert (low["meetings"], low["days"]) == (10, 200) and close(low["priced"], 0.2, 1e-9) and close(low["freq"], 0.6, 1e-9)
    assert low["ci_lo"] < 0.6 < low["ci_hi"] and low["ci_hi"] - low["ci_lo"] > 0.3          # ten meetings: a wide interval
    assert close(cal["bias"], 0.4, 1e-9) and close(cal["z"], 4.0 / math.sqrt(10 * 0.16), 1e-9)
    assert all(b["meetings"] == 0 for k, b in enumerate(cal["buckets"]) if k != 1)
    first = cal["meetings"][0]
    assert first["meeting"] == held[0] and first["hit"] == 1 and first["big"] == -50.0 and close(first["p_last"], 0.2, 1e-9)
    # priced right (two of ten decided −50 at 20 %): no bias
    fair, tl2 = synthetic_year(days, held, cut_at={2, 7})
    cal2 = qp.calibration(fair, qp.decisions_from(tl2, held, 50.0), 50.0)
    assert abs(cal2["z"]) < 1e-9 and abs(cal2["bias"]) < 1e-9
    # a few meetings only: the numbers are there, no signal (cal_monitor needs CAL_MIN_MEETINGS)
    few = {d: p for d, p in paths.items() if d < held[2]}                # the days of the first three meetings
    cal3 = qp.calibration(few, dec, 50.0)
    assert cal3["n"] == 3 and cal3["z"] is not None
    st = qp.State()
    now = {"ok": True, "calibration": cal3, "rows": qp.decompose(path_of(40.0, [-40.0, -50.0]), 50.0), "grid": 50.0, "day": TODAY.isoformat()}
    ctx = qf.Ctx(dict(DEFAULTS), TODAY, {}, {})
    assert qp.cal_monitor(ctx, "try", now, st) is None
    now["calibration"] = cal
    mon = qp.cal_monitor(ctx, "try", now, st)
    st.now["try"] = now
    mon.score({}, {})
    s = qf.make_signal(mon, dict(DEFAULTS), "10:00")
    assert s["family"] == "imacal" and s["direction"] == -1 and s["expression"].startswith("Receive PPK")      # lean to the cut
    assert close(s["target"] - s["entry"], -0.4 * 50.0, 1e-9) and close(s["entry"] - s["stop"], -0.8 * 50.0, 1e-9)
    assert "Taşıma 0" in s["note"] and s["carry_week"] == 0.0 and s["info"]["scenarios"][0]["outcome"] == -50.0


# ================================================================================================ the WIRP
def test_wirp_splits_each_step_and_convolves_the_meetings():
    rows = qp.decompose(path_of(40.0, [-40.0, -60.0]), 50.0)
    w = qp.wirp(rows, 50.0)
    one, two = ({k: round(p, 9) for k, p in x["dist"].items()} for x in w)
    assert one == {-1: 0.8, 0: 0.2}                                       # −40: 80 % −50, 20 % no change
    assert two == {-3: 0.16, -2: 0.68, -1: 0.16}                          # convolved with −60: 80 % −50, 20 % −100
    assert close(w[0]["ease"], 0.8) and close(w[0]["hold"], 0.2) and w[0]["hike"] == 0.0
    assert close(w[1]["ease"], 1.0) and w[1]["hold"] == 0.0
    # the matrix's expected values give the implied path back, for any path
    rnd = random.Random(5)
    for _ in range(20):
        steps = [rnd.uniform(-180, 120) for _ in range(12)]
        items = qp.wirp(qp.decompose(path_of(35.0, steps), 50.0), 50.0)
        assert max(abs(it["check"]) for it in items) < 1e-6
        assert all(abs(sum(it["dist"].values()) - 1.0) < 1e-9 for it in items)
    keys = qp.wirp_buckets(w)
    assert keys == [-3, -2, -1, 0]                                        # today's bucket always among the columns


def test_policy_rate_mapping_buckets_and_the_history_in_today_s_buckets():
    st = qp.State()
    st.policy = 36.0
    p = path_of(35.8159, [-85.5, -27.2], meetings=list(FUTURE[:2]))
    pol = qp.policy_of("try", dict(DEFAULTS), st, p)
    assert pol["rate"] == 36.0 and pol["source"].startswith("Masa!Q155") and close(pol["spread"], 18.41, 1e-6)
    manual = qp.policy_of("try", dict(DEFAULTS, path_policy=37.5), st, p)
    assert manual["rate"] == 37.5 and manual["source"] == "masa ayarı (elle)"
    st.policy = None
    assert qp.policy_of("try", dict(DEFAULTS), st, p)["rate"] is None
    assert qp._bucket("try", -2, 50.0, {"rate": 36.0})["label"] == "35,00"
    assert qp._bucket("usd", 1, 25.0, {"rate": 4.0})["label"] == "400–425"
    assert qp._bucket("try", -1, 50.0, {"rate": None})["label"] == "−50 bp"
    fed = qp.policy_of("usd", dict(DEFAULTS), st, dict(path_of(3.88, [19.0]), upper=4.0))
    assert fed["rate"] == 4.0 and close(fed["spread"], (3.875 - 3.88) * 100, 1e-9)
    # a day a week ago, before a −100 decision: its distribution in today's buckets (the decision from the bases)
    back = path_of(36.8159, [-100.0, -85.0, -30.0], meetings=["2026-10-22"] + list(FUTURE[:2]))
    back["day"] = "2026-10-27"
    now = dict(p, day="2026-11-03")
    w = qp.wirp_table("try", now, {"2026-10-27": back}, 50.0, {"rate": 36.0})
    dec = next(x for x in w["history"] if x["meeting"] == FUTURE[0] and x["lookback"] == "1 hafta önce")
    assert dec["day"] == "2026-10-27" and close(dec["step"], -85.0, 1e-9) and close(dec["cum"], -85.0, 1e-9)
    assert {x["k"]: round(x["p"], 9) for x in dec["dist"]} == {-2: 0.7, -1: 0.3}
    cells = {bk["k"]: round(p, 9) for bk, p in zip(w["history_buckets"], dec["matrix"])}
    assert cells == {-3: 0.0, -2: 0.7, -1: 0.3, 0: 0.0} and [bk["label"] for bk in w["history_buckets"]] == ["34,50", "35,00", "35,50", "36,00"]
    day_before = next(x for x in w["history"] if x["meeting"] == FUTURE[0] and x["lookback"] == "1 gün önce")
    assert day_before["day"] is None                                      # four days older than the day asked: not shown as yesterday
    assert w["chart"]["days"] == ["2026-10-27", "2026-11-03"]
    assert [round(v, 6) for v in w["chart"]["series"][0]["steps"]] == [-85.0, -85.5]
    assert close(w["check"], 0.0, 1e-9)


def test_usd_snapshots_are_kept_a_day_each():
    class KV(object):
        def __init__(self):
            self.kv = {}
            self.writes = 0

        def get(self, key, default=None):
            return self.kv.get(key, default)

        def put(self, key, value):
            self.writes += 1
            self.kv[key] = value

    store, st = KV(), qp.State()
    p = dict(path_of(3.88, [19.0, 8.0]), upper=4.0, fixing=3.95)
    assert qp.keep_usd(store, p, st, now=1000.0) and store.writes == 1
    assert not qp.keep_usd(store, p, st, now=1100.0)                      # unchanged
    moved = dict(p, base=3.87)
    assert not qp.keep_usd(store, moved, st, now=1200.0)                  # changed, but written less than 10 minutes ago
    assert qp.keep_usd(store, moved, st, now=1000.0 + qp.USD_WRITE_EVERY + 1) and store.writes == 2
    assert qp.keep_usd(store, dict(moved, day="2026-11-04"), st, now=1000.0 + qp.USD_WRITE_EVERY + 2)      # a new day: at once
    back = qp.usd_paths(store)
    assert sorted(back) == ["2026-11-03", "2026-11-04"] and back["2026-11-03"]["base"] == 3.87 and back["2026-11-04"]["upper"] == 4.0
    assert back["2026-11-03"]["meetings"][0][0] == p["meetings"][0][0]
    days = {("2024-%02d-%02d" % (1 + i // 28, 1 + i % 28)): {"spot": "x", "base": 1.0, "meetings": []} for i in range(qp.USD_KEEP_DAYS + 5)}
    store.kv[qp.USD_KEY] = {"v": 1, "days": days}
    qp.keep_usd(store, dict(p, day="2026-11-05"), qp.State(), now=5000.0)
    assert len(store.kv[qp.USD_KEY]["days"]) == qp.USD_KEEP_DAYS and "2026-11-05" in store.kv[qp.USD_KEY]["days"]


# ================================================================================================ the service
@pytest.fixture(scope="module")
def pathsvc(module_service):
    """The replay service with a synthetic year of meeting pricing in its store: ten meetings held (the bigger move
    priced at 20 %, decided at six), six ahead with a planted kink at the second of them today."""
    svc = module_service
    svc.quant.use_live = False
    days = quant_synth.business_days(TODAY, 260)
    held = [days[i] for i in range(25, 260, 25)]
    days = days + [TODAY.isoformat()]
    paths, tl = synthetic_year(days, held, cut_at={0, 1, 3, 4, 6, 8}, today_kink=9.0)
    svc.store.mpc_delete()
    for d, p in paths.items():
        rows = [{"meeting": m, "level": lv / 100.0, "step": None, "cum": None, "sigma": None, "front": i == 0} for i, (m, lv) in enumerate(p["meetings"])]
        svc.store.mpc_save(d, "synth-" + d, {"spot": p["spot"], "tlref": p["base"], "base": p["base"] / 100.0, "quotes": 18, "status": "OK",
                                             "control": 0.1, "tolerance": 5.0}, rows)
    ref = next(x for x in svc.history.snapshot()["defs"] if x.group == "ref")
    for sid in ref.ids():
        svc.store.hist_delete(sid)
    svc.store.hist_upsert(ref.id, sorted((d, v) for d, v in tl.items() if d < TODAY.isoformat()))
    svc.history.rev += 1
    svc.quant.compute()
    return svc


def test_the_fit_reads_both_paths_and_finds_the_planted_signals(pathsvc):
    svc = pathsvc
    st = svc.quant.status()
    assert st["ready"] and not st["errors"] and "imapath" in st["timing"]
    user = svc.login("ima okuyucu")["user"]
    v = svc.quant.view("path", user, {})
    t = v["path"]["banks"]["try"]
    assert t["ok"] and t["day"] == TODAY.isoformat() and [r["meeting"] for r in t["rows"]] == list(FUTURE) and t["grid"] == 50.0
    assert t["calibration"]["n"] == 10 and t["calibration"]["z"] > 3.0
    kink = next(k for k in t["kinks"] if k["meeting"] == FUTURE[1])
    assert close(kink["d"], 9.0, 1e-6) and kink["n"] >= qp.KINK_MIN_OBS and 2.0 < kink["z"] < 3.5 and kink["sid"] == "imapath:TRY:" + FUTURE[1]
    assert all(abs(k["z"]) < 2.0 for k in t["kinks"] if k["meeting"] != FUTURE[1] and k["z"] is not None)    # the neighbours: half of it
    sigs = {s["id"]: s for s in v["signals"]}
    s = sigs["imapath:TRY:" + FUTURE[1]]
    assert s["page"] == "quant-path" and s["family_label"] == "İma patikası ayrıklığı" and not s["gated"] and s["direction"] == -1
    assert s["expression"].startswith("Receive PPK 21.01.27–18.03.27 dönemi")
    assert {l["key"]: l["side"] for l in s["legs"]} == {"MPC:" + FUTURE[1]: -1, "MPC:" + FUTURE[2]: 1, "MPC:" + FUTURE[0]: 1}
    assert s["legs"][0]["text"].startswith("Receive PPK") and s["legs"][1]["text"].startswith("Pay PPK")
    assert "Senaryolar" in s["note"] and "Taşıma 0" in s["note"] and s["carry_week"] == 0.0 and s["info"]["scenarios"]
    cal = sigs["imacal:TRY"]
    assert cal["family"] == "imacal" and cal["direction"] == -1 and cal["legs"][0]["key"] == "MPC:" + FUTURE[0]
    # both rank on Sinyaller with the other families
    ranked = svc.quant.view("signals", user, {"family": "imapath"})
    assert [x["id"] for x in ranked["signals"]] == ["imapath:TRY:" + FUTURE[1]]
    assert {"imapath", "imacal"} <= {f["id"] for f in ranked["families"]}
    one = svc.quant.view("signal", user, {"id": "imapath:TRY:" + FUTURE[1]})
    assert len(one["history"]["days"]) >= qp.KINK_MIN_OBS and one["monitor"]["family"] == "imapath"
    # the USD path from the workbook (replay): ten FOMC meetings, the Fed's upper bound, a snapshot of today kept
    u = v["path"]["banks"]["usd"]
    assert u["ok"] and len(u["rows"]) == 10 and u["grid"] == 25.0 and u["rows"][0]["meeting"] == "2026-12-09"
    assert u["rows"][0]["lo"] == 0.0 and u["rows"][0]["hi"] == 25.0
    assert TODAY.isoformat() in (svc.store.get(qp.USD_KEY) or {}).get("days", {})
    cov = {c["key"]: c for c in v["coverage"]}
    assert cov["mpc"]["n"] == len([d for d in svc.store.mpc_days()]) and cov["usd"]["state"] == "birikiyor" and cov["TLREF"]["n"] > 200
    # the WIRP of both banks: the matrix gives the implied path back; the policy rate from Masa (Q155) in replay
    w = svc.quant.view("wirp", user, {})["wirp"]["banks"]
    assert w["try"]["ok"] and w["try"]["check"] < 1e-9 and w["try"]["policy"]["rate"] == 36.0 and len(w["try"]["rows"]) == 6
    assert w["usd"]["ok"] and w["usd"]["check"] < 1e-9 and w["usd"]["policy"]["rate"] == 4.0
    first = w["try"]["rows"][0]
    assert close(first["p_lo"], 0.8, 1e-9) and close(first["ease"], 0.8, 1e-9) and close(first["rate"], 36.0 - 0.40, 1e-9)
    assert sum(first["matrix"]) == pytest.approx(1.0) and len(first["matrix"]) == len(w["try"]["buckets"])
    assert [h["lookback"] for h in w["try"]["history"][:5]] == [lb for _, lb in qp.LOOKBACKS]
    # the minute's refresh: the USD path read again, the tables published again
    before = svc.quant.state["refreshes"]
    svc.quant.refresh_live()
    assert svc.quant.state["refreshes"] == before + 1 and svc.quant.view("wirp", user, {})["wirp"]["banks"]["usd"]["ok"]


def test_the_engine_read_is_one_short_call_at_the_lowest_priority(pathsvc, monkeypatch):
    svc = pathsvc
    seen = []
    real = svc.et.call_at

    def spy(priority, fn, *args, **kw):
        seen.append((priority, getattr(fn, "__name__", "")))
        return real(priority, fn, *args, **kw)

    monkeypatch.setattr(svc.et, "call_at", spy)
    st = qp.State()
    qp._read(svc.quant, st)
    assert seen == [(svc.et.BACKGROUND, "read_engine")]
    assert st.policy == 36.0 and st.usd["day"] == TODAY.isoformat() and len(st.usd["meetings"]) == 10 and st.usd["upper"] == 4.0
    assert st.usd["status"] == "OK" and st.engine_ms < 2000


def test_quantpath_http_api_and_the_pages(pathsvc):
    svc = pathsvc
    app = create_app(svc)
    with TestClient(app, headers=auth(svc, "İma HTTP")) as client:
        for what in ("path", "wirp"):
            r = client.get("/api/quant/" + what)
            assert r.status_code == 200 and r.json()["ready"] and set(r.json()[what]["banks"]) == {"try", "usd"}
        assert client.get("/api/quant/path").json()["mode"] == "replay"
        assert client.post("/api/quant/settings", json={"values": {"path_grid_try": "1"}}).status_code == 400
        res = client.post("/api/quant/settings", json={"values": {"path_grid_try": "25", "path_policy": "37,5"}})
        assert res.status_code == 200 and res.json()["values"]["path_grid_try"] == 25.0 and res.json()["values"]["path_policy"] == 37.5
        client.post("/api/quant/recompute", json={})
        if svc.quant._thread is not None:                                 # (no worker in the tests: recompute ran it already)
            svc.quant.compute()
        w = client.get("/api/quant/wirp").json()["wirp"]["banks"]["try"]
        assert w["grid"] == 25.0 and w["policy"]["rate"] == 37.5 and w["policy"]["source"] == "masa ayarı (elle)"
        first = w["rows"][0]
        assert (first["lo"], first["hi"]) == (-50.0, -25.0) and close(first["p_lo"], 0.6, 1e-9)       # −40 on a 25 grid
        client.post("/api/quant/settings", json={"values": {"path_grid_try": "50", "path_policy": "0"}})
        svc.quant.compute()
        nav = client.get("/api/nav").json()["pages"]
        quant = [p["id"] for p in nav if p["group"] == "Quant"]
        assert quant.index("quant-wirp") == quant.index("quant-path") + 1 and ("quant-path", "İma Patikası") in PAGES and ("quant-wirp", "TCMB WIRP") in PAGES
        assert client.get("/static/js/pages/quantpath.js").status_code == 200
        assert client.get("/api/quant/path", headers={"Authorization": ""}).status_code == 401


# ================================================================================================ the real solver's month
def test_the_recorded_month_through_the_workbook_s_own_solver(tmp_path):
    """The history's own solver on three recorded days around the 22 October meeting: the path as the store keeps it
    (steps from the base, the decision day measured from the level after it), the decision from TLREF."""
    svc = make_service(tmp_path / "real")
    try:
        days = ["2026-10-21", "2026-10-22", "2026-10-23"]
        assert svc.history.sync(only=days)["computed"] == 3
        svc.quant.use_live = False
        svc.quant.compute()
        user = svc.login("ima gerçek")["user"]
        t = svc.quant.view("path", user, {})["path"]["banks"]["try"]
        assert t["ok"] and t["day"] == "2026-10-23" and t["rows"][0]["meeting"] == "2026-12-10"
        stored = {r["meeting"]: r for r in svc.store.mpc_values("2026-10-23", "2026-10-23")}
        for r in t["rows"]:                                               # (the sheet rounds its cumulative to 0,01 bp)
            assert abs(r["step"] - stored[r["meeting"]]["step"]) < 1e-6 and abs(r["cum"] - stored[r["meeting"]]["cum"]) < 0.006
        cal = t["calibration"]
        assert cal["n"] == 1 and cal["meetings"][0]["meeting"] == "2026-10-22" and cal["meetings"][0]["decided"] == -100.0
        assert cal["meetings"][0]["big"] == -100.0 and cal["meetings"][0]["hit"] == 1
        w = svc.quant.view("wirp", user, {})["wirp"]["banks"]["try"]
        assert w["ok"] and w["check"] < 1e-9 and w["policy"]["rate"] == 36.0
    finally:
        svc.stop()
