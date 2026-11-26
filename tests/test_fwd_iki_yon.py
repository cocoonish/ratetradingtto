"""The Forward page's tables two-way (the desk, 24.11.2026: "Ancak ben hazırda olan forward kotasyon kısmında hem spread
hem faizler girdi olabilsin, hangisine ben girdiysem diğerini hesaplasın istemiştim. Genel olarak tablolar bu şekilde
olmalı karışıklık olmaması için" - "Bu söylediklerin ve tüm tablolar bu şekilde olmalı, kolay çalışmamız için"): of a
row's (and side's) linked values any can be typed, the one typed last stands, the others are worked out from it with the
table's own formulas and their exact inverses (``extras.implied_try``).

* TOPLU FORWARD (``EK_BULK``): Manuel TRY % (in place), ON karşılık % (26.11.2026: the O/N equivalent of the row's TRY
  rate, the Forward calculators' own), USDTRY fwd / puan, EURTRY fwd / puan, and (26.11.2026, "Bunların da hepsini
  yap") Spread (bp) over RET mid and both pairs' P/gün - one TRY rate prices both pairs; the table's general spread; the
  display columns (ON − RET ON, the period from the filled row above, the ON of every rate column); "İşleme al" books a
  USDTRY fwd / puan typed as the outright, the price the row shows;
* the value-date tables USDTRY / EURTRY FORWARD (``EK_FWD`` rows 47–51 / 58–62): per row and side TRY % (in place),
  outright, puan, P/gün; the EURTRY table's TRY rates follow the USDTRY table's; a value typed stays when the value date
  changes;
* SERBEST FORWARD (``EK_FWD`` rows 68–77): minor % (in place), swap, forward;
* FORWARD STARTING SWAP's Manuel row (``Forward`` row 179): the TRY fwd-fwd % (C169, in place), far TRY %, USDTRY far /
  FS puan / günlük puan, EURTRY far / puan;
* ÇAPRAZ FORWARD (``Forward`` rows 200–214): Manuel TRY % (in place) and the manual forward - a forward typed goes when
  the currency (C197) changes.

The mechanism itself: ``test_twoway.py``; FORWARD KOTASYON: ``test_fwd_twoway.py``."""
from __future__ import annotations

import json
import os
import re

import pytest

from conftest import ROOT, cell
from tto import entry
from tto import extras as ex
from tto.xl.model import COLS, parse_a1

#: the groups: id -> (sheet, [(member name, member range, store range or None)])
GROUPS = {
    "toplu-forward": ("EK_BULK", [("Manuel TRY %", "L5:L104", None), ("Spread (bp)", "I5:I104", "AF5:AF104"),
                                  ("ON karşılık %", "M5:M104", "AE5:AE104"), ("USDTRY fwd", "N5:N104", "Z5:Z104"),
                                  ("USDTRY puan", "O5:O104", "AA5:AA104"), ("USDTRY P/gün", "AO5:AO104", "AG5:AG104"),
                                  ("EURTRY fwd", "P5:P104", "AB5:AB104"), ("EURTRY puan", "Q5:Q104", "AC5:AC104"),
                                  ("EURTRY P/gün", "AP5:AP104", "AH5:AH104")]),
    # (the ON karşılık of 26.11.2026: the last member of each but TOPLU FORWARD's - test_fwd_on.py; TOPLU FORWARD's sits
    # beside its Manuel TRY %, its column M - the tests below)
    "fwdrate-usd-bid": ("EK_FWD", [("TRY bid %", "B47:B51", None), ("USDTRY bid", "E47:E51", "N47:N51"),
                                   ("Puan bid", "H47:H51", "O47:O51"), ("P/gün bid", "K47:K51", "P47:P51"),
                                   ("ON bid %", "V47:V51", "Y47:Y51")]),
    "fwdrate-usd-ask": ("EK_FWD", [("TRY ask %", "D47:D51", None), ("USDTRY ask", "G47:G51", "Q47:Q51"),
                                   ("Puan ask", "J47:J51", "R47:R51"), ("P/gün ask", "M47:M51", "S47:S51"),
                                   ("ON ask %", "X47:X51", "Z47:Z51")]),
    "fwdrate-eur-bid": ("EK_FWD", [("TRY bid %", "B58:B62", None), ("EURTRY bid", "E58:E62", "N58:N62"),
                                   ("Puan bid", "H58:H62", "O58:O62"), ("P/gün bid", "K58:K62", "P58:P62"),
                                   ("ON bid %", "V58:V62", "Y58:Y62")]),
    "fwdrate-eur-ask": ("EK_FWD", [("TRY ask %", "D58:D62", None), ("EURTRY ask", "G58:G62", "Q58:Q62"),
                                   ("Puan ask", "J58:J62", "R58:R62"), ("P/gün ask", "M58:M62", "S58:S62"),
                                   ("ON ask %", "X58:X62", "Z58:Z62")]),
    "fwdfree": ("EK_FWD", [("Minor %", "G68:G77", None), ("Swap", "H68:H77", "Z68:Z77"), ("Forward", "I68:I77", "AA68:AA77"),
                           ("Minor ON %", "N68:N77", "AC68:AC77")]),
    "fss-manuel": ("Forward", [("TRY fwd-fwd %", "C169", None), ("TRY far %", "D179", "U179"), ("Far outright", "H179", "V179"),
                               ("FS puan", "I179", "W179"), ("Günlük puan", "J179", "X179"), ("EURTRY far", "N179", "Y179"),
                               ("EURTRY puan", "O179", "Z179"), ("ON far %", "S179", "AB179"), ("ON fwd-fwd %", "T179", "AC179")]),
    "capraz-forward": ("Forward", [("Manuel TRY %", "F200:F214", None), ("Fwd (manuel)", "Q200:Q214", "U200:U214"),
                                   ("Manuel ON %", "X200:X214", "W200:W214")]),
}
#: the hidden helper table of the page each group's stores are in
HELPERS = {"toplu-forward": "BK2", "fwdrate-usd-bid": "EKF4", "fwdrate-usd-ask": "EKF4", "fwdrate-eur-bid": "EKF4",
           "fwdrate-eur-ask": "EKF4", "fwdfree": "EKF4", "fss-manuel": "B34y", "capraz-forward": "B36y"}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": v} for ref, v in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def get(svc, user, *refs):
    return [cell(svc, ref, user) for ref in refs]


def stored(svc, user, sheet):
    """What the user keeps on a sheet (typed values and stores), by address."""
    return {k.split("!")[1]: v for (_, k), v in svc.store.user_inputs(user, "tto").items() if k.startswith(sheet + "!")}


def panel(svc, user, pid, helpers=False):
    p = next(p for p in svc.view(user, "forward", helpers)["panels"] if p["id"] == pid)
    d = p["data"]
    return p, {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}


# ---------------------------------------------------------------------------------------------- the declarations
def test_the_tables_are_two_way_groups_with_stores_on_cells_no_input_ever_stood_on(svc):
    """Eight groups, every one usable: the in-place member the table's input from before (its values keep their meaning),
    the others formulas whose typed values are kept in stores - personal number inputs declared by the group, on cells no
    layout ever had an input on, inside a hidden helper table of the page.  The page's JSON has one "twoway" list (no key
    twice: a merge must not leave two)."""
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
    for gid, (sheet, members) in GROUPS.items():
        g = svc.twoway.groups[gid]
        assert (g.sheet, g.scope, [m.name for m in g.members]) == (sheet, "user", [m[0] for m in members]), gid
        for m, (_, rng, store) in zip(g.members, members):
            assert m.cells == book.cells_of("%s!%s" % (sheet, rng)), (gid, rng)
            if store is None:
                assert m.own and all(book.inputs[c].scope == "user" for c in m.cells)
                continue
            assert m.store == book.cells_of("%s!%s" % (sheet, store))
            assert all(c not in book.inputs or book.inputs[c].group.startswith("twoway:") for c in m.store)
            assert all(book.inputs[c].kind == "number" and book.inputs[c].scope == "user" for c in m.store)
            assert not set(m.store) & declared and not set(m.store) & retired and all(c not in book.inputs for c in m.cells)
        helper = panels[HELPERS[gid]]
        assert helper["hidden"] and helper.get("sheet", "Forward") == sheet, gid
        boxes = book.cells_of("%s!%s" % (sheet, helper["range"]))
        assert all(c in boxes for m in g.members if not m.own for c in m.store), gid
    assert ex.BULK_TW_ID in svc.twoway.groups and ex.CROSS_TW_ID in svc.twoway.groups

    def no_twice(pairs):
        keys = [k for k, _ in pairs]
        assert len(keys) == len(set(keys)), keys
        return dict(pairs)

    with open(os.path.join(ROOT, "tto", "views", "30_forward.json"), encoding="utf-8") as fh:
        json.load(fh, object_pairs_hook=no_twice)


def test_nothing_typed_every_value_as_before(svc):
    """With nothing typed the tables show what they did before they were two-way: the in-place inputs their old default
    (the curves' rates; TOPLU FORWARD's Manuel TRY %, the Manuel row's rate and ÇAPRAZ's Manuel TRY % blank - the Manuel
    row hidden), the members the table's own formulas (here against the Forward sheet's own tables, as their tests)."""
    usd, eur = ex.FR_USD, ex.FR_EUR
    for t, fwd in ((usd, 30), (eur, 42)):
        for k in range(len(ex.FR_NAMES)):
            r = t + 3 + k
            mine = [cell(svc, "EK_FWD!%s%d" % (c, r)) for c in "EFGHIJ"]
            assert mine == pytest.approx([cell(svc, "Forward!%s%d" % (c, fwd + k)) for c in "DEF"] + [
                (x - cell(svc, "EK_FWD!F%d" % (t + 1))) * 10000 for x in mine[:3]], rel=1e-12)
    assert [cell(svc, "EK_FWD!B%d" % (usd + 3 + k)) for k in range(4)] == pytest.approx(
        [cell(svc, "Forward!%s" % a) * 100 for a in ("I22", "O25", "C18", "W48")], rel=1e-15)
    assert [cell(svc, "EK_FWD!B%d" % (eur + 3 + k)) for k in range(5)] == [cell(svc, "EK_FWD!B%d" % (usd + 3 + k)) for k in range(5)]
    assert cell(svc, "EK_BULK!L5") == "" and cell(svc, "EK_BULK!N5") == "" and cell(svc, "EK_BULK!AD5") == ""
    assert cell(svc, "EK_BULK!M5") == "" and cell(svc, "EK_BULK!M4") == "ON karşılık %" and cell(svc, "EK_BULK!AE5") is None
    assert all(cell(svc, "EK_BULK!%s5" % c) == "" for c in ("I", "AI", "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AQ", "AU"))
    assert cell(svc, "Forward!C169") == "" and cell(svc, "Forward!D179") == "" and cell(svc, "Forward!AA179") == ""
    assert all(cell(svc, "Forward!%s%d" % (c, r)) == "" for r in range(200, 215) for c in "FV")


