"""What a row of a list of bonds holds goes with its bond, not with the row (``tto/rowkeys.py``): DİBS RV (and DİBS Trading),
DİBS ASW, each user's own Eurobond Kotaları.  Every user's values, the desk's, "Elle değer" and the saved scenarios follow
a bond moved and go with a bond replaced or taken off - in one transaction, the one who changed the list told; a database
of an earlier version is taken as it is, once; VİOP's gold contracts take each user's own VİOP price with them."""
from __future__ import annotations

import pytest

from conftest import cell, make_service
from tto import rowkeys as rk
from tto.store import Store, user_key

LIST = "DİBS RV!A5:A54"
ASW = "ASW!B7:B56"


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """One service for the tests of the desk's lists (each test its own bonds and rows)."""
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def row_of(s, user, isin, where=LIST, book="tto"):
    first = int(where.split("!")[1].split(":")[0][1:])
    return s._list_values(user, book, where).index(isin) + first


def test_where_the_values_of_each_row_go():
    assert rk.plan(["X", "Y", ""], ["X", "Y", ""]) == {}
    assert rk.plan(["X", "Y"], ["Y", "X"]) == {0: 1, 1: 0}                       # two bonds swapped
    assert rk.plan(["X", ""], ["", "X"]) == {0: 1, 1: None}                      # moved (what the empty row had goes)
    assert rk.plan(["X", "Y"], ["Z", "Y"]) == {0: None}                          # typed over: X's values go
    assert rk.plan(["X", "Y"], ["X", "X"]) == {1: None}                          # Y left; X twice keeps its own row
    assert rk.plan(["X", "X"], ["X", "Y"]) == {1: 0}                             # X left one of its rows: to the other
    assert rk.plan(["", "Y"], ["X", "Y"]) == {0: None}                           # a bond onto a row with no bond
    assert rk.isin_of(" trt150328t24 ") == "TRT150328T24" and rk.isin_of(3.0) == "" and rk.isin_of(None) == ""


def test_a_bond_moved_takes_what_its_row_held_for_everyone(svc):
    """The desk pastes the list re-sorted (15.03.28 from row 8 to an empty row, 13.09.28 from row 9 to 8): each user's
    manual clean price, known coupon, repo, an "Elle değer", the desk's source and the saved scenarios follow each bond; a
    formula there moves as its value; what is pasted with the list lands as pasted; the one who pasted is told."""
    s = svc
    a, b = s.login("Kayan Liste A")["user"], s.login("Kayan Liste B")["user"]
    ua, ub = user_key(a), user_key(b)
    assert (row_of(s, a, "TRT150328T24"), row_of(s, a, "TRT130928T38")) == (8, 9)
    empty = 5 + max(k for k, v in enumerate(s._list_values(a, "tto", LIST)) if v) + 1
    assert s.set_inputs(a, "tto", [{"ref": "DİBS RV!N8", "value": "98,5"}, {"ref": "DİBS RV!H9", "value": "=1+1"}])["errors"] == []
    assert s.set_inputs(a, "tto", [{"ref": "DİBS RV!AI8", "value": "123"}], allow_adhoc=True)["errors"] == []   # "Elle değer"
    assert s.set_inputs(b, "tto", [{"ref": "DİBS RV!AL8", "value": "40"}, {"ref": "DİBS RV!B8", "value": "ISL0"},
                                   {"ref": "DİBS RV!B9", "value": "BGN"}])["errors"] == []
    assert s.store.user_formulas(ua) == {("tto", "DİBS RV!H9"): "=1+1"}
    s.save_scenario(a, "önce")
    # the paste: 13.09.28 into row 8, 15.03.28 into the empty row (its own source pasted with it), row 9 left blank
    res = s.set_inputs(b, "tto", [{"ref": "DİBS RV!A8", "value": "TRT130928T38"}, {"ref": "DİBS RV!A9", "value": ""},
                                  {"ref": "DİBS RV!A%d" % empty, "value": "TRT150328T24"},
                                  {"ref": "DİBS RV!B%d" % empty, "value": "ISL1"}])
    assert res["errors"] == []
    moved = {m["isin"]: (m["from"], m["to"]) for m in res["row_values"]["moved"]}
    assert moved == {"TRT150328T24": (8, empty), "TRT130928T38": (9, 8)} and res["row_values"]["cleared"] == []
    assert "TRT150328T24 satır 8 → %d" % empty in res["row_values"]["text"] and "1 senaryo" in res["row_values"]["text"]
    # 15.03.28: everyone's values on its new row - the source as pasted
    assert cell(s, "DİBS RV!N%d" % empty, ua) == 98.5 and cell(s, "DİBS RV!AI%d" % empty, ua) == 123.0
    assert cell(s, "DİBS RV!AL%d" % empty, ub) == 40.0 and cell(s, "DİBS RV!B%d" % empty) == "ISL1"
    # 13.09.28 on row 8: its own (the coupon a value now), nothing of 15.03.28's
    assert cell(s, "DİBS RV!H8", ua) == 2.0 and s.store.user_formulas(ua) == {}
    # (nothing typed: the two-way table's default - test_kagit_twoway.py)
    assert cell(s, "DİBS RV!B8") == "BGN" and cell(s, "DİBS RV!N8", ua) == "" and cell(s, "DİBS RV!AL8", ub) == ""
    assert ("tto", "DİBS RV!AI8") not in s.store.user_inputs(ua, "tto")     # (no "Elle değer" left on it)
    assert cell(s, "EK_DIBS!A8") == "TRT130928T38"
    # row 9, empty now: not even the workbook's own source of the bond that was there (ISL1) is left on it
    assert cell(s, "DİBS RV!B9") is None and s.store.shared_inputs("tto")[("tto", "DİBS RV!B9")] is None
    # the saved scenario too: loaded, each bond has its own values again
    values, _ = s.store.scenario(ua, "önce")
    assert values[("tto", "DİBS RV!N%d" % empty)] == 98.5 and values[("tto", "DİBS RV!H8")] == 2.0
    assert ("tto", "DİBS RV!N8") not in values and ("tto", "DİBS RV!H9") not in values
    s.reset_inputs(a, "tto")
    s.load_scenario(a, "önce")
    assert cell(s, "DİBS RV!N%d" % empty, ua) == 98.5 and cell(s, "DİBS RV!N8", ua) == ""
    # the list kept as it is now
    kept = s.store.get("rowkeys.dibs")
    assert kept["8"] == "TRT130928T38" and kept[str(empty)] == "TRT150328T24" and "9" not in kept


