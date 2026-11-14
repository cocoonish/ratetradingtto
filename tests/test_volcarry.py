"""Realized volatility of what is typed, and the carry of the sheet's flies measured against it."""
from __future__ import annotations

import datetime as dt
import math
import random
import statistics

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell
from tto.service import ServiceError
from tto.xl.model import parse_a1
from tto import blotter as bl
from tto import volcarry as vc
from tto.server import create_app

DAYS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03"]


def curve_of(**tenors):
    """tenor=[closes on DAYS; None = no close that day]"""
    return {t.upper(): {d: v for d, v in zip(DAYS, vals) if v is not None} for t, vals in tenors.items()}


MONTHS = {"6M": 6.0, "1Y": 12.0, "2Y": 24.0, "3Y": 36.0, "5Y": 60.0}


# ---------------------------------------------------------------------------------------------- what is typed
def test_what_is_typed():
    items = vc.parse_items("18m, 1y5y; 2y3y4y\n9x12, 5y x, 1y1y, abc , 18M,, 1v5y spread ,xccy 2y5y")
    assert [(i["raw"], i["ok"]) for i in items] == [("18m", True), ("1y5y", True), ("2y3y4y", True), ("9x12", True), ("5y x", True),
                                                    ("1y1y", True), ("abc", False), ("xccy 2y5y", True)]      # the same thing twice is one row
    assert [(i["product"], i["kind"], i["label"], i["unit"]) for i in items if i["ok"]] == [
        ("OIS", "outright", "18M", "pct"), ("OIS", "spread", "1Y–5Y", "bp"), ("OIS", "fly", "2Y–3Y–4Y", "bp"), ("OIS", "fra", "9x12", "pct"),
        ("XCCY", "outright", "5Y", "pct"), ("OIS", "fwd", "1Y1Y", "pct"), ("XCCY", "spread", "2Y–5Y", "bp")]
    assert "anlaşılamadı" in items[6]["error"] and vc.parse_items("") == [] and vc.parse_items(None) == []
    bond = vc.parse_items("trt150328t24, TRT150328T24 , 2y")                    # a bond by its ISIN
    assert [(i["product"], i["kind"], i["label"], i["key"]) for i in bond] == [("DIBS", "outright", "TRT150328T24", "DIBS:outright:TRT150328T24"),
                                                                                ("OIS", "outright", "2Y", "OIS:outright:2Y")]
    fly = vc.item_of("fly", ["1y", " 2Y", "3y "])
    assert (fly["label"], fly["key"], fly["unit"], fly["months"], fly["product"]) == ("1Y–2Y–3Y", "OIS:fly:1Y/2Y/3Y", "bp", [12, 24, 36], "OIS")
    assert vc.item_of("spread", ["1M", "2M"])["label"] == "1M–2M"


def test_the_level_of_an_instrument_through_time():
    curve = curve_of(**{"1y": [35.00, 35.10, 35.30, 35.20, 35.25, 35.40, 35.30], "2y": [35.50, 35.55, 35.80, 35.60, 35.70, 35.90, 35.85],
                        "3y": [35.20, 35.30, None, 35.40, 35.45, 35.50, None]})
    one = lambda text: vc.parse_items(text)[0]                               # noqa: E731
    days, levels, why = vc.series_of(one("1y"), curve, MONTHS)
    assert (days, levels, why) == (DAYS, [35.00, 35.10, 35.30, 35.20, 35.25, 35.40, 35.30], "")
    days, levels, _ = vc.series_of(one("1y2y"), curve, MONTHS)
    assert days == DAYS and levels == pytest.approx([50.0, 45.0, 50.0, 40.0, 45.0, 50.0, 55.0])              # long − short, bp
    # a day counts when every leg closed: the fly has no level on the two days the 3Y did not
    days, levels, _ = vc.series_of(one("1y2y3y"), curve, MONTHS)
    assert days == [DAYS[0], DAYS[1], DAYS[3], DAYS[4], DAYS[5]]
    assert levels == pytest.approx([(2 * 35.50 - 35.00 - 35.20) * 100, (2 * 35.55 - 35.10 - 35.30) * 100, (2 * 35.60 - 35.20 - 35.40) * 100,
                                    (2 * 35.70 - 35.25 - 35.45) * 100, (2 * 35.90 - 35.40 - 35.50) * 100])
    assert vc.series_of(one("1y5y"), curve, MONTHS) == ([], [], "geçmişi yok: 5Y")
    assert vc.series_of(one("4y"), curve, MONTHS)[2] == "geçmişi yok: 4Y"
    assert "3'ün katı" in vc.series_of(one("1x4"), curve, MONTHS)[2] and "kadar yok" in vc.series_of(one("3y3y"), curve, MONTHS)[2]


