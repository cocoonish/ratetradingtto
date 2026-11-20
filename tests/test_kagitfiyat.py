"""Kâğıt Fiyatlama (19.11.2026; the desk: "Hangi seviyelerin iyi olduğunu ve fiyatlamayı nasıl yapacağımı net söylemiyor" -
asked what a price starts from: "Bunu sen bul. En çok neyi takip ediyor"): ``tto/kagitfiyat.py`` on its own - the weights
by bucket, the neighbours' curve left without the bond (its own quote does not move it), the fair from the spread at the
previous close, σ and its floor, the good levels' signs, the market against them, the backtest on a history with known
answers - and on the replay day over a made-up history: the spread taken at the last close before today (today's close
does not count), fair = base + spread, the bases now (the neighbours' curve on DİBS RV's yields, the OIS Bootstrap), the
closes' part kept per revision, floaters and CPI linkers refused with a reason, the widths only an administrator sets, the
page first in the Tahvil menu, one bond for the card, and the HTTP routes (last: the client stops the service)."""
from __future__ import annotations

import datetime as dt
import random
import statistics

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import kagitfiyat as kf
from tto import pricing as pr
from tto import quantcurve as qc
from tto import swaption as sw
from tto.server import create_app
from tto.service import ServiceError
from tto.xl.values import date_to_serial

FIXED, BILL, LONG, TLREF = "TRT150328T24", "TRB100227T13", "TRT050935T13", "TRT090130T12"
#: Eğri fiyatı: a fixed coupon bond of the desk's list off the trading list (no price on any sheet in replay), a zero coupon
#: one, the trading list's bond the sheet has no price of
OFF, OFF2, ZERO, NO_PRICE = "TRT240227T17", "TRT090627T12", "TRT060127T10", "TRT081128T15"


def serial(d: dt.date) -> float:
    return float(date_to_serial(d))


# ================================================================================================== the rules
def test_the_weights_by_bucket():
    assert [kf.bucket_of(t) for t in (0.1, 1.0, 1.01, 2.5, 3.0, 3.2, 5.0, 5.01, 9.9)] == \
        ["1y", "1y", "3y", "3y", "3y", "5y", "5y", "5y+", "5y+"]
    both = (kf.NBR, kf.OIS)
    assert kf.weights_of("1y", both) == {kf.OIS: 0.75, kf.NBR: 0.25}
    assert kf.weights_of("3y", both) == {kf.NBR: 1.0} == kf.weights_of("5y", both)
    assert kf.weights_of("5y+", both) == {kf.NBR: 0.75, kf.OIS: 0.25}
    # a base that cannot be had gives its share to the other; 1–5Y without the neighbours: no fair (OIS has no weight there)
    assert kf.weights_of("1y", (kf.NBR,)) == {kf.NBR: 1.0} and kf.weights_of("5y+", (kf.OIS,)) == {kf.OIS: 1.0}
    assert kf.weights_of("3y", (kf.OIS,)) == {} and kf.weights_of("1y", ()) == {}
    # the constants the desk may change, named; the floors are the analysis' next-day errors (bp)
    assert kf.SIGMA_FLOOR == {"1y": 37.0, "3y": 23.0, "5y": 16.0, "5y+": 16.0} and set(kf.WIDTH_DEFAULT.values()) == {10.0}
    assert all(abs(sum(w.values()) - 1.0) < 1e-12 for w in kf.WEIGHTS.values())


def _bonds(value: dt.date):
    """Nine coupon bonds and a bill priced off a Nelson-Siegel curve with a few bp of noise: (bond, value, yield, conv)."""
    curve = qc.Nss([0.33, 0.06, -0.04, 0.0], 1.4, 1.4, qc.NS)
    rng = random.Random(7)
    items = []
    for i, years in enumerate((0.8, 1.3, 1.9, 2.6, 3.4, 4.3, 5.5, 7.0, 8.8)):
        b = qc.Bond("TRT%02d" % i, "", "fixed", value + dt.timedelta(days=int(years * 365)), 30.0, 2)
        flows, _ = b.flows(value)
        p = sum(cf * curve.df((d - value).days / 365.0) for d, cf in flows)
        items.append((b, value, b.yield_of(p, value, "simple") + rng.gauss(0, 0.0005), "simple"))
    bill = qc.Bond("TRB01", "", "bill", value + dt.timedelta(days=200))
    p = 100.0 * curve.df(200 / 365.0)
    items.append((bill, value, bill.yield_of(p, value, "simple"), "simple"))
    return items


def test_the_neighbours_curve_is_left_without_the_bond():
    """A bond's base is the curve of the others: its own quote 50 bp off moves nothing of its base (the others' bases move
    a little - it is in their curves); a bill, never in the fit, moves nobody's."""
    value = dt.date(2026, 11, 4)
    items = _bonds(value)
    nss0 = qc.dibs_search(qc.BondFit(items))["nss"]
    base = kf.neighbours(items, nss0)["nbr"]
    assert len(base) == 10 and all(0.30 < v < 0.55 for v in base.values())
    moved = [(b, v, y + (0.005 if b.isin == "TRT04" else 0.0), c) for b, v, y, c in items]
    after = kf.neighbours(moved, nss0)["nbr"]
    # (the same curve: its refit starts from the full fit's β, so it lands on it to the solver's tolerance - 1e-5 bp)
    assert after["TRT04"] == pytest.approx(base["TRT04"], abs=1e-9)
    assert max(abs(after[k] - base[k]) for k in base if k != "TRT04") > 1e-5          # (the others' curves had it)
    bill = [(b, v, y + (0.005 if b.kind == "bill" else 0.0), c) for b, v, y, c in items]
    assert kf.neighbours(bill, nss0)["nbr"] == pytest.approx(base, abs=1e-12)
    # in BIST compound (a coupon bond's (1 + y/2)² − 1): the curve's own yield of the bond's cash flows, compounded
    fit_in = qc.BondFit([x for x in items if x[0].isin != "TRT04"])
    nss = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)["nss"]
    b4 = items[4][0]
    flows, _ = b4.flows(value)
    ys = b4.yield_of(sum(cf * nss.df((d - value).days / 365.0) for d, cf in flows), value, "simple", 0.3)
    assert base["TRT04"] == pytest.approx((1 + ys / 2) ** 2 - 1, abs=1e-8)
    # too few coupon bonds to leave one out: no base, and why
    few = kf.neighbours(items[:6], nss0)
    assert few["nbr"] == {} and "en az 7" in few["why"]


def test_the_fair_is_each_base_plus_the_spread_of_the_previous_close():
    prev = {"day": "2026-10-30", "t": 7.0, "y": 0.3600, kf.NBR: 0.3570, kf.OIS: 0.3250}
    rec = {"day": "2026-11-02", "t": 7.0, "y": 0.3650, kf.NBR: 0.3610, kf.OIS: 0.3300}
    fair, w = kf.fair_from(prev, rec, kf.bucket_of(rec["t"]))
    assert w == {kf.NBR: 0.75, kf.OIS: 0.25}
    assert fair == pytest.approx(0.75 * (0.3610 + 0.0030) + 0.25 * (0.3300 + 0.0350), abs=1e-15)
    # a base the previous close lacks is left out: the other takes its share
    fair2, w2 = kf.fair_from(dict(prev, **{kf.OIS: None}), rec, "5y+")
    assert w2 == {kf.NBR: 1.0} and fair2 == pytest.approx(0.3640, abs=1e-15)
    # the next-day errors: only between closes one day apart on the history's axis
    pos = {"2026-10-29": 0, "2026-10-30": 1, "2026-11-02": 2}
    errs = kf.errors_of([dict(prev, day="2026-10-29"), rec], pos)
    assert errs == []
    errs = kf.errors_of([prev, rec], pos)
    assert len(errs) == 1 and errs[0][1] == pytest.approx((rec["y"] - fair) * 1e4, abs=1e-9)


def test_sigma_is_the_bonds_own_next_day_error_with_its_floor():
    rng = random.Random(3)
    quiet = [rng.gauss(0, 5) for _ in range(80)]
    s = kf.sigma_of(quiet, 16.0)
    assert s["sigma"] == 16.0 and s["floored"] and not s["short"] and s["n"] == 60
    assert s["sd"] == pytest.approx(statistics.pstdev(quiet[-60:]), rel=1e-12)
    loud = [rng.gauss(0, 40) for _ in range(80)]
    s = kf.sigma_of(loud, 16.0)
    assert s["sigma"] == pytest.approx(statistics.pstdev(loud[-60:]), rel=1e-12) and s["sigma"] > 16.0 and not s["floored"]
    s = kf.sigma_of(loud[:12], 23.0)                                           # fewer than 20: the floor alone, said so
    assert s["sigma"] == 23.0 and s["short"] and s["sd"] is None and s["n"] == 12


def test_the_backtest_on_a_history_with_known_answers():
    """A 2Y bond (σ floor 23 bp) on a flat base: 30 quiet closes, then 60 bp cheap one day - 40 of it back 5 closes later
    (a hit, +40 bp) -, 30 more, then 60 bp rich and staying (no hit, 0 bp): 50 %, 20 bp on average."""
    days = ["d%03d" % i for i in range(80)]
    pos = {d: i for i, d in enumerate(days)}
    spread = [0.0] * 80
    for i in range(30, 80):
        spread[i] = 60.0
    for i in range(31, 80):
        spread[i] = 50.0
    for i in range(35, 80):
        spread[i] = 20.0
    for i in range(66, 80):
        spread[i] = 20.0 - 60.0
    recs = [{"day": d, "t": 2.0, "y": 0.35 + spread[i] / 1e4, kf.NBR: 0.35, kf.OIS: None} for i, d in enumerate(days)]
    errs = kf.errors_of(recs, pos)
    assert len(errs) == 79
    bt = kf.backtest(recs, errs)
    assert (bt["n"], bt["hits"]) == (2, 1) and bt["hit"] == 0.5 and bt["avg"] == pytest.approx(20.0, abs=1e-9)
    assert (bt["cheap"]["n"], bt["cheap"]["hits"], bt["cheap"]["avg"]) == (1, 1, pytest.approx(40.0, abs=1e-9))
    assert (bt["rich"]["n"], bt["rich"]["hits"], bt["rich"]["avg"]) == (1, 0, pytest.approx(0.0, abs=1e-9))
    # a smaller jump stays within 2σ (46 bp at the floor): no signal
    calm = [dict(r, y=0.35 + min(abs(spread[i]), 40.0) / 1e4) for i, r in enumerate(recs)]
    assert kf.backtest(calm, kf.errors_of(calm, pos))["n"] == 0


def test_the_good_levels_and_the_market_against_fair():
    """In yield a higher level is cheap: Al at fair + 2σ (a lower price), Sat at fair − 2σ (a higher one).  An offer at
    fair + 2σ or above says AL, a bid at fair − 2σ or below SAT - a broker's price made a yield the sheet's way."""
    bill = kf.Pricer("bill", dt.date(2026, 11, 3), 99.0, 2.0, [], 0.0)
    fair, sigma = 0.35, 37.0
    lo, hi = bill.clean(fair + 2 * sigma / 1e4), bill.clean(fair - 2 * sigma / 1e4)
    assert lo < bill.clean(fair) < hi
    assert bill.yield_of(bill.clean(0.36)) == pytest.approx(0.36, abs=1e-12)
    assert bill.simple(0.348) == pytest.approx(((1.348) ** (99 / 365.0) - 1) / (99 / 365.0), abs=1e-15)
    line = {"board": {"unit": "px", "best_bid": bill.clean(fair - 2.5 * sigma / 1e4), "best_ask": bill.clean(fair + 2.1 * sigma / 1e4),
                      "best_bid_by": "ICAP", "best_ask_by": "TP"},
            "bid": bill.clean(fair + 0.5 * sigma / 1e4), "ask": bill.clean(fair - 0.5 * sigma / 1e4), "quote": {"bid": 5e6, "ask": 0.0}}
    got = kf.KagitFiyat._market(line, bill, fair, sigma)
    by = {(m["src"], m["side"]): m for m in got}
    assert set(by) == {("broker", "bid"), ("broker", "ask"), ("bbg", "bid")}            # (no order on Bloomberg's ask: not a quote)
    assert by[("broker", "ask")]["signal"] == "AL" and by[("broker", "ask")]["z"] == pytest.approx(2.1, abs=1e-6)
    assert by[("broker", "bid")]["signal"] == "SAT" and by[("broker", "bid")]["z"] == pytest.approx(-2.5, abs=1e-6)
    assert by[("bbg", "bid")]["signal"] == "" and by[("bbg", "bid")]["z"] == pytest.approx(0.5, abs=1e-6)
    # a cheap bid is no buy, a rich offer no sell: AL only on an offer, SAT only on a bid
    line = {"board": {"unit": "yld", "best_bid": (fair + 3 * sigma / 1e4) * 100, "best_ask": (fair - 3 * sigma / 1e4) * 100}, "quote": {}}
    assert [m["signal"] for m in kf.KagitFiyat._market(line, bill, fair, sigma)] == ["", ""]


