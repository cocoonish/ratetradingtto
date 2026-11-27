"""Each scenario its own TLREF normalization date (OIS · PPK → SENARYOLAR: *Normalleşme tarihi*; ``extras.NORM_SC_*``).

The desk, 27.11.2026: "Normallesme tarihini de senaryoya gore degistirebileyim".

SENARYOLAR' column U (S1 Baz, S2 Hawkish, S3 Dovish), each user's own, defaults to the date in use (Parametreler →
Kullanılan tarih, L5); its days from the OIS spot n_s (OIS_MAIN!N3:N5).  A scenario's TLREF runs elevated until its own
date: its levels on IMPLIED RATES, its 1Y figure, its MPC OIS window rates, every reader of its PPK path (the O/N and
zero table among them) and DV01 Risk's scenario − implied.  The implied path, the solver and every other path keep the
date in use.

The checks: at the defaults every scenario runs to the date in use (the workbook as before: test_normallesme_ppk's
checks, and N3:N5 = M3); a later date for S2 and one before the spot for S3 move S2's and S3's figures and nothing of
S1, the implied path or the solver; DV01 Risk's deviation stays the page's row difference; with the switch off a typed
date changes nothing; each user's dates are their own and the page shows the column."""
from __future__ import annotations

import pytest

from conftest import cell, make_service
from test_normallesme_ppk import _book, at, moved, switch_on
from tto import extras as ex
from tto.xl.model import parse_a1
from tto.xl.tokenizer import index_to_col
from tto.xl.values import serial_to_date

H, L0, COMMON, LATE, EARLY = 0.39, 0.3585, 60, 400, -10
ROWS = range(ex.NORM_LEVEL_ROWS[0], ex.NORM_LEVEL_ROWS[1] + 1)


@pytest.fixture(scope="module")
def book():
    return _book(True)


def _cells(book, extra):
    si = book.model.sheet_index["OIS_MAIN"]
    return {(si, parse_a1(a)): v for a, v in extra.items()}


@pytest.fixture(scope="module")
def calcs(book):
    """The switch on (TLREF 39 %, normal 35.85 %, the date in use 60 days after the OIS spot): every scenario at its
    default, and S2 400 days out, S3 before the spot."""
    spot = at(book, "OIS_MAIN!B2")
    base = switch_on(book, spot + COMMON, L0, _cells(book, {"J2": H}))
    own = switch_on(book, spot + COMMON, L0, _cells(book, {"J2": H, "U4": spot + LATE, "U5": spot + EARLY}))
    return spot, base, own


def test_by_default_every_scenario_runs_to_the_date_in_use(book, calcs):
    spot, base, _ = calcs
    assert at(book, "OIS_MAIN!U2") == "Normalleşme tarihi"
    assert [at(book, "OIS_MAIN!" + a, base) for a in ex.NORM_SC_DATES] == [spot + COMMON] * 3     # (the date in use, L5)
    assert [at(book, "OIS_MAIN!" + a, base) for a in ex.NORM_SC_DAYS] == [float(COMMON)] * 3 == \
        [at(book, "OIS_MAIN!M3", base)] * 3
    gap = at(book, "OIS_MAIN!M5", base)
    assert abs(gap - (H - L0)) < 1e-15
    for r in ROWS:
        k = r + ex.NORM_MOTOR_ROW
        day = at(book, "Motor!C%d" % k, base)
        for level, _, _, path in ex.NORM_SCENARIOS:
            want = at(book, "Motor!%s%d" % (path, k), base) + (gap if day < COMMON else 0.0)
            assert at(book, "OIS_MAIN!%s%d" % (level, r), base) == want, (level, r)


