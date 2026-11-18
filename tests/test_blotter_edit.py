"""Günlük İşlemler: a trade changed after it was entered ("Düzenle") - priced again exactly as a new trade is, its rows
changed in place (the same ids, its day, who entered it and when), what it was kept with it (``edits``), a change of
product, strategy or number of legs refused; the workbook's sheet, the cost tables and the chat's pairs after an edit; and
the cost against mid as the desk reads it ("Mid'e göre": + better than mid) in the day's file."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell
from helpers import read_xlsx
from tto import blotter as bl
from tto import brokerchat as bc
from tto.server import create_app
from tto.service import ServiceError
from tto.store import Store
from tto.xl.values import date_to_serial

VALUE = "15.12.2026"


@pytest.fixture(scope="module")
def desk(module_service):
    """A blotter of its own (the tests change its trades): A enters, B edits - anyone may, as anyone may delete."""
    svc = module_service
    return svc, svc.login("Düzenle A")["user"], svc.login("Düzenle B")["user"]


def market(svc, tenor):
    """The mid (par) and the annuity of an OIS tenor, as the form prices it."""
    row = {r["tenor"]: r for r in svc.ois_market(None)["tenors"]}[tenor]
    return row["par"], row["annuity"]


def sheet_row(svc, tid):
    """The row of the workbook's own sheet a trade (a leg) of today is in: its place in its list (no meeting-dated OIS here)."""
    trades = svc.store.trades(svc.today_iso())
    t = next(x for x in trades if x["id"] == tid)
    assert not any(x.get("mpc") for x in trades)
    same = [x["id"] for x in trades if x["kind"] == t["kind"] and (x["kind"] != "fwd" or bl.in_summary(x))]
    return 3 + same.index(tid)


def sheet(svc, cols, row):
    return [cell(svc, "Günlük İşlemler!%s%d" % (c, row)) for c in cols]


def listed(svc, user, tid):
    return next(t for t in svc.blotter(user)["trades"] if t["id"] == tid)


# ---------------------------------------------------------------------------------------------- the store
def test_a_package_is_changed_whole_or_not_at_all(tmp_path):
    store = Store(str(tmp_path / "tto.db"))
    try:
        ids = store.add_trades("2026-11-18", "ois", [{"tenor": "3M", "rate": 0.1}, {"tenor": "6M", "rate": 0.2}], "ali", "pkg1")
        legs = store.trade_legs(ids[1])                                  # a leg: the whole package, oldest first
        assert [x["id"] for x in legs] == ids and legs[0]["created_by"] == "ali" and legs[1]["package"] == "pkg1"
        assert store.update_trades([(ids[0], {"tenor": "3M", "rate": 1.0}), (ids[1], {"tenor": "6M", "rate": 2.0})], "veli") == ids
        legs = store.trade_legs(ids[0])
        assert [x["rate"] for x in legs] == [1.0, 2.0] and {x["updated_by"] for x in legs} == {"veli"}
        assert [(x["created_by"], x["trade_date"]) for x in legs] == [("ali", "2026-11-18")] * 2
        # one of them not there (deleted meanwhile): none of them is changed
        gone = store.add_trade("2026-11-18", "fwd", {"amount": 1.0}, "ali")
        store.delete_trade(gone, "ali")
        assert store.update_trades([(ids[0], {"tenor": "3M", "rate": 9.0}), (gone, {"amount": 2.0})], "veli") == []
        assert store.trade(ids[0])["rate"] == 1.0 and not store._db.in_transaction
        assert store.trade_legs(gone) == [] and store.trade_legs(424242) == []
        assert store.update_trade(ids[0], {"tenor": "3M", "rate": 3.0}, "x") is True and store.update_trade(gone, {}, "x") is False
    finally:
        store.close()


