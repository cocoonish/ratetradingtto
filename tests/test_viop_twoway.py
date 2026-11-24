"""VİOP Target two-way (the desk, 24.11.2026: "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız
için"): per row, Hedef değer (in the row's own type), Hedef faiz, Uzak limit fiyatı, Spread fiyatı or Hedef − piyasa can
be typed - the one typed last stands, the others are worked out from it (``extras._tto_viop_tw``).  Checked against a
calculation of its own off the sheet's contract rows (97 labels, 98 days, 99 / 100 bid / ask, 101 USD, 105 / 106 FX
swap forwards): the near limit by the row's side, the USD carry, ACT/360.  The mechanism: ``test_twoway.py``."""
from __future__ import annotations

import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.xl.model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMBERS = ("P", "Q", "S", "T", "V")
STORES = {"P": "AE", "Q": "AF", "S": "AG", "T": "AH", "V": "AI"}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": "VIOP!" + ref, "value": v} for ref, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def target(r, near="Spot", far="31.12.2026", side="LONG", kind="Faiz %", value="34"):
    return {"L%d" % r: near, "M%d" % r: far, "N%d" % r: side, "O%d" % r: kind, "P%d" % r: value}


def row(svc, user, r):
    return {c: cell(svc, "VIOP!%s%d" % (c, r), user) for c in MEMBERS}


def stored(svc, user):
    return {k.split("!")[1]: v for (_, k), v in svc.store.user_inputs(user, "tto").items()
            if k.startswith("VIOP!A") and k[6:7] in "EFGHI"}


class Row(object):
    """The row's market off the sheet's contract rows - and the target worked out by hand from any of its members."""

    def __init__(self, svc, user, r):
        g = lambda ref: cell(svc, "VIOP!" + ref, user)                                     # noqa: E731
        cols = {g("%s97" % c): c for c in "LMNOPQRSTUVWX"}
        near, far = cols[g("L%d" % r)], cols[g("M%d" % r)]
        self.side, self.kind = g("N%d" % r), g("O%d" % r)
        self.days = g("%s98" % far) - g("%s98" % near)
        self.carry = (1 + g("%s101" % far) * g("%s98" % far) / 360) / (1 + g("%s101" % near) * g("%s98" % near) / 360)
        short = self.side == "SHORT"
        self.near = g("%s100" % near) if short else g("%s99" % near)
        far_px = g("%s99" % far) if short else g("%s100" % far)
        self.market = ((far_px / self.near) * self.carry - 1) * 360 / self.days                     # U: by the side
        self.fx = (((g("%s105" % far) + g("%s106" % far)) / 2) / ((g("%s105" % near) + g("%s106" % near)) / 2)
                   * self.carry - 1) * 360 / self.days
        self.fra = g("W%d" % r)                                                             # (the curve's: not a member)

    def rate_of(self, member, x):
        if member == "Q":
            return x
        if member == "V":
            return self.market + x / 10000
        if member in ("S", "T"):
            price = x if member == "S" else self.near + x
            return ((price / self.near) * self.carry - 1) * 360 / self.days
        return {"Faiz %": x / 100, "Fiyat": ((x / self.near) * self.carry - 1) * 360 / self.days if x > 0 else None,
                "FXswap+bp": self.fx + x / 10000}.get(self.kind, self.fra + x / 10000)

    def members(self, rate):
        far = self.near * (1 + rate * self.days / 360) / self.carry
        value = {"Faiz %": rate * 100, "Fiyat": far, "FXswap+bp": (rate - self.fx) * 10000}.get(self.kind, (rate - self.fra) * 10000)
        return {"P": value, "Q": rate, "S": far, "T": far - self.near, "V": (rate - self.market) * 10000}


# ---------------------------------------------------------------------------------------------- the declaration
def test_the_target_is_a_two_way_group_on_cells_no_input_ever_stood_on(svc):
    """Five members per row, each kept in a store of its row (AE:AI, beside the table's tooltips, in a helper table of the
    page); Hedef değer is no input of its own any more - its store is - and a row with nothing typed is empty."""
    assert svc.twoway.problems == {} and svc.books["tto"].left_out == []
    g = svc.twoway.groups["viop-target"]
    book = svc.books["tto"]
    assert [m.name for m in g.members] == ["Hedef değer", "Hedef faiz", "Uzak limit", "Spread fiyatı", "Hedef − piyasa"]
    assert g.shape == (8, 1) and not any(m.own for m in g.members)
    for m, c in zip(g.members, MEMBERS):
        assert m.cells == book.cells_of("VIOP!%s331:%s338" % (c, c)) and m.store == book.cells_of("VIOP!%s331:%s338" % ((STORES[c],) * 2))
        assert all(x not in book.inputs for x in m.cells)
        assert all(book.inputs[x].scope == "user" and book.inputs[x].kind == "number" for x in m.store)
    from tto.views import load_views
    viop = next(v for v in load_views() if v["id"] == "viop")
    assert not any(i["range"].startswith("P331") for i in viop["inputs"])
    assert next(p for p in viop["panels"] if p["id"] == "VT1")["range"] == "AE330:AI338"
    u = svc.login("vt boş")["user"]
    assert row(svc, u, 331) == dict.fromkeys(MEMBERS, "")


