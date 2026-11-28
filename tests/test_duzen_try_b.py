"""Düzen (27.11.2026, the desk: "Hepsini yap" to the 22 layout proposals): the Forward, VİOP, Borsa Swap, Carry & Roll,
OIS · Nakit Akışı and DV01 Risk pages.  Layout only - every value, formula and input stays as it was: the checks compare
what a page shows with the sheet's own cells, never with a market figure."""
import io
import json
import os
import re

import pytest

from conftest import cell
from tto.views import load_views
from tto.xl.model import COLS, parse_a1, parse_range
from tto.xl.tokenizer import col_to_index, index_to_col

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEWS = {v["id"]: v for v in load_views()}


def raw(name):
    """A page definition as written (its stacked columns not yet read flat)."""
    with io.open(os.path.join(ROOT, "tto", "views", name), encoding="utf-8") as fh:
        return json.load(fh)


def flat(ids):
    """A tab's panels in order, a stacked column read as its ids (whether the page definition is read flat or not)."""
    out = []
    for p in ids:
        out.extend(flat(p) if isinstance(p, list) else [p])
    return out


def tab(view, sid):
    return next(s for s in view["sections"] if s["id"] == sid)


def panel_def(vid, pid):
    return next(p for p in VIEWS[vid]["panels"] if p["id"] == pid)


def entry(page, pid):
    return next(p for p in page["panels"] if p["id"] == pid)


def shown(data, col, r):
    """A cell of a page's table by its column (letter, or the caption of a column of the dashboard's own) and sheet row."""
    return data["rows"][data["r"].index(r)][data["c"].index(col)]


# ---------------------------------------------------------------------------------------------- stacked columns
def test_small_panels_stack_in_a_column_beside_a_tall_one():
    """8: an element of a tab's panels may be a list - small panels one under the other beside a tall one (the mechanism is
    the core layout's); read flat, every page still lists each of its panels once, in order."""
    from tto import views
    if hasattr(views, "flat"):                                   # (this branch's reading: flat, until the core layout's)
        assert views.flat(["A", ["B", "C"], "D", [["E"]]]) == ["A", "B", "C", "D", "E"] and views.flat([]) == []
    stacks = {
        ("30_forward.json", "fwd"): ["FR1", "FR2", "FR3", "FR4", ["B18", "B16"]],      # Forward DV01 before the gold forward
        ("70_dv01.json", "pos"): ["B3", ["B1", "B7"], "B4"],                            # the paste table, beside it how-to + Özet
        ("70_dv01.json", "hedge"): ["B14", ["B14D", "B16"]],                            # "Yuvarlama TL" (2 cells) not alone
        ("50_carry.json", "out"): [["B2", "B3"], ["B4", "B5"]],                         # each horizon's strip above its table
        ("40_viop.json", "gold"): ["B9", "B10", ["B11", "B11b"], "XAU4", "XAU1", "XAU2", "XAU3D", "XAU3"],
    }
    for (name, sid), want in stacks.items():
        assert tab(raw(name), sid)["panels"] == want, (name, sid)
        vid = raw(name)["id"]
        assert flat(tab(VIEWS[vid], sid)["panels"]) == flat(want), (name, sid)


