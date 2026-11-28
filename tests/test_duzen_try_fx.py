"""The desk's 28.11.2026 items on the TRY / FX pages (K8): B4 (one number, one name), B5 (one spread rule), B11 (USD · FOMC
in two tables), B12 (OIS · PPK and Masa · Faiz · PPK), B14 (the Forward page's helpers named) and ORANLAR's direction in
colour.  How they read only: every value but the spreads said the other way round (B5) is the one before (the spot's own
proof: test_tek_spot.py)."""
from __future__ import annotations

import json
import os
import re

import pytest

from conftest import cell
from tto import extras as ex
from tto.books import formula_text
from tto.views import load_views
from tto.xl import numfmt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TR = numfmt.get_locale("tr")


def raw(name):
    with open(os.path.join(ROOT, "tto", "views", name), encoding="utf-8") as fh:
        return json.load(fh)


def tabs(view):
    return {s["id"]: s for s in view["sections"]}


def panels(view):
    return {p["id"]: p for p in view["panels"]}


def page(service, user, view_id):
    return {p["id"]: p for p in service.view(user, view_id)["panels"]}


def at(data, col, row):
    if col not in data["c"] or row not in data["r"]:
        return None
    return data["rows"][data["r"].index(row)][data["c"].index(col)]


def text(service, ref, user=None):
    return service.cell_info(user, "tto", ref, "tr")["cell"].get("t", "")


# ============================================================================== B4: no "-0"
@pytest.mark.parametrize("value, fmt, want", [
    (-0.11, "#,##0;\\-#,##0;0", "0"),                    # (ORANLAR's "Model fark (bp)": "-0" before)
    (-0.04, "#,##0.0;\\-#,##0.0;0.0", "0,0"),
    (-0.004, "0.00;[Red]-0.00", "0,00"),                 # (two sections: the positive one, no red)
    (-1.0552901145525578e-11, '_-* #,##0.00_-;\\-* #,##0.00_-;_-* "-"??_-;_-@_-', "-"),   # (accounting: its zero's dash)
    (-0.000049, "0.00%", "0,00%"),                       # (one section: no sign before either)
    (-0.6, "#,##0;\\-#,##0;0", "-1"), (-12.345, "0.0;\\-0.0", "-12,3"),
])
def test_a_negative_that_reads_as_zero_is_a_zero(value, fmt, want):
    text_, colour = numfmt.render(value, fmt, TR)
    assert text_.strip() == want and (colour is None or value <= -0.5)


def test_the_formulas_text_stays_excel_s():
    """TEXT() in a formula is Excel's to the letter ("-0" too): only what the pages show changed."""
    from tto.xl.functions import F_TEXT
    assert F_TEXT(-0.11, "#,##0;\\-#,##0;0") == "-0" and numfmt.render(-0.11, "#,##0;\\-#,##0;0", excel=True)[0] == "-0"


def test_no_page_says_minus_zero(service):
    neg0 = re.compile(r"^\s*[-−]\s*0([.,]0*)?\s*(%|bp)?\s*$")
    u = service.login("K8 eksi sıfır")["user"]
    for vid in ("carry", "masa", "ois", "usd", "forward", "viop", "tmois"):
        for pid, p in page(service, u, vid).items():
            for row in (p.get("data") or {}).get("rows") or []:
                for c in row:
                    assert not (isinstance(c, dict) and neg0.match(c.get("t") or "")), (vid, pid, c)


# ============================================================================== B4: the strip and Parametreler, counts
def test_the_strip_and_parametreler_read_alike(service):
    """OIS · PPK's Parametreler shows the strip's figures as the strip does: USDTRY (the same spot now: B4), İma 12A and İma
    / PPK with the strip's one decimal (-285 / -284,9 before), İma 1Y sonu TLREF and TLREF with two."""
    for mine, strip in (("OIS_MAIN!D2", "MASA!H2"), ("OIS_MAIN!D5", "MASA!M2"), ("OIS_MAIN!F5", "MASA!N2"),
                        ("OIS_MAIN!B5", "MASA!L2"), ("OIS_MAIN!J2", "MASA!J2")):
        assert text(service, mine) == text(service, strip), (mine, strip)
    assert re.fullmatch(r"-?[\d.]+,\d", text(service, "OIS_MAIN!D5")) and re.fullmatch(r"-?[\d.]+,\d", text(service, "OIS_MAIN!J5"))


