"""Masa → Faiz · PPK → TOPLU TARİH ARASI FAİZ (``tto/extras.py``, sheet EK_TARIH): the desk sheet's date-to-date block
(MASA!B59:N70) for up to 100 start / end pairs at once - each curve's period rate (ACT/360 by default; ACT/365 or O/N
when chosen) and the chosen curve's ACT/360 rate + spread, with the block's own formulas carried to each row.

Every check compares a row with the block itself: the block's dates and spread set to the row's, its cells read.

The other way round (the desk, 24.11.2026, item 1 of "1-2-3-4-5-6-7-8-11-11-13"): a quote typed -> its spread over the
curves - a row's "Kote %" in the table's basis over the chosen curve and Bootstrap, and the block's own box (TARİH ARASI
FAİZ → SPREAD) over each of its curves; the spread found, typed back as the spread, gives the quote (1e-9)."""
import datetime as dt
import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.views import load_views
from tto.xl.model import Model, parse_a1
from tto.xl.values import serial_to_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODES = [code for code, _ in ex.TARIH_CURVES]
MASA_ROW = dict(ex.TARIH_CURVES)                          # a curve's row of the block (62 … 68)
BASIS_COL = {"ACT/360": "D", "ACT/365": "C", "O/N (360)": "E"}
#: start, end and spread (bp; "" = the general one) of the pairs typed below, on rows far apart (row 60 / 63 / 65: the
#: block's own row numbers - a row's cells must not be taken for the block's)
PAIRS = {5: ("15.12.2026", "15.03.2027", "-100"), 6: ("04.01.2027", "05.07.2027", ""), 60: ("10.12.2026", "21.01.2027", "35"),
         63: ("30.06.2027", "30.06.2028", "0"), 65: ("04.11.2026", "04.11.2031", "-150"), 104: ("01.03.2027", "02.03.2027", "12")}
#: scenario steps (bp) at the first meeting (10.12.2026), so that S1, S2 and S3 differ
STEPS = {"OIS_MAIN!U10": "-50", "OIS_MAIN!V10": "100", "OIS_MAIN!W10": "-250"}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def typed(pairs):
    out = {}
    for r, (start, end, spread) in pairs.items():
        out.update({"EK_TARIH!B%d" % r: start, "EK_TARIH!C%d" % r: end, "EK_TARIH!D%d" % r: spread})
    return out


def block(svc, user, start, end, spread):
    """The block's numbers for these dates and this spread: {(column, row): value}."""
    put(svc, user, {"MASA!C60": start, "MASA!E60": end, "MASA!I60": spread})
    out = {(c, k): cell(svc, "MASA!%s%d" % (c, k), user) for c in "CDEF" for k in range(62, 69)}
    out[("G", 60)] = cell(svc, "MASA!G60", user)
    return out


def row(svc, user, r):
    return {c: cell(svc, "EK_TARIH!%s%d" % (c, r), user) for c in "BCDEFGHIJKLM"}


# ============================================================================== the block, row by row
def test_each_row_gives_the_blocks_numbers_for_its_dates_and_spread(svc):
    """Six pairs, from a day to five years, with their own spread: each row's days, every curve's rate in the three bases
    and each curve's rate + spread are the block's for the same start, end and spread (to the last bit)."""
    u = svc.login("Toplu faiz blok")["user"]
    try:
        put(svc, u, dict(STEPS, **typed(PAIRS)))
        for r, (start, end, spread) in PAIRS.items():
            want = block(svc, u, start, end, spread)
            got = row(svc, u, r)
            assert got["E"] == want[("G", 60)] > 0, r
            for basis, col in BASIS_COL.items():
                put(svc, u, {"EK_TARIH!" + ex.TARIH_BASIS: basis})
                for i, code in enumerate(CODES):
                    x = cell(svc, "EK_TARIH!%s%d" % (ex.TARIH_RATES[i], r), u)
                    assert isinstance(x, float) and x == pytest.approx(want[(col, MASA_ROW[code])], abs=1e-12), (r, basis, code)
            for code in CODES:
                put(svc, u, {"EK_TARIH!" + ex.TARIH_CURVE: code})
                assert cell(svc, "EK_TARIH!M%d" % r, u) == pytest.approx(want[("F", MASA_ROW[code])], abs=1e-12), (r, code)
            put(svc, u, {"EK_TARIH!" + ex.TARIH_BASIS: "", "EK_TARIH!" + ex.TARIH_CURVE: ""})
        # the curves differ (a row is no copy of one curve) and the spread is added in bp
        put(svc, u, {"MASA!I60": ""})
        five = row(svc, u, 5)
        assert len({round(five[c], 10) for c in "FGHIJKL"}) == 7
        assert five["I"] < five["G"] < five["H"]                                       # S3 −250, S1 −50, S2 +100 bp
        assert five["M"] == pytest.approx(five["F"] - 0.01, abs=1e-12)                 # MPC ima − 100 bp
    finally:
        svc.reset_inputs(u, "tto")


