"""Each DİBS yield also as its O/N equivalent on TLREF's convention (the desk, 26.11.2026: "Bunların da hepsini yap" - of
the integrator's list after "Toplu forward fiyatlama kısımlarında ON karşılıklarını da görmek istiyorum. Bu ve bunun gibi
başka önerin olur mu", one of them: "Bonds: each DİBS yield also as its ON equivalent on TLREF's convention, so it compares
directly with TLREF and repo"; the convention the desk's "B" of 25.11.2026 - TLREF compounds on business days).

A fixed coupon bond's or a bill's yield is turned into its window's growth - valör to maturity - in the yield's own
convention (a bill's simple ACT/365, 100 / P; a coupon bond's BIST yield compounded CU times a year over the periods its own
sum counts to the maturity), then into the overnight rate x that grows 1 the same as TLREF compounds:
d·ln(1 + x/365) − W·(x/365)² = ln G, W = Σ g(g − 1)/2 over the window's business days on the TRY list
(``extras._rv_on``, ``extras.try_term``; README *Getirinin ON karşılığı*).  Shown beside the yields on DİBS RV (the price in
use's a member of the bonds' two-way table: typed, it prices the row), on its Genel tab, on DİBS Trading's summary, on Tüm
Kâğıtlar and on the card; floaters, FRNs and CPI linkers have none.  Everything here is checked against the row's own cells
worked by hand."""
from __future__ import annotations

import datetime as dt
import math
import os

import pytest

from conftest import ROOT, cell, make_service
from tto import extras as ex
from tto.books import remove_sheets
from tto.service import _pick_columns
from tto.views import load_views
from tto.xl.engine import Clock, Engine
from tto.xl.model import Model
from tto.xl.tokenizer import col_to_index, index_to_col

RV = "DİBS RV"
LIST = "DİBS RV!A5:A54"
ON, ON_BID, ON_ASK = (c for c, _, _ in ex.RV_ON)
STORE = ex.RV_ON_STORE
#: replay's bonds: two bills priced T+0 (ISL0), a short and a long fixed coupon bond (T+1), a TLREF floater, one without a price
BILL, BILL2, FIXED, LONG, FLOATER, NO_PRICE = ("TRB100227T13", "TRB170327T15", "TRT150328T24", "TRT050935T13", "TRT030730T12",
                                               "TRT081128T15")
EPOCH = dt.date(1899, 12, 30)


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """A service of its own: the tests type over cells and move bonds on the desk's list."""
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def put(s, user, cells, adhoc=False):
    res = s.set_inputs(user, "tto", [{"ref": ref, "value": value} for ref, value in cells.items()], allow_adhoc=adhoc)
    assert res["errors"] == [], res["errors"]
    return res


def reader(s, user):
    return lambda addr: cell(s, "%s!%s" % (RV, addr), user)


def row_of(s, user, isin):
    return s._list_values(user, "tto", LIST).index(isin) + 5


def stored(s, user):
    return {ref.split("!")[1]: v for (_, ref), v in s.store.user_inputs(user, "tto").items() if ref.split("!")[0] == RV}


def cell_text(s, user, ref):
    """A cell's text as the pages show it (its own number format, the desk's locale)."""
    from tto.xl import numfmt
    book = s.books["tto"]
    si, rc = book.cell(ref)
    return s.et.call(lambda: s.renderers["tto"].cell(s._calc(user, book), si, *divmod(rc, 16384), numfmt.get_locale("tr"))).get("t", "")


# ---------------------------------------------------------------------------------------------- by hand
def holidays(s, user=None):
    """The desk's TRY list as the workbook reads it (Motor!A361:A523)."""
    first, last = ex.TRY_HOLIDAY_ROWS
    return {d for d in (cell(s, "Motor!A%d" % r, user) for r in range(first, last + 1)) if isinstance(d, float)}


def business(u, hol):
    return (EPOCH + dt.timedelta(days=int(u))).weekday() < 5 and float(u) not in hol


