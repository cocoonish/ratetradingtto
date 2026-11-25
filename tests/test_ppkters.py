"""The ways back of OIS · PPK and USD · FOMC (the desk, 24.11.2026: "1-2-3-4-5-6-7-8-11-11-13", items 2, 3 and 13;
``tto/extras.py``):

* **MPC OIS / MPC SPREAD → PPK adımı** (``EK_PPK``): a meeting window's swap rate typed -> the PPK step it prices, the
  overnight equivalent of the rate − that of the market's rate for the period before the meeting; an MPC spread typed ->
  the later window's rate (the earlier window's market + the spread) and its step.  Broker Chat's implied step of a
  meeting swap (``Service._mpc_implied``), cell for cell: the page and a chat line give the same bp - on Bootstrap and on
  PPK basamak.  The overnight equivalent is TLREF's as the MPC ima model compounds it (the desk, 25.11.2026: "B"): on
  the TRY calendar's business days, ACT/365 (``ppkcurve.window_overnight``) - the model's own window rate gives the
  model's own TLREF back, and its steps.
* **TÜM FORWARD / FRA**: a target FRA typed -> the end leg (with the start leg's fill) or the start leg (with the end
  leg's) it needs: the realized FRA's own formula, inverted.
* **USD · FOMC**: a window's OIS rate typed -> its O/N (the İma O/N formula on the rate's DF ratio) and the FOMC step it
  prices (as Toplantı adımı).

Every reverse is checked against the page's own cells: typed back into the forward direction it gives what was typed
(1e-9).  What is typed for a meeting window moves with its meeting (``meetings.TCMB`` / ``FED``) - tested on a calendar
change, the roll and a pasted FOMC list."""
import datetime as dt
import os

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto import meetings as mt
from tto import ppkcurve as pk
from tto.views import load_views
from tto.xl.model import Model, parse_a1, parse_range
from tto.xl.values import date_to_serial, serial_to_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = ex.PPK_WINDOWS[1] - ex.PPK_WINDOWS[0] + 1            # 16 windows of 'MPC OIS' ...
PAIRS = ex.PPK_PAIRS[1] - ex.PPK_PAIRS[0] + 1                  # ... 15 pairs of 'MPC SPREAD'
LINE_DAY = "2026-01-15"                                        # the chat's lines are read on a day no other test uses


def put(svc, user, cells, book="tto", **kw):
    res = svc.set_inputs(user, book, [{"ref": ref, "value": value} for ref, value in cells.items()], **kw)
    assert res["errors"] == [], res["errors"]
    return res


def term(svc, user, slot):
    """The weekend / holiday term of the window from meeting slot ``slot``'s effective day to the next one's (slot −1:
    the stub from the OIS spot), as the MPC ima model has it: Motor's Pcum at its end − at its start."""
    return cell(svc, "Motor!J%d" % (slot + 6), user) - cell(svc, "Motor!J%d" % (slot + 5), user)


#: Broker Chat's overnight equivalent of a meeting window's rate, and its way back: TLREF on business days (ACT/365)
on_bd, rate_bd = pk.window_overnight, pk.window_rate


def ppk(svc, user, col, r):
    return cell(svc, "%s!%s%d" % (ex.PPK_SHEET, col, r), user)


def chat(svc, user, text):
    """The meeting swaps of chat lines as Broker Chat reads them: {said: quote}."""
    rows = svc.broker_parse(user, text, LINE_DAY)["rows"]
    return {q["raw"].split(" mpc")[0].split()[-1]: q for q in rows if (q.get("mpc") or {}).get("start")}


# ============================================================================== MPC OIS / MPC SPREAD -> PPK step
def test_the_windows_are_mpc_ois_rows_with_the_period_before_each(service):
    """A row of EK_PPK is a window of 'MPC OIS': its dates, days and market rate; the period before it the window before
    (its market rate and days) - for the first window the bootstrap's stub from the OIS spot (ln DF 0 there).  Their
    overnight equivalents are TLREF's on business days, each window with its own weekend / holiday term (the model's,
    Motor's Pcum: 0 at the spot)."""
    import math
    u = service.login("PPK ters satırlar")["user"]
    spot = cell(service, "OIS_MAIN!B2", u)
    assert cell(service, "Motor!J4", u) == 0.0 and cell(service, "Motor!C4", u) == 0.0
    for k in range(WINDOWS):
        r, w = ex.PPK_FIRST + k, ex.PPK_WINDOWS[0] + k
        assert ppk(service, u, "A", r) == cell(service, "OIS_MAIN!A%d" % w, u)
        assert ppk(service, u, "B", r) == cell(service, "OIS_MAIN!P%d" % (10 + k), u)            # the meeting of the step
        assert ppk(service, u, "C", r) == cell(service, "OIS_MAIN!B%d" % w, u)
        assert ppk(service, u, "D", r) == cell(service, "OIS_MAIN!C%d" % w, u)
        assert ppk(service, u, "E", r) == cell(service, "OIS_MAIN!C%d" % w, u) - cell(service, "OIS_MAIN!B%d" % w, u) > 0
        assert ppk(service, u, "F", r) == cell(service, "OIS_MAIN!D%d" % w, u)
        # the model's window: its days are Motor's effective days, counted from the OIS spot
        assert ppk(service, u, "C", r) == spot + cell(service, "Motor!C%d" % (5 + k), u)
        assert ppk(service, u, "D", r) == spot + cell(service, "Motor!C%d" % (6 + k), u)
        if k:
            assert ppk(service, u, "H", r) == cell(service, "OIS_MAIN!D%d" % (w - 1), u)
            assert ppk(service, u, "I", r) == ppk(service, u, "E", r - 1)
        else:
            start = cell(service, "OIS_MAIN!B%d" % w, u)
            assert ppk(service, u, "I", r) == start - spot > 0
            assert ppk(service, u, "H", r) == pytest.approx((math.exp(-cell(service, "OIS_MAIN!BK%d" % w, u)) - 1) * 365 / (start - spot), rel=1e-15)
        assert ppk(service, u, "J", r) == pytest.approx(on_bd(ppk(service, u, "H", r), ppk(service, u, "I", r), term(service, u, k - 1)), rel=1e-15)
        # nothing typed: no step; the market's own step beside it (the rate's cell: its two-way default, nothing)
        assert ppk(service, u, ex.PPK_RATE, r) == "" and ppk(service, u, "K", r) == "" and ppk(service, u, "L", r) == ""
        on_mkt = on_bd(ppk(service, u, "F", r), ppk(service, u, "E", r), term(service, u, k))
        assert ppk(service, u, "M", r) == pytest.approx((on_mkt - ppk(service, u, "J", r)) * 1e4, abs=1e-9)
    for k in range(PAIRS):
        r = ex.PPK_FIRST + k
        assert ppk(service, u, "P", r) == cell(service, "OIS_MAIN!A%d" % (ex.PPK_PAIRS[0] + k), u)
        assert ppk(service, u, "R", r) == cell(service, "OIS_MAIN!B%d" % (ex.PPK_PAIRS[0] + k), u)
        assert ppk(service, u, "Q", r) == ppk(service, u, "B", r + 1)                              # the later window's meeting
        assert ppk(service, u, "W", r) == ppk(service, u, "M", r + 1)
        assert ppk(service, u, ex.PPK_SPREAD, r) == "" and ppk(service, u, "T", r) == "" and ppk(service, u, "V", r) == ""