def test_what_an_edit_changed_rounding_aside():
    old = {"id": 7, "kind": "ois", "created_at": "2026-11-18 10:00:00", "rate": 0.3689999999999999, "nominal": 1e9, "cpt": "A",
           "edits": [{"at": "x"}], "kept": True}
    new, was = bl.edited(old, {"rate": 0.369, "nominal": 2e9, "cpt": "B", "note": ""})
    assert was == {"nominal": 1e9, "cpt": "A", "note": None}                  # a rate back from its text: the same rate
    assert new["rate"] == 0.3689999999999999 and new["nominal"] == 2e9 and new["kept"] and new["edits"] == [{"at": "x"}]
    assert not set(bl.ROW_KEYS) & set(new)
    assert bl.edited(old, {"rate": 0.3689999999999999})[1] == {} and bl.edited(old, {"rate": 0.37})[1] == {"rate": 0.3689999999999999}


# ---------------------------------------------------------------------------------------------- OIS
def test_an_outright_is_changed_in_place(desk):
    svc, a, b = desk
    mid, annuity = market(svc, "7Y")
    o = svc.add_ois(a, {"strategy": "outright", "side": "PAY", "tenor": "7Y", "level": "35,60", "dv01": 5000, "cpt": "ABC", "note": "ilk"})
    (tid,) = o["ids"]
    before = listed(svc, a, tid)
    assert (before["size_mode"], before["size_typed"]) == ("dv01", 5000.0) and "edits" not in before
    risk = svc.blotter(a)["risk"]["ois"]
    gen = svc.gen
    res = svc.edit_trade(b, tid, {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "7Y", "level": "35,70", "nominal": "600m",
                                  "cpt": "XYZ", "note": "ilk"})
    assert res["edited"] and res["ids"] == [tid] and res["id"] == tid and res["label"] == "PAY 7Y @ 35,7000%" and svc.gen > gen
    t = listed(svc, a, tid)
    # priced as a new trade is: the level, the nominal, the counterparty - and its cost against the mid of now
    assert (t["rate"], t["level"], t["nominal"], t["cpt"], t["label"]) == (pytest.approx(0.357), pytest.approx(0.357), 600e6, "XYZ", res["label"])
    usdtry = svc.ois_market(None)["usdtry"]
    assert t["dv01"] == pytest.approx(600e6 * annuity * 1e-4 / usdtry) and t["cost_bp"] == pytest.approx((0.357 - mid) * 1e4)
    assert t["cost_usd"] == pytest.approx(t["cost_bp"] * t["dv01"]) and (t["size_mode"], t["size_typed"]) == ("nominal", 600e6)
    # the same row: its id, day, who entered it and when; who changed it, and what it was
    assert (t["created_by"], t["created_at"], t["trade_date"], t["package"]) == (a, before["created_at"], before["trade_date"], None)
    assert t["updated_by"] == b
    (e,) = t["edits"]
    assert e["by"] == b and e["at"] >= before["created_at"] and set(e) == {"at", "by", "was"}
    assert e["was"]["level"] == pytest.approx(0.356) and e["was"]["rate"] == pytest.approx(0.356) and e["was"]["cpt"] == "ABC"
    assert (e["was"]["nominal"], e["was"]["dv01"], e["was"]["label"]) == (before["nominal"], before["dv01"], "PAY 7Y @ 35,6000%")
    assert (e["was"]["size_mode"], e["was"]["size_typed"]) == ("dv01", 5000.0) and not {"note", "tenor", "dir", "role"} & set(e["was"])
    # the workbook's sheet, the cost table by tenor and the risk follow
    assert sheet(svc, "HIJKLM", sheet_row(svc, tid)) == [600e6, pytest.approx(t["dv01"]), "B", pytest.approx(0.357), "7Y", "XYZ"]
    data = svc.blotter(a)
    seven = {x["key"]: x for x in data["cost"]["ois"]}["7Y"]
    assert seven["buy"] == pytest.approx(t["dv01"]) and seven["cost"] == pytest.approx(0.357) and seven["sell"] == 0
    assert data["risk"]["ois"] == pytest.approx(risk - before["dv01"] + t["dv01"])
    # the same trade sent again: nothing changes, nothing is written
    again = svc.edit_trade(a, tid, {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "7Y", "level": "35,7", "nominal": "600.000.000",
                                    "cpt": "XYZ", "note": "ilk"})
    assert again["edited"] is False and again["ids"] == [tid]
    assert listed(svc, a, tid)["edits"] == t["edits"] and listed(svc, a, tid)["updated_by"] == b


