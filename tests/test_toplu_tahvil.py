"""Toplu iş 28.11.2026, the bond side (K6) - the desk: "kagit kismi cok duzensiz ve her sey her yerde gibi"; to the lists
"A - Yildizlilari yap. B - Hepsini yap. C - 2-3-4-5-8-10-12-13-16" and the reorganization "Digerlerini de onayliyorum".

* **One home for the bond table** (R): DİBS Trading's summary has every column DİBS RV · Genel's table had (the clean price
  in use, the simple yield, each fitted ASW curve's ASW, the zero-coupon curve's model yield / cheap-rich / fair price, the
  OIS hedge ratio), in one order - Kâğıt · Valör · Fiyat · Getiri · ASW · Eğri · Adil · Ucuz / pahalı · Sinyal · Sıfır kupon ·
  Risk · Carry · Broker -, each measure with its curves side by side, read three ways under "Sütunlar" (Trading / RV / Risk /
  Tümü); Genel links to it; the same bond column on every bond table (the short name, its ISIN in the tip, frozen, a click
  opens the card); the value date "T1 · 04.11"; UCUZ green, PAHALI red; bp whole.
* **B16** DİBS RV's results on the first screen, Ayarlar in two; Tüm Kâğıtlar' Tür, Kalan gün, Kaynak hidden by default.
* **B17** DİBS ASW's two ASW charts side by side, its history a full-width bar; Hazine İhalesi's empty Kâğıt 2 / 3 folded to
  their ISIN row, the inputs first.
* **C10** the quote ticket at any value date (the bond card's Kâğıt Fiyatlama block: ``/api/kagit-fiyat?ticket=1``; Manuel
  Tahvil: the sheet's own block).
* **C12** Tüm Kâğıtlar: every bond's yield (Kâğıt Fiyatlama's snapshot).
* **C13** Kâğıt Fiyatlama's fair / AL / SAT as alarm names.
* **A14** the desk's quote copy (Kâğıt Fiyatlama, Manuel Tahvil, DİBS RV).

(The pages in the browser: tests/e2e/e2e.js, the "toplu tahvil" checks.)"""
from __future__ import annotations

import datetime as dt
import math
import random

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import bonds as bd
from tto import dibsgenel as dg
from tto import kagitfiyat as kf
from tto import pricing as pr
from tto import quantcurve as qc
from tto import tradehint as th
from tto.server import create_app
from tto.views import load_views
from tto.xl import numfmt
from tto.xl.tokenizer import col_to_index

FIXED, BILL, TLREF, OFF = "TRT150328T24", "TRB100227T13", "TRT090130T12", "TRT240227T17"
VIEWS = {v["id"]: v for v in load_views()}


def vpanel(view, pid):
    return next(p for p in VIEWS[view]["panels"] if p["id"] == pid)


def page_panel(svc, user, view, pid):
    p = next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)
    assert not p.get("error"), p.get("error")
    return p


def summary(svc, user):
    return page_panel(svc, user, "dibslive", "L0")["data"]


def summary_line(d, isin):
    row = next(row for row in d["rows"] if len(row) > 2 and row[2].get("t") == isin)
    return {key: c for key, c in zip(d["c"], row)}


def rv(svc, col, r, user=None):
    return cell(svc, "DİBS RV!%s%d" % (col, r), user)


def row_of(svc, isin):
    return next(r for r in range(5, 55) if rv(svc, "A", r) == isin)


def rv_text(svc, user, col, r):
    book = svc.books["tto"]
    si = book.model.sheet_index["DİBS RV"]
    loc = numfmt.get_locale("tr")
    return svc.et.call(lambda: svc.renderers["tto"].cell(svc._calc(user, book), si, r, col_to_index(col), loc)).get("t", "")