def test_a_windows_rate_gives_broker_chats_step_and_goes_back(service):
    """(item 2) A meeting swap's rate typed for a window -> the step it prices: Broker Chat's implied step of the same
    line, to the bp's last digit (the same period before, the same rate for it, the same conversion), with the market's
    own step = the chat's model.  The step found, put back on the period before's overnight rate, gives the rate typed
    (1e-9); the window's market rate typed gives the market's own step."""
    u = service.login("PPK ters pencere")["user"]
    try:
        put(service, u, {"EK_PPK!G3": "36,5", "EK_PPK!G4": "35", "EK_PPK!G5": "34,25"})
        lines = chat(service, u, "10:00:00 dec mpc 36.50/37.00\n10:01:00 jan27 mpc 35.00/35.20\n10:02:00 mar27 mpc 34.25/34.50")
        for said, r in (("dec", 3), ("jan27", 4), ("mar27", 5)):
            q = lines[said]
            imp = q["implied"]
            # the same window: the chat's two days are the row's
            assert date_to_serial(dt.date.fromisoformat(q["mpc"]["start"])) == ppk(service, u, "C", r)
            assert date_to_serial(dt.date.fromisoformat(q["mpc"]["end"])) == ppk(service, u, "D", r)
            assert imp["meeting"] == q["mpc"]["meeting"] and date_to_serial(dt.date.fromisoformat(imp["meeting"])) == ppk(service, u, "B", r)
            assert imp["prev"] == pytest.approx(ppk(service, u, "H", r) * 100, rel=1e-14)
            assert imp["prev_on"] == pytest.approx(ppk(service, u, "J", r) * 100, rel=1e-14)
            assert ppk(service, u, "L", r) == pytest.approx(imp["bid"], abs=1e-9), said            # the page = the chat
            assert ppk(service, u, "M", r) == pytest.approx(imp["model"], abs=1e-9), said
            # back: the step on the period before's overnight rate makes the rate typed
            step, base, days, w = ppk(service, u, "L", r), ppk(service, u, "J", r), ppk(service, u, "E", r), term(service, u, r - ex.PPK_FIRST)
            assert rate_bd(base + step / 1e4, days, w) == pytest.approx(ppk(service, u, ex.PPK_RATE, r), abs=1e-12)
            assert ppk(service, u, "K", r) == pytest.approx(on_bd(ppk(service, u, ex.PPK_RATE, r), days, w), rel=1e-15)
        assert lines["dec"]["implied"]["ask"] > lines["dec"]["implied"]["bid"]
        # the market's own rate typed: the market's own step; a higher rate, a higher step
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            put(service, u, {"EK_PPK!G%d" % r: ppk(service, u, "F", r)})
            assert ppk(service, u, "L", r) == pytest.approx(ppk(service, u, "M", r), abs=1e-9), k
        put(service, u, {"EK_PPK!G6": ppk(service, u, "F", 6) + 0.0025})
        assert ppk(service, u, "L", 6) > ppk(service, u, "M", 6) + 20
        put(service, u, {"EK_PPK!G6": ""})
        assert ppk(service, u, "L", 6) == "" and ppk(service, u, "K", 6) == ""
    finally:
        service.reset_inputs(u, "tto")


def test_an_mpc_spread_gives_the_later_windows_rate_and_its_step(service):
    """(item 2) An MPC spread typed (later window − earlier, bp) -> the later window's rate = the earlier window's market
    rate + the spread, and the step that prices: the same as that rate typed for the later window, and as Broker Chat's
    for a line at that rate.  The market's own spread typed gives the later window's market rate and step back (1e-9)."""
    u = service.login("PPK ters spread")["user"]
    try:
        for k in range(PAIRS):
            r, w = ex.PPK_FIRST + k, ex.PPK_WINDOWS[0] + k
            exact = (cell(service, "OIS_MAIN!D%d" % (w + 1), u) - cell(service, "OIS_MAIN!D%d" % w, u)) * 1e4
            assert abs(ppk(service, u, "R", r) - exact) <= 0.005 + 1e-12                         # (the sheet's, rounded)
            put(service, u, {"EK_PPK!S%d" % r: exact})
            assert ppk(service, u, "T", r) == pytest.approx(cell(service, "OIS_MAIN!D%d" % (w + 1), u), abs=1e-12), k
            assert ppk(service, u, "V", r) == pytest.approx(ppk(service, u, "W", r), abs=1e-9), k
            assert (ppk(service, u, "T", r) - ppk(service, u, "F", r)) * 1e4 == pytest.approx(exact, abs=1e-9)
        # a spread of one's own: the same step as its rate typed for the later window, and as the chat's at that rate
        level = 0.3546                                                                           # 35,46 % for MPC2→3
        put(service, u, {"EK_PPK!S3": (level - ppk(service, u, "F", 3)) * 1e4, "EK_PPK!G4": level})
        assert ppk(service, u, "T", 3) == pytest.approx(level, abs=1e-15)
        assert ppk(service, u, "V", 3) == pytest.approx(ppk(service, u, "L", 4), abs=1e-9)
        assert ppk(service, u, "U", 3) == pytest.approx(ppk(service, u, "K", 4), rel=1e-14)
        assert ppk(service, u, "V", 3) == pytest.approx(chat(service, u, "10:00:00 jan27 mpc 35.46/35.50")["jan27"]["implied"]["bid"], abs=1e-9)
        put(service, u, {"EK_PPK!S3": "-30"})
        assert ppk(service, u, "T", 3) == pytest.approx(ppk(service, u, "F", 3) - 0.003, abs=1e-15)
        assert ppk(service, u, "U", 3) == pytest.approx(on_bd(ppk(service, u, "T", 3), ppk(service, u, "E", 4), term(service, u, 1)), rel=1e-15)
        put(service, u, {"EK_PPK!S3": ""})
        assert ppk(service, u, "T", 3) == "" and ppk(service, u, "V", 3) == ""
    finally:
        service.reset_inputs(u, "tto")


