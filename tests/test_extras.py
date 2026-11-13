"""The dashboard's own sheets (``tto/extras.py``): forward quotes from OIS + spread with separate bid / ask
spreads, gold forwards from lease rates in place of ``BFXFORWARD``, O/N equivalents of the BIST swap quotes.

They are ordinary Excel formulas inside the workbook model, so every check below reads cells - and compares
them with an independent calculation or with what the workbook itself computes elsewhere."""
import pytest

from conftest import cell
from tto import extras
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
    assert svc.cell_info(None, "tto", "EK_XAU!F27")["formula"].startswith('=IFERROR(IF(OR($C27="",$D27=""),"",$B$6*(1+$E27/100*$C27/360)')
    assert svc.cell_info(None, "borsa", "bu!O9")["formula"] == '=IF(AND(ISNUMBER(H9),ISNUMBER(E9),N(E9)>0),360*((1+H9*E9/360)^(1/E9)-1),"")'
    grid = svc.grid(None, "tto", "EK_FWD", "A3:C5")["data"]
    assert [c["t"] for c in grid["rows"][0]] == ["Vade", "Valör", "Gün"] and grid["rows"][2][0]["t"] == "1M"


def test_an_addition_that_no_longer_fits_its_workbook_is_left_out():
    """The additions build on particular cells.  When a workbook is imported again with another layout the
    dashboard must still start: an addition whose cells are not what it expects is left out and reported."""
    import os
    from tto.xl.model import Model
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sofr = Model.load(os.path.join(root, "models", "sofr.json.gz"))                 # not the workbook they were written for
    n = sofr.formula_count()
    problems = extras.apply("tto", sofr)
    assert [p.split(":")[0] for p in problems] == ["EK_FWD", "EK_XAU"]
    assert sofr.formula_count() == n and "EK_FWD" not in sofr.sheet_index and "EK_XAU" not in sofr.sheet_index
    # the TRY workbook with one gold forward typed over by hand: the gold tables stay as they are in the file
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    viop = tto.sheet("VIOP")
    del viop.fml[parse_a1("M58")]
    viop.consts[parse_a1("M58")] = 3971.85
    formulas = dict(viop.fml)
    assert extras.apply("tto", tto) == ["EK_XAU: VIOP!M58 bir formül değil"]
    assert "EK_FWD" in tto.sheet_index and "EK_XAU" not in tto.sheet_index and viop.fml == formulas
    # a discount factor that depends on another cell of the desk sheet cannot be moved to the matrix
    tto = Model.load(os.path.join(root, "models", "tto.json.gz"))
    b = extras.SheetBuilder(tto, "MASA")
    b.patch("I67", "=" + extras.formula_of(tto, "MASA", "I67") + "*$I$60/$I$60")
    assert extras.apply("tto", tto)[0].startswith("EK_FWD: unqualified references left")
    assert "EK_FWD" not in tto.sheet_index and "EK_XAU" in tto.sheet_index
    borsa = Model.load(os.path.join(root, "models", "borsa.json.gz"))
    borsa.sheet("bu").consts[parse_a1("H8")] = "Bid"
    assert extras.apply("borsa", borsa) == ["Borsa O/N: bu!H8 başlığı 'BID %' değil"]
    assert borsa.sheet("bu").fml.get(parse_a1("O9")) is None


def test_tables_of_a_left_out_addition_are_not_shown(svc):
    assert all(b["left_out"] == [] for b in svc.status()["books"].values())        # with the real files everything fits
    view = svc.view_index["masa"]
    saved = [dict(p) for p in view["panels"]]
    try:
        for p in view["panels"]:
            if p.get("sheet") == "EK_FWD":
                p["sheet"] = "EK_YOK"                                               # as if the sheet had not been built
        svc._view_cache.clear()
        ids = [p["id"] for p in svc.view(None, "masa", True)["panels"]]
        assert "B14" in ids and not any(i.startswith("EKF") for i in ids)
        assert all("error" not in p for p in svc.view(None, "masa", True)["panels"])
    finally:
        view["panels"][:] = saved
        svc._view_cache.clear()
    assert "EKF1" in [p["id"] for p in svc.view(None, "masa")["panels"]]


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


