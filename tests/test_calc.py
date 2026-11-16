"""Each user's own calc sheets (``tto/calc.py``): cells of numbers, texts and formulas over the dashboard's live cells -
kept with the account, evaluated on the calculation thread as the user's pages are, never asking Bloomberg.
(The grid on screen - typing, the formula bar, copy / paste, the drawer - is the browser test's.)"""
import json

import pytest
from starlette.testclient import TestClient

from conftest import ANON, auth, cell, make_service
from tto import calc as cs
from tto import layout as lay
from tto.server import create_app
from tto.service import ServiceError


def login(svc, name, admin=False):
    key = svc.login(name)["user"]
    if admin:
        svc.store.update_account(key, role="admin")
    return key


def save(svc, user, sheet, **change):
    return svc.calcsheets.save_future(user, dict(change, sheet=sheet), "tr").result()


def ev(svc, user, *items, locale="tr"):
    return svc.calcsheets.eval_future(user, list(items), locale).result()


def texts(ans, *addrs):
    return [ans["cells"][a]["t"] if a in ans["cells"] else "" for a in addrs]


# ---------------------------------------------------------------------------------------------- what is typed
@pytest.mark.parametrize("raw, value, fmt", [
    ("10", 10.0, None), ("2,5", 2.5, None), ("1.234,5", 1234.5, None), ("-150", -150.0, None), ("(12,5)", -12.5, None),
    ("25%", 0.25, "0%"), ("12,5%", 0.125, "0.00%"), ("15.12.2026", 46371.0, cs.DATE_FMT), ("doğru", True, None),
    ("YANLIŞ", False, None), ("Spread", "Spread", None), ("'123", "123", None), ("'=A1", "'=A1", None),
    ("=A1*2", "=A1*2", None), ("  ", None, None),
])
def test_what_is_typed_is_kept_as_excel_reads_it(raw, value, fmt):
    """A number in the user's own format (Turkish: 1.234,5), a percentage shown as one, a date as a date, TRUE / FALSE,
    a ' keeping a text a text (and a text that starts with = or ' kept behind one), a formula as typed."""
    got, auto = cs.typed(raw, "tr")
    assert got == value and type(got) is type(value) and auto == fmt
    assert cs.typed("1,234.5", "en")[0] == 1234.5


@pytest.mark.parametrize("text, want", [
    ("=ROUND(1,25;1)", "=ROUND(1.25,1)"),                         # Turkish Excel: ; between arguments, a decimal comma
    ("=SUM(A1:A5;B1)", "=SUM(A1:A5,B1)"),
    ('=IF(A1>0;"a;b";"c,d")', '=IF(A1>0,"a;b","c,d")'),           # (texts as they are)
    ("=SUM({1,2;3,4})", "=SUM({1,2;3,4})"),                       # (an array's ; is a row: not Turkish)
    ("=[sofr]SOFR_FOMC!B9+1", "='[sofr]SOFR_FOMC'!B9+1"),         # the book in the quoted sheet name
    ("=[sofr]'SOFR FOMC'!B9", "='[sofr]SOFR FOMC'!B9"),
    ("='[asw]ASW'!C5", "='[asw]ASW'!C5"),
    ("='C & R'!B5", "='C & R'!B5"),
])
def test_a_formula_is_read_as_the_engine_reads_it(text, want):
    assert cs.normalise(text) == want


def test_a_formula_copied_moves_its_relative_references():
    """As Excel copies: relative references move with the cell, $ ones stay, one that falls off the sheet is #REF!."""
    assert cs.shift_formula("=A1*2", 1, 2, 2, 2) == "=A2*2"
    assert cs.shift_formula("=$A$1+A1+A$1", 1, 2, 3, 3) == "=$A$1+B3+B$1"
    assert cs.shift_formula("=MASA!I60+SUM(A1:A3)", 1, 2, 2, 2) == "=MASA!I61+SUM(A2:A4)"
    assert cs.shift_formula("='C & R'!B5", 1, 1, 1, 2) == "='C & R'!C5"
    assert cs.shift_formula("=A1", 2, 2, 1, 2) == "=#REF!"


