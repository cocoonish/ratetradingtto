"""Günlük İşlemler's entry: a forward typed in its second currency (the TRY of a USDTRY), templates of the form
(personal and the desk's) and rows pasted from Excel - and a database of the earlier version."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell, make_service
from helpers import read_xlsx
from tto import blotter as bl
from tto import entry
from tto.server import create_app
from tto.service import ServiceError
from tto.xl.values import date_to_serial

VALUE = "15.12.2026"
VALUE_SERIAL = float(date_to_serial(dt.date(2026, 12, 15)))


@pytest.fixture(scope="module")
def desk(module_service):
    svc = module_service
    u = svc.login("Giriş Masa")["user"]
    other = svc.login("Giriş Diğer")["user"]
    admin = svc.login("Giriş Yönetici")["user"]
    svc.store.update_account(admin, role="admin")
    return svc, u, other, admin


def quote(svc, user, **kw):
    kw.setdefault("value_date", VALUE)
    kw.setdefault("basis", "RET_MID")
    return svc.quote_forward(user, kw)


def sheet_rows(svc):
    """The forward list of the workbook's own sheet: (direction, amount, rate, value date) of each filled row."""
    out = []
    for r in range(3, 40):
        a = cell(svc, "Günlük İşlemler!A%d" % r)
        if a is None:
            break
        out.append((a, cell(svc, "Günlük İşlemler!B%d" % r), cell(svc, "Günlük İşlemler!C%d" % r), cell(svc, "Günlük İşlemler!D%d" % r)))
    return out


# ---------------------------------------------------------------------------------------------- minor currency
def test_a_usdtry_forward_typed_in_try(desk):
    svc, u, _, _ = desk
    q = quote(svc, u, quote_amount="520m")
    fwd = q["forward"]
    # the TRY typed stays as it is; the USD follows from the deal's own forward, to the cent
    assert (q["typed"], q["typed_amount"], q["tl"]) == ("quote", 520e6, 520e6)
    assert q["amount"] == bl.ccy_round(520e6 / fwd, "USD") and abs(q["amount"] * fwd - 520e6) <= 0.005 * fwd
    assert q["dv01"]["amount"] == q["amount"]                                  # the risk is the USD amount's
    assert q["dv01"]["tl"] == pytest.approx(bl.forward_dv01("B", q["amount"], fwd, q["days"], q["usdtry"], q["df_try"], q["df_usd"])["tl"])
    t = svc.add_forward(u, {"dir": "S", "value_date": VALUE, "basis": "RET_MID", "quote_amount": "520m", "cpt": "ABC"})
    assert (t["pair"], t["dir"], t["amount"], t["tl"], t["forward"]) == ("USDTRY", "S", q["amount"], 520e6, fwd)
    assert (t["typed"], t["typed_amount"]) == ("quote", 520e6) and t["dv01"] < 0
    # ... and it stays a USD trade everywhere: the list, the cost, the risk, the workbook's own sheet
    data = svc.blotter(u)
    kept = {x["id"]: x for x in data["trades"]}[t["id"]]
    assert (kept["amount"], kept["tl"], kept["typed"], kept["typed_amount"]) == (t["amount"], 520e6, "quote", 520e6)
    (pos,) = [c for c in data["cost"]["fwd"] if c["pair"] == "USDTRY"]
    assert pos["sell"] == t["amount"] and pos["sell_avg"] == pytest.approx(fwd, rel=1e-14)
    assert data["risk"]["fwd"] == pytest.approx(t["dv01"])
    assert ("S", t["amount"], t["try_rate"], VALUE_SERIAL) in sheet_rows(svc)
    # a forward typed in USD, as before: its TRY follows from the forward
    b = svc.add_forward(u, {"dir": "B", "value_date": VALUE, "basis": "RET_MID", "amount": "10m"})
    assert (b["amount"], b["tl"], b["typed"], b["typed_amount"]) == (10e6, 10e6 * b["forward"], "base", 10e6)


def test_eurtry_and_eurusd_typed_in_their_second_currency(desk):
    svc, u, _, _ = desk
    e = quote(svc, u, pair="EURTRY", quote_amount="300.000.000")
    assert (e["typed"], e["tl"]) == ("quote", 300e6) and e["amount"] == bl.ccy_round(300e6 / e["forward"], "EUR")
    assert e["forward"] == quote(svc, u, pair="EURTRY")["forward"]                # the same forward as typed in EUR
    t = svc.add_forward(u, {"pair": "EURTRY", "dir": "B", "value_date": VALUE, "basis": "SP", "manual": "22.500", "quote_amount": "300m"})
    assert t["amount"] == bl.ccy_round(300e6 / t["forward"], "EUR") and t["tl"] == 300e6 and t["pair"] == "EURTRY"
    # EURUSD: the second currency is USD - 5.425.000 USD at 1,0850 is 5 mn EUR exactly
    x = svc.add_forward(u, {"pair": "EURUSD", "dir": "S", "value_date": VALUE, "basis": "FWD", "manual": "1,0850", "quote_amount": "5.425.000"})
    assert (x["amount"], x["tl"], x["typed"], x["typed_amount"]) == (5e6, 5.425e6, "quote", 5.425e6) and x["dv01"] is None
    assert svc.quote_forward(u, {"pair": "EURUSD", "value_date": VALUE, "basis": "FWD", "manual": "1.0850", "quote_amount": "5,425,000"},
                             "en")["amount"] == 5e6                             # an English number as well
    # an amount worked out in yen is a whole number of yen
    j = svc.add_forward(u, {"pair": "JPYTRY", "dir": "B", "value_date": VALUE, "basis": "FWD", "manual": "0,2150", "quote_amount": "1m"})
    assert j["amount"] == 4651163.0 and j["tl"] == 1e6


