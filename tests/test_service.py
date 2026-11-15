"""Application service: pages, personal vs shared inputs, scenarios, the RET curve."""
import pytest

from conftest import cell, make_service
from tto.inputs import parse_date
from tto.service import ServiceError
from tto.views import load_views

VIEW_IDS = [v["id"] for v in load_views()]


def login(svc, name):
    return svc.login(name)["user"]


def test_status_and_navigation(service):
    st = service.status()
    assert st["mode"] == "replay" and st["today"] == "2026-11-03" and st["port"] == 1057
    assert service.describe().startswith("Veri: kayıtlı")            # the line printed on the console at the start
    assert set(st["books"]) == {"tto", "sofr", "borsa", "asw"}
    assert st["books"]["tto"]["formulas"] > 110000 and st["books"]["sofr"]["formulas"] > 4000
    assert st["books"]["borsa"]["formulas"] > 16000 and st["books"]["asw"]["formulas"] > 80000
    pages = service.nav()
    ids = [p["id"] for p in pages]
    assert "blotter" in ids and "masa" in ids and "forward" in ids and "usd" in ids
    # the pages of the workbooks, the blotter and the dashboard's own pages (matrix, meeting pricing, spreads, settings)
    custom = [p["id"] for p in pages if p.get("custom")]
    assert custom == ["watch", "heat", "blotter", "broker", "eod", "mpc", "vol", "spreads", "settings", "fx", "fxvol"]
    assert len(ids) == len(set(ids)) == len(VIEW_IDS) + 11


@pytest.mark.parametrize("view_id", VIEW_IDS)
def test_every_page_renders_without_errors(service, view_id):
    data = service.view(None, view_id, True)
    assert data["id"] == view_id and data["panels"]
    for p in data["panels"]:
        assert "error" not in p, (view_id, p["id"], p.get("error"))
        if p["type"] == "image":                         # a picture of the sheet: served on its own
            assert p["src"].startswith("/api/image?") and p["title"]
            continue
        if p["type"] == "chart":
            d = p["data"]
            if d.get("scatter"):                         # an XY chart: every series brings its own x values
                assert d["series"] and all(len(s["x"]) == len(s["data"]) for s in d["series"]), (view_id, p["id"])
                continue
            assert d["cats"] and d["series"], (view_id, p["id"])
            assert all(len(s["data"]) == len(d["cats"]) for s in d["series"])
            continue
        d = p["data"]
        width = len(d["c"])
        assert len(d["rows"]) == len(d["r"]) and all(len(row) == width for row in d["rows"]), (view_id, p["id"])
        assert all("#ERR" != c.get("t") for row in d["rows"] for c in row), (view_id, p["id"])


def test_visible_panels_have_content(service):
    for view_id in VIEW_IDS:
        for p in service.view(None, view_id)["panels"]:
            if p["type"] not in ("chart", "image"):
                assert any(c.get("t") for row in p["data"]["rows"] for c in row), (view_id, p["id"])


def test_header_strip(service):
    items = service.header(None)["items"]
    labels = [i["label"] for i in items]
    assert "USDTRY mid" in labels and "TLREF" in labels and "Spot valör" in labels
    assert all(i["text"] for i in items)


def test_manual_spot_is_at_the_top_and_can_be_typed_from_the_header(service, tmp_path):
    """The manual USDTRY spot (VİOP sheet, "Manuel SP") replaces the Bloomberg spot on every page.  It is the
    first table of the VİOP page and of the main page, and the "Spot kaynağı" box of the header strip opens
    it from anywhere.  (Run live, as on the desk: offline the spot cells are frozen at what Excel recorded.)"""
    from conftest import cell
    from tto.config import Settings
    from tto.marketdata.base import bdp_key
    from tto.marketdata.replay import ReplayProvider
    from tto.service import Service
    from tto.xl.engine import Clock

    class Direct(ReplayProvider):
        """A connected Bloomberg that answers at once."""
        live = True

        def _get(self, key):
            v = self.snapshot.get(key)
            return "#N/A N/A" if v is None else v

        get_bdp = get_bdh = get_bds = _get

    today = service.books["tto"].engine.clock.today()
    snapshot = {k: v for k, v in service.provider.snapshot.items() if k[0] not in ("BFX", "RT")}
    snapshot.update({bdp_key("USDTRY Curncy", "BID"): 50.36, bdp_key("USDTRY Curncy", "ASK"): 50.37})
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    svc = Service(Settings(data_dir=str(tmp_path), mode="live", history=False), provider=Direct(snapshot), clock=clock)
    try:
        user = login(svc, "Spot Giren")
        for view_id in ("viop", "masa"):
            first = next(p for p in svc.view(user, view_id)["panels"] if not p["hidden"])
            assert first["title"].startswith("Manuel spot") and first["range"] == "Z8:AA11", view_id
            texts = [c.get("t", "") for row in first["data"]["rows"] for c in row]
            assert "Bid" in texts and "Ask" in texts and "BBG" in texts
            inputs = [c for row in first["data"]["rows"] for c in row if c.get("i")]
            assert len(inputs) == 2                                   # the two cells can be typed into right there
        items = svc.header(user)["items"]
        source = next(i for i in items if i["label"] == "Spot kaynağı")
        assert source["edit"] == "spot" and source["text"] == "BBG"
        assert [i["label"] for i in items if i.get("edit")] == ["Spot kaynağı"]

        def shown():
            return {i["label"]: i["v"] if isinstance(i["v"], float) else i["text"] for i in svc.header(None)["items"]}

        # the file was saved with a manual spot (49,997 / 49,9975): the desk's choice of that day, nobody's today - every
        # page starts on Bloomberg's spot
        assert svc.manual_spot(user) == {"book": "tto", "refs": {"bid": "VIOP!AA9", "ask": "VIOP!AA10"}, "bid": None,
                                         "ask": None, "source": "BBG", "available": True}
        assert (shown()["USDTRY bid"], shown()["USDTRY ask"]) == (50.36, 50.37)
        # typed (Turkish decimals): used on every page
        res = svc.set_inputs(user, "tto", [{"ref": "VIOP!AA9", "value": "50,3667"}, {"ref": "VIOP!AA10", "value": "50,3688"}], lang="tr")
        assert res["errors"] == []
        spot = svc.manual_spot(None)
        assert (spot["bid"], spot["ask"], spot["source"]) == (50.3667, 50.3688, "MANUEL")
        assert shown()["Spot kaynağı"] == "MANUEL" and (shown()["USDTRY bid"], shown()["USDTRY ask"]) == (50.3667, 50.3688)
        assert cell(svc, "VIOP!L99") == 50.3667 and cell(svc, "VIOP!L100") == 50.3688
        # cleared: Bloomberg's spot again, for everybody
        res = svc.set_inputs(user, "tto", [{"ref": "VIOP!AA9", "value": ""}, {"ref": "VIOP!AA10", "value": ""}])
        assert res["errors"] == []
        spot = svc.manual_spot(None)
        assert (spot["bid"], spot["ask"], spot["source"]) == (None, None, "BBG")
        assert shown()["Spot kaynağı"] == "BBG" and (shown()["USDTRY bid"], shown()["USDTRY ask"]) == (50.36, 50.37)
    finally:
        svc.stop()


