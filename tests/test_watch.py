"""Watching the market: the watch list (anything: a VİOP contract, a bond, an OIS or offshore tenor, the desk
strip, an expression of them, any cell; the day's open, high, low, path; the change since the open and since a
reference), alarms on them (≥, ≤, crossing; levels as shown; told once; re-armed), what fired today, the notes."""
from __future__ import annotations

import datetime as _dt
import statistics
import time

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell, make_service
from tto import watch as wt
from tto.server import create_app
from tto.service import ServiceError
from tto.store import user_key


@pytest.fixture()
def svc(tmp_path):
    s = make_service(tmp_path)
    yield s
    s.stop()


def tick(s):
    return s.et.call(s.watch.tick)


def preview(s, user, subject):
    return s.watch_preview(user, subject)


@pytest.fixture()
def clock(monkeypatch):
    """The watch's clock, told by the test (the last minutes of a move)."""
    now = {"t": _dt.datetime.combine(_dt.date.today(), _dt.time(10, 0, 0))}
    monkeypatch.setattr(wt, "_now", lambda: now["t"])
    return now


def at(clock, hhmm):
    h, m = hhmm.split(":")
    clock["t"] = _dt.datetime.combine(_dt.date.today(), _dt.time(int(h), int(m), 0))


def past_days(n):
    """The last n week days before today, oldest first."""
    out, d = [], _dt.date.today()
    while len(out) < n:
        d -= _dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out[::-1]


def seed(s, group, tenor, values):
    """Closes of the market history (as Bloomberg's would be kept) for the last week days."""
    d = s.et.call(s.watch._hist_defs)[(group, tenor)]
    days = past_days(len(values))
    s.store.hist_upsert(d.id, list(zip(days, values)))
    s.history.rev += 1
    return days


def test_expressions_are_read_as_the_desk_writes_them():
    tree = wt.parse_expr("2*[OIS 5Y] - [OIS 2Y] - [OIS 10Y]")
    assert tree == ("-", ("-", ("*", ("num", 2.0), ("name", "OIS 5Y")), ("name", "OIS 2Y")), ("name", "OIS 10Y"))
    assert wt.parse_expr("('DİBS RV'!Z8 + VIOP!M18) / 2,5") == \
        ("/", ("+", ("ref", "'DİBS RV'!Z8"), ("ref", "VIOP!M18")), ("num", 2.5))
    assert wt.parse_expr("-[TLREF] × 2") == ("*", ("neg", ("name", "TLREF")), ("num", 2.0))
    for bad in ("", "[OIS 2Y] -", "([OIS 2Y]", "[OIS 2Y] [OIS 1Y]", "[OIS 2Y] % 2", "OIS 2Y"):
        with pytest.raises(wt.ExprError):
            wt.parse_expr(bad)
    assert wt.fold("VİOP A1Z6 OIS − VİOP") == wt.fold("viop a1z6 ois - viop") == "viop a1z6 ois - viop"
    assert wt.value_text(35.556, "pct") == "35,56%" and wt.value_text(-64.0, "bp") == "-64,0 bp"
    assert wt.value_text(49.99734, "fx") == "49,9973" and wt.value_text(None, "bp") == ""
    assert wt.date_text("30.11.2026") == "30.11.2026" and wt.date_text(46356.0) == "30.11.2026"


