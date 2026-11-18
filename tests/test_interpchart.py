"""OIS · PPK's interpolation chart (18.11.2026, ``tto/interpchart.py``): "İnterpolasyonların nasıl değiştiğini gösteren,
hem normal interpolasyonla hem de bu sistemde nasıl olur, bana curve de çiz".  Between the quoted tenors both ways: the
overnight forward day by day - Bootstrap flat between Motor's nodes (the curve's own ln DF slope), PPK basamak flat
between the meetings and the quoted maturities - and the 3M FRA strip, the FRA lists' market and "PPK basamak" columns;
1Y / 3Y / 10Y, OIS / Offshore, every way sent at once; the user's own curves, kept until what they read changes.  And the
discount factors (the desk, 18.11.2026: "Bu enterpolasyondaki DF farkları da bir grafikte bana gösterilmeli"): the third
choice, "DF" - PPK basamak's discount factor against Bootstrap's, day by day, the quoted tenors marked."""
from __future__ import annotations

import math

import pytest

from conftest import cell, make_service
from tto import interpchart as ic
from tto import ppkcurve as pk
from tto.views import load_views

HORIZONS = (("1Y", 12), ("3Y", 36), ("10Y", 120))


# ================================================================================================== the lines on their own
def test_the_bootstrap_overnight_is_the_ln_df_slope_between_nodes():
    c = pk.LogLinear([0.0, 30.0, 92.0, 365.0], [0.0, -0.03, -0.09, -0.33])
    segs = ic.boot_overnight(c, 400.0, 365.0)
    assert [(a, b) for a, b, _, _ in segs] == [(0.0, 30.0), (30.0, 92.0), (92.0, 400.0)]    # past the last node: on to the end
    for i, (a, b, r, _) in enumerate(segs):
        slope = (c.lndf[i + 1] - c.lndf[i]) / (c.days[i + 1] - c.days[i])
        assert r == pytest.approx((math.exp(-slope) - 1.0) * 365.0, rel=1e-14)
        for t in range(int(a), int(b) - 1):                     # the one-day rate on every day of the stretch
            assert (c.df(float(t)) / c.df(t + 1.0) - 1.0) * 365.0 == pytest.approx(r, rel=1e-9)
    cut = ic.boot_overnight(c, 61.0, 360.0)                      # cut at the end; another day count
    assert [(a, b) for a, b, _, _ in cut] == [(0.0, 30.0), (30.0, 61.0)]
    assert cut[0][2] == pytest.approx(segs[0][2] * 360.0 / 365.0, rel=1e-14)


def test_ppk_basamak_overnight_is_flat_between_its_steps():
    curve = pk.StepCurve([0.0, 37.0, 79.0], [0.36, 0.35, 0.34]).with_shifts([(30.0, 0.001), (92.0, -0.002)])
    segs = ic.ppk_overnight(curve, 120.0)
    assert [(a, b) for a, b, _, _ in segs] == [(0.0, 30.0), (30.0, 37.0), (37.0, 79.0), (79.0, 92.0), (92.0, 120.0)]
    for a, b, r, _ in segs:                                      # a meeting, a quoted maturity: flat in between
        assert all(curve.overnight(float(t)) == r for t in range(int(a), int(b)))
    a, b, r, _ = ic.ppk_overnight(curve, 50.0, 360.0 / 365.0)[-1]
    assert (a, b) == (37.0, 50.0) and r == pytest.approx((0.35 - 0.002) * 360.0 / 365.0, rel=1e-14)


def test_a_step_line_closes_its_runs_and_leaves_a_gap_where_one_does_not_follow_on():
    x, y, what = ic.points([(0.0, 10.0, 0.30, "a"), (10.0, 20.0, 0.31, "b"), (20.0, 30.0, None, "c"),
                            (30.0, 40.0, 0.33, "d")], 100.0)
    assert x == [100.0, 110.0, 120.0, 120.0, 130.0, 140.0]
    assert y == [0.30, 0.31, 0.31, None, 0.33, 0.33]
    assert what == ["a", "b", "b", "", "d", "d"]
    assert ic.points([], 100.0) == ([], [], [])