def test_the_market_and_the_chat_follow_the_curve_setting_alike(service):
    """The market is the 'MPC OIS' table's: Bootstrap (Murex's MTM) for everybody, the user's PPK basamak curve for a user
    on it - the chat reads the same, so the page and a chat line agree either way; a Bootstrap user's numbers are the
    desk's (nothing typed here moves them)."""
    boot = service.login("PPK ters bootstrap")["user"]
    step = service.login("PPK ters basamak")["user"]
    try:
        service.set_interp(step, "ppk")
        put(service, boot, {"EK_PPK!G4": "35"})
        put(service, step, {"EK_PPK!G4": "35"})
        for k in range(WINDOWS):
            assert cell(service, "OIS_MAIN!D%d" % (ex.PPK_WINDOWS[0] + k), boot) == cell(service, "OIS_MAIN!D%d" % (ex.PPK_WINDOWS[0] + k))
        markets = [(ppk(service, boot, "F", ex.PPK_FIRST + k), ppk(service, step, "F", ex.PPK_FIRST + k)) for k in range(WINDOWS)]
        assert max(abs(a - b) for a, b in markets) > 1e-5                                       # two curves, two markets
        assert all(ppk(service, step, "F", ex.PPK_FIRST + k) == cell(service, "OIS_MAIN!D%d" % (ex.PPK_WINDOWS[0] + k), step)
                   for k in range(WINDOWS))
        for user in (boot, step):
            imp = chat(service, user, "10:00:00 jan27 mpc 35.00/35.20")["jan27"]["implied"]
            assert ppk(service, user, "L", 4) == pytest.approx(imp["bid"], abs=1e-9)
            assert ppk(service, user, "M", 4) == pytest.approx(imp["model"], abs=1e-9)
    finally:
        service.set_interp(step, "boot")
        service.reset_inputs(step, "tto")
        service.reset_inputs(boot, "tto")


def solve(f, lo=-0.2, hi=0.2):
    """The root of ``f``, increasing around it, by bisection (an algorithm of its own)."""
    for _ in range(200):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if f(mid) < 0.0 else (lo, mid)
    return (lo + hi) / 2.0


def test_a_windows_overnight_is_tlref_on_the_desks_business_days(service):
    """The desk, 25.11.2026: "B" - a window's rate is turned into its overnight rate as TLREF accrues: on the business days
    of the desk's TRY calendar (the dashboard's TR holiday list, Ayarlar → Tatiller), each one's rate for the calendar days
    to the next business day.  Counted by hand from the list for every window of the table: its ends are business days,
    its term Σ g(g − 1)/2 over the gaps is the model's (Motor's Pcum), and the O/N of a rate typed solves the model's own
    equation (bisection).  The replay's second window holds the Ramazan Bayramı of 2027 (09–11.03: Monday's rate for four
    days) and the first one New Year's Day (Thursday's rate for four days)."""
    import math
    u = service.login("PPK ters iş günü")["user"]
    holidays = service.holiday_dates(("TRY",))
    try:
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            start, end = (serial_to_date(ppk(service, u, c, r)) for c in "CD")
            days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
            business = [d for d in days if d.weekday() < 5 and d not in holidays]
            assert business[0] == start and business[-1] == end, k                       # effective days are business days
            gaps = [(b - a).days for a, b in zip(business, business[1:])]
            assert sum(gaps) == ppk(service, u, "E", r)
            assert sum(g * (g - 1) / 2 for g in gaps) == term(service, u, k), k          # the model's term is the list's
            if start == dt.date(2027, 1, 22) and end == dt.date(2027, 3, 19):              # (the replay's calendar)
                assert (dt.date(2027, 3, 8), dt.date(2027, 3, 12)) in list(zip(business, business[1:]))
                assert (len(business), gaps.count(3), gaps.count(4), term(service, u, k)) == (38, 8, 1, 30.0)
            if start == dt.date(2026, 12, 11):
                assert (dt.date(2026, 12, 31), dt.date(2027, 1, 4)) in list(zip(business, business[1:]))
        # a rate typed for each window: its O/N by hand, from the window's own days and term
        put(service, u, {"EK_PPK!G%d" % (ex.PPK_FIRST + k): "35,5" for k in range(WINDOWS)})
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            d, w = ppk(service, u, "E", r), term(service, u, k)
            x = solve(lambda v: d * math.log(1 + v) - w * v * v - math.log(1 + 0.355 * d / 365))
            assert ppk(service, u, "K", r) == pytest.approx(365 * x, rel=0, abs=1e-13), k      # (LN(1 + x)'s digits: 1e-9 bp)
            # (every calendar day compounded alone - before 25.11.2026 - is below it by 365·W·x²/d: 1.5 bp over six
            # weekends at 35,5 %)
            daily = 365 * ((1 + 0.355 * d / 365) ** (1 / d) - 1)
            assert ppk(service, u, "K", r) - daily == pytest.approx(365 * w * x * x / d, rel=0.01), k
    finally:
        service.reset_inputs(u, "tto")


