"""Number formats are rendered like Excel does (Turkish and English)."""
import pytest

from tto.xl import numfmt

TR = numfmt.get_locale("tr")
EN = numfmt.get_locale("en")


@pytest.mark.parametrize("value, fmt, tr, en", [
    (1234567.891, "#,##0", "1.234.568", "1,234,568"),
    (1234567.891, "#,##0.00", "1.234.567,89", "1,234,567.89"),
    (0.3555, "0.00%", "35,55%", "35.55%"),
    (0.3555, "0%", "36%", "36%"),
    (-12.345, "0.0", "-12,3", "-12.3"),
    (2.5, "0", "3", "3"),                         # half away from zero
    (46329.0, "dd.mm.yyyy", "03.11.2026", "03.11.2026"),
    (46329.0, "d.m.yyyy", "3.11.2026", "3.11.2026"),
    (46329.0, "mmm yy", "Kas 26", "Nov 26"),
    (46329.5, "hh:mm", "12:00", "12:00"),
    (5.0, "000", "005", "005"),
    (1234.5, '#,##0.0" bp"', "1.234,5 bp", "1,234.5 bp"),
    (0.0, '#,##0;-#,##0;"-"', "-", "-"),
    (-5.0, "#,##0;(#,##0)", "(5)", "(5)"),
])
def test_render(value, fmt, tr, en):
    assert numfmt.render(value, fmt, TR)[0].strip() == tr
    assert numfmt.render(value, fmt, EN)[0].strip() == en


def test_colour_sections():
    text, colour = numfmt.render(-3.0, "0.0;[Red]-0.0", TR)
    assert text.strip() == "-3,0" and colour == "red"
    assert numfmt.render(3.0, "0.0;[Red]-0.0", TR)[1] is None


def test_general_format():
    assert numfmt.render(0.1 + 0.2, "General", TR, general_digits=10)[0] == "0,3"
    assert numfmt.render(49.9977, "General", TR)[0] == "49,9977"
    assert numfmt.render(1e15, "General", EN)[0] in ("1E+15", "1000000000000000")
    assert numfmt.render("metin", "General", TR)[0] == "metin"


def test_format_classification():
    assert numfmt.is_percent_format("0.00%")
    assert not numfmt.is_percent_format("0.00")
    assert numfmt.is_date_format("dd.mm.yyyy")
    assert numfmt.is_date_format("d mmm yy")
    assert not numfmt.is_date_format("#,##0.00")
    assert not numfmt.is_date_format('0" gün"')
    assert numfmt.is_number_format("General") and numfmt.is_number_format('#,##0.0" bp"') and numfmt.is_number_format("0%")
    assert not numfmt.is_number_format("dd\\.mm\\.yyyy") and not numfmt.is_number_format("hh:mm")
    assert not numfmt.is_number_format("@") and not numfmt.is_number_format('"-"')


ACCOUNTING = '_-* #,##0.00_-;\\-* #,##0.00_-;_-* "-"??_-;_-@_-'


@pytest.mark.parametrize("fmt, n, want", [
    # a user's own number of decimals (tto/decimals.py): only the decimals change - Excel's "Increase / Decrease Decimal"
    ("0.00%", 3, "0.000%"), ("0.00%", 0, "0%"), ("0%", 2, "0.00%"),                           # a percent stays one
    ("#,##0", 2, "#,##0.00"), ("#,##0.0;[Red]-#,##0.0", 3, "#,##0.000;[Red]-#,##0.000"),     # grouping, colour
    ("#,##0;\\(#,##0\\);\\-", 1, "#,##0.0;\\(#,##0.0\\);\\-"),                                 # brackets; "-" for a zero
    ("[Color10]+0.0;[Red]-0.0;0.0", 2, "[Color10]+0.00;[Red]-0.00;0.00"),                    # a sign, the zero's digits
    (ACCOUNTING, 4, ACCOUNTING.replace("0.00_", "0.0000_")),                                 # its zero's "-" stays
    ("#,##0,,\\M;\\-#,##0,,\\M;0", 2, "#,##0.00,,\\M;\\-#,##0.00,,\\M;0.00"),                  # millions: before the commas
    ('#,##0.0,," mn"', 0, '#,##0,," mn"'), ('#,##0.0" bp"', 2, '#,##0.00" bp"'),             # a suffix stays
    ("_-[$$-409]* #,##0_ ", 2, "_-[$$-409]* #,##0.00_ "), ('0"/15"', 1, '0.0"/15"'),          # a currency, a literal
    ("0.00E+00", 4, "0.0000E+00"), ("0.0#", 3, "0.000"), ("0.000000", 2, "0.00"),             # the exponent's own digits
    ("General", 3, "0.000"), ("General", 0, "0"),                                            # General: no grouping
    ("dd\\.mm\\.yyyy", 2, "dd\\.mm\\.yyyy"), ("hh:mm", 2, "hh:mm"), ("@", 2, "@"), ('"-"', 2, '"-"'),   # never touched
])
def test_with_decimals_changes_only_the_decimals(fmt, n, want):
    assert numfmt.with_decimals(fmt, n) == want


@pytest.mark.parametrize("value, fmt, n, tr, en", [
    (0.3555, "0.00%", 3, "35,550%", "35.550%"),
    (-1234.5, "#,##0;\\(#,##0\\);\\-", 2, "(1.234,50)", "(1,234.50)"),
    (0.0, ACCOUNTING, 4, "-", "-"),
    (-2.5, ACCOUNTING, 0, "-3", "-3"),
    (6265432.1, "#,##0,,\\M;\\-#,##0,,\\M;0", 2, "6,27M", "6.27M"),
    (49.9977, "General", 2, "50,00", "50.00"),
    (46329.0, "dd\\.mm\\.yyyy", 3, "03.11.2026", "03.11.2026"),
])
def test_a_value_with_a_users_decimals(value, fmt, n, tr, en):
    g = numfmt.with_decimals(fmt, n)
    assert numfmt.render(value, g, TR)[0].strip() == tr
    assert numfmt.render(value, g, EN)[0].strip() == en
    assert numfmt.with_decimals(fmt, 99) == numfmt.with_decimals(fmt, numfmt.MAX_DECIMALS)