# ================================================================================================== one home for the bond table
def test_the_trading_summary_is_the_bond_tables_one_home(service):
    """DİBS Trading's summary in the desk's one order - each measure a group, OIS and FX side by side - with DİBS RV · Genel's
    columns moved in: the clean price in use, the simple yield, the fitted curves' ASW, the zero-coupon curve's three, the
    OIS hedge ratio.  Every column keeps its key (a user's hidden columns, a launchpad box); the new ones follow."""
    s = service
    u = s.login("Toplu Tahvil Ev")["user"]
    d = summary(s, u)
    groups = [c.get("t") for c in d["rows"][0] if not c.get("sk")]
    assert groups == ["", "Fiyat", "Getiri %", "ASW (bp)", "Eğri ASW (bp)", "Adil getiri %", "Adil fiyat", "Ucuz / pahalı (bp, + ucuz)",
                      "Sinyal", dg.ZERO_GROUP, "Risk", "Carry", "Broker", ""]
    caps = [c.get("t") for c in d["rows"][1]]
    assert caps[:14] == ["★", "Kâğıt", "ISIN", "Vade", "Kalan yıl", "Valör", "Bid", "Ask", "Son işlem", "Ne zaman", "Kullanılan temiz",
                         "Basit", "Bileşik", "ON karşılık"]
    assert caps[14:16] == ["OIS / DM", "FX"] and caps[16:26] == ["OIS", "FX"] * 5
    assert caps[26:29] == ["Model getiri % (basit)", "Ucuz / pahalı (bp)", "Adil fiyat"]
    # the keys: the first columns' letters, the 26.11 ones Y..AF, the 28.11 ones AG..AN - each where its caption is
    k = s._trading_keys()
    assert d["c"][:6] == ["A", "B", "C", "D", "E", "F"] and k["ycomp"] == "K" and k["ois_fy"] == "Y" and k["on"] == "AF"
    assert [k[x] for x in ("clean", "ysimple", "ois_curve", "fx_curve", "z_model", "z_rc", "z_fp", "hedge")] == \
        ["AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN"]
    assert sorted(d["c"]) == sorted(k.values()) and len(set(d["c"])) == len(d["c"]) == 40
    # each figure its source's: DİBS RV's own cells, the zero-coupon fit Genel draws (the same fit, kept)
    for isin in (FIXED, BILL, TLREF):
        r = row_of(s, isin)
        x = summary_line(d, isin)
        for key, col in (("clean", "O"), ("ysimple", "S"), ("ycomp", "T"), ("ois_asw", "Z"), ("hedge", "AJ"), ("dv01", "AI"), ("dur", "AG")):
            assert x[k[key]]["t"] == rv_text(s, u, col, r), (isin, key)
    loc = numfmt.get_locale("tr")
    got = s.et.call(lambda: s.dibsgenel._read(u, loc))
    rows = dg.fit_rows(s.dibsgenel.fit(got["quant"], got["live"], got["today"]))
    for isin in (FIXED, BILL):
        x = summary_line(d, isin)
        assert x[k["z_rc"]]["v"] == pytest.approx(rows[isin]["resid"], abs=1e-9)
        assert x[k["z_model"]]["v"] == pytest.approx(rows[isin]["model"] / 100.0, abs=1e-12)
        assert x[k["z_fp"]]["v"] == pytest.approx(rows[isin]["fair"]["clean"], abs=1e-12)
        assert x[k["z_rc"]]["t"] == ("%d" % round(rows[isin]["resid"])).replace("-", "-")          # (bp whole)
    # the OIS curve's ASW at the bond's years (DİBS RV's AA of a fixed coupon bond), the FX one whole bp
    assert summary_line(d, FIXED)[k["ois_curve"]]["v"] == pytest.approx(rv(s, "AA", row_of(s, FIXED)), abs=0.05)
    fx = summary_line(d, FIXED)[k["fx_asw"]]
    assert fx["t"] == "%d" % round(fx["v"]) or fx["t"] == "-%d" % round(-fx["v"])
    # a TLREF floater: not on the zero-coupon curve, said why
    x = summary_line(d, TLREF)
    assert x[k["z_rc"]]["t"] == "–" and "TLREF'e endeksli" in x[k["z_rc"]]["tip"]
    # the bond column: its short name, its ISIN in the tip, a link to its card; the value date "T1 · 04.11", ISL1 in the tip
    x = summary_line(d, FIXED)
    assert x["B"]["t"] == "15.03.28" and x["B"]["cls"] == "bondlink" and x["B"]["tip"].startswith(FIXED)
    assert x["F"]["t"] == "T1 · 04.11" and "ISL1" in x["F"]["tip"] and "04.11.2026" in x["F"]["tip"]
    assert summary_line(d, BILL)["F"]["t"] == "T0 · 03.11"                      # (a bill on ISL0: the same day)
    # UCUZ green, PAHALI red (Bugün's and Günlük İşlemler' buy / sell); the frozen ★ and Kâğıt
    signals = [summary_line(d, i)[k["ois_sig"]] for i in (FIXED, BILL, "TRT130928T38", "TRT021030T18")]
    assert all(("buy" in (c.get("cls") or "")) == (c["t"] == "UCUZ") and ("sell" in (c.get("cls") or "")) == (c["t"] == "PAHALI")
               for c in signals) and any(c["t"] in ("UCUZ", "PAHALI") for c in signals)
    assert vpanel("dibslive", "L0")["freeze"] == 2 and d.get("fz") == 2