def test_a_rate_typed_again_moves_only_the_side_not_typed(desk):
    svc, u, _, _ = desk
    a = quote(svc, u, basis="FWD", manual="52,00", quote_amount="520m")
    b = quote(svc, u, basis="FWD", manual="52,50", quote_amount="520m")
    assert (a["amount"], a["tl"]) == (10e6, 520e6)
    assert (b["amount"], b["tl"]) == (9904761.9, 520e6)
    c = quote(svc, u, basis="SP", manual="17.400", quote_amount="520m")          # another pricing: the TRY still stays
    assert c["tl"] == 520e6 and c["amount"] == bl.ccy_round(520e6 / c["forward"], "USD")
    # typed in USD, the TRY is what moves
    d = quote(svc, u, basis="FWD", manual="52,50", amount="10m")
    assert (d["amount"], d["tl"], d["typed"]) == (10e6, 525e6, "base")
    # nothing typed yet: the risk per 1 mn, no amount
    n = quote(svc, u)
    assert "amount" not in n and "tl" not in n and n["dv01"]["amount"] == 1e6


@pytest.mark.parametrize("payload, message", [
    ({"amount": "10m", "quote_amount": "520m"}, "ikisinden birini"),
    ({"quote_amount": "0"}, "karşı tutar pozitif"),
    ({"quote_amount": "-5m"}, "karşı tutar pozitif"),
    ({"quote_amount": "beş yüz"}, "karşı tutar anlaşılamadı"),
    ({}, "tutar pozitif"),
    ({"quote_amount": 0.004, "basis": "FWD", "manual": "52"}, "kadar küçük"),
])
def test_the_amount_is_typed_in_one_currency(desk, payload, message):
    svc, u, _, _ = desk
    with pytest.raises(ServiceError) as exc:
        svc.add_forward(u, dict({"dir": "B", "value_date": VALUE, "basis": "RET_MID"}, **payload))
    assert message in str(exc.value)


def test_rounding_and_what_was_typed():
    assert bl.ccy_round(9997635.2149, "USD") == 9997635.21 and bl.ccy_round(9997635.215, "USD") == 9997635.22
    assert bl.ccy_round(-1.005, "EUR") == -1.01 and bl.ccy_round(4651162.79, "JPY") == 4651163.0
    assert bl.forward_amounts(("quote", 520e6), 52.0, "USD") == (10e6, 520e6)
    assert bl.forward_amounts(("base", 10e6), 52.5, "USD") == (10e6, 525e6)
    assert bl.typed_amount({"amount": 1.0}) == ("base", 1.0) and bl.typed_amount({"quote_amount": 2.0}) == ("quote", 2.0)
    assert bl.typed_amount({}) is None and bl.typed_amount({"amount": None, "quote_amount": None}) is None
    # a forward of an earlier version was typed in its first currency
    assert bl.entered_as({"pair": "EURTRY", "amount": 5e6}) == ("base", 5e6, "EUR")
    assert bl.entered_as({"amount": 5e6}) == ("base", 5e6, "USD")
    assert bl.entered_as({"pair": "USDTRY", "amount": 9.9e6, "typed": "quote", "typed_amount": 520e6}) == ("quote", 520e6, "TRY")


def test_the_days_file_says_what_was_typed(desk):
    svc, u, _, _ = desk
    lst = read_xlsx(svc.blotter_export(u)[0])["İşlem listesi"]
    assert [lst[c + "5"] for c in "DIPQRS"] == ["Tutar (döviz)", "TL tutarı", "Parite", "Swap puanı", "Girilen tutar", "Girilen döviz"]
    rows = {}
    r = 6
    while lst.get("A%d" % r):
        rows.setdefault(lst["P%d" % r], []).append((lst["D%d" % r], lst["I%d" % r], lst.get("R%d" % r), lst.get("S%d" % r), lst["H%d" % r]))
        r += 1
    usd = rows["USDTRY"]
    assert usd[0][1:4] == (520e6, 520e6, "TRY") and usd[0][0] == bl.ccy_round(520e6 / usd[0][4], "USD")     # in USD, typed in TRY
    assert usd[1][:4] == (10e6, 10e6 * usd[1][4], 10e6, "USD")
    assert rows["EURUSD"][0][:4] == (5e6, 5.425e6, 5.425e6, "USD")
    assert lst["!formats"]["R6"] == "#,##0.00"


# ---------------------------------------------------------------------------------------------- templates
def ids(res):
    return [t["id"] for t in res["templates"]]


