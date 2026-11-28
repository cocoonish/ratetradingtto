"""Kotasyon defteri (C2, 28.11.2026; the desk: "Fiyatladiktan sonra bunu done diye gunluk islemlere alabilmeliyim veya done
olmadiysa da hit ratiosunu takip edebilmeliyim"): ``tto/quotelog.py`` on its own - a quote as the browser sends it, a
status change, the period asked for, the hit ratio by client and by product (open quotes count in neither side), a
table's "Kotasyon kopyala" read into a record (one row's levels, a whole table's none) -, the store's table and its
recovery rule, every ``Service.client_quote`` logged with the levels the table shows, and the HTTP routes."""
from __future__ import annotations

import datetime as dt

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell, make_service
from tto import quotelog as ql
from tto import recover
from tto.server import create_app
from tto.store import Store
from tto.service import ServiceError
from tto.xl.values import date_to_serial, serial_to_date


# ================================================================================================== the module
def test_a_quote_as_the_browser_sends_it():
    rec, status = ql.clean_new({"product": "FX forward", "instrument": "USDTRY forward 3M", "pair": "USDTRY", "side": "AL",
                                "levels": {"bid": 53.9018, "ask": 53.9024}, "source": "Fiyatlama", "size": "10m",
                                "client": "  Garanti   BBVA ", "page": "fiyatlama", "value_date": date_to_serial(dt.date(2027, 2, 4))})
    assert status == "open" and rec["client"] == "Garanti BBVA" and rec["size"] == 10e6 and rec["value_date"] == "2027-02-04"
    assert rec["levels"]["mid"] == pytest.approx(53.9021) and rec["levels"]["bid"] == 53.9018
    # a quote dealt on the spot; a value date typed; a level of one side only (no mid made up)
    rec, status = ql.clean_new({"product": "TRY OIS", "instrument": "2Y", "levels": {"bid": "35,10"}, "status": "done",
                                "value_date": "04.02.2027", "trade_id": 7})
    assert status == "done" and rec["source"] == "elle" and rec["value_date"] == "2027-02-04" and rec["trade_id"] == 7
    assert rec["levels"]["bid"] == pytest.approx(35.10) and rec["levels"]["mid"] is None
    for bad in ({"instrument": "x"}, {"product": "x"}, {"product": "x", "instrument": "y", "status": "belki"},
                {"product": "x", "instrument": "y", "trade_id": "abc"}, [1]):
        with pytest.raises(ql.QuoteLogError):
            ql.clean_new(bad)


def test_a_status_change_and_the_period_asked_for():
    assert ql.clean_update({"status": "done", "trade_id": "12"}) == ("done", {"trade_id": 12})
    assert ql.clean_update({"client": "Akbank"}) == (None, {"client": "Akbank"})
    assert ql.clean_update({"trade_id": None}) == (None, {"trade_id": None})            # (the link taken out)
    for bad in ({}, {"status": "x"}, {"trade_id": 0}, None):
        with pytest.raises(ql.QuoteLogError):
            ql.clean_update(bad)
    today = "2026-11-28"
    assert ql.period(None, None, today) == (today, today)
    assert ql.period("01.11.2026", None, today) == ("2026-11-01", today)
    assert ql.period(None, "2026-11-20", today) == ("2026-11-20", "2026-11-20")
    assert ql.period("2026-11-20", "2026-11-10", today) == ("2026-11-10", "2026-11-20")
    with pytest.raises(ql.QuoteLogError):
        ql.period("2024-01-01", "2026-11-28", today)
    with pytest.raises(ql.QuoteLogError):
        ql.period("yarın", None, today)


def test_the_hit_ratio_by_client_and_by_product():
    q = [{"client": "A", "product": "FX forward", "status": "done", "trade_id": 3},
         {"client": "A", "product": "FX forward", "status": "not_done"},
         {"client": "A", "product": "TRY OIS", "status": "open"},
         {"client": "B", "product": "FX forward", "status": "done"},
         {"product": "FX forward", "status": "not_done"}]
    got = ql.hit(q)
    a = next(g for g in got["by_client"] if g["key"] == "A")
    assert (a["quotes"], a["done"], a["not_done"], a["open"], a["ratio"]) == (3, 1, 1, 1, 0.5)
    assert next(g for g in got["by_client"] if g["key"] == ql.NO_CLIENT)["ratio"] == 0.0
    fx = next(g for g in got["by_product"] if g["key"] == "FX forward")
    assert (fx["quotes"], fx["ratio"], fx["unbooked"]) == (4, 0.5, 1)                    # (B's done has no trade yet)
    assert next(g for g in got["by_product"] if g["key"] == "TRY OIS")["ratio"] is None  # (nothing decided)
    assert got["all"]["quotes"] == 5 and got["all"]["ratio"] == pytest.approx(2 / 4.0)
    assert [g["key"] for g in got["by_client"]][0] == "A"                                # (the most quoted first)


