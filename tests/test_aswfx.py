"""DİBS ASW's FX swap implied TRY curve (``tto/aswfx.py``): EK_FX's rates read each by its own convention - up to 9M
FX swap implied (TRYI), one period simple ACT/360; from 1Y cross currency swaps (TRYSAQ; 1Y TRYSAQ1, the desk,
18.11.2026), annual ACT/360 par, as the desk's workbook reads them (Forward!AJ123:AN142, C123:K134); 18M no quote but
computed off the offshore XCCY curve, on
each user's curve setting (the desk, 18.11.2026) - and given to the ASW sheet as the par quotes of the sheet's
own convention with the same discount factor at the tenor.  The sheet's formulas are its own (a replica of them that
cannot drift: checked against the engine), its OIS side untouched.  The ASW history on the same curve, day by day: each
past day's offshore closes of the dashboard's own history in the place of that day's OIS quotes (a tenor or a day
without one keeps OIS, and says so), its chart against OIS, the offshore curve or both - each user's choice."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from tto import aswfx
from tto import extras as ex
from tto.xl.errors import XlError
from tto.xl.tokenizer import col_to_index

M = aswfx.TENORS
#: the days from a spot to the sheet's nodes (whole days, a month ~30.4 days), the OIS quotes of its tenors (%) and FX
#: rates (%) for some of them: 9M, 18M, 4Y and 6Y on are not priced (made-up figures of a TRY curve)
DAYS = [float(round(m * 30.4375)) for m in aswfx.NODES]
OIS = [40.0, 39.8, 39.5, 39.0, 38.5, 38.0, 37.0, 36.0, 35.0, 34.0, 33.0, 32.5, 32.0, 31.5, 31.0, 30.5]
FX = [36.0, 36.5, 37.0, 38.0, None, 38.5, None, 42.0, 41.0, None, 40.0, None, None, None, None, None]


def day(m):
    return DAYS[aswfx.node_of(m)]


def df_on(ln, m):
    return math.exp(ln[aswfx.node_of(m)])


def test_each_rate_is_read_by_its_own_convention():
    """TRYI (≤ 9M): one period, simple ACT/360 - an FX swap has no coupons; TRYSAQ (≥ 1Y): annual ACT/360 par over its
    yearly coupon dates, their discount factors the curve's as built so far - as the desk's workbook bootstraps its
    offshore curve (Forward!G125 = 1 / (1 + r·d1/360), G126 = (1 − r·ΣJ) / (1 + r·(d2 − d1)/360), J = G·τ); the 1Y
    (TRYSAQ1) has one coupon: the FX swap's reading.  The kind goes by the tenor; a tenor without an FX price keeps its
    OIS quote."""
    got = aswfx.to_sheet(OIS, FX, DAYS)
    assert [t.months for t in got] == list(M)
    assert [t.kind for t in got] == ["fx", "fx", "fx", "fx", "ois", "xccy", "ois", "xccy", "xccy", "ois", "xccy", "ois", "ois",
                                     "ois", "ois", "ois"]
    by = {t.months: t for t in got}
    for m, r in ((1, 36.0), (2, 36.5), (3, 37.0), (6, 38.0), (12, 38.5)):
        assert by[m].quote == r and by[m].df == pytest.approx(1 / (1 + r / 100 * day(m) / 360), abs=1e-15), m
    # 2Y and 3Y as the desk's sheet chains them: the 1Y discount factor (Forward!G125), then each year's
    g1 = by[12].df
    j1 = g1 * day(12) / 360
    g2 = (1 - 0.42 * j1) / (1 + 0.42 * (day(24) - day(12)) / 360)
    j2 = g2 * (day(24) - day(12)) / 360
    g3 = (1 - 0.41 * (j1 + j2)) / (1 + 0.41 * (day(36) - day(24)) / 360)
    assert (by[24].df, by[36].df) == (pytest.approx(g2, abs=1e-14), pytest.approx(g3, abs=1e-14))
    # 5Y: its 4Y coupon's discount factor is the curve's there - 4Y has no FX price: its OIS quote on the sheet's rule
    ln = aswfx.sheet_curve([t.par for t in got], DAYS)
    coupons = sum((day(y) - (day(y - 12) if y > 12 else 0.0)) / 360 * df_on(ln, y) for y in (12, 24, 36, 48))
    assert by[60].df == pytest.approx((1 - 0.40 * coupons) / (1 + 0.40 * (day(60) - day(48)) / 360), abs=1e-14)
    # no FX price: the OIS quote as it is
    for m in (9, 18, 48, 72, 120):
        k = M.index(m)
        assert (by[m].quote, by[m].df, by[m].par) == (OIS[k], None, OIS[k]), m
    assert [aswfx.kind_of(m) for m in (9, 12, 18, 24)] == ["fx", "xccy", "curve", "xccy"]      # (18M: computed)


def test_the_sheet_is_given_the_par_quote_with_the_same_discount_factor():
    """The round trip: the sheet's own bootstrap (its replica) fed the quotes it is given reproduces, at every priced
    tenor, the discount factor the FX rate gives by its own convention - to the last digits; up to 3M the quote is
    closed form (r·365/360 for an FX swap), from 6M on it is solved for.  Every node of the curve has a value."""
    got = aswfx.to_sheet(OIS, FX, DAYS)
    ln = aswfx.sheet_curve([t.par for t in got], DAYS)
    assert all(type(x) is float for x in ln)
    for t in got:
        if t.kind != aswfx.OIS:
            assert df_on(ln, t.months) == pytest.approx(t.df, abs=1e-12), t.months
    for t in got[:3]:
        assert t.par == pytest.approx(t.quote * 365 / 360, abs=1e-12)
    # a higher FX swap rate: a lower discount factor at its tenor, a higher par quote of the sheet
    up = aswfx.to_sheet(OIS, [x + 1.0 if x is not None else None for x in FX], DAYS)
    assert all(b.df < a.df and b.par > a.par for a, b in zip(got, up) if a.kind == aswfx.FX_SWAP)


def test_the_replica_is_the_sheets_formulas():
    """``sheet_curve`` is ASW row 65 as its formulas read: BT65 = −LN(1 + C65/100·AC65/365); BW65 (6M) =
    LN((1 − F65/100·DJ65) / (1 + F65/100·(AF65 − AE65)/365)) with DJ65 = AE65/365·EXP(BV65); BZ65 (15M) the 1Y and 18M
    quotes interpolated at 3/6; CD65 (27M) 2Y → 3Y at 3/12."""
    ln = aswfx.sheet_curve(OIS, DAYS)
    q = dict(zip(M, OIS))
    assert ln[0] == 0.0 and ln[aswfx.node_of(1)] == -math.log(1 + q[1] / 100 * day(1) / 365)
    h3 = day(3) / 365 * df_on(ln, 3)
    assert ln[aswfx.node_of(6)] == math.log((1 - q[6] / 100 * h3) / (1 + q[6] / 100 * (day(6) - day(3)) / 365))
    h = h3
    for m in range(6, 31, 3):                                       # the annuity up to the node before each
        if m in (15, 27):
            p = q[12] + (q[18] - q[12]) * 3 / 6 if m == 15 else q[24] + (q[36] - q[24]) * 3 / 12
            want = math.log((1 - p / 100 * h) / (1 + p / 100 * (day(m) - day(m - 3)) / 365))
            assert ln[aswfx.node_of(m)] == pytest.approx(want, abs=1e-15), m
        h += (day(m) - day(m - 3)) / 365 * df_on(ln, m)
    assert aswfx.zero_rate(1 / 1.4, 365.0) == pytest.approx(40.0, abs=1e-12)
    assert aswfx.zero_rate(1 / 1.4 ** 2, 730.0) == pytest.approx(40.0, abs=1e-12)
    assert aswfx.zero_rate(None, 365.0) is None and aswfx.zero_rate(0.9, 0.0) is None


def test_what_cannot_be_read_is_none():
    """A tenor whose rate cannot be had in the sheet's convention is None (the service puts #N/A there: the curve stops,
    as the sheet's does at a missing quote) - and so is every tenor whose curve needs it; the ones before stand.  Anything
    but a number is no FX price."""
    # an unpriced tenor without an OIS quote: the curve stops there (the tenors before it stand; an unpriced one after it
    # keeps its OIS quote - the sheet's curve has no value there either)
    ois = list(OIS)
    ois[M.index(9)] = XlError("#N/A")
    got = aswfx.to_sheet(ois, FX, DAYS)
    assert all(t.par is not None for t in got[:4]) and got[4].par is None
    assert all(t.par is None for t in got[5:] if t.kind != aswfx.OIS) and got[M.index(18)].par == OIS[M.index(18)]
    assert all(x is None for x in aswfx.sheet_curve([t.par for t in got], DAYS)[aswfx.node_of(9):])
    # a missing day: that node and every one after it (their annuity runs through it)
    days = list(DAYS)
    days[aswfx.node_of(24)] = None
    got = aswfx.to_sheet(OIS, FX, days)
    assert all(t.par is not None for t in got[:7]) and all(t.par is None for t in got[7:] if t.kind != aswfx.OIS)
    # an XCCY rate no par quote of the sheet reaches (its discount factor ≤ 0)
    fx = list(FX)
    fx[M.index(24)] = 400.0
    got = aswfx.to_sheet(OIS, fx, DAYS)
    assert got[M.index(24)].df is None and got[M.index(24)].par is None and got[M.index(12)].par is not None
    # text, an error, an empty cell: no FX price
    fx = list(FX)
    fx[0], fx[1], fx[2] = "", XlError("#N/A"), None
    assert [t.kind for t in aswfx.to_sheet(OIS, fx, DAYS)[:3]] == ["ois"] * 3


# ---------------------------------------------------------------------------------------------- 18M: computed
def test_an_xccys_coupons_are_counted_back_from_its_maturity():
    """An XCCY's annual coupons are counted back from its maturity, the short period first (the desk, 18.11.2026: "18
    ayda 6 ay + 12 ay olarak kupon ödemesi yapılıyor, sondan başlayıp"): 18M pays at 6M and 18M, 2Y3M at 3M, 15M and 27M;
    a whole number of years yearly, as before.  Its par rate and the bootstrap's step (ACT/360: τ the days between / 360)
    give each other back."""
    assert aswfx.xccy_months(18) == [6, 18] and aswfx.xccy_months(27) == [3, 15, 27]
    assert (aswfx.xccy_months(12), aswfx.xccy_months(24), aswfx.xccy_months(36)) == ([12], [12, 24], [12, 24, 36])
    days, dfs = [181.0, 547.0], [0.85, 0.6]
    par = aswfx.xccy_par(days, dfs)
    assert par == pytest.approx((1 - 0.6) / (181 / 360 * 0.85 + 366 / 360 * 0.6), rel=1e-15)
    assert aswfx.xccy_df(par, days, dfs[:1]) == pytest.approx(0.6, abs=1e-15)
    assert aswfx.xccy_df(0.42, [365.0], []) == pytest.approx(1 / (1 + 0.42 * 365 / 360), abs=1e-16)       # (one period)


def _xccy_nodes(r1, r2, d12, d24):
    """The 1Y and 2Y discount factors of an XCCY curve as the desk's Forward sheet chains them (G125, G126)."""
    df1 = 1 / (1 + r1 / 100 * d12 / 360)
    return df1, (1 - r2 / 100 * d12 / 360 * df1) / (1 + r2 / 100 * (d24 - d12) / 360)


