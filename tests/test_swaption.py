"""Swaption (19.11.2026; the desk: "Önce bir swaption sekmesi yapmanı istiyorum. Try ois için hesaplayacağız. Vadeyi
seçtiğimde günlük, yıllık bps vol ve % black vol çıkacak. Ben buraya vol girdiğimde bana delta gamma vega hesaplayacak
... implied rate vade sonunda ne olacak ... breakeven rate'i hesaplayacak. Bu sadece görmek için olacak"): ``tto/swaption.py``
on its own - Bachelier's premiums (ATM = A·σN√T/√(2π), payer − receiver = A·(F − K)), the greeks against finite
differences, normal ↔ Black and back, the breakevens, bp/year = bp/day·√252 - and on the replay day: the underlying is
Fiyatlama's forward-start TRY OIS (its forward, annuity and coupons on both curves), the expiry the TRY business day
before its start, T the TRY business days to it / 252; on a made-up history the realized vol is the sample standard
deviation of the daily changes of the forward rebuilt day by day from each day's own spot and closes (the replay day's
forward the sheet's own), a past day without a TLREF fixing a holiday, each day's curve built once; a vol typed in any
unit overrides; a PPK basamak user gets the PPK forward first; beyond 10Y is refused; nothing is stored; the menu; the
HTTP route (last: it stops the service)."""
from __future__ import annotations

import datetime as dt
import math
import random
import statistics

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth
from tto import fxvol as fv
from tto import pricing as pr
from tto import swaption as sw
from tto.server import create_app
from tto.service import ServiceError
from tto.xl.values import date_to_serial, serial_to_date

F, A, N = 0.3575, 0.9877, 1e8
TODAY = dt.date(2026, 11, 3)                       # the replay day (spot 04.11.2026)


def day(text: str) -> float:
    return float(date_to_serial(dt.date.fromisoformat(text)))


# ================================================================================================== the maths
def test_the_atm_premium_is_a_sigma_root_t_over_root_two_pi():
    sigma = 79.37 * 1e-4                           # 5 bp a day, a year of them
    for days in (1, 22, 250, 1260):
        T = days / 252.0
        p = sigma * math.sqrt(T) / math.sqrt(2.0 * math.pi)
        o = sw.options(F, F, sigma, days, A, N, None)
        for kind in (sw.PAYER, sw.RECEIVER):
            assert o[kind]["running_bp"] == pytest.approx(p * 1e4, rel=1e-13)
            assert o[kind]["upfront_bp"] == pytest.approx(A * p * 1e4, rel=1e-13)
            assert o[kind]["tl"] == pytest.approx(N * A * p, rel=1e-13)
        assert o[sw.STRADDLE]["tl"] == pytest.approx(2.0 * N * A * p, rel=1e-13)
        assert o[sw.PAYER]["delta"] == 0.5 and o[sw.RECEIVER]["delta"] == -0.5 and o[sw.STRADDLE]["delta"] == 0.0


def test_payer_less_receiver_is_the_forward_swap():
    for K in (0.30, 0.3400, 0.3575, 0.3700, 0.42):
        for sigma in (0.002, 0.0125, 0.04):
            pay, rec = sw.premiums(F, K, sigma * math.sqrt(250 / 252.0))
            assert pay - rec == pytest.approx(F - K, abs=1e-15)
            o = sw.options(F, K, sigma, 250, A, N, None)
            assert o[sw.PAYER]["tl"] - o[sw.RECEIVER]["tl"] == pytest.approx(N * A * (F - K), abs=1e-6)
            assert o[sw.PAYER]["delta"] - o[sw.RECEIVER]["delta"] == pytest.approx(1.0, abs=1e-15)
    assert sw.premiums(F, 0.34, 0.0) == (pytest.approx(F - 0.34), 0.0)                    # no time, no vol: what it is worth now


