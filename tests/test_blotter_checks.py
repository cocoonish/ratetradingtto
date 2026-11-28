"""Günlük İşlemler: the checks before "İşlemi kaydet" and the counterparty list (the desk, 28.11.2026, A5: "RET bugün
yüklenmemiş, veri BAYAT, OIS seviyesi mid'den N bp uzak, tutar alışılmışın ~10 katı → tek tık onay; Karşı taraf
listeden"), and a bond named as the desk names it ("mar28": Ctrl+K's "işlem gir dibs mar28 50m al").  The checks only say
what deserves a second look - nothing is kept, a trade that does not price is the save's to refuse."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import auth, make_service
from tto import blotter as bl
from tto.server import create_app
from tto.service import ServiceError

TODAY = "2026-11-28"
SETTINGS = dict(bl.CHECK_DEFAULTS)


def facts(**kw):
    out = {"live": False, "today": TODAY, "ret": None, "feed": {"state": "replay"}, "usual": {}, "names": []}
    out.update(kw)
    return out


def codes(warnings):
    return [w["code"] for w in warnings]


# ---------------------------------------------------------------------------------------------- the rules
def test_the_thresholds_are_the_desks_within_their_limits():
    assert bl.check_settings(None) == {"far_bp": 10.0, "size_x": 10.0}
    assert bl.check_settings({"far_bp": 25, "size_x": 4.5, "by": "x"}) == {"far_bp": 25.0, "size_x": 4.5}
    assert bl.check_settings({"far_bp": 0, "size_x": True}) == SETTINGS                       # (outside the limits: the default)


def test_the_usual_size_of_each_kind():
    """An OIS package by its largest leg DV01, a forward by its pair's amount, a bond by its nominal: the median."""
    trades = [{"kind": "ois", "id": 1, "package": "p", "dv01": 3000.0}, {"kind": "ois", "id": 2, "package": "p", "dv01": -2900.0},
              {"kind": "ois", "id": 3, "package": None, "dv01": 1000.0}, {"kind": "ois", "id": 4, "dv01": 5000.0},
              {"kind": "fwd", "pair": "USDTRY", "amount": 10e6}, {"kind": "fwd", "pair": "USDTRY", "amount": 2e6},
              {"kind": "fwd", "pair": "EURTRY", "amount": 5e6}, {"kind": "bond", "amount": -50e6}, {"kind": "bond", "amount": 10e6}]
    got = bl.usual_sizes(trades)
    assert got == {"ois": [3000.0, 3], "fwd": {"USDTRY": [6e6, 2], "EURTRY": [5e6, 1]}, "bond": [30e6, 2]}
    assert bl.usual_sizes([]) == {"fwd": {}}


def test_a_counterparty_spelled_like_another():
    known = ["Garanti", "İş Bankası", "Akbank"]
    assert bl.similar_name("Garanti BBVA", known) == "Garanti" and bl.similar_name("garanti bbva", known) == "Garanti"
    assert bl.similar_name("Is Bankasi", known) == "İş Bankası"
    assert bl.similar_name("GARANTI", known) is None                       # (the same name: Excel reads it as one)
    assert [bl.similar_name(x, known) for x in ("Yapı Kredi", "", None, "Ak")] == [None, None, None, None]


