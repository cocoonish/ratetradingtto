"""VİOP: each USDTRY contract's ON karşılık (the desk, 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını
da görmek istiyorum. Bu ve bunun gibi başka önerin olur mu" - among the proposals "VİOP USDTRY contracts: the ON of each
contract's implied TRY rate" - "Bunların da hepsini yap").

The VİOP sheet has it already: its BID / ASK tables' "TRY Repo" rows (17 / 29) are their "TRY" rows (13 / 25, the rate the
contract's bid / ask price implies, simple ACT/360 over VKGS days: the expiry − VIOP!K3) compounded daily over those very
days on 360 - the Forward calculators' "ON Karşılık" (``extras.on_equivalent``).  The VİOP page names it under the two
tables; the desk page's summary of the contracts shows it beside each implied rate (``extras.VIOP_ON_SIDES``,
``_tto_viop_on``: MASA's A / O, cells the workbook leaves empty).  Display only: no table of these takes a typed value per
contract - nothing is kept, and on a roll each ON stays beside its contract's rate.  Checked against a calculation of its
own off the cells' rates and days."""
from __future__ import annotations

import datetime as dt
import os
import re

import pytest

from conftest import cell
from tto import extras as ex
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.tokenizer import index_to_col
from tto.xl.values import date_to_serial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = ex.VIOP_DV01_COLS                     # M:X, the twelve contracts of the VİOP sheet
ROWS = list(range(ex.VIOP_ON_FIRST, ex.VIOP_ON_LAST + 1))      # MASA's contract rows: contract k in row 109 + k
#: the VİOP sheet's tables: (the implied rate's row, its days' row, its ON's row - "TRY Repo") of BID and of ASK
SIDES = {"bid": (13, 10, 17), "ask": (25, 22, 29)}
#: MASA's summary: the side -> (its rate's column, its ON's column)
MASA = {"bid": ("F", "A"), "ask": ("G", "O")}
SHOWN = ["B", "C", "D", "E", "F", "A", "G", "O", "H", "I", "J", "K", "L", "M", "N"]
TWO_DECIMALS = re.compile(r"^-?\d+,\d\d%$")


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def on_of(rate, days):
    """The ON karşılık of a simple ACT/360 rate (a fraction) over ``days``: compounded daily, on 360."""
    return 360.0 * ((1.0 + rate * days / 360.0) ** (1.0 / days) - 1.0)


def panel(svc, user, view, pid):
    return next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)


def raw_model():
    return Model.load(os.path.join(ROOT, "models", "tto.json.gz"))


# ============================================================================== the VİOP page: "TRY Repo" is the ON
def test_the_viop_sheets_try_repo_is_each_contracts_on_karsilik(svc):
    """Every contract, bid and ask: "TRY Repo" = 360·((1 + TRY·VKGS/360)^(1/VKGS) − 1) of the "TRY" above it, on the very
    days its formula uses (the contract's expiry − VIOP!K3, Bloomberg's USDTRY spot date) - the formula of the Forward
    calculators' ON Karşılık, written by ``extras.on_equivalent`` (the same number to the last bits)."""
    k3 = cell(svc, "VIOP!K3")                                                          # '4.11.2026' (replay)
    spot = cell(svc, "VIOP!M8")
    assert spot == (k3 if isinstance(k3, float) else float(date_to_serial(dt.datetime.strptime(k3, "%d.%m.%Y").date())))
    for side, (rate_row, days_row, on_row) in SIDES.items():
        assert cell(svc, "VIOP!L%d" % on_row) == "TRY Repo" and cell(svc, "VIOP!L%d" % rate_row) == "TRY"
        for col in CONTRACTS:
            rate, days, on = (cell(svc, "VIOP!%s%d" % (col, r)) for r in (rate_row, days_row, on_row))
            assert days == cell(svc, "VIOP!%s%d" % (col, days_row - 1)) - spot > 0, (side, col)
            assert on == pytest.approx(on_of(rate, days), rel=1e-13, abs=0), (side, col)
            # the Forward calculators' formula, as extras writes it, evaluated on the same rate and days
            text = ex.on_equivalent("rate", "days").replace("^", "**")
            assert on == pytest.approx(eval(text, {}, {"rate": rate, "days": days}), rel=1e-14, abs=0), (side, col)
            assert on < rate                                                    # (compounding daily: below the simple rate)
            assert ex.formula_of(svc.books["tto"].model, "VIOP", "%s%d" % (col, on_row)) == (
                "((1+%s%d/360*%s%d)^(1/%s%d)-1)*360" % (col, rate_row, col, days_row, col, days_row))


