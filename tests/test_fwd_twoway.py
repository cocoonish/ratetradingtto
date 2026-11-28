"""FORWARD KOTASYON two-way (the desk, 24.11.2026: "ben hazırda olan forward kotasyon kısmında hem spread hem faizler
girdi olabilsin, hangisine ben girdiysem diğerini hesaplasın"): in the USDTRY and EURTRY quote matrices a value date's
spread, TRY %, puan and fwd - bid and ask apart - can each be typed; the one typed last stands, the other three are
worked out from it with the matrix's own formulas and their exact inverses (``extras.fwd_outright`` / ``fwd_rate``).
The mechanism itself (``tto/twoway.py``): ``test_twoway.py``."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import extras
from tto.render import fill_tone, tone
from tto.xl.model import COLS, parse_a1

USD_ROWS = range(extras.FWD_ROWS[0], extras.FWD_ROWS[0] + 6)             # 1M … 12M
EUR_ROWS = range(extras.FWD_EUR_ROWS[0], extras.FWD_EUR_ROWS[0] + 6)
#: per side: spread, TRY %, puan, fwd, spot
SIDES = (("D", "M", "H", "J", "F"), ("E", "N", "I", "K", "G"))
KINDS = ("spread", "try", "puan", "fwd")


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": "EK_FWD!" + ref, "value": v} for ref, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def ref(kind, r, side):
    return "%s%d" % (SIDES[side][KINDS.index(kind)], r)


def quote(svc, user, r, side):
    """(spread, TRY %, puan, fwd) of a row-side as the matrix shows it."""
    return [cell(svc, "EK_FWD!" + ref(k, r, side), user) for k in KINDS]


def market(svc, user, r, side):
    """What the row-side's quote is made of: (days, OIS %, USD / EUR %, spot)."""
    return [cell(svc, "EK_FWD!%s%d" % (c, r), user) for c in ("C", "L", "O", SIDES[side][4])]


def from_rate(svc, user, r, side, rate):
    """The row-side's quote off a TRY rate, worked out here: spread = TRY − OIS, fwd = spot·(1+TRY·g/360)/(1+major·g/360),
    puan = (fwd − spot)·10000."""
    days, ois, major, spot = market(svc, user, r, side)
    fwd = spot * (1 + rate / 100 * days / 360) / (1 + major / 100 * days / 360)
    return [(rate - ois) * 100, rate, (fwd - spot) * 10000, fwd]


def rate_of(svc, user, r, side, fwd):
    """The TRY rate an outright implies: ((fwd/spot)·(1+major·g/360) − 1)·360/g."""
    days, _, major, spot = market(svc, user, r, side)
    return ((fwd / spot) * (1 + major / 100 * days / 360) - 1) * 360 / days * 100


def stored(svc, user):
    return {k.split("!")[1]: v for (_, k), v in svc.store.user_inputs(user, "tto").items() if k.startswith("EK_FWD!")}


def panel(svc, user, view, pid):
    p = next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


# ---------------------------------------------------------------------------------------------- the declaration
def test_the_matrices_are_two_way_groups_on_cells_no_input_ever_stood_on(svc):
    """Both matrices are groups of five members (spread in place - its old inputs D:E -, TRY % / puan / fwd kept in AN:AS
    of the same rows, the ON karşılık of 26.11.2026 in AX:AY: test_fwd_on.py); the stores are personal number inputs on
    cells no layout ever had an input on."""
    assert svc.twoway.problems == {}
    book = svc.books["tto"]
    for gid, (r1, r2) in (("ekfwd-quote", extras.FWD_ROWS), ("ekfwd-eur-quote", extras.FWD_EUR_ROWS)):
        g = svc.twoway.groups[gid]
        assert [m.name for m in g.members] == ["Spread", "TRY %", "Puan", "Fwd", "ON %"] and g.shape == (r2 - r1 + 1, 2)
        assert g.members[0].own and g.members[0].cells == book.cells_of("EK_FWD!D%d:E%d" % (r1, r2))
        for m, cols, store in zip(g.members[1:], ("M:N", "H:I", "J:K"), ("AN:AO", "AP:AQ", "AR:AS")):
            a, b = cols.split(":")
            sa, sb = store.split(":")
            assert m.cells == book.cells_of("EK_FWD!%s%d:%s%d" % (a, r1, b, r2))
            assert m.store == book.cells_of("EK_FWD!%s%d:%s%d" % (sa, r1, sb, r2))
            assert all(book.inputs[c].scope == "user" and book.inputs[c].kind == "number" for c in m.store)
            assert all(c not in book.inputs for c in m.cells)
    retired = set()
    for x in extras.RETIRED_INPUTS["tto"]:
        retired.update(book.cells_of(x))
    stores = {c for g in ("ekfwd-quote", "ekfwd-eur-quote") for m in svc.twoway.groups[g].members[1:] for c in m.store}
    from tto.views import load_views
    view = next(v for v in load_views() if v["id"] == "forward")
    declared = set()
    for i in view["inputs"]:
        declared.update(book.cells_of(i["range"], "Forward"))
    assert not stores & retired and not stores & declared and len(stores) == 160


