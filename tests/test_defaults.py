"""What every user starts with: no scenario step per meeting (PPK ima) and an empty VİOP target table - the file's
values of the day it was saved are nobody's choice today.  A user's own values are kept as before."""
from __future__ import annotations

from conftest import cell, make_service
from tto import extras as ex
from tto.store import Store


def test_the_steps_and_the_target_table_start_empty(service):
    refs = ex.empty_default_refs()
    assert len(refs) == 3 * 80 + 5 * 8 and refs[0] == "OIS_MAIN!U10" and refs[-1] == "VIOP!P338"
    for ref in ("OIS_MAIN!U10", "OIS_MAIN!V11", "OIS_MAIN!W12", "OIS_MAIN!W89", "VIOP!L331", "VIOP!N332", "VIOP!P338"):
        assert cell(service, ref) is None, ref
    assert cell(service, "VIOP!K330") == "Target" and cell(service, "VIOP!P330") == "Hedef değer"     # the table is there
    # a blank step follows the scenario base: with the file's base (B3 = 1: the implied path) each scenario is the
    # market's path - the three scenarios are one
    x, y, z = (cell(service, "OIS_MAIN!%s40" % c) for c in "XYZ")
    assert x == y == z
    # what a user types is theirs
    u = service.login("Boş Varsayılan")["user"]
    try:
        service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!U11", "value": "-75"}, {"ref": "VIOP!P331", "value": "-150"}])
        assert cell(service, "OIS_MAIN!U11", u) == -75.0 and cell(service, "VIOP!P331", u) == -150.0
        assert cell(service, "OIS_MAIN!U11") is None and cell(service, "VIOP!P331") is None
    finally:
        service.reset_inputs(u, "tto")


def test_a_file_the_blank_steps_do_not_fit_keeps_its_steps(tmp_path, monkeypatch):
    """Where the addition that blanks the steps is left out (a workbook of another layout keeps its own steps), the
    copies a calendar change made of them stay too - and the clean-up waits for a file the addition fits."""
    def no_fit(model):
        raise ValueError("başka düzen")
    monkeypatch.setitem(ex._BUILDERS, "tto", tuple((n, no_fit if n == ex.EMPTY_NAME else c, b)
                                                    for n, c, b in ex._BUILDERS["tto"]))
    store = Store(str(tmp_path / "tto.db"))
    store.set_shared_inputs("tto", {"OIS_MAIN!U11": -100.0}, "takvim")
    store.close()
    svc = make_service(tmp_path)
    try:
        assert any(x.startswith(ex.EMPTY_NAME + ":") for x in svc.books["tto"].left_out)
        assert svc.store.shared_inputs("tto")[("tto", "OIS_MAIN!U11")] == -100.0
        assert not svc.store.get("migrated.empty_defaults")
    finally:
        svc.stop()


def test_old_shared_copies_of_the_file_values_go_once(tmp_path):
    """A calendar change used to carry the file's steps as shared inputs: the first start of this version drops such
    copies of the cells that now start empty - only those - and only once."""
    store = Store(str(tmp_path / "tto.db"))
    store.set_shared_inputs("tto", {"OIS_MAIN!U11": -100.0, "OIS_MAIN!W40": -50.0, "VIOP!P331": -150.0, "OIS_MAIN!P10": 46366.0},
                            "takvim")
    store.close()
    svc = make_service(tmp_path)
    try:
        assert svc.store.shared_inputs("tto") == {("tto", "OIS_MAIN!P10"): 46366.0}      # a meeting date is no step
        assert cell(svc, "OIS_MAIN!U11") is None and cell(svc, "VIOP!P331") is None
        assert svc.store.get("migrated.empty_defaults")
        svc.store.set_shared_inputs("tto", {"OIS_MAIN!U12": -25.0}, "biri")
    finally:
        svc.stop()
    again = make_service(tmp_path)                                                       # a restart does not drop it again
    try:
        assert again.store.shared_inputs("tto")[("tto", "OIS_MAIN!U12")] == -25.0
    finally:
        again.stop()