def test_the_viop_page_names_it_under_the_bid_and_ask_tables(svc):
    """The two tables show "TRY Repo" two decimals wide, as their TRY rows; the note under each says it is the ON karşılık,
    of which price, on which days and basis - and where the desk page shows it."""
    for pid, side, row in (("B5", "bid", 17), ("B7", "ask", 29)):
        p = panel(svc, None, "viop", pid)
        assert "TRY Repo = ON karşılık" in p["note"] and "360·((1 + TRY·VKGS/360)^(1/VKGS) − 1)" in p["note"], pid
        assert ("kontratın %s fiyatından" % side) in p["note"] and "ON %s" % side in p["note"], pid
        d = p["data"]
        cells = dict(zip(d["c"], d["rows"][d["r"].index(row)]))
        assert cells["L"]["t"] == "TRY Repo"
        assert all(TWO_DECIMALS.match(cells[c]["t"]) for c in CONTRACTS), [cells[c]["t"] for c in CONTRACTS]


# ============================================================================== the desk page's summary
def test_the_desk_pages_summary_shows_the_on_beside_each_implied_rate(svc):
    """MASA's "VİOP · kontratlar, ima TRY ve baz": ON bid beside İma bid, ON ask beside İma ask - each contract's "TRY Repo"
    of the VİOP sheet (the same value, the same two decimals), read the way the summary reads the rates (contract k from
    column k of M:X).  The other columns are where they were."""
    p = panel(svc, None, "masa", "B15")
    d = p["data"]
    assert p["title"] == "VİOP  ·  kontratlar, ima TRY ve baz" and d["c"] == SHOWN
    head = [c.get("t") for c in d["rows"][d["r"].index(109)]]
    assert head == ["Kontrat", "Gün", "Bid", "Ask", "İma bid (360)", "ON bid (360)", "İma ask (360)", "ON ask (360)", "TRY OIS",
                    "VİOP − OIS (bp)", "Baz (bp)", "Baz z", "Baz yüzdelik", "VİOP − FX sw (bp)", "VİOP−FX z"]
    assert "ON karşılığı" in p["note"] and "TRY Repo" in p["note"]
    viop = {pid: panel(svc, None, "viop", pid)["data"] for pid in ("B5", "B7")}
    for k, r in enumerate(ROWS):
        col = CONTRACTS[k]
        shown = dict(zip(d["c"], d["rows"][d["r"].index(r)]))
        assert cell(svc, "MASA!B%d" % r) == cell(svc, "VIOP!%s97" % col)                  # the contract of the row
        for side, (rate_row, days_row, on_row) in SIDES.items():
            rate_col, on_col = MASA[side]
            on = cell(svc, "MASA!%s%d" % (on_col, r))
            assert on == cell(svc, "VIOP!%s%d" % (col, on_row)) and isinstance(on, float), (r, side)
            assert cell(svc, "MASA!%s%d" % (rate_col, r)) == cell(svc, "VIOP!%s%d" % (col, rate_row))
            assert on == pytest.approx(on_of(cell(svc, "MASA!%s%d" % (rate_col, r)), cell(svc, "MASA!C%d" % r)), rel=1e-13, abs=0)
            assert TWO_DECIMALS.match(shown[on_col]["t"]) and shown[on_col]["v"] == on, (r, side, shown[on_col])
            # the VİOP page's TRY Repo of the same contract, as it reads there
            page = viop["B5" if side == "bid" else "B7"]
            assert shown[on_col]["t"] == page["rows"][page["r"].index(on_row)][page["c"].index(col)]["t"]
    # the replay day's first contract (30.11.2026, 26 days): 33,58 % bid -> 33,20 % its ON, 33,83 % ask -> 33,44 %
    first = dict(zip(d["c"], d["rows"][d["r"].index(110)]))
    assert [first[c]["t"] for c in ("B", "C", "F", "A", "G", "O")] == ["30.11.2026", "26", "33,58%", "33,20%", "33,83%", "33,44%"]


