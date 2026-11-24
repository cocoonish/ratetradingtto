"""The dashboard's own sheets (``tto/extras.py``): forward quotes from OIS + spread with separate bid / ask
spreads, gold forwards from the gold swap rate in place of ``BFXFORWARD``, O/N equivalents of the BIST swap quotes.

They are ordinary Excel formulas inside the workbook model, so every check below reads cells - and compares
them with an independent calculation or with what the workbook itself computes elsewhere."""
import pytest

from conftest import cell
from tto import aswfx, extras
from tto.books import formula_text
from tto.config import Settings
from tto.marketdata.base import bdp_key
from tto.marketdata.bloomberg import NA_NA, NO_BFX, NO_RT
from tto.marketdata.replay import ReplayProvider
from tto.service import Service
from tto.xl.engine import Clock
from tto.xl.errors import XlError
from tto.xl.model import COLS, parse_a1

GRAM = 31.1035
FWD_ROWS = range(extras.FWD_ROWS[0], extras.FWD_ROWS[0] + 6)          # 1M … 12M
MASA_CURVE_ROWS = {"MPC ima": 62, "S1": 63, "S2": 64, "S3": 65, "Ağırlıklı": 66, "Bootstrap": 67, "TLREF sabit": 68}


@pytest.fixture(scope="module")
def svc(module_service):
    return module_service


def put(svc, user, cells, book="tto"):
    res = svc.set_inputs(user, book, [{"ref": ref, "value": value} for ref, value in cells.items()])
    assert res["errors"] == [], res["errors"]
    return res


def linear(points, x, flat):
    """Piecewise linear through sorted (x, y) points; outside them the end value (``flat``) or the end
    segment extended (what Bloomberg's BInterpol does)."""
    if x <= points[0][0]:
        if flat:
            return points[0][1]
        (x0, y0), (x1, y1) = points[0], points[1]
    elif x >= points[-1][0]:
        if flat:
            return points[-1][1]
        (x0, y0), (x1, y1) = points[-2], points[-1]
    else:
        i = max(k for k, p in enumerate(points) if p[0] <= x)
        (x0, y0), (x1, y1) = points[i], points[i + 1]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


# ============================================================================== building blocks
def test_a_reused_workbook_formula_must_not_keep_references_to_its_old_sheet():
    text = "INDEX(Motor!$L$4:$L$84,MATCH($M$60,Motor!$C$4:$C$84,1))+LN(1+$M$60/365)-LOG10($M$60)"
    assert extras.transplant(text, {"$M$60": "$X5"}) == "INDEX(Motor!$L$4:$L$84,MATCH($X5,Motor!$C$4:$C$84,1))+LN(1+$X5/365)-LOG10($X5)"
    with pytest.raises(ValueError) as exc:                           # $I$60 would silently point at the new sheet
        extras.transplant("Motor!$L$4*$M$60+$I$60", {"$M$60": "$X5"})
    assert "$I$60" in str(exc.value)


def test_the_extra_sheets_are_ordinary_workbook_sheets(svc):
    """Formulas in the status bar, values in the explorer, last in the list of sheets - and absent from the
    model files, which stay a pure import of the Excel files."""
    from tto.books import load_books
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plain = load_books(os.path.join(root, "models"), extras=False)
    assert "EK_FWD" not in plain["tto"].model.sheet_index and "EK_XAU" not in plain["tto"].model.sheet_index
    assert formula_text(plain["tto"], *plain["tto"].cell("VIOP!M58")) == '=_xll.BFXFORWARD("XAUUSD",M46,"AskOutright")'
    assert plain["borsa"].model.sheet("bu").fml.get(parse_a1("O9")) is None
    info = svc.cell_info(None, "tto", "EK_FWD!J5")
    assert info["formula"] == '=IFERROR(IF($C5="","",$F5*(1+$M5/100*$C5/360)/(1+$O5/100*$C5/360)),"")'
    assert svc.cell_info(None, "tto", "EK_XAU!E27")["formula"] == '=IFERROR(IF(OR($C27="",$D27=""),"",$B$6*(1+$D27/100*$C27/360)),"")'
    assert svc.cell_info(None, "borsa", "bu!O9")["formula"] == '=IF(AND(ISNUMBER(H9),ISNUMBER(E9),N(E9)>0),360*((1+H9*E9/360)^(1/E9)-1),"")'
    grid = svc.grid(None, "tto", "EK_FWD", "A3:C5")["data"]
    assert [c["t"] for c in grid["rows"][0]] == ["Vade", "Valör", "Gün"] and grid["rows"][2][0]["t"] == "1M"
    # EK_FX: how each FX rate is read (by its tenor), the days to the tenor and the zero-coupon rate of the ASW sheet's
    # curve there - read off the sheet's own nodes (1M: D1 / L1, 2Y: D24 / L24)
    assert svc.cell_info(None, "asw", "EK_FX!J6")["formula"] == "=ASW!AC$65"
    assert svc.cell_info(None, "asw", "EK_FX!K6")["formula"] == "=IFERROR((EXP(-ASW!BT$65*365/$J6)-1)*100,NA())"
    assert svc.cell_info(None, "asw", "EK_FX!K13")["formula"] == "=IFERROR((EXP(-ASW!CC$65*365/$J13)-1)*100,NA())"
    assert svc.cell_info(None, "asw", "EK_FX!I10")["formula"] == ('=IF(ISNUMBER($D10),"FX swap ima: tek dönem, basit ACT/360",'
                                                                  '"fiyat yok: OIS kotası, sayfanın kuralıyla")')
    # 1Y: the one year XCCY (TRYSAQ1 - the desk, 18.11.2026), as 2Y on
    assert svc.cell_info(None, "asw", "EK_FX!I11")["formula"] == ('=IF(ISNUMBER($D11),"XCCY: yıllık par, ACT/360",'
                                                                  '"fiyat yok: OIS kotası, sayfanın kuralıyla")')
    assert svc.cell_info(None, "asw", "EK_FX!B11")["base"] == "TRYSAQ1"
    assert svc.cell_info(None, "asw", "EK_FX!I13")["formula"].startswith('=IF(ISNUMBER($D13),"XCCY: yıllık par, ACT/360",')
    # 18M is no quote (the desk, 18.11.2026): no ticker root to type, no Bloomberg call - computed off the offshore XCCY
    # curve by the dashboard, its XCCY par given to D12 in the calculation on the FX swap curve (#N/A in the sheet itself)
    b12 = svc.cell_info(None, "asw", "EK_FX!B12")
    assert (b12["base"], b12["input"]) == ("hesaplanan", None) and svc.cell_info(None, "asw", "EK_FX!B13")["input"] is not None
    assert [svc.cell_info(None, "asw", "EK_FX!%s12" % c)["formula"] for c in "DGH"] == ["=NA()"] * 3
    assert svc.cell_info(None, "asw", "EK_FX!C12")["formula"] == '=IF(ISNUMBER($D12),"hesaplanan (XCCY 1Y–2Y, Bootstrap / PPK basamak)","yok")'
    assert svc.cell_info(None, "asw", "EK_FX!I12")["formula"] == ('=IF(ISNUMBER($D12),"%s","fiyat yok: OIS kotası, sayfanın kuralıyla")'
                                                                  % aswfx.RULES[aswfx.CURVE])