def test_the_summary_is_read_three_ways_under_sutunlar(service):
    """Sütunlar → Görünüm: Trading (the live board: prices, yields, ASW, signal, DV01, carry, the brokers), RV (the curves,
    fair, cheap / rich, signals, the zero-coupon curve), Risk (duration, DV01, the nominals, the hedge, carry and repo), Tümü;
    a user who never chose sees Trading; a preset is a choice like any (kept with the account; one column back at a time)."""
    s = service
    u = s.login("Toplu Tahvil Sütun")["user"]
    k = s._trading_keys()
    got = s.columns(u)
    presets = got["presets"][s.TRADING_TABLE]
    assert [p["name"] for p in presets] == ["Trading", "RV", "Risk", "Tümü"]
    by = {p["name"]: set(p["hide"]) for p in presets}
    every = set(k.values())
    shown = {name: every - hide for name, hide in by.items()}
    assert by["Tümü"] == set() and got["defaults"][s.TRADING_TABLE] == presets[0]["hide"]
    for name in ("Trading", "RV", "Risk"):
        assert {k["star"], k["bond"], k["valor"], k["card"]} <= shown[name] and k["isin"] not in shown[name]
    assert {k[x] for x in ("bid", "ask", "last", "ycomp", "ois_asw", "fx_asw", "ois_sig", "fx_sig", "dv01", "cr", "bk0", "bk3")} <= shown["Trading"]
    assert {k[x] for x in ("ois_curve", "fx_curve", "ois_fy", "fx_fp", "ois_rc", "fx_rc", "z_model", "z_rc", "z_fp")} <= shown["RV"]
    assert not {k[x] for x in ("bid", "ask", "bk0")} & shown["RV"]
    assert {k[x] for x in ("dur", "dv01", "usd", "hedge", "cr", "repo", "clean")} <= shown["Risk"]
    assert not {k[x] for x in ("ois_fy", "z_rc", "bk0", "bid")} & shown["Risk"]
    # chosen: kept as the user's own hidden columns; "Tümü" (every column) stays chosen - the default does not come back
    s.set_columns(u, s.TRADING_TABLE, presets[1]["hide"])
    assert s.columns(u)["tables"][s.TRADING_TABLE] == presets[1]["hide"]
    s.set_columns(u, s.TRADING_TABLE, [])
    assert s.columns(u)["tables"][s.TRADING_TABLE] == [] and s.TRADING_TABLE not in s.columns(u).get("defaults", {})


def test_genel_links_to_the_one_home(service):
    """DİBS RV · Genel: the charts, the fit, the settings, the hesap tablosu's tables - and no table of its own: a link to
    DİBS Trading's summary (how many bonds of each kind, the RV view of it)."""
    s = service
    u = s.login("Toplu Tahvil Genel")["user"]
    d = s.dibsgenel.view(u)
    assert "table" not in d and d["fit"]["ok"] and d["chart"]["series"]
    t = d["trading"]
    assert (t["view"], t["panel"], t["preset"]) == ("dibslive", "L0", "RV") and t["n"] == 19
    assert [(x["kind"], x["n"]) for x in t["kinds"]] == [("B", 2), ("S", 14), ("T", 3)]
    # the settings: each in the panel it is in now (Ayarlar in two: B1 A2:L2, B1b M2:Z2)
    sets = {x["ref"]: x["panel"] for x in d["settings"]}
    assert sets == {"DİBS RV!P2": "B1b", "DİBS RV!J2": "B1", "DİBS RV!X2": "B1b", "DİBS RV!Z2": "B1b", "DİBS RV!B2": "B1"}


# ================================================================================================== the same bond column
def test_the_same_bond_column_on_every_bond_table(service):
    """The short name first and frozen, its ISIN in the tip, a click on it opens the card: DİBS RV (beside its ISIN, the
    input), DİBS Trading's value dates, Tüm Kâğıtlar (the ISIN hidden by default, as Tür, Kalan gün, Kaynak), DİBS ASW."""
    s = service
    u = s.login("Toplu Tahvil Kâğıt")["user"]

    def first(view, pid, n):
        p = page_panel(s, u, view, pid)
        return p["data"]["c"][:n], p["data"].get("fz"), p["data"]

    cols, fz, data = first("dibs", "B3", 3)
    assert cols == ["Kâğıt", "A", "B"] and fz == 2
    named = [row[0] for row, r in zip(data["rows"], data["r"]) if isinstance(r, int) and 5 <= r <= 54 and row[1].get("t")]
    assert named and all(c.get("cls") == "bondlink" and c["tip"].startswith(row) for c, row in
                         zip(named, [row[1]["t"] for row, r in zip(data["rows"], data["r"]) if isinstance(r, int) and 5 <= r <= 54 and row[1].get("t")]))
    assert any(c["t"] == "15.03.28" for c in named)
    cols, fz, data = first("dibslive", "L1", 2)
    assert cols == ["B", "A"] and fz == 2
    cols, fz, data = first("kagitlar", "U1", 2)
    assert cols == ["B", "A"] and fz == 2
    bond = next(row for row in data["rows"] if len(row) > 1 and row[1].get("t") == FIXED)
    assert bond[0]["cls"] == "bondlink" and FIXED in bond[0]["tip"]
    assert s.columns(u)["defaults"]["v/kagitlar/U1"] == ["A", "C", "F", "R"]
    assert s.columns(u)["defaults"]["v/dibslive/L1"] == ["A"]
    cols, fz, data = first("asw", "tbl", 2)
    assert cols == ["Kâğıt", "B"] and fz == 2
    assert any(row[0].get("cls") == "bondlink" and row[0]["t"] == "15.03.28" for row in data["rows"])


