"""The desk's own corner (tto/desk.py): reports to the administrators (Hata / Öneri), the traders' chat (Sosyal) and the
agenda (Ajanda) - who sees and does what, what is kept (across a restart too), the limits; then the same over HTTP.

Most tests use the corner on a database of their own (``_desk``): no workbook is loaded for them."""
import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto import desk as dk
from tto.desk import Desk
from tto.server import create_app
from tto.service import Service, ServiceError
from tto.store import Store


class _Svc(object):
    """What the corner needs of the service: its store, who is signed in, a way to tell the pages."""
    require_user = Service.require_user
    require_admin = Service.require_admin

    def __init__(self, store):
        self.store = store
        self.told = 0

    def nudge(self):
        self.told += 1


def _desk(path):
    store = Store(str(path))
    return Desk(_Svc(store)), store


@pytest.fixture()
def desk(tmp_path):
    d, store = _desk(tmp_path / "tto.db")
    yield d
    store.close()


def _user(d, name, admin=False):
    key = d.store.login(name)["user"]
    if admin:
        d.store.update_account(key, role="admin")
    return key


def _refused(status, call, *args, **kw):
    with pytest.raises(ServiceError) as exc:
        call(*args, **kw)
    assert exc.value.status == status, (args, kw, str(exc.value))
    return str(exc.value)


def _day(n=0):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------- Hata / Öneri
def test_a_report_reaches_the_administrators_only(desk):
    ali, ayse = _user(desk, "Ali Veli"), _user(desk, "Ayşe Yönetici", admin=True)
    before = desk.counters()
    fid = desk.report(ali, "bug", "  Forward sayfasında\r\n2Y boş görünüyor  ", "forward", "Forward")["id"]
    assert desk.counters() == dict(before, feedback=before["feedback"] + 1) and desk.svc.told == 1
    # the badge: an administrator learns how many are open - a user nothing at all, and cannot list or close them
    assert "feedback" not in desk.state(ali) and desk.state(ayse)["feedback"] == 1
    _refused(403, desk.reports, ali)
    _refused(403, desk.report_done, ali, fid)
    got = desk.reports(ayse)
    assert got["count"] == 1 and got["done"] == []
    r = got["open"][0]
    assert (r["id"], r["kind"], r["text"], r["page"], r["title"], r["by"]) == (
        fid, "bug", "Forward sayfasında\n2Y boş görünüyor", "forward", "Forward", "Ali Veli")
    # "İlgilenildi": off the badge, into the history - by whom, when
    got = desk.report_done(ayse, fid)
    assert got["open"] == [] and got["count"] == 0 and desk.state(ayse)["feedback"] == 0
    assert got["done"][0]["id"] == fid and got["done"][0]["done_by"] == "Ayşe Yönetici" and got["done"][0]["done_at"]
    told = desk.svc.told
    assert desk.report_done(ayse, fid)["count"] == 0 and desk.svc.told == told       # twice (two administrators at once) is once
    assert desk.report_done(ayse, fid, done=False)["count"] == 1                       # open again
    assert desk.state(ayse)["feedback"] == 1
    _refused(404, desk.report_done, ayse, 99999)


def test_a_report_is_checked_and_its_pace_is_limited(desk):
    ali, boss = _user(desk, "Ali Veli"), _user(desk, "Yönetici", admin=True)
    for kind, text in (("soru", "x"), ("bug", "   "), ("idea", "x" * (dk.REPORT_MAX + 1)), ("idea", "\n".join("a" * 61))):
        _refused(400, desk.report, ali, kind, text)
    # a page that is not one of the dashboard's is not kept; the hidden characters that turn the text around go;
    # the rest stays text (the page shows it as text)
    fid = desk.report(ali, "idea", "Gece ‮modu‬ olsun", "javascript:alert(1)", "<b>Forward</b>\x00")["id"]
    r = desk.reports(boss)["open"][0]
    assert (r["id"], r["text"], r["page"], r["title"]) == (fid, "Gece modu olsun", None, "<b>Forward</b>")
    for _ in range(dk.PACE["feedback"][0] - 1):
        desk.report(ali, "bug", "bir daha")
    assert "hızlı" in _refused(429, desk.report, ali, "bug", "bir fazla")
    desk.report(boss, "bug", "başkası yazabilir")                                  # the pace is each user's own