# ---------------------------------------------------------------------------------------------- each kind typed
@pytest.mark.parametrize("rows", [USD_ROWS, EUR_ROWS], ids=["USDTRY", "EURTRY"])
def test_each_kind_typed_gives_the_other_three(svc, rows):
    """A TRY %, a puan, a fwd or a spread typed for a value date's side: that one exactly, the other three worked out from
    it - the matrix's conventions (EURTRY: its spot, the EUR rate, days from the EURTRY spot date)."""
    u = svc.login("çy türler %d" % rows[0])["user"]
    for r in (rows[0], rows[2], rows[5]):
        for side in (0, 1):
            days, ois, major, spot = market(svc, u, r, side)
            rate = round(ois - 1.234 + 0.3 * side, 4)
            put(svc, u, {ref("try", r, side): rate})
            got = quote(svc, u, r, side)
            assert got[1] == rate and got == pytest.approx(from_rate(svc, u, r, side, rate), abs=1e-9), (r, side)
            pts = round(got[2] + 150.5, 1)
            put(svc, u, {ref("puan", r, side): pts})
            got = quote(svc, u, r, side)
            assert got[2] == pts and got[3] == spot + pts / 10000
            assert got == pytest.approx(from_rate(svc, u, r, side, rate_of(svc, u, r, side, spot + pts / 10000)), abs=1e-9)
            fwd = round(got[3] - 0.0123, 4)
            put(svc, u, {ref("fwd", r, side): fwd})
            got = quote(svc, u, r, side)
            assert got[3] == fwd and got == pytest.approx(from_rate(svc, u, r, side, rate_of(svc, u, r, side, fwd)), abs=1e-9)
            put(svc, u, {ref("spread", r, side): -77})
            got = quote(svc, u, r, side)
            assert got[0] == -77.0 and got == pytest.approx(from_rate(svc, u, r, side, ois - 0.77), abs=1e-9)
    # the other side of a row and the rows not typed into keep the general spread
    assert quote(svc, u, rows[1], 0)[0] == cell(svc, "EK_FWD!D%d" % (rows[0] - 1), u)


@pytest.mark.parametrize("kind", KINDS)
def test_a_computed_value_typed_back_gives_the_same_row(svc, kind):
    """Round trips: one kind typed, each value it gives typed back as its own kind - the same four values (1e-9)."""
    u = svc.login("çy gidiş dönüş " + kind)["user"]
    for r in (USD_ROWS[1], EUR_ROWS[3]):
        for side in (0, 1):
            days, ois, major, spot = market(svc, u, r, side)
            start = {"spread": -123.0, "try": round(ois - 0.95, 3), "puan": 9876.5, "fwd": round(spot + 0.4321, 4)}[kind]
            put(svc, u, {ref(kind, r, side): start})
            want = quote(svc, u, r, side)
            for k in KINDS:
                put(svc, u, {ref(k, r, side): want[KINDS.index(k)]})
                assert quote(svc, u, r, side) == pytest.approx(want, abs=1e-9), (r, side, kind, k)
                assert list(stored(svc, u)) == [store_of(svc, k, r, side)]                 # (that one typed only)
            put(svc, u, {ref(kind, r, side): ""})


