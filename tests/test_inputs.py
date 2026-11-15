"""What users type or paste is understood the way the same text would be in their Excel."""
import pytest

from tto.inputs import InputError, parse_clipboard, parse_date, parse_input, parse_number


@pytest.mark.parametrize("text, lang, prefer_decimal, expected", [
    ("35,55", "tr", False, 35.55),
    ("35.55", "tr", False, 35.55),            # cannot be a grouped integer -> decimal
    ("1.234,56", "tr", False, 1234.56),
    ("1,234.56", "tr", False, 1234.56),
    ("12.345", "tr", False, 12345.0),         # Turkish Excel reads this as twelve thousand ...
    ("12.345", "en", False, 12.345),          # ... English Excel as a decimal
    ("12,345", "en", False, 12345.0),
    ("12,345", "tr", False, 12.345),
    ("500.000", "tr", False, 500000.0),
    ("1.000.000", "tr", False, 1000000.0),
    ("1,000,000", "en", False, 1000000.0),
    ("-1.250", "tr", False, -1250.0),
    ("0.355", "tr", False, 0.355),            # a leading zero is never a thousands group
    ("36.555", "tr", True, 36.555),           # rates / prices: always a decimal
    ("1234.5", "tr", False, 1234.5),
    ("35%", "tr", False, 0.35),
    ("%35", "tr", False, 0.35),
    ("(12,5)", "tr", False, -12.5),
    ("−3,5", "tr", False, -3.5),              # typographic minus
    (" 1 234,5 ", "tr", False, 1234.5),
    ("1e3", "tr", False, 1000.0),
])
def test_parse_number(text, lang, prefer_decimal, expected):
    assert parse_number(text, lang, prefer_decimal) == pytest.approx(expected, rel=1e-15)


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "3.11.2026", "1,2,3", "12a", "--1"])
def test_parse_number_rejects(text):
    assert parse_number(text) is None


@pytest.mark.parametrize("text, expected", [
    ("3.11.2026", 46329.0), ("03.11.2026", 46329.0), ("3/11/26", 46329.0), ("2026-11-03", 46329.0),
    ("3 Kas 2026", 46329.0), ("3-Nov-2026", 46329.0), ("15.12.2026", 46371.0),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["31.02.2026", "abc", "2026", "12.13.2026"])
def test_parse_date_rejects(text):
    assert parse_date(text) is None


def test_percent_cells_follow_excels_automatic_percent_entry():
    assert parse_input("35,5", percent_cell=True) == pytest.approx(0.355)
    assert parse_input("35,5%", percent_cell=True) == pytest.approx(0.355)
    assert parse_input("0,355", percent_cell=True) == pytest.approx(0.355)
    assert parse_input("1", percent_cell=True) == pytest.approx(0.01)       # 1 typed in a % cell is 1 %
    assert parse_input("36.555", percent_cell=True) == pytest.approx(0.36555)
    assert parse_input("-0,5", percent_cell=True) == pytest.approx(-0.5)
    assert parse_input(0.355, percent_cell=True) == 0.355                  # numbers from the API are taken as they are


def test_plain_cells():
    assert parse_input("12.345") == 12345.0
    assert parse_input("12.345", lang="en") == 12.345
    assert parse_input("  ") is None
    assert parse_input(None) is None
    assert parse_input("RECEIVE") == "RECEIVE"
    assert parse_input("doğru") is True
    assert parse_input("FALSE") is False
    assert parse_input("15.12.2026") == 46371.0            # a date typed into any cell
    assert parse_input("35%") == pytest.approx(0.35)
    assert parse_input("TRT150328T24", kind="text") == "TRT150328T24"
    assert parse_input("123", kind="text") == "123"


def test_date_cells():
    assert parse_input("15.12.2026", date_cell=True) == 46371.0
    assert parse_input("46371", date_cell=True) == 46371.0
    with pytest.raises(InputError):
        parse_input("yarın", date_cell=True)


def test_amount_cells_take_the_desks_shorthand():
    """A nominal is typed the way the desk says it: "100m" was text before, and a total over it quietly empty."""
    for text, expected in (("100m", 100e6), ("100M", 100e6), ("2,5mn", 2.5e6), ("2,5 milyon", 2.5e6), ("1,5 mio", 1.5e6),
                           ("500k", 500e3), ("500 bin", 500e3), ("1,5b", 1.5e9), ("2 milyar", 2e9), ("100.000.000", 100e6),
                           ("35000000", 35e6), ("1e6", 1e6), ("-10m", -10e6)):
        assert parse_input(text, kind="amount") == expected, text
    assert parse_input("100,000,000", kind="amount", lang="en") == 100e6
    assert parse_input("1.5m", kind="amount", lang="en") == 1.5e6
    assert parse_input(25e6, kind="amount") == 25e6 and parse_input("", kind="amount") is None
    for text in ("yüz milyon", "100 TL", "m", "35%x"):
        with pytest.raises(InputError):
            parse_input(text, kind="amount")               # not understood: refused, never kept as text
    assert parse_input("3m") == "3m"                       # any other cell (a tenor, say) keeps it as typed


def test_options_are_matched_case_insensitively():
    assert parse_input("receive", options=["PAY", "RECEIVE"]) == "RECEIVE"
    assert parse_input("1", options=["0", "1"]) == 1.0
    # the Turkish dotted capital İ and the dotless ı: typed either way, it is the item of the list
    assert parse_input("viop", options=["Offshore", "OIS", "VİOP", "RET"]) == "VİOP"
    assert parse_input("DIŞ", options=["iç", "dış"]) == "dış"


def test_bad_numbers_are_refused():
    with pytest.raises(InputError):
        parse_input(float("nan"))
    with pytest.raises(InputError):
        parse_input("x" * 3000)


def test_clipboard_as_excel_copies_it():
    assert parse_clipboard("35,10%\t35,30%\r\n35,20%\t35,40%\r\n") == [["35,10%", "35,30%"], ["35,20%", "35,40%"]]
    assert parse_clipboard("a\tb\tc\nd") == [["a", "b", "c"], ["d", "", ""]]
    assert parse_clipboard("tek") == [["tek"]]