def test_reports_are_kept_across_a_restart(tmp_path):
    d, store = _desk(tmp_path / "tto.db")
    ali, boss = _user(d, "Ali Veli"), _user(d, "Yönetici", admin=True)
    first = d.report(ali, "bug", "bir")["id"]
    d.report(ali, "idea", "iki")
    d.report_done(boss, first)
    store.close()
    d, store = _desk(tmp_path / "tto.db")
    got = d.reports(boss)
    assert [r["text"] for r in got["open"]] == ["iki"] and [r["text"] for r in got["done"]] == ["bir"]
    assert d.state(boss)["feedback"] == 1
    store.close()


# ---------------------------------------------------------------------- Sosyal
def test_the_chat_is_everybody_s_and_kept(tmp_path):
    d, store = _desk(tmp_path / "tto.db")
    ali, can = _user(d, "Ali Veli"), _user(d, "Can Kaya")
    first = d.say(ali, "Günaydın\r\n\r\n2Y'de alıcı var mı?  ")
    assert (first["text"], first["name"], first["mine"]) == ("Günaydın\n\n2Y'de alıcı var mı?", "Ali Veli", True)
    assert d.counters()["chat"] == 1 and d.svc.told == 1
    d.say(can, "var, 35,10")
    seen = d.chat(can)
    assert [m["text"] for m in seen["messages"]] == [first["text"], "var, 35,10"] and not seen["more"]
    assert [m["mine"] for m in seen["messages"]] == [False, True] and seen["last"] == seen["messages"][-1]["id"]
    assert seen["messages"][0]["at"][:10] == _day()
    # the menu's badge: the others' messages after the last one this browser showed (nothing before it showed one)
    assert d.state(ali, first["id"])["chat"] == {"last": seen["last"], "unread": 1}
    assert d.state(can, first["id"])["chat"]["unread"] == 0 and d.state(ali)["chat"]["unread"] == 0
    store.close()
    d, store = _desk(tmp_path / "tto.db")                         # the dashboard started again: all of it is there
    assert [m["text"] for m in d.chat(ali)["messages"]] == [first["text"], "var, 35,10"]
    store.close()


def test_a_message_is_checked_paged_and_taken_back_by_its_writer_only(desk):
    ali, can = _user(desk, "Ali Veli"), _user(desk, "Can Kaya")
    for text in ("", " \n ", "x" * (dk.CHAT_MAX + 1), "\n".join("a" * (dk.CHAT_LINES + 1))):
        _refused(400, desk.say, ali, text)
    mine = desk.say(ali, "a‮b\x07c")
    assert mine["text"] == "abc"
    for i in range(dk.CHAT_PAGE + 5):                            # a long day of chat (straight into the database)
        desk.store.add_chat(can, "mesaj %d" % i)
    page = desk.chat(ali)
    assert len(page["messages"]) == dk.CHAT_PAGE and page["more"]
    assert page["messages"][-1]["text"] == "mesaj %d" % (dk.CHAT_PAGE + 4)
    earlier = desk.chat(ali, before=page["messages"][0]["id"])
    assert [m["text"] for m in earlier["messages"]] == ["abc"] + ["mesaj %d" % i for i in range(5)] and not earlier["more"]
    again = desk.chat(ali, since=mine["id"])                     # what a page that has all of it reads again
    assert len(again["messages"]) == dk.CHAT_PAGE + 6 and not again["more"]
    # one's own message is taken back for everybody; somebody else's is not one's to take
    other = earlier["messages"][1]
    assert "kendi" in _refused(403, desk.unsay, ali, other["id"])
    assert desk.unsay(ali, mine["id"]) == {"deleted": mine["id"]}
    assert mine["id"] not in [m["id"] for m in desk.chat(can, since=0)["messages"]]
    _refused(404, desk.unsay, ali, mine["id"])