def test_the_columns_are_named_as_the_block_names_its_curves(svc):
    u = svc.login("Toplu faiz başlık")["user"]
    try:
        head = [cell(svc, "EK_TARIH!%s4" % c, u) for c in "BCDEFGHIJKLM"]
        assert head[:4] == ["Başlangıç", "Bitiş", "Spread (bp)", "Gün"]
        assert head[4:11] == [cell(svc, "MASA!B%d" % k, u) for k in range(62, 69)]
        assert head[5] == "S1 – " + cell(svc, "OIS_MAIN!P3", u) and head[11] == "MPC ima + spread (360)"
        put(svc, u, {"EK_TARIH!C2": "s2", "OIS_MAIN!P4": "Şahin"})                    # (the list's item, whatever the case)
        assert cell(svc, "EK_TARIH!C2", u) == "S2" and cell(svc, "EK_TARIH!M4", u) == "S2 – Şahin + spread (360)"
        assert svc.cell_info(u, "tto", "EK_TARIH!C2")["cell"]["o"] == CODES
        assert svc.cell_info(u, "tto", "EK_TARIH!E2")["cell"]["o"] == list(ex.TARIH_BASES)
        assert "listede yok" in svc.set_inputs(u, "tto", [{"ref": "EK_TARIH!E2", "value": "30/360"}])["errors"][0]
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== what a row takes when left blank
def test_a_blank_start_is_the_ois_spot_and_a_blank_spread_the_general_one(svc):
    """An end alone: the row starts at the OIS spot (the block's own default) and takes the general spread at the top -
    the desk's one OIS spread (MASA!I60) until one is typed there.  A row's own start or spread wins; Delete brings the
    default back."""
    u = svc.login("Toplu faiz varsayılan")["user"]
    try:
        spot = cell(svc, "OIS_MAIN!B2", u)
        put(svc, u, {"EK_TARIH!C5": "15.03.2027", "EK_TARIH!B6": "15.12.2026", "EK_TARIH!C6": "15.03.2027", "EK_TARIH!D6": "-80"})
        assert cell(svc, "EK_TARIH!B5", u) == spot and cell(svc, "EK_TARIH!E5", u) == cell(svc, "EK_TARIH!C5", u) - spot
        assert cell(svc, "EK_TARIH!G2", u) == cell(svc, "MASA!I60", u) == cell(svc, "EK_TARIH!D5", u) == -150.0
        want = block(svc, u, serial_to_date(spot).strftime("%d.%m.%Y"), "15.03.2027", "")
        assert cell(svc, "EK_TARIH!F5", u) == pytest.approx(want[("D", 62)], abs=1e-12)
        put(svc, u, {"MASA!I60": "-120"})                                             # the desk's spread moves: the row follows
        assert cell(svc, "EK_TARIH!D5", u) == -120.0 and cell(svc, "EK_TARIH!D6", u) == -80.0
        assert cell(svc, "EK_TARIH!M5", u) == pytest.approx(cell(svc, "MASA!F62", u), abs=1e-12)
        put(svc, u, {"EK_TARIH!G2": "-60"})                                           # a general spread of one's own
        assert cell(svc, "EK_TARIH!D5", u) == -60.0 and cell(svc, "EK_TARIH!D6", u) == -80.0
        assert cell(svc, "EK_TARIH!M5", u) == pytest.approx(cell(svc, "EK_TARIH!F5", u) - 0.006, abs=1e-12)
        put(svc, u, {"EK_TARIH!G2": "", "EK_TARIH!D6": "", "EK_TARIH!B6": ""})        # Delete: the defaults again
        assert cell(svc, "EK_TARIH!G2", u) == cell(svc, "EK_TARIH!D6", u) == -120.0 and cell(svc, "EK_TARIH!B6", u) == spot
        assert svc.store.user_inputs(u, "tto").keys() >= {("tto", "EK_TARIH!C5"), ("tto", "EK_TARIH!C6")}
        assert ("tto", "EK_TARIH!G2") not in svc.store.user_inputs(u, "tto")
    finally:
        svc.reset_inputs(u, "tto")