def test_realized_is_the_standard_deviation_of_the_daily_moves():
    rng = random.Random(11)
    levels = [35.0]
    for _ in range(140):
        levels.append(levels[-1] + rng.gauss(0, 0.08))
    moves = [(b - a) * 100 for a, b in zip(levels, levels[1:])]
    assert vc.changes_bp(levels, "pct") == pytest.approx(moves) and vc.changes_bp([10.0, 12.5, 11.0], "bp") == [2.5, -1.5]
    out = vc.realized(levels, "pct")
    assert set(out) == set(vc.WINDOWS) == {10, 20, 60, 120, 250}
    for n in (10, 20, 60, 120):
        assert out[n]["d"] == pytest.approx(statistics.stdev(moves[-n:]), rel=1e-12) and out[n] == {"d": out[n]["d"], "n": n, "full": True}
    assert out[250] == {"d": pytest.approx(statistics.stdev(moves)), "n": 140, "full": False}             # what there is, and said so
    assert vc.realized(levels[:5], "pct")[10] is None and vc.realized(levels[:6], "pct")[10]["n"] == 5      # five moves at least
    assert vc.realized([], "pct")[20] is None and vc.stdev([1.0]) is None and vc.stdev([1.0, 3.0]) == pytest.approx(math.sqrt(2))
    assert vc.realized([40.0, 45.0, 38.0, 41.0, 44.0, 39.0], "bp", (5,))[5]["d"] == pytest.approx(statistics.stdev([5, -7, 3, 3, -5]))
    roll = vc.rolling(levels, "pct", 20)
    assert len(roll) == len(levels) and roll[:20] == [None] * 20
    assert roll[20] == pytest.approx(statistics.stdev(moves[:20])) and roll[-1] == pytest.approx(out[20]["d"])
    assert vc.rolling(levels[:10], "pct", 20) == [None] * 10


def test_a_forward_from_the_par_curve_of_a_day():
    flat = {3.0: 35.0, 6.0: 35.0, 12.0: 35.0, 24.0: 35.0}
    for a, b in ((0, 12), (3, 6), (9, 12), (12, 24), (6, 18)):
        assert vc.bootstrap_forward(flat, a, b) == pytest.approx(35.0, abs=1e-9)
    up = {6.0: 34.0, 12.0: 35.0, 24.0: 37.0}
    assert vc.bootstrap_forward(up, 0, 12) == 35.0 and vc.bootstrap_forward(up, 12, 24) > 37.0 > vc.bootstrap_forward(up, 6, 12) > 35.0
    for bad in ((1, 4), (12, 12), (12, 9), (-3, 6), (12, 36)):                # off the quarterly grid, backwards, past the curve
        assert vc.bootstrap_forward(up, *bad) is None
    assert vc.bootstrap_forward({}, 3, 6) is None


def test_the_forward_is_close_to_the_workbooks(module_service):
    svc = module_service
    book = svc.books["tto"]

    def run():
        mkt = bl.OisMarket(book, svc._calc(None, book))
        pars = {float(m): mkt.par(t) * 100 for t, m in bl.TENOR_MONTHS.items() if mkt.par(t) is not None}
        return [(vc.bootstrap_forward(pars, a, b), mkt.fra_months(a, b) * 100) for a, b in ((0, 12), (3, 6), (9, 12), (12, 24), (24, 36), (60, 120))]

    for simple, sheet in svc.et.call(run):
        assert simple == pytest.approx(sheet, abs=0.05)                       # within 5 bp: for how much it moves, not for a price


