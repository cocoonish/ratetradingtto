"""SQLite persistence: users, personal inputs, scenarios, shared inputs, RET history, blotter; writes in one
transaction, every commit on the disk, the file's check, its backup and restore."""
import os
import sqlite3

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


def test_an_input_typed_as_a_formula_keeps_its_text_beside_its_value(tmp_path):
    """The formula (``=C60+7``) is kept with the input it was typed into, in the same row as its value; a value typed over
    it replaces it; clearing takes it; a scenario keeps it (a fourth item - a scenario of an earlier version has three); a
    meeting's cells moved keep their value without it (its references would not move: the dashboard takes no formula
    there); a formula dropped leaves its value; a database of an earlier version gets the column and keeps its rows.  Every
    write of the inputs is told (the formulas of the dashboard follow what any writer did)."""
    import json
    path = str(tmp_path / "tto.db")
    old = sqlite3.connect(path)                        # an earlier version's tables, without the column
    old.executescript("CREATE TABLE user_inputs (user TEXT NOT NULL, book TEXT NOT NULL, cell TEXT NOT NULL, value TEXT NOT NULL, "
                      "updated_at TEXT NOT NULL, PRIMARY KEY (user, book, cell)); CREATE TABLE shared_inputs (book TEXT NOT NULL, "
                      "cell TEXT NOT NULL, value TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (book, cell));")
    old.execute("INSERT INTO user_inputs VALUES ('ali', 'tto', 'MASA!C60', '46357.0', '2026-11-01 10:00:00')")
    old.commit()
    old.close()
    store = Store(path)
    told = []
    store.on_inputs = lambda user, formulas: told.append((user, formulas))
    try:
        assert store.user_inputs("ali") == {("tto", "MASA!C60"): 46357.0} and store.user_formulas("ali") == {}
        store.set_user_inputs("ali", "tto", {"MASA!C171": 46364.0, "MASA!E60": 46447.0}, {"MASA!C171": "=C60+7"})
        assert store.user_formulas("ali") == {("tto", "MASA!C171"): "=C60+7"} and store.formula_users() == ["ali"]
        assert store.user_inputs("ali", "tto")[("tto", "MASA!C171")] == 46364.0
        assert told[-1] == ("ali", True)
        store.set_user_inputs("ali", "tto", {"MASA!C171": 46400.0})            # a value typed over it
        assert store.user_formulas("ali") == {} and store.formula_users() == [] and told[-1] == ("ali", False)
        store.set_user_inputs("ali", "tto", {"OIS_MAIN!U11": -50.0}, {"OIS_MAIN!U11": "=-25*2"})
        store.save_scenario("ali", "S", store.user_inputs("ali"), store.user_formulas("ali"))
        payload = json.loads(store._q("SELECT payload FROM scenarios")[0]["payload"])
        assert ["tto", "OIS_MAIN!U11", -50.0, "=-25*2"] in payload and ["tto", "MASA!C60", 46357.0] in payload
        moved = store.remap_user_cells("tto", {"OIS_MAIN!U11": "OIS_MAIN!U10"})
        assert moved["moved"] == 1 and told[-1] == ("*", True)
        assert store.user_formulas("ali") == {} and store.user_inputs("ali")[("tto", "OIS_MAIN!U10")] == -50.0
        values, formulas = store.scenario("ali", "S")
        assert formulas == {} and values[("tto", "OIS_MAIN!U10")] == -50.0
        assert store.load_scenario("ali", "S") == values
        assert ("tto", "OIS_MAIN!U10") in store.saved_cells()
        store.set_user_inputs("ali", "tto", {"MASA!J171": 1.0}, {"MASA!J171": "=1"})
        store.drop_formulas("ali", [("tto", "MASA!J171")])
        assert store.user_formulas("ali") == {} and store.user_inputs("ali")[("tto", "MASA!J171")] == 1.0
        store.save_scenario("ali", "S2", {("tto", "MASA!J171"): 1.0}, {("tto", "MASA!J171"): "=1"})
        assert store.scenario("ali", "S2") == ({("tto", "MASA!J171"): 1.0}, {("tto", "MASA!J171"): "=1"})
        store.replace_user_inputs("ali", {("tto", "MASA!C171"): 1.0}, {("tto", "MASA!C171"): "=1"})
        assert store.user_formulas("ali") == {("tto", "MASA!C171"): "=1"} and told[-1] == ("ali", True)
        store.clear_user_inputs("ali", "tto", ["MASA!C171"])
        assert store.user_formulas("ali") == {} and told[-1] == ("ali", False)
        store.set_shared_inputs("tto", {"MASA!R161": 30.0}, "ali", {"MASA!R161": "=R160-5"})
        assert store.shared_formulas() == {("tto", "MASA!R161"): "=R160-5"} and told[-1] == (None, True)
        store.set_shared_inputs("tto", {"MASA!R161": 31.0}, "veli")
        assert store.shared_formulas("tto") == {} and store.shared_inputs() == {("tto", "MASA!R161"): 31.0}
        store.clear_shared_inputs("tto", ["MASA!R161"])
        assert told[-1] == (None, False)
    finally:
        store.close()


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


