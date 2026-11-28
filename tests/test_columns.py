"""The columns a user hides in the tables: kept with the account on the server, so that everybody looks at the tables
their own way - on any computer they sign in from; the columns a table hides until its user chooses (DİBS RV's own FX
swap columns).  (Hiding them on the page is the browser test's.)"""
import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto.server import create_app
from tto.service import Service, ServiceError

#: what a table hides until its user chooses: DİBS RV's own FX swap columns, the quant signal lists' secondary statistics
#: (Düzen, 27.11.2026) - read from the service: the layout builders each add their tables' entries
#: (28.11.2026: a table with presets - DİBS Trading's summary, "Trading / RV / Risk / Tümü" under Sütunlar - opens on its first)
PRESETS = Service.column_presets()
DEFAULTS = dict({t: list(c) for t, c in Service.DEFAULT_HIDDEN_COLUMNS.items()}, **{t: list(p[0]["hide"]) for t, p in PRESETS.items()})
#: what a user who never chose gets
FRESH = {"tables": {}, "defaults": DEFAULTS, "presets": PRESETS}


def _answer(tables, **more):
    """What ``columns`` answers: the tables the user chose for, the defaults of the tables they did not."""
    rest = {t: c for t, c in DEFAULTS.items() if t not in tables}
    return dict({"tables": tables}, **({"defaults": rest} if rest else {}), presets=PRESETS, **more)


def test_each_user_keeps_their_own_hidden_columns(service):
    a = service.login("Sütun Ayşe")["user"]
    b = service.login("Sütun Mehmet")["user"]
    assert service.columns(a) == FRESH
    # a table of a sheet by its view and panel, a column by its letter; twice the same column is one
    assert service.set_columns(a, "v/dibs/B5", ["B", "K", "B"]) == {"table": "v/dibs/B5", "hidden": ["B", "K"]}
    # one of the dashboard's own tables: a column by its caption
    service.set_columns(a, "eod/curve", ["Offshore · 1A"])
    assert service.columns(a)["tables"] == {"v/dibs/B5": ["B", "K"], "eod/curve": ["Offshore · 1A"]}
    assert service.columns(b) == FRESH      # one user's choice is nobody else's
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
    assert service.columns(u) == FRESH


def test_dibs_rvs_own_fx_swap_columns_are_hidden_until_a_user_shows_them(service):
    """DİBS RV's BF:BJ (its FX swap side on the offshore ICAP curve) are hidden by default - the desk reads the FX swap
    side on DİBS ASW's FX swap implied curve (Genel's "FX swap ASW"), the table's note says so.  A user who hides one
    more keeps them all hidden; "show every column" is kept as such (the default does not come back); nobody else's
    view changes.  Nothing of the sheet changes: the cells are there, their values the workbook's."""
    a = service.login("FX Sütun Ayşe")["user"]
    b = service.login("FX Sütun Mehmet")["user"]
    assert service.DEFAULT_HIDDEN_COLUMNS["v/dibs/B3"] == ("Q", "BE", "BF", "BG", "BH", "BI", "BJ")
    assert service.columns(a)["defaults"] == DEFAULTS
    note = next(p for p in service.view(a, "dibs")["panels"] if p["id"] == "B3").get("note") or ""
    assert note.startswith("BF–BJ") and "varsayılan olarak gizli" in note and "Genel" in note and "FX swap ASW" in note
    service.set_columns(a, "v/dibs/B3", DEFAULTS["v/dibs/B3"] + ["B"])                  # (the page sends what it hides now)
    assert service.columns(a) == _answer({"v/dibs/B3": ["Q", "BE", "BF", "BG", "BH", "BI", "BJ", "B"]})
    service.set_columns(a, "v/dibs/B3", [])
    assert service.columns(a) == _answer({"v/dibs/B3": []}) and service.store.get("cols." + a) == {"v/dibs/B3": []}
    assert service.columns(b) == FRESH
    # (another table's empty choice is forgotten, as before)
    service.set_columns(a, "v/dibs/B5", ["C"])
    service.set_columns(a, "v/dibs/B5", [])
    assert service.columns(a)["tables"] == {"v/dibs/B3": []}


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
    assert client.get("/api/columns", headers=h).json() == FRESH
    r = client.post("/api/columns", json={"table": "fx/board", "hidden": ["1M ATM ±1σ", "1M ↓1σ"]}, headers=h)
    assert r.status_code == 200 and r.json() == {"table": "fx/board", "hidden": ["1M ATM ±1σ", "1M ↓1σ"]}
    assert client.get("/api/columns", headers=h).json() == dict(FRESH, tables={"fx/board": ["1M ATM ±1σ", "1M ↓1σ"]})
    assert client.get("/api/columns", headers=auth(service, "Sütun Başkası")).json() == FRESH
    assert client.post("/api/columns", json={"table": "fx/board", "hidden": "1M"}, headers=h).status_code == 400
    assert client.post("/api/columns", content=b"[]", headers=dict(h, **{"Content-Type": "application/json"})).status_code == 400
    # without a session: nothing, and nothing is changed
    assert client.get("/api/columns", headers=ANON).status_code == 401
    assert client.post("/api/columns", json={"table": "fx/board", "hidden": []}, headers=ANON).status_code == 401
    # a change sent from another page than the dashboard's own is refused
    foreign = dict(h, Origin="http://kotu-site.example")
    assert client.post("/api/columns", json={"table": "fx/board", "hidden": []}, headers=foreign).status_code == 403
    assert client.get("/api/columns", headers=h).json()["tables"] == {"fx/board": ["1M ATM ±1σ", "1M ↓1σ"]}


