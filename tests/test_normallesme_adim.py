"""TLREF normalleşmesi (26.11.2026): what turns rates into PPK steps, and the PPK basamak curve, follow the user's switch on
OIS · PPK - "Burada tlref'e geri gelecek gibi hesap yapacagiz".  The switch's cells (``OIS_MAIN!M2:M5``: ON, n, REF,
gap · ON) are another builder's; here they are typed as a user's own values to stand for it (``put_switch``).

* **MPC OIS / MPC SPREAD → PPK ADIMI** (``EK_PPK``) and **Broker Chat's PPK step** (``Service._mpc_implied``): on, a
  window's rate is first taken to the normal path - its stretch part of ln G, E(min(end, n)) − E(min(start, n)), taken
  off (E(m) = m·[ln(1 + H/365) − ln(1 + L0/365)] − Pcum(m)·[(H/365)² − (L0/365)²]) - and the first window's base is REF,
  the normal TLREF; the page and the chat agree, every two-way inverse stays exact.
* **İma oran (model)** (``OIS_MAIN!BJ``): on, the model's actual window rate (its stretch part added back), so that typed
  back as a window's rate it gives the model's TLREF as its O/N.
* **PPK basamak** (``ppkcurve.read``): on, the path is the model's + the gap before the normalization date (a knot there),
  calibrated as before - every quote reprices; the sheet and the badge say so.  Bootstrap never moves.
* **Off** (the default, and every calculation without a user): every number is the formula of before, bit for bit."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell
from tto import extras as ex
from tto import ppkcurve as pk
from tto.render import calc_value
from tto.server import create_app
from tto.xl.errors import XlError
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.tokenizer import to_template

WINDOWS = ex.PPK_WINDOWS[1] - ex.PPK_WINDOWS[0] + 1            # 16 windows of 'MPC OIS' ...
PAIRS = ex.PPK_PAIRS[1] - ex.PPK_PAIRS[0] + 1                  # ... 15 pairs of 'MPC SPREAD'
LINE_DAY = "2026-01-15"                                        # (the day the chat's lines are read on: nothing is kept)
N_DAYS, L0 = 100.0, 0.3335                                     # N 100 days after the OIS spot (in window 1), L0 33,35 %


@pytest.fixture(scope="module")
def svc(module_service):
    """A private service whose switch cells (OIS_MAIN!M2:M5) are each user's own inputs - the switch's interface, typed."""
    s = module_service
    book = s.books["tto"]
    s.et.call(lambda: book.declare("OIS_MAIN!M2:M5", scope="user", group="test-norm"))
    return s


def put(svc, user, cells, **kw):
    res = svc.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()], **kw)
    assert res["errors"] == [], res["errors"]
    return res


def put_switch(svc, user, n=N_DAYS, l0=L0, on=1.0):
    """The switch as its cells have it: ON, n, REF = L0 (on), gap · ON = (H − L0)·ON."""
    h = cell(svc, "OIS_MAIN!J2", user)
    put(svc, user, {"OIS_MAIN!M2": on, "OIS_MAIN!M3": n if on else 0.0, "OIS_MAIN!M4": l0 if on else h,
                    "OIS_MAIN!M5": (h - l0) * on})


def ppk(svc, user, col, r):
    return cell(svc, "%s!%s%d" % (ex.PPK_SHEET, col, r), user)


def term(svc, user, slot):
    """The weekend / holiday term of the window from meeting slot ``slot``'s effective day to the next one's (slot −1: the
    stub from the OIS spot): Motor's Pcum at its end − at its start."""
    return cell(svc, "Motor!J%d" % (slot + 6), user) - cell(svc, "Motor!J%d" % (slot + 5), user)


def day(svc, user, slot):
    """Meeting slot ``slot``'s effective day, days from the OIS spot (slot −1: the spot, 0)."""
    return 0.0 if slot < 0 else cell(svc, "Motor!C%d" % (slot + 5), user)


def by_hand(svc, user, l0=L0, n=N_DAYS):
    """E(m) by hand - Motor's daily Pcum read cell by cell, H today's TLREF - as a function of a day from the spot."""
    h = cell(svc, "OIS_MAIN!J2", user)

    def e(t):
        m = min(t, n)
        p = cell(svc, "Motor!F%d" % (528 + int(min(m, 3700))), user)
        return m * (math.log(1 + h / 365) - math.log(1 + l0 / 365)) - p * ((h / 365) ** 2 - (l0 / 365) ** 2)
    return e


def solve(f, lo=-0.2, hi=0.2):
    """The root of ``f``, increasing around it, by bisection (an algorithm of its own)."""
    for _ in range(200):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if f(mid) < 0.0 else (lo, mid)
    return (lo + hi) / 2.0


