"""The Bloomberg session in a process of its own.

Why.  Bloomberg hands its events to the application through a queue; an application that reads too slowly
is warned ("slow consumer") and then loses events.  Reading is done in Python, and Python runs one thread
at a time: every call into blpapi lets go of the interpreter, and when the calculation engine is busy at
that moment the reader waits a whole scheduling interval to get it back.  Measured with blpapi 3.26: a
tick that takes 0.06 ms to read alone takes 6 ms next to a computing thread - a few hundred subscriptions
are enough to fall behind for good.

So the session, its subscriptions and its requests live in a helper process in which nothing else computes
(:func:`_child_main` runs an ordinary :class:`~tto.marketdata.bloomberg.BloombergProvider` there), and the
dashboard talks to it over two pipes:

    dashboard  -- ("lookup", [(key, policy, real-time field), ...]) ------>  helper   (a key again: used on a new day)
               -- ("desk", open, close, holidays) -------------------------->           (the desk's hours)
               -- ("history", id, items, start, end, timeout) ------------->
               -- ("bars", id, security, start, end, interval, event, timeout) ->
               -- ("ref", id, securities, fields, timeout) ------------------>
               -- ("stop",) ------------------------------------------------>
               <-- ("values", [(key, value), ...], lookups seen, status) ---   every 0.1 s when something changed
               <-- ("usage", {key: hits today}) ----------------------------   the keys whose count changed, every 5 s
               <-- ("history", id, result) ----------------------------------
               <-- ("bars", id, result) -------------------------------------
               <-- ("ref", id, result) --------------------------------------

:class:`IsolatedBloombergProvider` is the dashboard's side.  It answers the engine from its own copy of the
values (never blocking), so a burst of ticks reaches the engine as "the latest value of each item", however
busy the engine is.  A helper that dies is started again and given every answer the dashboard holds (nothing is
asked again that was answered today); a helper that cannot be started at all raises :class:`IsolationError`, on
which the dashboard falls back to a session inside its own process.

The helper sends its values at least once a second (an empty batch when nothing changed): that is its
heartbeat.  A helper that is alive but silent - hung in a call, deadlocked - would otherwise leave the last
prices on every screen with nothing to tell them apart from live ones: the dashboard notes when it last heard
from it (``heard`` in the status; the badge turns "stale"), and after ``silent_restart`` seconds of silence in
market hours it ends that helper and starts a new one (see :data:`SILENT_RESTART`).
"""
from __future__ import annotations

import datetime as _dt
import importlib
import importlib.util
import logging
import multiprocessing
import pickle
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..xl.values import XlArray
from .base import REQUESTING
from .bloomberg import BUDGET, NA_NA, P_ONCE, POLL_EVERY, QUEUE_SIZE, RT_FIELDS, BloombergProvider, bar_span

log = logging.getLogger("tto.bloomberg")

#: seconds the helper waits for a message of the dashboard before it looks for changed values again
PUMP = 0.1
#: lookups per message (a first calculation registers many thousands at once)
CHUNK = 2000
#: a helper that ends within this many seconds of its start died "quickly" ...
QUICK = 300.0
#: ... and after so many quick deaths in a row no new one is started: every new helper asks Bloomberg for
#: everything again, and a helper that keeps dying must not use up the terminal's daily data limit that way
MAX_QUICK_DEATHS = 5
#: a helper that says nothing for this many seconds (it reports every second) is taken as hung and started
#: again - in market hours only, at most MAX_SILENT_RESTARTS times a day, and each time of the day only after
#: twice as long a silence as the time before (60 s, 120 s, 240 s): a new helper gets the answers the dashboard holds,
#: but this must still never turn into a loop
SILENT_RESTART = 60.0
MAX_SILENT_RESTARTS = 3
#: seconds between two reports of the day's hits by key (the status page's sheets and fields)
USAGE_EVERY = 5.0


class IsolationError(RuntimeError):
    """The helper process could not be started or did not answer (this says nothing about Bloomberg)."""


# ====================================================================================== the helper process
def _history(prov: BloombergProvider, send, rid: int, items, start: str, end: str, timeout: float) -> None:
    try:
        res = prov.history(items, start, end, timeout=timeout)
    except Exception:  # noqa: BLE001 - the caller gets "nothing came" and asks again later
        res = {}
    try:
        send(("history", rid, res))
    except Exception:  # noqa: BLE001 - the dashboard is gone
        pass


