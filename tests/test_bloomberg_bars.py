"""Intraday bars (``IntradayBarRequest``) through the Bloomberg layer: :meth:`BloombergProvider.intraday_bars`.

Against the stand-in for ``blpapi`` (tests/fake_blpapi.py): its pretend terminal makes bars up for 09:30 - 18:00
Istanbul time on week days as a fixed function of the security and the time (``fake_blpapi.bar_values``), checks the
request the way blpapi's schema does (one security, the elements and event types it has), answers a long span in
parts and sends the bar that starts at the end of the span too.  The helper-process path is in
test_bloomberg_process.py.
"""
import datetime as dt
import inspect
import threading
import time

import pytest

import fake_blpapi
from tto.marketdata.base import Provider
from tto.marketdata.bbg_process import IsolatedBloombergProvider
from tto.marketdata.bloomberg import BloombergProvider
from tto.marketdata.replay import ReplayProvider

SPAN = ("2026-11-02 09:30", "2026-11-02 10:00")             # a Monday: six 5-minute bars


def bar(sec, local, interval=5):
    """The pretend terminal's bar of ``sec`` that starts at ``local`` (Istanbul time, UTC+3), as the call returns it."""
    start = dt.datetime.fromisoformat(local) - dt.timedelta(hours=3)
    o, h, lo, c, volume, _events = fake_blpapi.bar_values(sec, start, interval)
    return (local, o, h, lo, c, float(volume))


def bar_requests(server):
    return [r for r in server.requests if r["op"] == "IntradayBarRequest"]


def wait_for(cond, timeout=10.0, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


@pytest.fixture()
def server():
    return fake_blpapi.Server()


@pytest.fixture()
def provider(server):
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    p.start()
    yield p
    p.stop()


def test_a_bar_request_names_one_security_and_asks_in_utc(provider, server):
    """Bloomberg takes one security per IntradayBarRequest, the bar length in minutes, the event type, and the times in
    UTC: Istanbul is UTC+3 all year, so local midnight is 21:00 of the day before."""
    assert provider.intraday_bars("A1Z6 Curncy", *SPAN) is not None
    assert provider.intraday_bars("USDTRY Curncy", "2026-11-03 00:00", "2026-11-03 02:30", interval=1, event="bid") == []
    assert provider.intraday_bars("TRT150328T24 @ISL1 ISIN", "2026-11-02T10:00", "2026-11-02 10:15:00", event="BEST_ASK") is not None
    assert provider.intraday_bars("A1F7 Curncy", "2026-11-02", "2026-11-03") is not None          # a day: from midnight
    asked = bar_requests(server)
    assert [(r["securities"], r["options"]) for r in asked] == [
        (["A1Z6 Curncy"], {"eventType": "TRADE", "interval": 5, "startDateTime": dt.datetime(2026, 11, 2, 6, 30),
                           "endDateTime": dt.datetime(2026, 11, 2, 7, 0)}),
        (["USDTRY Curncy"], {"eventType": "BID", "interval": 1, "startDateTime": dt.datetime(2026, 11, 2, 21, 0),
                             "endDateTime": dt.datetime(2026, 11, 2, 23, 30)}),
        (["/isin/TRT150328T24@ISL1"], {"eventType": "BEST_ASK", "interval": 5,              # the API's spelling of an ISIN
                                       "startDateTime": dt.datetime(2026, 11, 2, 7, 0),
                                       "endDateTime": dt.datetime(2026, 11, 2, 7, 15)}),
        (["A1F7 Curncy"], {"eventType": "TRADE", "interval": 5, "startDateTime": dt.datetime(2026, 11, 1, 21, 0),
                           "endDateTime": dt.datetime(2026, 11, 2, 21, 0)}),
    ]
    assert all(r["fields"] == [] for r in asked)                       # no list of securities / fields at all
    assert provider.status()["error"] == ""


def test_bars_come_back_in_istanbul_time_oldest_first_without_the_end(provider, server):
    got = provider.intraday_bars("A1Z6 Curncy", "2026-11-02 09:30", "2026-11-02 09:45")
    assert got == [bar("A1Z6 Curncy", "2026-11-02 09:30"), bar("A1Z6 Curncy", "2026-11-02 09:35"),
                   bar("A1Z6 Curncy", "2026-11-02 09:40")]
    assert all(type(x) is float for row in got for x in row[1:])          # (Bloomberg's volume is an integer)
    o, h, lo, c, volume = got[0][1:]
    assert lo <= min(o, c) <= max(o, c) <= h and volume > 0
    # the pretend terminal sent the 09:45 bar too: the end is not part of the span, whatever the terminal does
    request = fake_blpapi.Request("IntradayBarRequest")
    for name, value in (("security", "A1Z6 Curncy"), ("eventType", "TRADE"), ("interval", 5),
                        ("startDateTime", dt.datetime(2026, 11, 2, 6, 30)), ("endDateTime", dt.datetime(2026, 11, 2, 6, 45))):
        request.set(name, value)
    assert server.answer(request)[0].asElement().getElement("barData").getElement("barTickData").numValues() == 4
    # over a weekend: Friday's last bars, then Monday's first; Saturday and Sunday have none
    got = provider.intraday_bars("A1Z6 Curncy", "2026-11-06 17:50", "2026-11-09 09:40")
    assert [b[0] for b in got] == ["2026-11-06 17:50", "2026-11-06 17:55", "2026-11-09 09:30", "2026-11-09 09:35"]
    assert got[2] == bar("A1Z6 Curncy", "2026-11-09 09:30")
    assert provider.intraday_bars("A1Z6 Curncy", "2026-11-07 00:00", "2026-11-09 00:00") == []     # Bloomberg has none
    assert provider.intraday_bars("A1Z6 Curncy", "2026-11-02 09:30", "2026-11-02 09:32", interval=1) == [
        bar("A1Z6 Curncy", "2026-11-02 09:30", 1), bar("A1Z6 Curncy", "2026-11-02 09:31", 1)]
    assert provider.status()["error"] == ""


def test_a_long_span_comes_in_parts_and_is_put_together(provider, server):
    """Twenty business days of 5-minute bars - what the VİOP page asks for first - are 2 040 bars: Bloomberg sends a
    long answer in several messages, PARTIAL_RESPONSE events before the final RESPONSE.  Still one request, one hit."""
    server.bar_chunk = 500
    got = provider.intraday_bars("A1Z6 Curncy", "2026-10-19 00:00", "2026-11-14 00:00")
    assert server.partials == 4                                          # five messages
    assert len(got) == 20 * 102 and len({b[0] for b in got}) == len(got)
    assert [b[0] for b in got] == sorted(b[0] for b in got)
    assert got[0] == bar("A1Z6 Curncy", "2026-10-19 09:30") and got[-1] == bar("A1Z6 Curncy", "2026-11-13 17:55")
    assert got[101] == bar("A1Z6 Curncy", "2026-10-19 17:55") and got[102] == bar("A1Z6 Curncy", "2026-10-20 09:30")
    assert len(bar_requests(server)) == 1 and provider.status()["hits_today"] == 1 == server.hits()
    # asked again: the same bars (nothing is kept - asked afresh, one hit more)
    assert provider.intraday_bars("A1Z6 Curncy", "2026-10-19 00:00", "2026-11-14 00:00") == got
    assert provider.status()["hits_today"] == 2


def test_each_bar_request_is_one_hit_and_none_is_sent_at_the_daily_limit(server):
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), max_hits_per_day=2)
    p.start()
    try:
        assert len(p.intraday_bars("A1Z6 Curncy", *SPAN)) == 6
        assert len(p.intraday_bars("A1F7 Curncy", *SPAN)) == 6
        assert p.status()["hits_today"] == 2 == server.hits()
        t0 = time.time()
        assert p.intraday_bars("USDTRY Curncy", *SPAN) is None                # the limit: not asked at all
        assert time.time() - t0 < 0.5 and len(bar_requests(server)) == 2 and p.hits == 2
        p.hits_day = dt.date.today() - dt.timedelta(days=1)                  # a new day: the count starts again
        assert wait_for(lambda: p.hits == 0)
        assert len(p.intraday_bars("USDTRY Curncy", *SPAN)) == 6 and p.hits == 1
    finally:
        p.stop()


