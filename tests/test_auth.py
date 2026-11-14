"""Sign-in and accounts: passwords kept as hashes, sessions, requests for an account, the first administrator, what
administrators do, the session gate in front of the API and the command that makes an administrator."""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from starlette.testclient import TestClient

from conftest import ANON, make_service
from tto import auth
from tto.server import create_app
from tto.service import ServiceError
from tto.store import Store

LOCAL = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def quick_hashes(monkeypatch):
    """Real hashes take half a second each (on purpose); the tests use few rounds (one test checks the real ones)."""
    monkeypatch.setattr(auth, "ROUNDS", 1000)


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("auth"))
    yield s
    s.stop()


@pytest.fixture()
def svc(shared):
    """The module's service without the accounts, sessions and personal inputs of the test before (signing in
    needs no workbook calculation, so one service serves them all)."""
    with shared.store._lock:
        for table in ("sessions", "users", "user_inputs"):
            shared.store._db.execute("DELETE FROM %s" % table)
    return shared


@pytest.fixture()
def fresh(tmp_path):
    """A service of its own, for a test that runs the web app (whose shutdown stops the service)."""
    s = make_service(tmp_path)
    yield s
    s.stop()


def clock(svc, monkeypatch, start=dt.datetime(2026, 11, 14, 9, 0, 0)):
    """The service's clock, moved by hand: ``tick(seconds)``."""
    now = [start]
    monkeypatch.setattr(svc, "_now", lambda: now[0])

    def tick(seconds):
        now[0] = now[0] + dt.timedelta(seconds=seconds)
    return tick


def err(fn, *args, **kw):
    with pytest.raises(ServiceError) as exc:
        fn(*args, **kw)
    return exc.value.status, str(exc.value)


# ---------------------------------------------------------------------------------------------- passwords
def test_passwords_are_kept_as_salted_hashes(monkeypatch):
    monkeypatch.setattr(auth, "ROUNDS", 600_000)
    h = auth.hash_password("bir şifre 123")
    algo, rounds, salt, digest = h.split("$")
    assert (algo, rounds, len(salt), len(digest)) == ("pbkdf2_sha256", "600000", 32, 64)
    assert auth.check_password("bir şifre 123", h) and not auth.check_password("bir şifre 124", h)
    assert auth.hash_password("bir şifre 123", rounds=1000) != auth.hash_password("bir şifre 123", rounds=1000)   # salt
    for stored in (None, "", "düz metin", "md5$1$00$00", "pbkdf2_sha256$x$00$00"):
        assert auth.check_password("bir şifre 123", stored) is False
    assert auth.password_problem("kısa") and auth.password_problem(" " * 9) and auth.password_problem("x" * 201)
    assert auth.password_problem("yeterince-uzun") is None
    assert auth.token_hash("abc") != "abc" and len(auth.new_token()) >= 40


def test_a_database_of_the_earlier_version_keeps_its_users(tmp_path):
    path = str(tmp_path / "tto.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (name TEXT PRIMARY KEY, display TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES ('ayşe yilmaz', 'Ayşe Yılmaz', '2026-01-05 09:00:00', '2026-11-13 17:00:00')")
    db.commit()
    db.close()
    store = Store(path)
    acc = store.account("ayşe yilmaz")
    assert (acc["display"], acc["role"], acc["status"], acc["pw_hash"], acc["failed"]) == ("Ayşe Yılmaz", "user", "active", None, 0)
    assert store.admins() == [] and store.pending_count() == 0
    assert store.accounts()[0]["has_password"] is False and "pw_hash" not in store.accounts()[0]
    store.close()


# ---------------------------------------------------------------------------------------------- the first administrator
def test_the_first_administrator_only_from_this_computer(svc):
    assert svc.auth_state(None, local=False) == {"user": None, "setup": True, "local": False}
    assert err(svc.setup_admin, "Masa Yöneticisi", "ilk-yonetici-1", False)[0] == 403
    assert err(svc.setup_admin, "Masa Yöneticisi", "kısa", True)[0] == 400
    token, me = svc.setup_admin("  Masa   Yöneticisi ", "ilk-yonetici-1", True)
    assert me == {"user": "masa yöneticisi", "display": "Masa Yöneticisi", "role": "admin", "pending": 0}
    assert svc.session_user(token) == "masa yöneticisi"
    assert svc.auth_state("masa yöneticisi", True)["setup"] is False
    assert err(svc.setup_admin, "Başkası", "ikinci-yonetici", True)[0] == 409              # only while there is none


