"""A date typed without its year (the desk, 28.11.2026: "Bir de tarih girdilerinde yil girmeden de algilayabilmeli. 26/12
yazdigimda otomatik 2026, 1/2 yazdigimda otomatik 2027 getirecek ornegin su anda").

* The one parser (``inputs.parse_date``, its rule ``inputs.day_month``): ``26/12``, ``26.12``, ``26-12``, ``26 Ara`` are
  the next such day from today on - 28.11.2026: 26.12.2026, ``1/2`` 01.02.2027, today's own day today -; an end from its
  start on when that is later (``1/3`` after 15.06.2027: 01.03.2028); in a cell that asks about the past the last such
  day (``datecells.PAST``: DV01 Risk's "Dünkü tarih", Masa's "Anket ayı"; a Trades trade's day, its close).  The year
  turn, 29 February (the nearest one there is), a day no year has (refused), a date with its year as ever, a value read
  without a today never given a year.
* Every typed path reads it so: a cell (the echo in its tooltip, a list of days kept as text, a pasted block's start, a
  meeting's date), Günlük İşlemler's forward value date (the form says what it became) and OIS dates (an end from its
  start), the holiday lists, Fiyatlama (``pricing.parse_when``), Trades (``tradebook._Form.date``), the meeting calendar
  and holiday list of the settings page (``history.js parseTrDate``, under Node).  A number cell keeps ``26.12`` a number.

The service runs on a clock at 28.11.2026 (the desk's example), on the workbook's recorded market."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import auth, cell
from tto import datecells
from tto.config import Settings
from tto.inputs import InputError, day_month, parse_date, parse_input, yearless
from tto.pricing import parse_when
from tto.service import Service
from tto.tradebook import _Form
from tto.views import load_views
from tto.xl import numfmt
from tto.xl.engine import Clock
from tto.xl.model import COLS, parse_range
from tto.xl.values import date_to_serial, serial_to_date

D = dt.date
TODAY = D(2026, 11, 28)                    # the desk's "su anda"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def serial(d: dt.date) -> float:
    return float(date_to_serial(d))


def day(text, today=TODAY, past=False, after=None):
    v = parse_date(text, today, past, after)
    return serial_to_date(v) if v is not None else None


# ---------------------------------------------------------------------------------------------- the rule
def test_the_desks_example():
    assert day("26/12") == D(2026, 12, 26)
    assert day("1/2") == D(2027, 2, 1)


@pytest.mark.parametrize("text", ["26/12", "26.12", "26-12", " 26/12 ", "26 Ara", "26 Aralık", "26 ARALIK", "26 aralik",
                                  "26 Dec", "26.Ara"])
def test_ways_of_writing_a_day_and_month(text):
    assert yearless(text) == (26, 12)
    assert day(text) == D(2026, 12, 26)


@pytest.mark.parametrize("text, ahead, back", [
    ("28/11", D(2026, 11, 28), D(2026, 11, 28)),        # today is both: from today on, up to today
    ("27/11", D(2027, 11, 27), D(2026, 11, 27)),        # yesterday's day: next year ahead, yesterday back
    ("29/11", D(2026, 11, 29), D(2025, 11, 29)),
    ("1/1", D(2027, 1, 1), D(2026, 1, 1)),
    ("31/12", D(2026, 12, 31), D(2025, 12, 31)),
    ("3 Ekim", D(2027, 10, 3), D(2026, 10, 3)),
    ("3 EKİM", D(2027, 10, 3), D(2026, 10, 3)),
    ("1 Şubat", D(2027, 2, 1), D(2026, 2, 1)),
    ("01.02", D(2027, 2, 1), D(2026, 2, 1)),
])
def test_next_and_last(text, ahead, back):
    assert day(text) == ahead
    assert day(text, past=True) == back


def test_the_year_turn():
    eve, first = D(2026, 12, 31), D(2027, 1, 1)
    assert day("31/12", eve) == eve and day("1/1", eve) == first
    assert day("31/12", first) == D(2027, 12, 31) and day("31/12", first, past=True) == eve
    assert day("1/1", first) == first == day("1/1", first, past=True)
    assert day("2/1", eve, past=True) == D(2026, 1, 2)


def test_29_february_is_the_nearest_there_is():
    assert day("29/2") == D(2028, 2, 29) and day("29.02", past=True) == D(2024, 2, 29)
    assert day("29/2", D(2028, 2, 29)) == D(2028, 2, 29) == day("29/2", D(2028, 2, 29), past=True)
    assert day("29/2", D(2028, 3, 1)) == D(2032, 2, 29) and day("29/2", D(2028, 2, 28), past=True) == D(2024, 2, 29)
    assert day("29/2", D(2097, 3, 1)) == D(2104, 2, 29)               # (2100 is no leap year)
    assert day("28/2") == D(2027, 2, 28)


@pytest.mark.parametrize("text", ["31/4", "31.06", "30/2", "32/1", "0/1", "1/0", "1/13", "00/00", "99/99"])
def test_a_day_no_year_has_is_refused(text):
    assert day(text) is None and day(text, past=True) is None
    with pytest.raises(InputError):
        parse_input(text, date_cell=True, today=TODAY)


@pytest.mark.parametrize("text", ["26/12/2025", "26.12.25", "2025-12-26", "26 Ara 2025"])
def test_a_date_with_its_year_keeps_it(text):
    assert day(text) == D(2025, 12, 26) == day(text, past=True) == day(text, after=D(2027, 1, 1))


@pytest.mark.parametrize("text", ["12", "2612", "1.5Y", "3M", "26/12/", "/12", "26//12", "26/12x", "1/2/3/4", "x/y", ""])
def test_what_is_no_day(text):
    assert yearless(text) is None and day(text) is None


def test_a_value_read_without_today_is_never_given_a_year():
    # what a workbook or a store holds always has its year: a text there ("1-3", "26.12") is never guessed one
    assert parse_date("26/12") is None and parse_date("26.12") is None and parse_date("1-3") is None
    assert parse_date("26.12.2026") == serial(D(2026, 12, 26))


def test_an_end_counts_from_its_start():
    assert day("1/3", after=D(2027, 6, 15)) == D(2028, 3, 1)
    assert day("15/6", after=D(2027, 6, 15)) == D(2027, 6, 15)          # (on its start: the user's own day)
    assert day("1/3", after=D(2026, 1, 1)) == D(2027, 3, 1)             # (a start before today: from today)
    assert day("1/3", past=True, after=D(2027, 6, 15)) == D(2026, 3, 1)   # (back: the start does not count)
    assert day_month(1, 3, serial(TODAY), after=serial(D(2027, 6, 15))) == D(2028, 3, 1)   # (serials too)
    assert day_month(1, 3, "2026-11-28") == D(2027, 3, 1)                                  # (an ISO day too)


def test_typed_into_cells_of_each_kind():
    assert parse_input("26/12", date_cell=True, today=TODAY) == serial(D(2026, 12, 26))
    assert parse_input("26/12", kind="date", today=TODAY, past=True) == serial(D(2025, 12, 26))
    assert parse_input("1/3", kind="date", today=TODAY, after=D(2027, 6, 15)) == serial(D(2028, 3, 1))
    # a number cell keeps "26.12" a number (a rate, a price) and "26/12" a text; a percent cell 26,12 %
    assert parse_input("26.12", today=TODAY) == 26.12 and parse_input("26/12", today=TODAY) == "26/12"
    assert parse_input("26.12", percent_cell=True, today=TODAY) == pytest.approx(0.2612)
    assert parse_input("26/12", kind="text", today=TODAY) == "26/12"
    with pytest.raises(InputError):
        parse_input("26/12", kind="amount", today=TODAY)
    # a list of days kept as text (VİOP's contracts): the day is its item - never one the list does not hold
    days = ["30.12.2026", "29.01.2027", "Spot"]
    assert parse_input("30/12", kind="list", options=days, today=TODAY) == "30.12.2026"
    assert parse_input("29.1", kind="list", options=days, today=TODAY) == "29.01.2027"
    with pytest.raises(InputError):
        parse_input("30/12", kind="list", options=days, today=D(2026, 12, 31))       # (30.12.2027 is not listed)
    # nobody said which day: the computer's
    assert parse_input("1/1", date_cell=True) == serial(day_month(1, 1, dt.date.today()))


def test_fiyatlama_reads_it():
    assert parse_when("26/12", TODAY) == ("d", serial(D(2026, 12, 26)))
    assert parse_when("1.2", TODAY) == ("d", serial(D(2027, 2, 1)))
    assert parse_when("12", TODAY) == ("m", 12.0)                       # (a bare number is still an FRA's months)
    assert parse_when("2Y3M", TODAY) == ("m", 27.0) and parse_when("2W", TODAY) == ("w", 2.0)
    assert parse_when("31/4", TODAY) is None
    assert parse_when("26/12") == ("d", serial(day_month(26, 12, dt.date.today())))     # (the page: the computer's day)


def test_trades_reads_it():
    """A Trades trade's day and its close look back; its value date, maturity, delivery ahead - from its start on."""
    f = _Form({"trade_date": "27/11", "settle_date": "1/12", "end_date": "1/3", "delivery": "5/1", "close_date": "1/12"},
              "tr", TODAY, lambda cal: set())
    td, _ = f.date("trade_date", "İşlem tarihi", TODAY, ("TRY",), required=True, past=True)
    assert td == D(2026, 11, 27)
    sd, _ = f.date("settle_date", "Valör", td, ("TRY",))
    assert sd == D(2026, 12, 1)
    end, _ = f.date("end_date", "Vade", D(2027, 6, 15), ("TRY",))
    assert end == D(2028, 3, 1)                                         # (after its start)
    close, _ = f.date("close_date", "Kapanış tarihi", TODAY, ("TRY",), past=True)
    assert close == D(2025, 12, 1)                                      # (a close is never ahead: the last 1 December)
    assert f.echo == {"trade_date": "27/11 → 27.11.2026", "settle_date": "1/12 → 01.12.2026",
                      "end_date": "1/3 → 01.03.2028", "close_date": "1/12 → 01.12.2025"} and not f.errors
    g = _Form({"trade_date": "31/4"}, "tr", TODAY, lambda cal: set())
    assert g.date("trade_date", "İşlem tarihi", TODAY, ("TRY",), past=True)[0] is None and "trade_date" in g.errors


