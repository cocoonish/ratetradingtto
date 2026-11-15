"""Application service: pages, personal vs shared inputs, scenarios, the RET curve."""
import pytest

from conftest import cell, make_service
from tto.inputs import parse_date
from tto.service import ServiceError
from tto.views import load_views
from tto.xl.model import COLS, parse_a1

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
    assert custom == ["watch", "heat", "blotter", "broker", "eod", "mpc", "vol", "spreads", "settings", "fx", "fxvol", "quant", "quant-corr",
                      "quant-pca", "quant-pairs", "quant-regime", "quant-fx", "quant-macro", "quant-model", "quant-curve", "quant-opt",
                      "social", "agenda"]
    assert len(ids) == len(set(ids)) == len(VIEW_IDS) + 23


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
    assert [s["name"] for s in service.sheets("tto")][-10:] == ["EK_TATIL", "EK_FWD", "EK_XAU", "EK_VIOP", "EK_KAYNAK", "EK_BULK", "EK_DIBS",
                                                                 "EK_EVREN", "EK_CARRY", "EK_IHALE"]
    assert len(service.sheets("tto")) == 17 - 4 + 10
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
    assert b1["r"] == [0, 2] and b1["c"] == ["C", "D", "F", "G", "I", "J", "K", "L"]
    assert [c["t"] for c in b1["rows"][0]] == ["", "Valör tarihi", "USDTRY spot", "EURTRY spot", "USDTRY spot valörü", "Bloomberg valörü",
                                               "EURTRY spot valörü", "Bloomberg valörü"]
    # (each spot date the desk's - typed over, a user's own -, Bloomberg's beside it for comparison)
    assert b1["rows"][1][0]["t"] == "Tarih" and [c.get("i") for c in b1["rows"][1]] == [None, "u", "u", "u", "u", None, "u", None]
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


# ====================================================================================== operations (ops.py)
@pytest.fixture()
def log_to(tmp_path):
    """The dashboard's rotating log file in a folder of the test (taken off again afterwards)."""
    import logging
    from tto import ops
    logger = logging.getLogger("tto")
    before, level = list(logger.handlers), logger.level

    def setup(folder):
        return ops.setup_logging(str(folder))

    yield setup
    for h in list(logger.handlers):
        if h not in before:
            logger.removeHandler(h)
            h.close()
    logger.setLevel(level)
    ops._LOG_FILE[:] = []


def test_the_loops_say_what_they_survive_and_the_status_tells_it(tmp_path, log_to):
    """The market and watch loops used to swallow every exception without a word.  Now each fault goes to the log
    file (the first time with its traceback, then once a minute with a count) and the status shows the last one,
    with the calculation thread's queue."""
    import time as _time
    from tto.config import Settings
    from tto.service import Service
    path = log_to(tmp_path / "logs")
    svc = Service(Settings(data_dir=str(tmp_path / "data"), mode="replay", history=False, tick_seconds=0.1))
    try:
        st = svc.status()["ops"]
        assert st["engine"] == {"queue": 0, "busy": 0.0} and st["last_error"] is None
        assert st["feed"]["state"] == "replay" and st["log"] == path and st["settings"]["market_open"] == "09:00"

        def broken():
            raise KeyError("bozuk anahtar")

        svc.provider.drain_changes = broken                      # the market loop fails on every round
        svc.start()
        deadline = _time.time() + 15
        while _time.time() < deadline and ((svc.ops.last_error or {}).get("count") or 0) < 5:
            _time.sleep(0.05)
        le = svc.status()["ops"]["last_error"]
        assert le["where"] == "piyasa döngüsü" and le["text"] == "KeyError: 'bozuk anahtar'" and le["count"] >= 5
        # the watch loop's faults as well
        svc.watch.tick = lambda: 1 / 0
        svc._watch_kick.set()
        while _time.time() < deadline and svc.ops.last_error["where"] != "izleme / alarm döngüsü":
            _time.sleep(0.05)
        assert svc.ops.last_error["text"].startswith("ZeroDivisionError")
    finally:
        svc.stop()
        svc.store.close()
    text = open(path, encoding="utf-8").read()
    # written once with where it came from, not on every round (the loop went round dozens of times)
    assert text.count("piyasa döngüsü: KeyError: 'bozuk anahtar'") == 1 and "Traceback" in text and "in broken" in text
    assert "izleme / alarm döngüsü: ZeroDivisionError" in text


