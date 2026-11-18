"""Hesap (``tto/progress.py``): where the long calculations are and the time left.

The rule of the time left on a clock of the test's own (a job of like units on this run's pace once three are done,
the last run's before; the fit by the last fit's steps of its own kind, the ML step by its models; never below zero,
never past the backtest's budget, nothing without a measure, nothing absurd); the fit's steps counted as the families
write their times; the ML family's models fitted / to fit (none when its cache has them); the backtest's refits and
their months; the history's series and days; ``/api/progress`` and the status the pages poll (the HTTP part last:
leaving its client stops the service)."""
from __future__ import annotations

import datetime as dt
import re

import pytest
from starlette.testclient import TestClient

import quant_synth
import quant_synth_ml as sm
from conftest import auth, make_service
from tto import progress as prog
from tto import quant as qq
from tto import quantbt as qbt
from tto import quantml as ml
from tto import quantuniv as qu
from tto.server import create_app


class Clock(object):
    """A clock the test moves."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Store(object):
    """The store's get / put, in memory."""

    def __init__(self):
        self.kv = {}

    def get(self, key):
        return self.kv.get(key)

    def put(self, key, value):
        self.kv[key] = value


# ================================================================================================ the rule
def test_the_time_left_is_said_the_desks_way():
    assert prog.eta_text(None) == "" and prog.eta_text(0.0) == "az kaldı" and prog.eta_text(9.4) == "az kaldı"
    assert prog.eta_text(12.0) == "~20 sn" and prog.eta_text(40.0) == "~40 sn" and prog.eta_text(55.0) == "~1 dk"
    assert prog.eta_text(170.0) == "~3 dk" and prog.eta_text(3600.0) == "~1 sa" and prog.eta_text(3900.0) == "~1 sa 5 dk"
    assert prog.month_text("2026-03-14") == "Mart 2026" and prog.month_text("2025-12-31") == "Aralık 2025" and prog.month_text("?") == ""
    assert qq.bt_month("2026-03-14") == "Mart 2026 · 14.03.2026 kapanışıyla"


def test_a_job_of_like_units_runs_on_its_own_pace_after_three_and_the_last_runs_before():
    clock, store = Clock(), Store()
    hub = prog.Progress(store, clock)
    job = hub.begin("bt", "geri test", "Geri test", "yeniden kurma", total=10)
    assert hub.eta(job) is None                                     # no measure: no estimate (never a guess)
    for _ in range(2):
        clock.t += 4.0
        job.tick()
    assert hub.eta(job) is None                                     # two units are no pace yet
    clock.t += 4.0
    job.tick()
    assert hub.eta(job) == pytest.approx(7 * 4.0)                   # 7 left × 4 s
    clock.t += 3.0
    assert hub.eta(job) == pytest.approx(1.0 + 6 * 4.0)             # the one under way less what it has taken
    clock.t += 10.0
    assert hub.eta(job) == pytest.approx(6 * 4.0)                   # ... at least zero: never below the rest
    job.at(10)
    assert hub.eta(job) == 0.0 and hub.view()["jobs"][0]["eta"] == "az kaldı"
    v = hub.view()
    assert v["busy"] and v["text"] == "geri test 10/10 · az kaldı" and v["jobs"][0]["short"] == "geri test 10/10"
    hub.end(job)
    assert hub.view() == {"busy": False, "jobs": [], "eta_s": None, "eta": "", "text": ""}
    took = 3 * 4.0 + 3.0 + 10.0
    assert store.kv[prog.RUNS_KEY]["bt"]["run"]["per_unit"] == pytest.approx(took / 10) and store.kv[prog.RUNS_KEY]["bt"]["run"]["units"] == 10
    # the next run (a new start: the store's record): the last run's pace before three units are done
    hub2 = prog.Progress(store, clock)
    job2 = hub2.begin("bt", "geri test", "Geri test", "yeniden kurma", total=25, budget=60.0)
    assert hub2.eta(job2) == pytest.approx(min(25 * took / 10, 60.0))   # ... never past the budget's end
    clock.t += 59.0
    assert hub2.eta(job2) == pytest.approx(1.0)
    clock.t += 5.0
    assert hub2.eta(job2) == 0.0                                    # (over its budget: the backtest stops there)
    hub2.end(job2, ok=False)
    assert store.kv[prog.RUNS_KEY]["bt"]["run"]["units"] == 10      # a run that failed measures nothing
    # nothing absurd: an estimate above two hours is not shown
    job3 = hub2.begin("history", "PPK geçmişi", "Tarihçe", "gün", total=10000, phase="mpc")
    for _ in range(3):
        clock.t += 2.0
        job3.tick()
    assert hub2.eta(job3) is None and hub2.view()["text"] == "PPK geçmişi 3/10000"