def test_the_models_own_window_rates_give_its_own_tlref_and_steps(service):
    """The step read from a quote is the MPC ima model's own convention: the model's window rate ("İma oran (model)",
    OIS_MAIN!BJ: Motor's TLREF of the window compounded its way) typed for a window gives the model's TLREF back as its O/N
    equivalent (Motor!K, 1e-12) - in both tables -, so the steps between them are the model's steps (Motor!K's, 1e-8 bp),
    the first one from the model's stub.  The market's own window rate typed gives the market's own step (Piyasanın adımı),
    on the same convention."""
    u = service.login("PPK ters model")["user"]
    try:
        bj = [cell(service, "OIS_MAIN!BJ%d" % (ex.PPK_WINDOWS[0] + k), u) for k in range(WINDOWS)]
        tlref = [cell(service, "Motor!K%d" % (4 + k), u) for k in range(WINDOWS + 1)]      # the stub's, then each window's
        put(service, u, {"EK_PPK!G%d" % (ex.PPK_FIRST + k): bj[k] for k in range(WINDOWS)})
        put(service, u, {"EK_PPK!T%d" % (ex.PPK_FIRST + k): bj[k + 1] for k in range(PAIRS)})    # the later windows' rates
        on = [ppk(service, u, "K", ex.PPK_FIRST + k) for k in range(WINDOWS)]
        for k in range(WINDOWS):
            assert on[k] == pytest.approx(tlref[k + 1], abs=1e-12), k
        for k in range(PAIRS):
            assert ppk(service, u, "U", ex.PPK_FIRST + k) == pytest.approx(tlref[k + 2], abs=1e-12), k
        # the model's stub rate (the spot to the first effective day at Motor!K4) gives its TLREF: the first step too
        stub = rate_bd(tlref[0], cell(service, "Motor!C5", u), term(service, u, -1))
        steps = [on_bd(stub, cell(service, "Motor!C5", u), term(service, u, -1))] + on
        for k in range(WINDOWS):
            assert (steps[k + 1] - steps[k]) * 1e4 == pytest.approx((tlref[k + 1] - tlref[k]) * 1e4, abs=1e-8), k
        # every calendar day compounded alone (the convention before 25.11.2026) read the model's window rates low, by
        # 365·W·x²/d (1.3-2.5 bp on the replay day)
        for k in range(WINDOWS):
            e, x = ppk(service, u, "E", ex.PPK_FIRST + k), tlref[k + 1] / 365
            daily = 365 * ((1 + bj[k] * e / 365) ** (1 / e) - 1)
            assert tlref[k + 1] - daily == pytest.approx(365 * term(service, u, k) * x * x / e, rel=0.01), k
        # the market's own window rate: the market's own step, as the page's market column reads it
        put(service, u, {"EK_PPK!G%d" % (ex.PPK_FIRST + k): ppk(service, u, "F", ex.PPK_FIRST + k) for k in range(WINDOWS)})
        for k in range(WINDOWS):
            r = ex.PPK_FIRST + k
            assert ppk(service, u, "L", r) == pytest.approx(ppk(service, u, "M", r), abs=1e-9), k
            assert ppk(service, u, "K", r) == pytest.approx(on_bd(ppk(service, u, "F", r), ppk(service, u, "E", r), term(service, u, k)), rel=1e-15)
    finally:
        service.reset_inputs(u, "tto")


# ============================================================================== TÜM FORWARD / FRA: the other leg
def test_a_target_fra_gives_the_leg_it_needs(service):
    """(item 3) A target FRA typed -> the end leg's rate with the start leg's fill (blank: its market par) and the start
    leg's rate with the end leg's: either typed back into its fill makes "Gerçekleşen FRA" the target (1e-12).  A spot
    start's end leg is the FRA itself; it has no start leg.  A row of one's own months works the same way."""
    u = service.login("FRA ikinci bacak")["user"]
    try:
        r = 337                                                                                  # 3M3M
        put(service, u, {"OIS_MAIN!U%d" % r: "35", "OIS_MAIN!Q%d" % r: "36,8"})
        need_end = cell(service, "OIS_MAIN!V%d" % r, u)
        o, p = cell(service, "OIS_MAIN!O%d" % r, u), cell(service, "OIS_MAIN!P%d" % r, u)
        assert need_end == pytest.approx((0.35 * (p - o) + 0.368 * o) / p, rel=1e-14)
        put(service, u, {"OIS_MAIN!R%d" % r: need_end})
        assert cell(service, "OIS_MAIN!S%d" % r, u) == pytest.approx(0.35, abs=1e-12)
        # the end leg filled first: the start leg it needs
        put(service, u, {"OIS_MAIN!Q%d" % r: "", "OIS_MAIN!R%d" % r: "36,1"})
        need_start = cell(service, "OIS_MAIN!W%d" % r, u)
        assert need_start == pytest.approx((0.361 * p - 0.35 * (p - o)) / o, rel=1e-14)
        put(service, u, {"OIS_MAIN!Q%d" % r: need_start})
        assert cell(service, "OIS_MAIN!S%d" % r, u) == pytest.approx(0.35, abs=1e-12)
        # nothing filled: each leg against the other's market par (I / J), as "Gerçekleşen FRA" reads a blank fill
        put(service, u, {"OIS_MAIN!Q%d" % r: "", "OIS_MAIN!R%d" % r: ""})
        i, j = cell(service, "OIS_MAIN!I%d" % r, u), cell(service, "OIS_MAIN!J%d" % r, u)
        assert cell(service, "OIS_MAIN!V%d" % r, u) == pytest.approx((0.35 * (p - o) + i * o) / p, rel=1e-14)
        assert cell(service, "OIS_MAIN!W%d" % r, u) == pytest.approx((j * p - 0.35 * (p - o)) / o, rel=1e-14)
        # the market's FRA as the target: the market's legs
        put(service, u, {"OIS_MAIN!U%d" % r: cell(service, "OIS_MAIN!S%d" % r, u)})
        assert cell(service, "OIS_MAIN!V%d" % r, u) == pytest.approx(j, abs=1e-12)
        assert cell(service, "OIS_MAIN!W%d" % r, u) == pytest.approx(i, abs=1e-12)
        # a spot start: the end leg is the FRA, no start leg
        assert cell(service, "OIS_MAIN!M336", u) == 0.0
        put(service, u, {"OIS_MAIN!U336": "37"})
        assert cell(service, "OIS_MAIN!V336", u) == pytest.approx(0.37, abs=1e-15) and cell(service, "OIS_MAIN!W336", u) == ""
        # a row of one's own months (1Y1Y)
        put(service, u, {"OIS_MAIN!M350": "12", "OIS_MAIN!N350": "24", "OIS_MAIN!U350": "33", "OIS_MAIN!Q350": "35"})
        put(service, u, {"OIS_MAIN!R350": cell(service, "OIS_MAIN!V350", u)})
        assert cell(service, "OIS_MAIN!S350", u) == pytest.approx(0.33, abs=1e-12)
        put(service, u, {"OIS_MAIN!U350": ""})
        assert cell(service, "OIS_MAIN!V350", u) == "" and cell(service, "OIS_MAIN!W350", u) == ""
    finally:
        service.reset_inputs(u, "tto")