def test_how_the_price_was_built_in_a_line():
    today = dt.date(2026, 11, 20)
    parts = [{"base": kf.NBR, "now": 37.62, "spread": 8.0, "day": "2026-11-19", "weight": 0.75},
             {"base": kf.OIS, "now": 38.10, "spread": -42.0, "day": "2026-11-19", "weight": 0.25}]
    assert kf.how_line(parts, 37.69, 98.452, "2026-11-20", today) == \
        "Komşu eğri 37,62 + dünkü fark +8 bp = 37,70 · OIS 38,10 − 42 bp = 37,68 · %75 / %25 → adil 37,69 · fiyat 98,452 (valör 20.11)"
    # a close older than the last business day is named by its day
    assert kf.how_line(parts[:1], 37.70, None, None, dt.date(2026, 11, 24)).startswith("Komşu eğri 37,62 + 19.11 kapanışındaki fark +8 bp")


# ================================================================================================== Öngörülen: the models
def test_each_projection_model_on_known_numbers():
    """The desk: "Bu adil fiyat bir süre sonra ulaşmasını tahmin ettiğimiz fiyat gibi de olmalı".  Each model's arithmetic
    (decimal compound yields): the bond at 36,00 %, the neighbours' curve 35,50 % (a +50 bp spread), the curve 10 closes on
    at the bond's shorter maturity 35,30 %, the spread's AR(1) mean +20 bp and φ 0,9, β 0,8 on an OIS forward 40 bp
    under the zero rate."""
    y, nbr, roll, ar, beta, move = 0.36, 0.355, 0.353, (0.002, 0.9), 0.8, -0.004
    to = 0.002 + 0.003 * 0.9 ** 10                                       # (the spread 10 closes on: μ + (s − μ)·φ^10)
    assert kf.project(kf.M0, 10, y, nbr, roll, ar, beta, move) == y                                    # no change
    assert kf.project(kf.M1, 10, y, nbr, roll, ar, beta, move) == pytest.approx(0.355 + to, abs=1e-15)  # back toward its mean
    assert kf.project(kf.M2, 10, y, nbr, roll, ar, beta, move) == pytest.approx(0.353 + 0.005, abs=1e-15)  # roll-down alone
    assert kf.project(kf.M3, 10, y, nbr, roll, ar, beta, move) == pytest.approx(0.353 + to, abs=1e-15)
    assert kf.project(kf.M4, 10, y, nbr, roll, ar, beta, move) == pytest.approx(0.353 + to - 0.8 * 0.004, abs=1e-15)
    # a model without one of its parts makes none: M2 the roll-down, M1 / M3 the AR(1), M4 β and the OIS move
    assert kf.project(kf.M2, 10, y, nbr, None, ar, beta, move) is None and kf.project(kf.M1, 10, y, nbr, roll, None, beta, move) is None
    assert kf.project(kf.M4, 10, y, nbr, roll, ar, None, move) is None and kf.project(kf.M4, 10, y, nbr, roll, ar, beta, None) is None
    assert kf.project(kf.M3, 10, y, None, roll, ar, beta, move) is None and kf.project(kf.M0, 10, y, None, None, None, None, None) == y


def test_the_ar1_the_beta_and_their_window():
    rng = random.Random(5)
    s = [0.0]
    for _ in range(40):
        s.append(0.7 * s[-1] + rng.gauss(0, 1))
    mu = sum(s) / len(s)
    num = sum((s[k] - mu) * (s[k + 1] - mu) for k in range(40))
    den = sum((s[k] - mu) ** 2 for k in range(40))
    got = kf.ar1(s, [True] * 40)
    assert got[0] == pytest.approx(mu, abs=1e-15) and got[1] == pytest.approx(num / den, abs=1e-15) and 0.4 < got[1] < 0.95
    # two closes not one day apart on the history's axis are no pair
    gap = [k != 10 for k in range(40)]
    assert kf.ar1(s, gap)[1] == pytest.approx((num - (s[10] - mu) * (s[11] - mu)) / (den - (s[10] - mu) ** 2), abs=1e-15)
    # φ held within [0, 1]: a spread flipping sign each day → 0, one growing away → 1; too few pairs or no variation: none
    assert kf.ar1([(-1.0) ** k for k in range(30)], [True] * 29)[1] == 0.0
    assert kf.ar1([1.1 ** k for k in range(30)], [True] * 29)[1] == 1.0
    assert kf.ar1(s[:20], [True] * 19) is None and kf.ar1([1.0] * 30, [True] * 29) is None
    # β: the yield's daily changes on its OIS base's
    dx = [rng.gauss(0, 10) for _ in range(30)]
    assert kf.beta_of([0.8 * x + 0.1 for x in dx], dx) == pytest.approx(0.8, abs=1e-12) and kf.beta_of(dx[:19], dx[:19]) is None
    # the window: the bond's last w closes up to the forecast's (included) - nothing after it
    days = ["d%03d" % i for i in range(50)]
    pos = {x: i for i, x in enumerate(days)}
    ois = [0.30 + rng.gauss(0, 0.001) for _ in days]
    recs = [{"day": x, "y": 0.35 + s[i % 41] / 1e4 + 0.9 * (ois[i] - 0.30), kf.NBR: 0.35, kf.OIS: ois[i]} for i, x in enumerate(days)]
    p = kf.fit_window(recs, pos, 35, 30)
    win = recs[6:36]
    assert p["n"] == 30 and p["ar"] == kf.ar1([r["y"] - r[kf.NBR] for r in win], [True] * 29)
    assert p["beta"] == pytest.approx(kf.beta_of([b["y"] - a["y"] for a, b in zip(win, win[1:])],
                                                 [b[kf.OIS] - a[kf.OIS] for a, b in zip(win, win[1:])]), abs=1e-15)
    later = [dict(r, y=r["y"] + 0.05) if i > 35 else r for i, r in enumerate(recs)]          # (closes after it: no matter)
    assert kf.fit_window(later, pos, 35, 30) == p


class _Curve(object):
    """A discount curve of annual zero rates ``z(t)`` (t days)."""

    def __init__(self, z):
        self.z = z

    def df(self, t):
        return (1.0 + self.z(t)) ** (-t / 365.0)


def test_the_ois_forwards_move():
    """M4's market-implied move of the base: the OIS forward zero rate from the horizon to the maturity less today's zero
    rate for the same remaining life - none on a flat curve, down where the curve falls (cuts priced), up where it rises."""
    assert kf.ois_move(_Curve(lambda t: 0.40), 100.0, 465.0, 28.0) == pytest.approx(0.0, abs=1e-12)
    falling = _Curve(lambda t: 0.42 - 0.02 * t / 365.0)
    fwd = (falling.df(28.0) / falling.df(365.0)) ** (365.0 / 337.0) - 1.0
    down = kf.ois_move(falling, 0.0, 365.0, 28.0)
    assert down == pytest.approx(fwd - (0.42 - 0.02 * 337.0 / 365.0), abs=1e-12) and down < 0
    assert kf.ois_move(_Curve(lambda t: 0.30 + 0.02 * t / 365.0), 0.0, 730.0, 28.0) > 0
    assert kf.ois_move(falling, 0.0, 20.0, 28.0) is None and kf.ois_move(None, 0.0, 365.0, 28.0) is None


def test_the_roll_down_is_the_bonds_yield_on_the_same_curve_later():
    """M2's "the curve unchanged, the bond shorter": the bond's cash flows from the horizon's value date on the very curve
    its base is read on now - for a coupon bond the curve of the others, for a bill the curve of all."""
    value = dt.date(2026, 11, 4)
    items = _bonds(value)
    nss0 = qc.dibs_search(qc.BondFit(items))["nss"]
    later = value + dt.timedelta(days=28)
    got = kf.neighbours(items, nss0, ahead={b.isin: {20: later} for b, _, _, _ in items})
    assert got["nbr"] == kf.neighbours(items, nss0)["nbr"] and set(got["roll"]) == set(got["nbr"])
    fit_in = qc.BondFit([x for x in items if x[0].isin != "TRT04"])
    nss = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)["nss"]
    b4 = items[4][0]
    flows, _ = b4.flows(later)
    ys = b4.yield_of(sum(cf * nss.df((d - later).days / 365.0) for d, cf in flows), later, "simple", items[4][2])
    assert got["roll"]["TRT04"][20] == pytest.approx((1 + ys / 2) ** 2 - 1, abs=1e-8)
    bill = items[-1][0]
    t = (bill.maturity - later).days / 365.0
    yb = bill.yield_of(100.0 * got["nss"].df(t), later, "simple")
    assert got["roll"]["TRB01"][20] == pytest.approx((1 + yb * t) ** (1 / t) - 1, abs=1e-10)
    # the horizon's days: TRY business days (a holiday skipped)
    assert kf.workday(dt.date(2026, 11, 3), 5, frozenset()) == dt.date(2026, 11, 10)
    assert kf.workday(dt.date(2026, 11, 3), 5, frozenset({serial(dt.date(2026, 11, 6))})) == dt.date(2026, 11, 11)


def test_the_decision_rule_falls_back_to_m2_where_nothing_beats_no_change():
    """The rule fixed before measuring: per bucket and horizon the lowest out-of-sample RMSE, if it beats no change (M0) by
    5 % or more; else M2, shown as "eğri ve fark değişmezse" with the plain record that no model beat no change."""
    assert kf.choose({"M1/60": 95.0, "M2": 99.0, "M4/120": 97.0}, 100.0) == ("M1/60", True)            # 5 % better: used
    assert kf.choose({"M1/60": 95.2, "M2": 99.0, "M4/120": 97.0}, 100.0) == (kf.M2, False)             # 4,8 %: not enough
    assert kf.choose({"M2": 101.0, "M3/60": 104.0}, 100.0) == (kf.M2, False)
    # the table the desk's history gave: a model used beat M0 by 5 % (and M2); elsewhere M2, said
    used = []
    for bucket, by_h in kf.PROJECTION.items():
        assert set(by_h) == {5, 10, 20}
        for h, rec in by_h.items():
            if rec["beat"]:
                assert rec["model"] in (kf.M1, kf.M3, kf.M4, kf.M2) and rec["window"] in kf.AR_WINDOWS + (0,)
                assert 1 - rec["rmse"] / rec["m0"] >= kf.BEAT and rec["rmse"] <= rec["m2"]["rmse"]
                used.append((bucket, h, rec["model"], rec["window"]))
            else:
                assert rec["model"] == kf.M2 and rec["gain"] < kf.BEAT * 100 and rec["rmse"] == rec["m2"]["rmse"]
                assert kf.record_text(rec, kf.M2).startswith("geri test: hiçbir model değişmezse'yi %5 yenemedi (en iyisi ")
    assert used == [("1y", 20, kf.M4, 120), ("3y", 20, kf.M4, 60)] and kf.DEFAULT_H == 20
    rec = kf.PROJECTION["3y"][20]
    assert kf.record_text(rec, kf.M4) == "geri test: RMSE 149 bp, değişmezse'ye göre %9,0 daha iyi, yön isabeti %64 (259)"
    assert kf.record_text(rec, kf.M2) == "geri test (eğri ve fark değişmezse): RMSE 166 bp (değişmez 164 bp), yön isabeti %50 (221)"
    assert kf.record_text(kf.PROJECTION["5y"][20], kf.M2) == ("geri test: hiçbir model değişmezse'yi %5 yenemedi (en iyisi M2, −%0,9) · "
                                                            "eğri ve fark değişmezse: RMSE 133 bp (değişmez 132 bp), yön isabeti %48 (279)")


# ================================================================================================== on the replay day
@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def market(svc) -> pr.Market:
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def run():
        calc = svc.interp.boot_of(book, svc._calc(None, book))
        return pr.read(lambda s, r, c: calc.get(idx[s], r, c))
    return svc.et.call(run)


