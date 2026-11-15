"""The daily backup of the database: at 17:30 by default; the administrators choose its time and its folders in the
dashboard (Araçlar → Yedekleme) - their choice before the command line / environment, those before the defaults,
read again at every look of the loop -; a folder is checked before it is taken (a full path, no cloud-synced
folder, made when missing, written to once); the second copy goes to D:\\tto-yedek by default only on a machine with
that drive; "Şimdi yedek al"; administrators only, and the folders reach nobody else."""
import datetime as _dt
import os
import shutil
import time as _time
from types import SimpleNamespace

import pytest

from tto import config
from tto import ops as ops_mod
from tto.config import Settings
from tto.store import Store


@pytest.fixture(autouse=True)
def _no_environment(monkeypatch):
    """What the desk machine's environment says about the backup (and OneDrive) stays out of these tests."""
    for var in ("TTO_BACKUP_DIR", "TTO_BACKUP_COPY_DIR") + ops_mod.CLOUD_ENV:
        monkeypatch.delenv(var, raising=False)


def make_ops(tmp_path, **kw):
    """The operations of a dashboard with its database (no workbooks): the data folder is ``tmp_path/data``."""
    settings = Settings(data_dir=str(tmp_path / "data"), **kw)
    store = Store(settings.db_path)
    store.login("Ali")
    svc = SimpleNamespace(store=store, settings=settings, started_at=_time.time() - 3600, mode="replay")
    return ops_mod.Ops(svc), store, settings


def put(folder, name, when):
    """A dated backup file written at ``when``."""
    os.makedirs(str(folder), exist_ok=True)
    path = os.path.join(str(folder), name)
    with open(path, "wb") as fh:
        fh.write(b"x")
    os.utime(path, (_time.mktime(when.timetuple()),) * 2)


def texts(x):
    """Every text of a JSON answer."""
    if isinstance(x, dict):
        for v in x.values():
            yield from texts(v)
    elif isinstance(x, list):
        for v in x:
            yield from texts(v)
    elif isinstance(x, str):
        yield x


def names(x, paths):
    """Whether any text of ``x`` names one of the folders - as written or as an error message quotes it."""
    forms = [p for p in paths] + [p.replace("\\", "\\\\") for p in paths if "\\" in p]
    return any(f in t for t in texts(x) for f in forms)


def test_the_backup_is_taken_at_half_past_five_by_default(tmp_path):
    from tto.__main__ import build_parser, settings_from
    assert config.DEFAULT_BACKUP_TIME == "17:30"
    st = settings_from(build_parser().parse_args(["--data-dir", str(tmp_path / "data")]))
    assert st.backup_time == "17:30" and st.backup_from == {"time": "default", "dir": "default", "copy_dir": "default"}
    assert "varsayılan 17:30" in " ".join(build_parser().format_help().split())
    st = settings_from(build_parser().parse_args(["--data-dir", str(tmp_path / "data"), "--backup-time", "18.15"]))
    assert st.backup_time == "18:15" and st.backup_from["time"] == "cli"
    o, s, settings = make_ops(tmp_path)
    try:
        today = _dt.date.today()
        at = lambda h, m=0: _dt.datetime.combine(today, _dt.time(h, m))          # noqa: E731
        put(settings.backup_dir, "tto-%s.db" % today.isoformat(), at(8))           # taken this morning
        assert not o.backup_due(at(17, 29)) and o.backup_due(at(17, 30)) and o.backup_due(at(22))
        db = next(r for r in o.system_rows() if r["kind"] == "db")
        assert "günlük yedek (17:30)" in db["threshold"] and o.db_status()["backup"]["time"] == "17:30"
    finally:
        s.close()


