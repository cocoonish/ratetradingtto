"""The desk's own corner, apart from the market: reports to the administrators (a bug, an idea), the traders' chat
(Sosyal) and the agenda (Ajanda).

A change here makes no new generation - the pages' tables are not read again for a chat line: the live stream carries
the corner's own counters (``Desk.counters``) and a page asks for what changed.  What a user types is kept and sent back
as plain text; every call needs a signed-in user, the list of reports and their "dealt with" an administrator.

An agenda item may repeat (Tekrarlayan işler): every day, every business day of the desk's calendar (the TRY holidays
of Ayarlar → Tatiller), chosen days of the week or the month's last business day - at a time, from a first day to a
last one if given.  The rule is kept once; each day it falls on is its own: done on that day by whom and when, and
each user's "Ertele" of that day's alarm.  What is to be told of them now - a deadline 15 minutes before its time,
each day at its time (late when the dashboard was not open then), again when a snooze is over - is worked out here
(``alarms`` of :meth:`Desk.state`) with the moment that changes next; the pages show it once per browser.
"""
from __future__ import annotations

import collections
import datetime as _dt
import math
import re
import threading
from time import monotonic
from typing import Any, Deque, Dict, List, Optional, Tuple

from .service import ServiceError

#: what a report is about
KINDS = {"bug": "Hata", "idea": "Öneri"}
#: the longest report, chat message and agenda item (characters); the most lines of a report and of a message
REPORT_MAX, REPORT_LINES = 2000, 60
CHAT_MAX, CHAT_LINES = 1000, 30
AGENDA_MAX = 300
#: at most this many of each in so many seconds per user, counted as they are written (taking one back does not give
#: its place back): more is turned away (a stuck key, a script)
PACE = {"feedback": (10, 600), "chat": (20, 60), "agenda": (60, 600)}
#: the chat's messages at a time (the latest; earlier ones on request) and the most a page reads again
CHAT_PAGE = 200
CHAT_SINCE = 2000
#: how far back the agenda's page goes - and the earliest day a new item may have (a deadline not met stays, however
#: old); the most items of the page from that day on, and of the deadlines before it
AGENDA_PAST_DAYS = 30
AGENDA_LIMIT = 1000
AGENDA_LATE = 200
#: the reports dealt with that an administrator sees under the open ones
REPORTS_DONE = 100
#: how an agenda item repeats (key: what the page shows); an item of a single day is the agenda's own table
REPEATS = {"daily": "Her gün", "workdays": "Her iş günü", "weekdays": "Seçili günler", "monthend": "Ayın son iş günü"}
#: the days of the week of "Seçili günler", Monday first (ISO 1-7)
WEEKDAYS = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")
#: the most recurring items one user may have added (the desk's and their own)
RULES_MAX = 100
#: a recurring deadline is told this many minutes before its time; "Ertele" puts an alarm off this many minutes; an
#: alarm first told this many minutes or more after its time says it is late (the dashboard was not open then)
SOON_MINUTES = 15
SNOOZE_MINUTES = 10
ON_TIME_MINUTES = 2

# control characters (a tab and a line end stay) and the ones that turn the direction of the text around
_HIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")
_PAGE_ID = re.compile(r"[A-Za-z0-9_.-]{1,60}")
_TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
_ONE_DAY = _dt.timedelta(days=1)


def _now() -> _dt.datetime:
    """The desk's clock (the tests set it)."""
    return _dt.datetime.now()


def _minute(moment: _dt.datetime) -> str:
    """"2026-11-16 10:05" of a moment: how a recurring item's ``since`` is kept and compared with its days' times."""
    return moment.strftime("%Y-%m-%d %H:%M")


