"""Bugün (tto/bugun.py, ``GET /api/bugun``): the morning screen's blocks with planted data - the RET (loaded today or not,
the fair value's updates), the open trades (the last MTM's P&L, the ``levels`` contract absent and present, another
trader's own trades never), the quant's new AL / SAT lines (since the previous close, "YENİ", best expectancy first),
the DİBS bonds whose signal turned (against the desk's close record - taken once a business day at the close - and the
zero-coupon curve's history), the chat's trades not entered, the agenda and the meetings; each block's "nothing", a block
that fails, and the route.  A service of the module's own: the blocks read shared state the other files change."""
import datetime as dt
import types

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, make_service
from tto import bugun as bg
from tto import tradevalue as tv
from tto.server import create_app
from tto.service import ServiceError

TODAY = dt.date.today()


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("bugun"))
    yield s
    s.stop()


def login(svc, name):
    return svc.login(name)["user"]


def at(day, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m))


def business_before(svc, day):
    d = day - dt.timedelta(days=1)
    while not svc.bugun.business(d):
        d -= dt.timedelta(days=1)
    return d


# ---------------------------------------------------------------------------------------------- the page and "nothing"
def test_the_page_is_in_the_masa_group_right_under_masa(svc):
    pages = svc.nav()
    masa = [p["id"] for p in pages if p.get("group") == "Masa"]
    assert masa[:2] == ["masa", "bugun"]
    page = next(p for p in pages if p["id"] == "bugun")
    assert (page["title"], page["custom"], page["book"]) == ("Bugün", True, None)


def test_each_block_says_nothing_plainly_when_there_is_nothing(svc, monkeypatch):
    u = login(svc, "Bugün Boş")
    monkeypatch.setattr(svc.retfair, "summary", lambda: {"updates": [], "at": "08:59:00"})
    monkeypatch.setattr(svc.history, "archive", lambda: [])
    v = svc.bugun.view(u)
    assert v["today"] == TODAY.isoformat() and v["close"] == "17:30"
    ret = v["ret"]
    # the RET as the header's yellow dot says it: not loaded today (never here) - the manual tab
    assert ret["available"] and not ret["loaded"] and ret["at"] is None and ret["updates"] == [] and ret["tab"] == "manual"
    t = v["trades"]
    assert t["count"] == 0 and t["rows"] == [] and t["near"] == [] and not t["levels"]
    assert t["tabs"]["personal"]["mtm_at"] is None and t["tabs"]["desk"]["mtm_at"] is None
    assert v["quant"] == {"available": True, "ready": False, "why": "quant sonucu henüz yok (ilk hesap sürüyor)"}
    assert v["chat"]["count"] == 0 and v["chat"]["items"] == []
    a = v["agenda"]
    assert a["items"] == [] and a["late"] == [] and a["count"] == 0
    assert a["meetings"]["ppk"]["known"] and a["meetings"]["ppk"]["next"] > TODAY.isoformat()
    d = v["dibs"]
    # no close record of DİBS RV's signals yet: today's state, "dünle kıyas yok"; the first record at the close
    assert d["available"] and not d["compared"] and d["prev_day"] is None and d["turned"] == [] and d["first_record"] == "17:30"
    assert d["now"] and all(r["signal"] and not r["ois"]["known"] and not r["fx"]["known"] for r in d["now"])
    assert d["zero_why"] == "quant sonucu henüz yok" and d["threshold"] == 5.0


# ---------------------------------------------------------------------------------------------- RET
def test_ret_loaded_today_by_whom_and_the_fair_values_updates(svc, monkeypatch):
    u = login(svc, "Bugün RET")
    svc.set_ret(u, [{"tenor": "1M", "bid": "40,00", "ask": "40,20"}])
    monkeypatch.setattr(svc.retfair, "summary", lambda: {"updates": [], "at": "09:00:00"})
    r = svc.bugun.view(u)["ret"]
    assert r["loaded"] and r["at"][:10] == TODAY.isoformat() and r["by"] == "Bugün RET" and r["tab"] is None
    monkeypatch.setattr(svc.retfair, "summary", lambda: {"updates": ["1M", "2M"], "at": "09:01:10"})
    r = svc.bugun.view(u)["ret"]
    assert r["updates"] == ["1M", "2M"] and r["checked"] == "09:01:10" and r["tab"] == "fair"
    # a load of another day: not today's (the dot's rule)
    monkeypatch.setattr(svc, "ret_meta", lambda: {"updated_at": "2026-01-02 17:40:00", "updated_by": u})
    r = svc.bugun.view(u)["ret"]
    assert not r["loaded"] and r["at"] == "2026-01-02 17:40:00" and r["tab"] == "fair"


