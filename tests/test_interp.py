"""Eğri interpolasyonu (18.11.2026, "Ayarlardan da PPK basamak kısmını, tüm interpolasyonları değiştirebiliyor olmam
lazım"): each user reads the TRY curves between their quoted tenors as Bootstrap (Murex) - today's curve, the default - or
PPK basamak (tto/ppkcurve.py), at the source: Motor's par rates of its nodes, the offshore curve's names and the ASW book's
curve of today follow the user's own choice (``extras.INTERP_SHEET``), the PPK cells filled by the service from the
calculation on Bootstrap (tto/interp.py).

On Bootstrap nothing moves (the IFs are lazy: a Bootstrap value does not even read the PPK cells, so writing them
recomputes nothing); on PPK Motor's nodes are the PPK curve's discount factors, every quoted tenor's par its quote, the
FRA list's market its own PPK column, a forward between quotes moves and one at a quote does not; one user on PPK, another
on Bootstrap, each sees their own; Trades follow the viewer's curve with the desk's snapshots kept on both; Günlük
İşlemler, the alarms and whatever runs for nobody stay on Bootstrap."""
from __future__ import annotations

import datetime as dt
import math

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell
from tto import borsaspread as bsp
from tto import extras as ex
from tto import interp as ip
from tto import ppkcurve as pk
from tto import tradebook as tbm
from tto import tradevalue as tv
from tto.render import calc_value
from tto.server import create_app
from tto.xl.model import COLS, parse_a1, parse_range
from tto.xl.tokenizer import to_template
from tto.xl.values import serial_to_date


def _calc(svc, user, book="tto"):
    return svc.et.call(svc._calc, user, svc.books[book])


def _get(svc, calc, ref, book="tto"):
    b = svc.books[book]
    si, rc = b.cell(ref)
    return svc.et.call(calc.get, si, *divmod(rc, COLS))


def _curves(svc, user=None):
    """The PPK curves (ppkcurve.read) off a user's calculation (nobody: the desk's)."""
    b = svc.books["tto"]
    idx = b.model.sheet_index

    def run():
        calc = svc._calc(user, b)
        return pk.read(lambda s, r, c: calc.get(idx[s], r, c))

    return svc.et.call(run)


@pytest.fixture(scope="module")
def users(module_service):
    svc = module_service
    names = {k: svc.login(v)["user"] for k, v in (("ppk", "Eğri PPK Ali"), ("boot", "Eğri Boot Banu"), ("own", "Eğri Kendi Can"))}
    svc.set_interp(names["ppk"], "ppk")
    return names


# ================================================================================================== the workbook
def test_the_switch_is_in_both_workbooks_and_motor_and_the_offshore_names_follow_it(module_service):
    svc = module_service
    tto, asw = svc.books["tto"], svc.books["asw"]
    assert not [x for x in tto.left_out + asw.left_out if x.startswith((ex.INTERP_NAME, ex.INTERP_ASW_NAME))]
    assert ex.INTERP_SHEET in tto.model.sheet_index and ex.INTERP_SHEET in asw.model.sheet_index
    for r in range(ex.INTERP_NODES[0] + 1, ex.INTERP_NODES[1] + 1):
        text = ex.formula_of(tto.model, "Motor", "F%d" % r)
        assert text.startswith("IF(EK_INTERP!$B$3=1,EK_INTERP!$F$%d," % (r - ex.INTERP_SHIFT)) and "$B$306:$B$321" in text
    from tto.xl.unparse import to_a1
    for name, col in ex.INTERP_OFF_COLS.items():
        assert to_a1(tto.model.names[name], 1, 1) == "IF(EK_INTERP!$B$4=1,EK_INTERP!$%s$%d:$%s$%d,%s)" % (
            col, ex.INTERP_OFF_FIRST, col, ex.INTERP_OFF_LAST, ex.INTERP_OFF_RANGES[name])
    assert ex.formula_of(asw.model, "ASW", "BZ65").startswith("IF(EK_INTERP!$B$3=1,EK_INTERP!$C$17,LN((1-")
    # the choice: a personal input of the TRY workbook, Bootstrap by default
    d = tto.inputs[tto.cell("EK_INTERP!B2")]
    assert d.scope == "user" and d.options == list(ex.INTERP_CHOICES)
    assert cell(svc, "EK_INTERP!B2") == ex.INTERP_BOOT and cell(svc, "EK_INTERP!B3") == 0.0


