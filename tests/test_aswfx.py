"""DİBS ASW's FX swap implied TRY curve (``tto/aswfx.py``): EK_FX's rates read each by its own convention - up to 18M
FX swap implied (TRYI), one period simple ACT/360; from 2Y cross currency swaps (TRYSAQ), annual ACT/360 par, as the
desk's workbook reads them (Forward!AJ123:AN142, C123:K134) - and given to the ASW sheet as the par quotes of the sheet's
own convention with the same discount factor at the tenor.  The sheet's formulas are its own (a replica of them that
cannot drift: checked against the engine), its OIS side untouched."""
from __future__ import annotations

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
    """TRYI (≤ 18M): one period, simple ACT/360 - an FX swap has no coupons; TRYSAQ (≥ 2Y): annual ACT/360 par over its
    yearly coupon dates, their discount factors the curve's as built so far - as the desk's workbook bootstraps its
    offshore curve (Forward!G125 = 1 / (1 + r·d1/360), G126 = (1 − r·ΣJ) / (1 + r·(d2 − d1)/360), J = G·τ).  The kind
    goes by the tenor; a tenor without an FX price keeps its OIS quote."""
    got = aswfx.to_sheet(OIS, FX, DAYS)
    assert [t.months for t in got] == list(M)
    assert [t.kind for t in got] == ["fx", "fx", "fx", "fx", "ois", "fx", "ois", "xccy", "xccy", "ois", "xccy", "ois", "ois",
                                     "ois", "ois", "ois"]
    by = {t.months: t for t in got}
    for m, r in ((1, 36.0), (2, 36.5), (3, 37.0), (6, 38.0), (12, 38.5)):
        assert by[m].quote == r and by[m].df == pytest.approx(1 / (1 + r / 100 * day(m) / 360), abs=1e-15), m
    # 2Y and 3Y as the desk's sheet chains them: the 1Y discount factor (the FX swap's here), then each year's
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
    assert aswfx.kind_of(18) == "fx" and aswfx.kind_of(24) == "xccy"


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


# ---------------------------------------------------------------------------------------------- on the engine
def _sheet(svc):
    book = svc.books["asw"]
    return book, book.model.sheet_index["ASW"], book.model.sheet_index[ex.FXC_SHEET]


def test_the_fx_calculation_is_the_sheets_own_on_those_quotes(service):
    """In the dashboard's calculation on the FX swap curve (``Service._asw_fx_calc``) the sheet's quotes (ASW!C65:R65) are
    ``to_sheet``'s - a priced tenor's par quote, an unpriced one's OIS quote - and the sheet's own discount factor at
    every priced tenor is the one the FX rate gives by its own convention.  The replica is the sheet: on the OIS quotes
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
        return before, oisside(), swapped, fx, days, quotes, ln, fx_asw
    before, after, swapped, fx, days, quotes, ln, fx_asw = s.et.call(run)
    ois_quotes, ois_ln, ois_asw = before
    assert after == before                                                         # the OIS side as it was
    assert all(type(x) is float for x in ois_ln + ln)
    assert aswfx.sheet_curve(ois_quotes, days) == ois_ln                           # the replica is the sheet ...
    assert aswfx.sheet_curve(quotes, days) == ln                                   # ... on the FX side too
    got = aswfx.to_sheet(ois_quotes, fx, days)
    priced = [t for t in got if t.kind != aswfx.OIS]
    assert swapped == len(priced) == sum(type(x) is float for x in fx) and swapped >= 5
    assert {t.kind for t in priced} == {"fx", "xccy"}                              # (both kinds on the recorded day)
    for k, t in enumerate(got):
        assert quotes[k] == t.par, t.months                                        # what the sheet is given
        if t.kind == aswfx.OIS:
            assert quotes[k] == ois_quotes[k]
        else:
            assert math.exp(ln[aswfx.node_of(t.months)]) == pytest.approx(t.df, abs=1e-12), t.months
    # the bonds are priced off it: another ASW than OIS's wherever the curve differs
    assert sum(type(a) is float and type(b) is float and abs(a - b) > 1.0 for a, b in zip(fx_asw, ois_asw)) >= 10