def test_one_row_of_the_page():
    rng = random.Random(5)
    days = [(dt.date(2026, 1, 1) + dt.timedelta(days=k)).isoformat() for k in range(300)]
    one = {d: 35.0 + rng.gauss(0, 0.5) for d in days}
    two = {d: one[d] + 0.4 + rng.gauss(0, 0.05) for d in days}
    row = vc.describe(vc.parse_items("1y2y")[0], {"1Y": one, "2Y": two}, MONTHS, 20, keep=100)
    levels = [(two[d] - one[d]) * 100 for d in days]
    moves = [b - a for a, b in zip(levels, levels[1:])]
    assert (row["ok"], row["label"], row["unit"], row["day"], row["first"], row["n"]) == (True, "1Y–2Y", "bp", days[-1], days[0], 299)
    assert row["level"] == pytest.approx(levels[-1]) and row["change"] == pytest.approx(moves[-1])
    assert row["vols"]["20"]["d"] == pytest.approx(statistics.stdev(moves[-20:])) and row["vols"]["250"]["full"] is True
    assert row["sigma"] == pytest.approx(moves[-1] / statistics.stdev(moves[-20:]))                      # the last move in its own vol
    assert (len(row["days"]), len(row["levels"]), len(row["roll"])) == (100, 100, 100) and row["days"][-1] == days[-1]
    assert row["roll"][-1] == pytest.approx(row["vols"]["20"]["d"]) and row["levels"][-1] == row["level"]
    gone = vc.describe(vc.parse_items("7y")[0], {"1Y": one}, MONTHS)
    assert gone["ok"] is False and gone["error"] == "geçmişi yok: 7Y" and gone["label"] == "7Y"


# ---------------------------------------------------------------------------------------------- with the dashboard's history
TENORS = ("6M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y")


@pytest.fixture(scope="module")
def seeded(module_service):
    """The service with 90 week days of made-up closes for seven OIS tenors (the 5Y missing every seventh day) and
    the 5Y cross-currency swap."""
    svc = module_service
    snap = svc.history.snapshot()
    ois = {d.label: d.id for d in snap["defs"] if d.group == "ois"}
    xccy = {d.label: d.id for d in snap["defs"] if d.group == "xccy"}
    days = []
    d = dt.date(2026, 11, 3)
    while len(days) < 90:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= dt.timedelta(days=1)
    days.reverse()
    rng = random.Random(3)
    data = {}
    for k, tenor in enumerate(TENORS):
        v = 36.0 - 0.2 * k
        series = {}
        for i, day in enumerate(days):
            v += rng.gauss(0, 0.06 + 0.01 * k)
            if tenor == "5Y" and i % 7 == 3:
                continue
            series[day] = round(v, 4)
        data[tenor] = series
        svc.store.hist_upsert(ois[tenor], sorted(series.items()))
    data["X5Y"] = {day: round(39.0 + rng.gauss(0, 0.3), 4) for day in days}
    svc.store.hist_upsert(xccy["5Y"], sorted(data["X5Y"].items()))
    # two bonds of the DİBS table: a fixed coupon (followed by its yield) and a floater (by its price)
    bonds = [d for d in snap["defs"] if d.group == "dibs"]
    fixed, floater = next(d for d in bonds if d.unit == "pct"), next(d for d in bonds if d.unit == "px")
    data["BOND"] = (fixed.label, {day: round(37.0 + rng.gauss(0, 0.2), 4) for day in days})
    data["FRN"] = (floater.label, {day: round(100.0 + rng.gauss(0, 0.15), 4) for day in days})
    svc.store.hist_upsert(fixed.id, sorted(data["BOND"][1].items()))
    svc.store.hist_upsert(floater.id, sorted(data["FRN"][1].items()))
    svc.history.rev += 1                                                     # what the history does when it stores closes
    return svc, days, data


def moves_of(series, days, weights):
    """Daily moves (bp) of a combination on the days all its legs closed."""
    common = [d for d in days if all(d in s for s in series)]
    levels = [sum(w * s[d] for w, s in zip(weights, series)) * 100 for d in common]
    return common, levels, [b - a for a, b in zip(levels, levels[1:])]