def chat(svc, user, text):
    """The meeting swaps of chat lines as Broker Chat reads them: {said: quote}."""
    rows = svc.broker_parse(user, text, LINE_DAY)["rows"]
    return {q["raw"].split(" mpc")[0].split()[-1]: q for q in rows if (q.get("mpc") or {}).get("start")}


def at_cell(svc, user, sheet, addr, text):
    """``text`` (a formula) evaluated as if it were the formula of ``sheet!addr``, in the user's calculation."""
    book = svc.books["tto"]
    si = book.model.sheet_index[sheet]
    r, c = divmod(parse_a1(addr), COLS)
    fn = book.engine.compiler.compile_expression(to_template(text.lstrip("="), r, c), False)
    return svc.et.call(lambda: calc_value(svc._calc(user, book), fn, si, r, c))


def curves(svc, user):
    book = svc.books["tto"]
    return svc.et.call(lambda: svc._try_curves(book, svc._calc(user, book)))


def model_path(svc, user):
    """The PPK model's path as the user's calculation has it (Motor!C4:C84 / K4:K84): (knots, rates) as a StepCurve
    keeps them."""
    c = pk.StepCurve([cell(svc, "Motor!C%d" % r, user) for r in range(4, 85)],
                     [cell(svc, "Motor!K%d" % r, user) for r in range(4, 85)])
    return c.knots, c.rates


# ============================================================================== the formulas of before (dc96cf3)
def before_window(r):
    """EK_PPK's formulas the normalization wraps, as they were (tto/extras.py of dc96cf3): window row ``r``."""
    k = r - ex.PPK_FIRST
    t, b = ex.ppk_term(k), ex.ppk_term(k - 1)
    on = "IF(ISBLANK($Y%d),$J%d+$Z%d/10000,$Y%d)" % (r, r, r, r)
    return {"G": '=IF(AND(ISBLANK($Y%d),ISBLANK($Z%d)),"",IFERROR(IF(N($E%d)>0,' % (r, r, r)
                 + ex.overnight_bd_back(on, "$E%d" % r, t) + ',""),""))',
            "J": "=" + ex.overnight_bd("$H%d" % r, "$I%d" % r, b),
            "K": "=IF(ISBLANK($Y%d),%s,$Y%d)" % (r, ex.overnight_bd("$G%d" % r, "$E%d" % r, t), r),
            "M": '=IFERROR((%s-$J%d)*10000,"")' % (ex.overnight_bd("$F%d" % r, "$E%d" % r, t), r)}


def before_pair(r):
    """... and pair row ``r``'s."""
    k = r - ex.PPK_FIRST
    t = ex.ppk_term(k + 1)
    on = "IF(ISBLANK($AB%d),$J%d+$AC%d/10000,$AB%d)" % (r, r + 1, r, r)
    later = "IF(ISBLANK($AA%d),%s,$AA%d)" % (r, ex.overnight_bd_back(on, "$E%d" % (r + 1), t), r)
    return {"S": '=IF(AND(ISBLANK($AA%d),ISBLANK($AB%d),ISBLANK($AC%d)),"",IFERROR((' % (r, r, r) + later
                 + '-$F%d)*10000,""))' % r,
            "U": "=IF(ISBLANK($AB%d),%s,$AB%d)" % (r, ex.overnight_bd("$T%d" % r, "$E%d" % (r + 1), t), r)}


#: EK_INTERP!C2 as it was (dc96cf3)
BEFORE_STATUS = ('=IF($B$3=1,"PPK basamak: TLREF toplantılar arasında sabit, kotalara aynen oturur"&IF($B$4=1,"",'
                 '" (offshore eğri kurulamadı: offshore Bootstrap)"),IF($B$2="%s","PPK basamak seçili ama PPK eğrisi '
                 'kurulamadı (kota ya da MPC ima yok): Bootstrap kullanılıyor","%s: bugünkü eğri, Murex\'in MTM\'i"))'
                 '&IF(OR($N$3=1,$N$4=1)," · eğri noktaları masanın listesinden (Ayarlar → Eğri noktaları)","")'
                 % (ex.INTERP_PPK, ex.INTERP_BOOT))


