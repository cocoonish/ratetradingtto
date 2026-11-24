"""Live market data through the Bloomberg Desktop API (``blpapi`` talking to the terminal on this machine,
``localhost:8194``).  Server-side products (B-PIPE / SAPI) need an authorisation step that is not
implemented here.

What is asked for                                how it is served
-----------------------------------------------  ------------------------------------------------------------
``BDP`` real-time fields (BID, ASK, MID,          one ``ReferenceDataRequest`` for the first value, then a
PX_LAST, LAST_PRICE, PX_BID/ASK/MID, HIGH, LOW,   ``//blp/mktdata`` subscription keeps it up to date (streaming
BID_SIZE, ASK_SIZE, VOLUME) without overrides     does not use up the daily data limit)
other ``BDP`` fields / ``BDP`` with overrides     ``ReferenceDataRequest``, once a day (see "Cache first")
``BDH``                                           ``HistoricalDataRequest`` (Days / Fill / Per / Dates options)
``BDS``                                           ``ReferenceDataRequest`` on the bulk field
``BFXFORWARD``                                    no API equivalent: ``#N/A`` (or an optional approximation)
``RTGET`` (Refinitiv)                             not a Bloomberg function: ``#N/A``
daily closes outside of any formula               ``HistoricalDataRequest``, 50 securities per request, asked
(:meth:`BloombergProvider.history`)               afresh on every call
intraday bars outside of any formula              ``IntradayBarRequest``: one security per request (Bloomberg
(:meth:`BloombergProvider.intraday_bars`)         takes one), one hit each, times sent in UTC
one-off reference data outside of any formula     ``ReferenceDataRequest`` on keys of its own, securities × fields
(:meth:`BloombergProvider.reference`)             hits, nothing kept, subscribed to or refreshed

Nothing here blocks the calculation engine: a value that is not known yet is returned as
``#N/A Requesting Data...`` (exactly what Excel shows) and the cells that used it are recalculated as soon
as the answer arrives (:meth:`BloombergProvider.drain_changes`).

Cache first (the desk, 24.11.2026, after Bloomberg's "Daily capacity reached": "Zaten çektiklerini cache atıp daha
fazla çekmemesi gerekliydi").  Every answer is kept for the day - here, and by the dashboard in its database, so that a
restart the same day asks nothing it has - and a key is asked again only for a reason of :func:`policy_of`, and only
while something uses it (a page reads it: :meth:`BloombergProvider._lookup`):

* a quote streams by its subscription; one that does not (a failed or silent subscription) is asked at most every
  15 minutes (``POLL_EVERY``, less often while its answer stays the same), one without any value every 3 hours
  (``POLL_EMPTY``);
* every other field once a day, unless it moves in the day: ``CHG_NET_<n>``, ``LAST_TRADE_DATE``, ``INTERVAL_LOW`` /
  ``_HIGH`` and a ``BDH`` range ending today follow the stream of their security instead (:meth:`_feed`); what moves
  and nothing streams, at most hourly;
* no refresh and no poll outside the desk's hours (:class:`DeskHours`: week days that are not TR holidays, 08:00 -
  19:00 by default); subscriptions keep streaming;
* the day's budget (``budget``): past 70 % only the first answers of keys a page needs, at 100 % nothing new; Bloomberg's
  own daily limit (category ``LIMIT``) stops everything until the next day - one probe an hour after the day changed.

Keeping up with Bloomberg.  The session hands events over through a queue of limited length; a reader that
is too slow first gets a ``SlowConsumerWarning`` and then loses events ("event queue is full, events are
being dropped").  Every call into blpapi releases Python's interpreter lock, and a thread that computes at
the same time (the calculation engine) takes it: measured with blpapi 3.26, a tick that costs 0.06 ms to
read alone costs 6 ms then.  So:

* the dashboard runs this provider in a process of its own (``bbg_process.py``), where nothing else
  computes; inside one process :func:`favour_reader` shortens the hand-over and ticks are conflated;
* a security is subscribed to only once a reference answer has shown that it exists (a sheet such as the
  BIST swap quotes asks for hundreds of maturities that do not);
* the queue is made longer (``queue_size``), a tick is read with as few calls as possible, and what
  Bloomberg says about the queue (``SlowConsumerWarning`` / ``DataLoss``) is counted, shown in
  :meth:`BloombergProvider.status` and repaired by asking the affected values again.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

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
             "BID_SIZE": "BID_SIZE", "ASK_SIZE": "ASK_SIZE",      # order sizes of the BIST swap quotes
             "VOLUME": "VOLUME"}                                  # the day's volume: it grows with every trade (DİBS Canlı)

#: Real-time fields that are gone when a tick carries them without a value: the size of an order.  Shown as
#: "#N/A N/A" then, as in Excel, so that a quote which was withdrawn does not stay on the page.  (A price
#: without a value is left at its last one: for a quote that updates rarely that is all there is.)
CLEARED_WHEN_NULL = ("BID_SIZE", "ASK_SIZE")

#: fields that do not change from one day to the next (asked once a day like the others; their kind in the count)
STATIC_FIELDS = {"NAME", "SECURITY_DES", "CPN", "CPN_TYP", "CPN_FREQ", "MATURITY", "FIRST_CPN_DT", "FLT_SPREAD",
                 "INFLATION_LINKED_INDICATOR", "LAST_TRADEABLE_DT", "CRNCY", "FLOATER_FORMULA", "RESET_IDX",
                 "FWD_SCALE"}                    # the decimals of a pair's forward points (the FX pages)
#: fields that move in the day and that no subscription carries: asked again at most hourly, in the desk's hours
MOVING_FIELDS = {"LAST_UPDATE"}
#: the low / high of a range up to today (DİBS RV's CM:CP): the answer, then the day's streamed low / high beside it
RANGE_FIELDS = {"INTERVAL_LOW": min, "INTERVAL_HIGH": max}
#: ... the real-time field that carries the day's part of the range, by ``MARKET_DATA_OVERRIDE`` (PX_LAST by default)
RANGE_SOURCE = {"PX_LOW": "LOW", "PX_HIGH": "HIGH", "PX_LAST": "LAST_PRICE", "LAST_PRICE": "LAST_PRICE"}
#: the real-time fields whose change tells that a security traded (its last price, its volume of the day) - the
#: service's own reading of trades (``Service.TRADE_FIELDS``)
TRADE_FIELDS = ("LAST_PRICE", "VOLUME")

#: how a key is kept (``_Item.policy``, :func:`policy_of`)
P_QUOTE = "quote"          # a real-time field: its first answer, then its subscription (polled when that does not bring it)
P_STATIC = "static"        # once a day: a field that does not change from day to day
P_DAILY = "daily"          # once a day
P_CHG = "chg"              # CHG_NET_<n>: once a day, then answer + (last price now - last price at the answer)
P_LTD = "ltd"              # LAST_TRADE_DATE: once a day, today as soon as the stream shows a trade
P_RANGE = "range"          # INTERVAL_LOW / _HIGH up to today: once a day, then min / max with the day's streamed low / high
P_BDH = "bdh"              # a BDH range ending today: once a day, its today's point from the stream
P_HOURLY = "hourly"        # moves in the day and nothing streams it: at most hourly in the desk's hours
P_ONCE = "once"            # one-off (history(), bars, reference()): never asked again
#: the policies whose value follows the stream of another key of their security (:meth:`BloombergProvider._feed`)
FED = (P_CHG, P_LTD, P_RANGE, P_BDH)

#: what a hit is counted as (the status page's "Bugünkü veri isteği" by kind; docs/market-data.md)
FIRST = "first"            # a key's first answer since the start: a page needs it
POLL = "poll"              # a quote its subscription does not bring
STATIC = "static"          # a static field's answer of a new day
DAILY = "daily"            # another field's answer of a new day (what Bloomberg did not know, once more, too)
HOURLY = "hourly"          # a field that moves in the day and that nothing streams
HISTORY = "history"        # BDH: a workbook range of a new day / hourly, the history's syncs, the FX pages' history
USER = "user"              # a user's one-off request: Kâğıt Fiyat Yükleme's Hesapla (reference())
RESYNC = "resync"          # values asked again after Bloomberg's event queue overflowed
BARS = "bars"              # intraday bars (the quant package's VİOP page)
PROBE = "probe"            # the one request that tries whether Bloomberg's daily limit is over
KINDS = (FIRST, POLL, STATIC, DAILY, HOURLY, HISTORY, USER, RESYNC, BARS, PROBE)

#: a quote that does not stream (its subscription failed, refused the field or stays silent) and has a value: asked at
#: most this often (seconds) in the desk's hours, whatever its answer does (``price_poll`` may make it longer) ...
POLL_EVERY = 15 * 60.0
#: ... and at twice the interval while its answer stays the same, up to this (an idle quote that answers its old price
#: all day - a BIST swap tenor - costs as little as an empty one; one that moves stays at 15 minutes)
POLL_MAX = 3 * 3600.0
#: a quote without any value ("#N/A N/A"): at the start, then this often in the desk's hours
POLL_EMPTY = 3 * 3600.0
#: a quote that streamed and whose subscription then failed: this often in the desk's hours
POLL_STOPPED = 60 * 60.0
#: what moves in the day and nothing streams (``P_HOURLY``, a fed key whose source does not deliver): this often
HOURLY_EVERY = 3600.0
#: seconds after which a started subscription that has not delivered a field counts as not delivering it
SILENT_AFTER = 30.0
#: answers that no later request will change today: asked again only on another day (an unknown security too: a
#: maturity that did not exist yesterday may exist today)
FINAL_ANSWERS = (INVALID_SECURITY, INVALID_FIELD, NOT_APPLICABLE)
#: undelivered events the session may hold (blpapi's own default is 10 000: the first paint of a few
#: thousand subscriptions alone is more than that)
QUEUE_SIZE = 100000
#: a new subscription waits this long for the reference answer that says whether the security exists
SUBSCRIBE_WAIT = 60.0
#: seconds between two rounds of asking again what a full queue may have dropped ...
RESYNC_EVERY = 60.0
#: ... and how long the queue must have been quiet before the first one
RESYNC_SETTLE = 2.0
#: values asked again per day at most: a reader that keeps falling behind must not use up the terminal's
#: daily data limit by repairing itself (the losses stay visible in the status)
RESYNC_BUDGET = 2000
#: after the queue overflowed without saying which subscriptions lost data: those that ticked this long (seconds)
#: before it filled up and not since it cleared are asked again (a quiet one lost nothing; an active one ticks again)
RESYNC_ACTIVE = 600.0
#: the dashboard's own daily budget of hits (``--daily-budget``): past ``BUDGET_WARN`` of it only the first answers of
#: keys a page needs go out, at 100 % nothing new; ``--max-hits`` stays the absolute stop beside it
BUDGET = 100000
BUDGET_WARN = 0.70
#: Bloomberg's own daily limit ("Daily capacity reached", category LIMIT): nothing is asked until one probe, this long
#: after the day changed, answers (then again this often while it does not)
PROBE_AFTER = 3600.0
#: the status counts the quotes polled and the keys fed by the stream at most this often (seconds)
SCAN_EVERY = 1.0

#: Identifier types the Excel add-in accepts *after* an identifier - "TRT150328T24 ISIN", with a pricing source
#: "TRT150328T24 @ISL1 ISIN" - and the prefix the API wants instead: "/isin/TRT150328T24@ISL1".  Sent to the
#: API as typed in Excel, such a security comes back as "#N/A Invalid Security".
ID_TYPES = {"ISIN": "isin", "CUSIP": "cusip", "CINS": "cins", "SEDOL": "sedol1", "SEDOL1": "sedol1",
            "SEDOL2": "sedol2", "BUID": "buid", "WPK": "wpk", "COMMON": "common", "FIGI": "bbgid", "BBGID": "bbgid"}

#: Istanbul time - in which the dashboard writes the times of intraday bars - is UTC+3, and Bloomberg takes and gives
#: them in UTC.  Türkiye has kept UTC+3 all year since September 2016 (no daylight saving), so a fixed offset is exact
#: for every day Bloomberg keeps bars of; and Windows' Python 3.9 has no time-zone database to ask (no tzdata).
ISTANBUL = _dt.timedelta(hours=3)
#: the event types an ``IntradayBarRequest`` takes
BAR_EVENTS = ("TRADE", "BID", "ASK", "BID_BEST", "ASK_BEST", "BEST_BID", "BEST_ASK")


def api_security(sec: str) -> str:
    """The security as the Bloomberg API takes it (the workbook writes it the way Excel's add-in does)."""
    if sec.startswith("/"):
        return sec
    parts = sec.split()
    if len(parts) >= 2:
        kind = ID_TYPES.get(parts[-1].upper())
        if kind is not None:
            return "/%s/%s" % (kind, "".join(parts[:-1]))
    return sec


def bar_span(start: str, end: str, interval: int, event: str) -> Tuple[_dt.datetime, _dt.datetime, int, str]:
    """An intraday bar request as Bloomberg takes it: the span's Istanbul times ("YYYY-MM-DD HH:MM") in UTC, the bar
    length in whole minutes (1 - 1440) and the event type.  ``ValueError`` for what it would refuse."""
    span = []
    for text in (start, end):
        try:
            t = _dt.datetime.fromisoformat(str(text).strip())
        except ValueError:
            raise ValueError("gün içi bar: zaman 'YYYY-MM-DD SS:DD' biçiminde olmalı, %r değil" % (text,)) from None
        span.append(t.astimezone(_dt.timezone.utc).replace(tzinfo=None) if t.tzinfo is not None else t - ISTANBUL)
    try:
        minutes = int(interval)
    except (TypeError, ValueError):
        minutes = 0
    if minutes != interval or not 1 <= minutes <= 1440:
        raise ValueError("gün içi bar: bar uzunluğu 1 – 1440 dakika olmalı, %r değil" % (interval,))
    kind = str(event).strip().upper()
    if kind not in BAR_EVENTS:
        raise ValueError("gün içi bar: olay türü %s olmalı, %r değil" % (" / ".join(BAR_EVENTS), event))
    return span[0], span[1], minutes, kind


def range_source(key: Tuple, today: str) -> Tuple[Optional[str], bool]:
    """An ``INTERVAL_LOW`` / ``_HIGH`` key: (the real-time field that carries the day's part of its range - None when
    none does -, whether the range ended before ``today`` (YYYYMMDD): then it does not move any more)."""
    ov = dict(key[3])
    end = str(ov.get("END_DATE_OVERRIDE") or today)
    if end < today:
        return None, True
    return RANGE_SOURCE.get(str(ov.get("MARKET_DATA_OVERRIDE") or "PX_LAST").upper()), False


def policy_of(key: Tuple, today: str) -> Tuple[str, Optional[str]]:
    """How a key of the workbooks is kept - (its policy, its real-time field or None); ``today`` as YYYYMMDD.  The
    reason for each (docs/market-data.md, "What costs hits"):

    * a real-time field without overrides streams (``P_QUOTE``); with overrides it is an ordinary field;
    * ``CHG_NET_<n>`` is the last price less the close n days ago - a close that does not move in the day: it follows
      the streamed last price (``P_CHG``);
    * ``LAST_TRADE_DATE`` is today once the stream shows a trade (``P_LTD``);
    * ``INTERVAL_LOW`` / ``_HIGH`` up to today follow the day's streamed low / high (``P_RANGE``); a range that ended is
      fixed; one whose day part nothing carries moves hourly;
    * a ``BDH`` range ending today takes its today's point from the stream (``P_BDH``); one that ended is fixed;
    * ``LAST_UPDATE``, other ``CHG_`` fields, ``YAS_`` fields without the price / yield they start from (overrides) and
      the forward curve of the BFXFORWARD approximation move and nothing streams them: hourly;
    * everything else does not move in the day: once a day (``P_STATIC`` / ``P_DAILY``)."""
    kind = key[0]
    if kind == "BDP":
        field, overrides = key[2], key[3]
        if not overrides:
            rt = RT_FIELDS.get(field)
            if rt is not None:
                return P_QUOTE, rt
        if field in STATIC_FIELDS:
            return P_STATIC, None
        if not overrides and field.startswith("CHG_NET_"):
            return P_CHG, None
        if not overrides and field == "LAST_TRADE_DATE":
            return P_LTD, None
        if field in RANGE_FIELDS:
            src, ended = range_source(key, today)
            return (P_DAILY if ended else P_RANGE if src else P_HOURLY), None
        if field in MOVING_FIELDS or field.startswith("CHG_") or (field.startswith("YAS_") and not overrides):
            return P_HOURLY, None
        return P_DAILY, None
    if kind == "BDS":
        return (P_HOURLY if key[2] == "FWD_CURVE" else P_STATIC), None
    if kind == "BDH":
        return (P_BDH if key[4] >= today else P_DAILY), None
    return P_DAILY, None


def usage_key(key: Tuple, policy: Optional[str] = None) -> Tuple:
    """What a hit is counted under for the status page's breakdown: a workbook key as it is; the history's / the FX
    pages' series (``history()``'s one-off ranges) by security and field, a one-off reference request by security and
    field, a bar request by security."""
    kind = key[0]
    if kind == "BDH" and policy == P_ONCE:
        return ("HIST", key[1], key[2])
    if kind == "REF":
        return ("REF", key[1], key[2])
    if kind == "BAR":
        return ("BAR", key[1])
    return key


_PERIODICITY = {"D": "DAILY", "W": "WEEKLY", "M": "MONTHLY", "Q": "QUARTERLY", "S": "SEMI_ANNUALLY", "Y": "YEARLY"}
_DAYS = {"W": "NON_TRADING_WEEKDAYS", "A": "ALL_CALENDAR_DAYS", "C": "ALL_CALENDAR_DAYS", "T": "ACTIVE_DAYS_ONLY"}
_FILL = {"P": "PREVIOUS_VALUE", "B": "NIL_VALUE", "N": "NIL_VALUE"}


def _override_value(name: str, value: str) -> str:
    """Date overrides typed as an Excel serial number are sent as YYYYMMDD."""
    if ("_DT" in name or "DATE" in name) and value.isdigit() and len(value) == 5 and 20000 < int(value) < 80000:
        return serial_to_date(float(value)).strftime("%Y%m%d")
    return value


def _hhmm(text: str) -> _dt.time:
    h, _, m = str(text).strip().replace(".", ":").partition(":")
    return _dt.time(int(h), int(m or 0))


class DeskHours(object):
    """When Bloomberg may be asked again (refreshes, polls, repairs): the desk's days - week days that are not on its
    TR holiday list - from ``open_`` to ``close`` (HH:MM, the computer's local time: Istanbul's on the desk's).  Outside
    them (quiet hours) nothing is asked again; subscriptions keep streaming and a key never answered is still asked."""

    def __init__(self, open_: str = "08:00", close: str = "19:00", holidays: Iterable[str] = ()):
        self.open, self.close = _hhmm(open_), _hhmm(close)
        self.holidays = frozenset(str(d) for d in holidays)

    def open_at(self, t: float) -> bool:
        d = _dt.datetime.fromtimestamp(t)
        if d.weekday() >= 5 or d.date().isoformat() in self.holidays:
            return False
        return self.open <= d.time() < self.close

    def as_dict(self) -> Dict[str, Any]:
        return {"open": self.open.strftime("%H:%M"), "close": self.close.strftime("%H:%M"), "holidays": len(self.holidays)}


class _Item(object):
    __slots__ = ("state", "fetched", "day", "used", "at", "policy", "streamed", "poll", "rt", "why", "base", "anchor",
                 "points")

    def __init__(self, policy: str = P_DAILY, rt: bool = False):
        self.state = "queued"        # queued | sent | ok | gone (a one-off key Bloomberg's limit refused)
        self.fetched = 0.0           # when its last answer came (a request's, or the one kept from earlier today)
        self.day = 0                 # ... that day (an ordinal): a key answered today is not asked again today
        self.used = 0                # the day it was last read (an ordinal): only what is used is ever asked again
        self.at = 0.0                # when its value last changed (an answer, a tick, the stream it follows)
        self.policy = policy         # how it is kept (P_*)
        self.streamed = 0.0          # time of the last value that came from a subscription
        self.poll = 0.0              # current interval of a polled real-time field (0: not polled yet); backs off
        self.rt = rt                 # a real-time field (a quote)
        self.why = FIRST             # what its pending request is counted as (KINDS)
        self.base = None             # a fed key: Bloomberg's own answer (its value is worked out from it)
        self.anchor = None           # CHG_NET_<n>: the last price at that answer
        self.points = None           # a BDH range ending today: its [(day serial, value)] as Bloomberg gave them


class _Request(object):
    __slots__ = ("kind", "keys", "sent", "wanted", "parts", "probe", "limited")

    def __init__(self, kind: str, keys: List[Tuple], wanted: Dict[str, List[Tuple]], sent: float):
        self.kind = kind
        self.keys = keys
        self.sent = sent
        self.wanted = wanted         # security -> keys expected for it
        self.parts: Optional[List[Any]] = []     # an answer in several messages (intraday bars) so far; None: unusable
        self.probe = False           # the one request that tries whether Bloomberg's daily limit is over
        self.limited = False         # Bloomberg answered it with its daily limit


class _Sub(object):
    __slots__ = ("cid", "fields", "sent_fields", "names", "state", "bad", "since", "created", "plain", "heard", "ticked")

    def __init__(self, cid: int, now: float):
        self.cid = cid
        self.fields: Set[str] = set()
        self.sent_fields: Set[str] = set()
        self.names: Tuple = ()       # (field, blpapi Name) of the fields sent: what a tick is searched for
        self.state = "new"           # new | pending | started | failed | invalid (no such security)
        self.bad: Set[str] = set()
        self.since = 0.0
        self.created = now
        self.plain = False           # subscribe without the conflation option (it was refused with it)
        self.heard = False           # a message of the stream has arrived (its first picture, a tick)
        self.ticked = 0.0            # when the last message of the stream arrived


def favour_reader(interval: float = 0.001) -> Dict[str, Any]:
    """For a provider that shares its process with the calculation engine: let the thread that reads from
    Bloomberg have the interpreter sooner when it asks for it.

    A thread that wants Python's interpreter lock waits one "switch interval" (5 ms by default) before the
    thread that holds it is told to let go; the reader loses the lock on its calls into blpapi all the
    time.  On Windows a wait of that length really takes until the next tick of the system clock (up to
    15.6 ms) unless the process asks for the finer clock.  Returns what was changed.
    """
    done: Dict[str, Any] = {}
    try:
        if sys.getswitchinterval() > interval:
            sys.setswitchinterval(interval)
            done["switch_interval"] = interval
    except Exception:  # noqa: BLE001 - tuning only
        pass
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415
            ctypes.windll.winmm.timeBeginPeriod(1)
            done["timer_ms"] = 1
        except Exception:  # noqa: BLE001
            pass
    return done


class BloombergProvider(Provider):
    live = True

    def __init__(self, host: str = "localhost", port: int = 8194, stream: bool = True, price_poll: float = POLL_EVERY,
                 request_timeout: float = 45.0, max_hits_per_day: int = 400000, bfx: str = "off",
                 blpapi_module=None, reconnect_wait: float = 10.0, queue_size: int = QUEUE_SIZE,
                 interval: float = 0.0, budget: int = BUDGET, clock: Optional[Callable[[], float]] = None):
        self.host = host
        self.port = int(port)
        self.stream = stream
        self.price_poll = float(price_poll)      # a quote that does not stream: asked at most this often (seconds)
        self.request_timeout = float(request_timeout)
        self.max_hits_per_day = int(max_hits_per_day)
        self.budget = int(budget or 0)           # the dashboard's own daily budget of hits (0: none)
        self.bfx_mode = bfx
        self.reconnect_wait = float(reconnect_wait)
        self.queue_size = int(queue_size or 0)       # undelivered events the session may hold (0: blpapi's default)
        self.interval = max(0.0, float(interval or 0.0))   # seconds between two ticks of a subscription (0: every tick)
        self.clock = clock or time.time          # seconds since the epoch (a test's simulated clock)
        self._bp = blpapi_module
        self._lock = threading.RLock()
        self._values: Dict[Tuple, Any] = {}
        self._items: Dict[Tuple, _Item] = {}
        self._queue: List[Tuple] = []
        self._changed: Set[Tuple] = set()
        self._requests: Dict[int, _Request] = {}
        self._subs: Dict[str, _Sub] = {}
        self._sub_by_cid: Dict[int, str] = {}
        self._rt_keys: Dict[Tuple[str, str], List[Tuple]] = {}      # (security, real-time field) -> its keys
        self._feeds: Dict[Tuple[str, str], Set[Tuple]] = {}         # (security, real-time field) -> keys that follow it
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
        self.hits_day = self._today()
        self._day_no = self.hits_day.toordinal()          # today, as the items keep their days
        self._day_text = (0, "")                          # (the day, it as YYYYMMDD)
        self._day_serial = float(date_to_serial(self.hits_day))
        self.kinds: Dict[str, int] = {}                     # today's hits by what they were for (KINDS)
        self.key_hits: Dict[Tuple, int] = {}               # ... by key (usage_key): the status page's sheets / fields
        self.usage_rev = 0                                 # bumped with every hit counted
        self.requests_sent = 0
        self.ticks = 0
        self.last_tick = 0.0
        self.last_error = ""
        self.limit_reached = False                        # the day's --max-hits or budget is used up
        self.limit_day: Optional[int] = None              # Bloomberg's own daily limit was reached that day (an ordinal)
        self.limit_text = ""                              # ... what Bloomberg said
        self._probe_at = 0.0                              # ... the next probe no sooner than this
        self.desk: Optional[DeskHours] = None             # None: no quiet hours (a provider of its own: a test, a check)
        self._desk_seen = (0.0, True)                     # (when worked out, open then)
        self._trade_prev: Dict[Tuple[str, str], float] = {}     # (security, LAST_PRICE / VOLUME) -> its last value today
        self._traded: Dict[str, int] = {}                 # security -> the day the stream showed it trade
        self._scan_at = 0.0
        self._polled = {"value": 0, "empty": 0, "stopped": 0}    # quotes that do not stream (the last scan's count)
        self._fed_now = 0                                 # keys kept current by the stream instead of asked again
        # what Bloomberg said about its event queue (see the module text)
        self.slow = False                # between a SlowConsumerWarning and its ...Cleared
        self.slow_warnings = 0
        self.events_dropped = 0          # events the session threw away because the queue was full
        self.messages_lost = 0           # ... as reported per subscription (DataLoss)
        self.resyncs = 0                 # values asked again after such a loss
        self._resyncs_today = 0
        self._resync: Set[str] = set()   # securities whose subscription lost data
        self._resync_all = False
        self._resync_at = 0.0
        self._slow_at = 0.0              # when the queue last said it filled up or cleared
        self._slow_since = 0.0           # when it last started filling up
        # answers kept from earlier today (before a restart): key -> (value, when it was fetched) - taken as answered
        # when the workbook asks for them, and asked again when they are due
        self._preload: Dict[Tuple, Tuple[Any, float]] = {}

    # ================================================================== time
    def _now(self) -> float:
        return float(self.clock())

    def _today(self) -> _dt.date:
        return _dt.date.fromtimestamp(self._now())

    def _today_text(self) -> str:
        """Today as YYYYMMDD (worked out once a day: every read of a Bloomberg cell asks it)."""
        day = self._day_no
        if self._day_text[0] != day:
            self._day_text = (day, _dt.date.fromordinal(day).strftime("%Y%m%d"))
        return self._day_text[1]

    def set_desk_hours(self, open_: str = "08:00", close: str = "19:00", holidays: Iterable[str] = ()) -> None:
        """The desk's hours (:class:`DeskHours`): no refresh and no poll outside them."""
        desk = DeskHours(open_, close, holidays)
        with self._lock:
            self.desk = desk
            self._desk_seen = (0.0, True)
        self._wake.set()

    def _desk_open(self, now: float) -> bool:
        """In the desk's hours now (lock held by the caller; worked out at most every few seconds)."""
        if self.desk is None:
            return True
        t, hit = self._desk_seen
        if 0.0 <= now - t < 5.0:
            return hit
        hit = self.desk.open_at(now)
        self._desk_seen = (now, hit)
        return hit

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
        tuning = [("setAutoRestartOnDisconnection", True), ("setNumStartAttempts", 2)]
        if self.queue_size > 0:
            tuning.append(("setMaxEventQueueSize", self.queue_size))
        for setter, value in tuning:
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
                    self.last_error = "%s açılamadı – fiyatlar sorguyla güncellenecek" % MKTDATA
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
    def _lookup(self, key: Tuple, policy: str, rt_field: Optional[str] = None) -> Any:
        """The value of ``key`` (``#N/A Requesting Data...`` until its first answer), noting that it is used today: a key
        is asked again only while it is read (yesterday's ranges, a bond gone from a list are left alone)."""
        with self._lock:
            it = self._items.get(key)
            if it is not None:
                it.used = self._day_no
                v = self._values.get(key)
                return v if v is not None else REQUESTING
            it = _Item(policy, rt_field is not None)
            it.used = self._day_no
            self._items[key] = it
            if rt_field is not None:
                self._rt_keys.setdefault((key[1], rt_field), []).append(key)
                if self.stream:
                    sub = self._subs.get(key[1])
                    if sub is None:
                        self._cid += 1
                        sub = _Sub(self._cid, self._now())
                        self._subs[key[1]] = sub
                        self._sub_by_cid[sub.cid] = key[1]
                    sub.fields.add(rt_field)
            self._follow(key, it)
            kept = self._preload.pop(key, None) if policy != P_ONCE else None
            if kept is not None:
                # answered earlier today, before a restart: as it was, until it is due again
                value, fetched = kept
                it.state = "ok"
                it.fetched = it.at = fetched
                it.day = _dt.date.fromtimestamp(fetched).toordinal()
                it.why = ""
                if policy in FED:
                    it.base = value                      # (what it showed: its stream picks it up from there)
                    if policy == P_CHG:
                        it.anchor = self._source(key[1], "LAST_PRICE")
                self._values[key] = value
                if rt_field is not None and type(value) is float:
                    self._feed(key[1], rt_field, value)  # (what follows it starts from the same moment)
                return value
            it.why = FIRST
            self._queue.append(key)
            self._wake.set()
            return REQUESTING

    def get_bdp(self, key: Tuple) -> Any:
        policy, rt = policy_of(key, self._today_text())
        return self._lookup(key, policy, rt)

    def get_bds(self, key: Tuple) -> Any:
        policy, _ = policy_of(key, self._today_text())
        return self._lookup(key, policy)

    def get_bdh(self, key: Tuple) -> Any:
        policy, _ = policy_of(key, self._today_text())
        return self._lookup(key, policy)

    def get_bfx(self, key: Tuple) -> Any:
        if self.bfx_mode != "approx":
            return NO_BFX
        return self._bfx_approx(key)

    def get_rt(self, key: Tuple) -> Any:
        return NO_RT

    def quote(self, security: str, field: str = "PX_LAST") -> Optional[float]:
        """The value a quote of ``security`` has now (the real-time field ``field`` stands for, kept by its subscription
        or its polls) - ``None`` when no page asks for one: nothing is asked here (the history's today's point)."""
        rt = RT_FIELDS.get(str(field).upper())
        if rt is None:
            return None
        with self._lock:
            return self._source(security, rt)

    # ================================================================== kept for a restart of the same day
    def preload(self, answers) -> None:
        """Answers kept from earlier today - ``[(key, value, fetched), ...]``, quotes too: taken as answered when the
        workbook asks for them (no request), asked again when they are due.  Before :meth:`start`."""
        with self._lock:
            for key, value, fetched in answers:
                if value is not None and value != REQUESTING:
                    self._preload[key] = (value, float(fetched))

    def answers(self, since: float = 0.0) -> List[Tuple[Tuple, Any, float]]:
        """Every answer that changed after ``since`` - ``[(key, value, when), ...]``: quotes, what Bloomberg did not
        know, what follows the stream; not the one-off requests - what a restart the same day need not ask again."""
        out = []
        with self._lock:
            for key, it in self._items.items():
                if it.policy == P_ONCE or it.state not in ("ok", "queued", "sent") or it.at <= since:
                    continue
                v = self._values.get(key)
                if v is not None and v != REQUESTING:
                    out.append((key, v, it.at))
        return out

    def carry_hits(self, hits: int) -> None:
        """The data points already used today (by an earlier run): the daily limit counts them.  Before start."""
        self._roll_day()
        self.hits = max(self.hits, int(hits))

    def carry_day(self, kinds: Optional[Dict[str, int]] = None, usage: Optional[Dict[Tuple, int]] = None,
                  limit: Optional[str] = None) -> None:
        """What an earlier run counted today - the hits by kind and by key - and the day Bloomberg's own daily limit was
        reached (ISO; nothing is asked until its probe answers).  Before start."""
        self._roll_day()
        with self._lock:
            for k, n in (kinds or {}).items():
                self.kinds[k] = max(self.kinds.get(k, 0), int(n))
            for k, n in (usage or {}).items():
                self.key_hits[k] = max(self.key_hits.get(k, 0), int(n))
            if limit:
                try:
                    self.limit_day = _dt.date.fromisoformat(str(limit)).toordinal()
                    self.limit_text = self.limit_text or "Daily capacity reached."
                    self.last_error = self._limit_words()
                except ValueError:
                    pass
            self.usage_rev += 1

    def usage(self) -> Dict[Tuple, int]:
        """Today's hits by key (:func:`usage_key`)."""
        with self._lock:
            return dict(self.key_hits)

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

    def _wait(self, keys: Iterable[Tuple], timeout: float) -> None:
        """Until every key has its answer (or was refused by Bloomberg's limit) or ``timeout`` has passed - real time,
        whatever the provider's clock: the caller's thread waits."""
        keys = list(keys)
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stop.is_set():
            with self._lock:
                if all(self._items.get(k) is not None and self._items[k].state in ("ok", "gone") for k in keys):
                    return
            time.sleep(0.05)

    def history(self, items, start, end, timeout=60.0):
        """Daily closes by ``HistoricalDataRequest`` (trading days only, nothing filled in).  Asked afresh on
        every call; items that share the field go out together, 50 securities per request.  Blocks until the
        answers are in or ``timeout`` has passed - items still outstanding then are simply not returned.  Nothing is
        asked past 70 % of the day's budget or at Bloomberg's limit (``{}``: asked again another time)."""
        with self._lock:
            if self._tier() > 0:
                return {}
        keys = {(sec, fld.upper()): ("BDH", sec, fld.upper(), start, end, ()) for sec, fld in items}
        with self._lock:
            for k in keys.values():
                it = self._items.get(k)
                if it is not None and it.state in ("ok", "gone"):        # an earlier answer: forget it and ask again
                    del self._items[k]
                    self._values.pop(k, None)
                    self._changed.discard(k)
            for k in keys.values():
                self._lookup(k, P_ONCE)
                it = self._items.get(k)
                if it is not None and it.state == "queued":
                    it.why = HISTORY
        self._wait(keys.values(), timeout)
        out: Dict[Tuple[str, str], List[Tuple[str, float]]] = {}
        with self._lock:
            for item, k in keys.items():
                it = self._items.get(k)
                if it is None or it.state != "ok":
                    if it is not None and it.state == "gone":
                        self._items.pop(k, None)
                    continue                                     # still on its way: the next call picks it up
                v = self._values.pop(k, None)
                del self._items[k]
                self._changed.discard(k)
                if type(v) is not XlArray:
                    continue
                rows = [(serial_to_date(r[0]).isoformat(), r[1]) for r in v.rows
                        if len(r) > 1 and type(r[0]) is float and type(r[1]) is float]
                if rows:
                    out[item] = rows
        return out

    def intraday_bars(self, security: str, start: str, end: str, interval: int = 5, event: str = "TRADE",
                      timeout: float = 60.0) -> Optional[List[Tuple[str, float, float, float, float, float]]]:
        """Intraday bars by ``IntradayBarRequest`` (what the call returns: :meth:`Provider.intraday_bars`).  One
        request per call - Bloomberg takes one security per request - and one hit; none past 70 % of the day's budget,
        at ``max_hits_per_day`` or at Bloomberg's limit.  The times go to Bloomberg in UTC; give a start on the bar
        length's grid (a midnight, 09:30 for 5-minute bars) to get bars on it.  A long span comes in several parts, put
        together here.  Asked afresh on every call, nothing is kept.  Blocks until the answer is in or ``timeout`` has
        passed - never call it on the calculation thread.  ``ValueError`` for what Bloomberg would refuse (a time not
        written "YYYY-MM-DD HH:MM", a bar length outside 1 - 1440 minutes, an event type it does not know)."""
        t0, t1, interval, event = bar_span(start, end, interval, event)
        if t1 <= t0:
            return []                                    # an empty span: nothing to ask
        with self._lock:
            if self._tier() > 0:
                return None                              # the daily data limit: not one request more
            self._cid += 1                               # a key of its own: two calls never share an answer
            key = ("BAR", security, t0, t1, interval, event, self._cid)
            self._lookup(key, P_ONCE)
            self._items[key].why = BARS
        self._wait([key], timeout)
        with self._lock:
            # forgotten either way, with a request still on its way: an answer that comes after the call gave up is
            # dropped, and nothing is sent again for it
            it = self._items.pop(key, None)
            value = self._values.pop(key, None)
            self._changed.discard(key)
            for cid in [c for c, r in self._requests.items() if r.kind == "BAR" and r.keys[0] == key]:
                del self._requests[cid]
        if it is None or it.state != "ok" or type(value) is not list:
            return None                                  # not in time, or Bloomberg could not answer it now
        return value

    def reference(self, securities, fields, timeout: float = 30.0) -> Optional[Dict[str, Dict[str, Any]]]:
        """A one-off ``ReferenceDataRequest`` outside of any formula (what the call returns:
        :meth:`Provider.reference`): securities × fields hits, counted as every request is (a user's request: it goes
        out past 70 % of the day's budget, not at 100 %, at ``max_hits_per_day`` or at Bloomberg's limit), in one request
        per 100 securities.  Its keys are its own (``("REF", security, FIELD, call)``): a workbook cell asking the same
        field never shares, loses or refreshes them, and nothing is subscribed to or asked again - an answer that comes
        after the call gave up is dropped.  None at the limit or when the answer did not come in time.  Blocks - never
        call it on the calculation thread."""
        secs = list(dict.fromkeys(str(s).strip() for s in securities if str(s or "").strip()))
        flds = list(dict.fromkeys(str(f).strip().upper() for f in fields if str(f or "").strip()))
        if not secs or not flds:
            return {}
        with self._lock:
            if self._tier() > 1:
                return None                              # the daily data limit: not one request more
            self._cid += 1                               # keys of its own: two calls never share an answer
            call = self._cid
        keys = {(s, f): ("REF", s, f, call) for s in secs for f in flds}
        with self._lock:                                 # (queued at once: the worker sends the call as one request)
            for k in keys.values():
                self._lookup(k, P_ONCE)                  # (never asked again)
                self._items[k].why = USER
        self._wait(keys.values(), timeout)
        out: Dict[str, Dict[str, Any]] = {}
        done = True
        with self._lock:
            # forgotten either way, with a request still on its way (as a bar call's)
            for (s, f), k in keys.items():
                it = self._items.pop(k, None)
                value = self._values.pop(k, None)
                self._changed.discard(k)
                if it is None or it.state != "ok":
                    done = False
                else:
                    out.setdefault(s, {})[f] = value
            for cid in [c for c, r in self._requests.items() if r.kind == "REF" and r.keys and r.keys[0][3] == call]:
                del self._requests[cid]
        return out if done else None

    # ================================================================== the day's budget
    def _tier(self) -> int:
        """0: everything; 1: past ``BUDGET_WARN`` of the day's budget - only the first answers of keys a page needs (and
        a user's one-off request); 2: nothing new - the budget or ``max_hits_per_day`` is used up, or Bloomberg said
        its daily limit is reached (lock held by the caller)."""
        if self.limit_day is not None:
            return 2
        if (self.max_hits_per_day and self.hits >= self.max_hits_per_day) or (self.budget and self.hits >= self.budget):
            return 2
        if self.budget and self.hits >= BUDGET_WARN * self.budget:
            return 1
        return 0

    def _limit_words(self) -> str:
        return "Bloomberg günlük limiti doldu – yarın yeniden (%s); yeni istek gönderilmiyor, son değerler gösteriliyor" % (
            self.limit_text or "Daily capacity reached.")

    def status(self) -> Dict[str, Any]:
        now = self._now()
        with self._lock:
            tier = self._tier()
            return {"mode": "live", "connected": self.connected, "host": "%s:%d" % (self.host, self.port),
                    "items": len(self._values), "pending": len(self._queue) + sum(len(r.keys) for r in self._requests.values()),
                    "subscriptions": sum(1 for s in self._subs.values() if s.state == "started"),
                    "subscriptions_failed": sum(1 for s in self._subs.values() if s.state == "failed"),
                    "subscriptions_invalid": sum(1 for s in self._subs.values() if s.state == "invalid"),
                    "streaming": self.stream, "requests": self.requests_sent, "hits_today": self.hits, "ticks": self.ticks,
                    "last_tick": self.last_tick, "limit_reached": self.limit_reached, "error": self.last_error,
                    "bfx": self.bfx_mode, "isolated": False, "interval": self.interval, "queue_size": self.queue_size,
                    "slow": self.slow, "slow_warnings": self.slow_warnings, "events_dropped": self.events_dropped,
                    "messages_lost": self.messages_lost, "resyncs": self.resyncs,
                    # cache first (docs/market-data.md): the day's budget, what the hits went to, Bloomberg's own limit,
                    # the desk's hours, the quotes polled and the keys the stream keeps current
                    "budget": self.budget, "max_hits": self.max_hits_per_day, "tier": tier,
                    "kinds": dict(self.kinds),
                    "bbg_limit": _dt.date.fromordinal(self.limit_day).isoformat() if self.limit_day is not None else "",
                    "bbg_limit_text": self.limit_text if self.limit_day is not None else "",
                    "desk": self.desk.as_dict() if self.desk is not None else None,
                    "quiet": not self._desk_open(now),
                    "polled": dict(self._polled), "poll_every": self.price_poll, "poll_empty": POLL_EMPTY,
                    "fed": self._fed_now}

    def unknown(self) -> List[Tuple[Tuple, str]]:
        """The calls Bloomberg answered with "no such security", "no such field" or "field not applicable"
        (in the helper's case: the answers it passed on)."""
        with self._lock:
            return [(k, v) for k, v in self._values.items() if type(v) is str and v in FINAL_ANSWERS]

    # ================================================================== values
    def _set(self, key: Tuple, value: Any, streamed: bool = False, tick: bool = False) -> None:
        """Store a value (lock held by the caller): Bloomberg's answer to a request, or a message of a subscription
        (``tick``: a later one, not its first picture)."""
        it = self._items.get(key)
        if it is None:
            it = _Item(P_ONCE)
            self._items[key] = it
        now = self._now()
        it.state = "ok"
        old = self._values.get(key)
        if streamed:
            it.streamed = now
            it.poll = 0.0                                # the subscription delivers: no need to poll
        else:
            if it.rt:                                    # a quote asked by request: the same answer again -> ask less often
                if type(value) is float:
                    it.poll = min(max(it.poll, self.price_poll) * 2.0, max(POLL_MAX, self.price_poll)) \
                        if (it.poll and type(old) is float and old == value) else self.price_poll
            elif it.policy in FED:
                value = self._answered(key, it, value)
            it.fetched = now
            it.day = self._day_no
        if type(old) is XlArray and type(value) is XlArray:
            same = old.rows == value.rows
        else:
            same = type(old) is type(value) and old == value
        if not same:
            self._values[key] = value
            self._changed.add(key)
            it.at = now
            if it.rt and old == INVALID_SECURITY:
                sub = self._subs.get(key[1])
                if sub is not None and sub.state == "invalid":
                    sub.state = "new"                    # it exists after all (a maturity that did not exist yesterday)
                    sub.created = now
        if it.rt and type(value) is float:
            self._feed(key[1], RT_FIELDS.get(key[2], key[2]), value, tick and type(old) is str and old not in FINAL_ANSWERS)

    def _put(self, key: Tuple, value: Any) -> None:
        """A value worked out from the stream (lock held by the caller): not an answer - when the key was answered
        and when it is due again stay as they were."""
        it = self._items.get(key)
        if it is None or it.state != "ok":
            return
        old = self._values.get(key)
        if type(old) is XlArray and type(value) is XlArray:
            if old.rows == value.rows:
                return
        elif type(old) is type(value) and old == value:
            return
        self._values[key] = value
        self._changed.add(key)
        it.at = self._now()

    # ================================================================== what follows the stream
    def _follow(self, key: Tuple, it: _Item) -> None:
        """A key whose value follows the stream of its security: what it listens to (lock held by the caller)."""
        if it.policy == P_CHG:
            src = "LAST_PRICE"
        elif it.policy == P_LTD:
            src = "TRADE"                                # (any trade: :meth:`_trade`)
        elif it.policy == P_RANGE:
            src = range_source(key, self._today_text())[0]
        elif it.policy == P_BDH:
            src = RT_FIELDS.get(key[2])
        else:
            return
        if src:
            self._feeds.setdefault((key[1], src), set()).add(key)

    def _source(self, security: str, rt_field: str) -> Optional[float]:
        """The value a real-time field of a security has now - any key of it with a number (lock held)."""
        for k in self._rt_keys.get((security, rt_field), ()):
            v = self._values.get(k)
            if type(v) is float:
                return v
        return None

    def _answered(self, key: Tuple, it: _Item, value: Any) -> Any:
        """Bloomberg's answer for a key that follows the stream: kept as the base, and what it shows now (lock held)."""
        sec = key[1]
        it.base = value
        if it.policy == P_CHG:
            # the change since the close n days ago: that close does not move in the day, so from here on the change
            # moves with the last price (``_feed``) - the answer is taken as Bloomberg's at the last price seen now
            it.anchor = self._source(sec, "LAST_PRICE")
            return value
        if it.policy == P_LTD:
            return tr_date_text(_dt.date.fromordinal(self._day_no)) if self._traded.get(sec) == self._day_no else value
        if it.policy == P_RANGE:
            return self._ranged(key, value, self._source(sec, range_source(key, self._today_text())[0] or ""))
        if it.policy == P_BDH:
            return self._today_point(key, it, self._source(sec, RT_FIELDS.get(key[2], "")))
        return value

    def _feed(self, security: str, rt_field: str, value: float, first_tick: bool = False) -> None:
        """A real-time field of ``security`` has a new value (a tick, a poll's answer): the keys that follow it (lock
        held by the caller).  ``first_tick``: a tick brought the field's first value - it had an answer without one."""
        if rt_field in TRADE_FIELDS:
            self._trade(security, rt_field, value, first_tick)
        keys = self._feeds.get((security, rt_field))
        if not keys:
            return
        for key in keys:
            it = self._items.get(key)
            if it is None or it.state != "ok" or it.base is None:
                continue
            if it.policy == P_CHG:
                if type(it.base) is not float:
                    continue
                if it.anchor is None:
                    it.anchor = value                    # (no last price at the answer: from the first one seen)
                    continue
                self._put(key, it.base + (value - it.anchor))
            elif it.policy == P_RANGE:
                self._put(key, self._ranged(key, it.base, value))
            elif it.policy == P_BDH:
                self._put(key, self._today_point(key, it, value))

    def _trade(self, security: str, rt_field: str, value: float, first_tick: bool = False) -> None:
        """A trade as the service reads one (``Service._note_trades``): the last price changed or the day's volume grew -
        not the first value seen today -; or a tick of the stream (not its first picture) gave a security its first last
        price / volume (a bond that had none).  ``LAST_TRADE_DATE`` of the security is today from then on."""
        prev = self._trade_prev.get((security, rt_field))
        self._trade_prev[(security, rt_field)] = value
        if prev is None:
            if not first_tick:
                return
        elif value == prev or (rt_field == "VOLUME" and value < prev):
            return
        if self._traded.get(security) == self._day_no:
            return
        self._traded[security] = self._day_no
        text = tr_date_text(_dt.date.fromordinal(self._day_no))
        for key in self._feeds.get((security, "TRADE"), ()):
            self._put(key, text)

    @staticmethod
    def _ranged(key: Tuple, base: Any, value: Optional[float]) -> Any:
        """``INTERVAL_LOW`` / ``_HIGH`` with the day's low / high so far: the lower / higher of the two - Bloomberg's own
        answer as long as the day's is not beyond it by more than its precision (it gives some ranges in single
        precision: 100.0999984741211 for 100.1)."""
        if type(base) is not float or type(value) is not float:
            return base
        if key[2] == "INTERVAL_LOW":
            return value if value < base - 1e-6 * abs(base) else base
        return value if value > base + 1e-6 * abs(base) else base

    def _today_point(self, key: Tuple, it: _Item, value: Optional[float]) -> Any:
        """A BDH range ending today with its today's point from the stream - only when Bloomberg's answer has a point for
        today (the range keeps its shape: the blocks beside it stay aligned); Bloomberg's answer as it was otherwise."""
        pts = it.points
        if type(value) is not float or not pts or pts[-1][0] != self._day_serial:
            return it.base
        if pts[-1][1] != value:
            pts[-1] = (pts[-1][0], value)
        return self._history_value(pts, dict(key[5]))

    def _live(self, security: str, rt_field: str) -> bool:
        """Whether a real-time field of a security is kept current without asking it (lock held): a key of it whose
        subscription delivers (started, the field not refused - a trade comes as a tick even to a bond without a last
        price yet), or one polled that has a value."""
        if (security, rt_field) not in self._rt_keys:
            return False
        if self.stream:
            sub = self._subs.get(security)
            # (a subscription on its way counts: after a restart the preloaded keys wait for it, not ask meanwhile)
            if sub is not None and sub.state in ("new", "pending", "started") and rt_field not in sub.bad:
                return True
        return self._source(security, rt_field) is not None

    def _fed(self, key: Tuple, it: _Item) -> bool:
        """Whether a key that follows the stream has a source that delivers now (lock held): else it is asked hourly."""
        sec = key[1]
        if it.policy == P_LTD:
            return any(self._live(sec, f) for f in TRADE_FIELDS)
        if it.policy == P_CHG:
            return self._live(sec, "LAST_PRICE")
        if it.policy == P_RANGE:
            src = range_source(key, self._today_text())[0]
            return bool(src) and self._live(sec, src)
        if it.policy == P_BDH:
            src = RT_FIELDS.get(key[2])
            return bool(src) and self._live(sec, src) and bool(it.points) and it.points[-1][0] == self._day_serial
        return False

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
                self._work_once()
            except Exception as exc:  # noqa: BLE001 - the worker must survive anything
                self.last_error = "%s: %s" % (type(exc).__name__, str(exc)[:200])
                time.sleep(1.0)

    def _work_once(self) -> None:
        """One turn of the worker (a test drives it with a simulated clock)."""
        if self._session is None:
            self._reconnect()
            return
        self._roll_day()
        self._schedule_refreshes()
        self._resync_lost()
        self._send_queued()
        self._sync_subscriptions()
        self._expire_requests()

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
                    if k in self._items:
                        self._items[k].state = "queued"
                        self._queue.append(k)
            self._requests.clear()
            now = self._now()
            for sub in self._subs.values():
                sub.state = "new"
                sub.sent_fields = set()
                sub.names = ()
                sub.created = now
                sub.heard = False
            self.slow = False

    def _roll_day(self) -> None:
        today = self._today()
        with self._lock:
            if today != self.hits_day:
                self.hits_day = today
                self.hits = 0
                self.limit_reached = False
                self._resyncs_today = 0
                self.kinds = {}
                self.key_hits = {}
                self.usage_rev += 1
                self._trade_prev.clear()                 # a new day starts afresh: its first value is no trade
                self._traded.clear()
                # (Bloomberg's own limit stays until its probe answers: an hour after the day changed)
            self._day_no = today.toordinal()
            self._day_serial = float(date_to_serial(today))

    def revalidate(self) -> int:
        """Ask again about the securities Bloomberg did not know - and are still used - (done once on every new day by
        the schedule anyway, in the desk's hours: a maturity that did not exist yesterday may exist today).  Returns how
        many values were queued."""
        n = 0
        with self._lock:
            for key, it in self._items.items():
                if it.state == "ok" and it.used == self._day_no and self._values.get(key) == INVALID_SECURITY:
                    it.state = "queued"
                    it.why = DAILY
                    self._queue.append(key)
                    n += 1
        if n:
            self._wake.set()
        return n

    def _resync_lost(self) -> None:
        """After the queue has overflowed: what a subscription delivered meanwhile may be missing, so the values of the
        subscriptions concerned - the ones Bloomberg named (DataLoss), else those that ticked shortly before the queue
        filled up and not since it cleared - are asked once more by request (not while the queue is still filling up,
        not outside the desk's hours, not past 70 % of the day's budget)."""
        now = self._now()
        with self._lock:
            if not (self._resync or self._resync_all) or self.slow:
                return
            if now - self._slow_at < RESYNC_SETTLE or now - self._resync_at < RESYNC_EVERY:
                return
            everything, self._resync_all = self._resync_all, False
            secs, self._resync = self._resync, set()
            self._resync_at = now
            if self._resyncs_today >= RESYNC_BUDGET or self._tier() > 0 or not self._desk_open(now):
                return                               # enough for one day: the streams go on, the counts stay
            if everything:
                # (a quiet subscription lost nothing; one that ticked again since the queue cleared is up to date)
                secs |= {sec for sec, sub in self._subs.items()
                         if self._slow_since - RESYNC_ACTIVE <= sub.ticked < self._slow_at}
            n = 0
            for (sec, _field), keys in self._rt_keys.items():
                if sec not in secs:
                    continue
                for key in keys:
                    it = self._items.get(key)
                    if it is None or it.state != "ok" or it.used != self._day_no:
                        continue                     # (not used today: nobody looks at it)
                    if self._values.get(key) in FINAL_ANSWERS:
                        continue
                    it.state = "queued"
                    it.why = RESYNC
                    self._queue.append(key)
                    n += 1
            self.resyncs += n
            self._resyncs_today += n

    def _schedule_refreshes(self) -> None:
        """Queue what is due again (see the module text): only keys used today, only in the desk's hours, only while the
        day's budget is below ``BUDGET_WARN``."""
        now = self._now()
        with self._lock:
            open_ = self._desk_open(now)
            tier = self._tier()
            scan = now - self._scan_at >= SCAN_EVERY or now < self._scan_at
            if not scan and (tier > 0 or not open_):
                return
            if scan:
                self._scan_at = now
            today = self._day_no
            polled = {"value": 0, "empty": 0, "stopped": 0}
            fed = 0
            asking = tier == 0 and open_
            for key, it in self._items.items():
                if it.state != "ok" or it.used != today or it.policy == P_ONCE:
                    continue
                if it.rt:
                    why = self._poll_due(key, it, now, today, polled)
                elif it.policy in FED and it.day == today and self._fed(key, it):
                    fed += 1
                    continue
                else:
                    why = self._due(key, it, now, today)
                if why is not None and asking:
                    it.state = "queued"
                    it.why = why
                    self._queue.append(key)
            if scan:
                self._polled = polled
                self._fed_now = fed

    def _due(self, key: Tuple, it: _Item, now: float, today: int) -> Optional[str]:
        """Why a key that is not a quote is asked again now (its kind), or None (lock held)."""
        if it.day < today:                               # answered on another day: once today
            if self._values.get(key) in FINAL_ANSWERS:
                return DAILY
            if key[0] == "BDH":
                return HISTORY
            return STATIC if it.policy == P_STATIC else DAILY
        if self._values.get(key) in FINAL_ANSWERS:
            return None
        if it.policy == P_HOURLY or (it.policy in FED and not self._fed(key, it)):
            if now - it.fetched >= HOURLY_EVERY:
                return HISTORY if key[0] == "BDH" else HOURLY
        return None

    def _poll_due(self, key: Tuple, it: _Item, now: float, today: int, polled: Dict[str, int]) -> Optional[str]:
        """Whether a quote is asked by request now: only one its subscription does not bring (lock held).  Counts the
        polled ones (``polled``: with a value, without one, stopped streaming) for the status."""
        v = self._values.get(key)
        if type(v) is str and v in FINAL_ANSWERS:
            return DAILY if it.day < today else None     # unknown: once a day (a maturity may exist tomorrow)
        rtf = RT_FIELDS.get(key[2], key[2])
        if self.stream:
            sub = self._subs.get(key[1])
            dead = sub is None or sub.state == "failed" or rtf in sub.bad or \
                (sub.state == "started" and now - sub.since > SILENT_AFTER)
            if not dead:
                return None
            if it.streamed:
                if sub is None or sub.state != "failed":
                    return None                          # a quiet stream: a tick brings what changes
                polled["stopped"] += 1
                interval = POLL_STOPPED                  # it streamed, and its subscription failed since
            elif rtf in CLEARED_WHEN_NULL and sub is not None and sub.heard and sub.state == "started":
                # the size of an order while the stream of its security flows: no size in it means no order stands, and
                # a new one arrives as a tick (asked again, every bond of a closed market would cost a request an hour)
                return None
            elif type(v) is float:
                polled["value"] += 1
                interval = max(it.poll, self.price_poll)
            else:
                polled["empty"] += 1
                interval = POLL_EMPTY
        elif type(v) is float:
            polled["value"] += 1
            interval = max(it.poll, self.price_poll)
        else:
            polled["empty"] += 1
            interval = POLL_EMPTY
        if it.day < today or now - it.fetched >= interval:
            return POLL
        return None

    def _probe_due(self, now: float) -> bool:
        """Bloomberg's limit: one probe an hour after the day changed, then hourly while it still says so (lock held)."""
        if self.limit_day is None or self._day_no <= self.limit_day:
            return False
        start = time.mktime(_dt.date.fromordinal(self._day_no).timetuple())
        return now >= start + PROBE_AFTER and now >= self._probe_at

    def _send_queued(self) -> None:
        now = self._now()
        probe = None
        with self._lock:
            if not self._queue or len(self._requests) >= 12:
                if not (self.limit_day is not None and self._probe_due(now) and len(self._requests) < 12):
                    return
            tier = self._tier()
            keys: List[Tuple] = []
            held: List[Tuple] = []
            for k in self._queue:
                it = self._items.get(k)
                if it is None or it.state != "queued":
                    continue                             # (a key queued twice; one forgotten meanwhile)
                if tier == 2:
                    if it.why in (FIRST, USER) or it.policy == P_ONCE:
                        held.append(k)                   # a page waits for it: asked when the day's limit is over
                    else:
                        it.state = "ok"                  # due again later, when the schedule says so
                    continue
                if tier == 1 and it.why not in (FIRST, USER):
                    it.state = "ok"                      # past 70 % of the budget: only what a page has never had
                    continue
                keys.append(k)
            if tier == 2 and self.limit_day is not None and self._probe_due(now):
                probe = next((k for k in held if self._items[k].policy != P_ONCE), None)
                if probe is None:
                    probe = next((k for k, it in self._items.items()
                                  if it.state == "ok" and it.used == self._day_no and k[0] == "BDP"), None)
                if probe is not None:
                    if probe in held:
                        held.remove(probe)
                    keys = [probe]
                    self._probe_at = now + PROBE_AFTER
            self._queue = held
            for k in keys:
                self._items[k].state = "sent"
        if probe is not None:
            k = probe
            self._reference([k[1]], [k[2]], k[3], "BDP", {k[1]: [k]}, probe=True)
            return
        bdp: Dict[Tuple, Dict[str, Set[str]]] = {}
        bds: Dict[Tuple, List[Tuple]] = {}
        bdh: Dict[Tuple, List[Tuple]] = {}
        bars: List[Tuple] = []
        refs: Dict[Any, List[Tuple]] = {}
        index: Dict[Tuple, Tuple] = {}
        for k in keys:
            kind = k[0]
            if kind == "REF":
                refs.setdefault(k[3], []).append(k)      # (one call's keys: :meth:`reference`)
            elif kind == "BDP":
                bdp.setdefault(k[3], {}).setdefault(k[1], set()).add(k[2])
                index[(k[3], k[1], k[2])] = k
            elif kind == "BDS":
                bds.setdefault((k[2], k[3]), []).append(k)
            elif kind == "BDH":
                # Dates / Sort / Dir only shape the result: calls that differ in nothing else share a request
                asked = tuple(o for o in k[5] if o[0] not in ("DATES", "SORT", "DIR"))
                bdh.setdefault((k[2], k[3], k[4], asked), []).append(k)
            elif kind == "BAR":
                bars.append(k)
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
        for k in bars:
            self._bars(k)
        for ks in refs.values():
            by_sec: Dict[str, List[Tuple]] = {}
            for k in ks:
                by_sec.setdefault(k[1], []).append(k)
            secs = list(by_sec)
            fields = sorted({k[2] for k in ks})
            for i in range(0, len(secs), 100):
                chunk = secs[i:i + 100]
                self._reference(chunk, fields, (), "REF", {s: by_sec[s] for s in chunk})

    def _charge(self, keys: List[Tuple], probe: bool = False) -> None:
        """Count the hits of a request - one per key given (a security × field) -, each under what it was asked for."""
        with self._lock:
            for k in keys:
                it = self._items.get(k)
                kind = PROBE if probe else (it.why if it is not None and it.why else FIRST)
                self.kinds[kind] = self.kinds.get(kind, 0) + 1
                u = usage_key(k, it.policy if it is not None else None)
                self.key_hits[u] = self.key_hits.get(u, 0) + 1
            self.hits += len(keys)
            self.usage_rev += 1
            caps = [c for c in (self.max_hits_per_day, self.budget) if c]
            if caps and self.hits >= min(caps) and not self.limit_reached:
                self.limit_reached = True
                self.last_error = ("günlük veri bütçesi doldu (%d istek) – yeni istek gönderilmiyor, akan veriler güncelleniyor"
                                   % self.hits)

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
                    if k in self._items:
                        self._items[k].state = "queued"
                        self._queue.append(k)
            time.sleep(0.5)

    def _reference(self, securities: List[str], fields: List[str], overrides: Tuple, kind: str,
                   wanted: Dict[str, List[Tuple]], probe: bool = False) -> None:
        request = self._refdata.createRequest("ReferenceDataRequest")
        by_name: Dict[str, List[Tuple]] = {}             # the answer names a security as it was asked for
        for s in securities:
            name = api_security(s)
            if name not in by_name:
                request.append(self._name("securities"), name)
            by_name.setdefault(name, []).extend(wanted.get(s, []))
        for f in fields:
            request.append(self._name("fields"), f)
        if overrides:
            ov = request.getElement(self._name("overrides"))
            for name, value in overrides:
                item = ov.appendElement()
                item.setElement(self._name("fieldId"), name)
                item.setElement(self._name("value"), _override_value(name, value))
        # securities × fields hits, each counted on its key (two spellings of one security are asked once)
        charged = []
        for ks in by_name.values():
            for f in fields:
                k = next((x for x in ks if x[2] == f), None) if kind != "BDS" else (ks[0] if ks else None)
                if k is not None:
                    charged.append(k)
        self._charge(charged, probe)
        keys = [k for ks in by_name.values() for k in ks]
        req = _Request(kind, keys, by_name, self._now())
        req.probe = probe
        self._dispatch(request, req)

    def _history(self, keys: List[Tuple], field: str, start: str, end: str, options: Tuple) -> None:
        request = self._refdata.createRequest("HistoricalDataRequest")
        wanted: Dict[str, List[Tuple]] = {}
        for k in keys:
            wanted.setdefault(api_security(k[1]), []).append(k)
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
        self._charge([ks[0] for ks in wanted.values()])  # one hit a security, whatever the span
        self._dispatch(request, _Request("BDH", keys, wanted, self._now()))

    def _bars(self, key: Tuple) -> None:
        """The ``IntradayBarRequest`` of a bar call (:meth:`intraday_bars`): one security - the request takes no
        more -, one hit."""
        sec = api_security(key[1])
        try:
            request = self._refdata.createRequest("IntradayBarRequest")
            for name, value in (("security", sec), ("eventType", key[5]), ("interval", key[4]),
                                ("startDateTime", key[2]), ("endDateTime", key[3])):     # the times in UTC
                request.set(self._name(name), value)
        except Exception as exc:  # noqa: BLE001 - refused by the library: the call gets "nothing came"
            self.last_error = "gün içi bar isteği hazırlanamadı (%s): %s" % (key[1], str(exc)[:160])
            with self._lock:
                self._answer_bars(key, NA_NA)
            return
        self._charge([key])
        self._dispatch(request, _Request("BAR", [key], {sec: [key]}, self._now()))

    def _expire_requests(self) -> None:
        now = self._now()
        with self._lock:
            for cid in [c for c, r in self._requests.items() if now - r.sent > self.request_timeout]:
                req = self._requests.pop(cid)
                self.last_error = "istek zaman aşımına uğradı (%d öğe) – yeniden denenecek" % len(req.keys)
                for k in req.keys:
                    it = self._items.get(k)
                    if it is not None and it.state == "sent":
                        if k[0] == "REF":
                            self._set(k, NA_NA)          # a one-off request is not sent again: "nothing came"
                            continue
                        it.state = "queued"
                        self._queue.append(k)

    def _sync_subscriptions(self) -> None:
        if not self.stream or self._session is None:
            return
        bp = self._bp
        fresh, changed = [], []
        now = self._now()
        conflate = ["interval=%s" % (("%.3f" % self.interval).rstrip("0").rstrip("."),)] if self.interval > 0 else []
        with self._lock:
            for sec, sub in self._subs.items():
                if sub.state == "new":
                    known = self._known(sec, sub)
                    if known is False:
                        sub.state = "invalid"            # no such security: nothing to subscribe to
                        continue
                    if known is None and now - sub.created < SUBSCRIBE_WAIT:
                        continue                         # the reference answer is still on its way
                    fields = sorted(sub.fields)
                    fresh.append((sec, sub, fields, [] if sub.plain else conflate))
                    sub.state = "pending"
                    sub.sent_fields = set(fields)
                    sub.names = tuple((f, self._name(f)) for f in fields)
                    sub.since = now
                elif sub.state == "started" and sub.fields - sub.sent_fields:
                    fields = sorted(sub.fields)
                    changed.append((sec, sub, fields, [] if sub.plain else conflate))
                    sub.sent_fields = set(fields)
                    sub.names = tuple((f, self._name(f)) for f in fields)
        for group, action in ((fresh, "subscribe"), (changed, "resubscribe")):
            for i in range(0, len(group), 200):
                lst = bp.SubscriptionList()
                for sec, sub, fields, options in group[i:i + 200]:
                    lst.add(api_security(sec), fields, options, bp.CorrelationId(sub.cid))
                try:
                    getattr(self._session, action)(lst)
                except Exception as exc:  # noqa: BLE001
                    self.last_error = "abonelik hatası: %s" % (str(exc)[:160],)
                    with self._lock:
                        for sec, sub, _f, _o in group[i:i + 200]:
                            sub.state = "failed"

    def _known(self, sec: str, sub: _Sub) -> Optional[bool]:
        """Does the security of a subscription exist?  ``None`` while no reference answer has arrived
        (lock held by the caller)."""
        answered = False
        for field in sub.fields:
            for key in self._rt_keys.get((sec, field), ()):
                it = self._items.get(key)
                if it is None or it.state != "ok":
                    continue
                if self._values.get(key) == INVALID_SECURITY:
                    return False
                answered = True
        return True if answered else None

    # ================================================================== reader: events from Bloomberg
    def _read_loop(self) -> None:
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
            self._handle(event)

    def _handle(self, event) -> None:
        """One event of the session (the reader's turn; a test hands them over itself)."""
        bp = self._bp
        ev_types = bp.Event
        admin = getattr(ev_types, "ADMIN", None)
        try:
            et = event.eventType()
            if et == ev_types.TIMEOUT:
                return
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
            elif admin is not None and et == admin:
                for msg in event:
                    self._on_admin(msg)
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

    def _number(self, msg, name: str) -> int:
        try:
            root = msg.asElement()
            if root.hasElement(self._name(name), True):
                return int(root.getElementAsFloat(self._name(name)))
        except Exception:  # noqa: BLE001
            pass
        return 0

    def _on_admin(self, msg) -> None:
        """What the session says about its event queue."""
        kind = str(msg.messageType())
        now = self._now()
        if kind == "SlowConsumerWarning":
            with self._lock:
                self.slow = True
                self.slow_warnings += 1
                self._slow_at = self._slow_since = now
            self.last_error = "Bloomberg olay kuyruğu doluyor: veriler yeterince hızlı okunamıyor"
        elif kind == "SlowConsumerWarningCleared":
            dropped = self._number(msg, "eventsDropped")
            with self._lock:
                self.slow = False
                self._slow_at = now
                self.events_dropped += dropped
                if dropped:
                    self._resync_all = True          # a dropped event may have been anything
            if dropped:
                self.last_error = "Bloomberg olay kuyruğu taştı: %d olay düştü – etkilenen değerler yeniden isteniyor" % dropped
            elif self.last_error.startswith("Bloomberg olay kuyruğu doluyor"):
                self.last_error = ""                 # caught up without losing anything
            self._wake.set()
        elif kind == "DataLoss":
            lost = self._number(msg, "numMessagesDropped") or 1
            cids = self._cids(msg)
            with self._lock:
                self.messages_lost += lost
                for cid in cids:
                    sec = self._sub_by_cid.get(cid)
                    if sec is not None:
                        self._resync.add(sec)
                if not cids:
                    self._resync_all = True
            self._wake.set()

    # ------------------------------------------------------------------ Bloomberg's own daily limit
    def _said(self, info) -> Dict[str, str]:
        out = {}
        for name in ("category", "subcategory", "message", "description"):
            try:
                out[name] = str(info.getElementAsString(self._name(name))) if info.hasElement(self._name(name)) else ""
            except Exception:  # noqa: BLE001
                out[name] = ""
        return out

    def _limit_in(self, info) -> Optional[str]:
        """Bloomberg's daily limit in an error element (``responseError``, ``securityError``, a field's ``errorInfo``, a
        request failure's ``reason``): its words, or None.  What the desk's terminal said on 24.11.2026: ``category =
        "LIMIT" ... message = "Daily capacity reached." subcategory = "DAILY_CAPACITY_REACHED"``."""
        if info is None:
            return None
        said = self._said(info)
        cat, sub = said["category"].upper(), said["subcategory"].upper()
        text = (said["message"] or said["description"]).strip()
        if cat == "LIMIT" or "DAILY_CAPACITY" in sub or "LIMIT" in sub or "DAILY CAPACITY" in text.upper():
            return text or sub or cat
        return None

    def _hit_limit(self, req: Optional[_Request], words: str) -> None:
        """Bloomberg said its daily limit is reached: nothing more is asked today (one probe an hour after the day
        changed); what the request asked keeps its last value - a first answer waits in the queue (lock held)."""
        if req is not None:
            req.limited = True
        if self.limit_day is None:                       # (a probe that meets it again: the next one in an hour)
            self.limit_day = self._day_no
        self.limit_text = words or "Daily capacity reached."
        self.last_error = self._limit_words()
        if req is None:
            return
        for k in req.keys:
            it = self._items.get(k)
            if it is None or it.state != "sent":
                continue
            if it.policy == P_ONCE:
                it.state = "gone"                        # a one-off call: "nothing came"
            elif k in self._values:
                it.state = "ok"                          # asked again when it is due, after the limit
            else:
                it.state = "queued"                      # a first answer: when the limit is over
                self._queue.append(k)

    def _on_request_failure(self, msg) -> None:
        reason = None
        try:
            root = msg.asElement()
            if root.hasElement(self._name("reason")):
                reason = root.getElement(self._name("reason"))
        except Exception:  # noqa: BLE001
            reason = None
        words = self._limit_in(reason)
        with self._lock:
            for cid in self._cids(msg):
                req = self._requests.pop(cid, None)
                if req is None:
                    continue
                if words is not None:
                    self._hit_limit(req, words)
                    continue
                self.last_error = "istek reddedildi: %s" % (str(msg)[:200].replace("\n", " "),)
                for k in req.keys:
                    if k in self._items:                 # (a bar call that gave up has forgotten its key)
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
                    sub.since = self._now()
                    try:
                        root = msg.asElement()
                        if root.hasElement(self._name("exceptions")):
                            exc = root.getElement(self._name("exceptions"))
                            for i in range(exc.numValues()):
                                item = exc.getValueAsElement(i)
                                sub.bad.add(str(item.getElementAsString(self._name("fieldId"))))
                    except Exception:  # noqa: BLE001
                        pass
                elif kind == "SubscriptionFailure" and self.interval > 0 and not sub.plain and sub.state == "pending":
                    sub.plain = True                     # refused with the conflation option: once more without
                    sub.state = "new"
                    sub.created = 0.0
                    self._wake.set()
                elif kind in ("SubscriptionFailure", "SubscriptionTerminated"):
                    sub.state = "failed"

    def _on_tick(self, msg) -> None:
        """One market-data message.  Reading it takes as few calls into blpapi as possible (one per field
        that is not in the message - two for a size - and three per field that is), and none of them while
        holding the lock."""
        root = None
        now = self._now()
        for cid in self._cids(msg):
            sec = self._sub_by_cid.get(cid)
            sub = self._subs.get(sec) if sec is not None else None
            if sub is None:
                continue
            # a later message, not the stream's first picture: one came before, or it started long enough ago (a security
            # without any value may send no first picture at all)
            tick = sub.heard or (sub.state == "started" and now - sub.since > SILENT_AFTER)
            sub.heard = True
            sub.ticked = now
            if root is None:
                root = msg.asElement()
            got: List[Tuple[str, Any]] = []
            for field, name in sub.names:
                try:
                    if not root.hasElement(name, True):      # absent, or present without a value
                        if field in CLEARED_WHEN_NULL and root.hasElement(name):
                            got.append((field, NA_NA))       # in the message, emptied: the order is gone
                        continue
                    got.append((field, float(root.getElementAsFloat(name))))
                except Exception:  # noqa: BLE001 - not a number: nothing a price field can use
                    continue
            with self._lock:
                for field, v in got:
                    for key in self._rt_keys.get((sec, field), ()):
                        self._set(key, v, streamed=True, tick=tick)
                self.ticks += 1
                self.last_tick = now

    def _on_response(self, msg, final: bool) -> None:
        with self._lock:
            reqs = [(cid, self._requests.get(cid)) for cid in self._cids(msg)]
        for cid, req in reqs:
            if req is None:
                continue
            try:
                if req.kind == "BDH":
                    self._parse_history(msg, req)
                elif req.kind == "BAR":
                    self._parse_bars(msg, req, final)
                else:
                    self._parse_reference(msg, req)
            finally:
                if final:
                    with self._lock:
                        self._requests.pop(cid, None)
                        if not req.limited:
                            for k in req.keys:           # anything Bloomberg did not mention
                                it = self._items.get(k)      # (a history item may have been collected already)
                                if it is not None and it.state == "sent":
                                    self._set(k, NA_NA)
                        if req.probe and not req.limited and self.limit_day is not None:
                            self.limit_day = None        # the probe was answered: Bloomberg's limit is over
                            self.limit_text = ""
                            if self.last_error.startswith("Bloomberg günlük limiti"):
                                self.last_error = ""
                            self._wake.set()
                    if self.stream and req.kind == "BDP":
                        self._wake.set()                 # subscriptions that waited for this answer can go out

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
            err = root.getElement(n("responseError"))
            words = self._limit_in(err)
            with self._lock:
                if words is not None:
                    self._hit_limit(req, words)
                    return
                self.last_error = "Bloomberg yanıt hatası: %s" % (str(err)[:200].replace("\n", " "),)
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
                err = sd.getElement(n("securityError"))
                words = self._limit_in(err)
                with self._lock:
                    if words is not None:
                        self._hit_limit(req, words)
                        continue
                    text = self._error_text(err)
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
            limited = None
            if sd.hasElement(n("fieldExceptions")):
                fe = sd.getElement(n("fieldExceptions"))
                for j in range(fe.numValues()):
                    item = fe.getValueAsElement(j)
                    fid = str(item.getElementAsString(n("fieldId"))).upper()
                    info = item.getElement(n("errorInfo")) if item.hasElement(n("errorInfo")) else None
                    words = self._limit_in(info)
                    if words is not None:
                        limited = words
                        continue
                    bad[fid] = self._error_text(info) if info is not None else NA_NA
            with self._lock:
                if limited is not None:
                    self._hit_limit(req, limited)
                for k in keys:
                    it = self._items.get(k)
                    if limited is not None and it is not None and it.state != "sent":
                        continue                         # (kept by the limit: its last value stays)
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
            err = root.getElement(n("responseError"))
            words = self._limit_in(err)
            with self._lock:
                if words is not None:
                    self._hit_limit(req, words)
                    return
                for k in req.keys:
                    self._set(k, NA_NA)
            return
        if not root.hasElement(n("securityData")):
            return
        sd = root.getElement(n("securityData"))
        sec = str(sd.getElementAsString(n("security")))
        keys = req.wanted.get(sec, [])
        if sd.hasElement(n("securityError")):
            err = sd.getElement(n("securityError"))
            words = self._limit_in(err)
            with self._lock:
                if words is not None:
                    self._hit_limit(req, words)
                    return
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
                it = self._items.get(k)
                if it is not None and it.policy == P_BDH:
                    it.points = list(points)             # (its today's point follows the stream: _today_point)
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

    def _parse_bars(self, msg, req: _Request, final: bool) -> None:
        """One message of an ``IntradayBarResponse``.  A long span comes in several - ``PARTIAL_RESPONSE`` events
        before the final ``RESPONSE`` -: the bars are collected on the request and handed to the waiting call with
        the last one, oldest first."""
        key = req.keys[0]
        n = self._name
        try:
            root = msg.asElement()
            if root.hasElement(n("responseError")):
                self._bar_error(key[1], root.getElement(n("responseError")), req)
            elif req.parts is not None and root.hasElement(n("barData")):
                data = root.getElement(n("barData"))
                if data.hasElement(n("barTickData")):
                    ticks = data.getElement(n("barTickData"))
                    for i in range(ticks.numValues()):
                        bar = self._bar(ticks.getValueAsElement(i), key[2], key[3])
                        if bar is not None:
                            req.parts.append(bar)
        except Exception as exc:  # noqa: BLE001 - an answer that cannot be read whole is no answer
            req.parts = None
            self.last_error = "gün içi bar yanıtı okunamadı (%s): %s" % (key[1], str(exc)[:160])
        with self._lock:
            if final:
                self._answer_bars(key, NA_NA if req.parts is None else sorted(req.parts))
            else:
                req.sent = self._now()       # parts keep coming: alive (not expired, not asked again meanwhile)

    def _bar(self, el, t0: _dt.datetime, t1: _dt.datetime) -> Optional[Tuple[str, float, float, float, float, float]]:
        """One ``barTickData`` entry -> (its start in Istanbul time, open, high, low, close, volume); None for a bar
        outside the span asked for (start included, end not - whatever the terminal does at the edges) or one
        without its prices."""
        n = self._name
        try:
            t = el.getElement(n("time")).getValue()
            if t.tzinfo is not None:                     # (Bloomberg's bar times are UTC; one with an offset is made so)
                t = t.astimezone(_dt.timezone.utc).replace(tzinfo=None)
            if not t0 <= t < t1:
                return None
            o, h, lo, c = (float(el.getElement(n(f)).getValue()) for f in ("open", "high", "low", "close"))
            v = float(el.getElement(n("volume")).getValue()) if el.hasElement(n("volume"), True) else 0.0
        except Exception:  # noqa: BLE001 - not a bar that can be used
            return None
        return ((t + ISTANBUL).strftime("%Y-%m-%d %H:%M"), o, h, lo, c, v)

    def _bar_error(self, security: str, info, req: _Request) -> None:
        """The ``responseError`` of a bar request: how Bloomberg answers one for an unknown security (the request
        names one).  Said in the status; the call gets ``[]`` (nothing there) - but ``None`` (ask again later) when
        it says a limit or a time-out: "no bars" then would pass for days without any.  Bloomberg's daily limit stops
        every request (:meth:`_hit_limit`)."""
        said = self._said(info)
        self.last_error = "gün içi bar isteği reddedildi (%s): %s" % (
            security, said["message"] or said["subcategory"] or said["category"] or "Bloomberg hatası")
        kind = (said["category"] + " " + said["subcategory"]).upper()
        req.parts = None if ("LIMIT" in kind or "TIMEOUT" in kind) else []
        words = self._limit_in(info)
        if words is not None:
            with self._lock:
                self._hit_limit(None, words)
                req.limited = True

    def _answer_bars(self, key: Tuple, value: Any) -> None:
        """Hand a bar call its answer (lock held by the caller) - unless the call has given up and forgotten its key:
        a late answer is dropped.  No formula reads bars, so there is nothing for the engine to recalculate."""
        it = self._items.get(key)
        if it is not None and it.state == "sent":
            it.state = "ok"
            it.fetched = self._now()
            self._values[key] = value

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
        curve = self._lookup(source, P_HOURLY)
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
        policy, rt = policy_of(k, end)
        prov._lookup(k, policy, rt)
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
