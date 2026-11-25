"""Curve fair value (``tto/quantcurve.py``): Nelson-Siegel-Svensson fits that recover a known curve from OIS par rates
(the workbook's conventions) and from bond yields (BIST's), the DİBS curve's Nelson-Siegel recovering a planted one from
the fixed-coupon bonds - the bills priced on it, not fitted (a bill does not move the curve: the desk's decision of
18.11.2026) -, the model rule (NS whatever the number of bonds) and leave-one-out residuals, a bond priced off a known
curve being neither rich nor cheap, one planted bond / tenor being the one that is, carry and roll on flat and sloped
curves, the families' signals on a synthetic history, the read of the DİBS RV sheet - and the service and the HTTP API
of both new pages ("Eğri Adil Değeri", "Opsiyon") on a seeded two-year history."""
from __future__ import annotations

import datetime as dt
import math
import statistics

import pytest
from starlette.testclient import TestClient

import quant_synth
import quant_synth_extra as qx
from conftest import auth
from tto import quantcurve as qc
from tto import quantfam as qf
from tto import quantopt as qo
from tto.quant import DEFAULTS, series_specs
from tto.server import create_app

TODAY = dt.date(2026, 11, 3)
OIS_MONTHS = {"OIS:1M": 1.0, "OIS:2M": 2.0, "OIS:3M": 3.0, "OIS:6M": 6.0, "OIS:9M": 9.0, "OIS:1Y": 12.0, "OIS:18M": 18.0, "OIS:2Y": 24.0,
              "OIS:3Y": 36.0, "OIS:4Y": 48.0, "OIS:5Y": 60.0, "OIS:6Y": 72.0, "OIS:7Y": 84.0, "OIS:8Y": 96.0, "OIS:9Y": 108.0, "OIS:10Y": 120.0}
TRUE = qc.Nss([0.30, 0.08, -0.06, 0.04], 0.9, 4.5)


def ois_day(curve, months=OIS_MONTHS, day=TODAY):
    """One day's par rates of a known curve, in the workbook's conventions."""
    probe = qc.OisDay(day, [(k, m, 0.3) for k, m in months.items()])
    return qc.OisDay(day, list(zip(probe.keys, probe.months, probe.pars(curve))))


# ================================================================================================ the curve
def test_loadings_ends_and_forward():
    c = TRUE
    b0, b1 = c.beta[:2]
    assert abs(c.zero(1e-9) - (b0 + b1)) < 1e-9 and abs(c.zero(500.0) - b0) < 2e-3          # the overnight and the long end
    assert abs(c.forward(0.0) - (b0 + b1)) < 1e-12
    for t in (0.1, 1.0, 3.7, 9.0):                         # f(t) = d(z·t)/dt
        h = 1e-5
        assert abs(c.forward(t) - ((t + h) * c.zero(t + h) - (t - h) * c.zero(t - h)) / (2 * h)) < 1e-8
    assert abs(c.df(2.0) - math.exp(-2.0 * c.zero(2.0))) < 1e-15


def test_ois_pars_follow_the_workbooks_conventions():
    """Motor!A325:K340: one payment up to 3M, ACT/365 - par = (1/DF − 1)/τ -, quarterly coupons from 6M on -
    par = (1 − DF(T)) / Σ τ_k·DF(t_k) - on dates months on from the OIS spot (the next week day)."""
    day = ois_day(TRUE, {"OIS:1M": 1.0, "OIS:3M": 3.0, "OIS:6M": 6.0, "OIS:2Y": 24.0})
    spot = qc.next_weekday(TODAY)
    assert day.spot == spot == dt.date(2026, 11, 4)

    def t(d):
        return (d - spot).days / 365.0

    one = qc._weekday_on_or_after(qf._add_months(spot, 1))
    assert abs(day.par[0] - (1 / TRUE.df(t(one)) - 1) / t(one)) < 1e-14
    q = [qc._weekday_on_or_after(qf._add_months(spot, m)) for m in (3, 6, 9, 12, 15, 18, 21, 24)]
    ann = sum((b - a).days / 365.0 * TRUE.df(t(b)) for a, b in zip([spot] + q, q))
    assert abs(day.par[3] - (1 - TRUE.df(t(q[-1]))) / ann) < 1e-14
    flat = qc.Nss([0.35, 0, 0, 0], 1.0, 3.0)
    p6 = ois_day(flat, {"OIS:6M": 6.0}).par[0]
    assert 0.35 < p6 < 4 * (math.exp(0.35 / 4) - 1) + 1e-3          # quarterly coupons: a little above the continuous rate


def test_fit_recovers_known_nss_parameters_from_ois_pars():
    day = ois_day(TRUE)
    found = qc.search(day.make)
    nss = found["nss"]
    assert max(abs(a - b) for a, b in zip(nss.beta, TRUE.beta)) < 1e-6
    assert abs(nss.tau1 / TRUE.tau1 - 1) < 1e-5 and abs(nss.tau2 / TRUE.tau2 - 1) < 1e-5
    assert math.sqrt(found["sse"] / len(day)) * 1e4 < 1e-6                 # bp
    # the β alone, the τ held: the same from any start
    again = qc.refit(day.make, qc.Nss([0.2, 0.0, 0.0, 0.0], nss.tau1, nss.tau2))
    assert max(abs(a - b) for a, b in zip(again["nss"].beta, TRUE.beta)) < 1e-6


def test_a_planted_tenor_is_the_cheap_one_and_does_not_bend_its_neighbours():
    day = ois_day(TRUE)
    bumped = list(day.par)
    j = day.keys.index("OIS:2Y")
    bumped[j] += 0.0015                                                     # 2Y quoted 15 bp above the curve
    found = qc.search(qc.OisDay(TODAY, list(zip(day.keys, day.months, bumped))).make)
    resid = [-e * 1e4 for e in found["resid"]]                              # quote − fit
    assert found["weights"] is not None and found["weights"][j] < 0.5
    # the Huber fit keeps most of it on the tenor (least squares: two thirds), its neighbours within 2 bp
    assert 12.5 < resid[j] < 15.0 and max(abs(r) for i, r in enumerate(resid) if i != j) < 2.0
    plain = qc.search(qc.OisDay(TODAY, list(zip(day.keys, day.months, bumped))).make, robust=False)
    assert -plain["resid"][j] * 1e4 < resid[j] - 2.0


# ================================================================================================ bonds
BONDS = qx.bond_list(TODAY)


def priced(curve, bonds=BONDS, conv="simple", bump=None):
    """Each bond's yield priced off ``curve`` (value date the next week day), ``bump``: {isin: bp} added."""
    out = []
    for b in bonds:
        v = qc.next_weekday(TODAY)
        flows, _ = b.flows(v)
        p = sum(cf * curve.df((d - v).days / 365.0) for d, cf in flows)
        y = b.yield_of(p, v, conv, 0.3) + ((bump or {}).get(b.isin, 0.0) / 1e4)
        out.append((b, v, y, conv))
    return qc.BondFit(out)


