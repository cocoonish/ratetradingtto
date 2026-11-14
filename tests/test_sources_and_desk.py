"""The order of Bloomberg pricing sources (live sheets and the history), ASW against FX swaps, the pricing tables
of the Forward page, the gold calculator's free column, z-scores of the carry table, and the broker chat's
board reset / ticked delete / the trades page's entry over a period."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from conftest import cell, make_service
from tto import extras as ex
from tto import volcarry as vc
from tto.history import SeriesDef
from tto.marketdata.base import bdp_key
from tto.server import create_app
from tto.service import ServiceError


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def rows_of(svc, kind):
    return [r for r in svc.sources()["rows"] if r["curve"] == kind]


# ---------------------------------------------------------------------------------------------- a backup fills gaps
def test_a_backup_fills_only_the_days_the_main_source_misses():
    d = SeriesDef("ois", "1M", "TYSOA GFOF Curncy", "PX_LAST", ["TYSOA Curncy"])
    main = {"2026-10-01": 36.0, "2026-10-02": 36.2, "2026-10-05": 36.5}
    backup = {"2026-09-30": 35.0, "2026-10-01": 35.9, "2026-10-02": 36.0, "2026-10-03": 36.3, "2026-10-05": 36.4, "2026-10-06": 36.1}
    ticker, points, used = d.merged({"TYSOA GFOF Curncy|PX_LAST": main, "TYSOA Curncy|PX_LAST": backup})
    assert ticker == "TYSOA GFOF Curncy"
    # the main source's own closes stand; a missing day is the main level plus what the backup did since the day before
    assert {k: points[k] for k in main} == main
    assert points["2026-10-03"] == pytest.approx(36.2 + (36.3 - 36.0))
    assert points["2026-10-06"] == pytest.approx(36.5 + (36.1 - 36.4))
    assert points["2026-09-30"] == pytest.approx(36.0 + (35.0 - 35.9))          # before the main source began: the day after
    assert used == {"2026-10-03": "TYSOA Curncy", "2026-10-06": "TYSOA Curncy", "2026-09-30": "TYSOA Curncy"}
    # no main source at all: the backup as it is; nothing in common: the main source alone
    assert d.merged({"TYSOA Curncy|PX_LAST": backup}) == ("TYSOA Curncy", backup, {})
    assert d.merged({"TYSOA GFOF Curncy|PX_LAST": {"2026-10-01": 1.0}, "TYSOA Curncy|PX_LAST": {"2026-10-02": 2.0}})[1] == {"2026-10-01": 1.0}
    assert d.pick({"TYSOA GFOF Curncy|PX_LAST": main, "TYSOA Curncy|PX_LAST": backup})[1] == points


# ---------------------------------------------------------------------------------------------- the source order
def test_the_live_quotes_go_through_the_source_order(svc):
    book = svc.books["tto"]
    assert book.left_out == []
    src = svc.sources()
    assert [(c["id"], c["sources"], c["default"]) for c in src["curves"]] == [
        ("ois", ["GFOF"], ["GFOF"]), ("off", ["ICPL"], ["ICPL"]), ("xccy", ["ICPL"], ["ICPL"])]
    assert [len(rows_of(svc, k)) for k in ("ois", "off", "xccy")] == [18, 11, 10]
    # offline the pages are the saved file: the cells that read the quotes keep what Excel saved
    for ref in ("OIS_MAIN!B9", "OIS_MAIN!B26", "OIS_MAIN!AU13", "Forward!I6", "Forward!K16", "Forward!I17", "Forward!D125", "Forward!F125"):
        si, rc = book.cell(ref)
        assert cell(svc, ref) == book.model.sheets[si].cached[rc], ref
    # the source in use per tenor: OIS from GFOF (the offline quotes have it), offshore from the workbook's BGN ticker
    ois = {r["tenor"]: r for r in rows_of(svc, "ois")}
    assert (ois["3M"]["source"], ois["3M"]["ticker"], ois["3M"]["rank"], ois["3M"]["excel"]) == ("GFOF", "TYSOC GFOF Curncy", 1, "TYSOC Curncy")
    off = {r["tenor"]: r for r in rows_of(svc, "off")}
    assert (off["1W"]["source"], off["1W"]["ticker"], off["1W"]["rank"]) == ("Excel (BGN)", "TRYI1W BGN Curncy", 5)
    assert (off["1W"]["bid"], off["1W"]["ask"]) == (cell(svc, "Forward!I8"), cell(svc, "Forward!K8"))
    # ICAP quoting both sides takes over; a source with one side only does not (a row never mixes two sources)
    svc.provider.update({bdp_key("TRYI1W ICPL Curncy", "BID"): 30.5, bdp_key("TRYI1W ICPL Curncy", "ASK"): 31.0,
                         bdp_key("TRYI2W ICPL Curncy", "BID"): 30.7})
    svc.books["tto"].engine.reset()
    off = {r["tenor"]: r for r in rows_of(svc, "off")}
    assert (off["1W"]["source"], off["1W"]["ticker"], off["1W"]["bid"], off["1W"]["ask"]) == ("ICPL", "TRYI1W ICPL Curncy", 30.5, 31.0)
    assert off["2W"]["source"] == "Excel (BGN)"


def test_the_source_order_is_set_for_everyone_and_kept(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Kaynak Masa")["user"]
        out = s.set_sources(u, {"ois": ["gfof", " bgn "], "off": "CMPN, ICPL", "xccy": []})
        assert [(c["id"], c["sources"]) for c in out["curves"]] == [("ois", ["GFOF", "BGN"]), ("off", ["CMPN", "ICPL"]), ("xccy", [])]
        assert [cell(s, "EK_KAYNAK!%s%d" % (c, r)) for r in (4, 5, 6) for c in "BCDE"] == [
            "GFOF", "BGN", None, None, "CMPN", "ICPL", None, None, None, None, None, None]
        # the history follows: the listed sources first, the workbook's own ticker last
        by = {}
        for d in s.history.snapshot()["defs"]:
            by.setdefault(d.group, []).append(d)
        assert (by["ois"][2].ticker, by["ois"][2].alts) == ("TYSOA GFOF Curncy", ["TYSOA BGN Curncy", "TYSOA Curncy"])
        assert (by["off"][4].ticker, by["off"][4].alts) == ("TRYI1M CMPN Curncy", ["TRYI1M ICPL Curncy", "TRYI1M BGN Curncy"])
        assert (by["xccy"][0].ticker, by["xccy"][0].alts) == ("TRYSAQ1 BGN Curncy", [])
        assert s.history.matrix()["source"]["ois"] == "GFOF → BGN → Excel (Curncy)"
        # an empty list: the workbook's ticker only
        assert {r["source"] for r in out["rows"] if r["curve"] == "xccy"} == {"Excel (BGN)"}
        for bad in ({"ois": ["GF OF!"]}, {"off": ["A"]}, {"ois": ["A1", "B2", "C3", "D4", "E5"]}, {}):
            with pytest.raises(ServiceError):
                s.set_sources(u, bad)
    finally:
        s.stop()
    s = make_service(tmp_path)                                                   # a restart keeps it
    try:
        assert [(c["id"], c["sources"]) for c in s.sources()["curves"]] == [("ois", ["GFOF", "BGN"]), ("off", ["CMPN", "ICPL"]), ("xccy", [])]
        with TestClient(create_app(s)) as client:
            hdr = {"X-TTO-User": s.login("Kaynak HTTP")["user"]}
            assert client.get("/api/sources", headers=hdr).json()["curves"][0]["sources"] == ["GFOF", "BGN"]
            res = client.post("/api/sources", json={"lists": {"ois": ["GFOF"], "off": ["ICPL"], "xccy": ["ICPL"]}}, headers=hdr)
            assert res.status_code == 200 and [c["sources"] for c in res.json()["curves"]] == [["GFOF"], ["ICPL"], ["ICPL"]]
            assert client.post("/api/sources", json={"lists": {"ois": ["?"]}}, headers=hdr).status_code == 400
    finally:
        s.stop()


def test_the_unknown_tickers_of_a_listed_source_are_explained(svc):
    notes = dict((rx.pattern, n) for rx, n in svc._UNKNOWN_NOTES)
    doubled = next(rx for rx, _ in svc._UNKNOWN_NOTES if "\\1" in rx.pattern)
    assert doubled.search("TRYION ICPL Curncy Curncy") and not doubled.search("TRYION ICPL Curncy")
    assert "Veri kaynakları" in svc._SOURCE_NOTE and notes


# ---------------------------------------------------------------------------------------------- ASW against FX swaps
def test_asw_against_the_fx_swap_curve(svc):
    v = svc.view(None, "asw")
    p = {q["id"]: q for q in v["panels"]}
    curve = p["fxc"]["data"]["rows"]
    first = next(r for r in curve if r and r[0].get("t") == "1M")
    assert [c.get("t") for c in first[:3]] == ["1M", "TRYI1M", "TRYI1M BGN Curncy"]          # ICAP has no offline quote: BGN
    fx_1m = cell(svc, "EK_FX!D6", book="asw")
    assert fx_1m == pytest.approx((svc.provider.snapshot[bdp_key("TRYI1M BGN Curncy", "BID")]
                                   + svc.provider.snapshot[bdp_key("TRYI1M BGN Curncy", "ASK")]) / 2)
    assert cell(svc, "EK_FX!E6", book="asw") == cell(svc, "ASW!C65", book="asw")
    tbl = p["tbl"]["data"]
    assert tbl["c"][-2:] == ["ASW FX", "FX−OIS"]
    head = tbl["rows"][tbl["r"].index(6)]
    assert [c["t"] for c in head[-2:]] == ["ASW FX (bp)", "FX − OIS (bp)"]
    ok = [(tbl["rows"][i][-3]["t"], tbl["rows"][i][-2], tbl["rows"][i][-1]) for i, r in enumerate(tbl["r"]) if 7 <= r <= 56]
    priced = [(fx, diff) for status, fx, diff in ok if status == "OK"]
    assert priced and all(isinstance(fx.get("v"), float) for fx, _ in priced)
    assert any(abs(diff["v"]) > 1.0 for _, diff in priced)                    # another curve, other spreads
    # the same bond with the OIS quotes typed in as the FX rates gives the OIS ASW back: the sheet's own calculation
    r7 = cell(svc, "ASW!R7", book="asw")
    i7 = tbl["r"].index(7)
    assert tbl["rows"][i7][-1]["v"] == pytest.approx(tbl["rows"][i7][-2]["v"] - r7)


# ---------------------------------------------------------------------------------------------- the Forward page's rates
USD, EUR = ex.FR_USD, ex.FR_EUR               # title rows of the USDTRY and the EURTRY table of the Forward page


def row_of(t, name):
    """Row of a curve ("Offshore", "OIS", "VİOP", "RET", "Elle") in the table whose title is in row ``t``."""
    return t + 3 + (list(ex.FR_NAMES) + ["Elle"]).index(name)


def test_the_value_date_tables_price_like_the_forward_sheet(svc):
    """USDTRY and EURTRY, one below the other: each curve's TRY bid / mid / ask, the outright, the swap points and the
    points per day - the numbers of the Forward sheet's own tables (its USDTRY daily points included)."""
    for t, fwd, points in ((USD, 30, 36), (EUR, 42, 48)):
        for k, name in enumerate(ex.FR_NAMES):
            r = row_of(t, name)
            assert cell(svc, "EK_FWD!A%d" % r) == name
            mine = [cell(svc, "EK_FWD!%s%d" % (c, r)) for c in "EFGHIJKLM"]
            sheet = [cell(svc, "Forward!%s%d" % (c, fwd + k)) for c in "DEF"] + [cell(svc, "Forward!%s%d" % (c, points + k)) for c in "DEFHIJ"]
            assert mine == pytest.approx(sheet, rel=1e-12)
            bid, mid, ask = (cell(svc, "EK_FWD!%s%d" % (c, r)) for c in "BCD")
            assert bid < mid < ask and mid == pytest.approx((bid + ask) / 2)
        # the "Elle" row starts from RET
        assert [cell(svc, "EK_FWD!%s%d" % (c, row_of(t, "Elle"))) for c in "BCDEFG"] == \
            pytest.approx([cell(svc, "EK_FWD!%s%d" % (c, row_of(t, "RET"))) for c in "BCDEFG"], rel=1e-12)
    assert cell(svc, "EK_FWD!D%d" % (USD + 1)) == cell(svc, "Forward!U27") and cell(svc, "EK_FWD!D%d" % (EUR + 1)) == cell(svc, "Forward!AA27")
    assert cell(svc, "EK_FWD!J%d" % (USD + 1)) == pytest.approx((cell(svc, "Forward!W27") + cell(svc, "Forward!Y27")) * 50)
    heads = [cell(svc, "EK_FWD!%s%d" % (c, USD + 2)) for c in "ABCDEFGHIJKLM"]
    assert heads == ["Eğri", "TRY bid %", "TRY mid %", "TRY ask %", "USDTRY bid", "USDTRY mid", "USDTRY ask", "Puan bid", "Puan mid",
                     "Puan ask", "P/gün bid", "P/gün mid", "P/gün ask"]
    page = svc.view(None, "forward")
    panels = {p["id"]: p for p in page["panels"]}
    tab = next(s for s in page["sections"] if s["id"] == "fwd")["panels"]
    assert tab == ["FR1", "FR2", "FR3", "FR4", "B16", "B18"]
    assert [panels[p]["title"].split("  ·  ")[0] for p in tab[:4]] == ["USDTRY FORWARD", "EURTRY FORWARD", "SERBEST FORWARD",
                                                                     "TRY FAİZLERİ VADELERE GÖRE"]
    assert all(not panels[p].get("error") for p in tab)
    assert not {"B14", "B15", "B15b", "B17"} & set(panels)                      # the sheet's own tables: among the helpers


