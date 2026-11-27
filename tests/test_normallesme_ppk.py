"""TLREF normalleşmesi on the OIS · PPK page (``tto/extras.py``: ``NORM_NAME``, ``NORM_USED_NAME``, ``NORM_PPK_NAME``).

The desk, 26.11.2026: "Tcmb api ihalelerine ara verdigi icin tlrefin normallesecegi tarihi de bulmamiz veya bir input
yazip onun ustunden gitmemiz gerekli" - "Ois ppk sayfasi ustunde yapmaliyiz yeni panel olmadan, normalizasyon ac kapat
yapabilmeliyiz" - (the normal TLREF) "bunu da yazabileyim".

A switch in the page's pinned parameters (OIS_MAIN!K2:L6, each user's own): on with a date N and a normal TLREF L0, TLREF
is today's (J2) until N and normal after it.  The PPK model (Motor's "GLOBAL İMA PPK v3") solves for the normal path: every
evaluation of a path's ln G at a day t gets + E(min(t, n)), r0's prior mean is REF = L0, and the page measures the steps
from REF; its TLREF levels are TLREF as it runs - today's until N (the desk, 27.11.2026: "hala tlref baz vs kisminda
normal tlref kullaniliyor").  Off - the file's "Kapalı", and every calculation without a user - every value is the one
before, bit for bit.

The checks: off, every cell of the workbook against the workbook without the addition; on with no gap, every number as
off; a market made from a known path (an elevated TLREF until N, then L0 and known steps) gives its first step back from
REF, off shows the normalization in it; each user's switch is their own and the history's MPC machine is the one before;
a PPK calendar change with the switch on."""
from __future__ import annotations

import math
import os

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto.books import Book, remove_sheets, snapshot_today
from tto.marketdata.replay import ReplayProvider
from tto.xl.engine import Clock
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.tokenizer import index_to_col
from tto.xl.values import serial_to_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MINE = (ex.NORM_NAME, ex.NORM_USED_NAME, ex.NORM_PPK_NAME)
#: the cells the addition writes that the workbook leaves empty (OIS_MAIN, Motor) - the switch, its labels, the status,
#: the interface and the E column; K2 / L2 held Bloomberg's settle date before (now A6:B6)
NEW_OIS = ({a for a, _, _ in ex.NORM_ROWS} | {a for _, _, a in ex.NORM_ROWS}
           | {ex.NORM_ON, ex.NORM_DAYS, ex.NORM_REF, ex.NORM_GAP} | set(ex.OIS_SPOT_CELLS))
NEW_MOTOR = {"%s%d" % (ex.NORM_E_COL, r) for r in range(ex.NORM_E_ROWS[0] - 1, ex.NORM_E_ROWS[1] + 1)}


def _book(with_mine: bool) -> Book:
    """The TRY workbook in replay, with every addition, or with every addition but this one and Bloomberg's settle date
    where it stood (OIS_MAIN!K2:L2) - the workbook as dc96cf3 built it."""
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    builders, cells = ex._BUILDERS["tto"], ex.OIS_SPOT_CELLS
    try:
        if not with_mine:
            ex._BUILDERS["tto"] = tuple(b for b in builders if b[0] not in MINE)
            ex.OIS_SPOT_CELLS = ("K2", "L2")
        assert ex.apply("tto", model) == []
    finally:
        ex._BUILDERS["tto"], ex.OIS_SPOT_CELLS = builders, cells
    today = snapshot_today(Model.load(os.path.join(ROOT, "models", "tto.json.gz")))
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)                          # type: ignore[assignment]
    return Book("tto", "TRY masa", model, provider=ReplayProvider(label="workbook"), clock=clock, replay=True)


@pytest.fixture(scope="module")
def books():
    return _book(True), _book(False)


def at(book: Book, ref: str, calc=None):
    si, rc = book.cell(ref)
    return (calc or book.engine.shared).get(si, *divmod(rc, COLS))