def test_an_addition_that_no_longer_fits_its_workbook_is_left_out():
    """The additions build on particular cells.  When a workbook is imported again with another layout the
    dashboard must still start: an addition whose cells are not what it expects is left out and reported."""
    import os
    from tto.xl.model import Model
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sofr = Model.load(os.path.join(root, "models", "sofr.json.gz"))                 # not the workbook they were written for
    n = sofr.formula_count()
    problems = extras.apply("tto", sofr)
    assert [p.split(":")[0] for p in problems] == ["EK_TATIL", "FX valörleri", "OIS spot valörü", "EK_FWD", "EK_XAU", "EK_VIOP",
                                                   "EK_FWD vade faizleri", "EK_FWD EURTRY", "EK_KAYNAK",
                                                   "Bulk Bond satırları", "EK_BULK", "Forward puandan faize", "EK_PPK", "FRA ikinci bacak",
                                                   "DİBS RV canlı kota", "EK_DIBS", "EK_EVREN",
                                                   "Tüm Kâğıtlar canlı kota", "DİBS RV FRN", "DİBS RV ASW / DM'den fiyat",
                                                   "DİBS RV switch seviyesinden fiyat", "Manuel Tahvil ISIN", "EK_CARRY",
                                                   "Motor gün sayıları", "DV01 pozisyonu sıfır", "VİOP matris DV01'leri", "EK_IHALE",
                                                   "Boş başlayan girdiler", "Hesaplayıcıların piyasa varsayılanları",
                                                   "VİOP kontratları", "Tahvil carry fiyattan repo", "Implied move hareketten vol",
                                                   "Tek OIS spread'i", "EK_TARIH", "VİOP hedef fiyatı", "EK_VFRA"] + [
                                                   # (two-way: each calculator by itself, the VİOP target)
                                                   t.name for t in extras.TW_HUBS] + [
                                                   "EK_RET", "Eğri interpolasyonu"]
    assert sofr.formula_count() == n and not {"EK_FWD", "EK_XAU", "EK_VIOP", "EK_KAYNAK", "EK_BULK", "EK_DIBS", "EK_EVREN", "EK_CARRY",
                                              "EK_IHALE", "EK_TATIL", "EK_TARIH", "EK_VFRA", "EK_RET", "EK_PPK"} & set(sofr.sheet_index)
    assert extras.apply("asw", Model.load(os.path.join(root, "models", "sofr.json.gz")))[0].startswith("EK_FX:")
    # the ASW sheet's curve laid out otherwise: EK_FX reads its node days and ln discount factors by their place
    asw = Model.load(os.path.join(root, "models", "asw.json.gz"))
    asw.sheet("ASW").consts[parse_a1("BS64")] = "L1"
    assert extras.apply("asw", asw) == ["EK_FX: ASW!BS64 beklenen başlık değil (L0 yok)"] and "EK_FX" not in asw.sheet_index
    # the TRY workbook with one gold forward typed over by hand: the gold tables stay as they are in the file
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    viop = tto.sheet("VIOP")
    del viop.fml[parse_a1("M58")]
    viop.consts[parse_a1("M58")] = 3971.85
    formulas = dict(viop.fml)
    assert extras.apply("tto", tto) == ["EK_XAU: VIOP!M58 bir formül değil"]
    # (rows 107-109: the matrix's DV01s, rewritten by their own addition whatever the gold tables are; rows 1 / 45 / 60:
    # the futures tickers, which roll by themselves - the gold ones too; rows 330-338: the target table, whose FRA takes
    # the curve chosen per row)
    dv01_rows = {r for r in (107, 108, 109, 1, 45, 60) + tuple(range(330, 339))}
    keep = lambda fml: {rc: t for rc, t in fml.items() if rc // COLS not in dv01_rows}          # noqa: E731
    assert "EK_FWD" in tto.sheet_index and "EK_XAU" not in tto.sheet_index and keep(viop.fml) == keep(formulas)
    assert "EK_VIOP" in tto.sheet_index                                             # the history charts do not need the gold tables
    # the VİOP history block laid out differently: its charts are left out, the rest stays
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    viop = tto.sheet("VIOP")
    del viop.fml[parse_a1("AJ380")]
    assert extras.apply("tto", tto) == ["EK_VIOP: VIOP!AJ380 bir formül değil"]
    assert "EK_XAU" in tto.sheet_index and "EK_VIOP" not in tto.sheet_index
    # a discount factor that depends on another cell of the desk sheet cannot be moved to the matrix
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    b = extras.SheetBuilder(tto, "MASA")
    b.patch("I67", "=" + extras.formula_of(tto, "MASA", "I67") + "*$I$60/$I$60")
    assert extras.apply("tto", tto)[0].startswith("EK_FWD: unqualified references left")
    assert "EK_FWD" not in tto.sheet_index and "EK_XAU" in tto.sheet_index
    # a bid of DİBS RV written another way: what tells a live quote is left out (Tüm Kâğıtlar's part with it), the pages stay
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    extras.SheetBuilder(tto, "DİBS RV").patch("K20", '=IF($A20="","",FD20)')
    assert extras.apply("tto", tto) == ["DİBS RV canlı kota: DİBS RV!K20 beklenen formül değil (IF(N(FD20)>0,FD20, yok)",
                                        "Tüm Kâğıtlar canlı kota: DİBS RV!XR5 bir formül değil"]
    assert "EK_DIBS" in tto.sheet_index and "EK_EVREN" in tto.sheet_index
    assert extras.formula_of(tto, "DİBS RV", "K5") == 'IF($A5="","",IF(N(FD5)>0,FD5,""))'
    assert extras.formula_of(tto, "EK_EVREN", "I30") == 'IFERROR(IF(N(V30)>0,V30,""),"")'
    borsa = Model.load(os.path.join(root, "models", "borsa.json.gz"))
    borsa.sheet("bu").consts[parse_a1("H8")] = "Bid"
    assert extras.apply("borsa", borsa) == ["Borsa O/N: bu!H8 başlığı 'BID %' değil"]
    assert borsa.sheet("bu").fml.get(parse_a1("O9")) is None


def test_tables_of_a_left_out_addition_are_not_shown(svc):
    assert all(b["left_out"] == [] for b in svc.status()["books"].values())        # with the real files everything fits
    view = svc.view_index["forward"]
    saved = [dict(p) for p in view["panels"]]
    try:
        for p in view["panels"]:
            if p.get("sheet") == "EK_FWD":
                p["sheet"] = "EK_YOK"                                               # as if the sheet had not been built
        with svc._render_lock:
            svc._renders.clear()                                                    # (the pages kept: made again)
        ids = [p["id"] for p in svc.view(None, "forward", True)["panels"]]
        assert "B14" in ids and not any(i.startswith("EKF") or i.startswith("FR") for i in ids)
        assert all("error" not in p for p in svc.view(None, "forward", True)["panels"])
    finally:
        view["panels"][:] = saved
        with svc._render_lock:
            svc._renders.clear()                                                    # (the pages kept: made again)
    assert "EKF1" in [p["id"] for p in svc.view(None, "forward")["panels"]]


# ============================================================================== forward quotes: OIS + spread
def test_the_matrix_starts_from_the_desk_sheets_spread_and_dates(svc):
    spread = cell(svc, "MASA!I60")
    assert spread == -150.0
    assert cell(svc, "EK_FWD!B2") == "MPC ima"
    assert cell(svc, "EK_FWD!D4") == spread and cell(svc, "EK_FWD!E4") == spread
    assert cell(svc, "EK_FWD!F4") == cell(svc, "VIOP!L99") and cell(svc, "EK_FWD!G4") == cell(svc, "VIOP!L100")
    assert [cell(svc, "EK_FWD!A%d" % r) for r in FWD_ROWS] == ["1M", "2M", "3M", "6M", "9M", "12M"]
    for i, r in enumerate(FWD_ROWS):                 # the dates of the desk sheet's forward pricing table
        assert cell(svc, "EK_FWD!B%d" % r) == cell(svc, "MASA!P%d" % (94 + i))
        assert cell(svc, "EK_FWD!C%d" % r) == cell(svc, "MASA!Q%d" % (94 + i))
        assert cell(svc, "EK_FWD!D%d" % r) == spread and cell(svc, "EK_FWD!E%d" % r) == spread


@pytest.mark.parametrize("curve", sorted(MASA_CURVE_ROWS))
def test_every_curve_gives_the_rate_of_the_desk_sheets_own_block(svc, curve):
    """MASA "Tarih arası forward" prices one date with one spread; for the same date (3M) and spread the
    matrix must show the same TRY rate, whichever OIS curve is chosen."""
    u = svc.login("Fwd " + curve)["user"]
    put(svc, u, {"EK_FWD!B2": curve})
    row = FWD_ROWS[2]
    assert cell(svc, "EK_FWD!B%d" % row, u) == cell(svc, "MASA!E60", u)             # both are spot + 3 months
    desk = cell(svc, "MASA!R%d" % MASA_CURVE_ROWS[curve], u)
    assert isinstance(desk, float) and 20 < desk < 60
    assert cell(svc, "EK_FWD!M%d" % row, u) == pytest.approx(desk, rel=1e-12)
    assert cell(svc, "EK_FWD!N%d" % row, u) == pytest.approx(desk, rel=1e-12)
    assert cell(svc, "EK_FWD!L%d" % row, u) == pytest.approx(desk + 1.5, rel=1e-12)   # the OIS rate itself


def test_an_unknown_curve_name_is_refused_by_the_formula(svc):
    u = svc.login("Fwd yanlış")["user"]
    put(svc, u, {"EK_FWD!B2": "olmayan"})
    v = cell(svc, "EK_FWD!L%d" % FWD_ROWS[0], u)
    assert type(v) is XlError and v.code == "#N/A"
    assert cell(svc, "EK_FWD!H%d" % FWD_ROWS[0], u) == ""                  # no quote rather than a wrong one


def test_bid_and_ask_are_priced_with_their_own_spread(svc):
    u = svc.login("Fwd spread")["user"]
    g = extras.FWD_ALL
    put(svc, u, {"EK_FWD!D%d" % g: -200, "EK_FWD!E%d" % g: "-100"})
    spot_bid, spot_ask = cell(svc, "VIOP!L99", u), cell(svc, "VIOP!L100", u)
    assert spot_bid < spot_ask
    for r in FWD_ROWS:
        days, ois, usd = (cell(svc, "EK_FWD!%s%d" % (c, r), u) for c in "CLO")
        try_bid, try_ask = ois - 2.0, ois - 1.0
        assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(try_bid, rel=1e-13)
        assert cell(svc, "EK_FWD!N%d" % r, u) == pytest.approx(try_ask, rel=1e-13)
        fwd_bid = spot_bid * (1 + try_bid / 100 * days / 360) / (1 + usd / 100 * days / 360)
        fwd_ask = spot_ask * (1 + try_ask / 100 * days / 360) / (1 + usd / 100 * days / 360)
        assert cell(svc, "EK_FWD!F%d" % r, u) == spot_bid and cell(svc, "EK_FWD!G%d" % r, u) == spot_ask
        assert cell(svc, "EK_FWD!J%d" % r, u) == pytest.approx(fwd_bid, rel=1e-13)
        assert cell(svc, "EK_FWD!K%d" % r, u) == pytest.approx(fwd_ask, rel=1e-13)
        assert cell(svc, "EK_FWD!H%d" % r, u) == pytest.approx((fwd_bid - spot_bid) * 10000, rel=1e-9)
        assert cell(svc, "EK_FWD!I%d" % r, u) == pytest.approx((fwd_ask - spot_ask) * 10000, rel=1e-9)
        assert cell(svc, "EK_FWD!P%d" % r, u) == pytest.approx((fwd_bid - spot_bid) * 10000 / days, rel=1e-9)
        assert cell(svc, "EK_FWD!H%d" % r, u) < cell(svc, "EK_FWD!I%d" % r, u)        # bid points below ask points
    # one date can have its own spread; blanking it returns to the general one
    r = FWD_ROWS[2]
    ois = cell(svc, "EK_FWD!L%d" % r, u)
    put(svc, u, {"EK_FWD!D%d" % r: -50})
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(ois - 0.5, rel=1e-13)
    assert cell(svc, "EK_FWD!M%d" % (r + 1), u) == pytest.approx(cell(svc, "EK_FWD!L%d" % (r + 1), u) - 2.0, rel=1e-13)
    put(svc, u, {"EK_FWD!D%d" % r: ""})
    assert cell(svc, "EK_FWD!D%d" % r, u) == -200.0
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(ois - 2.0, rel=1e-13)
    # nobody else's matrix moved
    assert cell(svc, "EK_FWD!D%d" % g) == -150.0 and cell(svc, "EK_FWD!M%d" % r) == pytest.approx(ois - 1.5, rel=1e-13)


def test_usd_and_ret_columns_are_the_forward_pricing_tables(svc):
    """Same value dates as MASA "Forward fiyatlama": USD %, RET bid / ask % and the RET points must agree."""
    for i, r in enumerate(FWD_ROWS):
        m = 94 + i
        assert cell(svc, "EK_FWD!O%d" % r) == pytest.approx(cell(svc, "MASA!R%d" % m), rel=1e-13)
        assert cell(svc, "EK_FWD!R%d" % r) == pytest.approx(cell(svc, "MASA!U%d" % m), rel=1e-13)
        assert cell(svc, "EK_FWD!S%d" % r) == pytest.approx(cell(svc, "MASA!V%d" % m), rel=1e-13)
        # "Bid − RET" = matrix points − points at the RET bid rate, i.e. matrix points − MASA's "Puan bid"
        assert cell(svc, "EK_FWD!H%d" % r) - cell(svc, "EK_FWD!T%d" % r) == pytest.approx(cell(svc, "MASA!Z%d" % m), rel=1e-9)
        assert cell(svc, "EK_FWD!I%d" % r) - cell(svc, "EK_FWD!U%d" % r) == pytest.approx(cell(svc, "MASA!AA%d" % m), rel=1e-9)


def test_a_free_date_is_priced_like_the_desk_sheet_prices_it(svc):
    u = svc.login("Fwd tarih")["user"]
    r = extras.FWD_ROWS[0] + 6                                    # the first free row
    assert cell(svc, "EK_FWD!C%d" % r, u) == "" and cell(svc, "EK_FWD!H%d" % r, u) == ""
    put(svc, u, {"EK_FWD!B%d" % r: "15.01.2027", "MASA!E60": "15.01.2027"})   # the same end date on the desk sheet
    days = cell(svc, "EK_FWD!C%d" % r, u)
    assert days == cell(svc, "MASA!M60", u) == 72.0
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(cell(svc, "MASA!R62", u), rel=1e-12)
    # MASA!T62 carries the mid spot with the same two rates: the carry factor must be identical
    factor = cell(svc, "MASA!T62", u) / cell(svc, "MASA!Q60", u)
    assert cell(svc, "EK_FWD!J%d" % r, u) / cell(svc, "EK_FWD!F%d" % r, u) == pytest.approx(factor, rel=1e-13)
    assert cell(svc, "EK_FWD!K%d" % r, u) / cell(svc, "EK_FWD!G%d" % r, u) == pytest.approx(factor, rel=1e-13)


def test_points_typed_by_hand_give_back_their_spread(svc):
    """The way back: the points of a matrix priced at −175 / −60 bp, typed into the lower table, must read
    −175 / −60 bp over the same curve."""
    u = svc.login("Fwd puan")["user"]
    g, back = extras.FWD_ALL, extras.FWD_BACK
    put(svc, u, {"EK_FWD!D%d" % g: -175, "EK_FWD!E%d" % g: -60, "EK_FWD!B2": "Bootstrap"})
    typed = {}
    for r in FWD_ROWS:
        typed["EK_FWD!D%d" % (r + back)] = cell(svc, "EK_FWD!H%d" % r, u)
        typed["EK_FWD!E%d" % (r + back)] = cell(svc, "EK_FWD!I%d" % r, u)
    put(svc, u, typed)
    for r in FWD_ROWS:
        k = r + back
        assert cell(svc, "EK_FWD!A%d" % k, u) == cell(svc, "EK_FWD!A%d" % r, u)
        assert cell(svc, "EK_FWD!B%d" % k, u) == cell(svc, "EK_FWD!B%d" % r, u)
        assert cell(svc, "EK_FWD!F%d" % k, u) == pytest.approx(cell(svc, "EK_FWD!J%d" % r, u), rel=1e-13)
        assert cell(svc, "EK_FWD!H%d" % k, u) == pytest.approx(cell(svc, "EK_FWD!M%d" % r, u), rel=1e-10)
        assert cell(svc, "EK_FWD!I%d" % k, u) == pytest.approx(cell(svc, "EK_FWD!N%d" % r, u), rel=1e-10)
        assert cell(svc, "EK_FWD!J%d" % k, u) == cell(svc, "EK_FWD!L%d" % r, u)
        assert cell(svc, "EK_FWD!K%d" % k, u) == pytest.approx(-175.0, abs=1e-7)
        assert cell(svc, "EK_FWD!L%d" % k, u) == pytest.approx(-60.0, abs=1e-7)
    # a row without points stays empty
    put(svc, u, {"EK_FWD!D%d" % (FWD_ROWS[0] + back): ""})
    assert cell(svc, "EK_FWD!K%d" % (FWD_ROWS[0] + back), u) == ""


def test_matrix_panels_are_on_the_forward_page_with_their_inputs(svc):
    """The forward quote matrices live on the Forward page's "Kotasyon" tab (they were on the desk page, which keeps a
    summary of the USDTRY one)."""
    page = svc.view(None, "forward")
    panels = {p["id"]: p for p in page["panels"]}
    ids = [p["id"] for p in page["panels"]]
    assert ids.index("EKF2") == ids.index("EKF1") + 1 and not any(i.startswith("EKF") for i in (p["id"] for p in svc.view(None, "masa", True)["panels"]))
    assert panels["EKF1"]["title"].startswith("FORWARD KOTASYON") and panels["EKF2"]["title"].startswith("PUAN → OIS SPREAD")
    rows = panels["EKF1"]["data"]["rows"]
    head = [c.get("t") for c in rows[1]]
    assert head[:11] == ["Vade", "Valör", "Gün", "Spread bid", "Spread ask", "Spot bid", "Spot ask", "Puan bid", "Puan ask",
                         "Fwd bid", "Fwd ask"]
    inputs = [(c.get("i"), c.get("o")) for row in rows for c in row if c.get("i")]
    assert len(inputs) == 1 + 1 + 2 + 10 + 20 and all(i == "u" for i, _ in inputs)      # curve, spread source, general, dates, per date
    assert inputs[0][1] == list(extras.FWD_CURVES)                                       # the curve is a drop-down
    assert "EKF3" not in panels and "EKF3" in {p["id"] for p in svc.view(None, "forward", True)["panels"]}


# ============================================================================== forward quotes: EURTRY, OIS + spread
EUR_ALL = extras.FWD_EUR_ALL
EUR_ROWS = range(extras.FWD_EUR_ROWS[0], extras.FWD_EUR_ROWS[0] + 6)        # 1M … 12M
EUR_FREE = extras.FWD_EUR_ROWS[0] + 6


def test_the_eurtry_matrix_starts_from_the_usdtry_ones_curve_and_spreads(svc):
    g = EUR_ALL
    assert cell(svc, "EK_FWD!B%d" % (g - 2)) == cell(svc, "EK_FWD!B2") == "MPC ima"
    assert [cell(svc, "EK_FWD!%s%d" % (c, g)) for c in "DE"] == [cell(svc, "EK_FWD!D4"), cell(svc, "EK_FWD!E4")] == [-150.0, -150.0]
    # the EURTRY spot: Bloomberg's bid / ask (the file has none recorded: the mid of the Forward sheet)
    for c, src in (("F", "F198"), ("G", "G198")):
        bbg = cell(svc, "Forward!" + src)
        assert cell(svc, "EK_FWD!%s%d" % (c, g)) == (bbg if isinstance(bbg, float) else cell(svc, "Forward!G2"))
    assert [cell(svc, "EK_FWD!A%d" % r) for r in EUR_ROWS] == ["1M", "2M", "3M", "6M", "9M", "12M"]
    spot_date = cell(svc, "EK_FWD!G%d" % (g - 2))
    assert spot_date == cell(svc, "Forward!D2") - cell(svc, "Forward!AA27")          # the EURTRY spot date
    for r in EUR_ROWS:
        days, ois, bid, ask, eur = (cell(svc, "EK_FWD!%s%d" % (c, r)) for c in "CLMNO")
        assert days == cell(svc, "EK_FWD!B%d" % r) - spot_date
        assert bid == pytest.approx(ois - 1.5, rel=1e-13) and ask == pytest.approx(ois - 1.5, rel=1e-13)
        sb, sa = cell(svc, "EK_FWD!F%d" % r), cell(svc, "EK_FWD!G%d" % r)
        fwd_bid = sb * (1 + bid / 100 * days / 360) / (1 + eur / 100 * days / 360)
        fwd_ask = sa * (1 + ask / 100 * days / 360) / (1 + eur / 100 * days / 360)
        assert cell(svc, "EK_FWD!J%d" % r) == pytest.approx(fwd_bid, rel=1e-13)
        assert cell(svc, "EK_FWD!K%d" % r) == pytest.approx(fwd_ask, rel=1e-13)
        assert cell(svc, "EK_FWD!H%d" % r) == pytest.approx((fwd_bid - sb) * 10000, rel=1e-9)
        assert cell(svc, "EK_FWD!P%d" % r) == pytest.approx((fwd_bid - sb) * 10000 / days, rel=1e-9)


def test_the_eurtry_matrix_reads_the_ois_and_eur_rates_of_the_desk_sheet(svc):
    """For the same date the TRY OIS rate is the USDTRY matrix's (one TRY curve); the EUR rate is the one the desk
    sheet's own forward table takes for EURTRY (MASA!AY), at days from the EURTRY spot date."""
    u = svc.login("EUR aynı tarih")["user"]
    put(svc, u, {"EK_FWD!B11": cell(svc, "MASA!P96"), "EK_FWD!B%d" % EUR_FREE: cell(svc, "MASA!P96")})       # spot + 3M
    assert cell(svc, "EK_FWD!L%d" % EUR_FREE, u) == pytest.approx(cell(svc, "EK_FWD!L11", u), rel=1e-13)
    assert cell(svc, "EK_FWD!C%d" % EUR_FREE, u) == cell(svc, "MASA!AZ96", u)                          # EURTRY days
    assert cell(svc, "EK_FWD!O%d" % EUR_FREE, u) == pytest.approx(cell(svc, "MASA!AY96", u), rel=1e-13)  # EUR %
    assert cell(svc, "EK_FWD!R%d" % EUR_FREE, u) == pytest.approx(cell(svc, "EK_FWD!R11", u), rel=1e-13)  # RET at TRY days
    # another curve for EURTRY only
    put(svc, u, {"EK_FWD!B%d" % (EUR_ALL - 2): "Bootstrap"})
    assert cell(svc, "EK_FWD!B2", u) == "MPC ima"
    assert cell(svc, "EK_FWD!L%d" % EUR_FREE, u) == pytest.approx(cell(svc, "EK_FWD!AJ%d" % EUR_FREE, u), rel=1e-13)
    assert cell(svc, "EK_FWD!L%d" % EUR_FREE, u) != pytest.approx(cell(svc, "EK_FWD!L11", u), rel=1e-6)


def test_eurtry_spreads_follow_the_usdtry_ones_until_set_apart(svc):
    u = svc.login("EUR spread")["user"]
    r = EUR_ROWS[2]
    put(svc, u, {"EK_FWD!D4": -200, "EK_FWD!E4": -100})                  # the USDTRY matrix's general spreads ...
    ois = cell(svc, "EK_FWD!L%d" % r, u)
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(ois - 2.0) and cell(svc, "EK_FWD!N%d" % r, u) == pytest.approx(ois - 1.0)
    put(svc, u, {"EK_FWD!D%d" % EUR_ALL: -120, "EK_FWD!E%d" % EUR_ALL: -80})    # ... until EURTRY has its own
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(ois - 1.2) and cell(svc, "EK_FWD!N%d" % r, u) == pytest.approx(ois - 0.8)
    assert cell(svc, "EK_FWD!D4", u) == -200.0 and cell(svc, "EK_FWD!M7", u) == pytest.approx(cell(svc, "EK_FWD!L7", u) - 2.0)
    put(svc, u, {"EK_FWD!E%d" % r: -25})                                   # one date with its own ask spread
    assert cell(svc, "EK_FWD!N%d" % r, u) == pytest.approx(ois - 0.25) and cell(svc, "EK_FWD!N%d" % (r + 1), u) == pytest.approx(
        cell(svc, "EK_FWD!L%d" % (r + 1), u) - 0.8)
    put(svc, u, {"EK_FWD!D%d" % EUR_ALL: ""})
    assert cell(svc, "EK_FWD!D%d" % EUR_ALL, u) == -200.0                  # blanked: the USDTRY one again
    # a spot of one's own
    put(svc, u, {"EK_FWD!F%d" % EUR_ALL: "56,10", "EK_FWD!G%d" % EUR_ALL: "56,14"})
    assert cell(svc, "EK_FWD!F%d" % r, u) == 56.10 and cell(svc, "EK_FWD!G%d" % r, u) == 56.14
    assert cell(svc, "EK_FWD!H%d" % r, u) == pytest.approx((cell(svc, "EK_FWD!J%d" % r, u) - 56.10) * 10000)


def test_eurtry_points_typed_by_hand_give_their_spread_over_ois(svc):
    u = svc.login("EUR puan")["user"]
    put(svc, u, {"EK_FWD!D%d" % EUR_ALL: -175, "EK_FWD!E%d" % EUR_ALL: -60})
    back = extras.FWD_BACK
    typed = {}
    for r in EUR_ROWS:
        typed["EK_FWD!D%d" % (r + back)] = cell(svc, "EK_FWD!H%d" % r, u)
        typed["EK_FWD!E%d" % (r + back)] = cell(svc, "EK_FWD!I%d" % r, u)
    put(svc, u, typed)
    for r in EUR_ROWS:
        k = r + back
        assert cell(svc, "EK_FWD!A%d" % k, u) == cell(svc, "EK_FWD!A%d" % r, u) and cell(svc, "EK_FWD!B%d" % k, u) == cell(svc, "EK_FWD!B%d" % r, u)
        assert cell(svc, "EK_FWD!F%d" % k, u) == pytest.approx(cell(svc, "EK_FWD!J%d" % r, u), rel=1e-13)
        assert cell(svc, "EK_FWD!H%d" % k, u) == pytest.approx(cell(svc, "EK_FWD!M%d" % r, u), rel=1e-10)
        assert cell(svc, "EK_FWD!K%d" % k, u) == pytest.approx(-175.0, abs=1e-7)
        assert cell(svc, "EK_FWD!L%d" % k, u) == pytest.approx(-60.0, abs=1e-7)
    put(svc, u, {"EK_FWD!D%d" % (EUR_ROWS[0] + back): ""})
    assert cell(svc, "EK_FWD!K%d" % (EUR_ROWS[0] + back), u) == ""


# ============================================================================== the way back from a rate: FAİZ → SPREAD
def _rate_back_check(svc, u, rows, off):
    """Rates typed into the FAİZ → SPREAD table of a matrix (``rows``, the table ``off`` rows below): its spread over
    the matrix's OIS and the matrix's own formulas with the typed rate; the spread found, typed into the matrix, gives
    the same points and forward (1e-9)."""
    typed = {}
    for i, r in enumerate(rows):
        ois = cell(svc, "EK_FWD!L%d" % r, u)
        typed["EK_FWD!D%d" % (r + off)] = round(ois - 1.234 - 0.1 * i, 4)
        typed["EK_FWD!E%d" % (r + off)] = round(ois - 0.567 + 0.05 * i, 4)
    put(svc, u, typed)
    found = {}
    for r in rows:
        k = r + off
        days, ois, sb, sa, maj, retb, reta = (cell(svc, "EK_FWD!%s%d" % (c, r), u) for c in "CLFGORS")
        tb, ta = cell(svc, "EK_FWD!D%d" % k, u), cell(svc, "EK_FWD!E%d" % k, u)
        assert [cell(svc, "EK_FWD!%s%d" % (c, k), u) for c in "ABC"] == [cell(svc, "EK_FWD!%s%d" % (c, r), u) for c in "ABC"]
        assert cell(svc, "EK_FWD!F%d" % k, u) == ois
        assert cell(svc, "EK_FWD!G%d" % k, u) == pytest.approx((tb - ois) * 100, abs=1e-9)
        assert cell(svc, "EK_FWD!H%d" % k, u) == pytest.approx((ta - ois) * 100, abs=1e-9)
        fb = sb * (1 + tb / 100 * days / 360) / (1 + maj / 100 * days / 360)
        fa = sa * (1 + ta / 100 * days / 360) / (1 + maj / 100 * days / 360)
        assert cell(svc, "EK_FWD!K%d" % k, u) == pytest.approx(fb, rel=1e-13) and cell(svc, "EK_FWD!L%d" % k, u) == pytest.approx(fa, rel=1e-13)
        assert cell(svc, "EK_FWD!I%d" % k, u) == pytest.approx((fb - sb) * 10000, abs=1e-8)
        assert cell(svc, "EK_FWD!J%d" % k, u) == pytest.approx((fa - sa) * 10000, abs=1e-8)
        assert cell(svc, "EK_FWD!M%d" % k, u) == pytest.approx((fb - sb) * 10000 / days, abs=1e-9)
        assert [cell(svc, "EK_FWD!%s%d" % (c, k), u) for c in "OP"] == [retb, reta]
        ret_pts = (sb * (1 + retb / 100 * days / 360) / (1 + maj / 100 * days / 360) - sb) * 10000
        assert cell(svc, "EK_FWD!Q%d" % k, u) == pytest.approx((fb - sb) * 10000 - ret_pts, abs=1e-8)
        found["EK_FWD!D%d" % r] = cell(svc, "EK_FWD!G%d" % k, u)
        found["EK_FWD!E%d" % r] = cell(svc, "EK_FWD!H%d" % k, u)
    # the spreads found, typed into the matrix: the same points and forwards
    put(svc, u, found)
    for r in rows:
        k = r + off
        for m, t in (("H", "I"), ("I", "J"), ("J", "K"), ("K", "L"), ("M", "D"), ("N", "E")):
            assert cell(svc, "EK_FWD!%s%d" % (m, r), u) == pytest.approx(cell(svc, "EK_FWD!%s%d" % (t, k), u), abs=1e-9), (m, r)
    # a row without a rate stays empty
    put(svc, u, {"EK_FWD!D%d" % (rows[0] + off): ""})
    assert [cell(svc, "EK_FWD!%s%d" % (c, rows[0] + off), u) for c in "GIKMQ"] == ["", "", "", "", ""]


def test_a_rate_typed_gives_its_spread_and_the_matrix_the_same_points(svc):
    """(the desk, 23.11.2026: "Spread ile forward kotasyonlarını bulduğumuz yere faizi girdiğimde de spreadi ve
    rate'leri vermesi lazım") USDTRY: a TRY bid / ask % typed for each of the matrix's dates -> its spread over OIS, the
    points, the forward, P/gün and the RET comparison, the matrix's own formulas; typed back as the matrix's spreads,
    the same points."""
    u = svc.login("Fwd faiz")["user"]
    put(svc, u, {"EK_FWD!B2": "S1"})
    _rate_back_check(svc, u, FWD_ROWS, extras.FWD_RATE)
    assert FWD_ROWS[0] + extras.FWD_RATE == 133


def test_an_eurtry_rate_typed_gives_its_spread_on_its_own_day_count(svc):
    """EURTRY: the same, on the EURTRY matrix - its spot, the EUR rate and the days from the EURTRY spot date."""
    u = svc.login("EUR faiz")["user"]
    _rate_back_check(svc, u, EUR_ROWS, extras.FWD_EUR_RATE)
    r = EUR_ROWS[2]
    assert cell(svc, "EK_FWD!C%d" % (r + extras.FWD_EUR_RATE), u) == cell(svc, "EK_FWD!B%d" % r, u) - cell(svc, "EK_FWD!G%d" % (EUR_ALL - 2), u)
    assert EUR_ROWS[0] + extras.FWD_EUR_RATE == 147


def test_the_new_inputs_stand_where_no_input_ever_stood(svc):
    """Users' typed values are kept by cell: the rate tables' and the bulk outrights' inputs are on cells no layout ever
    had an input on (none retired, none another table's)."""
    from tto.views import load_views
    view = next(v for v in load_views() if v["id"] == "forward")
    new = {"EK_FWD!D133:E142", "EK_FWD!D147:E156", "EK_BULK!R5:R104", "EK_BULK!T5:T104", "I181", "O182", "R200:R214"}
    have = [i["range"] for i in view["inputs"] if "range" in i]
    assert new <= set(have)

    def cells(rng):
        sh, a = rng.split("!") if "!" in rng else ("Forward", rng)
        a1, _, a2 = a.partition(":")
        (r1, c1), (r2, c2) = divmod(parse_a1(a1), COLS), divmod(parse_a1(a2 or a1), COLS)
        return {(sh, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}

    mine = set().union(*(cells(x) for x in new))
    others = set().union(*(cells(x) for x in have if x not in new))
    retired = set().union(*(cells(x) for x in extras.RETIRED_INPUTS["tto"]))
    assert not mine & others and not mine & retired


def test_a_bulk_rows_outright_gives_back_its_rate(svc):
    """(the desk, 23.11.2026: "Toplu fiyatlama kısmında da forward rate'lerden faizi de toplu olarak bulabilmeliyim") The
    bulk table's own USDTRY / EURTRY forwards (N / P) pasted into the new columns read back the TRY rate they were priced
    with - the manual one (L) or, without it, RET mid (G): the same spot, USD / EUR rate and days."""
    u = svc.login("Toplu ters")["user"]
    first = extras.BULK_FIRST
    put(svc, u, {"EK_BULK!B%d" % first: "15.01.2027", "EK_BULK!B%d" % (first + 1): "15.04.2027", "EK_BULK!L%d" % first: "41,25"})
    rows = (first, first + 1)
    pasted = {}
    for r in rows:
        pasted["EK_BULK!R%d" % r] = cell(svc, "EK_BULK!N%d" % r, u)
        pasted["EK_BULK!T%d" % r] = cell(svc, "EK_BULK!P%d" % r, u)
    put(svc, u, pasted)
    want = {first: 41.25, first + 1: cell(svc, "EK_BULK!G%d" % (first + 1), u)}
    for r in rows:
        assert isinstance(want[r], float)
        assert cell(svc, "EK_BULK!S%d" % r, u) == pytest.approx(want[r], abs=1e-9)
        assert cell(svc, "EK_BULK!U%d" % r, u) == pytest.approx(want[r], abs=1e-9)
    # the EURTRY one on its own days: a different day count from the USDTRY one's for the same date
    assert cell(svc, "EK_BULK!C%d" % first, u) != cell(svc, "EK_BULK!B%d" % first, u) - cell(svc, "Forward!K2", u)
    # an outright of one's own: its rate; a row without an outright stays empty
    put(svc, u, {"EK_BULK!R%d" % first: cell(svc, "EK_BULK!N%d" % first, u) + 0.05})
    assert cell(svc, "EK_BULK!S%d" % first, u) > 41.25
    put(svc, u, {"EK_BULK!T%d" % first: ""})
    assert cell(svc, "EK_BULK!U%d" % first, u) == ""
    view = next(p for p in svc.view(u, "forward")["panels"] if p["id"] == "BK1")
    assert view["range"] == "B1:Y106" and view["grow"]["key"] == "B"           # (to Y: "İşleme al"'s inputs, test_toplu_islem)


def test_fs_points_typed_give_back_the_manual_rate(svc):
    """(proposal #2, approved: "1-2-3-4 yap") FORWARD STARTING SWAP: the "Manuel" row's own FS points typed back give its
    TRY fwd-fwd % - USDTRY and EURTRY, on the same near / far and USD / EUR fwd-fwd % -, with its bp over OIS mid,
    offshore mid and RET mid beside it."""
    u = svc.login("FS ters")["user"]
    put(svc, u, {"Forward!C167": "08.12.2026", "Forward!C168": "08.03.2027", "Forward!C169": "40,5"})
    assert cell(svc, "Forward!F169", u) == "OK"
    for usd in (None, "4,1"):                               # the USD fwd-fwd % of the curve, then one typed
        put(svc, u, {"Forward!C170": usd or ""})
        pts, pts_eur = cell(svc, "Forward!I179", u), cell(svc, "Forward!O179", u)
        assert isinstance(pts, float) and isinstance(pts_eur, float)
        put(svc, u, {"Forward!I181": pts, "Forward!O182": pts_eur})
        for r in (extras.FS_BACK_USD, extras.FS_BACK_EUR):
            e = cell(svc, "Forward!E%d" % r, u)
            assert e == pytest.approx(40.5, abs=1e-9), (usd, r)
            for col, ref, _ in extras.FS_BACK_BP:
                assert cell(svc, "Forward!%s%d" % (col, r), u) == pytest.approx((e - cell(svc, "Forward!" + ref, u)) * 100, abs=1e-9)
            assert cell(svc, "Forward!D%d" % r, u) == pytest.approx(cell(svc, "Forward!D179", u), abs=1e-9)   # (the far TRY %)
        assert cell(svc, "Forward!H181", u) == pytest.approx(cell(svc, "Forward!H179", u), rel=1e-12)
        assert cell(svc, "Forward!N182", u) == pytest.approx(cell(svc, "Forward!N179", u), rel=1e-12)
        assert cell(svc, "Forward!F181", u) == cell(svc, "Forward!F179", u) and cell(svc, "Forward!J181", u) == pytest.approx(cell(svc, "Forward!J179", u))
    # points of one's own: more points, a higher TRY rate; none: empty
    put(svc, u, {"Forward!I181": cell(svc, "Forward!I179", u) + 100})
    assert cell(svc, "Forward!E181", u) > 40.5
    put(svc, u, {"Forward!I181": ""})
    assert cell(svc, "Forward!E181", u) == "" and cell(svc, "Forward!P181", u) == ""


def test_a_cross_forward_typed_gives_back_its_rate(svc):
    """ÇAPRAZ FORWARD: a XXXTRY forward typed -> the TRY rate it implies, the foreign leg held - the manual forward's (Q)
    own value typed back gives its manual TRY % (USD; EUR on its own days); another currency holds Bloomberg's USDXXX
    forward (none in the recorded file: no rate rather than a wrong one)."""
    u = svc.login("Çapraz ters")["user"]
    r1 = extras.CROSS_ROWS[0]
    for ccy in ("USD", "EUR"):
        put(svc, u, {"Forward!C197": ccy, "Forward!F%d" % r1: "41", "Forward!F%d" % (r1 + 3): "39,25"})
        typed = {"Forward!R%d" % r: cell(svc, "Forward!Q%d" % r, u) for r in (r1, r1 + 3)}
        assert all(isinstance(v, float) for v in typed.values())
        put(svc, u, typed)
        for r, rate in ((r1, 41.0), (r1 + 3, 39.25)):
            assert cell(svc, "Forward!S%d" % r, u) == pytest.approx(rate, abs=1e-9), ccy
            ret_mid = (cell(svc, "Forward!D%d" % r, u) + cell(svc, "Forward!E%d" % r, u)) / 2
            assert cell(svc, "Forward!T%d" % r, u) == pytest.approx((rate - ret_mid) * 100, abs=1e-9)
        assert cell(svc, "Forward!R%d" % (r1 - 1), u) == ccy + "TRY fwd (elle)"
    put(svc, u, {"Forward!C197": "CHF"})
    assert cell(svc, "Forward!S%d" % r1, u) == ""
    model = svc.books["tto"].model
    assert "$R%d*AVERAGE($K%d,$L%d)" % (r1, r1, r1) in extras.formula_of(model, "Forward", "S%d" % r1)
    put(svc, u, {"Forward!R%d" % r1: ""})
    assert cell(svc, "Forward!S%d" % r1, u) == ""


def test_the_eurtry_matrix_is_on_the_forward_page_below_the_usdtry_one(svc):
    page = svc.view(None, "forward")
    panels = {p["id"]: p for p in page["panels"]}
    tab = next(s for s in page["sections"] if s["id"] == "kot")
    assert tab["title"] == "Kotasyon" and tab["panels"] == ["EKF1", "EKF5", "EKF2", "EKF8", "EKF6", "EKF9"]
    assert panels["EKF5"]["title"].startswith("FORWARD KOTASYON  ·  EURTRY, OIS + spread")
    assert panels["EKF6"]["title"].startswith("PUAN → OIS SPREAD  ·  EURTRY")
    rows = panels["EKF5"]["data"]["rows"]
    assert [c.get("t") for c in rows[1]][:15] == ["Vade", "Valör", "Gün", "Spread bid", "Spread ask", "Spot bid", "Spot ask", "Puan bid",
                                                  "Puan ask", "Fwd bid", "Fwd ask", "OIS %", "TRY bid %", "TRY ask %", "EUR %"]
    inputs = [(c.get("i"), c.get("o")) for row in rows for c in row if c.get("i")]
    assert len(inputs) == 1 + 1 + 4 + 10 + 20 and all(i == "u" for i, _ in inputs)      # curve, spread source, spreads and spot, dates, per date
    assert inputs[0][1] == list(extras.FWD_CURVES)
    assert len([c for row in panels["EKF6"]["data"]["rows"] for c in row if c.get("i")]) == 20
    # each way back by a rate, right after its way back by points: 20 inputs (TRY bid / ask % of the 10 dates)
    for pid, name in (("EKF8", "FAİZ → SPREAD  ·  elle verilen"), ("EKF9", "FAİZ → SPREAD  ·  EURTRY")):
        assert panels[pid]["title"].startswith(name)
        assert len([c for row in panels[pid]["data"]["rows"] for c in row if c.get("i")]) == 20
    assert "EKF7" not in panels and "EKF7" in {p["id"] for p in svc.view(None, "forward", True)["panels"]}


# ============================================================================== gold: forwards from the swap rate
PATCHED = (("VIOP", "M58", "J27"), ("VIOP", "N58", "J28"), ("VIOP", "O58", "J29"),          # XAUTRY BID table: ask outright
           ("VIOP", "S58", "I27"), ("VIOP", "T58", "I28"), ("VIOP", "U58", "I29"),          # XAUTRY ASK table: bid outright
           ("VIOP", "M68", "J30"), ("VIOP", "N68", "J31"), ("VIOP", "O68", "J32"),          # XAUUSD table: ask outright
           ("Forward", "I29", "I33"), ("Forward", "J29", "J33"))
SPOT_BID, SPOT_ASK = 3950.10, 3950.60
RATES = {17: 4.10, 19: 4.20, 22: 4.45}                # 1M, 3M and 12M rows of the gold swap rate table, per cent
CURVE_ROWS = range(extras.XAU_CURVE[0], extras.XAU_CURVE[1] + 1)
TARGET_ROWS = range(extras.XAU_TARGETS[0], extras.XAU_TARGETS[0] + 7)
ROOTS = [root for _, _, root in extras.XAU_TENORS]


def recorded(svc, sheet, addr):
    return svc.books["tto"].model.sheet(sheet).cached[parse_a1(addr)]


def gold_defaults(svc, u):
    cells = {"EK_XAU!B3": "XAU Curncy", "EK_XAU!B5": "", "EK_XAU!C5": "", "EK_XAU!B8": "", "EK_XAU!B10": "PX_LAST",
             "EK_XAU!B11": "Otomatik", "EK_XAU!B12": extras.XAU_TICKER_KEY}
    for r, root in zip(CURVE_ROWS, ROOTS):
        cells["EK_XAU!D%d" % r] = root
        cells["EK_XAU!F%d" % r] = ""
    put(svc, u, cells)


@pytest.fixture()
def gold(svc):
    """Spot and three swap rates typed by hand (shared desk inputs); everything is put back afterwards."""
    u = svc.login("Altın")["user"]
    gold_defaults(svc, u)
    cells = {"EK_XAU!B5": SPOT_BID, "EK_XAU!C5": SPOT_ASK}
    cells.update({"EK_XAU!F%d" % r: v for r, v in RATES.items()})
    put(svc, u, cells)
    yield u
    gold_defaults(svc, u)


def rate_points(svc):
    return sorted((cell(svc, "EK_XAU!C%d" % r), v) for r, v in RATES.items())


def usd_points(svc):
    return sorted((cell(svc, "VIOP!B%d" % r), cell(svc, "VIOP!F%d" % r)) for r in range(16, 26))


def test_gold_swap_rate_tickers_are_the_bloomberg_ones():
    assert ROOTS == ["XAUSR1W", "XAUSR1M", "XAUSR2M", "XAUSR3M", "XAUSR6M", "XAUSR9M", "XAUSR12M"]
    assert extras.XAU_TICKER_KEY == "Curncy" and extras.XAU_SOURCES == ("Otomatik", "Swap faizi", "BFXFORWARD")


def test_offline_the_gold_tables_show_what_excel_recorded(svc):
    """The BFXFORWARD calls moved to EK_XAU with the values Excel saved for them: with no gold swap rates in
    the recording the VİOP gold tables and the Forward gold strip are exactly Excel's."""
    u = svc.login("Altın kayıt")["user"]
    gold_defaults(svc, u)
    assert cell(svc, "EK_XAU!B11") == "Otomatik"
    assert cell(svc, "EK_XAU!C11") == "Spot yok → BFXFORWARD"
    assert [cell(svc, "EK_XAU!D%d" % r) for r in CURVE_ROWS] == ROOTS and cell(svc, "EK_XAU!B12") == "Curncy"
    assert all(type(cell(svc, "EK_XAU!E%d" % r)) is XlError and cell(svc, "EK_XAU!G%d" % r) == "" for r in CURVE_ROWS)   # nothing recorded
    book = svc.books["tto"]
    for sheet, addr, source in PATCHED:
        assert formula_text(book, *book.cell("%s!%s" % (sheet, addr))) == "=EK_XAU!$%s$%s" % (source[0], source[1:])
        assert cell(svc, "%s!%s" % (sheet, addr)) == recorded(svc, sheet, addr) > 3900
        assert "BFXFORWARD" in formula_text(book, *book.cell("EK_XAU!%s%s" % ("G" if source[0] == "I" else "H", source[1:])))
    for r in TARGET_ROWS:
        assert cell(svc, "EK_XAU!K%d" % r) == "BFXFORWARD"
        assert cell(svc, "EK_XAU!E%d" % r) == "" and cell(svc, "EK_XAU!D%d" % r) == ""
    # what hangs on those cells is therefore unchanged too
    for addr in ("VIOP!M55", "VIOP!M52", "VIOP!S52", "VIOP!M65", "Forward!I30", "Forward!J30"):
        sheet, a = addr.split("!")
        assert cell(svc, addr) == pytest.approx(recorded(svc, sheet, a), rel=1e-12)


def test_gold_forward_is_the_spot_carried_at_the_swap_rate_without_a_usd_rate(svc, gold):
    """XAUUSD fwd = spot · (1 + swap rate · days / 360): the gold rate is applied directly."""
    assert cell(svc, "EK_XAU!B6") == SPOT_BID and cell(svc, "EK_XAU!C6") == SPOT_ASK
    assert cell(svc, "EK_XAU!D6") == pytest.approx((SPOT_BID + SPOT_ASK) / 2)
    assert cell(svc, "EK_XAU!Q16") == 3.0 and cell(svc, "EK_XAU!C11") == "Swap faizi · 3 vade"
    spot_date = cell(svc, "EK_XAU!B9")
    assert spot_date == 46330.0                                    # no gold value date offline: the USDTRY one
    curve = rate_points(svc)
    assert [d for d, _ in curve] == [30.0, 92.0, 365.0]
    seen = []
    for r in TARGET_ROWS:
        days = cell(svc, "EK_XAU!C%d" % r)
        assert days == cell(svc, "EK_XAU!B%d" % r) - spot_date
        rate = linear(curve, days, flat=True)
        assert cell(svc, "EK_XAU!D%d" % r) == pytest.approx(rate, rel=1e-13)
        carry = 1 + rate / 100 * days / 360
        assert cell(svc, "EK_XAU!E%d" % r) == pytest.approx(SPOT_BID * carry, rel=1e-13)
        assert cell(svc, "EK_XAU!F%d" % r) == pytest.approx(SPOT_ASK * carry, rel=1e-13)
        assert cell(svc, "EK_XAU!I%d" % r) == cell(svc, "EK_XAU!E%d" % r)
        assert cell(svc, "EK_XAU!J%d" % r) == cell(svc, "EK_XAU!F%d" % r)
        assert cell(svc, "EK_XAU!K%d" % r) == "Swap faizi"
        seen.append(days)
    assert seen == [57.0, 114.0, 177.0, 57.0, 114.0, 114.0, 215.0]
    # the other sheets read these forwards
    for sheet, addr, source in PATCHED:
        assert cell(svc, "%s!%s" % (sheet, addr)) == cell(svc, "EK_XAU!%s" % source) != recorded(svc, sheet, addr)
    assert cell(svc, "VIOP!M55") == pytest.approx(cell(svc, "VIOP!M57") / cell(svc, "EK_XAU!J27") * GRAM, rel=1e-13)
    assert cell(svc, "VIOP!S55") == pytest.approx(cell(svc, "VIOP!S57") / cell(svc, "EK_XAU!I27") * GRAM, rel=1e-13)
    assert cell(svc, "VIOP!M65") == pytest.approx((cell(svc, "VIOP!M67") - cell(svc, "EK_XAU!J30")) / cell(svc, "EK_XAU!J30"), rel=1e-12)
    # the curve table itself
    for r, rate in RATES.items():
        days = cell(svc, "EK_XAU!C%d" % r)
        assert cell(svc, "EK_XAU!G%d" % r) == rate
        assert cell(svc, "EK_XAU!H%d" % r) == pytest.approx(SPOT_BID * (1 + rate / 100 * days / 360), rel=1e-13)
        assert cell(svc, "EK_XAU!I%d" % r) == pytest.approx(SPOT_ASK * (1 + rate / 100 * days / 360), rel=1e-13)
        assert cell(svc, "EK_XAU!J%d" % r) == pytest.approx((SPOT_BID + SPOT_ASK) / 2 * rate / 100 * days / 360, rel=1e-9)
    assert cell(svc, "EK_XAU!G18") == "" and cell(svc, "EK_XAU!H18") == ""           # 2M has no rate: left out


def test_the_usd_rate_plays_no_part_in_the_gold_forward(svc, gold):
    """The USD OIS curve of the VİOP sheet is only shown next to the swap rate (with the lease rate the two
    imply): moving it must not move a single gold forward."""
    u = svc.login("Altın usd")["user"]
    before = [cell(svc, "EK_XAU!%s%d" % (c, r), u) for r in TARGET_ROWS for c in "EFIJ"] + [cell(svc, "VIOP!M58", u), cell(svc, "Forward!J29", u)]
    usd_1m = cell(svc, "EK_XAU!K17", u)
    days, rate = cell(svc, "EK_XAU!C17", u), RATES[17]
    assert usd_1m == pytest.approx(linear(usd_points(svc), days, False), rel=1e-13)
    lease = ((1 + usd_1m / 100 * days / 360) / (1 + rate / 100 * days / 360) - 1) * 360 / days * 100
    assert cell(svc, "EK_XAU!L17", u) == pytest.approx(lease, rel=1e-9)
    # what if the 1M USD OIS quote were 9.5 % (a what-if of this user on the VİOP sheet's USD curve)?
    res = svc.set_inputs(u, "tto", [{"ref": "VIOP!F18", "value": 9.5}], allow_adhoc=True)
    assert res["errors"] == [] and cell(svc, "VIOP!B18", u) == days
    assert cell(svc, "EK_XAU!K17", u) == pytest.approx(9.5) and cell(svc, "EK_XAU!L17", u) > lease + 5      # the information moves ...
    after = [cell(svc, "EK_XAU!%s%d" % (c, r), u) for r in TARGET_ROWS for c in "EFIJ"] + [cell(svc, "VIOP!M58", u), cell(svc, "Forward!J29", u)]
    assert after == before and all(isinstance(x, float) for x in before)                                   # ... no gold forward does
    book = svc.books["tto"]
    for r in list(TARGET_ROWS) + list(CURVE_ROWS):                   # because no forward formula refers to the USD curve
        for c in ("EFIJ" if r in TARGET_ROWS else "HIJ"):
            text = formula_text(book, *book.cell("EK_XAU!%s%d" % (c, r)))
            assert "VIOP" not in text and "BINTERPOL" not in text and "$K" not in text, text
    svc.reset_inputs(u, "tto")
    assert cell(svc, "EK_XAU!K17", u) == usd_1m


def test_swap_rate_is_flat_outside_the_quoted_tenors_and_free_dates_are_personal(svc, gold):
    u = svc.login("Altın tarih")["user"]
    put(svc, u, {"EK_XAU!B34": "09.11.2026", "EK_XAU!B35": "01.06.2028"})
    assert cell(svc, "EK_XAU!C34", u) == 5.0 and cell(svc, "EK_XAU!D34", u) == 4.10
    assert cell(svc, "EK_XAU!C35", u) == 575.0 and cell(svc, "EK_XAU!D35", u) == 4.45
    assert cell(svc, "EK_XAU!F35", u) == pytest.approx(SPOT_ASK * (1 + 4.45 / 100 * 575 / 360), rel=1e-13)
    assert cell(svc, "EK_XAU!K35", u) == "Swap faizi"
    assert cell(svc, "EK_XAU!C34") == "" and cell(svc, "EK_XAU!F35") == ""           # the dates are this user's only
    assert cell(svc, "EK_XAU!E27", u) == cell(svc, "EK_XAU!E27")                     # the curve is the desk's


def test_the_source_can_be_forced(svc, gold):
    put(svc, gold, {"EK_XAU!B11": "bfxforward"})                     # typed in any case: the list's own spelling is stored
    assert cell(svc, "EK_XAU!B11") == "BFXFORWARD" and cell(svc, "EK_XAU!C11") == "BFXFORWARD (seçildi)"
    for sheet, addr, _ in PATCHED:
        assert cell(svc, "%s!%s" % (sheet, addr)) == recorded(svc, sheet, addr)
    assert cell(svc, "EK_XAU!K27") == "BFXFORWARD" and isinstance(cell(svc, "EK_XAU!E27"), float)   # still shown for comparison
    assert cell(svc, "EK_XAU!M27") == pytest.approx((cell(svc, "EK_XAU!E27") + cell(svc, "EK_XAU!F27")) / 2
                                                    - (cell(svc, "EK_XAU!G27") + cell(svc, "EK_XAU!H27")) / 2)
    put(svc, gold, {"EK_XAU!B11": "Swap faizi", "EK_XAU!B5": "", "EK_XAU!C5": ""})
    assert cell(svc, "EK_XAU!C11") == "Swap faizi seçili: spot yok"
    v = cell(svc, "VIOP!M58")
    assert type(v) is XlError and v.code == "#N/A"                   # asked for the swap rate forward, none can be computed
    put(svc, gold, {"EK_XAU!B11": "Otomatik"})
    assert cell(svc, "EK_XAU!C11") == "Spot yok → BFXFORWARD"
    assert cell(svc, "VIOP!M58") == recorded(svc, "VIOP", "M58")
    put(svc, gold, {"EK_XAU!B5": SPOT_BID, "EK_XAU!C5": SPOT_ASK, "EK_XAU!F17": "", "EK_XAU!F19": "", "EK_XAU!F22": ""})
    assert cell(svc, "EK_XAU!C11") == "Swap faizi yok → BFXFORWARD"
    assert cell(svc, "VIOP!M58") == recorded(svc, "VIOP", "M58")


def test_bfxforward_implies_a_swap_rate(svc, gold):
    """The comparison column: the rate at which the spot carried directly gives Bloomberg's own forward."""
    spot = (SPOT_BID + SPOT_ASK) / 2
    for r in TARGET_ROWS:
        days = cell(svc, "EK_XAU!C%d" % r)
        mid = (cell(svc, "EK_XAU!G%d" % r) + cell(svc, "EK_XAU!H%d" % r)) / 2
        implied = cell(svc, "EK_XAU!L%d" % r)
        assert spot * (1 + implied / 100 * days / 360) == pytest.approx(mid, rel=1e-12)


def test_bloomberg_quotes_feed_the_swap_curve_and_a_typed_rate_wins(svc, gold):
    """Spot, its value date and the gold swap rates come from Bloomberg: the default tickers are XAUSR1W,
    XAUSR1M ... with the yellow key of the "Ticker eki" cell (here the offline provider answers for them).
    A manual rate overrides the quote of its tenor."""
    quotes = {bdp_key("XAU Curncy", "BID"): 3960.0, bdp_key("XAU Curncy", "ASK"): 3961.0,
              bdp_key("XAU Curncy", "SETTLE_DT"): "5.11.2026",
              bdp_key("XAUSR1W Curncy", "PX_LAST"): 4.00, bdp_key("XAUSR1M Curncy", "PX_LAST"): 4.05,
              bdp_key("XAUSR6M Curncy", "PX_LAST"): 4.30, bdp_key("XAUSR6M Curncy", "MID"): 4.35,
              bdp_key("XAUSR9M Index", "PX_LAST"): 4.40, bdp_key("TESTSWAP2M Comdty", "PX_LAST"): 4.15}
    changed = svc.provider.update(quotes)
    svc.et.call(svc._apply_market, changed)
    try:
        put(svc, gold, {"EK_XAU!B5": "", "EK_XAU!C5": ""})
        assert cell(svc, "EK_XAU!B6") == 3960.0 and cell(svc, "EK_XAU!C6") == 3961.0
        assert cell(svc, "EK_XAU!B7") == cell(svc, "EK_XAU!B9") == 46331.0          # gold settles a day after USDTRY here
        # without typing a ticker: the roots of the sheet + " Curncy"
        assert [cell(svc, "EK_XAU!E%d" % r) for r in (16, 17, 20)] == [4.00, 4.05, 4.30]
        assert all(type(cell(svc, "EK_XAU!E%d" % r)) is XlError and (r in RATES or cell(svc, "EK_XAU!G%d" % r) == "") for r in (18, 19, 21, 22))
        # 1W and 6M come from Bloomberg; 1M: the typed 4.10 wins over Bloomberg's 4.05; 3M and 12M are typed
        assert [cell(svc, "EK_XAU!G%d" % r) for r in (16, 17, 19, 20, 22)] == [4.00, 4.10, 4.20, 4.30, 4.45]
        assert cell(svc, "EK_XAU!Q16") == 5.0 and cell(svc, "EK_XAU!C11") == "Swap faizi · 5 vade"
        nodes = sorted((cell(svc, "EK_XAU!C%d" % r), cell(svc, "EK_XAU!G%d" % r)) for r in (16, 17, 19, 20, 22))
        days = cell(svc, "EK_XAU!C29")
        assert days == 176.0                                                          # one day less than from the USDTRY date
        rate = linear(nodes, days, True)
        assert cell(svc, "VIOP!O58") == pytest.approx(3961.0 * (1 + rate / 100 * days / 360), rel=1e-13)
        put(svc, gold, {"EK_XAU!F17": ""})
        assert cell(svc, "EK_XAU!G17") == 4.05
        # a full ticker (with its own yellow key) is used as it is typed; a root follows the "Ticker eki" cell
        put(svc, gold, {"EK_XAU!D18": "TESTSWAP2M Comdty"})
        assert cell(svc, "EK_XAU!E18") == 4.15 and cell(svc, "EK_XAU!G18") == 4.15
        put(svc, gold, {"EK_XAU!B12": "Index"})
        assert cell(svc, "EK_XAU!E21") == 4.40 and cell(svc, "EK_XAU!E18") == 4.15
        assert type(cell(svc, "EK_XAU!E17")) is XlError and cell(svc, "EK_XAU!G17") == ""       # "XAUSR1M Index" is not known
        put(svc, gold, {"EK_XAU!B12": "Curncy", "EK_XAU!B10": "MID"})                 # another Bloomberg field
        assert cell(svc, "EK_XAU!E20") == 4.35 and type(cell(svc, "EK_XAU!E17")) is XlError
        put(svc, gold, {"EK_XAU!B8": "06.11.2026"})                                   # a typed value date wins
        assert cell(svc, "EK_XAU!B9") == 46332.0 and cell(svc, "EK_XAU!C29") == 175.0
    finally:
        for k in quotes:
            svc.provider.snapshot.pop(k, None)
        svc.et.call(svc._apply_market, list(quotes))


def test_xautry_price_at_a_given_rate(svc, gold):
    """Gold's "Interest 2 SP": theoretical VİOP XAUTRY = XAUUSD forward × USDTRY forward / 31.1035."""
    u = svc.login("Altın hesap")["user"]
    c0 = extras.XAU_CALC
    row = dict((name, c0 + 1 + i) for i, name in enumerate(
        ("d1", "d2", "n", "s", "xau", "usd", "try", "swap", "xfwd", "simp", "fwd", "sp", "spd", "teo", "vbid", "vask", "dbid", "dask",
         "ibid", "iask", "sxt")))

    def v(name, col="B", user=u):
        return cell(svc, "EK_XAU!%s%d" % (col, row[name]), user)

    assert [cell(svc, "EK_XAU!%s%d" % (c, c0), u) for c in "BCD"] == [cell(svc, "VIOP!%s45" % c, u) for c in "MNO"]
    assert cell(svc, "EK_XAU!A%d" % row["swap"], u) == "Altın swap % (ops.)"
    for col, viop, target in (("B", "N", 27), ("C", "P", 28), ("D", "R", 29)):
        # the default TRY rate is what the USDTRY contract of the same expiry implies (mid of the bid / ask tables)
        assert cell(svc, "VIOP!%s9" % viop, u) == v("d2", col)
        implied = (cell(svc, "VIOP!%s13" % viop, u) + cell(svc, "VIOP!%s25" % viop, u)) / 2 * 100
        assert v("try", col) == pytest.approx(implied, rel=1e-13)
        n, spot, usd = v("n", col), v("s", col), v("usd", col)
        assert usd == pytest.approx(cell(svc, "VIOP!%s51" % "MNO"["BCD".index(col)], u) * 100, rel=1e-13)
        fwd = spot * (1 + implied / 100 / 360 * n) / (1 + usd / 100 / 360 * n)
        assert v("fwd", col) == pytest.approx(fwd, rel=1e-13)
        assert v("sp", col) == pytest.approx((fwd - spot) * 10000, rel=1e-9) and v("spd", col) == pytest.approx((fwd - spot) * 10000 / n, rel=1e-9)
        xfwd = (cell(svc, "EK_XAU!I%d" % target, u) + cell(svc, "EK_XAU!J%d" % target, u)) / 2
        assert v("xfwd", col) == pytest.approx(xfwd, rel=1e-13)
        assert v("teo", col) == pytest.approx(xfwd * fwd / GRAM, rel=1e-13)
        assert v("dbid", col) == pytest.approx(v("teo", col) - v("vbid", col)) and v("dask", col) == pytest.approx(v("teo", col) - v("vask", col))
        assert v("sxt", col) == pytest.approx((SPOT_BID + SPOT_ASK) / 2 * spot / GRAM, rel=1e-13)
        # the swap rate that the forward in use implies is the interpolated one
        assert v("simp", col) == pytest.approx(cell(svc, "EK_XAU!D%d" % target, u), rel=1e-9)
    # rates of my own: the gold forward needs the gold swap rate only, the USD rate belongs to the USDTRY leg
    put(svc, u, {"EK_XAU!B%d" % row["try"]: 40, "EK_XAU!B%d" % row["usd"]: "4,25", "EK_XAU!B%d" % row["swap"]: "4,5"})
    n, spot, days = v("n"), v("s"), cell(svc, "EK_XAU!C27", u)
    fwd = spot * (1 + 40 / 100 / 360 * n) / (1 + 4.25 / 100 / 360 * n)
    xfwd = (SPOT_BID + SPOT_ASK) / 2 * (1 + 4.5 / 100 * days / 360)
    assert v("try") == 40.0 and v("usd") == 4.25 and v("swap") == 4.5 and v("simp") == 4.5
    assert v("fwd") == pytest.approx(fwd, rel=1e-13) and v("xfwd") == pytest.approx(xfwd, rel=1e-13)
    assert v("teo") == pytest.approx(xfwd * fwd / GRAM, rel=1e-13)
    put(svc, u, {"EK_XAU!B%d" % row["usd"]: "6"})                       # another USD rate: the gold forward stays
    assert v("xfwd") == pytest.approx(xfwd, rel=1e-13) and v("fwd") != pytest.approx(fwd, rel=1e-6)
    # ... is mine alone, and blanking returns to the formula
    assert v("try", user=None) != 40.0 and v("swap", user=None) is None
    put(svc, u, {"EK_XAU!B%d" % row["try"]: "", "EK_XAU!B%d" % row["usd"]: "", "EK_XAU!B%d" % row["swap"]: ""})
    assert v("try") == v("try", user=None) and v("xfwd") == v("xfwd", user=None)


def test_xautry_calculator_takes_everything_by_hand(svc, gold):
    """Every driver of the gold calculator can be typed over (and blanked back to the market); a price typed
    into the VİOP rows gives the TRY rate and the gold swap rate it stands for; the last column is free."""
    u = svc.login("Altın elle")["user"]
    row = dict((name, extras.XAU_CALC + 1 + i) for i, name in enumerate(extras.XAU_CALC_ROWS))
    assert len(extras.XAU_CALC_ROWS) == len(extras.XAU_CALC_LABELS) == 24 and row["teo"] == 53 and row["gask"] == 63

    def v(name, col="B", user=u):
        return cell(svc, "EK_XAU!%s%d" % (col, row[name]), user)

    # untouched: the contract's own dates, the market's spot and price; the implied rate is the way back
    assert v("d1") == cell(svc, "VIOP!M47") and v("d2") == cell(svc, "VIOP!M48") and v("n") == cell(svc, "VIOP!M49")
    assert v("s") == cell(svc, "VIOP!M50") and v("xau") == pytest.approx((SPOT_BID + SPOT_ASK) / 2)
    assert v("vbid") == cell(svc, "VIOP!M57") and v("vask") == cell(svc, "VIOP!S57")
    for side in ("bid", "ask"):
        price, n, spot, usd = v("v" + side), v("n"), v("s"), v("usd")
        implied = ((price * GRAM / v("xfwd")) / spot * (1 + usd / 100 / 360 * n) - 1) * 360 / n * 100
        assert v("i" + side) == pytest.approx(implied, rel=1e-12)
        gold_days = v("d2") - cell(svc, "EK_XAU!B9")
        assert v("g" + side) == pytest.approx(((price * GRAM / v("fwd")) / v("xau") - 1) * 360 / gold_days * 100, rel=1e-12)
    # pricing at the implied rate gives the price back
    put(svc, u, {"EK_XAU!B%d" % row["try"]: v("ibid")})
    assert v("teo") == pytest.approx(v("vbid"), rel=1e-12) and v("dbid") == pytest.approx(0.0, abs=1e-8)
    assert v("on") == pytest.approx(360 * ((1 + v("try") / 100 * v("n") / 360) ** (1 / v("n")) - 1) * 100, rel=1e-12)
    put(svc, u, {"EK_XAU!B%d" % row["try"]: ""})
    # a price of my own instead of the market's; blanking it brings the market back
    market = v("ibid")
    put(svc, u, {"EK_XAU!B%d" % row["vbid"]: "6.750,00"})
    assert v("vbid") == 6750.0 and v("ibid") != pytest.approx(market, rel=1e-6) and v("vbid", user=None) == cell(svc, "VIOP!M57")
    put(svc, u, {"EK_XAU!B%d" % row["vbid"]: ""})
    assert v("vbid") == cell(svc, "VIOP!M57") and v("ibid") == pytest.approx(market, rel=1e-12)
    # another date: days, the USD rate and the gold forward follow it (the forward now off the swap rate curve)
    usd0, xfwd0 = v("usd"), v("xfwd")
    put(svc, u, {"EK_XAU!B%d" % row["d2"]: "15.01.2027"})
    n = v("n")
    assert n == 46402.0 - v("d1") and v("usd") != usd0 and v("xfwd") != xfwd0
    days = 46402.0 - cell(svc, "EK_XAU!B9")
    pts = [(cell(svc, "EK_XAU!C%d" % r), rate) for r, rate in sorted(RATES.items())]
    assert v("xfwd") == pytest.approx((SPOT_BID + SPOT_ASK) / 2 * (1 + linear(pts, days, True) / 100 * days / 360), rel=1e-12)
    # spot, forward and the first date by hand as well
    put(svc, u, {"EK_XAU!B%d" % row["s"]: "50,25", "EK_XAU!B%d" % row["xfwd"]: "3990", "EK_XAU!B%d" % row["d1"]: "10.11.2026",
                 "EK_XAU!B%d" % row["try"]: "36", "EK_XAU!B%d" % row["usd"]: "4"})
    n = 46402.0 - 46336.0
    fwd = 50.25 * (1 + 36 / 100 / 360 * n) / (1 + 4 / 100 / 360 * n)
    assert v("n") == n and v("fwd") == pytest.approx(fwd, rel=1e-13) and v("teo") == pytest.approx(3990 * fwd / GRAM, rel=1e-13)
    assert v("simp") == pytest.approx((3990 / v("xau") - 1) * 360 / days * 100, rel=1e-12)
    put(svc, u, {"EK_XAU!B%d" % row[k]: "" for k in ("d1", "d2", "s", "xfwd", "try", "usd")})
    assert v("d2") == cell(svc, "VIOP!M48") and v("xfwd") == pytest.approx(xfwd0, rel=1e-13) and v("usd") == pytest.approx(usd0, rel=1e-13)
    # the free column: nothing until its second date and rate are typed; no Bloomberg gold data needed
    assert cell(svc, "EK_XAU!E%d" % extras.XAU_CALC) == "Serbest" and v("d1", "E") == cell(svc, "VIOP!M47") and v("d2", "E") is None
    assert v("n", "E") == "" and v("teo", "E") == "" and v("ibid", "E") == ""
    put(svc, u, {"EK_XAU!E%d" % row["d2"]: "15.01.2027", "EK_XAU!E%d" % row["try"]: "36", "EK_XAU!E%d" % row["xfwd"]: "3990",
                 "EK_XAU!E%d" % row["vbid"]: "6900"})
    n, spot, usd = v("n", "E"), v("s", "E"), v("usd", "E")
    assert n == 46402.0 - v("d1", "E") and spot == cell(svc, "VIOP!M50") and 3.5 < usd < 4.5
    fwd = spot * (1 + 36 / 100 / 360 * n) / (1 + usd / 100 / 360 * n)
    assert v("teo", "E") == pytest.approx(3990 * fwd / GRAM, rel=1e-13) and v("dbid", "E") == pytest.approx(3990 * fwd / GRAM - 6900)
    assert v("ibid", "E") == pytest.approx(((6900 * GRAM / 3990) / spot * (1 + usd / 100 / 360 * n) - 1) * 360 / n * 100, rel=1e-12)
    assert v("iask", "E") == "" and v("dask", "E") == ""                        # no ask typed
    assert v("teo", "E", user=None) == ""                                         # mine alone


def test_gold_panels_are_on_the_viop_page(svc, gold):
    page = svc.view(None, "viop")
    ids = [p["id"] for p in page["panels"]]
    # after the gold tables (XAU3D: the Forward page's value date, above the forwards' "Forward tarihi" row)
    assert ids[ids.index("B11") + 1:ids.index("B11") + 7] == ["B11b", "XAU1", "XAU2", "XAU3D", "XAU3", "XAU4"]
    panels = {p["id"]: p for p in page["panels"]}
    assert panels["XAU2"]["note"].startswith("Swap % = Manuel doluysa") and "USD faizi hesaba girmez" in panels["XAU2"]["note"]
    assert panels["XAU1"]["note"].startswith("Canlıda spot ve altın swap faizi (XAUSR…) Bloomberg'den gelir")
    cells = [c for row in panels["XAU1"]["data"]["rows"] for c in row]
    shared = [c for c in cells if c.get("i") == "s"]
    assert len(shared) == 7 and any(c.get("o") == list(extras.XAU_SOURCES) for c in shared)        # incl. the ticker key
    assert sum(1 for row in panels["XAU2"]["data"]["rows"] for c in row if c.get("i") == "s") == 14       # tickers + manual rates
    assert [row[3]["t"] for row in panels["XAU2"]["data"]["rows"][1:]] == ROOTS
    # every driver of the calculator can be typed: dates, spots, USD / TRY / gold swap rate, gold forward, VİOP bid / ask
    assert sum(1 for row in panels["XAU4"]["data"]["rows"] for c in row if c.get("i") == "u") == 10 * 4
    assert sum(1 for row in panels["XAU3"]["data"]["rows"] for c in row if c.get("t") == "Swap faizi") == 7
    fwd = {p["id"]: p for p in svc.view(None, "forward")["panels"]}
    assert "swap faizi (XAUSR)" in fwd["B16"]["note"]


class _Direct(ReplayProvider):
    """A connected Bloomberg that answers at once - and, like the API, has no BFXFORWARD."""
    live = True

    def _get(self, key):
        v = self.snapshot.get(key)
        return NA_NA if v is None else v

    get_bdp = get_bdh = get_bds = _get

    def get_bfx(self, key):
        return NO_BFX

    def get_rt(self, key):
        return NO_RT


def test_live_without_bfxforward_the_gold_tables_run_on_the_swap_rate(svc, tmp_path):
    today = svc.books["tto"].engine.clock.today()
    snapshot = {k: v for k, v in svc.provider.snapshot.items() if k[0] != "BFX"}
    snapshot.update({bdp_key("XAU Curncy", "BID"): 3960.0, bdp_key("XAU Curncy", "ASK"): 3961.0})
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    provider = _Direct(snapshot)
    live = Service(Settings(data_dir=str(tmp_path), mode="live"), provider=provider, clock=clock)
    try:
        assert live.mode == "live"
        # Bloomberg has no quote for the swap rate tickers (yet): the API cannot price the forward, so the
        # tables are empty-handed, as they were
        assert cell(live, "EK_XAU!E17") == NA_NA and cell(live, "EK_XAU!H27") == NO_BFX == cell(live, "VIOP!M58")
        assert cell(live, "EK_XAU!C11") == "Swap faizi yok → BFXFORWARD"
        assert type(cell(live, "VIOP!M55")) is XlError
        # the quotes of the default tickers arrive: no typing needed
        quotes = {bdp_key("XAUSR1M Curncy", "PX_LAST"): 4.05, bdp_key("XAUSR12M Curncy", "PX_LAST"): 4.40}
        provider.snapshot.update(quotes)
        live.et.call(live._apply_market, list(quotes))
        assert cell(live, "EK_XAU!C11") == "Swap faizi · 2 vade"
        days = cell(live, "EK_XAU!C27")
        nodes = sorted((cell(live, "EK_XAU!C%d" % r), cell(live, "EK_XAU!G%d" % r)) for r in (17, 22))
        assert [y for _, y in nodes] == [4.05, 4.40]
        rate = linear(nodes, days, True)
        ask = 3961.0 * (1 + rate / 100 * days / 360)
        assert cell(live, "VIOP!M58") == pytest.approx(ask, rel=1e-13)
        assert cell(live, "VIOP!M55") == pytest.approx(cell(live, "VIOP!M57") / ask * GRAM, rel=1e-13)
        assert isinstance(cell(live, "VIOP!M52"), float) and isinstance(cell(live, "Forward!I30"), float)
        assert cell(live, "EK_XAU!K27") == "Swap faizi" and cell(live, "EK_XAU!L27") == ""          # nothing to compare with
        assert live.view(None, "borsa").get("note") is None                                    # the offline notice is offline only
    finally:
        live.stop()


# ============================================================================== BIST swap quotes: O/N equivalents
def test_overnight_equivalents_of_the_bist_swap_quotes(service):
    def b(ref):
        return cell(service, ref, book="borsa")

    assert [b("bu!%s8" % c) for c in ("I", "L", "O", "P")] == ["BID SP / gün", "ASK SP / gün", "BID O/N", "ASK O/N"]
    assert [b("bu!%s8" % c) for c in ("V", "Y", "AB", "AC")] == ["BID SP / gün", "ASK SP / gün", "BID O/N", "ASK O/N"]
    seen = 0
    for days_col, rate_col, on_col in (("E", "H", "O"), ("E", "M", "P"), ("R", "U", "AB"), ("R", "Z", "AC")):
        for r in range(9, 55):
            days, rate, on = b("bu!%s%d" % (days_col, r)), b("bu!%s%d" % (rate_col, r)), b("bu!%s%d" % (on_col, r))
            if not (isinstance(days, float) and isinstance(rate, float)):
                assert on == ""
                continue
            assert on == pytest.approx(360 * ((1 + rate * days / 360) ** (1 / days) - 1), rel=1e-13)
            if days == 1.0:
                assert on == pytest.approx(rate, rel=1e-12)                 # one day: the rate itself
            else:
                assert on < rate                                            # compounding daily needs a lower rate
            seen += 1
    assert seen >= 25
    # the listed maturities are the quoted ones, in order (the workbook's FILTER formulas)
    days = [b("bu!E%d" % r) for r in range(9, 30)]
    days = [d for d in days if isinstance(d, float)]
    assert days == sorted(days) and len(days) >= 9 and days[0] == 1.0


def test_bist_quotes_without_an_order_behind_them_are_not_listed(tmp_path):
    """What the desk saw live: a maturity that exists but is not quoted comes back from the API with a size
    of 0 and an old price - the same on both sides - or with no price at all.  The workbook lists a maturity
    whose size "is a number", so all of those were on the page.  Only a side with a size above zero is a
    quote; a maturity is listed when it has one."""
    from conftest import make_service
    svc = make_service(tmp_path)
    try:
        assert svc.books["borsa"].left_out == []
        prov = svc.provider
        na = "#N/A N/A"
        for k in list(prov.snapshot):                               # the offline example quotes
            if k[0] == "BDP" and " BFX" in k[1]:
                del prov.snapshot[k]

        def quote(days, source, bid=na, bid_size=na, ask=na, ask_size=na):
            for field, value in (("BID", bid), ("BID_SIZE", bid_size), ("ASK", ask), ("ASK_SIZE", ask_size)):
                prov.snapshot[bdp_key("TYB%dD BFX%d Curncy" % (days, source), field)] = value

        quote(1, 0, 434.0, 0.0, 434.0, 0.0)                         # an old price on both sides, no order
        quote(2, 0, na, 0.0, na, 0.0)                               # exists, nothing at all
        quote(7, 0, 3050.0, 5e6, 3100.0, 2e7)                       # a real two-sided quote
        quote(10, 0, 4330.0, 1e6, 4330.0, 0.0)                      # a real bid, an old ask
        quote(15, 0, 6575.0, 0.0, 6600.0, 3e6)                      # a real ask, an old bid
        quote(20, 0, 9000.0, na, 9010.0, na)                        # prices without sizes
        quote(30, 1, 12850.0, 5e6, 13100.0, 2e7)
        quote(64, 1, 26700.0, 1e7, 27350.0, 2.5e7)
        quote(92, 1, na, 0.0, na, 0.0)
        svc.et.call(lambda: [book.engine.reset() for book in svc.books.values()])

        def b(ref):
            return cell(svc, ref, book="borsa")

        t0 = [[b("bu!%s%d" % (c, r)) for c in "EGHIJKLMNOP"] for r in range(9, 14)]
        assert [row[0] for row in t0] == [7.0, 10.0, 15.0, None, None]             # days of the listed maturities
        both, bid_only, ask_only = t0[0], t0[1], t0[2]
        #          days  size   bid%  /day  points | points /day ask%  size |  O/N bid, ask
        assert both[1] == 5e6 and both[4] == 3050.0 and both[5] == 3100.0 and both[8] == 2e7
        assert all(isinstance(x, float) for x in both)
        assert both[3] == pytest.approx(3050.0 / 7) and both[6] == pytest.approx(3100.0 / 7)
        assert bid_only[1] == 1e6 and bid_only[4] == 4330.0 and isinstance(bid_only[2], float) and isinstance(bid_only[9], float)
        assert bid_only[5:9] == ["", "", "", ""] and bid_only[10] == ""            # no ask: not the old 4,330
        assert ask_only[5] == 6600.0 and ask_only[8] == 3e6 and isinstance(ask_only[7], float) and isinstance(ask_only[10], float)
        assert ask_only[1:5] == ["", "", "", ""] and ask_only[9] == ""
        t1 = [[b("bu!%s%d" % (c, r)) for c in ("R", "T", "W", "X", "AA")] for r in range(9, 12)]
        assert t1 == [[30.0, 5e6, 12850.0, 13100.0, 2e7], [64.0, 1e7, 26700.0, 27350.0, 2.5e7], [None, None, None, None, None]]
        # nothing on the page is an error any more (the unquoted maturities used to show #VALUE!)
        for panel in svc.view(None, "borsa")["panels"]:
            if panel["id"] in ("t0", "t1"):
                texts = [c.get("t", "") for row in panel["data"]["rows"] for c in row]
                assert not [t for t in texts if t.startswith("#")], [t for t in texts if t.startswith("#")][:5]
                assert len(panel["data"]["rows"]) >= 3
        # the workbook file itself is untouched: without the dashboard's additions its own rule applies
        from tto.books import load_books
        import os
        plain = load_books(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"), extras=False)
        assert formula_text(plain["borsa"], *plain["borsa"].cell("Sheet2!E6")) == \
            '=IF(OR(ISNUMBER(Sheet1!$D4),ISNUMBER(Sheet1!$G4)),Sheet1!E4,"")'
        assert svc.cell_info(None, "borsa", "Sheet2!E6")["formula"] == \
            '=IF(IF(ISNUMBER(Sheet1!$D4),Sheet1!$D4>0,FALSE),Sheet1!E4,"")'
        assert svc.cell_info(None, "borsa", "Sheet2!B6")["formula"] == \
            '=IF(OR(IF(ISNUMBER(Sheet1!$D4),Sheet1!$D4>0,FALSE),IF(ISNUMBER(Sheet1!$G4),Sheet1!$G4>0,FALSE)),Sheet1!B4,"")'
    finally:
        svc.stop()


def test_offline_bist_quotes_are_derived_from_the_recorded_ret_curve(service):
    """The Borsa workbook holds no market data: offline its quotes are example points derived from the RET
    curve of the TRY workbook, so the implied TRY rates must come out at RET (to the rounding of a point)."""
    def b(ref):
        return cell(service, ref, book="borsa")

    xs = [cell(service, "Forward!U%d" % r) for r in range(33, 48)]
    bid = sorted(zip(xs, [cell(service, "Forward!W%d" % r) for r in range(33, 48)]))
    ask = sorted(zip(xs, [cell(service, "Forward!X%d" % r) for r in range(33, 48)]))
    spot = b("Sheet1!AD19")
    assert 40 < spot < 60
    n = 0
    for r in range(9, 30):
        days = b("bu!E%d" % r)
        if not isinstance(days, float):
            continue
        tol = 0.5e-4 / spot * 360 / days + 1e-9                    # half a point of rounding
        for col, curve in (("H", bid), ("M", ask)):
            rate = b("bu!%s%d" % (col, r))
            if isinstance(rate, float):
                assert rate == pytest.approx(linear(curve, days, True), abs=tol)
                n += 1
    assert n >= 15
    note = service.view(None, "borsa")["note"]
    assert "ÖRNEK" in note and "RET" in note


# ============================================================================== DİBS ASW workbook
def test_asw_workbook_agrees_with_the_try_workbooks_bond_table(service):
    """Two workbooks, the same bonds on the same recorded day: the asset swap spread of the fixed and zero
    coupon bonds must be the one the TRY workbook's DİBS RV table shows (kept there to 0.1 bp)."""
    rv = {}
    for r in range(5, 55):
        isin = cell(service, "DİBS RV!A%d" % r)
        if isinstance(isin, str) and isin.strip():
            rv[isin.strip()] = r
    n = 0
    for r in range(7, 57):
        isin = cell(service, "ASW!B%d" % r, book="asw")
        asw = cell(service, "ASW!R%d" % r, book="asw")
        if not isinstance(isin, str) or isin.strip() not in rv:
            continue
        kind = cell(service, "DİBS RV!D%d" % rv[isin.strip()])
        if kind in ("S", "B"):
            assert asw == pytest.approx(cell(service, "DİBS RV!Z%d" % rv[isin.strip()]), abs=0.0501), isin
            n += 1
        elif kind == "T":
            assert asw == ""                                        # floaters have no fixed-rate asset swap here
    assert n >= 15


# ---------------------------------------------------------------------------------------------- VİOP history
def _piecewise(g, nodes):
    """The VİOP sheet's own interpolation: flat up to the first node and after the last, straight in between."""
    if g <= nodes[0][0]:
        return nodes[0][1]
    for (xa, ya), (xb, yb) in zip(nodes, nodes[1:]):
        if g <= xb:
            return ya + (yb - ya) * (g - xa) / (xb - xa)
    return nodes[-1][1]


VH = extras.VH_COLS


@pytest.fixture(scope="module")
def viop_history(svc, tmp_path_factory):
    """A connected Bloomberg that has a history for what the VİOP history asks for: the window of the charts
    (120 business days) and the window of the sheet's own statistics (20).  Made up: the spot creeps up, every
    contract is priced at a rate that rises with its expiry and from day to day, one close of the third contract
    is missing."""
    import datetime as dt

    from tto.marketdata.base import bdh_key
    from tto.xl.values import XlArray, serial_to_date

    today = svc.books["tto"].engine.clock.today()
    tickers = [cell(svc, "VIOP!%s1" % c) for c in "LMNOPQRSTUVW"]
    expiry = [cell(svc, "VIOP!%s9" % c) for c in "MNOPQRSTUVWX"]
    spot_ticker = cell(svc, "VIOP!S340")
    end = cell(svc, "EK_VIOP!F8")
    assert end == cell(svc, "VIOP!Q340") and cell(svc, "EK_VIOP!B8") == 120.0 == extras.VH_DAYS
    snapshot = {k: v for k, v in svc.provider.snapshot.items() if k[0] != "BFX"}
    week_day = lambda d: (dt.date(1899, 12, 30) + dt.timedelta(days=d)).weekday() < 5              # noqa: E731
    days = [d for d in range(int(cell(svc, "EK_VIOP!D8")), int(end) + 1) if week_day(d)]
    spot = {d: 46.00 + 0.03 * i for i, d in enumerate(days)}
    levels = {"TYSOA": 37.0, "TYSOB": 37.2, "TYSOC": 37.4, "TYSOF": 37.9, "TYSOI": 38.3, "TYSO1": 38.6,
              "USSOA": 3.90, "USSOC": 3.95, "USSOF": 4.05, "USSO1": 4.20}
    series = {name + " Curncy": {d: lvl + 0.004 * i for i, d in enumerate(days)} for name, lvl in levels.items()}
    price = {}
    for k, ticker in enumerate(tickers):
        series[ticker] = {}
        for i, d in enumerate(days):
            g = expiry[k] - (d + 1)
            rate = 0.33 + 0.004 * k + 0.0002 * i
            price[(k, d)] = None if (k == 2 and i == 5) else spot[d] * (1 + rate * g / 360) / (1 + 0.04 * g / 360)
            series[ticker][d] = price[(k, d)]
    dated = (("DATES", "S"), ("DAYS", "W"), ("FILL", "P"))
    plain = (("DATES", "H"), ("DAYS", "W"), ("FILL", "P"))
    for start in (cell(svc, "EK_VIOP!D8"), cell(svc, "VIOP!O340")):                  # the charts' window and the sheet's own
        lo, hi = serial_to_date(start).strftime("%Y%m%d"), serial_to_date(end).strftime("%Y%m%d")
        window = [d for d in days if d >= start]
        snapshot[bdh_key(spot_ticker, "PX_LAST", lo, hi, dated)] = XlArray([[float(d), spot[d]] for d in window])
        for ticker, points in series.items():
            snapshot[bdh_key(ticker, "PX_LAST", lo, hi, plain)] = XlArray([[points[d]] for d in window])
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    live = Service(Settings(data_dir=str(tmp_path_factory.mktemp("viop-hist")), mode="live", history=False), provider=_Direct(snapshot), clock=clock)
    yield live, days, spot, price, expiry
    live.stop()


def test_viop_history_series_use_the_sheets_own_formulas(viop_history):
    """EK_VIOP reads a history of its own (the contracts that are drawn, as long as its "Geçmiş" cell says) and
    computes the implied TRY rate, the basis over OIS and the OIS rate that goes with them with the VİOP sheet's
    formulas - checked against a calculation by hand and, where the two windows overlap, against the sheet."""
    import datetime as dt

    live, days, spot, price, expiry = viop_history
    assert live.mode == "live" and not live.books["tto"].left_out
    assert [cell(live, "EK_VIOP!%s3" % c) for c in "BCDEFG"] == [1.0, 2.0, 3.0, 4.0, None, None]
    assert cell(live, "EK_VIOP!B4") == cell(live, "VIOP!L1") and cell(live, "EK_VIOP!C5") == cell(live, "VIOP!N9")
    assert cell(live, "EK_VIOP!B6") == "30.11.26 · A1X6" and cell(live, "EK_VIOP!F6") == ""
    holidays = {int(v) for v in (cell(live, "Motor!A%d" % r) for r in range(361, 524)) if isinstance(v, float)}

    def next_business_day(d):
        d = int(d) + 1
        while (dt.date(1899, 12, 30) + dt.timedelta(days=d)).weekday() >= 5 or d in holidays:
            d += 1
        return d

    r0 = extras.VH_FIRST
    assert 120 < len(days) <= extras.VH_ROWS and extras.VH_LIVE == r0 + extras.VH_ROWS == 272
    own = {int(cell(live, "VIOP!K%d" % R)): R for R in range(380, 380 + 25) if isinstance(cell(live, "VIOP!K%d" % R), float)}
    assert len(own) == 21                                                   # the sheet's own, shorter history
    checked = same_as_sheet = 0
    for i, d in enumerate(days):
        r = r0 + i
        assert cell(live, "EK_VIOP!A%d" % r) == float(d) and cell(live, "EK_VIOP!B%d" % r) == spot[d]
        val = lambda col: cell(live, "EK_VIOP!%s%d" % (col, r))                                   # noqa: E731
        for slot in range(4):
            k = int(cell(live, "EK_VIOP!%s3" % "BCDE"[slot])) - 1
            g = expiry[k] - next_business_day(d)
            assert val(VH["days"][slot]) == g
            if price[(k, d)] is None:
                # a day without a close for the contract is left out (not drawn as a rate of -333 %)
                assert val(VH["imp"][slot]) == "" == val(VH["baz"][slot]) == val(VH["ois360"][slot])
                continue
            usd = _piecewise(g, [(x, val(c)) for x, c in zip((30, 91, 182, 365), VH["usd"])])
            implied = ((price[(k, d)] / spot[d]) * (1 + usd / 100 * g / 360) - 1) * 360 / g * 100
            ois = _piecewise(g, [(x, val(c)) for x, c in zip((30, 61, 91, 182, 273, 365), VH["ois"][:3] + VH["zero"][3:])]) * 360 / 365
            assert val(VH["imp"][slot]) == pytest.approx(implied, rel=1e-11)
            assert val(VH["baz"][slot]) == pytest.approx((implied - ois) * 100, abs=1e-7)
            assert val(VH["ois360"][slot]) == pytest.approx(ois, rel=1e-11)
            checked += 1
            if d in own:                                                    # the same day in the sheet's own block: its "Baz"
                assert val(VH["baz"][slot]) == pytest.approx(cell(live, "VIOP!%s%d" % (("AJ", "AK", "AL", "AM")[k], own[d])), abs=1e-9)
                same_as_sheet += 1
    assert checked == len(days) * 4 - 1 and same_as_sheet >= 80
    # the zero rates of the day are the sheet's (6M from the 3M and 6M quotes ...)
    R = own[days[-1]]
    assert [cell(live, "EK_VIOP!%s%d" % (c, r0 + len(days) - 1)) for c in VH["zero"]] == \
        pytest.approx([cell(live, "VIOP!%s%d" % (c, R)) for c in ("AW", "AX", "AY", "AZ", "BA", "BB")], rel=1e-13)
    assert [cell(live, "EK_VIOP!%s7" % c) for c in "BCDEFG"] == [len(days), len(days), len(days) - 1.0, len(days), "", ""]
    assert cell(live, "EK_VIOP!A%d" % (r0 + len(days))) is None                                  # nothing below the history
    # the row after it is the sheet's live row: today's last prices, the same way
    last = extras.VH_LIVE
    assert cell(live, "EK_VIOP!A%d" % last) == cell(live, "VIOP!K511") > days[-1]
    assert cell(live, "EK_VIOP!%s%d" % (VH["baz"][0], last)) == cell(live, "VIOP!AJ511") == pytest.approx(cell(live, "VIOP!M350"))
    assert cell(live, "EK_VIOP!%s%d" % (VH["imp"][0], last)) == pytest.approx(
        cell(live, "EK_VIOP!%s%d" % (VH["ois360"][0], last)) + cell(live, "VIOP!AJ511") / 100)


def test_viop_history_charts(viop_history, svc):
    live, days, spot, price, expiry = viop_history
    page = live.view(None, "viop")
    panels = {p["id"]: p for p in page["panels"]}
    tab = next(s for s in page["sections"] if s["id"] == "basis")
    assert tab["title"] == "Geçmiş · baz" and tab["panels"][:4] == ["VH1", "VH2", "VH3", "B34"]
    rate, basis = panels["VH2"]["data"], panels["VH3"]["data"]
    assert panels["VH2"]["title"].startswith("VİOP ima TRY faizi") and panels["VH3"]["title"].startswith("VİOP − OIS")
    for chart in (rate, basis):
        assert chart["kind"] == "scatter" and chart["xaxis"] == {"type": "date", "format": "dd.mm.yy"}
        assert [s["name"] for s in chart["series"]] == ["30.11.26 · A1X6", "31.12.26 · A1Z6", "29.01.27 · A1F7", "26.02.27 · A1G7"]
        for s in chart["series"]:
            assert s["x"] == [float(d) for d in days] + [cell(live, "VIOP!K511")]             # the history, then today
    r0 = extras.VH_FIRST
    assert rate["series"][0]["data"][3] == cell(live, "EK_VIOP!%s%d" % (VH["imp"][0], r0 + 3))
    assert basis["series"][1]["data"][-1] == cell(live, "VIOP!AK511")
    # the missing close: a point the line passes over, not a zero
    assert rate["series"][2]["data"][5] == "c" and basis["series"][2]["data"][5] == "c"
    assert all(type(y) is float for y in rate["series"][0]["data"]) and rate["decimals"] == 2 and basis["decimals"] == 0
    # the statistics of the sheet keep their own window: 20 days, whatever the charts draw
    assert cell(live, "VIOP!M340") == 20.0 and cell(live, "VIOP!M349") == 21.0 and len(rate["series"][0]["x"]) > 120
    # other contracts and another length: the user's own choice; a line without a contract is not drawn
    u = live.login("Geçmiş çizgi")["user"]
    put(live, u, {"EK_VIOP!B3": "", "EK_VIOP!F3": "12", "EK_VIOP!C3": "5"})
    mine = next(p for p in live.view(u, "viop")["panels"] if p["id"] == "VH2")["data"]
    assert [s["name"] for s in mine["series"]] == ["31.03.27 · A1H7", "29.01.27 · A1F7", "26.02.27 · A1G7", "27.10.27 · A1V7"]
    assert mine["series"][3]["data"][0] == pytest.approx(cell(live, "EK_VIOP!%s%d" % (VH["imp"][4], r0), u))
    assert cell(live, "EK_VIOP!%s%d" % (VH["imp"][0], r0), u) == ""
    assert [s["name"] for s in next(p for p in live.view(None, "viop")["panels"] if p["id"] == "VH2")["data"]["series"]][0] == "30.11.26 · A1X6"
    selector = panels["VH1"]["data"]
    assert [c.get("i") for c in selector["rows"][1][1:]] == ["u"] * 6 and selector["rows"][1][1].get("o") == [str(i) for i in range(1, 13)]
    assert selector["rows"][6][1]["i"] == "u" and selector["rows"][6][1]["v"] == 120.0                 # "Geçmiş (iş günü)"
    assert panels["VH1"]["note"].startswith("Grafikler kendi geçmişini okur")
    put(live, u, {"EK_VIOP!B8": "500"})                                         # more than the rows can hold: the most there is
    from tto.xl.values import serial_to_date
    span = (serial_to_date(cell(live, "EK_VIOP!F8", u)) - serial_to_date(cell(live, "EK_VIOP!D8", u))).days
    assert cell(live, "EK_VIOP!D8", u) < cell(live, "EK_VIOP!D8") and span * 5 / 7 < extras.VH_ROWS and extras.VH_MAX_DAYS == 240
    put(live, u, {"EK_VIOP!B8": "60"})
    assert cell(live, "EK_VIOP!D8", u) > cell(live, "EK_VIOP!D8") and cell(live, "VIOP!O340", u) == cell(live, "VIOP!O340")
    # offline nothing of the history is recorded: the charts show the live point alone, and say so
    off = {p["id"]: p for p in svc.view(None, "viop")["panels"]}
    assert [len([y for y in s["data"] if type(y) is float]) for s in off["VH2"]["data"]["series"]] == [1, 1, 1, 1]
    assert "Kayıtlı veri modunda VİOP geçmişi kaydı yoktur" in off["VH1"]["note"]


def test_the_matrices_show_the_markets_spread_and_can_price_with_it(svc):
    """Next to each date the market's spread: the offshore (ICAP) implied TRY rate − OIS, bid and ask.  "Piyasa spread"
    in the general row prices every date with it (EURTRY follows USDTRY unless set apart); "Elle spread" back."""
    nodes = [cell(svc, "Forward!G%d" % r) for r in range(8, 22)]
    bids = list(zip(nodes, [cell(svc, "Forward!I%d" % r) for r in range(8, 22)]))
    asks = list(zip(nodes, [cell(svc, "Forward!K%d" % r) for r in range(8, 22)]))
    u = svc.login("Piyasa spread")["user"]
    for g, rows, days in ((extras.FWD_ALL, FWD_ROWS, "C"), (EUR_ALL, EUR_ROWS, "AL")):
        assert cell(svc, "EK_FWD!B%d" % g) == extras.FWD_SPREAD_OWN
        for r in rows:
            d, ois = cell(svc, "EK_FWD!%s%d" % (days, r)), cell(svc, "EK_FWD!L%d" % r)
            assert cell(svc, "EK_FWD!V%d" % r) == pytest.approx((linear(bids, d, True) - ois) * 100, rel=1e-12)
            assert cell(svc, "EK_FWD!W%d" % r) == pytest.approx((linear(asks, d, True) - ois) * 100, rel=1e-12)
    put(svc, u, {"EK_FWD!B%d" % extras.FWD_ALL: "piyasa spread"})              # (any case)
    assert cell(svc, "EK_FWD!B%d" % EUR_ALL, u) == extras.FWD_SPREAD_MARKET     # EURTRY follows
    for g, rows, days in ((extras.FWD_ALL, FWD_ROWS, "C"), (EUR_ALL, EUR_ROWS, "AL")):
        for r in rows:
            d = cell(svc, "EK_FWD!%s%d" % (days, r), u)
            assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(linear(bids, d, True), rel=1e-12)   # TRY bid = offshore bid
            assert cell(svc, "EK_FWD!N%d" % r, u) == pytest.approx(linear(asks, d, True), rel=1e-12)
    put(svc, u, {"EK_FWD!E%d" % FWD_ROWS[2]: -10})                               # a date can still have its own
    assert cell(svc, "EK_FWD!N%d" % FWD_ROWS[2], u) == pytest.approx(cell(svc, "EK_FWD!L%d" % FWD_ROWS[2], u) - 0.1)
    put(svc, u, {"EK_FWD!B%d" % EUR_ALL: extras.FWD_SPREAD_OWN})                 # EURTRY set apart
    r = EUR_ROWS[0]
    assert cell(svc, "EK_FWD!M%d" % r, u) == pytest.approx(cell(svc, "EK_FWD!L%d" % r, u) - 1.5)
    assert cell(svc, "EK_FWD!B%d" % extras.FWD_ALL, u) == extras.FWD_SPREAD_MARKET