def test_the_greeks_are_the_premium_s_finite_differences():
    K, sigma, days = 0.3650, 0.0110, 250                                   # an out of the money payer
    T = days / 252.0
    sb = sw.black_of(F, K, T, sigma)

    def tl(kind, f=F, s=sigma, n=days):
        return sw.options(f, K, s, n, A, N, None)[kind]["tl"]

    o = sw.options(F, K, sigma, days, A, N, sb)
    h = 1e-6
    for kind in sw.KINDS:
        g = o[kind]
        # delta: TL per bp of F; gamma: that delta's change for 1 bp; vega: TL per bp a year of normal vol
        assert g["delta_tl"] == pytest.approx((tl(kind, F + h) - tl(kind, F - h)) / (2 * h) * 1e-4, rel=1e-7)
        up, down = sw.options(F + h, K, sigma, days, A, N, None)[kind], sw.options(F - h, K, sigma, days, A, N, None)[kind]
        assert g["gamma_tl"] == pytest.approx((up["delta_tl"] - down["delta_tl"]) / (2 * h) * 1e-4, rel=1e-6)
        assert g["vega_tl"] == pytest.approx((tl(kind, s=sigma + h) - tl(kind, s=sigma - h)) / (2 * h) * 1e-4, rel=1e-7)
        # per 1 % of Black vol: the premium through the Black vol ± a little, each turned into its normal vol
        hb = 1e-6
        lo, hi = sw.normal_of(F, K, T, sb - hb), sw.normal_of(F, K, T, sb + hb)
        assert g["vega_black_tl"] == pytest.approx((tl(kind, s=hi) - tl(kind, s=lo)) / (2 * hb) * 0.01, rel=1e-6)
        # theta: the premium one business day nearer the expiry less today's - about −∂/∂T over a day of 252
        assert g["theta_tl"] == pytest.approx(tl(kind, n=days - 1) - tl(kind), rel=1e-12) and g["theta_tl"] < 0
        dT = 1e-4
        slope = (sw.options(F, K, sigma * math.sqrt((T + dT) / T), days, A, N, None)[kind]["tl"]
                 - sw.options(F, K, sigma * math.sqrt((T - dT) / T), days, A, N, None)[kind]["tl"]) / (2 * dT)
        assert g["theta_tl"] == pytest.approx(-slope / 252.0, rel=5e-3)
    # the receiver's delta is the payer's less the swap's, the straddle's the sum; gamma and vega the same each side
    assert o[sw.RECEIVER]["delta_tl"] == pytest.approx(o[sw.PAYER]["delta_tl"] - N * A * 1e-4, rel=1e-12)
    assert o[sw.STRADDLE]["gamma_tl"] == pytest.approx(2 * o[sw.PAYER]["gamma_tl"]) and o[sw.RECEIVER]["vega_tl"] == o[sw.PAYER]["vega_tl"]
    # the daily breakeven move of a delta-hedged straddle, √(−2Θ/Γ), is the daily bp vol (ATM; the day's own theta)
    atm = sw.options(F, F, 5 * math.sqrt(252) * 1e-4, days, A, N, None)[sw.STRADDLE]
    assert math.sqrt(-2 * atm["theta_tl"] / atm["gamma_tl"]) == pytest.approx(5.0, rel=1e-3)


def test_normal_and_black_vols_both_ways():
    T = 250 / 252.0
    for K in (0.33, 0.3575, 0.38):
        for sigma in (0.006, 0.0125, 0.03):
            b = sw.black_of(F, K, T, sigma)
            pay, rec = sw.premiums(F, K, sigma * math.sqrt(T))
            assert fv.black(F, K, b, T, True) == pytest.approx(pay, rel=1e-12)
            assert fv.black(F, K, b, T, False) == pytest.approx(rec, rel=1e-9)                # (parity: the receiver's too)
            assert sw.normal_of(F, K, T, b) == pytest.approx(sigma, rel=1e-10)
    # deep in the money at a low vol the payer is all intrinsic value: solved on the receiver's side, still a vol
    deep = sw.black_of(F, 0.30, T, 0.004)
    assert deep is not None and 0.0 < deep < 0.05 and fv.black(F, 0.30, deep, T, True) == pytest.approx(F - 0.30, rel=1e-12)
    assert sw.black_of(F, F, T, 0.0125) == pytest.approx(0.0125 / F, rel=2e-3)            # ATM: about σN / F
    assert sw.normal_of(F, F, T, 0.035) == pytest.approx(0.035 * F, rel=2e-3)
    assert sw.black_of(F, -0.01, T, 0.0125) is None and sw.black_of(-0.01, 0.01, T, 0.0125) is None
    assert sw.normal_of(F, 0.0, T, 0.03) is None and sw.black_of(F, F, 0.0, 0.0125) is None