def test_bond_prices_follow_the_sheets_bist_conventions():
    """DİBS RV: coupons of c/f every round(364/f) days back from the maturity, the yield compounded f times a year
    over the periods left (the first a fraction); compound = (1 + y/f)^f − 1; a bill's simple (100/P − 1)·365/days."""
    b = qc.Bond("TRT150328T24", "15.03.28", "fixed", dt.date(2028, 3, 15), 36.8, 2)
    v = dt.date(2026, 11, 4)                                                  # the sheet's value date of this bond (replay, ISL1)
    flows, frac = b.flows(v)
    assert flows == [(dt.date(2027, 3, 17), 18.4), (dt.date(2027, 9, 15), 18.4), (dt.date(2028, 3, 15), 118.4)]
    assert abs(frac - 133 / 182) < 1e-15                                     # DİBS RV!DS8
    y = 0.3639184043698062                                                    # its simple yield (DİBS RV!S8) …
    p, dp = b.price(y, v)
    assert abs(p - 105.06634615384735) < 1e-9                                 # … is its dirty price (DİBS RV!R8)
    assert abs(b.yield_of(p, v) - y) < 1e-12 and dp < 0
    pc, _ = b.price((1 + y / 2) ** 2 - 1, v, "compound")                      # DİBS RV!T8 = (1 + S8/2)² − 1
    assert abs(pc - p) < 1e-10
    bill = qc.Bond("TRB100227T13", "10.02.27", "bill", dt.date(2027, 2, 10))
    pb, _ = bill.price(0.31103706770590284, dt.date(2026, 11, 3))            # S5 (ISL0: its own day) …
    assert abs(pb - 92.22) < 1e-9                                             # … the bill's price R5
    days = (dt.date(2027, 2, 10) - dt.date(2026, 11, 3)).days
    assert abs(bill.price((1 + 0.31103706770590284 * days / 365) ** (365 / days) - 1, dt.date(2026, 11, 3), "compound")[0] - pb) < 1e-10


@pytest.mark.parametrize("conv", ["simple", "compound"])
def test_bonds_priced_off_a_known_curve_are_neither_rich_nor_cheap(conv):
    """A Svensson curve (the search's ``k`` 4, the OIS family's model) recovered from the fixed-coupon bonds priced off
    it; the bills, priced off it too and not fitted, are on it."""
    fit_in = priced(TRUE, conv=conv)
    # the fixed-coupon bonds fitted, the bills not (``FIT_KINDS``)
    assert fit_in.n_fit == 12 and {fit_in.bonds[i].kind for i in fit_in.fitted} == {"fixed"} and fit_in.n_bills == 2
    found = qc.search(fit_in.make, tau_min=fit_in.shortest, tau_max=fit_in.longest)
    assert max(abs(e) * 1e4 for e in found["resid"]) < 0.01                 # bp
    assert max(abs(a - b) for a, b in zip(found["nss"].beta, TRUE.beta)) < 1e-5
    every, _ = fit_in.evaluate(found["nss"])
    assert len(every) == len(BONDS) and max(abs(e) * 1e4 for e in every) < 0.01          # the bills too: the same curve
    exact = [(y - m) * 1e4 for y, m in zip(fit_in.y, fit_in.model_yields(found["nss"]))]
    assert max(abs(e) for e in exact) < 0.01
    # a bond 25 bp cheap: its own residual, its neighbours not bent onto it (Huber)
    cheap = priced(TRUE, conv=conv, bump={qx.PLANTED: 25.0})
    res = qc.search(cheap.make, tau_min=cheap.shortest, tau_max=cheap.longest)
    r = {b.isin: e * 1e4 for b, e in zip(cheap.bonds, cheap.evaluate(res["nss"])[0])}
    # (twelve bonds fitted: each has some leverage, the Huber fit keeps a few bp of the bump in the curve)
    assert abs(r[qx.PLANTED] - 25.0) < 4.0 and max(abs(v) for k, v in r.items() if k != qx.PLANTED) < 2.0


#: a Nelson-Siegel curve (β3 0, one hump): the DİBS curve's model
TRUE_NS = qc.Nss([0.30, 0.07, -0.06], 1.3, 1.3, qc.NS)


@pytest.mark.parametrize("conv", ["simple", "compound"])
def test_the_dibs_curve_is_nelson_siegel_and_recovers_a_planted_one(conv):
    """The DİBS search (``dibs_search``, the quant family's and Genel's) is Nelson-Siegel's: three β and τ1 recovered
    from the fixed-coupon bonds priced off a planted NS curve; nothing rich or cheap (the bills, priced off it and not
    fitted, neither); its parameters say NS (no β3, τ2)."""
    fit_in = priced(TRUE_NS, conv=conv)
    found = qc.dibs_search(fit_in)
    nss = found["nss"]
    assert nss.k == qc.NS == 3 and nss.model == "NS" and nss.beta[3] == 0.0
    assert max(abs(a - b) for a, b in zip(nss.beta, TRUE_NS.beta)) < 1e-6 and abs(nss.tau1 / TRUE_NS.tau1 - 1) < 1e-5
    every, _ = fit_in.evaluate(nss)
    assert len(every) == len(BONDS) and max(abs(e) * 1e4 for e in every) < 0.01
    info = nss.info()
    assert info["model"] == "NS" and info["b3"] is None and info["tau2"] is None and abs(info["b0"] - 30.0) < 1e-4
    # the β alone, the τ held (the window's days, the live refit): the same, from any start; Svensson's own unchanged
    again = qc.refit(fit_in.make, qc.Nss([0.2, 0.0, 0.0], nss.tau1, nss.tau1, qc.NS))
    assert again["nss"].k == qc.NS and max(abs(a - b) for a, b in zip(again["nss"].beta, TRUE_NS.beta)) < 1e-6
    assert len(again["jac"][0]) == 3


def test_a_bill_is_priced_on_the_curve_not_fitted():
    """The bills are not in the fit (``FIT_KINDS``: the fixed-coupon bonds - the desk's decision of 18.11.2026): a bill's
    yield does not move the curve, its rich / cheap takes the whole move - read off the coupon bonds' curve at the short
    end -, with its model yield the curve's.  (Fitted too, as before that day, the bill pulled the short end towards it
    and its rich / cheap took only part of the move; least squares there: the robust fit would take one bill 40 bp off
    the others for an outlier and down-weight it, as it does any bond.)"""
    assert qc.FIT_KINDS == ("fixed",)
    base = priced(TRUE_NS)
    bill = next(i for i, b in enumerate(base.bonds) if b.kind == "bill" and base.flows[i][-1][0] < 0.5)
    isin = base.bonds[bill].isin
    moved = priced(TRUE_NS, bump={isin: 40.0})
    assert bill not in moved.fitted and moved.n_fit == len(BONDS) - 2 and moved.n_bills == 2
    curve = qc.refit(moved.make, TRUE_NS, TRUE_NS.beta)["nss"]
    t = base.flows[bill][-1][0]
    assert abs(curve.zero(t) - TRUE_NS.zero(t)) * 1e4 < 1e-6                    # the short end where the coupon bonds put it
    assert abs(moved.evaluate(curve)[0][bill] * 1e4 - 40.0) < 1.0               # the bill 40 bp cheap: all of it its own
    assert abs(moved.model_yields(curve)[bill] - base.y[bill]) * 1e4 < 1e-6     # its model yield: the curve's
    # (the bills fitted too: the short end pulled up by the bill, its own rich / cheap a part of the 40 bp)
    both = qc.BondFit([(b, v, y, c) for b, v, y, c in zip(moved.bonds, moved.value, moved.y, moved.conv)], ("fixed", "bill"))
    assert bill in both.fitted and both.n_fit == len(BONDS) and both.n_bills == 0
    pulled = qc.refit(both.make, TRUE_NS, TRUE_NS.beta, robust=False)["nss"]
    assert (TRUE_NS.zero(t) - pulled.zero(t)) * 1e4 < -1.0 and 0 < both.evaluate(pulled)[0][bill] * 1e4 < 40.0


