"""VİOP Target: the curve of the FRA, chosen per row ("FRA eğrisi", VIOP!Z331:Z338; ``tto/extras.py``, sheet EK_VFRA).

An FRA+bp target was priced off one curve only - the bootstrapped OIS curve of the VİOP sheet's row 104.  Each row now
chooses where its FRA comes from: the bootstrapped curve (the default: today's numbers) or one of the OIS sheet's three
PPK scenarios, listed by the names the SENARYOLAR table gives them.  Every check reads cells and compares them with what
the workbook computes elsewhere - each curve's rate between two dates is the desk sheet's own date-to-date block (MASA
"Tarih arası faiz", rows 62-68) - or with Excel's own values of the file's target rows."""
import datetime as dt
import os

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto.config import Settings
from tto.marketdata.base import bdp_key
from tto.service import Service
from tto.views import load_views
from tto.xl.engine import Clock
from tto.xl.model import Model, parse_a1
from tto.xl.values import date_to_serial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOT, S1, S2, S3 = "Bootstrap (piyasa)", "S1 · Baz", "S2 · Hawkish", "S3 · Dovish"
#: the desk sheet's date-to-date block: the row of each curve (D: the period's ACT/360 simple rate)
DESK = {BOOT: 67, S1: 63, S2: 64, S3: 65}
#: the scenario steps (bp) a user types at the first meeting (10.12.2026), so that the three scenarios differ
STEPS = {"OIS_MAIN!U10": "-50", "OIS_MAIN!V10": "100", "OIS_MAIN!W10": "-250"}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()])
    assert res["errors"] == [], res["errors"]


def target(r, near, far, side="SHORT", kind="FRA+bp", value="-150", curve=None):
    """The inputs of target row ``r`` (``curve``: the FRA's curve; None leaves it as it is)."""
    out = {"VIOP!L%d" % r: near, "VIOP!M%d" % r: far, "VIOP!N%d" % r: side, "VIOP!O%d" % r: kind, "VIOP!P%d" % r: value}
    if curve is not None:
        out["VIOP!Z%d" % r] = curve
    return out


def helper_row(r):
    return ex.VFRA_FIRST + r - ex.VFRA_ROWS[0]


def desk_rate(svc, user, r, curve):
    """The desk sheet's own rate of ``curve`` between the dates of target row ``r`` (its block's dates set to them)."""
    h = helper_row(r)
    near, far = cell(svc, "EK_VFRA!F%d" % h, user), cell(svc, "EK_VFRA!G%d" % h, user)
    put(svc, user, {"MASA!C60": "%d" % near, "MASA!E60": "%d" % far})
    return cell(svc, "MASA!D%d" % DESK[curve], user)


def page_cells(svc, user, view, panel, r):
    """{column: the cell as the page draws it} of row ``r`` of a table of a page."""
    data = next(p for p in svc.view(user, view)["panels"] if p["id"] == panel)["data"]
    return dict(zip(data["c"], data["rows"][data["r"].index(r)]))


