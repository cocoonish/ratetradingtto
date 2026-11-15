"""Build ``kurulum/tto_kur.py``: everything the dashboard needs to run, as ONE plain-text Python script.

Some machines cannot take the repository as a ZIP - a mail service refuses archives that hold ``.bat`` / ``.js``
files, a proxy refuses GitHub's "Download ZIP" - but can take single files.  The script written here carries
the program, the imported workbooks and the bundled web packages as a base64 zip archive in comment lines
below its code and unpacks them next to itself (``tools/bundle_stub.py`` is the code of that script).  It downloads
nothing and installs nothing.

    python tools/make_bundle.py              # writes kurulum/tto_kur.py and the same file as kurulum/tto_kur.txt
    python tools/make_bundle.py --check      # are the two files in the repository still what the tree holds?
    python tools/make_bundle.py --out x.py   # somewhere else

What goes in: ``tto/``, ``models/``, ``vendor/`` (not ``vendor/local``), ``tools/`` and the start scripts -
what is needed to run and to import a changed workbook.  The tests and the source workbooks stay out.
The build is reproducible: the same files give the same version (a digest of the contents).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import os
import re
import sys
import zipfile
from typing import Dict, List, Optional, Tuple

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
STUB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bundle_stub.py")
OUT = os.path.join(ROOT, "kurulum", "tto_kur.py")
#: the same file as .txt beside it: what a network that refuses a .py download (or a mail filter) lets through
OUT_TXT = os.path.join(ROOT, "kurulum", "tto_kur.txt")

#: what the bundle holds: these folders and these files of the repository root
FOLDERS = ("tto", "models", "vendor", "tools")
ROOT_FILES = ("README.md", "requirements.txt", "run.bat", "run.sh")
#: never bundled: caches, local additions, the things people's tools leave behind
SKIP_DIRS = ("__pycache__", ".pytest_cache", "node_modules", ".git")
SKIP_PREFIXES = ("vendor/local/",)
SKIP_SUFFIXES = (".pyc", ".pyo", "~", ".orig", ".rej", ".tto_yeni")
SKIP_NAMES = ("Thumbs.db",)


def repo_files(root: str = ROOT) -> List[str]:
    """The files that go into the bundle, as ``/``-separated paths relative to ``root`` (sorted)."""
    out: List[str] = []
    for name in ROOT_FILES:
        if os.path.isfile(os.path.join(root, name)):
            out.append(name)
    for folder in FOLDERS:
        top = os.path.join(root, folder)
        for base, dirs, files in os.walk(top):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for f in files:
                rel = os.path.relpath(os.path.join(base, f), root).replace(os.sep, "/")
                if f.startswith(".") or f.startswith("~$") or f in SKIP_NAMES or f.endswith(SKIP_SUFFIXES):
                    continue
                if rel.startswith(SKIP_PREFIXES):
                    continue
                out.append(rel)
    return sorted(set(out))


def read_tree(root: str = ROOT) -> Tuple[Dict[str, bytes], Dict[str, bool]]:
    """``({path: bytes}, {path: is executable})`` of the files of the bundle."""
    files: Dict[str, bytes] = {}
    execs: Dict[str, bool] = {}
    for rel in repo_files(root):
        full = os.path.join(root, *rel.split("/"))
        with open(full, "rb") as fh:
            files[rel] = fh.read()
        execs[rel] = rel.endswith(".sh") or bool(os.name != "nt" and os.stat(full).st_mode & 0o111)
    return files, execs


def content_version(files: Dict[str, bytes]) -> str:
    """Ten hex digits that change when any file, or the list of files, changes."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode("utf-8") + b"\0" + hashlib.sha256(files[name]).digest())
    return h.hexdigest()[:10]