# ---------------------------------------------------------------------------------------------- Trades
def _val(mtm):
    return {"ok": True, "why": None, "ccy": "TRY", "mtm": mtm, "mtm_try": mtm, "mtm_usd": mtm / 40.0, "carry_1d": 10.0,
            "carry_1d_try": 10.0, "carry_1d_usd": 0.25, "accrued": None, "price_now": 38.0, "price_text": "%38,00", "greeks": None,
            "inputs": {}}


def _ois(**kw):
    d = {"scope": "desk", "product": "ois", "structure": "outright", "trade_date": TODAY.isoformat(),
         "settle_date": (TODAY + dt.timedelta(days=1)).isoformat(), "side": "receive", "end_date": "2Y", "notional": "100m", "price": "38,50"}
    d.update(kw)
    return d


@pytest.fixture()
def valuation(monkeypatch):
    """tradevalue as the test plants it: each trade's MTM by its note."""
    values = {}
    monkeypatch.setattr(tv, "check", lambda trade, mkt=None, strict=True: dict(trade))
    monkeypatch.setattr(tv, "defaults", lambda product, pair=None, trade_date=None, mkt_or_svc=None, **given: {})
    monkeypatch.setattr(tv, "market", lambda s: "piyasa")
    monkeypatch.setattr(tv, "value", lambda trade, mkt, asof=None: dict(values[trade.get("note")]) if trade.get("note") in values
                        else {"ok": False, "why": "planlanmadı"})
    return values


def test_open_trades_with_the_last_mtms_p_and_l_and_nobody_elses_own(svc, valuation):
    ali, veli = login(svc, "Bugün Ali"), login(svc, "Bugün Veli")
    book = svc.tradebook
    desk = book.add(ali, _ois(note="masa-1"))["id"]
    mine = book.add(ali, _ois(scope="personal", note="ali-1", end_date="1Y"))["id"]
    theirs = book.add(veli, _ois(scope="personal", note="veli-1", end_date="5Y"))["id"]
    valuation.update({"masa-1": _val(1500.0), "ali-1": _val(-400.0), "veli-1": _val(99999.0)})
    # before any "MTM yenile": the trades, no P&L (nothing is valued by the page)
    t = svc.bugun.view(ali)["trades"]
    ids = [r["id"] for r in t["rows"]]
    assert ids == [mine, desk] and theirs not in ids and all(r["day"] is None and r["why"] is None for r in t["rows"])
    assert t["tabs"]["personal"]["open"] == 1 and t["tabs"]["desk"]["open"] >= 1
    book.mtm(ali, "desk")
    book.mtm(ali, "personal")
    later = book.add(ali, _ois(note="masa-2"))["id"]                # entered after the MTM: said so, the tab stale
    t = svc.bugun.view(ali)["trades"]
    rows = {r["id"]: r for r in t["rows"]}
    assert set(rows) == {mine, desk, later}
    assert (rows[desk]["day"], rows[desk]["total"], rows[desk]["who"], rows[desk]["scope"]) == (1500.0, 1500.0, "Bugün Ali", "desk")
    assert (rows[mine]["day"], rows[mine]["total"], rows[mine]["who"], rows[mine]["scope"]) == (-400.0, -400.0, None, "personal")
    assert rows[later]["day"] is None and rows[later]["why"] == "son MTM'den sonra girildi"
    assert t["tabs"]["desk"]["stale"] and t["tabs"]["desk"]["mtm_by"] == "Bugün Ali" and t["tabs"]["desk"]["day"] == {"try": 1500.0, "missing": 1}
    assert t["tabs"]["personal"]["total"] == {"try": -400.0, "missing": 0}
    # Veli: the desk's trades and his own - never Ali's own; his own tab has no MTM of his
    t2 = svc.bugun.view(veli)["trades"]
    ids2 = [r["id"] for r in t2["rows"]]
    assert theirs in ids2 and desk in ids2 and mine not in ids2
    assert t2["tabs"]["personal"]["mtm_at"] is None and next(r for r in t2["rows"] if r["id"] == theirs)["day"] is None
    assert not any(r["levels"] for r in t2["rows"]) and t2["near"] == [] and not t2["levels"]       # (the contract absent)
    for user, closed in ((ali, mine), (ali, desk), (ali, later), (veli, theirs)):
        book.remove(user, closed)


