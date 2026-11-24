"""Trades · target and stop (tto/tradebook.py), their İzleme alarms (tto/watch.py) and "İşleme al" from a quant line with
the "Quant'tan" table (tto/tradequant.py).

The first part reads the book on a database of its own with the valuation planted (as tests/test_trades.py does): the
levels per product and unit, the distances and ``near``, the contract fields of the listing and of "MTM yenile", the
hits of a closed trade.  Then the replay service of this module (its own: the alarms are the service's): the alarms'
lifecycle - set, changed, cleared, closed, deleted, a restart -, private vs desk; "İşleme al" for the line kinds Trades
books (and one it does not); the "Quant'tan" table; the routes over HTTP."""
import datetime as dt
import math
import time

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, make_service
from tto import tradebook as tbm
from tto import tradequant as tq
from tto import tradevalue as tv
from tto.server import create_app
from tto.service import Service, ServiceError
from tto.store import Store

TODAY = "2026-11-17"


# ---------------------------------------------------------------------- the book alone, the valuation planted
class _Svc(object):
    require_user = Service.require_user
    require_admin = Service.require_admin

    def __init__(self, store):
        self.store = store
        self.started_at = time.time() - 86400

    def nudge(self):
        pass

    def saw(self, user):
        pass

    def holiday_dates(self, ccys):
        return frozenset()


def _book():
    store = Store(":memory:")
    book = tbm.TradeBook(_Svc(store))
    book.now = lambda: dt.datetime(2026, 11, 17, 10, 0)
    return book, store


def _user(store, name):
    return store.login(name)["user"]


class _Values(object):
    """tradevalue.value as the test plants it: trade id -> the number its levels read (``price_now``, a bond's yield in
    its convention, an option's premium now)."""

    def __init__(self):
        self.now = {}

    def __call__(self, trade, mkt, asof=None):
        x = self.now.get(trade.get("id"))
        if x is None:
            return {"ok": False, "why": "planlanmadı"}
        return {"ok": True, "why": None, "ccy": "TRY", "mtm": 0.0, "mtm_try": 0.0, "mtm_usd": 0.0, "carry_1d": 0.0,
                "carry_1d_try": 0.0, "carry_1d_usd": 0.0, "accrued": None, "price_now": x, "price_text": "",
                "inputs": {"yield_trade_now": x, "premium_now": x}}


@pytest.fixture()
def values(monkeypatch):
    v = _Values()
    monkeypatch.setattr(tv, "check", lambda trade, mkt=None, strict=True: dict(trade))
    monkeypatch.setattr(tv, "value", v)
    monkeypatch.setattr(tv, "market", lambda svc: "piyasa")
    monkeypatch.setattr(tv, "defaults", lambda product, pair=None, trade_date=None, mkt_or_svc=None, **given: {"trade_date": TODAY})
    monkeypatch.setattr(tv, "notional_for_dv01", lambda t, dv01, ccy="USD", mkt=None: {
        "notional": max(5e6, math.floor(float(dv01) * 1e4 / 5e6 + 0.5) * 5e6), "raw": float(dv01) * 1e4, "dv01_check": None})
    return v


def _ois(**kw):
    d = {"scope": "desk", "product": "ois", "structure": "outright", "trade_date": TODAY, "settle_date": "2026-11-18",
         "side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,50"}
    d.update(kw)
    return d


def _spread(**kw):
    d = _ois(structure="spread", end_date="", notional="", price="", legs=[
        {"side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,50"},
        {"side": "pay", "end_date": "5Y", "notional": "45m", "price": "38,15"}])
    d.update(kw)
    return d


def _dibs(isin, **kw):
    d = {"scope": "desk", "product": "dibs", "isin": isin, "trade_date": TODAY, "settle_date": "2026-11-18", "side": "B",
         "notional": "50m", "price": "98,75"}
    d.update(kw)
    return d


def _fxspot(**kw):
    d = {"scope": "desk", "product": "fxspot", "pair": "USDTRY", "trade_date": TODAY, "settle_date": "2026-11-18",
         "side": "B", "notional": "10m", "price": "42,15"}
    d.update(kw)
    return d


def _fxopt(**kw):
    d = {"scope": "desk", "product": "fxopt", "pair": "USDTRY", "trade_date": TODAY, "settle_date": "2026-11-18",
         "call_put": "call", "side": "B", "strike": "45", "expiry": "2026-12-17", "delivery": "2026-12-21",
         "notional": "10m", "price": "150k", "premium_ccy": "TRY"}
    d.update(kw)
    return d


def _isin():
    from tto import bonds as bd
    return bd.listed(dt.date(2026, 11, 17))[0]["isin"]


def _refused(fn, *args):
    with pytest.raises(ServiceError) as exc:
        fn(*args)
    return exc.value