def test_matrix_panels_are_on_the_desk_page_with_their_inputs(svc):
    page = svc.view(None, "masa")
    panels = {p["id"]: p for p in page["panels"]}
    ids = [p["id"] for p in page["panels"]]
    assert ids.index("EKF1") == ids.index("B14") + 1 and ids.index("EKF2") == ids.index("EKF1") + 1
    assert panels["EKF1"]["title"].startswith("FORWARD KOTASYON") and panels["EKF2"]["title"].startswith("PUAN → OIS SPREAD")
    rows = panels["EKF1"]["data"]["rows"]
    head = [c.get("t") for c in rows[1]]
    assert head[:11] == ["Vade", "Valör", "Gün", "Spread bid", "Spread ask", "Spot bid", "Spot ask", "Puan bid", "Puan ask",
                         "Fwd bid", "Fwd ask"]
    inputs = [(c.get("i"), c.get("o")) for row in rows for c in row if c.get("i")]
    assert len(inputs) == 1 + 2 + 10 + 20 and all(i == "u" for i, _ in inputs)          # curve, general, dates, per date
    assert inputs[0][1] == list(extras.FWD_CURVES)                                       # the curve is a drop-down
    assert "EKF3" not in panels and "EKF3" in {p["id"] for p in svc.view(None, "masa", True)["panels"]}


# ============================================================================== gold: forwards from lease rates
PATCHED = (("VIOP", "M58", "K27"), ("VIOP", "N58", "K28"), ("VIOP", "O58", "K29"),          # XAUTRY BID table: ask outright
           ("VIOP", "S58", "J27"), ("VIOP", "T58", "J28"), ("VIOP", "U58", "J29"),          # XAUTRY ASK table: bid outright
           ("VIOP", "M68", "K30"), ("VIOP", "N68", "K31"), ("VIOP", "O68", "K32"),          # XAUUSD table: ask outright
           ("Forward", "I29", "J33"), ("Forward", "J29", "K33"))
SPOT_BID, SPOT_ASK = 3950.10, 3950.60
LEASE = {17: 0.45, 19: 0.55, 22: 0.80}                # 1M, 3M and 12M rows of the lease table, per cent
LEASE_ROWS = range(extras.XAU_LEASE[0], extras.XAU_LEASE[1] + 1)
TARGET_ROWS = range(extras.XAU_TARGETS[0], extras.XAU_TARGETS[0] + 7)


def recorded(svc, sheet, addr):
    return svc.books["tto"].model.sheet(sheet).cached[parse_a1(addr)]


def gold_defaults(svc, u):
    cells = {"EK_XAU!B3": "XAU Curncy", "EK_XAU!B5": "", "EK_XAU!C5": "", "EK_XAU!B8": "", "EK_XAU!B10": "PX_LAST",
             "EK_XAU!B11": "Otomatik"}
    for r in LEASE_ROWS:
        cells["EK_XAU!D%d" % r] = ""
        cells["EK_XAU!F%d" % r] = ""
    put(svc, u, cells)


@pytest.fixture()
def gold(svc):
    """Spot and three lease rates typed by hand (shared desk inputs); everything is put back afterwards."""
    u = svc.login("Altın")["user"]
    gold_defaults(svc, u)
    cells = {"EK_XAU!B5": SPOT_BID, "EK_XAU!C5": SPOT_ASK}
    cells.update({"EK_XAU!F%d" % r: v for r, v in LEASE.items()})
    put(svc, u, cells)
    yield u
    gold_defaults(svc, u)


def lease_points(svc):
    return sorted((cell(svc, "EK_XAU!C%d" % r), v) for r, v in LEASE.items())


def usd_points(svc):
    return sorted((cell(svc, "VIOP!B%d" % r), cell(svc, "VIOP!F%d" % r)) for r in range(16, 26))


def test_offline_the_gold_tables_show_what_excel_recorded(svc):
    """The BFXFORWARD calls moved to EK_XAU with the values Excel saved for them: with no lease rates in
    the recording the VİOP gold tables and the Forward gold strip are exactly Excel's."""
    u = svc.login("Altın kayıt")["user"]
    gold_defaults(svc, u)
    assert cell(svc, "EK_XAU!B11") == "Otomatik"
    assert cell(svc, "EK_XAU!C11") == "Spot yok → BFXFORWARD"
    book = svc.books["tto"]
    for sheet, addr, source in PATCHED:
        assert formula_text(book, *book.cell("%s!%s" % (sheet, addr))) == "=EK_XAU!$%s$%s" % (source[0], source[1:])
        assert cell(svc, "%s!%s" % (sheet, addr)) == recorded(svc, sheet, addr) > 3900
        assert "BFXFORWARD" in formula_text(book, *book.cell("EK_XAU!%s%s" % ("H" if source[0] == "J" else "I", source[1:])))
    for r in TARGET_ROWS:
        assert cell(svc, "EK_XAU!L%d" % r) == "BFXFORWARD"
        assert cell(svc, "EK_XAU!F%d" % r) == "" and cell(svc, "EK_XAU!D%d" % r) == ""
    # what hangs on those cells is therefore unchanged too
    for addr in ("VIOP!M55", "VIOP!M52", "VIOP!S52", "VIOP!M65", "Forward!I30", "Forward!J30"):
        sheet, a = addr.split("!")
        assert cell(svc, addr) == pytest.approx(recorded(svc, sheet, a), rel=1e-12)


