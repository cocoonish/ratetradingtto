"""Fiyatlama (18.11.2026; the desk: "Kırık vade fiyatlamayı da açalım. Bir fiyatlama sekmesi olsun, buradan asseti ve
vadeyi seçtiğimde fiyat, DV01'lar bucket bucket olarak, fiyat girdiğimde de NPV'yi vermeli."): ``tto/pricing.py`` on its
own - the calendar, what is typed, the coupons counted back from the maturity (an XCCY's short period first: "18 ayda 6
ay + 12 ay ... sondan başlayıp"), Motor's bootstrap and the offshore curve built again, the PPK calibration with one quote
bumped, values and their signs - and on the replay day: the curves built again are the sheet's to the last digit and
Motor's own bucket bumps (``Motor!T86``); every asset at MASA's broken-date block's own date is the block's number on
both curves (its own date and a broken one); OIS · PPK's FRA list and the quotes come back; PPK equals Bootstrap at a
quoted maturity of a zero coupon instrument; the DV01 buckets sum to the total and to a parallel bump, a bucket away from
the maturity is 0; NPV 0 at mid, + in the trader's favour; the page's inputs each user's own, per asset; the HTTP route."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell
from test_ppkcurve import synthetic
from tto import ppkcurve as pk
from tto import pricing as pr
from tto.server import create_app
from tto.xl.values import date_to_serial, serial_to_date

SPOT = date_to_serial(dt.date(2026, 11, 4))          # a Wednesday
NONE = frozenset()


def day(text: str) -> float:
    return date_to_serial(dt.date.fromisoformat(text))


# ================================================================================================== the module
def test_the_calendar():
    sat = day("2026-11-07")
    assert pr.roll(sat, NONE) == day("2026-11-09") and pr.roll(day("2026-11-09"), NONE) == day("2026-11-09")
    assert pr.roll(sat, frozenset([day("2026-11-09")])) == day("2026-11-10")              # a holiday on the Monday
    assert pr.edate(day("2027-01-31"), 1) == day("2027-02-28") and pr.edate(day("2028-01-31"), 1) == day("2028-02-29")
    assert pr.tenor_date(SPOT, 27, NONE) == day("2029-02-05")                              # 04.02.2029 is a Sunday
    assert [pr.is_business(SPOT + k, NONE) for k in range(7)] == [True, True, True, False, False, True, True]


def test_what_is_typed():
    w = pr.parse_when
    assert w("") == w("Spot") == w(" spot ") == w("0") == ("spot", 0.0)
    assert (w("1Y"), w("18M"), w("2Y3M"), w("2y 3m"), w("3A"), w("1 yıl 6 ay"), w("12"), w(15)) == (
        ("m", 12.0), ("m", 18.0), ("m", 27.0), ("m", 27.0), ("m", 3.0), ("m", 18.0), ("m", 12.0), ("m", 15.0))
    assert w("2W") == w("2h") == ("w", 2.0) and w("04.05.2028") == ("d", day("2028-05-04"))
    assert w("abc") is None and w("1Q") is None and w("0M") is None
    assert pr.split_pair("12x15") == ("12", "15") and pr.split_pair("1Y × 15M") == ("1Y", "15M") and pr.split_pair("12") is None
    assert [pr.when_label(("m", m)) for m in (9, 12, 15, 18, 24, 27, 30, 36)] == ["9M", "1Y", "15M", "18M", "2Y", "2Y3M", "2Y6M", "3Y"]
    assert pr.when_label(("d", day("2028-05-04"))) == "04.05.2028" and pr.when_label(("spot", 0.0)) == "Spot"
    # a user's inputs: what was typed over what was kept over the defaults, per asset; an FRA typed in one box is two
    kept = pr.clean_inputs({"asset": "xccy", "end": "18M", "side": "PAY"})
    assert kept["asset"] == "xccy" and kept["by"]["xccy"]["end"] == "18M" and kept["by"]["xccy"]["side"] == "PAY"
    nxt = pr.clean_inputs({"asset": "fra", "start": "12x15", "side": "AL"}, kept)
    assert nxt["by"]["fra"]["start"] == "12" and nxt["by"]["fra"]["end"] == "15" and nxt["by"]["fra"]["side"] == "PAY"
    assert nxt["by"]["xccy"]["end"] == "18M" and pr.clean_inputs(None, nxt) == nxt                  # (the XCCY kept)
    assert pr.clean_inputs({"asset": "fx", "pair": "eurtry", "price_kind": "points"})["by"]["fx"]["pair"] == "EURTRY"


def test_coupons_are_counted_back_from_the_maturity_the_short_period_first():
    """The desk: "18 ayda 6 ay + 12 ay olarak kupon ödemesi yapılıyor, sondan başlayıp" - an XCCY's annual coupons from
    the maturity back, the short period first (MASA's helper too); OIS quarterly, up to 3M one payment."""
    def periods(end, step, start=SPOT):
        pays = pr.coupons(start, end, SPOT, step, NONE)
        return [(serial_to_date(a).isoformat(), serial_to_date(b).isoformat()) for a, b in zip([start] + pays[:-1], pays)]

    assert periods(("m", 18), 12) == [("2026-11-04", "2027-05-04"), ("2027-05-04", "2028-05-04")]            # 6M + 12M
    assert periods(("m", 27), 12) == [("2026-11-04", "2027-02-04"), ("2027-02-04", "2028-02-04"),          # 3M + 12M + 12M
                                      ("2028-02-04", "2029-02-05")]
    assert periods(("m", 12), 12) == [("2026-11-04", "2027-11-04")]
    assert periods(("m", 4), 3) == [("2026-11-04", "2026-12-04"), ("2026-12-04", "2027-03-04")]              # 1M + 3M
    assert len(periods(("m", 3), 3)) == 1 and len(periods(("w", 2), 3)) == 1 and len(periods(("m", 12), 3)) == 4
    # a date: so many months back from it (MASA's helper: WORKDAY(EDATE(T, −3k) − 1, 1)), the first period short
    assert periods(("d", day("2027-08-20")), 3) == [("2026-11-04", "2026-11-20"), ("2026-11-20", "2027-02-22"),
                                                    ("2027-02-22", "2027-05-20"), ("2027-05-20", "2027-08-20")]
    # a forward start: only what pays after it - an FRA 12x15 one period, 12x18 two quarters
    start = pr.tenor_date(SPOT, 12, NONE)
    assert periods(("m", 15), 3, start) == [("2027-11-04", "2028-02-04")] and len(periods(("m", 18), 3, start)) == 2


def test_motor_s_bootstrap_built_again_reprices_every_node():
    quotes = [(1, 0.36), (2, 0.362), (3, 0.365), (6, 0.36), (9, 0.355), (12, 0.35), (18, 0.352), (24, 0.355)]
    nodes = [(0, 0.0)] + [(m, float(pr.tenor_date(SPOT, m, NONE) - SPOT)) for m in (1, 2, 3) + tuple(range(6, 25, 3))]
    c = pr.motor_curve(quotes, nodes)
    rate, days = dict(quotes), dict(nodes)
    for m in (1, 2, 3):
        assert (1.0 / c.df(days[m]) - 1.0) * 365.0 / days[m] == pytest.approx(rate[m], abs=1e-14)   # one period ACT/365
    for m in (6, 9, 12, 18, 24):                       # quarterly from the 3M node: the swap's par is the quote
        pays = [days[k] for k in range(3, m + 1, 3)]
        acc = [(b - a) / 365.0 for a, b in zip([0.0] + pays[:-1], pays)]
        assert pk.par(c, pays, acc) == pytest.approx(rate[m], abs=1e-14)
    # 15M and 21M: their par the quotes linear in months (Motor's F89:F130)
    pays = [days[k] for k in range(3, 16, 3)]
    assert pk.par(c, pays, [(b - a) / 365.0 for a, b in zip([0.0] + pays[:-1], pays)]) == pytest.approx(0.351, abs=1e-14)
    # a quote bumped (Motor's bucket bump): the nodes before the previous quote stay as they are
    up = pr.motor_curve([(m, r + (1e-4 if m == 12 else 0.0)) for m, r in quotes], nodes)
    assert all(up.ln(days[m]) == c.ln(days[m]) for m in (1, 2, 3, 6, 9)) and up.ln(days[12]) < c.ln(days[12])


def test_the_offshore_curve_built_again_reprices_its_quotes():
    off = pk.offshore_quotes([("1W", 8.0, 30.8), ("1M", 30.0, 33.0), ("3M", 92.0, 34.3), ("9M", 273.0, 37.5)],
                             [("1Y", 365.0, 39.4), ("2Y", 731.0, 41.6), ("3Y", 1096.0, 41.2)])
    c = pr.quote_curve(off)
    assert c.days == [0.0, 8.0, 30.0, 92.0, 273.0, 365.0, 731.0, 1096.0]
    for q in off:
        assert pk.par(c, q.pays, q.accruals) == pytest.approx(q.rate, abs=1e-14)


def test_one_quote_bumped_on_ppk_is_the_calibration_of_the_bumped_quotes():
    _, shape, _, _, quotes = synthetic()
    base, _ = pk.calibrate(shape, quotes)
    qs = sorted(quotes, key=lambda q: q.end)
    slope = pr.slopes(shape, qs, base)
    for j in range(len(qs)):
        warm = pr.recalibrated(shape, qs, base, j, slope=slope)
        cold, _ = pk.calibrate(shape, qs[:j] + [qs[j]._replace(rate=qs[j].rate + 1e-4)] + qs[j + 1:])
        assert warm.shifts[:j] == base.shifts[:j]                   # the stretches before the bumped quote: as they were
        for k, q in enumerate(qs):
            assert pk.par(warm, q.pays, q.accruals) == pytest.approx(q.rate + (1e-4 if k == j else 0.0), abs=1e-12)
        assert max(abs(warm.lng(float(t)) - cold.lng(float(t))) for t in range(0, 760, 3)) < 1e-10
        # a maturity before the bumped quote's stretch does not see it at all
        if j >= 2:
            t = qs[j - 2].end
            assert warm.lng(t) == base.lng(t)


def synthetic_market(**kw) -> pr.Market:
    hol = {"TRY": NONE, "USDTRY": NONE, "EURTRY": NONE}
    out = dict(ois_spot=SPOT, fx_spot=SPOT, eur_spot=SPOT + 1.0, holidays=hol, ois_quotes=(), nodes=(), usdtry=50.0,
               lot=5e6, spots={"USDTRY": 50.0, "EURTRY": 56.0},
               ccy_rates={"USD": ((7.0, 4.0), (365.0, 4.2), (3653.0, 4.5)), "EUR": ((7.0, 2.4), (3653.0, 3.2))})
    out.update(kw)
    return pr.Market(**out)


def test_values_dv01_signs_and_sizing_on_a_small_curve():
    mk = synthetic_market()
    curve = pk.LogLinear([0.0, 365.0, 730.0, 1095.0], [0.0, -0.33, -0.66, -0.97])
    up = pk.LogLinear([0.0, 365.0, 730.0, 1095.0], [0.0, -0.3301, -0.6602, -0.9703])     # rates a little higher
    assert pr.ccy_rate(1.0, mk.ccy_rates["USD"]) == 0.04 and pr.ccy_rate(5000.0, mk.ccy_rates["USD"]) == 0.045
    assert pr.ccy_rate(186.0, mk.ccy_rates["USD"]) == pytest.approx(0.041, abs=1e-15)
    for asset in (pr.OIS, pr.XCCY):
        deal = pr.swap_deal(asset, ("spot", 0.0), ("m", 27.0), mk)
        m = pr.mid(deal, curve)
        assert pr.value(deal, curve, 1, 1e8, m) == pytest.approx(0.0, abs=1e-6)                 # NPV 0 at mid
        assert pr.value(deal, curve, 1, 1e8, m - 0.001) > 0 > pr.value(deal, curve, -1, 1e8, m - 0.001)   # PAY under mid: +
        assert pr.value(deal, curve, 1, 1e8, m - 0.001) == pytest.approx(1e8 * 0.001 * pr.annuity(deal, curve), rel=1e-12)
        assert pr.value(deal, up, 1, 1e8, m) > 0 > pr.value(deal, up, -1, 1e8, m)            # payer + when rates rise
    fwd = pr.fx_deal("USDTRY", ("m", 18.0), mk)
    f = pr.forward(fwd, curve)
    g = 1.0 + pr.ccy_rate(fwd.end - fwd.start, mk.ccy_rates["USD"]) * (fwd.end - fwd.start) / 360.0
    assert f == pytest.approx(50.0 / curve.df(fwd.end - SPOT) / g, rel=1e-14)
    assert pr.value(fwd, curve, 1, 1e7, f) == 0.0 and pr.value(fwd, curve, 1, 1e7, f - 0.1) > 0     # bought under the mid: +
    assert pr.value(fwd, up, 1, 1e7, f) > 0                                                       # USD bought: + when TRY rates rise
    eur = pr.fx_deal("EURTRY", ("m", 18.0), mk)
    assert eur.start == SPOT + 1.0 and pr.forward(eur, curve) == pytest.approx(
        56.0 * curve.df(1.0) / curve.df(eur.end - SPOT) / (1.0 + pr.ccy_rate(eur.end - eur.start, mk.ccy_rates["EUR"]) * (eur.end - eur.start) / 360.0), rel=1e-14)
    with pytest.raises(pr.PricingError):
        pr.swap_deal(pr.FRA, ("spot", 0.0), ("m", 15.0), mk)                                   # an FRA starts later
    with pytest.raises(pr.PricingError):
        pr.swap_deal(pr.OIS, ("m", 15.0), ("m", 12.0), mk)
    with pytest.raises(pr.PricingError):
        pr.swap_deal(pr.OIS, ("d", SPOT - 3.0), ("m", 12.0), mk)                               # before the spot


# ---------------------------------------------------------------- the ways back (the desk, 24.11.2026: "…-4-…", item 4)
def test_an_npv_or_an_upfront_gives_the_level_that_prices_back_to_it():
    """"Type an NPV (TL or $) or an upfront in bp and get the fixed rate": ``level_for`` is ``value``'s exact inverse -
    value(level_for(v)) = v to 1e-9 and level_for(value(K)) = K - for swaps (spot, forward start, a date) and an FX
    forward, both sides, small and large; an NPV in $ is TL at USDTRY, an upfront bp of the nominal, + in the trader's
    favour as the NPV (a payer's + upfront is a rate under the mid, a receiver's over it)."""
    mk = synthetic_market()
    curve = pk.LogLinear([0.0, 365.0, 730.0, 1095.0], [0.0, -0.33, -0.66, -0.97])
    deals = [pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", 27.0), mk), pr.swap_deal(pr.FRA, ("m", 12.0), ("m", 15.0), mk),
             pr.swap_deal(pr.XCCY, ("spot", 0.0), ("d", SPOT + 500.0), mk), pr.fx_deal("USDTRY", ("m", 18.0), mk),
             pr.fx_deal("EURTRY", ("d", SPOT + 200.0), mk)]
    for deal in deals:
        m = pr.mid(deal, curve)
        for side in (1, -1):
            for size in (1e6, 1e8, 3.7e9):
                for v in (1e6, -250e3, 12345.678, -3e7):
                    k = pr.level_for(deal, curve, side, size, v)
                    assert pr.value(deal, curve, side, size, k) == pytest.approx(v, rel=1e-9), (deal.label, side, size, v)
                k0 = m - side * (0.25 if deal.asset == pr.FX else 0.0012)
                assert pr.level_for(deal, curve, side, size, pr.value(deal, curve, side, size, k0)) == pytest.approx(k0, rel=1e-12)
            assert pr.level_for(deal, curve, side, 1e8, 0.0) == pytest.approx(m, rel=1e-14)          # NPV 0: the mid
    assert pr.npv_of("npv_usd", 2e4, 1e8, 50.0) == 1e6 and pr.npv_of("upfront", 25.0, 1e8, 50.0) == 250000.0
    assert pr.npv_of("npv_tl", -3.0, 1e8, 50.0) == -3.0
    ois = deals[0]
    paid = pr.level_for(ois, curve, 1, 1e8, pr.npv_of("upfront", 25.0, 1e8, 50.0))
    assert paid < pr.mid(ois, curve) < pr.level_for(ois, curve, -1, 1e8, 250000.0)
    assert (pr.mid(ois, curve) - paid) * pr.annuity(ois, curve) * 1e4 == pytest.approx(25.0, abs=1e-9)


def test_the_price_box_holds_each_asset_s_kinds_and_kept_inputs_read_as_before():
    mk = synthetic_market()
    deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", 24.0), mk)
    fx = pr.fx_deal("USDTRY", ("m", 12.0), mk)
    rp = pr.read_price
    assert rp("rate", "35,10", deal) == pytest.approx(0.351, abs=1e-15) and rp("rate", "%35,10", deal) == pytest.approx(0.351, abs=1e-15)
    assert rp("npv_tl", "1.000.000", deal) == 1e6 and rp("npv_tl", "-250k", deal) == -250e3 and rp("npv_tl", "−250k", deal) == -250e3
    assert rp("npv_usd", "2,5m", deal) == 2.5e6 and rp("upfront", "25", deal) == 25.0 and rp("upfront", "-12,5", deal) == -12.5
    assert rp("upfront", "%0,5", deal) == pytest.approx(50.0, abs=1e-12)                    # (0,5 % of the nominal: 50 bp)
    assert rp("outright", "79,05", fx) == 79.05 and rp("points", "100", fx) == pytest.approx(50.01, abs=1e-12)
    assert rp("npv_tl", "1m", fx) == 1e6 and rp("rate", "", deal) is None and rp("npv_tl", "  ", deal) is None
    for kind, text, why in (("npv_tl", "abc", "NPV okunamadı"), ("upfront", "x", "peşin okunamadı"), ("rate", "?", "fiyat okunamadı"),
                            ("outright", "-1", "forward kur pozitif")):
        with pytest.raises(pr.PricingError, match=why):
            rp(kind, text, fx if kind == "outright" else deal)
    # the kinds per asset; inputs kept before 24.11.2026 (no kind, no Toplu box) read as they did: a rate, an FX
    # forward's own kind
    old = {"asset": "ois", "by": {"ois": {"start": "", "end": "2Y", "side": "PAY", "size_kind": "dv01", "size": "1000", "price": "35"},
                                  "fx": {"end": "1Y", "side": "AL", "size_kind": "amount", "size": "10m", "price": "100",
                                         "price_kind": "points", "pair": "USDTRY"}}}
    got = pr.clean_inputs(None, old)
    assert (got["by"]["ois"]["price_kind"], got["by"]["fx"]["price_kind"], got["by"]["ois"]["bulk"]) == ("rate", "points", "")
    assert pr.price_kind("ois", old["by"]["ois"]) == "rate" and pr.price_kind("fx", {}) == "outright"
    assert pr.clean_inputs({"price_kind": "upfront"}, got)["by"]["ois"]["price_kind"] == "upfront"
    assert pr.clean_inputs({"asset": "fx", "price_kind": "upfront"}, got)["by"]["fx"]["price_kind"] == "points"   # (no upfront)
    assert pr.clean_inputs({"asset": "fx", "price_kind": "npv_usd"}, got)["by"]["fx"]["price_kind"] == "npv_usd"
    assert pr.clean_inputs({"asset": "xccy", "price_kind": "points"}, got)["by"]["xccy"]["price_kind"] == "rate"   # (no points)
    # the Toplu box: kept as typed (line ends, blanks at the ends off), per asset, at most BULK_CHARS
    kept = pr.clean_inputs({"bulk": "1Y \r\n2Y\r\n\r\n"}, got)
    assert kept["by"]["ois"]["bulk"] == "1Y\n2Y" and kept["by"]["xccy"]["bulk"] == ""
    assert len(pr.clean_inputs({"bulk": "1Y\n" * 5000}, got)["by"]["ois"]["bulk"]) == pr.BULK_CHARS


def test_a_line_of_the_toplu_box():
    """A maturity (the whole line first: "2Y 3M" is 2Y3M), a start × end ("12x15"), two dates (a tab, ";" or " - "
    between them), then the price - one word: a bare number after a maturity is its price, not months; an FX forward's
    line is a value date."""
    def p(text, asset=pr.OIS):
        return pr.parse_line(text, asset)
    sp, d1, d2 = ("spot", 0.0), ("d", day("2027-05-04")), ("d", day("2028-05-04"))
    assert p("2Y3M") == p("2Y 3M") == (sp, ("m", 27.0), "") and p("1 yıl 6 ay") == (sp, ("m", 18.0), "")
    assert p("15") == (sp, ("m", 15.0), "") and p("12x15") == p("12 x 15") == p("12X15") == (("m", 12.0), ("m", 15.0), "")
    assert p("1Y × 18M -1m") == (("m", 12.0), ("m", 18.0), "-1m") and p("12x15 34,9") == (("m", 12.0), ("m", 15.0), "34,9")
    assert p("04.05.2027 04.05.2028") == p("04.05.2027;04.05.2028") == p("04.05.2027\t04.05.2028") == (d1, d2, "")
    assert p("04.05.2027 - 04.05.2028") == (d1, d2, "") and p("04.05.2027;04.05.2028;35,1") == (d1, d2, "35,1")
    assert p("04.05.2028 35,10") == (sp, d2, "35,10") and p("2Y 38,50") == (sp, ("m", 24.0), "38,50")
    assert p("1Y 500") == (sp, ("m", 12.0), "500") and p("1Y\t1.000.000") == (sp, ("m", 12.0), "1.000.000")
    assert p("2Y 3M 38,50") == (sp, ("m", 27.0), "38,50") and p("2Y -250k") == (sp, ("m", 24.0), "-250k")
    assert p("18M", pr.FX) == (sp, ("m", 18.0), "") and p("04.05.2028 79,10", pr.FX) == (sp, d2, "79,10")
    for bad, asset in (("abc", pr.OIS), ("12x15", pr.FX), ("", pr.OIS), ("2Y 38,50 1", pr.OIS)):
        with pytest.raises(pr.PricingError, match="satır okunamadı"):
            p(bad, asset)


# ================================================================================================== on the replay day
@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def curves(svc, user=None):
    book = svc.books["tto"]
    return svc.et.call(lambda: svc._try_curves(book, svc._calc(user, book)))


def market(svc, user=None) -> pr.Market:
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def run():
        calc = svc.interp.boot_of(book, svc._calc(user, book))
        return pr.read(lambda s, r, c: calc.get(idx[s], r, c))
    return svc.et.call(run)


def getter(svc, user=None):
    book = svc.books["tto"]
    idx = book.model.sheet_index
    return lambda s, r, c: svc.et.call(lambda: svc._calc(user, book).get(idx[s], r, c))


def text(serial: float) -> str:
    return serial_to_date(serial).strftime("%d.%m.%Y")


def test_the_curves_built_again_are_the_sheet_s_and_motor_s_own_bucket_bumps(svc):
    cv, mk = curves(svc), market(svc)
    boot = pr.motor_curve(mk.ois_quotes, mk.nodes)
    assert boot.days == cv["boot"].days and max(abs(a - b) for a, b in zip(boot.lndf, cv["boot"].lndf)) < 1e-15
    off = pr.quote_curve(cv["off_quotes"])
    assert off.days == cv["off_boot"].days and max(abs(a - b) for a, b in zip(off.lndf, cv["off_boot"].lndf)) < 1e-14
    # Motor's "Kova DV01 – her kota +1bp bootstrap" (T86:…): its ΔlnDF of every quote it bumps at every node
    base, bumps = pr.Curves(cv, mk).bumped(pr.ON, pr.BOOT)
    bumped = dict(bumps)
    checked = 0
    for c in range(20, 120):
        head = cell(svc, "Motor!%s87" % _col(c))
        if not (isinstance(head, str) and head.startswith("ΔlnDF ")):
            continue
        name = head[len("ΔlnDF "):]
        for r in range(89, 131):
            t = cell(svc, "Motor!C%d" % r)
            assert bumped[name].ln(t) - base.ln(t) == pytest.approx(cell(svc, "Motor!%s%d" % (_col(c), r)), abs=1e-15), (name, r)
        checked += 1
    assert checked >= 9                                                     # (1M … 3Y at least)


def _col(c: int) -> str:
    s = ""
    while c:
        c, k = divmod(c - 1, 26)
        s = chr(65 + k) + s
    return s


def test_every_asset_at_the_broken_date_block_s_own_date_is_the_block_s_number_both_ways(svc):
    """MASA's KIRIK VADE & KARŞILIK prices one value date: its forward, points, OIS (3M coupons, ACT/365) and XCCY (annual,
    ACT/360) market on the Bootstrap curves (F173, F174, F178, F179) and the same rows on the PPK curves (its PPK basamak
    column, ``ppkcurve.broken``) - the page at that date gives each number back, at the block's default date (18M) and at
    a broken one, the schedules counted back from the date as the block's helper does."""
    u = svc.login("Fiyatlama Kırık Vade")["user"]
    get = getter(svc, u)
    assert cell(svc, "MASA!BL175", u) == 0.0                                 # (the FX spot is the OIS spot: the OIS row's start)
    try:
        for when in (None, cell(svc, "MASA!BL171", u) + 819.0):              # (the block's own 18M; 31.01.2029, a Wednesday)
            if when is not None:
                assert svc.set_inputs(u, "tto", [{"ref": "MASA!C171", "value": text(when)}])["errors"] == []
            t = cell(svc, "MASA!C171", u)
            cv = curves(svc, u)
            ppk = pk.broken(get, cv["ppk"], cv["off_ppk"])
            fx = svc.pricing(u, {"asset": "fx", "pair": "USDTRY", "end": text(t), "side": "AL", "size_kind": "amount", "size": "1m"})
            assert fx["end"] == t and fx["mid"]["boot"] == pytest.approx(cell(svc, "MASA!F173", u), rel=1e-13)
            assert fx["fx"]["points"]["boot"] == pytest.approx(cell(svc, "MASA!F174", u), abs=1e-7)
            assert fx["mid"]["ppk"] == pytest.approx(ppk[pk.BROKEN_FWD], rel=1e-13)
            for asset, row in (("ois", pk.BROKEN_OIS), ("xccy", pk.BROKEN_XCCY)):
                got = svc.pricing(u, {"asset": asset, "start": "", "end": text(t), "side": "PAY", "size_kind": "dv01", "size": "1000"})
                assert got["end"] == t and "error" not in got, got.get("error")
                assert got["mid"]["boot"] == pytest.approx(cell(svc, "MASA!F%d" % row, u), abs=1e-13), (asset, when)
                assert got["mid"]["ppk"] == pytest.approx(ppk[row], abs=1e-13), (asset, when)
            # the XCCY's coupons are the helper's (BU192:BX203): back from the date in 12 months, the short one first
            helper = sorted((cell(svc, "MASA!BU%d" % r, u), cell(svc, "MASA!BX%d" % r, u)) for r in range(192, 204)
                            if cell(svc, "MASA!BV%d" % r, u) == 1.0)
            assert [(lg["pay"], lg["tau"]) for lg in got["schedule"]] == [(p, pytest.approx(a, abs=1e-15)) for p, a in helper]
    finally:
        svc.reset_inputs(u, "tto")


def test_the_fra_list_the_quotes_and_ppk_equal_to_bootstrap_at_a_quoted_maturity(svc):
    cv, mk = curves(svc), market(svc)
    # OIS · PPK's whole FRA list: the page's FRA (an OIS forward on the spot's quarterly calendar) is its market on
    # Bootstrap and its PPK basamak column's FRA on PPK
    n = 0
    for r in range(336, 439):
        m1, m2 = cell(svc, "OIS_MAIN!M%d" % r), cell(svc, "OIS_MAIN!N%d" % r)
        if type(m1) is not float or type(m2) is not float:
            continue
        deal = pr.swap_deal(pr.FRA if m1 else pr.OIS, ("m", m1) if m1 else ("spot", 0.0), ("m", m2), mk)
        assert pr.mid(deal, cv["boot"]) == pytest.approx(cell(svc, "OIS_MAIN!B%d" % r), abs=1e-13), r
        assert pr.mid(deal, cv["ppk"]) == pytest.approx(pk.fra(cv["ppk"], cv["grid"], int(m1), int(m2)), abs=1e-13), r
        n += 1
    assert n > 90
    # every OIS quote is the spot-start swap of its tenor on both curves (Motor's nodes are the swap's own days)
    for q in cv["quotes"]:
        deal = pr.swap_deal(pr.OIS, ("spot", 0.0), pr.parse_when(q.name), mk)
        assert [lg.pay - mk.ois_spot for lg in deal.legs] == list(q.pays)
        assert pr.mid(deal, cv["boot"]) == pytest.approx(q.rate, abs=1e-13) and pr.mid(deal, cv["ppk"]) == pytest.approx(q.rate, abs=1e-12)
    # zero coupon at a quoted maturity: both ways the same - OIS up to 3M, XCCY 1Y, an FX forward on a TRYI quote's day;
    # between two quotes they part
    for months in (1, 2, 3):
        deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", months), mk)
        assert len(deal.legs) == 1 and pr.mid(deal, cv["ppk"]) == pytest.approx(pr.mid(deal, cv["boot"]), abs=1e-13)
    one = pr.swap_deal(pr.XCCY, ("spot", 0.0), ("m", 12), mk)
    assert len(one.legs) == 1 and pr.mid(one, cv["off_ppk"]) == pytest.approx(pr.mid(one, cv["off_boot"]), abs=1e-13)
    assert pr.mid(one, cv["off_boot"]) == pytest.approx(next(q.rate for q in cv["off_quotes"] if q.name == "XCCY 1Y"), abs=1e-13)
    on_quote = 0
    for q in cv["off_quotes"]:
        if not q.name.startswith("TRYI"):
            continue
        fwd = pr.fx_deal("USDTRY", ("d", mk.fx_spot + q.end), mk)
        if fwd.end != mk.fx_spot + q.end:                                    # (a quote's day off the joint calendar)
            continue
        assert pr.forward(fwd, cv["off_ppk"]) == pytest.approx(pr.forward(fwd, cv["off_boot"]), rel=1e-13), q.name
        on_quote += 1
    assert on_quote >= 5
    seven = pr.fx_deal("USDTRY", ("m", 7), mk)
    assert abs(pr.forward(seven, cv["off_ppk"]) - pr.forward(seven, cv["off_boot"])) > 1e-4
    fifteen = pr.swap_deal(pr.FRA, ("m", 12), ("m", 15), mk)
    assert abs(pr.mid(fifteen, cv["ppk"]) - pr.mid(fifteen, cv["boot"])) * 1e4 > 50.0


def test_the_xccy_schedule_on_the_page_6m_then_12m(svc):
    """The desk's rule pinned on the page (18.11.2026): an 18M XCCY pays twice, 6 months then 12; a 2Y3M three times,
    3 + 12 + 12 months - ACT/360, the dates on business days."""
    u = svc.login("Fiyatlama XCCY Takvimi")["user"]
    got = svc.pricing(u, {"asset": "xccy", "start": "", "end": "18M", "side": "RECEIVE", "size_kind": "nominal", "size": "100m"})
    s = got["schedule"]
    assert [(text(x["start"]), text(x["pay"]), x["days"]) for x in s] == [("04.11.2026", "04.05.2027", 181.0),
                                                                        ("04.05.2027", "04.05.2028", 366.0)]
    assert [x["tau"] for x in s] == [181.0 / 360.0, 366.0 / 360.0]
    got = svc.pricing(u, {"end": "2Y3M"})
    assert [(text(x["start"]), text(x["pay"])) for x in got["schedule"]] == [
        ("04.11.2026", "04.02.2027"), ("04.02.2027", "04.02.2028"), ("04.02.2028", "05.02.2029")]
    mk = market(svc, u)
    hol = mk.holidays["TRY"]
    assert [x["pay"] for x in got["schedule"]] == [pr.tenor_date(mk.fx_spot, m, hol) for m in (3, 15, 27)]
    assert got["label"] == "XCCY 2Y3M" and got["texts"]["conventions"].startswith("XCCY: TRY sabit, yıllık ACT/360")


def test_dv01_buckets_sum_to_the_total_and_to_a_parallel_bump_a_far_one_is_zero(svc):
    u = svc.login("Fiyatlama DV01")["user"]
    cv, mk = curves(svc, u), market(svc, u)
    got = svc.pricing(u, {"asset": "ois", "start": "", "end": "2Y3M", "side": "PAY", "size_kind": "dv01", "size": "1000", "price": ""})
    rows = {r["name"]: r for r in got["buckets"]["rows"]}
    assert [r["name"] for r in got["buckets"]["rows"]][:4] == ["ON", "1W", "2W", "1M"] and rows["ON"]["dv01"]["boot"] is None
    deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", 27), mk)
    size = got["size"]["size"]
    # the size: OIS_MAIN's rule on the user's curve's annuity, rounded to the lot
    assert size == pr.round_half_away(1000.0 * mk.usdtry / (got["annuity"]["boot"] * 1e-4) / mk.lot) * mk.lot
    for m in pr.METHODS:
        total = got["buckets"]["total"][m]
        assert total == pytest.approx(sum(r["dv01"][m] for r in got["buckets"]["rows"] if r["pillar"]), abs=1e-9)
        assert all(rows[b]["dv01"][m] == 0.0 for b in ("5Y", "6Y", "7Y", "8Y", "9Y", "10Y")), m    # far from the maturity
        assert abs(rows["1M"]["dv01"][m]) < 1e-3 and rows["2Y"]["dv01"][m] > 100.0 and rows["3Y"]["dv01"][m] > 100.0
        assert 900.0 < total < 1100.0                                       # PAY: + when rates rise, ~ the size's DV01
    # the sum of the buckets is a parallel bump (every quote +1 bp at once) to the second order
    k = got["mid"]["boot"]
    par_boot = pr.motor_curve([(m, r + 1e-4) for m, r in mk.ois_quotes], mk.nodes)
    base = pr.motor_curve(mk.ois_quotes, mk.nodes)
    parallel = (pr.value(deal, par_boot, 1, size, k) - pr.value(deal, base, 1, size, k)) / mk.usdtry
    assert parallel == pytest.approx(got["buckets"]["total"]["boot"], rel=5e-3)
    par_ppk, _ = pk.calibrate(cv["shape"], [q._replace(rate=q.rate + 1e-4) for q in cv["quotes"]])
    k = got["mid"]["ppk"]
    parallel = (pr.value(deal, par_ppk, 1, size, k) - pr.value(deal, cv["ppk"], 1, size, k)) / mk.usdtry
    assert parallel == pytest.approx(got["buckets"]["total"]["ppk"], rel=5e-3)
    # RECEIVE the same: every bucket the other way round
    rec = svc.pricing(u, {"side": "RECEIVE"})
    assert all(r["dv01"]["boot"] == pytest.approx(-rows[r["name"]]["dv01"]["boot"], abs=1e-6) for r in rec["buckets"]["rows"] if r["pillar"])
    # XCCY 2Y3M received: the offshore curve's pillars, the far ones 0, the total −
    x = svc.pricing(u, {"asset": "xccy", "start": "", "end": "2Y3M", "side": "RECEIVE", "size_kind": "dv01", "size": "1000"})
    xr = {r["name"]: r["dv01"] for r in x["buckets"]["rows"]}
    assert set(xr) == {q.name for q in cv["off_quotes"]} and x["buckets"]["family"] == "off"
    assert all(xr[n][m] == 0.0 for n in ("XCCY 4Y", "XCCY 5Y") for m in pr.METHODS)
    assert x["buckets"]["total"]["boot"] < -800.0 and xr["XCCY 2Y"]["boot"] < -300.0
    # an FX forward bought: + when TRY rates rise, nothing beyond its date
    f = svc.pricing(u, {"asset": "fx", "pair": "USDTRY", "end": "18M", "side": "AL", "size_kind": "amount", "size": "10m"})
    fr = {r["name"]: r["dv01"] for r in f["buckets"]["rows"]}
    assert f["buckets"]["total"]["boot"] > 0 and f["buckets"]["total"]["ppk"] > 0
    assert all(fr[n][m] == 0.0 for n in ("XCCY 3Y", "XCCY 4Y", "XCCY 5Y") for m in pr.METHODS)
    # the bump sets are kept by what they are made of: asked again, none is made again
    kept = dict(svc._pricing_kept)
    svc.pricing(u, {"asset": "ois"})
    assert all(svc._pricing_kept.get(k) is v for k, v in kept.items())


def test_npv_is_zero_at_mid_and_plus_in_the_trader_s_favour(svc):
    u = svc.login("Fiyatlama NPV")["user"]
    got = svc.pricing(u, {"asset": "fra", "start": "12", "end": "15", "side": "PAY", "size_kind": "nominal", "size": "1mr"})
    mid = got["mid"]["boot"]
    at_mid = svc.pricing(u, {"price": repr(mid).replace(".", ",")})
    assert at_mid["npv"]["level"] == pytest.approx(mid, abs=1e-15) and abs(at_mid["npv"]["tl"]["boot"]) < 1e-3
    below = svc.pricing(u, {"price": "%%%s" % repr((mid - 0.001) * 100.0).replace(".", ",")})     # 10 bp under mid
    n = below["npv"]
    want = 1e9 * 0.001 * below["annuity"]["boot"]
    assert n["tl"]["boot"] == pytest.approx(want, rel=1e-9) and n["usd"]["boot"] == pytest.approx(want / got["usdtry"], rel=1e-9)
    assert n["dist"]["boot"] == pytest.approx(-10.0, abs=1e-9) and n["unit"] == "bp"
    rec = svc.pricing(u, {"side": "RECEIVE"})
    assert rec["npv"]["tl"]["boot"] == pytest.approx(-want, rel=1e-9)                 # received under mid: against
    # on PPK the same price is measured against PPK's mid
    assert n["tl"]["ppk"] == pytest.approx(1e9 * (got["mid"]["ppk"] - n["level"]) * below["annuity"]["ppk"], rel=1e-9)
    # an FX forward: the outright or points on the spot
    fx = svc.pricing(u, {"asset": "fx", "pair": "USDTRY", "end": "1Y", "side": "SAT", "size_kind": "amount", "size": "5m", "price": ""})
    f = fx["mid"]["boot"]
    pts = svc.pricing(u, {"price": repr((f - fx["fx"]["spot"]) * 1e4 + 100.0).replace(".", ","), "price_kind": "points"})
    assert pts["npv"]["level"] == pytest.approx(f + 0.01, abs=1e-9) and pts["npv"]["dist"]["boot"] == pytest.approx(100.0, abs=1e-6)
    assert pts["npv"]["tl"]["boot"] == pytest.approx(5e6 * 0.01 * fx["fx"]["df"]["boot"], rel=1e-9)   # sold over mid: +
    assert pts["npv"]["unit"] == "puan"


def test_the_page_s_inputs_are_each_user_s_own_per_asset(svc):
    a = svc.login("Fiyatlama Ayşe")["user"]
    b = svc.login("Fiyatlama Bora")["user"]
    first = svc.pricing(a)
    assert first["inputs"]["asset"] == "ois" and first["label"] == "TRY OIS 1Y" and first["method"] == "boot"
    assert [p["id"] for p in svc.nav() if p["group"] == "TRY Faiz"][:2] == ["ois", "fiyatlama"]
    svc.pricing(a, {"asset": "xccy", "end": "2Y3M", "side": "PAY"})
    svc.pricing(a, {"asset": "fra", "start": "1Yx18M"})
    again = svc.pricing(a)
    assert again["inputs"]["asset"] == "fra" and again["label"] == "FRA 12x18"
    back = svc.pricing(a, {"asset": "xccy"})
    assert back["label"] == "XCCY 2Y3M" and back["side"] == "PAY"                # (the XCCY as it was left)
    assert svc.pricing(b)["label"] == "TRY OIS 1Y"                               # another user: their own (the defaults)
    bad = svc.pricing(a, {"end": "2Q"})
    assert bad["error"].startswith("vade okunamadı") and bad["inputs"]["by"]["xccy"]["end"] == "2Q" and "label" not in bad
    assert svc.pricing(a, {"end": "18M"})["label"] == "XCCY 18M"
    # a user on PPK basamak: their curve first, the other beside
    svc.set_interp(b, "ppk")
    try:
        got = svc.pricing(b, {"asset": "fra", "start": "12", "end": "15"})
        assert got["method"] == "ppk" and got["methods"] == ["ppk", "boot"] and got["curve_text"] == "PPK basamak"
        assert got["mid"]["ppk"] == pytest.approx(pk.fra(curves(svc, b)["ppk"], curves(svc, b)["grid"], 12, 15), abs=1e-13)
    finally:
        svc.set_interp(b, "boot")


def test_on_the_replay_day(svc):
    """A few numbers of the replay day (03.11.2026, spot 04.11.2026): the 12x15 FRA ~70 bp lower on PPK; a 2Y3M XCCY
    between two quotes; the 18M USDTRY forward the block's; an XCCY 2Y two days after its quote's own day says so."""
    u = svc.login("Fiyatlama Kayıtlı Gün")["user"]
    fra = svc.pricing(u, {"asset": "fra", "start": "12", "end": "15"})
    assert round(fra["mid"]["boot"] * 100, 4) == 35.6684 and round(fra["mid"]["ppk"] * 100, 4) == 34.9610
    assert -71.5 < fra["diff"] < -70.0
    x = svc.pricing(u, {"asset": "xccy", "start": "", "end": "2Y3M"})
    assert 0.405 < x["mid"]["boot"] < 0.407 and abs(x["diff"]) < 2.0
    two = svc.pricing(u, {"end": "2Y"})
    assert any("XCCY 2Y kotasının gününe (04.11.2028) 2 gün uzak" in n for n in two["notes"])
    f = svc.pricing(u, {"asset": "fx", "pair": "USDTRY", "end": "18M"})
    assert round(f["mid"]["boot"], 4) == 79.0537 and f["end"] == date_to_serial(dt.date(2028, 5, 4))


def test_an_npv_or_an_upfront_typed_gives_the_rate_on_the_user_s_curve_every_number_at_it(svc):
    """The page with an NPV (TL, $) or an upfront (bp) typed: the rate that prices to it on the user's curve (a PPK user's
    on PPK), the other curve's rate for it beside; NPV, NPV $ and Peşin read back what was typed (forward(reverse(x)) = x to
    1e-9); the DV01 buckets and Fiyat − mid at that rate, as with that rate typed; an FX forward's outright the same."""
    u = svc.login("Fiyatlama NPV'den Faiz")["user"]
    first = svc.pricing(u, {"asset": "ois", "start": "", "end": "2Y3M", "side": "PAY", "size_kind": "nominal", "size": "1mr", "price": ""})
    assert first["price_kind"] == "rate" and first["npv"] is None
    usdtry = first["usdtry"]
    cv, mk = curves(svc, u), market(svc, u)
    deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", 27.0), mk)
    for kind, typed_text, tl in (("npv_tl", "1.000.000", 1e6), ("npv_usd", "-20.000", -2e4 * usdtry), ("upfront", "25", 2.5e6),
                                 ("upfront", "-0,1%", -1e6)):
        got = svc.pricing(u, {"price_kind": kind, "price": typed_text})
        n = got["npv"]
        assert "error" not in got and got["price_kind"] == kind and n["from"]["kind"] == kind and n["from"]["method"] == "boot"
        assert n["level"] == n["from"]["level"]["boot"]
        assert n["tl"]["boot"] == pytest.approx(tl, rel=1e-9) and n["usd"]["boot"] == pytest.approx(tl / usdtry, rel=1e-9)
        assert n["upfront"]["boot"] == pytest.approx(tl / 1e9 * 1e4, rel=1e-9)
        # the rate: the NPV's inverse on the Bootstrap curve; PPK's own rate for that NPV beside; the same rate on PPK
        assert n["level"] == pytest.approx(pr.level_for(deal, cv["boot"], 1, 1e9, tl), rel=1e-14)
        assert n["from"]["level"]["ppk"] == pytest.approx(pr.level_for(deal, cv["ppk"], 1, 1e9, tl), rel=1e-14)
        assert n["tl"]["ppk"] == pytest.approx(pr.value(deal, cv["ppk"], 1, 1e9, n["level"]), rel=1e-12)
        assert n["dist"]["boot"] == pytest.approx((n["level"] - got["mid"]["boot"]) * 1e4, abs=1e-9)
        # every number at that rate - as with the rate itself typed
        typed = svc.pricing(u, {"price_kind": "rate", "price": "%" + repr(n["level"] * 100.0).replace(".", ",")})
        assert typed["npv"]["tl"]["boot"] == pytest.approx(tl, rel=1e-6) and "from" not in typed["npv"]
        for a, b in zip(got["buckets"]["rows"], typed["buckets"]["rows"]):
            assert a["name"] == b["name"] and (a["dv01"]["boot"] is None or a["dv01"]["boot"] == pytest.approx(b["dv01"]["boot"], abs=1e-6))
    # a PPK user: the rate solved on PPK, Bootstrap's beside
    svc.set_interp(u, "ppk")
    try:
        got = svc.pricing(u, {"price_kind": "npv_tl", "price": "-500k"})
        n = got["npv"]
        assert got["methods"] == ["ppk", "boot"] and n["from"]["method"] == "ppk" and n["level"] == n["from"]["level"]["ppk"]
        assert n["tl"]["ppk"] == pytest.approx(-5e5, rel=1e-9)
        assert n["tl"]["boot"] == pytest.approx(pr.value(deal, cv["boot"], 1, 1e9, n["level"]), rel=1e-12)
    finally:
        svc.set_interp(u, "boot")
    # an FX forward sold: + over its forward; the outright solved is F + NPV / (amount · DF(value date))
    fx = svc.pricing(u, {"asset": "fx", "pair": "USDTRY", "end": "1Y", "side": "SAT", "size_kind": "amount", "size": "5m",
                         "price_kind": "npv_tl", "price": "250k"})
    n = fx["npv"]
    assert n["tl"]["boot"] == pytest.approx(250e3, rel=1e-9) and n["from"]["kind"] == "npv_tl" and "upfront" not in n
    assert n["level"] > fx["mid"]["boot"] and n["unit"] == "puan"
    assert n["level"] == pytest.approx(fx["mid"]["boot"] + 250e3 / (5e6 * fx["fx"]["df"]["boot"]), rel=1e-12)


def test_inputs_kept_before_the_price_kinds_read_as_they_did(svc):
    """A user's inputs kept before 24.11.2026 - no price kind, no Toplu box: a swap's price is its rate, an FX forward's
    its kept kind (points here); the Toplu box empty."""
    u = svc.login("Fiyatlama Eski Girdi")["user"]
    svc.store.put(svc.PRICING_KEY + u, {"asset": "fra", "by": {
        "fra": {"start": "12", "end": "15", "side": "PAY", "size_kind": "nominal", "size": "1mr", "price": "35"},
        "fx": {"start": "", "end": "1Y", "side": "AL", "size_kind": "amount", "size": "5m", "price": "100", "price_kind": "points",
               "pair": "USDTRY"}}})
    got = svc.pricing(u)
    assert got["price_kind"] == "rate" and got["npv"]["level"] == 0.35 and got["inputs"]["by"]["fra"]["bulk"] == ""
    deal = pr.swap_deal(pr.FRA, ("m", 12.0), ("m", 15.0), market(svc, u))
    assert got["npv"]["tl"]["boot"] == pytest.approx(pr.value(deal, curves(svc, u)["boot"], 1, 1e9, 0.35), rel=1e-12)
    fx = svc.pricing(u, {"asset": "fx"})
    assert fx["price_kind"] == "points" and fx["npv"]["level"] == pytest.approx(fx["fx"]["spot"] + 0.01, abs=1e-12)
    assert fx["bulk"]["rows"] == [] and fx["bulk"]["lines"] == 0


def test_the_toplu_box_prices_each_line_off_the_page_s_curves(svc, monkeypatch):
    """Toplu fiyatlama (item 4's "a box that prices a list of tenors at once"): each line as the page prices its
    instrument - its side, size and price kind - off the very curves of the page: nothing is built for a line (no
    bootstrap, no bump); each instrument on its own curve (OIS lines on OIS, XCCY and FX forwards offshore); a line
    that cannot be priced says why and the others are priced; at most 100 lines; the instrument's own error is not
    the lines'."""
    u = svc.login("Fiyatlama Toplu")["user"]
    lines = "2Y3M\n12x15\n04.05.2027 04.05.2028\n2Y 38,50\nabc\n12x9\n1Y 1.000.000"
    page = svc.pricing(u, {"asset": "ois", "start": "", "end": "2Y3M", "side": "PAY", "size_kind": "dv01", "size": "1000",
                           "price": "", "price_kind": "rate", "bulk": lines})
    b, rows = page["bulk"], page["bulk"]["rows"]
    assert [r["n"] for r in rows] == list(range(1, 8)) and [r["line"] for r in rows] == lines.split("\n")
    assert (b["family"], b["kind"], b["methods"], b["left_out"], b["side"]) == ("ois", "rate", ["boot", "ppk"], 0, "PAY")
    # the page's own instrument as a line: its very numbers (DV01: the size's, signed as the page's - a payer's +)
    one = rows[0]
    assert one["label"] == page["label"] and one["mid"] == page["mid"] and one["annuity"] == page["annuity"]
    assert one["size"] == page["size"]["size"] and one["dv01"]["boot"] == page["size"]["dv01"] > 0 and one["npv"] is None
    # a forward start on OIS: the FRA the page prices; two dates: that start and end
    fra = svc.pricing(u, {"asset": "fra", "start": "12", "end": "15"})
    assert rows[1]["mid"] == fra["mid"] and rows[1]["label"] == "TRY OIS 1Y × 15M"
    assert (text(rows[2]["start"]), text(rows[2]["end"])) == ("04.05.2027", "04.05.2028")
    # a price on the line: its NPV as the page gives it for that instrument and price
    two = svc.pricing(u, {"asset": "ois", "end": "2Y", "price": "38,50"})
    assert rows[3]["npv"]["tl"] == two["npv"]["tl"] and rows[3]["npv"]["dist"] == two["npv"]["dist"] and rows[3]["price"] == "38,50"
    # what cannot be priced says why on its own line
    assert rows[4]["error"].startswith("satır okunamadı") and "mid" not in rows[4]
    assert rows[5]["error"] == "vade başlangıçtan sonra olmalı"
    # the page's price kind for the lines: an NPV - each line's rate that prices to it, on the user's curve
    npv = svc.pricing(u, {"end": "2Y3M", "price": "", "price_kind": "npv_tl"})
    last = npv["bulk"]["rows"][6]
    assert last["npv"]["from"]["kind"] == "npv_tl" and last["npv"]["tl"]["boot"] == pytest.approx(1e6, rel=1e-9)
    assert npv["bulk"]["rows"][0]["npv"] is None and npv["bulk"]["kind"] == "npv_tl"
    svc.pricing(u, {"price_kind": "rate"})
    # XCCY lines on the offshore curve, FX forwards too - never OIS
    cv, mk = curves(svc, u), market(svc, u)
    x = svc.pricing(u, {"asset": "xccy", "start": "", "end": "2Y3M", "bulk": "2Y3M\n18M\n1Yx2Y"})
    xr = x["bulk"]["rows"]
    d18 = pr.swap_deal(pr.XCCY, ("spot", 0.0), ("m", 18.0), mk)
    assert x["bulk"]["family"] == "off" and xr[0]["mid"] == x["mid"] and xr[0]["label"] == "XCCY 2Y3M"
    assert xr[1]["mid"]["boot"] == pr.mid(d18, cv["off_boot"]) and xr[1]["mid"]["ppk"] == pr.mid(d18, cv["off_ppk"])
    assert xr[2]["label"] == "XCCY 1Y × 2Y" and abs(xr[1]["mid"]["boot"] - pr.mid(pr.swap_deal(pr.OIS, ("spot", 0.0), ("m", 18.0), mk), cv["boot"])) > 1e-4
    f = svc.pricing(u, {"asset": "fx", "pair": "USDTRY", "end": "18M", "bulk": "18M\n1M\n12x15"})
    fr = f["bulk"]["rows"]
    assert f["bulk"]["family"] == "off" and fr[0]["mid"] == f["mid"] and fr[0]["points"] == f["fx"]["points"]
    assert fr[2]["error"].startswith("satır okunamadı") and "valör" in fr[2]["error"]
    # the instrument's own error is not the lines'
    bad = svc.pricing(u, {"asset": "ois", "end": "2Q", "bulk": "1Y"})
    assert bad["error"].startswith("vade okunamadı") and bad["bulk"]["rows"][0]["label"] == "TRY OIS 1Y"
    # at most 100 lines priced, the rest counted
    many = svc.pricing(u, {"end": "1Y", "bulk": "\n".join(["1Y"] * 105)})
    assert len(many["bulk"]["rows"]) == 100 and many["bulk"]["lines"] == 105 and many["bulk"]["left_out"] == 5
    # a PPK user's lines: their curve first, sized on it
    svc.set_interp(u, "ppk")
    try:
        p = svc.pricing(u, {"end": "2Y3M", "bulk": "2Y3M"})
        assert p["bulk"]["methods"] == ["ppk", "boot"] and p["bulk"]["rows"][0]["size"] == p["size"]["size"]
        assert p["bulk"]["rows"][0]["dv01"]["ppk"] == p["size"]["dv01"]
        ppk_cv = curves(svc, u)
    finally:
        svc.set_interp(u, "boot")
    # nothing is built for a line: Motor's bootstrap, the offshore bootstrap, the bumps, the PPK calibration untouched
    def built(*a, **k):
        raise AssertionError("a curve built for a line")
    inputs = pr.clean_inputs({"asset": "xccy", "bulk": "2Y3M\n18M\n04.05.2027 04.05.2028 41"})
    for name in ("motor_curve", "quote_curve", "recalibrated", "slopes"):
        monkeypatch.setattr(pr, name, built)
    for name in ("calibrate", "bootstrap", "list_ois_curve"):
        monkeypatch.setattr(pk, name, built)
    monkeypatch.setattr(pr.Curves, "bumped", built)
    out = pr.bulk(inputs, pr.Curves(ppk_cv, mk), "ppk")
    assert [r.get("error") for r in out["rows"]] == [None, None, None] and out["rows"][2]["npv"]["level"] == 0.41


# ================================================================================================== over HTTP (last: it stops the service)
def test_the_route(svc):
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Fiyatlama HTTP")
        got = c.get("/api/pricing", headers=h).json()
        assert got["available"] and got["label"] == "TRY OIS 1Y" and got["inputs"]["asset"] == "ois"
        got = c.post("/api/pricing", json={"asset": "xccy", "end": "2Y3M", "side": "RECEIVE"}, headers=h).json()
        assert got["label"] == "XCCY 2Y3M" and len(got["schedule"]) == 3 and got["buckets"]["family"] == "off"
        assert c.get("/api/pricing", headers=h).json()["label"] == "XCCY 2Y3M"
        # an upfront typed and a Toplu box: the rate solved, every line priced; GET gives the same back
        up = c.post("/api/pricing", json={"price_kind": "upfront", "price": "25", "bulk": "2Y3M\n1Y 10"}, headers=h).json()
        assert up["npv"]["from"]["kind"] == "upfront" and abs(up["npv"]["upfront"]["boot"] - 25.0) < 1e-9
        assert [r["label"] for r in up["bulk"]["rows"]] == ["XCCY 2Y3M", "XCCY 1Y"] and up["bulk"]["rows"][1]["npv"]["from"]["typed"] == 10.0
        assert c.get("/api/pricing", headers=h).json()["bulk"]["rows"][0]["mid"] == up["bulk"]["rows"][0]["mid"]
        c.post("/api/pricing", json={"price_kind": "rate", "price": "", "bulk": ""}, headers=h)
        assert c.post("/api/pricing", json={"end": "yok"}, headers=h).json()["error"].startswith("vade okunamadı")
        assert c.post("/api/pricing", content=b"[1]", headers=dict(h, **{"Content-Type": "application/json"})).status_code == 400
        assert c.get("/api/pricing", headers=ANON).status_code == 401
        assert math.isfinite(got["buckets"]["total"]["boot"])
