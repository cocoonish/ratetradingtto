"""The live Bloomberg path, exercised against a stand-in for ``blpapi`` (tests/fake_blpapi.py).

The decisive test is :func:`test_live_pipeline_reproduces_a_direct_calculation`: with the same market data
the asynchronous chain *request -> answer -> invalidate -> recalculate* must give, for every formula cell of
the four workbooks, exactly what a plain synchronous calculation gives.
"""
import datetime as dt
import time

import pytest

import fake_blpapi
from helpers import close, complete_snapshot, server_from_snapshot
from tto.config import Settings
from tto.marketdata.base import INVALID_SECURITY, NOT_APPLICABLE, REQUESTING, bdp_key
from tto.marketdata import bloomberg
from tto.marketdata.bloomberg import NA_NA, NO_BFX, NO_RT, BloombergProvider, check_connection
from tto.marketdata.replay import ReplayProvider
from tto.service import Service
from tto.xl.engine import Clock
from tto.xl.errors import XlError
from tto.xl.model import COLS, a1, parse_a1
from tto.xl.values import XlArray


def settle(provider, timeout=10.0):
    t0 = time.time()
    while provider.busy() and time.time() - t0 < timeout:
        time.sleep(0.02)
    time.sleep(0.15)                    # let the reader thread hand over the last event
    assert not provider.busy()


@pytest.fixture()
def server():
    srv = fake_blpapi.Server()
    srv.ref[("USDTRY Curncy", "BID", ())] = 49.997
    srv.ref[("USDTRY Curncy", "ASK", ())] = 49.9975
    srv.ref[("USDTRY Curncy", "PX_LAST", ())] = 49.9973
    srv.ref[("TYSO1 Curncy", "MID", ())] = 35.55
    srv.ref[("TYSO1 Curncy", "DAYS_TO_MTY", ())] = 365
    srv.ref[("TRY Curncy", "SETTLE_DT", ())] = dt.date(2026, 11, 4)
    srv.ref[("TRT150328T24 ISIN", "MATURITY", ())] = dt.date(2028, 3, 15)
    srv.ref[("TRT150328T24 ISIN", "NAME", ())] = "TURKGB 36.8 03/15/28"
    srv.ref[("TRT150328T24 ISIN", "INFLATION_LINKED_INDICATOR", ())] = False
    srv.ref[("TRT150328T24 ISIN", "YAS_BOND_YLD", (("SETTLE_DT", "20261104"), ("YAS_BOND_PX", "98.5")))] = 37.42
    srv.ref[("TRT150328T24 ISIN", "DES_CASH_FLOW", ())] = [
        {"Payment Date": dt.date(2027, 3, 17), "Coupon Amount": 184000.0, "Principal Amount": 0.0},
        {"Payment Date": dt.date(2028, 3, 15), "Coupon Amount": 184000.0, "Principal Amount": 1000000.0}]
    srv.rt[("USDTRY Curncy", "BID")] = 49.997
    srv.history[("USDTRY Curncy", "PX_LAST")] = [(dt.date(2026, 10, 29), 49.90), (dt.date(2026, 10, 30), 49.93),
                                                  (dt.date(2026, 11, 2), 49.95), (dt.date(2026, 11, 3), 49.99)]
    return srv


@pytest.fixture()
def provider(server):
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    p.start()
    yield p
    p.stop()


def test_values_arrive_asynchronously_like_in_excel(provider, server):
    key = bdp_key("USDTRY Curncy", "BID")
    assert provider.get_bdp(key) == REQUESTING              # what Excel shows while it waits
    assert provider.busy()
    settle(provider)
    assert provider.get_bdp(key) == 49.997
    assert provider.drain_changes() == [key]                # the engine recalculates what used it
    assert provider.drain_changes() == []
    assert provider.get_bdp(key) == 49.997 and len(server.requests) == 1        # served from memory afterwards


def test_requests_are_batched_by_field_set(provider, server):
    for sec in ("USDTRY Curncy", "TYSO1 Curncy"):
        for fld in ("BID", "ASK") if sec.startswith("USD") else ("MID", "DAYS_TO_MTY"):
            provider.get_bdp(bdp_key(sec, fld))
    settle(provider)
    asked = sorted((tuple(r["securities"]), tuple(r["fields"])) for r in server.requests)
    assert asked == [(("TYSO1 Curncy",), ("DAYS_TO_MTY", "MID")), (("USDTRY Curncy",), ("ASK", "BID"))]
    assert provider.hits == 4 == server.hits()              # no cross product, no duplicates
    assert provider.get_bdp(bdp_key("TYSO1 Curncy", "DAYS_TO_MTY")) == 365.0


def test_values_look_like_the_desks_excel(provider):
    keys = {"date": bdp_key("TRY Curncy", "SETTLE_DT"), "mty": bdp_key("TRT150328T24 ISIN", "MATURITY"),
            "name": bdp_key("TRT150328T24 ISIN", "NAME"), "flag": bdp_key("TRT150328T24 ISIN", "INFLATION_LINKED_INDICATOR")}
    for k in keys.values():
        provider.get_bdp(k)
    settle(provider)
    assert provider.get_bdp(keys["date"]) == "4.11.2026"            # BDP dates are Turkish short-date text
    assert provider.get_bdp(keys["mty"]) == "15.03.2028"
    assert provider.get_bdp(keys["name"]) == "TURKGB 36.8 03/15/28"
    assert provider.get_bdp(keys["flag"]) == "N"                    # booleans are Y / N


def test_overrides_are_sent_and_excel_serial_dates_become_yyyymmdd(provider, server):
    key = bdp_key("TRT150328T24 ISIN", "YAS_BOND_YLD", (("SETTLE_DT", "46330"), ("YAS_BOND_PX", "98.5")))
    provider.get_bdp(key)
    settle(provider)
    assert server.requests[0]["overrides"] == (("SETTLE_DT", "20261104"), ("YAS_BOND_PX", "98.5"))
    assert provider.get_bdp(key) == 37.42