# ---------------------------------------------------------------------------------------------- TOPLU FORWARD
D1, D2 = "15.01.2027", "15.04.2027"
#: the group's members, by column: Manuel TRY %, Spread (bp), ON karşılık %, USDTRY fwd / puan / P/gün, EURTRY fwd / puan /
#: P/gün - and where what is typed into each is kept (Manuel TRY %: in place)
BULK = ("L", "I", "M", "N", "O", "AO", "P", "Q", "AP")
BULK_STORE = {"L": "L", "I": ex.BULK_TW_SPREAD, "M": ex.BULK_TW_ON, "N": "Z", "O": "AA", "AO": ex.BULK_TW_USD_PPD, "P": "AB",
              "Q": "AC", "AP": ex.BULK_TW_EUR_PPD}


def bulk(svc, user, r):
    """A row's members, by column."""
    return dict(zip(BULK, get(svc, user, *("EK_BULK!%s%d" % (c, r) for c in BULK))))


def typed_cols(svc, user):
    """The columns of the cells a user keeps on the table's rows (stores and in-place values), valör aside."""
    return {k for k in stored(svc, user, "EK_BULK") if not k.startswith("B") and k != ex.BULK_SPREAD_ALL}


def on_of(rate, days):
    """The Forward calculators' "ON Karşılık" (``Forward!AH14``: 360·((1 + TRY·g/360)^(1/g) − 1)) of a rate in %, in %."""
    return 360 * ((1 + rate / 100 * days / 360) ** (1 / days) - 1) * 100


def rate_of_on(on, days):
    """Its exact inverse, the simple rate over ``days`` an O/N rate gives (``Forward!AH52``: ((1 + ON/360)^g − 1)·360/g), in %."""
    return ((1 + on / 100 / 360) ** days - 1) * 360 / days * 100


def bulk_market(svc, user, r):
    """What a row's prices are made of: days (USDTRY, EURTRY), USD %, EUR %, spots, RET mid."""
    days = cell(svc, "EK_BULK!C%d" % r, user)
    eur_days = cell(svc, "EK_BULK!B%d" % r, user) - cell(svc, "Forward!K2", user)
    usd, eur, g = get(svc, user, "EK_BULK!J%d" % r, "EK_BULK!K%d" % r, "EK_BULK!G%d" % r)
    return days, eur_days, usd, eur, cell(svc, "Forward!F2", user), cell(svc, "Forward!G2", user), g


def bulk_from_rate(svc, user, r, rate, shown=None):
    """The row off a TRY rate, worked out here: Spread = (TRY − RET mid)·100, its ON over the row's Gün (USDTRY's days),
    N = F2·(1 + TRY·g/360)/(1 + USD·g/360), P = G2·(...EUR days, EUR %), puan = (fwd − spot)·10000, P/gün = puan / the
    pair's days."""
    days, eur_days, usd, eur, s_usd, s_eur, g = bulk_market(svc, user, r)
    n = s_usd * (1 + rate / 100 * days / 360) / (1 + usd / 100 * days / 360)
    p = s_eur * (1 + rate / 100 * eur_days / 360) / (1 + eur / 100 * eur_days / 360)
    return {"L": rate if shown is None else shown, "I": (rate - g) * 100, "M": on_of(rate, days), "N": n,
            "O": (n - s_usd) * 10000, "AO": (n - s_usd) * 10000 / days, "P": p, "Q": (p - s_eur) * 10000,
            "AP": (p - s_eur) * 10000 / eur_days}


def implied(fwd, spot, major, days):
    return ((fwd / spot) * (1 + major / 100 * days / 360) - 1) * 360 / days * 100


@pytest.fixture(scope="module")
def bulk_user(svc):
    u = svc.login("iy toplu")["user"]
    put(svc, u, {"EK_BULK!B5": D1, "EK_BULK!B6": D2, "EK_BULK!B7": D1})
    return u


def test_bulk_each_member_typed_gives_the_others(svc, bulk_user):
    """A Manuel TRY %, a USDTRY fwd, puan or P/gün, an EURTRY fwd, puan or P/gün, an ON karşılık %, a Spread (bp) typed:
    that one exactly, the others from the TRY rate it gives - one rate prices both pairs, so a USDTRY forward typed moves
    the row's EURTRY forward and the other way round; the ON is the rate's over the row's Gün, an ON typed gives the rate
    by the exact inverse; a spread typed gives RET mid + spread / 100; a P/gün typed gives puan = P/gün · the pair's days,
    fwd = spot + puan / 10000 and the rate that outright implies (EURTRY on its own days); the other rows keep theirs."""
    u = bulk_user
    for r in (5, 6):
        days, eur_days, usd, eur, s_usd, s_eur, g = bulk_market(svc, u, r)
        assert bulk(svc, u, r) == pytest.approx(bulk_from_rate(svc, u, r, g, ""), abs=1e-9)      # nothing typed: RET mid
        put(svc, u, {"EK_BULK!L%d" % r: "41,5"})
        assert bulk(svc, u, r) == pytest.approx(bulk_from_rate(svc, u, r, 41.5), abs=1e-9)
        fwd = round(bulk_from_rate(svc, u, r, g)["N"] + 0.0521, 4)
        put(svc, u, {"EK_BULK!N%d" % r: fwd})
        got = bulk(svc, u, r)
        assert got["N"] == fwd and got == pytest.approx(bulk_from_rate(svc, u, r, implied(fwd, s_usd, usd, days)), abs=1e-9)
        pts = 12345.5
        put(svc, u, {"EK_BULK!O%d" % r: pts})
        got = bulk(svc, u, r)
        assert got["O"] == pts and got["N"] == s_usd + pts / 10000
        assert got == pytest.approx(bulk_from_rate(svc, u, r, implied(s_usd + pts / 10000, s_usd, usd, days)), abs=1e-9)
        eur_fwd = round(bulk_from_rate(svc, u, r, g)["P"] - 0.0377, 4)
        put(svc, u, {"EK_BULK!P%d" % r: eur_fwd})
        got = bulk(svc, u, r)
        assert got["P"] == eur_fwd and got == pytest.approx(bulk_from_rate(svc, u, r, implied(eur_fwd, s_eur, eur, eur_days)), abs=1e-9)
        put(svc, u, {"EK_BULK!Q%d" % r: 9999})
        got = bulk(svc, u, r)
        assert got["Q"] == 9999.0 and got["P"] == s_eur + 9999 / 10000
        assert got == pytest.approx(bulk_from_rate(svc, u, r, implied(s_eur + 0.9999, s_eur, eur, eur_days)), abs=1e-9)
        put(svc, u, {"EK_BULK!M%d" % r: "33,25"})
        got = bulk(svc, u, r)
        assert got["M"] == 33.25 and got["L"] == pytest.approx(rate_of_on(33.25, days), abs=1e-12)
        assert got == pytest.approx(bulk_from_rate(svc, u, r, rate_of_on(33.25, days)), abs=1e-9)
        put(svc, u, {"EK_BULK!I%d" % r: "40"})
        got = bulk(svc, u, r)
        assert got["I"] == 40.0 and got["L"] == g + 40 / 100
        assert got == pytest.approx(bulk_from_rate(svc, u, r, g + 40 / 100), abs=1e-9)
        put(svc, u, {"EK_BULK!AO%d" % r: "120,5"})
        got = bulk(svc, u, r)
        assert got["AO"] == 120.5 and got["O"] == 120.5 * days and got["N"] == s_usd + 120.5 * days / 10000
        assert got == pytest.approx(bulk_from_rate(svc, u, r, implied(s_usd + 120.5 * days / 10000, s_usd, usd, days)), rel=1e-12, abs=1e-9)
        put(svc, u, {"EK_BULK!AP%d" % r: "150,5"})
        got = bulk(svc, u, r)
        assert got["AP"] == 150.5 and got["Q"] == 150.5 * eur_days and got["P"] == s_eur + 150.5 * eur_days / 10000
        assert got == pytest.approx(bulk_from_rate(svc, u, r, implied(s_eur + 150.5 * eur_days / 10000, s_eur, eur, eur_days)),
                                    rel=1e-12, abs=1e-9)
    # (row 7, the same date, nothing typed: RET mid)
    assert bulk(svc, u, 7) == pytest.approx(bulk_from_rate(svc, u, 7, cell(svc, "EK_BULK!G7", u), ""), abs=1e-9)
    # the "elle" columns stay as they were: their own way back, beside
    put(svc, u, {"EK_BULK!R5": 52.0})
    days, _, usd, _, s_usd, _, _ = bulk_market(svc, u, 5)
    assert cell(svc, "EK_BULK!S5", u) == pytest.approx(implied(52.0, s_usd, usd, days), abs=1e-12)
    assert stored(svc, u, "EK_BULK") == {"B5": cell(svc, "EK_BULK!B5", u), "B6": cell(svc, "EK_BULK!B6", u),
                                         "B7": cell(svc, "EK_BULK!B7", u), "AH5": 150.5, "AH6": 150.5, "R5": 52.0}
    svc.reset_inputs(u, "tto", ["EK_BULK!I5:AP6", "EK_BULK!R5"])