def test_an_ml_model_s_time_is_the_fit_s_own():
    """The lines whose models the cache has take time between the fits: the pace is the fits' own."""
    clock = Clock()
    hub = prog.Progress(None, clock)
    job = hub.begin("ml", "ML", "Makine öğrenmesi: modeller", "model", total=100)
    for _ in range(4):
        clock.t += 5.0                                              # (4 s of cached lines, 1 s of fitting)
        job.tick(1, 1.0)
    assert hub.eta(job) == pytest.approx(96 * 1.0)
    hub.end(job)
    assert hub.runs()["ml"]["run"]["per_unit"] == pytest.approx(1.0)


def test_the_fit_counts_its_steps_as_their_times_are_written_and_estimates_by_the_last_fit():
    clock, store = Clock(), Store()
    hub = prog.Progress(store, clock)
    plan = {"order": ["a", "ml", "c"], "at": [10.0, 30.0, 60.0], "total": 70.0}
    job = hub.begin("quant", "Quant", "Quant tam hesap", "adım", plan=plan, labels={"a": "Aile A", "ml": "Makine öğrenmesi"})
    timing = prog.Steps(job)
    v = hub.view()["jobs"][0]
    assert (v["done"], v["total"], v["step"], v["eta_s"]) == (0, 3, "Aile A", 70)
    clock.t += 12.0
    timing["a"] = 12.0                                              # (a family writes its time: that step is done)
    v = hub.view()["jobs"][0]
    assert (v["done"], v["step"], v["eta_s"], v["short"]) == (1, "Makine öğrenmesi", 20 + 30 + 10, "Quant 1/3")
    clock.t += 25.0                                                 # the ML step over the last fit's 20 s
    assert hub.eta(job) == pytest.approx(30 + 10)
    # ... its models under way: their own estimate stands for the step
    sub = hub.begin("ml", "ML", "Makine öğrenmesi: modeller", "model", total=50)
    for _ in range(5):
        clock.t += 2.0
        sub.tick(1, 2.0)
    assert hub.eta(job) == pytest.approx(45 * 2.0 + 30 + 10)
    v = hub.view()
    assert v["text"] == "Quant 1/3 · ML 5/50 · ~2 dk" and v["eta_s"] == round(45 * 2.0 + 40)
    hub.end(sub)
    clock.t += 1.0
    timing["ml"] = 36.0
    timing["x"] = 0.1                                               # (a step the last fit did not have: counted too)
    v = hub.view()["jobs"][0]
    assert (v["done"], v["total"], v["step"]) == (3, 4, "c")
    clock.t += 30.0
    timing["c"] = 30.0
    clock.t += 4.0
    assert hub.eta(job) == pytest.approx(10.0 - 4.0)               # the last fit's tail (score, publish)
    assert dict(timing) == {"a": 12.0, "ml": 36.0, "x": 0.1, "c": 30.0}   # (a dict as ever to who reads it)
    hub.end(job, True, "cold")
    rec = store.kv[prog.RUNS_KEY]["quant"]["cold"]
    assert rec["order"] == ["a", "ml", "x", "c"] and rec["at"] == [12.0, 48.0, 48.0, 78.0] and rec["total"] == 82.0
    assert "warm" not in store.kv[prog.RUNS_KEY]["quant"]
    # what the next fit counts: the last fit of its kind, else the other kind's order or the code's - no time without one
    hub2 = prog.Progress(store, clock)
    assert qq.Quant._fit_plan(hub2, "cold") == {"order": ["a", "ml", "x", "c"], "at": [12.0, 48.0, 48.0, 78.0], "total": 82.0}
    assert qq.Quant._fit_plan(hub2, "warm") == {"order": ["a", "ml", "x", "c"], "at": None, "total": None}
    assert qq.Quant._fit_plan(prog.Progress(Store(), clock), "cold") == {"order": list(qq.FIT_STEPS), "at": None, "total": None}
    job = hub2.begin("quant", "Quant", "Quant tam hesap", "adım", plan=qq.Quant._fit_plan(hub2, "warm"))
    assert hub2.eta(job) is None and hub2.view()["text"] == "Quant 0/4"