def test_the_vol_of_what_is_typed(seeded):
    svc, days, data = seeded
    out = svc.vol(None, "1y, 1y2y, 1y2y3y, 2y5y, 6x12, 5y x, 10y, zzz")
    assert (out["window"], out["windows"], out["year"]) == (20, [10, 20, 60, 120, 250], 252.0)
    assert out["history"]["first"] == days[0] and out["history"]["last"] == days[-1] and out["history"]["days"] == 90
    assert out["history"]["tenors"]["OIS"] == list(TENORS) and out["history"]["tenors"]["XCCY"] == ["5Y"] and out["history"]["live"] is False
    rows = {r["raw"]: r for r in out["rows"]}
    _, levels, moves = moves_of([data["1Y"]], days, (1,))
    r = rows["1y"]
    assert (r["level"], r["day"], r["n"], r["kind"]) == (pytest.approx(data["1Y"][days[-1]]), days[-1], 89, "outright")
    assert r["change"] == pytest.approx(moves[-1]) and r["vols"]["20"]["d"] == pytest.approx(statistics.stdev(moves[-20:]))
    assert r["vols"]["60"]["d"] == pytest.approx(statistics.stdev(moves[-60:])) and r["vols"]["60"]["full"] is True
    assert r["vols"]["120"] == {"d": pytest.approx(statistics.stdev(moves)), "n": 89, "full": False}
    _, levels, moves = moves_of([data["1Y"], data["2Y"]], days, (-1, 1))
    assert rows["1y2y"]["level"] == pytest.approx(levels[-1]) and rows["1y2y"]["vols"]["20"]["d"] == pytest.approx(statistics.stdev(moves[-20:]))
    _, levels, moves = moves_of([data["1Y"], data["2Y"], data["3Y"]], days, (-1, 2, -1))
    assert rows["1y2y3y"]["level"] == pytest.approx(levels[-1]) and rows["1y2y3y"]["vols"]["60"]["d"] == pytest.approx(statistics.stdev(moves[-60:]))
    # the 5Y has no close on some days: those days are not days without a move
    common, levels, moves = moves_of([data["2Y"], data["5Y"]], days, (-1, 1))
    assert len(common) == len(data["5Y"]) < 90 and rows["2y5y"]["n"] == len(common) - 1
    assert rows["2y5y"]["vols"]["20"]["d"] == pytest.approx(statistics.stdev(moves[-20:])) and rows["2y5y"]["first"] == common[0]
    # a forward: from the par curve of every day
    fwd = rows["6x12"]
    last = {vc_m: data[t][days[-1]] for t, vc_m in (("6M", 6.0), ("1Y", 12.0))}
    assert fwd["kind"] == "fra" and fwd["level"] == pytest.approx(vc.bootstrap_forward(last, 6, 12)) and fwd["n"] == 89
    x = rows["5y x"]
    assert x["product"] == "XCCY" and x["level"] == data["X5Y"][days[-1]] and x["vols"]["20"]["d"] > 15
    assert rows["10y"]["ok"] is False and rows["10y"]["error"] == "geçmişi yok: 10Y" and rows["zzz"]["ok"] is False
    # a bond by its ISIN: the yield moves in bp, the price of a floater in points
    (isin, yields), (frn, prices) = data["BOND"], data["FRN"]
    b = {r["label"]: r for r in svc.vol(None, "%s, %s, TRT010101T11" % (isin.lower(), frn))["rows"]}
    ys, ps = [yields[d] for d in days], [prices[d] for d in days]
    assert (b[isin]["product"], b[isin]["unit"], b[isin]["level"]) == ("DIBS", "pct", ys[-1])
    assert b[isin]["vols"]["20"]["d"] == pytest.approx(statistics.stdev([(y - x) * 100 for x, y in zip(ys[-21:], ys[-20:])]))
    assert b[frn]["unit"] == "px" and b[frn]["vols"]["20"]["d"] == pytest.approx(statistics.stdev([y - x for x, y in zip(ps[-21:], ps[-20:])]))
    assert b["TRT010101T11"]["ok"] is False and b["TRT010101T11"]["error"] == "geçmişi yok: TRT010101T11"
    # the window asked for: the rolling line and the size of the last move
    wide = svc.vol(None, "1y", 60)
    assert wide["window"] == 60 and wide["rows"][0]["roll"][-1] == pytest.approx(wide["rows"][0]["vols"]["60"]["d"])
    assert wide["rows"][0]["roll"][59] is None and wide["rows"][0]["roll"][60] is not None
    assert svc.vol(None, "1y", "abc")["window"] == 20 and svc.vol(None, "1y", 33)["window"] == 20 and svc.vol(None, "")["rows"] == []


