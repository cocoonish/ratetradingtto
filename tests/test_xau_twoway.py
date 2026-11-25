"""VİOP's gold calculator two-way (the desk, 25.11.2026: "Evet" - to "VİOP gold calculator: should it be two-way, with a
typed price or forward following its contract when it rolls and a typed rate staying in its column?"): in each column
TRY %, All In S -> E (the USDTRY forward), SP, Günlük SP, XAUTRY teorik or ON karşılık can be typed - the one typed last
stands, the others are worked out from it (``extras.XAU_TW``, ``extras._xau_hub``).  Checked against a calculation of its
own off the column's spot, USD rate, days and XAUUSD forward.  When the gold contracts roll, a forward, SP, SP per day or
theoretical price typed goes with its contract, a TRY % or ON typed stays in its column (``rowkeys.RowKeys.roll``).  The
mechanism itself: ``test_twoway.py``."""
from __future__ import annotations

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto import rowkeys as rk

GRAM = 31.1035
ROW = dict((name, ex.XAU_CALC + 1 + k) for k, name in enumerate(ex.XAU_CALC_ROWS))
MEMBERS = [name for name, _, _ in ex.XAU_TW]                     # try, fwd, sp, spd, teo, on
STORE = dict((name, ex.XAU_TW_FIRST + k) for k, (name, _, _) in enumerate(ex.XAU_TW))
SAMPLE = {"try": 36.5, "fwd": 52.45, "sp": 24500.0, "spd": 430.0, "teo": 6720.0, "on": 33.1}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def ref(name, col):
    return "EK_XAU!%s%d" % (col, ROW[name])


