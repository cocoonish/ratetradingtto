"""Each user's own number of decimals in the tables of the workbook pages (``tto/decimals.py``) - the desk, 25.11.2026:
"İstediğim şeyleri seçip sağ tıklayıp decimal formatını yapabilmeliyim".

Kept with the account; put on each answer of a page, never on the page kept (everybody without inputs of their own
shares one); only the decimals change - a percent stays a percent, the thousands separators, the negatives' look, a
suffix -; dates and text untouched; another user's view unchanged; a temporary copy's own; a format stays at its cell
when the rows move; a restart keeps it.  (The right-click menu itself is the browser test's.)"""
import re

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell, make_service
from tto import decimals as dm
from tto.server import create_app
from tto.service import Service, ServiceError
from tto.xl import numfmt

TR = numfmt.get_locale("tr")


def login(svc, name):
    return svc.login(name)["user"]


def entry(res, pid):
    return next(p for p in res["panels"] if p["id"] == pid)


def at(ent, ref):
    """The cell of a table's entry as the browser gets it ("OIS_MAIN!B9"; its strips of inputs too)."""
    sheet, _, a = ref.partition("!")
    m = re.match(r"([A-Z]+)(\d+)$", a)
    for d in [ent["data"]] + [x["data"] for x in ent.get("lead") or []]:
        if d and d.get("sheet") == sheet and m.group(1) in d["c"] and int(m.group(2)) in d["r"]:
            return d["rows"][d["r"].index(int(m.group(2)))][d["c"].index(m.group(1))]
    raise KeyError(ref)


def page(svc, user, view, pid, **kw):
    """One table of a page as ``user`` gets it (only that table is asked for)."""
    res = svc.view(user, view, panels=[pid], **kw)
    return entry(res, pid), res


def with_n(svc, ref, n, user=None, book="tto", copy_of=None):
    """What a cell shows with ``n`` decimals: its value in its own format, with ``n`` decimals."""
    b = svc.books[book]
    si, rc = b.cell(ref)
    v = cell(svc, ref, user, book) if copy_of is None else copy_of
    return numfmt.render(v, numfmt.with_decimals(svc.renderers[book].format_of(si, rc), n), TR, general_digits=10)[0].strip()


def kept_text(svc, view, pid, ref):
    """The cell as the page everybody shares keeps it (what no user's setting may change)."""
    with svc._render_lock:
        rec = svc._renders[("", view, False, "tr")]
    return at(rec["panels"][pid]["entry"], ref)


