"""Import an Excel workbook into a model file used by the dashboard.

    python tools/import_workbook.py workbooks/TTO_v8_5.xlsm models/tto.json.gz
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tto.xl.importer import import_workbook  # noqa: E402


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    t0 = time.time()
    model = import_workbook(argv[1])
    model.save(argv[2])
    print("%s -> %s : %d sheets, %d formulas, %d templates, %.1fs" % (
        argv[1], argv[2], len(model.sheets), model.meta["formulas"], model.meta["templates"], time.time() - t0))
    for p in model.meta["problems"]:
        print("  problem:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