def test_bulk_on_is_the_forward_calculators_on_of_the_rate_that_prices_the_row(svc, bulk_user):
    """ON karşılık % (the desk, 26.11.2026: "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek
    istiyorum"): the O/N equivalent of the TRY rate the row's N / P take - Manuel TRY % if any, else RET mid % - over the
    row's Gün (value date − USDTRY spot), exactly as the Forward calculator's "ON Karşılık" (Forward!AH14) gives it for
    the same rate and days (calendar days on 360); the integrator's check values (120 days: 35,30 % → 33,3884 %,
    35,0135 % → 33,1317 %); blank without a valör and at Gün 0 (a valör at the spot: no period - an ON typed there
    stays, it gives no rate); every digit kept, two decimals shown."""
    u = bulk_user
    try:
        days, _, _, _, _, _, g = bulk_market(svc, u, 5)
        assert days == cell(svc, "EK_BULK!B5", u) - cell(svc, "Forward!I2", u)
        assert cell(svc, "EK_BULK!M5", u) == pytest.approx(on_of(g, days), abs=1e-12)
        # the calculator (Interest 2 SP, USDTRY): from the spot to the row's valör, at the row's rate
        put(svc, u, {"Forward!AH5": cell(svc, "Forward!I2", u), "Forward!AH6": cell(svc, "EK_BULK!B5", u), "Forward!AH10": g / 100})
        assert cell(svc, "Forward!AH7", u) == days
        assert cell(svc, "EK_BULK!M5", u) == pytest.approx(cell(svc, "Forward!AH14", u) * 100, abs=1e-12)
        # Manuel TRY % typed: its ON (the other rows still RET mid's)
        put(svc, u, {"EK_BULK!B8": cell(svc, "Forward!I2", u) + 120, "EK_BULK!L8": "35,30", "EK_BULK!B9": cell(svc, "Forward!I2", u) + 120,
                     "EK_BULK!L9": "35,0135"})
        assert [cell(svc, "EK_BULK!C%d" % r, u) for r in (8, 9)] == [120.0, 120.0]
        assert [round(cell(svc, "EK_BULK!M%d" % r, u), 4) for r in (8, 9)] == [33.3884, 33.1317]
        assert cell(svc, "EK_BULK!M8", u) == pytest.approx(on_of(35.30, 120), abs=1e-12)
        assert cell(svc, "EK_BULK!M6", u) == pytest.approx(on_of(cell(svc, "EK_BULK!G6", u), cell(svc, "EK_BULK!C6", u)), abs=1e-12)
        # no valör, no ON; the page: two decimals, the value every digit
        assert cell(svc, "EK_BULK!M10", u) == ""
        _, m = panel(svc, u, "BK1")
        assert m["M8"]["t"] == "33,39" and m["M8"]["v"] == cell(svc, "EK_BULK!M8", u) and m["M4"]["t"] == "ON karşılık %"
        # a valör at the spot: Gün 0 - no ON (blank, not #DIV/0!), nor any ON or period column; an ON typed there stays
        put(svc, u, {"EK_BULK!B10": cell(svc, "Forward!I2", u)})
        assert cell(svc, "EK_BULK!C10", u) == 0.0 and cell(svc, "EK_BULK!N10", u) == cell(svc, "Forward!F2", u)
        assert [cell(svc, "EK_BULK!%s10" % c, u) for c in ["M", "AM", "AN", "AO"] + [x for x, _, _ in ex.BULK_ON_OF]] == [""] * 9
        put(svc, u, {"EK_BULK!M10": "33"})
        assert cell(svc, "EK_BULK!M10", u) == 33.0 and cell(svc, "EK_BULK!L10", u) == ""
        # (a valör before the spot: no period either - every Forward table's ON is blank there, extras.on_rate)
        put(svc, u, {"EK_BULK!B11": cell(svc, "Forward!I2", u) - 3})
        assert cell(svc, "EK_BULK!C11", u) == -3.0 and [cell(svc, "EK_BULK!%s11" % c, u) for c in ("M", "AM", "AQ", "AU")] == [""] * 4
    finally:
        svc.reset_inputs(u, "tto", ["Forward!AH5:AH10", "EK_BULK!B8:AP11"])


@pytest.mark.parametrize("kind", BULK)
def test_bulk_a_computed_value_typed_back_gives_the_same_row(svc, bulk_user, kind):
    """Round trips: one typed, each value it gives typed back as its own kind - the same row (1e-9), one value kept; the
    ON, the spread and both P/gün among them (worked out from any member and typed back, or typed and each value it gives
    typed back).  Through the ON the row is the same to 1e-11 relative: its exact inverse raises (1 + ON/360) to the
    row's days, so the last bits of a puan of 20 000-85 000 points (a few 1e-9 points, the outright's 1e-13) are the
    power's rounding (at most ~1e-12 relative up to 800 days); a puan by way of a P/gün and back to 1e-12 relative."""
    u = bulk_user
    r = 6
    g = cell(svc, "EK_BULK!G%d" % r, u)
    start = {"L": round(g + 0.77, 4), "I": 55.5, "M": round(on_of(g, cell(svc, "EK_BULK!C%d" % r, u)) - 0.66, 4),
             "N": round(bulk_from_rate(svc, u, r, g)["N"] + 0.31, 4), "O": 21000.0, "AO": 140.25,
             "P": round(bulk_from_rate(svc, u, r, g)["P"] - 0.2, 4), "Q": 26000.0, "AP": 160.75}[kind]
    try:
        put(svc, u, {"EK_BULK!%s%d" % (kind, r): start})
        want = bulk(svc, u, r)
        for col in BULK:
            put(svc, u, {"EK_BULK!%s%d" % (col, r): want[col]})
            tol = ({"rel": 1e-11, "abs": 1e-9} if "M" in (kind, col) else
                   {"rel": 1e-12, "abs": 1e-9} if {kind, col} & {"AO", "AP"} else {"abs": 1e-9})
            assert bulk(svc, u, r) == pytest.approx(want, **tol), (kind, col)
            assert typed_cols(svc, u) == {"%s%d" % (BULK_STORE[col], r)}
        put(svc, u, {"EK_BULK!%s%d" % (kind, r): ""})
        assert typed_cols(svc, u) == set()
    finally:
        svc.reset_inputs(u, "tto", ["EK_BULK!I%d:AP%d" % (r, r)])


def test_bulk_last_typed_wins_delete_and_a_pasted_column(svc, bulk_user):
    """Typing one clears the row's other typed value; Delete on the typed one or on a computed one takes the row back to
    RET mid; a column of USDTRY forwards (or of ON rates) pasted from Excel: each row's typed value.  The ON, the spread
    and the P/gün alike: typed over a Manuel TRY % or a fwd typed it stands, they typed over it stand; Delete on it, or on
    a member worked out from it, takes the row back to RET mid."""
    u = bulk_user
    put(svc, u, {"EK_BULK!L5": "40"})
    put(svc, u, {"EK_BULK!P5": 59.0})
    assert stored(svc, u, "EK_BULK").get("AB5") == 59.0 and "L5" not in stored(svc, u, "EK_BULK")
    put(svc, u, {"EK_BULK!N5": ""})                                                 # Delete on a computed member
    assert "AB5" not in stored(svc, u, "EK_BULK")
    assert bulk(svc, u, 5) == pytest.approx(bulk_from_rate(svc, u, 5, cell(svc, "EK_BULK!G5", u), ""), abs=1e-9)
    # the ON: over a Manuel TRY %, under a fwd typed, again over it; Delete on it and on the Manuel TRY % it gives
    days, g = cell(svc, "EK_BULK!C5", u), cell(svc, "EK_BULK!G5", u)
    put(svc, u, {"EK_BULK!L5": "40"})
    put(svc, u, {"EK_BULK!M5": "33"})
    assert typed_cols(svc, u) == {"AE5"}
    assert bulk(svc, u, 5) == pytest.approx(bulk_from_rate(svc, u, 5, rate_of_on(33.0, days)), abs=1e-9)
    fwd = round(bulk_from_rate(svc, u, 5, g)["N"] + 0.04, 4)
    put(svc, u, {"EK_BULK!N5": fwd})
    assert typed_cols(svc, u) == {"Z5"}
    assert cell(svc, "EK_BULK!M5", u) == pytest.approx(on_of(cell(svc, "EK_BULK!L5", u), days), abs=1e-12)
    put(svc, u, {"EK_BULK!M5": "33"})
    assert typed_cols(svc, u) == {"AE5"} and cell(svc, "EK_BULK!N5", u) != fwd
    put(svc, u, {"EK_BULK!M5": ""})                                                 # Delete on the ON typed
    assert typed_cols(svc, u) == set()
    assert bulk(svc, u, 5) == pytest.approx(bulk_from_rate(svc, u, 5, g, ""), abs=1e-9)
    put(svc, u, {"EK_BULK!M5": "33"})
    put(svc, u, {"EK_BULK!L5": ""})                                                 # Delete on the rate it gives
    assert typed_cols(svc, u) == set()
    assert bulk(svc, u, 5) == pytest.approx(bulk_from_rate(svc, u, 5, g, ""), abs=1e-9)
    # a spread, then a P/gün over it; Delete on the spread worked out from the P/gün
    put(svc, u, {"EK_BULK!I5": "35"})
    assert typed_cols(svc, u) == {"AF5"} and cell(svc, "EK_BULK!L5", u) == g + 35 / 100
    put(svc, u, {"EK_BULK!AO5": "100"})
    assert typed_cols(svc, u) == {"AG5"}
    assert cell(svc, "EK_BULK!I5", u) == pytest.approx((cell(svc, "EK_BULK!L5", u) - g) * 100, abs=1e-9)
    put(svc, u, {"EK_BULK!I5": ""})
    assert typed_cols(svc, u) == set()
    assert bulk(svc, u, 5) == pytest.approx(bulk_from_rate(svc, u, 5, g, ""), abs=1e-9)
    # a column of ON rates pasted
    res = svc.paste(u, "tto", "EK_BULK!M5", "33,1\n33,2\n33,3")
    assert res["errors"] == [] and res["applied"] == 3
    assert [cell(svc, "EK_BULK!M%d" % r, u) for r in (5, 6, 7)] == [33.1, 33.2, 33.3]
    assert [cell(svc, "EK_BULK!L%d" % r, u) for r in (5, 6, 7)] == pytest.approx(
        [rate_of_on(x, cell(svc, "EK_BULK!C%d" % r, u)) for r, x in zip((5, 6, 7), (33.1, 33.2, 33.3))], abs=1e-12)
    svc.reset_inputs(u, "tto", ["EK_BULK!M5:M7"])
    assert typed_cols(svc, u) == set()
    fwds = [round(bulk_from_rate(svc, u, r, 40.0)["N"], 4) for r in (5, 6, 7)]
    res = svc.paste(u, "tto", "EK_BULK!N5", "\n".join(("%.4f" % x).replace(".", ",") for x in fwds))
    assert res["errors"] == [] and res["applied"] == 3
    assert [cell(svc, "EK_BULK!N%d" % r, u) for r in (5, 6, 7)] == fwds
    assert [cell(svc, "EK_BULK!L%d" % r, u) for r in (5, 6, 7)] == pytest.approx([40.0] * 3, abs=1e-3)    # (4 decimals typed)
    assert svc.reset_inputs(u, "tto", ["EK_BULK!O6"])["reset"] == 1                  # "Kendi girdimi sil" on its puan
    assert "Z6" not in stored(svc, u, "EK_BULK") and "Z5" in stored(svc, u, "EK_BULK")
    svc.reset_inputs(u, "tto", ["EK_BULK!N5:N7"])
    assert typed_cols(svc, u) == set()