# ============================================================================== USD · FOMC: window OIS -> step
def test_a_window_ois_rate_gives_the_fomc_step_and_goes_back(service):
    """(item 13) A window's OIS rate typed -> its O/N (İma O/N's formula on the rate's own DF ratio) and the step it
    prices against Önceki ima, in bp and as Toplantı adımı (steps of Adım).  The market's window rate (İşlem 1's) typed
    gives İma O/N and Toplantı adımı back; a rate of one's own, its step put back on Önceki ima, gives the rate (1e-9,
    İşlem 1's own O/N → window formula).  A meeting without a decision gives nothing."""
    u = service.login("FOMC ters")["user"]
    f = lambda ref: cell(service, "SOFR_FOMC!" + ref, u, book="sofr")              # noqa: E731
    try:
        active = [r for r in range(ex.FOMC_BACK_ROWS[0], ex.FOMC_BACK_ROWS[1] + 1) if f("D%d" % r) == 1]
        assert len(active) >= 5
        for r in active:
            assert f("AA%d" % r) == f("E%d" % (r + ex.FOMC_TRADE_OFFSET))
            put(service, u, {"SOFR_FOMC!AB%d" % r: f("AA%d" % r)}, book="sofr")
            assert f("AC%d" % r) == pytest.approx(f("K%d" % r), rel=1e-12), r
            assert f("AD%d" % r) == pytest.approx((f("K%d" % r) - f("L%d" % r)) * 100, abs=1e-9), r
            assert f("AE%d" % r) == pytest.approx(f("N%d" % r), abs=1e-9), r
        r = active[1]
        put(service, u, {"SOFR_FOMC!AB%d" % r: "4,1"}, book="sofr")
        h, prev = f("H%d" % r), f("L%d" % r)
        assert f("AC%d" % r) == pytest.approx(((1 + 4.1 * h / 36000) ** (1 / h) - 1) * 36000, rel=1e-15)
        back = f("L%d" % r) + f("AD%d" % r) / 100
        assert ((1 + back / 36000) ** h - 1) * 36000 / h == pytest.approx(4.1, abs=1e-9)
        assert f("AE%d" % r) == pytest.approx((f("AC%d" % r) - prev) * 100 / f("B9"), abs=1e-12)
        # the step's size as the page has it (Adım, bp)
        put(service, u, {"SOFR_FOMC!B9": "50"}, book="sofr")
        assert f("AE%d" % r) == pytest.approx(f("AD%d" % r) / 50, abs=1e-12)
        # no decision at that meeting: no window, no step
        put(service, u, {"SOFR_FOMC!C%d" % r: "0"}, book="sofr")
        assert f("D%d" % r) == 0 and f("AC%d" % r) == "" and f("AD%d" % r) == "" and f("AE%d" % r) == ""
        put(service, u, {"SOFR_FOMC!AB%d" % r: ""}, book="sofr")
    finally:
        service.reset_inputs(u, "sofr")


