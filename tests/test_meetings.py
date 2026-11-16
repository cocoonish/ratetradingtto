"""What belongs to a meeting row (``tto/meetings.py``): the registry of the two meeting calendars - TCMB
(``OIS_MAIN!P10:P89``) and Fed (``SOFR_FOMC!B74:B83``) - and the one way a list changes.  Everything typed for a meeting
moves with it, for every user: values, the desk's labels, "Elle değer", saved scenarios, Motor's per-meeting inputs, the
references to its cells (input formulas, scenarios, calc sheets, watch expressions), the watch's items and alarms.  A
meeting that leaves a list is set aside under its date and comes back with it; a stale calendar save is refused; a
change lands in one transaction."""
import datetime as dt

import pytest

from conftest import auth, cell, make_service
from tto import meetings as mt
from tto.inputformula import KEPT
from tto.service import Service, ServiceError
from tto.xl.values import date_to_serial, serial_to_date


def login(svc, name, admin=False):
    key = svc.login(name)["user"]
    if admin:
        svc.store.update_account(key, role="admin")
    return key


def put(svc, user, items, book="tto", **kw):
    """``items``: {ref: value} or [(ref, value)] - one write."""
    pairs = items.items() if isinstance(items, dict) else items
    return svc.set_inputs(user, book, [{"ref": r, "value": v} for r, v in pairs], **kw)


def day(text):
    return float(date_to_serial(dt.date.fromisoformat(text)))


def p(svc, r):
    v = cell(svc, "OIS_MAIN!P%d" % r)
    return serial_to_date(v).isoformat() if isinstance(v, float) else None


def b(svc, r):
    v = cell(svc, "SOFR_FOMC!B%d" % r, book="sofr")
    return serial_to_date(v).isoformat() if isinstance(v, float) else None


def mine(svc, user, book="tto"):
    return {k[1]: v for k, v in svc.store.user_inputs(user, book).items()}


def scenario(svc, user, name):
    values, formulas = svc.store.scenario(user, name)
    return {k[1]: v for k, v in values.items()}, {k[1]: v for k, v in formulas.items()}


def watched(svc, user, book, ref):
    """A cell's value as the watch shows it (a per cent cell in per cent) for ``user``."""
    w = svc.watch
    return svc.et.call(lambda: w.resolve({"kind": "cell", "book": book, "ref": ref}, w._Reader(w, user))[0])


# ---------------------------------------------------------------------------------------------- the registry
def test_the_registry_knows_every_cell_of_a_meeting_row(service):
    tto, sofr = service.books["tto"], service.books["sofr"]

    def where(book, ref):
        hit = mt.place(book, *book.cell(ref))
        return None if hit is None else (hit[0].id, hit[1].kind, hit[2], hit[3])

    assert where(tto, "OIS_MAIN!P12") == ("tcmb", "key", 2, "P")
    assert where(tto, "OIS_MAIN!O12") == ("tcmb", "label", 2, "O")
    assert where(tto, "OIS_MAIN!W89") == ("tcmb", "typed", 79, "W")
    assert where(tto, "OIS_MAIN!R10") == ("tcmb", "computed", 0, "R") and where(tto, "OIS_MAIN!BO12")[1] == "computed"
    assert where(tto, "Motor!D4313") == ("tcmb", "typed", 2, "D") and where(tto, "Motor!A4560") == ("tcmb", "typed", 79, "A")
    # the other tables on the same rows are not meetings' (O/N, stub, solver settings, ranking helpers)
    for ref in ("OIS_MAIN!AD12", "OIS_MAIN!AU10", "OIS_MAIN!BC12", "OIS_MAIN!P9", "OIS_MAIN!P90", "OIS_MAIN!M12",
                "Motor!D4310", "Motor!H4313", "Motor!A4480"):
        assert where(tto, ref) is None, ref
    assert where(sofr, "SOFR_FOMC!B76") == ("fed", "key", 2, "B") and where(sofr, "SOFR_FOMC!R83")[1] == "typed"
    assert where(sofr, "SOFR_FOMC!K76")[1] == "computed" and where(sofr, "SOFR_FOMC!A76") is None
    assert where(sofr, "SOFR_FOMC!R72") is None and where(sofr, "SOFR_FOMC!B84") is None
    # a meeting's date and what moves with it take no formula; a computed cell is no input anyway
    assert mt.follows(tto, *tto.cell("OIS_MAIN!O12")) and mt.follows(sofr, *sofr.cell("SOFR_FOMC!C76"))
    assert not mt.follows(tto, *tto.cell("OIS_MAIN!R12")) and mt.key_of(sofr, *sofr.cell("SOFR_FOMC!B74")) is mt.FED
    assert mt.slot_dates(tto, mt.TCMB)[:3] == ["2026-12-10", "2027-01-21", "2027-03-18"]
    assert mt.slot_dates(sofr, mt.FED)[:3] == ["2026-12-09", "2027-01-27", "2027-03-17"]


