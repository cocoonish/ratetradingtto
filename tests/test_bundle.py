"""The dashboard as one plain-text file (``kurulum/tto_kur.py``): for machines that can take single files but
neither the repository as a ZIP nor an archive by mail.  ``tools/make_bundle.py`` builds it."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

import make_bundle
from tto.config import FORBIDDEN_PORTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "kurulum", "tto_kur.py")


def run(script, *args, cwd=None, bare=True):
    """Run a bundle script with an interpreter that has no installed packages; returns (exit code, output).

    Python writes to a pipe in the locale's encoding - UTF-8 on Linux, cp1254 on a Turkish Windows (a console
    gets Unicode either way) - so the script is asked for the UTF-8 its output is read in."""
    cmd = [sys.executable] + (["-S"] if bare else []) + [script] + list(args)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=300, stdin=subprocess.DEVNULL, env=env)
    return res.returncode, (res.stdout + res.stderr).decode("utf-8", "replace")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(text if isinstance(text, bytes) else text.encode("utf-8"))


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def tree(folder):
    out = {}
    for base, _, files in os.walk(folder):
        for f in files:
            full = os.path.join(base, f)
            out[os.path.relpath(full, folder).replace(os.sep, "/")] = read(full)
    return out


FILES_1 = {"run.bat": b"@echo off\r\npython -m tto %*\r\n", "run.sh": b"#!/bin/sh\nexec python3 -m tto\n",
           "tto/__init__.py": b"", "tto/views/10_masa.json": b'{"id": "masa"}', "tto/views/20_eski.json": b'{"id": "eski"}',
           "tto/static/js/main.js": "// Türkçe: çğıöşü\n".encode("utf-8"), "models/tto.json.gz": bytes(range(256)) * 40}


def test_what_goes_into_the_bundle():
    names = make_bundle.repo_files(ROOT)
    assert names == sorted(set(names))
    for needed in ("run.bat", "run.sh", "README.md", "requirements.txt", "tto/__main__.py", "tto/history.py", "tto/static/index.html",
                   "tto/static/js/main.js", "tto/static/js/pages/history.js", "tto/views/20_ois.json", "tto/data/replay_history.json",
                   "models/tto.json.gz", "models/sofr.json.gz", "models/borsa.json.gz", "models/asw.json.gz", "vendor/SHA256SUMS",
                   "tools/make_bundle.py", "tools/bundle_stub.py"):
        assert needed in names, needed
    assert sum(1 for n in names if n.startswith("vendor/") and n.endswith(".whl")) >= 27          # the three sets of web packages
    for n in names:
        assert n.split("/")[0] in ("tto", "models", "vendor", "tools") or "/" not in n, n
        assert "__pycache__" not in n and not n.endswith(".pyc") and not n.startswith(("vendor/local/", "data/", "kurulum/", "tests/")), n
    # everything the server reads at run time lives in those folders: every tracked file of tto/ is in
    tracked = subprocess.run(["git", "ls-files", "tto", "models", "vendor"], cwd=ROOT, capture_output=True, text=True)
    if tracked.returncode == 0 and tracked.stdout.strip():
        assert set(tracked.stdout.split()) <= set(names)


def test_the_version_is_a_digest_of_the_contents():
    a = make_bundle.content_version(FILES_1)
    assert len(a) == 10 and a == make_bundle.content_version(dict(reversed(list(FILES_1.items()))))
    changed = dict(FILES_1, **{"tto/__init__.py": b"# x"})
    renamed = {("tto/views/11_masa.json" if k == "tto/views/10_masa.json" else k): v for k, v in FILES_1.items()}
    assert len({a, make_bundle.content_version(changed), make_bundle.content_version(renamed)}) == 3
    one, two = make_bundle.bundle_script(FILES_1), make_bundle.bundle_script(FILES_1)
    assert one == two                                                    # no clock, no order: the same files give the same file
    assert make_bundle.bundle_contents(one) == {n: make_bundle.hashlib.sha256(b).hexdigest() for n, b in FILES_1.items()}
    assert make_bundle.differences(one, FILES_1) == []
    assert make_bundle.differences(one, changed) == ["değişmiş: tto/__init__.py"]
    assert make_bundle.differences(one, renamed) == ["eksik: tto/views/11_masa.json", "fazla: tto/views/10_masa.json"]


def test_the_script_is_plain_text_a_mail_service_takes():
    script = make_bundle.bundle_script(FILES_1, {"run.sh": True})
    compile(script, "tto_kur.py", "exec")                                # it is a Python program ...
    lines = script.split("\n")
    start = lines.index("# ---- ARSIV (base64 zip) ----")
    assert lines[-2] == "# ---- SON ----" and lines[-1] == ""
    body = lines[start + 1:-2]
    assert body and all(len(line) <= 77 and line.startswith("#") and line[1:].isascii() and " " not in line for line in body)
    assert "\x00" not in script and "\r" not in script and max(len(line) for line in lines) < 200
    assert "PK\x03\x04" not in script                                    # ... and nothing in it looks like an archive


def test_unpack_then_update_keeps_data_and_removes_what_is_gone(tmp_path):
    script = str(tmp_path / "tto_kur.py")
    write(script, make_bundle.bundle_script(FILES_1, {"run.sh": True}))
    code, out = run(script, "--no-run", cwd=str(tmp_path))
    target = tmp_path / "ratetradingtto"                                 # next to the script
    assert code == 0, out
    assert "%d dosya yazıldı." % len(FILES_1) in out and str(target) in out and "run.bat" in out and "kapatıp" not in out
    got = tree(str(target))
    manifest = json.loads(got.pop(".tto_kur.json").decode())
    assert got == FILES_1                                                # byte for byte, CRLF and UTF-8 included
    assert manifest["version"] == make_bundle.content_version(FILES_1) and set(manifest["files"]) == set(FILES_1)
    if os.name != "nt":
        assert os.access(str(target / "run.sh"), os.X_OK) and not os.access(str(target / "run.bat"), os.X_OK)

    # the same file again: nothing to do
    code, out = run(script, "--no-run", cwd=str(tmp_path))
    assert code == 0 and "0 dosya yazıldı, %d dosya zaten aynıydı." % len(FILES_1) in out

    # the dashboard has run meanwhile, and the desk added files of its own
    write(str(target / "data" / "tto.db"), b"users, scenarios, blotter")
    write(str(target / "vendor" / "local" / "blpapi" / "__init__.py"), b"# dropped in by hand")
    write(str(target / "tto" / "views" / "99_benim.json"), b'{"id": "benim"}')
    write(str(target / "tto" / "__pycache__" / "x.pyc"), b"\0")
    files_2 = dict(FILES_1)
    del files_2["tto/views/20_eski.json"]                                 # a page that is no longer there
    del files_2["tto/static/js/main.js"]                                  # the only file of its folder
    files_2["tto/views/10_masa.json"] = b'{"id": "masa", "v": 2}'
    files_2["tto/history.py"] = b"# new"
    write(script, make_bundle.bundle_script(files_2, {"run.sh": True}))
    code, out = run(script, str(target), "--no-run", cwd=str(tmp_path))   # the folder can be named
    assert code == 0, out
    assert "2 dosya yazıldı, %d dosya zaten aynıydı, 2 eski dosya silindi." % (len(files_2) - 2) in out
    assert "Önceki sürüm: %s" % make_bundle.content_version(FILES_1) in out and "data klasörüne" in out and "kapatıp yeniden başlatın" in out
    got = tree(str(target))
    assert got.pop("data/tto.db") == b"users, scenarios, blotter"
    assert got.pop("vendor/local/blpapi/__init__.py") == b"# dropped in by hand"
    assert got.pop("tto/views/99_benim.json") == b'{"id": "benim"}'       # not ours: left alone
    assert got.pop("tto/__pycache__/x.pyc") == b"\0"
    got.pop(".tto_kur.json")
    assert got == files_2
    assert not os.path.exists(str(target / "tto" / "static"))            # the folder that became empty is gone too
    assert not [n for n in os.listdir(str(target / "tto" / "views")) if n.endswith(".tto_yeni")]


def test_a_folder_that_came_from_a_zip_is_updated_without_deleting(tmp_path):
    target = tmp_path / "eski"
    write(str(target / "tto" / "views" / "10_masa.json"), b'{"id": "masa"}')          # the same as in the bundle
    write(str(target / "tto" / "views" / "05_cok_eski.json"), b"{}")                  # from who knows which version
    write(str(target / "data" / "tto.db"), b"x")
    script = str(tmp_path / "tto_kur.txt")                                             # the extension does not matter
    write(script, make_bundle.bundle_script(FILES_1))
    code, out = run(script, str(target), "--no-run")
    assert code == 0, out
    assert "%d dosya yazıldı, 1 dosya zaten aynıydı." % (len(FILES_1) - 1) in out and "başka bir yolla (ZIP) açılmış" in out
    assert read(str(target / "tto" / "views" / "05_cok_eski.json")) == b"{}" and read(str(target / "data" / "tto.db")) == b"x"
    # from now on the folder is known: a later bundle removes what an earlier bundle brought
    files_2 = {k: v for k, v in FILES_1.items() if k != "tto/views/20_eski.json"}
    write(script, make_bundle.bundle_script(files_2))
    code, out = run(script, str(target), "--no-run")
    assert code == 0 and "1 eski dosya silindi" in out and not os.path.exists(str(target / "tto" / "views" / "20_eski.json"))
    assert os.path.exists(str(target / "tto" / "views" / "05_cok_eski.json"))


def test_half_downloaded_and_damaged_files_are_refused(tmp_path):
    script = make_bundle.bundle_script(FILES_1)
    cut = str(tmp_path / "yarim.py")
    write(cut, script[:script.index("# ---- ARSIV") + 900])                 # the download stopped
    code, out = run(cut, "--no-run", cwd=str(tmp_path))
    assert code == 2 and "yarım inmiş" in out and "yeniden indirin" in out and "Traceback" not in out
    i = script.index("# ---- ARSIV (base64 zip) ----\n") + 200
    bad = str(tmp_path / "bozuk.py")
    write(bad, script[:i] + ("A" if script[i] != "A" else "B") + script[i + 1:])        # one character changed on the way
    code, out = run(bad, "--no-run", cwd=str(tmp_path))
    assert code == 2 and "özeti tutmuyor" in out and "Traceback" not in out
    crlf = str(tmp_path / "crlf.py")
    write(crlf, script.replace("\n", "\r\n"))                               # a transfer that rewrote the line ends
    code, out = run(crlf, str(tmp_path / "c"), "--no-run")
    assert code == 0 and tree(str(tmp_path / "c"))["run.bat"] == FILES_1["run.bat"]
    assert not os.path.exists(str(tmp_path / "ratetradingtto"))             # the refused files wrote nothing
    with pytest.raises(ValueError):
        make_bundle.bundle_contents(script[:i] + ("A" if script[i] != "A" else "B") + script[i + 1:])


def test_a_file_that_cannot_be_written_is_reported(tmp_path):
    script = str(tmp_path / "tto_kur.py")
    write(script, make_bundle.bundle_script(FILES_1))
    target = tmp_path / "hedef"
    assert run(script, str(target), "--no-run")[0] == 0
    # something stands where a new file has to go (the stand-in for a file the running dashboard holds)
    os.makedirs(str(target / "tto" / "yeni.py"))
    files_2 = dict(FILES_1, **{"tto/yeni.py": b"# new", "tto/views/10_masa.json": b"{}"})
    del files_2["tto/views/20_eski.json"]
    write(script, make_bundle.bundle_script(files_2))
    code, out = run(script, str(target), "--no-run")
    assert code == 2 and "1 dosya yazılamadı" in out and "tto/yeni.py" in out and "kapatıp yeniden deneyin" in out
    assert not [n for n in os.listdir(str(target / "tto")) if n.endswith(".tto_yeni")]               # no half copy left behind
    # nothing was removed and the folder still counts as the earlier version: the next run finishes the job
    assert os.path.exists(str(target / "tto" / "views" / "20_eski.json"))
    assert json.loads(read(str(target / ".tto_kur.json")).decode())["version"] == make_bundle.content_version(FILES_1)
    os.rmdir(str(target / "tto" / "yeni.py"))
    code, out = run(script, str(target), "--no-run")
    assert code == 0 and "1 dosya yazıldı" in out and "1 eski dosya silindi" in out
    got = tree(str(target))
    got.pop(".tto_kur.json")
    assert got == files_2


def test_names_that_would_leave_the_folder_are_refused(tmp_path):
    # a backslash is refused as such where it is no separator; on Windows zipfile turns it into "/" (so the ".." counts)
    for name in ("../disari.txt", "/kok.txt", "data/tto.db", "vendor/local/x.py", "..\\disari.txt"):
        script = str(tmp_path / "kotu.py")
        write(script, make_bundle.bundle_script({"tto/__init__.py": b"", name: b"x"}))
        code, out = run(script, str(tmp_path / "hedef"), "--no-run")
        assert code == 2 and "beklenmeyen bir ad" in out, (name, out)
        assert not os.path.exists(str(tmp_path / "disari.txt")) and not os.path.exists(str(tmp_path / "hedef" / "data"))


def test_options_and_messages(tmp_path):
    script = str(tmp_path / "tto_kur.py")
    write(script, make_bundle.bundle_script(FILES_1))
    code, out = run(script, "--list", cwd=str(tmp_path))
    assert code == 0 and "run.bat" in out and "tto/views/10_masa.json" in out and not os.path.exists(str(tmp_path / "ratetradingtto"))
    code, out = run(script, "--help", cwd=str(tmp_path))
    assert code == 0 and "tek dosyalık kurulum" in out and "--no-run" in out and "D:\\tto" in out
    code, out = run(script, "--sil", cwd=str(tmp_path))
    assert code == 2 and "Anlaşılmayan seçenek: --sil" in out
    code, out = run(script, "a", "b", "--no-run", cwd=str(tmp_path))
    assert code == 2
    write(str(tmp_path / "dosya"), b"x")
    code, out = run(script, str(tmp_path / "dosya"), "--no-run")
    assert code == 2 and "bir klasör değil" in out
    # without a console nobody is asked anything: the script unpacks and ends
    code, out = run(script, str(tmp_path / "sessiz"))
    assert code == 0 and "başlatılsın mı" not in out and os.path.isdir(str(tmp_path / "sessiz" / "tto"))
    # an interpreter that is too old says so (the check runs before anything is unpacked)
    old = str(tmp_path / "eski.py")
    write(old, read(script).decode("utf-8").replace("MIN_PYTHON = (3, 8)", "MIN_PYTHON = (9, 9)"))
    code, out = run(old, str(tmp_path / "olmaz"), "--no-run")
    assert code == 2 and "çok eski" in out and not os.path.exists(str(tmp_path / "olmaz"))


def _free_port():
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("no free port")


def test_the_file_in_the_repository_is_current_and_gives_a_running_dashboard(tmp_path):
    if not os.path.exists(BUNDLE):
        pytest.skip("kurulum/tto_kur.py is not part of this copy (archives leave it out)")
    files, _ = make_bundle.read_tree(ROOT)
    script = read(BUNDLE).decode("utf-8")
    # the same file as .txt beside it (a network that refuses a .py download lets a .txt through)
    txt = os.path.join(os.path.dirname(BUNDLE), "tto_kur.txt")
    assert os.path.exists(txt) and read(txt) == read(BUNDLE), \
        "kurulum/tto_kur.txt, tto_kur.py ile aynı olmalı - yenileyin:  python tools/make_bundle.py"
    diff = make_bundle.differences(script, files)
    assert diff == [], "kurulum/tto_kur.py güncel değil - yenileyin:  python tools/make_bundle.py   (%s)" % "; ".join(diff[:6])
    assert 'VERSION = "%s"' % make_bundle.content_version(files) in script
    assert 3e6 < len(script) < 12e6                                       # a few MB: one download, well under a mail limit

    # one file, an interpreter without any installed package, an empty folder
    copy = str(tmp_path / "tto_kur.txt")
    write(copy, script)
    code, out = run(copy, "--no-run", cwd=str(tmp_path))
    assert code == 0, out
    target = str(tmp_path / "ratetradingtto")
    assert "%d dosya yazıldı." % len(files) in out
    got = tree(target)
    got.pop(".tto_kur.json")
    assert got == files
    # "--run" starts what was unpacked and hands on what follows "--"
    code, out = run(copy, "--run", "--", "--help", cwd=str(tmp_path))
    assert code == 0 and "TTO masa dashboard" in out and "--port" in out

    port = _free_port()
    server = subprocess.Popen([sys.executable, "-S", "-m", "tto", "--mode", "replay", "--host", "127.0.0.1", "--port", str(port),
                               "--no-history"], cwd=target, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = "http://127.0.0.1:%d" % port

    session = {}

    def get(path):
        with urllib.request.urlopen(urllib.request.Request(url + path, headers=session), timeout=60) as r:
            return r.status, r.read()

    try:
        for _ in range(240):
            try:
                get("/api/auth")                                        # answers without a session
                break
            except Exception:  # noqa: BLE001
                if server.poll() is not None:
                    pytest.fail("server did not start: %s" % server.stdout.read().decode("utf-8", "replace")[-2000:])
                time.sleep(0.5)
        else:
            pytest.fail("server did not answer")
        from helpers import first_admin
        session.update(first_admin(url))                               # the first administrator, then their session
        status = json.loads(get("/api/status")[1])
        assert status["mode"] == "replay" and set(status["books"]) == {"tto", "sofr", "borsa", "asw"}
        assert not any(b["left_out"] for b in status["books"].values())
        pages = [p["id"] for p in json.loads(get("/api/nav")[1])["pages"]]
        # (the quant package's pages - intraday, curve fair value, options, the implied path, the WIRP, lead-lag, VİOP, Trend, Carry + momentum, Opsiyon → spot and DİBS switch among them - the desk corner's two, Trades, DİBS RV · Genel and Bugün)
        assert len(pages) == 55 and {"masa", "bugun", "ois", "fiyatlama", "eod", "mpc", "settings", "blotter", "trades", "broker", "vol", "dibslive", "kagitlar", "watch", "dibs-genel",
                                     "heat", "spreads", "quant", "quant-fx", "quant-intraday", "quant-curve", "quant-opt", "quant-path", "quant-wirp", "quant-lead",
                                     "quant-viop", "quant-trend", "quant-sira", "quant-ml", "quant-optspot", "quant-dibssw", "social", "agenda"} <= set(pages)
        page = json.loads(get("/api/view/ois")[1])
        assert len(page["panels"]) > 20 and not any(p.get("error") for p in page["panels"])
        assert len(json.loads(get("/api/calendar")[1])["meetings"]) == 95
        for path in ("/", "/static/js/main.js", "/static/js/pages/history.js", "/static/css/app.css"):
            assert get(path)[0] == 200, path
        assert os.path.exists(os.path.join(target, "data", "tto.db"))     # its data live next to the program
    finally:
        server.terminate()
        try:
            out = server.communicate(timeout=20)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            server.kill()
            out = server.communicate()[0].decode("utf-8", "replace")
    assert "Traceback" not in out
    # the next version over a folder in use: the program is replaced, the data stay
    code, out = run(copy, "--no-run", cwd=str(tmp_path))
    assert code == 0 and "0 dosya yazıldı" in out and "data klasörüne" in out


def test_run_bat_is_plain_and_names_nobody_s_folder():
    """``run.bat`` as cmd reads it: ASCII (the console's code page), CRLF line ends, and no user's folder written in it -
    Anaconda's place is found from ``%USERPROFILE%`` and the usual folders (``TTO_CONDA`` for another)."""
    data = read(os.path.join(ROOT, "run.bat"))
    data.decode("ascii")
    assert b"\r\n" in data and data.count(b"\n") == data.count(b"\r\n") and b"\x07" not in data
    text = data.decode("ascii")
    assert "C:\\Users" not in text and "%USERPROFILE%\\Anaconda3" in text and "TTO_CONDA" in text
    assert text.index("activate.bat") < text.index("python -c")          # (Anaconda opened before Python is looked for)


@pytest.mark.skipif(os.name != "nt", reason="run.bat is the Windows starter")
def test_run_bat_opens_anaconda_first_as_anaconda_prompt_does(tmp_path):
    """The desk's machine has no command window and Python only through Anaconda Prompt (19.11.2026: "Normal cmd'ye
    erişim olmadığı için anaconda prompt ile runlıyorum, bat'ı da bunun gibi değiştirelim" - their other starters call
    Anaconda's ``Scripts\\activate.bat`` with its folder, then ``python``).  On a PATH with no Python: a fake Anaconda
    whose ``activate.bat`` puts one on it - named by ``TTO_CONDA``, or in ``%USERPROFILE%\\Anaconda3`` - and run.bat
    starts the dashboard with it ("python -m tto" and what it was given, from its own folder); none: it says so and
    stops."""
    pydir = os.path.dirname(sys.executable)
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")     # (cmd, never a Python - nor py)

    def fake_conda(root):
        write(os.path.join(root, "Scripts", "activate.bat"),
              '@echo off\r\necho ACT %%~1\r\nset "PATH=%s;%%PATH%%"\r\n' % pydir)

    def start(**env):
        base = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "TTO_CONDA", "USERPROFILE", "LOCALAPPDATA",
                                                                        "PROGRAMDATA", "PYTHONPATH", "CONDA_PREFIX")}
        base.update(PATH=system, USERPROFILE=str(tmp_path / "home"), LOCALAPPDATA=str(tmp_path / "local"),
                    ProgramData=str(tmp_path / "all"), PYTHONIOENCODING="utf-8")
        base.update(env)
        res = subprocess.run(["cmd", "/c", os.path.join(ROOT, "run.bat"), "--help"], cwd=str(tmp_path), env=base,
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        return res.returncode, (res.stdout + res.stderr).decode("utf-8", "replace")

    code, out = start()
    assert code == 1 and "Python bulunamadi" in out and "TTO_CONDA" in out
    fake_conda(str(tmp_path / "elsewhere"))
    code, out = start(TTO_CONDA=str(tmp_path / "elsewhere"))
    assert "Anaconda: %s" % (tmp_path / "elsewhere") in out and "ACT %s" % (tmp_path / "elsewhere") in out, out
    assert "TTO masa dashboard" in out and "--port" in out, out                          # (python -m tto --help, from the repo)
    fake_conda(str(tmp_path / "home" / "Anaconda3"))
    code, out = start()
    assert "ACT %s" % (tmp_path / "home" / "Anaconda3") in out and "TTO masa dashboard" in out, out
