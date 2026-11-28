"""One USDTRY spot on every page (B4; the desk, 28.11.2026: "Bbg veya manual spot") - ``extras.SPOT_NAME`` and, for Borsa
Swap's workbook, ``tto/spotlink.py``.

The strip's spot (MASA!H2: the manual spot of VIOP!AA9:AA10, else Bloomberg's USDTRY bid / ask) is the one every page
reads: OIS_MAIN!D2 and Forward!F2 read Bloomberg's "TRY Curncy" MID, VİOP's spot rows USDTRY's MID / PX_LAST, Borsa Swap
USDTRY's PX_LAST.  The checks: every cell of the TRY workbook against the workbook without the addition - only the spot
cells and what reads them move; the curves (Motor's bootstrap, the OIS quotes, the offshore curve) and the strip keep their
bits; the cells read the strip; a manual spot typed reaches every page and Borsa's book, live; a spot typed on the Forward
page stays that user's."""
from __future__ import annotations

import os

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto.books import Book, formula_text, remove_sheets, snapshot_today
from tto.marketdata.replay import ReplayProvider
from tto.xl.engine import Clock
from tto.xl.model import COLS, Model, parse_a1, parse_range
from tto.xl.tokenizer import index_to_col

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _book(with_spot: bool) -> Book:
    """The TRY workbook in replay with every addition, or every addition but the one spot (the workbook as v2 built it)."""
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    builders = ex._BUILDERS["tto"]
    try:
        if not with_spot:
            ex._BUILDERS["tto"] = tuple(b for b in builders if b[0] != ex.SPOT_NAME)
        assert ex.apply("tto", model) == []
    finally:
        ex._BUILDERS["tto"] = builders
    today = snapshot_today(Model.load(os.path.join(ROOT, "models", "tto.json.gz")))
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)                          # type: ignore[assignment]
    return Book("tto", "TRY masa", model, provider=ReplayProvider(label="workbook"), clock=clock, replay=True)


@pytest.fixture(scope="module")
def books():
    return _book(True), _book(False)


def at(book: Book, ref: str):
    si, rc = book.cell(ref)
    return book.engine.shared.get(si, *divmod(rc, COLS))


def same(a, b) -> bool:
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return a == b or (a != a and b != b)
    if hasattr(a, "rows"):
        return len(a.rows) == len(b.rows) and all(len(x) == len(y) and all(same(p, q) for p, q in zip(x, y))
                                                  for x, y in zip(a.rows, b.rows))
    return a == b


def moved(new: Book, old: Book):
    """Every cell of the workbook (formulas and constants of every sheet) whose value differs between the two."""
    out = []
    for sa, sb in zip(new.model.sheets, old.model.sheets):
        assert sa.name == sb.name
        for rc in sorted(set(sa.fml) | set(sa.consts) | set(sb.fml) | set(sb.consts)):
            r, c = divmod(rc, COLS)
            if not same(new.engine.shared.get(sa.index, r, c), old.engine.shared.get(sb.index, r, c)):
                out.append((sa.index, rc))
    return out


