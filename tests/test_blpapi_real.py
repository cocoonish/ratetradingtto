"""Checks against the real ``blpapi`` package - skipped where it is not installed.

No terminal is needed: blpapi's own test helpers (``blpapi.test``) build real events and messages, so the
exact calls the provider makes on them are exercised with the real library.  Worth running once on the
desk machine after an upgrade of blpapi:

    python -m pytest tests/test_blpapi_real.py -q
"""
import sys
import threading
import time

import pytest

blpapi = pytest.importorskip("blpapi")

from tto.marketdata.base import bdp_key  # noqa: E402
from tto.marketdata.bbg_process import IsolatedBloombergProvider, IsolationError  # noqa: E402
from tto.marketdata.bloomberg import BloombergProvider  # noqa: E402

GIL = getattr(sys, "_is_gil_enabled", lambda: True)()

FLOATS = ["BID", "ASK", "MID", "LAST_PRICE", "HIGH", "LOW"] + ["FILLER_%02d" % i for i in range(40)]
SCHEMA = """<?xml version="1.0" encoding="UTF-8" ?>
<ServiceDefinition name="blp.mktdata" version="1.0.1.0">
   <service name="//blp/mktdata" version="1.0.0.0" authorizationService="//blp/apiauth">
      <event name="MarketDataEvents" eventType="MarketDataUpdate">
         <eventId>0</eventId><eventId>1</eventId><eventId>9999</eventId>
      </event>
      <defaultServiceId>134217729</defaultServiceId>
      <resolutionService></resolutionService>
      <recapEventId>9999</recapEventId>
   </service>
   <schema>
      <sequenceType name="MarketDataUpdate">
         <description>fields in subscription</description>
%s
         <element name="BID_SIZE" type="Int32" id="901" minOccurs="0" maxOccurs="1"><description>x</description></element>
         <element name="ASK_SIZE" type="Int64" id="902" minOccurs="0" maxOccurs="1"><description>x</description></element>
         <element name="MKTDATA_EVENT_TYPE" type="String" id="903" minOccurs="0" maxOccurs="1"><description>x</description></element>
      </sequenceType>
   </schema>
</ServiceDefinition>
""" % "\n".join('         <element name="%s" type="Float64" id="%d" minOccurs="0" maxOccurs="1"><description>x</description></element>'
                % (f, i + 1) for i, f in enumerate(FLOATS))


def subscribed(prov, sec, fields):
    """Register real-time items as the engine would and pretend their subscription has gone out."""
    for f in fields:
        prov._lookup(bdp_key(sec, f), 0.0, f)
    sub = prov._subs[sec]
    sub.sent_fields = set(sub.fields)
    sub.names = tuple((f, prov._name(f)) for f in sorted(sub.fields))
    sub.state = "started"
    return sub


def data_event(cid, contents):
    service = blpapi.test.deserializeService(SCHEMA)
    definition = service.getEventDefinition(blpapi.Name("MarketDataEvents"))
    event = blpapi.test.createEvent(blpapi.Event.SUBSCRIPTION_DATA)
    for content in contents:
        props = blpapi.test.MessageProperties()
        props.setCorrelationIds([blpapi.CorrelationId(cid)])
        blpapi.test.appendMessage(event, definition, props).formatMessageDict(content)
    return event


def admin_event(name, content=None, cid=None, kind=None):
    event = blpapi.test.createEvent(blpapi.Event.ADMIN if kind is None else kind)
    definition = blpapi.test.getAdminMessageDefinition(blpapi.Name(name))
    if cid is None:
        fmt = blpapi.test.appendMessage(event, definition)
    else:
        props = blpapi.test.MessageProperties()
        props.setCorrelationIds([blpapi.CorrelationId(cid)])
        fmt = blpapi.test.appendMessage(event, definition, props)
    if content is not None:
        fmt.formatMessageDict(content)
    return event


def test_a_tick_is_read_with_the_calls_the_provider_makes():
    prov = BloombergProvider(blpapi_module=blpapi)
    sec = "USDTRY Curncy"
    sub = subscribed(prov, sec, ["BID", "ASK", "BID_SIZE", "ASK_SIZE", "LAST_PRICE"])
    event = data_event(sub.cid, [
        {"BID": 49.997, "ASK": 49.9975, "BID_SIZE": 7, "ASK_SIZE": 12, "MKTDATA_EVENT_TYPE": "QUOTE"},
        {"ASK": 50.01, "FILLER_03": 1.5},                           # only one of the fields that are watched
        {"MKTDATA_EVENT_TYPE": "SUMMARY"},                          # none of them
    ])
    for msg in event:
        prov._on_tick(msg)
    get = lambda f: prov._values.get(bdp_key(sec, f))  # noqa: E731
    assert (get("BID"), get("ASK"), get("BID_SIZE"), get("ASK_SIZE"), get("LAST_PRICE")) == (49.997, 50.01, 7.0, 12.0, None)
    assert type(get("BID_SIZE")) is float and prov.ticks == 3
    assert sorted(prov.drain_changes()) == sorted(bdp_key(sec, f) for f in ("BID", "ASK", "BID_SIZE", "ASK_SIZE"))
    # a field that is watched but carries text is skipped, not an error
    text = subscribed(BloombergProvider(blpapi_module=blpapi), sec, ["BID"])
    other = BloombergProvider(blpapi_module=blpapi)
    sub2 = subscribed(other, sec, ["BID"])
    sub2.names = sub2.names + (("MKTDATA_EVENT_TYPE", other._name("MKTDATA_EVENT_TYPE")),)
    for msg in data_event(sub2.cid, [{"BID": 51.0, "MKTDATA_EVENT_TYPE": "QUOTE"}]):
        other._on_tick(msg)
    assert other._values.get(bdp_key(sec, "BID")) == 51.0 and other.last_error == "" and text is not None


