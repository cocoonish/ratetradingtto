"""Toplu iş 28.11.2026 - the quant part (builder K7; the desk: "A - Yildizlilari yap. B - Hepsini yap. C - 2-3-4-5-8-10-12-13-16").

* **The bugs found on the way:** a line with no target has none (Trend's said "hedef —" while the list showed the entry),
  Çiftler and the quant's meta name a bond as the desk does (not "TURKIYE GOVERNMENT BOND"), Korelasyon's day count reads
  "Gün", WIRP's check is "✓" (13 cells read "0,000000").  (DİBS switch's one sign convention and names:
  tests/test_quantdibssw.py.)
* **C16 - WIRP AL / SAT lines:** a meeting's implied policy rate against the PPK survey (MASA!R157:R159 dated Q157:Q159)
  - or a user's own "Beklentim" -, a line from a quarter of the grid: the meeting's period received or paid, entry its
  MPC OIS market rate (Trades' par), target its rate at the survey, stop half a grid against, money at the desk's DV01;
  "İşleme al" books the PPK period; a user's own lines theirs alone.
* **B1 / B18 - the card and the tables** (what a Python test can see of the pages: the browser test measures them).

(The HTTP part last: leaving its client stops the module's service.)"""
from __future__ import annotations

import datetime as dt
import io
import os
import re

import pytest
from starlette.testclient import TestClient

import quant_synth
from conftest import auth
from test_quantpath import FUTURE, TODAY, synthetic_year
from tto import quantfam as qf
from tto import quantpath as qp
from tto import tradequant as tq
from tto import tradevalue as tv
from tto.quant import DEFAULTS, QuantError
from tto.server import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "tto", "static", "js")
PAGES = os.path.join(JS, "pages")


def _read(name, where=PAGES):
    with io.open(os.path.join(where, name), encoding="utf-8") as f:
        return f.read()


# ================================================================================================ the bugs
def _line(reward, risk, z=2.5):
    """A drift line of a family that gives its own target / stop (``reward`` / ``risk``, level units)."""
    m = qf.Monitor("t:2Y", "momentum", "TRY OIS", "2Y OIS", "%", 3, [], [], [{"key": "OIS:2Y", "name": "2Y OIS", "weight": 1.0}],
                   lambda live: 38.0, zfn=lambda lv, live: z, mode="drift", follows=True, reward=reward, risk=risk, hold=5.0, entry=1.0)
    m.score({}, {})
    return qf.make_signal(m, dict(DEFAULTS), "10:00")


def test_a_line_with_no_target_has_none_never_the_entry():
    """quantfam.py:1280 (28.11.2026): "Trend: hedef girişe eşit" - a family with no move to aim at (reward 0 / none) had
    its target at the entry (the list's "Hedef" the entry, a backtest closing it at once "at its target")."""
    s = _line(0.0, 0.3)
    assert s["target"] is None and s["stop"] == pytest.approx(37.7) and s["reward"] is None and s["rr"] is None
    s = _line(None, None)
    assert s["target"] is None and s["stop"] is None and s["risk"] is None
    s = _line(0.2, 0.3)                                                  # (a family's own target: as before)
    assert s["target"] == pytest.approx(38.2) and s["stop"] == pytest.approx(37.7)
    down = _line(0.2, 0.3, z=-2.5)
    assert down["target"] == pytest.approx(37.8) and down["stop"] == pytest.approx(38.3)


