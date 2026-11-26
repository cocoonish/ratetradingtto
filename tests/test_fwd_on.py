"""The Forward page's pricing tables: an ON karşılık beside each TRY rate (the desk, 26.11.2026: "Toplu forward fiyatlama
kısımlarında ON karşılıklarını da görmek istiyorum. Bu ve bunun gibi başka önerin olur mu" - then, of the proposals,
"Bunların da hepsini yap").

The ON is the Forward calculators' own "ON Karşılık" (``Forward!AH14`` = 360·((1 + TRY·g/360)^(1/g) − 1),
``extras.on_equivalent`` / ``on_simple``) of the table's TRY rate, on the days and the 360 basis the table's own forward
formula applies that rate over:

* FORWARD KOTASYON (``EK_FWD`` USDTRY / EURTRY matrices): each value date's TRY bid / ask % over the date's days from the
  pair's spot (C) - ON bid / ask, typeable (a member of the row-side's two-way group);
* USDTRY / EURTRY FORWARD (the value-date tables): every row's TRY bid / mid / ask % over the table's days (D45 / D56) -
  ON bid / ask typeable, the mid's shown only (the mids are not typed);
* SERBEST FORWARD: the minor % over the row's start → end - typeable;
* FORWARD STARTING SWAP: every row's far TRY % over spot → far and TRY fwd-fwd % over near → far (the period's forward
  ON) - typeable on the Manuel row;
* ÇAPRAZ FORWARD: the Manuel TRY % (typeable) and the İma TRY % over the days its forward counts (EUR from its spot date).

An ON typed gives the rate (``extras.on_rate_back``, the exact inverse), the rest of the row follows; the last typed wins,
Delete goes back to the default, a computed value typed back gives the same row (1e-9).  The two-way tables themselves:
``test_fwd_twoway.py`` (FORWARD KOTASYON), ``test_fwd_iki_yon.py`` (the others)."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import extras as ex
from tto.xl.model import parse_a1


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": v} for ref, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def get(svc, user, *refs):
    return [cell(svc, ref, user) for ref in refs]


def on(rate, days):
    """The Forward calculators' ON Karşılık of a TRY rate in % simple ACT/360 over ``days``, in %."""
    return 360 * ((1 + rate / 100 * days / 360) ** (1 / days) - 1) * 100


def on_back(x, days):
    """Its inverse: the TRY rate in % over ``days`` whose ON karşılık is ``x`` (%)."""
    return ((1 + x / 100 / 360) ** days - 1) * 360 / days * 100


def stored(svc, user, sheet):
    return {k.split("!")[1]: v for (_, k), v in svc.store.user_inputs(user, "tto").items() if k.startswith(sheet + "!")}