# ---------------------------------------------------------------------------------------------- one user, another
def test_each_user_sees_their_own_decimals_and_only_the_decimals_change(service):
    a, b = login(service, "Ondalık Ayşe"), login(service, "Ondalık Mehmet")
    before, _ = page(service, a, "ois", "B3")
    pct, acc, mio = at(before, "OIS_MAIN!B9")["t"], at(before, "OIS_MAIN!C10")["t"], at(before, "OIS_MAIN!E9")["t"]
    assert re.match(r"^\d+,\d\d%$", pct) and re.match(r"^(-?\d+|-)$", acc) and re.match(r"^-?[\d.]+M$", mio), (pct, acc, mio)
    res = service.decimals.change(a, "tto", set_={"OIS_MAIN!B9": 3, "OIS_MAIN!C10": 2, "OIS_MAIN!E9": 1,
                                                  "OIS_MAIN!P10": 2})
    assert res["set"] == 3 and res["skipped"] == 1 and res["reset"] == 0       # (P10 is a date: never re-formatted)
    mine, ans = page(service, a, "ois", "B3")
    # a percent stays a percent, a negative its sign, the millions their "M" - one more / fewer decimal each
    b9, c10, e9 = at(mine, "OIS_MAIN!B9"), at(mine, "OIS_MAIN!C10"), at(mine, "OIS_MAIN!E9")
    assert re.match(r"^\d+,\d{3}%$", b9["t"]) and b9["t"] == with_n(service, "OIS_MAIN!B9", 3) and b9["dp"] == 3
    assert re.match(r"^(-?\d+,\d\d|-)$", c10["t"]) and c10["t"] == with_n(service, "OIS_MAIN!C10", 2) and c10["dp"] == 2
    assert re.match(r"^-?[\d.]+,\dM$", e9["t"]) and e9["t"] == with_n(service, "OIS_MAIN!E9", 1)
    # the values are the values: only the text a cell shows changed
    assert b9["v"] == at(before, "OIS_MAIN!B9")["v"] == cell(service, "OIS_MAIN!B9", a)
    assert {k: v for k, v in b9.items() if k not in ("t", "dp")} == {k: v for k, v in at(before, "OIS_MAIN!B9").items() if k != "t"}
    # a cell next to them, text (YÖN), is as it was
    assert at(mine, "OIS_MAIN!D9") == at(before, "OIS_MAIN!D9")
    # another user - and the page everybody shares, that both answers came from - see the file's format
    theirs, other = page(service, b, "ois", "B3")
    assert at(theirs, "OIS_MAIN!B9")["t"] == pct and "dp" not in at(theirs, "OIS_MAIN!B9")
    assert at(theirs, "OIS_MAIN!C10")["t"] == acc and kept_text(service, "ois", "B3", "OIS_MAIN!B9")["t"] == pct
    assert ans["as"].startswith("s~") and other["as"] == "s"
    # the date asked for: as it was, on the page and in what is kept
    impl, _ = page(service, a, "ois", "B4")
    assert re.match(r"^\d\d\.\d\d\.\d{4}$", at(impl, "OIS_MAIN!P10")["t"]) and "dp" not in at(impl, "OIS_MAIN!P10")
    assert service.decimals.listing(a) == {"cells": {"tto": {"OIS_MAIN!B9": 3, "OIS_MAIN!C10": 2, "OIS_MAIN!E9": 1}},
                                           "copies": {}, "max": numfmt.MAX_DECIMALS}
    assert service.decimals.listing(b) == {"cells": {}, "copies": {}, "max": numfmt.MAX_DECIMALS}
    assert service.store.get("decimals." + a) == {"books": {"tto": {"OIS_MAIN": {"B9": 3, "C10": 2, "E9": 1}}}}
    # set again (0 decimals), then back to the default: the cell's own format again
    service.decimals.change(a, "tto", set_={"OIS_MAIN!B9": 0})
    assert re.match(r"^\d+%$", at(page(service, a, "ois", "B3")[0], "OIS_MAIN!B9")["t"])
    assert service.decimals.change(a, "tto", reset=["OIS_MAIN!B9", "OIS_MAIN!B10"])["reset"] == 1
    back, _ = page(service, a, "ois", "B3")
    assert at(back, "OIS_MAIN!B9")["t"] == pct and "dp" not in at(back, "OIS_MAIN!B9")
    assert at(back, "OIS_MAIN!C10")["t"] == c10["t"]                          # (the others stay)
    service.decimals.change(a, "tto", reset=["OIS_MAIN!C10", "OIS_MAIN!E9"])
    assert service.decimals.listing(a)["cells"] == {} and service.decimals.mark(a) == ""
    assert page(service, a, "ois", "B3")[1]["as"] == "s"


def test_a_browser_holding_the_tables_from_before_a_change_gets_them_whole(service):
    """The answer's ``as`` carries the mark of the user's setting: asked "since" a generation with another mark, the
    tables come whole - not "unchanged" - so that no window keeps showing the decimals from before (the open page, its
    other tabs, a launchpad's boxes, another window)."""
    a = login(service, "Ondalık Zeynep")
    _, first = page(service, a, "ois", "B3")
    assert first["as"] == "s"
    service.decimals.change(a, "tto", set_={"OIS_MAIN!B9": 4})
    res = service.view(a, "ois", panels=["B3"], since=first["gen"], as_=first["as"])
    assert not res.get("unchanged") and at(entry(res, "B3"), "OIS_MAIN!B9")["t"] == with_n(service, "OIS_MAIN!B9", 4)
    again = service.view(a, "ois", panels=["B3"], since=res["gen"], as_=res["as"])
    assert again.get("unchanged") or "B3" not in [p["id"] for p in again["panels"]]
    # a launchpad's box: the same - its own mark, the table whole when it is another
    boxes = service.panels(a, [{"view": "ois", "panel": "B3", "since": first["gen"], "as": first["as"]}])["panels"]["ois/B3"]
    assert boxes["as"] == res["as"] and at(boxes["entry"], "OIS_MAIN!B9")["dp"] == 4
    held = service.panels(a, [{"view": "ois", "panel": "B3", "since": res["gen"], "as": res["as"]}])["panels"]["ois/B3"]
    assert held.get("unchanged") or at(held["entry"], "OIS_MAIN!B9")["dp"] == 4
    service.decimals.change(a, "tto", reset=["OIS_MAIN!B9"])


