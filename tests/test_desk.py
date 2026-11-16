"""The desk's own corner (tto/desk.py): reports to the administrators (Hata / Öneri), the traders' chat (Sosyal) and the
agenda (Ajanda) with its recurring items (Tekrarlayan işler) - who sees and does what, what is kept (across a restart
too), the limits, the recurring items' days and alarms; then the same over HTTP.

Most tests use the corner on a database of their own (``_desk``): no workbook is loaded for them - the desk's TRY
holidays are the test's (``svc.holidays``) and its clock too where it matters (``clock``)."""
import datetime as dt
import sqlite3
import threading
import time

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto import desk as dk
from tto.desk import Desk
from tto.server import create_app
from tto.service import Service, ServiceError
from tto.store import Store


class _Svc(object):
    """What the corner needs of the service: its store, who is signed in, a way to tell the pages, the holidays."""
    require_user = Service.require_user
    require_admin = Service.require_admin

    def __init__(self, store):
        self.store = store
        self.told = 0
        self.holidays = set()                          # the desk's TRY holidays (Ayarlar → Tatiller), as dates
        self.holiday_reads = 0

    def nudge(self):
        self.told += 1

    def saw(self, user):
        pass                                            # (who has the dashboard open: nothing kept here)

    def holiday_dates(self, ccys):
        assert tuple(ccys) == ("TRY",)
        self.holiday_reads += 1
        return frozenset(self.holidays)


class _Clock(object):
    """The desk's clock, set by the test."""

    def __init__(self):
        self.at = dt.datetime(2026, 11, 16, 9, 0)

    def __call__(self):
        return self.at

    def set(self, text):
        self.at = dt.datetime.fromisoformat(text)


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(dk, "_now", c)
    return c


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


# ---------------------------------------------------------------------- Ajanda: recurring items
def _rule(kind, weekdays=None, start=None, end=None):
    return {"kind": kind, "weekdays": weekdays, "start_day": start, "end_day": end}


def _days(rule, first, last, shut=frozenset()):
    """The days (MM-DD) from ``first`` to ``last`` a rule falls on."""
    day, out = dt.date.fromisoformat(first), []
    while day <= dt.date.fromisoformat(last):
        if dk.scheduled(rule, day, shut):
            out.append(day.isoformat()[5:])
        day += dt.timedelta(days=1)
    return out


def test_each_kind_of_recurring_item_falls_on_its_days():
    # Cumhuriyet Bayramı (Thursday 29.10.2026) and Kurban Bayramı (27-29.05.2026) on the desk's TRY list
    shut = frozenset({"2026-10-29", "2026-05-27", "2026-05-28", "2026-05-29"})
    # Her gün: every day, a weekend and a holiday too
    assert _days(_rule("daily"), "2026-10-28", "2026-11-01", shut) == ["10-28", "10-29", "10-30", "10-31", "11-01"]
    # Her iş günü: no Saturday, Sunday or TRY holiday
    assert _days(_rule("workdays"), "2026-10-26", "2026-11-03", shut) == ["10-26", "10-27", "10-28", "10-30", "11-02", "11-03"]
    # Seçili günler: the days of the week chosen, as they are (the Thursday holiday too: the days were chosen)
    assert _days(_rule("weekdays", "1,4,7"), "2026-10-26", "2026-11-02", shut) == ["10-26", "10-29", "11-01", "11-02"]
    # Ayın son iş günü: 30.11.2026 a Monday; 31.01.2027 a Sunday - Friday the 29th; May 2026 ends on a weekend after
    # three days of Kurban Bayramı - Tuesday the 26th
    month_end = _rule("monthend")
    assert _days(month_end, "2026-11-01", "2027-01-31", shut) == ["11-30", "12-31", "01-29"]
    assert _days(month_end, "2026-05-01", "2026-06-30", shut) == ["05-26", "06-30"]
    assert dk.month_end(dt.date(2026, 5, 3), shut) == dt.date(2026, 5, 26)
    assert dk.month_end(dt.date(2026, 5, 3), frozenset()) == dt.date(2026, 5, 29)      # without the holidays: Friday
    # the first and last days bound every kind
    assert _days(_rule("daily", start="2026-10-28", end="2026-10-30"), "2026-10-26", "2026-11-02") == ["10-28", "10-29", "10-30"]
    assert _days(_rule("workdays", start="2026-10-30"), "2026-10-26", "2026-11-03", shut) == ["10-30", "11-02", "11-03"]
    assert _days(_rule("monthend", end="2026-12-30"), "2026-11-01", "2027-01-31", shut) == ["11-30"]
    # how the page says it
    assert [dk.describe(r) for r in (_rule("daily"), _rule("workdays"), _rule("weekdays", "1,3,5"),
                                     _rule("weekdays", "1,2,3,4,5,6,7"), month_end)] == [
        "Her gün", "Her iş günü", "Pzt, Çar, Cum", "Her gün", "Ayın son iş günü"]


