"""Borsa Swap against the TRY workbook's mid curves (``tto/borsaspread.py``): per BIST swap quote the OIS and the
offshore mid curve's simple ACT/360 zero rate between the row's own start and maturity, and BID % / ASK % − each in bp."""
from __future__ import annotations

import math

import pytest

from conftest import cell
from tto import borsaspread as bsp
from tto.xl import numfmt
from tto.xl.errors import XlError
from tto.xl.model import Model, parse_a1

S = 46330.0                                               # a spot date (04.11.2026)
HEADS = [h for h, _ in bsp.HEADS]
T0 = ("D", "E", "H", "M")                                 # the tables' maturity, days, BID %, ASK %
T1 = ("Q", "R", "U", "Z")
BLANK = {"t": "", "k": ""}
NA = XlError("#N/A")


def planted(on=0.40):
    """A curve with nodes at its spot, 30 and 91 days: simple ACT/360 zero rates of 36 % and 38 % there."""
    l30 = -math.log(1 + 0.36 * 30 / 360)
    l91 = -math.log(1 + 0.38 * 91 / 360)
    return bsp.Curve(S, [0.0, 30.0, 91.0], [0.0, l30, l91], on), l30, l91


def tables(svc, user=None):
    panels = {p["id"]: p for p in svc.view(user, "borsa")["panels"]}
    return panels["t0"]["data"], panels["t1"]["data"]


def quoted(data, letters):
    """The quoted rows of a rendered BIST swap table: maturity, days, bid, ask and the six cells added on the right."""
    cols = data["c"]
    mat, days, bid, ask = (cols.index(x) for x in letters)
    added = [cols.index(h) for h in HEADS]
    out = []
    for r, row in zip(data["r"], data["rows"]):
        if r == 8:
            continue
        out.append({"r": r, "mat": row[mat].get("v"), "days": row[days].get("v"), "bid": row[bid].get("v"),
                    "ask": row[ask].get("v"), "cells": [row[j] for j in added]})
    return out


# ============================================================================== the curve
def test_zero_rate_of_a_planted_curve_matches_a_hand_computation():
    curve, l30, l91 = planted()
    assert curve.zero(S, S + 30) == pytest.approx(0.36, rel=1e-13)                 # at a node: its own rate
    assert curve.zero(S, S + 91) == pytest.approx(0.38, rel=1e-13)
    # between two dates off the nodes: ln DF linear in days between the nodes around each date
    l10 = l30 * 10 / 30
    l50 = l30 + (l91 - l30) * 20 / 61
    assert curve.zero(S + 10, S + 50) == pytest.approx((math.exp(l10 - l50) - 1) * 360 / 40, rel=1e-13)
    # past the last node: along the last segment (the workbook's MIN(MATCH(…), ROWS − 1))
    l120 = l30 + (l91 - l30) * 90 / 61
    assert curve.zero(S, S + 120) == pytest.approx((math.exp(-l120) - 1) * 360 / 120, rel=1e-13)
    assert curve.df(S) == 1.0 and curve.zero(S + 30, S + 30) is None and curve.zero(S + 31, S + 30) is None
    # a node without a number (Bloomberg did not answer): only the two segments that need it have no rate
    holed = bsp.Curve(S, [0.0, 30.0, 91.0, 182.0], [0.0, l30, NA, l91 * 2])
    assert holed.zero(S, S + 20) == pytest.approx(curve.zero(S, S + 20), rel=1e-13)
    assert holed.zero(S, S + 60) is None and holed.zero(S, S + 120) is None
    assert bsp.Curve(None, [0.0, 30.0], [0.0, l30]).zero(S, S + 30) is None          # no spot date: no curve


