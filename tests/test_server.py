"""HTTP layer: the JSON API the browser uses.  The client is signed in (as a reader with no inputs of their own);
``hdr(user)`` signs a request in as someone else, ``ANON`` sends it without a session."""
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto.server import create_app

_svc = []


@pytest.fixture(scope="module")
def client(module_service):
    app = create_app(module_service)
    _svc[:] = [module_service]
    with TestClient(app, headers=auth(module_service, "HTTP Okuyucu")) as c:
        yield c


def hdr(user):
    return auth(_svc[0], user)


@pytest.fixture(scope="module")
def user(client, module_service):
    return module_service.login("Çağrı Öztürk")["user"]


def test_index_and_static_files(client):
    res = client.get("/")
    assert res.status_code == 200 and "TTO Masa" in res.text and "/static/js/main.js" in res.text
    for path in ("/static/js/main.js", "/static/js/grid.js", "/static/js/chart.js", "/static/css/app.css",
                 "/static/js/pages/view.js", "/static/js/pages/blotter.js", "/static/js/pages/broker.js", "/static/js/pages/vol.js", "/static/js/pages/explorer.js",
                 "/static/js/ret.js", "/static/js/scenarios.js", "/static/js/api.js", "/static/js/ui.js", "/static/js/format.js",
                 "/static/js/find.js", "/static/js/spot.js", "/static/js/status.js", "/static/js/pages/users.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache"          # an updated dashboard is picked up at once
    assert client.get("/static/yok.js").status_code == 404


def test_login(client, module_service):
    from tto.auth import hash_password
    module_service.store.create_account("Yeni Kişi", hash_password("gizli-sifre-1"))
    try:
        res = client.post("/api/login", json={"name": "  YENİ   kişi ", "password": "gizli-sifre-1"}, headers=ANON)
        assert res.status_code == 200 and res.json() == {"user": "yeni kişi", "display": "Yeni Kişi", "role": "user"}
        cookie = res.headers["set-cookie"]
        assert cookie.startswith("tto_oturum=") and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert client.post("/api/login", json={"name": "Yeni Kişi", "password": "yanlış-şifre"}, headers=ANON).status_code == 401
        assert client.post("/api/login", json={"name": ""}, headers=ANON).status_code == 401
        assert client.post("/api/login", content=b"not json", headers=dict(ANON, **{"Content-Type": "application/json"})).status_code == 400
    finally:
        client.cookies.clear()                       # the module's client stays the reader
    names = [u["display"] for u in client.get("/api/users").json()["users"]]
    assert "Yeni Kişi" in names
    assert client.get("/api/users", headers=ANON).status_code == 401           # nothing but the sign-in without a session


def test_where_the_desks_files_live_is_for_the_administrators(tmp_path):
    """The status every signed-in user reads (data freshness, the queue, the last fault, a database problem) leaves
    out where the log, the database and its backups live on the desk's computer; an administrator sees them."""
    import json
    from conftest import make_service
    svc = make_service(tmp_path)
    try:
        with TestClient(create_app(svc)) as client:
            user = client.get("/api/status", headers=auth(svc, "Durum Kullanıcı")).json()["ops"]
            admin = client.get("/api/status", headers=auth(svc, "Durum Yönetici", admin=True)).json()["ops"]
        assert "log" not in user and "dir" not in user["db"]["backup"] and str(tmp_path) not in json.dumps(user)
        assert "log" in admin and admin["db"]["backup"]["dir"]
        # the calculation thread's state is everybody's (its numbers move between the two reads: the warm-up runs)
        assert set(user["engine"]) == set(admin["engine"]) and user["feed"]["state"] == "replay" and "last_error" in user
    finally:
        svc.stop()


def test_status_nav_header(client):
    st = client.get("/api/status").json()
    assert st["mode"] == "replay" and st["port"] == 1057
    # operations: the calculation thread's queue, the last fault a loop survived, how fresh the data is
    ops = st["ops"]
    assert ops["engine"]["queue"] >= 0 and ops["feed"]["state"] == "replay" and "last_error" in ops
    pages = client.get("/api/nav").json()["pages"]
    assert {"masa", "forward", "ois", "usd", "blotter"} <= {p["id"] for p in pages}
    assert len(client.get("/api/header").json()["items"]) >= 5


def test_views_and_locale(client, user):
    res = client.get("/api/view/forward", headers=hdr(user))
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "forward" and len(data["panels"]) > 20
    hidden = client.get("/api/view/forward?all=1").json()
    assert len(hidden["panels"]) > len(data["panels"])
    assert client.get("/api/view/yok").status_code == 404
    tr = client.get("/api/cell?book=tto&ref=Forward!F2&lang=tr").json()["cell"]["t"]
    en = client.get("/api/cell?book=tto&ref=Forward!F2&lang=en").json()["cell"]["t"]
    assert tr == "49,9977" and en == "49.9977"
    # the sheet explorer: administrators only (a page's cells come with the page, /api/cell answers everybody)
    adm = auth(_svc[0], "HTTP Yönetici", admin=True)
    grid = client.get("/api/grid", params={"book": "sofr", "sheet": "SOFR_FOMC", "range": "A47:C49"}, headers=adm).json()
    assert grid["data"]["rows"][0][0]["t"] == "Vade"
    assert client.get("/api/grid", params={"book": "tto", "sheet": "Yok", "range": "A1"}, headers=adm).status_code == 404
    assert [s["name"] for s in client.get("/api/sheets?book=sofr", headers=adm).json()["sheets"]] == ["SOFR_FOMC"]
    assert client.get("/api/grid", params={"book": "sofr", "sheet": "SOFR_FOMC", "range": "A47:C49"}).status_code == 403
    assert client.get("/api/sheets?book=sofr").status_code == 403


def test_inputs_need_a_user(client):
    body = {"book": "tto", "items": [{"ref": "Forward!D2", "value": "15.12.2026"}]}
    assert client.post("/api/inputs", json=body, headers=ANON).status_code == 401
    assert client.post("/api/inputs", json=body, headers={"Authorization": "Bearer gecersiz-oturum"}).status_code == 401
    assert client.post("/api/inputs", json={"book": "tto"}, headers=hdr("Girdi Kişisi")).status_code == 400


def test_inputs_paste_reset(client, user):
    h = hdr(user)
    res = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "Forward!D2", "value": "15.12.2026"}]}, headers=h)
    assert res.status_code == 200 and res.json()["applied"] == 1
    mine = client.get("/api/cell?book=tto&ref=Forward!D2", headers=h).json()["cell"]
    assert mine["t"] == "15.12.2026" and mine["m"] == 1
    assert client.get("/api/cell?book=tto&ref=Forward!D2").json()["cell"]["t"] != "15.12.2026"
    assert client.get("/api/my-inputs", headers=h).json()["inputs"][0]["ref"] == "Forward!D2"
    # Turkish and English number formats for the same paste
    res = client.post("/api/paste?lang=tr", json={"book": "tto", "anchor": "OIS_MAIN!F2", "text": "2.500"}, headers=h)
    assert res.json()["applied"] == 1
    assert client.get("/api/cell?book=tto&ref=OIS_MAIN!F2", headers=h).json()["cell"]["v"] == 2500.0
    res = client.post("/api/paste?lang=en", json={"book": "tto", "anchor": "OIS_MAIN!F2", "text": "2.500"}, headers=h)
    assert client.get("/api/cell?book=tto&ref=OIS_MAIN!F2", headers=h).json()["cell"]["v"] == 2.5
    assert client.post("/api/paste", json={"book": "tto", "anchor": "Forward!D33", "text": "1"}, headers=h).status_code == 400
    res = client.post("/api/reset", json={"book": "tto"}, headers=h)
    assert res.json()["reset"] == 2
    assert client.get("/api/my-inputs", headers=h).json()["inputs"] == []


