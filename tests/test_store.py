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
    s = Store(path)
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
    assert settings.backup_dir == os.path.join(str(tmp_path / "data"), "backups") and settings.backup_time == "22:00"
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

    put("tto-2026-11-16.db", at(8))                  # taken this morning (the night before, the machine was off)
    assert not o.backup_due(at(21, 59)) and o.backup_due(at(22, 0)) and o.backup_due(at(23, 30))
    put("tto-2026-11-16.db", at(22, 1))              # tonight's
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
