"""TRY government bonds: the catalog of the desk's Bloomberg list (``tto/data/try_bonds.json``) and the bonds the desk
adds to it or takes off it on Tüm Kâğıtlar, ISIN checks, a bond's kind from what Bloomberg says of it, and finding
the bond a chat line speaks of ("15/3/28", "mar28", "Jan30 tlref", "10/02/2027zc").

A Turkish government ISIN carries its maturity: ``TRT150328T24`` matures on 15.03.2028, ``TRB100227T13`` (a bill)
on 10.02.2027.  Bills and zero-coupon bonds are quoted in yield, the others in price.

The floaters are of two kinds: a TLREF floater ("float": its coupon is TLREF compounded over the coupon period -
Bloomberg's floater formula says "91 D TLREF FLAT" or "182 D TLREF FLAT") and an FRN (any other index: the formula
is empty and the reset index is not TLREF's).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG_FILE = os.path.join(_HERE, "data", "try_bonds.json")
KINDS = {"bill": "Bono", "zero": "Kuponsuz", "fixed": "Sabit", "cpi": "TÜFE", "float": "TLREF", "frn": "FRN"}
#: the floaters: priced, not quoted in yield; a TLREF one and an FRN
FLOATERS = ("float", "frn")
#: what Bloomberg is asked of a bond added by ISIN: its kind, maturity, coupon and name
FACTS = ("NAME", "SECURITY_DES", "CRNCY", "CPN_TYP", "CPN", "MATURITY", "INFLATION_LINKED_INDICATOR", "FLOATER_FORMULA",
         "RESET_IDX")
_TR_ISIN = re.compile(r"^TR[A-Z](\d\d)(\d\d)(\d\d)[A-Z0-9]\d\d$")
_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
_shipped: Optional[List[Dict[str, Any]]] = None
#: the desk's changes to the list (the service's, kept in its store): bonds added ``{isin: bond + who / when}`` - a bond
#: whose kind Bloomberg has not told yet has ``kind`` None - and bonds taken off ``{isin: {"by", "at"}}``
_desk: Dict[str, Dict[str, Dict[str, Any]]] = {"added": {}, "removed": {}}
_desk_owner: Any = None
_known: Optional[List[Dict[str, Any]]] = None


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


# ---------------------------------------------------------------------------------------------- the list
def shipped() -> List[Dict[str, Any]]:
    """The bonds of the catalog file: ``{isin, kind, maturity (ISO), name, coupon}``, by maturity."""
    global _shipped
    if _shipped is None:
        try:
            with open(CATALOG_FILE, encoding="utf-8") as fh:
                rows = json.load(fh).get("bonds") or []
        except (OSError, ValueError):
            rows = []
        _shipped = sorted(rows, key=lambda b: (b.get("maturity") or "", b.get("isin") or ""))
    return _shipped


def set_desk(desk: Optional[Dict[str, Any]], owner: Any = None) -> None:
    """The desk's changes to the list (``{"added": {...}, "removed": {...}}``), as the service keeps them."""
    global _desk, _known, _desk_owner
    desk = desk or {}
    _desk = {"added": dict(desk.get("added") or {}), "removed": dict(desk.get("removed") or {})}
    _desk_owner = owner
    _known = None


def drop_desk(owner: Any) -> None:
    """The service that set the desk's changes stops: none are left behind (for another one in the same process)."""
    if owner is not None and owner is _desk_owner:
        set_desk(None)


def desk() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {"added": dict(_desk["added"]), "removed": dict(_desk["removed"])}


def catalog() -> List[Dict[str, Any]]:
    """Every bond the dashboard knows: the catalog file's and the ones the desk added, by maturity - what a chat line
    is read against and a bond's card is made of (a bond taken off Tüm Kâğıtlar or past its maturity included)."""
    global _known
    if _known is None:
        rows = {b["isin"]: b for b in shipped()}
        for isin, b in _desk["added"].items():
            rows.setdefault(isin, b)                       # a bond the file has since got: the file's
        _known = sorted(rows.values(), key=lambda b: (b.get("maturity") or "9999", b["isin"]))
    return _known


def listed(today: Optional[_dt.date] = None) -> List[Dict[str, Any]]:
    """The bonds of Tüm Kâğıtlar: every bond known but the ones the desk took off, until their maturity day."""
    day = (today or _dt.date.today()).isoformat()
    gone = _desk["removed"]
    return [b for b in catalog() if b["isin"] not in gone and not (b.get("maturity") and b["maturity"] < day)]


def by_isin(isin: str) -> Optional[Dict[str, Any]]:
    code = str(isin or "").strip().upper()
    return next((b for b in catalog() if b["isin"] == code), None)


def pending() -> List[str]:
    """The bonds added whose kind Bloomberg has not told yet."""
    return [isin for isin, b in _desk["added"].items() if not b.get("kind") and isin not in _desk["removed"]]


def _said(v: Any) -> str:
    """What Bloomberg answered as text ("" for no answer: an error, "#N/A ...", nothing)."""
    if isinstance(v, str):
        s = v.strip()
        return "" if s.startswith("#") else s
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    return ""


