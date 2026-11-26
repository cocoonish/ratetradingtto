"""DİBS Trading in groups of columns, with each bond's fair yield and price on the fitted ASW curves - DİBS RV's OIS curve
and DİBS ASW's FX swap implied TRY curve (``tto/rvfair.py``) - and the bond lists shown as the trading list has them: DİBS
Trading's value dates and the DİBS ASW table without the rows that hold no bond, the ASW table kind by kind, by maturity
(display only)."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import bonds as bd
from tto import extras as ex
from tto import rvfair
from tto.store import user_key
from tto.xl.tokenizer import col_to_index, index_to_col

FIXED, BILL, TLREF, NO_PRICE, LONG = "TRT150328T24", "TRB100227T13", "TRT090130T12", "TRT081128T15", "TRT051033T12"
#: the columns of the summary by their letter (kept from before the groups; the fair values are new ones)
OIS_YIELD, OIS_PRICE, FX_ASW, FX_YIELD, FX_PRICE, FX_RICH, FX_SIGNAL = "Y", "Z", "AA", "AB", "AC", "AD", "AE"


def rv(s, col, r, user=None):
    return cell(s, "DİBS RV!%s%d" % (col, r), user)


def row_of(s, isin):
    return next(r for r in range(5, 55) if rv(s, "A", r) == isin)


def fx_sheet(s, user=None):
    """DİBS ASW's sheet on the FX swap implied curve: (a cell's value by column and row, the row of an ISIN)."""
    book = s.books["asw"]
    si = book.model.sheet_index["ASW"]

    def run():
        calc, _ = s._asw_fx_calc(book, user)
        return {(c, r): calc.get(si, r, col_to_index(c)) for r in range(3, 57) for c in ("B", "J", "L", "M", "N", "O", "P", "Q", "R", "S", "T",
                                                                                      "AN", "AW", "AX", "AY", "AZ", "BA")}
    got = s.et.call(run)
    return (lambda c, r: got[(c, r)]), (lambda isin: next(r for r in range(7, 57) if got[("B", r)] == isin))


def summary(s, user):
    return next(p for p in s.view(user, "dibslive")["panels"] if p["id"] == "L0")["data"]


def line_of(d, isin):
    return next(row for row in d["rows"] if len(row) > 2 and row[2].get("t") == isin)


def at(d, line, col):
    return line[d["c"].index(col)]


def by_hand_yield(s, r, dirty):
    """A coupon bond's BIST compound yield at a dirty price - bisection on the sheet's own cash flows and their periods."""
    f = rv(s, "CU", r)
    flows = [(rv(s, index_to_col(col_to_index("ID") + k), r), rv(s, index_to_col(col_to_index("LV") + k), r)) for k in range(24)]
    flows = [(cf, x) for cf, x in flows if cf]
    lo, hi = 0.0, 3.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if sum(cf * (1 + mid / f) ** -x for cf, x in flows) > dirty:
            lo = mid
        else:
            hi = mid
    return (1 + lo / f) ** f - 1


def test_the_fair_yield_and_price_of_a_fixed_coupon_bond_and_a_bill(service):
    """At the fitted curve's ASW (a + b·t + c·t² at the bond's years): the dirty price at the OIS spot is PV − ASW ×
    annuity / 100, at the value date that ÷ the funding factor, the clean one that − the accrued interest; the yield is
    the screen's BIST compound yield of that price.  By hand, from the sheet's own columns: a fixed coupon bond (on the
    curve: its fitted ASW is the sheet's) and a bill (not on it: read off the curve), on OIS (DİBS RV) and on the FX swap
    implied curve (DİBS ASW on it - its own PV, annuity, fitted curve, funding and accrued; the yield DİBS RV's)."""
    s = service
    u = s.login("Adil Değer")["user"]
    d = summary(s, u)
    fx, fx_row = fx_sheet(s, u)
    for isin in (FIXED, BILL):
        r, ar = row_of(s, isin), fx_row(isin)
        coef = [fx(x, 3) for x in ("AW", "AX", "AY")]
        t = fx("J", ar)
        asw = coef[0] + coef[1] * t + coef[2] * t ** 2
        assert asw == pytest.approx(fx("S", ar), abs=1e-9)                              # the sheet's own fitted curve
        dirty = (fx("P", ar) - asw * fx("Q", ar) / 100) / (fx("O", ar) / (fx("L", ar) + fx("N", ar)))
        line = line_of(d, isin)
        assert at(d, line, FX_PRICE)["v"] == pytest.approx(dirty - fx("N", ar), abs=1e-9), isin
        want = by_hand_yield(s, r, dirty) if isin == FIXED else (100 / dirty) ** (365 / rv(s, "DR", r)) - 1
        assert at(d, line, FX_YIELD)["v"] == pytest.approx(want, abs=1e-9), isin
        assert "DİBS ASW'nin ASW eğrisi (13 kâğıt; " + rvfair.FX_CURVE_TEXT in at(d, line, FX_YIELD)["tip"]
        assert (fx("M", ar), fx("N", ar), fx("L", ar)) == (rv(s, "P", r), pytest.approx(rv(s, "CW", r), abs=1e-9), rv(s, "O", r))
    for side, (a, b, c), pv, ann, fitted, ycol, pcol in (
            ("OIS", ("CA", "CB", "CC"), "EG", "EE", "FU", OIS_YIELD, OIS_PRICE),):
        coef = [rv(s, x, 3) for x in (a, b, c)]
        r = row_of(s, FIXED)
        t = rv(s, "FW", r)
        asw = coef[0] + coef[1] * t + coef[2] * t ** 2
        assert asw == pytest.approx(rv(s, fitted, r), abs=1e-9), side                 # the sheet's own fitted ASW
        dirty = (rv(s, pv, r) - asw * rv(s, ann, r) / 100) / rv(s, "DD", r)
        line = line_of(d, FIXED)
        assert at(d, line, pcol)["v"] == pytest.approx(dirty - rv(s, "CW", r), abs=1e-9), side
        assert at(d, line, ycol)["v"] == pytest.approx(by_hand_yield(s, r, dirty), abs=1e-9), side
        assert at(d, line, ycol)["t"].endswith("%") and "eğri ASW" in at(d, line, ycol)["tip"] and "soft" not in (at(d, line, ycol).get("cls") or "")
        # a bill: read off the curve at its years
        r = row_of(s, BILL)
        t = rv(s, "FW", r)
        assert rv(s, fitted, r) == ""                                                   # (not in the curve)
        dirty = (rv(s, pv, r) - (coef[0] + coef[1] * t + coef[2] * t ** 2) * rv(s, ann, r) / 100) / rv(s, "DD", r)
        line = line_of(d, BILL)
        assert at(d, line, pcol)["v"] == pytest.approx(dirty, abs=1e-9) and rv(s, "CW", r) == 0.0, side
        assert at(d, line, ycol)["v"] == pytest.approx((100 / dirty) ** (365 / rv(s, "DR", r)) - 1, abs=1e-12), side
        assert at(d, line, ycol)["tip"].startswith("Bono eğriye girmez"), side
    # cheap against the curve (ASW above the fitted one): its fair price is above the screen's, its fair yield below
    line = line_of(d, FIXED)
    assert at(d, line, "M")["v"] > 0 and at(d, line, OIS_PRICE)["v"] > rv(s, "O", row_of(s, FIXED))
    assert at(d, line, OIS_YIELD)["v"] < rv(s, "T", row_of(s, FIXED))


def test_at_its_own_asw_a_bond_is_worth_its_price(service):
    """The arithmetic is the sheet's own turned around: at the bond's own ASW the dirty price at the spot is the sheet's,
    and the yield the solver finds at the bond's dirty price is the screen's yield."""
    s = service
    r = row_of(s, FIXED)
    assert rv(s, "EG", r) - rv(s, "EH", r) * rv(s, "EE", r) / 100 == pytest.approx(rv(s, "DI", r), abs=1e-9)
    flows = [(rv(s, index_to_col(col_to_index("ID") + k), r), rv(s, index_to_col(col_to_index("LV") + k), r)) for k in range(24)]
    flows = [(cf, x) for cf, x in flows if cf]
    simple = rvfair.coupon_yield(rv(s, "DH", r), flows, rv(s, "CU", r), 0.25)
    assert simple == pytest.approx(rv(s, "S", r), abs=1e-10)                           # BIST basit getiri
    assert (1 + simple / rv(s, "CU", r)) ** rv(s, "CU", r) - 1 == pytest.approx(rv(s, "T", r), abs=1e-10)
    assert rvfair.bill_yield(100.0, 91.0) == 0.0 and rvfair.bill_yield(0.0, 91.0) is None
    assert rvfair.curve_asw((-300.0, 80.0, -7.0), 2.0) == pytest.approx(-168.0)


def test_every_trading_bond_has_its_fair_values_or_why_not(service, tmp_path):
    """The fair-value columns are there for every bond of the trading list: a value, or a dash whose tip says why - a TLREF
    floater (no curve for its DM), a bond DİBS RV does not price (DİBS ASW neither); with no fitted curve, none (the
    reason given).  The card says the same."""
    s = service
    u = s.login("Adil Değer Yok")["user"]
    d = summary(s, u)
    tops = [c.get("t") for c in d["rows"][0] if not c.get("sk")]
    assert tops == ["", "Fiyat", "OIS'e göre", "FX swap'a göre", "Risk", "Carry", "Broker", ""]
    heads = [c["t"] for c in d["rows"][1]]
    assert heads[:13] == ["★", "Kâğıt", "ISIN", "Vade", "Kalan yıl", "Valör", "Bid", "Ask", "Son işlem", "Ne zaman", "Getiri %",
                          "ON karşılık %", "ASW / DM"]                     # (the yield's O/N equivalent beside it: 26.11.2026)
    assert heads[13:22] == ["Adil getiri %", "Adil fiyat", "Pahalı / ucuz", "Sinyal", "ASW FX", "Adil getiri %", "Adil fiyat",
                            "Pahalı / ucuz", "Sinyal"]
    assert heads[22:27] == ["Mod. süre", "DV01 / 1mn", s.USD_DV01_HEAD, "C+R (bp)", "T0→T1 repo %"] and heads[-1] == "Kart"
    assert d["c"][:13] == list("ABCDEFGHIJK") + ["AF", "L"] and d["c"][13:22] == ["Y", "Z", "M", "N", "AA", "AB", "AC", "AD", "AE"]
    lines = [row for row in d["rows"][2:] if row[-1].get("t") == "▸"]
    assert len(lines) == len([v for v in s._list_values(u, "tto", "DİBS RV!A5:A54") if v]) >= 15
    for line in lines:
        for col in (OIS_YIELD, OIS_PRICE, FX_YIELD, FX_PRICE):
            got = at(d, line, col)
            assert type(got.get("v")) is float or (got["t"] == "–" and "adil değer yok" in got["tip"]), (line[2]["t"], col, got)
    why = {isin: at(d, line_of(d, isin), OIS_YIELD).get("tip") for isin in (TLREF, NO_PRICE)}
    assert "TLREF'e endeksli" in why[TLREF] and "Fiyat yok" in why[NO_PRICE]
    assert "DİBS ASW kâğıdı hesaplamıyor" in at(d, line_of(d, NO_PRICE), FX_ASW)["tip"] and at(d, line_of(d, NO_PRICE), FX_ASW)["t"] == "–"
    # the FX swap implied curve reaches every bond (beyond its last FX swap price the sheet's OIS quotes): DİBS RV's offshore
    # ICAP curve did not reach this one
    assert type(rv(s, "WX", row_of(s, LONG))) is not float and type(at(d, line_of(d, LONG), FX_YIELD)["v"]) is float
    # the FX side's own columns are DİBS ASW's on the FX swap implied curve (not DİBS RV's BF / BH / BI: the offshore ICAP curve)
    fx, fx_row = fx_sheet(s, u)
    line = line_of(d, FIXED)
    ar = fx_row(FIXED)
    assert (at(d, line, FX_ASW)["v"], at(d, line, FX_RICH)["v"]) == (fx("R", ar), fx("T", ar)) and fx("R", ar) != rv(s, "BF", row_of(s, FIXED))
    th = rv(s, "P", 2)
    assert at(d, line, FX_SIGNAL)["t"] == ("UCUZ" if fx("T", ar) > th else "PAHALI" if fx("T", ar) < -th else "–")
    # the card: the same numbers
    card = {x["name"]: x for x in s.bond_card(u, FIXED)["rv"]}
    assert card["Adil getiri (OIS eğrisi)"]["t"] == at(d, line, OIS_YIELD)["t"] and card["Adil fiyat (FX swap ima eğrisi)"]["t"] == at(d, line, FX_PRICE)["t"]
    assert card["Adil fiyat (OIS eğrisi)"]["tip"] == at(d, line, OIS_PRICE)["tip"]
    assert {x["name"]: x for x in s.bond_card(u, TLREF)["rv"]}["Adil fiyat (OIS eğrisi)"]["t"] == "–"
    # no fitted curve (here: its coefficient typed over by hand), no fair value - and the reason
    other = s.login("Eğrisiz Masa")["user"]
    assert s.set_inputs(other, "tto", [{"ref": "DİBS RV!CA3", "value": "yok"}], allow_adhoc=True)["errors"] == []
    d2 = summary(s, other)
    assert all(at(d2, line, OIS_YIELD)["t"] == "–" for line in d2["rows"][2:] if line[-1].get("t") == "▸")
    for isin in (FIXED, BILL):
        assert "OIS ASW eğrisi uydurulamadı" in at(d2, line_of(d2, isin), OIS_YIELD)["tip"]
    assert type(at(d2, line_of(d2, FIXED), FX_YIELD)["v"]) is float                   # (the FX curve is still there)
    s.reset_inputs(other, "tto")
    assert cell(s, "DİBS RV!CA3", user_key(other)) == rv(s, "CA", 3)


def test_the_bond_lists_show_only_their_bonds_the_asw_table_in_the_trading_lists_order(service):
    """Display only: DİBS Trading's value dates and the DİBS ASW table leave out the rows that hold no bond (the empty
    rows between the desk's groups, the unused ones below - the cells stay where they are: "+ ISIN ekle" finds them);
    the ASW table shows its bonds kind by kind, by maturity, a caption each, as Tüm Kâğıtlar does; DİBS RV is as it was."""
    s = service
    u = s.login("Liste Görünüşü")["user"]
    live = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L1")["data"]
    listed = [r for r in range(5, 55) if rv(s, "A", r)]
    assert [r for r in live["r"] if 5 <= r <= 54] == listed and live["r"][:3] == [2, 3, 4] and live["r"][-1] == 56
    rv_page = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")["data"]
    assert 7 in rv_page["r"] and 16 in rv_page["r"]                                   # (DİBS RV keeps its group separators)
    asw = next(p for p in s.view(u, "asw")["panels"] if p["id"] == "tbl")["data"]
    on_asw = [r for r in range(7, 57) if cell(s, "ASW!B%d" % r, book="asw")]
    assert sorted(r for r in asw["r"] if r >= 7) == on_asw and asw["r"][0] == 6
    captions = [row[0]["t"] for row, r in zip(asw["rows"], asw["r"]) if r == 0]
    names = {k: cap for k, cap, _ in ex.UNI_KINDS}
    count = {}
    for r in on_asw:
        kind = bd.by_isin(cell(s, "ASW!B%d" % r, book="asw"))["kind"]
        count[kind] = count.get(kind, 0) + 1
    assert captions == ["%s · %d kâğıt" % (names[k], count[k]) for k, _, _ in ex.UNI_KINDS if k in count]
    assert captions[:2] == ["Bono · 2 kâğıt", "Sabit kuponlu · 14 kâğıt"]          # (the desk's list: bills first)
    kinds, mats = [], []
    for row, r in zip(asw["rows"], asw["r"]):
        if r < 7:
            continue
        isin = cell(s, "ASW!B%d" % r, book="asw")
        assert row[0]["t"] == isin                                                   # each row is still its cell's
        kinds.append(bd.by_isin(isin)["kind"])
        mats.append(bd.by_isin(isin)["maturity"])
    order = [k for k, _, _ in ex.UNI_KINDS]
    assert [order.index(k) for k in kinds] == sorted(order.index(k) for k in kinds)
    assert all(mats[i] <= mats[i + 1] for i in range(len(mats) - 1) if kinds[i] == kinds[i + 1])
    # the charts read the sheet as it is: the OIS chart's bonds in the sheet's order
    chart = next(p for p in s.view(u, "asw")["panels"] if p["id"] == "chart0")["data"]
    assert chart["series"][0]["labels"] == [cell(s, "ASW!F%d" % r, book="asw") for r in on_asw if type(cell(s, "ASW!BG%d" % r, book="asw")) is float]


def test_a_launchpad_box_keeps_its_bonds(service):
    """A launchpad box keeps rows of a table by their first text (an ISIN, a caption) or by their number - in the
    sheet, or for the trading summary its place as it was - and a part always shows the table's header.  A box saved
    by the version before the bond lists were tidied (rows that hold no bond left out, the ASW table in the trading
    list's order with a caption per kind, the summary's groups of columns) gets the same rows with the same texts: the
    header row stays the header, a group's caption never comes into a part, only the empty rows picked are gone."""
    s = service
    u = s.login("Kutu Kâğıtları")["user"]

    def part(view, panel, rows):
        got = s.panels(u, [{"view": view, "panel": panel, "key": "k", "rows": rows}])["panels"]["k"]["entry"]["data"]
        assert not got.get("part_missing"), (view, panel, rows)
        return got

    def firsts(d, n=1):
        return [[str(c.get("t") or "") for c in row if not c.get("sk")][:n] for row in d["rows"]]

    def page_row(view, panel, r):
        d = next(p for p in s.view(u, view)["panels"] if p["id"] == panel)["data"]
        return d["rows"][d["r"].index(r)]

    # the DİBS ASW table, as the version before answered its boxes: the header row (6) and the bonds picked - by number
    # with the header among them, by the first text with an empty row's number (31 holds no bond: not shown any more)
    head = ["ISIN", "Kaynak (boş=genel)", "Manuel temiz", "Eğri / grafik (1 / 0 / x)", "Etiket", "Ad"]
    for rows in ([6, 8, 25, 31], ["TRB170327T15", "TRT110930T36", 31], [8, 25]):
        d = part("asw", "tbl", rows)
        assert d["r"] == [6, 8, 25] and 0 not in d["r"], (rows, d["r"])
        assert firsts(d, 6)[0] == head and d["rows"][0] == page_row("asw", "tbl", 6)
        assert [x[0] for x in firsts(d)[1:]] == ["TRB170327T15", "TRT110930T36"]
    keys = s.panels(u, [{"view": "asw", "panel": "tbl", "key": "k", "keys": True}])["panels"]["k"]["rk"]
    whole = next(p for p in s.view(u, "asw")["panels"] if p["id"] == "tbl")["data"]
    assert [k for k, r in zip(keys, whole["r"]) if r in (0, 6)] == [None] * 4                # (no caption is a row to pick)
    assert part("asw", "tbl", [FIXED])["r"] == [6, 7 + s._list_values(u, "asw", "ASW!B7:B56").index(FIXED)]
    # DİBS Trading's value dates: its header rows are rows like the others (as before), the empty ones are not shown
    for rows in ([4, 5, 26], ["ISIN", BILL, TLREF]):
        d = part("dibslive", "L1", rows)
        assert d["r"] == [4, 5, 26] and [x[0] for x in firsts(d)] == ["ISIN", BILL, TLREF], rows
    assert part("dibslive", "L1", [2, 3, 4, 8, 16])["r"] == [2, 3, 4, 8]                  # (7 and 16 hold no bond)
    d = part("dibslive", "L1", ["T0", FIXED, 7])
    assert d["r"] == [3, 8] and firsts(d, 6)[0][-1] == "T0 · aynı gün"
    # the trading summary: its rows numbered as before the groups (captions 1, then a row each: bills 3-4 under their
    # caption, the fixed coupon bonds from 6 by maturity - 15.03.28 the fifth, the last TLREF 23), its header row as it was,
    # the groups of columns above it (they tell its two "Adil getiri %" apart)
    for rows in ([3, 10, 23], [1, 3, 10, 23]):
        d = part("dibslive", "L0", rows)
        assert d["r"] == [0, 1, 3, 10, 23], (rows, d["r"])
        assert firsts(d, 6)[1] == ["★", "Kâğıt", "ISIN", "Vade", "Kalan yıl", "Valör"]
        assert [row[2]["t"] for row in d["rows"][2:]] == [BILL, FIXED, "TRT110930T36"]
        assert "OIS'e göre" in [c.get("t") for c in d["rows"][0]]
    d = part("dibslive", "L0", ["Bono", 3])
    assert d["r"] == [0, 1, 2, 3] and firsts(d)[2] == ["Bono · kuponsuz · 2"]
    keys = s.panels(u, [{"view": "dibslive", "panel": "L0", "key": "k", "keys": True}])["panels"]["k"]["rk"]
    full = summary(s, u)
    assert keys[full["rows"].index(line_of(full, FIXED))] == FIXED                      # a box picked now: by the bond's ISIN
    assert [row[2]["t"] for row in part("dibslive", "L0", [FIXED])["rows"][2:]] == [FIXED]


def test_each_page_names_its_fx_swap_curve(service):
    """Two FX swap curves stand side by side: DİBS RV's (the offshore discount curve, its BF:BJ) and the DİBS ASW page's
    (the FX swap implied rates in the place of the OIS quotes: its ASW FX column, its chart, the EK_FX table).  Each page
    names its own - in the titles, the captions and the tips; the cells and their values are as they were."""
    s = service
    u = s.login("Eğri Adı")["user"]
    ima = "FX swap ima eğrisi (TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden; fiyatı yoksa OIS)"
    rv_page = {p["id"]: p for p in s.view(u, "dibs")["panels"]}
    d = rv_page["B3"]["data"]
    caps = d["rows"][d["r"].index(4)]
    for col in ("BF", "BG", "BH", "BI", "BJ"):
        tip = caps[d["c"].index(col)]["tip"]
        assert "FX swap (offshore ICAP eğrisi)" in tip and ima in tip, col
    assert [caps[d["c"].index(c)]["t"] for c in ("BF", "BI")] == ["ASW FX swap (bp)", "Sinyal FX"]           # (the workbook's own)
    assert rv_page["B2b"]["title"] == "ASW eğrisi · FX swap (offshore ICAP eğrisi)"
    asw = {p["id"]: p for p in s.view(u, "asw")["panels"]}
    assert ima in asw["tbl"]["title"] and asw["fxc"]["title"].startswith(ima) and ima in asw["fxline"]["note"]
    head = asw["tbl"]["data"]["rows"][asw["tbl"]["data"]["r"].index(6)]
    assert [c["t"] for c in head[-2:]] == ["ASW FX ima (bp)", "FX ima − OIS (bp)"]
    assert ima in head[-2]["tip"] and "offshore ICAP" in head[-2]["tip"]
    assert asw["chartfx"]["title"] == "FX swap ima eğrisine göre ASW — kalan vade" and asw["chartfx"]["data"]["y_title"] == "ASW FX ima (bp)"
    assert ima in asw["chartfx"]["note"] and "offshore ICAP" in asw["chartfx"]["note"]