def test_a_trend_line_without_a_gain_to_aim_at_says_so_everywhere():
    """Trend without a calibrated trailing stop and no gain in its strength's past lines: no target - the list "—" (not
    the entry, nor "iz süren stop"), its line "hedef —", its card "Hedef yok"; the İşlem cell the trade and its size."""
    from test_quanttrend import build as trend_build, fit as trend_fit
    ctx, eng = trend_build(drift={"OIS:2Y": 0.03})
    _, mons, _ = trend_fit(ctx, eng)
    m = mons["trend:OIS:2Y"]
    line = m.trend
    line.lv = {"ok": False, "why": "seviye kalibrasyonu yok: test"}
    line.buckets = [dict(b, gain=-0.1) for b in line.buckets]           # (every strength's past lines lost)
    qf.score_all(ctx, [m], ctx.live)
    sg = qf.make_signal(m, line.cfg, "10:00")
    assert sg["target"] is None and sg["stop"] is not None and not sg.get("trail")
    assert " · hedef — · " in sg["line"] and "Hedef yok: bu güçteki geçmiş satırlar ortalamada kazandırmadı" in sg["plain"]
    assert sg["trade_line"].endswith(line.inst.line(sg["direction"], line.k)) and "giriş" not in sg["trade_line"]
    # the page's row: no trailing stop - its "Hedef" cell "—" (quanttrend.js reads ``trail``)
    from tto import quanttrend as qtr
    v = {"tables": {"trend": {"rows": [{"sid": m.sid, "label": "2Y OIS", "group": "TRY OIS"}], "_keys": ["OIS:2Y"]}, "errors": {}},
         "signals": [sg], "gated": []}
    row = qtr.view(None, "trend", {}, v, {"mons": {m.sid: m}, "cfg": line.cfg, "coverage": []})["trend"]["rows"][0]
    assert row["target"] is None and row["trail"] is False and row["trade_line"] == sg["trade_line"]
    js = _read("quanttrend.js")
    assert "const none = r.trail ? 'iz süren stop' : '—';" in js
    assert "{ empty: s.trail ? 'iz süren stop' : '—' }" in _read("quantbase.js")


def test_bonds_are_named_as_the_desk_names_them():
    """quantfam.py:2361 (28.11.2026): Çiftler's 13 DİBS rows read "TURKIYE GOVERNMENT BOND" (Bloomberg's NAME, the same
    on every bond): the desk's name from the catalog or the maturity and kind - the pairs' labels and legs, the quant's
    meta (the coverage, every table reading a series' label)."""
    meta = {"maturity": "2029-09-12", "type": "S", "name": "TURKIYE GOVERNMENT BOND"}
    assert qf.dibs_label(meta, "TRT999999T99") == "12.09.29"
    assert qf.dibs_label(dict(meta, type="T"), "TRT999999T98") == "12.09.29 TLREF"
    assert qf.dibs_label(dict(meta, type="B"), "TRB999999T97") == "12.09.29 Bono"
    assert qf.dibs_label({"name": "TURKIYE GOVERNMENT BOND"}, "TRT999999T96") == "TRT999999T96"
    # the pairs on a context: a bond's yields and the OIS curve
    days = quant_synth.business_days(TODAY, 160)
    series = {"DIBS:TRT999999T99": {d: 35.0 + 0.01 * i for i, d in enumerate(days)}}
    smeta = {"DIBS:TRT999999T99": dict(meta, label="TURKIYE GOVERNMENT BOND", kind="rate", group="dibs", unit="pct")}
    for label, mo in (("1M", 1), ("3M", 3), ("1Y", 12), ("2Y", 24), ("5Y", 60)):
        series["OIS:" + label] = {d: 34.0 + 0.002 * mo for d in days}
        smeta["OIS:" + label] = {"label": label + " OIS", "kind": "rate", "months": float(mo)}
    ctx = qf.Ctx(dict(DEFAULTS, min_obs=60), TODAY, series, smeta, {})
    spec = next(s for s in qf.pair_specs(ctx) if s["y"] == "DIBS:TRT999999T99")
    assert spec["label"] == "12.09.29 getiri / OIS" and "TURKIYE" not in spec["label"]
    assert qf._pair_legs(ctx, spec, 1.0)[0]["name"] == "12.09.29"
    # ... and the quant's meta of a bond series (tto/quant.py: the coverage table, every label) from the history's info
    text = _read("quant.py", os.path.join(ROOT, "tto"))
    assert 'blabel = qf.dibs_label(info, str(info.get("isin") or ""))' in text


def test_korelasyon_counts_days_and_wirp_s_check_reads_a_tick():
    """Korelasyon's "Değişim" was the count of daily changes (270): "Gün"; WIRP's check (the matrix's expected value −
    the implied path, 0 by construction) printed "0,000000" in 13 cells: "✓" (the value in its tooltip, a real gap red)."""
    views = _read("quantviews.js")
    assert "this.boxes.pairs.set(['A', 'B', 'Gün', " in views and "'Değişim'" not in views
    path = _read("quantpath.js")
    assert "N(b.check, 6" not in path and "N(r.check, 6)" not in path
    assert "checkCell(b.check, 'bp')" in path and "[checkCell(r.check)]" in path and "'✓'" in path