@pytest.fixture(scope="module")
def seeded(svc):
    """70 week days of made-up closes before the replay day for every bond of the trading list (the sheet's compound
    yield on the last one, a common and an own random walk back from it; 36 % for the coupon bond the sheet has no price
    of - read as a simple yield, as the history's convention is when the sheet has none), every OIS tenor Motor
    bootstraps (the sheet's quotes on the last one) and TLREF; and a close on the replay day itself, 40 bp off, that must
    not count."""
    snap = svc.history.snapshot()
    today = svc.history.today()
    days = []
    d = today - dt.timedelta(days=1)
    while len(days) < 70:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= dt.timedelta(days=1)
    days.reverse()
    rng = random.Random(11)
    bonds = {}
    for dd in snap["defs"]:
        if dd.group == "dibs" and dd.unit == "pct":
            t = cell(svc, "DİBS RV!T%d" % dd.info["row"])
            if type(t) is float:
                bonds[dd.info["isin"]] = (dd, t * 100.0)
            elif dd.info.get("type") == "S":
                bonds[dd.info["isin"]] = (dd, 36.0)
    closes = {isin: {} for isin in bonds}
    level = {isin: t for isin, (_, t) in bonds.items()}
    for iso in reversed(days):
        for isin in bonds:
            closes[isin][iso] = round(level[isin], 10)
        common = rng.gauss(0.0, 0.08)
        for isin in bonds:
            level[isin] -= common + rng.gauss(0.0, 0.05)
    for isin, (dd, t) in bonds.items():
        svc.store.hist_upsert(dd.id, sorted(closes[isin].items()) + [(today.isoformat(), t + 0.4)])
    mk = market(svc)
    quotes = dict(mk.ois_quotes)
    ids = {float(x.months): x.id for x in snap["defs"] if x.group == "ois" and x.months and x.months >= 1}
    ois = {m: {} for m in quotes}
    lvl = {m: quotes[m] * 100.0 for m in quotes}
    for iso in reversed(days):
        for m in quotes:
            ois[m][iso] = round(lvl[m], 10)
        common = rng.gauss(0.0, 0.06)
        for m in quotes:
            lvl[m] -= common + rng.gauss(0.0, 0.02)
    for m, s in ois.items():
        svc.store.hist_upsert(ids[m], sorted(s.items()))
    ref = next(x for x in snap["defs"] if x.group == "ref")
    svc.store.hist_upsert(ref.id, [(iso, 39.5) for iso in days])
    svc.history.rev += 1
    return {"days": days, "today": today, "closes": closes, "ois": ois, "mk": mk, "bonds": bonds}


def rows_of(svc, user):
    return {r["isin"]: r for r in svc.kagit_fiyat(user)["rows"]}


def test_without_closes_the_page_says_why(svc):
    """The recorded file has no bond history (before the made-up one below): no spread, so no fair - each bond says
    why; the neighbours' curve now is there all the same, its τ searched on the quotes now."""
    d = svc.kagit_fiyat(svc.login("Kâğıt Geçmişsiz")["user"])
    assert d["ok"] and d["history"]["days"] == 0 and "geçmiş kapanışı yok" in d["history"]["why"]
    assert d["fit"]["ok"] and d["fit"]["tau_from"] == "şimdi" and d["fit"]["n_fit"] == 13
    rows = {r["isin"]: r for r in d["rows"]}
    assert not rows[FIXED]["priced"] and "geçmiş kapanışı yok" in rows[FIXED]["why"]
    assert rows[FIXED]["bases"]["nbr"]["now"] > 30 and rows[FIXED]["bases"]["ois"]["now"] > 30      # (the bases now are there)
    assert "TLREF'e endeksli" in rows[TLREF]["why"]


# -------------------------------------------------------------------------------- Eğri fiyatı (the desk, 20.11.2026)
def test_market_of_a_two_sided_quote_or_todays_last_trade():
    today = dt.date(2026, 11, 3)
    assert kf.market_of(100.1, 100.125, 99.0, today, today) == (pytest.approx(100.1125), "bid / ask ortası")
    assert kf.market_of(100.1, "–", 100.2, today, today) == (100.2, "son işlem (bugün)")             # one side: no quote
    assert kf.market_of(None, None, 100.2, dt.date(2026, 11, 2), today) is None                     # yesterday's trade: none
    assert kf.market_of("", "", "", None, today) is None


def _row(isin, kind, bucket, ns, base, w, own=None, market=None):
    """A main table row before its answer (``_curve_row``'s; its clean price made up: 100 − yield): Eğri a fixed coupon
    bond's curve, a bill's base."""
    return {"isin": isin, "kind": kind, "bucket": bucket, "market": market, "_vtext": "valör 04.11",
            "_own": own or {"why": "geçmiş kapanışı yok"},
            "_level": lambda y: {"yield": y * 100.0, "simple": None, "clean": 100.0 - y * 100.0},
            "base": {"yield": base * 100.0, "weights": w, "text": kf.base_text(w)},
            "curve": {"yield": (ns if kind == "S" else base) * 100.0, "ns": ns * 100.0, "ois": 42.0, "fit": "Nelson-Siegel",
                      "base": "eğri" if kind == "S" else kf.base_text(w), "weights": {kf.NBR: 1.0} if kind == "S" else w}}


def test_the_rule_by_kind_and_its_typical_error():
    """A bond with no price and no history: a fixed coupon bond the curve alone ("eğri": the leave-one-out validation's best
    in every bucket); a bill or zero coupon bond its bucket's base - ≤1Y 75 % OIS + 25 % the curve, 1–5Y the curve, 5Y+ 75 %
    the curve + 25 % OIS - + the median spread of the market-priced bills and zero coupon bonds of its bucket to their
    bases, itself left out ("eğri + akran farkı"; none: the base alone, warned); a bond with its own history its base + its
    own last spread, whatever its kind.  Each says its rule's typical error - "ölçülemedi" on fewer than 2 bonds."""
    assert kf.base_of("1y", 0.36, 0.42) == (pytest.approx(0.75 * 0.42 + 0.25 * 0.36), {kf.OIS: 0.75, kf.NBR: 0.25})
    assert kf.base_of("3y", 0.39, 0.40) == (0.39, {kf.NBR: 1.0}) and kf.base_of("5y", 0.38, None) == (0.38, {kf.NBR: 1.0})
    assert kf.base_of("5y+", 0.36, 0.32) == (pytest.approx(0.75 * 0.36 + 0.25 * 0.32), {kf.NBR: 0.75, kf.OIS: 0.25})
    assert kf.base_of("1y", 0.36, None) == (0.36, {kf.NBR: 1.0}) and kf.base_of("3y", None, 0.4) == (None, {})
    assert [kf.base_text(kf.base_of(b, 0.3, 0.3)[1]) for b in ("1y", "3y", "5y+")] == ["OIS %75 + eğri %25", "eğri", "eğri %75 + OIS %25"]
    peers = [("A", -0.0190), ("B", -0.0150), ("C", -0.0300)]
    assert kf.peer_spread(peers) == (pytest.approx(-0.0190), 3)
    assert kf.peer_spread(peers, "A") == (pytest.approx(-0.0225), 2)          # (itself out: the median of the two others)
    assert kf.peer_spread([("A", 0.01)], "A") == (None, 0) and kf.peer_spread([]) == (None, 0)
    w1 = {kf.OIS: 0.75, kf.NBR: 0.25}
    bands = {("1y", "S", "curve"): (76.2, 4), ("1y", "B", "peer"): (43.3, 2), ("1y", "S", "spread"): (None, 1)}
    # a fixed coupon bond: the curve alone - never its peers, whatever its bucket's base
    s = _row("S1", "S", "1y", 0.36, 0.40, w1)
    kf.KagitFiyat._answer(s, {"1y": [("B9", -0.06)]}, bands)
    assert s["price"]["label"] == kf.EGRI and s["price"]["kind"] == "curve" and s["price"]["yield"] == pytest.approx(36.0) and s["alt"]["tag"] is None
    assert s["price"]["how"].startswith("eğri %36,00 (Nelson-Siegel) = %36,00 · temiz 64,000 (valör 04.11) · kendi son farkı yok")
    assert s["price"]["err"] == {"bp": 76.2, "n": 4}
    assert s["price"]["how"].endswith("tipik hata ±76 bp (bu kural bugün piyasa fiyatlı 4 ≤ 1Y sabit kuponlu kâğıtta, her biri kendisi "
                                      "dışarıda fiyatlanınca: piyasadan sapmanın medyanı)")
    # a bill: its base + its peers' median (itself not among them)
    b = _row("B1", "B", "1y", 0.35, 0.41, w1)
    kf.KagitFiyat._answer(b, {"1y": [("B1", 0.5), ("B2", -0.0600), ("B3", -0.0640)]}, bands)
    assert b["price"]["label"] == kf.EGRI_AKRAN and b["price"]["yield"] == pytest.approx(41.0 - 6.2) and b["price"]["peers"] == 2
    assert "OIS %75 + eğri %25 %41,00 (eğri %35,00; OIS %42,00; Nelson-Siegel)" in b["price"]["how"] and b["alt"]["tag"] == "akran farkı"
    assert "akran farkı −620 bp (2 bono / kuponsuz" in b["price"]["how"] and "tipik hata ±43 bp" in b["price"]["how"]
    # no bill priced in its bucket: the base alone, warned - its typical error not measured
    z = _row("Z1", "B", "5y+", 0.35, 0.34, {kf.NBR: 0.75, kf.OIS: 0.25})
    kf.KagitFiyat._answer(z, {"1y": [("B2", -0.06)]}, bands)
    assert z["price"]["label"] == kf.EGRI and z["price"]["yield"] == pytest.approx(34.0) and "akran yok - taban tek başına" in z["price"]["how"]
    assert z["price"]["err"] == {"bp": None, "n": 0}
    assert z["price"]["how"].endswith("tipik hata ölçülemedi (bu kuralla bugün ölçülen piyasa fiyatlı 5Y+ bono / kuponsuz kâğıt: 0; en az 2 gerekli)")
    # its own history: its base + its own last spread, whatever its kind (that rule's typical error here on 1 bond: none)
    point = {"src": "trade", "day": "2026-11-02", "age": 1, "y": 0.3650, "what": "DİBS RV 99,500 (valör 03.11; temiz fiyat)"}
    o = _row("S2", "S", "1y", 0.36, 0.40, w1, own={"y": 0.3700, "day": "2026-11-02", "spread": -0.0300, "weights": w1, "point": point,
                                                   "ties": ["kapanış"]})
    kf.KagitFiyat._answer(o, {}, bands)
    assert o["price"]["label"] == "eğri + son fark (son işlem 02.11, 1 iş günü önce)" and o["price"]["yield"] == pytest.approx(37.0)
    assert o["alt"]["tag"] == "son fark, son işlem 02.11" and o["alt"]["src"] == "trade" and o["alt"]["age"] == 1
    assert "OIS %75 + eğri %25 %40,00" in o["price"]["how"] and ("+ son fark −300 bp (son işlem 02.11, 1 iş günü önce: DİBS RV 99,500 "
                                                                  "(valör 03.11; temiz fiyat) → %36,50, o günün kapanış eğrisine göre; "
                                                                  "aynı gün kapanış da var, son işlem seçildi) = %37,00") in o["price"]["how"]
    assert o["price"]["err"] == {"bp": None, "n": 1} and "tipik hata ölçülemedi" in o["price"]["how"]
    # a market: the market's, Fark against the Eğri column (a fixed coupon bond's curve); the rest kept for the upload
    m = _row("S3", "S", "1y", 0.36, 0.40, w1, market={"yield": 37.0, "simple": None, "clean": 63.0, "source": "DİBS RV bid / ask ortası"})
    kf.KagitFiyat._answer(m, {}, bands)
    assert m["price"]["label"] == kf.PIYASA and m["diff"] == pytest.approx(100.0) and m["alt"]["label"] == kf.EGRI
    assert m["price"]["how"].endswith("(valör 04.11) · eğri %36,00, fark +100 bp") and "tipik hata" not in m["price"]["how"]


def test_the_most_recent_point_and_the_same_days_order():
    """A bond's last known spread comes from its most recent point; on the same day a trade before an auction before a
    close (the history's, then the one kept); a point needs a spread to a base to count; its age in TRY business days."""
    def p(src, day, spread=True):
        return {"src": src, "day": day, "spread": {kf.NBR: 0.01} if spread else {}}

    pts = [p("close", "2026-11-02"), p("auction", "2026-10-30"), p("kept", "2026-11-02"), p("trade", "2026-10-28")]
    assert kf.pick_point(pts)["src"] == "close"                                     # (the latest day; the history's close first)
    assert kf.pick_point(pts + [p("auction", "2026-11-02")])["src"] == "auction"
    assert kf.pick_point(pts + [p("auction", "2026-11-02"), p("trade", "2026-11-02")])["src"] == "trade"
    assert kf.pick_point(pts + [p("trade", "2026-11-03", spread=False)])["day"] == "2026-11-02"      # (not measured: not a point)
    assert kf.pick_point(pts + [p("auction", "2026-11-03")], "2026-11-03")["day"] == "2026-11-02"   # (before today: the fair's)
    assert kf.pick_point([]) is None and kf.pick_point([p("kept", "2026-11-03")], "2026-11-03") is None
    hol = frozenset({serial(dt.date(2026, 10, 29))})
    assert kf.business_days(dt.date(2026, 10, 27), dt.date(2026, 11, 2), hol) == 3      # (28, 30 October, 2 November)
    assert kf.business_days(dt.date(2026, 11, 3), dt.date(2026, 11, 3), hol) == 0 and kf.age_text(0) == "bugün"
    assert kf.point_label({"src": "auction", "day": "2026-11-20", "age": 0}) == "eğri + son fark (ihale 20.11, bugün)"
    assert kf.point_label({"src": "kept", "day": "2026-11-19", "age": 1}) == "eğri + son fark (kapanış 19.11, 1 iş günü önce)"


