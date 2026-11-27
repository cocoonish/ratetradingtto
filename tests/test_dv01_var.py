"""DV01 Risk → VaR (``tto/extras.py``: ``VAR_NAME``; ``tto/varrisk.py``).

The desk, 27.11.2026: "Bir de dv01 risk'e var hesaplamasi koyalim. Burada offshore'u, ve ois'e ayri ayri bakacagiz. Ois
tarafini da onshore ve ois olarak ikiye ayiralim, bunlarin toplamina ve ayri ayri da bakacagiz. Realized vol'den
hesaplayacagiz".

The checks: from a history made here (each curve a random walk of known shape, every series the history keeps), the
page's σ of each bucket and the VaR of the four books - Offshore on the offshore curve's moves, Onshore, TLREF and their
total on the OIS curve's - are the ones worked out by hand (sample covariance of the last window's moves, z of the
confidence, √horizon); each user's window, confidence and horizon are their own; today's point is left out; without
history the page says so; the page shows the tab; the workbook is otherwise the one before, cell for cell."""
from __future__ import annotations

import datetime as _dt
import math
import os
import random
from statistics import NormalDist

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto import varrisk as vr
from tto.books import remove_sheets
from tto.history import tenor_months
from tto.xl.model import COLS, Model, parse_a1
from tto.xl.tokenizer import index_to_col
from tto.xl.values import serial_to_date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUCKETS = ex.VAR_BUCKETS
GROUPS = ("ref", "ois", "off", "xccy")


def _today(svc) -> _dt.date:
    return serial_to_date(svc.books["tto"].engine.clock.today())


def _days(end: _dt.date, n: int):
    """The ``n`` week days before ``end`` (oldest first)."""
    out, d = [], end - _dt.timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= _dt.timedelta(days=1)
    return out[::-1]


def _walks(defs, days, seed: int):
    """A level a day (percent) for every series of the history's TRY curves: per curve a common move, a slope and a
    little of each tenor's own (so no close looks like a wrong print to the history's cleaning); TLREF in PPK steps."""
    rng = random.Random(seed)
    out = {}
    shape = {"ois": (0.18, 0.06, 0.02), "off": (0.45, 0.15, 0.03), "xccy": (0.45, 0.15, 0.03)}
    common = {g: [rng.gauss(0.0, shape[g][0]) for _ in days] for g in ("ois", "off")}
    slope = {g: [rng.gauss(0.0, shape[g][1]) for _ in days] for g in ("ois", "off")}
    for d in defs:
        if d.group not in GROUPS:
            continue
        if d.group == "ref":
            level, path = 38.0, []
            for k in range(len(days)):
                if k and k % 30 == 0:
                    level -= rng.choice((0.5, 1.0, 1.5))
                path.append(level + rng.gauss(0.0, 0.01))
            out[d.id] = path
            continue
        g = "ois" if d.group == "ois" else "off"
        m = float(d.months)
        level, path = 36.0 + m / 60.0 + (3.0 if g == "off" else 0.0), []
        own = shape[d.group][2] * (4.0 if m < 1.0 and g == "off" else 1.0)
        for k in range(len(days)):
            level += common[g][k] + slope[g][k] * min(m, 120.0) / 120.0 + rng.gauss(0.0, own)
            path.append(level)
        out[d.id] = path
    return out


def _fill(svc, seed: int = 7, n: int = 320):
    """The history of every series of the TRY curves (their main ticker only), up to the day before today; tells the
    history a sync wrote (``History.rev``).  Returns ``(defs, days, {series id: [level, ...]})``."""
    defs = [d for d in svc.history.snapshot()["defs"] if d.group in GROUPS]
    days = _days(_today(svc), n)
    levels = _walks(defs, days, seed)
    for sid, path in levels.items():
        svc.store.hist_upsert(sid, list(zip(days, path)))
    svc.history.rev += 1
    return defs, days, levels


def _bucket_levels(defs, levels, curve: str):
    """Each bucket's level a day, by hand: O/N and S/N TLREF (OIS) or O/N and T/N (offshore), 3W halfway between 2W and
    1M, the rest their tenor."""
    by = {}
    for d in defs:
        if d.group == "ref" and curve == "ois":
            by["TLREF"] = levels[d.id]
        elif (d.group == "ois") == (curve == "ois") and d.group != "ref":
            by[d.label] = levels[d.id]
    src = {"O/N": "TLREF", "S/N": "TLREF"} if curve == "ois" else {"S/N": "T/N"}
    out = []
    for b in BUCKETS:
        if b == "3W":
            out.append([(x + y) / 2.0 for x, y in zip(by["2W"], by["1M"])])
        else:
            out.append(by[src.get(b, b)])
    return out


