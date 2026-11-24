"""Prop (tto/prop.py): the top bar's position-size calculator and prop risk - to look at only.

The calculator's maths on a market made here (the desk's worked example, rounding down to 1M, long / short, every
conversion path, what is typed and refused); the risk on Trades' own book with the real valuation on a market made here,
as tests/test_trades.py builds it (each product's loss at its stop, no stop, a stop already passed, a trade that cannot
be valued, today's K/Z = the Trades listing's "Günlük", the limit each user's own, the room, the scope); then the same
over HTTP on the replay service (no session: 401; a bad input: 400 with the reason)."""
import datetime as dt
import math
import time

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto import bonds as bd
from tto import prop as pp
from tto import tradebook as tbm
from tto import tradevalue as tv
from tto.server import create_app
from tto.service import Service, ServiceError
from tto.store import Store

D = dt.date
TODAY = D(2026, 11, 17)                    # a Tuesday


def _market(day=TODAY, usdtry=42.0, shift=0.0, spots=None):
    """A small market: USDTRY 42, EURTRY 48,3, EURUSD 1,15, USDJPY 150; flat curves (TRY OIS 40 %, SOFR 4 % - both
    ``shift``ed), USD / EUR OIS, an offshore TRY curve at 30 %, a bond of DİBS RV."""
    s = {"USDTRY": usdtry, "EURTRY": 48.3, "EURUSD": 1.15, "USDJPY": 150.0} if spots is None else spots
    m = tv.Market(day, usdtry=usdtry, on_rates={"TRY": 30.0, "USD": 4.0, "EUR": 2.0}, spots=s,
                  rates={"USD": [(1.0, 4.0), (3650.0, 4.0)], "EUR": [(1.0, 2.0), (3650.0, 2.0)]},
                  bonds={"TRT150328T24": {"isin": "TRT150328T24", "where": "DİBS RV", "kind": "fixed", "type": "S",
                                          "maturity": "2028-03-15", "coupon": 36.8, "freq": 2.0, "clean": 100.1125,
                                          "value_date": (day + dt.timedelta(days=1)).isoformat(), "source": "ISL1",
                                          "dv01_mn": 101.766}})
    m.curves = {"ois": tv.Curve.flat(m.spot_date("ois"), 0.40 + shift, 365.0),
                "sofr": tv.Curve.flat(m.spot_date("sofr"), 0.04 + shift, 360.0, interp="zero")}
    m.fixings = {"ois": tv.Fixings({}, 0.40, m.hol("TRY"), 365.0, "TLREF"), "sofr": tv.Fixings({}, 0.04, m.hol("SIFMA"), 360.0, "SOFR")}
    m.off = tv.Curve.flat(m.fx_spot_date("USDTRY"), 0.30, 360.0)
    return m