def test_bulk_the_general_spread_prices_the_rows_with_nothing_typed(svc):
    """Genel spread (bp) (the desk, 26.11.2026; ``EK_BULK!C2``, each user's own, in the table's title area on a cell no
    input ever stood on, its label beside it): a row with nothing typed is priced at RET mid + it - N / P and their puan /
    P/gün, the ON and every column off the row's rate (the hidden "Fiyatlayan TRY %"), the Spread column shows it; a row
    with a value typed keeps its own; blank: RET mid itself (G, not G + 0), every value as before, to the last bit."""
    u = svc.login("iy genel spread")["user"]
    book = svc.books["tto"]
    d = book.inputs[book.cell("EK_BULK!" + ex.BULK_SPREAD_ALL)]
    assert (d.scope, d.kind, d.group) == ("user", "number", "bulk100-spread-all")
    assert cell(svc, "EK_BULK!B2") == "Genel spread (bp)" and cell(svc, "EK_BULK!" + ex.BULK_SPREAD_ALL) is None
    try:
        put(svc, u, {"EK_BULK!B5": D1, "EK_BULK!B6": D2, "EK_BULK!L6": "41"})
        before = {r: bulk(svc, u, r) for r in (5, 6)}
        rest = {r: get(svc, u, *("EK_BULK!%s%d" % (c, r) for c in ("AI", "AL", "AM", "AN", "AQ", "AU"))) for r in (5, 6)}
        g = cell(svc, "EK_BULK!G5", u)
        assert cell(svc, "EK_BULK!AI5", u) == g and before[5] == pytest.approx(bulk_from_rate(svc, u, 5, g, ""), abs=1e-9)
        put(svc, u, {"EK_BULK!" + ex.BULK_SPREAD_ALL: "25"})
        assert cell(svc, "EK_BULK!AI5", u) == g + 25 / 100
        got = bulk(svc, u, 5)
        assert got == pytest.approx(bulk_from_rate(svc, u, 5, g + 25 / 100, ""), abs=1e-9) and got["L"] == ""
        assert got["I"] == pytest.approx(25.0, abs=1e-9) and cell(svc, "EK_BULK!AM5", u) == g + 25 / 100
        assert bulk(svc, u, 6) == before[6]                                         # (a Manuel TRY % typed: its own)
        put(svc, u, {"EK_BULK!" + ex.BULK_SPREAD_ALL: ""})
        assert {r: bulk(svc, u, r) for r in (5, 6)} == before
        assert {r: get(svc, u, *("EK_BULK!%s%d" % (c, r) for c in ("AI", "AL", "AM", "AN", "AQ", "AU"))) for r in (5, 6)} == rest
    finally:
        svc.reset_inputs(u, "tto")


def test_bulk_the_period_from_the_filled_row_above(svc):
    """Dönem TRY % / Dönem ON % (26.11.2026): the forward-forward rate from the nearest filled row above (its valör) to
    this row's - ((1 + r2·d2/360) / (1 + r1·d1/360) − 1)·360 / (d2 − d1), r the TRY rate that prices each row, d its Gün -
    and its ON over d2 − d1 days; the first filled row runs from the spot: its own rate (its ON its ON karşılık); an empty
    row between is passed over; blank where the dates do not increase and at Gün 0.  The last filled row's Gün and rate
    are carried down the hidden helper columns, one cell each per row (no lookup over the table)."""
    u = svc.login("iy dönem")["user"]
    try:
        spot = cell(svc, "Forward!I2", u)
        put(svc, u, {"EK_BULK!B5": spot + 70, "EK_BULK!B7": spot + 160, "EK_BULK!B8": spot + 130, "EK_BULK!B9": spot + 220,
                     "EK_BULK!L9": "38,5", "EK_BULK!B10": spot, "EK_BULK!B11": spot + 45})

        def at(c, r):
            return cell(svc, "EK_BULK!%s%d" % (c, r), u)

        def fwd_fwd(r1, d1, r2, d2):
            return ((1 + r2 / 100 * d2 / 360) / (1 + r1 / 100 * d1 / 360) - 1) * 360 / (d2 - d1) * 100

        assert at("AM", 5) == at("AI", 5) == at("G", 5) and at("AN", 5) == pytest.approx(at("M", 5), abs=1e-12)
        assert (at("AM", 6), at("AN", 6), at("AJ", 6), at("AK", 6)) == ("", "", 70.0, at("AI", 5))   # (an empty row: passed over)
        want = fwd_fwd(at("AI", 5), 70, at("AI", 7), 160)
        assert at("AM", 7) == pytest.approx(want, abs=1e-12) and at("AN", 7) == pytest.approx(on_of(want, 90), abs=1e-12)
        assert at("AM", 8) == "" and at("AN", 8) == ""                              # (130 days after 160: no period)
        want = fwd_fwd(at("AI", 8), 130, 38.5, 220)                                 # (from row 8, the nearest filled row)
        assert at("AI", 9) == 38.5 and at("AM", 9) == pytest.approx(want, abs=1e-12)
        assert at("AN", 9) == pytest.approx(on_of(want, 90), abs=1e-12)
        assert at("AM", 10) == "" and at("AJ", 10) == 0.0                          # (Gün 0: no period, but a filled row)
        assert at("AM", 11) == pytest.approx(at("AI", 11), abs=1e-12)              # (from the spot again)
        _, m = panel(svc, u, "BK1")
        assert re.match(r"^\d+,\d{2}$", m["AM7"]["t"]) and m["AM7"]["v"] == at("AM", 7)
    finally:
        svc.reset_inputs(u, "tto")


def test_bulk_the_on_of_every_rate_and_the_on_less_ret_on(svc, bulk_user):
    """ON · Offshore mid / OIS mid / RET bid / mid / ask %: each rate column's ON through the calculators' formula on 360
    over the row's Gün - OIS mid too, not TLREF's business-day one: the table shows these rates side by side as % rates,
    and MASA's own "O/N EŞLENİKLERİ · 360 bazında" compares OIS and offshore O/N on 360 as well; ON − RET ON (bp): the
    row's ON karşılık less today's RET ON mid (AVERAGE(Forward!W33:X33), decimals), in bp with one decimal."""
    u = bulk_user
    days = cell(svc, "EK_BULK!C5", u)
    for col, src, head in ex.BULK_ON_OF:
        assert cell(svc, "EK_BULK!%s4" % col) == head
        assert cell(svc, "EK_BULK!%s5" % col, u) == pytest.approx(on_of(cell(svc, "EK_BULK!%s5" % src, u), days), abs=1e-12)
    assert cell(svc, "EK_BULK!AT5", u) == cell(svc, "EK_BULK!M5", u)              # (nothing typed: RET mid's ON is the row's)
    ret_on = (cell(svc, "Forward!W33") + cell(svc, "Forward!X33")) / 2
    assert cell(svc, "EK_BULK!AL5", u) == pytest.approx((cell(svc, "EK_BULK!M5", u) - ret_on * 100) * 100, abs=1e-9)
    try:
        put(svc, u, {"EK_BULK!M5": "36,15"})
        assert cell(svc, "EK_BULK!AL5", u) == pytest.approx((36.15 - ret_on * 100) * 100, abs=1e-9)
        _, m = panel(svc, u, "BK1")
        assert re.match(r"^-?\d+,\d$", m["AL5"]["t"]) and re.match(r"^\d+,\d{2}$", m["AR5"]["t"])
    finally:
        svc.reset_inputs(u, "tto", ["EK_BULK!M5"])


def test_bulk_the_hidden_block_and_the_frozen_valor_and_gun(svc, bulk_user):
    """On the page: the hidden block (the stores and helpers, Z:AK) hidden as Excel hides a column - out of TOPLU
    FORWARD, shown in its helper table -, the new columns right of it in the desk's order, Valör and Gün frozen while the
    page scrolls right, the general spread's label and box in the title area; Spread (bp) in I."""
    p, m = panel(svc, bulk_user, "BK1")
    cols = p["data"]["c"]
    hidden = ["Z", "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK"]
    shown = ["AL", "AM", "AN", "AO", "AP", "AQ", "AR", "AS", "AT", "AU"]
    assert p["range"] == "B1:AU106" and cols[cols.index("Y") + 1:] == shown and not set(cols) & set(hidden)
    assert (p["data"]["fz"], p["data"]["hc"], cols[:2]) == (2, len(hidden), ["B", "C"])
    assert [m["%s4" % c]["t"] for c in shown] == ["ON − RET ON (bp)", "Dönem TRY %", "Dönem ON %", "USDTRY P/gün", "EURTRY P/gün",
                                                  "ON · Offshore mid %", "ON · OIS mid %", "ON · RET bid %", "ON · RET mid %",
                                                  "ON · RET ask %"]
    assert m["I4"]["t"] == "Spread (bp)" and m["B2"]["t"] == "Genel spread (bp)" and m["C2"]["i"] == "u"
    q, h = panel(svc, bulk_user, "BK2", helpers=True)
    assert q["data"]["c"] == hidden and [h["%s4" % c]["t"] for c in hidden[5:]] == [
        "Yazılan ON karşılık %", "Yazılan Spread (bp)", "Yazılan USDTRY P/gün", "Yazılan EURTRY P/gün", "Fiyatlayan TRY %",
        "Son dolu satırın Gün'ü", "Son dolu satırın TRY %'si"]