# ====================================================================================== the file: consistency, check, backup
def _refuse(store, table, when, op="UPDATE"):
    """The database refuses one write (as a full disk or an I/O error would): a trigger aborts it."""
    store._db.execute("CREATE TRIGGER refuse_%s BEFORE %s ON %s WHEN %s BEGIN SELECT RAISE(ABORT, 'disk dolu'); END"
                      % (table, op, table, when))


def test_a_write_that_fails_half_way_leaves_nothing_behind(store):
    """A package's legs, a pasted chat, an account: written in several steps, kept together or not at all."""
    import sqlite3
    # a package of OIS legs whose second leg cannot be written: no leg is kept
    _refuse(store, "trades", "NEW.payload LIKE '%2Y%'", "INSERT")
    with pytest.raises(sqlite3.DatabaseError):
        store.add_trades("2026-11-12", "ois", [{"tenor": "1Y"}, {"tenor": "2Y"}, {"tenor": "3Y"}], "veli", package="p9")
    assert store.trades("2026-11-12") == []
    store._db.execute("DROP TRIGGER refuse_trades")
    ids = store.add_trades("2026-11-12", "ois", [{"tenor": "1Y"}, {"tenor": "2Y"}], "veli", package="p1")
    assert [t["id"] for t in store.trades("2026-11-12")] == ids and len(ids) == 2
    # deleting the package: the second leg's write fails - the first leg is not left deleted alone
    _refuse(store, "trades", "NEW.deleted = 1 AND OLD.id = %d" % ids[1])
    with pytest.raises(sqlite3.DatabaseError):
        store.delete_trade(ids[0], "ali")
    assert [t["id"] for t in store.trades("2026-11-12")] == ids
    store._db.execute("DROP TRIGGER refuse_trades")
    assert store.delete_trade(ids[0], "ali") == ids and store.trades("2026-11-12") == []
    # a chat pasted: its third line cannot be kept - none of the paste is; pasted again, all of it is new
    rows = [{"date": "2026-11-12", "time": "10:0%d" % i, "mark": "m%d" % i, "raw": "satır %d" % i} for i in range(4)]
    _refuse(store, "broker_quotes", "NEW.mark = 'm2'", "INSERT")
    with pytest.raises(sqlite3.DatabaseError):
        store.add_broker_quotes(rows, "ali")
    assert store.broker_quotes("2026-11-12") == []
    store._db.execute("DROP TRIGGER refuse_broker_quotes")
    assert store.add_broker_quotes(rows, "ali")[1] == 0 and len(store.broker_quotes("2026-11-12")) == 4
    # a line the code itself cannot store (not JSON): the transaction is rolled back the same way
    with pytest.raises(TypeError):
        store.add_broker_quotes([{"date": "2026-11-13", "time": "09:00", "mark": "a"},
                                 {"date": "2026-11-13", "time": "09:01", "mark": "b", "bad": {1, 2}}], "ali")
    assert store.broker_quotes("2026-11-13") == []
    # an account removed: its sessions and the account go together
    store.create_account("Silinecek", None, status="pending")
    store.add_session("tok", "silinecek", "2099-01-01 00:00:00")
    _refuse(store, "users", "OLD.name = 'silinecek'", "DELETE")
    with pytest.raises(sqlite3.DatabaseError):
        store.delete_account("silinecek")
    assert store.account("silinecek") is not None                       # neither the account ...
    assert store._q("SELECT COUNT(*) AS n FROM sessions WHERE user='silinecek'")[0]["n"] == 1     # ... nor its session went
    store._db.execute("DROP TRIGGER refuse_users")
    store.delete_account("silinecek")
    assert store.account("silinecek") is None
    assert store._q("SELECT COUNT(*) AS n FROM sessions WHERE user='silinecek'")[0]["n"] == 0
    # a transaction inside another joins it; nothing is left open after an error
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.add_trades("2026-11-14", "fwd", [{"dir": "B"}], "ali")
            raise RuntimeError("vazgeçildi")
    assert store.trades("2026-11-14") == [] and not store._db.in_transaction