# ================================================================================================ the fit, the models, the refits
@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    svc = make_service(tmp_path_factory.mktemp("prog"))
    svc.quant.use_live = False                                           # the workbook's live quotes are not of this history
    quant_synth.seed(svc)
    yield svc
    svc.stop()


def test_the_fit_counts_its_families_and_the_ml_family_its_models(seeded, monkeypatch):
    """A fit after a start (every cache empty): its steps in the code's order, the one running by its name - Trend's turn
    is step 21 of 26 -, the ML family's models fitted / to fit, one by one; nothing left when it is done, its steps' and
    models' times kept.  The same data again: no model to fit - no ML job at all; the fit measured as a later one."""
    svc = seeded
    hub = svc.progress
    ml.reset()
    seen = {}
    real_trend = qu.RUNNERS["trend"]

    def trend(ctx, reg, cfg):
        seen["trend"] = hub.view()
        seen["status"] = svc.quant.status()
        return real_trend(ctx, reg, cfg)

    fits = []
    real_fit = ml.Trees.fit

    def fit(cls, *a, **kw):
        job = hub.jobs.get("ml")
        fits.append((job.done, job.total) if job is not None else None)
        return real_fit(*a, **kw)

    monkeypatch.setitem(qu.RUNNERS, "trend", trend)
    monkeypatch.setattr(ml.Trees, "fit", classmethod(fit))
    svc.quant.state["fits"] = 0                                          # (a fit after a start)
    svc.quant.compute()
    at = seen["trend"]["jobs"][0]
    assert (at["id"], at["done"], at["total"], at["step"], at["unit"]) == ("quant", qq.FIT_STEPS.index("trend"), len(qq.FIT_STEPS), "Trend", "adım")
    assert seen["trend"]["text"].startswith("Quant %d/%d" % (qq.FIT_STEPS.index("trend"), len(qq.FIT_STEPS)))
    assert seen["status"]["phase"] == "fit" and seen["status"]["progress"]["jobs"][0]["id"] == "quant"
    n = len(fits)
    assert n > 20 and fits == [(i, n) for i in range(n)]                # every model, one by one, of all it had to fit
    assert hub.view()["busy"] is False and "progress" not in svc.quant.status()
    runs = hub.runs()
    assert runs["quant"]["cold"]["order"] == list(qq.FIT_STEPS) == list(svc.quant.state["timing"])
    assert runs["quant"]["cold"]["at"] == sorted(runs["quant"]["cold"]["at"]) and runs["ml"]["run"]["units"] == n
    # the same data again: the cache has every model - nothing to count; a later fit's measure of its own
    fits.clear()
    svc.quant.compute()
    assert fits == [] and "ml" not in hub.jobs and set(hub.runs()["quant"]) == {"cold", "warm"}
    # a start again (the cold fit's record): the time left from the first step on
    svc.quant.state["fits"] = 0
    svc.quant.compute()
    left = seen["trend"]["jobs"][0]["eta_s"]
    assert left is not None and 0 <= left <= prog.MAX_ETA and seen["trend"]["eta"]


def test_the_backtest_counts_its_refits_and_says_their_month(seeded, monkeypatch):
    """Each refit as it begins: done / all, its month and last close; the first backtest without a time left (nothing
    measured yet), the next one with the last one's pace from its first refit on."""
    svc = seeded
    q = svc.quant
    hub = svc.progress
    if q._last_base is None:
        q.compute()
    seen = []
    real = qbt.backtest

    def spy(days, make_ctx, runner, closes, cfg, **kw):
        on = kw["on_refit"]

        def at(n, day):
            on(n, day)
            seen.append((n, day, hub.view(("bt",)), q.backtest_view().get("progress")))

        kw["on_refit"] = at
        return real(days, make_ctx, runner, closes, cfg, **kw)

    monkeypatch.setattr(qbt, "backtest", spy)
    res = q.run_backtest(days=40, step=20)
    assert res["refits"] == 2 and [s[0] for s in seen] == [0, 1] and seen[1][1] > seen[0][1]
    for n, day, v, panel in seen:
        job = v["jobs"][0]
        assert (job["id"], job["done"], job["total"], job["unit"], job["eta_s"]) == ("bt", n, 2, "yeniden kurma", None)
        d = dt.date.fromisoformat(day)
        assert job["step"] == "%s %d · %s kapanışıyla" % (prog.MONTHS_TR[d.month - 1], d.year, d.strftime("%d.%m.%Y"))
        assert v["text"] == "geri test %d/2" % n and panel["jobs"][0]["id"] == "bt"
    assert hub.view()["busy"] is False and "progress" not in q.backtest_view()
    per = hub.runs()["bt"]["run"]["per_unit"]
    assert hub.runs()["bt"]["run"]["units"] == 2 and per > 0
    seen.clear()
    q.run_backtest(days=40, step=20)
    first = seen[0][2]["jobs"][0]
    assert first["eta_s"] is not None and abs(first["eta_s"] - 2 * per) <= 1 and seen[0][2]["text"].endswith(first["eta"])