def store_of(svc, kind, r, side):
    """Where a value typed into a member's cell is kept (the spread: its own cell)."""
    book = svc.books["tto"]
    return book.ref(*book.twoway[book.cell("EK_FWD!" + ref(kind, r, side))].store_cell).split("!")[1]


def test_the_last_typed_wins_and_delete_goes_back_to_the_default(svc):
    """Typing one of the four clears the row-side's other typed value; Delete on any of them (or a reset of a cell of the
    row) takes it back to the general spread."""
    u = svc.login("çy son yazılan")["user"]
    r = USD_ROWS[2]
    general = cell(svc, "EK_FWD!D4", u)
    put(svc, u, {"D%d" % r: -60})
    assert stored(svc, u) == {"D%d" % r: -60.0}
    put(svc, u, {"M%d" % r: 41.5})
    assert stored(svc, u) == {"AN%d" % r: 41.5} and cell(svc, "EK_FWD!M%d" % r, u) == 41.5
    put(svc, u, {"H%d" % r: 20000})
    assert stored(svc, u) == {"AP%d" % r: 20000.0}
    put(svc, u, {"K%d" % r: 55.5})                                                 # the ask side: its own
    assert stored(svc, u) == {"AP%d" % r: 20000.0, "AS%d" % r: 55.5}
    put(svc, u, {"J%d" % r: 52.25})
    assert stored(svc, u) == {"AR%d" % r: 52.25, "AS%d" % r: 55.5}
    res = put(svc, u, {"D%d" % r: ""})                                              # Delete on the spread (computed)
    assert stored(svc, u) == {"AS%d" % r: 55.5} and res["applied"] == 1
    assert quote(svc, u, r, 0) == pytest.approx(from_rate(svc, u, r, 0, cell(svc, "EK_FWD!L%d" % r, u) + general / 100), abs=1e-9)
    put(svc, u, {"K%d" % r: ""})                                                    # Delete on the typed value itself
    assert stored(svc, u) == {} and cell(svc, "EK_FWD!E%d" % r, u) == cell(svc, "EK_FWD!E4", u)
    put(svc, u, {"N%d" % r: 40})
    assert svc.reset_inputs(u, "tto", ["EK_FWD!I%d" % r])["reset"] == 1 and stored(svc, u) == {}       # "Kendi girdimi sil"


def test_a_spread_typed_before_reads_exactly_as_before(svc):
    """A spread users typed before (kept at D5:E14 / D104:E113, as an earlier version saved it): the row-side's typed
    value - the TRY rate OIS + spread, the forward and points from it, as before; marked as typed."""
    u = svc.login("çy eski spread")["user"]
    svc.store.set_user_inputs(u, "tto", {"EK_FWD!D6": -35.0, "EK_FWD!E104": -40.0})
    svc.et.call(svc._reload_user, u)
    assert stored(svc, u) == {"D6": -35.0, "E104": -40.0}
    for r, side, s in ((6, 0, -35.0), (104, 1, -40.0)):
        ois = cell(svc, "EK_FWD!L%d" % r, u)
        got = quote(svc, u, r, side)
        assert got[0] == s and got[1] == ois + s / 100 and got == pytest.approx(from_rate(svc, u, r, side, ois + s / 100), abs=1e-9)
    _, m = panel(svc, u, "forward", "EKF1")
    assert m["D6"]["an"] == "TRY %, Puan, Fwd, ON %" and m["D6"]["m"] == 1 and m["M6"]["ao"] == "Spread · D6"
    assert "an" not in m["E6"] and "ao" not in m["E6"]                             # (its ask side: nothing typed)


