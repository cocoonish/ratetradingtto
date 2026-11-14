"""FX option smiles (``tto/fxvol.py``): the normal law, Black, the quoted deltas and their strikes, the market
strangle, the three smiles fitted to quotes, and the distribution of the spot they imply.

The quotes here are made up (round numbers shaped like a G10 smile and like USDTRY's), not market data."""
from __future__ import annotations

import math

import pytest

from tto import fxvol as fv

EURUSD_1M = dict(F=1.1037, T=30 / 365, atm=0.0610, rr25=-0.0052, bf25=0.0018, rr10=-0.0095, bf10=0.0059)
# USDTRY-like: puts far below the ATM vol, calls far above, a large carry in the forward
USDTRY_1M = dict(F=51.56, T=30 / 365, atm=0.0465, rr25=0.054, bf25=0.0076, rr10=0.1055, bf10=0.0395)


def quotes(d, premium, df=1.0, **over):
    args = dict(d)
    args.update(over)
    return fv.Quotes(args["F"], args["T"], args["atm"], args.get("rr25"), args.get("bf25"), args.get("rr10"), args.get("bf10"),
                     premium=premium, df=df)


# ---------------------------------------------------------------------------------------------- building blocks
def test_normal_law_and_its_inverse():
    assert fv.ncdf(0.0) == 0.5
    assert abs(fv.ncdf(1.959963984540054) - 0.975) < 1e-15
    for p in (1e-9, 1e-4, 0.01, 0.02425, 0.1, 0.5, 0.75, 0.97575, 0.999, 1 - 1e-9):
        assert abs(fv.ncdf(fv.ninv(p)) - p) < 1e-13 * max(1.0, 1.0 / p)
    assert abs(fv.ninv(0.975) - 1.959963984540054) < 1e-13
    with pytest.raises(ValueError):
        fv.ninv(1.0)


def test_black_parity_and_vega():
    F, K, s, T = 51.5, 53.0, 0.12, 0.5
    assert abs(fv.black(F, K, s, T, True) - fv.black(F, K, s, T, False) - (F - K)) < 1e-12
    h = 1e-6
    numeric = (fv.black(F, K, s + h, T) - fv.black(F, K, s - h, T)) / (2 * h)
    assert abs(fv.vega(F, K, s, T) - numeric) < 1e-6
    assert fv.black(F, K, 0.0, T) == 0.0 and fv.black(F, 50.0, 0.0, T) == F - 50.0


@pytest.mark.parametrize("premium", [False, True])
@pytest.mark.parametrize("df", [1.0, 0.97])
def test_a_strike_from_a_delta_has_that_delta(premium, df):
    F, T, s = 51.56, 0.25, 0.09
    for call in (True, False):
        for dl in (0.10, 0.25, 0.40):
            K = fv.strike_at(F, T, dl, call, None, premium, df, flat=s)
            assert abs(abs(fv.delta(F, K, s, T, call, premium, df)) - dl) < 1e-10
            assert (K > F) == call or dl > 0.35          # out-of-the-money wings
    # a smile's own delta strike: the delta with the vol at that very strike
    smile = lambda K: 0.09 + 0.4 * math.log(K / F)    # noqa: E731
    K = fv.strike_at(F, T, 0.25, True, smile, premium, df)
    assert abs(fv.delta(F, K, smile(K), T, True, premium, df) - 0.25) < 1e-10


def test_premium_adjusted_call_delta_takes_the_falling_branch():
    """(K/F)·N(d2) rises and falls with the strike: deep in the money a second strike has the same delta - never the
    one the market means."""
    F, T, s = 100.0, 1.0, 0.6
    K = fv.strike_at(F, T, 0.25, True, None, True, flat=s)
    assert K > fv.atm_strike(F, s, T, True)
    deep = [k for k in (F * x / 100 for x in range(1, 100)) if abs(fv.delta(F, k, s, T, True, True) - 0.25) < 0.01]
    assert deep and max(deep) < F          # the other strike with that delta exists, in the money