def test_scenarios(client, user):
    h = hdr(user)
    client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "Forward!D2", "value": "04.02.2027"}]}, headers=h)
    assert client.post("/api/scenarios", json={"name": "Şubat"}, headers=h).json()["cells"] == 1
    client.post("/api/reset", json={"book": "tto"}, headers=h)
    assert client.get("/api/scenarios", headers=h).json()["scenarios"][0]["name"] == "Şubat"
    assert client.post("/api/scenarios/load", json={"name": "Şubat"}, headers=h).json()["cells"] == 1
    assert client.get("/api/cell?book=tto&ref=Forward!D2", headers=h).json()["cell"]["t"] == "04.02.2027"
    assert client.post("/api/scenarios/load", json={"name": "Yok"}, headers=h).status_code == 404
    assert client.request("DELETE", "/api/scenarios", json={"name": "Şubat"}, headers=h).status_code == 200
    assert client.get("/api/scenarios", headers=h).json()["scenarios"] == []
    assert client.get("/api/scenarios", headers=ANON).status_code == 401
    client.post("/api/reset", json={"book": "tto"}, headers=h)


def test_ret_endpoints(client, user):
    h = hdr(user)
    res = client.post("/api/ret", json={"rows": [{"tenor": "1W", "bid": "34,50", "ask": "34,70"}]}, headers=h)
    assert res.status_code == 200 and res.json()["applied"] == 2
    rows = {r["tenor"]: r for r in client.get("/api/ret").json()["rows"]}
    assert rows["1W"]["bid"] == pytest.approx(0.345) and rows["1W"]["ask"] == pytest.approx(0.347)
    hist = client.get("/api/ret/history").json()["history"]
    assert hist and hist[0]["user"] == user
    assert client.post("/api/ret", json={"rows": [{"tenor": "1W", "bid": "34,5"}]}, headers=ANON).status_code == 401
    assert client.post("/api/ret", json={"rows": "x"}, headers=h).status_code == 400
    assert client.post("/api/ret", json={"rows": [{"tenor": "99Y", "bid": 1}]}, headers=h).status_code == 400