def test_errors_use_bloombergs_excel_texts(provider, server):
    server.invalid.add("YOK Curncy")
    server.not_applicable.add(("USDTRY Curncy", "CPN"))
    bad_sec, bad_fld, missing = bdp_key("YOK Curncy", "BID"), bdp_key("USDTRY Curncy", "CPN"), bdp_key("USDTRY Curncy", "FLT_SPREAD")
    for k in (bad_sec, bad_fld, missing):
        provider.get_bdp(k)
    settle(provider)
    assert provider.get_bdp(bad_sec) == INVALID_SECURITY == "#N/A Invalid Security"
    assert provider.get_bdp(bad_fld) == NOT_APPLICABLE == "#N/A Field Not Applicable"
    assert provider.get_bdp(missing) == NA_NA == "#N/A N/A"
    assert provider.get_bfx(("BFX", "XAUUSD", "20261231", "ASKOUTRIGHT")) == NO_BFX
    assert provider.get_rt(("RT", "IDN", "TRY=", "BID")) == NO_RT


def test_streaming_updates_real_time_fields_without_new_requests(provider, server):
    bid, last = bdp_key("USDTRY Curncy", "BID"), bdp_key("USDTRY Curncy", "PX_LAST")
    provider.get_bdp(bid)
    provider.get_bdp(last)
    settle(provider)
    provider.drain_changes()
    assert ("USDTRY Curncy", ["BID", "LAST_PRICE"]) in server.subscriptions          # PX_LAST streams as LAST_PRICE
    n = len(server.requests)
    server.tick("USDTRY Curncy", {"BID": 50.012, "LAST_PRICE": 50.013, "ASK": 50.02})
    time.sleep(0.3)
    assert provider.get_bdp(bid) == 50.012 and provider.get_bdp(last) == 50.013
    assert sorted(provider.drain_changes()) == sorted([bid, last])
    server.tick("USDTRY Curncy", {"BID": 50.012})                                    # unchanged value: nothing to do
    time.sleep(0.3)
    assert provider.drain_changes() == []
    assert len(server.requests) == n                                                 # ticks cost no data points
    st = provider.status()
    assert st["connected"] and st["subscriptions"] == 1 and st["ticks"] >= 2 and st["mode"] == "live"


def test_bist_swap_quote_sizes_are_streamed(provider, server):
    """The Borsa swap sheet asks BID / ASK and their sizes for some 800 tickers: all four are real-time
    fields, so the quotes cost one request each and are then kept up to date by the subscription."""
    sec = "TYB7D BFX0 Curncy"
    server.ref[(sec, "BID", ())] = 3350.0
    server.ref[(sec, "BID_SIZE", ())] = 150.0
    server.ref[(sec, "ASK_SIZE", ())] = 40.0
    bid, size, ask_size = bdp_key(sec, "BID"), bdp_key(sec, "BID_SIZE"), bdp_key(sec, "ASK_SIZE")
    for k in (bid, size, ask_size):
        provider.get_bdp(k)
    settle(provider)
    provider.drain_changes()
    assert (provider.get_bdp(bid), provider.get_bdp(size), provider.get_bdp(ask_size)) == (3350.0, 150.0, 40.0)
    assert (sec, ["ASK_SIZE", "BID", "BID_SIZE"]) in server.subscriptions
    n = len(server.requests)
    server.tick(sec, {"BID_SIZE": 90.0, "ASK_SIZE": 40.0})
    time.sleep(0.3)
    assert provider.get_bdp(size) == 90.0 and provider.drain_changes() == [size]
    assert len(server.requests) == n


def requests_for(server, security):
    return sum(1 for r in server.requests if security in r["securities"])


def test_quotes_that_never_arrive_are_asked_less_and_less(server, monkeypatch):
    """A real-time field whose subscription stays silent is asked by request instead - cache first (24.11.2026): one
    without any value only every ``POLL_EMPTY`` (3 hours), one with a value at most every ``price_poll`` (15 minutes) and
    at twice the interval while the answer stays the same, up to ``POLL_MAX``; an unknown ticker once (once a day).  The
    BIST swap sheet watches hundreds of maturities without any quote: asked every two minutes they alone would use up
    the daily data limit.  (Times shortened here.)"""
    monkeypatch.setattr(bloomberg, "SILENT_AFTER", 0.2)
    monkeypatch.setattr(bloomberg, "POLL_MAX", 1.6)
    monkeypatch.setattr(bloomberg, "POLL_EMPTY", 1.0)
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), price_poll=0.2)
    p.start()
    try:
        quiet, unknown = "TYB200D BFX0 Curncy", "TYB999D BFX0 Curncy"
        server.invalid.add(unknown)
        kq, ku = bdp_key(quiet, "BID"), bdp_key(unknown, "BID")
        p.get_bdp(kq)
        p.get_bdp(ku)
        settle(p)
        assert p.get_bdp(kq) == NA_NA and p.get_bdp(ku) == INVALID_SECURITY
        time.sleep(3.0)
        # without a value: every POLL_EMPTY (1 s here) - not every 0.2 s (some fourteen requests)
        assert 2 <= requests_for(server, quiet) <= 4, requests_for(server, quiet)
        assert requests_for(server, unknown) == 1
        assert p.status()["polled"]["empty"] == 1
        # the quote appears: the next request finds it; from then on the value's interval, doubling while it stays
        server.ref[(quiet, "BID", ())] = 3350.0
        deadline = time.time() + 6.0
        while p.get_bdp(kq) != 3350.0 and time.time() < deadline:
            time.sleep(0.05)
        assert p.get_bdp(kq) == 3350.0 and kq in p.drain_changes()
        time.sleep(3.2)
        with p._lock:
            assert p._items[kq].poll == 1.6 and p._items[ku].poll == 0.0           # 0.2, 0.4, 0.8, 1.6 (POLL_MAX)
        assert p.status()["polled"]["value"] == 1
        # a moving quote goes back to the short interval
        server.ref[(quiet, "BID", ())] = 3351.0
        assert wait_for(lambda: p.get_bdp(kq) == 3351.0, timeout=4.0)
        n = requests_for(server, quiet)
        time.sleep(0.9)
        assert requests_for(server, quiet) > n                       # asked again within 0.2 + 0.4 s, not after 1.6 s
        # ... and once the subscription delivers, the polling stops altogether
        server.tick(quiet, {"BID": 3360.0})
        time.sleep(0.4)
        assert p.get_bdp(kq) == 3360.0
        n = requests_for(server, quiet)
        time.sleep(1.2)
        assert requests_for(server, quiet) == n
    finally:
        p.stop()