def test_number_format_follows_the_requested_locale(service):
    tr = service.cell_info(None, "tto", "Forward!D33", "tr")["cell"]["t"]
    en = service.cell_info(None, "tto", "Forward!D33", "en")["cell"]["t"]
    assert tr == "59,2364" and en == "59.2364"


def test_personal_inputs_change_only_my_view(service):
    a, b = login(service, "Servis A"), login(service, "Servis B")
    base = cell(service, "Forward!D33")
    res = service.set_inputs(a, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}])
    assert res == {"applied": 1, "errors": [], "gen": service.gen}
    assert cell(service, "Forward!D2", a) == parse_date("15.12.2026")
    mine = cell(service, "Forward!D33", a)
    assert mine != base
    assert cell(service, "Forward!D33", b) == base            # the other user ...
    assert cell(service, "Forward!D33") == base               # ... and the shared view are untouched
    # the rendered cell is flagged as my own input
    info = service.cell_info(a, "tto", "Forward!D2")
    assert info["cell"]["i"] == "u" and info["cell"]["m"] == 1 and info["cell"]["t"] == "15.12.2026"
    assert info["input"]["scope"] == "user"
    assert service.cell_info(b, "tto", "Forward!D2")["cell"].get("m") is None
    # stored under my name
    assert service.store.user_inputs(a) == {("tto", "Forward!D2"): parse_date("15.12.2026")}
    assert [i["ref"] for i in service.my_inputs(a)["inputs"]] == ["Forward!D2"]
    # back to the workbook's value
    assert service.reset_inputs(a, "tto", ["Forward!D2"])["reset"] == 1
    assert cell(service, "Forward!D33", a) == base
    assert service.store.user_inputs(a) == {}


def test_inputs_are_parsed_like_excel_would(service):
    u = login(service, "Servis Parse")
    res = service.set_inputs(u, "tto", [
        {"ref": "OIS_MAIN!J2", "value": "36,5"},           # percent cell: 36,5 means 36,5 %
        {"ref": "OIS_MAIN!F2", "value": "2.500"},          # Turkish thousands separator
        {"ref": "Forward!D2", "value": "4/2/27"},          # date
        {"ref": "OIS_MAIN!D3", "value": "-25"},
    ])
    assert res["errors"] == [] and res["applied"] == 4
    assert cell(service, "OIS_MAIN!J2", u) == pytest.approx(0.365)
    assert cell(service, "OIS_MAIN!F2", u) == 2500.0
    assert cell(service, "Forward!D2", u) == parse_date("04.02.2027")
    assert cell(service, "OIS_MAIN!D3", u) == -25.0
    en = service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!F2", "value": "2,500"}], lang="en")
    assert en["errors"] == [] and cell(service, "OIS_MAIN!F2", u) == 2500.0
    bad = service.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "geçersiz"}, {"ref": "Yok!A1", "value": 1}])
    assert bad["applied"] == 0 and len(bad["errors"]) == 2
    service.reset_inputs(u, "tto")
    assert service.my_inputs(u)["inputs"] == []


