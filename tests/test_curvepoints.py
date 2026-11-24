"""Eğri noktaları (18.11.2026, "Bu enterpolasyon noktalarına Ayarlar'dan ekle / çıkar yapabilmeliyim, yanlarına da ne
olduklarını not alabilmeliyim. Ama PPK'lar her zaman olmalı. PPK tarihleri güncellenince o da güncellenmeli."): the
desk's list of the points each TRY curve - OIS and offshore - is built from (tto/curvepoints.py).

The default list is today's points and gives every number as before (the workbook's own formulas, nothing of the list
read); the computed 18M XCCY is the offshore curve read at 18M (6M + 12M, counted back) and adds nothing; a curve whose
list differs is built on it both ways - a typed point is a node priced back exactly, a point switched off is interpolated
across; the PPK meetings are always there and follow the calendar; a ticker point says its cost and asks Bloomberg
nothing before the desk's yes; only administrators change the list and every change is logged."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell
from tto import curvepoints as cpm
from tto import extras as ex
from tto import interp as ip
from tto import ppkcurve as pk
from tto import pricing as pr
from tto.marketdata.base import bdp_key
from tto.server import create_app
from tto.service import ServiceError
from tto.xl.model import COLS, parse_a1
from tto.xl.tokenizer import to_template
from tto.xl.values import date_to_serial, serial_to_date


@pytest.fixture(scope="module")
def desk(module_service):
    svc = module_service
    names = {k: svc.login(v)["user"] for k, v in (("admin", "Nokta Yönetici Ayla"), ("boot", "Nokta Boot Berk"),
                                                   ("ppk", "Nokta PPK Pelin"), ("own", "Nokta Kendi Kaan"))}
    svc.store.update_account(names["admin"], role="admin")
    svc.set_interp(names["ppk"], "ppk")
    return names


def curves(svc, user=None):
    book = svc.books["tto"]
    return svc.et.call(lambda: svc._try_curves(book, svc._calc(user, book)))


class _Names(object):
    """The offshore curve as every page of the workbook reads it in a calculation: the names OFF_GUN / OFF_LNDF / OFF_SL
    read as MASA's broken-date block reads them (``LOOKUP``: the node at or before a day, on along its slope) - on PPK
    basamak the PPK node table, on the desk's list the list's."""

    def __init__(self, names):
        keep = [(float(d), v, s) for d, v, s in zip(names["OFF_GUN"], names["OFF_LNDF"], names["OFF_SL"]) if type(d) is float]
        self.days, self.lndf, self.slopes = [d for d, _, _ in keep], [v for _, v, _ in keep], [s for _, _, s in keep]

    def df(self, t):
        import bisect
        i = max(bisect.bisect_right(self.days, t) - 1, 0)
        return math.exp(self.lndf[i] + self.slopes[i] * (t - self.days[i]))


def reader(svc, user, curve="off"):
    """The offshore curve as the workbook's readers read it in the user's calculation."""
    assert curve == "off"
    return _Names(names_of(svc, user))


def names_of(svc, user=None):
    from tto import borsaspread as bsp
    book = svc.books["tto"]
    return svc.et.call(lambda: {n: bsp._named(book, svc._calc(user, book), n) for n in ("OFF_GUN", "OFF_LNDF", "OFF_SL")})


def rows_of(payload, curve):
    return [r for c in payload["curves"] if c["id"] == curve for r in c["rows"]]


def point(payload, rid):
    return next(r for c in payload["curves"] for r in c["rows"] if r["id"] == rid)


def to_default(svc, admin):
    if svc.curvepoints.custom():
        svc.set_curve_points(admin, {"action": "reset"})
    assert svc.curvepoints.specs() == {"ois": None, "off": None}


def own_formula(svc, calc, addr):
    """Motor's own formula of a node's par (what the switches wrap), evaluated in ``calc``."""
    from tto.render import calc_value
    b = svc.books["tto"]
    text = ex.formula_of(b.model, "Motor", addr)
    k = int(addr[1:]) - ex.INTERP_SHIFT
    head = "IF(EK_INTERP!$B$3=1,EK_INTERP!$F$%d,IF(EK_INTERP!$N$5=1,EK_INTERP!$N$%d," % (k, k)
    assert text.startswith(head) and text.endswith("))")
    own = text[len(head):-2]
    r, c = divmod(parse_a1(addr), COLS)
    fn = b.engine.compiler.compile_expression(to_template(own, r, c))
    return svc.et.call(calc_value, calc, fn, b.model.sheet_index["Motor"], r, c)


# ================================================================================================== the module on its own
def test_tenors_dates_rates_and_tickers_as_the_desk_types_them():
    assert [cpm.parse_tenor(t) for t in ("1W", "2h", "1M", "18M", "1A", "2Y", "2Y3M", "2y 3a", "120M")] == \
        [(None, 1), (None, 2), (1, None), (18, None), (1, None), (24, None), (27, None), (27, None), (120, None)]
    assert [cpm.parse_tenor(t) for t in ("", "0M", "3M2Y", "400M", "1W2M", "abc")] == [None] * 6
    assert [cpm.tenor_text(m) for m in (1, 12, 15, 18, 21, 24, 27, 30, 120)] == \
        ["1M", "1Y", "15M", "18M", "21M", "2Y", "2Y3M", "2Y6M", "10Y"]
    assert cpm.parse_day("15.03.2027") == dt.date(2027, 3, 15) and cpm.parse_day("2027-03-15") == dt.date(2027, 3, 15)
    assert cpm.parse_day("31.02.2027") is None
    assert cpm.parse_rate("41,25") == pytest.approx(0.4125) and cpm.parse_rate("%41.25") == pytest.approx(0.4125)
    assert cpm.parse_rate(41.25) == pytest.approx(0.4125) and cpm.parse_rate("x") is None and cpm.parse_rate("900") is None
    assert cpm.clean_ticker("trysaq1h icpl curncy") == "TRYSAQ1H ICPL Curncy" and cpm.clean_ticker("TRYSAQ1H") is None


def test_a_point_off_the_grid_and_a_counted_back_schedule():
    """The list's curves on their own: an XCCY counted back from its maturity (18M: 6M + 12M, the short period first),
    the node bootstrap prices every quote back (closed form on known coupons, solved when one falls before its node),
    Motor's method linear in months on its nodes."""
    hol = frozenset()
    spot = date_to_serial(dt.date(2026, 11, 4))
    raw = pk.edate(spot, 18)
    assert serial_to_date(raw) == dt.date(2028, 5, 4) and serial_to_date(pk.edate(raw, -12)) == dt.date(2027, 5, 4)
    assert serial_to_date(pk.following(date_to_serial(dt.date(2026, 11, 7)), hol)) == dt.date(2026, 11, 9)   # Saturday → Monday
    q = [pk.Quote("1Y", 0.39, (365.0,), (365.0 / 360,)), pk.Quote("3Y", 0.41, (365.0, 731.0, 1096.0),
                                                                  (365.0 / 360, 366.0 / 360, 365.0 / 360))]
    curve = pk.bootstrap(q)
    assert curve.days == [0.0, 365.0, 1096.0]                       # (no node at 2Y: its coupon interpolated)
    for x in q:
        assert pk.par(curve, x.pays, x.accruals) == pytest.approx(x.rate, abs=1e-13)
    pars, ln = pk.motor_curve([0, 1, 3, 6], [0.0, 30.0, 92.0, 181.0], [0.0, 30 / 365, 92 / 365, 89 / 365], [(1.0, 0.30), (6.0, 0.40)])
    assert pars[1] == 0.30 and pars[2] == pytest.approx(0.30 + 0.10 * 2 / 5) and pars[3] == 0.40


