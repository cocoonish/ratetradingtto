"""SQLite persistence: users, personal inputs, scenarios, shared inputs, RET history, blotter."""
import pytest

from tto.store import Store, user_key


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "tto.db"))
    yield s
    s.close()


def test_login_is_by_name_and_case_insensitive(store):
    a = store.login("  Ayşe   Yılmaz ")
    assert a == {"user": "ayşe yilmaz", "display": "Ayşe Yılmaz", "new": True}
    for other in ("AYŞE YILMAZ", "ayşe yılmaz", "ayşe yilmaz", "Ayşe  Yilmaz"):
        b = store.login(other)                 # Turkish I / ı / İ / i all mean the same person
        assert b["user"] == a["user"] and b["new"] is False and b["display"] == "Ayşe Yılmaz"
    assert user_key("  Ali  VELİ ") == "ali veli"
    assert user_key("IŞIL") == user_key("ışıl") == user_key("Işıl")
    assert [u["display"] for u in store.users()] == ["Ayşe Yılmaz"]
    assert store.user_exists(user_key("Ayşe Yılmaz")) and not store.user_exists("kimse")


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_bad_names(store, name):
    with pytest.raises(ValueError):
        store.login(name)


def test_personal_inputs_roundtrip(store):
    store.set_user_inputs("ali", "tto", {"Forward!D2": 46371.0, "OIS_MAIN!B3": "Baz", "MASA!C60": None})
    store.set_user_inputs("ali", "sofr", {"SOFR_FOMC!B9": 25.0})
    store.set_user_inputs("veli", "tto", {"Forward!D2": 1.0})
    assert store.user_inputs("ali", "tto") == {("tto", "Forward!D2"): 46371.0, ("tto", "OIS_MAIN!B3"): "Baz", ("tto", "MASA!C60"): None}
    assert len(store.user_inputs("ali")) == 4
    store.set_user_inputs("ali", "tto", {"Forward!D2": 46400.0})            # overwrite
    assert store.user_inputs("ali", "tto")[("tto", "Forward!D2")] == 46400.0
    store.clear_user_inputs("ali", "tto", ["Forward!D2"])
    assert ("tto", "Forward!D2") not in store.user_inputs("ali")
    store.clear_user_inputs("ali", "tto")
    assert store.user_inputs("ali") == {("sofr", "SOFR_FOMC!B9"): 25.0}
    assert store.user_inputs("veli") == {("tto", "Forward!D2"): 1.0}        # other users untouched


def test_scenarios_belong_to_the_user(store):
    values = {("tto", "Forward!D2"): 46371.0, ("sofr", "SOFR_FOMC!B9"): 50.0}
    store.save_scenario("ali", "  PPK   -250 ", values)
    store.save_scenario("ali", "Baz", {})
    store.save_scenario("veli", "Baz", {("tto", "MASA!C60"): 1.0})
    assert [s["name"] for s in store.scenarios("ali")] == ["Baz", "PPK -250"]
    assert store.scenarios("ali")[1]["cells"] == 2
    assert store.load_scenario("ali", "PPK -250") == values
    assert store.load_scenario("veli", "PPK -250") is None
    store.save_scenario("ali", "PPK -250", {("tto", "Forward!D2"): 1.0})    # same name overwrites
    assert store.load_scenario("ali", "PPK -250") == {("tto", "Forward!D2"): 1.0}
    assert store.delete_scenario("ali", "Baz") is True
    assert store.delete_scenario("ali", "Baz") is False
    assert [s["name"] for s in store.scenarios("veli")] == ["Baz"]
    with pytest.raises(ValueError):
        store.save_scenario("ali", " ", {})


def test_shared_inputs_and_meta(store):
    store.set_shared_inputs("tto", {"Forward!W33": 0.351, "Forward!X33": 0.353}, "ali")
    store.set_shared_inputs("tto", {"Forward!W33": 0.36}, "veli")
    assert store.shared_inputs("tto") == {("tto", "Forward!W33"): 0.36, ("tto", "Forward!X33"): 0.353}
    meta = store.shared_meta("tto", ["Forward!W33", "Forward!X33"])
    assert meta["updated_by"] in ("ali", "veli") and meta["updated_at"]
    assert store.shared_meta("tto", ["Forward!Z99"]) is None
    store.clear_shared_inputs("tto", ["Forward!W33"])
    assert store.shared_inputs("tto") == {("tto", "Forward!X33"): 0.353}


