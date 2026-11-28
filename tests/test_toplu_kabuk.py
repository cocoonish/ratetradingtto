"""The shell's part of the desk's batch of 28.11.2026 (docs/desk-decisions.md, *Toplu iş 28.11.2026 · kabuk*): the menu's
reorganization (R: tto/navmenu.py - Masa 5 entries, TRY Faiz 7, Tahvil 3, FX · USD 2, Quant 3, Araçlar last), every
entry's hint and the desk's default favourites (B8), the ``rows`` view option and VİOP's Kontratlar (B15), what a user
typed - the values typed over formulas (the personal badge, A6) and the market levels typed on an earlier day (A7).
The pure parts of the browser's modules (menu.js, hesap.js, mine.js) are read under Node; what the pages do on screen -
the tools in the tab bar (B3), the notes at the visible width (B2), the menu below 1500 px (B10), the title never cut
(B9) - is the browser test's (tests/e2e/e2e.js, the "kabuk" checks)."""
import datetime as _dt
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import cell, make_service
from tto import layout as lay
from tto import myinputs as mi
from tto import navmenu
from tto.service import ServiceError, _pick_part, _pick_rows
from tto.views import check_view, load_views
from tto.xl.model import COLS, parse_range
from tto.xl.values import serial_to_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "tto", "static", "js")


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """A service of this module's own: the desk's default favourites are desk-wide."""
    s = make_service(tmp_path_factory.mktemp("kabuk"))
    yield s
    s.stop()


def entries(nav):
    """The menu as the nav gives it: [(group, [(entry id, title, [page ids])])]."""
    out = []
    for p in nav:
        if not out or out[-1][0] != p["group"]:
            out.append((p["group"], []))
        key = p.get("menu") or p["id"]
        es = out[-1][1]
        if not es or es[-1][0] != key:
            es.append((key, p.get("menu_title") or p["title"], []))
        es[-1][2].append(p["id"])
    return out


# ---------------------------------------------------------------------------------------------- R: the menu
def test_the_menu_is_the_desks_reorganization(svc):
    """Masa · TRY Faiz · Tahvil · FX · USD · Quant · Araçlar, each entry with its tabs as the desk approved them (R); the
    pages keep their ids and titles - an address opens the entry on its tab."""
    admin = svc.login("Kabuk Yönetici")["user"]
    svc.store.update_account(admin, role="admin")
    nav = svc.nav(admin)
    got = [(g, [(k, t, ids) for k, t, ids in es]) for g, es in entries(nav)]
    assert [g for g, _ in got] == ["Masa", "TRY Faiz", "Tahvil", "FX · USD", "Quant", "Araçlar"]
    by = dict(got)
    assert by["Masa"] == [("bugun", "Bugün", ["bugun"]), ("masa", "Masa", ["masa"]),
                          ("masa.islemler", "İşlemler", ["blotter", "trades", "broker"]),
                          ("masa.piyasa", "Piyasa hareketi", ["heat", "eod", "watch"]),
                          ("masa.iletisim", "Masa iletişim", ["social", "agenda"])]
    assert by["TRY Faiz"] == [("faiz.ois", "OIS · PPK", ["ois", "mpc"]), ("faiz.fiyatlama", "Fiyatlama", ["fiyatlama", "swaption", "tmois"]),
                              ("forward", "Forward", ["forward"]), ("viop", "VİOP", ["viop"]), ("borsa", "Borsa Swap", ["borsa"]),
                              ("faiz.carry", "Carry & Roll", ["carry", "vol", "spreads"]), ("dv01", "DV01 Risk", ["dv01"])]
    assert by["Tahvil"] == [("tahvil.piyasa", "DİBS Piyasa", ["dibslive", "kagitlar", "bulk"]),
                            ("tahvil.fiyatlama", "DİBS Fiyatlama", ["kagit-fiyat", "manuel", "fiyat-yukleme", "ihale"]),
                            ("tahvil.dibsrv", "DİBS RV", ["dibs-genel", "dibs", "asw"])]
    assert by["FX · USD"] == [("fx.spot", "Spot / FX", ["fx", "fxvol"]), ("usd", "USD · FOMC", ["usd"])]
    assert [(k, t) for k, t, _ in by["Quant"]] == [("quant.sinyal", "Sinyaller"), ("quant.faiz", "Faiz analizleri"), ("quant.fx", "FX analizleri")]
    assert by["Quant"][0][2][-1] == "quant-viop"                     # (Quant · VİOP: Sinyaller's last tab)
    assert by["Araçlar"] == [("calc", "Hesaplayıcılar", ["calc"]), ("motor", "Motor", ["motor"]),
                             ("settings", "Ayarlar · Toplantı takvimi", ["settings"])]
    # 23 entries (Motor an administrator's) instead of 40: every page in one of them, with its tab titles
    assert sum(len(es) for _, es in got) == 23
    pages = {p["id"]: p for p in nav}
    assert [pages[x]["tab"] for x in ("blotter", "trades", "broker", "heat", "eod", "watch")] == [
        "Günlük İşlemler", "Trades", "Broker Chat", "Eğri Hareketi (gün içi)", "Gün Sonu Matrisi", "İzleme · Alarmlar"]
    assert [pages[x]["tab"] for x in ("mpc", "tmois", "vol", "spreads", "dibslive", "kagitlar", "bulk", "manuel", "ihale")] == [
        "PPK geçmişi", "Nakit akışı", "Realized vol", "Spread geçmişi", "Trading", "Evren", "Eurobond", "Tek kâğıt", "İhale"]
    # the pages keep their titles (the top bar, Ctrl+K) - the only two that had one title between them told apart
    assert (pages["blotter"]["title"], pages["mpc"]["title"], pages["manuel"]["title"]) == ("Günlük İşlemler", "PPK Fiyatlama Geçmişi", "Manuel Tahvil")
    assert pages["quant-viop"]["title"] == "Quant · VİOP" and pages["viop"]["title"] == "VİOP"
    titles = [p["title"] for p in nav]
    assert len(titles) == len(set(titles)), [t for t in titles if titles.count(t) > 1]
    # every view is still a page of the nav, once
    ids = [p["id"] for p in nav]
    assert len(ids) == len(set(ids)) and {v["id"] for v in load_views()} <= set(ids)