def test_the_first_administrator_can_be_a_user_of_the_earlier_version(svc):
    key = svc.login("Eski Yönetici")["user"]
    svc.store.set_user_inputs(key, "tto", {"Forward!D2": "15.12.2026"})
    svc.setup_admin("ESKİ YÖNETİCİ", "ilk-yonetici-1", True)
    acc = svc.store.account(key)
    assert (acc["role"], acc["status"], acc["display"]) == ("admin", "active", "ESKİ YÖNETİCİ")
    assert svc.store.user_inputs(key, "tto") == {("tto", "Forward!D2"): "15.12.2026"}       # what was kept stays


# ---------------------------------------------------------------------------------------------- signing in
def test_sign_in_wrong_passwords_and_the_lock(svc, monkeypatch):
    tick = clock(svc, monkeypatch)
    svc.setup_admin("Yönetici", "yonetici-sifre", True)
    svc.admin_action("yönetici", "create", {"name": "Mehmet", "password": "mehmet-sifre"})
    token, me = svc.authenticate(" mehmet ", "mehmet-sifre", "10.0.0.5")
    assert me == {"user": "mehmet", "display": "Mehmet", "role": "user"} and svc.session_user(token) == "mehmet"
    assert err(svc.authenticate, "Mehmet", "yanlış")[0] == 401
    assert err(svc.authenticate, "Yok Böyle", "herhangi-bir")[0] == 401                      # same answer: no telling who exists
    assert err(svc.authenticate, "", "")[0] == 401
    for _ in range(3):
        err(svc.authenticate, "Mehmet", "yanlış")
    status, text = err(svc.authenticate, "Mehmet", "yanlış")                                # the fifth in a row locks
    assert status == 401 and svc.store.account("mehmet")["locked_until"] == "2026-11-14 09:01:00"
    status, text = err(svc.authenticate, "Mehmet", "mehmet-sifre")                         # locked: even the right one waits
    assert status == 429 and "09:01:00" in text
    tick(61)
    assert svc.authenticate("Mehmet", "mehmet-sifre")[1]["user"] == "mehmet"
    assert svc.store.account("mehmet")["failed"] == 0 and svc.store.account("mehmet")["locked_until"] is None


def test_sessions_last_a_week_and_end_on_sign_out(svc, monkeypatch):
    tick = clock(svc, monkeypatch)
    svc.setup_admin("Yönetici", "yonetici-sifre", True)
    token, _ = svc.authenticate("Yönetici", "yonetici-sifre")
    raw = [r[0] for r in svc.store._db.execute("SELECT token FROM sessions").fetchall()]
    assert token not in raw and auth.token_hash(token) in raw                              # kept only as a hash
    tick(7 * 86400 - 1)
    assert svc.session_user(token) == "yönetici"
    tick(2)
    assert svc.session_user(token) is None
    token, _ = svc.authenticate("Yönetici", "yonetici-sifre")
    svc.logout(token)
    assert svc.session_user(token) is None and svc.session_user("") is None and svc.session_user(None) is None