def put(svc, user, cells, sheet="EK_XAU"):
    res = svc.set_inputs(user, "tto", [{"ref": "%s!%s" % (sheet, k), "value": v} for k, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def column(svc, user, col):
    return {m: cell(svc, ref(m, col), user) for m in MEMBERS}


def stored(svc, user):
    """The user's typed values kept in the calculator's stores: {"B71": 6720.0, ...}."""
    rows = set(STORE.values())
    out = {}
    for (_, k), v in svc.store.user_inputs(user, "tto").items():
        sheet, _, a = k.partition("!")
        if sheet == "EK_XAU" and int(a[1:]) in rows:
            out[a] = v
    return out


class Col(object):
    """A column's market as the calculator reads it - and its members worked out by hand from a TRY rate or any member."""

    def __init__(self, svc, user, col):
        g = lambda name: cell(svc, ref(name, col), user)                           # noqa: E731
        self.s, self.usd, self.n, self.xfwd = g("s"), g("usd"), g("n"), g("xfwd")

    def members(self, rate):
        fwd = self.s * (1 + rate / 100 / 360 * self.n) / (1 + self.usd / 100 / 360 * self.n)
        sp = (fwd - self.s) * 10000
        return {"try": rate, "fwd": fwd, "sp": sp, "spd": sp / self.n, "teo": self.xfwd * fwd / GRAM,
                "on": 360 * ((1 + rate / 100 * self.n / 360) ** (1 / self.n) - 1) * 100}

    def rate_of(self, member, x):
        if member == "try":
            return x
        if member == "on":
            return ((1 + x / 100 / 360) ** self.n - 1) * 360 / self.n * 100
        fwd = {"fwd": x, "sp": self.s + x / 10000, "spd": self.s + x * self.n / 10000, "teo": x * GRAM / self.xfwd}[member]
        return ((fwd / self.s) * (1 + self.usd / 100 / 360 * self.n) - 1) * 360 / self.n * 100

    def typed(self, member, x):
        """The column with ``x`` typed into ``member``: that value exactly, the others from the rate it gives."""
        out = self.members(self.rate_of(member, x))
        out[member] = x
        return out


# ---------------------------------------------------------------------------------------------- the declaration
def test_the_calculator_is_a_two_way_group_on_stores_of_its_own(svc):
    """Six members per column - TRY %, USDTRY fwd, SP, Günlük SP, XAUTRY teorik, ON karşılık -, each kept in a store of
    its column (rows 67-72, a hidden helper table of the page, the contracts in its header): none in place, the
    calculator is copyable; TRY % is no input of its own any more (its store is); the declaration is the builder's."""
    assert svc.twoway.problems == {} and svc.books["tto"].left_out == []
    g = svc.twoway.groups["viop-gold"]
    book = svc.books["tto"]
    assert [m.name for m in g.members] == [name for _, name, _ in ex.XAU_TW]
    assert g.sheet == "EK_XAU" and g.shape == (1, 4) and not any(m.own for m in g.members)
    for m, name in zip(g.members, MEMBERS):
        assert m.cells == book.cells_of("EK_XAU!B%d:E%d" % (ROW[name], ROW[name]))
        assert m.store == book.cells_of("EK_XAU!B%d:E%d" % (STORE[name], STORE[name]))
        assert all(c not in book.inputs for c in m.cells), name
        assert all(book.inputs[c].scope == "user" and book.inputs[c].kind == "number" for c in m.store), name
    from tto.views import load_views
    viop = next(v for v in load_views() if v["id"] == "viop")
    declared = set()
    for i in viop["inputs"]:
        declared.update(book.cells_of(i["range"], viop["sheet"]))
    assert not declared & {c for m in g.members for c in m.cells + m.store}
    assert set(book.cells_of("EK_XAU!B45:E45") + book.cells_of("EK_XAU!B47:E47")) <= declared      # (USD %, swap % stay)
    helper = next(p for p in viop["panels"] if p["id"] == "XAU6")
    assert helper["range"] == "A66:E72" and helper["hidden"] and helper["sheet"] == "EK_XAU"
    assert [cell(svc, "EK_XAU!%s66" % c) for c in "BCDE"] == [cell(svc, "VIOP!%s45" % c) for c in "MNO"] + ["Serbest"]
    # what a roll does with each (rowkeys.py): the prices and the forward follow their contract, the rates stay
    assert [(own, st, f) for own, st, f in rk.GOLD_TW] == [(46, 67, False), (50, 68, True), (51, 69, True),
                                                           (52, 70, True), (53, 71, True), (61, 72, False)]


def test_nothing_typed_the_calculator_shows_what_it_showed(svc):
    """Nothing typed: the stores blank, TRY % what the USDTRY contract of the same expiry implies, every member its own
    formula's value off it (as before: every EK_XAU value was compared with the commit before, cell for cell); the free
    column prices nothing until its date and a rate - or another member - are typed."""
    u = svc.login("xau varsayılan")["user"]
    for col, viop in (("B", "N"), ("C", "P"), ("D", "R")):
        implied = (cell(svc, "VIOP!%s13" % viop, u) + cell(svc, "VIOP!%s25" % viop, u)) / 2 * 100
        assert column(svc, u, col) == pytest.approx(Col(svc, u, col).members(implied), rel=1e-12), col
    assert column(svc, u, "E") == dict.fromkeys(MEMBERS, "")
    assert all(cell(svc, "EK_XAU!%s%d" % (c, r), u) is None for c in "BCDE" for r in STORE.values())


# ---------------------------------------------------------------------------------------------- typing
@pytest.mark.parametrize("col", ["B", "D", "E"])
def test_each_member_typed_gives_the_others(svc, col):
    """Any member typed in a column: that value exactly, the others worked out from the TRY rate it gives - the block's
    formulas solved (fwd = spot + SP / 10000 = spot + SP per day · VKGS / 10000 = teorik · 31.1035 / XAUUSD fwd; the O/N
    rate compounded daily on 360) - and back: each value typed again as its own kind gives the same column (1e-9); only
    the one typed last is kept.  The free column once its date and XAUUSD forward are typed."""
    u = svc.login("xau %s" % col)["user"]
    try:
        if col == "E":
            put(svc, u, {"E%d" % ROW["d2"]: "15.01.2027", "E%d" % ROW["xfwd"]: "3990"})
        m = Col(svc, u, col)
        for name, x in SAMPLE.items():
            put(svc, u, {"%s%d" % (col, ROW[name]): x})
            now = column(svc, u, col)
            assert now[name] == x and now == pytest.approx(m.typed(name, x), rel=1e-9, abs=1e-9), (col, name)
            assert stored(svc, u) == {"%s%d" % (col, STORE[name]): x}
            for k in MEMBERS:                                               # each value typed back as its own kind
                put(svc, u, {"%s%d" % (col, ROW[k]): now[k]})
                assert column(svc, u, col) == pytest.approx(now, rel=1e-9, abs=1e-9), (col, name, k)
                assert list(stored(svc, u)) == ["%s%d" % (col, STORE[k])]
    finally:
        svc.reset_inputs(u, "tto")


def test_the_last_typed_wins_and_delete_goes_back_to_the_default(svc):
    """Typing one member of a column clears the one typed before (the other columns keep theirs); Delete on a value
    worked out or on the typed one, a cell's reset ("Kendi girdimi sil") and "Girdilerimi sıfırla": the column shows its
    default again.  The column's other inputs stay the block's: a USD rate typed moves the values worked out, not the
    typed one."""
    u = svc.login("xau son")["user"]
    try:
        default = column(svc, u, "C")
        put(svc, u, {"C53": "7100"})
        assert stored(svc, u) == {"C71": 7100.0}
        put(svc, u, {"C61": "31,5"})
        assert stored(svc, u) == {"C72": 31.5} and cell(svc, ref("on", "C"), u) == 31.5 and cell(svc, ref("teo", "C"), u) != 7100.0
        put(svc, u, {"B50": "52,5", "D51": "70000"})                       # (other columns: their own)
        assert stored(svc, u) == {"C72": 31.5, "B68": 52.5, "D69": 70000.0}
        before = column(svc, u, "B")
        put(svc, u, {"B45": "5"})                                           # another USD rate: the forward typed stays
        after = column(svc, u, "B")
        assert after["fwd"] == 52.5 and after["sp"] == before["sp"] and after["try"] != pytest.approx(before["try"], rel=1e-6)
        assert after == pytest.approx(Col(svc, u, "B").typed("fwd", 52.5), rel=1e-9)
        res = put(svc, u, {"C46": ""})                                      # Delete on a value worked out
        assert res["applied"] == 1 and stored(svc, u) == {"B68": 52.5, "D69": 70000.0} and column(svc, u, "C") == default
        put(svc, u, {"B50": ""})                                            # Delete on the typed value itself
        assert stored(svc, u) == {"D69": 70000.0}
        assert svc.reset_inputs(u, "tto", ["EK_XAU!D53"])["reset"] == 1 and stored(svc, u) == {}
        put(svc, u, {"B53": "6700", "E61": "30"})
        assert stored(svc, u) == {"B71": 6700.0, "E72": 30.0}
        svc.reset_inputs(u, "tto")                                          # "Girdilerimi sıfırla"
        assert stored(svc, u) == {} and column(svc, u, "C") == default
    finally:
        svc.reset_inputs(u, "tto")


def test_a_pasted_row_and_a_scenario(svc):
    """A row of theoretical prices pasted over the four columns: each column's typed value; a scenario saved with them
    loads back as it was."""
    u = svc.login("xau yapıştır")["user"]
    try:
        put(svc, u, {"E41": "15.01.2027", "E48": "3990"})
        res = svc.paste(u, "tto", "EK_XAU!B53", "6700\t7050\t7460\t6800")
        assert res["errors"] == [] and stored(svc, u) == {"B71": 6700.0, "C71": 7050.0, "D71": 7460.0, "E71": 6800.0}
        want = {c: column(svc, u, c) for c in "BCDE"}
        assert [want[c]["teo"] for c in "BCDE"] == [6700.0, 7050.0, 7460.0, 6800.0]
        assert want["E"] == pytest.approx(Col(svc, u, "E").typed("teo", 6800.0), rel=1e-9)
        svc.save_scenario(u, "altın iki yönlü")
        put(svc, u, {"B53": "", "C46": "30"})
        assert stored(svc, u) == {"C67": 30.0, "D71": 7460.0, "E71": 6800.0}
        svc.load_scenario(u, "altın iki yönlü")
        assert stored(svc, u) == {"B71": 6700.0, "C71": 7050.0, "D71": 7460.0, "E71": 6800.0}
        assert {c: column(svc, u, c) for c in "BCDE"} == want
    finally:
        svc.reset_inputs(u, "tto")


def test_values_typed_before_read_as_before(svc):
    """What users typed before this change: a TRY rate typed when it was the page's input is its column's typed value -
    moved to its store once, the column priced exactly as before -, one typed as a formula moves with its formula and
    stays live; a value typed over a worked-out cell ("Elle değer", here the theoretical price) is that column's typed
    value; a scenario saved before loads into the stores."""
    u = svc.login("xau eski")["user"]
    svc.store.set_user_inputs(u, "tto", {"EK_XAU!B46": 40.0, "EK_XAU!C46": 37.25, "EK_XAU!D53": 7400.0},
                              {"EK_XAU!C46": "=EK_XAU!B46-2.75"})
    svc._reload_user(u)
    try:
        assert stored(svc, u) == {"B67": 40.0, "C67": 37.25, "D71": 7400.0}
        assert svc.store.user_formulas(u).get(("tto", "EK_XAU!C67")) == "=EK_XAU!B46-2.75"     # (the formula, live)
        assert column(svc, u, "B") == pytest.approx(Col(svc, u, "B").members(40.0), rel=1e-12)
        assert column(svc, u, "C") == pytest.approx(Col(svc, u, "C").members(37.25), rel=1e-12)
        assert column(svc, u, "D") == pytest.approx(Col(svc, u, "D").typed("teo", 7400.0), rel=1e-9)
        put(svc, u, {"B46": "41"})
        assert cell(svc, ref("try", "C"), u) == pytest.approx(38.25, rel=1e-12)                 # (it reads B's rate)
        book = svc.books["tto"]
        assert book.cell("EK_XAU!D53") not in book.inputs                                      # (no "Elle değer" declared)
        svc.reset_inputs(u, "tto")
        svc.store.save_scenario(u, "eski altın", {("tto", "EK_XAU!B46"): 39.5})
        svc.load_scenario(u, "eski altın")
        assert stored(svc, u) == {"B67": 39.5} and cell(svc, ref("try", "B"), u) == 39.5
    finally:
        svc.reset_inputs(u, "tto")


def test_the_calculator_in_a_temporary_copy(svc):
    """A copy of the calculator: a theoretical price typed there is the copy's - every member has a store, so nothing is
    refused, also where the table itself holds a TRY rate typed in that column -, the table keeps its own; Delete in the
    copy follows the table again."""
    u = svc.login("xau kopya")["user"]
    try:
        put(svc, u, {"B46": "40"})
        cid = svc.copy_action(u, "open", {"view": "viop", "panel": "XAU4"})["copy"]["id"]

        def copy_cell(name, col="B"):
            def run():
                cp = svc.copies.find(u, cid)
                return svc.copies.calc(u, cp).value(ref(name, col))
            return svc.et.call(run)

        assert copy_cell("try") == 40.0                                     # (it starts with the table's typed values)
        res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "EK_XAU!B53", "value": "6750"}]})
        assert res["errors"] == [] and copy_cell("teo") == 6750.0
        m = Col(svc, u, "B")
        assert copy_cell("try") == pytest.approx(m.rate_of("teo", 6750.0), rel=1e-12)
        assert copy_cell("sp") == pytest.approx(m.typed("teo", 6750.0)["sp"], rel=1e-9)
        assert cell(svc, ref("try", "B"), u) == 40.0 and stored(svc, u) == {"B67": 40.0}       # the table's own
        own = next(c for c in svc.copies.items(u) if c.id == cid).values
        assert own["EK_XAU!B71"] == 6750.0 and own.get("EK_XAU!B67", "gone") is None
        res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "EK_XAU!B50", "value": ""}]})
        assert res["applied"] == 1 and copy_cell("try") == 40.0 and copy_cell("teo") == cell(svc, ref("teo", "B"), u)
        svc.copy_action(u, "close", {"copy": cid})
    finally:
        svc.reset_inputs(u, "tto")