def test_blotter_endpoints(client, user):
    h = hdr(user)
    q = client.post("/api/blotter/quote/forward", json={"value_date": "15.12.2026", "basis": "RET_ASK", "amount": "5m"}).json()
    assert q["tl"] == 5e6 * q["forward"] and q["value_date_iso"] == "2026-12-15"
    assert client.post("/api/blotter/quote/forward", json={"basis": "RET_MID"}).status_code == 400
    saved = client.post("/api/blotter/forward", json={"dir": "S", "amount": "5m", "value_date": "15.12.2026", "basis": "RET_ASK"}, headers=h)
    assert saved.status_code == 200 and saved.json()["forward"] == q["forward"]
    assert client.post("/api/blotter/forward", json={"dir": "S", "amount": "5m", "value_date": "15.12.2026"}, headers=ANON).status_code == 401
    mk = client.get("/api/blotter/ois-market").json()
    assert mk["usdtry"] > 0 and len(mk["tenors"]) == 21
    oq = client.post("/api/blotter/quote/ois", json={"strategy": "fly", "side": "REC GÖVDE", "wing1": "1Y", "body": "2Y", "wing2": "3Y",
                                                     "level": "10"}).json()
    assert len(oq["legs"]) == 3
    assert client.post("/api/blotter/ois", json={"strategy": "outright", "side": "RECEIVE", "tenor": "2Y", "level": "35,9"}, headers=h).status_code == 200
    assert client.post("/api/blotter/bond", json={"instrument": "TRT120929T12", "dir": "B", "amount": "10m", "price": "97,5"}, headers=h).status_code == 200
    data = client.get("/api/blotter").json()
    assert [t["kind"] for t in data["trades"]] == ["fwd", "ois", "bond"]
    assert all(t["created_by"] == user for t in data["trades"])
    first = data["trades"][0]["id"]
    assert client.delete("/api/blotter/trade/%d" % first, headers=ANON).status_code == 401
    assert client.delete("/api/blotter/trade/%d" % first, headers=h).json()["deleted"] == [first]
    assert client.delete("/api/blotter/trade/%d" % first, headers=h).status_code == 404
    assert client.get("/api/blotter?date=2020-01-01").json()["trades"] == []
    assert client.get("/api/blotter?date=bozuk").status_code == 400