def test_a_user_of_the_earlier_version_asks_under_the_same_name(svc):
    svc.setup_admin("Yönetici", "yonetici-sifre", True)
    key = svc.login("Ayşe Yılmaz")["user"]                                                  # signed in by name, before
    svc.store.set_user_inputs(key, "tto", {"Forward!D2": "15.12.2026"})
    status, text = err(svc.authenticate, "Ayşe Yılmaz", "herhangi-bir")
    assert status == 401 and "Hesap iste" in text
    assert svc.request_account("ayşe yilmaz", "ayse-yeni-sifre", "  masa   2 ") == {"status": "pending", "display": "Ayşe Yılmaz"}
    acc = svc.store.account(key)
    assert (acc["status"], acc["note"]) == ("pending", "masa 2")
    assert err(svc.authenticate, "Ayşe Yılmaz", "ayse-yeni-sifre")[0] == 403                 # waits for an administrator
    assert err(svc.request_account, "Ayşe Yılmaz", "baska-bir-sifre")[1] == "bu isimle bir istek zaten onay bekliyor"
    assert err(svc.require_user, key)[0] == 401
    svc.admin_action("yönetici", "approve", {"name": "Ayşe Yılmaz"})
    assert svc.authenticate("Ayşe Yılmaz", "ayse-yeni-sifre")[1]["user"] == key
    assert svc.store.user_inputs(key, "tto") == {("tto", "Forward!D2"): "15.12.2026"}       # the same account, its inputs
    assert err(svc.request_account, "Ayşe Yılmaz", "ayse-yeni-sifre")[1].startswith("bu isimde bir hesap var")


def test_requests_approved_and_rejected(svc):
    svc.setup_admin("Yönetici", "yonetici-sifre", True)
    svc.request_account("Yeni Biri", "yeni-biri-sifre")
    svc.login("Eski Biri")
    svc.request_account("Eski Biri", "eski-biri-sifre")
    listed = svc.accounts("yönetici")
    assert listed["pending"] == 2 and svc.me("yönetici")["pending"] == 2
    assert {a["display"]: a["status"] for a in listed["accounts"]} == {"Yeni Biri": "pending", "Eski Biri": "pending",
                                                                       "Yönetici": "active"}
    assert all("pw_hash" not in a for a in listed["accounts"])
    # a new name: rejected, nothing of it is left; an existing user: back as it was, without a password
    svc.admin_action("yönetici", "reject", {"name": "Yeni Biri"})
    assert svc.store.account("yeni biri") is None
    svc.admin_action("yönetici", "reject", {"name": "eski biri"})
    acc = svc.store.account("eski biri")
    assert (acc["status"], acc["pw_hash"], acc["requested_at"]) == ("active", None, None)
    assert err(svc.admin_action, "yönetici", "approve", {"name": "Eski Biri"})[1] == "onay bekleyen bir istek değil"
    assert err(svc.admin_action, "yönetici", "approve", {"name": "Hiç Yok"})[0] == 404
    assert err(svc.admin_action, "yönetici", "uçur", {})[0] == 404


def test_what_administrators_do(svc):
    t_admin, _ = svc.setup_admin("Yönetici", "yonetici-sifre", True)
    act = lambda what, **data: svc.admin_action("yönetici", what, data)                     # noqa: E731
    act("create", name="Zeynep", password="zeynep-sifre")
    act("create", name="Can", password="can-sifre-1", admin=True)
    assert svc.store.admins() == ["can", "yönetici"]
    assert err(act, "create", name="Zeynep", password="zeynep-sifre")[1] == "bu isimde bir hesap var"
    assert err(act, "create", name="Kısa", password="kısa")[0] == 400
    # a user is not an administrator
    t_z, me = svc.authenticate("Zeynep", "zeynep-sifre")
    assert me["role"] == "user" and "pending" not in me
    assert err(svc.accounts, "zeynep")[0] == 403 and err(svc.admin_action, "zeynep", "create", {})[0] == 403
    # roles: the last administrator keeps the role
    act("role", name="Zeynep", admin=True)
    assert svc.me("zeynep")["role"] == "admin"
    act("role", name="Zeynep", admin=False)
    act("role", name="Can", admin=False)
    assert err(act, "role", name="Yönetici", admin=False)[1].startswith("son yöneticinin yetkisi alınamaz")
    # a new password: the user's open sessions end
    act("password", name="Zeynep", password="zeynep-yeni-sifre")
    assert svc.session_user(t_z) is None
    assert err(svc.authenticate, "Zeynep", "zeynep-sifre")[0] == 401
    t_z, _ = svc.authenticate("Zeynep", "zeynep-yeni-sifre")
    # closing an account: its sessions end, it cannot sign in; not one's own, not the last administrator
    act("status", name="Zeynep", active=False)
    assert svc.session_user(t_z) is None and err(svc.authenticate, "Zeynep", "zeynep-yeni-sifre")[0] == 403
    assert err(svc.require_user, "zeynep")[0] == 401
    act("status", name="Zeynep", active=True)
    assert svc.authenticate("Zeynep", "zeynep-yeni-sifre")[1]["user"] == "zeynep"
    assert err(act, "status", name="Yönetici", active=False)[1] == "kendi hesabınızı kapatamazsınız"
    act("role", name="Can", admin=True)
    assert err(svc.admin_action, "can", "status", {"name": "Can", "active": False})[1] == "kendi hesabınızı kapatamazsınız"
    act("status", name="Can", active=False)                                                 # another administrator: fine
    assert svc.store.admins() == ["yönetici"] and svc.session_user(t_admin) == "yönetici"
    # an administrator gives a user of the earlier version a password
    svc.login("Eski Kullanıcı")
    act("create", name="eski kullanıcı", password="eski-sifre-1")
    assert svc.authenticate("Eski Kullanıcı", "eski-sifre-1")[1]["display"] == "Eski Kullanıcı"