def raw_bj():
    """OIS_MAIN!BJ84:BJ99 as the workbook has them (no addition applied)."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw = Model.load(os.path.join(root, "models", "tto.json.gz"))
    return {r: ex.formula_of(raw, "OIS_MAIN", "BJ%d" % r) for r in range(ex.PPK_WINDOWS[0], ex.PPK_WINDOWS[1] + 1)}


def typed_some(svc, user):
    """A rate, a step, an O/N, a spread and a later window's rate / O/N / step typed across the tables (every branch)."""
    put(svc, user, {"EK_PPK!G3": "36,5", "EK_PPK!G4": "35", "EK_PPK!G9": "31,2", "EK_PPK!S5": "-25", "EK_PPK!S11": "10"})
    put(svc, user, {"EK_PPK!L5": "-40", "EK_PPK!K6": "0,339", "EK_PPK!T7": "0,33", "EK_PPK!U8": "0,325",
                    "EK_PPK!V9": "-30"})


def assert_off(svc, user, bj):
    """Every cell the normalization wraps is its formula of before, bit for bit (a typed rate / spread: its own value)."""
    book = svc.books["tto"]
    typed = svc.et.call(lambda: dict(svc._overlay(user, book))) if user else {}
    for k in range(WINDOWS):
        r = ex.PPK_FIRST + k
        for col, text in before_window(r).items():
            if book.cell("EK_PPK!%s%d" % (col, r)) in typed:
                continue
            got, want = ppk(svc, user, col, r), at_cell(svc, user, ex.PPK_SHEET, "%s%d" % (col, r), text)
            assert got == want and type(got) is type(want), (user, col, r, got, want)
        w = ex.PPK_WINDOWS[0] + k
        got, want = cell(svc, "OIS_MAIN!BJ%d" % w, user), at_cell(svc, user, "OIS_MAIN", "BJ%d" % w, bj[w])
        # (merged in v2: the PPK model itself reads M2, so with M2 typed as an error - a test's own doing, M2 is a formula
        # that never errs - Motor and with it the formula of before are that error too: equal, as off)
        assert got == want and (type(got) is float or isinstance(want, XlError)), (user, w)
    for k in range(PAIRS):
        r = ex.PPK_FIRST + k
        for col, text in before_pair(r).items():
            if book.cell("EK_PPK!%s%d" % (col, r)) in typed:
                continue
            got, want = ppk(svc, user, col, r), at_cell(svc, user, ex.PPK_SHEET, "%s%d" % (col, r), text)
            assert got == want and type(got) is type(want), (user, col, r, got, want)
    got, want = cell(svc, "EK_INTERP!C2", user), at_cell(svc, user, "EK_INTERP", "C2", BEFORE_STATUS)
    assert got == want and isinstance(got, str), (user, got, want)


# ============================================================================== off: the numbers of before
def test_off_every_number_is_the_formula_of_before(svc):
    """Off - nothing typed, the switch typed off (0), the switch's cell an error, the desk's calculation - every cell the
    normalization wraps (EK_PPK's O/N, bases, market steps, two-way defaults, OIS_MAIN!BJ, EK_INTERP's status) equals its
    formula of before evaluated in its place, bit for bit, with values typed across both tables; nothing else reads the
    normalization's helpers (they are 0)."""
    bj = raw_bj()
    plain, zero, broken = (svc.login(n)["user"] for n in ("Norm kapalı", "Norm sıfır yazılı", "Norm hatalı"))
    try:
        for u in (plain, zero, broken):
            typed_some(svc, u)
        put_switch(svc, zero, on=0.0)
        put(svc, broken, {"OIS_MAIN!M2": "=NA()", "OIS_MAIN!M3": N_DAYS, "OIS_MAIN!M4": L0, "OIS_MAIN!M5": 0.02})
        assert isinstance(cell(svc, "OIS_MAIN!M2", broken), XlError) and cell(svc, "OIS_MAIN!M2", zero) == 0.0
        for u in (None, plain, zero, broken):
            assert ppk(svc, u, "AJ", 3) == 0.0 and ppk(svc, u, "AJ", 7) == 0.0 and ppk(svc, u, "AG", 3) == 0.0
            assert_off(svc, u, bj)
        # (the steps typed came back as typed: the round trips of before)
        assert ppk(svc, plain, "L", 5) == -40.0 and ppk(svc, plain, "V", 9) == -30.0
    finally:
        for u in (plain, zero, broken):
            svc.reset_inputs(u, "tto")


