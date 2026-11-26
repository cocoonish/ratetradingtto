"""TLREF's normalization: the date the OIS market implies (v2, builder B; the desk, 26.11.2026: "Ois'in imply ettigi
normallesme noktasini da bulacagiz ... gunluk 1w 2w 1m hepsine bakip gunluk gunluk yurutup bulacagiz" and "implied rate
cutlarda 1m-2m'yi secebildigim gibi vadeleri de tikleyip secip ona gore ilerleyebilmeliyim 1w 2w dahil").

Every TRY business day after the OIS spot is tried as N - TLREF = the normal path + (today's − normal) before N, the
normal path L0 up to the first PPK meeting inside the ticked tenors and a fitted level after each - against the short OIS
quotes the user ticks (``extras._tto_norm_walk``, sheet EK_NORM; the block right of STUB İMA, OIS_MAIN!AO8:AS15).  The
checks build quotes from a known path with a calculation of their own (TLREF compounded as the MPC ima model does, on
Motor's own calendar) and read the day back; with the switch off nothing of before changes.

The switch and the normal TLREF (OIS_MAIN!L2:L4) are the switch builder's inputs (norm-ppk): where they are not declared
yet (this branch alone) the checks declare them on their own service as that builder does - a list, a date, a rate."""
from __future__ import annotations

import math
import os
import re

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from tto import extras as ex
from tto.inputs import InputError, parse_check, parse_input
from tto.server import create_app
from tto.xl import numfmt
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.values import serial_to_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = [t[0] for t in ex.NW_TENORS]
QUOTES = ["OIS_MAIN!AU13", "OIS_MAIN!AU14", "OIS_MAIN!D442", "OIS_MAIN!D443", "OIS_MAIN!D444"]
TICKS = ["OIS_MAIN!%s%d" % (ex.NW_TICK, ex.NW_FIRST_TENOR + j) for j in range(len(NAMES))]
#: the switch builder's inputs, as its page declares them (declared here only where they are not inputs yet)
SWITCH = (("OIS_MAIN!L2", dict(kind="list", options=["Kapalı", "Açık"])), ("OIS_MAIN!L3", dict(kind="date")),
          ("OIS_MAIN!L4", dict(kind="pct")))
L0, H = 0.355, 0.385                                   # a normal TLREF and today's: 300 bp of gap


@pytest.fixture(scope="module")
def svc(module_service):
    book = module_service.books["tto"]
    for ref, kw in SWITCH:
        if book.input_def(*book.cell(ref)) is None:
            book.declare(ref, scope="user", group="norm-switch", **kw)
    return module_service


# ============================================================================== an independent calculation
def calendar(svc):
    """Motor's daily calendar as the sheet has it: business day flags and Pcum, day 0 = the OIS spot."""
    book = svc.books["tto"]

    def read():
        calc = svc._calc(None, book)
        si = book.model.sheet_index["Motor"]
        return ([calc.get(si, r, 3) for r in range(528, 4229)], [calc.get(si, r, 6) for r in range(528, 4229)])

    flags, pcum = svc.et.call(read)
    return [f == 1.0 for f in flags], pcum


def days_of(svc):
    return [7.0, 14.0] + [cell(svc, "OIS_MAIN!E%d" % r) for r in (442, 443, 444)]


def piece(x, d, w):
    return d * math.log(1 + x / 365.0) - w * (x / 365.0) ** 2


def lng(P, T, n, levels, cuts, l0, gap):
    """ln G over [0, T): l0 before cuts[0], levels[k] from cuts[k], the gap added before day n."""
    a, b, x = [0] + list(cuts), list(cuts) + [10 ** 9], [l0] + list(levels)
    out = 0.0
    for s in range(len(a)):
        lo, hi = int(min(a[s], T)), int(min(b[s], T))
        if hi <= lo:
            continue
        m = min(max(lo, int(n)), hi)
        if m > lo:
            out += piece(x[s] + gap, m - lo, P[m] - P[lo])
        if hi > m:
            out += piece(x[s], hi - m, P[hi] - P[m])
    return out


def rate(P, T, *path):
    return (math.exp(lng(P, T, *path)) - 1) * 365.0 / T