def test_a_temporary_copy_has_its_own_decimals(service):
    """A setting made in a copy is the copy's (``dpc``), the table's stays; in its other cells the copy shows the table's
    setting; the copy's strip of inputs too; taken back in the copy, the table's shows again; closing the copy drops its
    own."""
    u = login(service, "Ondalık Kopya")
    one = service.copy_action(u, "open", {"view": "masa", "panel": "B10"})["copy"]
    try:
        res = service.view(u, "masa")
        table0 = entry(res, "B10")
        d = table0["data"]
        nums = [d["sheet"] + "!" + c + str(r) for i, r in enumerate(d["r"]) for j, c in enumerate(d["c"])
                if r and re.match(r"^[A-Z]+$", c) and d["rows"][i][j].get("k") == "n"]
        x, y = nums[0], nums[1]
        spread = "MASA!I60"                                       # (the strip above it: the spread, a number)
        assert at(entry(res, one["pid"]), spread).get("k") == "n"
        service.decimals.change(u, "tto", set_={x: 5})                     # on the table: the copy follows it
        service.decimals.change(u, "tto", copy=one["id"], set_={y: 4, spread: 2})       # in the copy: its own
        res = service.view(u, "masa")
        table, cp = entry(res, "B10"), entry(res, one["pid"])
        assert at(table, x)["t"] == with_n(service, x, 5, u) and at(table, x)["dp"] == 5 and "dpc" not in at(table, x)
        assert at(cp, x)["dp"] == 5 and "dpc" not in at(cp, x) and at(cp, x)["t"] == with_n(service, x, 5, copy_of=at(cp, x)["v"])
        assert at(cp, y)["dp"] == 4 and at(cp, y)["dpc"] == 1 and at(cp, y)["t"] == with_n(service, y, 4, copy_of=at(cp, y)["v"])
        assert at(table, y) == at(table0, y) and "dp" not in at(table, y)
        assert at(cp, spread)["dpc"] == 1 and re.match(r"^-?[\d.]+,\d\d$", at(cp, spread)["t"])
        assert "dp" not in at(entry(service.view(u, "masa", panels=["B9"]), "B9"), spread)       # (the page's dates row)
        # the copy's own over the table's, then taken back: the table's again
        service.decimals.change(u, "tto", copy=one["id"], set_={x: 1})
        assert at(entry(service.view(u, "masa"), one["pid"]), x)["dp"] == 1
        assert service.decimals.change(u, "tto", copy=one["id"], reset=[x])["reset"] == 1
        back = entry(service.view(u, "masa"), one["pid"])
        assert at(back, x)["dp"] == 5 and "dpc" not in at(back, x)
        assert service.decimals.listing(u)["copies"] == {one["id"]: {y: 4, spread: 2}}
        # a copy of another user's, or one closed: refused
        with pytest.raises(ServiceError) as err:
            service.decimals.change(login(service, "Ondalık Başkası"), "tto", copy=one["id"], set_={y: 1})
        assert err.value.status == 404
    finally:
        service.copy_action(u, "close", {"copy": one["id"]})
    assert service.decimals.listing(u)["copies"] == {} and service.decimals.listing(u)["cells"] == {"tto": {x: 5}}
    service.decimals.change(u, "tto", reset=[x])


