"""Masa → Genel bakış: ORANLAR and O/N EŞLENİKLERİ past 2Y (``tto/extras.py``: ``MASA_OFF_NAME``, ``MASA_CHART_NAME``).

The desk, 26.11.2026: "Masa sayfasında offshore'un da 2y sonrasını zero ve on karşılıkta göstermemişiz".  ORANLAR's 3Y /
5Y / 7Y / 10Y rows held the workbook's "" in ICAP (offshore) and OIS zero.  They read each curve's own zero rate now, as
the 2Y row does through the Forward sheet's comparison table (Forward!AC137 / AD137):

* ICAP - the XCCY bootstrap's "Zero Rate" (Forward!H127 / H129 / H131 / H134): (1/DF − 1)·360/days over the XCCY ticker's
  days from the USDTRY spot (Forward!G19 / G21 / K131 / K134);
* OIS zero - Motor's "Zero simple 360" at its 36 / 60 / 84 / 120-month node (Motor!M102 / M110 / M118 / M130): the same,
  over the days from the OIS spot.

O/N EŞLENİKLERİ reads the offshore O/N of the same discount factors (Forward!E112 / E114 / E116 / E119) and did so
already.  A node the XCCY curve lacks stays blank - never an OIS number.  The replay file has TRYSAQ6-10 as #N/A (its 7Y /
10Y offshore are blank there); a user's own values over those quotes stand for the desk, whose history has them.
"""
import math
import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.tokenizer import index_to_col

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: (MASA's row, tenor, the XCCY zero rate on the Forward sheet, Motor's row of the node): 3Y, 5Y, 7Y, 10Y
ROWS = ex.MASA_OFF_ROWS
#: the days each XCCY zero rate counts (the XCCY ticker's DAYS_TO_MTY; 6Y-10Y counted from the USDTRY spot without one)
OFF_DAYS = {"3Y": "Forward!G19", "5Y": "Forward!G21", "7Y": "Forward!K131", "10Y": "Forward!K134"}
#: the tenor's row of the Forward sheet's O/N block (E offshore O/N, F OIS O/N, K OIS days, L OIS ln DF) and of the
#: offshore curve's node table (AK days, AM ln DF)
ON_ROW = {"3Y": 112, "5Y": 114, "7Y": 116, "10Y": 119}
OFF_NODE = {"3Y": 136, "5Y": 138, "7Y": 140, "10Y": 143}
#: made-up XCCY mids (%) typed over TRYSAQ6-10 (Forward!E130:E134, #N/A in the replay file): the desk's case
XCCY_6_10 = {"Forward!E130": 39.0, "Forward!E131": 38.5, "Forward!E132": 38.0, "Forward!E133": 37.5, "Forward!E134": 37.0}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def num(v):
    return type(v) is float


def masa(svc, col, r, user=None):
    return cell(svc, "MASA!%s%d" % (col, r), user)


def typed(svc, name, values):
    """A user with their own values over workbook cells ("Elle değer")."""
    user = svc.login(name)["user"]
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": v} for ref, v in values.items()], allow_adhoc=True)
    assert res["errors"] == [], res["errors"]
    return user


def chart(svc, pid, user=None):
    return next(p["data"] for p in svc.view(user, "masa")["panels"] if p["id"] == pid)


def series(data):
    return {s["name"]: s["data"] for s in data["series"]}