def test_the_on_follows_the_rate_and_its_days(svc):
    """A user's own spot value date (VIOP!K3, the VİOP sheet's input) one day later: every contract one day shorter, its
    implied rates on the new days - and its ON on them, on the VİOP page and the desk page alike, for that user only."""
    u = svc.login("VİOP ON karşılık")["user"]
    before = {col: cell(svc, "VIOP!%s17" % col) for col in CONTRACTS}
    res = svc.set_inputs(u, "tto", [{"ref": "VIOP!K3", "value": "05.11.2026"}])
    assert res["errors"] == [], res["errors"]
    try:
        for k, col in enumerate(CONTRACTS):
            r = ROWS[k]
            assert cell(svc, "VIOP!%s10" % col, u) == cell(svc, "VIOP!%s10" % col) - 1
            for side, (rate_row, days_row, on_row) in SIDES.items():
                rate, days, on = (cell(svc, "VIOP!%s%d" % (col, x), u) for x in (rate_row, days_row, on_row))
                assert on == pytest.approx(on_of(rate, days), rel=1e-13, abs=0) and on != cell(svc, "VIOP!%s%d" % (col, on_row))
                assert cell(svc, "MASA!%s%d" % (MASA[side][1], r), u) == on
        assert {col: cell(svc, "VIOP!%s17" % col) for col in CONTRACTS} == before                # nobody else's moved
    finally:
        svc.reset_inputs(u, "tto", ["VIOP!K3"])
    assert {col: cell(svc, "VIOP!%s17" % col, u) for col in CONTRACTS} == before


def test_on_a_roll_each_on_stays_beside_its_contracts_rate(svc, tmp_path):
    """Display only, so nothing is kept to move: the contracts roll by themselves (the front trades until its expiry day,
    the list shifts the day after) and every column of the summary - the ON's too - is the contract's place.  The day
    after the November expiry the first row is December's, with its own rate, days (from that day's spot date) and their
    ON; the last row is the contract the roll lists next."""
    from test_viopfra import _Live
    live = _Live(svc, tmp_path)
    s = live.svc
    try:
        def summary():
            return [{c: cell(s, "MASA!%s%d" % (c, r)) for c in "BCFAGO"} for r in ROWS]

        start = summary()
        assert start[0]["B"] == "30.11.2026" and start[1]["B"] == "31.12.2026"
        live.on(dt.date(2026, 12, 1), "2.12.2026")
        rolled = summary()
        assert cell(s, "VIOP!L1") == "A1Z6 Curncy" and [x["B"] for x in rolled[:2]] == ["31.12.2026", "29.01.2027"]
        assert rolled[-1]["B"] == "30.11.2027"
        assert rolled[0]["C"] == 29.0 and start[1]["C"] == 57.0               # 31.12.2026 − 02.12.2026 (was − 04.11.2026)
        for k, row in enumerate(rolled):
            for rate_col, on_col in MASA.values():
                assert row[on_col] == pytest.approx(on_of(row[rate_col], row["C"]), rel=1e-13, abs=0), (k, on_col)
                assert row[on_col] == cell(s, "VIOP!%s%d" % (CONTRACTS[k], 17 if on_col == "A" else 29))
    finally:
        s.stop()


# ============================================================================== what the addition writes, and when it does not
def test_the_addition_writes_its_own_cells_only(monkeypatch):
    """The workbook with every addition but this one, against all of them: the same sheets, formulas, values and looks
    everywhere but MASA's A109:A121 and O109:O121 - empty in the workbook, read by no formula - so nothing shown before
    changes."""
    full = raw_model()
    assert ex.apply("tto", full) == []
    without = raw_model()
    monkeypatch.setitem(ex._BUILDERS, "tto", tuple(b for b in ex._BUILDERS["tto"] if b[0] != ex.VIOP_ON_NAME))
    assert ex.apply("tto", without) == []
    assert [s.name for s in full.sheets] == [s.name for s in without.sheets]

    def cells(model, sh):
        out = {rc: ("=", model.templates[t]) for rc, t in sh.fml.items()}
        out.update({rc: ("c", v) for rc, v in sh.consts.items()})
        return out

    new = {(r * COLS + col) for col in (1, 15) for r in range(ex.VIOP_ON_FIRST - 1, ex.VIOP_ON_LAST + 1)}      # A, O
    for a, b in zip(full.sheets, without.sheets):
        ca, cb = cells(full, a), cells(without, b)
        if a.name != "MASA":
            assert ca == cb and a.styles == b.styles and a.comments == b.comments, a.name
            continue
        assert set(ca) - set(cb) == new and set(cb) <= set(ca)
        assert {rc: v for rc, v in ca.items() if rc not in new} == cb
        assert {rc: x for rc, x in a.styles.items() if rc not in new} == b.styles
    masa = full.sheet("MASA")
    assert [full.xfs[masa.styles[parse_a1("%s%d" % (c, r))]][0] for c in "AO" for r in ROWS] == ["0.00%"] * 24      # two decimals
    assert masa.consts[parse_a1("A109")] == "ON bid (360)" and masa.consts[parse_a1("O109")] == "ON ask (360)"
    assert [ex.formula_of(full, "MASA", "A%d" % r) for r in (110, 121)] == ['IFERROR(INDEX(VIOP!$M$17:$X$17,1),"")',
                                                                            'IFERROR(INDEX(VIOP!$M$17:$X$17,12),"")']
    assert ex.formula_of(full, "MASA", "O115") == 'IFERROR(INDEX(VIOP!$M$29:$X$29,6),"")'


