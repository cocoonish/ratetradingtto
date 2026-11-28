"""A quote's age (the desk, 28.11.2026: proposal C4, "Kotanın yaşı" - the "BAYAT VERİ" badge catches only the whole feed;
tto/marketdata/age.py).

* The provider keeps in memory when each price's value last changed (``quote_times``): its answer, a tick that brings
  another value - not one that brings the same, not an order's size; the helper process's values as they reach the
  dashboard; nothing in replay.  Nothing is asked of Bloomberg for it.
* A market cell (a ``BDP`` of a price, by itself, in a chain, from a cell's text) gets the time of the quote whose value it
  shows - else the latest of its quotes (a mid of a bid and an ask) - as ``qa`` on the page; a size, a field with
  overrides, a cell computed from a market cell, a constant get none; replay none.
* Old: in market hours a price unchanged ``quote_old`` minutes (the desk's setting, 30; 0: never) of today's market -
  from today's opening when it changed before (overnight is not old at 09:01); none outside market hours.  The data
  status counts them and names the oldest (``ops.Ops.quotes``, ``/api/status`` → ``ops.quotes``, ``/api/quotes/age``).
* The page's side (``static/js/quoteage.js``, under Node): "son değişim 10:42 (37 dk)", the day when it is not today,
  the same rule for the fade.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
import types

import pytest
from starlette.testclient import TestClient

import fake_blpapi
from conftest import auth
from helpers import mini_engine
from tto import ops as opsmod
from tto.books import Book
from tto.config import Settings
from tto.marketdata.age import CellQuotes, is_old, is_price, market_minutes
from tto.marketdata.base import Provider, bdp_key
from tto.marketdata.bbg_process import IsolatedBloombergProvider
from tto.marketdata.bloomberg import NA_NA, P_QUOTE, BloombergProvider
from tto.marketdata.replay import ReplayProvider
from tto.render import Renderer
from tto.server import create_app
from tto.service import Service
from tto.xl import numfmt
from tto.xl.model import COLS, parse_a1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = dt.date(2026, 11, 27)                         # a Friday, a desk day
OPEN = dt.time(9, 0)


def ts(h, m, s=0, day=DAY):
    return dt.datetime.combine(day, dt.time(h, m, s)).timestamp()


# ---------------------------------------------------------------------------------------------- the rule
def test_minutes_of_todays_market():
    now = dt.datetime.combine(DAY, dt.time(10, 42))
    assert market_minutes(ts(10, 5), now, OPEN) == pytest.approx(37.0)
    assert market_minutes(ts(17, 55, day=DAY - dt.timedelta(days=1)), now, OPEN) == pytest.approx(102.0)   # (from 09:00)
    assert market_minutes(ts(10, 43), now, OPEN) == 0.0


def test_old_in_market_hours_only():
    at9 = dt.datetime.combine(DAY, dt.time(9, 1))
    overnight = ts(17, 30, day=DAY - dt.timedelta(days=1))
    assert not is_old(overnight, at9, 30, OPEN, True)                # (did not move overnight: not old at 09:01)
    assert is_old(overnight, dt.datetime.combine(DAY, dt.time(9, 30)), 30, OPEN, True)
    now = dt.datetime.combine(DAY, dt.time(10, 42))
    assert is_old(ts(10, 12), now, 30, OPEN, True) and not is_old(ts(10, 13), now, 30, OPEN, True)
    assert not is_old(ts(8, 0), now, 30, OPEN, False)                # (outside market hours: nothing is old)
    assert not is_old(ts(8, 0), now, 0, OPEN, True)                  # (the setting at 0: never)
    assert not is_old(None, now, 30, OPEN, True) and not is_old(0.0, now, 30, OPEN, True)


def test_what_a_price_quote_is():
    assert is_price(bdp_key("TYSO1 Curncy", "MID")) and is_price(bdp_key("USDTRY Curncy", "PX_LAST"))
    assert is_price(bdp_key("X Corp", "PX_BID")) and is_price(bdp_key("X Corp", "ASK"))
    assert not is_price(bdp_key("TYB1D BFX0 Curncy", "BID_SIZE")) and not is_price(bdp_key("X Corp", "VOLUME"))
    assert not is_price(bdp_key("X Corp", "HIGH")) and not is_price(bdp_key("X Corp", "DAYS_TO_MTY"))
    assert not is_price(bdp_key("X Corp", "PX_LAST", (("SETTLE_DT", "20261104"),)))     # (overrides: an ordinary field)
    assert not is_price(("BDH", "X Corp", "PX_LAST", "20261101", "20261103", ())) and not is_price("x")


# ---------------------------------------------------------------------------------------------- the provider
@pytest.fixture()
def terminal():
    srv = fake_blpapi.Server()
    srv.ref[("USDTRY Curncy", "BID", ())] = 49.997
    srv.ref[("USDTRY Curncy", "ASK", ())] = 49.998
    srv.ref[("TYB1D BFX0 Curncy", "BID_SIZE", ())] = 10.0
    srv.ref[("TYSO1 Curncy", "DAYS_TO_MTY", ())] = 365
    srv.rt[("USDTRY Curncy", "BID")] = 49.997
    return srv


def settle(p, timeout=10.0):
    t0 = time.time()
    while p.busy() and time.time() - t0 < timeout:
        time.sleep(0.02)
    time.sleep(0.2)


def test_the_provider_keeps_when_each_price_last_changed(terminal):
    now = [1_800_000_000.0]
    p = BloombergProvider(blpapi_module=fake_blpapi.module(terminal), clock=lambda: now[0])
    p.start()
    try:
        bid, ask = bdp_key("USDTRY Curncy", "BID"), bdp_key("USDTRY Curncy", "ASK")
        size, days = bdp_key("TYB1D BFX0 Curncy", "BID_SIZE"), bdp_key("TYSO1 Curncy", "DAYS_TO_MTY")
        assert p.quote_times() == {}                                     # (nothing asked yet)
        for k in (bid, ask, size, days):
            p.get_bdp(k)
        settle(p)
        assert p.quote_times() == {bid: (now[0], 49.997), ask: (now[0], 49.998)}     # (prices only; a size, a date: no)
        first = now[0]
        now[0] += 600
        terminal.tick("USDTRY Curncy", {"BID": 50.012})
        time.sleep(0.4)
        assert p.quote_times([bid, ask]) == {bid: (now[0], 50.012), ask: (first, 49.998)}
        now[0] += 600
        terminal.tick("USDTRY Curncy", {"BID": 50.012})                  # (the same value again: it did not change)
        time.sleep(0.4)
        assert p.quote_times([bid])[bid] == (first + 600, 50.012)
        assert p.quote_times([size, days, bdp_key("NONE Curncy", "BID")]) == {}
    finally:
        p.stop()


def test_the_helper_process_values_as_they_reach_the_dashboard(monkeypatch):
    """The isolated provider (its helper not started): what a batch from the helper changes is timed here."""
    from tto.marketdata import bbg_process
    clock = [1_800_000_000.0]
    monkeypatch.setattr(bbg_process, "time", types.SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic,
                                                                   sleep=time.sleep))
    p = IsolatedBloombergProvider()
    bid, size, eur = bdp_key("USDTRY Curncy", "BID"), bdp_key("TYB1D BFX0 Curncy", "BID_SIZE"), bdp_key("EURTRY Curncy", "ASK")
    p.preload([(eur, 51.2, 1_799_990_000.0)])                           # (kept from earlier today: its time)
    p._lookup(bid, P_QUOTE, "BID")
    p._lookup(size, P_QUOTE, "BID_SIZE")
    p._lookup(eur, P_QUOTE, "ASK")
    p._apply([(bid, 49.997), (size, 10.0)], 1, {})
    assert p.quote_times() == {bid: (clock[0], 49.997), eur: (1_799_990_000.0, 51.2)}
    clock[0] += 300
    p._apply([(bid, 49.997)], 2, {})                                     # (unchanged: the time stays)
    assert p.quote_times([bid]) == {bid: (clock[0] - 300, 49.997)}
    p._apply([(bid, 50.01)], 3, {})
    assert p.quote_times([bid, size]) == {bid: (clock[0], 50.01)}
    assert ReplayProvider().quote_times() == {}                                     # (replay: nothing moves)


# ---------------------------------------------------------------------------------------------- the market cells
class _Quotes(Provider):
    """Answers prices from a dict, with the time each last changed."""
    live = True

    def __init__(self, values, times):
        self.values, self.times = values, times

    def get_bdp(self, key):
        return self.values.get(key, NA_NA)

    def quote_times(self, keys=None):
        return {k: (self.times[k], self.values[k]) for k in (keys if keys is not None else self.times)
                if k in self.times and type(self.values.get(k)) is float}


CELLS = {
    "A1": '=BDP("TYSO1 Curncy","MID")',
    "A2": '=IFERROR(BDP("GFOF1 Curncy","MID"),BDP("BGN1 Curncy","PX_LAST"))',
    "A3": '=(BDP("USDTRY Curncy","BID")+BDP("USDTRY Curncy","ASK"))/2',
    "A4": '=BDP("TYB1D Curncy","BID_SIZE")',
    "A5": "=A1*2",
    "A6": 5,
    "A7": '=BDP(B7,"PX_LAST")', "B7": "SEC7 Curncy",
    "A8": '=BDP("GONE Curncy","MID")',
    "A9": '=BDP("TYSO1 Curncy","MID")/100',
}


def _book(values, times):
    model = mini_engine(CELLS).model
    prov = _Quotes(values, times)
    book = Book("mini", "Mini", model, provider=prov)
    r = Renderer(book)
    r.quotes = CellQuotes(book, prov)
    return book, r


def _qa(book, r, addr):
    rc = parse_a1(addr)
    return r.cell(book.engine.shared, 0, *divmod(rc, COLS), numfmt.get_locale("tr")).get("qa")


def test_a_market_cell_gets_the_time_of_the_quote_it_shows():
    k = {n: bdp_key(s, f) for n, (s, f) in {"ois": ("TYSO1 Curncy", "MID"), "gfof": ("GFOF1 Curncy", "MID"),
                                            "bgn": ("BGN1 Curncy", "PX_LAST"), "bid": ("USDTRY Curncy", "BID"),
                                            "ask": ("USDTRY Curncy", "ASK"), "size": ("TYB1D Curncy", "BID_SIZE"),
                                            "sec7": ("SEC7 Curncy", "PX_LAST")}.items()}
    values = {k["ois"]: 35.55, k["gfof"]: 36.0, k["bgn"]: 36.1, k["bid"]: 49.99, k["ask"]: 50.01, k["size"]: 10.0,
              k["sec7"]: 1.5}
    t = 1_800_000_000
    times = {k["ois"]: t, k["gfof"]: t - 2400, k["bgn"]: t - 10, k["bid"]: t - 50, k["ask"]: t - 900, k["size"]: t,
             k["sec7"]: t - 7}
    book, r = _book(values, times)
    assert _qa(book, r, "A1") == t
    assert _qa(book, r, "A2") == t - 2400                # (the chain shows GFOF's mid: its time, not the fallback's)
    assert _qa(book, r, "A3") == t - 50                  # (a mid of the two: the latest of them)
    assert _qa(book, r, "A7") == t - 7                   # (the security from a cell's text)
    assert _qa(book, r, "A9") == t                       # (worked out of one quote: its time)
    for addr in ("A4", "A5", "A6", "A8", "B7"):          # a size, a cell computed from a market cell, a constant, no answer
        assert _qa(book, r, addr) is None, addr
    # the time is read as the page is made: a later change shows at once
    times[k["ois"]] = t + 60
    assert _qa(book, r, "A1") == t + 60
    # replay (no ages kept), and a provider without a time: nothing
    r.quotes = None
    assert _qa(book, r, "A1") is None
    r.quotes = CellQuotes(book, _Quotes(values, {}))
    assert _qa(book, r, "A1") is None


# ---------------------------------------------------------------------------------------------- the data status
class _Store(object):
    def __init__(self, saved=None):
        self.saved = saved

    def get(self, key, default=None):
        return self.saved if key == "ops.settings" and self.saved is not None else default


class _Svc(object):
    def __init__(self, times, mode="live", saved=None):
        self.mode = mode
        self.provider = _Quotes({k: v for k, (_t, v) in times.items()}, {k: t for k, (t, _v) in times.items()})
        self.store = _Store(saved)


def test_the_data_status_counts_the_old_quotes():
    now = dt.datetime.combine(DAY, dt.time(10, 30))
    times = {bdp_key("FRESH Curncy", "MID"): (ts(10, 20), 1.0), bdp_key("STOPPED Curncy", "BID"): (ts(9, 50), 2.0),
             bdp_key("OVERNIGHT Curncy", "ASK"): (ts(17, 0, day=DAY - dt.timedelta(days=1)), 3.0),
             bdp_key("JUST Curncy", "PX_LAST"): (ts(9, 59, 30), 4.0)}
    q = opsmod.Ops(_Svc(times)).quotes(now, market=True)
    assert q["old"] == 3 and q["of"] == 4 and q["minutes"] == 30 and q["market"] is True and q["open"] == "09:00"
    assert [(o["ticker"], o["field"], o["at"], o["min"]) for o in q["oldest"]] == [
        ("OVERNIGHT Curncy", "ASK", "17:00", 90), ("STOPPED Curncy", "BID", "09:50", 40), ("JUST Curncy", "PX_LAST", "09:59", 30)]
    assert opsmod.Ops(_Svc(times)).quotes(now, market=False)["old"] == 0                 # (market closed)
    assert opsmod.Ops(_Svc(times, saved={"quote_old": 0})).quotes(now, market=True)["old"] == 0       # (the desk: never)
    assert opsmod.Ops(_Svc(times, saved={"quote_old": 45})).quotes(now, market=True)["old"] == 1     # (overnight only)
    assert opsmod.Ops(_Svc(times, mode="replay")).quotes(now, market=True) == {
        "old": 0, "of": 0, "minutes": 30, "market": True, "open": "09:00", "close": "18:00", "oldest": []}


def test_the_desk_setting():
    o = opsmod.Ops(_Svc({}))
    assert o.settings()["quote_old"] == 30
    assert o.check_settings({"quote_old": "0"})["quote_old"] == 0 and o.check_settings({"quote_old": "90"})["quote_old"] == 90
    with pytest.raises(ValueError):
        o.check_settings({"quote_old": "601"})
    with pytest.raises(ValueError):
        o.check_settings({"quote_old": "yarım saat"})
    assert opsmod.changes({"quote_old": 30}, {"quote_old": 45}) == "kota eskime süresi (dk): 30 → 45"


# ---------------------------------------------------------------------------------------------- a live dashboard
class _Live(ReplayProvider):
    """A live provider answering every price at once (any other field: none), each with a time of its own."""
    live = True
    T0 = 1_800_000_000.0

    def __init__(self):
        super(_Live, self).__init__({})
        self.times = {}

    def _get(self, key):
        if not is_price(key):
            return NA_NA
        if key not in self.snapshot:
            self.snapshot[key] = 30.0 + (sum(map(ord, key[1] + key[2])) % 997) / 100.0
            self.times[key] = self.T0 + len(self.times)
        return self.snapshot[key]

    get_bdp = get_bdh = get_bds = get_bfx = get_rt = _get

    def quote_times(self, keys=None):
        return {k: (self.times[k], self.snapshot[k]) for k in (keys if keys is not None else list(self.times))
                if k in self.times}


def test_a_live_dashboard(tmp_path):
    prov = _Live()
    svc = Service(Settings(data_dir=str(tmp_path / "data"), mode="live", history=False), provider=prov)
    try:
        assert svc.mode == "live" and isinstance(svc.renderers["tto"].quotes, CellQuotes)
        book, rn = svc.books["tto"], svc.renderers["tto"]
        loc = numfmt.get_locale("tr")

        def market_cells():
            out = []
            calc = book.engine.shared
            for si, rc in sorted(rn.quotes.cells()):
                sh = book.model.sheets[si]
                if rc not in sh.fml:
                    continue
                r, c = divmod(rc, COLS)
                cell = rn.cell(calc, si, r, c, loc)
                if cell.get("qa"):
                    # the times its quotes had as the cell was made (a quote first asked later has a later time)
                    keys = rn.quotes.keys(calc, si, r, c)
                    out.append((sh.name, rc, cell, {k: prov.times[k] for k in keys if k in prov.times}))
            return out

        found = svc.et.call(market_cells)
        assert found, "no market cell"
        direct = 0
        for name, rc, cell, times in found:
            shown = [k for k in times if prov.snapshot[k] == cell["v"]]
            # the time of the quote the cell shows - else (a value worked out of its quotes) the latest of them
            assert times and cell["qa"] == int(max(times[k] for k in (shown or times))), (name, divmod(rc, COLS), cell, times)
            direct += bool(shown)
        assert direct, "no market cell shows a quote as it is"       # (OIS_MAIN's spot reads the strip since 28.11.2026)
        # the page as the browser gets it carries them too
        auth(svc, "Kota Yaşı")
        assert re.search(r'"qa": \d{10}', json.dumps(svc.view("Kota Yaşı", "ois")))
        # the data status: the prices old by the rule an hour after the last of them changed
        now = dt.datetime.fromtimestamp(max(prov.times.values()) + 3600)
        q = svc.ops.quotes(now, market=True)
        assert q["of"] == len(prov.times) > 0 and q["minutes"] == 30
        assert q["old"] == sum(1 for t in prov.times.values() if is_old(t, now, 30, OPEN, True))
        st = svc.status()["ops"]["quotes"]
        assert 0 < st["of"] <= len(prov.times) and set(st) >= {"old", "of", "minutes", "market", "oldest"}
        with TestClient(create_app(svc)) as client:        # (the pages warming up may ask for more prices meanwhile)
            got = client.get("/api/quotes/age", headers=auth(svc, "Kota Yaşı")).json()
            assert 0 < got["of"] <= len(prov.times) and got["minutes"] == 30 and "market" in got
    finally:
        svc.stop()


def test_replay_shows_no_age(service):
    assert service.mode == "replay" and all(r.quotes is None for r in service.renderers.values())
    assert service.ops.quotes(market=True)["of"] == 0


# ---------------------------------------------------------------------------------------------- the page's side
HARNESS = r"""
import { quoteTip, isOld, spanText, whenText } from './quoteage.mjs';
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const c = JSON.parse(raw);
  process.stdout.write(JSON.stringify({
    tips: c.tips.map(([at, now]) => quoteTip({ qa: at }, now)),
    none: [quoteTip(null), quoteTip({ t: '1' })],
    spans: c.spans.map(spanText),
    old: c.old.map(([at, rule, now]) => isOld(at, rule, now)),
    when: c.when.map(([at, now]) => whenText(at, now)),
  }));
});
"""


def test_the_page_says_the_age_and_fades_by_the_same_rule(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to read quoteage.js")
    with open(os.path.join(ROOT, "tto", "static", "js", "quoteage.js"), encoding="utf-8") as fh:
        src = fh.read().replace("import { api } from './api.js';", "const api = { get: async () => ({}) };")
    (tmp_path / "quoteage.mjs").write_text(src, encoding="utf-8")
    (tmp_path / "run.mjs").write_text(HARNESS, encoding="utf-8")
    rule = {"minutes": 30, "market": True, "open": "09:00"}
    now = ts(10, 42)
    cases = {"tips": [[ts(10, 5), now], [ts(10, 42), now], [ts(17, 58, day=DAY - dt.timedelta(days=1)), now]],
             "spans": [0, 37, 59.9, 60, 125, 1440, 4000],
             "old": [[ts(10, 12), rule, now], [ts(10, 13), rule, now], [ts(17, 0, day=DAY - dt.timedelta(days=1)), rule, ts(9, 1)],
                     [ts(8, 0), dict(rule, market=False), now], [ts(8, 0), dict(rule, minutes=0), now], [ts(8, 0), None, now]],
             "when": [[ts(10, 5), now], [ts(17, 58, day=DAY - dt.timedelta(days=1)), now]]}
    res = subprocess.run([node, str(tmp_path / "run.mjs")], input=json.dumps(cases), capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    assert got["tips"] == ["son değişim 10:05 (37 dk)", "son değişim 10:42 (0 dk)", "son değişim 26.11 17:58 (16 sa 44 dk)"]
    assert got["none"] == ["", ""]
    assert got["spans"] == ["0 dk", "37 dk", "59 dk", "1 sa", "2 sa 5 dk", "1 gün", "2 gün"]
    assert got["old"] == [True, False, False, False, False, False]
    assert got["when"] == ["10:05", "26.11 17:58"]
    # the server's rule agrees, case by case
    for (at, r, n), want in zip(cases["old"], got["old"]):
        nd = dt.datetime.fromtimestamp(n)
        assert is_old(at, nd, (r or {}).get("minutes", 0), OPEN, bool(r and r.get("market"))) == want