def test_carry_against_the_vol(seeded):
    svc, days, data = seeded
    out = svc.carry_vol(None, "fly", 20)
    # the horizons of the sheet: their names and the week days from OIS spot to their end
    spot = dt.date(1899, 12, 30) + dt.timedelta(days=cell(svc, "OIS_MAIN!B2"))
    for name, row, label in (("a", 3, "1 ay"), ("b", 22, "3 ay")):
        end = dt.date(1899, 12, 30) + dt.timedelta(days=cell(svc, "C & R!C%d" % row))
        assert out["horizons"][name] == {"label": label, "date": end.isoformat(), "days": vc.week_days(spot, end)}
    assert out["horizons"]["a"]["days"] == 22 and out["horizons"]["b"]["days"] == 66
    # every fly of the sheet's table, with the sheet's own carry + roll
    first = next(r for r in range(1, 400) if str(cell(svc, "C & R!A%d" % r)).startswith("Kanat / Gövde"))
    labels = []
    r = first + 1
    while isinstance(cell(svc, "C & R!A%d" % r), str) and "/" in cell(svc, "C & R!A%d" % r):
        labels.append((r, cell(svc, "C & R!A%d" % r)))
        r += 1
    assert len(out["rows"]) == len(labels) == 34 and (out["kind"], out["window"]) == ("fly", 20)
    rows = {x["label"]: x for x in out["rows"]}
    for r, label in labels:
        x = rows[label.replace("/", "–")]
        assert x["market"] == cell(svc, "C & R!B%d" % r)
        for name, col in (("a", "C"), ("b", "D")):
            v = cell(svc, "C & R!%s%d" % (col, r))
            assert x["cr_" + name] == (v if isinstance(v, float) else None)
    # the volatility of the fly's own level, over the horizon, and carry against it
    x = rows["1Y–2Y–3Y"]
    _, _, moves = moves_of([data["1Y"], data["2Y"], data["3Y"]], days, (-1, 2, -1))
    sd = statistics.stdev(moves[-20:])
    assert x["vol"] == pytest.approx(sd) and (x["n"], x["full"], x["error"]) == (20, True, "")
    assert x["vol_a"] == pytest.approx(sd * math.sqrt(22)) and x["vol_b"] == pytest.approx(sd * math.sqrt(66))
    assert x["ratio_a"] == pytest.approx(x["cr_a"] / (sd * math.sqrt(22))) and x["ratio_b"] == pytest.approx(x["cr_b"] / (sd * math.sqrt(66)))
    gone = rows["8Y–9Y–10Y"]
    assert gone["vol"] is None and gone["ratio_b"] is None and gone["error"] == "geçmişi yok: 8Y, 9Y, 10Y" and gone["cr_b"] is not None
    assert rows["1M–2M–3M"]["cr_b"] is None and rows["1M–2M–3M"]["ratio_b"] is None            # a fly that is gone before the horizon ends
    # another window; the spreads
    assert svc.carry_vol(None, "fly", 60)["rows"][0]["label"] == out["rows"][0]["label"] and svc.carry_vol(None, "fly", 60)["window"] == 60
    wide = {x["label"]: x for x in svc.carry_vol(None, "fly", 60)["rows"]}["1Y–2Y–3Y"]
    assert wide["vol"] == pytest.approx(statistics.stdev(moves[-60:])) and wide["n"] == 60
    sp = svc.carry_vol(None, "spread", 20)
    assert sp["kind"] == "spread" and len(sp["rows"]) == 120 and sp["rows"][0]["label"] == "1M–2M"
    s = {x["label"]: x for x in sp["rows"]}["1Y–2Y"]
    _, _, moves = moves_of([data["1Y"], data["2Y"]], days, (-1, 1))
    assert s["vol"] == pytest.approx(statistics.stdev(moves[-20:])) and s["ratio_a"] == pytest.approx(s["cr_a"] / s["vol_a"])
    assert svc.carry_vol(None, "nedir", "x")["kind"] == "fly" and svc.carry_vol(None, "fly", "x")["window"] == 60