def test_the_breakevens_at_expiry():
    K, sigma, days = 0.3500, 0.0090, 120
    o = sw.options(F, K, sigma, days, A, N, None)
    pay, rec = sw.premiums(F, K, sigma * math.sqrt(days / 252.0))
    assert o[sw.PAYER]["breakeven"] == pytest.approx(K + pay, abs=1e-15) and o[sw.RECEIVER]["breakeven"] == pytest.approx(K - rec, abs=1e-15)
    assert o[sw.STRADDLE]["breakeven"] == {"low": pytest.approx(K - pay - rec), "high": pytest.approx(K + pay + rec)}
    # at the breakeven the payoff at the expiry pays the forward premium back
    assert max(o[sw.PAYER]["breakeven"] - K, 0.0) == pytest.approx(pay, abs=1e-15)
    assert max(K - o[sw.RECEIVER]["breakeven"], 0.0) == pytest.approx(rec, abs=1e-15)
    assert o[sw.PAYER]["running_bp"] * 1e-4 == pytest.approx(pay, rel=1e-15)


def test_what_is_typed():
    got = sw.read_inputs({})
    assert (got["expiry_m"], got["tenor_m"], got["k"], got["n"], got["typed"], got["vol_unit"]) == (12, 24, None, 1e8, None, "day")
    got = sw.read_inputs({"expiry": "18m", "tenor": "2Y3M", "strike": "35,10", "notional": "2,5mn", "vol": "5,5", "vol_unit": "DAY"})
    assert (got["expiry_m"], got["tenor_m"], got["k"], got["n"], got["typed"]) == (18, 27, pytest.approx(0.351), 2.5e6, 5.5)
    assert sw.read_inputs({"strike": "%35,1"})["k"] == pytest.approx(0.351) and sw.read_inputs({"strike": "ATM"})["k"] is None
    assert sw.read_inputs({"notional": "100 mn"})["n"] == 1e8 and sw.read_inputs({"notional": "50.000.000"})["n"] == 5e7
    assert sw.read_inputs({"vol": "4,2", "vol_unit": "black"})["typed"] == pytest.approx(0.042)
    assert sw.read_inputs({"vol": "%4,2", "vol_unit": "black"})["typed"] == pytest.approx(0.042)
    assert sw.read_inputs({"vol": "87", "vol_unit": "year"})["typed"] == 87.0
    assert sw.read_inputs({"expiry": "5Y", "tenor": "5Y"})["tenor_m"] == 60                     # 10Y: the curve's end
    for bad, says in (({"expiry": "5Y", "tenor": "7Y"}, "en çok 10 yıl"), ({"expiry": "1M", "tenor": "10Y"}, "1M × 10Y = 10Y1M"),
                      ({"expiry": "abc"}, "opsiyon vadesi okunamadı"), ({"expiry": "2W"}, "ay ya da yıl"),
                      ({"expiry": "04.05.2028"}, "ay ya da yıl"), ({"tenor": "x"}, "swap vadesi okunamadı"),
                      ({"strike": "yok"}, "strike okunamadı"), ({"notional": "0"}, "nominal okunamadı"),
                      ({"vol": "-1"}, "vol okunamadı"), ({"vol": "1", "vol_unit": "pct"}, "vol birimi")):
        with pytest.raises(sw.SwaptionError) as err:
            sw.read_inputs(bad)
        assert says in str(err.value), (bad, str(err.value))


def test_the_tenors_a_day_needs():
    nodes = [0, 1, 2, 3] + list(range(6, 121, 3))
    quotes = [1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 60, 72, 84, 96, 108, 120]
    assert sw.needed_months(12, 24, nodes, quotes) == [1, 2, 3, 6, 9, 12, 18, 24, 36]          # 3Y: a quote
    assert sw.needed_months(3, 9, nodes, quotes) == [1, 2, 3, 6, 9, 12]
    assert sw.needed_months(1, 12, nodes, quotes)[-1] == 18                  # 13M reads Motor's 15M node: 1Y and 18M quotes
    assert sw.needed_months(24, 15, nodes, quotes)[-1] == 48                 # 39M: the 39M node, between the 3Y and 4Y quotes
    assert sw.needed_months(60, 60, nodes, quotes)[-1] == 120


# ================================================================================================== on the replay day
@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def market(svc, user=None) -> pr.Market:
    book = svc.books["tto"]
    idx = book.model.sheet_index

    def run():
        calc = svc.interp.boot_of(book, svc._calc(user, book))
        return pr.read(lambda s, r, c: calc.get(idx[s], r, c))
    return svc.et.call(run)


def label(months: int) -> str:
    return sw.label(months)