def test_the_bills_do_not_make_up_the_dibs_fits_count():
    """The family's DİBS fit needs ``MIN_BONDS`` fixed-coupon bonds - on the list, then with a yield -: the bills, not
    fitted, do not count (two bills and five coupon bonds on the list are not enough; six coupon bonds, five of them
    with a yield, neither)."""
    def rows(n):
        return [{"isin": b.isin, "type": "B" if b.kind == "bill" else "S", "name": b.isin, "maturity": b.maturity.isoformat(),
                 "coupon": b.coupon, "freq": 2.0, "source": "ISL1"} for b in qx.bond_list(TODAY)[:n]]

    few = rows(7)                                                           # the two bills, five coupon bonds
    assert [r["type"] for r in few].count("B") == 2 and qc.MIN_BONDS == 6
    live = {"DIBSS:" + r["isin"]: 35.0 for r in few}
    mons, table = qc.fam_dibs(qf.Ctx(dict(DEFAULTS), TODAY, {}, {}, live=live), {"dibs": few}, None)
    assert mons == [] and not table["ok"] and table["why"] == "DİBS RV listesinde en az 6 sabit kuponlu kâğıt gerekli"
    six = rows(8)                                                           # a sixth coupon bond, without a yield
    mons, table = qc.fam_dibs(qf.Ctx(dict(DEFAULTS), TODAY, {}, {}, live=live), {"dibs": six}, None)
    assert mons == [] and not table["ok"] and table["why"] == "en az 6 sabit kuponlu kâğıdın getirisi gerekli"
    live["DIBSS:" + six[-1]["isin"]] = 35.0
    mons, table = qc.fam_dibs(qf.Ctx(dict(DEFAULTS), TODAY, {}, {}, live=live), {"dibs": six}, None)
    assert table["ok"] and table["build"](live)["n_fit"] == 6 and table["build"](live)["n_bills"] == 2


def test_the_model_is_nelson_siegel_whatever_the_number_of_bonds():
    """The rule (the evidence at ``quantcurve.DIBS_MODEL``): NS for the DİBS curve with 8 bonds as with 40 - no number of
    bonds the list holds is one where Svensson's two more parameters pay out of sample; the OIS curve stays NSS."""
    assert qc.DIBS_MODEL == qc.NS and qc.MODEL_NAMES[qc.DIBS_MODEL] == "NS"
    for n in (8, 40):
        bonds = [qc.Bond("TRT%09dT1" % i, "", "fixed", TODAY + dt.timedelta(days=int(365 * (0.4 + 9.5 * i / n))), 30.0, 2)
                 for i in range(n)]
        fit_in = priced(TRUE, bonds=bonds)
        assert fit_in.n_fit == n and qc.dibs_search(fit_in)["nss"].k == qc.NS
    # (the OIS family's search: Svensson's)
    assert qc.search(ois_day(TRUE).make)["nss"].k == qc.NSS


def test_leave_one_out_is_the_distance_from_a_curve_fitted_without_the_bond():
    """``BondFit.loo``: each fitted bond against the curve refitted without it (the model and τ held).  Off a planted curve
    every one is on it; a bond 30 bp cheap is that far from the curve that never saw it - further than its own residual,
    which the fit pulled the curve a little towards - and its neighbours stay near the curve."""
    clean = priced(TRUE_NS)
    nss = qc.dibs_search(clean)["nss"]
    assert max(abs(e) * 1e4 for e in clean.loo(nss)) < 0.01 and qc.loo_rmse(clean, nss) < 0.01
    cheap = priced(TRUE_NS, bump={qx.PLANTED: 30.0})
    fit = qc.refit(cheap.make, nss, nss.beta)
    own = {b.isin: e * 1e4 for b, e in zip(cheap.bonds, cheap.evaluate(fit["nss"])[0])}
    loo = {cheap.bonds[i].isin: e * 1e4 for i, e in zip(cheap.fitted, cheap.loo(fit["nss"]))}
    assert set(loo) == {b.isin for b in cheap.bonds if b.kind == "fixed"}                  # the fitted bonds' (no bill)
    assert abs(loo[qx.PLANTED] - 30.0) < 0.5 and own[qx.PLANTED] < loo[qx.PLANTED]
    assert max(abs(v) for k, v in loo.items() if k != qx.PLANTED) < 3.0
    assert qc.loo_rmse(cheap, fit["nss"]) == pytest.approx(math.sqrt(sum(v * v for v in loo.values()) / len(loo)), rel=1e-12)


def test_carry_and_roll_on_flat_and_sloped_curves():
    b = qc.Bond("TRT000001T11", "x", "fixed", dt.date(2029, 9, 12), 30.0, 2)
    v = dt.date(2026, 11, 4)
    flat = qc.Nss([0.33, 0, 0, 0], 1.0, 3.0)
    flows, _ = b.flows(v)
    p = sum(cf * flat.df((d - v).days / 365.0) for d, cf in flows)
    for conv in ("simple", "compound"):
        y = b.yield_of(p, v, conv)
        same = qc.carry_roll(b, v, y, conv, flat, 0.0, 30, lambda t: 1.0 / flat.df(t))
        # funded at the curve's own rate, on a flat curve: nothing to earn, nothing to roll
        assert abs(same["carry_bp"]) < 0.05 and abs(same["roll_bp"]) < 0.05, (conv, same)
        cheap = qc.carry_roll(b, v, y, conv, flat, 0.0, 30, lambda t: math.exp(0.32 * t))
        dur = -b.price(y, v + dt.timedelta(days=30), conv)[1] / b.price(y, v + dt.timedelta(days=30), conv)[0]
        # one point cheaper funding: ~1 % × 30/365 of the price, over the DV01
        assert abs(cheap["carry_bp"] - 0.01 * 30 / 365 / dur * 1e4) < 0.3, (cheap, dur)
    rising = qc.Nss([0.36, -0.06, 0, 0], 1.5, 4.0)                          # upward sloping: rolling down it gains
    falling = qc.Nss([0.30, 0.06, 0, 0], 1.5, 4.0)
    for curve, sign in ((rising, 1), (falling, -1)):
        p = sum(cf * curve.df((d - v).days / 365.0) for d, cf in flows)
        y = b.yield_of(p, v)
        res = qc.carry_roll(b, v, y, "simple", curve, 0.0, 30, lambda t: 1.0 / curve.df(t))
        assert sign * res["roll_bp"] > 0.5, (sign, res)
    # a coupon paid within the horizon is received, not lost
    near = qc.carry_roll(b, flows[0][0] - dt.timedelta(days=3), y, "simple", falling, 0.0, 7, lambda t: 1.0 / falling.df(t))
    assert abs(near["carry_bp"]) < 50


