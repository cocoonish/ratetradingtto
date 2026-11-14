"""TRY government bonds: the catalog of the desk's Bloomberg list (``tto/data/try_bonds.json``), ISIN checks, and
finding the bond a chat line speaks of ("15/3/28", "mar28", "Jan30 tlref", "10/02/2027zc").

A Turkish government ISIN carries its maturity: ``TRT150328T24`` matures on 15.03.2028, ``TRB100227T13`` (a bill)
on 10.02.2027.  Bills and zero-coupon bonds are quoted in yield, the others in price.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(_HERE, "data", "try_bonds.json")
KINDS = {"bill": "Bono", "zero": "Kuponsuz", "fixed": "Sabit", "cpi": "TÜFE", "float": "TLREF"}
_TR_ISIN = re.compile(r"^TR[A-Z](\d\d)(\d\d)(\d\d)[A-Z0-9]\d\d$")
_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
_catalog: Optional[List[Dict[str, Any]]] = None


def isin_valid(code: Any) -> bool:
    """An ISIN: two letters, nine letters or digits, a check digit that agrees (Luhn over the letters as numbers)."""
    s = str(code or "").strip().upper()
    if not re.match(r"^[A-Z]{2}[A-Z0-9]{9}\d$", s):
        return False
    digits = "".join(str(int(ch, 36)) for ch in s)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def maturity_of(isin: Any) -> Optional[_dt.date]:
    """The maturity a Turkish government ISIN carries (``None`` for any other ISIN)."""
    m = _TR_ISIN.match(str(isin or "").strip().upper())
    if not m:
        return None
    try:
        return _dt.date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def catalog() -> List[Dict[str, Any]]:
    """Every bond of the list: ``{isin, kind, maturity (ISO), name, coupon}``, by maturity."""
    global _catalog
    if _catalog is None:
        try:
            with open(CATALOG_FILE, encoding="utf-8") as fh:
                rows = json.load(fh).get("bonds") or []
        except (OSError, ValueError):
            rows = []
        _catalog = sorted(rows, key=lambda b: (b.get("maturity") or "", b.get("isin") or ""))
    return _catalog


def by_isin(isin: str) -> Optional[Dict[str, Any]]:
    code = str(isin or "").strip().upper()
    return next((b for b in catalog() if b["isin"] == code), None)


def quoted_in_yield(bond: Dict[str, Any]) -> bool:
    """Bills and zero-coupon bonds trade on their yield; the rest on their price."""
    return bond.get("kind") in ("bill", "zero")


def short_label(bond: Dict[str, Any]) -> str:
    """How the desk names a bond: "15.03.28", "09.01.30 TLREF", "10.02.27 Bono", "08.05.30 TÜFE"."""
    d = _dt.date.fromisoformat(bond["maturity"])
    tail = {"float": " TLREF", "cpi": " TÜFE", "bill": " Bono", "zero": " Kuponsuz"}.get(bond.get("kind"), "")
    return d.strftime("%d.%m.%y") + tail


def month_label(bond: Dict[str, Any]) -> str:
    d = _dt.date.fromisoformat(bond["maturity"])
    return "%s%02d" % (_MONTHS[d.month - 1], d.year % 100)


def candidates(date: Optional[str] = None, month: Optional[str] = None, kind: Optional[str] = None,
               extra: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """The bonds a chat line can mean: maturing on ``date`` (ISO) or in ``month`` ("2028-03"), of ``kind``
    ("fixed", "float", "cpi", "zc" - a bill or a zero coupon -, or ``None``: a fixed coupon one first, then the
    rest).  ``extra``: bonds of the desk's own lists that are not in the catalog."""
    pool = list(catalog()) + [b for b in extra if b.get("isin") and not by_isin(b["isin"])]
    if date:
        hit = [b for b in pool if b.get("maturity") == date]
    elif month:
        hit = [b for b in pool if (b.get("maturity") or "").startswith(month)]
    else:
        return []
    if kind == "fixed":
        return [b for b in hit if b.get("kind") == "fixed"]
    if kind == "float":
        return [b for b in hit if b.get("kind") == "float"]
    if kind == "cpi":
        return [b for b in hit if b.get("kind") == "cpi"]
    if kind == "zc":
        return [b for b in hit if b.get("kind") in ("bill", "zero")] or hit
    plain = [b for b in hit if b.get("kind") in ("fixed", "zero", "bill")]
    return plain or hit
