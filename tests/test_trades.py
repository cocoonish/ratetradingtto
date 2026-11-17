"""Trades (tto/tradebook.py): the desk's and each trader's own trades with their MTM and P&L, apart from the desk's position.

Most tests use the book on a database of its own (``_book``): no workbook is loaded, the clock is the test's and the
valuation is a fake that returns planted numbers (tto/tradevalue.py is a stub until the trades-deger branch replaces it).
Then the same over HTTP on the replay service: who reaches what through every route, the form's defaults and DV01, and an
MPC trade kept by its meeting's date while the calendar moves."""
import datetime as dt
import sqlite3
import threading
import time

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto import bonds as bd
from tto import tradebook as tbm
from tto import tradevalue as tv
from tto.server import create_app
from tto.service import Service, ServiceError
from tto.store import Store


class _Svc(object):
    """What the book needs of the service: its store, who is signed in, a way to tell the pages."""
    require_user = Service.require_user
    require_admin = Service.require_admin

    def __init__(self, store):
        self.store = store
        self.told = 0
        self.started_at = time.time() - 86400

    def nudge(self):
        self.told += 1

    def saw(self, user):
        pass

    def holiday_dates(self, ccys):
        return frozenset()


class _Ops(object):
    """The desk's settings and business days, as the test sets them."""

    def __init__(self, close="17:30", holidays=()):
        self.close = close
        self.holidays = set(holidays)

    def settings(self):
        return {"trades_close": self.close}

    def market_day(self, day):
        return dt.date.fromisoformat(day).weekday() < 5 and day not in self.holidays


class _Clock(object):
    def __init__(self, text="2026-11-17 10:00"):
        self.set(text)

    def set(self, text):
        self.at = dt.datetime.strptime(text, "%Y-%m-%d %H:%M")

    def __call__(self):
        return self.at


def _book(path=":memory:"):
    store = Store(str(path))
    book = tbm.TradeBook(_Svc(store))
    clock = _Clock()
    book.now = clock
    return book, store, clock


def _user(store, name, admin=False):
    key = store.login(name)["user"]
    if admin:
        store.update_account(key, role="admin")
    return key


def _refused(status, fn, *args, **kw):
    with pytest.raises(ServiceError) as exc:
        fn(*args, **kw)
    assert exc.value.status == status, (exc.value.status, str(exc.value))
    return exc.value


TODAY = "2026-11-17"


def _ois(**kw):
    d = {"scope": "desk", "product": "ois", "structure": "outright", "trade_date": TODAY, "settle_date": "2026-11-18",
         "side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,50"}
    d.update(kw)
    return d


def _fxspot(**kw):
    d = {"scope": "desk", "product": "fxspot", "pair": "USDTRY", "trade_date": TODAY, "settle_date": "2026-11-18",
         "side": "B", "notional": "10m", "price": "42,15"}
    d.update(kw)
    return d


def _fxopt(**kw):
    d = {"scope": "desk", "product": "fxopt", "pair": "USDTRY", "trade_date": TODAY, "settle_date": "2026-11-18",
         "call_put": "call", "side": "B", "strike": "45", "expiry": "1A", "delivery": "2026-12-21", "notional": "10m",
         "price": "150k", "premium_ccy": "TRY"}
    d.update(kw)
    return d


def _listed_isin():
    return bd.listed(dt.date(2026, 11, 17))[0]["isin"]


class _Planted(object):
    """tradevalue.value as the test plants it: (trade id, asof) -> its numbers."""

    def __init__(self):
        self.values = {}
        self.calls = []

    def set(self, tid, asof, mtm, carry, ccy="TRY", accrued=None, legs=None, fx=40.0):
        self.values[(tid, asof)] = _val(mtm, carry, ccy, accrued, legs, fx)

    def __call__(self, trade, mkt, asof=None):
        self.calls.append((trade.get("id"), asof, dict(trade)))
        hit = self.values.get((trade.get("id"), asof))
        return dict(hit) if hit else {"ok": False, "why": "planlanmadı"}


def _val(mtm, carry, ccy="TRY", accrued=None, legs=None, fx=40.0):
    """A valuation in TL (or USD) at USDTRY ``fx``."""
    to_try, to_usd = (1.0, 1.0 / fx) if ccy == "TRY" else (fx, 1.0)
    v = {"ok": True, "why": None, "ccy": ccy, "mtm": mtm, "mtm_try": mtm * to_try, "mtm_usd": mtm * to_usd,
         "carry_1d": carry, "carry_1d_try": carry * to_try, "carry_1d_usd": carry * to_usd, "accrued": accrued,
         "price_now": 38.0, "price_text": "%38,00", "greeks": None, "inputs": {}}
    if legs is not None:
        v["legs"] = [{"label": label, "mtm": m, "mtm_try": m * to_try, "mtm_usd": m * to_usd, "carry_1d": c,
                      "carry_1d_try": c * to_try, "carry_1d_usd": c * to_usd, "price_now": None, "price_text": ""}
                     for label, m, c in legs]
    return v


@pytest.fixture()
def planted(monkeypatch):
    p = _Planted()
    monkeypatch.setattr(tv, "value", p)
    monkeypatch.setattr(tv, "market", lambda svc: "piyasa")
    return p