def test_the_18m_point_is_the_offshore_curves_discount_factor_and_its_xccy_par_gives_it_back():
    """18M is no quote: ``point_18m`` reads it off the offshore curve - Bootstrap's ln DF linear between its 1Y and 2Y XCCY
    nodes, PPK basamak's step curve as it is - from the ASW sheet's spot (``shift``: that spot's day on the curve).  Its
    rate is the 18M XCCY par on the same curve with the coupons counted back from the maturity (6M, then 12M): bootstrapped
    back with that schedule (``xccy_df``) it gives the same discount factor at 18M.  Its zero rate is EK_FX's
    (DF^(−365/d) − 1).  A curve with an 18M node of its own is read there as it is."""
    from tto import ppkcurve as pk
    d6, d12, d18, d24 = 181.0, 365.0, 547.0, 731.0
    df1, df2 = _xccy_nodes(39.40, 41.62, d12, d24)
    boot = pk.LogLinear([0.0, 92.0, d6, 273.0, d12, d24, 1096.0],
                        [0.0, -0.084, -0.166, -0.25, math.log(df1), math.log(df2), -1.05])
    ppk = pk.StepCurve([0.0, 37.0, 79.0, 128.0, 400.0, 600.0], [0.40, 0.395, 0.385, 0.37, 0.36, 0.35]).with_shifts(
        [(d12, 0.01), (d24, 0.02)])
    for curve in (boot, ppk):
        for shift in (0.0, 1.0, -1.0):
            pt = aswfx.point_18m(curve, d6, d18, shift)
            base = curve.df(shift)
            dfs = [curve.df(shift + d6) / base, curve.df(shift + d18) / base]
            assert pt.df == pytest.approx(dfs[1], abs=1e-15)
            assert pt.par == pytest.approx(aswfx.xccy_par([d6, d18], dfs) * 100, abs=1e-12)
            assert aswfx.xccy_df(pt.par / 100, [d6, d18], dfs[:1]) == pytest.approx(pt.df, abs=1e-15)      # (round trip)
            assert pt.zero == pytest.approx(aswfx.zero_rate(pt.df, d18), abs=1e-12)
    pt = aswfx.point_18m(boot, d6, d18)
    assert math.log(pt.df) == pytest.approx(math.log(df1) + (math.log(df2) - math.log(df1)) * (d18 - d12) / (d24 - d12), abs=1e-15)
    assert aswfx.point_18m(boot, 181, 547) == pt                                                  # (whole days as ints)
    with18 = pk.LogLinear(boot.days + [d18], boot.lndf + [math.log(0.58)])
    assert aswfx.point_18m(with18, d6, d18).df == pytest.approx(0.58, abs=1e-15)
    assert aswfx.point_18m(None, d6, d18) is None and aswfx.point_18m(boot, None, d18) is None
    assert aswfx.point_18m(boot, d18, d6) is None


