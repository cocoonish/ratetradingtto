"""Who is at the desk (presence.py): online while a browser holds the live stream or asked for something lately, away
when nobody touched it for a while, offline after - and at once on a sign-out; "last seen" written at most once a minute
and kept across a restart; "last login" at a sign-in; the list (the same for everybody, no address) and the
administrators' account list; a request waiting for approval, a closed account and one without a password are no desk
users."""
from __future__ import annotations

import datetime as dt
import sqlite3
import time

import pytest
from starlette.testclient import TestClient

from conftest import make_service
from tto import auth
from tto import presence as pr
from tto import store as store_mod
from tto.presence import Presence
from tto.server import create_app
from tto.service import ServiceError
from tto.store import Store

#: the morning of the tests (presence's own clock); the accounts were made two weeks before
T0 = dt.datetime(2026, 11, 18, 9, 0, 0).timestamp()
MADE = "2026-11-04 08:30:00"
DESK = ["ayşe yilmaz", "mehmet", "zeynep"]


@pytest.fixture(autouse=True)
def quick_hashes(monkeypatch):
    """Real hashes take half a second each (on purpose); these tests use few rounds."""
    monkeypatch.setattr(auth, "ROUNDS", 1000)


class Clock(object):
    """Presence's two clocks (monotonic and wall), moved together by hand."""

    def __init__(self):
        self.mono = 1000.0
        self.wall = T0

    def tick(self, seconds):
        self.mono += seconds
        self.wall += seconds


@pytest.fixture()
def made(monkeypatch):
    """``made(path)``: a database with the desk's accounts - Ayşe Yılmaz (administrator), Mehmet, Zeynep - and a request
    waiting for approval, a closed account and a user of the earlier version without a password."""
    def make(path=":memory:"):
        monkeypatch.setattr(store_mod, "now_iso", lambda: MADE)
        s = Store(path)
        pw = auth.hash_password("bir-sifre-11")
        s.create_account("Ayşe Yılmaz", pw, role="admin")
        s.create_account("Mehmet", pw)
        s.create_account("Zeynep", pw)
        s.create_account("Bekleyen", pw, status="pending")
        s.create_account("Kapalı", pw)
        s.update_account("kapali", status="disabled")           # (the key: dotless ı is i)
        s.login("Eski Kullanıcı")
        return s
    return make


def watch(store, clock=None):
    """Presence over ``store`` on a clock moved by hand; ``told``: the versions the open pages were told of."""
    clock = clock or Clock()
    told = []
    p = Presence(store, on_change=lambda: told.append(p.version), clock=lambda: clock.mono, wall=lambda: clock.wall)
    return p, clock, told


def states(p):
    return {u["name"]: u["state"] for u in p.listing()["users"]}


def at(seconds):
    """The stamp of ``seconds`` after T0."""
    return pr.stamp(T0 + seconds)


# ---------------------------------------------------------------------------------------------- online, away, offline
def test_online_while_a_stream_or_a_recent_request_away_after_idle_offline_after(made):
    p, clock, told = watch(made())
    assert states(p) == dict.fromkeys(DESK, "offline")
    assert p.counters() == {"v": 0, "online": 0, "away": 0, "boot": int(T0)}
    # Mehmet's browser asks for something: connected - for CONNECTED seconds after its last request
    p.request("mehmet", "tok-m")
    assert p.tick() and states(p)["mehmet"] == "online" and p.counters()["online"] == 1
    clock.tick(pr.CONNECTED - 1)
    assert not p.tick() and states(p)["mehmet"] == "online"
    clock.tick(2)
    assert p.tick() and states(p)["mehmet"] == "offline" and p.counters()["online"] == 0
    # Ayşe's browser holds the live stream: connected however long it asks for nothing ...
    p.stream("ayşe yilmaz", "tok-a", +1)
    p.active("ayşe yilmaz", "tok-a", 0)
    assert p.tick() and states(p)["ayşe yilmaz"] == "online"
    clock.tick(pr.AWAY - 1)
    assert not p.tick() and states(p)["ayşe yilmaz"] == "online"
    # ... and away once nobody typed, clicked, scrolled or moved the mouse in it for AWAY seconds
    clock.tick(2)
    assert p.tick()
    ayse = [u for u in p.listing()["users"] if u["name"] == "ayşe yilmaz"][0]
    assert ayse["state"] == "away" and ayse["idle"] == int(pr.AWAY + 1)
    assert p.counters()["online"] == 0 and p.counters()["away"] == 1
    # an input reported long ago does not take back the one known; a move now makes her online at once
    p.active("ayşe yilmaz", "tok-a", 3 * pr.AWAY)
    assert not p.tick() and states(p)["ayşe yilmaz"] == "away"
    p.active("ayşe yilmaz", "tok-a", 0)
    assert p.tick() and states(p)["ayşe yilmaz"] == "online" and "idle" not in p.listing()["users"][0]
    # a second browser of hers, idle for twenty minutes (it says so as it connects): the other one keeps her online
    p.stream("ayşe yilmaz", "tok-a2", +1)
    p.active("ayşe yilmaz", "tok-a2", 20 * 60)
    clock.tick(pr.CONNECTED + 1)
    assert not p.tick() and states(p)["ayşe yilmaz"] == "online"
    # the streams close (the browsers closed) and nothing was asked for lately: offline at once
    p.stream("ayşe yilmaz", "tok-a", -1)
    p.stream("ayşe yilmaz", "tok-a2", -1)
    assert p.tick() and states(p)["ayşe yilmaz"] == "offline"
    # every change told the open pages once, each with a new version: Mehmet on and off, Ayşe on, away, on, off
    assert told == [1, 2, 3, 4, 5, 6] and p.counters()["v"] == 6


