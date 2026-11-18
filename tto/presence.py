"""Who is at the desk (18.11.2026, the desk: "kim online, kim en son ne zaman girmiş vs onu görebilmemiz lazım"): who
is online, away or offline, when each user was last seen and when they last signed in - the top bar's "● 3 çevrimiçi"
and its list (everybody's: a small desk), the administrators' account list.

A browser - one session: its tabs share the cookie and one live stream - is *connected* while it holds the live stream
(``/api/events``) or made a request in the last ``CONNECTED`` seconds.  A user is

* **online** while a browser of theirs is connected and somebody pressed a key, clicked, scrolled or moved the mouse in
  one of its tabs (a window of its own too) in the last ``AWAY`` seconds - the page says so at most once a minute
  (:meth:`Presence.active`, ``POST /api/presence``), so the first move after a while is heard at once;
* **away** while connected without that;
* **offline** otherwise.  Signing out takes that browser out at once (its stream may still be closing); another
  browser of theirs may keep them connected.

*Last seen* is the last moment a browser of theirs was connected - its last request, or now while it holds the live
stream - written to ``users.last_seen`` at most once every ``SAVE`` seconds per user (at once on a sign-out, and when
the dashboard stops): it survives a restart.  *Last login* is the last sign-in (``users.last_login``, written by
``Service.open_session``; the address beside it is for the administrators' account list only - never in this list).

The live stream carries :meth:`Presence.counters` - the online and away counts and a version that moves whenever
somebody's state changed: a page asks for the list (:meth:`Presence.listing`) only then.  What happens - a request, a
stream opened or closed, the page's word - only touches memory (the session gate tells every request on the event
loop); the states are worked out and the database written by a thread of its own, every ``TICK`` seconds and at once
after something that may move a state.
"""
from __future__ import annotations

import collections
import datetime as _dt
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import auth

#: a browser that made a request this recently (seconds) is connected without the live stream
CONNECTED = 120.0
#: connected, but no key, click, scroll or mouse move in any of its tabs for this long (seconds): away
AWAY = 15 * 60.0
#: "last seen" goes to the database at most this often per user (seconds)
SAVE = 60.0
#: how often the states are looked at when nothing happens (seconds): connected -> offline and online -> away by time
TICK = 5.0
#: a browser not connected for this long (seconds) is forgotten (it comes back as new: the page says how idle it is)
FORGET = 12 * 3600.0
#: sessions ended lately (signed out, a new password, an account closed) that a stream still closing must not bring back
ENDED_KEEP = 2000
#: the longest idle time a page may report (seconds)
IDLE_MAX = 7 * 86400.0

STATES = ("online", "away", "offline")


def stamp(wall: float) -> str:
    """"2026-11-18 10:15:03" of a moment (the database's stamps: the computer's local time)."""
    return _dt.datetime.fromtimestamp(wall).replace(microsecond=0).isoformat(sep=" ")


class _Browser(object):
    """One session as presence knows it: a browser (its tabs share the cookie), or a script with its token."""
    __slots__ = ("user", "since", "seen", "streams", "input")

    def __init__(self, user: str, now: float):
        self.user = user
        self.since = now                    # first heard of by this process (monotonic) - its input until it reports one
        self.seen = now                     # its last request (monotonic)
        self.streams = 0                    # live streams open
        self.input: Optional[float] = None  # the last key / click / scroll / mouse move its pages reported (monotonic)

    def connected(self, now: float) -> bool:
        return self.streams > 0 or now - self.seen < CONNECTED