def test_a_size_the_stream_does_not_bring_is_not_asked_again(server, monkeypatch):
    """The size of an order (BID_SIZE / ASK_SIZE) that a flowing subscription does not bring means that no order
    stands, and a new one arrives as a tick: it is not asked again by request (on a closed market every bond of
    Borsa İstanbul would cost a request an hour, all day).  A size whose subscription never says anything is asked
    as before."""
    monkeypatch.setattr(bloomberg, "SILENT_AFTER", 0.2)
    monkeypatch.setattr(bloomberg, "POLL_EMPTY", 0.4)
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), price_poll=0.2)
    p.start()
    try:
        flowing, silent = "/isin/TRT150328T24@ISL1", "/isin/TRT160431T35@ISL1"
        server.ref[(flowing, "LAST_PRICE", ())] = server.rt[(flowing, "LAST_PRICE")] = 100.5    # its first picture: no order
        server.ref[(silent, "LAST_PRICE", ())] = 94.1                                             # its stream says nothing

        def asked(sec, field):
            return sum(1 for r in server.requests if sec in r["securities"] and field in r["fields"])

        keys = {sec: [bdp_key(sec, f) for f in ("LAST_PRICE", "BID_SIZE", "ASK_SIZE")] for sec in (flowing, silent)}
        for k in keys[flowing] + keys[silent]:
            p.get_bdp(k)
        settle(p)
        assert [p.get_bdp(k) for k in keys[flowing]] == [100.5, NA_NA, NA_NA]
        assert [p.get_bdp(k) for k in keys[silent]] == [94.1, NA_NA, NA_NA]
        n_flowing, n_silent = asked(flowing, "BID_SIZE"), asked(silent, "BID_SIZE")
        time.sleep(2.0)
        assert asked(flowing, "BID_SIZE") == n_flowing and asked(flowing, "ASK_SIZE") == n_flowing
        assert asked(silent, "BID_SIZE") > n_silent + 1
        # an order arrives as a tick, and goes
        server.tick(flowing, {"BID": 100.4, "BID_SIZE": 5e6})
        assert wait_for(lambda: p.get_bdp(keys[flowing][1]) == 5e6)
        server.tick(flowing, {"BID": None, "BID_SIZE": None})
        assert wait_for(lambda: p.get_bdp(keys[flowing][1]) == NA_NA)
        assert asked(flowing, "BID_SIZE") == n_flowing
    finally:
        p.stop()


def test_without_subscriptions_unchanged_quotes_back_off_too(server, monkeypatch):
    monkeypatch.setattr(bloomberg, "POLL_MAX", 1.6)
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), stream=False, price_poll=0.2)
    p.start()
    try:
        key = bdp_key("USDTRY Curncy", "BID")
        p.get_bdp(key)
        settle(p)
        assert p.get_bdp(key) == 49.997 and server.subscriptions == []
        time.sleep(3.0)
        assert 2 <= requests_for(server, "USDTRY Curncy") <= 7, requests_for(server, "USDTRY Curncy")
        server.ref[("USDTRY Curncy", "BID", ())] = 50.01            # a moving quote is followed at the short interval
        deadline = time.time() + 6.0
        while p.get_bdp(key) != 50.01 and time.time() < deadline:
            time.sleep(0.05)
        assert p.get_bdp(key) == 50.01
        with p._lock:
            assert p._items[key].poll <= 0.4
    finally:
        p.stop()


def test_fields_with_overrides_and_static_fields_are_not_streamed(provider, server):
    provider.get_bdp(bdp_key("TRT150328T24 ISIN", "MATURITY"))
    provider.get_bdp(bdp_key("TRT150328T24 ISIN", "YAS_BOND_YLD", (("SETTLE_DT", "20261104"), ("YAS_BOND_PX", "98.5"))))
    settle(provider)
    assert server.subscriptions == []


def test_history(provider, server):
    opts = (("DATES", "S"), ("DAYS", "W"), ("FILL", "P"))
    shown = ("BDH", "USDTRY Curncy", "PX_LAST", "20261029", "20261103", opts)
    hidden = ("BDH", "USDTRY Curncy", "PX_LAST", "20261029", "20261103", (("DATES", "H"), ("DAYS", "W"), ("FILL", "P")))
    assert provider.get_bdh(shown) == REQUESTING and provider.get_bdh(hidden) == REQUESTING
    settle(provider)
    req = server.requests[0]
    assert req["op"] == "HistoricalDataRequest" and len(server.requests) == 1        # one request serves both
    assert req["options"] == {"startDate": "20261029", "endDate": "20261103", "periodicitySelection": "DAILY",
                              "nonTradingDayFillOption": "NON_TRADING_WEEKDAYS", "nonTradingDayFillMethod": "PREVIOUS_VALUE"}
    a = provider.get_bdh(shown)
    assert type(a) is XlArray and a.rows == [[46324.0, 49.90], [46325.0, 49.93], [46328.0, 49.95], [46329.0, 49.99]]
    assert provider.get_bdh(hidden).rows == [[49.90], [49.93], [49.95], [49.99]]
    nothing = ("BDH", "YENI Curncy", "PX_LAST", "20261029", "20261103", opts)
    provider.get_bdh(nothing)
    settle(provider)
    assert provider.get_bdh(nothing) == NA_NA


def test_bulk_data(provider):
    key = ("BDS", "TRT150328T24 ISIN", "DES_CASH_FLOW", ())
    assert provider.get_bds(key) == REQUESTING
    settle(provider)
    assert provider.get_bds(key).rows == [[46463.0, 184000.0, 0.0], [46827.0, 184000.0, 1000000.0]]      # dates as serials


