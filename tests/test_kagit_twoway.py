"""The bonds' tables two-way (the desk, 24.11.2026: "hangisine ben girdiysem diğerini hesaplasın ... Genel olarak tablolar
bu şekilde olmalı karışıklık olmaması için", "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız
için"): what a bond's row says of its price can be typed in the table itself - the one typed last stands exactly, the
others come from the clean price it gives (``tto/extras.py``, "the bonds' tables two-way"; the mechanism: ``tto/twoway.py``,
``test_twoway.py``).

* DİBS RV's bond rows: Manuel temiz (in place), BIST simple / compound yield, yield − OIS, ASW / DM, Z-spread; the repo
  (in place) and the carry; SWITCH / PAIR's yield and ASW / DM differences (the Al leg's price the row's own);
* DİBS ASW's bond rows: Manuel temiz (in place), ASW (the sheet's own OIS curve), the dirty price at the spot - the ASW
  FX column priced at that clean price;
* Manuel Tahvil: the clean price (in place) and its results.

Each member typed is checked against the formula worked by hand from the row's cells; the others against the sheet's
own forward formulas (another user typing that clean price by hand); every computed value typed back as its own kind
gives the same row (1e-9).  What is typed for a bond goes with its ISIN when the bond lists move."""
from __future__ import annotations

import pytest

from conftest import cell, make_service
from tto import extras
from tto.views import load_views
from tto.xl.model import COLS, parse_a1
from tto.xl.tokenizer import index_to_col

RV, ASW, MAN = "DİBS RV", "ASW", "Manuel Tahvil"
LIST, ASW_LIST = "DİBS RV!A5:A54", "ASW!B7:B56"
#: DİBS RV's members: N in place, the others kept in YF:YJ of their row
RV_MEMBERS = ("N", "S", "T", "Y", "Z", "AF")
RV_STORE = dict(extras.RV_TW)
ASW_MEMBERS = ("D", "R", "O")
MAN_MEMBERS = ("B14",) + tuple(m for m, _, _ in extras.MAN_TW)
BILL, FIXED, LONG, FLOATER, NO_PRICE = "TRB170327T15", "TRT150328T24", "TRT051033T12", "TRT030730T12", "TRT081128T15"


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """A service of its own: the tests move bonds on the desk's lists."""
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def put(s, user, book, cells, adhoc=False):
    res = s.set_inputs(user, book, [{"ref": ref, "value": value} for ref, value in cells.items()], allow_adhoc=adhoc)
    assert res["errors"] == [], res["errors"]
    return res


def reader(s, user, sheet, book="tto"):
    return lambda addr: cell(s, "%s!%s" % (sheet, addr), user, book=book)


def row_of(s, user, isin, where=LIST, book="tto"):
    first = int(where.split("!")[1].split(":")[0][1:])
    return s._list_values(user, book, where).index(isin) + first


def block(get, first, last, r):
    c1, c2 = parse_a1(first + "1") % COLS, parse_a1(last + "1") % COLS
    return [get("%s%d" % (index_to_col(c), r)) for c in range(c1, c2 + 1)]


def stored(s, user, sheet, book="tto"):
    return {ref.split("!")[1]: v for (_, ref), v in s.store.user_inputs(user, book).items() if ref.split("!")[0] == sheet}


def members(get, r, cols=RV_MEMBERS):
    return [get("%s%d" % (c, r)) for c in cols]


def close(a, b, tol=1e-9):
    """Two rows equal to ``tol`` (numbers), texts the same."""
    return len(a) == len(b) and all((abs(x - y) <= tol) if isinstance(x, float) and isinstance(y, float) else x == y
                                    for x, y in zip(a, b))


# ---------------------------------------------------------------------------------------------- by hand (DİBS RV)
def rv_yield_price(R, r, y):
    """The clean price at a BIST simple yield: a bill 100 / (1 + y · days / 365), else Σ CF · (1 + y / f)^−x − accrued."""
    if R("CR%d" % r) == "B":
        return 100 / (1 + y * R("DR%d" % r) / 365) - R("CW%d" % r)
    cf, x, f = block(R, "ID", "JA", r), block(R, "LV", "MS", r), R("CU%d" % r)
    return sum(c * (1 + y / f) ** -t for c, t in zip(cf, x)) - R("CW%d" % r)


def rv_compound_price(R, r, t):
    if R("CR%d" % r) == "B":
        return 100 / (1 + t) ** (R("DR%d" % r) / 365) - R("CW%d" % r)
    f = R("CU%d" % r)
    return rv_yield_price(R, r, f * ((1 + t) ** (1 / f) - 1))


def rv_asw_price(R, r, asw):
    return (R("EG%d" % r) - asw * R("EE%d" % r) / 100) / R("DD%d" % r) - R("CW%d" % r)


def rv_dm_price(R, r, dm):
    cf, fw, tau = block(R, "ID", "JA", r), block(R, "NR", "OO", r), block(R, "JZ", "KW", r)
    pv, df = 0.0, 1.0
    for c, f, t in zip(cf, fw, tau):
        df /= 1 + (f + dm / 10000) * t
        pv += c * df
    return pv / R("DD%d" % r) - R("CW%d" % r)


def rv_z_price(R, r, z):
    import math
    cf, df, t = block(R, "ID", "JA", r), block(R, "JB", "JY", r), block(R, "KX", "LU", r)
    return sum(c * d * math.exp(-z / 10000 * x) for c, d, x in zip(cf, df, t)) / R("DD%d" % r) - R("CW%d" % r)


def by_hand(R, r, member, v):
    """The clean price a member's value gives, worked out here from the row's cells."""
    if member == "S":
        return rv_yield_price(R, r, v)
    if member == "T":
        return rv_compound_price(R, r, v)
    if member == "Y":
        return rv_compound_price(R, r, R("EP%d" % r) + v / 10000)
    if member == "Z":
        return rv_dm_price(R, r, v) if R("CR%d" % r) == "T" else rv_asw_price(R, r, v)
    return rv_z_price(R, r, v)