def test_the_page_marks_the_typed_value_and_says_how(svc):
    """The VİOP page: the six members of a column inputs (``i``), the typed one marked (``an``), the others worked out
    from it (``ao``); the note under the calculator says what can be typed and what a roll does; the stores in their
    helper table."""
    u = svc.login("xau sayfa")["user"]
    try:
        put(svc, u, {"C52": "425"})
        p = next(x for x in svc.view(u, "viop")["panels"] if x["id"] == "XAU4")
        d = p["data"]
        cells = {name: d["rows"][d["r"].index(ROW[name])][d["c"].index("C")] for name in MEMBERS}
        assert all(cells[n]["i"] == "u" for n in MEMBERS)
        assert cells["spd"]["an"] == "TRY %, USDTRY fwd, SP, XAUTRY teorik, ON karşılık" and cells["spd"]["m"] == 1
        assert cells["try"]["ao"] == "Günlük SP · C52" and cells["teo"]["ao"] == "Günlük SP · C52"
        # every input of the calculator: dates, spots, USD %, swap %, XAUUSD fwd, VİOP bid / ask and the six members
        assert sum(1 for row in d["rows"] for c in row if c.get("i") == "u") == 15 * 4
        assert "İki yönlü: TRY %, USDTRY fwd (All In S -> E), SP, günlük SP, XAUTRY teorik ya da ON karşılık" in p["note"]
        assert "kontratıyla birlikte onun yeni sütununa gider" in p["note"] and "yazılan TRY % ya da ON sütununda kalır" in p["note"]
        helper = next(x for x in svc.view(u, "viop", True)["panels"] if x["id"] == "XAU6")["data"]
        assert helper["rows"][helper["r"].index(66)][0]["t"] == "Yazılan (iki yönlü)"
        assert helper["rows"][helper["r"].index(70)][helper["c"].index("C")]["m"] == 1
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the contracts roll
def _codes(s, codes):
    res = s.set_inputs(s.login("Altın Masa")["user"], "tto",
                       [{"ref": "VIOP!%s45" % c, "value": v} for c, v in zip("MNO", codes)])
    assert res["errors"] == [], res["errors"]
    s.et.call(s.rowkeys.roll)
    assert s.store.get(rk.GOLD_KEY) == list(codes)