def test_partial_responses_are_assembled(server):
    server.split_responses = True
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    p.start()
    try:
        keys = [bdp_key("USDTRY Curncy", "BID"), bdp_key("TYSO1 Curncy", "BID")]
        server.ref[("TYSO1 Curncy", "BID", ())] = 35.5
        for k in keys:
            p.get_bdp(k)
        settle(p)
        assert [p.get_bdp(k) for k in keys] == [49.997, 35.5]
    finally:
        p.stop()


def test_daily_data_limit_guard(server):
    """``max_hits_per_day`` is the absolute stop: once the day's count reaches it nothing new goes out - a new key waits
    (it used to be sent all the same: ``_send_queued`` did not look; 24.11.2026) - and what was answered stays."""
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), max_hits_per_day=4)
    p.start()
    try:
        for fld in ("BID", "ASK", "PX_LAST"):
            p.get_bdp(bdp_key("USDTRY Curncy", fld))
        settle(p)
        assert not p.limit_reached and p.status()["tier"] == 0
        p.get_bdp(bdp_key("TYSO1 Curncy", "MID"))
        settle(p)
        assert p.limit_reached and "bütçe" in p.status()["error"] and p.status()["tier"] == 2 and server.hits() == 4
        assert p.get_bdp(bdp_key("TYSO1 Curncy", "MID")) == 35.55          # what was asked is still answered
        assert p.get_bdp(bdp_key("TYSO1 Curncy", "DAYS_TO_MTY")) == REQUESTING
        time.sleep(0.6)
        assert server.hits() == 4 and p.get_bdp(bdp_key("TYSO1 Curncy", "DAYS_TO_MTY")) == REQUESTING   # nothing new
        assert p.status()["pending"] == 1                                   # ... it waits
    finally:
        p.stop()


def test_reconnects_and_resubscribes_after_the_terminal_drops(server):
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), reconnect_wait=0.05)
    p.start()
    try:
        bid = bdp_key("USDTRY Curncy", "BID")
        p.get_bdp(bid)
        settle(p)
        assert p.status()["connected"] and len(server.subscriptions) == 1
        server.drop_sessions()
        t0 = time.time()
        while len(server.subscriptions) < 2 and time.time() - t0 < 10:
            time.sleep(0.05)
        assert len(server.subscriptions) == 2                      # subscribed again on the new session
        assert p.status()["connected"]
        assert p.get_bdp(bid) == 49.997                            # the last value stays on screen meanwhile
        time.sleep(0.3)
        p.drain_changes()
        server.tick("USDTRY Curncy", {"BID": 50.5})
        time.sleep(0.4)
        assert p.get_bdp(bid) == 50.5 and p.drain_changes() == [bid]
        ask = bdp_key("USDTRY Curncy", "ASK")                      # and new requests work on the new session
        p.get_bdp(ask)
        settle(p)
        assert p.get_bdp(ask) == 49.9975
    finally:
        p.stop()


def test_identifiers_written_for_excel_are_sent_the_way_the_api_takes_them(provider, server):
    """DİBS RV names a bond the way Excel's add-in accepts it - "TRT150328T24 @ISL1 ISIN", identifier type at
    the end.  The API does not know that spelling (every bond of the page read "#N/A Invalid Security" on the
    desk); it wants "/isin/TRT150328T24@ISL1".  The provider translates on the way out, for requests, history
    and subscriptions alike, and the workbook keeps its own spelling."""
    priced, plain = "TRT150328T24 @ISL1 ISIN", "TRT150328T24 ISIN"
    assert server.unknown(priced) and server.unknown(plain)                 # what the API says to Excel's spelling
    assert not server.unknown("/isin/TRT150328T24@ISL1")
    server.ref[(plain, "NAME", ())] = "TURKIYE GOVERNMENT BOND"
    server.ref[(plain, "CPN", ())] = 36.8
    server.ref[(priced, "BID", ())] = 100.10
    server.ref[(priced, "ASK", ())] = 100.125
    server.ref[(priced, "YLD_YTM_MID", ())] = 39.7
    server.rt[(priced, "BID")] = 100.10
    server.history[(priced, "PX_LAST")] = [(dt.date(2026, 11, 2), 100.3), (dt.date(2026, 11, 3), 100.2)]
    keys = [bdp_key(plain, "NAME"), bdp_key(plain, "CPN"), bdp_key(priced, "BID"), bdp_key(priced, "ASK"),
            bdp_key(priced, "YLD_YTM_MID")]
    for k in keys:
        assert provider.get_bdp(k) == REQUESTING
    bdh = ("BDH", priced, "PX_LAST", "20261102", "20261103", (("DATES", "H"),))
    provider.get_bdh(bdh)
    settle(provider)
    assert [provider.get_bdp(k) for k in keys] == ["TURKIYE GOVERNMENT BOND", 36.8, 100.10, 100.125, 39.7]
    assert provider.get_bdh(bdh).rows == [[100.3], [100.2]]
    asked = {sec for r in server.requests for sec in r["securities"]}
    assert asked == {"/isin/TRT150328T24", "/isin/TRT150328T24@ISL1"}        # never the Excel spelling
    assert wait_for(lambda: provider.status()["subscriptions"] == 1)
    assert server.subscriptions == [("/isin/TRT150328T24@ISL1", ["ASK", "BID"])]
    provider.drain_changes()
    server.tick(priced, {"BID": 100.2})
    assert wait_for(lambda: provider.get_bdp(bdp_key(priced, "BID")) == 100.2)
    assert provider.drain_changes() == [bdp_key(priced, "BID")]              # under the workbook's own name
    rows = provider.history([(priced, "PX_LAST")], "20261101", "20261103", timeout=10)
    assert rows == {(priced, "PX_LAST"): [("2026-11-02", 100.3), ("2026-11-03", 100.2)]}
    st = provider.status()
    assert st["subscriptions_invalid"] == 0 and st["subscriptions_failed"] == 0