def test_gold_forward_is_the_cost_of_carry_at_the_interpolated_lease_rate(svc, gold):
    assert cell(svc, "EK_XAU!B6") == SPOT_BID and cell(svc, "EK_XAU!C6") == SPOT_ASK
    assert cell(svc, "EK_XAU!D6") == pytest.approx((SPOT_BID + SPOT_ASK) / 2)
    assert cell(svc, "EK_XAU!Q16") == 3.0 and cell(svc, "EK_XAU!C11") == "Lease · 3 vade"
    spot_date = cell(svc, "EK_XAU!B9")
    assert spot_date == 46330.0                                    # no gold value date offline: the USDTRY one
    lease, usd = lease_points(svc), usd_points(svc)
    assert [d for d, _ in lease] == [30.0, 92.0, 365.0]
    seen = []
    for r in TARGET_ROWS:
        days = cell(svc, "EK_XAU!C%d" % r)
        assert days == cell(svc, "EK_XAU!B%d" % r) - spot_date
        l, s = linear(lease, days, flat=True), linear(usd, days, flat=False)
        assert cell(svc, "EK_XAU!D%d" % r) == pytest.approx(l, rel=1e-13)
        assert cell(svc, "EK_XAU!E%d" % r) == pytest.approx(s, rel=1e-13)
        carry = (1 + s / 100 * days / 360) / (1 + l / 100 * days / 360)
        assert cell(svc, "EK_XAU!F%d" % r) == pytest.approx(SPOT_BID * carry, rel=1e-13)
        assert cell(svc, "EK_XAU!G%d" % r) == pytest.approx(SPOT_ASK * carry, rel=1e-13)
        assert cell(svc, "EK_XAU!J%d" % r) == cell(svc, "EK_XAU!F%d" % r)
        assert cell(svc, "EK_XAU!K%d" % r) == cell(svc, "EK_XAU!G%d" % r)
        assert cell(svc, "EK_XAU!L%d" % r) == "Lease"
        seen.append(days)
    assert seen == [57.0, 114.0, 177.0, 57.0, 114.0, 114.0, 215.0]
    # the other sheets read these forwards
    for sheet, addr, source in PATCHED:
        assert cell(svc, "%s!%s" % (sheet, addr)) == cell(svc, "EK_XAU!%s" % source) != recorded(svc, sheet, addr)
    assert cell(svc, "VIOP!M55") == pytest.approx(cell(svc, "VIOP!M57") / cell(svc, "EK_XAU!K27") * GRAM, rel=1e-13)
    assert cell(svc, "VIOP!S55") == pytest.approx(cell(svc, "VIOP!S57") / cell(svc, "EK_XAU!J27") * GRAM, rel=1e-13)
    assert cell(svc, "VIOP!M65") == pytest.approx((cell(svc, "VIOP!M67") - cell(svc, "EK_XAU!K30")) / cell(svc, "EK_XAU!K30"), rel=1e-12)
    # the lease curve table itself
    for r, rate in LEASE.items():
        days, s = cell(svc, "EK_XAU!C%d" % r), cell(svc, "EK_XAU!H%d" % r)
        assert cell(svc, "EK_XAU!G%d" % r) == rate
        assert cell(svc, "EK_XAU!J%d" % r) == pytest.approx(SPOT_BID * (1 + s / 100 * days / 360) / (1 + rate / 100 * days / 360), rel=1e-13)
        fwd_rate = ((1 + s / 100 * days / 360) / (1 + rate / 100 * days / 360) - 1) * 360 / days * 100
        assert cell(svc, "EK_XAU!I%d" % r) == pytest.approx(fwd_rate, rel=1e-12)
    assert cell(svc, "EK_XAU!G18") == "" and cell(svc, "EK_XAU!J18") == ""           # 2M has no rate: left out


