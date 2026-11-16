"""Formulas typed into the input cells of the pages (``tto/inputformula.py``): ``=C60+7`` in a value date - its result
is the input's value, evaluated again whenever what it reads changes; a personal input's formula is its user's, a shared
one everybody's; refused with the reason (Bloomberg, a cycle, one that cannot be read, a cell that takes no formula);
removed with the input; kept across a restart.  (Pointing at cells with the mouse, the ƒ on screen, F2: the browser
test's.)"""
import datetime as dt
import logging

import pytest
from starlette.testclient import TestClient

from conftest import auth, cell, make_service
from tto import calc as calc_mod
from tto.inputformula import KEPT
from tto.marketdata.base import bdp_key
from tto.server import create_app
from tto.store import Store
from tto.xl.errors import E_CALC
from tto.xl.values import date_to_serial


def login(svc, name):
    return svc.login(name)["user"]


def put(svc, user, ref, value, **kw):
    return svc.set_inputs(user, kw.pop("book", "tto"), [{"ref": ref, "value": value}], **kw)


def mark(svc, user, view, ref, show_hidden=False):
    """The cell ``ref`` as the page ``view`` draws it for ``user`` (the first table that shows it)."""
    sheet, _, addr = ref.rpartition("!")
    col = "".join(ch for ch in addr if ch.isalpha())
    row = int("".join(ch for ch in addr if ch.isdigit()))
    for p in svc.view(user, view, show_hidden)["panels"]:
        d = p.get("data") or {}
        if d.get("sheet") == sheet and row in (d.get("r") or []) and col in (d.get("c") or []):
            return d["rows"][d["r"].index(row)][d["c"].index(col)]
    raise AssertionError("not on the page: %s" % ref)


def day(y, m, d):
    return float(date_to_serial(dt.date(y, m, d)))


# ---------------------------------------------------------------------------------------------- live
def test_a_personal_formula_follows_its_source(module_service):
    """=C60+7 in the broken-date converter's value date (MASA!C171): its value is C60's plus seven, as a value typed
    there would be; C60 typed again - the formula input follows at once; the page draws it with its formula (ƒ)."""
    svc = module_service
    u = login(svc, "Formül Canlı")
    try:
        res = put(svc, u, "MASA!C171", "=C60+7")
        assert res["errors"] == [] and res["applied"] == 1
        assert cell(svc, "MASA!C171", u) == cell(svc, "MASA!C60", u) + 7
        put(svc, u, "MASA!C60", "01.12.2026")
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 8)
        put(svc, u, "MASA!C60", "15.01.2027")
        assert cell(svc, "MASA!C171", u) == day(2027, 1, 22)
        # everything downstream reads it as a value: the converter's own day count follows
        c = mark(svc, u, "masa", "MASA!C171")
        assert c["ff"] == "=C60+7" and c["t"] == "22.01.2027" and c["i"] == "u" and c["m"] == 1 and "fe" not in c
        info = svc.cell_info(u, "tto", "MASA!C171")
        assert info["input"]["formula"] == "=C60+7" and info["cell"]["ff"] == "=C60+7"
        mine = {x["ref"]: x for x in svc.my_inputs(u)["inputs"]}
        assert mine["MASA!C171"]["formula"] == "=C60+7" and mine["MASA!C171"]["value"] == day(2027, 1, 22)
        assert "formula" not in mine["MASA!C60"]
        # the Turkish separator and decimal comma, and another sheet by name
        put(svc, u, "MASA!C171", "=ROUND(C60;0)+0,4*10")
        assert cell(svc, "MASA!C171", u) == day(2027, 1, 19)
        put(svc, u, "MASA!C171", "=Forward!D2")
        assert cell(svc, "MASA!C171", u) == cell(svc, "Forward!D2", u)
        put(svc, u, "Forward!D2", "15.03.2027")
        assert cell(svc, "MASA!C171", u) == day(2027, 3, 15)
    finally:
        svc.reset_inputs(u, "tto")


