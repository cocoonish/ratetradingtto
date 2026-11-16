"""The boxes of the dashboard's own pages on a launchpad, in the side drawer and in a window of its own - their item
checks (``tto/layout.py``) and the light parts of their pages they read (``/api/quant/box``, ``/api/broker?part=board``,
``/api/watch?part=``) -, the quant menu's four entries with tabs (``/api/nav``) and each user's own menu (``hidden_pages``).
(The boxes on screen, the tabs and "Menüyü düzenle" are the browser test's; the quant boxes' numbers: test_quant.py.)"""
import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto import layout as lay
from tto import quant as qmod
from tto.server import create_app
from tto.service import ServiceError


def login(svc, name):
    return svc.login(name)["user"]


# ---------------------------------------------------------------------------------------------- the items
def test_each_box_keeps_the_options_its_page_has(service):
    u = login(service, "Kutu Ayşe")
    items = [{"type": "quant-signals", "family": "pca", "asset": " TRY  OIS ", "open": "page", "w": 12},
             {"type": "quant-signals"},
             {"type": "viop-levels"}, {"type": "viop-levels", "contract": "A1Z6 Curncy", "h": 360},
             {"type": "viop-contracts", "view": "x", "panel": "y"},
             {"type": "broker-board", "product": "OIS", "keys": ["OIS:outright:18M", "OIS:spread:1Y/5Y", "OIS:outright:18M"], "brokers": True},
             {"type": "broker-board", "brokers": "evet"},
             {"type": "watch-list", "list": "alarms", "title": " Alarmlarım ", "collapsed": True},
             {"type": "wirp", "bank": "usd", "w": 4}, {"type": "fx-summary", "w": 8}]
    got = service.set_layout(u, {"launchpads": [{"name": "Kutular", "items": items}], "drawer": [dict(items[2], w=12)]})
    out = [{k: v for k, v in it.items() if k != "id"} for it in got["launchpads"][0]["items"]]
    assert out == [
        {"type": "quant-signals", "family": "pca", "asset": "TRY OIS", "open": "page", "w": 12, "h": "auto"},
        {"type": "quant-signals", "w": 6, "h": "auto"},
        {"type": "viop-levels", "contract": "front", "w": 6, "h": "auto"},                      # (the front, rolling with it)
        {"type": "viop-levels", "contract": "A1Z6 Curncy", "w": 6, "h": 360},
        {"type": "viop-contracts", "w": 6, "h": "auto"},                                         # (a table's fields are not its)
        {"type": "broker-board", "product": "OIS", "keys": ["OIS:outright:18M", "OIS:spread:1Y/5Y"], "brokers": True, "w": 6, "h": "auto"},
        {"type": "broker-board", "w": 6, "h": "auto"},
        {"type": "watch-list", "list": "alarms", "title": "Alarmlarım", "w": 6, "h": "auto", "collapsed": True},
        {"type": "wirp", "bank": "usd", "w": 4, "h": "auto"}, {"type": "fx-summary", "w": 8, "h": "auto"}]
    assert got["drawer"][0]["type"] == "viop-levels" and got["drawer"][0]["w"] == 12
    # kept as they are: read back, and through a change of another part
    assert service.layout(u)["launchpads"] == got["launchpads"]
    assert service.set_layout(u, {"favs": ["quant-viop"]})["launchpads"] == got["launchpads"]
    # a launchpad of boxes goes out as a file and comes back as it was
    import json
    raw, _ = service.export_launchpad(u, "Kutular")
    assert service.import_launchpad(u, json.loads(raw.decode("utf-8")))["layout"]["launchpads"][1]["items"] == got["launchpads"][0]["items"]


