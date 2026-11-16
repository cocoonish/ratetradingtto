"""Each user's own arrangement of the dashboard: launchpads (named pages of tables picked from any page), the side
drawer, the favourite pages of the top bar and the page the dashboard opens on.

It is kept with the account in the store's key / value table (``layout.<user>``), so it follows the sign-in to any
computer and survives an update of the dashboard.  Everything sent is checked and normalised here (the service holds
the lock and the size limit); what is stored is only what these checks let through.

An item of a launchpad (or of the drawer) names its ``type``: a table of a page is ``"table"``.  Another kind of item
(a box of one of the dashboard's own pages, a calculation sheet ...) registers its own check in ``ITEM_TYPES`` - the
launchpads, the drawer and the common fields of an item (``id``, ``title``, ``w``, ``h``, ``collapsed``) stay as they are.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Callable, Dict, List, Optional

#: the widths of an item, in columns of the launchpad's 12: ¼ ⅓ ½ ⅔ and the whole width
WIDTHS = (3, 4, 6, 8, 12)
DEFAULT_WIDTH = 6
#: a fixed height (px) - the table scrolls inside; "auto": as tall as the table
MIN_HEIGHT, MAX_HEIGHT = 80, 2400
MAX_LAUNCHPADS = 24
MAX_ITEMS = 60                       # on one launchpad
MAX_DRAWER = 24
MAX_FAVS = 40
MAX_NAME = 60
MAX_TITLE = 120
MAX_ROWS = 300                       # the rows picked of one table
MAX_COLS = 200                       # the columns picked of one table
MAX_LABEL = 80

_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
#: a page (view) id and a panel id: the global key of a table is "<view>/<panel>"
PAGE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
PANEL_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,60}$")
#: a column of a table: its letter in the sheet, or the name of a column the dashboard adds ("DV01 B")
_COLUMN = re.compile(r"^[^\x00-\x1f]{1,24}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class LayoutError(ValueError):
    """What was sent is not a layout (the service answers 400 with the message)."""


def _text(v: Any, limit: int, what: str, empty_ok: bool = False) -> str:
    if not isinstance(v, str):
        raise LayoutError("%s bir metin olmalı" % what)
    t = " ".join(_CONTROL.sub(" ", v).split())
    if not t and not empty_ok:
        raise LayoutError("%s boş olamaz" % what)
    if len(t) > limit:
        raise LayoutError("%s en fazla %d karakter olabilir" % (what, limit))
    return t


def _flag(v: Any) -> bool:
    return v is True


def rows_choice(v: Any) -> List[Any]:
    """The rows of a table an item shows: each a row's label (its first text from the left) or its number in the
    sheet.  An empty list: every row."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > MAX_ROWS:
        raise LayoutError("satır seçimi en fazla %d satırlık bir liste olmalı" % MAX_ROWS)
    out: List[Any] = []
    for x in v:
        if isinstance(x, bool):
            raise LayoutError("satır seçimi geçersiz")
        if isinstance(x, int):
            if not 0 < x <= 1048576:
                raise LayoutError("satır numarası geçersiz")
        elif isinstance(x, str):
            x = _text(x, MAX_LABEL, "satır adı")
        else:
            raise LayoutError("satır seçimi geçersiz")
        if x not in out:
            out.append(x)
    return out


def cols_choice(v: Any) -> List[str]:
    """The columns of a table an item shows, by letter (an empty list: every column)."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > MAX_COLS:
        raise LayoutError("sütun seçimi en fazla %d sütunluk bir liste olmalı" % MAX_COLS)
    out: List[str] = []
    for x in v:
        if not isinstance(x, str) or not _COLUMN.match(x):
            raise LayoutError("sütun seçimi geçersiz")
        if x not in out:
            out.append(x)
    return out


def _table_item(x: Dict[str, Any], out: Dict[str, Any]) -> None:
    """A table of a page: ``view`` / ``panel`` name it; ``rows`` / ``cols`` a part of it; ``all``: it is one of the
    helper tables (or has the columns Excel hides) - the page's "Yardımcı tablolar"."""
    view, panel = x.get("view"), x.get("panel")
    if not isinstance(view, str) or not PAGE_ID.match(view):
        raise LayoutError("tablonun sayfası geçersiz")
    if not isinstance(panel, str) or not PANEL_ID.match(panel):
        raise LayoutError("tablo adı geçersiz")
    out["view"] = view
    out["panel"] = panel
    rows = rows_choice(x.get("rows"))
    cols = cols_choice(x.get("cols"))
    if rows:
        out["rows"] = rows
    if cols:
        out["cols"] = cols
    if _flag(x.get("all")):
        out["all"] = True