def test_the_underlying_is_fiyatlama_s_forward_start_ois(svc):
    u = svc.login("Swaption Fiyatlama")["user"]
    for e, t in ((12, 24), (3, 12), (18, 60), (24, 36), (1, 12), (60, 60)):
        got = svc.swaption(u, {"expiry": label(e), "tenor": label(t)})
        p = svc.pricing(u, {"asset": "ois", "start": label(e), "end": label(e + t)})
        assert got["underlying"] == p["label"] == "TRY OIS %s × %s" % (label(e), label(e + t))
        assert got["forward"] == p["mid"] and got["annuity"] == p["annuity"]                 # both curves, to the last digit
        assert (got["start"], got["end"]) == (p["start"], p["end"]) and got["spot"] == p["spot"] == day("2026-11-04")
        assert [(s["start"], s["pay"], s["tau"]) for s in got["schedule"]] == [(s["start"], s["pay"], s["tau"]) for s in p["schedule"]]
        assert got["F"] == got["forward"]["boot"] and got["A"] == got["annuity"]["boot"] and got["curve"] == "boot"
        assert got["strike"] == got["F"] and got["atm"] and got["dv01"] == pytest.approx(1e8 * got["A"] * 1e-4, rel=1e-15)
    # the replay day's 1Y × 2Y: the forward 1Y × 3Y, a year and its 250 TRY business days to the expiry
    one = svc.swaption(u, {})
    assert (one["label"], one["underlying"]) == ("1Y × 2Y", "TRY OIS 1Y × 3Y")
    assert round(one["F"] * 100, 4) == 35.7502 and round(one["A"], 5) == 0.98771 and abs(one["diff"]) < 0.01


def test_the_expiry_is_the_business_day_before_the_start_and_t_counts_business_days(svc):
    u = svc.login("Swaption Tarih")["user"]
    hol = market(svc).holidays["TRY"]
    today = float(date_to_serial(TODAY))
    for e in ("1M", "3M", "1Y", "2Y", "3Y", "5Y"):
        got = svc.swaption(u, {"expiry": e, "tenor": "1Y"})
        x, start = got["expiry"], got["start"]
        assert x < start and pr.is_business(x, hol) and not any(pr.is_business(d, hol) for d in range(int(x) + 1, int(start)))
        n = sum(1 for d in range(int(today) + 1, int(x) + 1) if serial_to_date(d).weekday() < 5 and float(d) not in hol)
        assert got["today"] == today and got["bdays"] == n and got["T"] == n / 252.0 and got["cdays"] == x - today
    one = svc.swaption(u, {"expiry": "1Y"})
    assert serial_to_date(one["expiry"]) == dt.date(2027, 11, 3) and one["bdays"] == 250
    two = svc.swaption(u, {"expiry": "2Y"})                    # its start 04.11.2028 is a Saturday: Monday, the Friday before
    assert (serial_to_date(two["start"]), serial_to_date(two["expiry"])) == (dt.date(2028, 11, 6), dt.date(2028, 11, 3))


def test_a_vol_typed_in_any_unit_prices_and_the_other_two_follow(svc):
    u = svc.login("Swaption Vol")["user"]
    plain = svc.swaption(u, {})
    assert plain["vol"]["source"] == "realized" and plain["vol"]["day"] is None and plain["options"] is None
    assert plain["vol"]["why"].startswith("Gerçekleşen vol yok")                 # (this service has no history: no vol)
    d = svc.swaption(u, {"vol": "5", "vol_unit": "day"})
    v = d["vol"]
    assert (v["source"], v["unit"], v["day"]) == ("typed", "day", 5.0) and v["year"] == pytest.approx(5 * math.sqrt(252), rel=1e-15)
    assert v["black"] == pytest.approx(sw.black_of(d["F"], d["strike"], d["T"], v["year"] * 1e-4), rel=1e-15)
    y = svc.swaption(u, {"vol": str(v["year"]).replace(".", ","), "vol_unit": "year"})
    b = svc.swaption(u, {"vol": repr(v["black"] * 100), "vol_unit": "black"})
    for other, unit in ((y, "year"), (b, "black")):
        assert other["vol"]["unit"] == unit and other["vol"]["day"] == pytest.approx(5.0, rel=1e-9)
        for kind in sw.KINDS:
            for k in ("tl", "delta_tl", "gamma_tl", "vega_tl", "theta_tl"):
                assert other["options"][kind][k] == pytest.approx(d["options"][kind][k], rel=1e-8), (unit, kind, k)
    # the rate at the expiry, ±1σ and ±2σ on the normal model
    r, sd = d["range"], v["year"] * 1e-4 * math.sqrt(d["T"])
    assert r["sd_bp"] == pytest.approx(sd * 1e4) and (r["down1"], r["up2"]) == (pytest.approx(d["F"] - sd), pytest.approx(d["F"] + 2 * sd))
    # a strike typed: the moneyness, Black at that strike, the payer's breakeven K + its running premium
    k = svc.swaption(u, {"strike": "36,50", "vol": "5"})
    assert k["strike"] == pytest.approx(0.365) and not k["atm"] and k["moneyness_bp"] == pytest.approx((0.365 - k["F"]) * 1e4)
    assert k["options"]["payer"]["breakeven"] == pytest.approx(0.365 + k["options"]["payer"]["running_bp"] * 1e-4, abs=1e-15)
    assert k["options"]["payer"]["delta"] < 0.5 and k["options"]["receiver"]["delta"] < -0.5         # out of / in the money
    assert svc.swaption(u, {"notional": "50m", "vol": "5"})["options"]["payer"]["tl"] == pytest.approx(d["options"]["payer"]["tl"] / 2)