def test_recurring_items_on_the_agenda(desk, clock):
    desk.svc.holidays = {dt.date(2026, 10, 29)}
    desk.holidays_changed()                                                  # (as Service.set_holidays tells it)
    ali, can = _user(desk, "Ali Veli"), _user(desk, "Can Kaya")
    clock.set("2026-10-26 09:00")                                            # a Monday
    one = desk.add(ali, "2026-10-26", "11:00", "Tek seferlik")["added"]
    w = desk.add_rule(ali, "workdays", "10:00", "TLREF fixingini kontrol et")["added_rule"]
    d = desk.add_rule(can, "daily", "08:30", "Sabah raporu", deadline=True)["added_rule"]      # its time today has passed
    m = desk.add_rule(ali, "monthend", "16:00", "Ay sonu mutabakatı")["added_rule"]
    k = desk.add_rule(ali, "weekdays", "17:00", "Kendi notum", shared=False, weekdays=[1, 3])["added_rule"]
    got = desk.agenda(ali)
    # today's days among the day's items, by time - none of the 08:30 one: added after its time, it starts tomorrow
    assert [(it.get("rule"), it["time"]) for it in got["items"]] == [(w, "10:00"), (None, "11:00"), (k, "17:00")]
    first = got["items"][0]
    assert (first["id"], first["day"], first["repeat"], first["text"], first["done"], first["shared"], first["by"],
            first["can_delete"]) == ("r%d@2026-10-26" % w, "2026-10-26", "Her iş günü", "TLREF fixingini kontrol et", False,
                                     True, "Ali Veli", False)
    assert got["items"][1]["id"] == one
    # the recurring items: how they repeat, when they come next, who may change them
    rules = {r["id"]: r for r in got["rules"]}
    assert [r["id"] for r in got["rules"]] == [d, w, m, k]                 # by time
    assert rules[d]["next"] == {"day": "2026-10-27", "time": "08:30"} and rules[d]["deadline"] and rules[d]["by"] == "Can Kaya"
    assert rules[m]["next"] == {"day": "2026-10-30", "time": "16:00"}      # October ends on a Saturday: Friday the 30th
    assert (rules[k]["repeat"], rules[k]["repeat_text"], rules[k]["weekdays"], rules[k]["shared"]) == ("weekdays", "Pzt, Çar", [1, 3], False)
    assert rules[w]["can_edit"] and not rules[d]["can_edit"] and got["rules_max"] == dk.RULES_MAX
    # another trader sees the desk's, not Ali's own
    seen = desk.agenda(can)
    assert [r["id"] for r in seen["rules"]] == [d, w, m] and k not in [it.get("rule") for it in seen["items"]]
    assert not {r["id"]: r for r in seen["rules"]}[w]["can_edit"]
    # the menu's badge counts today's days not done
    assert [x["id"] for x in desk.state(ali)["agenda"]] == [one, "r%d@2026-10-26" % w, "r%d@2026-10-26" % k]
    # a holiday: no "Her iş günü" - the deadline of every day is late since 08:30 (Tuesday's and Wednesday's not done)
    clock.set("2026-10-29 09:00")
    got = desk.agenda(ali)
    assert [(it["day"], it.get("rule")) for it in got["items"] if it["day"] >= "2026-10-27"] == [
        ("2026-10-27", d), ("2026-10-28", d), ("2026-10-29", d)]
    assert {r["id"]: r for r in got["rules"]}[w]["next"] == {"day": "2026-10-30", "time": "10:00"}
    assert [x["id"] for x in desk.state(ali)["agenda"]] == ["r%d@2026-10-2%d" % (d, n) for n in (7, 8, 9)]
    # the month's last business day: Friday the 30th
    clock.set("2026-10-30 09:00")
    assert [it.get("rule") for it in desk.agenda(can)["items"] if it["day"] == "2026-10-30"] == [d, w, m]
    # a first day far ahead: it comes then
    far = desk.add_rule(ali, "workdays", "10:00", "Uzak bir başlangıç", start="2028-01-03")["added_rule"]
    assert {r["id"]: r for r in desk.agenda(ali)["rules"]}[far]["next"] == {"day": "2028-01-03", "time": "10:00"}
    # the holidays are kept, not read for every request - and read again on a new day in the background: the agenda (the
    # shell's state) does not wait for a busy calculation thread
    if desk._refreshing is not None:
        desk._refreshing.join(10)
    reads = desk.svc.holiday_reads
    desk.agenda(ali)
    desk.state(can)
    assert desk.svc.holiday_reads == reads
    gate, read = threading.Event(), desk.svc.holiday_dates
    desk.svc.holiday_dates = lambda ccys: gate.wait(10) and read(ccys)
    clock.set("2026-10-31 09:00")
    began = time.monotonic()
    assert desk.state(can)["agenda"] and time.monotonic() - began < 2
    gate.set()
    desk._refreshing.join(10)
    assert desk.svc.holiday_reads == reads + 1 and desk.holidays() == {"2026-10-29"}