def test_a_users_own_templates(desk):
    svc, u, other, _ = desk
    res = svc.save_trade_template(u, "  Garanti   3A ", "fwd", {"pair": "eur", "dir": "S", "quote_amount": "300m", "date": "3M",
                                                               "cpt": "GARANTI", "note": "", "junk": "x"})
    tid = res["saved"]
    (t,) = [x for x in res["templates"] if x["id"] == tid]
    assert t["name"] == "Garanti 3A" and t["kind"] == "fwd" and not t["shared"] and t["can_edit"]
    assert t["spec"] == {"kind": "fwd", "pair": "EURTRY", "dir": "S", "quote_amount": "300m", "date": "3M", "cpt": "GARANTI"}
    assert tid not in ids(svc.trade_templates(other))                          # nobody else's
    for act in (lambda: svc.save_trade_template(other, "Benim", None, None, None, tid), lambda: svc.delete_trade_template(other, tid)):
        with pytest.raises(ServiceError) as exc:
            act()
        assert exc.value.status == 404
    # renamed: the name alone; edited: the content alone
    res = svc.save_trade_template(u, "Garanti EUR 3A", None, None, None, tid)
    (t,) = [x for x in res["templates"] if x["id"] == tid]
    assert t["name"] == "Garanti EUR 3A" and t["spec"]["quote_amount"] == "300m"
    res = svc.save_trade_template(u, None, "fwd", {"pair": "USDTRY", "dir": "B", "amount": "10m", "basis": "SP", "value": "17.400"}, None, tid)
    (t,) = [x for x in res["templates"] if x["id"] == tid]
    assert t["name"] == "Garanti EUR 3A" and t["spec"] == {"kind": "fwd", "pair": "USDTRY", "dir": "B", "amount": "10m", "basis": "SP",
                                                         "value": "17.400"}
    ois = svc.save_trade_template(u, "Fly", "ois", {"strategy": "fly", "side": "REC GÖVDE", "tenors": ["1Y", "2Y", "3Y"], "level": "-12",
                                                   "size": "2.000", "sizeMode": "dv01"})["saved"]
    bond = svc.save_trade_template(u, "TRT", "bond", {"dir": "B", "instrument": "TRT150328T24", "amount": "50m"})["saved"]
    mine = svc.trade_templates(u)
    assert [t["name"] for t in mine["templates"] if not t["shared"]] == ["Fly", "Garanti EUR 3A", "TRT"]      # by name
    assert svc.delete_trade_template(u, tid)["deleted"] == tid and tid not in ids(svc.trade_templates(u))
    with pytest.raises(ServiceError) as exc:
        svc.delete_trade_template(u, tid)
    assert exc.value.status == 404
    for x in (ois, bond):
        svc.delete_trade_template(u, x)


def test_the_desks_templates_are_an_administrators(desk):
    svc, u, other, admin = desk
    spec = {"strategy": "mpc", "side": "PAY", "mpc": [1, 2], "size": "5000", "sizeMode": "dv01", "cpt": "BARX"}
    with pytest.raises(ServiceError) as exc:
        svc.save_trade_template(u, "Masa MPC1-2", "ois", spec, shared=True)
    assert exc.value.status == 403
    gen = svc.gen
    tid = svc.save_trade_template(admin, "Masa MPC1-2", "ois", spec, shared=True)["saved"]
    assert svc.gen > gen                                                       # on everyone's page at once
    for user in (u, other, admin):
        (t,) = [x for x in svc.trade_templates(user)["templates"] if x["id"] == tid]
        assert t["shared"] and t["by"] == "Giriş Yönetici" and t["can_edit"] == (user == admin)
        assert t["spec"] == {"kind": "ois", "strategy": "mpc", "side": "PAY", "mpc": [1, 2], "size": "5000", "sizeMode": "dv01", "cpt": "BARX"}
    assert svc.trade_templates(admin)["can_publish"] and not svc.trade_templates(u)["can_publish"]
    # a user's own template may have the same name as the desk's
    mine = svc.save_trade_template(u, "Masa MPC1-2", "ois", spec)["saved"]
    listed = svc.trade_templates(u)["templates"]
    assert [x["id"] for x in listed if x["name"] == "Masa MPC1-2"] == [mine, tid]          # one's own first
    for act in (lambda: svc.save_trade_template(u, "Benim", None, None, None, tid), lambda: svc.delete_trade_template(u, tid),
                lambda: svc.save_trade_template(u, None, None, None, True, mine)):
        with pytest.raises(ServiceError) as exc:
            act()
        assert exc.value.status == 403
    # the administrator renames it, takes it back as their own, publishes it again, deletes it
    assert [x["name"] for x in svc.save_trade_template(admin, "Masa: MPC1→2", None, None, None, tid)["templates"] if x["id"] == tid] == ["Masa: MPC1→2"]
    svc.save_trade_template(admin, None, None, None, False, tid)
    assert tid not in ids(svc.trade_templates(u)) and tid in ids(svc.trade_templates(admin))
    svc.save_trade_template(admin, None, None, None, True, tid)
    assert tid in ids(svc.trade_templates(other))
    svc.delete_trade_template(admin, tid)
    assert tid not in ids(svc.trade_templates(other))
    svc.delete_trade_template(u, mine)