@pytest.mark.parametrize("bad", [
    {"type": "quant-signals", "family": "PCA!"}, {"type": "quant-signals", "family": 3}, {"type": "quant-signals", "asset": 5},
    {"type": "quant-signals", "asset": "x" * 41}, {"type": "quant-signals", "open": "popup"},
    {"type": "viop-levels", "contract": "A1Z6\nCurncy"}, {"type": "viop-levels", "contract": 5}, {"type": "viop-levels", "contract": "../x"},
    {"type": "broker-board", "product": "ois"}, {"type": "broker-board", "keys": "OIS:outright:18M"},
    {"type": "broker-board", "keys": [""]}, {"type": "broker-board", "keys": ["x" * 81]}, {"type": "broker-board", "keys": [3]},
    {"type": "broker-board", "keys": ["k%d" % i for i in range(61)]},
    {"type": "watch-list", "list": "desk"}, {"type": "wirp", "bank": "ecb"}, {"type": "fx-summary", "w": 5},
    {"type": "viop-contracts", "h": 10},
])
def test_what_a_box_cannot_be_is_refused(service, bad):
    u = login(service, "Kutu Hatalı")
    with pytest.raises(ServiceError) as err:
        service.set_layout(u, {"launchpads": [{"name": "A", "items": [bad]}]})
    assert err.value.status == 400
    assert service.layout(u)["rev"] == 0


def test_a_box_this_version_does_not_know_is_left_out_by_itself(service):
    """A box another version saved (a kind this one does not know, an option it does not take) is left out of what is
    read - the boxes and tables beside it stay."""
    u = login(service, "Kutu Eski")
    good = {"type": "wirp", "id": "w1", "bank": "try", "w": 6, "h": "auto"}
    table = {"type": "table", "id": "t1", "view": "forward", "panel": "B1", "w": 6, "h": "auto"}
    service.store.put("layout." + u, {"launchpads": [{"name": "A", "items": [good, {"type": "wirp", "bank": "boe"}, table,
                                                                             {"type": "yarın-gelecek-kutu"}]}], "rev": 3})
    assert service.layout(u)["launchpads"] == [{"name": "A", "items": [good, table]}]


# ---------------------------------------------------------------------------------------------- the user's own menu
def test_each_user_takes_pages_out_of_their_own_menu(service):
    u = login(service, "Menü Ayşe")
    v = login(service, "Menü Mehmet")
    assert service.layout(u)["hidden_pages"] == []
    got = service.set_layout(u, {"hidden_pages": ["heat", "quant.faiz", "heat", "users"]})
    assert got["hidden_pages"] == ["heat", "quant.faiz", "users"] and got["rev"] == 1
    # the other parts stay, and a change of another part keeps the list
    assert service.set_layout(u, {"favs": ["forward"]})["hidden_pages"] == ["heat", "quant.faiz", "users"]
    assert service.layout(v)["hidden_pages"] == []                                   # one user's menu is nobody else's
    assert service.set_layout(u, {"hidden_pages": []})["hidden_pages"] == []
    # (a page hidden from the menu is still the user's to open: the nav and the pages do not change)
    assert any(p["id"] == "heat" for p in service.nav(u))
    for bad in ("heat", [3], ["a b"], ["x" * 41], ["p%d" % i for i in range(lay.MAX_HIDDEN + 1)], None):
        with pytest.raises(ServiceError) as err:
            service.set_layout(u, {"hidden_pages": bad})
        assert err.value.status == 400
    # read leniently: what another version wrote that is not a page's id is left out
    service.store.put("layout." + v, {"hidden_pages": ["heat", "a b", 3, "heat", "quant.fx"], "rev": 2})
    assert service.layout(v)["hidden_pages"] == ["heat", "quant.fx"]