# ---------------------------------------------------------------------------------------------- evaluation
def test_numbers_own_references_and_ranges(service):
    u = login(service, "Hesap Sayılar")
    ans = save(service, u, "own", cells={"A1": "10", "A2": "2,5", "A3": "=SUM(A1:A2)", "B1": "=A1*A2", "B2": "=A3/A1",
                                         "B3": "=AVERAGE(A1:A3)", "C1": "Toplam", "C2": '=C1&": "&TEXT(A3;"0.00")',
                                         "C3": "=IF(A3>12;\"büyük\";\"küçük\")", "D1": "=ROUND(1,25;1)",
                                         "D2": "=LET(x;A1*2;x+1)", "D3": "=INDEX(A1:A3;2)", "D4": "=A9+1", "D5": "=TRUE()"})
    assert texts(ans, "A1", "A2", "A3", "B1", "B2", "B3") == ["10", "2,5", "12,5", "25", "1,25", "8,333333333"]
    assert texts(ans, "C1", "C2", "C3", "D1", "D2", "D3", "D4", "D5") == ["Toplam", "Toplam: 12,50", "büyük", "1,3", "21", "2,5", "1",
                                                                         "TRUE"]
    assert ans["cells"]["A3"] == {"t": "12,5", "k": "n", "v": 12.5, "f": "=SUM(A1:A2)"}
    assert ans["cells"]["A2"]["x"] == "2,5" and ans["cells"]["C1"]["k"] == "s"
    assert ans["rev"] == 1 and (ans["rows"], ans["cols"]) == (cs.DEFAULT_ROWS, cs.DEFAULT_COLS)
    # the dashboard's number format (1,234.56): the same sheet, the other way round
    en = ev(service, u, {"key": "k", "sheet": "own"}, locale="en")["sheets"]["k"]
    assert texts(en, "A2", "A3", "B3") == ["2.5", "12.5", "8.333333333"]


def test_workbook_cells_by_sheet_name_other_books_and_names(service):
    """The desk workbook's cells by sheet name (the case does not matter, a quoted one with spaces), its names, the other
    books' with the book in brackets - each the value the user's page shows; a formula leading with a reference takes its
    number format (a date stays a date, a percentage a percentage)."""
    u = login(service, "Hesap Kitaplar")
    ans = save(service, u, "wb", cells={"A1": "=MASA!I60+25", "A2": "=masa!i60", "A3": "='C & R'!B5", "A4": "=[sofr]SOFR_FOMC!B9",
                                        "A5": "=SPOTDATE", "A6": "=Forward!D2", "A7": "=SUM(MASA!I60:I61)", "A8": "=TODAY()",
                                        "B1": "=[asw]ASW!J3", "B2": "='[borsa]bu'!B5", "B3": "=WORKDAY(Forward!D2;2)",
                                        "B4": "=[SOFR.xlsx]sofr_fomc!B9"})
    c = ans["cells"]
    assert c["A1"]["v"] == cell(service, "MASA!I60") + 25 == -125.0 and c["A1"]["t"] == "-125"
    assert c["A2"]["v"] == -150.0
    assert c["A3"]["v"] == pytest.approx(cell(service, "C & R!B5")) and c["A3"]["t"].endswith("%")
    assert c["A4"]["v"] == c["B4"]["v"] == cell(service, "SOFR_FOMC!B9", book="sofr")
    assert c["A5"]["v"] == cell(service, "OIS_MAIN!B2") and c["A5"]["k"] == "d" and c["A5"]["t"].count(".") == 2
    assert c["A6"]["k"] == "d" and c["A6"]["t"].count(".") == 2 and c["A6"]["fm"]
    assert c["A7"]["v"] == -150.0                                               # (I61 is a caption: SUM leaves it out)
    assert c["A8"]["k"] == "d"                                                  # (the workbook's own day)
    assert c["B1"]["v"] == cell(service, "ASW!J3", book="asw") == 120.0
    borsa = cell(service, "bu!B5", book="borsa")
    assert c["B2"].get("v", c["B2"]["t"]) == (0.0 if borsa is None else borsa)  # (an empty cell read by a formula: 0)
    assert c["B3"]["k"] == "d" and c["B3"]["v"] > c["A6"]["v"]