def nudged(R, r, member):
    """A value of ``member`` away from the row's now (the market's)."""
    v = R("%s%d" % (member, r))
    if member == "N":
        return R("O%d" % r) - 0.4375
    return v + (0.0035 if member in ("S", "T") else 17.5)


# ---------------------------------------------------------------------------------------------- the declarations
def test_the_bond_tables_are_two_way_groups(svc):
    """Five groups, every one usable: their stores personal number inputs on blank cells no layout ever had an input on,
    the members' own cells formulas (not inputs) - but the in-place members, the old inputs N, AL, D and B14."""
    s = svc
    assert s.twoway.problems == {}
    assert all(b.left_out == [] for b in s.books.values())
    want = {"dibs-rv": ("tto", ["Manuel temiz", "BIST basit getiri", "BIST bileşik getiri", "Getiri − OIS", "ASW / DM", "Z-spread",
                                "ON karşılık"]),
            "dibs-carry": ("tto", ["Repo", "Carry"]), "dibs-switch": ("tto", ["Getiri farkı", "ASW/DM farkı"]),
            "asw-rv": ("asw", ["Manuel temiz", "ASW", "Kirli @spot"]),
            "manuel": ("tto", ["Temiz fiyat", "Kirli fiyat (valör)", "Kirli fiyat (OIS spot)", "BIST basit getiri",
                               "BIST bileşik getiri", "ASW par-par", "Z-spread", "DM", "Getiri − OIS"])}
    views = {v["id"]: v for v in load_views()}
    for gid, (bid, names) in want.items():
        g = s.twoway.groups[gid]
        book = s.books[bid]
        assert g.book is book and [m.name for m in g.members] == names and g.scope == "user"
        for m in g.members:
            if m.own:
                assert all(book.inputs[c].group not in ("adhoc", "adhoc-shared") for c in m.cells)
                continue
            assert all(book.inputs[c].scope == "user" and book.inputs[c].kind == "number" for c in m.store)
            assert all(c not in book.inputs for c in m.cells)
        declared = set()
        for i in views[g.view]["inputs"]:
            declared.update(book.cells_of(i["range"], views[g.view]["sheet"]))
        stores = {c for m in g.members if not m.own for c in m.store}
        retired = {c for x in extras.RETIRED_INPUTS.get(bid, ()) for c in book.cells_of(x)}
        assert stores and not stores & declared and not stores & retired, gid
    assert [m.own for m in s.twoway.groups["dibs-rv"].members] == [True] + [False] * 6        # (the O/N equivalent's: 26.11.2026)
    assert not any(m.own for m in s.twoway.groups["dibs-switch"].members)          # (both kept in stores)


# ---------------------------------------------------------------------------------------------- DİBS RV
@pytest.mark.parametrize("isin", [BILL, FIXED, LONG, FLOATER])
def test_dibs_rv_each_member_typed_gives_the_clean_price_and_the_others(svc, isin):
    """A yield, compound yield, yield − OIS, ASW / DM or Z-spread typed: that one exactly, the manual clean price the one
    it gives (worked out here from the row's cells), the others the sheet's own at that price (another user typing that
    price by hand sees the same row); a floater has no yields (its DM and Z-spread only)."""
    s = svc
    u, v = s.login("RV iki yönlü %s" % isin)["user"], s.login("RV iki yönlü elle %s" % isin)["user"]
    R, V = reader(s, u, RV), reader(s, v, RV)
    r = row_of(s, u, isin)
    kinds = ("Z", "AF") if R("CR%d" % r) == "T" else ("S", "T", "Y", "Z", "AF")
    for m in kinds:
        x = nudged(R, r, m)
        put(s, u, "tto", {"%s!%s%d" % (RV, m, r): x})
        assert R("%s%d" % (m, r)) == x and stored(s, u, RV) == {"%s%d" % (RV_STORE[m], r): x}
        price = R("N%d" % r)
        assert price == pytest.approx(by_hand(R, r, m, x), abs=1e-9) and R("O%d" % r) == price, (isin, m)
        put(s, v, "tto", {"%s!N%d" % (RV, r): price})
        assert close(members(R, r), members(V, r)), (isin, m, members(R, r), members(V, r))
        assert R("J%d" % r).endswith("(yazılan)") and R("YK%d" % r) == m
    s.reset_inputs(u, "tto")
    s.reset_inputs(v, "tto")


@pytest.mark.parametrize("isin", [BILL, FIXED, LONG, FLOATER])
def test_dibs_rv_every_computed_value_typed_back_gives_the_same_row(svc, isin):
    """Round trips: each member typed, each value it gives typed back as its own kind - the same row (1e-9).  On a row
    priced by hand yield − OIS, ASW / DM and Z-spread are exact (the Z-spread two more of its solver's steps); with nothing
    typed they are the sheet's 0.1 bp, as before."""
    s = svc
    u = s.login("RV gidiş dönüş %s" % isin)["user"]
    R = reader(s, u, RV)
    r = row_of(s, u, isin)
    kinds = ("N", "Z", "AF") if R("CR%d" % r) == "T" else RV_MEMBERS
    for c in ("Y", "Z", "AF"):
        x = R("%s%d" % (c, r))
        assert x == "" or x == round(x, 1)                                          # (nothing typed: 0.1 bp)
    for m in kinds:
        put(s, u, "tto", {"%s!%s%d" % (RV, m, r): nudged(R, r, m)})
        want = members(R, r)
        for k in kinds:
            put(s, u, "tto", {"%s!%s%d" % (RV, k, r): want[RV_MEMBERS.index(k)]})
            assert close(members(R, r), want), (isin, m, k, members(R, r), want)
            assert list(stored(s, u, RV)) == ["%s%d" % (RV_STORE.get(k, k), r)]       # (the one typed only)
    s.reset_inputs(u, "tto")
    assert all(R("%s%d" % (c, r)) in ("",) or R("%s%d" % (c, r)) == round(R("%s%d" % (c, r)), 1) for c in ("Y", "Z", "AF"))