def test_blotter_risk_period_and_bond_quote_over_http(client, user):
    import datetime as dt
    h = hdr(user)
    q = client.post("/api/blotter/quote/forward", json={"dir": "S", "value_date": "15.12.2026", "basis": "RET_MID", "amount": "5m"}).json()
    assert q["dv01"]["tl"] < 0 < q["dv01"]["usd_leg"] and q["dv01"]["amount"] == 5e6 and q["dv01"]["dir"] == "S"
    oq = client.post("/api/blotter/quote/ois", json={"strategy": "outright", "side": "PAY", "tenor": "2Y", "level": "35"}).json()
    assert oq["dv01"]["net"] == oq["dv01"]["gross"] == oq["legs"][0]["dv01"]
    bq = client.post("/api/blotter/quote/bond", json={"instrument": "TRT150328T24", "dir": "B", "amount": "20m"}).json()
    assert bq["known"] and bq["info"]["isin"] == "TRT150328T24" and bq["dv01_tl"] == pytest.approx(-20 * bq["info"]["dv01_mn"])
    assert client.post("/api/blotter/quote/bond", json={"instrument": "YOK"}).json()["known"] is False
    assert client.post("/api/blotter/quote/bond", json={}).status_code == 400
    assert client.post("/api/blotter/bond", json={"instrument": "TRT150328T24", "dir": "B", "amount": "20m", "price": "100"}, headers=h).status_code == 200
    today = dt.date.today()
    data = client.get("/api/blotter").json()
    assert data["ranged"] is False and data["is_today"] and data["to"] == today.isoformat()
    bonds = [t for t in data["trades"] if t["kind"] == "bond"]
    assert bonds[-1]["dv01"] == pytest.approx(bq["dv01"]) and bonds[-1]["dv01_tl"] == pytest.approx(bq["dv01_tl"])
    assert data["risk"]["bond"] == pytest.approx(sum(t["dv01"] for t in bonds)) and "total" in data["risk"]
    start = (today - dt.timedelta(days=30)).isoformat()
    per = client.get("/api/blotter?date=%s&to=%s" % (start, today.isoformat())).json()
    assert per["ranged"] and per["date"] == start and per["to"] == today.isoformat() and not per["is_today"]
    assert [t["id"] for t in per["trades"]] == [t["id"] for t in data["trades"]] and per["sheet"] == []
    assert client.get("/api/blotter?date=%s&to=bozuk" % start).status_code == 400
    res = client.get("/api/blotter/export?date=%s&to=%s" % (start, today.isoformat()))
    assert res.status_code == 200 and res.content[:2] == b"PK"
    assert res.headers["content-disposition"] == 'attachment; filename="Blotter_%s-%s.xlsx"' % (
        start.replace("-", "."), today.strftime("%Y.%m.%d"))