@pytest.mark.parametrize("excel, api", [
    ("TRT150328T24 @ISL1 ISIN", "/isin/TRT150328T24@ISL1"),
    ("TRT150328T24@ISL0 ISIN", "/isin/TRT150328T24@ISL0"),
    ("TRT150328T24 ISIN", "/isin/TRT150328T24"),
    ("trt150328t24 isin", "/isin/trt150328t24"),
    ("912828U81 CUSIP", "/cusip/912828U81"),
    ("B0YQ5W0 SEDOL", "/sedol1/B0YQ5W0"),
    ("BBG000BLNNH6 FIGI", "/bbgid/BBG000BLNNH6"),
    ("/isin/TRT150328T24@ISL1", "/isin/TRT150328T24@ISL1"),                  # already the API's way
    ("USDTRY Curncy", "USDTRY Curncy"),                                      # ordinary tickers are left alone
    ("TYB7D BFX0 Curncy", "TYB7D BFX0 Curncy"),
    ("TRT150328T24 Govt", "TRT150328T24 Govt"),
    ("XS1234567890 Corp", "XS1234567890 Corp"),
    ("BISTTREF Index", "BISTTREF Index"),
    ("ISIN", "ISIN"),
])
def test_api_security(excel, api):
    assert bloomberg.api_security(excel) == api


# ---------------------------------------------------------------------------------- keeping up with Bloomberg
def wait_for(cond, timeout=10.0, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


def test_securities_bloomberg_does_not_know_are_not_subscribed_to(provider, server):
    """The BIST swap sheet asks for hundreds of maturities that do not exist.  Each is asked once by request
    (Excel shows "#N/A Invalid Security" for them); a subscription would only make the terminal log
    "Resolution failed" and send a failure event for every one of them."""
    for n in (374, 375, 376):
        server.invalid.add("TYB%dD BFX0 Curncy" % n)
    sec = "TYB7D BFX0 Curncy"
    for f, v in (("BID", 3350.0), ("ASK", 3352.0), ("BID_SIZE", 150.0), ("ASK_SIZE", 40.0)):
        server.ref[(sec, f, ())] = v
    keys = [bdp_key("TYB%dD BFX0 Curncy" % n, f) for n in (7, 374, 375, 376) for f in ("BID", "ASK", "BID_SIZE", "ASK_SIZE")]
    for k in keys:
        provider.get_bdp(k)
    settle(provider)
    assert wait_for(lambda: provider.status()["subscriptions"] == 1)
    assert [t for t, _ in server.subscriptions] == [sec]                  # only the one that exists
    assert provider.get_bdp(bdp_key("TYB374D BFX0 Curncy", "BID")) == INVALID_SECURITY
    st = provider.status()
    assert st["subscriptions_invalid"] == 3 and st["subscriptions_failed"] == 0 and st["hits_today"] == 16
    hits, asked = server.hits(), len(server.subscriptions)
    time.sleep(0.8)                                                       # ... and they are left alone afterwards
    assert server.hits() == hits and len(server.subscriptions) == asked


def test_a_security_that_appears_on_a_new_day_is_found(server):
    """A maturity that does not exist today may exist tomorrow: what Bloomberg did not know - and a page still reads -
    is asked once more on the next day, and subscribed to if it is there now."""
    sec = "TYB30D BFX0 Curncy"
    server.invalid.add(sec)
    now = [time.time()]
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), clock=lambda: now[0])
    p.start()
    try:
        bid = bdp_key(sec, "BID")
        p.get_bdp(bid)
        settle(p)
        assert p.get_bdp(bid) == INVALID_SECURITY and server.subscriptions == []
        p.drain_changes()
        server.invalid.discard(sec)
        server.ref[(sec, "BID", ())] = 3301.0
        server.rt[(sec, "BID")] = 3301.5
        time.sleep(0.6)
        assert requests_for(server, sec) == 1                              # not again today
        now[0] += 86400.0                                                  # midnight has passed
        assert wait_for(lambda: p.hits_day == dt.date.fromtimestamp(now[0]))
        p.get_bdp(bid)                                                     # (a page reads it on the new day)
        now[0] += 5.0                                                      # (the clock goes on: the keys are looked over)
        assert wait_for(lambda: p.get_bdp(bid) != INVALID_SECURITY)
        assert wait_for(lambda: p.status()["subscriptions"] == 1)
        assert wait_for(lambda: p.get_bdp(bid) == 3301.5)                  # the first paint of the new subscription
        assert bid in p.drain_changes()
        assert p.status()["subscriptions_invalid"] == 0
        assert requests_for(server, sec) == 2                              # once on each day
    finally:
        p.stop()


def test_a_subscription_does_not_wait_for_ever_for_the_reference_answer(server, monkeypatch):
    monkeypatch.setattr(bloomberg, "SUBSCRIBE_WAIT", 0.3)
    server.silent = True                                                   # requests are swallowed
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    p.start()
    try:
        bid = bdp_key("USDTRY Curncy", "BID")
        p.get_bdp(bid)
        time.sleep(0.15)
        assert server.subscriptions == []                                  # still waiting for the answer
        assert wait_for(lambda: p.get_bdp(bid) == 49.997, timeout=5)       # ... then subscribed anyway: first paint
        assert server.subscriptions == [("USDTRY Curncy", ["BID"])]
    finally:
        p.stop()


def test_ticks_can_be_conflated_and_the_option_is_dropped_when_refused(server):
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), interval=1.0)
    p.start()
    try:
        p.get_bdp(bdp_key("USDTRY Curncy", "BID"))
        settle(p)
        assert wait_for(lambda: p.status()["subscriptions"] == 1)
        assert server.subscription_options == [("USDTRY Curncy", ["interval=1"])]
        assert p.status()["interval"] == 1.0
    finally:
        p.stop()
    server.subscription_options[:] = []
    server.subscriptions[:] = []
    server.refuse_options = True
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), interval=0.5)
    p.start()
    try:
        bid = bdp_key("USDTRY Curncy", "BID")
        p.get_bdp(bid)
        settle(p)
        assert wait_for(lambda: p.status()["subscriptions"] == 1)
        assert server.subscription_options == [("USDTRY Curncy", ["interval=0.5"]), ("USDTRY Curncy", [])]
        server.tick("USDTRY Curncy", {"BID": 50.25})
        assert wait_for(lambda: p.get_bdp(bid) == 50.25)
        assert p.status()["subscriptions_failed"] == 0
    finally:
        p.stop()
    plain = BloombergProvider(blpapi_module=fake_blpapi.module(server))     # default: every tick, no option
    assert plain.interval == 0.0