def test_the_history_convention_is_the_sheets_closer_yield():
    assert qc.detect_convention(36.2, 36.39, 39.70) == "simple"
    assert qc.detect_convention(39.6, 36.39, 39.70) == "compound"
    assert qc.detect_convention(25.0, 36.39, 39.70) == "simple"              # far from both: nothing said, the default
    assert qc.detect_convention(None, 36.39, 39.70) == "simple"


# ================================================================================================ the families
def synth_ctx(live=None, planted=qx.PLANTED, conv="simple", **kw):
    days, data = quant_synth.build(TODAY, OIS_MONTHS, 520, 11, **kw)
    meta = {k: {"label": k[4:] + " OIS", "kind": "rate", "months": m, "group": "ois"} for k, m in OIS_MONTHS.items()}
    for s in series_specs():
        meta.setdefault(s["key"], {"label": s["label"], "kind": s["kind"], "group": s["group"]})
    meta["TLREF"] = {"label": "TLREF", "kind": "rate"}
    _, ys, _ = qx.bond_yields(TODAY, planted=planted, conv=conv)
    rows = []
    for b in qx.bond_list(TODAY):
        typ = "B" if b.kind == "bill" else "S"
        data["DIBS:" + b.isin] = ys[b.isin]
        meta["DIBS:" + b.isin] = {"label": b.isin, "kind": "rate", "group": "dibs", "unit": "pct", "maturity": b.maturity.isoformat(),
                                  "name": b.isin, "type": typ}
        rows.append({"isin": b.isin, "type": typ, "name": b.isin, "maturity": b.maturity.isoformat(), "coupon": b.coupon, "freq": 2.0,
                     "source": "ISL1"})
    return qf.Ctx(dict(DEFAULTS), TODAY, data, meta, live=live), {"dibs": rows}, data


def run(ctx, eng):
    mons, tables, timing = [], {}, {}
    qc.run(ctx, eng, mons, tables, timing)
    qf.score_all(ctx, mons, ctx.live)
    t = dict(tables)
    qc.live_tables(t, ctx)
    return mons, tables, t, timing


@pytest.fixture(scope="module")
def fitted():
    ctx, eng, data = synth_ctx()
    return (ctx, eng, data) + run(ctx, eng)


def test_curve_family_finds_the_planted_tenor(fitted):
    ctx, eng, data, mons, tables, t, timing = fitted
    assert not tables["errors"]
    sig = {s["id"]: s for s in (qf.make_signal(m, ctx.cfg, "10:00") for m in mons) if s}
    s = sig["curve:OIS:2Y"]
    assert s["expression"].startswith("Receive 2Y OIS") and s["z"] > 2 and s["family_label"] == "Eğri adil değeri"
    # the series is the tenor's own distance from the fit; the hedge is the package's, every leg told
    assert s["instrument"] == "2Y OIS · NSS farkı" and s["expression"] == " · ".join("%s %s" % (l["action"], l["name"]) for l in s["legs"])
    assert [p["name"] for p in s["packages"]] == ["Paket · iki komşu vadeyle hedge'li (NSS seviye β0 ve eğim β1'e nötr, DV01 ağırlıklı)"]
    # the package: the tenor and two neighbours, neutral to the fit's level and slope
    m = next(x for x in mons if x.sid == "curve:OIS:2Y")
    day = t["curve"]
    rows = {r["key"]: r for r in day["rows"]}
    assert len(m.legs) == 3 and all(leg["key"] in rows for leg in m.legs)
    c = day["rows"]
    assert day["ok"] and day["n"] == len(OIS_MONTHS) and day["rmse"] < 15 and rows["OIS:2Y"]["resid"] > 0
    assert all(abs(r["par"] - r["fit"] - r["resid"] / 100) < 1e-9 for r in c)
    assert timing["curve"] < 5.0


def test_dibs_family_finds_the_planted_bond_with_carry_and_ranking(fitted):
    ctx, eng, data, mons, tables, t, timing = fitted
    d = t["dibsfv"]
    assert d["ok"] and d["n"] == len(qx.BONDS) and d["days"] == ctx.window()
    rows = {r["isin"]: r for r in d["rows"]}
    planted = rows[qx.PLANTED]
    sd_eq = qx.MISPRICE_SD / math.sqrt(1 - 0.85 ** 2) * 1e4
    assert abs(planted["resid"] - 3 * sd_eq) < 8 and planted["z"] > DEFAULTS["entry_z"]
    # the fixed-coupon bonds are fitted (3 bp of noise each), by Nelson-Siegel (the synthetic curve is Svensson's: its
    # second hump is not in the model); the bills are priced on the curve, not fitted (``n_bills``: the bills out of the
    # fit) - each with a model yield and a rich / cheap, as any bond; the fit's leave-one-out RMSE beside its RMSE
    assert d["n_fit"] == len(qx.BONDS) - 2 == 12 and d["n_bills"] == 2 and all(r["fitted"] == (r["kind"] == "fixed") for r in d["rows"])
    assert all(r["weight"] is None and r["model"] is not None and r["resid"] is not None for r in d["rows"] if r["kind"] == "bill")
    assert d["model"] == "NS" and d["params"]["model"] == "NS" and d["params"]["b3"] is None and d["rmse"] < d["loo"] < 3 * d["rmse"]
    # (the bills too: priced off the same synthetic curve, they sit on the coupon bonds' one at the short end)
    assert max(abs(r["resid"]) for k, r in rows.items() if k != qx.PLANTED) < 12
    assert max(rows.values(), key=lambda r: r["z"] or -9)["isin"] == qx.PLANTED
    sig = {s["id"]: s for s in (qf.make_signal(m, ctx.cfg, "10:00") for m in mons) if s}
    s = sig["dibsfv:" + qx.PLANTED]
    assert s["expression"].startswith("Buy ") and s["family_label"] == "DİBS adil değeri" and s["asset"] == "DİBS"
    assert s["legs"][0]["key"] == "DIBS:" + qx.PLANTED and len(s["legs"]) == 3
    # carry + roll for both horizons, funded on the OIS fit; the bonds sit below the OIS curve here (negative spread)
    for r in d["rows"]:
        assert r["funding"] == "OIS" and all(r[k] is not None for k in ("carry_1w", "roll_1w", "carry_1m", "roll_1m", "total_1m"))
        assert abs(r["total_1m"] - r["carry_1m"] - r["roll_1m"]) < 1e-9 and r["ois_spread"] < 0
        assert abs(r["model"] - (r["yield"] - r["resid"] / 100)) < 1e-12
    assert abs(rows[qx.PLANTED]["total_1m"] / rows[qx.PLANTED]["total_1w"] - 30 / 7) < 1.5
    # the ranking: z × (carry + roll) / σ, cheap on the receive side, rich on the pay side, best first
    for side, sign in (("receive", 1), ("pay", -1)):
        lst = d[side]
        assert all(sign * r["z"] > 0 for r in lst) and [r["score"] for r in lst] == sorted((r["score"] for r in lst), reverse=True)
        for r in lst:
            assert abs(r["score"] - r["z"] * r["total_1m"] / r["sigma_1m"]) < 1e-9
    assert qx.PLANTED in [r["isin"] for r in d["receive"]] + [r["isin"] for r in d["rows"] if r["score"] is not None and r["score"] < 0]


