"""Decimals the desk reads (the desk, 25.11.2026: "Forward fiyatlama kısımlarında try faizleri 4 decimal'i çok yoruyor
gözü. Bunları 2 decimala alalım. VİOP target kısmında da faiz seçtiğim durumda decimalsiz yazıyor."):

* the Forward page's pricing tables show their TRY rates with two decimals (``extras.TRY_PCT``): USDTRY / EURTRY FORWARD's
  TRY bid / mid / ask % and "Elle ayarı" mid, SERBEST FORWARD's minor %, TOPLU FORWARD's offshore / OIS / RET rates,
  Manuel TRY % and İma TRY %, ÇAPRAZ FORWARD's İma TRY %.  How they read only: the value ("v", what Ctrl+Shift+C copies),
  what is typed and every calculation keep every digit; the USD / EUR rates beside them keep theirs;
* VİOP Target's "Hedef değer" reads in the row's "Hedef tipi" - a rate with two decimals, a far price as the far limit
  reads (four), bp with one, typed or worked out - a number format chosen by another cell
  (``SheetBuilder.number_format_if``, drawn by ``Renderer.cell``); the desk strip (MASA!S121:S128) writes it the same way.

Every check compares with the values the sheet holds now (the session's shared service: no market literal pinned)."""
from __future__ import annotations

import os
import re

import pytest

from conftest import cell
from helpers import mini_book
from tto import extras as ex
from tto.books import remove_sheets
from tto.render import Renderer
from tto.xl import numfmt
from tto.xl.model import Model, parse_a1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TR = numfmt.get_locale("tr")
TWO = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}$")          # a number with two decimals, as the page writes it
FOUR = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{4}$")


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()])
    assert res["errors"] == [], res["errors"]


def typed(x: float) -> str:
    """A number as the desk types it (six decimals, the decimal comma)."""
    return ("%.6f" % x).replace(".", ",")


def rows_of(svc, user, view, panel):
    """{(row, column): the cell as the page draws it} of a table of a page."""
    data = next(p for p in svc.view(user, view)["panels"] if p["id"] == panel)["data"]
    return {(r, c): data["rows"][i][j] for i, r in enumerate(data["r"]) for j, c in enumerate(data["c"])}


def reads(got, ref, pattern):
    """The page's cell ``ref`` ("B47" of ``got``) as it reads (``pattern``: its decimals) - returned, to check its value."""
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    c = got[(int(m.group(2)), m.group(1))]
    assert pattern.match(c["t"]), (ref, c)
    return c


# ---------------------------------------------------------------------------------------------- the mechanism
def test_a_number_format_chosen_by_another_cell():
    """``number_format_if``: where its condition (written for the range's first cell) holds, the number reads in its format
    - the first rule that holds, in the order added; a cell no rule holds for reads in its own (General); a text, a blank
    and the value itself ("v") untouched."""
    cells = {"A1": "Faiz %", "B1": 45.0, "A2": "Fiyat", "B2": 51.05, "A3": "FRA+bp", "B3": -75.0, "A4": "Faiz %", "B4": "metin",
             "A5": "Faiz %", "A6": "Fiyat", "B6": -3.5, "A7": "x", "B7": 12.3456, "A8": "Faiz %", "B8": 45.123456789}
    book = mini_book(cells)
    b = ex.SheetBuilder(book.model, "S")
    b.number_format_if("B1:B8", '$A1="Faiz %"', "0.00")
    b.number_format_if("B1:B8", '$A1="Fiyat"', "#,##0.0000")
    b.number_format_if("B1:B8", "$B1<0", "0.0")
    t = Renderer(book).table(book.engine.shared, "S", "A1:B8", TR, None, trim=False)
    got = [(row[1].get("t"), row[1].get("v"), row[1].get("k")) for row in t["rows"]]
    assert got == [("45,00", 45.0, "n"), ("51,0500", 51.05, "n"), ("-75,0", -75.0, "n"), ("metin", None, "s"), ("", None, ""),
                   ("-3,5000", -3.5, "n"), ("12,3456", 12.3456, "n"), ("45,12", 45.123456789, "n")]
    # (the dashboard's own rules come after the workbook's, each with a style of its own)
    rules = book.model.sheets[0].cf
    assert [r["priority"] for r in rules] == [1, 2, 3] and [book.model.dxfs[r["dxf"]] for r in rules] == [
        {"fmt": "0.00"}, {"fmt": "#,##0.0000"}, {"fmt": "0.0"}]