def fitted(P, tenors, quotes, n, cuts, l0, gap, steps=12):
    """The levels after the meetings that fit the quotes best (rate misses, least squares; Gauss-Newton to the end with
    central differences) and the misses there."""
    k = len(cuts)
    x = [l0] * k
    for _ in range(steps if k else 0):
        e = [rate(P, T, n, x, cuts, l0, gap) - q for T, q in zip(tenors, quotes)]
        J = []
        for T in tenors:
            row = []
            for s in range(k):
                up, down = list(x), list(x)
                up[s] += 1e-6
                down[s] -= 1e-6
                row.append((rate(P, T, n, up, cuts, l0, gap) - rate(P, T, n, down, cuts, l0, gap)) / 2e-6)
            J.append(row)
        A = [[sum(J[j][p] * J[j][q] for j in range(len(J))) for q in range(k)] for p in range(k)]
        g = [sum(J[j][p] * e[j] for j in range(len(J))) for p in range(k)]
        d = solve(A, g)
        x = [x[s] - d[s] for s in range(k)]
    misses = [rate(P, T, n, x, cuts, l0, gap) - q for T, q in zip(tenors, quotes)]
    return x, misses


def solve(A, g):
    n = len(g)
    M = [list(A[i]) + [g[i]] for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(n):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [M[r][c] - f * M[i][c] for c in range(n + 1)]
    return [M[i][n] / M[i][i] for i in range(n)]


# ============================================================================== setting a case up
def case(svc, name, ticks, meetings=None, quotes=None, l0=L0, h=H, typed=None):
    """A user with the switch on, its normal TLREF and today's, the tenors ticked, the meetings' effective days (Motor!C5
    on, typed over by hand - the calendar itself left alone) and the quotes."""
    u = svc.login(("nw " + name)[:40])["user"]
    items = [{"ref": "OIS_MAIN!L2", "value": "Açık"}, {"ref": "OIS_MAIN!L4", "value": l0}, {"ref": "OIS_MAIN!J2", "value": h}]
    items += [{"ref": ref, "value": 1 if NAMES[j] in ticks else 0} for j, ref in enumerate(TICKS)]
    if typed is not None:
        items.append({"ref": "OIS_MAIN!L3", "value": typed})
    res = svc.set_inputs(u, "tto", items)
    assert res["errors"] == [], res["errors"]
    hand = [{"ref": "Motor!C%d" % (5 + k), "value": float(c)} for k, c in enumerate(meetings or [])]
    hand += [{"ref": ref, "value": q} for ref, q in zip(QUOTES, quotes or [])]
    if hand:
        res = svc.set_inputs(u, "tto", hand, allow_adhoc=True)
        assert res["errors"] == [], res["errors"]
    return u


def synthetic(svc, n, levels, cuts, l0=L0, h=H):
    """The five quotes a TLREF path prices: l0 + the gap before day n, l0 up to the first meeting, levels after each."""
    _, P = calendar(svc)
    return [rate(P, T, n, levels, cuts, l0, h - l0) for T in days_of(svc)]


def block(svc, user):
    """The block right of STUB İMA as the page shows it: {row: {column: cell}}."""
    p = next(p for p in svc.view(user, "ois")["panels"] if p["id"] == "B6")
    d = p["data"]
    return {r: dict(zip(d["c"], row)) for r, row in zip(d["r"], d["rows"])}


def day(svc, n):
    return cell(svc, "OIS_MAIN!B2") + n


# ============================================================================== the walk finds the day
#: (name, ticked, the meetings' effective days typed (Motor!C5 …), the day N, the levels after the meetings inside)
#: - the replay's meetings take effect on days 37 and 79 (Motor!C5:C6); the spot is Wednesday 04.11.2026; New Year's Day
#: (a Friday, the TRY list) is day 58, so Thursday 31.12's fixing runs four days, to Monday 04.01 (day 61)
CASES = (
    ("1W alone, past a weekend", ["1W"], None, 5, []),                       # Monday 09.11: Friday's three days stretched
    ("1W alone, before the weekend", ["1W"], None, 2, []),                   # Friday 06.11: its weekend normal
    ("1W+2W+1M, no meeting inside", ["1W", "2W", "1M"], None, 12, []),        # Monday 16.11
    ("2W+1M+2M, a step inside", ["2W", "1M", "2M"], [20, 79], 9, [0.33]),    # a meeting on day 20 (−250 bp), N Friday 13.11
    ("1M+2M+3M, across New Year's Day", ["1M", "2M", "3M"], [37, 120], 61, [0.33]),        # N Monday 04.01.2027
    ("1M+2M+3M, the day before the holiday", ["1M", "2M", "3M"], [37, 120], 57, [0.33]),    # N Thursday 31.12.2026
    ("all five, two steps inside", NAMES, [20, 45], 12, [0.34, 0.325]),
)


@pytest.mark.parametrize("name,ticks,meetings,n,levels", CASES, ids=[c[0] for c in CASES])
def test_the_walk_recovers_the_day(svc, name, ticks, meetings, n, levels):
    """Quotes made from a known path: the day back exactly, the model's rates at it the quotes (misses 0,0 bp), the date
    in use (L5) that day while none is typed; no tie said."""
    cuts = [c for c in (meetings or [37, 79]) if 0 < c < max(days_of(svc)[NAMES.index(t)] for t in ticks)]
    quotes = synthetic(svc, n, levels + [0.3] * 3, meetings or [37, 79])
    u = case(svc, name, ticks, meetings, quotes)
    assert len(levels) == len(cuts) or not levels
    assert cell(svc, "EK_NORM!B12", u) == 1.0 and cell(svc, "EK_NORM!B11", u) == len(cuts)
    assert cell(svc, "EK_NORM!E11", u) == day(svc, n) and cell(svc, "EK_NORM!E7", u) == 1.0
    assert cell(svc, "OIS_MAIN!L5", u) == day(svc, n)
    b = block(svc, u)
    assert b[ex.NW_DATE_ROW][ex.NW_QUOTE]["t"] == serial_to_date(day(svc, n)).strftime("%d.%m.%Y")
    assert b[ex.NW_DATE_ROW][ex.NW_MODEL]["t"] == "spot + %d gün" % n
    assert b[ex.NW_MSG_ROW][ex.NW_LABEL]["t"].startswith("Seçili vadelere en iyi uyan iş günü: spot + %d gün" % n)
    for j, label in enumerate(NAMES):
        r = ex.NW_FIRST_TENOR + j
        assert b[r][ex.NW_LABEL]["t"] == label and b[r][ex.NW_QUOTE]["v"] == quotes[j]
        if label in ticks:
            assert b[r][ex.NW_MODEL]["v"] == pytest.approx(quotes[j], abs=1e-11), (label, b[r])
            assert b[r][ex.NW_MISS]["t"] in ("0,0", "-0,0") and abs(b[r][ex.NW_MISS]["v"]) < 1e-6
        else:
            assert b[r][ex.NW_MODEL]["t"] == "" and b[r][ex.NW_MISS]["t"] == ""
    # the levels fitted after the meetings inside are the path's
    last = int(cell(svc, "EK_NORM!E9", u)) + ex.NW_R - 1
    for s, level in enumerate(levels):
        assert cell(svc, "EK_NORM!%s%d" % (ex.NW_COLS["x2"][s], last), u) == pytest.approx(level, abs=1e-10)


def test_every_day_tried_against_an_independent_calculation(svc):
    """Two meetings inside, all five tenors: on every business day tried (and "sonrası") the model's rates and the sum of
    squared misses are those of a calculation of its own - its own pieces, Newton to the end on the rate misses."""
    flags, P = calendar(svc)
    days = days_of(svc)
    cuts, levels, n_true = [20, 45], [0.34, 0.325], 23
    quotes = synthetic(svc, n_true, levels + [0.3], cuts + [135])
    u = case(svc, "her gün", NAMES, cuts, quotes)
    tried = [n for n in range(1, int(days[-1])) if flags[n]] + [int(days[-1])]
    rows = list(range(ex.NW_R, ex.NW_R + len(tried) - 1)) + [ex.NW_AFTER]
    assert [cell(svc, "EK_NORM!B%d" % r, u) for r in rows] == [float(n) for n in tried]
    assert all(cell(svc, "EK_NORM!D%d" % r, u) == 1.0 for r in rows)
    assert cell(svc, "EK_NORM!D%d" % (ex.NW_R + len(tried) - 1), u) == 0.0          # (the tenor's end itself: "sonrası")
    scores, worst = [], []
    for n, r in zip(tried, rows):
        x, misses = fitted(P, days, quotes, n, cuts, L0, H - L0)
        ssr = sum(m * m for m in misses)
        scores.append((ssr, n))
        got = cell(svc, "EK_NORM!%s%d" % (ex.NW_COLS["ssr"][0], r), u)
        assert got == pytest.approx(ssr, rel=1e-6, abs=1e-20), n
        worst.append(max(abs(cell(svc, "EK_NORM!%s%d" % (ex.NW_COLS["rate"][j], r), u) - (quotes[j] + misses[j]))
                         for j in range(len(days))))
    # (two Gauss-Newton steps: a day far off the quotes - misses of tens of bp, where the step on the rate misses converges
    # only linearly - is fitted to 0,0001 bp at worst, which moves its sum of squares by ~1e-11 (neighbouring days differ
    # by ~1e-9); the best day to 1e-8 bp)
    assert max(worst) < 1e-8 and worst[tried.index(n_true)] < 1e-12, worst
    assert min(scores)[1] == n_true and cell(svc, "EK_NORM!E6", u) == n_true and cell(svc, "EK_NORM!E7", u) == 1.0
    assert sorted(scores)[1][0] > 1e-12                                       # (the next best day is far off: no tie)


def test_two_meetings_inside_need_three_tenors(svc):
    """The ticked tenors no more than the unknown levels (2M and 3M; the meetings of days 37 and 79 inside): no date, the
    message says why and how many to tick; nothing ticked, or no normal TLREF: the same."""
    u = case(svc, "eksik", ["2M", "3M"])
    assert cell(svc, "EK_NORM!B12", u) == 5.0 and cell(svc, "EK_NORM!E11", u) == "" and cell(svc, "OIS_MAIN!L5", u) == ""
    b = block(svc, u)
    assert b[ex.NW_DATE_ROW][ex.NW_QUOTE]["t"] == "–"
    assert b[ex.NW_MSG_ROW][ex.NW_LABEL]["t"] == ("Seçili vadeler tarihi belirleyemiyor: 2 vade, 2 bilinmeyen seviye (vadelerin "
                                                  "içindeki PPK toplantılarından sonraki normal TLREF) - en az 3 vade seçin.")
    assert all(b[ex.NW_FIRST_TENOR + j][ex.NW_MODEL]["t"] == "" for j in range(5))
    res = svc.set_inputs(u, "tto", [{"ref": ref, "value": 0} for ref in TICKS])
    assert res["errors"] == [] and cell(svc, "EK_NORM!B12", u) == 3.0
    assert cell(svc, "OIS_MAIN!%s%d" % (ex.NW_LABEL, ex.NW_MSG_ROW), u) == "Tarih için kotası olan en az bir vade seçin."
    # no normal TLREF read (the switch builder's L4 has a default - its policy rate gone, say): typed over by hand, a text
    u2 = case(svc, "normalsiz", ["1W"])
    assert svc.set_inputs(u2, "tto", [{"ref": "EK_NORM!B7", "value": "yok"}], allow_adhoc=True)["errors"] == []
    assert cell(svc, "EK_NORM!B12", u2) == 2.0 and cell(svc, "EK_NORM!E11", u2) == "" and cell(svc, "OIS_MAIN!L5", u2) == ""
    assert "Normal TLREF (L4)" in cell(svc, "OIS_MAIN!%s%d" % (ex.NW_LABEL, ex.NW_MSG_ROW), u2)


def test_a_day_past_the_ticked_tenors(svc):
    """TLREF normal only after 1M ends (day 40): every ticked tenor priced with the gap all the way - "sonrası" fits, the
    day is none ("normalleşme seçili vadelerin sonrasında"); the model's rates are that fit's."""
    quotes = synthetic(svc, 40, [], [])
    u = case(svc, "sonrası", ["1W", "2W", "1M"], None, quotes)
    assert cell(svc, "EK_NORM!E10", u) == 1.0 and cell(svc, "EK_NORM!E11", u) == "" and cell(svc, "OIS_MAIN!L5", u) == ""
    b = block(svc, u)
    msg = b[ex.NW_MSG_ROW][ex.NW_LABEL]["t"]
    assert msg.startswith("Normalleşme seçili vadelerin sonrasında: TLREF, seçili en uzun vadenin (1M, 04.12.2026) sonuna")
    assert b[ex.NW_DATE_ROW][ex.NW_QUOTE]["t"] == "–" and b[ex.NW_DATE_ROW][ex.NW_MODEL]["t"] == ""
    for j in range(3):
        assert b[ex.NW_FIRST_TENOR + j][ex.NW_MODEL]["v"] == pytest.approx(quotes[j], abs=1e-12)


def test_a_tie_is_said_and_the_earliest_day_taken(svc):
    """1M, 2M and 3M with the meetings of days 37 and 79 inside, TLREF normal on day 50: the levels after the meetings take
    the gap up from day 30 on (1M's end) - every day from there fits as well; the earliest is the date, the message says the
    ticked tenors do not fix it."""
    quotes = synthetic(svc, 50, [0.33, 0.31, 0.3], [37, 79, 135])
    u = case(svc, "eşit", ["1M", "2M", "3M"], None, quotes)
    assert cell(svc, "EK_NORM!E6", u) == 30.0 and cell(svc, "EK_NORM!E7", u) > 10 and cell(svc, "EK_NORM!E8", u) == 92.0
    assert cell(svc, "EK_NORM!E11", u) == day(svc, 30)
    msg = cell(svc, "OIS_MAIN!%s%d" % (ex.NW_LABEL, ex.NW_MSG_ROW), u)
    assert msg.startswith("En iyi uyum 04.12.2026 ve sonrasındaki her günde aynı") and "en erken gün alındı" in msg


def test_a_meeting_added_to_the_calendar_is_read_where_it_lands(svc):
    """Nothing is kept per meeting row: an extraordinary PPK meeting on Friday 20.11.2026 (the calendar's rows move) takes
    effect on Monday 23.11 (day 19) - inside 1M now, a level of its own fitted after it; the day is found as before."""
    h = svc.history
    start = h.meetings()
    quotes = synthetic(svc, 9, [0.33, 0.3, 0.3], [19, 37, 79])
    u = case(svc, "takvim", ["1W", "2W", "1M"], None, quotes)
    miss = "OIS_MAIN!%s%d" % (ex.NW_MISS, ex.NW_FIRST_TENOR + 2)                             # 1M's (bp)
    assert cell(svc, "EK_NORM!B11", u) == 0.0 and abs(cell(svc, miss, u)) > 10         # (without it: no step, 1M missed)
    try:
        res = h.set_calendar(u, ["20.11.2026"] + start[:-1])
        assert res["parked"]["meetings"] == []
        assert cell(svc, "Motor!C5", u) == 19.0 and cell(svc, "EK_NORM!B25", u) == 19.0
        assert cell(svc, "EK_NORM!B11", u) == 1.0 and cell(svc, "EK_NORM!E11", u) == day(svc, 9) and cell(svc, "EK_NORM!E7", u) == 1.0
        assert abs(cell(svc, miss, u)) < 1e-6
        last = int(cell(svc, "EK_NORM!E9", u)) + ex.NW_R - 1
        assert cell(svc, "EK_NORM!%s%d" % (ex.NW_COLS["x2"][0], last), u) == pytest.approx(0.33, abs=1e-10)
    finally:
        h.set_calendar(u, start)
    assert cell(svc, "Motor!C5", u) == 37.0


def test_the_date_in_use_falls_back_to_the_ois_implied_date(svc):
    """L5 (the date in use): the date typed (L3) when there is one; with L3 blank the OIS-implied date; switched off,
    nothing - whatever is typed."""
    quotes = synthetic(svc, 12, [], [])
    u = case(svc, "kullanılan", ["1W", "2W", "1M"], None, quotes, typed="20.11.2026")
    typed = cell(svc, "OIS_MAIN!L3", u)
    assert cell(svc, "OIS_MAIN!L5", u) == typed != day(svc, 12) and cell(svc, "EK_NORM!E11", u) == day(svc, 12)
    svc.reset_inputs(u, "tto", ["OIS_MAIN!L3"])
    assert cell(svc, "OIS_MAIN!L5", u) == day(svc, 12)
    assert svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!L2", "value": "Kapalı"}, {"ref": "OIS_MAIN!L3", "value": "20.11.2026"}])["errors"] == []
    assert cell(svc, "OIS_MAIN!L5", u) == "" and cell(svc, "EK_NORM!E11", u) == "" and cell(svc, "EK_NORM!B12", u) == 0.0


# ============================================================================== switched off: the page as before
def _panel(svc, user, p):
    book = svc.books["tto"]
    v = svc.view_index["ois"]

    def run():
        calc = svc._calc(user, book)
        overlay = svc._overlay(user, book) if user else None
        return svc._panel(p, v, book, calc, svc.renderers["tto"], numfmt.get_locale("tr"), overlay, user, "OIS_MAIN", [], False,
                          False)

    return svc.et.call(run)


def test_off_stub_ima_reads_as_before(svc):
    """Switched off (nobody's switch, a user's own off, a user with ticks of their own): STUB İMA's panel is what its old
    range made of it, cell for cell - the block's columns empty and dropped, no tick box offered - and L5 empty."""
    b6 = next(p for p in svc.view_index["ois"]["panels"] if p["id"] == "B6")
    assert b6["range"] == "AJ8:AS15"
    old = dict(b6, range="AJ8:AN15")
    u = svc.login("normwalk kapalı")["user"]
    assert svc.set_inputs(u, "tto", [{"ref": TICKS[3], "value": 1}, {"ref": TICKS[0], "value": 0}])["errors"] == []
    for user in (None, u):
        new, before = _panel(svc, user, b6), _panel(svc, user, old)
        assert new.pop("range") == "AJ8:AS15" and before.pop("range") == "AJ8:AN15"
        assert new == before and new["data"]["c"] == ["AJ", "AK", "AL", "AM", "AN"], user
        assert cell(svc, "OIS_MAIN!L5", user) == "" and cell(svc, "EK_NORM!B4", user) == 0.0
        assert all(cell(svc, "OIS_MAIN!%s%d" % (c, r), user) in ("", None) for c in "AO AQ AR AS".split() for r in range(8, 16))
    assert cell(svc, TICKS[3], u) == 1.0                                      # (kept for when the switch is on again)


def test_tick_boxes_on_the_page(svc):
    """On: a tick box per tenor - a per-user input of kind "check", 1W, 2W, 1M ticked by default, a tick of one's own
    marked as changed; the captions, quotes and labels beside them."""
    u = case(svc, "kutular", ["1W", "2W", "1M"])
    svc.reset_inputs(u, "tto", TICKS)                                         # (the defaults)
    b = block(svc, u)
    assert [b[ex.NW_HEAD][c]["t"] for c in ("AO", "AP", "AQ", "AR", "AS")] == ["OIS ima normalleşme", "Seç", "Kota", "Model",
                                                                              "Fark bp"]
    boxes = [b[ex.NW_FIRST_TENOR + j][ex.NW_TICK] for j in range(5)]
    assert [(x["i"], x["ik"], x["v"], x.get("m")) for x in boxes] == [("u", "check", 1.0, None)] * 3 + [("u", "check", 0.0, None)] * 2
    assert svc.set_inputs(u, "tto", [{"ref": TICKS[4], "value": "evet"}])["errors"] == []
    x = block(svc, u)[ex.NW_FIRST_TENOR + 4][ex.NW_TICK]
    assert x["v"] == 1.0 and x["m"] == 1 and x["fx"] == 1
    assert block(svc, u)[ex.NW_FIRST_TENOR + 4][ex.NW_MODEL]["t"] != ""      # (3M now in the fit)
    nobody = block(svc, None)
    assert "AP" not in next(iter(nobody.values())) and ex.NW_FIRST_TENOR in nobody


def test_tick_boxes_over_http(svc):
    """POST /api/inputs: a tick is the user's own (another user's page keeps the default), kept in the store and read back
    when the user's values are read again; Delete (blank) - its default; anything but 1 / 0 is refused, said in Turkish."""
    client = TestClient(create_app(service=svc))                              # (no "with": the module's service stays up)
    h, other = auth(svc, "normwalk http"), auth(svc, "normwalk http komşu")
    user = svc.login("normwalk http")["user"]
    for headers in (h, other):
        r = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "OIS_MAIN!L2", "value": "Açık"}]}, headers=headers)
        assert r.status_code == 200 and r.json()["errors"] == []
    r = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": TICKS[3], "value": "1"}]}, headers=h)
    assert r.status_code == 200 and r.json()["applied"] == 1 and r.json()["errors"] == []

    def tick(headers, j):
        page = client.get("/api/view/ois?panels=B6", headers=headers).json()
        d = next(p for p in page["panels"] if p["id"] == "B6")["data"]
        return d["rows"][d["r"].index(ex.NW_FIRST_TENOR + j)][d["c"].index(ex.NW_TICK)]

    mine, theirs = tick(h, 3), tick(other, 3)
    assert (mine["v"], mine["ik"], mine["m"]) == (1.0, "check", 1) and (theirs["v"], theirs.get("m")) == (0.0, None)
    assert svc.store.user_inputs(user, "tto")[("tto", TICKS[3])] == 1.0
    svc._overlays.pop((user, "tto"), None)                                    # (the user's values read again from the store)
    assert cell(svc, TICKS[3], user) == 1.0
    info = client.get("/api/cell", params={"book": "tto", "ref": TICKS[3]}, headers=h).json()
    assert info["input"]["kind"] == "check" and info["input"]["scope"] == "user"
    r = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": TICKS[3], "value": "2"}]}, headers=h)
    assert r.json()["applied"] == 0 and "tik kutusu: 1 (seçili) ya da 0 (seçili değil)" in r.json()["errors"][0]
    r = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": TICKS[3], "value": ""}, {"ref": TICKS[0], "value": "0"}]},
                    headers=h)
    assert r.json()["errors"] == [] and tick(h, 3)["v"] == 0.0 and "m" not in tick(h, 3) and tick(h, 0)["v"] == 0.0
    r = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": TICKS[0], "value": ""}]}, headers=h)
    assert tick(h, 0)["v"] == 1.0 and ("tto", TICKS[0]) not in svc.store.user_inputs(user, "tto")
    assert client.post("/api/inputs", json={"book": "tto", "items": [{"ref": TICKS[0], "value": "1"}]}, headers=ANON).status_code == 401


