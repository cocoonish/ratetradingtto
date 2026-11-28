"""Fiyatlama, 28.11.2026 - the desk: "Bir de fiyatlama kisminda forward gelsin istiyorum. Oraya yazdigimda forward fiyatlamak
icin de isimi kolaylastiracak bir sey olmali. Vadeleri rahat gorup, rette veya diger curvelerde ne oldugunu vs rahat
gorebilecegim bir sey olmali. Fiyatladiktan sonra bunu done diye gunluk islemlere alabilmeliyim veya done olmadiysa da hit
ratiosunu takip edebilmeliyim." - and from the list (C3, A1):

* the forward card: every source at the value date by its own rule - OIS + spread is FORWARD KOTASYON's own row (a
  matrix row at that date as the user sees it, else the matrix's formulas evaluated at the date in a layer of the engine:
  the same numbers as a row typed there, nothing of the user's changed), RET its bid / ask at the date, the offshore
  market the FX swap implied bid / ask (and Fiyatlama's own offshore mid), VİOP a contract expiring near the date; each
  one's difference to the source picked; the ladder (tenors, PPK meetings, the value date); the quote copied and logged;
* "Bu işlemi hedge'le": each OIS bucket's opposite TRY OIS by OIS_MAIN's rule (none for offshore);
* "Pozisyona ekle (deneme)": DV01 Risk's buckets + the instrument, by the sheet's own formulas - nothing saved;
* "İşlem gir": the instrument (and each Toplu line) as Günlük İşlemler's / Trades' forms take it."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import pricing as pr
from tto.server import create_app
from tto.xl.values import serial_to_date


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def fx(svc, user, **fields):
    d = svc.pricing(user, dict({"asset": "fx", "pair": "USDTRY", "side": "AL", "size_kind": "amount", "size": "10m",
                                "price": "", "source": "ois"}, **fields))
    assert "error" not in d, d.get("error")
    return d


def src(card, sid):
    return next(s for s in card["sources"] if s["id"] == sid)


def row(svc, user, r, cols="CDEFGHIJKLMNORSVW"):
    return {c: cell(svc, "EK_FWD!%s%d" % (c, r), user) for c in cols}


# ================================================================================================== the forward card
def test_at_a_matrix_row_s_date_the_card_is_forward_kotasyon_s_row(svc):
    u = svc.login("Fwd Kart Satır")["user"]
    d = fx(svc, u, end="3M")
    card = d["card"]
    w = row(svc, u, 7)                                                   # (EK_FWD row 7: the matrix's 3M)
    assert card["valor"] == cell(svc, "EK_FWD!B7", u) and card["days"] == w["C"] and card["picked"] == "ois"
    o = src(card, "ois")
    assert o["row"] == "3M" and (o["fwd"]["bid"], o["fwd"]["ask"]) == (w["J"], w["K"]) and (o["pts"]["bid"], o["pts"]["ask"]) == (w["H"], w["I"])
    assert o["try"]["bid"] == w["M"] / 100 and o["try"]["ask"] == w["N"] / 100
    # RET: its bid / ask at the date (RET's rule), the forward the matrix's formula on each side's spot
    r = src(card, "ret")
    assert (r["try"]["bid"], r["try"]["ask"]) == (w["R"] / 100, w["S"] / 100)
    assert r["fwd"]["bid"] == pr.fwd_outright(w["F"], w["R"], w["O"], w["C"]) and r["fwd"]["ask"] == pr.fwd_outright(w["G"], w["S"], w["O"], w["C"])
    assert r["pts"]["bid"] == (r["fwd"]["bid"] - w["F"]) * 10000
    # the offshore market: the FX swap implied bid / ask at the date (OIS + the matrix's market spread), the mid the page's own
    off = src(card, "off")
    assert off["implied"] and off["try"]["bid"] == (w["L"] + w["V"] / 100) / 100 and off["try"]["ask"] == (w["L"] + w["W"] / 100) / 100
    assert off["fwd"]["bid"] == pr.fwd_outright(w["F"], w["L"] + w["V"] / 100, w["O"], w["C"])
    assert off["fwd"]["mid"] == d["mid"][d["methods"][0]] and off["pts"]["mid"] == pytest.approx(d["fx"]["points"][d["methods"][0]], abs=1e-9)
    # each source's difference to the one picked
    assert o["diff"]["pts"] == {"bid": 0.0, "ask": 0.0, "mid": 0.0}
    assert r["diff"]["bp"]["bid"] == pytest.approx((r["try"]["bid"] - o["try"]["bid"]) * 10000, abs=1e-9)
    assert off["diff"]["pts"]["ask"] == pytest.approx(off["pts"]["ask"] - o["pts"]["ask"], abs=1e-9)
    # the deal the picked source gives: AL at the bid (the desk buys USD at its bid), on the bid's spot
    assert card["deal"] == {"side": "AL", "dir": "B", "level_side": "bid", "level": w["J"], "spot": w["F"], "amount": 10e6}
    assert fx(svc, u, side="SAT")["card"]["deal"]["level"] == w["K"]


def test_at_a_broken_date_the_card_is_the_matrix_formulas_at_that_date_and_nothing_of_the_user_s_changes(svc):
    """A date no row of the matrix has: the matrix's own formulas at that date (a layer over the user's calculation) - the
    same numbers as another user's row with that date typed in; the user's own matrix as it was, nothing stored."""
    u = svc.login("Fwd Kart Kırık")["user"]
    other = svc.login("Fwd Kart Elle")["user"]
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B12", "value": "20.04.2027"}])      # (a free row of the user's in use)
    stored = dict(svc.store.user_inputs(u, "tto"))
    card = fx(svc, u, end="15.03.2027")["card"]
    svc.set_inputs(other, "tto", [{"ref": "EK_FWD!B11", "value": "15.03.2027"}])
    w = row(svc, other, 11)
    o = src(card, "ois")
    assert not o.get("row") and card["days"] == w["C"] and o["spread"] == {"bid": w["D"], "ask": w["E"]}
    for side, f, t, p in (("bid", "J", "M", "H"), ("ask", "K", "N", "I")):
        assert o["fwd"][side] == pytest.approx(w[f], rel=1e-14) and o["try"][side] == pytest.approx(w[t] / 100, rel=1e-14)
        assert o["pts"][side] == pytest.approx(w[p], abs=1e-6)
    assert src(card, "ret")["try"]["bid"] == pytest.approx(w["R"] / 100, rel=1e-14)
    assert src(card, "off")["try"]["ask"] == pytest.approx((w["L"] + w["W"] / 100) / 100, rel=1e-14)
    # nothing of the user's changed: their row, their stored inputs; the layers of the card are the engine's, kept per user
    assert serial_to_date(cell(svc, "EK_FWD!B12", u)) == dt.date(2027, 4, 20)
    assert dict(svc.store.user_inputs(u, "tto")) == stored
    assert cell(svc, "EK_FWD!B11", u) in (None, "")
    book = svc.books["tto"]
    assert (u, "pricing-fwd", 0) in book.engine.layers
    # (keyed by the user first, as every user's layer: the idle sweep and copies.drop give them back with the user)
    assert not [k for k in book.engine.layers if isinstance(k, tuple) and k and k[0] in ("pricing-fwd", "pricing-trial")]
    svc.pricing(u, {"asset": "ois"})                                             # (another instrument: the layers go)
    assert not [k for k in book.engine.layers if k[:2] == (u, "pricing-fwd")]


def test_with_every_row_typed_into_the_card_applies_the_matrix_rule_itself(svc):
    """A user whose every matrix row holds a spread of its own (no row is the matrix as it is at another date): the date's
    own numbers (OIS rate, RET, market spread, days) from a row in a layer, the rule - OIS + the general spread - applied
    to them; the same numbers as a row typed only with that date."""
    u = svc.login("Fwd Kart Hep Yazılı")["user"]
    other = svc.login("Fwd Kart Yalnız Tarih")["user"]
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!D%d" % r, "value": "-120"} for r in range(5, 15)])
    card = fx(svc, u, end="15.03.2027")["card"]
    svc.set_inputs(other, "tto", [{"ref": "EK_FWD!B11", "value": "15.03.2027"}])
    w = row(svc, other, 11)
    o = src(card, "ois")
    assert "row" not in o and o["spread"] == {"bid": cell(svc, "EK_FWD!D4", u), "ask": cell(svc, "EK_FWD!E4", u)}
    for side, f, t in (("bid", "J", "M"), ("ask", "K", "N")):
        assert o["fwd"][side] == pytest.approx(w[f], rel=1e-14) and o["try"][side] == pytest.approx(w[t] / 100, rel=1e-14)
    # its own 3M row stays its own: the spread typed there
    three = src(fx(svc, u, end="3M")["card"], "ois")
    assert three["row"] == "3M" and three["try"]["bid"] == pytest.approx(cell(svc, "EK_FWD!L7", u) / 100 - 0.012, abs=1e-12)


def test_the_spread_rule_market_mode_and_a_row_s_own_spread(svc):
    u = svc.login("Fwd Kart Piyasa")["user"]
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B4", "value": "Piyasa spread"}])
    card = fx(svc, u, end="15.03.2027")["card"]
    o, off = src(card, "ois"), src(card, "off")
    assert card["mode"] == "Piyasa spread" and o["try"]["bid"] == pytest.approx(off["try"]["bid"], rel=1e-14)
    assert o["fwd"]["ask"] == pytest.approx(off["fwd"]["ask"], rel=1e-14)
    v = svc.login("Fwd Kart Spread")["user"]
    svc.set_inputs(v, "tto", [{"ref": "EK_FWD!D7", "value": "-100"}])            # (the 3M row's own bid spread)
    o = src(fx(svc, v, end="3M")["card"], "ois")
    assert o["row"] == "3M" and o["try"]["bid"] == pytest.approx(cell(svc, "EK_FWD!L7", v) / 100 - 0.01, abs=1e-12)
    assert o["try"]["ask"] == pytest.approx((cell(svc, "EK_FWD!L7", v) + cell(svc, "EK_FWD!E4", v) / 100) / 100, abs=1e-12)


def test_the_ladder_the_tenors_and_the_ppk_meetings_around_the_value_date(svc):
    u = svc.login("Fwd Kart Merdiven")["user"]
    card = fx(svc, u, end="4M")["card"]
    lad = card["ladder"]
    days = [r["date"] for r in lad]
    assert days == sorted(days) and len(set(days)) == len(days)
    tenors = {lab: r["date"] for r in lad for lab, k in zip(r["labels"], r["kinds"]) if k == "tenor"}
    assert list(tenors)[:8] == ["1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y"]
    for lab, r in zip(("1M", "2M", "3M", "6M", "9M", "1Y"), range(5, 11)):         # (the matrix's own rows' dates)
        assert tenors[lab] == cell(svc, "EK_FWD!B%d" % r, u)
    valor = [r for r in lad if "valor" in r["kinds"]]
    assert len(valor) == 1 and valor[0]["date"] == card["valor"] and tenors["3M"] < card["valor"] < tenors["6M"]
    meetings = [cell(svc, "Motor!B%d" % k, u) for k in range(5, 85)]
    meetings = [m for m in meetings if isinstance(m, float) and card["spot_date"] < m <= tenors["1Y"]]
    got = [r["date"] for r in lad if "mpc" in r["kinds"]]
    assert got == meetings and len(got) >= 4 and all(r["mpc"].startswith("MPC") for r in lad if "mpc" in r["kinds"])
    one = next(r for r in lad if "mpc" in r["kinds"])
    assert one["label"].startswith("PPK ") and one["by"]["ois"]["try"]["mid"] > 0 and one["by"]["ret"]["pts"]["mid"] > 0
    # past 1Y the ladder goes to the first tenor past the value date
    far = fx(svc, u, end="20M")["card"]["ladder"]
    assert [x for r in far for x in r["labels"] if x in ("18M", "2Y")] == ["18M", "2Y"]


def test_viop_when_a_contract_expires_near_the_value_date(svc):
    u = svc.login("Fwd Kart VİOP")["user"]
    card = fx(svc, u, end="29.01.2027")["card"]
    v = src(card, "viop")
    assert v["available"] and v["contract"]["name"] == "A1F7" and v["gap"] == 0
    assert v["try"]["bid"] == cell(svc, "VIOP!O13", u) and v["try"]["ask"] == cell(svc, "VIOP!O25", u)
    assert v["contract"]["px_bid"] == cell(svc, "VIOP!O16", u) and v["contract"]["expiry"] == cell(svc, "VIOP!O9", u)
    w = card["spot"]
    assert v["fwd"]["bid"] == pr.fwd_outright(w["bid"], v["try"]["bid"] * 100, card["ccy_rate"] * 100, card["days"])
    near = fx(svc, u, end="03.02.2027")["card"]                  # (5 days past A1F7's expiry: still near)
    assert src(near, "viop")["contract"]["name"] == "A1F7" and src(near, "viop")["gap"] == -5
    far = fx(svc, u, end="15.12.2026")["card"]                  # (15 / 16 days from the two around it)
    assert not src(far, "viop")["available"] and "7 günden yakın" in src(far, "viop")["why"]
    # the source picked is kept per user; one not there falls back to OIS + spread
    assert fx(svc, u, end="29.01.2027", source="viop")["card"]["picked"] == "viop"
    back = fx(svc, u, end="15.12.2026", source="viop")["card"]
    assert back["picked"] == "ois" and back["asked"] == "viop"
    assert svc.pricing(u)["inputs"]["by"]["fx"]["source"] == "viop"
    eur = fx(svc, u, pair="EURTRY", end="3M", source="ois")["card"]
    assert eur["pair"] == "EURTRY" and not src(eur, "viop")["available"]
    assert src(eur, "ois")["row"] == "3M" and src(eur, "ois")["fwd"]["bid"] == cell(svc, "EK_FWD!J106", u)
    fx(svc, u, pair="USDTRY")


def test_the_card_s_quote_is_copied_and_logged(svc):
    u = svc.login("Fwd Kart Kota")["user"]
    fx(svc, u, end="3M", source="ret")
    q = svc.pricing_quote(u, {"client": "Garanti", "language": "tr"})
    card = q["card"]
    r = src(card, "ret")
    lines = q["text"].split("\n")
    assert lines[0] == "USDTRY forward 3M · %s · bid / ask" % dt.date.today().strftime("%d.%m.%Y")
    assert lines[1].split("  ")[-1].strip() == "RET" and "Outright" in q["text"] and "Tutar        10.000.000 USD" in q["text"]
    out = next(x for x in lines if x.startswith("Outright"))
    assert out.endswith("%s / %s" % (("%.4f" % r["fwd"]["bid"]).replace(".", ","), ("%.4f" % r["fwd"]["ask"]).replace(".", ",")))
    rec = q["quote"]
    assert rec["status"] == "open" and rec["client"] == "Garanti" and rec["product"] == "FX forward" and rec["side"] == "AL"
    assert (rec["levels"]["bid"], rec["levels"]["ask"]) == (r["fwd"]["bid"], r["fwd"]["ask"]) and rec["level"] == r["fwd"]["bid"]
    assert rec["value_date"] == serial_to_date(card["valor"]).isoformat() and rec["size"] == 10e6 and rec["text"] == q["text"]
    assert svc.pricing(u)["inputs"]["by"]["fx"]["client"] == "Garanti"            # (the client kept with the card)
    en = svc.pricing_quote(u, {"language": "en", "status": "not_done"})
    assert en["text"].startswith("USDTRY forward 3M · ") and "Source" in en["text"] and en["quote"]["status"] == "not_done"
    hit = svc.quote_log(u)["hit"]
    g = next(x for x in hit["by_client"] if x["key"] == "Garanti")
    assert g["quotes"] >= 2 and g["not_done"] >= 1


# ================================================================================================== hedge, trial
def test_each_bucket_s_hedge_by_ois_main_s_rule(svc):
    u = svc.login("Fiyatlama Hedge")["user"]
    d = svc.pricing(u, {"asset": "ois", "start": "", "end": "2Y3M", "side": "PAY", "size_kind": "dv01", "size": "1000", "price": ""})
    hd = d["hedges"]
    m = d["methods"][0]
    lot = hd["lot"]
    assert hd["family"] == "ois" and [r["bucket"] for r in hd["rows"]] == ["2Y", "3Y"] and lot > 0
    two = svc.pricing(u, {"end": "2Y"})                                     # (the hedge: a spot TRY OIS of the bucket's tenor)
    for r in hd["rows"]:
        dv = next(b for b in d["buckets"]["rows"] if b["name"] == r["bucket"])["dv01"][m]
        assert r["dv01"] == dv and r["side"] == "RECEIVE" and r["nominal"] % lot == 0 and r["nominal"] > 0
        assert r["quote"] == next(b for b in d["buckets"]["rows"] if b["name"] == r["bucket"])["quote"]
        assert abs(r["nominal"] - dv * hd["usdtry"] / (r["annuity"] * 1e-4)) <= lot / 2
        assert r["hedge_dv01"] == pytest.approx(-r["nominal"] * r["annuity"] * 1e-4 / hd["usdtry"], rel=1e-12)
        assert r["left"] == pytest.approx(dv + r["hedge_dv01"], abs=1e-9)
    assert hd["rows"][0]["annuity"] == pytest.approx(two["annuity"][m], rel=1e-12)
    fra = svc.pricing(u, {"asset": "fra", "start": "12", "end": "15", "side": "PAY", "size_kind": "dv01", "size": "1000"})["hedges"]
    assert {r["side"] for r in fra["rows"]} == {"PAY", "RECEIVE"}
    x = svc.pricing(u, {"asset": "xccy", "end": "2Y"})["hedges"]
    assert x["rows"] == [] and "offshore ≠ OIS" in x["text"]


def test_pozisyona_ekle_deneme_dv01_risk_before_and_after_nothing_saved(svc):
    u = svc.login("Fiyatlama Deneme")["user"]
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!C16", "value": "500"}])          # (a position pasted: 1Y)
    stored = dict(svc.store.user_inputs(u, "tto"))
    d = svc.pricing(u, {"asset": "ois", "start": "", "end": "2Y3M", "side": "PAY", "size_kind": "dv01", "size": "1000"})
    t = svc.pricing_trial(u)
    m = d["methods"][0]
    assert t["available"] and t["family"] == "ois" and t["sign"] == 1.0 and t["columns"] == "TLREF + Pozisyon" and not t["saved"]
    assert t["deal_total"] == pytest.approx(d["buckets"]["total"][m] * d["usdtry"], rel=1e-9)
    assert t["total"]["before"] == 500 and t["total"]["after"] == pytest.approx(500 + t["deal_total"], rel=1e-12)
    b = {r["name"]: r for r in t["buckets"]}
    assert b["1Y"]["before"] == 500 and b["2Y"]["deal"] > 0 and b["3Y"]["deal"] > 0
    assert b["2Y"]["after"] == pytest.approx(b["2Y"]["before"] + b["2Y"]["deal"])
    var = {r["name"]: r for r in t["var"]}
    assert var["OIS (TLREF)"]["dv01_after"] - var["OIS (TLREF)"]["dv01"] == pytest.approx(t["deal_total"])
    assert var["Offshore"]["dv01_after"] == var["Offshore"]["dv01"]
    mpc1 = next(r for r in t["ppk"] if r["name"] == "MPC1")
    assert mpc1["decision_after"] != mpc1["decision"] and mpc1["pnl25_after"] == pytest.approx(mpc1["decision_after"] * 25)
    # nothing saved: the user's inputs and the page's cells as they were, the layer given back
    assert dict(svc.store.user_inputs(u, "tto")) == stored and cell(svc, "DV01_RISK!C26", u) == 500
    assert cell(svc, "DV01_RISK!Y45", u) in (0, 0.0, None)
    assert (u, "pricing-trial") not in svc.books["tto"].engine.layers
    # an offshore instrument: the Offshore column only - never OIS: the position and its PPK risk as they were
    svc.pricing(u, {"asset": "xccy", "end": "2Y", "side": "PAY"})
    x = svc.pricing_trial(u)
    xv = {r["name"]: r for r in x["var"]}
    assert x["columns"] == "Offshore" and x["total"]["after"] == x["total"]["before"] == 500
    assert xv["Offshore"]["dv01_after"] - xv["Offshore"]["dv01"] == pytest.approx(x["deal_total"]) and x["deal_total"] != 0
    assert all(r["decision_after"] == r["decision"] for r in x["ppk"])


def test_dv01_risk_s_buckets_take_a_pillar_by_name_or_split_by_days():
    buckets = [("ON", 1.0), ("1M", 30.0), ("1Y", 365.0), ("2Y", 730.0)]
    got = pr.to_buckets([("1M", 30.0, 10.0), ("XCCY 2Y", 731.0, 4.0), ("18M", 547.5, 6.0), ("TRYI 1W", 7.0, 2.0)], buckets)
    assert got[1] == pytest.approx(10.0 + 2.0 * 6 / 29) and got[0] == pytest.approx(2.0 * 23 / 29)
    assert got[2] == pytest.approx(3.0) and got[3] == pytest.approx(4.0 + 3.0) and sum(got) == pytest.approx(22.0)
    assert pr.bucket_name("TRYI 1M") == "1M" and pr.bucket_name("XCCY 10Y") == "10Y" and pr.bucket_name("2y") == "2Y"


# ================================================================================================== İşlem gir
def test_the_instrument_as_the_forms_take_it(svc):
    u = svc.login("Fiyatlama İşlem Gir")["user"]
    d = svc.pricing(u, {"asset": "ois", "start": "", "end": "1Y", "side": "RECEIVE", "size_kind": "dv01", "size": "1000", "price": ""})
    t = d["trade"]
    m = d["methods"][0]
    assert t["blotter"] == {"kind": "ois", "side": "RECEIVE", "level": d["mid"][m], "size": 1000.0, "sizeMode": "dv01",
                            "strategy": "outright", "tenors": ["1Y"]}
    assert t["trades"] == {"product": "ois", "side": "receive", "price": d["mid"][m], "dv01": 1000.0, "structure": "outright",
                           "end_date": "1Y"} and t["level_from"] == "mid"
    d = svc.pricing(u, {"end": "2Y3M", "price": "38,5", "size_kind": "nominal", "size": "100m"})
    t = d["trade"]
    assert t["level"] == pytest.approx(0.385) and t["level_from"] == "fiyat" and t["blotter"]["sizeMode"] == "nominal"
    assert t["blotter"]["tenors"] == [serial_to_date(d["end"]).strftime("%d.%m.%Y")] and t["trades"]["notional"] == 1e8
    d = svc.pricing(u, {"asset": "fra", "start": "12", "end": "15", "side": "PAY", "price": ""})
    assert d["trade"]["blotter"]["strategy"] == "fra" and d["trade"]["blotter"]["months"] == [12, 15]
    assert d["trade"]["trades"]["fra"] == "12x15" and d["trade"]["trades"]["structure"] == "fra"
    d = svc.pricing(u, {"asset": "ois", "start": "04.05.2027", "end": "04.05.2028", "price": ""})
    days = [serial_to_date(d["start"]).strftime("%d.%m.%Y"), serial_to_date(d["end"]).strftime("%d.%m.%Y")]
    assert d["trade"]["blotter"]["months"] == days and [d["trade"]["trades"][k] for k in ("value_date", "end_date")] == days
    f = fx(svc, u, end="3M")
    assert f["trade"]["blotter"] == {"kind": "fwd", "pair": "USDTRY", "dir": "B", "date": serial_to_date(f["end"]).strftime("%d.%m.%Y"),
                                     "basis": "FWD", "value": f["mid"][f["methods"][0]], "amount": 10e6}
    assert f["trade"]["trades"] is None and "FX forward" in f["trade"]["why"]["trades"]
    x = svc.pricing(u, {"asset": "xccy", "end": "2Y"})
    assert x["trade"]["blotter"] is None and x["trade"]["trades"] is None and "XCCY" in x["trade"]["why"]["blotter"]
    # every Toplu line too
    b = svc.pricing(u, {"asset": "ois", "start": "", "end": "1Y", "bulk": "2Y\n12x15\n2Y 40"})["bulk"]["rows"]
    assert b[0]["trade"]["blotter"]["tenors"] == ["2Y"] and b[1]["trade"]["blotter"]["months"] == [12, 15]
    assert b[2]["trade"]["level"] == pytest.approx(0.40) and b[2]["trade"]["level_from"] == "fiyat"
    svc.pricing(u, {"bulk": ""})


def test_the_routes(svc):
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Fwd Kart HTTP")
        got = c.post("/api/pricing", json={"asset": "fx", "end": "3M", "pair": "USDTRY"}, headers=h).json()
        assert got["card"]["picked"] == "ois" and [s["id"] for s in got["card"]["sources"]] == list(pr.SOURCES)
        q = c.post("/api/pricing/quote", json={"client": "Akbank"}, headers=h)
        assert q.status_code == 200 and q.json()["quote"]["status"] == "open" and q.json()["text"].startswith("USDTRY forward 3M")
        assert c.post("/api/pricing/quote", json={"status": "belki"}, headers=h).status_code == 400
        t = c.get("/api/pricing/trial", headers=h).json()
        assert t["available"] and t["columns"] == "Offshore"
        assert c.post("/api/pricing", json={"asset": "ois"}, headers=h).json()["hedges"]["family"] == "ois"
        assert c.get("/api/pricing/trial", headers=h).json()["columns"] == "TLREF + Pozisyon"
        # the card's quote prices the FX forward kept; the page's instrument stays the one on screen
        assert c.post("/api/pricing/quote", json={"client": "Akbank"}, headers=h).json()["quote"]["pair"] == "USDTRY"
        assert c.get("/api/pricing", headers=h).json()["inputs"]["asset"] == "ois"
        assert c.get("/api/pricing/trial", headers=ANON).status_code == 401
        assert c.post("/api/pricing/quote", json={}, headers=ANON).status_code == 401