def test_dibs_rv_the_last_typed_wins_and_delete_goes_back_to_the_market(svc):
    """Typing a member empties the row's other typed value (the manual clean price too); Delete on the typed cell or on
    one worked out from it - or a reset - takes the row back to the market."""
    s = svc
    u = s.login("RV son yazılan")["user"]
    R = reader(s, u, RV)
    r = row_of(s, u, FIXED)
    market = members(R, r) + [R("O%d" % r)]
    put(s, u, "tto", {"%s!N%d" % (RV, r): 99.5})
    assert stored(s, u, RV) == {"N%d" % r: 99.5} and R("J%d" % r) == "Manuel"
    put(s, u, "tto", {"%s!Z%d" % (RV, r): -40})
    assert stored(s, u, RV) == {"YI%d" % r: -40.0} and R("Z%d" % r) == -40.0 and R("J%d" % r) == "ASW'den (yazılan)"
    put(s, u, "tto", {"%s!S%d" % (RV, r): 0.37})
    assert stored(s, u, RV) == {"YF%d" % r: 0.37} and R("S%d" % r) == 0.37
    res = put(s, u, "tto", {"%s!AF%d" % (RV, r): ""})                             # Delete on a value worked out from S
    assert stored(s, u, RV) == {} and res["applied"] == 1 and members(R, r) + [R("O%d" % r)] == market
    put(s, u, "tto", {"%s!T%d" % (RV, r): 0.41})
    put(s, u, "tto", {"%s!T%d" % (RV, r): ""})                                     # Delete on the typed value itself
    assert stored(s, u, RV) == {} and members(R, r) == market[:-1]
    put(s, u, "tto", {"%s!Y%d" % (RV, r): -120})
    assert s.reset_inputs(u, "tto", ["%s!N%d" % (RV, r)])["reset"] == 1 and stored(s, u, RV) == {}     # "Kendi girdimi sil"


def test_dibs_rv_a_bond_without_a_price_is_priced_by_a_typed_level(svc):
    """The row's guard (DG) blanks a bond without a price; a level typed prices it - the inverse needs no price - and the
    others follow; Delete: blank again."""
    s = svc
    u = s.login("RV fiyatsız")["user"]
    R = reader(s, u, RV)
    r = row_of(s, u, NO_PRICE)
    assert R("O%d" % r) == "" and R("S%d" % r) == "" and R("DG%d" % r) is False
    put(s, u, "tto", {"%s!Z%d" % (RV, r): 25})
    price = R("N%d" % r)
    assert R("DG%d" % r) is True and price == pytest.approx(rv_asw_price(R, r, 25), abs=1e-9) and R("O%d" % r) == price
    assert isinstance(R("S%d" % r), float) and R("EH%d" % r) == pytest.approx(25, abs=1e-9) and R("J%d" % r) == "ASW'den (yazılan)"
    put(s, u, "tto", {"%s!S%d" % (RV, r): R("S%d" % r)})
    assert R("N%d" % r) == pytest.approx(price, abs=1e-9)
    put(s, u, "tto", {"%s!S%d" % (RV, r): ""})
    assert R("O%d" % r) == "" and R("DG%d" % r) is False and stored(s, u, RV) == {}


def test_dibs_rv_a_level_the_bond_does_not_have_prices_nothing(svc):
    """A floater has no BIST yield here: a yield typed on it stays as typed but prices nothing - the row at the market,
    "Fiyat durumu" says why; its DM still prices it."""
    s = svc
    u = s.login("RV olmayan")["user"]
    R = reader(s, u, RV)
    r = row_of(s, u, FLOATER)
    market = members(R, r)
    put(s, u, "tto", {"%s!S%d" % (RV, r): 0.35})
    assert R("S%d" % r) == 0.35 and R("N%d" % r) == "" and R("YK%d" % r) == ""
    assert [R("%s%d" % (c, r)) for c in ("Z", "AF", "O")] == [market[4], market[5], R("O%d" % r)]
    assert R("J%d" % r).startswith("Yazılan basit getiri bu kâğıtta yok: fiyat piyasadan · ")
    put(s, u, "tto", {"%s!Z%d" % (RV, r): market[4] + 20})
    assert R("YK%d" % r) == "Z" and R("N%d" % r) == pytest.approx(rv_dm_price(R, r, market[4] + 20), abs=1e-9)
    assert R("J%d" % r) == "DM'den (yazılan)" and R("S%d" % r) == ""
    s.reset_inputs(u, "tto")


def test_the_carry_typed_gives_the_repo_it_needs(svc):
    """Repo (in place) and carry: the carry typed -> the repo (the carry's forward formulas solved for it, a floater's
    its own way); either typed back gives the same row; Delete: OIS funding again."""
    s = svc
    u = s.login("RV carry")["user"]
    R = reader(s, u, RV)
    for isin in (BILL, FIXED, FLOATER):
        r = row_of(s, u, isin)
        market = (R("AL%d" % r), R("AM%d" % r))
        assert market[0] == "" and market[1] == round(market[1], 1)
        c = market[1] + 30
        put(s, u, "tto", {"%s!AM%d" % (RV, r): c})
        repo = R("AL%d" % r)
        assert R("AM%d" % r) == c and stored(s, u, RV) == {"YL%d" % r: c} and isinstance(repo, float)
        days = R("L2") - R("DC%d" % r)
        fp = 1 + repo / 100 * days / 365                                            # (the funding factor at that repo)
        ew = (R("EN%d" % r) * days / 365 * 100 + R("DH%d" % r) * (R("EV%d" % r) - fp) if R("CR%d" % r) == "T"
              else R("ET%d" % r) + R("EU%d" % r) - R("DH%d" % r) * fp)
        assert ew * 10000 / R("ED%d" % r) == pytest.approx(c, abs=1e-9), isin
        put(s, u, "tto", {"%s!AL%d" % (RV, r): repo})                                # typed back: the same
        assert R("AM%d" % r) == pytest.approx(c, abs=1e-9) and stored(s, u, RV) == {"AL%d" % r: repo}
        put(s, u, "tto", {"%s!AM%d" % (RV, r): R("AM%d" % r)})
        assert R("AL%d" % r) == pytest.approx(repo, abs=1e-9)
        put(s, u, "tto", {"%s!AL%d" % (RV, r): ""})
        assert (R("AL%d" % r), R("AM%d" % r)) == market and stored(s, u, RV) == {}