class Presence(object):
    def __init__(self, store, on_change: Optional[Callable[[], None]] = None,
                 on_error: Optional[Callable[[BaseException], None]] = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        self.store = store
        self.on_change = on_change              # a state changed: the open pages are told (Service.nudge)
        self.on_error = on_error
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._browsers: Dict[str, _Browser] = {}                # token hash -> browser
        self._ended: "collections.OrderedDict[str, None]" = collections.OrderedDict()
        self._activity: Dict[str, float] = {}                   # user -> last moment connected (wall clock)
        self._saved: Dict[str, float] = {}                      # user -> the "last seen" written last (wall clock)
        self._saved_at: Dict[str, float] = {}                   # user -> when it was written (monotonic)
        self._urgent: set = set()                               # users whose "last seen" goes at the next look
        self._states: Dict[str, str] = {}                       # user -> state at the last look (connected users)
        self._counts: Tuple[int, int] = (0, 0)                  # (online, away) of the desk's users at the last look
        self.version = 0
        self.boot = int(wall())                                 # this process (a page that sees it change reports again)
        self._kick = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ what happens: memory only (the event loop too)
    def _browser(self, user: str, h: str, now: float) -> Optional[_Browser]:
        """The browser of the token hash ``h`` - new when unknown, ``None`` for a session ended lately.  Under the lock."""
        b = self._browsers.get(h)
        if b is None and h not in self._ended:
            b = self._browsers[h] = _Browser(user, now)
        return b

    def request(self, user: Optional[str], token: Optional[str]) -> None:
        """An authenticated request of ``user`` with the session ``token`` (the session gate tells every one)."""
        if not user or not token:
            return
        h = auth.token_hash(token)
        now = self._clock()
        with self._lock:
            b = self._browser(user, h, now)
            if b is None:
                return
            b.seen = now
            self._activity[user] = self._wall()
            quiet = user not in self._states                    # (offline until now: a state may move)
        if quiet:
            self._kick.set()

    def stream(self, user: Optional[str], token: Optional[str], delta: int) -> None:
        """A live stream of the session opened (+1) or closed (-1)."""
        if not user or not token:
            return
        h = auth.token_hash(token)
        now = self._clock()
        with self._lock:
            b = self._browsers.get(h) if delta < 0 else self._browser(user, h, now)
            if b is None:
                return
            b.streams = max(0, b.streams + delta)
            self._activity[user] = self._wall()
        self._kick.set()

    def active(self, user: Optional[str], token: Optional[str], idle: Any = 0) -> None:
        """The page's word: somebody typed, clicked, scrolled or moved the mouse in a tab of this browser ``idle``
        seconds ago (0: now)."""
        if not user or not token:
            return
        try:
            idle = float(idle or 0)
        except (TypeError, ValueError):
            idle = 0.0
        idle = min(max(idle, 0.0), IDLE_MAX) if idle == idle else 0.0
        h = auth.token_hash(token)
        now = self._clock()
        with self._lock:
            b = self._browser(user, h, now)
            if b is None:
                return
            at = now - idle
            if b.input is None or at > b.input:
                b.input = at
            moved = self._states.get(user) != ("online" if now - b.input < AWAY else "away")
        if moved:
            self._kick.set()

    def signed_in(self, user: str, token: str) -> None:
        """A new session (a sign-in): connected, and somebody is at it."""
        h = auth.token_hash(token)
        now = self._clock()
        with self._lock:
            self._ended.pop(h, None)
            b = self._browsers[h] = _Browser(user, now)
            b.input = now
            self._activity[user] = self._wall()
        self._kick.set()

    def signed_out(self, token: Optional[str]) -> None:
        """Signed out: that browser is not connected any more - at once; the user's "last seen" (now) is written at the
        next look."""
        if not token:
            return
        h = auth.token_hash(token)
        with self._lock:
            b = self._browsers.pop(h, None)
            self._end(h)
            if b is not None:
                self._activity[b.user] = self._wall()
                self._urgent.add(b.user)
        self._kick.set()

    def ended(self, user: str, keep: Optional[str] = None) -> None:
        """The user's sessions ended but ``keep`` (a token hash): a new password, an account closed."""
        with self._lock:
            for h in [h for h, b in self._browsers.items() if b.user == user and h != keep]:
                del self._browsers[h]
                self._end(h)
        self._kick.set()

    def _end(self, h: str) -> None:
        self._ended[h] = None
        while len(self._ended) > ENDED_KEEP:
            self._ended.popitem(last=False)

    # ------------------------------------------------------------------ the states
    def _evaluate(self, now: float) -> Dict[str, Dict[str, Any]]:
        """Every connected user -> {"state": online | away, "input": the last input (monotonic), "stream": bool}.
        Under the lock."""
        out: Dict[str, Dict[str, Any]] = {}
        for b in self._browsers.values():
            if not b.connected(now):
                continue
            last = b.input if b.input is not None else b.since
            cur = out.get(b.user)
            if cur is None:
                out[b.user] = {"input": last, "stream": b.streams > 0}
            else:
                cur["input"] = max(cur["input"], last)
                cur["stream"] = cur["stream"] or b.streams > 0
        for d in out.values():
            d["state"] = "online" if now - d["input"] < AWAY else "away"
        return out

    def tick(self) -> bool:
        """One look: the states now (a change moves the version and tells the open pages) and every "last seen" that is
        due written.  True when something changed."""
        desk = {r["name"] for r in self.store.desk_users()}
        now, wall = self._clock(), self._wall()
        with self._lock:
            for h in [h for h, b in self._browsers.items() if b.streams <= 0 and now - b.seen > FORGET]:
                del self._browsers[h]
            found = self._evaluate(now)
            for user, d in found.items():
                if d["stream"]:
                    self._activity[user] = wall                      # (the live stream open: seen now)
            states = {u: d["state"] for u, d in found.items()}
            counts = (sum(1 for u, s in states.items() if s == "online" and u in desk),
                      sum(1 for u, s in states.items() if s == "away" and u in desk))
            changed = states != self._states or counts != self._counts
            self._states, self._counts = states, counts
            if changed:
                self.version += 1
            urgent, self._urgent = self._urgent, set()
            due = [(u, at) for u, at in self._activity.items() if at > self._saved.get(u, 0.0)
                   and (u in urgent or now - self._saved_at.get(u, -1e18) >= SAVE)]
        self._write(due, now)
        if changed and self.on_change is not None:
            self.on_change()
        return changed

    def _write(self, due: Sequence[Tuple[str, float]], now: float) -> None:
        if not due:
            return
        self.store.set_last_seen([(u, stamp(at)) for u, at in due])
        with self._lock:
            for u, at in due:
                self._saved[u] = max(at, self._saved.get(u, 0.0))
                self._saved_at[u] = now

    def flush(self) -> None:
        """Every "last seen" not written yet, now (the dashboard stops)."""
        now, wall = self._clock(), self._wall()
        with self._lock:
            for b in self._browsers.values():
                if b.streams > 0:
                    self._activity[b.user] = wall
            due = [(u, at) for u, at in self._activity.items() if at > self._saved.get(u, 0.0)]
        self._write(due, now)

    def counters(self) -> Dict[str, int]:
        """What the live stream carries: the version (it moves when somebody's state changed), how many of the desk's
        users are online and away, and this process' start (a page that sees it change says again how idle it is)."""
        with self._lock:
            return {"v": self.version, "online": self._counts[0], "away": self._counts[1], "boot": self.boot}

    def mark(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Accounts (rows with name, created_at, last_seen, last_login) with their state now: ``state`` online / away /
        offline, ``idle`` (seconds without input, when away) and ``last_seen`` with what is not written yet (``None``:
        made and never signed in)."""
        now, wall = self._clock(), self._wall()
        with self._lock:
            found = self._evaluate(now)
            activity = dict(self._activity)
        for r in rows:
            d = found.get(r["name"])
            r["state"] = d["state"] if d else "offline"
            if d and d["state"] == "away":
                r["idle"] = int(now - d["input"])
            seen = r.get("last_seen")
            if not r.get("last_login") and seen == r.get("created_at"):
                seen = None                                          # (the account's creation, not a visit)
            at = wall if d and d["stream"] else activity.get(r["name"])
            if at is not None and (seen is None or stamp(at) > seen):
                seen = stamp(at)
            r["last_seen"] = seen
        return rows

    def listing(self, me: Optional[str] = None) -> Dict[str, Any]:
        """The desk's users as the top bar's list shows them - everybody gets the same, no address: name, state (and how
        long idle when away), last seen, last login; the counts; ``now`` (the server's time: "12 dk önce" is worked out
        against it)."""
        rows = self.mark(self.store.desk_users())
        users = []
        for r in rows:
            item = {"name": r["name"], "display": r["display"], "state": r["state"], "last_seen": r["last_seen"],
                    "last_login": r["last_login"]}
            if "idle" in r:
                item["idle"] = r["idle"]
            if me and r["name"] == me:
                item["me"] = True
            users.append(item)
        with self._lock:
            version = self.version
        return {"now": stamp(self._wall()), "users": users, "online": sum(1 for u in users if u["state"] == "online"),
                "away": sum(1 for u in users if u["state"] == "away"), "v": version, "boot": self.boot}

    # ------------------------------------------------------------------ the thread
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tto-presence", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """The thread ends; what is not written yet is written."""
        self._stop.set()
        self._kick.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5.0)
        self._thread = None
        try:
            self.flush()
        except Exception as exc:  # noqa: BLE001 - stopping goes on (said in the log)
            self._failed(exc)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._kick.wait(TICK)
            if self._stop.is_set():
                break
            self._kick.clear()
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything (and say so in the log)
                self._failed(exc)
            self._stop.wait(0.2)                    # (a burst of changes: one look for all of them)

    def _failed(self, exc: BaseException) -> None:
        if self.on_error is not None:
            try:
                self.on_error(exc)
            except Exception:  # noqa: BLE001
                pass