def term_by_hand(a, t, hol):
    """W of the window [a, t): Σ over its days of p, the days since the last business day (Σ g(g − 1)/2 between
    business days a and t)."""
    w, p = 0, 0
    k = 0
    while not business(int(a) - 1 - k, hol):                       # (p of the day before the window)
        k += 1
    p = k
    for u in range(int(a), int(t)):
        p = 0 if business(u, hol) else p + 1
        w += p
    return w


def overnight_by_hand(lng, d, w):
    """x of d·ln(1 + x/365) − W·(x/365)² = ln G (Newton, to the last digit), as a fraction a year."""
    x = math.exp(lng / d) - 1
    for _ in range(50):
        f = d * math.log(1 + x) - w * x * x - lng
        x -= f / (d / (1 + x) - 2 * w * x)
    return 365 * x


def growth_by_hand(R, r, y):
    """ln G of row r's window at the BIST simple yield y in its own convention: a bill's simple ACT/365; a coupon bond's
    (1 + y / f) a period over its periods to the maturity - the current period's fraction left (next coupon − valör over
    the period's length), then whole periods."""
    days = R("CT%d" % r) - R("DC%d" % r)
    if R("CR%d" % r) == "B":
        return math.log(1 + y * days / 365)
    nxt, prev = R("GH%d" % r), R("HF%d" % r)
    periods = R("DO%d" % r) - 1 + (nxt - R("DC%d" % r)) / (nxt - prev)
    return periods * math.log(1 + y / R("CU%d" % r))


def price_by_hand(R, r, on):
    """The clean price at which row r's yield has the O/N equivalent ``on``."""
    days, w = R("CT%d" % r) - R("DC%d" % r), R("%s%d" % (ex.RV_ON_TERM, r))
    g = math.exp(days * math.log(1 + on / 365) - w * (on / 365) ** 2)
    if R("CR%d" % r) == "B":
        return 100 / g - R("CW%d" % r)
    f = R("CU%d" % r)
    nxt, prev = R("GH%d" % r), R("HF%d" % r)
    periods = R("DO%d" % r) - 1 + (nxt - R("DC%d" % r)) / (nxt - prev)
    y = f * (g ** (1 / periods) - 1)
    cfs = [R("%s%d" % (index_to_col(col_to_index("ID") + k), r)) for k in range(24)]
    xs = [R("%s%d" % (index_to_col(col_to_index("LV") + k), r)) for k in range(24)]
    return sum(c * (1 + y / f) ** -x for c, x in zip(cfs, xs) if c) - R("CW%d" % r)


# ---------------------------------------------------------------------------------------------- the convention
@pytest.mark.parametrize("isin", [BILL, BILL2, FIXED, LONG])
def test_a_yields_on_is_tlrefs_on_its_window_worked_by_hand(svc, isin):
    """The O/N equivalent of the yield at the price in use (BO), of the bid (BP) and of the ask (BQ): each yield's growth
    over valör → maturity in its own convention (a bill's 100 / P - its simple and compound yields grow the same; a coupon
    bond's (1 + y / f) a period), then TLREF's overnight rate on business days with the window's own term W - worked here
    from the row's cells and the TRY list, to the last digit.  On business days it is above the rate that compounds every
    calendar day (a weekend earns Friday's rate for three days in one step), by about a bp at TRY's rates; the model's
    second order is within a hundredth of a bp of the exact product Π (1 + x·g)."""
    s = svc
    u = s.login("ON elle %s" % isin)["user"]
    R = reader(s, u)
    r = row_of(s, u, isin)
    hol = holidays(s, u)
    dc, ct = R("DC%d" % r), R("CT%d" % r)
    days, w = ct - dc, term_by_hand(dc, ct, hol)
    assert R("%s%d" % (ex.RV_ON_DAYS, r)) == days and R("%s%d" % (ex.RV_ON_TERM, r)) == w
    for col, y in ((ON, "S"), (ON_BID, "U"), (ON_ASK, "V")):
        lng = growth_by_hand(R, r, R("%s%d" % (y, r)))
        assert R("%s%d" % (col, r)) == pytest.approx(overnight_by_hand(lng, days, w), abs=1e-13), (isin, col)
    # the compound yield grows the window the same: one O/N for the price, whichever yield it is read from (a bill's
    # (1 + T)^(days / 365), a coupon bond's (1 + T)^(periods / f))
    t = R("T%d" % r)
    if R("CR%d" % r) == "B":
        lng_t = days / 365 * math.log(1 + t)
    else:
        nxt, prev = R("GH%d" % r), R("HF%d" % r)
        lng_t = (R("DO%d" % r) - 1 + (nxt - dc) / (nxt - prev)) / R("CU%d" % r) * math.log(1 + t)
    assert lng_t == pytest.approx(growth_by_hand(R, r, R("S%d" % r)), abs=1e-12)
    on = R("%s%d" % (ON, r))
    calendar = 365 * (math.exp(growth_by_hand(R, r, R("S%d" % r)) / days) - 1)
    assert 0.5e-4 < on - calendar < 3e-4, (isin, on, calendar)
    # the exact product over the window's business days (each step x·g, g the days to the next business day)
    x, steps, prev = on / 365, 0.0, int(dc)
    for b in [v for v in range(int(dc) + 1, int(ct) + 1) if business(v, hol)] + ([int(ct)] if not business(ct, hol) else []):
        steps += math.log(1 + x * (b - prev))
        prev = b
    assert abs(steps - growth_by_hand(R, r, R("S%d" % r))) / days * 365 < 0.01e-4