def test_a_bond_typed_over_another_takes_nothing_of_it(svc):
    """An ISIN typed over another (the desk's list edited in place): the new bond starts clean - nothing of the old one's
    row is left for anyone (the desk's source, every user's values, an "Elle değer", the saved scenarios); values typed
    on a row with no bond go when ★ / + ISIN ekle puts a bond there."""
    s = svc
    a, b = s.login("Üstüne Yazan A")["user"], s.login("Üstüne Yazan B")["user"]
    ua, ub = user_key(a), user_key(b)
    r = row_of(s, a, "TRT081128T15")
    assert cell(s, "DİBS RV!B%d" % r) == "ISL1"                               # (the workbook's own source for it)
    s.set_inputs(a, "tto", [{"ref": "DİBS RV!N%d" % r, "value": "101"}])
    s.set_inputs(a, "tto", [{"ref": "DİBS RV!AI%d" % r, "value": "-80"}], allow_adhoc=True)    # ("Elle değer")
    s.set_inputs(b, "tto", [{"ref": "DİBS RV!AL%d" % r, "value": "41"}, {"ref": "DİBS RV!B%d" % r, "value": "ISL0"}])
    s.save_scenario(b, "eski")
    ra = row_of(s, a, "TRT081128T15", ASW, "asw")
    res = s.set_inputs(b, "tto", [{"ref": "DİBS RV!A%d" % r, "value": "trt130127t11"}])
    # ... off the ASW list too, which follows the trading list - with the workbook's own source for it there
    assert res["row_values"]["cleared"] == [{"isin": "TRT081128T15", "row": r, "values": 5},
                                            {"isin": "TRT081128T15", "row": ra, "values": 1}] and res["row_values"]["moved"] == []
    assert res["follow"]["asw_removed"] == ["TRT081128T15"] and res["follow"]["asw_added"] == ["TRT130127T11"]
    assert "TRT081128T15 listeden çıktı" in res["row_values"]["text"] and res["row_values"]["lists"] == ["dibs", "asw"]
    # the new bond's own source is blank (the general one), not the old one's - nor the workbook's for the old one
    assert s._list_values(a, "tto", LIST)[r - 5] == "TRT130127T11" and cell(s, "DİBS RV!B%d" % r) is None
    assert cell(s, "DİBS RV!N%d" % r, ua) == "" and cell(s, "DİBS RV!AL%d" % r, ub) == ""
    assert ("tto", "DİBS RV!AI%d" % r) not in s.store.user_inputs(ua, "tto")
    assert s.store.scenario(ub, "eski")[0] == {}
    # values typed on a row with no bond: gone when a bond takes the row
    empty = 5 + max(k for k, v in enumerate(s._list_values(a, "tto", LIST)) if v) + 1
    s.set_inputs(a, "tto", [{"ref": "DİBS RV!N%d" % empty, "value": "50"}])
    got = s.bond_flag(a, "TRT131027T36" if "TRT131027T36" not in s._list_values(a, "tto", LIST) else "TRT060127T10", True)
    assert got["cells"] == ["DİBS RV!A%d" % empty] and cell(s, "DİBS RV!N%d" % empty, ua) == ""
    assert got["row_values"]["cleared"][0]["isin"] == "" and "kâğıtsızken yazılmış 1 değer" in got["row_values"]["text"]