# ================================================================================================ C16: the pieces
def test_a_window_s_term_its_period_and_its_sensitivity():
    hol = {dt.date(2026, 12, 25)}
    start, end = dt.date(2026, 12, 11), dt.date(2027, 1, 22)                 # (Friday to Friday: six weekends, a holiday)
    days, w = qp.window_term(start, end, hol)
    # (six weekends: three days in one step each, g(g − 1)/2 = 3; the holiday Friday makes its weekend four days: 6)
    assert days == 42 and w == pytest.approx(5 * 3 + 6)
    rows = [{"meeting": "2026-12-10", "level": 35.0}, {"meeting": "2027-01-21", "level": 34.5}]
    mkt = [{"row": 84, "start": "2026-12-11", "end": "2027-01-22", "rate": 35.7613, "model": 35.7339}]
    p = qp.period_of(rows, 0, mkt, hol)
    assert (p["start"], p["end"], p["rate"], p["market"], p["model"], p["row"]) == ("2026-12-11", "2027-01-22", 35.7613, 35.7613, 35.7339, 84)
    assert p["source"] == "MPC OIS piyasa (bootstrap)" and 1.03 < p["sens"] < 1.05            # (the O/N compounds over 42 days)
    alone = qp.period_of(rows, 0, [], hol)                                   # (no MPC OIS row: the model's window rate)
    from tto import ppkcurve as pc
    assert alone["rate"] == pytest.approx(pc.window_rate(0.35, 42, alone["term"]) * 100.0) and alone["market"] is None
    assert qp.period_of(rows, 1, mkt, hol) is None                          # (the last meeting: no next one, no period)
    # (a share of the grid in the sentences as the desk says it)
    assert [qp._share(x) for x in (0.25, 0.5, 0.3, 0.2, 0.4, 0.125, 0.05, 1.5, 2.0)] == [
        "dörtte biri", "yarısı", "%30'u", "%20'si", "%40'ı", "%12,5'i", "%5'i", "%150'si", "%200'ü"]


def test_the_survey_s_meetings():
    survey = [{"row": 157, "meeting": "2026-10-22", "rate": 36.0}, {"row": 158, "meeting": "2026-12-11", "rate": 35.0},
              {"row": 159, "meeting": "2027-01-21", "rate": 34.35}]
    got = qp.survey_of(list(FUTURE), survey, "2026-11-04")
    # a meeting already held has none; a date typed a day off is its meeting's
    assert sorted(got) == ["2026-12-10", "2027-01-21"] and got["2026-12-10"]["rate"] == 35.0 and got["2026-12-10"]["row"] == 158
    assert qp.survey_of(list(FUTURE), [{"row": 158, "meeting": "2026-12-20", "rate": 35.0}], "2026-11-04") == {}


def test_a_users_expectation_follows_its_meeting():
    mine = {"2026-12-10": 35.0, "2027-01-22": 34.0, "2026-10-22": 36.0}
    # by the meeting's date; a corrected date (21.01 typed for 22.01) is the same meeting; a meeting held never moves on
    al = qp.align_mine(mine, list(FUTURE))
    assert al == {"2026-12-10": (35.0, "2026-12-10"), "2027-01-21": (34.0, "2027-01-22")}
    assert qp.align_mine({"2026-12-09": 35.0}, ["2027-01-21", "2027-03-18"]) == {}                 # (held: not the next one)
    assert qp.align_mine({}, list(FUTURE)) == {}


def test_a_users_expectation_is_kept_theirs_alone():
    class KV(object):
        def __init__(self):
            self.kv = {}

        def get(self, key, default=None):
            return self.kv.get(key, default)

        def put(self, key, value):
            self.kv[key] = value

    store = KV()
    assert qp.set_mine(store, "ayse", "try", "2027-01-21", "34,25", "2026-11-03") == {"try": {"2027-01-21": 34.25}}
    qp.set_mine(store, "mehmet", "try", "2027-01-21", "%35.0", "2026-11-03")
    assert qp.mine_of(store, "ayse") == {"try": {"2027-01-21": 34.25}} and qp.mine_of(store, "mehmet") == {"try": {"2027-01-21": 35.0}}
    assert qp.set_mine(store, "ayse", "try", "2027-01-21", "", "2026-11-03") == {"try": {}}           # (an empty box: taken back)
    for bad in ("abc", "250", "-3"):
        with pytest.raises(ValueError):
            qp.set_mine(store, "ayse", "try", "2027-01-21", bad, "2026-11-03")
    with pytest.raises(ValueError):
        qp.set_mine(store, "ayse", "try", "21.01.2027", "34", "2026-11-03")
    qp.set_mine(store, "ayse", "try", "2026-09-10", "36", "2026-09-01")
    qp.set_mine(store, "ayse", "try", "2027-01-21", "34", "2026-11-03")       # (a month after its meeting it goes)
    assert qp.mine_of(store, "ayse") == {"try": {"2027-01-21": 34.0}}