def test_an_unknown_security_has_no_bars_and_the_status_says_so(provider, server):
    server.invalid.add("A1X9 Curncy")
    assert provider.intraday_bars("A1X9 Curncy", *SPAN) == []
    st = provider.status()
    assert "A1X9 Curncy" in st["error"] and "Invalid security" in st["error"]
    assert st["hits_today"] == 1                                         # Bloomberg was asked


def test_a_limit_or_a_time_out_from_bloomberg_is_not_taken_for_no_bars(provider, server):
    """An empty answer would pass for days without any bars: when Bloomberg's answer says a limit or a time-out the
    call gets None ("ask again later"), as when the provider's own daily count is used up.  Any other error is
    final: no bars.  Bloomberg's own daily limit stops every request after it (24.11.2026: one probe the next day)."""
    server.bar_errors["A1Z6 Curncy"] = {"source": "fake", "code": 9, "category": "LIMIT", "message": "Daily capacity reached"}
    server.bar_errors["A1F7 Curncy"] = {"source": "fake", "code": 10, "category": "UNCLASSIFIED", "subcategory": "TIMEOUT",
                                        "message": "Request timed out"}
    server.bar_errors["A1G7 Curncy"] = {"source": "fake", "code": 2, "category": "BAD_ARGS", "message": "Invalid start"}
    assert provider.intraday_bars("A1F7 Curncy", *SPAN) is None and "timed out" in provider.status()["error"]
    assert provider.intraday_bars("A1G7 Curncy", *SPAN) == [] and "Invalid start" in provider.status()["error"]
    assert provider.intraday_bars("A1Z6 Curncy", *SPAN) is None and "Daily capacity reached" in provider.status()["error"]
    st = provider.status()
    assert st["bbg_limit"] == dt.date.today().isoformat() and st["tier"] == 2 and "günlük limiti doldu" in st["error"]
    hits = server.hits()
    assert provider.intraday_bars("A1X6 Curncy", *SPAN) is None and server.hits() == hits      # nothing more today


