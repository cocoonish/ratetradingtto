"""Running without installing anything: the web packages come from the wheels kept in ``vendor/``."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import pytest

from tto import bundled
from tto.config import FORBIDDEN_PORTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEEDED = {"starlette", "uvicorn", "anyio", "h11", "click", "idna", "colorama", "exceptiongroup", "typing_extensions"}


def wheels(folder):
    return sorted(n for n in os.listdir(os.path.join(bundled.VENDOR, folder)) if n.endswith(".whl"))


def free_port():
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("no free port")


def test_every_generation_of_python_has_its_set():
    assert bundled.folder_for((3, 14)) == bundled.folder_for((3, 13, 1)) == bundled.folder_for((3, 10)) == "py310"
    assert bundled.folder_for((3, 9)) == "py39" and bundled.folder_for((3, 8)) == "py38"
    assert bundled.folder_for((3, 7)) is None                                    # too old for the dashboard itself
    assert bundled.folder_for() == bundled.folder_for(sys.version_info)
    for _, folder in bundled.SETS:
        names = wheels(folder)
        # pure Python only: nothing to compile, the same files on every platform
        assert names and all(n.endswith("-none-any.whl") for n in names), folder
        assert NEEDED <= {n.split("-")[0].lower() for n in names}, folder


def test_the_wheels_are_the_listed_ones_and_carry_their_licence():
    listed = {}
    with open(os.path.join(bundled.VENDOR, "SHA256SUMS"), encoding="utf-8") as fh:
        for line in fh:
            digest, path = line.split()
            listed[path] = digest
    assert set(listed) == {"%s/%s" % (folder, n) for _, folder in bundled.SETS for n in wheels(folder)}
    for path, digest in listed.items():
        full = os.path.join(bundled.VENDOR, *path.split("/"))
        with open(full, "rb") as fh:
            assert hashlib.sha256(fh.read()).hexdigest() == digest, path
        with zipfile.ZipFile(full) as zf:
            names = [n.lower() for n in zf.namelist()]
            assert zf.testzip() is None
            assert any("licen" in n or "copying" in n for n in names), path           # redistributed with its licence text
            assert not any(n.endswith((".pyd", ".so", ".dll", ".exe")) for n in names), path


def test_installed_packages_are_preferred(monkeypatch):
    monkeypatch.delenv("TTO_BUNDLED", raising=False)
    assert bundled.missing() == []                               # the test environment has Starlette and uvicorn
    before = list(sys.path)
    info = bundled.enable()
    assert info == {"bundled": None, "local": os.path.isdir(os.path.join(bundled.VENDOR, "local"))}
    assert [p for p in sys.path if p.endswith(".whl")] == [p for p in before if p.endswith(".whl")]


def run(code, *flags, **env):
    full = dict(os.environ)
    full.update(env)
    res = subprocess.run([sys.executable] + list(flags) + ["-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120, env=full)
    assert res.returncode == 0, res.stderr[-1500:]
    return res.stdout.strip()


def test_without_installed_packages_the_bundle_is_imported_from_the_wheels():
    """``python -S`` has no site-packages at all - the situation of a machine where nothing may be installed."""
    code = ("import json, sys; from tto import bundled; lacking = bundled.missing(); info = bundled.enable(); "
            "import starlette, uvicorn, anyio, h11, click, idna; "
            "print(json.dumps([lacking, info, starlette.__file__, uvicorn.__file__, sys.path[0]]))")
    lacking, info, starlette_file, uvicorn_file, first = json.loads(run(code, "-S"))
    folder = bundled.folder_for()
    assert lacking == ["starlette", "uvicorn"] and info["bundled"] == folder
    assert os.path.join("vendor", folder) in starlette_file and ".whl" in starlette_file and ".whl" in uvicorn_file
    assert first.endswith(".whl")                                # in front of everything else: one consistent set


def test_the_bundle_can_be_asked_for_although_packages_are_installed():
    code = ("import json; from tto import bundled; info = bundled.enable(); import starlette; "
            "print(json.dumps([info['bundled'], starlette.__file__]))")
    used, where = json.loads(run(code, TTO_BUNDLED="1"))
    assert used == bundled.folder_for() and os.path.join("vendor", used) in where
    used, where = json.loads(run(code, TTO_BUNDLED=""))
    assert used is None and "vendor" not in where


def test_packages_dropped_into_vendor_local_are_importable(tmp_path, monkeypatch):
    """A package that cannot be installed either (blpapi) can be unpacked into vendor/local."""
    local = tmp_path / "local"
    (local / "birpaket").mkdir(parents=True)
    (local / "birpaket" / "__init__.py").write_text("DEGER = 42\n", encoding="utf-8")
    with zipfile.ZipFile(str(local / "ikincipaket-1.0-py3-none-any.whl"), "w") as zf:
        zf.writestr("ikincipaket.py", "DEGER = 7\n")
    monkeypatch.setattr(bundled, "VENDOR", str(tmp_path))
    before = list(sys.path)
    try:
        assert bundled.add_local() is True
        import birpaket
        import ikincipaket
        assert birpaket.DEGER == 42 and ikincipaket.DEGER == 7
        assert sys.path[:len(before)] == before                  # appended: installed packages still come first
    finally:
        sys.path[:] = before
        sys.modules.pop("birpaket", None)
        sys.modules.pop("ikincipaket", None)
    monkeypatch.setattr(bundled, "VENDOR", str(tmp_path / "yok"))
    assert bundled.add_local() is False


def test_a_missing_bundle_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr(bundled, "VENDOR", str(tmp_path))        # no wheels here
    monkeypatch.setattr(bundled, "missing", lambda: ["uvicorn"])
    with pytest.raises(bundled.BundleError) as exc:
        bundled.enable()
    assert "uvicorn kurulu değil" in str(exc.value) and "pip install -r requirements.txt" in str(exc.value)
    monkeypatch.setattr(bundled, "folder_for", lambda version=None: None)
    with pytest.raises(bundled.BundleError) as exc:
        bundled.enable()
    assert "en az Python 3.8" in str(exc.value)


def test_a_python_without_any_installed_package_serves_the_dashboard(tmp_path):
    """The whole server on ``python -S``: download the repository, run it - nothing to install."""
    port = free_port()
    server = subprocess.Popen([sys.executable, "-S", "-m", "tto", "--mode", "replay", "--host", "127.0.0.1", "--port", str(port),
                               "--data-dir", str(tmp_path / "data")], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = "http://127.0.0.1:%d" % port

    def get(path):
        with urllib.request.urlopen(url + path, timeout=30) as r:
            return r.status, r.headers.get("content-type", ""), r.read()

    try:
        for _ in range(240):
            try:
                status = json.loads(get("/api/status")[2])
                break
            except Exception:  # noqa: BLE001
                if server.poll() is not None:
                    pytest.fail("server did not start: %s" % server.stdout.read().decode("utf-8", "replace")[-2000:])
                time.sleep(0.5)
        else:
            pytest.fail("server did not answer")
        assert status["mode"] == "replay" and set(status["books"]) == {"tto", "sofr", "borsa", "asw"}
        page = json.loads(get("/api/view/forward")[2])
        assert len(page["panels"]) > 30 and not any(p.get("error") for p in page["panels"])
        code, kind, body = get("/static/js/main.js")
        assert code == 200 and "javascript" in kind and len(body) > 5000
        assert get("/")[0] == 200
        req = urllib.request.Request(url + "/api/login", data=json.dumps({"name": "Kurulumsuz"}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            assert json.loads(r.read())["user"] == "kurulumsuz"
        with urllib.request.urlopen(url + "/api/events", timeout=30) as r:           # the live-update stream opens
            assert r.status == 200 and r.headers.get("content-type", "").startswith("text/event-stream")
    finally:
        server.terminate()
        try:
            out = server.communicate(timeout=15)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            server.kill()
            out = server.communicate()[0].decode("utf-8", "replace")
    assert "vendor/%s" % bundled.folder_for() in out                                 # the start line says which copies are used
    assert "Traceback" not in out
