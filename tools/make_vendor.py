"""Fetch the bundled copies of the web packages (``vendor/``).

The server needs Starlette and uvicorn and the few pure-Python packages those two depend on.  On a machine
where nothing may be installed, ``python -m tto`` imports them straight from the wheels kept in ``vendor/``
(see ``tto/bundled.py``).  This tool downloads exactly the pinned wheels from PyPI - unmodified, one set per
generation of Python - and writes their checksums to ``vendor/SHA256SUMS``.

    python tools/make_vendor.py            # needs pip and access to PyPI; nothing is installed
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
VENDOR = os.path.join(ROOT, "vendor")

#: folder -> (Python version the set is resolved for, pinned wheels)
SETS = {
    "py310": ("3.10", ["starlette==1.7.0", "uvicorn==0.54.0", "anyio==4.15.1", "h11==0.16.0", "click==8.5.0", "idna==3.20",
                       "typing_extensions==4.16.0", "exceptiongroup==1.3.1", "colorama==0.4.6"]),
    "py39": ("3.9", ["starlette==0.49.3", "uvicorn==0.39.0", "anyio==4.12.1", "h11==0.16.0", "click==8.1.8", "idna==3.20",
                     "typing_extensions==4.16.0", "exceptiongroup==1.3.1", "colorama==0.4.6"]),
    "py38": ("3.8", ["starlette==0.44.0", "uvicorn==0.33.0", "anyio==4.5.2", "h11==0.16.0", "click==8.1.8", "idna==3.15",
                     "sniffio==1.3.1", "typing_extensions==4.13.2", "exceptiongroup==1.3.1", "colorama==0.4.6"]),
}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    sums = []
    for folder, (version, pins) in SETS.items():
        target = os.path.join(VENDOR, folder)
        os.makedirs(target, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            # pure-Python wheels only (py3-none-any); the platform is given so that nothing is ever built here
            cmd = [sys.executable, "-m", "pip", "download", "--quiet", "--no-deps", "--only-binary=:all:", "--python-version", version,
                   "--platform", "win_amd64", "--implementation", "cp", "-d", tmp] + pins
            subprocess.run(cmd, check=True)
            got = sorted(os.listdir(tmp))
            if len(got) != len(pins) or not all(name.endswith("-none-any.whl") for name in got):
                raise SystemExit("%s: expected %d pure-Python wheels, got %s" % (folder, len(pins), got))
            for old in os.listdir(target):
                if old.endswith(".whl"):
                    os.remove(os.path.join(target, old))
            for name in got:
                with open(os.path.join(tmp, name), "rb") as src, open(os.path.join(target, name), "wb") as dst:
                    dst.write(src.read())
                sums.append("%s  %s/%s" % (sha256(os.path.join(target, name)), folder, name))
        print("%s (Python %s): %d wheels" % (folder, version, len(got)))
    with open(os.path.join(VENDOR, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(sums) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
