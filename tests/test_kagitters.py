"""Bonds the other way round (the desk, 24.11.2026: "1-2-3-4-5-6-7-8-11-11-13"): a level typed -> the clean price it means,
each the exact inverse of what its page works out the other way (``tto/extras.py``, "bonds the other way round").

* DİBS ASW: an ASW typed -> the clean price, on the ASW sheet's own OIS curve (5);
* DİBS RV: an ASW (fixed coupon, bill) or a DM (TLREF floater) typed -> the clean price, on its TRY OIS curve (5);
* DİBS RV's SWITCH / PAIR: a switch level (yield or ASW / DM, bp) -> the Al leg's clean price, the Sat leg at the
  market (6);
* Manuel Tahvil: an ISIN -> the bond's terms as the inputs' defaults, so its targets price that bond (7).

Every answer is checked against the page's own forward cells: the price found, typed as the bond's manual clean price,
gives back the level typed (to 1e-9) - and against the formula worked by hand from the row's cells.  What is typed for a
bond stays with its ISIN when the bond list moves the bonds (``tto/rowkeys.py``)."""
from __future__ import annotations

import datetime as _dt

import pytest

from conftest import cell, make_service
from tto import bonds as bd
from tto import extras
from tto.views import load_views
from tto.xl.model import COLS, parse_a1
from tto.xl.values import date_to_serial

LIST, ASW_LIST = "DİBS RV!A5:A54", "ASW!B7:B56"


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """A service of its own: the tests move bonds on the desk's lists."""
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def put(s, user, book, cells, adhoc=False):
    res = s.set_inputs(user, book, [{"ref": ref, "value": value} for ref, value in cells.items()], allow_adhoc=adhoc)
    assert res["errors"] == [], res["errors"]
    return res


def row_of(s, user, isin, where=LIST, book="tto"):
    first = int(where.split("!")[1].split(":")[0][1:])
    return s._list_values(user, book, where).index(isin) + first


def reader(s, user, sheet, book="tto"):
    return lambda addr: cell(s, "%s!%s" % (sheet, addr), user, book=book)


def block(get, first, last, r):
    """A row's block of DİBS RV ("ID", "JA" -> 24 values)."""
    c1, c2 = parse_a1(first + "1") % COLS, parse_a1(last + "1") % COLS
    from tto.xl.tokenizer import index_to_col
    return [get("%s%d" % (index_to_col(c), r)) for c in range(c1, c2 + 1)]


def panel(s, user, view, pid):
    page = s.view(user, view)
    return [p["id"] for p in page["panels"]], next(p for p in page["panels"] if p["id"] == pid)


# ============================================================================== 5. DİBS ASW: ASW -> price
def test_an_asw_typed_on_dibs_asw_gives_the_clean_price_it_means(svc):
    """The ASW sheet's own R = (P − O) / Q · 100, O = (L + N) · (1 + TLREF · (spot − valör) / 365), solved for the clean
    price L: a bill and a short and a long fixed coupon bond, their own ASW back to their own price, other levels to the
    formula worked by hand; that price typed as the manual clean price gives back the ASW typed (and does not move the
    answer: P, Q, N and the carry do not depend on the price).  Its own table under the bonds' table, the input yellow."""
    s = svc
    u = s.login("ASW ters")["user"]
    A = reader(s, u, "ASW", "asw")
    for isin in ("TRB100227T13", "TRT150328T24", "TRT050935T13"):
        r = row_of(s, u, isin, ASW_LIST, "asw")
        asw, clean = A("R%d" % r), A("L%d" % r)
        assert isinstance(asw, float) and isinstance(clean, float) and A("W%d" % r) == ""       # nothing typed: nothing
        put(s, u, "asw", {"ASW!V%d" % r: asw})
        assert A("W%d" % r) == pytest.approx(clean, abs=1e-9) and abs(A("X%d" % r)) < 1e-9 and A("Y%d" % r) == ""
        for level in (asw - 25.5, asw + 40.0):
            put(s, u, "asw", {"ASW!V%d" % r: level})
            got = A("W%d" % r)
            by_hand = (A("P%d" % r) - level / 100 * A("Q%d" % r)) / (1 + A("E4") * (A("C4") - A("M%d" % r)) / 365) - A("N%d" % r)
            assert got == pytest.approx(by_hand, abs=1e-12) and A("X%d" % r) == pytest.approx(got - clean, abs=1e-12)
            assert (got < clean) == (level > asw)                       # cheaper at a wider ASW
            put(s, u, "asw", {"ASW!D%d" % r: got})                     # forward: the price as the manual clean price
            assert A("L%d" % r) == got and A("R%d" % r) == pytest.approx(level, abs=1e-9)
            assert A("W%d" % r) == pytest.approx(got, abs=1e-9)
            put(s, u, "asw", {"ASW!D%d" % r: ""})
        assert A("L%d" % r) == clean
    # a TLREF floater: its ASW is not worked out here - DM -> price is DİBS RV's
    r = row_of(s, u, "TRT090130T12", ASW_LIST, "asw")
    put(s, u, "asw", {"ASW!V%d" % r: 100})
    assert A("W%d" % r) == "" and A("Y%d" % r) == "TLREF endeksli: DM → temiz fiyat DİBS RV'de"
    # each user's own
    other = s.login("ASW ters başka")["user"]
    assert cell(s, "ASW!V%d" % r, other, book="asw") is None and cell(s, "ASW!W%d" % row_of(s, u, "TRT150328T24", ASW_LIST, "asw"), other, book="asw") == ""
    # the page: its own table right after the bonds' table, the bonds only, kind by kind, the typed ASW an input
    ids, p = panel(s, u, "asw", "aswters")
    data = p["data"]
    assert ids[ids.index("tbl") + 1] == "aswters" and "kendi OIS eğrisine göre" in p["title"] and "ASW FX" in p["note"]
    assert data["c"] == ["B", "F", "H", "I", "L", "R", "V", "W", "X", "Y"]
    assert [c["t"] for c in data["rows"][0]][6:] == ["Hedef ASW (bp)", "Temiz (hedef ASW'den)", "Fark (temiz)", "Not"]
    bond_rows = [row for row, r in zip(data["rows"], data["r"]) if isinstance(r, int) and r >= 7]
    assert bond_rows and all(row[0]["t"].startswith("TR") for row in bond_rows)
    assert all(row[6].get("i") == "u" for row in bond_rows) and not any(row[7].get("i") for row in bond_rows)
    assert any(c["t"] == "Bono · 2 kâğıt" for row in data["rows"] for c in row[:1])


