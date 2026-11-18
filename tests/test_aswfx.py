"""DİBS ASW's FX swap implied TRY curve (``tto/aswfx.py``): EK_FX's rates read each by its own convention - up to 18M
FX swap implied (TRYI), one period simple ACT/360; from 2Y cross currency swaps (TRYSAQ), annual ACT/360 par, as the
desk's workbook reads them (Forward!AJ123:AN142, C123:K134) - and given to the ASW sheet as the par quotes of the sheet's
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


# ---------------------------------------------------------------------------------------------- the history offshore
def test_the_history_series_of_each_tenor():
    """A past day's offshore rate of each tenor is the dashboard's own history (tto/history.py), by months: the FX swap
    implied yield (group "off": TRYI1M … TRYI9M), else the cross currency swap ("xccy": TRYSAQ1 at 1Y, TRYSAQ2 … 10);
    none at 18M (no TRYI18M is kept) - and an FX swap implied 12M, were it kept, before the 1Y cross currency swap."""
    from types import SimpleNamespace as S
    defs = [S(group="ref", months=None, id="TLREF")] + \
        [S(group="off", months=m, id="TRYI%s" % t) for m, t in ((0.01, "ON"), (0.25, "1W"), (1.0, "1M"), (2.0, "2M"), (3.0, "3M"),
                                                                 (4.0, "4M"), (6.0, "6M"), (9.0, "9M"))] + \
        [S(group="xccy", months=12.0 * y, id="TRYSAQ%d" % y) for y in range(1, 11)] + [S(group="ois", months=18.0, id="TYSO1F")]
    got = [d.id if d is not None else None for d in aswfx.history_series(defs)]
    assert got == ["TRYI1M", "TRYI2M", "TRYI3M", "TRYI6M", "TRYI9M", "TRYSAQ1", None] + ["TRYSAQ%d" % y for y in range(2, 11)]
    assert aswfx.history_series(defs + [S(group="off", months=12.0, id="TRYI12M")])[M.index(12)].id == "TRYI12M"


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
    on one day and none of 9M on another; on a third day 1M only from the backup source (BGN)."""
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
        none, no9, bgn = days[10].isoformat(), days[20].isoformat(), days[30].isoformat()
        for k, s in enumerate(series):
            if s is None:
                continue
            level = 34.0 + 0.4 * k
            pts = [(d.isoformat(), round(level + 0.5 * math.sin(i / 5.0 + k) + 0.6 * (n - i) / n, 4)) for i, d in enumerate(days)]
            svc.store.hist_upsert(s.id, [(d, v) for d, v in pts if d != none and not (M[k] == 9 and d == no9)
                                         and not (M[k] == 1 and d == bgn)])
            if M[k] == 1:
                svc.store.hist_upsert(s.ids()[1], [(d, v + 0.3) for d, v in pts if d != none])    # the backup (BGN)
        svc.history.rev += 1                                                     # (what the history does when it stores)
        yield svc, days, (none, no9, bgn)
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
    as today's FX quotes are; 18M keeps the day's OIS quote.  The curve is the sheet's own formulas on them (its replica,
    to the last digit), at every priced tenor the discount factor the rate gives by its own convention; the bonds' ASW is
    the sheet's own - a second engine with the rows' quotes pinned gives the same - and another than OIS's.  The OIS
    calculation is untouched."""
    from tto.xl.values import serial_to_date
    svc, days, (none, no9, bgn) = hist
    before = _hist_state(svc)[2]
    layer, info, rows = _hist_state(svc)
    assert info["days"] == len(days) == len(rows) >= 100 and info["offshore"] == len(days) - 1
    assert [serial_to_date(rows[r]["day"]) for r in sorted(rows)] == days                       # (oldest first)
    priced = [k for k in range(3) if type(rows[aswfx.HIST_FIRST]["asw_ois"][k]) is float]
    assert priced                                                                                # (a bond with a price history)
    picked = sorted(set(sorted(rows)[::23] + [_row_of(days, bgn), aswfx.HIST_FIRST + len(days) - 1]))
    for r in picked:
        x = rows[r]
        got = aswfx.to_sheet(x["ois"], _offshore_closes(svc, days, serial_to_date(x["day"]).isoformat()), x["days"])
        assert [t.kind for t in got][M.index(18)] == aswfx.OIS and info["n"][r] == 15
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


def test_a_day_or_a_tenor_without_offshore_keeps_ois_and_is_reported(hist):
    """No offshore close at all on a day: the row keeps its OIS quotes - its ASW on the offshore side is the OIS one - and
    the table says 0 / 16 offshore; a tenor without a close (9M on another day), and 18M every day, keep that day's OIS
    quote: 14 / 16, the cell's tip naming them."""
    svc, days, (none, no9, _) = hist
    _, info, rows = _hist_state(svc)
    r0, r9 = _row_of(days, none), _row_of(days, no9)
    assert rows[r0]["quotes"] == rows[r0]["ois"] and info["n"][r0] == 0 and info["kinds"][r0] == [aswfx.OIS] * len(M)
    assert rows[r0]["asw"] == rows[r0]["asw_ois"]
    assert all(rows[r]["quotes"][M.index(18)] == rows[r]["ois"][M.index(18)] for r in rows)
    k9 = M.index(9)
    assert rows[r9]["quotes"][k9] == rows[r9]["ois"][k9] and info["n"][r9] == 14
    assert rows[r9]["quotes"][k9 - 1] != rows[r9]["ois"][k9 - 1]                         # (6M that day: offshore)
    t = {p["id"]: p for p in svc.view(None, "asw")["panels"]}["hist"]["data"]
    assert t["added"] == 4 and t["c"][-4:] == ["ASW 1 off", "ASW 2 off", "ASW 3 off", "Off vade"]
    head = t["rows"][t["r"].index(aswfx.ROW - 1)]
    assert [c["t"] for c in head[-4:]] == ["ASW 1 offshore", "ASW 2 offshore", "ASW 3 offshore", "Offshore vade"]
    count = {r: t["rows"][t["r"].index(r)][-1] for r in (r0, r9, aswfx.HIST_FIRST)}
    assert (count[r0]["t"], count[r9]["t"], count[aswfx.HIST_FIRST]["t"]) == ("0 / 16", "14 / 16", "15 / 16")
    assert count[r0]["tip"] == "Offshore: yok · OIS: 1M 2M 3M 6M 9M 1Y 18M 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y"
    assert count[r9]["tip"] == "Offshore: 1M 2M 3M 6M 1Y 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y · OIS: 9M 18M"
    shown = t["rows"][t["r"].index(r0)]
    assert [c["t"] for c in shown[-4:-1]] == [c["t"] for c in shown[-7:-4]]             # (ASW 1–3 offshore = OIS)