def test_a_rate_typed_reprices_both_pairs_for_its_writer_only(svc):
    u = svc.login("Vade Faiz")["user"]
    ois, eur_ois = row_of(USD, "OIS"), row_of(EUR, "OIS")
    res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % ois, "value": "40"}, {"ref": "EK_FWD!D%d" % ois, "value": "41"}])
    assert res["errors"] == []
    i = USD + 1
    spot, days, usd_bid, usd_ask = (cell(svc, "EK_FWD!%s%d" % (c, i), u) for c in "FDHL")
    assert cell(svc, "EK_FWD!E%d" % ois, u) == pytest.approx(spot * (1 + 0.40 / 360 * days) / (1 + usd_ask / 100 / 360 * days))
    assert cell(svc, "EK_FWD!G%d" % ois, u) == pytest.approx(spot * (1 + 0.41 / 360 * days) / (1 + usd_bid / 100 / 360 * days))
    assert cell(svc, "EK_FWD!C%d" % ois, u) == pytest.approx(40.5)
    # the EURTRY table takes the TRY rates of the USDTRY one ...
    e = EUR + 1
    spot, days, eur_ask = (cell(svc, "EK_FWD!%s%d" % (c, e), u) for c in "FDL")
    assert cell(svc, "EK_FWD!B%d" % eur_ois, u) == 40.0
    assert cell(svc, "EK_FWD!E%d" % eur_ois, u) == pytest.approx(spot * (1 + 0.40 / 360 * days) / (1 + eur_ask / 100 / 360 * days))
    # ... and can have its own
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % eur_ois, "value": "39"}])
    assert cell(svc, "EK_FWD!B%d" % eur_ois, u) == 39.0 and cell(svc, "EK_FWD!B%d" % ois, u) == 40.0
    assert cell(svc, "EK_FWD!E%d" % ois) == cell(svc, "Forward!D31")              # nobody else's
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % ois, "value": ""}, {"ref": "EK_FWD!D%d" % ois, "value": ""},
                              {"ref": "EK_FWD!B%d" % eur_ois, "value": ""}])
    assert cell(svc, "EK_FWD!E%d" % ois, u) == pytest.approx(cell(svc, "Forward!D31"), rel=1e-12)    # blanked: back to the curve
    assert cell(svc, "EK_FWD!E%d" % eur_ois, u) == pytest.approx(cell(svc, "Forward!D43"), rel=1e-12)