def test_each_product_takes_its_levels_in_its_own_quote(values):
    book, store = _book()
    ali = _user(store, "Seviye Ali")
    isin = _isin()
    ids = {
        "ois": book.add(ali, _ois(target="%37,50", stop="39"))["id"],
        "spread": book.add(ali, _spread(target="-20", stop="-45,5"))["id"],
        "dibs_y": book.add(ali, _dibs(isin, price_kind="yield", price="38,10", target="37,60", stop="38,40"))["id"],
        "dibs_p": book.add(ali, _dibs(isin, target="99,50", stop="98,10"))["id"],
        "fxspot": book.add(ali, _fxspot(side="S", target="41,80", stop="42,40"))["id"],
        "fxopt": book.add(ali, _fxopt(target="300k", stop="75.000"))["id"],
        "plain": book.add(ali, _ois(side="pay"))["id"],
    }
    rows = {k: store.tb_get(v) for k, v in ids.items()}
    assert (rows["ois"]["target"], rows["ois"]["stop"]) == (37.5, 39.0)            # a rate: a "%" is taken
    assert (rows["spread"]["target"], rows["spread"]["stop"]) == (-20.0, -45.5)    # a package's level, bp
    assert (rows["dibs_y"]["target"], rows["dibs_p"]["target"]) == (37.6, 99.5)    # a bond: its yield, or its price
    assert (rows["fxspot"]["target"], rows["fxopt"]["target"], rows["fxopt"]["stop"]) == (41.8, 3e5, 75e3)
    assert "target" not in rows["plain"] and "stop" not in rows["plain"]
    # the unit each one's levels and distances are in (the form's labels, the rows' distances)
    spec = {k: tbm.level_spec(r) for k, r in rows.items()}
    assert [(spec[k]["what"], spec[k]["unit"]) for k in ("ois", "spread", "dibs_y", "dibs_p", "fxspot", "fxopt")] == [
        ("oran (%)", "bp"), ("seviye (bp)", "bp"), ("getiri (%)", "bp"), ("temiz fiyat", "puan"), ("kur", "pip"),
        ("prim tutarı (TRY)", "%")]
    # which way each one gains: a receive and a bond bought by its yield gain when the level falls
    assert [tbm.gains_up(rows[k]) for k in ("ois", "spread", "dibs_y", "dibs_p", "fxspot", "fxopt", "plain")] == [
        False, True, False, True, False, True, True]
    # a level's value never changes the trade's own: its close values stay its own (the fingerprint)
    bare = {k: v for k, v in rows["ois"].items() if k not in ("target", "stop")}
    assert tbm.fingerprint(rows["ois"]) == tbm.fingerprint(bare)


def test_the_target_must_be_on_the_side_the_trade_gains(values):
    book, store = _book()
    ali = _user(store, "Yön Ali")
    for raw in (_ois(target="39", stop="37,5"),                        # a receive gains as the rate falls
                _ois(side="pay", target="37,5", stop="39"),
                _fxspot(target="41", stop="43"),                      # bought: gains as the rate rises
                _spread(target="-50", stop="-20")):                    # the long leg paid: gains as the level rises
        res = book.check(ali, raw)
        assert not res["ok"] and "kâr tarafında" in res["fields"]["target"], raw
    assert book.check(ali, _ois(target="37,5"))["ok"] and book.check(ali, _ois(stop="39"))["ok"]
    res = book.check(ali, _fxspot(target="-1"))
    assert not res["ok"] and "target" in res["fields"]                   # (a price is positive)


def test_levels_change_clear_and_stay_with_an_edit_that_does_not_send_them(values):
    book, store = _book()
    ali = _user(store, "Değiştiren Ali")
    tid = book.add(ali, _ois(target="37,5", stop="39"))["id"]
    assert book.edit(ali, tid, _ois(target="37,25", stop="39"))["changed"]
    assert (store.tb_get(tid)["target"], store.tb_get(tid)["stop"]) == (37.25, 39.0)
    log = book.log(ali, tid)["entries"][-1]
    assert log["action"] == "edit" and ["target", 37.5, 37.25] in log["changes"]
    # a script that does not send them keeps them; an empty box clears it
    assert book.edit(ali, tid, _ois(notional="150m"))["changed"]
    assert (store.tb_get(tid)["target"], store.tb_get(tid)["stop"]) == (37.25, 39.0)
    assert book.edit(ali, tid, _ois(notional="150m", target="", stop="39"))["changed"]
    assert "target" not in store.tb_get(tid) and store.tb_get(tid)["stop"] == 39.0