def test_a_start_before_the_spot_is_carried_with_the_curves_overnight():
    """T+0 starts a day - over a weekend three - before the curve's spot: that stub runs at the curve's O/N, simple ACT/360."""
    curve, l30, _ = planted(on=0.40)
    df30 = 1 / (1 + 0.36 * 30 / 360)
    assert curve.zero(S - 1, S + 30) == pytest.approx(((1 + 0.40 * 1 / 360) / df30 - 1) * 360 / 31, rel=1e-13)
    assert curve.zero(S - 3, S + 30) == pytest.approx(((1 + 0.40 * 3 / 360) / df30 - 1) * 360 / 33, rel=1e-13)
    assert curve.zero(S - 1, S) == pytest.approx(0.40, rel=1e-13)                  # up to the spot: the O/N itself
    assert curve.zero(S - 3, S - 1) == pytest.approx(((1 + 0.40 * 3 / 360) / (1 + 0.40 / 360) - 1) * 360 / 2, rel=1e-13)
    assert curve.df(S - 3) == pytest.approx(1 + 0.40 * 3 / 360)
    # a curve without an O/N prices from its spot on, never before it
    bare = bsp.Curve(S, curve.days, curve.lndf, None)
    assert bare.zero(S - 1, S + 30) is None and bare.zero(S, S + 30) == pytest.approx(0.36, rel=1e-13)


def test_short_points_come_before_the_curves_first_node():
    """The OIS curve's first node is 1M: for the spreads the 1W and 2W points (ORANLAR's 1W / 2W "OIS zero", simple
    ACT/360) come before it - exact at their own days, ln DF linear between them, nothing changed from the 1M node on."""
    curve, l30, l91 = planted(on=0.40)
    days, lndf = bsp.with_short_points(curve.days, curve.lndf, [(7.0, 0.35), (14.0, 0.355)])
    assert days == [0.0, 7.0, 14.0, 30.0, 91.0] and lndf[3:] == [l30, l91]
    short = bsp.Curve(S, days, lndf, 0.40)
    assert short.zero(S, S + 7) == pytest.approx(0.35, rel=1e-13)
    assert short.zero(S, S + 14) == pytest.approx(0.355, rel=1e-13)
    for a, b in ((S, S + 30), (S + 30, S + 91), (S + 40, S + 120)):            # from the 1M node on: the curve's own
        assert short.zero(a, b) == pytest.approx(curve.zero(a, b), rel=1e-13)
    l7, l14 = -math.log(1 + 0.35 * 7 / 360), -math.log(1 + 0.355 * 14 / 360)
    l10, l20 = l7 + (l14 - l7) * 3 / 7, l14 + (l30 - l14) * 6 / 16
    assert short.zero(S + 10, S + 20) == pytest.approx((math.exp(l10 - l20) - 1) * 360 / 10, rel=1e-13)
    # under 1W: spot → 1W, a T+0 start carried to the spot with the O/N as before
    assert short.zero(S, S + 3) == pytest.approx((math.exp(-l7 * 3 / 7) - 1) * 360 / 3, rel=1e-13)
    assert short.zero(S - 1, S + 3) == pytest.approx(((1 + 0.40 / 360) / math.exp(l7 * 3 / 7) - 1) * 360 / 4, rel=1e-13)
    # a point without a number, past the first node, at the spot or of a day given twice is left out
    assert bsp.with_short_points(curve.days, curve.lndf, [(7.0, None), (45.0, 0.35), (0.0, 0.3), (14.0, 0.355), (14.0, 0.5)])[0] == \
        [0.0, 14.0, 30.0, 91.0]
    assert bsp.with_short_points([5.0, 30.0], [0.0, l30], [(7.0, 0.35)]) == ([5.0, 30.0], [0.0, l30])      # no spot node