#: type -> its check (fills the normalised item from what was sent; raises LayoutError).  Later kinds of items add
#: themselves here.
ITEM_TYPES: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], None]] = {"table": _table_item}


def item(x: Any) -> Dict[str, Any]:
    """One item of a launchpad or of the drawer, normalised (what is not part of it is left out)."""
    if not isinstance(x, dict):
        raise LayoutError("öğe geçersiz")
    kind = x.get("type", "table")
    check = ITEM_TYPES.get(kind) if isinstance(kind, str) else None
    if check is None:
        raise LayoutError("bilinmeyen öğe türü: %s" % str(kind)[:40])
    out: Dict[str, Any] = {"type": kind}
    iid = x.get("id")
    out["id"] = iid if isinstance(iid, str) and _ID.match(iid) else uuid.uuid4().hex[:10]
    check(x, out)
    if x.get("title") not in (None, ""):
        title = _text(x["title"], MAX_TITLE, "başlık", empty_ok=True)
        if title:
            out["title"] = title
    w = x.get("w", DEFAULT_WIDTH)
    if isinstance(w, bool) or w not in WIDTHS:
        raise LayoutError("genişlik %s olmalı" % " / ".join(str(n) for n in WIDTHS))
    out["w"] = w
    hv = x.get("h", "auto")
    if hv != "auto":
        if isinstance(hv, bool) or not isinstance(hv, int) or not MIN_HEIGHT <= hv <= MAX_HEIGHT:
            raise LayoutError("yükseklik \"auto\" ya da %d–%d piksel olmalı" % (MIN_HEIGHT, MAX_HEIGHT))
    out["h"] = hv
    if _flag(x.get("collapsed")):
        out["collapsed"] = True
    return out


def items(v: Any, limit: int, what: str) -> List[Dict[str, Any]]:
    if not isinstance(v, list):
        raise LayoutError("%s bir liste olmalı" % what)
    if len(v) > limit:
        raise LayoutError("%s en fazla %d tablo alır" % (what, limit))
    out: List[Dict[str, Any]] = []
    seen = set()
    for x in v:
        it = item(x)
        while it["id"] in seen:                       # (two items with one id: the second gets its own)
            it["id"] = uuid.uuid4().hex[:10]
        seen.add(it["id"])
        out.append(it)
    return out


def name_key(name: str) -> str:
    """Names are told apart without case (Turkish rules): "Sabah" and "SABAH" are one launchpad."""
    return name.replace("I", "ı").replace("İ", "i").lower()


def launchpad(x: Any) -> Dict[str, Any]:
    if not isinstance(x, dict):
        raise LayoutError("launchpad geçersiz")
    return {"name": _text(x.get("name"), MAX_NAME, "launchpad adı"),
            "items": items(x.get("items", []), MAX_ITEMS, "bir launchpad")}


def launchpads(v: Any) -> List[Dict[str, Any]]:
    if not isinstance(v, list):
        raise LayoutError("launchpad listesi geçersiz")
    if len(v) > MAX_LAUNCHPADS:
        raise LayoutError("en fazla %d launchpad olabilir" % MAX_LAUNCHPADS)
    out = [launchpad(x) for x in v]
    seen = set()
    for lp in out:
        k = name_key(lp["name"])
        if k in seen:
            raise LayoutError("iki launchpad aynı adı taşıyamaz: %s" % lp["name"])
        seen.add(k)
    return out


def page_id(v: Any, what: str) -> str:
    if not isinstance(v, str) or not PAGE_ID.match(v):
        raise LayoutError("%s geçersiz" % what)
    return v


def favs(v: Any) -> List[str]:
    if not isinstance(v, list) or len(v) > MAX_FAVS:
        raise LayoutError("favori sayfalar en fazla %d sayfalık bir liste olmalı" % MAX_FAVS)
    return list(dict.fromkeys(page_id(x, "favori sayfa") for x in v))


