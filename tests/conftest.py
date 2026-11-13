"""pytest fixtures.  Everything runs in replay mode (the market data saved in the workbook): no Bloomberg,
no network.  ``tests/fake_blpapi.py`` stands in for the Bloomberg API where the live path is tested."""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tto.config import Settings  # noqa: E402
from tto.service import Service  # noqa: E402


def make_service(data_dir) -> Service:
    # history=False: the daily history is not filled in the background (tests that need it run it themselves)
    return Service(Settings(data_dir=str(data_dir), mode="replay", history=False))


@pytest.fixture(scope="session")
def service(tmp_path_factory):
    """One replay service shared by the read-mostly tests (use your own user names)."""
    svc = make_service(tmp_path_factory.mktemp("data"))
    yield svc
    svc.stop()


@pytest.fixture(scope="module")
def module_service(tmp_path_factory):
    """A private service for a test module that changes shared state (RET curve, blotter)."""
    svc = make_service(tmp_path_factory.mktemp("data"))
    yield svc
    svc.stop()


@pytest.fixture()
def tr_locale():
    """Tests that format text must not be affected by (or affect) the engine locale."""
    from tto.xl import numfmt
    numfmt.set_engine_locale("tr")
    yield
    numfmt.set_engine_locale("tr")


def cell(svc: Service, ref: str, user=None, book: str = "tto"):
    """Raw value of a cell as the given user sees it."""
    from tto.xl.model import COLS
    b = svc.books[book]

    def run():
        calc = svc._calc(user, b)
        si, rc = b.cell(ref)
        r, c = divmod(rc, COLS)
        return calc.get(si, r, c)

    return svc.et.call(run)