def test_icap_and_ois_zero_after_2y_are_each_curves_own_zero_rate(svc):
    """Every row reads its curve's zero rate where the curve is bootstrapped - by hand from its discount factor and days,
    and on the curve's node table (the offshore curve Forward!AK:AM, the OIS curve's ln DF as the O/N block reads
    ``BOOT_GUN`` / ``BOOT_LNDF``).  The two count different days: offshore from the USDTRY spot to the XCCY ticker's
    maturity, OIS from the OIS spot to Motor's node.  The 2Y row reads the same two columns."""
    assert masa(svc, "F", 16) == pytest.approx(cell(svc, "Forward!H126"), rel=1e-14)
    assert masa(svc, "G", 16) == pytest.approx(cell(svc, "Motor!M98"), rel=1e-14)
    for r, tenor, zero, m in ROWS:
        f, g, l = masa(svc, "F", r), masa(svc, "G", r), masa(svc, "L", r)
        assert svc.cell_info(None, "tto", "MASA!F%d" % r)["formula"] == '=IFERROR(Forward!$%s$%s,"")' % (zero[0], zero[1:])
        assert svc.cell_info(None, "tto", "MASA!G%d" % r)["formula"] == '=IFERROR(Motor!$M$%d,"")' % m
        # OIS: Motor's node - its discount factor, its days from the OIS spot; the O/N block's ln DF at the same days
        df, days = cell(svc, "Motor!G%d" % m), cell(svc, "Motor!C%d" % m)
        assert num(g) and g == cell(svc, "Motor!M%d" % m) == pytest.approx((1 / df - 1) * 360 / days, rel=1e-14)
        k = ON_ROW[tenor]
        assert cell(svc, "Forward!K%d" % k) == days
        assert g == pytest.approx((math.exp(-cell(svc, "Forward!L%d" % k)) - 1) * 360 / days, rel=1e-12)
        # offshore: the XCCY bootstrap - its discount factor over the XCCY ticker's days from the USDTRY spot
        xdf, xdays = cell(svc, "Forward!G%s" % zero[1:]), cell(svc, OFF_DAYS[tenor])
        assert svc.cell_info(None, "tto", "Forward!" + zero)["formula"].replace("$", "").endswith(OFF_DAYS[tenor][8:])
        assert num(xdays) and cell(svc, "Forward!AK%d" % OFF_NODE[tenor]) == xdays
        if tenor in ("3Y", "5Y"):                                    # (the replay file prices TRYSAQ1-5)
            assert num(f) and f == cell(svc, "Forward!" + zero) == pytest.approx((1 / xdf - 1) * 360 / xdays, rel=1e-14)
            assert f == pytest.approx((math.exp(-cell(svc, "Forward!AM%d" % OFF_NODE[tenor])) - 1) * 360 / xdays, rel=1e-12)
            assert l == pytest.approx((f - g) * 10000, rel=1e-12)
        else:                                                        # TRYSAQ6-10 #N/A: no node, no number
            assert not num(xdf) and f == "" and l == ""
        # RET and VİOP have no quotes there: blank, and their differences too
        assert [masa(svc, c, r) for c in "DEHKM"] == [""] * 5


def test_on_equivalents_after_2y_read_the_same_discount_factors(svc):
    """O/N EŞLENİKLERİ: offshore O/N at every tenor the XCCY curve has, from the discount factor and days its ICAP zero
    reads - so a row's zero and O/N are one discount factor: 1 + zero·d/360 = (1 + O/N/360)^d, on each curve."""
    for r, tenor, zero, m in ROWS:
        q, on, v = masa(svc, "Q", r), masa(svc, "R", r), masa(svc, "V", r)
        k = ON_ROW[tenor]
        assert num(q) and q == cell(svc, "Forward!F%d" % k)
        days = cell(svc, "Motor!C%d" % m)
        assert 1 + masa(svc, "G", r) * days / 360 == pytest.approx((1 + q / 360) ** days, rel=1e-12)
        if tenor in ("3Y", "5Y"):
            xdf, xdays = cell(svc, "Forward!G%s" % zero[1:]), cell(svc, OFF_DAYS[tenor])
            assert on == cell(svc, "Forward!E%d" % k) == pytest.approx(360 * ((1 / xdf) ** (1 / xdays) - 1), rel=1e-12)
            assert 1 + masa(svc, "F", r) * xdays / 360 == pytest.approx((1 + on / 360) ** xdays, rel=1e-12)
            assert v == pytest.approx((q - on) * 10000, rel=1e-12)
        else:
            assert on == "" and v == ""