def test_rows_start_empty_and_an_unfinished_row_shows_nothing(svc):
    """Nobody's dates to start with: every row, the helpers too, is empty (no 0 % in Ağırlıklı); a start without its end
    shows nothing either."""
    u = svc.login("Toplu faiz boş")["user"]
    lay = ex._tarih_layout()
    helpers = (lay["ks"], lay["ke"], lay[("df", "MPC ima", 0)], lay[("d", "MPC ima")], lay[("d", "Ağırlıklı")], lay[("f", "Ağırlıklı")])
    try:
        for r in (ex.TARIH_FIRST, 50, ex.TARIH_LAST):
            assert set(row(svc, u, r).values()) <= {"", None}, r                       # (the end: an input with nothing in it)
            assert {cell(svc, "EK_TARIH!%s%d" % (c, r), u) for c in helpers + ex.TARIH_VS} == {""}
            assert cell(svc, "EK_TARIH!%s%d" % (ex.TARIH_QUOTE, r), u) is None         # (the quote: nobody's, to start with)
        put(svc, u, {"EK_TARIH!B7": "15.12.2026"})
        got = row(svc, u, 7)
        assert isinstance(got["B"], float) and {got[c] for c in "CDEFGHIJKLM"} <= {"", None}
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== how rows are typed
def test_rows_pasted_from_excel_and_dates_typed_as_tenors(svc):
    """A block copied in Excel - start | end | spread, an empty spread cell among them - lands as typed; an end typed as
    a tenor counts from the row's start on the TRY calendar (OIS: the TRY list, as the block's own end default)."""
    u = svc.login("Toplu faiz yapıştır")["user"]
    try:
        res = put(svc, u, {"EK_TARIH!B5": "15.12.2026", "EK_TARIH!C5": "15.03.2027", "EK_TARIH!D5": "-100",
                           "EK_TARIH!B6": "04.01.2027", "EK_TARIH!C6": "05.07.2027", "EK_TARIH!D6": "",
                           "EK_TARIH!B7": "15.12.2026", "EK_TARIH!C7": "3A"})
        assert [cell(svc, "EK_TARIH!D%d" % r, u) for r in (5, 6)] == [-100.0, -150.0]
        assert serial_to_date(cell(svc, "EK_TARIH!C5", u)) == dt.date(2027, 3, 15)
        end = serial_to_date(cell(svc, "EK_TARIH!C7", u))
        assert res["shortcuts"]["EK_TARIH!C7"]["typed"] == "3A" and dt.date(2027, 3, 15) <= end <= dt.date(2027, 3, 19)
        assert end.weekday() < 5
        assert cell(svc, "EK_TARIH!E7", u) == float((end - dt.date(2026, 12, 15)).days)
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== the curve setting
def test_the_rows_follow_the_viewers_curve_setting_as_the_block_does(svc):
    """The block's Bootstrap row reads Motor's nodes, which a PPK basamak user's setting moves: the rows follow it as the
    block does, and a Bootstrap user's stay the market's."""
    ppk, boot = svc.login("Toplu faiz PPK")["user"], svc.login("Toplu faiz Boot")["user"]
    svc.set_interp(ppk, "ppk")
    try:
        pair = {5: ("04.11.2026", "04.05.2028", "0")}                                 # 18M: between two quotes
        got = {}
        for u in (ppk, boot):
            put(svc, u, typed(pair))
            want = block(svc, u, *pair[5])
            got[u] = cell(svc, "EK_TARIH!K5", u)                                       # Bootstrap
            assert got[u] == pytest.approx(want[("D", 67)], abs=1e-12)
            assert cell(svc, "EK_TARIH!F5", u) == pytest.approx(want[("D", 62)], abs=1e-12)
            # a quote's spread over Bootstrap follows too: the row's and the block's box (each over the viewer's curve)
            put(svc, u, {"EK_TARIH!N5": "38", "EK_TARIH!" + ex.TARIH_BACK_QUOTE: "38"})
            assert cell(svc, "EK_TARIH!P5", u) == pytest.approx((0.38 - got[u]) * 10000, abs=1e-9)
            assert cell(svc, "EK_TARIH!H%d" % (ex.TARIH_BACK + 4), u) == pytest.approx((0.38 - want[("D", 67)]) * 10000, abs=1e-9)
        assert abs(got[ppk] - got[boot]) > 1e-6
    finally:
        svc.set_interp(ppk, "bootstrap")
        svc.reset_inputs(ppk, "tto")
        svc.reset_inputs(boot, "tto")