# ================================================================================================ C16: the service
@pytest.fixture(scope="module")
def wirpsvc(module_service):
    """The replay service with a synthetic year of meeting pricing (tests/test_quantpath.py's): six meetings ahead from
    10.12.2026 - the survey of the recorded workbook names two of them (MASA!R158:R159: 35,00 and 34,35), the policy
    rate 36,00 (Q155), MPC OIS's market rates the workbook's."""
    svc = module_service
    svc.quant.use_live = False
    days = quant_synth.business_days(TODAY, 260)
    held = [days[i] for i in range(25, 260, 25)]
    days = days + [TODAY.isoformat()]
    paths, tl = synthetic_year(days, held, cut_at={0, 1, 3, 4, 6, 8})
    svc.store.mpc_delete()
    for d, p in paths.items():
        rows = [{"meeting": m, "level": lv / 100.0, "step": None, "cum": None, "sigma": None, "front": i == 0} for i, (m, lv) in enumerate(p["meetings"])]
        svc.store.mpc_save(d, "synth-" + d, {"spot": p["spot"], "tlref": p["base"], "base": p["base"] / 100.0, "quotes": 18, "status": "OK",
                                             "control": 0.1, "tolerance": 5.0}, rows)
    ref = next(x for x in svc.history.snapshot()["defs"] if x.group == "ref")
    for sid in ref.ids():
        svc.store.hist_delete(sid)
    svc.store.hist_upsert(ref.id, sorted((d, v) for d, v in tl.items() if d < TODAY.isoformat()))
    svc.history.rev += 1
    svc.quant.compute()
    return svc


def _bank(svc, user):
    return svc.quant.view("wirp", user, {})