def test_a_way_without_its_curves_says_why_and_the_others_draw():
    grid = pk.Grid(tuple(91.0 * k for k in range(1, 41)), (91.0 / 365.0,) * 40)
    cv = {"grid": grid, "boot": pk.LogLinear([0.0, 3640.0], [0.0, -3.0]), "ppk": pk.StepCurve([0.0, 100.0], [0.31, 0.29]),
          "quotes": [], "off_quotes": [], "fx_shift": 0.0, "off_ppk": None,
          "errors": ["offshore PPK basamak: XCCY 1Y kotasına oturulamadı"]}
    data, choice = ic.panel(cv, lambda sheet, r, c: 46330.0 if (sheet, r, c) == pk.OIS_SPOT else None, None)
    for h, months in HORIZONS:
        ois, off = choice["items"][h + "|OIS|Faiz"], choice["items"][h + "|Offshore|Faiz"]
        assert len(ois["data"]["series"]) == 4 and len(ois["strip"]["rows"][0]) == months // 3 + 1
        assert off["data"]["series"] == [] and off["strip"] is None and "XCCY 1Y kotasına oturulamadı" in off["line"]
        off = choice["items"][h + "|Offshore|DF"]
        assert off["data"]["series"] == [] and off["strip"] is None and "XCCY 1Y kotasına oturulamadı" in off["line"]
    assert data is choice["items"]["3Y|OIS|Faiz"]["data"]
    # a workbook without the curves' sheets: nothing read, every way says so
    nothing = ic.panel(None, lambda *a: pytest.fail("nothing is read"), None)[1]
    assert all(not it["data"]["series"] and "çizilemedi" in it["line"] for it in nothing["items"].values())


def test_the_df_view_is_ppk_against_bootstrap_day_by_day():
    """The DF view of a way: on every day from the spot, PPK basamak's ``(DF_PPK / DF_Bootstrap − 1)·10⁴`` (to 0,01 bp; the
    tooltip's difference with its sign and unit) beside Bootstrap's own line at 0, up to the horizon - or the last quote,
    past which both curves only go on: not drawn, the line says so; the quoted tenors marked (both discount factors in
    their tips), the meetings as ticks; under it a table of both discount factors and the difference at each quoted tenor
    (one with a coupon date between quotes says so).  The shorter horizons are the first days of the longest."""
    grid = pk.Grid(tuple(91.0 * k for k in range(1, 41)), (91.0 / 365.0,) * 40)
    a = 91.0 / 365.0
    quotes = [pk.Quote("1M", 0.40, (30.0,), (30.0 / 365.0,)), pk.Quote("3M", 0.39, (91.0,), (a,)),
              pk.Quote("6M", 0.385, (91.0, 182.0), (a, a)),                          # (its coupon on a quoted tenor)
              pk.Quote("1Y", 0.38, (91.0, 182.0, 273.0, 364.0), (a, a, a, a))]      # (9M: no quote)
    ppk, _ = pk.calibrate(pk.StepCurve([0.0, 40.0, 130.0, 250.0], [0.40, 0.39, 0.38, 0.37]), quotes)
    boot = pk.LogLinear([0.0, 30.0, 91.0, 182.0, 364.0], [-ppk.lng(t) * 0.999 for t in (0.0, 30.0, 91.0, 182.0, 364.0)])
    cv = {"grid": grid, "boot": boot, "ppk": ppk, "quotes": quotes, "off_quotes": [], "fx_shift": 0.0, "off_ppk": None,
          "errors": []}
    meets = [(40.0, "MPC1", 46370.0), (130.0, "MPC2", 46460.0), (500.0, "MPC5", 46830.0)]
    it = ic.df_view(cv, None, meets, 46330.0, "1Y", "OIS", None)
    d = it["data"]
    ref, line = d["series"]
    assert [s["name"] for s in d["series"]] == ["DF · Bootstrap (Murex)", "DF · PPK basamak"] and d["y_title"].startswith("bp")
    assert (ref["x"], ref["data"], ref["step"]) == ([46330, 46694], [0.0, 0.0], 1) and "step" not in line
    assert line["x"] == list(range(46330, 46695))
    assert line["data"] == [round((ppk.df(float(t)) / boot.df(float(t)) - 1) * 1e4, 2) + 0.0 for t in range(365)]
    assert d["tipdiff"] == [{"a": 1, "b": 0, "name": "PPK / Bootstrap − 1", "scale": 1, "digits": 2, "unit": "bp"}]
    marks = [m for m in d["vmarks"] if m.get("k") != "tick"]
    assert [m["t"] for m in marks] == ["1M", "3M", "6M", "1Y"] and [m["x"] - 46330 for m in marks] == [30.0, 91.0, 182.0, 364.0]
    assert "DF Bootstrap (Murex) " in marks[0]["tip"] and "aynı" in marks[2]["tip"] and "kotasız kupon" in marks[3]["tip"]
    assert [m["x"] - 46330 for m in d["vmarks"] if m.get("k") == "tick"] == [40.0, 130.0]
    rows = it["strip"]["rows"]
    assert [c["t"] for c in rows[0][1:]] == ["1M", "3M", "6M", "1Y"] and [r[0]["t"] for r in rows[1:]] == \
        ["Bootstrap (Murex)", "PPK basamak", "PPK / Bootstrap − 1 (bp)"]
    for j, q in enumerate(quotes, 1):
        assert (rows[1][j]["v"], rows[2][j]["v"]) == (boot.df(q.end), ppk.df(q.end))
        assert rows[3][j]["v"] == pytest.approx((ppk.df(q.end) / boot.df(q.end) - 1) * 1e4, abs=1e-12)
    assert "arada kotasız kupon tarihi" in rows[0][4]["tip"] and "kotasız" not in rows[0][3]["tip"]
    assert it["line"].startswith("1Y · OIS · DF farkı (PPK basamak / Bootstrap − 1): en yüksek ")
    assert "kotalı vadede aynı: 1M, 3M, 6M" in it["line"] and "arada kotasız kuponu olan kotada: 1Y " in it["line"]
    # 3Y: past the last quote (1Y) nothing is drawn; worked out once for every horizon
    memo = {}
    long = ic.df_view(cv, None, meets, 46330.0, "3Y", "OIS", None, memo)
    assert long["data"]["series"][1]["x"][-1] == 46694 and "Son kota 1Y (" in long["line"] and long["line"].endswith("çizilmedi")
    assert ic.df_view(cv, None, meets, 46330.0, "1Y", "OIS", None, memo) == it and len(memo["OIS"]) == 365