def _text(value: Any, longest: int, what: str, lines: int = 1) -> str:
    """A user's text as it is kept: hidden characters out, one line (``lines`` 1: blanks collapsed) or at most
    ``lines`` lines; not empty, at most ``longest`` characters."""
    s = _HIDDEN.sub("", str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n"))
    if lines == 1:
        s = " ".join(s.split())
    else:
        s = "\n".join(row.rstrip() for row in s.split("\n")).strip()
        if s.count("\n") >= lines:
            raise ServiceError("%s en fazla %d satır olabilir" % (what, lines))
    if not s:
        raise ServiceError("%s boş olamaz" % what)
    if len(s) > longest:
        raise ServiceError("%s en fazla %d karakter olabilir" % (what, longest))
    return s


def _number(value: Any, what: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ServiceError("%s belli değil" % what)


def _maybe_number(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _yes(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "evet", "yes", "on")
    return bool(value)


def _day(value: Any) -> str:
    try:
        day = _dt.date.fromisoformat(str(value or "").strip())
    except ValueError:
        raise ServiceError("tarih YYYY-AA-GG biçiminde olmalı")
    if not 2000 <= day.year <= 2099:
        raise ServiceError("tarih 2000 ile 2099 arasında olmalı")
    return day.isoformat()


def _time(value: Any) -> Optional[str]:
    s = str(value or "").strip()
    if not s:
        return None
    m = _TIME.fullmatch(s)
    if m is None:
        raise ServiceError("saat SS:DD biçiminde olmalı")
    return "%02d:%s" % (int(m.group(1)), m.group(2))


def _weekdays(value: Any) -> str:
    """The days of "Seçili günler" as kept: "1,3,5" (Monday 1 ... Sunday 7) of a list (or a text) of them."""
    if isinstance(value, str):
        value = [x for x in re.split(r"[,;\s]+", value) if x]
    if not isinstance(value, (list, tuple)):
        raise ServiceError("seçili günler bir liste olmalı (1 = Pzt … 7 = Paz)")
    days = set()
    for v in value:
        try:
            n = int(v)
        except (TypeError, ValueError):
            n = 0
        if not 1 <= n <= 7 or isinstance(v, bool):
            raise ServiceError("gün 1 (Pzt) ile 7 (Paz) arasında olmalı")
        days.add(n)
    if not days:
        raise ServiceError("en az bir gün seçin")
    return ",".join(str(n) for n in sorted(days))


def workday(day: _dt.date, shut: frozenset) -> bool:
    """A business day of the desk: a week day that is not one of its TRY holidays (``shut``: ISO days)."""
    return day.weekday() < 5 and day.isoformat() not in shut


def month_end(day: _dt.date, shut: frozenset) -> Optional[_dt.date]:
    """The last business day of ``day``'s month (``None``: a month without one)."""
    d = (day.replace(day=28) + _dt.timedelta(days=4)).replace(day=1) - _ONE_DAY
    while d.month == day.month:
        if workday(d, shut):
            return d
        d -= _ONE_DAY
    return None


def scheduled(rule: Dict[str, Any], day: _dt.date, shut: frozenset) -> bool:
    """Whether a recurring item falls on ``day`` by its rule: its kind, its days of the week, its first and last day
    (paused or not, and from when it counts, are the caller's)."""
    iso = day.isoformat()
    if (rule["start_day"] and iso < rule["start_day"]) or (rule["end_day"] and iso > rule["end_day"]):
        return False
    kind = rule["kind"]
    if kind == "daily":
        return True
    if kind == "workdays":
        return workday(day, shut)
    if kind == "weekdays":
        return str(day.isoweekday()) in (rule["weekdays"] or "").split(",")
    if kind == "monthend":
        return day == month_end(day, shut)
    return False


def describe(rule: Dict[str, Any]) -> str:
    """How a recurring item repeats, as the page says it: "Her iş günü", "Pzt, Çar, Cum", "Ayın son iş günü" …"""
    if rule["kind"] == "weekdays":
        days = [int(x) for x in (rule["weekdays"] or "").split(",") if x]
        return "Her gün" if len(days) == 7 else ", ".join(WEEKDAYS[d - 1] for d in days)
    return REPEATS.get(rule["kind"], rule["kind"])


class Desk(object):
    def __init__(self, svc):
        self.svc = svc
        self.store = svc.store
        self._counting = threading.Lock()
        self._writing = threading.Lock()          # the pace check and the row it lets in, one request at a time
        self._counters = {"chat": 0, "feedback": 0, "agenda": 0}
        self._written: Dict[Tuple[str, str], Deque[float]] = {}     # (part, user) -> when they wrote lately
        # the desk's TRY holidays as ISO days: (the day read, the days, how many times the list changed) - read as the
        # corner starts (the calculation thread is free then), again when the list changes and in the background on a
        # new day (``holidays``): the agenda never waits for the calculation thread
        self._shut: Tuple[str, frozenset, int] = (_now().date().isoformat(), self._read_holidays(), 0)
        self._refreshing: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ live
    def counters(self, admin: bool = True) -> Dict[str, int]:
        """How many times each part of the corner changed since the start (the live stream sends them along; the
        reports' counter only to an administrator - nobody else learns that one was sent or dealt with)."""
        with self._counting:
            out = dict(self._counters)
        if not admin:
            del out["feedback"]
        return out

    def _changed(self, part: str) -> None:
        with self._counting:
            self._counters[part] += 1
        self.svc.nudge()

    def _pace(self, part: str, user: str) -> None:
        """One more of ``part`` by ``user`` (under ``_writing``) - or 429 when ``PACE`` is used up."""
        n, seconds = PACE[part]
        now = monotonic()
        seen = self._written.setdefault((part, user), collections.deque())
        while seen and now - seen[0] >= seconds:
            seen.popleft()
        if len(seen) >= n:
            raise ServiceError("çok hızlı – biraz bekleyip tekrar deneyin", 429)
        seen.append(now)

    def _names(self) -> Dict[str, str]:
        return {u["name"]: u["display"] for u in self.store.users()}

    def is_admin(self, user: Optional[str]) -> bool:
        return bool(user) and (self.store.account(user) or {}).get("role") == "admin"

    def state(self, user: Optional[str], seen: Any = None) -> Dict[str, Any]:
        """What the top bar and the menu show: the chat's last message and how many the others wrote after ``seen``
        (the last one this browser showed; none: nothing is new), the agenda's items due - today's, tomorrow's and the
        deadlines not met; of the recurring items today's days not done and their deadlines not met -, what of the
        recurring items is to be told now (``alarms``) and in how many seconds that changes (``next``; ``None``: not
        before something changes) - and, for an administrator, how many reports are open."""
        user = self.svc.require_user(user)
        seen = _maybe_number(seen)
        now = _now()
        today, tomorrow = now.date().isoformat(), (now.date() + _ONE_DAY).isoformat()
        days = self._occurring(self.store.agenda_rules(user), now)
        alarms, wait = self._alarms(days, self.store.agenda_snoozes(user, today), now)
        out: Dict[str, Any] = {
            "chat": {"last": self.store.chat_last(), "unread": self.store.chat_unread(user, seen) if seen is not None else 0},
            "agenda": [self._due(r) for r in self.store.agenda_due(user, today, tomorrow)]
            + [self._due_day(o) for o in days if not o["done"] and o["day"] <= today],
            "alarms": alarms, "next": wait}
        if self.is_admin(user):
            out["feedback"] = self.store.feedback_open()
        return out

    @staticmethod
    def _due(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": r["id"], "day": r["day"], "time": r["time"], "text": r["text"], "deadline": bool(r["deadline"]),
                "shared": r["owner"] is None}

    @staticmethod
    def _due_day(o: Dict[str, Any]) -> Dict[str, Any]:
        """A recurring item's day as the menu's badge counts it (``rule``: its rule; ``id``: "r<rule>@<day>")."""
        r = o["rule"]
        return {"id": "r%d@%s" % (r["id"], o["day"]), "rule": r["id"], "day": o["day"], "time": r["time"], "text": r["text"],
                "deadline": bool(r["deadline"]), "shared": r["owner"] is None}

    # ------------------------------------------------------------------ reports to the administrators
    def report(self, user: Optional[str], kind: Any, text: Any, page: Any = None, title: Any = None) -> Dict[str, Any]:
        """A bug or an idea for the administrators, with the page it was written on."""
        user = self.svc.require_user(user)
        kind = str(kind or "")
        if kind not in KINDS:
            raise ServiceError("tür hata ya da öneri olmalı")
        text = _text(text, REPORT_MAX, "bildirim", REPORT_LINES)
        page = str(page or "")
        page = page if _PAGE_ID.fullmatch(page) else None
        title = " ".join(_HIDDEN.sub("", str(title or "")).split())[:120] or None
        with self._writing:
            self._pace("feedback", user)
            fid = self.store.add_feedback(kind, text, page, title, user)
        self._changed("feedback")
        return {"id": fid}

    def reports(self, user: Optional[str]) -> Dict[str, Any]:
        """The reports, for an administrator: the open ones and the latest dealt with (by whom, when), newest first."""
        self.svc.require_admin(user)
        names = self._names()

        def show(r: Dict[str, Any]) -> Dict[str, Any]:
            return {"id": r["id"], "kind": r["kind"], "text": r["text"], "page": r["page"], "title": r["page_title"],
                    "by": names.get(r["created_by"], r["created_by"]), "at": r["created_at"],
                    "done_by": names.get(r["done_by"], r["done_by"]) if r["done_by"] else None, "done_at": r["done_at"]}

        return {"open": [show(r) for r in self.store.feedback(done=False)], "count": self.store.feedback_open(),
                "done": [show(r) for r in self.store.feedback(done=True, limit=REPORTS_DONE)]}

    def report_done(self, user: Optional[str], fid: Any, done: Any = True) -> Dict[str, Any]:
        """An administrator dealt with a report: it leaves the badge (``done`` false: it is open again)."""
        me = self.svc.require_admin(user)
        fid = _number(fid, "bildirim")
        if self.store.feedback_item(fid) is None:
            raise ServiceError("bildirim bulunamadı", 404)
        if self.store.set_feedback_done(fid, me if _yes(done) else None):
            self._changed("feedback")
        return self.reports(me)

    # ------------------------------------------------------------------ the chat (Sosyal)
    def _message(self, r: Dict[str, Any], user: str, names: Dict[str, str]) -> Dict[str, Any]:
        return {"id": r["id"], "user": r["user"], "name": names.get(r["user"], r["user"]), "text": r["text"],
                "at": r["created_at"], "mine": r["user"] == user}

    def chat(self, user: Optional[str], before: Any = None, since: Any = None) -> Dict[str, Any]:
        """The chat, oldest first: the latest messages (``before``: the ones before that message; ``since``: every one
        from that message on - what a page has, read again), and whether there are earlier ones."""
        user = self.svc.require_user(user)
        since = _maybe_number(since)
        if since is not None:
            rows, more = self.store.chat(since=since, limit=CHAT_SINCE)
        else:
            rows, more = self.store.chat(before=_maybe_number(before), limit=CHAT_PAGE)
        names = self._names()
        return {"messages": [self._message(r, user, names) for r in rows], "more": more, "last": self.store.chat_last()}

    def say(self, user: Optional[str], text: Any) -> Dict[str, Any]:
        """A message to everybody signed in."""
        user = self.svc.require_user(user)
        text = _text(text, CHAT_MAX, "mesaj", CHAT_LINES)
        with self._writing:
            self._pace("chat", user)
            row = self.store.add_chat(user, text)
        self._changed("chat")
        return self._message(row, user, self._names())

    def unsay(self, user: Optional[str], mid: Any) -> Dict[str, Any]:
        """Take one's own message back (for everybody)."""
        user = self.svc.require_user(user)
        mid = _number(mid, "mesaj")
        row = self.store.chat_item(mid)
        if row is None:
            raise ServiceError("mesaj bulunamadı", 404)
        if row["user"] != user:
            raise ServiceError("yalnızca kendi mesajınızı silebilirsiniz", 403)
        self.store.delete_chat(mid, user)
        self._changed("chat")
        return {"deleted": mid}

    # ------------------------------------------------------------------ the agenda (Ajanda)
    def agenda(self, user: Optional[str]) -> Dict[str, Any]:
        """The agenda as the user sees it: the desk's items and their own from ``AGENDA_PAST_DAYS`` days ago on, and
        every deadline not met however old - by day and time; among them the recurring items' days of today and their
        deadlines not met of the days before (``rule``: its rule).  And the recurring items themselves (``rules``):
        how they repeat, the next time each comes, who may change them."""
        user = self.svc.require_user(user)
        now = _now()
        today = now.date()
        names = self._names()
        admin = self.is_admin(user)
        items = []
        for r in self.store.agenda(user, (today - _dt.timedelta(days=AGENDA_PAST_DAYS)).isoformat(), AGENDA_LIMIT, AGENDA_LATE):
            items.append({"id": r["id"], "day": r["day"], "time": r["time"], "text": r["text"], "deadline": bool(r["deadline"]),
                          "shared": r["owner"] is None, "by": names.get(r["created_by"], r["created_by"]), "at": r["created_at"],
                          "done": r["done_at"] is not None, "done_by": names.get(r["done_by"], r["done_by"]) if r["done_by"] else None,
                          "done_at": r["done_at"], "can_delete": r["owner"] is not None or r["created_by"] == user or admin})
        rules = self.store.agenda_rules(user)
        days = self._occurring(rules, now)
        for o in days:
            r, done = o["rule"], o["done"]
            # today's (done or not); a day before only while its deadline is not met; tomorrow's are the alarms' only
            if o["day"] > today.isoformat() or (o["day"] < today.isoformat() and done):
                continue
            items.append(dict(self._due_day(o), by=names.get(r["created_by"], r["created_by"]), at=r["created_at"],
                              done=done is not None, done_by=names.get(done["done_by"], done["done_by"]) if done else None,
                              done_at=done["done_at"] if done else None, can_delete=False, repeat=describe(r)))
        # by day, then time (an item without a time first in its day), an item of the day before a recurring one
        items.sort(key=lambda it: (it["day"], it["time"] is not None, it["time"] or "", "rule" in it,
                                   it["rule"] if "rule" in it else it["id"]))
        shut = self.holidays() if rules else frozenset()
        done_days = {(o["rule"]["id"], o["day"]) for o in days if o["done"]}
        return {"items": items, "today": today.isoformat(), "past_days": AGENDA_PAST_DAYS,
                "rules": [self._rule(r, names, user, admin, now, shut, done_days) for r in rules], "rules_max": RULES_MAX}

    def _visible(self, user: str, aid: Any) -> Dict[str, Any]:
        """An item the user may see (another user's own item is not there for them)."""
        row = self.store.agenda_item(_number(aid, "iş"))
        if row is None or row["owner"] not in (None, user):
            raise ServiceError("iş bulunamadı", 404)
        return row

    def add(self, user: Optional[str], day: Any, time: Any = None, text: Any = "", deadline: Any = False,
            shared: Any = True) -> Dict[str, Any]:
        """Something not to forget on a day (at a time), maybe a deadline: the desk's (``shared``) or one's own - on a day
        from ``AGENDA_PAST_DAYS`` days ago on."""
        user = self.svc.require_user(user)
        day, time = _day(day), _time(time)
        if day < (_now().date() - _dt.timedelta(days=AGENDA_PAST_DAYS)).isoformat():
            raise ServiceError("en fazla %d gün öncesine iş eklenebilir" % AGENDA_PAST_DAYS)
        text = _text(text, AGENDA_MAX, "iş")
        with self._writing:
            self._pace("agenda", user)
            aid = self.store.add_agenda(None if _yes(shared) else user, day, time, text, _yes(deadline), user)
        self._changed("agenda")
        return dict(self.agenda(user), added=aid)

    def mark(self, user: Optional[str], aid: Any, done: Any = True) -> Dict[str, Any]:
        """Done (``done`` false: not done after all) - the desk's items by anybody, one's own by oneself."""
        user = self.svc.require_user(user)
        row = self._visible(user, aid)
        self.store.set_agenda_done(row["id"], user if _yes(done) else None)
        self._changed("agenda")
        return self.agenda(user)

    def remove(self, user: Optional[str], aid: Any) -> Dict[str, Any]:
        """Delete an item: one's own; the desk's by whoever added it or an administrator."""
        user = self.svc.require_user(user)
        row = self._visible(user, aid)
        if row["owner"] is None and row["created_by"] != user and not self.is_admin(user):
            raise ServiceError("masanın işini yalnızca ekleyen ya da bir yönetici silebilir", 403)
        self.store.delete_agenda(row["id"])
        self._changed("agenda")
        return self.agenda(user)

    # ------------------------------------------------------------------ recurring items (Tekrarlayan işler)
    def _read_holidays(self) -> frozenset:
        """The desk's TRY holidays as the dashboard's calendar has them now (on the calculation thread: the caller waits
        for it)."""
        try:
            return frozenset(d.isoformat() for d in self.svc.holiday_dates(("TRY",)))
        except Exception:  # noqa: BLE001 - a workbook without the list: the weekends only
            return frozenset()

    def holidays(self) -> frozenset:
        """The TRY holidays of the dashboard's calendar (Ayarlar → Tatiller; the list the workbook's WORKDAY reads), as
        ISO days: the days "Her iş günü" and "Ayın son iş günü" skip besides the weekend.  Kept: read as the corner
        starts and again whenever the list changes (:meth:`holidays_changed`); on a new day read once more in the
        background - the agenda (and the shell's state) does not wait for a busy calculation thread."""
        today = _now().date().isoformat()
        with self._counting:
            day, days, version = self._shut
            if day == today or (self._refreshing is not None and self._refreshing.is_alive()):
                return days
            self._refreshing = threading.Thread(target=self._refresh, args=(today, version), name="tto-desk-holidays",
                                                daemon=True)
            self._refreshing.start()
        return days

    def _refresh(self, today: str, version: int) -> None:
        days = self._read_holidays()
        with self._counting:
            if self._shut[2] != version:                # the list changed meanwhile: that reading stands
                return
            changed = days != self._shut[1]
            self._shut = (today, days, version)
        if changed:
            self._changed("agenda")

    def holidays_changed(self) -> None:
        """The TRY holidays changed (Service.set_holidays - on the calculation thread, where the list is read at once):
        the recurring items' days are worked out again and the open pages told."""
        days = self._read_holidays()
        with self._counting:
            self._shut = (_now().date().isoformat(), days, self._shut[2] + 1)
        self._changed("agenda")

    def _occurring(self, rules: List[Dict[str, Any]], now: _dt.datetime) -> List[Dict[str, Any]]:
        """The days of the recurring items (not paused) that concern the agenda now: today's and tomorrow's, and of a
        deadline the days of the last ``AGENDA_PAST_DAYS`` days - each ``{"rule", "day", "done": who and when, or
        None}``, by day and time.  A day counts from the rule's ``since`` on (when it was added, went on after a pause
        or got a new time, kind or deadline): what came before it was not missed.  A day done is there all the same."""
        live = [r for r in rules if not r["paused_at"]]
        if not live:
            return []
        today = now.date()
        first, last = today - _dt.timedelta(days=AGENDA_PAST_DAYS), today + _ONE_DAY
        shut = self.holidays()
        done = self.store.agenda_rule_days(first.isoformat(), last.isoformat())
        out = []
        for r in live:
            day = max(first if r["deadline"] else today, _dt.date.fromisoformat(r["since"][:10]))
            while day <= last:
                iso = day.isoformat()
                if scheduled(r, day, shut):
                    got = done.get((r["id"], iso))
                    if got is not None or "%s %s" % (iso, r["time"]) >= r["since"]:
                        out.append({"rule": r, "day": iso, "done": got})
                day += _ONE_DAY
        out.sort(key=lambda o: (o["day"], o["rule"]["time"], o["rule"]["id"]))
        return out

    @staticmethod
    def _alarms(days: List[Dict[str, Any]], snoozes: Dict[Tuple[int, str], str],
                now: _dt.datetime) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """What of the recurring items' days (not done; today's and tomorrow's) is to be told now, and in how many
        seconds that changes (``None``: not before something changes).  A day's moments: a deadline ``SOON_MINUTES``
        before its time, every day at its time, the end of the user's snooze; the latest moment passed is the one told
        (``key``: once per browser) - late, when told ``ON_TIME_MINUTES`` or more after the time; nothing while the
        snooze lasts.  A day of the days before is told no more (its deadline not met stays on the agenda)."""
        out: List[Dict[str, Any]] = []
        ahead: List[_dt.datetime] = []
        today = now.date().isoformat()
        for o in days:
            r = o["rule"]
            if o["done"] or o["day"] < today:
                continue
            at = _dt.datetime.fromisoformat("%s %s" % (o["day"], r["time"]))
            moments = ([("soon", at - _dt.timedelta(minutes=SOON_MINUTES))] if r["deadline"] else []) + [("due", at)]
            until = snoozes.get((r["id"], o["day"]))
            if until:
                moments.append(("z" + until[11:19].replace(":", ""), _dt.datetime.fromisoformat(until)))
            ahead.extend(m for _, m in moments if m > now)
            if until and moments[-1][1] > now:
                continue                                  # put off: quiet until then
            passed = [(m, i, stage) for i, (stage, m) in enumerate(moments) if m <= now]
            if not passed:
                continue
            _, _, stage = max(passed)
            what = "%s · %s" % (r["time"], r["text"])
            late = (now - at).total_seconds() >= ON_TIME_MINUTES * 60
            if now < at:                                  # before its time: 15 minutes before, or a snooze ended early
                left = int(math.ceil((at - now).total_seconds() / 60.0))
                text, kind = ("Deadline yaklaşıyor (%d dk): %s" if r["deadline"] else "Hatırlatma (%d dk sonra): %s") % (left, what), "warn"
            elif stage == "due":
                text = ("Deadline geçti: " if late else "Deadline geldi: ") if r["deadline"] else ("Gecikmiş: " if late else "Hatırlatma: ")
                text, kind = text + what, "err" if r["deadline"] else ("warn" if late else "")
            else:
                text, kind = ("Ertelenen deadline: " if r["deadline"] else "Ertelenen hatırlatma: ") + what, "err" if r["deadline"] else ""
            out.append({"key": "r%d@%s:%s" % (r["id"], o["day"], stage), "rule": r["id"], "day": o["day"], "time": r["time"],
                        "stage": "snooze" if stage.startswith("z") else stage, "late": stage == "due" and late, "text": text,
                        "kind": kind, "deadline": bool(r["deadline"]), "shared": r["owner"] is None, "repeat": describe(r)})
        wait = int(math.ceil((min(ahead) - now).total_seconds())) if ahead else None
        return out, wait

    def _rule(self, r: Dict[str, Any], names: Dict[str, str], user: str, admin: bool, now: _dt.datetime, shut: frozenset,
              done: set) -> Dict[str, Any]:
        """A recurring item as the page lists it."""
        return {"id": r["id"], "repeat": r["kind"], "repeat_text": describe(r),
                "weekdays": [int(x) for x in (r["weekdays"] or "").split(",") if x], "time": r["time"], "text": r["text"],
                "deadline": bool(r["deadline"]), "shared": r["owner"] is None, "start": r["start_day"], "end": r["end_day"],
                "paused": bool(r["paused_at"]), "paused_by": names.get(r["paused_by"], r["paused_by"]) if r["paused_by"] else None,
                "paused_at": r["paused_at"], "by": names.get(r["created_by"], r["created_by"]), "at": r["created_at"],
                "next": None if r["paused_at"] else self._next(r, now, shut, done), "can_edit": self._may_change(user, r, admin)}

    @staticmethod
    def _next(r: Dict[str, Any], now: _dt.datetime, shut: frozenset, done: set) -> Optional[Dict[str, str]]:
        """The next time a recurring item comes (a day done ahead of its time skipped); ``None``: never again."""
        day, stamp = max(now.date(), _dt.date.fromisoformat(r["start_day"] or "2000-01-01")), _minute(now)
        for _ in range(400):
            iso = day.isoformat()
            if r["end_day"] and iso > r["end_day"]:
                return None
            moment = "%s %s" % (iso, r["time"])
            if moment > stamp and moment >= r["since"] and (r["id"], iso) not in done and scheduled(r, day, shut):
                return {"day": iso, "time": r["time"]}
            day += _ONE_DAY
        return None

    @staticmethod
    def _may_change(user: str, r: Dict[str, Any], admin: bool) -> bool:
        """Change, pause or delete a recurring item: one's own; the desk's whoever added it or an administrator."""
        return r["owner"] is not None or r["created_by"] == user or admin

    def _rule_seen(self, user: str, rid: Any) -> Dict[str, Any]:
        """A recurring item the user may see (another user's own is not there for them)."""
        row = self.store.agenda_rule(_number(rid, "tekrarlayan iş"))
        if row is None or row["owner"] not in (None, user):
            raise ServiceError("tekrarlayan iş bulunamadı", 404)
        return row

    def _rule_mine(self, user: str, rid: Any, what: str) -> Dict[str, Any]:
        row = self._rule_seen(user, rid)
        if not self._may_change(user, row, self.is_admin(user)):
            raise ServiceError("masanın tekrarlayan işini yalnızca ekleyen ya da bir yönetici %s" % what, 403)
        return row

    @staticmethod
    def _schedule(repeat: Any, weekdays: Any, time: Any, start: Any, end: Any, today: str) -> Dict[str, Any]:
        """How an item repeats, checked: kind, days of the week ("Seçili günler"), time (a recurring item needs one: it
        is told at it), first and last day (either may be left out)."""
        kind = str(repeat or "").strip()
        if kind not in REPEATS:
            raise ServiceError("tekrar şunlardan biri olmalı: %s" % ", ".join(REPEATS.values()))
        time = _time(time)
        if time is None:
            raise ServiceError("tekrarlayan işin bir saati olmalı (o saatte uyarır)")
        start = _day(start) if start not in (None, "") else None
        end = _day(end) if end not in (None, "") else None
        if start and end and end < start:
            raise ServiceError("bitiş günü başlangıçtan önce olamaz")
        if end and end < today:
            raise ServiceError("bitiş günü geçmişte olamaz")
        return {"kind": kind, "weekdays": _weekdays(weekdays) if kind == "weekdays" else None, "time": time,
                "start_day": start, "end_day": end}

    def add_rule(self, user: Optional[str], repeat: Any, time: Any = None, text: Any = "", deadline: Any = False,
                 shared: Any = True, weekdays: Any = None, start: Any = None, end: Any = None) -> Dict[str, Any]:
        """An item that repeats (``repeat``: every day, every business day, chosen days of the week, the month's last
        business day) at a time: the desk's (``shared``) or one's own; from ``start`` to ``end`` when given.  Its days
        count from now on."""
        user = self.svc.require_user(user)
        now = _now()
        rule = self._schedule(repeat, weekdays, time, start, end, now.date().isoformat())
        rule.update(text=_text(text, AGENDA_MAX, "iş"), deadline=1 if _yes(deadline) else 0, since=_minute(now))
        with self._writing:
            if self.store.agenda_rules_added(user) >= RULES_MAX:
                raise ServiceError("en fazla %d tekrarlayan iş eklenebilir – kullanılmayanları silin" % RULES_MAX)
            self._pace("agenda", user)
            rid = self.store.add_agenda_rule(None if _yes(shared) else user, rule, user)
        self._changed("agenda")
        return dict(self.agenda(user), added_rule=rid)

    def edit_rule(self, user: Optional[str], rid: Any, repeat: Any, time: Any = None, text: Any = "", deadline: Any = False,
                  weekdays: Any = None, start: Any = None, end: Any = None) -> Dict[str, Any]:
        """A recurring item changed - by its owner; the desk's by whoever added it or an administrator.  Who it is for
        stays.  A new time, kind or deadline counts from now on: the days before are not missed under it."""
        user = self.svc.require_user(user)
        row = self._rule_mine(user, rid, "değiştirebilir")
        now = _now()
        rule = self._schedule(repeat, weekdays, time, start, end, now.date().isoformat())
        rule.update(text=_text(text, AGENDA_MAX, "iş"), deadline=1 if _yes(deadline) else 0)
        if any(rule[k] != row[k] for k in ("kind", "weekdays", "time", "deadline")):
            rule["since"] = _minute(now)
        with self._writing:
            self._pace("agenda", user)
            self.store.update_agenda_rule(row["id"], rule, user)
        self._changed("agenda")
        return self.agenda(user)

    def pause_rule(self, user: Optional[str], rid: Any, paused: Any = True) -> Dict[str, Any]:
        """Paused, a recurring item has no days and tells nothing (its days done stay); going on, it counts from now -
        the days it was paused are not missed."""
        user = self.svc.require_user(user)
        row = self._rule_mine(user, rid, "duraklatabilir")
        now = _now()
        if _yes(paused):
            changed = not row["paused_at"]
            if changed:
                self.store.update_agenda_rule(row["id"], {"paused_by": user, "paused_at": now.strftime("%Y-%m-%d %H:%M:%S")}, user)
        else:
            changed = bool(row["paused_at"])
            if changed:
                self.store.update_agenda_rule(row["id"], {"paused_by": None, "paused_at": None, "since": _minute(now)}, user)
        if changed:
            self._changed("agenda")
        return self.agenda(user)

    def remove_rule(self, user: Optional[str], rid: Any) -> Dict[str, Any]:
        """Delete a recurring item with its days done: one's own; the desk's by whoever added it or an administrator."""
        user = self.svc.require_user(user)
        row = self._rule_mine(user, rid, "silebilir")
        self.store.delete_agenda_rule(row["id"])
        self._changed("agenda")
        return self.agenda(user)

    def _its_day(self, row: Dict[str, Any], day: Any, now: _dt.datetime) -> str:
        """A day of a recurring item that can be answered now: today's, or one of the last ``AGENDA_PAST_DAYS`` days
        (a deadline not met) - a day it falls on, counted (not before its ``since``), the item not paused."""
        day = _day(day)
        today = now.date()
        if not (today - _dt.timedelta(days=AGENDA_PAST_DAYS)).isoformat() <= day <= today.isoformat():
            raise ServiceError("yalnızca bugünün ya da son %d günün tekrarı işaretlenebilir" % AGENDA_PAST_DAYS)
        if row["paused_at"]:
            raise ServiceError("bu tekrarlayan iş duraklatılmış")
        if not scheduled(row, _dt.date.fromisoformat(day), self.holidays()) or "%s %s" % (day, row["time"]) < row["since"]:
            raise ServiceError("bu tekrarlayan iş o gün yok")
        return day

    def rule_done(self, user: Optional[str], rid: Any, day: Any, done: Any = True) -> Dict[str, Any]:
        """A recurring item done on a day ("Bugün tamam") - that day only; its other days stay as they are.  The desk's
        by anybody, one's own by oneself; who and when are kept.  ``done`` false: not done after all."""
        user = self.svc.require_user(user)
        row = self._rule_seen(user, rid)
        if _yes(done):
            changed = self.store.set_agenda_rule_day(row["id"], self._its_day(row, day, _now()), user)
        else:
            changed = self.store.set_agenda_rule_day(row["id"], _day(day), None)
        if changed:
            self._changed("agenda")
        return self.agenda(user)

    def snooze(self, user: Optional[str], rid: Any, day: Any) -> Dict[str, Any]:
        """"Ertele 10 dk": the alarm of a recurring item's day (today's) put off ``SNOOZE_MINUTES`` minutes for this user
        only - the others are told as before."""
        user = self.svc.require_user(user)
        row = self._rule_seen(user, rid)
        now = _now()
        day = self._its_day(row, day, now)
        if day != now.date().isoformat():
            raise ServiceError("yalnızca bugünün hatırlatması ertelenebilir")
        until = (now + _dt.timedelta(minutes=SNOOZE_MINUTES)).replace(microsecond=0)
        self.store.snooze_agenda_rule(row["id"], day, user, until.strftime("%Y-%m-%d %H:%M:%S"),
                                      (now.date() - _ONE_DAY).isoformat())
        self._changed("agenda")
        return dict(self.agenda(user), snoozed=until.strftime("%H:%M"))