def test_the_chat_s_pace_is_limited(desk):
    ali, can = _user(desk, "Ali Veli"), _user(desk, "Can Kaya")
    said = [desk.say(ali, "hızlı %d" % i) for i in range(dk.PACE["chat"][0])]
    for m in said:                                               # taking them back does not give their places back
        desk.unsay(ali, m["id"])
    _refused(429, desk.say, ali, "bir fazla")
    desk.say(can, "ben yazabilirim")


# ---------------------------------------------------------------------- Ajanda
def test_the_agenda_of_the_desk_and_of_each_trader(desk):
    ali, can, boss = _user(desk, "Ali Veli"), _user(desk, "Can Kaya"), _user(desk, "Yönetici", admin=True)
    a = desk.add(ali, _day(0), "14:30", "PPK metnini oku", deadline=True)["added"]
    b = desk.add(ali, _day(0), None, "Swap limitlerini kontrol et")["added"]
    c = desk.add(ali, _day(1), "9:05", "Kendi notum", shared=False)["added"]
    d = desk.add(can, _day(-3), None, "Rapor gönder", deadline=True)["added"]          # a deadline not met, days ago
    e = desk.add(can, _day(-2), "10:00", "Toplantı")["added"]                          # the past
    # items that aged: before the page goes back to (and before any new item may be added for)
    old = desk.store.add_agenda(None, _day(-dk.AGENDA_PAST_DAYS - 5), None, "Çok eski", False, can)
    late = desk.store.add_agenda(None, _day(-dk.AGENDA_PAST_DAYS - 9), "11:00", "Unutulan deadline", True, can)
    seen = desk.agenda(ali)
    # by day, then time (the untimed first in their day); a deadline not met stays, however old
    assert [it["id"] for it in seen["items"]] == [late, d, e, b, a, c] and old not in [it["id"] for it in seen["items"]]
    assert seen["today"] == _day(0) and seen["past_days"] == dk.AGENDA_PAST_DAYS
    it = {x["id"]: x for x in seen["items"]}
    assert (it[c]["time"], it[c]["shared"], it[a]["deadline"], it[a]["shared"], it[d]["by"]) == ("09:05", False, True, True, "Can Kaya")
    assert it[b]["can_delete"] and not it[d]["can_delete"] and it[c]["can_delete"]
    # another trader sees the desk's items, not Ali's own one - and cannot reach it either
    assert [x["id"] for x in desk.agenda(can)["items"]] == [late, d, e, b, a]
    _refused(404, desk.mark, can, c)
    _refused(404, desk.remove, can, c)
    # what is due (the menu's badge, the reminders): today's, tomorrow's and the deadlines not met
    assert [x["id"] for x in desk.state(ali)["agenda"]] == [late, d, b, a, c]
    assert [x["id"] for x in desk.state(can)["agenda"]] == [late, d, b, a]
    # the desk's item is ticked off by anybody (who, when) and leaves what is due; it can be undone
    done = {x["id"]: x for x in desk.mark(can, a)["items"]}[a]
    assert done["done"] and done["done_by"] == "Can Kaya" and done["done_at"][:10] == _day(0)
    assert a not in [x["id"] for x in desk.state(ali)["agenda"]]
    assert not {x["id"]: x for x in desk.mark(ali, a, done=False)["items"]}[a]["done"]
    desk.mark(can, late)                                             # a deadline met long ago leaves the page
    assert late not in [x["id"] for x in desk.agenda(ali)["items"]] + [x["id"] for x in desk.state(ali)["agenda"]]
    # deleted: the desk's item by whoever added it or an administrator, one's own by oneself
    assert "ekleyen" in _refused(403, desk.remove, can, b)
    assert b not in [x["id"] for x in desk.remove(boss, b)["items"]]
    assert e not in [x["id"] for x in desk.remove(can, e)["items"]]
    assert c not in [x["id"] for x in desk.remove(ali, c)["items"]]
    _refused(404, desk.mark, ali, c)