def test_a_fit_signal_is_told_in_the_tenors_rate_and_a_bonds_yield_the_gap_beside_them(fitted):
    """The desk, 24.11.2026 ("6x9 net bir seviye değil mi, bps olarak yazdıklarını anlayamadım"): a fit's residual is
    told in the traded instrument's own level - the tenor's rate, the bond's yield (its own convention) -, target and
    stop the level where the residual is theirs on today's fit (fit + residual), the residual beside them; live."""
    ctx, eng, data, mons, tables, t, timing = fitted
    m = next(x for x in mons if x.sid == "curve:OIS:2Y")
    s = qf.make_signal(m, ctx.cfg, "10:00")
    q, row = s["quote"], {r["key"]: r for r in t["curve"]["rows"]}["OIS:2Y"]
    assert (q["inst"], q["unit"], q["label"]) == ("2Y OIS", "%", "2Y OIS %") and q["entry"] == pytest.approx(row["par"])
    assert q["base"] == pytest.approx(row["fit"]) and s["level"] == pytest.approx(row["resid"])
    for which in ("entry", "target", "stop"):
        assert (q[which] - q["base"]) * 100.0 == pytest.approx(s[which])
    assert {lg["key"]: lg["level"]["level"] for lg in s["legs"]} == {lg["key"]: pytest.approx(ctx.cur(lg["key"])) for lg in m.legs}
    assert "2Y OIS şimdi %%%s (%s bp NSS uyumunun üstünde)" % (qf._th(q["entry"], 3), qf._sg(s["level"], 1)) in s["plain"]
    assert "Hedef ve stop bugünkü NSS uyumuyla" in s["plain"] and "2Y OIS (%" in s["trade_tr"]
    # the bond: its yield in the fit's own convention, the model yield the base
    b = next(x for x in mons if x.sid == "dibsfv:" + qx.PLANTED)
    sb = qf.make_signal(b, ctx.cfg, "10:00")
    qb, rb = sb["quote"], {r["isin"]: r for r in t["dibsfv"]["rows"]}[qx.PLANTED]
    assert qb["entry"] == pytest.approx(rb["yield"]) and qb["base"] == pytest.approx(rb["model"]) and qb["note"].startswith("basit getiri")
    for which in ("entry", "target", "stop"):
        assert (qb[which] - qb["base"]) * 100.0 == pytest.approx(sb[which])
    assert sb["legs"][0]["level"]["level"] == pytest.approx(rb["yield"]) and "NS uyumunun üstünde" in sb["plain"]
    # live: a yield moves - the quote with it, the relation held
    live = {"DIBSS:" + qx.PLANTED: rb["yield"] + 0.05}
    b.score(ctx.derive_live(live), live)
    s2 = qf.make_signal(b, dict(ctx.cfg, entry_z=0.01), "10:01")
    q2 = s2["quote"]
    assert q2["entry"] == pytest.approx(rb["yield"] + 0.05) and (q2["entry"] - q2["base"]) * 100.0 == pytest.approx(s2["level"])
    qf.score_all(ctx, [b], ctx.live)                                      # (the module's monitors as they were)


def test_the_cross_section_z_is_over_the_fitted_bonds(fitted):
    """"Kesit z": every row's residual over the dispersion (sample standard deviation) of today's residuals of the bonds
    in the fit - the fixed-coupon ones -; the bills, priced on the curve and not fitted, are measured against it as any
    row.  The bills 150 bp rich now (as on the desk's list) leave the coupon bonds' Kesit z as it was - with the bills'
    residuals in, the dispersion would be several times wider -, theirs is their residual over the coupon bonds' one."""
    ctx, eng, data, mons, tables, t, timing = fitted
    bills = [b.isin for b in qx.bond_list(TODAY) if b.kind == "bill"]
    base = ctx.derive_live(ctx.live)
    rich = dict(base, **{"DIBSS:" + i: ctx.last("DIBS:" + i) - 1.5 for i in bills})
    before, after = ({r["isin"]: r for r in tables["dibsfv"]["build"](live)["rows"]} for live in (base, rich))
    for rows in (before, after):
        sd = statistics.stdev(r["resid"] for r in rows.values() if r["fitted"])
        assert all(r["cs_z"] == pytest.approx(r["resid"] / sd, rel=1e-12) for r in rows.values())     # every row, the bills too
    assert all(after[i]["resid"] < -140 and after[i]["cs_z"] < -5 for i in bills)
    assert statistics.stdev(r["resid"] for r in after.values()) > 3 * statistics.stdev(r["resid"] for r in after.values() if r["fitted"])
    assert all(after[i]["cs_z"] == pytest.approx(r["cs_z"], abs=1e-9) for i, r in before.items() if r["fitted"])