def test_every_entry_says_what_it_is_in_one_line(svc):
    """B8: each page its hint (a tab's own), each entry of tabs its own hint - one line, named after the entry."""
    nav = svc.nav(svc.login("Kabuk İpucu")["user"])
    for p in nav:
        assert p.get("hint") and "\n" not in p["hint"], p["id"]
        if p.get("menu"):
            assert p.get("menu_hint") and p["menu_hint"].startswith(p["menu_title"]), p["id"]
    hints = {p["id"]: p["hint"] for p in nav}
    assert hints["blotter"].startswith("Günlük İşlemler — masanın blotter'ı")
    assert "pozisyona girmez" in hints["trades"]
    assert next(p for p in nav if p["id"] == "blotter")["menu_hint"].startswith("İşlemler — Günlük İşlemler (masanın blotter'ı), Trades")


def test_the_arrangement_keeps_every_page_and_places_the_unknown(svc):
    """navmenu.arrange: no page lost or twice; an entry with one of its pages there is that page alone; an old group's
    name its group of today; a group the menu does not know before Araçlar; Motor only for administrators."""
    pages = svc._nav_pages(None)
    out = navmenu.arrange(pages)
    assert sorted(p["id"] for p in out) == sorted(p["id"] for p in pages)
    # a page of a group of before (another version) and one of a group the menu does not know
    extra = [{"id": "risk2", "title": "Risk 2", "group": "Risk"}, {"id": "yeni", "title": "Yeni", "group": "Yeni grup"}]
    out = navmenu.arrange(pages + extra)
    groups = []
    for p in out:
        if not groups or groups[-1] != p["group"]:
            groups.append(p["group"])
    assert groups == ["Masa", "TRY Faiz", "Tahvil", "FX · USD", "Quant", "Yeni grup", "Araçlar"]
    faiz = [p["id"] for p in out if p["group"] == "TRY Faiz"]
    assert faiz[-2:] == ["dv01", "risk2"]                            # (at its group's end)
    # an entry with one page there: that page alone, no tab strip
    alone = navmenu.arrange([p for p in pages if p["id"] != "mpc"])
    ois = next(p for p in alone if p["id"] == "ois")
    assert "menu" not in ois and ois["hint"].startswith("OIS · PPK")
    # an administrator's page for administrators only
    user = svc.login("Kabuk Kullanıcı")["user"]
    assert "motor" not in {p["id"] for p in svc.nav(user)} and "motor" in {p["id"] for p in svc.nav(None)}
    assert navmenu.page_entry("broker") == "masa.islemler" and navmenu.page_entry("forward") is None
    assert len(navmenu.entry_ids()) == len(set(navmenu.entry_ids()))


