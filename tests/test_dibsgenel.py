"""DİBS RV · Genel (``tto/dibsgenel.py``): one menu entry with three tabs (Genel, the RV and the ASW hesap tablosu - the old
pages' addresses and boxes keep working); the bond table's one home is DİBS Trading's summary since 28.11.2026 (Genel links to
it: its columns, each figure its source's, are test_toplu_tahvil's) - the FX swap figures the same there and on the card,
the zero-coupon fit that is quantcurve's on the same inputs (Nelson-Siegel on the fixed coupon bonds, the bills priced on
it, not fitted) and steady on the trading list's bonds, the summary's zero-coupon cells that fit's, a bond added in the
middle of the trading list followed by its ISIN, the charts' points, the tables of the hesap tablosu tabs shown as their
pages draw them, and the HTTP endpoint."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import bonds as bd
from tto import dibsgenel as dg
from tto import quantcurve as qc
from tto import quantfam as qf
from tto import rvfair
from tto.quant import DEFAULTS
from tto.server import create_app
from tto.xl import numfmt
from tto.xl.tokenizer import col_to_index

FIXED, BILL, TLREF, NO_PRICE = "TRT150328T24", "TRB100227T13", "TRT090130T12", "TRT081128T15"


def rv(s, col, r, user=None):
    return cell(s, "DİBS RV!%s%d" % (col, r), user)


def row_of(s, isin):
    return next(r for r in range(5, 55) if rv(s, "A", r) == isin)


def genel(s, user):
    return s.dibsgenel.view(user)


def line(d, isin):
    """A bond's cells in DİBS Trading's summary (``d``: its data), by the names Genel's table had (``Service._trading_keys``)."""
    from tto.service import Service
    keys = Service._trading_keys()
    by = summary_line(d, isin)
    return {name: by[key] for name, key in keys.items()}


def summary(s, user):
    return next(p for p in s.view(user, "dibslive")["panels"] if p["id"] == "L0")["data"]


def summary_line(d, isin):
    row = next(row for row in d["rows"] if len(row) > 2 and row[2].get("t") == isin)
    return {key: c for key, c in zip(d["c"], row)}


# ---------------------------------------------------------------------------------------------- the menu
def test_dibs_rv_is_one_menu_entry_with_three_tabs(service):
    u = service.login("Genel Menü")["user"]
    nav = service.nav(u)
    tahvil = [p for p in nav if p["group"] == "Tahvil"]
    entry = [p for p in tahvil if p.get("menu") == dg.MENU_ID]
    assert [(p["id"], p["tab"], p["menu_title"]) for p in entry] == [("dibs-genel", "Genel", "DİBS RV"), ("dibs", "RV hesap tablosu", "DİBS RV"),
                                                                    ("asw", "ASW hesap tablosu", "DİBS RV")]
    # one entry, the Tahvil group's last (the menu's reorganization of 28.11.2026, tto/navmenu.py: DİBS Piyasa · DİBS
    # Fiyatlama · DİBS RV); the pages keep their titles and addresses
    ids = [p["id"] for p in tahvil]
    assert ids == ["dibslive", "kagitlar", "bulk", "kagit-fiyat", "manuel", "fiyat-yukleme", "ihale", "dibs-genel", "dibs", "asw"]
    by = {p["id"]: p for p in tahvil}
    assert by["dibs"]["title"] == "DİBS RV" and by["asw"]["title"] == "DİBS ASW" and by["dibs-genel"]["title"] == "DİBS RV · Genel"
    assert by["dibs-genel"]["custom"] and by["dibs"]["sheet"] == "DİBS RV" and by["asw"]["book"] == "asw" and by["dibs"]["tables"]
    assert [p["id"] for p in nav if p.get("menu") == dg.MENU_ID] == ["dibs-genel", "dibs", "asw"]
    # the old pages open as before; a launchpad box of them, a cell of them, the card's link to them
    assert any(p["id"] == "B3" for p in service.view(u, "dibs")["panels"]) and any(p["id"] == "tbl" for p in service.view(u, "asw")["panels"])
    got = service.panels(u, [{"view": "dibs", "panel": "B3", "key": "a"}, {"view": "asw", "panel": "chart0", "key": "b"}])["panels"]
    assert got["a"]["entry"]["data"]["rows"] and got["b"]["entry"]["data"]["series"] and got["a"]["page"] == "DİBS RV"
    # a dashboard without the TRY workbook: no entry (the pages are not there)
    assert dg.menu([{"id": "usd", "title": "USD"}]) == [{"id": "usd", "title": "USD"}]