def test_a_rate_of_ones_own_from_a_curve_with_a_mid_or_a_spread(svc):
    u = svc.login("Elle Faiz")["user"]
    s, elle, ois = row_of(USD, "Elle") + 1, row_of(USD, "Elle"), row_of(USD, "OIS")
    assert [cell(svc, "EK_FWD!%s%d" % (c, s)) for c in "ABCEG"] == ["Elle ayarı", "RET", "Mid %", "Spread bp", "Genişlik bp"]
    res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % s, "value": "OIS"}, {"ref": "EK_FWD!F%d" % s, "value": "25"}])
    assert res["errors"] == []
    bid, mid, ask = (cell(svc, "EK_FWD!%s%d" % (c, ois), u) for c in "BCD")
    got = [cell(svc, "EK_FWD!%s%d" % (c, elle), u) for c in "BCD"]
    assert got == pytest.approx([bid + 0.25, mid + 0.25, ask + 0.25])           # the curve's mid + 25 bp, the curve's width
    eur = row_of(EUR, "Elle")
    assert [cell(svc, "EK_FWD!%s%d" % (c, eur), u) for c in "BCD"] == pytest.approx(got)      # EURTRY follows
    # a mid typed is taken as it is (the spread no longer counts), and a width of one's own
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!D%d" % s, "value": "40"}, {"ref": "EK_FWD!H%d" % s, "value": "50"}])
    assert [cell(svc, "EK_FWD!%s%d" % (c, elle), u) for c in "BCD"] == pytest.approx([39.75, 40.0, 40.25])
    i = USD + 1
    spot, days, usd_ask = (cell(svc, "EK_FWD!%s%d" % (c, i), u) for c in "FDL")
    assert cell(svc, "EK_FWD!E%d" % elle, u) == pytest.approx(spot * (1 + 0.3975 / 360 * days) / (1 + usd_ask / 100 / 360 * days))
    # the bid / ask of the row itself can be typed over too
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % elle, "value": "39"}])
    assert cell(svc, "EK_FWD!C%d" % elle, u) == pytest.approx(39.625)
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % elle, "value": ""}, {"ref": "EK_FWD!D%d" % s, "value": ""},
                              {"ref": "EK_FWD!H%d" % s, "value": ""}, {"ref": "EK_FWD!B%d" % s, "value": "viop"}])
    assert cell(svc, "EK_FWD!B%d" % s, u) == "VİOP"                             # as the list writes it
    viop = row_of(USD, "VİOP")
    assert [cell(svc, "EK_FWD!%s%d" % (c, elle), u) for c in "BCD"] == \
        pytest.approx([cell(svc, "EK_FWD!%s%d" % (c, viop), u) + 0.25 for c in "BCD"])
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % s, "value": "Yok"}])
    assert [cell(svc, "EK_FWD!%s%d" % (c, elle), u) for c in "BCE"] == ["", "", ""]      # no curve: no price rather than a wrong one