def test_distance_to_target_and_stop_and_near_in_each_unit(values):
    book, store = _book()
    ali = _user(store, "Uzaklık Ali")
    isin = _isin()
    ois = book.add(ali, _ois(target="37,50", stop="39,50"))["id"]                    # receive @ 38,50
    spread = book.add(ali, _spread(target="-20", stop="-45"))["id"]                  # level -35, gains as it rises
    fx = book.add(ali, _fxspot(side="S", target="41,80", stop="42,40"))["id"]         # sold @ 42,15
    opt = book.add(ali, _fxopt(target="300k", stop="75k"))["id"]                     # bought @ 150k
    dy = book.add(ali, _dibs(isin, price_kind="yield", price="38,10", target="37,60", stop="38,40"))["id"]
    dp = book.add(ali, _dibs(isin, stop="98,25"))["id"]                              # one level: its distance from 98,75
    jpy = book.add(ali, _fxspot(pair="USDJPY", price="150", notional="1m", target="152", stop="149"))["id"]
    values.now.update({ois: 38.30, spread: -24.0, fx: 42.30, opt: 120000.0, dy: 37.70, dp: 98.35, jpy: 151.0})
    res = book.mtm(ali, "desk")
    lv = {tid: res["values"][str(tid)]["levels"] for tid in (ois, spread, fx, opt, dy, dp, jpy)}

    def near(a, b):
        return a is not None and abs(a - b) < 1e-6

    # a receive at 38,30: 80 bp to its target, 120 bp to its stop - the range is 200 bp, a quarter of it 50 bp
    assert lv[ois]["unit"] == "bp" and near(lv[ois]["to_target"], 80.0) and near(lv[ois]["to_stop"], 120.0) and lv[ois]["near"] is None
    assert (lv[ois]["target"], lv[ois]["stop"], lv[ois]["now"]) == (37.5, 39.5, 38.3)
    # the spread at -24 bp: 4 bp to its target (within a quarter of 25 bp)
    assert near(lv[spread]["to_target"], 4.0) and near(lv[spread]["to_stop"], 21.0) and lv[spread]["near"] == "target"
    # FX in pips: sold at 42,15, now 42,30 - 5.000 pips to the target, 1.000 to the stop (a quarter of 6.000: 1.500)
    assert lv[fx]["unit"] == "pip" and near(lv[fx]["to_target"], 5000.0) and near(lv[fx]["to_stop"], 1000.0) and lv[fx]["near"] == "stop"
    assert near(lv[jpy]["to_target"], 100.0) and near(lv[jpy]["to_stop"], 200.0)       # (a yen pair's pip: 0,01)
    # an option by its premium: worth 120k now - +150 % to 300k, 37,5 % down to 75k (45k of a 225k range: near it)
    assert lv[opt]["unit"] == "%" and near(lv[opt]["to_target"], 150.0) and near(lv[opt]["to_stop"], 37.5) and lv[opt]["near"] == "stop"
    # a bond by its yield (bought: gains as it falls) in bp; by its price in price points
    assert near(lv[dy]["to_target"], 10.0) and near(lv[dy]["to_stop"], 70.0) and lv[dy]["near"] == "target"
    # (its one level: a quarter of its distance from the price paid, 0,125)
    assert lv[dp]["unit"] == "puan" and lv[dp]["to_target"] is None and near(lv[dp]["to_stop"], 0.10) and lv[dp]["near"] == "stop"
    # the listing says the same until the next valuation; a level passed: ≤ 0 and "near" it
    listed = {it["id"]: it for it in book.listing(ali, "desk")["open"]}
    assert listed[ois]["levels"]["to_target"] == lv[ois]["to_target"] and "MTM" in listed[ois]["levels"]["at"]
    values.now[ois] = 37.40
    book.refresh_levels(force=True)
    again = {it["id"]: it for it in book.listing(ali, "desk")["open"]}[ois]["levels"]
    assert near(again["to_target"], -10.0) and again["near"] == "target" and "canlı" in again["at"]


def test_the_contract_fields_and_nothing_without_a_level(values):
    book, store = _book()
    ali = _user(store, "Sözleşme Ali")
    with_lv = book.add(ali, _ois(target="37,5"))["id"]
    bare = book.add(ali, _ois())["id"]
    values.now.update({with_lv: 38.0, bare: 38.0})
    listed = {it["id"]: it for it in book.listing(ali, "desk")["open"]}
    # (not valued yet: the levels, no distance)
    assert {k: listed[with_lv]["levels"][k] for k in ("target", "stop", "unit", "to_target", "to_stop", "near")} == {
        "target": 37.5, "stop": None, "unit": "bp", "to_target": None, "to_stop": None, "near": None}
    assert "levels" not in listed[bare]
    res = book.mtm(ali, "desk")
    assert set(res["values"][str(with_lv)]["levels"]) >= {"target", "stop", "unit", "to_target", "to_stop", "near"}
    assert "levels" not in res["values"][str(bare)] and res["values"][str(bare)]["level_now"] == 38.0
    assert abs(res["values"][str(with_lv)]["levels"]["to_target"] - 50.0) < 1e-9


def test_a_closed_trade_s_hit_by_its_close_price(values):
    book, store = _book()
    ali = _user(store, "Kapanış Ali")
    rows = []
    for close in ("37,50", "37,55", "39", "38,95", "38,10"):            # receive @ 38,50: target 37,50, stop 39
        tid = book.add(ali, _ois(target="37,5", stop="39"))["id"]
        book.close(ali, tid, TODAY, close)
        rows.append(store.tb_get(tid))
    # at / beyond a level, or within 5 % of the range short of it (7,5 bp here): at it
    assert [tbm.hit_of(r) for r in rows] == ["target", "target", "stop", "stop", "other"]
    closed = {it["id"]: it for it in book.listing(ali, "desk")["closed"]}
    assert closed[rows[0]["id"]]["levels"]["hit"] == "target" and closed[rows[4]["id"]]["levels"]["hit"] == "other"


# ---------------------------------------------------------------------- the replay service of this module
@pytest.fixture(scope="module")
def box(tmp_path_factory):
    """This module's own replay service (its alarms and trades are its own; the last test restarts it)."""
    d = tmp_path_factory.mktemp("levels")
    holder = {"svc": make_service(d), "dir": d}
    yield holder
    holder["svc"].stop()


def _key(svc, name, admin=False):
    key = svc.login(name)["user"]
    if admin:
        svc.store.update_account(key, role="admin")
    return key


def _now_of(svc, tid):
    """A trade's level now, as MTM reads it (the market now - never a literal: the sources may have moved)."""
    tb = svc.tradebook
    row = svc.store.tb_get(tid)
    return svc.et.call(lambda: tbm.level_now(row, tb._value(tb.for_value(row), tv.market(svc))))


def _trade_alarms(svc, tid=None):
    return [a for a in svc.watch.alarms() if a.get("trade") and (tid is None or a["trade"]["id"] == tid)]


def _ois_now(**kw):
    d = {"scope": "desk", "product": "ois", "structure": "outright", "side": "receive", "end_date": "2Y", "notional": "100m",
         "price": "38,50"}
    d.update(kw)
    return d


def _form(svc, user, raw):
    """A form with the dates the valuation's defaults give today."""
    d = svc.tradebook.defaults(user, raw["product"], raw.get("pair"), structure=raw.get("structure"))
    return dict(raw, trade_date=raw.get("trade_date") or d["trade_date"], settle_date=raw.get("settle_date") or d.get("settle_date"))