def test_the_session_is_given_a_longer_event_queue(server):
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    p.start()
    try:
        assert server.sessions[0].options.settings["MaxEventQueueSize"] == bloomberg.QUEUE_SIZE == 100000
        assert p.status()["queue_size"] == 100000
    finally:
        p.stop()
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), queue_size=0)      # blpapi's own default
    p.start()
    try:
        assert "MaxEventQueueSize" not in server.sessions[0].options.settings
    finally:
        p.stop()


def test_ticks_without_a_number_are_ignored(provider, server):
    bid, size = bdp_key("USDTRY Curncy", "BID"), bdp_key("USDTRY Curncy", "BID_SIZE")
    server.ref[("USDTRY Curncy", "BID_SIZE", ())] = 5.0
    provider.get_bdp(bid)
    provider.get_bdp(size)
    settle(provider)
    assert wait_for(lambda: provider.status()["subscriptions"] == 1)
    provider.drain_changes()
    ticks = provider.status()["ticks"]
    server.tick("USDTRY Curncy", {"BID": None, "BID_SIZE": "n.a.", "MKTDATA_EVENT_TYPE": "QUOTE"})
    assert wait_for(lambda: provider.status()["ticks"] == ticks + 1)
    assert provider.get_bdp(bid) == 49.997 and provider.get_bdp(size) == 5.0 and provider.drain_changes() == []
    server.tick("USDTRY Curncy", {"BID_SIZE": 7})                           # an integer field
    assert wait_for(lambda: provider.get_bdp(size) == 7.0)
    assert type(provider.get_bdp(size)) is float and provider.drain_changes() == [size]


def test_an_order_that_is_withdrawn_takes_its_size_with_it(provider, server):
    """A tick that carries a size without a value says the order is gone.  Excel shows "#N/A N/A" then; kept
    at its last value, the size would leave a quote on the BIST swap page that is no longer in the market."""
    sec = "TYB30D BFX1 Curncy"
    for f, v in (("BID", 12850.0), ("BID_SIZE", 5e6), ("ASK", 13100.0), ("ASK_SIZE", 2e7)):
        server.ref[(sec, f, ())] = v
    keys = {f: bdp_key(sec, f) for f in ("BID", "BID_SIZE", "ASK", "ASK_SIZE")}
    for k in keys.values():
        provider.get_bdp(k)
    settle(provider)
    assert wait_for(lambda: provider.status()["subscriptions"] == 1)
    provider.drain_changes()
    server.tick(sec, {"BID": None, "BID_SIZE": None, "ASK_SIZE": 1.5e7})     # the bid is pulled, the ask shrinks
    assert wait_for(lambda: provider.get_bdp(keys["ASK_SIZE"]) == 1.5e7)
    assert provider.get_bdp(keys["BID_SIZE"]) == NA_NA                       # no size: no quote
    assert provider.get_bdp(keys["BID"]) == 12850.0                          # a price keeps its last value
    assert sorted(provider.drain_changes()) == sorted([keys["BID_SIZE"], keys["ASK_SIZE"]])
    hits = server.hits()
    server.tick(sec, {"BID": 12800.0, "BID_SIZE": 2e6})                      # a new order
    assert wait_for(lambda: provider.get_bdp(keys["BID_SIZE"]) == 2e6)
    assert provider.get_bdp(keys["BID"]) == 12800.0 and server.hits() == hits


def test_a_full_event_queue_is_reported_and_what_it_dropped_is_asked_again(server, monkeypatch):
    """Bloomberg's session holds a limited number of undelivered events.  When the reader falls behind, it
    is warned (SlowConsumerWarning) and then loses events; afterwards the session says how many
    (SlowConsumerWarningCleared) and for which subscriptions (DataLoss).  The provider counts all of that,
    shows it in its status and asks the values concerned once more by request - a dropped tick must not
    leave an old price on the screen."""
    monkeypatch.setattr(bloomberg, "RESYNC_SETTLE", 0.1)
    server.queue_limit = 40
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    p.start()
    try:
        bid, ask = bdp_key("USDTRY Curncy", "BID"), bdp_key("USDTRY Curncy", "ASK")
        p.get_bdp(bid)
        p.get_bdp(ask)
        settle(p)
        assert wait_for(lambda: p.status()["subscriptions"] == 1)
        st = p.status()
        assert not st["slow"] and st["slow_warnings"] == 0 and st["events_dropped"] == 0 and st["messages_lost"] == 0
        hits = server.hits()
        with p._lock:                                # the reader is stuck (as when the engine keeps it waiting)
            for i in range(200):
                server.tick("USDTRY Curncy", {"BID": 50.0 + i * 0.001})
        # the last ticks were dropped; what a request answers now is the true last price
        server.ref[("USDTRY Curncy", "BID", ())] = 50.199
        assert server.dropped >= 150
        assert wait_for(lambda: p.status()["events_dropped"] == server.dropped and not p.status()["slow"])
        st = p.status()
        assert st["slow_warnings"] == 1 and st["messages_lost"] == server.dropped
        assert "düştü" in st["error"]
        assert wait_for(lambda: p.get_bdp(bid) == 50.199)                 # asked again, not left at an old tick
        assert wait_for(lambda: p.status()["resyncs"] == 2)               # both fields of the subscription
        assert server.hits() == hits + 2
        assert wait_for(lambda: not p.busy())
        time.sleep(0.3)
        assert server.hits() == hits + 2                                  # once, not in a loop
    finally:
        p.stop()