def test_a_table_s_quote_read_into_a_record():
    cells = {"S!B5": (46360.0, "dd.mm.yyyy"), "S!J5": (51.2633, "0.0000"), "S!K5": (51.2639, "0.0000"), "S!A5": ("1M", "General"),
             "S!H5": (12663.4, "#,##0"), "S!I5": (12663.6, "#,##0"), "S!G2": (46330.0, "dd.mm.yyyy")}
    read = lambda ref: cells.get(ref, (None, "General"))                                 # noqa: E731
    spec = {"pair": "USDTRY", "title": "forward", "rows": "5:14", "label": "A", "start": "G2", "end": "B", "points": ["H", "I"],
            "outright": ["J", "K"]}
    where = {"page": "masa", "panel": "EKS", "panel_title": "FORWARD KOTASYON"}
    one = ql.from_table(spec, read, "S", 5, None, "USDTRY forward 1M · 28.11.2026 · bid / ask\nVade tarihi  04.12.2026", where)
    assert one["product"] == "FX forward" and one["pair"] == "USDTRY" and one["instrument"] == "USDTRY forward 1M"
    assert one["levels"]["bid"] == 51.2633 and one["levels"]["ask"] == 51.2639 and one["levels"]["kind"] == "outright"
    assert one["levels"]["text"] == "51,2633 / 51,2639" and one["value_date"] == "2026-12-04" and one["page"] == "masa"
    whole = ql.from_table(spec, read, "S", None, None, "USDTRY forward · 28.11.2026\n\nVade  Puan\n1M  12.663", where)
    assert whole["levels"]["bid"] is None and whole["lines"] == 2 and whole["instrument"] == "USDTRY forward"
    # quotes side by side: one part's levels (one value: a mid); a table with its own product named
    parts = {"title": "forward", "parts": [{"pair": "USDTRY", "outright": "J5"}, {"pair": "EURTRY", "outright": "K5"}]}
    p1 = ql.from_table(parts, read, "S", None, 1, "EURTRY forward · 28.11.2026", where)
    assert p1["pair"] == "EURTRY" and p1["levels"]["mid"] == 51.2639 and p1["levels"]["bid"] is None
    assert ql.from_table(dict(spec, product="TRY OIS"), read, "S", 5, None, "x", where)["product"] == "TRY OIS"
    assert ql.from_table({"pair": "VİOP USDTRY", "points": "H5"}, read, "S", None, None, "VİOP", where)["product"] == "VİOP"


# ================================================================================================== the store
def test_the_store_keeps_a_quote_and_its_status(tmp_path):
    s = Store(str(tmp_path / "q.db"))
    try:
        qid = s.add_quote_log("2026-11-28", {"product": "FX forward", "instrument": "x", "levels": {"bid": 1.0}}, "open", "ali")
        s.add_quote_log("2026-11-27", {"product": "TRY OIS", "instrument": "y", "levels": {}}, "done", "veli")
        assert [q["id"] for q in s.quote_log("2026-11-28", "2026-11-28")] == [qid]
        assert [q["instrument"] for q in s.quote_log("2026-11-01", "2026-11-30")] == ["y", "x"]
        got = s.set_quote_log(qid, "done", {"trade_id": 5, "client": "Garanti"}, "veli")
        assert got["status"] == "done" and got["trade_id"] == 5 and got["client"] == "Garanti" and got["updated_by"] == "veli"
        assert got["created_by"] == "ali" and got["levels"] == {"bid": 1.0}
        got = s.set_quote_log(qid, None, {"trade_id": None}, "ali")
        assert got["status"] == "done" and "trade_id" not in got
        assert s.set_quote_log(999, "done", {}, "ali") is None and s.quote_log_item(999) is None
    finally:
        s.close()
    rule = next(r for r in recover.RULES if r.table == "quote_log")
    assert rule.birth == ("created_at", "created_by") and rule.newer == "updated_at" and rule.json == ("payload",)