def _original(svc, calc, sheet, addr):
    """The cell's own formula (what the switch wraps), evaluated in ``calc``."""
    b = svc.books["tto"]
    text = ex.formula_of(b.model, sheet, addr)
    head = "IF(EK_INTERP!$B$3=1,EK_INTERP!$F$%d," % (int(addr[1:]) - ex.INTERP_SHIFT)
    assert text.startswith(head)
    own = text[len(head):-1]
    r, c = divmod(parse_a1(addr), COLS)
    fn = b.engine.compiler.compile_expression(to_template(own, r, c))
    return svc.et.call(calc_value, calc, fn, b.model.sheet_index[sheet], r, c)


def test_on_bootstrap_every_node_is_its_own_formula_and_the_names_their_own_ranges(module_service, users):
    """The workbook additions fit with nothing moved: Motor's par rates are their own formulas' values to the bit, the
    offshore names read the Forward sheet's ranges, the nodes carry no bit of the PPK cells (they never read them)."""
    svc = module_service
    b = svc.books["tto"]
    shared, banu = b.engine.shared, _calc(svc, users["boot"])
    assert banu is shared                                         # (nothing of her own: everybody's calculation)
    for r in range(89, 131):
        own = _original(svc, shared, "Motor", "F%d" % r)
        got = _get(svc, shared, "Motor!F%d" % r)
        assert got == own and type(got) is type(own)
    for name, rng in ex.INTERP_OFF_RANGES.items():
        mine = svc.et.call(bsp._named, b, shared, name)
        sheet, addr = rng.split("!")
        si = b.model.sheet_index[sheet]
        r1, c1, r2, c2 = parse_range(addr.replace("$", ""))
        assert mine == [v for row in svc.et.call(shared.get_range, si, r1, c1, r2, c2) for v in row]
    eng = b.engine
    ppk_bits = eng._bits[("group", ip.GROUP_OIS)] | eng._bits[("group", ip.GROUP_OFF)]
    for ref in ("Motor!G130", "Motor!O178", "MASA!BL179", "OIS_MAIN!B336", "DV01_RISK!J6"):
        si, rc = b.cell(ref)
        svc.et.call(shared.get, si, *divmod(rc, COLS))
        assert not (shared.maskd[si].get(rc, 0) & ppk_bits), ref


def test_refreshing_the_ppk_cells_recomputes_nothing_on_bootstrap(module_service, users):
    """The desk's PPK cells written again (the market moved): nothing of the shared calculation is computed again, a
    Bootstrap user's page stays as made; only a PPK user's calculation follows."""
    svc = module_service
    b = svc.books["tto"]
    svc.view(users["boot"], "ois")
    _get(svc, _calc(svc, users["ppk"]), "Motor!G130")
    shared = b.engine.shared
    page = svc.view(users["boot"], "ois")
    ppk_calc = _calc(svc, users["ppk"])
    before = _get(svc, ppk_calc, "Motor!G130")

    def nudge():
        st = svc.interp._shared["tto"]
        moved = {cell_: (v * (1.0 + 1e-6) if type(v) is float else v) for cell_, v in st["values"].items()}
        ev = shared.evals
        changed = b.engine.set_inputs(moved, counted=False)
        return changed, shared.evals - ev, b.engine.input_changes

    inputs = b.engine.input_changes
    changed, evals, inputs_after = svc.et.call(nudge)
    assert changed and evals == 0 and inputs_after == inputs        # (uncounted: no change of the desk's inputs)
    svc.bump(market=True)                                           # (as the market loop tells the pages)
    ev = shared.evals
    again = svc.view(users["boot"], "ois", since=page["gen"])
    assert shared.evals == ev and again.get("unchanged")            # (checked: nothing it read changed - nothing made)
    assert _get(svc, ppk_calc, "Motor!G130") != before            # (the PPK user's follows the cells)
    svc.et.call(lambda: svc.interp._shared.clear())                 # (made again from the market, as it is)
    _calc(svc, users["ppk"])
    assert _get(svc, _calc(svc, users["ppk"]), "Motor!G130") == pytest.approx(before, rel=1e-14)