def test_the_administrators_choice_comes_before_the_command_line_and_that_before_the_defaults(tmp_path, monkeypatch):
    o, s, settings = make_ops(tmp_path)
    conf = o.backup_conf()
    assert (conf["time"], conf["dir"], conf["copy_dir"]) == ("17:30", os.path.join(str(tmp_path / "data"), "backups"), None)
    assert conf["source"] == {"time": "default", "dir": "default", "copy_dir": "default"}
    s.close()
    # the command line and the environment before the defaults
    monkeypatch.setenv("TTO_BACKUP_DIR", str(tmp_path / "ortam"))
    second = str(tmp_path / "E" / "kopya")
    o, s, settings = make_ops(tmp_path, backup_time="18:05", backup_copy_dir=second)
    conf = o.backup_conf()
    assert (conf["time"], conf["dir"], conf["copy_dir"]) == ("18:05", str(tmp_path / "ortam"), second)
    assert conf["source"] == {"time": "cli", "dir": "cli", "copy_dir": "cli"}
    # the administrators' choice before both - what it names; the rest as the command line says
    chosen = str(tmp_path / "secilen")
    o.set_backup({"time": "17:45", "dir": chosen}, by="ali")
    conf = o.backup_conf()
    assert (conf["time"], conf["dir"], conf["copy_dir"]) == ("17:45", chosen, second)
    assert conf["source"] == {"time": "saved", "dir": "saved", "copy_dir": "cli"}
    assert conf["base"] == {"time": "18:05", "dir": str(tmp_path / "ortam"), "copy_dir": second}
    # an empty second folder chosen: no second copy, though the command line names one
    o.set_backup({"copy_dir": ""}, by="ali")
    conf = o.backup_conf()
    assert conf["copy_dir"] is None and conf["source"]["copy_dir"] == "saved" and o.backup_now()["copy"] is None
    page = o.backup_page()
    assert page["saved"]["by"] == "ali" and page["saved"]["at"] and page["copy_dir"] is None and page["count"] == 1
    s.close()
    # kept in the database: the next start has it
    o, s, settings = make_ops(tmp_path, backup_time="18:05", backup_copy_dir=second)
    assert (o.backup_conf()["time"], o.backup_conf()["dir"]) == ("17:45", chosen)
    # "Varsayılanlara dön": the command line again
    conf = o.reset_backup(by="ali")
    assert conf["source"] == {"time": "cli", "dir": "cli", "copy_dir": "cli"} and conf["time"] == "18:05"
    assert o.backup_page()["saved"] is None
    s.close()