def test_the_menu_and_its_addresses_over_http(svc):
    from starlette.testclient import TestClient
    from conftest import auth
    from tto.server import create_app
    client = TestClient(create_app(service=svc))
    h = auth(svc, "Kabuk HTTP")
    nav = client.get("/api/nav", headers=h).json()["pages"]
    assert [p["id"] for p in nav if p.get("menu") == "masa.islemler"] == ["blotter", "trades", "broker"]
    for path in ("/static/js/menu.js", "/static/js/mine.js", "/static/js/hesap.js", "/static/index.html"):
        assert client.get(path).status_code == 200, path
    assert 'id="mine-badge"' in client.get("/static/index.html").text


# ---------------------------------------------------------------------------------------------- B8: the desk's favourites
def test_the_desks_default_favourites(svc):
    """An administrator sets the desk's favourites; a user who never chose favourites of their own gets them; a star
    added or taken out makes the list their own (the desk's no longer comes); a user who had favourites keeps them."""
    admin = svc.login("Kabuk Fav Yönetici")["user"]
    svc.store.update_account(admin, role="admin")
    new, old, other = (svc.login(n)["user"] for n in ("Kabuk Fav Yeni", "Kabuk Fav Eski", "Kabuk Fav Diğer"))
    svc.set_layout(old, {"favs": ["forward"]})
    assert "desk_favs" not in svc.layout(new) and svc.layout(new)["favs"] == []          # (no defaults yet: as before)
    with pytest.raises(ServiceError) as err:
        svc.set_layout(new, {"desk_favs": ["ois"]})
    assert err.value.status == 403
    with pytest.raises(ServiceError) as err:
        svc.set_layout(admin, {"desk_favs": ["bir sayfa değil"]})
    assert err.value.status == 400
    got = svc.set_layout(admin, {"desk_favs": ["ois", "forward", "ois", "blotter"]})
    assert got["desk_favs"] == ["ois", "forward", "blotter"]
    mine = svc.layout(new)
    assert mine["favs"] == ["ois", "forward", "blotter"] and mine["favs_desk"] is True
    assert svc.layout(old)["favs"] == ["forward"] and "favs_desk" not in svc.layout(old)       # (their own stand)
    # another part changed: still the desk's; a star: their own from then on
    assert svc.set_layout(new, {"compact": True})["favs_desk"] is True
    own = svc.set_layout(new, {"favs": ["ois", "forward", "blotter", "dv01"]})
    assert own["favs"] == ["ois", "forward", "blotter", "dv01"] and "favs_desk" not in own
    svc.set_layout(admin, {"desk_favs": ["masa"]})
    assert svc.layout(new)["favs"] == ["ois", "forward", "blotter", "dv01"] and svc.layout(other)["favs"] == ["masa"]
    # emptied by the user: their own empty list
    assert svc.set_layout(other, {"favs": []})["favs"] == []
    assert svc.store.get(lay.DESK_KEY)["favs"] == ["masa"] and svc.store.get(lay.DESK_KEY)["by"] == admin
    svc.set_layout(admin, {"desk_favs": []})
    assert "desk_favs" not in svc.layout(new)


# ---------------------------------------------------------------------------------------------- B15: "rows"
def _table(rows, cols="ABC", first=1):
    return {"sheet": "X", "r": list(range(first, first + len(rows))), "c": list(cols),
            "rows": [[dict(c) for c in row] for row in rows]}


def test_rows_picks_the_rows_by_number_in_their_order():
    t = _table([[{"t": "h"}, {"t": "a"}, {"t": "b"}], [{"t": "1"}, {"t": "x"}, {"t": "y"}], [{"t": "2"}, {"t": "z"}, {"t": "w"}],
                [{"t": "3"}, {"t": "q"}, {"t": "r"}]], first=7)
    _pick_rows(t, [7, 10, 99, 9, 10])
    assert t["r"] == [7, 10, 9] and [row[0]["t"] for row in t["rows"]] == ["h", "3", "2"] and t["ar"] == [7, 8, 9, 10]
    same = _table([[{"t": "a"}], [{"t": "b"}]], cols="A")
    _pick_rows(same, [1, 2])
    assert "ar" not in same and same["r"] == [1, 2]                  # (all of them in their order: nothing to do)