# ---------------------------------------------------------------------------------------------- Genel without a table
def test_genel_is_the_charts_the_fit_and_a_link_to_the_one_home(service):
    """Genel's answer: the zero-coupon fit, the yield curve, the settings the figures read (each typed in the RV hesap
    tablosu's Ayarlar, in the panel it is in), the mirrored tables - and the link to the bond table's one home, DİBS Trading's
    summary, with the trading list's bonds counted by kind (the desk, 28.11.2026: "Genel yalnız grafikler + Trading tablosuna
    bağlantı")."""
    s = service
    u = s.login("Genel Kaynak")["user"]
    d = genel(s, u)
    assert "table" not in d and d["fit"]["ok"] and d["chart"]["series"] and len(d["mirrors"]) == 5
    assert d["trading"] == dict(dg.TRADING, n=19, kinds=[{"kind": "B", "title": "Bono · kuponsuz", "n": 2},
                                                          {"kind": "S", "title": "Sabit kuponlu", "n": 14},
                                                          {"kind": "T", "title": "TLREF'e endeksli", "n": 3}])
    listed = [v for v in s._list_values(u, "tto", "DİBS RV!A5:A54") if v]
    assert d["trading"]["n"] == len(listed)
    sets = {x["ref"]: x for x in d["settings"]}
    assert set(sets) == {"DİBS RV!P2", "DİBS RV!J2", "DİBS RV!X2", "DİBS RV!Z2", "DİBS RV!B2"}
    assert sets["DİBS RV!X2"]["t"] == "ORTA" and all(x["view"] == "dibs" for x in sets.values())
    assert {x["panel"] for x in sets.values()} == {"B1", "B1b"} and sets["DİBS RV!P2"]["panel"] == "B1b"
    # the zero-coupon group of the summary is Genel's fit's, named as before
    assert dg.ZERO_GROUP == "Sıfır kupon eğrisi (NS)" and dg.ZERO_GROUP in [c.get("t") for c in summary(s, u)["rows"][0]]


def test_the_fx_figures_are_the_same_on_dibs_trading_the_card_and_genel(service):
    """The FX swap side everywhere a trader reads one is DİBS ASW's FX swap implied TRY curve (EK_FX): the summary (the bond
    table's one home, Genel's link) and the card show the same ASW, cheap / rich, signal, fair yield and fair price - DİBS
    ASW's own figures on that curve."""
    s = service
    u = s.login("Genel FX")["user"]
    summ = summary(s, u)
    d = summ
    book = s.books["asw"]
    ai = book.model.sheet_index["ASW"]
    for isin in (FIXED, BILL, "TRT130928T38"):
        g, y = line(d, isin), summary_line(summ, isin)
        card = {x["name"]: x for x in s.bond_card(u, isin)["rv"]}
        for gk, sk, name in (("fx_asw", "AA", "ASW FX ima (bp)"), ("fx_rc", "AD", "Pahalı/ucuz FX ima (bp, + ucuz)"), ("fx_sig", "AE", "Sinyal FX ima"),
                             ("fx_fy", "AB", "Adil getiri (FX swap ima eğrisi)"), ("fx_fp", "AC", "Adil fiyat (FX swap ima eğrisi)")):
            assert g[gk]["t"] == y[sk]["t"] == card[name]["t"], (isin, name)
        ar = 7 + s._list_values(u, "asw", "ASW!B7:B56").index(isin)
        r_fx, t_fx = s.et.call(lambda: [s._asw_fx_calc(book, u)[0].get(ai, ar, col_to_index(c)) for c in ("R", "T")])
        assert (g["fx_asw"]["v"], g["fx_rc"]["v"]) == (r_fx, t_fx)
        # (not DİBS RV's own FX columns: those are on the offshore ICAP curve, its tab only)
        assert g["fx_asw"]["v"] != rv(s, "BF", row_of(s, isin))
    # ... in whole bp, as every spread of the bond pages (the desk's one rule, 28.11.2026; −164 for −163,9 on the recorded
    # data of a fresh service - the session's service may have had its sources changed by the tests before this one, so the
    # sheet's own value now), the value whole
    assert summary_line(summ, "TRT130928T38")["AA"]["t"] == "%d" % round(r_fx) and summary_line(summ, "TRT130928T38")["AA"]["v"] == r_fx