def test_the_trades_levels_contract_near_target_and_stop(svc, valuation, monkeypatch):
    """``/api/trades`` may carry each open trade's ``levels`` (another branch adds them): read as they come, the ones near
    their target / stop listed (a stop first); a trade without them, or with what cannot be read, says nothing of it."""
    u = login(svc, "Bugün Hedef")
    book = svc.tradebook
    a = book.add(u, _ois(scope="personal", note="h-1"))["id"]
    b = book.add(u, _ois(scope="personal", note="h-2"))["id"]
    c = book.add(u, _ois(scope="personal", note="h-3"))["id"]
    d = book.add(u, _ois(scope="personal", note="h-4"))["id"]
    planted = {a: {"target": 37.5, "stop": 39.0, "unit": "%", "to_target": 0.12, "to_stop": 1.38, "near": "target"},
               b: {"target": 37.0, "stop": 38.75, "unit": "%", "to_target": 1.5, "to_stop": 0.04, "near": "stop"},
               c: {"target": 36.0, "stop": 40.0, "unit": "%", "to_target": 2.5, "to_stop": 1.5, "near": None},
               d: "bozuk"}
    real = book.listing

    def listing(user, scope="desk"):
        got = real(user, scope)
        for it in got["open"]:
            if it["id"] in planted:
                it["levels"] = planted[it["id"]]
        return got

    monkeypatch.setattr(book, "listing", listing)
    t = svc.bugun.view(u)["trades"]
    rows = {r["id"]: r for r in t["rows"]}
    assert t["levels"] and [r["id"] for r in t["near"]] == [b, a]
    assert rows[b]["levels"] == {"target": 37.0, "stop": 38.75, "to_target": 1.5, "to_stop": 0.04, "unit": "%", "near": "stop"}
    assert rows[c]["levels"]["near"] is None and rows[d]["levels"] is None
    assert bg.levels_of({"near": "elsewhere"}) is None and bg.levels_of(None) is None
    assert bg.levels_of({"target": float("nan"), "stop": 1.0, "near": "stop", "unit": "bp"})["target"] is None
    for tid in (a, b, c, d):
        book.remove(u, tid)


# ---------------------------------------------------------------------------------------------- quant
def _sig(sid, direction, exp_try, **kw):
    s = {"id": sid, "family": "pca", "family_label": "PCA / RV", "asset": "TRY OIS", "direction": direction, "expression": "expr " + sid,
         "trade_tr": "trade " + sid, "entry": 38.5, "target": 38.0, "stop": 38.9, "digits": 2, "unit": "%", "rr": 1.25,
         "exp_try": exp_try, "strength": "Güçlü", "gated": "", "page": "quant-pca", "time": "09:30", "day": "2026-11-17",
         "legs": [{"action": "Receive" if direction < 0 else "Pay", "name": "2Y OIS"}], "money": {"per_bp": 25000.0, "dv01_usd": 10000.0},
         "info": {}}
    s.update(kw)
    return s


def _entry(sid, day, time, status="open", **kw):
    e = {"seq": 1, "sid": sid, "family": "pca", "family_label": "PCA / RV", "asset": "TRY OIS", "expression": "expr " + sid, "dir": -1,
         "level": 38.5, "target": 38.0, "stop": 38.75, "unit": "%", "digits": 2, "strength": "Orta", "day": day, "time": time, "status": status}
    e.update(kw)
    return e