def test_bulk_books_each_row_at_the_price_it_shows(svc):
    """"İşleme al" with the row's typed value: a USDTRY fwd or puan typed - the USDTRY row books it as the outright
    (Forward kur = the row's USDTRY fwd); an EURTRY fwd or puan typed - the USDTRY row books the TRY rate it gives (the
    blotter's TRY-rate pricing is the row's own formula: the row's USDTRY fwd), the EURTRY row its EURTRY fwd.  Every
    booked forward is what the row shows (1e-9); the note says where the rate came from."""
    u = svc.login("iy toplu işlem")["user"]
    dates = {5: "15.01.2027", 6: "15.03.2027", 7: "15.06.2027", 8: "15.02.2027", 9: "14.05.2027", 10: "15.09.2027",
             11: "15.12.2027", 12: "15.07.2027"}
    cells = {"EK_BULK!B%d" % r: d for r, d in dates.items()}
    cells.update({"EK_BULK!W%d" % r: "AL" for r in dates})
    cells.update({"EK_BULK!X%d" % r: "1m" for r in dates})
    cells.update({"EK_BULK!V%d" % r: "EURTRY" for r in (9, 10, 11, 12)})
    put(svc, u, cells)
    g = {r: cell(svc, "EK_BULK!G%d" % r, u) for r in dates}
    usd_fwd = {r: round(bulk_from_rate(svc, u, r, g[r])["N"] + 0.0333, 4) for r in (5, 9)}
    eur_fwd = {r: round(bulk_from_rate(svc, u, r, g[r])["P"] + 0.0444, 4) for r in (7, 11)}
    put(svc, u, {"EK_BULK!N5": usd_fwd[5], "EK_BULK!O6": 15000, "EK_BULK!P7": eur_fwd[7], "EK_BULK!Q8": 18000,
                 "EK_BULK!N9": usd_fwd[9], "EK_BULK!O10": 15500, "EK_BULK!P11": eur_fwd[11], "EK_BULK!L12": "41,25"})
    src = svc.bulk_from_forward(u)
    assert src["taken"] == 8
    p = svc.bulk_preview(u, "fwd", src["text"])
    assert p["valid"] == 8, p
    by_row = {int(x["cells"][0]): x["trade"] for x in p["rows"]}
    want = {1: ("USDTRY", "FWD", "N", "USDTRY fwd"), 2: ("USDTRY", "FWD", "N", "USDTRY puan"),
            3: ("USDTRY", "TRY", "N", "EURTRY fwd"), 4: ("USDTRY", "TRY", "N", "EURTRY puan"),
            5: ("EURTRY", "FWD", "P", "USDTRY fwd"), 6: ("EURTRY", "FWD", "P", "USDTRY puan"),
            7: ("EURTRY", "FWD", "P", "EURTRY fwd"), 8: ("EURTRY", "FWD", "P", "Manuel TRY %")}
    for n, (pair, basis, col, source) in want.items():
        t = by_row[n]
        r = 4 + n
        assert (t["pair"], t["basis"], t["note"]) == (pair, basis, "TOPLU FORWARD · " + source), n
        assert t["forward"] == pytest.approx(cell(svc, "EK_BULK!%s%d" % (col, r), u), abs=1e-9), n
    # the forward typed is booked as it is, to the last digit; the puan's as spot + puan / 10000
    assert by_row[1]["forward"] == usd_fwd[5] and by_row[2]["forward"] == cell(svc, "Forward!F2", u) + 15000 / 10000
    assert by_row[7]["forward"] == eur_fwd[11]
    # an USDTRY row whose rate comes from an EURTRY forward: its TRY rate is the row's Manuel TRY % (worked out), the
    # forward the blotter prices from it the row's own USDTRY fwd - to the last bits (the same formula)
    assert by_row[3]["try_rate"] * 100 == pytest.approx(cell(svc, "EK_BULK!L7", u), abs=1e-12)
    assert abs(by_row[3]["forward"] - cell(svc, "EK_BULK!N7", u)) < 1e-12
    # the paste says so
    rows = {line.split("\t")[0]: line.split("\t") for line in src["text"].split("\n")[1:]}
    assert rows["1"][5:7] == ["", entry._plain(usd_fwd[5], "tr")] and rows["3"][5].endswith("%") and rows["3"][6] == ""
    assert "USDTRY fwd, puanı ya da P/gün'ü yazılmışsa o forward" in src["said"]
    svc.reset_inputs(u, "tto")


def test_bulk_values_typed_before_read_as_before(svc):
    """A Manuel TRY % typed before is the row's typed value, as it always was; a value an earlier version kept over a
    USDTRY fwd ("Elle değer" at N) is that row's typed fwd now (moved to its store once)."""
    u = svc.login("iy toplu eski")["user"]
    svc.store.set_user_inputs(u, "tto", {"EK_BULK!B5": 46402.0, "EK_BULK!L5": 41.25, "EK_BULK!B6": 46402.0, "EK_BULK!N6": 52.5})
    svc._reload_user(u)
    assert stored(svc, u, "EK_BULK") == {"B5": 46402.0, "L5": 41.25, "B6": 46402.0, "Z6": 52.5}
    assert bulk(svc, u, 5) == pytest.approx(bulk_from_rate(svc, u, 5, 41.25), abs=1e-9)
    days, _, usd, _, s_usd, _, _ = bulk_market(svc, u, 6)
    assert cell(svc, "EK_BULK!N6", u) == 52.5 and cell(svc, "EK_BULK!L6", u) == pytest.approx(implied(52.5, s_usd, usd, days), abs=1e-12)
    _, m = panel(svc, u, "BK1")
    assert m["N6"]["an"] == ("Manuel TRY %, Spread (bp), ON karşılık %, USDTRY puan, USDTRY P/gün, EURTRY fwd, EURTRY puan, "
                             "EURTRY P/gün") and m["L6"]["ao"] == "USDTRY fwd · N6"
    assert m["L5"]["an"] and m["L5"]["m"] == 1 and m["P5"]["ao"] == "Manuel TRY % · L5"
    assert m["M6"]["ao"] == m["I6"]["ao"] == m["AO6"]["ao"] == m["AP6"]["ao"] == "USDTRY fwd · N6"
    # an ON typed: marked, the others worked out from it; the hidden helper table shows it in its store
    put(svc, u, {"EK_BULK!M5": "33,5"})
    _, m = panel(svc, u, "BK1")
    assert m["M5"]["an"] == ("Manuel TRY %, Spread (bp), USDTRY fwd, USDTRY puan, USDTRY P/gün, EURTRY fwd, EURTRY puan, "
                             "EURTRY P/gün")
    assert m["L5"]["ao"] == m["N5"]["ao"] == "ON karşılık % · M5"
    _, h = panel(svc, u, "BK2", helpers=True)
    assert h["AE4"]["t"] == "Yazılan ON karşılık %" and h["AE5"]["v"] == 33.5
    assert h["AD5"]["v"] == pytest.approx(cell(svc, "EK_BULK!L5", u), abs=1e-15) and h["AI5"]["v"] == h["AD5"]["v"]
    svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- the value-date tables
USD, EUR = ex.FR_USD, ex.FR_EUR
SIDE = (("B", "E", "H", "K", "L"), ("D", "G", "J", "M", "H"))            # TRY %, fwd, puan, P/gün; the major's column


def fr(svc, user, r, side):
    return get(svc, user, *("EK_FWD!%s%d" % (c, r) for c in SIDE[side][:4]))


def fr_market(svc, user, t, side):
    """(days, spot, the major's rate this side uses) of the table whose title is in row ``t``."""
    i = t + 1
    return get(svc, user, "EK_FWD!D%d" % i, "EK_FWD!F%d" % i, "EK_FWD!%s%d" % (SIDE[side][4], i))


def fr_from_rate(svc, user, t, side, rate):
    days, spot, major = fr_market(svc, user, t, side)
    fwd = spot * (1 + rate / 100 / 360 * days) / (1 + major / 100 / 360 * days)
    return [rate, fwd, (fwd - spot) * 10000, (fwd - spot) * 10000 / days]


@pytest.mark.parametrize("t", [USD, EUR], ids=["USDTRY", "EURTRY"])
def test_the_value_date_tables_each_member_typed_gives_the_others(svc, t):
    """Per row and side: a TRY %, an outright, points or points per day typed - that one exactly, the other three from
    it (the sheet's formula: bid with the major's ask, ask with its bid; points ÷ days); the mids from both sides."""
    u = svc.login("iy valör %d" % t)["user"]
    for k in (0, 3, 4):                                                             # Offshore, RET, Elle
        r = t + 3 + k
        for side in (0, 1):
            days, spot, major = fr_market(svc, u, t, side)
            rate = round(fr(svc, u, r, side)[0] + 0.5 - side, 3)
            put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][0], r): rate})
            assert fr(svc, u, r, side) == pytest.approx(fr_from_rate(svc, u, t, side, rate), abs=1e-9)
            fwd = round(fr(svc, u, r, side)[1] + 0.0123, 4)
            put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][1], r): fwd})
            got = fr(svc, u, r, side)
            assert got[1] == fwd and got == pytest.approx(fr_from_rate(svc, u, t, side, implied(fwd, spot, major, days)), abs=1e-9)
            put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][2], r): 20000})
            got = fr(svc, u, r, side)
            assert got[2] == 20000.0 and got[1] == spot + 2 and got[3] == 20000 / days
            assert got == pytest.approx(fr_from_rate(svc, u, t, side, implied(spot + 2, spot, major, days)), abs=1e-9)
            put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][3], r): 250})
            got = fr(svc, u, r, side)
            assert got[3] == 250.0 and got[2] == 250 * days and got[1] == spot + 250 * days / 10000
            assert got == pytest.approx(fr_from_rate(svc, u, t, side, implied(spot + 250 * days / 10000, spot, major, days)), abs=1e-9)
        bid, ask = fr(svc, u, r, 0), fr(svc, u, r, 1)
        mids = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "CFIL"))
        assert mids == pytest.approx([(bid[0] + ask[0]) / 2, (bid[1] + ask[1]) / 2, (bid[2] + ask[2]) / 2, (bid[2] + ask[2]) / 2 / days],
                                     abs=1e-9)
    svc.reset_inputs(u, "tto")


