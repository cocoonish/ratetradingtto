"""The web packages without an installation.

The server needs Starlette and uvicorn (and the few pure-Python packages those two need).  On a machine where
nothing may be installed they are imported straight from the unmodified wheels kept in ``vendor/``: a wheel
is a zip archive, and Python imports pure-Python packages from zip archives.  There is one set of wheels per
generation of Python (``vendor/py310`` for 3.10 and later, ``py39``, ``py38``).

Installed packages are preferred - the bundle is only used when Starlette or uvicorn cannot be imported, or
when ``TTO_BUNDLED=1`` asks for it.

``vendor/local`` (not part of the repository) is a drop-in folder for packages of your own that cannot be
installed either, such as an unpacked ``blpapi`` wheel: the folder and any wheel in it are importable.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import ROOT

VENDOR = os.path.join(ROOT, "vendor")
#: minimum Python version -> folder of the set written for it (first match wins)
SETS: Tuple[Tuple[Tuple[int, int], str], ...] = (((3, 10), "py310"), ((3, 9), "py39"), ((3, 8), "py38"))
NEEDED = ("starlette", "uvicorn")


class BundleError(RuntimeError):
    """The web packages are neither installed nor available from the bundle."""


def folder_for(version: Optional[Sequence[int]] = None) -> Optional[str]:
    """The bundle folder for a Python version (``None``: too old for any of them)."""
    v = tuple((version or sys.version_info)[:2])
    for minimum, name in SETS:
        if v >= minimum:
            return name
    return None


def missing() -> List[str]:
    """Which of the needed packages cannot be imported as things stand."""
    out = []
    for name in NEEDED:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            out.append(name)
    return out


def _wheels(folder: str) -> List[str]:
    return sorted(os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".whl")) if os.path.isdir(folder) else []


def add_local() -> bool:
    """Make what was dropped into ``vendor/local`` importable (unpacked packages and wheels)."""
    local = os.path.join(VENDOR, "local")
    if not os.path.isdir(local):
        return False
    for path in [local] + _wheels(local):                 # after everything else: an installed package wins
        if path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()
    return True


def enable(force: Optional[bool] = None) -> Dict[str, Any]:
    """Make the web packages importable; returns what was done.

    ``{"bundled": folder name or None, "local": True when vendor/local was added}``.  Raises
    :class:`BundleError` with what to do when the packages are not installed and no bundle fits.
    """
    info: Dict[str, Any] = {"bundled": None, "local": add_local()}
    if force is None:
        force = os.environ.get("TTO_BUNDLED", "").strip().lower() in ("1", "true", "yes", "evet")
    lacking = missing()
    if not force and not lacking:
        return info
    name = folder_for()
    wheels = _wheels(os.path.join(VENDOR, name)) if name else []
    if not wheels:
        if not lacking:
            return info                                   # asked for the bundle, but the installed packages will do
        version = "%d.%d" % tuple(sys.version_info[:2])
        if name is None:
            raise BundleError("Python %s çok eski: en az Python 3.8 gerekir." % version)
        raise BundleError("%s kurulu değil ve gömülü kopyası (vendor/%s) bulunamadı.  Kurmak için:  pip install -r requirements.txt"
                          % (" / ".join(lacking), name))
    # in front of the installed packages, all of them: the set is consistent in itself
    sys.path[0:0] = [w for w in wheels if w not in sys.path]
    importlib.invalidate_caches()
    info["bundled"] = name
    return info


__all__ = ["BundleError", "add_local", "enable", "folder_for", "missing", "VENDOR", "SETS"]