def _cov(defs, levels, curve: str, window: int):
    cols = _bucket_levels(defs, levels, curve)
    moves = [[(c[k] - c[k - 1]) * 100.0 for c in cols] for k in range(1, len(cols[0]))][-window:]
    n = len(moves)
    mean = [sum(x[j] for x in moves) / n for j in range(20)]
    return [[sum((x[i] - mean[i]) * (x[j] - mean[j]) for x in moves) / (n - 1) for j in range(20)] for i in range(20)], n


def _var(d, cov, z, h):
    return z * math.sqrt(h) * math.sqrt(sum(d[i] * cov[i][j] * d[j] for i in range(20) for j in range(20)))


def _paste(svc, user, col: str, values):
    svc.login(user)
    svc.set_inputs(user, "tto", [{"ref": "DV01_RISK!%s%d" % (col, ex.VAR_FIRST + i), "value": str(v)}
                                 for i, v in enumerate(values)])


def _close(a, b, rel=1e-9):
    return abs(a - b) <= rel * max(1.0, abs(b))


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("var"))
    yield s
    s.stop()


@pytest.fixture(scope="module")
def filled(svc):
    return _fill(svc)


def test_the_var_of_each_book_is_worked_out_by_hand(svc, filled):
    defs, days, levels = filled
    user = "var-elle"
    rng = random.Random(11)
    dv = {col: [rng.choice((-1, 1)) * rng.randint(1000, 900000) for _ in BUCKETS] for col in ("AA", "X", "Y")}
    for col, values in dv.items():
        _paste(svc, user, col, values)
    z = NormalDist().inv_cdf(0.99)
    ois, n_ois = _cov(defs, levels, "ois", 250)
    off, n_off = _cov(defs, levels, "off", 250)
    assert (n_ois, n_off) == (250, 250)
    assert cell(svc, "DV01_RISK!AJ29", user) == 4.0                      # "1 yıl", the default
    assert (cell(svc, "DV01_RISK!AK29", user), cell(svc, "DV01_RISK!AL29", user)) == (250.0, 250.0)
    assert _close(cell(svc, "DV01_RISK!AD29", user), z, 1e-14)
    assert cell(svc, "DV01_RISK!AI29", user) == ""
    assert serial_to_date(cell(svc, "DV01_RISK!AH29", user)).isoformat() == days[-1]    # the last close: yesterday's
    for i in range(20):
        r = ex.VAR_FIRST + i
        assert _close(cell(svc, "DV01_RISK!AB%d" % r, user), math.sqrt(off[i][i])), BUCKETS[i]
        assert _close(cell(svc, "DV01_RISK!AC%d" % r, user), math.sqrt(ois[i][i])), BUCKETS[i]
        assert _close(cell(svc, "DV01_RISK!AD%d" % r, user), z * abs(dv["AA"][i]) * math.sqrt(off[i][i]))
        assert _close(cell(svc, "DV01_RISK!AE%d" % r, user), z * abs(dv["X"][i]) * math.sqrt(ois[i][i]))
        assert _close(cell(svc, "DV01_RISK!AF%d" % r, user), z * abs(dv["Y"][i]) * math.sqrt(ois[i][i]))
        assert _close(cell(svc, "DV01_RISK!AG%d" % r, user), z * abs(dv["X"][i] + dv["Y"][i]) * math.sqrt(ois[i][i]))
    total = [x + y for x, y in zip(dv["X"], dv["Y"])]
    want = {"AD": _var(dv["AA"], off, z, 1), "AE": _var(dv["X"], ois, z, 1), "AF": _var(dv["Y"], ois, z, 1),
            "AG": _var(total, ois, z, 1)}
    for col, v in want.items():
        assert _close(cell(svc, "DV01_RISK!%s%d" % (col, ex.VAR_TOTAL), user), v), col
    # the summary: each book's DV01, its VaR, its buckets' own VaRs added up, the difference
    for k, (name, dvc, var, _, _, _) in enumerate(ex.VAR_BOOKS):
        r = ex.VAR_SUMMARY + 1 + k
        assert cell(svc, "DV01_RISK!W%d" % r, user) == name
        assert _close(cell(svc, "DV01_RISK!X%d" % r, user), sum(dv["AA"] if dvc == "AA" else total if dvc == "Z" else dv[dvc]))
        assert _close(cell(svc, "DV01_RISK!Y%d" % r, user), want[var])
        own = sum(cell(svc, "DV01_RISK!%s%d" % (var, ex.VAR_FIRST + i), user) for i in range(20))
        assert _close(cell(svc, "DV01_RISK!Z%d" % r, user), own)
        assert _close(cell(svc, "DV01_RISK!AA%d" % r, user), own - want[var])
        assert own >= want[var] - 1e-6                                  # correlations below 1 never add to it
    # the OIS side together is the VaR of the two vectors added: one curve's moves
    assert want["AG"] <= want["AE"] + want["AF"] + 1e-6


