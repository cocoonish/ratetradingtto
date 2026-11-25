"""``python -m tto kurtar`` (tto/recover.py): a damaged copy of a test database (bytes of a page overwritten), the last
backup restored in its place, and what the damaged file still holds added back - by each table's key, nothing that is
there overwritten (but a row whose own time is later, and today's Bloomberg counts); the unreadable rows told by the
tables' indexes, the history's skipped; ``--dene`` changes nothing; the damaged file is never touched; the data
folder's lock is respected; a number given to another row meanwhile; a file SQLite cannot read at all."""
import datetime as _dt
import hashlib
import os
import shutil
import sqlite3
import struct
import time

import pytest

from tto import recover
from tto.__main__ import main
from tto.datadir import DataLock
from tto.store import Store, restore


def leaves(path, table):
    """The leaf pages of a table's b-tree, in key order (the file's own format: interior pages point to their
    children)."""
    con = sqlite3.connect(path)
    root = con.execute("SELECT rootpage FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
    size = con.execute("PRAGMA page_size").fetchone()[0]
    con.close()
    out = []
    with open(path, "rb") as fh:
        def walk(page):
            fh.seek((page - 1) * size)
            data = fh.read(size)
            at = 100 if page == 1 else 0
            if data[at] in (0x0D, 0x0A):                                # a leaf (of a table, of an index)
                out.append(page)
                return
            cells = struct.unpack(">H", data[at + 3:at + 5])[0]
            for k in range(cells):
                ptr = struct.unpack(">H", data[at + 12 + 2 * k:at + 14 + 2 * k])[0]
                walk(struct.unpack(">I", data[ptr:ptr + 4])[0])
            walk(struct.unpack(">I", data[at + 8:at + 12])[0])
        walk(root)
    return out, size


def damage(path, table, which):
    """Overwrite the head of some of a table's leaf pages (``which``: their places in key order); returns how many rows
    they held (their headers' count of cells)."""
    pages, size = leaves(path, table)
    held = 0
    with open(path, "r+b") as fh:
        for i in which:
            fh.seek((pages[i] - 1) * size)
            held += struct.unpack(">H", fh.read(5)[3:5])[0]
            fh.seek((pages[i] - 1) * size)
            fh.write(b"\xff" * 32)
    return held


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


DAY = "2026-11-24"


def desk(tmp_path):
    """The desk's database: a backup taken on the evening before (23.11), then a day of work (24.11) - and the file
    damaged at the end of it: a leaf in the middle of Günlük İşlemler, one of the daily history (a table without
    rowid).  The backup goes back in its place (yedekten-don); the damaged file stays beside it."""
    data = tmp_path / "data"
    db = str(data / "tto.db")
    s = Store(db)
    for name in ("Ali", "Veli", "Ayşe"):
        s.create_account(name, "hash-%s" % name, role="admin" if name == "Ali" else "user")
    for i in range(120):                                               # (about ten a page: twelve pages)
        s.add_trade("2026-11-%02d" % (10 + i % 10), "ois", {"tenor": "1Y", "dv01": 1000 + i, "not": "x" * 300}, "ali")
    s.set_user_inputs("ali", "tto", {"MASA!C60": 1.5, "MASA!D60": 2.5})
    s.set_user_inputs("veli", "tto", {"MASA!C60": 7.0})
    s.set_shared_inputs("tto", {"Forward!W33": 0.351}, "ali")
    s.save_scenario("ali", "baz", {("tto", "MASA!C60"): 1.0})
    s.put("layout.ali", {"pages": ["masa"]})
    s.put("bbg.hits", {"day": "2026-11-23", "hits": 52000})
    s.put("hist.fetch", {"A|PX_LAST": {"day": "2026-11-23", "from": "2025-01-01"}, "B|PX_LAST": {"day": "2026-11-20"}})
    # (about ninety closes a page: the first series' 2 000 days fill the first twenty pages - the damaged one is inside it)
    for k, (first, days) in enumerate([(_dt.date(2020, 1, 1), 2000)] + [(_dt.date(2025, 1, 1), 300)] * 11):
        s.hist_upsert("SERI%02d Index|PX_LAST" % k, [((first + _dt.timedelta(days=d)).isoformat(), float(d)) for d in range(days)])
    s.add_chat("ali", "günaydın")
    s.add_broker_quotes([{"date": "2026-11-23", "time": "10:00", "mark": "m1", "payload": {"text": "1Y 39,50"}}], "ali")
    tb = s.tb_add("desk", "ali", "ois", "2026-11-23", {"dv01": 500}, "ali", {"note": "ilk"})
    s.add_agenda(None, "2026-11-23", "10:00", "PPK", False, "ali")
    backup = s.backup_to(str(data / "backups" / "tto-2026-11-23.db"))["path"]
    time.sleep(1.1)                                                    # (the day's rows a second later)
    # 24.11: trades, a trade changed and one deleted, inputs typed again, a setting, the day's Bloomberg count ...
    new_ids = [s.add_trade(DAY, "ois", {"tenor": "2Y", "dv01": 2000 + i, "not": "y" * 300}, "veli") for i in range(25)]
    s.update_trade(5, {"tenor": "1Y", "dv01": 9999, "not": "düzeltildi"}, "ali")
    s.delete_trade(6, "ali")
    s.set_user_inputs("ali", "tto", {"MASA!C60": 9.5, "MASA!E60": 3.0})
    s.set_shared_inputs("tto", {"Forward!W34": 0.4}, "veli")
    s.create_account("Zeynep", "hash-z")
    s.put("layout.ali", {"pages": ["ois"]})
    s.put("bbg.hits", {"day": DAY, "hits": 61000})
    s.put("hist.fetch", {"A|PX_LAST": {"day": DAY, "from": "2025-01-01"}, "C|PX_LAST": {"day": DAY}})
    s.put("kagitfiyat.widths", {"1y": 10})
    for k in range(12):
        s.hist_upsert("SERI%02d Index|PX_LAST" % k, [(DAY, 99.0)])
    s.add_chat("veli", "işlem tamam")
    s.add_chat("ali", "teşekkürler")
    ids, _ = s.add_broker_quotes([{"date": DAY, "time": "11:%02d" % i, "mark": "n%d" % i, "payload": {"text": "2Y %d" % i}}
                                  for i in range(5)], "veli")
    old_quote = s.broker_quotes("2026-11-23")[0]["id"]
    s.delete_broker_quote(old_quote)
    tb2 = s.tb_add("desk", "veli", "ois", DAY, {"dv01": 700}, "veli", {"note": "yeni"})
    s.tb_put_close(DAY, "17:30", False, [(tb, {"ok": True, "pnl": 1}), (tb2, {"ok": True, "pnl": 2})])
    s.add_agenda("veli", DAY, "15:00", "ihale", True, "veli")
    s.close()
    con = sqlite3.connect(db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    lost_trades = damage(db, "trades", [3])
    lost_closes = damage(db, "hist_values", [9])
    assert lost_trades > 3 and lost_closes > 50
    res = restore(backup, db)                                         # (yedekten-don)
    return {"data": data, "db": db, "damaged": res["kept"], "backup": backup, "new_ids": new_ids, "tb": tb, "tb2": tb2,
            "quotes": ids, "old_quote": old_quote, "lost_trades": lost_trades, "lost_closes": lost_closes}


def test_what_a_damaged_file_still_holds_comes_back(tmp_path, capsys):
    d = desk(tmp_path)
    before = digest(d["damaged"])
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    out = capsys.readouterr().out
    assert digest(d["damaged"]) == before                              # the damaged file: never touched
    s = Store(d["db"])
    try:
        # the day's trades: back with their own numbers; the edited one in its later form, the deleted one deleted
        got = [t["id"] for t in s.trades(DAY)]
        assert got == d["new_ids"]
        assert s.trade_legs(5)[0]["dv01"] == 9999 and s.trade(6) is None
        assert "Günlük İşlemler: 25 işlem (24.11) · 2 işlem güncellendi (bozuk dosyadaki hali daha yeni)" in out
        # the leaf in the middle (rows of the backup) is told by the table's index - none of them lost
        assert "Günlük İşlemler: %d işlem okunamadı" % d["lost_trades"] in out and "kayıp: 0" in out
        assert len(s.trades("2026-11-10", "2026-11-19")) == 120 - 1        # (all of the backup's; #6 deleted on the day)
        # inputs: the later one taken, one the database has newer kept, the new one added
        assert s.user_inputs("ali") == {("tto", "MASA!C60"): 9.5, ("tto", "MASA!D60"): 2.5, ("tto", "MASA!E60"): 3.0}
        assert s.user_inputs("veli") == {("tto", "MASA!C60"): 7.0}
        assert s.shared_inputs() == {("tto", "Forward!W33"): 0.351, ("tto", "Forward!W34"): 0.4}
        assert "kişisel girdiler: 1 girdi (1 kullanıcı) · 1 girdi güncellendi" in out and "ortak girdiler: 1 girdi" in out
        # kv: never overwritten (no time of its own) - but today's Bloomberg count and the history's requests
        assert s.get("layout.ali") == {"pages": ["masa"]} and s.get("kagitfiyat.widths") == {"1y": 10}
        assert s.get("bbg.hits") == {"day": DAY, "hits": 61000}
        assert s.get("hist.fetch") == {"A|PX_LAST": {"day": DAY, "from": "2025-01-01"}, "B|PX_LAST": {"day": "2026-11-20"},
                                       "C|PX_LAST": {"day": DAY}}
        assert "Bloomberg'in bugünkü veri sayacı" in out and "tarihçenin istek kaydı" in out
        assert "Şimdiki hali korunanlar" in out and "layout.ali" in out
        # accounts, chat, Broker Chat (a line deleted on the day stays deleted), Trades with its log and close, agenda
        assert s.account("zeynep") is not None
        msgs = s.chat()[0]
        said = _dt.date.fromisoformat(msgs[-1]["created_at"][:10]).strftime("%d.%m")    # (a chat line is stamped now)
        assert [m["text"] for m in msgs][-2:] == ["işlem tamam", "teşekkürler"] and "chat: 2 mesaj (%s)" % said in out
        assert [q["id"] for q in s.broker_quotes(DAY)] == d["quotes"] and s.broker_quotes("2026-11-23") == []
        assert "Broker Chat: 5 satır (24.11) · 1 satır güncellendi" in out
        assert s.tb_get(d["tb2"])["dv01"] == 700
        assert [r["detail"]["note"] for r in s.tb_log(trade=d["tb2"])] == ["yeni"]
        assert set(s.tb_closes([d["tb"], d["tb2"]])) == {d["tb"], d["tb2"]} and s.tb_close_day(DAY) is not None
        assert [a["text"] for a in s.agenda("veli", DAY)][-1:] == ["ihale"]
        # the history: the leaf that cannot be read is skipped (the backup has those closes), the day's closes come back
        assert all(s.hist_series("SERI%02d Index|PX_LAST" % k, DAY, DAY) == [(DAY, 99.0)] for k in range(12))
        assert "günlük tarihçe: 12 kapanış (24.11)" in out
        assert "günlük tarihçe: okunamayan 1 bölüm var (SERI00 Index|PX_LAST/20" in out
        assert "dashboard eksik günleri kendisi çeker" in out
        assert len(s.hist_series("SERI00 Index|PX_LAST")) == 2001 and len(s.hist_series("SERI05 Index|PX_LAST")) == 301
        assert s.quick_check() == []
    finally:
        s.close()
    # the database as it was before is kept beside it - and a second run adds nothing (nothing is copied either)
    kept = [n for n in os.listdir(str(d["data"])) if n.startswith("tto.db.kurtarma-oncesi-")]
    assert len(kept) == 1 and "Kurtarmadan önceki hali yanında duruyor" in out
    old = Store(os.path.join(str(d["data"]), kept[0]))
    assert old.trades(DAY) == []
    old.close()
    assert main(["kurtar", os.path.basename(d["damaged"]), "--data-dir", str(d["data"])]) == 0     # (a name alone)
    again = capsys.readouterr().out
    assert "hiçbir şey eklenmedi" in again
    assert len([n for n in os.listdir(str(d["data"])) if n.startswith("tto.db.kurtarma-oncesi-")]) == 1
    # the summary is in the dashboard's log too
    with open(str(d["data"] / "logs" / "tto.log"), encoding="utf-8") as fh:
        assert "Günlük İşlemler: 25 işlem (24.11)" in fh.read()


def test_dene_changes_nothing_and_says_what_would_come(tmp_path, capsys):
    d = desk(tmp_path)
    files = {n: digest(os.path.join(str(d["data"]), n)) for n in os.listdir(str(d["data"])) if os.path.isfile(os.path.join(str(d["data"]), n))}
    assert main(["kurtar", d["damaged"], "--dene", "--data-dir", str(d["data"])]) == 0
    out = capsys.readouterr().out
    assert "DENEMESİ" in out and "Geri gelecekler" in out and "Günlük İşlemler: 25 işlem (24.11) · 2 işlem güncellenecek" in out
    after = {n: digest(os.path.join(str(d["data"]), n)) for n in os.listdir(str(d["data"])) if os.path.isfile(os.path.join(str(d["data"]), n))}
    assert after == files                                              # (no file changed, none added: no -wal, no log, no copy)
    s = Store(d["db"])
    assert s.trades(DAY) == [] and s.get("bbg.hits")["day"] == "2026-11-23"
    s.close()
    # the real run does what the trial said
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    real = capsys.readouterr().out
    assert "Günlük İşlemler: 25 işlem (24.11) · 2 işlem güncellendi" in real


def test_the_lock_is_respected(tmp_path, capsys):
    """While a dashboard holds the data folder, neither the recovery (nor its trial) nor yedekten-don runs - and nothing
    changes."""
    d = desk(tmp_path)
    before = digest(d["db"])
    lock = DataLock(str(d["data"]), port=1057).acquire()
    try:
        for args in (["kurtar", d["damaged"]], ["kurtar", d["damaged"], "--dene"], ["yedekten-don", d["backup"]]):
            assert main(args + ["--data-dir", str(d["data"])]) == 3
            err = capsys.readouterr().err
            assert "Dashboard açıkken" in err and "bir dashboard kullanıyor" in err
    finally:
        lock.release()
    assert digest(d["db"]) == before and not [n for n in os.listdir(str(d["data"])) if "kurtarma-oncesi" in n]
    # a lock a crashed dashboard left (its process gone): taken over - said in the log - and given back at the end
    from test_datadir import dead_pid, record
    from tto import datadir
    record(d["data"], host=datadir.host_name(), pid=dead_pid())
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    assert "eski kilidi devralındı" in capsys.readouterr().out
    with open(str(d["data"] / "logs" / "tto.log"), encoding="utf-8") as fh:
        assert "kurtar: veri klasörünün eski kilidi devralındı" in fh.read()
    assert not os.path.exists(os.path.join(str(d["data"]), datadir.LOCK_NAME))


def test_a_number_the_database_gave_another_row_meanwhile(tmp_path, capsys):
    """The dashboard ran on the restored backup before the recovery: a trade and a Trades entry took numbers the
    damaged file's rows have.  Those come back under new numbers - Trades' log and close with theirs -, and a second
    run adds them again nowhere."""
    d = desk(tmp_path)
    s = Store(d["db"])
    mine = s.add_trade(DAY, "fx", {"note": "yedek üzerinde girildi"}, "ayşe")
    mine_tb = s.tb_add("desk", "ayşe", "fx", DAY, {"dv01": 1}, "ayşe", {"note": "yedek üzerinde"})
    s.close()
    assert mine == d["new_ids"][0] and mine_tb == d["tb2"]
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    out = capsys.readouterr().out
    assert "1 tanesi yeni numarayla" in out
    s = Store(d["db"])
    try:
        rows = s.trades(DAY)
        assert len(rows) == 26 and s.trade(mine)["note"] == "yedek üzerinde girildi"
        moved = [t for t in rows if t.get("dv01") == 2000]
        assert len(moved) == 1 and moved[0]["id"] > max(d["new_ids"])
        books = [t for t in s.tb_list("desk") if t["trade_date"] == DAY]
        theirs = next(t for t in books if t["owner"] == "veli")
        assert theirs["id"] not in (mine_tb, d["tb"])
        assert [r["detail"]["note"] for r in s.tb_log(trade=theirs["id"])] == ["yeni"]
        assert set(s.tb_closes([theirs["id"]])) == {theirs["id"]}
    finally:
        s.close()
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    assert "hiçbir şey eklenmedi" in capsys.readouterr().out
    s = Store(d["db"])
    assert len(s.trades(DAY)) == 26
    s.close()


def test_rows_whose_values_are_not_what_their_columns_hold_are_left(tmp_path, capsys):
    d = desk(tmp_path)
    con = sqlite3.connect(d["damaged"])
    con.execute("UPDATE kv SET value='{bozuk' WHERE key='kagitfiyat.widths'")
    con.execute("UPDATE chat SET created_at='dün' WHERE text='teşekkürler'")
    con.commit()
    con.close()
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    out = capsys.readouterr().out
    s = Store(d["db"])
    assert s.get("kagitfiyat.widths") is None and [m["text"] for m in s.chat()[0]][-1] == "işlem tamam"
    s.close()
    assert "chat: 1 satırın değerleri bozuk (alınmadı)" in out


def test_the_write_ahead_log_of_the_damaged_file_is_read_too(tmp_path, capsys):
    """Rows only in the damaged file's write-ahead log (yedekten-don moves it with the file) come back; a log that
    cannot be read is left and the file read without it."""
    data = tmp_path / "data"
    s = Store(str(data / "tto.db"))
    s.login("Ali")
    backup = s.backup_to(str(data / "backups" / "tto-2026-11-23.db"))["path"]
    s.add_chat("ali", "yalnızca günlükte")
    damaged = str(tmp_path / "bozuk.db")
    shutil.copyfile(str(data / "tto.db"), damaged)                    # (copied while open: the row is in the -wal only)
    shutil.copyfile(str(data / "tto.db-wal"), damaged + "-wal")
    s.close()
    restore(backup, str(data / "tto.db"))
    assert main(["kurtar", damaged, "--dene", "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert "chat: 1 mesaj" in out and "-wal dosyasıyla" in out
    assert os.path.exists(damaged + "-wal") and not os.path.exists(damaged + "-shm")   # (the copy was read, not the file)


def test_a_file_sqlite_cannot_read_at_all(tmp_path, capsys):
    d = desk(tmp_path)
    with open(d["damaged"], "r+b") as fh:                              # the first page: the list of every table
        fh.write(b"\xff" * 200)
    before = digest(d["db"])
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 2
    assert "şeması (tabloların listesi) okunamadı" in capsys.readouterr().err
    assert digest(d["db"]) == before
    assert not [n for n in os.listdir(str(d["data"])) if "kurtarma-oncesi" in n]


def test_what_cannot_be_recovered_into(tmp_path, capsys):
    """The database itself as the damaged file, a damaged database to add to, a file that is not there; without a file
    the damaged files yedekten-don kept are listed."""
    d = desk(tmp_path)
    data = str(d["data"])
    assert main(["kurtar", d["db"], "--data-dir", data]) == 2
    assert "şimdiki veritabanının kendisi" in capsys.readouterr().err
    assert main(["kurtar", str(tmp_path / "yok.db"), "--data-dir", data]) == 2
    assert "bozuk dosya yok" in capsys.readouterr().err
    assert main(["kurtar", "--data-dir", data]) == 0
    listed = capsys.readouterr().out
    assert d["damaged"] in listed and "--dene" in listed
    assert main(["kurtar", "--data-dir", str(tmp_path / "bos")]) == 1
    capsys.readouterr()
    shutil.copyfile(d["damaged"], d["db"])                             # the database itself damaged
    assert main(["kurtar", d["damaged"], "--data-dir", data]) == 2
    assert "şimdiki veritabanı da sağlam değil" in capsys.readouterr().err


def test_into_a_database_that_is_not_there_yet(tmp_path, capsys):
    """No backup to go back to: everything readable goes into a new database - the history too, past its damaged leaf,
    with no key of the database's to look with (a day moved on, then the next series)."""
    d = desk(tmp_path)
    os.remove(d["db"])
    assert main(["kurtar", d["damaged"], "--data-dir", str(d["data"])]) == 0
    out = capsys.readouterr().out
    assert "Şimdiki veritabanı yoktu" in out and "Kurtarmadan önceki hali" not in out
    s = Store(d["db"])
    try:
        assert [t["id"] for t in s.trades(DAY)] == d["new_ids"] and s.account("ali")["role"] == "admin"
        assert len(s.trades("2026-11-10", "2026-11-19")) == 120 - 1 - d["lost_trades"]     # (the unreadable leaf: lost now)
        assert "kayıp: %d" % d["lost_trades"] in out
        closes = sum(len(s.hist_series("SERI%02d Index|PX_LAST" % k)) for k in range(12))
        assert closes == 2001 + 11 * 301 - d["lost_closes"]
    finally:
        s.close()


def test_every_table_of_the_store_has_its_rule():
    from tto.store import _SCHEMA
    import re
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _SCHEMA))
    assert tables == {r.table for r in recover.RULES}
    assert set(recover.KV_MERGE) >= {"bbg.hits", "hist.fetch"}