# ============================================================================== the page
def test_each_quote_gets_its_spread_to_the_ois_and_the_offshore_mid(service):
    loc = numfmt.get_locale("tr")
    seen = {"pos": 0, "neg": 0, "bid only": 0, "ask only": 0}
    for data, letters in zip(tables(service), (T0, T1)):
        assert data["c"][-6:] == HEADS and data["added"] == 6
        head = data["rows"][data["r"].index(8)][-6:]
        assert [c["t"] for c in head] == HEADS and all(c["b"] and c["tip"] for c in head)
        rows = quoted(data, letters)
        assert len(rows) >= 5
        for row in rows:
            zo, zf, bid_ois, ask_ois, bid_off, ask_off = row["cells"]
            for z in (zo, zf):                                     # every quoted row has both mids, as BID % shows its rate
                assert isinstance(z["v"], float) and z["t"] == numfmt.format_value(z["v"], "0.00%", loc)
            for side, cells in (("bid", (bid_ois, bid_off)), ("ask", (ask_ois, ask_off))):
                rate = row[side]
                for spread, z in zip(cells, (zo["v"], zf["v"])):
                    if not isinstance(rate, float):
                        assert spread == BLANK                     # a one-sided quote: the other side has no spread
                        continue
                    assert spread["v"] == pytest.approx((rate - z) * 1e4, abs=1e-9)
                    if rate > z + 0.5e-4:                          # above the mid: a positive spread
                        assert spread["t"].startswith("+") and spread["c"] == "pos"
                        seen["pos"] += 1
                    elif rate < z - 0.5e-4:
                        assert spread["t"].startswith("-") and spread["c"] == "neg"
                        seen["neg"] += 1
                    assert spread["t"].lstrip("+-") == numfmt.format_value(math.floor(abs(spread["v"]) + 0.5), "#,##0", loc)
            if isinstance(row["bid"], float) != isinstance(row["ask"], float):
                seen["bid only" if isinstance(row["bid"], float) else "ask only"] += 1
        texts = [c.get("t", "") for row in data["rows"] for c in row[-6:]]
        assert not [t for t in texts if t.startswith("#")]
    assert all(n >= 1 for n in seen.values()), seen                # (the recorded day has all four)


def test_the_mids_agree_with_oranlar_at_its_tenors(service):
    """ORANLAR's "OIS zero" and "ICAP" (Masa) for the same dates: a T+1 quote of 30 days runs from the spot to the
    curves' 1M node; a T+0 quote of one day from today to the spot - ORANLAR's ON row, the stub alone."""
    def tto(ref):
        return cell(service, ref)

    t0, t1 = (quoted(d, x) for d, x in zip(tables(service), (T0, T1)))
    spot = tto("OIS_MAIN!B2")
    assert tto("Forward!I2") == spot                               # (the recorded day: USDTRY and TRY OIS spot the same)
    row = next(r for r in t1 if r["days"] == 30.0)
    assert row["mat"] - 30 == spot and row["mat"] == tto("Motor!B89") and tto("Forward!AK127") == 30.0
    assert row["cells"][0]["v"] == pytest.approx(tto("MASA!G10"), rel=1e-12) and tto("MASA!G10") == tto("Motor!M89")
    assert row["cells"][1]["v"] == pytest.approx(tto("MASA!F10"), rel=1e-12)          # ICAP 1M: the offshore 1M mid
    assert tto("MASA!F10") == pytest.approx(tto("Forward!J10") / 100, rel=1e-12)
    row = next(r for r in t0 if r["days"] == 1.0)
    assert row["mat"] == spot
    assert row["cells"][0]["v"] == pytest.approx(tto("MASA!G6"), rel=1e-12)              # TLREF, 365 → 360
    assert tto("MASA!G6") == pytest.approx(tto("OIS_MAIN!J2") * 360 / 365, rel=1e-12)
    assert row["cells"][1]["v"] == pytest.approx(tto("MASA!F6"), rel=1e-12)              # the offshore O/N mid
    assert tto("MASA!F6") == pytest.approx((tto("Forward!I6") + tto("Forward!K6")) / 200, rel=1e-12)
    assert "Spot öncesi" in row["cells"][0]["tip"] and "TLREF" in row["cells"][0]["tip"]
    assert "Spot öncesi" not in next(r for r in t1 if r["days"] == 30.0)["cells"][0]["tip"]