# ============================================================================== rows move
def test_the_typed_cells_belong_to_their_meetings_row(service):
    """The rate / spread typed per window and the window OIS rate are cells of a meeting's row (meetings.py): typed per
    meeting - they follow it -, the rest computed; the bands are where the sheets' rows are."""
    tto, sofr = service.books["tto"], service.books["sofr"]

    def where(book, ref):
        hit = mt.place(book, *book.cell(ref))
        return None if hit is None else (hit[0].id, hit[1].kind, hit[2], hit[3])

    assert where(tto, "EK_PPK!G3") == ("tcmb", "typed", 0, "G") and where(tto, "EK_PPK!G18") == ("tcmb", "typed", 15, "G")
    assert where(tto, "EK_PPK!S17") == ("tcmb", "typed", 14, "S")
    assert where(tto, "EK_PPK!L5") == ("tcmb", "computed", 2, "L") and where(tto, "EK_PPK!V3")[1] == "computed"
    # (two-way: an O/N, a step or a later rate typed is kept in its store - typed per meeting too)
    assert where(tto, "EK_PPK!Z5") == ("tcmb", "typed", 2, "Z") and where(tto, "EK_PPK!AA17") == ("tcmb", "typed", 14, "AA")
    for ref in ("EK_PPK!G2", "EK_PPK!N3", "EK_PPK!O3", "EK_PPK!X3", "EK_PPK!A1", "EK_PPK!Y2", "EK_PPK!AD3"):    # headers, the gaps
        assert where(tto, ref) is None, ref
    assert mt.follows(tto, *tto.cell("EK_PPK!G3")) and not mt.follows(tto, *tto.cell("EK_PPK!L3"))
    assert where(sofr, "SOFR_FOMC!AB76") == ("fed", "typed", 2, "AB") and where(sofr, "SOFR_FOMC!AD83") == ("fed", "computed", 9, "AD")
    assert where(sofr, "SOFR_FOMC!AB73") is None and where(sofr, "SOFR_FOMC!AF74") is None
    assert {"AA", "AB", "AC", "AD", "AE"} <= set(mt.FED.columns())
    assert where(sofr, "SOFR_FOMC!AG74") == ("fed", "typed", 0, "AG") and where(sofr, "SOFR_FOMC!AJ83") == ("fed", "typed", 9, "AJ")
    # the registry and the sheets agree: every input of a row is typed (the rate and the spread - two-way, a formula
    # default each - and the two-way stores), every other formula of a row computed
    sh = tto.model.sheet(ex.PPK_SHEET)
    typed = (ex.PPK_RATE, ex.PPK_SPREAD) + ex.PPK_TW_WINDOW + ex.PPK_TW_PAIR
    for k in range(WINDOWS):
        r = ex.PPK_FIRST + k
        for col in "ABCDEFGHIJKLMPQRSTUVW" + "YZ" + "".join(ex.PPK_TW_PAIR):
            if (col in "PQRSTUVW" or col in ex.PPK_TW_PAIR) and k >= PAIRS:
                continue
            ref = "%s!%s%d" % (ex.PPK_SHEET, col, r)
            kind = where(tto, ref)[1]
            assert kind == ("typed" if tto.cell(ref) in tto.inputs else "computed"), (col, r)
            assert (col in typed) == (tto.cell(ref) in tto.inputs), (col, r)
            assert (parse_a1("%s%d" % (col, r)) in sh.fml) == (col not in ex.PPK_TW_WINDOW + ex.PPK_TW_PAIR), (col, r)
    for r in range(ex.FOMC_BACK_ROWS[0], ex.FOMC_BACK_ROWS[1] + 1):
        for col in ex.FOMC_BACK_COLS + ex.FOMC_TW:
            ref = "SOFR_FOMC!%s%d" % (col, r)
            assert where(sofr, ref)[1] == ("typed" if sofr.cell(ref) in sofr.inputs else "computed")
            assert (col in (ex.FOMC_BACK_RATE,) + ex.FOMC_TW) == (sofr.cell(ref) in sofr.inputs)