# ---------------------------------------------------------------------------------------------- SWITCH / PAIR
PAIRS = {64: (FIXED, "TRT130928T38"), 65: (FIXED, BILL), 66: ("TRT090130T12", FLOATER), 67: (FIXED, "TRT110930T36")}


def test_the_switch_two_way(svc):
    """SWITCH / PAIR: the yield difference (G) typed -> the Al leg's clean price (AA: the yield the Sat leg's + G), the
    ASW / DM difference at it; the ASW / DM difference (I) typed -> the Al leg's price (its ASW / DM the Sat leg's + I)
    and the yield difference at it (DİBS RV's own yield steps: as the page shows it with that price typed for the Al
    bond).  Round trips; the Al bond's own row untouched; Delete: the market's differences; a leg without a yield says so."""
    s = svc
    u, v = s.login("Switch iki yönlü")["user"], s.login("Switch iki yönlü elle")["user"]
    R, V = reader(s, u, RV), reader(s, v, RV)
    for r, (sat, al) in PAIRS.items():
        put(s, u, "tto", {"%s!A%d" % (RV, r): sat, "%s!B%d" % (RV, r): al, "%s!C%d" % (RV, r): 10})
        put(s, v, "tto", {"%s!A%d" % (RV, r): sat, "%s!B%d" % (RV, r): al})
    market = {r: (R("G%d" % r), R("I%d" % r)) for r in PAIRS}
    assert all(R("AA%d" % r) == "" for r in PAIRS)
    for r in (64, 65):
        sat_row, al_row = row_of(s, u, PAIRS[r][0]), row_of(s, u, PAIRS[r][1])
        al_now = (R("N%d" % al_row), R("O%d" % al_row))
        g = market[r][0] + 12.5
        put(s, u, "tto", {"%s!G%d" % (RV, r): g})
        px = R("AA%d" % r)
        assert R("G%d" % r) == g and px == pytest.approx(rv_yield_price(R, al_row, R("S%d" % sat_row) + g / 10000), abs=1e-9)
        assert R("I%d" % r) == pytest.approx(
            (R("EG%d" % al_row) - (px + R("CW%d" % al_row)) * R("DD%d" % al_row)) / R("EE%d" % al_row) * 100 - R("Z%d" % sat_row), abs=1e-9)
        assert (R("N%d" % al_row), R("O%d" % al_row)) == al_now                     # (the Al bond's own row: as it was)
        i = R("I%d" % r)
        put(s, u, "tto", {"%s!I%d" % (RV, r): i})                                   # typed back: the same price and G
        assert R("AA%d" % r) == pytest.approx(px, abs=1e-9) and R("G%d" % r) == pytest.approx(g, abs=1e-9)
        assert stored(s, u, RV).get("AC%d" % r) == i and "AB%d" % r not in stored(s, u, RV)
        put(s, u, "tto", {"%s!I%d" % (RV, r): market[r][1] - 6})
        px = R("AA%d" % r)
        assert px == pytest.approx(rv_asw_price(R, al_row, R("Z%d" % sat_row) + market[r][1] - 6), abs=1e-9)
        put(s, v, "tto", {"%s!N%d" % (RV, al_row): px})                             # the Al bond at that price, by hand
        assert R("G%d" % r) == pytest.approx(V("G%d" % r), abs=1e-9)
        s.reset_inputs(v, "tto", ["%s!N%d" % (RV, al_row)])
        put(s, u, "tto", {"%s!G%d" % (RV, r): R("G%d" % r)})
        assert R("AA%d" % r) == pytest.approx(px, abs=1e-9)
        put(s, u, "tto", {"%s!I%d" % (RV, r): ""})                                  # Delete on the one worked out
        assert (R("G%d" % r), R("I%d" % r), R("AA%d" % r)) == market[r] + ("",)
    # two floaters: the DM difference prices the Al leg, the yield difference cannot (said)
    al_row = row_of(s, u, PAIRS[66][1])
    put(s, u, "tto", {"%s!I66" % RV: 15})
    assert R("AA66") == pytest.approx(rv_dm_price(R, al_row, R("Z%d" % row_of(s, u, PAIRS[66][0])) + 15), abs=1e-9)
    assert R("G66") == ""
    put(s, u, "tto", {"%s!G66" % RV: 10})
    assert R("AA66").startswith("fiyat vermez: bir bacağın getirisi yok") and R("I66") == ""
    s.reset_inputs(u, "tto", ["%s!G66" % RV])
    assert (R("G66"), R("I66"), R("AA66")) == market[66] + ("",)
    # the pair is typed in its row: the desk swaps its two bonds on the trading list - what is typed stays with the pair
    desk = s.login("Switch iki yönlü masa")["user"]
    put(s, u, "tto", {"%s!I64" % RV: market[64][1] + 4})
    before = (R("I64"), R("AA64"), R("G64"))
    a, b = PAIRS[64]
    ra, rb = row_of(s, desk, a), row_of(s, desk, b)
    put(s, desk, "tto", {"%s!A%d" % (RV, ra): b, "%s!A%d" % (RV, rb): a})
    try:
        assert R("I64") == before[0] and isinstance(R("AA64"), float)
        assert R("AA64") == pytest.approx(rv_asw_price(R, row_of(s, u, b), R("Z%d" % row_of(s, u, a)) + before[0]), abs=1e-9)
    finally:
        put(s, desk, "tto", {"%s!A%d" % (RV, ra): a, "%s!A%d" % (RV, rb): b})
    assert (R("I64"), R("AA64"), R("G64")) == before
    s.reset_inputs(u, "tto")
    s.reset_inputs(v, "tto")