def test_a_typed_asw_stays_with_its_bond_when_the_asw_list_moves(svc):
    """Rows move: two bonds of the ASW list swapped - each user's ASW typed for a bond (and its answer) goes with it."""
    s = svc
    u, desk = s.login("ASW ters kayan")["user"], s.login("ASW ters masa")["user"]
    A = reader(s, u, "ASW", "asw")
    a, b = "TRT150328T24", "TRT130928T38"
    ra, rb = row_of(s, u, a, ASW_LIST, "asw"), row_of(s, u, b, ASW_LIST, "asw")
    put(s, u, "asw", {"ASW!V%d" % ra: -50, "ASW!V%d" % rb: 10})
    before = {a: A("W%d" % ra), b: A("W%d" % rb)}
    res = put(s, desk, "asw", {"ASW!B%d" % ra: b, "ASW!B%d" % rb: a})
    assert {m["isin"] for m in res["row_values"]["moved"]} == {a, b}
    assert (row_of(s, u, a, ASW_LIST, "asw"), row_of(s, u, b, ASW_LIST, "asw")) == (rb, ra)
    assert (A("V%d" % rb), A("V%d" % ra)) == (-50.0, 10.0)
    assert A("W%d" % rb) == pytest.approx(before[a], abs=1e-9) and A("W%d" % ra) == pytest.approx(before[b], abs=1e-9)
    put(s, desk, "asw", {"ASW!B%d" % ra: a, "ASW!B%d" % rb: b})
    assert (A("V%d" % ra), A("V%d" % rb)) == (-50.0, 10.0)


# ============================================================================== 5. DİBS RV: ASW / DM -> price
def _dm_price(R, r, dm_bp):
    """A floater's clean price at a DM, by hand: Σ CF_k · Π_{j≤k} 1 / (1 + (fw_j + DM) · τ_j), / funding − accrued."""
    cf, fw, tau = block(R, "ID", "JA", r), block(R, "NR", "OO", r), block(R, "JZ", "KW", r)
    pv, df = 0.0, 1.0
    for c, f, t in zip(cf, fw, tau):
        df /= 1 + (f + dm_bp / 10000) * t
        pv += c * df
    return pv / R("DD%d" % r) - R("CW%d" % r)