def test_a_premium_or_a_breakeven_typed_gives_the_vol_two_way():
    """Two-way (the desk, 24.11.2026: "tüm tablolar bu şekilde olmalı"): an option's premium (running bp, upfront bp, TL)
    or breakeven typed in place of the vol is priced at the normal vol that gives it - the closed form at the money,
    Brent elsewhere, for payer, receiver and straddle, in and out of the money; under the intrinsic value no vol."""
    T = 250 / 252.0
    for K in (F, F + 0.0125, F - 0.02):
        sigma = 118.7e-4
        pay, rec = sw.premiums(F, K, sigma * math.sqrt(T))
        for kind, p in (("payer", pay), ("receiver", rec), ("straddle", pay + rec)):
            assert sw.normal_from_premium(kind, F, K, T, p) == pytest.approx(sigma, rel=1e-12), (K, kind)
            for measure, typed in (("running", p / 1e-4), ("upfront", A * p / 1e-4), ("tl", N * A * p)):
                assert sw.premium_of("%s:%s" % (kind, measure), typed, K, A, N) == pytest.approx(p, rel=1e-14)
        assert sw.premium_of("payer:be", K + pay, K, A, N) == pytest.approx(pay, abs=1e-15)
        assert sw.premium_of("receiver:be", K - rec, K, A, N) == pytest.approx(rec, abs=1e-15)
        for unit, level in (("straddle:be_low", K - pay - rec), ("straddle:be_high", K + pay + rec)):
            assert sw.premium_of(unit, level, K, A, N) == pytest.approx(pay + rec, abs=1e-15)
    # at the money each leg is s/√(2π): the closed form
    assert sw.normal_from_premium("payer", F, F, T, 0.01) == 0.01 * fv.SQRT2PI / math.sqrt(T)
    assert sw.normal_from_premium("straddle", F, F, T, 0.02) == 0.01 * fv.SQRT2PI / math.sqrt(T)
    # at or under the intrinsic value (0,02 in the money) no vol; nothing typed reads as before
    assert sw.normal_from_premium("payer", F, F - 0.02, T, 0.02) is None and sw.normal_from_premium("receiver", F, F + 0.02, T, 0.015) is None
    got = sw.read_inputs({"vol": "125,5", "vol_unit": "payer:running"})
    assert (got["typed"], got["vol_unit"]) == (125.5, "payer:running")
    assert sw.read_inputs({"vol": "1,2mn", "vol_unit": "straddle:tl"})["typed"] == 1.2e6
    assert sw.read_inputs({"vol": "36,25", "vol_unit": "receiver:be"})["typed"] == pytest.approx(0.3625)
    for bad, why in (({"vol": "0", "vol_unit": "payer:upfront"}, "Payer prim (bp, peşin) okunamadı: '0'"),
                     ({"vol": "abc", "vol_unit": "straddle:be_low"}, "Straddle alt başabaşı okunamadı")):
        with pytest.raises(sw.SwaptionError) as exc:
            sw.read_inputs(bad)
        assert str(exc.value).startswith(why), exc.value