def test_a_tick_is_one_or_zero():
    """What a tick box takes: 1 / 0 (a click), TRUE / FALSE, "evet" / "hayır", "x" / "✓"; empty is its default; nothing else."""
    for raw, want in ((1, 1.0), (0, 0.0), (True, 1.0), (False, 0.0), ("1", 1.0), ("0", 0.0), ("1,0", 1.0), (" evet ", 1.0),
                      ("Hayır", 0.0), ("DOĞRU", 1.0), ("yanlış", 0.0), ("x", 1.0), ("✓", 1.0), ("", None), ("  ", None)):
        assert parse_check(raw) == want and parse_input(raw, kind="check") == want, raw
    assert parse_input(None, kind="check") is None
    for raw in (2, -1, 0.5, "2", "evetx", "%50", "açık"):
        with pytest.raises(InputError, match="tik kutusu"):
            parse_input(raw, kind="check")


# ============================================================================== what the addition writes, and when it does not
def raw_model():
    return Model.load(os.path.join(ROOT, "models", "tto.json.gz"))


def test_the_addition_writes_its_own_cells_only(monkeypatch):
    """The workbook with every addition but this one, against all of them: the same sheets but EK_NORM, the same formulas,
    values and looks everywhere but OIS_MAIN's block right of STUB İMA (AO8:AS15, empty in the workbook) and L5 (the date
    in use: empty in this branch alone, the switch builder's formula once merged - widened) - and one conditional number
    format, the tick boxes' while off."""
    full = raw_model()
    assert ex.apply("tto", full) == []
    without = raw_model()
    monkeypatch.setitem(ex._BUILDERS, "tto", tuple(b for b in ex._BUILDERS["tto"] if b[0] != ex.NW_NAME))
    assert ex.apply("tto", without) == []
    assert [s.name for s in full.sheets if s.name != ex.NW_SHEET] == [s.name for s in without.sheets]

    def cells(model, sh):
        out = {rc: ("=", model.templates[t]) for rc, t in sh.fml.items()}
        out.update({rc: ("c", v) for rc, v in sh.consts.items()})
        return out

    def rules(model, sh):
        """A sheet's conditional formats, each with its style's contents (the model's list of them is shared)."""
        return [dict(x, dxf=model.dxfs[x["dxf"]] if isinstance(x.get("dxf"), int) else x.get("dxf")) for x in sh.cf]

    block = {r * COLS + c for r in range(8, 16) for c in range(41, 46)}            # AO8:AS15
    used = parse_a1(ex.NW_USED)
    new = block | {used}
    others = [s for s in full.sheets if s.name != ex.NW_SHEET]
    for a, b in zip(others, without.sheets):
        ca, cb = cells(full, a), cells(without, b)
        if a.name != "OIS_MAIN":
            assert ca == cb and a.styles == b.styles and a.comments == b.comments and rules(full, a) == rules(without, b), a.name
            continue
        assert set(ca) - set(cb) <= new and set(cb) <= set(ca) and ca[used] != cb.get(used)
        assert {rc: v for rc, v in ca.items() if rc not in new} == {rc: v for rc, v in cb.items() if rc not in new}
        assert {rc: x for rc, x in a.styles.items() if rc not in new} == {rc: x for rc, x in b.styles.items() if rc not in new}
        mine = [x for x in rules(full, a) if x["sqref"] == ex.NW_TICKS]
        assert [x for x in rules(full, a) if x["sqref"] != ex.NW_TICKS] == rules(without, b)
        assert len(mine) == 1 and mine[0]["dxf"] == {"fmt": ";;;"}
    sh = full.sheet("OIS_MAIN")
    assert ex.formula_of(full, "OIS_MAIN", "L5") == 'IF($L$2="Açık",IF(ISNUMBER($L$3),$L$3,EK_NORM!$E$11),"")'
    assert [ex.formula_of(full, "OIS_MAIN", "AP%d" % r) for r in range(9, 14)] == ["1", "1", "1", "0", "0"]
    assert ex.formula_of(full, "OIS_MAIN", "AO9") == 'IF($L$2="Açık","1W","")'
    assert sh.consts.get(parse_a1("AP14")) is None and parse_a1("AS14") not in sh.fml