def test_short_rows_meet_oranlars_1w_and_2w(service):
    """Under a month the OIS mid reads the 1W and 2W points before the curve's 1M node: a T+1 quote of 7 / 14 days is
    ORANLAR's 1W / 2W "OIS zero" (the 1W / 2W OIS quotes, 365 → 360).  The bootstrapped curve and Masa's Bootstrap row
    stay as they were: their spot → 7 days is still the spot → 1M segment.  The offshore curve has its own 1W, 2W and
    1M points (TRYI1W, TRYI2W, TRYI1M): a quote on one of their days is ORANLAR's "ICAP" there."""
    def tto(ref, user=None):
        return cell(service, ref, user)

    t1 = quoted(tables(service)[1], T1)
    spot = tto("OIS_MAIN!B2")
    assert (tto("Forward!O6"), tto("Forward!N6"), tto("Forward!O7"), tto("Forward!N7")) == ("1W", 7.0, "2W", 14.0)
    for days, oranlar in ((7.0, "MASA!G8"), (14.0, "MASA!G9")):
        row = next(r for r in t1 if r["days"] == days)
        assert row["mat"] - days == spot
        assert row["cells"][0]["v"] == pytest.approx(tto(oranlar), rel=1e-12)
    assert tto("MASA!G8") == pytest.approx(tto("Forward!P6") / 100, rel=1e-12) and tto("MASA!G10") == tto("Motor!M89")
    assert tto("Motor!C88") == 0.0 and tto("Motor!C89") == 30.0                    # the curve: no node before 1M
    u = service.login("Borsa spread kısa")["user"]
    try:
        res = service.set_inputs(u, "tto", [{"ref": "MASA!C60", "value": spot}, {"ref": "MASA!E60", "value": spot + 7}])
        assert res["errors"] == []
        boot = tto("MASA!D67", u)                                                  # Masa's Bootstrap row, spot → 7 days
        assert boot == pytest.approx((math.exp(-tto("Motor!I89") * 7 / 30) - 1) * 360 / 7, rel=1e-12)
        assert abs(boot - tto("MASA!G8")) > 1e-4                                   # (not the 1W quote: it is not on the curve)
    finally:
        service.reset_inputs(u, "tto")
    row = next(r for r in t1 if r["days"] == 14.0)                                 # offshore 2W node: 14 days
    assert tto("Forward!AK126") == 14.0 and row["cells"][1]["v"] == pytest.approx(tto("MASA!F9"), rel=1e-12)


def test_between_any_two_dates_the_mids_are_those_of_masas_blocks(service):
    """Between any two dates from 1M on the OIS mid is Masa's 'TARİH ARASI FAİZ' Bootstrap row (ACT/360); the offshore
    mid of a quote is the market simple rate of Masa's 'KIRIK VADE' block (offshore curve, ACT/360) at its maturity."""
    u = service.login("Borsa spread tarih")["user"]
    tto = service.books["tto"]
    try:
        spot = cell(service, "OIS_MAIN!B2")
        for a, b in ((30, 100), (45, 200), (0, 300), (61, 92)):
            res = service.set_inputs(u, "tto", [{"ref": "MASA!C60", "value": spot + a}, {"ref": "MASA!E60", "value": spot + b}])
            assert res["errors"] == [] and cell(service, "MASA!G60", u) == b - a
            ois = service.et.call(lambda: bsp.read_curves(tto, service._calc(u, tto))["ois"])
            assert ois.zero(spot + a, spot + b) == pytest.approx(cell(service, "MASA!D67", u), rel=1e-12)
        for days in (7.0, 14.0):
            row = next(r for r in quoted(tables(service, u)[1], T1) if r["days"] == days)
            res = service.set_inputs(u, "tto", [{"ref": "MASA!C171", "value": row["mat"]}])
            assert res["errors"] == [] and cell(service, "MASA!BL173", u) == days
            assert row["cells"][1]["v"] == pytest.approx(cell(service, "MASA!F175", u), rel=1e-12)
    finally:
        service.reset_inputs(u, "tto")


def test_a_users_own_ois_quote_moves_their_mids_only(service):
    """The curves are the TRY workbook's as the page's user has it: a 1M OIS quote of their own moves their page, nobody
    else's."""
    def row30(user):
        return next(r for r in quoted(tables(service, user)[1], T1) if r["days"] == 30.0)

    u = service.login("Borsa spread kendi")["user"]
    before = row30(None)["cells"][0]["v"]
    try:
        res = service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B9", "value": 0.40}], allow_adhoc=True)
        assert res["errors"] == []
        mine = row30(u)
        assert mine["cells"][0]["v"] == pytest.approx(0.40 * 360 / 365, rel=1e-12)     # the 1M par (ACT/365) as zero ACT/360
        assert mine["cells"][2]["v"] == pytest.approx((mine["bid"] - 0.40 * 360 / 365) * 1e4, abs=1e-9)
        assert row30(None)["cells"][0]["v"] == before and row30(None)["cells"][1]["v"] == mine["cells"][1]["v"]
    finally:
        service.reset_inputs(u, "tto")
    assert row30(u)["cells"][0]["v"] == before


