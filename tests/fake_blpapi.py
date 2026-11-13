"""A small stand-in for the ``blpapi`` package: just enough of its API to exercise
:class:`tto.marketdata.bloomberg.BloombergProvider` without a Bloomberg terminal.

The "terminal" is a :class:`Server` object the test fills with data:

    server = fake_blpapi.Server()
    server.ref[("USDTRY Curncy", "BID", ())] = 49.997
    server.history[("USDTRY Curncy", "PX_LAST")] = [(date(2026, 11, 2), 49.9), ...]
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))

Two things the real library does that matter for keeping up with a busy market can be switched on:

* ``server.release_gil = True``: every accessor lets go of Python's interpreter lock for a moment, as each
  call into the real (ctypes) blpapi does - a reader that shares its process with a computing thread then
  loses the lock on them;
* ``server.queue_limit = N``: the session holds at most N undelivered events, warns at 75 % of that
  (``SlowConsumerWarning``), drops what does not fit and reports it afterwards (``DataLoss`` per
  subscription, ``SlowConsumerWarningCleared`` with the number of events dropped).

Like the real API - and unlike Excel's add-in - the pretend terminal does not know a security that is written
with its identifier type at the end ("TRT150328T24 ISIN", "TRT150328T24 @ISL1 ISIN"): it wants
"/isin/TRT150328T24@ISL1".  Test data may be stored under either spelling.
"""
from __future__ import annotations

import datetime as _dt
import queue
import threading
import time
import types
from typing import Any, Dict, List, Optional, Tuple

#: identifier types Excel's add-in accepts after an identifier, and the API's prefix for them
_ID_SUFFIX = {"ISIN": "isin", "CUSIP": "cusip", "CINS": "cins", "SEDOL": "sedol1", "SEDOL1": "sedol1",
              "SEDOL2": "sedol2", "BUID": "buid", "WPK": "wpk", "COMMON": "common", "FIGI": "bbgid", "BBGID": "bbgid"}


def excel_only(sec: str) -> bool:
    """A spelling only Excel's add-in understands (the API answers "invalid security")."""
    parts = str(sec).split()
    return not str(sec).startswith("/") and len(parts) >= 2 and parts[-1].upper() in _ID_SUFFIX


def spellings(sec: str) -> List[str]:
    """The names under which a test may have stored data for a security: as asked, and - for "/isin/ID@SRC" -
    the ways a workbook writes it for Excel ("ID @SRC ISIN", "ID@SRC ISIN", "ID ISIN")."""
    sec = str(sec)
    out = [sec]
    if excel_only(sec):                                   # stored the Excel way, asked the Excel way (ticks)
        parts = sec.split()
        out.append("/%s/%s" % (_ID_SUFFIX[parts[-1].upper()], "".join(parts[:-1])))
    elif sec.startswith("/") and sec.count("/") >= 2:
        kind, _, ident = sec[1:].partition("/")
        base, at, source = ident.partition("@")
        for suffix, prefix in _ID_SUFFIX.items():
            if prefix == kind.lower():
                out += ["%s @%s %s" % (base, source, suffix), "%s@%s %s" % (base, source, suffix)] if at \
                    else ["%s %s" % (base, suffix)]
    return out


#: set by :class:`Server` (``release_gil``): accessors behave like calls into a C library
_YIELD = {"on": False}


def _noop():
    """A C function that does nothing, called the way blpapi calls its library (``ctypes.CDLL``: the
    interpreter lock is released for the call)."""
    import ctypes
    try:
        fn = ctypes.CDLL(None).getpid                    # POSIX: the C library of the process itself
    except (OSError, AttributeError, TypeError):
        fn = ctypes.WinDLL("kernel32").GetCurrentThreadId
    fn.restype = ctypes.c_int
    fn.argtypes = []
    return fn


_NOOP = _noop()


def _c() -> None:
    """Stands for the moment a real blpapi call spends outside the interpreter lock."""
    if _YIELD["on"]:
        _NOOP()


class Name(object):
    def __init__(self, text):
        self.text = str(text)

    def __str__(self):
        return self.text

    def __repr__(self):
        return "Name(%r)" % self.text

    def __eq__(self, other):
        return str(other) == self.text

    def __hash__(self):
        return hash(self.text)


class CorrelationId(object):
    def __init__(self, value=None):
        self._value = value

    def value(self):
        _c()
        return self._value


