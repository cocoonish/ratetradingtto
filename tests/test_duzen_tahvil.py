"""Düzen (27.11.2026): the bond pages, Hesaplayıcılar and Motor laid out for the desk's flow - "Panellerin boyutlarindan da
bazi sorunlar yasiyorum ... hem akisi kolaylastirmak hem de gorsel duzen icin" - with nothing of what they compute changed.

The panel the trader acts on first comes first (DİBS Trading's trades of the day above Valörler; Manuel Tahvil's ISIN and
"Hedef → temiz fiyat"); the identifier columns stay in view when a wide table scrolls (``"freeze"``); the rows without a bond
or a period are folded (``"grow"``: the rows in use and one more); Hazine İhalesi's typed realized nominal is in view;
Eurobond Kotaları's empty row no longer prints "#N/A Invalid Security"; Hesaplayıcılar in three tabs (Faiz / FX · vol /
Tahvil) with Ana girdiler's rows named and read alike; Motor's panels open; DİBS RV's two helper columns hidden until a user
shows them.  (The pages drawn in the browser: tests/e2e/e2e.js, the duzenTahvil checks.)"""
from __future__ import annotations

import re

import pytest

from conftest import cell
from tto import extras as ex
from tto.store import user_key
from tto.views import load_views

VIEWS = {v["id"]: v for v in load_views()}


def panel(view, pid):
    return next(p for p in VIEWS[view]["panels"] if p["id"] == pid)


def shown(view):
    return [p["id"] for p in VIEWS[view]["panels"] if not p.get("hidden")]


def page_panel(svc, user, view, pid):
    return next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)


def texts(data, col):
    j = data["c"].index(col)
    return {r: row[j].get("t", "") for r, row in zip(data["r"], data["rows"])}


# ------------------------------------------------------------------------------------------------ the panel acted on first
def test_the_panel_the_desk_acts_on_comes_first():
    # DİBS Trading: the summary, then today's trades, then the value dates' table
    assert shown("dibslive") == ["L0", "L3", "L1"]
    # Manuel Tahvil: the ISIN (the page's first input, a strip of its own) and the target → clean price first; the results;
    # the other inputs (filled from the ISIN), the period table and the notes after them
    assert shown("manuel") == ["B2i", "B5", "B3", "B4", "B4D", "B2", "B7", "B8", "B1"]
    isin, inputs = panel("manuel", "B2i"), panel("manuel", "B2")
    assert (isin["range"], isin["title"], inputs["range"]) == ("A17:C17", "ISIN", "A2:C16")
    assert "DİBS RV" in isin["note"] and "Tüm Kâğıtlar" in isin["note"] and "Hedef → temiz fiyat" in isin["note"]
    assert {i["range"] for i in VIEWS["manuel"]["inputs"]} >= {"B17", "B14", "I10", "I11", "I12"}
    # DİBS RV: the strip of inputs (DV01 per leg) beside the curve read-outs, each at its natural width
    assert shown("dibs")[:5] == ["B1", "B3D", "B2", "B2b", "B3"]
    assert all(panel("dibs", pid).get("fit") for pid in ("B3D", "B2", "B2b"))
    assert panel("kagitlar", "U1D").get("fit") and panel("manuel", "B4D").get("fit")


def test_manuels_isin_strip_takes_the_isin_as_before(service):
    u = service.login("Düzen Manuel")["user"]
    strip = page_panel(service, u, "manuel", "B2i")
    data = strip["data"]
    assert strip["title"] == "ISIN" and data["r"] == [17] and [c.get("t") for c in data["rows"][0]][0] == "ISIN"
    assert data["rows"][0][1].get("i") == "u"                                    # B17: typed here, as in Girdiler before
    inputs = page_panel(service, u, "manuel", "B2")["data"]
    assert inputs["r"][-1] == 16 and 17 not in inputs["r"]
    service.set_inputs(u, "tto", [{"ref": "Manuel Tahvil!B17", "value": "TRT150328T24"}])
    try:
        assert cell(service, "Manuel Tahvil!B17", user_key(u)) == "TRT150328T24"
        # the bond's maturity comes into Girdiler from the ISIN typed in the strip
        assert texts(page_panel(service, u, "manuel", "B2")["data"], "B")[7] == "15.03.2028"
    finally:
        service.reset_inputs(u, "tto", ["Manuel Tahvil!B17"])