def same(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return a == b or (a != a and b != b)
    if hasattr(a, "rows"):
        return len(a.rows) == len(b.rows) and all(len(x) == len(y) and all(same(p, q) for p, q in zip(x, y))
                                                  for x, y in zip(a.rows, b.rows))
    return a == b


def moved(book: Book, calc_a, calc_b, other: Book = None):
    """Every cell of the workbook (formulas and constants of every sheet) whose value differs between two calculations
    (of this book, or ``other``'s second)."""
    other = other or book
    out = []
    for sa, sb in zip(book.model.sheets, other.model.sheets):
        assert sa.name == sb.name
        for rc in sorted(set(sa.fml) | set(sa.consts) | set(sb.fml) | set(sb.consts)):
            r, c = divmod(rc, COLS)
            if not same(calc_a.get(sa.index, r, c), calc_b.get(sb.index, r, c)):
                out.append("%s!%s%d" % (sa.name, index_to_col(c), r))
    return out


def switch_on(book: Book, date: float, level: float, extra=None):
    """A calculation of its own with the switch on (L2 Açık, L3 the date, L4 the normal TLREF) and ``extra`` cells."""
    si = book.model.sheet_index["OIS_MAIN"]
    values = {(si, parse_a1(ex.NORM_SWITCH)): ex.NORM_OPEN, (si, parse_a1(ex.NORM_DATE)): date,
              (si, parse_a1(ex.NORM_LEVEL)): level}
    values.update(extra or {})
    return book.engine.layer(("normppk", date, level, tuple(sorted(values.items(), key=str))), book.engine.shared, values)


# ============================================================================== off: as before, cell for cell
def test_off_every_value_is_the_one_before(books):
    """The file's "Kapalı" - every calculation without a user, and every user who did not switch it on: every value of
    every sheet is the workbook's without the addition, but the addition's own cells - the switch and its labels where
    Bloomberg's settle date stood (K2:L2, now in the parameters' last row A6:B6), the status, the interface M2:M5 and
    Motor's E column (0 everywhere).  The added terms are an exact 0 and the references are picked with IF, so the PPK
    solver, the scenarios, the date-to-date block, the forwards, every reader of the paths, give the same bits."""
    new, old = books
    diff = moved(new, new.engine.shared, old.engine.shared, old)
    ois = sorted(d for d in diff if d.startswith("OIS_MAIN!"))
    motor = {d.split("!")[1] for d in diff if d.startswith("Motor!")}
    # (the OIS-implied date's helper sheet reads the switch's cells - L2, L4: the walk's own builder, merged in v2)
    assert [d for d in diff if not d.startswith(("OIS_MAIN!", "Motor!", "EK_NORM!"))] == []
    assert set(a.split("!")[1] for a in ois) <= NEW_OIS, ois
    assert motor <= NEW_MOTOR, sorted(motor)[:10]
    assert {"K2", "L2", "A6", "B6"} <= set(a.split("!")[1] for a in ois)          # (the settle date moved)
    assert at(new, "OIS_MAIN!A6") == at(old, "OIS_MAIN!K2") == "Bloomberg valörü" and at(new, "OIS_MAIN!B6") == at(old, "OIS_MAIN!L2")
    assert [at(new, "OIS_MAIN!" + a) for a in ("K2", "L2", "L5", "L6", "M2", "M3", "M5")] == \
        ["Normalleşme", "Kapalı", "", "Kapalı", 0.0, 0.0, 0.0]
    assert at(new, "OIS_MAIN!M4") == at(new, "OIS_MAIN!J2")
    assert {at(new, "Motor!H%d" % r) for r in range(*ex.NORM_E_ROWS)} == {0.0}
    # the default normal TLREF: Masa's policy rate − 15 bp
    assert at(new, "OIS_MAIN!L4") == at(new, "MASA!Q155") / 100 - 0.0015
    # the other books have no part of it
    assert not any(b[0] in MINE for k, v in ex._BUILDERS.items() if k != "tto" for b in v)


def test_every_read_of_a_path_gets_its_own_day_e():
    """What the addition writes: + E(t) after every ln G of a PPK path read at a day t, as the meeting table's readers
    read it (the path's ln G at the last meeting up to t, then the growth from there to t at the path's level) - the
    scenario pars, the implied curve's discount factors, the date-to-date block, the forwards, RET's scenarios, the cash
    flows, carry; the solver's payment days; nothing of the step / PPK basamak part (EK_PPK, OIS_MAIN!BJ)."""
    from tto.xl.parser import parse_template
    from tto.xl.unparse import Unparser
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    assert ex.apply("tto", model) == []
    found, exact = [], []

    def walk(nd, parent, host, r, c, text):
        if nd[0] == "func" and nd[1] == "INDEX" and len(nd[2]) == 2 and ex._norm_ref(nd[2][0], host, c) in ex.NORM_PATHS:
            match = nd[2][1]
            assert match[0] == "func" and match[1] == "MATCH" and ex._norm_ref(match[2][1], host, c) == ("Motor", "C", 4, 84)
            # its parent: (INDEX(...) + E(t)), t the MATCH's day ...
            ok = (parent is not None and parent[0] == "bin" and parent[1] == "+" and parent[2] is nd
                  and parent[3] == ex._norm_e_node(match[2][0]))
            # ... and the growth from the meeting to t follows - or t is a meeting's day itself (MATCH(t, ·, 0))
            u = Unparser(r, c)
            t, cref = u.text(match[2][0]), u.text(match[2][1])
            if u.text(match[2][2]) == "0":
                exact.append(t)
            else:
                ok = ok and ("+(%s-INDEX(%s,MATCH(%s," % (t, cref, t)) in text
            found.append(ok)
        kids = nd[2] if nd[0] == "func" else [nd[2], nd[3]] if nd[0] == "bin" else [nd[1]] if nd[0] in ("paren", "neg", "pos", "pct", "single") else []
        for k in kids:
            walk(k, nd, host, r, c, text)

    for name in ex.NORM_READERS:
        for rc, tid in model.sheet(name).fml.items():
            if not ex._NORM_PATH_TPL.search(model.templates[tid]):
                continue
            r, c = divmod(rc, COLS)
            ast = parse_template(model.templates[tid])
            walk(ast, None, name, r, c, Unparser(r, c).text(ast))
    assert len(found) >= 1700 and all(found), (len(found), found.count(False))
    assert exact == ["$K$123"] * 3                                  # (the stub calculator: the first meeting's day)
    assert "IF(OIS_MAIN!$M$2=1" not in ex.formula_of(model, "OIS_MAIN", "BJ84")
    assert not any("M$2" in model.templates[t] for t in model.sheet("EK_PPK").fml.values())
    for start in ex.NORM_ITERATIONS + (ex.NORM_RESULT - 88,):
        for p in (0, 44):
            text = ex.formula_of(model, "Motor", "B%d" % (start + 88 + p))
            assert text.endswith("+" + ex.norm_e("$B$%d" % (ex.NORM_PAYDAYS[0] + p))), text
            # the derivatives (C) are as they were: E does not depend on the levels
            assert "M$2" not in ex.formula_of(model, "Motor", "C%d" % (start + 88 + p))
    assert ex.formula_of(model, "Motor", "D4305").startswith("IF(OIS_MAIN!$M$2=1,OIS_MAIN!$M$4,IF(AND(ISNUMBER(OIS_MAIN!$J$2)")


# ============================================================================== on, no gap: as off
def test_on_without_a_gap_every_number_is_the_one_before(books):
    """On with a date and the normal TLREF typed at today's TLREF (gap 0): E is 0, REF is today's TLREF - every number of
    every sheet as off; only the switch's own cells (M2, M3, L5, the status) say it is on."""
    new, _ = books
    spot, j2 = at(new, "OIS_MAIN!B2"), at(new, "OIS_MAIN!J2")
    on = switch_on(new, spot + 20, j2)
    assert (at(new, "OIS_MAIN!M2", on), at(new, "OIS_MAIN!M3", on), at(new, "OIS_MAIN!M5", on)) == (1.0, 20.0, 0.0)
    assert at(new, "OIS_MAIN!L6", on) == "Açık · 20 gün · fark 0 bp" and at(new, "OIS_MAIN!O9", on) == "Spot"
    diff = moved(new, new.engine.shared, on)
    # (merged in v2: with the switch on the OIS-implied date's walk works - its helper sheet EK_NORM and its block beside
    # STUB İMA, OIS_MAIN!AO8:AS15 -, and the PPK step tables measure their first window from REF instead of the stub's
    # O/N (EK_PPK, the step builder's choice): their own tests cover them; everything else as off)
    walk = {d for d in diff if d.startswith("EK_NORM!") or (d.startswith("OIS_MAIN!A") and d.split("!")[1][:2] in ("AO", "AP", "AQ", "AR", "AS")
                                                            and 8 <= int("".join(ch for ch in d.split("!")[1] if ch.isdigit())) <= 15)}
    steps = {d for d in diff if d.startswith("EK_PPK!")}
    diff = [d for d in diff if d not in walk and d not in steps]
    assert sorted(diff) == sorted(["OIS_MAIN!" + a for a in ("L2", "L4", "L5", "L6", "M2", "M3")]), diff


# ============================================================================== a market from a known path
#: the synthetic market: TLREF H until the normalization (n days after the OIS spot), then L0; a step at each meeting
H, L0, N_DAYS = 0.40, 0.37, 20
STEPS = [-0.0100, -0.0100, -0.0075, -0.0075] + [-0.0050] * 8 + [-0.0025] * 8


def _market(book: Book):
    """The quotes the known path prices, each by the solver's own convention (zero coupon to 3M, quarterly ACT/365 par
    after; TLREF compounded as the model compounds it, Motor's Pcum), on the solver's own days - and the cells they go
    into (1W / 2W OIS_MAIN!AU13:AU14, 1M … 10Y the page's quotes Motor!B306:B321 read)."""
    pcum = [at(book, "Motor!F%d" % r) for r in range(528, 4229)]
    meet = [(at(book, "Motor!C%d" % r), at(book, "Motor!C%d" % (4306 + r))) for r in range(5, 85)]   # (day, knot active)
    meet = [d for d, on in meet if on == 1.0 and d < 99999]
    pay = [(at(book, "Motor!B%d" % r), at(book, "Motor!C%d" % r)) for r in range(4395, 4440)]

    def normal(t):
        return L0 + sum(s for d, s in zip(meet, STEPS) if d <= t)

    def lng(t):
        cuts = sorted({0, t, N_DAYS} | {d for d in meet if d < t})
        cuts = [x for x in cuts if x <= t]
        out = 0.0
        for a, b in zip(cuts, cuts[1:]):
            x = normal(a) + ((H - L0) if a < N_DAYS else 0.0)
            out += (b - a) * math.log(1 + x / 365) - (pcum[min(int(b), 3700)] - pcum[min(int(a), 3700)]) * (x / 365) ** 2
        return out

    quotes = []
    for r in range(4445, 4463):
        typ, point, days = at(book, "Motor!B%d" % r), int(at(book, "Motor!C%d" % r)), at(book, "Motor!E%d" % r)
        if typ == 0:
            quotes.append((math.exp(lng(days)) - 1) * 365 / days)
        else:
            ann = sum(tau * math.exp(-lng(t)) for p, (t, tau) in enumerate(pay, 1) if 6 <= p <= point)
            quotes.append((1 - math.exp(-lng(pay[point - 1][0]))) / ann)
    si = book.model.sheet_index["OIS_MAIN"]
    cells = ["AU13", "AU14"] + [ex.formula_of(book.model, "Motor", "B%d" % r).split("!")[1] for r in range(306, 322)]
    values = {(si, parse_a1(a)): q for a, q in zip(cells, quotes)}
    values[(si, parse_a1("J2"))] = H
    return values


def test_a_market_made_from_a_known_path_gives_its_first_step_back(books):
    """Quotes made from a known path - TLREF 40 % until 20 days after the spot, then the normal 37 %, −100 bp at the next
    meeting, −100, −75, −75, then smaller cuts - switched on with that date and level: the solver reprices every quote it
    includes within its tolerance (AU6, 1 bp) and gives the next meeting's step back from REF to within a couple of bp
    (−100,15 bp on 03.11's calendar), the one after too (−99,08); the stub's levels are the normal TLREF.  Off, the same quotes put
    the normalization into the next meeting's cut (about −430 bp from today's 40 %) and fit worse."""
    new, _ = books
    market = _market(new)
    spot = at(new, "OIS_MAIN!B2")
    off = new.engine.layer(("normppk", "market off"), new.engine.shared, market)
    on = switch_on(new, spot + N_DAYS, L0, market)
    assert (at(new, "OIS_MAIN!M2", on), at(new, "OIS_MAIN!M3", on), at(new, "OIS_MAIN!M4", on)) == (1.0, float(N_DAYS), L0)
    tol = at(new, "OIS_MAIN!AU6", on)
    got = {k: at(new, "OIS_MAIN!" + k, on) for k in ("R10", "R11", "R12", "R13", "AU11", "AU12", "AN9", "AN10", "AN11", "AN12")}
    assert abs(got["R10"] - STEPS[0] * 10000) < 2.0 and abs(got["R11"] - STEPS[1] * 10000) < 2.0, got
    assert abs(got["R12"] - STEPS[2] * 10000) < 3.0 and abs(got["R13"] - STEPS[3] * 10000) < 3.0, got
    assert got["AU11"] <= tol and got["AU12"] == "OK", got                      # every included quote within 1 bp
    residuals = [at(new, "Motor!C%d" % r, on) for r in range(5861, 5879)]
    assert max(abs(x) for x in residuals) <= tol, residuals
    stub = [got[k] for k in ("AN9", "AN10", "AN11", "AN12") if got[k] != "–"]            # (the stub's knots in use)
    assert len(stub) >= 2 and all(abs(x) < 0.5 for x in stub), got                    # the stub's levels: the normal TLREF
    # the Spot row is TLREF as it runs - today's -, the cumulative step is measured from REF
    assert at(new, "OIS_MAIN!S9", on) == H and at(new, "OIS_MAIN!T10", on) == round(got["R10"], 2)
    # off: today's 40 % is the base - the normalization is part of the next meeting's cut
    first_off = at(new, "OIS_MAIN!R10", off)
    assert first_off < (L0 - H + STEPS[0]) * 10000 + 50 and first_off < -350, first_off
    assert at(new, "OIS_MAIN!AU11", off) > got["AU11"]
    # the scenarios carry the stretch too: S1 typed with the true first two steps prices the 3M (two meetings in it) at
    # the 3M quote - its par Motor!G327, from REF with the steps, + E
    si = new.model.sheet_index["OIS_MAIN"]
    steps = {(si, parse_a1("U%d" % (10 + k))): s * 10000 for k, s in enumerate(STEPS[:2])}
    s1 = switch_on(new, spot + N_DAYS, L0, {**market, **steps})
    assert at(new, "OIS_MAIN!X9", s1) == H and at(new, "Motor!H4", s1) == L0          # (the chain starts from REF)
    assert abs(at(new, "OIS_MAIN!X11", s1) - (L0 + STEPS[0] + STEPS[1])) < 1e-15        # (both meetings after N: normal)
    assert abs(at(new, "Motor!G327", s1) - market[(si, parse_a1("B11"))]) < 1e-12


# ============================================================================== the page's levels: TLREF as it runs
def _one_year(book: Book, calc, path: str) -> float:
    """A path of Motor's meeting table at the 1Y day (OIS_MAIN!E447) as the page reads it: the last meeting up to it."""
    day = at(book, "OIS_MAIN!E447", calc)
    k = max(k for k in range(4, 85) if isinstance(at(book, "Motor!C%d" % k, calc), float) and at(book, "Motor!C%d" % k, calc) <= day)
    return at(book, "Motor!%s%d" % (path, k), calc)


def test_the_page_shows_tlref_as_it_runs(books):
    """The desk, 27.11.2026, on the page with the switch on: "Normal tlref ve kullanilan tarihi degistirdim ama hala tlref
    baz vs kisminda normal tlref kullaniliyor".  TLREF typed at 39 %, the normal TLREF 35,85 %, the date 91 days after the
    spot - MPC1 (day 37) and MPC2 (day 79) inside the stretch - and S1's steps typed 0, 0, −100: IMPLIED RATES' levels are
    TLREF as it runs - today's on the Spot row, the normal path + the gap after a meeting inside the stretch, the normal
    path after the date - in the Implied MPC and the three TLREF scenario columns alike; every step stays the PPK step on
    the normal path (Implied bps, Cum. Implied, the chart's scenario steps, DV01 Risk's scenario − implied) and the model
    reads the normal path (Motor's meeting table).  STUB İMA's levels and, with a date past a year, the 1Y figures follow
    the same rule; off, the same typed TLREF and steps give TLREF + the steps everywhere."""
    new, _ = books
    si = new.model.sheet_index["OIS_MAIN"]
    spot = at(new, "OIS_MAIN!B2")
    typed = {(si, parse_a1("J2")): 0.39, (si, parse_a1("U10")): 0.0, (si, parse_a1("U11")): 0.0, (si, parse_a1("U12")): -100.0}
    on = switch_on(new, spot + 91, 0.3585, typed)
    gap = at(new, "OIS_MAIN!M5", on)
    assert (at(new, "OIS_MAIN!M2", on), at(new, "OIS_MAIN!M3", on), gap) == (1.0, 91.0, 0.39 - 0.3585)
    assert at(new, "OIS_MAIN!L6", on) == "Açık · 91 gün · fark 315 bp"
    days = [at(new, "Motor!C%d" % k, on) for k in (5, 6, 7)]
    assert days[0] < 91 and days[1] < 91 <= days[2], days                    # (replay: MPC1, MPC2 inside; MPC3 after)
    # the Spot row: today's TLREF in every level column, its label as off
    assert [at(new, "OIS_MAIN!%s9" % c, on) for c in "SXYZ"] == [0.39] * 4 and at(new, "OIS_MAIN!O9", on) == "Spot"
    # TLREF Baz (S1): 39 % through MPC1 and MPC2 (steps 0), then the normal TLREF − 100 bp after the date; Motor's S1 is the
    # normal path the scenario is priced on
    assert [at(new, "Motor!H%d" % k, on) for k in (4, 5, 6)] == [0.3585] * 3
    assert [round(at(new, "OIS_MAIN!X%d" % r, on), 12) for r in (10, 11, 12)] == [0.39, 0.39, 0.3485]
    assert [at(new, "OIS_MAIN!BM%d" % r, on) for r in (10, 11, 12)] == [0.0, 0.0, -100.0]   # the steps, not the drop at N
    checked = 0
    for r in range(10, 90):
        k, b = r - 5, r + 5724
        d = at(new, "Motor!C%d" % k, on)
        if at(new, "OIS_MAIN!P%d" % r, on) == "" or d == 0:
            continue
        add = gap if d < 91 else 0.0
        assert at(new, "OIS_MAIN!S%d" % r, on) == at(new, "Motor!B%d" % b, on) + add, r
        for col, path in (("X", "H"), ("Y", "N"), ("Z", "P")):
            assert at(new, "OIS_MAIN!%s%d" % (col, r), on) == at(new, "Motor!%s%d" % (path, k), on) + add, (col, r)
        # Cum. Implied from the normal TLREF on the normal path (Motor's İma TLREF = the solver's level)
        implied = at(new, "Motor!K%d" % k, on)
        assert implied == at(new, "Motor!B%d" % b, on)
        assert abs(at(new, "OIS_MAIN!T%d" % r, on) - (implied - 0.3585) * 10000) <= 0.005 + 1e-9, r
        checked += 1
    assert checked >= 8
    for col, r in (("AK", 10), ("AL", 11), ("AM", 12)):
        assert at(new, "DV01_RISK!%s66" % col, on) == (at(new, "Motor!H%d" % (r - 5), on) - at(new, "Motor!K%d" % (r - 5), on)) * 10000
    # STUB İMA: its levels start before the date - the gap in them; TLREF farkı from the normal TLREF, as before
    assert at(new, "OIS_MAIN!AM9", on) == at(new, "Motor!B5728", on) + gap
    assert at(new, "OIS_MAIN!AN9", on) == (at(new, "Motor!B5728", on) - 0.3585) * 10000
    # the 1Y figures: the date before the year - no gap; a date past it - the gap in the levels, not in the bp
    assert at(new, "OIS_MAIN!B5", on) == _one_year(new, on, "K") and at(new, "OIS_MAIN!H5", on) == _one_year(new, on, "H")
    late = switch_on(new, spot + 400, 0.3585, typed)
    gap = at(new, "OIS_MAIN!M5", late)
    assert at(new, "OIS_MAIN!E447", late) < 400 and gap == 0.39 - 0.3585
    for addr, path in (("B5", "K"), ("H5", "H"), ("R3", "H"), ("R4", "N"), ("R5", "P")):
        assert at(new, "OIS_MAIN!" + addr, late) == _one_year(new, late, path) + gap, addr
    assert at(new, "OIS_MAIN!D5", late) == (_one_year(new, late, "K") - 0.3585) * 10000
    assert abs(at(new, "OIS_MAIN!S3", late) - (_one_year(new, late, "H") - 0.3585) * 10000) <= 0.05 + 1e-9
    # off: the typed TLREF is the Spot row and the base of every scenario, as before
    off = new.engine.layer(("normppk", "levels off"), new.engine.shared, typed)
    assert at(new, "OIS_MAIN!M2", off) == 0.0 and at(new, "OIS_MAIN!X9", off) == 0.39 == at(new, "Motor!H4", off)
    assert at(new, "OIS_MAIN!X10", off) == at(new, "Motor!H5", off) == 0.39 and round(at(new, "OIS_MAIN!X12", off), 12) == 0.38
    assert at(new, "OIS_MAIN!S10", off) == at(new, "Motor!B5734", off)


# ============================================================================== per user; the history
def test_each_users_switch_is_their_own_and_the_history_is_as_before(books, tmp_path):
    """One user's switch changes their own page only: another user's and the shared calculation keep today's numbers, and
    the user's own Bootstrap is everybody's.  The history's MPC machine (no user: the file's "Kapalı") answers a day
    exactly as without the addition."""
    from tto.history import MpcMachine
    svc = make_service(tmp_path)
    try:
        ayse, veli = svc.login("Norm Ayşe")["user"], svc.login("Norm Veli")["user"]
        before = {ref: cell(svc, ref) for ref in ("OIS_MAIN!R10", "OIS_MAIN!S9", "OIS_MAIN!D5", "MASA!I62", "Motor!G325")}
        spot = cell(svc, "OIS_MAIN!B2")
        res = svc.set_inputs(ayse, "tto", [{"ref": "OIS_MAIN!L2", "value": "Açık"},
                                           {"ref": "OIS_MAIN!L3", "value": serial_to_date(spot + 20).strftime("%d.%m.%Y")},
                                           {"ref": "OIS_MAIN!L4", "value": "33"}])
        assert res["errors"] == []
        assert cell(svc, "OIS_MAIN!M2", ayse) == 1.0 and cell(svc, "OIS_MAIN!L4", ayse) == 0.33
        # the Spot row stays today's TLREF; the scenarios start from the normal TLREF, the first step is measured from it
        assert cell(svc, "OIS_MAIN!S9", ayse) == cell(svc, "OIS_MAIN!J2") and cell(svc, "Motor!H4", ayse) == 0.33
        assert cell(svc, "OIS_MAIN!R10", ayse) != before["OIS_MAIN!R10"]
        # Bootstrap (Murex's MTM) never moves: the switched-on user's bootstrap is everybody's
        boot = ["Motor!%s%d" % (col, r) for r in range(88, 131) for col in "FGI"]
        assert [cell(svc, ref, ayse) for ref in boot] == [cell(svc, ref) for ref in boot]
        for user in (None, veli):
            assert {ref: cell(svc, ref, user) for ref in before} == before, user
            assert cell(svc, "OIS_MAIN!M2", user) == 0.0
        # Delete on the normal TLREF: back to its default (the policy rate − 15 bp); "Kapalı" again: the numbers of before
        assert svc.set_inputs(ayse, "tto", [{"ref": "OIS_MAIN!L4", "value": ""}])["errors"] == []
        assert cell(svc, "OIS_MAIN!L4", ayse) == cell(svc, "MASA!Q155") / 100 - 0.0015
        assert svc.set_inputs(ayse, "tto", [{"ref": "OIS_MAIN!L2", "value": "Kapalı"}])["errors"] == []
        assert {ref: cell(svc, ref, ayse) for ref in before} == before
        # the page: the pinned parameters show the switch, the status and Bloomberg's settle date
        params = next(p for p in svc.view(ayse, "ois")["panels"] if p["id"] == "B1")["data"]
        texts = [[c.get("t", "") for c in row] for row in params["rows"]]
        assert ["Normalleşme", "Kapalı"] in [row[-2:] for row in texts] and texts[-1][:2][0] == "Bloomberg valörü"
        assert [row[-2] for row in texts] == ["Normalleşme", "Normalleşme tarihi", "Normal TLREF %", "Kullanılan tarih", "Durum"]
    finally:
        svc.stop()
    # the history's machine, on the workbook with and without the addition: one day's answer, the same
    new, old = books
    roots = {r: at(new, "OIS_MAIN!J%d" % r) for r in range(9, 27) if isinstance(at(new, "OIS_MAIN!J%d" % r), str)}
    quotes = {root: at(new, "OIS_MAIN!B%d" % r) * 100 for r, root in roots.items() if isinstance(at(new, "OIS_MAIN!B%d" % r), float)}
    meetings = [serial_to_date(at(new, "OIS_MAIN!P%d" % r)) for r in range(10, 90) if isinstance(at(new, "OIS_MAIN!P%d" % r), float)]
    holidays = [at(new, "Motor!A%d" % r) for r in range(361, 524) if isinstance(at(new, "Motor!A%d" % r), float)]
    day = serial_to_date(at(new, "OIS_MAIN!B2") - 1)
    answers = [MpcMachine(b.model).solve(day, serial_to_date(at(new, "OIS_MAIN!B2")), at(new, "OIS_MAIN!J2") * 100, quotes,
                                         meetings, roots, holidays) for b in (new, old)]
    assert answers[0]["rows"] and answers[0] == answers[1]


# ============================================================================== rows move
def test_a_calendar_change_with_the_switch_on(tmp_path):
    """An extraordinary meeting put in before the next one while a user's switch is on: nothing of the switch is kept by
    meeting row, so it stays as it was; the new meeting is the first upcoming one and its step is measured from REF, the
    solver still reprices its quotes, and the shared numbers of the new calendar are the switch-off ones."""
    svc = make_service(tmp_path)
    try:
        user = svc.login("Norm Takvim")["user"]
        spot = cell(svc, "OIS_MAIN!B2")
        assert svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!L2", "value": "Açık"},
                                            {"ref": "OIS_MAIN!L3", "value": serial_to_date(spot + 30).strftime("%d.%m.%Y")},
                                            {"ref": "OIS_MAIN!L4", "value": "34"}])["errors"] == []
        h = svc.history
        start = h.meetings()
        extra = serial_to_date(spot + 21)                            # a Wednesday, inside the stretch
        assert extra.weekday() < 5
        res = h.set_calendar(svc.login("norm-admin")["user"], [extra.strftime("%d.%m.%Y")] + start[:-1])
        assert res["changed"] >= 1
        assert cell(svc, "OIS_MAIN!P10") == float(spot + 21)
        mine = {k[1]: v for k, v in svc.store.user_inputs(user, "tto").items()}
        assert (mine["OIS_MAIN!L2"], mine["OIS_MAIN!L3"], mine["OIS_MAIN!L4"]) == ("Açık", float(spot + 30), 0.34)
        assert cell(svc, "OIS_MAIN!M2", user) == 1.0 and cell(svc, "OIS_MAIN!M3", user) == 30.0
        # the new meeting takes effect inside the stretch (day 22, N day 30): its step is measured on the normal path
        # (Motor's İma TLREF), its level on the page is the normal one + the gap
        ref, level, gap = cell(svc, "OIS_MAIN!M4", user), cell(svc, "Motor!K5", user), cell(svc, "OIS_MAIN!M5", user)
        assert ref == 0.34 and abs(cell(svc, "OIS_MAIN!R10", user) - (level - ref) * 10000) < 1e-9
        assert abs(cell(svc, "OIS_MAIN!T10", user) - round((level - ref) * 10000, 2)) < 1e-9
        assert cell(svc, "Motor!C5", user) < 30 and cell(svc, "OIS_MAIN!S10", user) == level + gap
        assert cell(svc, "OIS_MAIN!AU12", user) in ("OK", "Kota/takvim tutarsız – kontrolü incele")
        assert cell(svc, "OIS_MAIN!AU11", user) < 10
        shared = cell(svc, "OIS_MAIN!J2")
        assert cell(svc, "OIS_MAIN!M2") == 0.0 and abs(cell(svc, "OIS_MAIN!R10") - (cell(svc, "OIS_MAIN!S10") - shared) * 10000) < 1e-9
    finally:
        svc.stop()