def panel(svc, user, view, pid):
    p = next(p for p in svc.view(user, view)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, d, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


def calculator_on(svc, user, start, end, rate):
    """What the Forward page's own Interest 2 SP calculator (USDTRY half) says is the ON karşılık of ``rate`` (%) between
    two dates: its 1st / 2nd Date and TRY typed, its "ON Karşılık" (AH14) read back, in % (its days AH7 checked)."""
    put(svc, user, {"Forward!AH5": start, "Forward!AH6": end, "Forward!AH10": rate / 100})
    days, got = get(svc, user, "Forward!AH7", "Forward!AH14")
    svc.reset_inputs(user, "tto", ["Forward!AH5:AH6", "Forward!AH10"])
    return days, got * 100


#: the ON members: group -> (sheet, member name, range, store, the visible table showing it, its hidden helper)
ON_MEMBERS = {
    "ekfwd-quote": ("EK_FWD", "ON %", "AV5:AW14", "AX5:AY14", "EKF1", "EKF3"),
    "ekfwd-eur-quote": ("EK_FWD", "ON %", "AV104:AW113", "AX104:AY113", "EKF5", "EKF7"),
    "fwdrate-usd-bid": ("EK_FWD", "ON bid %", "V47:V51", "Y47:Y51", "FR1", "EKF4"),
    "fwdrate-usd-ask": ("EK_FWD", "ON ask %", "X47:X51", "Z47:Z51", "FR1", "EKF4"),
    "fwdrate-eur-bid": ("EK_FWD", "ON bid %", "V58:V62", "Y58:Y62", "FR2", "EKF4"),
    "fwdrate-eur-ask": ("EK_FWD", "ON ask %", "X58:X62", "Z58:Z62", "FR2", "EKF4"),
    "fwdfree": ("EK_FWD", "Minor ON %", "N68:N77", "AC68:AC77", "FR3", "EKF4"),
    "fss-manuel": ("Forward", "ON fwd-fwd %", "T179", "AC179", "B34", "B34y"),
    "capraz-forward": ("Forward", "Manuel ON %", "X200:X214", "W200:W214", "B36", "B36y"),
}
#: each visible table's column order: the ON right after the TRY rate(s) it is of
SHOWN = {
    "EKF1": (3, ["TRY bid %", "TRY ask %", "ON bid %", "ON ask %", "USD %"]),
    "EKF5": (102, ["TRY bid %", "TRY ask %", "ON bid %", "ON ask %", "EUR %"]),
    "FR1": (46, ["TRY bid %", "TRY mid %", "TRY ask %", "ON bid %", "ON mid %", "ON ask %", "USDTRY bid"]),
    "FR2": (57, ["TRY bid %", "TRY mid %", "TRY ask %", "ON bid %", "ON mid %", "ON ask %", "EURTRY bid"]),
    "FR3": (67, ["Minor %", "Minor ON %", "Swap"]),
    "B34": (173, ["TRY far %", "ON far %", "TRY fwd-fwd %", "ON fwd-fwd %", "USD fwd-fwd %"]),
}


# ---------------------------------------------------------------------------------------------- the declarations
def test_the_on_columns_are_members_of_their_tables_groups_beside_the_try_rates(svc):
    """Every table's ON is the last member of its two-way group (the members before it as they were), its store a
    personal number input on cells no layout ever had an input on, inside the page's hidden helper table; the page shows
    it right after the TRY rate it is of (the view's "cols"), the stores and helpers not."""
    assert svc.twoway.problems == {}
    book = svc.books["tto"]
    from tto.views import load_views
    view = next(v for v in load_views() if v["id"] == "forward")
    declared = set()
    for i in view["inputs"]:
        declared.update(book.cells_of(i["range"], "Forward"))
    retired = set()
    for x in ex.RETIRED_INPUTS["tto"]:
        retired.update(book.cells_of(x))
    panels = {p["id"]: p for p in view["panels"]}
    for gid, (sheet, name, rng, store, shown, helper) in ON_MEMBERS.items():
        g = svc.twoway.groups[gid]
        m = g.members[-1]
        if gid == "fss-manuel":                                                       # (two: the far's ON before it)
            far = g.members[-2]
            assert (far.name, far.cells, far.store) == ("ON far %", book.cells_of("Forward!S179"), book.cells_of("Forward!AB179"))
        assert (m.name, m.cells, m.store) == (name, book.cells_of("%s!%s" % (sheet, rng)), book.cells_of("%s!%s" % (sheet, store))), gid
        assert not m.own and all(book.inputs[c].kind == "number" and book.inputs[c].scope == "user" for c in m.store)
        assert not set(m.store) & declared and not set(m.store) & retired and all(c not in book.inputs for c in m.cells)
        boxes = set(book.cells_of("%s!%s" % (sheet, panels[helper]["range"])))
        assert panels[helper]["hidden"] and set(m.store) <= boxes, gid
        p = panels[shown]
        assert not p["hidden"] and set(m.cells) <= set(book.cells_of("%s!%s" % (sheet, p["range"]))), gid
    u = svc.login("on sütunlar")["user"]
    put(svc, u, {"Forward!C167": "08.12.2026", "Forward!C168": "08.03.2027", "EK_FWD!C68": "15.12.2026"})
    for pid, (row, heads) in SHOWN.items():
        _, d, _ = panel(svc, u, "forward", pid)
        line = [c.get("t") for c in d["rows"][d["r"].index(row)]]
        at = line.index(heads[0])
        assert line[at:at + len(heads)] == heads, (pid, line)
    _, d, _ = panel(svc, u, "forward", "B36")
    line = [c.get("t") for c in d["rows"][d["r"].index(199)]]
    assert line[line.index("Manuel TRY %"):line.index("Manuel TRY %") + 2] == ["Manuel TRY %", "Manuel ON %"]
    assert line[line.index("İma TRY %"):line.index("İma TRY %") + 3] == ["İma TRY %", "İma ON %", "− RET mid (bp)"]
    assert not {"U", "V", "W"} & set(d["c"]) and d["c"][d["c"].index("F") + 1] == "X"
    # the stores and the rates they give stay out of the visible tables
    for pid, hidden in (("EKF1", {"AN", "AT", "AX", "AY"}), ("FR1", {"N", "T", "Y", "Z"}), ("FR3", {"Z", "AB", "AC"}),
                        ("B34", {"U", "AA", "AB", "AC"})):
        _, d, _ = panel(svc, u, "forward", pid)
        assert not hidden & set(d["c"]), (pid, d["c"])
    svc.reset_inputs(u, "tto")


def test_the_forward_sheets_new_cells_were_empty_in_the_workbook():
    """The cells taken on the workbook's own Forward sheet (FSS's and ÇAPRAZ's ON, their stores, captions) are empty in
    the file - checked when the addition is applied (``_fwd_twoway_check``), else it is left out."""
    import os
    from tto.books import remove_sheets
    from tto.xl.model import Model
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = Model.load(os.path.join(root, "models", "tto.json.gz"))
    remove_sheets("tto", m)
    sh = m.sheet("Forward")
    taken = ["S173", "T173", "S179", "T179", "S181", "T182", "AB178", "AC179", "W199", "X200", "Y214"]
    assert set(taken) <= set(ex.FS_CROSS_TW_CELLS)
    assert all(parse_a1(a) not in sh.fml and sh.consts.get(parse_a1(a)) in (None, "") for a in ex.FS_CROSS_TW_CELLS)
    sh.consts[parse_a1("T176")] = "x"                             # a file that holds something there: left out
    assert [p.split(":")[0] for p in ex.apply("tto", m) if "boş değil" in p] == [ex.FS_CROSS_TW_NAME]


# ---------------------------------------------------------------------------------------------- nothing typed
def test_each_on_is_the_calculators_on_karsilik_of_its_tables_rate_and_days(svc):
    """Nothing typed: each ON is 360·((1 + TRY·g/360)^(1/g) − 1) of the table's own TRY rate, on the days its forward
    formula applies the rate over (1e-12) - and the Forward page's own calculator, given the same two dates and rate,
    says the same (its "ON Karşılık", AH14)."""
    u = svc.login("on hesap")["user"]
    i2, k2, d2 = get(svc, u, "Forward!I2", "Forward!K2", "Forward!D2")
    # FORWARD KOTASYON: the date's days from the pair's spot (C)
    for r, spot in ((5, i2), (9, i2), (104, k2), (107, k2)):
        days, bid, ask, on_bid, on_ask, b = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in ("C", "M", "N", "AV", "AW", "B")))
        assert days == b - spot > 0
        assert on_bid == pytest.approx(on(bid, days), rel=1e-12) and on_ask == pytest.approx(on(ask, days), rel=1e-12)
        if r in (5, 104):
            assert calculator_on(svc, u, spot, b, bid) == pytest.approx((days, on_bid), rel=1e-12)
    # the value-date tables: the table's days (USDTRY from I2, EURTRY from K2), bid / mid / ask
    for t, spot in ((ex.FR_USD, i2), (ex.FR_EUR, k2)):
        days = cell(svc, "EK_FWD!D%d" % (t + 1), u)
        assert days == d2 - spot
        for r in range(t + 3, t + 8):
            rates = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "BCD"))
            ons = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "VWX"))
            assert ons == pytest.approx([on(x, days) for x in rates], rel=1e-12), r
        assert calculator_on(svc, u, spot, d2, rates[0]) == pytest.approx((days, ons[0]), rel=1e-12)
    # SERBEST FORWARD: the row's start → end
    put(svc, u, {"EK_FWD!C68": "15.12.2026", "EK_FWD!A69": "EURTRY", "EK_FWD!C69": "15.03.2027"})
    for r in (68, 69):
        b, c, days, minor, x = get(svc, u, *("EK_FWD!%s%d" % (col, r) for col in "BCDGN"))
        assert days == c - b and x == pytest.approx(on(minor, days), rel=1e-12)
    assert calculator_on(svc, u, b, c, minor) == pytest.approx((days, x), rel=1e-12)
    assert get(svc, u, "EK_FWD!N70") == [""]                                             # (no end date: none)
    # FORWARD STARTING SWAP: every row's far % over spot → far, its fwd-fwd % over near → far
    put(svc, u, {"Forward!C167": "08.12.2026", "Forward!C168": "08.03.2027", "Forward!C169": "40,5", "Forward!I181": 5000})
    near, far, g, h = get(svc, u, "Forward!C167", "Forward!C168", "Forward!G167", "Forward!H167")
    assert (g, h) == (far - i2, far - near)
    for r in ex.FS_ON_ROWS:
        d, e, s, t = get(svc, u, *("Forward!%s%d" % (col, r) for col in "DEST"))
        if r == ex.FS_BACK_EUR:
            assert (d, e, s, t) == ("", "", "", ""), r                                  # (nothing typed there)
            continue
        assert isinstance(d, float) and s == pytest.approx(on(d, g), rel=1e-12) and t == pytest.approx(on(e, h), rel=1e-12), r
    assert calculator_on(svc, u, near, far, 40.5) == pytest.approx((h, cell(svc, "Forward!T179", u)), rel=1e-12)
    d177, s177 = get(svc, u, "Forward!D177", "Forward!S177")                          # RET mid's far
    assert calculator_on(svc, u, i2, far, d177) == pytest.approx((g, s177), rel=1e-12)
    # ÇAPRAZ FORWARD: the Manuel TRY % and the İma TRY % on the days its forward counts (EUR from its spot date)
    put(svc, u, {"Forward!F200": "41", "Forward!R201": 56.0, "Forward!F203": "39,5"})
    for ccy in ("USD", "EUR", "GBP"):
        put(svc, u, {"Forward!C197": ccy})
        for r, rate_col, on_col in ((200, "F", "X"), (201, "S", "Y"), (203, "F", "X")):
            b, c, rate, x = get(svc, u, "Forward!B%d" % r, "Forward!C%d" % r, "Forward!%s%d" % (rate_col, r), "Forward!%s%d" % (on_col, r))
            days = b - k2 if ccy == "EUR" else c
            if not isinstance(rate, float):
                assert x == "", (ccy, r)                     # (another currency's İma TRY %: Bloomberg's forward, none in replay)
                continue
            assert x == pytest.approx(on(rate, days), rel=1e-12), (ccy, r)
    put(svc, u, {"Forward!C197": "USD"})
    b200 = cell(svc, "Forward!B200", u)
    assert calculator_on(svc, u, i2, b200, 41.0) == pytest.approx((cell(svc, "Forward!C200", u), cell(svc, "Forward!X200", u)), rel=1e-12)
    # rows without a rate: no ON
    assert get(svc, u, "Forward!X205", "Forward!Y205") == ["", ""]
    svc.reset_inputs(u, "tto")


