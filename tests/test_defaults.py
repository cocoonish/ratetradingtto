"""What every user starts with: no scenario step per meeting (PPK ima) and an empty VİOP target table - the file's
values of the day it was saved are nobody's choice today.  A user's own values are kept as before."""
from __future__ import annotations

import pytest
from conftest import cell, make_service
from tto import extras as ex
from tto.inputs import parse_date
from tto.store import Store


def test_the_steps_and_the_target_table_start_empty(service):
    refs = ex.empty_default_refs()
    assert refs[:3 * 80 + 5 * 8] == ex.empty_default_refs(ex.EMPTY_FIRST) and refs[0] == "OIS_MAIN!U10"
    assert len(ex.empty_default_refs(ex.EMPTY_FIRST)) == 3 * 80 + 5 * 8 and "VIOP!P338" in refs
    for ref in ("OIS_MAIN!U10", "OIS_MAIN!V11", "OIS_MAIN!W12", "OIS_MAIN!W89", "VIOP!L331", "VIOP!N332"):
        assert cell(service, ref) is None, ref
    # (Hedef değer is two-way since 24.11.2026: worked out from the row's typed value - none: empty)
    assert cell(service, "VIOP!P338") == "" and cell(service, "VIOP!AE338") is None
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
        assert cell(service, "OIS_MAIN!U11") is None and cell(service, "VIOP!P331") == ""
    finally:
        service.reset_inputs(u, "tto")


def test_a_far_contract_picked_from_its_list_prices_the_target_row(service):
    """The target table's near and far contracts come from the contract row's list (=$L$97:$X$97) and the formulas
    look that text up.  The far one was kept as a date number (46356): nothing matched and the row stayed empty."""
    u = service.login("Target Uzak Kontrat")["user"]
    try:
        for far in ("30.11.2026", "30.11.26", "30/11/2026"):
            res = service.set_inputs(u, "tto", [{"ref": "VIOP!L331", "value": "Spot"}, {"ref": "VIOP!M331", "value": far},
                                                {"ref": "VIOP!N331", "value": "SHORT"}, {"ref": "VIOP!O331", "value": "FRA+bp"},
                                                {"ref": "VIOP!P331", "value": "-150"}])
            assert res["errors"] == [] and cell(service, "VIOP!M331", u) == "30.11.2026", far
            # the file's own row with the same choices: the target rate, the spread price and the days
            assert cell(service, "VIOP!Q331", u) == pytest.approx(0.34301087462666635, rel=1e-12)
            assert cell(service, "VIOP!R331", u) == pytest.approx(49.9975) and cell(service, "VIOP!Y331", u) == 26.0
    finally:
        service.reset_inputs(u, "tto")


def test_the_viop_contracts_are_the_desks(tmp_path):
    """The futures tickers of the VİOP page (USDTRY 1-12, gold TRY and USD) are the desk's: one user rolls them and
    everyone sees it.  A ticker a user kept while they were personal goes at the next start (it would hide the desk's
    from them) - the user's other inputs stay."""
    store = Store(str(tmp_path / "tto.db"))
    key = store.login("Eski Kontratçı")["user"]
    store.set_user_inputs(key, "tto", {"VIOP!L1": "A1X6 Eski", "VIOP!M45": "XLZ6 Eski", "VIOP!B44": 2.0})
    store.close()
    svc = make_service(tmp_path)
    try:
        other = svc.login("Masa Arkadaşı")["user"]
        assert cell(svc, "VIOP!L1", key) == cell(svc, "VIOP!L1") == "A1X6 Curncy"
        assert cell(svc, "VIOP!M45", key) == "XLZ6 Comdty" and cell(svc, "VIOP!B44", key) == 2.0
        assert set(svc.store.user_inputs(key, "tto")) == {("tto", "VIOP!B44")}
        res = svc.set_inputs(other, "tto", [{"ref": "VIOP!L1", "value": "A1Z6 Curncy"}, {"ref": "VIOP!O60", "value": "XLTM7 Comdty"}])
        assert res["errors"] == []
        for who in (key, other, None):
            assert cell(svc, "VIOP!L1", who) == "A1Z6 Curncy" and cell(svc, "VIOP!O60", who) == "XLTM7 Comdty"
    finally:
        svc.stop()


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
        assert cell(svc, "OIS_MAIN!U11") is None and cell(svc, "VIOP!P331") == ""         # (two-way: nothing typed)
        assert svc.store.get("migrated.empty_defaults")
        svc.store.set_shared_inputs("tto", {"OIS_MAIN!U12": -25.0}, "biri")
    finally:
        svc.stop()
    again = make_service(tmp_path)                                                       # a restart does not drop it again
    try:
        assert again.store.shared_inputs("tto")[("tto", "OIS_MAIN!U12")] == -25.0
    finally:
        again.stop()