def test_rows_keeps_what_follows_of_a_cell_merged_down():
    rows = [[{"t": "ad", "rs": 3}, {"t": "1"}], [{"sk": 1}, {"t": "2"}], [{"sk": 1}, {"t": "3"}], [{"t": "x"}, {"t": "4"}]]
    a = _table(rows, cols="AB")
    _pick_rows(a, [1, 2, 4])                                          # (the merge's first two rows still follow it)
    assert a["rows"][0][0] == {"t": "ad", "rs": 2} and a["rows"][1][0] == {"sk": 1} and a["rows"][2][0] == {"t": "x"}
    b = _table(rows, cols="AB")
    _pick_rows(b, [2, 3, 4])                                          # (its first row gone: its cells their own, empty)
    assert all(not row[0].get("sk") for row in b["rows"]) and b["r"] == [2, 3, 4]
    c = _table(rows, cols="AB")
    _pick_rows(c, [1, 3])                                             # (a row of it left out between: one row)
    assert c["rows"][0][0] == {"t": "ad"} and c["rows"][1][0] == {}


def test_check_view_says_what_is_wrong_with_rows():
    v = {"id": "x", "panels": [{"id": "A", "type": "table", "range": "K19:X29", "rows": [19, 25, "26", 30, 25, True]},
                               {"id": "B", "type": "chart", "rows": [1]}, {"id": "C", "type": "table", "range": "A1:B2", "rows": []},
                               {"id": "D", "type": "table", "range": "A1:B9", "rows": [1, 9]}],
         "sections": [], "pinned": []}
    said = "\n".join(check_view(v))
    for want in ("x/A: rows bir satır numarası olur: '26'", "x/A: rows 30 tablonun aralığında değil", "x/A: rows 25 iki kez",
                 "x/A: rows bir satır numarası olur: True", "x/B: rows yalnız tabloda", "x/C: rows satır numaralarının listesi olur"):
        assert want in said, (want, said)
    assert "x/D" not in said


def test_viop_kontratlar_show_the_rows_they_share_once(svc):
    """B15: VIOP BID shows 1st / 2nd Date, VKGS, Spot and USD; VIOP ASK, OIS and ICAP only their own rows under the
    contracts' dates - every cell at its row; the gold tables without the name column (the title says it)."""
    v = svc.view(None, "viop")
    p = {x["id"]: x for x in v["panels"]}
    label = lambda d: [row[0].get("t", "") for row in d["rows"]]                                     # noqa: E731
    assert label(p["B5"]["data"])[1:6] == ["1st Date", "2nd Dat", "VKGS", "Spot", "USD"]
    assert p["B7"]["data"]["r"] == [19, 25, 26, 27, 28, 29] and label(p["B7"]["data"])[1:] == ["TRY", "SP", "Günlük SP", "VIOP Price", "ON karşılık"]
    assert p["B12"]["data"]["r"] == [71, 77, 78, 79, 80, 81, 82] and label(p["B12"]["data"])[-1] == "OIS vs VIOP"
    assert p["B13"]["data"]["r"] == [84, 90, 91, 92, 93, 94, 95] and label(p["B13"]["data"])[-1] == "ICAP vs VIOP"
    for pid, first in (("B7", 19), ("B12", 71), ("B13", 84)):
        d = p[pid]["data"]
        assert d["ar"] == list(range(first, first + len(d["ar"]))) and len(d["ar"]) in (11, 12)
        # the dates row: the contracts' expiries, the same columns as VIOP BID's
        assert [c.get("t") for c in d["rows"][0][1:]] == [c.get("t") for c in p["B5"]["data"]["rows"][0][1:]]
    # what the four tables leave out is the same in each (one formula a row: the spot date, the expiry, the days, the
    # spot, the USD rate) - shown once, in VIOP BID; the OIS copy's spot date is the same day written as text ("OIS kopyası
    # başka tarih biçiminde")
    def day(v):
        if isinstance(v, str) and re.match(r"^\d{1,2}\.\d{1,2}\.\d{4}$", v):
            d, m, y = (int(x) for x in v.split("."))
            return _dt.date(y, m, d)
        return serial_to_date(v) if off in (1, 2) else v
    for off in range(1, 6):
        rows = [day(cell(svc, "VIOP!M%d" % (r0 + off))) for r0 in (7, 19, 71, 84)]
        assert len(set(rows)) == 1, (off, rows)
    for pid, letters in (("B9", "LMNO"), ("B10", "RSTU"), ("B11", "LMNO")):
        assert p[pid]["data"]["c"] == list(letters), pid
    # a launchpad's part of such a table keeps the whole range's rows (a block pasted lands on the rows on screen)
    part = _pick_part(p["B12"]["data"], [77, 78], [])
    assert part["r"] == [71, 77, 78] and part["ar"] == p["B12"]["data"]["ar"]