def test_an_answer_that_does_not_come_in_time(provider, server):
    """None after ``timeout``.  The call forgets its request, so an answer that comes later is dropped: nothing of it
    stays in the provider or reaches the workbook."""
    server.silent = True
    t0 = time.time()
    assert provider.intraday_bars("A1Z6 Curncy", *SPAN, timeout=0.3) is None
    assert 0.3 <= time.time() - t0 < 2.0
    assert not provider.busy()                                           # nobody waits for that request any more
    server.release()                                                     # ... and now the terminal answers it
    server.silent = False
    # the next call's answer comes after the late one (one event queue): once it is in, the late one was read too
    assert len(provider.intraday_bars("A1Z6 Curncy", *SPAN)) == 6 and provider.status()["hits_today"] == 2
    with provider._lock:
        assert not [k for k in list(provider._items) + list(provider._values) if k[0] == "BAR"]
    assert provider.drain_changes() == [] and not provider.busy() and provider.status()["error"] == ""


def test_a_request_that_times_out_is_sent_again_while_the_call_waits(server):
    """As every request of the provider: unanswered after ``request_timeout``, it is sent again (another hit)."""
    server.silent = True
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), request_timeout=0.3)
    p.start()
    try:
        got = {}
        t = threading.Thread(target=lambda: got.update(bars=p.intraday_bars("A1Z6 Curncy", *SPAN, timeout=20)))
        t.start()
        assert wait_for(lambda: len(bar_requests(server)) >= 2)
        server.silent = False                                            # the next one is answered
        t.join(20)
        assert got["bars"] == [bar("A1Z6 Curncy", "2026-11-02 %s" % hm) for hm in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55")]
        assert p.hits == len(bar_requests(server)) >= 2
    finally:
        p.stop()


def test_what_bloomberg_would_refuse_is_refused_before_asking(provider, server):
    for start, end, interval, event in (("2026-11-02 9:30", "2026-11-02 10:00", 5, "TRADE"),          # not HH:MM
                                        ("02.11.2026 09:30", "2026-11-02 10:00", 5, "TRADE"),
                                        ("2026-11-02 09:30", "", 5, "TRADE"),
                                        ("2026-11-02 09:30", "2026-11-02 10:00", 0, "TRADE"),          # 1 - 1440 minutes
                                        ("2026-11-02 09:30", "2026-11-02 10:00", 1441, "TRADE"),
                                        ("2026-11-02 09:30", "2026-11-02 10:00", 2.5, "TRADE"),
                                        ("2026-11-02 09:30", "2026-11-02 10:00", 5, "MID")):           # not an event type
        with pytest.raises(ValueError):
            provider.intraday_bars("A1Z6 Curncy", start, end, interval=interval, event=event)
    assert provider.intraday_bars("A1Z6 Curncy", "2026-11-02 10:00", "2026-11-02 10:00") == []        # an empty span
    assert provider.intraday_bars("A1Z6 Curncy", "2026-11-02 10:00", "2026-11-02 09:30") == []        # ... asks nothing
    assert server.requests == [] and provider.hits == 0


def test_calls_side_by_side_get_their_own_answers(provider, server):
    """The VİOP page may ask for its three series at once: every call is a request of its own - the same span of the
    same security twice too - and gets its own answer."""
    secs = ["A1Z6 Curncy", "A1F7 Curncy", "USDTRY Curncy", "A1Z6 Curncy"]
    got = [None] * len(secs)

    def ask(i):
        got[i] = provider.intraday_bars(secs[i], "2026-11-02 09:30", "2026-11-02 12:00", timeout=20)

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(len(secs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    for sec, bars in zip(secs, got):
        assert bars is not None and len(bars) == 30 and bars[0] == bar(sec, "2026-11-02 09:30")
    assert got[0] == got[3] and got[0] != got[1]
    assert len(bar_requests(server)) == 4 and provider.status()["hits_today"] == 4


def test_every_provider_has_the_call_and_those_without_bars_answer_none():
    """The VİOP page feature-detects ``getattr(provider, "intraday_bars", None)``: one signature everywhere, and the saved
    data (replay) or a provider without bars answer None ("cannot ask"), not an empty list."""
    sig = inspect.signature(Provider.intraday_bars)
    assert str(sig) == ("(self, security: 'str', start: 'str', end: 'str', interval: 'int' = 5, event: 'str' = 'TRADE', "
                        "timeout: 'float' = 60.0) -> 'Optional[List[Tuple[str, float, float, float, float, float]]]'")
    for cls in (BloombergProvider, IsolatedBloombergProvider, ReplayProvider):
        assert inspect.signature(cls.intraday_bars) == sig
    for p in (Provider(), ReplayProvider({("BDP", "A1Z6 Curncy", "PX_LAST", ()): 44.2}, label="kayıtlı")):
        fn = getattr(p, "intraday_bars", None)
        assert callable(fn) and fn("A1Z6 Curncy", *SPAN) is None