# ---------------------------------------------------------------------------------------------- Forward
def test_forward_tabs(service):
    """16: the one-table Ticker'lar tab folded into Eğriler (last), Forward DV01 before the gold forward; 21: the four ways
    back of the quote matrices start folded and at their own width; 4: the matrices' "serbest" rows and ÇAPRAZ FORWARD's
    free valörs grow (the filled rows and one more); 3: the identifier columns of the wide tables stay in view."""
    fwd = VIEWS["forward"]
    assert [s["id"] for s in fwd["sections"]] == ["calc", "fwd", "kot", "ret", "bulk", "curves", "off"]
    assert tab(fwd, "curves")["panels"][-1] == "B12" and "ticker" in tab(fwd, "curves")["note"]
    assert flat(tab(fwd, "fwd")["panels"]) == ["FR1", "FR2", "FR3", "FR4", "B18", "B16"]
    assert tab(fwd, "kot")["panels"] == ["EKF1", "EKF5", "EKF2", "EKF8", "EKF6", "EKF9"]           # (the order as it was)
    page = service.view(None, "forward")
    for pid in ("EKF2", "EKF8", "EKF6", "EKF9"):
        p, e = panel_def("forward", pid), entry(page, pid)
        assert p["collapsed"] and not p.get("wide") and e["collapsed"] and not e["wide"], pid
    for pid in ("EKF1", "EKF5"):
        assert not entry(page, pid)["collapsed"], pid
    # the rows that grow: a date typed in "Valör" (B) - each table's first data row to its last "serbest" row
    grows = {"EKF1": (5, 14), "EKF5": (104, 113), "EKF2": (20, 29), "EKF8": (133, 142), "EKF6": (119, 128), "EKF9": (147, 156),
             "B36": (200, 215)}
    for pid, (first, last) in grows.items():
        g = entry(page, pid)["grow"]
        assert (g["key"], g["first"], g["last"], g["extra"]) == ("B", first, last, 1), pid
        data = entry(page, pid)["data"]
        assert first - 1 in data["r"] and last + 1 in data["r"], pid                    # (the header above, a note below)
        if pid.startswith("EKF"):
            assert [shown(data, "A", r)["t"] for r in range(first + 6, last + 1)] == ["serbest"] * 4, pid
    # (ÇAPRAZ FORWARD: six preset valörs, nine free ones - each an input of the page)
    assert {i["range"] for i in fwd["inputs"]} >= {"B200:B205", "B206:B214"}
    freeze = {"FR1": 1, "FR2": 1, "EKF1": 2, "EKF5": 2, "EKF8": 2, "EKF9": 2, "B34": 1, "B36": 1}
    assert {pid: panel_def("forward", pid).get("freeze") for pid in freeze} == freeze


# ---------------------------------------------------------------------------------------------- VİOP
VIOP_NAMED = ["B5", "B7", "B12", "B13", "B32", "B33", "B34", "B35", "B36"] + ["B%d" % k for k in range(17, 32)]


def test_viop_contracts_tab_and_the_gold_calculator(service):
    """15: Kontratlar → DEALS → Target first, then BID / ASK / OIS / ICAP, the manual spot last; 16: the gold calculator's
    one home is the Altın tab (its own tab only repeated it); 4: Target's filled rows and one more."""
    viop = VIEWS["viop"]
    assert [s["id"] for s in viop["sections"]] == ["main", "gold", "matrix", "basis", "curves"]
    assert tab(viop, "main")["panels"] == ["B1", "B32", "B33", "B5", "B7", "B12", "B13", "B6"]
    assert "XAU4" in tab(viop, "gold")["panels"] and "hesaplayıcı" in tab(viop, "gold")["note"]
    assert sum("XAU4" in s["panels"] for s in viop["sections"]) == 1
    page = service.view(None, "viop")
    g = entry(page, "B33")["grow"]
    assert (g["key"], g["first"], g["last"], g["extra"]) == ("L", 331, 338, 1)
    assert panel_def("viop", "B33")["freeze"] == 2 and all(panel_def("viop", p).get("freeze") == 1 for p in ("B34", "B35", "B36"))
    # the manual spot is a panel of the page still - its two cells typeable, the header strip's "Spot kaynağı" edits them too
    spot = entry(page, "B6")
    assert len([c for row in spot["data"]["rows"] for c in row if c.get("i")]) == 2


def test_viop_tables_leave_out_the_column_that_repeats_their_name(service):
    """15: the merged column K of the VİOP tables only repeats the table's name, which the panel's title says: shown from
    L.  Every other column, and every input in them, is there as before (cells keep their letters)."""
    page = service.view(None, "viop")
    for pid in VIOP_NAMED:
        p, data = panel_def("viop", pid), entry(page, pid)["data"]
        r1, c1, r2, c2 = parse_range(p["range"])
        assert index_to_col(c1) == "K" and "K" not in data["c"] and data["c"][0] == "L", pid
        assert cell(service, "VIOP!K%d" % r1).strip() == p["title"].strip(), pid            # the name: the title
        every = {index_to_col(c) for c in range(12, c2 + 1)}
        if pid == "B33":
            assert data["c"] == p["cols"] and set(p["cols"]) == every - {"AA", "AB", "AC"}   # (AA:AC: its tooltips' text)
        else:
            assert set(data["c"]) == (every - {"U"}) | ({"U"} & set(data["c"])), pid         # (DEALS: U hidden in Excel)
    # the inputs inside them: DEALS' contract limit (W321), the history tables' look-back (M340) and day basis (R353)
    for pid, ref in (("B32", "W321"), ("B34", "M340"), ("B35", "R353")):
        col, r = re.match(r"([A-Z]+)(\d+)", ref).groups()
        assert shown(entry(page, pid)["data"], col, int(r)).get("i"), (pid, ref)
    # the contracts' table keeps its K: K3 is the spot value date every table counts from (an input)
    assert entry(page, "B1")["data"]["c"][0] == "K" and shown(entry(page, "B1")["data"], "K", 3).get("i") == "u"