# ================================================================================================== the default list
def test_the_default_list_is_today_s_points(module_service, desk):
    svc = module_service
    p = svc.curve_points(desk["boot"])
    assert p["available"] and not p["can_edit"] and svc.curve_points(desk["admin"])["can_edit"]
    assert p["custom"] == {"ois": False, "off": False} and svc.curvepoints.specs() == {"ois": None, "off": None}
    ois = [r for r in rows_of(p, "ois") if not r["ppk"]]
    months = [cell(svc, "Motor!A%d" % r) for r in range(306, 322)]
    assert [r["name"] for r in ois] == [pk.tenor_label(int(m)) for m in months]          # 1M … 10Y: no 15M, 21M
    for (m, motor, main), r in zip(cpm.DEFAULT_OIS, ois):
        assert ex.formula_of(svc.books["tto"].model, "Motor", "B%d" % motor) == "OIS_MAIN!B%d" % main     # (the quote it reads)
        assert r["source"] == "book" and r["on"] and r["default"] and r["value"] == cell(svc, "Motor!B%d" % motor)
    off = [r for r in rows_of(p, "off") if not r["ppk"]]
    assert [r["name"] for r in off if r["kind"] == "fx"] == ["TRYI %s" % cell(svc, "Forward!H%d" % r) for r in range(8, 17)]
    assert [r["name"] for r in off if r["source"] == "book" and r["kind"] == "xccy"] == \
        ["XCCY %s" % cell(svc, "Forward!C%d" % r) for r in range(125, 135)]
    calc18 = point(p, cpm.COMPUTED_18M)
    assert calc18["source"] == "calc" and calc18["kind"] == "xccy" and calc18["on"] and calc18["note"] == cpm.COMPUTED_18M_NOTE
    # the PPK meetings - read only, from Motor's meeting table, in both lists - among the points by their day
    meets = [r for r in range(5, 85) if 0 < cell(svc, "Motor!C%d" % r) < 99999]
    for curve in ("ois", "off"):
        ppk = [r for r in rows_of(p, curve) if r["ppk"]]
        assert len(ppk) == len(meets) and all(r["source_text"] == "takvimden" and r["kind_text"] == "PPK toplantısı" for r in ppk)
        days = [r["day"] for r in rows_of(p, curve) if isinstance(r["day"], (int, float))]
        assert days == sorted(days)
    assert point(p, "ppk:MPC1")["day"] == cell(svc, "Motor!C5")
    # nothing of the list is in the workbook: flags 0, no ticker
    assert [cell(svc, "EK_INTERP!%s" % a) for a in ("N3", "N4", "N5", "N6")] == [0.0, 0.0, 0.0, 0.0]
    assert cell(svc, "EK_INTERP!U10") is None