def test_tabs_hand_values_and_search_data_over_http(client, user):
    h = hdr(user)
    page = client.get("/api/view/forward", headers=h).json()
    assert page["pinned"] == ["B1"] and page["sections"][0]["id"] == "calc" and page["sections"][0]["panels"][0] == "B7"
    assert client.get("/api/view/bulk").json()["sections"] == []
    tables = {p["id"]: p.get("tables") for p in client.get("/api/nav").json()["pages"]}
    assert any(t["id"] == "XAU4" and t["tab"] == "Hesaplayıcılar" for t in tables["viop"]) and tables["blotter"] is None
    # a value over a formula needs the mode ("adhoc"); it is undone by "reset" with the cell's address
    # (EK_FWD!F50: the RET mid outright of the USDTRY table on the "Forward fiyatları" tab - a formula)
    res = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "EK_FWD!F50", "value": "55"}]}, headers=h).json()
    assert res["applied"] == 0 and res["errors"]
    res = client.post("/api/inputs", json={"book": "tto", "adhoc": True, "items": [{"ref": "EK_FWD!F50", "value": "55"}]}, headers=h).json()
    assert res["applied"] == 1 and res["errors"] == []
    usd = next(p for p in client.get("/api/view/forward", headers=h).json()["panels"] if p["id"] == "FR1")["data"]
    mine = usd["rows"][usd["r"].index(50)][usd["c"].index("F")]
    assert mine["m"] == 1 and mine["fx"] == 1 and mine["i"] == "u" and mine["t"] == "55,0000"
    assert client.post("/api/reset", json={"book": "tto", "refs": ["EK_FWD!F50"]}, headers=h).json()["reset"] == 1
    usd = next(p for p in client.get("/api/view/forward", headers=h).json()["panels"] if p["id"] == "FR1")["data"]
    assert "m" not in usd["rows"][usd["r"].index(50)][usd["c"].index("F")]


def test_workbook_extras_over_http(client, user, module_service, monkeypatch):
    # the sheets the desk does not use are taken out as the workbook loads: no page, no cells, no picture
    h = hdr(user)
    assert client.get("/api/view/ivir", headers=h).status_code == 404
    assert client.get("/api/view/ypdibs", headers=h).status_code == 404
    assert client.get("/api/image?book=tto&sheet=%s&i=0" % quote("Ivır Zıvır"), headers=h).status_code == 404
    # (that the sheet explorer does not list them is tested on the service: test_views.py)
    # a picture of a sheet (the workbook's only one was on "Ivır Zıvır"; put on MASA here) is served and cached
    assert client.get("/api/image?book=tto&sheet=MASA&i=0", headers=h).status_code == 404
    from tto.xl.model import Model
    import os
    raw = Model.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "tto.json.gz"))
    monkeypatch.setattr(module_service.books["tto"].model.sheet("MASA"), "images", list(raw.sheet("Ivır Zıvır").images))
    res = client.get("/api/image?book=tto&sheet=MASA&i=0", headers=h)
    assert res.status_code == 200 and res.headers["content-type"] == "image/png" and res.content[:4] == b"\x89PNG"
    assert "max-age" in res.headers["cache-control"]
    assert client.get("/api/image?book=tto&sheet=MASA&i=x", headers=h).status_code == 404
    # shortcuts of the desk sheet (29; the one to the Motor page is an administrator's); columns hidden in Excel only with
    # the helper tables
    links = client.get("/api/view/masa").json()["links"]
    assert len(links) == 28 and "motor" not in {link["page"] for link in links}
    admin = auth(module_service, "HTTP Yönetici", admin=True)
    assert len(client.get("/api/view/masa", headers=admin).json()["links"]) == 29

    def columns(query):
        return next(p for p in client.get("/api/view/viop" + query).json()["panels"] if p["id"] == "B2")["data"]["c"]

    assert columns("") == ["B", "D", "E", "F", "G"] and columns("?all=1") == ["B", "C", "D", "E", "F", "G"]
    # a block pasted in Excel's layout: what is not an input is skipped instead of refused
    items = [{"ref": "VIOP!B16", "value": "7"}, {"ref": "VIOP!C16", "value": "USSO1Z"}]
    res = client.post("/api/inputs", json={"book": "tto", "items": items, "lenient": True}, headers=hdr(user)).json()
    assert (res["applied"], res["skipped"], res["errors"]) == (1, 1, [])
    res = client.post("/api/inputs", json={"book": "tto", "items": items}, headers=hdr(user)).json()
    assert res["applied"] == 1 and len(res["errors"]) == 1 and "skipped" not in res
    assert client.post("/api/reset", json={"book": "tto"}, headers=hdr(user)).status_code == 200


