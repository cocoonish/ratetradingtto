"""Lead-lag (tto/quantlead.py): the F distribution's tail, a planted lag found with its β both ways, nothing found
between independent or same-day series, the rule's history, a signal on a follower that has not caught up (and none
when the leader did not move), the intraday adapter on bars at minute lags, then the service, the HTTP API and the
page on a synthetic two-year history with a planted lead."""
from __future__ import annotations

import datetime as dt
import random
import types

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from tto import quantfam as qf
from tto import quantlead as ql
from tto.quant import DEFAULTS, PAGES
from tto.server import create_app

TODAY = dt.date(2026, 11, 3)


def lagged(n, lag, beta, noise, seed):
    """Changes: x white noise, y = β·x(t − lag) + noise."""
    rnd = random.Random(seed)
    dx = [rnd.gauss(0, 1.0) for _ in range(n)]
    dy = [beta * (dx[t - lag] if t >= lag else 0.0) + rnd.gauss(0, noise) for t in range(n)]
    return dx, dy


def levels(start, bp_changes):
    out, v = [], start
    for c in bp_changes:
        v += c / 100.0
        out.append(v)
    return out


def test_the_f_distribution_s_tail():
    assert abs(ql.f_sf(4.17, 1, 30) - 0.05) < 1e-3 and abs(ql.f_sf(2.30, 5, 100) - 0.05) < 2e-3
    assert abs(ql.f_sf(3.0, 2, 50) - 0.05878) < 2e-4 and ql.f_sf(0.0, 3, 40) == 1.0 and ql.f_sf(50.0, 1, 200) < 1e-10
    assert abs(ql.betainc(1.0, 3.0, 0.2) - (1 - 0.8 ** 3)) < 1e-12                        # I_x(1, b) = 1 − (1 − x)^b
    assert abs(ql.betainc(2.5, 1.5, 0.3) + ql.betainc(1.5, 2.5, 0.7) - 1.0) < 1e-12      # I_x(a, b) = 1 − I_1−x(b, a)


def test_a_planted_lag_is_found_with_its_beta_both_ways():
    dx, dy = lagged(600, 2, 0.6, 0.5, 1)
    res = ql.lead_lag(dx, dy, 5, 2.0)
    assert res["leader"] == "x" and res["lag"] == 2 and abs(res["beta"] - 0.6) < 0.08 and res["p"] < 1e-6
    assert res["stable"] == "3/3" and res["xcorr"][2] > 0.6 and abs(res["xcorr"][0]) < 0.15 and abs(res["b"][2] - 0.6) < 0.08
    back = ql.lead_lag(dy, dx, 5, 2.0)                                     # the same pair the other way round
    assert back["leader"] == "y" and back["lag"] == 2 and abs(back["beta"] - 0.6) < 0.08
    ev = res["events"]                                                     # after the leader's 2σ moves the follower went along
    assert ev["n"] >= 10 and ev["hit_rate"] >= 0.7 and 0.6 < ev["ratio"] < 1.4
    # a lead only in the last stretch does not hold over 250 days
    rnd = random.Random(9)
    early = [rnd.gauss(0, 1) for _ in range(190)]
    mixed_x = early + dx[-70:]
    mixed_y = [rnd.gauss(0, 1) for _ in range(190)] + dy[-70:]
    st = {s["window"]: s["ok"] for s in ql.stability(mixed_x, mixed_y, 2, 1)}
    assert st[60] is True and st[250] is False


def test_nothing_is_found_between_independent_or_same_day_series():
    found = 0
    for seed in range(20):
        rnd = random.Random(100 + seed)
        dx = [rnd.gauss(0, 1) for _ in range(400)]
        dy = [rnd.gauss(0, 1) for _ in range(400)]
        found += ql.lead_lag(dx, dy, 5, 2.0)["leader"] is not None
    assert found <= 2                                                      # (5 % over five lags, and Granger as well)
    rnd = random.Random(7)
    dx = [rnd.gauss(0, 1) for _ in range(500)]
    same = [0.8 * v + rnd.gauss(0, 0.4) for v in dx]                      # the same day, together: nobody leads
    res = ql.lead_lag(dx, same, 5, 2.0)
    assert res["leader"] is None and res["xcorr"][0] > 0.8


def test_noisy_co_movers_and_a_mean_reverting_spread_have_no_leader():
    """The same quotes with noise of their own, or around a spread that mean-reverts: each one's lags "help" the
    other in a Granger test (they rebuild the other's noise), the cross-correlations stay symmetric - nobody leads."""
    for seed in (31, 32):
        rnd = random.Random(seed)
        common = levels(30.0, [rnd.gauss(0, 5) for _ in range(500)])
        noisy = [c + rnd.gauss(0, 0.03) for c in common]
        s, spread = 0.0, []
        for _ in common:
            s = 0.8 * s + rnd.gauss(0, 0.05)
            spread.append(s)
        for other in (noisy, [c + x for c, x in zip(common, spread)]):
            res = ql.lead_lag(ql.changes("rate", common), ql.changes("rate", other), 5, 2.0)
            assert min(res["granger_xy"]["p"], res["granger_yx"]["p"]) < 0.05           # Granger alone would name a leader
            assert res["leader"] is None and res["why"].startswith("öncü yok") and abs(res["asym"]["z"]) < ql.z_lead(5)
    assert abs(ql.z_lead(5) - 2.576) < 1e-3 and abs(ql.z_lead(1) - 1.960) < 1e-3