def test_a_desk_trade_s_levels_ring_for_everyone_and_follow_the_trade(box):
    svc = box["svc"]
    tb = svc.tradebook
    ayse, mehmet = _key(svc, "Hedef Ayşe"), _key(svc, "Hedef Mehmet")
    admin = _key(svc, "Hedef Yönetici", admin=True)
    tid = tb.add(ayse, _form(svc, ayse, _ois_now()))["id"]
    now = _now_of(svc, tid)
    assert now is not None and not _trade_alarms(svc, tid)                # (no level: no alarm)
    lo, hi = round(now - 0.50, 2), round(now + 0.50, 2)
    res = tb.edit(ayse, tid, _form(svc, ayse, _ois_now(target="%.2f" % lo, stop="%.2f" % hi)))
    assert res["changed"] and res["alarms"]["set"] == 2
    al = {a["trade"]["which"]: a for a in _trade_alarms(svc, tid)}
    # a receive: the target is reached from above, the stop from below; the desk's (everyone's), set by its creator
    assert (al["target"]["op"], al["target"]["level"], al["stop"]["op"], al["stop"]["level"]) == ("<=", lo, ">=", hi)
    assert all(a["user"] == "" and a["desk"] and a["by"] == ayse and a["subject"] == {"kind": "trade", "id": tid} for a in al.values())
    assert al["target"]["note"] == "hedefe geldi" and al["stop"]["note"] == "stopa geldi" and al["target"]["id"] == "tb%d-target" % tid
    assert {a["id"] for a in svc.watch.desk_list()} >= set(a["id"] for a in al.values())
    assert not [a for a in svc.watch.alarms(ayse) if a.get("trade")]
    # everyone sees them among the desk's alarms - with the level now and what is left to it
    rows = {a["id"]: a for a in svc.watch_view(mehmet)["desk"]["alarms"]}
    row = rows[al["target"]["id"]]
    assert row["now"] is not None and row["what"].startswith("Trades #%d" % tid) and abs(row["distance"] - (lo - row["now"]) * 100.0) < 1e-6
    # the listing's levels read the same value
    listed = {it["id"]: it for it in tb.listing(mehmet, "desk")["open"]}[tid]["levels"]
    assert listed["unit"] == "bp" and abs(listed["to_target"] - (listed["now"] - lo) * 100.0) < 1e-6
    # nothing rings in between; a target moved over the level now rings at the watch's next round, for everyone
    svc.et.call(svc.watch.tick)
    assert all(a["active"] for a in _trade_alarms(svc, tid))
    over = round(now + 0.10, 2)
    res = tb.edit(ayse, tid, _form(svc, ayse, _ois_now(target="%.2f" % over, stop="%.2f" % hi)))
    assert res["alarms"]["changed"] == 1
    svc.et.call(svc.watch.tick)                    # (the service's own watch loop may have rung it first: a change kicks it)
    rang = [e for e in svc.desk_alarms.log() if e.get("alarm") == "tb%d-target" % tid and e["kind"] == "fired"]
    assert len(rang) == 1 and rang[0]["note"] == "hedefe geldi" and rang[0]["label"].startswith("Trades #%d hedef" % tid)
    target = {a["trade"]["which"]: a for a in _trade_alarms(svc, tid)}["target"]
    assert not target["active"] and target["fired_value"] is not None
    # a level changed: armed again at it
    tb.edit(ayse, tid, _form(svc, ayse, _ois_now(target="%.2f" % lo, stop="%.2f" % hi)))
    al = {a["trade"]["which"]: a for a in _trade_alarms(svc, tid)}
    assert al["target"]["active"] and al["target"]["level"] == lo and al["target"]["fired_at"] is None
    # İzleme cannot remove them (an administrator neither): they are the trade's
    with pytest.raises(ServiceError) as exc:
        svc.desk_alarm_remove(admin, al["target"]["id"])
    assert "Trades" in str(exc.value) and len(_trade_alarms(svc, tid)) == 2
    # emptied: gone; closed: gone; opened again: back; deleted: gone
    tb.edit(ayse, tid, _form(svc, ayse, _ois_now(target="", stop="%.2f" % hi)))
    assert [a["trade"]["which"] for a in _trade_alarms(svc, tid)] == ["stop"]
    tb.close(ayse, tid, svc.store.tb_get(tid)["trade_date"], "%.2f" % now)
    assert not _trade_alarms(svc, tid)
    tb.reopen(ayse, tid)
    assert [a["trade"]["which"] for a in _trade_alarms(svc, tid)] == ["stop"]
    tb.remove(ayse, tid)
    assert not _trade_alarms(svc, tid)
    assert any(e.get("alarm") == "tb%d-stop" % tid and e["kind"] == "removed" for e in svc.desk_alarms.log())