def test_an_agenda_item_is_checked_and_kept(tmp_path):
    d, store = _desk(tmp_path / "tto.db")
    ali = _user(d, "Ali Veli")
    for args in (("15.11.2026", None, "x"), ("2026-02-30", None, "x"), ("1999-12-31", None, "x"), (_day(), "25:00", "x"),
                 (_day(), "9.30", "x"), (_day(), None, "  "), (_day(), None, "x" * (dk.AGENDA_MAX + 1)),
                 (_day(-dk.AGENDA_PAST_DAYS - 1), None, "x")):
        _refused(400, d.add, ali, *args)
    assert d.add(ali, _day(-dk.AGENDA_PAST_DAYS), None, "geç kalmış not")["added"]
    aid = d.add(ali, _day(), "08:00", "Sabah   toplantısı\nnotu", deadline="true", shared=False)["added"]
    assert d.counters()["agenda"] == 2
    store.close()
    d, store = _desk(tmp_path / "tto.db")
    item = d.agenda(ali)["items"][1]
    assert (item["id"], item["text"], item["time"], item["deadline"], item["shared"]) == (aid, "Sabah toplantısı notu", "08:00",
                                                                                         True, False)
    for i in range(dk.PACE["agenda"][0]):
        d.add(ali, _day(1), None, "iş %d" % i)
    _refused(429, d.add, ali, _day(1), None, "bir fazla")
    store.close()


def test_the_agenda_page_is_bounded(desk, monkeypatch):
    monkeypatch.setattr(dk, "AGENDA_LIMIT", 3)
    monkeypatch.setattr(dk, "AGENDA_LATE", 2)
    ali = _user(desk, "Ali Veli")
    for n in (5, 1, 3, 2):
        desk.add(ali, _day(n), None, "ileride %d" % n)
    for n in range(3):
        desk.store.add_agenda(None, _day(-dk.AGENDA_PAST_DAYS - 10 - n), None, "eski %d" % n, True, ali)
    # the latest of the old deadlines not met, then the nearest days
    assert [it["text"] for it in desk.agenda(ali)["items"]] == ["eski 1", "eski 0", "ileride 1", "ileride 2", "ileride 3"]


# ---------------------------------------------------------------------- the service: no new generation
def test_the_corner_tells_the_pages_without_a_new_generation(module_service):
    svc = module_service
    user = svc.login("Sosyal Deneme")["user"]
    heard = []
    svc.add_listener(heard.append)
    try:
        gen, before = svc.gen, svc.desk.counters()
        svc.desk.say(user, "merhaba")
        svc.desk.add(user, _day(), None, "iş")
        assert heard == [gen, gen] and svc.gen == gen                # the open tables are not read again for a chat line
        after = svc.desk.counters()
        assert after == dict(before, chat=before["chat"] + 1, agenda=before["agenda"] + 1)
        # the live stream of a user does not carry the reports' counter (nobody else learns that one came or went)
        assert svc.desk.counters(admin=False) == {"chat": after["chat"], "agenda": after["agenda"]}
        assert not svc.desk.is_admin(user) and not svc.desk.is_admin(None)
    finally:
        svc.remove_listener(heard.append)
    assert [p["id"] for p in svc.nav()][-2:] == ["social", "agenda"]
    assert {p["group"] for p in svc.nav() if p["id"] in ("social", "agenda")} == {"Masa"}


# ---------------------------------------------------------------------- over HTTP
@pytest.fixture(scope="module")
def client(module_service):
    with TestClient(create_app(module_service)) as c:
        yield c


def test_every_call_needs_a_session(client):
    for method, path in (("GET", "/api/desk"), ("GET", "/api/feedback"), ("POST", "/api/feedback"), ("POST", "/api/feedback/1"),
                         ("GET", "/api/social"), ("POST", "/api/social"), ("DELETE", "/api/social/1"), ("GET", "/api/agenda"),
                         ("POST", "/api/agenda"), ("POST", "/api/agenda/1"), ("DELETE", "/api/agenda/1")):
        res = client.request(method, path, headers=ANON, json={} if method == "POST" else None)
        assert res.status_code == 401, (method, path)
    for path in ("/static/js/desk.js", "/static/js/pages/social.js", "/static/js/pages/agenda.js"):
        assert client.get(path).status_code == 200, path
    assert 'id="btn-feedback"' in client.get("/").text