def test_references_follow_their_meeting():
    """The rewrite of a formula's references: a meeting's own cells (date, steps, label) follow it, a meeting that left is
    #REF!, a computed cell and a range over several meetings stay on their slots, texts and other sheets are untouched."""
    from tto.calc import _fold
    moves = mt.ref_moves(mt.TCMB, {2: 3, 3: 4, 79: None}, ["OIS_MAIN", "Motor"])
    home = ("tto", _fold("OIS_MAIN"))
    rw = lambda text, h=None: mt.rewrite_formula(text, h, moves)            # noqa: E731
    assert rw("=OIS_MAIN!U12+25") == "=OIS_MAIN!U13+25"
    assert rw("=OIS_MAIN!$U$12*2+P13", home) == "=OIS_MAIN!$U$13*2+P14"    # (no sheet: the formula's own sheet)
    assert rw("=P13") is None                                               # (no sheet in a calc sheet: its own cells)
    assert rw("=ois_main!u12") == "=ois_main!U13"
    assert rw("=SUM(OIS_MAIN!U12:W12)") == "=SUM(OIS_MAIN!U13:W13)"         # one meeting's row: with it
    assert rw("=SUM(OIS_MAIN!U10:U20)") is None                             # several meetings: the slots
    assert rw("=OIS_MAIN!R12+OIS_MAIN!Q12") is None                         # computed: "MPC3" stays MPC3
    assert rw("=OIS_MAIN!P89+1") == "=#REF!+1" and rw("=SUM(OIS_MAIN!U89:W89)") == "=SUM(#REF!)"
    assert rw('=IF(OIS_MAIN!U12>0;"OIS_MAIN!U12";1,5)') == '=IF(OIS_MAIN!U13>0,"OIS_MAIN!U12",1.5)'   # (Turkish ; read)
    assert rw("=MASA!U12+'OIS_MAIN'!O12") == "=MASA!U12+'OIS_MAIN'!O13"
    assert rw("=Motor!D4313*2") == "=Motor!D4314*2" and rw("=[sofr]SOFR_FOMC!R76") is None
    assert rw("=1+") is None and rw("12") is None
    fed = mt.ref_moves(mt.FED, {2: 0, 0: None}, ["SOFR_FOMC"])
    assert mt.rewrite_formula("=[sofr]SOFR_FOMC!R76/100", None, fed) == "='[sofr]SOFR_FOMC'!R74/100"
    assert mt.rewrite_formula("=R76/100+B74", ("sofr", "sofr_fomc"), fed) == "=R74/100+#REF!"
    assert mt.rewrite_formula("=OIS_MAIN!R76", None, fed) is None
    # the watch's expressions: names in brackets are never references
    assert mt.rewrite_expr("OIS_MAIN!U12 - [OIS 1Y]", moves) == "OIS_MAIN!U13 - [OIS 1Y]"
    assert mt.rewrite_expr("('OIS_MAIN'!U12 + OIS_MAIN!U89) / 2", moves) == "('OIS_MAIN'!U13 + #REF!) / 2"
    assert mt.rewrite_expr("[OIS_MAIN!U12]", moves) is None and mt.rewrite_expr("OIS_MAIN!R12", moves) is None


