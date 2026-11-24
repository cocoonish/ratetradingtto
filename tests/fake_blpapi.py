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

Intraday bars (``IntradayBarRequest``) are made up for every security it knows: a session from 09:30 to 18:00
Istanbul time (UTC+3) on week days, the bars laid out from the request's start on, their prices and volumes a fixed
function of the security and the time (:func:`bar_values`: two requests that overlap agree).  The request is checked
the way blpapi checks it (one ``security``, the elements and event types its schema has; times are UTC), an answer
of more than ``server.bar_chunk`` bars comes in parts (``PARTIAL_RESPONSE`` events before the ``RESPONSE``), an
unknown security is a ``responseError``.  A bar that starts exactly at ``endDateTime`` is sent too: the provider
must keep the end out itself.
"""
from __future__ import annotations

import datetime as _dt
import math
import queue
import threading
import time
import types
import zlib
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


#: the elements of an ``IntradayBarRequest`` (blpapi refuses any other name), those it cannot do without, and the
#: values its ``eventType`` takes
BAR_ELEMENTS = frozenset(("security", "eventType", "interval", "startDateTime", "endDateTime", "gapFillInitialBar",
                          "adjustmentNormal", "adjustmentAbnormal", "adjustmentSplit", "adjustmentFollowDPDF",
                          "returnEids"))
BAR_REQUIRED = ("security", "eventType", "interval", "startDateTime", "endDateTime")
BAR_EVENTS = ("TRADE", "BID", "ASK", "BID_BEST", "ASK_BEST", "BEST_BID", "BEST_ASK")
#: the pretend terminal's intraday session, in Istanbul time (UTC+3), on week days
BAR_SESSION = (_dt.time(9, 30), _dt.time(18, 0))
ISTANBUL = _dt.timedelta(hours=3)
_BAR_EPOCH = _dt.datetime(2026, 1, 1)


def bar_values(security: str, start: _dt.datetime, interval: int) -> Tuple[float, float, float, float, int, int]:
    """open, high, low, close, volume and number of events of the pretend terminal's bar of ``security`` that starts
    at ``start`` (UTC) - a fixed function of the security and the time: two requests that overlap get the same bars,
    and a bar closes where the next one opens.  Made-up numbers, nothing of them a real quote."""
    seed = zlib.crc32(str(security).encode("utf-8"))
    level = 20.0 + seed % 4000 / 100.0

    def at(t: _dt.datetime) -> float:
        m = (t - _BAR_EPOCH).total_seconds() / 60.0
        return round(level * (1.0 + 0.01 * math.sin(m / 390.0 + seed % 7) + 0.002 * math.sin(m / 17.0 + seed % 5)), 4)

    o, c = at(start), at(start + _dt.timedelta(minutes=interval))
    m = int((start - _BAR_EPOCH).total_seconds() // 60)
    reach = round(level * 0.0003 * (1 + (seed + m) % 4), 4)
    events = 1 + (seed // 7 + m * 31) % 60
    return o, round(max(o, c) + reach, 4), round(min(o, c) - reach, 4), c, 25 * events, events


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
        self.bars = operation == "IntradayBarRequest"      # names one security, takes no lists
        self.data: Dict[str, Any] = {} if self.bars else {"securities": [], "fields": [], "overrides": []}

    def append(self, name, value):
        if self.bars:                                      # blpapi: NotFoundException / not an array
            raise KeyError("IntradayBarRequest has no list %r" % str(name))
        self.data.setdefault(str(name), []).append(value)

    def set(self, name, value):
        if self.bars:                                      # what blpapi's schema refuses at once
            name = str(name)
            if name not in BAR_ELEMENTS:
                raise KeyError("IntradayBarRequest has no element %r" % name)
            if name == "eventType" and value not in BAR_EVENTS:
                raise ValueError("eventType %r" % (value,))
            if name == "interval" and (type(value) is not int or not 1 <= value <= 1440):
                raise ValueError("interval %r" % (value,))
            if name in ("startDateTime", "endDateTime") and not isinstance(value, _dt.datetime):
                raise TypeError("%s %r" % (name, value))
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
        self.silent = False                                       # swallow requests (timeouts) ...
        self.held: List[Tuple] = []                               # ... their answers, for release() (late answers)
        self.bar_chunk = 1000                                     # bars per message: a longer answer comes in parts
        self.bar_errors: Dict[str, Dict[str, Any]] = {}           # security -> responseError of its bar requests
        self.partials = 0                                         # PARTIAL_RESPONSE events sent
        self.strict_ids = True                                    # refuse spellings only Excel understands
        self.subscription_options: List[Tuple[str, List[str]]] = []   # (topic, options) of every subscribe
        self.refuse_options = False                               # subscriptions that carry options fail
        self.refused: set = set()                                 # securities whose subscription fails (not entitled)
        self.queue_limit = 0                                      # undelivered events a session holds (0: no limit)
        self.dropped = 0                                          # events thrown away because the queue was full
        # Bloomberg's own daily limit (what the desk's terminal said on 24.11.2026): from this many hits on, every
        # request is answered with a ``responseError`` of category LIMIT (None: no limit)
        self.daily_capacity: Optional[int] = None
        self.capacity_said = 0                                    # requests answered with it

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

    def release(self) -> None:
        """The terminal answers, late, what it held back while ``silent``."""
        held, self.held = self.held, []
        for session, cid, operation, messages in held:
            session.respond(cid, operation, messages)

    #: Bloomberg's answer once its daily capacity is used up (as the desk's terminal gave it on 24.11.2026)
    CAPACITY_ERROR = {"source": "rsfrdsvc3", "code": -4001, "category": "LIMIT", "message": "Daily capacity reached.",
                      "subcategory": "DAILY_CAPACITY_REACHED"}

    def over_capacity(self) -> bool:
        return self.daily_capacity is not None and self.hits() >= self.daily_capacity

    # ---- request handling
    def answer(self, request: Request) -> List[Message]:
        if request.operation == "IntradayBarRequest":
            return self.intraday_bars(request)
        d = request.data
        ov = tuple(sorted((str(o["fieldId"]), str(o["value"])) for o in d.get("overrides", [])))
        over = self.over_capacity()
        self.requests.append({"op": request.operation, "securities": list(d["securities"]), "fields": list(d["fields"]),
                              "overrides": ov, "options": {k: v for k, v in d.items() if k not in ("securities", "fields", "overrides")}})
        if over:
            self.capacity_said += 1
            kind = "ReferenceDataResponse" if request.operation == "ReferenceDataRequest" else "HistoricalDataResponse"
            return [Message(kind, [], {"responseError": dict(self.CAPACITY_ERROR)})]
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
                    if callable(v):
                        v = v()                                  # an answer that changes from request to request
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

    def intraday_bars(self, request: Request) -> List[Message]:
        """The bars of an ``IntradayBarRequest`` (see the module text), logged as a request for one security."""
        d = request.data
        sec = d.get("security")
        self.requests.append({"op": request.operation, "securities": [sec], "fields": [], "overrides": (),
                              "options": {k: v for k, v in d.items() if k != "security"}})

        def error(category, subcategory, message, code):
            return [Message("IntradayBarResponse", [], {"responseError": {
                "source": "fake", "code": code, "category": category, "message": message, "subcategory": subcategory}})]

        missing = [name for name in BAR_REQUIRED if name not in d]
        if missing:
            return error("BAD_ARGS", "", "Missing %s" % ", ".join(missing), 2)
        if self.unknown(sec):
            return error("BAD_SEC", "INVALID_SECURITY", "Unknown/Invalid security [nid:fake]", 3)
        canned = next((self.bar_errors[name] for name in spellings(sec) if name in self.bar_errors), None)
        if canned is not None:
            return [Message("IntradayBarResponse", [], {"responseError": dict(canned)})]
        step = _dt.timedelta(minutes=d["interval"])
        bars = []
        t = d["startDateTime"]
        while t <= d["endDateTime"]:                     # (a bar that starts at the end too: see the module text)
            local = t + ISTANBUL
            if local.weekday() < 5 and BAR_SESSION[0] <= local.time() < BAR_SESSION[1]:
                o, h, lo, c, volume, events = bar_values(sec, t, d["interval"])
                bars.append({"time": t, "open": o, "high": h, "low": lo, "close": c, "volume": volume,
                             "numEvents": events, "value": round(c * volume, 2)})
            t += step
        size = max(1, int(self.bar_chunk))
        parts = [bars[i:i + size] for i in range(0, len(bars), size)] or [[]]
        return [Message("IntradayBarResponse", [], {"barData": {"eidData": [], "delayedSecurity": False,
                                                                 "barTickData": part}}) for part in parts]


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
            self.server.held.append((self, cid, request.operation, messages))
            return correlationId
        self.respond(cid, request.operation, messages)
        return correlationId

    def respond(self, cid, operation: str, messages: List[Message]) -> None:
        """The answer of a request: every message but the last in a ``PARTIAL_RESPONSE`` event."""
        for m in messages:
            m._cids = [CorrelationId(cid)]
        if self.server.split_responses and len(messages) == 1 and operation == "ReferenceDataRequest":
            data = messages[0]._data["securityData"]
            half = max(1, len(data) // 2)
            first = Message("ReferenceDataResponse", [cid], {"securityData": data[:half]})
            second = Message("ReferenceDataResponse", [cid], {"securityData": data[half:]})
            messages = [first, second]
        for m in messages[:-1]:
            self.server.partials += 1
            self._put(Event(Event.PARTIAL_RESPONSE, [m]))
        self._put(Event(Event.RESPONSE, [messages[-1]]))

    def subscribe(self, sublist: SubscriptionList):
        for topic, fields, options, cid in sublist.entries:
            self._subscribe(topic, fields, cid, options)

    def resubscribe(self, sublist: SubscriptionList):
        self.subscribe(sublist)

    def _subscribe(self, topic, fields, cid, options=None):
        self.server.subscriptions.append((topic, list(fields)))
        self.server.subscription_options.append((topic, list(options or [])))
        unknown = self.server.unknown(topic)
        if unknown or (options and self.server.refuse_options) or any(n in self.server.refused for n in spellings(topic)):
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