@pytest.mark.parametrize("name, kind, spec, message", [
    ("", "fwd", {"dir": "B"}, "adı gerekli"),
    ("x" * 61, "fwd", {"dir": "B"}, "60 karakter"),
    ("A", "swap", {"dir": "B"}, "bilinmeyen ürün"),
    ("A", "fwd", "B", "içeriği"),
    ("A", "fwd", {"junk": 1}, "şablon boş"),
    ("A", "fwd", {"dir": "X"}, "yön"),
    ("A", "fwd", {"pair": "lira"}, "parite"),
    ("A", "fwd", {"basis": "MID"}, "fiyatlama"),
    ("A", "fwd", {"amount": "10m", "quote_amount": "520m"}, "ikisinden biri"),
    ("A", "fwd", {"amount": "on milyon"}, "tutar anlaşılamadı"),
    ("A", "fwd", {"note": "n" * 201}, "200 karakter"),
    ("A", "ois", {"strategy": "spread", "side": "PAY"}, "STEEPENER ya da FLATTENER"),
    ("A", "ois", {"strategy": "fly", "tenors": ["1Y", "2Y"]}, "vadeler"),
    ("A", "ois", {"strategy": "outright", "tenors": ["13M"]}, "vadeler"),
    ("A", "ois", {"strategy": "fra", "months": [3, 5]}, "3'ün katı"),
    ("A", "ois", {"strategy": "mpc", "mpc": [2, 1]}, "sonraki bir toplantı"),
    ("A", "ois", {"strategy": "outright", "size": "5000", "sizeMode": "lot"}, "DV01 ya da nominal"),
    ("A", "bond", {"dir": "B", "amount": "elli"}, "tutar anlaşılamadı"),
])
def test_a_template_holds_only_what_the_form_takes(desk, name, kind, spec, message):
    svc, u, _, _ = desk
    with pytest.raises(ServiceError) as exc:
        svc.save_trade_template(u, name, kind, spec)
    assert message in str(exc.value)


def test_template_names_are_one_name_whatever_the_case(desk):
    svc, u, _, _ = desk
    tid = svc.save_trade_template(u, "Garanti 3A", "fwd", {"dir": "B"})["saved"]
    for twin in ("garanti 3a", "GARANTİ 3A", " Garanti  3A "):
        with pytest.raises(ServiceError) as exc:
            svc.save_trade_template(u, twin, "fwd", {"dir": "S"})
        assert exc.value.status == 409
    assert svc.save_trade_template(u, "GARANTI 3A", None, None, None, tid)["saved"] == tid          # its own name, recased
    svc.delete_trade_template(u, tid)


def test_a_template_fills_a_trade_the_form_prices(desk):
    """What one click fills the form with: the template comes with the blotter (the page's data), and its fields, sent as
    the form sends them, are a trade."""
    svc, u, _, admin = desk
    own = svc.save_trade_template(u, "USD 3A TRY", "fwd", {"pair": "USDTRY", "dir": "S", "quote_amount": "520m", "date": "3M",
                                                          "basis": "SP", "value": "40.000", "cpt": "ABC"})["saved"]
    shared = svc.save_trade_template(admin, "Masa 1Y", "ois", {"strategy": "outright", "side": "RECEIVE", "tenors": ["1Y"], "level": "35,60",
                                                              "size": "2.500", "sizeMode": "dv01"}, shared=True)["saved"]
    page = svc.blotter(u)
    listed = {t["id"]: t for t in page["templates"]}
    assert set(listed) == {own, shared} and not page["can_publish"] and [t["id"] for t in page["templates"]] == [own, shared]
    assert [t["id"] for t in svc.blotter(None)["templates"]] == [shared]                 # nobody signed in: the desk's alone
    f = listed[own]["spec"]
    q = svc.quote_forward(u, {"pair": f["pair"], "dir": f["dir"], "quote_amount": f["quote_amount"], "value_date": f["date"],
                              "basis": f["basis"], "manual": f["value"]})
    assert q["tl"] == 520e6 and q["typed"] == "quote" and q["points"] == pytest.approx(40000.0)
    assert q["value_date"] == svc.et.call(svc._tenor_date, "3M", "USDTRY")
    o = listed[shared]["spec"]
    legs = svc.quote_ois(u, {"strategy": o["strategy"], "side": o["side"], "tenor": o["tenors"][0], "level": o["level"], "dv01": o["size"]})
    assert legs["legs"][0]["dir"] == "S" and legs["legs"][0]["dv01"] == pytest.approx(2500, rel=0.01)
    svc.delete_trade_template(u, own)
    svc.delete_trade_template(admin, shared)