def test_the_date_in_use_kept_from_the_switch_builder():
    """With the switch builder's L5 there (the date typed, while on - its own formula once merged, else written here as it
    writes it), the addition widens it to the OIS-implied date when none is typed - its look kept; an L5 that is anything
    else leaves the addition out."""
    m = before_the_walk()
    ex._nw_check(m)                                                           # (the workbook as it comes: it fits)
    l5 = "OIS_MAIN!L5 boş ya da kullanılan normalleşme tarihi değil"
    for sheet, addr, value, why in (("OIS_MAIN", "L5", "Normalleşme", l5), ("OIS_MAIN", "L5", "=$J$2", l5),
                                    ("OIS_MAIN", "AQ10", 1.5, "OIS_MAIN!AQ10 boş değil"),
                                    ("OIS_MAIN", "AT13", "1W", "OIS_MAIN!AT13 beklenen başlık değil"),
                                    ("Motor", "B4306", "=7", "Motor!B4306 beklenen formül değil"),
                                    ("OIS_MAIN", "E443", "=61", "OIS_MAIN!E443 beklenen formül değil"),
                                    ("Motor", "G528", "=A528", "Motor!G528 beklenen formül değil")):
        sh, rc = m.sheet(sheet), parse_a1(addr)
        kept = (sh.fml.get(rc), sh.consts.get(rc), sh.styles.get(rc))
        ex.SheetBuilder(m, sheet).set(addr, value)
        with pytest.raises(ValueError, match=re.escape(why)):
            ex._nw_check(m)
        for part, was in zip((sh.fml, sh.consts, sh.styles), kept):           # (the cell as it was)
            part.pop(rc, None)
            if was is not None:
                part[rc] = was
    ex._nw_check(m)
    sh = m.sheet("OIS_MAIN")
    if parse_a1("L5") not in sh.fml:
        ex.SheetBuilder(m, "OIS_MAIN").set("L5", '=IF(AND($L$2="Açık",ISNUMBER($L$3)),$L$3,"")', fmt="d.m.yyyy", bold=True)
    look = sh.styles.get(parse_a1("L5"))
    ex._nw_check(m)
    ex._tto_norm_walk(m)
    assert ex.formula_of(m, "OIS_MAIN", "L5") == 'IF($L$2="Açık",IF(ISNUMBER($L$3),$L$3,EK_NORM!$E$11),"")'
    assert sh.styles.get(parse_a1("L5")) == look


def before_the_walk():
    """The workbook with every addition before this one."""
    m = raw_model()
    for name, check, build in ex._BUILDERS["tto"]:
        if name != ex.NW_NAME:
            check(m)
            build(m)
    return m


def test_nothing_but_the_walk_reads_its_cells(svc):
    """The block and EK_NORM feed nothing of before: what reads them is the walk itself, the block and the date in use
    (L5 - which the switch builder's cells read, once merged: the date the PPK model takes)."""
    book = svc.books["tto"]
    idx = svc.et.call(book.engine.ref_index)
    model = book.model
    ois, norm = model.sheet_index["OIS_MAIN"], model.sheet_index[ex.NW_SHEET]
    block = {(ois, r * COLS + c) for r in range(8, 16) for c in range(41, 46)}
    assert idx.complete
    for si, rc in list(block) + [(norm, rc) for rc in model.sheets[norm].fml]:
        for reader in idx.readers(si, rc):
            assert reader[0] == norm or reader in block or reader == (ois, parse_a1(ex.NW_USED)), (model.sheets[si].name, rc,
                                                                                                    reader)
    assert (ois, parse_a1(ex.NW_USED)) in idx.readers(norm, parse_a1("E11"))           # (the OIS-implied date)