# ---------------------------------------------------------------------------------------------- TCMB
def test_a_meeting_moves_with_everything_typed_for_it(tmp_path):
    """An extraordinary meeting is put in before 18.03.2027: that meeting and the ones after it move a row down, and
    with them every user's steps (K1-K4), "Elle değer" over its computed cells (K4), the desk's label (K9), Motor's prior
    and start step of its slot (K11), saved scenarios, the references to its cells - input formulas, a scenario's
    formula, calc sheets, a watch expression (K5) - and the alarms and watch items on its row (K6).  A reference to a
    computed cell ("MPC3") stays on its slot."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        a = login(svc, "Toplantı Ayşe", admin=True)
        v = login(svc, "Toplantı Veli")
        assert put(svc, a, {"OIS_MAIN!U12": "-50", "OIS_MAIN!V12": "-75", "OIS_MAIN!U13": "-25", "Motor!D4313": "0,5",
                            "Motor!A4483": "0,25", "MASA!C171": "=OIS_MAIN!P12+1"})["errors"] == []
        assert put(svc, a, {"OIS_MAIN!R12": "12,5"}, allow_adhoc=True)["errors"] == []          # an "Elle değer"
        assert put(svc, v, {"OIS_MAIN!W12": "25"})["errors"] == []
        assert put(svc, a, {"OIS_MAIN!O12": "Mart PPK"})["errors"] == []                       # the desk's label
        assert put(svc, a, {"MASA!R161": "=OIS_MAIN!U12*0+30"})["errors"] == []                 # a desk formula
        svc.save_scenario(a, "mart")
        sheet = "takvim1"
        svc.calcsheets.save_future(a, {"sheet": sheet, "cells": {
            "A1": "=OIS_MAIN!U12+25", "A2": "=OIS_MAIN!R12", "A3": "=SUM(OIS_MAIN!U10:U20)", "A4": "=SUM(OIS_MAIN!U12:W12)",
            "A5": '="OIS_MAIN!U12"'}}, "tr").result()
        alarm = svc.alarm_add(a, "tto", "OIS_MAIN!R12", ">=", "999")["alarm"]
        assert alarm["subject"] == {"kind": "meeting", "cal": "tcmb", "date": "2027-03-18", "col": "R"}
        assert alarm["label"] == "PPK 18.03.2027 · Implied bps"
        assert svc.watch_add(v, "tto", "OIS_MAIN!S12")["added"]
        assert svc.watch_add(v, subject={"kind": "expr", "text": "OIS_MAIN!U12 - OIS_MAIN!U11"})["added"]
        # ---- the extraordinary meeting (80 rows: the last meeting makes room)
        start = h.meetings()
        res = h.set_calendar(v, ["11.02.2027"] + start[:-1])
        assert (res["meetings"], res["changed"], res["dropped"]) == (80, 78, 0)
        assert res["parked"]["meetings"] == [] and res["formulas"]["moved"] >= 4 and res["formulas"]["broken"] == 0
        assert "toplantısıyla taşınan" in res["note"] and "formülün başvurusu" in res["note"]
        assert [p(svc, r) for r in (11, 12, 13)] == ["2027-01-21", "2027-02-11", "2027-03-18"]
        got = mine(svc, a)
        assert (got["OIS_MAIN!U13"], got["OIS_MAIN!V13"], got["OIS_MAIN!U14"], got["OIS_MAIN!R13"]) == (-50.0, -75.0, -25.0, 12.5)
        assert "OIS_MAIN!U12" not in got and "OIS_MAIN!R12" not in got
        assert (got["Motor!D4314"], got["Motor!A4484"]) == (0.5, 0.25) and "Motor!D4313" not in got
        assert mine(svc, v) == {"OIS_MAIN!W13": 25.0}
        assert cell(svc, "OIS_MAIN!R13", a) == 12.5 and cell(svc, "OIS_MAIN!R12", a) != 12.5
        assert cell(svc, "OIS_MAIN!U13", a) == -50.0 and cell(svc, "OIS_MAIN!U12", a) is None
        # the desk's label went with its meeting; the file's names stay the slots' (MPC3 is the third meeting ahead)
        assert (cell(svc, "OIS_MAIN!O12"), cell(svc, "OIS_MAIN!O13")) == ("MPC3", "Mart PPK")
        assert h.calendar()["meetings"][17]["label"] == "MPC3" and h.calendar()["meetings"][18]["label"] == "Mart PPK"
        # references to the meeting's cells followed it; one to a computed cell, one to several meetings stayed
        assert svc.store.user_formulas(a) == {("tto", "MASA!C171"): "=OIS_MAIN!P13+1"}
        assert cell(svc, "MASA!C171", a) == day("2027-03-19")
        assert svc.store.shared_formulas() == {("tto", "MASA!R161"): "=OIS_MAIN!U13*0+30"}
        values, formulas = scenario(svc, a, "mart")
        assert formulas == {"MASA!C171": "=OIS_MAIN!P13+1"} and values["OIS_MAIN!U13"] == -50.0 and values["OIS_MAIN!R13"] == 12.5
        assert "OIS_MAIN!U12" not in values and values["Motor!D4314"] == 0.5
        cells = svc.calcsheets._sheets(a)[sheet]["cells"]
        assert cells == {"A1": "=OIS_MAIN!U13+25", "A2": "=OIS_MAIN!R12", "A3": "=SUM(OIS_MAIN!U10:U20)",
                         "A4": "=SUM(OIS_MAIN!U13:W13)", "A5": '="OIS_MAIN!U12"'}
        ans = svc.calcsheets.eval_future(a, [{"key": "k", "sheet": sheet}], "tr").result()["sheets"]["k"]
        assert ans["cells"]["A1"]["v"] == -25.0
        # the alarm and the watch item stay on their meeting (its row now: 13), the expression's reference followed it
        w = svc.watch_view(a)
        assert w["alarms"][0]["subject"]["date"] == "2027-03-18" and w["alarms"][0]["now"] == 12.5
        assert "OIS_MAIN!R13" in w["alarms"][0]["detail"]
        items = svc.watch_view(v)["items"]
        assert items[0]["subject"] == {"kind": "meeting", "cal": "tcmb", "date": "2027-03-18", "col": "S"}
        assert items[0]["value"] == watched(svc, v, "tto", "OIS_MAIN!S13") and items[0]["value"] is not None
        assert items[1]["subject"]["text"] == "OIS_MAIN!U13 - OIS_MAIN!U11"
        # ---- and after a restart all of it is there
        again = Service(svc.settings)
        try:
            assert cell(again, "OIS_MAIN!U13", a) == -50.0 and cell(again, "OIS_MAIN!R13", a) == 12.5
            assert cell(again, "OIS_MAIN!O13") == "Mart PPK" and cell(again, "MASA!C171", a) == day("2027-03-19")
        finally:
            again.stop()
    finally:
        svc.stop()


def test_a_meeting_that_leaves_the_list_is_set_aside_and_comes_back(tmp_path):
    """K1: a meeting removed by an ordinary edit loses nothing.  ✕ on the calendar page, a year typed wrong on the OIS
    page (more than 45 days: another meeting): what everybody typed for it - steps, "Elle değer", the desk's label, the
    values in saved scenarios - is set aside under its date, out of the rows, and said; the date back, all of it is
    back.  References to the meeting that left read #REF!; its alarm is quiet and comes back with it."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        a, v = login(svc, "Kenar Ayşe"), login(svc, "Kenar Veli")
        put(svc, a, {"OIS_MAIN!U12": "-50", "OIS_MAIN!V12": "-75", "OIS_MAIN!U13": "-25", "OIS_MAIN!O12": "Mart PPK",
                     "MASA!C171": "=OIS_MAIN!P12+1"})
        put(svc, a, {"OIS_MAIN!R12": "12,5"}, allow_adhoc=True)
        put(svc, v, {"OIS_MAIN!W12": "25"})
        svc.save_scenario(a, "mart")
        alarm = svc.alarm_add(a, "tto", "OIS_MAIN!U12", "<=", "-40")["alarm"]
        # a value date that goes into a Bloomberg request (BFXFORWARD), read from the meeting's date
        assert put(svc, a, {"Forward!D2": "=OIS_MAIN!P12"})["errors"] == [] and cell(svc, "Forward!D2", a) == day("2027-03-18")
        start = h.meetings()
        formulas = ("MASA!C171", "Forward!D2")
        before = {u: {k: x for k, x in mine(svc, u).items() if k not in formulas} for u in (a, v)}
        # ---- ✕ on 18.03.2027 (a meeting at the end keeps the list at 80)
        res = h.set_calendar(a, [d for d in start if d != "2027-03-18"] + ["2036-12-10"])
        assert res["parked"] == {"meetings": ["2027-03-18"], "cells": 5, "users": 2, "scenario_cells": 3}
        assert "1 toplantı listeden çıktı (18.03.2027): 5 değer (2 kullanıcı) ve kayıtlı senaryolarda 3 değer kenara alındı" in res["note"]
        assert res["formulas"]["broken"] == 3                       # (her two inputs' formulas and one's copy in the scenario)
        assert p(svc, 12) == "2027-04-22" and {k: x for k, x in mine(svc, a).items() if k not in formulas} == {"OIS_MAIN!U12": -25.0}
        assert mine(svc, v) == {} and cell(svc, "OIS_MAIN!O12") == "MPC3" and cell(svc, "OIS_MAIN!R12", a) != 12.5
        # the value date reads #REF! now: it goes into a Bloomberg request - its last good value kept, the error the
        # reason on the cell (no request with an empty argument; not stopped: a value again would be written again)
        assert svc.store.user_formulas(a)[("tto", "Forward!D2")] == "=#REF!"
        assert cell(svc, "Forward!D2", a) == day("2027-03-18")
        e = svc.formulas.entry(a, "tto", *svc.books["tto"].cell("Forward!D2"))
        assert not e.frozen and "hata (#REF!)" in e.error and e.error.endswith(KEPT)
        rec = mt.parked(svc.store)["tcmb"]["2027-03-18"]
        assert rec["user"] == {a: {"OIS_MAIN!U": -50.0, "OIS_MAIN!V": -75.0, "OIS_MAIN!R": 12.5}, v: {"OIS_MAIN!W": 25.0}}
        assert rec["shared"] == {"OIS_MAIN!O": "Mart PPK"} and rec["by"] == a
        assert rec["scenarios"] == {a: {"mart": {"OIS_MAIN!U": -50.0, "OIS_MAIN!V": -75.0, "OIS_MAIN!R": 12.5}}}
        assert h.calendar()["parked"] == ["2027-03-18"]
        assert svc.store.user_formulas(a)[("tto", "MASA!C171")] == "=#REF!+1"
        values, _ = scenario(svc, a, "mart")
        assert values["OIS_MAIN!U12"] == -25.0 and "OIS_MAIN!V12" not in values
        w = svc.watch_view(a)["alarms"][0]
        assert w["now"] is None and "listede yok" in w["detail"]
        # ---- the date back (the whole list as it was): everything is back, everybody's
        res = h.set_calendar(a, start)
        assert res["restored"] == {"meetings": ["2027-03-18"], "cells": 5, "users": 2, "scenario_cells": 3}
        assert "18.03.2027 listeye geri geldi: kenara alınan 8 değer yerine kondu" in res["note"]
        for u in (a, v):
            assert {k: x for k, x in mine(svc, u).items() if k not in formulas} == before[u]
        assert cell(svc, "OIS_MAIN!O12") == "Mart PPK" and cell(svc, "OIS_MAIN!R12", a) == 12.5
        values, _ = scenario(svc, a, "mart")
        assert (values["OIS_MAIN!U12"], values["OIS_MAIN!V12"], values["OIS_MAIN!R12"], values["OIS_MAIN!U13"]) == (-50.0, -75.0, 12.5, -25.0)
        assert mt.parked(svc.store).get("tcmb") == {} and h.calendar()["parked"] == []
        assert svc.watch_view(a)["alarms"][0]["now"] == -50.0
        # ---- a year typed wrong on the OIS page: another meeting - the one of the row is set aside, and said
        res = put(svc, a, {"OIS_MAIN!P12": "18.03.2028"})
        assert res["errors"] == [] and "18.03.2027" in res["note"] and "kenara alındı" in res["note"]
        assert p(svc, 12) == "2027-04-22" and p(svc, 20) == "2028-03-18" and cell(svc, "OIS_MAIN!U12", a) == -25.0
        # ... corrected: typed back over the wrong one, the meeting and everything of it are back in their row
        res = put(svc, a, {"OIS_MAIN!P20": "18.03.2027"})
        assert res["errors"] == [] and "geri geldi" in res["note"]
        assert [p(svc, r) for r in (12, 20)] == ["2027-03-18", "2028-03-16"]
        assert (cell(svc, "OIS_MAIN!U12", a), cell(svc, "OIS_MAIN!W12", v), cell(svc, "OIS_MAIN!O12")) == (-50.0, 25.0, "Mart PPK")
        # ---- what a paste with an empty date does: refused for the meeting, the rest written
        res = svc.paste(a, "tto", "OIS_MAIN!P13", "\t\t\t\t\t-30")
        assert "toplantı tarihi silinmez (OIS_MAIN!P13)" in res["errors"][0] and p(svc, 13) == "2027-04-22"
        assert cell(svc, "OIS_MAIN!U13", a) == -30.0
    finally:
        svc.stop()


