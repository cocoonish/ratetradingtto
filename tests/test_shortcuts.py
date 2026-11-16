"""Shortcuts in the inputs: amounts as the desk says them ("5m", "250k", "1,5mn", "2mr") in amount cells, and dates
("1A", "3M", "2H", "ON", "TN", "SN", "ay sonu", "IMM", "+5") in date cells and the blotter's value date - from the
cell's natural start, on its pair's calendar and spot convention.  Nothing that is not a shortcut parses differently;
a formula ("=") is never one; rate and price cells keep what they did.

The calendars are the desk's own lists (TRY: 29.10.2026 Cumhuriyet Bayramı, 01.01.2027; USD: Veterans Day 11.11.2026,
Thanksgiving 26.11.2026; EUR: Good Friday 03.04.2026, Easter Monday 06.04.2026) and days planted for the test.  The
service runs on the workbook's recorded market (03.11.2026: USDTRY spot 04.11, EURTRY spot 05.11, TRY OIS spot 04.11)
on a clock the tests move."""
from __future__ import annotations

import datetime as dt

import pytest

from conftest import cell
from tto import shortcuts as sc
from tto.config import Settings
from tto.inputs import InputError, parse_amount, parse_date, parse_input
from tto.service import EngineThread, Service
from tto.xl.engine import Clock
from tto.xl.values import date_to_serial, serial_to_date

D = dt.date
RECORDED = D(2026, 11, 3)


def serial(d: dt.date) -> float:
    return float(date_to_serial(d))


def on(svc, day):
    """The dashboard on ``day`` (at noon): TODAY() and everything that follows it computed again."""
    svc.books["tto"].engine.clock.fixed = serial(day) + 0.5
    svc.et.call_at(EngineThread.WRITE, lambda: [b.engine.clock_tick() for b in svc.books.values()])
    svc.bump()


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    """A service on the recorded market whose clock the tests move (``on``)."""
    svc = Service(Settings(data_dir=str(tmp_path_factory.mktemp("kisayol")), mode="replay", history=False),
                  clock=Clock(serial(RECORDED) + 0.5))
    yield svc
    svc.stop()


def typed(svc, user, ref, text, book="tto"):
    """Type ``text`` into ``ref``: (the value stored, the answer's shortcut note of the cell, the errors)."""
    res = svc.set_inputs(user, book, [{"ref": ref, "value": text}])
    v = cell(svc, ref, user, book)
    return (serial_to_date(v) if type(v) is float and 20000 < v < 80000 else v), (res.get("shortcuts") or {}).get(ref), res["errors"]


# ---------------------------------------------------------------------------------------------- amounts
@pytest.mark.parametrize("text, lang, expected", [
    ("5m", "tr", 5e6), ("5mn", "tr", 5e6), ("5M", "tr", 5e6), ("5 mn", "tr", 5e6), ("5mln", "tr", 5e6),
    ("250k", "tr", 250e3), ("250K", "en", 250e3), ("250 bin", "tr", 250e3),
    ("1,5mn", "tr", 1.5e6), ("1.5mn", "tr", 1.5e6), ("1.5mn", "en", 1.5e6), ("1,5mn", "en", 1.5e6),   # either convention
    ("2b", "tr", 2e9), ("2mr", "tr", 2e9), ("2MR", "tr", 2e9), ("2 mr", "tr", 2e9), ("2mlr", "tr", 2e9), ("2bn", "en", 2e9),
    ("1,25mr", "tr", 1.25e9), ("-10m", "tr", -10e6),
])
def test_each_amount_shortcut(text, lang, expected):
    assert parse_input(text, kind="amount", lang=lang) == pytest.approx(expected, rel=1e-15)
    assert parse_amount(text, lang) == pytest.approx(expected, rel=1e-15)