# ---------------------------------------------------------------------------------------------- Borsa Swap
def test_borsa_spreads_follow_the_rates(service):
    """13: at 1366 px the four spread columns were exactly what scrolled away: BID % / ASK % and their spreads to the OIS
    and the offshore mid come right after the dates, the curves' zero rates after them, the rest in the sheet's order -
    every cell as before (by its letter; the spreads by their caption)."""
    from tto import borsaspread as bsp
    page = service.view(None, "borsa")
    heads = [h for h, _ in bsp.HEADS]
    spreads, zeros = heads[2:], heads[:2]
    for pid, (date, days, bid, ask), rest in (("t0", "DEHM", "GIJKLNOP"), ("t1", ("Q", "R", "U", "Z"), ("T", "V", "W", "X", "Y", "AA", "AB", "AC"))):
        data = entry(page, pid)["data"]
        assert data["c"] == [date, days, bid, ask] + spreads + zeros + list(rest), pid
        assert [c["t"] for c in data["rows"][0]][2:8] == ["BID %", "ASK %"] + spreads, pid
        assert data["added"] == 6 and panel_def("borsa", pid)["freeze"] == 1
        # the sheet's own cells read as the sheet has them, wherever their column stands now
        r1, c1, r2, c2 = parse_range(panel_def("borsa", pid)["range"])
        grid = service.grid(None, "borsa", "bu", panel_def("borsa", pid)["range"])["data"]
        for r in data["r"][1:6]:
            for col in [date, days, bid, ask] + list(rest):
                assert shown(data, col, r)["t"] == grid["rows"][grid["r"].index(r)][grid["c"].index(col)]["t"], (pid, col, r)
    # the Excel-hidden ticker column comes in its place with the helper columns
    full = entry(service.view(None, "borsa", True), "t0")["data"]
    assert full["c"][10:12] == ["F", "G"] and full["c"][:4] == ["D", "E", "H", "M"]


def test_columns_of_the_dashboard_own_stay_at_the_end_unless_named(service):
    """The second pass of "cols" (after the dashboard's own columns are added) only moves the columns a page names: a
    page that names none of them shows them on the right, as before."""
    from tto.service import _pick_columns
    data = {"c": ["D", "E", "x"], "r": [1, 2], "rows": [[{"t": "D"}, {"t": "E"}, {"t": "x"}], [{"t": 1}, {"t": 2}, {"t": 3}]]}
    cols = ["E", "D"]
    have = data["c"]
    _pick_columns(data, [c for c in cols if c in have] + [c for c in have if c not in cols])
    assert data["c"] == ["E", "D", "x"] and [c["t"] for c in data["rows"][1]] == [2, 1, 3]


# ---------------------------------------------------------------------------------------------- Carry & Roll
def test_carry_tabs(service):
    """14: the simulator's result beside its inputs (its 18 intermediate values folded), Spread · fly open, the notes panel
    that only said the title and the path (CARRY PATİKASI says it, pinned) among the helper tables."""
    carry = VIEWS["carry"]
    assert tab(carry, "sim")["panels"] == ["B8", "B10", "B9"]
    assert panel_def("carry", "B9")["collapsed"] and not panel_def("carry", "B6").get("collapsed") and not panel_def("carry", "B7").get("collapsed")
    assert panel_def("carry", "B1")["hidden"] and "B1" not in tab(carry, "out")["panels"] and carry["pinned"] == ["CP1", "CP2"]
    page = service.view(None, "carry")
    assert "B1" not in [p["id"] for p in page["panels"]] and entry(service.view(None, "carry", True), "B1")["type"] == "notes"
    # (the title the notes panel showed is the pinned path's text: nothing is lost)
    assert cell(service, "EK_CARRY!C2") in cell(service, "'C & R'!A1")