def test_off_the_chat_and_the_ppk_curve_are_those_of_before(svc):
    """Off, Broker Chat's step is the conversion of before (no extra, the stub's O/N the first base: ``==``) and says
    nothing of a normalization; ``ppkcurve.read`` reads the model's path as it is - ``norm`` None, the shape Motor's own."""
    u = svc.login("Norm kapalı chat")["user"]
    lines = chat(svc, u, "10:00:00 dec mpc 36.50/37.00\n10:01:00 jan27 mpc 35.00/35.20")
    for said, k in (("dec", 0), ("jan27", 1)):
        imp = lines[said]["implied"]
        assert "norm" not in imp
        d, w = ppk(svc, u, "E", 3 + k), term(svc, u, k)
        prev_d, prev_w = ppk(svc, u, "I", 3 + k), term(svc, u, k - 1)
        base = pk.window_overnight(ppk(svc, u, "H", 3 + k), prev_d, prev_w)
        assert imp["prev_on"] == base * 100.0
        assert imp["bid"] == (pk.window_overnight(lines[said]["bid"] / 100.0, d, w) - base) * 1e4
    cv = curves(svc, u)
    assert cv["norm"] is None and not cv["errors"]
    assert (cv["shape"].knots, cv["shape"].rates) == model_path(svc, u)


# ============================================================================== on: E and the normal path
def test_on_a_windows_part_before_n_is_e_by_hand(svc):
    """The helpers: the switch as the sheet reads it (ON, n, H, REF, E's factors) and per window E at its start / end and
    their difference - by hand from Motor's daily Pcum; a window wholly after N has no part, one wholly before it the
    whole gap's growth over its days, one across N the days up to N."""
    u = svc.login("Norm E")["user"]
    try:
        put_switch(svc, u)
        h = cell(svc, "OIS_MAIN!J2", u)
        assert [ppk(svc, u, "AJ", r) for r in (3, 4, 5, 6)] == [1.0, N_DAYS, h, L0]
        assert ppk(svc, u, "AJ", 7) == math.log(1 + h / 365) - math.log(1 + L0 / 365)
        assert ppk(svc, u, "AJ", 8) == (h / 365) ** 2 - (L0 / 365) ** 2
        e = by_hand(svc, u)
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            a, b = day(svc, u, k), day(svc, u, k + 1)
            assert ppk(svc, u, "AE", r) == e(a) and ppk(svc, u, "AF", r) == e(b), k
            assert ppk(svc, u, "AG", r) == e(b) - e(a), k
            if a >= N_DAYS:
                assert ppk(svc, u, "AG", r) == 0.0, k
        # (the replay's windows: 37 → 79 wholly before N, 79 → 135 across it)
        assert (day(svc, u, 0), day(svc, u, 1), day(svc, u, 2)) == (37.0, 79.0, 135.0)
        x = (h - L0) / 365                                                              # ~ the gap's growth a day
        assert ppk(svc, u, "AG", 3) == pytest.approx(42 * x, rel=0.01) and ppk(svc, u, "AG", 4) == pytest.approx(21 * x, rel=0.01)
        # a date before the spot: no stretch (n taken as 0)
        put(svc, u, {"OIS_MAIN!M3": -5.0})
        assert ppk(svc, u, "AJ", 4) == 0.0 and all(ppk(svc, u, "AG", ex.PPK_FIRST + k) == 0.0 for k in range(WINDOWS))
    finally:
        svc.reset_inputs(u, "tto")


def test_on_a_rate_is_measured_on_the_normal_path(svc):
    """On, a window's rate typed: its O/N solves d·ln(1 + x) − W·x² = ln(1 + R·d/365) − (its part before N) - the normal
    path's (bisection) -; the first window's base is REF, a later one's the window before's market rate on the normal
    path; the market's own step the same way.  A window wholly after N keeps its O/N of off."""
    off, u = svc.login("Norm ölçü kapalı")["user"], svc.login("Norm ölçü açık")["user"]
    try:
        rates = {k: "35,5" for k in range(WINDOWS)}
        for user in (off, u):
            put(svc, user, {"EK_PPK!G%d" % (ex.PPK_FIRST + k): v for k, v in rates.items()})
        put_switch(svc, u)
        e = by_hand(svc, u)
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            a, b = day(svc, u, k), day(svc, u, k + 1)
            d, w, part = ppk(svc, u, "E", r), term(svc, u, k), e(b) - e(a)
            x = solve(lambda v: d * math.log(1 + v) - w * v * v - (math.log(1 + 0.355 * d / 365) - part))
            assert ppk(svc, u, "K", r) == pytest.approx(365 * x, rel=0, abs=1e-13), k
            fx = solve(lambda v: d * math.log(1 + v) - w * v * v - (math.log(1 + ppk(svc, u, "F", r) * d / 365) - part))
            if k == 0:
                assert ppk(svc, u, "J", r) == L0 and ppk(svc, u, "H", r) == ppk(svc, off, "H", r)
            else:
                pa = day(svc, u, k - 1)
                pd, pw, prev_part = ppk(svc, u, "I", r), term(svc, u, k - 1), e(a) - e(pa)
                px = solve(lambda v: pd * math.log(1 + v) - pw * v * v - (math.log(1 + ppk(svc, u, "H", r) * pd / 365) - prev_part))
                assert ppk(svc, u, "J", r) == pytest.approx(365 * px, rel=0, abs=1e-13), k
            assert ppk(svc, u, "L", r) == pytest.approx((ppk(svc, u, "K", r) - ppk(svc, u, "J", r)) * 1e4, abs=1e-12)
            assert ppk(svc, u, "M", r) == pytest.approx((365 * fx - ppk(svc, u, "J", r)) * 1e4, abs=1e-8), k
            if a >= N_DAYS:
                assert ppk(svc, u, "K", r) == ppk(svc, off, "K", r), k                   # (no part: the same O/N)
            else:
                assert ppk(svc, u, "K", r) < ppk(svc, off, "K", r) - 1e-4, k            # (the gap taken off)
            if k and day(svc, u, k - 1) >= N_DAYS:
                assert ppk(svc, u, "J", r) == ppk(svc, off, "J", r), k                   # (the window before: no part)
        # the market's rates, the two curves and the windows' dates are the same either way
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            assert [ppk(svc, u, c, r) for c in "CDEFHI"] == [ppk(svc, off, c, r) for c in "CDEFHI"]
    finally:
        svc.reset_inputs(u, "tto")
        svc.reset_inputs(off, "tto")