def test_on_the_default_list_every_number_is_the_workbook_s_own(module_service, desk):
    """Motor's node pars are their own formulas' values to the bit, the offshore names the Forward sheet's ranges, the
    curves both ways the same as without a list; nothing of the list is read (no bit of its cells in any mask)."""
    svc = module_service
    b = svc.books["tto"]
    shared = b.engine.shared
    for r in range(89, 131):
        own = own_formula(svc, shared, "F%d" % r)
        got = cell(svc, "Motor!F%d" % r)
        assert got == own and type(got) is type(own)
    names = names_of(svc)
    for name, rng in ex.INTERP_OFF_RANGES.items():
        sheet, addr = rng.split("!")
        a, z = addr.replace("$", "").split(":")
        r1, r2 = int(a[2:]), int(z[2:])
        assert names[name] == [cell(svc, "%s!%s%d" % (sheet, a[:2], r)) for r in range(r1, r2 + 1)]
    idx = b.model.sheet_index
    plain = svc.et.call(lambda: pk.read(lambda s, r, c: shared.get(idx[s], r, c)))
    listed = svc.et.call(lambda: pk.read(lambda s, r, c: shared.get(idx[s], r, c), svc.curvepoints.specs()))
    assert plain["boot"].days == listed["boot"].days and plain["boot"].lndf == listed["boot"].lndf
    assert plain["ppk"].steps() == listed["ppk"].steps() and plain["off_ppk"].steps() == listed["off_ppk"].steps()
    assert [tuple(q) for q in plain["quotes"]] == [tuple(q) for q in listed["quotes"]]
    # the PPK users' offshore table: a quote's coupon days are nodes - on the default list each is an earlier quote's
    # maturity already, so the table is the steps' and the quotes' as before
    off_ppk, quotes = plain["off_ppk"], plain["off_quotes"]
    last = max(q.end for q in quotes)
    table = ip.off_nodes(off_ppk, quotes, len(svc.interp.off_cells))
    assert [d for d, _, _ in table if d <= last] == sorted({0.0, last} | {d for d, _ in off_ppk.steps() if 0.0 < d < last})
    eng = b.engine
    bits = eng._bits[("group", ip.GROUP_LIST_OIS)] | eng._bits[("group", ip.GROUP_LIST_OFF)]
    for ref in ("Motor!G130", "MASA!BL179", "OIS_MAIN!B336", "DV01_RISK!J6"):
        si, rc = b.cell(ref)
        svc.et.call(shared.get, si, *divmod(rc, COLS))
        assert not (shared.maskd[si].get(rc, 0) & bits), ref


def _on_date(svc, user, days):
    """MASA's broken date (C171) set to the FX spot + ``days`` for the user: the offshore discount factor there as the
    block reads it (BL179: the names on the user's setting)."""
    s0 = cell(svc, "Forward!I2")
    text = serial_to_date(s0 + days).strftime("%d.%m.%Y")
    assert not svc.set_inputs(user, "tto", [{"ref": "MASA!C171", "value": text}])["errors"]
    try:
        return cell(svc, "MASA!BL179", user)
    finally:
        svc.reset_inputs(user, "tto", ["MASA!C171"])


def _xccy18(svc, user):
    """Fiyatlama's XCCY 18M (spot start, received): its mids both ways and its schedule."""
    got = svc.pricing(user, {"asset": "xccy", "start": "", "end": "18M", "side": "RECEIVE", "size_kind": "nominal",
                             "size": "100m", "price": ""})
    assert got["label"] == "XCCY 18M" and not got.get("error")
    return got


