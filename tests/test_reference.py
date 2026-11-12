"""Full recalculation against an independent calculator.

``tools/lo_reference.py`` exported each workbook with its Bloomberg cells frozen, let LibreOffice
recalculate it from scratch and stored LibreOffice's value of every formula in ``tests/data/lo_*.json.gz``.
Here the engine recalculates the same workbook from scratch and must agree.

The only cells allowed to differ are downstream of the TRY curve solver in ``Motor`` (a Gauss-Newton fit
whose normal matrix has a condition number of ~3e6: Excel itself is ~1e-9 away from the exact solution
there) - and they must still agree to 4 significant digits.
"""
import collections
import os

import pytest

import lo_reference as L
from tto.xl import numfmt
from tto.xl.engine import run_with_big_stack
from tto.xl.model import COLS, Model, a1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOLVER_SHEETS = {"Motor", "OIS_MAIN", "MASA", "DV01_RISK"}


def compare(model_file, golden_file, tol):
    def run():
        numfmt.set_engine_locale("en")              # the reference was produced with an English LibreOffice
        try:
            model = Model.load(os.path.join(ROOT, "models", model_file))
            gold = L.load_golden(os.path.join(ROOT, "tests", "data", golden_file))
            extra = {model.cell_ref(k): (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                     for k, v in gold["inputs"].items()}
            eng, pins = L.reference_engine(model, gold["today"], extra)
            calc = eng.shared
            total = collections.Counter()
            bad = []
            for s in model.sheets:
                for rc, lo in gold["sheets"][s.name].items():
                    rc = int(rc)
                    r, c = divmod(rc, COLS)
                    v = calc.get(s.index, r, c)
                    total[s.name] += 1
                    if not L.same(v, lo, tol):
                        bad.append((s.name, a1(rc), v, lo))
            return total, bad
        finally:
            numfmt.set_engine_locale("tr")
    return run_with_big_stack(run)


@pytest.fixture(scope="module")
def tto():
    return compare("tto.json.gz", "lo_tto.json.gz", 1e-7)


def test_usd_workbook_matches_libreoffice_everywhere():
    total, bad = compare("sofr.json.gz", "lo_sofr.json.gz", 1e-9)
    assert sum(total.values()) == 4277
    assert bad == []


def test_try_workbook_coverage(tto):
    total, _ = tto
    assert sum(total.values()) > 186000          # every formula cell of all 17 sheets
    assert len(total) == 17


def test_try_workbook_sheets_without_the_solver_match_exactly(tto):
    total, bad = tto
    outside = [b for b in bad if b[0] not in SOLVER_SHEETS]
    assert outside == []
    for sheet in ("Forward", "VIOP", "DİBS RV", "C & R", "Günlük İşlemler", "Calculators", "TM_OIS", "Manuel Tahvil",
                  "YP DIBS", "Bulk Bond", "Ivır Zıvır", "MOBIL MK", "USDTRY IYIX"):
        assert total[sheet] > 0


def test_try_workbook_solver_cells_agree_to_numerical_noise(tto):
    total, bad = tto
    assert len(bad) <= 320                                      # 0.17 % of 186 585 cells
    assert sum(total.values()) - len(bad) >= 0.998 * sum(total.values())
    for sheet, addr, v, lo in bad:
        assert isinstance(v, float) and isinstance(lo, float), (sheet, addr, v, lo)
        diff = abs(v - lo)
        assert diff <= 1e-6 or diff <= 1e-4 * max(abs(v), abs(lo)), (sheet, addr, v, lo)


def test_forward_sheet_is_identical_to_libreoffice(tto):
    total, bad = tto
    assert total["Forward"] == 1556
    assert [b for b in bad if b[0] == "Forward"] == []