def test_values_follow_what_their_row_is_about_in_one_transaction(store):
    """``move_values`` (the lists of bonds, ``tto/rowkeys.py``): every user's values, the desk's and the saved scenarios'
    of the rows that changed go to their new cell or go; a value moved onto a cell that holds one does not replace it; a
    formula does not move; the key cells written and the list kept with them - all of it, or (a write refused half way)
    none of it."""
    import json
    told = []
    store.on_inputs = lambda user, formulas: told.append((user, formulas))
    store.set_user_inputs("ali", "tto", {"DİBS RV!N8": 98.5, "DİBS RV!H8": 2.0, "DİBS RV!N9": 99.0, "MASA!C60": 1.0},
                          {"DİBS RV!H8": "=1+1"})
    store.set_user_inputs("veli", "tto", {"DİBS RV!AL8": 40.0, "DİBS RV!AL29": 41.0})
    store.set_shared_inputs("tto", {"DİBS RV!A8": "X", "DİBS RV!B8": "ISL0"}, "masa")
    store.save_scenario("ali", "S", {("tto", "DİBS RV!N8"): 97.0, ("tto", "DİBS RV!N9"): 96.0, ("tto", "MASA!C60"): 1.0},
                        {("tto", "DİBS RV!N8"): "=97"})
    moves = {"DİBS RV!N8": "DİBS RV!N29", "DİBS RV!H8": "DİBS RV!H29", "DİBS RV!AL8": "DİBS RV!AL29",
             "DİBS RV!B8": "DİBS RV!B29", "DİBS RV!N9": None}
    res = store.move_values("tto", lambda c: moves.get(c, False), keys={"DİBS RV!A29": "X", "DİBS RV!A8": None},
                            by="masa", put=[("rowkeys.deneme", {"29": "X"})])
    assert set(res["moved"]) == {("ali", "DİBS RV!H8", "DİBS RV!H29", 2.0), ("ali", "DİBS RV!N8", "DİBS RV!N29", 98.5),
                                 (None, "DİBS RV!B8", "DİBS RV!B29", "ISL0")}
    assert set(res["dropped"]) == {("ali", "DİBS RV!N9"), ("veli", "DİBS RV!AL8")}          # (veli's AL29 stays)
    assert (res["scenarios"], res["scenario_moved"], res["scenario_dropped"]) == (1, 1, 1)
    assert store.user_inputs("ali", "tto") == {("tto", "DİBS RV!N29"): 98.5, ("tto", "DİBS RV!H29"): 2.0, ("tto", "MASA!C60"): 1.0}
    assert store.user_formulas("ali") == {}                                                  # (a value moves, not a formula)
    assert store.user_inputs("veli", "tto") == {("tto", "DİBS RV!AL29"): 41.0}
    assert store.shared_inputs("tto") == {("tto", "DİBS RV!A8"): None, ("tto", "DİBS RV!A29"): "X", ("tto", "DİBS RV!B29"): "ISL0"}
    assert store.shared_meta("tto", ["DİBS RV!A29"])["updated_by"] == "masa"
    assert store.scenario("ali", "S") == ({("tto", "DİBS RV!N29"): 97.0, ("tto", "MASA!C60"): 1.0}, {})
    assert store.get("rowkeys.deneme") == {"29": "X"} and ("*", True) in told
    # a write refused half way (a full disk): nothing moved, nothing written, the list not kept
    before = (store.user_inputs("ali"), store.shared_inputs(), store._q("SELECT payload FROM scenarios")[0]["payload"])
    _refuse(store, "user_inputs", "NEW.cell = 'DİBS RV!N8'", "INSERT")
    with pytest.raises(sqlite3.DatabaseError):
        store.move_values("tto", lambda c: {"DİBS RV!N29": "DİBS RV!N8", "DİBS RV!H29": "DİBS RV!H8",
                                            "DİBS RV!B29": "DİBS RV!B8"}.get(c, False),
                          keys={"DİBS RV!A8": "X", "DİBS RV!A29": None}, put=[("rowkeys.deneme", {"8": "X"})])
    assert (store.user_inputs("ali"), store.shared_inputs(), store._q("SELECT payload FROM scenarios")[0]["payload"]) == before
    assert store.get("rowkeys.deneme") == {"29": "X"} and not store._db.in_transaction
    assert json.loads(before[2])                                                             # (a scenario's payload as kept)


def test_every_commit_is_on_the_disk(store):
    assert store._q("PRAGMA synchronous")[0][0] == 2                 # FULL
    assert store._q("PRAGMA journal_mode")[0][0] == "wal"