def test_the_survey_s_lines_tell_the_period_in_its_traded_rate(wirpsvc):
    svc = wirpsvc
    user = svc.login("wirp okuyucu")["user"]
    page = _bank(svc, user)
    b = page["wirp"]["banks"]["try"]
    rows = {r["meeting"]: r for r in b["rows"]}
    st = qp.state_of(svc.quant)
    assert b["survey"]["cells"] == "MASA!Q157:R159" and [s["rate"] for s in b["survey"]["rows"]] == [36.0, 35.0, 34.35]
    # the survey's meetings ahead (22.10 is held): ima − anket, bp
    assert rows[FUTURE[0]]["survey"] == 35.0 and rows[FUTURE[1]]["survey"] == 34.35 and "survey" not in rows[FUTURE[2]]
    for m in FUTURE[:2]:
        r = rows[m]
        assert r["survey_gap"] == pytest.approx((r["rate"] - r["survey"]) * 100.0)
    lines = {s["id"]: s for s in page["signals"] if s["family"] == "wirp"}
    grid = b["grid"]
    for m in FUTURE[:2]:
        r = rows[m]
        sid = "wirp:TRY:" + m
        gap = r["survey_gap"]
        assert (sid in lines) == (abs(gap) >= 0.25 * grid), (m, gap)
        if sid not in lines:
            continue
        s = lines[sid]
        per = r["period"]
        mkt = next(p for p in st.mpc_ois if p["start"] == per["start"])
        q = s["quote"]
        # receive when the market prices more than the survey; the meeting's period, by its date
        assert s["direction"] == (-1 if gap > 0 else 1) and [l["key"] for l in s["legs"]] == ["MPC:" + m]
        assert s["legs"][0]["action"] == ("Receive" if gap > 0 else "Pay") and s["expression"].startswith(("Receive" if gap > 0 else "Pay") + " PPK ")
        # entry the period's MPC OIS market rate now; target its rate at the survey; stop half a grid against
        assert q["entry"] == pytest.approx(mkt["rate"]) and per["source"] == "MPC OIS piyasa (bootstrap)"
        assert q["target"] == pytest.approx(mkt["rate"] - per["sens"] * gap / 100.0)
        assert q["stop"] == pytest.approx(mkt["rate"] + per["sens"] * (25.0 if gap > 0 else -25.0) / 100.0)
        assert s["entry"] == pytest.approx(gap) and s["target"] == pytest.approx(0.0, abs=1e-9)
        # money at the desk's DV01: the expectation under the survey is the gap
        tl = s["money"]["per_bp"]
        assert s["money"]["dv01_usd"] == 1000.0 and s["exp_pnl"] == pytest.approx(abs(gap) * per["sens"])
        assert s["money"]["total"] == pytest.approx(abs(gap) * per["sens"] * tl) and s["money"]["stop"] == pytest.approx(-25.0 * per["sens"] * tl)
        pat = (r"^(Receive|Pay) PPK \d\d\.\d\d\.\d\d–\d\d\.\d\d\.\d\d dönemi · 1\.000 \$ DV01 · giriş %[\d,]+ · hedef %[\d,]+ \(anket %[\d,]+\) · "
               r"stop %[\d,]+ · beklenen [+-][\d.,]+( bin| mn)? TL · ankete göre$")
        assert re.match(pat, s["line"]), s["line"]
        assert s["trade_line"] == s["expression"] + " · 1.000 $ DV01" and "ankete gelirse" in s["plain"] and s["info"]["source"] == "anket"
        assert s["levels"]["own"] and not s.get("personal") and s["info"]["model"] == "TCMB WIRP · anket"
        # "İşleme al": a PPK period at its market rate - Trades' par of it
        assert tq.bookable(s)[2] == "mpc"
        pre = tq.prefill(svc, user, sid)
        t = pre["trade"]
        assert pre["ok"] and pre["kind"] == "mpc" and t["structure"] == "mpc" and t["mpc_date"] == m and t["side"] == ("S" if gap > 0 else "B")
        assert t["price"] == pytest.approx(round(mkt["rate"], 4)) and t["dv01"] == 1000.0
        assert t["target"] == pytest.approx(round(q["target"], 4)) and t["stop"] == pytest.approx(round(q["stop"], 4))
        par = svc.tradebook._engine(lambda t=t: tv.value(dict(t, trade_date=TODAY.isoformat()), tv.market(svc)))
        assert par["ok"] and par["price_now"] == pytest.approx(mkt["rate"], abs=1e-6)
    assert lines, "no survey line on the synthetic path"
    # the survey's lines are everybody's: Sinyaller's list (TRY OIS), on its page
    sig = svc.quant.view("signals", user, {"family": "wirp"})
    assert {s["id"] for s in sig["signals"]} == set(lines) and all(s["group"] == "TRY OIS" for s in sig["signals"])
    assert all(r.get("sid") == "wirp:TRY:" + m for m, r in rows.items() if "survey" in r)


def test_the_threshold_and_the_stop_are_the_desk_s_settings(wirpsvc):
    svc = wirpsvc
    user = svc.login("wirp ayar")["user"]
    gaps = {r["meeting"]: r["survey_gap"] for r in _bank(svc, user)["wirp"]["banks"]["try"]["rows"] if r.get("survey_gap") is not None}
    big = max(abs(g) for g in gaps.values())
    try:
        share = round(min(2.0, big / 50.0 + 0.05), 4)
        assert share * 50.0 > big                                                           # (a threshold past every gap)
        svc.quant.set_settings(user, {"wirp_min": str(share).replace(".", ","), "wirp_stop": "1"})
        svc.quant.compute()
        page = _bank(svc, user)
        assert not [s for s in page["signals"] if s["family"] == "wirp"]                    # (every gap under the threshold)
        svc.quant.set_settings(user, {"wirp_min": "0,05"})
        svc.quant.compute()
        s = next(x for x in _bank(svc, user)["signals"] if x["family"] == "wirp")
        assert s["stop"] - s["entry"] == pytest.approx(50.0 if s["direction"] < 0 else -50.0)   # (a whole grid against)
    finally:
        svc.quant.set_settings(user, {"wirp_min": "0,25", "wirp_stop": "0,5"})
        svc.quant.compute()