def test_repairing_after_losses_cannot_use_up_the_daily_data_limit(provider, server, monkeypatch):
    """A reader that keeps falling behind would ask everything again after every overflow; that is capped per
    day (the terminal's data limit is shared with the desk's Excel)."""
    monkeypatch.setattr(bloomberg, "RESYNC_SETTLE", 0.0)
    monkeypatch.setattr(bloomberg, "RESYNC_EVERY", 0.0)
    monkeypatch.setattr(bloomberg, "RESYNC_BUDGET", 3)
    bid, ask = bdp_key("USDTRY Curncy", "BID"), bdp_key("USDTRY Curncy", "ASK")
    provider.get_bdp(bid)
    provider.get_bdp(ask)
    settle(provider)
    assert wait_for(lambda: provider.status()["subscriptions"] == 1)
    hits = server.hits()
    for round_ in range(4):
        server.admin("SlowConsumerWarning")
        server.admin("SlowConsumerWarningCleared", {"eventsDropped": 10})
        assert wait_for(lambda: provider.status()["events_dropped"] == 10 * (round_ + 1))
        time.sleep(0.6)                                  # two turns of the worker
        assert wait_for(lambda: not provider.busy())
    assert provider.status()["resyncs"] == 4 and server.hits() == hits + 4      # two rounds of two, then no more
    provider.hits_day = dt.date.today() - dt.timedelta(days=1)                  # a new day: the budget is back
    assert wait_for(lambda: provider.hits_day == dt.date.today())
    server.admin("SlowConsumerWarningCleared", {"eventsDropped": 1})
    assert wait_for(lambda: provider.status()["resyncs"] == 6)


def test_admin_messages_alone_are_understood(provider, server):
    bid = bdp_key("USDTRY Curncy", "BID")
    provider.get_bdp(bid)
    settle(provider)
    assert wait_for(lambda: provider.status()["subscriptions"] == 1)
    server.admin("SlowConsumerWarning")
    assert wait_for(lambda: provider.status()["slow"])
    assert provider.status()["slow_warnings"] == 1 and "kuyruğu" in provider.status()["error"]
    server.admin("SlowConsumerWarningCleared", {"eventsDropped": 0})
    assert wait_for(lambda: not provider.status()["slow"])
    assert provider.status()["events_dropped"] == 0 and provider.status()["resyncs"] == 0
    assert provider.status()["error"] == ""                                # caught up: nothing left to report
    server.admin("SomethingNew", {"x": 1})                                 # unknown admin messages are harmless
    server.tick("USDTRY Curncy", {"BID": 50.4})
    assert wait_for(lambda: provider.get_bdp(bid) == 50.4)


def test_favour_reader_shortens_the_switch_interval():
    import sys
    before = sys.getswitchinterval()
    try:
        sys.setswitchinterval(0.005)
        done = bloomberg.favour_reader()
        assert done.get("switch_interval") == 0.001 and abs(sys.getswitchinterval() - 0.001) < 1e-9
        assert "switch_interval" not in bloomberg.favour_reader()          # already short: left alone
    finally:
        sys.setswitchinterval(before)


def test_unreachable_bloomberg_is_reported(server):
    server.fail_start = True
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    with pytest.raises(RuntimeError):
        p.start()
    assert check_connection(blpapi_module=fake_blpapi.module(server)) == 1


def test_auto_mode_falls_back_to_the_saved_data(tmp_path):
    """No blpapi / no terminal: the dashboard still starts, on the data saved in the workbook."""
    svc = Service(Settings(data_dir=str(tmp_path), mode="auto", bbg_port=1))      # nothing listens there
    try:
        assert svc.mode == "replay"
        assert "Bloomberg" in svc.mode_note
    finally:
        svc.stop()


def test_live_mode_refuses_to_start_without_bloomberg(tmp_path):
    with pytest.raises(Exception):
        Service(Settings(data_dir=str(tmp_path), mode="live", bbg_port=1))


class _Direct(ReplayProvider):
    """Answers at once from a dict - the reference the live pipeline is compared with."""
    live = True

    def _get(self, key):
        v = self.snapshot.get(key)
        return NA_NA if v is None else v

    get_bdp = get_bdh = get_bds = _get

    def get_bfx(self, key):
        return NO_BFX

    def get_rt(self, key):
        return NO_RT


def _all_formula_values(svc):
    out = {}

    def run():
        for bid, b in svc.books.items():
            calc = b.engine.shared
            for si, sh in enumerate(b.model.sheets):
                for rc in sh.fml:
                    r, c = divmod(rc, COLS)
                    out[(bid, sh.name, rc)] = calc.get(si, r, c)

    svc.et.call(run)
    return out