def test_the_on_reads_with_two_decimals_its_value_every_digit(svc):
    """The desk's 25.11 rule for the pricing tables' TRY rates (``extras.TRY_PCT``): the ON reads with two decimals, its
    value keeps every digit."""
    import re
    u = svc.login("on ondalık")["user"]
    for pid, refs in (("EKF1", ["AV5", "AW6"]), ("FR1", ["V47", "W48", "X51"]), ("FR2", ["V58"])):
        _, _, m = panel(svc, u, "forward", pid)
        for ref in refs:
            assert re.match(r"^\d+,\d{2}$", m[ref]["t"]) and m[ref]["v"] == cell(svc, "EK_FWD!" + ref, u), (pid, ref, m[ref])
            assert m[ref]["v"] != round(m[ref]["v"], 2)


# ---------------------------------------------------------------------------------------------- FORWARD KOTASYON
def kot(svc, user, r, side):
    """(spread, TRY %, puan, fwd, ON) of a matrix row-side."""
    return get(svc, user, *("EK_FWD!%s%d" % (c, r) for c in (("D", "M", "H", "J", "AV"), ("E", "N", "I", "K", "AW"))[side]))


def kot_from_rate(svc, user, r, side, rate):
    days, ois, major, spot = get(svc, user, *("EK_FWD!%s%d" % (c, r) for c in ("C", "L", "O", "FG"[side])))
    fwd = spot * (1 + rate / 100 * days / 360) / (1 + major / 100 * days / 360)
    return [(rate - ois) * 100, rate, (fwd - spot) * 10000, fwd, on(rate, days)]