def test_the_manual_spot_starts_on_bloomberg_and_a_stored_copy_of_the_files_goes_once(tmp_path):
    """The manual USDTRY spot (VİOP AA9:AA10, the desk's: blank = Bloomberg) came with the file's 49,997 / 49,9975, which
    replaced Bloomberg's spot on every page for everybody.  It starts empty.  A value stored of it goes once - only when it
    is the file's own value (a copy, nobody's choice); a spot the desk typed stays, and so does one typed later."""
    assert ex.FILE_VALUES and ("VIOP", "AA9:AA10") in ex.EMPTY_BY_DEFAULT
    store = Store(str(tmp_path / "tto.db"))
    store.set_shared_inputs("tto", {"VIOP!AA9": 49.997, "VIOP!AA10": 50.12}, "masa")
    store.close()
    svc = make_service(tmp_path)
    try:
        model = svc.books["tto"].model
        assert model.meta[ex.FILE_VALUES]["VIOP!AA9"] == 49.997 and model.meta[ex.FILE_VALUES]["VIOP!AA10"] == 49.9975
        assert "OIS_MAIN!U10" not in model.meta[ex.FILE_VALUES]           # (the first clean-up dropped those long ago)
        assert svc.store.shared_inputs("tto") == {("tto", "VIOP!AA10"): 50.12}
        assert cell(svc, "VIOP!AA9") is None and cell(svc, "VIOP!AA10") == 50.12 and cell(svc, "VIOP!AA8") == "MANUEL"
        assert {"VIOP!AA9", "VIOP!AA10"} <= set(svc.store.get(svc.FILE_COPIES_DONE)["tto"])
        svc.store.set_shared_inputs("tto", {"VIOP!AA9": 49.997}, "masa")      # the desk types the same spot again
    finally:
        svc.stop()
    again = make_service(tmp_path)                                           # ... and a restart keeps it
    try:
        assert again.store.shared_inputs("tto") == {("tto", "VIOP!AA9"): 49.997, ("tto", "VIOP!AA10"): 50.12}
        assert cell(again, "VIOP!AA9") == 49.997
    finally:
        again.stop()
    fresh = make_service(tmp_path / "bos")                                   # a new desk: Bloomberg's spot
    try:
        assert cell(fresh, "VIOP!AA9") is None and cell(fresh, "VIOP!AA10") is None and cell(fresh, "VIOP!AA8") == "BBG"
    finally:
        fresh.stop()


def test_the_calculators_values_of_the_save_day_start_empty(service):
    """The hand calculators' values of the day the file was saved are nobody's today: TM OIS's trade, the Forward page's
    day counter, the XAU leg's dates and swap, the bond carry, the OIS page's two dates, the VİOP calculators' TRY rates,
    DİBS RV's switch, the Eurobond page's own asks and the USD page's FOMC scenario steps start empty."""
    for ref in ("TM_OIS!A10", "TM_OIS!B11", "TM_OIS!C12", "Forward!E20", "Forward!E22", "Forward!C59", "Forward!C60", "Forward!C63",
                "Forward!E61", "Forward!E67", "Forward!V56", "Forward!V57", "Forward!V58", "Forward!V62",
                "OIS_MAIN!B122", "OIS_MAIN!B123", "VIOP!M37", "VIOP!P37", "VIOP!S37", "DİBS RV!A64", "DİBS RV!B64", "DİBS RV!C64",
                "Bulk Bond!D3", "Bulk Bond!D4", "Bulk Bond!D5"):
        assert cell(service, ref) is None, ref
    # (the bond carry's Carry: empty too - its formula default, the two-way block's: the repo of a B/E, Px Drop typed)
    assert cell(service, "Forward!V61") == ""
    for ref in ("SOFR_FOMC!R74", "SOFR_FOMC!S77", "SOFR_FOMC!T83"):
        assert cell(service, ref, book="sofr") is None, ref
    # their captions, the formulas beside them and the rest of the lists stay
    assert cell(service, "Forward!D59") == "USDTRY Spot" and cell(service, "Forward!U56") == "ISIN" and cell(service, "VIOP!L37") == "TRY"
    assert cell(service, "Bulk Bond!A3") == "XS3429167243" and cell(service, "TM_OIS!F10") == 0.0
    # no FOMC step: the base path stays where it starts
    path = [cell(service, "SOFR_FOMC!U%d" % r, book="sofr") for r in range(74, 84)]
    assert len(set(path)) == 1 and isinstance(path[0], float)
    assert ex.FILE_VALUES in service.books["sofr"].model.meta
    # what a user types is theirs
    u = service.login("Boş Hesaplayıcı")["user"]
    try:
        assert service.set_inputs(u, "tto", [{"ref": "VIOP!M37", "value": "34,05"}, {"ref": "TM_OIS!C10", "value": "100m"}])["errors"] == []
        assert cell(service, "VIOP!M37", u) == pytest.approx(0.3405) and cell(service, "TM_OIS!C10", u) == 100e6
        assert cell(service, "VIOP!M37") is None
    finally:
        service.reset_inputs(u, "tto")