def test_a_bond_taken_off_takes_its_values_from_both_lists(svc):
    """☆ (or the ISIN blanked, or the desk's list reset to the file's): the bond's row empties and what it held goes with
    it, for everyone - DİBS RV and the ASW list that follows it (its source, manual price, curve flag, an "Elle değer"),
    in the saved scenarios too."""
    s = svc
    a = s.login("Çıkaran Masa")["user"]
    ua = user_key(a)
    code = "TRT120929T12"
    r, ra = row_of(s, a, code), row_of(s, a, code, ASW, "asw")
    s.set_inputs(a, "tto", [{"ref": "DİBS RV!N%d" % r, "value": "99"}, {"ref": "DİBS RV!B%d" % r, "value": "ISL0"}])
    s.set_inputs(a, "asw", [{"ref": "ASW!C%d" % ra, "value": "ISL0"}, {"ref": "ASW!D%d" % ra, "value": "98"},
                            {"ref": "ASW!E%d" % ra, "value": "0"}])
    s.set_inputs(a, "asw", [{"ref": "ASW!J%d" % ra, "value": "2,5"}], allow_adhoc=True)
    s.save_scenario(a, "çıkmadan")
    res = s.bond_flag(a, code, False)
    assert (res["removed"], res["asw"]) == (1, True)
    assert {x["isin"] for x in res["row_values"]["cleared"]} == {code} and res["row_values"]["lists"] == ["dibs", "asw"]
    assert "DİBS RV" in res["row_values"]["text"] and "DİBS ASW" in res["row_values"]["text"]
    assert [cell(s, "DİBS RV!%s%d" % (c, r), ua) for c in "ABN"] == [None, None, ""]         # (N, D: the two-way
    assert [cell(s, "ASW!%s%d" % (c, ra), ua, book="asw") for c in "BCD"] == [None, None, ""]  # tables' default)
    assert cell(s, "ASW!J%d" % ra, ua, book="asw") == cell(s, "ASW!J%d" % ra, book="asw")
    assert s.store.scenario(ua, "çıkmadan")[0] == {}
    # a row of the desk's list reset to the file's (empty there): the bond that leaves takes its values
    before = s._list_values(a, "tto", LIST)
    empty = 5 + max(k for k, v in enumerate(before) if v) + 1
    s.set_inputs(a, "tto", [{"ref": "DİBS RV!A%d" % empty, "value": "TRT020130T19"}, {"ref": "DİBS RV!N%d" % empty, "value": "97"}])
    assert cell(s, "DİBS RV!N%d" % empty, ua) == 97.0
    res = s.reset_inputs(a, "tto", ["DİBS RV!A%d" % empty], shared=True)
    assert res["reset"] == 1 and res["row_values"]["cleared"][0]["isin"] == "TRT020130T19"
    assert cell(s, "DİBS RV!N%d" % empty, ua) == "" and s._list_values(a, "tto", LIST) == before