def test_the_sheet_is_given_the_18m_point():
    """``to_sheet`` with the 18M point: 18M is a tenor of its own kind ("curve") quoting the point's XCCY par, the sheet
    given the par quote of its own convention that reproduces the point's discount factor at its 18M node (the replica, to
    the last digits).  The tenors before it are as without it, the 2Y XCCY's discount factor too (its coupon is the 1Y
    node) - its par of the sheet another (the curve between 1Y and 2Y is).  Without the point 18M keeps its OIS quote,
    whatever EK_FX has there."""
    plain = aswfx.to_sheet(OIS, FX, DAYS)
    k = M.index(18)
    ln0 = aswfx.sheet_curve([t.par for t in plain], DAYS)
    pt = aswfx.Point(math.exp(ln0[aswfx.node_of(18)]) * 0.99, 39.5, 41.0)          # (another discount factor than OIS's)
    got = aswfx.to_sheet(OIS, FX, DAYS, {18: pt})
    assert (got[k].kind, got[k].quote, got[k].df) == ("curve", 39.5, pt.df) and plain[k].kind == "ois"
    ln = aswfx.sheet_curve([t.par for t in got], DAYS)
    assert all(type(x) is float for x in ln)
    for t in got:
        if t.kind != aswfx.OIS:
            assert math.exp(ln[aswfx.node_of(t.months)]) == pytest.approx(t.df, abs=1e-12), t.months
    assert got[:k] == plain[:k]
    assert got[k + 1].df == pytest.approx(plain[k + 1].df, abs=1e-15) and abs(got[k + 1].par - plain[k + 1].par) > 1e-6
    fx = list(FX)
    fx[k] = 37.0                                                                   # (a rate typed there: no quote of 18M)
    assert aswfx.to_sheet(OIS, fx, DAYS)[k].kind == "ois" and aswfx.to_sheet(OIS, fx, DAYS, {18: None})[k].kind == "ois"


def test_a_past_days_18m_point_from_its_xccy_closes():
    """A past day's 18M (``history_point``): the offshore XCCY curve of that day's TRYSAQ1 and TRYSAQ2 closes on the row's
    own node days - chained as the Forward sheet chains them, ln DF linear between the 1Y and 2Y nodes (Bootstrap: a past
    day has no PPK curve) - read by ``point_18m``.  Without both closes there is none: 18M keeps that day's OIS quote."""
    r1, r2 = 39.4, 41.6
    df1, df2 = _xccy_nodes(r1, r2, day(12), day(24))
    pt = aswfx.history_point((r1, r2), DAYS)
    want = math.log(df1) + (math.log(df2) - math.log(df1)) * (day(18) - day(12)) / (day(24) - day(12))
    assert math.log(pt.df) == pytest.approx(want, abs=1e-15)
    assert pt == aswfx.point_18m(aswfx.xccy_curve([(day(12), r1), (day(24), r2)]), day(6), day(18))
    pars, kinds = aswfx.history_row(OIS, FX, DAYS, (r1, r2))
    assert kinds[M.index(18)] == "curve" and pars == [t.par for t in aswfx.to_sheet(OIS, FX, DAYS, {18: pt})]
    for two in (None, (r1, None), (None, r2)):
        assert aswfx.history_point(two, DAYS) is None and aswfx.history_row(OIS, FX, DAYS, two)[1][M.index(18)] == "ois"


# ---------------------------------------------------------------------------------------------- on the engine
def _sheet(svc):
    book = svc.books["asw"]
    return book, book.model.sheet_index["ASW"], book.model.sheet_index[ex.FXC_SHEET]


def test_the_fx_calculation_is_the_sheets_own_on_those_quotes(service):
    """In the dashboard's calculation on the FX swap curve (``Service._asw_fx_calc``) the sheet's quotes (ASW!C65:R65) are
    ``to_sheet``'s - a priced tenor's par quote, an unpriced one's OIS quote; 18M the computed point's (``_asw_fx_18m``) -
    and the sheet's own discount factor at every priced tenor is the one the FX rate gives by its own convention (18M: the
    offshore curve's).  The replica is the sheet: on the OIS quotes
    and on these it gives the engine's ln discount factors (ASW!BS65:DI65) to the last digit.  The OIS side is untouched:
    the user's calculation keeps its quotes, curve and ASWs while the FX one is made."""
    s = service
    book, si, fi = _sheet(s)
    n, nodes = len(M), len(aswfx.NODES)

    def run():
        base = s._calc(None, book)

        def oisside():
            return ([base.get(si, aswfx.ROW, aswfx.QUOTE_COL + k) for k in range(n)],
                    [base.get(si, aswfx.ROW, aswfx.LN_COL + i) for i in range(nodes)],
                    [base.get(si, r, col_to_index("R")) for r in range(7, 57)])
        before = oisside()
        s._fx_calc_kept = None                                   # (made again now)
        calc, swapped = s._asw_fx_calc(book, None)
        fx = [base.get(fi, ex.FXC_FIRST + k, col_to_index("D")) for k in range(n)]
        days = [base.get(si, aswfx.ROW, aswfx.DAY_COL + i) for i in range(nodes)]
        quotes = [calc.get(si, aswfx.ROW, aswfx.QUOTE_COL + k) for k in range(n)]
        ln = [calc.get(si, aswfx.ROW, aswfx.LN_COL + i) for i in range(nodes)]
        fx_asw = [calc.get(si, r, col_to_index("R")) for r in range(7, 57)]
        return before, oisside(), swapped, fx, days, quotes, ln, fx_asw, s._asw_fx_point(book, None)["point"]
    before, after, swapped, fx, days, quotes, ln, fx_asw, point = s.et.call(run)
    ois_quotes, ois_ln, ois_asw = before
    assert after == before                                                         # the OIS side as it was
    assert all(type(x) is float for x in ois_ln + ln)
    assert aswfx.sheet_curve(ois_quotes, days) == ois_ln                           # the replica is the sheet ...
    assert aswfx.sheet_curve(quotes, days) == ln                                   # ... on the FX side too
    got = aswfx.to_sheet(ois_quotes, fx, days, {18: point})
    priced = [t for t in got if t.kind != aswfx.OIS]
    assert swapped == len(priced) == sum(type(x) is float for x in fx) + 1 and swapped >= 5      # (+ 18M: no quote in EK_FX)
    assert {t.kind for t in priced} == {"fx", "xccy", "curve"}                     # (every kind on the recorded day)
    for k, t in enumerate(got):
        assert quotes[k] == t.par, t.months                                        # what the sheet is given
        if t.kind == aswfx.OIS:
            assert quotes[k] == ois_quotes[k]
        else:
            assert math.exp(ln[aswfx.node_of(t.months)]) == pytest.approx(t.df, abs=1e-12), t.months
    # the bonds are priced off it: another ASW than OIS's wherever the curve differs
    assert sum(type(a) is float and type(b) is float and abs(a - b) > 1.0 for a, b in zip(fx_asw, ois_asw)) >= 10


