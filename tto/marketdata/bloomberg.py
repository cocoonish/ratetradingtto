"""Live market data through the Bloomberg Desktop API (``blpapi`` talking to the terminal on this machine,
``localhost:8194``).  Server-side products (B-PIPE / SAPI) need an authorisation step that is not
implemented here.

What the workbook asks for                       how it is served
-----------------------------------------------  ------------------------------------------------------------
``BDP`` real-time fields (BID, ASK, MID,          one ``ReferenceDataRequest`` for the first value, then a
PX_LAST, LAST_PRICE, PX_BID/ASK/MID, HIGH, LOW,   ``//blp/mktdata`` subscription keeps it up to date (streaming
BID_SIZE, ASK_SIZE) without overrides             does not use up the daily data limit)
other ``BDP`` fields / ``BDP`` with overrides     ``ReferenceDataRequest``, refreshed on a slow schedule
``BDH``                                           ``HistoricalDataRequest`` (Days / Fill / Per / Dates options)
``BDS``                                           ``ReferenceDataRequest`` on the bulk field
``BFXFORWARD``                                    no API equivalent: ``#N/A`` (or an optional approximation)
``RTGET`` (Refinitiv)                             not a Bloomberg function: ``#N/A``

Nothing here blocks the calculation engine: a value that is not known yet is returned as
``#N/A Requesting Data...`` (exactly what Excel shows) and the cells that used it are recalculated as soon
as the answer arrives (:meth:`BloombergProvider.drain_changes`).
"""
from __future__ import annotations

import datetime as _dt
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ..xl.errors import E_NA
from ..xl.values import XlArray, date_to_serial, serial_to_date
from .base import INVALID_FIELD, INVALID_SECURITY, NOT_APPLICABLE, REQUESTING, Provider, bdp_key, tr_date_text

NA_NA = "#N/A N/A"
NO_BFX = "#N/A BFXFORWARD"
NO_RT = "#N/A RTGET"
REFDATA = "//blp/refdata"
MKTDATA = "//blp/mktdata"

#: BDP field -> name of the same quantity in a market-data subscription
RT_FIELDS = {"BID": "BID", "ASK": "ASK", "MID": "MID", "LAST_PRICE": "LAST_PRICE", "PX_LAST": "LAST_PRICE",
             "PX_BID": "BID", "PX_ASK": "ASK", "PX_MID": "MID", "HIGH": "HIGH", "LOW": "LOW",
             "BID_SIZE": "BID_SIZE", "ASK_SIZE": "ASK_SIZE"}      # order sizes of the BIST swap quotes

#: how often (seconds) reference values are asked again; real-time fields are streamed instead
STATIC_FIELDS = {"NAME", "SECURITY_DES", "CPN", "CPN_TYP", "CPN_FREQ", "MATURITY", "FIRST_CPN_DT", "FLT_SPREAD",
                 "INFLATION_LINKED_INDICATOR", "LAST_TRADEABLE_DT"}
REFRESH_STATIC = 6 * 3600.0
REFRESH_DAILY = 30 * 60.0
REFRESH_DERIVED = 60.0
REFRESH_HISTORY = 15 * 60.0
#: a real-time field that does not arrive through its subscription is asked by request instead: first after
#: ``price_poll`` seconds and then, as long as the answer stays the same, at twice the previous interval up to
#: these limits.  (A sheet such as the BIST swap quotes watches hundreds of maturities that have no quote at
#: all: asked every two minutes they alone would use up the daily data limit within hours.)
PRICE_POLL_MAX = 30 * 60.0            # a value that may have gone stale
PRICE_POLL_MAX_EMPTY = 60 * 60.0      # a field without any value ("#N/A N/A")
#: seconds after which a started subscription that has not delivered a field counts as not delivering it
SILENT_AFTER = 30.0
#: answers that no later request will change: never asked again
FINAL_ANSWERS = (INVALID_SECURITY, INVALID_FIELD, NOT_APPLICABLE)

_PERIODICITY = {"D": "DAILY", "W": "WEEKLY", "M": "MONTHLY", "Q": "QUARTERLY", "S": "SEMI_ANNUALLY", "Y": "YEARLY"}
_DAYS = {"W": "NON_TRADING_WEEKDAYS", "A": "ALL_CALENDAR_DAYS", "C": "ALL_CALENDAR_DAYS", "T": "ACTIVE_DAYS_ONLY"}
_FILL = {"P": "PREVIOUS_VALUE", "B": "NIL_VALUE", "N": "NIL_VALUE"}


def _override_value(name: str, value: str) -> str:
    """Date overrides typed as an Excel serial number are sent as YYYYMMDD."""
    if ("_DT" in name or "DATE" in name) and value.isdigit() and len(value) == 5 and 20000 < int(value) < 80000:
        return serial_to_date(float(value)).strftime("%Y%m%d")
    return value


