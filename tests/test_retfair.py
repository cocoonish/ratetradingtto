"""Fair value RET (``tto/retfair.py``) and the desk's forwards per RET tenor (``tto/retflow.py``): each base's mid per
tenor against its machinery, blends, the offset and the width, the 5 bp grid, the 2 bp hysteresis, "Kopyala ve
yayınla", "Neredeyim", flow suggestions from planted trades (volume, normal, cost, neighbours, never below cost +
margin, nothing from Broker Chat), the flow adjustment that stays until removed, the administrators' settings, an old
database, the tenors kept by their label - and Günlük İşlemler's "Pozisyon ve maliyet" on the same aggregation."""
from __future__ import annotations

import datetime as _dt
import sqlite3

import pytest

from conftest import ANON, auth, cell, make_service
from tto import borsaspread as bsp
from tto import quantviop as qv
from tto import retfair as rfv
from tto import retflow as rf
from tto.service import Service, ServiceError
from tto.xl.model import COLS, parse_a1
from tto.xl.values import date_to_serial

TODAY = "2026-11-17"                       # a Tuesday: the ten business days before it are 03.11 – 16.11
SPOT = 46330.0                             # the replay's USDTRY spot date (04.11.2026)


# ---------------------------------------------------------------------------------------------- helpers
class FlatCurve(object):
    """A curve with one rate between any two dates (``why``: it cannot be read)."""

    def __init__(self, rate, why=""):
        self.rate, self.why = rate, why

    def zero(self, start, end):
        return self.rate if not self.why and end > start else None


def market(ois=0.36, off=0.33, viop=None, tenors=None, spot=SPOT):
    tenors = tenors or [("ON", 1.0, 0.3555, 0.3575), ("1M", 30.0, 0.3445, 0.3465), ("2M", 61.0, 0.3445, 0.3495),
                        ("3M", 92.0, 0.35, 0.355)]
    rows = [{"label": lab, "row": 33 + i, "days": d, "bid": b, "ask": a} for i, (lab, d, b, a) in enumerate(tenors)]
    return rfv.Market(spot, rows, {"ois": ois if not isinstance(ois, float) else FlatCurve(ois),
                                   "off": off if not isinstance(off, float) else FlatCurve(off)}, viop or [])


def by_tenor(rows):
    return {r["tenor"]: r for r in rows}


def reset(svc):
    """The module's service as new: no fair value settings, no shown values, no trades."""
    for key in ("retfair.desk", "retfair.admin", "retfair.shown", "retfair.accepted"):
        svc.store.put(key, {})
    for t in svc.store.trades("2000-01-01", "2100-01-01"):
        svc.store.delete_trade(t["id"], None)


def fwd(direction, amount, days, rate, dv01=None, pair="USDTRY"):
    """A forward as the blotter keeps one (priced: its days, TRY rate and DV01 in TL - payer +)."""
    return {"pair": pair, "dir": direction, "amount": float(amount), "value_date": SPOT + days, "basis": "TRY", "days": float(days),
            "try_rate": rate, "forward": 52.0, "spot": 50.0, "usdtry": 50.0, "usd_rate": 0.04,
            "dv01_tl": float(dv01 if dv01 is not None else (1.0 if direction == "B" else -1.0) * amount / 1e6 * 10.0)}


def plant(svc, day, *records):
    for r in records:
        svc.store.add_trade(day, "fwd", r, None)


def cells_of(svc, refs):
    book = svc.books["tto"]

    def run():
        calc = book.engine.shared
        out = {}
        for ref in refs:
            si, rc = book.cell(ref)
            out[ref] = calc.get(si, *divmod(rc, COLS))
        return out

    return svc.et.call(run)


# ---------------------------------------------------------------------------------------------- the numbers
def test_offset_width_and_the_5bp_grid():
    m = market(ois=0.3587)
    rows, shown = rfv.compute(m, {"tenors": {"1M": {"base": "ois", "offset": -60.0}}}, {"hysteresis": 2.0, "widths": {"1M": 20, "2M": 50}}, {})
    r = by_tenor(rows)["1M"]
    # mid 35,87 − 60 bp = 35,27; bid 35,17 on the grid: 35,15; ask = bid + the width
    assert r["raw_mid"] == pytest.approx(0.3527) and r["raw_bid"] == pytest.approx(0.3517)
    assert r["now"] == {"bid": 0.3515, "ask": 0.3535} and shown["1M"]["bid"] == 3515.0
    assert r["formula"] == "OIS mid − 60"
    assert r["diff"] == {"bid": 70.0, "ask": 70.0} and r["update"] is True          # published 34,45 / 34,65
    # no offset: no value (and why); the published RET stays what it is
    r2 = by_tenor(rows)["2M"]
    assert r2["now"] is None and r2["now_why"] == "tabana spread yazılmadı" and r2["update"] is False
    assert r2["pub"] == {"bid": 0.3445, "ask": 0.3495}
    # the grid: a half step up, on the step stays
    assert rfv.grid_round(3427.5) == 3430.0 and rfv.grid_round(3427.4999) == 3425.0 and rfv.grid_round(3425.0) == 3425.0
    assert rfv.grid_round(3412.5) == 3415.0
    # an offset with the width: 50 bp wide, mid 35,87 − 100 = 34,87: bid 34,62 → 34,60, ask 35,10
    rows, _ = rfv.compute(m, {"tenors": {"2M": {"offset": -100.0}}}, {"widths": {"2M": 50}}, {})
    assert by_tenor(rows)["2M"]["now"] == {"bid": 0.346, "ask": 0.351}
    # the base missing (a curve that cannot be read): no value, the curve's reason
    rows, _ = rfv.compute(market(ois=FlatCurve(0.36, why="TTO çalışma kitabında BOOT_GUN / BOOT_LNDF adı yok")),
                          {"tenors": {"1M": {"offset": 0.0}}}, {"widths": {"1M": 20}}, {})
    assert by_tenor(rows)["1M"]["now"] is None and "BOOT_GUN" in by_tenor(rows)["1M"]["now_why"]