def test_the_free_forward_list_takes_spot_and_rates_from_the_curves(svc):
    u = svc.login("Serbest Fwd")["user"]
    h = ex.FR_LIST + 2
    r1, r2, r3, r4 = h + 1, h + 2, h + 3, h + 4
    assert [cell(svc, "EK_FWD!%s%d" % (c, h)) for c in "ABCDEFGHI"] == ["Parite", "Başlangıç", "Bitiş", "Gün", "Spot", "Major %",
                                                                         "Minor %", "Swap", "Forward"]
    assert cell(svc, "EK_FWD!B%d" % r1) == "" and cell(svc, "EK_FWD!I%d" % r1) == ""            # an empty row waits for its date
    value_date = cell(svc, "Forward!D2")
    res = svc.set_inputs(u, "tto", [
        {"ref": "EK_FWD!C%d" % r1, "value": value_date},                                          # spot -> the value date
        {"ref": "EK_FWD!B%d" % r2, "value": cell(svc, "Forward!D2") - 185}, {"ref": "EK_FWD!C%d" % r2, "value": value_date},
        {"ref": "EK_FWD!A%d" % r3, "value": "EURTRY"}, {"ref": "EK_FWD!C%d" % r3, "value": value_date},
        {"ref": "EK_FWD!C%d" % r4, "value": value_date + 1500}])
    assert res["errors"] == []
    usd_spot_date = cell(svc, "EK_FWD!B%d" % r1, u)
    assert usd_spot_date == pytest.approx(cell(svc, "Forward!D2") - cell(svc, "Forward!U27"))      # starts at the spot date
    assert cell(svc, "EK_FWD!D%d" % r1, u) == cell(svc, "Forward!U27")
    assert cell(svc, "EK_FWD!E%d" % r1, u) == cell(svc, "Forward!F2")                            # the spot itself
    ret = row_of(USD, "RET")
    assert cell(svc, "EK_FWD!G%d" % r1, u) == pytest.approx(cell(svc, "EK_FWD!C%d" % ret))       # RET mid at the value date
    assert cell(svc, "EK_FWD!F%d" % r1, u) == pytest.approx(cell(svc, "Forward!X27") * 100, rel=1e-3)
    # the four curves at the end date, side by side: those of the value-date row of the rates by tenor
    assert [cell(svc, "EK_FWD!%s%d" % (c, r1), u) for c in "JKLM"] == \
        pytest.approx([cell(svc, "EK_FWD!%s%d" % (c, ex.FR_TENOR + 2)) for c in "DEFG"], rel=1e-12)
    # mid rates against the average of the bid and the ask forwards of the table: the same forward but for a hair
    assert cell(svc, "EK_FWD!I%d" % r1, u) == pytest.approx(cell(svc, "EK_FWD!F%d" % ret), rel=1e-6)
    # a later start: the spot is carried to it, the period's rates make the same end outright
    fwd_start = cell(svc, "EK_FWD!E%d" % r2, u)
    assert fwd_start > cell(svc, "Forward!F2")
    assert cell(svc, "EK_FWD!I%d" % r2, u) == pytest.approx(cell(svc, "EK_FWD!I%d" % r1, u), rel=1e-12)
    assert cell(svc, "EK_FWD!H%d" % r2, u) == pytest.approx((cell(svc, "EK_FWD!I%d" % r2, u) - fwd_start) * 10000)
    # EURTRY: its own spot, spot date and EUR rate
    assert cell(svc, "EK_FWD!E%d" % r3, u) == cell(svc, "Forward!G2")
    assert cell(svc, "EK_FWD!D%d" % r3, u) == cell(svc, "Forward!AA27")
    assert cell(svc, "EK_FWD!I%d" % r3, u) == pytest.approx(cell(svc, "EK_FWD!F%d" % row_of(EUR, "RET")), rel=1e-6)
    # four years out RET has no rate (its last node is 2Y): no forward rather than a flat one; another curve has one
    assert cell(svc, "EK_FWD!M%d" % r4, u) == "" and cell(svc, "EK_FWD!I%d" % r4, u) == ""
    assert isinstance(cell(svc, "EK_FWD!K%d" % r4, u), float)
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % (ex.FR_LIST + 1), "value": "OIS"}])
    assert cell(svc, "EK_FWD!G%d" % r4, u) == pytest.approx(cell(svc, "EK_FWD!K%d" % r4, u))
    assert isinstance(cell(svc, "EK_FWD!I%d" % r4, u), float)
    # every one of them can be typed over
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!E%d" % r1, "value": "50"}, {"ref": "EK_FWD!F%d" % r1, "value": "4"},
                              {"ref": "EK_FWD!G%d" % r1, "value": "36"}])
    days = cell(svc, "EK_FWD!D%d" % r1, u)
    assert cell(svc, "EK_FWD!I%d" % r1, u) == pytest.approx(50 * (1 + 0.36 * days / 360) / (1 + 0.04 * days / 360))
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!E%d" % r1, "value": ""}])
    assert cell(svc, "EK_FWD!E%d" % r1, u) == cell(svc, "Forward!F2")