# ---------------------------------------------------------------------------------------------- pasted rows
def test_reading_a_paste():
    # the workbook's own lists, copied with their captions
    p = entry.read_paste("Yön\tTutar\tFaiz\tValör\r\nB\t10.000.000\t35,00%\t15.12.2026\r\n\r\nS\t2m\t36\t3M\r\n", "fwd")
    assert p["header"] and p["header_found"] and [c["field"] for c in p["columns"]] == ["dir", "amount", "try_rate", "value_date"]
    assert [r["n"] for r in p["rows"]] == [2, 4] and p["problems"] == []                # the line of the paste, empty lines left out
    assert entry.row_payload("fwd", p["columns"], p["rows"][0]["cells"]) == {
        "pair": "USDTRY", "dir": "B", "amount": "10.000.000", "value_date": "15.12.2026", "basis": "TRY", "manual": "35,00%", "cpt": "", "note": ""}
    o = entry.read_paste("Nominal\tDV01 USD\tYön\tFaiz\tValör\tCPT\n\t1000\tS\t35,55%\t1Y\tBARX\n500m\t\tB\t36\t2y\t\n", "ois")
    assert [c["field"] for c in o["columns"]] == ["nominal", "dv01", "side", "level", "tenor", "cpt"]
    assert entry.row_payload("ois", o["columns"], o["rows"][0]["cells"]) == {
        "side": "RECEIVE", "level": "35,55%", "strategy": "outright", "tenor": "1Y", "dv01": "1000", "cpt": "BARX", "note": ""}
    assert entry.row_payload("ois", o["columns"], o["rows"][1]["cells"])["nominal"] == "500m"       # a nominal is the size itself
    b = entry.read_paste("Enstrüman\tTutar\tFiyat\nTRT150328T24\t-20.000.000\t98,75\n", "bond")
    assert entry.row_payload("bond", b["columns"], b["rows"][0]["cells"]) == {"instrument": "TRT150328T24", "amount": "-20.000.000",
                                                                            "price": "98,75", "note": ""}
    # without a header: the order of the workbook's lists; a mapping says otherwise
    n = entry.read_paste("B\t10.000.000\t35,00%\t15.12.2026\tGARANTI", "fwd")
    assert not n["header"] and [c["field"] for c in n["columns"]] == ["dir", "amount", "try_rate", "value_date", None]
    m = entry.read_paste("B\t10.000.000\t35,00%\t15.12.2026\tGARANTI", "fwd", ["dir", "quote_amount", "try_rate", "value_date", "cpt"])
    assert entry.row_payload("fwd", m["columns"], m["rows"][0]["cells"])["quote_amount"] == "10.000.000"
    assert entry.read_paste("Yön\tTutar\nB\t1m", "fwd", header=False)["rows"][0]["cells"] == ["Yön", "Tutar"]
    # English captions, a currency in the caption: the pair of each row says which side it is
    e = entry.read_paste("Ccy Pair\tSide\tUSD Amount\tTRY\tValue Date\tFwd Rate\tCounterparty\n"
                         "EURUSD\tSell\t1m\t\t3M\t1.08\tX\nUSDTRY\tBuy\t\t520m\t3M\t52.1\tY\nEURTRY\tB\t1m\t\t3M\t60\t\n", "fwd")
    assert [(c["field"], c["ccy"]) for c in e["columns"]] == [("pair", None), ("dir", None), ("amount", "USD"), ("quote_amount", "TRY"),
                                                              ("value_date", None), ("forward", None), ("cpt", None)]
    rows = [entry.row_payload("fwd", e["columns"], r["cells"]) for r in e["rows"][:2]]
    assert (rows[0]["dir"], rows[0]["quote_amount"], "amount" in rows[0]) == ("S", "1m", False)        # USD is EURUSD's second
    assert (rows[1]["dir"], rows[1]["quote_amount"], rows[1]["basis"]) == ("B", "520m", "FWD")
    with pytest.raises(entry.EntryError) as exc:
        entry.row_payload("fwd", e["columns"], e["rows"][2]["cells"])                       # a USD amount on EURTRY
    assert "USD tutarı EURTRY paritesinde yok" in str(exc.value)
    # what the columns cannot be
    d = entry.read_paste("B\t1m\t35\t15.12.2026", "fwd", ["dir", "amount", "amount", "value_date"])
    assert any("iki sütunda" in x for x in d["problems"])
    s = entry.read_paste("Yön\tTutar\nB\t1m", "fwd")
    assert any("sütunu olmayan" in x and "Valör" in x for x in s["problems"])
    with pytest.raises(entry.EntryError):
        entry.read_paste("B", "fwd", ["yön"])
    with pytest.raises(entry.EntryError):
        entry.read_paste("B", "swap")
    with pytest.raises(entry.EntryError):
        entry.read_paste("B\t1m\t35\t3M\n" * (entry.PASTE_MAX_ROWS + 1), "fwd")
    # Excel puts a cell with a tab, a line break or a quote in quotes
    q = entry.read_paste('B\t1m\t35\t3M\t"ilk\tsatır\nikinci ""not"""\nS\t2m\t36\t3M\t', "fwd", ["dir", "amount", "try_rate", "value_date", "note"])
    assert q["rows"][0]["cells"][4] == 'ilk\tsatır\nikinci "not"' and [r["n"] for r in q["rows"]] == [2, 3]


def test_reading_a_rows_words():
    assert [entry.row_payload("fwd", entry.read_paste("Yön\tTutar\tFaiz\tValör\n%s\t1m\t35\t3M" % w, "fwd")["columns"], [w, "1m", "35", "3M"])["dir"]
            for w in ("B", "alış", "ALIŞ", "Buy", "S", "Satış", "sell")] == ["B", "B", "B", "B", "S", "S", "S"]
    cols = entry.read_paste("Yön\tTutar\tValör\tFiyatlama\tFaiz\tForward\tSwap puanı\nB\t1m\t3M\t\t\t\t", "fwd")["columns"]
    row = lambda *cells: entry.row_payload("fwd", cols, ["B", "1m", "3M"] + list(cells))          # noqa: E731
    assert (row("RET mid", "", "", "")["basis"], "manual" in row("RET mid", "", "", "")) == ("RET_MID", False)
    assert row("Swap puanı", "35", "52", "17.400")["manual"] == "17.400"                     # the basis picks its own price
    assert row("", "", "52,1", "")["basis"] == "FWD" and row("", "", "", "17.400")["basis"] == "SP"
    for cells, message in ((("", "", "", ""), "fiyat yok"), (("", "35", "52", ""), "birden çok fiyat"), (("FWD", "35", "", ""), "Forward kur yazılmamış"),
                           (("orta", "", "", ""), "fiyatlama anlaşılamadı")):
        with pytest.raises(entry.EntryError) as exc:
            row(*cells)
        assert message in str(exc.value)
    ois = entry.read_paste("Yön\tVade\tBaşlangıç\tBitiş\tOran\nPAY\t\t11.12.2026\t22.01.2027\t35,9", "ois")
    assert entry.row_payload("ois", ois["columns"], ois["rows"][0]["cells"])["strategy"] == "mpc"
    assert [entry.row_payload("ois", ois["columns"], [w, "1Y", "", "", "35"])["side"] for w in ("PAY", "rec", "B", "S", "Receive")] == [
        "PAY", "RECEIVE", "PAY", "RECEIVE", "RECEIVE"]
    with pytest.raises(entry.EntryError):
        entry.row_payload("ois", ois["columns"], ["PAY", "1Y", "11.12.2026", "", "35"])         # a tenor and a date