def test_the_desks_case_every_xccy_tenor_priced(svc):
    """With TRYSAQ6-10 priced (the desk's history has them every day; the replay file does not), 7Y and 10Y show their
    XCCY zero rate, its difference to OIS and the offshore O/N - each from the XCCY bootstrap, over the days K131 / K134
    count; OIS stays as it was."""
    user = typed(svc, "Masa offshore 6-10Y", XCCY_6_10)
    for r, tenor, zero, m in ROWS:
        f, g, on = masa(svc, "F", r, user), masa(svc, "G", r, user), masa(svc, "R", r, user)
        xdf, xdays = cell(svc, "Forward!G%s" % zero[1:], user), cell(svc, OFF_DAYS[tenor], user)
        assert num(f) and f == cell(svc, "Forward!" + zero, user) == pytest.approx((1 / xdf - 1) * 360 / xdays, rel=1e-14)
        assert masa(svc, "L", r, user) == pytest.approx((f - g) * 10000, rel=1e-12)
        assert on == cell(svc, "Forward!E%d" % ON_ROW[tenor], user) == pytest.approx(360 * ((1 / xdf) ** (1 / xdays) - 1), rel=1e-12)
        assert masa(svc, "V", r, user) == pytest.approx((masa(svc, "Q", r, user) - on) * 10000, rel=1e-12)
        assert g == masa(svc, "G", r) and masa(svc, "Q", r, user) == masa(svc, "Q", r)     # (OIS: nothing to do with it)
        if tenor in ("3Y", "5Y"):
            assert f == masa(svc, "F", r)                            # (the nodes before 6Y are as they were)
    # the charts draw them: ICAP and the offshore O/N to 10Y
    icap, on_off = series(chart(svc, "chart0", user))["ICAP"], series(chart(svc, "chart1", user))["Offshore O/N"]
    assert icap[11:] == [masa(svc, "F", r, user) for r in (17, 18, 19, 20)]
    assert on_off[11:] == [masa(svc, "R", r, user) for r in (17, 18, 19, 20)]


def test_a_missing_xccy_node_stays_blank_never_ois(svc):
    """A tenor whose XCCY node cannot be bootstrapped - its TRYSAQ, or one before it, without a price (here TRYSAQ3's mid
    typed away) - shows no offshore zero, no ICAP − OIS, no offshore O/N and no OIS − Off: blank, not OIS.  The OIS
    columns and the 2Y row (TRYSAQ1-2) are untouched."""
    user = typed(svc, "Masa offshore 3Y yok", {"Forward!E127": "yok"})
    for r, tenor, _, _ in ROWS:
        assert [masa(svc, c, r, user) for c in "FLRV"] == ["", "", "", ""], tenor
        assert masa(svc, "G", r, user) == masa(svc, "G", r) and masa(svc, "Q", r, user) == masa(svc, "Q", r)
    assert masa(svc, "F", 16, user) == masa(svc, "F", 16) and num(masa(svc, "F", 16, user))
    icap = series(chart(svc, "chart0", user))["ICAP"]
    assert icap[10] == masa(svc, "F", 16) and icap[11:] == ["c"] * 4     # (#N/A: the line ends at 2Y)


def test_on_ppk_basamak_ois_zero_follows_the_viewers_curve_as_2y_does(svc):
    """OIS zero reads Motor's node, which follows the viewer's curve setting (Ayarlar → Eğri interpolasyonu) as the rows up
    to 2Y do (they read Motor's M through the Forward sheet); ICAP is the XCCY bootstrap of the quotes, the same on both -
    as the 2Y row.  The Bootstrap viewer's numbers do not move."""
    if not svc.interp.available:
        pytest.skip("no curve switch in this workbook")
    user = svc.login("Masa offshore PPK")["user"]
    boot = {(c, r): masa(svc, c, r) for c in "FG" for r in range(16, 21)}
    svc.set_interp(user, "ppk")
    try:
        for r, m in [(16, 98)] + [(row, mrow) for row, _, _, mrow in ROWS]:
            assert masa(svc, "G", r, user) == pytest.approx(cell(svc, "Motor!M%d" % m, user), rel=1e-14)
            assert masa(svc, "F", r, user) == boot[("F", r)]
        assert any(masa(svc, "G", r, user) != boot[("G", r)] for r in range(16, 21))   # (the setting took)
        assert {(c, r): masa(svc, c, r) for c in "FG" for r in range(16, 21)} == boot
    finally:
        svc.set_interp(user, "boot")