def test_the_computed_18m_xccy_is_point_18m_and_fiyatlama_s_mid_and_adds_nothing(module_service, desk):
    """"18M hesaplanacak, gerçek kotasyon girilmeyecek": the default offshore list's 18M XCCY is computed - read off the
    offshore curve on the viewer's setting (Bootstrap: the curve the names give, PPK basamak: ppkcurve's) by
    ``aswfx.point_18m`` itself (EK_FX's 18M): the coupons counted back from the maturity, 6M then 12M, on the TRY calendar
    as Fiyatlama and MASA's broken-date block date them; its par is Fiyatlama's XCCY 18M mid on both methods (the replay
    day: 39,5879 % / 39,3752 %), its zero EK_FX's (once a year, ACT/365); on Bootstrap its discount factor is what the
    broken-date block reads at that date.  On or off, the curves do not move."""
    from tto import aswfx
    svc = module_service
    spot = cell(svc, "Forward!I2")
    book = svc.books["tto"]
    idx = book.model.sheet_index
    hol = svc.et.call(lambda: pk.holidays(lambda s, r, c: book.engine.shared.get(idx[s], r, c), pk.OIS_HOLIDAYS))
    t18 = pk.following(pk.edate(spot, 18), hol) - spot
    t6 = pk.following(pk.edate(spot, 6), hol) - spot
    seen = {}
    for who, method in (("boot", "boot"), ("ppk", "ppk")):
        user = desk[who]
        r = point(svc.curve_points(user), cpm.COMPUTED_18M)
        assert r["day"] == t18 and r["schedule"] == "%dg + %dg" % (t6, t18 - t6)
        cv = curves(svc, user)
        on = cv["off_ppk"] if method == "ppk" else cv["off_boot"]
        pt = aswfx.point_18m(on, t6, t18)
        assert (r["df"], r["value"], r["zero"]) == (pt.df, pt.par / 100.0, pt.zero / 100.0)          # (the very function)
        fx = _xccy18(svc, user)                                  # (both methods there: the user's own first)
        assert [(x["start"] - spot, x["pay"] - spot) for x in fx["schedule"]] == [(0.0, t6), (t6, t18)]
        assert fx["method"] == method and fx["mid"][method] == pytest.approx(r["value"], abs=1e-15)
        assert round(r["value"] * 100, 4) == {"boot": 39.5879, "ppk": 39.3752}[method]
        seen[method] = r
    assert fx["mid"]["boot"] == pytest.approx(seen["boot"]["value"], abs=1e-15)          # (the other way beside it)
    # Bootstrap: the discount factor the broken-date block reads at the 18M date (the names: every page's)
    assert seen["boot"]["df"] == pytest.approx(_on_date(svc, desk["boot"], t18), rel=1e-14)
    assert seen["boot"]["zero"] == pytest.approx(aswfx.zero_rate(seen["boot"]["df"], t18) / 100.0, rel=1e-15)
    assert abs(seen["ppk"]["df"] - seen["boot"]["df"]) > 1e-7          # (between the 1Y and 2Y quotes: the methods part)
    # no information added: off and on again, the curves are the same and nothing of the list is in the workbook
    before = curves(svc)
    admin = desk["admin"]
    svc.set_curve_points(admin, {"action": "off", "id": cpm.COMPUTED_18M})
    assert svc.curvepoints.specs() == {"ois": None, "off": None} and cell(svc, "EK_INTERP!N4") == 0.0
    after = curves(svc)
    assert after["off_boot"].lndf == before["off_boot"].lndf and after["off_ppk"].steps() == before["off_ppk"].steps()
    assert point(svc.curve_points(admin), cpm.COMPUTED_18M)["value"] is None
    svc.set_curve_points(admin, {"action": "on", "id": cpm.COMPUTED_18M})
    assert point(svc.curve_points(desk["boot"]), cpm.COMPUTED_18M)["df"] == seen["boot"]["df"]


# ================================================================================================== a list that differs
def test_a_typed_point_is_a_node_and_both_ways_price_it_back(module_service, desk):
    """A 2Y3M XCCY typed at 42,10 %: the offshore curve gets a node at its maturity, its swap - coupons counted back from
    the maturity, 3M + 12M + 12M - comes back at 42,10 % on Bootstrap (the names: every reader) and on PPK basamak; every
    other quote too; OIS stays the workbook's own.  Switched off: the curves are as before, to the bit."""
    svc = module_service
    admin, boot, ppk = desk["admin"], desk["boot"], desk["ppk"]
    g = names_of(svc)["OFF_GUN"]
    before = {"boot": reader(svc, boot, "off"), "ppk": reader(svc, ppk, "off")}
    res = svc.set_curve_points(admin, {"action": "add", "curve": "off", "kind": "xccy", "when": "2Y3M", "source": "typed",
                                       "rate": "42,10", "note": "aracı kotası, deneme"})
    assert "2Y3M" in res["done"] and res["custom"] == {"ois": False, "off": True}
    row = next(r for r in rows_of(res, "off") if r["name"] == "XCCY 2Y3M")
    assert row["note"] == "aracı kotası, deneme" and row["added_by"] == "Nokta Yönetici Ayla" and row["value"] == pytest.approx(0.421)
    assert [cell(svc, "EK_INTERP!%s" % a) for a in ("N3", "N4", "N5", "N6")] == [0.0, 1.0, 0.0, 1.0]
    d = row["day"]
    cv = curves(svc)
    q = next(x for x in cv["off_quotes"] if x.name == "XCCY 2Y3M")
    assert q.end == d and len(q.pays) == 3 and q.pays[0] < 100 and q.accruals[0] < 0.3          # the short period first
    assert d in names_of(svc)["OFF_GUN"] and d not in g                                          # a node of every reader
    for who, user in (("boot", boot), ("ppk", ppk)):
        read = reader(svc, user, "off")
        assert pk.par(read, q.pays, q.accruals) == pytest.approx(0.421, abs=1e-12), who
    for x in cv["off_quotes"]:
        assert pk.par(cv["off_ppk"], x.pays, x.accruals) == pytest.approx(x.rate, abs=1e-12), x.name
        assert pk.par(cv["off_boot"], x.pays, x.accruals) == pytest.approx(x.rate, abs=1e-12), x.name
    assert abs(reader(svc, boot, "off").df(d) - before["boot"].df(d)) > 1e-6                   # (it moved the curve there)
    # OIS: the workbook's own
    for r in (95, 98, 110):
        assert cell(svc, "Motor!F%d" % r) == own_formula(svc, svc.books["tto"].engine.shared, "F%d" % r)
    # an OIS point typed at 15M: Motor's 15M node is that par, PPK basamak prices it back on Motor's grid
    res = svc.set_curve_points(admin, {"action": "add", "curve": "ois", "kind": "ois", "when": "15M", "source": "typed",
                                       "rate": "35,00"})
    assert res["custom"] == {"ois": True, "off": True} and cell(svc, "EK_INTERP!N5") == 1.0
    assert cell(svc, "Motor!F95") == pytest.approx(0.35, abs=1e-15)
    cv = curves(svc)
    q15 = next(x for x in cv["quotes"] if x.name == "15M")
    assert q15.pays == tuple(cell(svc, "Motor!C%d" % r) for r in range(91, 96))
    assert pk.par(cv["ppk"], q15.pays, q15.accruals) == pytest.approx(0.35, abs=1e-12)
    for r in range(89, 131):
        assert cell(svc, "Motor!G%d" % r) == pytest.approx(cv["boot"].df(cell(svc, "Motor!C%d" % r)), rel=1e-13)
    # back to the default: every number as before (the workbook's own formulas)
    to_default(svc, admin)
    for r in (95, 98):
        assert cell(svc, "Motor!F%d" % r) == own_formula(svc, svc.books["tto"].engine.shared, "F%d" % r)
    assert names_of(svc)["OFF_GUN"] == g
    assert reader(svc, boot, "off").df(d) == before["boot"].df(d) and reader(svc, ppk, "off").df(d) == before["ppk"].df(d)
    p = svc.curve_points(admin)
    assert not next(r for r in rows_of(p, "off") if r["name"] == "XCCY 2Y3M")["on"]          # (kept, off, with its note)