def test_a_roll_takes_a_typed_price_with_its_contract_and_leaves_a_typed_rate_in_its_column(tmp_path):
    """The gold contracts roll (the desk types the next three codes here, as the expiry does by itself): a forward, SP,
    SP per day or theoretical price typed for a contract - and one's own VİOP bid / ask, a price too - goes to the column
    the contract sits in now, or with the contract that left the table; a TRY % or ON typed stays in its column (the
    desk's "Evet", 25.11.2026) - each user's, and in the saved scenarios.  A price that would land on a column holding a
    typed value that stays there goes: the column's own stands (one typed value per column).  The free column is no
    contract's: it stays as it is."""
    s = make_service(tmp_path)
    try:
        a, b = s.login("Altın Rol A")["user"], s.login("Altın Rol B")["user"]
        codes = [cell(s, "VIOP!%s45" % c) for c in "MNO"]
        assert codes == ["XLZ6 Comdty", "XLG7 Comdty", "XLJ7 Comdty"] and s.store.get(rk.GOLD_KEY) == codes
        # A: XLZ6's forward (B), XLG7's theoretical price (C), the third column's TRY rate (D), the free column's forward;
        # its own VİOP bid for XLG7 (C) and ask for XLZ6 (B)
        put(s, a, {"B50": "52,4", "C53": "7050", "D46": "36", "E50": "52,9", "C54": "7060", "B55": "6702"})
        # B: the first column's O/N rate (B), XLG7's SP per day (C: it lands on B's rate), XLJ7's SP (D)
        put(s, b, {"B61": "33,5", "C52": "421", "D51": "76000"})
        s.save_scenario(a, "rol öncesi")
        s.save_scenario(b, "rol öncesi")

        def own_prices(user):
            return {k[1]: v for k, v in s.store.user_inputs(user, "tto").items() if k[1][-2:] in ("54", "55")}

        _codes(s, ["XLG7 Comdty", "XLJ7 Comdty", "XLM7 Comdty"])
        # A: XLG7's price now in B, XLZ6's forward gone with it, the rate stays in D, the free column as it was
        assert stored(s, a) == {"B71": 7050.0, "D67": 36.0, "E68": 52.9}
        assert column(s, a, "B") == pytest.approx(Col(s, a, "B").typed("teo", 7050.0), rel=1e-9)
        assert cell(s, ref("try", "D"), a) == 36.0 and cell(s, ref("fwd", "E"), a) == 52.9
        # ... its own VİOP bid for XLG7 with its contract in B, XLZ6's ask gone
        assert own_prices(a) == {"EK_XAU!B54": 7060.0} and cell(s, "EK_XAU!B54", a) == 7060.0
        assert cell(s, "EK_XAU!B55", a) == cell(s, "EK_XAU!B55") and cell(s, "EK_XAU!C54", a) == cell(s, "EK_XAU!C54")
        # B: the O/N rate stays in B (XLG7's SP per day would land on it: it goes), XLJ7's SP now in C
        assert stored(s, b) == {"B72": 33.5, "C69": 76000.0}
        assert cell(s, ref("on", "B"), b) == 33.5 and cell(s, ref("sp", "C"), b) == 76000.0
        assert column(s, b, "C") == pytest.approx(Col(s, b, "C").typed("sp", 76000.0), rel=1e-9)
        # the saved scenarios the same way
        assert s.store.scenario(a, "rol öncesi")[0] == {("tto", "EK_XAU!B71"): 7050.0, ("tto", "EK_XAU!D67"): 36.0,
                                                       ("tto", "EK_XAU!E68"): 52.9, ("tto", "EK_XAU!B54"): 7060.0}
        assert s.store.scenario(b, "rol öncesi")[0] == {("tto", "EK_XAU!B72"): 33.5, ("tto", "EK_XAU!C69"): 76000.0}
        # the desk takes a contract off the table (XLJ7 → XLQ7 in C): its typed price goes; nothing else moves
        _codes(s, ["XLG7 Comdty", "XLQ7 Comdty", "XLM7 Comdty"])
        assert stored(s, a) == {"B71": 7050.0, "D67": 36.0, "E68": 52.9} and stored(s, b) == {"B72": 33.5}
        assert own_prices(a) == {"EK_XAU!B54": 7060.0}
        # ... and back: a contract that comes back to the table finds nothing of its own (what it had went with it)
        _codes(s, ["XLG7 Comdty", "XLJ7 Comdty", "XLM7 Comdty"])
        assert stored(s, b) == {"B72": 33.5}
    finally:
        s.stop()