@pytest.mark.parametrize("r", [6, 105], ids=["USDTRY", "EURTRY"])
def test_forward_kotasyon_an_on_typed_gives_the_row(svc, r):
    """An ON typed for a value date's side: it stands exactly; the TRY % is its exact inverse over the date's days, the
    spread, puan and fwd follow (the matrix's formulas); every value typed back gives the same row-side (1e-9) and is the
    only one kept; the other side and rows keep theirs; Delete: the general spread again."""
    u = svc.login("on kotasyon %d" % r)["user"]
    days = cell(svc, "EK_FWD!C%d" % r, u)
    default = kot(svc, u, r, 0)
    put(svc, u, {"EK_FWD!AV%d" % r: "39,5"})
    got = kot(svc, u, r, 0)
    assert got[4] == 39.5 and got[1] == pytest.approx(on_back(39.5, days), abs=1e-12)
    assert got == pytest.approx(kot_from_rate(svc, u, r, 0, on_back(39.5, days)), rel=1e-9, abs=1e-9)
    assert stored(svc, u, "EK_FWD") == {"AX%d" % r: 39.5}
    general = ex.FWD_ALL if r < ex.FWD_EUR_ALL else ex.FWD_EUR_ALL
    assert kot(svc, u, r, 1)[0] == cell(svc, "EK_FWD!E%d" % general, u)              # (its ask: the general spread)
    want = got
    for k, col in enumerate(("D", "M", "H", "J", "AV")):
        put(svc, u, {"EK_FWD!%s%d" % (col, r): want[k]})
        assert kot(svc, u, r, 0) == pytest.approx(want, rel=1e-9, abs=1e-9), col
        assert len(stored(svc, u, "EK_FWD")) == 1, (col, stored(svc, u, "EK_FWD"))
    put(svc, u, {"EK_FWD!AW%d" % r: "38"})                                        # the ask side: its own
    assert kot(svc, u, r, 1)[4] == 38.0 and kot(svc, u, r, 0) == pytest.approx(want, rel=1e-9, abs=1e-9)
    put(svc, u, {"EK_FWD!N%d" % r: 41.25})                                         # a TRY % typed: the ON follows
    assert kot(svc, u, r, 1)[4] == pytest.approx(on(41.25, days), rel=1e-12) and "AY%d" % r not in stored(svc, u, "EK_FWD")
    put(svc, u, {"EK_FWD!H%d" % r: ""})                                            # Delete on a computed one of the bid
    assert kot(svc, u, r, 0) == pytest.approx(default, abs=1e-12)
    svc.reset_inputs(u, "tto")