def test_on_with_no_gap_only_the_first_base_moves(svc):
    """On with the normal TLREF at today's (gap 0): every part before N is 0, so every O/N, every later base, the model's
    window rate and the PPK basamak path are the formulas of before, bit for bit; only the first window's base is REF -
    today's TLREF then - instead of the stub's O/N (and so the first step)."""
    u = svc.login("Norm fark yok")["user"]
    try:
        typed_some(svc, u)
        h = cell(svc, "OIS_MAIN!J2", u)
        put_switch(svc, u, l0=h)
        assert ppk(svc, u, "AJ", 3) == 1.0 and ppk(svc, u, "AJ", 7) == 0.0 and ppk(svc, u, "AJ", 8) == 0.0
        assert all(ppk(svc, u, "AG", ex.PPK_FIRST + k) == 0.0 for k in range(WINDOWS))
        bj = raw_bj()
        book = svc.books["tto"]
        typed = svc.et.call(lambda: dict(svc._overlay(u, book)))
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            w = ex.PPK_WINDOWS[0] + k
            assert cell(svc, "OIS_MAIN!BJ%d" % w, u) == at_cell(svc, u, "OIS_MAIN", "BJ%d" % w, bj[w])
            for col, text in before_window(r).items():
                if book.cell("EK_PPK!%s%d" % (col, r)) in typed or (k == 0 and col in "JM"):
                    continue
                assert ppk(svc, u, col, r) == at_cell(svc, u, ex.PPK_SHEET, "%s%d" % (col, r), text), (col, r)
        for k in range(PAIRS):
            r = ex.PPK_FIRST + k
            for col, text in before_pair(r).items():
                if book.cell("EK_PPK!%s%d" % (col, r)) not in typed:
                    assert ppk(svc, u, col, r) == at_cell(svc, u, ex.PPK_SHEET, "%s%d" % (col, r), text), (col, r)
        stub = at_cell(svc, u, ex.PPK_SHEET, "J3", before_window(3)["J"])
        assert ppk(svc, u, "J", 3) == h != stub
        assert ppk(svc, u, "L", 3) == pytest.approx((ppk(svc, u, "K", 3) - h) * 1e4, abs=1e-12)
        cv = curves(svc, u)
        assert cv["norm"] is not None and cv["norm"].gap == 0.0
        assert (cv["shape"].knots, cv["shape"].rates) == model_path(svc, u)
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== on: the page, the chat, the ways back
def test_on_the_page_and_the_chat_give_the_same_step(svc):
    """On, Broker Chat's step of a meeting swap is the page's to the bp's last digit: the same base (REF for the first
    window, the window before's market on the normal path after it), the same part before N, the same conversion; the
    market's own step too.  The chat says the normalization's date and gap, and whether its base is REF."""
    u = svc.login("Norm chat")["user"]
    try:
        for n in (N_DAYS, 60.0):
            put_switch(svc, u, n=n)
            put(svc, u, {"EK_PPK!G3": "36,5", "EK_PPK!G4": "35", "EK_PPK!G5": "34,25"})
            lines = chat(svc, u, "10:00:00 dec mpc 36.50/37.00\n10:01:00 jan27 mpc 35.00/35.20\n10:02:00 mar27 mpc 34.25/34.50")
            spot = cell(svc, "OIS_MAIN!B2", u)
            for said, r in (("dec", 3), ("jan27", 4), ("mar27", 5)):
                imp = lines[said]["implied"]
                assert ppk(svc, u, "L", r) == pytest.approx(imp["bid"], abs=1e-9), (n, said)
                assert ppk(svc, u, "M", r) == pytest.approx(imp["model"], abs=1e-9), (n, said)
                assert imp["prev_on"] == pytest.approx(ppk(svc, u, "J", r) * 100, rel=1e-14)
                assert imp["prev"] == pytest.approx(ppk(svc, u, "H", r) * 100, rel=1e-14)
                assert imp["norm"] == {"date": dt.date.fromordinal(dt.date(1899, 12, 30).toordinal() + int(spot + n)).isoformat(),
                                       "gap": pytest.approx((cell(svc, "OIS_MAIN!J2", u) - L0) * 1e4, rel=1e-12),
                                       "ref": pytest.approx(L0 * 100, rel=1e-15), "base_ref": r == 3}
            assert lines["dec"]["implied"]["prev_on"] == pytest.approx(L0 * 100, rel=1e-15)
            # the market's own rate typed gives the market's own step, both ways
            for k in range(WINDOWS):
                put(svc, u, {"EK_PPK!G%d" % (ex.PPK_FIRST + k): ppk(svc, u, "F", ex.PPK_FIRST + k)})
                assert ppk(svc, u, "L", ex.PPK_FIRST + k) == pytest.approx(ppk(svc, u, "M", ex.PPK_FIRST + k), abs=1e-9), k
            svc.reset_inputs(u, "tto")
    finally:
        svc.reset_inputs(u, "tto")