def _told(desk, clock, user, at):
    """What the desk tells ``user`` at ``at`` of the recurring items: [(day, stage, text, kind)], and the seconds to the
    next change."""
    clock.set(at)
    st = desk.state(user)
    return [(a["day"], a["stage"], a["text"], a["kind"]) for a in st["alarms"]], st["next"]


def test_the_alarms_of_a_recurring_item(desk, clock):
    ali, can = _user(desk, "Ali Veli"), _user(desk, "Can Kaya")
    clock.set("2026-11-16 09:00")                                            # a Monday
    rid = desk.add_rule(ali, "workdays", "10:00", "Swap limitleri", deadline=True)["added_rule"]
    day = "2026-11-16"
    assert _told(desk, clock, ali, "2026-11-16 09:44") == ([], 60)            # 15 minutes before its time: in a minute
    assert _told(desk, clock, ali, "2026-11-16 09:45") == ([(day, "soon", "Deadline yaklaşıyor (15 dk): 10:00 · Swap limitleri", "warn")], 900)
    alarm = desk.state(ali)["alarms"][0]
    assert (alarm["key"], alarm["rule"], alarm["time"], alarm["deadline"], alarm["shared"], alarm["repeat"], alarm["late"]) == (
        "r%d@%s:soon" % (rid, day), rid, "10:00", True, True, "Her iş günü", False)
    assert _told(desk, clock, ali, "2026-11-16 09:52:30")[0][0][2] == "Deadline yaklaşıyor (8 dk): 10:00 · Swap limitleri"
    assert _told(desk, clock, ali, "2026-11-16 10:00:20")[0] == [(day, "due", "Deadline geldi: 10:00 · Swap limitleri", "err")]
    assert desk.state(ali)["alarms"][0]["key"] == "r%d@%s:due" % (rid, day)
    # first told two minutes or more after its time - the dashboard was not open then: late
    told, wait = _told(desk, clock, can, "2026-11-16 13:30")
    assert told == [(day, "due", "Deadline geçti: 10:00 · Swap limitleri", "err")] and desk.state(can)["alarms"][0]["late"]
    assert wait == (dt.datetime(2026, 11, 17, 9, 45) - dt.datetime(2026, 11, 16, 13, 30)).total_seconds()    # tomorrow's
    # "Ertele 10 dk": quiet for Ali until then - Can is told as before; then told again (a new key: told once more)
    clock.set("2026-11-16 10:01")
    assert desk.snooze(ali, rid, day)["snoozed"] == "10:11"
    assert _told(desk, clock, ali, "2026-11-16 10:05") == ([], 360)
    assert _told(desk, clock, can, "2026-11-16 10:05")[0][0][1] == "due"
    assert _told(desk, clock, ali, "2026-11-16 10:11") == ([(day, "snooze", "Ertelenen deadline: 10:00 · Swap limitleri", "err")],
                                                            (dt.datetime(2026, 11, 17, 9, 45) - dt.datetime(2026, 11, 16, 10, 11)).total_seconds())
    assert desk.state(ali)["alarms"][0]["key"] == "r%d@%s:z101100" % (rid, day)
    # "Bugün tamam" (by anybody, the desk's): nobody is told of that day any more - the next day it comes again
    clock.set("2026-11-16 10:12")
    desk.rule_done(can, rid, day)
    assert _told(desk, clock, ali, "2026-11-16 10:12")[0] == [] and _told(desk, clock, can, "2026-11-16 10:12")[0] == []
    assert _told(desk, clock, ali, "2026-11-17 09:45")[0][0][:2] == ("2026-11-17", "soon")
    # put off before its time, a deadline is "coming" when the snooze ends
    clock.set("2026-11-17 09:46")
    desk.snooze(ali, rid, "2026-11-17")
    assert _told(desk, clock, ali, "2026-11-17 09:56")[0] == [("2026-11-17", "snooze", "Deadline yaklaşıyor (4 dk): 10:00 · Swap limitleri", "warn")]
    assert _told(desk, clock, ali, "2026-11-17 10:00")[0][0][1] == "due"
    # not done, a deadline of a day before stays on the badge as late - and is not told again
    clock.set("2026-11-18 08:00")
    assert "r%d@2026-11-17" % rid in [x["id"] for x in desk.state(ali)["agenda"]] and desk.state(ali)["alarms"] == []
    assert "r%d@2026-11-16" % rid not in [x["id"] for x in desk.state(ali)["agenda"]]           # (that one was done)
    # an item without a deadline: at its time only, "late" when told later - and of that day only
    clock.set("2026-11-18 08:00")
    plain = desk.add_rule(can, "daily", "08:30", "Ekranları aç")["added_rule"]
    assert _told(desk, clock, ali, "2026-11-18 08:20")[0] == []
    assert ("2026-11-18", "due", "Hatırlatma: 08:30 · Ekranları aç", "") in _told(desk, clock, ali, "2026-11-18 08:30")[0]
    assert ("2026-11-18", "due", "Gecikmiş: 08:30 · Ekranları aç", "warn") in _told(desk, clock, ali, "2026-11-18 08:40")[0]
    clock.set("2026-11-19 08:00")
    assert "r%d@2026-11-18" % plain not in [x["id"] for x in desk.state(ali)["agenda"]]
    # a time just after midnight: told the evening before, as the day's own
    desk.add_rule(ali, "daily", "00:05", "Gece işi", deadline=True)
    assert [a for a in _told(desk, clock, ali, "2026-11-19 23:50")[0] if "Gece" in a[2]] == [
        ("2026-11-20", "soon", "Deadline yaklaşıyor (15 dk): 00:05 · Gece işi", "warn")]