def test_the_quants_new_al_sat_lines_since_the_previous_close_best_expectancy_first(svc, monkeypatch):
    u = login(svc, "Bugün Quant")
    q = svc.quant
    day = dt.date(2026, 11, 17)                                     # a Tuesday: the close before it is Monday's 17:30
    fx = _sig("fx:usd", 1, 52000.0, px={"label": "USDTRY 1A fwd", "entry": 43.1234, "target": 43.6, "stop": 42.9, "digits": 4},
              money={"base": "USD", "ccy": "TRY", "total": 1.3e6, "target": 476600.0, "stop": -223400.0}, rr=None, legs=[], info={})
    live = [_sig("pca:2y", -1, 120000.0), fx, _sig("trend:eur", 1, None, new=True, line="AL EURUSD spot · 1 mn EUR", legs=[]),
            _sig("old:5y", -1, 999999.0)]
    gated = [_sig("held:1y", -1, 80000.0, gated="rejim uyumsuz")]
    monkeypatch.setattr(q, "_view", {"today": day.isoformat(), "at": "2026-11-17 09:31:02", "signals": live, "gated": gated, "list": live + gated})
    log = [_entry("pca:2y", "2026-11-17", "09:10"), _entry("fx:usd", "2026-11-16", "18:05"),        # after Monday's close: new
           _entry("old:5y", "2026-11-16", "10:00"),                                                  # before it: not new
           _entry("held:1y", "2026-11-17", "08:45"), _entry("gone:3y", "2026-11-17", "09:20", level=38.0, target=37.5, stop=38.25),
           _entry("shut:7y", "2026-11-17", "09:00", status="hedef")]
    svc.store.put(q.LOG_KEY, log)
    try:
        got = svc.bugun.view(u)["quant"]
    finally:
        svc.store.put(q.LOG_KEY, [])
    assert got["ready"] and got["day"] == "2026-11-17" and got["since"] == "2026-11-16 17:30" and got["count"] == 5
    # by the expected P&L in TRY at the line's own size; the ones without it last
    assert [x["sid"] for x in got["lines"]] == ["pca:2y", "held:1y", "fx:usd", "gone:3y", "trend:eur"]
    f = got["lines"][2]
    # an FX line: its instrument's own prices, AL, 1 mn of its base, R/R from what the target and the stop make
    assert (f["side"], f["size"], f["entry"], f["target"], f["stop"], f["digits"], f["unit"]) == ("AL", "1 mn USD", 43.1234, 43.6, 42.9, 4, "USDTRY 1A fwd")
    assert f["rr"] == pytest.approx(476600.0 / 223400.0) and f["time"] == "18:05" and f["day"] == "2026-11-16" and f["listed"]
    p = got["lines"][0]
    assert (p["side"], p["size"], p["trade"], p["rr"], p["exp_try"], p["page"]) == ("RECEIVE", "DV01 10.000 $", "trade pca:2y", 1.25, 120000.0, "quant-pca")
    assert got["lines"][1]["gated"] == "rejim uyumsuz"
    g = got["lines"][3]                                            # written down since, out of the list now: the log's own
    assert not g["listed"] and g["side"] == "SAT" and g["rr"] == pytest.approx(2.0) and g["exp_try"] is None
    tr = got["lines"][4]                                           # a daily line turned since the close ("YENİ")
    assert tr["new"] and tr["trade"] == "AL EURUSD spot · 1 mn EUR" and tr["side"] == "AL"
    # nothing new: said so; more than the page shows: how many more
    monkeypatch.setattr(q, "_view", {"today": day.isoformat(), "at": None, "signals": [_sig("old:5y", -1, 1.0)], "gated": [], "list": []})
    assert svc.bugun.view(u)["quant"]["count"] == 0
    many = [_sig("n%d" % i, 1, float(i), new=True) for i in range(bg.QUANT_TOP + 3)]
    monkeypatch.setattr(q, "_view", {"today": day.isoformat(), "at": None, "signals": many, "gated": [], "list": many})
    got = svc.bugun.view(u)["quant"]
    assert got["count"] == bg.QUANT_TOP + 3 and got["more"] == 3 and len(got["lines"]) == bg.QUANT_TOP
    assert got["lines"][0]["sid"] == "n%d" % (bg.QUANT_TOP + 2)


FRA_QUOTE = {"inst": "6x9 FRA", "unit": "%", "digits": 3, "label": "6x9 FRA %", "fra": "6x9", "base": 38.65, "scale": 0.01,
             "entry": 38.719, "target": 38.651, "stop": 38.729, "gap": {"name": "patika farkı", "unit": "bp", "digits": 1, "of": "patikanın",
                                                                       "at": "patikada", "entry": 6.9, "target": 0.1, "stop": 7.9}}