def test_a_personal_trade_s_alarms_are_its_owner_s_only(box):
    svc = box["svc"]
    tb = svc.tradebook
    owner, other = _key(svc, "Kendi Seviye"), _key(svc, "Başka Seviye")
    raw = _form(svc, owner, {"scope": "personal", "product": "fxspot", "pair": "USDTRY", "side": "B", "notional": "10m", "price": "1"})
    tid = tb.add(owner, raw)["id"]
    spot = _now_of(svc, tid)
    assert spot
    # bought: the target above the spot, the stop below - set at the spot now, so that the stop rings at once
    tb.edit(owner, tid, dict(raw, target="%.4f" % (spot * 1.05), stop="%.4f" % (spot * 1.001)))
    al = {a["trade"]["which"]: a for a in _trade_alarms(svc, tid)}
    assert set(al) == {"target", "stop"} and all(a["user"] == owner and not a.get("desk") for a in al.values())
    assert (al["target"]["op"], al["stop"]["op"], al["target"]["show"]) == (">=", "<=", "fx")
    assert {a["id"] for a in svc.watch.alarms(owner)} >= {a["id"] for a in al.values()}
    desk_ids = {x["id"] for x in svc.watch.desk_list()}
    assert not [a for a in svc.watch.alarms(other) if a.get("trade")] and not desk_ids & set(x["id"] for x in al.values())
    assert not {x["id"] for x in svc.watch_view(other)["alarms"]} & set(x["id"] for x in al.values())
    svc.et.call(svc.watch.tick)                    # (or the service's own loop first)
    mine = [e for e in svc.alarms_fired(owner)["fired"] if e["id"] == al["stop"]["id"]]
    assert len(mine) == 1 and mine[0]["note"] == "stopa geldi" and mine[0]["user"] == owner
    assert al["stop"]["id"] not in [e["id"] for e in svc.alarms_fired(other)["fired"]]
    with pytest.raises(ServiceError):
        svc.alarm_remove(owner, al["stop"]["id"])
    # (another user does not even reach them: removing is nothing)
    assert svc.alarm_remove(other, al["stop"]["id"])["removed"] == 0 and len(_trade_alarms(svc, tid)) == 2


# ---------------------------------------------------------------------- "İşleme al": a quant line as the Trades form
def _market(svc):
    return svc.et.call(tv.market, svc)


def _par(svc, mkt, tenor):
    """The curve's rate now of a spot-starting TRY OIS to ``tenor`` (as the line's legs are read)."""
    tb = svc.tradebook
    d = tb.defaults(_key(svc, "Par Okur"), "ois", structure="outright")
    return tq._par(tb, mkt, tenor, d["trade_date"], d.get("value_date") or d.get("settle_date"))


def _leg(key, name, side, weight=1.0, dv01=1000.0):
    return {"key": key, "name": name, "weight": weight, "side": side, "action": "", "dv01_usd": dv01, "dv01": dv01 * 40.0, "notional": None}


def _lines(svc):
    """Quant lines as the list makes them (quantfam.make_signal), at the market's levels now."""
    mkt = _market(svc)
    r1, r2 = _par(svc, mkt, "1Y"), _par(svc, mkt, "2Y")
    bond = next(r for r in mkt.bonds.values() if r.get("where") == "DİBS RV" and r.get("kind") == "fixed" and r.get("compound"))
    y = bond["compound"] * 100.0
    spot = mkt.spot("USDTRY")
    base = {"family_label": "", "gated": "", "info": {}, "px": None, "expression": "", "group": ""}
    return {
        "ois": dict(base, id="trend:OIS:2Y", family="trend", family_label="Trend", asset="TRY OIS", instrument="2Y OIS", unit="%",
                    direction=-1, entry=r2, target=r2 - 0.40, stop=r2 + 0.20, legs=[_leg("OIS:2Y", "2Y OIS", -1)],
                    info={"universe": "OIS:2Y", "k": 1.0}),
        "spread": dict(base, id="sira:spread:OISS:1Y/2Y", family="sira", family_label="Carry + momentum", asset="TRY OIS",
                       instrument="1Y/2Y spread", unit="bp", direction=1, entry=(r2 - r1) * 100.0, target=(r2 - r1) * 100.0 + 25.0,
                       stop=(r2 - r1) * 100.0 - 10.0, legs=[_leg("OIS:2Y", "2Y OIS", 1), _leg("OIS:1Y", "1Y OIS", -1)],
                       info={"universe": "OISS:1Y/2Y"}),
        "dibs": dict(base, id="ml:DIBS:" + bond["isin"], family="ml", family_label="Makine öğrenmesi", asset="DİBS",
                     instrument="DİBS " + bond["isin"], unit="%", direction=-1, entry=y, target=y - 0.5, stop=y + 0.3,
                     legs=[_leg("DIBS:" + bond["isin"], bond["isin"], -1, dv01=2000.0)], info={"universe": "DIBS:" + bond["isin"]}),
        "fx": dict(base, id="optspot:FX:USDTRY", family="optspot", family_label="Opsiyon → spot", asset="FX", instrument="USDTRY spot",
                   unit="", direction=1, entry=0.1, target=0.5, stop=-0.2, legs=[_leg("FX:USDTRY", "USDTRY spot", 1)],
                   px={"pair": "USDTRY", "inst": "USDTRY spot", "digits": 4, "entry": spot, "target": spot * 1.02, "stop": spot * 0.99,
                       "unit": "TRY"}, info={"universe": "FX:USDTRY", "k": 2.0}, group="Offshore", tag="offshore limiti"),
        "vol": dict(base, id="ml:FXV:EURUSD", family="ml", asset="FX vol", instrument="EURUSD ATM 3A vol", unit="vol", direction=1,
                    entry=6.6, target=7.2, stop=6.1, legs=[_leg("FXV:EURUSD", "EURUSD ATM 3A vol", 1)]),
        "pca": dict(base, id="pca:OIS:18M", family="pca", asset="TRY OIS", instrument="18M OIS (PC1–PC2 hedge'li)", unit="bp",
                    direction=1, entry=-18.0, target=0.0, stop=-19.0,
                    legs=[_leg("OIS:18M", "18M OIS", 1), _leg("OIS:1Y", "1Y OIS", 1, 0.51), _leg("OIS:2Y", "2Y OIS", -1, 1.49)]),
        "fwd": dict(base, id="momentum:XR:EURTRY", family="momentum", asset="FX", instrument="EURTRY forward", unit="%", direction=-1,
                    entry=-9.6, target=-12.7, stop=-4.5, legs=[_leg("FX:EURTRY", "EURTRY forward", -1)],
                    px={"pair": "EURTRY", "inst": "EURTRY 1A forward", "digits": 4, "entry": 60.1, "target": 58.3, "stop": 63.3}),
        "off": dict(base, id="trend:OFF:3M", family="trend", asset="Offshore", instrument="Offshore 3M", unit="%", direction=1,
                    entry=35.8, target=None, stop=35.3, legs=[_leg("OFF:3M", "Offshore 3M", 1)]),
        # the FRA / PPK line: its level the gap to the path (bp), its legs the FRA's annuity-weighted OIS legs; told in the
        # FRA's rate (quantfam.inst_quote): entry the FRA now, target / stop the path's forward + their gaps
        "frapath": dict(base, id="frapath:3x6", family="frapath", family_label="FRA / PPK patikası", asset="TRY OIS",
                        instrument="3x6 FRA (PPK patikasına göre)", unit="bp", direction=-1, entry=6.9, target=0.1, stop=7.9,
                        legs=[_leg("OIS:6M", "6M OIS", -1, 2.1, 2100.0), _leg("OIS:3M", "3M OIS", 1, 1.1, 1100.0)],
                        quote={"inst": "3x6 FRA", "unit": "%", "digits": 2, "label": "3x6 FRA %", "fra": "3x6", "base": r1 - 0.30,
                               "scale": 0.01, "entry": r1 - 0.30 + 0.069, "target": r1 - 0.30 + 0.001, "stop": r1 - 0.30 + 0.079,
                               "gap": {"name": "patika farkı", "unit": "bp", "entry": 6.9, "target": 0.1, "stop": 7.9}}),
    }