def test_what_can_be_watched_and_its_value_now(svc):
    u = svc.login("Konu Bakan")["user"]
    cat = svc.watch_catalog(u)
    assert [c["short"] for c in cat["viop"]][:3] == ["A1X6", "A1Z6", "A1F7"] and cat["viop"][1]["due"] == "31.12.2026"
    assert {m["id"]: m["show"] for m in cat["viop_metrics"]}["ois"] == "bp"
    listed = [b for b in cat["bonds"] if b["listed"]]
    assert {"isin": "TRT150328T24", "label": "15.03.28", "listed": True} in listed and len(cat["bonds"]) >= 77
    assert cat["ois"][:3] == ["TLREF", "1W", "2W"] and "12M" in cat["off"]
    uk = user_key(u)
    # OIS: the par rate in per cent; offshore: the Forward sheet's implied TRY; the desk strip
    p = preview(svc, u, {"kind": "ois", "tenor": "2Y"})
    assert (p["label"], p["show"], p["text"]) == ("OIS 2Y", "pct", "35,85%")
    assert p["value"] == pytest.approx(cell(svc, "OIS_MAIN!B18", user=uk) * 100)
    p = preview(svc, u, {"kind": "off", "tenor": "1M", "side": "bid"})
    assert p["label"] == "Offshore 1M bid" and p["value"] == pytest.approx(cell(svc, "Forward!I10", user=uk))
    assert preview(svc, u, {"kind": "masa", "key": "usdtry_mid"})["text"] == "49,9973"
    # a VİOP contract: OIS − VİOP in bp, the implied TRY rate in per cent; by its ticker or its place
    p = preview(svc, u, {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"})
    assert (p["label"], p["show"], p["text"], p["detail"]) == ("VİOP A1Z6 OIS − VİOP", "bp", "203,2 bp", "vade 31.12.2026")
    assert p["value"] == pytest.approx(cell(svc, "VIOP!N18", user=uk) * 10000)
    mid = preview(svc, u, {"kind": "viop", "ticker": "a1z6", "metric": "try_mid"})
    assert mid["subject"]["ticker"] == "A1Z6 Curncy"
    assert mid["value"] == pytest.approx((cell(svc, "VIOP!N13", user=uk) + cell(svc, "VIOP!N25", user=uk)) * 50)
    first = preview(svc, u, {"kind": "viop", "position": 1, "metric": "ois"})
    assert first["label"] == "VİOP 1. kontrat OIS − VİOP" and first["detail"] == "şu an A1X6, vade 30.11.2026"
    # a bond by its ISIN: DİBS RV's numbers (ASW in bp, the yield in per cent), its prices
    p = preview(svc, u, {"kind": "bond", "isin": "trt150328t24", "metric": "asw"})
    assert (p["label"], p["text"], p["detail"]) == ("15.03.28 ASW", "-64,0 bp", "TRT150328T24")
    assert preview(svc, u, {"kind": "bond", "isin": "TRT150328T24", "metric": "yield"})["text"] == "39,70%"
    assert preview(svc, u, {"kind": "bond", "isin": "TRT150328T24", "metric": "rv"})["value"] == pytest.approx(cell(svc, "DİBS RV!AB8", user=uk))
    off = preview(svc, u, {"kind": "bond", "isin": "TRT060127T10", "metric": "asw"})
    assert off["value"] is None and "trading listesinde değil" in off["detail"]
    # a cell that shows something is taken as that thing; any other stays a cell
    assert preview(svc, u, {"kind": "cell", "book": "tto", "ref": "VIOP!N18"})["subject"] == \
        {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"}
    assert preview(svc, u, {"kind": "cell", "book": "tto", "ref": "DİBS RV!Z8"})["subject"] == \
        {"kind": "bond", "isin": "TRT150328T24", "metric": "asw"}
    assert preview(svc, u, {"kind": "cell", "book": "tto", "ref": "EK_DIBS!F8"})["subject"]["metric"] == "t0_bid"
    assert preview(svc, u, {"kind": "cell", "book": "tto", "ref": "OIS_MAIN!B14"})["subject"] == {"kind": "ois", "tenor": "1Y"}
    assert preview(svc, u, {"kind": "cell", "book": "tto", "ref": "Forward!K12"})["subject"] == {"kind": "off", "tenor": "3M", "side": "ask"}
    plain = preview(svc, u, {"kind": "cell", "book": "tto", "ref": "Forward!F2"})
    assert plain["subject"] == {"kind": "cell", "book": "tto", "ref": "Forward!F2"} and plain["show"] == "raw"
    # what is not there is refused
    for bad in ({"kind": "ois", "tenor": "7M"}, {"kind": "viop", "metric": "ois"}, {"kind": "viop", "ticker": "A1Z6", "metric": "x"},
                {"kind": "bond", "isin": "XX123", "metric": "asw"}, {"kind": "bond", "isin": "TRT150328T24", "metric": "x"},
                {"kind": "cell", "book": "tto", "ref": "YOK!A1"}, {"kind": "expr", "text": "[OIS 2Y] -"},
                {"kind": "expr", "text": "[Yok] + 1"}, {"kind": "expr", "text": "YOK!A1 + 1"}, {"kind": "nope"}, "?"):
        with pytest.raises(ServiceError):
            preview(svc, u, bad)


def test_an_expression_is_told_in_its_unit(svc):
    u = svc.login("İfade Yazan")["user"]

    def p(text):
        x = preview(svc, u, {"kind": "expr", "text": text})
        return x["show"], x["value"]

    o1, o2, o5, o10 = (preview(svc, u, {"kind": "ois", "tenor": t})["value"] for t in ("1Y", "2Y", "5Y", "10Y"))
    assert p("[OIS 2Y] - [OIS 1Y]") == ("bp", pytest.approx((o2 - o1) * 100))                       # a spread
    assert p("2*[OIS 5Y] - [OIS 2Y] - [OIS 10Y]") == ("bp", pytest.approx((2 * o5 - o2 - o10) * 100))  # a fly
    assert p("([OIS 2Y] + [OIS 1Y]) / 2") == ("pct", pytest.approx((o2 + o1) / 2))                   # an average
    assert p("[ois 2y] - 0,25") == ("pct", pytest.approx(o2 - 0.25))
    assert p("[OIS 2Y] / [OIS 1Y]") == ("raw", pytest.approx(o2 / o1))                              # a ratio
    v1 = preview(svc, u, {"kind": "viop", "position": 1, "metric": "ois"})["value"]
    v2 = preview(svc, u, {"kind": "viop", "position": 2, "metric": "ois"})["value"]
    assert p("[VİOP 1. kontrat OIS − VİOP] - [VİOP 2 OIS - VİOP]") == ("bp", pytest.approx(v1 - v2))   # bp stay bp
    assert p("[OIS 2Y] - [VİOP A1X6 OIS − VİOP]")[0] == "raw"                                        # % and bp: a number
    assert p("VIOP!M18 - VIOP!N18") == ("bp", pytest.approx(v1 - v2))                  # cells read as what they show
    a8 = preview(svc, u, {"kind": "bond", "isin": "TRT150328T24", "metric": "asw"})["value"]
    a9 = preview(svc, u, {"kind": "bond", "isin": "TRT130928T38", "metric": "asw"})["value"]
    assert p("[15.03.28 ASW] - [13.09.28 ASW]") == ("bp", pytest.approx(a8 - a9))
    assert p("'DİBS RV'!Z8 - [TRT130928T38 ASW]") == ("bp", pytest.approx(a8 - a9))
    y8 = preview(svc, u, {"kind": "bond", "isin": "TRT150328T24", "metric": "yield"})["value"]
    assert p("[15.03.28 getiri] - [OIS 2Y]") == ("bp", pytest.approx((y8 - o2) * 100))
    assert p("[USDTRY mid] * 2")[0] == "fx" and p("[İma 12A (bp)] + [İma / PPK]")[0] == "bp"


def test_a_watch_list_follows_the_day(svc):
    u = svc.login("İzleyen Masa")["user"]
    assert svc.watch_preset(u, "Masa") == {"added": 5}
    assert svc.watch_preset(u, "TRY OIS eğrisi") == {"added": 9}
    assert svc.watch_add(u, "tto", "OIS_MAIN!B14", "1Y tekrar") == {"added": False, "count": 14}     # it is OIS 1Y: there
    res = svc.watch_add(u, "tto", "DİBS RV!T8", hint="15.03.28 · Getiri")
    assert res["added"] is True and res["item"]["label"] == "15.03.28 getiri"          # named as the desk calls it
    assert svc.watch_add(u, "tto", "Forward!F2", hint="Spot · Bid")["item"]["label"] == "Spot · Bid"    # a cell: its name
    with pytest.raises(ServiceError):
        svc.watch_add(u, "tto", "YOK!A1")
    with pytest.raises(ServiceError):
        svc.watch_preset(u, "Yok")
    tick(svc)
    view = svc.watch_view(u)
    items = {i["label"]: i for i in view["items"]}
    assert list(items)[:3] == ["USDTRY mid", "TLREF", "İma 1Y sonu TLREF"] and len(items) == 16
    one = items["OIS 1Y"]
    assert (one["show"], one["unit_name"], one["now"], one["open_text"], one["change"]) == ("pct", "bp", "35,55%", "35,55%", 0.0)
    assert one["subject"] == {"kind": "ois", "tenor": "1Y"} and one["what"] == "OIS 1Y"
    assert items["USDTRY mid"]["show"] == "fx" and items["İma 12A (bp)"]["show"] == "bp"
    assert items["15.03.28 getiri"]["show"] == "pct" and items["15.03.28 getiri"]["now"] == "39,70%"
    # the market moves (here: 1Y typed over for this user): the change since the open, the day's high, the path
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,05%"}], allow_adhoc=True)
    assert cell(svc, "OIS_MAIN!B14", user=user_key(u)) == pytest.approx(0.3605)
    tick(svc)
    one = {i["label"]: i for i in svc.watch_view(u)["items"]}["OIS 1Y"]
    assert one["change"] == pytest.approx(50.0) and one["high_text"] == "36,05%" and one["low_text"] == "35,55%"
    assert one["path"] == [pytest.approx(35.55), pytest.approx(36.05)] and len(one["moved"]) == 8
    # a reference taken now: the change is told since then as well
    assert svc.watch_base(u, one["id"]) == {"taken": 1}
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "35,95%"}], allow_adhoc=True)
    tick(svc)
    one = {i["label"]: i for i in svc.watch_view(u)["items"]}["OIS 1Y"]
    assert one["since_base"] == pytest.approx(-10.0) and one["change"] == pytest.approx(40.0) and one["base_text"] == "36,05%"
    # someone else's list is their own; the open of the day is kept for a restart
    other = svc.login("Öbür İzleyen")["user"]
    assert svc.watch_view(other)["items"] == []
    assert svc.store.get("watch.open:%s" % svc.today_iso())["%s#ois|tenor=1Y" % u] == pytest.approx(35.55)
    # order, name, removal; how a cell is read (a subject knows its unit: not changed)
    svc.watch_update(u, one["id"], label="1Y OIS", move=-100)
    items = svc.watch_view(u)["items"]
    assert items[0]["label"] == "1Y OIS"
    svc.watch_update(u, items[0]["id"], unit="bp")
    assert svc.watch_view(u)["items"][0]["show"] == "pct"
    spot = next(i for i in items if i["label"] == "Spot · Bid")
    assert spot["show"] == "raw"
    svc.watch_update(u, spot["id"], unit="fx")
    assert next(i for i in svc.watch_view(u)["items"] if i["id"] == spot["id"])["show"] == "fx"
    assert svc.watch_remove(u, items[0]["id"]) == {"removed": 1} and len(svc.watch_view(u)["items"]) == 15
    # a new day starts from its open
    svc.watch.day = "2000-01-01"
    tick(svc)
    assert all(not i["path"] or len(i["path"]) == 1 for i in svc.watch_view(u)["items"])