def test_a_fra_package_is_changed_leg_by_leg(desk):
    svc, a, b = desk
    o = svc.add_ois(a, {"strategy": "fra", "side": "RECEIVE", "start_months": 3, "end_months": 6, "level": "35,10", "dv01": 2000, "cpt": "FRA"})
    ids = o["ids"]
    start, end = o["legs"]
    old = svc.store.trade_legs(ids[0])
    nominal = 2 * start["nominal"]
    # what the form sends back: the start leg's own rate as it showed it (per cent, in full)
    res = svc.edit_trade(b, ids[1], {"kind": "ois", "strategy": "fra", "side": "RECEIVE", "start_months": 3, "end_months": 6,
                                     "level": "35,20", "nominal": nominal, "start_rate": ("%.13f" % (start["rate"] * 100)).replace(".", ","),
                                     "cpt": "FRA"})
    assert res["edited"] and res["ids"] == ids
    legs = svc.store.trade_legs(ids[1])
    assert [x["id"] for x in legs] == ids and {x["package"] for x in legs} == {old[0]["package"]}
    s, e = legs
    assert (s["role"], e["role"]) == ("start", "end") and s["nominal"] == e["nominal"] == nominal      # one nominal, both swaps
    assert s["rate"] == start["rate"]                       # its own rate sent back as it was shown: kept as it was
    a1, a2 = res["legs"][0]["annuity"], res["legs"][1]["annuity"]
    assert (e["rate"] * a2 - s["rate"] * a1) / (a2 - a1) == pytest.approx(0.352, rel=1e-12)      # the swaps lock in the new level
    assert s["label"] == e["label"] == "RECEIVE FRA 3M→6M @ 35,2000%" and s["level"] == e["level"] == pytest.approx(0.352)
    assert s["cost_bp"] == e["cost_bp"] == pytest.approx((res["info"]["market"] - 0.352) * 1e4)
    # every leg keeps the edit - one edit, each leg's own values before
    assert [len(x["edits"]) for x in legs] == [1, 1] and s["edits"][0]["at"] == e["edits"][0]["at"]
    assert "rate" not in s["edits"][0]["was"] and e["edits"][0]["was"]["rate"] == end["rate"]
    assert s["edits"][0]["was"]["nominal"] == e["edits"][0]["was"]["nominal"] == start["nominal"]
    assert s["edits"][0]["was"]["label"] == "RECEIVE FRA 3M→6M @ 35,1000%"
    # the sheet's two rows and the cost table by tenor follow
    for leg in legs:
        assert sheet(svc, "HIJKLM", sheet_row(svc, leg["id"])) == [nominal, pytest.approx(leg["dv01"]), leg["dir"], pytest.approx(leg["rate"]),
                                                                    leg["tenor"], "FRA"]
    cost = {x["key"]: x for x in svc.blotter(a)["cost"]["ois"]}
    assert cost["3M"]["buy"] == pytest.approx(s["dv01"]) and cost["6M"]["sell"] == pytest.approx(e["dv01"])
    assert cost["6M"]["sell_avg"] == pytest.approx(e["rate"]) and cost["3M"]["buy_avg"] == pytest.approx(s["rate"])