@pytest.mark.parametrize("premium", [False, True])
def test_at_the_money_is_the_delta_neutral_straddle(premium):
    F, T, s = 51.56, 0.75, 0.15
    K = fv.atm_strike(F, s, T, premium)
    assert abs(fv.delta(F, K, s, T, True, premium) + fv.delta(F, K, s, T, False, premium)) < 1e-12
    assert (K < F) == premium              # premium-adjusted: below the forward


def test_market_strangle_strikes_are_at_the_strangle_vol():
    q = quotes(USDTRY_1M, premium=True)
    kc, kp, value, vg = fv.market_strangle(q, 0.25, q.bf25)
    s = q.atm + q.bf25
    assert abs(fv.delta(q.F, kc, s, q.T, True, True) - 0.25) < 1e-10
    assert abs(fv.delta(q.F, kp, s, q.T, False, True) + 0.25) < 1e-10
    assert abs(value - fv.black(q.F, kc, s, q.T, True) - fv.black(q.F, kp, s, q.T, False)) < 1e-12 and vg > 0


# ---------------------------------------------------------------------------------------------- smiles
def _quotes_of(smile, F, T, premium):
    """The five quotes a given smile makes: ATM at the DNS strike, the risk reversals at the smile's own delta
    strikes, the butterflies as market strangles (the one vol at which the strangle costs what the smile says)."""
    def atm_vol():
        v = smile.vol(F)
        for _ in range(50):
            v = smile.vol(fv.atm_strike(F, v, T, premium))
        return v

    atm = atm_vol()
    out = {"F": F, "T": T, "atm": atm}
    for tag, dl in (("25", 0.25), ("10", 0.10)):
        kc = fv.strike_at(F, T, dl, True, smile.vol, premium)
        kp = fv.strike_at(F, T, dl, False, smile.vol, premium)
        out["rr" + tag] = smile.vol(kc) - smile.vol(kp)

        def gap(bf):
            q = fv.Quotes(F, T, atm, premium=premium)
            mc, mp, value, _ = fv.market_strangle(q, dl, bf)
            return fv.black(F, mc, smile.vol(mc), T, True) + fv.black(F, mp, smile.vol(mp), T, False) - value

        out["bf" + tag] = fv.brent(gap, -0.5 * atm + 1e-4, 0.5)
    return out


@pytest.mark.parametrize("premium", [False, True])
def test_svi_finds_the_smile_the_quotes_came_from(premium):
    F, T = 51.56, 0.5
    truth = fv.SviSmile(F, T, a=0.004, b=0.02, rho=0.35, m=0.02, s=0.08)
    q = quotes(_quotes_of(truth, F, T, premium), premium)
    smile, info = fv.build_smile(q, "svi")
    assert info["model"] == "svi"
    assert max(abs(v) for v in info["fit"].values()) < 2e-5          # well below a hundredth of a vol point
    for name, (K, v) in info["points"].items():
        assert abs(v - truth.vol(K)) < 1e-4, name


def test_svi_fits_a_g10_smile_exactly_and_without_arbitrage():
    q = quotes(EURUSD_1M, premium=False, df=math.exp(-0.02 * 30 / 365))
    smile, info = fv.build_smile(q, "svi")
    assert max(abs(v) for v in info["fit"].values()) < 1e-5
    chk = fv.Distribution(smile).check()
    assert not chk["arbitrage"] and abs(chk["mass"] - 1) < 1e-4 and abs(chk["mean_error"]) < 1e-6


def test_a_usdtry_like_smile_stays_free_of_arbitrage():
    """Mid quotes this skewed need not fit any arbitrage-free smile exactly: SVI takes the closest one - the ATM vol and
    the 25-delta quotes within a tenth of a vol point, the density nowhere negative, the mean the forward."""
    q = quotes(USDTRY_1M, premium=True)
    smile, info = fv.build_smile(q, "svi")
    fit = info["fit"]
    assert abs(fit["ATM"]) < 0.001 and abs(fit["RR25"]) < 0.001 and abs(fit["BF25"]) < 0.002
    assert max(abs(v) for v in fit.values()) < 0.01                    # under one vol point everywhere
    d = fv.Distribution(smile)
    chk = d.check()
    assert not chk["arbitrage"] and abs(chk["mean_error"]) < 1e-4 and abs(chk["mass"] - 1) < 1e-3
    qs = fv.quantiles(d)
    levels = [qs[p] for p in fv.QUANTILES]
    assert all(b > a for a, b in zip(levels, levels[1:]))
    # the skew: the 95th percentile lies much further above the median than the 5th below it
    assert qs[0.95] - qs[0.5] > 2 * (qs[0.5] - qs[0.05])