def test_dibs_rv_results_on_the_first_screen(service):
    """B16: right after Valör the compound yield, its O/N, ASW / DM, cheap / rich and the signal; Ad, Bilinen kupon, Son işlem
    tarihi and Fiyat durumu last; Ayarlar in two panels (one row of 26 cells was wider than the screen)."""
    c = vpanel("dibs", "B3")["cols"]
    at = c.index("P")
    assert c[at + 1:at + 6] == ["T", "BO", "Z", "AB", "AC"] and c[-4:] == ["C", "H", "I", "J"]
    assert set(c) - {"Kâğıt"} == {x for x in set(c) if x != "Kâğıt"} and len(c) == len(set(c))
    b1, b1b = vpanel("dibs", "B1"), vpanel("dibs", "B1b")
    assert (b1["range"], b1b["range"]) == ("A2:L2", "M2:Z2") and b1.get("fit") and b1b.get("fit")
    u = service.login("Toplu Tahvil RV")["user"]
    p1, p2 = page_panel(service, u, "dibs", "B1"), page_panel(service, u, "dibs", "B1b")
    assert [x.get("t") for x in p1["data"]["rows"][0]][0] == "Kaynak (genel)" and p2["data"]["rows"][0][0].get("t") == "BBG eki"
    # the desk's quote (Kota mesajı): the row's yield ± half a width, its bid the higher yield ("yield": quote.js)
    q = vpanel("dibs", "B3")["quote"]
    desk = next(x for x in q["sets"] if x["id"] == "desk")
    assert (q["label"], q["alt"], desk["mid"], desk["yield"]) == ("Kâğıt", "A", "T", True)


def test_bond_pages_are_shorter(service):
    """B17: DİBS ASW's two ASW charts side by side, its history a full-width bar when folded; Hazine İhalesi's blocks folded to
    their ISIN row while it is empty (an ISIN typed opens it), the realized nominal typed beside the bids."""
    s = service
    assert not vpanel("asw", "chart0").get("wide") and not vpanel("asw", "chartfx").get("wide")
    assert vpanel("asw", "hist").get("wide") and vpanel("asw", "hist").get("collapsed")
    for pid in ("H1", "H2", "H3"):
        assert vpanel("ihale", pid)["cols"][:7] == ["A", "B", "C", "D", "E", "P", "F"]
    u = s.login("Toplu Tahvil İhale")["user"]
    for pid, isin_row in (("H2", 27), ("H3", 47)):
        p = page_panel(s, u, "ihale", pid)
        assert p["data"]["r"] == [isin_row - 1, isin_row, isin_row + 1], (pid, p["data"]["r"])
    try:
        assert s.set_inputs(u, "tto", [{"ref": "EK_IHALE!A27", "value": FIXED}])["errors"] == []
        p = page_panel(s, u, "ihale", "H2")
        assert len(p["data"]["r"]) > 10 and 30 in p["data"]["r"] and 38 in p["data"]["r"]
    finally:
        s.set_inputs(u, "tto", [{"ref": "EK_IHALE!A27", "value": ""}])
    assert len(page_panel(s, u, "ihale", "H2")["data"]["r"]) == 3


def test_the_value_date_as_the_bond_pages_write_it():
    today = dt.date(2026, 11, 3)                          # a Tuesday
    hol = {"2026-11-05"}
    assert bd.valor_label(dt.date(2026, 11, 3), today, hol) == ("T0 · 03.11", 0)
    assert bd.valor_label(dt.date(2026, 11, 4), today, hol) == ("T1 · 04.11", 1)
    assert bd.valor_label(dt.date(2026, 11, 6), today, hol) == ("T2 · 06.11", 2)          # (the 5th a holiday)
    assert bd.valor_label(dt.date(2026, 11, 2), today, hol) == ("02.11.2026", None)
    assert [bd.value_day(today, n, hol) for n in (0, 1, 2, 3)] == [dt.date(2026, 11, d) for d in (3, 4, 6, 9)]
    assert bd.value_day(dt.date(2026, 11, 7), 0) == dt.date(2026, 11, 9)                   # (a Saturday: the next business day)