# ---------------------------------------------------------------------------------------------- DİBS ASW
def asw_by_hand(A, r, member, v):
    carry = 1 + A("E4") * (A("C4") - A("M%d" % r)) / 365
    if member == "R":
        return (A("P%d" % r) - v / 100 * A("Q%d" % r)) / carry - A("N%d" % r)
    return v / carry - A("N%d" % r)


@pytest.mark.parametrize("isin", [BILL, FIXED, "TRT050935T13"])
def test_dibs_asw_each_member_typed_and_typed_back(svc, isin):
    """DİBS ASW, its own OIS curve: an ASW or the dirty price at the spot typed -> the clean price it gives (worked out
    here), the other at that price as the sheet has it (another user typing that price); every value typed back as its
    own kind gives the same row; the last typed wins; Delete: the market."""
    s = svc
    u, v = s.login("ASW iki yönlü %s" % isin)["user"], s.login("ASW iki yönlü elle %s" % isin)["user"]
    A, V = reader(s, u, ASW, "asw"), reader(s, v, ASW, "asw")
    r = row_of(s, u, isin, ASW_LIST, "asw")
    market = members(A, r, ("D", "L", "R", "O"))
    for m, x in (("R", A("R%d" % r) + 22.5), ("O", A("O%d" % r) - 0.625)):
        put(s, u, "asw", {"ASW!%s%d" % (m, r): x})
        price = A("D%d" % r)
        assert A("%s%d" % (m, r)) == x and price == pytest.approx(asw_by_hand(A, r, m, x), abs=1e-9) and A("L%d" % r) == price
        assert stored(s, u, ASW, "asw") == {"%s%d" % (dict(extras.ASW_TW)[m], r): x} and A("AB%d" % r) == m
        put(s, v, "asw", {"ASW!D%d" % r: price})
        assert close(members(A, r, ASW_MEMBERS), members(V, r, ASW_MEMBERS))
        want = members(A, r, ASW_MEMBERS)
        for k in ASW_MEMBERS:
            put(s, u, "asw", {"ASW!%s%d" % (k, r): want[ASW_MEMBERS.index(k)]})
            assert close(members(A, r, ASW_MEMBERS), want), (isin, m, k)
    put(s, u, "asw", {"ASW!R%d" % r: ""})
    assert members(A, r, ("D", "L", "R", "O")) == market and stored(s, u, ASW, "asw") == {}
    s.reset_inputs(v, "asw")


def test_dibs_asw_fx_prices_a_row_at_the_typed_asws_clean_price(svc):
    """The ASW FX column (the sheet on the FX swap implied curve, a calculation of its own) prices a row whose ASW is typed
    at the clean price that ASW gives on the OIS curve - its ASW FX the same as with that price typed by hand - not at
    the typed OIS ASW; the offshore history's live row likewise reads that price."""
    s = svc
    u, v = s.login("ASW FX iki yönlü")["user"], s.login("ASW FX iki yönlü elle")["user"]
    book = s.books["asw"]
    si = book.model.sheet_index[ASW]
    r = row_of(s, u, FIXED, ASW_LIST, "asw")
    put(s, u, "asw", {"ASW!R%d" % r: -20})
    price = cell(s, "ASW!D%d" % r, u, book="asw")
    put(s, v, "asw", {"ASW!D%d" % r: price})

    def fx(user):
        calc, _ = s._asw_fx_calc(book, user)
        return [calc.get(si, r, parse_a1("%s1" % c) % COLS) for c in ("L", "R")]

    got, want = s.et.call(lambda: fx(u)), s.et.call(lambda: fx(v))
    assert got[0] == price and got == pytest.approx(want, abs=1e-9) and abs(got[1] - (-20)) > 1
    rows = {p["id"]: p for p in s.view(u, "asw")["panels"]}["tbl"]["data"]
    line = rows["rows"][rows["r"].index(r)]
    assert line[rows["c"].index("ASW FX")]["v"] == pytest.approx(got[1], abs=1e-9)
    # the offshore history's live row (its second selected bond's price, ASW!V65) reads that clean price as well
    w = row_of(s, u, cell(s, "ASW!C60", u, book="asw"), ASW_LIST, "asw")
    put(s, u, "asw", {"ASW!R%d" % w: -35})
    p2 = cell(s, "ASW!L%d" % w, u, book="asw")
    put(s, v, "asw", {"ASW!D%d" % w: p2})

    def live(user):
        layer, _ = s._asw_hist_fx(book, user)
        return layer.get(si, 65, parse_a1("V1") % COLS)

    assert s.et.call(lambda: live(u)) == p2 == s.et.call(lambda: live(v))
    s.reset_inputs(u, "asw")
    s.reset_inputs(v, "asw")