def _bars(prov: BloombergProvider, send, rid: int, security: str, start: str, end: str, interval: int, event: str,
          timeout: float) -> None:
    try:
        res = prov.intraday_bars(security, start, end, interval=interval, event=event, timeout=timeout)
    except Exception:  # noqa: BLE001 - the caller gets "nothing came" and asks again later
        res = None
    try:
        send(("bars", rid, res))
    except Exception:  # noqa: BLE001 - the dashboard is gone
        pass


def _ref(prov: BloombergProvider, send, rid: int, securities, fields, timeout: float) -> None:
    try:
        res = prov.reference(securities, fields, timeout=timeout)
    except Exception:  # noqa: BLE001 - the caller gets "nothing came"
        res = None
    try:
        send(("ref", rid, res))
    except Exception:  # noqa: BLE001 - the dashboard is gone
        pass


def _send_values(send, batch, seen: int, status: Dict[str, Any]) -> None:
    try:
        send(("values", batch, seen, status))
    except (EOFError, OSError):
        raise
    except Exception:  # noqa: BLE001 - a value that cannot cross the pipe must not hold up the others
        good = []
        for key, value in batch:
            try:
                pickle.dumps(value)
                good.append((key, value))
            except Exception:  # noqa: BLE001
                good.append((key, NA_NA))
        send(("values", good, seen, status))


