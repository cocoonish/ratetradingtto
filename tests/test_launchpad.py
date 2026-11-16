"""Launchpads, the side drawer, the favourite pages and the page the dashboard opens on - kept with each user's account
(``tto/layout.py``) - and the request that brings the tables of many pages at once (``POST /api/panels``).
(The pages themselves, the pop-out window and the drawer on screen are the browser test's.)"""
import copy
import json

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, make_service
from tto import layout as lay
from tto.server import create_app
from tto.service import ServiceError, _pick_part, _row_label


def login(svc, name, admin=False):
    key = svc.login(name)["user"]
    if admin:
        svc.store.update_account(key, role="admin")
    return key


def page_panel(svc, user, view, pid):
    return next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)


def texts(data):
    return [[c.get("t") for c in row] for row in data["rows"]]


# ---------------------------------------------------------------------------------------------- tables of many pages
def test_tables_of_several_pages_come_in_one_answer_keyed_by_page_and_table(service):
    """One request, the tables of any pages: each as its own page draws it, keyed by "page/table" - panel ids repeat
    across pages (B1 of Forward is not B1 of DİBS RV)."""
    u = login(service, "Lp Okur")
    forward = [p["id"] for p in service.view(u, "forward")["panels"]]
    dibs = [p["id"] for p in service.view(u, "dibs")["panels"]]
    twin = next(pid for pid in forward if pid in dibs and pid not in ("B1", "B3", "B19"))
    items = [{"view": "forward", "panel": "B1"}, {"view": "dibs", "panel": "B3"}, {"view": "forward", "panel": "B19"},
             {"view": "forward", "panel": twin}, {"view": "dibs", "panel": twin}]
    got = service.panels(u, items)["panels"]
    assert set(got) == {"forward/B1", "dibs/B3", "forward/B19", "forward/" + twin, "dibs/" + twin}
    for it in items:
        ans = got["%s/%s" % (it["view"], it["panel"])]
        assert ans["entry"] == page_panel(service, u, it["view"], it["panel"])
        assert ans["view"] == it["view"] and ans["panel"] == it["panel"] and ans["as"] == "s" and ans["book"] == "tto"
        assert isinstance(ans["gen"], int)
    assert got["forward/" + twin]["entry"] != got["dibs/" + twin]["entry"]
    # where the table lives: its page and its tab (the value date strip is pinned above the tabs)
    assert (got["forward/B19"]["page"], got["forward/B19"]["tab"]) == ("Forward", "RET")
    assert (got["forward/B1"]["page"], got["forward/B1"]["tab"]) == ("Forward", "")
    assert got["dibs/B3"]["page"] == "DİBS RV"


def test_since_a_generation_only_what_changed_comes_and_a_users_own_page_follows(module_service):
    """As a page asks: ``since`` the generation the browser has, ``as`` the page it has them of - unchanged tables say
    so; a shared input brings again only the tables that read it; a value typed by the user makes their page their
    own ("p") and the whole table comes again."""
    svc = module_service                         # (a shared input changes: a service of this module's own)
    u = login(svc, "Lp Since")
    items = [{"view": "forward", "panel": "B1"}, {"view": "forward", "panel": "B19"}, {"view": "usd", "panel": "fomc"}]
    first = svc.panels(u, items)["panels"]
    since = [dict(it, since=first["%s/%s" % (it["view"], it["panel"])]["gen"], **{"as": "s"}) for it in items]
    svc.bump()
    again = svc.panels(u, since)["panels"]
    assert all(a.get("unchanged") and a["as"] == "s" and a["gen"] == svc.gen for a in again.values()), again
    desk = login(svc, "Lp RET")
    try:
        svc.set_inputs(desk, "tto", [{"ref": "Forward!W40", "value": "41,5"}])          # the RET curve: everybody's
        part = svc.panels(u, since)["panels"]
        assert any("41,50%" in row for row in texts(part["forward/B19"]["entry"]["data"]))
        assert part["forward/B1"].get("unchanged") and part["usd/fomc"].get("unchanged"), part
    finally:
        svc.reset_inputs(desk, "tto", ["Forward!W40"], shared=True)
    try:
        svc.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}])
        mine = svc.panels(u, since)["panels"]
        assert all(m["as"] == "p" and "entry" in m for m in mine.values())
        assert "15.12.2026" in texts(mine["forward/B1"]["entry"]["data"])[1]
    finally:
        svc.reset_inputs(u, "tto")