# ---------------------------------------------------------------------------------------------- the quant menu
def test_the_quant_pages_are_four_menu_entries_with_tabs(service):
    u = login(service, "Menü Quant")
    quant = [p for p in service.nav(u) if p["group"] == "Quant"]
    assert len(quant) == len(qmod.PAGES) == 16 and len({p["id"] for p in quant}) == 16
    entries = []
    for p in quant:
        key = p.get("menu") or p["id"]
        if not entries or entries[-1][0] != key:
            entries.append((key, p.get("menu_title") or p["title"], []))
        entries[-1][2].append((p["id"], p.get("tab")))
    assert [(k, t) for k, t, _ in entries] == [("quant.sinyal", "Sinyaller"), ("quant.faiz", "Faiz"), ("quant.fx", "FX"), ("quant-viop", "VİOP")]
    tabs = {k: [x for x, _ in pages] for k, _, pages in entries}
    assert tabs["quant.sinyal"] == ["quant", "quant-intraday", "quant-model", "quant-ml"]
    assert tabs["quant.faiz"] == ["quant-pca", "quant-pairs", "quant-corr", "quant-regime", "quant-curve", "quant-path", "quant-wirp", "quant-lead"]
    assert tabs["quant.fx"] == ["quant-fx", "quant-macro", "quant-opt"] and tabs["quant-viop"] == ["quant-viop"]
    names = {pid: tab for _, _, pages in entries for pid, tab in pages}
    assert [names[x] for x in tabs["quant.faiz"]] == ["PCA / RV", "Çiftler", "Korelasyon", "Rejim", "Eğri Adil Değeri", "İma Patikası",
                                                      "TCMB WIRP", "Öncü-Takipçi"]
    assert [names[x] for x in tabs["quant.sinyal"] + tabs["quant.fx"]] == ["Sinyaller", "Gün içi", "Model", "Makine öğrenmesi", "FX", "Makro", "Opsiyon"]
    # a page keeps its own title (Ctrl+K finds it by it) and its address; VİOP is an entry of one page
    by = {p["id"]: p for p in quant}
    assert by["quant-regime"]["title"] == "Rejim & Momentum" and by["quant-fx"]["title"] == "FX Vol Primi & Carry"
    assert "menu" not in by["quant-viop"] and by["quant-viop"]["title"] == "VİOP"


def test_a_quant_page_the_menu_does_not_name_comes_as_an_entry_of_its_own(service, monkeypatch):
    monkeypatch.setattr(qmod, "PAGES", qmod.PAGES + (("quant-yeni", "Yeni Analiz"),))
    pages = service.quant.pages()
    assert pages[-1] == {"id": "quant-yeni", "title": "Yeni Analiz", "group": "Quant", "book": "tto", "sheet": None, "custom": True}
    assert len(pages) == 17


# ---------------------------------------------------------------------------------------------- what the boxes read
def test_a_quant_box_before_the_first_result_and_an_unknown_one(service, monkeypatch):
    u = login(service, "Kutu Quant")
    monkeypatch.setattr(service.quant, "_view", None)
    for of in qmod.Quant.BOXES:
        got = service.quant.view("box", u, {"of": of})
        assert got["of"] == of and got["ready"] is False and isinstance(got["version"], int) and "signals" not in got
    for of in ("", "pca", "../x"):
        with pytest.raises(ServiceError) as err:
            service.quant.view("box", u, {"of": of})
        assert err.value.status == 400


CHAT = ("12:15:38 18m ois 35.03/35.23\n12:16:02 2y ois 35.40/35.60\n12:16:30 1yr x 38.60/80\n"
        "12:17:01 t/n 375/90\n12:18:00 18m ois taken at 23")