@pytest.fixture()
def lines(box):
    """The quant list of the module's service, planted: the lines above (the list's own view put back afterwards)."""
    svc = box["svc"]
    ls = _lines(svc)
    keep = svc.quant._view
    svc.quant._view = {"list": list(ls.values()), "signals": list(ls.values()), "gated": []}
    yield ls
    svc.quant._view = keep


def test_which_lines_trades_can_book_and_every_line_says_so(lines):
    got = {k: tq.bookable(s) for k, s in lines.items()}
    assert {k: (ok, kind) for k, (ok, _, kind) in got.items()} == {
        "ois": (True, "outright"), "spread": (True, "spread"), "dibs": (True, "dibs"), "fx": (True, "fxspot"), "vol": (False, None),
        "pca": (False, None), "fwd": (False, None), "off": (False, None), "frapath": (True, "fra")}
    assert "vol" in got["vol"][1] and "PCA" in got["pca"][1] and "forward" in got["fwd"][1] and "offshore" in got["off"][1]
    # (the FRA / PPK line is its FRA by its quote; without one - no rate to book it at - its weighted legs are no Trades package)
    assert tq.bookable(dict(lines["frapath"], quote=None))[:2] == (False, "paket Trades'in spread (1:1) / fly (50/50) yapısında değil (PCA ya da "
                                                                      "hedge ağırlıklı): bacakları ayrı girin")
    assert tq.bookable(dict(lines["frapath"], quote=dict(lines["frapath"]["quote"], unit="bp")))[0] is False
    assert tq.bookable(dict(lines["ois"], legs=[_leg("MPC:2026-12-11", "PPK", 1)], unit="bp", quote={"unit": "%", "entry": 38.4}))[2] == "mpc"
    fly = dict(lines["spread"], unit="bp", legs=[_leg("OIS:1Y", "1Y", 1), _leg("OIS:6M", "6M", -1, 0.5), _leg("OIS:2Y", "2Y", -1, 0.5)])
    assert tq.bookable(fly)[2] == "fly"
    assert tq.bookable(dict(fly, legs=fly["legs"][:2] + [_leg("OIS:2Y", "2Y", 1, 0.5)]))[0] is False      # (wings on two sides)
    assert tq.bookable(dict(lines["ois"], legs=[_leg("MPC:2026-12-11", "PPK", 1)], info={"universe": "PPK:1"}))[2] == "mpc"
    assert tq.bookable(dict(lines["ois"], legs=[_leg("OIS:6M", "6M", 1), _leg("OIS:3M", "3M", -1)], info={"universe": "FRA:3x6"}))[2] == "fra"
    assert tq.bookable(dict(lines["ois"], id="corr:x", family="corr", unit="ρ"))[0] is False
    out = tq.mark({"signals": [lines["ois"], lines["vol"]], "gated": [lines["pca"]], "signal": dict(lines["fx"])})
    assert [s["book"]["ok"] for s in out["signals"] + out["gated"]] == [True, False, False] and out["signal"]["book"]["kind"] == "fxspot"