def test_the_bonds_trade_is_told_leg_by_leg_with_its_size(fitted):
    """The planted (cheap) bond's signal: the series its own NS distance ("NS farkı"), the trade every leg, sized for
    the main leg's 1.000 $ a bp - package 1 the bond and its two neighbours, neutral to the DİBS fit's level and slope;
    package 2 the bond against the two TRY OIS tenors around its maturity, linearly, DV01 1:1 (its asset swap, as
    DİBS RV!AJ hedges it)."""
    ctx, eng, data, mons, tables, t, timing = fitted
    m = next(x for x in mons if x.sid == "dibsfv:" + qx.PLANTED)
    s = qf.make_signal(m, ctx.cfg, "10:00")
    assert m.name.endswith(" · NS farkı") and "hedge" not in m.name and "hedge" not in s["expression"]
    p1, p2 = s["packages"]
    assert p1["legs"] is s["legs"] and p1["name"].startswith("Paket 1 · DİBS komşularıyla") and p2["name"].startswith("Paket 2 · kâğıt + OIS")
    assert s["expression"] == p1["trade"] == " · ".join("%s %s" % (l["action"], l["name"]) for l in s["legs"])
    main = s["legs"][0]
    assert [l["action"] for l in s["legs"]] == ["Buy", "Sell", "Sell"]                  # cheap: bought, its neighbours sold
    usd, tl = ctx.dv01_size()
    assert usd == 1000.0 and tl == pytest.approx(1000.0 * ctx.last("FX:USDTRY"))
    # the main leg: 1.000 $ a bp, its nominal by the desk's DV01 (DİBS RV!AI: −dP/dy of the simple yield, TL a bp a 1 mn)
    b = next(x for x in qx.bond_list(TODAY) if x.isin == qx.PLANTED)
    v = qc.next_weekday(TODAY)
    _, dp = b.price(ctx.last("DIBS:" + qx.PLANTED) / 100.0, v)
    assert main["dv01_usd"] == pytest.approx(usd) and main["dv01"] == pytest.approx(tl) and main["notional"] == pytest.approx(tl / -dp, rel=1e-9)
    # package 1 neutral to the DİBS fit's level and slope: Σ side × nominal × ∂(model price)/∂β ≈ 0
    pr = t["dibsfv"]["params"]
    curve = qc.Nss([pr["b0"] / 100, pr["b1"] / 100, pr["b2"] / 100], pr["tau1"], pr["tau1"], qc.NS)
    bonds = {x.isin: x for x in qx.bond_list(TODAY)}

    def price(isin, c):
        flows, _ = bonds[isin].flows(v)
        return sum(cf * c.df((d - v).days / 365.0) for d, cf in flows)

    for j in (0, 1):
        up, dn = list(curve.beta), list(curve.beta)
        up[j] += 1e-6
        dn[j] -= 1e-6
        cu, cd = qc.Nss(up, curve.tau1, curve.tau2), qc.Nss(dn, curve.tau1, curve.tau2)
        moves = [l["side"] * l["notional"] * (price(l["key"][5:], cu) - price(l["key"][5:], cd)) for l in p1["legs"]]
        assert abs(sum(moves)) < 1e-6 * abs(moves[0]), (j, moves)
    # package 2: the bond and the two OIS tenors around its maturity, paid (the bond bought), linearly by it
    years = (b.maturity - v).days / 365.0
    ois = p2["legs"][1:]
    assert p2["legs"][0] == main and [l["action"] for l in ois] == ["Pay", "Pay"] and len(ois) == 2
    m1, m2 = (OIS_MONTHS[l["key"]] / 12.0 for l in ois)
    assert m1 <= years <= m2 and sum(l["dv01_usd"] for l in ois) == pytest.approx(usd)
    assert ois[1]["dv01_usd"] == pytest.approx(usd * (years - m1) / (m2 - m1)) and ois[1]["dv01"] == pytest.approx(ois[1]["dv01_usd"] * tl / usd)
    for l in ois:
        ann = qf._annuity(ctx.cur(l["key"]), OIS_MONTHS[l["key"]])
        assert l["notional"] == pytest.approx(l["dv01"] / (ann * 1e-4) / 1e6, rel=1e-12)
    assert "asset swap" in p2["name"] and "DİBS − OIS" in p2["note"] and p2["trade"] == " · ".join("%s %s" % (l["action"], l["name"]) for l in p2["legs"])
    # (no carry engine here: package 2's carry and expected P&L are not made up)
    assert p2["carry_week"] is None and p2["exp_pnl"] is None and p1["carry_week"] is not None


def test_the_ois_side_of_a_bond_is_the_two_tenors_around_its_maturity():
    tenors = [("OIS:1Y", 1.0), ("OIS:2Y", 2.0), ("OIS:5Y", 5.0)]
    assert qc.ois_hedge(2.75, tenors)["legs"] == [("OIS:2Y", pytest.approx(-0.75)), ("OIS:5Y", pytest.approx(-0.25))]
    assert qc.ois_hedge(2.0, tenors)["legs"] == [("OIS:2Y", -1.0)]
    assert qc.ois_hedge(0.4, tenors)["legs"] == [("OIS:1Y", -1.0)] and qc.ois_hedge(7.5, tenors)["legs"] == [("OIS:5Y", -1.0)]
    assert qc.ois_hedge(3.0, []) is None


def test_a_live_yield_moves_the_bonds_residual_and_its_z():
    ctx, eng, data = synth_ctx()
    mons, tables, t, _ = run(ctx, eng)
    planted = next(r for r in t["dibsfv"]["rows"] if r["isin"] == qx.PLANTED)
    m = next(x for x in mons if x.sid == "dibsfv:" + qx.PLANTED)
    fair = planted["yield"] - planted["resid"] / 100.0                     # back onto the curve now
    live = {"DIBSS:" + qx.PLANTED: fair}
    m.score(ctx.derive_live(live), live)
    # (the curve moves a little with it: the Huber fit had it at a reduced weight, now at a full one)
    assert abs(m.level) < 4.0 and abs(m.z) < 1.0 and m.live


def test_bonds_whose_history_is_compounded_read_as_compounded():
    ctx, eng, data = synth_ctx(conv="compound")
    for row in eng["dibs"]:                                                 # the sheet's yields today, near the history's
        last = ctx.last("DIBS:" + row["isin"])
        row["compound"], row["simple"] = last / 100.0, (2 * ((1 + last / 100.0) ** 0.5 - 1))
    mons, tables, t, _ = run(ctx, eng)
    d = t["dibsfv"]
    assert d["ok"] and {r["conv"] for r in d["rows"]} == {"compound"}
    planted = next(r for r in d["rows"] if r["isin"] == qx.PLANTED)
    assert planted["z"] > DEFAULTS["entry_z"]


# ================================================================================================ quotes from the fair curve
def test_a_bond_off_a_known_curve_quotes_fair_plus_minus_the_half_spread():
    b = qc.Bond("TRT150328T24", "15.03.28", "fixed", dt.date(2028, 3, 15), 36.8, 2)
    v = dt.date(2026, 11, 4)
    assert abs(qc.accrued(b, v) - 18.4 * 49 / 182) < 1e-12                    # DİBS RV!Q8: 4,9538…
    q = qc.quote_bond(b, v, TRUE, 12.5)
    flows, _ = b.flows(v)
    fair_dirty = sum(cf * TRUE.df((d - v).days / 365.0) for d, cf in flows)
    y = b.yield_of(fair_dirty, v)
    assert abs(q["fair"]["dirty"] - fair_dirty) < 1e-9 and abs(q["fair"]["yield"] - y * 100) < 1e-10
    assert abs(q["bid"]["yield"] - (q["fair"]["yield"] + 0.125)) < 1e-12 and abs(q["ask"]["yield"] - (q["fair"]["yield"] - 0.125)) < 1e-12
    for side, yy in (("bid", y + 0.00125), ("ask", y - 0.00125), ("fair", y)):
        p, dp = b.price(yy, v)
        assert abs(q[side]["dirty"] - p) < 1e-12 and abs(q[side]["clean"] - (p - q["accrued"])) < 1e-12 and abs(q[side]["dv01"] + dp) < 1e-12
        assert abs(q[side]["compound"] - ((1 + yy / 2) ** 2 - 1) * 100) < 1e-10
    assert q["bid"]["clean"] < q["fair"]["clean"] < q["ask"]["clean"]          # the desk buys lower, sells higher
    # the desk's half spreads by the bond's years to maturity
    s = dict(qc.QUOTE_DEFAULTS)
    assert qc.spread_for(1.0, s) == ("kısa", 10.0) and qc.spread_for(3.0, s) == ("orta", 15.0) and qc.spread_for(8.0, s) == ("uzun", 20.0)