def test_alarms_fire_once_and_are_told(svc):
    u = svc.login("Alarm Kuran")["user"]
    # typed as shown: 35,80 on a rate in per cent (a cell that shows OIS 1Y is OIS 1Y)
    res = svc.alarm_add(u, "tto", "OIS_MAIN!B14", ">=", "35,80", "1Y yukarı", "35,80 üstünde alıcı yok")
    assert res["already"] is False and res["alarm"]["level"] == pytest.approx(35.8) and res["alarm"]["active"]
    assert res["alarm"]["subject"] == {"kind": "ois", "tenor": "1Y"} and res["text"] == "35,55%"
    down = svc.alarm_add(u, "tto", "OIS_MAIN!B14", "<=", 35.0, "1Y aşağı")["alarm"]
    cross = svc.alarm_add(u, subject={"kind": "ois", "tenor": "1Y"}, op="x", level=35.6, label="1Y 35,60'ı geçer")["alarm"]
    assert svc.alarm_add(u, subject={"kind": "ois", "tenor": "1Y"}, op=">=", level=30)["already"] is True
    with pytest.raises(ServiceError):
        svc.alarm_add(u, "tto", "OIS_MAIN!B14", "==", 35, "?")
    with pytest.raises(ServiceError):
        svc.alarm_add(u, "tto", "OIS_MAIN!B14", ">=", "abc", "?")
    # (the watch loop reads after every change by itself: what fired is asked of the log, not of a tick)
    tick(svc)
    first = svc.alarms_fired(u, 0)
    assert [e["label"] for e in first["fired"]] == ["OIS 1Y"]
    tick(svc)
    assert svc.alarms_fired(u, first["last"])["fired"] == []      # told once
    # the market moves through 35,60 and above 35,80
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "35,90%"}], allow_adhoc=True)
    tick(svc)
    fired = svc.alarms_fired(u, first["last"])["fired"]
    assert sorted(e["label"] for e in fired) == ["1Y 35,60'ı geçer", "1Y yukarı"]
    hit = next(e for e in fired if e["label"] == "1Y yukarı")
    assert (hit["value_text"], hit["level_text"], hit["note"], hit["op"]) == ("35,90%", "35,80%", "35,80 üstünde alıcı yok", ">=")
    assert all(e["seq"] > first["last"] for e in fired)
    view = svc.watch_view(u)
    state = {a["label"]: a for a in view["alarms"]}
    assert state["1Y yukarı"]["active"] is False and state["1Y yukarı"]["fired_text"] == "35,90%"
    assert state["1Y aşağı"]["active"] is True and state["1Y aşağı"]["distance"] == pytest.approx(-90.0)   # bp to go
    assert [e["label"] for e in view["fired"]][-2:] == [e["label"] for e in fired]
    # another user is told nothing of them
    other = svc.login("Başka Masa")["user"]
    assert svc.alarms_fired(other, 0)["fired"] == [] and svc.watch_view(other)["alarms"] == []
    # re-armed (with a new level) it waits again; removed it is gone
    svc.alarm_rearm(u, state["1Y yukarı"]["id"], "36,20")
    a = {x["label"]: x for x in svc.watch_view(u)["alarms"]}["1Y yukarı"]
    assert a["active"] is True and a["level"] == pytest.approx(36.2)
    before = svc.alarms_fired(u, 0)["last"]
    tick(svc)
    assert svc.alarms_fired(u, before)["fired"] == []
    assert svc.alarm_remove(u, down["id"]) == {"removed": 1} and svc.alarm_remove(other, cross["id"]) == {"removed": 0}
    # the watch loop does it on its own after a change
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,30%"}], allow_adhoc=True)
    deadline = time.time() + 15
    while time.time() < deadline and not any(e["label"] == "1Y yukarı" and e["value_text"] == "36,30%"
                                             for e in svc.alarms_fired(u, 0)["fired"]):
        time.sleep(0.2)
    assert any(e["value_text"] == "36,30%" for e in svc.alarms_fired(u, 0)["fired"])