def test_a_spread_sized_by_dv01_starts_from_what_was_typed(desk):
    """A spread / fly sized by DV01 has legs of different nominals: the record keeps the DV01 typed - the edit gives it
    back and the legs come out the same on the same curve."""
    svc, a, b = desk
    o = svc.add_ois(a, {"strategy": "spread", "side": "STEEPENER", "short": "8Y", "long": "9Y", "level": "12", "dv01": 3000})
    short, long_ = svc.store.trade_legs(o["ids"][0])
    assert short["nominal"] != long_["nominal"] and (short["size_mode"], short["size_typed"]) == ("dv01", 3000.0)
    pct = lambda x: ("%.13f" % (x * 100)).replace(".", ",")                                          # noqa: E731
    res = svc.edit_trade(b, o["ids"][0], {"kind": "ois", "strategy": "spread", "side": "STEEPENER", "short": "8Y", "long": "9Y",
                                          "level": "13", "dv01": "3.000", "short_rate": pct(short["rate"]), "cpt": "SPR"})
    s, lg = svc.store.trade_legs(o["ids"][0])
    assert res["edited"] and (s["nominal"], lg["nominal"]) == (short["nominal"], long_["nominal"]) and s["rate"] == short["rate"]
    assert lg["rate"] == pytest.approx(short["rate"] + 13 / 1e4) and s["cpt"] == lg["cpt"] == "SPR"
    assert set(s["edits"][0]["was"]) == {"cpt", "label", "level", "cost_bp", "cost_usd"}           # (its leg as it was)


# ---------------------------------------------------------------------------------------------- forward, bond
def test_a_forward_is_priced_again_as_a_new_one(desk):
    svc, a, b = desk
    f = svc.add_forward(a, {"dir": "B", "amount": "10m", "value_date": VALUE, "basis": "RET_MID", "cpt": "ABC", "note": "fwd"})
    before = listed(svc, a, f["id"])
    new = {"pair": "USDTRY", "dir": "S", "amount": "12m", "value_date": "07.06.2027", "basis": "TRY", "manual": "36,5", "cpt": "DEF", "note": "fwd"}
    q = svc.quote_forward(b, dict(new))                       # what a new trade of it would be
    res = svc.edit_trade(b, f["id"], dict(new, kind="fwd"))
    assert res["edited"] and res["ids"] == [f["id"]]
    t = listed(svc, a, f["id"])
    assert (t["dir"], t["amount"], t["basis"], t["try_rate"], t["cpt"]) == ("S", 12e6, "TRY", 0.365, "DEF")
    assert t["value_date"] == float(date_to_serial(dt.date(2027, 6, 7)))
    assert (t["forward"], t["days"], t["tl"]) == (q["forward"], q["days"], pytest.approx(12e6 * q["forward"]))
    assert t["dv01"] == pytest.approx(q["dv01"]["usd"]) and t["dv01"] < 0 < f["dv01"]                       # sold: receiver −
    assert (t["created_by"], t["created_at"], t["updated_by"]) == (a, before["created_at"], b)
    was = t["edits"][0]["was"]
    assert (was["dir"], was["amount"], was["basis"], was["cpt"], was["value_date"], was["forward"]) == \
        ("B", 10e6, "RET_MID", "ABC", f["value_date"], f["forward"]) and was["manual"] is None
    assert sheet(svc, "ABCD", sheet_row(svc, f["id"])) == ["S", 12e6, 0.365, t["value_date"]]
    fwd = {x["key"]: x for x in svc.blotter(a)["cost"]["fwd"]}
    assert fwd[t["value_date"]]["sell"] == 12e6 and f["value_date"] not in fwd                        # the old value date is empty
    # typed in TRY: the TRY amount stays what is typed, the USD follows from the new forward
    g = svc.add_forward(a, {"dir": "B", "quote_amount": "520m", "value_date": VALUE, "basis": "FWD", "manual": "52"})
    svc.edit_trade(a, g["id"], {"kind": "fwd", "dir": "B", "quote_amount": "520m", "value_date": VALUE, "basis": "FWD", "manual": "52,5"})
    t = listed(svc, a, g["id"])
    assert (t["typed"], t["typed_amount"], t["tl"], t["forward"]) == ("quote", 520e6, 520e6, 52.5)
    assert t["amount"] == bl.ccy_round(520e6 / 52.5, "USD") and t["edits"][0]["was"]["amount"] == g["amount"]