@pytest.mark.parametrize("text, lang, expected", [
    ("5000000", "tr", 5e6), ("5.000.000", "tr", 5e6), ("5,000,000", "en", 5e6), ("5.000.000,50", "tr", 5000000.5),
    ("5,000,000.50", "en", 5000000.5), ("12.345", "tr", 12345.0), ("12.345", "en", 12.345), ("12,345", "en", 12345.0),
    ("1,5", "tr", 1.5), ("1.5", "en", 1.5), ("1e6", "tr", 1e6), ("-250000", "tr", -250e3), (" 1 000 000 ", "tr", 1e6),
    ("35%", "tr", 0.35), ("(12,5)", "tr", -12.5),
])
def test_plain_amounts_parse_as_before(text, lang, expected):
    """An amount cell reads a plain number exactly as it did: grouped thousands by the user's number format, a decimal
    otherwise - the shorthand is only a suffix."""
    assert parse_input(text, kind="amount", lang=lang) == pytest.approx(expected, rel=1e-15)


@pytest.mark.parametrize("text", ["beş milyon", "5 milyon TL", "m", "mr", "5x", "5 m r", "5mrr", "1A", "ay sonu", "IMM"])
def test_an_amount_not_understood_is_refused(text):
    with pytest.raises(InputError):
        parse_input(text, kind="amount")
    assert parse_input("+5", kind="amount") == 5.0                # (a date shortcut's "+5" is a plain 5 in an amount)


def test_rate_and_price_cells_never_take_an_amount_or_a_date_shortcut():
    """"5m" in a rate is nonsense: a rate / price cell keeps it as the text it always was (the page shows it as typed,
    nothing is multiplied), and so does any cell that is no amount."""
    for kind, pct in (("pct", True), ("number", False), ("auto", False), ("auto", True)):
        for text in ("5m", "250k", "2mr", "1A", "ay sonu", "IMM"):
            assert parse_input(text, pct, False, kind) == text, (kind, text)
    assert parse_input("35,5", percent_cell=True) == pytest.approx(0.355)
    assert parse_input("49,9977", kind="number") == pytest.approx(49.9977)


# ---------------------------------------------------------------------------------------------- what is a date shortcut
@pytest.mark.parametrize("text, expected", [
    ("1A", ("M", 1)), ("1a", ("M", 1)), (" 1 A ", ("M", 1)), ("1 ay", ("M", 1)), ("1M", ("M", 1)), ("1m", ("M", 1)),
    ("3A", ("M", 3)), ("6A", ("M", 6)), ("18M", ("M", 18)), ("1Y", ("M", 12)), ("2y", ("M", 24)), ("1 yıl", ("M", 12)),
    ("2H", ("W", 2)), ("2W", ("W", 2)), ("2 hf", None), ("ON", ("ON", 0)), ("O/N", ("ON", 0)), ("on", ("ON", 0)),
    ("TN", ("TN", 0)), ("T/N", ("TN", 0)), ("SN", ("SN", 0)), ("s/n", ("SN", 0)), ("ay sonu", ("EOM", 0)),
    ("AY SONU", ("EOM", 0)), ("aysonu", ("EOM", 0)), ("Ay  Sonu", ("EOM", 0)), ("EOM", ("EOM", 0)), ("IMM", ("IMM", 0)),
    ("imm", ("IMM", 0)), ("İMM", ("IMM", 0)), ("+5", ("BD", 5)), ("+ 5", ("BD", 5)), ("+12", ("BD", 12)),
])
def test_what_each_date_shortcut_means(text, expected):
    assert sc.date_shortcut(text) == expected


@pytest.mark.parametrize("text", [
    "15.12.2026", "15/12/26", "2026-12-15", "15 Ara 2026", "15-Dec-2026", "46371", "46371,0", "1.5", "5", "+45000",
    "-5", "+5,5", "=1A", "=C60+7", "= 3M", "", "   ", "1AB", "A1", "M", "1 ay sonra", "yarın", "T+1", "1.5M", "1,5A",
    "10G", "1D", "0.5Y", "1A1", "IMM2", "+5d", "ay", "sonu", "spot", "Spot", "LONG", "B", "1234A", "+1234",
])
def test_anything_else_is_no_date_shortcut(text):
    assert sc.date_shortcut(text) is None
    assert sc.date_shortcut(None) is None and sc.date_shortcut(46371.0) is None