def test_each_day_of_a_recurring_item_is_its_own(desk, clock):
    desk.svc.holidays = {dt.date(2026, 11, 20)}
    desk.holidays_changed()
    ali, can, boss = _user(desk, "Ali Veli"), _user(desk, "Can Kaya"), _user(desk, "Yönetici", admin=True)
    clock.set("2026-11-16 09:00")
    rid = desk.add_rule(ali, "daily", "10:00", "Kapanış kontrolü", deadline=True)["added_rule"]
    work = desk.add_rule(ali, "workdays", "15:00", "Pozisyon raporu")["added_rule"]

    def days(user, rule=rid):
        return [(it["day"], it["done"], it["done_by"]) for it in desk.agenda(user)["items"] if it.get("rule") == rule]

    clock.set("2026-11-18 11:00")                                           # two days on: Monday's and Tuesday's not done
    assert days(can) == [("2026-11-16", False, None), ("2026-11-17", False, None), ("2026-11-18", False, None)]
    # done on one day by anybody (the desk's): that day only - who and when
    done = {it["day"]: it for it in desk.rule_done(can, rid, "2026-11-17")["items"] if it.get("rule") == rid}
    assert set(done) == {"2026-11-16", "2026-11-18"}                         # a day before, done, leaves the list
    got = {it["day"]: it for it in desk.rule_done(can, rid, "2026-11-18")["items"] if it.get("rule") == rid}
    assert got["2026-11-18"]["done"] and got["2026-11-18"]["done_by"] == "Can Kaya" and got["2026-11-18"]["done_at"]
    assert not got["2026-11-16"]["done"]
    assert set(desk.store.agenda_rule_days("2026-11-01", "2026-11-30")) == {(rid, "2026-11-17"), (rid, "2026-11-18")}
    told = desk.svc.told
    desk.rule_done(ali, rid, "2026-11-18")                                   # done already: Can's stands, nobody told
    assert days(ali)[-1] == ("2026-11-18", True, "Can Kaya") and desk.svc.told == told
    assert days(ali, work) == [("2026-11-18", False, None)]                  # the other item's day is untouched
    # not done after all; a day it does not fall on, a day to come, a day before it was added: refused
    desk.rule_done(ali, rid, "2026-11-18", done=False)
    assert days(ali)[-1] == ("2026-11-18", False, None)
    clock.set("2026-11-21 11:00")                                            # a Saturday
    for rule, day in ((work, "2026-11-21"), (work, "2026-11-20"), (rid, "2026-11-22"), (rid, "2026-11-15"), (rid, "2026-10-01"),
                      (rid, "21.11.2026")):
        _refused(400, desk.rule_done, can, rule, day)                         # (20.11: a holiday of the desk's list)
    _refused(404, desk.rule_done, can, 99999, "2026-11-21")
    # changed - by whoever added it or an administrator; a new time counts from now: the days before are not late under it
    for call, args in ((desk.edit_rule, (rid, "daily", "12:00", "x", True)), (desk.pause_rule, (rid,)), (desk.remove_rule, (rid,))):
        assert "ekleyen" in _refused(403, call, can, *args)
    late = [it["day"] for it in desk.agenda(can)["items"] if it.get("rule") == rid and not it["done"]]
    assert late == ["2026-11-16", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]
    got = desk.edit_rule(boss, rid, "daily", "12:00", "Kapanış kontrolü (öğlen)", deadline=True)
    assert [it["day"] for it in got["items"] if it.get("rule") == rid] == ["2026-11-21"]
    r = {x["id"]: x for x in got["rules"]}[rid]
    assert (r["time"], r["text"], r["by"], r["next"]) == ("12:00", "Kapanış kontrolü (öğlen)", "Ali Veli", {"day": "2026-11-21", "time": "12:00"})
    # its words only: the days stay as they were
    clock.set("2026-11-23 13:00")
    desk.edit_rule(ali, rid, "daily", "12:00", "Kapanış kontrolü", deadline=True)
    assert [it["day"] for it in desk.agenda(ali)["items"] if it.get("rule") == rid] == ["2026-11-21", "2026-11-22", "2026-11-23"]
    # paused: no days, nothing told, nothing to tick off; going on, it counts from then
    got = desk.pause_rule(boss, rid)
    r = {x["id"]: x for x in got["rules"]}[rid]
    assert r["paused"] and r["paused_by"] == "Yönetici" and r["next"] is None and rid not in [it.get("rule") for it in got["items"]]
    assert "duraklat" in _refused(400, desk.rule_done, can, rid, "2026-11-23")
    assert rid not in [a["rule"] for a in desk.state(ali)["alarms"]]
    clock.set("2026-11-26 12:30")
    got = desk.pause_rule(ali, rid, paused=False)
    assert not {x["id"]: x for x in got["rules"]}[rid]["paused"] and rid not in [it.get("rule") for it in got["items"]]
    assert {x["id"]: x for x in got["rules"]}[rid]["next"] == {"day": "2026-11-27", "time": "12:00"}
    # deleted with the days it was done
    desk.rule_done(can, work, "2026-11-26")
    assert work not in [r["id"] for r in desk.remove_rule(boss, work)["rules"]]
    assert all(rule != work for rule, _ in desk.store.agenda_rule_days("2026-11-01", "2026-11-30"))
    _refused(404, desk.rule_done, can, work, "2026-11-26")


