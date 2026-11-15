"""The desk's own corner, apart from the market: reports to the administrators (a bug, an idea), the traders' chat
(Sosyal) and the agenda (Ajanda).

A change here makes no new generation - the pages' tables are not read again for a chat line: the live stream carries
the corner's own counters (``Desk.counters``) and a page asks for what changed.  What a user types is kept and sent back
as plain text; every call needs a signed-in user, the list of reports and their "dealt with" an administrator.
"""
from __future__ import annotations

import collections
import datetime as _dt
import re
import threading
from time import monotonic
from typing import Any, Deque, Dict, Optional, Tuple

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

# control characters (a tab and a line end stay) and the ones that turn the direction of the text around
_HIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")
_PAGE_ID = re.compile(r"[A-Za-z0-9_.-]{1,60}")
_TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


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


class Desk(object):
    def __init__(self, svc):
        self.svc = svc
        self.store = svc.store
        self._counting = threading.Lock()
        self._writing = threading.Lock()          # the pace check and the row it lets in, one request at a time
        self._counters = {"chat": 0, "feedback": 0, "agenda": 0}
        self._written: Dict[Tuple[str, str], Deque[float]] = {}     # (part, user) -> when they wrote lately

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
        deadlines not met - and, for an administrator, how many reports are open."""
        user = self.svc.require_user(user)
        seen = _maybe_number(seen)
        out: Dict[str, Any] = {
            "chat": {"last": self.store.chat_last(), "unread": self.store.chat_unread(user, seen) if seen is not None else 0},
            "agenda": [self._due(r) for r in self.store.agenda_due(user, *self._today_tomorrow())]}
        if self.is_admin(user):
            out["feedback"] = self.store.feedback_open()
        return out

    @staticmethod
    def _today_tomorrow():
        today = _dt.date.today()
        return today.isoformat(), (today + _dt.timedelta(days=1)).isoformat()

    @staticmethod
    def _due(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": r["id"], "day": r["day"], "time": r["time"], "text": r["text"], "deadline": bool(r["deadline"]),
                "shared": r["owner"] is None}

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
        every deadline not met however old - by day and time."""
        user = self.svc.require_user(user)
        today = _dt.date.today()
        names = self._names()
        admin = self.is_admin(user)
        items = []
        for r in self.store.agenda(user, (today - _dt.timedelta(days=AGENDA_PAST_DAYS)).isoformat(), AGENDA_LIMIT, AGENDA_LATE):
            items.append({"id": r["id"], "day": r["day"], "time": r["time"], "text": r["text"], "deadline": bool(r["deadline"]),
                          "shared": r["owner"] is None, "by": names.get(r["created_by"], r["created_by"]), "at": r["created_at"],
                          "done": r["done_at"] is not None, "done_by": names.get(r["done_by"], r["done_by"]) if r["done_by"] else None,
                          "done_at": r["done_at"], "can_delete": r["owner"] is not None or r["created_by"] == user or admin})
        return {"items": items, "today": today.isoformat(), "past_days": AGENDA_PAST_DAYS}

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
        if day < (_dt.date.today() - _dt.timedelta(days=AGENDA_PAST_DAYS)).isoformat():
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