def test_the_cells_that_ask_about_the_past_are_date_inputs():
    """``datecells.PAST``: each a date input of a page, the past by what it is ("Dünkü tarih": WORKDAY(SPOTDATE,-2))."""
    model = datecells.model_of("tto")
    declared = {}
    for v in load_views():
        if v["book"] != "tto":
            continue
        for inp in v.get("inputs", []):
            sheet, _, addr = inp["range"].rpartition("!")
            sheet = sheet.strip("'") or v.get("sheet")
            r1, c1, r2, c2 = parse_range(addr)
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    declared[(sheet, r * COLS + c)] = inp
    cells = datecells.past_cells("tto", model)
    assert len(cells) == len(datecells.PAST["tto"]) == 2
    for si, rc in cells:
        sheet = model.sheets[si]
        inp = declared.get((sheet.name, rc))
        xf = sheet.styles.get(rc, 0)
        assert inp is not None and (inp.get("kind") == "date" or numfmt.is_date_format(model.xfs[xf][0])), (sheet.name, rc)
    si, rc = model.cell_ref("DV01_RISK!C112")
    assert "WORKDAY(SPOTDATE,-2" in model.templates[model.sheets[si].fml[rc]].replace(" ", "")
    assert datecells.past_cells("asw", datecells.model_of("asw")) == frozenset()