def test_market_hours_follow_the_desks_days_and_settings(module_service):
    import datetime as _dt
    ops = module_service.ops
    assert ops.market_hours(_dt.datetime(2026, 11, 13, 10, 0)) is True             # a Friday
    assert ops.in_market() is True                                                 # the last answer, at hand
    assert ops.market_hours(_dt.datetime(2026, 11, 13, 8, 59)) is False
    assert ops.market_hours(_dt.datetime(2026, 11, 13, 18, 0)) is False
    assert ops.market_hours(_dt.datetime(2026, 11, 14, 10, 0)) is False            # a Saturday
    assert ops.market_hours(_dt.datetime(2026, 10, 29, 10, 0)) is False            # a holiday of the desk (the workbook's list)
    cur = ops.set_settings({"market_open": "8.30", "market_close": "18:30", "tick_stale": "300"})
    try:
        assert (cur["market_open"], cur["market_close"], cur["tick_stale"]) == ("08:30", "18:30", 300)
        assert ops.market_hours(_dt.datetime(2026, 11, 13, 8, 45)) is True
        for bad in ({"market_open": "25:00"}, {"market_open": "19:00"}, {"tick_stale": "yok"}, {"tick_stale": 0}):
            with pytest.raises(ValueError):
                ops.set_settings(bad)
        assert ops.settings()["tick_stale"] == 300                                 # a refused change changes nothing
    finally:
        module_service.store.put("ops.settings", {})


def test_a_damaged_database_is_told_at_the_start(tmp_path, capsys):
    """``PRAGMA quick_check`` at every start: a damaged file is said on the console, in the log and the status (the
    page tells everyone); the dashboard still runs on what it can read.  A file that cannot be opened at all stops
    the start with where the newest backup is."""
    import os
    from test_store import damage, fill_history
    from tto.config import Settings
    from tto.service import Service
    from tto.store import Store
    data = tmp_path / "data"
    s = Store(str(data / "tto.db"))
    s.login("Ali")
    s.backup_to(str(data / "backups" / "tto-2026-11-14.db"))
    fill_history(s)
    s.close()
    damage(str(data / "tto.db"))
    svc = Service(Settings(data_dir=str(data), mode="replay", history=False))
    try:
        out = capsys.readouterr().out
        assert "UYARI: VERİTABANI DENETİMİ BAŞARISIZ" in out and "tto-2026-11-14.db" in out
        db = svc.status()["ops"]["db"]
        assert db["check"]["ok"] is False and db["check"]["problems"]
        assert db["backup"]["count"] == 1 and db["backup"]["last"]["name"] == "tto-2026-11-14.db"
        assert svc.store.user_exists("ali")                                   # what can be read still is
    finally:
        svc.stop()
        svc.store.close()
    # not a database at all: the start stops and says where the backup is
    bad = tmp_path / "bad"
    os.makedirs(str(bad / "backups"))
    (bad / "tto.db").write_bytes(b"bozuk" * 2000)
    (bad / "backups" / "tto-2026-11-13.db").write_bytes(b"")
    with pytest.raises(RuntimeError) as err:
        Service(Settings(data_dir=str(bad), mode="replay", history=False))
    assert "Veritabanı açılamadı" in str(err.value) and "tto-2026-11-13.db" in str(err.value) and "yedekten-don" in str(err.value)


def test_a_package_of_ois_legs_is_kept_whole(module_service, monkeypatch):
    """The legs of a package go in one transaction: a leg that cannot be written leaves no leg of it."""
    import sqlite3
    store = module_service.store
    u = module_service.login("Paket Giren")["user"]
    before = len(store.trades(module_service.today_iso()))
    store._db.execute("CREATE TRIGGER refuse_leg BEFORE INSERT ON trades WHEN NEW.payload LIKE '%\"tenor\": \"2Y\"%' "
                      "BEGIN SELECT RAISE(ABORT, 'disk dolu'); END")
    try:
        with pytest.raises(sqlite3.DatabaseError):         # the second leg (2Y) of the spread is refused
            module_service.add_ois(u, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": "25",
                                       "dv01": 1000})
    finally:
        store._db.execute("DROP TRIGGER refuse_leg")
    assert len(store.trades(module_service.today_iso())) == before               # the first leg is not left alone
    res = module_service.add_ois(u, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "2Y", "level": "25",
                                     "dv01": 1000})
    assert len(res["ids"]) == 2 and len(store.trades(module_service.today_iso())) == before + 2
    module_service.delete_trade(u, res["ids"][0])                                 # (the module's other tests see no trades)


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


