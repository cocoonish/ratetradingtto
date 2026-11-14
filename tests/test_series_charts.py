"""A click draws the past ("tıkla → grafik", as on Realized Vol · Carry): the closes behind a row of the end-of-day
matrix (``/api/history/closes``) and behind an item of the watch list or a point of the heat map
(``/api/watch/history``), and the statistics the browser draws them with (``tto/static/js/seriesstats.js``) - the
very numbers of the tables next to them: the FX monitor's (the workbook's macro block, ``tto.fx.stats``) and the
watch list's (``Watch.zinfo``).  The browser's module is run by Node.js (skipped when there is none)."""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import shutil
import statistics
import subprocess

import pytest
from starlette.testclient import TestClient

from conftest import auth, make_service
from tto import fx
from tto import watch as wt
from tto.server import create_app
from tto.service import ServiceError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS_JS = os.path.join(ROOT, "tto", "static", "js", "seriesstats.js")


@pytest.fixture()
def svc(tmp_path):
    s = make_service(tmp_path)
    yield s
    s.stop()


def week_days(end, n):
    """The last n week days up to ``end``, oldest first."""
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= _dt.timedelta(days=1)
    return out[::-1]


# ---------------------------------------------------------------------------------------------- end-of-day matrix
def test_a_row_of_the_end_of_day_matrix_draws_its_closes(svc):
    u = svc.login("Gün Sonu Grafik")["user"]
    defs = {(d.group, d.label): d for d in svc.history.snapshot()["defs"]}
    ois = defs[("ois", "1Y")]
    today = svc.history.today()
    days = week_days(today - _dt.timedelta(days=1), 40)
    svc.store.hist_upsert(ois.id, [(d, 35.0 + 0.01 * i) for i, d in enumerate(days) if d != days[-3]])
    gap = days[-3]
    if ois.alts:                                      # the main source misses a day: its backup's move fills it
        svc.store.hist_upsert("%s|%s" % (ois.alts[0], ois.field), [(days[-4], 40.0), (gap, 40.5)])
    svc.history.rev += 1
    res = svc.history_closes(u, ois.id)
    assert res["sid"] == ois.id and res["label"] == ois.label == "1Y" and res["group"] == "ois" and res["unit"] == "pct"
    assert res["ticker"] == ois.ticker and res["field"] == ois.field and res["today"] == today.isoformat()
    pts = dict(res["points"])
    assert [d for d, _ in res["points"]] == sorted(pts) and all(d <= today.isoformat() for d in pts)
    assert pts[days[0]] == 35.0 and pts[days[-1]] == pytest.approx(35.39)
    if ois.alts:
        assert gap in pts and res["backup_days"] == 1
    # the matrix tells each row's series, so that a click can ask for it
    m = svc.history.matrix()
    one = next(r for r in m["curve"] if r["tenor"] == "1Y")
    assert one["ois"]["sid"] == ois.id
    assert all(b["sid"] for b in m["bonds"])
    with pytest.raises(ServiceError):
        svc.history_closes(u, "YOK Curncy|PX_LAST")
    with pytest.raises(ServiceError):
        svc.history_closes(None, ois.id)


# ---------------------------------------------------------------------------------------------- watch list / heat map
def seed(s, group, tenor, values):
    """Closes of the market history (as Bloomberg's would be kept) for the last week days before today."""
    d = s.et.call(s.watch._hist_defs)[(group, tenor)]
    days = week_days(_dt.date.today() - _dt.timedelta(days=1), len(values))
    s.store.hist_upsert(d.id, list(zip(days, values)))
    s.history.rev += 1
    return days


def test_a_watched_subjects_past_is_what_its_z_score_uses(svc):
    u = svc.login("İzleme Grafik")["user"]
    one = {"kind": "ois", "tenor": "1Y"}
    ones = [35.0 + 0.02 * i + (0.05 if i % 4 == 0 else 0.0) for i in range(30)]
    days = seed(svc, "ois", "1Y", ones)
    res = svc.watch_history(u, one)
    assert res["label"] == "OIS 1Y" and res["show"] == "pct" and res["source"] == "tarihçe" and res["today"] == svc.today_iso()
    assert [tuple(p) for p in res["points"]] == list(zip(days, ones))
    z = svc.watch_preview(u, one)["z"]["20"]
    assert res["value"] == pytest.approx(svc.watch_preview(u, one)["value"])
    last = ones[-20:]
    assert z["z"] == pytest.approx((res["value"] - statistics.mean(last)) / statistics.stdev(last))
    # an expression: its parts' closes, day by day
    seed(svc, "ois", "6M", [36.0 + 0.01 * i for i in range(30)])
    spread = svc.watch_history(u, {"kind": "expr", "text": "[OIS 1Y] - [OIS 6M]"})
    assert len(spread["points"]) == 30 and spread["show"] == "bp"
    assert spread["points"][-1][1] == pytest.approx((ones[-1] - (36.0 + 0.29)) * 100)
    with pytest.raises(ServiceError):
        svc.watch_history(u, None)
    with pytest.raises(ServiceError):
        svc.watch_history(u, {"kind": "ois", "tenor": "99Y"})