# ---------------------------------------------------------------------------------------------- typing
@pytest.mark.parametrize("kind,side", [("Faiz %", "LONG"), ("FRA+bp", "SHORT"), ("FXswap+bp", "LONG"), ("Fiyat", "SHORT")])
def test_each_member_typed_gives_the_others(svc, kind, side):
    """Any of the five typed on a row of each type and side: that value exactly, the others the sheet's formulas of the
    rate it gives (Hedef değer in the row's type) - and back: each value typed again as its own kind gives the same row
    (1e-9); only the one typed last is kept."""
    u = svc.login("vt %s %s" % (kind, side))["user"]
    r = 333
    first = {"Faiz %": "33", "FRA+bp": "-75", "FXswap+bp": "40", "Fiyat": "51,05"}[kind]
    try:
        put(svc, u, target(r, side=side, kind=kind, value=first))
        m = Row(svc, u, r)
        want = m.members(m.rate_of("P", float(first.replace(",", "."))))
        assert row(svc, u, r) == pytest.approx(want, rel=1e-9, abs=1e-9)
        samples = {"P": want["P"] * 0.9 if kind == "Fiyat" else want["P"] + 12.5, "Q": 0.3175, "S": 51.2, "T": 1.35, "V": -42.5}
        for c, x in samples.items():
            put(svc, u, {"%s%d" % (c, r): x})
            now = row(svc, u, r)
            assert now[c] == x and now == pytest.approx(m.members(m.rate_of(c, x)), rel=1e-9, abs=1e-9), (c, x)
            assert stored(svc, u) == {"%s%d" % (STORES[c], r): x}
            for k in MEMBERS:                                               # each value typed back as its own kind
                put(svc, u, {"%s%d" % (k, r): now[k]})
                assert row(svc, u, r) == pytest.approx(now, rel=1e-9, abs=1e-9), (c, k)
                assert list(stored(svc, u)) == ["%s%d" % (STORES[k], r)]
    finally:
        svc.reset_inputs(u, "tto")


def test_the_type_stays_the_users_and_says_what_hedef_deger_is(svc):
    """A far price typed on an FRA+bp row: Hedef değer shows its bp over OIS FRA (the row's type is the user's choice);
    the type changed: Hedef değer in the new type, the far price typed stays; Hedef faiz's tooltip says where the rate
    comes from; Delete on any of the five: the row empty again."""
    u = svc.login("vt tip")["user"]
    r = 334
    try:
        put(svc, u, target(r, side="SHORT", kind="FRA+bp", value="-150"))
        put(svc, u, {"S%d" % r: "51,1"})
        m = Row(svc, u, r)
        rate = m.rate_of("S", 51.1)
        assert cell(svc, "VIOP!P%d" % r, u) == pytest.approx((rate - m.fra) * 10000, rel=1e-9)
        tip = cell(svc, "VIOP!AB%d" % r, u)
        assert tip.startswith("Hedef faiz = yazılan uzak limit fiyatı 51,1 → ima TRY faizi (yakın limit ") and tip.endswith("gün, ACT/360)")
        for kind, value in (("Faiz %", rate * 100), ("Fiyat", 51.1), ("FXswap+bp", (rate - Row(svc, u, r).fx) * 10000)):
            put(svc, u, {"O%d" % r: kind})
            assert cell(svc, "VIOP!S%d" % r, u) == 51.1 and cell(svc, "VIOP!P%d" % r, u) == pytest.approx(value, rel=1e-9), kind
        put(svc, u, {"V%d" % r: "15"})
        assert cell(svc, "VIOP!AB%d" % r, u).startswith("Hedef faiz = piyasa ima ff (yön) ") and stored(svc, u) == {"AI%d" % r: 15.0}
        put(svc, u, {"T%d" % r: "1,2"})
        assert cell(svc, "VIOP!AB%d" % r, u).startswith("Hedef faiz = yazılan spread fiyatı 1,2: uzak limit = yakın limit ")
        put(svc, u, {"Q%d" % r: "31"})
        assert cell(svc, "VIOP!AB%d" % r, u).startswith("Hedef faiz yazıldı") and cell(svc, "VIOP!Q%d" % r, u) == 0.31
        res = put(svc, u, {"V%d" % r: ""})                                    # Delete on a worked-out one
        assert res["applied"] == 1 and stored(svc, u) == {} and row(svc, u, r) == dict.fromkeys(MEMBERS, "")
        put(svc, u, {"O%d" % r: "FRA+bp", "P%d" % r: "-150"})                  # the row's own value again: as before
        assert cell(svc, "VIOP!AB%d" % r, u).startswith("Hedef faiz = OIS FRA (") and stored(svc, u) == {"AE%d" % r: -150.0}
        assert svc.reset_inputs(u, "tto", ["VIOP!T%d" % r])["reset"] == 1 and stored(svc, u) == {}
    finally:
        svc.reset_inputs(u, "tto")