def test_a_part_of_a_table_is_cut_out_on_the_server(service):
    """An item's own rows (by the row's name - its first text - or its number in the sheet) and columns (letters):
    cut out of a copy, in the table's order, the caption rows kept; an input is still its own cell."""
    u = login(service, "Lp Parça")
    full = page_panel(service, u, "forward", "B19")["data"]
    labels = [_row_label(r) for r in full["rows"]]
    one_m, three_m = full["r"][labels.index("1M")], full["r"][labels.index("3M")]
    last = full["r"][-1]
    got = service.panels(u, [{"view": "forward", "panel": "B19", "key": "part", "rows": ["3M", "1M", last],
                              "cols": ["X", "V", "W"]},
                             {"view": "forward", "panel": "B19", "key": "whole"}])["panels"]
    part = got["part"]["entry"]["data"]
    assert part["c"] == ["V", "W", "X"]                                       # the table's order, not the list's
    assert part["r"] == [full["r"][0], one_m, three_m, last]                  # the caption row, then the rows picked
    assert [len(row) for row in part["rows"]] == [3, 3, 3, 3] and texts(part)[1][0] == "1M"
    j = full["c"].index("W")
    assert part["rows"][1][1] == full["rows"][full["r"].index(one_m)][j] and part["rows"][1][1].get("i") == "s"
    assert got["whole"]["entry"]["data"] == full                              # the whole table beside it
    assert page_panel(service, u, "forward", "B19")["data"] == full           # and the page's kept table is untouched
    # nothing left of the choice: the whole table, marked (the item says so)
    gone = service.panels(u, [{"view": "forward", "panel": "B19", "rows": ["yok"], "cols": ["ZZ"]}])["panels"]
    data = gone["forward/B19"]["entry"]["data"]
    assert data["part_missing"] and data["rows"] == full["rows"] and data["c"] == full["c"]


def test_a_merged_cell_keeps_what_is_left_of_it():
    data = {"sheet": "S", "r": [1, 2, 3], "c": ["A", "B", "C"], "fz": 2, "hc": 1, "rows": [
        [{"t": "Başlık", "k": "s", "b": 1, "cs": 3}, {"sk": 1}, {"sk": 1}],
        [{"t": "x", "k": "s"}, {"t": "1", "k": "n", "v": 1, "i": "u", "rs": 2}, {"t": "2", "k": "n"}],
        [{"t": "y", "k": "s"}, {"sk": 1}, {"t": "3", "k": "n"}]]}
    before = copy.deepcopy(data)
    cols = _pick_part(data, [], ["B", "C"])
    assert cols["c"] == ["B", "C"] and cols["r"] == [1, 2, 3] and cols["fz"] == 1 and "hc" not in cols
    assert cols["rows"][0] == [{"t": "Başlık", "k": "s", "b": 1, "cs": 2}, {"sk": 1}]       # the caption over what is left
    assert cols["rows"][1][0] == {"t": "1", "k": "n", "v": 1, "i": "u", "rs": 2}           # its own cell: still an input
    rows = _pick_part(data, ["y"], [])
    assert rows["r"] == [1, 3] and rows["rows"][0][0]["cs"] == 3                             # the lone title row stays
    assert rows["rows"][1] == [{"t": "y", "k": "s"}, {"t": "1", "k": "n", "v": 1}, {"t": "3", "k": "n"}]   # moved: read only
    assert data == before