def test_each_user_their_window_confidence_and_horizon(svc, filled):
    defs, _, levels = filled
    a, b = "var-pencere-a", "var-pencere-b"
    d = [100000.0 * (i + 1) * (-1) ** i for i in range(20)]
    for user in (a, b):
        _paste(svc, user, "Y", d)
    svc.set_inputs(b, "tto", [{"ref": "DV01_RISK!AB29", "value": "3 ay"}, {"ref": "DV01_RISK!X29", "value": "95"},
                              {"ref": "DV01_RISK!Z29", "value": "10"}])
    assert cell(svc, "DV01_RISK!AB29", b) == "3 ay" and cell(svc, "DV01_RISK!AB29", a) == ex.VAR_WINDOW_DEFAULT
    assert _close(cell(svc, "DV01_RISK!X29", b), 0.95)
    cov63, n = _cov(defs, levels, "ois", 63)
    assert n == 63 and cell(svc, "DV01_RISK!AL29", b) == 63.0
    z95 = NormalDist().inv_cdf(0.95)
    assert _close(cell(svc, "DV01_RISK!AF%d" % ex.VAR_TOTAL, b), _var(d, cov63, z95, 10))
    cov250, _ = _cov(defs, levels, "ois", 250)
    assert _close(cell(svc, "DV01_RISK!AF%d" % ex.VAR_TOTAL, a), _var(d, cov250, NormalDist().inv_cdf(0.99), 1))
    # every window the list offers
    for label, days in ex.VAR_WINDOWS:
        svc.set_inputs(b, "tto", [{"ref": "DV01_RISK!AB29", "value": label}])
        want = min(days, len(filled[1]) - 1)
        assert cell(svc, "DV01_RISK!AL29", b) == float(want), label
    # a confidence that is not one (40 %): the page says so, no number
    svc.set_inputs(b, "tto", [{"ref": "DV01_RISK!X29", "value": "40"}])
    assert cell(svc, "DV01_RISK!AF%d" % ex.VAR_TOTAL, b) == ""
    assert "Güven düzeyi" in cell(svc, "DV01_RISK!AI29", b)


def test_today_s_point_is_left_out_and_the_stats_follow_the_history(svc, filled):
    defs, days, levels = filled
    user = "var-bugun"
    _paste(svc, user, "AA", [50000.0] * 20)
    before = cell(svc, "DV01_RISK!AD%d" % ex.VAR_TOTAL, user)
    today = _today(svc).isoformat()
    for d in defs:
        if d.group in GROUPS:
            svc.store.hist_upsert(d.id, [(today, levels[d.id][-1] + 5.0)])     # a 500 bp jump today: not a close yet
    svc.history.rev += 1
    assert cell(svc, "DV01_RISK!AD%d" % ex.VAR_TOTAL, user) == before
    made = svc.varrisk.stats["made"]
    assert cell(svc, "DV01_RISK!AD%d" % ex.VAR_TOTAL, user) == before and svc.varrisk.stats["made"] == made   # (kept)
    # a close of the past restated (yesterday's, every offshore tenor 100 bp up): made again once the history says so
    off = [d for d in defs if d.group in ("off", "xccy")]
    for d in off:
        svc.store.hist_upsert(d.id, [(days[-1], levels[d.id][-1] + 1.0)])
    assert cell(svc, "DV01_RISK!AD%d" % ex.VAR_TOTAL, user) == before          # (the history has not told yet)
    svc.history.rev += 1
    assert cell(svc, "DV01_RISK!AD%d" % ex.VAR_TOTAL, user) > before
    for d in off:
        svc.store.hist_upsert(d.id, [(days[-1], levels[d.id][-1])])
    svc.history.rev += 1
    assert _close(cell(svc, "DV01_RISK!AD%d" % ex.VAR_TOTAL, user), before)