FWD_PASTE = "Yön\tTutar\tFaiz\tValör\nB\t3.000.000\t36,50%\t15.12.2026\nS\t2.000.000\t36,00%\t32.13.2026\nB\t1m\t36,25\t15.01.2027\n"


def test_pasted_rows_are_checked_as_the_form_checks_them(desk):
    svc, u, _, _ = desk
    p = svc.bulk_preview(u, "fwd", FWD_PASTE)
    assert [(r["n"], r["ok"]) for r in p["rows"]] == [(2, True), (3, False), (4, True)] and (p["valid"], p["invalid"]) == (2, 1)
    assert "valör tarihi anlaşılamadı" in p["rows"][1]["error"] and "32.13.2026" in p["rows"][1]["error"]
    # the numbers are the form's own
    form = svc.quote_forward(u, {"dir": "B", "amount": "3.000.000", "value_date": "15.12.2026", "basis": "TRY", "manual": "36,50%"})
    one = p["rows"][0]["trade"]
    assert (one["forward"], one["try_rate"], one["amount"], one["basis"]) == (form["forward"], 0.365, 3e6, "TRY")
    assert p["rows"][2]["trade"]["try_rate"] == 0.3625 and p["rows"][2]["trade"]["value_date"] == float(date_to_serial(dt.date(2027, 1, 15)))
    # English numbers when the user works in English
    en = svc.bulk_preview(u, "fwd", "B\t3,000,000\t36.50%\t15.12.2026", lang="en")["rows"][0]["trade"]
    assert (en["amount"], en["try_rate"]) == (3e6, 0.365)
    # each row with its own error, the others as they are
    bad = svc.bulk_preview(u, "fwd", "Parite\tYön\tTutar\tTL tutarı\tValör\tForward\n"
                                     "USDTRY\tX\t1m\t\t3M\t52\n"            # direction
                                     "USDTRY\tB\t1m\t52m\t3M\t52\n"         # two amounts
                                     "EURUSD\tB\t\t52m\t3M\t1,08\n"         # TRY on EURUSD
                                     "LIRA\tB\t1m\t\t3M\t52\n"              # no such pair
                                     "USDTRY\tB\t\t520m\t3M\t52\n")         # TRY typed: USD from the forward
    errors = [r.get("error", "") for r in bad["rows"]]
    assert "yön anlaşılamadı" in errors[0] and "ikisinden birini" in errors[1] and "TRY tutarı EURUSD paritesinde yok" in errors[2]
    assert "parite" in errors[3] and bad["rows"][4]["ok"] and bad["rows"][4]["trade"]["amount"] == 10e6
    # a mapping problem fails every row and says why
    nod = svc.bulk_preview(u, "fwd", "Yön\tTutar\nB\t1m")
    assert not nod["rows"][0]["ok"] and "Valör" in nod["rows"][0]["error"]
    # OIS and bonds, as the workbook's own lists have them
    o = svc.bulk_preview(u, "ois", "Nominal\tDV01 USD\tYön\tFaiz\tValör\tCPT\n\t1000\tS\t35,55%\t1Y\tBARX\n\t1000\tB\t35,47\t13M\tBARX\n")
    assert o["rows"][0]["ok"] and o["rows"][0]["trade"]["legs"][0]["dir"] == "S"
    assert o["rows"][0]["trade"]["legs"][0]["rate"] == pytest.approx(0.3555, abs=1e-15)
    assert "geçersiz vade" in o["rows"][1]["error"]
    bd = svc.bulk_preview(u, "bond", "TRT150328T24\t-20.000.000\t98,75\nTRT150328T24\t\t98,75\n")
    assert bd["rows"][0]["trade"]["amount"] == -20e6 and "tutar gerekli" in bd["rows"][1]["error"]
    assert svc.bulk_preview(u, "fwd", "")["rows"] == []
    with pytest.raises(ServiceError):
        svc.bulk_preview(u, "swap", FWD_PASTE)
    with pytest.raises(ServiceError) as exc:
        svc.bulk_preview(None, "fwd", FWD_PASTE)
    assert exc.value.status == 401


