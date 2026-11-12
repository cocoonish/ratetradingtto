"""The engine reproduces the workbooks.

1. *Excel's own values.*  Every formula is evaluated on the values Excel saved for its precedents and
   compared with the value Excel saved for the formula itself.  TTO_v8_5.xlsm was edited after its last
   full calculation, so part of what it stores is stale (formulas that Excel never ran, such as
   ``Forward!H126``, next to older saved results that depend on them, such as ``Forward!J18``); those
   cells cannot match *any* correct calculator, which is why the thresholds below are the measured
   consistency of the file and not 100 %.
2. *An independent calculator.*  ``tests/test_reference.py`` compares a full recalculation with LibreOffice.
"""
import argparse
import os

import pytest

import parity
from tto.xl.engine import Clock, Engine, cached_pins, run_with_big_stack
from tto.xl.model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: sheet -> minimum share of formulas that reproduce Excel's saved value (measured; see module docstring)
THRESHOLDS = {
    "MOBIL MK": 1.0, "YP DIBS": 1.0, "TM_OIS": 1.0, "Bulk Bond": 1.0, "Ivır Zıvır": 1.0,
    "Günlük İşlemler": 0.999, "DV01_RISK": 0.999, "C & R": 0.999, "DİBS RV": 0.999, "Manuel Tahvil": 0.999,
    "Calculators": 0.993, "OIS_MAIN": 0.991, "Forward": 0.986, "Motor": 0.933, "VIOP": 0.910, "USDTRY IYIX": 0.90,
}


@pytest.fixture(scope="module")
def result():
    def run():
        model = Model.load(os.path.join(ROOT, "models", "tto.json.gz"))
        today = parity.find_today(model)
        eng = Engine(model, clock=Clock(today))
        pins = cached_pins(model)
        eng.set_pins(pins)
        total, ok, by_sheet, bad = parity.local_parity(model, eng, pins, argparse.Namespace(sheet=None, tol=1e-9))
        return {"model": model, "today": today, "total": total, "ok": ok, "by_sheet": by_sheet, "bad": bad,
                "unknown": sorted(eng.compiler.unknown_functions), "compile_errors": list(eng.compiler.errors)}
    return run_with_big_stack(run)


def test_every_function_of_the_workbook_is_implemented(result):
    assert result["unknown"] == []
    assert result["compile_errors"] == []


def test_workbook_was_last_calculated_on_3_november_2026(result):
    assert result["today"] == 46329.0


def test_overall_agreement_with_excels_saved_values(result):
    assert result["total"] > 160000
    assert result["ok"] / result["total"] >= 0.954


@pytest.mark.parametrize("sheet", sorted(THRESHOLDS))
def test_sheet_agreement(result, sheet):
    n, good = result["by_sheet"][sheet]
    assert n > 0
    assert good / n >= THRESHOLDS[sheet], "%s: %d / %d" % (sheet, good, n)


def test_no_formula_fails_to_evaluate(result):
    crashes = [b for b in result["bad"] if isinstance(b[2], str) and b[2].startswith("EXC:")]
    assert crashes == []


def test_forward_differences_are_stale_values_in_the_file(result):
    """The handful of Forward cells that differ hold results saved *before* formulas they depend on were
    added: e.g. ``J18 = +H126*100`` has a saved value although ``H126`` was never calculated by Excel."""
    from tto.xl.model import a1, parse_a1
    model = result["model"]
    sh = model.sheet("Forward")
    bad = {a1(rc): (got, excel) for name, rc, got, excel in result["bad"] if name == "Forward"}
    assert len(bad) <= 13
    assert parse_a1("H126") in sh.fml and parse_a1("H126") not in sh.cached      # a formula Excel never ran
    assert "J18" in bad
    # none of the outright / swap point tables is among them
    assert not any(k in bad for k in ("D30", "E30", "F30", "D31", "E31", "F31", "D32", "E32", "F32", "D33", "E33", "F33",
                                      "D36", "D37", "D38", "D39", "E39", "F39"))