def test_counts_read_whole_and_a_threshold_in_bp_with_one_decimal(service):
    """"3,000 ay" (DİBS RV's horizon) was a count: months, days and business days read whole; a bp threshold one decimal."""
    assert [text(service, ref) for ref in ("DİBS RV!J2", "DİBS RV!V2", "Manuel Tahvil!B9", "Manuel Tahvil!B13")] == \
        ["3", "2", "182", "2"]
    assert text(service, "DİBS RV!P2") == "5,0" and text(service, "Forward!AG124") == "2"
    months = [text(service, "OIS_MAIN!J%d" % r) for r in range(66, 81)]
    assert any(months) and all(re.fullmatch(r"\d*", t) for t in months), months


# ============================================================================== B4: one name for the offshore curve
def test_one_name_for_the_offshore_curve(service):
    """"Offshore" wherever the curve is meant (ICAP its source, FX swap ima / XCCY its parts); the titles say the curve and
    its day count (B14: VİOP's quotes ACT/365 / par, the Forward page's zero rates ACT/360)."""
    u = service.login("K8 tek ad")["user"]
    assert [cell(service, ref) for ref in ("MASA!F5", "MASA!L5", "MASA!T42", "MASA!AI5", "MASA!M109")] == \
        ["Offshore", "Offshore − OIS (bp)", "Offshore", "Offshore", "VİOP − Offshore (bp)"]
    fwd, viop = page(service, u, "forward"), page(service, u, "viop")
    assert fwd["B3"]["title"].startswith("Offshore · TRY faizi (ACT/360 basit)") and fwd["B4"]["title"] == "TRY OIS · basit zero (ACT/360)"
    assert viop["B4"]["title"].startswith("Offshore · ICAP kotaları") and viop["B3"]["title"] == "TRY OIS · kotalar (ACT/365 basit)"
    assert viop["B13"]["title"] == "Offshore" and viop["B28"]["title"] == "Offshore TRY ff"
    assert fwd["chart0"]["title"] == "O/N karşılığı (360) · Offshore, OIS ve VİOP" and fwd["chart0"]["data"].get("auto") == "fit"
    # the curves' tables name no curve "ICAP" any more (only the source: "Offshore (ICAP kaynağı)", "ICAP kotaları")
    for vid, got in (("forward", fwd), ("viop", viop), ("masa", page(service, u, "masa"))):
        for pid, p in got.items():
            if p.get("hidden"):
                continue
            words = [p.get("title") or ""] + [c.get("t") or "" for row in (p.get("data") or {}).get("rows") or [] for c in row
                                              if isinstance(c, dict) and c.get("v") is None]
            assert not [w for w in words if re.search(r"\bICAP\b(?! kaynağı| kotaları| kotası|\))", w)], (vid, pid)
    assert os.path.exists(os.path.join(ROOT, "tto", "static", "js", "glossary.js"))
    with open(os.path.join(ROOT, "tto", "static", "js", "glossary.js"), encoding="utf-8") as fh:
        js = fh.read()
    assert all("['%s'" % term in js for term in ("Offshore", "FX swap ima", "XCCY", "ICAP", "OIS", "Spot", "X − OIS (bp)"))


