"""Cache first (the desk, 24.11.2026, after Bloomberg answered "Daily capacity reached": "Zaten çektiklerini cache atıp
daha fazla çekmemesi gerekliydi") - the rules of ``tto/marketdata/bloomberg.py``, one by one, on the fake terminal with a
simulated clock: the provider is driven turn by turn here (no threads), so a day takes a moment and every count is exact.

* a key answered today is not asked again today - whatever its field - and a key nobody reads is never asked again;
* DİBS RV's ``CHG_NET_5D`` / ``CHG_NET_1M`` follow the streamed last price, ``LAST_TRADE_DATE`` turns today on a trade,
  ``INTERVAL_LOW`` / ``_HIGH`` take the day's streamed low / high, a ``BDH`` range ending today its today's point;
* a quote that does not stream: at most every 15 minutes, one without a value every 3 hours; nothing outside the desk's
  hours (subscriptions keep streaming);
* the day's budget: past 70 % only first answers, at 100 % nothing new; Bloomberg's own LIMIT answer stops everything
  until a probe an hour after the day changed;
* the status: today's hits by kind and by key.
"""
import datetime as dt

import pytest

import fake_blpapi
from tto.marketdata import bloomberg
from tto.marketdata.base import INVALID_SECURITY, REQUESTING, bdp_key
from tto.marketdata.bloomberg import NA_NA, BloombergProvider
from tto.xl.values import XlArray, date_to_serial

#: a Tuesday of the desk (not a holiday), 07:55 local time
MORNING = dt.datetime(2026, 11, 24, 7, 55)


class Sim(object):
    """A provider on the fake terminal, its clock simulated and its worker / reader driven turn by turn."""

    def __init__(self, server, start=MORNING, desk=True, **kw):
        self.server = server
        self.t = start.timestamp()
        self.p = BloombergProvider(blpapi_module=fake_blpapi.module(server), clock=lambda: self.t, **kw)
        self.p._open_session()                           # (no threads: :meth:`turn` is the worker and the reader)
        self.session = self.p._session
        if desk:
            self.p.set_desk_hours("08:00", "19:00", ["2026-12-25"])

    def at(self, when: dt.datetime) -> "Sim":
        self.t = when.timestamp()
        return self

    def turn(self) -> None:
        """One turn of the worker, and of the reader for what the terminal answered - again while requests go out."""
        for _ in range(50):
            sent = self.p.requests_sent
            self.p._work_once()
            self.pump()
            if self.p.requests_sent == sent:
                break

    def pump(self) -> None:
        while not self.session.events.empty():          # (the fake terminal answers at once, into its queue)
            self.p._handle(self.session.events.get_nowait())

    def run(self, seconds: float, step: float = 30.0, read=()) -> None:
        """``seconds`` of simulated time, a turn every ``step``; the keys in ``read`` are read (a page open) each turn."""
        end = self.t + seconds
        while self.t < end:
            for k in read:
                self.get(k)
            self.turn()
            self.t += step

    def get(self, key):
        kind = key[0]
        return self.p.get_bdh(key) if kind == "BDH" else self.p.get_bds(key) if kind == "BDS" else self.p.get_bdp(key)

    def tick(self, security, values) -> None:
        self.server.tick(security, values)
        self.pump()

    def asked(self, security=None, field=None) -> int:
        """Hits the terminal served (security × field per request) - of a security / field when given."""
        return sum(1 for r in self.server.requests for s in r["securities"] for f in (r["fields"] or [""])
                   if (security is None or s == security) and (field is None or f == field))


@pytest.fixture()
def server():
    srv = fake_blpapi.Server()
    bond = "/isin/TRT150328T24@ISL1"
    for f, v in (("LAST_PRICE", 100.2), ("LOW", 100.1), ("HIGH", 100.3), ("VOLUME", 1.5e9)):
        srv.ref[(bond, f, ())] = v
        srv.rt[(bond, f)] = v
    srv.ref[(bond, "CHG_NET_5D", ())] = -0.2750000000000057      # (DİBS RV's saved answers: CH 100.2, CK, CL)
    srv.ref[(bond, "CHG_NET_1M", ())] = -0.07500000000000284
    srv.ref[(bond, "LAST_TRADE_DATE", ())] = dt.date(2026, 11, 23)
    srv.ref[("TRY Curncy", "SETTLE_DT", ())] = dt.date(2026, 11, 25)
    srv.ref[("TRT150328T24 ISIN", "NAME", ())] = "TURKGB 36.8 03/15/28"
    srv.ref[("USDTRY Curncy", "BID", ())] = srv.rt[("USDTRY Curncy", "BID")] = 42.2
    return srv