def test_an_asw_or_a_dm_typed_on_dibs_rv_gives_the_clean_price_it_means(svc):
    """DİBS RV, its TRY OIS curve: a fixed coupon bond's or a bill's ASW (EH = (PV − dirty @spot) / annuity · 100), a TLREF
    floater's DM (its solver's price: the cash flows at the forwards + DM, period by period; a floater with its first
    coupon fixed too) -> the clean price; worked by hand from the row's cells; typed as the manual clean price it gives
    back the level (the unrounded ASW / DM to 1e-9, the page's column to its 0.1 bp)."""
    s = svc
    u = s.login("RV ters")["user"]
    R = reader(s, u, "DİBS RV")
    for isin in ("TRB100227T13", "TRT150328T24", "TRT050935T13", "TRT090130T12", "TRT030730T12", "TRT110930T36"):
        r = row_of(s, u, isin)
        kind, clean = R("D%d" % r), R("O%d" % r)
        level_now = R("EN%d" % r) * 10000 if kind == "T" else R("EH%d" % r)
        assert kind in ("B", "S", "T") and isinstance(clean, float) and R("BL%d" % r) == ""
        put(s, u, "tto", {"DİBS RV!BK%d" % r: level_now})
        assert R("BL%d" % r) == pytest.approx(clean, abs=1e-9) and R("BN%d" % r) == ("DM'den" if kind == "T" else "ASW'den")
        for level in (level_now - 30.0, level_now + 55.5):
            put(s, u, "tto", {"DİBS RV!BK%d" % r: level})
            got = R("BL%d" % r)
            by_hand = (_dm_price(R, r, level) if kind == "T"
                       else (R("EG%d" % r) - level * R("EE%d" % r) / 100) / R("DD%d" % r) - R("CW%d" % r))
            assert got == pytest.approx(by_hand, abs=1e-9) and R("BM%d" % r) == pytest.approx(got - clean, abs=1e-12)
            assert (got < clean) == (level > level_now)
            put(s, u, "tto", {"DİBS RV!N%d" % r: got})
            back = R("EN%d" % r) * 10000 if kind == "T" else R("EH%d" % r)
            assert back == pytest.approx(level, abs=1e-9), (isin, level)
            assert abs(R("Z%d" % r) - level) <= 0.05 + 1e-9                    # (the page's column: to 0.1 bp)
            assert R("BL%d" % r) == pytest.approx(got, abs=1e-9)
            put(s, u, "tto", {"DİBS RV!N%d" % r: ""})
    # an FRN has no DM, a CPI linker no ASW (the kind typed over by hand: the replay file has neither on the list)
    r = row_of(s, u, "TRT090130T12")
    for kind, why in (("F", "FRN: DM yok - yalnız fiyatla izlenir"), ("E", "TÜFE: reel getiri, ASW yok")):
        put(s, u, "tto", {"DİBS RV!D%d" % r: kind}, adhoc=True)
        assert R("BL%d" % r) == "" and R("BN%d" % r) == why
    s.reset_inputs(u, "tto", ["DİBS RV!D%d" % r])
    assert R("D%d" % r) == "T" and isinstance(R("BL%d" % r), float)
    # a bond with no price: its row is not worked out - any price makes it, and the answer does not depend on it
    r = row_of(s, u, "TRT081128T15")
    put(s, u, "tto", {"DİBS RV!BK%d" % r: 50})
    assert R("BL%d" % r) == "" and R("BN%d" % r) == "Fiyat yok: Manuel temiz'e bir fiyat yazın - sonuç ona bağlı değil"
    put(s, u, "tto", {"DİBS RV!N%d" % r: 95})
    got = R("BL%d" % r)
    put(s, u, "tto", {"DİBS RV!N%d" % r: 90})
    assert isinstance(got, float) and R("BL%d" % r) == pytest.approx(got, abs=1e-9)
    put(s, u, "tto", {"DİBS RV!N%d" % r: got})
    assert R("EH%d" % r) == pytest.approx(50, abs=1e-9)
    put(s, u, "tto", {"DİBS RV!N%d" % r: ""})
    # the page: its own table after the bonds' table, the bonds only, the typed level an input
    ids, p = panel(s, u, "dibs", "B3r")
    data = p["data"]
    assert ids[ids.index("B3") + 1] == "B3r" and ids[ids.index("B3r") + 1] == "B4" and "TRY OIS" in p["title"]
    assert data["c"] == ["A", "C", "D", "E", "O", "Z", "BK", "BL", "BM", "BN"]
    rows = [row for row, rr in zip(data["rows"], data["r"]) if isinstance(rr, int) and rr >= 5]
    assert rows and all(row[0]["t"].startswith("TR") for row in rows) and all(row[6].get("i") == "u" for row in rows)


def _asw_price(R, r, asw_bp):
    """A fixed coupon bond's or a bill's clean price at an ASW, by hand: (PV − ASW · annuity / 100) / funding − accrued."""
    return (R("EG%d" % r) - asw_bp * R("EE%d" % r) / 100) / R("DD%d" % r) - R("CW%d" % r)


def swapped(s, desk, a, b):
    """The desk swaps two bonds of the trading list (and swaps them back on leaving)."""
    class _Swap(object):
        def __enter__(self):
            self.ra, self.rb = row_of(s, desk, a), row_of(s, desk, b)
            self.res = put(s, desk, "tto", {"DİBS RV!A%d" % self.ra: b, "DİBS RV!A%d" % self.rb: a})
            return self

        def __exit__(self, *exc):
            put(s, desk, "tto", {"DİBS RV!A%d" % self.ra: a, "DİBS RV!A%d" % self.rb: b})
    return _Swap()