def test_a_row_typed_before_reads_as_before(svc):
    """A Hedef değer users typed when it was the table's input (kept at P331): its row's typed value - moved to its store
    once, the row priced exactly as before (the file's own row: SHORT, FRA+bp, −150)."""
    u = svc.login("vt eski")["user"]
    svc.store.set_user_inputs(u, "tto", {"VIOP!L331": "Spot", "VIOP!M331": "30.11.2026", "VIOP!N331": "SHORT",
                                         "VIOP!O331": "FRA+bp", "VIOP!P331": -150.0})
    svc._reload_user(u)
    try:
        assert stored(svc, u) == {"AE331": -150.0} and cell(svc, "VIOP!P331", u) == -150.0
        assert cell(svc, "VIOP!Q331", u) == pytest.approx(0.34301087462666635, rel=1e-12)          # (test_defaults' value)
        assert cell(svc, "VIOP!R331", u) == pytest.approx(49.9975) and cell(svc, "VIOP!Y331", u) == 26.0
        assert cell(svc, "MASA!S121", u) == "FRA+bp -150" and cell(svc, "MASA!T121", u) == cell(svc, "VIOP!Q331", u)
    finally:
        svc.reset_inputs(u, "tto")


def test_a_contract_that_rolled_off_leaves_the_row_invalid_with_its_typed_value(svc):
    """Contracts are found by their label: a near contract no longer listed leaves the row "Geçersiz" - nothing priced,
    the typed far price kept in its store and shown in its cell; the contract picked again: the row priced from it."""
    u = svc.login("vt geçersiz")["user"]
    r = 335
    try:
        put(svc, u, target(r, side="LONG", kind="Fiyat", value="51"))
        put(svc, u, {"S%d" % r: "51,25"})
        put(svc, u, {"L%d" % r: "31.10.2026"})                                # an expired contract
        assert cell(svc, "EK_VFRA!U%d" % (r - 321), u).startswith("Geçersiz")
        assert row(svc, u, r) == {"P": "", "Q": "", "S": 51.25, "T": "", "V": ""} and stored(svc, u) == {"AG%d" % r: 51.25}
        put(svc, u, {"L%d" % r: "Spot"})
        m = Row(svc, u, r)
        assert row(svc, u, r) == pytest.approx(m.members(m.rate_of("S", 51.25)), rel=1e-9)
    finally:
        svc.reset_inputs(u, "tto")


def test_a_pasted_column_a_scenario_and_masas_strip(svc):
    """Far prices pasted down three rows: each row's typed value; saved in a scenario and loaded back as they were;
    Masa's TARGET strip reads the rows (a worked-out Hedef değer to four decimals) and its strip of inputs types Hedef
    değer into the same store."""
    u = svc.login("vt yapıştır")["user"]
    try:
        for r in (336, 337, 338):
            put(svc, u, target(r, side="SHORT", kind="FRA+bp", value="-100"))
        res = svc.paste(u, "tto", "VIOP!S336", "51,2\n51,4\n51,6")
        assert res["errors"] == [] and stored(svc, u) == {"AG336": 51.2, "AG337": 51.4, "AG338": 51.6}
        want = {r: row(svc, u, r) for r in (336, 337, 338)}
        assert [want[r]["S"] for r in (336, 337, 338)] == [51.2, 51.4, 51.6]
        svc.save_scenario(u, "vt senaryo")
        put(svc, u, {"S336": "", "Q337": "0,3"})
        svc.load_scenario(u, "vt senaryo")
        assert {r: row(svc, u, r) for r in (336, 337, 338)} == want
        p = want[336]["P"]
        assert cell(svc, "MASA!S126", u) == "FRA+bp %s" % round(p, 4) and cell(svc, "MASA!V126", u) == 51.2
        # Masa's strip of the target's inputs: Hedef değer typed there is the row's typed value
        res = svc.set_inputs(u, "tto", [{"ref": "VIOP!P337", "value": "-80"}])
        assert res["errors"] == [] and stored(svc, u)["AE337"] == -80.0 and "AG337" not in stored(svc, u)
        masa = next(x for x in svc.view(u, "masa")["panels"] if x["id"] == "B17D")["data"]
        p337 = masa["rows"][masa["r"].index(337)][masa["c"].index("P")]
        assert p337["i"] == "u" and p337["an"] == "Hedef faiz, Uzak limit, Spread fiyatı, Hedef − piyasa"
    finally:
        svc.reset_inputs(u, "tto")