BOND = "TRT150328T24 @ISL1 ISIN"
LAST, VOLUME = bdp_key(BOND, "LAST_PRICE"), bdp_key(BOND, "VOLUME")
CHG5, CHG1M, LTD = bdp_key(BOND, "CHG_NET_5D"), bdp_key(BOND, "CHG_NET_1M"), bdp_key(BOND, "LAST_TRADE_DATE")


# ================================================================================================ once a day
def test_a_key_answered_today_is_not_asked_again_today(server):
    """Every field - static, daily, the 60-second class of before (CHG_NET_, LAST_TRADE_DATE: DİBS RV's CK / CL / CG
    were asked every minute, ~216 000 hits a day for 50 bonds) - is asked once a day; the next day once more, in the
    desk's hours, if a page still reads it - and a key no page reads any more (yesterday's range) never again."""
    sim = Sim(server)
    keys = [bdp_key("TRY Curncy", "SETTLE_DT"), bdp_key("TRT150328T24 ISIN", "NAME"), CHG5, CHG1M, LTD, LAST]
    sim.run(11 * 3600, read=keys)                                # 07:55 - 18:55, a page open all day
    assert sim.asked() == len(keys)                              # each once: its first answer
    assert sim.p.status()["kinds"] == {"first": len(keys)}
    # 19:00 - 07:59 of the next day: quiet hours - not even the day's once
    yesterday_only = bdp_key("TRY Curncy", "SETTLE_DT", (("SETTLE_DT", "20261124"),))
    sim.get(yesterday_only)
    sim.run(60, read=[yesterday_only])                           # (a first answer goes out in any hour)
    sim.run(13 * 3600, step=60.0, read=keys)
    assert sim.asked() == len(keys) + 1
    # 08:00: once each (the quote streams: not asked); the key of yesterday's cells is not read today: never again
    sim.run(4 * 3600, read=keys)
    assert sim.asked() == 2 * len(keys) - 1 + 1
    assert sim.p.status()["kinds"] == {"static": 1, "daily": 4}
    assert sim.asked("TRY Curncy", "SETTLE_DT") == 3              # (two days' SETTLE_DT, one of yesterday's range)


def test_quiet_hours_weekends_and_holidays_ask_nothing_again_but_the_stream_flows(server):
    """Outside the desk's hours (08:00 - 19:00 by default, settable), at weekends and on TR holidays: no refresh and
    no poll at all - subscriptions keep streaming; a key no page has had is still asked (a page needs it)."""
    server.refused.add("/isin/TRT150328T24@ISL1")              # the bond's quotes do not stream: polled
    server.ref[("/isin/TRT150328T24@ISL1", "LAST_PRICE", ())] = lambda: next(moving)
    moving = iter(100.0 + i / 1000.0 for i in range(10000))
    sim = Sim(server, start=dt.datetime(2026, 11, 27, 18, 30))     # a Friday evening
    usd = bdp_key("USDTRY Curncy", "BID")
    sim.run(25 * 60, read=[LAST, usd])
    assert sim.asked("/isin/TRT150328T24@ISL1", "LAST_PRICE") == 2                  # 18:30, 18:45 (not 19:00)
    n = sim.asked()
    sim.run(2 * 24 * 3600 + 12 * 3600, step=120.0, read=[LAST, usd])    # Friday 18:55 - Monday 07:55: nothing again
    assert sim.asked() == n
    sim.tick("USDTRY Curncy", {"BID": 42.31})                    # ... the stream flows all the same
    assert sim.p.get_bdp(usd) == 42.31
    sim.get(bdp_key("EURTRY Curncy", "BID"))                     # ... and a new key is asked at once
    sim.turn()
    assert sim.asked() == n + 1
    # Christmas (the desk's holiday list): nothing either
    sim.at(dt.datetime(2026, 12, 25, 10, 0)).run(3600, read=[LAST])
    assert sim.asked() == n + 1
    assert sim.p.status()["quiet"]