def test_a_typed_asw_or_dm_stays_with_its_bond_when_the_trading_list_moves(svc):
    """Rows move: the desk swaps two bonds of the trading list - each user's level typed for a bond goes with it and is
    worked out on the bond's new row.  (The recorded file pins each row's Bloomberg answers to the row - on the desk a
    bond's data follows its ISIN -, so the answer is checked against the new row's own cells.)"""
    s = svc
    u, desk = s.login("RV ters kayan")["user"], s.login("RV ters masa")["user"]
    R = reader(s, u, "DİBS RV")
    a, b = "TRT150328T24", "TRT130928T38"
    ra, rb = row_of(s, u, a), row_of(s, u, b)
    put(s, u, "tto", {"DİBS RV!BK%d" % ra: -40, "DİBS RV!BK%d" % rb: 25})
    before = {a: R("BL%d" % ra), b: R("BL%d" % rb)}
    with swapped(s, desk, a, b) as sw:
        assert {m["isin"] for m in sw.res["row_values"]["moved"]} >= {a, b}
        assert (row_of(s, u, a), row_of(s, u, b)) == (rb, ra) and (R("BK%d" % rb), R("BK%d" % ra)) == (-40.0, 25.0)
        for r, level in ((rb, -40.0), (ra, 25.0)):
            assert R("BL%d" % r) == pytest.approx(_asw_price(R, r, level), abs=1e-9)
    assert (R("BK%d" % ra), R("BK%d" % rb)) == (-40.0, 25.0)
    assert R("BL%d" % ra) == pytest.approx(before[a], abs=1e-12) and R("BL%d" % rb) == pytest.approx(before[b], abs=1e-12)
    s.reset_inputs(u, "tto", ["DİBS RV!BK%d" % ra, "DİBS RV!BK%d" % rb])


# ============================================================================== 6. SWITCH / PAIR: level -> Al's price
def test_a_switch_level_gives_the_al_legs_clean_price(svc):
    """SWITCH / PAIR: a yield level is Al − Sat BIST simple yield (G), an ASW / DM level Al − Sat ASW / DM as the page
    shows them (I); the Sat leg at the market, the Al leg's clean price solved - fixed / fixed, a bill as the Al leg, two
    TLREF floaters (DM), a fixed coupon Sat leg against a floater (ASW vs DM).  The Al leg's price typed as its manual
    clean price gives the level back in G / I; a level a leg cannot give (a floater's yield) says why."""
    s = svc
    u = s.login("Switch ters")["user"]
    R = reader(s, u, "DİBS RV")
    pairs = {64: ("TRT150328T24", "TRT130928T38"), 65: ("TRT150328T24", "TRB170327T15"),
             66: ("TRT090130T12", "TRT030730T12"), 67: ("TRT150328T24", "TRT110930T36")}
    for r, (sat, al) in pairs.items():
        put(s, u, "tto", {"DİBS RV!A%d" % r: sat, "DİBS RV!B%d" % r: al, "DİBS RV!C%d" % r: 10})
    assert all(R("%s%d" % (c, r)) == "" for r in pairs for c in "VXYZ")                     # no level: nothing

    def forward(r, price, then):
        """The Al leg's price typed as its manual clean price: what ``then`` reads."""
        ra = row_of(s, u, pairs[r][1])
        put(s, u, "tto", {"DİBS RV!N%d" % ra: price})
        try:
            return then()
        finally:
            put(s, u, "tto", {"DİBS RV!N%d" % ra: ""})

    # yield levels: fixed / fixed and a bill as the Al leg
    for r in (64, 65):
        sat_row, al_row = row_of(s, u, pairs[r][0]), row_of(s, u, pairs[r][1])
        now = R("G%d" % r)
        put(s, u, "tto", {"DİBS RV!U%d" % r: now})
        assert R("V%d" % r) == pytest.approx(R("O%d" % al_row), abs=1e-9) and R("Y%d" % r) == R("O%d" % al_row)
        level = now + 12.5
        put(s, u, "tto", {"DİBS RV!U%d" % r: level})
        got = R("V%d" % r)
        y = R("S%d" % sat_row) + level / 10000
        if R("CR%d" % al_row) == "B":
            by_hand = 100 / (1 + y * R("DR%d" % al_row) / 365)
        else:
            cf, x, f = block(R, "ID", "JA", al_row), block(R, "LV", "MS", al_row), R("CU%d" % al_row)
            by_hand = sum(c * (1 + y / f) ** -t for c, t in zip(cf, x)) - R("CW%d" % al_row)
        assert got == pytest.approx(by_hand, abs=1e-9) and got < R("O%d" % al_row)
        assert forward(r, got, lambda: R("G%d" % r)) == pytest.approx(level, abs=1e-9)
    # ASW / DM levels: fixed / fixed (ASW), floater / floater (DM), fixed against a floater (ASW vs DM)
    for r, level in ((64, 3.5), (66, 15.0), (67, -20.0)):
        sat_row, al_row = row_of(s, u, pairs[r][0]), row_of(s, u, pairs[r][1])
        put(s, u, "tto", {"DİBS RV!W%d" % r: level})
        got = R("X%d" % r)
        target = R("Z%d" % sat_row) + level
        by_hand = _dm_price(R, al_row, target) if R("D%d" % al_row) == "T" else _asw_price(R, al_row, target)
        assert isinstance(got, float) and got == pytest.approx(by_hand, abs=1e-9), r

        def back(al_row=al_row, sat_row=sat_row, r=r):
            al_level = R("EN%d" % al_row) * 10000 if R("D%d" % al_row) == "T" else R("EH%d" % al_row)
            return al_level - R("Z%d" % sat_row), R("I%d" % r)
        exact, shown = forward(r, got, back)
        assert exact == pytest.approx(level, abs=1e-9) and shown == pytest.approx(level, abs=1e-9), (r, exact, shown)
    # a level a leg cannot give: a TLREF floater has no yield
    put(s, u, "tto", {"DİBS RV!U66": 10, "DİBS RV!U67": 10})
    assert R("V66") == "" and R("Z66") == "Getiri: Sat bacağının getirisi yok (TLREF / FRN ya da fiyatı yok)."
    assert R("V67") == "" and R("Z67") == "Getiri: Al bacağının getirisi yok (TLREF / FRN ya da fiyatı yok)."
    assert isinstance(R("X67"), float)                                    # (its ASW / DM level still priced)
    # the table: the new columns at its right, its note under the sheet's own (and since, the two-way table's price:
    # test_kagit_twoway.py)
    _, p = panel(s, u, "dibs", "B4")
    data = p["data"]
    assert p["range"] == "A62:AA78" and data["c"][-7:] == ["U", "V", "W", "X", "Y", "Z", "AA"]
    head = next(row for row, rr in zip(data["rows"], data["r"]) if rr == 63)
    assert [c["t"] for c in head[-7:-1]] == ["Getiri seviyesi (bp)", "Al temiz (getiri seviyesinden)", "ASW/DM seviyesi (bp)",
                                             "Al temiz (ASW/DM seviyesinden)", "Al temiz (şimdi)", "Seviye notu"]
    note = next(row for row, rr in zip(data["rows"], data["r"]) if rr == extras.SW_NOTE)
    assert note[0]["t"].startswith("Seviye → Al fiyatı: Sat bacağı piyasada kalır")
    # rows move: the pair is typed by ISIN - the desk swaps its two bonds on the trading list: its levels stay on it and
    # it reads its bonds where they stand now (the same pair and levels typed afresh on another row read the same; the
    # recorded file pins each row's Bloomberg answers to the row, so not the prices of before)
    desk = s.login("Switch ters masa")["user"]
    before = [R("%s64" % c) for c in "UVWXY"]
    a, b = pairs[64]
    put(s, u, "tto", {"DİBS RV!A70": a, "DİBS RV!B70": b, "DİBS RV!U70": before[0], "DİBS RV!W70": before[2]})
    with swapped(s, desk, a, b):
        after = [R("%s64" % c) for c in "UVWXY"]
        assert (after[0], after[2]) == (before[0], before[2]) and all(isinstance(x, float) for x in after)
        assert after == [R("%s70" % c) for c in "UVWXY"]
        assert after[4] == R("O%d" % row_of(s, u, b))
    assert [R("%s64" % c) for c in "UVWXY"] == before
    s.reset_inputs(u, "tto", ["DİBS RV!%s%d" % (c, r) for r in range(64, 76) for c in "ABCUW"])