def test_a_users_own_input_changes_their_result_and_nobody_elses(service):
    """The user's own inputs (and "Elle değer") apply, exactly as their pages show; another user's do not reach them -
    asked since the generation they have, their sheet says it did not change."""
    u = login(service, "Hesap Kendi")
    v = login(service, "Hesap Komşu")
    try:
        mine = save(service, u, "s", cells={"A1": "=MASA!I60+25", "A2": "=MASA!D9"})
        theirs = save(service, v, "s", cells={"A1": "=MASA!I60+25"})
        assert mine["cells"]["A1"]["v"] == theirs["cells"]["A1"]["v"] == -125.0
        service.set_inputs(u, "tto", [{"ref": "MASA!I60", "value": "-100"}])
        got = ev(service, u, {"key": "k", "sheet": "s", "since": mine["gen"], "rev": mine["rev"]})["sheets"]["k"]
        assert got["cells"]["A1"]["v"] == -75.0 == cell(service, "MASA!I60", u) + 25
        again = ev(service, v, {"key": "k", "sheet": "s", "since": theirs["gen"], "rev": theirs["rev"]})["sheets"]["k"]
        assert again.get("unchanged") is True                                    # (not their input)
        # a value typed over a formula ("Elle değer") is the user's too
        service.set_inputs(u, "tto", [{"ref": "MASA!D9", "value": "0,4"}], allow_adhoc=True)
        got = ev(service, u, {"key": "k", "sheet": "s", "since": got["gen"], "rev": got["rev"]})["sheets"]["k"]
        assert got["cells"]["A2"]["v"] == pytest.approx(0.4) and got["cells"]["A2"]["t"] == "40,00%"
        assert ev(service, v, {"key": "k", "sheet": "s"})["sheets"]["k"]["cells"]["A1"]["v"] == -125.0
    finally:
        service.reset_inputs(u, "tto")


def test_a_shared_input_reaches_the_sheets_that_read_it(module_service):
    """A desk input (the RET curve) brings again the sheets that read it; one that does not read it says unchanged."""
    svc = module_service
    u = login(svc, "Hesap Ortak")
    desk = login(svc, "Hesap Masa")
    reads = save(svc, u, "ret", cells={"A1": "=Forward!W40"})
    other = save(svc, u, "masa", cells={"A1": "=MASA!I60"})
    try:
        svc.set_inputs(desk, "tto", [{"ref": "Forward!W40", "value": "41,5"}])
        got = ev(svc, u, {"key": "r", "sheet": "ret", "since": reads["gen"], "rev": reads["rev"]},
                 {"key": "m", "sheet": "masa", "since": other["gen"], "rev": other["rev"]})["sheets"]
        assert got["r"]["cells"]["A1"]["v"] == pytest.approx(0.415) and got["m"].get("unchanged") is True
    finally:
        svc.reset_inputs(desk, "tto", ["Forward!W40"], shared=True)