def test_quote_spreads_are_the_desks_and_checked():
    from tto.store import Store
    import tempfile
    import os
    store = Store(os.path.join(tempfile.mkdtemp(), "q.db"))
    try:
        out = qc.set_quote_spreads(store, "ayse", {"short": "7,5", "long_from": 6})
        assert out["short"] == 7.5 and out["long_from"] == 6.0 and out["mid"] == 15.0 and out["by"] == "ayse"
        for bad in ({"short": "x"}, {"mid": -1}, {"short_until": 7}, {"long": 900}):
            with pytest.raises(ValueError):
                qc.set_quote_spreads(store, "ayse", bad)
        assert qc.quote_spreads(store)["short"] == 7.5
    finally:
        store.close()


def test_quote_and_switch_on_the_fitted_curve(fitted):
    ctx, eng, data, mons, tables, t, timing = fitted
    live = ctx.derive_live(ctx.live)
    spreads = dict(qc.QUOTE_DEFAULTS)
    rows = {r["isin"]: r for r in t["dibsfv"]["rows"]}
    q = tables["dibsfv"]["quote"](qx.PLANTED, live, spreads)
    assert q["ok"] and q["listed"] and q["bucket"] == "orta" and q["half_bp"] == 15.0
    # the market against fair: the bond's rich / cheap (exact yields here, the first-order residual on the table)
    assert abs(q["distance"] - rows[qx.PLANTED]["resid"]) < 0.5 and abs(q["z"] - rows[qx.PLANTED]["z"]) < 1e-9
    assert abs(q["market"]["yield"] - rows[qx.PLANTED]["yield"]) < 1e-9 and q["total_1m"] == rows[qx.PLANTED]["total_1m"]
    assert q["line"].startswith("DİBS ") and qx.PLANTED in q["line"] and "getiri " in q["line"] and " / " in q["line"]
    assert not tables["dibsfv"]["quote"]("TRB000001T11", live, spreads)["ok"]       # a bill: not a fixed-coupon bond
    assert not tables["dibsfv"]["quote"]("XS0000000000", live, spreads)["ok"]
    # sell A, buy B: the nominal that keeps the DV01, the pickup against the curve, the carry difference, the z
    a, b = "TRT000005T11", qx.PLANTED
    sw = tables["dibsfv"]["switch"](a, b, live, spreads)
    assert sw["ok"]
    dv_a, dv_b = sw["a"]["market"]["dv01"], sw["b"]["market"]["dv01"]
    assert abs(1.0 * dv_a - sw["ratio"] * dv_b) < 1e-9 and abs(sw["dv01_mn"] - dv_a) < 1e-12        # DV01-neutral
    assert abs(sw["pickup"] - (sw["b"]["distance"] - sw["a"]["distance"])) < 1e-9 and sw["pickup"] > 15
    assert abs(sw["cr_1m"] - (sw["b"]["total_1m"] - sw["a"]["total_1m"])) < 1e-9
    assert sw["n"] >= ctx.window() - 5 and sw["z"] > 2.0                   # the planted bond cheapens the switch to it
    assert sw["line"].startswith("Switch: ") and "DV01 nötr" in sw["line"] and "daha ucuz (lehte)" in sw["line"]
    back = tables["dibsfv"]["switch"](b, a, live, spreads)
    assert abs(back["pickup"] + sw["pickup"]) < 1e-9 and abs(back["ratio"] * sw["ratio"] - 1) < 1e-12 and "aleyhte" in back["line"]
    assert not tables["dibsfv"]["switch"](a, a, live, spreads)["ok"]