def test_hysteresis_two_bp():
    h = 2.0
    assert rfv.next_shown(3427.0, None, h) == 3425.0                    # first reading: the raw bid rounded
    assert rfv.next_shown(3430.0, 3425.0, h) == 3430.0                  # 3 bp up across the step (34,275): moves
    assert rfv.next_shown(3428.0, 3425.0, h) == 3425.0                  # 1 bp: rounding says 34,30, the hysteresis keeps 34,25
    shown, seen = 3425.0, []
    for raw in (3428.0, 3427.0, 3428.5, 3426.9, 3429.4, 3427.2):        # back and forth across the step: no flapping
        shown = rfv.next_shown(raw, shown, h)
        seen.append(shown)
    assert seen == [3425.0] * 6
    assert rfv.next_shown(3429.0, 3430.0, h) == 3430.0 and rfv.next_shown(3425.6, 3430.0, h) == 3430.0
    assert rfv.next_shown(3425.4, 3430.0, h) == 3425.0                  # 2,1 bp past the step below: back
    assert rfv.next_shown(3428.0, 3425.0, 0.0) == 3430.0                # no hysteresis: plain rounding
    # the same through the curve: the OIS base moves, the 1M row follows with the hysteresis
    m = market(ois=0.3437)
    desk = {"tenors": {"1M": {"offset": 0.0}}}
    admin = {"hysteresis": 2.0, "widths": {"1M": 20}}
    state = {}

    def bid_at(rate):
        m.curves["ois"] = FlatCurve(rate)
        rows, new = rfv.compute(m, desk, admin, state)
        state.update(new)
        return by_tenor(rows)["1M"]["now"]["bid"]

    assert bid_at(0.3437) == 0.3425                                     # raw bid 34,27
    assert bid_at(0.3440) == 0.343                                      # +3 bp across the step: 34,30
    assert bid_at(0.3439) == 0.343 and bid_at(0.3438) == 0.343          # back by 1, by 2: stays
    assert bid_at(0.3439) == 0.343 and bid_at(0.3437) == 0.343          # back and forth: no flapping
    assert bid_at(0.34355) == 0.343                                     # 2 bp below the step: not more than 2
    assert bid_at(0.34354) == 0.3425                                    # 2,1 bp below it: down again


def test_blends():
    mids = {"ois": 0.36, "viop": 0.34, "off": 0.33}
    v, why = rfv.blend_mid(mids, {"ois": 50, "viop": 25, "off": 25})
    assert v == pytest.approx(0.3475) and why == ""
    assert rfv.blend_mid(mids, {"ois": 2, "viop": 1, "off": 1})[0] == pytest.approx(0.3475)      # need not add up to 100
    assert rfv.blend_mid(mids, {"ois": 1, "viop": 0, "off": 1})[0] == pytest.approx(0.345)       # 0: that base is out
    v, why = rfv.blend_mid(dict(mids, viop=None), {"ois": 50, "viop": 25, "off": 25})
    assert v is None and why == "karma: VİOP mid yok"
    assert rfv.blend_mid(dict(mids, viop=None), {"ois": 50, "off": 50})[0] == pytest.approx(0.345)
    assert rfv.blend_mid(mids, {})[0] is None
    # a blended tenor in the curve, with its offset
    m = market(ois=0.36, off=0.33, viop=[(SPOT + 20, 0.34, "A"), (SPOT + 40, 0.34, "B")])
    rows, _ = rfv.compute(m, {"tenors": {"1M": {"base": "blend", "weights": {"ois": 50, "viop": 25, "off": 25}, "offset": -10.0}}},
                          {"widths": {"1M": 20}}, {})
    r = by_tenor(rows)["1M"]
    assert r["base_mid"] == pytest.approx(0.3475) and r["formula"] == "Karma (OIS 50 · VİOP 25 · Offshore 25) − 10"
    assert r["now"] == {"bid": 0.3455, "ask": 0.3475}                   # 34,75 − 10 bp = 34,65 mid, bid 34,55
    # the default blend of the settings when a tenor has none of its own
    rows, _ = rfv.compute(m, {"tenors": {"1M": {"base": "blend", "offset": 0.0}}}, {"widths": {"1M": 20}, "blend": {"ois": 100}}, {})
    assert by_tenor(rows)["1M"]["base_mid"] == pytest.approx(0.36)


def test_viop_mid_by_date():
    pts = [(100.0, 0.33), (131.0, 0.34)]
    assert rfv.interp_dates(pts, 110.0) == pytest.approx(0.33 + 0.01 * 10 / 31)
    assert rfv.interp_dates(pts, 100.0) == 0.33 and rfv.interp_dates(pts, 131.0) == 0.34
    assert rfv.interp_dates(pts, 99.0) is None and rfv.interp_dates(pts, 132.0) is None      # no extrapolation
    m = market(viop=[(SPOT + 26.0, 0.337, "A1X6"), (SPOT + 57.0, 0.340, "A1Z6")])
    rows, _ = rfv.compute(m, {}, {"widths": {}}, {})
    r = by_tenor(rows)
    assert r["1M"]["mids"]["viop"] == pytest.approx(0.337 + 0.003 * 4 / 31)
    assert r["ON"]["mids"]["viop"] is None and r["ON"]["why"]["viop"].startswith("VİOP: ilk kontratın vadesinden")
    assert r["3M"]["mids"]["viop"] is None and r["3M"]["why"]["viop"].startswith("VİOP: son kontratın vadesinden")
    # the tenor's dates: ON from the spot − its days to the spot, the others from the spot
    assert (r["ON"]["start"], r["ON"]["end"]) == ("2026-11-03", "2026-11-04")
    assert (r["1M"]["start"], r["1M"]["end"]) == ("2026-11-04", "2026-12-04")