def test_carry_of_the_instruments_typed(seeded):
    """"Listem": OIS tenors, spreads and flies typed - the sheet's tenor engine prices them as its tables do (a fly
    of the table gives the table's number), against their own volatility."""
    svc, days, data = seeded
    out = svc.carry_vol(None, "list", 20, "1y2y3y, 1y2y, 1y, 15m, 9x12, 5y x, yok")
    assert out["kind"] == "list" and out["horizons"] == svc.carry_vol(None, "fly", 20)["horizons"]
    assert out["path"] == "piyasa OIS eğrisinin (bootstrap) ima ettiği TLREF"                     # the default
    rows = out["rows"]
    assert [r["label"] for r in rows] == ["1Y–2Y–3Y", "1Y–2Y", "1Y", "15M", "9x12", "5Y", "yok"]     # in the order typed
    table = {r["label"]: r for r in svc.carry_vol(None, "fly", 20)["rows"]}["1Y–2Y–3Y"]
    spreads = {r["label"]: r for r in svc.carry_vol(None, "spread", 20)["rows"]}["1Y–2Y"]
    for got, want in ((rows[0], table), (rows[1], spreads)):
        for k in ("market", "cr_a", "cr_b", "vol", "vol_a", "ratio_b"):
            assert got[k] == pytest.approx(want[k], rel=1e-12), k
    # an outright: the receiver's carry + roll in bp of its annuity, the tenor engine's row (1Y is the sixth tenor)
    k1, d1 = cell(svc, "Motor!K187"), cell(svc, "Motor!D187")
    assert cell(svc, "Motor!A187") == 12 and rows[2]["cr_a"] == pytest.approx(k1 / d1 * 10000)
    assert rows[2]["market"] == pytest.approx(cell(svc, "Motor!B311") * 100) and rows[2]["kind"] == "outright"
    assert rows[3]["error"].startswith("carry vadeleri: 1M, 2M, 3M, 6M, 9M, 1Y, 18M, 2Y") and rows[3]["cr_a"] is None if "cr_a" in rows[3] else True
    assert rows[4]["error"] == rows[5]["error"] == "carry yalnız OIS vadesi, spread'i ve fly'ı için"
    assert "anlaşılamadı" in rows[6]["error"]
    assert svc.carry_vol(None, "list", 20, "")["rows"] == []


def test_the_carry_path_is_ones_own_choice(seeded):
    """Bootstrap by default; S1 gives the workbook's own numbers (Excel compounds S1); the roll keeps the curve and
    the S1 cells the OIS sheet prices with stay as they are."""
    svc, days, data = seeded
    u = svc.login("Carry Patika")["user"]
    st = svc.carry_settings(u)
    assert (st["path"], st["default"], st["a"], st["b"]) == ("Bootstrap", "Bootstrap", 1.0, 3.0)
    assert [o["id"] for o in st["options"]] == ["Bootstrap", "MPC ima", "S1", "S2", "S3", "Sabit TLREF"]
    assert [o["label"] for o in st["options"]][2:5] == ["S1 · Baz", "S2 · Hawkish", "S3 · Dovish"]
    assert cell(svc, "C & R!A1", u).endswith("TLREF = piyasa OIS eğrisinin (bootstrap) ima ettiği TLREF (iş günü bileşik)")
    s1_cells = [cell(svc, "Motor!G%d" % r, u) for r in range(139, 179)]
    roll = [cell(svc, "C & R!E%d" % r, u) for r in range(24, 40)]
    # a 3M swap carried over three months along the curve it is priced off: no carry
    assert cell(svc, "C & R!A26") == "3M" and abs(cell(svc, "C & R!D26", u)) < 1e-6
    svc.set_carry_settings(u, "S1", 1, 3)
    sh = svc.books["tto"].model.sheet("C & R")
    n = 0
    for r in list(range(5, 21)) + list(range(24, 40)) + list(range(43, 163)) + list(range(166, 200)):
        for col in "CDEF":
            saved = sh.cached.get(parse_a1("%s%d" % (col, r)))
            if isinstance(saved, float):
                assert cell(svc, "C & R!%s%d" % (col, r), u) == pytest.approx(saved, rel=1e-12, abs=1e-9), (col, r)
                n += 1
    assert n > 600
    assert cell(svc, "Motor!G135", u) == cell(svc, "OIS_MAIN!X11", u)           # S1's TLREF after the second meeting
    tl = {}
    for path in ("Sabit TLREF", "MPC ima", "S2", "S3", "Bootstrap"):
        svc.set_carry_settings(u, path, 1, 3)
        tl[path] = cell(svc, "Motor!G135", u)
        now = [cell(svc, "C & R!E%d" % r, u) for r in range(24, 40)]                                          # the roll keeps the curve
        assert [x for x in now if not isinstance(x, float)] == [x for x in roll if not isinstance(x, float)] == ["", ""]
        assert [x for x in now if isinstance(x, float)] == pytest.approx([x for x in roll if isinstance(x, float)], rel=1e-12, abs=1e-12)
        assert [cell(svc, "Motor!G%d" % r, u) for r in range(139, 179)] == s1_cells                              # S1 as it was
    assert tl["Sabit TLREF"] == cell(svc, "OIS_MAIN!J2")
    assert tl["MPC ima"] == cell(svc, "Motor!K6")                                   # the implied path after two meetings
    assert tl["S2"] == cell(svc, "OIS_MAIN!Y11") and tl["S3"] == cell(svc, "OIS_MAIN!Z11")
    # flat TLREF: carry = fixed − TLREF compounded on business days, the sheet's own day-count correction
    svc.set_carry_settings(u, "Sabit TLREF", 1, 3)
    d = cell(svc, "Motor!D135", u)
    r = cell(svc, "OIS_MAIN!J2")
    growth = math.exp(d * math.log(1 + r / 365) - cell(svc, "Motor!F%d" % (528 + int(d))) * (r / 365) ** 2)
    assert cell(svc, "Motor!E135", u) == pytest.approx(growth, rel=1e-13)
    # nobody else's; the horizons are one's own too
    assert cell(svc, "EK_CARRY!B2") == "Bootstrap" and cell(svc, "C & R!E26") == pytest.approx(roll[2])
    st = svc.set_carry_settings(u, "MPC ima", 2, 6)
    assert (st["path"], st["a"], st["b"]) == ("MPC ima", 2.0, 6.0) and st["horizons"]["b"]["label"] == "6 ay"
    assert cell(svc, "C & R!A3", u).startswith("Ufuk A: 2 ay") and cell(svc, "C & R!A22", u).startswith("Ufuk B: 6 ay")
    for bad in (("Yok", 1, 3), ("S1", 0, 3), ("S1", 1, 121), ("S1", 1.5, 3), ("S1", "x", 3)):
        with pytest.raises(ServiceError):
            svc.set_carry_settings(u, *bad)
    with pytest.raises(ServiceError):
        svc.set_carry_settings(None, "S1", 1, 3)