def test_the_history_chart_for_each_choice(hist):
    """The history chart, drawn as each user chooses (Parametreler's "Geçmiş grafiği", ASW!N3, or the chart's own small
    selector - the same cell): OIS by default - the workbook's chart as it was -, Offshore (the same chart on the offshore
    calculation, each bond "· offshore") or İkisi (both: the OIS series, then the offshore ones dashed).  One user's
    choice is theirs; anything but the three is refused.  A user whose only input is the choice reads everybody's
    offshore history (no calculation of their own for it)."""
    from tto.xl import numfmt
    svc, days, _ = hist
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
    c = chart1(ali)
    assert c["pick"] == {"ref": "ASW!N3", "book": "asw", "value": "OIS", "options": ["OIS", "Offshore", "İkisi"], "default": "OIS"}
    assert c["data"] == ois and c["title"] == "ASW geçmişi (son nokta canlı)" and len(ois["series"]) == 3
    assert len(ois["series"][1]["data"]) == len(days) + 1                                   # (the past days, then today)
    assert not svc.set_inputs(ali, "asw", [{"ref": "ASW!N3", "value": "fx"}])["errors"]     # (a word for it: Offshore)
    c = chart1(ali)
    assert c["pick"]["value"] == "Offshore" and c["title"] == "ASW geçmişi · offshore eğrisine göre (son nokta canlı)"
    assert [s["name"] for s in c["data"]["series"]] == ["%s · offshore" % (s["name"] or "Kâğıt %d" % (k + 1))
                                                        for k, s in enumerate(ois["series"])]
    assert [s["data"] for s in c["data"]["series"]] == [s["data"] for s in off["series"]] != [s["data"] for s in ois["series"]]
    assert "Offshore faizli gün: %d / %d" % (len(days) - 1, len(days)) in c["note"]
    assert chart1(veli)["pick"]["value"] == "OIS" and chart1(veli)["data"] == ois             # (ali's choice is ali's)
    assert (ali, svc.HIST_FX) not in book.engine.layers and ("", svc.HIST_FX) in book.engine.layers
    assert not svc.set_inputs(ali, "asw", [{"ref": "ASW!N3", "value": "ikisi"}])["errors"]
    c = chart1(ali)
    assert c["pick"]["value"] == "İkisi" and len(c["data"]["series"]) == 6
    assert [s["data"] for s in c["data"]["series"]] == [s["data"] for s in ois["series"] + off["series"]]
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