def _ctx(lead, follow, days, live=None, **cfg):
    meta = {"OIS:1Y": {"label": "1Y OIS", "kind": "rate", "months": 12.0}, "OIS:2Y": {"label": "2Y OIS", "kind": "rate", "months": 24.0}}
    settings = dict(DEFAULTS)
    settings.update(cfg)
    return qf.Ctx(settings, TODAY, {"OIS:1Y": dict(zip(days, lead)), "OIS:2Y": dict(zip(days, follow))}, meta, live=live or {})


def test_a_follower_that_has_not_caught_up_is_a_signal():
    days = quant_synth.business_days(TODAY, 400)
    dx, dy = lagged(len(days), 2, 0.7, 0.5, 3)
    lead, follow = levels(30.0, [4.0 * v for v in dx]), levels(29.0, [4.0 * v for v in dy])     # bp a day: σ 4
    for series in (lead, follow):                                          # the last three closes flat
        series[-1] = series[-2] = series[-3]
    quiet = _ctx(lead, follow, days)
    mons, tables = [], {}
    ql.run(types.SimpleNamespace(svc=None), quiet, mons, tables)
    row = next(r for r in tables["lead"]["rows"] if r["group"] == "Eğri içi")
    assert row["leader"] == "OIS:1Y" and row["follower"] == "OIS:2Y" and row["lag"] == 2 and abs(row["beta"] - 0.7) < 0.1
    assert tables["lead"]["intraday"] == {"ok": False, "why": "gün içi barlar yok", "rows": []}
    m = mons[0]
    m.score({}, {})
    assert m.z is None and qf.make_signal(m, quiet.cfg, "10:00") is None   # the leader did not move: no signal
    # today the leader is 30 bp up (over the last three days: 4σ·√3 ≈ 28), the follower has not moved
    ctx = _ctx(lead, follow, days, live={"OIS:1Y": lead[-1] + 0.30, "OIS:2Y": follow[-1]})
    mons, tables = [], {}
    ql.run(types.SimpleNamespace(svc=None), ctx, mons, tables)
    m = mons[0]
    m.score(ctx.live, ctx.live)
    now = m.now
    assert now["event"] and abs(now["lead_move"] - 30.0) < 1e-6 and abs(now["follow_move"]) < 1e-9
    assert abs(now["catch_up"] - m.row["beta"] * 30.0) < 1e-9 and now["z"] > 2.0
    s = qf.make_signal(m, ctx.cfg, "10:00")
    assert s["family"] == "leadlag" and s["page"] == "quant-lead" and s["direction"] == 1 and s["expression"] == "Pay 2Y OIS (1Y OIS öncülüğünde)"
    assert s["legs"][0]["key"] == "OIS:2Y" and s["legs"][0]["text"] == "Pay 2Y OIS" and s["unit"] == "%"
    assert abs(s["entry"] - follow[-1]) < 1e-12 and abs((s["target"] - s["entry"]) * 100.0 - now["catch_up"]) < 1e-9
    assert abs((s["entry"] - s["stop"]) * 100.0 - now["sigma"]) < 1e-9 and "bekleniyor" in s["note"] and "isabet" in s["note"]
    assert not s["gated"] and m.row["stable"] == "3/3"
    # a lead that does not hold in every window is shown, gated
    shaky = dict(m.row, stability=[{"window": 60, "ok": True}, {"window": 120, "ok": False}, {"window": 250, "ok": None}], stable="1/2")
    gm = ql.LeadMonitor(ctx, shaky, 2.0)
    gm.score(ctx.live, ctx.live)
    gs = qf.make_signal(gm, ctx.cfg, "10:00")
    assert gs["gated"].startswith("öncülük her pencerede tutmuyor") and gs["composite"] == 0.0
    # the score day by day for the chart: the catch-up's z on the days the leader had moved
    hist = m.history()
    assert len(hist["z"]) == len(hist["days"]) and any(z is not None for z in hist["z"])
    # a follower that already followed: nothing left to catch up
    done = _ctx(lead, follow, days, live={"OIS:1Y": lead[-1] + 0.30, "OIS:2Y": follow[-1] + m.row["beta"] * 0.30})
    mons, tables = [], {}
    ql.run(types.SimpleNamespace(svc=None), done, mons, tables)
    mons[0].score(done.live, done.live)
    assert abs(mons[0].now["catch_up"]) < 1e-9 and qf.make_signal(mons[0], done.cfg, "10:00") is None


