"""DİBS RV · Genel (``tto/dibsgenel.py``): one menu entry with three tabs (Genel, the RV and the ASW hesap tablosu - the old
pages' addresses and boxes keep working), the bond table whose every figure is its source's (DİBS RV's cell, rvfair's fair
value - the same as DİBS Trading's and the card's -, DİBS ASW on the FX swap implied curve, the live fit), the zero-coupon
fit that is quantcurve's on the same inputs (Nelson-Siegel, the bills in) and steady on the trading list's bonds, a bond
added in the middle of the trading list followed by its ISIN, the charts' points, the tables of the hesap tablosu tabs
shown as their pages draw them, and the HTTP endpoint."""
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
    t = d["table"]
    i = t["isin"].index(isin)
    return dict(zip(t["c"], t["rows"][i]))


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
    # one entry, where the two pages stood (between DİBS Trading and Manuel Tahvil); the pages keep their titles and addresses
    ids = [p["id"] for p in tahvil]
    assert ids == ["kagitlar", "dibslive", "dibs-genel", "dibs", "asw", "manuel", "ihale", "bulk"]
    by = {p["id"]: p for p in tahvil}
    assert by["dibs"]["title"] == "DİBS RV" and by["asw"]["title"] == "DİBS ASW" and by["dibs-genel"]["title"] == "DİBS RV · Genel"
    assert by["dibs-genel"]["custom"] and by["dibs"]["sheet"] == "DİBS RV" and by["asw"]["book"] == "asw" and by["dibs"]["tables"]
    assert not any(p.get("menu") for p in nav if p["id"] not in ("dibs-genel", "dibs", "asw") and p["group"] != "Quant")
    # the old pages open as before; a launchpad box of them, a cell of them, the card's link to them
    assert any(p["id"] == "B3" for p in service.view(u, "dibs")["panels"]) and any(p["id"] == "tbl" for p in service.view(u, "asw")["panels"])
    got = service.panels(u, [{"view": "dibs", "panel": "B3", "key": "a"}, {"view": "asw", "panel": "chart0", "key": "b"}])["panels"]
    assert got["a"]["entry"]["data"]["rows"] and got["b"]["entry"]["data"]["series"] and got["a"]["page"] == "DİBS RV"
    # a dashboard without the TRY workbook: no entry (the pages are not there)
    assert dg.menu([{"id": "usd", "title": "USD"}]) == [{"id": "usd", "title": "USD"}]


