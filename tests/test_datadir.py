"""The data folder's guards (tto/datadir.py): one dashboard per data folder - a second one refused, from this computer or
another, a stale lock taken over, a clean exit removing it, the commands that change the database refused while a
dashboard runs -, and a data folder on a network drive: the database without its write-ahead log there (journal mode
DELETE), said on the console, in the log and on the status page; backups, restoring and the start's check in both
modes."""
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

from tto import datadir
from tto.datadir import DataLock, LockHeld
from tto.store import Store, restore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def record(folder, **kw):
    """A lock file as another holder would have written it."""
    now = time.time()
    rec = {"program": "dashboard", "host": "BASKA-PC", "user": "veli", "pid": 4321, "started": "2026-11-24 08:55:00",
           "beat": datadir._stamp(now), "beat_epoch": now, "seq": 0, "token": "baskasinin-kilidi", "port": 1057}
    rec.update(kw)
    os.makedirs(str(folder), exist_ok=True)
    with open(os.path.join(str(folder), datadir.LOCK_NAME), "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    return rec


def on_disk(folder):
    """The lock file's record, read as the dashboard reads it (again while a heartbeat rewrites it that moment)."""
    rec = datadir.read_lock(os.path.join(str(folder), datadir.LOCK_NAME))
    assert rec is None or "raw" not in rec, rec
    return rec


def dead_pid():
    """The number of a process of this computer that has ended."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_one_dashboard_per_data_folder(tmp_path):
    data = tmp_path / "data"
    first = DataLock(str(data), port=1057).acquire()
    try:
        rec = on_disk(data)
        assert (rec["program"], rec["host"], rec["pid"], rec["port"]) == ("dashboard", datadir.host_name(), os.getpid(), 1057)
        assert rec["user"] and rec["started"] and rec["beat"] and rec["token"] == first.token
        # a second dashboard on the same folder - this computer, the holder runs: refused, with who and since when
        with pytest.raises(LockHeld) as err:
            DataLock(str(data), port=1060).acquire()
        text = str(err.value)
        assert "bu bilgisayarda (%s)" % datadir.host_name() in text and "açılışı" in text and "başlatılmadı" in text
        assert "http://localhost:1057" in text and err.value.holder["token"] == first.token
        assert on_disk(data)["token"] == first.token                         # (the holder's lock untouched)
        # the commands that change the database are refused too
        for program, said in (("yedekten-don", "yedekten dönülmez"), ("kurtar", "kurtarma yapılmaz")):
            with pytest.raises(LockHeld) as err:
                DataLock(str(data), program=program).acquire()
            assert said in str(err.value) and "Dashboard açıkken" in str(err.value)
        with pytest.raises(LockHeld):
            datadir.check_free(str(data), "kurtar")
    finally:
        first.release()
    # a clean exit removes it: the next one takes the folder
    assert on_disk(data) is None
    datadir.check_free(str(data), "kurtar")
    again = DataLock(str(data)).acquire()
    assert again.took_over is None
    again.release()


def test_a_stale_lock_of_this_computer_is_taken_over_at_once(tmp_path, caplog):
    data = tmp_path / "data"
    # its process is gone (the window was closed, a crash): taken over at once, never watched
    old = record(data, host=datadir.host_name(), pid=dead_pid(), beat_epoch=time.time())
    t0 = time.time()
    lock = DataLock(str(data), watch=30.0).acquire()
    assert time.time() - t0 < 5.0
    assert lock.took_over["token"] == old["token"] and "süreci" in lock.took_over_why
    assert on_disk(data)["token"] == lock.token
    said = datadir.took_over_text(lock.took_over, lock.took_over_why)
    assert "eski kilidi devralındı" in said and datadir.host_name() in said and "veli" in said
    lock.release()
    # its process runs (a number used again) but its heartbeat is two minutes old: stale too
    record(data, host=datadir.host_name(), pid=os.getpid(), beat_epoch=time.time() - 120)
    lock = DataLock(str(data), watch=30.0).acquire()
    assert "son işareti" in lock.took_over_why
    lock.release()
    assert on_disk(data) is None


def test_another_computers_lock_is_watched_its_clock_is_not_ours(tmp_path):
    """Another computer's heartbeat is never read against this computer's clock: its lock is watched, a heartbeat that
    moves meanwhile is a dashboard that runs (refused, naming the computer), one that does not is taken over."""
    data = tmp_path / "data"
    rec = record(data, beat_epoch=time.time() - 3600)          # (its clock an hour behind ours: it looks old)
    stop = threading.Event()

    def beating():
        seq = 0
        while not stop.wait(0.2):
            seq += 1
            record(data, seq=seq, beat_epoch=time.time() - 3600)
    t = threading.Thread(target=beating)
    t.start()
    said = []
    try:
        with pytest.raises(LockHeld) as err:
            DataLock(str(data), watch=3.0, say=said.append).acquire()
    finally:
        stop.set()
        t.join()
    text = str(err.value)
    assert "BASKA-PC bilgisayarında" in text and "kullanıcı: veli" in text and "24.11.2026 08:55" in text
    assert "iki bilgisayar" in text and said and "BASKA-PC" in said[0]
    assert on_disk(data)["token"] == rec["token"]
    # its clock ahead of ours (the heartbeat looks fresh) and nothing moves: watched all the same, then taken over
    record(data, beat_epoch=time.time() + 3600)
    t0 = time.time()
    lock = DataLock(str(data), watch=1.5).acquire()
    assert time.time() - t0 >= 1.5 and lock.took_over["host"] == "BASKA-PC" and "işaret vermedi" in lock.took_over_why
    lock.release()
    # a lock file that does not read (its holder died while writing it) is watched the same way
    with open(os.path.join(str(data), datadir.LOCK_NAME), "wb") as fh:
        fh.write(b'{"program": "dash')
    lock = DataLock(str(data), watch=1.0).acquire()
    assert "raw" in lock.took_over and "okunamayan" in datadir.took_over_text(lock.took_over, lock.took_over_why)
    lock.release()


def test_the_heartbeat_and_a_lock_taken_over_meanwhile(tmp_path, caplog):
    data = tmp_path / "data"
    lock = DataLock(str(data)).acquire()
    told = []
    lock.on_lost = told.append
    first = on_disk(data)
    assert lock.beat() is True
    second = on_disk(data)
    assert second["seq"] == first["seq"] + 1 and second["token"] == lock.token and second["started"] == first["started"]
    # deleted by hand: made again at the next heartbeat
    os.remove(os.path.join(str(data), datadir.LOCK_NAME))
    assert lock.beat() is True and on_disk(data)["token"] == lock.token
    # another dashboard took it over (this one's heartbeat could not be written for a minute): told, and it is never
    # written over - nor removed at the exit
    theirs = record(data)
    with caplog.at_level(logging.ERROR, logger="tto.datadir"):
        assert lock.beat() is False
    assert told and told[0]["token"] == theirs["token"] and lock.lost["host"] == "BASKA-PC" and not lock.held
    assert any("başka bir dashboard'a geçti" in r.getMessage() for r in caplog.records)
    assert lock.info()["lost"]["host"] == "BASKA-PC"
    lock.release()
    assert on_disk(data)["token"] == theirs["token"]


def test_the_heartbeat_thread_keeps_the_lock_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(datadir, "BEAT_EVERY", 0.1)
    data = tmp_path / "data"
    with DataLock(str(data)) as lock:
        seq = on_disk(data)["seq"]
        deadline = time.time() + 10
        while on_disk(data)["seq"] < seq + 3 and time.time() < deadline:
            time.sleep(0.05)
        assert on_disk(data)["seq"] >= seq + 3
        info = lock.info()
        assert info["held"] and info["host"] == datadir.host_name() and info["beat"] and info["lost"] is None
    assert on_disk(data) is None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


HOLDER = """
import sys
sys.path.insert(0, %r)
from tto.datadir import DataLock
lock = DataLock(sys.argv[1], port=1057).acquire().start()
print("HELD" + (" TOOK" if lock.took_over else ""), flush=True)
sys.stdin.readline()
lock.release()
print("RELEASED", flush=True)
""" % ROOT


def test_two_processes_on_one_data_folder(tmp_path):
    """Real processes: while one holds the folder, ``python -m tto`` is refused before it opens anything (exit 3, the
    message on the console), and so is ``yedekten-don``; a holder killed leaves a
    stale lock the next one takes over at once; a clean exit removes it."""
    data = tmp_path / "data"
    script = tmp_path / "holder.py"
    script.write_text(HOLDER, encoding="utf-8")
    backup = tmp_path / "yedek.db"
    s = Store(str(tmp_path / "kaynak.db"))
    s.login("Ali")
    s.backup_to(str(backup))
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    def holder():
        p = subprocess.Popen([sys.executable, str(script), str(data)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             env=env, cwd=str(tmp_path))
        return p, p.stdout.readline().decode().strip()

    def tto(*args):
        return subprocess.run([sys.executable, "-m", "tto"] + list(args), cwd=ROOT, env=env, capture_output=True,
                              timeout=120)

    first, said = holder()
    held_by = on_disk(data)["pid"]                    # (the interpreter itself: a venv's python.exe starts it as a child)
    try:
        assert said == "HELD"
        res = tto("--mode", "replay", "--host", "127.0.0.1", "--port", str(free_port()), "--no-history",
                  "--backup-copy-dir", "", "--data-dir", str(data))
        err = res.stderr.decode("utf-8", "replace")
        assert res.returncode == 3 and "bir dashboard kullanıyor" in err and "başlatılmadı" in err, err
        assert not (data / "tto.db").exists()                             # (refused before the database was opened)
        res = tto("yedekten-don", str(backup), "--data-dir", str(data))
        assert res.returncode == 3 and "yedekten dönülmez" in res.stderr.decode("utf-8", "replace")
        assert not (data / "tto.db").exists()
    finally:
        if held_by != os.getpid():
            os.kill(held_by, signal.SIGTERM)                              # (a crash: no clean exit)
        first.kill()
        first.wait()
    deadline = time.time() + 20
    while datadir.pid_running(held_by) and time.time() < deadline:
        time.sleep(0.1)
    assert datadir.pid_running(held_by) is False
    assert on_disk(data)["pid"] == held_by                                # the stale lock stays ...
    second, said = holder()
    assert said == "HELD TOOK"                                            # ... and is taken over at once
    second.stdin.write(b"\n")
    second.stdin.flush()
    assert second.stdout.readline().decode().strip() == "RELEASED"
    second.wait(timeout=30)
    assert on_disk(data) is None                                          # a clean exit removes it


def test_the_dashboard_holds_the_lock_while_it_runs_and_stops_when_it_loses_it(tmp_path, monkeypatch, capsys):
    """``python -m tto``: the lock taken before the server starts (with the port), given back when it stops; a stale
    one is said on the console and in the log; a lock another dashboard took over stops this one as Ctrl+C does."""
    import _thread

    import uvicorn

    from tto import __main__ as cli
    data = tmp_path / "data"
    record(data, host=datadir.host_name(), pid=dead_pid())
    seen, locks, stopped = {}, [], []
    real_start = DataLock.start
    monkeypatch.setattr(DataLock, "start", lambda self: (locks.append(self), real_start(self))[1])
    monkeypatch.setattr(_thread, "interrupt_main", lambda: stopped.append(True))

    def run(app, **kw):
        seen.update(on_disk(data), port_given=kw["port"])
        lock = locks[0]
        record(data, token="sonra-gelen")                                 # another dashboard took it over meanwhile
        assert lock.beat() is False
    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main(["--mode", "replay", "--port", "18093", "--no-history", "--data-dir", str(data)]) == 0
    assert seen["program"] == "dashboard" and seen["port"] == 18093 and seen["pid"] == os.getpid()
    out = capsys.readouterr()
    assert "eski kilidi devralındı" in out.out and stopped == [True]
    assert "başka bir dashboard'a geçti" in out.err and "bu dashboard kapanıyor" in out.err
    assert on_disk(data)["token"] == "sonra-gelen"                       # (never removed: it is not this one's)
    with open(str(data / "logs" / "tto.log"), encoding="utf-8") as fh:
        log = fh.read()
    assert "eski kilidi devralındı" in log and "başka bir dashboard'a geçti" in log
    # a clean run: the lock is gone afterwards
    os.remove(os.path.join(str(data), datadir.LOCK_NAME))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(during=on_disk(data)))
    assert cli.main(["--mode", "replay", "--port", "18093", "--no-history", "--data-dir", str(data)]) == 0
    assert seen["during"]["program"] == "dashboard" and on_disk(data) is None


# ---------------------------------------------------------------------- the network drive
@pytest.mark.skipif(os.name != "nt", reason="the detection is Windows' (elsewhere: none)")
def test_a_network_drive_is_told_by_its_path_or_by_windows(monkeypatch):
    for path in (r"\\sunucu\paylasim\tto\data\tto.db", "//sunucu/paylasim/data", r"\\?\UNC\sunucu\paylasim\data"):
        assert datadir.on_network_drive(path) is True
    kinds = {"Z:\\": datadir.DRIVE_REMOTE, "C:\\": 3, "D:\\": 3}
    monkeypatch.setattr(datadir, "_drive_type", lambda root: kinds.get(root.upper(), 1))
    assert datadir.on_network_drive(r"Z:\tto\data\tto.db") is True              # a drive letter mapped to a share
    assert datadir.on_network_drive(r"z:\tto\data") is True
    assert datadir.on_network_drive(r"C:\tto\data\tto.db") is False
    assert datadir.on_network_drive(r"\\?\C:\tto\data") is False                # (the long form of a local path)
    assert datadir.on_network_drive(":memory:") is False
    monkeypatch.setattr(datadir.os, "name", "posix")
    assert datadir.on_network_drive(r"\\sunucu\paylasim\data") is False         # elsewhere: no detection


def network(monkeypatch, where=None):
    """Every folder (or the ones under ``where``) taken for a network drive."""
    monkeypatch.setattr(datadir, "on_network_drive",
                        lambda path: where is None or os.path.abspath(path).startswith(os.path.abspath(str(where))))


def test_on_a_network_drive_the_database_keeps_no_write_ahead_log(tmp_path, monkeypatch):
    """WAL cannot work there: the rollback journal for that run - the backups, restoring and the check as before; back
    on a local disk the write-ahead log again."""
    share = tmp_path / "ag"
    network(monkeypatch, share)
    path = str(share / "data" / "tto.db")
    s = Store(path)
    assert (s.network, s.journal_mode) == (True, "delete")
    assert s._q("PRAGMA journal_mode")[0][0] == "delete" and s._q("PRAGMA synchronous")[0][0] == 2
    s.login("Ali")
    tid = s.add_trade("2026-11-24", "fwd", {"dir": "B", "amount": 1e6}, "ali")
    assert not os.path.exists(path + "-wal") and not os.path.exists(path + "-shm")
    assert s.quick_check() == []
    backup = s.backup_to(str(tmp_path / "yedek" / "tto-2026-11-24.db"))
    s.add_trade("2026-11-24", "fwd", {"dir": "S", "amount": 2e6}, "ali")
    s.close()
    # a run on the share that crashed in a write leaves its rollback journal: restoring moves it with the file
    with open(path + "-journal", "wb") as fh:
        fh.write(b"\0" * 512)
    out = restore(backup["path"], path)
    assert os.path.exists(out["kept"] + "-journal") and not os.path.exists(path + "-journal")
    back = Store(path)
    assert back.journal_mode == "delete" and [t["id"] for t in back.trades("2026-11-24")] == [tid]
    assert back.quick_check() == []
    back.close()
    # the same file on a local disk again: the write-ahead log
    monkeypatch.setattr(datadir, "on_network_drive", lambda p: False)
    local = Store(path)
    assert (local.network, local.journal_mode) == (False, "wal")
    local.close()


def test_a_wal_database_moved_to_a_network_drive_leaves_its_log(tmp_path, monkeypatch):
    path = str(tmp_path / "data" / "tto.db")
    s = Store(path)
    s.login("Ali")
    assert s.journal_mode == "wal"
    s.close()
    network(monkeypatch)
    s = Store(path)
    assert s.journal_mode == "delete" and s.user_exists("ali")
    s.login("Veli")
    assert not os.path.exists(path + "-wal")
    s.close()


def test_the_start_says_it_loud_and_the_status_shows_it_red(tmp_path, monkeypatch, capsys, caplog):
    """A dashboard whose data folder is on a network drive: a loud console line and a log line at the start, the red
    line of the status page (for every user: no folder in it) - its start's check of the file as before.  The lock
    the dashboard holds is on the status page too."""
    from starlette.testclient import TestClient

    from conftest import ANON, auth, make_service
    from tto.config import Settings
    from tto.server import create_app
    network(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="tto.ops"):
        svc = make_service(tmp_path / "data")
    try:
        out = capsys.readouterr().out
        assert "UYARI: " + datadir.NETWORK_WARNING in out and "DELETE" in out
        assert any(datadir.NETWORK_WARNING in r.getMessage() for r in caplog.records)
        assert svc.store.journal_mode == "delete" and svc.ops.db_check["ok"] is True
        folder = svc.status()["ops"]["db"]["folder"]
        assert folder["network"] is True and folder["warning"] == datadir.NETWORK_WARNING and folder["journal"] == "delete"
        assert folder["lock"] is None                                     # (a service of the tests: no lock)
        lock = DataLock(str(tmp_path / "data"), port=1057).acquire()
        svc.settings.data_lock = lock
        user = auth(svc, "Ali Kullanıcı")
        with TestClient(create_app(svc)) as client:                     # (the HTTP part last: leaving it stops the service)
            st = client.get("/api/status", headers=user).json()["ops"]["db"]["folder"]
            assert st["network"] is True and st["warning"] == datadir.NETWORK_WARNING
            assert st["lock"]["held"] is True and st["lock"]["host"] == datadir.host_name()
            assert str(tmp_path) not in json.dumps(st)
            assert client.get("/api/status", headers=ANON).status_code == 401
        lock.release()
    finally:
        svc.stop()
        svc.store.close()
    # a local disk: no warning, the write-ahead log
    monkeypatch.setattr(datadir, "on_network_drive", lambda p: False)
    from tto.ops import Ops
    from types import SimpleNamespace
    s = Store(str(tmp_path / "yerel" / "tto.db"))
    o = Ops(SimpleNamespace(store=s, settings=Settings(data_dir=str(tmp_path / "yerel")), started_at=time.time(), mode="replay"))
    assert o.check_folder() == {"network": False, "journal": "wal"} and "UYARI" not in capsys.readouterr().out
    assert o.db_status()["folder"]["warning"] is None
    s.close()