# ================================================================================================== on PPK
def test_on_ppk_motor_s_nodes_are_the_ppk_discount_factors_and_every_quote_comes_back(module_service, users):
    svc = module_service
    ali, banu = _calc(svc, users["ppk"]), _calc(svc, users["boot"])
    assert _get(svc, ali, "EK_INTERP!B3") == 1.0 and _get(svc, ali, "EK_INTERP!B4") == 1.0
    cv = _curves(svc)
    ppk = cv["ppk"]
    moved = 0
    for r in range(89, 131):
        days = _get(svc, ali, "Motor!C%d" % r)
        g = _get(svc, ali, "Motor!G%d" % r)
        assert g == pytest.approx(ppk.df(days), rel=1e-13, abs=0), r
        moved += abs(g - _get(svc, banu, "Motor!G%d" % r)) > 1e-9
    assert moved >= 20                                              # (15M, 21M, 27M ... and what follows from them)
    # every quoted tenor's par comes back on Motor's own grid (one period up to 3M, then quarterly from the 3M node)
    for q in cv["quotes"]:
        pays = q.pays
        rows = [r for r in range(89, 131) if _get(svc, ali, "Motor!C%d" % r) in pays]
        assert len(rows) == len(pays)
        dfs = [_get(svc, ali, "Motor!G%d" % r) for r in rows]
        par = (1.0 - dfs[-1]) / sum(a * d for a, d in zip(q.accruals, dfs))
        assert par == pytest.approx(q.rate, abs=1e-10), q.name
    # up to 1Y every node is a quote (or its coupon): the same discount factors as Bootstrap
    for r in range(89, 95):
        assert _get(svc, ali, "Motor!G%d" % r) == pytest.approx(_get(svc, banu, "Motor!G%d" % r), rel=1e-13)


def _fra_row(svc, calc, m1, m2):
    """The FRA list's row of an ``m1`` × ``m2`` FRA (its months: OIS_MAIN!M / N)."""
    for r in range(svc.FRA_ALL[0], svc.FRA_ALL[1] + 1):
        if (_get(svc, calc, "OIS_MAIN!M%d" % r), _get(svc, calc, "OIS_MAIN!N%d" % r)) == (float(m1), float(m2)):
            return r
    raise AssertionError("no %dx%d in the FRA list" % (m1, m2))


def test_the_fra_list_s_market_is_its_own_ppk_column_on_ppk(module_service, users):
    """OIS · PPK's FRA list: on PPK the market of 12x15 is the list's own "PPK basamak" column (the same quarterly calendar
    and day count); on Bootstrap they differ (12x15 lies between two quotes) - and the page says which the market is."""
    svc = module_service
    ali, banu = _calc(svc, users["ppk"]), _calc(svc, users["boot"])
    cv = _curves(svc)
    want = pk.fra(cv["ppk"], cv["grid"], 12, 15)
    r = _fra_row(svc, ali, 12, 15)
    assert _get(svc, ali, "OIS_MAIN!B%d" % r) == pytest.approx(want, abs=1e-12)
    assert abs(_get(svc, banu, "OIS_MAIN!B%d" % r) - want) > 1e-5
    page = svc.view(users["ppk"], "ois")
    for p in page["panels"]:
        d = p.get("data") or {}
        if "PPK basamak" in (d.get("c") or []) and r in (d.get("r") or []):
            row = d["rows"][d["r"].index(r)]
            assert row[d["c"].index("PPK basamak")]["v"] == pytest.approx(row[d["c"].index("B")]["v"], abs=1e-12)
            assert "PPK basamak" in d["rows"][d["r"].index(svc.FRA_ALL_HEAD)][d["c"].index("B")].get("tip", "")
            break
    else:
        raise AssertionError("the FRA list's PPK column is not on the page")


def _spot(svc, calc):
    return serial_to_date(_get(svc, calc, "Forward!I2"))