def _date_said(v: Any) -> Optional[_dt.date]:
    s = _said(v)
    for pat, order in ((r"^(\d{4})-(\d{1,2})-(\d{1,2})", "ymd"), (r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", "dmy"),
                       (r"^(\d{1,2})/(\d{1,2})/(\d{4})$", "mdy")):
        m = re.match(pat, s)
        if m:
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = {"ymd": (a, b, c), "dmy": (c, b, a), "mdy": (c, a, b)}[order]
            try:
                return _dt.date(y, mo, d)
            except ValueError:
                return None
    return None


def classify(isin: str, facts: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """A bond's record from what Bloomberg says of it (``FACTS``): ``(bond, "")``, or ``(None, why)`` - "fx:USD" (not a
    TL bond), "unknown" (Bloomberg does not know the ISIN), "kind" (a coupon type that is none of the desk's kinds) or
    "pending" (Bloomberg has not answered)."""
    code = str(isin or "").strip().upper()
    typ = _said(facts.get("CPN_TYP")).upper()
    if not typ:
        bad = facts.get("CPN_TYP")
        return None, ("unknown" if isinstance(bad, str) and "INVALID SECURITY" in bad.upper() else "pending")
    ccy = _said(facts.get("CRNCY")).upper()
    if not ccy:
        return None, "pending"
    if ccy != "TRY":
        return None, "fx:" + ccy
    if _said(facts.get("INFLATION_LINKED_INDICATOR")).upper().startswith("Y"):
        kind = "cpi"
    elif any(w in typ for w in ("FLOAT", "VARIABLE", "FRN")):
        said = (_said(facts.get("FLOATER_FORMULA")) + " " + _said(facts.get("RESET_IDX"))).upper()
        kind = "float" if ("TLREF" in said or "BISTREF" in said) else "frn"
    elif "ZERO" in typ or "DISC" in typ:
        kind = "bill" if code.startswith("TRB") or "BILL" in _said(facts.get("NAME")).upper() else "zero"
    elif "FIX" in typ:
        kind = "fixed"
    else:
        return None, "kind"
    mat = _date_said(facts.get("MATURITY")) or maturity_of(code)
    if mat is None:
        return None, "pending"
    cpn = facts.get("CPN")
    coupon = float(cpn) if kind in ("fixed", "cpi") and isinstance(cpn, (int, float)) and not isinstance(cpn, bool) else None
    name = _said(facts.get("SECURITY_DES")) or _said(facts.get("NAME")) or code
    return {"isin": code, "kind": kind, "maturity": mat.isoformat(), "name": name, "coupon": coupon}, ""


def waiting(isin: str) -> Dict[str, Any]:
    """A bond added whose kind is not known yet: its maturity from the ISIN (a Turkish one), nothing else."""
    code = str(isin or "").strip().upper()
    mat = maturity_of(code)
    return {"isin": code, "kind": None, "maturity": mat.isoformat() if mat else None, "name": "", "coupon": None}


# ---------------------------------------------------------------------------------------------- names, chat
def quoted_in_yield(bond: Dict[str, Any]) -> bool:
    """Bills and zero-coupon bonds trade on their yield; the rest on their price."""
    return bond.get("kind") in ("bill", "zero")


_TAIL = {"float": " TLREF", "frn": " FRN", "cpi": " TÜFE", "bill": " Bono", "zero": " Kuponsuz"}


def short_label(bond: Dict[str, Any]) -> str:
    """How the desk names a bond: "15.03.28", "09.01.30 TLREF", "05.05.27 FRN", "10.02.27 Bono", "08.05.30 TÜFE"."""
    if not bond.get("maturity"):
        return bond.get("isin") or ""
    d = _dt.date.fromisoformat(bond["maturity"])
    return d.strftime("%d.%m.%y") + _TAIL.get(bond.get("kind") or "", "")


def month_label(bond: Dict[str, Any]) -> str:
    d = _dt.date.fromisoformat(bond["maturity"])
    return "%s%02d" % (_MONTHS[d.month - 1], d.year % 100)


def candidates(date: Optional[str] = None, month: Optional[str] = None, kind: Optional[str] = None,
               extra: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """The bonds a chat line can mean: maturing on ``date`` (ISO) or in ``month`` ("2028-03"), of ``kind``
    ("fixed", "float" - a TLREF floater -, "frn", "floating" - either floater -, "cpi", "zc" - a bill or a zero
    coupon -, "any", or ``None``: a fixed coupon one first, then the rest).  ``extra``: bonds of the desk's own lists
    that are not in the catalog."""
    pool = list(catalog()) + [b for b in extra if b.get("isin") and not by_isin(b["isin"])]
    pool = [b for b in pool if b.get("maturity")]
    if date:
        hit = [b for b in pool if b.get("maturity") == date]
    elif month:
        hit = [b for b in pool if (b.get("maturity") or "").startswith(month)]
    else:
        return []
    if kind == "any":
        return hit
    if kind in ("fixed", "float", "frn", "cpi"):
        return [b for b in hit if b.get("kind") == kind]
    if kind == "floating":
        return [b for b in hit if b.get("kind") in FLOATERS]
    if kind == "zc":
        return [b for b in hit if b.get("kind") in ("bill", "zero")]          # zero coupon: never a coupon bond instead
    plain = [b for b in hit if b.get("kind") in ("fixed", "zero", "bill")]
    return plain or hit