def test_dates_and_steps_typed_together_land_on_one_meeting(tmp_path):
    """K10: an extraordinary meeting pasted with its steps over the last row: the date goes to its place in the list (row
    15) - and so do the steps pasted with it; the meeting that was in row 15 keeps its own steps, a row lower."""
    svc = make_service(tmp_path)
    try:
        a = login(svc, "Yapıştır Ayşe")
        put(svc, a, {"OIS_MAIN!U15": "-100"})                                        # 22.07.2027's step
        assert p(svc, 15) == "2027-07-22" and p(svc, 89) == "2036-10-19"
        res = svc.paste(a, "tto", "OIS_MAIN!P89", "01.07.2027\t\t\t\t\t-50\t-75\t-25")
        assert res["errors"] == [] and res["applied"] == 4
        assert [p(svc, r) for r in (14, 15, 16, 89)] == ["2027-06-10", "2027-07-01", "2027-07-22", "2036-09-11"]
        assert mine(svc, a) == {"OIS_MAIN!U15": -50.0, "OIS_MAIN!V15": -75.0, "OIS_MAIN!W15": -25.0, "OIS_MAIN!U16": -100.0}
        # another date typed on its row with a new step: the step goes with the date typed - here past the next meeting,
        # so another meeting (01.07's steps are set aside, and said); 22.07 keeps its own, back a row up
        res = put(svc, a, [("OIS_MAIN!P15", "25.07.2027"), ("OIS_MAIN!V15", "-10")])
        assert res["errors"] == [] and res["applied"] == 2 and "01.07.2027" in res["note"] and "kenara alındı" in res["note"]
        assert [p(svc, r) for r in (15, 16)] == ["2027-07-22", "2027-07-25"]
        assert mine(svc, a) == {"OIS_MAIN!U15": -100.0, "OIS_MAIN!V16": -10.0}
        assert mt.parked(svc.store)["tcmb"]["2027-07-01"]["user"] == {a: {"OIS_MAIN!U": -50.0, "OIS_MAIN!V": -75.0, "OIS_MAIN!W": -25.0}}
        # a date corrected within its place (the same meeting) with a step: both on that row
        res = put(svc, a, [("OIS_MAIN!P16", "28.07.2027"), ("OIS_MAIN!W16", "5")])
        assert res["errors"] == [] and p(svc, 16) == "2027-07-28"
        assert mine(svc, a) == {"OIS_MAIN!U15": -100.0, "OIS_MAIN!V16": -10.0, "OIS_MAIN!W16": 5.0}
    finally:
        svc.stop()