def test_one_s_own_recurring_item_is_nobody_else_s(desk, clock):
    ali, can, boss = _user(desk, "Ali Veli"), _user(desk, "Can Kaya"), _user(desk, "Yönetici", admin=True)
    clock.set("2026-11-16 09:00")
    own = desk.add_rule(ali, "workdays", "09:30", "Kendi işim", shared=False, deadline=True)["added_rule"]
    clock.set("2026-11-16 09:20")
    assert [a["rule"] for a in desk.state(ali)["alarms"]] == [own] and desk.state(can)["alarms"] == []
    for user in (can, boss):
        assert own not in [r["id"] for r in desk.agenda(user)["rules"]] + [it.get("rule") for it in desk.agenda(user)["items"]]
        for call, args in ((desk.rule_done, (own, "2026-11-16")), (desk.snooze, (own, "2026-11-16")),
                           (desk.edit_rule, (own, "daily", "10:00", "x")), (desk.pause_rule, (own,)), (desk.remove_rule, (own,))):
            _refused(404, call, user, *args)
    assert desk.rule_done(ali, own, "2026-11-16")["items"][0]["done_by"] == "Ali Veli"
    assert own not in [r["id"] for r in desk.remove_rule(ali, own)["rules"]]


def test_a_recurring_item_is_checked_limited_and_kept(tmp_path, clock, monkeypatch):
    d, store = _desk(tmp_path / "tto.db")
    ali = _user(d, "Ali Veli")
    clock.set("2026-11-16 09:00")
    for args, kw in ((("haftalık", "10:00", "x"), {}), (("", "10:00", "x"), {}), (("daily", None, "x"), {}),
                     (("daily", "", "x"), {}), (("daily", "25:00", "x"), {}), (("daily", "10:00", "  "), {}),
                     (("daily", "10:00", "x" * (dk.AGENDA_MAX + 1)), {}), (("weekdays", "10:00", "x"), {"weekdays": []}),
                     (("weekdays", "10:00", "x"), {}), (("weekdays", "10:00", "x"), {"weekdays": [0, 8]}),
                     (("weekdays", "10:00", "x"), {"weekdays": "pzt"}), (("daily", "10:00", "x"), {"start": "16.11.2026"}),
                     (("daily", "10:00", "x"), {"start": "2026-12-01", "end": "2026-11-30"}),
                     (("daily", "10:00", "x"), {"end": "2026-11-15"})):
        _refused(400, d.add_rule, ali, *args, **kw)
    rid = d.add_rule(ali, "weekdays", "8:05", "Sabah   kontrolü\nnotu", deadline="true", shared=False, weekdays="5, 1,3,1",
                     start="2026-11-17", end="2026-12-31")["added_rule"]
    clock.set("2026-11-18 08:30")                                           # a Wednesday: done, and put off until 08:40
    d.snooze(ali, rid, "2026-11-18")
    clock.set("2026-11-20 08:30")                                           # a Friday: done
    d.rule_done(ali, rid, "2026-11-20")
    assert "yalnızca bugünün" in _refused(400, d.snooze, ali, rid, "2026-11-18")
    store.close()
    d, store = _desk(tmp_path / "tto.db")                                    # the dashboard started again: all of it is there
    r = d.agenda(ali)["rules"][0]
    assert (r["id"], r["repeat"], r["weekdays"], r["repeat_text"], r["time"], r["text"], r["deadline"], r["shared"], r["start"],
            r["end"]) == (rid, "weekdays", [1, 3, 5], "Pzt, Çar, Cum", "08:05", "Sabah kontrolü notu", True, False, "2026-11-17",
                          "2026-12-31")
    assert [(it["day"], it["done"]) for it in d.agenda(ali)["items"]] == [("2026-11-18", False), ("2026-11-20", True)]
    assert d.store.agenda_snoozes(ali, "2026-11-18") == {(rid, "2026-11-18"): "2026-11-18 08:40:00"}
    clock.set("2026-11-18 08:35")
    assert d.state(ali)["alarms"] == [] and d.state(ali)["next"] == 300                 # still put off after the restart
    # the most recurring items a user may add, and the agenda's pace (items and recurring items together)
    monkeypatch.setattr(dk, "RULES_MAX", 2)
    d.add_rule(ali, "daily", "10:00", "ikinci")
    assert "en fazla 2" in _refused(400, d.add_rule, ali, "daily", "11:00", "üçüncü")
    monkeypatch.setattr(dk, "RULES_MAX", 100)
    for i in range(dk.PACE["agenda"][0] - 1):
        d.add(ali, "2026-11-19", None, "iş %d" % i)
    _refused(429, d.add_rule, ali, "daily", "12:00", "bir fazla")
    _refused(429, d.edit_rule, ali, rid, "daily", "12:00", "bir fazla")
    store.close()