def test_what_deserves_a_second_look():
    """RET and the feed only when live; an OIS level far from mid either side, in its own unit; a size ~10× the usual (a
    kind of trade with fewer than five behind it is not judged); a bond's price far from DİBS RV's in yield."""
    ret_old = {"updated_at": "2026-11-27 17:05:00", "updated_by": "ayse"}
    w = bl.pre_save_warnings("fwd", {"amount": 1e6, "pair": "USDTRY"}, {"basis": "RET_MID"}, facts(live=True, ret=ret_old), SETTINGS)
    assert w == [{"code": "ret", "text": "RET bugün yüklenmedi (son: 27.11.2026 17:05 · ayse): forward eski RET'le fiyatlanıyor"}]
    assert codes(bl.pre_save_warnings("fwd", None, {"basis": "RET_BID"}, facts(live=True), SETTINGS)) == ["ret"]      # (never loaded)
    today = {"updated_at": TODAY + " 09:12:00", "updated_by": "ayse"}
    for basis, live, ret in (("RET_ASK", True, today), ("TRY", True, ret_old), ("RET_MID", False, ret_old)):
        assert bl.pre_save_warnings("fwd", None, {"basis": basis}, facts(live=live, ret=ret), SETTINGS) == [], basis
    for state in ("stale", "silent", "down"):
        w = bl.pre_save_warnings("ois", None, {}, facts(live=True, feed={"state": state, "as_of": "10:42"}), SETTINGS)
        assert w == [{"code": "stale", "text": "Piyasa verisi BAYAT (10:42 itibarıyla): mid ve fiyatlar eski olabilir"}]
    assert bl.pre_save_warnings("ois", None, {}, facts(feed={"state": "stale"}), SETTINGS) == []                  # (replay)
    # an OIS: its level against its mid, + or −; a spread in bp
    q = {"strategy": "outright", "level": 0.3575, "info": {"market": 0.3555, "cost_bp": 20.0}, "legs": [{"dv01": 3000.0}]}
    assert bl.pre_save_warnings("ois", q, {}, facts(), SETTINGS) == [
        {"code": "far", "text": "Seviye mid'den 20,0 bp uzak: seviye %35,75, mid %35,55 (sınır 10 bp)"}]
    q2 = dict(q, info={"market": 0.3555, "cost_bp": -9.99})
    assert bl.pre_save_warnings("ois", q2, {}, facts(), SETTINGS) == []
    sp = {"strategy": "spread", "level": 25.0, "info": {"market": -50.0, "cost_bp": -75.0}, "legs": [{"dv01": 3000.0}, {"dv01": 3000.0}]}
    assert bl.pre_save_warnings("ois", sp, {}, facts(), SETTINGS)[0]["text"] == "Seviye mid'den 75,0 bp uzak: seviye 25,00 bp, mid -50,00 bp (sınır 10 bp)"
    assert bl.pre_save_warnings("ois", sp, {}, facts(), dict(SETTINGS, far_bp=80.0)) == []
    # the size: ten times the usual or more, from five trades on
    usual = {"ois": [2500.0, 12], "fwd": {"USDTRY": [5e6, 20], "EURTRY": [5e6, 4]}, "bond": [20e6, 9]}
    big = dict(q, info={"market": 0.3555, "cost_bp": 0.0}, legs=[{"dv01": 25000.0}, {"dv01": -24000.0}])
    assert bl.pre_save_warnings("ois", big, {}, facts(usual=usual), SETTINGS) == [
        {"code": "size", "text": "Büyüklük alışılmışın 10 katı: DV01 25.000 $ (son 60 günün ortancası 2.500 $, 12 işlem)"}]
    assert bl.pre_save_warnings("ois", big, {}, facts(usual={"ois": [2500.0, 4]}), SETTINGS) == []                 # (four behind it)
    assert codes(bl.pre_save_warnings("fwd", {"amount": 50e6, "pair": "USDTRY"}, {"basis": "TRY"}, facts(usual=usual), SETTINGS)) == ["size"]
    assert bl.pre_save_warnings("fwd", {"amount": 50e6, "pair": "EURTRY"}, {"basis": "TRY"}, facts(usual=usual), SETTINGS) == []
    assert bl.pre_save_warnings("fwd", {"amount": 49e6, "pair": "USDTRY"}, {"basis": "TRY"}, facts(usual=usual), SETTINGS) == []
    # a bond: its price against the table's clean price, in yield by its modified duration; its nominal
    bq = {"amount": -200e6, "info": {"clean": 98.5, "mod_dur": 2.0}}
    w = bl.pre_save_warnings("bond", bq, {"price": 98.0}, facts(usual=usual), SETTINGS)
    assert codes(w) == ["far", "size"] and w[0]["text"] == "Fiyat DİBS RV'nin temiz fiyatından ~25 bp (getiri) uzak: 98,000, tabloda 98,500"
    assert bl.pre_save_warnings("bond", dict(bq, amount=1e6), {"price": 98.45}, facts(usual=usual), SETTINGS) == []
    # a counterparty spelled like one used before
    w = bl.pre_save_warnings("ois", None, {"cpt": "Garanti BBVA"}, facts(names=["Garanti", "Akbank"]), SETTINGS)
    assert w == [{"code": "cpt", "text": "Karşı taraf \"Garanti BBVA\" daha önce \"Garanti\" diye yazıldı: CPT × VADE ikisini ayrı satırda sayar"}]


# ---------------------------------------------------------------------------------------------- on the service
@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("checks"))
    yield s
    s.stop()