def test_forward_kotasyon_marks_paste_formula_scenario_and_the_desks_summary(svc):
    """The ON typed is marked (✎), the others say they come from it; a column of ONs pasted: each date's typed value; a
    formula reading its own row-side is refused; a scenario keeps it; Masa's summary shows each ON beside its TRY rate and
    takes it typed too (the same cell)."""
    u = svc.login("on kotasyon sayfa")["user"]
    _, _, m0 = panel(svc, u, "forward", "EKF1")
    assert m0["AV5"]["i"] == "u" and "an" not in m0["AV5"]
    put(svc, u, {"EK_FWD!AV7": "40"})
    p, _, m = panel(svc, u, "forward", "EKF1")
    assert m["AV7"]["an"] == "Spread, TRY %, Puan, Fwd" and m["M7"]["ao"] == "ON % · AV7" and m["D7"]["ao"] == "ON % · AV7"
    assert p["note"].count("İki yönlü: spread, TRY %, ON karşılık, puan ya da fwd - hangisini yazarsanız o kalır") == 1
    assert "ON karşılık = TRY faizinin her gün bileşik karşılığı" in cell(svc, "EK_FWD!A16", u)
    # a column pasted from Excel
    res = svc.paste(u, "tto", "EK_FWD!AV5", "38,5\n39\n39,5")
    assert res["errors"] == [] and res["applied"] == 3
    assert stored(svc, u, "EK_FWD") == {"AX5": 38.5, "AX6": 39.0, "AX7": 39.5}
    # a formula reading its own row-side: a cycle
    res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!AV8", "value": "=EK_FWD!M8-1"}])
    assert len(res["errors"]) == 1 and "döngüsel başvuru" in res["errors"][0] and res["errors"][0].startswith("EK_FWD!AV8:")
    put(svc, u, {"EK_FWD!AV8": "=EK_FWD!AW8-0.25"})                                 # (the other side: no cycle)
    assert cell(svc, "EK_FWD!AV8", u) == pytest.approx(cell(svc, "EK_FWD!AW8", u) - 0.25, abs=1e-12)
    want = get(svc, u, "EK_FWD!M5", "EK_FWD!M7", "EK_FWD!AV8")
    svc.save_scenario(u, "on kotasyon")
    svc.reset_inputs(u, "tto")
    assert stored(svc, u, "EK_FWD") == {}
    svc.load_scenario(u, "on kotasyon")
    assert get(svc, u, "EK_FWD!M5", "EK_FWD!M7", "EK_FWD!AV8") == want
    svc.reset_inputs(u, "tto")
    # Masa's summary: Spread | TRY % | ON % per side; an ON typed there is the matrix's
    for pid, row in (("EKS", 3), ("EKSE", 102)):
        _, d, _ = panel(svc, u, "masa", pid)
        assert d["c"] == ["A", "B", "C", "D", "M", "AV", "E", "N", "AW", "F", "G", "H", "I", "J", "K"]
        assert [c.get("t") for c in d["rows"][d["r"].index(row)]][3:9] == ["Spread bid", "TRY bid %", "ON bid %", "Spread ask",
                                                                           "TRY ask %", "ON ask %"]
    put(svc, u, {"EK_FWD!AW6": "39,75"})
    _, _, m = panel(svc, u, "masa", "EKS")
    assert m["AW6"]["an"] and m["N6"]["ao"] == "ON % · AW6" and m["N6"]["v"] == pytest.approx(on_back(39.75, cell(svc, "EK_FWD!C6", u)), abs=1e-12)
    _, _, f = panel(svc, u, "forward", "EKF1")
    assert f["AW6"]["v"] == 39.75 and f["AW6"]["an"]
    assert cell(svc, "EK_FWD!AW6") != 39.75                                          # (nobody else's)
    svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the value-date tables
SIDE = (("B", "E", "H", "K", "V", "L"), ("D", "G", "J", "M", "X", "H"))              # TRY %, fwd, puan, P/gün, ON; the major


def fr(svc, user, r, side):
    return get(svc, user, *("EK_FWD!%s%d" % (c, r) for c in SIDE[side][:5]))


def fr_from_rate(svc, user, t, side, rate):
    days, spot, major = get(svc, user, "EK_FWD!D%d" % (t + 1), "EK_FWD!F%d" % (t + 1), "EK_FWD!%s%d" % (SIDE[side][5], t + 1))
    fwd = spot * (1 + rate / 100 / 360 * days) / (1 + major / 100 / 360 * days)
    return [rate, fwd, (fwd - spot) * 10000, (fwd - spot) * 10000 / days, on(rate, days)]


@pytest.mark.parametrize("side", [0, 1], ids=["bid", "ask"])
def test_the_value_date_tables_an_on_typed_gives_the_row(svc, side):
    """An ON typed in a row-side: the TRY % is its inverse over the table's days, the outright, points and P/gün follow,
    the mid's ON is the ON of the new mid; round trips (1e-9), one value kept; Delete: the curve again."""
    u = svc.login("on valör %d" % side)["user"]
    t = ex.FR_USD
    r = t + 3 + 1                                                                     # OIS
    days = cell(svc, "EK_FWD!D%d" % (t + 1), u)
    curve = fr(svc, u, r, side)
    put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][4], r): "35,25"})
    got = fr(svc, u, r, side)
    assert got[4] == 35.25 and got == pytest.approx(fr_from_rate(svc, u, t, side, on_back(35.25, days)), rel=1e-9, abs=1e-9)
    assert stored(svc, u, "EK_FWD") == {"%s%d" % (ex.FR_TW_ON[side], r): 35.25}
    bid, mid, ask = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "BCD"))
    assert mid == pytest.approx((bid + ask) / 2, abs=1e-12) and cell(svc, "EK_FWD!W%d" % r, u) == pytest.approx(on(mid, days), rel=1e-12)
    want = got
    for k in range(5):
        put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][k], r): want[k]})
        assert fr(svc, u, r, side) == pytest.approx(want, rel=1e-9, abs=1e-9), k
        assert len(stored(svc, u, "EK_FWD")) == 1
    put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][2], r): ""})                              # Delete on its points
    assert fr(svc, u, r, side) == pytest.approx(curve, abs=1e-12) and stored(svc, u, "EK_FWD") == {}
    # the mid is not typed: neither is its ON
    res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!W%d" % r, "value": "35"}])
    assert len(res["errors"]) == 1 and "girdi hücresi değil" in res["errors"][0]
    svc.reset_inputs(u, "tto")