def test_the_survey_typed_during_the_day_reaches_the_lines(wirpsvc):
    """The desk types a new survey on Masa (a desk input): the minute's refresh makes the lines again."""
    svc = wirpsvc
    user = svc.login("wirp masa")["user"]
    sid = "wirp:TRY:" + FUTURE[1]
    before = svc.quant._fit["mons"][sid].info["expect"]
    try:
        assert not svc.set_inputs(user, "tto", [{"ref": "MASA!R159", "value": "33,90"}])["errors"]
        svc.quant.refresh_live()
        m = svc.quant._fit["mons"][sid]
        assert before == 34.35 and m.info["expect"] == 33.9
        row = next(r for r in _bank(svc, user)["wirp"]["banks"]["try"]["rows"] if r["meeting"] == FUTURE[1])
        assert row["survey"] == 33.9 and m.level == pytest.approx((row["rate"] - 33.9) * 100.0)
    finally:
        svc.reset_inputs(user, "tto", ["MASA!R159"], shared=True)
        svc.quant.refresh_live()
    assert svc.quant._fit["mons"][sid].info["expect"] == 34.35


def test_a_users_own_expectation_makes_their_own_lines(wirpsvc):
    svc = wirpsvc
    ayse = svc.login("wirp beklenti ayşe")["user"]
    mehmet = svc.login("wirp beklenti mehmet")["user"]
    m = FUTURE[2]                                                        # (no survey for it: only her expectation)
    sid = "wirp:TRY:%s:mine" % m
    try:
        page = svc.quant.action("wirp-mine", ayse, {"bank": "try", "meeting": m, "rate": "33,5"})
        row = next(r for r in page["wirp"]["banks"]["try"]["rows"] if r["meeting"] == m)
        assert row["mine"] == 33.5 and row["mine_gap"] == pytest.approx((row["rate"] - 33.5) * 100.0) and row["mine_sid"] == sid
        own = next(s for s in page["signals"] if s["id"] == sid)
        assert own["personal"] and own["info"]["source"] == "mine" and own["line"].endswith(" · beklentime göre") and "(beklentim %33,500)" in own["line"]
        assert own["direction"] == (-1 if row["mine_gap"] > 0 else 1) and own["book"]["ok"] and own["book"]["kind"] == "mpc"     # (the save's answer: marked)
        # hers alone: not on another's page, not in the desk's list, never logged
        assert not any(s["id"] == sid for s in _bank(svc, mehmet)["signals"])
        assert not any(s["id"] == sid for s in svc.quant.view("signals", ayse, {})["signals"])
        assert sid not in svc.quant._fit["mons"] and not any(e["sid"] == sid for e in svc.quant.log_view()["entries"])
        # its card and its "İşleme al" are made for her
        card = svc.quant.view("signal", ayse, {"id": sid})
        assert card["signal"]["id"] == sid and card["monitor"]["family"] == "wirp" and card["signal"]["personal"]
        with pytest.raises(QuantError):
            svc.quant.view("signal", mehmet, {"id": sid})
        pre = svc.quant.view("book", ayse, {"id": sid})
        assert pre["ok"] and pre["trade"]["mpc_date"] == m and pre["trade"]["price"] == pytest.approx(round(row["period"]["rate"], 4))
        # nothing typed that is no rate
        with pytest.raises(QuantError):
            svc.quant.action("wirp-mine", ayse, {"bank": "try", "meeting": m, "rate": "otuz"})
    finally:
        page = svc.quant.action("wirp-mine", ayse, {"bank": "try", "meeting": m, "rate": ""})
    assert not any(s["id"] == sid for s in page["signals"]) and "mine" not in next(r for r in page["wirp"]["banks"]["try"]["rows"] if r["meeting"] == m)


def test_wirp_http_lines_beklentim_card_and_book(wirpsvc):
    svc = wirpsvc
    m = FUTURE[2]
    with TestClient(create_app(svc), headers=auth(svc, "Wirp HTTP")) as client:
        body = client.get("/api/quant/wirp").json()
        assert body["ready"] and all(s["book"]["ok"] for s in body["signals"] if s["family"] == "wirp")
        r = client.post("/api/quant/wirp-mine", json={"bank": "try", "meeting": m, "rate": "33,25"})
        assert r.status_code == 200 and any(s.get("personal") for s in r.json()["signals"])
        sid = "wirp:TRY:%s:mine" % m
        assert client.get("/api/quant/signal", params={"id": sid}).json()["signal"]["id"] == sid
        book = client.get("/api/quant/book", params={"id": sid}).json()
        assert book["ok"] and book["kind"] == "mpc" and book["trade"]["mpc_date"] == m
        assert client.post("/api/quant/wirp-mine", json={"bank": "try", "meeting": m, "rate": "x"}).status_code == 400
        assert client.post("/api/quant/wirp-mine", json={"bank": "try", "meeting": m, "rate": ""}).status_code == 200
        assert client.get("/api/quant/book", params={"id": sid}).status_code == 404
        assert client.get("/api/quant/wirp", headers={"Authorization": ""}).status_code == 401