@pytest.mark.parametrize("side", [0, 1], ids=["bid", "ask"])
def test_the_value_date_tables_round_trips(svc, side):
    """Each kind typed, each value it gives typed back as its own kind: the same row-side (1e-9), one value kept."""
    u = svc.login("iy valör gidiş dönüş %d" % side)["user"]
    r = USD + 3 + 1                                                                   # OIS
    days, spot, _ = fr_market(svc, u, USD, side)
    for k, start in enumerate((round(fr(svc, u, r, side)[0] - 0.4, 3), round(spot + 1.7, 4), 17500.0, 190.5)):
        put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][k], r): start})
        want = fr(svc, u, r, side)
        for j in range(4):
            put(svc, u, {"EK_FWD!%s%d" % (SIDE[side][j], r): want[j]})
            assert fr(svc, u, r, side) == pytest.approx(want, abs=1e-9), (k, j)
            assert len(stored(svc, u, "EK_FWD")) == 1
        svc.reset_inputs(u, "tto")


def test_the_eurtry_table_follows_the_usdtry_ones_rates_and_a_value_date_changed(svc):
    """The EURTRY table's TRY rates are the USDTRY table's - a USDTRY forward typed moves them (its EURTRY forwards with
    them) - unless one is typed in the EURTRY table itself.  The value date changed: a value typed stays as typed, the
    others are worked out on the new days; Delete: back to the curve."""
    u = svc.login("iy valör tarih")["user"]
    r, re_ = USD + 3 + 3, EUR + 3 + 3                                                # RET
    curve = cell(svc, "EK_FWD!B%d" % r, u)
    days, spot, major = fr_market(svc, u, USD, 0)
    fwd = round(fr(svc, u, r, 0)[1] + 0.25, 4)
    put(svc, u, {"EK_FWD!E%d" % r: fwd})
    rate = implied(fwd, spot, major, days)
    assert cell(svc, "EK_FWD!B%d" % re_, u) == pytest.approx(rate, abs=1e-12)
    assert fr(svc, u, re_, 0) == pytest.approx(fr_from_rate(svc, u, EUR, 0, rate), abs=1e-9)
    put(svc, u, {"EK_FWD!H%d" % re_: 33000})                                        # the EURTRY table's own
    assert cell(svc, "EK_FWD!H%d" % re_, u) == 33000.0 and cell(svc, "EK_FWD!B%d" % r, u) == pytest.approx(rate, abs=1e-12)
    put(svc, u, {"EK_FWD!H%d" % re_: ""})
    # the value date moved a month on: the forward typed stays, its rate is the new period's
    d2 = cell(svc, "Forward!D2", u)
    put(svc, u, {"Forward!D2": d2 + 31})
    days2, spot2, major2 = fr_market(svc, u, USD, 0)
    assert days2 != days and cell(svc, "EK_FWD!E%d" % r, u) == fwd
    assert fr(svc, u, r, 0) == pytest.approx(fr_from_rate(svc, u, USD, 0, implied(fwd, spot2, major2, days2)), abs=1e-9)
    assert stored(svc, u, "EK_FWD") == {"N%d" % r: fwd}
    put(svc, u, {"EK_FWD!K%d" % r: ""})                                              # Delete (on its P/gün)
    assert cell(svc, "EK_FWD!B%d" % r, u) != curve and cell(svc, "EK_FWD!B%d" % r, u) == pytest.approx(
        cell(svc, "Forward!W48", u) * 100, rel=1e-15)
    svc.reset_inputs(u, "tto", ["Forward!D2"])                                       # the value date back
    assert cell(svc, "EK_FWD!B%d" % r, u) == curve and stored(svc, u, "EK_FWD") == {}


def test_the_value_date_tables_marks_and_values_typed_before(svc):
    """The page marks the typed value (✎) and says the others come from it, the note under both tables; a TRY rate typed
    before reads as before; an "Elle değer" an earlier version kept over an outright is that side's typed value now."""
    u = svc.login("iy valör eski")["user"]
    svc.store.set_user_inputs(u, "tto", {"EK_FWD!B48": 41.0, "EK_FWD!G49": 49.75})
    svc._reload_user(u)
    assert stored(svc, u, "EK_FWD") == {"B48": 41.0, "Q49": 49.75}
    assert fr(svc, u, 48, 0) == pytest.approx(fr_from_rate(svc, u, USD, 0, 41.0), abs=1e-9)
    days, spot, major = fr_market(svc, u, USD, 1)
    assert fr(svc, u, 49, 1) == pytest.approx(fr_from_rate(svc, u, USD, 1, implied(49.75, spot, major, days)), abs=1e-9)
    p, m = panel(svc, u, "FR1")
    assert p["note"].count("İki yönlü: her satırın bid'inde ve ask'inde TRY %, ON karşılık, forward, puan ya da P/gün - hangisini yazarsanız "
                           "o kalır, diğerleri ondan hesaplanır") == 1
    assert m["B48"]["an"] == "USDTRY bid, Puan bid, P/gün bid, ON bid %" and m["E48"]["ao"] == "TRY bid % · B48"
    assert m["G49"]["an"] == "TRY ask %, Puan ask, P/gün ask, ON ask %" and m["D49"]["ao"] == "USDTRY ask · G49" and m["M49"]["i"] == "u"
    assert not any(k in m["E49"] for k in ("an", "ao", "m"))                        # (the bid side of that row: nothing typed)
    p2, m2 = panel(svc, u, "FR2")
    assert "İki yönlü" in p2["note"] and "an" not in m2["B59"] and m2["B59"]["i"] == "u"


# ---------------------------------------------------------------------------------------------- SERBEST FORWARD
def test_the_free_forward_list(svc):
    """Minor %, swap or forward typed: the one typed stands, the others on the row's own spot at the start, major % and
    days; round trips; Delete: the curve's minor % again."""
    u = svc.login("iy serbest")["user"]
    h = ex.FR_LIST + 2
    r = h + 1
    put(svc, u, {"EK_FWD!C%d" % r: cell(svc, "Forward!D2")})
    spot, major, days, minor = get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "EFDG"))

    def row():
        return get(svc, u, *("EK_FWD!%s%d" % (c, r) for c in "GHI"))

    def off(rate):
        fwd = spot * (1 + rate / 100 * days / 360) / (1 + major / 100 * days / 360)
        return [rate, (fwd - spot) * 10000, fwd]

    assert row() == pytest.approx(off(minor), abs=1e-9)
    put(svc, u, {"EK_FWD!I%d" % r: round(off(minor)[2] + 0.11, 4)})
    fwd = round(off(minor)[2] + 0.11, 4)
    assert row()[2] == fwd and row() == pytest.approx(off(implied(fwd, spot, major, days)), abs=1e-9)
    put(svc, u, {"EK_FWD!H%d" % r: 30000})
    assert row()[1] == 30000.0 and row()[2] == spot + 3 and row() == pytest.approx(off(implied(spot + 3, spot, major, days)), abs=1e-9)
    want = row()
    for k, col in enumerate("GHI"):
        put(svc, u, {"EK_FWD!%s%d" % (col, r): want[k]})
        assert row() == pytest.approx(want, abs=1e-9), col
    assert stored(svc, u, "EK_FWD") == {"C%d" % r: cell(svc, "Forward!D2"), "AA%d" % r: want[2]}
    put(svc, u, {"EK_FWD!H%d" % r: ""})
    assert row() == pytest.approx(off(minor), abs=1e-9) and stored(svc, u, "EK_FWD") == {"C%d" % r: cell(svc, "Forward!D2")}
    _, m = panel(svc, u, "FR3")
    assert m["G%d" % r]["i"] == "u" and m["H%d" % r]["i"] == "u" and m["I%d" % r]["i"] == "u"
    svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- FORWARD STARTING SWAP
FSS = ("C169", "D179", "H179", "I179", "J179", "N179", "O179")


def fss(svc, user):
    return get(svc, user, *("Forward!" + a for a in FSS))


def fss_from_rate(svc, user, x):
    """The Manuel row off a TRY fwd-fwd % ``x``, worked out here: the near leg RET mid, the USD / EUR fwd-fwd % (C170 /
    C171 or the curve's), USDTRY over the period from the USDTRY spot dates, EURTRY over its own (Δ)."""
    c177, f177, g177, k177, l177, f167, g167, h167, f168, g168, c170, c171 = get(
        svc, user, *("Forward!" + a for a in ("C177", "F177", "G177", "K177", "L177", "F167", "G167", "H167", "F168", "G168",
                                               "C170", "C171")))
    usd = c170 if isinstance(c170, float) else f177
    eur = c171 if isinstance(c171, float) else k177
    delta = max(0, g168 - f168)
    far = g177 * (1 + x / 100 * h167 / 360) / (1 + usd / 100 * h167 / 360)
    d = ((1 + c177 / 100 * f167 / 360) * (1 + x / 100 * h167 / 360) - 1) * 360 / g167 * 100
    n = l177 * (1 + x / 100 * delta / 360) / (1 + eur / 100 * delta / 360)
    return [x, d, far, (far - g177) * 10000, (far - g177) * 10000 / h167, n, (n - l177) * 10000]


def fss_back(svc, user, what, v):
    """The TRY fwd-fwd % a far TRY %, far outright or EURTRY far gives, worked out here."""
    c177, f177, g177, k177, l177, f167, g167, h167, f168, g168, c170, c171 = get(
        svc, user, *("Forward!" + a for a in ("C177", "F177", "G177", "K177", "L177", "F167", "G167", "H167", "F168", "G168",
                                               "C170", "C171")))
    if what == "D":
        return ((1 + v / 100 * g167 / 360) / (1 + c177 / 100 * f167 / 360) - 1) * 360 / h167 * 100
    if what == "H":
        return implied(v, g177, c170 if isinstance(c170, float) else f177, h167)
    return implied(v, l177, c171 if isinstance(c171, float) else k177, max(0, g168 - f168))