# ================================================================================================ the service and the API
@pytest.fixture(scope="module")
def seeded(module_service):
    """The replay service with a two-year synthetic history: the package's (quant_synth), the DİBS RV list's bonds
    priced off a moving NSS curve (one planted cheap) and the options' quotes (one planted risk reversal)."""
    svc = module_service
    svc.quant.use_live = False
    quant_synth.seed(svc)
    eng = svc.quant._engine_read(True)
    bonds = [b for b in (qc._bond_of(r["isin"], {}, r) for r in eng["dibs"]) if b is not None and b.maturity > svc.history.today()]
    today = svc.history.snapshot()["today"]
    fixed = sorted((b for b in bonds if b.kind == "fixed"), key=lambda b: b.maturity)
    planted = fixed[len(fixed) // 2].isin                                   # mid-curve (an end of the fit leans on the curve more)
    _, ys, _ = qx.bond_yields(today, bonds=bonds, planted=planted, beta0=(0.20, 0.05, -0.04, 0.02))
    _, quotes = qx.option_quotes(today)
    snap = svc.history.snapshot()
    from tto.quant import Quant
    defs = {Quant._key_of(d): d for d in snap["defs"]}
    spot = svc.store.hist_many([defs["FX:EURUSD"].id], "2000-01-01", today.isoformat())[defs["FX:EURUSD"].id]
    pts = qx.forward_points(spot, 2.0)
    data = dict(quotes)
    data.update({"DIBS:" + isin: v for isin, v in ys.items()})
    data.update({"FXP:EURUSD:" + t: v for t, v in pts.items()})
    for k, points in data.items():
        d = defs.get(k)
        assert d is not None, k
        for sid in d.ids():
            svc.store.hist_delete(sid)
        svc.store.hist_upsert(d.id, sorted(points.items()))
    svc.history.rev += 1
    svc.quant._planted_bond = planted
    return svc


def test_the_dibs_rv_sheet_is_read_for_the_fixed_coupon_bonds_and_bills(seeded):
    eng = seeded.quant._engine_read(False)
    rows = eng["dibs"]
    assert rows and {r["type"] for r in rows} <= {"S", "B"} and any(r["type"] == "S" for r in rows) and any(r["type"] == "B" for r in rows)
    fixed = next(r for r in rows if r["isin"] == "TRT150328T24")
    assert fixed["coupon"] == 36.8 and fixed["freq"] == 2.0 and fixed["maturity"] == "2028-03-15" and fixed["source"] == "ISL1"
    assert abs(fixed["simple"] - 0.3639184043698062) < 1e-9 and fixed["compound"] > fixed["simple"] and fixed["dv01"] > 0
    assert not any(r["isin"] == "TRT090130T12" for r in rows)              # a TLREF floater stays out
    live = qc.live_values(eng)
    assert abs(live["DIBSS:TRT150328T24"] - 36.39184043698062) < 1e-7
    # the desk's DV01 of every row is the sheet's own (DİBS RV!AI: modified duration × dirty price, of the simple yield)
    for r in rows:
        b = qc._bond_of(r["isin"], {}, r)
        if b is not None and r["dirty"] is not None and r["dv01"] is not None:
            assert qc.desk_dv01(b, dt.date.fromisoformat(r["value_date"]), r["dirty"], r["simple"]) == pytest.approx(r["dv01"], rel=1e-9), r["isin"]
    # what a package's size is made of, as the blotter sizes a trade: USDTRY of OIS_MAIN!D2, Motor's annuities
    full = seeded.quant._engine_read(True)["desk"]
    market = seeded.ois_market(None)
    assert full["usdtry"] == pytest.approx(market["usdtry"]) and full["usdtry"] > 10
    ann = {r["tenor"]: r["annuity"] for r in market["tenors"] if r["annuity"]}
    assert set(full["ois_annuity"]) == set(ann) - {"ON", "1W", "2W"} and all(full["ois_annuity"][k] == ann[k] for k in full["ois_annuity"])


def test_both_pages_from_the_service(seeded):
    svc = seeded
    st = svc.quant.compute()
    assert st["ready"] and not st["errors"], st["errors"]
    assert {"curve", "dibsfv", "opt"} <= set(st["timing"])
    user = svc.login("eğri okuyucu")["user"]
    v = svc.quant.view("signals", user, {})
    fams = {f["id"]: f for f in v["families"]}
    assert {"curve", "dibsfv", "opt"} <= set(fams) and fams["opt"]["page"] == "quant-opt" and fams["curve"]["label"] == "Eğri adil değeri"
    ids = {s["id"]: s for s in v["signals"] + v["gated"]}
    assert ids["opt:USDTRY:RR25:1M"]["expression"] == "Sell USDTRY 1M 25D RR"
    assert ids["dibsfv:" + svc.quant._planted_bond]["expression"].startswith("Buy ")
    # the planted bond's two packages sized as the desk's trades are: 1.000 $ a bp at OIS_MAIN!D2, the OIS legs by
    # Motor's annuities (the blotter's), the OIS DV01 the bond's
    sg = ids["dibsfv:" + svc.quant._planted_bond]
    p1, p2 = sg["packages"]
    market = svc.ois_market(None)
    ann = {r["tenor"]: r["annuity"] for r in market["tenors"] if r["annuity"]}
    assert sg["legs"][0]["dv01_usd"] == pytest.approx(1000.0) and sg["legs"][0]["dv01"] == pytest.approx(1000.0 * market["usdtry"])
    assert all(l["notional"] > 0 for l in p1["legs"] + p2["legs"]) and [l["action"] for l in p2["legs"][1:]] == ["Pay"] * (len(p2["legs"]) - 1)
    assert sum(l["dv01_usd"] for l in p2["legs"][1:]) == pytest.approx(1000.0)
    for l in p2["legs"][1:]:
        assert l["notional"] == pytest.approx(l["dv01"] / (ann[l["key"][4:]] * 1e-4) / 1e6, rel=1e-12)
    curve = svc.quant.view("curve", user, {})
    assert curve["curve"]["ok"] and curve["dibsfv"]["ok"] and curve["curve"]["n"] >= 12 and curve["dibsfv"]["n"] >= 8
    assert all(s["page"] == "quant-curve" for s in curve["signals"]) and curve["coverage"]
    assert all(c["key"].startswith("OIS:") or c["key"] == "TLREF" for c in curve["coverage"])
    opt = svc.quant.view("opt", user, {})
    pairs = {p["pair"]: p for p in opt["opt"]["pairs"]}
    assert set(pairs) == {"USDTRY", "EURUSD"}
    for p in pairs.values():
        assert [r["tenor"] for r in p["surface"]] == ["1W", "1M", "3M", "6M", "1Y"]
        for s in p["smiles"]:
            assert s["model"] == "svi" and not s["arbitrage"] and len(s["probs"]) == 3 and all(x["up"] is not None for x in s["probs"])
            assert s["realized"]["n"] > 300
    assert pairs["EURUSD"]["smiles"][0]["delta"] == "spot" and pairs["USDTRY"]["smiles"][0]["delta"] == "forward"
    assert any(c["key"].startswith("OPT:") for c in opt["coverage"]) and all(qo.covers(c["key"]) for c in opt["coverage"])
    one = svc.quant.view("signal", user, {"id": "opt:USDTRY:RR25:1M"})
    assert len(one["history"]["days"]) >= DEFAULTS["min_obs"]
    t0 = svc.quant.state["refreshes"]
    svc.quant.refresh_live()
    assert svc.quant.state["refreshes"] == t0 + 1 and svc.quant.state["live_ms"] < 3000


def test_both_pages_over_http(seeded):
    svc = seeded
    if not svc.quant.status()["ready"]:
        svc.quant.compute()
    with TestClient(create_app(svc), headers=auth(svc, "Eğri HTTP")) as client:
        for what in ("curve", "opt"):
            r = client.get("/api/quant/" + what)
            assert r.status_code == 200 and r.json()["ready"], what
        body = client.get("/api/quant/curve").json()
        assert body["curve"]["rows"] and "build" not in body["curve"] and body["dibsfv"]["rows"]
        assert client.get("/api/quant/opt").json()["opt"]["pairs"]
        nav = client.get("/api/nav").json()["pages"]
        quant = [p["id"] for p in nav if p["group"] == "Quant"]
        # (in the menu's order: Eğri Adil Değeri on Faiz's tabs after Rejim, Opsiyon on FX's after Makro)
        assert quant.index("quant-curve") == quant.index("quant-regime") + 1 and quant.index("quant-opt") == quant.index("quant-macro") + 1
        assert len(quant) == 20                                         # (Trend, Carry + momentum, Makine öğrenmesi: tabs of Sinyaller; Opsiyon → spot: of FX; DİBS switch: of Faiz)
        assert quant.index("quant-dibssw") == quant.index("quant-curve") + 1
        assert client.get("/static/js/pages/quantfit.js").status_code == 200
        # the quote and the switch from the fair curve, the desk's half spreads
        fixed = [r["isin"] for r in body["dibsfv"]["rows"] if r["kind"] == "fixed"]
        q = client.get("/api/quant/quote", params={"isin": fixed[0]}).json()
        assert q["ok"] and q["bid"]["yield"] > q["fair"]["yield"] > q["ask"]["yield"] and q["line"]
        assert not client.get("/api/quant/quote", params={"isin": "yok"}).json()["ok"]
        sw = client.get("/api/quant/switch", params={"a": fixed[0], "b": fixed[-1]}).json()
        assert sw["ok"] and sw["ratio"] > 0 and sw["line"]
        assert client.get("/api/quant/quote_spreads").json()["values"]["mid"] == 15.0
        res = client.post("/api/quant/quote_spreads", json={"values": {"mid": "12,5"}})
        assert res.status_code == 200 and res.json()["mid"] == 12.5
        assert client.post("/api/quant/quote_spreads", json={"values": {"mid": "-3"}}).status_code == 400
        client.post("/api/quant/quote_spreads", json={"values": {"mid": 15}})