def test_changing_ones_own_password(svc):
    svc.setup_admin("Yönetici", "yonetici-sifre", True)
    assert err(svc.change_password, "yönetici", "yanlış", "yeni-sifre-12")[0] == 403
    assert err(svc.change_password, "yönetici", "yonetici-sifre", "kısa")[0] == 400
    svc.change_password("yönetici", "yonetici-sifre", "yeni-sifre-12")
    assert svc.authenticate("Yönetici", "yeni-sifre-12")[1]["role"] == "admin"
    assert err(svc.change_password, None, "a", "b")[0] == 401


# ---------------------------------------------------------------------------------------------- over HTTP
def test_the_api_answers_only_with_a_session(fresh):
    svc = fresh
    app = create_app(svc)
    with TestClient(app) as web:
        assert web.get("/").status_code == 200 and web.get("/static/js/pages/users.js").status_code == 200
        for path in ("/api/status", "/api/nav", "/api/users", "/api/view/masa", "/api/events", "/api/admin/users"):
            res = web.get(path)
            assert res.status_code == 401 and res.json() == {"error": "giriş gerekli", "login": True}, path
        assert web.get("/api/auth").json() == {"user": None, "setup": True, "local": False}
        assert web.post("/api/setup", json={"name": "Ağdan", "password": "agdan-sifre-1"}).status_code == 403
    with TestClient(app, client=LOCAL) as here:
        res = here.post("/api/setup", json={"name": "Yönetici", "password": "yonetici-sifre"})
        assert res.status_code == 200 and res.json()["role"] == "admin"
        cookie = res.headers["set-cookie"]
        for part in ("tto_oturum=", "HttpOnly", "Max-Age=604800", "Path=/", "SameSite=strict"):
            assert part in cookie, part
        assert "Secure" not in cookie                                                           # plain http on the desk network
        assert here.get("/api/status").status_code == 200                                       # the cookie signs in
        assert here.get("/api/auth").json()["user"]["user"] == "yönetici"
        assert here.post("/api/setup", json={"name": "İkinci", "password": "ikinci-sifre"}).status_code == 409