def test_the_valid_rows_are_kept_in_one_transaction(desk, monkeypatch):
    svc, u, _, _ = desk
    before = len(svc.blotter(u)["trades"])
    # a line the preview showed as valid that is not valid now: nothing is kept
    with pytest.raises(ServiceError) as exc:
        svc.bulk_save(u, "fwd", FWD_PASTE, rows=[2, 3, 4])
    assert exc.value.status == 409 and exc.value.data["preview"]["valid"] == 2 and "3. satır" in str(exc.value)
    assert len(svc.blotter(u)["trades"]) == before
    # a failure while writing: none of them
    real, calls = svc.store.add_trade, []

    def failing(*a, **kw):
        calls.append(a)
        if len(calls) == 2:
            raise sqlite3.OperationalError("disk dolu")
        return real(*a, **kw)

    monkeypatch.setattr(svc.store, "add_trade", failing)
    with pytest.raises(sqlite3.OperationalError):
        svc.bulk_save(u, "fwd", FWD_PASTE, rows=[2, 4])
    monkeypatch.setattr(svc.store, "add_trade", real)
    assert len(calls) == 2 and len(svc.blotter(u)["trades"]) == before
    # the two good ones, together; the bad one is said, not kept
    gen = svc.gen
    res = svc.bulk_save(u, "fwd", FWD_PASTE, rows=[2, 4])
    assert (res["saved"], res["rows"], res["left"], [e["n"] for e in res["errors"]]) == (2, [2, 4], [3], [3]) and svc.gen > gen
    trades = svc.blotter(u)["trades"]
    assert len(trades) == before + 2
    new = [t for t in trades if t["id"] in res["ids"]]
    assert [(t["dir"], t["amount"], t["try_rate"], t["typed"]) for t in new] == [("B", 3e6, pytest.approx(0.365, abs=1e-15), "base"),
                                                                                ("B", 1e6, pytest.approx(0.3625, abs=1e-15), "base")]
    assert all(t["created_by"] == u and t["kind"] == "fwd" for t in new)
    assert ("B", 3e6, new[0]["try_rate"], VALUE_SERIAL) in sheet_rows(svc)      # the workbook's sheet has them
    # without the lines of a preview (a script): every valid row, the errors listed
    res = svc.bulk_save(u, "bond", "Enstrüman\tTutar\tFiyat\tYön\nTRT150328T24\t20m\t98,75\tS\nTRT150328T24\t5m\t0\tB\n")
    assert res["saved"] == 1 and res["errors"][0]["n"] == 3 and "fiyat gerekli" in res["errors"][0]["error"]
    (bond,) = [t for t in svc.blotter(u)["trades"] if t["id"] in res["ids"]]
    assert (bond["amount"], bond["price"]) == (-20e6, 98.75) and bond["name"] and bond["dv01"] > 0       # a sale gains when rates rise
    with pytest.raises(ServiceError) as exc:
        svc.bulk_save(u, "fwd", "Yön\tTutar\nB\t1m")
    assert "geçerli satır yok" in str(exc.value) and exc.value.data["preview"]["invalid"] == 1
    with pytest.raises(ServiceError):
        svc.bulk_save(u, "fwd", FWD_PASTE, rows=["iki"])


def test_pasted_ois_rows_are_legs_of_the_form(desk):
    svc, u, _, _ = desk
    m = svc.ois_market(u)["mpc"]
    text = ("Yön\tVade\tBaşlangıç\tBitiş\tOran\tDV01\tNominal\tKarşı taraf\n"
            "RECEIVE\t1Y\t\t\t35,60\t2000\t\tXYZ\n"
            "PAY\t\t%s\t%s\t35,90\t\t\t\n"
            "PAY\t2Y\t\t\t34\t1000\t500m\t\n" % (m["dates"][0]["text"], m["dates"][1]["text"]))
    res = svc.bulk_save(u, "ois", text)
    assert res["saved"] == 3
    legs = {t["id"]: t for t in svc.blotter(u)["trades"] if t["id"] in res["ids"]}
    one, mpc, two = (legs[i] for i in res["ids"])
    form = svc.quote_ois(u, {"strategy": "outright", "side": "RECEIVE", "tenor": "1Y", "level": "35,60", "dv01": "2000"})
    assert (one["dir"], one["tenor"], one["nominal"], one["cpt"]) == ("S", "1Y", form["legs"][0]["nominal"], "XYZ")
    assert one["rate"] == form["legs"][0]["rate"] == pytest.approx(0.356, abs=1e-15)
    assert mpc["strategy"] == "mpc" and mpc["mpc"]["start"] == m["dates"][0]["date"] and mpc["dir"] == "B"
    assert two["nominal"] == 500e6                                              # the nominal written, not the DV01 beside it