def test_a_forward_page_try_rate_between_quotes_moves_and_one_at_a_quote_does_not(module_service, users):
    """The Forward page's TRY rates by tenor (EK_FWD 'TRY FAİZLERİ VADELERE GÖRE'): a free date between the 1Y and 18M
    quotes reads the OIS curve where PPK and Bootstrap part; the 1Y row (a quote) is the same both ways.  Offshore (MASA's
    broken date): a date between two offshore quotes moves, the 1M quote's own date does not."""
    svc = module_service
    ali, banu = users["ppk"], users["boot"]
    spot = _spot(svc, _calc(svc, banu))
    free = (spot + dt.timedelta(days=455)).strftime("%d.%m.%Y")
    for u in (ali, banu):
        res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B93", "value": free}])
        assert not res["errors"]
    a, b = _calc(svc, ali), _calc(svc, banu)
    assert abs(_get(svc, a, "EK_FWD!E93") - _get(svc, b, "EK_FWD!E93")) > 1e-4          # (%: > 0.01 bp)
    assert _get(svc, a, "EK_FWD!E90") == pytest.approx(_get(svc, b, "EK_FWD!E90"), abs=1e-10)       # 1Y
    # offshore (MASA's broken date, MASA!C171): a date between the 1Y and 2Y offshore quotes moves, the 1M quote's own
    # date (FX spot + its days: Forward!G10) does not
    ref = "MASA!C171"
    fx_spot, one_m = _get(svc, b, "Forward!I2"), _get(svc, b, "Forward!G10")
    for when, moves in (((spot + dt.timedelta(days=500)).strftime("%d.%m.%Y"), True),
                        (serial_to_date(fx_spot + one_m).strftime("%d.%m.%Y"), False)):
        for u in (ali, banu):
            assert not svc.set_inputs(u, "tto", [{"ref": ref, "value": when}])["errors"]
        a, b = _calc(svc, ali), _calc(svc, banu)
        fa, fb = _get(svc, a, "MASA!F175"), _get(svc, b, "MASA!F175")           # simple ACT/360 to the date
        if moves:
            assert abs(fa - fb) > 1e-5, when
        else:
            assert fa == pytest.approx(fb, abs=1e-10), when
    for u in (ali, banu):
        svc.reset_inputs(u, "tto", ["EK_FWD!B93", ref])


def test_the_asw_book_s_curve_of_today_follows_the_choice(module_service, users):
    svc = module_service
    a, b = _calc(svc, users["ppk"], "asw"), _calc(svc, users["boot"], "asw")
    assert b is svc.books["asw"].engine.shared and a is not b
    assert _get(svc, a, "EK_INTERP!B2", "asw") == ex.INTERP_PPK and _get(svc, a, "EK_INTERP!B3", "asw") == 1.0
    # a quoted node (3M) the same, one between quotes (15M) on the PPK curve - and the history rows stay as they are
    assert _get(svc, a, "ASW!BV65", "asw") == pytest.approx(_get(svc, b, "ASW!BV65", "asw"), abs=1e-12)
    assert abs(_get(svc, a, "ASW!BZ65", "asw") - _get(svc, b, "ASW!BZ65", "asw")) > 1e-6
    assert _get(svc, a, "ASW!BZ66", "asw") == _get(svc, b, "ASW!BZ66", "asw")


def test_a_ppk_user_and_a_bootstrap_user_each_see_their_own_and_the_desk_s_stays(module_service, users):
    svc = module_service
    b = svc.books["tto"]
    shared = b.engine.shared
    assert _calc(svc, users["boot"]) is shared
    node = "Motor!G95"                                              # (15M)
    desk = _get(svc, shared, node)
    assert _get(svc, _calc(svc, users["boot"]), node) == desk
    assert abs(_get(svc, _calc(svc, users["ppk"]), node) - desk) > 1e-6
    # the header says so on PPK only (and nothing new on Bootstrap)
    ha, hb = svc.header(users["ppk"]), svc.header(users["boot"])
    assert ha["interp"]["label"] == "Eğri: PPK basamak" and ha["interp"]["on"] is True
    assert "interp" not in hb and set(hb) == {"items", "gen", "as"}
    st = svc.interp_settings(users["ppk"])
    assert st["mode"] == "ppk" and st["on"] and st["stats"]["made"] >= 1
    assert svc.interp_settings(users["boot"])["mode"] == "boot"