def test_spots_rates_prices_and_an_isin_are_typed_where_they_were_refused_as_dates(service):
    """These cells were declared dates: "45,5" typed into them gave "tarih anlaşılamadı".  Each column now takes what it
    holds - a spot, a rate (35,25 = %35,25), a price, an ISIN - and the date columns beside them still take dates only."""
    u = login(service, "Servis Girdi Türü")
    try:
        res = service.set_inputs(u, "tto", [
            {"ref": "Forward!D25", "value": "45,5"}, {"ref": "Forward!G25", "value": "4,25"}, {"ref": "Forward!H27", "value": "35,25"},
            {"ref": "Forward!C61", "value": "4.100,5"}, {"ref": "Forward!C63", "value": "1414"}, {"ref": "Forward!E59", "value": "45,5"},
            {"ref": "Forward!E63", "value": "4"}, {"ref": "Forward!E64", "value": "35,25"}, {"ref": "Forward!V56", "value": "TRT150328T24"},
            {"ref": "Forward!V57", "value": "98,5"}, {"ref": "Forward!V61", "value": "40"}, {"ref": "Forward!V78", "value": "35"},
            {"ref": "Forward!V79", "value": "36,5"}, {"ref": "Forward!AB1", "value": "34,5"}, {"ref": "Forward!N71", "value": "35,75"},
            {"ref": "Forward!AA58", "value": "13432"}, {"ref": "MASA!W94", "value": "45,5"}, {"ref": "Calculators!C54", "value": "98,7"},
            {"ref": "Calculators!I54", "value": "101,7"}, {"ref": "Forward!B25", "value": "03.12.2026"}])
        assert res["errors"] == []
        got = {ref: cell(service, ref, u) for ref in ("Forward!D25", "Forward!G25", "Forward!H27", "Forward!C61", "Forward!E59",
                                                      "Forward!E63", "Forward!E64", "Forward!V56", "Forward!V57", "Forward!V61",
                                                      "Forward!V78", "Forward!V79", "Forward!AB1", "MASA!W94", "Calculators!C54",
                                                      "Calculators!I54", "Forward!B25")}
        assert got == pytest.approx({"Forward!D25": 45.5, "Forward!G25": 0.0425, "Forward!H27": 0.3525, "Forward!C61": 4100.5,
                                     "Forward!E59": 45.5, "Forward!E63": 0.04, "Forward!E64": 0.3525, "Forward!V56": "TRT150328T24",
                                     "Forward!V57": 98.5, "Forward!V61": 0.4, "Forward!V78": 0.35, "Forward!V79": 0.365,
                                     "Forward!AB1": 34.5, "MASA!W94": 45.5, "Calculators!C54": 98.7, "Calculators!I54": 101.7,
                                     "Forward!B25": parse_date("03.12.2026")})
        # the rows compute with them: the forward of the list's first row, the TLREF spread of the price
        n = cell(service, "Forward!A25", u)
        assert n == 15.0 and cell(service, "Forward!F25", u) == pytest.approx(45.5 * (1 + 0.37 / 360 * n) / (1 + 0.0425 / 360 * n), rel=1e-12)
        assert cell(service, "Calculators!C56", u) == pytest.approx((100 - 98.7) / 100 * 365 / 1162 * 10000, rel=1e-12)
        bad = service.set_inputs(u, "tto", [{"ref": "Forward!B25", "value": "45,5"}, {"ref": "Forward!V58", "value": "TRT150328T24"}])
        assert len(bad["errors"]) == 2 and all("tarih anlaşılamadı" in e for e in bad["errors"])
    finally:
        service.reset_inputs(u, "tto")


def test_buy_or_sell_of_the_forward_dv01_blocks_is_b_or_s_and_nothing_else(service):
    """Forward!O44 and Calculators!X29 (B/S) had no list and their formulas test for "S" only: "Sat" priced a sale as a
    buy, silently.  Both offer B / S, take Al / Sat (Alış, Satış, Buy, Sell) for them and refuse anything else."""
    u = login(service, "Servis BS")
    try:
        for sheet, side, usd, view, panel in (("Forward", "O44", "O47", "forward", "B18"), ("Calculators", "X29", "X32", "calc", "B10")):
            ref = "%s!%s" % (sheet, side)
            info = service.cell_info(u, "tto", ref)["cell"]
            assert info["o"] == ["B", "S"] and info["i"] == "u", ref
            res = service.set_inputs(u, "tto", [{"ref": ref, "value": "B"}])
            assert res["errors"] == []
            buy = cell(service, "%s!%s" % (sheet, usd), u)
            for typed in ("Sat", "satış", "s", "Sell"):
                assert service.set_inputs(u, "tto", [{"ref": ref, "value": typed}])["errors"] == [], typed
                assert cell(service, ref, u) == "S" and cell(service, "%s!%s" % (sheet, usd), u) == pytest.approx(-buy), typed
            assert service.set_inputs(u, "tto", [{"ref": ref, "value": "al"}])["errors"] == [] and cell(service, ref, u) == "B"
            bad = service.set_inputs(u, "tto", [{"ref": ref, "value": "Satıcı"}])
            assert len(bad["errors"]) == 1 and "listede yok" in bad["errors"][0] and cell(service, ref, u) == "B"
    finally:
        service.reset_inputs(u, "tto")


def test_dv01_targets_and_pnl_take_the_desks_shorthand(service):
    """OIS "DV01/bacak $" (F2, read by ~900 formulas), USD "Hedef DV01" (B12) and the DV01 page's P&L (C140 / C141) hold
    full amounts; "5k" typed there stayed text and the pages went empty.  They are amount cells now."""
    u = login(service, "Servis Tutar")
    try:
        assert service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!F2", "value": "5k"}, {"ref": "DV01_RISK!C140", "value": "-2,5m"},
                                             {"ref": "DV01_RISK!C141", "value": "150 bin"}])["errors"] == []
        assert service.set_inputs(u, "sofr", [{"ref": "SOFR_FOMC!B12", "value": "10k"}])["errors"] == []
        assert cell(service, "OIS_MAIN!F2", u) == 5000.0 and cell(service, "SOFR_FOMC!B12", u, book="sofr") == 10000.0
        assert cell(service, "DV01_RISK!C140", u) == -2.5e6 and cell(service, "DV01_RISK!C141", u) == 150e3
        assert cell(service, "DV01_RISK!C142", u) == pytest.approx(-2.5e6 - 150e3 - cell(service, "DV01_RISK!C139", u))
        bad = service.set_inputs(u, "tto", [{"ref": "OIS_MAIN!F2", "value": "beş bin"}])
        assert len(bad["errors"]) == 1 and "tutar anlaşılamadı" in bad["errors"][0] and cell(service, "OIS_MAIN!F2", u) == 5000.0
    finally:
        service.reset_inputs(u, "tto")
        service.reset_inputs(u, "sofr")