def test_dibs_asw_a_bond_without_a_price_is_priced_by_a_typed_asw(svc):
    """The row's guard (BB) blanks a bond without a price (its Bloomberg mid typed over as nothing); an ASW typed prices
    it; Delete: blank again."""
    s = svc
    u = s.login("ASW fiyatsız")["user"]
    A = reader(s, u, ASW, "asw")
    r = row_of(s, u, FIXED, ASW_LIST, "asw")
    put(s, u, "asw", {"ASW!AW%d" % r: 0}, adhoc=True)
    assert A("L%d" % r) == "" and A("R%d" % r) == "" and A("U%d" % r) == "Fiyat yok"
    put(s, u, "asw", {"ASW!R%d" % r: 40})
    assert A("L%d" % r) == pytest.approx(asw_by_hand(A, r, "R", 40), abs=1e-9) and A("U%d" % r) == "OK"
    put(s, u, "asw", {"ASW!R%d" % r: ""})
    assert A("L%d" % r) == ""
    s.reset_inputs(u, "asw")


# ---------------------------------------------------------------------------------------------- Manuel Tahvil
def man_by_hand(M, m, v):
    """The clean price a result's value gives, worked out here from the period table."""
    import math
    S = [M("S%d" % k) for k in range(24, 64)]
    W = [M("W%d" % k) for k in range(24, 64)]
    T = [M("T%d" % k) for k in range(24, 64)]
    V = [M("V%d" % k) for k in range(24, 64)]
    f, acc, fund = M("B8"), M("F3"), M("B6")

    def at_yield(y):
        return sum(c * (1 + y / f) ** -x for c, x in zip(S, W)) - acc
    if m == "F4":
        return v - acc
    if m == "F6":
        return v / fund - acc
    if m == "F7":
        return at_yield(v)
    if m == "F8":
        return at_yield(f * ((1 + v) ** (1 / f) - 1))
    if m == "I5":
        return at_yield(f * ((1 + M("I4") + v / 10000) ** (1 / f) - 1))
    if m == "F15":
        return (M("F13") - v / 100 * M("F14")) / fund - acc
    if m == "F16":
        return sum(c * d * math.exp(-v / 10000 * x) for c, d, x in zip(S, T, V)) / fund - acc
    # DM: the cash flows at the forwards + DM, period by period
    pv, lt = 0.0, 0.0
    for k in range(24, 64):
        if M("I%d" % k):
            lt += math.log(1 + (M("Y%d" % k) + v / 10000) * M("U%d" % k))
        pv += M("S%d" % k) * math.exp(-lt)
    return pv / fund - acc


def test_manuel_tahvil_each_result_typed_gives_the_price_over_the_isins(svc):
    """Manuel Tahvil with a bond picked by its ISIN: each result typed -> the clean price it gives (worked out here) - in
    place of the ISIN's price, which a typed result comes before -, the others from that price; every value typed back
    gives the same results; the status says the price is a typed result's; Delete: the ISIN's price again, and without
    an ISIN the file's."""
    s = svc
    u = s.login("Manuel iki yönlü")["user"]
    M = reader(s, u, MAN)
    put(s, u, "tto", {"%s!B17" % MAN: FIXED})
    isin_price = M("B14")
    assert isin_price == cell(s, "%s!O%d" % (RV, row_of(s, u, FIXED)), u)
    for m in MAN_MEMBERS[1:]:
        x = M(m) + (0.004 if m in ("F7", "F8") else (0.55 if m in ("F4", "F6") else 13.5))
        put(s, u, "tto", {"%s!%s" % (MAN, m): x})
        assert M(m) == x and M("B14") == pytest.approx(man_by_hand(M, m, x), abs=1e-9) and M("B14") != isin_price, m
        assert stored(s, u, MAN) == {"B17": FIXED, dict((a, b) for a, b, _ in extras.MAN_TW)[m]: x}
        assert "elle yazılan (önce gelir): fiyat (yazılan sonuçtan)" in M("C17")
        want = [M(k) for k in MAN_MEMBERS]
        for k in MAN_MEMBERS:
            put(s, u, "tto", {"%s!%s" % (MAN, k): want[MAN_MEMBERS.index(k)]})
            assert close([M(j) for j in MAN_MEMBERS], want), (m, k)
        put(s, u, "tto", {"%s!%s" % (MAN, m): ""})
        assert M("B14") == isin_price and stored(s, u, MAN) == {"B17": FIXED}
    put(s, u, "tto", {"%s!I3" % MAN: -60})
    s.reset_inputs(u, "tto", ["%s!B17" % MAN])                                       # (no ISIN: the file's terms)
    assert M("I3") == -60 and M("B14") == pytest.approx(man_by_hand(M, "I3", -60), abs=1e-9) and M("B7") == 47373.0
    put(s, u, "tto", {"%s!F4" % MAN: ""})
    assert M("B14") == 90.1 and stored(s, u, MAN) == {}


# ---------------------------------------------------------------------------------------------- what users typed before
def test_values_typed_before_read_as_before(svc):
    """What an earlier version kept: the manual clean prices (DİBS RV N, DİBS ASW D, Manuel Tahvil B14) and the repo (AL)
    typed in their own cells - the row's typed value, as before, its members worked out from it; a value typed over a
    member's cell ("Elle değer" over DİBS RV's ASW, the ASW sheet's ASW) - that row's typed value, moved to its store."""
    s = svc
    u, v = s.login("iki yönlü eski")["user"], s.login("iki yönlü eski elle")["user"]
    R, A = reader(s, u, RV), reader(s, u, ASW, "asw")
    r, ra = row_of(s, u, FIXED), row_of(s, u, LONG)
    w = row_of(s, u, FIXED, ASW_LIST, "asw")
    s.store.set_user_inputs(u, "tto", {"%s!N%d" % (RV, r): 99.25, "%s!AL%d" % (RV, r): 41.0, "%s!Z%d" % (RV, ra): -150.0,
                                       "%s!B14" % MAN: 97.5})
    s.store.set_user_inputs(u, "asw", {"ASW!D%d" % w: 99.75, "ASW!R%d" % (w + 1): -30.0})
    s._reload_user(u)
    assert stored(s, u, RV) == {"N%d" % r: 99.25, "AL%d" % r: 41.0, "YI%d" % ra: -150.0} and stored(s, u, MAN) == {"B14": 97.5}
    assert stored(s, u, ASW, "asw") == {"D%d" % w: 99.75, "Z%d" % (w + 1): -30.0}
    put(s, v, "tto", {"%s!N%d" % (RV, r): 99.25, "%s!AL%d" % (RV, r): 41.0})
    V = reader(s, v, RV)
    assert members(R, r) + [R("AL%d" % r), R("AM%d" % r)] == members(V, r) + [V("AL%d" % r), V("AM%d" % r)]
    assert R("Z%d" % ra) == -150.0 and R("N%d" % ra) == pytest.approx(rv_asw_price(R, ra, -150.0), abs=1e-9)
    assert A("L%d" % w) == 99.75 and A("R%d" % (w + 1)) == -30.0
    assert cell(s, "%s!B14" % MAN, u) == 97.5
    _, m = marks(s, u, "dibs", "B3")
    assert m["Z%d" % ra]["an"] and m["N%d" % ra]["ao"] == "ASW / DM · Z%d" % ra and m["N%d" % r]["an"]
    s.reset_inputs(u, "tto")
    s.reset_inputs(u, "asw")
    s.reset_inputs(v, "tto")