def test_a_bond_is_changed(desk):
    svc, a, b = desk
    x = svc.add_bond(a, {"instrument": "TRT150328T24", "dir": "B", "amount": "50m", "price": "98,25", "note": "tahvil"})
    res = svc.edit_trade(b, x["id"], {"kind": "bond", "instrument": "TRT150328T24", "dir": "S", "amount": "20m", "price": "98,75",
                                      "note": "tahvil"})
    assert res["edited"] and res["ids"] == [x["id"]]
    t = listed(svc, a, x["id"])
    assert (t["amount"], t["price"], t["instrument"]) == (-20e6, 98.75, "TRT150328T24")
    assert t["dv01"] > 0 > x["dv01"] and t["dv01_tl"] == pytest.approx(-x["dv01_tl"] * 20 / 50)    # sold: payer + (the DİBS table's DV01)
    assert t["edits"][0]["was"] == {"amount": 50e6, "price": 98.25, "dv01": x["dv01"], "dv01_tl": x["dv01_tl"]}
    assert sheet(svc, ["Y", "Z", "AA"], sheet_row(svc, x["id"])) == ["TRT150328T24", -20e6, 98.75]
    (bond,) = [c for c in svc.blotter(a)["cost"]["bond"] if c["key"] == "TRT150328T24"]
    assert (bond["buy"], bond["sell"], bond["sell_avg"]) == (0, 20e6, 98.75)


def test_a_trade_keeps_its_last_edits(desk, monkeypatch):
    svc, a, b = desk
    monkeypatch.setattr(bl, "EDITS_KEPT", 2)
    x = svc.add_bond(a, {"instrument": "LISTEDE YOK", "dir": "B", "amount": "1m", "price": "99"})
    for note in ("bir", "iki", "üç"):
        svc.edit_trade(b, x["id"], {"kind": "bond", "instrument": "LISTEDE YOK", "dir": "B", "amount": "1m", "price": "99", "note": note})
    t = listed(svc, a, x["id"])
    assert t["note"] == "üç" and [e["was"] for e in t["edits"]] == [{"note": "bir"}, {"note": "iki"}]