# ================================================================================================ the history; the endpoint
def test_the_history_counts_its_series_then_its_days_and_the_endpoint_tells_it(tmp_path):
    """The recorded month: the series asked of the history (each request's tickers), then the meeting-pricing days one
    by one; ``/api/progress`` and the status the pages poll say what runs ({"busy": false} when nothing does), signed
    in only."""
    days = ["2026-11-03", "2026-11-02", "2026-10-27"]
    svc = make_service(tmp_path)
    try:
        hub = svc.progress
        asked, solved = [], []
        real_hist, real_solve = svc.provider.history, svc.history._solve

        def history(items, start, end, timeout=60.0):
            asked.append((len(items), hub.view()["jobs"]))
            return real_hist(items, start, end, timeout=timeout)

        def solve(p, shared):
            solved.append(hub.view()["jobs"])
            return real_solve(p, shared)

        svc.provider.history = history
        svc.history._solve = solve
        res = svc.history.sync(only=days)
        assert res["computed"] == 3 and asked and len(solved) == 3
        total = sum(k for k, _ in asked)
        done = 0
        for k, jobs in asked:
            job = jobs[0]
            assert (job["id"], job["phase"], job["unit"], job["done"], job["total"]) == ("history", "fetch", "seri", done, total)
            assert job["short"] == "tarihçe %d/%d" % (done, total)
            done += k
        assert [j[0]["short"] for j in solved] == ["PPK geçmişi 0/3", "PPK geçmişi 1/3", "PPK geçmişi 2/3"]
        assert solved[0][0]["title"] == "Tarihçe: PPK fiyatlama geçmişi" and solved[0][0]["unit"] == "gün"
        assert hub.view()["busy"] is False
        runs = hub.runs()["history"]
        assert runs["fetch"]["units"] == total and runs["mpc"]["units"] == 3 and runs["mpc"]["per_unit"] > 0
        # a sync cut short by an error (Bloomberg gone in the middle of its requests): its progress does not stay behind
        def broken(items, start, end, timeout=60.0):
            raise RuntimeError("Bloomberg yanıt vermedi")

        svc.provider.history = broken
        with pytest.raises(RuntimeError):
            svc.history.sync(only=days[:1])
        assert hub.view()["busy"] is False and svc.history.state["phase"] == "idle"
        # the endpoint and the status (the HTTP part last)
        job = hub.begin("bt", "geri test", "Geri test", "yeniden kurma", total=25)
        job.at(12, "2026-03-14", qq.bt_month("2026-03-14"))
        assert svc.quant.status()["progress"]["text"] == "geri test 12/25"
        with TestClient(create_app(svc)) as client:
            assert client.get("/api/progress").status_code == 401
            head = auth(svc, "Hesap Okur")
            body = client.get("/api/progress", headers=head).json()
            assert body["busy"] is True and body["text"] == "geri test 12/25" and body["jobs"][0]["step"] == "Mart 2026 · 14.03.2026 kapanışıyla"
            assert re.match(r"^\d\d:\d\d:\d\d$", body["jobs"][0]["since"]) and body["jobs"][0]["title"] == "Geri test"
            assert client.get("/api/status", headers=head).json()["progress"]["text"] == "geri test 12/25"
            hub.end(job)
            assert client.get("/api/progress", headers=head).json() == {"busy": False, "jobs": [], "eta_s": None, "eta": "", "text": ""}
            assert client.get("/api/status", headers=head).json()["progress"]["busy"] is False
    finally:
        svc.stop()