def test_lease_is_flat_outside_the_quoted_tenors_and_free_dates_are_personal(svc, gold):
    u = svc.login("Altın tarih")["user"]
    put(svc, u, {"EK_XAU!B34": "09.11.2026", "EK_XAU!B35": "01.06.2028"})
    assert cell(svc, "EK_XAU!C34", u) == 5.0 and cell(svc, "EK_XAU!D34", u) == 0.45
    assert cell(svc, "EK_XAU!C35", u) == 575.0 and cell(svc, "EK_XAU!D35", u) == 0.80
    usd = linear(usd_points(svc), 575.0, flat=False)                 # beyond 1Y the USD curve is extended
    assert cell(svc, "EK_XAU!E35", u) == pytest.approx(usd, rel=1e-13)
    assert cell(svc, "EK_XAU!G35", u) == pytest.approx(SPOT_ASK * (1 + usd / 100 * 575 / 360) / (1 + 0.80 / 100 * 575 / 360), rel=1e-13)
    assert cell(svc, "EK_XAU!L35", u) == "Lease"
    assert cell(svc, "EK_XAU!C34") == "" and cell(svc, "EK_XAU!G35") == ""           # the dates are this user's only
    assert cell(svc, "EK_XAU!F27", u) == cell(svc, "EK_XAU!F27")                     # the lease curve is the desk's


def test_the_source_can_be_forced(svc, gold):
    put(svc, gold, {"EK_XAU!B11": "bfxforward"})                     # typed in any case: the list's own spelling is stored
    assert cell(svc, "EK_XAU!B11") == "BFXFORWARD" and cell(svc, "EK_XAU!C11") == "BFXFORWARD (seçildi)"
    for sheet, addr, _ in PATCHED:
        assert cell(svc, "%s!%s" % (sheet, addr)) == recorded(svc, sheet, addr)
    assert cell(svc, "EK_XAU!L27") == "BFXFORWARD" and isinstance(cell(svc, "EK_XAU!F27"), float)   # still shown for comparison
    assert cell(svc, "EK_XAU!N27") == pytest.approx((cell(svc, "EK_XAU!F27") + cell(svc, "EK_XAU!G27")) / 2
                                                    - (cell(svc, "EK_XAU!H27") + cell(svc, "EK_XAU!I27")) / 2)
    put(svc, gold, {"EK_XAU!B11": "Lease", "EK_XAU!B5": "", "EK_XAU!C5": ""})
    assert cell(svc, "EK_XAU!C11") == "Lease seçili: spot yok"
    v = cell(svc, "VIOP!M58")
    assert type(v) is XlError and v.code == "#N/A"                   # asked for lease, none can be computed
    put(svc, gold, {"EK_XAU!B11": "Otomatik"})
    assert cell(svc, "EK_XAU!C11") == "Spot yok → BFXFORWARD"
    assert cell(svc, "VIOP!M58") == recorded(svc, "VIOP", "M58")
    put(svc, gold, {"EK_XAU!B5": SPOT_BID, "EK_XAU!C5": SPOT_ASK, "EK_XAU!F17": "", "EK_XAU!F19": "", "EK_XAU!F22": ""})
    assert cell(svc, "EK_XAU!C11") == "Lease faizi yok → BFXFORWARD"
    assert cell(svc, "VIOP!M58") == recorded(svc, "VIOP", "M58")


def test_bfxforward_implies_a_lease_rate(svc, gold):
    """The comparison column: the lease rate at which the cost of carry gives Bloomberg's own forward."""
    for r in TARGET_ROWS:
        days, usd = cell(svc, "EK_XAU!C%d" % r), cell(svc, "EK_XAU!E%d" % r)
        mid = (cell(svc, "EK_XAU!H%d" % r) + cell(svc, "EK_XAU!I%d" % r)) / 2
        implied = cell(svc, "EK_XAU!M%d" % r)
        spot = (SPOT_BID + SPOT_ASK) / 2
        assert spot * (1 + usd / 100 * days / 360) / (1 + implied / 100 * days / 360) == pytest.approx(mid, rel=1e-12)