# ================================================================================================ DİBS RV from the stream
def test_dibs_rv_ck_cl_follow_the_streamed_last_price(server):
    """CHG_NET_5D / _1M (DİBS RV's CK / CL) are the last price less the close 5 days / a month ago - a close that does
    not move in the day: asked once, then answer + (last now - last at the answer).  On the fake terminal Bloomberg's
    fresh answer is that too: they agree after every trade (and the sheet's GC / GF - its close n days ago - stays)."""
    bond = "/isin/TRT150328T24@ISL1"
    close5, close1m = 100.475, 100.275                         # (100.2 - CK, 100.2 - CL: DİBS RV's saved row 8)
    sim = Sim(server)
    sim.at(dt.datetime(2026, 11, 24, 9, 30))
    for k in (LAST, CHG5, CHG1M):
        sim.get(k)
    sim.turn()
    assert (sim.p.get_bdp(CHG5), sim.p.get_bdp(CHG1M)) == (-0.2750000000000057, -0.07500000000000284)   # Bloomberg's own
    for i, last in enumerate((100.25, 100.1875, 100.4, 99.95)):
        sim.tick(bond, {"LAST_PRICE": last})
        server.ref[(bond, "CHG_NET_5D", ())] = last - close5     # what a request would answer now
        server.ref[(bond, "CHG_NET_1M", ())] = last - close1m
        for k in (CHG5, CHG1M):
            assert abs(sim.p.get_bdp(k) - server.ref[(bond, k[2], ())]) < 1e-9
        assert abs((last - sim.p.get_bdp(CHG5)) - close5) < 1e-9          # the sheet's GC: the close 5 days ago, constant
    sim.run(3600, read=[LAST, CHG5, CHG1M])
    assert sim.asked(bond, "CHG_NET_5D") == 1 and sim.asked(bond, "CHG_NET_1M") == 1             # once today
    assert sim.p.status()["fed"] == 2


def test_dibs_rv_ck_is_measured_from_the_last_price_on_the_replay_values(service):
    """The replay's DİBS RV (the desk's file of 03.11.2026): for every bond, last price (CH) less CHG_NET_5D / _1M (CK /
    CL) is a clean price of three decimals - Bloomberg measures the change from the last price, the price the stream
    carries (``LAST_PRICE``); from it the change follows the stream."""
    from conftest import cell
    rows = 0
    for r in range(5, 55):
        if not cell(service, "DİBS RV!BT%d" % r):
            continue
        last = cell(service, "DİBS RV!CH%d" % r)
        for col in ("CK", "CL"):
            chg = cell(service, "DİBS RV!%s%d" % (col, r))
            if type(last) is float and type(chg) is float:
                close = last - chg
                assert abs(close - round(close, 3)) < 1e-9, (r, col, last, chg)
                rows += 1
    assert rows >= 30


def test_dibs_rv_cg_is_today_once_the_stream_shows_a_trade(server):
    """LAST_TRADE_DATE (DİBS RV's CG, DİBS Trading's, Tüm Kâğıtlar') is asked once a day; a trade the stream shows - the
    last price changes, the day's volume grows (not the first value seen) - makes it today."""
    bond = "/isin/TRT150328T24@ISL1"
    sim = Sim(server).at(dt.datetime(2026, 11, 24, 9, 30))
    for k in (LAST, VOLUME, LTD):
        sim.get(k)
    sim.turn()
    assert sim.p.get_bdp(LTD) == "23.11.2026"
    sim.tick(bond, {"LAST_PRICE": 100.2, "VOLUME": 1.5e9})       # the first picture again: no trade
    assert sim.p.get_bdp(LTD) == "23.11.2026"
    sim.tick(bond, {"VOLUME": 1.6e9})                            # a trade at the same price: the volume grew
    assert sim.p.get_bdp(LTD) == "24.11.2026" and LTD in sim.p.drain_changes()
    sim.run(4 * 3600, read=[LAST, VOLUME, LTD])
    assert sim.asked(bond, "LAST_TRADE_DATE") == 1 and sim.p.get_bdp(LTD) == "24.11.2026"


