"""Günlük İşlemler: the cost against mid as the desk reads it ("Mid'e göre": + better than mid, in the trade's favour)
in the day's file."""
from __future__ import annotations

import pytest

from helpers import read_xlsx


@pytest.fixture(scope="module")
def desk(module_service):
    """A blotter of its own (the tests change its trades)."""
    svc = module_service
    return svc, svc.login("Düzenle A")["user"], svc.login("Düzenle B")["user"]


def market(svc, tenor):
    """The mid (par) and the annuity of an OIS tenor, as the form prices it."""
    row = {r["tenor"]: r for r in svc.ois_market(None)["tenors"]}[tenor]
    return row["par"], row["annuity"]


# ---------------------------------------------------------------------------------------------- "Mid'e göre"
def test_the_days_file_says_the_cost_against_mid_the_desks_way(desk):
    """The desk: a PAY done 67 bp under mid is 67 bp in its favour.  The day's file says "Mid'e göre" - + better than mid
    (in the trade's favour), − worse - for a PAY and a RECEIVE either side of mid; the stored cost (+ worse: paid) is as it
    was, so a trade of before reads the same."""
    svc, a, _ = desk
    mid, _ = market(svc, "5Y")
    made = {}
    for side, level, better in (("PAY", mid - 0.0067, True), ("PAY", mid + 0.0067, False), ("RECEIVE", mid + 0.0067, True),
                                ("RECEIVE", mid - 0.0067, False)):
        note = "mid %s %s" % (side, "iyi" if better else "kötü")
        q = svc.add_ois(a, {"strategy": "outright", "side": side, "tenor": "5Y", "level": level, "dv01": 1000, "note": note})
        assert q["info"]["cost_bp"] == pytest.approx(-67.0 if better else 67.0)          # the stored cost: + worse than mid
        made[note] = (q, better)
    lst = read_xlsx(svc.blotter_export(a)[0])["İşlem listesi"]
    cells = {v: k for k, v in lst.items() if isinstance(v, str)}
    head = int(cells["OIS"][1:]) + 1
    assert [lst["%s%d" % (c, head)] for c in "IJKLM"] == ["DV01 ($)", "Mid'e göre (bp)", "Mid'e göre ($)", "Karşı taraf", "Not"]
    found = {lst.get("M%d" % r): r for r in range(head + 1, head + 200) if lst.get("M%d" % r)}
    for note, (q, better) in made.items():
        r = found[note]
        assert lst["J%d" % r] == pytest.approx(-q["info"]["cost_bp"]) and lst["K%d" % r] == pytest.approx(-q["info"]["cost_usd"])
        assert (lst["J%d" % r] > 0) == better and (lst["K%d" % r] > 0) == better