@pytest.mark.parametrize("formula, name", [
    ('=BDP("USDTRY Curncy";"PX_LAST")', "BDP"), ('=1+BDH("XU100 Index","PX_LAST",46000,46010)', "BDH"),
    ('=BDS("X Index";"INDX_MEMBERS")', "BDS"), ('=IFERROR(BFXFORWARD("USDTRY",46400),0)', "BFXFORWARD"),
    ("=_xll.BCURVE(1)", "BCURVE"), ("=_xll.ANYTHING(A1)", "ANYTHING"), ('=SUM(A1,BINTERPOL(A1:A2,B1:B2,1))', "BINTERPOL"),
    ('=RTGET("IDN","USD=","BID")', "RTGET"), ('=bdp("USDTRY Curncy","BID")', "BDP"),
])
def test_bloomberg_functions_are_refused_with_the_reason(service, formula, name):
    """The daily Bloomberg limit is a hard rule: a formula that would ask for data is refused as it is typed - saying
    why - and nothing of the change is kept."""
    u = login(service, "Hesap Bloomberg")
    before = save(service, u, "b", cells={"A1": "1"})
    with pytest.raises(ServiceError) as err:
        save(service, u, "b", cells={"A2": "2", "B1": formula})
    assert err.value.status == 400
    msg = str(err.value)
    assert msg.startswith("B1: " + name) and "Bloomberg" in msg and "günlük veri limiti" in msg
    after = ev(service, u, {"key": "k", "sheet": "b"})["sheets"]["k"]
    assert after["rev"] == before["rev"] and set(after["cells"]) == {"A1"}


def test_a_formula_never_reaches_the_provider(service, monkeypatch):
    """Even a sheet kept by another version that holds one (written straight into the store) asks nothing: the cell says
    why it is an error."""
    u = login(service, "Hesap Eski Sürüm")
    service.store.put("calc." + u, {"sheets": {"old": {"rows": 8, "cols": 6, "rev": 3,
                                                        "cells": {"A1": '=BDP("USDTRY Curncy","PX_LAST")', "A2": "=A1+1"}}}})
    service.calcsheets._users.pop(u, None)
    called = []
    monkeypatch.setattr(service.provider, "call", lambda *a, **k: called.append(a) or 1.0)
    got = ev(service, u, {"key": "k", "sheet": "old"})["sheets"]["k"]
    assert not called
    assert got["cells"]["A1"]["t"] == "#NAME?" and "Bloomberg" in got["cells"]["A1"]["tip"]
    assert got["cells"]["A2"]["t"] == "#NAME?"


def test_errors_are_said_cell_by_cell(service):
    """Excel's error codes, as the dashboard shows them elsewhere, each with what it means; the other cells go on."""
    u = login(service, "Hesap Hatalar")
    ans = save(service, u, "e", cells={"A1": "=1/0", "A2": "=FOO(1)", "A3": "=YOK!A1", "A4": "=[hayal]X!A1", "A5": "=B5",
                                       "B5": "=A5", "A6": "=XLOOKUP(1;A1:A2;A1:A2)", "A7": "=BILINMEYEN_AD+1",
                                       "A8": "=SQRT(-1)", "B1": '="a"+1', "B2": "=A1+1", "B3": "5"})
    c = ans["cells"]
    assert (c["A1"]["t"], c["A1"]["tip"]) == ("#DIV/0!", "Sıfıra bölme")
    assert c["A2"]["t"] == "#NAME?" and c["A2"]["tip"].startswith("Bilinmeyen işlev: FOO")
    assert c["A3"]["t"] == "#REF!" and c["A3"]["tip"] == "Böyle bir sayfa yok: YOK"
    assert c["A4"]["t"] == "#REF!" and c["A4"]["tip"].startswith("Böyle bir kitap yok: [hayal]")
    assert c["A5"]["t"] == c["B5"]["t"] == "#CALC!" and "Döngüsel başvuru" in c["A5"]["tip"] and "B5" in c["B5"]["tip"]
    assert c["A6"]["t"] == "#NAME?" and "XLOOKUP" in c["A6"]["tip"]
    assert c["A7"]["t"] == "#NAME?" and c["A7"]["tip"] == "Bilinmeyen ad: BILINMEYEN_AD"
    assert c["A8"]["t"] == "#NUM!" and c["B1"]["t"] == "#VALUE!" and c["B2"]["t"] == "#DIV/0!"
    assert c["B3"]["t"] == "5"
    for bad in ("=1+", "=SUM(A1", "=" + "(" * 70 + "1" + ")" * 70, "=" + "-" * 40 + "1", "=A1 B1"):
        with pytest.raises(ServiceError) as err:
            save(service, u, "e", cells={"C1": bad})
        assert err.value.status == 400 and str(err.value).startswith("C1: formül")