def test_interval_low_high_take_the_days_streamed_low_and_high(server):
    """INTERVAL_LOW / _HIGH up to today (DİBS RV's CM:CP): once a day, then the lower / higher of Bloomberg's answer and the
    day's streamed low / high (Bloomberg's own answer while the day's is not beyond it: it gives some in single
    precision, 100.0999984741211 for 100.1)."""
    bond = "/isin/TRT150328T24@ISL1"
    ov = (("END_DATE_OVERRIDE", "20261124"), ("MARKET_DATA_OVERRIDE", "PX_LOW"), ("START_DATE_OVERRIDE", "20261026"))
    lo, hi = bdp_key(BOND, "INTERVAL_LOW", ov), bdp_key(BOND, "INTERVAL_HIGH", tuple(
        (n, "PX_HIGH" if n == "MARKET_DATA_OVERRIDE" else v) for n, v in ov))
    server.ref[(bond, "INTERVAL_LOW", ov)] = 100.0999984741211
    server.ref[(bond, "INTERVAL_HIGH", hi[3])] = 100.5
    sim = Sim(server).at(dt.datetime(2026, 11, 24, 9, 30))
    for k in (bdp_key(BOND, "LOW"), bdp_key(BOND, "HIGH"), lo, hi):
        sim.get(k)
    sim.turn()
    assert (sim.p.get_bdp(lo), sim.p.get_bdp(hi)) == (100.0999984741211, 100.5)      # today's 100.1: not beyond it
    sim.tick(bond, {"LOW": 99.95, "HIGH": 100.45})
    assert (sim.p.get_bdp(lo), sim.p.get_bdp(hi)) == (99.95, 100.5)
    sim.tick(bond, {"HIGH": 100.6})
    assert sim.p.get_bdp(hi) == 100.6
    sim.run(5 * 3600, read=[lo, hi])
    assert sim.asked(bond, "INTERVAL_LOW") == 1 and sim.asked(bond, "INTERVAL_HIGH") == 1


def test_a_bdh_range_ending_today_takes_its_todays_point_from_the_stream(server):
    """A workbook BDH ending today (EK_VIOP's, VIOP's: Days=W, Fill=P, Dates=H beside a Dates=S block) is asked once a
    day - not every 15 minutes - and its today's point follows the security's live quote; without one (or without a
    point for today in the answer) it is asked at most hourly in the desk's hours."""
    days = [dt.date(2026, 11, d) for d in (20, 23, 24)]
    server.history[("TYSOA Curncy", "PX_LAST")] = list(zip(days, (37.1, 37.2, 37.25)))
    server.history[("TYSOB Curncy", "PX_LAST")] = list(zip(days, (37.3, 37.35, 37.36)))   # no live quote of it
    server.ref[("TYSOA Curncy", "PX_LAST", ())] = server.rt[("TYSOA Curncy", "LAST_PRICE")] = 37.25
    opts = (("DATES", "H"), ("DAYS", "W"), ("FILL", "P"))
    a, b = ("BDH", "TYSOA Curncy", "PX_LAST", "20261120", "20261124", opts), \
        ("BDH", "TYSOB Curncy", "PX_LAST", "20261120", "20261124", opts)
    sim = Sim(server).at(dt.datetime(2026, 11, 24, 9, 30))
    quote = bdp_key("TYSOA Curncy", "PX_LAST")
    for k in (quote, a, b):
        sim.get(k)
    sim.turn()
    assert sim.p.get_bdh(a).rows == [[37.1], [37.2], [37.25]]
    sim.tick("TYSOA Curncy", {"LAST_PRICE": 37.4})
    assert sim.p.get_bdh(a).rows == [[37.1], [37.2], [37.4]] and a in sim.p.drain_changes()
    sim.run(8 * 3600, read=[quote, a, b])                       # 09:30 - 17:30
    requests = [r for r in server.requests if r["op"] == "HistoricalDataRequest"]
    assert sum(1 for r in requests if "TYSOA Curncy" in r["securities"]) == 1
    assert sum(1 for r in requests if "TYSOB Curncy" in r["securities"]) == 8          # 09:30, then hourly to 16:30
    assert sim.p.status()["kinds"] == {"first": 3, "history": 7}