# ============================================================================== the other way round: a quote -> its spread
def test_a_quote_for_the_blocks_dates_reads_its_spread_over_each_curve(svc):
    """(the desk, 24.11.2026, item 1: "type the rate someone quotes for a broken date and see its spread over each curve")
    The block's box: a quote typed for the block's dates - ACT/360 simple, as the block adds its spread - less each
    curve's period rate (MASA!D62:D68) is its spread over that curve; typed into the block's spread (MASA!I60) it makes
    that curve's "Dönem + spread (360)" the quote (1e-9), every curve, three months and five years."""
    u = svc.login("Tarih arası kote")["user"]
    t = ex.TARIH_BACK
    quote = "EK_TARIH!" + ex.TARIH_BACK_QUOTE
    try:
        put(svc, u, STEPS)
        for start, end, typed_q, q in (("15.12.2026", "15.03.2027", "38,5", 0.385), ("04.11.2026", "04.11.2031", "%31,25", 0.3125)):
            put(svc, u, {"MASA!C60": start, "MASA!E60": end, "MASA!I60": "", quote: typed_q})
            assert cell(svc, quote, u) == pytest.approx(q, abs=1e-15)
            # the box shows the block's dates, days and curves
            assert [cell(svc, "EK_TARIH!%s%d" % (c, t + 1), u) for c in "EGI"] == [cell(svc, "MASA!%s60" % c, u) for c in "CEG"]
            spreads = {}
            for i, (code, k) in enumerate(ex.TARIH_CURVES):
                col = chr(ord("C") + i)
                assert cell(svc, "EK_TARIH!%s%d" % (col, t + 2), u) == cell(svc, "MASA!B%d" % k, u), code
                d = cell(svc, "MASA!D%d" % k, u)
                assert isinstance(d, float) and cell(svc, "EK_TARIH!%s%d" % (col, t + 3), u) == d
                spreads[k] = cell(svc, "EK_TARIH!%s%d" % (col, t + 4), u)
                assert spreads[k] == pytest.approx((q - d) * 10000, abs=1e-9), code
            assert len({round(s, 6) for s in spreads.values()}) == 7                      # (seven curves, seven spreads)
            for k, s in spreads.items():                                                 # the spread typed back: the quote
                put(svc, u, {"MASA!I60": s})
                assert cell(svc, "MASA!F%d" % k, u) == pytest.approx(q, abs=1e-9), k
        # no quote, or a text: no spread
        for typed_q in ("", "yok"):
            put(svc, u, {quote: typed_q})
            assert {cell(svc, "EK_TARIH!%s%d" % (chr(ord("C") + i), t + 4), u) for i in range(7)} == {""}
    finally:
        svc.reset_inputs(u, "tto")