def test_the_try_rates_by_tenor_side_by_side(svc):
    t = ex.FR_TENOR
    assert [cell(svc, "EK_FWD!%s%d" % (c, t + 1)) for c in "ABCDEFG"] == ["Vade", "Tarih", "Gün", "Offshore %", "OIS %", "VİOP %", "RET %"]
    v = t + 2                                                                   # the value date: the sheet's own rates
    assert cell(svc, "EK_FWD!C%d" % v) == cell(svc, "Forward!G22")
    assert [cell(svc, "EK_FWD!%s%d" % (c, v)) for c in "DEFG"] == pytest.approx(
        [cell(svc, "Forward!J22") * 100, cell(svc, "Forward!P24") * 100, cell(svc, "Forward!D18") * 100,
         (cell(svc, "Forward!W48") + cell(svc, "Forward!X48")) * 50], rel=1e-12)
    assert cell(svc, "EK_FWD!H%d" % v) == pytest.approx((cell(svc, "EK_FWD!D%d" % v) - cell(svc, "EK_FWD!E%d" % v)) * 100)
    tenors = {cell(svc, "EK_FWD!A%d" % r): r for r in range(t + 3, t + 3 + len(ex.FR_TENORS))}
    assert list(tenors) == [x[0] for x in ex.FR_TENORS]
    assert cell(svc, "EK_FWD!C%d" % tenors["1W"]) == 7
    assert cell(svc, "EK_FWD!B%d" % tenors["3M"]) == cell(svc, "EK_FWD!B7")      # as the desk's matrix dates 3M
    assert cell(svc, "EK_FWD!F%d" % tenors["2Y"]) == "" and cell(svc, "EK_FWD!I%d" % tenors["2Y"]) == ""   # VİOP ends near 1Y
    assert all(isinstance(cell(svc, "EK_FWD!%s%d" % (c, tenors["2Y"])), float) for c in "DEG")
    u = svc.login("Vade Tablosu")["user"]
    free = t + 3 + len(ex.FR_TENORS)
    assert cell(svc, "EK_FWD!D%d" % free) == ""
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B%d" % free, "value": cell(svc, "Forward!D2")}])
    assert [cell(svc, "EK_FWD!%s%d" % (c, free), u) for c in "CDEFG"] == [cell(svc, "EK_FWD!%s%d" % (c, v)) for c in "CDEFG"]