def test_each_premium_and_breakeven_of_the_page_typed_back_gives_the_same_vol(svc):
    """On the replay day (5 bp a day typed): each premium of the table and each breakeven typed back as such gives the
    same vol and the same numbers (1e-9); the vol says what priced it; one under the intrinsic value is refused with the
    reason; nothing typed in its unit reads the realized vol as before."""
    u = svc.login("Swaption iki yönlü")["user"]
    for strike in ("", "36,50"):
        d = svc.swaption(u, {"strike": strike, "vol": "5", "vol_unit": "day"})
        o = d["options"]
        typed = {"%s:%s" % (k, m): o[k][key] for k in sw.KINDS for m, key in (("running", "running_bp"), ("upfront", "upfront_bp"),
                                                                                ("tl", "tl"))}
        typed.update({"payer:be": o["payer"]["breakeven"], "receiver:be": o["receiver"]["breakeven"],
                      "straddle:be_low": o["straddle"]["breakeven"]["low"], "straddle:be_high": o["straddle"]["breakeven"]["high"]})
        for unit, value in typed.items():
            back = svc.swaption(u, {"strike": strike, "vol": repr(value * 100 if ":be" in unit else value), "vol_unit": unit})
            assert back["vol"]["source"] == "typed" and back["vol"]["unit"] == unit and back["vol"]["unit_text"] == sw.UNIT_TEXT[unit]
            assert back["vol"]["day"] == pytest.approx(5.0, rel=1e-9), (strike, unit)
            for kind in sw.KINDS:
                for k in ("running_bp", "upfront_bp", "tl", "delta_tl", "vega_tl", "theta_tl"):
                    assert back["options"][kind][k] == pytest.approx(o[kind][k], rel=1e-9), (strike, unit, kind, k)
    k = svc.swaption(u, {"strike": "33", "vol": "5", "vol_unit": "day"})               # (deep in the money for the payer)
    intrinsic = (k["F"] - 0.33) * 1e4
    with pytest.raises(ServiceError) as exc:
        svc.swaption(u, {"strike": "33", "vol": "%.2f" % (intrinsic - 1), "vol_unit": "payer:running"})
    assert exc.value.status == 400 and str(exc.value).startswith("Payer prim (bp, running): hiçbir vol bunu vermez")
    assert svc.swaption(u, {"vol": "", "vol_unit": "payer:running"})["vol"]["source"] == "realized"


def test_a_ppk_user_gets_the_ppk_forward_first(svc):
    a = svc.login("Swaption Boot")["user"]
    b = svc.login("Swaption PPK")["user"]
    svc.set_interp(b, "ppk")
    try:
        got = svc.swaption(b, {"expiry": "15M", "tenor": "2Y", "vol": "5"})
        assert (got["curve"], got["methods"], got["curve_text"]) == ("ppk", ["ppk", "boot"], "PPK basamak")
        assert got["F"] == got["forward"]["ppk"] and got["A"] == got["annuity"]["ppk"] and got["strike"] == got["forward"]["ppk"]
        p = svc.pricing(b, {"asset": "ois", "start": "15M", "end": "3Y3M"})
        assert got["forward"] == p["mid"] and got["annuity"] == p["annuity"]
        boot = svc.swaption(a, {"expiry": "15M", "tenor": "2Y", "vol": "5"})
        assert boot["curve"] == "boot" and boot["forward"] == got["forward"]                 # the same two curves, the other first
        assert got["diff"] == pytest.approx((got["forward"]["ppk"] - got["forward"]["boot"]) * 1e4) and abs(got["diff"]) > 0.1
        assert got["options"]["payer"]["tl"] == pytest.approx(
            1e8 * got["annuity"]["ppk"] * sw.premiums(got["F"], got["F"], 5 * math.sqrt(252) * 1e-4 * math.sqrt(got["T"]))[0])
    finally:
        svc.set_interp(b, "boot")


def test_beyond_ten_years_and_what_cannot_be_read_are_refused(svc):
    u = svc.login("Swaption Hata")["user"]
    for q, says in (({"expiry": "5Y", "tenor": "7Y"}, "10 yıl"), ({"expiry": "3Y", "tenor": "10Y"}, "TRY OIS eğrisi 10Y'de biter"),
                    ({"tenor": "abc"}, "swap vadesi okunamadı"), ({"vol": "x"}, "vol okunamadı")):
        with pytest.raises(ServiceError) as err:
            svc.swaption(u, q)
        assert err.value.status == 400 and says in str(err.value)
    assert svc.swaption(u, {"expiry": "5Y", "tenor": "5Y"})["end"] == svc.pricing(u, {"asset": "ois", "start": "5Y", "end": "10Y"})["end"]
    with pytest.raises(ServiceError) as err:
        svc.swaption(None, {})
    assert err.value.status == 401