def test_where_we_stand_and_what_a_base_change_gives():
    m = market(ois=0.3587, off=0.3301, viop=[(SPOT + 26.0, 0.3375, "A"), (SPOT + 57.0, 0.3375, "B")])
    rows, _ = rfv.compute(m, {"tenors": {"1M": {"base": "ois", "offset": -132.0, "flow": 5.0}}}, {"widths": {"1M": 20}}, {})
    r = by_tenor(rows)["1M"]
    # "1M bid 34,45: OIS mid'e −142 bp · VİOP mid'e +70 bp · offshore mid'e +144 bp"
    assert r["where"] == {"ois": pytest.approx(-142.0), "viop": pytest.approx(70.0), "off": pytest.approx(144.0)}
    # with each base and this offset (−132) and flow (+5): bid = base − 127 − 10, on the grid
    assert r["whatif"]["ois"] == {"bid": 0.345, "ask": 0.347}            # 35,87 − 1,37 = 34,50
    assert r["whatif"]["viop"] == {"bid": 0.3240, "ask": 0.3260}         # 33,75 − 1,37 = 32,38 → 32,40
    assert r["whatif"]["off"] == {"bid": 0.3165, "ask": 0.3185}          # 33,01 − 1,37 = 31,64 → 31,65
    assert r["formula"] == "OIS mid − 132 + 5 (akış)"
    assert r["now"] == r["whatif"]["ois"]                                # the base in use is the one shown


def test_tenors_are_kept_by_their_label():
    # the RET table's rows found by the labels of column V, wherever they are; a label missing keeps its shipped row
    class Sheet(object):
        consts = {}

    class Model(object):
        sheet_index = {"Forward": 0}
        sheets = [Sheet()]

    class FakeBook(object):
        model = Model()

    order = ["2Y", "18M", "1Y", "9M", "6M", "5M", "4M", "3M", "2M", "1M", "3W", "2W", "1W", "ON"]      # TN left out
    for i, lab in enumerate(order):
        Sheet.consts[(40 + i) * COLS + 22] = " %s " % lab.lower()
    layout = dict(Service._ret_layout(Service.__new__(Service), FakeBook()))
    assert layout["2Y"] == 40 and layout["1M"] == 49 and layout["ON"] == 53 and layout["TN"] == 34
    # a curve whose rows changed: what is set for "1M" stays with 1M
    tenors = [("3M", 92.0, 0.35, 0.355), ("1M", 30.0, 0.3445, 0.3465), ("ON", 1.0, 0.3555, 0.3575)]
    rows, _ = rfv.compute(market(ois=0.3587, tenors=tenors), {"tenors": {"1M": {"offset": -132.0}}}, {"widths": {"1M": 20}}, {})
    assert by_tenor(rows)["1M"]["now"] == {"bid": 0.3445, "ask": 0.3465} and by_tenor(rows)["3M"]["now"] is None


# ---------------------------------------------------------------------------------------------- the flows
def test_flows_per_tenor_volume_normal_cost_and_pnl():
    buckets = [("1W", 8.0), ("1M", 30.0), ("2M", 61.0)]
    trades = [dict(fwd("B", 200e6, 30, 0.341, dv01=1000.0), id=1, kind="fwd", trade_date=TODAY),
              dict(fwd("B", 40e6, 30, 0.343, dv01=200.0), id=2, kind="fwd", trade_date=TODAY),
              dict(fwd("S", 31e6, 45, 0.35, dv01=-150.0), id=3, kind="fwd", trade_date=TODAY),        # 45 days: 1M and 2M
              {"id": 4, "kind": "ois", "dir": "B", "tenor": "1M", "rate": 0.36, "dv01": 1000.0, "trade_date": TODAY},
              {"id": 5, "kind": "bond", "instrument": "TRT1", "amount": 1e6, "price": 99.0, "trade_date": TODAY},
              dict(fwd("B", 5e6, 30, 0.34, pair="EURUSD"), id=6, kind="fwd", trade_date=TODAY)]        # no TRY: no flow
    fwds = rf.forwards(trades)
    assert [f["id"] for f in fwds] == [1, 2, 3]
    agg = rf.aggregate(fwds, buckets, lambda d: 0.3455, lambda d: 0.3587)
    w1 = (61.0 - 45.0) / 31.0                                          # the 45-day forward's share of 1M (the sheet's split)
    a = agg["1M"]
    assert a["sold"] == pytest.approx(240e6) and a["bought"] == pytest.approx(31e6 * w1)
    assert a["sold_avg"] == pytest.approx((200 * 0.341 + 40 * 0.343) / 240) and a["bought_avg"] == pytest.approx(0.35)
    assert a["net"] == pytest.approx(240e6 - 31e6 * w1) and a["side"] == "sold" and a["cost"] == pytest.approx(a["sold_avg"])
    # P&L: DV01 (TL, payer +) × (the curve's rate − the rate dealt), bp
    assert a["pnl_ret"] == pytest.approx(1000 * (0.3455 - 0.341) * 1e4 + 200 * (0.3455 - 0.343) * 1e4 - 150 * w1 * (0.3455 - 0.35) * 1e4)
    assert a["pnl_ois"] == pytest.approx(1000 * (0.3587 - 0.341) * 1e4 + 200 * (0.3587 - 0.343) * 1e4 - 150 * w1 * (0.3587 - 0.35) * 1e4)
    assert agg["2M"]["bought"] == pytest.approx(31e6 * (1 - w1)) and agg["2M"]["side"] == "bought" and "1W" not in agg
    # a curve without a rate at a trade's days: no P&L for that tenor (not a part of one)
    assert rf.aggregate(fwds, buckets, lambda d: None if d > 40 else 0.3455)["2M"]["pnl_ret"] is None
    # the normal: the average size of the daily net over the days (a day without flow counts as nothing)
    nets = rf.daily_nets([dict(f, day=d) for f, d in zip(fwds, ("2026-11-16", "2026-11-13", "2026-11-13"))], buckets)
    assert nets["2026-11-16"]["1M"] == pytest.approx(200e6)
    assert rf.normal(nets, ["2026-11-16", "2026-11-13", "2026-11-12", "2026-11-11"], "1M") == pytest.approx(
        (200e6 + abs(40e6 - 31e6 * w1)) / 4)
    assert rf.normal(nets, [], "1M") == 0.0
    # the RET read at a number of days: straight lines, flat beyond, the later of equal days
    pts = [(1.0, 0.36), (1.0, 0.37), (30.0, 0.34), (61.0, 0.35)]
    assert rf.curve_at(pts, 0.5) == 0.37 and rf.curve_at(pts, 45.5) == pytest.approx(0.345) and rf.curve_at(pts, 90.0) == 0.35