# ================================================================================================== on the page
def chart_of(svc, user):
    page = svc.view(user, "ois")
    return next(p for p in page["panels"] if p["id"] == "interp"), page


def curves(svc, user=None):
    book = svc.books["tto"]
    return svc.et.call(lambda: svc._try_curves(book, svc._calc(user, book)))


def offshore(svc, user=None):
    """The offshore curve as the sheet has it (Forward!AK124:AK143 days, AM124:AM143 ln DF)."""
    return pk.LogLinear([cell(svc, "Forward!AK%d" % r, user) for r in range(124, 144)],
                        [cell(svc, "Forward!AM%d" % r, user) for r in range(124, 144)])


def test_the_chart_is_beside_the_fra_lists_and_nothing_else_on_the_page_moves(service):
    u = service.login("Eğri grafiği sayfa")["user"]
    p, page = chart_of(service, u)
    view = next(v for v in load_views() if v["id"] == "ois")
    defined = [x["id"] for x in view["panels"] if not x.get("hidden")]
    assert [x["id"] for x in page["panels"] if x["id"] in defined] == defined
    best = next(s for s in page["sections"] if s["id"] == "best")
    assert best["panels"] == ["B9", "B10", "B11", "interp", "chart2", "chart5"]               # right after the 15 best FRAs
    assert [(s["id"], s["panels"]) for s in page["sections"] if s["id"] != "best"] == \
        [(s["id"], s["panels"]) for s in view["sections"] if s["id"] != "best"]
    assert not any(x.get("choice") or x.get("full") for x in page["panels"] if x["id"] != "interp")
    assert p["type"] == "chart" and p["wide"] and p["full"] and "error" not in p
    assert p["title"] == "İnterpolasyon · Bootstrap (Murex) ve PPK basamak"
    assert "12x15 −70,7 bp, 15x18 +78,8 bp, 12x18 aynı" in p["note"] and "aynen fiyatlar" in p["note"]
    # every way at once: 1Y / 3Y / 10Y × OIS / Offshore × rates / discount factors, the page opening on 3Y OIS's rates
    # (what a launchpad draws too; a browser that kept "3Y|OIS" of before opens on the same)
    ch = p["choice"]
    assert [g["options"] for g in ch["groups"]] == [["1Y", "3Y", "10Y"], ["OIS", "Offshore"], ["Faiz", "DF"]]
    assert [g["default"] for g in ch["groups"]] == ["3Y", "OIS", "Faiz"] and [g["id"] for g in ch["groups"]][2] == "gorunum"
    assert list(ch["items"]) == ["%s|%s|%s" % (h, c, v) for h, _ in HORIZONS for c in ("OIS", "Offshore") for v in ("Faiz", "DF")]
    assert p["data"] == ch["items"]["3Y|OIS|Faiz"]["data"]