def test_a_backup_is_a_consistent_copy_that_can_be_restored(tmp_path):
    from tto.store import restore
    path = str(tmp_path / "data" / "tto.db")
    s = Store(path)
    s.login("Ali")
    tid = s.add_trade("2026-11-12", "fwd", {"dir": "B", "amount": 1e6}, "ali")
    s.set_shared_inputs("tto", {"Forward!W33": 0.351}, "ali")
    res = s.backup_to(str(tmp_path / "yedek" / "tto-2026-11-12.db"))
    assert res["bytes"] > 0 and os.path.exists(res["path"])
    # one file (no write-ahead log of its own, nothing half written beside it): it can be copied off as it is
    assert sorted(os.listdir(str(tmp_path / "yedek"))) == ["tto-2026-11-12.db"]
    with open(res["path"], "rb") as fh:
        assert fh.read(20)[18:20] == b"\x01\x01"                     # the rollback journal's file format, not WAL's
    # the dashboard goes on: what comes after the backup is not in it
    s.add_trade("2026-11-12", "fwd", {"dir": "S", "amount": 2e6}, "veli")
    s.set_shared_inputs("tto", {"Forward!W33": 0.36}, "veli")
    copy = Store(res["path"])
    assert [t["id"] for t in copy.trades("2026-11-12")] == [tid] and copy.shared_inputs()[("tto", "Forward!W33")] == 0.351
    assert copy.quick_check() == []
    copy.close()
    # restoring needs the dashboard stopped: on Windows an open database cannot be moved away
    if os.name == "nt":
        with pytest.raises(ValueError) as err:
            restore(res["path"], path)
        assert "dashboard açık mı" in str(err.value)
        assert len(s.trades("2026-11-12")) == 2                       # nothing changed
    s.close()
    out = restore(res["path"], path)
    assert out["kept"] and os.path.exists(out["kept"])
    back = Store(path)
    assert [t["id"] for t in back.trades("2026-11-12")] == [tid] and back.user_exists("ali")
    back.close()
    # what was replaced is kept beside it, whole
    before = Store(out["kept"])
    assert len(before.trades("2026-11-12")) == 2 and before.shared_inputs()[("tto", "Forward!W33")] == 0.36
    before.close()
    # a file that is not a sound backup of this dashboard is refused, and nothing is touched
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"bu bir veritabani degil" * 100)
    for bad in (str(junk), str(tmp_path / "yok.db")):
        with pytest.raises(ValueError):
            restore(bad, path)
    other = sqlite3.connect(str(tmp_path / "other.db"))
    other.execute("CREATE TABLE x (a)")
    other.close()
    with pytest.raises(ValueError) as err:
        restore(str(tmp_path / "other.db"), path)
    assert "TTO Masa veritabanı değil" in str(err.value)
    again = Store(path)
    assert [t["id"] for t in again.trades("2026-11-12")] == [tid]
    again.close()