# ---------------------------------------------------------------------------------------------- against a planted calendar
#: made-up holidays: a Friday that 1M lands on, a Wednesday two weeks on, the month's last Monday, New Year's Eve, the
#: March IMM date, the Friday after the spot
PLANTED = {D(2026, 12, 4), D(2026, 11, 18), D(2026, 11, 30), D(2026, 12, 31), D(2027, 3, 17), D(2026, 11, 6)}
START, TODAY = D(2026, 11, 4), D(2026, 11, 3)


@pytest.mark.parametrize("text, start, expected", [
    ("1A", START, D(2026, 12, 7)),        # 04.12 a holiday, then the weekend: Monday
    ("1M", START, D(2026, 12, 7)),
    ("3A", START, D(2027, 2, 4)),
    ("6A", START, D(2027, 5, 4)),
    ("1Y", START, D(2027, 11, 4)),
    ("2H", START, D(2026, 11, 19)),       # 18.11 a holiday: the next day
    ("2W", START, D(2026, 11, 19)),
    ("1M", D(2027, 1, 29), D(2027, 3, 1)),   # EDATE: 28.02 (a Sunday) - then the next business day, as the workbook rolls
    ("SN", START, D(2026, 11, 5)),
    ("+5", START, D(2026, 11, 12)),       # 06.11 does not count
    ("+0", START, START),
    ("ay sonu", START, D(2026, 11, 27)),  # 30.11 a holiday: the business day before it
    ("ay sonu", D(2026, 11, 27), D(2026, 12, 30)),   # already the month's end: the next month's (31.12 a holiday)
    ("IMM", START, D(2026, 12, 16)),      # the third Wednesday of December
    ("IMM", D(2026, 12, 16), D(2027, 3, 18)),        # after it: March's - a holiday, so the day after
    ("IMM", D(2027, 3, 16), D(2027, 3, 18)),
])
def test_each_date_shortcut_against_a_planted_calendar(text, start, expected):
    assert sc.resolve(sc.date_shortcut(text), start, TODAY, PLANTED) == expected


def test_overnight_and_tom_next_count_from_today():
    """ON is the business day after today, TN the second - whatever the cell's start; SN the business day after it."""
    assert sc.resolve(("ON", 0), D(2027, 6, 1), TODAY, PLANTED) == D(2026, 11, 4)
    assert sc.resolve(("TN", 0), D(2027, 6, 1), TODAY, PLANTED) == D(2026, 11, 5)
    assert sc.resolve(("TN", 0), START, D(2026, 11, 4), PLANTED) == D(2026, 11, 9)     # 06.11 planted, then the weekend
    assert sc.resolve(("SN", 0), D(2026, 11, 5), TODAY, PLANTED) == D(2026, 11, 9)
    assert sc.next_imm(D(2026, 3, 18)) == D(2026, 6, 17) and sc.next_imm(D(2026, 12, 31)) == D(2027, 3, 17)