# ---------------------------------------------------------------------------------------------- the zero-coupon curve
def test_par_yield_and_zero_rate_on_a_flat_curve():
    """On a flat curve (continuous z) a bond priced at par yields 2·(e^(z·182/365) − 1) a half year (its periods are 182
    days): compounded once a year, (1 + y/2)² − 1; the zero rate compounded once a year is e^z − 1."""
    flat = qc.Nss([0.3, 0.0, 0.0, 0.0], 1.0, 5.0)
    value = dt.date(2026, 11, 4)
    want = (1 + (math.exp(0.3 * 182 / 365) - 1)) ** 2 - 1
    for t in (0.7, 1.0, 2.35, 5.0, 9.9):
        assert dg.par_yield(flat, value, t) == pytest.approx(want, abs=1e-10), t
    res = {"ok": True, "nss": flat, "in": type("I", (), {"value": [value]})()}
    lines = dg.curve_lines(res, 3.0)
    assert len(lines["t"]) == 30 and lines["t"][0] == pytest.approx(0.1) and lines["t"][-1] == pytest.approx(3.0)
    assert all(z == pytest.approx((math.exp(0.3) - 1) * 100, abs=1e-9) for z in lines["zero"])


def test_the_zero_coupon_fit_is_quantcurves_on_the_same_inputs(service):
    """The live fit is quant's "DİBS adil değeri" fit of today's quotes: quantcurve.fam_dibs run on the same bonds (no
    history: the model's τ searched on them, the β with them held) gives the same model (Nelson-Siegel), RMSE,
    leave-one-out RMSE, parameters, residuals and model yields - the curve fitted to the fixed coupon bonds, the bills
    priced on it (not fitted: a model yield and a rich / cheap all the same); the fair price is quantcurve.quote_bond's."""
    s = service
    u = s.login("Genel NSS")["user"]
    loc = numfmt.get_locale("tr")
    got = s.et.call(lambda: s.dibsgenel._read(u, loc))
    mine = dg.DibsGenel(s).fit(got["quant"], got["live"], got["today"])           # (a fresh one: nothing kept)
    assert mine["ok"] and mine["found"] is not None
    ctx = qf.Ctx(dict(DEFAULTS), got["today"], {}, {}, live=got["live"])
    _, table = qc.fam_dibs(ctx, {"dibs": got["quant"]}, None)
    built = table["build"](got["live"])
    assert built["ok"]
    summ = dg.fit_summary(mine)
    assert summ["rmse"] == pytest.approx(built["rmse"], abs=1e-9) and summ["n_fit"] == built["n_fit"] == 13 and summ["n"] == built["n"] == 15
    assert summ["n_bills"] == built["n_bills"] == 2 and summ["model"] == built["model"] == "NS"          # (the bills out of the fit)
    assert summ["loo"] == pytest.approx(built["loo"], abs=1e-9) and summ["loo"] > summ["rmse"]
    p = built["params"]
    assert summ["beta"] == pytest.approx([p["b0"], p["b1"], p["b2"]], abs=1e-9) and summ["tau"] == pytest.approx([p["tau1"]], abs=1e-12)
    assert p["b3"] is None and p["tau2"] is None
    rows = dg.fit_rows(mine)
    for b in built["rows"]:
        x = rows[b["isin"]]
        assert x["resid"] == pytest.approx(b["resid"], abs=1e-9) and x["model"] == pytest.approx(b["model"], abs=1e-12), b["isin"]
        assert x["fitted"] == b["fitted"] == (b["kind"] == "fixed") and (x["weight"] is None) == (b["weight"] is None) == (b["kind"] == "bill")
    # the page's line and DİBS Trading's summary (the bond table's one home) are those numbers
    assert genel(s, u)["fit"]["rmse"] == pytest.approx(built["rmse"], abs=1e-9)
    d = summary(s, u)
    for isin in (FIXED, BILL):
        x = line(d, isin)
        assert x["z_rc"]["v"] == pytest.approx(rows[isin]["resid"], abs=1e-9) and x["z_model"]["v"] == pytest.approx(rows[isin]["model"] / 100, abs=1e-12)
        b = next(z for z in mine["in"].bonds if z.isin == isin)
        value = mine["in"].value[mine["in"].bonds.index(b)]
        assert x["z_fp"]["v"] == pytest.approx(qc.quote_bond(b, value, mine["nss"], 0.0)["fair"]["clean"], abs=1e-12)
        # a bond's model yield is its yield less its cheap / rich (the simple yield of DİBS RV!S)
        assert x["z_model"]["v"] == pytest.approx(rv(s, "S", row_of(s, isin)) - x["z_rc"]["v"] / 1e4, abs=1e-12)
    # the bill priced on the curve, marked as not in the fit - as any bond out of it
    assert "uydurmaya girmez, eğriye karşı ölçülür" in line(d, BILL)["z_rc"]["tip"] and "uydurmada" in line(d, FIXED)["z_rc"]["tip"]
    assert "uydurmada" not in line(d, BILL)["z_rc"]["tip"]
    assert "NS sıfır kupon eğrisi (13 sabit kuponluya uyduruldu, 2 bono eğriye göre ölçüldü)" in line(d, BILL)["z_rc"]["tip"]
    # kept: the same inputs answer the same fit; new yields refit the β with the τ held
    again = s.dibsgenel.fit(got["quant"], got["live"], got["today"])
    assert again["fit"] is s.dibsgenel.fit(got["quant"], got["live"], got["today"])["fit"]
    moved = dict(got["live"], **{"DIBSS:" + FIXED: got["live"]["DIBSS:" + FIXED] + 0.25})
    held = s.dibsgenel.fit(got["quant"], moved, got["today"])
    assert held["found"] is None and (held["nss"].tau1, held["nss"].tau2) == (again["nss"].tau1, again["nss"].tau2)
    assert dg.fit_rows(held)[FIXED]["resid"] > dg.fit_rows(again)[FIXED]["resid"] + 15