def test_the_calculators_start_from_the_market(service):
    """The Calculators sheet's top band (AA3 / AA4 / AA9 / AA10: 03.11.2026, a spot and a forward of that day, read by the
    first four calculators) and the XAU leg's spots and rates start from the market, as the Forward page's calculators do:
    whoever wants another types it over, Delete brings the market back."""
    spot_date = parse_date("04.11.2026")
    assert cell(service, "Calculators!AA3") == spot_date and cell(service, "Calculators!AA4") == cell(service, "Forward!D2")
    assert cell(service, "Calculators!AA9") == cell(service, "Forward!F2")
    # the forward of the end date: the offshore curve's mid - the Forward page's ICAP row at its value date
    assert cell(service, "Calculators!AA10") == pytest.approx(cell(service, "Forward!E30"), rel=1e-6)
    assert cell(service, "Calculators!C3") == spot_date and cell(service, "Calculators!C6") == cell(service, "Forward!F2")
    u = service.login("Piyasa Hesaplayıcı")["user"]
    try:
        # the value date of the Forward page moves the end date and the forward with it
        service.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "04.05.2027"}])
        assert cell(service, "Calculators!AA4", u) == parse_date("04.05.2027") == cell(service, "Calculators!C4", u)
        assert cell(service, "Calculators!AA10", u) == pytest.approx(cell(service, "Forward!E30", u), rel=1e-6)
        # a spot of one's own: the forward follows it; Delete: the market again
        service.set_inputs(u, "tto", [{"ref": "Calculators!AA9", "value": "50"}])
        assert cell(service, "Calculators!C6", u) == 50.0
        assert cell(service, "Calculators!AA10", u) == pytest.approx(cell(service, "Forward!E30", u) * 50 / cell(service, "Forward!F2"), rel=1e-6)
        service.set_inputs(u, "tto", [{"ref": "Calculators!AA9", "value": ""}])
        assert cell(service, "Calculators!AA9", u) == cell(service, "Forward!F2")
        # the XAU leg: the spot from the market, the rates once the customer's forward date is there
        assert cell(service, "Forward!E59") == cell(service, "Forward!F2") and cell(service, "Forward!E63") == cell(service, "Forward!E64") == ""
        service.set_inputs(u, "tto", [{"ref": "Forward!E61", "value": "08.12.2026"}])
        n = cell(service, "Forward!C65", u)
        usd, tl = cell(service, "Forward!E63", u), cell(service, "Forward!E64", u)
        assert n == 34.0 and 0.02 < usd < 0.06 and 0.2 < tl < 0.5
        assert cell(service, "Forward!E62", u) == pytest.approx(cell(service, "Forward!F2") * (1 + tl / 360 * n) / (1 + usd / 360 * n), rel=1e-12)
        service.set_inputs(u, "tto", [{"ref": "Forward!E64", "value": "40"}])                  # a rate of one's own
        assert cell(service, "Forward!E64", u) == pytest.approx(0.4)
        service.set_inputs(u, "tto", [{"ref": "Forward!E64", "value": ""}])
        assert cell(service, "Forward!E64", u) == tl
    finally:
        service.reset_inputs(u, "tto")


#: desk reference data that was each user's own: tickers, holiday names, source codes, bucket definitions
DESK_DATA = {"viop": ("C16:C35", "D16:D35", "C43:C52", "C58:C69", "S340", "R353"),
             "motor": ("O89", "O130", "C327:C342", "B361:B523"), "masa": ("S171",),
             "bulk": ("K1", "M1", "O1", "Q1", "S1", "U1", "K2:V2"), "dibs": ("V2",), "dv01": ("H6:H25", "I6:I25"),
             "ois": ("B442:B457", "F442:F457", "G442:G457")}