class _Item(object):
    __slots__ = ("state", "fetched", "refresh", "streamed", "poll")

    def __init__(self):
        self.state = "queued"        # queued | sent | ok
        self.fetched = 0.0
        self.refresh = 0.0           # seconds between reference refreshes (0 = never)
        self.streamed = 0.0          # time of the last value that came from a subscription
        self.poll = 0.0              # current interval of a polled real-time field (0 = not polled); backs off


class _Request(object):
    __slots__ = ("kind", "keys", "sent", "wanted")

    def __init__(self, kind: str, keys: List[Tuple], wanted: Dict[str, List[Tuple]]):
        self.kind = kind
        self.keys = keys
        self.sent = time.time()
        self.wanted = wanted         # security -> keys expected for it


class _Sub(object):
    __slots__ = ("cid", "fields", "sent_fields", "state", "bad", "since")

    def __init__(self, cid: int):
        self.cid = cid
        self.fields: Set[str] = set()
        self.sent_fields: Set[str] = set()
        self.state = "new"           # new | pending | started | failed
        self.bad: Set[str] = set()
        self.since = 0.0


class BloombergProvider(Provider):
    live = True

    def __init__(self, host: str = "localhost", port: int = 8194, stream: bool = True, price_poll: float = 120.0,
                 request_timeout: float = 45.0, max_hits_per_day: int = 400000, bfx: str = "off",
                 blpapi_module=None, reconnect_wait: float = 10.0):
        self.host = host
        self.port = int(port)
        self.stream = stream
        self.price_poll = float(price_poll)
        self.request_timeout = float(request_timeout)
        self.max_hits_per_day = int(max_hits_per_day)
        self.bfx_mode = bfx
        self.reconnect_wait = float(reconnect_wait)
        self._bp = blpapi_module
        self._lock = threading.RLock()
        self._values: Dict[Tuple, Any] = {}
        self._items: Dict[Tuple, _Item] = {}
        self._queue: List[Tuple] = []
        self._changed: Set[Tuple] = set()
        self._requests: Dict[int, _Request] = {}
        self._subs: Dict[str, _Sub] = {}
        self._sub_by_cid: Dict[int, str] = {}
        self._rt_keys: Dict[Tuple[str, str], List[Tuple]] = {}
        self._derived: Dict[Tuple, Set[Tuple]] = {}      # source key -> keys computed from it (BFX approximation)
        self._cid = 1000
        self._session = None
        self._refdata = None
        self._names: Dict[str, Any] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self.connected = False
        self.hits = 0
        self.hits_day = _dt.date.today()
        self.requests_sent = 0
        self.ticks = 0
        self.last_tick = 0.0
        self.last_error = ""
        self.limit_reached = False

    # ================================================================== lifecycle
    def start(self) -> None:
        """Connect (raises ``RuntimeError`` / ``ImportError`` when Bloomberg is not reachable)."""
        if self._bp is None:
            import blpapi  # noqa: PLC0415 - optional dependency
            self._bp = blpapi
        self._open_session()
        self._stop.clear()
        for name, fn in (("tto-bbg-read", self._read_loop), ("tto-bbg-work", self._work_loop)):
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def _open_session(self) -> None:
        bp = self._bp
        opts = bp.SessionOptions()
        opts.setServerHost(self.host)
        opts.setServerPort(self.port)
        for setter, value in (("setAutoRestartOnDisconnection", True), ("setNumStartAttempts", 2)):
            fn = getattr(opts, setter, None)
            if fn is not None:
                try:
                    fn(value)
                except Exception:  # noqa: BLE001 - optional tuning only
                    pass
        session = bp.Session(opts)
        if not session.start():
            raise RuntimeError("Bloomberg oturumu açılamadı (%s:%d) – terminal açık ve giriş yapılmış mı?" % (self.host, self.port))
        if not session.openService(REFDATA):
            session.stop()
            raise RuntimeError("Bloomberg %s servisi açılamadı" % REFDATA)
        self._refdata = session.getService(REFDATA)
        if self.stream:
            try:
                if not session.openService(MKTDATA):
                    self.stream = False
                    self.last_error = "%s açılamadı – fiyatlar %g sn'de bir sorgulanacak" % (MKTDATA, self.price_poll)
            except Exception as exc:  # noqa: BLE001
                self.stream = False
                self.last_error = "%s: %s" % (MKTDATA, exc)
        self._session = session
        self.connected = True

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        session = self._session
        self._session = None
        self.connected = False
        if session is not None:
            try:
                session.stop()
            except Exception:  # noqa: BLE001
                pass
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads = []

    def _name(self, text: str):
        n = self._names.get(text)
        if n is None:
            cls = getattr(self._bp, "Name", None)
            n = cls(text) if cls is not None else text
            self._names[text] = n
        return n

    # ================================================================== engine side (never blocks)
    def _lookup(self, key: Tuple, refresh: float, rt_field: Optional[str] = None) -> Any:
        with self._lock:
            v = self._values.get(key)
            if v is not None:
                return v
            if key not in self._items:
                it = _Item()
                it.refresh = refresh
                if rt_field is not None and not self.stream:
                    it.poll = refresh                    # no subscriptions at all: quotes are polled (and back off)
                self._items[key] = it
                self._queue.append(key)
                if rt_field is not None and self.stream:
                    self._rt_keys.setdefault((key[1], rt_field), []).append(key)
                    sub = self._subs.get(key[1])
                    if sub is None:
                        self._cid += 1
                        sub = _Sub(self._cid)
                        self._subs[key[1]] = sub
                        self._sub_by_cid[sub.cid] = key[1]
                    sub.fields.add(rt_field)
                self._wake.set()
            return REQUESTING

    def get_bdp(self, key: Tuple) -> Any:
        field, overrides = key[2], key[3]
        rt = RT_FIELDS.get(field) if not overrides else None
        if rt is not None:
            refresh = 0.0 if self.stream else self.price_poll
        elif field in STATIC_FIELDS:
            refresh = REFRESH_STATIC
        elif field.startswith("YAS_") or field.startswith("CHG_") or field in ("LAST_TRADE_DATE", "LAST_UPDATE"):
            refresh = REFRESH_DERIVED
        else:
            refresh = REFRESH_DAILY
        return self._lookup(key, refresh, rt)

    def get_bds(self, key: Tuple) -> Any:
        return self._lookup(key, REFRESH_STATIC)

    def get_bdh(self, key: Tuple) -> Any:
        today = _dt.date.today().strftime("%Y%m%d")
        return self._lookup(key, REFRESH_HISTORY if key[4] >= today else REFRESH_STATIC)

    def get_bfx(self, key: Tuple) -> Any:
        if self.bfx_mode != "approx":
            return NO_BFX
        return self._bfx_approx(key)

    def get_rt(self, key: Tuple) -> Any:
        return NO_RT

    def drain_changes(self) -> List[Tuple]:
        """Keys whose value changed since the last call (the engine recalculates their dependants)."""
        with self._lock:
            if not self._changed:
                return []
            out = list(self._changed)
            self._changed.clear()
            for k in list(out):
                out.extend(self._derived.get(k, ()))
            return out

    def busy(self) -> bool:
        with self._lock:
            return bool(self._queue) or bool(self._requests)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"mode": "live", "connected": self.connected, "host": "%s:%d" % (self.host, self.port),
                    "items": len(self._values), "pending": len(self._queue) + sum(len(r.keys) for r in self._requests.values()),
                    "subscriptions": sum(1 for s in self._subs.values() if s.state == "started"),
                    "subscriptions_failed": sum(1 for s in self._subs.values() if s.state == "failed"),
                    "streaming": self.stream, "requests": self.requests_sent, "hits_today": self.hits, "ticks": self.ticks,
                    "last_tick": self.last_tick, "limit_reached": self.limit_reached, "error": self.last_error,
                    "bfx": self.bfx_mode}

    # ================================================================== values
    def _set(self, key: Tuple, value: Any, streamed: bool = False) -> None:
        """Store a value (lock held by the caller)."""
        it = self._items.get(key)
        if it is None:
            it = _Item()
            self._items[key] = it
        now = time.time()
        it.state = "ok"
        old = self._values.get(key)
        if type(old) is XlArray and type(value) is XlArray:
            same = old.rows == value.rows
        else:
            same = type(old) is type(value) and old == value
        if streamed:
            it.streamed = now
            it.poll = 0.0                                # the subscription delivers: no need to poll
        else:
            if it.poll and it.fetched:                   # a polled quote: the same answer again -> ask less often
                limit = PRICE_POLL_MAX if type(value) is float else PRICE_POLL_MAX_EMPTY
                it.poll = min(it.poll * 2.0, max(limit, self.price_poll)) if same else self.price_poll
            it.fetched = now
        if not same:
            self._values[key] = value
            self._changed.add(key)

    def _convert(self, el, as_text_date: bool) -> Any:
        """blpapi scalar element -> the value Excel shows."""
        try:
            if el.isNull():
                return None
        except Exception:  # noqa: BLE001
            pass
        v = el.getValue(0) if getattr(el, "numValues", None) is None or el.numValues() > 0 else None
        return self._py(v, as_text_date)

    @staticmethod
    def _py(v: Any, as_text_date: bool) -> Any:
        if v is None:
            return None
        if isinstance(v, bool):
            return "Y" if v else "N"
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, _dt.datetime):
            if as_text_date:
                if v.hour or v.minute or v.second:
                    return "%s %02d:%02d:%02d" % (tr_date_text(v.date()), v.hour, v.minute, v.second)
                return tr_date_text(v.date())
            return date_to_serial(v.date()) + (v.hour * 3600 + v.minute * 60 + v.second) / 86400.0
        if isinstance(v, _dt.date):
            return tr_date_text(v) if as_text_date else float(date_to_serial(v))
        if isinstance(v, _dt.time):
            return "%02d:%02d:%02d" % (v.hour, v.minute, v.second)
        if isinstance(v, str):
            return v
        return str(v)

    # ================================================================== worker: requests, refreshes, subscriptions
    def _work_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(0.25)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                if self._session is None:
                    self._reconnect()
                    continue
                self._roll_day()
                self._schedule_refreshes()
                self._send_queued()
                self._sync_subscriptions()
                self._expire_requests()
            except Exception as exc:  # noqa: BLE001 - the worker must survive anything
                self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                time.sleep(1.0)

    def _reconnect(self) -> None:
        if self._stop.wait(self.reconnect_wait):
            return
        try:
            self._open_session()
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)[:200]
            return
        with self._lock:
            for req in self._requests.values():
                for k in req.keys:
                    self._items[k].state = "queued"
                    self._queue.append(k)
            self._requests.clear()
            for sub in self._subs.values():
                sub.state = "new"
                sub.sent_fields = set()

    def _roll_day(self) -> None:
        today = _dt.date.today()
        if today != self.hits_day:
            self.hits_day = today
            self.hits = 0
            self.limit_reached = False

    def _schedule_refreshes(self) -> None:
        now = time.time()
        with self._lock:
            if self.limit_reached:
                return
            for key, it in self._items.items():
                if it.state != "ok" or it.refresh <= 0:
                    continue
                if it.poll and self._values.get(key) in FINAL_ANSWERS:
                    continue                             # a polled quote of an unknown ticker / field
                last = max(it.fetched, it.streamed)
                if now - last >= max(it.refresh, it.poll):
                    it.state = "queued"
                    self._queue.append(key)
            # real-time keys whose subscription does not deliver are polled instead
            if self.stream and self.price_poll > 0:
                for (sec, field), keys in self._rt_keys.items():
                    sub = self._subs.get(sec)
                    dead = sub is None or sub.state == "failed" or field in sub.bad or \
                        (sub.state == "started" and now - sub.since > SILENT_AFTER)
                    if not dead:
                        continue
                    for key in keys:
                        it = self._items.get(key)
                        if it is None or it.state != "ok" or it.streamed:
                            continue
                        if self._values.get(key) in FINAL_ANSWERS:
                            continue                     # nothing a later request could change
                        if now - it.fetched >= (it.poll or self.price_poll):
                            it.poll = it.poll or self.price_poll
                            it.state = "queued"
                            self._queue.append(key)

    def _send_queued(self) -> None:
        with self._lock:
            if not self._queue or len(self._requests) >= 12:
                return
            keys = self._queue
            self._queue = []
            for k in keys:
                self._items[k].state = "sent"
        bdp: Dict[Tuple, Dict[str, Set[str]]] = {}
        bds: Dict[Tuple, List[Tuple]] = {}
        bdh: Dict[Tuple, List[Tuple]] = {}
        index: Dict[Tuple, Tuple] = {}
        for k in keys:
            kind = k[0]
            if kind == "BDP":
                bdp.setdefault(k[3], {}).setdefault(k[1], set()).add(k[2])
                index[(k[3], k[1], k[2])] = k
            elif kind == "BDS":
                bds.setdefault((k[2], k[3]), []).append(k)
            elif kind == "BDH":
                # Dates / Sort / Dir only shape the result: calls that differ in nothing else share a request
                asked = tuple(o for o in k[5] if o[0] not in ("DATES", "SORT", "DIR"))
                bdh.setdefault((k[2], k[3], k[4], asked), []).append(k)
        for overrides, by_sec in bdp.items():
            groups: Dict[frozenset, List[str]] = {}
            for sec, fields in by_sec.items():
                groups.setdefault(frozenset(fields), []).append(sec)
            for fields, secs in groups.items():
                for i in range(0, len(secs), 100):
                    chunk = secs[i:i + 100]
                    wanted = {s: [index[(overrides, s, f)] for f in fields] for s in chunk}
                    self._reference(chunk, sorted(fields), overrides, "BDP", wanted)
        for (field, overrides), ks in bds.items():
            for i in range(0, len(ks), 50):
                chunk = ks[i:i + 50]
                self._reference([k[1] for k in chunk], [field], overrides, "BDS", {k[1]: [k] for k in chunk})
        for (field, start, end, options), ks in bdh.items():
            for i in range(0, len(ks), 50):
                self._history(ks[i:i + 50], field, start, end, options)

    def _count(self, n: int) -> bool:
        self.hits += n
        if self.max_hits_per_day and self.hits > self.max_hits_per_day:
            if not self.limit_reached:
                self.limit_reached = True
                self.last_error = "günlük veri limiti koruması devrede (%d istek) – yalnızca akan veriler güncelleniyor" % self.hits
        return True

    def _dispatch(self, request, req: _Request) -> None:
        bp = self._bp
        with self._lock:
            self._cid += 1
            cid = self._cid
            self._requests[cid] = req
        try:
            self._session.sendRequest(request, correlationId=bp.CorrelationId(cid))
            self.requests_sent += 1
        except Exception as exc:  # noqa: BLE001
            self.last_error = "istek gönderilemedi: %s" % (str(exc)[:160],)
            with self._lock:
                self._requests.pop(cid, None)
                for k in req.keys:
                    self._items[k].state = "queued"
                    self._queue.append(k)
            time.sleep(0.5)

    def _reference(self, securities: List[str], fields: List[str], overrides: Tuple, kind: str,
                   wanted: Dict[str, List[Tuple]]) -> None:
        request = self._refdata.createRequest("ReferenceDataRequest")
        for s in securities:
            request.append(self._name("securities"), s)
        for f in fields:
            request.append(self._name("fields"), f)
        if overrides:
            ov = request.getElement(self._name("overrides"))
            for name, value in overrides:
                item = ov.appendElement()
                item.setElement(self._name("fieldId"), name)
                item.setElement(self._name("value"), _override_value(name, value))
        self._count(len(securities) * len(fields))
        keys = [k for ks in wanted.values() for k in ks]
        self._dispatch(request, _Request(kind, keys, wanted))

    def _history(self, keys: List[Tuple], field: str, start: str, end: str, options: Tuple) -> None:
        request = self._refdata.createRequest("HistoricalDataRequest")
        wanted: Dict[str, List[Tuple]] = {}
        for k in keys:
            wanted.setdefault(k[1], []).append(k)
        for sec in wanted:
            request.append(self._name("securities"), sec)
        request.append(self._name("fields"), field)
        request.set(self._name("startDate"), start)
        request.set(self._name("endDate"), end)
        opts = dict(options)
        per = opts.get("PER", "D")
        request.set(self._name("periodicitySelection"), _PERIODICITY.get(per[-1:], "DAILY"))
        if len(per) > 1 and per[0] in ("A", "C", "F"):
            request.set(self._name("periodicityAdjustment"), {"A": "ACTUAL", "C": "CALENDAR", "F": "FISCAL"}[per[0]])
        if opts.get("DAYS") in _DAYS:
            request.set(self._name("nonTradingDayFillOption"), _DAYS[opts["DAYS"]])
        if opts.get("FILL") in _FILL:
            request.set(self._name("nonTradingDayFillMethod"), _FILL[opts["FILL"]])
        if opts.get("CDR"):
            request.set(self._name("calendarCodeOverride"), opts["CDR"])
        if opts.get("FX"):
            request.set(self._name("currency"), opts["FX"])
        self._count(len(wanted))
        self._dispatch(request, _Request("BDH", keys, wanted))

    def _expire_requests(self) -> None:
        now = time.time()
        with self._lock:
            for cid in [c for c, r in self._requests.items() if now - r.sent > self.request_timeout]:
                req = self._requests.pop(cid)
                self.last_error = "istek zaman aşımına uğradı (%d öğe) – yeniden denenecek" % len(req.keys)
                for k in req.keys:
                    it = self._items[k]
                    if it.state == "sent":
                        it.state = "queued"
                        self._queue.append(k)

    def _sync_subscriptions(self) -> None:
        if not self.stream or self._session is None:
            return
        bp = self._bp
        fresh, changed = [], []
        with self._lock:
            for sec, sub in self._subs.items():
                if sub.state == "new":
                    fresh.append((sec, sub, sorted(sub.fields)))
                    sub.state = "pending"
                    sub.sent_fields = set(sub.fields)
                    sub.since = time.time()
                elif sub.state == "started" and sub.fields - sub.sent_fields:
                    changed.append((sec, sub, sorted(sub.fields)))
                    sub.sent_fields = set(sub.fields)
        for group, action in ((fresh, "subscribe"), (changed, "resubscribe")):
            for i in range(0, len(group), 200):
                lst = bp.SubscriptionList()
                for sec, sub, fields in group[i:i + 200]:
                    lst.add(sec, fields, [], bp.CorrelationId(sub.cid))
                try:
                    getattr(self._session, action)(lst)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = "abonelik hatası: %s" % (str(exc)[:160],)
                    with self._lock:
                        for sec, sub, _ in group[i:i + 200]:
                            sub.state = "failed"

    # ================================================================== reader: events from Bloomberg
    def _read_loop(self) -> None:
        bp = self._bp
        ev_types = bp.Event
        while not self._stop.is_set():
            session = self._session
            if session is None:
                time.sleep(0.2)
                continue
            try:
                event = session.nextEvent(500)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    return
                self.last_error = "nextEvent: %s" % (str(exc)[:160],)
                time.sleep(0.5)
                continue
            try:
                et = event.eventType()
                if et == ev_types.TIMEOUT:
                    continue
                if et == ev_types.SUBSCRIPTION_DATA:
                    for msg in event:
                        self._on_tick(msg)
                elif et in (ev_types.RESPONSE, ev_types.PARTIAL_RESPONSE):
                    final = et == ev_types.RESPONSE
                    for msg in event:
                        self._on_response(msg, final)
                elif et == ev_types.SUBSCRIPTION_STATUS:
                    for msg in event:
                        self._on_sub_status(msg)
                elif et == ev_types.REQUEST_STATUS:
                    for msg in event:
                        self._on_request_failure(msg)
                elif et == ev_types.SESSION_STATUS:
                    for msg in event:
                        self._on_session_status(msg)
            except Exception as exc:  # noqa: BLE001 - one bad message must not stop the stream
                self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])

    @staticmethod
    def _cids(msg) -> List[Any]:
        try:
            return [c.value() for c in msg.correlationIds()]
        except Exception:  # noqa: BLE001
            return []

    def _on_session_status(self, msg) -> None:
        kind = str(msg.messageType())
        if kind in ("SessionTerminated", "SessionStartupFailure"):
            self.connected = False
            self.last_error = "Bloomberg oturumu kapandı – yeniden bağlanılacak"
            old = self._session
            self._session = None
            try:
                if old is not None:
                    old.stop()
            except Exception:  # noqa: BLE001
                pass
        elif kind == "SessionConnectionDown":
            self.connected = False
            self.last_error = "Bloomberg bağlantısı koptu"
        elif kind in ("SessionConnectionUp", "SessionStarted"):
            self.connected = True

    def _on_request_failure(self, msg) -> None:
        with self._lock:
            for cid in self._cids(msg):
                req = self._requests.pop(cid, None)
                if req is None:
                    continue
                self.last_error = "istek reddedildi: %s" % (str(msg)[:200].replace("\n", " "),)
                for k in req.keys:
                    self._set(k, NA_NA)

    def _on_sub_status(self, msg) -> None:
        kind = str(msg.messageType())
        with self._lock:
            for cid in self._cids(msg):
                sec = self._sub_by_cid.get(cid)
                sub = self._subs.get(sec) if sec is not None else None
                if sub is None:
                    continue
                if kind == "SubscriptionStarted":
                    sub.state = "started"
                    sub.since = time.time()
                    try:
                        root = msg.asElement()
                        if root.hasElement(self._name("exceptions")):
                            exc = root.getElement(self._name("exceptions"))
                            for i in range(exc.numValues()):
                                item = exc.getValueAsElement(i)
                                sub.bad.add(str(item.getElementAsString(self._name("fieldId"))))
                    except Exception:  # noqa: BLE001
                        pass
                elif kind in ("SubscriptionFailure", "SubscriptionTerminated"):
                    sub.state = "failed"

    def _on_tick(self, msg) -> None:
        cids = self._cids(msg)
        with self._lock:
            for cid in cids:
                sec = self._sub_by_cid.get(cid)
                sub = self._subs.get(sec) if sec is not None else None
                if sub is None:
                    continue
                for field in sub.sent_fields:
                    name = self._name(field)
                    if not msg.hasElement(name):
                        continue
                    el = msg.getElement(name)
                    v = self._convert(el, True)
                    if type(v) is not float:
                        continue
                    for key in self._rt_keys.get((sec, field), ()):
                        self._set(key, v, streamed=True)
                self.ticks += 1
                self.last_tick = time.time()

    def _on_response(self, msg, final: bool) -> None:
        with self._lock:
            reqs = [(cid, self._requests.get(cid)) for cid in self._cids(msg)]
        for cid, req in reqs:
            if req is None:
                continue
            try:
                if req.kind == "BDH":
                    self._parse_history(msg, req)
                else:
                    self._parse_reference(msg, req)
            finally:
                if final:
                    with self._lock:
                        self._requests.pop(cid, None)
                        for k in req.keys:           # anything Bloomberg did not mention
                            if self._items[k].state == "sent":
                                self._set(k, NA_NA)

    def _error_text(self, info) -> str:
        try:
            sub = str(info.getElementAsString(self._name("subcategory"))) if info.hasElement(self._name("subcategory")) else ""
            cat = str(info.getElementAsString(self._name("category"))) if info.hasElement(self._name("category")) else ""
        except Exception:  # noqa: BLE001
            return NA_NA
        if sub == "NOT_APPLICABLE_TO_REF_DATA" or sub == "NOT_APPLICABLE_TO_HIST_DATA":
            return NOT_APPLICABLE
        if sub.startswith("INVALID_FIELD") or (cat == "BAD_FLD" and not sub):
            return INVALID_FIELD
        if cat == "BAD_SEC" or sub == "INVALID_SECURITY":
            return INVALID_SECURITY
        return NA_NA

    def _parse_reference(self, msg, req: _Request) -> None:
        root = msg.asElement()
        n = self._name
        if root.hasElement(n("responseError")):
            self.last_error = "Bloomberg yanıt hatası: %s" % (str(root.getElement(n("responseError")))[:200].replace("\n", " "),)
            with self._lock:
                for k in req.keys:
                    self._set(k, NA_NA)
            return
        if not root.hasElement(n("securityData")):
            return
        sdata = root.getElement(n("securityData"))
        for i in range(sdata.numValues()):
            sd = sdata.getValueAsElement(i)
            sec = str(sd.getElementAsString(n("security")))
            keys = req.wanted.get(sec, [])
            if sd.hasElement(n("securityError")):
                text = self._error_text(sd.getElement(n("securityError")))
                with self._lock:
                    for k in keys:
                        self._set(k, INVALID_SECURITY if text == NA_NA else text)
                continue
            got: Dict[str, Any] = {}
            if sd.hasElement(n("fieldData")):
                fd = sd.getElement(n("fieldData"))
                for j in range(fd.numElements()):
                    el = fd.getElement(j)
                    got[str(el.name()).upper()] = el
            bad: Dict[str, str] = {}
            if sd.hasElement(n("fieldExceptions")):
                fe = sd.getElement(n("fieldExceptions"))
                for j in range(fe.numValues()):
                    item = fe.getValueAsElement(j)
                    fid = str(item.getElementAsString(n("fieldId"))).upper()
                    bad[fid] = self._error_text(item.getElement(n("errorInfo"))) if item.hasElement(n("errorInfo")) else NA_NA
            with self._lock:
                for k in keys:
                    field = k[2]
                    el = got.get(field)
                    if el is None:
                        self._set(k, bad.get(field, NA_NA))
                    elif req.kind == "BDS" or el.isArray():
                        self._set(k, self._bulk(el))
                    else:
                        v = self._convert(el, True)
                        self._set(k, NA_NA if v is None else v)

    def _bulk(self, el) -> Any:
        rows = []
        if el.isArray():
            for i in range(el.numValues()):
                row_el = el.getValueAsElement(i)
                rows.append([self._convert(row_el.getElement(j), False) for j in range(row_el.numElements())])
        if not rows:
            return NA_NA
        width = max(len(r) for r in rows)
        return XlArray([r + [None] * (width - len(r)) for r in rows])

    def _parse_history(self, msg, req: _Request) -> None:
        root = msg.asElement()
        n = self._name
        if root.hasElement(n("responseError")):
            with self._lock:
                for k in req.keys:
                    self._set(k, NA_NA)
            return
        if not root.hasElement(n("securityData")):
            return
        sd = root.getElement(n("securityData"))
        sec = str(sd.getElementAsString(n("security")))
        keys = req.wanted.get(sec, [])
        if sd.hasElement(n("securityError")):
            with self._lock:
                for k in keys:
                    self._set(k, INVALID_SECURITY)
            return
        points: List[Tuple[float, Any]] = []
        field = keys[0][2] if keys else ""
        if sd.hasElement(n("fieldData")):
            fd = sd.getElement(n("fieldData"))
            for i in range(fd.numValues()):
                row = fd.getValueAsElement(i)
                if not row.hasElement(n("date")):
                    continue
                d = self._convert(row.getElement(n("date")), False)
                v = self._convert(row.getElement(n(field)), False) if row.hasElement(n(field)) else None
                if type(d) is float:
                    points.append((d, v))
        points.sort(key=lambda p: p[0])
        with self._lock:
            for k in keys:
                self._set(k, self._history_value(points, dict(k[5])))

    @staticmethod
    def _history_value(points: List[Tuple[float, Any]], opts: Dict[str, str]) -> Any:
        if not points:
            return NA_NA
        if opts.get("SORT") in ("D", "R"):
            points = list(reversed(points))
        if opts.get("DATES") == "H":
            rows = [[v] for _, v in points]
        else:
            rows = [[d, v] for d, v in points]
        if opts.get("DIR") == "H":
            rows = [list(col) for col in zip(*rows)]
        return XlArray(rows)

    # ================================================================== BFXFORWARD approximation (optional)
    def _bfx_approx(self, key: Tuple) -> Any:
        """Broken-date outright from Bloomberg's own forward curve of the pair (bulk field ``FWD_CURVE``,
        outright quotes), interpolated linearly in calendar days between the standard tenors.

        This is an approximation of the FRD calculator behind Excel's ``BFXFORWARD`` - off unless the
        provider is created with ``bfx="approx"``.
        """
        pair, date, kind = key[1], key[2], key[3]
        source = ("BDS", "%s Curncy" % pair, "FWD_CURVE", (("FWD_CURVE_QUOTE_FORMAT", "OUTRIGHT"),))
        with self._lock:
            self._derived.setdefault(source, set()).add(key)
        curve = self._lookup(source, REFRESH_DERIVED)
        if type(curve) is not XlArray:
            return REQUESTING if curve == REQUESTING else NO_BFX
        try:
            target = float(date_to_serial(_dt.datetime.strptime(date, "%Y%m%d").date()))
        except ValueError:
            return E_NA
        side = 1 if kind.startswith("ASK") else 0
        pts = []
        for row in curve.rows:
            nums = [x for x in row if type(x) is float]
            dates = [x for x in nums if 30000 < x < 80000]
            quotes = [x for x in nums if not (30000 < x < 80000)]
            if not dates or len(quotes) < 2:
                continue
            q = (quotes[0] + quotes[1]) / 2.0 if kind.startswith("MID") else quotes[side]
            pts.append((dates[-1], q))
        pts.sort()
        if len(pts) < 2:
            return NO_BFX
        lo = max((p for p in pts if p[0] <= target), default=pts[0])
        hi = min((p for p in pts if p[0] >= target), default=pts[-1])
        if hi[0] == lo[0]:
            return lo[1]
        return lo[1] + (hi[1] - lo[1]) * (target - lo[0]) / (hi[0] - lo[0])