def test_the_term_from_today_and_from_the_spot_is_the_try_lists(svc):
    """W of every priced fixed coupon bond and bill: Σ g(g − 1)/2 over its window's business days on the TRY list - from
    the OIS spot Motor's daily calendar (Pcum, the MPC ima model's term); a T+0 valör (ISL0: today) adds the days to the
    spot.  Floaters and the bond without a price have none (nor an O/N)."""
    s = svc
    u = s.login("ON terim")["user"]
    R = reader(s, u)
    hol = holidays(s, u)
    spot = cell(s, "OIS_MAIN!B2", u)
    seen = {"today": 0, "spot": 0}
    for r in range(5, 55):
        if R("CR%d" % r) not in ("S", "B") or R("DG%d" % r) is not True:
            assert R("%s%d" % (ex.RV_ON_TERM, r)) == "" and R("%s%d" % (ON, r)) == "", r
            continue
        dc, ct = R("DC%d" % r), R("CT%d" % r)
        assert R("%s%d" % (ex.RV_ON_TERM, r)) == term_by_hand(dc, ct, hol), r
        motor = cell(s, "Motor!F%d" % (528 + int(ct - spot)), u)
        assert R("%s%d" % (ex.RV_ON_TERM, r)) == motor + (term_by_hand(dc, spot, hol) if dc < spot else 0)
        seen["today" if dc < spot else "spot"] += 1
    assert seen["today"] == 2 and seen["spot"] >= 12
    for isin in (FLOATER, NO_PRICE):
        r = row_of(s, u, isin)
        assert [R("%s%d" % (c, r)) for c in (ON, ON_BID, ON_ASK)] == ["", "", ""]


#: the days the long windows are counted from: the replay day (a Tuesday), a Saturday and a holiday (Cumhuriyet Bayramı, a
#: Thursday) - "today", a T+0 valör, on each
TODAYS = (dt.date(2026, 11, 3), dt.date(2026, 11, 7), dt.date(2026, 10, 29))


def serial(day):
    return float((day - EPOCH).days)


def prefix_by_hand(hol, lo, hi):
    """Σ p over the days from ``lo`` before each day of [lo, hi] - W(a, t) = P[t] − P[a] -, p counted day by day."""
    k = 0
    while not business(lo - 1 - k, hol):
        k += 1
    p, acc, out = k, 0, {}
    for u in range(int(lo), int(hi) + 1):
        out[u] = acc
        p = 0 if business(u, hol) else p + 1
        acc += p
    return out