# ============================================================================== 7. Manuel Tahvil: ISIN
def _serial(iso):
    return date_to_serial(_dt.date.fromisoformat(iso))


def test_without_an_isin_manuel_tahvil_keeps_the_workbooks_defaults(svc):
    """Nothing typed: every input the ISIN would fill is the workbook's own (the file's terms, T+1 valör), the status
    says what to type."""
    s = svc
    u = s.login("Manuel boş")["user"]
    M = reader(s, u, "Manuel Tahvil")
    assert [M(a) for a in ("B7", "B8", "B10", "B11", "B12", "B13", "B14")] == [47373.0, 2.0, "S", 30.0, 0.0, 2.0, 90.1]
    assert M("B15") == "" and M("B3") == cell(s, "OIS_MAIN!B2", u) and all(M("H%d" % r) == "" for r in range(24, 64))
    assert M("C17").startswith("Kâğıdın ISIN'i:") and M("B17") is None


def test_an_isin_fills_manuel_tahvils_terms_and_its_targets_price_the_bond(svc):
    """A fixed coupon bond of the trading list: its maturity, coupon, frequency, the clean price in use and its valör come
    in; the targets (BIST yield, ASW, Z) give clean prices that, typed as the price, read back the target; a value typed
    over a default comes first (said) and Delete brings the bond's back.  A TLREF floater of the trading list: its
    margin, the current period's known coupon, the realized index; its DM target likewise."""
    s = svc
    u = s.login("Manuel ISIN")["user"]
    M, R = reader(s, u, "Manuel Tahvil"), reader(s, u, "DİBS RV")
    put(s, u, "tto", {"Manuel Tahvil!B17": " trt150328t24 "})
    r = row_of(s, u, "TRT150328T24")
    bond = bd.by_isin("TRT150328T24")
    assert M("B7") == _serial(bond["maturity"]) == R("CT%d" % r)
    assert M("B11") == R("CS%d" % r) == bond["coupon"] == 36.8 and (M("B8"), M("B10"), M("B12")) == (2.0, "S", 0.0)
    assert M("B14") == R("O%d" % r) and M("B3") == R("P%d" % r) and M("B15") == "" and M("H24") == ""
    assert M("C17") == "15.03.28 · sabit %36,80 · yılda 2 kupon · fiyat: DİBS RV · kullanılan temiz"
    for target, result, scale, shift in (("I10", "F7", 100, 0.75), ("I11", "F15", 1, -35.0), ("I12", "F16", 1, 20.0)):
        level = M(result) * scale + shift
        put(s, u, "tto", {"Manuel Tahvil!" + target: level})
        got = M("J" + target[1:])
        assert isinstance(got, float) and got != M("B14")
        put(s, u, "tto", {"Manuel Tahvil!B14": got})
        assert M(result) * scale == pytest.approx(level, abs=1e-9), target
        assert "elle yazılan (önce gelir): fiyat" in M("C17")
        put(s, u, "tto", {"Manuel Tahvil!B14": "", "Manuel Tahvil!" + target: ""})
        assert M("B14") == R("O%d" % r)
    # a value typed over a default comes first and is said; Delete brings the bond's back
    put(s, u, "tto", {"Manuel Tahvil!B11": 35})
    assert M("B11") == 35.0 and M("C17").endswith("elle yazılan (önce gelir): kupon")
    put(s, u, "tto", {"Manuel Tahvil!B11": ""})
    assert M("B11") == 36.8 and "elle" not in M("C17")
    # the manual clean price typed on DİBS RV is the price in use there - and here
    put(s, u, "tto", {"DİBS RV!N%d" % r: 99.5})
    assert M("B14") == 99.5
    put(s, u, "tto", {"DİBS RV!N%d" % r: ""})
    # a TLREF floater of the trading list whose first coupon is fixed
    put(s, u, "tto", {"Manuel Tahvil!B17": "TRT030730T12"})
    r = row_of(s, u, "TRT030730T12")
    assert (M("B10"), M("B11"), M("B8")) == ("D", 0.0, R("CU%d" % r)) and M("B12") == R("CY%d" % r)
    assert M("B13") == R("V2") and M("B14") == R("O%d" % r) and M("B15") == R("DQ%d" % r)
    assert M("H24") == R("DP%d" % r) == 20.0 and all(M("H%d" % k) == "" for k in range(25, 64))
    assert "cari dönemin kuponu %20,00 (bilinen, dönemsel)" in M("C17") and "DİBS RV" in M("C17")
    assert M("R24") == 20.0                                     # (the period table's coupon of the current period)
    level = M("I3") + 20
    put(s, u, "tto", {"Manuel Tahvil!I8": level})
    got = M("J13")
    put(s, u, "tto", {"Manuel Tahvil!B14": got})
    assert M("I3") == pytest.approx(level, abs=1e-9)
    put(s, u, "tto", {"Manuel Tahvil!B14": "", "Manuel Tahvil!I8": ""})
    # a floater without a known coupon: the realized index part of its accrued (the current period's own projection)
    put(s, u, "tto", {"Manuel Tahvil!B17": "TRT090130T12"})
    r = row_of(s, u, "TRT090130T12")
    assert M("H24") == "" and M("B15") == R("DQ%d" % r) and "cari dönemin kuponu gerçekleşen endeksten" in M("C17")
    put(s, u, "tto", {"Manuel Tahvil!B17": ""})


