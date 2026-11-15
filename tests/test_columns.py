"""The columns a user hides in the tables: kept with the account on the server, so that everybody looks at the tables
their own way - on any computer they sign in from.  (Hiding them on the page is the browser test's.)"""
import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto.server import create_app
from tto.service import ServiceError


def test_each_user_keeps_their_own_hidden_columns(service):
    a = service.login("Sütun Ayşe")["user"]
    b = service.login("Sütun Mehmet")["user"]
    assert service.columns(a) == {"tables": {}}
    # a table of a sheet by its view and panel, a column by its letter; twice the same column is one
    assert service.set_columns(a, "v/dibs/B5", ["B", "K", "B"]) == {"table": "v/dibs/B5", "hidden": ["B", "K"]}
    # one of the dashboard's own tables: a column by its caption
    service.set_columns(a, "eod/curve", ["Offshore · 1A"])
    assert service.columns(a)["tables"] == {"v/dibs/B5": ["B", "K"], "eod/curve": ["Offshore · 1A"]}
    assert service.columns(b) == {"tables": {}}                            # one user's choice is nobody else's
    service.set_columns(b, "v/dibs/B5", ["C"])
    assert service.columns(a)["tables"]["v/dibs/B5"] == ["B", "K"]
    # every column shown again: the table is forgotten
    service.set_columns(a, "v/dibs/B5", [])
    assert service.columns(a)["tables"] == {"eod/curve": ["Offshore · 1A"]}
    assert service.columns(b)["tables"] == {"v/dibs/B5": ["C"]}
    # kept with the account in the dashboard's database: a restart finds them
    assert service.store.get("cols." + a) == {"eod/curve": ["Offshore · 1A"]}


@pytest.mark.parametrize("table, hidden", [
    ("", ["B"]), ("   ", ["B"]), (None, ["B"]), (12, ["B"]), ("x" * 161, ["B"]),
    ("t", "B"), ("t", None), ("t", {"B": 1}), ("t", [""]), ("t", [3]), ("t", ["x" * 161]),
    ("t", ["c%d" % i for i in range(401)]),
])
def test_what_is_not_a_table_and_its_columns_is_refused(service, table, hidden):
    u = service.login("Sütun Hatalı")["user"]
    with pytest.raises(ServiceError) as err:
        service.set_columns(u, table, hidden)
    assert err.value.status == 400
    assert service.columns(u) == {"tables": {}}


def test_a_user_must_be_signed_in(service):
    for call in (lambda: service.columns(None), lambda: service.set_columns(None, "t", ["B"]),
                 lambda: service.columns("hiç olmayan kişi")):
        with pytest.raises(ServiceError) as err:
            call()
        assert err.value.status == 401


def test_how_many_tables_a_user_may_keep(service, monkeypatch):
    monkeypatch.setattr(service, "MAX_COLUMN_TABLES", 2)
    u = service.login("Sütun Çok")["user"]
    service.set_columns(u, "a", ["B"])
    service.set_columns(u, "b", ["B"])
    with pytest.raises(ServiceError):
        service.set_columns(u, "c", ["B"])
    service.set_columns(u, "a", ["C"])                                       # a table already kept may change
    service.set_columns(u, "b", [])
    service.set_columns(u, "c", ["B"])                                       # room again
    assert service.columns(u)["tables"] == {"a": ["C"], "c": ["B"]}


def test_how_much_a_user_may_keep_in_all(service, monkeypatch):
    monkeypatch.setattr(service, "MAX_COLUMN_BYTES", 80)
    u = service.login("Sütun Uzun")["user"]
    service.set_columns(u, "v/dibs/B3", ["B", "C"])
    with pytest.raises(ServiceError) as err:
        service.set_columns(u, "eod/curve", ["TRY OIS · par (%) · Δ1G bp", "TRY OIS · par (%) · Δ1H bp", "Offshore · Son"])
    assert err.value.status == 400 and "çok uzun" in str(err.value)
    assert service.columns(u)["tables"] == {"v/dibs/B3": ["B", "C"]}           # what was kept stays


def test_over_http(service):
    client = TestClient(create_app(service=service))                         # (no "with": the shared service stays up)
    h = auth(service, "Sütun Zeynep")
    assert client.get("/api/columns", headers=h).json() == {"tables": {}}
    r = client.post("/api/columns", json={"table": "fx/board", "hidden": ["1M ATM ±1σ", "1M ↓1σ"]}, headers=h)
    assert r.status_code == 200 and r.json() == {"table": "fx/board", "hidden": ["1M ATM ±1σ", "1M ↓1σ"]}
    assert client.get("/api/columns", headers=h).json() == {"tables": {"fx/board": ["1M ATM ±1σ", "1M ↓1σ"]}}
    assert client.get("/api/columns", headers=auth(service, "Sütun Başkası")).json() == {"tables": {}}
    assert client.post("/api/columns", json={"table": "fx/board", "hidden": "1M"}, headers=h).status_code == 400
    assert client.post("/api/columns", content=b"[]", headers=dict(h, **{"Content-Type": "application/json"})).status_code == 400
    # without a session: nothing, and nothing is changed
    assert client.get("/api/columns", headers=ANON).status_code == 401
    assert client.post("/api/columns", json={"table": "fx/board", "hidden": []}, headers=ANON).status_code == 401
    # a change sent from another page than the dashboard's own is refused
    foreign = dict(h, Origin="http://kotu-site.example")
    assert client.post("/api/columns", json={"table": "fx/board", "hidden": []}, headers=foreign).status_code == 403
    assert client.get("/api/columns", headers=h).json()["tables"] == {"fx/board": ["1M ATM ±1σ", "1M ↓1σ"]}