def _today(net, cost, side, bought_avg=None):
    return {"net": net if side == "sold" else -net, "side": side, "cost": cost, "sold_avg": cost if side == "sold" else None,
            "bought_avg": bought_avg if bought_avg is not None else (cost if side == "bought" else None)}


ORDER = ["ON", "TN", "1W", "2W", "3W", "1M", "2M", "3M"]
CURVE = {"1M": {"pub_bid": 0.3425, "pub_ask": 0.3445, "cur_bid": 0.3425, "cur_ask": 0.3445},
         "2M": {"pub_bid": 0.3445, "pub_ask": 0.3495, "cur_bid": 0.3445, "cur_ask": 0.3495},
         "3W": {"pub_bid": 0.3420, "pub_ask": 0.3440, "cur_bid": 0.3420, "cur_ask": 0.3440}}


def test_the_desks_example_word_for_word():
    s = rf.suggest({"1M": _today(240e6, 0.341, "sold")}, {"1M": 120e6}, ORDER, CURVE, 5.0, 5.0)
    assert len(s) == 1 and s[0]["ok"] and s[0]["moves"] == {"1M": 5, "2M": 5}
    assert s[0]["text"] == "1M'de bugün net 240 mn USD TRY sattık (normalin 2 katı), ortalama 34,10 ile; RET bid 34,25 maliyetin 15 bp üstünde → öneri 1M / 2M ask +5 bp"
    assert s[0]["id"] == "1M:+" and s[0]["steps"] == 1 and s[0]["ratio"] == pytest.approx(2.0)


def test_suggestion_size_neighbours_and_normal():
    # 5 bp for each full 100 mn above the normal (sensitivity 5): 300 mn above → 15 bp; the next tenor out half of it
    s = rf.suggest({"1M": _today(420e6, 0.341, "sold")}, {"1M": 120e6}, ORDER, CURVE, 5.0, 5.0)[0]
    assert s["moves"] == {"1M": 15, "2M": 10} and s["text"].endswith("→ öneri 1M ask +15 bp, 2M ask +10 bp")
    # at or under the normal: nothing; just above it, less than a step: nothing
    assert rf.suggest({"1M": _today(120e6, 0.341, "sold")}, {"1M": 120e6}, ORDER, CURVE, 5.0, 5.0) == []
    assert rf.suggest({"1M": _today(219e6, 0.341, "sold")}, {"1M": 120e6}, ORDER, CURVE, 5.0, 5.0) == []
    # no flow before (no normal): the whole net counts, said so
    s = rf.suggest({"1M": _today(200e6, 0.341, "sold")}, {}, ORDER, CURVE, 5.0, 5.0, quiet_days=10)[0]
    assert s["moves"] == {"1M": 10, "2M": 5} and "(önceki 10 iş gününde akış yok)" in s["text"]
    # TRY bought (on the ask): down, the bid named, the tenor before it half
    s = rf.suggest({"1M": _today(240e6, 0.3400, "bought")}, {"1M": 40e6}, ORDER, CURVE, 5.0, 5.0)[0]
    assert s["moves"] == {"1M": -10, "3W": -5} and s["id"] == "1M:-"
    assert s["text"] == "1M'de bugün net 240 mn USD TRY aldık (normalin 6 katı), ortalama 34,00 ile; RET ask 34,45 maliyetin 45 bp üstünde → öneri 1M bid −10 bp, 3W bid −5 bp"
    # steps accepted today are not suggested again (only what the flow added since)
    assert rf.suggest({"1M": _today(240e6, 0.341, "sold")}, {"1M": 120e6}, ORDER, CURVE, 5.0, 5.0, {"1M:+": 1}) == []
    assert rf.suggest({"1M": _today(420e6, 0.341, "sold")}, {"1M": 120e6}, ORDER, CURVE, 5.0, 5.0, {"1M:+": 1})[0]["moves"] == {"1M": 10, "2M": 5}
    # the last tenor has no next one
    s = rf.suggest({"3M": _today(300e6, 0.35, "sold")}, {}, ORDER, dict(CURVE, **{"3M": CURVE["2M"]}), 5.0, 5.0)[0]
    assert s["moves"] == {"3M": 15}