def test_a_save_over_a_newer_calendar_is_refused_and_a_change_is_one_transaction(tmp_path, monkeypatch):
    """K12: the calendar page saves with the version it was loaded with; a list that changed meanwhile (somebody else's
    save, the OIS page, the roll) is not saved over - the answer says who changed it.  K13: a change that fails half way
    leaves nothing moved - dates, steps, scenarios, what was set aside, the engine."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        a, v = login(svc, "Sürüm Ayşe"), login(svc, "Sürüm Veli")
        put(svc, a, {"OIS_MAIN!U12": "-50", "OIS_MAIN!U13": "-25"})
        svc.save_scenario(a, "s")
        cal = h.calendar()
        start = [m["date"] for m in cal["meetings"]]
        assert put(svc, v, {"OIS_MAIN!P13": "29.04.2027"})["errors"] == []                       # Veli's correction
        edited = [d for d in start if d != "2027-03-18"] + ["2036-12-10"]                         # Ayşe's stale list
        with pytest.raises(ServiceError) as exc:
            h.set_calendar(a, edited, version=cal["version"])
        assert exc.value.status == 409 and "takvim siz düzenlerken değişti (en son %s" % v in str(exc.value)
        assert p(svc, 12) == "2027-03-18" and p(svc, 13) == "2027-04-29"
        assert h.set_calendar(a, start, version=h.calendar()["version"])["meetings"] == 80               # current: saved
        assert p(svc, 13) == "2027-04-22"
        # ---- one transaction: a failure in the middle (the disk, the process) changes nothing
        before = (mine(svc, a), scenario(svc, a, "s"), svc.store.shared_inputs("tto"), svc.store.get(mt.PARK_KEY),
                  [p(svc, r) for r in range(10, 90)], cell(svc, "OIS_MAIN!U12", a))

        def broken(*args, **kw):
            raise RuntimeError("disk dolu")
        monkeypatch.setattr(svc.store, "put_scenario_items", broken)
        with pytest.raises(RuntimeError):
            h.set_calendar(a, ["11.02.2027"] + start[:-1])
        monkeypatch.undo()
        after = (mine(svc, a), scenario(svc, a, "s"), svc.store.shared_inputs("tto"), svc.store.get(mt.PARK_KEY),
                 [p(svc, r) for r in range(10, 90)], cell(svc, "OIS_MAIN!U12", a))
        assert after == before
        assert h.set_calendar(a, ["11.02.2027"] + start[:-1])["moved"] == 2          # (and it goes through when it can)
        # ---- over HTTP (the page sends the version it has)
        from starlette.testclient import TestClient
        from tto.server import create_app
        with TestClient(create_app(svc), headers=auth(svc, "Sürüm Ayşe")) as c:
            now = c.get("/api/calendar").json()
            dates = [m["date"] for m in now["meetings"]]
            r = c.post("/api/calendar", json={"dates": dates, "version": "eskisi"})
            assert r.status_code == 409 and "değişti" in r.json()["error"]
            r = c.post("/api/calendar", json={"dates": dates, "version": now["version"]})
            assert r.status_code == 200 and r.json()["moved"] == 0 and "slot_to" not in r.json()
    finally:
        svc.stop()


def test_the_roll_takes_everything_of_the_passed_meeting_aside_and_the_next_ones_along(tmp_path):
    """The roll (a meeting passed): "Elle değer", labels, Motor's per-meeting inputs move a row up with their meetings;
    what was typed for the passed meeting is set aside (B6) - not deleted - and goes some weeks after its day."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        book = svc.books["tto"]
        a = login(svc, "Kayma Ayşe", admin=True)
        put(svc, a, {"OIS_MAIN!U10": "-100", "OIS_MAIN!U11": "-75", "OIS_MAIN!O11": "Ocak", "Motor!D4312": "0,4"})
        put(svc, a, {"OIS_MAIN!T11": "-150"}, allow_adhoc=True)

        def move_spot():
            book.declare("OIS_MAIN!B2", scope="shared", group="test-spot")
            book.engine.set_inputs({book.cell("OIS_MAIN!B2"): day("2026-12-14")})
        svc.et.call(move_spot)
        svc.bump()
        res = h.roll_calendar(a)
        assert res["rolled"] == ["2026-12-10"] and res["parked"]["meetings"] == ["2026-12-10"]
        assert mine(svc, a) == {"OIS_MAIN!U10": -75.0, "OIS_MAIN!T10": -150.0, "Motor!D4311": 0.4}
        assert cell(svc, "OIS_MAIN!O10") == "Ocak" and cell(svc, "OIS_MAIN!O11") == "MPC2"
        assert mt.parked(svc.store)["tcmb"]["2026-12-10"]["user"] == {a: {"OIS_MAIN!U": -100.0}}
        # a later change, more than PARK_DAYS after the meeting's day: the set aside values go
        monkeypatch_today = dt.date(2027, 1, 20)
        svc.et.call(lambda: setattr(book.engine.clock, "today", lambda: float(date_to_serial(monkeypatch_today))))
        h.set_calendar(a, h.meetings())
        assert "2026-12-10" not in (mt.parked(svc.store).get("tcmb") or {})
    finally:
        svc.stop()