def test_everything_survives_a_restart(tmp_path):
    path = str(tmp_path / "tto.db")
    s = Store(path)
    s.login("Ali")
    s.set_user_inputs("ali", "tto", {"Forward!D2": 46371.0})
    s.save_scenario("ali", "S1", {("tto", "Forward!D2"): 46371.0})
    s.set_shared_inputs("tto", {"Forward!W33": 0.351}, "ali")
    s.add_ret_history("ali", [{"tenor": "ON", "bid": 0.351, "ask": 0.353}])
    tid = s.add_trade("2026-11-12", "fwd", {"dir": "B", "amount": 1e6}, "ali")
    s.close()
    s2 = Store(path)
    assert s2.user_exists("ali")
    assert s2.user_inputs("ali") == {("tto", "Forward!D2"): 46371.0}
    assert s2.load_scenario("ali", "S1") == {("tto", "Forward!D2"): 46371.0}
    assert s2.shared_inputs() == {("tto", "Forward!W33"): 0.351}
    assert s2.ret_history()[0]["rows"][0]["bid"] == 0.351 and s2.ret_history()[0]["user"] == "ali"
    assert s2.trade(tid)["amount"] == 1e6
    s2.close()


def test_trades_and_packages(store):
    a = store.add_trade("2026-11-12", "fwd", {"dir": "B", "amount": 1e6}, "ali")
    b = store.add_trade("2026-11-12", "ois", {"tenor": "1Y"}, "veli", package="p1")
    c = store.add_trade("2026-11-12", "ois", {"tenor": "2Y"}, "veli", package="p1")
    store.add_trade("2026-11-11", "bond", {"instrument": "X"}, "ali")
    day = store.trades("2026-11-12")
    assert [t["id"] for t in day] == [a, b, c]
    assert day[0]["created_by"] == "ali" and day[1]["package"] == "p1" and day[0]["kind"] == "fwd"
    assert store.trade_dates() == [{"date": "2026-11-12", "count": 3}, {"date": "2026-11-11", "count": 1}]
    assert store.delete_trade(b, "ali") == [b, c]              # the whole package goes
    assert [t["id"] for t in store.trades("2026-11-12")] == [a]
    assert store.delete_trade(b, "ali") == []                  # already gone
    assert store.update_trade(a, {"dir": "S", "amount": 2e6}, "veli") is True
    assert store.trade(a)["amount"] == 2e6
    store.save_blotter_snapshot("2026-11-12", {"sheet": [1, 2]})
    assert store.blotter_snapshot("2026-11-12")["sheet"] == [1, 2]
    assert store.blotter_snapshot("2020-01-01") is None


def test_key_value(store):
    assert store.get("x", 5) == 5
    store.put("x", {"a": [1, 2]})
    assert store.get("x") == {"a": [1, 2]}


def test_what_the_history_polls_is_kept_until_the_history_changes(store, monkeypatch):
    """The settings page polls the history's status: the first and last day and the count of every series (a GROUP BY
    over every close) and the computed MPC days are kept until closes or days are written, not read each time."""
    store.hist_upsert("A Index|PX_LAST", [("2026-01-02", 1.0), ("2026-01-05", 2.0)])
    store.mpc_save("2026-01-05", "close", {"status": "OK"}, [])
    asked = []
    real = store._q
    monkeypatch.setattr(store, "_q", lambda sql, args=(): (asked.append(sql.split()[0:3]), real(sql, args))[1])
    for _ in range(3):
        assert store.hist_bounds() == {"A Index|PX_LAST": ("2026-01-02", "2026-01-05", 2)}
        assert list(store.mpc_days()) == ["2026-01-05"]
    assert len(asked) == 2                                     # once each
    store.hist_upsert("A Index|PX_LAST", [("2026-01-06", 3.0)])
    store.mpc_save("2026-01-06", "close", {"status": "OK"}, [])
    assert store.hist_bounds()["A Index|PX_LAST"] == ("2026-01-02", "2026-01-06", 3)
    assert list(store.mpc_days()) == ["2026-01-05", "2026-01-06"]
    store.hist_delete("A Index|PX_LAST")
    store.mpc_delete()
    assert store.hist_bounds() == {} and store.mpc_days() == {}
    bounds = store.hist_bounds()
    bounds["x"] = 1                                            # (a copy: what is kept is not changed by a caller)
    assert store.hist_bounds() == {}
