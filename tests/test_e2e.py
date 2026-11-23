"""Browser end-to-end test (Playwright / Chromium) against a real server process.

Skipped when Node.js or Playwright is not installed.  The scenario lives in ``tests/e2e/e2e.js``.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from tto.config import FORBIDDEN_PORTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E2E_PASSWORD = "e2e-sifre-1"
#: the days of the bonds' closes put in for Kâğıt Fiyatlama: long before the recorded month (03.11.2026), outside every
#: window the other checks read (the end-of-day matrix's 22 week days, "DİBS geçmişi yok")
SEED_DAYS = ("2026-08-26", "2026-08-27", "2026-08-28")


def _seed_bond_closes(store) -> int:
    """Three days of closes for the trading list's fixed coupon bonds and bills - the recorded file has no bond history,
    and Kâğıt Fiyatlama's fair needs a bond's spread at a past close: the replay sheet's own BIST compound yield
    (DİBS RV!T, as saved) a few bp apart day to day, under the series the history keeps for the bond (DİBS RV!BT's
    security, ``YLD_YTM_MID``).  How many series were put in."""
    from tto.xl.model import Model, parse_a1
    sheet = Model.load(os.path.join(ROOT, "models", "tto.json.gz")).sheet("DİBS RV")

    def get(ref):
        rc = parse_a1(ref)
        return sheet.consts.get(rc, sheet.cached.get(rc))

    n = 0
    for r in range(5, 55):
        kind, sec, y = get("D%d" % r), get("BT%d" % r), get("T%d" % r)
        if kind not in ("S", "B") or not isinstance(sec, str) or not sec.strip() or type(y) is not float:
            continue
        store.hist_upsert("%s|YLD_YTM_MID" % sec.strip(), [(d, round(y * 100.0 + 0.02 * (k - 1), 6)) for k, d in enumerate(SEED_DAYS)])
        n += 1
    return n


def _seed_past_trade(store, user: str) -> str:
    """A TRY OIS of a day gone by for Günlük İşlemler's "Benzerini gir" / "Ters işlem" (PAY 1Y, 150 mn, its record as the
    form keeps one): 45 days back - out of "Son 30 gün", which the other checks count.  Its day."""
    import datetime
    day = (datetime.date.today() - datetime.timedelta(days=45)).isoformat()
    store.add_trade(day, "ois", {"dir": "B", "tenor": "1Y", "rate": 0.38, "dv01": 3500.0, "nominal": 150e6, "cpt": "E2E ESKİ",
                                 "role": "outright", "strategy": "outright", "label": "PAY 1Y @ 38,0000%", "level": 0.38, "side": "PAY",
                                 "cost_bp": 0.0, "cost_usd": 0.0, "market": 0.38, "note": "e2e geçmiş", "size_mode": "nominal",
                                 "size_typed": 150e6}, user)
    return day


def _free_port():
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("no free port")


def _node_env():
    node = shutil.which("node")
    if node is None:
        return None, None
    env = dict(os.environ)
    npm = shutil.which("npm")                           # npm.cmd on Windows: a bare "npm" is not found there
    try:
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=30).stdout.strip() if npm else ""
        if root:
            env["NODE_PATH"] = root + os.pathsep + env.get("NODE_PATH", "")
    except Exception:  # noqa: BLE001
        pass
    probe = subprocess.run([node, "-e", "require('playwright')"], env=env, capture_output=True, timeout=60)
    return (node, env) if probe.returncode == 0 else (None, None)


def test_dashboard_in_a_real_browser(tmp_path):
    node, env = _node_env()
    if node is None:
        pytest.skip("Node.js + Playwright are needed for the browser test")
    port = _free_port()
    shots = tmp_path / "shots"
    shots.mkdir()
    # the scenario's accounts (the dashboard opens with a name and a password; Ayşe Yılmaz is the administrator)
    from tto.auth import hash_password
    from tto.store import Store, user_key
    store = Store(str(tmp_path / "data" / "tto.db"))
    for name, role in (("Ayşe Yılmaz", "admin"), ("Mehmet", "user"), ("Zeynep", "user")):
        store.create_account(name, hash_password(E2E_PASSWORD), role=role)
    seeded = _seed_bond_closes(store)
    env["TTO_E2E_PAST_DAY"] = _seed_past_trade(store, user_key("Ayşe Yılmaz"))
    store.close()
    env["TTO_E2E_PASSWORD"] = E2E_PASSWORD
    env["TTO_E2E_SEEDED"] = str(seeded)                 # (the history's count of series grows by these)
    server = subprocess.Popen([sys.executable, "-m", "tto", "--mode", "replay", "--host", "127.0.0.1", "--port", str(port),
                               "--data-dir", str(tmp_path / "data")], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        url = "http://127.0.0.1:%d" % port
        for _ in range(120):
            try:
                urllib.request.urlopen(url + "/api/auth", timeout=1).read()                 # answers without a session
                break
            except Exception:  # noqa: BLE001
                if server.poll() is not None:
                    pytest.fail("server did not start: %s" % server.stdout.read().decode("utf-8", "replace")[-2000:])
                time.sleep(0.5)
        else:
            pytest.fail("server did not answer")
        # (node writes UTF-8: read as the locale's code page - cp1254 on the desk machine - an "Ş" in its output stopped the test)
        res = subprocess.run([node, os.path.join(ROOT, "tests", "e2e", "e2e.js"), url, str(shots)], env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        print(res.stdout[-6000:])
        # the checks that failed first, wherever they are in the long output (only its end is shown otherwise)
        failed = [line.strip() for line in res.stdout.splitlines() if line.lstrip().startswith("FAIL")]
        assert res.returncode == 0, "\n".join(failed[:20]) + "\n...\n" + res.stdout[-3000:] + res.stderr[-2000:]
        assert " 0 failed" in res.stdout
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