def test_a_points_yield_at_its_value_date():
    """A point's yield (BIST compound) at its value date, the repo's conventions: an auction value - a bill's simple
    yield, a fixed coupon bond's clean price -; a last trade's price - a fixed coupon bond's clean price, a bill's price
    (Bloomberg's TRY bills are quoted in price; a figure that can only be a yield read as one)."""
    vd = dt.date(2026, 11, 4)
    bill = qc.Bond("TRB1", "", "bill", vd + dt.timedelta(days=200))
    t = 200 / 365.0
    assert kf.auction_yield(bill, "B", 31.5, vd) == pytest.approx((1 + 0.315 * t) ** (1 / t) - 1, abs=1e-15)
    fixed = qc.Bond("TRT1", "", "fixed", dt.date(2028, 3, 15), 30.0, 2)
    s = fixed.yield_of(99.5 + qc.accrued(fixed, vd), vd, "simple", 0.3)
    assert kf.auction_yield(fixed, "S", 99.5, vd) == pytest.approx((1 + s / 2) ** 2 - 1, abs=1e-12)
    assert kf.trade_yield(fixed, "S", 99.5, vd) == (pytest.approx((1 + s / 2) ** 2 - 1, abs=1e-12), "temiz fiyat")
    y, how = kf.trade_yield(bill, "B", 85.0, vd)
    assert how == "fiyat" and y == pytest.approx((100 / 85.0) ** (1 / t) - 1, abs=1e-12)
    y, how = kf.trade_yield(bill, "B", 31.4, vd)                                    # (as a price 399 %: a yield's figure)
    assert how.startswith("getiri olarak okundu") and y == pytest.approx((1 + 0.314 * t) ** (1 / t) - 1, abs=1e-12)
    assert kf.trade_yield(bill, "B", 85.0, bill.maturity)[0] is None and kf.auction_yield(bill, "B", 31.5, bill.maturity) is None
    # the value dates: a trade's its source's (ISL0 the same day, else the next week day), an auction's the line's own
    assert qc._value_date(dt.date(2026, 10, 30), {"source": "ISL1"}) == dt.date(2026, 11, 2)
    assert qc._value_date(dt.date(2026, 10, 30), {"source": "ISL0"}) == dt.date(2026, 10, 30)


def test_the_validation_prices_each_bond_without_its_own_quote():
    """The live check behind the typical errors (and the desk copy's validation): each market-priced bond priced as if it
    had no price - a fixed coupon bond at its curve (the page's leave-one-out: the fit without it), a bill at its base + the
    other bills' median spread to their bases - its own quote in none of it; the errors per rule, bucket and kind group,
    none on fewer than 2 bonds."""
    def c(isin, group, bucket, market, ns, ois=None, own=None):
        return {"isin": isin, "group": group, "bucket": bucket, "market": market, "ns": ns, "ois": ois, "own": own}

    cands = [c("S1", "S", "3y", 0.3950, 0.3930), c("S2", "S", "3y", 0.3980, 0.4000, own=0.3975), c("S3", "S", "3y", 0.3900, 0.3950, own=0.3910),
             c("B1", "B", "1y", 0.3480, 0.3530, 0.4260), c("B2", "B", "1y", 0.3430, 0.3560, 0.4220), c("B3", "B", "1y", 0.3500, 0.3500, 0.4300),
             c("B4", "B", "3y", 0.3600, 0.3700), c("S4", "S", "5y+", 0.3600, 0.3550, 0.3300)]
    res = kf.validate(cands)
    by = {x["isin"]: x for x in cands}

    def base(code):
        return kf.base_of(by[code]["bucket"], by[code]["ns"], by[code]["ois"])[0]

    # a fixed coupon bond: its curve
    assert res["S1"]["rule"] == "curve" and res["S1"]["after"] == 0.3930 and res["S1"]["err_after"] == pytest.approx(-20.0) == res["S1"]["err_before"]
    # a bill: its base + the other bills' median spread to their bases (itself not among them); its own quote moves only its error
    assert res["B1"]["rule"] == "peer" and res["B1"]["peers"] == 2
    assert res["B1"]["after"] == pytest.approx(base("B1") + statistics.median([by[p]["market"] - base(p) for p in ("B2", "B3")]))
    moved = kf.validate([dict(x, market=x["market"] + 0.01) if x["isin"] == "B1" else x for x in cands])
    assert moved["B1"]["after"] == pytest.approx(res["B1"]["after"]) and moved["B1"]["err_after"] == pytest.approx(res["B1"]["err_after"] - 100.0)
    assert abs(moved["B2"]["after"] - res["B2"]["after"]) > 1e-4                                  # (B1 is its peer)
    # alone in its bucket: the base alone; its own last spread's error where it has history
    assert res["B4"]["rule"] == "curve" and res["B4"]["peers"] == 0 and res["B4"]["after"] == pytest.approx(0.3700)
    assert res["S2"]["err_own"] == pytest.approx(-5.0) and res["S1"]["err_own"] is None
    bands = kf.error_bands(res)
    assert bands[("3y", "S", "curve")] == (pytest.approx(20.0), 3) and bands[("3y", "S", "spread")] == (pytest.approx(7.5), 2)
    assert bands[("1y", "B", "peer")] == (pytest.approx(15.0), 3)                     # (|−15|, |+26,25|, |−11,25|)
    assert bands[("3y", "B", "curve")] == (None, 1) and bands[("5y+", "S", "curve")] == (None, 1)
    assert kf.error_text(bands[("1y", "B", "peer")], "1y", "B") == (
        "tipik hata ±15 bp (bu kural bugün piyasa fiyatlı 3 ≤ 1Y bono / kuponsuz kâğıtta, her biri kendisi dışarıda fiyatlanınca: "
        "piyasadan sapmanın medyanı)")
    assert kf.error_text(bands[("3y", "B", "curve")], "3y", "B") == (
        "tipik hata ölçülemedi (bu kuralla bugün ölçülen piyasa fiyatlı 1–3Y bono / kuponsuz kâğıt: 1; en az 2 gerekli)")
    table = {(r["bucket"], r["group"]): r for r in kf.validation_table(res)}
    assert table[("1y", "B")]["rules"] == ["peer"] and table[("3y", "S")]["after"]["median"] == pytest.approx(20.0)
    assert table[("3y", "S")]["own"] == {"n": 2, "median": pytest.approx(7.5), "max": pytest.approx(10.0)}
    assert table[("3y", "B")]["no_peer"] == 1 and sum(r["n"] for r in table.values()) == len(cands)


def live_fit(svc, user):
    """What the page reads now: the sheets, the closes' part, the fit of the quotes now (its curve of all of them)."""
    k = svc.kagitfiyat
    got = svc.et.call(k._read, user)
    panel = k.closes(got)
    return got, panel, k.now_fit(got, panel, k.horizon_days(got))


def test_every_bond_of_the_desks_list_gets_a_curve_price(svc):
    """(the desk, 20.11.2026: "curve'e göre fiyatı olmayanların da fiyatını bulmak içindi asıl") Every fixed coupon bond,
    bill and zero coupon bond of the desk's list has a row - the trading list's priced on DİBS RV's quotes ("piyasa", the
    middle of bid / ask, its yield DİBS RV's own); the others (no market in replay, no closes) by their kind: a fixed coupon
    bond at the curve alone ("eğri": the Nelson-Siegel fitted now to the bonds with prices, at its own cash flows from its
    value date, on the fit without it when it is in it); a bill or zero coupon bond at its bucket's base (the curve and the
    OIS zero rate at its maturity, by the fair model's weights) + the median spread to their bases of today's market-priced
    bills and zero coupon bonds of its bucket ("eğri + akran farkı"; none: the base alone, "eğri", said).  Each with its
    rule's typical error, measured now: the same rule on the market-priced bonds of its bucket and kind group, each
    without its own quote.  Market − Eğri in bp; the floaters left out and counted, with why."""
    from tto import bonds as bd
    u = svc.login("Eğri Katalog")["user"]
    d = svc.kagit_fiyat(u)
    rows = {r["isin"]: r for r in d["curve_rows"]}
    cat = {b["isin"] for b in bd.listed(dt.date(2026, 11, 3)) if b["kind"] in kf.CURVE_KINDS}
    assert set(rows) == cat and len(cat) >= 29 and OFF in rows and ZERO in rows and FIXED in rows
    assert [r["kind"] for r in d["curve_rows"]] == sorted((r["kind"] for r in d["curve_rows"]), key="BS".index)
    got, panel, now = live_fit(svc, u)
    priced = [r for r in d["curve_rows"] if r["market"] is not None and r["base"] is not None]

    def errs(bucket, kind):
        """|the curve − the market| (bp) of the market-priced bonds of a bucket and kind (their curves: without them)."""
        return [abs(r["curve"]["yield"] - r["market"]["yield"]) * 100.0 for r in priced if r["bucket"] == bucket and r["kind"] == kind]

    # a fixed coupon bond off the trading list (≤ 1Y): the curve alone, at its own cash flows (value date T+1, the bonds'
    # source) on the curve of all - its bucket's base (75 % OIS + 25 % the curve) beside it, not used
    o = rows[OFF]
    b = qc._bond_of(OFF, {}, None)
    value = dt.date(2026, 11, 4)
    ns = kf.yield_on(b, now["full"], value, "compound", 0.35)
    ois = kf.zero_rate(got["boot"], got["mk"].ois_spot, serial(b.maturity))
    assert o["market"] is None and not o["listed"] and o["value_date"] == "2026-11-04" and o["diff"] is None and o["bucket"] == "1y"
    assert o["curve"]["yield"] == pytest.approx(ns * 100.0, abs=1e-9) == o["curve"]["ns"] and o["curve"]["base"] == "eğri" and o["curve"]["loo"] is False
    assert o["base"]["yield"] == pytest.approx((0.75 * ois + 0.25 * ns) * 100.0, abs=1e-9) and o["base"]["text"] == "OIS %75 + eğri %25"
    assert o["price"]["label"] == kf.EGRI and o["price"]["kind"] == "curve" and o["price"]["yield"] == o["curve"]["yield"]
    assert o["price"]["clean"] == pytest.approx(kf.Pricer("fixed", value, None, 2.0, [], qc.accrued(b, value), b).clean(ns), abs=1e-9)
    assert o["alt"] == o["price"] and "kâğıt uydurmada değil" in o["price"]["how"] and "geçmiş kapanışı yok" in o["price"]["how"]
    # its typical error: the curve's on the market-priced ≤ 1Y fixed coupon bonds (each on the fit without it)
    e = errs("1y", "S")
    assert len(e) >= 2 and o["price"]["err"] == {"bp": pytest.approx(statistics.median(e), abs=1e-6), "n": len(e)}
    assert "tipik hata ±%d bp (bu kural bugün piyasa fiyatlı %d ≤ 1Y sabit kuponlu kâğıtta" % (round(statistics.median(e)), len(e)) in o["price"]["how"]
    # a zero coupon bond off the list: its value date the bills' (ISL0, today), priced as a bill - its base + the bills'
    # median spread to theirs; its typical error that rule's on the two bills: each priced off the other, |s1 − s2|
    z = rows[ZERO]
    zb = qc._bond_of(ZERO, {}, None)
    bills = [(r["isin"], (r["market"]["yield"] - r["base"]["yield"]) / 100.0) for r in priced if r["bucket"] == "1y" and r["kind"] == "B"]
    assert len(bills) == 2 and BILL in dict(bills) and z["curve"]["yield"] == z["base"]["yield"] and z["curve"]["base"] == "OIS %75 + eğri %25"
    assert z["value_date"] == "2026-11-03" and z["kind"] == "B" and z["price"]["label"] == kf.EGRI_AKRAN and z["price"]["peers"] == 2
    assert z["price"]["yield"] == pytest.approx(z["base"]["yield"] + statistics.median(s for _, s in bills) * 100.0, abs=1e-9)
    assert z["price"]["err"] == {"bp": pytest.approx(abs(bills[0][1] - bills[1][1]) * 1e4, abs=1e-6), "n": 2} and "bono / kuponsuz" in z["price"]["how"]
    assert z["price"]["clean"] == pytest.approx(100.0 / (1 + z["price"]["yield"] / 100) ** ((zb.maturity - dt.date(2026, 11, 3)).days / 365.0), abs=1e-9)
    # a bond of the trading list with a quote: the market's (DİBS RV's bid / ask middle, its compound yield the sheet's own);
    # its curve on the fit without it (leave one out), not the curve of all of them; market − curve
    f = rows[FIXED]
    r = next(x for x in got["lines"] if x["isin"] == FIXED)
    assert f["listed"] and f["price"]["label"] == kf.PIYASA and f["market"]["clean"] == pytest.approx((r["bid"] + r["ask"]) / 2.0, abs=1e-12)
    assert f["market"]["yield"] == pytest.approx(cell(svc, "DİBS RV!T%d" % r["row"]) * 100.0, abs=1e-9) and "DİBS RV bid / ask ortası" in f["market"]["source"]
    assert f["curve"]["loo"] and f["curve"]["yield"] == pytest.approx(now["nbr"][FIXED] * 100.0, abs=1e-12)
    fb = qc._bond_of(FIXED, {}, next(q for q in got["quant"] if q["isin"] == FIXED))
    whole = kf.yield_on(fb, now["full"], qc._value_date(dt.date(2026, 11, 3), next(q for q in got["quant"] if q["isin"] == FIXED)), "simple", 0.36)
    assert abs(f["curve"]["yield"] - whole * 100.0) > 0.001                                     # (the fit with it is another curve)
    assert f["diff"] == pytest.approx((f["market"]["yield"] - f["curve"]["yield"]) * 100.0, abs=1e-9)
    assert f["bucket"] == "3y" and f["base"]["text"] == "eğri" and f["curve"]["weights"] == {kf.NBR: 1.0}       # (1–5Y: the curve alone)
    # the upload's: never the market - its most recent point, DİBS RV's last trade today, on the curve now (the trade's own
    # yield); without closes its typical error is not measured
    y_f = kf.trade_yield(fb, "S", r["last"], dt.date(2026, 11, 4))[0]
    assert f["alt"]["label"] == "eğri + son fark (son işlem 03.11, bugün)" and f["alt"]["yield"] == pytest.approx(y_f * 100.0, abs=1e-9)
    assert f["alt"]["err"] == {"bp": None, "n": 0} and "tipik hata ölçülemedi" in f["alt"]["how"]
    # the trading list's bond the sheet has no price of: no closes yet - the curve
    assert rows[NO_PRICE]["market"] is None and rows[NO_PRICE]["price"]["label"] == kf.EGRI
    # every bond without a market: a fixed coupon bond the curve; a bill or zero coupon bond its peers' where its bucket has
    # a market-priced one other than itself, else its base alone, warned; each its typical error - or "ölçülemedi"
    for r in d["curve_rows"]:
        if r["price"] is None or r["market"] is not None:
            continue
        has = [c for c, _ in bills if c != r["isin"]] if r["bucket"] == "1y" else \
            [x["isin"] for x in priced if x["bucket"] == r["bucket"] and x["kind"] == "B" and x["isin"] != r["isin"]]
        want_label = kf.EGRI if r["kind"] == "S" or not has else kf.EGRI_AKRAN
        assert r["price"]["label"] == want_label, r["isin"]
        assert r["kind"] == "S" or has or "akran yok - taban tek başına" in r["price"]["how"], r["isin"]
        n = r["price"]["err"]["n"]
        assert ("tipik hata ±" in r["price"]["how"]) == (n >= 2) and ("tipik hata ölçülemedi" in r["price"]["how"]) == (n < 2), r["isin"]
    # the floaters: not in the table, counted with why
    assert not any(r["cat_kind"] in ("float", "cpi", "frn") for r in d["curve_rows"]) and TLREF not in rows
    want = {k: sum(1 for x in bd.listed(dt.date(2026, 11, 3)) if x["kind"] == k) for k, _ in kf.OTHER_KINDS}
    assert {x["kind"]: x["n"] for x in d["others"]} == {k: n for k, n in want.items() if n} and "nominal eğriye göre" in d["others_why"]
    assert d["counts"]["market"] >= 14 and d["counts"]["peer"] >= 2 and d["counts"]["curve"] >= 10 and d["counts"]["spread"] == 0
    # the validation: the same check (every market-priced bond as if it had no price), its table per bucket and kind
    v = svc.kagitfiyat.validation(u)
    assert set(v["bonds"]) == {r["isin"] for r in priced} and sum(t["n"] for t in v["table"]) == len(priced)
    assert v["bands"]["1y/S/curve"] == (pytest.approx(statistics.median(e), abs=1e-6), len(e))
    assert {t["group"]: t["rules"] for t in v["table"] if t["bucket"] == "1y"} == {"B": ["peer"], "S": ["curve"]}
    # a fixed coupon bond of the catalog without a coupon: its row, no price, why
    nocpn = [x for x in d["curve_rows"] if x["price"] is None]
    assert all("kuponu bilinmiyor" in x["why"] for x in nocpn if x["cat_kind"] == "fixed")