def test_blanking_an_input_returns_to_the_formula_or_empties_the_cell(service):
    u = login(service, "Servis Blank")
    base = cell(service, "MASA!C60")                        # a formula default (start date)
    service.set_inputs(u, "tto", [{"ref": "MASA!C60", "value": "01.12.2026"}])
    assert cell(service, "MASA!C60", u) == parse_date("01.12.2026")
    service.set_inputs(u, "tto", [{"ref": "MASA!C60", "value": ""}])
    assert cell(service, "MASA!C60", u) == base
    service.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": ""}])      # a typed constant: really empty
    assert cell(service, "Forward!D2", u) is None
    service.reset_inputs(u, "tto")
    assert cell(service, "Forward!D2", u) == cell(service, "Forward!D2")


def test_only_input_cells_can_be_written(service):
    u = login(service, "Servis Guard")
    res = service.set_inputs(u, "tto", [{"ref": "Forward!D33", "value": 1}])
    assert res["applied"] == 0 and "girdi hücresi değil" in res["errors"][0]
    assert cell(service, "Forward!D33", u) == cell(service, "Forward!D33")
    with pytest.raises(ServiceError) as exc:
        service.set_inputs("kimse", "tto", [{"ref": "Forward!D2", "value": 1}])
    assert exc.value.status == 401
    with pytest.raises(ServiceError):
        service.set_inputs(None, "tto", [])


def test_scenarios_roundtrip(service):
    u, other = login(service, "Servis Senaryo"), login(service, "Servis Senaryo 2")
    service.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}, {"ref": "OIS_MAIN!D3", "value": "-50"}])
    service.set_inputs(u, "sofr", [{"ref": "SOFR_FOMC!B9", "value": "50"}])
    saved = service.save_scenario(u, "Şahin")
    assert saved["cells"] == 3
    service.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "01.03.2027"}, {"ref": "MASA!I60", "value": "10"}])
    service.save_scenario(u, "Güvercin")
    assert [s["name"] for s in service.scenarios(u)] == ["Güvercin", "Şahin"]
    assert service.scenarios(other) == []                                   # scenarios are personal
    assert service.load_scenario(u, "Şahin")["cells"] == 3
    assert cell(service, "Forward!D2", u) == parse_date("15.12.2026")
    assert cell(service, "OIS_MAIN!D3", u) == -50.0
    assert cell(service, "SOFR_FOMC!B9", u, "sofr") == 50.0
    assert cell(service, "MASA!I60", u) == cell(service, "MASA!I60")        # not part of that scenario
    service.load_scenario(u, "Güvercin")
    assert cell(service, "Forward!D2", u) == parse_date("01.03.2027") and cell(service, "MASA!I60", u) == 10.0
    with pytest.raises(ServiceError) as exc:
        service.load_scenario(other, "Şahin")
    assert exc.value.status == 404
    assert service.delete_scenario(u, "Şahin") == {"deleted": "Şahin"}
    with pytest.raises(ServiceError):
        service.delete_scenario(u, "Şahin")
    service.reset_inputs(u, "tto")
    service.reset_inputs(u, "sofr")


def test_usd_page_reacts_to_inputs(service):
    u = login(service, "Servis USD")
    before = cell(service, "SOFR_FOMC!K74", u, "sofr")
    assert isinstance(before, float)
    service.set_inputs(u, "sofr", [{"ref": "SOFR_FOMC!D49", "value": "4,25"}])     # manual 1W quote
    after = cell(service, "SOFR_FOMC!E49", u, "sofr")
    assert after == 4.25
    assert cell(service, "SOFR_FOMC!E49", None, "sofr") != 4.25
    service.reset_inputs(u, "sofr")


def test_cell_info_and_grid(service):
    info = service.cell_info(None, "tto", "OIS_MAIN!C9")
    assert info["formula"].startswith("=ROUND((B9-")
    assert info["ref"] == "OIS_MAIN!C9" and info["input"] is None
    g = service.grid(None, "tto", "Motor", "A86:E90")
    assert g["data"]["c"] == ["A", "B", "C", "D", "E"] and g["data"]["r"] == [86, 87, 88, 89, 90]
    with pytest.raises(ServiceError):
        service.grid(None, "tto", "Motor", "A1:ZZ9999")
    with pytest.raises(ServiceError) as exc:
        service.grid(None, "tto", "Yok", "A1:B2")
    assert exc.value.status == 404
    with pytest.raises(ServiceError):
        service.cell_info(None, "tto", "Yok!A1")
    assert [s["name"] for s in service.sheets("sofr")] == ["SOFR_FOMC"]
    # the dashboard's own sheets come last; four of the workbook's 17 are taken out (MOBIL MK, YP DIBS, Ivır Zıvır,
    # USDTRY IYIX)
    assert [s["name"] for s in service.sheets("tto")][-9:] == ["EK_FWD", "EK_XAU", "EK_VIOP", "EK_KAYNAK", "EK_BULK", "EK_DIBS", "EK_EVREN",
                                                                "EK_CARRY", "EK_IHALE"]
    assert len(service.sheets("tto")) == 17 - 4 + 9
    assert [s["name"] for s in service.sheets("borsa")] == ["bu", "Sheet1", "Sheet2"] and [s["name"] for s in service.sheets("asw")] == ["ASW", "EK_FX"]