def test_a_ppk_user_s_own_quote_is_repriced_by_their_own_ppk_curve(module_service, users):
    """A PPK user who types their own 2Y quote ("Elle değer") gets PPK cells of their own, calibrated to it; the desk's
    stay as they are (another PPK user's numbers do not move)."""
    svc = module_service
    can = users["own"]
    svc.set_interp(can, "ppk")
    b = svc.books["tto"]
    row = next(r for r in range(306, 322) if _get(svc, b.engine.shared, "Motor!A%d" % r) == 24.0)
    quote = _get(svc, b.engine.shared, "Motor!B%d" % row)
    mine = quote + 0.0025
    res = svc.set_inputs(can, "tto", [{"ref": "Motor!B%d" % row, "value": mine}], allow_adhoc=True)
    assert not res["errors"]
    calc = _calc(svc, can)
    assert svc.books["tto"].engine.derived.get(can)                 # (their own PPK cells)
    days = [_get(svc, calc, "Motor!C%d" % r) for r in range(91, 99)]       # 3M … 2Y
    dfs = [_get(svc, calc, "Motor!G%d" % r) for r in range(91, 99)]
    acc = [days[0] / 365.0] + [(y - x) / 365.0 for x, y in zip(days, days[1:])]
    assert (1.0 - dfs[-1]) / sum(a * d for a, d in zip(acc, dfs)) == pytest.approx(mine, abs=1e-10)
    # the other PPK user's 2Y is still the desk's quote
    ali = _calc(svc, users["ppk"])
    dfs = [_get(svc, ali, "Motor!G%d" % r) for r in range(91, 99)]
    assert (1.0 - dfs[-1]) / sum(a * d for a, d in zip(acc, dfs)) == pytest.approx(quote, abs=1e-10)
    # "Girdilerimi sıfırla": the choice goes with the rest - back to everybody's calculation, in both books
    svc.reset_inputs(can, "tto")
    assert _calc(svc, can) is b.engine.shared and _calc(svc, can, "asw") is svc.books["asw"].engine.shared
    assert not b.engine.derived.get(can) and not svc.books["asw"].engine.derived.get(can)
    assert "interp" not in svc.header(can)


def test_guenluk_islemler_prices_on_bootstrap_whatever_the_setting(module_service, users):
    """Günlük İşlemler keeps the desk's records: its quotes and mids are Bootstrap's for a PPK user too (the FRA's PPK
    mid beside it, as before)."""
    svc = module_service
    a, b = svc.ois_market(users["ppk"]), svc.ois_market(users["boot"])
    assert [(t["tenor"], t["par"], t["annuity"]) for t in a["tenors"]] == [(t["tenor"], t["par"], t["annuity"]) for t in b["tenors"]]
    assert a["mpc"] == b["mpc"]
    fra = {"strategy": "fra", "side": "RECEIVE", "start_months": 12.0, "end_months": 15.0, "level": "35,10"}
    qa, qb = svc.quote_ois(users["ppk"], fra), svc.quote_ois(users["boot"], fra)
    shared = svc.books["tto"].engine.shared
    r = _fra_row(svc, shared, 12, 15)
    assert qa["info"]["market"] == qb["info"]["market"] == pytest.approx(_get(svc, shared, "OIS_MAIN!B%d" % r), abs=1e-12)
    assert qa["info"]["market_ppk"] == pytest.approx(qb["info"]["market_ppk"], abs=1e-12)
    assert abs(qa["info"]["market_ppk"] - qa["info"]["market"]) > 1e-5


# ================================================================================================== Trades
def _ois(**kw):
    d = {"scope": "desk", "product": "ois", "structure": "outright", "trade_date": "2026-11-17", "settle_date": "2026-11-18",
         "side": "receive", "end_date": "15M", "notional": "100m", "price": "35,50"}
    d.update(kw)
    return d