def test_nothing_is_stored_and_the_page_is_in_try_faiz_after_fiyatlama(svc):
    u = svc.login("Swaption Menü")["user"]

    def counts():
        return [svc.store._q("SELECT COUNT(*) AS n FROM %s" % t)[0]["n"] for t in ("kv", "user_inputs", "shared_inputs")]

    before = counts()
    for q in ({}, {"expiry": "3M", "tenor": "5Y", "strike": "35", "vol": "4,5", "vol_unit": "black"}, {"notional": "1mr"}):
        svc.swaption(u, q)
    assert counts() == before
    pages = svc.nav()
    # a tab of Fiyatlama, right after it (the menu of 28.11.2026: tto/navmenu.py)
    assert [p["id"] for p in pages if p.get("menu") == "faiz.fiyatlama"][:2] == ["fiyatlama", "swaption"]
    page = next(p for p in pages if p["id"] == "swaption")
    assert (page["title"], page["group"], page["custom"], page["book"]) == ("Swaption", "TRY Faiz", True, "tto")


# ================================================================================================== on a made-up history
@pytest.fixture(scope="module")
def seeded(svc):
    """90 week days of made-up closes for every tenor Motor bootstraps (1M … 10Y), ending on the replay day with the
    sheet's own quotes; the 3Y missing on one day (the 1Y × 2Y forward has no level that day), the 7Y on another (it
    does); TLREF fixed every week day of them but one (a holiday of the past the history knows by that)."""
    snap = svc.history.snapshot()
    ids = {float(d.months): d.id for d in snap["defs"] if d.group == "ois" and d.months and d.months >= 1}
    ref = next(d for d in snap["defs"] if d.group == "ref")
    quotes = dict(market(svc).ois_quotes)
    assert sorted(quotes) == sorted(ids)
    days = []
    d = TODAY
    while len(days) < 90:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= dt.timedelta(days=1)
    days.reverse()
    rng = random.Random(19)
    closes = {m: {} for m in quotes}
    level = {m: quotes[m] * 100.0 for m in quotes}
    for iso in reversed(days):
        for m in quotes:
            closes[m][iso] = round(level[m], 10)
        common = rng.gauss(0.0, 0.07)
        for m in quotes:
            level[m] -= common + rng.gauss(0.0, 0.02 + 0.002 * math.sqrt(m))
    hole3y, hole7y, gap = days[-10], days[-20], days[-30]
    del closes[36.0][hole3y]
    del closes[84.0][hole7y]
    for m, s in closes.items():
        svc.store.hist_upsert(ids[m], sorted(s.items()))
    svc.store.hist_upsert(ref.id, [(iso, 39.5) for iso in days if iso != gap])
    svc.history.rev += 1                                                     # what the history does when it stores closes
    return {"days": days, "closes": closes, "hole3y": hole3y, "hole7y": hole7y, "gap": gap}


def history_forward(mk: pr.Market, closes, iso: str, e: int, t: int, hol) -> float:
    """The forward of one day as the desk's workbook would have it that day: its spot the next TRY business day, Motor's
    nodes from it, Motor's bootstrap of that day's closes, Fiyatlama's dating."""
    spot = pr.roll(day(iso) + 1.0, hol)
    nodes = [(m, (pr.tenor_date(spot, int(m), hol) - spot) if m else 0.0) for m, _ in mk.nodes]
    curve = pr.motor_curve([(m, s[iso] / 100.0) for m, s in sorted(closes.items()) if iso in s], nodes)
    deal = pr.swap_deal(pr.OIS, ("m", float(e)), ("m", float(e + t)), mk._replace(ois_spot=spot))
    return pr.mid(deal, curve)


