"""TRY rates two ways (18.11.2026; a counterparty told the desk FRA prices can differ "by the interpolation choice"):
Bootstrap - today's curve, also Murex's MTM - and PPK basamak - TLREF flat between PPK meetings, the PPK solver's implied
path ("MPC ima") shifted flat between successive quoted maturities so that it reprices the very quotes the bootstrap
is built from.  ``tto/ppkcurve.py`` on its own."""
from __future__ import annotations

import math

import pytest

from tto import ppkcurve as pk
from tto.xl.errors import XlError


def calendar(days: int, monday: int = 0, holidays=()) -> list:
    """Pcum by day as Motor!F528:F4228 counts it: day 0 a business day, ``monday`` the first Monday's day, Σ over the
    days before of (day − the last business day up to it)."""
    out, last, acc = [0.0], 0, 0.0
    for k in range(days):
        if k > 0 and (k - monday) % 7 not in (5, 6) and k not in holidays:
            last = k
        acc += k - last
        out.append(acc)
    return out


def piece(pc, a, b, r):
    x = r / 365.0
    return (b - a) * math.log(1.0 + x) - (pc[b] - pc[a]) * x * x


# ================================================================================================== the module
def test_the_step_curve_compounds_tlref_as_motor_does():
    pc = calendar(400)
    c = pk.StepCurve([0.0, 37.0, 79.0], [0.36, 0.35, 0.34], pc)
    assert c.lng(0.0) == 0.0 and c.df(0.0) == 1.0
    assert c.lng(30.0) == pytest.approx(piece(pc, 0, 30, 0.36), abs=1e-15)
    assert c.lng(100.0) == pytest.approx(piece(pc, 0, 37, 0.36) + piece(pc, 37, 79, 0.35) + piece(pc, 79, 100, 0.34), abs=1e-15)
    # a weekend compounds as one simple period (to second order): Friday → Monday
    x = 0.36 / 365.0
    assert c.lng(7.0) - c.lng(4.0) == pytest.approx(3 * math.log(1 + x) - 3 * x * x, abs=1e-16)
    assert (c.overnight(36.0), c.overnight(37.0), c.overnight(500.0)) == (0.36, 0.35, 0.34)
    # without a calendar every day compounds alone; a meeting listed twice takes its last rate (Motor: a meeting past
    # the spot sits at day 0 with the rate before it); a path starting later starts with its first rate
    assert pk.StepCurve([0.0, 37.0], [0.36, 0.35]).df(37.0) == pytest.approx((1 + 0.36 / 365) ** -37, rel=1e-14)
    assert pk.StepCurve([0.0, 0.0, 37.0], [0.30, 0.36, 0.35]).overnight(1.0) == 0.36
    assert pk.StepCurve([5.0, 37.0], [0.36, 0.35]).df(5.0) == pytest.approx((1 + 0.36 / 365) ** -5, rel=1e-14)
    # beyond the calendar its last value (MIN(t, 3700))
    short = pk.StepCurve([0.0], [0.36], pc[:11])
    assert short.lng(20.0) - short.lng(10.0) == pytest.approx(10 * math.log(1 + x), abs=1e-15)
    with pytest.raises(ValueError):
        pk.StepCurve([XlError("#N/A")], [0.3])


def test_a_path_seen_from_another_spot():
    pc = calendar(500)
    c = pk.StepCurve([0.0, 37.0, 79.0], [0.36, 0.35, 0.34], pc)
    later = c.rebased(2.0)
    for t in (0.0, 1.0, 5.0, 34.0, 35.0, 77.0, 120.0, 300.0):
        assert later.lng(t) == pytest.approx(c.lng(t + 2.0) - c.lng(2.0), abs=1e-14)


def test_log_linear_between_nodes_and_the_end_segment_beyond():
    c = pk.LogLinear([0.0, 100.0, 200.0, XlError("#N/A")], [0.0, -0.1, -0.15, -0.2])
    assert c.days == [0.0, 100.0, 200.0]
    assert c.ln(50.0) == pytest.approx(-0.05) and c.ln(250.0) == pytest.approx(-0.175)
    assert c.df(100.0) == pytest.approx(math.exp(-0.1))
    with pytest.raises(ValueError):
        pk.LogLinear([0.0], [0.0])


def test_par_forward_and_fra():
    c = pk.LogLinear([0.0, 365.0, 730.0], [0.0, -0.3, -0.55])
    assert pk.par(c, [365.0], [1.0]) == pytest.approx(math.exp(0.3) - 1.0)          # one period: the simple rate
    assert pk.forward(c, 0.0, 365.0) == pytest.approx(math.exp(0.3) - 1.0)
    assert pk.forward(c, 365.0, 730.0, 360.0) == pytest.approx((math.exp(0.25) - 1.0) * 360.0 / 365.0)
    grid = pk.Grid(tuple(91.25 * k for k in range(1, 9)), (0.25,) * 8)
    assert pk.fra(c, grid, 3, 6) == pytest.approx((c.df(91.25) / c.df(182.5) - 1.0) / 0.25)
    # an m1 × m2 FRA: the forward-starting swap, (DF(m1) − DF(m2)) / Σ τ·DF over the quarters in (m1, m2]
    assert pk.fra(c, grid, 6, 18) == pytest.approx((c.df(182.5) - c.df(547.5)) / sum(0.25 * c.df(91.25 * k) for k in (3, 4, 5, 6)))
    assert pk.fra(c, grid, 0, 12) == pytest.approx(pk.par(c, grid.days[:4], grid.accruals[:4]))
    assert pk.fra(c, grid, 1, 6) is None and pk.fra(c, grid, 6, 3) is None and pk.fra(c, grid, 0, 27) is None