# ---------------------------------------------------------------------------------------------- rows that move; a restart
def test_a_format_stays_at_its_place_when_the_rows_move_and_a_restart_keeps_it(tmp_path):
    """A setting belongs to the cell, not to the row's meeting: an extraordinary meeting put in before 18.03.2027 moves
    that meeting a row down - what was typed for it goes with it (meetings.py) - and the decimals set on its row's
    implied bps (R12) stay on R12, the row the meetings moved into.  A restart reads them back."""
    svc = make_service(tmp_path)
    try:
        a = login(svc, "Ondalık Takvim")
        assert svc.set_inputs(a, "tto", [{"ref": "OIS_MAIN!U12", "value": "-50"}])["errors"] == []
        svc.decimals.change(a, "tto", set_={"OIS_MAIN!R12": 4})
        start = svc.history.meetings()
        res = svc.history.set_calendar(a, ["11.02.2027"] + start[:-1])
        assert res["changed"] == 78
        assert {k[1]: v for k, v in svc.store.user_inputs(a, "tto").items()} == {"OIS_MAIN!U13": -50.0}     # (it moved)
        assert svc.decimals.listing(a)["cells"] == {"tto": {"OIS_MAIN!R12": 4}}                          # (this did not)
        impl, _ = page(svc, a, "ois", "B4")
        assert at(impl, "OIS_MAIN!R12")["t"] == with_n(svc, "OIS_MAIN!R12", 4, a) and at(impl, "OIS_MAIN!R12")["dp"] == 4
        assert "dp" not in at(impl, "OIS_MAIN!R13") and re.match(r"^(-?\d+|-)$", at(impl, "OIS_MAIN!R13")["t"])
        again = Service(svc.settings)
        try:
            assert again.decimals.listing(a)["cells"] == {"tto": {"OIS_MAIN!R12": 4}}
            r12 = at(page(again, a, "ois", "B4")[0], "OIS_MAIN!R12")
            assert r12["dp"] == 4 and r12["t"] == with_n(again, "OIS_MAIN!R12", 4, a)
        finally:
            again.stop()
    finally:
        svc.stop()


# ---------------------------------------------------------------------------------------------- what is refused
@pytest.mark.parametrize("book, set_, reset, status", [
    ("yok", {"OIS_MAIN!B9": 2}, None, 404),
    (None, {"OIS_MAIN!B9": 2}, None, 404),
    ("tto", {"OIS_MAIN!B9": -1}, None, 400),
    ("tto", {"OIS_MAIN!B9": 11}, None, 400),
    ("tto", {"OIS_MAIN!B9": 2.0}, None, 400),
    ("tto", {"OIS_MAIN!B9": True}, None, 400),
    ("tto", {"OIS_MAIN!B9": "2"}, None, 400),
    ("tto", {"OIS_MAIN!B9:C9": 2}, None, 400),
    ("tto", {"Yok!B9": 2}, None, 400),
    ("tto", {"B9": 2}, None, 400),
    ("tto", {"OIS_MAIN!b9": 2}, None, 400),
    ("tto", ["OIS_MAIN!B9"], None, 400),
    ("tto", None, "OIS_MAIN!B9", 400),
    ("tto", None, ["OIS_MAIN!B0"], 400),
    ("tto", {"OIS_MAIN!A%d" % i: 2 for i in range(1, 5002)}, None, 400),
])
def test_what_is_not_a_setting_is_refused(service, book, set_, reset, status):
    u = login(service, "Ondalık Hatalı")
    with pytest.raises(ServiceError) as err:
        service.decimals.change(u, book, set_=set_, reset=reset)
    assert err.value.status == status
    assert service.decimals.listing(u)["cells"] == {}