def test_an_isin_off_the_trading_list_takes_the_catalog_and_tum_kagitlar(svc):
    """A fixed coupon bond off the trading list: the catalog's maturity and coupon, semi-annual; its price the middle of
    Tüm Kâğıtlar' bid / ask, else today's last trade there (the recorded file has none for it: no price, said - the
    targets need none)."""
    s = svc
    u = s.login("Manuel katalog")["user"]
    M = reader(s, u, "Manuel Tahvil")
    put(s, u, "tto", {"Manuel Tahvil!B17": "TRT240227T17"})
    bond = bd.by_isin("TRT240227T17")
    assert (M("B7"), M("B11"), M("B8"), M("B10")) == (_serial(bond["maturity"]), bond["coupon"], 2.0, "S")
    assert M("B14") == "" and M("B3") == cell(s, "OIS_MAIN!B2", u)
    assert M("C17").endswith("fiyat yok: Temiz fiyat'ı yazın (Hedef → temiz fiyat fiyatsız da çalışır)")
    put(s, u, "tto", {"Manuel Tahvil!I11": -100})
    assert isinstance(M("J11"), float)
    # Tüm Kâğıtlar' quotes for it (typed over its cells by hand, "Elle değer": the recorded file has none)
    uni = "%s!A%d:A%d" % (extras.UNI_SHEET, extras.UNI_FIRST, extras.UNI_LAST)
    u_row = extras.UNI_FIRST + s._list_values(u, "tto", uni).index("TRT240227T17")
    ek = lambda col: "%s!%s%d" % (extras.UNI_SHEET, col, u_row)                    # noqa: E731
    put(s, u, "tto", {ek("I"): 97.5, ek("J"): 97.9, ek("K"): 97.6}, adhoc=True)
    assert M("B14") == pytest.approx(97.7, abs=1e-12) and "fiyat: Tüm Kâğıtlar · bid / ask ortası" in M("C17")
    # one side only: today's last trade; a last trade of another day: no price
    s.reset_inputs(u, "tto", [ek("J")])
    today = s.books["tto"].engine.clock.today()
    put(s, u, "tto", {ek("L"): today}, adhoc=True)
    assert M("B14") == 97.6 and "fiyat: Tüm Kâğıtlar · bugünkü son işlem" in M("C17")
    put(s, u, "tto", {ek("L"): today - 1}, adhoc=True)
    assert M("B14") == ""
    s.reset_inputs(u, "tto", [ek(c) for c in "IKL"] + ["Manuel Tahvil!I11", "Manuel Tahvil!B17"])