def test_bloomberg_quotes_feed_the_lease_curve_and_a_typed_rate_wins(svc, gold):
    """Spot, its value date and the lease rates come from Bloomberg through the ticker cells (here: the
    offline provider answers for made-up tickers); a manual rate overrides the quote of its tenor."""
    quotes = {bdp_key("XAU Curncy", "BID"): 3960.0, bdp_key("XAU Curncy", "ASK"): 3961.0,
              bdp_key("XAU Curncy", "SETTLE_DT"): "5.11.2026",
              bdp_key("TESTLEASE1M Index", "PX_LAST"): 0.30, bdp_key("TESTLEASE6M Index", "PX_LAST"): 0.60,
              bdp_key("TESTLEASE6M Index", "MID"): 0.65}
    changed = svc.provider.update(quotes)
    svc.et.call(svc._apply_market, changed)
    try:
        put(svc, gold, {"EK_XAU!B5": "", "EK_XAU!C5": "", "EK_XAU!D17": "TESTLEASE1M Index", "EK_XAU!D20": "TESTLEASE6M Index",
                        "EK_XAU!D21": "YOK9M Index"})
        assert cell(svc, "EK_XAU!B6") == 3960.0 and cell(svc, "EK_XAU!C6") == 3961.0
        assert cell(svc, "EK_XAU!B7") == cell(svc, "EK_XAU!B9") == 46331.0          # gold settles a day after USDTRY here
        assert cell(svc, "EK_XAU!E17") == 0.30 and cell(svc, "EK_XAU!E20") == 0.60
        assert type(cell(svc, "EK_XAU!E21")) is XlError and cell(svc, "EK_XAU!G21") == ""      # unknown ticker: no node
        # 1M: the typed 0.45 wins over Bloomberg's 0.30; 6M comes from Bloomberg; 3M and 12M are typed
        assert [cell(svc, "EK_XAU!G%d" % r) for r in (17, 19, 20, 22)] == [0.45, 0.55, 0.60, 0.80]
        assert cell(svc, "EK_XAU!Q16") == 4.0
        nodes = sorted((cell(svc, "EK_XAU!C%d" % r), cell(svc, "EK_XAU!G%d" % r)) for r in (17, 19, 20, 22))
        days = cell(svc, "EK_XAU!C29")
        assert days == 176.0                                                          # one day less than from the USDTRY date
        l, s = linear(nodes, days, True), linear(usd_points(svc), days, False)
        assert cell(svc, "VIOP!O58") == pytest.approx(3961.0 * (1 + s / 100 * days / 360) / (1 + l / 100 * days / 360), rel=1e-13)
        put(svc, gold, {"EK_XAU!F17": ""})
        assert cell(svc, "EK_XAU!G17") == 0.30
        put(svc, gold, {"EK_XAU!B10": "MID"})                                         # another Bloomberg field
        assert cell(svc, "EK_XAU!E20") == 0.65 and type(cell(svc, "EK_XAU!E17")) is XlError
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
        ("d1", "d2", "n", "s", "xau", "usd", "try", "lease", "xfwd", "limp", "fwd", "sp", "spd", "teo", "vbid", "vask", "dbid", "dask",
         "ibid", "iask", "sxt")))

    def v(name, col="B", user=u):
        return cell(svc, "EK_XAU!%s%d" % (col, row[name]), user)

    assert [cell(svc, "EK_XAU!%s%d" % (c, c0), u) for c in "BCD"] == [cell(svc, "VIOP!%s45" % c, u) for c in "MNO"]
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
        xfwd = (cell(svc, "EK_XAU!J%d" % target, u) + cell(svc, "EK_XAU!K%d" % target, u)) / 2
        assert v("xfwd", col) == pytest.approx(xfwd, rel=1e-13)
        assert v("teo", col) == pytest.approx(xfwd * fwd / GRAM, rel=1e-13)
        assert v("dbid", col) == pytest.approx(v("teo", col) - v("vbid", col)) and v("dask", col) == pytest.approx(v("teo", col) - v("vask", col))
        assert v("sxt", col) == pytest.approx((SPOT_BID + SPOT_ASK) / 2 * spot / GRAM, rel=1e-13)
        # the lease rate that the forward in use implies is the interpolated one
        assert v("limp", col) == pytest.approx(cell(svc, "EK_XAU!D%d" % target, u), rel=1e-9)
    # a rate of my own
    put(svc, u, {"EK_XAU!B%d" % row["try"]: 40, "EK_XAU!B%d" % row["usd"]: "4,25", "EK_XAU!B%d" % row["lease"]: "0,5"})
    n, spot, days = v("n"), v("s"), cell(svc, "EK_XAU!C27", u)
    fwd = spot * (1 + 40 / 100 / 360 * n) / (1 + 4.25 / 100 / 360 * n)
    xfwd = (SPOT_BID + SPOT_ASK) / 2 * (1 + 4.25 / 100 * days / 360) / (1 + 0.5 / 100 * days / 360)
    assert v("try") == 40.0 and v("usd") == 4.25 and v("lease") == 0.5 and v("limp") == 0.5
    assert v("fwd") == pytest.approx(fwd, rel=1e-13) and v("xfwd") == pytest.approx(xfwd, rel=1e-13)
    assert v("teo") == pytest.approx(xfwd * fwd / GRAM, rel=1e-13)
    # ... is mine alone, and blanking returns to the formula
    assert v("try", user=None) != 40.0 and v("lease", user=None) is None
    put(svc, u, {"EK_XAU!B%d" % row["try"]: "", "EK_XAU!B%d" % row["usd"]: "", "EK_XAU!B%d" % row["lease"]: ""})
    assert v("try") == v("try", user=None) and v("xfwd") == v("xfwd", user=None)