def test_blotter_archive_download(client, user):
    import re

    from helpers import read_xlsx
    res = client.get("/api/blotter/export", headers=hdr(user))
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert re.fullmatch(r'attachment; filename="Blotter_\d{4}\.\d{2}\.\d{2}\.xlsx"', res.headers["content-disposition"])
    assert res.headers["cache-control"] == "no-store"
    book = read_xlsx(res.content)
    assert list(book) == ["Günlük İşlemler", "İşlem listesi"] and book["Günlük İşlemler"]["B1"] == "USDTRY Forward"
    assert book["Günlük İşlemler"]["L3"] == "2Y"                                # the OIS trade entered above
    empty = client.get("/api/blotter/export?date=2020-01-01")                  # a day without trades is still a file
    assert empty.status_code == 200 and 'filename="Blotter_2020.01.01.xlsx"' in empty.headers["content-disposition"]
    assert "kayıt yok" in read_xlsx(empty.content)["İşlem listesi"].values()
    assert client.get("/api/blotter/export?date=bozuk").status_code == 400


def test_the_desks_chat_trades_against_the_blotter_over_http(client, user):
    """A trade of the desk said in the broker chat and not entered: counted in the status (the menu's badge), listed,
    ignored and taken back over HTTP; deciding needs a session."""
    h = hdr(user)
    before = client.get("/api/status").json()["chat_missing"]
    assert client.post("/api/broker", json={"text": "9y ois given at 33.05", "party": "biz"}, headers=h).status_code == 200
    data = client.get("/api/broker/recon").json()
    line = next(x for x in data["items"] if x["raw"] == "9y ois given at 33.05")
    assert line["state"] == "missing" and line["q"]["party"] == "biz" and data["window"] == 900
    assert client.get("/api/status").json()["chat_missing"] == before + 1
    assert client.post("/api/broker/recon", json={"quote": line["id"], "action": "ignore"}, headers=ANON).status_code == 401
    res = client.post("/api/broker/recon", json={"quote": line["id"], "action": "ignore"}, headers=h)
    assert res.status_code == 200 and next(x for x in res.json()["items"] if x["id"] == line["id"])["state"] == "ignored"
    assert client.get("/api/status").json()["chat_missing"] == before
    assert client.post("/api/broker/recon", json={"quote": line["id"], "action": "undo"}, headers=h).json()["missing"] == data["missing"]
    assert client.post("/api/broker/recon", json={"quote": line["id"], "action": "bozuk"}, headers=h).status_code == 400
    assert client.post("/api/broker/recon", json={"quote": "x", "action": "ignore"}, headers=h).status_code == 400
    assert client.get("/api/broker/recon", params={"date": "dün"}).status_code == 400
    assert client.get("/static/js/recon.js").status_code == 200
    # the board's stale limit: the desk's, set by a signed-in user, between 1 and 1440 minutes
    assert client.get("/api/broker").json()["stale_minutes"] == 10
    assert client.post("/api/broker/settings", json={"stale_minutes": 15}, headers=ANON).status_code == 401
    assert client.post("/api/broker/settings", json={"stale_minutes": "0"}, headers=h).status_code == 400
    assert client.post("/api/broker/settings", json={"stale_minutes": "15"}, headers=h).json() == {"stale_minutes": 15}
    assert client.get("/api/broker").json()["stale_minutes"] == 15
    assert client.post("/api/broker/settings", json={"stale_minutes": 10}, headers=h).status_code == 200