# ================================================================================================== the service
def test_every_client_quote_is_logged_with_the_levels_the_table_shows(service):
    """A row's "Kotasyon kopyala" on Masa's forward summary: an open quote of the day with that row's outright bid / ask,
    its value date and pair; the whole table one record without levels; a status changed, the hit ratio."""
    u = service.login("Kotasyon Defteri")["user"]
    before = len(service.quote_log(u)["quotes"])
    res = service.client_quote(u, "masa", "EKS", row=5, language="tr")
    assert res["log_id"] > 0
    got = service.quote_log(u)
    q = next(x for x in got["quotes"] if x["id"] == res["log_id"])
    assert len(got["quotes"]) == before + 1 and q["status"] == "open" and q["created_by"] == u
    assert q["product"] == "FX forward" and q["pair"] == "USDTRY" and q["instrument"] == "USDTRY forward 1M"
    assert q["source"] == "Kotasyon kopyala" and q["page"] == "masa" and q["panel"] == "EKS" and q["text"] == res["text"]
    assert q["levels"]["bid"] == cell(service, "EK_FWD!J5", u) and q["levels"]["ask"] == cell(service, "EK_FWD!K5", u)
    assert q["value_date"] == serial_to_date(cell(service, "EK_FWD!B5", u)).isoformat()
    whole = service.client_quote(u, "masa", "EKS", language="tr")
    w = next(x for x in service.quote_log(u)["quotes"] if x["id"] == whole["log_id"])
    assert w["levels"]["bid"] is None and w["instrument"] == "USDTRY forward"
    # done / not done: the hit ratio by client and product
    service.quote_log_set(u, res["log_id"], {"status": "done", "client": "Garanti"})
    service.quote_log_set(u, whole["log_id"], {"status": "not_done", "client": "Garanti"})
    hit = service.quote_log(u)["hit"]
    g = next(x for x in hit["by_client"] if x["key"] == "Garanti")
    assert (g["done"], g["not_done"], g["ratio"], g["unbooked"]) == (1, 1, 0.5, 1)
    service.quote_log_set(u, res["log_id"], {"trade_id": 41})
    g = next(x for x in service.quote_log(u)["hit"]["by_client"] if x["key"] == "Garanti")
    assert g["unbooked"] == 0
    with pytest.raises(ServiceError) as e:
        service.quote_log_set(u, 10 ** 9, {"status": "done"})
    assert e.value.status == 404


def test_the_routes(tmp_path):
    svc = make_service(tmp_path)
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Defter HTTP")
        r = c.post("/api/quote-log", json={"product": "FX forward", "instrument": "USDTRY 3M", "pair": "USDTRY", "side": "SAT",
                                           "levels": {"bid": 53.90, "ask": 53.91}, "source": "Broker", "client": "Akbank",
                                           "page": "blotter"}, headers=h)
        assert r.status_code == 200 and r.json()["quote"]["status"] == "open"
        qid = r.json()["id"]
        r = c.post("/api/quote-log/%d" % qid, json={"status": "not_done"}, headers=h)
        assert r.status_code == 200 and r.json()["quote"]["status"] == "not_done" and r.json()["quote"]["updated_by"] == "defter http"
        today = dt.date.today().isoformat()
        got = c.get("/api/quote-log", params={"from": today, "to": today}, headers=h).json()
        assert [q["id"] for q in got["quotes"]] == [qid] and got["hit"]["by_client"][0]["key"] == "Akbank"
        assert got["hit"]["all"]["ratio"] == 0.0 and got["statuses"]["not_done"] == "Done değil"
        assert c.get("/api/quote-log", params={"from": "2020-01-01", "to": "2020-01-02"}, headers=h).json()["quotes"] == []
        assert c.post("/api/quote-log", json={"product": "x"}, headers=h).status_code == 400
        assert c.post("/api/quote-log/%d" % qid, json={"status": "belki"}, headers=h).status_code == 400
        assert c.post("/api/quote-log/999999", json={"status": "done"}, headers=h).status_code == 404
        assert c.get("/api/quote-log", params={"from": "abc"}, headers=h).status_code == 400
        assert c.get("/api/quote-log", headers=ANON).status_code == 401
        assert c.post("/api/quote-log", json={"product": "x", "instrument": "y"}, headers=ANON).status_code == 401