class SessionOptions(object):
    def __init__(self):
        self.settings: Dict[str, Any] = {}

    def __getattr__(self, name):
        if name.startswith("set"):
            def setter(value):
                self.settings[name[3:]] = value
            return setter
        raise AttributeError(name)


class Element(object):
    """Value tree: dict = sequence, list = array, anything else = scalar (``None`` = null)."""

    def __init__(self, name, value):
        self._name = Name(name)
        self._value = value

    def name(self):
        return self._name

    def isArray(self):
        return isinstance(self._value, list)

    def isComplexType(self):
        return isinstance(self._value, dict)

    def isNull(self):
        _c()
        return self._value is None

    def numValues(self):
        _c()
        if isinstance(self._value, list):
            return len(self._value)
        return 0 if self._value is None else 1

    def numElements(self):
        _c()
        return len(self._value) if isinstance(self._value, dict) else 0

    def getValue(self, index=0):
        _c()
        _c()                                    # the real one asks for the data type first
        if isinstance(self._value, list):
            return self._value[index]
        if index != 0:
            raise IndexError(index)
        return self._value

    def getValueAsElement(self, index=0):
        _c()
        v = self._value[index] if isinstance(self._value, list) else self._value
        return Element(self._name, v)

    def hasElement(self, name, excludeNullElements=False):
        _c()
        if not (isinstance(self._value, dict) and str(name) in self._value):
            return False
        return not (excludeNullElements and self._value[str(name)] is None)

    def getElement(self, name):
        _c()
        if isinstance(name, int):
            key = list(self._value.keys())[name]
            return Element(key, self._value[key])
        if not (isinstance(self._value, dict) and str(name) in self._value):
            raise KeyError(str(name))
        return Element(str(name), self._value[str(name)])

    def getElementAsString(self, name):
        _c()
        _c()
        return str(self._value[str(name)])

    def getElementAsFloat(self, name):
        _c()
        _c()
        v = self._value[str(name)]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError("%s is not a number" % (name,))
        return float(v)

    def elements(self):
        return [Element(k, v) for k, v in self._value.items()] if isinstance(self._value, dict) else []

    def values(self):
        return list(self._value) if isinstance(self._value, list) else [self._value]

    # ---- request building
    def appendElement(self):
        item: Dict[str, Any] = {}
        self._value.append(item)
        return Element(self._name, item)

    def setElement(self, name, value):
        self._value[str(name)] = value

    def __str__(self):
        return "%s = %r" % (self._name, self._value)


class Message(object):
    def __init__(self, message_type: str, cids: List[Any], data: Dict[str, Any]):
        self._type = Name(message_type)
        self._cids = [CorrelationId(c) for c in cids]
        self._data = data

    def messageType(self):
        _c()
        return self._type

    def correlationIds(self):
        _c()
        for _ in self._cids:
            _c()
        return list(self._cids)

    def asElement(self):
        _c()
        return Element(str(self._type), self._data)

    def hasElement(self, name, excludeNullElements=False):
        return self.asElement().hasElement(name, excludeNullElements)

    def getElement(self, name):
        return self.asElement().getElement(name)

    def __str__(self):
        return "%s %r" % (self._type, self._data)


class Event(object):
    ADMIN = 1
    SESSION_STATUS = 2
    SUBSCRIPTION_STATUS = 3
    REQUEST_STATUS = 4
    RESPONSE = 5
    PARTIAL_RESPONSE = 6
    SUBSCRIPTION_DATA = 8
    SERVICE_STATUS = 9
    TIMEOUT = 10

    def __init__(self, event_type: int, messages: Optional[List[Message]] = None):
        self._type = event_type
        self._messages = messages or []

    def eventType(self):
        _c()
        return self._type

    def __iter__(self):
        _c()
        for m in self._messages:
            _c()
            yield m
        _c()


class Request(object):
    def __init__(self, operation: str):
        self.operation = operation
        self.data: Dict[str, Any] = {"securities": [], "fields": [], "overrides": []}

    def append(self, name, value):
        self.data.setdefault(str(name), []).append(value)

    def set(self, name, value):
        self.data[str(name)] = value

    def getElement(self, name):
        return Element(str(name), self.data.setdefault(str(name), []))


class Service(object):
    def __init__(self, name: str):
        self.name = name

    def createRequest(self, operation: str) -> Request:
        return Request(operation)