def synthetic():
    """A meeting path, the bootstrap's node days and a "market": the path with known shifts between the quotes."""
    pc = calendar(1200)
    shape = pk.StepCurve([0.0, 20.0, 62.0, 120.0, 200.0, 300.0, 420.0, 600.0],
                         [0.40, 0.38, 0.36, 0.35, 0.33, 0.32, 0.30, 0.29], pc)
    node_m = [0, 1, 2, 3, 6, 9, 12, 15, 18, 21, 24]
    node_d = [0.0, 31.0, 59.0, 92.0, 182.0, 273.0, 365.0, 456.0, 548.0, 640.0, 731.0]
    months = [1, 2, 3, 6, 9, 12, 18, 24]
    true = [(31.0, 0.0012), (59.0, -0.0030), (92.0, 0.0020), (182.0, 0.0050), (273.0, -0.0040), (365.0, 0.0010),
            (548.0, 0.0080), (731.0, -0.0060)]
    market = shape.with_shifts(true)
    shells = pk.ois_quotes(months, [0.3] * len(months), node_m, node_d)
    quotes = [q._replace(rate=pk.par(market, q.pays, q.accruals)) for q in shells]
    return pc, shape, market, true, quotes


def test_the_quotes_as_the_swaps_they_are():
    _, _, _, _, quotes = synthetic()
    by = {q.name: q for q in quotes}
    assert list(by) == ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y"]
    assert by["1M"].pays == (31.0,) and by["1M"].accruals == (31.0 / 365,)            # one period, simple ACT/365
    assert by["18M"].pays == (92.0, 182.0, 273.0, 365.0, 456.0, 548.0)                # quarterly par from 6M
    assert by["18M"].accruals == pytest.approx((92 / 365, 90 / 365, 91 / 365, 92 / 365, 91 / 365, 92 / 365))
    # offshore: TRYI one period simple ACT/360; TRYSAQ n annual ACT/360 par on TRYSAQ 1 … n's days, up to the first missing
    off = pk.offshore_quotes([("1W", 8.0, 30.0), ("1M", 30.0, 33.0), ("2M", XlError("#N/A"), 34.0)],
                             [("1Y", 365.0, 39.4), ("2Y", 731.0, 41.6), ("3Y", 1096.0, XlError("#N/A")), ("4Y", 1461.0, 40.0)])
    assert [q.name for q in off] == ["TRYI 1W", "TRYI 1M", "XCCY 1Y", "XCCY 2Y"]
    assert (off[0].rate, off[0].pays, off[0].accruals) == (0.30, (8.0,), (8.0 / 360,))
    assert off[3].pays == (365.0, 731.0) and off[3].accruals == pytest.approx((365 / 360, 366 / 360))


def test_calibration_reprices_every_quote_and_keeps_tlref_flat_between_meetings():
    pc, shape, market, true, quotes = synthetic()
    ppk, report = pk.calibrate(shape, quotes)
    for q, x in zip(quotes, report):
        assert pk.par(ppk, q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12)      # every quote back
        assert abs(x["after_bp"]) < 1e-7
        assert x["miss_bp"] == pytest.approx((pk.par(shape, q.pays, q.accruals) - q.rate) * 1e4, abs=1e-9)
    # the shifts found are the ones the market was made with, the curve the market's
    assert [x["shift_bp"] for x in report] == pytest.approx([a * 1e4 for _, a in true], abs=1e-6)
    for t in range(0, 732, 7):
        assert ppk.df(float(t)) == pytest.approx(market.df(float(t)), abs=1e-13)
    # TLREF steps only at a meeting or at a quoted maturity, and is flat in between: what the discount factors imply
    # from one business day to the next (no weekend term) is the step's rate
    ends = {q.end for q in quotes}
    steps = ppk.steps()
    assert {d for d, _ in steps} <= set(shape.knots) | ends
    for u in range(0, 731):
        if pc[u + 1] == pc[u]:
            implied = (math.exp(ppk.lng(u + 1.0) - ppk.lng(float(u))) - 1.0) * 365.0
            assert implied == pytest.approx(ppk.overnight(float(u)), abs=1e-10)
    for (d0, r0), (d1, _) in zip(steps, steps[1:]):
        assert all(ppk.overnight(d) == r0 for d in range(int(d0), int(d1)))
    # quotes in any order; two at one maturity cannot both be met
    assert pk.calibrate(shape, list(reversed(quotes)))[0].df(500.0) == pytest.approx(ppk.df(500.0), abs=1e-15)
    with pytest.raises(ValueError):
        pk.calibrate(shape, [quotes[0], quotes[0]._replace(name="1M bis", rate=0.5)])