def test_never_below_cost_plus_margin():
    # TRY bought at 34,30 on average; the ask is 34,45: 15 bp above cost, 5 bp margin → at most 10 bp down
    s = rf.suggest({"1M": _today(400e6, 0.3430, "bought")}, {"1M": 100e6}, ORDER, CURVE, 5.0, 5.0)[0]
    assert s["ok"] and s["moves"] == {"1M": -10, "3W": -10} and s["blocked"] == ["1M"]
    assert s["text"].endswith("(maliyet + marj sınırıyla)")
    assert CURVE["1M"]["cur_ask"] - 0.0010 >= 0.3430 + 0.0005 - 1e-12
    # cost 34,42: no room at all → no suggestion that would cross it (shown, not acceptable)
    s = rf.suggest({"1M": _today(400e6, 0.3442, "bought")}, {"1M": 100e6}, ORDER, CURVE, 5.0, 5.0)[0]
    assert not s["ok"] and s["moves"] == {} and "öneri yok" in s["text"]
    # a neighbour with TRY bought of its own is held by its own cost: 3W's ask 34,40, its cost 34,33 → 0 steps
    today = {"1M": _today(400e6, 0.3400, "bought"), "3W": _today(1e6, 0.3433, "bought")}
    s = rf.suggest(today, {"1M": 100e6, "3W": 1e6}, ORDER, CURVE, 5.0, 5.0)[0]
    assert s["moves"] == {"1M": -15} and s["blocked"] == ["3W"]
    # up never meets the floor
    s = rf.suggest({"1M": _today(400e6, 0.3500, "sold")}, {"1M": 100e6}, ORDER, CURVE, 5.0, 50.0)[0]
    assert s["ok"] and s["moves"] == {"1M": 15, "2M": 10}


# ---------------------------------------------------------------------------------------------- on the workbook
def test_each_base_against_its_machinery(module_service):
    svc = module_service
    reset(svc)
    u = svc.login("RET Taban")["user"]
    rows = by_tenor(svc.retfair.state(u)["rows"])
    book = svc.books["tto"]
    refs = ["Forward!I2"] + ["Forward!%s%d" % (c, r) for r in range(123, 138) for c in ("AC", "AD")]

    def run():
        calc = book.engine.shared
        index = book.model.sheet_index
        out = {}
        qv.read_engine(out, index, lambda sh: (lambda ref: calc.get(index[sh], *divmod(parse_a1(ref), COLS))),
                       lambda v: v if type(v) is float else None)
        return bsp.read_curves(book, calc), out["viopq"]

    curves, viopq = svc.et.call(run)
    sheet = cells_of(svc, refs)
    spot = bsp._date(sheet["Forward!I2"])
    assert spot == SPOT
    assert [t for t in rows] == ["ON", "TN", "1W", "2W", "3W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M", "2Y"]
    for label, r in rows.items():
        d = r["days"]
        start, end = (spot - d, spot) if label == "ON" else (spot, spot + d)
        # OIS / offshore: the Borsa Swap spreads' machinery between the tenor's own dates, simple ACT/360
        assert r["mids"]["ois"] == pytest.approx(curves["ois"].zero(start, end), abs=1e-12)
        assert r["mids"]["off"] == pytest.approx(curves["off"].zero(start, end), abs=1e-12)
    # ... which is the workbook's own: its comparison table (Masa's ORANLAR "OIS zero" / "ICAP") at the curves' nodes
    for label, row in (("ON", 123), ("1M", 128), ("2M", 129), ("3M", 130), ("6M", 133), ("9M", 134), ("1Y", 135)):
        assert rows[label]["mids"]["ois"] == pytest.approx(sheet["Forward!AD%d" % row], abs=1e-9), label
        assert rows[label]["mids"]["off"] == pytest.approx(sheet["Forward!AC%d" % row], abs=1e-9), label
    for label, row in (("1W", 125), ("2W", 126)):
        assert rows[label]["mids"]["off"] == pytest.approx(sheet["Forward!AC%d" % row], abs=1e-9), label
    # VİOP: the VİOP sheet's implied rate of each contract (as the VİOP page reads it), its mid, in a straight line by date
    pts = sorted((float(date_to_serial(_dt.date.fromisoformat(q["expiry"]))), (q["i_bid"] + q["i_ask"]) / 200.0)
                 for q in viopq if q["i_bid"] is not None and q["i_ask"] is not None)
    assert len(pts) >= 6
    for label, r in rows.items():
        end = spot + r["days"]
        if end < pts[0][0] or end > pts[-1][0]:
            assert r["mids"]["viop"] is None and r["why"]["viop"].startswith("VİOP:"), label
            continue
        (d0, m0), (d1, m1) = next((a, b) for a, b in zip(pts, pts[1:]) if a[0] <= end <= b[0])
        assert r["mids"]["viop"] == pytest.approx(m0 + (m1 - m0) * (end - d0) / (d1 - d0), abs=1e-12), label
    assert rows["1M"]["mids"]["viop"] is not None and rows["ON"]["mids"]["viop"] is None and rows["2Y"]["mids"]["viop"] is None
    # the widths start from the published RET (all on the 5 bp grid in the file)
    st = svc.retfair.state(u)
    assert st["settings"]["widths"] == {"ON": 20, "TN": 20, "1W": 20, "2W": 20, "3W": 20, "1M": 20, "2M": 50, "3M": 50, "4M": 60,
                                        "5M": 60, "6M": 70, "9M": 110, "1Y": 110, "18M": 110, "2Y": 110}
    assert st["width_notes"] == [] and st["log"][-1]["text"].startswith("Genişlikler yayınlanan RET'ten alındı")