def test_an_earlier_database_gets_the_recurring_items_tables_and_keeps_its_rows(tmp_path, clock):
    """A database of the version before the recurring items (an update): opened, it gets their tables - every row of
    every table it had stays."""
    path = tmp_path / "tto.db"
    d, store = _desk(path)
    ali = _user(d, "Ali Veli")
    d.add(ali, "2026-11-16", "10:00", "eski iş", deadline=True)
    d.say(ali, "eski mesaj")
    d.report(ali, "idea", "eski öneri")
    store.close()
    new = ("agenda_rules", "agenda_rule_days", "agenda_snoozes")
    con = sqlite3.connect(str(path))
    for table in new:
        con.execute("DROP TABLE %s" % table)
    con.commit()

    def rows():
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in names}

    before = rows()
    assert not set(new) & set(before) and before["agenda"] == before["chat"] == before["feedback"] == 1
    con.close()
    d, store = _desk(path)
    con = sqlite3.connect(str(path))
    try:
        assert rows() == dict(before, **{t: 0 for t in new})
    finally:
        con.close()
    assert d.agenda(ali)["items"][0]["text"] == "eski iş"
    assert d.add_rule(ali, "daily", "12:00", "yeni")["added_rule"]
    store.close()


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


def test_business_days_are_the_dashboard_s_own_calendar(module_service):
    """"Her iş günü" and "Ayın son iş günü" skip the TRY holidays of the dashboard's calendar (Ayarlar → Tatiller: the
    list the workbook's WORKDAY reads) - and follow a change of it at once."""
    svc = module_service
    desk = svc.desk
    assert "2026-10-29" in desk.holidays()                                 # Cumhuriyet Bayramı, on the workbook's list
    user = svc.login("Tatil Deneme")["user"]
    items = svc.holidays()["tr"]
    every_workday = {"kind": "workdays", "weekdays": None, "start_day": None, "end_day": None}
    before = desk.counters()["agenda"]
    try:
        svc.set_holidays(user, items + [{"date": "20.11.2026", "name": "Deneme tatili"}])
        assert "2026-11-20" in desk.holidays() and desk.counters()["agenda"] > before         # read again, the pages told
        assert not dk.scheduled(every_workday, dt.date(2026, 11, 20), desk.holidays())
    finally:
        svc.set_holidays(user, items)
    assert "2026-11-20" not in desk.holidays() and dk.scheduled(every_workday, dt.date(2026, 11, 20), desk.holidays())