def test_spreads_over_ois_day_by_day(seeded):
    """Offshore − OIS tenor by tenor from the closes both curves have (the 5Y: the cross currency swap against the
    5Y OIS, the days the OIS closed), today's level from the live quotes of the source in use, the changes and
    where the level stands against the last 20 / 60 / 250 closes."""
    svc, days, data = seeded
    out = svc.spreads(None)
    assert out["windows"] == [20, 60, 250] and out["today"] == "2026-11-03"
    five = next(r for r in out["off"] if r["months"] == 60.0)
    assert five["tenor"] == "5Y" and five["kind"] == "XCCY" and five["id"] == "off:60"
    common = [d for d in days if d in data["5Y"] and d in data["X5Y"] and d < out["today"]]
    spread = [(data["X5Y"][d] - data["5Y"][d]) * 100 for d in common]
    assert five["live"] and five["day"] == out["today"] and five["n"] == len(common) + 1
    assert five["level"] == pytest.approx((five["off_now"] - five["ois_now"]) * 100)
    assert five["off_now"] == pytest.approx(39.97001) and five["ois_now"] == pytest.approx(34.71)
    assert five["d1"] == pytest.approx(five["level"] - spread[-1]) and five["d1_day"] == common[-1]
    assert five["w1"] == pytest.approx(five["level"] - spread[-5]) and five["m1"] == pytest.approx(five["level"] - spread[-21])
    for n in (20, 60):
        part = spread[-n:]
        b = five["bands"][str(n)]
        assert b["n"] == n and b["mean"] == pytest.approx(statistics.mean(part)) and b["sd"] == pytest.approx(statistics.stdev(part))
        assert b["z"] == pytest.approx((five["level"] - b["mean"]) / b["sd"])
        assert b["min"] == pytest.approx(min(part + [five["level"]])) and b["max"] == pytest.approx(max(part + [five["level"]]))
        assert b["pct"] == pytest.approx(sum(1 for x in part if x < five["level"]) / n)
    assert five["bands"]["250"]["n"] == len(common)                       # fewer closes than the window: all of them
    assert five["days"][-1] == out["today"] and five["values"][-1] == five["level"] and len(five["days"]) == len(common) + 1
    assert five["values"][:-1] == pytest.approx(spread)
    # a tenor without closes on one side still shows today's level, with nothing to compare it with
    one = next(r for r in out["off"] if r["months"] == 12.0)
    assert one["live"] and one["n"] == 1 and one["d1"] is None and one["bands"]["20"]["z"] is None
    # VİOP − OIS: the contracts of the VİOP history (the four nearest at first), today's basis from the sheet's live row
    assert [r["order"] for r in out["viop"]] == [1, 2, 3, 4] and all(r["id"].startswith("viop:") for r in out["viop"])
    first = out["viop"][0]
    assert first["live"] and type(first["level"]) is float and first["imp_now"] - first["ois_now"] == pytest.approx(first["level"] / 100, abs=1e-6)