# ------------------------------------------------------------------------------------------------ frozen identifier columns
@pytest.mark.parametrize("view, pid, n, first", [
    ("dibs", "B3", 2, ["ISIN", "Kaynak (boş = genel)"]),             # the name ("TURKIYE GOVERNMENT BOND") scrolls
    ("asw", "tbl", 1, ["ISIN"]),
    ("bulk", "B1", 2, ["ISIN", "Description"]),
    ("dibslive", "L0", 2, ["★", "Kâğıt"]),
])
def test_the_identifier_columns_are_frozen(service, view, pid, n, first):
    """``"freeze": n`` (duzen-cekirdek's mechanism) names the columns that identify a row: the first n columns the table
    shows are those."""
    assert panel(view, pid)["freeze"] == n
    data = page_panel(service, None, view, pid)["data"]
    head = next(row for row in data["rows"] if [c.get("t") for c in row[:n]] == first)
    assert len(head) > n


# ------------------------------------------------------------------------------------------------ rows without a bond folded
def test_rows_without_a_bond_or_a_period_are_folded():
    """The rows in use and one more (``"grow"``, view.js): "+ Satır" opens another, "Tümü" all of them - the cells all stay
    where they are (an ISIN is still typed into the row after the last bond)."""
    assert panel("dibs", "B3")["grow"] == {"key": "A", "first": 5, "extra": 1, "last": 54}
    assert panel("dibs", "B4")["grow"] == {"key": "A", "first": 64, "extra": 1, "last": 75}
    assert panel("manuel", "B7")["grow"] == {"key": "B", "first": 24, "extra": 1, "last": 63}
    # (the rows of the lists are the ones their inputs are declared on)
    inputs = {i["range"] for i in VIEWS["dibs"]["inputs"]}
    assert {"A5:A54", "A64:A75"} <= inputs and "B24:C63" in {i["range"] for i in VIEWS["manuel"]["inputs"]}


def test_the_page_sends_every_row_and_how_to_fold_them(service):
    b3 = page_panel(service, None, "dibs", "B3")
    assert b3["grow"]["key"] == "A" and set(range(5, 55)) <= set(b3["data"]["r"])
    filled = [r for r, t in texts(b3["data"], "A").items() if 5 <= r <= 54 and t.strip()]
    assert filled and max(filled) < 54                       # the trading list leaves rows below it: folded on the page
    b7 = page_panel(service, None, "manuel", "B7")
    periods = [r for r, t in texts(b7["data"], "B").items() if 24 <= r <= 63 and t.strip()]
    assert b7["grow"]["key"] == "B" and periods and max(periods) < 63


# ------------------------------------------------------------------------------------------------ Hazine İhalesi
def test_the_auctions_typed_realized_nominal_is_beside_the_bids_result(service):
    for pid in ("H1", "H2", "H3"):
        assert panel("ihale", pid)["cols"] == ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "P", "Q", "M", "N", "O"]
    data = page_panel(service, None, "ihale", "H1")["data"]
    assert data["c"][11:14] == ["L", "P", "Q"] and data.get("fz") == 1
    head = next(row for row in data["rows"] if row[0].get("t") == "#")
    assert [c.get("t") for c in head[11:14]] == ["Sonuç", "Gerçekleşen nom. (yaz)", "Gerçekleşen nominal"]
    typed = {r for r, row in zip(data["r"], data["rows"]) if row[12].get("i")}
    assert typed == set(range(10, 15))                       # P10:P14, the column typed after the auction


# ------------------------------------------------------------------------------------------------ Eurobond Kotaları
def test_eurobonds_empty_row_prints_no_bloomberg_error(service):
    """The row under the list - shown to type a new ISIN into - asked Bloomberg for a security of no ISIN and printed
    "#N/A Invalid Security" in every cell (12 dealer columns ~131 px wide): the workbook's own rows ask nothing while
    their ISIN is empty, as the rows the dashboard added below them; a row with an ISIN reads as before."""
    model = service.books["tto"].model
    for r in range(3, 7):
        for col in ex.BULK_BOND_ASKS:
            assert ex.formula_of(model, "Bulk Bond", "%s%d" % (col, r)).startswith('IF(TRIM($A%d&"")="","",_xll.BDP(' % r)
    data = page_panel(service, None, "bulk", "B1")["data"]
    assert not any("Invalid Security" in (c.get("t") or "") for row in data["rows"] for c in row)
    assert all(cell(service, "Bulk Bond!%s6" % col) == "" for col in ex.BULK_BOND_ASKS)
    # the file's three bonds keep the values Excel saved (offline: frozen at them)
    for r in (3, 4, 5):
        assert cell(service, "Bulk Bond!A%d" % r) and cell(service, "Bulk Bond!B%d" % r) == ex.recorded_value(model, "Bulk Bond", "B%d" % r)
        assert cell(service, "Bulk Bond!K%d" % r) == ex.recorded_value(model, "Bulk Bond", "K%d" % r)