def test_the_curve_of_the_trading_list_is_steady_and_prices_the_bills(service):
    """The trading list's curve now (DİBS RV's bonds and bills - the sheet as it stands, no figure pinned): Nelson-Siegel
    fitted to the fixed coupon bonds alone (the desk's decision of 18.11.2026), its β tens of per cent (Svensson's on the
    same bonds ran to hundreds, opposite signs), τ1 within the bonds' years; the bills priced on it, not fitted - a bill's
    own yield does not move it, its rich / cheap reads the coupon bonds' curve at the short end: further from the curve
    than the bills read when they were fitted too (the short end bent towards them); a day's noise of a few bp on every
    yield, refitted as the quant family refits a day (the τ held), moves the β by a point or so, not tens."""
    import random
    s = service
    u = s.login("Genel Eğri")["user"]
    got = s.et.call(lambda: s.dibsgenel._read(u, numfmt.get_locale("tr")))
    res = dg.DibsGenel(s).fit(got["quant"], got["live"], got["today"])
    summ = dg.fit_summary(res)
    assert summ["model"] == "NS" and summ["n_bills"] >= 1 and all(abs(b) < 100.0 for b in summ["beta"])
    assert 0.5 * summ["shortest"] <= summ["tau"][0] <= summ["longest"] and summ["rmse"] <= summ["loo"]
    rows = dg.fit_rows(res)
    items, _ = dg.bond_inputs(got["quant"], got["live"], got["today"])
    bills = [i for i, x in rows.items() if x["kind"] == "bill"]
    assert len(bills) == summ["n_bills"] and summ["n_fit"] + summ["n_bills"] == summ["n"] == len(rows)
    assert all(x["fitted"] == (x["kind"] == "fixed") for x in rows.values())
    assert all(rows[i]["weight"] is None and math.isfinite(rows[i]["model"]) and math.isfinite(rows[i]["fair"]["clean"]) for i in bills)
    # a bill's own yield does not move the curve: 10 bp on it, the same β and fair price, its rich / cheap 10 bp more
    bill = bills[0]
    moved = dg.zero_fit([(b, v, y + (0.001 if b.isin == bill else 0.0), c) for b, v, y, c in items], res["tau"])
    assert moved["nss"].beta == pytest.approx(res["nss"].beta, abs=1e-12)
    after = dg.fit_rows(moved)[bill]
    assert after["fair"]["clean"] == pytest.approx(rows[bill]["fair"]["clean"], abs=1e-9)
    assert after["resid"] - rows[bill]["resid"] == pytest.approx(10.0, abs=0.5)
    # fitted too (as before 18.11.2026) the bills bent the short end towards them and read nearer the curve
    both = qc.BondFit(items, ("fixed", "bill"))
    in_r = {b.isin: e * 1e4 for b, e in zip(both.bonds, both.evaluate(qc.dibs_search(both)["nss"])[0])}
    assert sum(abs(rows[i]["resid"]) for i in bills) > sum(abs(in_r[i]) for i in bills)
    rnd = random.Random(3)
    moved = qc.BondFit([(b, v, y + rnd.gauss(0, 0.0003), c) for b, v, y, c in items])
    nxt = qc.refit(moved.make, res["nss"], res["nss"].beta, iters=5)["nss"]
    assert nxt.k == qc.NS and max(abs(a - b) for a, b in zip(nxt.beta, res["nss"].beta)) * 100 < 2.0