def test_on_every_way_back_stays_the_exact_inverse(svc):
    """On, both tables two-way as before: a step typed gives the rate (the actual window's: the part before N added back)
    whose step, typed back, is the step; an O/N typed gives the rate whose O/N it is; a later window's rate, O/N or step
    typed gives the spread that gives it back (1e-9 bp, 1e-12 for rates)."""
    u = svc.login("Norm iki yön")["user"]
    try:
        put_switch(svc, u)
        e = by_hand(svc, u)
        for k in (0, 1, 2, 7):
            r = ex.PPK_FIRST + k
            put(svc, u, {"EK_PPK!L%d" % r: "-37,5"})
            rate, base = ppk(svc, u, "G", r), ppk(svc, u, "J", r)
            d, w = ppk(svc, u, "E", r), term(svc, u, k)
            part = e(day(svc, u, k + 1)) - e(day(svc, u, k))
            assert rate == pytest.approx(pk.window_rate(base - 0.00375, d, w, part), abs=1e-15)
            put(svc, u, {"EK_PPK!G%d" % r: rate})
            assert ppk(svc, u, "L", r) == pytest.approx(-37.5, abs=1e-9), k
            assert ppk(svc, u, "K", r) == pytest.approx(base - 0.00375, abs=1e-12), k
            put(svc, u, {"EK_PPK!K%d" % r: "0,331"})
            put(svc, u, {"EK_PPK!G%d" % r: ppk(svc, u, "G", r)})
            assert ppk(svc, u, "K", r) == pytest.approx(0.331, abs=1e-12), k
        for k in (0, 1, 5):
            r = ex.PPK_FIRST + k
            for col, v in (("T", 0.3412), ("U", 0.332), ("V", 12.5)):
                put(svc, u, {"EK_PPK!%s%d" % (col, r): v})
                spread = ppk(svc, u, "S", r)
                put(svc, u, {"EK_PPK!S%d" % r: spread})
                assert ppk(svc, u, col, r) == pytest.approx(v, abs=1e-9 if col == "V" else 1e-12), (k, col)
                # the later window's own table agrees: its rate typed there gives the same step
                put(svc, u, {"EK_PPK!G%d" % (r + 1): ppk(svc, u, "T", r)})
                assert ppk(svc, u, "L", r + 1) == pytest.approx(ppk(svc, u, "V", r), abs=1e-9), (k, col)
                put(svc, u, {"EK_PPK!G%d" % (r + 1): ""})
    finally:
        svc.reset_inputs(u, "tto")