def test_adhoc_what_if_on_any_cell(module_service):
    svc = module_service
    u = login(svc, "Servis Adhoc")
    base = cell(svc, "Forward!F2")
    res = svc.set_inputs(u, "tto", [{"ref": "Forward!F2", "value": "55"}], True)
    assert res["errors"] == []
    assert cell(svc, "Forward!F2", u) == 55.0
    assert cell(svc, "Forward!F2") == base                                   # only for me
    assert cell(svc, "Forward!D33", u) == pytest.approx(cell(svc, "Forward!D33") * 55.0 / base, rel=1e-12)
    svc.reset_inputs(u, "tto")
    assert cell(svc, "Forward!F2", u) == base


# ---------------------------------------------------------------------------------------------- RET curve
def test_ret_curve_is_shared_logged_and_survives_a_restart(tmp_path):
    svc = make_service(tmp_path)
    try:
        a, b = login(svc, "RET A"), login(svc, "RET B")
        base = svc.ret()
        assert svc.status()["ret"] is None                       # nothing loaded yet: the UI warns
        assert [r["tenor"] for r in base["rows"]] == ["ON", "TN", "1W", "2W", "3W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M", "2Y"]
        assert base["meta"] is None and svc.ret_history() == []
        fwd_before = cell(svc, "Forward!D33", b)
        res = svc.set_ret(a, [{"tenor": "1M", "bid": "34,00", "ask": "34,20"}, {"tenor": "3m", "bid": 0.351, "ask": "35,6%"},
                              {"tenor": "12M", "bid": "38,2", "ask": "39,3"}, {"tenor": "2Y", "bid": "", "ask": None},
                              {"tenor": "9M", "bid": "36,95", "ask": "37,95"}])
        assert res["errors"] == [] and res["applied"] == 8
        rows = {r["tenor"]: r for r in svc.ret()["rows"]}
        assert rows["1M"]["bid"] == pytest.approx(0.34) and rows["1M"]["ask"] == pytest.approx(0.342)
        assert rows["3M"]["bid"] == pytest.approx(0.351) and rows["3M"]["ask"] == pytest.approx(0.356)
        assert rows["1Y"]["bid"] == pytest.approx(0.382) and rows["1Y"]["ask"] == pytest.approx(0.393)
        assert rows["2Y"]["bid"] == {r["tenor"]: r for r in base["rows"]}["2Y"]["bid"]          # untouched
        # everybody sees it (the sheet and everything priced from it)
        assert cell(svc, "Forward!W38", b) == pytest.approx(0.34)
        assert cell(svc, "Forward!D33", b) != fwd_before            # 215 days: between the 6M and 9M nodes
        assert svc.cell_info(b, "tto", "Forward!W38")["cell"]["i"] == "s"
        meta = svc.ret()["meta"]
        assert meta["updated_by"] == a
        st = svc.status()
        assert st["ret"]["updated_by"] == a and st["ret"]["updated_at"][:10] == st["server_date"]      # loaded today
        hist = svc.ret_history()
        assert len(hist) == 1 and hist[0]["user"] == a
        assert {r["tenor"]: r for r in hist[0]["rows"]}["1M"]["bid"] == pytest.approx(0.34)
        # pasting straight into the sheet goes the same way
        res = svc.paste(b, "tto", "Forward!W33", "35,10%\t35,30%\r\n35,20%\t35,40%\r\n")
        assert res["applied"] == 4 and res["skipped"] == 0 and res["rows"] == 2 and res["cols"] == 2
        assert cell(svc, "Forward!X34", a) == pytest.approx(0.354)
        assert len(svc.ret_history()) == 2 and svc.ret_history()[0]["user"] == b
        with pytest.raises(ServiceError):
            svc.set_ret(a, [{"tenor": "7Y", "bid": 1}])
        with pytest.raises(ServiceError):
            svc.set_ret(a, [])
        expected = {r["tenor"]: (r["bid"], r["ask"]) for r in svc.ret()["rows"]}
        fwd_after = cell(svc, "Forward!D33")
    finally:
        svc.stop()
    again = make_service(tmp_path)                      # same data directory = a server restart
    try:
        assert {r["tenor"]: (r["bid"], r["ask"]) for r in again.ret()["rows"]} == expected
        assert cell(again, "Forward!D33") == fwd_after
        assert len(again.ret_history()) == 2
        assert again.store.user_exists(a)
    finally:
        again.stop()


def test_paste_skips_cells_that_are_not_inputs(module_service):
    svc = module_service
    u = login(svc, "Servis Paste")
    # U33:X34 = days (formula), tenor (text), bid, ask: only bid / ask are inputs
    res = svc.paste(u, "tto", "Forward!U33", "1\tON\t36,00%\t36,20%\n1\tTN\t36,10%\t36,30%")
    assert res["applied"] == 4 and res["skipped"] == 4
    assert cell(svc, "Forward!W34", u) == pytest.approx(0.361)
    with pytest.raises(ServiceError):
        svc.paste(u, "tto", "Forward!D33", "1\t2")
    with pytest.raises(ServiceError):
        svc.paste(u, "tto", "Yok!A1", "1")


def test_personal_inputs_survive_a_restart(tmp_path):
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Kalıcı Kullanıcı")
        svc.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}])
        svc.save_scenario(u, "Senaryo 1")
        expected = cell(svc, "Forward!D33", u)
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        assert again.login("kalıcı kullanıcı")["new"] is False            # the same person
        assert cell(again, "Forward!D33", u) == expected
        assert [s["name"] for s in again.scenarios(u)] == ["Senaryo 1"]
    finally:
        again.stop()