def test_a_choice_applies_at_the_loops_next_look_without_a_restart(tmp_path):
    """The loop reads the choice at every look: a new time is the next due time; a new folder takes the next backup -
    at once, it has none yet -, the old backups stay where they were and each folder keeps its own newest 30."""
    o, s, settings = make_ops(tmp_path)
    try:
        today = _dt.date.today()
        at = lambda h, m=0: _dt.datetime.combine(today, _dt.time(h, m))          # noqa: E731
        old = settings.backup_dir
        put(old, "tto-%s.db" % today.isoformat(), at(8))
        assert not o.backup_due(at(17))
        o.set_backup({"time": "16:45"}, by="ali")
        assert o.backup_due(at(17))                                # its time has come
        o.set_backup({"time": "18:00"}, by="ali")
        assert not o.backup_due(at(17))
        for k in range(35):                                        # more than 30 in the old folder
            put(old, "tto-2026-%02d-%02d.db" % (9 + k // 28, 1 + k % 28), _dt.datetime(2026, 9, 1) + _dt.timedelta(days=k))
        new = tmp_path / "yeni"
        o.set_backup({"dir": str(new)}, by="ali")
        assert o.backup_due(at(17))                                # nothing in the new folder yet
        res = o.backup_now(today)
        assert res["path"] == str(new / ("tto-%s.db" % today.isoformat())) and os.listdir(str(new)) == [os.path.basename(res["path"])]
        assert res["removed"] == [] and len(os.listdir(old)) == 36     # the old folder: nothing moved, nothing pruned
        assert not o.backup_due(at(17))
        st = o.db_status()["backup"]
        assert (st["dir"], st["count"], st["time"]) == (str(new), 1, "18:00")
        # a backup folder that failed: a new one is tried at once, not after half an hour
        o.backup_error = {"at": "2026-11-16 17:30:00", "text": "OSError: ağ yolu bulunamadı"}
        o._backup_tried = _time.time()
        assert not o.backup_due(at(17))
        o.set_backup({"dir": str(tmp_path / "baska")}, by="ali")
        assert o.backup_error is None and o.backup_due(at(17))
    finally:
        s.close()


def test_a_folder_is_checked_before_it_is_taken(tmp_path, monkeypatch):
    """A full path only; a folder a cloud service synchronises is refused, saying why (OneDrive's own variables, the
    names the services give their folders), before anything is made there; a folder is made when missing and written
    to once - one that cannot be made or written to is refused; the second copy is not the backup folder itself; each
    refusal is said for its own field and nothing is saved."""
    o, s, settings = make_ops(tmp_path)
    try:
        def errors(values):
            with pytest.raises(ops_mod.BackupError) as err:
                o.set_backup(values, by="ali")
            return err.value.errors

        e = errors({"dir": "yedekler", "copy_dir": "..\\kopya"})
        assert set(e) == {"dir", "copy_dir"} and "Tam yol" in e["dir"] and "göreli" in e["dir"] and "Tam yol" in e["copy_dir"]
        assert "Klasörü yazın" in errors({"dir": "  "})["dir"]
        if os.name == "nt":                                        # the root of the current drive, a drive's current folder
            assert "Tam yol" in errors({"dir": "\\tto-yedek"})["dir"] and "Tam yol" in errors({"dir": "E:tto-yedek"})["dir"]
        assert "SS:DD" in errors({"time": "25:00"})["time"] and "SS:DD" in errors({"time": "beş buçuk"})["time"]
        # OneDrive where its variable says (any name), and the folders of the services by their names
        cloud = tmp_path / "Bulut"
        monkeypatch.setenv("OneDriveCommercial", str(cloud))
        e = errors({"dir": str(cloud / "tto-yedek")})["dir"]
        assert "OneDrive" in e and "Bloomberg verisi ve şifre özetleri" in e and "hiçbir dış hizmete gitmez" in e
        for name, service in (("OneDrive", "OneDrive"), ("OneDrive - Firma", "OneDrive"), ("Dropbox", "Dropbox"),
                              ("Dropbox (Kişisel)", "Dropbox"), ("Google Drive", "Google Drive"), ("My Drive", "Google Drive"),
                              ("iCloudDrive", "iCloud Drive"), ("Box", "Box")):
            assert service in errors({"copy_dir": str(tmp_path / "u" / name / "tto")})["copy_dir"], name
        assert not os.path.exists(str(cloud)) and not os.path.exists(str(tmp_path / "u"))       # nothing made there
        # a folder that cannot be made (a file where it should be), one that cannot be written to
        (tmp_path / "dosya").write_text("bir dosya, klasör değil")
        assert "Klasör açılamadı" in errors({"dir": str(tmp_path / "dosya" / "yedek")})["dir"]
        locked = tmp_path / "kilitli"
        (locked / ops_mod.PROBE_NAME).mkdir(parents=True)          # the trial file cannot be written there
        assert "Klasöre yazılamıyor" in errors({"copy_dir": str(locked)})["copy_dir"]
        # the second copy in the backup folder itself
        same = str(tmp_path / "ayni")
        assert "kendisi olamaz" in errors({"dir": same, "copy_dir": same + os.sep})["copy_dir"]
        assert o.saved_backup() == {} and o.backup_conf()["source"] == {"time": "default", "dir": "default", "copy_dir": "default"}
        # a folder that is fine: made, written to, the trial file gone (blanks and quotes around it do not matter)
        ok = tmp_path / "yeni" / "tto-yedek"
        conf = o.set_backup({"time": " 7.05 ", "dir": ' "%s" ' % ok, "copy_dir": ""}, by="ali")
        assert (conf["time"], conf["dir"], conf["copy_dir"]) == ("07:05", str(ok), None)
        assert os.path.isdir(str(ok)) and os.listdir(str(ok)) == []
    finally:
        s.close()


def test_the_second_copy_goes_to_d_by_default_only_on_a_machine_with_that_drive(tmp_path, monkeypatch):
    """D:\\tto-yedek is the installed dashboard's default only on a machine with a D: drive; an office computer without
    one has no second copy - and no alarm about it -, the page says none is chosen with a hint.  A second folder that
    is chosen and fails two days in a row is the alarm, which names no folder (the whole desk reads it)."""
    installed = tmp_path / "kurulum"
    (installed / "data").mkdir(parents=True)
    assert config.drive_exists("tto-yedek") is False                                           # no drive at all
    monkeypatch.setattr(config, "drive_exists", lambda path: True)
    assert config.backup_copy_default(str(installed / "data"), root=str(installed), windows=True) == "D:\\tto-yedek"
    monkeypatch.setattr(config, "drive_exists", lambda path: False)
    assert config.backup_copy_default(str(installed / "data"), root=str(installed), windows=True) is None
    o, s, settings = make_ops(tmp_path)
    try:
        # no second copy: the backup alone, nothing failed, no alarm - even with failures of an earlier copy recorded
        s.put("ops.backup_copy", {"failed_days": ["2026-11-12", "2026-11-13"], "error": {"at": "2026-11-13 22:00:00", "text": "x"}})
        assert o.backup_now(_dt.date(2026, 11, 14))["copy"] is None
        assert o.system_checks(_dt.datetime(2026, 11, 14, 18, 0))["db"]["state"] == "ok"
        page = o.backup_page()
        assert page["copy_dir"] is None and page["d_drive"] is False and page["copy_error"] is None
        monkeypatch.setattr(config, "drive_exists", lambda path: True)
        assert o.backup_page()["d_drive"] is True
        # a second folder chosen that cannot be written two days in a row: the alarm - without the folder in it
        bad = tmp_path / "Q"
        o.set_backup({"copy_dir": str(bad / "kopya")}, by="ali")
        assert o.copy_state()["failed_days"] == []                 # (the earlier folder's failures are not this one's)
        shutil.rmtree(str(bad))
        bad.write_text("bir dosya, klasör değil")                  # the share gone
        for day in (15, 16):
            res = o.backup_now(_dt.date(2026, 11, day))
            assert os.path.exists(res["path"]) and res["copy"]["error"]
        db = o.system_checks(_dt.datetime(2026, 11, 16, 18, 0))["db"]
        assert db["state"] == "alarm" and "2 gündür alınamadı" in db["text"]
        assert not names(db, [str(bad), str(bad / "kopya"), str(tmp_path)])
        page = o.backup_page()
        assert page["copy_failed"] == 2 and page["copy_error"]["text"]
        # the folder given up: no second copy, the alarm's condition ends
        o.set_backup({"copy_dir": ""}, by="ali")
        assert o.system_checks(_dt.datetime(2026, 11, 16, 18, 1))["db"]["state"] == "ok"
    finally:
        s.close()


def test_a_chosen_folder_that_cannot_be_written_falls_back_to_the_dashboards_own(tmp_path):
    """The share of the chosen folder is down at the backup time: the day's backup goes to the dashboard's own folder
    (data/backups), its second copy is still made from it, the database's alarm rings (no folder in its text); the day
    counts as backed up - no second full backup however often the loop looks, across a restart too.  The chosen folder
    is tried again every half hour; once it can be written the file is copied there and the alarm ends."""
    o, s, settings = make_ops(tmp_path)
    try:
        now = _dt.datetime.now().replace(microsecond=0)
        if now.hour == 23 and now.minute >= 50:
            pytest.skip("the day must not end during the test")
        share, second = tmp_path / "paylasim", tmp_path / "E" / "kopya"
        chosen = share / "tto"
        o.set_backup({"time": now.strftime("%H:%M"), "dir": str(chosen), "copy_dir": str(second)}, by="ali")
        own = os.path.join(str(tmp_path / "data"), "backups")
        name = "tto-%s.db" % now.date().isoformat()
        assert o.own_backup_dir() == own
        shutil.rmtree(str(share))
        share.write_text("paylaşım kapalı")
        o.look(now)                                                # the backup is due: the chosen folder cannot be written
        assert os.listdir(own) == [name] and not os.path.exists(str(chosen))
        assert os.path.isfile(str(second / name)) and o.copy_state()["failed_days"] == []        # the second copy, from it
        assert o.backup_error is None
        db = o.system_checks(now)["db"]
        assert db["state"] == "alarm" and ("seçilen yedek klasörüne yazılamadı – bugünkü yedek dashboard'un kendi klasörüne (%s) alındı"
                                           % os.path.join("data", "backups")) in db["text"]
        assert not names(db, [str(tmp_path)])
        view = o.fallback_view()
        assert (view["today"], view["waiting"], view["reached_at"], view["dir"]) == (True, [now.date().isoformat()], None, own)
        assert o.backup_page()["own"]["backups"][0]["name"] == name and o.db_status()["backup"]["fallback"]["waiting"]
        # the day is backed up: the loop takes no other backup, and the chosen folder is not tried before half an hour
        written = os.path.getmtime(os.path.join(own, name))
        later = [min(now + _dt.timedelta(minutes=m), now.replace(hour=23, minute=59, second=59)) for m in (1, 29, 31, 9)]
        for t in later:
            o.look(t)
            assert not o.backup_due(t)
        assert os.listdir(own) == [name] and os.path.getmtime(os.path.join(own, name)) == written
        assert not ops_mod.Ops(o.svc).backup_due(later[-1])                                  # (a restart knows it)
        # half an hour later, still down: tried, the day still waits, the alarm stays
        o._fallback_tried -= ops_mod.BACKUP_RETRY
        assert o.catch_up() == [] and o.fallback_pending() and o.system_checks(now)["db"]["state"] == "alarm"
        # the share is back: not tried before the next half hour ...
        share.unlink()
        assert o.catch_up() == [] and not os.path.exists(str(chosen / name))
        # ... then the day's file is copied there whole, and the alarm ends
        o._fallback_tried -= ops_mod.BACKUP_RETRY
        o.look(later[-1])
        assert os.path.getsize(str(chosen / name)) == os.path.getsize(os.path.join(own, name))
        copied = Store(str(chosen / name))
        assert copied.user_exists("ali") and copied.quick_check() == []
        copied.close()
        assert not o.fallback_pending() and o.system_checks(now)["db"]["state"] == "ok"
        view = o.fallback_view()                                   # today's backup went there first - and it reached the folder
        assert view["today"] and view["waiting"] == [] and view["reached_at"]
        assert not o.backup_due(later[-1]) and os.listdir(own) == [name]
    finally:
        s.close()


def test_no_fallback_from_the_dashboards_own_folder_and_none_when_both_fail(tmp_path):
    """The chosen folder is the dashboard's own: a backup that fails there is a failure, as before (said, tried again
    after half an hour).  A chosen folder and the dashboard's own folder both failing: no backup, both reasons said."""
    o, s, settings = make_ops(tmp_path)
    try:
        own = o.own_backup_dir()
        assert same(o.backup_conf()["dir"], own)
        with open(own, "w") as fh:
            fh.write("klasör değil")
        with pytest.raises(Exception):
            o.backup_now()
        assert o.backup_error and o.fallback_state()["days"] == {} and not o.backup_due(_dt.datetime.now())
        db = o.system_checks(_dt.datetime.now())["db"]
        assert db["state"] == "alarm" and "yedek alınamadı" in db["text"] and "seçilen yedek klasörüne" not in db["text"]
        share = tmp_path / "paylasim"
        o.set_backup({"dir": str(share / "tto")}, by="ali")
        shutil.rmtree(str(share))
        share.write_text("paylaşım kapalı")
        with pytest.raises(Exception):
            o.backup_now()
        assert "seçilen klasör: " in o.backup_error["text"] and "dashboard'un kendi klasörü: " in o.backup_error["text"]
        assert o.fallback_state()["days"] == {}
    finally:
        s.close()


def test_the_days_that_waited_follow_the_first_backup_that_reaches_the_chosen_folder(tmp_path):
    """Two days in the dashboard's own folder (the alarm counts them); the share back, the next day's backup goes there
    and the two follow at once.  A day that reached the chosen folder meanwhile needs nothing: its later backup there is
    never overwritten by the earlier file.  A second copy that is the dashboard's own folder holds the fallback itself."""
    o, s, settings = make_ops(tmp_path)
    try:
        share = tmp_path / "paylasim"
        chosen, own = share / "tto", o.own_backup_dir()

        def down():
            shutil.rmtree(str(share))
            share.write_text("paylaşım kapalı")

        o.set_backup({"dir": str(chosen), "copy_dir": own}, by="ali")
        down()
        r1 = o.backup_now(_dt.date(2026, 11, 16))
        assert r1["fallback"] and r1["copy"]["path"] == r1["path"] and "error" not in r1["copy"]
        o.backup_now(_dt.date(2026, 11, 17))
        db = o.system_checks(_dt.datetime(2026, 11, 17, 18, 0))["db"]
        assert db["state"] == "alarm" and "2 gündür yazılamıyor" in db["text"]
        share.unlink()                                             # the share is back
        r3 = o.backup_now(_dt.date(2026, 11, 18))
        assert not r3["fallback"] and sorted(os.listdir(str(chosen))) == ["tto-2026-11-%d.db" % d for d in (16, 17, 18)]
        assert not o.fallback_pending() and o.system_checks(_dt.datetime(2026, 11, 18, 18, 0))["db"]["state"] == "ok"
        # the 19th: down at its backup, back, then "Şimdi yedek al" writes the day there itself - it waits no more
        down()
        o.backup_now(_dt.date(2026, 11, 19))
        share.unlink()
        s.login("Veli")
        o.backup_now(_dt.date(2026, 11, 19))
        assert not o.fallback_pending() and o.catch_up(force=True) == []
        later = Store(str(chosen / "tto-2026-11-19.db"))
        assert later.user_exists("veli")
        later.close()
        # the 20th: down, and the chosen folder gets that day's file by other means before the retry - nothing copied over it
        down()
        o.backup_now(_dt.date(2026, 11, 20))
        share.unlink()
        s.login("Zeynep")
        s.backup_to(str(chosen / "tto-2026-11-20.db"))
        o._fallback_tried -= ops_mod.BACKUP_RETRY
        assert o.catch_up() == ["2026-11-20"] and not o.fallback_pending()
        there = Store(str(chosen / "tto-2026-11-20.db"))
        assert there.user_exists("zeynep")                         # (the file put there, not the earlier one of the dashboard's)
        there.close()
    finally:
        s.close()


def same(a, b):
    return ops_mod.same_folder(a, b)


def test_restoring_looks_in_the_chosen_folders_too(tmp_path, capsys):
    """``yedekten-don`` reads the administrators' choice from the database: its folders first, then those of the
    command line / defaults (a changed folder keeps the backups taken before it)."""
    from tto.__main__ import main
    data = tmp_path / "data"
    o, s, settings = make_ops(tmp_path)
    s.backup_to(str(data / "backups" / "tto-2026-11-13.db"))      # before the change: in the default folder
    chosen = tmp_path / "E" / "yedek"
    o.set_backup({"dir": str(chosen)}, by="ali")
    s.login("Veli")
    o.backup_now(_dt.date(2026, 11, 14))                           # after it: in the chosen one
    s.close()
    assert main(["yedekten-don", "--data-dir", str(data)]) == 0
    out = capsys.readouterr().out
    assert "Yedekler · dashboard'da seçilen klasör (%s)" % chosen in out and "Yedekler (%s)" % (data / "backups") in out
    assert out.index("tto-2026-11-14.db") < out.index("tto-2026-11-13.db")
    assert main(["yedekten-don", "tto-2026-11-14.db", "--data-dir", str(data)]) == 0           # by its name alone
    assert str(chosen / "tto-2026-11-14.db") in capsys.readouterr().out
    back = Store(str(data / "tto.db"))
    assert back.user_exists("veli")
    back.close()
    assert ops_mod.saved_folders(str(tmp_path / "yok.db")) == {}


def test_only_administrators_choose_and_take_backups_and_nobody_else_sees_the_folders(tmp_path):
    """"Şimdi yedek al" writes into the chosen folders and says the file, its size and the second copy; the settings
    API answers administrators only (401 without a session, 403 for a user); a refusal comes field by field; a user's
    status names none of the folders.  (The HTTP part last: leaving the client stops the service.)"""
    from starlette.testclient import TestClient

    from conftest import ANON, auth, make_service
    from tto.server import create_app
    from tto.service import ServiceError
    svc = make_service(tmp_path / "data")
    try:
        admin = svc.login("Yedek Yönetici")["user"]
        svc.store.update_account(admin, role="admin")
        user = svc.login("Yedek Kullanıcı")["user"]
        main, second = tmp_path / "E" / "yedek", tmp_path / "F" / "kopya"
        for call in (lambda: svc.backup_settings(user), lambda: svc.set_backup_settings(user, {"time": "18:00"}),
                     lambda: svc.backup_run(user)):
            with pytest.raises(ServiceError) as err:
                call()
            assert err.value.status == 403
        page = svc.set_backup_settings(admin, {"time": "17:30", "dir": str(main), "copy_dir": str(second)})
        assert (page["dir"], page["copy_dir"], page["source"]["dir"]) == (str(main), str(second), "saved")
        out = svc.backup_run(admin)
        r = out["result"]
        name = "tto-%s.db" % _dt.date.today().isoformat()
        assert r["path"] == str(main / name) and r["bytes"] > 0 and r["copy"]["path"] == str(second / name)
        assert (out["count"], out["backups"][0]["name"], out["copy_count"], out["copies"][0]["name"]) == (1, name, 1, name)
        copy = Store(r["copy"]["path"])
        assert copy.user_exists(admin) and copy.quick_check() == []
        copy.close()
        with TestClient(create_app(svc)) as client:
            adm, usr = auth(svc, "Yedek Yönetici", admin=True), auth(svc, "Yedek Kullanıcı")
            assert client.get("/api/admin/backup", headers=ANON).status_code == 401
            for method, path, body in (("GET", "/api/admin/backup", None), ("POST", "/api/admin/backup", {"values": {"time": "18:00"}}),
                                       ("POST", "/api/admin/backup", {"reset": True}), ("POST", "/api/admin/backup/now", {})):
                assert client.request(method, path, json=body, headers=usr).status_code == 403, (method, path, body)
            assert svc.ops.backup_conf()["time"] == "17:30" and svc.ops.saved_backup()["dir"] == str(main)
            got = client.get("/api/admin/backup", headers=adm).json()
            assert got["dir"] == str(main) and got["backups"][0]["name"] == name
            res = client.post("/api/admin/backup", json={"values": {"time": "17:30", "dir": "goreli", "copy_dir": str(tmp_path / "OneDrive" / "x")}},
                              headers=adm)
            body = res.json()
            assert res.status_code == 400 and set(body["errors"]) == {"dir", "copy_dir"} and body["error"] in body["errors"].values()
            assert "Bloomberg" in body["errors"]["copy_dir"] and svc.ops.backup_conf()["dir"] == str(main)
            res = client.post("/api/admin/backup/now", json={}, headers=adm)
            assert res.status_code == 200 and res.json()["result"]["copy"]["path"] == str(second / name)
            status = client.get("/api/status", headers=usr).json()
            assert not names(status, [str(main), str(second), str(tmp_path)])
            assert status["ops"]["db"]["backup"]["count"] == 1 and status["ops"]["db"]["backup"]["time"] == "17:30"
            mine = client.get("/api/status", headers=adm).json()["ops"]["db"]["backup"]
            assert mine["dir"] == str(main) and mine["copy"]["dir"] == str(second)
            # the chosen folder's drive is gone: "Şimdi yedek al" goes to the dashboard's own folder, the second copy is
            # made from it; the alarm rings for everyone - neither it nor a user's status names a folder
            shutil.rmtree(str(tmp_path / "E"))
            (tmp_path / "E").write_text("sürücü yok")
            own, today = os.path.join(str(tmp_path / "data"), "backups"), _dt.date.today().isoformat()
            res = client.post("/api/admin/backup/now", json={}, headers=adm).json()
            assert res["result"]["fallback"] and res["result"]["path"] == os.path.join(own, name)
            assert res["result"]["copy"]["path"] == str(second / name) and res["fallback"]["waiting"] == [today]
            assert res["own"]["backups"][0]["name"] == name
            svc.ops.system_checks()
            status = client.get("/api/status", headers=usr).json()
            fb = status["ops"]["db"]["backup"]["fallback"]
            assert fb["waiting"] == [today] and fb["today"] and "dir" not in fb and "path" not in fb
            assert not names(status, [str(main), str(second), str(tmp_path)])
            desk = client.get("/api/watch", headers=usr).json()["desk"]
            db = next(r for r in desk["system"] if r["kind"] == "db")
            assert db["state"] == "alarm" and "seçilen yedek klasörüne yazılamadı" in db["text"] and not names(desk, [str(tmp_path)])
            mine = client.get("/api/status", headers=adm).json()["ops"]["db"]["backup"]["fallback"]
            assert mine["dir"] == own and mine["path"] == os.path.join(own, name)
            res = client.post("/api/admin/backup", json={"reset": True}, headers=adm)
            assert res.status_code == 200 and res.json()["source"]["dir"] == "default" and res.json()["saved"] is None
    finally:
        svc.stop()