def test_a_value_saved_where_an_input_used_to_be_is_dropped(svc):
    """The value-date rates were once in rows 33-42: what a user had typed there must not land on whatever stands
    there now, nor be listed as theirs."""
    u = svc.login("Eski Girdi")["user"]
    svc.store.set_user_inputs(u, "tto", {"EK_FWD!B37": 40.0, "EK_FWD!D35": 4.5, "EK_FWD!B47": 41.0})
    refs = [i["ref"] for i in svc.my_inputs(u)["inputs"]]
    assert "EK_FWD!B37" not in refs and "EK_FWD!D35" not in refs and "EK_FWD!B47" in refs
    assert cell(svc, "EK_FWD!B37", u) is None and cell(svc, "EK_FWD!B47", u) == 41.0
    assert set(svc.store.user_inputs(u, "tto")) == {("tto", "EK_FWD!B47")}     # gone from the store as well


def test_the_gold_calculators_free_column_waits_for_its_date(svc):
    u = svc.login("Altın Serbest")["user"]
    assert cell(svc, "EK_XAU!E41") is None and cell(svc, "EK_XAU!E48") == ""
    # its date, the spot and a gold swap rate typed (offline the file has no gold quotes): spot · (1 + swap · g / 360)
    svc.set_inputs(u, "tto", [{"ref": "EK_XAU!E41", "value": "15.01.2027"}, {"ref": "EK_XAU!E44", "value": "4000"},
                              {"ref": "EK_XAU!E47", "value": "1,5"}])
    spot, days = cell(svc, "EK_XAU!E44", u), cell(svc, "EK_XAU!E41", u) - cell(svc, "EK_XAU!B9", u)
    assert cell(svc, "EK_XAU!E48", u) == pytest.approx(spot * (1 + 1.5 / 100 * days / 360))
    svc.set_inputs(u, "tto", [{"ref": "EK_XAU!E41", "value": ""}])
    assert cell(svc, "EK_XAU!E48", u) == ""                                                   # no date: no forward again