# ---------------------------------------------------------------------------------------------- in the cells
def test_date_shortcuts_in_the_cells_count_on_the_pairs_calendar_and_spot(desk):
    """Forward's value date is USDTRY's (T+1 on TRY + USD: 11.11 Veterans Day does not count), the EURTRY quote matrix's
    dates EURTRY's (T+2 on TRY + EUR), the OIS date-to-date rate's the TRY money market's (T+1 on the TRY list); the
    stored value is the date, what was typed comes back for the cell's tooltip."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Kısayol Tarih")["user"]
    try:
        assert day(svc, "Forward!I2") == D(2026, 11, 4) and day(svc, "Forward!K2") == D(2026, 11, 5)
        assert day(svc, "OIS_MAIN!B2") == D(2026, 11, 4)
        for text, expected in (("1A", D(2026, 12, 4)), ("1M", D(2026, 12, 4)), ("3A", D(2027, 2, 4)), ("6A", D(2027, 5, 4)),
                               ("1Y", D(2027, 11, 4)), ("2H", D(2026, 11, 18)), ("2W", D(2026, 11, 18)), ("ON", D(2026, 11, 4)),
                               ("TN", D(2026, 11, 5)), ("SN", D(2026, 11, 5)), ("ay sonu", D(2026, 11, 30)),
                               ("IMM", D(2026, 12, 16)), ("+5", D(2026, 11, 12))):
            got, note, errors = typed(svc, u, "Forward!D2", text)
            assert errors == [] and got == expected, (text, got)
            assert note == {"typed": text, "date": serial(expected), "text": expected.strftime("%d.%m.%Y")}, note
        # the TRY money market: Veterans Day is a business day of TRY
        got, note, _ = typed(svc, u, "OIS_MAIN!B123", "+5")
        assert got == D(2026, 11, 11) and note["typed"] == "+5"
        # EURTRY: its own spot date (05.11), one month on is a Saturday
        got, _, _ = typed(svc, u, "EK_FWD!B104", "1A")
        assert got == D(2026, 12, 7) == day(svc, "EK_FWD!B104", u)
        # the free row of the USDTRY matrix: "1A" is the 1M row's own date
        got, _, _ = typed(svc, u, "EK_FWD!B11", "1A")
        assert got == day(svc, "EK_FWD!B5", u) == D(2026, 12, 4)
        # an end date counts from the start of its row / calculator
        svc.set_inputs(u, "tto", [{"ref": "MASA!C60", "value": "01.12.2026"}])
        got, _, _ = typed(svc, u, "MASA!E60", "3A")
        assert got == D(2027, 3, 1) and cell(svc, "MASA!G60", u) == 90.0
        svc.set_inputs(u, "tto", [{"ref": "Forward!AH5", "value": "07.12.2026"}])
        assert typed(svc, u, "Forward!AH6", "2W")[0] == D(2026, 12, 21)
        assert typed(svc, u, "Forward!AH5", "2W")[0] == D(2026, 11, 18)        # the 1st date itself: from the spot
    finally:
        svc.reset_inputs(u, "tto")


def day(svc, ref, user=None):
    v = cell(svc, ref, user)
    return serial_to_date(v) if type(v) is float else v


def test_a_us_or_a_target2_holiday_moves_the_pairs_dates_and_nothing_else(desk):
    """Spot Monday 26.10.2026: one month on is Thanksgiving - USDTRY takes Friday, the TRY money market Thursday.
    Wednesday 25.11: USDTRY's ON is the 27th, TLREF's the 26th.  Monday 02.03.2026: EURTRY spot 04.03 - one month on
    is a Saturday, then Easter Monday: 07.04."""
    svc = desk
    u = svc.login("Kısayol Takvim")["user"]
    try:
        on(svc, D(2026, 10, 23))
        assert typed(svc, u, "Forward!D2", "1A")[0] == D(2026, 11, 27)
        assert typed(svc, u, "OIS_MAIN!B123", "1A")[0] == D(2026, 11, 26)
        on(svc, D(2026, 11, 25))
        assert [typed(svc, u, "Forward!D2", t)[0] for t in ("ON", "TN", "SN")] == [D(2026, 11, 27), D(2026, 11, 30), D(2026, 11, 30)]
        assert typed(svc, u, "OIS_MAIN!B123", "ON")[0] == D(2026, 11, 26)
        on(svc, D(2026, 3, 2))
        assert typed(svc, u, "EK_FWD!B104", "1A")[0] == D(2026, 4, 7)
        assert typed(svc, u, "Forward!D2", "1A")[0] == D(2026, 4, 3)          # Good Friday: USDTRY settles
    finally:
        svc.reset_inputs(u, "tto")
        on(svc, RECORDED)


def test_a_holiday_planted_in_the_desks_list_moves_the_shortcuts(desk):
    """A day added to the TRY list (Ayarlar → Tatiller) is a holiday of every TRY pair at once: the month's end and the
    business days count around it."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Kısayol Tatil")["user"]
    tr = svc.holidays()["lists"]["TRY"]["items"]
    try:
        svc.set_holidays(u, tr + [{"date": "30.11.2026", "name": "Deneme"}, {"date": "06.11.2026", "name": "Deneme 2"}])
        assert typed(svc, u, "Forward!D2", "ay sonu")[0] == D(2026, 11, 27)
        assert typed(svc, u, "OIS_MAIN!B123", "ay sonu")[0] == D(2026, 11, 27)
        assert typed(svc, u, "Forward!D2", "+5")[0] == D(2026, 11, 13)       # 06.11 and 11.11 (USD) do not count
        assert typed(svc, u, "OIS_MAIN!B123", "+5")[0] == D(2026, 11, 12)    # 06.11 does not count
    finally:
        svc.set_holidays(u, tr)
        svc.reset_inputs(u, "tto")