def test_errors_are_json_and_never_tracebacks(client, module_service, monkeypatch):
    res = client.get("/api/cell?book=tto&ref=bozuk")
    assert res.status_code == 404 and set(res.json()) == {"error"}
    # an unexpected fault: a short answer to the browser, the whole story to the log (and the status)
    def broken(*args, **kwargs):
        raise RuntimeError("beklenmeyen durum")
    monkeypatch.setattr(module_service, "ret_history", broken)
    res = client.get("/api/ret/history")
    assert res.status_code == 500 and res.json() == {"error": "sunucu hatası: beklenmeyen durum"}
    le = module_service.status()["ops"]["last_error"]
    assert le["where"] == "GET /api/ret/history" and le["text"] == "RuntimeError: beklenmeyen durum"
    # a name in the query string (or in the old X-TTO-User header) signs nobody in: only a session does
    assert client.get("/api/view/masa?user=%s" % quote("çağrı öztürk"), headers=ANON).status_code == 401
    assert client.get("/api/view/masa", headers=dict(ANON, **{"X-TTO-User": quote("çağrı öztürk")})).status_code == 401


def test_a_number_json_cannot_hold_is_sent_as_null_not_a_500(client, module_service, monkeypatch):
    """Starlette writes JSON without infinity / NaN: one such number (a ratio worked out outside the engine) used to
    turn the whole answer into a 500.  It is sent as null; everything else of the answer stays."""
    real = module_service.status

    def status():
        out = real()
        out["odd"] = {"inf": float("inf"), "nan": float("nan"), "list": [1.5, float("-inf")], "ok": 2.5}
        return out

    monkeypatch.setattr(module_service, "status", status)
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json()["odd"] == {"inf": None, "nan": None, "list": [1.5, None], "ok": 2.5}
    assert res.json()["mode"] == "replay"


def test_pages_waiting_for_a_busy_calculation_thread_hold_no_server_thread(client, module_service):
    """A page waits for the calculation thread without holding one of the server's threads (Starlette has 40, shared
    with the static files and the sign-in): with the calculation thread busy and 54 pages asked at once, the
    dashboard's files and the sign-in still answer at once; the pages come when the calculation is done."""
    import threading
    import time
    users = [hdr("Bekleyen %d" % i) for i in range(3)]
    views = [p["id"] for p in client.get("/api/nav").json()["pages"] if not p.get("custom")][:18]
    gate = threading.Event()
    module_service.et.submit_at(module_service.et.WRITE, gate.wait, 120)
    codes = []

    def ask(h, vid):
        codes.append(client.get("/api/view/" + vid, headers=h).status_code)

    threads = [threading.Thread(target=ask, args=(h, vid)) for h in users for vid in views]
    try:
        for t in threads:
            t.start()
        time.sleep(1.0)
        t0 = time.time()
        assert client.get("/static/js/main.js").status_code == 200
        assert client.get("/api/auth").status_code == 200 and client.get("/api/status").status_code == 200
        assert time.time() - t0 < 5.0 and not codes                     # (the pages still wait)
    finally:
        gate.set()
        for t in threads:
            t.join(300)
    assert codes == [200] * len(threads)


def test_a_session_is_looked_up_once_a_minute_and_a_sign_out_ends_it_at_once(client, module_service, monkeypatch):
    """The session of a request is not a database query on the event loop each time: it is kept for a minute - and
    forgotten at once when it ends (signed out, a new password, an account closed)."""
    h = hdr("Oturum Önbellek")
    looked = []
    real = module_service.store.session_user
    monkeypatch.setattr(module_service.store, "session_user", lambda *a: (looked.append(1), real(*a))[1])
    for _ in range(5):
        assert client.get("/api/status", headers=h).status_code == 200
    assert len(looked) == 1
    assert client.post("/api/logout", headers=h).status_code == 200
    assert client.get("/api/status", headers=h).status_code == 401


# ---------------------------------------------------------------------- gzip-compressed JSON answers (hiz-dizi)
def _raw(client, url, encoding):
    """The answer's bytes as they travel (not decoded) and its headers."""
    with client.stream("GET", url, headers={"Accept-Encoding": encoding}) as res:
        return res.status_code, res.headers, b"".join(res.iter_raw())