def test_rows_without_a_quote_stay_empty_and_other_tables_are_left_alone(service):
    borsa, tto = service.books["borsa"], service.books["tto"]
    loc = numfmt.get_locale("tr")
    letters = list("DEGHIJKLMNOP")

    def table(rnums, cols):
        return {"rows": [[dict(BLANK) for _ in cols] for _ in rnums], "r": list(rnums), "c": list(cols)}

    def run():
        calc = borsa.engine.shared
        curves = bsp.read_curves(tto, tto.engine.shared)
        out = {"empty": table([8, 40, 60], letters), "other": table([4], "ABC"), "moved": table([9, 10], letters),
               "lost": table([8, 9], letters)}
        bsp.columns(borsa, calc, "D8:P54", out["empty"], loc, curves)          # row 40: no quote, row 60: past the table
        bsp.columns(borsa, calc, "A4:C54", out["other"], loc, curves)          # not a swap table
        bsp.columns(borsa, calc, "D9:P54", out["moved"], loc, curves)          # its first row is no caption row
        gone = {"ois": bsp.Curve(None, [], [], why="TTO çalışma kitabında BOOT_GUN / BOOT_LNDF adı yok"), "off": curves["off"]}
        bsp.columns(borsa, calc, "D8:P54", out["lost"], loc, gone)
        return out

    out = service.et.call(run)
    empty = out["empty"]
    assert [c["t"] for c in empty["rows"][0][-6:]] == HEADS and empty["c"][-6:] == HEADS and empty["added"] == 6
    assert empty["rows"][1][-6:] == [BLANK] * 6 and empty["rows"][2][-6:] == [BLANK] * 6
    for name in ("other", "moved"):
        assert "added" not in out[name] and all(len(row) == len(out[name]["c"]) for row in out[name]["rows"])
    # a curve that cannot be read: its columns stay empty and say why; the other curve's are there
    head, row = out["lost"]["rows"][0][-6:], out["lost"]["rows"][1][-6:]
    assert "BOOT_GUN" in head[0]["tip"] and "BOOT_GUN" in head[2]["tip"] and "BOOT_GUN" not in head[1]["tip"]
    assert row[0]["t"] == "" and "BOOT_GUN" in row[0]["tip"] and row[2] == BLANK and row[3] == BLANK
    assert isinstance(row[1]["v"], float) and isinstance(row[4]["v"], float)


# ============================================================================== the T+1 value date
def test_the_t1_table_counts_its_value_dates_on_the_copy_of_the_try_holidays():
    """The Borsa workbook counts the T+1 quotes' value date over weekends only (WORKDAY(TODAY(),1)) and has no holiday
    list: the dashboard's addition gives it a copy of the TRY list and the T+1 date on it, and every "Valör" of the T+1
    table counts from that date - the file's last row too, which has no formula there.  The T+0 table's last "Valör"
    (today, its days left out in the file) counts as the rows above it.  The model file stays as it was."""
    import os
    from tto import extras
    from tto.books import formula_text, load_books
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plain, books = load_books(os.path.join(root, "models"), extras=False)["borsa"], load_books(os.path.join(root, "models"))
    borsa = books["borsa"]

    def f(book, ref):
        return formula_text(book, *book.cell(ref))

    assert f(plain, "bu!Q9") == '=IF(R9="","",WORKDAY(TODAY(),1)+R9)' and f(plain, "bu!Q54") is None
    assert f(plain, "bu!D54") == '=IF(ISNUMBER(E54),TODAY(),"")'
    assert borsa.left_out == [] and f(borsa, "EK_TATIL!B2") == "=WORKDAY(TODAY(),1,$A$5:$A$204)"
    assert [f(borsa, "bu!Q%d" % r) for r in (9, 30, 53, 54)] == ['=IF(R%d="","",EK_TATIL!$B$2+R%d)' % (r, r) for r in (9, 30, 53, 54)]
    assert f(borsa, "bu!D54") == '=IF(ISNUMBER(E54),TODAY()+E54,"")' and f(borsa, "bu!D53") == f(plain, "bu!D53")
    styles = borsa.model.sheet("bu").styles
    assert styles.get(parse_a1("Q54")) == styles.get(parse_a1("Q53"))
    # a file whose T+1 dates are counted otherwise is left as it is (the addition says why it does not fit)
    model = Model.load(os.path.join(root, "models", "borsa.json.gz"))
    model.sheet("bu").fml.pop(parse_a1("Q20"))
    assert [x for x in extras.apply("borsa", model) if x.startswith("Borsa T+1")] == ["Borsa T+1 valörü: bu!Q20 bir formül değil"]
    assert extras.BORSA_HOL_SHEET not in model.sheet_index