_FSS_USERS = iter(range(1000))


@pytest.fixture()
def fss_user(svc):
    u = svc.login("iy fss %d" % next(_FSS_USERS))["user"]
    put(svc, u, {"Forward!C167": "08.12.2026", "Forward!C168": "08.03.2027"})
    assert cell(svc, "Forward!F169", u) == "OK"
    yield u
    svc.reset_inputs(u, "tto")


def test_fss_each_member_typed_gives_the_others(svc, fss_user):
    """The TRY fwd-fwd %, the far TRY %, the USDTRY far outright, FS points or points per day, the EURTRY far or points
    typed: that one exactly, the others from the TRY fwd-fwd % it gives - which prices both legs; the row shows once a
    value is typed in it (its rate is a number), as it did with a rate typed in C169."""
    u = fss_user
    assert fss(svc, u) == [""] * 7 and cell(svc, "Forward!E179", u) == ""                # nothing typed: no Manuel row
    put(svc, u, {"Forward!C169": "40,5"})
    assert fss(svc, u) == pytest.approx(fss_from_rate(svc, u, 40.5), abs=1e-9)
    want = fss_from_rate(svc, u, 40.5)
    for ref, v, what in (("D179", round(want[1] + 0.3, 4), "D"), ("H179", round(want[2] + 0.05, 4), "H"),
                         ("N179", round(want[5] - 0.07, 4), "N")):
        put(svc, u, {"Forward!" + ref: v})
        got = fss(svc, u)
        assert got[FSS.index(ref)] == v and got == pytest.approx(fss_from_rate(svc, u, fss_back(svc, u, what, v)), abs=1e-9), ref
        assert cell(svc, "Forward!E179", u) == pytest.approx(got[0], abs=0)
    g177, l177, h167 = get(svc, u, "Forward!G177", "Forward!L177", "Forward!H167")
    put(svc, u, {"Forward!I179": 4321.5})
    got = fss(svc, u)
    assert got[3] == 4321.5 and got[2] == g177 + 0.43215 and got == pytest.approx(fss_from_rate(svc, u, fss_back(svc, u, "H", g177 + 0.43215)), abs=1e-9)
    put(svc, u, {"Forward!J179": 48.5})
    got = fss(svc, u)
    assert got[4] == 48.5 and got[3] == 48.5 * h167
    assert got == pytest.approx(fss_from_rate(svc, u, fss_back(svc, u, "H", g177 + 48.5 * h167 / 10000)), abs=1e-9)
    put(svc, u, {"Forward!O179": 5000})
    got = fss(svc, u)
    assert got[6] == 5000.0 and got[5] == l177 + 0.5 and got == pytest.approx(fss_from_rate(svc, u, fss_back(svc, u, "N", l177 + 0.5)), abs=1e-9)
    # the USD fwd-fwd % typed (C170): a far outright typed stays, its rate is worked out on it
    put(svc, u, {"Forward!H179": round(want[2], 4), "Forward!C170": "4,1"})
    assert fss(svc, u) == pytest.approx(fss_from_rate(svc, u, fss_back(svc, u, "H", round(want[2], 4))), abs=1e-9)
    # the points typed back (the "Elle puan → faiz" row) read the rate the row shows
    put(svc, u, {"Forward!I181": cell(svc, "Forward!I179", u)})
    assert cell(svc, "Forward!E181", u) == pytest.approx(cell(svc, "Forward!C169", u), abs=1e-9)


@pytest.mark.parametrize("ref", FSS)
def test_fss_a_computed_value_typed_back_gives_the_same_row(svc, fss_user, ref):
    """Round trips on the Manuel row: each value typed back as its own kind - the same row (1e-9), one value kept."""
    u = fss_user
    g177, l177 = get(svc, u, "Forward!G177", "Forward!L177")
    put(svc, u, {"Forward!" + ref: dict(zip(FSS, (39.75, 41.0, round(g177 + 3.1, 4), 25000.0, 300.0, round(l177 + 3.6, 4), 30000.0)))[ref]})
    want = fss(svc, u)
    assert all(isinstance(x, float) for x in want), want
    for k, other in enumerate(FSS):
        put(svc, u, {"Forward!" + other: want[k]})
        assert fss(svc, u) == pytest.approx(want, abs=1e-9), (ref, other)
        assert [k2 for k2 in stored(svc, u, "Forward") if k2 not in ("C167", "C168")] == \
            ["C169" if other == "C169" else ex.FS_TW_STORES[ex.FS_TW_MEMBERS.index(other[0])] + "179"]


def test_fss_no_period_no_rate_delete_and_the_elle_rows_stay(svc, fss_user):
    """Without a valid near / far (Durum not OK) the row stays empty but for the value typed; EURTRY's far typed with no
    EURTRY period (both dates before its spot) gives no rate; Delete on any of the row: back to nothing; the "Elle puan →
    faiz" rows are not the row's values."""
    u = fss_user
    put(svc, u, {"Forward!H179": 47.5})
    put(svc, u, {"Forward!C168": "01.12.2026"})                                      # far before near
    assert cell(svc, "Forward!F169", u) != "OK"
    assert fss(svc, u) == ["", "", 47.5, "", "", "", ""]
    put(svc, u, {"Forward!C168": "08.03.2027", "Forward!I181": 5000})
    assert isinstance(cell(svc, "Forward!C169", u), float) and isinstance(cell(svc, "Forward!E181", u), float)
    put(svc, u, {"Forward!D179": ""})                                                # Delete on a computed one
    assert fss(svc, u) == [""] * 7 and stored(svc, u, "Forward") == {"C167": cell(svc, "Forward!C167", u),
                                                                     "C168": cell(svc, "Forward!C168", u), "I181": 5000.0}
    k2 = cell(svc, "Forward!K2", u)
    put(svc, u, {"Forward!C167": k2 - 1, "Forward!C168": k2, "Forward!N179": 50.0})   # EURTRY: no period of its own
    assert cell(svc, "Forward!F169", u) == "OK" and cell(svc, "Forward!N179", u) == 50.0
    assert cell(svc, "Forward!C169", u) == "" and str(cell(svc, "Forward!AA179", u)) == "#N/A"


def test_fss_in_a_temporary_copy(svc, fss_user):
    """FORWARD STARTING SWAP is a copyable calculator: a value typed in its copy is the copy's Manuel row (its store the
    copy's own), the table stays; with a rate typed in the table itself (C169, in place) another value of the row typed
    in the copy is refused, saying why."""
    u = fss_user
    cid = svc.copy_action(u, "open", {"view": "forward", "panel": "B34"})["copy"]["id"]
    res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "Forward!H179", "value": "47,25"}]})
    assert res["errors"] == []
    assert fss(svc, u) == [""] * 7                                                   # the table's own: nothing typed
    pane = next(p for p in svc.view(u, "forward")["panels"] if (p.get("copy") or {}).get("id") == cid)
    d = pane["data"]
    cells = {"%s%d" % (c, r): x for r, line in zip(d["r"], d["rows"]) for c, x in zip(d["c"], line)}
    assert cells["H179"].get("v") == 47.25 and cells["H179"]["an"] and isinstance(cells["C169"].get("v"), float)
    assert isinstance(cells["I179"].get("v"), float) and cells["I179"]["ao"] == "Far outright · H179"
    put(svc, u, {"Forward!C169": "40"})
    res = svc.copy_action(u, "inputs", {"copy": cid, "items": [{"ref": "Forward!I179", "value": "100"}]})
    assert len(res["errors"]) == 1 and "kopyada yazılamaz" in res["errors"][0] and "Forward!C169" in res["errors"][0]
    svc.copy_action(u, "close", {"copy": cid})


# ---------------------------------------------------------------------------------------------- ÇAPRAZ FORWARD
def cross(svc, user, r):
    return get(svc, user, "Forward!F%d" % r, "Forward!Q%d" % r)


def cross_from_rate(svc, user, r, rate):
    b, c, g, h, k2, s_usd, s_eur = get(svc, user, *("Forward!%s" % a for a in ("B%d" % r, "C%d" % r, "G%d" % r, "H%d" % r, "K2", "F2", "G2")))
    if cross_ccy(svc, user) == "EUR":
        return [rate, s_eur * (1 + rate / 100 * (b - k2) / 360) / (1 + h / 100 * (b - k2) / 360)]
    return [rate, s_usd * (1 + rate / 100 * c / 360) / (1 + g / 100 * c / 360)]


def cross_ccy(svc, user):
    return ex.cross_currency(cell(svc, "Forward!C197", user))


def test_cross_each_member_typed_and_round_trips(svc):
    """Manuel TRY % or the manual forward typed: the other from it (USD on its OIS % and days, EUR on its own from the
    EURTRY spot date); each typed back gives the same row."""
    u = svc.login("iy çapraz")["user"]
    r1 = ex.CROSS_ROWS[0]
    for ccy in ("USD", "EUR"):
        put(svc, u, {"Forward!C197": ccy})
        for r in (r1, r1 + 3, r1 + 7):
            if r > r1 + 5:
                put(svc, u, {"Forward!B%d" % r: "15.10.2027"})
            put(svc, u, {"Forward!F%d" % r: "41,5"})
            assert cross(svc, u, r) == pytest.approx(cross_from_rate(svc, u, r, 41.5), abs=1e-9)
            fwd = round(cross(svc, u, r)[1] + 0.0789, 4)
            put(svc, u, {"Forward!Q%d" % r: fwd})
            got = cross(svc, u, r)
            assert got[1] == fwd and cell(svc, "Forward!V%d" % r, u) == got[0]
            assert got[0] == pytest.approx(implied_cross(svc, u, r, fwd), abs=1e-12)
            assert got == pytest.approx(cross_from_rate(svc, u, r, got[0]), abs=1e-9)
            for k, ref in enumerate(("F", "Q")):
                put(svc, u, {"Forward!%s%d" % (ref, r): got[k]})
                assert cross(svc, u, r) == pytest.approx(got, abs=1e-9), (ccy, r, ref)
            put(svc, u, {"Forward!R%d" % r: fwd})                                   # the "elle" column: the same rate
            assert cell(svc, "Forward!S%d" % r, u) == pytest.approx(implied_cross(svc, u, r, fwd), abs=1e-12)
        svc.reset_inputs(u, "tto", ["Forward!F%d:F%d" % ex.CROSS_ROWS, "Forward!R%d:R%d" % ex.CROSS_ROWS])
    svc.reset_inputs(u, "tto")