def _child_main(inbox, outbox, cfg: Dict[str, Any]) -> None:
    """Body of the helper process: a :class:`BloombergProvider`, fed and emptied through the two pipes."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)       # Ctrl+C in the console: the dashboard stops us
    except Exception:  # noqa: BLE001
        pass
    lock = threading.Lock()

    def send(obj) -> None:
        with lock:
            outbox.send(obj)

    try:
        module = importlib.import_module(cfg["module"]) if cfg.get("module") else None
        prov = BloombergProvider(cfg["host"], cfg["port"], stream=cfg["stream"], price_poll=cfg["price_poll"],
                                 request_timeout=cfg["request_timeout"], max_hits_per_day=cfg["max_hits_per_day"],
                                 bfx="off", blpapi_module=module, reconnect_wait=cfg["reconnect_wait"],
                                 queue_size=cfg["queue_size"], interval=cfg["interval"], budget=cfg.get("budget", BUDGET))
        prov.hits = int(cfg.get("hits_start") or 0)        # what earlier helpers used today counts too
        prov.carry_day(cfg.get("kinds_start"), cfg.get("usage_start"), cfg.get("limit"))
        if cfg.get("desk"):
            prov.set_desk_hours(*cfg["desk"])            # the desk's hours: no refresh, no poll outside them
        prov.preload(cfg.get("preload") or [])            # every answer the dashboard holds from earlier today
        prov.start()
    except ImportError as exc:
        send(("failed", "import", str(exc)))
        return
    except Exception as exc:  # noqa: BLE001
        send(("failed", "start", str(exc)))
        return
    registered = set()
    seen = 0
    last = 0.0
    told: Dict[Tuple, int] = dict(prov.usage())          # the day's hits by key as the dashboard has them
    told_rev, told_at = prov.usage_rev, time.time()
    pump = float(cfg.get("pump") or PUMP)
    try:
        send(("started", prov.status()))
        while True:
            fresh: List[Tuple] = []
            keys: List[Tuple] = []
            asked = False
            try:
                if inbox.poll(pump):                       # EOFError / OSError: the dashboard is gone
                    while True:
                        msg = inbox.recv()
                        kind = msg[0]
                        if kind == "stop":
                            return
                        if kind == "lookup":
                            asked = True
                            for key, policy, rt in msg[1]:
                                registered.add(key)
                                seen += 1
                                if prov._lookup(key, policy, rt) != REQUESTING:
                                    fresh.append(key)      # known already (asked a second time: used on a new day)
                        elif kind == "desk":
                            prov.set_desk_hours(*msg[1:])
                        elif kind == "history":
                            threading.Thread(target=_history, args=(prov, send) + tuple(msg[1:]),
                                             name="tto-bbg-history", daemon=True).start()
                        elif kind == "bars":
                            threading.Thread(target=_bars, args=(prov, send) + tuple(msg[1:]),
                                             name="tto-bbg-bars", daemon=True).start()
                        elif kind == "ref":
                            threading.Thread(target=_ref, args=(prov, send) + tuple(msg[1:]),
                                             name="tto-bbg-ref", daemon=True).start()
                        if not inbox.poll(0):
                            break
                status = prov.status()                     # before the values: "nothing pending" then means
                keys = prov.drain_changes()                # that every answer is in this very batch
                now = time.time()
                if keys or fresh or asked or now - last >= 1.0:
                    with prov._lock:
                        batch = [(k, prov._values.get(k)) for k in set(keys).union(fresh) if k in registered]
                    _send_values(send, batch, seen, status)
                    last = now
                if prov.usage_rev != told_rev and now - told_at >= USAGE_EVERY:
                    told_rev, told_at = prov.usage_rev, now
                    counts = prov.usage()
                    if not counts and told:
                        told = {}
                        send(("usage", None))              # a new day: the dashboard starts its count afresh
                    delta = {k: n for k, n in counts.items() if told.get(k) != n}
                    if delta:
                        told.update(delta)
                        send(("usage", delta))
            except (EOFError, OSError):
                raise
            except Exception as exc:  # noqa: BLE001 - the helper must survive anything but a lost dashboard
                prov.last_error = "yardımcı süreç: %s: %s" % (type(exc).__name__, str(exc)[:160])
                with prov._lock:
                    prov._changed.update(keys)             # not delivered: they go out with the next batch
                time.sleep(0.2)
    except (EOFError, OSError):
        pass                                               # the dashboard went away: so do we
    finally:
        try:
            prov.stop()
        except Exception:  # noqa: BLE001
            pass


# ====================================================================================== the dashboard's side
class IsolatedBloombergProvider(BloombergProvider):
    """A :class:`BloombergProvider` whose session runs in a helper process (see the module text).

    ``blpapi_name`` names a module to use in place of ``blpapi`` (the tests' stand-in); it is imported in
    the helper, never here.
    """

    isolated = True

    def __init__(self, host: str = "localhost", port: int = 8194, stream: bool = True, price_poll: float = POLL_EVERY,
                 request_timeout: float = 45.0, max_hits_per_day: int = 400000, bfx: str = "off",
                 reconnect_wait: float = 10.0, queue_size: int = QUEUE_SIZE, interval: float = 0.0,
                 blpapi_name: Optional[str] = None, start_timeout: float = 60.0, pump: float = PUMP,
                 silent_restart: float = SILENT_RESTART, budget: int = BUDGET):
        super(IsolatedBloombergProvider, self).__init__(
            host, port, stream=stream, price_poll=price_poll, request_timeout=request_timeout,
            max_hits_per_day=max_hits_per_day, bfx=bfx, reconnect_wait=reconnect_wait, queue_size=queue_size,
            interval=interval, budget=budget)
        self.blpapi_name = blpapi_name
        self.start_timeout = float(start_timeout)
        self._cfg = {"host": host, "port": int(port), "stream": bool(stream), "price_poll": float(price_poll),
                     "request_timeout": float(request_timeout), "max_hits_per_day": int(max_hits_per_day),
                     "reconnect_wait": float(reconnect_wait), "queue_size": int(queue_size or 0),
                     "interval": float(interval or 0.0), "module": blpapi_name, "pump": float(pump),
                     "budget": int(budget or 0)}
        self._wanted: Dict[Tuple, Tuple[str, Optional[str]]] = {}       # everything asked for so far: (policy, rt)
        self._used: Dict[Tuple, int] = {}                                # ... the day each was last read (an ordinal)
        self._outbox: List[Tuple] = []                                   # ... and not sent to the helper yet
        self._sent = 0
        self._seen = 0
        self._proc = None
        self._rx = None                      # helper -> dashboard
        self._tx = None                      # dashboard -> helper
        self._tx_lock = threading.Lock()
        self._remote: Dict[str, Any] = {}    # the helper's last status
        self._waiters: Dict[int, List[Any]] = {}
        self._rid = 0
        self.restarts = 0
        self._born = 0.0                     # when the present helper came up
        self._quick_deaths = 0               # helpers in a row that did not live long
        self._gave_up = False
        self._carry = (None, 0)              # (day, data points used) by helpers that are gone
        # the heartbeat: when the present helper last said anything; silent that long, it is started again
        self.silent_restart = max(0.0, float(silent_restart or 0.0))
        #: asked (from this provider's own thread, so it must not block) whether a silent helper may be started
        #: again now - the dashboard answers "in market hours"; None: always
        self.restart_allowed: Optional[Callable[[], bool]] = None
        self._heard = 0.0                    # epoch seconds, as the ticks' times (shown)
        self._quiet_since = 0.0              # the same on the monotonic clock (measured: a clock set right is no silence)
        self._silent = (None, 0)             # (day, helpers started again today because they went silent)
        self._silence_told = False           # the present silence is in the log already
        self._said = ""                      # the last word of this side in the log (a fault repeats every few seconds)
        self._kept: List[Tuple] = []         # answers kept from earlier today (preload): the helper's too
        self._got: Dict[Tuple, float] = {}   # key -> when its answer last came from the helper
        self._desk_args: Optional[Tuple] = None      # (open, close, holidays): the desk's hours, told every helper
        self._limit_iso = ""                 # Bloomberg's own daily limit, as the helpers said (a new one starts with it)

    # ================================================================== lifecycle
    def start(self) -> None:
        """Start the helper and wait for its session (``ImportError`` / ``RuntimeError`` as in-process;
        :class:`IsolationError` when the helper itself does not come up)."""
        name = self.blpapi_name or "blpapi"
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            raise ImportError("No module named %r" % name)       # not worth starting a process to find out
        self._stop.clear()
        self._spawn()
        for label, fn in (("tto-bbg-recv", self._recv_loop), ("tto-bbg-send", self._send_loop)):
            t = threading.Thread(target=fn, name=label, daemon=True)
            t.start()
            self._threads.append(t)

    def _spawn(self) -> None:
        # "spawn" everywhere: what Windows does anyway, and safe in a process that already has threads
        ctx = multiprocessing.get_context("spawn")
        proc = None
        ends: List[Any] = []
        try:
            rx, child_tx = ctx.Pipe(False)
            child_rx, tx = ctx.Pipe(False)
            ends = [rx, child_tx, child_rx, tx]
            cfg = dict(self._cfg)
            today = _dt.date.today()
            day, used = self._carry
            cfg["hits_start"] = used if day == today else 0
            with self._lock:
                # every answer held here - kept from earlier today and got since -: a new helper asks none of them again
                held = {k: (v, t) for k, v, t in self._kept}
                held.update({k: (v, t) for k, v, t in self.answers(0.0)})
                cfg["preload"] = [(k, v, t) for k, (v, t) in held.items()]
                if self.hits_day == today:
                    cfg["kinds_start"] = dict(self.kinds)
                    cfg["usage_start"] = dict(self.key_hits)
            cfg["limit"] = self._limit_iso
            cfg["desk"] = self._desk_args
            proc = ctx.Process(target=_child_main, args=(child_rx, child_tx, cfg), name="tto-bloomberg", daemon=True)
            proc.start()
            child_rx.close()                 # ours are the other two ends; with these closed here the pipes
            child_tx.close()                 # break when the helper goes away
        except Exception as exc:  # noqa: BLE001
            for end in ends:
                self._close(end)
            raise IsolationError("yardımcı süreç başlatılamadı: %s" % (str(exc)[:160],))
        first = None
        deadline = time.time() + self.start_timeout
        try:
            while time.time() < deadline and not self._stop.is_set():
                if rx.poll(0.2):
                    first = rx.recv()
                    break
                if not proc.is_alive():
                    if rx.poll(0.2):         # what it said just before it ended
                        first = rx.recv()
                    break
        except (EOFError, OSError):
            first = None
        if first is None or first[0] not in ("started", "failed"):
            code = proc.exitcode
            self._kill(proc)
            self._close(rx)
            self._close(tx)
            raise IsolationError("yardımcı süreç yanıt vermedi (%s)" % (
                "çıkış kodu %s" % code if code is not None else "%g sn içinde" % self.start_timeout,))
        if first[0] == "failed":
            proc.join(3.0)
            self._kill(proc)
            self._close(rx)
            self._close(tx)
            if first[1] == "import":
                raise ImportError(first[2])
            raise RuntimeError(first[2])
        with self._tx_lock:
            self._proc, self._rx, self._tx = proc, rx, tx
        self._born = self._heard = time.time()
        self._quiet_since = time.monotonic()
        self._silence_told = False
        self._take_status(first[1])

    @staticmethod
    def _close(end) -> None:
        try:
            end.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _kill(proc) -> None:
        try:
            if proc.is_alive():
                proc.terminate()
            proc.join(3.0)
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._post(("stop",))
        with self._tx_lock:
            proc, rx, tx = self._proc, self._rx, self._tx
            self._proc = self._rx = self._tx = None
        self.connected = False
        if proc is not None:
            try:
                proc.join(5.0)
            except Exception:  # noqa: BLE001
                pass
            self._kill(proc)
        for end in (rx, tx):
            if end is not None:
                self._close(end)
        self._release_waiters()
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads = []

    # ================================================================== engine side (never blocks)
    def _lookup(self, key: Tuple, policy: str, rt_field: Optional[str] = None) -> Any:
        with self._lock:
            v = self._values.get(key)
            if key not in self._wanted:
                # (an answer kept from earlier today is known here already: the helper is still told of the key -
                # it keeps it as answered and asks again when it is due)
                self._wanted[key] = (policy, rt_field)
                self._used[key] = self._day_no
                if rt_field is not None:
                    self._rt_keys.setdefault((key[1], rt_field), []).append(key)     # (:meth:`quote`)
                self._outbox.append((key, policy, rt_field))
                self._wake.set()
            elif self._used.get(key) != self._day_no:
                # the first read of a new day: the helper hears of it (only what is used is ever asked again)
                self._used[key] = self._day_no
                self._outbox.append((key,) + self._wanted[key])
                self._wake.set()
            return v if v is not None else REQUESTING

    def preload(self, answers) -> None:
        """As :meth:`BloombergProvider.preload`: known here at once, and to every helper started."""
        kept = [(k, v, float(t)) for k, v, t in answers if v is not None and v != REQUESTING]
        with self._lock:
            self._kept = kept
            for key, value, fetched in kept:
                self._values[key] = value
                self._got[key] = fetched

    def answers(self, since: float = 0.0) -> List[Tuple[Tuple, Any, float]]:
        """As :meth:`BloombergProvider.answers`, from what the helper sent (every key but the one-off ones)."""
        out = []
        with self._lock:
            for key, (policy, _rt) in self._wanted.items():
                if policy == P_ONCE:
                    continue
                t = self._got.get(key, 0.0)
                v = self._values.get(key)
                if t > since and v is not None and v != REQUESTING:
                    out.append((key, v, t))
        return out

    def carry_hits(self, hits: int) -> None:
        """As :meth:`BloombergProvider.carry_hits`: what the first helper starts counting from."""
        day, used = self._carry
        today = _dt.date.today()
        self._carry = (today, max(int(hits), used if day == today else 0))
        self.hits = self._carry[1]

    def carry_day(self, kinds=None, usage=None, limit=None) -> None:
        """As :meth:`BloombergProvider.carry_day`: what the first helper starts from."""
        with self._lock:
            self.hits_day = _dt.date.today()
            for k, n in (kinds or {}).items():
                self.kinds[k] = max(self.kinds.get(k, 0), int(n))
            for k, n in (usage or {}).items():
                self.key_hits[k] = max(self.key_hits.get(k, 0), int(n))
            if limit:
                self._limit_iso = str(limit)

    def set_desk_hours(self, open_: str = "08:00", close: str = "19:00", holidays=()) -> None:
        """As :meth:`BloombergProvider.set_desk_hours`, told to the helper (and to every helper started)."""
        args = (str(open_), str(close), tuple(sorted(str(d) for d in holidays)))
        super(IsolatedBloombergProvider, self).set_desk_hours(*args)
        self._desk_args = args
        self._post(("desk",) + args)

    def usage(self) -> Dict[Tuple, int]:
        """As :meth:`BloombergProvider.usage`, as the helper reported it (every few seconds)."""
        with self._lock:
            return dict(self.key_hits)

    def _roll_local_day(self) -> None:
        """The dashboard side's day (what a read counts on); a new one starts the day's counts afresh."""
        today = _dt.date.today()
        with self._lock:
            if today != self.hits_day:
                self.hits_day = today
                self.kinds = {}
                self.key_hits = {}
            self._day_no = today.toordinal()

    def busy(self) -> bool:
        if self._gave_up or self._stop.is_set():
            return False                         # nothing more will come
        with self._lock:
            if self._outbox or self._seen < self._sent:
                return True
            return bool(self._remote.get("pending"))

    def history(self, items, start, end, timeout=60.0):
        """As :meth:`BloombergProvider.history`, asked of the helper."""
        waiter: List[Any] = [threading.Event(), None]
        with self._lock:
            self._rid += 1
            rid = self._rid
            self._waiters[rid] = waiter
        try:
            if not self._post(("history", rid, [tuple(i) for i in items], start, end, float(timeout))):
                return {}
            waiter[0].wait(float(timeout) + 15.0)
            return waiter[1] or {}
        finally:
            with self._lock:
                self._waiters.pop(rid, None)

    def intraday_bars(self, security: str, start: str, end: str, interval: int = 5, event: str = "TRADE",
                      timeout: float = 60.0) -> Optional[List[Tuple[str, float, float, float, float, float]]]:
        """As :meth:`BloombergProvider.intraday_bars`, asked of the helper (which counts the hit and keeps the daily
        limit); ``None`` too when there is no helper or it ends meanwhile.  What Bloomberg would refuse is refused
        here (``ValueError``), and an empty span asks nothing."""
        t0, t1, interval, event = bar_span(start, end, interval, event)
        if t1 <= t0:
            return []
        waiter: List[Any] = [threading.Event(), None]
        with self._lock:
            self._rid += 1
            rid = self._rid
            self._waiters[rid] = waiter
        try:
            if not self._post(("bars", rid, security, start, end, interval, event, float(timeout))):
                return None
            waiter[0].wait(float(timeout) + 15.0)
            return waiter[1]
        finally:
            with self._lock:
                self._waiters.pop(rid, None)

    def reference(self, securities, fields, timeout: float = 30.0):
        """As :meth:`BloombergProvider.reference`, asked of the helper (which counts the hits and keeps the daily
        limit); None too when there is no helper or it ends meanwhile."""
        secs = [str(s) for s in securities if str(s or "").strip()]
        flds = [str(f) for f in fields if str(f or "").strip()]
        if not secs or not flds:
            return {}
        waiter: List[Any] = [threading.Event(), None]
        with self._lock:
            self._rid += 1
            rid = self._rid
            self._waiters[rid] = waiter
        try:
            if not self._post(("ref", rid, secs, flds, float(timeout))):
                return None
            waiter[0].wait(float(timeout) + 15.0)
            return waiter[1]
        finally:
            with self._lock:
                self._waiters.pop(rid, None)

    def revalidate(self) -> int:
        return 0                             # the helper does this on its own when the day changes

    def status(self) -> Dict[str, Any]:
        with self._lock:
            st = dict(self._remote)
            waiting = len(self._outbox) + max(0, self._sent - self._seen)
            alive = self._proc is not None and self._rx is not None
            st.update({"mode": "live", "host": "%s:%d" % (self.host, self.port), "items": len(self._values),
                       "pending": int(st.get("pending") or 0) + waiting, "connected": bool(self.connected and alive),
                       "streaming": bool(st.get("streaming", self.stream)), "error": self.last_error,
                       "bfx": self.bfx_mode, "isolated": True, "restarts": self.restarts,
                       "worker": "running" if alive else ("stopped" if self._gave_up or self._stop.is_set() else "restarting"),
                       # the heartbeat: when the helper last said anything (epoch seconds), and the restarts of
                       # helpers that went silent today
                       "heard": self._heard if alive else 0.0,
                       "silent_restarts": self._silent[1] if self._silent[0] == _dt.date.today() else 0})
            for name, default in (("subscriptions", 0), ("subscriptions_failed", 0), ("subscriptions_invalid", 0),
                                  ("requests", 0), ("hits_today", 0), ("ticks", 0), ("last_tick", 0.0),
                                  ("limit_reached", False), ("interval", self.interval), ("queue_size", self.queue_size),
                                  ("slow", False), ("slow_warnings", 0), ("events_dropped", 0), ("messages_lost", 0),
                                  ("resyncs", 0), ("budget", self.budget), ("max_hits", self.max_hits_per_day),
                                  ("tier", 0), ("kinds", {}), ("bbg_limit", self._limit_iso), ("bbg_limit_text", ""),
                                  ("desk", self.desk.as_dict() if self.desk is not None else None), ("quiet", False),
                                  ("polled", {}), ("poll_every", self.price_poll), ("poll_empty", 0.0), ("fed", 0)):
                st.setdefault(name, default)
            return st

    # ================================================================== talking to the helper
    def _post(self, obj) -> bool:
        with self._tx_lock:
            tx = self._tx
            if tx is None:
                return False
            try:
                tx.send(obj)
                return True
            except (OSError, ValueError, EOFError):
                return False

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.25)
            self._wake.clear()
            if self._stop.is_set():
                return
            self._roll_local_day()
            with self._lock:
                items, self._outbox = self._outbox, []
            for i in range(0, len(items), CHUNK):
                chunk = items[i:i + CHUNK]
                if self._post(("lookup", chunk)):
                    with self._lock:
                        self._sent += len(chunk)
                    continue
                with self._lock:             # no helper at the moment: a new one is asked for everything
                    if self._tx is not None:
                        self._outbox = items[i:] + self._outbox
                self._stop.wait(0.5)
                break

    def _recv_loop(self) -> None:
        while not self._stop.is_set():
            rx = self._rx
            if rx is None:
                self._respawn()
                continue
            try:
                if not rx.poll(0.5):
                    proc = self._proc
                    if proc is not None and not proc.is_alive() and not rx.poll(0):
                        raise EOFError("helper ended")
                    self._watchdog()
                    continue
                msg = rx.recv()
                self._heard = time.time()
                self._quiet_since = time.monotonic()
                self._silence_told = False
            except (EOFError, OSError):
                if self._stop.is_set():
                    return
                self._lost()
                continue
            try:
                kind = msg[0]
                if kind == "values":
                    self._apply(msg[1], msg[2], msg[3])
                elif kind == "usage":
                    with self._lock:
                        if msg[1] is None:
                            self.key_hits = {}           # the helper's day changed: its count starts afresh
                        else:
                            self.key_hits.update(msg[1])
                elif kind in ("history", "bars", "ref"):
                    with self._lock:
                        waiter = self._waiters.get(msg[1])
                    if waiter is not None:
                        waiter[1] = msg[2]
                        waiter[0].set()
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop the stream
                self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])

    def _take_status(self, status: Dict[str, Any]) -> None:
        with self._lock:
            self._remote = dict(status)
        self.connected = bool(status.get("connected"))
        self.last_error = status.get("error") or ""
        self.limit_reached = bool(status.get("limit_reached"))
        self.hits = int(status.get("hits_today") or 0)
        self.ticks = int(status.get("ticks") or 0)
        self.last_tick = float(status.get("last_tick") or 0.0)
        self.requests_sent = int(status.get("requests") or 0)
        self.stream = bool(status.get("streaming", self.stream))
        self.slow = bool(status.get("slow"))
        self.slow_warnings = int(status.get("slow_warnings") or 0)
        self.events_dropped = int(status.get("events_dropped") or 0)
        self.messages_lost = int(status.get("messages_lost") or 0)
        self.resyncs = int(status.get("resyncs") or 0)
        with self._lock:
            if isinstance(status.get("kinds"), dict):
                self.kinds = dict(status["kinds"])
        self._limit_iso = str(status.get("bbg_limit") or "")

    def _apply(self, batch, seen: int, status: Dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            for key, value in batch:
                if value is None:
                    continue
                old = self._values.get(key)
                if type(old) is XlArray and type(value) is XlArray:
                    same = old.rows == value.rows
                else:
                    same = type(old) is type(value) and old == value
                if not same:
                    self._values[key] = value
                    self._changed.add(key)
                    if value != REQUESTING:
                        # (an answer kept from earlier today, sent back unchanged, keeps the time it was fetched)
                        self._got[key] = now
            self._seen = max(self._seen, int(seen))
        self._take_status(status)

    def _release_waiters(self) -> None:
        with self._lock:
            waiters = list(self._waiters.values())
        for w in waiters:
            w[0].set()

    def _say(self, level: int, text: str) -> None:
        """Into the dashboard's log - a word repeated (a helper that cannot be started, every few seconds) once."""
        if text != self._said:
            self._said = text
            log.log(level, text)

    def _lost(self, why: str = "") -> None:
        """The helper is gone without having been told to stop (``why``: it was ended here, e.g. gone silent)."""
        with self._tx_lock:
            proc, rx, tx = self._proc, self._rx, self._tx
            self._proc = self._rx = self._tx = None
        self.connected = False
        self.last_error = "Bloomberg yardımcı süreci %s – yeniden başlatılıyor" % (why or "kapandı")
        self._quick_deaths = self._quick_deaths + 1 if time.time() - self._born < QUICK else 0
        self._carry = (_dt.date.today(), int(self.hits))    # the daily count goes on with the next helper
        code = proc.exitcode if proc is not None else None
        for end in (rx, tx):
            if end is not None:
                self._close(end)
        if proc is not None:
            self._kill(proc)
        self._release_waiters()
        self._say(logging.WARNING, "Bloomberg yardımcı süreci %s%s – yeniden başlatılacak (art arda kısa ömürlü: %d)"
                  % (why or "kapandı", "" if why or code is None else " (çıkış kodu %s)" % code, self._quick_deaths))

    def _watchdog(self) -> None:
        """A helper that is alive but has said nothing for ``silent_restart`` seconds (it reports every second:
        it hangs) is ended and a new one started - in market hours only (``restart_allowed``), and at most
        MAX_SILENT_RESTARTS times a day, the n-th time after twice as long a silence as the one before.  Beyond
        that the badge stays "stale" and the status says why: someone has to look."""
        if not self.silent_restart or not self._quiet_since or self._stop.is_set():
            return
        silent = time.monotonic() - self._quiet_since
        if silent < self.silent_restart:
            return
        today = _dt.date.today()
        used = self._silent[1] if self._silent[0] == today else 0
        if silent < self.silent_restart * (2 ** used):
            return
        try:
            allowed = self.restart_allowed is None or bool(self.restart_allowed())
        except Exception:  # noqa: BLE001 - when in doubt, nothing is started
            allowed = False
        if used >= MAX_SILENT_RESTARTS or not allowed:
            if not self._silence_told:
                self._silence_told = True
                why = ("bugün %d kez yeniden başlatıldı, artık kendiliğinden başlatılmıyor – dashboard'u yeniden başlatın"
                       % used) if used >= MAX_SILENT_RESTARTS else "piyasa saatleri dışında yeniden başlatılmıyor"
                self.last_error = "Bloomberg yardımcı süreci %d sn'dir ses vermiyor; %s" % (silent, why)
                self._say(logging.ERROR if used >= MAX_SILENT_RESTARTS else logging.WARNING, self.last_error)
            return
        self._silent = (today, used + 1)
        self._lost("%d sn ses vermedi (bugün %d. kez)" % (silent, used + 1))

    def _respawn(self) -> None:
        if self._quick_deaths >= MAX_QUICK_DEATHS:
            self._gave_up = True
            self.last_error = ("Bloomberg yardımcı süreci art arda %d kez kapandı – yeniden başlatılmıyor; "
                               "dashboard'u kapatıp yeniden açın" % self._quick_deaths)
            self._say(logging.ERROR, self.last_error)
            self._stop.wait(5.0)
            return
        # each quick death doubles the wait: 10 s, 20 s, 40 s ...
        if self._stop.wait(self.reconnect_wait * (2 ** max(0, self._quick_deaths - 1))):
            return
        try:
            self._spawn()
        except Exception as exc:  # noqa: BLE001 - tried again after the next wait
            self.last_error = "Bloomberg yardımcı süreci başlatılamadı: %s" % (str(exc)[:160],)
            self._say(logging.WARNING, self.last_error)
            return
        if self._stop.is_set():                # stopped while the helper was coming up
            with self._tx_lock:
                proc, rx, tx = self._proc, self._rx, self._tx
                self._proc = self._rx = self._tx = None
            for end in (rx, tx):
                if end is not None:
                    self._close(end)
            if proc is not None:
                self._kill(proc)
            return
        with self._lock:                       # the new helper is told every key; it holds their answers (preload)
            self._outbox = [(k, p, f) for k, (p, f) in self._wanted.items()]
            self._sent = 0
            self._seen = 0
            self.restarts += 1
            answered = sum(1 for k in self._wanted if self._values.get(k) not in (None, REQUESTING))
        self._wake.set()
        self._say(logging.INFO, "Bloomberg yardımcı süreci yeniden başladı (%d. kez); %d kalem, %d tanesinin cevabı elde "
                  "(yeniden sorulmuyor)" % (self.restarts, len(self._outbox), answered))