# ---------------------------------------------------------------------------------------------- the history offshore
def test_the_history_series_of_each_tenor():
    """A past day's offshore rate of each tenor is the dashboard's own history (tto/history.py), by months and the
    tenor's kind: the FX swap implied yield (group "off": TRYI1M … TRYI9M) or the cross currency swap ("xccy": TRYSAQ1
    … 10); none at 18M - computed from TRYSAQ1 and TRYSAQ2 (``history_pair``).  1Y is TRYSAQ1 as today's EK_FX has it
    (the desk, 18.11.2026), even were an FX swap implied 12M kept."""
    from types import SimpleNamespace as S
    defs = [S(group="ref", months=None, id="TLREF")] + \
        [S(group="off", months=m, id="TRYI%s" % t) for m, t in ((0.01, "ON"), (0.25, "1W"), (1.0, "1M"), (2.0, "2M"), (3.0, "3M"),
                                                                 (4.0, "4M"), (6.0, "6M"), (9.0, "9M"))] + \
        [S(group="xccy", months=12.0 * y, id="TRYSAQ%d" % y) for y in range(1, 11)] + [S(group="ois", months=18.0, id="TYSO1F")]
    got = [d.id if d is not None else None for d in aswfx.history_series(defs)]
    assert got == ["TRYI1M", "TRYI2M", "TRYI3M", "TRYI6M", "TRYI9M", "TRYSAQ1", None] + ["TRYSAQ%d" % y for y in range(2, 11)]
    assert aswfx.history_series(defs + [S(group="off", months=12.0, id="TRYI12M")])[M.index(12)].id == "TRYSAQ1"
    assert aswfx.history_series([d for d in defs if d.id != "TRYSAQ1"] + [S(group="off", months=12.0, id="TRYI12M")])[
        M.index(12)] is None                                                                  # (no TRYSAQ1: none)
    assert aswfx.history_series([d for d in defs if d.id != "TRYI6M"] + [S(group="xccy", months=6.0, id="TRYSAQ6M")])[
        M.index(6)] is None                                                                   # (each in its kind's group)
    assert [d.id for d in aswfx.history_pair(defs + [S(group="off", months=12.0, id="TRYI12M")])] == ["TRYSAQ1", "TRYSAQ2"]
    assert aswfx.history_series(defs + [S(group="off", months=18.0, id="TRYI18M")])[M.index(18)] is None
    assert aswfx.history_pair([d for d in defs if d.id != "TRYSAQ2"]) is None


def _weekdays(start, end):
    d, e = (dt.date(int(x[:4]), int(x[4:6]), int(x[6:])) for x in (start, end))
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    """A service of its own with the ASW history filled as Bloomberg would fill it - the sheet's history blocks (B66, D66
    … R66, S66, U66 … W66: made-up closes for the week days of its window: the OIS quotes around today's, TLREF, the
    bonds' prices) - and the dashboard's history of the offshore closes of every tenor's series (ICPL), but none at all
    on one day and none of 9M on another; on a third day 1M only from the backup source (BGN); on a fourth no TRYSAQ2 (2Y,
    and so no 18M)."""
    from conftest import make_service
    from tto.marketdata.replay import addin_callers
    from tto.xl.model import COLS, a1
    from tto.xl.tokenizer import index_to_col
    from tto.xl.values import XlArray, date_to_serial
    svc = make_service(tmp_path_factory.mktemp("aswhist"))
    try:
        book = svc.books["asw"]
        eng, si = book.engine, book.model.sheet_index["ASW"]

        def read():
            keys = {}
            for key, cells in addin_callers(eng).items():
                for s, rc in cells:
                    if s == si and rc // COLS == aswfx.HIST_FIRST and key[0] == "BDH":
                        keys[a1(rc)] = key
            ois = [eng.shared.get(si, aswfx.ROW, aswfx.QUOTE_COL + k) for k in range(len(M))]
            return keys, ois, [eng.shared.get(si, aswfx.ROW, col_to_index(c)) for c in "UVW"]
        keys, ois, prices = svc.et.call(read)
        days = _weekdays(keys["B66"][3], keys["B66"][4])
        n = len(days)
        blocks = {}
        for k in range(len(M)):
            closes = [round(ois[k] + 0.8 * (n - 1 - i) / n + 0.15 * math.sin(i / 3.0 + k), 4) for i in range(n)]
            if k == 0:
                blocks[keys["B66"]] = XlArray([[float(date_to_serial(d)), v] for d, v in zip(days, closes)])
            else:
                blocks[keys["%s66" % index_to_col(aswfx.QUOTE_COL + k)]] = XlArray([[v] for v in closes])
        blocks[keys["S66"]] = XlArray([[39.5 - 0.5 * i / n] for i in range(n)])
        for col, p in zip("UVW", prices):
            p = p if type(p) is float else 99.0
            blocks[keys[col + "66"]] = XlArray([[round(p - 1.5 * (n - 1 - i) / n + 0.2 * math.cos(i / 4.0), 4)] for i in range(n)])
        svc.et.call(svc._apply_market, svc.provider.update(blocks))
        series = aswfx.history_series(svc.history.snapshot()["defs"])
        none, no9, bgn, no2y = days[10].isoformat(), days[20].isoformat(), days[30].isoformat(), days[40].isoformat()
        for k, s in enumerate(series):
            if s is None:
                continue
            level = 34.0 + 0.4 * k
            pts = [(d.isoformat(), round(level + 0.5 * math.sin(i / 5.0 + k) + 0.6 * (n - i) / n, 4)) for i, d in enumerate(days)]
            svc.store.hist_upsert(s.id, [(d, v) for d, v in pts if d != none and not (M[k] == 9 and d == no9)
                                         and not (M[k] == 1 and d == bgn) and not (M[k] == 24 and d == no2y)])
            if M[k] == 1:
                svc.store.hist_upsert(s.ids()[1], [(d, v + 0.3) for d, v in pts if d != none])    # the backup (BGN)
        svc.history.rev += 1                                                     # (what the history does when it stores)
        yield svc, days, (none, no9, bgn, no2y)
    finally:
        svc.stop()


def _row_of(days, iso):
    """The history's row of a day (oldest first from row 66)."""
    return aswfx.HIST_FIRST + days.index(dt.date.fromisoformat(iso))


def _hist_state(svc, user=None):
    """The history on both curves: per past row its day, OIS quotes, node days, the offshore calculation's quotes, ln
    discount factors and ASW 1–3, the OIS calculation's ASW 1–3; the offshore calculation's info."""
    book = svc.books["asw"]
    si = book.model.sheet_index["ASW"]

    def run():
        base = svc._calc(user, book)
        layer, info = svc._asw_hist_fx(book, user)
        out = {}
        for r in sorted(info["n"]):
            out[r] = {"day": base.get(si, r, aswfx.HIST_DATE_COL),
                      "ois": [base.get(si, r, aswfx.QUOTE_COL + k) for k in range(len(M))],
                      "days": [base.get(si, r, aswfx.DAY_COL + i) for i in range(len(aswfx.NODES))],
                      "quotes": [layer.get(si, r, aswfx.QUOTE_COL + k) for k in range(len(M))],
                      "ln": [layer.get(si, r, aswfx.LN_COL + i) for i in range(len(aswfx.NODES))],
                      "asw": [layer.get(si, r, col_to_index(c)) for c in "XYZ"],
                      "asw_ois": [base.get(si, r, col_to_index(c)) for c in "XYZ"]}
        return layer, info, out
    return svc.et.call(run)


def _offshore_closes(svc, days, day):
    """The offshore close of each tenor on ``day`` as the dashboard's history has it over the history's days: the first
    source's, else the backup's move laid on the first one's level (``SeriesDef.merged``)."""
    series = aswfx.history_series(svc.history.snapshot()["defs"])
    lo, hi = days[0].isoformat(), days[-1].isoformat()
    return [s.merged(svc.store.hist_many(s.ids(), lo, hi))[1].get(day) if s is not None else None for s in series]


