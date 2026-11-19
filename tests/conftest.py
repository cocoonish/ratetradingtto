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

# No test writes a second backup copy, above all not to the desk's D:\tto-yedek: a copy of the install a test unpacks
# (no .git, its own data/) defaults to it (config.backup_copy_default), and started after 17:30 it takes the day's
# backup at once, replacing the desk's copy of that day.  Every process a test starts inherits this; the tests of that
# default delete it first (test_backup, test_store).
os.environ["TTO_BACKUP_COPY_DIR"] = ""

from tto.config import Settings  # noqa: E402
from tto.service import Service  # noqa: E402


#: request headers without a session, for a test client that signs in by default (cookies of the client aside)
ANON = {"Authorization": ""}


def auth(svc: Service, user: str, admin: bool = False) -> dict:
    """Request headers of a signed-in user: a session as the sign-in opens it, sent the way scripts send it
    (``Authorization: Bearer …``).  The user is made (active) when new; ``admin``: an administrator."""
    key = svc.login(str(user))["user"]
    if admin:
        svc.store.update_account(key, role="admin")
    return {"Authorization": "Bearer " + svc.open_session(key)}


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
