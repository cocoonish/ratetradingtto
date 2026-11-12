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