def test_a_bond_typed_into_the_empty_row_is_asked_for(service):
    u = service.login("Düzen Eurobond")["user"]
    service.set_inputs(u, "tto", [{"ref": "Bulk Bond!A6", "value": "XS2010030836"}])
    try:
        # (offline nothing answers: what matters is that the row asks - its cell no longer the guard's empty text)
        assert cell(service, "Bulk Bond!B6", user_key(u)) != ""
        assert cell(service, "Bulk Bond!B6") == ""
    finally:
        service.reset_inputs(u, "tto", ["Bulk Bond!A6"])


# ------------------------------------------------------------------------------------------------ Hesaplayıcılar, Motor
def test_the_calculators_come_in_three_tabs():
    tabs = {s["id"]: (s["title"], s["panels"]) for s in VIEWS["calc"]["sections"]}
    assert tabs == {"conv": ("Faiz", ["B7", "B5", "B6", "B8", "B9", "B24"]),
                    "fx": ("FX · vol", ["B23", "B28", "B31", "B32"]),
                    "bond": ("Tahvil", ["B27", "B33", "B26"])}
    listed = [pid for _, ids in tabs.values() for pid in ids]
    assert sorted(listed) == sorted(shown("calc")) and len(listed) == len(set(listed))      # each in one tab, none left


def test_ana_girdiler_rows_are_named_and_read_alike(service):
    data = page_panel(service, None, "calc", "B7")["data"]
    names, values = texts(data, "Z"), texts(data, "AA")
    assert (names[6], names[11], names[12]) == ("Gün", "Fark (Forward − Spot)", "Puan")
    assert all(re.match(r"^-?\d{1,3}(\.\d{3})*,\d{4}$", values[r]) for r in (9, 10, 11))      # spot, forward, difference
    assert re.match(r"^-?\d{1,3}(\.\d{3})*$", values[12])                                    # points: whole, as the Forward page's
    spot, fwd, diff, pts = (cell(service, "Calculators!AA%d" % r) for r in (9, 10, 11, 12))
    assert diff == pytest.approx(fwd - spot, abs=1e-12) and pts == pytest.approx(diff * 10000, abs=1e-6)   # (values the workbook's)
    model = service.books["tto"].model
    assert ex.formula_of(model, "Calculators", "AA11").endswith("AA10-AA9,$AH$11)")


def test_motors_panels_open():
    assert not panel("motor", "B12").get("collapsed")              # Tatiller: the tab's only panel
    sonuc = panel("motor", "B18")
    assert not sonuc.get("collapsed") and sonuc["limit"] == {"rows": 24}


# ------------------------------------------------------------------------------------------------ DİBS RV's helper columns
def test_dibs_rvs_default_hidden_columns_are_helpers_only(service):
    """The widest table (72 columns) hides by default only helper columns - its own FX swap side on the offshore ICAP
    curve as before, the accrued interest beside the dirty price and the cash flows' status - never a yield, price, spread,
    ASW, carry or signal; one click brings them back ("Sütunlar")."""
    hidden = service.DEFAULT_HIDDEN_COLUMNS["v/dibs/B3"]
    assert hidden == ("Q", "BE", "BF", "BG", "BH", "BI", "BJ")
    b3 = page_panel(service, None, "dibs", "B3")["data"]
    head = dict(zip(b3["c"], (c.get("t") for c in next(row for row in b3["rows"] if row[0].get("t") == "ISIN"))))
    assert (head["Q"], head["BE"]) == ("İşlemiş (valör)", "Durum")
    assert all(col in b3["c"] for col in hidden)                   # sent with the table: hidden in the browser only