def _xccy_closes(svc, days, day):
    """TRYSAQ1's and TRYSAQ2's closes on ``day`` (``aswfx.history_pair``), as ``_offshore_closes`` reads them."""
    pair = aswfx.history_pair(svc.history.snapshot()["defs"])
    lo, hi = days[0].isoformat(), days[-1].isoformat()
    return tuple(s.merged(svc.store.hist_many(s.ids(), lo, hi))[1].get(day) for s in pair)


def _oracle(svc, rows):
    """Past rows of the sheet with quotes of their own (``{row: quotes}``), worked out another way: a second engine of
    the same workbook (its inputs as the desk has them) whose Bloomberg history blocks are fixed - pinned - to what the
    service's calculation holds in them, each row's quotes to its own.  Their ASW 1–3."""
    from tto.books import Book
    from tto.xl.model import COLS
    book = svc.books["asw"]
    eng, si = book.engine, book.model.sheet_index["ASW"]
    sh = book.model.sheets[si]

    def run():
        other = Book("asw-oracle", "", book.model, provider=eng.provider, clock=eng.clock)
        other.engine.set_inputs({(s, rc): v for s, vals in enumerate(eng.input_value) for rc, v in vals.items()})
        pins = {}
        for anchor, (r1, c1, r2, c2) in sh.arr.items():
            if anchor // COLS == aswfx.HIST_FIRST and (r1, c1) != (r2, c2):
                pins.update({(si, r * COLS + c): eng.shared.get(si, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)})
        for row, quotes in rows.items():
            pins.update({(si, row * COLS + aswfx.QUOTE_COL + k): q for k, q in enumerate(quotes)})
        other.engine.set_pins(pins)
        return {row: [other.engine.shared.get(si, row, col_to_index(c)) for c in "XYZ"] for row in rows}
    return svc.et.call(run)


def test_each_past_day_is_the_sheets_calculation_on_that_days_offshore_quotes(hist):
    """A past row of the ASW history on the offshore curve: its quotes are that day's offshore closes of the dashboard's
    history (each tenor's series, the first source with a close - the backup's on a day the first has none), each read by
    its own convention and given as the par quote of the sheet's convention with the same discount factor - ``to_sheet``,
    as today's FX quotes are; 18M computed from that day's TRYSAQ1 and TRYSAQ2 closes (``history_point``).  The curve is
    the sheet's own formulas on them (its replica, to the last digit), at every priced tenor the discount factor the rate
    gives by its own convention; the bonds' ASW is the sheet's own - a second engine with the rows' quotes pinned gives
    the same - and another than OIS's.  The OIS calculation is untouched."""
    from tto.xl.values import serial_to_date
    svc, days, (none, no9, bgn, _) = hist
    before = _hist_state(svc)[2]
    layer, info, rows = _hist_state(svc)
    assert info["days"] == len(days) == len(rows) >= 100 and info["offshore"] == len(days) - 1
    assert [serial_to_date(rows[r]["day"]) for r in sorted(rows)] == days                       # (oldest first)
    priced = [k for k in range(3) if type(rows[aswfx.HIST_FIRST]["asw_ois"][k]) is float]
    assert priced                                                                                # (a bond with a price history)
    picked = sorted(set(sorted(rows)[::23] + [_row_of(days, bgn), aswfx.HIST_FIRST + len(days) - 1]))
    for r in picked:
        x = rows[r]
        iso = serial_to_date(x["day"]).isoformat()
        point = aswfx.history_point(_xccy_closes(svc, days, iso), x["days"])
        got = aswfx.to_sheet(x["ois"], _offshore_closes(svc, days, iso), x["days"], {18: point})
        assert [t.kind for t in got][M.index(18)] == aswfx.CURVE and info["n"][r] == 16
        for k, t in enumerate(got):
            assert x["quotes"][k] == (t.par if t.kind != aswfx.OIS else x["ois"][k]), (r, M[k])
            if t.kind != aswfx.OIS:
                assert math.exp(x["ln"][aswfx.node_of(t.months)]) == pytest.approx(t.df, abs=1e-12), (r, M[k])
        assert aswfx.sheet_curve(x["quotes"], x["days"]) == x["ln"]                       # the sheet's own formulas
        for k in priced:
            assert type(x["asw"][k]) is float and abs(x["asw"][k] - x["asw_ois"][k]) > 0.5, (r, k)
    oracle = _oracle(svc, {r: rows[r]["quotes"] for r in picked})
    for r in picked:
        assert [type(a) for a in oracle[r]] == [type(a) for a in rows[r]["asw"]], r
        assert [a for a in oracle[r] if type(a) is float] == pytest.approx([a for a in rows[r]["asw"] if type(a) is float], abs=1e-9), r
    assert len(picked) >= 6
    # the day 1M has only the backup source's close: offshore all the same
    assert info["kinds"][_row_of(days, bgn)][0] == aswfx.FX_SWAP
    # nothing of the OIS side moved
    assert {r: (v["asw_ois"], v["ois"]) for r, v in before.items()} == {r: (v["asw_ois"], v["ois"]) for r, v in rows.items()}


def test_today_is_the_asw_tables_asw_fx(hist):
    """The history's last row is today: on the offshore side its ASW is the ASW table's "ASW FX ima" of the same bond -
    in the calculation and on the page (the history table's offshore column, the table's ASW FX column)."""
    svc, _, _ = hist
    book = svc.books["asw"]
    si = book.model.sheet_index["ASW"]

    def run():
        base = svc._calc(None, book)
        layer, info = svc._asw_hist_fx(book, None)
        fx, swapped = svc._asw_fx_calc(book, None)
        isins = [base.get(si, r, col_to_index("C")) for r in (59, 60, 61)]
        rows = {base.get(si, r, col_to_index("B")): r for r in range(7, 57)}
        return ([layer.get(si, aswfx.ROW, col_to_index(c)) for c in "XYZ"],
                [fx.get(si, rows[i], col_to_index("R")) if i in rows else None for i in isins], isins, info, swapped)
    today, table, isins, info, swapped = svc.et.call(run)
    assert info["today"] == swapped >= 5
    shown = [k for k in range(3) if type(table[k]) is float]
    assert shown and all(today[k] == pytest.approx(table[k], abs=1e-9) for k in shown)
    page = {p["id"]: p for p in svc.view(None, "asw")["panels"]}
    hist_t, tbl = page["hist"]["data"], page["tbl"]["data"]
    row = hist_t["rows"][hist_t["r"].index(aswfx.ROW)]
    j, b, fxc = hist_t["c"].index("ASW 1 off"), tbl["c"].index("B"), tbl["c"].index("ASW FX")
    for k in shown:
        mine = next(r for r in tbl["rows"] if len(r) > fxc and r[b].get("t") == isins[k])
        assert row[j + k]["t"] == mine[fxc]["t"] and row[j + k]["v"] == pytest.approx(mine[fxc]["v"], abs=1e-9)
    assert row[j + 3]["t"] == "%d / 16" % swapped