# ---------------------------------------------------------------------------------------------- the Forward page
def test_usdtry_and_eurtry_forward_show_their_try_rates_with_two_decimals(service):
    """USDTRY / EURTRY FORWARD: every curve's TRY bid / mid / ask % with two decimals, its value every digit; the outrights,
    points and the USD / EUR rates of the value date as before (four decimals)."""
    u = service.login("ondalık fwd")["user"]
    for panel, rows, major in (("FR1", range(47, 52), 45), ("FR2", range(58, 63), 56)):
        got = rows_of(service, u, "forward", panel)
        digits = 0
        for r in rows:
            for c in "BCD":
                x = reads(got, "%s%d" % (c, r), TWO)
                assert x["v"] == cell(service, "EK_FWD!%s%d" % (c, r), u) and x["t"] == numfmt.format_value(x["v"], "0.00", TR)
                digits += x["v"] != round(x["v"], 2)
            for c in "EFG":
                reads(got, "%s%d" % (c, r), FOUR)                      # the outrights
        assert digits > 0                                                         # (the values keep their digits)
        for c in "HJL":
            reads(got, "%s%d" % (c, major), FOUR)                      # USD / EUR bid, mid, ask %: as they were


def test_a_try_rate_typed_keeps_every_digit(service):
    """A TRY rate typed with six decimals reads with two; the value, the outright worked out from it and "Elle ayarı"'s
    mid keep all six."""
    u = service.login("ondalık yazılan")["user"]
    try:
        put(service, u, {"EK_FWD!B47": "36,123456", "EK_FWD!D52": "35,654321"})
        got = rows_of(service, u, "forward", "FR1")
        b47 = reads(got, "B47", TWO)
        assert b47["t"] == "36,12" and b47["v"] == 36.123456 and b47["i"] == "u" and b47["m"] == 1
        spot, days, usd_ask = (cell(service, "EK_FWD!%s" % a, u) for a in ("F45", "D45", "L45"))
        assert cell(service, "EK_FWD!E47", u) == pytest.approx(spot * (1 + 36.123456 / 100 / 360 * days) / (1 + usd_ask / 100 / 360 * days),
                                                               rel=1e-15)
        d52 = reads(got, "D52", TWO)
        assert d52["t"] == "35,65" and d52["v"] == 35.654321
        assert cell(service, "EK_FWD!C51", u) == pytest.approx(35.654321, abs=1e-12)          # the Elle row's mid: the one typed
        reads(got, "C51", TWO)
    finally:
        service.reset_inputs(u, "tto")


def test_free_forward_bulk_and_cross_show_their_try_rates_with_two_decimals(service):
    """SERBEST FORWARD's minor % (its major % - USD / EUR - as before), TOPLU FORWARD's offshore / OIS / RET rates, Manuel
    TRY % (typed: every digit kept) and İma TRY % (its USD / EUR % as before), ÇAPRAZ FORWARD's İma TRY %."""
    u = service.login("ondalık toplu")["user"]
    try:
        put(service, u, {"EK_FWD!C68": "15.12.2026", "EK_BULK!B5": "15.01.2027", "EK_BULK!B6": "15.04.2027", "EK_BULK!L6": "36,1234",
                         "Forward!C197": "USD"})
        put(service, u, {"EK_BULK!R5": typed(cell(service, "EK_BULK!N5", u) + 0.0123456),
                         "Forward!R200": typed(cell(service, "Forward!I200", u) + 0.0123456)})
        free = rows_of(service, u, "forward", "FR3")
        reads(free, "G68", TWO)
        reads(free, "F68", FOUR)
        bulk = rows_of(service, u, "forward", "BK1")
        for c in "DEFGHS":
            x = reads(bulk, "%s5" % c, TWO)
            assert x["v"] == cell(service, "EK_BULK!%s5" % c, u)
        for c in "JK":
            assert re.match(r"^\d+,\d{3}$", bulk[(5, c)]["t"]), bulk[(5, c)]                # USD / EUR %: as they were
        l6 = reads(bulk, "L6", TWO)
        assert l6["t"] == "36,12" and l6["v"] == 36.1234
        cross = rows_of(service, u, "forward", "B36")
        s200 = reads(cross, "S200", TWO)
        assert s200["v"] == cell(service, "Forward!S200", u) and s200["v"] != round(s200["v"], 2)
    finally:
        service.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- VİOP Target