def test_sign_in_requests_and_administration_over_http(fresh):
    svc = fresh
    app = create_app(svc)
    with TestClient(app, client=LOCAL) as admin:
        admin.post("/api/setup", json={"name": "Yönetici", "password": "yonetici-sifre"})
        with TestClient(app) as web:
            res = web.post("/api/account-request", json={"name": "Deniz", "password": "deniz-sifre", "note": "repo masası"})
            assert res.json() == {"status": "pending", "display": "Deniz"}
            res = web.post("/api/login", json={"name": "Deniz", "password": "deniz-sifre"})
            assert res.status_code == 403 and "onay" in res.json()["error"] and "set-cookie" not in res.headers
            listed = admin.get("/api/admin/users").json()
            assert listed["pending"] == 1 and [a["note"] for a in listed["accounts"] if a["status"] == "pending"] == ["repo masası"]
            assert admin.post("/api/admin/users/approve", json={"name": "Deniz"}).json()["pending"] == 0
            res = web.post("/api/login", json={"name": "deniz", "password": "deniz-sifre"})
            assert res.status_code == 200 and res.json() == {"user": "deniz", "display": "Deniz", "role": "user"}
            assert web.get("/api/status").status_code == 200
            assert web.get("/api/admin/users").status_code == 403
            assert web.post("/api/admin/users/role", json={"name": "Deniz", "admin": True}).status_code == 403
            # the sheet explorer is the administrators'; a cell's details are everybody's (the status bar of every page)
            assert web.get("/api/sheets?book=tto").status_code == 403
            assert web.get("/api/grid", params={"book": "tto", "sheet": "MASA", "range": "A1:B2"}).status_code == 403
            assert web.get("/api/cell", params={"book": "tto", "ref": "MASA!B4"}).status_code == 200
            assert admin.get("/api/sheets?book=tto").status_code == 200
            assert admin.get("/api/grid", params={"book": "tto", "sheet": "MASA", "range": "A1:B2"}).status_code == 200
            assert web.post("/api/password", json={"old": "deniz-sifre", "new": "deniz-yeni-sifre"}).json() == {"ok": True}
            # a token in the Authorization header is a session as well (scripts); a wrong one is nobody
            token, _ = svc.authenticate("Deniz", "deniz-yeni-sifre")
            assert web.get("/api/status", headers={"Authorization": "Bearer " + token}).status_code == 200
            assert web.get("/api/status", headers={"Authorization": "Bearer yanlis"}).status_code == 401
            # signing out ends the session on the server, not only in the browser
            old = web.cookies.get("tto_oturum")
            res = web.post("/api/logout")
            assert res.status_code == 200 and 'tto_oturum=""' in res.headers["set-cookie"]
            assert svc.session_user(old) is None and web.get("/api/status", headers=ANON).status_code == 401
            # closed by an administrator: the next request of that browser is turned away
            web.post("/api/login", json={"name": "Deniz", "password": "deniz-yeni-sifre"})
            assert web.get("/api/status").status_code == 200
            assert admin.post("/api/admin/users/status", json={"name": "Deniz", "active": False}).status_code == 200
            assert web.get("/api/status").status_code == 401
            assert admin.post("/api/admin/users/yok", json={}).status_code == 404


def test_the_command_that_makes_an_administrator(tmp_path, monkeypatch, capsys):
    import getpass

    from tto.__main__ import main
    answers = []
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": answers.pop(0))
    data = str(tmp_path / "data")
    answers[:] = ["komut-sifresi", "komut-sifresi"]
    assert main(["yonetici", "Komut Yönetici", "--data-dir", data]) == 0
    assert "Komut Yönetici artık yönetici" in capsys.readouterr().out
    store = Store(str(tmp_path / "data" / "tto.db"))
    acc = store.account("komut yönetici")
    assert (acc["role"], acc["status"]) == ("admin", "active") and auth.check_password("komut-sifresi", acc["pw_hash"])
    store.update_account("komut yönetici", failed=3, locked_until="2099-01-01 00:00:00")
    store.close()
    answers[:] = ["yeni-komut-sifresi", "yeni-komut-sifresi"]                               # a forgotten password
    assert main(["yonetici", "komut yönetici", "--data-dir", data]) == 0
    store = Store(str(tmp_path / "data" / "tto.db"))
    acc = store.account("komut yönetici")
    assert auth.check_password("yeni-komut-sifresi", acc["pw_hash"]) and acc["locked_until"] is None
    store.close()
    answers[:] = ["kısa"]
    assert main(["yonetici", "Komut Yönetici", "--data-dir", data]) == 2
    answers[:] = ["uzun-bir-sifre", "baska-bir-sifre"]
    assert main(["yonetici", "Komut Yönetici", "--data-dir", data]) == 2