# ---------------------------------------------------------------------------------------------- a database of the earlier version
#: the tables the blotter keeps, as the version before these features made them
OLD_TABLES = """
CREATE TABLE users (name TEXT PRIMARY KEY, display TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT NOT NULL, kind TEXT NOT NULL, package TEXT,
    payload TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX trades_date ON trades (trade_date, deleted);
CREATE TABLE blotter_snapshots (trade_date TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def test_a_database_of_the_earlier_version_opens_with_its_trades(tmp_path):
    day = "2026-11-02"
    fwd = {"pair": "USDTRY", "dir": "B", "amount": 10e6, "value_date": VALUE_SERIAL, "basis": "RET_MID", "manual": None, "days": 43.0,
           "spot": 42.3, "usd_rate": 0.039, "try_rate": 0.385, "forward": 44.2, "points": 19000.0, "tl": 442e6, "df_try": 0.96,
           "df_usd": 0.995, "usdtry": 42.3, "cpt": "ABC", "note": "eski", "dv01_tl": 52000.0, "dv01": 1229.3, "usd_dv01": -1190.0}
    ois = {"dir": "S", "tenor": "1Y", "rate": 0.356, "dv01": 2000.0, "nominal": 812e6, "cpt": "XYZ", "role": "outright", "strategy": "outright",
           "label": "RECEIVE 1Y @ 35,6000%", "level": 0.356, "side": "RECEIVE", "cost_bp": 1.0, "cost_usd": 2000.0, "market": 0.3561, "note": ""}
    bond = {"instrument": "TRT150328T24", "amount": 50e6, "price": 98.25, "note": "", "dv01_tl": -25000.0, "dv01": -591.0, "name": None}
    path = tmp_path / "tto.db"
    old = sqlite3.connect(str(path))
    old.executescript(OLD_TABLES)
    old.execute("INSERT INTO users VALUES ('eski', 'Eski Kullanıcı', '2026-01-01 09:00:00', '2026-11-02 09:00:00')")
    for kind, payload in (("fwd", fwd), ("ois", ois), ("bond", bond)):
        old.execute("INSERT INTO trades (trade_date, kind, package, payload, created_by, created_at, updated_by, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)", (day, kind, None, json.dumps(payload, ensure_ascii=False), "eski", day + " 10:00:00",
                                                 "eski", day + " 10:00:00"))
    old.commit()
    stored = [r[0] for r in old.execute("SELECT payload FROM trades ORDER BY id")]
    old.close()
    svc = make_service(tmp_path)
    try:
        data = svc.blotter("eski", day)
        assert [t["kind"] for t in data["trades"]] == ["fwd", "ois", "bond"] and data["templates"] == []
        f = data["trades"][0]
        assert (f["amount"], f["tl"], f["dv01"], f["cpt"], f["note"]) == (10e6, 442e6, 1229.3, "ABC", "eski") and "typed" not in f
        assert data["cost"]["fwd"][0]["buy"] == 10e6 and data["risk"]["fwd"] == 1229.3 and data["risk"]["ois"] == -2000.0
        lst = read_xlsx(svc.blotter_export("eski", day)[0])["İşlem listesi"]
        assert (lst["D6"], lst["I6"], lst["R6"], lst["S6"]) == (10e6, 442e6, 10e6, "USD")          # typed in USD, as every forward was
        # the new parts work on it, and what was there is as it was
        tid = svc.save_trade_template("eski", "Eski şablon", "fwd", {"dir": "B", "amount": "10m"})["saved"]
        assert [t["id"] for t in svc.trade_templates("eski")["templates"]] == [tid]
        t = svc.add_forward("eski", {"dir": "S", "value_date": VALUE, "basis": "FWD", "manual": "52", "quote_amount": "520m"})
        assert (t["amount"], t["typed"]) == (10e6, "quote")
        assert [r["payload"] for r in svc.store._q("SELECT payload FROM trades WHERE trade_date=? ORDER BY id", (day,))] == stored
        assert svc.store.quick_check() == []
    finally:
        svc.stop()


# ---------------------------------------------------------------------------------------------- over HTTP (last: the client stops the service)
def test_over_http(desk):
    svc, u, other, admin = desk
    hdr, adm = auth(svc, u), auth(svc, admin)
    with TestClient(create_app(svc)) as client:
        res = client.post("/api/blotter/quote/forward", json={"value_date": VALUE, "basis": "FWD", "manual": "52", "quote_amount": "520m"}, headers=hdr)
        assert res.status_code == 200 and (res.json()["amount"], res.json()["tl"], res.json()["typed"]) == (10e6, 520e6, "quote")
        made = client.post("/api/blotter/templates", json={"name": "HTTP", "kind": "fwd", "spec": {"pair": "EURTRY", "dir": "B"}}, headers=hdr)
        assert made.status_code == 200
        tid = made.json()["saved"]
        assert tid in [t["id"] for t in client.get("/api/blotter/templates", headers=hdr).json()["templates"]]
        renamed = client.post("/api/blotter/templates/%d" % tid, json={"name": "HTTP 2"}, headers=hdr).json()
        assert [t for t in renamed["templates"] if t["id"] == tid][0]["spec"] == {"kind": "fwd", "pair": "EURTRY", "dir": "B"}
        assert client.post("/api/blotter/templates", json={"name": "Masa", "kind": "fwd", "spec": {"dir": "B"}, "shared": True},
                           headers=hdr).status_code == 403
        assert client.post("/api/blotter/templates", json={"name": "Masa", "kind": "fwd", "spec": {"dir": "B"}, "shared": True},
                           headers=adm).json()["templates"][-1]["shared"]
        assert client.delete("/api/blotter/templates/%d" % tid, headers=auth(svc, other)).status_code == 404
        assert client.delete("/api/blotter/templates/%d" % tid, headers=hdr).status_code == 200
        assert client.get("/api/blotter/templates", headers={"Authorization": ""}).status_code == 401
        p = client.post("/api/blotter/bulk/preview", json={"kind": "fwd", "text": FWD_PASTE}, headers=hdr).json()
        assert [r["ok"] for r in p["rows"]] == [True, False, True]
        stale = client.post("/api/blotter/bulk", json={"kind": "fwd", "text": FWD_PASTE, "rows": [2, 3]}, headers=hdr)
        assert stale.status_code == 409 and stale.json()["preview"]["valid"] == 2
        saved = client.post("/api/blotter/bulk", json={"kind": "fwd", "text": FWD_PASTE, "rows": [2, 4]}, headers=hdr).json()
        assert saved["saved"] == 2 and saved["errors"][0]["n"] == 3
        en = client.post("/api/blotter/bulk/preview?lang=en", json={"kind": "fwd", "text": "B\t3,000,000\t36.5%\t15.12.2026"}, headers=hdr).json()
        assert en["rows"][0]["trade"]["amount"] == 3e6