def test_the_board_alone_is_the_pages_board(module_service):
    svc = module_service
    u = login(svc, "Kutu Broker")
    svc.broker_add(u, CHAT, source="Tullett", party="broker")
    full = svc.broker(u)
    board = svc.broker(u, part="board")

    def still(rows):                                  # (a quote's age is read with the clock: it moves between two reads)
        return [{k: [still([b])[0] for b in v] if k == "brokers" else v for k, v in r.items() if not k.endswith("_age")} for r in rows]

    assert still(board["board"]) == still(full["board"]) and len(board["board"]) >= 4
    assert {r["product"] for r in board["board"]} >= {"OIS", "XCCY", "FX"}
    assert board["live"] is True and board["stale_minutes"] == full["stale_minutes"] and board["date"] == full["date"]
    # the lines, the days and the trades not entered are the page's: not read for a box
    assert not {"rows", "dates", "unbooked", "resets"} & set(board)
    with pytest.raises(ServiceError) as err:
        svc.broker(u, part="log")
    assert err.value.status == 400
    # Broker Chat's own changes are counted (the live stream carries the count: the board's box asks again on it, not on
    # every generation of the market); the board says the count it was made at
    n = svc.broker_changes
    assert board["changes"] == n >= 1
    gen = svc.gen
    svc.bump(market=True)
    assert svc.broker_changes == n and svc.gen > gen
    svc.broker_settings(u, 30)
    svc.broker_reset(u)
    svc.broker_delete(u, next(q["id"] for q in full["rows"] if q.get("ok")))
    assert svc.broker_changes == n + 3 and svc.broker(u, part="board")["changes"] == n + 3
    svc.broker_settings(u, 10)


def test_one_list_of_the_watch_page_alone(module_service):
    svc = module_service
    u = login(svc, "Kutu İzleyen")
    svc.watch_preset(u, "Masa")
    svc.alarm_add(u, subject={"kind": "ois", "tenor": "1Y"}, op=">=", level="99", label="1Y yüksek")
    full = svc.watch_view(u)
    items = svc.watch_view(u, part="items")
    assert [i["label"] for i in items["items"]] == [i["label"] for i in full["items"]] and len(items["items"]) == 5
    assert items["items"][0]["now"] == full["items"][0]["now"] and items["days"] == 60 and "alarms" not in items
    alarms = svc.watch_view(u, part="alarms")
    assert [a["label"] for a in alarms["alarms"]] == ["1Y yüksek"] and alarms["alarms"] == full["alarms"] and "items" not in alarms
    fired = svc.watch_view(u, part="fired")
    assert fired["fired"] == full["fired"] and set(fired) == {"fired", "day", "gen"}
    # (the desk's alarms and the notes are the page's)
    assert all("desk" not in x and "notes" not in x for x in (items, alarms, fired)) and "desk" in full
    with pytest.raises(ServiceError) as err:
        svc.watch_view(u, part="desk")
    assert err.value.status == 400


# ---------------------------------------------------------------------------------------------- over HTTP
def test_over_http(module_service):
    svc = module_service
    client = TestClient(create_app(service=svc))                      # (no "with": the module's service stays up)
    for path in ("/static/js/pagebox.js", "/static/js/pageboxes.js", "/static/js/menu.js"):
        assert client.get(path).status_code == 200, path
    h = auth(svc, "Kutu HTTP")
    r = client.get("/api/broker", params={"part": "board"}, headers=h)
    assert r.status_code == 200 and "board" in r.json() and "rows" not in r.json()
    assert client.get("/api/broker", params={"part": "x"}, headers=h).status_code == 400
    r = client.get("/api/watch", params={"part": "alarms"}, headers=h)
    assert r.status_code == 200 and r.json()["alarms"] == [] and "items" not in r.json()
    assert client.get("/api/watch", params={"part": "x"}, headers=h).status_code == 400
    r = client.get("/api/quant/box", params={"of": "signals"}, headers=h)
    assert r.status_code == 200 and r.json()["of"] == "signals"
    assert client.get("/api/quant/box", params={"of": "x"}, headers=h).status_code == 400
    assert client.get("/api/quant/box", params={"of": "signals"}, headers=ANON).status_code == 401
    r = client.post("/api/layout", json={"hidden_pages": ["heat"], "drawer": [{"type": "viop-contracts"}]}, headers=h)
    assert r.status_code == 200 and r.json()["hidden_pages"] == ["heat"] and r.json()["drawer"][0]["type"] == "viop-contracts"
    nav = client.get("/api/nav", headers=h).json()["pages"]
    assert [p["id"] for p in nav if p.get("menu") == "quant.fx"] == ["quant-fx", "quant-macro", "quant-opt"]
