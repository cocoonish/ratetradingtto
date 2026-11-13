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
from tto.xl.model import COLS, a1
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
    """A real-time field whose subscription stays silent is asked by request instead.  The BIST swap sheet
    watches hundreds of maturities without any quote: asked at a fixed interval they would use up the daily
    data limit, so the interval doubles while the answer stays the same - and an unknown ticker is asked once."""
    monkeypatch.setattr(bloomberg, "SILENT_AFTER", 0.2)
    monkeypatch.setattr(bloomberg, "PRICE_POLL_MAX", 1.6)
    monkeypatch.setattr(bloomberg, "PRICE_POLL_MAX_EMPTY", 1.6)
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
        # every 0.2 s would be some fourteen requests; 0.2, 0.4, 0.8, 1.6 ... leaves a handful
        assert 2 <= requests_for(server, quiet) <= 7, requests_for(server, quiet)
        assert requests_for(server, unknown) == 1
        with p._lock:
            assert p._items[kq].poll == 1.6 and p._items[ku].poll == 0.0
        # the quote appears: the next request finds it and the short interval applies again
        server.ref[(quiet, "BID", ())] = 3350.0
        deadline = time.time() + 6.0
        while p.get_bdp(kq) != 3350.0 and time.time() < deadline:
            time.sleep(0.05)
        assert p.get_bdp(kq) == 3350.0 and kq in p.drain_changes()
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


def test_without_subscriptions_unchanged_quotes_back_off_too(server, monkeypatch):
    monkeypatch.setattr(bloomberg, "PRICE_POLL_MAX", 1.6)
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
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), max_hits_per_day=3)
    p.start()
    try:
        for fld in ("BID", "ASK", "PX_LAST"):
            p.get_bdp(bdp_key("USDTRY Curncy", fld))
        settle(p)
        assert not p.limit_reached
        p.get_bdp(bdp_key("TYSO1 Curncy", "MID"))
        settle(p)
        assert p.limit_reached and "limit" in p.status()["error"]
        assert p.get_bdp(bdp_key("TYSO1 Curncy", "MID")) == 35.55          # what was asked is still answered
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
        assert numbers > 80000 and errors < 500
        assert sum(1 for k, v in expected.items() if k[0] in ("borsa", "asw") and isinstance(v, float)) > 5000
        st = provider.status()
        # four workbooks: the BIST swap sheet alone watches 800 tickers (bid, ask and their sizes).  Each item is
        # asked once and the requests are batched - how finely depends on how fast the cells are evaluated (some
        # ten items per request here, four on a slow interpreter), so only "clearly batched" is asserted
        assert st["subscriptions"] > 900 and st["hits_today"] < 6000 and not st["error"]
        assert st["hits_today"] == warm["items"] and st["requests"] < st["hits_today"] / 2

        # a tick moves the curve: both sides again agree after the change
        tickers = sorted({k[1] for k in snapshot if k[0] == "BDP" and k[1].startswith("TYSO") and k[2] == "PX_LAST"})
        assert len(tickers) >= 10
        changes = {}
        for i, sec in enumerate(tickers):
            new = snapshot[("BDP", sec, "PX_LAST", ())] + 0.05 + 0.01 * i
            server.ref[(sec, "PX_LAST", ())] = new                       # what a later request would get
            server.rt[(sec, "LAST_PRICE")] = new
            server.tick(sec, {"LAST_PRICE": new})                        # what the subscription delivers now
            changes[("BDP", sec, "PX_LAST", ())] = new
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
    finally:
        direct.stop()
        live.stop()