# ---------------------------------------------------------------------------------------------- hand values
def _cell_of(page, panel, ref):
    p = next(x for x in page["panels"] if x["id"] == panel)
    col = "".join(ch for ch in ref if ch.isalpha())
    row = int("".join(ch for ch in ref if ch.isdigit()))
    return p["data"]["rows"][p["data"]["r"].index(row)][p["data"]["c"].index(col)]


def test_a_value_typed_over_a_formula_is_mine_marked_and_undone_by_blanking(tmp_path):
    """"Elle değer": any cell of a page may be typed over - a formula too.  The value is the user's own, the
    cell is shown as theirs (and as an ordinary cell to everybody else), blanking it brings the formula back,
    and it is kept across a restart."""
    svc = make_service(tmp_path)
    try:
        u, w = login(svc, "Elle A"), login(svc, "Elle B")
        ref = "Forward!E33"                 # RET mid forward: a formula, no input (B15: among the helper tables)
        base = cell(svc, ref)
        assert _cell_of(svc.view(u, "forward", True), "B15", "E33").get("i") is None
        res = svc.set_inputs(u, "tto", [{"ref": ref, "value": "55"}])
        assert res["applied"] == 0 and "girdi hücresi değil" in res["errors"][0]          # not without the mode
        res = svc.set_inputs(u, "tto", [{"ref": ref, "value": "55"}], True)
        assert res["errors"] == [] and cell(svc, ref, u) == 55.0 and cell(svc, ref, w) == base == cell(svc, ref)
        assert cell(svc, "Forward!O46", u) == 55.0                         # what reads the cell follows
        mine = _cell_of(svc.view(u, "forward", True), "B15", "E33")
        assert (mine["i"], mine["m"], mine["fx"]) == ("u", 1, 1) and mine["v"] == 55.0
        for other in (w, None):
            c = _cell_of(svc.view(other, "forward", True), "B15", "E33")
            assert "i" not in c and "m" not in c and c["fx"] == 1 and c["v"] == base
        assert svc.my_inputs(u)["inputs"] == [{"book": "tto", "ref": ref, "value": 55.0, "label": ""}]
        # a constant typed over as well (a label here), and put back by blanking it
        assert cell(svc, "Forward!C2") == "Tarih"
        svc.set_inputs(u, "tto", [{"ref": "Forward!C2", "value": "Valör"}], True)
        assert cell(svc, "Forward!C2", u) == "Valör"
        svc.set_inputs(u, "tto", [{"ref": "Forward!C2", "value": ""}], True)
        assert cell(svc, "Forward!C2", u) == "Tarih"
    finally:
        svc.stop()
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Elle A")
        assert cell(svc, "Forward!E33", u) == 55.0 and cell(svc, "Forward!E33") == base
        assert _cell_of(svc.view(u, "forward", True), "B15", "E33")["m"] == 1
        # blanking: the formula is back and the cell is nobody's input any more
        res = svc.set_inputs(u, "tto", [{"ref": "Forward!E33", "value": ""}], True)
        assert res["errors"] == [] and cell(svc, "Forward!E33", u) == base
        assert "i" not in _cell_of(svc.view(u, "forward", True), "B15", "E33") and svc.my_inputs(u)["inputs"] == []
        # ... as does "back to the formulas" for a list of cells
        svc.set_inputs(u, "tto", [{"ref": "Forward!E33", "value": "56"}, {"ref": "Forward!D33", "value": "55,9"}], True)
        assert svc.reset_inputs(u, "tto", ["Forward!E33", "Forward!D33"])["reset"] == 2
        assert cell(svc, "Forward!E33", u) == base and cell(svc, "Forward!D33", u) == cell(svc, "Forward!D33")
    finally:
        svc.stop()


def test_the_first_value_typed_over_a_formula_keeps_everyones_computed_values(tmp_path):
    """The first value typed over a formula used to drop every computed value of every user: the header strip
    (MASA's KPIs, a long chain of the Motor sheet) then took ~20 s on the desk's machine, everybody waiting on the
    one calculation thread.  Nothing is dropped now; what reads the cell follows it for its user only."""
    svc = make_service(tmp_path)
    try:
        u, w = login(svc, "Elle Hızlı A"), login(svc, "Elle Hızlı B")
        svc.header(None)
        svc.view(w, "forward")
        eng = svc.books["tto"].engine
        before = sum(len(m) for m in eng.shared.memo)
        base, o46 = cell(svc, "Forward!E33"), cell(svc, "Forward!O46")
        assert svc.set_inputs(u, "tto", [{"ref": "Forward!E33", "value": "55"}], True)["errors"] == []
        assert sum(len(m) for m in eng.shared.memo) >= before                       # nothing dropped
        evals = eng.shared.evals
        svc.header(u)
        svc.header(w)
        assert eng.shared.evals - evals < 50                                         # the header is not computed again
        assert cell(svc, "Forward!E33", u) == 55.0 and cell(svc, "Forward!O46", u) == 55.0
        assert cell(svc, "Forward!E33", w) == base and cell(svc, "Forward!O46", w) == o46 == cell(svc, "Forward!O46")
        svc.set_inputs(u, "tto", [{"ref": "Forward!E33", "value": "56"}], True)
        assert cell(svc, "Forward!O46", u) == 56.0 and cell(svc, "Forward!O46", w) == o46
        svc.reset_inputs(u, "tto")
        assert cell(svc, "Forward!O46", u) == o46
    finally:
        svc.stop()