def test_an_ois_outright_line_fills_the_form_with_its_dv01_as_a_rounded_nominal(box, lines):
    svc = box["svc"]
    tb = svc.tradebook
    u = _key(svc, "Sinyal Alan")
    res = tq.prefill(svc, u, "trend:OIS:2Y")
    t, line = res["trade"], lines["ois"]
    assert res["ok"] and res["scope"] == "personal" and res["kind"] == "outright"                 # (personal unless chosen)
    assert (t["product"], t["structure"], tbm.rate_side(t["side"]), t["tenor"], t["sized_by"], t["dv01"]) == (
        "ois", "outright", "receive", "2Y", "dv01", 1000.0)
    assert t["price"] == round(line["entry"], 4) and (t["target"], t["stop"]) == (round(line["target"], 4), round(line["stop"], 4))
    # the nominal the form gives this DV01: on the desk's 5 mn lot
    form = dict(t, size=[{"leg": None, "dv01": 1000, "dv01_ccy": "USD"}])
    form.pop("notional")
    assert t["notional"] % 5e6 == 0 and t["notional"] == tb.size(u, form)["units"][0]["notional"]
    src = res["source"]
    assert (src["kind"], src["family"], src["line_id"], src["entry"], src["target"]) == (
        "quant", "trend", "trend:OIS:2Y", t["price"], t["target"]) and src["family_label"] == "Trend"
    assert res["text"].startswith("RECEIVE 2Y TRY OIS") and tq.prefill(svc, u, "trend:OIS:2Y", "desk")["scope"] == "desk"
    # saved as it came (the page sends the form back): the trade remembers its line, and its levels are its alarms
    tid = tb.add(u, dict(t, scope="personal", source=src))["id"]
    row = svc.store.tb_get(tid)
    assert row["source"]["line_id"] == "trend:OIS:2Y" and row["source"]["family"] == "trend"
    assert {a["trade"]["which"] for a in _trade_alarms(svc, tid)} == {"target", "stop"}
    # an edit never changes where it came from
    tb.edit(u, tid, dict(t, notional="150m", source={"kind": "quant", "family": "x", "line_id": "y"}))
    assert svc.store.tb_get(tid)["source"]["line_id"] == "trend:OIS:2Y"


def test_an_ois_spread_line_fills_both_legs_at_the_curve_and_the_package_at_the_entry(box, lines):
    svc = box["svc"]
    res = tq.prefill(svc, _key(svc, "Spread Alan"), "sira:spread:OISS:1Y/2Y")
    t, line = res["trade"], lines["spread"]
    assert res["ok"] and (t["structure"], [lg["tenor"] for lg in t["legs"]]) == ("spread", ["1Y", "2Y"])
    # steepener: receive the short leg, pay the long one - each sized by its DV01 (1.000 $) on the desk's lot
    assert [tbm.rate_side(lg["side"]) for lg in t["legs"]] == ["receive", "pay"] and tbm.package_side(t) == "steepener"
    assert all(lg["sized_by"] == "dv01" and lg["dv01"] == 1000.0 and lg["notional"] % 5e6 == 0 for lg in t["legs"])
    assert abs(t["price"] - line["entry"]) < 0.02                       # (the package at the line's entry, its legs to 4 decimals)
    assert abs(t["target"] - round(line["target"], 2)) < 1e-9 and abs(t["stop"] - round(line["stop"], 2)) < 1e-9
    assert tbm.gains_up(t) is True and tbm.level_spec(t)["unit"] == "bp"


def test_an_fra_path_line_fills_its_fra_at_the_fra_rate(box, lines):
    """The FRA / PPK patikası line (the desk, 24.11.2026: "6x9 net bir seviye değil mi"): booked as Trades' FRA - its
    "3x6", receive -, the price its FRA rate now, target and stop the FRA rates of its quote (the path's forward + the
    gap), never the gap in bp; its DV01 the package's (1.000 $)."""
    svc = box["svc"]
    res = tq.prefill(svc, _key(svc, "FRA Alan"), "frapath:3x6")
    t, q = res["trade"], lines["frapath"]["quote"]
    assert res["ok"] and res["kind"] == "fra" and (t["product"], t["structure"], t["fra"], tbm.rate_side(t["side"])) == ("ois", "fra", "3x6", "receive")
    assert t["price"] == round(q["entry"], 4) and (t["target"], t["stop"]) == (round(q["target"], 4), round(q["stop"], 4))
    assert t["sized_by"] == "dv01" and t["dv01"] == 1000.0 and t["notional"] % 5e6 == 0 and t["value_date"] < t["end_date"]
    src = res["source"]
    assert (src["entry"], src["target"], src["stop"], src["unit"], src["instrument"]) == (t["price"], t["target"], t["stop"], "%", "3x6 FRA")
    assert res["text"].startswith("RECEIVE 3x6 FRA") and tbm.level_spec(t)["unit"] == "bp"


def test_a_dibs_line_fills_the_bond_by_its_yield(box, lines):
    svc = box["svc"]
    res = tq.prefill(svc, _key(svc, "DİBS Alan"), lines["dibs"]["id"])
    t, line = res["trade"], lines["dibs"]
    assert res["ok"] and (t["product"], t["isin"], t["side"], t["price_kind"], t["yield_conv"]) == (
        "dibs", line["legs"][0]["key"][5:], "B", "yield", "bileşik")
    assert t["yield"] == round(line["entry"], 4) and (t["target"], t["stop"]) == (round(line["target"], 4), round(line["stop"], 4))
    assert t["sized_by"] == "dv01" and t["dv01"] == 2000.0 and t["notional"] > 0
    assert tbm.gains_up(t) is False and tbm.level_spec(t)["what"] == "getiri (%)"


def test_an_fx_spot_line_fills_the_pair_at_its_prices_and_a_line_without_a_button_is_refused(box, lines):
    svc = box["svc"]
    u = _key(svc, "FX Alan")
    res = tq.prefill(svc, u, "optspot:FX:USDTRY")
    t, px = res["trade"], lines["fx"]["px"]
    assert res["ok"] and (t["product"], t["pair"], t["side"], t["notional"], t["notional_ccy"]) == ("fxspot", "USDTRY", "B", 2e6, "USD")
    assert (t["price"], t["target"], t["stop"]) == (round(px["entry"], 4), round(px["target"], 4), round(px["stop"], 4))
    assert res["source"]["unit"] == "TRY" and res["source"]["entry"] == t["price"]
    for lid in ("ml:FXV:EURUSD", "pca:OIS:18M", "trend:OFF:3M"):
        with pytest.raises(ServiceError) as exc:
            tq.prefill(svc, u, lid)
        assert "alınamaz" in str(exc.value)
    with pytest.raises(ServiceError) as exc:
        tq.prefill(svc, u, "yok:boyle:bir")
    assert exc.value.status == 404