@pytest.fixture(scope="module")
def long_book():
    """The TRY workbook with its additions and a few holidays past Motor's daily calendar (OIS spot + 3700 days) in the
    list's spare rows: a Thursday and the Friday after it, a Monday, a Wednesday-Thursday, one on a Saturday, one listed
    twice; and one in the calendar's last days.  An engine for each of ``TODAYS``, its windows from today and from its OIS
    spot: every end day around the calendar's last day, a few inside it, three far past it."""
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    assert ex.apply("tto", model) == []
    b = ex.SheetBuilder(model, "Motor")
    extra = [dt.date(2036, 12, 19), dt.date(2037, 1, 1), dt.date(2037, 1, 2), dt.date(2037, 4, 20), dt.date(2037, 5, 13),
             dt.date(2037, 5, 14), dt.date(2037, 4, 25), dt.date(2037, 1, 1), dt.date(2038, 10, 29)]
    for k, day in enumerate(extra):
        b.set("A%d" % (504 + k), serial(day))
    hol = {v for v in (model.sheet("Motor").consts.get(r * 16384 + 1) for r in range(361, 524)) if isinstance(v, float)}
    assert {serial(d) for d in extra} <= hol
    t = ex.SheetBuilder(model, "ON_TEST")
    cases = {}
    for j, today in enumerate(TODAYS):
        a0 = serial(today)
        spot = a0 + 1
        while not business(spot, hol):
            spot += 1
        end = spot + ex.PCUM_DAYS
        around = range(int(end) - 12, int(end) + 200) if j == 0 else range(int(end) - 3, int(end) + 30)
        windows = [(a, e) for a in (a0, spot) for e in list(around) + [spot + 1, spot + 98, end + 1000, end + 1500, end + 4000]]
        col = index_to_col(1 + j)
        for k, (a, e) in enumerate(windows):
            t.set("%s%d" % (col, k + 1), "=" + ex.try_term(repr(float(a)), repr(float(e))))
        cases[today] = (Engine(model, clock=Clock(a0 + 0.5)), spot, col, windows)
    return cases, hol


def test_a_window_past_motors_calendar_reads_the_holiday_list(long_book):
    """A bond maturing more than 3700 days after the OIS spot (past Motor's daily calendar, the end of 2036 now): the term
    of the days past it comes from the TRY list itself (EK_ISGUNU) - every window to two hundred days past the calendar's
    end, from today (T+0) and from the spot, a few inside it and three far past it, against Σ g(g − 1)/2 counted day by
    day; the holidays added there (a Friday's p on its weekend, a Saturday's nothing, one listed twice once) count as the
    calendar counts them.  Today a Saturday or a holiday: a T+0 valör's days to the spot count from it (p of today)."""
    cases, hol = long_book
    for today, (engine, spot, col, windows) in cases.items():
        calc = engine.shared
        assert calc.value("OIS_MAIN!B2") == spot, today
        pre = prefix_by_hand(hol, serial(today), max(e for _, e in windows))
        for k, (a, e) in enumerate(windows):
            assert calc.value("ON_TEST!%s%d" % (col, k + 1)) == pre[int(e)] - pre[int(a)], (today, a, e)
    assert term_by_hand(serial(TODAYS[1]), serial(TODAYS[1]) + 2, hol) == 3              # (Saturday 1, Sunday 2)
    # the list's pieces: a week-day holiday listed for the first time, its p, the Friday's again
    calc = cases[TODAYS[0]][0].shared
    rows = {calc.value("%s!A%d" % (ex.ISG_SHEET, r)): (calc.value("%s!B%d" % (ex.ISG_SHEET, r)), calc.value("%s!C%d" % (ex.ISG_SHEET, r)))
            for r in range(ex.ISG_FIRST, ex.ISG_LAST + 1)}
    jan1, jan2 = serial(dt.date(2037, 1, 1)), serial(dt.date(2037, 1, 2))
    assert rows[jan1] == (1.0, 0.0) and rows[jan2] == (2.0, 2.0) and serial(dt.date(2037, 4, 25)) not in rows
    assert sum(1 for r in range(ex.ISG_FIRST, ex.ISG_LAST + 1) if calc.value("%s!A%d" % (ex.ISG_SHEET, r)) == jan1) == 1