def test_a_sheet_only_an_administrators_page_shows_is_theirs(service):
    """The Motor page is the administrators': its cells are read in their sheets only."""
    u = login(service, "Hesap Kullanıcı")
    a = login(service, "Hesap Yönetici", admin=True)
    mine = save(service, u, "m", cells={"A1": "=Motor!C5", "A2": "=MASA!I60"})
    assert mine["cells"]["A1"]["t"] == "#REF!" and mine["cells"]["A1"]["tip"] == "Motor sayfası yalnızca yöneticilere açık"
    assert mine["cells"]["A2"]["v"] == -150.0
    theirs = service.calcsheets.save_future(a, {"sheet": "m", "cells": {"A1": "=Motor!C5"}}, "tr", "admin").result()
    assert theirs["cells"]["A1"]["v"] == cell(service, "Motor!C5") == 37.0


def test_the_limits(service, monkeypatch):
    u = login(service, "Hesap Sınırlar")
    save(service, u, "lim", cells={"A1": "1"})
    for change, words in (({"cells": {"A1": "=" + "1+" * 600 + "1"}}, "en fazla 1000 karakter"),
                          ({"cells": {"M1": "1"}}, "en fazla 50 satır × 12 sütun"),
                          ({"cells": {"A51": "1"}}, "en fazla 50 satır × 12 sütun"),
                          ({"cells": {"a1": "1"}}, "hücre adresi geçersiz"),
                          ({"cells": {"A1": "x" * 1001}}, "en fazla 1000 karakter"),
                          ({"rows": 51}, "en fazla 50 satır"), ({"rows": 0}, "en fazla 50 satır"),
                          ({"widths": {"A": 10}}, "40–600 piksel"), ({"widths": {"Z": 100}}, "sütun geçersiz"),
                          ({"fmt": {"A1": "[Red]0"}}, "sayı biçimi geçersiz"),
                          ({"copy": {"from": "A1:B2", "to": "L50"}}, "sığmıyor")):
        with pytest.raises(ServiceError) as err:
            save(service, u, "lim", **change)
        assert err.value.status == 400 and words in str(err.value), (change, str(err.value))
    # a size smaller than the filled cells; growing and cutting back
    save(service, u, "lim", cells={"C5": "x"})
    with pytest.raises(ServiceError) as err:
        save(service, u, "lim", rows=4)
    assert "dolu hücreler" in str(err.value)
    grown = save(service, u, "lim", rows=12, cols=8, widths={"H": 150}, fmt={"H12": "0.00"})
    assert (grown["rows"], grown["cols"], grown["widths"]) == (12, 8, {"H": 150}) and grown["fmt"] == {"H12": "0.00"}
    cut = save(service, u, "lim", rows=5, cols=3)
    assert (cut["rows"], cut["cols"], cut["widths"], cut["fmt"]) == (5, 3, {}, {})
    # how much one evaluation may take: time and cells read
    monkeypatch.setattr(cs, "MAX_READS", 50)
    big = save(service, u, "lim", cells={"A2": "=SUM(Forward!A1:J40)", "A3": "=A1+1"})
    assert big["cells"]["A2"]["t"] == "#CALC!" and "Çok fazla hücre" in big["cells"]["A2"]["tip"]
    assert big["cells"]["A3"]["v"] == 2.0                                        # (the others go on)
    monkeypatch.setattr(cs, "MAX_READS", 200000)
    monkeypatch.setattr(cs, "MAX_RANGE", 100)
    big = save(service, u, "lim", cells={"A2": "=SUM(Forward!A1:J40)+1"})
    assert big["cells"]["A2"]["t"] == "#CALC!" and "Aralık çok büyük" in big["cells"]["A2"]["tip"]
    monkeypatch.setattr(cs, "EVAL_SECONDS", -1.0)
    slow = save(service, u, "lim", cells={"A2": "=A1*2"})
    assert slow["cells"]["A2"]["t"] == "#CALC!" and "süresi" in slow["cells"]["A2"]["tip"]
    assert slow["cells"]["A1"]["v"] == 1.0
    # how many sheets one user keeps, and how big
    monkeypatch.setattr(cs, "EVAL_SECONDS", 2.0)
    monkeypatch.setattr(cs, "MAX_SHEET_BYTES", 300)
    with pytest.raises(ServiceError) as err:
        save(service, u, "lim", cells={"B1": "y" * 400})
    assert "çok büyüdü" in str(err.value)
    with pytest.raises(ServiceError) as err:
        ev(service, u, *[{"key": "k%d" % i, "sheet": "s%d" % i} for i in range(cs.MAX_EVAL_ITEMS + 1)])
    assert "en fazla 40" in str(err.value)