def test_the_motor_page_is_for_administrators_and_two_pages_have_their_desk_names(service):
    """The Motor sheet (the workbook's engine: bootstrap, solver, holidays) is an administrator's page: not in anyone
    else's menu, search or shortcuts, and refused to them; the service itself (no user) still renders it.  "Bulk Bond"
    holds the desk's Eurobonds (XS ISINs, dealer pricing sources) and is named so; "TM OIS" is the cash-flow OIS."""
    user = login(service, "Motor Görmeyen")
    admin = login(service, "Motor Yöneticisi")
    service.store.update_account(admin, role="admin")
    assert "motor" not in [p["id"] for p in service.nav(user)] and "motor" in [p["id"] for p in service.nav(admin)]
    assert "motor" in [p["id"] for p in service.nav()]
    with pytest.raises(ServiceError) as exc:
        service.view(user, "motor")
    assert exc.value.status == 403
    assert service.view(admin, "motor")["id"] == "motor" and service.view(None, "motor")["id"] == "motor"
    assert "motor" not in {link["page"] for link in service.view(user, "masa")["links"]}
    assert "motor" in {link["page"] for link in service.view(admin, "masa")["links"]}
    # the page everybody shares is kept - also when the service itself made it (the warm-up has no user): kept, the
    # administrators' page reaches no one else, nor does a shortcut to it
    service.view(None, "motor")
    service.view(None, "masa")
    with pytest.raises(ServiceError) as exc:
        service.view(user, "motor")
    assert exc.value.status == 403
    assert "motor" not in {link["page"] for link in service.view(user, "masa")["links"]}
    titles = {p["id"]: p["title"] for p in service.nav(user)}
    assert titles["bulk"] == "Eurobond Kotaları" and titles["tmois"] == "OIS · Nakit Akışı"
    isins = [cell(service, "Bulk Bond!A%d" % r) for r in (3, 4, 5)]
    assert all(i.startswith("XS") for i in isins)                     # international (Euroclear / Clearstream) bonds


def test_the_calculation_thread_evaluates_long_chains_in_one_go(service):
    """The calculation thread runs on a big stack (255 MiB: Windows refuses 256) and evaluates DEEP_LIMIT nested
    cells before unwinding - the header's Motor chain is no longer unwound and restarted (~7x slower).  Every other
    thread keeps DEPTH_LIMIT.  (``tools/depth_check.py`` renders every page both ways: identical.)"""
    from tto.xl.engine import DEEP_LIMIT, DEPTH_LIMIT, depth_limit
    assert service.et.call(depth_limit) == DEEP_LIMIT and depth_limit() == DEPTH_LIMIT
    eng = service.books["tto"].engine
    service.et.call(eng.reset)                           # from cold
    service.bump()
    before = eng.shared.restarts
    assert service.header(None)["items"]
    assert eng.shared.restarts == before                 # nothing unwound


def _constant_read_by(book, cells):
    """A constant (no input, no formula) that one of ``cells`` reads."""
    eng = book.engine
    idx = eng.ref_index()
    for s in book.model.sheets:
        si = s.index
        for rc, v in sorted(s.consts.items()):
            if type(v) is not float or (si, rc) in book.inputs or rc in s.fml or rc in eng.spill_zone[si] or rc in eng.members[si]:
                continue
            if any(h in cells for h in idx.readers(si, rc)):
                return book.ref(si, rc), v
    raise AssertionError("no constant found")


def _page_cells(book, page):
    out = set()
    for p in page["panels"]:
        d = p.get("data") or {}
        if d.get("sheet") in book.model.sheet_index and d.get("r"):
            si = book.model.sheet_index[d["sheet"]]
            out.update((si, r * COLS + parse_a1(c + "1") % COLS) for r in d["r"] for c in d["c"])
    return out