def test_live_pipeline_reproduces_a_direct_calculation(tmp_path_factory):
    replay = Service(Settings(data_dir=str(tmp_path_factory.mktemp("r")), mode="replay"))
    today = replay.books["tto"].engine.clock.today()
    snapshot = complete_snapshot(replay)                     # everything the workbooks ask Bloomberg for
    replay.stop()
    assert len(snapshot) > 900

    def clock():
        c = Clock(today + 0.5)
        c.today = lambda: float(today)
        return c

    direct = Service(Settings(data_dir=str(tmp_path_factory.mktemp("d")), mode="live"), provider=_Direct(snapshot), clock=clock())
    server = server_from_snapshot(snapshot)
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    provider.start()
    live = Service(Settings(data_dir=str(tmp_path_factory.mktemp("l")), mode="live"), provider=provider, clock=clock())
    try:
        assert live.mode == "live" and direct.mode == "live"
        warm = live.warmup()
        assert warm["items"] > 900 and warm["rounds"] <= 10
        # what the first calculation asked for, counted now (cache first: nothing is asked again the same day - CHG_NET_,
        # LAST_TRADE_DATE and the ranges up to today follow the stream; a test machine's slow comparison asks nothing)
        asked = provider.status()
        expected = _all_formula_values(direct)
        got = _all_formula_values(live)
        for _ in range(8):                                   # a full pass may discover a few more items
            if not live.warmup()["items"]:
                break
            got = _all_formula_values(live)
        assert len(expected) > 220000                        # every formula of the four workbooks and of the extra sheets
        differ = [(k[1], a1(k[2]), v, got[k]) for k, v in expected.items()
                  if not (close(v, got[k], 1e-12) or (type(v) is XlError and type(got[k]) is XlError and v.code == got[k].code))]
        assert differ == [], differ[:10]
        # a real calculation, not a comparison of errors - counted on the two workbooks whose files hold the
        # market data of their last calculation (the other two have no recorded history to answer with)
        recorded = [v for k, v in expected.items() if k[0] in ("tto", "sofr")]
        numbers = sum(1 for v in recorded if isinstance(v, float))
        errors = sum(1 for v in recorded if type(v) is XlError)
        # (errors: the hand calculators that start empty - the TM OIS page's cash flows of no trade are #DIV/0!, as in
        # Excel - and the Bloomberg fields the recorded files hold no answer for; well under 1 % of the values)
        assert numbers > 80000 and errors * 100 < numbers
        assert sum(1 for k, v in expected.items() if k[0] in ("borsa", "asw") and isinstance(v, float)) > 5000
        st = provider.status()
        # four workbooks: the BIST swap sheet alone watches 800 tickers (bid, ask and their sizes).  Each item is
        # asked once and the requests are batched - how finely depends on how fast the cells are evaluated (some
        # ten items per request here, four on a slow interpreter), so only "clearly batched" is asserted
        assert st["subscriptions"] > 900 and asked["hits_today"] < 6000 and not st["error"]
        assert asked["hits_today"] == warm["items"] and asked["requests"] < asked["hits_today"] / 2

        # a tick moves the curve: both sides again agree after the change (the OIS page reads its quotes from the
        # first pricing source that has one - GFOF's MID - the workbook's own ticker's PX_LAST after it)
        tickers = sorted({(k[1], k[2]) for k in snapshot if k[0] == "BDP" and k[1].startswith("TYSO") and k[2] in ("PX_LAST", "MID")
                          and not k[3]})
        assert len(tickers) >= 10
        changes = {}
        for i, (sec, fld) in enumerate(tickers):
            new = snapshot[("BDP", sec, fld, ())] + 0.05 + 0.01 * i
            rt = "LAST_PRICE" if fld == "PX_LAST" else fld
            server.ref[(sec, fld, ())] = new                             # what a later request would get
            server.rt[(sec, rt)] = new
            server.tick(sec, {rt: new})                                  # what the subscription delivers now
            changes[("BDP", sec, fld, ())] = new
        time.sleep(0.5)
        keys = provider.drain_changes()
        assert len(keys) >= 10 and set(keys) <= set(changes)             # only what the workbook really uses
        live.et.call(live._apply_market, keys)
        direct.provider.snapshot.update(changes)
        direct.et.call(direct._apply_market, list(changes))
        expected = _all_formula_values(direct)
        got = _all_formula_values(live)
        for _ in range(8):
            if not live.warmup()["items"]:
                break
            got = _all_formula_values(live)
        moved = sum(1 for k, v in expected.items() if isinstance(v, float) and isinstance(got[k], float))
        differ = [k for k, v in expected.items()
                  if not (close(v, got[k], 1e-12) or (type(v) is XlError and type(got[k]) is XlError))]
        assert differ == [] and moved > 80000

        # the size of an order: none in the stream (as on a closed market) - DİBS RV shows no quote; a tick brings one
        si = live.books["tto"].model.sheet_index["DİBS RV"]

        def rv8(col):
            return live.et.call(lambda: live.books["tto"].engine.shared.get(si, 8, parse_a1(col + "1") % COLS))

        assert (rv8("K"), rv8("L"), rv8("W")) == ("–", "–", "") and str(rv8("J")).startswith("Kota yok · ")
        server.tick("/isin/TRT150328T24@ISL1", {"BID_SIZE": 5e6, "ASK_SIZE": 2.5e6})
        sizes = {bdp_key("TRT150328T24 @ISL1 ISIN", f) for f in ("BID_SIZE", "ASK_SIZE")}
        got = set()
        deadline = time.time() + 10.0
        while not sizes <= got and time.time() < deadline:
            got |= set(provider.drain_changes())
            time.sleep(0.05)
        assert sizes <= got
        live.et.call(live._apply_market, list(got))
        assert (rv8("K"), rv8("L"), rv8("J")) == (100.1, 100.125, "Canlı kota") and type(rv8("W")) is float
    finally:
        direct.stop()
        live.stop()


def test_a_restart_the_same_day_does_not_ask_bloomberg_again_what_it_answered(server):
    """The day's answers - quotes too (cache first, 24.11.2026: they used to be asked again at every start) - and the data
    points used are kept (the service keeps them in its database): a provider started again the same day takes the
    answers as given - no request, the quote's subscription brings it up to date for free - and goes on counting from
    where the earlier one stopped.  An answer is asked again when it is due: a once-a-day field the next day."""
    keys = [bdp_key("TRT150328T24 ISIN", "MATURITY"), bdp_key("TRY Curncy", "SETTLE_DT"), bdp_key("USDTRY Curncy", "BID")]
    first = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    first.start()
    try:
        for k in keys:
            first.get_bdp(k)
        settle(first)
        values = {k: first.get_bdp(k) for k in keys}
        kept = first.answers()
        used = first.status()["hits_today"]
    finally:
        first.stop()
    assert {k for k, _, _ in kept} == set(keys) and used == 3               # (the quote too)
    asked = len(server.requests)
    now = [time.time()]
    again = BloombergProvider(blpapi_module=fake_blpapi.module(server), clock=lambda: now[0])
    again.preload(kept)
    again.carry_hits(used)
    again.start()
    try:
        assert [again.get_bdp(k) for k in keys] == [values[k] for k in keys]
        time.sleep(0.6)
        assert server.requests[asked:] == [] and again.status()["hits_today"] == used        # nothing asked again
        assert wait_for(lambda: again.status()["subscriptions"] == 1)       # (the quote streams: free)
        assert {k for k, _, _ in again.answers()} == set(keys)              # kept again, for a next restart
        # the next day (a page reads them): asked once more - a maturity once a day like every field
        now[0] += 86400.0
        assert wait_for(lambda: again.hits_day == dt.date.fromtimestamp(now[0]))
        for k in keys[:2]:
            again.get_bdp(k)
        now[0] += 5.0                                                       # (the clock goes on: the keys are looked over)
        assert wait_for(lambda: "MATURITY" in [f for r in server.requests[asked:] for f in r["fields"]])
        assert again.status()["kinds"] == {"static": 1, "daily": 1}         # (the quote streams: not asked)
    finally:
        again.stop()