def test_what_the_session_says_about_its_queue_is_understood():
    prov = BloombergProvider(blpapi_module=blpapi)
    sub = subscribed(prov, "USDTRY Curncy", ["BID"])
    for msg in admin_event("SlowConsumerWarning"):
        prov._on_admin(msg)
    assert prov.slow and prov.slow_warnings == 1
    for msg in admin_event("DataLoss", {"id": "x", "source": "test", "numMessagesDropped": 5}, cid=sub.cid):
        prov._on_admin(msg)
    assert prov.messages_lost == 5 and prov._resync == {"USDTRY Curncy"}
    for msg in admin_event("SlowConsumerWarningCleared", {"eventsDropped": 123}):
        prov._on_admin(msg)
    assert not prov.slow and prov.events_dropped == 123 and prov._resync_all
    st = prov.status()
    assert st["events_dropped"] == 123 and st["messages_lost"] == 5 and st["slow_warnings"] == 1 and not st["slow"]


def test_subscription_status_messages():
    prov = BloombergProvider(blpapi_module=blpapi)
    sub = subscribed(prov, "USDTRY Curncy", ["BID", "ASK"])
    sub.state = "pending"
    content = {"exceptions": [{"fieldId": "ASK", "reason": {"source": "test", "errorCode": 1, "category": "BAD_FLD",
                                                             "description": "not a real-time field", "subcategory": "x"}}],
               "resubscriptionId": 1, "streamIds": ["1"], "receivedFrom": {"address": "localhost:8194"}, "reason": "test"}
    for msg in admin_event("SubscriptionStarted", content, cid=sub.cid, kind=blpapi.Event.SUBSCRIPTION_STATUS):
        prov._on_sub_status(msg)
    assert sub.state == "started" and sub.bad == {"ASK"}
    failure = {"reason": {"source": "test", "errorCode": 2, "category": "BAD_SEC", "description": "Invalid security",
                          "subcategory": "INVALID_SECURITY"}, "failureDetails": [], "resubscriptionId": 1}
    for msg in admin_event("SubscriptionFailure", failure, cid=sub.cid, kind=blpapi.Event.SUBSCRIPTION_STATUS):
        prov._on_sub_status(msg)
    assert sub.state == "failed"


def test_session_options_and_subscription_strings():
    opts = blpapi.SessionOptions()
    assert opts.maxEventQueueSize() == 10000 and abs(opts.slowConsumerWarningHiWaterMark() - 0.75) < 1e-6
    opts.setMaxEventQueueSize(100000)                    # what _open_session asks for
    assert opts.maxEventQueueSize() == 100000
    lst = blpapi.SubscriptionList()
    lst.add("USDTRY Curncy", ["ASK", "BID"], ["interval=1"], blpapi.CorrelationId(7))
    lst.add("TYSO1 Curncy", ["MID"], [], blpapi.CorrelationId(8))
    assert lst.size() == 2
    assert lst.topicStringAt(0) == "USDTRY Curncy?fields=ASK,BID&interval=1"
    assert lst.topicStringAt(1) == "TYSO1 Curncy?fields=MID"
    assert lst.correlationIdAt(0).value() == 7
    assert blpapi.Event.ADMIN != blpapi.Event.SUBSCRIPTION_DATA      # the reader tells them apart by these


@pytest.mark.skipif(not GIL, reason="needs the interpreter lock")
def test_reading_next_to_a_computing_thread_is_many_times_slower():
    """The reason the session runs in a helper process, measured with the real library."""
    prov = BloombergProvider(blpapi_module=blpapi)
    sub = subscribed(prov, "USDTRY Curncy", ["BID", "ASK", "BID_SIZE", "ASK_SIZE"])
    event = data_event(sub.cid, [{"BID": 40.0 + i * 0.001, "ASK": 40.1, "BID_SIZE": 5, "ASK_SIZE": 6,
                                  "FILLER_01": 1.0, "FILLER_02": 2.0} for i in range(20)])

    def per_message(rounds):
        t0 = time.perf_counter()
        n = 0
        for _ in range(rounds):
            for msg in event:
                prov._on_tick(msg)
                n += 1
        return (time.perf_counter() - t0) / n

    alone = per_message(50)
    stop = threading.Event()

    def spin():
        x = 0
        while not stop.is_set():
            for i in range(5000):
                x = (x * 31 + i) % 1000003

    t = threading.Thread(target=spin, daemon=True)
    t.start()
    try:
        busy = per_message(2)
    finally:
        stop.set()
        t.join()
    print("\nblpapi %s: %.0f us a message alone, %.1f ms next to a computing thread (x%.0f)" % (
        blpapi.__version__, alone * 1e6, busy * 1e3, busy / alone))
    assert alone < 0.002
    assert busy > 5 * alone


def test_no_terminal_with_the_real_library():
    """Nothing listens on the port: the same plain error in-process and through the helper process."""
    inproc = BloombergProvider(port=1, blpapi_module=blpapi)
    with pytest.raises(RuntimeError) as err:
        inproc.start()
    assert "Bloomberg oturumu açılamadı" in str(err.value)
    helper = IsolatedBloombergProvider(port=1, start_timeout=120)
    try:
        with pytest.raises(RuntimeError) as err:
            helper.start()
        assert not isinstance(err.value, IsolationError) and "Bloomberg oturumu açılamadı" in str(err.value)
    finally:
        helper.stop()