def test_too_few_bonds_no_fit_and_why(service):
    items = [(qc.Bond("TRT1", "", "fixed", dt.date(2028, 3, 15), 36.8, 2), dt.date(2026, 11, 4), 0.36, "simple")]
    res = dg.zero_fit(items)
    assert not res["ok"] and res["why"] == "en az 6 sabit kuponlu kâğıdın getirisi gerekli (1 var)"
    assert dg.fit_summary(res) == {"ok": False, "why": res["why"]}
    # the bills do not make up the count (not in the fit): five coupon bonds and three bills are not enough
    v = dt.date(2026, 11, 4)
    items = [(qc.Bond("TRT%d" % i, "", "fixed", dt.date(2028 + i, 3, 15), 30.0, 2), v, 0.33, "simple") for i in range(5)] + \
            [(qc.Bond("TRB%d" % i, "", "bill", dt.date(2027, 1 + i, 10)), v, 0.36, "simple") for i in range(3)]
    res = dg.zero_fit(items)
    assert not res["ok"] and res["why"] == "en az 6 sabit kuponlu kâğıdın getirisi gerekli (5 var)"


# ---------------------------------------------------------------------------------------------- following the bonds
def test_a_bond_added_in_the_middle_is_followed_by_its_isin(module_service):
    """The trading list changes: a bond added in an empty row in the middle comes in its group by maturity; every other
    bond's figures stay its own (keyed by ISIN, not by row); taken off, it is gone."""
    s = module_service
    u = s.login("Genel Takip")["user"]
    before = summary(s, u)
    # (a bond's own figures; what reads a fitted curve moves when a fixed coupon bond comes into the fits)
    own = ("bond", "isin", "due", "left", "valor", "bid", "ask", "last", "clean", "ycomp", "ysimple", "ois_asw", "fx_asw", "dur", "dv01",
           "hedge", "cr", "card", "star")
    keep = {isin: {k: line(before, isin)[k].get("t") for k in own} for isin in (FIXED, BILL, TLREF)}
    empty = next(r for r in range(5, 55) if not rv(s, "A", r))
    new = "TRT190128T14"
    assert s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % empty, "value": new}])["errors"] == []
    try:
        after = summary(s, u)
        isins = [row[2].get("t") if len(row) > 2 else None for row in after["rows"]]
        assert new in isins
        for isin, cells in keep.items():
            assert {k: line(after, isin)[k].get("t") for k in own} == cells, isin
        # in its kind's group, by maturity
        groups, cap = {}, None
        for row in after["rows"][2:]:
            if "grouphead" in (row[0].get("cls") or ""):
                cap = row[0]["t"].split(" · ")[0]
            else:
                groups.setdefault(cap, []).append(row[2]["t"])
        kind = {"bill": "Bono", "zero": "Bono", "fixed": "Sabit kuponlu", "float": "TLREF'e endeksli"}[bd.by_isin(new)["kind"]]
        assert new in groups[kind] and line(after, new)["isin"]["t"] == new and line(after, new)["bond"]["cls"] == "bondlink"
        mats = [bd.by_isin(x)["maturity"] for x in groups[kind]]
        assert mats == sorted(mats)
    finally:
        s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % empty, "value": ""}])
    assert new not in [row[2].get("t") for row in summary(s, u)["rows"] if len(row) > 2]