def test_a_constant_typed_over_on_a_page_drops_nobodys_values(tmp_path):
    """"Elle değer" over a constant: the values that follow from it (by the formulas that name it) are marked, nothing
    of anybody's is dropped - it used to drop every value of every user (the next pages ~10 s, for everybody).  The
    user's pages are what a calculation from scratch gives; everybody else's stay, without being computed again."""
    svc = make_service(tmp_path)
    try:
        u, w = login(svc, "Sabit A"), login(svc, "Sabit B")
        book = svc.books["tto"]
        eng = book.engine
        page_w = svc.view(w, "ois")
        svc.header(None)
        ref, v = svc.et.call(_constant_read_by, book, _page_cells(book, page_w))      # (Motor!C4: deep in the chain)
        memo = sum(len(m) for m in eng.shared.memo)
        res = svc.set_inputs(u, "tto", [{"ref": ref, "value": repr(v * 3 + 1)}], True, "en")
        assert res["errors"] == [] and eng.marked >= 1
        assert sum(len(m) for m in eng.shared.memo) >= memo                       # nothing dropped
        evals = eng.shared.evals
        assert svc.view(w, "ois")["panels"] == page_w["panels"]                   # the others: as they were ...
        assert eng.shared.evals == evals                                           # ... without a calculation
        mine = svc.view(u, "ois", True)
        mine_header = svc.header(u)
        assert mine["panels"] != svc.view(w, "ois", True)["panels"]               # (the value reaches the page)
        svc.et.call(eng.reset)                                                     # from scratch: the same
        svc.bump()
        assert svc.view(u, "ois", True)["panels"] == mine["panels"]
        assert svc.header(u)["items"] == mine_header["items"]
    finally:
        svc.stop()


def test_hand_values_and_scenarios_saved_earlier_are_declared_at_the_start(tmp_path):
    """Every cell a user typed over or keeps in a scenario is declared when the service starts, before anything is
    computed: nobody's first request after a restart - nor loading a scenario - drops everybody's values any more."""
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Kayıtlı Elle")
        book = svc.books["tto"]
        s = book.model.sheets[book.model.sheet_index["MASA"]]
        consts = [book.ref(s.index, rc) for rc, v in sorted(s.consts.items())
                  if type(v) is float and (s.index, rc) not in book.inputs and rc not in s.fml][:2]
        svc.set_inputs(u, "tto", [{"ref": consts[0], "value": "7"}], True, "en")
        svc.save_scenario(u, "S1")
        svc.set_inputs(u, "tto", [{"ref": consts[0], "value": ""}, {"ref": consts[1], "value": "8"}], True, "en")
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        book = again.books["tto"]
        eng = book.engine
        assert all(book.cell(r) in book.inputs for r in consts)               # (declared at the start)
        resets = []
        real = eng.reset
        eng.reset = lambda: (resets.append(1), real())
        again.header(None)
        memo = sum(len(m) for m in eng.shared.memo)
        assert cell(again, consts[1], u) == 8.0 and again.header(u)["items"]
        again.load_scenario(u, "S1")
        assert cell(again, consts[0], u) == 7.0
        assert resets == [] and sum(len(m) for m in eng.shared.memo) >= memo
    finally:
        again.stop()


# ---------------------------------------------------------------------------------------------- the calculation thread
def test_the_calculation_thread_takes_what_was_typed_before_the_header_pages_and_background(service):
    """One calculation thread does everything; what waits goes by priority - inputs typed (and market ticks), then
    the header strip, then pages, then the background (watch lists, warming up) - first come first served within one."""
    import threading
    et = service.et
    gate = threading.Event()
    order = []
    et.submit_at(et.WRITE, gate.wait, 10)
    futs = [et.submit_at(et.BACKGROUND, order.append, "background"), et.submit_at(et.VIEW, order.append, "page"),
            et.submit_at(et.HEADER, order.append, "header"), et.submit_at(et.WRITE, order.append, "typed"),
            et.submit_at(et.VIEW, order.append, "page 2")]
    gate.set()
    for f in futs:
        f.result(timeout=30)
    assert order == ["typed", "header", "page", "page 2", "background"]