# ---------------------------------------------------------------------------------------------- Fed
def test_the_fomc_list_moves_what_was_typed_with_its_meetings(tmp_path):
    """K3: the FOMC list (SOFR_FOMC!B74:B83) had no "moves with its meeting".  The desk pastes the list without the two
    held meetings and with two new ones: every user's decision flag, WIRP and scenario steps (C, P, R:T), their "Elle
    değer", saved scenarios, a formula's reference and an alarm go with their meeting.  A date blanked takes its
    meeting out of the list (set aside, said); typed back, it is all back.  No formula in the dates or the steps; the
    file's dates are not put back over the list."""
    svc = make_service(tmp_path)
    try:
        a, desk = login(svc, "FOMC Ayşe"), login(svc, "FOMC Masa")
        fed = {"SOFR_FOMC!C76": "0", "SOFR_FOMC!P76": "4,1", "SOFR_FOMC!R76": "25", "SOFR_FOMC!S76": "50",
               "SOFR_FOMC!T76": "-25", "SOFR_FOMC!R77": "-25", "SOFR_FOMC!C6": "=R76/100"}
        assert put(svc, a, fed, book="sofr")["errors"] == []
        assert put(svc, a, {"SOFR_FOMC!K76": "4"}, book="sofr", allow_adhoc=True)["errors"] == []
        svc.save_scenario(a, "fomc")
        alarm = svc.alarm_add(a, "sofr", "SOFR_FOMC!K76", ">=", "9")["alarm"]
        assert alarm["subject"] == {"kind": "meeting", "cal": "fed", "date": "2027-03-17", "col": "K"}
        assert alarm["label"] == "FOMC 17.03.2027 · İma O/N %"
        assert cell(svc, "SOFR_FOMC!C6", a, book="sofr") == 0.25
        # ---- refused: a formula in a date or a step, the file's dates back over the list
        assert "takvimden değişir (USD · FOMC sayfası)" in put(svc, desk, {"SOFR_FOMC!B74": "=B75-42"}, book="sofr")["errors"][0]
        assert "toplantı takvimiyle kayan hücre" in put(svc, a, {"SOFR_FOMC!R78": "=R77"}, book="sofr")["errors"][0]
        with pytest.raises(ServiceError) as exc:
            svc.reset_inputs(desk, "sofr", ["SOFR_FOMC!B74:B83"], shared=True)
        assert "USD · FOMC sayfası" in str(exc.value)
        # ---- the held meetings out, two new ones in (a pasted column)
        new = ["17.03.2027", "28.04.2027", "09.06.2027", "28.07.2027", "15.09.2027", "27.10.2027", "08.12.2027",
               "26.01.2028", "15.03.2028", "26.04.2028"]
        res = svc.paste(desk, "sofr", "SOFR_FOMC!B74", "\n".join(new))
        assert res["errors"] == [] and res["calendar"]["moved"] == 7
        assert [b(svc, r) for r in (74, 75, 82, 83)] == ["2027-03-17", "2027-04-28", "2028-03-15", "2028-04-26"]
        got = mine(svc, a, "sofr")
        assert {k: x for k, x in got.items() if k != "SOFR_FOMC!C6"} == {
            "SOFR_FOMC!C74": 0.0, "SOFR_FOMC!P74": 4.1, "SOFR_FOMC!R74": 25.0, "SOFR_FOMC!S74": 50.0, "SOFR_FOMC!T74": -25.0,
            "SOFR_FOMC!R75": -25.0, "SOFR_FOMC!K74": 4.0}
        assert svc.store.user_formulas(a) == {("sofr", "SOFR_FOMC!C6"): "=R74/100"}
        assert cell(svc, "SOFR_FOMC!C6", a, book="sofr") == 0.25 and cell(svc, "SOFR_FOMC!C82", a, book="sofr") == 1.0
        values, _ = scenario(svc, a, "fomc")
        assert values["SOFR_FOMC!R74"] == 25.0 and "SOFR_FOMC!R76" not in values
        w = svc.watch_view(a)["alarms"][0]
        assert w["subject"]["date"] == "2027-03-17" and w["now"] == watched(svc, a, "sofr", "SOFR_FOMC!K74") is not None
        # ---- a date blanked (Delete over B74): the meeting leaves, what was typed for it waits under its date
        res = put(svc, desk, {"SOFR_FOMC!B74": ""}, book="sofr")
        assert res["errors"] == [] and "1 toplantı listeden çıktı (17.03.2027)" in res["note"]
        assert [b(svc, r) for r in (74, 82, 83)] == ["2027-04-28", "2028-04-26", None]
        assert mine(svc, a, "sofr").get("SOFR_FOMC!R74") == -25.0 and "SOFR_FOMC!K74" not in mine(svc, a, "sofr")
        res = put(svc, desk, {"SOFR_FOMC!B83": "17.03.2027"}, book="sofr")
        assert res["errors"] == [] and "geri geldi" in res["note"] and b(svc, 74) == "2027-03-17"
        assert {k: x for k, x in mine(svc, a, "sofr").items() if k != "SOFR_FOMC!C6"} == {
            "SOFR_FOMC!C74": 0.0, "SOFR_FOMC!P74": 4.1, "SOFR_FOMC!R74": 25.0, "SOFR_FOMC!S74": 50.0, "SOFR_FOMC!T74": -25.0,
            "SOFR_FOMC!R75": -25.0, "SOFR_FOMC!K74": 4.0}
        # a date twice is refused (two rows, one meeting)
        res = put(svc, desk, {"SOFR_FOMC!B75": "17.03.2027"}, book="sofr")
        assert "17.03.2027 listede zaten var (B74)" in res["errors"][0] and b(svc, 75) == "2027-04-28"
    finally:
        svc.stop()