def test_a_model_level_line_says_its_instruments_levels_the_gap_beside_them(svc, monkeypatch):
    """The FRA / PPK line (the desk, 24.11.2026: "6x9 net bir seviye değil mi"): entry / target / stop in the FRA's rate,
    the unit its instrument, the gap to the path in the note - live, and as the log kept it once the line left the list."""
    u = login(svc, "Bugün FRA")
    q = svc.quant
    day = dt.date(2026, 11, 17)
    fra = _sig("frapath:6x9", -1, 343000.0, entry=6.9, target=0.1, stop=7.9, unit="bp", digits=1, quote=FRA_QUOTE)
    monkeypatch.setattr(q, "_view", {"today": day.isoformat(), "at": "2026-11-17 09:31:02", "signals": [fra], "gated": [], "list": [fra]})
    log = [_entry("frapath:6x9", "2026-11-17", "09:10", level=6.9, target=0.1, stop=7.9, unit="bp", digits=1, quote=FRA_QUOTE),
           _entry("frapath:3x6", "2026-11-17", "09:15", level=-7.0, target=-0.5, stop=-8.2, unit="bp", digits=1,
                  quote=dict(FRA_QUOTE, inst="3x6 FRA", label="3x6 FRA %", entry=38.10, target=38.165, stop=38.088,
                             gap=dict(FRA_QUOTE["gap"], entry=-7.0, target=-0.5, stop=-8.2)))]
    svc.store.put(q.LOG_KEY, log)
    try:
        got = svc.bugun.view(u)["quant"]
    finally:
        svc.store.put(q.LOG_KEY, [])
    by = {x["sid"]: x for x in got["lines"]}
    live, gone = by["frapath:6x9"], by["frapath:3x6"]
    assert (live["entry"], live["target"], live["stop"], live["digits"], live["unit"]) == (38.719, 38.651, 38.729, 3, "6x9 FRA %")
    assert live["note"] == "patika farkı +6,9 / +0,1 / +7,9 bp" and live["side"] == "RECEIVE" and live["listed"]
    assert (gone["entry"], gone["target"], gone["stop"], gone["unit"], gone["listed"]) == (38.10, 38.165, 38.088, "3x6 FRA %", False)
    assert gone["note"] == "patika farkı -7,0 / -0,5 / -8,2 bp" and gone["rr"] == pytest.approx(0.065 / 0.012)


# ---------------------------------------------------------------------------------------------- DİBS
def test_the_close_record_is_taken_once_a_business_day_at_the_desks_close(svc):
    b = svc.bugun
    svc.store.put(bg.DIBS_KEY, {})
    b._recorded = None
    day = business_before(svc, TODAY)
    assert b.look(at(day, "17:29")) is None and b.closes() == {}                        # before the close: nothing
    rec = b.look(at(day, "17:31"))
    assert rec["at"] == "17:31" and rec["threshold"] == 5.0 and len(rec["bonds"]) >= 10
    first = next(iter(rec["bonds"].values()))
    assert set(first) == {"ois", "ois_v", "fx", "fx_v"} and first["ois"] in ("UCUZ", "PAHALI", "")
    assert b.look(at(day, "18:10")) is None and list(b.closes()) == [day.isoformat()]     # once a day
    b._recorded = None
    assert b.look(at(day, "19:00")) is None                                            # (kept: found, not taken again)
    sat = day + dt.timedelta(days=(5 - day.weekday()) % 7 or 7)
    assert sat.weekday() == 5 and b.look(at(sat, "18:00")) is None and sat.isoformat() not in b.closes()
    svc.store.put(bg.DIBS_KEY, {})
    b._recorded = None


def test_the_dibs_bonds_whose_signal_turned_against_the_close_and_the_zero_curve(svc, monkeypatch):
    u = login(svc, "Bugün DİBS")
    b = svc.bugun
    prev = business_before(svc, TODAY)
    svc.store.put(bg.DIBS_KEY, {})
    b._recorded = None
    rec = b.look(at(prev, "17:45"))
    isins = list(rec["bonds"])
    flip, zero_isin = isins[0], isins[1]
    # the record as it was at the close: the first bond's OIS signal another one then
    closes = b.closes()
    was = closes[prev.isoformat()]["bonds"][flip]
    now_ois = was["ois"]
    was["ois"] = "PAHALI" if now_ois != "PAHALI" else "UCUZ"
    svc.store.put(bg.DIBS_KEY, closes)
    # the zero-coupon curve: 2 bp at the last close (inside the 5 bp threshold), 7,5 bp now (cheap)
    mon = types.SimpleNamespace(days=["2026-11-13", "2026-11-16", "2026-11-17"], values=[1.0, 2.0, 9.0], level=7.5)
    monkeypatch.setattr(svc.quant, "_fit", {"today": "2026-11-17", "mons": {"dibsfv:" + zero_isin: mon}})
    d = b.view(u)["dibs"]
    assert d["compared"] and d["prev_day"] == prev.isoformat() and d["now"] == [] and d["z_prev_day"] == "2026-11-16"
    turned = {r["isin"]: r for r in d["turned"]}
    assert set(turned) == {flip, zero_isin}
    f = turned[flip]
    assert f["turned"] == ["ois"] and f["ois"]["prev"] == was["ois"] and f["ois"]["now"] == now_ois and f["ois"]["known"]
    z = turned[zero_isin]["z"]
    assert "z" in turned[zero_isin]["turned"] and (z["prev"], z["now"], z["prev_v"], z["v"], z["known"]) == ("", "UCUZ", 2.0, 7.5, True)
    assert turned[flip]["label"] and turned[flip]["label"] != flip                    # (the desk's name of the bond)
    # nothing turned since the close: said so
    svc.store.put(bg.DIBS_KEY, {prev.isoformat(): dict(rec)})
    monkeypatch.setattr(svc.quant, "_fit", None)
    d = b.view(u)["dibs"]
    assert d["compared"] and d["turned"] == [] and d["now"] == []
    svc.store.put(bg.DIBS_KEY, {})
    assert bg.zero_state(5.1, 5.0) == "UCUZ" and bg.zero_state(-5.1, 5.0) == "PAHALI" and bg.zero_state(4.9, 5.0) == ""
    assert bg.zero_state(None, 5.0) is None and bg.zero_state(3.0, None) is None