def test_signing_out_takes_that_browser_out_at_once(made):
    p, clock, _ = watch(made())
    p.signed_in("mehmet", "masa")                          # two browsers of Mehmet: the desk's computer, a laptop
    p.signed_in("mehmet", "laptop")
    p.stream("mehmet", "masa", +1)
    p.request("mehmet", "laptop")
    p.tick()
    p.signed_out("masa")
    assert not p.tick() and states(p)["mehmet"] == "online"           # the laptop asked for something a moment ago
    p.signed_out("laptop")
    assert p.tick() and states(p)["mehmet"] == "offline"              # at once, though it asked a moment ago
    # the desk computer's stream closes late, the ended sessions ask again: nothing brings him back
    p.stream("mehmet", "masa", -1)
    p.stream("mehmet", "masa", +1)
    p.request("mehmet", "laptop")
    p.active("mehmet", "laptop", 0)
    assert not p.tick() and states(p)["mehmet"] == "offline"
    # a new password ends the other sessions - the page that asked stays; an account closed: all of them
    p.signed_in("zeynep", "burada")
    p.signed_in("zeynep", "orada")
    p.stream("zeynep", "burada", +1)
    p.stream("zeynep", "orada", +1)
    assert p.tick() and states(p)["zeynep"] == "online"
    clock.tick(pr.CONNECTED + 1)
    p.ended("zeynep", keep=auth.token_hash("burada"))
    p.stream("zeynep", "orada", -1)                                    # (its stream closes late, opens again: no)
    p.stream("zeynep", "orada", +1)
    assert not p.tick() and states(p)["zeynep"] == "online"
    p.stream("zeynep", "burada", -1)
    assert p.tick() and states(p)["zeynep"] == "offline"               # (the other browser's stream did not count)
    p.stream("zeynep", "burada", +1)
    p.ended("zeynep")
    assert not p.tick() and states(p)["zeynep"] == "offline"
    # signing in again is a new session: online
    p.signed_in("mehmet", "masa-2")
    assert p.tick() and states(p)["mehmet"] == "online"


def test_the_list_is_the_desks_users_only(made):
    """Pending requests, closed accounts and password-less users of the earlier version are no desk users: not listed,
    not counted - even with a browser connected (a closed account's stream still closing, a script's token)."""
    p, clock, _ = watch(made())
    for user, token in (("kapali", "k"), ("eski kullanici", "e"), ("mehmet", "m")):
        p.signed_in(user, token)
        p.stream(user, token, +1)
    p.tick()
    view = p.listing("mehmet")
    assert [u["display"] for u in view["users"]] == ["Ayşe Yılmaz", "Mehmet", "Zeynep"]
    assert (view["online"], view["away"]) == (1, 0) and (p.counters()["online"], p.counters()["away"]) == (1, 0)
    assert [u["name"] for u in view["users"] if u.get("me")] == ["mehmet"]
    assert all(set(u) <= {"name", "display", "state", "last_seen", "last_login", "idle", "me"} for u in view["users"])
    assert view["now"] == at(0)


