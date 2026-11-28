"""Carry & Roll's "Yıllık vol" from the realized vol (C8 of 28.11.2026 - ``extras.CARRY_VOL_NAME``): each tenor's default is
the daily σ of its TRY OIS quote's moves (bp) × √252, from EK_VAR (DV01 Risk → VaR's covariances, the window the user chose
there); 18M halfway between 1Y and 2Y with their covariance; a value typed is the user's, Delete brings the default back; no
history, no default (blank, as before) - so C+R/vol fills."""
from __future__ import annotations

import datetime as _dt
import math
import random

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto.xl.tokenizer import index_to_col
from tto.xl.values import serial_to_date

GROUPS = ("ref", "ois", "off", "xccy")


def _fill(svc, n: int = 300, seed: int = 11):
    """A random walk a day for every series of the history's TRY curves (their main ticker), up to the day before today."""
    rng = random.Random(seed)
    today = serial_to_date(svc.books["tto"].engine.clock.today())
    days, d = [], today - _dt.timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= _dt.timedelta(days=1)
    days.reverse()
    common = [rng.gauss(0.0, 0.2) for _ in days]
    for s in (x for x in svc.history.snapshot()["defs"] if x.group in GROUPS):
        level, path = 36.0 + float(getattr(s, "months", 0) or 0) / 60.0, []
        for k in range(len(days)):
            level += common[k] * (1.0 if s.group != "ref" else 0.2) + rng.gauss(0.0, 0.05)
            path.append(level)
        svc.store.hist_upsert(s.id, list(zip(days, path)))
    svc.history.rev += 1


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("carryvol"))
    yield s
    s.stop()


def cov(svc, window: int, i: int, j: int, user=None) -> float:
    """EK_VAR's OIS covariance of buckets i, j (1-based, VAR_BUCKETS) in window k (1-based)."""
    row = ex.VAR_COV_ROW + 20 * (window - 1) + (i - 1)
    return cell(svc, "%s!%s%d" % (ex.VAR_SHEET, index_to_col(ex.VAR_OIS_COL + j - 1), row), user)


def bucket(label: str) -> int:
    return ex.VAR_BUCKETS.index(label) + 1


def test_without_history_the_vol_stays_blank(tmp_path):
    s = make_service(tmp_path)
    try:
        assert {cell(s, "C & R!N%d" % r) for r in range(24, 40)} == {""} and {cell(s, "C & R!O%d" % r) for r in range(24, 40)} == {""}
    finally:
        s.stop()


def test_the_vol_is_the_tenors_realized_vol_a_year(svc):
    _fill(svc)
    u = svc.login("K8 carry vol")["user"]
    k = 1 + [w for w, _ in ex.VAR_WINDOWS].index(ex.VAR_WINDOW_DEFAULT)                 # ("1 yıl": the DV01 page's default)
    for r, (label, weights) in zip(range(24, 40), ex.CARRY_VOL_TENORS):
        var = sum(w1 * w2 * cov(svc, k, bucket(b1), bucket(b2), u) for b1, w1 in weights for b2, w2 in weights)
        assert cell(svc, "C & R!N%d" % r, u) == pytest.approx(math.sqrt(var) * math.sqrt(252), rel=1e-12), label
    # 18M: halfway between 1Y and 2Y - ¼σ²(1Y) + ¼σ²(2Y) + ½cov
    i, j = bucket("1Y"), bucket("2Y")
    want = math.sqrt(0.25 * cov(svc, k, i, i, u) + 0.25 * cov(svc, k, j, j, u) + 0.5 * cov(svc, k, i, j, u)) * math.sqrt(252)
    assert cell(svc, "C & R!N30", u) == pytest.approx(want, rel=1e-12)
    # C+R/vol fills where the carry is there
    g = cell(svc, "C & R!G27", u)
    if type(g) is float:
        assert cell(svc, "C & R!O27", u) == pytest.approx(g / cell(svc, "C & R!N27", u), rel=1e-12)


def test_a_value_typed_wins_and_delete_brings_the_default_back(svc):
    _fill(svc)
    u = svc.login("K8 carry vol yazılan")["user"]
    default = cell(svc, "C & R!N27", u)
    assert type(default) is float and default > 0
    svc.set_inputs(u, "tto", [{"ref": "C & R!N27", "value": "150"}])
    assert cell(svc, "C & R!N27", u) == 150.0 and cell(svc, "C & R!N27") == default          # (the user's own)
    svc.set_inputs(u, "tto", [{"ref": "C & R!N27", "value": ""}])
    assert cell(svc, "C & R!N27", u) == default


def test_the_window_is_the_one_chosen_on_dv01_risk(svc):
    _fill(svc)
    u = svc.login("K8 carry vol pencere")["user"]
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!AB%d" % ex.VAR_PARAM, "value": "3 ay"}])
    k = 1 + [w for w, _ in ex.VAR_WINDOWS].index("3 ay")
    i = bucket("5Y")
    assert cell(svc, "C & R!N34", u) == pytest.approx(math.sqrt(cov(svc, k, i, i, u)) * math.sqrt(252), rel=1e-12)
    assert cell(svc, "C & R!N34", u) != cell(svc, "C & R!N34")                               # (the desk's "1 yıl" elsewhere)