# ================================================================================================ B1, B18: the pages
def test_the_card_is_two_columns_its_details_folded_per_user_and_a_window_when_off_screen():
    base = _read("quantbase.js")
    # two columns: the sentence, the trade, İşleme al and the levels left; the charts right, one above the other
    assert "h('div', { class: 'qcardcols' }, h('div', { class: 'qcardleft' }, this.lead), h('div', { class: 'qcardright' }, this.plots))" in base
    # "Ayrıntı" and "Gerekçe" folded, each user's choice kept (by user, in this browser - as the menu's folds)
    assert "const pkey = CARD_FOLD + (session.user || '') + '.' + key;" in base and "el.open = pref(pkey, '0') === '1';" in base
    assert "cardFold('ayrinti', 'Ayrıntı'" in base and "cardFold('gerekce', 'Gerekçe'" in base and "this.reasons.appendChild(box);" in base
    # a card off screen opens in the card window instead of the page scrolling to it
    assert "export async function cardWindow(sid, opts = {})" in base and "if (away) cardWindow(sid, { data: d" in base
    assert "scrollIntoView" not in base[base.index("  revealCard() {"):base.index("  fillStatus() {")]
    boxes = _read("pageboxes.js", JS)
    assert "return cardWindow(sid, { go: ['Sinyaller sayfasında aç'" in boxes and "new SignalChart(" not in boxes
    css = _read("app.css", os.path.join(ROOT, "tto", "static", "css"))
    assert ".qcard2 .qcardcols { display: flex;" in css and ".qcard2 .qcardright .volcharts.svcharts { grid-template-columns: minmax(0, 1fr);" in css


def test_the_tables_the_trade_cell_one_basket_table_and_charts_beside_their_tables():
    base = _read("quantbase.js")
    # the İşlem cell: the trade and its size, wrapping; the whole line in its tooltip
    assert "const cell = tradeCellText(s);" in base and "const whole = s.line || s.expression || '';" in base
    assert "row.push(T(cell, Object.assign({ b: 1, tip: (whole && whole !== cell ? whole + " in base
    assert "{ cls: ('qtrade' + (side ? ' ' + side : '')) }" in base
    for fn, word in (("quanttrend.py", 'sg["trade_line"] = " · ".join('), ("quantdibssw.py", 'sg["trade_line"] = head'),
                     ("quantoptspot.py", 'sg["trade_line"] = head'), ("quantml.py", 'sg["trade_line"] = inst.line(side)'),
                     ("quantcons.py", '"trade_line": "%s · birleşik %s" % (head, size)')):
        assert word in _read(fn, os.path.join(ROOT, "tto")), fn
    # Carry + momentum: the six baskets one table, one ranking at a time (the six panels gone)
    sira = _read("quantsira.js")
    assert "panel('quant-sira-baskets'" in sira and "panel('quant-sira-ranking'" in sira and "panel('quant-sira-g10'" not in sira
    assert re.search(r"seg\(SETS\.map", sira) and "showSet(id)" in sira
    # a chart beside the table it draws: Opsiyon's ATM term structure, PCA's loadings, WIRP's history; WIRP's buckets beside its table
    assert "panel('quant-opt-ts', 'ATM vade yapısı', { side: this.tsChart, wide: true })" in _read("quantfit.js")
    assert "panel('quant-pca-loadings', 'Yükler (vade başına)', { side: this.loadChartHost, wide: true })" in _read("quantviews.js")
    path = _read("quantpath.js")
    assert "{ side: this.histHost, wide: true }" in path and "panel('quant-wirp-bars', 'Toplantı sonrası faiz olasılıkları', { cls: 'qbeside' })" in path
    assert "const main = opts.side ? h('div', { class: 'qside' }, body, h('div', { class: 'qsidechart' }, opts.side)) : body;" in base