# ================================================================================================== C10 · the quote ticket
def test_the_ticket_sums_on_known_numbers():
    """The OIS annuity: quarterly from maturity back, the short period first (ACT/365); on a flat curve its closed form.  A
    bond's DV01 is the dirty price's change for one bp of its BIST simple yield."""
    class Flat:
        def df(self, t):
            return math.exp(-0.3 * t / 365.0)
    spot, mat = dt.date(2026, 11, 4), dt.date(2028, 3, 15)
    ends = [mat]
    k = 1
    while kf.add_months(mat, -3 * k) > spot:
        ends.append(kf.add_months(mat, -3 * k))
        k += 1
    ends.sort()
    want, prev = 0.0, spot
    for e in ends:
        want += (e - prev).days / 365.0 * math.exp(-0.3 * (e - spot).days / 365.0)
        prev = e
    assert kf.ois_annuity(Flat(), spot, mat) == pytest.approx(want, rel=1e-14) and (ends[0] - spot).days < 92
    assert kf.add_months(dt.date(2026, 3, 31), -1) == dt.date(2026, 2, 28) and kf.ois_annuity(Flat(), spot, spot) is None
    bond = qc.Bond("X", "", "fixed", mat, 36.8, 2)
    p = kf.KagitFiyat.pricer_at({"kind": "S", "freq": 2.0, "guess": 0.3}, bond, spot)
    yc = 0.39
    ys = p.simple(yc)
    num = (p.dirty(kf.compound_of(ys - 1e-4, "fixed", 2.0, None)) - p.dirty(kf.compound_of(ys + 1e-4, "fixed", 2.0, None))) / 2.0
    assert kf.dv01_of(p, yc) == pytest.approx(num, rel=1e-12) and 0.005 < kf.dv01_of(p, yc) < 0.05      # (per 100 of nominal)
    assert kf.compound_of(p.simple(yc), "fixed", 2.0, None) == pytest.approx(yc, abs=1e-14)
    b = kf.KagitFiyat.pricer_at({"kind": "B", "freq": 2.0, "guess": 0.3}, qc.Bond("B", "", "bill", dt.date(2027, 2, 10)), spot)
    assert kf.compound_of(b.simple(0.35), "bill", 2.0, b.days) == pytest.approx(0.35, abs=1e-13)


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def test_the_quote_ticket_at_any_value_date(svc):
    """The bond card's ticket: T0 / T1 / T2 or a date, a nominal, a centre (the market's yield, Kâğıt Fiyatlama's price, a
    yield typed) and a spread → bid = centre + spread / 2 (the desk buys at the higher yield), ask = centre − spread / 2, each
    compound and simple, clean and dirty at that value date (the same yield, priced at the new date), the amounts; the
    nominal's DV01 (DİBS RV's AI scaled) and its OIS hedge; the text to send, Turkish or English; refusals with why."""
    s = svc
    u = s.login("Toplu Tahvil Fiş")["user"]
    t1 = s.kagit_fiyat(u, {"ticket": "1", "isin": FIXED, "valor": "T1", "nominal": "10m"})
    assert t1["valor"] == {"date": "2026-11-04", "t": "T1", "text": "T1 · 04.11", "n": 1} and [v["key"] for v in t1["valors"]] == ["T0", "T1", "T2"]
    assert t1["center"]["kind"] == "piyasa" and set(t1["centers"]) >= {"piyasa", "fiyat"}
    # the market's yield: Kâğıt Fiyatlama's main table's, DİBS RV's bid / ask middle
    main = next(r for r in s.kagit_fiyat(u)["curve_rows"] if r["isin"] == FIXED)
    assert t1["center"]["yield"] == pytest.approx(main["market"]["yield"], abs=1e-12)
    assert t1["spread"] == t1["width"] == kf.WIDTH_DEFAULT[t1["bucket"]]
    bid, ask, mid = t1["bid"], t1["ask"], t1["mid"]
    assert bid["yield"] - ask["yield"] == pytest.approx(t1["spread"] / 100.0, abs=1e-12) and bid["clean"] < mid["clean"] < ask["clean"]
    assert bid["dirty"] == pytest.approx(bid["clean"] + t1["accrued"], abs=1e-12) and bid["amount"] == pytest.approx(1e7 * bid["dirty"] / 100.0)
    # at DİBS RV's own value date (T1) the market's mid prices back to the market's clean price; DV01 = AI per 1 mn × 10
    assert mid["clean"] == pytest.approx(main["market"]["clean"], abs=2e-6)
    assert t1["dv01"] == pytest.approx(rv(s, "AI", row_of(s, FIXED)) * 10.0, rel=0.01)
    h = t1["hedge"]
    assert h["nominal"] == pytest.approx(t1["dv01"] / (h["annuity"] / 1e4), rel=1e-12) and 0.5 < h["ratio"] < 1.5
    # the same yield at another value date: the price there (T2), a date typed (a week on)
    t2 = s.kagit_fiyat(u, {"ticket": "1", "isin": FIXED, "valor": "T2", "nominal": 1e7})
    assert t2["valor"]["date"] == "2026-11-05" and t2["mid"]["yield"] == pytest.approx(mid["yield"], abs=1e-12)
    p2 = kf.KagitFiyat.pricer_at({"kind": "S", "freq": 2.0, "guess": 0.3}, qc._bond_of(FIXED, {}, None), dt.date(2026, 11, 5))
    assert t2["mid"]["clean"] == pytest.approx(p2.clean(mid["yield"] / 100.0), abs=1e-9) and t2["mid"]["clean"] != mid["clean"]
    td = s.kagit_fiyat(u, {"ticket": "1", "isin": FIXED, "valor": "10.11.2026", "center": "yazilan", "level": "40", "spread": "20",
                            "nominal": "2,5mn"})
    assert td["valor"]["date"] == "2026-11-10" and td["valor"]["t"] == "T5" and td["nominal"] == 2.5e6
    assert td["center"]["kind"] == "yazilan" and td["bid"]["yield"] == pytest.approx(40.1) and td["ask"]["yield"] == pytest.approx(39.9)
    # a bond off the trading list, no market today: Kâğıt Fiyatlama's price (the curve) its centre
    off = s.kagit_fiyat(u, {"ticket": "1", "isin": OFF, "valor": "T1"})
    curve = next(r for r in s.kagit_fiyat(u)["curve_rows"] if r["isin"] == OFF)
    assert off["center"]["kind"] == "fiyat" and off["center"]["yield"] == pytest.approx(curve["price"]["yield"], abs=1e-12)
    assert "piyasa" not in off["centers"] and off["nominal"] == kf.TICKET_NOMINAL
    # a bill: at T0 (ISL0) its price is DİBS RV's, the simple yield BIST's of a bill
    bill = s.kagit_fiyat(u, {"ticket": "1", "isin": BILL, "valor": "T0"})
    assert bill["valor"]["date"] == "2026-11-03" and bill["accrued"] == 0.0 and bill["bid"]["dirty"] == bill["bid"]["clean"]
    # the text to send: the bond, its value date and nominal, then bid / ask lined up
    lines = t1["text"].split("\n")
    assert lines[0] == "DİBS 15.03.28 (TRT150328T24) · valör 04.11.2026 (T1) · nominal 10.000.000"
    assert lines[2].startswith("Getiri % (bileşik)  ") and lines[2].endswith("%s / %s" % (
        ("%.2f" % bid["yield"]).replace(".", ","), ("%.2f" % ask["yield"]).replace(".", ",")))
    en = s.kagit_fiyat(u, {"ticket": "1", "isin": FIXED, "valor": "T1", "language": "en"})["text"]
    assert en.startswith("TRY govt bond 15.03.28 (TRT150328T24) · value 04 Nov 2026 (T1) · nominal 10,000,000")
    # refused, said why
    for q, why in (({"isin": TLREF}, "TLREF'e endeksli"), ({"isin": FIXED, "valor": "02.11.2026"}, "bugünden önce"),
                   ({"isin": FIXED, "valor": "16.03.2028"}, "vadesinde ya da sonra"), ({"isin": FIXED, "valor": "yarın"}, "valör anlaşılamadı"),
                   ({"isin": FIXED, "nominal": "çok"}, "nominal anlaşılamadı"), ({"isin": FIXED, "center": "yazilan"}, "merkez getiri"),
                   ({"isin": OFF, "center": "piyasa"}, "piyasa fiyatı yok"), ({"isin": ""}, "ISIN gerekli")):
        with pytest.raises(Exception) as err:
            s.kagit_fiyat(u, dict(q, ticket="1"))
        assert why in str(err.value), (q, str(err.value))


