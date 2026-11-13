"""Watching the market: the watch list (any cell; the day's open, high, low, path; the change since the open and
since a reference), alarms on cells (≥, ≤, crossing; told once; re-armed), what fired today, the desk's notes."""
from __future__ import annotations

import time
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from conftest import cell, make_service
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


def test_the_unit_of_a_change():
    assert wt.Watch.guess_unit(0.3555, True) == "frac"            # a cell in per cent: bp = × 10 000
    assert wt.Watch.guess_unit(35.55, False) == "pct"             # a rate written in per cent: bp = × 100
    assert wt.Watch.guess_unit(49.9973, False) == "pct" and wt.Watch.guess_unit(102.5, False) == "px"
    assert wt.Watch.as_value(35.5, True) == pytest.approx(0.355) and wt.Watch.as_value(0.355, True) == 0.355
    assert wt.Watch.as_value(35.5, False) == 35.5


def test_a_watch_list_follows_the_day(svc):
    u = svc.login("İzleyen Masa")["user"]
    assert svc.watch_preset(u, "Masa") == {"added": 5}
    assert svc.watch_preset(u, "TRY OIS eğrisi") == {"added": 9}
    assert svc.watch_add(u, "tto", "OIS_MAIN!B14", "1Y tekrar") == {"added": False, "count": 14}     # already there
    assert svc.watch_add(u, "tto", "DİBS RV!T8", "15.03.28 getiri")["added"] is True
    with pytest.raises(ServiceError):
        svc.watch_add(u, "tto", "YOK!A1")
    with pytest.raises(ServiceError):
        svc.watch_preset(u, "Yok")
    tick(svc)
    view = svc.watch_view(u)
    items = {i["label"]: i for i in view["items"]}
    assert list(items)[:3] == ["USDTRY mid", "TLREF", "İma 1Y sonu TLREF"] and len(items) == 15
    one = items["OIS 1Y"]
    assert (one["unit"], one["unit_name"], one["now"], one["open_text"], one["change"]) == ("frac", "bp", "35,55%", "35,55%", 0.0)
    assert items["USDTRY mid"]["unit"] == "fx" and items["İma 12A (bp)"]["unit"] == "bp"
    assert items["15.03.28 getiri"]["unit"] == "frac" and items["15.03.28 getiri"]["now"] == "39,70%"
    # the market moves (here: 1Y typed over for this user): the change since the open, the day's high, the path
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,05%"}], allow_adhoc=True)
    assert cell(svc, "OIS_MAIN!B14", user=user_key(u)) == pytest.approx(0.3605)
    tick(svc)
    one = {i["label"]: i for i in svc.watch_view(u)["items"]}["OIS 1Y"]
    assert one["change"] == pytest.approx(50.0) and one["high_text"] == "36,05%" and one["low_text"] == "35,55%"
    assert one["path"] == [pytest.approx(0.3555), pytest.approx(0.3605)] and len(one["moved"]) == 8
    # a reference taken now: the change is told since then as well
    assert svc.watch_base(u, one["id"]) == {"taken": 1}
    svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "35,95%"}], allow_adhoc=True)
    tick(svc)
    one = {i["label"]: i for i in svc.watch_view(u)["items"]}["OIS 1Y"]
    assert one["since_base"] == pytest.approx(-10.0) and one["change"] == pytest.approx(40.0) and one["base_text"] == "36,05%"
    # someone else's list is their own; the open of the day is kept for a restart
    other = svc.login("Öbür İzleyen")["user"]
    assert svc.watch_view(other)["items"] == []
    assert svc.store.get("watch.open:%s" % svc.today_iso())["%s|tto|OIS_MAIN!B14" % u] == pytest.approx(0.3555)
    # order, name, unit, removal
    svc.watch_update(u, one["id"], label="1Y OIS", move=-100)
    items = svc.watch_view(u)["items"]
    assert items[0]["label"] == "1Y OIS"
    svc.watch_update(u, items[0]["id"], unit="pct")
    assert svc.watch_view(u)["items"][0]["unit"] == "pct"
    assert svc.watch_remove(u, items[0]["id"]) == {"removed": 1} and len(svc.watch_view(u)["items"]) == 14
    # a new day starts from its open
    svc.watch.day = "2000-01-01"
    tick(svc)
    assert all(not i["path"] or len(i["path"]) == 1 for i in svc.watch_view(u)["items"])


def test_alarms_fire_once_and_are_told(svc):
    u = svc.login("Alarm Kuran")["user"]
    # typed as the cell shows it: 35,80 on a cell in per cent is 0.358
    res = svc.alarm_add(u, "tto", "OIS_MAIN!B14", ">=", "35,80", "1Y yukarı", "35,80 üstünde alıcı yok")
    assert res["already"] is False and res["alarm"]["level"] == pytest.approx(0.358) and res["alarm"]["active"]
    down = svc.alarm_add(u, "tto", "OIS_MAIN!B14", "<=", 35.0, "1Y aşağı")["alarm"]
    cross = svc.alarm_add(u, "tto", "OIS_MAIN!B14", "x", 35.6, "1Y 35,60'ı geçer")["alarm"]
    assert svc.alarm_add(u, "tto", "OIS_MAIN!B14", ">=", 30, "hemen")["already"] is True
    with pytest.raises(ServiceError):
        svc.alarm_add(u, "tto", "OIS_MAIN!B14", "==", 35, "?")
    with pytest.raises(ServiceError):
        svc.alarm_add(u, "tto", "OIS_MAIN!B14", ">=", "abc", "?")
    # (the watch loop reads the cells after every change by itself: what fired is asked of the log, not of a tick)
    tick(svc)
    first = svc.alarms_fired(u, 0)
    assert [e["label"] for e in first["fired"]] == ["hemen"]
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
    assert a["active"] is True and a["level"] == pytest.approx(0.362)
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


def test_the_page_over_http_and_the_notes(svc):
    u = svc.login("İzleme HTTP")["user"]
    assert any(p["id"] == "watch" and p["group"] == "Masa" for p in svc.nav())
    with TestClient(create_app(svc)) as client:
        hdr = {"X-TTO-User": quote(u)}
        assert client.post("/api/watch/preset", json={"group": "Masa"}, headers=hdr).json() == {"added": 5}
        assert client.post("/api/watch/add", json={"book": "tto", "ref": "OIS_MAIN!B18", "label": "2Y"}, headers=hdr).json()["added"] is True
        got = client.get("/api/watch", headers=hdr).json()
        assert [i["label"] for i in got["items"]][-1] == "2Y" and got["presets"][0]["group"] == "Masa"
        assert client.post("/api/watch/base", json={}, headers=hdr).json()["taken"] == 6
        res = client.post("/api/alarms/add", json={"book": "tto", "ref": "OIS_MAIN!B18", "op": ">=", "level": "30", "label": "2Y"}, headers=hdr)
        assert res.status_code == 200 and res.json()["already"] is True
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
        assert client.get("/api/watch", headers={"X-TTO-User": quote(other)}).json()["notes"]["text"] == "1Y 35,50 üstü alıcı yok"
        assert client.get("/api/watch").status_code == 401