def test_a_point_switched_off_is_interpolated_across(module_service, desk):
    """OIS 2Y off: Motor's nodes around it take the par linear in months between 18M and 3Y (Motor's own method on the
    list), PPK basamak no longer meets 2Y; offshore XCCY 2Y off: the 3Y's 2Y coupon reads the curve between 1Y and 3Y.
    On again: as before."""
    svc = module_service
    admin, boot, ppk = desk["admin"], desk["boot"], desk["ppk"]
    g = {r: cell(svc, "Motor!G%d" % r) for r in range(89, 131)}
    two = cell(svc, "Motor!B313")
    svc.set_curve_points(admin, {"action": "off", "id": "ois:2Y"})
    m18, m36 = cell(svc, "Motor!B312"), cell(svc, "Motor!B314")
    for r, months in ((97, 21), (98, 24), (99, 27)):
        assert cell(svc, "Motor!F%d" % r) == pytest.approx(m18 + (m36 - m18) * (months - 18) / 18.0, abs=1e-15)
    assert abs(cell(svc, "Motor!G98") - g[98]) > 1e-6 and cell(svc, "Motor!G96") == pytest.approx(g[96], rel=1e-14)
    cv = curves(svc)
    assert "2Y" not in [q.name for q in cv["quotes"]]
    pays = tuple(cell(svc, "Motor!C%d" % r) for r in range(91, 99))
    acc = tuple((b - a) / 365.0 for a, b in zip((0.0,) + pays[:-1], pays))
    assert abs(pk.par(cv["ppk"], pays, acc) - two) > 1e-6 and abs(pk.par(cv["boot"], pays, acc) - two) > 1e-6
    for q in cv["quotes"]:
        assert pk.par(cv["ppk"], q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-12)
    # the PPK user's Motor: the PPK curve on the list, at its nodes
    assert cell(svc, "Motor!G98", ppk) == pytest.approx(cv["ppk"].df(cell(svc, "Motor!C98")), rel=1e-13)
    svc.set_curve_points(admin, {"action": "on", "id": "ois:2Y"})
    assert all(cell(svc, "Motor!G%d" % r) == g[r] for r in g)
    # offshore: the 2Y XCCY off
    gun = names_of(svc)["OFF_GUN"]
    svc.set_curve_points(admin, {"action": "off", "id": "off:XCCY 2Y"})
    cv = curves(svc)
    q3 = next(q for q in cv["off_quotes"] if q.name == "XCCY 3Y")
    two_day = cell(svc, "Forward!K126")
    assert q3.pays[1] == two_day and two_day not in names_of(svc)["OFF_GUN"]
    assert pk.par(reader(svc, boot, "off"), q3.pays, q3.accruals) == pytest.approx(q3.rate, abs=1e-12)
    svc.set_curve_points(admin, {"action": "on", "id": "off:XCCY 2Y"})
    assert names_of(svc)["OFF_GUN"] == gun


def market(svc, user=None):
    """Fiyatlama's market of the user's calculation (on Bootstrap, as the service reads it)."""
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def run():
        base = svc.interp.boot_of(book, svc._calc(user, book))
        return pr.read(lambda s, r, c: base.get(idx[s], r, c))
    return svc.et.call(run)


def _buckets(got):
    return {r["name"]: r["dv01"] for r in got["buckets"]["rows"] if r["pillar"]}