def test_gold_panels_are_on_the_viop_page(svc, gold):
    page = svc.view(None, "viop")
    ids = [p["id"] for p in page["panels"]]
    assert ids[ids.index("B11") + 1:ids.index("B11") + 6] == ["B11b", "XAU1", "XAU2", "XAU3", "XAU4"]      # after the gold tables
    panels = {p["id"]: p for p in page["panels"]}
    assert panels["XAU2"]["note"].startswith("Lease % = Manuel doluysa")              # the explanation kept in a cell
    assert panels["XAU1"]["note"].startswith("Canlıda spot ve lease Bloomberg'den gelir")
    cells = [c for row in panels["XAU1"]["data"]["rows"] for c in row]
    shared = [c for c in cells if c.get("i") == "s"]
    assert len(shared) == 6 and any(c.get("o") == list(extras.XAU_SOURCES) for c in shared)
    assert sum(1 for row in panels["XAU2"]["data"]["rows"] for c in row if c.get("i") == "s") == 14       # tickers + manual rates
    assert sum(1 for row in panels["XAU4"]["data"]["rows"] for c in row if c.get("i") == "u") == 9        # USD, TRY, lease × 3
    assert sum(1 for row in panels["XAU3"]["data"]["rows"] for c in row if c.get("t") == "Lease") == 7


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


def test_live_without_bfxforward_the_gold_tables_run_on_the_lease_curve(svc, tmp_path):
    today = svc.books["tto"].engine.clock.today()
    snapshot = {k: v for k, v in svc.provider.snapshot.items() if k[0] != "BFX"}
    snapshot.update({bdp_key("XAU Curncy", "BID"): 3960.0, bdp_key("XAU Curncy", "ASK"): 3961.0,
                     bdp_key("TESTLEASE1M Index", "PX_LAST"): 0.30, bdp_key("TESTLEASE12M Index", "PX_LAST"): 0.70})
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    live = Service(Settings(data_dir=str(tmp_path), mode="live"), provider=_Direct(snapshot), clock=clock)
    try:
        assert live.mode == "live"
        u = live.login("Canlı")["user"]
        # no lease ticker yet: the API cannot price the forward, so the tables are empty-handed (as they were)
        assert cell(live, "EK_XAU!I27") == NO_BFX == cell(live, "VIOP!M58")
        assert cell(live, "EK_XAU!C11") == "Lease faizi yok → BFXFORWARD"
        assert type(cell(live, "VIOP!M55")) is XlError
        put(live, u, {"EK_XAU!D17": "TESTLEASE1M Index", "EK_XAU!D22": "TESTLEASE12M Index"})
        assert cell(live, "EK_XAU!C11") == "Lease · 2 vade"
        days = cell(live, "EK_XAU!C27")
        nodes = sorted((cell(live, "EK_XAU!C%d" % r), cell(live, "EK_XAU!G%d" % r)) for r in (17, 22))
        usd = sorted((cell(live, "VIOP!B%d" % r), cell(live, "VIOP!F%d" % r)) for r in range(16, 26))
        l, s = linear(nodes, days, True), linear(usd, days, False)
        ask = 3961.0 * (1 + s / 100 * days / 360) / (1 + l / 100 * days / 360)
        assert cell(live, "VIOP!M58") == pytest.approx(ask, rel=1e-13)
        assert cell(live, "VIOP!M55") == pytest.approx(cell(live, "VIOP!M57") / ask * GRAM, rel=1e-13)
        assert isinstance(cell(live, "VIOP!M52"), float) and isinstance(cell(live, "Forward!I30"), float)
        assert cell(live, "EK_XAU!L27") == "Lease" and cell(live, "EK_XAU!M27") == ""          # nothing to compare with
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