# ---------------------------------------------------------------------------------------------- the watch
def test_watch_items_and_alarms_follow_a_corrected_meeting_and_legacy_ones_are_anchored(tmp_path):
    """K6: an alarm on a meeting's cell is that meeting's - its date corrected, the alarm, the watch item, the day's
    open and the closes kept go with it.  An item an earlier version kept as a cell of a meeting's row is anchored, once,
    to the meeting the row holds when the dashboard starts."""
    svc = make_service(tmp_path)
    db = svc.settings
    try:
        h = svc.history
        a = login(svc, "İzleme Ayşe")
        alarm = svc.alarm_add(a, "tto", "OIS_MAIN!R12", ">=", "999")["alarm"]
        key = svc.watch.key(alarm["subject"])
        assert key == "meeting|tcmb|2027-03-18|R"
        svc.store.close_upsert([(key, "2026-11-02", 12.0), ("meeting|tcmb|2027-03-18|S", "2026-11-02", 36.0)])
        start = h.meetings()
        h.set_calendar(a, [d if d != "2027-03-18" else "2027-03-25" for d in start])                # the date corrected
        w = svc.watch_view(a)["alarms"][0]
        assert w["subject"]["date"] == "2027-03-25" and w["label"] == "PPK 25.03.2027 · Implied bps"   # (a name of its own stays)
        kept = svc.store.closes(["meeting|tcmb|2027-03-25|R", "meeting|tcmb|2027-03-25|S", key], end="2026-11-10")
        assert kept == {"meeting|tcmb|2027-03-25|R": {"2026-11-02": 12.0}, "meeting|tcmb|2027-03-25|S": {"2026-11-02": 36.0}, key: {}}
        # an earlier version's items and alarms: cells of a meeting's row (and one that is not)
        items = {a: [{"id": "x1", "subject": {"kind": "cell", "book": "tto", "ref": "OIS_MAIN!T13"}, "label": "eski"},
                     {"id": "x2", "book": "tto", "ref": "OIS_MAIN!X11", "unit": "pct", "label": "çok eski"},
                     {"id": "x3", "subject": {"kind": "cell", "book": "tto", "ref": "MASA!I60"}, "label": "masa"}]}
        svc.store.put("watch.items", items)
        svc.store.put(svc.watch.MEETINGS_ANCHORED, None)
    finally:
        svc.stop()
    again = Service(db)
    try:
        got = {i["id"]: i["subject"] for i in again.watch.items(a)}
        assert got == {"x1": {"kind": "meeting", "cal": "tcmb", "date": "2027-04-22", "col": "T"},
                       "x2": {"kind": "meeting", "cal": "tcmb", "date": "2027-01-21", "col": "X", "show": "pct"},
                       "x3": {"kind": "cell", "book": "tto", "ref": "MASA!I60"}}
        assert again.watch.anchor_meetings_once() == 0                                              # once
    finally:
        again.stop()