def test_on_the_models_window_rate_gives_its_tlref_back(svc):
    """On, "İma oran (model)" is the model's actual window rate - Motor's TLREF of the window compounded its way, plus its
    part before N -, so typed back into either table it gives the model's TLREF as its O/N (1e-12), its steps the model's;
    the first one from REF.  "Boot − İma" compares the market with it."""
    u = svc.login("Norm model")["user"]
    try:
        put_switch(svc, u)
        e = by_hand(svc, u)
        bj = [cell(svc, "OIS_MAIN!BJ%d" % (ex.PPK_WINDOWS[0] + k), u) for k in range(WINDOWS)]
        tlref = [cell(svc, "Motor!K%d" % (4 + k), u) for k in range(WINDOWS + 1)]
        for k in range(WINDOWS):
            d, w = ppk(svc, u, "E", ex.PPK_FIRST + k), term(svc, u, k)
            part = e(day(svc, u, k + 1)) - e(day(svc, u, k))
            assert bj[k] == pytest.approx(pk.window_rate(tlref[k + 1], d, w, part), rel=0, abs=1e-15), k
            w84 = ex.PPK_WINDOWS[0] + k
            assert cell(svc, "OIS_MAIN!M%d" % w84, u) == pytest.approx((cell(svc, "OIS_MAIN!D%d" % w84, u) - bj[k]) * 1e4, abs=0.05 + 1e-9)
        put(svc, u, {"EK_PPK!G%d" % (ex.PPK_FIRST + k): bj[k] for k in range(WINDOWS)})
        put(svc, u, {"EK_PPK!T%d" % (ex.PPK_FIRST + k): bj[k + 1] for k in range(PAIRS)})
        for k in range(WINDOWS):
            assert ppk(svc, u, "K", ex.PPK_FIRST + k) == pytest.approx(tlref[k + 1], abs=1e-12), k
        for k in range(PAIRS):
            assert ppk(svc, u, "U", ex.PPK_FIRST + k) == pytest.approx(tlref[k + 2], abs=1e-12), k
        assert ppk(svc, u, "L", ex.PPK_FIRST) == pytest.approx((tlref[1] - L0) * 1e4, abs=1e-8)
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== on: the PPK basamak curve
def test_on_the_ppk_curve_is_the_normal_path_plus_the_gap_and_reprices_every_quote(svc):
    """On, the PPK basamak path is the model's + the gap before N (a knot at N; a meeting before N moves both), calibrated
    as before: every OIS quote and every offshore quote comes back; the calibrated O/N drops by the gap at N.  Bootstrap
    (Murex's MTM) never moves: its curve, Motor's nodes and the 'MPC OIS' market of a Bootstrap user are off's."""
    off, u = svc.login("Norm eğri kapalı")["user"], svc.login("Norm eğri açık")["user"]
    try:
        put_switch(svc, u)
        gap = cell(svc, "OIS_MAIN!J2", u) - L0
        a, b = curves(svc, off), curves(svc, u)
        assert not b["errors"] and (b["norm"].days, b["norm"].ref, b["norm"].gap) == (N_DAYS, L0, gap)
        assert N_DAYS in b["shape"].knots and N_DAYS not in a["shape"].knots
        # the user's model path (Motor's: the normal one, the switch on) + the gap up to N - its meetings at 37 and 79 days
        # (inside the stretch) move both
        normal = pk.StepCurve(*model_path(svc, u))
        assert (day(svc, u, 0), day(svc, u, 1)) == (37.0, 79.0)
        for t in (0.0, 1.0, 36.0, 37.0, 78.0, 79.0, 99.0, 100.0, 101.0, 134.0, 135.0, 400.0):
            assert b["shape"].overnight(t) == (normal.overnight(t) + gap if t < N_DAYS else normal.overnight(t)), t
        for q in b["quotes"]:
            assert pk.par(b["ppk"], q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12), q.name
        for q in b["off_quotes"]:
            assert pk.par(b["off_ppk"], q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12), q.name
        assert {d for d, _ in b["ppk"].steps()} <= set(b["shape"].knots) | {q.end for q in b["quotes"]}
        assert b["ppk"].overnight(N_DAYS - 1) - b["ppk"].overnight(N_DAYS) == pytest.approx(gap, abs=1e-15)
        assert any(abs(a["ppk"].df(t) - b["ppk"].df(t)) > 1e-7 for t in range(93, 182))     # (between 3M and 6M)
        # Bootstrap never moves
        assert (a["boot"].days, a["boot"].lndf) == (b["boot"].days, b["boot"].lndf)
        for r in range(88, 131):
            assert cell(svc, "Motor!I%d" % r, u) == cell(svc, "Motor!I%d" % r, off)
        for r in range(ex.PPK_WINDOWS[0], ex.PPK_WINDOWS[1] + 1):
            assert cell(svc, "OIS_MAIN!D%d" % r, u) == cell(svc, "OIS_MAIN!D%d" % r, off)
    finally:
        svc.reset_inputs(u, "tto")