def implied_cross(svc, user, r, fwd):
    b, c, g, h, k2, s_usd, s_eur = get(svc, user, *("Forward!%s" % a for a in ("B%d" % r, "C%d" % r, "G%d" % r, "H%d" % r, "K2", "F2", "G2")))
    if cross_ccy(svc, user) == "EUR":
        return implied(fwd, s_eur, h, b - k2)
    return implied(fwd, s_usd, g, c)


def test_cross_a_forward_typed_goes_when_the_currency_changes(svc):
    """A forward typed is a forward of the currency it was typed in: the currency changed (typed, Delete, back to the
    file's), the forwards typed go - their rows back to the Manuel TRY % typed, if any, else nothing; a Manuel TRY % typed
    stays (a TRY rate is one in any currency); the same currency typed again (another spelling) changes nothing; a
    forward typed in the same write as the currency stays."""
    u = svc.login("iy çapraz döviz")["user"]
    r1 = ex.CROSS_ROWS[0]
    put(svc, u, {"Forward!C197": "USD", "Forward!F%d" % (r1 + 1): "40"})
    put(svc, u, {"Forward!Q%d" % r1: 44.5, "Forward!Q%d" % (r1 + 2): 46.0})
    assert stored(svc, u, "Forward") == {"C197": "USD", "F%d" % (r1 + 1): 40.0, "U%d" % r1: 44.5, "U%d" % (r1 + 2): 46.0}
    res = put(svc, u, {"Forward!C197": " usd "})                                    # the same currency
    assert res["applied"] == 1 and {"U%d" % r1, "U%d" % (r1 + 2)} <= set(stored(svc, u, "Forward"))
    res = put(svc, u, {"Forward!C197": "EUR"})
    assert res["applied"] == 1
    assert stored(svc, u, "Forward") == {"C197": "EUR", "F%d" % (r1 + 1): 40.0}
    assert cross(svc, u, r1) == ["", ""] and cross(svc, u, r1 + 1) == pytest.approx(cross_from_rate(svc, u, r1 + 1, 40.0), abs=1e-9)
    put(svc, u, {"Forward!C197": "USD", "Forward!Q%d" % r1: 45.25})                 # typed with the currency: it stays
    assert stored(svc, u, "Forward")["U%d" % r1] == 45.25 and cross_ccy(svc, u) == "USD"
    put(svc, u, {"Forward!C197": ""})                                                # Delete: blank is USD - no change
    assert stored(svc, u, "Forward")["U%d" % r1] == 45.25
    assert svc.reset_inputs(u, "tto", ["Forward!C197"])["reset"] == 1                 # back to the file's (CHF)
    assert cross_ccy(svc, u) == ex.cross_currency(cell(svc, "Forward!C197")) != "USD"
    assert stored(svc, u, "Forward") == {"F%d" % (r1 + 1): 40.0}
    svc.reset_inputs(u, "tto")


def test_cross_marks_and_a_rolling_date(svc):
    """The page marks the typed value; the preset rows' dates roll with the spot (formulas): a forward typed stays as
    typed on its row, its rate is worked out on the row's date of the day."""
    u = svc.login("iy çapraz işaret")["user"]
    r1 = ex.CROSS_ROWS[0]
    put(svc, u, {"Forward!C197": "USD"})
    put(svc, u, {"Forward!Q%d" % r1: 44.0})
    p, m = panel(svc, u, "B36")
    assert m["Q%d" % r1]["an"] == "Manuel TRY %, Manuel ON %" and m["F%d" % r1]["ao"] == "Fwd (manuel) · Q%d" % r1
    assert "Yazılan forward yazıldığı dövizindir" in p["note"]
    put(svc, u, {"Forward!B%d" % r1: cell(svc, "Forward!B%d" % r1, u) + 1})         # the date a day later
    assert cell(svc, "Forward!Q%d" % r1, u) == 44.0
    assert cell(svc, "Forward!F%d" % r1, u) == pytest.approx(implied_cross(svc, u, r1, 44.0), abs=1e-12)
    svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- all of them
def test_columns_pasted_delete_and_values_typed_before_in_the_other_tables(svc):
    """A column pasted from Excel into a member: each row's typed value (the value-date table's bid points, the free list's
    forwards, ÇAPRAZ's manual forwards); Delete on a worked-out cell takes its row back; values an earlier version kept
    over a member ("Elle değer" over FSS's far outright, ÇAPRAZ's manual forward, the free list's forward) are their rows'
    typed values now."""
    u = svc.login("iy yapıştır")["user"]
    r1 = ex.CROSS_ROWS[0]
    h = ex.FR_LIST + 2
    put(svc, u, {"Forward!C197": "USD", "EK_FWD!C%d" % (h + 1): cell(svc, "Forward!D2"), "EK_FWD!C%d" % (h + 2): cell(svc, "Forward!D2") + 60})
    res = svc.paste(u, "tto", "EK_FWD!H47", "\n".join(str(15000 + 500 * k) for k in range(5)))
    assert res["errors"] == [] and res["applied"] == 5
    assert [cell(svc, "EK_FWD!H%d" % r, u) for r in range(47, 52)] == [15000.0 + 500 * k for k in range(5)]
    days, spot, major = fr_market(svc, u, USD, 0)
    assert [cell(svc, "EK_FWD!B%d" % r, u) for r in range(47, 52)] == pytest.approx(
        [implied(spot + (15000 + 500 * k) / 10000, spot, major, days) for k in range(5)], abs=1e-9)
    svc.paste(u, "tto", "EK_FWD!I%d" % (h + 1), "45,5\n46,25")
    assert [cell(svc, "EK_FWD!I%d" % r, u) for r in (h + 1, h + 2)] == [45.5, 46.25]
    svc.paste(u, "tto", "Forward!Q%d" % r1, "44,1\n44,2\n44,3")
    assert [cell(svc, "Forward!Q%d" % r, u) for r in range(r1, r1 + 3)] == [44.1, 44.2, 44.3]
    assert [cell(svc, "Forward!F%d" % r, u) for r in range(r1, r1 + 3)] == pytest.approx(
        [implied_cross(svc, u, r, x) for r, x in zip(range(r1, r1 + 3), (44.1, 44.2, 44.3))], abs=1e-12)
    # Delete on a worked-out cell: its row only, back to its default
    put(svc, u, {"EK_FWD!B48": "", "EK_FWD!G%d" % (h + 2): "", "Forward!F%d" % (r1 + 1): ""})
    kept = stored(svc, u, "EK_FWD")
    assert "O48" not in kept and {"O47", "O49", "O50", "O51", "AA%d" % (h + 1)} <= set(kept) and "AA%d" % (h + 2) not in kept
    assert cell(svc, "Forward!Q%d" % (r1 + 1), u) == "" and cell(svc, "Forward!Q%d" % r1, u) == 44.1
    svc.reset_inputs(u, "tto")
    # values kept over the members before they were two-way
    svc.store.set_user_inputs(u, "tto", {"Forward!C167": 46364.0, "Forward!C168": 46454.0, "Forward!H179": 47.5,
                                         "Forward!C197": "USD", "Forward!Q%d" % r1: 44.75, "EK_FWD!C%d" % (h + 1): 46545.0,
                                         "EK_FWD!I%d" % (h + 1): 45.25})
    svc._reload_user(u)
    assert stored(svc, u, "Forward") == {"C167": 46364.0, "C168": 46454.0, "V179": 47.5, "C197": "USD", "U%d" % r1: 44.75}
    assert stored(svc, u, "EK_FWD") == {"C%d" % (h + 1): 46545.0, "AA%d" % (h + 1): 45.25}
    assert cell(svc, "Forward!H179", u) == 47.5 and cell(svc, "Forward!C169", u) == pytest.approx(fss_back(svc, u, "H", 47.5), abs=1e-12)
    assert cell(svc, "Forward!Q%d" % r1, u) == 44.75 and isinstance(cell(svc, "Forward!F%d" % r1, u), float)
    assert cell(svc, "EK_FWD!I%d" % (h + 1), u) == 45.25 and isinstance(cell(svc, "EK_FWD!G%d" % (h + 1), u), float)
    svc.reset_inputs(u, "tto")


def test_a_scenario_and_the_notes_under_the_tables(svc):
    """Senaryolar: saved with the typed values of every table, loaded back as they were; each table says how it works."""
    u = svc.login("iy senaryo")["user"]
    put(svc, u, {"EK_BULK!B5": D1, "Forward!C167": "08.12.2026", "Forward!C168": "08.03.2027", "Forward!C197": "USD"})
    g177 = cell(svc, "Forward!G177", u)
    put(svc, u, {"EK_BULK!O5": 14000, "EK_FWD!J48": 21000, "Forward!H179": round(g177 + 3.2, 4), "Forward!Q200": 44.0})
    refs = ["EK_BULK!L5", "EK_BULK!P5", "EK_FWD!D48", "Forward!C169", "Forward!N179", "Forward!F200"]
    want = [cell(svc, x, u) for x in refs]
    assert all(isinstance(x, float) for x in want), want
    svc.save_scenario(u, "iki yönlü forward")
    svc.reset_inputs(u, "tto")
    assert cell(svc, "Forward!C169", u) == ""
    svc.load_scenario(u, "iki yönlü forward")
    assert [cell(svc, x, u) for x in refs] == want
    page = {p["id"]: p for p in svc.view(u, "forward")["panels"]}
    for pid in ("BK1", "FR1", "FR2", "FR3", "B34", "B36"):
        assert "hangisini yazarsanız o kalır, diğer" in page[pid]["note"], pid
    assert "tek TRY faiziyle" in page["BK1"]["note"] and "Valör tarihi değişince yazılan değer kalır" in page["FR1"]["note"]
    assert "EURTRY'ninkiler de değişir" in page["B34"]["note"] and page["B34"]["note"].startswith("Elle puan → faiz")
    svc.reset_inputs(u, "tto")