def test_desk_reference_data_is_the_desks_and_the_carry_horizon_each_users(tmp_path):
    """The VİOP page's OIS / ICAP tickers and spot ticker, Motor's ticker roots, "Kotalı" flags and holiday names, Masa's
    history source, the Eurobond page's pricing sources and fields, DİBS RV's TLREF lag, DV01's bucket definitions and
    the OIS solver's buckets are the desk's: one sets them, everyone sees it (a value a user kept while they were
    personal goes at the next start).  DİBS RV's horizon ("Ufuk (ay)") goes the other way: each user's own."""
    from tto.views import load_views
    views = {v["id"]: v for v in load_views()}
    scopes = {(v, i["range"]): i.get("scope", "user") for v, view in views.items() for i in view["inputs"]}
    for view, ranges in DESK_DATA.items():
        for rng in ranges:
            assert scopes[(view, rng)] == "shared", (view, rng)
    assert scopes[("dibs", "J2")] == "user"
    store = Store(str(tmp_path / "tto.db"))
    key = store.login("Eski Ticker")["user"]
    store.set_user_inputs(key, "tto", {"VIOP!C16": "USSO2Z", "Motor!B361": "Benim tatilim", "DİBS RV!V2": 3.0, "DİBS RV!P2": 7.0})
    store.close()
    svc = make_service(tmp_path)
    try:
        other = svc.login("Masa Komşusu")["user"]
        assert cell(svc, "VIOP!C16", key) == "USSO1Z" and cell(svc, "Motor!B361", key) == "Cumhuriyet"
        assert set(svc.store.user_inputs(key, "tto")) == {("tto", "DİBS RV!P2")}          # the personal threshold stays
        res = svc.set_inputs(other, "tto", [{"ref": "MASA!S171", "value": "CMPN"}, {"ref": "Bulk Bond!K1", "value": "BVAL"},
                                            {"ref": "DİBS RV!J2", "value": "6"}])
        assert res["errors"] == []
        for who in (key, other, None):
            assert cell(svc, "MASA!S171", who) == "CMPN" and cell(svc, "Bulk Bond!K1", who) == "BVAL"
        assert cell(svc, "DİBS RV!J2", other) == 6.0 and cell(svc, "DİBS RV!J2", key) == cell(svc, "DİBS RV!J2") == 3.0
        assert svc.store.shared_inputs("tto")[("tto", "MASA!S171")] == "CMPN"
    finally:
        svc.stop()