def _near(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


def _refused(fn, *args, **kw):
    with pytest.raises(pp.PropError) as exc:
        fn(*args, **kw)
    return str(exc.value)


# ---------------------------------------------------------------------------------------------- the calculator
def test_the_desk_s_worked_example():
    """USDTRY, entry 44,35, stop 44,55, a loss of 500k TL: short; 0,20 away; 2,5M raw; 2M USD; a real loss of 400.000 TL;
    200.000 TL a million."""
    r = pp.size(_market(), "USDTRY", 44.55, 500000.0, "TRY", entry=44.35)
    assert (r["direction"], r["direction_text"], r["base"], r["quote"]) == ("short", "SHORT · SAT", "USD", "TRY")
    assert _near(r["distance"], 0.20, 1e-12) and _near(r["size_raw"], 2.5e6, 1e-9)
    assert (r["size"], r["lots"], r["under_1m"]) == (2e6, 2, False)
    assert _near(r["real_loss"]["try"], 400000.0) and _near(r["real_loss"]["ccy"], 400000.0) and _near(r["real_loss"]["quote"], 400000.0)
    assert _near(r["per_1m"]["try"], 200000.0) and _near(r["real_loss"]["usd"], 400000.0 / 42.0)
    assert _near(r["kurus"], 20.0) and _near(r["pips"], 2000.0) and _near(r["distance_pct"], 0.20 / 44.35 * 100.0)
    assert r["entry_typed"] and r["mid"] == 42.0 and r["mid_how"] == "Forward sayfası"
    assert r["note"] == "SHORT · SAT 2M USD · gerçek kayıp 400.000 TRY"


def test_the_size_is_rounded_down_never_above_the_loss_and_under_1m_says_so():
    m = _market()
    # a lira short of 2M's loss: 1M - never up to 2M
    r = pp.size(m, "USDTRY", 44.55, 399999.0, "TRY", entry=44.35)
    assert r["size"] == 1e6 and r["real_loss"]["try"] <= 399999.0 and _near(r["real_loss"]["try"], 200000.0)
    # exactly 2M's loss: 2M (the float noise of 44,55 − 44,35 does not make it a lot less)
    assert pp.size(m, "USDTRY", 44.55, 400000.0, "TRY", entry=44.35)["size"] == 2e6
    # under 1M: no size, and what 1M would lose
    r = pp.size(m, "USDTRY", 44.55, 150000.0, "TRY", entry=44.35)
    assert (r["size"], r["lots"], r["under_1m"], r["real_loss"]) == (0.0, 0, True, None) and _near(r["per_1m"]["try"], 200000.0)
    assert r["note"] == "1M bile 150.000 TRY kaybı aşıyor: 1M'de kayıp 200.000 TRY"
    # across losses and stops: the real loss never above the loss typed (but for the float noise of the distance: 42 −
    # 41,9999 is 0,000100000000003), and never a whole 1M below it
    for loss in (95e3, 250e3, 1e6, 3.3e6, 12.5e6):
        for stop in (41.0, 41.73, 41.9999, 42.01, 43.5):
            r = pp.size(m, "USDTRY", stop, loss, "TRY")
            real = r["real_loss"]["ccy"] if r["real_loss"] else 0.0
            assert real <= loss * (1 + 1e-9) and loss - real < r["per_1m"]["ccy"] * (1 + 1e-9), (loss, stop, r["size"])
            assert r["size"] % 1e6 == 0
    assert pp.size(m, "USDTRY", 41.9999, 1e6, "TRY")["size"] == 1e10                 # (1M over a pip: 10 000M, not 9 999M)


def test_long_below_the_entry_short_above_equal_refused_entry_the_live_mid():
    m = _market()
    r = pp.size(m, "USDTRY", 41.0, 1e6, "TRY")
    assert (r["direction"], r["entry"], r["entry_typed"], r["size"]) == ("long", 42.0, False, 1e6) and _near(r["distance"], 1.0)
    r = pp.size(m, "USDTRY", 43.0, 1e6, "TRY")
    assert (r["direction"], r["direction_text"]) == ("short", "SHORT · SAT")
    assert pp.size(m, "USDTRY", 43.0, 1e6, "TRY", entry=44.0)["direction"] == "long"          # (a typed entry decides)
    assert "stop girişe eşit olamaz" in _refused(pp.size, m, "USDTRY", 42.0, 1e6, "TRY")


def test_the_loss_in_the_pair_s_quote_currency_every_way():
    m = _market()
    # USDTRY with a TL loss: as it is; with a USD loss: × USDTRY
    r = pp.size(m, "USDTRY", 41.0, 1e6, "TRY", entry=42.0)
    assert r["loss_quote"] == 1e6 and r["size"] == 1e6
    r = pp.size(m, "USDTRY", 41.0, 50000.0, "USD", entry=42.0)
    assert _near(r["loss_quote"], 2.1e6) and r["size"] == 2e6 and _near(r["real_loss"]["ccy"], 2e6 / 42.0) and _near(r["real_loss"]["try"], 2e6)
    # EURUSD with a TL loss: TL → USD over USDTRY (1M TL = 23 809,52 USD; 0,01 away: 2,38M → 2M EUR, 20 000 USD)
    r = pp.size(m, "EURUSD", 1.14, 1e6, "TRY", entry=1.15)
    assert _near(r["loss_quote"], 1e6 / 42.0) and r["size"] == 2e6 and r["base"] == "EUR"
    assert _near(r["real_loss"]["quote"], 20000.0) and _near(r["real_loss"]["ccy"], 840000.0) and _near(r["real_loss"]["usd"], 20000.0)
    # ... with a USD loss: none
    assert pp.size(m, "EURUSD", 1.14, 25000.0, "USD", entry=1.15)["loss_quote"] == 25000.0
    # USDJPY with a USD loss: × USDJPY; with a TL loss: TL → USD → JPY
    r = pp.size(m, "USDJPY", 151.0, 10000.0, "USD", entry=150.0)
    assert _near(r["loss_quote"], 1.5e6) and r["size"] == 1e6 and _near(r["real_loss"]["ccy"], 1e6 / 150.0)
    assert _near(r["real_loss"]["try"], 1e6 / 150.0 * 42.0) and _near(r["pips"], 100.0)            # (a yen pair's pip: 0,01)
    r = pp.size(m, "USDJPY", 151.0, 1e6, "TRY", entry=150.0)
    assert _near(r["loss_quote"], 1e6 / 42.0 * 150.0) and r["size"] == 3e6 and r["kurus"] is None
    # EURTRY with a USD loss: × USDTRY
    assert _near(pp.size(m, "EURTRY", 48.0, 10000.0, "USD", entry=48.3)["loss_quote"], 420000.0)
    # a pair the market does not price but both of its TL prices: their cross (EURUSD = EURTRY / USDTRY)
    m2 = _market(spots={"USDTRY": 42.0, "EURTRY": 48.3})
    assert pp.spot_of(m2, "EURUSD") == (48.3 / 42.0, "çapraz kur (EURTRY / USDTRY)")
    assert pp.spot_of(m, "EURUSD") == (1.15, "quant FX verisi") and pp.spot_of(m, "USDTRY") == (42.0, "Forward sayfası")
    assert pp.spot_of(m, "EURJPY") == (1.15 * 150.0, "çapraz kur (USD üzerinden)") and pp.spot_of(m2, "USDJPY") == (None, "fiyat yok")
    assert "USDJPY: canlı fiyat yok" in _refused(pp.size, m2, "USDJPY", 151.0, 1e4, "USD")


def test_a_size_typed_gives_the_loss_at_the_stop():
    """Two-way (the desk, 24.11.2026: "tüm tablolar bu şekilde olmalı"): the size typed instead of the loss - the stop as
    given, the loss it makes there worked out (size · |entry − stop| into the loss's currency), the size as typed (not
    rounded).  The desk's example the other way round: 2,5M at 0,20 is 500.000 TL; each loss's size typed back gives that
    loss again; the loss typed gives what it did before (the anchor said)."""
    m = _market()
    r = pp.size(m, "USDTRY", 44.55, None, "TRY", entry=44.35, amount=2.5e6)
    assert (r["anchor"], r["direction"], r["size"], r["lots"], r["under_1m"]) == ("size", "short", 2.5e6, 2.5, False)
    assert _near(r["loss"], 5e5) and _near(r["real_loss"]["try"], 5e5) and _near(r["loss_quote"], 5e5) and _near(r["per_1m"]["try"], 2e5)
    assert r["note"] == "SHORT · SAT 2,5M USD · kayıp 500.000 TRY"
    assert pp.size(m, "USDTRY", 44.55, 5e5, "TRY", entry=44.35)["anchor"] == "loss"
    # every conversion path, and back: the loss found typed as the loss gives the size typed (raw, before rounding)
    for pair, stop, entry, amount, ccy, loss in (("USDTRY", 41.0, 42.0, 2e6, "USD", 2e6 / 42.0), ("EURUSD", 1.14, 1.15, 2e6, "TRY", 840000.0),
                                                 ("USDJPY", 151.0, 150.0, 1e6, "USD", 1e6 / 150.0), ("EURTRY", 48.0, 48.3, 3e6, "TRY", 9e5)):
        r = pp.size(m, pair, stop, None, ccy, entry=entry, amount=amount)
        assert _near(r["loss"], loss) and _near(r["real_loss"]["ccy"], loss) and r["size"] == amount, pair
        back = pp.size(m, pair, stop, r["loss"], ccy, entry=entry)
        assert _near(back["size_raw"], amount, 1e-9) and back["size"] <= amount, pair
        assert _near(pp.size(m, pair, stop, None, ccy, entry=entry, amount=back["size"])["loss"], back["real_loss"]["ccy"]), pair
    # a size under 1M is a size too (the loss it makes, nothing rounded away)
    r = pp.size(m, "USDTRY", 41.0, None, "TRY", entry=42.0, amount=500000.0)
    assert r["size"] == 5e5 and r["lots"] == 0.5 and not r["under_1m"] and _near(r["loss"], 5e5)
    assert "stop girişe eşit olamaz" in _refused(pp.size, m, "USDTRY", 42.0, None, "TRY", amount=1e6)


def test_the_panel_reads_the_size_or_the_loss(monkeypatch):
    """The panel's request: ``size`` in place of ``loss`` (the one the user typed last); both - the loss, as before; a size
    read as an amount (2,5m) and refused with the reason."""
    _, store, _, prop, _ = _desk(monkeypatch)
    ali = _user(store, "Prop İki Yön")
    q = {"pair": "usdtry", "entry": "44,35", "stop": "44,55", "ccy": "TRY"}
    r = prop.calc(ali, dict(q, size="2,5m"))
    assert r["anchor"] == "size" and r["size"] == 2.5e6 and _near(r["loss"], 5e5)
    r = prop.calc(ali, dict(q, size="2,5m", loss="500k"))
    assert r["anchor"] == "loss" and r["size"] == 2e6
    assert prop.calc(ali, dict(q, loss="", size="3m"))["anchor"] == "size"
    assert _refused(prop.calc, ali, dict(q, size="0")) == "Büyüklük sıfırdan büyük olmalı"
    assert _refused(prop.calc, ali, dict(q, size="çok")) == "Büyüklük anlaşılamadı: çok (örn. 500k, 1mn, 2,5mn)"
    assert _refused(prop.calc, ali, q) == "Kayıp gerekli"


class _Svc(object):
    """What Trades' book and the panel need of the service: its store, who is signed in, a way to tell the pages."""
    require_user = Service.require_user

    def __init__(self, store):
        self.store = store
        self.started_at = time.time() - 86400

    def nudge(self):
        pass

    def saw(self, user):
        pass

    def holiday_dates(self, ccys):
        return frozenset()


class _Clock(object):
    def __init__(self, text):
        self.set(text)

    def set(self, text):
        self.at = dt.datetime.strptime(text, "%Y-%m-%d %H:%M")

    def __call__(self):
        return self.at


def _desk(monkeypatch, when="2026-11-17 10:00", **kw):
    """Trades' book on a database of its own, the panel over it, the real valuation on ``_market`` (``state["m"]``: the
    market now - a test moves it)."""
    store = Store(":memory:")
    svc = _Svc(store)
    book = tbm.TradeBook(svc)
    clock = _Clock(when)
    book.now = clock
    svc.tradebook = book
    state = {"m": _market(clock().date(), **kw)}
    monkeypatch.setattr(tv, "market", lambda s, curve="boot": state["m"])
    monkeypatch.setattr(pp, "MARKET_SECONDS", 0.0)
    return book, store, clock, pp.Prop(svc), state


def _user(store, name):
    return store.login(name)["user"]


def test_what_is_typed_and_what_is_refused(monkeypatch):
    assert (pp.read_pair("usd/try"), pp.read_pair(" Eurusd "), pp.read_pair("gbp")) == ("USDTRY", "EURUSD", "GBPTRY")
    assert _refused(pp.read_pair, "") == "parite yazın (örn. USDTRY)" and _refused(pp.read_pair, "xx") == "parite anlaşılamadı: xx"
    assert (pp.read_price("44,55", "Stop"), pp.read_price("44.550", "Stop"), pp.read_price("1.234,5", "Stop")) == (44.55, 44.55, 1234.5)
    assert pp.read_price("44.55", "Stop", "en") == 44.55 and pp.read_price(44.5, "Stop") == 44.5
    assert _refused(pp.read_price, "abc", "Stop") == "Stop anlaşılamadı: abc" and _refused(pp.read_price, "", "Stop") == "Stop gerekli"
    assert _refused(pp.read_price, "-1", "Giriş") == "Giriş sıfırdan büyük olmalı"
    assert [pp.read_amount(x, "Kayıp") for x in ("500k", "1mn", "2,5mn", "1.000.000", "250 bin")] == [5e5, 1e6, 2.5e6, 1e6, 2.5e5]
    assert pp.read_amount("1.5mn", "Kayıp", "en") == 1.5e6
    assert _refused(pp.read_amount, "çok", "Kayıp") == "Kayıp anlaşılamadı: çok (örn. 500k, 1mn, 2,5mn)"
    assert _refused(pp.read_amount, "0", "Kayıp") == "Kayıp sıfırdan büyük olmalı"
    assert (pp.read_ccy("tl"), pp.read_ccy(" usd")) == ("TRY", "USD") and _refused(pp.read_ccy, "EUR", "Kaybın dövizi") == "Kaybın dövizi TRY ya da USD olmalı"
    # the panel's request: the desk's pairs only, with a price; each input read as typed
    book, store, clock, prop, state = _desk(monkeypatch)
    ali = _user(store, "Ali Veli")
    q = {"pair": "usdtry", "entry": "44,35", "stop": "44,55", "loss": "500k", "ccy": "TRY"}
    assert prop.calc(ali, q)["size"] == 2e6
    assert prop.calc(ali, dict(q, entry="44.35", stop="44.55"), "en")["size"] == 2e6
    assert "USDSGD masanın FX listesinde yok" in _refused(prop.calc, ali, dict(q, pair="USDSGD"))
    assert _refused(prop.calc, ali, dict(q, pair="USDZAR")).startswith("USDZAR: canlı fiyat yok")    # (the quant's list; no price here)
    assert _refused(prop.calc, ali, dict(q, stop="")) == "Stop gerekli" and _refused(prop.calc, ali, dict(q, loss="")) == "Kayıp gerekli"
    assert _refused(prop.calc, ali, dict(q, ccy="")) == "Kaybın dövizi TRY ya da USD olmalı"
    assert _refused(prop.calc, ali, dict(q, entry="x")) == "Giriş anlaşılamadı: x"
    with pytest.raises(ServiceError) as exc:
        prop.calc(None, q)
    assert exc.value.status == 401
    # what the panel opens with: the desk's pairs that have a price, in the desk's order (the quant's list, then the board's)
    got = prop.state(ali)
    assert [(p["pair"], p["how"]) for p in got["pairs"]] == [
        ("USDTRY", "Forward sayfası"), ("EURTRY", "Forward sayfası"), ("EURUSD", "quant FX verisi"), ("USDJPY", "quant FX verisi"),
        ("EURJPY", "çapraz kur (USD üzerinden)")]
    assert got["pairs"][0]["mid"] == 42.0 and got["pairs"][3]["decimals"] == 3 and got["limit"] is None and got["lot"] == 1e6


# ---------------------------------------------------------------------------------------------- the risk
def _value(store, tid, m):
    return tv.value(tbm.TradeBook.for_value(store.tb_get(tid)), m)


BASE = {"scope": "personal", "trade_date": "2026-11-17", "settle_date": "2026-11-18"}


def test_the_loss_at_each_stop_product_by_product(monkeypatch):
    """Each product's loss if its stop is hit, from the market now, in its own level's unit with its valuation's
    sensitivity - against a hand calculation from the same valuation; a stop already passed adds nothing (what is beyond
    it is said apart); a trade without a stop is listed with its DV01 / size / delta; one that cannot be valued, apart."""
    book, store, clock, prop, state = _desk(monkeypatch)
    ali = _user(store, "Ali Veli")
    add = lambda **kw: book.add(ali, dict(BASE, **kw))["id"]          # noqa: E731
    ids = {
        "ois": add(product="ois", structure="outright", side="receive", end_date="2Y", notional="100m", price="42", stop="42,50"),
        "sofr": add(product="sofr", structure="outright", side="pay", settle_date="2026-11-19", end_date="5Y", notional="25m",
                    price="4", stop="3,90"),
        "fra": add(product="ois", structure="fra", side="pay", fra="3x6", notional="100m", price="40", stop="41,60"),
        "spread": add(product="ois", structure="spread", side="steepener", stop="-10", legs=[
            {"side": "receive", "end_date": "2Y", "notional": "100m", "price": "40"},
            {"side": "pay", "end_date": "5Y", "notional": "50m", "price": "40"}]),
        "fly": add(product="ois", structure="fly", stop="-5", legs=[
            {"side": "receive", "end_date": "1Y", "notional": "100m", "price": "40"},
            {"side": "pay", "end_date": "2Y", "notional": "100m", "price": "40"},
            {"side": "receive", "end_date": "5Y", "notional": "25m", "price": "40"}]),
        "dibs_px": add(product="dibs", isin="TRT150328T24", side="B", notional="10m", price="101", stop="99,5"),
        "dibs_y": add(product="dibs", isin="TRT150328T24", side="B", notional="10m", price_kind="yield", price="39", stop="41"),
        "usdtry": add(product="fxspot", pair="USDTRY", side="B", notional="10m", price="41,50", stop="41,80"),
        "eurusd": add(product="fxspot", pair="EURUSD", side="S", settle_date="2026-11-19", notional="5m", price="1,14", stop="1,16"),
        "opt": add(product="fxopt", pair="USDTRY", call_put="call", side="B", strike="44", expiry="2027-02-17", delivery="2027-02-18",
                   notional="10m", price="5mn", premium_ccy="TRY", manual_price="15", stop="4mn"),
        "passed": add(product="ois", structure="outright", side="receive", end_date="2Y", notional="100m", price="40", stop="40,50"),
        "nostop": add(product="ois", structure="outright", side="pay", end_date="1Y", notional="50m", price="40"),
        "fx_nostop": add(product="fxspot", pair="USDTRY", side="S", notional="3m", price="42,10"),
        "opt_nostop": add(product="fxopt", pair="USDTRY", call_put="put", side="S", strike="40", expiry="2027-02-17",
                          delivery="2027-02-18", notional="5m", price="1mn", premium_ccy="TRY", manual_price="15"),
        "unvalued": add(product="dibs", isin=bd.listed(TODAY)[0]["isin"], side="B", notional="5m", price="90", stop="85"),
    }
    m = state["m"]
    r = prop.risk(ali)
    rows = {row["id"]: row for row in r["trades"] + r["nostop"]}
    assert set(rows) == set(ids.values()) and r["scope"] == "personal" and r["scope_text"] == "Kişisel"

    def check(key, per, ccy, unit=None):
        row, v = rows[ids[key]], _value(store, ids[key], m)
        t = store.tb_get(ids[key])
        now = tbm.level_now(t, v)
        up = tbm.gains_up(t)
        gap = (now - t["stop"]) * (1 if up else -1)
        assert row["state"] == "open" and gap > 0 and _near(row["now"], now) and _near(row["sens"]["per"], per), (key, row)
        assert row["loss"]["ccy"] == ccy and _near(row["loss"]["amount"], per * gap, 1e-9), (key, row["loss"], per * gap)
        assert _near(row["loss"]["try"], per * gap * (42.0 if ccy == "USD" else 1.0), 1e-9)
        assert _near(row["loss"]["usd"], per * gap / (42.0 if ccy == "TRY" else 1.0), 1e-9)
        assert row["to_stop"] > 0 and (unit is None or row["unit"] == unit)
        return v, row

    # TRY OIS / SOFR / FRA: their DV01 (notional × annuity × 1 bp) × the bp to the stop
    for key, ccy in (("ois", "TRY"), ("sofr", "USD"), ("fra", "TRY")):
        v = _value(store, ids[key], m)
        check(key, v["inputs"]["dv01"] * 100.0, ccy, "bp")
    # ... which is what the swap loses when the market takes its rate there (first order): the receiver's 2Y with the
    # curve 25 bp up
    v0 = _value(store, ids["ois"], m)
    v1 = _value(store, ids["ois"], _market(shift=0.0025))
    moved = (v1["price_now"] - v0["price_now"]) * 100.0
    assert 20.0 < moved < 30.0 and abs(v0["inputs"]["dv01"] * moved - (v0["mtm"] - v1["mtm"])) < 0.02 * abs(v0["mtm"] - v1["mtm"])
    # a spread / fly: the level's DV01 - half its legs' DV01s - × the level's bp
    for key in ("spread", "fly"):
        v = _value(store, ids[key], m)
        v, row = check(key, 0.5 * sum(v["inputs"]["legs_dv01"]), "TRY", "bp")
        assert row["sens"]["what"].startswith("seviyenin DV01'i")
    # DİBS by its price: nominal × the price points / 100 (10m, 100,1125 → 99,5: 61.250 TL); by its yield: DİBS RV's DV01
    _, row = check("dibs_px", 10e6 / 100.0, "TRY", "puan")
    assert _near(row["loss"]["try"], 10e6 * (100.1125 - 99.5) / 100.0, 1e-9)
    _, row = check("dibs_y", 10e6 / 1e6 * 101.766 * 100.0, "TRY", "bp")
    assert row["sens"]["dv01"] == pytest.approx(1017.66)
    # FX spot: the base amount × the rate's distance (USDTRY 10m, 42 → 41,80: 2M TL; EURUSD 5m sold, 1,15 → 1,16: 50k USD)
    _, row = check("usdtry", 10e6, "TRY", "pip")
    assert _near(row["loss"]["try"], 2e6) and _near(row["to_stop"], 2000.0)
    _, row = check("eurusd", 5e6, "USD", "pip")
    assert _near(row["loss"]["usd"], 50000.0) and _near(row["loss"]["try"], 2.1e6)
    # an FX option: its stop is a premium - the loss is the premium's distance; the delta says where the spot would be
    v, row = check("opt", 1.0, "TRY", "%")
    assert _near(row["loss"]["try"], v["inputs"]["premium_now"] - 4e6) and row["approx"] == "yaklaşık (delta)"
    assert row["spot_at_stop"] < 42.0                                 # (a call bought loses as the spot falls)
    near = v["inputs"]["premium_now"] * 0.995                         # (a stop half a percent away: the delta's spot reprices to it)
    s = pp._spot_at_stop(store.tb_get(ids["opt"]), v, near, v["inputs"]["premium_now"])
    again = _value(store, ids["opt"], _market(usdtry=s))
    assert abs(again["inputs"]["premium_now"] / near - 1.0) < 2e-4, (s, again["inputs"]["premium_now"], near)
    # a stop already passed (a receiver at 40 with its stop at 40,50, the rate now above it): nothing more to lose at the
    # stop - what lies beyond it is in the MTM already, said apart
    row, v = rows[ids["passed"]], _value(store, ids["passed"], m)
    beyond = v["inputs"]["dv01"] * (v["price_now"] - 40.5) * 100.0
    assert row["state"] == "passed" and row["loss"]["try"] == 0.0 and _near(row["beyond"]["try"], beyond) and row["to_stop"] < 0
    # no stop: listed apart with its DV01, its size (signed), its delta (approximate)
    nostop = {row["id"]: row for row in r["nostop"]}
    assert set(nostop) == {ids["nostop"], ids["fx_nostop"], ids["opt_nostop"]}
    e = nostop[ids["nostop"]]["exposure"]
    assert (e["kind"], e["ccy"]) == ("dv01", "TRY") and _near(e["amount"], _value(store, ids["nostop"], m)["inputs"]["dv01"])
    e = nostop[ids["fx_nostop"]]["exposure"]
    assert (e["kind"], e["ccy"], e["amount"]) == ("size", "USD", -3e6) and _near(e["try"], -3e6 * 42.0)
    e = nostop[ids["opt_nostop"]]["exposure"]
    assert e["kind"] == "delta" and e["approx"] and e["ccy"] == "USD" and _near(e["amount"], _value(store, ids["opt_nostop"], m)["greeks"]["delta"])
    # a bond the market does not price: said, and left out of the sum
    row = rows[ids["unvalued"]]
    assert row["state"] == "unvalued" and "fiyat yok" in row["why"]
    # Stoplar: the stops still ahead, summed in TL and USD; the passed one adds nothing; the unknown one is counted apart
    ahead = [row for row in r["trades"] if row["state"] == "open"]
    assert len(ahead) == 10 and r["stops"]["count"] == 10 and r["stops"]["passed"] == 1 and r["stops"]["unknown"] == 1
    assert _near(r["stops"]["try"], sum(row["loss"]["try"] for row in ahead), 1e-12)
    assert _near(r["stops"]["usd"], sum(row["loss"]["usd"] for row in ahead), 1e-12)
    # (the biggest loss first; the passed, the unknown after the open ones)
    assert [row["state"] for row in r["trades"]][-2:] == ["passed", "unvalued"]
    losses = [row["loss"]["try"] for row in ahead]
    assert losses == sorted(losses, reverse=True)
    store.close()


def test_today_s_k_z_is_the_trades_listing_s_gunluk(monkeypatch):
    """Bugün K/Z is the tab's "Günlük" as the Trades page shows it: the totals of its last "MTM yenile" (today's) -
    none before it, none from another day."""
    book, store, clock, prop, state = _desk(monkeypatch, when="2026-11-16 10:00")
    ali = _user(store, "Ali Veli")
    base = dict(BASE, trade_date="2026-11-16", settle_date="2026-11-17")
    book.add(ali, dict(base, product="fxspot", pair="USDTRY", side="B", notional="10m", price="42", stop="41,5"))
    book.add(ali, dict(base, product="ois", structure="outright", side="receive", end_date="2Y", notional="100m", price="42"))
    book.add(ali, dict(base, scope="desk", product="fxspot", pair="EURUSD", side="S", notional="5m", price="1,15"))
    clock.set("2026-11-16 17:30")
    assert book.take_close("2026-11-16")["valued"] == 3
    clock.set("2026-11-17 10:00")
    state["m"] = _market(D(2026, 11, 17), usdtry=41.8, shift=0.001)
    pnl = prop.risk(ali)["pnl"]
    assert pnl["try"] is None and "MTM yenile\" yapılmadı" in pnl["why"]
    book.mtm(ali, "personal")
    for scope in ("personal", "desk"):
        if scope == "desk":
            book.mtm(ali, "desk")
        page = book.listing(ali, scope)["mtm"]["totals"]["all"]
        got = prop.risk(ali, scope)["pnl"]
        assert got["try"] == page["day.pnl.try"] and got["usd"] == page["day.pnl.usd"] and got["why"] is None, (scope, got, page)
        assert got["at"] == "2026-11-17 10:00:00" and got["missing"] == 0
    personal = prop.risk(ali)["pnl"]
    assert personal["try"] < 0 and _near(personal["used_try"], -personal["try"])        # (USDTRY 42 → 41,8 on 10m: −2M TL and the swap's)
    # an "MTM yenile" of another day is not today's K/Z
    clock.set("2026-11-18 09:00")
    got = prop.risk(ali)["pnl"]
    assert got["try"] is None and got["why"] == "son \"MTM yenile\" bugünün değil (17.11.2026): bugünkü K/Z bilinmiyor"
    store.close()


def test_the_limit_is_each_user_s_own(monkeypatch):
    book, store, clock, prop, state = _desk(monkeypatch)
    ali, veli = _user(store, "Ali Veli"), _user(store, "Veli Can")
    assert prop.set_limit(ali, "1mn", "TRY")["limit"]["amount"] == 1e6
    assert prop.limit(ali)["ccy"] == "TRY" and prop.limit(veli) is None and prop.risk(veli)["limit"] is None
    assert prop.set_limit(veli, "50k", "usd")["limit"] == dict(prop.limit(veli), amount=5e4, ccy="USD")
    assert prop.limit(ali)["amount"] == 1e6 and store.get("prop.limit:" + ali)["amount"] == 1e6
    assert store.get("prop.limit:" + veli)["ccy"] == "USD"
    assert prop.state(ali)["limit"]["amount"] == 1e6 and prop.state(veli)["limit"]["ccy"] == "USD"
    assert _refused(prop.set_limit, ali, "bol", "TRY") == "Günlük kayıp limiti anlaşılamadı: bol (örn. 500k, 1mn, 2,5mn)"
    assert _refused(prop.set_limit, ali, "1mn", "EUR") == "Limitin dövizi TRY ya da USD olmalı"
    assert prop.limit(ali)["amount"] == 1e6                                  # (a refused change leaves it)
    assert prop.set_limit(ali, "", "TRY") == {"limit": None} and prop.limit(ali) is None and prop.limit(veli)["amount"] == 5e4
    store.close()


def test_room_is_the_limit_less_today_s_loss_less_the_stops(monkeypatch):
    # gains give no room; a loss takes it; nothing to say without any of the three
    assert pp.room(1e6, 5e5, 2e5) == 8e5 and pp.room(1e6, -3e5, 2e5) == 5e5 and pp.room(1e6, 0.0, 0.0) == 1e6
    assert pp.room(1e6, -2e6, 0.0) == -1e6 and pp.room(None, 0.0, 0.0) is None and pp.room(1e6, None, 0.0) is None
    book, store, clock, prop, state = _desk(monkeypatch, when="2026-11-16 10:00")
    ali = _user(store, "Ali Veli")
    base = dict(BASE, trade_date="2026-11-16", settle_date="2026-11-17")
    book.add(ali, dict(base, product="fxspot", pair="USDTRY", side="B", notional="10m", price="42", stop="41,5"))
    clock.set("2026-11-16 17:30")
    book.take_close("2026-11-16")
    clock.set("2026-11-17 10:00")
    state["m"] = _market(D(2026, 11, 17), usdtry=41.9)
    r = prop.risk(ali)
    assert r["room"] == {"try": None, "usd": None, "why": "günlük kayıp limiti yok"}
    prop.set_limit(ali, "100k", "USD")
    r = prop.risk(ali)
    assert r["room"]["try"] is None and "MTM yenile" in r["room"]["why"]                # (no K/Z today: no room)
    book.mtm(ali, "personal")
    r = prop.risk(ali)
    lim, pnl, stops = r["limit"], r["pnl"], r["stops"]
    assert (lim["amount"], lim["ccy"]) == (1e5, "USD") and _near(lim["try"], 1e5 * 41.9) and lim["usd"] == 1e5
    assert pnl["try"] < 0 and _near(stops["try"], 10e6 * (41.9 - 41.5))                 # (10m bought at 42: 41,9 now, stop 41,5)
    for k in ("try", "usd"):
        assert _near(r["room"][k], lim[k] - (-pnl[k]) - stops[k], 1e-12), (k, r["room"], lim, pnl, stops)
    # the market at the stop: today's loss holds what the stop held, nothing is left at the stop - the room (a TL limit)
    # is the same
    prop.set_limit(ali, "4mn", "TRY")
    before = prop.risk(ali)["room"]["try"]
    state["m"] = _market(D(2026, 11, 17), usdtry=41.5)
    book.mtm(ali, "personal")
    later = prop.risk(ali)
    assert later["stops"]["try"] == 0.0 and later["trades"][0]["state"] == "passed" and later["trades"][0]["beyond"]["try"] == 0.0
    assert _near(later["pnl"]["try"], r["pnl"]["try"] - 4e6, 1e-9) and _near(later["room"]["try"], before, 1e-9)
    store.close()


def test_the_scope_is_trades_own_tab(monkeypatch):
    """Kişisel: the viewer's own trades; Masa: the desk's; another trader's own never - the same tabs as Trades."""
    book, store, clock, prop, state = _desk(monkeypatch)
    ali, veli = _user(store, "Ali Veli"), _user(store, "Veli Can")
    fx = dict(BASE, product="fxspot", pair="USDTRY", side="B", price="42,5", stop="41")
    mine = book.add(ali, dict(fx, notional="1m"))["id"]
    desk = book.add(veli, dict(fx, scope="desk", notional="2m"))["id"]
    theirs = book.add(veli, dict(fx, notional="3m"))["id"]
    assert [t["id"] for t in prop.risk(ali)["trades"]] == [mine]                   # (Kişisel by default)
    assert [t["id"] for t in prop.risk(ali, "personal")["trades"]] == [mine]
    assert [t["id"] for t in prop.risk(ali, "desk")["trades"]] == [desk]
    assert [t["id"] for t in prop.risk(veli, "masa")["trades"]] == [desk]
    assert [t["id"] for t in prop.risk(veli, "kişisel")["trades"]] == [theirs]
    assert prop.risk(ali, "desk")["scope_text"] == "Masa" and _near(prop.risk(ali, "desk")["stops"]["try"], 2e6 * 1.0)
    with pytest.raises(ServiceError) as exc:
        prop.risk(ali, "herkes")
    assert exc.value.status == 400
    store.close()


# ---------------------------------------------------------------------------------------------- over HTTP (replay)
@pytest.fixture(scope="module")
def client(module_service):
    with TestClient(create_app(module_service)) as c:
        yield c


def test_every_route_needs_a_session(client):
    for method, path in (("GET", "/api/prop"), ("GET", "/api/prop/size?pair=USDTRY&stop=44&loss=1mn&ccy=TRY"),
                         ("GET", "/api/prop/risk"), ("GET", "/api/prop/limit"), ("POST", "/api/prop/limit")):
        res = client.request(method, path, headers=ANON, json={} if method == "POST" else None)
        assert res.status_code == 401, (method, path)
    assert client.get("/static/js/prop.js").status_code == 200


def test_the_panel_over_http(client, module_service):
    """The replay service: the worked example (entry typed), a bad input's 400 with the reason, the limit one's own, the
    risk of one's own tab after "MTM yenile"."""
    svc = module_service
    ali, veli = auth(svc, "Prop Ali"), auth(svc, "Prop Veli")
    opened = client.get("/api/prop", headers=ali).json()
    usdtry = tv.market(svc).spot("USDTRY")
    assert opened["pairs"][0]["pair"] == "USDTRY" and opened["pairs"][0]["mid"] == usdtry and opened["limit"] is None
    q = {"pair": "usdtry", "entry": "44,35", "stop": "44,55", "loss": "500k", "ccy": "TRY"}
    got = client.get("/api/prop/size", params=q, headers=ali).json()
    assert (got["direction"], got["size"], got["base"]) == ("short", 2e6, "USD")
    assert abs(got["real_loss"]["try"] - 4e5) < 1e-6 and abs(got["per_1m"]["try"] - 2e5) < 1e-6 and abs(got["real_loss"]["usd"] - 4e5 / usdtry) < 1e-6
    assert client.get("/api/prop/size", params=dict(q, entry=""), headers=ali).json()["entry"] == usdtry     # (no entry: the mid)
    # two-way: the size typed in place of the loss - the loss it makes at the stop; the old request reads as before
    two = client.get("/api/prop/size", params=dict(q, loss="", size="2,5m"), headers=ali).json()
    assert (two["anchor"], two["size"]) == ("size", 2.5e6) and abs(two["loss"] - 5e5) < 1e-6 and got["anchor"] == "loss"
    for bad, why in ((dict(q, stop=""), "Stop gerekli"), (dict(q, pair="1234"), "parite anlaşılamadı: 1234"),
                     (dict(q, pair="xyz"), "XYZTRY masanın FX listesinde yok"),          # (a currency alone: against TL)
                     (dict(q, pair="USDSGD"), "USDSGD masanın FX listesinde yok"), (dict(q, stop="44,35"), "stop girişe eşit olamaz"),
                     (dict(q, ccy="EUR"), "Kaybın dövizi TRY ya da USD olmalı"), (dict(q, loss="çok"), "Kayıp anlaşılamadı: çok")):
        res = client.get("/api/prop/size", params=bad, headers=ali)
        assert res.status_code == 400 and why in res.json()["error"], (bad, res.json())
    # the limit: one's own
    assert client.post("/api/prop/limit", json={"amount": "abc", "ccy": "TRY"}, headers=ali).status_code == 400
    assert client.post("/api/prop/limit", json={"amount": "2mn", "ccy": "TRY"}, headers=ali).json()["limit"]["amount"] == 2e6
    assert client.get("/api/prop/limit", headers=ali).json()["limit"]["amount"] == 2e6
    assert client.get("/api/prop/limit", headers=veli).json() == {"limit": None}
    # the risk of one's own tab: a stop, then "MTM yenile" - the K/Z and the room
    today = dt.date.today().isoformat()
    trade = {"scope": "personal", "product": "fxspot", "pair": "USDTRY", "trade_date": today, "settle_date": "+1", "side": "B",
             "notional": "1m", "price": "%.4f" % usdtry, "stop": "%.4f" % (usdtry - 0.25)}
    assert client.post("/api/trades", json=trade, headers=ali).status_code == 200
    r = client.get("/api/prop/risk", headers=ali).json()
    assert r["scope"] == "personal" and r["stops"]["count"] == 1 and abs(r["stops"]["try"] - 250000.0) < 1.0
    assert r["pnl"]["try"] is None and r["room"]["try"] is None
    assert client.post("/api/trades/mtm", json={"scope": "personal"}, headers=ali).status_code == 200
    r = client.get("/api/prop/risk", params={"scope": "personal"}, headers=ali).json()
    page = client.get("/api/trades", params={"scope": "personal"}, headers=ali).json()["mtm"]["totals"]["all"]
    assert r["pnl"]["try"] == page["day.pnl.try"] and r["room"]["try"] == pytest.approx(2e6 - max(0.0, -r["pnl"]["try"]) - r["stops"]["try"])
    assert client.get("/api/prop/risk", params={"scope": "desk"}, headers=veli).json()["trades"] == []       # (Ali's own: never Veli's)
    assert client.get("/api/prop/risk", params={"scope": "x"}, headers=ali).status_code == 400