def test_alarms_on_a_viop_spread_a_bond_asw_and_an_expression(svc):
    u = svc.login("Spread İzleyen")["user"]
    viop = {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"}
    up = svc.alarm_add(u, subject=viop, op=">=", level="250", note="OIS − VİOP açılırsa öde")
    assert (up["already"], up["text"], up["alarm"]["label"], up["alarm"]["show"]) == (False, "203,2 bp", "VİOP A1Z6 OIS − VİOP", "bp")
    under = svc.alarm_add(u, subject={"kind": "viop", "position": 2, "metric": "ois"}, op="<=", level="150")["alarm"]
    asw = svc.alarm_add(u, subject={"kind": "bond", "isin": "TRT150328T24", "metric": "asw"}, op="<=", level="-70", label="15.03.28 ASW pahalandı")
    assert (asw["already"], asw["text"]) == (False, "-64,0 bp")
    curve = svc.alarm_add(u, subject={"kind": "expr", "text": "[OIS 2Y] - [OIS 1Y]"}, op="x", level="20", label="1Y2Y düzleşiyor")
    assert (curve["text"], curve["alarm"]["show"]) == ("30,0 bp", "bp")
    with pytest.raises(ServiceError):
        svc.alarm_add(u, subject={"kind": "expr", "text": "[OIS 2Y] - [Yok]"}, op=">=", level="1")
    svc.watch_add(u, subject={"kind": "expr", "text": "[OIS 2Y] - [OIS 1Y]"}, label="1Y2Y")
    svc.watch_add(u, subject=viop)
    tick(svc)
    assert svc.alarms_fired(u, 0)["fired"] == []
    # the market moves: the A1Z6 spread to 262 bp, 15.03.28's ASW to -75, 2Y to 35,60% (1Y2Y: +5 bp)
    svc.set_inputs(u, "tto", [{"ref": "VIOP!N18", "value": "0,0262"}, {"ref": "DİBS RV!Z8", "value": "-75"},
                              {"ref": "OIS_MAIN!B18", "value": "35,60%"}], allow_adhoc=True)
    tick(svc)
    fired = {e["label"]: e for e in svc.alarms_fired(u, 0)["fired"]}
    assert set(fired) == {"VİOP A1Z6 OIS − VİOP", "15.03.28 ASW pahalandı", "1Y2Y düzleşiyor"}
    e = fired["VİOP A1Z6 OIS − VİOP"]
    assert (e["value_text"], e["level_text"], e["note"], e["subject"]) == ("262,0 bp", "250,0 bp", "OIS − VİOP açılırsa öde", viop)
    assert (fired["15.03.28 ASW pahalandı"]["value_text"], fired["15.03.28 ASW pahalandı"]["level_text"]) == ("-75,0 bp", "-70,0 bp")
    assert fired["1Y2Y düzleşiyor"]["value_text"] == "5,0 bp"
    view = svc.watch_view(u)
    items = {i["label"]: i for i in view["items"]}
    assert items["1Y2Y"]["now"] == "5,0 bp" and items["1Y2Y"]["change"] == pytest.approx(-25.0)
    assert items["VİOP A1Z6 OIS − VİOP"]["change"] == pytest.approx(58.8, abs=0.1)
    waiting = {a["id"]: a for a in view["alarms"]}[under["id"]]
    assert waiting["active"] is True and waiting["label"] == "VİOP 2. kontrat OIS − VİOP" and "şu an A1Z6" in waiting["detail"]


def test_subjects_are_followed_when_the_tables_move(svc):
    u = svc.login("Takip Eden")["user"]
    bond = {"kind": "bond", "isin": "TRT150328T24", "metric": "asw"}
    svc.watch_add(u, subject=bond)
    # the bond leaves row 8 for row 40: still the bond (the row itself is priced live; typed over here)
    svc.set_inputs(u, "tto", [{"ref": "DİBS RV!A8", "value": ""}, {"ref": "DİBS RV!A40", "value": "TRT150328T24"},
                              {"ref": "DİBS RV!Z40", "value": "-66"}], allow_adhoc=True)
    assert preview(svc, u, bond)["text"] == "-66,0 bp"
    assert {i["label"]: i for i in svc.watch_view(u)["items"]}["15.03.28 ASW"]["now"] == "-66,0 bp"
    # the contracts roll: A1Z6 is now first - its ticker is followed; the first contract is now A1Z6; A1X6 is gone
    svc.set_inputs(u, "tto", [{"ref": "VIOP!L1", "value": "A1Z6 Curncy"}, {"ref": "VIOP!M1", "value": "A1F7 Curncy"}], allow_adhoc=True)
    uk = user_key(u)
    z6 = preview(svc, u, {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"})
    assert z6["value"] == pytest.approx(cell(svc, "VIOP!M18", user=uk) * 10000)
    assert preview(svc, u, {"kind": "viop", "position": 1, "metric": "ois"})["detail"].startswith("şu an A1Z6")
    gone = preview(svc, u, {"kind": "viop", "ticker": "A1X6 Curncy", "metric": "ois"})
    assert gone["value"] is None and "vadesi geçmiş" in gone["detail"]


def test_lists_of_an_earlier_version_still_read(svc):
    u = svc.login("Eski Liste")["user"]
    svc.store.put("watch.items", {u: [{"id": "old1", "book": "tto", "ref": "OIS_MAIN!B14", "label": "eski 1Y", "unit": "frac",
                                       "base": 0.35, "base_at": "2026-11-12 09:00:00", "fmt": "0.00%"},
                                      {"id": "old2", "book": "tto", "ref": "Forward!F2", "label": "spot", "unit": "fx",
                                       "base": None, "base_at": None, "fmt": "General"}]})
    svc.store.put("watch.alarms", [{"id": "olda", "user": u, "book": "tto", "ref": "OIS_MAIN!B14", "op": ">=", "level": 0.36,
                                    "label": "eski alarm", "note": "", "active": True, "created": "2026-11-12 09:00:00",
                                    "fired_at": None, "fired_value": None, "last": 0.3555, "unit": "frac", "fmt": "0.00%"}])
    view = svc.watch_view(u)
    items = {i["label"]: i for i in view["items"]}
    assert items["eski 1Y"]["now"] == "35,55%" and items["eski 1Y"]["since_base"] == pytest.approx(55.0)
    assert items["spot"]["show"] == "fx" and items["spot"]["now"]
    alarm = view["alarms"][0]
    assert alarm["level_text"] == "36,00%" and alarm["distance"] == pytest.approx(45.0)
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,10%"}], allow_adhoc=True)
    tick(svc)
    e = svc.alarms_fired(u, 0)["fired"][0]
    assert (e["label"], e["value_text"], e["level_text"]) == ("eski alarm", "36,10%", "36,00%")


def test_the_page_over_http_and_the_notes(svc):
    u = svc.login("İzleme HTTP")["user"]
    assert any(p["id"] == "watch" and p["group"] == "Masa" for p in svc.nav())
    hdr = auth(svc, u)
    with TestClient(create_app(svc)) as client:
        assert client.post("/api/watch/preset", json={"group": "Masa"}, headers=hdr).json() == {"added": 5}
        assert client.post("/api/watch/add", json={"book": "tto", "ref": "OIS_MAIN!B18", "label": "2Y"}, headers=hdr).json()["added"] is True
        cat = client.get("/api/watch/catalog", headers=hdr).json()
        assert cat["viop"][0]["short"] == "A1X6" and any(b["isin"] == "TRT150328T24" for b in cat["bonds"])
        assert [g["group"] for g in cat["presets"]] == ["Masa", "TRY OIS eğrisi", "Offshore (FX swap ima)", "VİOP · OIS − VİOP (ilk 4 kontrat)"]
        p = client.post("/api/watch/preview", json={"subject": {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"}}, headers=hdr).json()
        assert (p["label"], p["text"], p["unit"]) == ("VİOP A1Z6 OIS − VİOP", "203,2 bp", "bp")
        assert client.post("/api/watch/preview", json={"book": "tto", "ref": "DİBS RV!Z8"}, headers=hdr).json()["label"] == "15.03.28 ASW"
        bad = client.post("/api/watch/preview", json={"subject": {"kind": "expr", "text": "[OIS 2Y] -"}}, headers=hdr)
        assert bad.status_code == 400 and "yarım" in bad.json()["error"]
        sub = {"kind": "expr", "text": "[OIS 2Y] - [OIS 1Y]"}
        assert client.post("/api/watch/add", json={"subject": sub, "label": "1Y2Y"}, headers=hdr).json()["item"]["label"] == "1Y2Y"
        got = client.get("/api/watch", headers=hdr).json()
        assert [i["label"] for i in got["items"]][-2:] == ["2Y", "1Y2Y"] and got["presets"][0]["group"] == "Masa"
        assert got["items"][-1]["now"] == "30,0 bp" and got["items"][-1]["subject"] == sub
        assert client.post("/api/watch/base", json={}, headers=hdr).json()["taken"] == 7
        res = client.post("/api/alarms/add", json={"book": "tto", "ref": "OIS_MAIN!B18", "op": ">=", "level": "30", "label": "2Y"}, headers=hdr)
        assert res.status_code == 200 and res.json()["already"] is True
        res = client.post("/api/alarms/add", json={"subject": {"kind": "bond", "isin": "TRT150328T24", "metric": "asw"}, "op": "<=",
                                                   "level": "-80,5"}, headers=hdr)
        assert res.status_code == 200 and res.json()["alarm"]["level"] == -80.5 and res.json()["alarm"]["label"] == "15.03.28 ASW"
        assert client.post("/api/alarms/add", json={"book": "tto", "ref": "YOK!A1", "op": ">=", "level": 1}, headers=hdr).status_code == 400
        tick(svc)
        fired = client.get("/api/alarms/fired?since=0", headers=hdr).json()     # (or the watch loop did it already)
        assert [e["label"] for e in fired["fired"]] == ["2Y"] and fired["last"] >= 1
        assert client.get("/api/alarms/fired?since=%d" % fired["last"], headers=hdr).json()["fired"] == []
        alarm = client.get("/api/watch", headers=hdr).json()["alarms"][0]
        assert client.post("/api/alarms/rearm", json={"id": alarm["id"]}, headers=hdr).json()["alarm"]["active"] is True
        assert client.post("/api/alarms/remove", json={"id": alarm["id"]}, headers=hdr).json() == {"removed": 1}
        item = got["items"][0]
        assert client.post("/api/watch/update", json={"id": item["id"], "label": "Spot"}, headers=hdr).status_code == 200
        assert client.post("/api/watch/remove", json={"id": item["id"]}, headers=hdr).json() == {"removed": 1}
        assert client.post("/api/watch/nope", json={}, headers=hdr).status_code == 404
        # the desk's notes of the day: for everyone
        note = client.post("/api/notes", json={"text": "1Y 35,50 üstü alıcı yok"}, headers=hdr).json()
        assert note["text"] == "1Y 35,50 üstü alıcı yok" and note["by"] == u
        other = svc.login("Notu Okuyan")["user"]
        assert client.get("/api/watch", headers=auth(svc, other)).json()["notes"]["text"] == "1Y 35,50 üstü alıcı yok"
        assert client.get("/api/watch").status_code == 401
        assert client.get("/api/watch/catalog").status_code == 401


def test_alarms_on_a_move(svc, clock):
    u = svc.login("Hareket Bekleyen")["user"]
    one = {"kind": "ois", "tenor": "1Y"}

    def typed(text):
        svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": text}], allow_adhoc=True)
        tick(svc)

    tick(svc)                                                     # 10:00: the day's first reading (the open)
    svc.watch_add(u, subject=one)
    opened = svc.alarm_add(u, subject=one, mode="open", op="any", level="15")
    assert (opened["already"], opened["condition"], opened["measure"]) == (False, "açılıştan ± 15,0 bp", 0.0)
    frm = svc.alarm_add(u, subject=one, mode="set", op="up", level="10", label="kurduğumdan 10 yukarı")["alarm"]
    assert frm["base"] == pytest.approx(35.55)
    fast = svc.alarm_add(u, subject=one, mode="window", op="any", level="5", minutes=10, label="hızlı")
    assert fast["condition"] == "10 dk içinde ± 5,0 bp"
    for bad in (dict(mode="window", op="any", level="5", minutes=0), dict(mode="open", op=">=", level="5"),
                dict(mode="open", op="up", level="0"), dict(mode="z", op=">=", level="2", days=30), dict(mode="nope", op="up", level="1")):
        with pytest.raises(ServiceError):
            svc.alarm_add(u, subject=one, **bad)
    tick(svc)
    at(clock, "10:05")
    typed("35,58%")                                               # +3 bp
    assert svc.watch_base(u) == {"taken": 1}                      # the reference: 35,58
    refd = svc.alarm_add(u, subject=one, mode="ref", op="down", level="5", label="referanstan 5 aşağı")
    assert refd["condition"] == "referanstan ↓ 5,0 bp" and refd["measure"] == pytest.approx(0.0)
    at(clock, "10:20")
    typed("35,61%")                                               # 3 bp in the last ten minutes: not yet
    assert svc.alarms_fired(u, 0)["fired"] == []
    at(clock, "10:21")
    typed("35,64%")                                               # from 35,58 (the level at 10:11) to 35,64: 6 bp
    fired = svc.alarms_fired(u, 0)["fired"]
    assert [(e["label"], e["measure_text"], e["condition"]) for e in fired] == [("hızlı", "+6,0 bp", "10 dk içinde ± 5,0 bp")]
    at(clock, "10:30")
    typed("35,71%")                                               # 16 bp from the open and from where it was set
    got = {e["label"]: e for e in svc.alarms_fired(u, 0)["fired"]}
    assert got["OIS 1Y"]["measure_text"] == "+16,0 bp" and got["OIS 1Y"]["value_text"] == "35,71%"
    assert got["kurduğumdan 10 yukarı"]["condition"] == "kurulduğundan (35,55%) ↑ 10,0 bp"
    assert "referanstan 5 aşağı" not in got
    at(clock, "10:40")
    typed("35,50%")                                               # 8 bp below the reference
    got = {e["label"]: e for e in svc.alarms_fired(u, 0)["fired"]}
    assert got["referanstan 5 aşağı"]["measure_text"] == "−8,0 bp"
    # the list: what each condition is, the move now, what is left
    view = {a["label"]: a for a in svc.watch_view(u)["alarms"]}
    assert view["hızlı"]["active"] is False and view["kurduğumdan 10 yukarı"]["measure_text"] == "−5,0 bp"
    # re-armed, "from where it is set" starts from now
    a = svc.alarm_rearm(u, frm["id"])["alarm"]
    assert a["active"] is True and a["base"] == pytest.approx(35.50)
    assert svc.watch_view(u)["items"][0]["open_text"] == "35,55%"


def test_z_scores_and_the_band_of_the_past(svc, monkeypatch):
    u = svc.login("Z Bakan")["user"]
    one = {"kind": "ois", "tenor": "1Y"}
    ones = [35.0 + 0.02 * i for i in range(30)]
    sixes = [36.0 + 0.01 * i for i in range(30)]
    days = seed(svc, "ois", "1Y", ones)
    seed(svc, "ois", "6M", sixes)
    last = ones[-20:]
    p = preview(svc, u, one)
    z20 = (35.55 - statistics.mean(last)) / statistics.stdev(last)
    assert p["z"]["20"]["z"] == pytest.approx(z20) and p["z"]["20"]["n"] == 20 and p["z"]["20"]["source"] == "tarihçe"
    assert p["z"]["60"]["n"] == 30 and p["z"]["250"]["z"] == pytest.approx((35.55 - statistics.mean(ones)) / statistics.stdev(ones))
    # an expression: the same arithmetic on every past day its parts closed (a spread of rates in bp)
    spread = [(a - b) * 100 for a, b in zip(ones, sixes)][-20:]
    now = preview(svc, u, {"kind": "expr", "text": "[OIS 1Y] - [OIS 6M]"})
    assert now["z"]["20"]["z"] == pytest.approx((now["value"] - statistics.mean(spread)) / statistics.stdev(spread))
    # what the history does not keep: the watch's own closes (here written for the past days)
    viop = {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"}
    key = svc.watch.key(viop)
    svc.store.close_upsert([(key, d, 200.0 + (i % 5)) for i, d in enumerate(days[-25:])])
    vz = preview(svc, u, viop)["z"]["20"]
    assert vz["source"] == "kayıt" and vz["n"] == 20 and vz["z"] > 0
    assert preview(svc, u, {"kind": "viop", "ticker": "A1F7 Curncy", "metric": "ois"})["z"]["20"] == \
        {"z": None, "z_text": "", "n": 0, "need": 15, "pct": None, "source": ""}
    # ... kept every day for what is watched (the market's level, whoever watches it) - on a day the market
    # trades (the tests run on any day; a Saturday keeps none: see the test of the days the market is shut)
    svc.watch_add(u, subject=viop)
    monkeypatch.setattr(svc.watch, "market_open", lambda day: True)
    assert svc.et.call(svc.watch.record, True) >= 1
    monkeypatch.undo()
    today = svc.store.closes([key])[key][svc.today_iso()]
    assert today == pytest.approx(preview(svc, u, viop)["value"])
    # the watch list: z and the band over the window asked for
    svc.watch_add(u, subject=one)
    item = {i["label"]: i for i in svc.watch_view(u, days=20)["items"]}["OIS 1Y"]
    assert item["z"]["z"] == pytest.approx(z20) and item["z"]["min"] == pytest.approx(min(last)) and item["z"]["max"] == pytest.approx(max(last))
    assert item["z"]["z_text"] == ("%.2f" % z20).replace(".", ",") and item["z"]["pct"] == pytest.approx(100.0 * sum(x < 35.55 for x in last) / 20)
    # an alarm on the z-score: 2 over the last 20 closes
    za = svc.alarm_add(u, subject=one, mode="z", op=">=", level="2", days=20)
    assert za["already"] is False and za["condition"] == "z(20g) ≥ 2,00"
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "35,70%"}], allow_adhoc=True)
    tick(svc)
    e = next(x for x in svc.alarms_fired(u, 0)["fired"] if x.get("mode") == "z")
    assert e["measure"] == pytest.approx((35.70 - statistics.mean(last)) / statistics.stdev(last)) and e["condition"] == "z(20g) ≥ 2,00"


def test_the_heat_map_of_the_curves(svc, monkeypatch):
    # a week day's map (the tests run on any day; a Saturday or a Sunday: see the test of the days the market is shut)
    monkeypatch.setattr(svc.watch, "shut_day", lambda today: None)
    u = svc.login("Isı Haritası")["user"]
    tick(svc)
    assert not any(user == "" for user, _ in svc.watch.days)          # not read before anyone opens it (Bloomberg hits)
    svc.heat_view(u, "open")
    tick(svc)                                                          # opened: read from now on, the open kept
    assert svc.store.get("watch.open:%s" % svc.today_iso())["#ois|tenor=1Y"] == pytest.approx(35.55)
    h = svc.heat_view(u, "open")
    assert [p["id"] for p in h["panels"]] == ["curve", "viop", "dibs"]
    curve = h["panels"][0]
    cols = [c["id"] for c in curve["cols"]]
    assert cols[:5] == ["O/N", "T/N", "1W", "2W", "1M"] and cols[-1] == "10Y" and len(cols) == 24
    rows = {r["name"]: r["cells"] for r in curve["rows"]}
    assert list(rows) == ["OIS", "Offshore", "Offshore − OIS"]
    one = rows["OIS"][cols.index("1Y")]
    assert one["subject"] == {"kind": "ois", "tenor": "1Y"} and one["now_text"] == "35,55" and one["chg"] == pytest.approx(0.0)
    assert rows["OIS"][cols.index("O/N")]["subject"] == {"kind": "ois", "tenor": "TLREF"} and rows["OIS"][cols.index("T/N")] is None
    assert rows["Offshore"][cols.index("1Y")]["subject"] == {"kind": "off", "tenor": "12M", "side": "mid"}
    basis = rows["Offshore − OIS"][cols.index("1M")]
    assert basis["subject"] == {"kind": "expr", "text": "[Offshore 1M] - [OIS 1M]"} and basis["show"] == "bp"
    assert basis["now"] == pytest.approx((rows["Offshore"][cols.index("1M")]["now"] - rows["OIS"][cols.index("1M")]["now"]) * 100)
    viop = h["panels"][1]
    assert viop["cols"][1] == {"id": "A1Z6 Curncy", "label": "Ara26", "tip": "A1Z6 · vade 31.12.2026"}       # by its month
    assert [c["label"] for c in viop["cols"]][:3] == ["Kas26", "Ara26", "Oca27"]
    assert [r["name"] for r in viop["rows"]] == ["OIS − VİOP", "ima TRY"]
    dibs = h["panels"][2]
    assert [r["name"] for r in dibs["rows"]] == ["getiri", "ASW", "pahalı/ucuz"] and "TRT150328T24" in [c["id"] for c in dibs["cols"]]
    # the market moves: 1Y 12 bp up (the heat map is the market's, not anyone's scenario)
    book = svc.books["tto"]
    si, rc = book.cell("OIS_MAIN!B14")
    svc.et.call(book.engine.set_inputs, {(si, rc): 0.3567})
    h = svc.heat_view(u, "open")
    rows = {r["name"]: r["cells"] for r in h["panels"][0]["rows"]}
    assert rows["OIS"][cols.index("1Y")]["chg"] == pytest.approx(12.0) and rows["OIS"][cols.index("1Y")]["chg_text"] == "+12,0 bp"
    assert rows["Offshore − OIS"][cols.index("1Y")]["chg"] == pytest.approx(-12.0) and h["cap"] >= 12
    # the previous close: the market history's (OIS), the watch's own closes (VİOP)
    yesterday = past_days(1)[0]
    seed(svc, "ois", "1Y", [35.40])
    key = svc.watch.key({"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"})
    svc.store.close_upsert([(key, svc.watch.last_open_day(svc.today_iso()), 200.0)])     # the last day the market traded
    h = svc.heat_view(u, "close")
    one = {r["name"]: r["cells"] for r in h["panels"][0]["rows"]}["OIS"][cols.index("1Y")]
    assert (one["chg"], one["base_day"], one["base_text"]) == (pytest.approx(27.0), yesterday, "35,40%")
    z6 = {r["name"]: r["cells"] for r in h["panels"][1]["rows"]}["OIS − VİOP"][1]
    assert z6["base"] == 200.0 and z6["chg"] == pytest.approx(z6["now"] - 200.0)
    assert h["panels"][0]["rows"][0]["cells"][cols.index("2Y")]["chg"] is None          # no close kept: no change
    # a reference taken now: the moves since then, this user's only
    assert svc.heat_ref(u)["count"] > 50
    svc.et.call(book.engine.set_inputs, {(si, rc): 0.3572})
    h = svc.heat_view(u, "ref")
    assert h["ref_at"] and {r["name"]: r["cells"] for r in h["panels"][0]["rows"]}["OIS"][cols.index("1Y")]["chg"] == pytest.approx(5.0)
    other = svc.login("Başka Isı")["user"]
    h = svc.heat_view(other, "ref")
    assert h["ref_at"] is None and h["panels"][0]["rows"][0]["cells"][cols.index("1Y")]["chg"] is None
    hdr = auth(svc, u)
    with TestClient(create_app(svc)) as client:
        got = client.get("/api/heat?basis=open", headers=hdr).json()
        assert got["basis"] == "open" and got["panels"][0]["id"] == "curve"
        assert client.post("/api/heat/ref", json={}, headers=hdr).json()["count"] > 50
        assert client.get("/api/heat").status_code == 401
        res = client.post("/api/alarms/add", json={"subject": {"kind": "ois", "tenor": "2Y"}, "mode": "window", "op": "up", "level": "4",
                                                   "minutes": "15"}, headers=hdr)
        assert res.status_code == 200 and res.json()["condition"] == "15 dk içinde ↑ 4,0 bp"
        assert client.post("/api/alarms/add", json={"subject": {"kind": "ois", "tenor": "2Y"}, "mode": "window", "op": "up",
                                                    "level": "4"}, headers=hdr).status_code == 400
        got = client.get("/api/watch?days=250", headers=hdr).json()
        assert got["days"] == 250 and got["z_days"] == [20, 60, 250] and got["modes"]["window"] == "son dakikalarda"


def test_a_day_the_market_is_shut(svc, monkeypatch):
    w = svc.watch
    # the market's days: the week days that are not the desk's holidays (the workbook's Motor!A361:A523: 29.10.2026)
    assert w.market_open("2026-11-13") and not w.market_open("2026-11-14") and not w.market_open("2026-11-15")
    assert w.market_open("2026-10-28") and not w.market_open("2026-10-29") and not w.market_open("2026-13-01")
    assert w.last_open_day("2026-11-16") == "2026-11-13" and w.last_open_day("2026-10-30") == "2026-10-28"
    assert (w.shut_day("2026-11-14"), w.shut_day("2026-11-15"), w.shut_day("2026-11-16"), w.shut_day("2026-10-29")) == \
        ("2026-11-13", "2026-11-13", None, None)              # a holiday is no weekend: offshore trades in London
    u = svc.login("Hafta Sonu")["user"]
    viop = {"kind": "viop", "ticker": "A1Z6 Curncy", "metric": "ois"}
    key = w.key(viop)
    svc.watch_add(u, subject=viop)
    # a Saturday keeps no close of its own, even when asked
    monkeypatch.setattr(svc, "today_iso", lambda: "2026-11-14")
    assert svc.et.call(w.record, True) == 0 and not svc.store.closes([key]).get(key)
    # ... and one kept on a Saturday by an earlier version is no close: Monday's previous close is Friday's
    svc.store.close_upsert([(key, "2026-11-12", 190.0), (key, "2026-11-13", 200.0), (key, "2026-11-14", 250.0)])
    d = svc.et.call(w._hist_defs)[("ois", "1Y")]
    svc.store.hist_upsert(d.id, [("2026-11-12", 35.30), ("2026-11-13", 35.40)])
    svc.history.rev += 1
    monkeypatch.setattr(svc, "today_iso", lambda: "2026-11-16")
    assert sorted(svc.et.call(w.history, viop)[0]) == ["2026-11-12", "2026-11-13"]

    def points(h):
        cols = [c["id"] for c in h["panels"][0]["cols"]]
        curve = {r["name"]: r["cells"] for r in h["panels"][0]["rows"]}
        viops = {r["name"]: r["cells"] for r in h["panels"][1]["rows"]}
        return curve["OIS"][cols.index("1Y")], viops["OIS − VİOP"][1], curve["OIS"][cols.index("2Y")]

    h = svc.heat_view(u, "close")
    one, z6, _ = points(h)
    assert h["closed"] is None and (one["base_day"], one["base"]) == ("2026-11-13", 35.40) and one["chg"] == pytest.approx(15.0)
    assert (z6["base_day"], z6["base"]) == ("2026-11-13", 200.0) and z6["chg"] == pytest.approx(z6["now"] - 200.0)
    # a Sunday (a Saturday the same): the market is shut - Friday's close stands and nothing has moved, whatever is read
    # now (the live 35,55 here; a bond's yield priced to another value date)
    for day in ("2026-11-15", "2026-11-14"):
        monkeypatch.setattr(svc, "today_iso", lambda day=day: day)
        h = svc.heat_view(u, "close")
        one, z6, two = points(h)
        assert h["closed"] == "2026-11-13"
        assert (one["base_day"], one["now"], one["chg"], one["now_text"]) == ("2026-11-13", 35.40, 0.0, "35,40")
        assert (z6["base_day"], z6["now"], z6["chg"]) == ("2026-11-13", 200.0, 0.0)
        assert two["chg"] is None and type(two["now"]) is float      # no close kept for it: read as it is, no change


def test_a_user_away_is_read_from_what_everybody_sees_and_one_here_at_most_every_few_seconds(svc):
    """A user with inputs of their own has a calculation of their own.  While they are here (a request or a live
    stream lately) their list is read from it - for a market change at most every ``private_refresh`` seconds, for
    their own change at once.  While they are away it is read from what everybody sees (their own calculation is not
    made again for a list nobody looks at): a subject their own inputs decide is not read then."""
    u = svc.login("Uzaktaki")["user"]
    svc.watch_add(u, "tto", "OIS_MAIN!B14", "1Y")                       # their own value below
    svc.watch_add(u, "tto", "DİBS RV!T8", hint="15.03.28 · Getiri")     # nothing of theirs
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,05%"}], allow_adhoc=True)
    tick(svc)
    items = {i["label"]: i for i in svc.watch_view(u)["items"]}
    assert items["1Y"]["now"] == "36,05%"
    # a market change right after: their own calculation is not read again yet; their own change is
    svc.settings.private_refresh = 60.0
    calc = svc.books["tto"].engine.user(u)
    evals = calc.evals
    svc.et.call(svc.books["tto"].engine.invalidate, 1 << 60)            # (a tick of nothing)
    tick(svc)
    assert calc.evals == evals
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,15%"}], allow_adhoc=True)
    tick(svc)
    assert {i["label"]: i for i in svc.watch_view(u)["items"]}["1Y"]["now"] == "36,15%"
    # away: given back after a while; read from everybody's calculation, without theirs
    svc._seen[u] = -1e9
    svc.settings.idle_minutes = 0.001
    assert u in svc.et.call(svc._sweep_idle) and u not in svc.books["tto"].engine.users
    key = (u, svc.watch.key(items["1Y"]["subject"]))
    svc.watch.days[key]["last"] = 1.0                                   # (as if read long ago)
    tick(svc)
    assert u not in svc.books["tto"].engine.users                        # (not made again for the list)
    assert svc.watch.days[key]["last"] == 1.0                            # their own value decides it: not read
    other = (u, svc.watch.key(items["15.03.28 getiri"]["subject"]))
    assert svc.watch.days[other]["last"] == pytest.approx(39.70, abs=0.01)    # nothing of theirs: read
    # back: their own calculation is made again, with their value
    assert cell(svc, "OIS_MAIN!B14", user=u) == pytest.approx(0.3615)
    view = {i["label"]: i for i in svc.watch_view(u)["items"]}
    assert view["1Y"]["now"] == "36,15%" and view["15.03.28 getiri"]["now"] == "39,70%"