def test_the_same_page_asked_again_while_it_is_made_is_made_once(service):
    """Two tabs of one user (or a refresh on the heels of another) ask for the same page of the same generation:
    one calculation, both get it."""
    import threading
    u = login(service, "Aynı Sayfa")
    gate = threading.Event()
    service.et.submit_at(service.et.WRITE, gate.wait, 10)
    service.bump()
    made = []
    real = service._render
    service._render = lambda *a: (made.append(a[3]), real(*a))[1]
    try:
        before = len(service._inflight)
        f1, f2 = service.view_future(u, "calc"), service.view_future(u, "calc")
        h1, h2 = service.header_future(u), service.header_future(u)
        assert len(service._inflight) == before + 2 and not f1.done()      # one page job, one header job
        gate.set()
        assert f1.result(timeout=120)["panels"] == f2.result(timeout=120)["panels"]
        assert h1.result(timeout=120)["items"] == h2.result(timeout=120)["items"]
        assert made == ["calc"]
    finally:
        del service._render


# ---------------------------------------------------------------------------------------------- pages kept
def _made_panels(svc):
    """Count the panels made (not kept) from now on: (counter, undo)."""
    made = []
    real = svc._panel
    svc._panel = lambda *a: (made.append(a[0].get("id")), real(*a))[1]
    return made, lambda: svc.__dict__.pop("_panel", None)


def test_a_page_is_made_once_for_everybody_without_inputs_and_only_what_changed_again(tmp_path):
    """Pages are kept per calculation: two users without inputs of their own share one; a new generation in which
    nothing they read changed makes no panel again (and ``since`` answers "unchanged"); a shared input makes again only
    the panels that read it - what is kept equals a page made from scratch."""
    svc = make_service(tmp_path)
    try:
        a, b = login(svc, "Pay A"), login(svc, "Pay B")
        made, undo = _made_panels(svc)
        try:
            first = svc.view(a, "forward")
            n = len(made)
            assert n > 30 and svc.view(b, "forward")["panels"] == first["panels"] and len(made) == n   # B: kept
            svc.bump()
            again = svc.view(b, "forward")
            assert len(made) == n and again["panels"] == first["panels"] and again["gen"] == svc.gen
            assert svc.view(a, "forward", since=first["gen"]) == {"id": "forward", "gen": svc.gen, "unchanged": True, "as": "s"}
            # the RET curve (a shared input): the panels that read it, and only those
            svc.set_inputs(a, "tto", [{"ref": "Forward!W40", "value": "41,5"}])
            g = svc.gen
            made.clear()
            part = svc.view(b, "forward", since=again["gen"])
            assert part["partial"] and 0 < len(part["panels"]) < len(first["panels"])
            assert set(made) >= {p["id"] for p in part["panels"]} and len(made) < n
            assert svc.view(a, "forward")["panels"] == svc.et.call(svc._view, a, "forward", False, None)["panels"]
            assert svc.view(a, "forward", since=g) ["unchanged"]
        finally:
            undo()
    finally:
        svc.stop()


def test_only_the_panels_asked_for_are_made_and_sent(service):
    """The browser asks for the panels of the open tab: only those are made (and sent); another tab's are made when
    they are asked for."""
    u = login(service, "Sekme Kullanıcı")
    page = service.view(u, "forward")
    tabs = {s["id"]: s["panels"] for s in page["sections"]}
    service.bump()
    made, undo = _made_panels(service)
    try:
        calc = tabs["calc"] + page["pinned"]
        part = service.view(u, "forward", panels=calc)
        assert part["partial"] and [p["id"] for p in part["panels"]] == [i.split(":")[0] for i in page["ids"] if i.split(":")[0] in calc]
        assert part["ids"] == page["ids"] and part["sections"] == page["sections"]
        other = service.view(u, "forward", panels=tabs["ret"])
        assert {p["id"] for p in other["panels"]} == set(tabs["ret"])
    finally:
        undo()


def test_a_user_who_types_a_value_gets_a_page_of_their_own_at_once(service):
    """A value typed by a user makes their page their own (``as``: "p") at once - also when the browser asks "since" a
    generation of the page everybody shares (then it gets the whole page); blanking it gives the shared page back."""
    u = login(service, "Kendi Sayfası")
    shared = service.view(u, "forward")
    assert shared["as"] == "s"
    service.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}])
    mine = service.view(u, "forward", since=shared["gen"], as_="s")
    assert mine["as"] == "p" and len(mine["panels"]) == len(shared["panels"])
    assert any(c.get("m") == 1 for p in mine["panels"] for row in (p.get("data") or {}).get("rows", []) for c in row)
    assert service.header(u)["as"] == "p"
    service.reset_inputs(u, "tto")
    back = service.view(u, "forward", since=mine["gen"], as_="p")
    assert back["as"] == "s" and len(back["panels"]) == len(shared["panels"])