# ---------------------------------------------------------------------------------------------- A6 / A7: what a user typed
def _backdate(svc, user, book, ref, days=1):
    at = (_dt.datetime.now() - _dt.timedelta(days=days)).replace(microsecond=0).isoformat(sep=" ")
    if user is None:
        svc.store._x("UPDATE shared_inputs SET updated_at=? WHERE book=? AND cell=?", (at, book, ref))
    else:
        svc.store._x("UPDATE user_inputs SET updated_at=? WHERE user=? AND book=? AND cell=?", (at, user, book, ref))
    return at


def test_the_market_levels_are_inputs_of_their_pages(svc):
    """Every range MARKET names is an input of its book (a two-way table's member or store too), every sheet named is
    there: a place that moves is found here."""
    for book_id, where, label in mi.MARKET:
        book = svc.books[book_id]
        if "!" not in where:
            assert where in book.model.sheet_index, where
            continue
        sheet, addr = where.split("!")
        r1, c1, r2, c2 = parse_range(addr)
        si = book.model.sheet_index[sheet]
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                key = (si, r * COLS + c)
                assert key in book.inputs or key in book.twoway, (where, r, c)
    assert mi.market_label("tto", "Forward!F2") == "Forward spot (elle)" and mi.market_label("tto", "EK_FWD!M5")
    assert mi.market_label("tto", "Forward!D2") is None and mi.market_label("sofr", "VIOP!AA9") is None
    assert mi.is_level(50.1, "number", "0.0000") and not mi.is_level("Elle spread", "text", None)
    assert not mi.is_level(46400.0, "date", None) and not mi.is_level(46400.0, None, "dd.mm.yyyy") and not mi.is_level(True, None, None)


def test_my_inputs_say_when_each_was_typed_and_which_are_old_market_levels(svc):
    """A7: each value with its time (``at``) and its pages; a market level typed before today is ``old`` - a setting, a
    date or a formula never; the desk's manual spot typed yesterday is the desk's, with who typed it."""
    u = svc.login("Kabuk Girdi")["user"]
    spot = cell(svc, "OIS_MAIN!B2")
    res = svc.set_inputs(u, "tto", [{"ref": "Forward!F2", "value": "50,1"}, {"ref": "EK_FWD!B4", "value": "Piyasa spread"},
                                    {"ref": "EK_TARIH!N5", "value": "=MASA!I60/100+35"},
                                    {"ref": "DV01_RISK!C6", "value": "1250"},
                                    {"ref": "EK_FWD!B104", "value": serial_to_date(spot + 40).strftime("%d.%m.%Y")}])
    assert res["errors"] == [], res
    got = {x["ref"]: x for x in svc.my_inputs(u)["inputs"]}
    today = _dt.date.today().isoformat()
    assert all(x["at"][:10] == today for x in got.values())
    f2 = got["Forward!F2"]
    assert f2["market"] == "Forward spot (elle)" and f2["old"] is False and {"view": "forward", "panel": "B1"} in f2["pages"]
    assert "market" not in got["EK_FWD!B4"] and "market" not in got["EK_FWD!B104"]          # (a setting, a date)
    assert got["DV01_RISK!C6"]["market"].startswith("Pozisyon DV01") and got["DV01_RISK!C6"]["pages"][0]["view"] == "dv01"
    for ref in ("Forward!F2", "EK_FWD!B4", "EK_TARIH!N5", "DV01_RISK!C6"):
        _backdate(svc, u, "tto", ref)
    got = {x["ref"]: x for x in svc.my_inputs(u)["inputs"]}
    assert got["Forward!F2"]["old"] is True and got["DV01_RISK!C6"]["old"] is True
    assert "market" not in got["EK_FWD!B4"] and got["EK_TARIH!N5"]["old"] is False           # (a formula reads its cells live)
    # the desk's own: the manual spot, typed yesterday - every page that shows it says so to everybody
    admin = svc.login("Kabuk Spot")["user"]
    assert svc.set_inputs(admin, "tto", [{"ref": "VIOP!AA9", "value": "49,9"}, {"ref": "VIOP!AA10", "value": "50"}])["errors"] == []
    _backdate(svc, None, "tto", "VIOP!AA9")
    desk = {x["ref"]: x for x in svc.my_inputs(u)["desk"]}
    assert desk["VIOP!AA9"]["old"] is True and desk["VIOP!AA9"]["shared"] and desk["VIOP!AA9"]["by"] == admin
    assert desk["VIOP!AA10"]["old"] is False and "viop" in {p["view"] for p in desk["VIOP!AA9"]["pages"]}
    svc.reset_inputs(admin, "tto", ["VIOP!AA9", "VIOP!AA10"], shared=True)
    assert not svc.my_inputs(u)["desk"]
    svc.reset_inputs(u, "tto", None)