def test_a_spread_row_without_a_live_quote(module_service):
    """No quote today: the last close is the level and the changes are counted from the closes before it."""
    svc = module_service
    pts = [("2026-10-%02d" % d, float(d)) for d in range(1, 31) if dt.date(2026, 10, d).weekday() < 5]
    row = svc._spread_row(pts, None, "2026-11-03")
    assert not row["live"] and row["day"] == pts[-1][0] and row["level"] == pts[-1][1] and row["n"] == len(pts)
    assert row["d1"] == pts[-1][1] - pts[-2][1] and row["w1"] == pts[-1][1] - pts[-6][1] and row["m1"] == pts[-1][1] - pts[-22][1]
    assert row["bands"]["20"]["n"] == 20 and row["bands"]["60"]["n"] == len(pts) - 1
    assert svc._spread_row([], None, "2026-11-03") is None and svc._spread_row([("2026-11-02", float("nan"))], None, "2026-11-03") is None
    # a live quote replaces the day's own close
    row = svc._spread_row(pts + [("2026-11-03", 99.0)], 50.0, "2026-11-03")
    assert row["level"] == 50.0 and row["d1_from"] == pts[-1][1] and 99.0 not in row["values"]


def test_week_days():
    assert vc.week_days(dt.date(2026, 11, 4), dt.date(2026, 12, 4)) == 22 and vc.week_days(dt.date(2026, 11, 6), dt.date(2026, 11, 9)) == 1
    assert vc.week_days(dt.date(2026, 11, 4), dt.date(2026, 11, 4)) == 0 == vc.week_days(dt.date(2026, 11, 7), dt.date(2026, 11, 8))


def test_over_http(seeded):
    svc, days, data = seeded
    with TestClient(create_app(svc), headers=auth(svc, "Vol Okuyucu")) as client:
        res = client.post("/api/vol", json={"text": "1y, 1y2y3y, yok", "window": 60})
        assert res.status_code == 200
        out = res.json()
        assert out["window"] == 60 and [r["ok"] for r in out["rows"]] == [True, True, False] and out["rows"][0]["vols"]["60"]["n"] == 60
        assert len(out["rows"][1]["days"]) == 90 == len(out["rows"][1]["levels"]) == len(out["rows"][1]["roll"])
        res = client.get("/api/vol/carry", params={"kind": "spread", "window": 10})
        assert res.status_code == 200 and res.json()["kind"] == "spread" and res.json()["window"] == 10 and len(res.json()["rows"]) == 120
        assert client.get("/api/vol/carry").json()["kind"] == "fly"
        res = client.post("/api/vol/carry", json={"kind": "list", "window": 20, "text": "1y2y3y, 2y"})
        assert res.status_code == 200 and [r["label"] for r in res.json()["rows"]] == ["1Y–2Y–3Y", "2Y"]
        h = auth(svc, "carry http")
        assert client.get("/api/carry", headers=h).json()["path"] == "Bootstrap"
        res = client.post("/api/carry", json={"path": "S3", "a": "1", "b": "3"}, headers=h)
        assert res.status_code == 200 and res.json()["path"] == "S3" and res.json()["about"] == "S3 senaryosu (Dovish)"
        assert client.post("/api/carry", json={"path": "S9", "a": 1, "b": 3}, headers=h).status_code == 400
        nav = client.get("/api/nav").json()["pages"]
        assert [p["title"] for p in nav if p["id"] == "vol"] == ["Realized Vol · Carry"]
        assert [p["title"] for p in nav if p["id"] == "spreads"] == ["Spread Geçmişi"]
        res = client.get("/api/spreads")
        assert res.status_code == 200 and {"off", "viop", "windows", "state"} <= set(res.json())
        assert client.get("/static/js/pages/vol.js").status_code == 200