def test_forward_calculators_take_dates_spot_and_the_foreign_rate_by_hand(service):
    """The calculators on the right of the Forward sheet read their dates, the spot and the USD / EUR rate from
    the sheet.  Each of those can be typed over; blanking returns to the sheet's value."""
    u = login(service, "Hesap Elle")
    page = service.view(u, "forward")
    for ref in ("AH5", "AH6", "AH8", "AH9", "AK5", "AK6", "AK8", "AK9"):
        c = _cell_of(page, "B7", ref)
        assert c["i"] == "u" and c["fx"] == 1 and "m" not in c, ref          # an input the sheet fills by itself
    assert _cell_of(page, "B7", "AH10")["i"] == "u" and "fx" not in _cell_of(page, "B7", "AH10")      # the TRY rate: typed
    assert "i" not in _cell_of(page, "B7", "AH11")                                                      # the result
    sp0, fwd0 = cell(service, "Forward!AH11"), cell(service, "Forward!AH12")
    days = cell(service, "Forward!AH7")
    res = service.set_inputs(u, "tto", [{"ref": "Forward!AH8", "value": "50,50"}, {"ref": "Forward!AH9", "value": "4,5"},
                                        {"ref": "Forward!AH6", "value": "15.01.2027"}])
    assert res["errors"] == []
    first = cell(service, "Forward!AH5")                         # Bloomberg's SETTLE_DT: a date as text offline
    n = parse_date("15.01.2027") - (parse_date(first) if isinstance(first, str) else first)
    assert cell(service, "Forward!AH7", u) == n != days
    sp = 50.50 * ((1 + 0.36 / 360 * n) / (1 + 0.045 / 360 * n) - 1) * 10000
    assert cell(service, "Forward!AH11", u) == pytest.approx(sp, rel=1e-13)
    assert cell(service, "Forward!AH22", u) == 50.50 and cell(service, "Forward!AH20", u) == parse_date("15.01.2027")   # the next one follows
    assert cell(service, "Forward!AH11") == sp0                                                            # mine alone
    c = _cell_of(service.view(u, "forward"), "B7", "AH8")
    assert (c["i"], c["m"], c["fx"]) == ("u", 1, 1)
    service.set_inputs(u, "tto", [{"ref": "Forward!AH%d" % r, "value": ""} for r in (6, 8, 9)])
    assert cell(service, "Forward!AH11", u) == sp0 and cell(service, "Forward!AH12", u) == fwd0
    # the spot of the whole page (Bloomberg's mid) and its value date, when Bloomberg does not deliver them
    service.set_inputs(u, "tto", [{"ref": "Forward!F2", "value": "51"}, {"ref": "Forward!I2", "value": "05.11.2026"}])
    assert cell(service, "Forward!AH8", u) == 51.0 and cell(service, "Forward!AH5", u) == parse_date("05.11.2026")
    assert cell(service, "Forward!O32", u) == 51.0 and cell(service, "Forward!F2") != 51.0
    service.reset_inputs(u, "tto")
    assert cell(service, "Forward!AH8", u) == cell(service, "Forward!F2")
    # the three USDTRY contract calculators of the VİOP page (helper tables now: Interest 2 SP lives on the Forward page)
    vp = service.view(u, "viop", True)
    for ref in ("M32", "M33", "M35", "M36", "P33", "S36"):
        c = _cell_of(vp, "B8", ref)
        assert c["i"] == "u" and c["fx"] == 1, ref
    service.set_inputs(u, "tto", [{"ref": "VIOP!M35", "value": "50"}, {"ref": "VIOP!M36", "value": "4"}, {"ref": "VIOP!M37", "value": "34,05"}])
    n = cell(service, "VIOP!M34", u)
    assert cell(service, "VIOP!M38", u) == pytest.approx(50 * ((1 + 0.3405 / 360 * n) / (1 + 0.04 / 360 * n) - 1) * 10000, rel=1e-13)
    assert cell(service, "VIOP!P35", u) == 50.0                                 # the second calculator reads the first one's spot
    service.reset_inputs(u, "tto")


def test_pages_come_in_tabs_with_the_calculators_first(service):
    page = service.view(None, "forward")
    assert page["pinned"] == ["B1"]
    tabs = page["sections"]
    assert [s["id"] for s in tabs] == ["calc", "fwd", "kot", "ret", "bulk", "curves", "off", "tick"]
    assert tabs[0]["title"] == "Hesaplayıcılar" and tabs[0]["panels"][:5] == ["B7", "B8", "B9", "B10", "B11"] and tabs[0]["note"]
    shown = [p["id"] for p in page["panels"]]
    listed = [pid for s in tabs for pid in s["panels"]]
    assert sorted(listed + page["pinned"]) == sorted(shown) and len(listed) == len(set(listed))
    # the value date strip: captions of the dashboard's own above the cells the sheet leaves unnamed
    b1 = next(p for p in page["panels"] if p["id"] == "B1")["data"]
    assert b1["r"] == [0, 2] and b1["c"] == ["C", "D", "F", "G", "I", "K"]
    assert [c["t"] for c in b1["rows"][0]] == ["", "Valör tarihi", "USDTRY spot", "EURTRY spot", "USDTRY spot valörü", "EURTRY spot valörü"]
    assert b1["rows"][1][0]["t"] == "Tarih" and [c.get("i") for c in b1["rows"][1]] == [None, "u", "u", "u", "u", "u"]
    # the RET table has the button of the RET editor
    assert next(p for p in page["panels"] if p["id"] == "B19")["action"] == "ret"
    # with the helper tables: they get a tab of their own, nothing is left out
    full = service.view(None, "forward", True)
    assert [s["id"] for s in full["sections"]][-1] == "aux" and full["sections"][-1]["title"] == "Yardımcı tablolar"
    assert "B22" in full["sections"][-1]["panels"] and full["sections"][0] == tabs[0]
    assert sorted(pid for s in full["sections"] for pid in s["panels"]) + ["B1"] == sorted(p["id"] for p in full["panels"] if p["id"] != "B1") + ["B1"]
    # a page without tabs
    small = service.view(None, "bulk")
    assert small["sections"] == [] and small["pinned"] == []
    # a calculator may be in two tabs (VİOP: the gold calculator)
    viop = {s["id"]: s for s in service.view(None, "viop")["sections"]}
    assert viop["calc"]["panels"] == ["XAU4"] and "XAU4" in viop["gold"]["panels"]
    # the search box of the top bar: the tables of every page, with their tab
    pages = {p["id"]: p for p in service.nav()}
    tables = {t["id"]: t for t in pages["forward"]["tables"]}
    assert tables["B7"]["tab"] == "Hesaplayıcılar" and tables["B7"]["title"].startswith("Interest 2 SP")
    assert tables["B19"]["tab"] == "RET" and "B22" not in tables and "tables" not in pages["blotter"]