def test_values_typed_over_formulas_and_the_normalization_in_the_header(svc):
    """A6: the header carries how many values a user typed over formulas (with every answer, also an unchanged one; none
    said: none) and whether their TLREF normalization is on; /api/my-inputs lists the values with their page."""
    u = svc.login("Kabuk Elle")["user"]
    before = svc.header(u)
    assert "hand" not in before and "mine" not in before
    assert svc.set_inputs(u, "tto", [{"ref": "EK_FWD!F50", "value": "55"}], allow_adhoc=True)["errors"] == []
    hand = [x for x in svc.my_inputs(u)["inputs"] if x.get("hand")]
    assert [x["ref"] for x in hand] == ["EK_FWD!F50"] and hand[0]["pages"][0]["view"] == "forward"
    head = svc.header(u)
    assert head["hand"] == 1
    again = svc.header_future(u, None, head["gen"], None, head["as"]).result()
    assert again.get("unchanged") and again["hand"] == 1
    spot = cell(svc, "OIS_MAIN!B2")
    assert svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!L2", "value": "Açık"},
                                     {"ref": "OIS_MAIN!L3", "value": serial_to_date(spot + 25).strftime("%d.%m.%Y")},
                                     {"ref": "OIS_MAIN!L4", "value": "33"}])["errors"] == []
    assert svc.header(u)["mine"] == {"norm": True}
    other = svc.login("Kabuk Elle Diğer")["user"]
    assert "mine" not in svc.header(other) and "hand" not in svc.header(other)              # (one user's is nobody else's)
    svc.reset_inputs(u, "tto", ["EK_FWD!F50"])
    assert "hand" not in svc.header(u)
    assert svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!L2", "value": "Kapalı"}])["errors"] == []
    assert "mine" not in svc.header(u)
    svc.reset_inputs(u, "tto", None)


