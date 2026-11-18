"""TRY rates two ways (18.11.2026; a counterparty told the desk FRA prices can differ "by the interpolation choice"):
Bootstrap - today's curve, also Murex's MTM - and PPK basamak - TLREF flat between PPK meetings, the PPK solver's implied
path ("MPC ima") shifted flat between successive quoted maturities so that it reprices the very quotes the bootstrap
is built from.  ``tto/ppkcurve.py`` on its own; both ways against the workbook (the bootstrap and MPC ima exactly as the
sheet has them, every quote repriced); and where the desk sees them side by side: OIS · PPK's FRA lists, Günlük
İşlemler's FRA quote and MASA's broken-date block (KIRIK VADE & KARŞILIK)."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from conftest import cell, make_service
from tto import ppkcurve as pk
from tto.xl.errors import XlError
from tto.xl.values import serial_to_date


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


# ================================================================================================== the workbook
def curves(svc, user=None):
    book = svc.books["tto"]
    return svc.et.call(lambda: svc._try_curves(book, svc._calc(user, book)))


def getter(svc, user=None):
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def get(sheet, r, c):
        return svc.et.call(lambda: svc._calc(user, book).get(idx[sheet], r, c))
    return get


def offshore(svc, user=None):
    """The offshore curve as the sheet has it (Forward!AK124:AK143 days, AM124:AM143 ln DF)."""
    return pk.LogLinear([cell(svc, "Forward!AK%d" % r, user) for r in range(124, 144)],
                        [cell(svc, "Forward!AM%d" % r, user) for r in range(124, 144)])


def test_the_bootstrap_and_mpc_ima_are_the_sheets(service):
    """Bootstrap untouched: read as the sheet has it, the FRA lists' market comes back to the last digit; MPC ima - the
    PPK steps' shape - is Motor's "DF ima" column and MASA's MPC ima row."""
    cv = curves(service)
    assert not cv["errors"]
    boot, shape, grid = cv["boot"], cv["shape"], cv["grid"]
    assert len(grid.days) == 40
    for k, d in enumerate(grid.days):
        assert boot.df(d) == pytest.approx(cell(service, "Motor!O%d" % (139 + k)), abs=1e-14)        # DF Bootstrap
        assert shape.df(d) == pytest.approx(cell(service, "Motor!L%d" % (139 + k)), abs=1e-14)       # DF ima (1/G_ima)
    for r in range(336, 439):
        m1, m2 = cell(service, "OIS_MAIN!M%d" % r), cell(service, "OIS_MAIN!N%d" % r)
        assert pk.fra(boot, grid, int(m1), int(m2)) == pytest.approx(cell(service, "OIS_MAIN!B%d" % r), abs=1e-12)
    k60, m60 = cell(service, "MASA!K60"), cell(service, "MASA!M60")
    assert pk.forward(shape, k60, m60) == pytest.approx(cell(service, "MASA!C62"), abs=1e-13)        # MPC ima
    assert pk.forward(boot, k60, m60) == pytest.approx(cell(service, "MASA!C67"), abs=1e-13)         # Bootstrap


def test_the_ppk_curves_reprice_every_quote(service):
    cv = curves(service)
    quoted = [cell(service, "Motor!B%d" % r) for r in range(306, 322)]                  # the quotes' copy (no 15M / 21M)
    assert len(cv["quotes"]) == sum(type(q) is float for q in quoted) >= 12
    for q in cv["quotes"]:
        assert pk.par(cv["ppk"], q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12)
        assert pk.par(cv["boot"], q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12)          # (the same swaps)
    assert all(abs(x["after_bp"]) < 1e-6 for x in cv["report"])
    assert {d for d, _ in cv["ppk"].steps()} <= set(cv["shape"].knots) | {q.end for q in cv["quotes"]}
    # offshore: the offshore curve and its PPK twin both reprice the offshore quotes by their own conventions
    off = offshore(service)
    assert len(cv["off_quotes"]) >= 10
    for q in cv["off_quotes"]:
        assert pk.par(cv["off_ppk"], q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12)
        assert pk.par(off, q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-10)