# ---------------------------------------------------------------------------------------------- the typed paths
@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    svc = Service(Settings(data_dir=str(tmp_path_factory.mktemp("yilsiz")), mode="replay", history=False),
                  clock=Clock(serial(TODAY) + 0.5))
    for u in ("yilsiz-hucre", "yilsiz-bitis", "yilsiz-gecmis", "yilsiz-ppk", "yilsiz-blotter", "yilsiz-tatil"):
        auth(svc, u, admin=u in ("yilsiz-ppk", "yilsiz-tatil"))
    yield svc
    svc.stop()


def typed(svc, user, *pairs):
    res = svc.set_inputs(user, "tto", [{"ref": r, "value": t} for r, t in pairs])
    return res


def at(svc, ref, user):
    v = cell(svc, ref, user)
    return serial_to_date(v) if type(v) is float and 20000 < v < 80000 else v


def test_a_cell(desk):
    u = "yilsiz-hucre"
    res = typed(desk, u, ("Forward!D2", "26/12"))
    assert res["errors"] == [] and at(desk, "Forward!D2", u) == D(2026, 12, 26)
    # what was typed goes back for the cell's tooltip, as a shortcut's ("Kısayol: 26/12 → 26.12.2026")
    assert res["shortcuts"]["Forward!D2"] == {"typed": "26/12", "date": serial(D(2026, 12, 26)), "text": "26.12.2026"}
    res = typed(desk, u, ("Forward!D2", "1.2"))
    assert at(desk, "Forward!D2", u) == D(2027, 2, 1) and res["shortcuts"]["Forward!D2"]["text"] == "01.02.2027"
    res = typed(desk, u, ("EK_FWD!B11", "26 Ara"))
    assert at(desk, "EK_FWD!B11", u) == D(2026, 12, 26) and not res["errors"]
    res = typed(desk, u, ("Forward!D2", "31/4"))
    assert res["errors"] and "tarih anlaşılamadı" in res["errors"][0] and at(desk, "Forward!D2", u) == D(2027, 2, 1)
    res = typed(desk, u, ("Forward!D2", "26.12.2027"))                 # (with its year: as ever, no echo)
    assert at(desk, "Forward!D2", u) == D(2027, 12, 26) and not res.get("shortcuts")
    desk.reset_inputs(u, "tto")