def test_the_rates_chart_runs_to_10y(svc):
    """Masa's "Oranlar (360 basit)" chart ran to 2Y: it runs to 10Y now, as its chart data (MASA!AF17:AK20) and the O/N
    chart beside it do - ICAP where the XCCY curve has a node, OIS zero at every tenor; RET and VİOP end where their quotes
    do (#N/A: passed over).  The model file stays the workbook's (a pure import); the O/N chart is as it was."""
    tenors = ["ON", "TN", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y"]
    rates, on = chart(svc, "chart0"), chart(svc, "chart1")
    assert rates["title"] == ex.MASA_CHART_TITLE and rates["cats"] == tenors and on["cats"] == tenors
    s = series(rates)
    assert list(s) == ["RET bid", "RET ask", "ICAP", "OIS zero", "VİOP"]
    assert s["ICAP"][11:] == [masa(svc, "F", 17), masa(svc, "F", 18), "c", "c"]
    assert s["OIS zero"][11:] == [masa(svc, "G", r) for r in (17, 18, 19, 20)]
    assert all(s[name][11:] == ["c"] * 4 for name in ("RET bid", "RET ask", "VİOP"))
    assert s["ICAP"][:11] == [masa(svc, "F", r) for r in range(6, 17)]
    assert series(on)["Offshore O/N"][11:] == [masa(svc, "R", 17), masa(svc, "R", 18), "c", "c"]
    raw = Model.load(os.path.join(ROOT, "models", "tto.json.gz")).sheet("MASA").charts[0]
    served = svc.books["tto"].model.sheet("MASA").charts[0]
    assert [x["val"] for x in raw["series"]] == ["MASA!$A%s$6:$A%s$16" % (c, c) for c in "GHIJK"]
    assert [x["val"] for x in served["series"]] == ["MASA!$A%s$6:$A%s$20" % (c, c) for c in "GHIJK"]
    assert all(x["cat"] == "MASA!$AF$6:$AF$20" for x in served["series"])
    assert {k: v for k, v in served.items() if k != "series"} == {k: v for k, v in raw.items() if k != "series"}
    assert [dict(x, cat=None, val=None) for x in served["series"]] == [dict(x, cat=None, val=None) for x in raw["series"]]


def _models():
    """The TRY workbook's model with the dashboard's additions, and with them but these two."""
    mine = (ex.MASA_OFF_NAME, ex.MASA_CHART_NAME)
    path = os.path.join(ROOT, "models", "tto.json.gz")
    new, old = Model.load(path), Model.load(path)
    assert ex.apply("tto", new) == []
    builders = ex._BUILDERS["tto"]
    try:
        ex._BUILDERS["tto"] = tuple(b for b in builders if b[0] not in mine)
        assert ex.apply("tto", old) == []
    finally:
        ex._BUILDERS["tto"] = builders
    return old, new


def test_nothing_else_changes_in_the_workbook():
    """The two additions change MASA!F17:G20's formulas and the rates chart's ranges - every other cell of every sheet
    (formula, constant, look) and every other chart is as the other additions leave it."""
    old, new = _models()
    assert [s.name for s in old.sheets] == [s.name for s in new.sheets]
    changed = []
    for so, sn in zip(old.sheets, new.sheets):
        def text(m, s, rc):
            tid = s.fml.get(rc)
            return None if tid is None else m.templates[tid]
        for rc in set(so.fml) | set(sn.fml) | set(so.consts) | set(sn.consts):
            if text(old, so, rc) != text(new, sn, rc) or so.consts.get(rc) != sn.consts.get(rc) \
                    or so.styles.get(rc) != sn.styles.get(rc):
                r, c = divmod(rc, COLS)
                changed.append("%s!%s%d" % (sn.name, index_to_col(c), r))
        if sn.name == "MASA":
            assert sn.charts[1:] == so.charts[1:] and sn.charts[0] != so.charts[0]
        else:
            assert sn.charts == so.charts
    assert sorted(changed) == sorted("MASA!%s%d" % (c, r) for c in "FG" for r in (17, 18, 19, 20))
    masa_new = new.sheet("MASA")
    for r, _, zero, m in ROWS:
        assert ex.formula_of(new, "MASA", "F%d" % r) == 'IFERROR(Forward!$%s$%s,"")' % (zero[0], zero[1:])
        assert ex.formula_of(new, "MASA", "G%d" % r) == 'IFERROR(Motor!$M$%d,"")' % m
        assert ex.formula_of(old, "MASA", "F%d" % r) == ex.formula_of(old, "MASA", "G%d" % r) == '""'
        assert masa_new.styles.get(parse_a1("F%d" % r)) == masa_new.styles.get(parse_a1("F16"))     # (the 2Y row's look)
        assert masa_new.styles.get(parse_a1("G%d" % r)) == masa_new.styles.get(parse_a1("G16"))


def test_a_workbook_that_changed_there_is_left_as_it_is():
    """Each addition checks what the workbook holds before it writes: a file whose 7Y ICAP is a formula of its own (not
    its "") keeps its table as it is, a chart over other rows keeps its rows - each left out and said so."""
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    ex.SheetBuilder(model, "MASA").patch("F19", "=Forward!$H$131")
    masa_sheet = model.sheet("MASA")
    rates = masa_sheet.charts[0]
    masa_sheet.charts[0] = dict(rates, series=[dict(s, val=s["val"].replace("$16", "$15")) for s in rates["series"]])
    problems = ex.apply("tto", model)
    assert [p.split(":")[0] for p in problems] == [ex.MASA_OFF_NAME, ex.MASA_CHART_NAME]
    assert ex.formula_of(model, "MASA", "F19") == "Forward!$H$131" and ex.formula_of(model, "MASA", "F17") == '""'
    assert [s["val"] for s in model.sheet("MASA").charts[0]["series"]] == ["MASA!$A%s$6:$A%s$15" % (c, c) for c in "GHIJK"]


def test_nothing_else_moves_on_masa_and_forward(svc):
    """Every value of MASA and Forward is what it was with the workbook's blanks at MASA!F17:G20 (a calculation of its own
    on top of the desk's, the blanks put back), but these cells and what reads them: ICAP − OIS and the chart data."""
    book = svc.books["tto"]
    si = book.model.sheet_index["MASA"]
    blanks = {(si, parse_a1("%s%d" % (c, r))): "" for c in "FG" for r in (17, 18, 19, 20)}

    def same(a, b):
        if type(a) is not type(b):
            return False
        if type(a) is float:
            return a == b or (a != a and b != b)
        if hasattr(a, "rows"):
            return len(a.rows) == len(b.rows) and all(len(x) == len(y) and all(same(p, q) for p, q in zip(x, y))
                                                      for x, y in zip(a.rows, b.rows))
        return a == b

    def run():
        eng = book.engine
        before = eng.layer(("test_masa_offshore", "blanks"), eng.shared, blanks)
        moved = []
        try:
            for name in ("MASA", "Forward"):
                sh = book.model.sheet(name)
                for rc in sorted(set(sh.fml) | set(sh.consts)):
                    r, c = divmod(rc, COLS)
                    if not same(before.get(sh.index, r, c), eng.shared.get(sh.index, r, c)):
                        moved.append("%s!%s%d" % (name, index_to_col(c), r))
        finally:
            eng.drop_layer(("test_masa_offshore", "blanks"))
        return moved

    moved = svc.et.call(run)
    assert sorted(moved) == sorted(["MASA!F17", "MASA!F18", "MASA!G17", "MASA!G18", "MASA!G19", "MASA!G20",
                                    "MASA!L17", "MASA!L18", "MASA!AI17", "MASA!AI18",
                                    "MASA!AJ17", "MASA!AJ18", "MASA!AJ19", "MASA!AJ20"])
