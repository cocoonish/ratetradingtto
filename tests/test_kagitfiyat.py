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
    with pytest.raises(ServiceError) as err:
        svc.kagit_fiyat(u, {"isin": "TRT010199T11"})
    assert err.value.status == 400 and "trading listesinde değil: TRT010199T11" in str(err.value)


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
    assert [p["id"] for p in tahvil][1:3] == ["kagitlar", "dibslive"]
    assert kf.menu([{"id": "usd", "title": "USD", "group": "USD"}]) == [{"id": "usd", "title": "USD", "group": "USD"}]


# ================================================================================================== over HTTP (last: the client stops the service)
def test_the_routes(svc, seeded):
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Kâğıt HTTP")
        got = c.get("/api/kagit-fiyat", headers=h)
        assert got.status_code == 200 and got.json()["ok"] and any(r["priced"] for r in got.json()["rows"])
        one = c.get("/api/kagit-fiyat", headers=h, params={"isin": BILL})
        assert one.status_code == 200 and [r["isin"] for r in one.json()["rows"]] == [BILL]
        bad = c.get("/api/kagit-fiyat", headers=h, params={"isin": "XYZ"})
        assert bad.status_code == 400 and "trading listesinde değil" in bad.json()["error"]
        assert c.get("/api/kagit-fiyat", headers=ANON).status_code == 401
        assert c.post("/api/kagit-fiyat/genislik", headers=h, json={"widths": {"3y": 12}}).status_code == 403
        assert c.post("/api/kagit-fiyat/genislik", headers=ANON, json={"widths": {"3y": 12}}).status_code == 401
        adm = auth(svc, "Kâğıt HTTP Yönetici", admin=True)
        bad = c.post("/api/kagit-fiyat/genislik", headers=adm, json={"widths": {"3y": 999}})
        assert bad.status_code == 400 and "0 – 200 bp" in bad.json()["error"]
        for path in ("/static/js/pages/kagitfiyat.js", "/static/js/kagitblock.js"):
            assert c.get(path).status_code == 200, path