def test_a_table_that_is_not_there_or_not_yours_says_so_and_the_others_still_come(service):
    u = login(service, "Lp Kullanıcı")
    a = login(service, "Lp Yönetici", admin=True)
    items = [{"view": "motor", "panel": "B1"}, {"view": "forward", "panel": "YOK1"}, {"view": "kaldirildi", "panel": "B1"},
             {"view": "forward", "panel": "B1"}]
    got = service.panels(u, items, role="user")["panels"]
    assert got["motor/B1"]["missing"] and got["motor/B1"]["status"] == 403 and "erişim yok" in got["motor/B1"]["error"]
    assert got["forward/YOK1"]["missing"] and got["forward/YOK1"]["status"] == 404 and "artık yok" in got["forward/YOK1"]["error"]
    assert got["kaldirildi/B1"]["missing"] and got["kaldirildi/B1"]["status"] == 404
    assert got["forward/B1"]["entry"]["id"] == "B1"
    assert service.panels(u, items)["panels"]["motor/B1"]["status"] == 403       # (the role read from the account)
    mine = service.panels(a, items, role="admin")["panels"]
    assert mine["motor/B1"]["entry"] == page_panel(service, a, "motor", "B1")


@pytest.mark.parametrize("items", [
    None, [], "forward/B1", [1], [{"view": "forward"}], [{"panel": "B1"}], [{"view": "../x", "panel": "B1"}],
    [{"view": "forward", "panel": "B1/x"}], [{"view": "forward", "panel": "B1"}, {"view": "forward", "panel": "B1"}],
    [{"view": "forward", "panel": "B1", "key": ""}], [{"view": "forward", "panel": "B1", "rows": "1M"}],
    [{"view": "forward", "panel": "B1", "cols": [1]}], [{"view": "forward", "panel": "B1", "rows": [True]}],
    [{"view": "forward", "panel": "B1", "key": "k%d" % i} for i in range(201)],
])
def test_what_is_not_a_request_for_tables_is_refused(service, items):
    u = login(service, "Lp Hatalı İstek")
    with pytest.raises(ServiceError) as err:
        service.panels(u, items)
    assert err.value.status == 400


# ---------------------------------------------------------------------------------------------- the layout
def test_each_user_keeps_their_own_layout(service):
    u = login(service, "Lp Ayşe")
    v = login(service, "Lp Mehmet")
    assert service.layout(u) == {"launchpads": [], "drawer": [], "favs": [], "landing": "", "rev": 0}
    first = {"type": "table", "id": "a1", "view": "forward", "panel": "B1", "w": 6, "h": "auto"}
    second = {"view": "dibs", "panel": "B3", "w": 12, "h": 320, "rows": ["TRT150328T24", 9, 9], "cols": ["A", "C"],
              "title": "  Benim\tRV ", "collapsed": True, "all": True, "extra": "x"}
    out = service.set_layout(u, {"launchpads": [{"name": " Sabah ", "items": [first, second]}]})
    lp = out["launchpads"]
    assert [x["name"] for x in lp] == ["Sabah"] and lp[0]["items"][0] == first
    b = lp[0]["items"][1]
    assert b == {"type": "table", "id": b["id"], "view": "dibs", "panel": "B3", "w": 12, "h": 320, "rows": ["TRT150328T24", 9],
                 "cols": ["A", "C"], "all": True, "title": "Benim RV", "collapsed": True} and len(b["id"]) >= 6
    assert out["rev"] == 1 and out["drawer"] == [] and out["favs"] == []
    # the parts not sent stay as they are
    service.set_layout(u, {"favs": ["forward", "dibs", "forward"], "landing": "launchpad/Sabah", "drawer": [first]})
    got = service.layout(u)
    assert got["launchpads"] == lp and got["favs"] == ["forward", "dibs"] and got["landing"] == "launchpad/Sabah"
    assert got["drawer"] == [first] and got["rev"] == 2
    assert service.layout(v)["launchpads"] == [] and service.layout(v)["rev"] == 0       # one user's is nobody else's
    service.set_layout(v, {"launchpads": [{"name": "Öğle", "items": []}]})
    assert [x["name"] for x in service.layout(u)["launchpads"]] == ["Sabah"]
    # kept with the account in the dashboard's database
    assert service.store.get("layout." + u)["drawer"] == [first]
    # the page it opens on: a page, a launchpad, or the desk's default
    for landing in ("forward", "launchpad/Sabah", ""):
        assert service.set_layout(u, {"landing": landing})["landing"] == landing