def test_what_is_typed_for_a_window_moves_with_its_meeting(tmp_path):
    """A PPK calendar change, the roll and a pasted FOMC list: the rate / spread typed for a window (and a step typed - the
    table is two-way: kept in its store) stay with the meeting that starts the window; one whose meeting left is set aside;
    no formula is taken there."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        book = svc.books["tto"]
        a = svc.login("Ters Toplantı Ayşe")["user"]
        mine = lambda bk="tto": {k[1]: v for k, v in svc.store.user_inputs(a, bk).items()}           # noqa: E731
        assert [cell(svc, "OIS_MAIN!P%d" % r) for r in (10, 11, 12)] == [float(date_to_serial(dt.date(*d))) for d in
                                                                          ((2026, 12, 10), (2027, 1, 21), (2027, 3, 18))]
        put(svc, a, {"EK_PPK!G3": "36,5", "EK_PPK!G4": "35", "EK_PPK!S5": "-25"})          # slots 0, 1, 2
        put(svc, a, {"EK_PPK!L5": "12,5"}, allow_adhoc=True)                                # slot 2's step typed (two-way: its store Z5)
        res = svc.set_inputs(a, "tto", [{"ref": "EK_PPK!G6", "value": "=OIS_MAIN!D87"}])
        assert "toplantı takvimiyle kayan hücre" in res["errors"][0]
        step = cell(svc, "EK_PPK!L4", a)
        # ---- an extraordinary meeting before 18.03.2027: that one and those after it move a row down
        start = h.meetings()
        res = h.set_calendar(a, ["11.02.2027"] + start[:-1])
        assert res["parked"]["meetings"] == []
        assert mine() == {"EK_PPK!G3": 0.365, "EK_PPK!G4": 0.35, "EK_PPK!S6": -25.0, "EK_PPK!Z6": 12.5}
        assert cell(svc, "EK_PPK!B6", a) == float(date_to_serial(dt.date(2027, 3, 18)))           # the spread's first window
        assert cell(svc, "EK_PPK!B5", a) == float(date_to_serial(dt.date(2027, 2, 11)))           # the new meeting: nothing typed
        assert cell(svc, "EK_PPK!S5", a) == "" and cell(svc, "EK_PPK!T5", a) == ""
        # the 21.01.2027 window ends at the new meeting now: the same rate, another window - another step, read on the new
        # window's business days (22.01 → 12.02.2027: 21 days, three weekends)
        assert cell(svc, "EK_PPK!D4", a) == cell(svc, "OIS_MAIN!C85", a) == float(date_to_serial(dt.date(2027, 2, 12)))
        assert cell(svc, "EK_PPK!L4", a) != pytest.approx(step, abs=1e-6)
        assert (cell(svc, "EK_PPK!G4", a), cell(svc, "EK_PPK!E4", a), term(svc, a, 1)) == (0.35, 21.0, 9.0)
        assert cell(svc, "EK_PPK!K4", a) == pytest.approx(on_bd(0.35, 21.0, 9.0), rel=1e-15)
        assert cell(svc, "EK_PPK!L4", a) == pytest.approx((on_bd(0.35, 21.0, 9.0) - cell(svc, "EK_PPK!J4", a)) * 1e4, abs=1e-9)
        # the step typed for the 18.03.2027 window stays the step; the rate that prices it follows the new window
        assert cell(svc, "EK_PPK!L6", a) == 12.5
        assert cell(svc, "EK_PPK!G6", a) == pytest.approx(rate_bd(cell(svc, "EK_PPK!J6", a) + 0.00125, cell(svc, "EK_PPK!E6", a), term(svc, a, 3)), abs=1e-15)
        assert cell(svc, "EK_PPK!T6", a) == pytest.approx(cell(svc, "EK_PPK!F6", a) - 0.0025, abs=1e-15)
        # ---- the roll: 10.12.2026 has passed - its window's rate is set aside, the others a row up
        def move_spot():
            book.declare("OIS_MAIN!B2", scope="shared", group="test-spot")
            book.engine.set_inputs({book.cell("OIS_MAIN!B2"): float(date_to_serial(dt.date(2026, 12, 14)))})
        svc.et.call(move_spot)
        svc.bump()
        res = h.roll_calendar(a)
        assert res["rolled"] == ["2026-12-10"] and res["parked"]["meetings"] == ["2026-12-10"]
        assert mine() == {"EK_PPK!G3": 0.35, "EK_PPK!S5": -25.0, "EK_PPK!Z5": 12.5}
        assert mt.parked(svc.store)["tcmb"]["2026-12-10"]["user"] == {a: {"EK_PPK!G": 0.365}}
        assert cell(svc, "EK_PPK!B3", a) == float(date_to_serial(dt.date(2027, 1, 21))) and cell(svc, "EK_PPK!G3", a) == 0.35
        assert isinstance(cell(svc, "EK_PPK!L3", a), float)
        # (the calendar term counted from the new spot: the window's own still)
        assert cell(svc, "EK_PPK!K3", a) == pytest.approx(on_bd(0.35, cell(svc, "EK_PPK!E3", a), term(svc, a, 0)), rel=1e-15)
        assert term(svc, a, 0) == 9.0 and term(svc, a, -1) == cell(svc, "Motor!J5", a) > 0
        # ---- the FOMC list pasted without the two held meetings: a rate typed goes with its meeting
        put(svc, a, {"SOFR_FOMC!AB74": "3,9", "SOFR_FOMC!AB76": "4,2"}, book="sofr")
        new = ["17.03.2027", "28.04.2027", "09.06.2027", "28.07.2027", "15.09.2027", "27.10.2027", "08.12.2027",
               "26.01.2028", "15.03.2028", "26.04.2028"]
        res = svc.paste(a, "sofr", "SOFR_FOMC!B74", "\n".join(new))
        assert res["errors"] == [] and res["calendar"]["parked"]["meetings"] == ["2026-12-09"]
        assert mine("sofr") == {"SOFR_FOMC!AB74": 4.2}
        assert mt.parked(svc.store)["fed"]["2026-12-09"]["user"] == {a: {"SOFR_FOMC!AB": 3.9}}
        f = lambda ref: cell(svc, "SOFR_FOMC!" + ref, a, book="sofr")                          # noqa: E731
        assert f("B74") == float(date_to_serial(dt.date(2027, 3, 17))) and f("AB74") == 4.2
        hh = f("H74")
        assert f("AC74") == pytest.approx(((1 + 4.2 * hh / 36000) ** (1 / hh) - 1) * 36000, rel=1e-15)
        assert f("AD74") == pytest.approx((f("AC74") - f("L74")) * 100, abs=1e-9)
    finally:
        svc.stop()


# ============================================================================== the page and the workbook
def test_the_tables_sit_after_their_sources_and_their_inputs_are_new(service):
    """MPC OIS → PPK ADIMI right after MPC OIS, MPC SPREAD → PPK ADIMI right after MPC SPREAD (PPK ima tab); the FRA list
    and the FOMC table wider; each with a note saying what to type and what comes back.  The inputs are the user's own and
    stand where no input ever stood (no other range, none retired)."""
    views = {v["id"]: v for v in load_views()}
    ois, usd = views["ois"], views["usd"]
    mpc = next(s for s in ois["sections"] if s["id"] == "mpc")["panels"]
    assert mpc[mpc.index("B13") + 1] == "PPK1" and mpc[mpc.index("B15") + 1] == "PPK2"
    panels = {p["id"]: p for p in ois["panels"]}
    assert (panels["PPK1"]["sheet"], panels["PPK1"]["range"]) == (ex.PPK_SHEET, "A1:M%d" % (ex.PPK_FIRST + WINDOWS - 1))
    assert (panels["PPK2"]["sheet"], panels["PPK2"]["range"]) == (ex.PPK_SHEET, "P1:W%d" % (ex.PPK_FIRST + PAIRS - 1))
    assert panels["B21"]["range"] == "A334:W438"
    assert next(p for p in usd["panels"] if p["id"] == "fomc")["range"] == "A71:AE83"
    for p in (panels["PPK1"], panels["PPK2"], panels["B21"], next(p for p in usd["panels"] if p["id"] == "fomc")):
        assert "yazın" in p["note"], p["id"]
    assert "Broker Chat" in panels["PPK1"]["note"] and "Bootstrap" in panels["PPK1"]["note"]
    new = {("ois", "EK_PPK!G3:G18"), ("ois", "EK_PPK!S3:S17"), ("ois", "U336:U438"), ("usd", "AB74:AB83")}
    have = {(v["id"], i["range"]): i for v in views.values() for i in v["inputs"]}
    assert new <= set(have) and all(have[k]["scope"] == "user" for k in new)

    def cells(view, ref):
        sheet, _, addr = ref.rpartition("!")
        r1, c1, r2, c2 = parse_range(addr)
        return {(view["book"], sheet or view["sheet"], r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}

    mine = set().union(*(cells(views[v], ref) for v, ref in new))
    others = set().union(*(cells(v, i["range"]) for v in views.values() for i in v["inputs"] if (v["id"], i["range"]) not in new))
    retired = set().union(*(cells({"book": bk, "sheet": ""}, ref) for bk, refs in ex.RETIRED_INPUTS.items() for ref in refs))
    assert not mine & others and not mine & retired and retired


def test_the_page_shows_them(service):
    """The OIS page's PPK ima tab with the two tables (their own titles, inputs on the typed columns), the FRA list with
    its three columns before the PPK ones, the FOMC table with its five."""
    u = service.login("PPK ters sayfa")["user"]
    page = service.view(u, "ois")
    panels = {p["id"]: p for p in page["panels"]}
    one, two = panels["PPK1"], panels["PPK2"]
    assert one["title"] == "MPC OIS → PPK ADIMI" and two["title"] == "MPC SPREAD → PPK ADIMI"
    assert "error" not in one and "error" not in two
    first = dict(zip(one["data"]["c"], one["data"]["rows"][one["data"]["r"].index(ex.PPK_FIRST)]))
    assert first["G"].get("i") == "u" and first["L"].get("i") == "u" and "i" not in first["J"] and first["A"]["t"].startswith("MPC1→2")
    first = dict(zip(two["data"]["c"], two["data"]["rows"][two["data"]["r"].index(ex.PPK_FIRST)]))
    assert first["S"].get("i") == "u" and first["P"]["t"] == "MPC1 / MPC2"
    fra = panels["B21"]["data"]
    assert fra["c"][fra["c"].index("T") + 1:fra["c"].index("T") + 4] == ["U", "V", "W"]
    head = dict(zip(fra["c"], fra["rows"][fra["r"].index(335)]))
    assert [head[c]["t"] for c in "UVW"] == ["Hedef FRA", "Gereken bitiş bacağı", "Gereken başl. bacağı"]
    assert dict(zip(fra["c"], fra["rows"][fra["r"].index(337)]))["U"].get("i") == "u"
    fomc = next(p for p in service.view(u, "usd")["panels"] if p["id"] == "fomc")["data"]
    head = dict(zip(fomc["c"], fomc["rows"][fomc["r"].index(73)]))
    assert [head[c]["t"] for c in ex.FOMC_BACK_COLS] == ["Piyasa pencere OIS %", "Pencere OIS (elle) %", "Elle O/N %",
                                                         "Elle adım (bp)", "Elle toplantı adımı %"]
    assert dict(zip(fomc["c"], fomc["rows"][fomc["r"].index(74)]))["AB"].get("i") == "u"


def test_left_out_when_the_tables_are_not_what_they_read():
    """Each way back is the exact inverse of a formula of the workbook: written otherwise, that addition is left out (the
    rest of the dashboard stays); a cell it takes that holds something leaves it out too."""
    path = os.path.join(ROOT, "models", "tto.json.gz")
    tto = Model.load(path)
    ex.SheetBuilder(tto, "OIS_MAIN").patch("D90", "=(EXP(BK90-BL90)-1)*360/(C90-B90)")       # a window on ACT/360
    assert ex.apply("tto", tto) == ["EK_PPK: OIS_MAIN!D90 beklenen formül değil ((EXP(BK90-BL90)-1)*365/(C90-B90) yok)"]
    assert ex.PPK_SHEET not in tto.sheet_index and "EK_TARIH" in tto.sheet_index
    tto = Model.load(path)
    ex.SheetBuilder(tto, "OIS_MAIN").patch("C86", "=$B$2+Motor!$C$9")                         # a window over two meetings
    assert ex.apply("tto", tto) == ["EK_PPK: OIS_MAIN!C86 beklenen formül değil ($B$2+Motor!$C$8 değil)"]
    tto = Model.load(path)
    ex.SheetBuilder(tto, "OIS_MAIN").patch("B110", "=ROUND((D92-D91)*100,2)")                 # a spread in another unit
    assert ex.apply("tto", tto) == ["EK_PPK: OIS_MAIN!B110 beklenen formül değil (ROUND((D92-D91)*10000,2) yok)"]
    tto = Model.load(path)
    ex.SheetBuilder(tto, "Motor").patch("J9", "=INDEX($F$528:$F$4228,C9)")                   # the model's term read a day off
    assert ex.apply("tto", tto) == ["EK_PPK: Motor!J9 beklenen formül değil (INDEX($F$528:$F$4228,MIN(C9,3700)+1) değil)"]
    tto = Model.load(path)
    ex.SheetBuilder(tto, "OIS_MAIN").patch("S400", "=(R400*P400-Q400*O400)/(P400-O400)")       # fills without the market
    problems = ex.apply("tto", tto)
    assert len(problems) == 1 and problems[0].startswith("FRA ikinci bacak: OIS_MAIN!S400 beklenen formül değil")
    assert parse_a1("V400") not in tto.sheet("OIS_MAIN").fml and ex.PPK_SHEET in tto.sheet_index
    tto = Model.load(path)
    tto.sheet("OIS_MAIN").consts[parse_a1("W420")] = "not"
    assert ex.apply("tto", tto) == ["FRA ikinci bacak: OIS_MAIN!W420 boş değil"]
    sofr_path = os.path.join(ROOT, "models", "sofr.json.gz")
    sofr = Model.load(sofr_path)
    ex.SheetBuilder(sofr, "SOFR_FOMC").patch("N77", "=(K77-L77)*100/25")
    assert ex.apply("sofr", sofr) == ["FOMC pencere OIS'ten adım: SOFR_FOMC!N77 beklenen formül değil ((K77-L77)*100/$B$9 yok)"]
    assert parse_a1("AC77") not in sofr.sheet("SOFR_FOMC").fml
    sofr = Model.load(sofr_path)
    sofr.sheet("SOFR_FOMC").consts[parse_a1("AD80")] = 1.0
    assert ex.apply("sofr", sofr) == ["FOMC pencere OIS'ten adım: SOFR_FOMC!AD80 boş değil"]
    # as they fit: the formulas they invert stay as they are (the realized FRA within its two-way cell: an FRA typed shows,
    # else the formula - tests/test_ois_twoway.py)
    tto = Model.load(path)
    before = {a: ex.formula_of(tto, "OIS_MAIN", a) for a in ("D84", "B103", "S336", "S438")}
    assert ex.apply("tto", tto) == []
    after = {a: ex.formula_of(tto, "OIS_MAIN", a) for a in before}
    assert after["D84"] == before["D84"] and after["B103"] == before["B103"]
    for a in ("S336", "S438"):
        store = "$%s%s" % (ex.FRA_TW, a[1:])
        assert after[a] == "IF(ISBLANK(%s),%s,%s)" % (store, before[a], store), a