def test_big_json_answers_go_gzipped_to_a_client_that_takes_gzip(client):
    import gzip
    import json
    from tto.server import GZIP_MIN
    for url in ("/api/nav", "/api/view/ois"):
        code, head, plain = _raw(client, url, "identity")
        assert code == 200 and "content-encoding" not in head and len(plain) >= GZIP_MIN
        assert "accept-encoding" in head["vary"].lower()
        code, head, packed = _raw(client, url, "gzip, deflate, br")
        assert code == 200 and head["content-encoding"] == "gzip" and "accept-encoding" in head["vary"].lower()
        assert int(head["content-length"]) == len(packed) < len(plain) // 3
        if url == "/api/nav":                                           # (the same answer twice: the very same bytes)
            assert gzip.decompress(packed) == plain
        moving = ("gen", "ms")                                          # (a page made again in between: its generation)
        a, b = json.loads(gzip.decompress(packed)), json.loads(plain)
        assert {k: v for k, v in a.items() if k not in moving} == {k: v for k, v in b.items() if k not in moving}
        c = client.get(url).json()                                      # (a client decodes it by itself)
        assert {k: v for k, v in c.items() if k not in moving} == {k: v for k, v in b.items() if k not in moving}


def test_small_answers_and_clients_without_gzip_get_plain_json(client):
    from tto.server import GZIP_MIN
    code, head, body = _raw(client, "/api/progress", "gzip")
    assert code == 200 and "content-encoding" not in head and len(body) < GZIP_MIN    # below the threshold
    for encoding in ("identity", "deflate, br", "gzip;q=0", "GZIP; Q=0.0, identity", ""):
        code, head, body = _raw(client, "/api/nav", encoding)
        assert code == 200 and "content-encoding" not in head and body.startswith(b"{"), encoding
    code, head, body = _raw(client, "/api/nav", "br;q=1.0, GZIP;q=0.5")
    assert head["content-encoding"] == "gzip"
    code, head, body = _raw(client, "/api/view/yok-boyle-sayfa", "gzip")                 # an error answer is JSON too
    assert code == 404 and "content-encoding" not in head and b"error" in body


def test_accept_encoding_is_read_with_its_q_values():
    from tto.server import accepts_gzip
    yes = ("gzip", "gzip, deflate", "deflate, gzip;q=0.5", "x-gzip", " GZip ;q=1", "br, gzip;q=0.001")
    no = (None, "", "identity", "deflate, br", "gzip;q=0", "gzip; q=0.000", "gzip;q=abc", "*", "gzipx")
    assert all(accepts_gzip(h) for h in yes) and not any(accepts_gzip(h) for h in no)


def test_the_live_stream_is_never_compressed(client, module_service, monkeypatch):
    """/api/events (server-sent events) is sent as it is, even to a client that takes gzip: a compressed stream would
    hold its messages back.  (The stream is made to end after its second message here.)"""
    from starlette.requests import Request

    async def gone(self):
        return True

    real = module_service.add_listener

    def add_listener(fn):
        real(fn)
        fn(module_service.gen)                                          # a generation at once, then the client is gone

    monkeypatch.setattr(Request, "is_disconnected", gone)
    monkeypatch.setattr(module_service, "add_listener", add_listener)
    code, head, body = _raw(client, "/api/events", "gzip, deflate, br")
    assert code == 200 and head["content-type"].startswith("text/event-stream")
    assert "content-encoding" not in head and body.startswith(b"data: ") and body.count(b"data: ") == 2


def test_compression_leaves_anything_but_json_answers_alone():
    import asyncio
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse, Response, StreamingResponse
    from tto.server import compress_json
    req = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"accept-encoding", b"gzip")]})

    async def gen():
        yield "data: x\n\n"

    for resp in (StreamingResponse(gen(), media_type="text/event-stream"), PlainTextResponse("x" * 5000),
                 Response(b"x" * 5000, media_type="application/json")):       # (a download that is JSON)
        out = asyncio.run(compress_json(req, resp))
        assert out is resp and "content-encoding" not in out.headers and "vary" not in out.headers