# ============================================================================== B5: one spread rule
def test_one_spread_rule_x_minus_ois_in_whole_bp(service):
    """X − OIS (or X − Offshore), bp, whole, the side named: the same rates as before, the other way round, in bp."""
    for c in ("M", "N", "X"):
        mid = (cell(service, "VIOP!%s13" % c) + cell(service, "VIOP!%s25" % c)) / 2
        assert cell(service, "VIOP!%s18" % c) == pytest.approx((mid - cell(service, "VIOP!%s77" % c)) * 10000, abs=1e-9)
    assert cell(service, "MASA!I110") == cell(service, "VIOP!M18")                   # (Masa's VİOP summary reads the bp)
    for r in (101, 103, 110):
        e, f, h = (cell(service, "Forward!%s%d" % (c, r)) for c in "EFH")
        assert cell(service, "Forward!G%d" % r) == pytest.approx((e - f) * 10000, abs=1e-9)
        if type(h) is float:
            assert cell(service, "Forward!I%d" % r) == pytest.approx((h - f) * 10000, abs=1e-9)
    assert cell(service, "Forward!X132") == pytest.approx((cell(service, "Forward!P132") - cell(service, "Forward!W132")) * 100, abs=1e-9)
    assert cell(service, "MASA!V6") == pytest.approx((cell(service, "MASA!R6") - cell(service, "MASA!Q6")) * 10000, abs=1e-9)
    # VİOP's last price against the OIS / offshore fair forward: the rate it implies (the block's own formula, 360) − the TRY rate
    s, p, u_, d, r = (cell(service, "VIOP!M%d" % k) for k in (75, 81, 76, 74, 77))
    assert cell(service, "VIOP!M82") == pytest.approx((((p / s) * (1 + u_ * d / 360) - 1) * 360 / d - r) * 10000, rel=1e-12)
    captions = [cell(service, ref) for ref in ("VIOP!L18", "VIOP!L82", "VIOP!L95", "Forward!G100", "Forward!I100", "Forward!X131", "MASA!V5")]
    assert captions == ["VİOP mid − OIS (bp)", "VİOP son − OIS (bp)", "VİOP son − Offshore (bp)", "Offshore − OIS (bp)",
                        "VİOP − OIS (bp)", "Offshore − OIS O/N (bp)", "Offshore − OIS (bp)"]
    for ref in ("VIOP!M18", "VIOP!M82", "VIOP!M95", "Forward!G101", "Forward!X132", "MASA!V6"):
        assert re.fullmatch(r"-?[\d.]+", text(service, ref)), (ref, text(service, ref))


# ============================================================================== B14: the Forward page's helpers
def test_the_forward_page_names_its_helpers(service):
    u = service.login("K8 yardımcılar")["user"]
    fwd = page(service, u, "forward")
    dv01 = fwd["B18"]["data"]
    assert at(dv01, "P", 32)["t"] == "O/N · T/N puan" and at(dv01, "P", 33)["t"] and at(dv01, "P", 34)["t"]
    # USD_Index and the two USD OIS nodes around it ("8", "4,15 % 181", "4,28 % 273") went: USD_SOFR interpolates by itself
    assert all(cell(service, "Forward!%s" % a) is None for a in ("N38", "O38", "N39", "O39", "N40", "O40"))
    assert cell(service, "Forward!O41") > 0 and at(dv01, "N", 41)["t"] == "USD_SOFR"
    ret = fwd["B20"]["data"]
    assert [at(ret, "AB", 32)["t"], at(ret, "AC", 32)["t"], at(ret, "AA", 48)["t"]] == ["Bid (P/gün)", "Ask (P/gün)", "Valör"]
    plus = fwd["B26"]["data"]
    assert [at(plus, c, 95)["t"] for c in ("AA", "AB", "AC")] == ["RET + spread", "Bid", "Ask"]
    on = fwd["B27"]["data"]
    assert on["c"] == ["D", "E", "F", "G", "H", "I"] and at(on, "G", 100)["t"] == "Offshore − OIS (bp)"
    helper = panels(raw("30_forward.json"))["B27y"]
    assert helper["hidden"] and helper["range"] == "K99:N119"


# ============================================================================== ORANLAR's direction in colour
def test_oranlar_direction_reads_in_the_yon_colours(service):
    u = service.login("K8 yön")["user"]
    data = page(service, u, "masa")["B3"]["data"]
    seen = {}
    for r in range(6, 21):
        c = at(data, "J", r)
        if c and c.get("t") in ("RECEIVE", "PAY"):
            seen[c["t"]] = {k: c.get(k) for k in ("fg", "bg", "b", "c", "f") if c.get(k) is not None}
    assert seen.get("RECEIVE") and seen["RECEIVE"] != seen.get("PAY", {}), seen
    yon = page(service, u, "ois")["B3"]["data"]
    rec = next(at(yon, "D", r) for r in range(9, 27) if (at(yon, "D", r) or {}).get("t") == "RECEIVE")
    assert {k: rec.get(k) for k in seen["RECEIVE"]} == seen["RECEIVE"]                  # (the OIS list's YÖN, the same look)