# ---------------------------------------------------------------------------------------------- last seen, last login
def test_last_seen_is_written_at_most_once_a_minute_and_kept_across_a_restart(made, tmp_path, monkeypatch):
    path = str(tmp_path / "tto.db")
    store = made(path)
    p, clock, _ = watch(store)
    writes = []
    real = store.set_last_seen
    monkeypatch.setattr(store, "set_last_seen", lambda items: (writes.append(list(items)), real(items))[1])

    def seen(user):
        return store.account(user)["last_seen"]

    # Mehmet holds the live stream for three minutes and asks for something every five seconds: "last seen" follows
    # him to the database once a minute, not with every request
    p.signed_in("mehmet", "tok-m")
    p.stream("mehmet", "tok-m", +1)
    p.tick()
    assert seen("mehmet") == at(0)
    for _ in range(36):
        clock.tick(5)
        p.request("mehmet", "tok-m")
        p.tick()
    assert [w for w in writes if w[0][0] == "mehmet"] == [[("mehmet", at(s))] for s in (0, 60, 120, 180)]
    assert seen("mehmet") == at(180)
    # signed out within the minute: written at the next look all the same
    clock.tick(20)
    p.signed_out("tok-m")
    p.tick()
    assert seen("mehmet") == at(200)
    # Zeynep asks for something and the dashboard stops before the next look: written as it stops
    clock.tick(5)
    p.request("zeynep", "tok-z")
    p.stop()
    assert seen("zeynep") == at(205)
    # what was written is never moved back (a late, older stamp)
    store.set_last_seen([("zeynep", at(100))])
    assert seen("zeynep") == at(205)
    store.close()
    # a restart: an hour later the list still says when each was last seen - and that Ayşe never signed in
    store = Store(path)
    later = Clock()
    later.tick(3600)
    p2, _, _ = watch(store, later)
    listed = {u["name"]: u for u in p2.listing()["users"]}
    assert (listed["mehmet"]["state"], listed["mehmet"]["last_seen"]) == ("offline", at(200))
    assert (listed["zeynep"]["state"], listed["zeynep"]["last_seen"]) == ("offline", at(205))
    assert listed["ayşe yilmaz"]["last_seen"] is None and listed["ayşe yilmaz"]["last_login"] is None
    store.close()


def test_a_database_of_the_earlier_version_keeps_its_sign_ins_as_last_login(tmp_path):
    """Until now "last seen" was written at a sign-in only: it becomes the last login of every account that signed in
    after it was made (once, when the column is added)."""
    path = str(tmp_path / "tto.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (name TEXT PRIMARY KEY, display TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES ('ayşe yilmaz', 'Ayşe Yılmaz', '2026-01-05 09:00:00', '2026-11-13 17:00:00')")
    db.execute("INSERT INTO users VALUES ('mehmet', 'Mehmet', '2026-11-10 10:00:00', '2026-11-10 10:00:00')")
    db.commit()
    db.close()
    store = Store(path)
    assert store.account("ayşe yilmaz")["last_login"] == "2026-11-13 17:00:00"
    assert store.account("mehmet")["last_login"] is None                       # made, never signed in
    store.update_account("ayşe yilmaz", last_seen="2026-11-18 10:00:00")       # seen since: the last login stays
    store.close()
    store = Store(path)
    assert store.account("ayşe yilmaz")["last_login"] == "2026-11-13 17:00:00"
    store.close()


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("presence"))
    yield s
    s.stop()


@pytest.fixture()
def svc(shared):
    """The module's service without the accounts and sessions of the test before, with presence anew."""
    with shared.store._lock:
        for table in ("sessions", "users"):
            shared.store._db.execute("DELETE FROM %s" % table)
    shared.presence = Presence(shared.store, on_change=shared.nudge)
    return shared


def test_last_login_on_sign_in_and_the_open_pages_told(svc, monkeypatch):
    now = [dt.datetime(2026, 11, 14, 9, 0, 0)]
    monkeypatch.setattr(svc, "_now", lambda: now[0])
    svc.setup_admin("Yönetici", "yonetici-sifre", True, "127.0.0.1")
    acc = svc.store.account("yönetici")
    assert (acc["last_login"], acc["last_login_ip"]) == ("2026-11-14 09:00:00", "127.0.0.1")
    svc.admin_action("yönetici", "create", {"name": "Mehmet", "password": "mehmet-sifre"})
    assert svc.store.account("mehmet")["last_login"] is None
    told = []
    svc.add_listener(told.append)
    try:
        now[0] += dt.timedelta(seconds=90)
        with pytest.raises(ServiceError):
            svc.authenticate("Mehmet", "yanlış-sifre", "10.0.0.5")                  # a wrong password is no sign-in
        assert svc.store.account("mehmet")["last_login"] is None
        token, _ = svc.authenticate("Mehmet", "mehmet-sifre", "10.0.0.5")
        acc = svc.store.account("mehmet")
        assert (acc["last_login"], acc["last_login_ip"]) == ("2026-11-14 09:01:30", "10.0.0.5")
        assert svc.presence.tick() and told                 # the open pages are told (their streams carry the counts)
        assert svc.presence.counters()["online"] == 2
        view = svc.presence_view("mehmet")
        mine = [u for u in view["users"] if u["name"] == "mehmet"][0]
        assert (mine["state"], mine["last_login"], mine.get("me")) == ("online", "2026-11-14 09:01:30", True)
        assert "10.0.0.5" not in str(view)
        svc.logout(token)
        svc.presence.tick()
        assert [u["state"] for u in svc.presence_view("yönetici")["users"] if u["name"] == "mehmet"] == ["offline"]
    finally:
        svc.remove_listener(told.append)