def test_the_realized_vol_is_the_stdev_of_the_daily_forward_changes(svc, seeded):
    u = svc.login("Swaption Geçmiş")["user"]
    got = svc.swaption(u, {"expiry": "1Y", "tenor": "2Y"})
    days, closes = seeded["days"], seeded["closes"]
    mk = market(svc)
    hol = mk.holidays["TRY"] | {day(seeded["gap"])}                          # the week day TLREF was not fixed: a holiday
    need = [1.0, 2.0, 3.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0]
    used = [d for d in days if all(d in closes[m] for m in need)]
    assert len(used) == 89 and seeded["hole3y"] not in used and seeded["hole7y"] in used
    levels = [history_forward(mk, closes, d, 12, 24, hol) for d in used]
    # the replay day's closes are the sheet's quotes: its forward is today's Bootstrap forward
    assert levels[-1] == pytest.approx(got["forward"]["boot"], abs=1e-13)
    moves = [(b - a) * 1e4 for a, b in zip(levels, levels[1:])]
    rows = {r["window"]: r for r in got["realized"]["rows"]}
    for n in (20, 60):
        r = rows[n]
        assert r["day"] == pytest.approx(statistics.stdev(moves[-n:]), rel=1e-9) and (r["n"], r["full"]) == (n, True)
        assert (r["first"], r["last"]) == (used[-(n + 1)], used[-1])
        assert r["year"] == pytest.approx(r["day"] * math.sqrt(252), rel=1e-15)
        assert r["black"] == pytest.approx(sw.black_of(got["F"], got["strike"], got["T"], r["year"] * 1e-4), rel=1e-15)
    for n in (120, 250):                                                       # what there is, and said so
        assert rows[n]["day"] == pytest.approx(statistics.stdev(moves), rel=1e-9) and (rows[n]["n"], rows[n]["full"]) == (88, False)
    rz = got["realized"]
    assert rz["need"] == ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y"] and rz["missing"] == [] and rz["days"] == 89
    assert (rz["first"], rz["last"]) == (used[0], used[-1]) and got["history"]["days"] == 90
    # the 60 changes' vol prices: its bp/day, × √252 a year, Black at F and K
    v = got["vol"]
    assert (v["source"], v["window"], v["n"], v["full"]) == ("realized", 60, 60, True) and v["day"] == rows[60]["day"]
    assert v["year"] == rows[60]["year"] and v["black"] == rows[60]["black"] and got["options"]["payer"]["tl"] > 0
    # a vol typed still wins over it
    typed = svc.swaption(u, {"expiry": "1Y", "tenor": "2Y", "vol": "4", "vol_unit": "day"})
    assert (typed["vol"]["source"], typed["vol"]["day"]) == ("typed", 4.0) and typed["realized"]["rows"] == got["realized"]["rows"]
    # without the past holiday the day before it would be dated from another spot: the TLREF gap does count
    before = used.index(seeded["gap"]) - 1
    assert history_forward(mk, closes, used[before], 12, 24, mk.holidays["TRY"]) != pytest.approx(levels[before], abs=1e-12)


def test_each_day_s_curve_is_built_once_for_every_expiry_and_tenor(svc, seeded, monkeypatch):
    u = svc.login("Swaption Önbellek")["user"]
    svc.swaption(u, {"expiry": "6M", "tenor": "1Y"})
    built = []
    real = sw.day_curve
    monkeypatch.setattr(sw, "day_curve", lambda *a: built.append(a[0]) or real(*a))
    short = svc.swaption(u, {"expiry": "3M", "tenor": "9M"})
    again = svc.swaption(u, {"expiry": "6M", "tenor": "1Y"})
    assert built == [] and short["realized"]["days"] == 90 and again["realized"]["rows"][0]["day"] is not None
    assert short["realized"]["need"] == ["1M", "2M", "3M", "6M", "9M", "1Y"]                # the holes are beyond it: every day
    mk = market(svc)
    hol = mk.holidays["TRY"] | {day(seeded["gap"])}
    levels = [history_forward(mk, seeded["closes"], d, 3, 9, hol) for d in seeded["days"]]
    moves = [(b - a) * 1e4 for a, b in zip(levels, levels[1:])]
    assert short["realized"]["rows"][0]["day"] == pytest.approx(statistics.stdev(moves[-20:]), rel=1e-9)
    # a new close (the history's revision moves): that day's curve again, the others kept
    svc.store.hist_upsert(next(d.id for d in svc.history.snapshot()["defs"] if d.group == "ois" and d.months == 12.0),
                          [(seeded["days"][-1], seeded["closes"][12.0][seeded["days"][-1]] + 0.05)])
    svc.history.rev += 1
    svc.swaption(u, {"expiry": "3M", "tenor": "9M"})
    assert built == [day(seeded["days"][-1])]


# ================================================================================================== over HTTP (last: it stops the service)
def test_the_route(svc):
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Swaption HTTP")
        got = c.get("/api/swaption", headers=h, params={"expiry": "1Y", "tenor": "2Y", "vol": "5"})
        assert got.status_code == 200
        d = got.json()
        assert d["available"] and d["label"] == "1Y × 2Y" and d["vol"]["source"] == "typed" and d["options"]["payer"]["tl"] > 0
        bad = c.get("/api/swaption", headers=h, params={"expiry": "5Y", "tenor": "7Y"})
        assert bad.status_code == 400 and "10 yıl" in bad.json()["error"]
        assert c.get("/api/swaption", headers=h, params={"strike": "abc"}).json()["error"].startswith("strike okunamadı")
        assert c.get("/api/swaption", headers=ANON).status_code == 401
        assert c.get("/api/swaption", headers=h).json()["label"] == "1Y × 2Y"            # nothing kept: the defaults again