# ---------------------------------------------------------------------------------------------- two-way
@pytest.mark.parametrize("isin", [BILL2, FIXED, LONG])
def test_an_on_typed_prices_the_row_and_the_others_follow(svc, isin):
    """The O/N equivalent is a member of DİBS RV's two-way table: typed, it stays as typed (✎), the manual clean price is
    the one it gives (its growth over the window as TLREF compounds, back to the yield in the yield's own convention -
    worked here by hand), the row's other members are the sheet's own at that price (another user typing that price sees
    the same row), "Fiyat durumu" says what priced it."""
    s = svc
    u, v = s.login("ON yazılan %s" % isin)["user"], s.login("ON elle fiyat %s" % isin)["user"]
    R, V = reader(s, u), reader(s, v)
    r = row_of(s, u, isin)
    x = R("%s%d" % (ON, r)) + 0.0035
    put(s, u, {"%s!%s%d" % (RV, ON, r): x})
    price = R("N%d" % r)
    assert R("%s%d" % (ON, r)) == x and stored(s, u) == {"%s%d" % (STORE, r): x} and R("YK%d" % r) == ON
    assert price == pytest.approx(price_by_hand(R, r, x), abs=1e-9) and R("O%d" % r) == price
    assert R("J%d" % r) == "ON karşılığından (yazılan)"
    put(s, v, {"%s!N%d" % (RV, r): price})
    for c in ("S", "T", "Y", "Z", "AF", ON_BID, ON_ASK):
        assert R("%s%d" % (c, r)) == pytest.approx(V("%s%d" % (c, r)), abs=1e-9), (isin, c)
    assert V("%s%d" % (ON, r)) == pytest.approx(x, abs=1e-12)                 # (that price's O/N is the one typed)
    s.reset_inputs(u, "tto")
    s.reset_inputs(v, "tto")


@pytest.mark.parametrize("isin", [BILL2, FIXED, LONG])
def test_every_value_typed_back_gives_the_same_row(svc, isin):
    """Round trips: a yield typed -> its O/N; that O/N typed back gives the same price and yields (1e-9); and the O/N typed
    -> the yield, typed back, gives the same O/N.  The last typed wins: typing the yield empties the O/N's store."""
    s = svc
    u = s.login("ON gidiş dönüş %s" % isin)["user"]
    R = reader(s, u)
    r = row_of(s, u, isin)
    members = ("N", "S", "T", "Y", "Z", "AF", ON)
    put(s, u, {"%s!S%d" % (RV, r): R("S%d" % r) + 0.004})
    want = [R("%s%d" % (c, r)) for c in members]
    put(s, u, {"%s!%s%d" % (RV, ON, r): want[-1]})
    assert stored(s, u) == {"%s%d" % (STORE, r): want[-1]}
    assert [R("%s%d" % (c, r)) for c in members] == pytest.approx(want, abs=1e-9)
    put(s, u, {"%s!T%d" % (RV, r): R("T%d" % r)})
    st = stored(s, u)
    assert list(st) == ["YG%d" % r] and st["YG%d" % r] == pytest.approx(want[2], abs=1e-12)
    assert R("%s%d" % (ON, r)) == pytest.approx(want[-1], abs=1e-12)
    s.reset_inputs(u, "tto")