def test_trades_follow_each_viewer_s_curve_from_one_desk_snapshot(module_service, users):
    """A desk trade between quotes (a 15M receiver): "MTM yenile" by the PPK user keeps both curves; the PPK user reads
    PPK, the Bootstrap user Bootstrap - from the same snapshot, either refreshing; a snapshot without PPK (kept before)
    shows as Bootstrap and says so; the coupons the same way."""
    svc = module_service
    book = svc.tradebook
    ali, banu = users["ppk"], users["boot"]
    tid = book.add(banu, _ois())["id"]
    row = svc.store.tb_get(tid)
    boot = svc.et.call(lambda: tv.value(book.for_value(row), tv.market(svc)))["mtm"]
    ppk = svc.et.call(lambda: tv.value(book.for_value(row), tv.market(svc, "ppk")))["mtm"]
    assert abs(ppk - boot) > 100.0                                   # (TL on 100m: the 15M node)
    assert svc.et.call(lambda: tv.market(svc, "ppk").curve) == "ppk"
    mine = book.mtm(ali, "desk")
    assert mine["curve"] == "ppk" and mine["values"][str(tid)]["mtm"] == pytest.approx(ppk, rel=1e-9)
    hers = book.listing(banu, "desk")["mtm"]
    assert hers["curve"] == "boot" and hers["values"][str(tid)]["mtm"] == pytest.approx(boot, rel=1e-9)
    assert hers["curve_text"] == "Bootstrap (Murex)" and book.listing(banu, "desk")["curve"] == "boot"
    book.mtm(banu, "desk")                                           # (refreshed by the Bootstrap user: both again)
    assert book.listing(ali, "desk")["mtm"]["values"][str(tid)]["mtm"] == pytest.approx(ppk, rel=1e-9)
    # a snapshot kept on Bootstrap only: shown so, and said
    with book._lock:
        book._mtm[("desk", "")]["curves"].pop("ppk")
    old = book.listing(ali, "desk")["mtm"]
    assert old["curve"] == "boot" and "MTM yenile" in old["curve_note"]
    assert old["values"][str(tid)]["mtm"] == pytest.approx(boot, rel=1e-9)
    # the coupons on the viewer's curve
    ca, cb = book.coupons(ali, tid), book.coupons(banu, tid)
    assert (ca["curve"], cb["curve"]) == ("ppk", "boot")
    # the switch: off, everybody's Trades on Bootstrap
    tbm.FOLLOW_CURVE = False
    try:
        assert book.curve_of(ali) == "boot" and book.mtm(ali, "desk")["values"][str(tid)]["mtm"] == pytest.approx(boot, rel=1e-9)
    finally:
        tbm.FOLLOW_CURVE = True
    book.remove(banu, tid)


def test_the_daily_close_is_kept_on_both_curves_and_a_trade_s_alarm_reads_bootstrap(module_service, users):
    svc = module_service
    book = svc.tradebook
    ali = users["ppk"]
    tid = book.add(ali, _ois(target="30,00", stop="40,00"))["id"]
    row = svc.store.tb_get(tid)
    day = "2026-11-17"
    assert svc.store.tb_close_day(day) is None and book.take_close(day)["valued"] >= 1
    kept = svc.store.tb_closes([tid])[tid][day]
    assert kept["ok"] and kept["ppk"]["ok"] and abs(kept["ppk"]["mtm"] - kept["mtm"]) > 100.0
    # each viewer's P&L counts from the close of their curve (the Bootstrap user's from the Bootstrap one)
    ppk_snap, boot_snap = tbm.on_curve(kept, "ppk"), tbm.on_curve(kept, "boot")
    assert ppk_snap[1] and ppk_snap[0]["mtm"] == kept["ppk"]["mtm"] and ppk_snap[0]["fp"] == kept["fp"]
    assert boot_snap == (kept, True) and tbm.on_curve({"mtm": 1.0}, "ppk") == ({"mtm": 1.0}, False)
    # the level its alarms read: Bootstrap's, whoever entered it and whatever their setting
    book.refresh_levels(force=True)
    level, _ = book.level_value(tid)
    want = svc.et.call(lambda: tbm.level_now(row, book._value(book.for_value(row), tv.market(svc))))
    other = svc.et.call(lambda: tbm.level_now(row, book._value(book.for_value(row), tv.market(svc, "ppk"))))
    assert level == pytest.approx(want, abs=1e-12) and abs(other - want) > 1e-6
    book.remove(ali, tid)


# ================================================================================================== over HTTP (last: it stops the service)
def test_ayarlar_sets_the_choice_and_the_header_says_it(module_service):
    svc = module_service
    with TestClient(create_app(svc)) as c:
        h = auth(svc, "Eğri HTTP Deniz")
        got = c.get("/api/interp", headers=h).json()
        assert got["available"] and got["mode"] == "boot" and [x["id"] for x in got["choices"]] == ["boot", "ppk"]
        assert "interp" not in c.get("/api/header", headers=h).json()
        got = c.post("/api/interp", json={"mode": "ppk"}, headers=h).json()
        assert got["mode"] == "ppk" and got["on"] and got["status"].startswith("PPK basamak")
        assert c.get("/api/header", headers=h).json()["interp"]["label"] == "Eğri: PPK basamak"
        assert c.post("/api/interp", json={"mode": "nope"}, headers=h).status_code == 400
        assert c.post("/api/interp", json={"mode": "boot"}, headers=h).json()["mode"] == "boot"
        assert "interp" not in c.get("/api/header", headers=h).json()