def test_piyasa_spread_mode_sets_the_default_only(svc):
    """"Piyasa spread": the default is the market's spread (offshore implied − OIS) of the date; a typed spread stands
    over it, as before, and so does a typed TRY % (its spread worked out from it, not the market's); Delete: the
    market's again."""
    u = svc.login("çy piyasa")["user"]
    r = USD_ROWS[1]
    put(svc, u, {"B4": extras.FWD_SPREAD_MARKET})
    mkt = cell(svc, "EK_FWD!V%d" % r, u)
    assert isinstance(mkt, float) and cell(svc, "EK_FWD!D%d" % r, u) == mkt
    put(svc, u, {"D%d" % r: -10})
    assert cell(svc, "EK_FWD!D%d" % r, u) == -10.0
    ois = cell(svc, "EK_FWD!L%d" % r, u)
    put(svc, u, {"M%d" % r: round(ois + 0.5, 2)})
    assert cell(svc, "EK_FWD!D%d" % r, u) == pytest.approx((round(ois + 0.5, 2) - ois) * 100, abs=1e-9)
    put(svc, u, {"M%d" % r: ""})
    assert cell(svc, "EK_FWD!D%d" % r, u) == mkt and stored(svc, u) == {"B4": extras.FWD_SPREAD_MARKET}


def test_a_column_pasted_and_a_scenario(svc):
    """A column of TRY rates pasted from Excel: each date's typed value; a column of spreads over them: the spreads; a
    scenario saved with every kind loads back as it was."""
    u = svc.login("çy yapıştır")["user"]
    rates = [round(cell(svc, "EK_FWD!L%d" % r, u) - 1, 2) for r in USD_ROWS]
    res = svc.paste(u, "tto", "EK_FWD!M%d" % USD_ROWS[0], "\n".join(("%.2f" % x).replace(".", ",") for x in rates))
    assert res["errors"] == [] and res["applied"] == 6
    assert [cell(svc, "EK_FWD!M%d" % r, u) for r in USD_ROWS] == rates
    assert [cell(svc, "EK_FWD!D%d" % r, u) for r in USD_ROWS] == pytest.approx(
        [(x - cell(svc, "EK_FWD!L%d" % r, u)) * 100 for x, r in zip(rates, USD_ROWS)], abs=1e-9)
    svc.paste(u, "tto", "EK_FWD!D%d" % USD_ROWS[0], "-90\n-80")
    assert stored(svc, u)["D5"] == -90.0 and "AN5" not in stored(svc, u) and stored(svc, u)["AN7"] == rates[2]
    put(svc, u, {"I8": 15000, "K9": 52.1, "N104": 39.9})
    want = {r: quote(svc, u, r, s) for r, s in ((5, 0), (7, 0), (8, 1), (9, 1), (104, 1))}
    svc.save_scenario(u, "iki yönlü kotasyon")
    svc.reset_inputs(u, "tto")
    assert stored(svc, u) == {}
    svc.load_scenario(u, "iki yönlü kotasyon")
    assert {r: quote(svc, u, r, s) for r, s in ((5, 0), (7, 0), (8, 1), (9, 1), (104, 1))} == want


def test_formulas_on_the_matrix(svc):
    """A formula typed into a member: the bid 25 bp under the ask (another side of the row: no cycle); one that reads its
    own row-side's spread is a cycle, refused with the matrix's cells named."""
    u = svc.login("çy formül")["user"]
    r = USD_ROWS[0]
    put(svc, u, {"M%d" % r: "=EK_FWD!N%d-0.25" % r})
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(cell(svc, "EK_FWD!N%d" % r, u) - 0.25, abs=1e-12)
    put(svc, u, {"E%d" % r: -40})                                                    # the ask moves: the bid follows
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(cell(svc, "EK_FWD!L%d" % r, u) - 0.40 - 0.25, abs=1e-12)
    _, m = panel(svc, u, "forward", "EKF1")
    assert m["M%d" % r]["ff"] == "=EK_FWD!N%d-0.25" % r and m["M%d" % r]["an"] == "Spread, Puan, Fwd, ON %"
    res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!J%d" % r, "value": "=EK_FWD!D%d/100+50" % r}])
    assert len(res["errors"]) == 1 and "döngüsel başvuru" in res["errors"][0] and "EK_FWD!AR" not in res["errors"][0]
    assert res["errors"][0].startswith("EK_FWD!J%d:" % r) and "EK_FWD!D%d" % r in res["errors"][0]