# ---------------------------------------------------------------------------------------------- the desk
def test_the_chats_trades_not_entered(svc):
    u = login(svc, "Bugün Chat")
    svc.broker_add(u, "7y ois trades 33.10", None, "", True, "biz")
    c = svc.bugun.view(u)["chat"]
    assert c["count"] >= 1
    line = next(x for x in c["items"] if x["raw"] == "7y ois trades 33.10")
    assert line["q"]["product"] == "OIS" and line["q"]["price"] == pytest.approx(33.10) and len(line["time"]) == 5
    svc.add_ois(u, {"strategy": "outright", "side": "PAY", "tenor": "7Y", "level": "33,10"})
    assert "7y ois trades 33.10" not in [x["raw"] for x in svc.bugun.view(u)["chat"]["items"]]


def test_todays_agenda_the_late_deadlines_and_the_meetings(svc, monkeypatch):
    u, other = login(svc, "Bugün Ajanda"), login(svc, "Bugün Başkası")
    iso = TODAY.isoformat()
    svc.desk.add(u, iso, "10:00", "TÜFE verisi", False, True)
    svc.desk.add(u, iso, None, "Kendi notum", False, False)
    svc.desk.add(other, iso, "11:00", "Başkasının kendi işi", False, False)
    svc.desk.add(u, (TODAY - dt.timedelta(days=2)).isoformat(), "16:00", "Rapor teslimi", True, True)
    monkeypatch.setattr(svc.history, "archive", lambda: [iso])
    a = svc.bugun.view(u)["agenda"]
    texts = [x["text"] for x in a["items"]]
    assert "TÜFE verisi" in texts and "Kendi notum" in texts and "Başkasının kendi işi" not in texts
    mine = next(x for x in a["items"] if x["text"] == "Kendi notum")
    assert not mine["shared"] and mine["time"] is None
    assert [x["text"] for x in a["late"]] == ["Rapor teslimi"] and a["late"][0]["deadline"]
    assert a["meetings"]["ppk"]["today"] and a["meetings"]["fomc"]["known"]
    assert isinstance(a["holidays"], list)
    # the other user sees the desk's item and their own
    texts2 = [x["text"] for x in svc.bugun.view(other)["agenda"]["items"]]
    assert "TÜFE verisi" in texts2 and "Başkasının kendi işi" in texts2 and "Kendi notum" not in texts2


def test_a_block_that_fails_says_so_and_the_others_stand(svc, monkeypatch):
    u = login(svc, "Bugün Hata")

    def broken(user, date=None, date_to=None):
        raise RuntimeError("chat kırıldı")

    monkeypatch.setattr(svc, "broker_recon", broken)
    v = svc.bugun.view(u)
    assert v["chat"] == {"error": "okunamadı: chat kırıldı"} and "available" in v["ret"] and "items" in v["agenda"]
    with pytest.raises(ServiceError):
        svc.bugun.view(None)


def test_over_http(svc):
    with TestClient(create_app(svc)) as client:
        assert client.get("/api/bugun", headers=ANON).status_code == 401
        res = client.get("/api/bugun", headers=auth(svc, "Bugün HTTP"))
        assert res.status_code == 200
        assert set(res.json()) >= {"today", "time", "close", "ret", "trades", "quant", "dibs", "chat", "agenda"}