def damage(path: str) -> None:
    """Overwrite the head of the file's last page (a page of the daily history, written last): the dashboard still
    opens - only a check reads that page - but the file is no longer sound."""
    size = os.path.getsize(path)
    with open(path, "r+b") as fh:
        fh.seek((size // 4096 - 1) * 4096)
        fh.write(b"\xff" * 64)


def fill_history(s: Store) -> None:
    s.hist_upsert("TEST|PX_LAST", [("2026-%02d-%02d" % (1 + i // 28, 1 + i % 28), float(i)) for i in range(300)])


def test_the_check_finds_a_damaged_file(tmp_path):
    path = str(tmp_path / "tto.db")
    s = Store(path)
    fill_history(s)
    assert s.quick_check() == []
    s.close()
    damage(path)
    s = Store(path)                         # it opens (the history it cannot read into memory is read from the file)
    assert s._memory is False
    found = s.quick_check()
    assert found and found != ["ok"]
    with pytest.raises(sqlite3.DatabaseError):                        # ... and a backup of it is refused, not kept
        s.backup_to(str(tmp_path / "yedek" / "tto-2026-11-12.db"))
    assert not os.listdir(str(tmp_path / "yedek"))
    s.close()


def test_the_nightly_backups_are_taken_when_due_and_thirty_are_kept(tmp_path, monkeypatch):
    import datetime as _dt
    import time as _time
    from types import SimpleNamespace

    from tto import ops as ops_mod
    from tto.config import Settings
    settings = Settings(data_dir=str(tmp_path / "data"))
    assert settings.backup_dir == os.path.join(str(tmp_path / "data"), "backups") and settings.backup_time == "17:30"
    s = Store(settings.db_path)
    s.login("Ali")
    svc = SimpleNamespace(store=s, settings=settings, started_at=_time.time() - 3600)
    o = ops_mod.Ops(svc)
    folder = settings.backup_dir
    day = _dt.date(2026, 11, 16)
    at = lambda h, m=0: _dt.datetime.combine(day, _dt.time(h, m))          # noqa: E731
    # no backup at all: one as soon as the dashboard has run five minutes (not at its very start)
    assert o.backup_due(at(9))
    svc.started_at = _time.time() - 60
    assert not o.backup_due(at(9))
    svc.started_at = _time.time() - 3600
    os.makedirs(folder)

    def put(name, when):
        path = os.path.join(folder, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        os.utime(path, (_time.mktime(when.timetuple()),) * 2)

    put("tto-2026-11-16.db", at(8))                  # taken this morning (the day before, the machine was off)
    assert not o.backup_due(at(17, 29)) and o.backup_due(at(17, 30)) and o.backup_due(at(23, 30))
    put("tto-2026-11-16.db", at(17, 31))             # this evening's
    assert not o.backup_due(at(23, 30))
    os.remove(os.path.join(folder, "tto-2026-11-16.db"))
    put("tto-2026-11-14.db", _dt.datetime(2026, 11, 14, 22, 0))
    assert o.backup_due(at(9))                       # nothing for more than a day: the missed one now
    # the copy itself, and only the newest 30 kept - nothing else in the folder is touched
    for k in range(35):
        put("tto-2026-%02d-%02d.db" % (9 + k // 28, 1 + k % 28), _dt.datetime(2026, 9, 1) + _dt.timedelta(days=k))
    put("notlar.txt", at(8))
    res = o.backup_now()
    names = sorted(os.listdir(folder))
    assert len([n for n in names if n.startswith("tto-")]) == 30 and "notlar.txt" in names
    assert "tto-%s.db" % _dt.date.today().isoformat() in names and len(res["removed"]) == 7
    copy = Store(res["path"])
    assert copy.user_exists("ali")
    copy.close()
    st = o.db_status()
    assert st["backup"]["count"] == 30 and st["backup"]["last"]["name"] == "tto-%s.db" % _dt.date.today().isoformat()
    assert st["backup"]["error"] is None
    # a backup that fails is said and tried again only after a while
    monkeypatch.setattr(s, "backup_to", lambda path: (_ for _ in ()).throw(OSError("disk dolu")))
    with pytest.raises(OSError):
        o.backup_now()
    assert o.db_status()["backup"]["error"]["text"] == "OSError: disk dolu"
    assert not o.backup_due(at(23, 30))
    s.close()


def test_restoring_from_the_command_line(tmp_path, capsys):
    from tto.__main__ import main
    data = tmp_path / "data"
    s = Store(str(data / "tto.db"))
    s.login("Ali")
    s.backup_to(str(data / "backups" / "tto-2026-11-14.db"))
    s.login("Veli")
    s.close()
    assert main(["yedekten-don", "--data-dir", str(data)]) == 0               # without a file: the list
    out = capsys.readouterr().out
    assert "tto-2026-11-14.db" in out and "yedekten-don <dosya>" in out
    assert main(["yedekten-don", str(data / "backups" / "tto-2026-11-14.db"), "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert "geri getirildi" in out and "Önceki hali silinmedi" in out
    back = Store(str(data / "tto.db"))
    assert back.user_exists("ali") and not back.user_exists("veli")
    back.close()
    assert main(["yedekten-don", str(tmp_path / "yok.db"), "--data-dir", str(data)]) == 2


def test_the_second_copy_goes_to_another_drive_only_for_the_installed_dashboard(tmp_path, monkeypatch):
    """D:\\tto-yedek by default - for the installed dashboard only (no git checkout, its own data folder): a checkout
    (a developer's, the tests') or another data folder never writes over the desk's copies unless asked.  (A machine
    without a D: drive: test_backup.py.)"""
    from tto import config
    from tto.config import DEFAULT_BACKUP_COPY_DIR, Settings, backup_copy_default
    monkeypatch.setattr(config, "drive_exists", lambda path: True)
    installed = tmp_path / "kurulum"
    (installed / "data").mkdir(parents=True)
    assert DEFAULT_BACKUP_COPY_DIR == "D:\\tto-yedek"
    assert backup_copy_default(str(installed / "data"), root=str(installed), windows=True) == "D:\\tto-yedek"
    assert backup_copy_default(str(tmp_path / "baska"), root=str(installed), windows=True) is None      # another data folder
    assert backup_copy_default(str(installed / "data"), root=str(installed), windows=False) is None
    (installed / ".git").mkdir()
    assert backup_copy_default(str(installed / "data"), root=str(installed), windows=True) is None      # a checkout
    monkeypatch.delenv("TTO_BACKUP_COPY_DIR", raising=False)
    assert Settings(data_dir=str(tmp_path / "data")).backup_copy_dir is None
    assert Settings(data_dir=str(tmp_path / "data"), backup_copy_dir=str(tmp_path / "E")).backup_copy_dir == str(tmp_path / "E")
    monkeypatch.setenv("TTO_BACKUP_COPY_DIR", str(tmp_path / "F"))
    assert Settings(data_dir=str(tmp_path / "data")).backup_copy_dir == str(tmp_path / "F")
    assert Settings(data_dir=str(tmp_path / "data"), backup_copy_dir="").backup_copy_dir is None        # "": none


def test_the_nightly_backup_keeps_a_second_copy_and_never_fails_because_of_it(tmp_path, caplog):
    import datetime as _dt
    import logging
    import time as _time
    from types import SimpleNamespace

    from tto import ops as ops_mod
    from tto.config import Settings
    copies = tmp_path / "D" / "tto-yedek"
    settings = Settings(data_dir=str(tmp_path / "data"), backup_copy_dir=str(copies))
    s = Store(settings.db_path)
    s.login("Ali")
    svc = SimpleNamespace(store=s, settings=settings, started_at=_time.time() - 3600, mode="replay")
    o = ops_mod.Ops(svc)
    # the night's backup, and its second copy under the same name (the folder is made when missing)
    res = o.backup_now(_dt.date(2026, 11, 14))
    copy = res["copy"]
    assert copy["path"] == str(copies / "tto-2026-11-14.db") and os.path.getsize(copy["path"]) == res["bytes"]
    second = Store(copy["path"])
    assert second.user_exists("ali") and second.quick_check() == []
    second.close()
    # the same 30 kept there - nothing else in the folder is touched
    for k in range(35):
        (copies / ("tto-2026-%02d-%02d.db" % (9 + k // 28, 1 + k % 28))).write_bytes(b"x")
    (copies / "notlar.txt").write_text("kalır")
    res = o.backup_now(_dt.date(2026, 11, 15))
    names = sorted(os.listdir(str(copies)))
    assert len([n for n in names if n.startswith("tto-")]) == 30 and "notlar.txt" in names and "tto-2026-11-15.db" in names
    assert len(res["copy"]["removed"]) == 7
    st = o.db_status()["backup"]["copy"]
    assert (st["dir"], st["count"], st["last"]["name"], st["error"], st["failed_nights"]) == (str(copies), 30, "tto-2026-11-15.db", None, 0)
    # the drive is gone (here: a file where the folder should be): the backup itself is taken, the copy's failure is
    # logged once - not every night - and shown; one night is no alarm, the second night in a row is
    blocker = tmp_path / "Q"
    blocker.write_text("bir dosya, klasör değil")
    settings.backup_copy_dir = str(blocker / "tto-yedek")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="tto.ops"):
        res = o.backup_now(_dt.date(2026, 11, 16))
        assert os.path.exists(res["path"]) and o.backup_error is None and res["copy"]["failed_nights"] == 1
        assert o.db_status()["backup"]["error"] is None
        st = o.db_status()["backup"]["copy"]
        assert st["failed_nights"] == 1 and st["error"]["text"] and st["count"] == 0
        assert o.system_checks(_dt.datetime(2026, 11, 16, 23, 0))["db"]["state"] == "ok"           # one night: the status only
        o.backup_now(_dt.date(2026, 11, 16))                                                       # (the same night again)
        assert o.copy_state()["failed_days"] == ["2026-11-16"]
        res = o.backup_now(_dt.date(2026, 11, 17))
        assert res["copy"]["failed_nights"] == 2
    said = [r for r in caplog.records if "ikinci kopyası alınamadı" in r.getMessage()]
    assert len(said) == 1 and said[0].levelno == logging.WARNING
    db = o.system_checks(_dt.datetime(2026, 11, 17, 23, 0))["db"]
    assert db["state"] == "alarm" and "ikinci kopyası 2 gündür alınamadı" in db["text"]
    # the drive back: the copy works again, the alarm's condition ends, the log says so
    settings.backup_copy_dir = str(copies)
    with caplog.at_level(logging.INFO, logger="tto.ops"):
        res = o.backup_now(_dt.date(2026, 11, 18))
    assert res["copy"]["path"] == str(copies / "tto-2026-11-18.db") and o.copy_state()["failed_days"] == []
    assert any("ikinci kopyası yeniden alınıyor" in r.getMessage() for r in caplog.records)
    assert o.system_checks(_dt.datetime(2026, 11, 18, 23, 0))["db"]["state"] == "ok"
    assert o.db_status()["backup"]["copy"]["error"] is None
    # a second folder that is the backup folder itself is refused (a copy of nothing), the backup stands
    settings.backup_copy_dir = settings.backup_dir
    res = o.backup_now(_dt.date(2026, 11, 19))
    assert os.path.exists(res["path"]) and "yedek klasörünün kendisi" in res["copy"]["error"]["text"]
    # no second folder: no copy, nothing said about one
    settings.backup_copy_dir = None
    assert o.backup_now(_dt.date(2026, 11, 20))["copy"] is None and o.db_status()["backup"]["copy"] is None
    s.close()


def test_restoring_from_either_folder(tmp_path, capsys):
    """``yedekten-don`` lists the backups and their second copies, and takes a file from either folder - by its
    path, or by its name alone."""
    import shutil
    from tto.__main__ import main
    data, copies = tmp_path / "data", tmp_path / "D" / "tto-yedek"
    s = Store(str(data / "tto.db"))
    s.login("Ali")
    s.backup_to(str(data / "backups" / "tto-2026-11-14.db"))
    s.login("Veli")
    s.backup_to(str(tmp_path / "gecici.db"))
    s.login("Ayşe")
    s.close()
    copies.mkdir(parents=True)
    shutil.copyfile(str(tmp_path / "gecici.db"), str(copies / "tto-2026-11-13.db"))      # only among the second copies
    common = ["--data-dir", str(data), "--backup-copy-dir", str(copies)]
    assert main(["yedekten-don"] + common) == 0
    out = capsys.readouterr().out
    assert "Yedekler (%s)" % (data / "backups") in out and "İkinci kopyalar (%s)" % copies in out
    assert "tto-2026-11-14.db" in out and "tto-2026-11-13.db" in out
    assert main(["yedekten-don", "tto-2026-11-13.db"] + common) == 0                     # a name: found in the second folder
    assert str(copies / "tto-2026-11-13.db") in capsys.readouterr().out
    back = Store(str(data / "tto.db"))
    assert back.user_exists("veli") and not back.user_exists("ayşe")
    back.close()
    assert main(["yedekten-don", "tto-2026-11-14.db"] + common) == 0                     # ... or in the first
    back = Store(str(data / "tto.db"))
    assert back.user_exists("ali") and not back.user_exists("veli")
    back.close()
    assert main(["yedekten-don", "tto-2026-01-01.db"] + common) == 2                     # in neither


def test_what_the_history_polls_is_kept_until_the_history_changes(store, monkeypatch):
    """The settings page polls the history's status: the first and last day and the count of every series and the
    computed MPC days come from memory (the file is not asked: a GROUP BY over every close each time was a full scan)
    and follow every write."""
    store.hist_upsert("A Index|PX_LAST", [("2026-01-02", 1.0), ("2026-01-05", 2.0)])
    store.mpc_save("2026-01-05", "close", {"status": "OK"}, [])
    asked = []
    real = store._q
    monkeypatch.setattr(store, "_q", lambda sql, args=(): (asked.append(sql.split()[0:3]), real(sql, args))[1])
    for _ in range(3):
        assert store.hist_bounds() == {"A Index|PX_LAST": ("2026-01-02", "2026-01-05", 2)}
        assert list(store.mpc_days()) == ["2026-01-05"]
    assert asked == []
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


def test_the_history_is_read_from_memory_and_follows_every_write(tmp_path, monkeypatch):
    """The history's tables - the closes, the watch's own closes, the meeting pricing - are read from the file once, as
    it is opened, and answered from memory after that: SQLite gave the interpreter up on every row it read, and while
    the quant or the backtest ran each row waited for it again (a heat map's closes held the calculation thread for
    half a minute).  Every write is seen at once and exactly as the file holds it (a -0.0 as SQLite keeps it, a whole
    number as a float, a NaN as nothing) - one inside a transaction once it is committed."""
    import store_sql as q

    path = str(tmp_path / "tto.db")
    st = Store(path)
    st.hist_upsert("A|PX_LAST", [("2026-11-02", 35.5), ("2026-11-03", -0.0), ("2026-11-04", 36)])
    st.hist_upsert("B|PX_LAST", [("2026-10-30", float("inf")), ("2026-11-03", 1e-300)])
    st.hist_upsert("A|PX_LAST", [("2026-11-03", 35.25), ("2026-11-01", 35.0)])        # one changed, one before the others
    with pytest.raises(sqlite3.IntegrityError):
        st.hist_upsert("A|PX_LAST", [("2026-11-05", float("nan"))])                      # refused: nothing kept
    st.close_upsert([("cell|tto|X1", "2026-11-03", 2), ("viop|ticker=A", "2026-11-03", -0.0), ("cell|tto|X1", "2026-11-03", 7.25),
                     ("cell|tto|X2", "2026-11-02", 1.5), ("cell|tto|X2", "2026-11-03", 1.75)])
    rows = [{"meeting": "2026-12-11", "step": -0.0, "level": 0.37, "cum": None, "sigma": float("nan"), "front": True},
            {"meeting": "2026-12-10", "step": -150.25, "level": 1, "cum": 2.5, "sigma": 3.0}]
    st.mpc_save("2026-11-03", "b1", {"spot": "2026-11-04", "tlref": 39, "decision": True, "quotes": 18, "status": "OK",
                                     "control": -0.0, "carried": 2, "cleaned": ""}, rows)

    class Odd(float):                    # a value of no plain kind (as numpy's would be): the day is read back from the file
        pass

    st.mpc_save("2026-11-04", "b2", {"spot": "2026-11-05", "tlref": Odd(39.5), "quotes": 17, "status": "OK"},
                [dict(r, step=Odd(-1.0)) for r in rows])
    import datetime as _dt
    st.hist_upsert("D|PX_LAST", [(_dt.date(2026, 11, 2), 4.5)])       # a day that is no text: the copy is read again
    windows = [(None, None), ("2026-11-02", None), (None, "2026-11-03"), ("2026-11-03", "2026-11-03"), ("", ""),
               ("2027-01-01", "2027-12-31")]
    series = ["A|PX_LAST", "B|PX_LAST", "C|PX_LAST", "A|PX_LAST", "D|PX_LAST"]
    subjects = ["cell|tto|X1", "viop|ticker=A", "cell|tto|X2", "cell|tto|X3"]

    def reads(s, sql=False):
        r = q if sql else None

        def ask(name, *args):
            return getattr(r, name)(s, *args) if sql else getattr(s, name)(*args)

        out = [ask("hist_bounds"), ask("mpc_values", None, None, ["2026-12-10"]), ask("mpc_values", None, None, [])]
        for a, b in windows:
            out += [ask("hist_many", series, a, b), ask("hist_series", "A|PX_LAST", a, b), ask("closes", subjects, a, b),
                    ask("mpc_days", a, b), ask("mpc_values", a, b)]
        return out

    q.same(reads(st), reads(st, sql=True))
    assert st.hist_many(["A|PX_LAST"])["A|PX_LAST"] == {"2026-11-01": 35.0, "2026-11-02": 35.5, "2026-11-03": 35.25, "2026-11-04": 36.0}
    assert st.mpc_values("2026-11-04", "2026-11-04")[0]["step"] == -1.0 and st.mpc_days()["2026-11-04"]["tlref"] == 39.5
    # ... and never from the file: no statement on these tables, whatever is read
    with monkeypatch.context() as m:
        seen = q.spy(m, st)
        reads(st)
        assert seen.history() == []
    # a write inside a transaction is seen once it is committed: a rollback takes it back with the file's
    with pytest.raises(RuntimeError):
        with st.transaction():
            st.rename_closes({"cell|tto|X1": "cell|tto|X9"})
            st.hist_delete("B|PX_LAST")
            st.mpc_delete(["2026-11-03"])
            raise RuntimeError("vazgeçildi")
    q.same(reads(st), reads(st, sql=True))
    assert "B|PX_LAST" in st.hist_bounds() and "2026-11-03" in st.mpc_days()
    with st.transaction():
        # a chain, as UPDATE OR REPLACE runs it: X1's closes go to X2 (in place of X2's of the same day), then X2's to X3
        st.rename_closes({"cell|tto|X1": "cell|tto|X2", "cell|tto|X2": "cell|tto|X3"})
        st.hist_delete("B|PX_LAST")
    q.same(reads(st), reads(st, sql=True))
    assert st.closes(["cell|tto|X1", "cell|tto|X2", "cell|tto|X3"]) == {
        "cell|tto|X1": {}, "cell|tto|X2": {}, "cell|tto|X3": {"2026-11-02": 1.5, "2026-11-03": 7.25}}
    st.mpc_save("2026-11-04", "b3", {"status": "HATA", "note": "çözülemedi"}, [])        # a day without its rows
    st.mpc_delete(["2026-11-03", "1999-01-01"])
    q.same(reads(st), reads(st, sql=True))
    kept = reads(st)
    st.close()
    back = Store(path)                                          # opened again: read from the file
    q.same(reads(back), kept)
    back.hist_delete()
    back.mpc_delete()
    q.same(reads(back), reads(back, sql=True))
    assert back.hist_bounds() == {} and back.mpc_days() == {} and back.hist_many(["A|PX_LAST"]) == {"A|PX_LAST": {}}
    back.close()


def test_bloombergs_answers_of_the_day_are_kept_and_the_days_before_go(store):
    from tto.xl.values import XlArray
    key = ("BDS", "TRT150328T24 ISIN", "DES_CASH_FLOW", ())
    rows = XlArray([[46463.0, 184000.0], [46827.0, 1184000.0]])
    store.bbg_keep("2026-11-14", [(("BDP", "X", "NAME", ()), "eski", 1.0)])
    assert store.bbg_keep("2026-11-15", [(key, rows, 1234.5), (("BDP", "TRY Curncy", "SETTLE_DT", ()), 46330.0, 1200.0)]) == 2
    got = {k: (v, t) for k, v, t in store.bbg_answers("2026-11-15")}
    assert got[key][0].rows == rows.rows and got[key][1] == 1234.5
    assert got[("BDP", "TRY Curncy", "SETTLE_DT", ())] == (46330.0, 1200.0)
    assert store.bbg_answers("2026-11-14") == []                        # another day's: gone
    store.bbg_keep("2026-11-15", [(key, rows, 2000.0)])                  # the same key again: replaced
    assert {k: t for k, _, t in store.bbg_answers("2026-11-15")}[key] == 2000.0


def test_bloombergs_hits_of_the_day_by_key_are_kept_and_the_days_before_go(store):
    """The status window's sheets and fields (cache first, 24.11.2026): the day's Bloomberg hits by key, kept for a
    restart - only what changed is written again; another day's go."""
    a, b = ("BDP", "TRY Curncy", "SETTLE_DT", ()), ("HIST", "TYSO1 Curncy", "PX_LAST")
    store.bbg_usage_keep("2026-11-23", [(a, 7)])
    assert store.bbg_usage_keep("2026-11-24", [(a, 1), (b, 4)]) == 2
    assert store.bbg_usage("2026-11-24") == {a: 1, b: 4} and store.bbg_usage("2026-11-23") == {}
    store.bbg_usage_keep("2026-11-24", [(b, 5)])                          # the same key again: replaced
    assert store.bbg_usage("2026-11-24") == {a: 1, b: 5}