@pytest.mark.parametrize("isin, why", [
    ("TRB100227T13", "Bono / kuponsuz: Manuel Tahvil kuponlu kâğıt içindir"),
    ("TRT060127T10", "Bono / kuponsuz"),
    ("TRT070727T13", "TÜFE'ye endeksli: reel kupon ve endeks - Manuel Tahvil fiyatlamaz"),
    ("TRT130928T12", "FRN: TLREF dışı endeks - Manuel Tahvil fiyatlamaz"),
    ("TRT131027T10", "TLREF'e endeksli: kupon payı ve bilinen kupon DİBS RV'den gelir - kâğıdı trading listesine ekleyin"),
    ("TRT210329T17", "Kuponu bilinmiyor"),
    ("TRT010101T10", "ISIN kâğıt listesinde yok"),
])
def test_an_isin_manuel_tahvil_does_not_price_is_refused_with_the_reason(svc, isin, why):
    """Bills and zero coupon bonds (Manuel Tahvil's yield is the coupon bonds' rule), CPI linkers, FRNs, a TLREF floater
    off the trading list (its margin and known coupon are DİBS RV's), a fixed coupon bond without a coupon, an ISIN the
    list does not know: nothing is filled, the status says why."""
    s = svc
    u = s.login("Manuel ret %s" % isin)["user"]
    M = reader(s, u, "Manuel Tahvil")
    put(s, u, "tto", {"Manuel Tahvil!B17": isin})
    assert why in M("C17"), M("C17")
    assert [M(a) for a in ("B7", "B8", "B10", "B11", "B12", "B13", "B14")] == [47373.0, 2.0, "S", 30.0, 0.0, 2.0, 90.1]
    assert M("B15") == "" and M("B3") == cell(s, "OIS_MAIN!B2", u)


def test_the_isins_bond_is_found_by_its_isin_when_the_list_moves(svc):
    """Rows move: the bond picked by its ISIN moves on the trading list - its terms (the catalog's, kept by ISIN), its
    price (a manual one typed there follows it) and valör still come from it."""
    s = svc
    u, desk = s.login("Manuel kayan")["user"], s.login("Manuel kayan masa")["user"]
    M = reader(s, u, "Manuel Tahvil")
    a, b = "TRT160431T35", "TRT051033T12"
    ra = row_of(s, u, a)
    put(s, u, "tto", {"Manuel Tahvil!B17": a, "DİBS RV!N%d" % ra: 94.25})
    before = [M(x) for x in ("B3", "B7", "B8", "B11", "B14")]
    assert before[-1] == 94.25 and before[1] == _serial(bd.by_isin(a)["maturity"]) and before[3] == bd.by_isin(a)["coupon"]
    with swapped(s, desk, a, b) as sw:
        assert row_of(s, u, a) == sw.rb and cell(s, "DİBS RV!N%d" % sw.rb, u) == 94.25
        assert [M(x) for x in ("B3", "B7", "B8", "B11", "B14")] == before
    s.reset_inputs(u, "tto", ["DİBS RV!N%d" % ra, "Manuel Tahvil!B17"])