# ---------------------------------------------------------------------------------------------- diagnostics
def check_connection(host: str = "localhost", port: int = 8194, wait: float = 20.0, blpapi_module=None) -> int:
    """``python -m tto check-bloomberg``: connect, ask a few of the workbook's items, print what came back."""
    prov = BloombergProvider(host, port, blpapi_module=blpapi_module)
    try:
        prov.start()
    except ImportError as exc:
        print("blpapi yüklü değil (%s).  Kurulum:  pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi" % exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        print("Bağlantı kurulamadı: %s" % exc)
        return 1
    start = (_dt.date.today() - _dt.timedelta(days=10)).strftime("%Y%m%d")
    end = _dt.date.today().strftime("%Y%m%d")
    probes = [bdp_key("USDTRY Curncy", f) for f in ("BID", "ASK", "PX_LAST")] + \
        [bdp_key("TRY Curncy", "SETTLE_DT"), bdp_key("TYSO1 Curncy", "MID"), bdp_key("TYSO1 Curncy", "DAYS_TO_MTY"),
         bdp_key("USOSFR1 Curncy", "MID"), bdp_key("BISTTREF Index", "PX_LAST"),
         ("BDH", "USDTRY Curncy", "PX_LAST", start, end, (("DATES", "S"), ("DAYS", "W"), ("FILL", "P")))]
    for k in probes:
        prov._lookup(k, 0.0, RT_FIELDS.get(k[2]) if k[0] == "BDP" else None)
    deadline = time.time() + wait
    while time.time() < deadline and prov.busy():
        time.sleep(0.2)
    time.sleep(1.0)
    ok = 0
    for k in probes:
        v = prov._values.get(k, REQUESTING)
        shown = ("%d satır, son: %r" % (len(v.rows), v.rows[-1])) if type(v) is XlArray else repr(v)
        good = type(v) in (float, XlArray) or (type(v) is str and not v.startswith("#N/A"))
        ok += 1 if good else 0
        print("  %s  %-22s %-12s -> %s" % ("ok " if good else "!! ", k[1], k[2] if k[0] == "BDP" else "BDH " + k[2], shown))
    st = prov.status()
    print("Bağlantı: %s · abonelik: %d (başarısız %d) · istek: %d · akış: %s" % (
        "var" if st["connected"] else "yok", st["subscriptions"], st["subscriptions_failed"], st["requests"],
        "açık" if st["streaming"] else "kapalı"))
    if st["error"]:
        print("Not: %s" % st["error"])
    prov.stop()
    print("%d / %d öğe geldi" % (ok, len(probes)))
    return 0 if ok == len(probes) else 2