def test_the_eurtry_table_takes_the_rate_an_usdtry_on_gives_and_a_value_date_changed(svc):
    """The EURTRY table's TRY rates are the USDTRY table's: an ON typed in the USDTRY table moves EURTRY's TRY rate - its
    ON is that rate's over EURTRY's own days - unless something is typed in the EURTRY row itself; an ON typed in the
    EURTRY table gives EURTRY's rate on its days, the USDTRY row as it was.  The value date changed: the ON typed stays,
    the rate is its inverse over the new days."""
    u = svc.login("on valör eur")["user"]
    r, re_ = ex.FR_USD + 3 + 3, ex.FR_EUR + 3 + 3                                    # RET
    d_usd, d_eur = get(svc, u, "EK_FWD!D%d" % (ex.FR_USD + 1), "EK_FWD!D%d" % (ex.FR_EUR + 1))
    put(svc, u, {"EK_FWD!V%d" % r: "34"})
    rate = on_back(34.0, d_usd)
    assert cell(svc, "EK_FWD!B%d" % r, u) == pytest.approx(rate, abs=1e-12)
    assert cell(svc, "EK_FWD!B%d" % re_, u) == pytest.approx(rate, abs=1e-12)
    assert fr(svc, u, re_, 0) == pytest.approx(fr_from_rate(svc, u, ex.FR_EUR, 0, rate), rel=1e-9, abs=1e-9)
    assert cell(svc, "EK_FWD!V%d" % re_, u) == pytest.approx(on(rate, d_eur), rel=1e-12) and d_eur != d_usd
    put(svc, u, {"EK_FWD!V%d" % re_: "33"})                                         # EURTRY's own
    assert cell(svc, "EK_FWD!B%d" % re_, u) == pytest.approx(on_back(33.0, d_eur), abs=1e-12)
    assert cell(svc, "EK_FWD!B%d" % r, u) == pytest.approx(rate, abs=1e-12)
    put(svc, u, {"EK_FWD!V%d" % re_: ""})
    d2 = cell(svc, "Forward!D2", u)
    put(svc, u, {"Forward!D2": d2 + 31})
    d_usd2 = cell(svc, "EK_FWD!D%d" % (ex.FR_USD + 1), u)
    assert d_usd2 == d_usd + 31 and cell(svc, "EK_FWD!V%d" % r, u) == 34.0
    assert fr(svc, u, r, 0) == pytest.approx(fr_from_rate(svc, u, ex.FR_USD, 0, on_back(34.0, d_usd2)), rel=1e-9, abs=1e-9)
    svc.reset_inputs(u, "tto")


def test_the_value_date_tables_marks_and_note(svc):
    """The ON typed is marked, the row's others say where they come from; the note names the ON."""
    u = svc.login("on valör işaret")["user"]
    put(svc, u, {"EK_FWD!X49": "33,5"})
    p, _, m = panel(svc, u, "forward", "FR1")
    assert m["X49"]["an"] == "TRY ask %, USDTRY ask, Puan ask, P/gün ask" and m["D49"]["ao"] == "ON ask % · X49"
    assert m["W49"].get("i") is None and "an" not in m["V49"]
    assert "TRY %, ON karşılık, forward, puan ya da P/gün" in p["note"] and "ON karşılık = " in p["note"]
    p2, _, _ = panel(svc, u, "forward", "FR2")
    assert "ON karşılık da bu günle" in p2["note"]
    svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- SERBEST FORWARD
def test_the_free_forward_list_an_on_typed_gives_the_minor(svc):
    """The minor's ON typed: the minor % is its inverse over the row's start → end, the swap and forward follow (the row's
    spot, major and days); round trips; Delete: the curve; no end date: the ON typed alone."""
    u = svc.login("on serbest")["user"]
    r = ex.FR_LIST + 3
    put(svc, u, {"EK_FWD!C%d" % r: "15.02.2027"})
    spot, major, days, minor = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "EFDG"))

    def row():
        return get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "GHIN"))

    def off(rate):
        fwd = spot * (1 + rate / 100 * days / 360) / (1 + major / 100 * days / 360)
        return [rate, (fwd - spot) * 10000, fwd, on(rate, days)]

    assert row() == pytest.approx(off(minor), rel=1e-9, abs=1e-9)
    put(svc, u, {"EK_FWD!N%d" % r: "33,3"})
    assert row()[3] == 33.3 and row() == pytest.approx(off(on_back(33.3, days)), rel=1e-9, abs=1e-9)
    want = row()
    for k, col in enumerate("GHIN"):
        put(svc, u, {"EK_FWD!%s%d" % (col, r): want[k]})
        assert row() == pytest.approx(want, rel=1e-9, abs=1e-9), col
        assert [k2 for k2 in stored(svc, u, "EK_FWD") if not k2.startswith("C")] == [
            {"G": "G", "H": "Z", "I": "AA", "N": "AC"}[col] + str(r)]
    put(svc, u, {"EK_FWD!I%d" % r: ""})
    assert row() == pytest.approx(off(minor), rel=1e-9, abs=1e-9)
    put(svc, u, {"EK_FWD!N%d" % r: "30", "EK_FWD!C%d" % r: ""})                     # no end date: only the ON typed
    assert row() == ["", "", "", 30.0] and cell(svc, "EK_FWD!AB%d" % r, u) == ""
    svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- FORWARD STARTING SWAP