def _near(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# ---------------------------------------------------------------------- entering trades
def test_each_product_and_structure_is_entered_kept_and_said_in_the_desk_s_words():
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    ids = {}
    ids["ois"] = book.add(ali, _ois())["id"]
    ids["sofr"] = book.add(ali, _ois(product="sofr", side="pay", end_date="5Y", notional="25m", price="3,85"))["id"]
    ids["mpc"] = book.add(ali, _ois(structure="mpc", meeting="2026-12-11", end_date="", notional="50m", price="37,25"))["id"]
    ids["fra"] = book.add(ali, _ois(structure="fra", fra="3x6", side="pay", end_date="", price="%37,10"))["id"]
    ids["spread"] = book.add(ali, _ois(structure="spread", side="steepener", end_date="", notional="", price="", legs=[
        {"side": "pay", "end_date": "5Y", "notional": "45m", "price": "38,15"},
        {"side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,50"}]))["id"]
    ids["fly"] = book.add(ali, _ois(structure="fly", end_date="", notional="", price="", legs=[
        {"side": "pay", "end_date": "2Y", "notional": "50m", "price": "38,50"},
        {"side": "receive", "end_date": "5Y", "notional": "45m", "price": "38,15"},
        {"side": "pay", "end_date": "10Y", "notional": "15m", "price": "37,90"}]))["id"]
    isin = _listed_isin()
    ids["dibs"] = book.add(ali, {"scope": "desk", "product": "dibs", "isin": " " + isin.lower() + " ", "trade_date": TODAY,
                                 "settle_date": "+1", "side": "B", "notional": "50m", "price": "98,75"})["id"]
    ids["dibs_y"] = book.add(ali, {"scope": "desk", "product": "dibs", "isin": isin, "trade_date": TODAY, "settle_date": "2026-11-18",
                                   "side": "S", "notional": "20m", "price_kind": "yield", "price": "38,10"})["id"]
    ids["fxspot"] = book.add(ali, _fxspot())["id"]
    ids["fxspot_q"] = book.add(ali, _fxspot(side="S", notional="", quote_amount="421,5m", amount_typed="quote"))["id"]
    ids["fxopt"] = book.add(ali, _fxopt())["id"]
    rows = {r["id"]: r for r in store.tb_list("desk")}
    by = {k: rows[v] for k, v in ids.items()}
    o = by["ois"]
    assert (o["trade_date"], o["settle_date"], o["value_date"], o["end_date"], o["tenor"]) == (
        TODAY, "2026-11-18", "2026-11-18", "2028-11-20", "2Y")
    assert (o["notional"], o["notional_ccy"], o["price"], o["side"], o["sized_by"], o["status"]) == (
        1e8, "TRY", 38.5, "receive", "notional", "open")
    assert by["sofr"]["notional_ccy"] == "USD" and by["sofr"]["end_date"] == "2031-11-18"
    assert by["mpc"]["meeting"] == "2026-12-11" and "end_date" not in by["mpc"]
    # a FRA as the desk says it: 3x6 from the settle date (the trade's spot), the rate typed with its "%"
    assert (by["fra"]["value_date"], by["fra"]["end_date"], by["fra"]["fra"], by["fra"]["price"]) == ("2027-02-18", "2027-05-18", "3x6", 37.1)
    # a spread's legs short → long whatever order they were typed in; its level in bp from their rates
    sp = by["spread"]
    assert [lg["tenor"] for lg in sp["legs"]] == ["2Y", "5Y"] and [lg["notional"] for lg in sp["legs"]] == [1e8, 4.5e7]
    assert _near(sp["price"], -35.0) and sp["side"] == "steepener" and sp["notional_ccy"] == "TRY"
    assert _near(by["fly"]["price"], -10.0) and len(by["fly"]["legs"]) == 3
    assert (by["dibs"]["isin"], by["dibs"]["settle_date"], by["dibs"]["value_date"], by["dibs"]["price"]) == (isin, "2026-11-18", "2026-11-18", 98.75)
    assert (by["dibs_y"]["price_kind"], by["dibs_y"]["yield"], by["dibs_y"].get("price")) == ("yield", 38.1, None)
    # the amount in either currency of the pair: the other one follows from the rate
    q = by["fxspot_q"]
    assert (q["amount_typed"], q["quote_amount"], q["notional_ccy"]) == ("quote", 421.5e6, "USD") and _near(q["notional"], 1e7, 1e-6)
    op = by["fxopt"]
    assert (op["expiry"], op["delivery"], op["notional"], op["notional_ccy"], op["price"], op["premium_ccy"]) == (
        "2026-12-17", "2026-12-21", 1e7, "USD", 150000.0, "TRY")
    assert op["premium_date"] == op["settle_date"] == op["value_date"] == "2026-11-18"
    # the list says each trade in the desk's words
    texts = {it["id"]: it["text"] for it in book.listing(ali, "desk")["open"]}
    assert texts[ids["ois"]] == "RECEIVE 2Y TRY OIS 100m @ %38,50"
    assert texts[ids["sofr"]] == "PAY 5Y SOFR 25m @ %3,85"
    assert texts[ids["mpc"]] == "RECEIVE PPK 11.12.2026 TRY OIS 50m @ %37,25"
    assert texts[ids["fra"]] == "PAY 3x6 FRA TRY OIS 100m @ %37,10"
    assert texts[ids["spread"]] == "2s5s steepener TRY OIS -35,0 bp"
    assert texts[ids["fly"]] == "2s5s10s REC gövde TRY OIS -10,0 bp"
    assert texts[ids["dibs"]] == "ALIŞ %s (%s) 50m @ 98,750" % (bd.short_label(bd.by_isin(isin)), isin)
    assert texts[ids["dibs_y"]].endswith("20m @ %38,10 getiri")
    assert texts[ids["fxspot"]] == "ALIŞ USDTRY 10m USD @ 42,1500"
    assert texts[ids["fxopt"]] == "ALIŞ USDTRY 45 CALL 10m USD · vade 17.12.2026 · prim 150.000,00 TRY"
    listed = {it["id"]: it for it in book.listing(ali, "desk")["open"]}
    assert [lg["text"] for lg in listed[ids["spread"]]["legs"]] == ["RECEIVE 2Y 100m @ %38,50", "PAY 5Y 45m @ %38,15"]
    # changed, closed, deleted: what is kept follows
    assert book.edit(ali, ids["ois"], _ois(notional="200m"))["changed"]
    assert store.tb_get(ids["ois"])["notional"] == 2e8
    assert not book.edit(ali, ids["ois"], _ois(notional="200m"))["changed"]            # nothing to change: nothing logged
    book.close(ali, ids["fxspot"], TODAY, "42,40")
    assert (store.tb_get(ids["fxspot"])["status"], store.tb_get(ids["fxspot"])["close_price"]) == ("closed", 42.4)
    assert book.remove(ali, ids["sofr"]) == {"deleted": ids["sofr"]} and store.tb_get(ids["sofr"]) is None
    lists = book.listing(ali, "desk")
    assert ids["fxspot"] in [it["id"] for it in lists["closed"]] and ids["sofr"] not in [it["id"] for it in lists["open"]]
    assert lists["closed"][0]["close_price_text"] == "42,4000"
    # a closed trade is changed only after its close is taken back
    _refused(400, book.edit, ali, ids["fxspot"], _fxspot())
    book.reopen(ali, ids["fxspot"])
    assert store.tb_get(ids["fxspot"])["status"] == "open" and "close_date" not in store.tb_get(ids["fxspot"])
    store.close()


def test_what_a_trade_needs_and_what_it_refuses():
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")

    def fields(raw):
        err = _refused(400, book.add, ali, raw)
        return set(err.data["fields"])

    # the trade date and the trade price always
    assert "trade_date" in fields(_ois(trade_date=""))
    assert "price" in fields(_ois(price=""))
    assert "price" in fields(_fxspot(price=None))
    assert "price" in fields(_fxopt(price=""))
    assert "price" in fields({"scope": "desk", "product": "dibs", "isin": _listed_isin(), "trade_date": TODAY,
                              "settle_date": "2026-11-18", "side": "B", "notional": "5m"})
    assert fields(_ois(trade_date="2026-11-18")) == {"trade_date"}            # not a day ahead of today
    assert fields(_ois(settle_date="", value_date="", end_date="2028-11-20")) == {"settle_date"}
    assert fields(_ois(settle_date="", value_date="")) == {"settle_date", "end_date"}       # ("2Y" from what?)
    assert fields(_fxspot(settle_date="2026-11-16")) == {"settle_date"}       # before the trade date
    assert fields(_ois(side="")) == {"side"} and fields(_ois(side="al")) == {"side"}
    assert fields(_ois(end_date="2026-11-18")) == {"end_date"}               # not after its start
    assert fields(_ois(notional="", dv01="")) == {"notional"}
    assert fields(_ois(notional="çok")) == {"notional"}
    assert fields(_ois(structure="spread", legs=[{"side": "pay", "end_date": "2Y", "notional": "5m", "price": "38"}])) >= {"legs"}
    assert fields(_ois(structure="spread", legs=[{"side": "pay", "end_date": "2Y", "notional": "5m"},
                                                 {"side": "receive", "end_date": "5Y", "notional": "5m", "price": "38"}])) == {"legs.0.price"}
    assert fields(_ois(structure="fra", fra="6x3", end_date="")) == {"fra"}
    assert fields(_ois(structure="mpc", meeting="", end_date="")) == {"meeting"}
    assert fields(_fxopt(delivery="2026-12-16")) == {"delivery"}
    assert fields(_fxopt(pair="")) >= {"pair"} and fields(_fxspot(pair="dolar")) >= {"pair"}
    assert fields({"scope": "desk", "product": "dibs", "isin": "TRT000000000", "trade_date": TODAY, "settle_date": "2026-11-18",
                   "side": "B", "notional": "5m", "price": "99"}) == {"isin"}
    # a sound ISIN that is not on the desk's list of bonds
    assert fields({"scope": "desk", "product": "dibs", "isin": "US0378331005", "trade_date": TODAY, "settle_date": "2026-11-18",
                   "side": "B", "notional": "5m", "price": "99"}) == {"isin"}
    assert fields(_ois(product="swap")) == {"product"}
    assert fields(_ois(note="x" * 301)) == {"note"}
    _refused(400, book.add, ali, _ois(scope="herkes"))
    assert store.tb_list("desk") == [] and store.tb_log(scope="desk") == []
    # the form's preview reads it the same way and saves nothing
    pre = book.check(ali, _ois(end_date="5Y"))
    assert pre["ok"] and pre["text"] == "RECEIVE 5Y TRY OIS 100m @ %38,50" and pre["echo"]["end_date"] == "5Y → 18.11.2031"
    bad = book.check(ali, _ois(price=""))
    assert not bad["ok"] and set(bad["fields"]) == {"price"} and store.tb_list("desk") == []
    store.close()


def test_a_dv01_gives_a_rounded_nominal_and_a_typed_nominal_stays():
    """DV01 in USD (or TL) per bp: the nominal from tradevalue.notional_for_dv01 (the stub: DV01 × 10.000), to the nearest
    5 mn, never below 5 mn, and the DV01 it actually gives; a nominal typed wins and its DV01 is information only."""
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    size = lambda raw, *asks: book.size(ali, dict(raw, size=list(asks)))["units"]    # noqa: E731
    u = size(_ois(), {"leg": None, "dv01": "1.012", "dv01_ccy": "USD"})[0]
    assert (u["notional"], u["dv01"], u["sized_by"], u["dv01_ccy"]) == (1e7, 1000.0, "dv01", "USD")
    assert size(_ois(), {"leg": None, "dv01": "10"})[0]["notional"] == 5e6                    # never below 5 mn
    assert size(_ois(), {"leg": None, "dv01": "26k", "dv01_ccy": "TL"})[0]["notional"] == 2.6e8
    u = size(_ois(), {"leg": None, "notional": "52m"})[0]
    assert (u["notional"], u["dv01"], u["sized_by"]) == (5.2e7, 5200.0, "notional")
    legs = [{"side": "receive", "end_date": "2Y", "price": "38,5"}, {"side": "pay", "end_date": "5Y", "price": "38,15"}]
    got = size(_ois(structure="spread", legs=legs), {"leg": 0, "dv01": "2500"}, {"leg": 1, "dv01": "1250"})
    assert [g["notional"] for g in got] == [2.5e7, 1.5e7] and [g["leg"] for g in got] == [0, 1]
    fx = size(_fxspot(), {"leg": None, "dv01": "1000"})[0]
    assert fx["notional"] is None and fx["why"]
    # saved by DV01: the DV01 typed, the nominal worked out (when the form did not), which one was typed
    t1 = book.add(ali, _ois(notional="", dv01="1012", sized_by="dv01"))["id"]
    r = store.tb_get(t1)
    assert (r["sized_by"], r["dv01"], r["dv01_ccy"], r["notional"]) == ("dv01", 1012.0, "USD", 1e7)
    # a nominal typed after the DV01: it stays, nothing works it out again
    t2 = book.add(ali, _ois(notional="12m", dv01="1012", sized_by="notional"))["id"]
    r = store.tb_get(t2)
    assert (r["sized_by"], r["notional"]) == ("notional", 1.2e7) and "dv01" not in r
    # the form's nominal from a DV01 is kept as it was shown
    t3 = book.add(ali, _ois(notional="15m", dv01="1500", sized_by="dv01", dv01_ccy="TRY"))["id"]
    assert (store.tb_get(t3)["notional"], store.tb_get(t3)["dv01_ccy"]) == (1.5e7, "TRY")
    t4 = book.add(ali, {"scope": "desk", "product": "dibs", "isin": _listed_isin(), "trade_date": TODAY, "settle_date": "2026-11-18",
                        "side": "B", "dv01": "3.000", "sized_by": "dv01", "price": "99"})["id"]
    assert store.tb_get(t4)["notional"] == 3e7
    store.close()


# ---------------------------------------------------------------------- who sees and changes what
def test_a_personal_trade_is_its_owner_s_only_and_a_desk_trade_changes_by_its_creator_or_an_administrator():
    book, store, clock = _book()
    ali, veli, admin = _user(store, "Ali Veli"), _user(store, "Veli Can"), _user(store, "Yönetici", admin=True)
    mine = book.add(ali, _fxspot(scope="personal"))["id"]
    desk = book.add(ali, _ois())["id"]
    assert [it["id"] for it in book.listing(ali, "personal")["open"]] == [mine]
    for who in (veli, admin):
        assert book.listing(who, "personal")["open"] == []
        assert [it["id"] for it in book.listing(who, "desk")["open"]] == [desk]
        for fn, args in ((book.edit, (mine, _fxspot())), (book.close, (mine, TODAY, "42")), (book.reopen, (mine,)),
                         (book.remove, (mine,)), (book.log, (mine,))):
            _refused(404, fn, who, *args)            # the same answer as a trade that does not exist
        _refused(404, book.log, who, 99999)
        assert all(e["trade"] != mine for e in book.recent(who, "personal")["entries"])
        assert str(mine) not in book.mtm(who, "personal")["values"]
    assert str(mine) in book.mtm(ali, "personal")["values"]
    # the desk's trade: everybody sees it; its creator or an administrator changes it
    assert [it["can_edit"] for it in book.listing(veli, "desk")["open"]] == [False]
    assert [it["can_edit"] for it in book.listing(admin, "desk")["open"]] == [True]
    _refused(403, book.edit, veli, desk, _ois(notional="1m"))
    _refused(403, book.close, veli, desk, TODAY, "38")
    _refused(403, book.remove, veli, desk)
    assert book.edit(admin, desk, _ois(notional="300m"))["changed"]
    assert book.edit(ali, desk, _ois(notional="400m"))["changed"]
    _refused(400, book.edit, ali, desk, _ois(scope="personal"))          # its list never changes
    _refused(400, book.edit, ali, desk, _fxspot())                        # nor its product
    # a trade entered by somebody else is the desk's: a user who did not enter it may still enter one
    other = book.add(veli, _ois(side="pay"))["id"]
    assert book.remove(veli, other) == {"deleted": other}
    _refused(401, book.listing, None, "desk")
    _refused(400, book.listing, ali, "herkes")
    store.close()


def test_every_change_is_logged_who_when_what():
    book, store, clock = _book()
    ali, admin = _user(store, "Ali Veli"), _user(store, "Yönetici", admin=True)
    tid = book.add(ali, _ois())["id"]
    book.edit(admin, tid, _ois(notional="150m", note="masa düzeltmesi"))
    book.close(ali, tid, TODAY, "38,10")
    book.reopen(admin, tid)
    book.remove(ali, tid)
    # (a deleted trade is not there any more: its log stays in the tab's log)
    entries = book.recent(ali, "desk")["entries"]
    assert [e["action"] for e in entries] == ["delete", "reopen", "close", "edit", "create"]
    assert [e["user_name"] for e in entries] == ["Ali Veli", "Yönetici", "Ali Veli", "Yönetici", "Ali Veli"]
    assert all(e["trade"] == tid and e["ts"][:10] == dt.date.today().isoformat() for e in entries)
    edit = entries[3]
    assert edit["text"] == "RECEIVE 2Y TRY OIS 150m @ %38,50" and edit["action_text"] == "değiştirdi"
    assert ["notional", 1e8, 1.5e8] in edit["changes"] and ["note", None, "masa düzeltmesi"] in edit["changes"]
    assert entries[2]["close_price_text"] == "%38,10" and entries[2]["close_date"] == TODAY
    assert entries[4]["text"] == "RECEIVE 2Y TRY OIS 100m @ %38,50"
    # one trade's log, oldest first; a trader's own trades' log is theirs only
    t2 = book.add(ali, _fxspot(scope="personal"))["id"]
    book.edit(ali, t2, _fxspot(scope="personal", price="42,20"))
    assert [e["action"] for e in book.log(ali, t2)["entries"]] == ["create", "edit"]
    assert [e["trade"] for e in book.recent(ali, "personal")["entries"]] == [t2, t2]
    assert book.recent(admin, "personal")["entries"] == [] and all(e["trade"] != t2 for e in book.recent(admin, "desk")["entries"])
    store.close()


# ---------------------------------------------------------------------- the desk's close
def test_the_close_is_taken_once_a_business_day_and_a_missed_one_at_the_next_start(planted):
    book, store, clock = _book()
    book.svc.ops = _Ops()
    ali = _user(store, "Ali Veli")
    clock.set("2026-11-16 09:00")
    tid = book.add(ali, _ois(trade_date="2026-11-16", settle_date="2026-11-17"))["id"]
    mine = book.add(ali, _fxspot(scope="personal", trade_date="2026-11-16", settle_date="2026-11-17"))["id"]
    planted.set(tid, "2026-11-16", 100.0, 10.0)
    book.started = dt.datetime(2026, 11, 16, 8, 0)
    assert store.tb_put_close("2026-11-13", "2026-11-13 17:30", False, [])
    assert not store.tb_put_close("2026-11-13", "2026-11-13 17:30", False, [])              # a day once
    at = lambda text: dt.datetime.strptime(text, "%Y-%m-%d %H:%M")                            # noqa: E731
    assert book.close_due(at("2026-11-16 17:29")) is None
    assert book.close_due(at("2026-11-16 17:30")) == ("2026-11-16", False)
    res = book.look(at("2026-11-16 17:30"))
    assert res == {"day": "2026-11-16", "at": "2026-11-16 17:30", "late": False, "trades": 2, "valued": 1}
    # every open trade - the desk's and each trader's own - valued as of that day
    assert sorted((c[0], c[1]) for c in planted.calls) == [(tid, "2026-11-16"), (mine, "2026-11-16")]
    kept = store.tb_closes([tid, mine])
    assert kept[tid]["2026-11-16"]["mtm"] == 100.0 and kept[tid]["2026-11-16"]["fp"] == tbm.fingerprint(store.tb_get(tid))
    assert kept[mine]["2026-11-16"]["ok"] is False
    assert book.look(at("2026-11-16 17:31")) is None and book.look(at("2026-11-16 23:59")) is None   # once a day
    assert book.close_due(at("2026-11-17 09:00")) is None                                          # (Tuesday's comes at 17:30)
    # off at Tuesday's close: started on Wednesday, Tuesday's is taken once the market data had its minutes - dated Tuesday
    book.started = at("2026-11-18 08:00")
    assert book.close_due(at("2026-11-18 08:01")) is None
    assert book.close_due(at("2026-11-18 08:04")) == ("2026-11-17", True)
    res = book.look(at("2026-11-18 08:04"))
    assert (res["day"], res["late"], res["trades"]) == ("2026-11-17", True, 2)
    assert store.tb_close_day("2026-11-17")["late"] == 1 and store.tb_close_day("2026-11-17")["at"] == "2026-11-17 17:30"
    assert book.look(at("2026-11-18 08:05")) is None
    # a trade closed on a day is not in that day's close (nor in a later one)
    clock.set("2026-11-18 12:00")
    book.close(ali, mine, "2026-11-18", "43")
    assert book.look(at("2026-11-18 17:30"))["trades"] == 1
    # a weekend and a holiday have no close; the time is the desk's setting
    book.svc.ops = _Ops(close="18:00", holidays={"2026-11-19"})
    assert book.close_due(at("2026-11-19 18:30")) is None                                          # Thursday: a holiday
    assert book.close_due(at("2026-11-20 17:59")) is None and book.close_due(at("2026-11-20 18:00")) == ("2026-11-20", False)
    assert book.look(at("2026-11-20 18:00"))["day"] == "2026-11-20"
    assert book.close_due(at("2026-11-21 12:00")) is None and book.close_due(at("2026-11-22 20:00")) is None
    assert book.take_close("2026-11-20") is None                                                   # taken already
    assert set(store.tb_closes([mine])[mine]) == {"2026-11-16", "2026-11-17"}                      # (closed on the 18th)
    assert set(store.tb_closes([tid])[tid]) == {"2026-11-16", "2026-11-17", "2026-11-18", "2026-11-20"}
    # one dealt after a day is not in that day's close
    clock.set("2026-11-23 09:00")
    late = book.add(ali, _ois(trade_date="2026-11-23", settle_date="2026-11-24"))["id"]
    assert late not in [r["id"] for r in store.tb_dealt_by("2026-11-20")]
    store.close()


def test_two_looks_at_once_take_one_close(monkeypatch):
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    clock.set("2026-11-16 09:00")
    for _ in range(3):
        book.add(ali, _ois(trade_date="2026-11-16", settle_date="2026-11-17"))

    def slow(trade, mkt, asof=None):
        time.sleep(0.05)
        return {"ok": False, "why": "yavaş"}

    monkeypatch.setattr(tv, "value", slow)
    book.started = dt.datetime(2026, 11, 16, 8, 0)
    now = dt.datetime(2026, 11, 16, 17, 31)
    got = []
    threads = [threading.Thread(target=lambda: got.append(book.look(now))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(x is None for x in got) == [False, True, True, True]
    assert [d["day"] for d in store.tb_close_days()] == ["2026-11-16"]
    assert len(store.tb_closes([r["id"] for r in store.tb_list("desk")])) == 3
    store.close()


# ---------------------------------------------------------------------- P&L periods: carry + price effect
def test_daily_weekly_and_total_p_and_l_split_into_carry_and_price_effect(planted):
    """An OIS dealt on Wednesday, its closes Wed / Thu / Fri / Mon, valued on Tuesday 11:30: the day against Monday's
    close, the week against Friday's (over the weekend: three days of Friday's carry), the total against its inception;
    the cash it received since (``accrued``) counts.  An FX spot dealt on Thursday and closed on Monday: its realised P&L,
    in the week's total but not in the day's."""
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    clock.set("2026-11-11 10:00")
    a = book.add(ali, _ois(trade_date="2026-11-11", settle_date="2026-11-12"))["id"]
    clock.set("2026-11-12 10:00")
    b = book.add(ali, _fxspot(trade_date="2026-11-12", settle_date="2026-11-13"))["id"]
    for day, mtm, carry in (("2026-11-11", 100.0, 10.0), ("2026-11-12", 130.0, 10.0), ("2026-11-13", 150.0, 12.0),
                            ("2026-11-16", 190.0, 12.0)):
        planted.set(a, day, mtm, carry, accrued=0.0)
    planted.set(b, "2026-11-12", 50.0, 5.0)
    planted.set(b, "2026-11-13", 80.0, 5.0)
    planted.set(b, "2026-11-16", 300.0, 0.0)                     # its value closed at its close price (asof: the close day)
    for day in ("2026-11-11", "2026-11-12", "2026-11-13"):
        assert book.take_close(day)
    clock.set("2026-11-16 16:00")
    closed = book.close(ali, b, "2026-11-16", "43,00")
    assert closed["closing"]["ok"] and closed["closing"]["mtm"] == 300.0
    call = planted.calls[-1]
    assert call[1] == "2026-11-16" and call[2]["status"] == "closed" and call[2]["manual_price"] == 43.0
    assert book.take_close("2026-11-16")["trades"] == 1                     # (the closed one is not in Monday's close)
    clock.set("2026-11-17 11:30")
    planted.set(a, None, 205.0, 15.0, accrued=5.0)
    res = book.mtm(ali, "desk")
    assert (res["last_close"], res["week_close"]) == ("2026-11-16", "2026-11-13")
    p = res["values"][str(a)]["periods"]
    day, week, total = p["day"], p["week"], p["total"]
    assert (day["from"], day["basis"], week["from"], total["basis"], total["from"]) == ("2026-11-16", "close", "2026-11-13", "inception", "2026-11-11")
    assert _near(day["pnl"]["ccy"], 20.0) and _near(day["carry"]["ccy"], 9.0) and _near(day["price"]["ccy"], 11.0)      # 210 − 190; 12 × 0,75
    assert _near(week["pnl"]["ccy"], 60.0) and _near(week["carry"]["ccy"], 45.0) and _near(week["price"]["ccy"], 15.0)  # 12 × 3 + 9
    assert _near(total["pnl"]["ccy"], 210.0) and _near(total["carry"]["ccy"], 65.0) and _near(total["price"]["ccy"], 145.0)
    assert _near(day["pnl"]["try"], 20.0) and _near(day["pnl"]["usd"], 0.5) and _near(week["carry"]["usd"], 45.0 / 40)
    # the closed one: its realised P&L (closed at 16:00 on Monday: two days and 22,5 hours of Friday's carry)
    q = res["closed"][str(b)]["periods"]
    assert _near(q["total"]["pnl"]["ccy"], 300.0) and _near(q["total"]["carry"]["ccy"], 5.0 + 5.0 * 2.9375)
    assert q["day"]["out"] and _near(q["week"]["pnl"]["ccy"], 220.0) and _near(q["week"]["carry"]["ccy"], 5.0 * 2.9375)
    tot = res["totals"]
    every = tot["all"]
    assert (every["count"], every["closed"]) == (1, 1)
    assert _near(every["day.pnl.try"], 20.0) and _near(every["week.pnl.try"], 280.0) and _near(every["total.pnl.try"], 210.0)
    assert _near(every["realized.pnl.try"], 300.0) and _near(every["mtm.try"], 205.0) and _near(every["mtm.usd"], 205.0 / 40)
    assert [x["product"] for x in tot["products"]] == ["ois", "fxspot"]
    assert _near(tot["products"][1]["week.carry.try"], 5.0 * 2.9375) and "day.pnl.try" not in tot["products"][1]
    # the list shows the closed trade's realised P&L without valuing anything: kept with its close value once worked out
    assert _near(store.tb_get(b)["closing"]["realized"]["pnl"]["ccy"], 300.0)
    assert _near(store.tb_get(b)["closing"]["realized"]["carry"]["ccy"], 5.0 + 5.0 * 2.9375)
    planted.calls.clear()
    listed = book.listing(ali, "desk")
    assert planted.calls == [] and _near(listed["closed"][0]["realized"]["periods"]["total"]["pnl"]["try"], 300.0)
    assert listed["mtm"]["values"][str(a)]["mtm"] == 205.0 and listed["mtm"]["at"] == "2026-11-17 11:30:00"
    store.close()


def test_a_trade_dealt_today_backdated_or_changed_after_a_close(planted):
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    clock.set("2026-11-16 10:00")
    edited = book.add(ali, _ois(trade_date="2026-11-16", settle_date="2026-11-17"))["id"]
    planted.set(edited, "2026-11-16", 40.0, 4.0)
    assert book.take_close("2026-11-16")
    clock.set("2026-11-17 09:00")
    new = book.add(ali, _ois(settle_date="2026-11-18"))["id"]
    old = book.add(ali, _ois(trade_date="2026-11-13", settle_date="2026-11-16"))["id"]       # entered late: no close of it
    book.edit(ali, edited, _ois(trade_date="2026-11-16", settle_date="2026-11-17", notional="300m"))
    clock.set("2026-11-17 11:30")
    for t in (new, old, edited):
        planted.set(t, None, 7.0, 2.0)
    res = book.mtm(ali, "desk")["values"]
    d = res[str(new)]["periods"]
    # dealt today: against its inception, no carry before its first close
    assert d["day"]["basis"] == "inception" and _near(d["day"]["pnl"]["ccy"], 7.0) and d["day"]["carry"]["ccy"] == 0.0
    assert _near(d["week"]["pnl"]["ccy"], 7.0) and _near(d["total"]["price"]["ccy"], 7.0)
    o = res[str(old)]["periods"]
    assert o["day"]["pnl"]["ccy"] is None and o["day"]["why"] == "16.11.2026 kapanışında kaydı yok"
    assert _near(o["total"]["pnl"]["ccy"], 7.0) and _near(o["total"]["carry"]["ccy"], 2.0 * (3 + 18 / 24.0))  # (its first carry, back)
    e = res[str(edited)]["periods"]
    assert e["day"]["why"] == "işlem 16.11.2026 kapanışından sonra değiştirildi" and _near(e["total"]["pnl"]["ccy"], 7.0)
    store.close()


def test_spread_and_fra_legs_each_with_their_p_and_l_and_what_they_leave_over(planted):
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    clock.set("2026-11-16 10:00")
    legs = [{"side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,5"},
            {"side": "pay", "end_date": "5Y", "notional": "45m", "price": "38,15"}]
    sp = book.add(ali, _ois(structure="spread", trade_date="2026-11-16", settle_date="2026-11-17", legs=legs, end_date="",
                            notional="", price=""))["id"]
    fra = book.add(ali, _ois(structure="fra", fra="3x6", trade_date="2026-11-16", settle_date="2026-11-17", end_date=""))["id"]
    planted.set(sp, "2026-11-16", 10.0, 10.0, legs=[("2Y", 4.0, 4.0), ("5Y", 6.0, 6.0)])
    planted.set(fra, "2026-11-16", 0.0, 1.0, legs=[("6A OIS", 30.0, 3.0), ("3A OIS", -30.0, -2.0)])
    assert book.take_close("2026-11-16")
    clock.set("2026-11-17 11:30")
    planted.set(sp, None, 110.0, 10.0, legs=[("2Y", 64.0, 4.0), ("5Y", 43.0, 6.0)])
    planted.set(fra, None, 25.0, 1.0, legs=[("6A OIS", 70.0, 3.0), ("3A OIS", -48.0, -2.0)])
    res = book.mtm(ali, "desk")["values"]
    s = res[str(sp)]["periods"]
    assert [lg["label"] for lg in s["legs"]] == ["2Y", "5Y"] and _near(s["day"]["pnl"]["ccy"], 100.0)
    assert _near(s["legs"][0]["day"]["pnl"]["ccy"], 60.0) and _near(s["legs"][1]["day"]["pnl"]["ccy"], 37.0)
    assert _near(s["legs"][0]["day"]["carry"]["ccy"], 3.0) and _near(s["legs"][1]["day"]["carry"]["ccy"], 4.5)
    assert _near(s["residual"]["day"]["pnl"]["ccy"], 3.0) and _near(s["residual"]["day"]["carry"]["ccy"], 0.0)
    assert _near(s["legs"][0]["total"]["pnl"]["ccy"], 64.0) and _near(s["legs"][1]["week"]["pnl"]["ccy"], 43.0)
    f = res[str(fra)]
    # a FRA: its total is the single instrument's value; the legs say where it came from; the rest is shown
    assert f["mtm"] == 25.0 and [lg["mtm"] for lg in f["legs"]] == [70.0, -48.0]
    assert _near(f["periods"]["day"]["pnl"]["ccy"], 25.0) and _near(f["periods"]["residual"]["day"]["pnl"]["ccy"], 3.0)
    assert _near(f["periods"]["legs"][1]["day"]["price"]["ccy"], -18.0 + 1.5)
    store.close()


def test_an_option_starts_at_its_premium(planted):
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    bought = book.add(ali, _fxopt())["id"]
    sold = book.add(ali, _fxopt(side="S"))["id"]
    in_usd = book.add(ali, _fxopt(price="3.750", premium_ccy="USD"))["id"]
    clock.set("2026-11-17 11:30")
    planted.set(bought, None, 180000.0, -1000.0)
    planted.set(sold, None, -180000.0, 1000.0)
    planted.set(in_usd, None, 180000.0, -1000.0)
    res = book.mtm(ali, "desk")["values"]
    t = res[str(bought)]["periods"]["total"]
    assert _near(t["pnl"]["ccy"], 30000.0) and t["carry"]["ccy"] == 0.0 and _near(t["pnl"]["usd"], 750.0)
    assert _near(res[str(sold)]["periods"]["total"]["pnl"]["ccy"], -30000.0)
    assert _near(res[str(in_usd)]["periods"]["total"]["pnl"]["try"], 30000.0, 1e-6)       # 3.750 USD × 40
    store.close()


def test_nothing_is_valued_until_mtm_yenile(monkeypatch):
    calls = {"market": 0, "value": 0}

    def market(svc):
        calls["market"] += 1
        return "piyasa"

    def value(trade, mkt, asof=None):
        calls["value"] += 1
        return {"ok": False, "why": "değerleme henüz yok"}

    monkeypatch.setattr(tv, "market", market)
    monkeypatch.setattr(tv, "value", value)
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    ids = [book.add(ali, _ois())["id"], book.add(ali, _fxspot())["id"], book.add(ali, _fxopt(scope="personal"))["id"]]
    book.edit(ali, ids[0], _ois(notional="20m"))
    book.listing(ali, "desk")
    book.listing(ali, "personal")
    book.check(ali, _ois())
    book.recent(ali, "desk")
    book.log(ali, ids[0])
    book.defaults(ali, "fxopt", "USDTRY", TODAY, "2026-12-17")
    assert calls == {"market": 0, "value": 0} and book.listing(ali, "desk")["mtm"] is None
    res = book.mtm(ali, "desk")
    assert calls == {"market": 1, "value": 2}
    v = res["values"][str(ids[0])]
    assert (v["ok"], v["why"]) == (False, "değerleme henüz yok") and v["periods"]["day"]["why"] == "değerleme henüz yok"
    assert res["at"] == "2026-11-17 10:00:00" and res["totals"]["all"]["missing"]["mtm.try"] == 2
    # the tab's last refresh comes back with its list; a change after it is said
    assert book.listing(ali, "desk")["mtm"]["at"] == res["at"] and not book.listing(ali, "desk")["mtm"]["stale"]
    book.add(ali, _ois(side="pay"))
    assert book.listing(ali, "desk")["mtm"]["stale"] and book.listing(ali, "personal")["mtm"] is None
    assert calls == {"market": 1, "value": 2}
    store.close()


def test_the_stub_values_nothing_and_says_why():
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    tid = book.add(ali, _ois())["id"]
    v = book.mtm(ali, "desk")["values"][str(tid)]
    assert (v["ok"], v["why"]) == (False, "değerleme henüz yok")
    assert tv.value({}, None) == {"ok": False, "why": "değerleme henüz yok"}
    assert tv.defaults("ois") == {"trade_date": dt.date.today().isoformat()}
    assert tv.notional_for_dv01({}, 1012) == 1e7 and tv.notional_for_dv01({}, 1) == 5e6 and tv.check({"a": 1}) == {"a": 1}
    assert tv.PRODUCTS == ("ois", "sofr", "dibs", "fxspot", "fxopt") and tv.market(None) is None
    store.close()


def test_the_live_counter_is_the_desk_s_and_one_s_own(monkeypatch):
    book, store, clock = _book()
    ali, veli = _user(store, "Ali Veli"), _user(store, "Veli Can")
    a0, v0 = book.counter(ali), book.counter(veli)
    book.add(ali, _fxspot(scope="personal"))
    assert book.counter(ali) == a0 + 1 and book.counter(veli) == v0                # nobody learns of another's own trades
    book.add(veli, _ois())
    assert book.counter(ali) == a0 + 2 and book.counter(veli) == v0 + 1 and book.svc.told == 2
    store.close()


# ---------------------------------------------------------------------- the form's defaults
def test_the_form_s_defaults_come_from_the_valuation(monkeypatch):
    book, store, clock = _book()
    ali = _user(store, "Ali Veli")
    got = book.defaults(ali, "ois")
    assert got["trade_date"] == dt.date.today().isoformat() and got["notional_ccy"] == "TRY"
    assert got["weights"] == {"spread": [1.0, 1.0], "fly": [0.5, 1.0, 0.5]} and got["meetings"] == []
    seen = []

    def defaults(product, pair=None, trade_date=None, mkt_or_svc=None):
        seen.append((product, pair, trade_date))
        if product == "fxspot":
            return {"trade_date": trade_date, "settle_date": "2026-12-21" if trade_date == "2026-12-17" else "2026-11-18"}
        if product == "fxopt":
            return {"trade_date": TODAY, "settle_date": "2026-11-18", "premium_ccy": pair[3:], "delivery": "2026-12-01"}
        return {"trade_date": TODAY, "settle_date": "2026-11-18", "value_date": "2026-11-18",
                "meetings": [{"meeting": "2026-12-11", "start": "2026-12-12", "end": "2027-01-23", "label": "PPK 11.12.2026"}]}

    monkeypatch.setattr(tv, "defaults", defaults)
    opt = book.defaults(ali, "fxopt", "usd/try", TODAY, "2026-12-17")
    # an option's delivery: its expiry's spot by the pair's conventions (the valuation's spot from the expiry)
    assert (opt["delivery"], opt["premium_ccy"], opt["notional_ccy"]) == ("2026-12-21", "TRY", "USD")
    assert seen == [("fxopt", "USDTRY", TODAY), ("fxspot", "USDTRY", "2026-12-17")]
    assert book.defaults(ali, "fxopt", "USDTRY", TODAY)["delivery"] == "2026-12-01"        # no expiry yet: the valuation's
    ois = book.defaults(ali, "ois", trade_date=TODAY)
    assert ois["meetings"][0]["meeting"] == "2026-12-11" and ois["settle_date"] == "2026-11-18"
    _refused(400, book.defaults, ali, "swap")
    _refused(401, book.defaults, None, "ois")

    def broken(*a, **k):
        raise RuntimeError("piyasa yok")

    monkeypatch.setattr(tv, "defaults", broken)
    assert book.defaults(ali, "sofr")["notional_ccy"] == "USD"                              # the form opens without them
    store.close()


# ---------------------------------------------------------------------- an earlier database
def test_an_earlier_database_gets_the_trades_tables_and_keeps_every_row(tmp_path):
    path = tmp_path / "tto.db"
    store = Store(str(path))
    user = store.login("Eski Kullanıcı")["user"]
    store.add_trade(TODAY, "fwd", {"pair": "USDTRY", "amount": 1e6}, user)
    store.put("bir.ayar", {"x": 1})
    store.close()
    new = ("tradebook", "tradebook_close_days", "tradebook_closes", "tradebook_log")
    con = sqlite3.connect(str(path))
    for table in new:
        con.execute("DROP TABLE %s" % table)
    con.commit()

    def rows():
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in names if t != "sqlite_sequence"}

    before = rows()
    assert not set(new) & set(before) and before["trades"] == 1 and before["users"] == 1
    con.close()
    store = Store(str(path))
    book = tbm.TradeBook(_Svc(store))
    book.now = _Clock()
    con = sqlite3.connect(str(path))
    try:
        assert rows() == dict(before, **{t: 0 for t in new})
    finally:
        con.close()
    assert store.trades(TODAY)[0]["pair"] == "USDTRY" and store.get("bir.ayar") == {"x": 1}
    tid = book.add(user, _ois())["id"]
    assert store.tb_get(tid)["product"] == "ois" and store.trades(TODAY)[0]["kind"] == "fwd"         # (the blotter's own table)
    store.close()


# ---------------------------------------------------------------------- the replay service, over HTTP
def _today():
    return dt.date.today().isoformat()


def _http_ois(**kw):
    d = {"scope": "desk", "product": "ois", "structure": "outright", "trade_date": _today(), "settle_date": "+1",
         "side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,50"}
    d.update(kw)
    return d


@pytest.fixture(scope="module")
def client(module_service):
    with TestClient(create_app(module_service)) as c:
        yield c


def test_the_page_is_in_the_desk_s_menu_and_the_trades_stay_out_of_the_desk_s_own(module_service):
    svc = module_service
    pages = [p["id"] for p in svc.nav()]
    assert pages[pages.index("blotter") + 1] == "trades"
    page = next(p for p in svc.nav() if p["id"] == "trades")
    assert (page["title"], page["group"], page["custom"]) == ("Trades", "Masa", True)
    assert svc.ops.settings()["trades_close"] == "17:30" and svc.tradebook.close_info()["time"] == "17:30"
    user = svc.login("Trades Kenarı")["user"]
    before = svc.blotter(user)
    svc.tradebook.add(user, _http_ois())
    svc.tradebook.add(user, {"scope": "personal", "product": "fxspot", "pair": "USDTRY", "trade_date": _today(),
                             "settle_date": "+1", "side": "B", "notional": "5m", "price": "42"})
    after = svc.blotter(user)
    # never in Günlük İşlemler, its positions and DV01, the RET flow: those read the blotter's own table
    assert after["trades"] == before["trades"] and svc.store.trades(_today()) == []
    assert len(svc.store.tb_list("desk")) >= 1 and len(svc.store.tb_list("personal", user)) == 1


def test_every_route_needs_a_session(client):
    for method, path in (("GET", "/api/trades"), ("POST", "/api/trades"), ("POST", "/api/trades/check"),
                         ("GET", "/api/trades/defaults?product=ois"), ("GET", "/api/trades/dv01"), ("POST", "/api/trades/dv01"),
                         ("POST", "/api/trades/mtm"), ("GET", "/api/trades/log"), ("POST", "/api/trades/1"),
                         ("DELETE", "/api/trades/1"), ("GET", "/api/trades/1/log"), ("POST", "/api/trades/1/close"),
                         ("POST", "/api/trades/1/reopen")):
        res = client.request(method, path, headers=ANON, json={} if method == "POST" else None)
        assert res.status_code == 401, (method, path)
    assert client.get("/static/js/pages/trades.js").status_code == 200


def test_a_personal_trade_reaches_its_owner_only_through_every_route(client, module_service):
    owner, other = auth(module_service, "Kişisel Sahip"), auth(module_service, "Başka Trader")
    admin = auth(module_service, "Trades Yönetici", admin=True)
    raw = {"scope": "personal", "product": "fxspot", "pair": "USDTRY", "trade_date": _today(), "settle_date": "+1",
           "side": "B", "notional": "5m", "price": "42,10", "note": "kendi notum"}
    # a change sent from another site's page is turned away before anything is read
    assert client.post("/api/trades", json=raw, headers=dict(owner, Origin="http://kotu.example")).status_code == 403
    tid = client.post("/api/trades", json=raw, headers=owner).json()["id"]
    assert tid in [t["id"] for t in client.get("/api/trades", params={"scope": "personal"}, headers=owner).json()["open"]]
    for who in (other, admin):
        for scope in ("personal", "desk"):
            got = client.get("/api/trades", params={"scope": scope}, headers=who).json()
            assert tid not in [t["id"] for t in got["open"] + got["closed"]]
            assert "kendi notum" not in str(got)
            assert str(tid) not in client.post("/api/trades/mtm", json={"scope": scope}, headers=who).json()["values"]
            assert all(e["trade"] != tid for e in client.get("/api/trades/log", params={"scope": scope}, headers=who).json()["entries"])
        for method, path, body in (("GET", "/api/trades/%d/log" % tid, None), ("POST", "/api/trades/%d" % tid, raw),
                                   ("POST", "/api/trades/%d/close" % tid, {"close_date": _today(), "close_price": "42"}),
                                   ("POST", "/api/trades/%d/reopen" % tid, {}), ("DELETE", "/api/trades/%d" % tid, None)):
            res = client.request(method, path, headers=who, json=body)
            assert res.status_code == 404 and res.json()["error"] == "işlem bulunamadı", (method, path)
    # the owner reaches it everywhere
    assert [e["action"] for e in client.get("/api/trades/%d/log" % tid, headers=owner).json()["entries"]] == ["create"]
    assert str(tid) in client.post("/api/trades/mtm", json={"scope": "personal"}, headers=owner).json()["values"]
    res = client.post("/api/trades/%d/close" % tid, json={"close_date": _today(), "close_price": "42,30"}, headers=owner)
    assert res.status_code == 200 and res.json()["closing"]["why"] == "değerleme henüz yok"
    assert client.delete("/api/trades/%d" % tid, headers=owner).json() == {"deleted": tid}


def test_a_desk_trade_over_http(client, module_service):
    ali, veli = auth(module_service, "Http Ali"), auth(module_service, "Http Veli")
    admin = auth(module_service, "Http Yönetici", admin=True)
    res = client.post("/api/trades", json=_http_ois(), headers=ali)
    assert res.status_code == 200 and res.json()["text"] == "RECEIVE 2Y TRY OIS 100m @ %38,50"
    tid = res.json()["id"]
    seen = client.get("/api/trades", params={"scope": "desk"}, headers=veli).json()
    row = next(t for t in seen["open"] if t["id"] == tid)
    assert (row["owner_name"], row["can_edit"], row["product_text"], row["price_text"]) == ("Http Ali", False, "TRY OIS", "%38,50")
    assert seen["close"]["time"] == "17:30"
    assert client.post("/api/trades/%d" % tid, json=_http_ois(notional="5m"), headers=veli).status_code == 403
    assert client.post("/api/trades/%d" % tid, json=_http_ois(notional="5m"), headers=admin).json()["changed"]
    bad = client.post("/api/trades", json=_http_ois(price=""), headers=ali)
    assert bad.status_code == 400 and bad.json()["fields"] == {"price": "Oran (%) gerekli"}
    pre = client.post("/api/trades/check", json=_http_ois(end_date="1Y"), headers=ali).json()
    assert pre["ok"] and pre["text"] == "RECEIVE 1Y TRY OIS 100m @ %38,50" and "1Y →" in pre["echo"]["end_date"]
    mtm = client.post("/api/trades/mtm", json={"scope": "desk"}, headers=veli).json()
    assert mtm["values"][str(tid)]["why"] == "değerleme henüz yok" and mtm["by_name"] == "Http Veli"
    got = client.get("/api/trades", params={"scope": "desk"}, headers=ali).json()["mtm"]
    assert got["at"] == mtm["at"]                                                     # the desk's last refresh is everybody's
    assert client.post("/api/trades/%d/close" % tid, json={"close_date": _today(), "close_price": ""}, headers=ali).status_code == 400
    assert client.post("/api/trades/%d/close" % tid, json={"close_date": _today(), "close_price": "38,2"}, headers=ali).status_code == 200
    log = client.get("/api/trades/%d/log" % tid, headers=veli).json()["entries"]
    assert [e["action"] for e in log] == ["create", "edit", "close"] and log[1]["user_name"] == "Http Yönetici"


def test_the_form_s_defaults_and_dv01_over_http(client, module_service):
    u = auth(module_service, "Http Form")
    got = client.get("/api/trades/defaults", params={"product": "ois"}, headers=u).json()
    assert got["trade_date"] == _today() and got["weights"]["fly"] == [0.5, 1.0, 0.5] and len(got["meetings"]) >= 3
    assert all(m["meeting"] >= _today() and m["label"].startswith("PPK ") for m in got["meetings"])
    assert client.get("/api/trades/defaults", params={"product": "sofr"}, headers=u).json()["meetings"][0]["label"].startswith("FOMC ")
    assert client.get("/api/trades/defaults", params={"product": "x"}, headers=u).status_code == 400
    one = client.get("/api/trades/dv01", params={"product": "ois", "trade_date": _today(), "settle_date": "+1", "end_date": "2Y",
                                                 "dv01": "2.012"}, headers=u).json()["units"][0]
    assert (one["notional"], one["dv01"]) == (2e7, 2000.0)
    body = dict(_http_ois(), size=[{"leg": None, "notional": "7m"}])
    assert client.post("/api/trades/dv01", json=body, headers=u).json()["units"][0]["dv01"] == 700.0


def test_an_mpc_trade_is_kept_by_its_meeting_s_date_while_the_calendar_moves(module_service, monkeypatch):
    svc = module_service
    h = svc.history
    user = svc.login("Takvim Trader")["user"]
    ahead = svc.tradebook.meetings("ois")
    meeting = ahead[2]
    tid = svc.tradebook.add(user, _http_ois(structure="mpc", meeting=meeting, end_date=""))["id"]
    start = h.meetings()
    seen = []
    monkeypatch.setattr(tv, "value", lambda t, m, asof=None: seen.append(t.get("meeting")) or {"ok": False, "why": "-"})
    try:
        # an extraordinary meeting before it: every meeting after moves a row down - the trade keeps its date
        extra = (dt.date.fromisoformat(ahead[0]) + dt.timedelta(days=7)).isoformat()
        assert extra < meeting
        h.set_calendar(user, [extra] + start[:-1])
        assert svc.tradebook.meetings("ois")[:4] == [ahead[0], extra, ahead[1], ahead[2]]
        row = svc.store.tb_get(tid)
        assert row["meeting"] == meeting
        text = next(t["text"] for t in svc.tradebook.listing(user, "desk")["open"] if t["id"] == tid)
        assert "PPK %s" % ".".join(reversed(meeting.split("-"))) in text
        svc.tradebook.mtm(user, "desk")
        assert meeting in seen
    finally:
        h.set_calendar(user, start)
    assert svc.tradebook.meetings("ois")[:3] == ahead[:3] and svc.store.tb_get(tid)["meeting"] == meeting