def test_the_spread_is_taken_at_the_last_close_and_fair_is_base_plus_spread(svc, seeded):
    u = svc.login("Kâğıt Fiyat")["user"]
    d = svc.kagit_fiyat(u)
    assert d["ok"] and d["history"]["days"] == 70 and d["history"]["last"] == seeded["days"][-1] and d["history"]["ois_days"] == 70
    rows = {r["isin"]: r for r in d["rows"]}
    last = seeded["days"][-1]
    panel = svc.kagitfiyat._panel[1]
    nss0 = panel["nss0"]
    assert d["history"]["tau_day"] == last and d["fit"]["ok"] and d["fit"]["tau_from"] == "geçmiş"
    # the last close's bases, worked out again: the neighbours' curve of that day's closes (the bond left out), OIS
    # Motor's bootstrap of that day's closes - the spread is the close's yield less each
    book = svc.books["tto"]
    got = svc.et.call(svc.kagitfiyat._read, u)
    quant = {r["isin"]: r for r in got["quant"]}
    day = dt.date.fromisoformat(last)
    # (each close read in the convention of the sheet's yield it is near: compound - simple where the sheet has none)
    items = [(qc._bond_of(i, {}, quant[i]), qc._value_date(day, quant[i]), seeded["closes"][i][last] / 100.0,
              "compound" if quant[i].get("compound") is not None else "simple") for i in sorted(seeded["closes"]) if i in quant]
    nbr_close = kf.neighbours(items, nss0)["nbr"]
    _, _, hol, _ = svc._swaption_closes(seeded["mk"])
    node_months = [float(m) for m, _ in seeded["mk"].nodes]
    quotes = tuple((m, seeded["ois"][m][last] / 100.0) for m in sorted(seeded["ois"]))
    spot, curve = sw.day_curve(serial(day), quotes, node_months, hol)
    cv = svc.et.call(lambda: svc._try_curves(book, svc._calc(u, book)))
    for isin in (FIXED, BILL, LONG):
        r = rows[isin]
        assert r["priced"], (isin, r.get("why"))
        y_close = seeded["closes"][isin][last] / 100.0                         # (the sheet's compound yield: read as compound)
        mat = dt.date.fromisoformat(r["maturity"])
        ois_close = kf.zero_rate(curve, spot, serial(mat))
        b = r["bases"]
        assert b["nbr"]["day"] == last and b["nbr"]["close"] == pytest.approx(nbr_close[isin] * 100, abs=1e-9)
        assert b["nbr"]["spread"] == pytest.approx((y_close - nbr_close[isin]) * 1e4, abs=1e-7)
        assert b["ois"]["close"] == pytest.approx(ois_close * 100, abs=1e-9)
        assert b["ois"]["spread"] == pytest.approx((y_close - ois_close) * 1e4, abs=1e-7)
        # the bases now: OIS the workbook's Bootstrap at the maturity from the OIS spot
        assert b["ois"]["now"] == pytest.approx(kf.zero_rate(cv["boot"], seeded["mk"].ois_spot, serial(mat)) * 100, abs=1e-9)
        # fair = Σ weight × (base now + spread at the last close), the weights the bucket's
        want = {"3y": {"nbr": 1.0}, "1y": {"ois": 0.75, "nbr": 0.25}, "5y+": {"nbr": 0.75, "ois": 0.25}}[r["bucket"]]
        assert {k: v["used"] for k, v in b.items() if v["used"]} == want
        fair = sum(w * (b[k]["now"] / 100 + b[k]["spread"] / 1e4) for k, w in want.items())
        assert r["fair"]["yield"] == pytest.approx(fair * 100, abs=1e-9)
        # the quote and the levels around it: a higher yield is cheap - Al above fair, Sat below; prices the other way
        q, lv, s = r["quote"], r["levels"], r["sigma"]
        assert q["width"] == 10.0 and q["bid"]["yield"] - q["ask"]["yield"] == pytest.approx(0.10, abs=1e-9)
        assert q["bid"]["clean"] < r["fair"]["clean"] < q["ask"]["clean"]
        assert lv["buy"]["yield"] == pytest.approx(r["fair"]["yield"] + 2 * s["sigma"] / 100, abs=1e-9)
        assert lv["sell"]["yield"] == pytest.approx(r["fair"]["yield"] - 2 * s["sigma"] / 100, abs=1e-9)
        assert lv["buy"]["clean"] < r["fair"]["clean"] < lv["sell"]["clean"]
        assert s["n"] == 60 and s["sigma"] == max(s["floor"], s["sd"]) and s["floor"] == kf.SIGMA_FLOOR[r["bucket"]]
        assert r["backtest"]["n"] >= 0 and r["value_date"] and "adil" in r["line"] and r["line"].startswith("Komşu eğri")
    # prices as DİBS RV works them out (its own cash flows, days and accrued at its value date): at the screen's own
    # compound yield, the sheet's clean price in use and its simple yield
    lines = {x["isin"]: x for x in got["lines"]}
    for isin in (FIXED, BILL, LONG):
        line = lines[isin]
        p = svc.kagitfiyat._pricer(line, qc._bond_of(isin, {}, quant[isin]), seeded["today"])
        assert p.clean(line["compound"]) == pytest.approx(cell(svc, "DİBS RV!O%d" % line["row"]), abs=1e-9), isin
        assert p.simple(line["compound"]) == pytest.approx(line["simple"], abs=1e-12), isin
        assert p.yield_of(cell(svc, "DİBS RV!O%d" % line["row"])) == pytest.approx(line["compound"], abs=1e-12), isin
    bill = rows[BILL]
    days = cell(svc, "DİBS RV!DR%d" % lines[BILL]["row"])
    assert bill["fair"]["clean"] == pytest.approx(100.0 / (1 + bill["fair"]["yield"] / 100) ** (days / 365.0), abs=1e-9)
    assert bill["value_date"] == "2026-11-03" and rows[FIXED]["value_date"] == "2026-11-04"          # (ISL0 / ISL1, DİBS RV!P)


def test_todays_close_does_not_count_and_the_closes_part_is_kept(svc, seeded, monkeypatch):
    u = svc.login("Kâğıt Önbellek")["user"]
    before = rows_of(svc, u)
    panel = svc.kagitfiyat._panel
    # a page asked again: the same closes' part (nothing built)
    built = []
    real = kf.neighbours
    monkeypatch.setattr(kf, "neighbours", lambda *a, **k: built.append(1) or real(*a, **k))
    again = rows_of(svc, u)
    assert svc.kagitfiyat._panel is panel and built == []
    assert again[FIXED]["fair"] == before[FIXED]["fair"]
    # today's close moves: the history's revision moves, nothing of the last close's - each day's curves kept
    dd = seeded["bonds"][FIXED][0]
    svc.store.hist_upsert(dd.id, [(seeded["today"].isoformat(), seeded["bonds"][FIXED][1] + 0.6)])
    svc.history.rev += 1
    after = rows_of(svc, u)
    assert svc.kagitfiyat._panel is not panel and built == []                  # (built again of the days kept: no curve)
    assert after[FIXED]["bases"]["nbr"]["spread"] == before[FIXED]["bases"]["nbr"]["spread"]
    assert after[FIXED]["fair"]["yield"] == before[FIXED]["fair"]["yield"]