def test_manuel_tahvils_ticket_is_the_pages_own(service):
    """Manuel Tahvil's quote ticket (its sheet's own block): the page's bond at the page's valör around the compound yield of
    the page's price - or a centre typed - with a spread: bid / ask yields, their clean price by the page's own inverse (the
    target yield's - Hedef → temiz fiyat), dirty, the amount; the nominal's DV01 (F11) and OIS hedge (I6, the OIS page's
    rounding).  Each user's own inputs; Kota mesajı and a right click (İşlem gir) on its clean prices."""
    s = service
    u = s.login("Toplu Tahvil Manuel")["user"]
    p = page_panel(s, u, "manuel", "B12")
    assert p["title"] == "Kotasyon fişi · masanın kotası" and p["data"]["c"] == ["AR", "AS", "AT", "AU"]

    def m(ref):
        return cell(s, "Manuel Tahvil!" + ref, u)

    try:
        assert s.set_inputs(u, "tto", [{"ref": "Manuel Tahvil!B17", "value": FIXED}])["errors"] == []
        f8, b8 = m("F8"), m("B8")
        assert m("AS6") == pytest.approx(f8) and m("AS7") == 10.0 and m("AS5") == 1e7
        assert m("AS10") == pytest.approx(f8 + 0.0005) and m("AT10") == pytest.approx(f8 - 0.0005)
        assert m("AS11") == pytest.approx(b8 * ((1 + m("AS10")) ** (1 / b8) - 1))
        # the clean price: the page's own target-yield inverse (J10) at the bid's simple yield
        assert s.set_inputs(u, "tto", [{"ref": "Manuel Tahvil!I10", "value": m("AS11") * 100}])["errors"] == []
        assert m("AS12") == pytest.approx(m("J10"), abs=1e-9) and m("AS13") == pytest.approx(m("AS12") + m("F3"))
        assert m("AS14") == pytest.approx(1e7 * m("AS13") / 100.0) and m("AU12") == FIXED
        assert m("AS15") == pytest.approx(m("F11") * 10.0) and m("AS17") == pytest.approx(m("I6") * 1e7)
        h2 = cell(s, "OIS_MAIN!H2", u)
        assert m("AS16") == pytest.approx(round(m("I6") * 1e7 / h2) * h2)
        # typed: a nominal, a centre, a spread
        assert s.set_inputs(u, "tto", [{"ref": "Manuel Tahvil!AS5", "value": "25m"}, {"ref": "Manuel Tahvil!AS6", "value": "40"},
                                       {"ref": "Manuel Tahvil!AS7", "value": "20"}])["errors"] == []
        assert m("AS5") == 2.5e7 and m("AS10") == pytest.approx(0.401) and m("AT10") == pytest.approx(0.399)
        assert "15.03.28 · valör" in str(m("AS3"))
    finally:
        s.set_inputs(u, "tto", [{"ref": "Manuel Tahvil!" + r, "value": ""} for r in ("B17", "I10", "AS5", "AS6", "AS7")])
    # Kota mesajı and İşlem gir: a valid trade hint on the clean prices' row, the quote's rows the four bid / ask lines
    v = vpanel("manuel", "B12")
    assert th.check(v["trade"]) == [] and v["trade"]["cells"] == {"AS": "price bid", "AT": "price ask"} and (v["trade"]["first"], v["trade"]["last"]) == (12, 12)
    assert (v["quote"]["first"], v["quote"]["last"], v["quote"]["date"]) == (10, 13, "AS3")