def test_offshore_moves_never_reach_the_ois_side(svc, filled):
    """The offshore curve's statistics are its own: OIS σ's are the OIS curve's whatever the offshore one did."""
    defs, _, levels = filled
    ois, _ = _cov(defs, levels, "ois", 250)
    off, _ = _cov(defs, levels, "off", 250)
    user = "var-ayri"
    assert any(abs(math.sqrt(off[i][i]) - math.sqrt(ois[i][i])) > 1.0 for i in range(20))
    for i in range(20):
        r = ex.VAR_FIRST + i
        assert _close(cell(svc, "DV01_RISK!AC%d" % r, user), math.sqrt(ois[i][i]))
        assert _close(cell(svc, "DV01_RISK!AB%d" % r, user), math.sqrt(off[i][i]))


def test_without_history_the_page_says_so(tmp_path):
    s = make_service(tmp_path / "bos")
    try:
        user = "var-bos"
        _paste(s, user, "X", [100000.0] * 20)
        assert cell(s, "DV01_RISK!AI29", user) == "Tarihçe yok: gerçekleşen vol hesaplanamadı"
        assert cell(s, "DV01_RISK!AE%d" % ex.VAR_TOTAL, user) == ""
        assert cell(s, "DV01_RISK!AC33", user) == ""
        assert cell(s, "DV01_RISK!AE33", user) == ""
    finally:
        s.stop()


def test_the_page_shows_the_var_tab(svc, filled):
    user = "var-sayfa"
    _paste(svc, user, "AA", [1000.0 * (i + 1) for i in range(20)])
    view = svc.view(user, "dv01")
    sec = next(s for s in view["sections"] if s["id"] == "var")
    assert sec["title"] == "VaR" and sec["panels"] == ["V1", "V2", "V3"]
    panels = {p["id"]: p for p in view["panels"]}
    grid = panels["V3"]["data"]
    assert grid["c"] == ["W", "AA", "X", "Y", "Z", "AB", "AC", "AD", "AE", "AF", "AG"]
    head = [x.get("t") if isinstance(x, dict) else x for x in grid["rows"][0]]
    assert head == ["Kova", "Offshore", "Onshore", "TLREF", "Onshore + TLREF", "σ offshore (bp/gün)", "σ OIS (bp/gün)",
                    "VaR offshore", "VaR onshore", "VaR TLREF", "VaR onshore + TLREF"]
    assert grid["r"][-1] == ex.VAR_TOTAL
    summary = panels["V2"]["data"]
    names = [row[0].get("t") if isinstance(row[0], dict) else row[0] for row in summary["rows"][1:]]
    assert names == ["Offshore", "Onshore", "OIS (TLREF)", "Onshore + OIS"]
    params = panels["V1"]["data"]
    texts = [x.get("t") if isinstance(x, dict) else x for x in params["rows"][0]]
    assert texts[:2] == ["Güven düzeyi", "99,0%"] or texts[:2] == ["Güven düzeyi", "%99,0"]
    assert "1 yıl" in texts
    # the pasted Offshore column and the parameters are the user's own inputs
    assert any(isinstance(c, dict) and c.get("i") for row in grid["rows"] for c in row)


def test_the_window_list_matches_the_page():
    import json
    with open(os.path.join(ROOT, "tto", "views", "70_dv01.json"), encoding="utf-8") as f:
        view = json.load(f)
    item = next(i for i in view["inputs"] if i["range"] == "AB29")
    assert item["kind"] == "list" and item["options"] == [label for label, _ in ex.VAR_WINDOWS]
    assert ex.VAR_WINDOW_DEFAULT in item["options"]


# ---------------------------------------------------------------------------------------------- the workbook
def _model(with_var: bool) -> Model:
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    builders = ex._BUILDERS["tto"]
    try:
        if not with_var:
            ex._BUILDERS["tto"] = tuple(b for b in builders if b[0] != ex.VAR_NAME)
        assert ex.apply("tto", model) == []
    finally:
        ex._BUILDERS["tto"] = builders
    return model