def test_the_quant_table_counts_per_family_what_the_user_sees(box, lines):
    svc = box["svc"]
    tb = svc.tradebook
    ali, veli = _key(svc, "Tablo Ali"), _key(svc, "Tablo Veli")

    def take(user, lid, scope):
        res = tq.prefill(svc, user, lid, scope)
        return tb.add(user, dict(res["trade"], scope=scope, source=res["source"]))["id"]

    desk = take(ali, "trend:OIS:2Y", "desk")
    own = take(ali, "optspot:FX:USDTRY", "personal")
    other = take(veli, "trend:OIS:2Y", "personal")               # (Veli's own: never in Ali's table)
    lost = take(ali, "optspot:FX:USDTRY", "personal")
    px = lines["fx"]["px"]
    tb.close(ali, own, svc.store.tb_get(own)["trade_date"], "%.4f" % px["target"])
    tb.close(ali, lost, svc.store.tb_get(lost)["trade_date"], "%.4f" % px["stop"])
    plain = tb.add(ali, _form(svc, ali, _ois_now()))["id"]       # (not from a line: not in the table)
    got = tq.table(tb, ali)
    fam = {f["family"]: f for f in got["families"]}
    assert desk in got["ids"] and own in got["ids"] and other not in got["ids"] and plain not in got["ids"]
    tr = fam["trend"]
    assert (tr["label"], tr["count"], tr["desk"], tr["personal"], tr["open"], tr["closed"], tr["closed"]) == ("Trend", 1, 1, 0, 1, 0, 0)
    op = fam["optspot"]
    assert (op["count"], op["personal"], op["open"], op["closed"], op["target"], op["stop"], op["other"]) == (2, 2, 0, 2, 1, 1, 0)
    assert op["hit_rate"] == 0.5 and op["known"] == 2 and op["avg_try"] == op["pnl_try"] / 2
    assert got["all"]["count"] == sum(f["count"] for f in got["families"]) and "Tablo Veli" not in str(got)
    # Veli sees his own and the desk's
    vf = {f["family"]: f for f in tq.table(tb, veli)["families"]}
    assert vf["trend"]["personal"] == 1 and "optspot" not in vf


def test_a_restart_keeps_one_alarm_per_level_and_drops_what_has_no_trade(box):
    svc = box["svc"]
    tb = svc.tradebook
    u = _key(svc, "Yeniden Başlayan")
    tid = tb.add(u, _form(svc, u, _ois_now(scope="personal", target="30", stop="45")))["id"]
    before = _trade_alarms(svc)
    assert len({a["id"] for a in before}) == len(before) and {a["id"] for a in _trade_alarms(svc, tid)} == {
        "tb%d-target" % tid, "tb%d-stop" % tid}
    # a copy of one (as a database restored over another would leave) and one of a trade that is gone
    extra = [dict(_trade_alarms(svc, tid)[0]), dict(_trade_alarms(svc, tid)[0], id="tb999999-target", trade={"id": 999999, "which": "target"},
                                                    subject={"kind": "trade", "id": 999999})]
    svc.watch._put_alarms(svc.watch.alarms() + extra)
    svc.stop()
    box["svc"] = svc = make_service(box["dir"])
    after = _trade_alarms(svc)
    assert sorted(a["id"] for a in after) == sorted(a["id"] for a in before)
    assert svc.store.tb_get(tid)["target"] == 30.0


def test_the_routes_over_http(box, lines):
    """(last: leaving the TestClient stops the module's service)"""
    svc = box["svc"]
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Http Sinyal")
        assert c.get("/api/trades/from-quant", params={"id": "trend:OIS:2Y"}, headers=ANON).status_code == 401
        r = c.get("/api/trades/from-quant", params={"id": "trend:OIS:2Y", "scope": "desk"}, headers=h)
        assert r.status_code == 200 and r.json()["scope"] == "desk" and r.json()["trade"]["tenor"] == "2Y"
        r = c.get("/api/trades/from-quant", params={"id": "ml:FXV:EURUSD"}, headers=h)
        assert r.status_code == 400 and "vol" in r.json()["error"]
        res = c.get("/api/trades/from-quant", params={"id": "optspot:FX:USDTRY"}, headers=h).json()
        saved = c.post("/api/trades", json=dict(res["trade"], scope="personal", source=res["source"]), headers=h)
        assert saved.status_code == 200 and saved.json()["alarms"]["set"] == 2
        listed = c.get("/api/trades", params={"scope": "personal"}, headers=h).json()["open"]
        it = next(x for x in listed if x["id"] == saved.json()["id"])
        assert it["source"]["family"] == "optspot" and set(it["levels"]) >= {"target", "stop", "unit", "to_target", "to_stop", "near"}
        assert it["levels"]["unit"] == "pip"
        q = c.get("/api/trades/quant", headers=h)
        assert q.status_code == 200 and {f["family"] for f in q.json()["families"]} >= {"optspot"}
        # the alarm of a trade's level cannot be removed from İzleme
        aid = "tb%d-target" % saved.json()["id"]
        r = c.post("/api/alarms/remove", json={"id": aid}, headers=h)
        assert r.status_code == 400 and "Trades" in r.json()["error"]