# ============================================================================== the choice
def test_the_choice_sits_beside_the_target_type_as_a_list_of_the_scenarios(svc):
    """A drop-down "FRA eğrisi" right after "Hedef tipi": the bootstrapped curve and S1 / S2 / S3 with the names of the
    SENARYOLAR table, read from a range of EK_VFRA (as the target's contracts are read from L97:X97).  Personal, as the
    row's other inputs are."""
    viop = next(v for v in load_views() if v["id"] == "viop")
    scope = {i["range"]: (i["scope"], i["kind"]) for i in viop["inputs"]}
    assert scope["Z331:Z338"] == ("user", "list")
    assert {scope[r][0] for r in ("L331:L338", "M331:M338", "N331:N338", "O331:O338", "P331:P338")} == {"user"}
    u = svc.login("FRA eğrisi liste")["user"]
    page = svc.view(u, "viop")
    table = next(p for p in page["panels"] if p["id"] == "B33")["data"]
    assert table["c"] == ["K", "L", "M", "N", "O", "Z", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y"]
    head = [c.get("t") for c in table["rows"][0]]
    assert head[4:7] == ["Hedef tipi", "FRA eğrisi", "Hedef değer"] and head[13] == "OIS FRA · " + BOOT
    for r in range(331, 339):
        z = page_cells(svc, u, "viop", "B33", r)["Z"]
        assert z["i"] == "u" and z["o"] == [BOOT, S1, S2, S3], r
    info = svc.cell_info(u, "tto", "VIOP!Z331")["cell"]
    assert info["o"] == [BOOT, S1, S2, S3] and info["t"] == ""                        # an empty row: nothing to show
    assert {"sqref": "Z331:Z338", "type": "list", "formula1": "EK_VFRA!$A$3:$A$6"} in svc.books["tto"].model.sheet("VIOP").validations
    # the helpers are among the page's helper tables
    assert next(p for p in viop["panels"] if p["id"] == "VF1")["hidden"] is True


def test_today_the_ois_fra_is_the_bootstrapped_curve_and_stays_the_default(svc):
    """The OIS FRA of the target table was the bootstrapped curve's (row 104 reads BOOT_LNDF): the desk sheet's
    "Bootstrap" rate between the same dates, not its MPC-implied path.  Left alone, the choice is that curve, and the
    file's own six target rows give Excel's own values in every column."""
    raw = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    assert "BOOT_LNDF" in ex.formula_of(raw, "VIOP", "M104") and ex.viop_target_fra(331) in ex.formula_of(raw, "VIOP", "W331")
    sh = raw.sheet("VIOP")
    u = svc.login("FRA eğrisi bugün")["user"]
    try:
        rows = {}
        for r in range(331, 339):
            typed = [sh.consts.get(parse_a1("%s%d" % (c, r))) for c in "LMNOP"]
            if typed[0] is not None:
                rows[r] = typed
                put(svc, u, target(r, typed[0], typed[1], typed[2], typed[3], "%g" % typed[4]))
        assert len(rows) == 6
        for r in rows:
            assert cell(svc, "VIOP!Z%d" % r, u) == BOOT
            for c in "QRSTUVWXY":
                excel, got = sh.cached[parse_a1("%s%d" % (c, r))], cell(svc, "VIOP!%s%d" % (c, r), u)
                assert got == pytest.approx(excel, rel=1e-12), (c, r)
            # the sheet's own formula, word for word on EK_VFRA: OIS FRA is exactly its value
            assert cell(svc, "VIOP!W%d" % r, u) == cell(svc, "EK_VFRA!P%d" % helper_row(r), u)
        assert cell(svc, "VIOP!W330", u) == "OIS FRA · " + BOOT
        assert cell(svc, "VIOP!W331", u) == pytest.approx(desk_rate(svc, u, 331, BOOT), rel=1e-12)
        assert abs(cell(svc, "VIOP!W331", u) - cell(svc, "MASA!D62", u)) > 1e-5             # not the MPC-implied path
        assert cell(svc, "VIOP!AA331", u) == "OIS FRA, %s eğrisinden" % BOOT
    finally:
        svc.reset_inputs(u, "tto")


@pytest.mark.parametrize("curve", [BOOT, S1, S2, S3])
def test_each_curve_gives_the_fra_the_desk_sheet_gives_between_the_two_dates(svc, curve):
    """With the three scenarios set apart (a different step at the first meeting), each choice makes OIS FRA the desk
    sheet's own rate of that curve between the row's dates, the target rate OIS FRA + bp, and what is built on the target
    rate follows it: the far limit price, the spread price, target − market (the near limit is the near leg's price)."""
    u = svc.login("FRA eğrisi " + curve[:2])["user"]
    try:
        put(svc, u, dict(STEPS, **target(331, "Spot", "31.12.2026"), **target(332, "31.12.2026", "26.02.2027", side="LONG")))
        boot = {(r, c): cell(svc, "VIOP!%s%d" % (c, r), u) for r in (331, 332) for c in "QRSTUVW"}
        put(svc, u, {"VIOP!Z331": curve, "VIOP!Z332": curve})
        for r in (331, 332):
            w, q = cell(svc, "VIOP!W%d" % r, u), cell(svc, "VIOP!Q%d" % r, u)
            assert w == pytest.approx(desk_rate(svc, u, r, curve), rel=1e-12), r
            assert q == pytest.approx(w - 0.015, rel=1e-12)
            g = cell(svc, "VIOP!Y%d" % r, u)
            assert cell(svc, "VIOP!R%d" % r, u) == boot[(r, "R")] and cell(svc, "VIOP!U%d" % r, u) == boot[(r, "U")]
            assert cell(svc, "VIOP!S%d" % r, u) == pytest.approx(boot[(r, "S")] * (1 + q * g / 360) / (1 + boot[(r, "Q")] * g / 360), rel=1e-12)
            assert cell(svc, "VIOP!T%d" % r, u) == pytest.approx(cell(svc, "VIOP!S%d" % r, u) - boot[(r, "R")], rel=1e-12)
            assert cell(svc, "VIOP!V%d" % r, u) == pytest.approx((q - boot[(r, "U")]) * 10000, rel=1e-9)
            # the desk page's strip follows: the target rate and, for a scenario, the curve beside the target
            assert cell(svc, "MASA!T%d" % (r - 210), u) == q
            assert cell(svc, "MASA!S%d" % (r - 210), u) == "FRA+bp -150" + ("" if curve == BOOT else " · " + curve)
        if curve == BOOT:
            assert all(cell(svc, "VIOP!%s%d" % (c, r), u) == boot[(r, c)] for r in (331, 332) for c in "QRSTUVW")
        else:
            assert abs(cell(svc, "VIOP!W331", u) - boot[(331, "W")]) > 1e-5
        # the column says its curve: in the caption (one curve for both rows), and each cell in its tooltip
        assert cell(svc, "VIOP!W330", u) == "OIS FRA · " + curve
        cells = page_cells(svc, u, "viop", "B33", 331)
        assert cells["Z"]["t"] == curve and cells["W"]["tip"].startswith("OIS FRA, %s eğrisinden" % curve)
        assert cells["Q"]["tip"] == "Hedef faiz = OIS FRA (%s) − 150 bp" % curve
    finally:
        svc.reset_inputs(u, "tto")


def test_rows_on_different_curves_say_so_and_the_scenarios_keep_their_order(svc):
    u = svc.login("FRA eğrisi karışık")["user"]
    try:
        put(svc, u, dict(STEPS, **target(332, "31.12.2026", "26.02.2027", curve=S2), **target(333, "31.12.2026", "26.02.2027", curve=S3)))
        assert cell(svc, "VIOP!W330", u) == "OIS FRA · eğri satıra göre"
        h2, h3 = helper_row(332), helper_row(333)
        fra = {name: cell(svc, "EK_VFRA!%s%d" % (col, h2), u) for name, col in (("boot", "P"), ("s1", "Q"), ("s2", "R"), ("s3", "S"))}
        assert fra["s2"] > fra["s1"] > fra["s3"]                       # +100 / −50 / −250 bp at the first meeting
        assert cell(svc, "VIOP!W332", u) == fra["s2"] and cell(svc, "VIOP!W333", u) == cell(svc, "EK_VFRA!S%d" % h3, u) == fra["s3"]
        tip = page_cells(svc, u, "viop", "B33", 332)["W"]["tip"]
        assert tip == "OIS FRA, %s eğrisinden (Bootstrap (piyasa): %s)" % (S2, ("%.2f%%" % (fra["boot"] * 100)).replace(".", ","))
    finally:
        svc.reset_inputs(u, "tto")


def test_the_names_follow_the_scenario_table(svc):
    """The scenarios are renamed on the OIS page (SENARYOLAR, the user's own names): the list, the caption, the tooltips and
    the desk strip take the new name; a row chosen before keeps its scenario (the choice is read by its code) - its cell
    keeps the old text, as an Excel list does, and says that the name changed."""
    u = svc.login("FRA eğrisi ad")["user"]
    try:
        put(svc, u, dict(STEPS, **target(331, "Spot", "31.12.2026", curve=S2)))
        s2 = cell(svc, "VIOP!W331", u)
        put(svc, u, {"OIS_MAIN!P4": "Şahin"})
        assert svc.cell_info(u, "tto", "VIOP!Z331")["cell"]["o"] == [BOOT, S1, "S2 · Şahin", S3]
        assert cell(svc, "VIOP!W331", u) == s2 and cell(svc, "EK_VFRA!D%d" % helper_row(331), u) == 3.0
        assert cell(svc, "VIOP!Z331", u) == S2                                              # the text it was chosen with
        assert cell(svc, "VIOP!W330", u) == "OIS FRA · S2 · Şahin" and cell(svc, "MASA!S121", u) == "FRA+bp -150 · S2 · Şahin"
        cells = page_cells(svc, u, "viop", "B33", 331)
        assert cells["W"]["tip"].startswith("OIS FRA, S2 · Şahin eğrisinden") and "(S2 · Şahin)" in cells["Q"]["tip"]
        assert cells["Z"]["tip"] == "Senaryonun adı değişti: seçim yine S2, şimdiki adıyla S2 · Şahin (listeden yeniden seçilebilir)"
        put(svc, u, {"VIOP!Z331": "S2 · Şahin"})                                            # picked again: the new text
        assert cell(svc, "VIOP!Z331", u) == "S2 · Şahin" and cell(svc, "VIOP!W331", u) == s2
        assert "tip" not in page_cells(svc, u, "viop", "B33", 331)["Z"]
        assert cell(svc, "OIS_MAIN!P4") == "Hawkish" and cell(svc, "EK_VFRA!A5") == S2       # the others keep theirs
    finally:
        svc.reset_inputs(u, "tto")


def test_other_target_types_are_not_touched_by_the_curve(svc):
    """FXswap+bp and Faiz % rows do not read the FRA: whatever curve is chosen they keep every number (OIS FRA on the
    bootstrapped curve), and say that the choice does nothing there.  A row without a type is priced as FRA+bp by the
    workbook's own formula: the curve applies to it."""
    u = svc.login("FRA eğrisi diğer")["user"]
    try:
        put(svc, u, dict(STEPS, **target(331, "Spot", "31.12.2026", kind="FXswap+bp"), **target(332, "Spot", "31.12.2026", kind="Faiz %", value="34"),
                         **target(333, "Spot", "31.12.2026", kind="")))
        assert [cell(svc, "VIOP!Z%d" % r, u) for r in (331, 332, 333)] == ["", "", BOOT]       # the default where it applies
        before = {(r, c): cell(svc, "VIOP!%s%d" % (c, r), u) for r in (331, 332) for c in "QRSTUVWXY"}
        put(svc, u, {"VIOP!Z331": S2, "VIOP!Z332": S2, "VIOP!Z333": S2})
        for (r, c), v in before.items():
            assert cell(svc, "VIOP!%s%d" % (c, r), u) == v, (r, c)
        assert cell(svc, "VIOP!Q332", u) == 0.34
        for r, kind in ((331, "FXswap+bp"), (332, "Faiz %")):
            cells = page_cells(svc, u, "viop", "B33", r)
            assert cells["Z"]["tip"] == "Hedef tipi %s: FRA eğrisi bu satırda etkisiz (yalnız FRA+bp satırında geçerli)" % kind
            assert cells["W"]["tip"] == "OIS FRA, %s eğrisinden - seçilen FRA eğrisi (%s) yalnız FRA+bp satırında geçerli" % (BOOT, S2)
            assert "tip" not in cells["Q"] and cell(svc, "MASA!S%d" % (r - 210), u) == "%s %s" % (kind, "-150" if r == 331 else "34")
        assert cell(svc, "VIOP!W333", u) == cell(svc, "EK_VFRA!R%d" % helper_row(333), u) != cell(svc, "VIOP!W331", u)
        assert cell(svc, "VIOP!Q333", u) == pytest.approx(cell(svc, "VIOP!W333", u) - 0.015, rel=1e-12)
        assert cell(svc, "VIOP!W330", u) == "OIS FRA · eğri satıra göre"
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== whose it is, and where it goes
def test_the_choice_is_personal_kept_and_reset_with_the_users_inputs(svc):
    """The choice is the user's own (stored with their inputs: it survives a reload), "Girdilerimi sıfırla" and Delete take
    it back to the bootstrapped curve, and the cell takes a scenario of its list only - typed in any case, never a
    formula."""
    a, b = svc.login("FRA eğrisi Ayşe")["user"], svc.login("FRA eğrisi Mehmet")["user"]
    try:
        row = dict(STEPS, **target(331, "Spot", "31.12.2026"))
        put(svc, a, dict(row, **{"VIOP!Z331": "s3 · dovish"}))                    # (the list's item, whatever the case)
        put(svc, b, row)
        assert cell(svc, "VIOP!Z331", a) == S3 and cell(svc, "VIOP!Z331", b) == BOOT and cell(svc, "VIOP!Z331") == ""
        assert svc.store.user_inputs(a, "tto")[("tto", "VIOP!Z331")] == S3 and ("tto", "VIOP!Z331") not in svc.store.user_inputs(b, "tto")
        s3 = cell(svc, "VIOP!W331", a)
        assert s3 == cell(svc, "EK_VFRA!S%d" % helper_row(331), a) != cell(svc, "VIOP!W331", b)
        assert next(x for x in svc.my_inputs(a)["inputs"] if x["ref"] == "VIOP!Z331")["value"] == S3
        refused = svc.set_inputs(a, "tto", [{"ref": "VIOP!Z331", "value": "=EK_VFRA!A5"}])["errors"]
        assert refused == ["VIOP!Z331: bu hücre listeden bir değer alır (%s): formül yazılamaz" % ", ".join([BOOT, S1, S2, S3])]
        assert "listede yok" in svc.set_inputs(a, "tto", [{"ref": "VIOP!Z331", "value": "S4"}])["errors"][0]
        assert cell(svc, "VIOP!Z331", a) == S3 and cell(svc, "VIOP!W331", a) == s3
        put(svc, a, {"VIOP!Z331": ""})                                                       # Delete: the default again
        assert cell(svc, "VIOP!Z331", a) == BOOT and cell(svc, "VIOP!W331", a) == cell(svc, "VIOP!W331", b)
        put(svc, a, {"VIOP!Z331": S3})
        assert svc.reset_inputs(a, "tto")["reset"] >= 1                                      # "Girdilerimi sıfırla"
        assert cell(svc, "VIOP!Z331", a) == "" and ("tto", "VIOP!Z331") not in svc.store.user_inputs(a, "tto")
    finally:
        svc.reset_inputs(a, "tto")
        svc.reset_inputs(b, "tto")


def test_a_saved_scenario_takes_the_choice_along(svc):
    u = svc.login("FRA eğrisi senaryo")["user"]
    try:
        put(svc, u, dict(STEPS, **target(334, "31.12.2026", "26.02.2027", curve=S3)))
        s3 = cell(svc, "VIOP!W334", u)
        svc.save_scenario(u, "s3 hedefi")
        svc.reset_inputs(u, "tto")
        assert cell(svc, "VIOP!Z334", u) == "" and cell(svc, "VIOP!W334", u) == ""
        assert svc.load_scenario(u, "s3 hedefi")["cells"] == 9
        assert cell(svc, "VIOP!Z334", u) == S3 and cell(svc, "VIOP!W334", u) == s3 == cell(svc, "EK_VFRA!S%d" % helper_row(334), u)
    finally:
        svc.reset_inputs(u, "tto")
        svc.delete_scenario(u, "s3 hedefi")


def test_the_rows_say_their_curve_wherever_they_are_shown(svc):
    """The target rows are on the VİOP page, on the desk page (the inputs strip above its TARGET summary, and the summary)
    and in any launchpad: the choice is in each of them, typed in either place, and the OIS FRA cell says its curve."""
    u = svc.login("FRA eğrisi her yerde")["user"]
    try:
        put(svc, u, dict(STEPS, **target(331, "Spot", "31.12.2026")))
        strip = next(p for p in svc.view(u, "masa")["panels"] if p["id"] == "B17D")["data"]
        assert strip["c"] == ["L", "M", "N", "O", "Z", "P"] and strip["rows"][0][4]["t"] == "FRA eğrisi"
        z = strip["rows"][strip["r"].index(331)][4]
        assert z["i"] == "u" and z["t"] == BOOT and z["o"] == [BOOT, S1, S2, S3]
        put(svc, u, {"VIOP!Z331": S1})                                                         # typed on the desk page
        assert page_cells(svc, u, "masa", "B17", 121)["S"]["t"] == "FRA+bp -150 · " + S1
        assert page_cells(svc, u, "viop", "B33", 331)["Z"]["t"] == S1
        got = svc.panels(u, [{"view": "viop", "panel": "B33"}, {"view": "viop", "panel": "B33", "key": "part", "cols": ["L", "M", "Z", "W"]},
                             {"view": "masa", "panel": "B17D"}])["panels"]
        part = got["part"]["entry"]["data"]
        assert part["c"] == ["L", "M", "Z", "W"]
        row = dict(zip(part["c"], part["rows"][part["r"].index(331)]))
        assert row["Z"]["t"] == S1 and row["W"]["tip"].startswith("OIS FRA, %s eğrisinden" % S1)
        assert got["viop/B33"]["entry"]["data"]["c"][5] == "Z" and got["masa/B17D"]["entry"]["data"]["c"][4] == "Z"
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== the desk's own changes: meetings, contracts
def test_the_curve_follows_its_scenario_through_a_change_of_the_meeting_calendar(tmp_path):
    """The scenario steps sit on the meeting rows of the OIS sheet and move with their meeting when the calendar changes:
    a row priced off S2 still takes the S2 curve - the desk sheet's own, as it stands after the change - and the same
    numbers come back with the calendar."""
    svc = make_service(tmp_path)
    try:
        u = svc.login("FRA eğrisi takvim")["user"]
        put(svc, u, dict({"OIS_MAIN!U11": "0", "OIS_MAIN!V11": "200", "OIS_MAIN!W11": "-200"},           # the 21.01.2027 meeting
                         **target(331, "31.12.2026", "26.02.2027", curve=S2)))
        h = svc.history
        start = h.meetings()
        assert "2027-01-21" in start and cell(svc, "OIS_MAIN!P11") == float(date_to_serial(dt.date(2027, 1, 21)))
        first = cell(svc, "VIOP!W331", u)
        assert first == pytest.approx(desk_rate(svc, u, 331, S2), rel=1e-12)
        row = helper_row(331)
        fra = lambda col: cell(svc, "EK_VFRA!%s%d" % (col, row), u)                    # noqa: E731
        assert fra("R") > fra("Q") > fra("S")
        res = h.set_calendar(u, sorted(start[:-1] + ["2027-01-07"]))                  # a meeting put in before it
        assert res["moved"] == 3 and cell(svc, "OIS_MAIN!P12") == float(date_to_serial(dt.date(2027, 1, 21)))
        assert [cell(svc, "OIS_MAIN!%s12" % c, u) for c in "UVW"] == [0.0, 200.0, -200.0]        # the steps went with it
        assert [cell(svc, "OIS_MAIN!%s11" % c, u) for c in "UVW"] == [None, None, None]
        assert cell(svc, "VIOP!Z331", u) == S2 and cell(svc, "EK_VFRA!D%d" % row, u) == 3.0
        moved = cell(svc, "VIOP!W331", u)
        assert moved == fra("R") == pytest.approx(desk_rate(svc, u, 331, S2), rel=1e-12) and fra("R") > fra("Q") > fra("S")
        h.set_calendar(u, start)
        assert cell(svc, "OIS_MAIN!V11", u) == 200.0 and cell(svc, "VIOP!W331", u) == first
    finally:
        svc.stop()


class _Live(object):
    """A connected Bloomberg answering from a dictionary (the workbook's values of its day), with the day of the clock
    ours to move: the VİOP contracts roll by themselves and Bloomberg answers for whichever contract a cell names."""

    def __init__(self, svc_replay, tmp_path):
        from test_extras import _Direct
        today = svc_replay.books["tto"].engine.clock.today()
        snapshot = {k: v for k, v in svc_replay.provider.snapshot.items() if k[0] != "BFX"}
        snapshot.update({bdp_key("A1X7 Curncy", "LAST_TRADEABLE_DT"): "30.11.2027", bdp_key("A1X7 Curncy", "BID"): 66.0,
                         bdp_key("A1X7 Curncy", "ASK"): 66.1})                     # the contract the roll lists next
        self.clock = Clock(today + 0.5)
        self.clock.today = lambda: float(today)
        self.provider = _Direct(snapshot)
        self.svc = Service(Settings(data_dir=str(tmp_path), mode="live", history=False), provider=self.provider, clock=self.clock)

    def on(self, day, settles):
        """A day of the clock, and Bloomberg's USDTRY spot date for it (the VİOP sheet's spot)."""
        key = bdp_key("USDTRY Curncy", "SETTLE_DT")
        self.clock.today = (lambda x=float(date_to_serial(day)): x)
        self.provider.snapshot[key] = settles
        self.svc.et.call(self.svc._apply_market, [key])
        self.svc.et.call(self.svc.books["tto"].engine.clock_tick)


def test_a_contract_that_rolls_off_leaves_its_rows_marked_and_the_others_on_their_contracts(svc, tmp_path):
    """The VİOP contracts roll by themselves (the front trades until its expiry day; the list L97:X97 shifts the day after).
    A target row keeps its contracts by their dates: one still listed is the same contract after the roll - same dates, its
    curve, the desk sheet's rate of that curve.  A row whose contract expired is left without numbers and says why (its
    tooltips, the desk strip); on the expiry day a period that does not end after the OIS spot date says it too (the
    sheet's own FRA is 0 there)."""
    live = _Live(svc, tmp_path)
    s = live.svc
    try:
        u = s.login("FRA eğrisi rol")["user"]
        put(s, u, dict(STEPS, **target(331, "31.12.2026", "26.02.2027", curve=S2), **target(332, "Spot", "30.11.2026", side="LONG", curve=S2)))
        listed = lambda: [x for x in (cell(s, "VIOP!%s97" % c, u) for c in "LMNOPQRSTUVWX")]     # noqa: E731
        assert listed()[:3] == ["Spot", "30.11.2026", "31.12.2026"]
        dates = [cell(s, "EK_VFRA!%s%d" % (c, helper_row(331)), u) for c in "FG"]
        assert cell(s, "EK_VFRA!U10", u) == cell(s, "EK_VFRA!U11", u) == "" and isinstance(cell(s, "VIOP!W332", u), float)
        # the expiry day of the front: still listed, but its period ends before the OIS spot date
        live.on(dt.date(2026, 11, 30), "1.12.2026")
        assert listed()[1] == "30.11.2026" and cell(s, "VIOP!Y332", u) == -1.0
        why = "Geçersiz: dönem OIS spot valöründen (01.12.2026) sonra bitmiyor (uzak kontratın vade günü ya da geçmiş): OIS FRA ve hedef faiz anlamsız"
        assert cell(s, "EK_VFRA!U11", u) == why and cell(s, "MASA!S122", u) == "FRA+bp -150 · geçersiz"
        cells = page_cells(s, u, "viop", "B33", 332)
        assert cells["W"]["tip"] == cells["Q"]["tip"] == cells["Z"]["tip"] == why
        # the day after: the contracts roll, the list shifts by one
        live.on(dt.date(2026, 12, 1), "2.12.2026")
        assert cell(s, "VIOP!L1") == "A1Z6 Curncy" and listed()[:3] == ["Spot", "31.12.2026", "29.01.2027"] and listed()[-1] == "30.11.2027"
        assert [cell(s, "EK_VFRA!%s%d" % (c, helper_row(331)), u) for c in "FG"] == dates               # the same contracts
        assert cell(s, "EK_VFRA!D10", u) == 3.0 and cell(s, "VIOP!W331", u) == cell(s, "EK_VFRA!R10", u)
        assert cell(s, "VIOP!W331", u) == pytest.approx(desk_rate(s, u, 331, S2), rel=1e-12)
        assert cell(s, "EK_VFRA!U10", u) == "" and cell(s, "MASA!S121", u) == "FRA+bp -150 · " + S2
        # the expired one: no number at all, and why
        assert [cell(s, "VIOP!%s332" % c, u) for c in "QRSTUVWXY"] == [""] * 9 and cell(s, "MASA!T122", u) == ""
        gone = ("Geçersiz: uzak kontrat 30.11.2026 VİOP kontrat listesinde yok (vadesi geçmiş olabilir): satır hesaplanmıyor, "
                "kontratı listeden yeniden seçin")
        assert cell(s, "EK_VFRA!U11", u) == gone and cell(s, "MASA!S122", u) == "FRA+bp -150 · geçersiz"
        cells = page_cells(s, u, "viop", "B33", 332)
        assert cells["W"]["tip"] == cells["Z"]["tip"] == gone and cells["Z"]["t"] == S2
        assert cell(s, "VIOP!W330", u) == "OIS FRA · " + S2                                 # (only the row still priced)
    finally:
        s.stop()