# ---------------------------------------------------------------------------------------------- the table
def test_every_figure_of_the_table_is_its_sources(service):
    s = service
    u = s.login("Genel Kaynak")["user"]
    d = genel(s, u)
    t = d["table"]
    assert [c.get("t") for c in t["rows"][0] if not c.get("sk")] == ["Kâğıt", "Fiyat", "Getiri", "OIS ASW", dg.FX_GROUP,
                                                                     "Sıfır kupon eğrisi (NS)", "Risk", "Carry", "Broker", ""]
    assert dg.ZERO_GROUP == "Sıfır kupon eğrisi (NS)"
    assert t["c"][:4] == ["bond", "isin", "due", "left"] and t["c"][-2:] == ["card", "flag"]
    assert [c["t"] for c in t["rows"][1]][23:26] == ["Model getiri %", "Pahalı / ucuz", "Adil fiyat"]
    # the trading list's bonds, kind by kind (bills first), by maturity: each row its bond's
    listed = [v for v in s._list_values(u, "tto", "DİBS RV!A5:A54") if v]
    bonds = [x for x in t["isin"] if x]
    assert sorted(bonds) == sorted(listed) and len(bonds) == 19
    captions = [row[0]["t"] for row, x in zip(t["rows"][2:], t["isin"][2:]) if x is None]
    assert captions == ["Bono · kuponsuz · 2", "Sabit kuponlu · 14", "TLREF'e endeksli · 3"]
    fixed = [x for x in bonds if x.startswith("TRT") and rv(s, "D", row_of(s, x)) == "S"]
    mats = [rv(s, "E", row_of(s, x)) for x in fixed if type(rv(s, "E", row_of(s, x))) is float]
    assert mats == sorted(mats)
    # DİBS RV's own cells
    loc = numfmt.get_locale("tr")
    R = s.renderers["tto"]
    book = s.books["tto"]
    si = book.model.sheet_index["DİBS RV"]
    for isin in (FIXED, BILL, TLREF):
        r = row_of(s, isin)
        x = line(d, isin)
        for key, col in (("ycomp", "T"), ("ysimple", "S"), ("ois_asw", "Z"), ("ois_rc", "AB"), ("ois_sig", "AC"), ("dur", "AG"),
                         ("dv01", "AI"), ("hedge", "AJ"), ("cr", "AO"), ("clean", "O"), ("left", "F")):
            want = s.et.call(lambda r=r, col=col: R.cell(s._calc(u, book), si, r, col_to_index(col), loc))
            assert x[key]["t"] == want.get("t", ""), (isin, key)
            assert x[key].get("v") == want.get("v"), (isin, key)
        assert x["card"]["t"] == "▸" and isin in x["card"]["tip"] and "flag on" in x["flag"]["cls"] and x["flag"]["tip"].endswith(isin)
    # rvfair's fair values (DİBS RV's OIS curve; DİBS ASW on the FX swap implied curve) - DİBS Trading's
    summ = summary(s, u)
    for isin in (FIXED, BILL):
        x, y = line(d, isin), summary_line(summ, isin)
        assert (x["ois_fy"]["v"], x["ois_fp"]["v"]) == (y["Y"]["v"], y["Z"]["v"]) and x["ois_fy"]["tip"] == y["Y"]["tip"]
        assert (x["fx_fy"]["v"], x["fx_fp"]["v"], x["fx_asw"]["v"], x["fx_rc"]["v"]) == (y["AB"]["v"], y["AC"]["v"], y["AA"]["v"], y["AD"]["v"])
        assert x["fx_sig"]["t"] == y["AE"]["t"] and x["fx_sig"]["t"] in ("UCUZ", "PAHALI", "–")
    # the OIS curve's ASW at the bond's years: DİBS RV's AA for a fixed coupon bond (the bill is not in the curve)
    assert line(d, FIXED)["ois_curve"]["v"] == pytest.approx(rv(s, "AA", row_of(s, FIXED)), abs=0.05)
    assert rv(s, "AA", row_of(s, BILL)) == "" and type(line(d, BILL)["ois_curve"]["v"]) is float
    # a TLREF floater: its DM, no fair value, not on the zero-coupon curve - the reasons in the cells
    x = line(d, TLREF)
    assert type(x["ois_asw"]["v"]) is float and x["ois_fy"]["t"] == "–" and "TLREF'e endeksli" in x["ois_fy"]["tip"]
    assert x["z_rc"]["t"] == "–" and "TLREF'e endeksli" in x["z_rc"]["tip"] and x["fx_fy"]["t"] == "–"
    # a bond with no price: dashes that say why
    x = line(d, NO_PRICE)
    assert x["z_rc"]["t"] == "–" and "getirisi yok" in x["z_rc"]["tip"] and "Fiyat yok" in x["ois_fy"]["tip"]
    # the settings the figures read: DİBS RV's, typed in its tab
    sets = {x["ref"]: x for x in d["settings"]}
    assert set(sets) == {"DİBS RV!P2", "DİBS RV!J2", "DİBS RV!X2", "DİBS RV!Z2", "DİBS RV!B2"}
    assert sets["DİBS RV!X2"]["t"] == "ORTA" and all(x["view"] == "dibs" and x["panel"] == "B1" for x in sets.values())