# ============================================================================== B11: USD · FOMC in two tables
def test_usd_fomc_in_two_tables_the_scenarios_beside_the_chart(service):
    v = raw("80_usd.json")
    t, p = tabs(v), panels(v)
    assert t["fomc"]["panels"] == ["fomc", "fomc-sc", "fomc-chart", "inp"]
    mkt, sc = p["fomc"], p["fomc-sc"]
    assert mkt["range"] == "A73:AE83" and mkt["wide"] and mkt["freeze"] == 2
    shown = [c for c in mkt["cols"] if c not in ("F", "G", "I", "J")]                  # (those four: hidden until asked for)
    assert shown == ["A", "B", "C", "D", "E", "H", "K", "AA", "AB", "AC", "AD", "AE", "L", "M", "N", "O", "P", "Q"]
    assert sc["range"] == "A72:Z83" and sc["cols"] == ["B", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"] and not sc.get("wide")
    u = service.login("K8 FOMC")["user"]
    got = service.view(u, "usd")
    data = next(x for x in got["panels"] if x["id"] == "fomc-sc")["data"]
    assert [at(data, c, 72)["t"] for c in "BRST"] == ["Olasılık →", "50%", "25%", "25%"]
    assert at(data, "R", 72).get("i") and at(data, "R", 74).get("i")                    # (the probabilities, the steps: typed here)
    assert cell(service, "SOFR_FOMC!B72", book="sofr") == "Olasılık →"
    assert not any(c.get("t") == "Olasılık →" for row in next(x for x in got["panels"] if x["id"] == "fomc")["data"]["rows"] for c in row)


# ============================================================================== B12: OIS · PPK and Masa · Faiz · PPK
def test_ois_ppk_kotalar_mpc_ima_and_the_parameters_line(service):
    v = raw("20_ois.json")
    t, p = tabs(v), panels(v)
    assert t["quotes"]["panels"] == ["B3", ["B2", "B18"], "chart3", "chart4", "B5"]
    assert t["mpc"]["panels"] == ["B4", "chart0", "chart1", "B6", "B7", ["B22", "B8"]]
    assert p["B1"]["range"] == "A1:L6"
    u = service.login("K8 parametreler")["user"]
    b1 = page(service, u, "ois")["B1"]
    assert b1["title"] == "Parametreler  ·  Normalleşme Kapalı  ·  DV01/bacak 1.000 $  ·  Senaryo tabanı 1  ·  Ufuk 1/3 ay"
    assert b1["data"]["r"][0] == 2                                                      # (row 1 is the title, not a row)
    service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!F2", "value": "3000"}, {"ref": "OIS_MAIN!L2", "value": "Açık"},
                                  {"ref": "OIS_MAIN!D4", "value": "6"}])
    b1 = page(service, u, "ois")["B1"]
    assert b1["title"] == "Parametreler  ·  Normalleşme Açık  ·  DV01/bacak 3.000 $  ·  Senaryo tabanı 1  ·  Ufuk 1/6 ay"
    service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!F2", "value": ""}, {"ref": "OIS_MAIN!L2", "value": ""},
                                  {"ref": "OIS_MAIN!D4", "value": ""}])
    # the lists' "R/R Beklenen" shorter: FLY beside SPREAD on a desk screen (the browser test measures it)
    assert {cell(service, "OIS_MAIN!%s" % a) for a in ("K8", "K29", "K47", "K65", "K83", "J102", "J132", "J288")} == {"R/R Bekl."}
    m = tabs(raw("10_masa.json"))
    assert m["rates"]["panels"] == ["B13", "chart5", "B21", "chart4"]


def test_every_view_is_well_formed():
    for v in load_views():
        assert v.get("id")