# ---------------------------------------------------------------------------------------------- over HTTP
def test_the_list_over_http_for_a_user_and_for_an_administrator(tmp_path):
    """The same list for a user and an administrator, never an address; the administrators' account list has the
    states, the last sign-in and its address; the page's word over POST; a sign-out over HTTP: offline at once, with
    when he was last seen."""
    svc = make_service(tmp_path)
    shift = [0.0]
    svc.presence._clock = lambda: time.monotonic() + shift[0]
    try:
        app = create_app(svc)
        admin = TestClient(app, client=("127.0.0.1", 50000))       # (no lifespan: the test looks at presence itself)
        web = TestClient(app, client=("10.0.0.5", 50001))
        assert admin.post("/api/setup", json={"name": "Ayşe Yılmaz", "password": "ayse-sifre-1"}).status_code == 200
        assert admin.post("/api/admin/users/create", json={"name": "Mehmet", "password": "mehmet-sifre"}).status_code == 200
        assert web.post("/api/account-request", json={"name": "Bekleyen", "password": "bekleyen-sifre"}).status_code == 200
        assert web.get("/api/presence").status_code == 401 and web.post("/api/presence", json={}).status_code == 401
        assert web.post("/api/login", json={"name": "Mehmet", "password": "mehmet-sifre"}).status_code == 200
        assert web.post("/api/presence", json={"idle": 0}).json() == {"ok": True}
        svc.presence.tick()
        mine, hers = web.get("/api/presence"), admin.get("/api/presence")
        assert mine.status_code == 200 and hers.status_code == 200
        mine, hers = mine.json(), hers.json()
        assert [(u["display"], u["state"]) for u in mine["users"]] == [("Ayşe Yılmaz", "online"), ("Mehmet", "online")]
        assert mine["online"] == 2 and mine["away"] == 0
        # (last seen: each one's own request moves theirs - compared apart from it)
        assert [(u["name"], u["state"], u["last_login"]) for u in mine["users"]] \
            == [(u["name"], u["state"], u["last_login"]) for u in hers["users"]]     # the same list for everybody ...
        assert {k for u in mine["users"] for k in u} | {k for u in hers["users"] for k in u} \
            == {"name", "display", "state", "last_seen", "last_login", "me"}
        assert [u["name"] for u in mine["users"] if u.get("me")] == ["mehmet"]
        assert [u["name"] for u in hers["users"] if u.get("me")] == ["ayşe yilmaz"]
        for res in (web.get("/api/presence"), admin.get("/api/presence")):     # ... never with an address
            assert "10.0.0.5" not in res.text and "127.0.0.1" not in res.text and "_ip" not in res.text
        # the administrators' account list: the states, the last sign-in and its address (that list only)
        accounts = {a["name"]: a for a in admin.get("/api/admin/users").json()["accounts"]}
        m = accounts["mehmet"]
        assert (m["state"], m["last_login_ip"]) == ("online", "10.0.0.5") and m["last_login"] and m["last_seen"]
        assert accounts["bekleyen"]["state"] == "offline" and accounts["bekleyen"]["last_seen"] is None
        assert web.get("/api/admin/users").status_code == 403
        # sixteen minutes without a key or a click: both away; Mehmet's page says somebody moved - he is online again
        shift[0] = pr.AWAY + 60
        admin.get("/api/status")                       # (both pages still ask for things - no stream here: connected)
        web.get("/api/status")
        svc.presence.tick()
        assert {u["name"]: u["state"] for u in web.get("/api/presence").json()["users"]} == {"ayşe yilmaz": "away",
                                                                                           "mehmet": "away"}
        assert web.post("/api/presence", json={"idle": "?"}).json() == {"ok": True}       # (a word it cannot read: now)
        svc.presence.tick()
        view = admin.get("/api/presence").json()
        # (Ayşe's page asking for something is no input: she stays away)
        assert {u["name"]: u["state"] for u in view["users"]} == {"ayşe yilmaz": "away", "mehmet": "online"}
        assert [u["idle"] for u in view["users"] if u["name"] == "ayşe yilmaz"][0] >= pr.AWAY + 60
        # Mehmet signs out: offline for the others at once, with when he was last seen
        assert web.post("/api/logout").status_code == 200
        svc.presence.tick()
        listed = {u["name"]: u for u in admin.get("/api/presence").json()["users"]}
        assert listed["mehmet"]["state"] == "offline" and listed["mehmet"]["last_seen"]
    finally:
        svc.stop()
    assert svc.store.account("mehmet")["last_seen"] == listed["mehmet"]["last_seen"]    # written as the dashboard stopped