def test_the_service_checks_a_trade_as_the_form_prices_it(svc):
    """Replay: no RET or feed warning (a recording); an OIS far from its mid; the usual sizes from the days before today
    (today's trades are not their own yardstick); a counterparty like one used before; nothing is kept."""
    u = svc.login("Kontrol Masa")["user"]
    today = dt.date.fromisoformat(svc.today_iso())
    mid = svc.quote_ois(u, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35"})["info"]["market"]
    near = "%.4f" % ((mid + 0.0005) * 100)
    far = "%.4f" % ((mid + 0.0030) * 100)
    pay = {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "1Y"}
    assert svc.blotter_check(u, dict(pay, level=near.replace(".", ","))) == {"warnings": [], "settings": SETTINGS}
    w = svc.blotter_check(u, dict(pay, level=far.replace(".", ",")))["warnings"]
    assert codes(w) == ["far"] and w[0]["text"].startswith("Seviye mid'den 30,0 bp uzak")
    assert codes(svc.blotter_check(u, {"kind": "fwd", "value_date": "3M", "basis": "RET_MID", "amount": "10m", "dir": "B"})["warnings"]) == []
    # five past days' trades make the yardstick (kept on past days: today's are not)
    for k in range(1, 6):
        day = (today - dt.timedelta(days=k)).isoformat()
        svc.store.add_trade(day, "fwd", {"pair": "USDTRY", "dir": "B", "amount": 5e6, "cpt": "Garanti"}, u)
        svc.store.add_trades(day, "ois", [{"dir": "B", "tenor": "1Y", "dv01": 2000.0, "nominal": 1e9, "cpt": "Akbank"}], u, None)
    svc._past_trades_kept = None                                         # (read once a day: a new day here)
    w = svc.blotter_check(u, {"kind": "fwd", "value_date": "3M", "basis": "RET_MID", "amount": "60m", "dir": "B", "cpt": "Garanti BBVA"})["warnings"]
    assert codes(w) == ["size", "cpt"] and "12 katı" in w[0]["text"] and "Garanti" in w[1]["text"]
    w = svc.blotter_check(u, dict(pay, level=near.replace(".", ","), dv01="25k"))["warnings"]
    assert codes(w) == ["size"] and "DV01 25.000 $" in w[0]["text"]
    assert svc.blotter_check(u, dict(pay, level=near.replace(".", ","), dv01="15k"))["warnings"] == []
    # a trade that does not price: nothing of its own (the save says why); a kind that is none: refused
    assert svc.blotter_check(u, {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "7M", "level": "35"})["warnings"] == []
    with pytest.raises(ServiceError):
        svc.blotter_check(u, {"kind": "swap"})
    assert svc.store.trades(svc.today_iso()) == []                       # nothing was kept


def test_the_thresholds_and_the_counterparty_list(svc):
    """The desk's thresholds: anyone changes them (as typed, within limits), everyone reads the same; the names used
    before - the most used first - and Broker Chat's houses."""
    u, v = svc.login("Kontrol Ayar")["user"], svc.login("Kontrol Diğer")["user"]
    got = svc.blotter_checks(u)
    assert got["settings"] == SETTINGS and got["counterparties"][:2] == ["Akbank", "Garanti"]
    got = svc.blotter_checks(u, {"far_bp": "7,5", "size_x": 20})
    assert got["settings"] == {"far_bp": 7.5, "size_x": 20.0}
    assert svc.blotter_checks(v)["settings"] == {"far_bp": 7.5, "size_x": 20.0} and svc.blotter_checks(v)["set"]["by"] == u
    for bad in ({"far_bp": "0"}, {"size_x": "1"}, {"far_bp": "çok"}):
        with pytest.raises(ServiceError):
            svc.blotter_checks(u, bad)
    svc.store.put("broker.people", {"x": {"name": "Ali", "source": "Tullett", "party": "broker"}})
    names = svc.blotter_checks(u)["counterparties"]
    assert names.index("Tullett") > names.index("Garanti")              # (the houses after the names used)
    svc.blotter_checks(u, {"far_bp": 10, "size_x": 10})


def test_a_bond_named_as_the_desk_names_it(svc):
    """"mar28", "15.03.28", "15/3/2028": the bond the broker chat would read - its ISIN in the form and in the trade."""
    from tto import bonds as bd
    hit = bd.candidates(None, "2028-03", "fixed")
    assert hit, "the catalog has a March 2028 fixed coupon bond"
    best = sorted(hit, key=lambda b: -(b.get("coupon") or 0.0))[0]
    d = dt.date.fromisoformat(best["maturity"])
    assert bl.bond_isin("mar28") == best["isin"] and bl.bond_isin("Mar28") == best["isin"]
    assert bl.bond_isin(d.strftime("%d.%m.%y")) == best["isin"] and bl.bond_isin("%d/%d/%d" % (d.day, d.month, d.year)) == best["isin"]
    assert bl.bond_isin(" trt150328t24 ") == "TRT150328T24" and bl.bond_isin("xyz") == "xyz" and bl.bond_isin("mar28 jun29") == "mar28 jun29"
    u = svc.login("Kontrol Tahvil")["user"]
    q = svc.quote_bond(u, {"instrument": "mar28", "amount": "5m", "dir": "B"})
    assert q["instrument"] == best["isin"] and q["typed"] == "mar28"
    assert "typed" not in svc.quote_bond(u, {"instrument": best["isin"], "amount": "5m", "dir": "B"})


def test_over_http(svc):
    client = TestClient(create_app(service=svc))                          # (no "with": the module's service stays up)
    h = auth(svc, "Kontrol HTTP")
    r = client.post("/api/blotter/check", json={"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "50"}, headers=h)
    assert r.status_code == 200 and codes(r.json()["warnings"]) == ["far"]
    assert client.get("/api/blotter/checks", headers=h).json()["settings"] == SETTINGS
    assert client.post("/api/blotter/checks", json={"far_bp": "abc"}, headers=h).status_code == 400
    assert client.post("/api/blotter/check", json={"kind": "ois"}, headers={"Authorization": ""}).status_code == 401