def test_the_pages_are_told_of_new_generations_at_most_once_a_second(service):
    """A busy market bumps the generation every 0.3 s and every page asks again when told: they are told at most once
    a second - of the last generation."""
    import time
    told = []
    service.add_listener(told.append)
    try:
        time.sleep(1.1)
        for _ in range(5):
            service.bump()
        assert len(told) == 1
        time.sleep(1.3)
        assert len(told) == 2 and told[-1] == service.gen
    finally:
        service.remove_listener(told.append)


def test_the_header_is_kept_and_answers_unchanged(service):
    u = login(service, "Şerit")
    h = service.header(u)
    service.bump()
    again = service.header(u, since=h["gen"])
    assert again["unchanged"] and again["as"] == "s"
    assert service.header(u)["items"] == h["items"]


def test_a_user_with_inputs_of_their_own_follows_the_market_every_few_seconds(tmp_path):
    """The header (and pages) of a user with inputs of their own is a calculation of its own: a market change makes
    it again at most every ``private_refresh`` seconds; their own change, or a shared input, at once.  Gone for
    ``idle_minutes``, their calculation is given back - and made again, with their values, when they return."""
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Özel Şerit")
        svc.settings.private_refresh = 60.0
        svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!J2", "value": "0,31"}])
        h = svc.header(u)
        eng = svc.books["tto"].engine
        calc = eng.user(u)
        evals = calc.evals
        pinned = [(si, rc) for si in range(eng.nsheets) for rc in eng.pins[si]]
        svc.et.call(lambda: eng.declare_inputs([c for c in pinned if c[1] not in eng.input_mask[c[0]]]))
        svc.bump()
        h = svc.header(u)
        evals = calc.evals
        svc.et.call(eng.invalidate, eng.input_mask[pinned[0][0]][pinned[0][1]] | eng.input_mask[pinned[-1][0]][pinned[-1][1]])
        svc.bump(market=True)                                                     # (a market move, as the market loop's)
        assert svc.header(u)["items"] == h["items"] and calc.evals == evals     # (kept: the market waits)
        svc.set_inputs(u, "tto", [{"ref": "OIS_MAIN!J2", "value": "0,30"}])  # their own change: at once
        mine = svc.header(u)
        assert calc.evals > evals
        w = login(svc, "Ortak Değiştiren")                                      # a shared input: at once
        svc.set_inputs(w, "tto", [{"ref": "Forward!W40", "value": "41,5"}])
        assert svc.header(u)["gen"] == svc.gen != mine["gen"]                    # (checked now, not kept)
        svc.et.call(eng.invalidate, eng.input_mask[pinned[0][0]][pinned[0][1]])
        svc.bump(market=True)
        assert svc.header(u)["gen"] != svc.gen                                  # (the market: kept a while)
        # gone a while: their calculation is given back; back, it is made again with their value
        svc._seen[u] = -1e9
        svc.settings.idle_minutes = 0.001
        assert svc.et.call(svc._sweep_idle) == [u] and u not in eng.users
        assert cell(svc, "OIS_MAIN!J2", u) == 0.30 and u in eng.users
    finally:
        svc.stop()


def test_the_header_and_every_page_are_made_ahead_at_the_lowest_priority(tmp_path):
    """After the start (the day's turn, a new meeting calendar) the header and every page are made ahead for
    everybody without inputs of their own - one page at a time at the lowest priority (a request goes first): the
    first trader of the morning gets them made."""
    import threading
    import time as _time
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Sabahın İlki")
        gate = threading.Event()
        svc.et.submit_at(svc.et.WRITE, gate.wait, 30)
        assert svc.warm() and not svc.warm()                     # (one round at a time)
        header = svc.header_future(u)
        gate.set()
        assert header.result(timeout=120)["items"] and svc.warmed == 0       # the request went first
        t0 = _time.time()
        while svc.warmed < 1 and _time.time() - t0 < 300:
            _time.sleep(0.2)
        assert svc.warmed == 1
        made = []
        real = svc._render
        svc._render = lambda *a: (made.append(a[3]), real(*a))[1]
        try:
            for v in svc.views:
                if v.get("admin"):
                    continue                             # (an administrators' page is kept per administrator: not made ahead)
                assert svc.view(u, v["id"])["panels"]
        finally:
            del svc._render
        assert made == []                                        # every page was made already
    finally:
        svc.stop()


