"""OIS · PPK's FRA lists with the desk's buckets (18.11.2026, the desk: "FRA listesinde de böyle gösterelim, bana hangi
bucket'lara kaçtan ne DV01 pozisyonu geleceğini de göreyim"): each FRA's start and end leg - the buckets a leg goes to
in Günlük İşlemler (one between the desk's buckets split between the two around it, linearly in months: 15M half 1Y and
half 18M, 27M ¾ 2Y and ¼ 3Y), its DV01 ($, + pay) done
in the row's YÖN at its Nominal and its rate; the 15 best the same as their FRA in the whole list; booked from the
list, Günlük İşlemler puts the legs in those buckets with those DV01s."""
from __future__ import annotations

import re

import pytest

from conftest import cell
from tto import blotter as bl
from tto.xl import numfmt


def panels(svc, user):
    return {p["id"]: p for p in svc.view(user, "ois")["panels"]}


def by_row(panel):
    """A table's rows by sheet row, each its cells' texts (the two added columns last)."""
    d = panel["data"]
    return {r: [c.get("t") for c in row] for r, row in zip(d["r"], d["rows"])}


def g(svc, col, r):
    return cell(svc, "OIS_MAIN!%s%d" % (col, r))


def money(v):
    return numfmt.format_value(abs(v), "#,##0", numfmt.TR) + " $"


def leg_text(months, sign, dv01, rate):
    """A leg's cell: each bucket it goes to with its share of the DV01 (15M: half 1Y, half 18M), then the leg's rate."""
    return " + ".join("%s %s%s" % (bl.month_label(b), sign, money(abs(dv01) * w)) for b, w in bl.bucket_split(months)) + " · %" + pct(rate)


def pct(v):
    return numfmt.format_value(v * 100.0, "0.00", numfmt.TR)                    # (as Excel rounds: 34,425 → 34,43)


def test_the_fra_lists_say_where_each_leg_goes(service):
    u = service.login("FRA kova")["user"]
    ps = panels(service, u)
    full, top = ps["B21"], ps["B11"]
    assert full["data"]["c"][-2:] == ["Başl. kova", "Bitiş kova"] and top["data"]["c"][-2:] == ["Başl. kova", "Bitiş kova"]
    rows = by_row(full)
    assert rows[335][-2:] == ["Başlangıç bacağı → kova", "Bitiş bacağı → kova"]
    seen = set()
    for r in range(336, 439):
        m1, m2, yon = g(service, "M", r), g(service, "N", r), g(service, "D", r)
        start, end = rows[r][-2:]
        sign = {"RECEIVE": 1, "PAY": -1}.get(yon, 0)                         # a RECEIVE FRA pays its start leg
        mark = {1: "+", -1: "−", 0: ""}
        assert end == leg_text(int(m2), mark[-sign], g(service, "L", r), g(service, "J", r)), (r, end)
        if m1 == 0:
            assert start == ""                                                 # from the spot: one leg
        else:
            assert start == leg_text(int(m1), mark[sign], g(service, "K", r), g(service, "I", r)), (r, start)
        seen.add((int(m1), int(m2)))
    # the cases the desk named: 12x15's end in 18M, 15x18's both legs in 18M, 24x27's end in 3Y
    label = {(int(g(service, "M", r)), int(g(service, "N", r))): r for r in range(336, 439)}
    assert {(12, 15), (15, 18), (24, 27)} <= seen
    assert re.match(r"^1Y \S+ \$ \+ 18M \S+ \$ · %", rows[label[(12, 15)]][-1]) and re.match(r"^1Y \S+ \$ · %", rows[label[(12, 15)]][-2])
    assert re.match(r"^1Y \S+ \$ \+ 18M \S+ \$ · %", rows[label[(15, 18)]][-2]) and re.match(r"^18M \S+ \$ · %", rows[label[(15, 18)]][-1])
    assert re.match(r"^2Y \S+ \$ \+ 3Y \S+ \$ · %", rows[label[(24, 27)]][-1]) and re.match(r"^2Y \S+ \$ · %", rows[label[(24, 27)]][-2])
    # the 15 best: the same cells as their FRA in the whole list (found by its label)
    top_rows = by_row(top)
    assert top_rows[65][-2:] == ["Başlangıç bacağı → kova", "Bitiş bacağı → kova"]
    names = {g(service, "A", r): r for r in range(336, 439)}
    checked = 0
    for r in range(66, 81):
        name, yon = g(service, "B", r), g(service, "E", r)
        if not name:
            continue
        src = names[name]
        assert yon == g(service, "D", src)
        assert top_rows[r][-2:] == rows[src][-2:], (name, top_rows[r][-2:], rows[src][-2:])
        checked += 1
    assert checked >= 10


def test_booked_from_the_list_the_blotter_puts_the_legs_in_those_buckets(tmp_path):
    """A 12x15 FRA of the list done in Günlük İşlemler at the list's Nominal: its legs land in the buckets the list said,
    with its DV01s (the list rounds them to the dollar)."""
    from conftest import make_service
    svc = make_service(tmp_path)
    try:
        u = svc.login("FRA kova B")["user"]
        r = next(r for r in range(336, 439) if (g(svc, "M", r), g(svc, "N", r)) == (12.0, 15.0))
        nominal, yon = g(svc, "E", r), g(svc, "D", r)
        side = yon if yon in ("RECEIVE", "PAY") else "RECEIVE"
        fra = svc.add_ois(u, {"strategy": "fra", "side": side, "start_months": 12, "end_months": 15, "level": "35,10",
                              "nominal": nominal})
        start, end = fra["legs"]
        assert start["dv01"] == pytest.approx(g(svc, "K", r), abs=1.0) and end["dv01"] == pytest.approx(g(svc, "L", r), abs=1.0)
        assert [cell(svc, "Günlük İşlemler!L%d" % k) for k in (3, 4, 5)] == ["1Y", "1Y", "18M"]
        assert [cell(svc, "Günlük İşlemler!I%d" % k) for k in (4, 5)] == pytest.approx([end["dv01"] / 2] * 2)
        row = by_row(panels(svc, u)["B21"])[r]
        assert row[-2].startswith("1Y ") and re.match(r"^1Y \S+ \$ \+ 18M \S+ \$ · %", row[-1])
    finally:
        svc.stop()