def test_one_request_does_not_hold_the_calculation_thread(service, monkeypatch):
    """The calculation thread is everybody's: the sheets of one request not begun within its time are answered when the
    browser asks again (at least one each time)."""
    u = login(service, "Hesap İş Parçacığı")
    save(service, u, "j1", cells={"A1": "1"})
    save(service, u, "j2", cells={"A1": "2"})
    monkeypatch.setattr(cs, "JOB_SECONDS", -1.0)
    service.bump()                                        # (a new generation: checked again on the calculation thread)
    first = ev(service, u, {"key": "a", "sheet": "j1"}, {"key": "b", "sheet": "j2"})["sheets"]
    assert list(first) == ["a"]
    second = ev(service, u, {"key": "a", "sheet": "j1"}, {"key": "b", "sheet": "j2"})["sheets"]
    assert sorted(second) == ["a", "b"] and second["b"]["cells"]["A1"]["v"] == 2.0


def test_sheets_no_item_names_go_and_there_is_a_cap(service, monkeypatch):
    """A sheet no launchpad or drawer item names any more goes some days after its last change; over the cap the oldest
    of them first - those the items name stay, and when they alone are too many a new one is refused."""
    u = login(service, "Hesap Çok")
    service.set_layout(u, {"launchpads": [{"name": "A", "items": [{"type": "calc", "sheet": "kept"}]}]})
    service.store.put("calc." + u, {"sheets": {"kept": {"rows": 8, "cols": 6, "cells": {"A1": 1}, "at": "2020-01-01T10:00:00"},
                                                "old": {"rows": 8, "cols": 6, "cells": {"A1": 2}, "at": "2020-01-01T10:00:00"},
                                                "new": {"rows": 8, "cols": 6, "cells": {"A1": 3}, "at": "2999-01-01T10:00:00"}}})
    service.calcsheets._users.pop(u, None)
    save(service, u, "fresh", cells={"A1": "4"})
    assert sorted(service.store.get("calc." + u)["sheets"]) == ["fresh", "kept", "new"]
    monkeypatch.setattr(cs, "MAX_SHEETS", 3)
    save(service, u, "more", cells={"A1": "5"})                                    # ("new" or "fresh" goes: no item names it)
    assert len(service.store.get("calc." + u)["sheets"]) == 3 and "kept" in service.store.get("calc." + u)["sheets"]
    service.set_layout(u, {"launchpads": [{"name": "A", "items": [{"type": "calc", "sheet": s} for s in ("kept", "more", "x")]}]})
    monkeypatch.setattr(cs, "MAX_SHEETS", 2)
    with pytest.raises(ServiceError) as err:
        save(service, u, "x", cells={"A1": "6"})
    assert "en fazla 2 hesap tablosu" in str(err.value)