# ---------------------------------------------------------------------------------------------- OIS · Nakit Akışı
def test_cash_flow_schedule_is_one_table_with_its_results(service):
    """14: the schedule (inputs, A:E) and the market leg of each period (F:J) one table - each period's dates beside its
    results; 4: the filled periods and one more (it was 96 % empty); the title-only notes panel among the helpers."""
    p = panel_def("tmois", "B4")
    assert p["range"] == "A9:J34" and p["grow"] == {"key": "A", "first": 10, "extra": 1, "last": 34}
    page = service.view(None, "tmois")
    data = entry(page, "B4")["data"]
    assert data["c"] == list("ABCDEFGHIJ") and data["r"] == list(range(9, 35))
    assert [shown(data, c, 10).get("i") for c in "ABCDE"] == ["u"] * 5 and not shown(data, "F", 10).get("i")
    ids = [x["id"] for x in page["panels"]]
    assert "B1" not in ids and "B5" not in ids
    full = {x["id"]: x for x in service.view(None, "tmois", True)["panels"]}
    assert full["B5"]["range"] == "F9:J34" and full["B1"]["type"] == "notes"              # (ids kept, one click away)


# ---------------------------------------------------------------------------------------------- DV01 Risk
def test_dv01_carry_table_names_its_buckets(service):
    """14: the carry / roll-down table with the bucket each row is (it was read beside the bucket table by counting rows)."""
    p = panel_def("dv01", "B4")
    assert p["range"] == "B5:Y27" and p["cols"] == ["B"] + [index_to_col(c) for c in range(col_to_index("Q"), col_to_index("Y") + 1)]
    page = service.view(None, "dv01")
    carry, buckets = entry(page, "B4")["data"], entry(page, "B3")["data"]
    assert carry["c"][0] == "B" and shown(carry, "B", 5)["t"] == "Bucket"
    for r in range(6, 27):
        assert shown(carry, "B", r)["t"] == shown(buckets, "B", r)["t"], r
    # the fixed rates typed into it stay its inputs
    assert all(shown(carry, "Q", r).get("i") == "u" for r in range(6, 26))


# ---------------------------------------------------------------------------------------------- how numbers read
def _page_cell(service, vid, ref, panels=None):
    """A workbook cell as a page shows it (the first table that has it)."""
    sheet, _, addr = ref.rpartition("!")
    col, r = re.match(r"([A-Z]+)(\d+)", addr).groups()
    for p in service.view(None, vid, True)["panels"]:
        d = p.get("data") or {}
        if p.get("type") != "table" or (panels and p["id"] not in panels) or int(r) not in d.get("r", []) or col not in d.get("c", []):
            continue
        return shown(d, col, int(r))
    raise AssertionError(ref)


def test_numbers_read_as_on_the_rest_of_the_dashboard(service):
    """9: day counts as whole days ("1.097", not "1.097,00"), DV01 Risk's P&L rates with two decimals as its other tabs,
    Borsa's O/N swap points as points ("415,50", not "415,50000000") - their look only: the values are the cells' own."""
    # (the O/N table's day columns stand in its helper table since 28.11.2026: "O/N eşlenikleri · ara sütunlar", B27y)
    days = _page_cell(service, "forward", "Forward!K112", ["B27y"])
    assert re.match(r"^\d{1,3}(\.\d{3})*$", days["t"]) and days["v"] == cell(service, "Forward!K112") == int(days["v"])
    vgun = _page_cell(service, "forward", "Forward!M112", ["B27y"])
    assert re.match(r"^\d{1,3}(\.\d{3})*$", vgun["t"]) and vgun["v"] == cell(service, "Forward!M112")
    for ref in ("DV01_RISK!D120", "DV01_RISK!E120", "DV01_RISK!G112"):
        c = _page_cell(service, "dv01", ref)
        assert re.match(r"^\d+,\d{2}%$", c["t"]) and c["v"] == cell(service, ref), (ref, c)
    book = service.books["tto"]
    si, rc = book.cell("DV01_RISK!F120")                                       # an input: typed as before (a pct cell)
    assert service.renderers["tto"].format_of(si, rc) == "0.00%"
    assert {i["range"]: i["kind"] for i in VIEWS["dv01"]["inputs"]}["F120:F134"] == "pct"
    on = _page_cell(service, "borsa", "Sheet1!AE19")
    assert re.match(r"^-?\d{1,3}(\.\d{3})*,\d{2}$", on["t"]) and on["v"] == cell(service, "Sheet1!AE19", book="borsa")
    assert not service.books["tto"].left_out and not service.books["borsa"].left_out