def test_a_reference_without_a_sheet_is_the_inputs_own(module_service):
    """=AB2*2 typed on the Forward sheet reads Forward!AB2 (not MASA's) - even with both inputs in one group (they share
    the engine's dependency bit: the formula's own references tell that AB2 is not computed from AB1)."""
    svc = module_service
    u = login(svc, "Formül Kendi Sayfası")
    try:
        assert put(svc, u, "Forward!AB2", "21")["errors"] == []
        res = put(svc, u, "Forward!AB1", "=AB2*2")
        assert res["errors"] == [] and cell(svc, "Forward!AB1", u) == 42.0
        put(svc, u, "Forward!AB2", "5")
        assert cell(svc, "Forward!AB1", u) == 10.0
        assert put(svc, u, "MASA!C171", "=MASA!C60+7")["errors"] == []
        assert cell(svc, "MASA!C171", u) == cell(svc, "MASA!C60", u) + 7
    finally:
        svc.reset_inputs(u, "tto")


def test_a_shared_formula_is_everybodys_a_personal_one_only_its_users(module_service):
    """A formula in a shared (green) input is the desk's: another user sees its value and its formula, and it reads what
    everybody sees.  A personal (yellow) input's formula is invisible to everyone else."""
    svc = module_service
    a, b = login(svc, "Formül Ortak A"), login(svc, "Formül Ortak B")
    try:
        assert put(svc, a, "MASA!R161", "=R160-5")["errors"] == []
        assert cell(svc, "MASA!R161", b) == cell(svc, "MASA!R161") == 30.0
        info = svc.cell_info(b, "tto", "MASA!R161")
        assert info["input"]["scope"] == "shared" and info["input"]["formula"] == "=R160-5"
        assert mark(svc, b, "masa", "MASA!R161")["ff"] == "=R160-5"
        put(svc, b, "MASA!R160", "40")                              # (anyone may type the desk's inputs: the formula follows)
        assert cell(svc, "MASA!R161", a) == 35.0
        # a's own formula: theirs alone
        assert put(svc, a, "MASA!C171", "=C60+7")["errors"] == []
        assert cell(svc, "MASA!C171", a) != cell(svc, "MASA!C171", b)
        assert svc.cell_info(b, "tto", "MASA!C171")["input"].get("formula") is None
        assert "ff" not in mark(svc, b, "masa", "MASA!C171") and mark(svc, a, "masa", "MASA!C171")["ff"] == "=C60+7"
        assert svc.my_inputs(b)["inputs"] == []
    finally:
        svc.reset_inputs(a, "tto")
        svc.reset_inputs(a, "tto", ["MASA!R160", "MASA!R161"], shared=True)
    assert cell(svc, "MASA!R161") == 29.01 and svc.store.shared_formulas() == {}


# ---------------------------------------------------------------------------------------------- refused
@pytest.mark.parametrize("ref, text, why", [
    ("MASA!C171", '=BDP("USDTRY Curncy";"PX_LAST")', "BDP Bloomberg'den veri ister: girdi formüllerinde Bloomberg"),
    ("MASA!C171", "=_xll.BDH(\"X\";\"PX_LAST\";1;2)", "Bloomberg'den veri ister"),
    ("MASA!C171", "=C171+1", "döngüsel başvuru: MASA!C171 → MASA!C171"),
    ("MASA!C60", "=E60-90", "döngüsel başvuru: MASA!C60 → MASA!E60 → MASA!C60"),       # (E60's own formula reads C60)
    ("MASA!C171", "=(C60+", "formül okunamadı"),
    ("MASA!C171", "=FOO(1)", "Bilinmeyen işlev: FOO"),
    ("MASA!C171", "=Yok!A1", "Böyle bir sayfa yok: Yok"),
    ("Forward!O44", '="S"', "bu hücre listeden bir değer alır (B, S)"),
    ("OIS_MAIN!P10", "=P11-7", "toplantı tarihleri takvimden değişir"),
    ("OIS_MAIN!U12", "=-25", "toplantı takvimiyle kayan hücre: formül yazılamaz"),   # (a step: it moves with its meeting)
    ("OIS_MAIN!W89", "=V89", "toplantı takvimiyle kayan hücre: formül yazılamaz"),
    ("MASA!R161", "=Motor!C5", "Motor sayfası yalnızca yöneticilere açık"),
    ("Forward!D2", "=NOW()+30", "Bloomberg isteğine girer (EK_XAU!"),          # (a live value into BFXFORWARD's date)
])
def test_refused_with_the_reason(module_service, ref, text, why):
    svc = module_service
    u = login(svc, "Formül Ret")
    before = cell(svc, ref, u)
    res = put(svc, u, ref, text)
    assert res["applied"] == 0 and len(res["errors"]) == 1 and res["errors"][0].startswith(ref + ": ")
    assert why in res["errors"][0], res["errors"]
    assert cell(svc, ref, u) == before and svc.my_inputs(u)["inputs"] == []