def test_http(svc):
    u = svc.login("Grafik HTTP")["user"]
    h = auth(svc, u)
    client = TestClient(create_app(service=svc))
    seed(svc, "ois", "1Y", [35.0 + 0.02 * i for i in range(30)])
    r = client.post("/api/watch/history", json={"subject": {"kind": "ois", "tenor": "1Y"}}, headers=h)
    assert r.status_code == 200 and len(r.json()["points"]) == 30
    assert client.post("/api/watch/history", json={"subject": "x"}, headers=h).status_code == 400
    assert client.post("/api/watch/history", json={"subject": {"kind": "ois", "tenor": "1Y"}}).status_code == 401
    sid = next(d.id for d in svc.history.snapshot()["defs"] if d.group == "ois" and d.label == "1Y")
    r = client.get("/api/history/closes", params={"sid": sid}, headers=h)
    assert r.status_code == 200 and r.json()["sid"] == sid
    assert client.get("/api/history/closes", params={"sid": "yok"}, headers=h).status_code == 400
    assert client.get("/api/history/closes", params={"sid": sid}).status_code == 401


# ---------------------------------------------------------------------------------------------- the browser's statistics
RUNNER = """
import { basis, standing, rollingZ } from %s;
import { readFileSync } from 'node:fs';
const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map((c) => {
  const b = basis(c.points, c.rule, c.today, c.from);
  const closes = b.map((p) => p[1]);
  const now = c.live === null ? closes[closes.length - 1] : c.live;
  return { st: standing(closes, now, c.w, c.rule), n: closes.length, z: rollingZ(closes, c.w, 20).slice(-3) };
});
process.stdout.write(JSON.stringify(out));
"""


def run_js(tmp_path, cases):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js yok: tarayıcının istatistik modülü çalıştırılamadı")
    runner = tmp_path / "run.mjs"
    url = "file:///" + STATS_JS.replace(os.sep, "/").lstrip("/")
    runner.write_text(RUNNER % json.dumps(url), encoding="utf-8")
    data = tmp_path / "cases.json"
    data.write_text(json.dumps(cases), encoding="utf-8")
    res = subprocess.run([node, str(runner), str(data)], capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_the_browser_draws_with_the_tables_numbers(tmp_path):
    today = _dt.date(2026, 11, 16)                                    # a Monday
    axis_from = fx.closes_axis(today)[0].isoformat()
    days = week_days(today - _dt.timedelta(days=3), 261)
    vals = {d: 10.0 + 0.01 * i + 0.4 * math.sin(i / 7.0) for i, d in enumerate(days)}
    holes = dict(vals)
    for i in (5, 6, 7, 8, 9, 10, 11, 40, 41, 120, 200):               # a week and more without a close, short gaps
        holes.pop(days[i])
    holes[(today - _dt.timedelta(days=400)).isoformat()] = 99.0          # before the macro block's axis: not counted
    holes[today.isoformat()] = 55.0                                      # today's close: the live value stands for today
    cases, want = [], []
    for pts, live, w in ((vals, 13.2, 250), (holes, 13.2, 63), (holes, 11.1, 126), (holes, None, 250), (holes, 12.0, 20)):
        cases.append({"points": sorted(pts.items()), "rule": "macro", "today": today.isoformat(), "from": axis_from, "live": live, "w": w})
        want.append(("macro", fx.stats(pts, live, today, w)))
    # the watch list's: the closes as they are, the last ``days`` before today
    short = {d: v for d, v in list(holes.items())[-40:]}
    for live, w in ((12.5, 20), (12.5, 60), (9.0, 250)):
        cases.append({"points": sorted(short.items()), "rule": "raw", "today": today.isoformat(), "from": None, "live": live, "w": w})
        keys = sorted(k for k in short if k < today.isoformat())[-w:]
        win = [short[k] for k in keys]
        mean, sd = statistics.mean(win), statistics.stdev(win)
        want.append(("raw", {"z": (live - mean) / sd if len(win) >= wt.min_closes(w) else None,
                             "pct": sum(x < live for x in win) / len(win), "min": min(win), "max": max(win), "window": len(win)}))
    got = run_js(tmp_path, cases)
    for (rule, w), g in zip(want, got):
        st = g["st"]
        if w["z"] is None:
            assert st is None
            continue
        assert st["z"] == pytest.approx(w["z"], rel=1e-9, abs=1e-12), rule
        assert st["pct"] == pytest.approx(w["pct"]) and st["min"] == w["min"] and st["max"] == w["max"] and st["n"] == w["window"], rule
    # the z chart: a day's close against the closes before it
    closes = [v for _, v in sorted(vals.items())]
    win = closes[-251:-1]
    assert got[0]["z"][-1] == pytest.approx((closes[-1] - statistics.mean(win)) / statistics.stdev(win), rel=1e-9)