# ---------------------------------------------------------------------- the order of the columns, per user
def test_each_user_puts_the_columns_of_a_table_in_their_own_order(service):
    a = service.login("Sıra Ayşe")["user"]
    b = service.login("Sıra Mehmet")["user"]
    assert "order" not in service.columns(a)                                   # nobody moved a column: the sheet's order
    assert service.set_column_order(a, "v/dibs/B3", ["C", "A", "B", "C"]) == {"table": "v/dibs/B3", "order": ["C", "A", "B"]}
    service.set_columns(a, "v/dibs/B3", ["K"])                                 # hidden and moved: both kept, apart
    assert service.columns(a) == _answer({"v/dibs/B3": ["K"]}, order={"v/dibs/B3": ["C", "A", "B"]})
    assert "order" not in service.columns(b)
    service.set_column_order(b, "v/dibs/B3", ["B"])
    assert service.columns(a)["order"] == {"v/dibs/B3": ["C", "A", "B"]}
    # back to the sheet's order: the table is forgotten, what is hidden stays
    service.set_column_order(a, "v/dibs/B3", [])
    assert service.columns(a) == _answer({"v/dibs/B3": ["K"]})
    assert service.store.get("colorder." + a) == {} and service.store.get("colorder." + b) == {"v/dibs/B3": ["B"]}


@pytest.mark.parametrize("table, order", [
    ("", ["B"]), (None, ["B"]), ("x" * 161, ["B"]), ("t", "B"), ("t", None), ("t", [""]), ("t", [3]),
    ("t", ["c%d" % i for i in range(401)]),
])
def test_what_is_not_an_order_of_columns_is_refused(service, table, order):
    u = service.login("Sıra Hatalı")["user"]
    with pytest.raises(ServiceError) as err:
        service.set_column_order(u, table, order)
    assert err.value.status == 400
    assert "order" not in service.columns(u)


def test_how_many_orders_a_user_may_keep(service, monkeypatch):
    monkeypatch.setattr(service, "MAX_COLUMN_TABLES", 1)
    u = service.login("Sıra Çok")["user"]
    service.set_column_order(u, "a", ["B", "A"])
    with pytest.raises(ServiceError):
        service.set_column_order(u, "b", ["B", "A"])
    monkeypatch.setattr(service, "MAX_COLUMN_BYTES", 30)
    with pytest.raises(ServiceError) as err:
        service.set_column_order(u, "a", ["Uzun bir sütun başlığı", "Bir başkası"])
    assert "çok uzun" in str(err.value)
    assert service.columns(u)["order"] == {"a": ["B", "A"]}


def test_the_order_over_http(service):
    client = TestClient(create_app(service=service))
    h = auth(service, "Sıra Zeynep")
    r = client.post("/api/columns", json={"table": "v/forward/B19", "order": ["X", "W"]}, headers=h)
    assert r.status_code == 200 and r.json() == {"table": "v/forward/B19", "order": ["X", "W"]}
    r = client.post("/api/columns", json={"table": "v/forward/B19", "order": ["W", "X"], "hidden": ["U"]}, headers=h)
    assert r.json() == {"table": "v/forward/B19", "order": ["W", "X"], "hidden": ["U"]}
    assert client.get("/api/columns", headers=h).json() == dict(FRESH, tables={"v/forward/B19": ["U"]}, order={"v/forward/B19": ["W", "X"]})
    assert client.post("/api/columns", json={"table": "v/forward/B19", "order": "X"}, headers=h).status_code == 400
    assert client.post("/api/columns", json={"table": "v/forward/B19", "order": []}, headers=ANON).status_code == 401