def test_floaters_and_cpi_linkers_are_not_priced_and_say_why(svc, seeded):
    u = svc.login("Kâğıt Tür")["user"]
    d = svc.kagit_fiyat(u)
    rows = {r["isin"]: r for r in d["rows"]}
    t = rows[TLREF]
    assert t["kind"] == "T" and not t["priced"] and "TLREF'e endeksli" in t["why"] and "fair" not in t
    assert kf.NOT_PRICED["E"].startswith("TÜFE'ye endeksli") and kf.NOT_PRICED["F"].startswith("FRN")
    # kind by kind (bills first), by maturity - every row keyed by its ISIN
    kinds = [r["kind"] for r in d["rows"]]
    assert kinds == sorted(kinds, key=lambda k: [x for x, _ in kf.KINDS].index(k))
    mats = [r["maturity"] for r in d["rows"] if r["kind"] == "S"]
    assert mats == sorted(mats) and len({r["isin"] for r in d["rows"]}) == len(d["rows"])
    # a bond with no price on the sheet still has a fair: its neighbours' curve now plus its spread at the last close
    no_price = rows["TRT081128T15"]
    assert no_price["priced"] and "yield" not in no_price and "z" not in no_price


def test_one_bond_for_the_card_and_a_reason_for_another(svc, seeded):
    u = svc.login("Kâğıt Kart")["user"]
    one = svc.kagit_fiyat(u, {"isin": "trt150328t24"})
    assert [r["isin"] for r in one["rows"]] == [FIXED] and one["rows"][0]["priced"]
    assert [r["isin"] for r in one["curve_rows"]] == [FIXED]                    # (and its curve price: the card's line)
    with pytest.raises(ServiceError) as err:
        svc.kagit_fiyat(u, {"isin": "TRT010199T11"})
    assert err.value.status == 400 and "masanın listesinde yok: TRT010199T11" in str(err.value)
    # a bond of the desk's list off the trading list: no old row, its curve row (the card's "Eğri fiyatı")
    off = svc.kagit_fiyat(u, {"isin": OFF})
    assert off["rows"] == [] and [r["isin"] for r in off["curve_rows"]] == [OFF] and off["curve_rows"][0]["price"]["label"] == kf.EGRI
    # (its peers the whole list's, as on the main table: the same price)
    assert off["curve_rows"][0]["price"] == next(r for r in svc.kagit_fiyat(u)["curve_rows"] if r["isin"] == OFF)["price"]
    # a TLREF floater of the catalog off the trading list: no curve price, why
    fl = svc.kagit_fiyat(u, {"isin": "TRT130127T11"})
    assert fl["rows"] == [] and fl["curve_rows"] == [] and "nominal eğriye göre fiyatlanmaz" in fl["why"]


def test_without_a_market_the_curve_plus_the_last_known_spread(svc, seeded):
    """With the made-up history: a bond with no market price - the trading list's one the sheet has no price of, and a bond
    off the list whose series the history kept (a bond once on the list) - is priced at its bucket's base now + its
    spread to that base at its most recent point ("eğri + son fark (<source> <day>, <age>)": the desk's history found the
    last spread the best predictor): the history's last close - the trading list's as Kâğıt Fiyatlama's closes measure
    it, the other's on that day's curve and OIS - or, newer or the same day, its last trade (DİBS RV's: the same day a
    trade before a close, said); the fair of its details from the same point.  A bond with a market keeps it, its curve
    price for the upload from its most recent point - today's trade, on the curve now -; its fair from its point before
    today.  A bond with no point at all: by its kind."""
    from tto.fiyatyukleme import date_said
    u = svc.login("Eğri Son Fark")["user"]
    last = seeded["days"][-1]
    k = svc.kagitfiyat
    svc.kagit_fiyat(u)                                   # (the made-up history's curves built and kept, day by day)
    b = qc._bond_of(OFF2, {}, None)
    vd = qc._value_date(dt.date.fromisoformat(last), {"source": "ISL1"})
    curve_then = kf.yield_on(b, k._days[last][1]["nss"], vd, "compound", 0.35)
    # its series as DİBS RV named it ("<ISIN> @ISL1 ISIN"), 30 bp over that day's curve (read as the trading list's fixed
    # coupon bonds' closes are: compound)
    series = "%s @ISL1 ISIN|YLD_YTM_MID" % OFF2
    svc.store.hist_upsert(series, [(seeded["days"][-2], 40.0), (last, (curve_then + 0.0030) * 100.0)])
    svc.history.rev += 1
    try:
        d = svc.kagit_fiyat(u)
        rows = {r["isin"]: r for r in d["curve_rows"]}
        old = {r["isin"]: r for r in d["rows"]}
        got, panel, now = live_fit(svc, u)
        o = rows[OFF2]
        assert o["price"]["label"] == "eğri + son fark (kapanış %s.%s, 1 iş günü önce)" % (last[8:10], last[5:7])
        assert o["price"]["kind"] == "spread" and o["price"]["src"] == "close" and not o["listed"]
        # (≤ 1Y: its spread to that day's base - 75 % that day's OIS zero rate at its maturity, Motor's bootstrap of that day's
        # closes, + 25 % the curve -, on today's base)
        spot, oc = k._days[last][1]["ois_curve"]
        z_then = kf.zero_rate(oc, spot, serial(b.maturity))
        want = 0.75 * (curve_then + 0.0030 - z_then) + 0.25 * 0.0030
        assert o["bucket"] == "1y" and o["base"]["text"] == "OIS %75 + eğri %25" and o["price"]["tag"] == "son fark, kapanış %s.%s" % (last[8:10], last[5:7])
        assert o["curve"]["base"] == "eğri" and o["curve"]["yield"] == o["curve"]["ns"]                # (Eğri: the curve)
        assert o["price"]["spread"] == pytest.approx(want * 1e4, abs=1e-6) and o["price"]["day"] == last
        assert o["price"]["yield"] == pytest.approx(o["base"]["yield"] + want * 100.0, abs=1e-9)
        assert "+ son fark %s bp (kapanış" % kf._bp(want * 1e4) in o["price"]["how"] and "o günün kapanış eğrisine göre" in o["price"]["how"]
        # the trading list's bond with no price: its last close and DİBS RV's last trade the same day - the trade, said; its
        # yield at its value date against that day's neighbours' curve (the bond left out, as its closes are measured)
        n = rows[NO_PRICE]
        line = next(x for x in got["lines"] if x["isin"] == NO_PRICE)
        nb = qc._bond_of(NO_PRICE, {}, next(q for q in got["quant"] if q["isin"] == NO_PRICE))
        assert date_said(line["last_day"]).isoformat() == last == panel["stats"][NO_PRICE]["last"]["day"]
        y_t = kf.trade_yield(nb, "S", line["last"], qc._value_date(dt.date.fromisoformat(last), {"source": "ISL1"}))[0]
        assert n["market"] is None and n["price"]["kind"] == "spread" and n["price"]["src"] == "trade" and n["price"]["day"] == last
        assert n["price"]["yield"] == pytest.approx((now["nbr"][NO_PRICE] + y_t - k._days[last][1]["nbr"][NO_PRICE]) * 100.0, abs=1e-9)
        assert n["price"]["label"] == "eğri + son fark (son işlem %s.%s, 1 iş günü önce)" % (last[8:10], last[5:7])
        assert "aynı gün kapanış da var, son işlem seçildi" in n["price"]["how"] and "DİBS RV 93,200" in n["price"]["how"]
        # its fair (the details) from the same point: the one function
        assert old[NO_PRICE]["fair"]["yield"] == pytest.approx(n["price"]["yield"], abs=1e-9)
        assert old[NO_PRICE]["point"]["src"] == "trade" and "dünkü son işlemdeki fark" in old[NO_PRICE]["line"]
        # with a market: the market's; its curve price for the upload from its most recent point - today's trade, on the
        # curve now (its yield itself) -; its fair from its point before today (its last close, as before)
        f, fline = rows[FIXED], next(x for x in got["lines"] if x["isin"] == FIXED)
        fb = qc._bond_of(FIXED, {}, next(q for q in got["quant"] if q["isin"] == FIXED))
        y_f = kf.trade_yield(fb, "S", fline["last"], dt.date(2026, 11, 4))[0]
        assert f["price"]["label"] == kf.PIYASA and f["alt"]["label"] == "eğri + son fark (son işlem 03.11, bugün)"
        assert f["alt"]["yield"] == pytest.approx(y_f * 100.0, abs=1e-9) and "şimdiki eğriye göre (bugünkü nokta)" in f["alt"]["how"]
        assert old[FIXED]["fair"]["yield"] == pytest.approx(f["curve"]["yield"] + panel["stats"][FIXED]["last"]["spread"][kf.NBR] * 100.0, abs=1e-9)
        assert old[FIXED]["point"]["src"] == "close"
        # a ≤ 1Y bond of the trading list: its fair from its last spreads to each base by the bucket's weights; its curve
        # price today's trade (a bill's price at its value date, the same day)
        bl, st = rows[BILL], panel["stats"][BILL]["last"]["spread"]
        assert old[BILL]["fair"]["yield"] == pytest.approx(
            0.75 * (bl["curve"]["ois"] + st[kf.OIS] * 100.0) + 0.25 * (bl["curve"]["ns"] + st[kf.NBR] * 100.0), abs=1e-9)
        bline = next(x for x in got["lines"] if x["isin"] == BILL)
        bb = qc._bond_of(BILL, {}, next(q for q in got["quant"] if q["isin"] == BILL))
        assert bl["alt"]["src"] == "trade" and bl["alt"]["yield"] == pytest.approx(kf.trade_yield(bb, "B", bline["last"], dt.date(2026, 11, 3))[0] * 100.0, abs=1e-9)
        # no point at all: a fixed coupon bond the curve alone, a zero coupon bond its peers'
        assert rows[OFF]["price"]["label"] == kf.EGRI and rows[ZERO]["price"]["label"] == kf.EGRI_AKRAN and d["counts"]["spread"] >= 2
        # the own last spread's typical error: that rule on the market-priced bonds of the bucket and kind, each from its
        # point before today (here its last close: its fair) against today's market
        sp = [abs(old[c]["fair"]["yield"] - r["market"]["yield"]) * 100.0 for c, r in rows.items()
              if r["market"] is not None and r["base"] is not None and r["bucket"] == "3y" and r["kind"] == "S"]
        assert len(sp) >= 2 and n["price"]["err"] == {"bp": pytest.approx(statistics.median(sp), abs=1e-6), "n": len(sp)}
        assert "tipik hata ±%d bp" % round(statistics.median(sp)) in n["price"]["how"]
        # the upload's quotes: the same (never the market), with their short names
        q = k.curve_quotes(u, [OFF2, FIXED, OFF, "TRT130127T11"])
        assert set(q) == {OFF2, FIXED, OFF} and q[OFF2]["yield"] == o["price"]["yield"] and q[FIXED]["yield"] == f["alt"]["yield"]
        assert q[OFF]["label"] == kf.EGRI and q[OFF2]["simple"] == pytest.approx(o["price"]["simple"], abs=1e-12)
        assert (q[OFF]["tag"], q[OFF2]["tag"], q[FIXED]["tag"]) == (None, "son fark, kapanış %s.%s" % (last[8:10], last[5:7]), "son fark, son işlem 03.11")
        assert q[OFF]["err"] == rows[OFF]["price"]["err"]
    finally:
        svc.store.hist_delete(series)
        svc.history.rev += 1


def _put(svc, key, isin, value):
    book = dict(svc.store.get(key) or {})
    book[isin] = value
    svc.store.put(key, book)