# ---------------------------------------------------------------------------------------------- z-scores
def test_zscores_of_a_level():
    levels = [10.0, 12.0, 11.0, 13.0, 12.0] * 6                                   # 30 closes
    z = vc.zscores(levels, 15.0)
    mean = sum(levels) / len(levels)
    assert z["60"] == z["120"] == z["250"] == pytest.approx((15.0 - mean) / vc.stdev(levels))
    assert vc.zscores(levels, None)["60"] == pytest.approx((12.0 - mean) / vc.stdev(levels))   # no market: the last close
    assert vc.zscores(levels[:10], 15.0) == {"60": None, "120": None, "250": None}             # too few closes
    assert vc.zscores([5.0] * 40, 6.0)["60"] is None                                          # no spread at all
    long = list(range(300))
    z = vc.zscores([float(x) for x in long], 300.0)
    assert z["60"] == pytest.approx((300.0 - sum(long[-60:]) / 60) / vc.stdev([float(x) for x in long[-60:]]))
    row = vc.carry_row(vc.item_of("fly", ["1Y", "2Y", "3Y"]), 51.0, {"a": 25.6}, {"a": 22}, {}, {}, 60)
    assert row["z"] == {"60": None, "120": None, "250": None} and row["closes"] == 0


# ---------------------------------------------------------------------------------------------- broker chat
CHAT = "\n".join(["SAFA YILMAZ", "6m ois 35.90/35.95", "09:00:00", "1y ois 35.00/35.15", "09:05:00", "6m ois 36.00 bid", "09:10:00"])