def test_the_on_typed_last_wins_and_delete_goes_back_to_the_market(svc):
    """Typing the O/N empties the row's other typed value (the manual clean price too); a yield typed after it empties
    the O/N's; Delete on the O/N (or on a value worked out from it) takes the row back to the market."""
    s = svc
    u = s.login("ON son yazılan")["user"]
    R = reader(s, u)
    r = row_of(s, u, FIXED)
    cols = ("N", "O", "S", "T", "Z", ON, ON_BID, ON_ASK)
    market = [R("%s%d" % (c, r)) for c in cols]
    put(s, u, {"%s!N%d" % (RV, r): 99.5})
    put(s, u, {"%s!%s%d" % (RV, ON, r): 0.36})
    assert stored(s, u) == {"%s%d" % (STORE, r): 0.36} and R("%s%d" % (ON, r)) == 0.36
    put(s, u, {"%s!S%d" % (RV, r): 0.37})
    assert stored(s, u) == {"YF%d" % r: 0.37} and R("%s%d" % (ON, r)) != 0.36
    put(s, u, {"%s!%s%d" % (RV, ON, r): 0.355})
    res = put(s, u, {"%s!S%d" % (RV, r): ""})                                # Delete on a value worked out from the O/N
    assert stored(s, u) == {} and res["applied"] == 1 and [R("%s%d" % (c, r)) for c in cols] == market
    put(s, u, {"%s!%s%d" % (RV, ON, r): 0.355})
    put(s, u, {"%s!%s%d" % (RV, ON, r): ""})                                  # Delete on the typed O/N itself
    assert stored(s, u) == {} and [R("%s%d" % (c, r)) for c in cols] == market


def test_an_on_the_bond_does_not_have_prices_nothing_and_a_bond_without_a_price_takes_one(svc):
    """A floater has no O/N equivalent here: one typed stays as typed but prices nothing, "Fiyat durumu" says why.  A
    bond with no price is priced by an O/N typed (the inverse needs no price), its yields follow; Delete: blank again."""
    s = svc
    u = s.login("ON olmayan")["user"]
    R = reader(s, u)
    r = row_of(s, u, FLOATER)
    market = [R("%s%d" % (c, r)) for c in ("O", "Z", "AF")]
    put(s, u, {"%s!%s%d" % (RV, ON, r): 0.38})
    assert R("%s%d" % (ON, r)) == 0.38 and R("N%d" % r) == "" and R("YK%d" % r) == ""
    assert [R("%s%d" % (c, r)) for c in ("O", "Z", "AF")] == market
    assert R("J%d" % r).startswith("Yazılan ON karşılık bu kâğıtta yok: fiyat piyasadan · ")
    s.reset_inputs(u, "tto")
    r = row_of(s, u, NO_PRICE)
    assert R("O%d" % r) == "" and R("%s%d" % (ON, r)) == "" and R("DG%d" % r) is False
    put(s, u, {"%s!%s%d" % (RV, ON, r): 0.34})
    price = R("N%d" % r)
    assert R("DG%d" % r) is True and price == pytest.approx(price_by_hand(R, r, 0.34), abs=1e-9) and R("O%d" % r) == price
    assert isinstance(R("S%d" % r), float) and R("J%d" % r) == "ON karşılığından (yazılan)"
    put(s, u, {"%s!%s%d" % (RV, ON, r): ""})
    assert R("O%d" % r) == "" and R("DG%d" % r) is False and stored(s, u) == {}


def test_the_on_is_the_same_on_either_curve_setting(svc):
    """The O/N equivalent reads the yield and the TRY calendar, no curve: a PPK basamak user's is the Bootstrap one's, and
    an O/N typed gives both the same price."""
    s = svc
    boot, ppk = s.login("ON bootstrap")["user"], s.login("ON ppk")["user"]
    s.set_interp(ppk, "ppk")
    B, P = reader(s, boot), reader(s, ppk)
    r = row_of(s, boot, FIXED)
    assert [P("%s%d" % (c, r)) for c in (ON, ON_BID, ON_ASK)] == [B("%s%d" % (c, r)) for c in (ON, ON_BID, ON_ASK)]
    put(s, boot, {"%s!%s%d" % (RV, ON, r): 0.335})
    put(s, ppk, {"%s!%s%d" % (RV, ON, r): 0.335})
    assert P("N%d" % r) == B("N%d" % r)
    s.reset_inputs(boot, "tto")
    s.reset_inputs(ppk, "tto")