def test_the_target_in_a_temporary_copy(svc):
    """A copy of the target table: a far price typed there is the copy's (every member has a store: nothing refused,
    whatever the table holds); the table keeps its Hedef değer; Delete in the copy follows the table again."""
    u = svc.login("vt kopya")["user"]
    try:
        put(svc, u, target(331, side="LONG", kind="Faiz %", value="34"))
        cid = svc.copy_action(u, "open", {"view": "viop", "panel": "B33"})["copy"]["id"]

        def copy_cell(ref):
            def run():
                cp = svc.copies.find(u, cid)
                return svc.copies.calc(u, cp).value("VIOP!" + ref)
            return svc.et.call(run)

        assert copy_cell("Q331") == 0.34
        res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "VIOP!S331", "value": "51,3"}]})
        assert res["errors"] == [] and copy_cell("S331") == 51.3
        m = Row(svc, u, 331)
        assert copy_cell("Q331") == pytest.approx(m.rate_of("S", 51.3), rel=1e-12)
        assert copy_cell("P331") == pytest.approx(m.rate_of("S", 51.3) * 100, rel=1e-12)
        assert cell(svc, "VIOP!Q331", u) == 0.34 and stored(svc, u) == {"AE331": 34.0}             # the table's own
        res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "VIOP!T331", "value": ""}]})
        assert res["applied"] == 1 and copy_cell("Q331") == 0.34
        svc.copy_action(u, "close", {"copy": cid})
    finally:
        svc.reset_inputs(u, "tto")


def test_the_page_marks_and_note(svc):
    """The VİOP page: the five of a row inputs (``i``), the typed one marked, the others worked out from it; the note
    under the table; the stores in their helper table."""
    u = svc.login("vt sayfa")["user"]
    try:
        put(svc, u, target(332, side="LONG", kind="FRA+bp", value="-50"))
        put(svc, u, {"V332": "20"})
        p = next(x for x in svc.view(u, "viop")["panels"] if x["id"] == "B33")
        d = p["data"]
        cells = dict(zip(d["c"], d["rows"][d["r"].index(332)]))
        assert all(cells[c]["i"] == "u" for c in MEMBERS) and cells["V"]["an"] == "Hedef değer, Hedef faiz, Uzak limit, Spread fiyatı"
        assert cells["P"]["ao"] == "Hedef − piyasa · V332" and cells["S"]["ao"] == "Hedef − piyasa · V332"
        assert "İki yönlü: hedef değer, hedef faiz, uzak limit fiyatı, spread fiyatı ya da hedef − piyasa" in p["note"]
        helper = next(x for x in svc.view(u, "viop", True)["panels"] if x["id"] == "VT1")["data"]
        assert helper["rows"][0][0]["t"] == "Yazılan hedef değer" and helper["rows"][helper["r"].index(332)][4]["m"] == 1
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the workbook
def test_left_out_when_the_target_rate_is_written_otherwise():
    """The two-way target solves the sheet's own target rate: a rate written otherwise leaves the table as it was."""
    tto = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    ex.SheetBuilder(tto, "VIOP").patch("V336", "=IFERROR(($Q336-$U336)*100,\"\")")             # the gap in % points
    assert ex.apply("tto", tto) == [ex.VT_NAME + ": VIOP!V336 beklenen formül değil (($Q336-$U336)*10000 yok)"]
    assert ex.formula_of(tto, "VIOP", "Q331").startswith('IF(EK_VFRA!$U$10<>"",') and parse_p(tto) is None


def parse_p(model):
    from tto.xl.model import parse_a1
    sh = model.sheet("VIOP")
    return sh.fml.get(parse_a1("P331"))
