"""Borsa Swap against the TRY workbook's mid curves (``tto/borsaspread.py``): per BIST swap quote the OIS and the
offshore mid curve's simple ACT/360 zero rate between the row's own start and maturity, and BID % / ASK % − each in bp."""
from __future__ import annotations

import math

import pytest

from conftest import cell
from tto import borsaspread as bsp
from tto.xl import numfmt
from tto.xl.errors import XlError

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


def test_between_any_two_dates_the_mids_are_those_of_masas_blocks(service):
    """Off the nodes: the OIS mid is Masa's 'TARİH ARASI FAİZ' Bootstrap row (ACT/360) between the row's two dates, the
    offshore mid the market simple rate of its 'KIRIK VADE' block (offshore curve, ACT/360) at the row's maturity."""
    u = service.login("Borsa spread tarih")["user"]
    try:
        for days in (7.0, 14.0):
            row = next(r for r in quoted(tables(service, u)[1], T1) if r["days"] == days)
            start, end = row["mat"] - days, row["mat"]
            res = service.set_inputs(u, "tto", [{"ref": "MASA!C60", "value": start}, {"ref": "MASA!E60", "value": end},
                                                {"ref": "MASA!C171", "value": end}])
            assert res["errors"] == [] and cell(service, "MASA!G60", u) == days and cell(service, "MASA!BL173", u) == days
            assert row["cells"][0]["v"] == pytest.approx(cell(service, "MASA!D67", u), rel=1e-12)
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