def test_the_last_known_spread_from_every_source(svc, seeded):
    """(the desk, 20.11.2026: "Fiyatı olmayanı eğriden fiyatlarken eğriye göre önceden ne kadar pahalı ucuz olduğuna da
    bakmamız gerekli") A bond's last known spread from the most recent of its points, none a new Bloomberg request: an
    auction Kâğıt Fiyat Yükleme kept - today's measured on the curve now (said), an earlier one on that day's close curve -,
    a last trade (the upload's Bloomberg answer kept), a daily close kept; the same day a trade before an auction (said);
    an older point loses to a newer one.  The price: the bucket's base now + that spread, labelled with the source, the
    day and its age; the upload's fallback says the same."""
    from tto import fiyatyukleme as fy
    u = svc.login("Son Fark Kaynak")["user"]
    last = seeded["days"][-1]
    k = svc.kagitfiyat
    svc.kagit_fiyat(u)
    keys = (fy.KEY_AUCTIONS, fy.KEY_TRADES, kf.KEY_CLOSES)
    saved = {key: svc.store.get(key) for key in keys}
    TIE = "TRT110827T16"
    dd = "%s.%s" % (last[8:10], last[5:7])
    try:
        auction = {"label": "x", "tn": 1, "by": "test", "at": "x"}
        _put(svc, fy.KEY_AUCTIONS, OFF, [dict(auction, day="2026-11-03", value=99.0, value_date="2026-11-04")])     # (today's)
        _put(svc, fy.KEY_AUCTIONS, OFF2, [dict(auction, day=last, value=99.5, value_date="2026-11-03")])
        _put(svc, fy.KEY_AUCTIONS, ZERO, [dict(auction, day=seeded["days"][-5], value=33.0, value_date=seeded["days"][-5])])
        _put(svc, fy.KEY_AUCTIONS, TIE, [dict(auction, day=last, value=96.0, value_date="2026-11-03")])
        _put(svc, fy.KEY_TRADES, TIE, {"day": last, "price": 95.0, "source": "ISL1", "at": "x"})
        svc.store.put(kf.KEY_CLOSES, {"days": [last], "bonds": {ZERO: [[last, 97.0, 0.36, last, "Tüm Kâğıtlar bid / ask ortası"]]}})
        d = svc.kagit_fiyat(u)
        rows = {r["isin"]: r for r in d["curve_rows"]}
        then = k._days[last][1]
        spot, oc = then["ois_curve"]

        def on_base(r, y, bond, vd):
            """base now + (y − that day's base), by the bucket's weights (≤ 1Y: 75 % OIS + 25 % the curve)."""
            ns_then = kf.yield_on(bond, then["nss"], vd, "compound", y)
            z_then = kf.zero_rate(oc, spot, serial(bond.maturity))
            return 0.75 * (r["curve"]["ois"] / 100.0 + y - z_then) + 0.25 * (r["curve"]["ns"] / 100.0 + y - ns_then)

        # today's auction: on the curve now - the price is the auction's own yield
        a = rows[OFF]
        y_a = kf.auction_yield(qc._bond_of(OFF, {}, None), "S", 99.0, dt.date(2026, 11, 4))
        assert a["price"]["label"] == "eğri + son fark (ihale 03.11, bugün)" and a["price"]["src"] == "auction" and a["price"]["age"] == 0
        assert a["price"]["yield"] == pytest.approx(y_a * 100.0, abs=1e-9) and "şimdiki eğriye göre (bugünkü nokta)" in a["price"]["how"]
        assert "ihale x.t1 99,000 (valör 04.11)" in a["price"]["how"]
        # an earlier day's auction: on that day's close curve and OIS
        b2 = rows[OFF2]
        bond2 = qc._bond_of(OFF2, {}, None)
        y2 = kf.auction_yield(bond2, "S", 99.5, dt.date(2026, 11, 3))
        assert b2["price"]["label"] == "eğri + son fark (ihale %s, 1 iş günü önce)" % dd
        assert b2["price"]["yield"] == pytest.approx(on_base(b2, y2, bond2, dt.date(2026, 11, 3)) * 100.0, abs=1e-9)
        # a daily close kept, newer than its auction: the close
        z = rows[ZERO]
        zb = qc._bond_of(ZERO, {}, None)
        assert z["price"]["label"] == "eğri + son fark (kapanış %s, 1 iş günü önce)" % dd and z["price"]["src"] == "kept"
        assert z["price"]["yield"] == pytest.approx(on_base(z, 0.36, zb, dt.date.fromisoformat(last)) * 100.0, abs=1e-9)
        # a trade (the upload's Bloomberg answer kept) and an auction the same day: the trade, said
        t = rows[TIE]
        tb = qc._bond_of(TIE, {}, None)
        y_t = kf.trade_yield(tb, "S", 95.0, dt.date(2026, 11, 3))[0]
        assert t["price"]["label"] == "eğri + son fark (son işlem %s, 1 iş günü önce)" % dd and "Bloomberg 95,000" in t["price"]["how"]
        assert t["price"]["yield"] == pytest.approx(on_base(t, y_t, tb, dt.date(2026, 11, 3)) * 100.0, abs=1e-9)
        assert "aynı gün ihale da var, son işlem seçildi" in t["price"]["how"]
        assert d["counts"]["spread"] >= 5
        # the upload's fallback: the same price, its mark naming the point
        svc.fiyat_yukleme(u, "ekle", {"isins": "%s %s" % (OFF, TIE)})
        res = svc.fiyat_yukleme(u, "hesapla", {"mode": "ihale", "text": "10/02/2027.t1   99.500\n"})
        up = {r["isin"]: r for r in res["rows"]}
        assert up[OFF]["curve"]["mark"] == "eğri fiyatı (son fark, ihale 03.11)" and up[OFF]["curve"]["yield"] == pytest.approx(a["price"]["yield"], abs=1e-9)
        assert up[TIE]["curve"]["mark"] == "eğri fiyatı (son fark, son işlem %s)" % dd and up[TIE]["how"].startswith("eğri fiyatı (son fark, son işlem")
    finally:
        for key, v in saved.items():
            svc.store.put(key, v if v is not None else {})


def test_the_daily_close_is_kept_once_a_day_without_bloomberg(svc, monkeypatch):
    """Every bond of the desk's list with a price today keeps its daily close - Piyasa's price (DİBS RV's bid / ask
    middle for the trading list, Tüm Kâğıtlar's for the rest), its yield and value date - once a day after 17:35 on a
    business day, or when the workbook's day turns with the day before not kept (its prices then are still its last);
    nothing is asked of Bloomberg."""
    k = svc.kagitfiyat
    saved = svc.store.get(kf.KEY_CLOSES)
    asked = []
    for name in ("reference", "bdh", "bdp", "history"):
        if hasattr(svc.provider, name):
            monkeypatch.setattr(svc.provider, name, lambda *a, _n=name, **kw: asked.append(_n))
    seen = k._rec_seen
    try:
        svc.store.put(kf.KEY_CLOSES, {})
        k._rec_seen = None
        got = svc.et.call(k._read, None)
        assert got["today"] == dt.date(2026, 11, 3)
        assert k.record_closes(dt.datetime(2026, 11, 3, 17, 0), got) is None                # (before the close: nothing)
        assert k.record_closes(dt.datetime(2026, 11, 3, 17, 40), got) == "2026-11-03"
        assert k.record_closes(dt.datetime(2026, 11, 3, 18, 30), got) is None               # (once a day)
        kept = svc.store.get(kf.KEY_CLOSES)
        rows = {r["isin"]: r for r in svc.kagit_fiyat(svc.login("Kapanış Kaydı")["user"])["curve_rows"]}
        assert set(kept["bonds"]) == {c for c, r in rows.items() if r["market"] is not None} and kept["days"] == ["2026-11-03"]
        day, clean, y, vd, how = kept["bonds"][FIXED][-1]
        f = rows[FIXED]
        assert (day, clean, vd, how) == ("2026-11-03", f["market"]["clean"], f["value_date"], "DİBS RV bid / ask ortası")
        assert y * 100.0 == pytest.approx(f["market"]["yield"], abs=1e-9)
        # (a weekend: none)
        assert k.record_closes(dt.datetime(2026, 11, 7, 18, 0), dict(got, today=dt.date(2026, 11, 7))) is None
        # the day turns with the day before not kept: today's prices kept as its close, at its value date
        svc.store.put(kf.KEY_CLOSES, {})
        k._rec_seen = dt.date(2026, 11, 2)
        assert k.record_closes(dt.datetime(2026, 11, 3, 9, 0), got) == "2026-11-02"
        b = svc.store.get(kf.KEY_CLOSES)["bonds"][FIXED][-1]
        assert b[0] == "2026-11-02" and b[1] == f["market"]["clean"] and b[3] == "2026-11-03"
        assert asked == []
    finally:
        k._rec_seen = seen
        svc.store.put(kf.KEY_CLOSES, saved if saved is not None else {})


def test_the_widths_are_the_administrators(svc, seeded):
    u = svc.login("Kâğıt Trader")["user"]
    a = svc.login("Kâğıt Yönetici")["user"]
    svc.store.update_account(a, role="admin")
    with pytest.raises(ServiceError) as err:
        svc.kagit_fiyat_widths(u, {"widths": {"3y": 12}})
    assert err.value.status == 403
    assert not svc.kagit_fiyat(u)["admin"] and svc.kagit_fiyat(a)["admin"]
    for bad, says in (({"widths": {"7y": 5}}, "bilinmeyen vade kovası"), ({"widths": {"3y": "x"}}, "bir sayı olmalı"),
                      ({"widths": {"3y": -1}}, "0 – 200 bp"), ({}, "anlaşılamadı")):
        with pytest.raises(ServiceError) as err:
            svc.kagit_fiyat_widths(a, bad)
        assert err.value.status == 400 and says in str(err.value)
    got = svc.kagit_fiyat_widths(a, {"widths": {"3y": "12,5"}})
    try:
        assert got["widths"]["3y"] == 12.5 and got["widths"]["by"] == a and "1–3Y 10,0 → 12,5 bp" in got["log"][0]["text"]
        r = rows_of(svc, u)[FIXED]
        assert r["quote"]["width"] == 12.5 and r["quote"]["bid"]["yield"] - r["quote"]["ask"]["yield"] == pytest.approx(0.125, abs=1e-9)
        assert rows_of(svc, u)[LONG]["quote"]["width"] == 10.0
    finally:
        svc.kagit_fiyat_widths(a, {"widths": {"3y": 10}})


def test_the_page_is_first_in_the_tahvil_menu(svc):
    nav = svc.nav(svc.login("Kâğıt Menü")["user"])
    tahvil = [p for p in nav if p["group"] == "Tahvil"]
    assert tahvil[0]["id"] == "kagit-fiyat" and tahvil[0]["title"] == "Kâğıt Fiyatlama" and tahvil[0]["custom"]
    assert [p["id"] for p in tahvil][1:4] == ["fiyat-yukleme", "kagitlar", "dibslive"]            # (Kâğıt Fiyat Yükleme next)
    assert kf.menu([{"id": "usd", "title": "USD", "group": "USD"}]) == [{"id": "usd", "title": "USD", "group": "USD"}]


def test_the_projection_and_the_horizon_switch(svc, seeded):
    """Öngörülen of a bill (≤ 1Y), a 1–3Y and a 5Y+ bond over the made-up history: at each horizon its bucket's model of
    the measured table (M4 at 1 ay for ≤ 1Y and 1–3Y, else M2 "eğri ve fark değişmezse"), worked out again here from its
    parts - DİBS RV's yield now, the neighbours' curve now and its roll-down to the horizon's value date, the window's AR(1)
    and β of the closes, the OIS Bootstrap's forwards; the three horizons each their own (the switch's), 1 ay the
    default."""
    u = svc.login("Kâğıt Öngörü")["user"]
    d = svc.kagit_fiyat(u)
    pj = d["projection"]
    today, mk = seeded["today"], seeded["mk"]
    _, _, hol, _ = svc._swaption_closes(mk)
    hdays = {h: kf.workday(today, h, hol) for h in (5, 10, 20)}
    assert pj["default"] == 20 and [(x["h"], x["text"], x["day"]) for x in pj["horizons"]] == \
        [(5, "1 hafta", hdays[5].isoformat()), (10, "2 hafta", hdays[10].isoformat()), (20, "1 ay", hdays[20].isoformat())]
    assert pj["table"]["3y"][20]["model"] == kf.M4 and pj["models"][kf.M2] == "eğri ve fark değişmezse"
    rows = {r["isin"]: r for r in d["rows"]}
    kfo = svc.kagitfiyat
    got = svc.et.call(kfo._read, u)
    lines = {x["isin"]: x for x in got["lines"]}
    quant = {x["isin"]: x for x in got["quant"]}
    panel = kfo._panel[1]
    now = kfo.now_fit(got, panel, kfo.horizon_days(got))
    pos = {x: i for i, x in enumerate(seeded["days"])}
    book = svc.books["tto"]
    boot = svc.et.call(lambda: svc._try_curves(book, svc._calc(u, book)))["boot"]
    seen = {}
    for isin in (BILL, FIXED, LONG):
        r, line = rows[isin], lines[isin]
        bond = qc._bond_of(isin, {}, quant[isin])
        p = r["proj"]
        y0, nbr, roll = line["compound"], now["nbr"][isin], now["roll"][isin]
        assert p["from"] == "ekran" and p["y"] == pytest.approx(y0 * 100, abs=1e-12) and p["nbr"] == pytest.approx(nbr * 100, abs=1e-12)
        st = panel["stats"][isin]
        recs = panel["recs"][isin]
        for w in kf.AR_WINDOWS:                                               # (the windows: of the closes before today)
            assert st["windows"][w] == kf.fit_window(recs, pos, len(recs) - 1, w)
        for h in (5, 10, 20):
            e = p["h"][str(h)]
            rec = kf.PROJECTION[r["bucket"]][h]
            assert e["model"] == e["rule"] == rec["model"] and e["window"] == rec["window"] and e["why"] is None, (isin, h, e.get("why"))
            assert e["day"] == hdays[h].isoformat() and e["value_date"] == qc._value_date(hdays[h], quant[isin]).isoformat()
            w = st["windows"].get(rec["window"]) or {}
            move = kf.ois_move(boot, mk.ois_spot, serial(bond.maturity), (hdays[h] - today).days)
            want = kf.project(rec["model"], h, y0, nbr, roll[h], w.get("ar"), w.get("beta"), move)
            assert e["yield"] == pytest.approx(want * 100, abs=1e-9) and e["bp"] == pytest.approx((want - y0) * 1e4, abs=1e-7)
            assert e["record"] == kf.record_text(rec, rec["model"]) and e["line"].startswith(e["text"] + " (valör ")
            if rec["model"] == kf.M2:
                assert e["yield"] == pytest.approx((roll[h] + y0 - nbr) * 100, abs=1e-9) and "fark" in e["line"] and not e["beat"]
            else:
                assert e["beat"] and e["ois"]["bp"] == pytest.approx(w["beta"] * move * 1e4, abs=1e-9) and "β" in e["line"]
            seen[(isin, h)] = e
        assert r["bucket"] == {BILL: "1y", FIXED: "3y", LONG: "5y+"}[isin]
    # the switch: each horizon is its own - a later value date, another yield and price
    for isin in (BILL, FIXED, LONG):
        e5, e10, e20 = (seen[(isin, h)] for h in (5, 10, 20))
        assert e5["value_date"] < e10["value_date"] < e20["value_date"]
        assert len({round(e["yield"], 9) for e in (e5, e10, e20)}) == 3 and len({round(e["clean"], 9) for e in (e5, e10, e20)}) == 3
    assert seen[(FIXED, 20)]["model"] == kf.M4 and seen[(FIXED, 5)]["model"] == kf.M2