def test_the_fx_figures_are_the_same_on_dibs_trading_the_card_and_genel(service):
    """The FX swap side everywhere a trader reads one is DİBS ASW's FX swap implied TRY curve (EK_FX): the summary, the
    card and Genel show the same ASW, cheap / rich, signal, fair yield and fair price - DİBS ASW's own figures on that curve."""
    s = service
    u = s.login("Genel FX")["user"]
    d, summ = genel(s, u), summary(s, u)
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
    # ... told as DİBS ASW tells it, one decimal (the last bond's: −140,1 on the recorded data of a fresh service - the
    # session's service may have had its sources changed by the tests before this one, so the sheet's own value now)
    assert summary_line(summ, "TRT130928T38")["AA"]["t"] == ("%.1f" % r_fx).replace(".", ",")


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
    leave-one-out RMSE, parameters, residuals and model yields - the bills in the fit; the fair price is
    quantcurve.quote_bond's."""
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
    assert summ["rmse"] == pytest.approx(built["rmse"], abs=1e-9) and summ["n_fit"] == built["n_fit"] == 15 and summ["n"] == built["n"] == 15
    assert summ["n_bills"] == built["n_bills"] == 2 and summ["model"] == built["model"] == "NS"
    assert summ["loo"] == pytest.approx(built["loo"], abs=1e-9) and summ["loo"] > summ["rmse"]
    p = built["params"]
    assert summ["beta"] == pytest.approx([p["b0"], p["b1"], p["b2"]], abs=1e-9) and summ["tau"] == pytest.approx([p["tau1"]], abs=1e-12)
    assert p["b3"] is None and p["tau2"] is None
    rows = dg.fit_rows(mine)
    for b in built["rows"]:
        x = rows[b["isin"]]
        assert x["resid"] == pytest.approx(b["resid"], abs=1e-9) and x["model"] == pytest.approx(b["model"], abs=1e-12), b["isin"]
        assert x["fitted"] == b["fitted"] is True
    # the page's cells are those numbers
    d = genel(s, u)
    assert d["fit"]["rmse"] == pytest.approx(built["rmse"], abs=1e-9)
    for isin in (FIXED, BILL):
        x = line(d, isin)
        assert x["z_rc"]["v"] == pytest.approx(rows[isin]["resid"], abs=1e-9) and x["z_model"]["v"] == pytest.approx(rows[isin]["model"] / 100, abs=1e-12)
        b = next(z for z in mine["in"].bonds if z.isin == isin)
        value = mine["in"].value[mine["in"].bonds.index(b)]
        assert x["z_fp"]["v"] == pytest.approx(qc.quote_bond(b, value, mine["nss"], 0.0)["fair"]["clean"], abs=1e-12)
        # a bond's model yield is its yield less its cheap / rich (the simple yield of DİBS RV!S)
        assert x["z_model"]["v"] == pytest.approx(rv(s, "S", row_of(s, isin)) - x["z_rc"]["v"] / 1e4, abs=1e-12)
    assert "uydurmada" in line(d, BILL)["z_rc"]["tip"] and "uydurmada" in line(d, FIXED)["z_rc"]["tip"]
    assert "NS sıfır kupon eğrisi (15 kâğıda uyduruldu: 13 sabit kuponlu, 2 bono)" in line(d, BILL)["z_rc"]["tip"]
    # kept: the same inputs answer the same fit; new yields refit the β with the τ held
    again = s.dibsgenel.fit(got["quant"], got["live"], got["today"])
    assert again["fit"] is s.dibsgenel.fit(got["quant"], got["live"], got["today"])["fit"]
    moved = dict(got["live"], **{"DIBSS:" + FIXED: got["live"]["DIBSS:" + FIXED] + 0.25})
    held = s.dibsgenel.fit(got["quant"], moved, got["today"])
    assert held["found"] is None and (held["nss"].tau1, held["nss"].tau2) == (again["nss"].tau1, again["nss"].tau2)
    assert dg.fit_rows(held)[FIXED]["resid"] > dg.fit_rows(again)[FIXED]["resid"] + 15


def test_the_curve_of_the_trading_list_is_steady_and_holds_its_short_end(service):
    """The trading list's curve now (DİBS RV's bonds and bills - the sheet as it stands, no figure pinned): Nelson-Siegel
    with the bills in, its β tens of per cent (Svensson's on the coupon bonds alone ran to hundreds, opposite signs), τ1
    within the bonds' years; the bills nearer the curve than that old fit put them (it read the short end off the coupon
    bonds); a day's noise of a few bp on every yield, refitted as the quant family refits a day (the τ held), moves the
    β by a point or so, not tens."""
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
    old_in = qc.BondFit(items, ("fixed",))
    old = qc.search(old_in.make, tau_min=old_in.shortest, tau_max=old_in.longest)          # (the old fit: NSS, coupon bonds)
    old_r = {b.isin: e * 1e4 for b, e in zip(old_in.bonds, old_in.evaluate(old["nss"])[0])}
    bills = [i for i, x in rows.items() if x["kind"] == "bill"]
    assert bills and all(rows[i]["fitted"] for i in bills) and sum(abs(rows[i]["resid"]) for i in bills) < sum(abs(old_r[i]) for i in bills)
    rnd = random.Random(3)
    moved = qc.BondFit([(b, v, y + rnd.gauss(0, 0.0003), c) for b, v, y, c in items])
    nxt = qc.refit(moved.make, res["nss"], res["nss"].beta, iters=5)["nss"]
    assert nxt.k == qc.NS and max(abs(a - b) for a, b in zip(nxt.beta, res["nss"].beta)) * 100 < 2.0