def test_copy_and_fill_move_the_formulas(service):
    """A block pasted from one of the user's sheets keeps its formulas, moved as Excel moves them; over a block that is a
    multiple of it, repeated (Ctrl+D); its number formats go along."""
    u = login(service, "Hesap Kopya")
    save(service, u, "src", cells={"A1": "1", "A2": "2", "A3": "3", "B1": "=A1*10", "C1": "=$A$1+A1"}, fmt={"B1": "0.00"})
    got = save(service, u, "src", copy={"sheet": "src", "from": "B1:C1", "to": "B2:C3"})
    c = got["cells"]
    assert (c["B2"]["f"], c["B3"]["f"], c["C3"]["f"]) == ("=A2*10", "=A3*10", "=$A$1+A3")
    assert texts(got, "B1", "B2", "B3", "C3") == ["10,00", "20,00", "30,00", "4"]
    other = save(service, u, "dst", copy={"sheet": "src", "from": "A1:B1", "to": "D5"})
    assert other["cells"]["E5"]["f"] == "=D5*10" and other["cells"]["E5"]["v"] == 10.0 and (other["rows"], other["cols"]) == (8, 6)


def test_number_formats(service):
    u = login(service, "Hesap Biçim")
    ans = save(service, u, "f", cells={"A1": "1234,5678", "A2": "0,1234", "A3": "46371", "A4": "-5", "B1": "=A1"},
               fmt={"A1": "#,##0.00", "A2": "0.0%", "A3": cs.DATE_FMT, "A4": "0"})
    assert texts(ans, "A1", "A2", "A3", "A4", "B1") == ["1.234,57", "12,3%", "15.12.2026", "-5", "1.234,57"]
    assert ans["cells"]["A3"]["k"] == "d" and ans["cells"]["A2"]["x"] == "12,34%" and ans["cells"]["A3"]["x"] == "15.12.2026"
    assert ans["cells"]["B1"]["fm"] == "#,##0.00"                               # (a formula takes its reference's format)
    back = save(service, u, "f", fmt={"A1": ""}, cells={"A4": ""})
    assert texts(back, "A1") == ["1234,5678"] and "A4" not in back["cells"] and back["fmt"].get("A4") == "0"


# ---------------------------------------------------------------------------------------------- kept, as a file, on a launchpad
def test_a_calc_item_on_a_launchpad_and_in_the_drawer(service):
    """The layout's check: a calc item names its sheet (the same sheet may stand in two places)."""
    u = login(service, "Hesap Düzen")
    got = service.set_layout(u, {"launchpads": [{"name": "A", "items": [{"type": "calc", "sheet": "s1", "title": " Spread  hesabı ", "w": 4}]}],
                                 "drawer": [{"type": "calc", "sheet": "s1", "w": 12, "h": 300}]})
    it = got["launchpads"][0]["items"][0]
    assert {k: it[k] for k in ("type", "sheet", "title", "w", "h")} == {"type": "calc", "sheet": "s1", "title": "Spread hesabı",
                                                                          "w": 4, "h": "auto"}
    assert got["drawer"][0]["sheet"] == "s1" and got["drawer"][0]["h"] == 300
    for bad in ({"type": "calc"}, {"type": "calc", "sheet": "a b"}, {"type": "calc", "sheet": 5}, {"type": "calc", "sheet": "x" * 33}):
        with pytest.raises(ServiceError) as err:
            service.set_layout(u, {"launchpads": [{"name": "A", "items": [bad]}]})
        assert err.value.status == 400 and "hesap tablosu geçersiz" in str(err.value)
    assert lay.ITEM_TYPES["calc"] and service.layout(u)["rev"] == 1