def test_a_cycle_through_another_formula_input_and_what_takes_no_formula(module_service):
    """A formula reading - through other formula inputs - the cell it is typed into is refused, the way named; so is one
    in a cell typed over by hand ("Elle değer": a constant) and in a cell of no input; a date formula that is not live
    goes into a cell Bloomberg reads (once a day: TODAY())."""
    svc = module_service
    u = login(svc, "Formül Döngü")
    try:
        assert put(svc, u, "MASA!C171", "=C60+7")["errors"] == []
        err = put(svc, u, "MASA!C60", "=C171-7")["errors"]
        assert err == ["MASA!C60: döngüsel başvuru: MASA!C60 → MASA!C171 → MASA!C60 - formül yazıldığı hücreyi okuyor"]
        # two at once, reading each other (a paste): the second is refused
        res = svc.set_inputs(u, "tto", [{"ref": "Forward!AB1", "value": "=AB2+1"}, {"ref": "Forward!AB2", "value": "=AB1+1"}])
        assert res["applied"] == 1 and len(res["errors"]) == 1 and "döngüsel başvuru: Forward!AB2 → Forward!AB1" in res["errors"][0]
        res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!F50", "value": "=1+1"}], True)
        assert "formül yalnızca girdi hücrelerine" in res["errors"][0]
        res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!F50", "value": "=1+1"}], False, None, True)       # (a paste)
        assert res["errors"] == [] and res["skipped"] == 1
        assert put(svc, u, "Forward!D2", "=TODAY()+30")["errors"] == []
        assert cell(svc, "Forward!D2", u) == svc.books["tto"].engine.clock.today() + 30
    finally:
        svc.reset_inputs(u, "tto")


def test_a_cycle_that_appears_later_is_stopped_never_spun(module_service):
    """C60 =E60 while E60 holds a typed date: no cycle.  E60 blanked - its own formula reads C60 again (three months on):
    the formula is stopped after a few rounds (#CALC!, the reason on the cell), the calculation thread goes on; a value
    typed over it ends it."""
    svc = module_service
    u = login(svc, "Formül Sonra Döngü")
    try:
        put(svc, u, "MASA!E60", "01.03.2027")
        assert put(svc, u, "MASA!C60", "=E60")["errors"] == []
        assert cell(svc, "MASA!C60", u) == day(2027, 3, 1)
        n = svc.formulas.evaluations
        assert put(svc, u, "MASA!E60", "")["errors"] == []
        assert cell(svc, "MASA!C60", u) is E_CALC
        assert svc.formulas.evaluations - n <= 12                    # (a few rounds, then stopped: it never spins)
        info = svc.cell_info(u, "tto", "MASA!C60")
        assert info["input"]["error"].startswith("Döngüsel başvuru: MASA!C60 → MASA!E60 → MASA!C60 - formül durduruldu")
        assert mark(svc, u, "masa", "MASA!C60")["fe"] == info["input"]["error"]
        n = svc.formulas.evaluations
        svc.bump()
        svc.bump(market=True)
        assert cell(svc, "MASA!C60", u) is E_CALC and svc.formulas.evaluations == n      # (stopped: not tried at each tick)
        put(svc, u, "MASA!C60", "01.12.2026")
        assert cell(svc, "MASA!C60", u) == day(2026, 12, 1) and svc.store.user_formulas(u) == {}
    finally:
        svc.reset_inputs(u, "tto")