def test_the_viop_contracts_roll_by_themselves(tmp_path):
    """The VİOP page's futures (USDTRY 1-12, gold TRY and gold USD: even months) are built from today: a contract trades
    until its expiry - the last business day of its month, or the business day before when that one is a half day (the
    eve of 29 October or of a bayram).  The rule gives the workbook's own contract dates: on each the contract is still
    the nearest, the day after the next one is.  What the desk types still wins; Delete brings the roll back.  A stored
    copy of the file's tickers goes once."""
    import datetime as dt
    from tto.xl.values import date_to_serial
    store = Store(str(tmp_path / "tto.db"))
    store.set_shared_inputs("tto", {"VIOP!L1": "A1X6 Curncy", "VIOP!M45": "XLG7 Comdty"}, "masa")      # a copy, and a choice
    store.close()
    svc = make_service(tmp_path)
    book = svc.books["tto"]
    clock = book.engine.clock
    today = clock.today

    def on(day):
        clock.today = (lambda x=float(date_to_serial(day)): x)
        svc.et.call(book.engine.clock_tick)

    try:
        assert svc.store.shared_inputs("tto") == {("tto", "VIOP!M45"): "XLG7 Comdty"}
        assert cell(svc, "VIOP!M45") == "XLG7 Comdty"                               # the desk's choice wins ...
        u = svc.login("Kontrat Rolü")["user"]
        assert svc.set_inputs(u, "tto", [{"ref": "VIOP!M45", "value": ""}])["errors"] == []
        assert cell(svc, "VIOP!M45") == "XLZ6 Comdty" and svc.store.shared_inputs("tto") == {}     # ... Delete: the roll
        # the day the file was saved: the workbook's own tickers
        files = book.model.meta[ex.FILE_VALUES]
        for rng, _, _, _ in ex.VIOP_ROLLS:
            for ref in ex.empty_default_refs((("VIOP", rng),)):
                assert cell(svc, ref) == files[ref], ref
        assert (cell(svc, "VIOP!L1"), cell(svc, "VIOP!W1"), cell(svc, "VIOP!O60")) == ("A1X6 Curncy", "A1V7 Curncy", "XLTJ7 Comdty")
        # the workbook's contract dates: the contract trades on its date, the next one is the nearest the day after
        tickers = [files["VIOP!%s1" % c] for c in "LMNOPQRSTUVW"]
        days = [cell(svc, "VIOP!%s19" % c) for c in "MNOPQRSTUVWX"]               # "30.11.2026" ... "27.10.2027"
        assert days[0] == "30.11.2026" and days[-1] == "27.10.2027"
        for k, text in enumerate(days[:-1]):
            day = dt.date(int(text[6:]), int(text[3:5]), int(text[:2]))
            on(day)
            assert cell(svc, "VIOP!L1") == tickers[k], text
            on(day + dt.timedelta(days=1))
            assert cell(svc, "VIOP!L1") == tickers[k + 1], text
        on(dt.date(2027, 10, 27))                                                  # 28.10.2027 is the eve of the 29th
        assert cell(svc, "VIOP!L1") == "A1V7 Curncy" and cell(svc, "VIOP!M45") == "XLV7 Comdty"
        on(dt.date(2027, 10, 28))
        assert [cell(svc, "VIOP!%s1" % c) for c in "LMW"] == ["A1X7 Curncy", "A1Z7 Curncy", "A1V8 Curncy"]
        assert [cell(svc, "VIOP!%s45" % c) for c in "MNO"] == ["XLZ7 Comdty", "XLG8 Comdty", "XLJ8 Comdty"]
        assert [cell(svc, "VIOP!%s60" % c) for c in "MNO"] == ["XLTZ7 Comdty", "XLTG8 Comdty", "XLTJ8 Comdty"]
        on(dt.date(2027, 1, 1))                                                    # an odd month: the next even one
        assert cell(svc, "VIOP!L1") == "A1F7 Curncy" and cell(svc, "VIOP!M45") == "XLG7 Comdty" and cell(svc, "VIOP!O45") == "XLM7 Comdty"
        # a contract the desk types still wins on any day
        assert svc.set_inputs(u, "tto", [{"ref": "VIOP!L1", "value": "A1Z6 Curncy"}])["errors"] == []
        assert cell(svc, "VIOP!L1") == cell(svc, "VIOP!L1", u) == "A1Z6 Curncy" and cell(svc, "VIOP!M1") == "A1G7 Curncy"
    finally:
        clock.today = today
        svc.stop()


def test_one_ois_spread_is_typed_once(service):
    """The desk's OIS spread assumption was typed four times in three units: MASA!I60 = -150 bp (read by the desk sheet and
    the forward quote matrix), Forward!P58 = -1,5 (%-points), Forward!O27 = -1,5 % and OIS_MAIN!F122 = -1,5 %.  I60 stays
    the one typed; the three others follow it (a formula default each - typed over, a user's own; Delete: I60's again)."""
    assert cell(service, "MASA!I60") == -150.0
    assert cell(service, "Forward!P58") == -1.5 and cell(service, "Forward!O27") == pytest.approx(-0.015)
    assert cell(service, "OIS_MAIN!F122") == pytest.approx(-0.015)
    assert cell(service, "Forward!P27") == pytest.approx(cell(service, "Forward!P24") - 0.015)
    u = service.login("Tek Spread")["user"]
    try:
        assert service.set_inputs(u, "tto", [{"ref": "MASA!I60", "value": "-100"}])["errors"] == []
        assert cell(service, "Forward!P58", u) == -1.0 and cell(service, "Forward!O27", u) == pytest.approx(-0.01)
        assert cell(service, "OIS_MAIN!F122", u) == pytest.approx(-0.01) and cell(service, "EK_FWD!D4", u) == -100.0
        assert cell(service, "Forward!P59", u) == pytest.approx(cell(service, "Forward!P6", u) - 1.0)
        assert cell(service, "Forward!P58") == -1.5                                      # the others keep the desk's
        assert service.set_inputs(u, "tto", [{"ref": "Forward!P58", "value": "-2"}])["errors"] == []
        assert cell(service, "Forward!P58", u) == -2.0 and cell(service, "Forward!O27", u) == pytest.approx(-0.01)
        assert service.set_inputs(u, "tto", [{"ref": "Forward!P58", "value": ""}])["errors"] == []
        assert cell(service, "Forward!P58", u) == -1.0
    finally:
        service.reset_inputs(u, "tto")