def test_nothing_reads_the_new_cells(svc):
    """The summary's ON cells feed nothing: no formula of the workbook or of the dashboard's sheets reads them."""
    book = svc.books["tto"]
    idx = svc.et.call(book.engine.ref_index)
    si = book.model.sheet_index["MASA"]
    assert idx.complete
    for col in ("A", "O"):
        for r in range(ex.VIOP_ON_FIRST - 1, ex.VIOP_ON_LAST + 1):
            assert idx.readers(si, parse_a1("%s%d" % (col, r))) == [], (col, r)


def test_a_workbook_laid_out_otherwise_leaves_it_out():
    """The addition builds on the VİOP sheet's TRY / TRY Repo rows and the summary's rate columns: a "TRY Repo" written
    otherwise (its days not the rate's), a summary column of rates read from another row, a caption moved or a value in
    the cells it takes - the addition is left out by name, its cells not written, the rest of the workbook as it is."""
    tto = raw_model()
    ex.SheetBuilder(tto, "VIOP").patch("X29", "=((1+X25/360*X10)^(1/X10)-1)*360")         # the bid table's days
    problems = ex.apply("tto", tto)
    assert problems == ["%s: VIOP!X29 beklenen formül değil (((1+X25/360*X22)^(1/X22)-1)*360)" % ex.VIOP_ON_NAME], problems
    masa = tto.sheet("MASA")
    assert not any(parse_a1("%s%d" % (c, r)) in masa.fml or parse_a1("%s%d" % (c, r)) in masa.consts
                   for c in "AO" for r in range(108, 123))
    assert "EK_XAU" in tto.sheet_index and "EK_VFRA" in tto.sheet_index                     # the rest is there
    # (the check alone, on the workbook as the file has it: each of these leaves the addition out)
    ex._viop_on_check(raw_model())
    for sheet, addr, value, why in (
            ("MASA", "F113", '=IFERROR(INDEX(VIOP!$M$18:$X$18,4),"")', "MASA!F113 beklenen formül değil"),
            ("MASA", "G109", "İma ask", "MASA!G109 beklenen başlık değil"),
            ("MASA", "O118", 1.5, "MASA!O118 boş değil"),
            ("MASA", "A108", "not", "MASA!A108 boş değil"),
            ("VIOP", "L17", "Repo", "VIOP!L13 / L17 beklenen başlık değil"),
            ("VIOP", "P13", "=((1+P14/10000/P11)*(1+P12*P10/365)-1)*365/P10", "VIOP!P13 beklenen formül değil")):
        model = raw_model()
        ex.SheetBuilder(model, sheet).set(addr, value)
        with pytest.raises(ValueError, match=re.escape(why)):
            ex._viop_on_check(model)


def test_the_summary_without_the_addition_is_as_before(svc):
    """Should the addition be left out, the summary's columns A and O are empty: the table drops them and shows the
    workbook's columns in their order (``_pick_columns`` skips a column the table does not have)."""
    from tto.service import _pick_columns
    data = {"c": [index_to_col(c) for c in range(2, 15)], "r": [109], "rows": [[{"t": index_to_col(c)} for c in range(2, 15)]]}
    _pick_columns(data, SHOWN)
    assert data["c"] == [index_to_col(c) for c in range(2, 15)]