# ================================================================================================== C12, C13 (with a history)
def _market(svc) -> pr.Market:
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def run():
        calc = svc.interp.boot_of(book, svc._calc(None, book))
        return pr.read(lambda sh, r, c: calc.get(idx[sh], r, c))
    return svc.et.call(run)


@pytest.fixture(scope="module")
def seeded(svc):
    """60 week days of made-up closes before the replay day (Kâğıt Fiyatlama's tests' way: each bond of the trading list from
    the sheet's compound yield back by a random walk, every OIS tenor, TLREF) - so the trading list's bonds have a fair."""
    snap = svc.history.snapshot()
    today = svc.history.today()
    days, d = [], today - dt.timedelta(days=1)
    while len(days) < 60:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= dt.timedelta(days=1)
    days.reverse()
    rng = random.Random(5)
    bonds = {}
    for dd in snap["defs"]:
        if dd.group == "dibs" and dd.unit == "pct":
            t = cell(svc, "DİBS RV!T%d" % dd.info["row"])
            if type(t) is float:
                bonds[dd.info["isin"]] = (dd, t * 100.0)
    level = {isin: t for isin, (_, t) in bonds.items()}
    closes = {isin: {} for isin in bonds}
    for iso in reversed(days):
        for isin in bonds:
            closes[isin][iso] = round(level[isin], 10)
        common = rng.gauss(0.0, 0.08)
        for isin in bonds:
            level[isin] -= common + rng.gauss(0.0, 0.05)
    for isin, (dd, _) in bonds.items():
        svc.store.hist_upsert(dd.id, sorted(closes[isin].items()))
    quotes = dict(_market(svc).ois_quotes)
    ids = {float(x.months): x.id for x in snap["defs"] if x.group == "ois" and x.months and x.months >= 1}
    lvl = {m: quotes[m] * 100.0 for m in quotes}
    ois = {m: {} for m in quotes}
    for iso in reversed(days):
        for m in quotes:
            ois[m][iso] = round(lvl[m], 10)
        common = rng.gauss(0.0, 0.06)
        for m in quotes:
            lvl[m] -= common + rng.gauss(0.0, 0.02)
    for m, series in ois.items():
        svc.store.hist_upsert(ids[m], sorted(series.items()))
    ref = next(x for x in snap["defs"] if x.group == "ref")
    svc.store.hist_upsert(ref.id, [(iso, 39.5) for iso in days])
    svc.history.rev += 1
    return {"days": days}


def test_tum_kagitlar_has_a_yield_for_every_bond(svc, seeded):
    """C12: every fixed coupon bond, bill and zero coupon bond of Tüm Kâğıtlar - off the trading list too - with Kâğıt
    Fiyatlama's market yield, its price (the curve's where there is no market; how in the tip) and the market's gap to the
    curve; "hesaplanıyor" before its first snapshot; floaters say why not."""
    s = svc
    u = s.login("Toplu Tahvil Evren")["user"]
    kfa = s.kagitfiyat
    with kfa._snap_lock:
        kfa._snap, kfa._snap_busy = None, True                  # (no snapshot yet, none being made: the page waits)
    data = page_panel(s, u, "kagitlar", "U1")["data"]
    caps = [h for h, _ in s.UNI_KF]
    assert data["c"][-len(caps) - 6:-6] == caps[:0] or all(c in data["c"] for c in caps)
    at = data["c"].index(caps[0])
    rows = {row[1].get("t"): row for row in data["rows"] if len(row) > 1}
    assert rows[FIXED][at]["t"] == "hesaplanıyor"
    with kfa._snap_lock:
        kfa._snap_busy = False
    snap = kfa.snapshot(wait=True)
    assert snap["curves"] and snap["day"] == "2026-11-03"
    data = page_panel(s, u, "kagitlar", "U1")["data"]
    rows = {row[1].get("t"): row for row in data["rows"] if len(row) > 1}
    curves = s.kagit_fiyat(u)["curve_rows"]
    by = {r["isin"]: r for r in curves}
    # on the trading list, a market price: its yield; the price the market's; the gap to the curve
    x = rows[FIXED][at:at + 4]
    assert x[0]["v"] == pytest.approx(by[FIXED]["market"]["yield"] / 100.0, abs=1e-12) and x[1]["v"] == x[0]["v"]
    assert x[3]["v"] == pytest.approx(by[FIXED]["diff"], abs=1e-9) and "kf-curve" not in (x[1].get("cls") or "")
    # off the list, no market: the curve's price, marked, how in the tip
    y = rows[OFF][at:at + 4]
    assert y[0]["t"] == "" and y[1]["v"] == pytest.approx(by[OFF]["price"]["yield"] / 100.0, abs=1e-12) and y[1]["cls"] == "kf-curve"
    assert y[2]["v"] == pytest.approx(by[OFF]["price"]["clean"], abs=1e-12) and by[OFF]["price"]["label"] in y[1]["tip"]
    # every fixed coupon bond has a yield now (12 of 26 had none: C12's evidence)
    fixed = [row for isin, row in rows.items() if isin and isin.startswith("TRT") and (bd.by_isin(isin) or {}).get("kind") == "fixed"]
    assert fixed and all(row[at + 1]["t"] for row in fixed)
    assert all(not row[at]["t"] for isin, row in rows.items() if (bd.by_isin(isin or "") or {}).get("kind") in ("float", "frn", "cpi"))