def test_pasted_blocks_take_shortcuts_cell_by_cell_and_a_start_pasted_with_them(desk):
    """The free forward list: a start and "1A" pasted side by side - the end counts from the start pasted with it
    (01.12.2026 + 1M is New Year's Day: the next business day); through the server's paste too; a row whose pair is
    EURTRY counts on EURTRY's calendar from its own spot."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Kısayol Yapıştır")["user"]
    try:
        res = svc.set_inputs(u, "tto", [{"ref": "EK_FWD!B69", "value": "01.12.2026"}, {"ref": "EK_FWD!C69", "value": "1A"},
                                        {"ref": "EK_FWD!C68", "value": "2H"}])
        assert res["errors"] == [] and set(res["shortcuts"]) == {"EK_FWD!C69", "EK_FWD!C68"}
        assert day(svc, "EK_FWD!C69", u) == D(2027, 1, 4) and day(svc, "EK_FWD!C68", u) == D(2026, 11, 18)
        res = svc.paste(u, "tto", "EK_FWD!B70", "01.12.2026\t3A\r\n")
        assert res["errors"] == [] and day(svc, "EK_FWD!C70", u) == D(2027, 3, 1) and res["shortcuts"]["EK_FWD!C70"]["typed"] == "3A"
        svc.set_inputs(u, "tto", [{"ref": "EK_FWD!A71", "value": "EURTRY"}])
        assert typed(svc, u, "EK_FWD!C71", "1A")[0] == D(2026, 12, 7)
        assert day(svc, "EK_FWD!B71", u) == D(2026, 11, 5)                   # (its start: EURTRY's spot date)
    finally:
        svc.reset_inputs(u, "tto")


def test_a_list_of_days_takes_the_item_a_shortcut_lands_on(desk):
    """VİOP Target's far contract is a list of days kept as text: "ay sonu" from the near leg's spot is November's
    contract, stored as that item; "Spot" is the list's own word, never a shortcut."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Kısayol VİOP")["user"]
    try:
        got, note, errors = typed(svc, u, "VIOP!M331", "ay sonu")
        assert errors == [] and got == "30.11.2026" and note["text"] == "30.11.2026"
        assert typed(svc, u, "VIOP!M331", "spot")[:2] == ("Spot", None)
    finally:
        svc.reset_inputs(u, "tto")