def test_the_copy_starts_as_the_try_workbooks_list(service):
    """Nothing stored for it: the copy is the TRY workbook's list row by row as the service starts, and the T+1 date on
    it is the TRY OIS spot date; the settings page lists the three books the TRY holidays are written to."""
    copy = [cell(service, "EK_TATIL!A%d" % r, book="borsa") for r in range(5, 205)]
    motor = [cell(service, "Motor!A%d" % r) for r in range(361, 524)]
    assert copy[:163] == motor and copy[163:] == [None] * 37 and sum(1 for x in motor if x) > 100
    assert cell(service, "EK_TATIL!B2", book="borsa") == cell(service, "OIS_MAIN!B2") == S
    assert [s["name"] for s in service.sheets("borsa")][-1] == "EK_TATIL"
    hol = service.holidays()
    assert hol["books"] == ["tto", "asw", "borsa"] and hol["slots"] == 163


def test_a_t1_start_over_a_planted_try_holiday(tmp_path):
    """04.11.2026 - the recorded day's T+1 - made a TRY holiday on the settings page: the TRY OIS spot date and the BIST
    swaps' T+1 date both move to the 5th, so does every "Valör" of the T+1 table, and the T+1 quotes start on the OIS spot
    again (no stub); a T+0 quote reaches it over two days.  A restart keeps it - from the TRY workbook's list, the
    copy's own stored days aside."""
    from conftest import make_service
    svc = make_service(tmp_path)
    try:
        def b(ref):
            return cell(svc, ref, book="borsa")

        u = svc.login("Borsa tatil")["user"]
        tr = svc.holidays()["tr"]
        assert b("EK_TATIL!B2") == cell(svc, "OIS_MAIN!B2") == S and b("bu!Q9") == S + b("bu!R9")
        res = svc.set_holidays(u, tr + [{"date": "04.11.2026", "name": "Deneme tatili"}])
        assert res["books"] == ["tto", "asw", "borsa"] and S in [b("EK_TATIL!A%d" % r) for r in range(5, 205)]
        assert cell(svc, "OIS_MAIN!B2") == S + 1 == b("EK_TATIL!B2")
        assert b("bu!Q9") == S + 1 + b("bu!R9")                                      # the shown value date moved
        t0, t1 = tables(svc)
        rows = quoted(t1, T1)
        assert rows and all(r["mat"] - r["days"] == S + 1 for r in rows)
        assert all("Spot öncesi" not in r["cells"][0]["tip"] for r in rows)
        one = next(r for r in quoted(t0, T0) if r["days"] == 1.0)
        on = cell(svc, "Forward!AD123")
        assert one["mat"] == S and "(2 gün)" in one["cells"][0]["tip"]               # 03.11 → 05.11: two days of O/N
        assert one["cells"][0]["v"] == pytest.approx(((1 + on * 2 / 360) / (1 + on / 360) - 1) * 360, rel=1e-12)
        # (as if the desk had saved the list before the copy existed: nothing stored for the copy)
        refs = [ref for (_, ref) in svc.store.shared_inputs("borsa") if ref.startswith("EK_TATIL!")]
        assert refs
        svc.store.clear_shared_inputs("borsa", refs)
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        assert cell(again, "EK_TATIL!B2", book="borsa") == cell(again, "OIS_MAIN!B2") == S + 1
        assert cell(again, "bu!Q9", book="borsa") == S + 1 + cell(again, "bu!R9", book="borsa")
    finally:
        again.stop()
