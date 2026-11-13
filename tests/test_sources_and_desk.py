"""The order of Bloomberg pricing sources (live sheets and the history), ASW against FX swaps, the value-date rate
table of the Forward page, the gold calculator's free column, z-scores of the carry table, and the broker chat's
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
def test_the_value_date_rates_price_like_the_forward_sheet(svc):
    u = svc.login("Vade Faiz")["user"]
    for k in range(4):
        assert [cell(svc, "EK_FWD!%s%d" % (c, 37 + k)) for c in "DEF"] == [cell(svc, "Forward!%s%d" % (c, 30 + k)) for c in "DEF"]
        assert [cell(svc, "EK_FWD!%s%d" % (c, 37 + k)) for c in "LM"] == [cell(svc, "Forward!%s%d" % (c, 42 + k)) for c in "DF"]
        assert cell(svc, "EK_FWD!G%d" % (37 + k)) == pytest.approx(cell(svc, "Forward!D%d" % (36 + k)))
    assert cell(svc, "EK_FWD!B41") == cell(svc, "EK_FWD!B40")                   # "Elle" starts from RET
    res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B38", "value": "40"}, {"ref": "EK_FWD!C38", "value": "41"}])
    assert res["errors"] == []
    spot, days, usd_ask = cell(svc, "EK_FWD!B35", u), cell(svc, "EK_FWD!D34", u), cell(svc, "EK_FWD!F35", u)
    assert cell(svc, "EK_FWD!D38", u) == pytest.approx(spot * (1 + 0.40 / 360 * days) / (1 + usd_ask / 100 / 360 * days))
    assert cell(svc, "EK_FWD!D38") == cell(svc, "Forward!D31")                    # nobody else's
    svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B38", "value": ""}])
    assert cell(svc, "EK_FWD!D38", u) == cell(svc, "Forward!D31")                 # blanked: back to the curve
    panel = next(p for p in svc.view(u, "forward")["panels"] if p["id"] == "FR1")
    assert not panel.get("error") and panel["title"].startswith("VADE FAİZLERİYLE FORWARD")


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
        with TestClient(create_app(s)) as client:
            hdr = {"X-TTO-User": u}
            res = client.post("/api/broker/reset", json={"date": day}, headers=hdr)
            assert res.status_code == 200 and [r["label"] for r in res.json()["board"]] == ["2Y"]       # said later in the day
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