# ---------------------------------------------------------------------- over HTTP
@pytest.fixture(scope="module")
def client(module_service):
    with TestClient(create_app(module_service)) as c:
        yield c


def test_every_call_needs_a_session(client):
    for method, path in (("GET", "/api/desk"), ("GET", "/api/feedback"), ("POST", "/api/feedback"), ("POST", "/api/feedback/1"),
                         ("GET", "/api/social"), ("POST", "/api/social"), ("DELETE", "/api/social/1"), ("GET", "/api/agenda"),
                         ("POST", "/api/agenda"), ("POST", "/api/agenda/1"), ("DELETE", "/api/agenda/1"),
                         ("POST", "/api/agenda/rules"), ("POST", "/api/agenda/rules/1"), ("DELETE", "/api/agenda/rules/1"),
                         ("POST", "/api/agenda/rules/1/done"), ("POST", "/api/agenda/rules/1/snooze"),
                         ("POST", "/api/agenda/rules/1/pause")):
        res = client.request(method, path, headers=ANON, json={} if method == "POST" else None)
        assert res.status_code == 401, (method, path)
    for path in ("/static/js/desk.js", "/static/js/pages/social.js", "/static/js/pages/agenda.js", "/static/js/agendaalarms.js"):
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


def test_recurring_items_over_http(client, module_service):
    u, a = auth(module_service, "Http Trader"), auth(module_service, "Http Yönetici", admin=True)
    other = auth(module_service, "Üçüncü Kişi")
    body = {"repeat": "daily", "time": "23:59", "text": "Gün sonu kontrolü", "deadline": True}
    # a change sent from another site's page is turned away before anything is read
    assert client.post("/api/agenda/rules", json=body, headers=dict(u, Origin="http://kotu.example")).status_code == 403
    rid = client.post("/api/agenda/rules", json=body, headers=u).json()["added_rule"]
    today = _day()
    got = client.get("/api/agenda", headers=other).json()
    rule = next(r for r in got["rules"] if r["id"] == rid)
    assert (rule["repeat_text"], rule["time"], rule["deadline"], rule["shared"], rule["by"], rule["can_edit"]) == (
        "Her gün", "23:59", True, True, "Http Trader", False)
    assert any(it.get("rule") == rid and it["day"] == today and not it["done"] for it in got["items"])
    assert "r%d@%s" % (rid, today) in [x["id"] for x in client.get("/api/desk", headers=other).json()["agenda"]]
    # "Ertele 10 dk" (for oneself), "Bugün tamam" (by another trader: that day only)
    assert client.post("/api/agenda/rules/%d/snooze" % rid, json={"day": today}, headers=other).json()["snoozed"]
    done = client.post("/api/agenda/rules/%d/done" % rid, json={"day": today}, headers=other).json()
    assert next(it for it in done["items"] if it.get("rule") == rid)["done_by"] == "Üçüncü Kişi"
    assert client.post("/api/agenda/rules/%d/done" % rid, json={"day": "yarın"}, headers=other).status_code == 400
    # changed, paused and deleted by whoever added it or an administrator only
    assert client.post("/api/agenda/rules/%d" % rid, json=dict(body, time="23:58"), headers=other).status_code == 403
    edited = client.post("/api/agenda/rules/%d" % rid, json=dict(body, repeat="weekdays", weekdays=[1, 2, 3, 4, 5, 6, 7]),
                         headers=u).json()
    assert next(r for r in edited["rules"] if r["id"] == rid)["weekdays"] == [1, 2, 3, 4, 5, 6, 7]
    assert client.post("/api/agenda/rules/%d/pause" % rid, json={"paused": True}, headers=other).status_code == 403
    paused = client.post("/api/agenda/rules/%d/pause" % rid, json={"paused": True}, headers=a).json()
    assert next(r for r in paused["rules"] if r["id"] == rid)["paused"]
    assert client.post("/api/agenda/rules/%d/sil" % rid, json={}, headers=u).status_code == 404
    assert client.post("/api/agenda/rules", json=dict(body, time=None), headers=u).status_code == 400
    assert client.delete("/api/agenda/rules/%d" % rid, headers=other).status_code == 403
    assert rid not in [r["id"] for r in client.delete("/api/agenda/rules/%d" % rid, headers=u).json()["rules"]]
    assert client.post("/api/agenda/rules/%d/done" % rid, json={"day": today}, headers=u).status_code == 404