# ---------------------------------------------------------------------------------------------- removed
def test_clearing_and_resets_remove_the_formula(module_service):
    """Delete (an empty value), "Girdilerimi sıfırla" and every reset take the formula with the value; a value typed over a
    formula replaces it; a paste of a formula is one."""
    svc = module_service
    u = login(svc, "Formül Sil")
    default = cell(svc, "MASA!C171", u)
    try:
        put(svc, u, "MASA!C171", "=C60+7")
        assert put(svc, u, "MASA!C171", "")["applied"] == 1
        assert cell(svc, "MASA!C171", u) == default and svc.store.user_formulas(u) == {}
        assert "ff" not in mark(svc, u, "masa", "MASA!C171")
        put(svc, u, "MASA!C171", "=C60+7")
        put(svc, u, "MASA!C171", "01.04.2027")                     # (a value typed over the formula: the value)
        assert svc.store.user_formulas(u) == {} and cell(svc, "MASA!C171", u) == day(2027, 4, 1)
        put(svc, u, "MASA!C60", "01.12.2026")
        assert cell(svc, "MASA!C171", u) == day(2027, 4, 1)          # (no formula follows C60 any more)
        res = svc.paste(u, "tto", "MASA!C171", "=C60+1")
        assert res["applied"] == 1 and svc.store.user_formulas(u) == {("tto", "MASA!C171"): "=C60+1"}
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 2)
        svc.reset_inputs(u, "tto", ["MASA!C171"])                   # (the cell's own reset)
        assert svc.store.user_formulas(u) == {} and cell(svc, "MASA!C171", u) == default
        put(svc, u, "MASA!C171", "=C60+7")
        assert svc.reset_inputs(u, "tto")["reset"] == 2             # ("Girdilerimi sıfırla")
        assert svc.store.user_formulas(u) == {} and svc.my_inputs(u)["inputs"] == []
        assert cell(svc, "MASA!C171", u) == default
        put(svc, u, "MASA!C60", "01.12.2026")
        assert cell(svc, "MASA!C171", u) == default
    finally:
        svc.reset_inputs(u, "tto")


def test_a_scenario_keeps_its_formulas(module_service):
    svc = module_service
    u = login(svc, "Formül Senaryo")
    try:
        put(svc, u, "MASA!C60", "01.12.2026")
        put(svc, u, "MASA!C171", "=C60+7")
        assert svc.save_scenario(u, "formüllü")["cells"] == 2
        svc.reset_inputs(u, "tto")
        assert svc.load_scenario(u, "formüllü")["cells"] == 2
        assert svc.store.user_formulas(u) == {("tto", "MASA!C171"): "=C60+7"}
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 8)
        put(svc, u, "MASA!C60", "05.12.2026")
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 12)
    finally:
        svc.reset_inputs(u, "tto")
        svc.delete_scenario(u, "formüllü")


# ---------------------------------------------------------------------------------------------- kept, and the cost
def test_no_work_without_formulas_and_formulas_survive_a_restart(tmp_path):
    """Nobody with a formula: a new generation costs nothing (no evaluation is even queued).  The formulas are kept with
    the inputs: after a restart the desk's is evaluated at the start, a user's once their calculation is made - over what
    is there then."""
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Formül Kalıcı")
        put(svc, u, "MASA!C60", "01.12.2026")
        svc.bump()
        svc.bump(market=True)
        assert cell(svc, "MASA!C60", u) == day(2026, 12, 1)
        assert (svc.formulas.jobs, svc.formulas.evaluations, svc.formulas.active) == (0, 0, False)
        put(svc, u, "MASA!C171", "=C60+7")
        put(svc, u, "MASA!R161", "=R160-5")
        assert svc.store.user_formulas(u) == {("tto", "MASA!C171"): "=C60+7"}
        assert svc.store.shared_formulas() == {("tto", "MASA!R161"): "=R160-5"}
        assert svc.store.user_inputs(u)[("tto", "MASA!C171")] == day(2026, 12, 8)         # (the value beside the formula)
        assert svc.formulas.active and svc.formulas.jobs > 0
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        assert cell(again, "MASA!R161") == 30.0
        assert again.cell_info(None, "tto", "MASA!R161")["input"]["formula"] == "=R160-5"
        assert cell(again, "MASA!C171", u) == day(2026, 12, 8)
        put(again, u, "MASA!C60", "10.12.2026")
        assert cell(again, "MASA!C171", u) == day(2026, 12, 17)
        assert mark(again, u, "masa", "MASA!C171")["ff"] == "=C60+7"
    finally:
        again.stop()