def test_holidays_are_edited_in_one_place_for_both_workbooks(tmp_path):
    """The TR holidays live twice: the TRY workbook's Motor!A361:B523 (date and name, read by every WORKDAY) and the ASW
    workbook's ASW!LR2:LR200 (dates).  The settings page edits them as one list and writes both; the US holidays and the
    FOMC meetings of the USD workbook come with it.  Kept by the store: a restart has the same list."""
    from starlette.testclient import TestClient
    from conftest import auth
    from tto.server import create_app
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Tatil Yazan")
        hol = svc.holidays()
        assert hol["available"] and hol["books"] == ["tto", "asw"] and hol["slots"] == 163
        days = {x["date"]: x["name"] for x in hol["tr"]}
        # the ASW list has 2026's earlier holidays as well: both lists together, the names from the TRY one
        assert len(days) == 152 and days["2026-01-01"] == "" and days["2026-10-29"] == "Cumhuriyet" and days["2027-01-01"] == "Yılbaşı"
        assert hol["us"][:2] == ["2026-01-01", "2026-01-19"] and len(hol["fomc"]) == 10 and hol["fomc"][0] == "2026-12-09"
        # 04.11.2026 a holiday: the next business day of the save day (03.11.2026) moves for everyone, in both workbooks
        assert cell(svc, "DİBS RV!D2") == parse_date("04.11.2026")
        items = [{"date": d, "name": n} for d, n in days.items() if d != "2027-01-01"] + [{"date": "04.11.2026", "name": "Deneme tatili"},
                                                                                         {"date": "2026-11-04", "name": ""}]
        res = svc.set_holidays(u, items)
        assert res["saved"] == 152 and res["tr"][len([d for d in days if d < "2026-11-04"])] == {"date": "2026-11-04", "name": "Deneme tatili"}
        assert cell(svc, "DİBS RV!D2") == parse_date("05.11.2026")
        motor = [cell(svc, "Motor!A%d" % r) for r in range(361, 524)]
        names = [cell(svc, "Motor!B%d" % r) for r in range(361, 524)]
        asw = [cell(svc, "ASW!LR%d" % r, book="asw") for r in range(2, 201)]
        serial = parse_date("04.11.2026")
        assert serial in motor and serial in asw and names[motor.index(serial)] == "Deneme tatili"
        assert parse_date("01.01.2027") not in motor and parse_date("01.01.2027") not in asw
        assert motor == sorted(x for x in motor if x is not None) + [None] * motor.count(None)          # in date order
        assert motor.count(None) == 163 - 152 and asw.count(None) == 199 - 152
        # refused: a day that is no date, more days than the list has rows
        with pytest.raises(ServiceError):
            svc.set_holidays(u, [{"date": "31.02.2027"}])
        with pytest.raises(ServiceError):
            svc.set_holidays(u, ["%02d.01.2030" % d for d in range(1, 32)] + ["%02d.%02d.2031" % (d, m) for m in range(1, 7) for d in range(1, 29)])
        assert len(svc.holidays()["tr"]) == 152
        with TestClient(create_app(svc)) as client:                     # (its shutdown stops the service)
            hdr = auth(svc, "Tatil Okuyan")
            got = client.get("/api/holidays", headers=hdr).json()
            assert got["tr"] == res["tr"] and got["fomc"] == hol["fomc"]
            back = client.post("/api/holidays", json={"items": [{"date": d, "name": n} for d, n in days.items()]}, headers=hdr)
            assert back.status_code == 200 and back.json()["tr"] == hol["tr"]
            assert client.post("/api/holidays", json={"items": "x"}, headers=hdr).status_code == 400
            assert cell(svc, "DİBS RV!D2") == parse_date("04.11.2026")
            # the file's own list again everywhere the file had it: nothing stored for those rows
            stored = svc.store.shared_inputs("asw")
            assert not any(ref.startswith("ASW!LR") for _, ref in stored)
            svc.set_holidays(u, items)
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        assert {x["date"]: x["name"] for x in again.holidays()["tr"]}["2026-11-04"] == "Deneme tatili"
        assert cell(again, "DİBS RV!D2") == parse_date("05.11.2026")
    finally:
        again.stop()