def inside(book: Book, sheet: str, rng: str):
    si = book.model.sheet_index[sheet]
    r1, c1, r2, c2 = parse_range(rng)
    return {(si, r * COLS + c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}


# ============================================================================== the whole workbook, before and after
def test_only_what_reads_the_spot_moves_and_the_curves_keep_their_bits(books):
    """Every cell of every sheet: the cells that move are the spot cells and what reads them (the reverse reference index's
    downstream of them) - nominals and $DV01s, forwards, VİOP's implied rates, the gold calculator; Motor (Bootstrap),
    the OIS quotes, the offshore curve, the USD OIS and the strip itself are the same bits."""
    new, old = books
    spots = [new.cell(ref) for ref in ex.spot_cells()]
    diff = moved(new, old)
    assert diff
    allowed = new.engine.ref_index().downstream(spots) | set(spots)
    stray = [new.ref(si, rc) for si, rc in diff if (si, rc) not in allowed]
    assert stray == []
    sheets = {new.model.sheets[si].name for si, _ in diff}
    assert sheets <= {"OIS_MAIN", "Forward", "VIOP", "MASA", "C & R", "EK_FWD", "EK_BULK", "EK_XAU", "Calculators",
                      "DİBS RV", "Manuel Tahvil", "TM_OIS"}, sheets
    assert {"OIS_MAIN", "Forward", "VIOP", "C & R"} <= sheets           # (nominals, forwards, VİOP, carry $; TOPLU FORWARD
    #                                                                      reads it too, but has no row typed in the recording)
    # the curves and the strip: not one bit
    still = (inside(new, "Motor", "A1:BZ4500") | inside(new, "OIS_MAIN", "B9:B26") | inside(new, "Forward", "AJ122:AN145")
             | inside(new, "Forward", "C123:K134") | inside(new, "Forward", "F4:K22") | inside(new, "Forward", "U4:AE29")
             | inside(new, "MASA", "F2:N2") | inside(new, "VIOP", "L99:L100"))
    assert not still & set(diff)
    # what each spot cell reads now: the strip's mid, the manual spot's or Bloomberg's bid / ask
    strip = at(new, "MASA!H2")
    assert strip == (at(new, "VIOP!L99") + at(new, "VIOP!L100")) / 2
    assert {at(new, ref) for ref in ex.spot_cells()} == {strip}
    assert at(old, "OIS_MAIN!D2") != strip                  # (the file's "TRY Curncy" MID: 49,9977, the strip 49,99725)


def test_the_cells_read_the_strip_and_ask_bloomberg_for_nothing_new(books):
    new, _ = books
    for ref in ex.spot_cells():
        si, rc = new.cell(ref)
        assert formula_text(new, si, rc) == ex.SPOT_FORMULA, ref
    # the TRY workbook asks Bloomberg for no USDTRY mid any more: the strip's bid / ask and the settle dates are what is left
    texts = [formula_text(new, s.index, rc) for s in new.model.sheets for rc in s.fml]
    assert not [t for t in texts if '"TRY Curncy","MID"' in t or '"USDTRY Curncy","MID"' in t]
    assert sum('"USDTRY Curncy","BID"' in t for t in texts) == 1 and sum('"USDTRY Curncy","ASK"' in t for t in texts) == 1


# ============================================================================== Borsa Swap's book
def test_borsa_swap_reads_the_strip(service):
    """Borsa's spot (Sheet1!AD18) is the strip's: the service writes it into EK_SPOT!B2 before Borsa is calculated; the BIST
    swaps' implied TRY rates are worked out from it (U = spot + points, V = (U / spot ·(1 + USD·g/360) − 1)·360/g)."""
    ans = service.view(None, "borsa")
    strip = cell(service, "MASA!H2")
    assert cell(service, "%s!%s" % (ex.SPOT_SHEET, ex.SPOT_CELL), book="borsa") == strip
    assert cell(service, "Sheet1!AD18", book="borsa") == strip
    mkt = next(p for p in ans["panels"] if p["id"] == "mkt")["data"]
    row = dict(zip(mkt["c"], mkt["rows"][mkt["r"].index(18)]))
    shown = service.cell_info(None, "tto", "MASA!H2", "tr")["cell"]["t"]
    assert row["AC"]["t"] == ex.BORSA_SPOT_CAPTION and row["AD"]["t"] == shown            # (the strip's four decimals)
    pts = [(r, cell(service, "Sheet1!R%d" % r, book="borsa")) for r in range(4, 60)]
    r, p = next((r, p) for r, p in pts if type(p) is float)
    assert cell(service, "Sheet1!U%d" % r, book="borsa") == pytest.approx(strip + p / 10000, rel=1e-12)


# ============================================================================== a manual spot, live
def test_a_manual_spot_reaches_every_page(service, tmp_path):
    """Live, as on the desk (offline the spot cells' Bloomberg values are frozen): a manual spot typed in the strip's box is
    every page's spot - OIS · PPK's, the Forward page's, VİOP's rows and Borsa Swap's -; cleared, Bloomberg's again; a spot a
    user typed on the Forward page stays theirs."""
    from tto.config import Settings
    from tto.marketdata.base import bdp_key
    from tto.service import Service

    class Direct(ReplayProvider):
        """A connected Bloomberg that answers at once."""
        live = True

        def _get(self, key):
            v = self.snapshot.get(key)
            return "#N/A N/A" if v is None else v

        get_bdp = get_bdh = get_bds = _get

    today = service.books["tto"].engine.clock.today()
    snapshot = {k: v for k, v in service.provider.snapshot.items() if k[0] not in ("BFX", "RT")}
    snapshot.update({bdp_key("USDTRY Curncy", "BID"): 50.36, bdp_key("USDTRY Curncy", "ASK"): 50.37,
                     bdp_key("TRY Curncy", "MID"): 50.5, bdp_key("USDTRY Curncy", "MID"): 50.6,
                     bdp_key("USDTRY Curncy", "PX_LAST"): 50.7})
    clock = Clock(today + 0.5)
    clock.today = lambda: float(today)
    svc = Service(Settings(data_dir=str(tmp_path), mode="live", history=False), provider=Direct(snapshot), clock=clock)
    try:
        u = svc.login("Tek Spot")["user"]
        pages = ["OIS_MAIN!D2", "Forward!F2", "VIOP!M11", "VIOP!X23", "VIOP!M50", "VIOP!U50", "VIOP!M75", "VIOP!X88"]

        def spots():
            svc.view(None, "borsa")
            return [cell(svc, ref) for ref in pages] + [cell(svc, "Sheet1!AD18", book="borsa")]

        assert spots() == [pytest.approx(50.365, abs=1e-12)] * 9               # Bloomberg's bid / ask mid, not TRY / USDTRY MID
        res = svc.set_inputs(u, "tto", [{"ref": "VIOP!AA9", "value": "50,3667"}, {"ref": "VIOP!AA10", "value": "50,3688"}], lang="tr")
        assert res["errors"] == []
        assert spots() == [pytest.approx((50.3667 + 50.3688) / 2, abs=1e-12)] * 9
        # (the pages that read them follow: OIS · PPK's nominal of 1M at the new spot, the Forward page's outrights)
        assert cell(svc, "Forward!O32") == cell(svc, "MASA!H2") and cell(svc, "EK_FWD!F45") == cell(svc, "MASA!H2")
        # a spot of one's own on the Forward page: theirs alone, Delete brings the strip's back
        svc.set_inputs(u, "tto", [{"ref": "Forward!F2", "value": "51"}])
        assert cell(svc, "Forward!F2", u) == 51.0 and cell(svc, "Forward!F2") == cell(svc, "MASA!H2")
        svc.set_inputs(u, "tto", [{"ref": "Forward!F2", "value": ""}])
        assert cell(svc, "Forward!F2", u) == cell(svc, "MASA!H2")
        res = svc.set_inputs(u, "tto", [{"ref": "VIOP!AA9", "value": ""}, {"ref": "VIOP!AA10", "value": ""}])
        assert res["errors"] == []
        assert spots() == [pytest.approx(50.365, abs=1e-12)] * 9
    finally:
        svc.stop()


def test_a_workbook_without_the_strip_is_left_as_it_is(tmp_path):
    """The addition checks what it reads: a TRY workbook whose spot cells are no Bloomberg MID (or whose strip reads no
    manual spot) keeps them, and only this addition is left out; Borsa's book without its spot formula keeps Bloomberg's."""
    model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    ex.SheetBuilder(model, "VIOP").set("M11", 49.5)
    left = ex.apply("tto", model)
    assert left == [ex.SPOT_NAME + ": VIOP!M11 bir formül değil"]
    assert ex.formula_of(model, "OIS_MAIN", "D2") == '_xll.BDP("TRY Curncy","MID")'
    borsa = Model.load(os.path.join(ROOT, "models", "borsa.json.gz"))
    ex.SheetBuilder(borsa, "Sheet1").patch("AD18", "=50")
    assert ex.apply("borsa", borsa) == [ex.SPOT_SHEET + ': Sheet1!AD18 beklenen formül değil ("USDTRY Curncy","PX_LAST" yok)']
    assert ex.SPOT_SHEET not in borsa.sheet_index
    svc = make_service(tmp_path)
    try:
        assert svc.spotlink.available and svc.spotlink.borsa is svc.books["borsa"]
    finally:
        svc.stop()