# ================================================================================================ quotes that do not stream
def test_a_quote_that_does_not_stream_is_asked_at_most_every_15_minutes(server):
    """A failed subscription (the office had 48 of 822) whose answer changes on every request used to be asked every
    120 s all day (the interval doubled only while the answer stayed): now at most every 15 minutes in the desk's
    hours, whatever its answer does; one without any value every 3 hours; an unknown ticker once a day."""
    moving = iter(42.0 + i / 10000.0 for i in range(100000))
    server.refused.update({"USDTRY Curncy", "TYB30D BFX0 Curncy"})
    server.ref[("USDTRY Curncy", "ASK", ())] = lambda: next(moving)
    server.invalid.add("TYB31D BFX0 Curncy")
    ask, empty, unknown = bdp_key("USDTRY Curncy", "ASK"), bdp_key("TYB30D BFX0 Curncy", "BID"), bdp_key("TYB31D BFX0 Curncy", "BID")
    sim = Sim(server).at(dt.datetime(2026, 11, 24, 8, 0))
    sim.run(11 * 3600 - 60, step=20.0, read=[ask, empty, unknown])         # 08:00 - 18:59
    assert sim.asked("USDTRY Curncy", "ASK") == 44                          # 08:00, then every 15 minutes
    assert sim.asked("TYB30D BFX0 Curncy", "BID") == 4                      # 08:00, 11:00, 14:00, 17:00
    assert sim.asked("TYB31D BFX0 Curncy", "BID") == 1
    assert sim.p.get_bdp(unknown) == INVALID_SECURITY and sim.p.get_bdp(empty) == NA_NA
    st = sim.p.status()
    assert st["polled"] == {"value": 1, "empty": 1, "stopped": 0} and st["kinds"] == {"first": 3, "poll": 43 + 3}
    assert st["poll_every"] == bloomberg.POLL_EVERY == 900.0 and bloomberg.POLL_EMPTY == 3 * 3600.0


# ================================================================================================ the day's budget
def test_past_70_percent_of_the_budget_only_first_answers_and_at_100_nothing_new(server):
    """The day's budget (``--daily-budget``, 100 000 by default; ``--max-hits`` stays the absolute stop): past 70 % no
    refresh, no poll - only the first answer of a key a page has never had; at 100 % nothing new - a key waits."""
    server.refused.add("USDTRY Curncy")
    server.ref[("USDTRY Curncy", "ASK", ())] = 42.3
    sim = Sim(server, budget=10).at(dt.datetime(2026, 11, 24, 9, 0))
    ask = bdp_key("USDTRY Curncy", "ASK")
    keys = [ask] + [bdp_key("TEST%d Curncy" % i, "NAME") for i in range(6)]
    sim.run(60, read=keys)
    assert sim.p.status()["tier"] == 1 and sim.asked() == 7      # 70 % of 10
    sim.run(3600, read=keys)
    assert sim.asked() == 7                                      # the quote is not polled any more
    sim.get(bdp_key("TEST7 Curncy", "NAME"))
    sim.get(bdp_key("TEST8 Curncy", "NAME"))
    sim.get(bdp_key("TEST9 Curncy", "NAME"))
    sim.turn()
    assert sim.asked() == 10 and sim.p.status()["tier"] == 2 and sim.p.status()["limit_reached"]
    late = bdp_key("TEST10 Curncy", "NAME")
    assert sim.get(late) == REQUESTING
    sim.run(3600, read=[late])
    assert sim.asked() == 10 and sim.get(late) == REQUESTING and sim.p.status()["pending"] == 1      # it waits
    sim.at(dt.datetime(2026, 11, 25, 9, 0)).run(60, read=[late])                                    # a new day
    assert sim.get(late) != REQUESTING and sim.p.status()["tier"] == 0


def test_bloombergs_own_limit_stops_everything_until_a_probe_the_next_day(server):
    """Bloomberg's "Daily capacity reached" (category LIMIT) on any request: no request more today - not a first answer,
    not a poll -, the last values stay on the page (not "#N/A"), the status says it; an hour after the day changed one
    probe - one security, one field -, hourly while Bloomberg still says so; once it answers, everything as before."""
    server.daily_capacity = 3
    server.refused.add("USDTRY Curncy")
    server.ref[("USDTRY Curncy", "ASK", ())] = 42.3
    sim = Sim(server).at(dt.datetime(2026, 11, 24, 9, 0))
    keys = [bdp_key("USDTRY Curncy", "ASK"), bdp_key("TRY Curncy", "SETTLE_DT"), bdp_key("TRT150328T24 ISIN", "NAME")]
    sim.run(60, read=keys)
    assert [sim.get(k) for k in keys] == [42.3, "25.11.2026", "TURKGB 36.8 03/15/28"]
    sim.run(20 * 60, read=keys)                                  # the quote's poll at 09:15: Bloomberg says its limit
    st = sim.p.status()
    assert server.capacity_said == 1 and st["bbg_limit"] == "2026-11-24" and st["tier"] == 2
    assert "Bloomberg günlük limiti doldu – yarın yeniden" in st["error"] and "Daily capacity reached." in st["error"]
    assert sim.get(keys[0]) == 42.3                              # the last value stays
    new = bdp_key("EURTRY Curncy", "BID")
    sim.get(new)
    sim.run(14 * 3600, step=60.0, read=keys + [new])             # the rest of the day and the evening: nothing
    assert server.capacity_said == 1 and sim.get(new) == REQUESTING
    sim.run(2 * 3600, step=60.0, read=keys + [new])              # 01:00 of the next day: one probe, still limited
    assert server.capacity_said == 2 and sim.p.status()["bbg_limit"] == "2026-11-24"
    server.daily_capacity = None                                 # Bloomberg's new day
    sim.run(3600, step=60.0, read=keys + [new])                  # 02:00: the next probe answers - the limit is over
    assert server.capacity_said == 2 and not sim.p.status()["bbg_limit"] and sim.p.status()["kinds"].get("probe") == 2
    assert sim.get(new) != REQUESTING                            # (a first answer goes out in any hour)