def test_an_end_counts_from_its_start_typed_with_it_or_before(desk):
    """The broken-date block's end (``Forward!C60``, ``"from": "C59"``): from its start on when that is later."""
    u = "yilsiz-bitis"
    typed(desk, u, ("Forward!C59", "15/6"), ("Forward!C60", "1/3"))      # (a start typed in the same block counts)
    assert at(desk, "Forward!C59", u) == D(2027, 6, 15) and at(desk, "Forward!C60", u) == D(2028, 3, 1)
    typed(desk, u, ("Forward!C59", "1/12"))
    typed(desk, u, ("Forward!C60", "1/3"))
    assert at(desk, "Forward!C60", u) == D(2027, 3, 1)
    # Masa's date-to-date (E60 from C60, its formulas' start): the same
    typed(desk, u, ("MASA!C60", "15.06.2027"))
    res = typed(desk, u, ("MASA!E60", "15/9"))
    assert at(desk, "MASA!E60", u) == D(2027, 9, 15) and res["shortcuts"]["MASA!E60"]["text"] == "15.09.2027"
    desk.reset_inputs(u, "tto")


def test_the_cells_that_ask_about_the_past(desk):
    u = "yilsiz-gecmis"
    res = typed(desk, u, ("DV01_RISK!C112", "27/11"), ("MASA!S155", "1/11"))
    assert not res["errors"]
    assert at(desk, "DV01_RISK!C112", u) == D(2026, 11, 27)            # "Dünkü tarih": yesterday, not next year
    assert at(desk, "MASA!S155", u) == D(2026, 11, 1)                  # "Anket ayı": this month's survey
    typed(desk, u, ("DV01_RISK!C112", "1/12"))
    assert at(desk, "DV01_RISK!C112", u) == D(2025, 12, 1)             # (the last 1 December)
    typed(desk, u, ("DV01_RISK!C112", "28/11"))
    assert at(desk, "DV01_RISK!C112", u) == TODAY
    res = typed(desk, u, ("Forward!D2", "27/11"))                      # (a value date looks ahead)
    assert at(desk, "Forward!D2", u) == D(2027, 11, 27)
    desk.reset_inputs(u, "tto")


def test_a_meetings_date(desk):
    """A meeting's date in OIS · PPK's list is read so too (it moves its meeting by the calendar's rule): the list's
    own date typed without its year changes nothing."""
    u = "yilsiz-ppk"
    first = at(desk, "OIS_MAIN!P10", u)
    assert isinstance(first, dt.date) and first >= TODAY
    res = typed(desk, u, ("OIS_MAIN!P10", first.strftime("%d/%m").lstrip("0")))
    assert res["errors"] == [] and at(desk, "OIS_MAIN!P10", u) == first


def test_gunluk_islemler(desk):
    """The forward's value date (the form says what it became) and an OIS's dates (an end from its start on)."""
    q = desk.quote_forward("yilsiz-blotter", {"dir": "B", "amount": "10m", "value_date": "26/12", "basis": "RET_MID"})
    assert q["value_date"] == serial(D(2026, 12, 26)) and q["value_date_typed"] == "26/12"
    q = desk.quote_forward("yilsiz-blotter", {"dir": "B", "amount": "10m", "value_date": "26.12.2026", "basis": "RET_MID"})
    assert q["value_date"] == serial(D(2026, 12, 26)) and "value_date_typed" not in q
    p = desk._ois_payload({"strategy": "mpc", "start": "10/12", "end": "21/1"})
    assert p["start"] == serial(D(2026, 12, 10)) and p["end"] == serial(D(2027, 1, 21))
    p = desk._ois_payload({"strategy": "mpc", "start": "15/6", "end": "1/3"})
    assert p["end"] == serial(D(2028, 3, 1))
    with pytest.raises(Exception):
        desk._ois_payload({"strategy": "mpc", "start": "31/4", "end": "1/3"})