def test_each_horizon_and_curve(service):
    """Each way from the curve's spot to the quarterly calendar's day at the horizon: four step lines (O/N and the strip,
    both ways), the strip an FRA a quarter, its table under the chart, the quoted tenors and the meetings marked."""
    u = service.login("Eğri grafiği ufuk")["user"]
    p, _ = chart_of(service, u)
    cv = curves(service, u)
    spot = cell(service, "OIS_MAIN!B2", u)
    meets = [cell(service, "Motor!C%d" % r, u) for r in range(5, 85)]
    names = {"OIS": ["O/N · Bootstrap (Murex)", "O/N · PPK basamak", "3A FRA · Bootstrap (Murex)", "3A FRA · PPK basamak"],
             "Offshore": ["O/N · Bootstrap (offshore)", "O/N · PPK basamak (offshore)", "3A forward · Bootstrap (offshore)",
                          "3A forward · PPK basamak (offshore)"]}
    for h, months in HORIZONS:
        end = cv["grid"].days[months // 3 - 1]
        for c in ("OIS", "Offshore"):
            it = p["choice"]["items"]["%s|%s|Faiz" % (h, c)]
            d = it["data"]
            origin = spot + (0.0 if c == "OIS" else cv["fx_shift"])
            assert d["scatter"] and d["xaxis"]["type"] == "date" and d["unit"] == "pct"
            assert d["y_title"] == ("%, ACT/365" if c == "OIS" else "%, ACT/360")
            assert [s["name"] for s in d["series"]] == names[c]
            for s in d["series"]:
                assert s["step"] == 1 and len(s["x"]) == len(s["data"]) and s["x"] == sorted(s["x"])
                assert s["x"][0] == origin and s["x"][-1] == spot + end and None not in s["data"]
            quarters = ["%dx%d" % (3 * k, 3 * k + 3) for k in range(months // 3)]
            assert d["series"][2]["tips"][:-1] == quarters == [x["t"] for x in it["strip"]["rows"][0][1:]]
            assert [r[0]["t"] for r in it["strip"]["rows"][1:]] == \
                [n[len("O/N · "):] for n in names[c][:2]] + ["PPK − Bootstrap (bp)"]
            assert it["line"].startswith("%s · %s · " % (h, c))
            # the quoted tenors within the horizon (15M / 21M are not quotes) and the meetings ahead, at their effective day
            quotes = cv["quotes"] if c == "OIS" else cv["off_quotes"]
            lines = [m for m in d["vmarks"] if m.get("k") != "tick"]
            assert [m["t"] for m in lines] == [q.name.split(" ")[-1] for q in quotes if q.end <= end - (origin - spot)]
            assert [m["x"] - origin for m in lines] == [q.end for q in quotes if q.end <= end - (origin - spot)]
            ticks = [m["x"] - spot for m in d["vmarks"] if m.get("k") == "tick"]
            assert ticks == [x for x in meets if 0 < x < min(end, 99999)] and ticks
    assert "15M" not in [m.get("t") for m in p["choice"]["items"]["10Y|OIS|Faiz"]["data"]["vmarks"]]
    assert "MPC1 toplantısı " in next(m["tip"] for m in p["data"]["vmarks"] if m.get("k") == "tick")


def test_the_bootstrap_overnight_forward_is_the_curves_own_ln_df_slope(service):
    """Bootstrap's O/N: a step at each node of the curve (Motor's on OIS, the Forward sheet's offshore), the one-day rate
    of its ln DF slope in between - the offshore curve's last stretch going on past its last node, as the sheet's does."""
    u = service.login("Eğri grafiği bootstrap")["user"]
    p, _ = chart_of(service, u)
    cv = curves(service, u)
    spot = cell(service, "OIS_MAIN!B2", u)
    for c, curve, shift, basis in (("OIS", cv["boot"], 0.0, 365.0), ("Offshore", offshore(service, u), cv["fx_shift"], 360.0)):
        s = p["choice"]["items"]["10Y|%s|Faiz" % c]["data"]["series"][0]
        days = [x - spot - shift for x in s["x"]]
        assert days[:-1] == [d for d in curve.days[:-1] if d < days[-1]]
        for i, r in enumerate(s["data"][:-1]):
            k = curve.days.index(days[i])
            slope = (curve.lndf[k + 1] - curve.lndf[k]) / (curve.days[k + 1] - curve.days[k])
            assert r == pytest.approx((math.exp(-slope) - 1.0) * basis, rel=1e-13)
            t = days[i] + 1.0                                     # (a day inside the stretch, read off the curve itself)
            assert (curve.df(t) / curve.df(t + 1.0) - 1.0) * basis == pytest.approx(r, rel=1e-9)
        assert s["data"][-1] == s["data"][-2]                     # (the closing point)


def test_ppk_basamak_steps_at_the_meetings_and_quoted_maturities_flat_between(service):
    u = service.login("Eğri grafiği basamak")["user"]
    p, _ = chart_of(service, u)
    cv = curves(service, u)
    spot = cell(service, "OIS_MAIN!B2", u)
    meets = {cell(service, "Motor!C%d" % r, u) for r in range(5, 85)}
    for c, curve, quotes, shift, scale in (("OIS", cv["ppk"], cv["quotes"], 0.0, 1.0),
                                           ("Offshore", cv["off_ppk"], cv["off_quotes"], cv["fx_shift"], 360.0 / 365.0)):
        s = p["choice"]["items"]["10Y|%s|Faiz" % c]["data"]["series"][1]
        days = [x - spot - shift for x in s["x"]]
        steps = set(days[:-1])
        assert steps <= {m - shift for m in meets} | {q.end for q in quotes} | {0.0}       # a meeting or a quoted maturity
        assert {m - shift for m in meets if 0 < m - shift < days[-1]} <= steps                # every meeting ahead is one
        for (d0, r), d1 in zip(zip(days, s["data"]), days[1:]):
            assert all(curve.overnight(float(t)) * scale == r for t in range(int(d0), int(d1)))
        assert len(set(s["data"])) > 20                                                      # (it moves)


def test_both_fra_strips_are_the_fra_lists_market_and_ppk_columns(service):
    """The OIS strip on the same quarters as *TÜM FORWARD / FRA*'s 3M FRAs: Bootstrap its market (OIS_MAIN!B), PPK basamak
    its "PPK basamak" column, the difference its "PPK fark" (text too); offshore the two offshore curves' 3M forward
    rates on the same quarters, simple ACT/360."""
    u = service.login("Eğri grafiği FRA")["user"]
    p, page = chart_of(service, u)
    cv = curves(service, u)
    b21 = next(x for x in page["panels"] if x["id"] == "B21")["data"]
    rows = {r: row for r, row in zip(b21["r"], b21["rows"])}
    col = b21["c"].index("PPK basamak")
    by_months = {}
    for r in range(336, 439):
        by_months.setdefault((int(cell(service, "OIS_MAIN!M%d" % r, u)), int(cell(service, "OIS_MAIN!N%d" % r, u))), r)
    it = p["choice"]["items"]["10Y|OIS|Faiz"]
    sb, sp = it["data"]["series"][2], it["data"]["series"][3]
    table = it["strip"]["rows"]
    checked = 0
    for k in range(40):
        r = by_months.get((3 * k, 3 * k + 3))
        if r is None:
            continue
        market = cell(service, "OIS_MAIN!B%d" % r, u)
        assert sb["data"][k] == pytest.approx(market, abs=1e-14) and sb["tips"][k] == "%dx%d" % (3 * k, 3 * k + 3)
        assert sp["data"][k] == rows[r][col]["v"]
        assert table[1][k + 1]["v"] == sb["data"][k] and table[2][k + 1]["v"] == sp["data"][k]
        assert table[3][k + 1]["v"] == pytest.approx((sp["data"][k] - market) * 1e4, abs=1e-9)
        assert table[3][k + 1]["t"] == rows[r][col + 1]["t"] and table[3][k + 1].get("c") == rows[r][col + 1].get("c")
        checked += 1
    assert checked == 40
    # the 3Y and 1Y strips: the first quarters of the same
    for h, months in HORIZONS[:2]:
        short = p["choice"]["items"]["%s|OIS|Faiz" % h]["data"]["series"]
        assert short[2]["data"][:-1] == sb["data"][:months // 3] and short[3]["data"][:-1] == sp["data"][:months // 3]
    off, shift, grid = offshore(service, u), cv["fx_shift"], cv["grid"]
    ob, op = (p["choice"]["items"]["10Y|Offshore|Faiz"]["data"]["series"][k] for k in (2, 3))
    for k in range(40):
        a, b = (grid.days[k - 1] - shift if k else 0.0), grid.days[k] - shift
        assert ob["data"][k] == pytest.approx(pk.forward(off, a, b, 360.0), abs=1e-14)
        assert op["data"][k] == pytest.approx(pk.forward(cv["off_ppk"], a, b, 360.0), abs=1e-14)


def test_the_df_view_of_each_way(service):
    """The DF view on the page, out of the user's own curves: PPK basamak's discount factor against Bootstrap's on every day
    from the curve's spot to the horizon (or the last quote) - OIS Motor's bootstrap and the PPK step curve, offshore the
    Forward sheet's curve and the offshore PPK curve.  At a quoted tenor whose cash flows are all on quoted tenors the two
    are the same (OIS 1M … 1Y: zero-coupon, then quarterly coupons on quotes; every offshore quote: TRYI one period, XCCY
    yearly coupons on the XCCY quotes); at OIS's coupon quotes from 18M (15M, 21M … no quotes) they part.  The table's
    discount factors are the curves' own; the rates' views are as they were (the tests above)."""
    u = service.login("Eğri grafiği DF")["user"]
    p, _ = chart_of(service, u)
    cv = curves(service, u)
    off = offshore(service, u)
    spot = cell(service, "OIS_MAIN!B2", u)
    parted = []
    for h, months in HORIZONS:
        for c, boot, ppk, quotes, shift in (("OIS", cv["boot"], cv["ppk"], cv["quotes"], 0.0),
                                            ("Offshore", off, cv["off_ppk"], cv["off_quotes"], cv["fx_shift"])):
            it = p["choice"]["items"]["%s|%s|DF" % (h, c)]
            ref, line = it["data"]["series"]
            end = cv["grid"].days[months // 3 - 1] - shift
            last = max(q.end for q in quotes)
            n = int(min(end, last))
            assert line["x"] == [spot + shift + t for t in range(n + 1)] and ref["data"] == [0.0, 0.0]
            for t in list(range(0, n + 1, 37)) + [n]:
                assert line["data"][t] == pytest.approx((ppk.df(float(t)) / boot.df(float(t)) - 1) * 1e4, abs=0.0051), (h, c, t)
            rows = it["strip"]["rows"]
            shown = [q for q in sorted(quotes, key=lambda q: q.end) if q.end <= n]
            assert [x["t"] for x in rows[0][1:]] == [q.name.split(" ")[-1] for q in shown]
            for j, q in enumerate(shown, 1):
                assert (rows[1][j]["v"], rows[2][j]["v"]) == (boot.df(q.end), ppk.df(q.end))
                pinned = c == "Offshore" or q.end <= 366
                assert (abs(rows[3][j]["v"]) < 1e-6) == pinned, (h, c, q.name, rows[3][j]["v"])
                parted += [] if pinned else [abs(rows[3][j]["v"])]
            assert it["line"].startswith("%s · %s · DF farkı (PPK basamak / Bootstrap − 1): en yüksek " % (h, c))
            assert ("çizilmedi" in it["line"]) == (last < end)
    assert parted and max(parted) > 0.5


def test_on_the_replay_day_and_the_users_own_curves(tmp_path, monkeypatch):
    """The day the desk asked on (the replay, 03.11.2026): over 3Y the strip parts most at 15x18 (+78,8 bp on the PPK
    steps) and 12x15 (−70,7 bp), the same up to 9x12 - both ends quoted; offshore past the last XCCY quote (5Y) both lines
    only go on.  The chart is the user's own calculation: a quote typed over moves this user's lines only, and the
    chart is made again only when what it read changed."""
    svc = make_service(tmp_path)
    try:
        u, w = svc.login("Grafik A")["user"], svc.login("Grafik B")["user"]
        made = []
        real = ic.panel
        monkeypatch.setattr(ic, "panel", lambda *a: made.append(1) or real(*a))
        p, _ = chart_of(svc, u)
        it = p["choice"]["items"]["3Y|OIS|Faiz"]
        diff = {head["t"]: x["v"] for head, x in zip(it["strip"]["rows"][0][1:], it["strip"]["rows"][3][1:])}
        assert -71.5 < diff["12x15"] < -70.0 and 78.0 < diff["15x18"] < 79.5
        assert max(diff, key=lambda k: abs(diff[k])) == "15x18"
        assert all(abs(diff[k]) < 1e-6 for k in ("0x3", "3x6", "6x9", "9x12"))
        assert "en çok 15x18 +78,8 bp · 12x15 -70,7 bp" in it["line"] and "0x3, 3x6, 6x9, 9x12" in it["line"]
        assert "Son kota XCCY 5Y (04.11.2031): sonrası iki eğride de uzatma" in p["choice"]["items"]["10Y|Offshore|Faiz"]["line"]
        # the discount factors: over 3Y PPK basamak's is up to 17,5 bp above Bootstrap's and 15,0 bp below, the same at the
        # quoted tenors up to 1Y, −1,47 / −0,27 / +2,40 bp at 18M / 2Y / 3Y; offshore the same at every quote, up to 5Y
        df = p["choice"]["items"]["3Y|OIS|DF"]
        at = {head["t"]: x["v"] for head, x in zip(df["strip"]["rows"][0][1:], df["strip"]["rows"][3][1:])}
        assert all(abs(at[k]) < 1e-6 for k in ("1M", "2M", "3M", "6M", "9M", "1Y"))
        assert [round(at[k], 2) for k in ("18M", "2Y", "3Y")] == [-1.47, -0.27, 2.4]
        assert "en yüksek +17,49 bp (21.01.2028), en düşük -14,97 bp (04.08.2028)" in df["line"]
        off = p["choice"]["items"]["10Y|Offshore|DF"]
        assert off["data"]["series"][1]["x"][-1] - off["data"]["series"][1]["x"][0] == 1826
        assert "Son kota XCCY 5Y (04.11.2031): sonrası iki eğride de uzatma, çizilmedi" in off["line"]
        n = len(made)
        assert n >= 1 and chart_of(svc, u)[0] == p and len(made) == n                # kept: nothing it read changed
        assert svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!B14", "value": "36,55%"}], allow_adhoc=True)["errors"] == []
        mine, _ = chart_of(svc, u)
        assert len(made) > n and mine["choice"]["items"]["3Y|OIS|Faiz"]["strip"] != it["strip"]
        cv = curves(svc, u)
        fra = mine["choice"]["items"]["3Y|OIS|Faiz"]["data"]["series"][3]["data"]
        assert fra[4] == pytest.approx(pk.fra(cv["ppk"], cv["grid"], 12, 15), abs=1e-15)    # (12x15 on this user's curve)
        assert chart_of(svc, w)[0]["choice"] == p["choice"]                                   # another user: as it was
    finally:
        svc.stop()


def test_a_user_on_ppk_basamak_sees_the_true_bootstrap_beside_their_ppk(tmp_path):
    """(where the chart meets Ayarlar's "Eğri interpolasyonu", 18.11.2026) For a user whose own setting is PPK basamak -
    Motor's nodes are PPK for them - the chart still draws the true Bootstrap (Murex) next to PPK basamak: every series,
    every horizon, OIS and offshore, as a user on Bootstrap sees it."""
    svc = make_service(tmp_path)
    try:
        on_ppk, on_boot = svc.login("Grafik PPK")["user"], svc.login("Grafik Bootstrap")["user"]
        svc.set_interp(on_ppk, "ppk")
        assert cell(svc, "EK_INTERP!B3", on_ppk) == 1.0 and cell(svc, "EK_INTERP!B3", on_boot) == 0.0
        # (the user's own curve is PPK: the FRA list's market for 12x15 is their PPK column, not the bootstrap's)
        assert cell(svc, "OIS_MAIN!B340", on_ppk) != cell(svc, "OIS_MAIN!B340", on_boot)
        a, b = chart_of(svc, on_ppk)[0]["choice"]["items"], chart_of(svc, on_boot)[0]["choice"]["items"]
        assert set(a) == set(b) and len(a) == 12
        for key in a:
            sa, sb = a[key]["data"]["series"], b[key]["data"]["series"]
            assert [s["name"] for s in sa] == [s["name"] for s in sb]
            for x, y in zip(sa, sb):
                assert x["x"] == y["x"] and x["data"] == pytest.approx(y["data"], abs=1e-12), (key, x["name"])
    finally:
        svc.stop()