def test_fiyatlama_s_dv01_buckets_are_the_list_s_points(module_service, desk):
    """Fiyatlama's DV01 buckets on the desk's list: every point that carries a rate and is on - the workbook's quote, a
    ticker, a typed rate - is a bucket, bumped and the curve built again the list's way; a computed point and the PPK
    meetings never are.  A 15M OIS paid: on the default list its DV01 is split between the 1Y and 18M buckets (15M is
    no quote); a typed 15M OIS point is a bucket of its own and takes it all, the buckets sum to the total and to a
    parallel bump (both methods); switched off, it is gone and every number is as before.  Offshore the same (a 2Y XCCY
    switched off: no 2Y bucket, the 3Y's 2Y coupon read off the curve)."""
    svc = module_service
    admin, u = desk["admin"], desk["boot"]
    ois = {"asset": "ois", "start": "", "end": "15M", "side": "PAY", "size_kind": "dv01", "size": "1000", "price": ""}
    before = svc.pricing(u, dict(ois))
    names0 = list(_buckets(before))
    assert names0 == [pk.tenor_label(int(m)) for m, _ in sorted(market(svc, u).ois_quotes)]          # (the workbook's)
    assert "ois_nodes" not in curves(svc, u) and "off_listed" not in curves(svc, u)                     # (the default list)
    b0 = _buckets(before)
    assert "15M" not in b0 and b0["1Y"]["boot"] > 200.0 and b0["18M"]["boot"] > 200.0                  # (between 1Y and 18M)
    res = svc.set_curve_points(admin, {"action": "add", "curve": "ois", "kind": "ois", "when": "15M", "source": "typed",
                                       "rate": "35,00", "note": "kova"})
    rid = next(r["id"] for r in rows_of(res, "ois") if r["note"] == "kova")
    try:
        got = svc.pricing(u, dict(ois))
        rows = _buckets(got)
        assert list(rows) == names0[:6] + ["15M"] + names0[6:]
        for m in pr.METHODS:                                       # (a quote now: the 15M swap's DV01 is its bucket's)
            assert rows["15M"][m] > 900.0 and abs(rows["1Y"][m]) < 1e-3 and abs(rows["18M"][m]) < 1e-3, m
        quotes = {r["name"]: r["quote"] for r in got["buckets"]["rows"]}           # (the bucket's quote: the rate typed)
        assert quotes["15M"] == pytest.approx(0.35, abs=1e-15) and quotes["1Y"] == dict(market(svc, u).ois_quotes)[12.0]
        assert not [n for n in rows if n.startswith(("MPC", "PPK"))]
        for m in pr.METHODS:
            assert got["buckets"]["total"][m] == pytest.approx(sum(r[m] for r in rows.values()), abs=1e-9)
        cv, mk = curves(svc, u), market(svc, u)
        deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", 15), mk)
        size = got["size"]["size"]
        up = [q._replace(rate=q.rate + 1e-4) for q in cv["quotes"]]
        k = got["mid"]["boot"]
        base = pk.list_ois_curve(cv["quotes"], cv["ois_nodes"])[1]
        assert pr.mid(deal, base) == pytest.approx(k, abs=1e-14)                        # (the mid on the list's curve)
        parallel = (pr.value(deal, pk.list_ois_curve(up, cv["ois_nodes"])[1], 1, size, k) - pr.value(deal, base, 1, size, k)) / mk.usdtry
        assert parallel == pytest.approx(got["buckets"]["total"]["boot"], rel=5e-3)
        k = got["mid"]["ppk"]
        parallel = (pr.value(deal, pk.calibrate(cv["shape"], up)[0], 1, size, k) - pr.value(deal, cv["ppk"], 1, size, k)) / mk.usdtry
        assert parallel == pytest.approx(got["buckets"]["total"]["ppk"], rel=5e-3)
    finally:
        svc.set_curve_points(admin, {"action": "off", "id": rid})
    again = svc.pricing(u, dict(ois))
    assert again["buckets"] == before["buckets"] and again["mid"] == before["mid"] and again["size"] == before["size"]
    # offshore: the 18M is computed (never a bucket); the 2Y XCCY switched off - no 2Y bucket, the rest sum up
    xccy = {"asset": "xccy", "start": "", "end": "2Y3M", "side": "RECEIVE", "size_kind": "dv01", "size": "1000"}
    x0 = svc.pricing(u, dict(xccy))
    assert "XCCY 18M" not in _buckets(x0) and "XCCY 2Y" in _buckets(x0)
    svc.set_curve_points(admin, {"action": "off", "id": "off:XCCY 2Y"})
    try:
        x1 = svc.pricing(u, dict(xccy))
        xr = _buckets(x1)
        assert "XCCY 2Y" not in xr and set(xr) == {q.name for q in curves(svc, u)["off_quotes"]}
        for m in pr.METHODS:
            assert x1["buckets"]["total"][m] == pytest.approx(sum(r[m] for r in xr.values()), abs=1e-9)
        assert x1["buckets"]["total"]["boot"] < -800.0 and xr["XCCY 3Y"]["boot"] < -300.0
    finally:
        svc.set_curve_points(admin, {"action": "on", "id": "off:XCCY 2Y"})
    assert svc.pricing(u, dict(xccy))["buckets"] == x0["buckets"]