def test_a_cell_the_meeting_calendar_moves_takes_no_formula(tmp_path, caplog):
    """A meeting's date, its steps and its label (OIS_MAIN P / U:W / O, rows 10-89 - meetings.py) move with the meeting
    when the list shifts: no formula is taken there.  A formula elsewhere that names such a cell follows the meeting
    through a shift, as Excel moves a reference when rows move.  One an earlier version took in a moving cell goes when
    the service starts: its value stays, the log says so."""
    svc = make_service(tmp_path)
    db = svc.settings.db_path
    u = login(svc, "Formül Takvim")
    try:
        for ref in ("OIS_MAIN!U12", "OIS_MAIN!V40", "OIS_MAIN!W89", "OIS_MAIN!P12", "OIS_MAIN!O12"):
            err = put(svc, u, ref, "=-25")["errors"]
            assert len(err) == 1 and ("toplantı takvimiyle kayan hücre" in err[0] or "toplantı tarihleri" in err[0]), err
        assert put(svc, u, "OIS_MAIN!U12", "-25")["errors"] == []
        assert put(svc, u, "MASA!C171", "=OIS_MAIN!P12+1")["errors"] == []
        start = svc.history.meetings()
        svc.history.set_calendar(u, ["11.02.2027"] + start[:-1])          # one more meeting: the later ones a row down
        assert svc.store.user_formulas(u) == {("tto", "MASA!C171"): "=OIS_MAIN!P13+1"} and svc.store.shared_formulas() == {}
        assert cell(svc, "OIS_MAIN!P12") == day(2027, 2, 11)
        assert cell(svc, "MASA!C171", u) == day(2027, 3, 19)               # (18.03.2027's date + 1: its meeting, a row down)
        assert svc.store.user_inputs(u, "tto")[("tto", "OIS_MAIN!U13")] == -25.0      # (the typed step went with its meeting)
        assert "toplantı takvimiyle kayan hücre" in put(svc, u, "OIS_MAIN!U13", "=1")["errors"][0]
    finally:
        svc.stop()
    st = Store(db)
    st.set_user_inputs(u, "tto", {"OIS_MAIN!V13": -50.0}, {"OIS_MAIN!V13": "=-25*2"})       # (as an earlier version could)
    st.close()
    caplog.set_level(logging.WARNING, logger="tto")
    again = make_service(tmp_path)
    try:
        assert again.store.user_formulas(u) == {("tto", "MASA!C171"): "=OIS_MAIN!P13+1"}
        assert again.store.user_inputs(u, "tto")[("tto", "OIS_MAIN!V13")] == -50.0 and cell(again, "OIS_MAIN!V13", u) == -50.0
        assert [r.getMessage() for r in caplog.records if "OIS_MAIN!V13" in r.getMessage()] == [
            "girdi formülü kaldırıldı (toplantı takvimiyle kayan hücre; değeri kaldı): formül takvim tto!OIS_MAIN!V13 =-25*2"]
    finally:
        again.stop()


def test_a_formula_following_the_market_is_a_market_move_not_a_desk_change(module_service):
    """A formula reading a live price follows each tick - as a market move: the desk's change counter, which makes the
    pages of users with inputs of their own at once, stays where it was (an entry or a change of a formula moves it)."""
    svc = module_service
    u = login(svc, "Formül Piyasa")
    key = bdp_key("XAU Curncy", "BID")                                    # (EK_XAU!B6: the gold spot, a quote here)
    svc.et.call(svc._apply_market, svc.provider.update({key: 3960.0}))
    try:
        desk = svc.desk_changes
        assert put(svc, u, "MASA!J171", "=EK_XAU!B6")["errors"] == []
        assert cell(svc, "MASA!J171", u) == 3960.0 and svc.desk_changes > desk
        desk = svc.desk_changes
        for price in (3970.0, 3975.5):
            svc.et.call(svc._apply_market, svc.provider.update({key: price}))
            svc.bump(market=True)                                         # (the market loop's own, after a tick)
            assert cell(svc, "MASA!J171", u) == price
        assert svc.desk_changes == desk
    finally:
        svc.reset_inputs(u, "tto")
        svc.provider.snapshot.pop(key, None)
        svc.et.call(svc._apply_market, [key])