# ============================================================================== the inputs
def test_the_new_inputs_stand_where_no_input_ever_stood():
    """Each user's own, blank at the start, on cells no layout ever had an input on (none retired, none another
    table's): DİBS ASW's ASW, DİBS RV's ASW / DM and switch levels, Manuel Tahvil's ISIN."""
    views = {v["id"]: v for v in load_views()}
    new = {"asw": ["V7:V56"], "dibs": ["BK5:BK54", "U64:U75", "W64:W75"], "manuel": ["B17"]}

    def cells(rng):
        a1, _, a2 = rng.partition(":")
        (r1, c1), (r2, c2) = divmod(parse_a1(a1), COLS), divmod(parse_a1(a2 or a1), COLS)
        return {(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}

    for vid, ranges in new.items():
        have = {i["range"]: i for i in views[vid]["inputs"]}
        for rng in ranges:
            assert have[rng]["scope"] == "user" and have[rng]["kind"] in ("number", "text")
        mine = set().union(*(cells(x) for x in ranges))
        others = set().union(*(cells(x) for x in have if x not in ranges and "!" not in x))
        assert not mine & others, vid
    assert not any(ref.startswith(("ASW!", "DİBS RV!", "Manuel Tahvil!")) for refs in extras.RETIRED_INPUTS.values() for ref in refs)


def test_the_reverse_formulas_are_the_exact_inverse_of_the_sheets(svc):
    """The formulas' texts: each reads the cells of the forward formula it inverts (a sheet that no longer has them
    leaves the addition out - ``extras._need_formula`` checks); every addition fits the recorded workbooks."""
    s = svc
    assert all(b.left_out == [] for b in s.books.values())
    assert extras.asw_clean_from_asw(9, "$V9") == "($P9-($V9)/100*$Q9)/(1+$E$4*($C$4-$M9)/365)-$N9"
    at = extras.rv_at(8)
    assert extras.rv_clean_from_asw(at, "$BK8") == "(EG8-($BK8)*EE8/100)/DD8-CW8"
    assert extras.rv_clean_from_dm(at, "$BK8").startswith("SUMPRODUCT($ID8:$JA8,EXP(-MMULT(LN(1+($NR8:$OO8+($BK8)/10000)*$JZ8:$KW8),--({1;2;3;")
    at = extras.rv_at("MATCH($B64,$A$5:$A$54,0)")
    assert at("ID:JA") == "INDEX($ID$5:$JA$54,MATCH($B64,$A$5:$A$54,0),0)" and at("CW") == "INDEX($CW$5:$CW$54,MATCH($B64,$A$5:$A$54,0))"
    # the running sum MMULT builds a floater's discount factors from: 24 places each way
    assert extras.RUNNING_SUM.count(";") == 23 and extras.RUNNING_SUM.count(",") == 23


def test_a_workbook_whose_formulas_differ_loads_without_the_ways_back():
    """A sheet whose formula a way back inverts written another way: that addition is left out (and said), the sheet and
    the other additions stay as they are."""
    import os
    from tto.xl.model import Model
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    asw = Model.load(os.path.join(root, "models", "asw.json.gz"))
    extras.SheetBuilder(asw, "ASW").patch("R9", '=IF($BB9,IFERROR(($O9-$P9)/$Q9*100,""),"")')
    # (the table two-way - test_kagit_twoway.py - inverts the same formula: left out as well)
    assert extras.apply("asw", asw) == ["ASW'den temiz fiyat: ASW!R9 beklenen formül değil (($P9-$O9)/$Q9*100 yok)",
                                        "DİBS ASW iki yönlü: ASW!R9 beklenen formül değil"]
    assert parse_a1("W9") not in asw.sheet("ASW").fml and "EK_FX" in asw.sheet_index
    assert extras.formula_of(asw, "ASW", "R9") == 'IF($BB9,IFERROR(($O9-$P9)/$Q9*100,""),"")' and parse_a1("D9") not in asw.sheet("ASW").fml
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    extras.SheetBuilder(tto, "DİBS RV").patch("EH20", '=IF(AND(DG20,OR(CR20="S",CR20="B")),(EG20-DH20)/EE20*100,"")')
    problems = extras.apply("tto", tto)
    assert [p.split(":")[0] for p in problems] == ["DİBS RV ASW / DM'den fiyat", "DİBS RV switch seviyesinden fiyat",
                                                   "DİBS RV iki yönlü", "DİBS RV switch iki yönlü"]
    assert problems[0].endswith("DİBS RV!EH20 beklenen formül değil ((EG20-DI20)/EE20*100 yok)")
    rv, man = tto.sheet("DİBS RV"), tto.sheet("Manuel Tahvil")
    assert parse_a1("BL20") not in rv.fml and parse_a1("V64") not in rv.fml and parse_a1("A78") not in rv.consts
    assert parse_a1("N20") not in rv.fml and extras.formula_of(tto, "DİBS RV", "S20") == 'IF(AND(DG20,CR20<>"T"),DX20,"")'
    assert parse_a1("AA64") not in rv.fml
    assert parse_a1("B7") in man.fml and parse_a1("AM18") in man.fml           # (Manuel Tahvil's ISIN does not read EH)
    assert "$AP$18" in extras.formula_of(tto, "Manuel Tahvil", "B14")            # (nor its two-way)