def test_nothing_else_changes_in_the_workbook():
    """Every cell of every sheet but the VaR's own is the one before (formula, value, look); on DV01_RISK the paste
    area keeps its values, its captions but Z32's (now "Onshore + TLREF") and gets the look of a table."""
    old, new = _model(False), _model(True)
    assert set(new.sheet_index) - set(old.sheet_index) == {ex.VAR_SHEET}
    own = set()
    for rng in ("W29:AM29", "W32:AK53", "W55:AA59"):
        r1, c1, r2, c2 = (int(x) for x in _rng(rng))
        own |= {(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
    for sh in old.sheets:
        ns = new.sheet(sh.name)
        keys = set(sh.fml) | set(ns.fml) | set(sh.consts) | set(ns.consts)
        for rc in keys:
            r, c = divmod(rc, COLS)
            if sh.name == "DV01_RISK" and (r, c) in own:
                continue
            assert (sh.fml.get(rc) is None) == (ns.fml.get(rc) is None), (sh.name, rc)
            if rc in sh.fml:
                assert old.templates[sh.fml[rc]] == new.templates[ns.fml[rc]], (sh.name, index_to_col(c), r)
            assert sh.consts.get(rc) == ns.consts.get(rc), (sh.name, index_to_col(c), r)
    dv_old, dv_new = old.sheet("DV01_RISK"), new.sheet("DV01_RISK")
    for r in range(ex.VAR_FIRST, ex.VAR_FIRST + 20):
        for col in "WXY":
            assert dv_old.consts.get(parse_a1("%s%d" % (col, r))) == dv_new.consts.get(parse_a1("%s%d" % (col, r)))
        assert old.templates[dv_old.fml[parse_a1("Z%d" % r)]] == new.templates[dv_new.fml[parse_a1("Z%d" % r)]]
    assert dv_new.consts.get(parse_a1("Z32")) == "Onshore + TLREF"
    assert (dv_new.consts.get(parse_a1("X32")), dv_new.consts.get(parse_a1("Y32"))) == ("Onshore", "TLREF")


def _rng(text):
    from tto.xl.model import parse_range
    return parse_range(text)


def test_a_workbook_that_changed_there_is_left_as_it_is():
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    model.sheet("DV01_RISK").consts[parse_a1("AA40")] = 5.0
    left = ex.apply("tto", model)
    assert any(x.startswith(ex.VAR_NAME + ":") for x in left), left
    assert ex.VAR_SHEET not in model.sheet_index


# ---------------------------------------------------------------------------------------------- the module's parts
def test_moves_skip_a_day_a_bucket_has_no_level():
    levels = {"TLREF": {"2026-11-02": 40.0, "2026-11-03": 40.0, "2026-11-04": 39.0, "2026-11-05": 39.0},
              "A": {"2026-11-02": 30.0, "2026-11-03": 30.5, "2026-11-05": 31.0},
              "B": {"2026-11-02": 31.0, "2026-11-03": 31.1, "2026-11-04": 31.2, "2026-11-05": 31.0}}
    days, moves = vr.bucket_moves(levels, {"O/N": "TLREF"}, ("O/N", "A", "B"), "2026-11-05")
    # 05.11 is today: left out; 04.11 has no A: neither its move in nor the one out of it
    assert days == ["2026-11-03"]
    assert moves == [[0.0, pytest.approx(50.0), pytest.approx(10.0)]]


def test_a_bucket_between_two_tenors_lies_linear_by_months():
    levels = {"2W": {"a": 30.0, "b": 31.0}, "1M": {"a": 32.0, "b": 32.0}}
    days, moves = vr.bucket_moves(levels, {"3W": ("2W", "1M")}, ("3W",), "z")
    assert tenor_months("3W") == 0.75 and moves == [[pytest.approx(50.0)]]       # (31 + 32)/2 − (30 + 32)/2


def test_tlref_is_carried_a_few_market_days_only():
    days = ["d%02d" % k for k in range(8)]
    out = vr.carried({"d00": 40.0, "d06": 39.0}, days, stale=3)
    assert [out.get(d) for d in days] == [40.0, 40.0, 40.0, 40.0, None, None, 39.0, 39.0]


def test_the_covariance_is_the_sample_one():
    moves = [[1.0, 2.0], [3.0, 1.0], [2.0, 6.0]]
    cov = vr.covariance(moves)
    assert cov[0][0] == pytest.approx(1.0) and cov[1][1] == pytest.approx(7.0) and cov[0][1] == pytest.approx(-0.5) and cov[1][0] == cov[0][1]
    assert vr.covariance(moves[:1]) is None