# ---------------------------------------------------------------------------------------------- rows move
def test_what_is_typed_goes_with_its_bond_when_the_lists_move(svc):
    """The desk swaps two bonds of the trading list (and of the ASW list): each user's typed yield, ASW and carry go with
    their bond - worked out on its new row (the recorded file pins each row's Bloomberg answers to the row: checked
    against the new row's own cells) - and come back when the bonds do."""
    s = svc
    u, desk = s.login("iki yönlü kayan")["user"], s.login("iki yönlü kayan masa")["user"]
    R, A = reader(s, u, RV), reader(s, u, ASW, "asw")
    a, b = FIXED, "TRT130928T38"
    ra, rb = row_of(s, u, a), row_of(s, u, b)
    put(s, u, "tto", {"%s!S%d" % (RV, ra): 0.371, "%s!Z%d" % (RV, rb): -55.0, "%s!AM%d" % (RV, rb): -20.0})
    wa, wb = row_of(s, u, a, ASW_LIST, "asw"), row_of(s, u, b, ASW_LIST, "asw")
    put(s, u, "asw", {"ASW!R%d" % wa: -45.0, "ASW!O%d" % wb: 104.0})
    res = put(s, desk, "tto", {"%s!A%d" % (RV, ra): b, "%s!A%d" % (RV, rb): a})
    try:
        assert {m["isin"] for m in res["row_values"]["moved"]} >= {a, b}
        assert stored(s, u, RV) == {"YF%d" % rb: 0.371, "YI%d" % ra: -55.0, "YL%d" % ra: -20.0}
        assert R("S%d" % rb) == 0.371 and R("N%d" % rb) == pytest.approx(rv_yield_price(R, rb, 0.371), abs=1e-9)
        assert R("Z%d" % ra) == -55.0 and R("N%d" % ra) == pytest.approx(rv_asw_price(R, ra, -55.0), abs=1e-9)
        assert R("AM%d" % ra) == -20.0 and isinstance(R("AL%d" % ra), float)
    finally:
        put(s, desk, "tto", {"%s!A%d" % (RV, ra): a, "%s!A%d" % (RV, rb): b})
    assert stored(s, u, RV) == {"YF%d" % ra: 0.371, "YI%d" % rb: -55.0, "YL%d" % rb: -20.0}
    res = put(s, desk, "asw", {"ASW!B%d" % wa: b, "ASW!B%d" % wb: a})
    try:
        assert {m["isin"] for m in res["row_values"]["moved"]} >= {a, b}
        assert stored(s, u, ASW, "asw") == {"Z%d" % wb: -45.0, "AA%d" % wa: 104.0}
        assert A("R%d" % wb) == -45.0 and A("D%d" % wb) == pytest.approx(asw_by_hand(A, wb, "R", -45.0), abs=1e-9)
        assert A("O%d" % wa) == 104.0 and A("D%d" % wa) == pytest.approx(asw_by_hand(A, wa, "O", 104.0), abs=1e-9)
    finally:
        put(s, desk, "asw", {"ASW!B%d" % wa: a, "ASW!B%d" % wb: b})
    assert stored(s, u, ASW, "asw") == {"Z%d" % wa: -45.0, "AA%d" % wb: 104.0}
    s.reset_inputs(u, "tto")
    s.reset_inputs(u, "asw")


# ---------------------------------------------------------------------------------------------- paste, scenario
def test_a_column_pasted_and_a_scenario(svc):
    """A column of ASWs pasted from Excel into DİBS RV's ASW / DM: each row's typed value; a column of manual clean prices
    over two of them: those rows' prices; a scenario with every kind loads back as it was."""
    s = svc
    u = s.login("iki yönlü yapıştır")["user"]
    R = reader(s, u, RV)
    first = row_of(s, u, FIXED)
    rows = [first, first + 1, first + 2]
    res = s.paste(u, "tto", "%s!Z%d" % (RV, first), "-50\n-60,5\n-70")
    assert res["errors"] == [] and res["applied"] == 3
    assert [R("Z%d" % r) for r in rows] == [-50.0, -60.5, -70.0]
    assert [R("N%d" % r) for r in rows] == pytest.approx([rv_asw_price(R, r, z) for r, z in zip(rows, (-50, -60.5, -70))], abs=1e-9)
    s.paste(u, "tto", "%s!N%d" % (RV, first), "99\n98")
    assert stored(s, u, RV) == {"N%d" % first: 99.0, "N%d" % (first + 1): 98.0, "YI%d" % (first + 2): -70.0}
    put(s, u, "tto", {"%s!AF%d" % (RV, first + 3): -30, "%s!I64" % RV: 5, "%s!F7" % MAN: 0.36})
    want = {r: members(R, r) for r in rows + [first + 3]}
    s.save_scenario(u, "kâğıt iki yönlü")
    s.reset_inputs(u, "tto")
    assert stored(s, u, RV) == {}
    s.load_scenario(u, "kâğıt iki yönlü")
    assert {r: members(R, r) for r in rows + [first + 3]} == want and cell(s, "%s!F7" % MAN, u) == 0.36
    s.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- who reads the price