# ---------------------------------------------------------------------------------------------- the browser's modules
STUB = ("const __stub = new Proxy({}, { get: (t, k) => (k === 'then' ? undefined : function stub() { return {}; }) });\n")
MODULES = {"menu": "menu.js", "hesap": "hesap.js", "mine": "mine.js"}
RUNNER = r"""
import * as menu from './menu.mjs';
import * as hesap from './hesap.mjs';
import * as mine from './mine.mjs';
const mods = { menu, hesap, mine };
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const calls = JSON.parse(raw);
  const plain = (x) => (x instanceof Set ? [...x] : x);
  const out = calls.map(([mod, name, args]) => {
    const x = mods[mod][name];
    return plain(typeof x === 'function' ? x(...(args || []).map((a) => (a && a.__set ? new Set(a.__set) : a))) : x);
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def _stubbed(src):
    def repl(m):
        names = []
        for x in m.group(1).split(","):
            x = x.strip()
            if x:
                a, _, b = x.partition(" as ")
                names.append(a.strip() + (": " + b.strip() if b else ""))
        return "const { " + ", ".join(names) + " } = __stub;"
    out = re.sub(r"^import\s*\{([^}]*)\}\s*from\s*'[^']+';", repl, src, flags=re.M)
    assert not re.search(r"^import\b", out, flags=re.M), "an import this harness does not read"
    return STUB + out


@pytest.fixture(scope="module")
def node_run(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to read the pages' modules")
    d = tmp_path_factory.mktemp("kabuk-js")
    for name, rel in MODULES.items():
        with open(os.path.join(JS, rel), encoding="utf-8") as fh:
            (d / (name + ".mjs")).write_text(_stubbed(fh.read()), encoding="utf-8")
    (d / "run.mjs").write_text(RUNNER, encoding="utf-8")

    def run(*calls):
        res = subprocess.run([node, str(d / "run.mjs")], input=json.dumps(calls), capture_output=True, text=True, encoding="utf-8",
                             timeout=60)
        assert res.returncode == 0, res.stderr
        return json.loads(res.stdout)

    return run


def test_the_menus_entries_their_hints_and_an_old_hidden_page(node_run, svc):
    """menu.js: the nav's entries with their hints and tabs; Araçlar folded until opened; an entry is out of the user's
    menu when its id was taken out - or, its pages entries of their own before 28.11.2026, when all of them were."""
    nav = svc.nav(None)
    model, tools, masa = node_run(["menu", "menuModel", [nav, False]], ["menu", "groupFolded", ["Araçlar"]], ["menu", "groupFolded", ["Masa"]])
    islem = next(e for g in model if g["group"] == "Masa" for e in g["entries"] if e["id"] == "masa.islemler")
    assert [t["id"] for t in islem["tabs"]] == ["blotter", "trades", "broker"] and islem["hint"].startswith("İşlemler —")
    assert islem["tabs"][1]["hint"].startswith("Trades — izlenen işlemler")
    assert tools is True and masa is False
    piyasa = next(e for g in model for e in g["entries"] if e["id"] == "masa.piyasa")
    hidden = node_run(["menu", "entryHidden", [piyasa, {"__set": ["heat"]}]], ["menu", "entryHidden", [piyasa, {"__set": ["heat", "eod", "watch"]}]],
                      ["menu", "entryHidden", [piyasa, {"__set": ["masa.piyasa"]}]], ["menu", "entryHidden", [{"id": "dv01", "title": "DV01"}, {"__set": ["dv01"]}]])
    assert hidden == [False, True, True, True]


def test_the_hesap_chip_is_short_and_the_times_read_as_the_desk_writes_them(node_run):
    """B9: "Hesap" says the first job's count, how many more and the time left (each job in its tooltip); A6 / A7: a time
    as "27.11 17:02"."""
    planted = {"busy": True, "eta": "~3 dk", "text": "Quant 14/26 · ML 240/480 · geri test 12/25 · ~3 dk",
               "jobs": [{"short": "Quant 14/26"}, {"short": "ML 240/480"}, {"short": "geri test 12/25"}]}
    one = {"busy": True, "eta": "", "jobs": [{"short": "PPK geçmişi 98/254"}]}
    got = node_run(["hesap", "shortText", [planted]], ["hesap", "shortText", [one]], ["mine", "dayTime", ["2026-11-27 17:02:11"]],
                   ["mine", "dayTime", [""]])
    assert got == ["Quant 14/26 +2 · ~3 dk", "PPK geçmişi 98/254", "27.11 17:02", "—"]


def test_the_shell_uses_its_shared_parts():
    """B7: the pages, the launchpad's and the drawer's boxes wait with the one "Hesaplanıyor…" (ui.js waiting); B2: a tab's
    note folds to a line (view.js, foldNote); B3: a page in tabs has its tools in the tab line."""
    def src(rel):
        with open(os.path.join(JS, rel), encoding="utf-8") as fh:
            return fh.read()
    assert "export function waiting(" in src("ui.js")
    for rel in ("pages/view.js", "boxes.js", "pagebox.js"):
        assert "waiting()" in src(rel) and "'Yükleniyor…'" not in src(rel), rel
    view = src("pages/view.js")
    assert "this.secFold = foldNote(this.secNote)" in view and "h('div', { class: 'tabline' }, this.tabBar, tools)" in view
    css = src(os.path.join("..", "css", "app.css"))
    for rule in (".tabline {", ".secnote.clamp {", "#side.peek {", "table.grid.notevis td.ovw > .ovt {", ".badge.mine {",
                 ".waiting .spin {"):
        assert rule in css, rule