def test_offsets_bases_and_the_banner(module_service):
    svc = module_service
    reset(svc)
    u = svc.login("RET Spread")["user"]
    st = svc.retfair.state(u)
    assert all(r["now"] is None for r in st["rows"]) and st["updates"] == []          # no offset yet: nothing computed
    st = svc.retfair.change(u, {"tenors": "all", "from_published": True})
    rows = by_tenor(st["rows"])
    assert all(r["now"] == r["pub"] for r in rows.values()) and st["updates"] == []   # the published RET again, exactly
    assert rows["1M"]["offset"] == round((0.3455 - rows["1M"]["base_mid"]) * 1e4)
    # one base and one offset change: those two tenors differ from the published RET
    st = svc.retfair.change(u, {"tenors": ["1M"], "base": "viop"})
    st = svc.retfair.change(u, {"tenors": ["2M"], "offset": by_tenor(st["rows"])["2M"]["offset"] + 25})
    rows = by_tenor(st["rows"])
    assert st["updates"] == ["1M", "2M"] and svc.retfair.summary()["updates"] == ["1M", "2M"]
    assert svc.status()["ret_fair"]["updates"] == ["1M", "2M"]
    vb = rfv.grid_round(rows["1M"]["mids"]["viop"] * 1e4 + rows["1M"]["offset"] - 10)
    assert rows["1M"]["now"] == {"bid": vb / 1e4, "ask": (vb + 20) / 1e4} and rows["1M"]["formula"].startswith("VİOP mid − ")
    assert rows["2M"]["diff"] == {"bid": 25.0, "ask": 25.0}
    # many at once: a shift for the selected, a value for all
    st = svc.retfair.change(u, {"tenors": ["3M", "4M"], "shift": -5})
    assert by_tenor(st["rows"])["3M"]["diff"]["bid"] == -5.0 and by_tenor(st["rows"])["4M"]["diff"]["bid"] == -5.0
    st = svc.retfair.change(u, {"tenors": ["5M"], "offset": None})
    assert by_tenor(st["rows"])["5M"]["now"] is None
    with pytest.raises(ServiceError):
        svc.retfair.change(u, {"tenors": ["7Y"], "offset": 1})
    with pytest.raises(ServiceError):
        svc.retfair.change(u, {"tenors": ["1M"], "base": "libor"})
    with pytest.raises(ServiceError):
        svc.retfair.change(u, {"tenors": ["1M"], "offset": "abc"})
    with pytest.raises(ServiceError):
        svc.retfair.change(u, {"tenors": ["5M"], "shift": 5})                  # no offset to shift
    # a blend with its weights, and who changed what
    st = svc.retfair.change(u, {"tenors": ["6M"], "base": "blend", "weights": {"ois": 60, "viop": 40, "off": 0}})
    r6 = by_tenor(st["rows"])["6M"]
    assert r6["weights"] == {"ois": 60.0, "viop": 40.0, "off": 0.0}
    assert r6["base_mid"] == pytest.approx(0.6 * r6["mids"]["ois"] + 0.4 * r6["mids"]["viop"])
    texts = [x["text"] for x in st["log"]]
    assert texts[0] == "6M: taban karma (OIS 60 · VİOP 40)" and "1M: taban VİOP mid" in texts
    assert all(x["user"] == u for x in st["log"][:5])
    # the published RET itself did not move
    assert cell(svc, "Forward!W38") == pytest.approx(0.3445)


def test_flow_suggestions_from_planted_trades(module_service, monkeypatch):
    svc = module_service
    reset(svc)
    monkeypatch.setattr(svc, "today_iso", lambda: TODAY)
    u = svc.login("RET Akış")["user"]
    svc.retfair.change(u, {"tenors": "all", "from_published": True})
    days = rfv.lookback_days(_dt.date(2026, 11, 17), 10, set())
    assert days[0] == "2026-11-16" and days[-1] == "2026-11-03"
    for d in days:                                                       # the normal: 120 mn TRY sold a day in 1M
        plant(svc, d, fwd("B", 120e6, 30, 0.340))
    plant(svc, TODAY, fwd("B", 200e6, 30, 0.341, dv01=800.0), fwd("B", 40e6, 30, 0.341, dv01=160.0))
    st = svc.retfair.state(u)
    f = st["flows"]
    assert f["days"] == days and f["lookback"] == 10
    e = by_tenor(f["table"])["1M"]
    assert e["today"]["net"] == pytest.approx(240e6) and e["normal"] == pytest.approx(120e6) and e["ratio"] == pytest.approx(2.0)
    assert e["today"]["cost"] == pytest.approx(0.341) and e["window"]["net"] == pytest.approx(1440e6)
    assert e["vs_ret"] == pytest.approx((0.3445 - 0.341) * 1e4)          # TRY sold: dealt on the bid
    s = f["suggestions"]
    assert [x["id"] for x in s] == ["1M:+"] and s[0]["moves"] == {"1M": 5, "2M": 5}
    assert s[0]["text"] == "1M'de bugün net 240 mn USD TRY sattık (normalin 2 katı), ortalama 34,10 ile; RET bid 34,45 maliyetin 35 bp üstünde → öneri 1M / 2M ask +5 bp"
    # nothing from Broker Chat, OIS or bonds: the same flows after the chat's trades and other trades
    before = svc.retfair.position(u)
    svc.broker_add(u, "10:00:00 fx 1m 12.750 paid\n10:05:00 fx 1m 12.800 given\n10:06:00 1m ois paid 35.10", source="BGC")
    svc.store.add_trade(TODAY, "ois", {"tenor": "1M", "dir": "B", "rate": 0.36, "dv01": 1000.0, "nominal": 1e8, "strategy": "outright"}, u)
    svc.store.add_trade(TODAY, "bond", {"instrument": "TRT150328T24", "amount": 5e7, "price": 100.0}, u)
    assert svc.retfair.position(u) == before
    assert svc.retfair.state(u)["flows"]["suggestions"] == s
    # accepted: a flow adjustment on both tenors - apart from the offset, the width untouched; the suggestion is gone
    offs = {r["tenor"]: (r["offset"], r["width"]) for r in st["rows"]}
    st = svc.retfair.flow(u, {"accept": "1M:+"})
    rows = by_tenor(st["rows"])
    assert rows["1M"]["flow"] == 5.0 and rows["2M"]["flow"] == 5.0 and rows["3W"]["flow"] == 0.0
    assert {t: (r["offset"], r["width"]) for t, r in rows.items()} == offs
    assert rows["1M"]["formula"] == "OIS mid − %d + 5 (akış)" % -rows["1M"]["offset"]
    assert rows["1M"]["now"] == {"bid": 0.345, "ask": 0.347} and rows["2M"]["now"] == {"bid": 0.345, "ask": 0.35}
    assert st["flows"]["suggestions"] == [] and st["updates"] == ["1M", "2M"]
    assert rows["1M"]["flow_log"][0]["by"] == u and rows["1M"]["flow_log"][0]["why"] == s[0]["text"]
    assert st["log"][0]["text"] == "Akış önerisi kabul edildi: " + s[0]["text"]
    with pytest.raises(ServiceError) as err:
        svc.retfair.flow(u, {"accept": "1M:+"})                          # taken already
    assert err.value.status == 409
    # more flow later in the day: only what it adds is suggested
    plant(svc, TODAY, fwd("B", 200e6, 30, 0.342))
    assert [(x["id"], x["moves"]) for x in svc.retfair.state(u)["flows"]["suggestions"]] == [("1M:+", {"1M": 10, "2M": 5})]
    # it stays (the next reading, the next day's flows) until removed - one click each
    assert by_tenor(svc.retfair.state(u)["rows"])["1M"]["flow"] == 5.0
    st = svc.retfair.flow(u, {"remove": "1M"})
    assert by_tenor(st["rows"])["1M"]["flow"] == 0.0 and by_tenor(st["rows"])["2M"]["flow"] == 5.0
    assert by_tenor(st["rows"])["1M"]["now"] == by_tenor(st["rows"])["1M"]["pub"]
    assert st["log"][0]["text"] == "1M: akış ayarı (+5 bp) kaldırıldı"
    with pytest.raises(ServiceError):
        svc.retfair.flow(u, {"remove": "1M"})
    st = svc.retfair.flow(u, {"remove": "2M"})
    assert st["updates"] == []


