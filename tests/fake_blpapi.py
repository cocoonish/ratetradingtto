"""A small stand-in for the ``blpapi`` package: just enough of its API to exercise
:class:`tto.marketdata.bloomberg.BloombergProvider` without a Bloomberg terminal.

The "terminal" is a :class:`Server` object the test fills with data:

    server = fake_blpapi.Server()
    server.ref[("USDTRY Curncy", "BID", ())] = 49.997
    server.history[("USDTRY Curncy", "PX_LAST")] = [(date(2026, 11, 2), 49.9), ...]
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))
"""
from __future__ import annotations

import datetime as _dt
import queue
import threading
import types
from typing import Any, Dict, List, Optional, Tuple


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
        return self._value is None

    def numValues(self):
        if isinstance(self._value, list):
            return len(self._value)
        return 0 if self._value is None else 1

    def numElements(self):
        return len(self._value) if isinstance(self._value, dict) else 0

    def getValue(self, index=0):
        if isinstance(self._value, list):
            return self._value[index]
        if index != 0:
            raise IndexError(index)
        return self._value

    def getValueAsElement(self, index=0):
        v = self._value[index] if isinstance(self._value, list) else self._value
        return Element(self._name, v)

    def hasElement(self, name, excludeNullElements=False):
        return isinstance(self._value, dict) and str(name) in self._value

    def getElement(self, name):
        if isinstance(name, int):
            key = list(self._value.keys())[name]
            return Element(key, self._value[key])
        if not self.hasElement(name):
            raise KeyError(str(name))
        return Element(str(name), self._value[str(name)])

    def getElementAsString(self, name):
        return str(self._value[str(name)])

    def getElementAsFloat(self, name):
        return float(self._value[str(name)])

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
        return self._type

    def correlationIds(self):
        return list(self._cids)

    def asElement(self):
        return Element(str(self._type), self._data)

    def hasElement(self, name, excludeNullElements=False):
        return str(name) in self._data

    def getElement(self, name):
        return Element(str(name), self._data[str(name)])

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
        return self._type

    def __iter__(self):
        return iter(self._messages)


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

    # ---- helpers for tests
    def tick(self, security: str, values: Dict[str, Any]) -> None:
        for s in list(self.sessions):
            s.push_tick(security, values)

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
                if sec in self.invalid:
                    out.append({"security": sec, "securityError": {"source": "fake", "code": 15, "category": "BAD_SEC",
                                                                    "message": "Unknown/Invalid security", "subcategory": "INVALID_SECURITY"},
                                "fieldExceptions": [], "fieldData": {}})
                    continue
                fd: Dict[str, Any] = {}
                exc = []
                for f in d["fields"]:
                    if (sec, f) in self.not_applicable:
                        exc.append({"fieldId": f, "errorInfo": {"source": "fake", "code": 9, "category": "BAD_FLD",
                                                                "message": "Field not applicable to security",
                                                                "subcategory": "NOT_APPLICABLE_TO_REF_DATA"}})
                        continue
                    v = self.ref.get((sec, f, ov))
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
                if sec in self.invalid:
                    msgs.append(Message("HistoricalDataResponse", [], {"securityData": {
                        "security": sec, "securityError": {"category": "BAD_SEC", "subcategory": "INVALID_SECURITY"}, "fieldData": []}}))
                    continue
                canned = self.history_exact.get((sec, field, d["startDate"], d["endDate"]))
                if canned is not None:
                    rows = [({"date": day} if value is None else {"date": day, field: value}) for day, value in canned]
                    msgs.append(Message("HistoricalDataResponse", [], {"securityData": {"security": sec, "fieldData": rows}}))
                    continue
                known = dict(self.history.get((sec, field), []))
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
            self.events.put(Event(Event.PARTIAL_RESPONSE, [first]))
            self.events.put(Event(Event.RESPONSE, [second]))
        else:
            for m in messages[:-1]:
                self.events.put(Event(Event.PARTIAL_RESPONSE, [m]))
            self.events.put(Event(Event.RESPONSE, [messages[-1]]))
        return correlationId

    def subscribe(self, sublist: SubscriptionList):
        for topic, fields, _options, cid in sublist.entries:
            self._subscribe(topic, fields, cid)

    def resubscribe(self, sublist: SubscriptionList):
        self.subscribe(sublist)

    def _subscribe(self, topic, fields, cid):
        self.server.subscriptions.append((topic, list(fields)))
        if topic in self.server.invalid:
            self.events.put(Event(Event.SUBSCRIPTION_STATUS, [Message("SubscriptionFailure", [cid.value()], {
                "reason": {"category": "BAD_SEC", "description": "Invalid security"}})]))
            return
        self.subs[topic] = (list(fields), cid.value())
        bad = [f for f in fields if f in self.server.bad_rt_fields]
        data: Dict[str, Any] = {}
        if bad:
            data["exceptions"] = [{"fieldId": f, "reason": {"category": "BAD_FLD", "description": "not a real-time field"}} for f in bad]
        self.events.put(Event(Event.SUBSCRIPTION_STATUS, [Message("SubscriptionStarted", [cid.value()], data)]))
        first = {f: self.server.rt[(topic, f)] for f in fields if (topic, f) in self.server.rt and f not in bad}
        if first:
            first["MKTDATA_EVENT_TYPE"] = "SUMMARY"
            self.events.put(Event(Event.SUBSCRIPTION_DATA, [Message("MarketDataEvents", [cid.value()], first)]))

    def push_tick(self, security: str, values: Dict[str, Any]):
        sub = self.subs.get(security)
        if sub is None:
            return
        self.events.put(Event(Event.SUBSCRIPTION_DATA, [Message("MarketDataEvents", [sub[1]], dict(values))]))

    def nextEvent(self, timeout=0):
        try:
            return self.events.get(timeout=(timeout or 0) / 1000.0 if timeout else None)
        except queue.Empty:
            return Event(Event.TIMEOUT)


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