def test_a_scenario_loaded_after_the_list_changed_puts_nothing_on_another_bond(svc):
    """A scenario saved before the list changed: loaded after it, each value lands on its bond's row now - none on the
    bond that took the old row."""
    s = svc
    a, desk = s.login("Senaryo Sonra")["user"], s.login("Senaryo Masa")["user"]
    ua = user_key(a)
    r = row_of(s, a, "TRT160431T35")
    s.set_inputs(a, "tto", [{"ref": "DİBS RV!N%d" % r, "value": "94,1"}])
    s.save_scenario(a, "16.04.31 fiyatım")
    s.reset_inputs(a, "tto")
    # the desk swaps 16.04.31 with the bond below it - two ISINs pasted from Excel
    other = s._list_values(a, "tto", LIST)[r - 5 + 1]
    assert other
    res = s.paste(desk, "tto", "DİBS RV!A%d" % r, "%s\nTRT160431T35" % other)
    assert res["rows"] == 2 and {"TRT160431T35", other} == {m["isin"] for m in res["row_values"]["moved"]}   # (its source too)
    s.load_scenario(a, "16.04.31 fiyatım")
    assert cell(s, "DİBS RV!N%d" % (r + 1), ua) == 94.1 and cell(s, "DİBS RV!N%d" % r, ua) == ""
    assert cell(s, "DİBS RV!A%d" % (r + 1)) == "TRT160431T35"


def test_ones_own_eurobond_list_keeps_its_values_by_isin_and_its_own_quotes_by_row(svc):
    """Eurobond Kotaları is each user's own list: an "Elle değer" on a bond's row follows the bond when the user moves it
    and goes with it when it leaves; the user's own bid / ask stay on their row (the form's: the quote typed on that
    row); another user's list and values are their own; a scenario loaded brings its own list with its rows' values."""
    s = svc
    a, b = s.login("Eurobond A")["user"], s.login("Eurobond B")["user"]
    ua, ub = user_key(a), user_key(b)
    first, second, third = s._list_values(a, "tto", "Bulk Bond!A3:A52")[:3]
    assert first and second and third
    s.set_inputs(a, "tto", [{"ref": "Bulk Bond!C3", "value": "99,5"}])
    s.set_inputs(a, "tto", [{"ref": "Bulk Bond!F3", "value": "101"}, {"ref": "Bulk Bond!F5", "value": "77"}], allow_adhoc=True)
    s.set_inputs(b, "tto", [{"ref": "Bulk Bond!F3", "value": "55"}], allow_adhoc=True)
    s.save_scenario(a, "eurobond")
    res = s.set_inputs(a, "tto", [{"ref": "Bulk Bond!A3", "value": second}, {"ref": "Bulk Bond!A4", "value": first}])
    assert {m["isin"]: (m["from"], m["to"]) for m in res["row_values"]["moved"]} == {first: (3, 4)}
    assert "Eurobond Kotaları" in res["row_values"]["text"]
    assert cell(s, "Bulk Bond!F4", ua) == 101.0 and cell(s, "Bulk Bond!C3", ua) == 99.5         # (the own bid: its row's)
    assert cell(s, "Bulk Bond!F3", ub) == 55.0 and s._list_values(b, "tto", "Bulk Bond!A3:A52")[:2] == [first, second]
    assert s.store.get("rowkeys.bulk:%s" % ua)["4"] == first and s.store.get("rowkeys.bulk:%s" % ub) is None
    # the third leaves the list: its "Elle değer" goes; the scenario keeps its own list and values
    res = s.set_inputs(a, "tto", [{"ref": "Bulk Bond!A5", "value": ""}])
    assert res["row_values"]["cleared"] == [{"isin": third, "row": 5, "values": 1}]
    assert cell(s, "Bulk Bond!F5", ua) == cell(s, "Bulk Bond!F5")
    s.load_scenario(a, "eurobond")
    assert s._list_values(a, "tto", "Bulk Bond!A3:A52")[:3] == [first, second, third]
    assert (cell(s, "Bulk Bond!F3", ua), cell(s, "Bulk Bond!F5", ua)) == (101.0, 77.0)
    assert s.store.get("rowkeys.bulk:%s" % ua)["3"] == first