def test_a_user_must_be_signed_in_and_may_set_so_many_cells(service, monkeypatch):
    for call in (lambda: service.decimals.listing(None), lambda: service.decimals.change(None, "tto", {"OIS_MAIN!B9": 2}),
                 lambda: service.decimals.change("hiç olmayan kişi", "tto", {"OIS_MAIN!B9": 2})):
        with pytest.raises(ServiceError) as err:
            call()
        assert err.value.status == 401
    with pytest.raises(ServiceError) as err:
        service.decimals.change(login(service, "Ondalık Kopyasız"), "tto", copy="k00000000", set_={"OIS_MAIN!B9": 2})
    assert err.value.status == 404
    monkeypatch.setattr(dm, "MAX_CELLS", 3)
    u = login(service, "Ondalık Çok")
    service.decimals.change(u, "tto", set_={"OIS_MAIN!B9": 2, "OIS_MAIN!B10": 2, "OIS_MAIN!B11": 2})
    with pytest.raises(ServiceError) as err:
        service.decimals.change(u, "tto", set_={"OIS_MAIN!B12": 2})
    assert "en fazla 3" in str(err.value)
    service.decimals.change(u, "tto", set_={"OIS_MAIN!B9": 4})                       # (a cell already set may change)
    assert service.decimals.listing(u)["cells"]["tto"] == {"OIS_MAIN!B9": 4, "OIS_MAIN!B10": 2, "OIS_MAIN!B11": 2}
    service.decimals.change(u, "tto", reset=["OIS_MAIN!B9", "OIS_MAIN!B10", "OIS_MAIN!B11"])


# ---------------------------------------------------------------------------------------------- over HTTP
def test_over_http(service):
    client = TestClient(create_app(service=service))                         # (no "with": the shared service stays up)
    h, other = auth(service, "Ondalık Http"), auth(service, "Ondalık Http Komşu")
    assert client.get("/api/decimals", headers=h).json() == {"cells": {}, "copies": {}, "max": numfmt.MAX_DECIMALS}
    first = client.get("/api/view/ois?panels=B3", headers=h).json()
    r = client.post("/api/decimals", json={"book": "tto", "set": {"OIS_MAIN!G9": 3, "OIS_MAIN!H9": 1}}, headers=h)
    assert r.status_code == 200 and r.json()["set"] == 2 and r.json()["mark"].startswith("~")
    assert client.get("/api/decimals", headers=h).json()["cells"] == {"tto": {"OIS_MAIN!G9": 3, "OIS_MAIN!H9": 1}}
    # the page (asked "since" with the mark from before: whole), a launchpad's box, the neighbour's page
    mine = client.get("/api/view/ois", params={"panels": "B3", "since": first["gen"], "as": first["as"]}, headers=h).json()
    g9 = at(entry(mine, "B3"), "OIS_MAIN!G9")
    assert re.match(r"^\d+,\d{3}%$", g9["t"]) and g9["dp"] == 3 and mine["as"] == "s" + r.json()["mark"]
    box = client.post("/api/panels", json={"items": [{"view": "ois", "panel": "B3", "since": first["gen"], "as": first["as"]}]},
                      headers=h).json()["panels"]["ois/B3"]
    assert at(box["entry"], "OIS_MAIN!H9")["t"] == with_n(service, "OIS_MAIN!H9", 1) and box["as"] == mine["as"]
    theirs = client.get("/api/view/ois?panels=B3", headers=other).json()
    assert re.match(r"^\d+,\d\d%$", at(entry(theirs, "B3"), "OIS_MAIN!G9")["t"]) and theirs["as"] == "s"
    assert client.post("/api/decimals", json={"book": "tto", "set": {"OIS_MAIN!G9": "3"}}, headers=h).status_code == 400
    assert client.post("/api/decimals", json={"book": "yok", "set": {}}, headers=h).status_code == 404
    # without a session: nothing, and nothing is changed; a change sent from another site's page is refused
    assert client.get("/api/decimals", headers=ANON).status_code == 401
    assert client.post("/api/decimals", json={"book": "tto", "reset": ["OIS_MAIN!G9"]}, headers=ANON).status_code == 401
    foreign = dict(h, Origin="http://kotu-site.example")
    assert client.post("/api/decimals", json={"book": "tto", "reset": ["OIS_MAIN!G9"]}, headers=foreign).status_code == 403
    r = client.post("/api/decimals", json={"book": "tto", "reset": ["OIS_MAIN!G9", "OIS_MAIN!H9"]}, headers=h)
    assert r.json() == {"set": 0, "reset": 2, "skipped": 0, "mark": ""}
    assert client.get("/api/view/ois?panels=B3", headers=h).json()["as"] == "s"