def test_the_board_is_reset_and_the_log_keeps_its_lines(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("Broker Sıfır")["user"]
        day = s.today_iso()
        s.broker_add(u, CHAT, day, "", None)
        before = s.broker(u, day)
        assert {r["label"] for r in before["board"]} == {"6M", "1Y"} and len(before["rows"]) >= 3
        six = next(r for r in before["board"] if r["label"] == "6M")
        # one instrument
        after = s.broker_reset(u, day, six["key"])
        assert {r["label"] for r in after["board"]} == {"1Y"} and len(after["rows"]) == len(before["rows"])
        assert [(x["key"], x["label"]) for x in after["resets"]] == [(six["key"], "6M")]
        # all of them; then something said later is on the board again
        assert s.broker_reset(u, day)["board"] == []
        s.broker_add(u, "SAFA YILMAZ\n2y ois 34.00/34.20\n23:59:59", day, "", None)
        assert [r["label"] for r in s.broker(u, day)["board"]] == ["2Y"]
        # taken back, the last first
        s.broker_reset(u, day, undo=True)
        assert {r["label"] for r in s.broker(u, day)["board"]} == {"1Y", "2Y"}
        s.broker_reset(u, day, undo=True)
        assert {r["label"] for r in s.broker(u, day)["board"]} == {"6M", "1Y", "2Y"}
        with pytest.raises(ServiceError):
            s.broker_reset(u, day, undo=True)
        # lines ticked in the log are deleted together
        ids = [q["id"] for q in s.broker(u, day)["rows"] if q.get("label") == "6M"]
        assert len(ids) == 2 and s.broker_delete_many(u, ids + [999999, "x"]) == {"deleted": 2}
        assert {r["label"] for r in s.broker(u, day)["board"]} == {"1Y", "2Y"}
        # a line kept within the very second of a reset (typed without a time, it takes the moment it was entered)
        # is the reset's; one said in that second but kept after it stands
        s.broker_add(u, "18m ois 35.10/35.30", day, "", None)
        row = next(q for q in s.broker(u, day)["rows"] if q.get("label") == "18M")
        s.broker_reset(u, day)
        resets = s.store.get("broker.resets")
        resets[-1]["at"] = "%s %s" % (row["date"], row["time"])
        s.store.put("broker.resets", resets)
        assert "18M" not in [r["label"] for r in s.broker(u, day)["board"]]
        s.broker_add(u, "%s 9m ois 35.40/35.60" % row["time"], day, "", None)
        assert "9M" in [r["label"] for r in s.broker(u, day)["board"]]
        s.broker_reset(u, day, undo=True)
        s.broker_delete_many(u, [q["id"] for q in s.broker(u, day)["rows"] if q.get("label") in ("18M", "9M")])
        # a line kept before the reset is cleared whatever time it carries (here 23:59:59: a clock ahead of ours)
        assert s.broker_reset(u, day)["board"] == []
        s.broker_reset(u, day, undo=True)
        with TestClient(create_app(s)) as client:
            hdr = {"X-TTO-User": u}
            res = client.post("/api/broker/reset", json={"date": day}, headers=hdr)
            assert res.status_code == 200 and res.json()["board"] == []
            back = client.post("/api/broker/reset", json={"date": day, "undo": True}, headers=hdr).json()["board"]
            assert {r["label"] for r in back} == {"1Y", "2Y"}
            one = s.broker(u, day)["rows"][0]["id"]
            assert client.post("/api/broker/delete", json={"ids": [one]}, headers=hdr).json() == {"deleted": 1}
    finally:
        s.stop()


# ---------------------------------------------------------------------------------------------- the trades page
def test_a_period_up_to_today_can_take_todays_trades(svc):
    u = svc.login("Aralık Giriş")["user"]
    today = svc.today_iso()
    week = svc.blotter(u, "2026-11-02", locale=None, date_to=today)
    assert week["ranged"] and week["can_enter"] and not week["is_today"]
    assert svc.blotter(u)["can_enter"] and not svc.blotter(u, "2026-10-01", date_to="2026-10-31")["can_enter"]
    assert not svc.blotter(u, "2026-10-30")["can_enter"]


# ---------------------------------------------------------------------------------------------- FX swap points in the chat
def test_fx_swap_points_are_read_as_such():
    from tto import brokerchat as bc

    def q(text):
        r = bc.parse_quote(text)
        return None if r is None else (r["product"], r["label"], r["unit"], r["event"], r["bid"], r["ask"], r["price"], r["side"])

    assert q("t/n 380/385") == ("FX", "T/N", "pts", "quote", 380.0, 385.0, None, None)
    assert q("t/n 375/90") == ("FX", "T/N", "pts", "quote", 375.0, 390.0, None, None)                # the offer written short
    assert q("o/n 1175 bid lcl")[:6] == ("FX", "O/N", "pts", "quote", 1175.0, None) and bc.parse_quote("o/n 1175 bid lcl")["note"] == "lcl"
    assert q("o/n 1.175 bid")[4] == 1175.0 and q("tn 380 trading")[3:7] == ("trade", None, None, 380.0)
    assert q("t/n gvn")[3] == "trade" and q("t/n gvn")[7] == "bid" and q("o/n ref , no deal here")[3] == "ref"
    assert q("s/n 375 paid")[:2] == ("FX", "S/N") and q("s/n 375 paid")[6:] == (375.0, "ask")
    # a tenor with the word: "fx", "pts"; thousands written with a space or a dot
    assert q("{tu} fx 2m 25 500/ 1f a counter")[:6] == ("FX", "2M", "pts", "quote", 25500.0, None)
    assert q("fx 1m 12.750/13.000")[4:6] == (12750.0, 13000.0) and q("2m pts 25500/600")[4:6] == (25500.0, 25600.0)
    assert q("1w fx 2 950/3 000")[4:6] == (2950.0, 3000.0)
    # what is not: a short date with a rate is a money market rate, an OIS stays an OIS
    assert q("on 35.10 bid") is None and q("o/n 35.10/35.40") is None
    assert q("1y ois 35.10/35.15")[:2] == ("OIS", "1Y") and q("6m 35.85/36.00")[0] == "OIS"
    # in a chat: the trade at the bid takes the bid said before it
    rows = bc.parse_chat("SAFA YILMAZ\nt/n 380/385\n12:15:41\nt/n gvn\n12:20:00")
    assert [(r["label"], r["event"], r.get("price")) for r in rows] == [("T/N", "quote", None), ("T/N", "trade", 380.0)]


def test_fx_swap_quotes_show_the_try_rate_they_stand_for(tmp_path):
    s = make_service(tmp_path)
    try:
        u = s.login("FX Swap")["user"]
        day = s.today_iso()
        chat = "SAFA YILMAZ\nt/n 380/385\n12:15:41\nfx 1m 12750/13000\n13:00:00\nt/n gvn\n13:10:00"
        spot = cell(s, "Forward!F2")
        usd_t = cell(s, "Forward!X6")                                                  # SOFR: one day
        d_1m = cell(s, "Forward!G10")
        prev = s.broker_parse(u, chat, day)["rows"]
        tn = prev[0]["implied"]
        assert tn["days"] == cell(s, "Forward!G7") == 1.0 and tn["spot"] == spot
        assert tn["bid"] == pytest.approx(((1 + 380 / 1e4 / spot) * (1 + usd_t / 100 / 360) - 1) * 360 * 100)
        assert tn["ask"] == pytest.approx(((1 + 385 / 1e4 / spot) * (1 + usd_t / 100 / 360) - 1) * 360 * 100)
        one = prev[1]["implied"]
        # the bid side with the USD ask, the ask side with the USD bid (the Forward sheet's own way), USD at the tenor's days
        assert one["days"] == d_1m and one["bid"] < one["ask"] and 20 < one["bid"] < 50
        assert prev[2]["implied"]["price"] == pytest.approx(tn["bid"])                 # given: at the bid
        s.broker_add(u, chat, day, "", None)
        board = {r["label"]: r for r in s.broker(u, day)["board"]}
        assert board["T/N"]["implied"]["last"] == pytest.approx(tn["bid"]) and board["1M"]["implied"]["ask"] == pytest.approx(one["ask"])
        assert board["T/N"]["unit"] == "pts" and board["T/N"].get("mid") is None
    finally:
        s.stop()