def test_a_day_without_any_offshore_close_is_left_empty_and_a_missing_tenor_keeps_ois(hist):
    """No offshore close at all on a day: no offshore ASW that day - its offshore cells are empty, "Offshore vade" says
    0 / 16 ("o gün offshore kapanışı yok"); the chart leaves a gap there (below).  A tenor without a close (9M on another
    day; 2Y on a third, and with it 18M, computed from TRYSAQ1 and TRYSAQ2) keeps that day's OIS quote - the live rule:
    15 / 16, 14 / 16, the cell's tip naming them.  Today without any FX rate in EK_FX (the ASW FX column empty too) is
    such a day as well."""
    svc, days, (none, no9, _, no2y) = hist
    _, info, rows = _hist_state(svc)
    r0, r9, r2 = _row_of(days, none), _row_of(days, no9), _row_of(days, no2y)
    assert info["n"][r0] == 0 and info["kinds"][r0] == [aswfx.OIS] * len(M) and info["none"] == {r0}
    k18, k24 = M.index(18), M.index(24)
    assert all((rows[r]["quotes"][k18] == rows[r]["ois"][k18]) == (r in (r0, r2)) for r in rows)
    assert rows[r2]["quotes"][k24] == rows[r2]["ois"][k24] and info["n"][r2] == 14
    k9 = M.index(9)
    assert rows[r9]["quotes"][k9] == rows[r9]["ois"][k9] and info["n"][r9] == 15
    assert rows[r9]["quotes"][k9 - 1] != rows[r9]["ois"][k9 - 1]                         # (6M that day: offshore)
    t = {p["id"]: p for p in svc.view(None, "asw")["panels"]}["hist"]["data"]
    assert t["added"] == 4 and t["c"][-4:] == ["ASW 1 off", "ASW 2 off", "ASW 3 off", "Off vade"]
    head = t["rows"][t["r"].index(aswfx.ROW - 1)]
    assert [c["t"] for c in head[-4:]] == ["ASW 1 offshore", "ASW 2 offshore", "ASW 3 offshore", "Offshore vade"]
    count = {r: t["rows"][t["r"].index(r)][-1] for r in (r0, r9, r2, aswfx.HIST_FIRST)}
    assert [count[r]["t"] for r in (r0, r9, r2, aswfx.HIST_FIRST)] == ["0 / 16", "15 / 16", "14 / 16", "16 / 16"]
    assert count[r0]["tip"] == "o gün offshore kapanışı yok" and count[r0]["cls"] == "soft"
    assert count[r9]["tip"] == "Offshore: 1M 2M 3M 6M 1Y 18M 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y · OIS: 9M"
    assert count[r2]["tip"] == "Offshore: 1M 2M 3M 6M 9M 1Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y · OIS: 18M 2Y"
    shown = t["rows"][t["r"].index(r0)]
    assert [c.get("t") for c in shown[-4:-1]] == ["", "", ""] and not any("v" in c for c in shown[-4:-1])
    assert any(c.get("v") is not None for c in shown[-7:-4])                            # (the OIS ASWs stand)
    # today without an FX rate (no tenor priced in EK_FX): no offshore point today either
    real = svc._asw_fx_calc
    svc._asw_fx_calc = lambda book, user: (None, 0)
    try:
        assert svc.et.call(svc._asw_hist_fx, svc.books["asw"], None)[1]["none"] == {r0, aswfx.ROW}
        svc.bump()                                                               # (the page made again)
        today = {p["id"]: p for p in svc.view(None, "asw")["panels"]}["hist"]["data"]
        today = today["rows"][today["r"].index(aswfx.ROW)]
        assert [c.get("t") for c in today[-4:]] == ["", "", "", "0 / 16"] and today[-1]["tip"] == "bugün EK_FX'te FX faizi yok"
    finally:
        svc._asw_fx_calc = real
        svc.bump()


def test_the_history_chart_for_each_choice(hist):
    """The history chart, drawn as each user chooses (Parametreler's "Geçmiş grafiği", ASW!N3, or the chart's own small
    selector - the same cell): OIS by default - the workbook's chart as it was -, Offshore (the same chart on the offshore
    calculation, each bond "· offshore") or İkisi (both: the OIS series, then the offshore ones dashed).  A day without
    any offshore close has no offshore point: a gap in the offshore line - the OIS line goes on through it.  One user's
    choice is theirs; anything but the three is refused.  A user whose only input is the choice reads everybody's
    offshore history (no calculation of their own for it)."""
    from tto.xl import numfmt
    from tto.xl.values import date_to_serial
    svc, days, (none, _, _, _) = hist
    book = svc.books["asw"]
    spec = book.model.sheets[book.model.sheet_index["ASW"]].charts[1]

    def charts(user):
        def run():
            loc = numfmt.get_locale(svc.settings.locale)
            R = svc.renderers["asw"]
            return R.chart(svc._calc(user, book), spec, loc), R.chart(svc._asw_hist_fx(book, user)[0], spec, loc)
        return svc.et.call(run)

    def chart1(user):
        return next(p for p in svc.view(user, "asw")["panels"] if p["id"] == "chart1")

    ali, veli = (svc.login(n)["user"] for n in ("asw geçmiş ali", "asw geçmiş veli"))
    ois, off = charts(ali)
    gap = float(date_to_serial(dt.date.fromisoformat(none)))
    off_data = [[None if x == gap else v for x, v in zip(s["x"], s["data"])] for s in off["series"]]
    priced = [k for k, s in enumerate(ois["series"]) if type(s["data"][s["x"].index(gap)]) is float]
    assert priced and all(type(off["series"][k]["data"][off["series"][k]["x"].index(gap)]) is float for k in priced)
    c = chart1(ali)
    assert c["pick"] == {"ref": "ASW!N3", "book": "asw", "value": "OIS", "options": ["OIS", "Offshore", "İkisi"], "default": "OIS"}
    assert c["data"] == ois and c["title"] == "ASW geçmişi (son nokta canlı)" and len(ois["series"]) == 3
    assert len(ois["series"][1]["data"]) == len(days) + 1                                   # (the past days, then today)
    assert not svc.set_inputs(ali, "asw", [{"ref": "ASW!N3", "value": "fx"}])["errors"]     # (a word for it: Offshore)
    c = chart1(ali)
    assert c["pick"]["value"] == "Offshore" and c["title"] == "ASW geçmişi · offshore eğrisine göre (son nokta canlı)"
    assert [s["name"] for s in c["data"]["series"]] == ["%s · offshore" % (s["name"] or "Kâğıt %d" % (k + 1))
                                                        for k, s in enumerate(ois["series"])]
    assert [s["data"] for s in c["data"]["series"]] == off_data != [s["data"] for s in ois["series"]]
    for k in priced:                                          # (the gap: that day only, the days around it drawn)
        x, data = c["data"]["series"][k]["x"], c["data"]["series"][k]["data"]
        i = x.index(gap)
        assert data[i] is None and type(data[i - 1]) is float and type(data[i + 1]) is float
    assert "Offshore faizli gün: %d / %d" % (len(days) - 1, len(days)) in c["note"]
    assert chart1(veli)["pick"]["value"] == "OIS" and chart1(veli)["data"] == ois             # (ali's choice is ali's)
    assert (ali, svc.HIST_FX) not in book.engine.layers and ("", svc.HIST_FX) in book.engine.layers
    assert not svc.set_inputs(ali, "asw", [{"ref": "ASW!N3", "value": "ikisi"}])["errors"]
    c = chart1(ali)
    assert c["pick"]["value"] == "İkisi" and len(c["data"]["series"]) == 6
    assert [s["data"] for s in c["data"]["series"]] == [s["data"] for s in ois["series"]] + off_data
    assert [s.get("dash") for s in c["data"]["series"]] == [None] * 3 + [1] * 3
    assert [s["name"] for s in c["data"]["series"][:3]] == ["%s · OIS" % (s["name"] or "Kâğıt %d" % (k + 1))
                                                             for k, s in enumerate(ois["series"])]
    assert "listede yok" in svc.set_inputs(ali, "asw", [{"ref": "ASW!N3", "value": "TLREF"}])["errors"][0]
    assert chart1(ali)["pick"]["value"] == "İkisi"
    svc.reset_inputs(ali, "asw", ["ASW!N3"])
    assert chart1(ali)["pick"]["value"] == "OIS" and chart1(ali)["data"] == ois


