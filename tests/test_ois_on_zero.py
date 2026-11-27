"""OIS · PPK → Kotalar: O/N EŞLENİKLERİ with each curve's zero (``tto/extras.py``: ``ONZ_NAME``).

The desk, 27.11.2026, on the table O/N EŞLENİKLERİ (360) (OIS_MAIN!AD7:AH26: per tenor the O/N equivalent, 360 basis, of
the MPC-implied curve "piyasa" and of the scenarios Baz / Hawkish / Dovish): "Bunlarin on esleniklerini verirken zerosunu
da vermemiz gerekli".  Beside the O/N columns each curve's zero rate, 360 simple - as Masa's ORANLAR / O/N EŞLENİKLERİ
show OIS and offshore: the same discount factor and the same days g as the row's O/N, 1 + zero·g/360 = (1 + O/N/360)^g.
The zeros sit in the panel's free columns AA:AC and AI; the page lists them after the O/N columns (``"cols"``), the O/N
cells stay where they are.  With the TLREF normalization on, the scenarios' zeros carry the stretch as their O/N do.
"""
import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.tokenizer import index_to_col

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: (O/N column, zero column, Motor's column of the curve, its DF is 1 / that column's value - else that value itself)
CURVES = (("AE", "AA", "J", True), ("AF", "AB", "E", False), ("AG", "AC", "L", False), ("AH", "AI", "P", False))
ROWS = range(9, 27)


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def _days(svc, r, user=None):
    """The row's days g, as its O/N counts them: Motor's quarterly calendar from 6M, else the tenor's days."""
    m = r + 316
    months = cell(svc, "Motor!A%d" % m, user)
    if months >= 6:
        return cell(svc, "Motor!F%d" % (139 + int(months / 3) - 1), user)
    return cell(svc, "Motor!B%d" % m, user)


def _check_rows(svc, user=None):
    seen = 0
    for r in ROWS:
        g = _days(svc, r, user)
        for on_col, zero_col, motor, inverse in CURVES:
            v = cell(svc, "Motor!%s%d" % (motor, r + 316), user)
            growth = 1 / v if inverse else v
            on, zero = cell(svc, "OIS_MAIN!%s%d" % (on_col, r), user), cell(svc, "OIS_MAIN!%s%d" % (zero_col, r), user)
            assert type(on) is float and type(zero) is float, (r, zero_col, on, zero)
            assert zero == pytest.approx((growth - 1) * 360 / g, rel=1e-13), (r, zero_col)
            # one discount factor, one day count: the O/N compounded over g days is the zero's simple growth
            assert (1 + on / 360) ** g == pytest.approx(1 + zero * g / 360, rel=1e-12), (r, zero_col)
            seen += 1
    assert seen == 4 * len(ROWS)


def test_each_curves_zero_beside_its_on(svc):
    """Every tenor, every curve: the zero is (G − 1)·360/g on the O/N's own growth factor and days, and the two say the
    same discount factor; a longer tenor's zero is above its O/N (simple vs compounded) and the 1M's nearly equal."""
    _check_rows(svc)
    on, zero = cell(svc, "OIS_MAIN!AE9"), cell(svc, "OIS_MAIN!AA9")
    assert zero > on and (zero - on) * 10000 < 100                       # 1M: a month's compounding
    assert cell(svc, "OIS_MAIN!AA26") - cell(svc, "OIS_MAIN!AE26") > 0.05   # 10Y: years of it


