"""Hesap: where the long calculations are - counters the loops that do them update, one view read by ``/api/progress``
and by the status the pages poll (the top bar's "Hesap" indicator, the quant pages' banner).

**Jobs** (:data:`ORDER`):

* ``quant`` - the quant worker's full fit (``tto/quant.py``): its steps done / all and the one running.  The steps are
  the fit's own ``timing`` keys, counted as the families write them (:class:`Steps` - nothing added to their code);
  their order and durations are the last fit's;
* ``ml`` - the Makine öğrenmesi family's models fitted / to fit in that fit (``tto/quantml.py``: the ones its cache
  does not have - none on another fit of the same data, every one after a start);
* ``bt`` - the walk-forward backtest (``tto/quantbt.py``): refits done / all and the month of the one under way;
* ``history`` - the history sync (``tto/history.py``): the series fetched / to fetch, then the meeting-pricing days
  computed / to compute.

**Cheap.**  A job's counters are attributes the one thread that runs it writes (``done += 1``) - no lock, nothing
computed in the loops; the view reads them as they are (a count one behind is no harm).

**Time left** (:meth:`Progress.eta`) - shown with "~", never below zero, never without a measure:

* a job of like units (models, refits, series, days): the units left × the time of one - this run's mean once
  :data:`MIN_UNITS` are done, before that the last run's -, the one under way less what it has taken (at least zero);
  an ML model's time is the fit's own (the lines whose models the cache has are not counted in it);
* the fit: the last fit's durations of the steps still to come - of a fit of the same kind: the first after a start
  (every cache empty: the ML models, the levels' calibrations) or a later one -, the step under way less what it has
  taken; the ML step by its models while they are fitted;
* the backtest never past the end of its time budget; an estimate above :data:`MAX_ETA` is not shown.

Jobs at the same time run side by side (threads of their own): the top bar's time is the longest one.  The durations
are kept in the store (:data:`RUNS_KEY`) - the first fit after an update has the last one's.
"""
from __future__ import annotations

import datetime as _dt
import math
import threading
import time
from typing import Any, Callable, Dict, Optional, Sequence

#: the jobs, in the order the top bar and the details list them
ORDER = ("quant", "ml", "bt", "history")
#: the store's record of the last runs: job -> kind -> {"order", "at", "total"} (the fit) | {"per_unit", "units", "s"}
RUNS_KEY = "progress.runs"
#: this run's own pace counts once this many units are done (the first ones carry the start's costs)
MIN_UNITS = 3
#: an estimate above this (seconds) is not shown
MAX_ETA = 7200.0
MONTHS_TR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")