def test_position_and_cost_panel(module_service, monkeypatch):
    svc = module_service
    reset(svc)
    monkeypatch.setattr(svc, "today_iso", lambda: TODAY)
    u = svc.login("RET Pozisyon")["user"]
    assert svc.retfair.position(u)["rows"] == []
    plant(svc, "2026-11-10", fwd("S", 100e6, 30, 0.350, dv01=-500.0))
    plant(svc, TODAY, fwd("B", 240e6, 30, 0.341, dv01=1000.0), fwd("S", 31e6, 45, 0.35, dv01=-150.0))
    plant(svc, "2026-10-01", fwd("B", 999e6, 30, 0.30))                  # before the lookback: not in it
    p = svc.retfair.position(u)
    assert p["today"] == TODAY and p["lookback"] == 10 and [r["tenor"] for r in p["rows"]] == ["1M", "2M"]
    r = {x["tenor"]: x for x in p["rows"]}["1M"]
    w1 = 16.0 / 31.0
    t = r["today"]
    assert t["sold"] == pytest.approx(240e6) and t["bought"] == pytest.approx(31e6 * w1) and t["cost"] == pytest.approx(0.341)
    ret_mid = (0.3445 + 0.3465) / 2.0
    ret_45 = 0.3455 + (0.3470 - 0.3455) * 15.0 / 31.0                    # the RET mid at 45 days: between 1M and 2M
    ois = by_tenor(svc.retfair.state(u)["rows"])["1M"]["mids"]["ois"]
    assert t["pnl_ret"] == pytest.approx(1000 * (ret_mid - 0.341) * 1e4 - 150 * w1 * (ret_45 - 0.35) * 1e4)
    book = svc.books["tto"]
    ois45 = svc.et.call(lambda: bsp.read_curves(book, book.engine.shared)["ois"].zero(SPOT, SPOT + 45))
    assert t["pnl_ois"] == pytest.approx(1000 * (ois - 0.341) * 1e4 - 150 * w1 * (ois45 - 0.35) * 1e4)
    wnd = r["window"]
    assert wnd["net"] == pytest.approx(240e6 - 31e6 * w1 - 100e6) and wnd["bought"] == pytest.approx(31e6 * w1 + 100e6)
    assert wnd["pnl_ret"] == pytest.approx(t["pnl_ret"] - 500 * (ret_mid - 0.35) * 1e4)
    assert p["total"]["today"]["net"] == pytest.approx(240e6 - 31e6) and p["total"]["window"]["net"] == pytest.approx(240e6 - 131e6)


def test_admin_only_settings(module_service):
    svc = module_service
    reset(svc)
    u = svc.login("RET Kullanıcı")["user"]
    admin = svc.login("RET Yönetici")["user"]
    svc.store.update_account(admin, role="admin")
    st = svc.retfair.state(u)
    assert st["admin"] is False and st["settings"]["hysteresis"] == 2.0                  # seen, read-only
    with pytest.raises(ServiceError) as err:
        svc.retfair.set_settings(u, {"hysteresis": 3})
    assert err.value.status == 403
    assert svc.retfair.state(u)["settings"]["hysteresis"] == 2.0
    svc.retfair.change(u, {"tenors": ["1M"], "from_published": True})
    st = svc.retfair.set_settings(admin, {"hysteresis": 3, "sensitivity": "7,5", "lookback": 5, "margin": 10,
                                          "widths": {"1M": 25}, "blend": {"ois": 70, "viop": 30, "off": 0}})
    s = st["settings"]
    assert (s["hysteresis"], s["sensitivity"], s["lookback"], s["margin"]) == (3.0, 7.5, 5, 10.0) and st["admin"] is True
    assert s["widths"]["1M"] == 25 and s["blend"] == {"ois": 70.0, "viop": 30.0, "off": 0.0}
    r = by_tenor(st["rows"])["1M"]
    assert round((r["now"]["ask"] - r["now"]["bid"]) * 1e4) == 25
    assert st["log"][0]["user"] == admin and "1M genişlik 20 → 25 bp" in st["log"][0]["text"] and "histerezis 2 → 3" in st["log"][0]["text"]
    for bad in ({"widths": {"1M": 23}}, {"widths": {"7Y": 20}}, {"hysteresis": 11}, {"lookback": 0}, {"margin": -1},
                {"blend": {"ois": 0, "viop": 0, "off": 0}}, {"sensitivity": "çok"}):
        with pytest.raises(ServiceError) as err:
            svc.retfair.set_settings(admin, bad)
        assert err.value.status == 400, bad
    assert svc.retfair.state(u)["settings"]["widths"]["1M"] == 25