def test_the_page_shows_the_zeros_after_the_on_columns(svc):
    """The panel (Kotalar tab): its title says zero, the columns in order - Vade, the four O/N, the four zeros - the
    captions follow the scenarios' names (SENARYOLAR), the zeros read as % with the O/N's look."""
    user = svc.login("onz sayfa")["user"]
    p = next(p for p in svc.view(user, "ois")["panels"] if p["id"] == "B5")
    d = p["data"]
    assert p["title"] == ex.ONZ_TITLE == "O/N EŞLENİKLERİ VE ZERO (360 · zero basit)"
    assert d["c"] == ["AD", "AE", "AF", "AG", "AH", "AA", "AB", "AC", "AI"]
    head = next(row for row in d["rows"] if row and isinstance(row[0], dict) and row[0].get("t") == "Vade")
    names = [cell(svc, "OIS_MAIN!P%d" % r) for r in (3, 4, 5)]
    assert [c.get("t") for c in head] == (["Vade", "O/N piyasa"] + ["O/N " + n for n in names] + ["Zero piyasa"]
                                           + ["Zero " + n for n in names])
    row1 = d["rows"][d["r"].index(9)]
    assert row1[0]["t"] == cell(svc, "OIS_MAIN!A9")
    assert all(c["t"].endswith("%") and c.get("k") == "n" for c in row1[1:]), row1


def test_with_the_normalization_on_the_scenarios_zeros_carry_the_stretch(svc):
    """TLREF typed over its normal level with the switch on: the scenarios' growth factors carry the stretch before the
    date (Motor!E / L / P), and so do both their O/N and their zero - still one discount factor; the implied curve's
    ("piyasa") still fits the market."""
    user = svc.login("onz normallesme")["user"]
    spot = cell(svc, "OIS_MAIN!B2")
    res = svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!L2", "value": "Açık"}, {"ref": "OIS_MAIN!L4", "value": "35"},
                                       {"ref": "OIS_MAIN!J2", "value": "39"},
                                       {"ref": "OIS_MAIN!L3", "value": _date(spot + 60)}])
    assert res["errors"] == [], res["errors"]
    assert cell(svc, "OIS_MAIN!M2", user) == 1.0
    _check_rows(svc, user)
    # the 1M Baz zero moved with the stretch (the user's S1 against the shared one, the switch off)
    assert cell(svc, "OIS_MAIN!AB9", user) != cell(svc, "OIS_MAIN!AB9")


def _date(serial):
    from tto.xl.values import serial_to_date
    return serial_to_date(serial).strftime("%d.%m.%Y")


def _models():
    """The TRY workbook's model with the dashboard's additions, and with them but this one."""
    path = os.path.join(ROOT, "models", "tto.json.gz")
    new, old = Model.load(path), Model.load(path)
    assert ex.apply("tto", new) == []
    builders = ex._BUILDERS["tto"]
    try:
        ex._BUILDERS["tto"] = tuple(b for b in builders if b[0] != ex.ONZ_NAME)
        assert ex.apply("tto", old) == []
    finally:
        ex._BUILDERS["tto"] = builders
    return old, new


def test_nothing_else_changes_in_the_workbook():
    """The addition writes the zeros' cells (AA8:AC26, AI8:AI26) and the table's title (AD7) - every other cell of every
    sheet (formula, constant, look) and every chart is as the other additions leave it; the zeros look like their O/N."""
    old, new = _models()
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
        assert sn.charts == so.charts, sn.name
    want = ["OIS_MAIN!AD7"] + ["OIS_MAIN!%s%d" % (z, r) for _, z, _, _ in CURVES for r in range(8, 27)]
    assert sorted(changed) == sorted(want)
    sh = new.sheet("OIS_MAIN")
    for on_col, zero_col, _, _ in CURVES:
        for r in range(8, 27):
            assert sh.styles.get(parse_a1("%s%d" % (zero_col, r))) == sh.styles.get(parse_a1("%s%d" % (on_col, r)))


def test_a_workbook_that_changed_there_is_left_as_it_is():
    """The addition checks what the workbook holds before it writes: a file with something of its own in a zero's column
    (AB12) keeps its table as it is - the addition left out and said so."""
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    ex.SheetBuilder(model, "OIS_MAIN").set("AB12", "not")
    problems = ex.apply("tto", model)
    assert [p.split(":")[0] for p in problems] == [ex.ONZ_NAME]
    assert model.sheet("OIS_MAIN").consts.get(parse_a1(ex.ONZ_TITLE_CELL)) == "O/N EŞLENİKLERİ (360)"