def test_a_user_s_own_quote_reaches_their_curve_on_the_list(module_service, desk):
    """A list that differs: a user who types their own 1Y quote ("Elle değer") gets the list's cells of their own - their
    Motor's 1Y node is their quote; the desk's stays."""
    svc = module_service
    admin, kaan = desk["admin"], desk["own"]
    svc.set_curve_points(admin, {"action": "off", "id": "ois:2Y"})
    try:
        desk_1y = cell(svc, "Motor!B311")
        mine = desk_1y + 0.0030
        assert not svc.set_inputs(kaan, "tto", [{"ref": "Motor!B311", "value": mine}], allow_adhoc=True)["errors"]
        assert cell(svc, "Motor!F94", kaan) == pytest.approx(mine, abs=1e-15)
        assert cell(svc, "Motor!F94") == pytest.approx(desk_1y, abs=1e-15)
        assert svc.books["tto"].engine.derived.get(kaan)
    finally:
        svc.reset_inputs(kaan, "tto")
        svc.set_curve_points(admin, {"action": "on", "id": "ois:2Y"})
    assert cell(svc, "Motor!F94", kaan) == cell(svc, "Motor!F94")         # (back on everybody's calculation ...)
    assert not svc.books["tto"].engine.derived.get(kaan)                     # (... nothing worked out for him)


# ================================================================================================== PPK, tickers, who and the log
def test_ppk_meetings_are_always_in_the_list_and_follow_the_calendar(module_service, desk):
    svc = module_service
    admin = desk["admin"]
    for action in ("off", "note"):
        with pytest.raises(ServiceError) as exc:
            svc.set_curve_points(admin, {"action": action, "id": "ppk:MPC1", "note": "x"})
        assert "takvimden" in str(exc.value)
    h = svc.history
    start = h.meetings()
    spot = serial_to_date(cell(svc, "OIS_MAIN!B2")).isoformat()
    first = [d for d in start if d > spot][1]                               # (the second meeting ahead: MPC2)
    moved = (dt.date.fromisoformat(first) + dt.timedelta(days=7)).isoformat()
    try:
        h.set_calendar(admin, [moved if d == first else d for d in start])
        p = svc.curve_points(admin)
        for curve in ("ois", "off"):
            when = [r["when"] for r in rows_of(p, curve) if r["ppk"]]
            assert dt.date.fromisoformat(moved).strftime("%d.%m.%Y") in when
            assert dt.date.fromisoformat(first).strftime("%d.%m.%Y") not in when
    finally:
        h.set_calendar(admin, start)
    p = svc.curve_points(admin)
    assert dt.date.fromisoformat(first).strftime("%d.%m.%Y") in [r["when"] for r in rows_of(p, "ois") if r["ppk"]]


TICKER = "TESTNOKTA13M ICPL Curncy"


def test_a_ticker_point_says_its_cost_and_asks_bloomberg_nothing_before_the_yes(module_service, desk):
    """A Bloomberg ticker point is a new live subscription: without the desk's confirmation nothing is saved and nothing
    is asked of Bloomberg (the stand-in records every request); confirmed, its slot holds the ticker, MID / BID / ASK
    are asked and its rate (a percent) is a point of the curve; switched off, the slot is empty again - on again, the
    cost is asked once more."""
    svc = module_service
    admin = desk["admin"]
    prov = svc.provider
    asked = []
    real = prov.get_bdp

    def recording(key):
        asked.append(key)
        return real(key)

    prov.get_bdp = recording
    try:
        rev = svc.curvepoints.rev
        body = {"action": "add", "curve": "off", "kind": "fx", "when": "13M", "source": "ticker", "ticker": TICKER.lower(),
                "note": "ICAP 13A"}
        res = svc.set_curve_points(admin, body)
        assert res["needs_confirm"] and res["ticker"] == TICKER and "3 veri noktası" in res["cost"]
        assert "günlük sınır" in res["cost"] and "replay" in res["cost"]
        assert svc.curvepoints.rev == rev and not any(r.get("ticker") for r in svc.curvepoints.rows)
        svc.view(admin, "ois")
        svc.curve_points(admin)
        assert not [k for k in asked if TICKER in str(k)]                                # (nothing asked)
        assert all(cell(svc, "EK_INTERP!U%d" % r) is None for r in range(10, 30))
        # the yes: saved, the slot holds it, Bloomberg is asked
        svc.provider.set(bdp_key(TICKER, "MID"), 40.25)
        res = svc.set_curve_points(admin, dict(body, confirm=True))
        row = next(r for r in rows_of(res, "off") if r["source"] == "ticker")
        assert row["ticker"] == TICKER and row["on"] and "onayladı" in row["source_tip"]
        assert cell(svc, "EK_INTERP!U10") == TICKER and cell(svc, "EK_INTERP!Y10") == 40.25
        assert {k[2] for k in asked if TICKER in str(k)} >= {"MID"}
        assert row["value"] == pytest.approx(0.4025)
        cv = curves(svc)
        q = next(x for x in cv["off_quotes"] if x.name == "FX 13M")
        assert q.rate == pytest.approx(0.4025) and q.pays == (row["day"],)
        assert pk.par(reader(svc, desk["boot"], "off"), q.pays, q.accruals) == pytest.approx(0.4025, abs=1e-12)
        # off: the slot is empty (no subscription asked for again); on again needs the yes once more
        res = svc.set_curve_points(admin, {"action": "off", "id": row["id"]})
        assert cell(svc, "EK_INTERP!U10") is None and not res["custom"]["off"]
        n = len(asked)
        svc.view(admin, "ois")
        assert not [k for k in asked[n:] if TICKER in str(k)]
        res = svc.set_curve_points(admin, {"action": "on", "id": row["id"]})
        assert res["needs_confirm"] and not next(r for r in svc.curvepoints.rows if r["id"] == row["id"])["on"]
    finally:
        prov.get_bdp = real
        to_default(svc, admin)