def test_the_pages_marks_note_and_the_desks_summary(svc):
    """The page: all five pairs typeable (the matrices' inputs: 115 / 117 - the general row's width too, 28.11.2026), the
    typed value marked, the others worked out from it, the note under both matrices; Masa's summary is two-way as well (a
    TRY rate typed there moves the spread); "İşlem gir" on a typed rate prices it."""
    u = svc.login("çy sayfa")["user"]
    page = svc.view(u, "forward")
    panels = {p["id"]: p for p in page["panels"]}
    want = "İki yönlü: spread, TRY %, ON karşılık, puan ya da fwd - hangisini yazarsanız o kalır, diğerleri ondan hesaplanır"
    for pid, n in (("EKF1", 115), ("EKF5", 117)):
        assert want in panels[pid]["note"]                                       # (the general row's width's note beside it)
        assert len([c for row in panels[pid]["data"]["rows"] for c in row if c.get("i")]) == n
    assert "note" not in panels["EKF2"] or not (panels["EKF2"]["note"] or "").startswith(want)
    _, m = panel(svc, u, "masa", "EKS")
    assert all(m[c + "5"]["i"] == "u" for c in "DMENHIJK")
    ois = cell(svc, "EK_FWD!L7", u)
    put(svc, u, {"N7": round(ois + 0.42, 2)})                                       # typed on Masa's summary
    _, m = panel(svc, u, "masa", "EKS")
    assert m["N7"]["an"] == "Spread, Puan, Fwd, ON %" and m["E7"]["ao"] == "TRY % · N7" and m["E7"]["t"] == "42"
    _, f = panel(svc, u, "forward", "EKF1")
    assert f["N7"]["an"] and f["K7"]["ao"] == "TRY % · N7" and f["I7"]["ao"] == "TRY % · N7"
    spec = svc.trade_prefill(u, {"view": "forward", "panel": "EKF1", "row": 7, "col": "N", "text": f["N7"]["t"], "label": ""})["spec"]
    assert (spec["basis"], spec["dir"], spec["value"], spec["pair"]) == ("TRY", "S", f["N7"]["t"], "USDTRY")
    # nobody else's matrix moved
    assert cell(svc, "EK_FWD!N7") == pytest.approx(ois + cell(svc, "EK_FWD!E4") / 100, abs=1e-12)


# ---------------------------------------------------------------------------------------------- the general row's width
def look(c):
    return (c.get("c"), c.get("f"), c.get("b"))


WARN = (tone(extras.FWD_WARN_LOOK["color"]), fill_tone(extras.FWD_WARN_LOOK["fill"]), 1)