# ================================================================================================ the status's breakdown
def test_the_days_hits_by_kind_and_by_key(server):
    """What the status window shows: today's hits by kind (first answer, poll, static, daily, hourly, history, a user's
    request ...) and by key - a one-off request by security and field, the history's ranges by series."""
    moving = iter(42.0 + i / 10000.0 for i in range(1000))
    server.refused.add("USDTRY Curncy")
    server.ref[("USDTRY Curncy", "ASK", ())] = lambda: next(moving)
    server.history[("TYSO1 Curncy", "PX_LAST")] = [(dt.date(2026, 11, 23), 37.0)]
    sim = Sim(server).at(dt.datetime(2026, 11, 24, 9, 0))
    ask, name = bdp_key("USDTRY Curncy", "ASK"), bdp_key("TRT150328T24 ISIN", "NAME")
    sim.run(3600, read=[ask, name])                              # first answers, then the quote's polls
    p = sim.p
    p._lookup(("BDH", "TYSO1 Curncy", "PX_LAST", "20261120", "20261124", ()), bloomberg.P_ONCE)      # (as history() does)
    p._items[("BDH", "TYSO1 Curncy", "PX_LAST", "20261120", "20261124", ())].why = bloomberg.HISTORY
    sim.turn()
    assert p.status()["kinds"] == {"first": 2, "poll": 4, "history": 1}       # (polls at 09:15, 09:30, 09:45 and 10:00)
    assert p.usage() == {ask: 5, name: 1, ("HIST", "TYSO1 Curncy", "PX_LAST"): 1}
    assert p.status()["hits_today"] == sum(p.usage().values()) == sim.asked()


def test_market_usage_names_the_sheets_and_fields(service):
    """The status window's breakdown (``/api/market/usage``): the kinds, the top sheets - which workbook sheet asks for
    the key, from the cells -, the top fields; the history's series and Hesapla by name."""
    ck = next(k for k, cells in service._market_callers().items()
              if k[0] == "BDP" and k[2] == "CHG_NET_5D" and any(service.books[b].model.sheets[si].name == "DİBS RV" for b, si, _ in cells))

    class Stub(object):
        live = True

        def status(self):
            return {"hits_today": 13, "budget": 100, "kinds": {"first": 3, "daily": 10}, "tier": 0, "polled": {"value": 2}}

        def usage(self):
            return {ck: 10, ("HIST", "TYSO1 Curncy", "PX_LAST"): 2, ("REF", "/isin/X", "PX_BID"): 1}

    real, mode = service.provider, service.mode
    service.provider, service.mode = Stub(), "live"
    try:
        u = service.market_usage()
    finally:
        service.provider, service.mode = real, mode
    assert u["hits"] == 13 and u["used"] == 13.0 and [k["kind"] for k in u["kinds"]] == ["daily", "first"]
    assert u["sheets"][0]["sheet"] == "DİBS RV" and u["sheets"][0]["hits"] == 10 and u["sheets"][0]["page"] == "dibs"
    assert {s["book_title"] for s in u["sheets"][1:]} == {"Tarihçe (gün sonu, quant, FX)", "Kâğıt Fiyat Yükleme (Hesapla)"}
    assert [(f["field"], f["hits"]) for f in u["fields"]] == [("CHG_NET_5D", 10), ("BDH PX_LAST", 2), ("PX_BID", 1)]