def bundle_script(files: Dict[str, bytes], execs: Optional[Dict[str, bool]] = None) -> str:
    """The text of the self-unpacking script for these files."""
    execs = execs or {}
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))      # no clock in the archive
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = ((0o755 if execs.get(name) else 0o644) | 0o100000) << 16
            zf.writestr(info, files[name], zipfile.ZIP_DEFLATED, 9)
    data = raw.getvalue()
    text = base64.b64encode(data).decode("ascii")
    lines = "\n".join("#" + text[i:i + 76] for i in range(0, len(text), 76))     # comment lines below the code
    with open(STUB, encoding="utf-8") as fh:
        stub = fh.read()
    for mark in ("@VERSION@", "@SHA256@", "@COUNT@", "@PAYLOAD@"):
        if mark not in stub:
            raise RuntimeError("tools/bundle_stub.py has no %s" % mark)
    return (stub.replace("@VERSION@", content_version(files)).replace("@SHA256@", hashlib.sha256(data).hexdigest())
            .replace("@COUNT@", str(len(files))).replace("@PAYLOAD@", lines))


def bundle_contents(script: str) -> Dict[str, str]:
    """``{path: sha256}`` of the files a bundle script carries (raises ``ValueError`` when it is damaged)."""
    m = re.search(r"^# ---- ARSIV \(base64 zip\) ----\n(.*?)\n# ---- SON ----$", script, re.S | re.M)
    s = re.search(r'^SHA256 = "([0-9a-f]{64})"', script, re.M)
    if not m or not s:
        raise ValueError("not a bundle script")
    data = base64.b64decode("".join(line[1:] for line in m.group(1).split("\n")))
    if hashlib.sha256(data).hexdigest() != s.group(1):
        raise ValueError("the archive in the script does not match its digest")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n: hashlib.sha256(zf.read(n)).hexdigest() for n in zf.namelist()}


def differences(script: str, files: Dict[str, bytes]) -> List[str]:
    """What separates a bundle script from the files of the tree (empty: it is current)."""
    have = bundle_contents(script)
    want = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
    out = ["eksik: %s" % n for n in sorted(set(want) - set(have))]
    out += ["fazla: %s" % n for n in sorted(set(have) - set(want))]
    out += ["değişmiş: %s" % n for n in sorted(n for n in want if n in have and have[n] != want[n])]
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/make_bundle.py", description="tek dosyalık kurulum betiğini üret")
    ap.add_argument("--out", default=OUT, help="yazılacak dosya (varsayılan kurulum/tto_kur.py)")
    ap.add_argument("--check", action="store_true", help="yazma; repodaki dosya ağaçla aynı mı, onu söyle")
    args = ap.parse_args(argv)
    files, execs = read_tree(ROOT)
    twin = OUT_TXT if os.path.abspath(args.out) == os.path.abspath(OUT) else None      # (the repository's pair)
    if args.check:
        try:
            with open(args.out, encoding="utf-8") as fh:
                diff = differences(fh.read(), files)
        except (OSError, ValueError) as exc:
            print("%s okunamadı: %s" % (args.out, exc))
            return 1
        if not diff and twin is not None:
            try:
                with open(twin, "rb") as a, open(args.out, "rb") as b:
                    same = a.read() == b.read()
            except OSError:
                same = False
            if not same:
                diff = ["%s, %s ile aynı değil" % (os.path.relpath(twin, ROOT), os.path.relpath(args.out, ROOT))]
        if diff:
            print("%s güncel değil (%d fark):" % (os.path.relpath(args.out, ROOT), len(diff)))
            for line in diff[:20]:
                print("   " + line)
            print("Yenilemek için:  python tools/make_bundle.py")
            return 1
        print("%s güncel: sürüm %s, %d dosya" % (os.path.relpath(args.out, ROOT), content_version(files), len(files)))
        return 0
    script = bundle_script(files, execs)
    folder = os.path.dirname(os.path.abspath(args.out))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    for path in (args.out, twin):
        if path is not None:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(script)
    print("%s  ->  sürüm %s, %d dosya, %.1f MB" % (os.path.relpath(args.out, ROOT), content_version(files), len(files),
                                                    len(script.encode("utf-8")) / 1e6)
          + ("  (aynısı: %s)" % os.path.relpath(twin, ROOT) if twin else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
