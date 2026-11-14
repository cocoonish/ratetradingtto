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
    from tto.store import Store
    store = Store(str(tmp_path / "data" / "tto.db"))
    for name, role in (("Ayşe Yılmaz", "admin"), ("Mehmet", "user"), ("Zeynep", "user")):
        store.create_account(name, hash_password(E2E_PASSWORD), role=role)
    store.close()
    env["TTO_E2E_PASSWORD"] = E2E_PASSWORD
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
        res = subprocess.run([node, os.path.join(ROOT, "tests", "e2e", "e2e.js"), url, str(shots)], env=env,
                             capture_output=True, text=True, timeout=900)
        print(res.stdout[-6000:])
        assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-2000:]
        assert " 0 failed" in res.stdout
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