def test_a_typed_on_goes_with_its_bond_when_the_list_moves(svc):
    """The desk swaps two bonds of the trading list: the O/N a user typed for one goes with it to its new row (its store
    is in the columns that move with the ISIN) and prices it there; and comes back when the bonds do."""
    s = svc
    u, desk = s.login("ON kayan")["user"], s.login("ON kayan masa")["user"]
    R = reader(s, u)
    a, b = FIXED, "TRT130928T38"
    ra, rb = row_of(s, u, a), row_of(s, u, b)
    put(s, u, {"%s!%s%d" % (RV, ON, ra): 0.3345})
    put(s, desk, {"%s!A%d" % (RV, ra): b, "%s!A%d" % (RV, rb): a})
    try:
        assert stored(s, u) == {"%s%d" % (STORE, rb): 0.3345}
        assert R("%s%d" % (ON, rb)) == 0.3345 and R("%s%d" % (ON, ra)) != 0.3345 and R("YK%d" % ra) == ""
        assert R("N%d" % rb) == pytest.approx(price_by_hand(R, rb, 0.3345), abs=1e-9)
    finally:
        put(s, desk, {"%s!A%d" % (RV, ra): a, "%s!A%d" % (RV, rb): b})
    assert stored(s, u) == {"%s%d" % (STORE, ra): 0.3345} and R("%s%d" % (ON, ra)) == 0.3345
    s.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- where it is shown
def test_dibs_rv_shows_each_on_beside_its_yield(svc):
    """DİBS RV's bonds' table: "ON karşılık %" right of the compound yield, "Alış ON %" right of the bid's yield, "Satış ON
    %" right of the ask's - two decimals as the yields; the ISIN, source and name still kept in view; the helpers and the
    typed O/N's store in a hidden helper table of the page; the group says the O/N is two-way."""
    s = svc
    u = s.login("ON sayfa")["user"]
    p = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")
    d = p["data"]
    at = d["c"].index
    assert d["c"][at("S"):at("S") + 7] == ["S", "T", ON, "U", ON_BID, "V", ON_ASK] and d["fz"] == 3
    assert not set(d["c"]) & {"BK", "BL", "BM", "BN"}                        # ("ASW / DM → temiz fiyat": its own table)
    head = d["rows"][d["r"].index(4)]
    assert [head[at(c)]["t"] for c in (ON, ON_BID, ON_ASK)] == ["ON karşılık %", "Alış ON %", "Satış ON %"]
    r = row_of(s, u, FIXED)
    line = d["rows"][d["r"].index(r)]
    for c in (ON, ON_BID, ON_ASK):
        v = cell(s, "%s!%s%d" % (RV, c, r), u)
        assert line[at(c)]["t"] == ("%.2f%%" % (v * 100)).replace(".", ",") and line[at(c)].get("i") == ("u" if c == ON else None)
    assert "ON karşılık" in p["note"] and "TLREF" in p["note"]
    views = {v["id"]: v for v in load_views()}
    helper = next(x for x in views["dibs"]["panels"] if x["id"] == "on")
    assert helper["hidden"] and helper["range"] == "%s3:%s54" % (STORE, ex.RV_ON_GROWTH[-1])
    g = s.twoway.groups["dibs-rv"]
    assert g.members[-1].name == "ON karşılık" and "ON karşılık" in g.note