def test_a_contract_listed_twice_keeps_its_own_column(tmp_path):
    """The desk types a contract already on the table into another column, then takes it back: what was typed for it in
    the column it leaves goes to the column it stays in - unless that column holds its own typed value: then the column's
    own stands."""
    s = make_service(tmp_path)
    try:
        a = s.login("Altın Çift")["user"]
        _codes(s, ["XLJ7 Comdty", "XLG7 Comdty", "XLJ7 Comdty"])          # XLJ7 in B and D, XLZ6 off the table
        put(s, a, {"B53": "7460", "D46": "35"})
        _codes(s, ["XLZ6 Comdty", "XLG7 Comdty", "XLJ7 Comdty"])          # back: XLJ7 stays in D, which holds a rate
        assert stored(s, a) == {"D67": 35.0}
        _codes(s, ["XLJ7 Comdty", "XLG7 Comdty", "XLJ7 Comdty"])
        put(s, a, {"B53": "7460", "D46": ""})
        _codes(s, ["XLZ6 Comdty", "XLG7 Comdty", "XLJ7 Comdty"])          # D holds nothing: XLJ7's price lands there
        assert stored(s, a) == {"D71": 7460.0} and cell(s, ref("teo", "D"), a) == 7460.0
    finally:
        s.stop()