def test_reports_over_http(client, module_service):
    u, a = auth(module_service, "Http Trader"), auth(module_service, "Http Yönetici", admin=True)
    res = client.post("/api/feedback", json={"kind": "bug", "text": "Grafik boş", "page": "fx", "title": "Spot / FX"}, headers=u)
    assert res.status_code == 200
    fid = res.json()["id"]
    assert "feedback" not in client.get("/api/desk", headers=u).json()
    assert client.get("/api/desk", headers=a).json()["feedback"] >= 1
    assert client.get("/api/feedback", headers=u).status_code == 403
    assert client.post("/api/feedback/%d" % fid, json={}, headers=u).status_code == 403
    listed = client.get("/api/feedback", headers=a).json()
    assert any(r["id"] == fid and r["by"] == "Http Trader" and r["title"] == "Spot / FX" for r in listed["open"])
    after = client.post("/api/feedback/%d" % fid, json={}, headers=a).json()
    assert fid not in [r["id"] for r in after["open"]] and after["done"][0]["id"] == fid
    assert client.post("/api/feedback", json={"kind": "bug", "text": ""}, headers=u).status_code == 400


def test_the_chat_over_http(client, module_service):
    u, a = auth(module_service, "Http Trader"), auth(module_service, "Http Yönetici", admin=True)
    # a change sent from another site's page is turned away before anything is read
    assert client.post("/api/social", json={"text": "x"}, headers=dict(u, Origin="http://kotu.example")).status_code == 403
    m = client.post("/api/social", json={"text": "<img src=x onerror=alert(1)>"}, headers=u).json()
    assert m["text"] == "<img src=x onerror=alert(1)>" and m["mine"]          # kept as text: the page shows it as text
    got = client.get("/api/social", headers=a).json()
    assert got["messages"][-1]["id"] == m["id"] and not got["messages"][-1]["mine"] and got["last"] == m["id"]
    assert client.get("/api/desk", params={"seen": m["id"] - 1}, headers=a).json()["chat"]["unread"] == 1
    assert client.delete("/api/social/%d" % m["id"], headers=a).status_code == 403
    assert client.delete("/api/social/%d" % m["id"], headers=u).json() == {"deleted": m["id"]}
    assert client.post("/api/social", json={"text": "x" * (dk.CHAT_MAX + 1)}, headers=u).status_code == 400


def test_the_agenda_over_http(client, module_service):
    u, a = auth(module_service, "Http Trader"), auth(module_service, "Http Yönetici", admin=True)
    res = client.post("/api/agenda", json={"day": _day(), "time": "16:00", "text": "Kapanış", "deadline": True}, headers=u)
    aid = res.json()["added"]
    assert any(i["id"] == aid and i["deadline"] and i["shared"] for i in client.get("/api/agenda", headers=a).json()["items"])
    assert any(i["id"] == aid for i in client.get("/api/desk", headers=a).json()["agenda"])
    mine = client.post("/api/agenda", json={"day": _day(), "text": "Kendi işim", "shared": False}, headers=u).json()["added"]
    assert mine not in [i["id"] for i in client.get("/api/agenda", headers=a).json()["items"]]
    assert client.post("/api/agenda/%d" % mine, json={"done": True}, headers=a).status_code == 404
    done = client.post("/api/agenda/%d" % aid, json={"done": True}, headers=a).json()
    assert next(i for i in done["items"] if i["id"] == aid)["done_by"] == "Http Yönetici"
    assert client.delete("/api/agenda/%d" % aid, headers=auth(module_service, "Üçüncü Kişi")).status_code == 403
    assert client.delete("/api/agenda/%d" % aid, headers=u).status_code == 200
    assert client.post("/api/agenda", json={"day": "yarın", "text": "x"}, headers=u).status_code == 400