def eta_text(s: Optional[float]) -> str:
    """The time left as the top bar says it: "" (no measure), "az kaldı" (under 10 s), "~40 sn", "~3 dk", "~1 sa 5 dk"."""
    if s is None:
        return ""
    if s < 10.0:
        return "az kaldı"
    if s < 50.0:
        return "~%d sn" % (int(math.ceil(s / 10.0)) * 10)
    m = max(1, int(round(s / 60.0)))
    if m < 60:
        return "~%d dk" % m
    return "~%d sa %d dk" % divmod(m, 60) if m % 60 else "~%d sa" % (m // 60)


def month_text(day: str) -> str:
    """"2026-03-14" -> "Mart 2026" (the month a backtest's refit is on)."""
    try:
        d = _dt.date.fromisoformat(str(day)[:10])
    except ValueError:
        return ""
    return "%s %d" % (MONTHS_TR[d.month - 1], d.year)


class Job(object):
    """One calculation under way: ``done`` of ``total`` units (``None``: not known yet), the step it is on (``step``;
    ``label``: what the screen calls it), since when.  Its own thread writes, the view reads."""

    __slots__ = ("id", "name", "title", "unit", "phase", "done", "total", "step", "label", "t0", "t_last", "since", "spent",
                 "deadline", "plan", "marks", "labels", "_clock")

    def __init__(self, jid: str, name: str, title: str, unit: str, phase: str, total: Optional[int], clock: Callable[[], float],
                 plan: Optional[Dict[str, Any]] = None, labels: Optional[Dict[str, str]] = None, deadline: Optional[float] = None):
        self.id, self.name, self.title, self.unit, self.phase = jid, name, title, unit, phase
        self.done = 0
        self.total = total
        self.step = ""
        self.label = ""
        self._clock = clock
        self.t0 = self.t_last = clock()
        self.since = _dt.datetime.now().replace(microsecond=0)
        self.spent = 0.0                        # the units' own time, when they say it (an ML model's fit)
        self.deadline = deadline                # (the clock's) - the backtest's budget
        self.plan = plan                        # the fit: the last fit's {"order", "at", "total"} ("at": None - never timed)
        self.marks: Dict[str, float] = {}       # the fit: step -> seconds from the start when it was done
        self.labels = labels or {}
        if plan is not None:
            self._next()

    def tick(self, n: int = 1, spent: Optional[float] = None) -> None:
        """``n`` more units done (``spent``: the seconds they took themselves)."""
        self.done += n
        if spent is not None:
            self.spent += spent
        self.t_last = self._clock()

    def at(self, done: int, step: str = "", label: str = "") -> None:
        """``done`` units done, the next under way (``step``, ``label``)."""
        self.done = done
        self.step, self.label = step, label
        self.t_last = self._clock()

    def passed(self, key: str) -> None:
        """A step of the fit done (its ``timing`` key written): the next one of the last fit's order is under way."""
        if key in self.marks:
            return
        now = self._clock()
        self.marks[key] = now - self.t0
        self.done = len(self.marks)
        self.t_last = now
        self._next()

    def _next(self) -> None:
        nxt = next((k for k in (self.plan or {}).get("order") or () if k not in self.marks), "")
        self.step, self.label = nxt, self.labels.get(nxt, nxt)


class Steps(dict):
    """The fit's ``timing``: each step's time as the families write it - and, as they write it, that step done
    (:meth:`Job.passed`).  A dict like any other to the code that reads it."""

    __slots__ = ("job",)

    def __init__(self, job: Optional[Job]):
        super().__init__()
        self.job = job

    def __setitem__(self, key: str, value: Any) -> None:
        dict.__setitem__(self, key, value)
        if self.job is not None:
            self.job.passed(key)


class Progress(object):
    """The jobs under way (one of each at a time) and the last runs' durations."""

    def __init__(self, store: Any = None, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.clock = clock
        self.jobs: Dict[str, Job] = {}
        self._runs: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ what the loops call
    def begin(self, jid: str, name: str, title: str, unit: str, total: Optional[int] = None, phase: str = "",
              plan: Optional[Dict[str, Any]] = None, labels: Optional[Dict[str, str]] = None, budget: Optional[float] = None) -> Job:
        """A job starts (``budget``: seconds it may take at most - the backtest's)."""
        job = Job(jid, name, title, unit, phase, total, self.clock, plan, labels)
        if budget is not None:
            job.deadline = job.t0 + budget
        self.jobs[jid] = job
        return job

    def end(self, job: Optional[Job], ok: bool = True, kind: Optional[str] = None) -> None:
        """The job is over; ``ok``: it ran to its end - its durations are the next run's measure (``kind``: of which
        runs - the fit's "cold" / "warm"; else the job's phase)."""
        if job is None:
            return
        if self.jobs.get(job.id) is job:
            del self.jobs[job.id]
        if not ok:
            return
        took = self.clock() - job.t0
        if job.marks:
            order = sorted(job.marks, key=job.marks.get)
            rec: Dict[str, Any] = {"order": order, "at": [round(job.marks[k], 3) for k in order], "total": round(took, 3)}
        elif job.done > 0:
            rec = {"per_unit": round((job.spent or took) / job.done, 4), "units": job.done, "s": round(took, 3)}
        else:
            return
        rec["day"] = _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
        with self._lock:
            runs = dict(self.runs())
            mine = dict(runs.get(job.id) or {})
            mine[kind or job.phase or "run"] = rec
            runs[job.id] = mine
            self._runs = runs
            if self.store is not None:
                try:
                    self.store.put(RUNS_KEY, runs)
                except Exception:  # noqa: BLE001 - the measure of the next run is not worth the calculation
                    pass

    def runs(self) -> Dict[str, Any]:
        """The last runs' durations (the store's, read once)."""
        if self._runs is None:
            v = None
            if self.store is not None:
                try:
                    v = self.store.get(RUNS_KEY)
                except Exception:  # noqa: BLE001 - no record: no estimate
                    v = None
            self._runs = v if isinstance(v, dict) else {}
        return self._runs

    def last(self, jid: str, kind: str) -> Optional[Dict[str, Any]]:
        rec = (self.runs().get(jid) or {}).get(kind)
        return rec if isinstance(rec, dict) else None

    # ------------------------------------------------------------------ the time left
    def eta(self, job: Job, now: Optional[float] = None) -> Optional[float]:
        """Seconds left (``None``: no measure, or not believable) - the rule of the module's doc."""
        now = self.clock() if now is None else now
        left = self._fit_left(job, now) if job.plan is not None else self._units_left(job, now)
        if left is None:
            return None
        if job.deadline is not None:
            left = min(left, job.deadline - now)
        left = max(0.0, left)
        return left if left <= MAX_ETA else None

    def _units_left(self, job: Job, now: float) -> Optional[float]:
        if job.total is None:
            return None
        left = job.total - job.done
        if left <= 0:
            return 0.0
        if job.done >= MIN_UNITS:
            per = (job.spent or (job.t_last - job.t0)) / job.done
        else:
            per = (self.last(job.id, job.phase or "run") or {}).get("per_unit")
        if not per or per <= 0:
            return None
        return max(0.0, per - (now - job.t_last)) + (left - 1) * per

    def _fit_left(self, job: Job, now: float) -> Optional[float]:
        plan = job.plan or {}
        order, at, total = plan.get("order") or [], plan.get("at"), plan.get("total")
        if not at or total is None or len(at) != len(order):
            return None
        durs = {k: at[i] - (at[i - 1] if i else 0.0) for i, k in enumerate(order)}
        tail = max(0.0, total - at[-1])
        pending = [k for k in order if k not in job.marks]
        if not pending:
            return max(0.0, tail - (now - job.t_last))
        cur = pending[0]
        cur_left = max(0.0, durs[cur] - (now - job.t_last))
        sub = self.jobs.get(cur)                         # (a step that counts its own units: the ML family's models)
        if sub is not None and sub is not job:
            own = self._units_left(sub, now)
            if own is not None:
                cur_left = own
        return cur_left + sum(durs[k] for k in pending[1:]) + tail

    # ------------------------------------------------------------------ the view
    def view(self, only: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """What runs now: each job with its counts, step, since when and the time left; ``text`` the top bar's line
        ("Quant 14/26 · ML 240/480 · geri test 12/25 · ~3 dk"); ``busy`` false and nothing else when idle."""
        now = self.clock()
        jobs = []
        for jid in ORDER:
            job = self.jobs.get(jid)
            if job is None or (only is not None and jid not in only):
                continue
            jobs.append(self._job_view(job, now))
        etas = [j["eta_s"] for j in jobs if j["eta_s"] is not None]
        eta = max(etas) if etas else None
        return {"busy": bool(jobs), "jobs": jobs, "eta_s": eta, "eta": eta_text(eta),
                "text": " · ".join([j["short"] for j in jobs] + ([eta_text(eta)] if eta is not None else []))}

    def _job_view(self, job: Job, now: float) -> Dict[str, Any]:
        total = job.total
        if job.plan is not None:
            total = len(set(job.plan.get("order") or ()) | set(job.marks))
        done = min(job.done, total) if total is not None else job.done
        eta = self.eta(job, now)
        return {"id": job.id, "name": job.name, "title": job.title, "phase": job.phase, "unit": job.unit, "done": done, "total": total,
                "step": job.label or job.step, "since": job.since.strftime("%H:%M:%S"), "elapsed_s": int(round(now - job.t0)),
                "eta_s": None if eta is None else int(round(eta)), "eta": eta_text(eta),
                "short": "%s %d/%d" % (job.name, done, total) if total is not None else "%s %d" % (job.name, done)}