def test_a_launchpad_goes_out_with_its_sheets_and_comes_back_as_new_ones(service):
    u = login(service, "Hesap Dışa")
    v = login(service, "Hesap İçe")
    save(service, u, "s1", cells={"A1": "10", "B1": "=MASA!I60+A1"}, fmt={"A1": "0.00"}, widths={"B": 140})
    service.set_layout(u, {"launchpads": [{"name": "Öğle", "items": [{"type": "calc", "sheet": "s1", "title": "Spread"},
                                                                      {"view": "forward", "panel": "B1"}]}]})
    raw, _ = service.export_launchpad(u, "öğle")
    data = json.loads(raw.decode("utf-8"))
    item = data["items"][0]
    assert item["type"] == "calc" and item["data"]["cells"] == {"A1": 10.0, "B1": "=MASA!I60+A1"}
    assert item["data"]["fmt"] == {"A1": "0.00"} and item["data"]["widths"] == {"B": 140}
    res = service.import_launchpad(v, data)
    got = res["layout"]["launchpads"][0]["items"]
    assert got[0]["type"] == "calc" and got[0]["sheet"] != "s1" and "data" not in got[0] and got[1]["panel"] == "B1"
    theirs = ev(service, v, {"key": "k", "sheet": got[0]["sheet"]})["sheets"]["k"]
    assert texts(theirs, "A1", "B1") == ["10,00", "-140"] and theirs["widths"] == {"B": 140}
    # a file whose sheet would ask Bloomberg is refused as a whole
    item["data"]["cells"]["C1"] = '=BDP("USDTRY Curncy","PX_LAST")'
    with pytest.raises(ServiceError) as err:
        service.import_launchpad(v, data, "Bloomberg")
    assert "içe aktarılan hesap tablosu" in str(err.value) and "Bloomberg" in str(err.value)
    assert [x["name"] for x in service.layout(v)["launchpads"]] == ["Öğle"]


def test_sheets_survive_a_restart(tmp_path):
    svc = make_service(tmp_path)
    try:
        u = login(svc, "Hesap Kalıcı")
        kept = save(svc, u, "k1", cells={"A1": "=MASA!I60+25", "A2": "metin", "A3": "2,5"}, fmt={"A3": "0.00"}, widths={"A": 120})
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        got = ev(again, u, {"key": "k", "sheet": "k1"})["sheets"]["k"]
        assert got["cells"] == kept["cells"] and (got["rev"], got["widths"]) == (kept["rev"], {"A": 120})
    finally:
        again.stop()


# ---------------------------------------------------------------------------------------------- over HTTP
def test_over_http(service):
    client = TestClient(create_app(service=service))                          # (no "with": the shared service stays up)
    assert client.get("/static/js/calc.js").status_code == 200
    h = auth(service, "Hesap Zeynep")
    r = client.post("/api/calc/save", json={"sheet": "w1", "cells": {"A1": "=MASA!I60+25", "A2": "1,5"}}, headers=h)
    assert r.status_code == 200 and r.json()["cells"]["A1"]["t"] == "-125" and r.json()["cells"]["A2"]["v"] == 1.5
    r = client.post("/api/calc/save?lang=en", json={"sheet": "w1", "cells": {"A3": "1,234.5"}}, headers=h)
    assert r.json()["cells"]["A3"]["t"] == "1234.5"                             # (the user's number format, both ways)
    gen = r.json()["gen"]
    r = client.post("/api/calc/eval?lang=en", json={"items": [{"key": "x", "sheet": "w1", "since": gen, "rev": r.json()["rev"]},
                                                      {"key": "y", "sheet": "nothing-yet"}]}, headers=h)
    assert r.status_code == 200
    got = r.json()["sheets"]
    assert got["x"]["unchanged"] is True and got["y"]["cells"] == {} and got["y"]["rev"] == 0
    r = client.post("/api/calc/save", json={"sheet": "w1", "cells": {"B1": '=BDP("USDTRY Curncy","PX_LAST")'}}, headers=h)
    assert r.status_code == 400 and "Bloomberg" in r.json()["error"]
    assert client.post("/api/calc/eval", json={"items": "x"}, headers=h).status_code == 400
    assert client.post("/api/calc/save", json={"sheet": "a b"}, headers=h).status_code == 400
    assert client.post("/api/calc/nope", json={}, headers=h).status_code == 404
    assert client.post("/api/calc/eval", json={"items": [{"sheet": "w1"}]}, headers=ANON).status_code == 401
    foreign = dict(h, Origin="http://kotu-site.example")
    assert client.post("/api/calc/save", json={"sheet": "w1", "cells": {"A1": "1"}}, headers=foreign).status_code == 403