def test_too_few_bonds_no_fit_and_why(service):
    items = [(qc.Bond("TRT1", "", "fixed", dt.date(2028, 3, 15), 36.8, 2), dt.date(2026, 11, 4), 0.36, "simple")]
    res = dg.zero_fit(items)
    assert not res["ok"] and "en az 6 kâğıdın (sabit kuponlu ya da bono)" in res["why"]
    assert dg.fit_summary(res) == {"ok": False, "why": res["why"]}


# ---------------------------------------------------------------------------------------------- following the bonds
def test_a_bond_added_in_the_middle_is_followed_by_its_isin(module_service):
    """The trading list changes: a bond added in an empty row in the middle comes in its group by maturity; every other
    bond's figures stay its own (keyed by ISIN, not by row); taken off, it is gone."""
    s = module_service
    u = s.login("Genel Takip")["user"]
    before = genel(s, u)
    # (a bond's own figures; what reads a fitted curve moves when a fixed coupon bond comes into the fits)
    own = ("bond", "isin", "due", "left", "src", "bid", "ask", "last", "clean", "ycomp", "ysimple", "ois_asw", "fx_asw", "dur", "dv01",
           "hedge", "cr", "card", "flag")
    keep = {isin: {k: line(before, isin)[k].get("t") for k in own} for isin in (FIXED, BILL, TLREF)}
    empty = next(r for r in range(5, 55) if not rv(s, "A", r))
    new = "TRT190128T14"
    assert s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % empty, "value": new}])["errors"] == []
    try:
        after = genel(s, u)
        assert new in after["table"]["isin"]
        for isin, cells in keep.items():
            assert {k: line(after, isin)[k].get("t") for k in own} == cells, isin
        # in its kind's group, by maturity
        t = after["table"]
        groups, cap = {}, None
        for row, x in zip(t["rows"][2:], t["isin"][2:]):
            if x is None:
                cap = row[0]["t"].split(" · ")[0]
            else:
                groups.setdefault(cap, []).append(x)
        kind = {"bill": "Bono", "zero": "Bono", "fixed": "Sabit kuponlu", "float": "TLREF'e endeksli"}[bd.by_isin(new)["kind"]]
        assert new in groups[kind] and line(after, new)["isin"]["t"] == new
        mats = [bd.by_isin(x)["maturity"] for x in groups[kind]]
        assert mats == sorted(mats)
    finally:
        s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % empty, "value": ""}])
    assert new not in genel(s, u)["table"]["isin"]


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
    assert fit["ok"] and fit["n_fit"] == 15 and 0 < fit["rmse"] < 100 and len(fit["beta"]) == 3 and len(fit["tau"]) == 1
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
    assert body["ok"] and body["table"]["rows"] and body["fit"]["ok"] and body["chart"]["series"] and body["tabs"][0] == {"id": "dibs-genel", "title": "Genel"}
    assert client.get("/api/dibs/genel", headers=ANON).status_code == 401
    nav = client.get("/api/nav", headers=h).json()["pages"]
    assert [p["id"] for p in nav if p.get("menu") == dg.MENU_ID] == ["dibs-genel", "dibs", "asw"]
    for path in ("/static/js/pages/dibsgenel.js", "/static/js/menu.js"):
        assert client.get(path).status_code == 200, path
    assert client.post("/api/panels", json={"items": [{"view": m["view"], "panel": m["panel"], "key": m["key"]} for m in dg.MIRRORS]},
                       headers=h).status_code == 200