def test_a_rows_quote_reads_its_spread_over_the_chosen_curve_and_bootstrap(svc):
    """(item 1, the bulk table) A row's "Kote %", read in the table's basis, less the chosen curve's and Bootstrap's rate as
    the row shows them: rate + spread = the quote in each basis, whichever curve is chosen; with ACT/360 the chosen
    curve's spread typed as the row's spread makes its "+ spread (360)" the quote (1e-9).  The columns say the basis and
    the curves; a row without its dates shows nothing."""
    u = svc.login("Toplu faiz kote")["user"]
    pairs = {r: PAIRS[r] for r in (5, 60, 104)}
    quotes = {5: ("38,5", 0.385), 60: ("41,25", 0.4125), 104: ("%35", 0.35)}
    boot = ex.TARIH_RATES[CODES.index("Bootstrap")]
    try:
        put(svc, u, dict(STEPS, **typed(pairs), **{"EK_TARIH!N%d" % r: text for r, (text, _) in quotes.items()},
                         **{"EK_TARIH!N7": "40"}))                                          # (a quote without dates)
        for basis in ex.TARIH_BASES:
            put(svc, u, {"EK_TARIH!" + ex.TARIH_BASIS: basis})
            assert cell(svc, "EK_TARIH!N4", u) == "Kote %% (%s)" % basis
            for i, code in enumerate(CODES):
                put(svc, u, {"EK_TARIH!" + ex.TARIH_CURVE: code})
                assert cell(svc, "EK_TARIH!O4", u) == "Kote − %s (bp)" % cell(svc, "EK_TARIH!%s4" % ex.TARIH_RATES[i], u)
                for r, (_, q) in quotes.items():
                    assert cell(svc, "EK_TARIH!N%d" % r, u) == pytest.approx(q, abs=1e-15)
                    shown, s = cell(svc, "EK_TARIH!%s%d" % (ex.TARIH_RATES[i], r), u), cell(svc, "EK_TARIH!O%d" % r, u)
                    assert isinstance(shown, float) and s == pytest.approx((q - shown) * 10000, abs=1e-9), (basis, code, r)
                    assert shown + s / 10000 == pytest.approx(q, abs=1e-9)
                    b = cell(svc, "EK_TARIH!%s%d" % (boot, r), u)
                    assert cell(svc, "EK_TARIH!P%d" % r, u) == pytest.approx((q - b) * 10000, abs=1e-9)
                assert cell(svc, "EK_TARIH!O7", u) == cell(svc, "EK_TARIH!P7", u) == ""
        assert cell(svc, "EK_TARIH!P4", u) == "Kote − Bootstrap (bp)"
        # ACT/360: the chosen curve's spread, typed as the row's spread, gives back the quote in "+ spread (360)"
        put(svc, u, {"EK_TARIH!" + ex.TARIH_BASIS: "ACT/360"})
        for code in CODES:
            put(svc, u, {"EK_TARIH!" + ex.TARIH_CURVE: code})
            spreads = {r: cell(svc, "EK_TARIH!O%d" % r, u) for r in quotes}
            put(svc, u, {"EK_TARIH!D%d" % r: s for r, s in spreads.items()})
            for r, (_, q) in quotes.items():
                assert cell(svc, "EK_TARIH!%s%d" % (ex.TARIH_PLUS, r), u) == pytest.approx(q, abs=1e-9), (code, r)
                assert cell(svc, "EK_TARIH!O%d" % r, u) == spreads[r]                       # (the spread does not read it)
            put(svc, u, {"EK_TARIH!D%d" % r: "" for r in quotes})
        # a column of quotes pasted from Excel lands row by row; Delete empties a row's spreads
        res = svc.set_inputs(u, "tto", [{"ref": "EK_TARIH!N%d" % r, "value": v} for r, v in ((5, "37,25"), (6, "36"), (60, "0,39"))],
                             lenient=True)
        assert res["errors"] == [] and [cell(svc, "EK_TARIH!N%d" % r, u) for r in (5, 6, 60)] == pytest.approx([0.3725, 0.36, 0.39])
        put(svc, u, {"EK_TARIH!N5": ""})
        assert cell(svc, "EK_TARIH!O5", u) == cell(svc, "EK_TARIH!P5", u) == ""
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== the page
def test_the_table_sits_right_after_the_blocks_on_the_desk_page(svc):
    masa = next(v for v in load_views() if v["id"] == "masa")
    rates = next(s for s in masa["sections"] if s["id"] == "rates")
    assert rates["panels"][:3] == ["B9", "TAFS", "TAF"]                       # the block, its box (a quote's spreads), the table
    panels = {p["id"]: p for p in masa["panels"]}
    assert panels["TAF"]["sheet"] == ex.TARIH_SHEET and panels["TAF"]["range"] == "B1:P108" and not panels["TAF"]["hidden"]
    assert panels["TAF"]["grow"] == {"key": "B", "first": 5, "extra": 1, "last": 104}
    assert panels["TAFH"]["hidden"] and panels["TAFH"]["range"] == "R1:%s104" % ex.TARIH_TW       # (+ the two-way store)
    assert panels["TAFS"]["sheet"] == ex.TARIH_SHEET and panels["TAFS"]["range"] == "B%d:I%d" % (ex.TARIH_BACK, ex.TARIH_BACK + 5)
    assert not panels["TAFS"]["hidden"]
    inputs = {i["range"]: (i["scope"], i["kind"]) for i in masa["inputs"] if i["range"].startswith("EK_TARIH!")}
    assert inputs == {"EK_TARIH!C2": ("user", "list"), "EK_TARIH!E2": ("user", "list"), "EK_TARIH!G2": ("user", "number"),
                      "EK_TARIH!B5:B104": ("user", "date"), "EK_TARIH!C5:C104": ("user", "date"),
                      "EK_TARIH!D5:D104": ("user", "number"), "EK_TARIH!N5:N104": ("user", "pct"),
                      "EK_TARIH!" + ex.TARIH_BACK_QUOTE: ("user", "pct")}
    u = svc.login("Toplu faiz sayfa")["user"]
    try:
        put(svc, u, dict(typed({5: PAIRS[5]}), **{"EK_TARIH!N5": "38,5", "EK_TARIH!" + ex.TARIH_BACK_QUOTE: "38,5"}))
        page = svc.view(u, "masa")
        table = next(p for p in page["panels"] if p["id"] == "TAF")
        data = table["data"]
        assert table["title"].startswith("TOPLU TARİH ARASI FAİZ") and table["grow"]["key"] == "B"
        assert data["c"] == list("BCDEFGHIJKLMNOP") and data["r"][-1] == 108
        cells = dict(zip(data["c"], data["rows"][data["r"].index(5)]))
        assert [cells[c].get("i") for c in "BCDN"] == ["u"] * 4 and not {"i"} & (set(cells["E"]) | set(cells["O"]) | set(cells["P"]))
        assert cells["B"]["t"] == "15.12.2026" and cells["F"]["t"].endswith("%") and cells["N"]["t"] == "38,50%"
        head = dict(zip(data["c"], data["rows"][data["r"].index(4)]))
        assert [head[c]["t"] for c in "NOP"] == ["Kote % (ACT/360)", "Kote − MPC ima (bp)", "Kote − Bootstrap (bp)"]
        box = next(p for p in page["panels"] if p["id"] == "TAFS")
        assert box["title"].startswith("TARİH ARASI FAİZ → SPREAD")
        rows = dict(zip(box["data"]["r"], box["data"]["rows"]))
        strip = dict(zip(box["data"]["c"], rows[ex.TARIH_BACK + 1]))
        assert strip["B"]["t"] == "Kote % (ACT/360)" and strip["C"].get("i") == "u" and strip["C"]["t"] == "38,50%"
        assert [c["t"] for c in rows[ex.TARIH_BACK + 2]] == ["Eğri"] + [cell(svc, "MASA!B%d" % k, u) for _, k in ex.TARIH_CURVES]
        assert all(c["t"] for c in rows[ex.TARIH_BACK + 4])                                  # a spread over every curve
        assert next(s for s in page["sections"] if s["id"] == "rates")["panels"][:3] == ["B9", "TAFS", "TAF"]
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== the workbook it is built on
def test_left_out_when_the_block_is_not_what_it_reads():
    """The rows reuse the block's formulas: a block written otherwise leaves the table out, the rest of the dashboard
    stays."""
    path = os.path.join(ROOT, "models", "tto.json.gz")
    tto = Model.load(path)
    ex.SheetBuilder(tto, "MASA").patch("D64", '=IFERROR((H64/I63-1)*360/$G$60,"")')         # S2's rate off S1's DF
    # (the block's two-way cells - an addition of their own - invert the block's formulas: left out too)
    assert ex.apply("tto", tto) == ["EK_TARIH: MASA!D64 beklenen formül değil (H64/I64 yok)",
                                    'TARİH ARASI iki yönlü: MASA!D64 beklenen formül değil (IFERROR((H64/I64-1)*360/$G$60,"") değil)']
    assert ex.TARIH_SHEET not in tto.sheet_index and "EK_VFRA" in tto.sheet_index
    tto = Model.load(path)                                                                  # a DF that reads another cell
    ex.SheetBuilder(tto, "MASA").patch("H62", "=" + ex.formula_of(tto, "MASA", "H62") + "*$I$60/$I$60")
    assert ex.apply("tto", tto) == ["EK_TARIH: unqualified references left in a transplanted formula: $I$60",
                                    "TARİH ARASI iki yönlü: MASA!H62 bloğun spread'ini okuyor ($I$60)"]
    tto = Model.load(path)
    ex.SheetBuilder(tto, "MASA").patch("F65", '=IFERROR(D65+$I$61/10000,"")')               # another spread
    assert ex.apply("tto", tto) == ["EK_TARIH: MASA!F65 beklenen formül değil (D65+$I$60/10000 yok)",
                                    'TARİH ARASI iki yönlü: MASA!F65 beklenen formül değil (IFERROR(D65+$I$60/10000,"") değil)']
    tto = Model.load(path)
    tto.sheet("MASA").consts[parse_a1("D61")] = "ACT/360"
    assert ex.apply("tto", tto) == ["EK_TARIH: MASA!D61 beklenen başlık değil (Dönem ACT/360 yok)"]