def test_no_width_is_said_and_a_width_spreads_the_general_row(svc):
    """The desk, 28.11.2026 (A14): both general spreads default to MASA!I60, so every quote went out as 34,38 / 34,38.
    Nothing typed: the same numbers as before, the width 0, the value dates whose TRY ask is not above their bid red and
    counted in the general row.  "Genişlik (bp)" typed: the spreads at the desk's spread ∓ ½ width, every date's TRY ask
    the width above its bid, nothing red; two-way with the ask spread - the last typed wins -; a bid typed keeps the
    width above it; Delete: back to the defaults.  EURTRY follows USDTRY's spreads (its width with them) or has its own,
    centred on USDTRY's."""
    u = svc.login("çy genişlik")["user"]
    desk = cell(svc, "MASA!I60", u)
    g = extras.FWD_ALL
    assert [cell(svc, "EK_FWD!%s4" % c, u) for c in "DEI"] == [desk, desk, 0.0] and cell(svc, "EK_FWD!H4", u) == "Genişlik (bp) →"
    dated = [r for r in range(extras.FWD_ROWS[0], extras.FWD_ROWS[1] + 1) if cell(svc, "EK_FWD!C%d" % r, u) != ""]
    assert len(dated) == 6 and all(cell(svc, "EK_FWD!N%d" % r, u) == cell(svc, "EK_FWD!M%d" % r, u) for r in dated)
    assert cell(svc, "EK_FWD!J4", u) == "⚠ 6 vadede ask ≤ bid (genişlik yok)"
    _, m = panel(svc, u, "masa", "EKS")
    assert look(m["M5"]) == look(m["N5"]) == look(m["D5"]) == look(m["D4"]) == look(m["I4"]) == WARN
    assert look(m["H5"]) != WARN and look(m["M11"]) != WARN                                # (a free row without a date)
    assert m["I4"]["i"] == "u" and m["J4"]["t"].startswith("⚠ 6 vadede")
    # a width typed: bid and ask either side of the desk's spread, every quote two-way
    put(svc, u, {"I4": 20})
    assert stored(svc, u) == {"AN4": 20.0}
    assert [cell(svc, "EK_FWD!%s4" % c, u) for c in "DEI"] == [desk - 10, desk + 10, 20.0] and cell(svc, "EK_FWD!J4", u) == ""
    for r in dated:
        assert cell(svc, "EK_FWD!N%d" % r, u) - cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(0.20, abs=1e-12)
    _, m = panel(svc, u, "masa", "EKS")
    assert look(m["M5"]) != WARN and look(m["D4"]) != WARN and m["I4"]["an"] == "Spread ask" and m["E4"]["ao"] == "Genişlik (bp) · I4"
    assert cell(svc, "EK_FWD!N7") == cell(svc, "EK_FWD!M7")                                # (nobody else's matrix moved)
    # a bid typed: the width stays above it
    put(svc, u, {"D4": desk - 30})
    assert [cell(svc, "EK_FWD!%s4" % c, u) for c in "DEI"] == [desk - 30, desk - 10, 20.0]
    # the ask typed: the last typed wins - the width is what the two spreads make now
    put(svc, u, {"E4": desk + 5})
    assert stored(svc, u) == {"D4": desk - 30, "E4": desk + 5} and cell(svc, "EK_FWD!I4", u) == 35.0
    put(svc, u, {"D4": "", "E4": ""})
    assert stored(svc, u) == {} and [cell(svc, "EK_FWD!%s4" % c, u) for c in "DEI"] == [desk, desk, 0.0]
    # an inverted width is said too
    put(svc, u, {"I4": -6})
    assert cell(svc, "EK_FWD!J4", u) == "⚠ 6 vadede ask ≤ bid (genişlik yok)"
    put(svc, u, {"I4": ""})
    assert stored(svc, u) == {}
    # EURTRY: the USDTRY general row's spreads (its width with them), or a width of its own around their middle
    e = extras.FWD_EUR_ALL
    put(svc, u, {"I4": 10})
    assert [cell(svc, "EK_FWD!%s%d" % (c, e), u) for c in "DEI"] == [desk - 5, desk + 5, 10.0]
    put(svc, u, {"I%d" % e: 30})
    assert [cell(svc, "EK_FWD!%s%d" % (c, e), u) for c in "DEI"] == [desk - 15, desk + 15, 30.0]
    assert cell(svc, "EK_FWD!N%d" % (e + 1), u) - cell(svc, "EK_FWD!M%d" % (e + 1), u) == pytest.approx(0.30, abs=1e-12)
    assert stored(svc, u) == {"AN4": 10.0, "AN%d" % e: 30.0}
    svc.reset_inputs(u, "tto")
    # "Piyasa spread": the general row is not used - not red for its own sake
    put(svc, u, {"B4": extras.FWD_SPREAD_MARKET})
    _, m = panel(svc, u, "masa", "EKS")
    assert look(m["D4"]) != WARN
    svc.reset_inputs(u, "tto")


def test_the_width_groups_and_their_store(svc):
    """Declared on Masa's page (its summaries show the general rows): the ask spread in place, the width kept in AN of
    the general row - a cell no input ever stood on, shown among the Forward page's helpers."""
    book = svc.books["tto"]
    for gid, g in (("ekfwd-width", extras.FWD_ALL), ("ekfwd-eur-width", extras.FWD_EUR_ALL)):
        grp = svc.twoway.groups[gid]
        assert [m.name for m in grp.members] == ["Spread ask", "Genişlik (bp)"] and grp.view == "masa"
        assert grp.members[0].own and grp.members[0].cells == book.cells_of("EK_FWD!E%d" % g)
        assert grp.members[1].store == book.cells_of("EK_FWD!AN%d" % g)
        assert book.inputs[grp.members[1].store[0]].scope == "user"
    assert svc.twoway.problems == {}