def test_the_fra_lists_both_ways(service):
    u = service.login("PPK FRA listesi")["user"]
    ps = {p["id"]: p for p in service.view(u, "ois")["panels"]}
    cv = curves(service)
    tables = {}
    for pid, head, mcol in (("B21", 335, "B"), ("B11", 65, "C")):
        d = ps[pid]["data"]
        assert d["c"][-4:] == ["PPK basamak", "PPK fark", "Başl. kova", "Bitiş kova"] and d["added"] == 4
        rows = {r: row for r, row in zip(d["r"], d["rows"])}
        assert [c["t"] for c in rows[head][-4:-2]] == ["PPK basamak", "PPK − piyasa (bp)"]
        assert "TLREF toplantılar arasında sabit, kotalara aynen oturur" in rows[head][-4]["tip"]
        assert "Bootstrap (Murex) = bugünkü eğri, Murex'in MTM'i" in rows[head][d["c"].index(mcol)]["tip"]
        tables[pid] = rows
    diff = {}
    for r in range(336, 439):
        m1, m2, market = (cell(service, "OIS_MAIN!%s%d" % (c, r)) for c in "MNB")
        want = pk.fra(cv["ppk"], cv["grid"], int(m1), int(m2))
        value, bp = tables["B21"][r][-4], tables["B21"][r][-3]
        assert value["v"] == pytest.approx(want, abs=1e-15) and bp["v"] == pytest.approx((want - market) * 1e4, abs=1e-9)
        diff[(int(m1), int(m2))] = bp["v"]
    # where the two ways meet: FRAs whose ends are quoted maturities (3M ↔ 1Y) the same, joining 1Y / 18M / 2Y within a
    # fraction of a bp; between two quotes they part
    for m in ((0, 3), (3, 6), (6, 9), (9, 12)):
        assert abs(diff[m]) < 1e-6
    for m in ((12, 18), (12, 24), (18, 24)):
        if m in diff:
            assert abs(diff[m]) < 0.5
    names = {cell(service, "OIS_MAIN!A%d" % r): r for r in range(336, 439)}
    checked = 0
    for r in range(66, 81):
        label = cell(service, "OIS_MAIN!B%d" % r)
        if label in names:
            assert tables["B11"][r][-4]["v"] == tables["B21"][names[label]][-4]["v"]
            assert tables["B11"][r][-3]["v"] == pytest.approx(tables["B21"][names[label]][-3]["v"], abs=1e-9)
            checked += 1
    assert checked >= 10


def test_the_fra_quote_both_ways(service):
    """Günlük İşlemler's FRA quote: the market and the cost as they were (the bootstrap), and beside them the mid on the
    PPK steps and the cost against it (same sign as the cost: + paid away)."""
    u = service.login("PPK FRA kotasyonu")["user"]
    cv = curves(service)
    names = {cell(service, "OIS_MAIN!A%d" % r): r for r in range(336, 439)}
    for side, sign in (("RECEIVE", 1.0), ("PAY", -1.0)):
        q = service.quote_ois(u, {"strategy": "fra", "side": side, "start_months": 12.0, "end_months": 15.0, "level": "35,10"})
        info, level = q["info"], q["level"]
        ppk = pk.fra(cv["ppk"], cv["grid"], 12, 15)
        assert info["market"] == pytest.approx(cell(service, "OIS_MAIN!B%d" % names["1Y3M"]), abs=1e-12)
        assert info["cost_bp"] == pytest.approx(sign * (info["market"] - level) * 1e4, abs=1e-9)
        assert info["market_ppk"] == pytest.approx(ppk, abs=1e-15)
        assert info["cost_bp_ppk"] == pytest.approx(sign * (ppk - level) * 1e4, abs=1e-9)
    q = service.quote_ois(u, {"strategy": "fra", "side": "PAY", "start_months": 3.0, "end_months": 6.0, "level": "35,10"})
    assert q["info"]["market_ppk"] == pytest.approx(q["info"]["market"], abs=1e-12)            # between two quotes' ends


def b22(svc, user):
    p = next(p for p in svc.view(user, "masa")["panels"] if p["id"] == "B22")
    return p, {r: row for r, row in zip(p["data"]["r"], p["data"]["rows"])}


SCALE = {173: 1e4, 174: 1.0, 175: 1e4, 176: 1e4, 177: 1e4, 178: 1e4, 179: 1e4}


