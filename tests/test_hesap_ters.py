"""The calculators' ways back (the desk, 24.11.2026: "1-2-3-4-5-6-7-8-11-11-13", then "I meant 11-12"): item 8, the Forward
page's bond carry - a buy / sell-back price typed -> the repo it implies (Forward!V71 -> V72) - and item 12, the
Calculators page's Implied Move - a move typed in %, as a breakeven level or in pips -> the vol it implies
(Calculators!O44 / O46 / O48 -> O45 / O47 / O49).  Each is its block's own formula solved for the other side: the result
typed back into the block gives the value typed (1e-9), with the block's own cells."""
import os

import pytest

from conftest import cell
from tto import extras as ex
from tto.views import load_views
from tto.xl.model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: a bond, its clean price, settlement, the repo and the end of the carry (a quarter)
CARRY = {"Forward!V56": "TRB100227T13", "Forward!V57": "91,713", "Forward!V58": "05.11.2026", "Forward!V61": "36",
         "Forward!V62": "03.02.2027"}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells, adhoc=False):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()], allow_adhoc=adhoc)
    assert res["errors"] == [], res["errors"]
    return res


# ============================================================================== bond carry: a forward price -> its repo
def test_a_forward_price_reads_the_repo_it_implies(svc):
    """(item 8: "type a buy/sell-back price and read the implied repo") B/E = Temiz Fiyat − Kupon + Dirty Price · repo /
    365 · N: the calculator's own B/E typed as the forward price reads its Carry back, and any price's repo typed into
    Carry makes B/E that price - a bill (the recorded file's: no coupon) and a coupon bond (a coupon typed over the
    calculator's Bloomberg cell)."""
    u = svc.login("Tahvil carry ters")["user"]
    try:
        put(svc, u, CARRY)
        assert cell(svc, "Forward!V63", u) == 90.0
        for coupon in (None, 0.3):
            if coupon is not None:
                put(svc, u, {"Forward!V64": coupon}, adhoc=True)                  # (an "elle değer" over Bloomberg's coupon)
                assert cell(svc, "Forward!V66", u) == pytest.approx(0.3 * 90 / 364 * 100)
            be = cell(svc, "Forward!V67", u)
            put(svc, u, {"Forward!V71": be})
            assert cell(svc, "Forward!V72", u) == pytest.approx(0.36, abs=1e-9), coupon
            for price in (be + 1.5, be - 0.75, 99.0):
                put(svc, u, {"Forward!V71": price})
                repo = cell(svc, "Forward!V72", u)
                want = (price - cell(svc, "Forward!V57", u) + cell(svc, "Forward!V66", u)) * 365 / (cell(svc, "Forward!V60", u) * 90)
                assert repo == pytest.approx(want, rel=1e-12), (coupon, price)
                put(svc, u, {"Forward!V61": repo})                                    # the repo found, typed as Carry: B/E = price
                assert cell(svc, "Forward!V67", u) == pytest.approx(price, abs=1e-9), (coupon, price)
                put(svc, u, {"Forward!V61": "36"})
        # a higher price, a higher repo; a price typed as the desk types it; none, or no days to carry: no repo
        put(svc, u, {"Forward!V71": "99,5"})
        high = cell(svc, "Forward!V72", u)
        put(svc, u, {"Forward!V71": "99"})
        assert high > cell(svc, "Forward!V72", u) > 0
        put(svc, u, {"Forward!V62": "05.11.2026"})
        assert cell(svc, "Forward!V63", u) == 0.0 and cell(svc, "Forward!V72", u) == ""
        put(svc, u, {"Forward!V62": "03.02.2027", "Forward!V71": ""})
        assert cell(svc, "Forward!V72", u) == ""
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== implied move: a move -> its vol
def test_a_move_reads_the_vol_it_implies(svc):
    """(item 12: "move → vol ... to turn a straddle breakeven into a vol") Implied Move = √(Gün / Gün Basis) · Volatilite,
    the bounds (1 ± move) · Spot, the pips Spot · move · 10000: the block's own move, upper and lower bound and pips typed
    back read its Volatilite, and any move's vol typed into Volatilite gives that move, bound or pips back - on the
    file's spot, days and basis and on others."""
    u = svc.login("Implied move ters")["user"]
    try:
        for setup in ({}, {"Calculators!O36": "41,25", "Calculators!O37": "30", "Calculators!O38": "365"}):
            put(svc, u, dict(setup, **{"Calculators!O39": "19"}))
            move, up, low, pips = [cell(svc, "Calculators!O%d" % r, u) for r in (40, 41, 42, 43)]
            spot = cell(svc, "Calculators!O36", u)
            assert cell(svc, "Calculators!O39", u) == 0.19 and up > spot > low
            put(svc, u, {"Calculators!O44": move, "Calculators!O46": up, "Calculators!O48": pips})
            for out in ("O45", "O47", "O49"):
                assert cell(svc, "Calculators!" + out, u) == pytest.approx(0.19, abs=1e-9), (setup, out)
            put(svc, u, {"Calculators!O46": low})                                   # the lower breakeven: the same vol
            assert cell(svc, "Calculators!O47", u) == pytest.approx(0.19, abs=1e-9)
            for typed, out, value, back in (("O44", "O45", 0.0725, "O40"), ("O46", "O47", spot * 1.05, "O41"),
                                            ("O46", "O47", spot * 0.9, "O42"), ("O48", "O49", 12345.6, "O43")):
                put(svc, u, {"Calculators!" + typed: value})
                vol = cell(svc, "Calculators!" + out, u)
                assert isinstance(vol, float) and vol > 0
                put(svc, u, {"Calculators!O39": vol})                                 # the vol found, typed: the value typed back
                assert cell(svc, "Calculators!" + back, u) == pytest.approx(value, abs=1e-9), (setup, typed)
            put(svc, u, {"Calculators!O39": "19"})
        # typed as the desk types them: a move in %, a level, pips with thousands
        put(svc, u, {"Calculators!O44": "9,5", "Calculators!O46": "43,3125", "Calculators!O48": "36.717,5"})
        assert cell(svc, "Calculators!O44", u) == 0.095 and cell(svc, "Calculators!O48", u) == 36717.5
        # nothing, zero or below zero: no vol
        for value in ("", "0", "-5"):
            put(svc, u, {"Calculators!O44": value, "Calculators!O46": value, "Calculators!O48": value})
            assert [cell(svc, "Calculators!O%d" % r, u) for r in (45, 47, 49)] == ["", "", ""], value
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== the pages
def test_the_new_inputs_are_personal_blank_and_on_cells_no_input_ever_stood_on(svc):
    """Each a cell of its block's table, the user's own, empty to start with, where no input stood before (the views'
    history: none retired, none another table's); the block's own inputs and numbers do not move."""
    views = {v["id"]: v for v in load_views()}
    new = {"forward": {"V71": "number"}, "calc": {"O44": "pct", "O46": "number", "O48": "number"}}
    for vid, cells in new.items():
        have = {i["range"]: i for i in views[vid]["inputs"]}
        for ref, kind in cells.items():
            assert have[ref]["scope"] == "user" and have[ref]["kind"] == kind, (vid, ref)
    assert ex.BOND_BACK_PRICE == "V71" and [m[0] for m in ex.MOVE_BACK] == ["O44", "O46", "O48"]
    panels = {(vid, p["id"]): p for vid in new for p in views[vid]["panels"]}
    assert panels[("forward", "B24")]["range"] == "U56:W72" and panels[("calc", "B23")]["range"] == "N35:O49"
    u = svc.login("Ters hesap yeni")["user"]
    assert cell(svc, "Forward!V71", u) is None and cell(svc, "Forward!V72", u) == ""
    for typed, out, _, _, _ in ex.MOVE_BACK:
        assert cell(svc, "Calculators!" + typed, u) is None and cell(svc, "Calculators!" + out, u) == ""
    assert cell(svc, "Calculators!O40", u) == pytest.approx(0.095)                    # (the block as the file has it)
    # on the page: the labels beside them; the bond carry's ISIN row stays a row of its table (blank, it would become the
    # panel's title, its input gone with it)
    fwd = next(p for p in svc.view(u, "forward")["panels"] if p["id"] == "B24")
    assert fwd["title"] == "Tahvil carry / başabaş" and fwd["data"]["r"][0] == 56 and fwd["data"]["r"][-1] == 72
    rows = dict(zip(fwd["data"]["r"], fwd["data"]["rows"]))
    assert rows[56][0]["t"] == "ISIN" and rows[56][1].get("i") == "u"
    assert [rows[71][0]["t"], rows[72][0]["t"]] == ["Fwd temiz fiyat (elle)", "İma repo"] and rows[71][1].get("i") == "u"
    calc = next(p for p in svc.view(u, "calc")["panels"] if p["id"] == "B23")
    rows = dict(zip(calc["data"]["r"], calc["data"]["rows"]))
    assert [rows[r][0]["t"] for r in range(44, 50)] == ["Hareket % (elle)", "İma vol (hareket)", "Başabaş seviyesi (elle)",
                                                         "İma vol (başabaş)", "Hareket pip (elle)", "İma vol (pip)"]
    assert [bool(rows[r][1].get("i")) for r in range(44, 50)] == [True, False] * 3