def test_a_time_out_is_tried_again_later_and_stops_only_after_several_in_a_row(module_service, monkeypatch):
    """Over the evaluation's time limit (a cold calculation): the formula keeps its value, says it will be tried again,
    is not evaluated during its pause, follows again once evaluated in time; stopped only after several in a row."""
    svc = module_service
    fx = svc.formulas
    u = login(svc, "Formül Süre")
    monkeypatch.setattr(fx, "BACKOFF", (3600.0,))
    monkeypatch.setattr(fx, "STOP_AFTER", 3)
    book = svc.books["tto"]
    try:
        assert put(svc, u, "MASA!C171", "=C60+7+0*COUNT(EK_TATIL!B5:C264)")["errors"] == []     # (520 cells read)
        put(svc, u, "MASA!C60", "01.12.2026")
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 8)
        e = fx.entry(u, "tto", *book.cell("MASA!C171"))
        monkeypatch.setattr(calc_mod, "EVAL_SECONDS", -1.0)              # (every evaluation over the limit)
        put(svc, u, "MASA!C60", "02.12.2026")
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 8)              # (its value stays meanwhile)
        assert (e.timeouts, e.frozen) == (1, False) and "yeniden denenecek" in e.note
        assert mark(svc, u, "masa", "MASA!C171").get("fe") is None or "yeniden denenecek" in mark(svc, u, "masa", "MASA!C171")["fe"]
        n = fx.evaluations
        svc.bump(market=True)
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 8) and fx.evaluations == n          # (its pause: not tried)
        monkeypatch.setattr(calc_mod, "EVAL_SECONDS", 2.0)
        e.retry_at = 0.0                                                  # (the pause is over)
        svc.bump(market=True)
        assert cell(svc, "MASA!C171", u) == day(2026, 12, 9) and e.timeouts == 0
        monkeypatch.setattr(calc_mod, "EVAL_SECONDS", -1.0)
        for k in range(3):
            e.retry_at = 0.0
            put(svc, u, "MASA!C60", "%02d.12.2026" % (10 + k))
            cell(svc, "MASA!C171", u)
        assert e.frozen and e.error.startswith("Hesap süresi sınırı aşıldı") and "3 kez üst üste" in e.error
        assert cell(svc, "MASA!C171", u) is E_CALC                        # (MASA!C171 goes into no Bloomberg request)
    finally:
        monkeypatch.setattr(calc_mod, "EVAL_SECONDS", 2.0)
        svc.reset_inputs(u, "tto")


def test_where_the_value_goes_into_a_bloomberg_request_a_stopped_formula_keeps_its_last_good_value(module_service,
                                                                                                    monkeypatch):
    """Forward!D2 goes into BFXFORWARD (EK_XAU!G33): an error value there would be a request with an empty argument.  A
    formula stopped there keeps the value it had, the reason says so."""
    svc = module_service
    fx = svc.formulas
    u = login(svc, "Formül Bloomberg Hücresi")
    monkeypatch.setattr(fx, "STOP_AFTER", 1)
    try:
        assert put(svc, u, "Forward!D2", "=MASA!C60+30+0*COUNT(EK_TATIL!B5:C264)")["errors"] == []
        good = cell(svc, "Forward!D2", u)
        assert good == cell(svc, "MASA!C60", u) + 30
        monkeypatch.setattr(calc_mod, "EVAL_SECONDS", -1.0)
        put(svc, u, "MASA!C60", "05.12.2026")
        got = cell(svc, "Forward!D2", u)                                  # (once the round queued by the write has run)
        e = fx.entry(u, "tto", *svc.books["tto"].cell("Forward!D2"))
        assert e.frozen and e.error.endswith(KEPT) and got == good
    finally:
        monkeypatch.setattr(calc_mod, "EVAL_SECONDS", 2.0)
        svc.reset_inputs(u, "tto")


def test_a_shared_formula_reads_with_nobodys_rights_a_personal_one_with_its_owners_role_now(module_service):
    """Motor is the administrators': a shared formula is everybody's, so it may not read it - not even typed by an
    administrator; a user's own reads with the role they have when it is evaluated (taken away: stopped with the reason;
    given back: it reads again)."""
    svc = module_service
    a, b = login(svc, "Formül Yönetici A"), login(svc, "Formül Yönetici B")
    for k in (a, b):
        svc.store.update_account(k, role="admin", pw_hash="-")
    try:
        err = put(svc, a, "MASA!R161", "=Motor!C5")["errors"]
        assert len(err) == 1 and "Motor sayfası yalnızca yöneticilere açık" in err[0]
        assert put(svc, a, "MASA!J171", "=Motor!C5")["errors"] == []
        assert cell(svc, "MASA!J171", a) == 37.0
        svc.admin_action(b, "role", {"name": "Formül Yönetici A", "admin": False})
        assert cell(svc, "MASA!J171", a) is E_CALC
        assert "Motor sayfası yalnızca yöneticilere açık" in svc.cell_info(a, "tto", "MASA!J171")["input"]["error"]
        svc.admin_action(b, "role", {"name": "Formül Yönetici A", "admin": True})
        assert cell(svc, "MASA!J171", a) == 37.0 and "error" not in svc.cell_info(a, "tto", "MASA!J171")["input"]
    finally:
        svc.reset_inputs(a, "tto")
        svc.store.update_account(a, role="user")
        svc.store.update_account(b, role="user")