def test_the_broken_date_block_both_ways(service):
    u = service.login("PPK kırık vade")["user"]
    p, rows = b22(service, u)
    assert p["data"]["c"][-2:] == ["PPK basamak", "PPK fark"] and p["data"]["added"] == 2 and p.get("copyable")
    assert [c["t"] for c in rows[172][-2:]] == ["PPK basamak", "PPK − piyasa"]
    cv = curves(service, u)
    get = getter(service, u)
    # on the curves the block reads itself the same rows are the block's market: a difference is the curve's alone
    same = pk.broken(get, cv["boot"], offshore(service, u))
    got = pk.broken(get, cv["ppk"], cv["off_ppk"])
    assert set(same) == set(got) == set(SCALE)
    for r, scale in SCALE.items():
        market = cell(service, "MASA!F%d" % r, u)
        assert same[r] == pytest.approx(market, rel=1e-13)
        assert rows[r][-2]["v"] == pytest.approx(got[r], rel=1e-13)
        assert rows[r][-1]["v"] == pytest.approx((got[r] - market) * scale, abs=1e-6)
    # at the offshore curve's 1Y quote's day (TRYSAQ1) both ways agree on every offshore row; between quotes they do not
    s0 = cell(service, "MASA!BL171", u)
    one_year = next(q.end for q in cv["off_quotes"] if q.name.startswith("XCCY"))
    for days, equal in ((one_year, True), (one_year + 459.0, False)):
        text = serial_to_date(s0 + days).strftime("%d.%m.%Y")
        assert service.set_inputs(u, "tto", [{"ref": "MASA!C171", "value": text}])["errors"] == []
        _, rows = b22(service, u)
        for r in (173, 175, 177, 179):
            market = cell(service, "MASA!F%d" % r, u)
            assert type(market) is float and type(rows[r][-2]["v"]) is float
            if equal:
                assert rows[r][-2]["v"] == pytest.approx(market, rel=1e-12), r
            else:
                assert abs(rows[r][-2]["v"] - market) > 1e-7 * abs(market), r
    # a temporary copy of the block ("Geçici kopya aç") prices both ways at its own date
    cp = service.copy_action(u, "open", {"view": "masa", "panel": "B22"})["copy"]
    try:
        text = serial_to_date(s0 + 400.0).strftime("%d.%m.%Y")
        assert service.copy_action(u, "inputs", {"copy": cp["id"], "items": [{"ref": "MASA!C171", "value": text}]})["errors"] == []
        res = service.view(u, "masa")
        copy = next(p for p in res["panels"] if p["id"] == cp["pid"])
        crows = {r: row for r, row in zip(copy["data"]["r"], copy["data"]["rows"])}
        _, rows = b22(service, u)
        f = copy["data"]["c"].index("F")
        assert copy["data"]["c"][-2:] == ["PPK basamak", "PPK fark"]
        for r in (175, 178, 179):
            assert crows[r][-2]["v"] != rows[r][-2]["v"]                                 # (another date than the table's)
            assert crows[r][-1]["v"] == pytest.approx((crows[r][-2]["v"] - crows[r][f]["v"]) * 1e4, abs=1e-6)
    finally:
        service.copy_action(u, "close", {"copy": cp["id"]})
        service.reset_inputs(u, "tto")


def test_on_the_replay_day(tmp_path):
    """The day the desk asked on (the replay, 03.11.2026): a 12x15 FRA 70 bp lower on the PPK steps than on the
    bootstrap - MPC ima's own −70.0 bp before the calibration, −70.7 after -, the 15x18 ~80 bp higher, the 12x18 the
    same; the calibration shifts within ±11 bp (MPC ima misses no OIS quote by 1 bp); a broken date between two XCCY
    quotes (spot + 2Y3M) apart, at the 2Y XCCY quote's day the same."""
    svc = make_service(tmp_path)
    try:
        cv = curves(svc)
        names = {cell(svc, "OIS_MAIN!A%d" % r): r for r in range(336, 439)}
        fra = lambda c, m1, m2: pk.fra(c, cv["grid"], m1, m2)                            # noqa: E731
        bp = lambda c, m1, m2, name: (fra(c, m1, m2) - cell(svc, "OIS_MAIN!B%d" % names[name])) * 1e4   # noqa: E731
        assert -70.5 < bp(cv["shape"], 12, 15, "1Y3M") < -69.5
        assert -71.5 < bp(cv["ppk"], 12, 15, "1Y3M") < -70.0
        assert 75.0 < bp(cv["ppk"], 15, 18, "15M3M") < 82.0
        assert abs(bp(cv["ppk"], 12, 18, "1Y6M")) < 0.1
        assert max(abs(x["miss_bp"]) for x in cv["report"]) < 1.0
        assert max(abs(x["shift_bp"]) for x in cv["report"]) < 11.0
        u = svc.login("PPK replay")["user"]
        s0 = cell(svc, "MASA!BL171", u)
        for when, lo, hi in ((dt.date(2029, 2, 5), 0.5, 2.0), (serial_to_date(s0 + 731.0), -1e-9, 1e-9)):
            assert svc.set_inputs(u, "tto", [{"ref": "MASA!C171", "value": when.strftime("%d.%m.%Y")}])["errors"] == []
            _, rows = b22(svc, u)
            assert lo < rows[179][-1]["v"] < hi, (when, rows[179][-1])                   # XCCY, PPK − offshore (bp)
    finally:
        svc.stop()