def landing(v: Any) -> str:
    """The page the dashboard opens on: a page's id, ``launchpad/<name>``, or "" (the desk's default)."""
    if v is None or v == "":
        return ""
    if not isinstance(v, str):
        raise LayoutError("açılış sayfası geçersiz")
    if v.startswith("launchpad/"):
        return "launchpad/" + _text(v[len("launchpad/"):], MAX_NAME, "açılış launchpad'i")
    return page_id(v, "açılış sayfası")


#: the parts of a layout and their checks; a change sends any of them and replaces those (the others stay)
SECTIONS: Dict[str, Callable[[Any], Any]] = {
    "launchpads": launchpads,
    "drawer": lambda v: items(v, MAX_DRAWER, "yan panel"),
    "favs": favs,
    "landing": landing,
}


def empty() -> Dict[str, Any]:
    return {"launchpads": [], "drawer": [], "favs": [], "landing": "", "rev": 0}


def _kept_items(v: Any, limit: int) -> List[Dict[str, Any]]:
    """The items of a list as kept, each checked on its own: one that does not pass today's checks (a kind of item this
    version does not know) is left out, the others stay."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for x in v if isinstance(v, list) else []:
        try:
            it = item(x)
        except LayoutError:
            continue
        if it["id"] in seen or len(out) >= limit:
            continue
        seen.add(it["id"])
        out.append(it)
    return out


def stored(v: Any) -> Dict[str, Any]:
    """What is kept, as the browser gets it.  Read leniently - a launchpad or an item that does not pass today's checks
    (written by another version) is left out by itself, never the whole part with it."""
    out = empty()
    if not isinstance(v, dict):
        return out
    names = set()
    for x in v.get("launchpads") if isinstance(v.get("launchpads"), list) else []:
        try:
            name = _text(x.get("name"), MAX_NAME, "launchpad adı") if isinstance(x, dict) else None
        except LayoutError:
            name = None
        if not name or name_key(name) in names or len(out["launchpads"]) >= MAX_LAUNCHPADS:
            continue
        names.add(name_key(name))
        out["launchpads"].append({"name": name, "items": _kept_items(x.get("items"), MAX_ITEMS)})
    out["drawer"] = _kept_items(v.get("drawer"), MAX_DRAWER)
    out["favs"] = [x for x in (v.get("favs") if isinstance(v.get("favs"), list) else [])
                   if isinstance(x, str) and PAGE_ID.match(x)][:MAX_FAVS]
    try:
        out["landing"] = landing(v.get("landing"))
    except LayoutError:
        out["landing"] = ""
    rev = v.get("rev")
    out["rev"] = rev if isinstance(rev, int) and not isinstance(rev, bool) else 0
    return out


def change(cur: Dict[str, Any], data: Any) -> Dict[str, Any]:
    """``cur`` with the parts ``data`` sends replaced (``rev`` counts the changes)."""
    if not isinstance(data, dict):
        raise LayoutError("düzen geçersiz")
    parts = [k for k in data if k in SECTIONS]
    if not parts:
        raise LayoutError("değişecek bir şey yok (launchpads, drawer, favs ya da landing)")
    out = dict(cur)
    for k in parts:
        out[k] = SECTIONS[k](data[k])
    out["rev"] = int(cur.get("rev") or 0) + 1
    return out


def unique_name(name: str, taken: List[str]) -> str:
    """``name``, or "name (2)", "name (3)" ... when a launchpad has it already."""
    keys = {name_key(t) for t in taken}
    if name_key(name) not in keys:
        return name
    for n in range(2, 1000):
        suffix = " (%d)" % n
        cand = name[:MAX_NAME - len(suffix)] + suffix
        if name_key(cand) not in keys:
            return cand
    raise LayoutError("bu adla çok fazla launchpad var")


EXPORT_KIND = "tto-launchpad"


def export(lp: Dict[str, Any]) -> Dict[str, Any]:
    """A launchpad as a file of its own (to keep, or to give a colleague: their dashboard imports it)."""
    return {"kind": EXPORT_KIND, "version": 1, "name": lp["name"], "items": lp["items"]}


def imported(data: Any, name: Optional[str] = None) -> Dict[str, Any]:
    """A launchpad read from such a file (or a bare ``{"name", "items"}``)."""
    if not isinstance(data, dict):
        raise LayoutError("dosya bir launchpad değil")
    if "kind" in data and data["kind"] != EXPORT_KIND:
        raise LayoutError("dosya bir launchpad değil")
    lp = launchpad({"name": name if name else data.get("name"), "items": data.get("items", [])})
    return lp