def test_the_days_bloomberg_count_and_answers_are_kept_for_a_restart(tmp_path):
    """Live: every 30 s (and when the dashboard stops) the day's data points used and the reference answers got are
    kept in the database; a provider started the same day is given both (a restart does not spend the daily limit
    again).  Another day's are not given."""
    import datetime as _d
    svc = make_service(tmp_path)
    try:
        today = _d.date.today().isoformat()
        answers = [(("BDP", "TRY Curncy", "SETTLE_DT", ()), 46330.0, 1000.0)]

        class Stub(object):
            def __init__(self):
                self.got, self.carried = [], None

            def status(self):
                return {"hits_today": 1234}

            def answers(self, since=0.0):
                return [a for a in answers if a[2] > since]

            def preload(self, kept):
                self.got = list(kept)

            def carry_hits(self, n):
                self.carried = n

        svc.provider = Stub()
        svc._keep_bloomberg()
        assert svc.store.get("bbg.hits") == {"day": today, "hits": 1234}
        assert [(k, v) for k, v, _ in svc.store.bbg_answers(today)] == [(answers[0][0], 46330.0)]
        fresh = Stub()
        svc._kept_bloomberg(fresh)
        assert fresh.carried == 1234 and [(k, v) for k, v, _ in fresh.got] == [(answers[0][0], 46330.0)]
        svc.store.put("bbg.hits", {"day": "2000-01-01", "hits": 99})
        old = Stub()
        svc._kept_bloomberg(old)
        assert old.carried is None                               # another day's count: not carried
    finally:
        svc.stop()


def test_a_shared_change_reaches_another_tabs_panel_after_one_tab_was_refreshed(tmp_path):
    """Regression (browser test, the RET editor): a user with inputs of their own and the market throttle; a shared
    input changes (the RET curve), the open tab is refreshed, then another tab is opened and asked "since" the
    page was loaded - its RET table changed and must come, not "unchanged"."""
    svc = make_service(tmp_path)
    try:
        u, w = login(svc, "Sekmeler A"), login(svc, "Sekmeler B")
        svc.settings.private_refresh = 60.0
        svc.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}])            # (a calculation of her own)
        page = svc.view(u, "forward")
        tabs = {s["id"]: s["panels"] for s in page["sections"]}
        pinned = page["pinned"]
        svc.set_inputs(w, "tto", [{"ref": "Forward!W38", "value": "34,00"}])                # the RET curve: shared
        svc.view(u, "forward", since=page["gen"], panels=tabs["fwd"] + pinned, as_="p")
        ret = svc.view(u, "forward", since=page["gen"], panels=tabs["ret"] + pinned, as_="p")
        assert not ret.get("unchanged")
        b19 = next(p for p in ret["panels"] if p["id"] == "B19")["data"]
        assert b19["rows"][b19["r"].index(38)][b19["c"].index("W")]["t"] == "34,00%"
    finally:
        svc.stop()


def test_a_change_at_the_desk_reaches_a_page_of_ones_own_at_once(tmp_path):
    """A user with inputs of their own has the market's moves on their pages every few seconds (private_refresh) - but
    a change at the desk is no market move: a broker's quote said in the chat is on their DİBS RV at once, as on
    everybody's (it waited for the next change of anything before)."""
    import datetime as _dt
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Kendi Girdisiyle")
        svc.set_inputs(u, "tto", [{"ref": "Forward!F2", "value": "51"}])           # an input of their own
        assert u in svc._private_users
        first = svc.view(u, "dibs")
        said = (_dt.datetime.now() - _dt.timedelta(minutes=1)).strftime("%H:%M:%S")
        svc.broker_add(u, said + " 16/4/31 94.000/94.200", source="BGC")
        again = svc.view(u, "dibs", since=first["gen"])
        assert not again.get("unchanged")
        b3 = next(p for p in again["panels"] if p["id"] == "B3")["data"]
        row = next(r for r in b3["rows"] if r and r[0].get("t") == "TRT160431T35")
        assert any("BGC" in (c.get("t") or "") for c in row)
        # a market move alone is still held back for a few seconds (nothing at the desk changed)
        svc.bump(market=True)
        assert svc.view(u, "dibs", since=again["gen"]).get("unchanged")
    finally:
        svc.stop()