# ============================================================================== the workbooks they are built on
def test_left_out_when_a_block_is_not_what_it_reads():
    """Each way back solves its block's formula: a block written otherwise, or a cell it takes already used, leaves that
    way back out (and only it); the rest of the dashboard stays."""
    path = os.path.join(ROOT, "models", "tto.json.gz")
    tto = Model.load(path)
    ex.SheetBuilder(tto, "Forward").patch("V65", "=V60*V61/360*V63")                    # carry on 360 days
    ex.SheetBuilder(tto, "Calculators").set("O45", 1.0)                                  # a cell the move's vol takes
    assert ex.apply("tto", tto) == [ex.BOND_BACK_NAME + ": Forward!V65 beklenen formül değil (V60*V61/365*V63 yok)",
                                    ex.MOVE_BACK_NAME + ": Calculators!O45 boş değil"]
    assert ex.formula_of(tto, "Forward", "V67") == "+V57-V66+V65" and "EK_TARIH" in tto.sheet_index
    tto = Model.load(path)
    ex.SheetBuilder(tto, "Calculators").patch("O40", "=SQRT(O37/365)*O39")              # another basis
    assert ex.apply("tto", tto) == [ex.MOVE_BACK_NAME + ": Calculators!O40 beklenen formül değil (SQRT(O37/O38)*O39 yok)"]