def test_sabr_cannot_follow_a_usdtry_like_smile():
    """Why SVI is the default: SABR (beta = 1) holds the ATM vol, but it misses the 25-delta risk reversal by more than
    half a vol point and its density turns negative; SVI's misses it by a thousandth of one."""
    q = quotes(USDTRY_1M, premium=True)
    svi_smile, svi = fv.build_smile(q, "svi")
    sabr_smile, sabr = fv.build_smile(q, "sabr")
    assert abs(sabr["fit"]["ATM"]) < 1e-6
    assert abs(sabr["fit"]["RR25"]) > 0.005 and abs(svi["fit"]["RR25"]) < 0.0001
    assert fv.Distribution(sabr_smile).check()["arbitrage"] and not fv.Distribution(svi_smile).check()["arbitrage"]


def test_sabr_and_vanna_volga_on_a_g10_smile():
    q = quotes(EURUSD_1M, premium=False)
    _, sabr = fv.build_smile(q, "sabr")
    assert abs(sabr["fit"]["ATM"]) < 1e-8 and max(abs(v) for v in sabr["fit"].values()) < 0.001
    smile, vv = fv.build_smile(q, "vv")
    assert max(abs(vv["fit"][k]) for k in ("ATM", "RR25", "BF25")) < 1e-8      # exact on the 25-delta quotes
    for name in ("25P", "ATM", "25C"):                                          # through its own pillars
        K, v = vv["pillars"][name]
        assert abs(smile.vol(K) - v) < 1e-12


def test_what_little_there_is():
    flat, info = fv.build_smile(quotes(EURUSD_1M, premium=False, rr25=None, bf25=None, rr10=None, bf10=None))
    assert info["model"] == "flat" and flat.vol(0.9) == flat.vol(1.3) == EURUSD_1M["atm"]
    _, info = fv.build_smile(quotes(EURUSD_1M, premium=False, rr10=None, bf10=None))
    assert info["fit"]["RR10"] is None and abs(info["fit"]["RR25"]) < 1e-5
    with pytest.raises(fv.SmileError):
        fv.build_smile(quotes(EURUSD_1M, premium=False, atm=0.0))


# ---------------------------------------------------------------------------------------------- the distribution
def test_a_flat_smile_gives_the_lognormal_law():
    F, T, s = 51.56, 0.5, 0.2
    d = fv.Distribution(fv.FlatSmile(F, T, s))
    for K in (40.0, 51.56, 60.0):
        d2 = (math.log(F / K) - 0.5 * s * s * T) / (s * math.sqrt(T))
        assert abs(d.above(K) - fv.ncdf(d2)) < 1e-15
    assert abs(d.quantile(0.5) - F * math.exp(-0.5 * s * s * T)) < 1e-9          # the lognormal median
    for p in (0.01, 0.25, 0.9):
        assert abs(d.cdf(d.quantile(p)) - p) < 1e-10
    chk = d.check()
    assert abs(chk["mean_error"]) < 1e-6 and not chk["arbitrage"]


def test_the_density_is_the_second_derivative_of_the_call():
    q = quotes(USDTRY_1M, premium=True)
    smile, _ = fv.build_smile(q)
    d = fv.Distribution(smile)
    for K in (51.0, 51.4, 52.0, 53.5):
        h = 1e-3
        c = [fv.black(q.F, k, smile.vol(k), q.T) for k in (K - h, K, K + h)]
        numeric = (c[0] - 2 * c[1] + c[2]) / (h * h)
        assert abs(d.density(K) - numeric) < 1e-3 * max(1.0, numeric)