FSS = ("C169", "D179", "S179", "T179", "H179", "I179", "N179")


def fss(svc, user):
    return get(svc, user, *("Forward!" + a for a in FSS))


@pytest.fixture()
def fss_user(svc):
    u = svc.login("on fss")["user"]
    put(svc, u, {"Forward!C167": "08.12.2026", "Forward!C168": "08.03.2027"})
    assert cell(svc, "Forward!F169", u) == "OK"
    yield u
    svc.reset_inputs(u, "tto")


def test_fss_an_on_typed_gives_the_manuel_row(svc, fss_user):
    """The Manuel row: an ON fwd-fwd typed gives the TRY fwd-fwd % (its inverse over near → far), the far legs follow; an
    ON far typed gives the far TRY % (its inverse over spot → far) and the TRY fwd-fwd % D179's formula solved for it, as
    a far TRY % typed; every value typed back gives the same row (1e-9), one kept; Durum not OK: only the ON typed."""
    u = fss_user
    g, h = get(svc, u, "Forward!G167", "Forward!H167")
    assert fss(svc, u) == [""] * 7 and get(svc, u, "Forward!S179", "Forward!T179") == ["", ""]
    put(svc, u, {"Forward!T179": "38,25"})
    got = fss(svc, u)
    assert got[3] == 38.25 and got[0] == pytest.approx(on_back(38.25, h), abs=1e-12)
    put(svc, u, {"Forward!C169": got[0]})                                            # the same rate typed in C169
    assert fss(svc, u) == pytest.approx(got, rel=1e-9, abs=1e-9)
    assert got[2] == pytest.approx(on(got[1], g), rel=1e-12)
    put(svc, u, {"Forward!S179": "37,5"})
    got = fss(svc, u)
    c177, f = get(svc, u, "Forward!C177", "Forward!F167")
    far = on_back(37.5, g)
    assert got[2] == 37.5 and got[1] == pytest.approx(far, rel=1e-9, abs=1e-9)
    assert got[0] == pytest.approx(((1 + far / 100 * g / 360) / (1 + c177 / 100 * f / 360) - 1) * 360 / h * 100, abs=1e-12)
    assert got[3] == pytest.approx(on(got[0], h), rel=1e-12)
    want = got
    stores = {"C169": "C169", "D179": "U179", "S179": "AB179", "T179": "AC179", "H179": "V179", "I179": "W179", "N179": "Y179"}
    for k, ref in enumerate(FSS):
        put(svc, u, {"Forward!" + ref: want[k]})
        assert fss(svc, u) == pytest.approx(want, rel=1e-9, abs=1e-9), ref
        assert [x for x in stored(svc, u, "Forward") if x not in ("C167", "C168")] == [stores[ref]], ref
    put(svc, u, {"Forward!T179": "38"})
    put(svc, u, {"Forward!C168": "01.12.2026"})                                      # far before near: not OK
    assert cell(svc, "Forward!F169", u) != "OK" and fss(svc, u) == ["", "", "", 38.0, "", "", ""]
    put(svc, u, {"Forward!C168": "08.03.2027"})
    assert fss(svc, u)[0] == pytest.approx(on_back(38.0, h), abs=1e-12)
    put(svc, u, {"Forward!H179": ""})                                                # Delete on a computed one
    assert fss(svc, u) == [""] * 7 and stored(svc, u, "Forward") == {"C167": cell(svc, "Forward!C167", u),
                                                                     "C168": cell(svc, "Forward!C168", u)}


def test_fss_marks_note_and_a_temporary_copy(svc, fss_user):
    """The ON typed is marked, the row says so; FSS is a copyable calculator: an ON typed in its copy is the copy's
    Manuel row, the table stays."""
    u = fss_user
    put(svc, u, {"Forward!T179": "38"})
    p, _, m = panel(svc, u, "forward", "B34")
    assert m["T179"]["an"] and m["C169"]["ao"] == "ON fwd-fwd % · T179" and m["S179"]["ao"] == "ON fwd-fwd % · T179"
    assert "ikisinin ON karşılığı" in p["note"] and p["note"].startswith("Elle puan → faiz")
    svc.reset_inputs(u, "tto", ["Forward!T179"])
    cid = svc.copy_action(u, "open", {"view": "forward", "panel": "B34"})["copy"]["id"]
    try:
        res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "Forward!T179", "value": "37"}]})
        assert res["errors"] == []
        assert fss(svc, u) == [""] * 7                                               # the table's own: nothing typed
        pane = next(x for x in svc.view(u, "forward")["panels"] if (x.get("copy") or {}).get("id") == cid)
        d = pane["data"]
        cells = {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}
        assert cells["T179"].get("v") == 37.0 and cells["T179"]["an"]
        assert cells["C169"]["v"] == pytest.approx(on_back(37.0, cell(svc, "Forward!H167", u)), abs=1e-12)
    finally:
        svc.copy_action(u, "close", {"copy": cid})