def test_an_earlier_versions_database_is_taken_as_it_is_once(tmp_path):
    """A database of an earlier version (values on the bonds' rows, scenarios, no rows kept): opened, it keeps everything
    where it is - each row's values are its bond's now, kept once; a change from then on moves them.  A list found changed
    at a start (an earlier version wrote it, another file) moves what the rows held then."""
    import json
    store = Store(str(tmp_path / "tto.db"))
    store.login("Eski Kullanıcı")
    u = user_key("Eski Kullanıcı")
    store.set_user_inputs(u, "tto", {"DİBS RV!N8": 98.5, "DİBS RV!T9": 0.4, "Bulk Bond!F4": 12.0})
    store.set_user_inputs(u, "asw", {"ASW!D9": 97.0})
    store.set_shared_inputs("tto", {"DİBS RV!B8": "ISL0"}, "masa")
    store.save_scenario(u, "eski", {("tto", "DİBS RV!N8"): 98.0})
    before = (store.user_inputs(u), store.shared_inputs(), store._q("SELECT payload FROM scenarios")[0]["payload"])
    store.close()
    s = make_service(tmp_path)
    try:
        assert (s.store.user_inputs(u), s.store.shared_inputs(), s.store._q("SELECT payload FROM scenarios")[0]["payload"]) == before
        kept = s.store.get("rowkeys.dibs")
        assert kept["8"] == "TRT150328T24" and kept["9"] == "TRT130928T38" and "7" not in kept
        assert s.store.get("rowkeys.asw")["9"] == "TRT150328T24"
        assert s.store.get("rowkeys.bulk:%s" % u)["4"] == s._list_values(u, "tto", "Bulk Bond!A3:A52")[1]
        assert cell(s, "DİBS RV!N8", u) == 98.5 and cell(s, "DİBS RV!B8") == "ISL0"
        # from now on a change moves them
        s.set_inputs(u, "tto", [{"ref": "DİBS RV!A8", "value": ""}, {"ref": "DİBS RV!A40", "value": "TRT150328T24"}])
        assert cell(s, "DİBS RV!N40", u) == 98.5 and cell(s, "DİBS RV!B40") == "ISL0"
        assert s.store.scenario(u, "eski")[0] == {("tto", "DİBS RV!N40"): 98.0}
    finally:
        s.stop()
    # while the dashboard is off, a version that does not move them changes the list: the next start moves them
    store = Store(str(tmp_path / "tto.db"))
    store.set_shared_inputs("tto", {"DİBS RV!A40": None, "DİBS RV!A41": "TRT150328T24"}, "eski sürüm")
    store.close()
    again = make_service(tmp_path)
    try:
        assert cell(again, "DİBS RV!N41", u) == 98.5 and cell(again, "DİBS RV!B41") == "ISL0"
        assert again.store.user_inputs(u, "tto").get(("tto", "DİBS RV!N40")) is None
        assert again.store.get("rowkeys.dibs")["41"] == "TRT150328T24" and json.loads(again.store._q(
            "SELECT payload FROM scenarios")[0]["payload"]) == [["tto", "DİBS RV!N41", 98.0]]
    finally:
        again.stop()


def test_ones_own_viop_prices_go_when_another_gold_contract_takes_the_column(tmp_path):
    """VİOP's columns are places: what is typed for a place stays with it when the contracts roll - but one's own VİOP bid
    / ask typed into the gold calculator is that contract's price: when another contract takes the column (it expired, or
    the desk typed another), it goes - for everyone, in the saved scenarios too; the other columns' stay."""
    s = make_service(tmp_path)
    try:
        a = s.login("Altın Fiyat")["user"]
        ua = user_key(a)
        codes = [cell(s, "VIOP!%s45" % c) for c in "MNO"]
        assert all(isinstance(c, str) and c.endswith("Comdty") for c in codes)
        assert s.store.get(rk.GOLD_KEY) == codes                                 # (kept at the start)
        s.set_inputs(a, "tto", [{"ref": "EK_XAU!B54", "value": "4100"}, {"ref": "EK_XAU!C55", "value": "4200"},
                                {"ref": "EK_XAU!B45", "value": "5"}])
        s.save_scenario(a, "altın")
        assert s.et.call(s.rowkeys.roll) is None                                  # (nothing changed)
        assert s.set_inputs(a, "tto", [{"ref": "VIOP!M45", "value": "XLJ7 Comdty"}])["errors"] == []
        s.et.call(s.rowkeys.roll)
        assert cell(s, "EK_XAU!B54", ua) == cell(s, "EK_XAU!B54") and cell(s, "EK_XAU!C55", ua) == 4200.0
        assert cell(s, "EK_XAU!B45", ua) == 5.0                                   # (a rate typed for the place stays)
        assert s.store.scenario(ua, "altın")[0] == {("tto", "EK_XAU!C55"): 4200.0, ("tto", "EK_XAU!B45"): 5.0}
        assert s.store.get(rk.GOLD_KEY) == ["XLJ7 Comdty"] + codes[1:]
    finally:
        s.stop()