class SubscriptionList(object):
    def __init__(self):
        self.entries: List[Tuple[str, List[str], Any, CorrelationId]] = []

    def add(self, topic, fields=None, options=None, correlationId=None):
        if isinstance(fields, str):
            fields = [f for f in fields.split(",") if f]
        self.entries.append((topic, list(fields or []), options, correlationId or CorrelationId()))

    def size(self):
        return len(self.entries)


class Server(object):
    """The pretend Bloomberg back end shared by every fake session."""

    def __init__(self):
        self.ref: Dict[Tuple[str, str, Tuple], Any] = {}          # (security, FIELD, overrides) -> value | rows
        self.history: Dict[Tuple[str, str], List[Tuple[_dt.date, float]]] = {}
        self.history_exact: Dict[Tuple[str, str, str, str], List[Tuple[_dt.date, Any]]] = {}   # canned answers per range
        self.rt: Dict[Tuple[str, str], float] = {}                # (security, RT field) -> value of the first paint
        self.invalid: set = set()                                 # unknown securities
        self.not_applicable: set = set()                          # (security, FIELD) refused as not applicable
        self.bad_rt_fields: set = set()                           # RT fields a subscription refuses
        self.fail_start = False
        self.services = {"//blp/refdata", "//blp/mktdata"}
        self.requests: List[Dict[str, Any]] = []                  # log of everything that was asked
        self.subscriptions: List[Tuple[str, List[str]]] = []
        self.sessions: List["Session"] = []
        self.lock = threading.Lock()
        self.split_responses = False                              # answer with PARTIAL_RESPONSE + RESPONSE
        self.silent = False                                       # swallow requests (timeouts)
        self.strict_ids = True                                    # refuse spellings only Excel understands
        self.subscription_options: List[Tuple[str, List[str]]] = []   # (topic, options) of every subscribe
        self.refuse_options = False                               # subscriptions that carry options fail
        self.queue_limit = 0                                      # undelivered events a session holds (0: no limit)
        self.dropped = 0                                          # events thrown away because the queue was full

    @property
    def release_gil(self) -> bool:
        return _YIELD["on"]

    @release_gil.setter
    def release_gil(self, on: bool) -> None:
        _YIELD["on"] = bool(on)

    # ---- securities
    def unknown(self, sec: str) -> bool:
        """Would the API say "invalid security"?"""
        if self.strict_ids and excel_only(sec):
            return True
        return any(name in self.invalid for name in spellings(sec))

    def stored(self, table: Dict, sec: str, *rest) -> Any:
        """The entry of ``table`` for a security, whichever way the test spelled it."""
        for name in spellings(sec):
            v = table.get((name,) + rest)
            if v is not None:
                return v
        return None

    # ---- helpers for tests
    def tick(self, security: str, values: Dict[str, Any]) -> None:
        for s in list(self.sessions):
            s.push_tick(security, values)

    def admin(self, message_type: str, data: Optional[Dict[str, Any]] = None, security: Optional[str] = None) -> None:
        """An ADMIN event (``SlowConsumerWarning`` ...), for a subscription when ``security`` is given."""
        for s in list(self.sessions):
            sub = s.subs.get(security) if security is not None else None
            cids = [sub[1]] if sub is not None else []
            s.events.put(Event(Event.ADMIN, [Message(message_type, cids, dict(data or {}))]))

    def drop_sessions(self) -> None:
        """The terminal goes away: every session is told it was terminated."""
        for s in list(self.sessions):
            s.subs.clear()
            s.events.put(Event(Event.SESSION_STATUS, [Message("SessionTerminated", [], {})]))

    def hits(self) -> int:
        return sum(len(r["securities"]) * max(1, len(r["fields"])) for r in self.requests)

    # ---- request handling
    def answer(self, request: Request) -> List[Message]:
        d = request.data
        ov = tuple(sorted((str(o["fieldId"]), str(o["value"])) for o in d.get("overrides", [])))
        self.requests.append({"op": request.operation, "securities": list(d["securities"]), "fields": list(d["fields"]),
                              "overrides": ov, "options": {k: v for k, v in d.items() if k not in ("securities", "fields", "overrides")}})
        if request.operation == "ReferenceDataRequest":
            out = []
            for sec in d["securities"]:
                if self.unknown(sec):
                    out.append({"security": sec, "securityError": {"source": "fake", "code": 15, "category": "BAD_SEC",
                                                                    "message": "Unknown/Invalid security", "subcategory": "INVALID_SECURITY"},
                                "fieldExceptions": [], "fieldData": {}})
                    continue
                fd: Dict[str, Any] = {}
                exc = []
                for f in d["fields"]:
                    if any((name, f) in self.not_applicable for name in spellings(sec)):
                        exc.append({"fieldId": f, "errorInfo": {"source": "fake", "code": 9, "category": "BAD_FLD",
                                                                "message": "Field not applicable to security",
                                                                "subcategory": "NOT_APPLICABLE_TO_REF_DATA"}})
                        continue
                    v = self.stored(self.ref, sec, f, ov)
                    if v is not None:
                        fd[f] = v
                out.append({"security": sec, "fieldData": fd, "fieldExceptions": exc})
            return [Message("ReferenceDataResponse", [], {"securityData": out})]
        if request.operation == "HistoricalDataRequest":
            msgs = []
            field = d["fields"][0]
            start = _dt.datetime.strptime(d["startDate"], "%Y%m%d").date()
            end = _dt.datetime.strptime(d["endDate"], "%Y%m%d").date()
            for sec in d["securities"]:
                if self.unknown(sec):
                    msgs.append(Message("HistoricalDataResponse", [], {"securityData": {
                        "security": sec, "securityError": {"category": "BAD_SEC", "subcategory": "INVALID_SECURITY"}, "fieldData": []}}))
                    continue
                canned = self.stored(self.history_exact, sec, field, d["startDate"], d["endDate"])
                if canned is not None:
                    rows = [({"date": day} if value is None else {"date": day, field: value}) for day, value in canned]
                    msgs.append(Message("HistoricalDataResponse", [], {"securityData": {"security": sec, "fieldData": rows}}))
                    continue
                known = dict(self.stored(self.history, sec, field) or [])
                rows = []
                day = start
                last = None
                weekdays = d.get("nonTradingDayFillOption") == "NON_TRADING_WEEKDAYS"
                every = d.get("nonTradingDayFillOption") == "ALL_CALENDAR_DAYS"
                fill = d.get("nonTradingDayFillMethod") == "PREVIOUS_VALUE"
                for earlier in sorted(known):
                    if earlier < start:
                        last = known[earlier]
                while day <= end:
                    if day in known:
                        if known[day] is None:
                            rows.append({"date": day})          # a date without a value
                        else:
                            last = known[day]
                            rows.append({"date": day, field: known[day]})
                    elif (every or (weekdays and day.weekday() < 5)) and fill and last is not None:
                        rows.append({"date": day, field: last})
                    day += _dt.timedelta(days=1)
                msgs.append(Message("HistoricalDataResponse", [], {"securityData": {"security": sec, "fieldData": rows}}))
            return msgs
        return [Message("ErrorResponse", [], {"responseError": {"message": "unknown operation"}})]