def test_formulas_rates_and_plain_values_are_untouched(desk):
    """"=" is a formula - "=1A" is a formula that cannot be read, never a shortcut; a rate, a price, a text cell keep
    "5m" / "1A" as the text they always were; every plain value typed into a date, an amount, a rate, a number or a text
    cell is stored exactly as the input parser always made it - and no shortcut is said for it."""
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Kısayol Dokunma")["user"]
    try:
        before = cell(svc, "MASA!C171", u)
        res = svc.set_inputs(u, "tto", [{"ref": "MASA!C171", "value": "=1A"}])
        assert res["errors"] and "shortcuts" not in res and cell(svc, "MASA!C171", u) == before
        res = svc.set_inputs(u, "tto", [{"ref": "MASA!C171", "value": "=C60+7"}])
        assert res["errors"] == [] and "shortcuts" not in res
        assert cell(svc, "MASA!C171", u) == cell(svc, "MASA!C60", u) + 7
        for ref in ("Forward!AH9", "Forward!AH8", "EK_FWD!D20", "Forward!V56"):     # a rate, a spot, swap points, an ISIN
            for text in ("5m", "2mr", "1A", "IMM"):
                v, note, errors = typed(svc, u, ref, text)
                assert v == text and note is None and errors == [], (ref, text, v)
        plain = {
            "Forward!D2": ["15.12.2026", "15/12/26", "2026-12-15", "15 Ara 2026", "46371", "15.12.26"],      # a date
            "Forward!O45": ["5000000", "5.000.000", "1,5", "(12,5)", "1e6", "35%"],                        # an amount
            "Forward!AH9": ["4,25", "4,25%", "0,0425", "1", "35%"],                                        # a rate
            "Forward!AH8": ["50,5", "50.5", "12.345", "1.234,56", "(12,5)"],                              # a price
            "Forward!V56": ["TRT150328T24", "123", "15.12.2026"],                                          # a text
        }
        book = svc.books["tto"]
        for ref, texts in plain.items():
            si, rc = book.cell(ref)
            d = book.inputs[(si, rc)]
            fmt = book.model.numfmts[book.model.sheets[si].styles.get(rc, 0)]
            from tto.xl import numfmt
            for text in texts:
                res = svc.set_inputs(u, "tto", [{"ref": ref, "value": text}])
                want = parse_input(text, numfmt.is_percent_format(fmt), numfmt.is_date_format(fmt), d.kind,
                                   book.options_for(si, rc), "tr", d.aliases)
                assert res["errors"] == [] and "shortcuts" not in res, (ref, text, res)
                assert cell(svc, ref, u) == want, (ref, text, cell(svc, ref, u), want)
        assert cell(svc, "Forward!D2", u) == parse_date("15.12.26")
    finally:
        svc.reset_inputs(u, "tto")


def test_amount_cells_take_the_shortcuts_rate_cells_do_not(desk):
    svc = desk
    on(svc, RECORDED)
    u = svc.login("Kısayol Tutar")["user"]
    try:
        for text, expected in (("5m", 5e6), ("5mn", 5e6), ("250k", 250e3), ("1,5mn", 1.5e6), ("2b", 2e9), ("2mr", 2e9)):
            assert typed(svc, u, "Forward!O45", text)[:3] == (expected, None, []), text
        res = svc.set_inputs(u, "tto", [{"ref": "Forward!O45", "value": "1.5mn"}], lang="en")
        assert res["errors"] == [] and cell(svc, "Forward!O45", u) == 1.5e6
        assert typed(svc, u, "OIS_MAIN!F2", "5k")[0] == 5000.0                  # (an amount of the OIS page)
        assert typed(svc, u, "Forward!AH9", "5m")[0] == "5m"                     # a rate: kept as typed, as ever
    finally:
        svc.reset_inputs(u, "tto")


def test_the_blotters_value_date_takes_the_same_shortcuts(desk):
    """Günlük İşlemler's value date: "1A", "ay sonu", "IMM", "+5" from the pair's spot, on its calendar; the answer says
    what was typed (the form shows "1A → 04.12.2026" under the box); a date is a date, as before."""
    svc = desk
    on(svc, RECORDED)
    for text, pair, iso in (("1A", "USDTRY", "2026-12-04"), ("3M", "USDTRY", "2027-02-04"), ("ay sonu", "USDTRY", "2026-11-30"),
                            ("IMM", "USDTRY", "2026-12-16"), ("+5", "USDTRY", "2026-11-12"), ("2H", "USDTRY", "2026-11-18"),
                            ("1A", "EURTRY", "2026-12-07"), ("TN", "USDTRY", "2026-11-05")):
        q = svc.quote_forward("Kısayol Blotter", {"value_date": text, "pair": pair, "basis": "RET_MID"})
        assert q["value_date_iso"] == iso and q["value_date_typed"] == text, (text, pair, q["value_date_iso"])
    q = svc.quote_forward("Kısayol Blotter", {"value_date": "15.12.2026", "basis": "RET_MID"})
    assert q["value_date_iso"] == "2026-12-15" and "value_date_typed" not in q
    assert serial_to_date(svc.et.call(svc._tenor_date, "1A", "USDTRY")) == D(2026, 12, 4)