def test_a_stopped_formula_is_tried_again_once_then_after_a_pause(module_service):
    """Stopped (a cycle that appeared later): its owner's next write tries it again at once; stopped again, writes do
    not try it again until a pause is over - it is not evaluated and stopped anew on every write."""
    svc = module_service
    fx = svc.formulas
    u = login(svc, "Formül Bekleme")
    try:
        put(svc, u, "MASA!E60", "01.03.2027")
        assert put(svc, u, "MASA!C60", "=E60")["errors"] == []
        put(svc, u, "MASA!E60", "")                                       # (E60's own formula reads C60: a cycle)
        e = fx.entry(u, "tto", *svc.books["tto"].cell("MASA!C60"))
        assert cell(svc, "MASA!C60", u) is E_CALC and e.frozen and e.freezes == 1
        n = fx.evaluations
        put(svc, u, "MASA!I60", "-140")                                    # (tried again at once - and stopped again)
        assert cell(svc, "MASA!C60", u) is E_CALC and e.frozen and e.freezes == 2 and fx.evaluations > n
        n = fx.evaluations
        put(svc, u, "MASA!I60", "-130")
        assert cell(svc, "MASA!C60", u) is E_CALC and e.frozen and fx.evaluations == n      # (its pause: not tried)
        e.thaw_after = 0.0                                                 # (the pause is over)
        put(svc, u, "MASA!I60", "-120")
        assert cell(svc, "MASA!C60", u) is E_CALC and e.frozen and e.freezes == 3 and fx.evaluations > n
    finally:
        svc.reset_inputs(u, "tto")


def test_scheduling_goes_on_after_a_failed_submit(module_service, monkeypatch):
    """A round that could not be queued leaves nothing behind: the next generation queues one."""
    import types
    svc = module_service
    fx = svc.formulas
    svc.et.call(lambda: None)                                             # (whatever was queued has run)
    fx._queued = False

    def refuse(*args, **kw):
        raise RuntimeError("kuyruk kapalı")

    monkeypatch.setattr(fx, "svc", types.SimpleNamespace(et=types.SimpleNamespace(submit_at=refuse)))
    with pytest.raises(RuntimeError):
        fx.schedule()
    assert fx._queued is False
    monkeypatch.setattr(fx, "svc", svc)
    jobs = fx.jobs
    fx.schedule()
    svc.et.call(lambda: None)
    assert fx.jobs == jobs + 1 and fx._queued is False


def test_over_http(module_service):
    """POST /api/inputs takes a formula as any value (refusals among the errors, with the reason); /api/cell, the page and
    /api/my-inputs show it; /api/reset takes it away."""
    svc = module_service
    h = auth(svc, "Formül HTTP")
    u = login(svc, "Formül HTTP")
    with TestClient(create_app(svc), headers=h) as client:
        res = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "MASA!C171", "value": "=C60+7"}]})
        assert res.status_code == 200 and res.json()["applied"] == 1 and res.json()["errors"] == []
        res = client.post("/api/inputs", json={"book": "tto", "items": [{"ref": "MASA!C60", "value": "=BDP(\"X\";\"Y\")"}]})
        assert res.status_code == 200 and "Bloomberg" in res.json()["errors"][0]
        info = client.get("/api/cell?book=tto&ref=MASA!C171").json()
        assert info["input"]["formula"] == "=C60+7" and info["cell"]["ff"] == "=C60+7"
        assert info["cell"]["v"] == cell(svc, "MASA!C60", u) + 7
        page = client.get("/api/view/masa").json()
        ff = [c for p in page["panels"] for row in (p.get("data") or {}).get("rows", []) for c in row if c.get("ff")]
        assert ff and {c["ff"] for c in ff} == {"=C60+7"}
        mine = client.get("/api/my-inputs").json()["inputs"]
        assert [(x["ref"], x["formula"]) for x in mine] == [("MASA!C171", "=C60+7")]
        assert client.post("/api/reset", json={"book": "tto"}).json()["reset"] == 1
        assert client.get("/api/my-inputs").json()["inputs"] == []
        assert "formula" not in client.get("/api/cell?book=tto&ref=MASA!C171").json()["input"]