def test_the_ois_history_is_shown_as_before(hist):
    """With the offshore side beside it, the history table's own columns are the sheet's range as the renderer draws it
    (the four offshore columns are the dashboard's, after them) and the chart on OIS is the workbook's chart."""
    from tto.xl import numfmt
    svc, _, _ = hist
    book = svc.books["asw"]
    page = {p["id"]: p for p in svc.view(None, "asw")["panels"]}
    t = page["hist"]["data"]

    def run():
        loc = numfmt.get_locale(svc.settings.locale)
        R = svc.renderers["asw"]
        calc = svc._calc(None, book)
        spec = book.model.sheets[book.model.sheet_index["ASW"]].charts[1]
        return R.table(calc, "ASW", "A62:Z326", loc, None, show_hidden=False), R.chart(calc, spec, loc)
    plain, chart = svc.et.call(run)
    n = len(plain["c"])
    assert t["c"][:n] == plain["c"] and t["r"] == plain["r"] and [row[:n] for row in t["rows"]] == plain["rows"]
    assert all(len(row) == n + 4 for row in t["rows"]) and page["chart1"]["data"] == chart


# ---------------------------------------------------------------------------------------------- 18M on the engine
def _point_state(svc, user):
    """A user's 18M as the service has it, and what it is read from: the 18M point (``_asw_fx_point``), the Forward
    sheet's offshore curve (AK124:AK143 days from the FX spot, AM ln DF), the user's offshore PPK curve, the ASW sheet's
    6M / 18M node days and the spots; on the FX swap curve the sheet's ln DF at 18M and its bonds' ASW and years."""
    from tto import ppkcurve as pk
    asw, tto = svc.books["asw"], svc.books["tto"]
    si = asw.model.sheet_index["ASW"]

    def run():
        calc, _ = svc._asw_fx_calc(asw, user)
        x18 = svc._asw_fx_point(asw, user)
        base, tc = svc._calc(user, asw), svc._calc(user, tto)
        fwd = tto.model.sheet_index["Forward"]
        boot = pk.LogLinear([tc.get(fwd, r, col_to_index("AK")) for r in range(124, 144)],
                            [tc.get(fwd, r, col_to_index("AM")) for r in range(124, 144)])
        xccy = [(tc.get(fwd, r, col_to_index("AK")), tc.get(fwd, r, col_to_index("AM"))) for r in (134, 135)]   # 1Y, 2Y
        d = {m: base.get(si, aswfx.ROW, aswfx.DAY_COL + aswfx.node_of(m)) for m in (6, 18)}
        shift = base.get(si, aswfx.ROW, col_to_index("T")) - tc.get(fwd, 2, col_to_index("I"))
        return {"x18": x18, "boot": boot, "xccy": xccy, "ppk": svc._try_curves(tto, tc)["off_ppk"], "d": d, "shift": shift,
                "ln18": calc.get(si, aswfx.ROW, aswfx.LN_COL + aswfx.node_of(18)),
                "asw": {r: calc.get(si, r, col_to_index("R")) for r in range(7, 57)},
                "years": {r: base.get(si, r, col_to_index("J")) for r in range(7, 57)},
                "ois18": base.get(si, aswfx.ROW, aswfx.QUOTE_COL + M.index(18))}
    return svc.et.call(run)


def test_the_18m_point_on_each_users_curve_setting(hist):
    """18M of the FX swap curve is computed, never a quote (the desk, 18.11.2026: "TRYI18M gerçek bir kotasyon değil ...
    Zero'yu oradan bulmamız gerekli. Bunun da interpolasyonu PPK'yı seçersem PPK'ya gelmeli"): the offshore curve's
    discount factor at the ASW sheet's 18M node day, on the user's own setting - Bootstrap: the Forward sheet's curve, ln DF
    linear between its 1Y (TRYSAQ1) and 2Y (TRYSAQ2) nodes; PPK basamak: the offshore PPK curve of the user's own
    calculation.  The sheet reproduces it at its 18M node and prices the bonds of one to three years off it (another ASW
    FX on each setting; the shorter ones as before).  Its rate, the 18M XCCY par on the same curve with the coupons counted
    back from the maturity (6M, then 12M), bootstrapped back gives the same discount factor.  On the recorded day
    (03.11.2026) TRYI18M had no price - 18M stood on its OIS quote, 35,59 -: now 39,59 on Bootstrap, 39,38 on PPK basamak."""
    svc, _, _ = hist
    on_boot, on_ppk = (svc.login(n)["user"] for n in ("18A bootstrap", "18A ppk"))
    svc.set_interp(on_ppk, "ppk")
    b, p = _point_state(svc, on_boot), _point_state(svc, on_ppk)
    assert (b["x18"]["mode"], b["x18"]["label"]) == ("boot", "hesaplanan (XCCY 1Y–2Y, Bootstrap)")
    assert (p["x18"]["mode"], p["x18"]["label"]) == ("ppk", "hesaplanan (XCCY 1Y–2Y, PPK basamak)")
    # Bootstrap: between the 1Y and 2Y XCCY nodes, ln DF linear in days (from the ASW sheet's spot: shift)
    (t1, l1), (t2, l2) = b["xccy"]
    t = b["shift"] + b["d"][18]
    assert t1 < t < t2
    ln_at = (lambda x: l1 + (l2 - l1) * (x - t1) / (t2 - t1))                                 # noqa: E731
    assert b["x18"]["point"].df == pytest.approx(math.exp(ln_at(t)) / b["boot"].df(b["shift"]), abs=1e-14)
    # PPK basamak: the user's offshore PPK curve there
    sh = p["shift"]
    assert p["x18"]["point"].df == pytest.approx(p["ppk"].df(sh + p["d"][18]) / p["ppk"].df(sh), abs=1e-15)
    assert abs(p["x18"]["point"].df - b["x18"]["point"].df) > 1e-4
    for s, curve in ((b, b["boot"]), (p, p["ppk"])):
        pt, d, sh = s["x18"]["point"], s["d"], s["shift"]
        assert math.exp(s["ln18"]) == pytest.approx(pt.df, abs=1e-12)                    # (the sheet's 18M node)
        df6 = curve.df(sh + d[6]) / curve.df(sh)
        assert aswfx.xccy_df(pt.par / 100, [d[6], d[18]], [df6]) == pytest.approx(pt.df, abs=1e-15)    # (6M + 12M)
        assert pt.zero == pytest.approx(aswfx.zero_rate(pt.df, d[18]), abs=1e-12)
    assert 39.5 < b["x18"]["point"].par < 39.7 and 39.3 < p["x18"]["point"].par < 39.45 and b["ois18"] == 35.59
    short = [r for r, y in b["years"].items() if type(y) is float and y < 0.95 and type(b["asw"][r]) is float]
    mid = [r for r, y in b["years"].items() if type(y) is float and 1.05 < y < 3.0 and type(b["asw"][r]) is float]
    assert short and mid and all(b["asw"][r] == p["asw"][r] for r in short)
    assert all(abs(b["asw"][r] - p["asw"][r]) > 0.5 for r in mid)