def test_kagit_fiyatlama_levels_are_alarm_names(svc, seeded):
    """C13: "[15.03.28 adil]", "[15.03.28 AL]", "[15.03.28 SAT]" - the desk's Kâğıt Fiyatlama now (its snapshot, never made
    on the calculation thread) - for any alarm; the card's / the details' button sets two: the screen yield at AL (cheap: buy)
    and at SAT (rich: sell)."""
    s = svc
    u = s.login("Toplu Tahvil Alarm")["user"]
    snap = s.kagitfiyat._keep_snapshot(s.kagitfiyat.make_snapshot())
    page = {r["isin"]: r for r in s.kagit_fiyat(u)["rows"]}
    lv = snap["levels"][FIXED]
    assert lv["fair"] == pytest.approx(page[FIXED]["fair"]["yield"], abs=1e-9)
    assert (lv["buy"], lv["sell"]) == (pytest.approx(page[FIXED]["levels"]["buy"]["yield"], abs=1e-9),
                                       pytest.approx(page[FIXED]["levels"]["sell"]["yield"], abs=1e-9))
    names = s.watch.names()
    for name, metric in (("15.03.28 adil", "kf_fair"), ("15.03.28 al", "kf_buy"), ("15.03.28 sat", "kf_sell"), ("trt150328t24 al", "kf_buy")):
        assert names[name] == {"kind": "bond", "isin": FIXED, "metric": metric}
    assert "trt240227t17 al" not in names                       # (off the trading list: no fair)
    rd = s.watch._Reader(s.watch, None)
    assert s.et.call(lambda: s.watch.resolve({"kind": "bond", "isin": FIXED, "metric": "kf_buy"}, rd))[:2] == (pytest.approx(lv["buy"]), "pct")
    assert s.watch.label({"kind": "bond", "isin": FIXED, "metric": "kf_sell"}) == "15.03.28 SAT (Kâğıt Fiyatlama)"
    # the button's alarm: the screen yield − AL, in bp, ≥ 0
    res = s.alarm_add(u, subject={"kind": "expr", "text": "[%s getiri] - [%s AL]" % (FIXED, FIXED)}, op=">=", level=0,
                      label="15.03.28 AL seviyesinde")
    t = rv(s, "T", row_of(s, FIXED), u)
    assert res["value"] == pytest.approx((t * 100.0 - lv["buy"]) * 100.0, abs=1e-6) and res["alarm"]["show"] == "bp"
    assert res["already"] == (t * 100.0 >= lv["buy"])
    s.alarm_remove(u, res["alarm"]["id"])
    # the alarm form's list of a bond's measures has them (the trading list's only)
    got = s.watch_catalog(u)["bond_metrics"]
    assert [x["id"] for x in got if x["id"].startswith("kf_")] == ["kf_fair", "kf_buy", "kf_sell"]


def test_over_http(svc, seeded):
    client = TestClient(create_app(service=svc))                  # (no "with": the module's service stays up)
    h = auth(svc, "Toplu Tahvil HTTP")
    r = client.get("/api/kagit-fiyat", params={"ticket": "1", "isin": FIXED, "valor": "T2", "nominal": "5m"}, headers=h)
    assert r.status_code == 200 and r.json()["valor"]["t"] == "T2" and r.json()["nominal"] == 5e6 and r.json()["text"]
    assert client.get("/api/kagit-fiyat", params={"ticket": "1", "isin": TLREF}, headers=h).status_code == 400
    assert client.get("/api/kagit-fiyat", params={"ticket": "1", "isin": FIXED}, headers=ANON).status_code == 401
    cols = client.get("/api/columns", headers=h).json()
    assert [p["name"] for p in cols["presets"]["v/dibslive/L0"]] == ["Trading", "RV", "Risk", "Tümü"]
    body = client.get("/api/dibs/genel", headers=h).json()
    assert body["ok"] and body["trading"]["panel"] == "L0" and "table" not in body