def test_only_administrators_change_the_list_and_every_change_is_logged(module_service, desk):
    svc = module_service
    admin, boot = desk["admin"], desk["boot"]
    with pytest.raises(ServiceError) as exc:
        svc.set_curve_points(boot, {"action": "off", "id": "ois:1M"})
    assert exc.value.status == 403
    assert svc.curve_points(boot)["can_edit"] is False
    res = svc.set_curve_points(admin, {"action": "add", "curve": "ois", "kind": "ois", "when": "27.05.2027", "source": "typed",
                                       "rate": "34,9", "note": "toplantı tarihli OIS"})
    rid = next(r["id"] for r in rows_of(res, "ois") if r["note"] == "toplantı tarihli OIS")
    svc.set_curve_points(admin, {"action": "note", "id": rid, "note": "MPC tarihli OIS (aracı)"})
    svc.set_curve_points(admin, {"action": "rate", "id": rid, "rate": "35,10"})
    for bad in ({"action": "add", "curve": "ois", "kind": "xccy", "when": "2Y", "source": "typed", "rate": "1"},
                {"action": "add", "curve": "off", "kind": "fx", "when": "yarın", "source": "typed", "rate": "1"},
                {"action": "add", "curve": "ois", "kind": "ois", "when": "1Y", "source": "typed", "rate": "36"},
                {"action": "rate", "id": "ois:1Y", "rate": "36"}, {"action": "nope"}):
        with pytest.raises(ServiceError):
            svc.set_curve_points(admin, bad)
    none_on = [dict(r, on=False) if r["curve"] == "ois" else r for r in cpm.default_rows()]
    with pytest.raises(ServiceError) as exc:                                   # (a curve keeps one point at least)
        svc.curvepoints._check(none_on)
    assert "en az bir nokta" in str(exc.value)
    to_default(svc, admin)
    log = svc.curve_points(boot)["log"]
    texts = [e["text"] for e in log]
    assert texts[0].startswith("Varsayılana dönüldü") and "kapatıldı" in texts[0]
    assert any("oranı 34,9000% → 35,1000%" in t for t in texts) and any("notu:" in t and "MPC tarihli OIS" in t for t in texts)
    assert any(t.startswith("OIS · 27.05.2027 eklendi") for t in texts)
    assert all(e["by"] == admin and e["who"] == "Nokta Yönetici Ayla" and e["at"] for e in log)
    assert svc.store.get(cpm.LOG_KEY)[-1]["text"] == texts[0]
    # kept across a restart of the list (the store): the same rows, the same specs
    again = cpm.CurvePoints(svc)
    assert [r["id"] for r in again.rows] == [r["id"] for r in svc.curvepoints.rows] and again.specs() == svc.curvepoints.specs()


# ================================================================================================== over HTTP (last: it stops the service)
def test_ayarlar_reads_the_list_and_only_an_administrator_changes_it(module_service, desk):
    svc = module_service
    with TestClient(create_app(svc)) as c:
        user, admin = auth(svc, "Nokta HTTP Deniz"), auth(svc, "Nokta HTTP Yönetici", admin=True)
        got = c.get("/api/curve-points", headers=user).json()
        assert got["available"] and not got["can_edit"] and [x["id"] for x in got["curves"]] == ["ois", "off"]
        assert c.post("/api/curve-points", json={"action": "off", "id": "ois:1M"}, headers=user).status_code == 403
        got = c.post("/api/curve-points", json={"action": "add", "curve": "off", "kind": "xccy", "when": "2Y6M", "source": "typed",
                                                "rate": "41,5", "note": "HTTP"}, headers=admin).json()
        assert got["custom"]["off"] and got["can_edit"]
        rid = next(r["id"] for r in rows_of(got, "off") if r["note"] == "HTTP")
        got = c.post("/api/curve-points", json={"action": "off", "id": rid}, headers=admin).json()
        assert not got["custom"]["off"]
        assert c.post("/api/curve-points", json={"action": "add", "curve": "off", "kind": "fx", "when": "7M", "source": "ticker",
                                                 "ticker": "TRYI7M ICPL Curncy"}, headers=admin).json()["needs_confirm"]