# ---------------------------------------------------------------------------------------------- ÇAPRAZ FORWARD
def test_cross_an_on_typed_gives_the_manuel_try_and_stays_when_the_currency_changes(svc):
    """ÇAPRAZ: a Manuel ON typed gives the Manuel TRY % (its inverse over the row's days: USD from the USDTRY spot, EUR
    from its own), the manual forward follows; round trips; a forward typed clears it.  The currency changed: the forward
    typed goes, the ON typed stays - a TRY rate - its Manuel TRY % now over the new currency's days."""
    u = svc.login("on çapraz")["user"]
    r = ex.CROSS_ROWS[0] + 2
    put(svc, u, {"Forward!C197": "USD"})
    c = cell(svc, "Forward!C%d" % r, u)
    put(svc, u, {"Forward!X%d" % r: "39"})
    f, q, x = get(svc, u, *("Forward!%s%d" % (col, r) for col in "FQX"))
    assert x == 39.0 and f == pytest.approx(on_back(39.0, c), abs=1e-12) and isinstance(q, float)
    want = [f, q, x]
    for k, col in enumerate("FQX"):
        put(svc, u, {"Forward!%s%d" % (col, r): want[k]})
        assert get(svc, u, *("Forward!%s%d" % (cc, r) for cc in "FQX")) == pytest.approx(want, rel=1e-9, abs=1e-9), col
        assert [k2 for k2 in stored(svc, u, "Forward") if k2 != "C197"] == [{"F": "F", "Q": "U", "X": "W"}[col] + str(r)]
    put(svc, u, {"Forward!X%d" % r: "39", "Forward!Q%d" % (r + 1): 52.5})
    put(svc, u, {"Forward!C197": "EUR"})
    b, k2 = get(svc, u, "Forward!B%d" % r, "Forward!K2")
    assert stored(svc, u, "Forward") == {"C197": "EUR", "W%d" % r: 39.0}               # the forward went, the ON stayed
    assert cell(svc, "Forward!X%d" % r, u) == 39.0 and cell(svc, "Forward!F%d" % r, u) == pytest.approx(on_back(39.0, b - k2), abs=1e-12)
    assert get(svc, u, "Forward!F%d" % (r + 1), "Forward!X%d" % (r + 1)) == ["", ""]
    _, _, m = panel(svc, u, "forward", "B36")
    assert m["X%d" % r]["an"] == "Manuel TRY %, Fwd (manuel)" and m["F%d" % r]["ao"] == "Manuel ON % · X" + str(r)
    svc.reset_inputs(u, "tto")


def test_cross_the_yontem_row_keeps_its_merged_cells(svc):
    """ÇAPRAZ FORWARD shows its ON columns in an order of its own ("cols"): the workbook's merged cells of its "Yöntem"
    row stay one cell each (E197:F197, H197:Q197), every row as long as the header."""
    u = svc.login("on çapraz satır")["user"]
    _, d, m = panel(svc, u, "forward", "B36")
    assert m["E197"].get("cs") == 2 and m["H197"].get("cs") == 10 and m["F197"].get("sk") and m["Q197"].get("sk")
    for r, line in zip(d["r"], d["rows"]):
        assert sum(x.get("cs", 1) for x in line if not x.get("sk")) == len(d["c"]), r     # (every column drawn once)


def test_pick_columns_keeps_a_span_whose_columns_still_follow_it():
    """``_pick_columns``: a merged cell keeps the columns it covered that still follow it in the order asked for; one it
    no longer reaches is a cell of its own again; a span over a column dropped ends there."""
    from tto.service import _pick_columns
    data = {"c": ["A", "B", "C", "D", "E"], "r": [1, 2],
            "rows": [[{"t": "a"}, {"t": "m", "cs": 3}, {"sk": 1}, {"sk": 1}, {"t": "e"}],
                     [{"t": "1"}, {"t": "2"}, {"t": "3"}, {"t": "4"}, {"t": "5"}]]}
    _pick_columns(data, ["A", "E", "B", "C", "D"])
    assert [x.get("t") for x in data["rows"][0]] == ["a", "e", "m", None, None] and data["rows"][0][2]["cs"] == 3
    data = {"c": ["A", "B", "C", "D"], "r": [1], "rows": [[{"t": "m", "cs": 3}, {"sk": 1}, {"sk": 1}, {"t": "d"}]]}
    _pick_columns(data, ["A", "B", "D", "C"])
    row = data["rows"][0]
    assert row[0]["cs"] == 2 and row[1] == {"sk": 1} and row[3] == {} and data["c"] == ["A", "B", "D", "C"]