class Session(object):
    def __init__(self, options=None, server: Optional[Server] = None):
        self.options = options
        self.server = server
        self.events: "queue.Queue[Event]" = queue.Queue()
        self.subs: Dict[str, Tuple[List[str], Any]] = {}
        self.started = False
        self._slow = False                        # a SlowConsumerWarning is out
        self._dropped = 0                         # ... events dropped since then
        self._lost: Dict[Any, int] = {}           # ... per correlation id of a subscription

    # ---- the bounded event queue of the real session
    def _put(self, event: Event) -> None:
        limit = self.server.queue_limit
        if not limit:
            self.events.put(event)
            return
        n = self.events.qsize()
        if n >= limit:                            # "event queue is full, events are being dropped"
            self._dropped += 1
            self.server.dropped += 1
            for m in event._messages:
                for c in m._cids:
                    self._lost[c._value] = self._lost.get(c._value, 0) + 1
            return
        if n >= 0.75 * limit and not self._slow:
            self._slow = True
            self.events.put(Event(Event.ADMIN, [Message("SlowConsumerWarning", [], {})]))
        self.events.put(event)

    def _after_get(self) -> None:
        limit = self.server.queue_limit
        if limit and self._slow and self.events.qsize() <= 0.5 * limit:
            self._slow = False
            lost, self._lost = self._lost, {}
            dropped, self._dropped = self._dropped, 0
            for cid, count in lost.items():
                self.events.put(Event(Event.ADMIN, [Message("DataLoss", [cid], {
                    "id": str(cid), "source": "fake", "numMessagesDropped": count})]))
            self.events.put(Event(Event.ADMIN, [Message("SlowConsumerWarningCleared", [], {"eventsDropped": dropped})]))

    def start(self):
        if self.server.fail_start:
            return False
        self.started = True
        self.server.sessions.append(self)
        self.events.put(Event(Event.SESSION_STATUS, [Message("SessionStarted", [], {})]))
        return True

    def stop(self):
        self.started = False
        if self in self.server.sessions:
            self.server.sessions.remove(self)

    def openService(self, name):
        return name in self.server.services

    def getService(self, name):
        return Service(name)

    def sendRequest(self, request, correlationId=None, **kwargs):
        cid = correlationId.value() if correlationId is not None else None
        with self.server.lock:
            messages = self.server.answer(request)
        if self.server.silent:
            return correlationId
        for m in messages:
            m._cids = [CorrelationId(cid)]
        if self.server.split_responses and len(messages) == 1 and request.operation == "ReferenceDataRequest":
            data = messages[0]._data["securityData"]
            half = max(1, len(data) // 2)
            first = Message("ReferenceDataResponse", [cid], {"securityData": data[:half]})
            second = Message("ReferenceDataResponse", [cid], {"securityData": data[half:]})
            self._put(Event(Event.PARTIAL_RESPONSE, [first]))
            self._put(Event(Event.RESPONSE, [second]))
        else:
            for m in messages[:-1]:
                self._put(Event(Event.PARTIAL_RESPONSE, [m]))
            self._put(Event(Event.RESPONSE, [messages[-1]]))
        return correlationId

    def subscribe(self, sublist: SubscriptionList):
        for topic, fields, options, cid in sublist.entries:
            self._subscribe(topic, fields, cid, options)

    def resubscribe(self, sublist: SubscriptionList):
        self.subscribe(sublist)

    def _subscribe(self, topic, fields, cid, options=None):
        self.server.subscriptions.append((topic, list(fields)))
        self.server.subscription_options.append((topic, list(options or [])))
        unknown = self.server.unknown(topic)
        if unknown or (options and self.server.refuse_options):
            self._put(Event(Event.SUBSCRIPTION_STATUS, [Message("SubscriptionFailure", [cid._value], {
                "reason": {"category": "BAD_SEC" if unknown else "NOT_AUTHORIZED",
                           "description": "Invalid security" if unknown else "option refused"}})]))
            return
        self.subs[topic] = (list(fields), cid._value)
        bad = [f for f in fields if f in self.server.bad_rt_fields]
        data: Dict[str, Any] = {}
        if bad:
            data["exceptions"] = [{"fieldId": f, "reason": {"category": "BAD_FLD", "description": "not a real-time field"}} for f in bad]
        self._put(Event(Event.SUBSCRIPTION_STATUS, [Message("SubscriptionStarted", [cid._value], data)]))
        first = {f: self.server.stored(self.server.rt, topic, f) for f in fields if f not in bad}
        first = {f: v for f, v in first.items() if v is not None}
        if first:
            first["MKTDATA_EVENT_TYPE"] = "SUMMARY"
            self._put(Event(Event.SUBSCRIPTION_DATA, [Message("MarketDataEvents", [cid._value], first)]))

    def push_tick(self, security: str, values: Dict[str, Any]):
        sub = next((self.subs[name] for name in spellings(security) if name in self.subs), None)
        if sub is None:
            return
        self._put(Event(Event.SUBSCRIPTION_DATA, [Message("MarketDataEvents", [sub[1]], dict(values))]))

    def nextEvent(self, timeout=0):
        try:
            event = self.events.get(timeout=(timeout or 0) / 1000.0 if timeout else None)
        except queue.Empty:
            return Event(Event.TIMEOUT)
        self._after_get()
        return event


def module(server: Server):
    """A module-like object to pass as ``blpapi_module``."""
    mod = types.SimpleNamespace()
    mod.Name = Name
    mod.CorrelationId = CorrelationId
    mod.SessionOptions = SessionOptions
    mod.Event = Event
    mod.SubscriptionList = SubscriptionList
    mod.Session = lambda options=None: Session(options, server)
    mod.server = server
    return mod