def test_intraday_runs_on_bars_at_minute_lags():
    pairs = [("OIS:1Y", "OIS:2Y", "Eğri içi")]
    assert ql.intraday(None, pairs, {}, 2.0) == {"ok": False, "why": "gün içi barlar yok", "rows": []}
    dx, dy = lagged(900, 3, 0.8, 0.3, 4)                                  # 1-minute bars: the follower three bars later
    t0 = dt.datetime(2026, 11, 3, 9, 30)
    times = [t0 + dt.timedelta(minutes=i) for i in range(900)]
    bars = {"OIS:1Y": levels(30.0, dx), "OIS:2Y": levels(29.0, dy)}

    def source(key, minutes):
        if key not in bars:
            return None
        return times[::minutes], bars[key][::minutes]

    svc = types.SimpleNamespace(bars=types.SimpleNamespace(series=source))
    assert ql.bar_source(svc) is source and ql.bar_source(types.SimpleNamespace()) is None
    out = ql.intraday(ql.bar_source(svc), pairs + [("OIS:1Y", "OIS:5Y", "Eğri içi")], {"OIS:1Y": "rate", "OIS:2Y": "rate"}, 2.0)
    one = next(r for r in out["rows"] if r["minutes"] == 1)
    assert out["ok"] and one["leader"] == "OIS:1Y" and one["follower"] == "OIS:2Y" and one["lag"] == 3 and abs(one["beta"] - 0.8) < 0.1
    assert {r["minutes"] for r in out["rows"]} == {1, 5}                  # (the 5Y has no bars: left out)


# ================================================================================================ the service
@pytest.fixture(scope="module")
def leadsvc(module_service):
    """The two-year synthetic history with the 5Y OIS following the 1Y two days later."""
    svc = module_service
    svc.quant.use_live = False
    days, data = quant_synth.seed(svc)
    one = [data["OIS:1Y"][d] for d in days]
    rnd = random.Random(21)
    five = [one[0] + 0.5]
    for t in range(1, len(days)):
        move = (one[t - 2] - one[t - 3]) * 0.8 if t >= 3 else 0.0
        five.append(five[-1] + move + rnd.gauss(0, 0.02))
    ref = next(d for d in svc.history.snapshot()["defs"] if d.group == "ois" and d.label.strip().upper() == "5Y")
    for sid in ref.ids():
        svc.store.hist_delete(sid)
    svc.store.hist_upsert(ref.id, list(zip(days, five)))
    svc.history.rev += 1
    svc.quant.compute()
    return svc


def test_the_service_scans_every_candidate_pair_and_finds_the_planted_lead(leadsvc):
    svc = leadsvc
    st = svc.quant.status()
    assert st["ready"] and not st["errors"] and "lead" in st["timing"]
    user = svc.login("öncü okuyucu")["user"]
    v = svc.quant.view("lead", user, {})
    rows = v["lead"]["rows"]
    assert {"Offshore ↔ OIS", "Swap puanı ↔ OIS", "Kur ↔ OIS ön uç", "Eğri içi"} <= {r["group"] for r in rows}
    planted = next(r for r in rows if r["x"] == "OIS:1Y" and r["y"] == "OIS:5Y")
    assert planted["leader"] == "OIS:1Y" and planted["follower"] == "OIS:5Y" and planted["lag"] == 2 and abs(planted["beta"] - 0.8) < 0.15
    assert planted["sid"] == "leadlag:OIS:1Y|OIS:5Y" and planted["stable"] == "3/3" and planted["n"] >= 240
    assert planted["xcorr"]["2"] > 0.5 and abs(planted["xcorr"]["0"]) < 0.3                  # (the cross-correlations reach the page)
    assert all(r.get("leader") or r.get("why") for r in rows)
    assert v["lead"]["intraday"]["why"] == "gün içi barlar yok" and v["coverage"]
    one = svc.quant.view("signal", user, {"id": "leadlag:OIS:1Y|OIS:5Y"})
    assert one["monitor"]["family"] == "leadlag" and len(one["history"]["z"]) == len(one["history"]["days"])
    assert any(f["id"] == "leadlag" for f in svc.quant.view("signals", user, {})["families"])


def test_lead_http_api_and_the_page(leadsvc):
    svc = leadsvc
    with TestClient(create_app(svc), headers=auth(svc, "Öncü HTTP")) as client:
        r = client.get("/api/quant/lead")
        assert r.status_code == 200 and r.json()["ready"] and r.json()["lead"]["rows"] and r.json()["mode"] == "replay"
        assert client.post("/api/quant/settings", json={"values": {"lead_k": "0,1"}}).status_code == 400
        res = client.post("/api/quant/settings", json={"values": {"lead_k": "2,5", "lead_lag": "4"}})
        assert res.status_code == 200 and res.json()["values"]["lead_k"] == 2.5 and res.json()["values"]["lead_lag"] == 4
        client.post("/api/quant/settings", json={"values": {"lead_k": "2", "lead_lag": "5"}})
        nav = client.get("/api/nav").json()["pages"]
        assert "quant-lead" in [p["id"] for p in nav if p["group"] == "Quant"] and ("quant-lead", "Öncü-Takipçi") in PAGES
        assert client.get("/static/js/pages/quantlead.js").status_code == 200
        assert client.get("/api/quant/lead", headers={"Authorization": ""}).status_code == 401