def test_what_reads_the_bonds_price_reads_the_hypothetical_one(svc):
    """A level typed is a clean price of the user's: Manuel Tahvil's ISIN default, Tüm Kâğıtlar' yield and ASW of the bond,
    the switch's legs all read it - and nobody else's (the desk's calculation) moves."""
    s = svc
    u = s.login("iki yönlü okuyan")["user"]
    R = reader(s, u, RV)
    r = row_of(s, u, FIXED)
    desk_o = cell(s, "%s!O%d" % (RV, r))
    put(s, u, "tto", {"%s!Z%d" % (RV, r): -35.0, "%s!B17" % MAN: FIXED,
                      "%s!A70" % RV: FIXED, "%s!B70" % RV: "TRT130928T38"})
    price = R("O%d" % r)
    assert price != desk_o and cell(s, "%s!B14" % MAN, u) == price
    uni = "%s!A%d:A%d" % (extras.UNI_SHEET, extras.UNI_FIRST, extras.UNI_LAST)
    k = extras.UNI_FIRST + s._list_values(u, "tto", uni).index(FIXED)
    assert cell(s, "%s!O%d" % (extras.UNI_SHEET, k), u) == -35.0 and cell(s, "%s!N%d" % (extras.UNI_SHEET, k), u) == R("T%d" % r)
    assert R("I70") == pytest.approx(R("Z%d" % row_of(s, u, "TRT130928T38")) + 35.0, abs=1e-9)
    assert cell(s, "%s!O%d" % (RV, r)) == desk_o
    s.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the pages
def marks(s, user, view, pid):
    p = next(p for p in s.view(user, view, True)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


def test_the_pages_mark_the_typed_value_and_say_what_the_tables_do(svc):
    """The pages: the members typeable (``i``), the typed one marked (``an``: the members worked out from it), the others
    ``ao``; the notes under the tables; the stores in hidden helper tables of the page (within the columns that move with
    the ISIN); the switch's price column at its right."""
    s = svc
    u = s.login("iki yönlü sayfa")["user"]
    r = row_of(s, u, FIXED)
    put(s, u, "tto", {"%s!Z%d" % (RV, r): -42, "%s!AM%d" % (RV, r): 10, "%s!A64" % RV: FIXED, "%s!B64" % RV: "TRT130928T38",
                      "%s!G64" % RV: 3, "%s!F16" % MAN: -50})
    put(s, u, "asw", {"ASW!O%d" % row_of(s, u, FIXED, ASW_LIST, "asw"): 104.5})
    p, m = marks(s, u, "dibs", "B3")
    assert p["note"].count("İki yönlü: Manuel temiz, BIST basit / bileşik getiri") == 1 and "Repo ile carry de iki yönlüdür" in p["note"]
    assert all(m["%s%d" % (c, r)]["i"] == "u" for c in RV_MEMBERS + ("AL", "AM"))
    assert m["Z%d" % r]["an"] == "Manuel temiz, BIST basit getiri, BIST bileşik getiri, Getiri − OIS, Z-spread, ON karşılık"
    assert m["S%d" % r]["ao"] == "ASW / DM · Z%d" % r and m["AL%d" % r]["ao"] == "Carry · AM%d" % r and m["AM%d" % r]["an"] == "Repo"
    assert m["J%d" % r]["t"] == "ASW'den (yazılan)"
    p, m = marks(s, u, "dibs", "B4")
    assert p["range"] == "A62:AA78" and m["G64"]["an"] == "ASW/DM farkı" and m["I64"]["ao"] == "Getiri farkı · G64"
    assert "İki yönlü: getiri farkı ya da ASW/DM farkı" in p["note"] and isinstance(m["AA64"]["v"], float)
    assert m["AA63"]["t"] == "Al temiz (yazılan farktan)"
    p, m = marks(s, u, "asw", "tbl")
    w = row_of(s, u, FIXED, ASW_LIST, "asw")
    assert m["O%d" % w]["an"] == "Manuel temiz, ASW" and m["R%d" % w]["ao"] == "Kirli @spot · O%d" % w
    assert p["note"].endswith("kâğıdıyla gider.") and "İki yönlü: Manuel temiz, ASW ya da kirli @spot" in p["note"]
    p, m = marks(s, u, "manuel", "B3")
    assert m["F16"]["an"] and m["F7"]["ao"] == "Z-spread · F16" and "İki yönlü: temiz fiyat ya da sonuçlardan biri" in p["note"]
    _, m = marks(s, u, "manuel", "B2")
    assert m["B14"]["ao"] == "Z-spread · F16"
    # the stores: in hidden helper tables of their page (and DİBS RV's / ASW's in the columns that go with the ISIN)
    pages = {v["id"]: v for v in load_views()}
    for vid, pid, rng in (("dibs", "tw", "YF3:YP54"), ("dibs", "B4t", "AB62:AJ75"), ("asw", "tw", "Z6:AB56"),
                          ("manuel", "B11", "AO17:AP25")):
        p = next(p for p in pages[vid]["panels"] if p["id"] == pid)
        assert p["range"] == rng and p["hidden"] is True
    from tto import rowkeys
    band = next(x for x in rowkeys.LISTS if x.id == "asw").band["ASW"]
    assert band[0] <= parse_a1("Z1") % COLS and parse_a1("AB1") % COLS <= band[1]
    s.reset_inputs(u, "tto")
    s.reset_inputs(u, "asw")