# ---------------------------------------------------------------------------------------------- the charts and the mirrors
def test_the_charts_points_and_the_mirrored_tables(service):
    s = service
    u = s.login("Genel Grafik")["user"]
    d = genel(s, u)
    ch = d["chart"]
    names = [x["name"] for x in ch["series"]]
    assert names == ["Kâğıtlar (bileşik getiri)", "Sıfır kupon eğrisi · par getiri", "Sıfır kupon eğrisi · zero faiz", "OIS par @vade (DİBS RV)"]
    pts = ch["series"][0]
    # each fixed coupon bond and bill with a price, at its years with its compound yield (DİBS RV!F, T)
    priced = [r for r in range(5, 55) if rv(s, "D", r) in ("S", "B") and type(rv(s, "T", r)) is float]
    assert len(pts["x"]) == len(priced) == 15 and len(pts["labels"]) == 15
    by_x = sorted((rv(s, "F", r), rv(s, "T", r) * 100) for r in priced)
    assert list(zip(pts["x"], pts["data"])) == pytest.approx(by_x)
    ois = ch["series"][3]
    assert len(ois["x"]) == len([r for r in range(5, 55) if type(rv(s, "X", r)) is float and type(rv(s, "F", r)) is float]) == 18
    par, zero = ch["series"][1], ch["series"][2]
    assert len(par["x"]) == len(zero["x"]) == math.floor((max(pts["x"]) + 0.25) / dg.GRID_STEP + 1e-9) and all(type(v) is float for v in par["data"])
    # the fitted bonds sit around the par line, within a few RMSEs
    fit = d["fit"]
    assert fit["ok"] and fit["n_fit"] == 13 and fit["n_bills"] == 2 and 0 < fit["rmse"] < 100 and len(fit["beta"]) == 3 and len(fit["tau"]) == 1
    # the tables and charts of the hesap tablosu tabs, as their pages draw them
    assert [(m["view"], m["panel"]) for m in d["mirrors"]] == [("asw", "chart0"), ("asw", "chartfx"), ("dibs", "B4"), ("asw", "sel"), ("asw", "chart1")]
    got = s.panels(u, [{"view": m["view"], "panel": m["panel"], "key": m["key"]} for m in d["mirrors"]])["panels"]
    assert all(not x.get("missing") for x in got.values()), got
    page = {p["id"]: p for p in s.view(u, "asw")["panels"]}
    assert got["asw_fx"]["entry"]["data"] == page["chartfx"]["data"] and got["asw_ois"]["entry"]["data"] == page["chart0"]["data"]
    switch = got["switch"]["entry"]["data"]
    assert switch["sheet"] == "DİBS RV" and any(c.get("i") for row in switch["rows"] for c in row)          # (its inputs: typed in its tab)


# ---------------------------------------------------------------------------------------------- over HTTP
def test_over_http(module_service):
    s = module_service
    client = TestClient(create_app(service=s))                        # (no "with": the module's service stays up)
    h = auth(s, "Genel HTTP")
    r = client.get("/api/dibs/genel", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["trading"]["view"] == "dibslive" and body["fit"]["ok"] and body["chart"]["series"]
    assert body["tabs"][0] == {"id": "dibs-genel", "title": "Genel"} and "table" not in body
    assert client.get("/api/dibs/genel", headers=ANON).status_code == 401
    nav = client.get("/api/nav", headers=h).json()["pages"]
    assert [p["id"] for p in nav if p.get("menu") == dg.MENU_ID] == ["dibs-genel", "dibs", "asw"]
    for path in ("/static/js/pages/dibsgenel.js", "/static/js/menu.js"):
        assert client.get(path).status_code == 200, path
    assert client.post("/api/panels", json={"items": [{"view": m["view"], "panel": m["panel"], "key": m["key"]} for m in dg.MIRRORS]},
                       headers=h).status_code == 200