def test_the_viop_target_value_reads_in_its_type(service):
    """Hedef değer in the row's type: Faiz % a rate with two decimals (typed whole, or worked out from a rate typed in
    Hedef faiz), Fiyat the price with the far limit's four, FRA+bp / FXswap+bp bp with one (typed, or worked out from
    another member) - on the VİOP page and on Masa's VİOP TARGET; its value every digit.  The row's other members read as
    they did (a rate in %, prices with four decimals, bp whole); the type changed, the same value reads the new type's way.
    The desk strip says it alike."""
    u = service.login("ondalık hedef")["user"]
    rows = {331: ("Faiz %", "45", "45,00"), 332: ("Faiz %", "45,5", "45,50"), 333: ("Fiyat", "51,05", "51,0500"),
            334: ("FRA+bp", "-75", "-75,0"), 335: ("FXswap+bp", "40,5", "40,5")}
    try:
        for r, (kind, value, _) in rows.items():
            put(service, u, {"VIOP!L%d" % r: "Spot", "VIOP!M%d" % r: "31.12.2026", "VIOP!N%d" % r: "LONG", "VIOP!O%d" % r: kind,
                             "VIOP!P%d" % r: value})
        put(service, u, {"VIOP!L336": "Spot", "VIOP!M336": "31.12.2026", "VIOP!N336": "LONG", "VIOP!O336": "Faiz %",
                         "VIOP!Q336": "44,123456%"})
        page, masa = rows_of(service, u, "viop", "B33"), rows_of(service, u, "masa", "B17D")
        for r, (kind, value, text) in rows.items():
            v = float(value.replace(",", "."))
            for got in (page, masa):
                assert got[(r, "P")]["t"] == text and got[(r, "P")]["v"] == v, (r, got[(r, "P")])
            strip = "%s %s" % (kind, text)
            assert cell(service, "MASA!S%d" % (r - 210), u) == strip
        p336 = page[(336, "P")]
        assert p336["t"] == "44,12" and p336["v"] == pytest.approx(44.123456, abs=1e-12) and cell(service, "MASA!S126", u) == "Faiz % 44,12"
        for r in rows:
            assert re.match(r"^-?\d+,\d{2}%$", page[(r, "Q")]["t"]) and FOUR.match(page[(r, "S")]["t"]) and FOUR.match(page[(r, "T")]["t"])
            assert re.match(r"^-?\d{1,3}(\.\d{3})*$", page[(r, "V")]["t"]), page[(r, "V")]
        # a far price typed on a bp row: its bp worked out reads with one decimal (-1636,148629 -> -1636,1), the strip alike
        put(service, u, {"VIOP!S334": "51,2345"})
        p = cell(service, "VIOP!P334", u)
        one = numfmt.format_value(p, "0.0", TR)
        p334 = rows_of(service, u, "viop", "B33")[(334, "P")]
        assert re.match(r"^-?\d+,\d$", one) and p334["t"] == one and p334["v"] == p and p != round(p, 1)
        assert cell(service, "MASA!S124", u) == "FRA+bp " + one
        # the type changed: the same far price reads as a price, then as a rate
        for kind, want in (("Fiyat", "51,2345"), ("Faiz %", numfmt.format_value(cell(service, "VIOP!Q334", u) * 100, "0.00", TR))):
            put(service, u, {"VIOP!O334": kind})
            assert rows_of(service, u, "viop", "B33")[(334, "P")]["t"] == want, kind
    finally:
        service.reset_inputs(u, "tto")


def test_the_formats_by_type_go_with_the_target_table():
    """The guard: a workbook whose target table is not what the two-way builds on (a caption of its own) keeps Hedef değer
    in its cell's own format and the strip as the FRA's curve leaves it - nothing chosen by the type, the rest loads."""
    tto = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", tto)
    tto.sheet("VIOP").consts[parse_a1("V330")] = "Hedef − piyasa"
    left = ex.apply("tto", tto)
    assert left == [ex.VT_NAME + ": VIOP!V330 beklenen başlık değil (Hedef − piyasa (bp) yok)"], left
    sh = tto.sheet("VIOP")
    assert not [x for x in sh.cf if x["sqref"].startswith("P331")] and ex._numfmt(tto, "VIOP", "P331") == "General"
    assert "TEXT(" not in ex.formula_of(tto, "MASA", "S121") and 'VIOP!$O$331&" "&VIOP!$P$331' in ex.formula_of(tto, "MASA", "S121")
    tto = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))                   # the file as it is: the three rules there
    remove_sheets("tto", tto)
    assert ex.apply("tto", tto) == []
    rules = [x for x in tto.sheet("VIOP").cf if x["sqref"] == "P331:P338"]
    assert [tto.dxfs[x["dxf"]]["fmt"] for x in rules] == [ex.TRY_PCT, ex._numfmt(tto, "VIOP", "S331"), "0.0"]