def test_on_a_ppk_users_own_curve_follows_and_says_so(svc):
    """A user on PPK basamak with the switch on gets PPK cells of their own, made with it: the offshore node table has a
    node at N (seen from the FX spot); the sheet's status and the top bar's badge say "normalleşme açık".  The desk's PPK
    cells (made for nobody) and another PPK user's stay off's."""
    u, other = svc.login("Norm PPK açık")["user"], svc.login("Norm PPK kapalı")["user"]
    try:
        for user in (u, other):
            svc.set_interp(user, "ppk")
        put_switch(svc, u)
        cv = curves(svc, u)
        shift = cv["fx_shift"]
        days_on = [cell(svc, "EK_INTERP!I%d" % r, u) for r in range(ex.INTERP_OFF_FIRST, ex.INTERP_OFF_LAST + 1)]
        days_off = [cell(svc, "EK_INTERP!I%d" % r, other) for r in range(ex.INTERP_OFF_FIRST, ex.INTERP_OFF_LAST + 1)]
        assert N_DAYS - shift in days_on and N_DAYS - shift not in days_off
        assert cell(svc, "EK_INTERP!B3", u) == 1.0 and cell(svc, "EK_INTERP!B4", u) == 1.0
        status = cell(svc, "EK_INTERP!C2", u)
        n_date = (dt.date(1899, 12, 30) + dt.timedelta(days=int(cell(svc, "OIS_MAIN!B2", u) + N_DAYS))).strftime("%d.%m.%Y")
        gap_bp = "%d" % round((cell(svc, "OIS_MAIN!J2", u) - L0) * 1e4)
        assert status.startswith("PPK basamak: TLREF toplantılar arasında sabit, kotalara aynen oturur · normalleşme açık: "
                                 "TLREF normalleşme tarihi %s öncesinde normal patika + %s bp" % (n_date, gap_bp)), status
        assert "normalleşme" not in cell(svc, "EK_INTERP!C2", other)
        badge = svc.et.call(lambda: svc.interp.badge(u, svc._calc(u, svc.books["tto"])))
        assert badge["label"] == "Eğri: PPK basamak · normalleşme açık" and badge["norm"] is True
        assert "normalleşme" in badge["tip"]
        badge = svc.et.call(lambda: svc.interp.badge(other, svc._calc(other, svc.books["tto"])))
        assert badge["label"] == "Eğri: PPK basamak" and "norm" not in badge
        # the desk's (shared) PPK cells: made for nobody, off
        st = svc.et.call(svc.interp.refresh)
        assert st["curves"]["norm"] is None and N_DAYS not in st["curves"]["shape"].knots
    finally:
        for user in (u, other):
            svc.set_interp(user, "boot")
            svc.reset_inputs(user, "tto")


def test_shared_calculations_stay_off(svc):
    """With a user's switch on, the desk's calculation (nobody: alarms, quant, history, Günlük İşlemler) is off's: EK_PPK,
    the model's window rates and the curves read for nobody."""
    u = svc.login("Norm ortak")["user"]
    try:
        put_switch(svc, u)
        assert ppk(svc, u, "AJ", 3) == 1.0
        assert ppk(svc, None, "AJ", 3) == 0.0 and ppk(svc, None, "J", 3) != L0
        assert_off(svc, None, raw_bj())
        book = svc.books["tto"]
        idx = book.model.sheet_index
        cv = svc.et.call(lambda: pk.read(lambda s, r, c: book.engine.shared.get(idx[s], r, c)))
        assert cv["norm"] is None
    finally:
        svc.reset_inputs(u, "tto")


# ============================================================================== over HTTP (last: it stops the service)
def test_the_header_says_it_over_http(svc):
    """The top bar's curve badge of a PPK user with the switch on, as the browser gets it."""
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Norm HTTP")
        u = svc.login("Norm HTTP")["user"]
        assert c.post("/api/interp", json={"mode": "ppk"}, headers=h).json()["mode"] == "ppk"
        assert c.get("/api/header", headers=h).json()["interp"]["label"] == "Eğri: PPK basamak"
        put_switch(svc, u)
        got = c.get("/api/header", headers=h).json()["interp"]
        assert got["label"] == "Eğri: PPK basamak · normalleşme açık" and got["norm"] is True
        assert "normalleşme açık" in c.get("/api/interp", headers=h).json()["status"]
        assert c.post("/api/interp", json={"mode": "boot"}, headers=h).json()["mode"] == "boot"