def test_the_projected_price_at_the_horizons_value_date(svc, seeded):
    """The projected yield's clean price on the day the horizon settles - a bill from its days then, a coupon bond from its
    cash flows then less the accrued interest then (BIST's rules: as DİBS RV prices today, the same price at today's value
    date) -, its simple yield then, and the K/Z of 1 mn nominal: the price at the projected yield less the price at today's
    yield, both on that date."""
    u = svc.login("Kâğıt Ufuk Fiyatı")["user"]
    rows = rows_of(svc, u)
    kfo = svc.kagitfiyat
    got = svc.et.call(kfo._read, u)
    lines = {x["isin"]: x for x in got["lines"]}
    quant = {x["isin"]: x for x in got["quant"]}
    for isin in (BILL, FIXED, LONG):
        line = lines[isin]
        bond = qc._bond_of(isin, {}, quant[isin])
        y0 = line["compound"]
        # (the bond's own cash flows price as DİBS RV's at its value date)
        now = kfo.pricer_at(line, bond, line["value"])
        assert now.clean(y0) == pytest.approx(cell(svc, "DİBS RV!O%d" % line["row"]), abs=1e-6), isin
        for h in (5, 10, 20):
            e = rows[isin]["proj"]["h"][str(h)]
            vd = dt.date.fromisoformat(e["value_date"])
            y = e["yield"] / 100.0
            if bond.kind == "bill":
                days = (bond.maturity - vd).days
                assert e["clean"] == pytest.approx(100.0 / (1 + y) ** (days / 365.0), abs=1e-9)
                assert e["simple"] == pytest.approx(((1 + y) ** (days / 365.0) - 1) / (days / 365.0) * 100, abs=1e-9)
                c0 = 100.0 / (1 + y0) ** (days / 365.0)
            else:
                assert e["clean"] == pytest.approx(bond.price(y, vd, "compound")[0] - qc.accrued(bond, vd), abs=1e-9)
                assert e["simple"] == pytest.approx(2 * ((1 + y) ** 0.5 - 1) * 100, abs=1e-9)
                c0 = bond.price(y0, vd, "compound")[0] - qc.accrued(bond, vd)
            assert e["pnl"] == pytest.approx((e["clean"] - c0) * 1e4, abs=1e-6)
            assert (e["pnl"] > 0) == (e["bp"] < 0) or abs(e["bp"]) < 1e-9                # (a lower yield: a long earns)


def test_a_bond_that_cannot_have_its_model_now_shows_m2_and_why(svc, seeded, monkeypatch):
    """M4 needs the window's AR(1) and β: a bond whose closes cannot give them (here: too few) shows M2 in its place, says
    why, and M2's own record."""
    u = svc.login("Kâğıt Kısa Geçmiş")["user"]
    real = kf.fit_window
    monkeypatch.setattr(kf, "fit_window", lambda recs, pos, end, w: dict(real(recs, pos, end, w), ar=None))
    svc.history.rev += 1                                                      # (the closes' part built again)
    try:
        e = rows_of(svc, u)[FIXED]["proj"]["h"]["20"]
    finally:
        monkeypatch.undo()
        svc.history.rev += 1
    assert e["rule"] == kf.M4 and e["model"] == kf.M2 and e["window"] == 0 and e["beat"]
    assert e["why"].startswith("M4 kurulamadı: son 60 kapanışta farkın ortalamaya dönüşü ölçülemedi")
    assert e["record"] == "geri test (eğri ve fark değişmezse): RMSE 166 bp (değişmez 164 bp), yön isabeti %50 (221)"


def test_ois_and_fx_swap_are_the_values_dibs_trading_shows(svc, seeded):
    """"OIS ve FX swap curve'üne göre fiyatları da ayrıca gösterilsin": each bond's fair yield and clean price on DİBS RV's
    fitted OIS ASW curve and on DİBS ASW's FX swap one - rvfair's, exactly the cells of DİBS Trading's "OIS'e göre" and
    "FX swap'a göre" groups (their text, and their reason where there is none)."""
    from tto import rvfair
    u = svc.login("Kâğıt ASW")["user"]
    rows = rows_of(svc, u)
    d = next(p for p in svc.view(u, "dibslive")["panels"] if p["id"] == "L0")["data"]
    book = svc.books["tto"]
    si = book.model.sheet_index["DİBS RV"]

    def fair_of(r):
        calc = svc._calc(u, book)
        fx = svc._fx_curve(u)
        return rvfair.fair(calc, si, r, rvfair.read_fits(calc, si, fx), fx)

    got = svc.et.call(svc.kagitfiyat._read, u)
    lines = {x["isin"]: x for x in got["lines"]}
    n = 0
    for isin in (BILL, FIXED, LONG, TLREF, "TRT081128T15"):
        line = next(row for row in d["rows"] if len(row) > 2 and row[2].get("t") == isin)
        at = {col: line[d["c"].index(col)] for col in ("Y", "Z", "AB", "AC")}
        f = svc.et.call(fair_of, lines[isin]["row"])
        for side, (yc, pc) in (("ois", ("Y", "Z")), ("fx", ("AB", "AC"))):
            a = rows[isin]["asw"][side]
            assert a["t"] == [at[yc]["t"], at[pc]["t"]], (isin, side)
            if at[yc]["t"] == "–":
                assert a["why"] == at[yc]["tip"] and "yield" not in f[side]
            else:
                assert a["yield"] == pytest.approx(f[side]["yield"] * 100, abs=1e-12) == pytest.approx(at[yc]["v"] * 100, abs=1e-12)
                assert a["price"] == pytest.approx(f[side]["price"], abs=1e-12) == pytest.approx(at[pc]["v"], abs=1e-12)
                assert a["tip"] == at[yc]["tip"] and a["soft"] == ("soft" in (at[yc].get("cls") or ""))
                n += 1
    assert n >= 5 and "TLREF'e endeksli" in rows[TLREF]["asw"]["ois"]["why"]


def test_the_main_tables_projection_and_asw_columns(svc, seeded):
    """(the desk, 20.11.2026, asked whether the projected prices should be visible columns again: "Göster") The main
    table's Öngörülen, OIS'e göre and FX swap'a göre: a bond of the trading list shows its details' values - in the same
    answer, its row's projection at every horizon and rvfair's fair values on the two ASW curves, DİBS Trading's -; a bond
    off the trading list "—", said why (no daily closes, no DİBS RV row)."""
    from tto import rvfair
    u = svc.login("Kâğıt Kolon")["user"]
    d = svc.kagit_fiyat(u)
    main = {r["isin"]: r for r in d["curve_rows"]}
    det = {r["isin"]: r for r in d["rows"]}
    # every row of the main table: its details' values in the answer, or why there are none
    assert all(("cols_why" in r) == (c not in det) for c, r in main.items()) and len(set(main) & set(det)) >= 15
    assert main[OFF]["cols_why"] == kf.COLS_WHY and "yalnız trading listesindeki" in kf.COLS_WHY and "günlük kapanış" in kf.COLS_WHY
    f = det[FIXED]
    assert "cols_why" not in main[FIXED] and sorted(f["proj"]["h"]) == ["10", "20", "5"]
    assert all(isinstance(f["proj"]["h"][h]["yield"], float) and isinstance(f["proj"]["h"][h]["clean"], float) for h in ("5", "10", "20"))
    # OIS'e / FX swap'a göre: rvfair's, as DİBS Trading shows them
    book = svc.books["tto"]
    si = book.model.sheet_index["DİBS RV"]
    line = next(x for x in svc.et.call(svc.kagitfiyat._read, u)["lines"] if x["isin"] == FIXED)

    def fair_of(r):
        calc = svc._calc(u, book)
        fx = svc._fx_curve(u)
        return rvfair.fair(calc, si, r, rvfair.read_fits(calc, si, fx), fx)

    fv = svc.et.call(fair_of, line["row"])
    assert "yield" in fv["ois"]
    for side in ("ois", "fx"):
        if "yield" in fv[side]:
            assert f["asw"][side]["yield"] == pytest.approx(fv[side]["yield"] * 100.0, abs=1e-12)
            assert f["asw"][side]["price"] == pytest.approx(fv[side]["price"], abs=1e-12)
    # the card's answer of a bond off the list: the same reason
    assert svc.kagit_fiyat(u, {"isin": OFF})["curve_rows"][0]["cols_why"] == kf.COLS_WHY


# ================================================================================================== over HTTP (last: the client stops the service)
def test_the_routes(svc, seeded):
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Kâğıt HTTP")
        got = c.get("/api/kagit-fiyat", headers=h)
        assert got.status_code == 200 and got.json()["ok"] and any(r["priced"] for r in got.json()["rows"])
        one = c.get("/api/kagit-fiyat", headers=h, params={"isin": BILL})
        assert one.status_code == 200 and [r["isin"] for r in one.json()["rows"]] == [BILL]
        # Öngörülen at the three horizons (the switch's, 1 ay first shown) and DİBS Trading's two ASW curves' fair values
        pj = one.json()["projection"]
        bill = one.json()["rows"][0]
        assert pj["default"] == 20 and [x["h"] for x in pj["horizons"]] == [5, 10, 20] and pj["table"]["1y"]["20"]["model"] == "M4"
        assert sorted(bill["proj"]["h"]) == ["10", "20", "5"] and bill["proj"]["h"]["20"]["model"] == "M4"
        assert set(bill["asw"]) == {"ois", "fx"} and all("yield" in bill["asw"][k] or bill["asw"][k]["why"] for k in ("ois", "fx"))
        bad = c.get("/api/kagit-fiyat", headers=h, params={"isin": "XYZ"})
        assert bad.status_code == 400 and "masanın listesinde yok" in bad.json()["error"]
        # the main table over HTTP: every fixed coupon bond, bill and zero coupon bond of the desk's list, a label each
        body = got.json()
        assert len(body["curve_rows"]) >= 29 and {(r.get("price") or {}).get("label") for r in body["curve_rows"]} >= {kf.PIYASA, kf.EGRI, kf.EGRI_AKRAN}
        assert body["others"] and sum(body["counts"].values()) == sum(1 for r in body["curve_rows"] if r.get("price"))
        off = c.get("/api/kagit-fiyat", headers=h, params={"isin": OFF}).json()
        assert off["curve_rows"][0]["isin"] == OFF and off["rows"] == []
        assert c.get("/api/kagit-fiyat", headers=ANON).status_code == 401
        assert c.post("/api/kagit-fiyat/genislik", headers=h, json={"widths": {"3y": 12}}).status_code == 403
        assert c.post("/api/kagit-fiyat/genislik", headers=ANON, json={"widths": {"3y": 12}}).status_code == 401
        adm = auth(svc, "Kâğıt HTTP Yönetici", admin=True)
        bad = c.post("/api/kagit-fiyat/genislik", headers=adm, json={"widths": {"3y": 999}})
        assert bad.status_code == 400 and "0 – 200 bp" in bad.json()["error"]
        for path in ("/static/js/pages/kagitfiyat.js", "/static/js/kagitblock.js"):
            assert c.get(path).status_code == 200, path