def test_a_temporary_copy(desk):
    """A temporary copy of TARİH ARASI FORWARD (its strip of dates, ``copies.py``): the copy's own start counts."""
    u = "yilsiz-kopya"
    auth(desk, u)
    one = desk.copy_action(u, "open", {"view": "masa", "panel": "B10"})["copy"]
    try:
        res = desk.copy_action(u, "inputs", {"copy": one["id"], "items": [{"ref": "MASA!C60", "value": "15/6"},
                                                                          {"ref": "MASA!E60", "value": "26.12.2027"}]})
        assert res["errors"] == []
        res = desk.copy_action(u, "inputs", {"copy": one["id"], "items": [{"ref": "MASA!E60", "value": "1/3"}]})
        assert res["errors"] == []

        def copy_day(ref):
            v = desk.et.call(lambda: desk.copies.calc(u, desk.copies.find(u, one["id"])).value(ref))
            return serial_to_date(v)

        assert copy_day("MASA!C60") == D(2027, 6, 15) and copy_day("MASA!E60") == D(2028, 3, 1)
    finally:
        desk.copy_action(u, "close", {"copy": one["id"]})


def test_the_holiday_list(desk):
    u = "yilsiz-tatil"
    items = desk.holidays()["lists"]["TRY"]["items"]
    try:
        desk.set_holidays(u, items + [{"date": "1/5", "name": "Deneme"}], "TRY")
        assert "2027-05-01" in {x["date"] for x in desk.holidays()["lists"]["TRY"]["items"]}
    finally:
        desk.set_holidays(u, items, "TRY")


# ---------------------------------------------------------------------------------------------- the settings page
HARNESS = r"""
import { parseTrDate } from './parsetr.mjs';
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const cases = JSON.parse(raw);
  process.stdout.write(JSON.stringify(cases.map(([t, o]) => parseTrDate(t, o === null ? undefined : o))));
});
"""


def test_the_settings_pages_parser_has_the_same_rule(tmp_path):
    """``history.js parseTrDate`` (the meeting calendar, the holiday lists): the same days as the server's rule."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is needed to read history.js parseTrDate")
    with open(os.path.join(ROOT, "tto", "static", "js", "pages", "history.js"), encoding="utf-8") as fh:
        src = fh.read()
    body = re.search(r"^export function parseTrDate\(.*?^}\n", src, re.S | re.M).group(0)
    (tmp_path / "parsetr.mjs").write_text(body, encoding="utf-8")
    (tmp_path / "run.mjs").write_text(HARNESS, encoding="utf-8")
    on = {"today": "2026-11-28"}
    cases = [["26/12", on], ["1/2", on], ["26.12", on], ["26-12", on], ["28/11", on], ["27/11", on],
             ["27/11", dict(on, past=True)], ["1/12", dict(on, past=True)], ["29/2", on], ["29/2", dict(on, past=True)],
             ["31/4", on], ["1/13", on], ["0/1", on], ["10.12.2026", on], ["2026-12-10", None], ["31.02.2026", None],
             ["1/1", {"today": "2026-12-31"}], ["31/12", {"today": "2027-01-01", "past": True}], ["x", on], ["1/1", None]]
    res = subprocess.run([node, str(tmp_path / "run.mjs")], input=json.dumps(cases), capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    want = ["2026-12-26", "2027-02-01", "2026-12-26", "2026-12-26", "2026-11-28", "2027-11-27", "2026-11-27", "2025-12-01",
            "2028-02-29", "2024-02-29", None, None, None, "2026-12-10", "2026-12-10", None, "2027-01-01", "2026-12-31", None,
            day_month(1, 1, dt.date.today()).isoformat()]
    assert got == want
    # the server's rule gives the same days
    for (text, opts), iso in zip(cases[:14], want[:14]):
        if iso is not None and yearless(text):
            assert day(text, D.fromisoformat(opts["today"]), bool(opts.get("past"))).isoformat() == iso
