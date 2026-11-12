"""HTTP layer: the JSON API the browser uses."""
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from tto.server import create_app


@pytest.fixture(scope="module")
def client(module_service):
    app = create_app(module_service)
    with TestClient(app) as c:
        yield c


def hdr(user):
    return {"X-TTO-User": quote(user)}


@pytest.fixture(scope="module")
def user(client):
    res = client.post("/api/login", json={"name": "Çağrı Öztürk"})
    assert res.status_code == 200
    return res.json()["user"]


def test_index_and_static_files(client):
    res = client.get("/")
    assert res.status_code == 200 and "TTO Masa" in res.text and "/static/js/main.js" in res.text
    for path in ("/static/js/main.js", "/static/js/grid.js", "/static/js/chart.js", "/static/css/app.css",
                 "/static/js/pages/view.js", "/static/js/pages/blotter.js", "/static/js/pages/explorer.js",
                 "/static/js/ret.js", "/static/js/scenarios.js", "/static/js/api.js", "/static/js/ui.js", "/static/js/format.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache"          # an updated dashboard is picked up at once
    assert client.get("/static/yok.js").status_code == 404


def test_login(client):
    res = client.post("/api/login", json={"name": "  Yeni   Kişi "})
    assert res.json() == {"user": "yeni kişi", "display": "Yeni Kişi", "new": True}
    assert client.post("/api/login", json={"name": "YENİ KİŞİ"}).json()["new"] is False
    assert client.post("/api/login", json={"name": ""}).status_code == 400
    assert client.post("/api/login", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 400
    names = [u["display"] for u in client.get("/api/users").json()["users"]]
    assert "Yeni Kişi" in names


def test_status_nav_header(client):
    st = client.get("/api/status").json()
    assert st["mode"] == "replay" and st["port"] == 1057
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
    grid = client.get("/api/grid", params={"book": "sofr", "sheet": "SOFR_FOMC", "range": "A47:C49"}).json()
    assert grid["data"]["rows"][0][0]["t"] == "Vade"
    assert client.get("/api/grid", params={"book": "tto", "sheet": "Yok", "range": "A1"}).status_code == 404
    assert [s["name"] for s in client.get("/api/sheets?book=sofr").json()["sheets"]] == ["SOFR_FOMC"]


def test_inputs_need_a_user(client):
    body = {"book": "tto", "items": [{"ref": "Forward!D2", "value": "15.12.2026"}]}
    assert client.post("/api/inputs", json=body).status_code == 401
    assert client.post("/api/inputs", json=body, headers=hdr("tanımsız")).status_code == 401
    assert client.post("/api/inputs", json={"book": "tto"}, headers=hdr("tanımsız")).status_code == 400


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
    assert client.get("/api/scenarios").status_code == 401
    client.post("/api/reset", json={"book": "tto"}, headers=h)


def test_ret_endpoints(client, user):
    h = hdr(user)
    res = client.post("/api/ret", json={"rows": [{"tenor": "1W", "bid": "34,50", "ask": "34,70"}]}, headers=h)
    assert res.status_code == 200 and res.json()["applied"] == 2
    rows = {r["tenor"]: r for r in client.get("/api/ret").json()["rows"]}
    assert rows["1W"]["bid"] == pytest.approx(0.345) and rows["1W"]["ask"] == pytest.approx(0.347)
    hist = client.get("/api/ret/history").json()["history"]
    assert hist and hist[0]["user"] == user
    assert client.post("/api/ret", json={"rows": [{"tenor": "1W", "bid": "34,5"}]}).status_code == 401
    assert client.post("/api/ret", json={"rows": "x"}, headers=h).status_code == 400
    assert client.post("/api/ret", json={"rows": [{"tenor": "99Y", "bid": 1}]}, headers=h).status_code == 400


def test_blotter_endpoints(client, user):
    h = hdr(user)
    q = client.post("/api/blotter/quote/forward", json={"value_date": "15.12.2026", "basis": "RET_ASK", "amount": "5m"}).json()
    assert q["tl"] == 5e6 * q["forward"] and q["value_date_iso"] == "2026-12-15"
    assert client.post("/api/blotter/quote/forward", json={"basis": "RET_MID"}).status_code == 400
    saved = client.post("/api/blotter/forward", json={"dir": "S", "amount": "5m", "value_date": "15.12.2026", "basis": "RET_ASK"}, headers=h)
    assert saved.status_code == 200 and saved.json()["forward"] == q["forward"]
    assert client.post("/api/blotter/forward", json={"dir": "S", "amount": "5m", "value_date": "15.12.2026"}).status_code == 401
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
    assert client.delete("/api/blotter/trade/%d" % first).status_code == 401
    assert client.delete("/api/blotter/trade/%d" % first, headers=h).json()["deleted"] == [first]
    assert client.delete("/api/blotter/trade/%d" % first, headers=h).status_code == 404
    assert client.get("/api/blotter?date=2020-01-01").json()["trades"] == []
    assert client.get("/api/blotter?date=bozuk").status_code == 400


def test_errors_are_json_and_never_tracebacks(client):
    res = client.get("/api/cell?book=tto&ref=bozuk")
    assert res.status_code == 404 and set(res.json()) == {"error"}
    res = client.get("/api/view/masa?user=%s" % quote("çağrı öztürk"))        # user may also come in the query string
    assert res.status_code == 200