def test_another_kind_of_item_comes_in_by_its_own_check(service, monkeypatch):
    """An item names its type; a kind of item a later version adds brings its own check - the rest does not change."""
    u = login(service, "Lp Tür")
    with pytest.raises(ServiceError) as err:
        service.set_layout(u, {"launchpads": [{"name": "A", "items": [{"type": "not", "text": "x"}]}]})
    assert "bilinmeyen öğe türü" in str(err.value)

    def note(x, out):
        out["text"] = lay._text(x.get("text"), 200, "not")

    monkeypatch.setitem(lay.ITEM_TYPES, "note", note)
    got = service.set_layout(u, {"launchpads": [{"name": "A", "items": [{"type": "note", "text": " alış  güçlü ", "w": 3},
                                                                     {"view": "forward", "panel": "B7"}]}]})
    items = got["launchpads"][0]["items"]
    assert items[0]["type"] == "note" and items[0]["text"] == "alış güçlü" and items[0]["w"] == 3 and items[0]["h"] == "auto"
    assert items[1]["type"] == "table" and items[1]["w"] == lay.DEFAULT_WIDTH


@pytest.mark.parametrize("data", [
    None, [], {}, {"x": 1}, {"launchpads": "A"}, {"launchpads": [{"name": ""}]}, {"launchpads": [{"name": "x" * 61}]},
    {"launchpads": [{"name": "Sabah"}, {"name": "SABAH"}]}, {"launchpads": [{"name": "A", "items": "B1"}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward"}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "w": 5}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "w": True}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "h": 20}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "h": "320"}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "title": 5}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "rows": [0]}]}]},
    {"launchpads": [{"name": "A", "items": [{"view": "forward", "panel": "B1", "cols": [""]}]}]},
    {"drawer": {"view": "forward"}}, {"favs": "forward"}, {"favs": ["a b"]}, {"landing": 3}, {"landing": "launchpad/"},
    {"landing": "a/b"},
])
def test_what_is_not_a_layout_is_refused_and_nothing_changes(service, data):
    u = login(service, "Lp Hatalı")
    with pytest.raises(ServiceError) as err:
        service.set_layout(u, data)
    assert err.value.status == 400
    assert service.layout(u)["rev"] == 0


def test_how_much_a_user_may_keep(service, monkeypatch):
    u = login(service, "Lp Çok")
    monkeypatch.setattr(lay, "MAX_LAUNCHPADS", 2)
    monkeypatch.setattr(lay, "MAX_ITEMS", 3)
    monkeypatch.setattr(lay, "MAX_DRAWER", 1)
    t = {"view": "forward", "panel": "B1"}
    service.set_layout(u, {"launchpads": [{"name": "A", "items": [t, t, t]}, {"name": "B"}]})
    for data in ({"launchpads": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}, {"launchpads": [{"name": "A", "items": [t] * 4}]},
                 {"drawer": [t, t]}):
        with pytest.raises(ServiceError) as err:
            service.set_layout(u, data)
        assert err.value.status == 400 and "en fazla" in str(err.value)
    got = service.layout(u)
    assert [len(x["items"]) for x in got["launchpads"]] == [3, 0]
    assert len({x["id"] for x in got["launchpads"][0]["items"]}) == 3                # (each item its own id)
    monkeypatch.setattr(service, "MAX_LAYOUT_BYTES", 600)
    with pytest.raises(ServiceError) as err:
        service.set_layout(u, {"drawer": [dict(t, title="x" * 100)], "favs": ["p%d" % i for i in range(30)]})
    assert "çok büyüdü" in str(err.value)
    assert service.layout(u) == got                                                  # what was kept stays


def test_a_launchpad_goes_out_as_a_file_and_comes_back(service):
    u = login(service, "Lp Dışa")
    v = login(service, "Lp İçe")
    items = [{"id": "x1", "view": "forward", "panel": "B1", "w": 4, "h": 300, "rows": ["Tarih"]}]
    service.set_layout(u, {"launchpads": [{"name": "Şube Öğle", "items": items}]})
    raw, name = service.export_launchpad(u, "şube öğle")
    assert name == "launchpad-Sube-Ogle.json"
    data = json.loads(raw.decode("utf-8"))
    assert data["kind"] == "tto-launchpad" and data["name"] == "Şube Öğle"
    assert data["items"] == [dict(items[0], type="table")]
    with pytest.raises(ServiceError) as err:
        service.export_launchpad(u, "yok")
    assert err.value.status == 404
    # a colleague imports it; a name they have already gets a number
    service.set_layout(v, {"launchpads": [{"name": "Şube Öğle"}]})
    res = service.import_launchpad(v, data)
    assert res["name"] == "Şube Öğle (2)" and res["layout"]["launchpads"][1]["items"] == data["items"]
    assert service.import_launchpad(v, data, "Akşam")["name"] == "Akşam"
    for bad in (None, [], {"kind": "başka", "name": "x"}, {"name": "x", "items": [{"view": "forward"}]}):
        with pytest.raises(ServiceError):
            service.import_launchpad(v, bad)
    assert [x["name"] for x in service.layout(v)["launchpads"]] == ["Şube Öğle", "Şube Öğle (2)", "Akşam"]


def test_a_user_must_be_signed_in(service):
    for call in (lambda: service.layout(None), lambda: service.set_layout(None, {"favs": []}),
                 lambda: service.layout("hiç olmayan kişi"), lambda: service.import_launchpad(None, {"name": "x"})):
        with pytest.raises(ServiceError) as err:
            call()
        assert err.value.status == 401


def test_the_layout_and_the_column_order_survive_a_restart(tmp_path):
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Lp Kalıcı")
        kept = svc.set_layout(u, {"launchpads": [{"name": "Sabah", "items": [{"view": "forward", "panel": "B1", "w": 12}]}],
                                  "favs": ["forward"], "landing": "launchpad/Sabah", "drawer": [{"view": "dibs", "panel": "B3"}]})
        svc.set_column_order(u, "v/dibs/B3", ["C", "A", "B"])
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        assert again.layout(u) == kept
        assert again.columns(u)["order"] == {"v/dibs/B3": ["C", "A", "B"]}
    finally:
        again.stop()


# ---------------------------------------------------------------------------------------------- over HTTP
def test_over_http(service):
    client = TestClient(create_app(service=service))                          # (no "with": the shared service stays up)
    for path in ("/static/js/layout.js", "/static/js/boxes.js", "/static/js/drawer.js", "/static/js/pages/launchpad.js"):
        assert client.get(path).status_code == 200, path
    h = auth(service, "Lp Zeynep")
    r = client.post("/api/panels", json={"items": [{"view": "forward", "panel": "B1"}, {"view": "motor", "panel": "B1"}]}, headers=h)
    assert r.status_code == 200
    got = r.json()["panels"]
    assert got["forward/B1"]["entry"]["id"] == "B1" and got["motor/B1"]["status"] == 403
    assert client.post("/api/panels", json={"items": "x"}, headers=h).status_code == 400
    assert client.post("/api/panels", json={"items": [{"view": "forward", "panel": "B1"}]}, headers=ANON).status_code == 401
    # the layout: read, a part replaced, a launchpad out as a file and in again
    assert client.get("/api/layout", headers=h).json()["rev"] == 0
    r = client.post("/api/layout", json={"launchpads": [{"name": "Sabah", "items": [{"view": "forward", "panel": "B1"}]}]}, headers=h)
    assert r.status_code == 200 and r.json()["launchpads"][0]["name"] == "Sabah"
    assert client.post("/api/layout", json={"favs": "x"}, headers=h).status_code == 400
    f = client.get("/api/layout/export", params={"name": "Sabah"}, headers=h)
    assert f.status_code == 200 and 'filename="launchpad-Sabah.json"' in f.headers["content-disposition"]
    r = client.post("/api/layout/import", json={"launchpad": f.json()}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Sabah (2)"
    assert [x["name"] for x in client.get("/api/layout", headers=h).json()["launchpads"]] == ["Sabah", "Sabah (2)"]
    assert client.get("/api/layout", headers=ANON).status_code == 401
    # a change sent from another page than the dashboard's own is refused
    foreign = dict(h, Origin="http://kotu-site.example")
    assert client.post("/api/layout", json={"favs": []}, headers=foreign).status_code == 403
    assert client.post("/api/panels", json={"items": [{"view": "forward", "panel": "B1"}]}, headers=foreign).status_code == 403