def test_old_database_publish_and_the_yellow_dot(tmp_path):
    """A desk database of before this version (no fair value table, its RET and history in place) opens with both kept;
    the widths start from its RET (one not on the 5 bp grid is said); "Kopyala ve yayınla" writes the RET, its history
    and clears the "not loaded today" mark; a restart keeps the settings."""
    data = tmp_path / "data"
    data.mkdir()
    db = str(data / "tto.db")
    from tto.store import Store
    old = Store(db)
    old._x("DROP TABLE ret_fair_log")
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat() + " 17:00:00"
    for c, v in (("Forward!W38", 0.34), ("Forward!X38", 0.3423), ("Forward!W39", 0.3445), ("Forward!X39", 0.3495)):
        old._x("INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at) VALUES (?,?,?,?,?)", ("tto", c, str(v), "eski kullanıcı", yesterday))
    old._x("INSERT INTO ret_history (ts, user, payload) VALUES (?,?,?)", (yesterday, "eski kullanıcı", '[{"tenor": "1M", "bid": 0.34, "ask": 0.3423}]'))
    old.close()
    con = sqlite3.connect(db)
    assert "ret_fair_log" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    svc = make_service(data)
    try:
        u = svc.login("RET Yayıncı")["user"]
        assert {r["tenor"]: (r["bid"], r["ask"]) for r in svc.ret()["rows"]}["1M"] == (0.34, 0.3423)       # its RET, kept
        assert len(svc.ret_history()) == 1 and svc.ret_history()[0]["user"] == "eski kullanıcı"
        st = svc.status()
        assert st["ret"]["updated_at"][:10] != st["server_date"]                                       # the yellow dot
        fair = svc.retfair.state(u)
        assert fair["settings"]["widths"]["1M"] == 25 and fair["width_notes"] == ["1M 23 → 25"]
        assert "5 bp'nin katı olmayanlar yuvarlandı: 1M 23 → 25" in fair["log"][0]["text"]
        fair = svc.retfair.change(u, {"tenors": "all", "from_published": True})
        fair = svc.retfair.change(u, {"tenors": ["1M"], "shift": 10})
        rows = by_tenor(fair["rows"])
        assert fair["updates"] == ["1M"]
        new = rows["1M"]["now"]
        curve = [{"tenor": r["tenor"], "bid": (r["now"] or r["pub"])["bid"], "ask": (r["now"] or r["pub"])["ask"]} for r in fair["rows"]]
        out = svc.retfair.publish(u, curve)
        assert out["published"] == 15 and out["updates"] == []
        # the desk's RET: the sheet, the tables that read it (Masa's ORANLAR "RET bid / ask"), the history, the dot
        assert cell(svc, "Forward!W38") == pytest.approx(new["bid"]) and cell(svc, "Forward!X38") == pytest.approx(new["ask"])
        assert cell(svc, "MASA!D10") == pytest.approx(new["bid"]) and cell(svc, "MASA!E10") == pytest.approx(new["ask"])
        hist = svc.ret_history()
        assert len(hist) == 2 and hist[0]["user"] == u and {r["tenor"]: r for r in hist[0]["rows"]}["1M"]["bid"] == pytest.approx(new["bid"])
        st = svc.status()
        assert st["ret"]["updated_by"] == u and st["ret"]["updated_at"][:10] == st["server_date"]
        assert out["log"][0]["kind"] == "yayin" and out["log"][0]["text"].startswith("Kopyala ve yayınla: 1M ")
        with pytest.raises(ServiceError):
            svc.retfair.publish(u, [{"tenor": "1M", "bid": 0.35, "ask": 0.34}])                      # ask below bid
        with pytest.raises(ServiceError):
            svc.retfair.publish(u, [])
        settings = svc.store.get("retfair.desk")
    finally:
        svc.stop()
    again = make_service(data)
    try:
        assert again.store.get("retfair.desk") == settings and len(again.ret_history()) == 2
        assert by_tenor(again.retfair.state(u)["rows"])["1M"]["now"] == new
    finally:
        again.stop()


def test_http(module_service, monkeypatch):
    """The routes (last in the module: the client stops the service when it closes)."""
    from starlette.testclient import TestClient
    from tto.server import create_app
    svc = module_service
    reset(svc)
    monkeypatch.setattr(svc, "today_iso", lambda: TODAY)
    user, admin = auth(svc, "RET HTTP"), auth(svc, "RET HTTP Yönetici", admin=True)
    with TestClient(create_app(svc)) as c:
        res = c.get("/api/ret/fair", headers=user)
        assert res.status_code == 200 and len(res.json()["rows"]) == 15 and res.json()["admin"] is False
        assert c.get("/api/ret/fair", headers=ANON).status_code == 401
        res = c.post("/api/ret/fair/tenors", json={"tenors": ["1M"], "offset": "-50"}, headers=user)
        assert res.status_code == 200 and by_tenor(res.json()["rows"])["1M"]["offset"] == -50.0
        assert c.post("/api/ret/fair/tenors", json={"tenors": ["1M"]}, headers=user).status_code == 400
        assert c.post("/api/ret/fair/settings", json={"hysteresis": 3}, headers=user).status_code == 403
        assert c.post("/api/ret/fair/settings", json={"hysteresis": 3}, headers=admin).json()["settings"]["hysteresis"] == 3.0
        assert c.post("/api/ret/fair/flow", json={"remove": "1M"}, headers=user).status_code == 400
        assert c.post("/api/ret/fair/publish", json={"rows": "x"}, headers=user).status_code == 400
        assert c.get("/api/ret/position", headers=user).json()["rows"] == []
        assert "ret_fair" in c.get("/api/status", headers=user).json()