def test_ek_fx_shows_each_users_18m(hist):
    """EK_FX's 18M row as each user has it: no ticker ("hesaplanan"), where it comes from - "hesaplanan (XCCY 1Y–2Y,
    Bootstrap)" / "… PPK basamak)", the user's own setting -, the computed 18M XCCY par (D), its difference to OIS (F, bp),
    how it is read, and (FX sıfır) its zero rate; the FX quotes' line of the chart below has the par at 18M.  Without the
    1Y and 2Y XCCY quotes (a user who typed TRYSAQ2's mid away) there is no 18M: its OIS quote stays, the row says so."""
    from tto.xl import numfmt
    svc, _, _ = hist
    on_boot, on_ppk, typed = (svc.login(n)["user"] for n in ("EK_FX 18A bootstrap", "EK_FX 18A ppk", "EK_FX 18A yok"))
    svc.set_interp(on_ppk, "ppk")
    assert not svc.set_inputs(typed, "tto", [{"ref": "Forward!E126", "value": "yok"}], allow_adhoc=True)["errors"]
    loc = numfmt.get_locale(svc.settings.locale)
    for user in (on_boot, on_ppk, typed):
        x18 = _point_state(svc, user)["x18"]
        page = {q["id"]: q for q in svc.view(user, "asw")["panels"]}
        tab = page["fxc"]["data"]
        row = dict(zip(tab["c"], tab["rows"][tab["r"].index(ex.FXC_CURVE_ROW)]))
        assert (row["A"]["t"], row["B"]["t"]) == ("18M", "hesaplanan")
        kota = page["fxline"]["data"]["series"][2]
        pt = x18["point"]
        if user == typed:
            assert pt is None and x18["why"] == "XCCY 1Y / 2Y (TRYSAQ1 / TRYSAQ2) fiyatı yok"
            assert (row["C"]["t"], row["I"]["t"]) == ("yok", aswfx.RULES[aswfx.OIS]) and type(row["D"].get("v")) is not float
            assert kota["data"][M.index(18)] in (None, "c")
            continue
        assert row["C"]["t"] == x18["label"] == "hesaplanan (XCCY 1Y–2Y, %s)" % ("PPK basamak" if user == on_ppk else "Bootstrap")
        assert row["D"]["v"] == pt.par and row["D"]["t"] == numfmt.format_value(pt.par, "0.000", loc)
        assert row["F"]["v"] == pytest.approx((pt.par - row["E"]["v"]) * 100, abs=1e-9)
        assert row["I"]["t"] == aswfx.RULES[aswfx.CURVE] and row["FX sıfır"]["v"] == pytest.approx(pt.zero, abs=1e-9)
        assert kota["name"] == "FX swap ima · kota" and kota["data"][M.index(18)] == pytest.approx(pt.par, abs=1e-12)


def test_ek_fx_reads_the_one_year_xccy_at_1y(hist):
    """1Y of the FX swap curve is the one year cross currency swap TRYSAQ1 (the desk, 18.11.2026), the offshore 1Y of
    the desk's Forward sheet and of the ASW history - TRYI12M had no price on either source (1Y stood on its OIS quote).
    Its kind is XCCY (annual ACT/360 par); with its one coupon the discount factor is the FX swap's reading,
    1 / (1 + r·d/360), and the sheet's 1Y node has it.  On the recorded day 39,400 (TRYSAQ1 BGN; ICPL has none)."""
    svc, _, _ = hist
    user = svc.login("EK_FX 1Y")["user"]
    k = M.index(12)
    assert ex.FXC_ROOTS[k] == "TRYSAQ1" and aswfx.kind_of(12) == aswfx.XCCY
    page = {q["id"]: q for q in svc.view(user, "asw")["panels"]}
    tab = page["fxc"]["data"]
    row = dict(zip(tab["c"], tab["rows"][tab["r"].index(ex.FXC_FIRST + k)]))
    assert (row["A"]["t"], row["B"]["t"], row["C"]["t"]) == ("1Y", "TRYSAQ1", "TRYSAQ1 BGN Curncy")
    assert row["I"]["t"] == aswfx.RULES[aswfx.XCCY] and row["D"]["v"] == pytest.approx(39.4, abs=1e-9)
    asw = svc.books["asw"]
    si = asw.model.sheet_index["ASW"]

    def run():
        calc, _ = svc._asw_fx_calc(asw, user)
        return (calc.get(si, aswfx.ROW, aswfx.DAY_COL + aswfx.node_of(12)),
                calc.get(si, aswfx.ROW, aswfx.LN_COL + aswfx.node_of(12)))
    d, ln = svc.et.call(run)
    assert math.exp(ln) == pytest.approx(1 / (1 + row["D"]["v"] / 100 * d / 360), abs=1e-12)


def test_a_past_days_18m_comes_from_its_xccy_closes(hist):
    """The ASW history against the offshore curve takes 18M from that day's TRYSAQ1 and TRYSAQ2 closes the same way -
    the XCCY curve of the two, ln DF linear between them (Bootstrap): a past day has no PPK curve, so a user on PPK basamak
    has the same past days as one on Bootstrap; only today's row (the ASW FX column's) is on their setting."""
    from tto.xl.values import serial_to_date
    svc, days, (none, _, _, no2y) = hist
    on_ppk = svc.login("geçmiş 18A ppk")["user"]
    svc.set_interp(on_ppk, "ppk")
    layer, info, rows = _hist_state(svc)
    k18 = M.index(18)
    checked = 0
    for r in sorted(rows)[5::17]:
        if r in (_row_of(days, none), _row_of(days, no2y)):
            continue
        x = rows[r]
        r1, r2 = _xccy_closes(svc, days, serial_to_date(x["day"]).isoformat())
        d = {m: x["days"][aswfx.node_of(m)] for m in (12, 18, 24)}
        df1, df2 = _xccy_nodes(r1, r2, d[12], d[24])
        want = math.log(df1) + (math.log(df2) - math.log(df1)) * (d[18] - d[12]) / (d[24] - d[12])
        assert x["ln"][aswfx.node_of(18)] == pytest.approx(want, abs=1e-12) and info["kinds"][r][k18] == aswfx.CURVE
        checked += 1
    assert checked >= 5
    mine = _hist_state(svc, on_ppk)
    assert {r: v["quotes"] for r, v in mine[2].items()} == {r: v["quotes"] for r, v in rows.items()}      # (past days)
    asw = svc.books["asw"]
    si = asw.model.sheet_index["ASW"]

    def today(user):
        def run():
            fx, _ = svc._asw_fx_calc(asw, user)
            hist_calc, _ = svc._asw_hist_fx(asw, user)
            return hist_calc.get(si, aswfx.ROW, aswfx.QUOTE_COL + k18), fx.get(si, aswfx.ROW, aswfx.QUOTE_COL + k18)
        return svc.et.call(run)
    (h_desk, fx_desk), (h_ppk, fx_ppk) = today(None), today(on_ppk)
    assert h_desk == fx_desk and h_ppk == fx_ppk and h_desk != h_ppk