def test_dibs_trading_tuem_kagitlar_genel_and_the_card_show_the_on(svc):
    """DİBS Trading's summary: "ON karşılık %" right of "Getiri %" in "OIS'e göre", DİBS RV's for each bond (none for a
    floater); Tüm Kâğıtlar: "ON karşılık % (RV)" right of "Getiri % (RV)" for a bond of the trading list, its first two
    columns kept in view; the card: right after the compound yield; DİBS RV · Genel: in "Getiri", after its two yields."""
    s = svc
    u = s.login("ON özet")["user"]
    d = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L0")["data"]
    heads = [c.get("t") for c in d["rows"][1]]
    assert heads[heads.index("Getiri %") + 1] == s.ON_HEAD
    for isin in (BILL, FIXED, LONG, FLOATER):
        line = next(row for row in d["rows"] if len(row) > 2 and row[2].get("t") == isin)
        want = cell(s, "%s!%s%d" % (RV, ON, row_of(s, u, isin)), u)
        got = line[heads.index(s.ON_HEAD)]
        assert got["t"] == (("%.2f%%" % (want * 100)).replace(".", ",") if isinstance(want, float) else ""), isin
    k = next(p for p in s.view(u, "kagitlar")["panels"] if p["id"] == "U1")["data"]
    caps = k["rows"][k["r"].index(4)]
    i = k["c"].index(ex.UNI_ON[0])
    assert caps[i - 1]["t"] == "Getiri % (RV)" and caps[i]["t"] == ex.UNI_ON[1] and k["fz"] == 2
    by = {row[0].get("t"): row[i]["t"] for row in k["rows"]}
    assert by[FIXED] == ("%.2f%%" % (cell(s, "%s!%s%d" % (RV, ON, row_of(s, u, FIXED)), u) * 100)).replace(".", ",")
    assert by[FLOATER] == "" and by["TRT280432T14"] == ""                     # (a floater; a bond off the trading list)
    rv = [x["name"] for x in s.bond_card(u, FIXED)["rv"]]
    assert rv[rv.index("BIST bileşik getiri") + 1] == "ON karşılık %"
    # DİBS RV · Genel (the entry's first tab): in "Getiri", right of the compound and the simple yield
    t = s.dibsgenel.view(u)["table"]
    assert t["c"][t["c"].index("ysimple") + 1] == "on" and t["rows"][1][t["c"].index("on")]["t"] == "ON karşılık %"
    for isin in (FIXED, FLOATER):
        got = t["rows"][t["isin"].index(isin)][t["c"].index("on")]
        assert got["t"] == cell_text(s, u, "%s!%s%d" % (RV, ON, row_of(s, u, isin))), isin


def test_the_on_is_soft_where_its_price_is_no_live_quote(svc):
    """Worked out of the price in use, the O/N is soft (with the reason) where no live two-sided quote stands behind it -
    on DİBS RV, in the trading summary, on the card and on Tüm Kâğıtlar - as the yields are."""
    s = svc
    u = s.login("ON bayat")["user"]
    r = row_of(s, u, FIXED)
    put(s, u, {"%s!XR%d" % (RV, r): 0, "%s!XS%d" % (RV, r): 0}, adhoc=True)
    d = next(p for p in s.view(u, "dibs")["panels"] if p["id"] == "B3")["data"]
    line = d["rows"][d["r"].index(r)]
    assert "soft" in line[d["c"].index(ON)]["cls"] and "soft" in line[d["c"].index("T")]["cls"]
    assert "soft" not in (line[d["c"].index(ON_BID)].get("cls") or "")
    rows = next(p for p in s.view(u, "dibslive")["panels"] if p["id"] == "L0")["data"]["rows"]
    heads = [c.get("t") for c in rows[1]]
    on = next(row for row in rows if len(row) > 2 and row[2].get("t") == FIXED)[heads.index(s.ON_HEAD)]
    assert "soft" in on["cls"] and "iki taraflı canlı kota yok" in on["tip"]
    assert next(x for x in s.bond_card(u, FIXED)["rv"] if x["name"] == "ON karşılık %").get("soft") is True
    k = next(p for p in s.view(u, "kagitlar")["panels"] if p["id"] == "U1")["data"]
    line = next(row for row in k["rows"] if row[0].get("t") == FIXED)
    assert "soft" in line[k["c"].index(ex.UNI_ON[0])]["cls"] and "soft" in line[k["c"].index("N")]["cls"]
    s.reset_inputs(u, "tto")


def test_a_tables_frozen_columns_stay_when_the_order_keeps_them_first():
    """A page's own order of a table's columns (``cols``): the columns Excel keeps in view stay so when they lead the
    order in their place; otherwise none (as before)."""
    def table(fz):
        return {"c": ["A", "B", "C", "D", "E"], "rows": [[{"t": c} for c in "ABCDE"]], "fz": fz}

    d = table(2)
    _pick_columns(d, ["A", "B", "E", "C", "D"])
    assert d["c"] == ["A", "B", "E", "C", "D"] and d["fz"] == 2
    for cols in (["A", "C", "D"], ["B", "A", "C"], ["A", "B"]):
        d = table(2)
        _pick_columns(d, cols)
        assert "fz" not in d, cols