def test_a_scenario_with_its_own_date(book, calcs):
    spot, base, own = calcs
    assert [at(book, "OIS_MAIN!" + a, own) for a in ex.NORM_SC_DAYS] == [float(COMMON), float(LATE), 0.0]
    gap = at(book, "OIS_MAIN!M5", own)
    # the implied path, the solver and S1: the same bits
    for ref in (["OIS_MAIN!S%d" % r for r in ROWS] + ["OIS_MAIN!X%d" % r for r in ROWS]
                + ["OIS_MAIN!%s%d" % (c, r) for c in ("R", "T", "BD", "BM", "BN", "BO") for r in ROWS]
                + ["Motor!B%d" % r for r in range(5728, 5814)] + ["Motor!%s%d" % (c, r) for c in "HKNP" for r in range(4, 85)]
                + ["OIS_MAIN!" + a for a in ("B5", "D5", "H5", "J5", "R3", "S3", "S4", "S5", "AE9", "AA9", "AF20", "AB20")]):
        assert at(book, ref, own) == at(book, ref, base), ref
    later = early = 0
    for r in ROWS:
        k = r + ex.NORM_MOTOR_ROW
        day = at(book, "Motor!C%d" % k, own)
        y, z, s = (at(book, "OIS_MAIN!%s%d" % (c, r), own) for c in "YZS")
        # S2 runs elevated until its own date, S3 is normal from the spot
        assert y == at(book, "Motor!N%d" % k, own) + (gap if day < LATE else 0.0), r
        assert z == at(book, "Motor!P%d" % k, own), r
        later += COMMON <= day < LATE
        early += day < COMMON
        # DV01 Risk's scenario − implied: the page's row difference (S2 / S3), the same as before for S1
        if r < 42 and isinstance(s, float):
            col = index_to_col(ex.NORM_DV01_FIRST + r - ex.NORM_LEVEL_ROWS[0])
            for row, level in ((66, "X"), (67, "Y"), (68, "Z")):
                got = at(book, "DV01_RISK!%s%d" % (col, row), own)
                want = (at(book, "OIS_MAIN!%s%d" % (level, r), own) - s) * 10000
                assert abs(got - want) < 1e-6, (col, row, got, want)
            assert at(book, "DV01_RISK!%s66" % col, own) == at(book, "DV01_RISK!%s66" % col, base)
    assert later >= 3 and early >= 1                        # (meetings on both sides of each date: the test bites)
    # the 1Y figures: S2's day 365 is before its date, S3 has none
    assert at(book, "OIS_MAIN!R4", own) == at(book, "OIS_MAIN!R4", base) + gap
    assert abs(at(book, "OIS_MAIN!T4", own) - at(book, "OIS_MAIN!T4", base) - round(gap * 10000, 1)) < 0.11
    assert at(book, "OIS_MAIN!R5", own) == at(book, "OIS_MAIN!R5", base)  # (365 days: past the date in use as well)
    # the window rates and every reader of the paths: S2's and S3's moved, S1's did not
    assert any(at(book, "OIS_MAIN!BE%d" % r, own) != at(book, "OIS_MAIN!BE%d" % r, base) for r in range(84, 100))
    assert any(at(book, "OIS_MAIN!BF%d" % r, own) != at(book, "OIS_MAIN!BF%d" % r, base) for r in range(84, 100))
    on_s2 = [at(book, "OIS_MAIN!AG%d" % r, own) - at(book, "OIS_MAIN!AG%d" % r, base) for r in range(9, 27)]
    assert max(on_s2) > 0.01                                 # (S2's O/N up by its longer stretch, ~ the gap over it)
    assert [at(book, "OIS_MAIN!AF%d" % r, own) for r in range(9, 27)] == [at(book, "OIS_MAIN!AF%d" % r, base) for r in range(9, 27)]


def test_off_a_typed_date_changes_nothing(book):
    """The switch off: a date typed for a scenario stands in its cell and moves nothing else (n_s 0)."""
    spot = at(book, "OIS_MAIN!B2")
    si = book.model.sheet_index["OIS_MAIN"]
    typed = book.engine.layer(("normsc", "off"), book.engine.shared, {(si, parse_a1("U4")): spot + LATE})
    assert at(book, "OIS_MAIN!N4", typed) == 0.0
    assert moved(book, book.engine.shared, typed) == ["OIS_MAIN!U4"]


def test_each_users_dates_are_their_own_and_the_page_shows_them(tmp_path):
    svc = make_service(tmp_path / "sc")
    try:
        a, b = "norm-senaryo-a", "norm-senaryo-b"
        spot = cell(svc, "OIS_MAIN!B2")
        for user in (a, b):
            svc.login(user)
            svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!L2", "value": "Açık"},
                                         {"ref": "OIS_MAIN!L3", "value": serial_to_date(spot + COMMON).strftime("%d.%m.%Y")}])
        svc.set_inputs(a, "tto", [{"ref": "OIS_MAIN!U4", "value": serial_to_date(spot + LATE).strftime("%d.%m.%Y")}])
        assert cell(svc, "OIS_MAIN!N4", a) == float(LATE) and cell(svc, "OIS_MAIN!N4", b) == float(COMMON)
        assert cell(svc, "OIS_MAIN!U4", b) == spot + COMMON
        view = svc.view(a, "ois")
        panel = next(p for p in view["panels"] if p["id"] == "B2")
        data = panel["data"]
        assert "U" in data["c"]
        j = data["c"].index("U")
        head = data["rows"][data["r"].index(2)][j]
        assert (head.get("t") if isinstance(head, dict) else head) == "Normalleşme tarihi"
        s2 = data["rows"][data["r"].index(4)][j]
        assert s2.get("i") and s2.get("v") == spot + LATE                    # (an input of the user's, their date)
        # deleted: back to the date in use
        svc.set_inputs(a, "tto", [{"ref": "OIS_MAIN!U4", "value": ""}])
        assert cell(svc, "OIS_MAIN!U4", a) == spot + COMMON and cell(svc, "OIS_MAIN!N4", a) == float(COMMON)
    finally:
        svc.stop()