# ---------------------------------------------------------------------------------------------- what an edit cannot do
def test_what_an_edit_does_not_change(desk):
    svc, a, b = desk
    out = svc.add_ois(a, {"strategy": "outright", "side": "RECEIVE", "tenor": "2Y", "level": "35", "nominal": "500m"})
    fra = svc.add_ois(a, {"strategy": "fra", "side": "PAY", "start_months": 0, "end_months": 12, "level": "35,7", "nominal": "1000m"})
    fwd = svc.add_forward(a, {"dir": "B", "amount": "1m", "value_date": VALUE, "basis": "RET_MID"})
    before = svc.store.trades(svc.today_iso())
    for tid, payload, words in (
            (out["ids"][0], {"kind": "ois", "strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": "25"},
             "düzenlemede strateji değişmez (Outright → Spread)"),
            (fra["ids"][0], {"kind": "ois", "strategy": "fra", "side": "PAY", "start_months": 3, "end_months": 12, "level": "35,7"},
             "düzenlemede bacak sayısı değişmez (1 → 2; spot başlangıçlı FRA tek bacaktır)"),
            (fwd["id"], {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35"},
             "düzenlemede ürün değişmez (FX Forward → OIS)"),
            (out["ids"][0], {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "2Y"}, "seviye"),        # checked as a new trade
            (fwd["id"], {"kind": "fwd", "dir": "B", "amount": "0", "value_date": VALUE}, "tutar")):
        with pytest.raises(ServiceError) as err:
            svc.edit_trade(b, tid, payload)
        assert words in str(err.value) and err.value.status == 400, (words, str(err.value))
        if "değişmez" in words:
            assert str(err.value).endswith("strateji değişiyorsa silip yeniden girin")
    assert svc.store.trades(svc.today_iso()) == before                       # nothing was changed
    # a trade of another day (priced with today's market: today's trades only), one that is not there, nobody signed in
    old = svc.store.add_trade("2026-02-03", "ois", {"strategy": "outright", "tenor": "2Y", "level": 0.355, "role": "outright", "dir": "S"}, a)
    with pytest.raises(ServiceError) as err:
        svc.edit_trade(b, old, {"kind": "ois", "strategy": "outright", "side": "RECEIVE", "tenor": "2Y", "level": "36"})
    assert "yalnızca bugünün işlemleri düzenlenebilir" in str(err.value) and "03.02.2026" in str(err.value)
    for tid in (999999, "x", None):
        with pytest.raises(ServiceError) as err:
            svc.edit_trade(b, tid, {"kind": "ois"})
        assert err.value.status == 404
    with pytest.raises(ServiceError) as err:
        svc.edit_trade(None, out["ids"][0], {"kind": "ois", "strategy": "outright", "side": "RECEIVE", "tenor": "2Y", "level": "36"})
    assert err.value.status == 401
    svc.delete_trade(a, fwd["id"])                                            # deleted meanwhile
    with pytest.raises(ServiceError) as err:
        svc.edit_trade(b, fwd["id"], {"kind": "fwd", "dir": "B", "amount": "2m", "value_date": VALUE, "basis": "RET_MID"})
    assert err.value.status == 404


# ---------------------------------------------------------------------------------------------- the chat's pairs
def test_the_chats_pairs_stay_with_an_edited_trade(desk):
    """A chat line is paired with a trade by its id (by hand), by its note ("İşlem gir") or by its level and time: an edit
    keeps the ids, the time it was entered and the note - the pairs stay (and follow its new label)."""
    svc, a, b = desk
    svc.broker_add(a, "18m ois paid 35.14\n1y ois paid 35.00\n9x12m ois fra paid 35.40", None, "", True, "biz")
    rows = {q["raw"]: q for q in svc.broker(a)["rows"]}
    note = bc.chat_note(rows["1y ois paid 35.00"])
    auto = svc.add_ois(a, {"strategy": "outright", "side": "PAY", "tenor": "18M", "level": "35,14", "cpt": "AUTO"})
    linked = svc.add_ois(a, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35", "note": note})
    fra = svc.add_ois(a, {"strategy": "fra", "side": "PAY", "start_months": 9, "end_months": 12, "level": "35,50", "dv01": 1000})  # not 35.40
    svc.broker_recon_set(a, rows["9x12m ois fra paid 35.40"]["id"], "match", fra["ids"][1])         # by hand, with its second leg

    def states():
        return {x["raw"]: (x["state"], (x["entry"] or {}).get("id")) for x in svc.broker_recon(a)["items"]}

    paired = {"18m ois paid 35.14": ("auto", auto["ids"][0]), "1y ois paid 35.00": ("linked", linked["ids"][0]),
              "9x12m ois fra paid 35.40": ("manual", fra["ids"][0])}
    assert states() == paired
    times = {e["id"]: e["time"] for e in svc.broker_recon(a)["entries"]}
    # edited by another user: the counterparty of the one paired by its level, the level of the one entered from its line
    # (the form keeps its note), the level and the size of the FRA paired by hand
    svc.edit_trade(b, auto["ids"][0], {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "18M", "level": "35,14", "cpt": "DEĞİŞTİ"})
    svc.edit_trade(b, linked["ids"][0], {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "35,02", "note": note})
    svc.edit_trade(b, fra["ids"][0], {"kind": "ois", "strategy": "fra", "side": "PAY", "start_months": 9, "end_months": 12, "level": "35,40",
                                      "dv01": 3000})
    assert states() == paired
    entries = {e["id"]: e for e in svc.broker_recon(a)["entries"]}
    assert entries[fra["ids"][0]]["label"] == "PAY FRA 9M→1Y @ 35,4000%" and entries[fra["ids"][0]]["ids"] == fra["ids"]
    assert {i: entries[i]["time"] for i in times} == times and all(entries[i]["taken"] for i in (auto["ids"][0], linked["ids"][0]))
    # a level edited away from the chat's is not the chat's trade any more: the line says it is not entered
    svc.edit_trade(b, auto["ids"][0], {"kind": "ois", "strategy": "outright", "side": "PAY", "tenor": "18M", "level": "35,30", "cpt": "DEĞİŞTİ"})
    assert states()["18m ois paid 35.14"] == ("missing", None)


# ---------------------------------------------------------------------------------------------- "Mid'e göre"
def test_the_days_file_says_the_cost_against_mid_the_desks_way(desk):
    """The desk: a PAY done 67 bp under mid is 67 bp in its favour.  The day's file says "Mid'e göre" - + better than mid
    (in the trade's favour), − worse - for a PAY and a RECEIVE either side of mid; the stored cost (+ worse: paid) is as it
    was, so a trade of before reads the same."""
    svc, a, _ = desk
    mid, _ = market(svc, "5Y")
    made = {}
    for side, level, better in (("PAY", mid - 0.0067, True), ("PAY", mid + 0.0067, False), ("RECEIVE", mid + 0.0067, True),
                                ("RECEIVE", mid - 0.0067, False)):
        note = "mid %s %s" % (side, "iyi" if better else "kötü")
        q = svc.add_ois(a, {"strategy": "outright", "side": side, "tenor": "5Y", "level": level, "dv01": 1000, "note": note})
        assert q["info"]["cost_bp"] == pytest.approx(-67.0 if better else 67.0)          # the stored cost: + worse than mid
        made[note] = (q, better)
    lst = read_xlsx(svc.blotter_export(a)[0])["İşlem listesi"]
    cells = {v: k for k, v in lst.items() if isinstance(v, str)}
    head = int(cells["OIS"][1:]) + 1
    assert [lst["%s%d" % (c, head)] for c in "IJKLM"] == ["DV01 ($)", "Mid'e göre (bp)", "Mid'e göre ($)", "Karşı taraf", "Not"]
    found = {lst.get("M%d" % r): r for r in range(head + 1, head + 200) if lst.get("M%d" % r)}
    for note, (q, better) in made.items():
        r = found[note]
        assert lst["J%d" % r] == pytest.approx(-q["info"]["cost_bp"]) and lst["K%d" % r] == pytest.approx(-q["info"]["cost_usd"])
        assert (lst["J%d" % r] > 0) == better and (lst["K%d" % r] > 0) == better


# ---------------------------------------------------------------------------------------------- over HTTP (last: the client stops the service)
def test_over_http(desk):
    svc, a, b = desk
    hdr = auth(svc, a)
    with TestClient(create_app(svc)) as client:
        made = client.post("/api/blotter/ois", json={"strategy": "outright", "side": "PAY", "tenor": "4Y", "level": "36", "nominal": "300m"},
                           headers=hdr).json()
        tid = made["ids"][0]
        body = {"kind": "ois", "strategy": "outright", "side": "RECEIVE", "tenor": "4Y", "level": "36,1", "nominal": "300m"}
        res = client.post("/api/blotter/trade/%d" % tid, json=body, headers=auth(svc, b))
        assert res.status_code == 200 and res.json()["edited"] and res.json()["ids"] == [tid]
        t = next(x for x in client.get("/api/blotter", headers=hdr).json()["trades"] if x["id"] == tid)
        assert t["dir"] == "S" and t["created_by"] == a and t["edits"][0]["by"] == b and t["edits"][0]["was"]["dir"] == "B"
        spread = dict(body, strategy="spread", side="FLATTENER", short="1Y", long="4Y", level="25")
        refused = client.post("/api/blotter/trade/%d" % tid, json=spread, headers=hdr)
        assert refused.status_code == 400 and "strateji değişiyorsa silip yeniden girin" in refused.json()["error"]
        assert client.post("/api/blotter/trade/999999", json=body, headers=hdr).status_code == 404
        assert client.post("/api/blotter/trade/%d" % tid, json=body, headers={"Authorization": ""}).status_code == 401
        assert client.post("/api/blotter/trade/%d" % tid, content=b"[]", headers=dict(hdr, **{"Content-Type": "application/json"})).status_code == 400
        assert client.delete("/api/blotter/trade/%d" % tid, headers=hdr).json()["deleted"] == [tid]          # (deleting is as it was)
