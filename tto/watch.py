"""Watching the market: each user's watch list (any cell of any page - its level now, the day's open, high and
low, the change since the open and since a reference the user takes, when it last moved and its path through
the day), alarms on any cell (at or above a level, at or below it, or crossing it), the alarms that fired today,
and the desk's notes of the day.

Kept in the store's key / value table: the watch lists (``watch.items``: user -> items), the alarms
(``watch.alarms``), what fired (``watch.fired:<day>``), the opens of the day (``watch.open:<day>``) and the notes
(``desk.notes:<day>``).  The path of a day is held in memory (a restart starts it again from the open).

:meth:`Watch.tick` runs on the calculation thread after the market or an input moved; it reads every watched
cell with its owner's calculation (personal scenarios included) and tells which alarms fired.
"""
from __future__ import annotations

import datetime as _dt
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .xl import numfmt
from .xl.model import COLS

#: the units a change is told in: a rate in per cent (35.10: bp = × 100), a rate as a fraction (0.351: bp =
#: × 10 000), basis points, a price or an FX level (the difference itself)
UNITS = {"pct": ("bp", 100.0), "frac": ("bp", 10000.0), "bp": ("bp", 1.0), "px": ("puan", 1.0), "fx": ("", 1.0)}
OPS = {">=": "≥", "<=": "≤", "x": "kesişir"}
MAX_ITEMS = 60          # per user
MAX_ALARMS = 200        # for the desk
MAX_PATH = 1500         # points of a day's path (thinned beyond)

#: ready-made groups the watch list takes in one click: (group, [(label, book, ref, unit)])
PRESETS: List[Tuple[str, List[Tuple[str, str, str, str]]]] = [
    ("Masa", [("USDTRY mid", "tto", "MASA!H2", "fx"), ("TLREF", "tto", "MASA!J2", "frac"),
              ("İma 1Y sonu TLREF", "tto", "MASA!L2", "frac"), ("İma 12A (bp)", "tto", "MASA!M2", "bp"),
              ("İma / PPK (bp)", "tto", "MASA!N2", "bp")]),
    ("TRY OIS eğrisi", [("OIS %s" % t, "tto", "OIS_MAIN!B%d" % r, "frac") for t, r in
                        (("1M", 9), ("3M", 11), ("6M", 12), ("1Y", 14), ("18M", 16), ("2Y", 18), ("3Y", 19), ("5Y", 21),
                         ("10Y", 26))]),
]


def _now() -> _dt.datetime:
    return _dt.datetime.now()


class Watch(object):
    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self.day = ""
        # (user, book, ref) -> {"open", "high", "low", "last", "moved", "path": [(time, value)]}
        self.days: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    # ------------------------------------------------------------------ what is kept
    def _items_all(self) -> Dict[str, List[Dict[str, Any]]]:
        v = self.svc.store.get("watch.items", {})
        return v if isinstance(v, dict) else {}

    def items(self, user: str) -> List[Dict[str, Any]]:
        return list(self._items_all().get(user) or [])

    def _put_items(self, user: str, items: List[Dict[str, Any]]) -> None:
        with self._lock:
            allv = self._items_all()
            allv[user] = items
            self.svc.store.put("watch.items", allv)

    def alarms(self, user: Optional[str] = None) -> List[Dict[str, Any]]:
        v = self.svc.store.get("watch.alarms", [])
        v = [a for a in v if isinstance(a, dict)] if isinstance(v, list) else []
        return [a for a in v if user is None or a.get("user") == user]

    def _put_alarms(self, alarms: List[Dict[str, Any]]) -> None:
        self.svc.store.put("watch.alarms", alarms[-MAX_ALARMS:])

    def fired(self, day: Optional[str] = None) -> List[Dict[str, Any]]:
        v = self.svc.store.get("watch.fired:%s" % (day or self.svc.today_iso()), [])
        return v if isinstance(v, list) else []

    # ------------------------------------------------------------------ cells
    def _cell(self, book_id: str, ref: str) -> Tuple[Any, int, int]:
        book = self.svc.books.get(book_id)
        if book is None:
            raise KeyError(book_id)
        si, rc = book.cell(ref)
        r, c = divmod(rc, COLS)
        return book, si, r * COLS + c

    def describe(self, user: Optional[str], book_id: str, ref: str) -> Dict[str, Any]:
        """What a cell is and shows now: its value, its text, its number format (for the unit of a change)."""
        from .store import user_key
        book, si, rc = self._cell(book_id, ref)
        calc = self.svc._calc(user_key(user) if user else None, book)
        r, c = divmod(rc, COLS)
        v = calc.get(si, r, c)
        sheet = book.model.sheets[si]
        x = sheet.styles.get(rc, 0)
        fmt = book.model.numfmts[x] if x < len(book.model.numfmts) else "General"
        return {"ref": book.ref(si, rc), "value": v if type(v) is float else None, "fmt": fmt,
                "percent": numfmt.is_percent_format(fmt)}

    @staticmethod
    def guess_unit(value: Optional[float], percent: bool) -> str:
        """The unit of a cell's change: a percent format is a rate as a fraction (bp); a level between 1 and 100
        with no format of its own reads as a rate in per cent; anything else as a price."""
        if percent:
            return "frac"
        if value is not None and 1.0 <= abs(value) <= 100.0:
            return "pct"
        return "px"

    # ------------------------------------------------------------------ the watch list
    def add(self, user: str, book_id: str, ref: str, label: str = "", unit: str = "") -> Dict[str, Any]:
        info = self.describe(user, book_id, ref)                 # raises when there is no such cell
        items = self.items(user)
        if any(i["book"] == book_id and i["ref"] == info["ref"] for i in items):
            return {"added": False, "items": items}
        if len(items) >= MAX_ITEMS:
            raise ValueError("izleme listesi dolu (%d)" % MAX_ITEMS)
        item = {"id": uuid.uuid4().hex[:10], "book": book_id, "ref": info["ref"], "label": (label or info["ref"]).strip()[:60],
                "unit": unit if unit in UNITS else self.guess_unit(info["value"], info["percent"]), "base": None, "base_at": None,
                "fmt": info["fmt"]}
        items.append(item)
        self._put_items(user, items)
        return {"added": True, "item": item, "items": items}

    def add_preset(self, user: str, group: str) -> Dict[str, Any]:
        found = next((p for g, p in PRESETS if g == group), None)
        if found is None:
            raise ValueError("hazır grup yok: %s" % group)
        n = 0
        for label, book_id, ref, unit in found:
            if book_id in self.svc.books:
                try:
                    n += 1 if self.add(user, book_id, ref, label, unit)["added"] else 0
                except (KeyError, ValueError):
                    continue
        return {"added": n}

    def remove(self, user: str, item_id: str) -> int:
        items = self.items(user)
        keep = [i for i in items if i["id"] != item_id]
        self._put_items(user, keep)
        return len(items) - len(keep)

    def update(self, user: str, item_id: str, label: Optional[str] = None, unit: Optional[str] = None,
               move: Optional[int] = None) -> None:
        items = self.items(user)
        k = next((n for n, i in enumerate(items) if i["id"] == item_id), None)
        if k is None:
            raise KeyError(item_id)
        if label is not None and label.strip():
            items[k]["label"] = label.strip()[:60]
        if unit is not None and unit in UNITS:
            items[k]["unit"] = unit
        if move:
            j = max(0, min(len(items) - 1, k + int(move)))
            items.insert(j, items.pop(k))
        self._put_items(user, items)

    def set_base(self, user: str, item_id: Optional[str] = None) -> int:
        """The reference a change is also told against ("since the morning meeting"): the level now - of one
        item, or of every item (``item_id`` ``None``); taken again it is replaced, cleared with ``clear``."""
        from .store import user_key
        items = self.items(user)
        at = _now().strftime("%H:%M:%S")
        n = 0
        for i in items:
            if item_id is not None and i["id"] != item_id:
                continue
            try:
                book, si, rc = self._cell(i["book"], i["ref"])
            except (KeyError, ValueError):
                continue
            v = self.svc._calc(user_key(user), book).get(si, *divmod(rc, COLS))
            if type(v) is float:
                i["base"], i["base_at"] = v, self.svc.today_iso() + " " + at
                n += 1
        self._put_items(user, items)
        return n

    # ------------------------------------------------------------------ alarms
    @staticmethod
    def as_value(level: float, percent: bool) -> float:
        """A level typed as the cell shows it: on a cell in per cent (35,50%) "35.50" means 0.355."""
        return level / 100.0 if percent and abs(level) > 1.5 else level

    def add_alarm(self, user: str, book_id: str, ref: str, op: str, level: float, label: str = "", note: str = "") -> Dict[str, Any]:
        if op not in OPS:
            raise ValueError("koşul: ≥, ≤ ya da kesişir")
        if type(level) is not float:
            raise ValueError("seviye bir sayı olmalı")
        info = self.describe(user, book_id, ref)
        level = self.as_value(level, info["percent"])
        alarms = self.alarms()
        if len(alarms) >= MAX_ALARMS:
            raise ValueError("alarm listesi dolu (%d)" % MAX_ALARMS)
        a = {"id": uuid.uuid4().hex[:10], "user": user, "book": book_id, "ref": info["ref"], "op": op, "level": level,
             "label": (label or info["ref"]).strip()[:60], "note": (note or "").strip()[:200], "active": True,
             "created": _now().strftime("%Y-%m-%d %H:%M:%S"), "fired_at": None, "fired_value": None, "last": info["value"],
             "unit": self.guess_unit(info["value"], info["percent"]), "fmt": info["fmt"]}
        alarms.append(a)
        self._put_alarms(alarms)
        v = info["value"]
        already = v is not None and ((op == ">=" and v >= level) or (op == "<=" and v <= level))
        return {"alarm": a, "already": already, "value": v}

    def remove_alarm(self, user: str, alarm_id: str) -> int:
        alarms = self.alarms()
        keep = [a for a in alarms if not (a["id"] == alarm_id and a.get("user") == user)]
        self._put_alarms(keep)
        return len(alarms) - len(keep)

    def rearm(self, user: str, alarm_id: str, level: Optional[float] = None) -> Dict[str, Any]:
        alarms = self.alarms()
        a = next((x for x in alarms if x["id"] == alarm_id and x.get("user") == user), None)
        if a is None:
            raise KeyError(alarm_id)
        a["active"], a["fired_at"], a["fired_value"] = True, None, None
        if type(level) is float:
            a["level"] = self.as_value(level, numfmt.is_percent_format(a.get("fmt") or "General"))
        self._put_alarms(alarms)
        return a

    # ------------------------------------------------------------------ the tick (calculation thread)
    def tick(self) -> List[Dict[str, Any]]:
        """Read every watched cell and every armed alarm's cell; keep the day's open, high, low and path; fire
        the alarms whose condition holds (``>=`` / ``<=``: the level is reached; ``x``: crossed since the last
        reading).  Returns what fired now."""
        from .store import user_key
        today = self.svc.today_iso()
        now = _now().strftime("%H:%M:%S")
        if today != self.day:
            self.day = today
            self.days = {}
            opened = self.svc.store.get("watch.open:%s" % today, {})
            for key, v in (opened.items() if isinstance(opened, dict) else ()):
                parts = key.split("|", 2)
                if len(parts) == 3 and type(v) is float:
                    self.days[tuple(parts)] = {"open": v, "high": v, "low": v, "last": v, "moved": None, "path": []}
        calcs: Dict[Tuple[str, str], Any] = {}

        def value(user: str, book_id: str, ref: str) -> Any:
            try:
                book, si, rc = self._cell(book_id, ref)
            except (KeyError, ValueError):
                return None
            calc = calcs.get((user, book_id))
            if calc is None:
                calc = calcs[(user, book_id)] = self.svc._calc(user_key(user) if user else None, book)
            try:
                return calc.get(si, *divmod(rc, COLS))
            except Exception:  # noqa: BLE001 - a cell that cannot be read is not watched this time
                return None

        new_opens: Dict[str, float] = {}
        for user, items in self._items_all().items():
            for i in items or []:
                v = value(user, i["book"], i["ref"])
                if type(v) is not float:
                    continue
                key = (user, i["book"], i["ref"])
                d = self.days.get(key)
                if d is None:
                    d = self.days[key] = {"open": v, "high": v, "low": v, "last": None, "moved": None, "path": []}
                    new_opens["|".join(key)] = v
                if d["last"] is not None and v != d["last"]:
                    d["moved"] = now
                if d["last"] is None or v != d["last"] or not d["path"]:
                    d["path"].append((now, v))
                    if len(d["path"]) > MAX_PATH:
                        d["path"] = d["path"][:1] + d["path"][1::2]          # thinned: the open stays
                d["last"] = v
                d["high"], d["low"] = max(d["high"], v), min(d["low"], v)
        if new_opens:
            opened = self.svc.store.get("watch.open:%s" % today, {})
            opened = opened if isinstance(opened, dict) else {}
            opened.update(new_opens)
            self.svc.store.put("watch.open:%s" % today, opened)
        alarms = self.alarms()
        fired: List[Dict[str, Any]] = []
        changed = False
        for a in alarms:
            if not a.get("active"):
                continue
            v = value(a.get("user") or "", a["book"], a["ref"])
            if type(v) is not float:
                continue
            prev, level = a.get("last"), a["level"]
            hit = (a["op"] == ">=" and v >= level) or (a["op"] == "<=" and v <= level) or \
                (a["op"] == "x" and type(prev) is float and ((prev < level <= v) or (prev > level >= v)))
            if v != prev:
                a["last"] = v
                changed = True
            if hit:
                a["active"], a["fired_at"], a["fired_value"] = False, today + " " + now, v
                fmt = a.get("fmt") or "General"
                loc = numfmt.get_locale(self.svc.settings.locale)
                fired.append({"id": a["id"], "user": a.get("user"), "label": a["label"], "book": a["book"], "ref": a["ref"],
                              "op": a["op"], "level": level, "value": v, "unit": a.get("unit"), "time": now, "note": a.get("note", ""),
                              "level_text": numfmt.format_value(level, fmt, loc), "value_text": numfmt.format_value(v, fmt, loc)})
                changed = True
        if changed:
            self._put_alarms(alarms)
        if fired:
            log = self.fired(today)
            seq = max([int(e.get("seq") or 0) for e in log] or [0])
            for e in fired:
                seq += 1
                e["seq"] = seq
            self.svc.store.put("watch.fired:%s" % today, (log + fired)[-500:])
        return fired

    # ------------------------------------------------------------------ what the page shows
    def snapshot(self, user: str, loc) -> Dict[str, Any]:
        from .store import user_key
        out_items = []
        for i in self.items(user):
            info: Dict[str, Any] = {}
            try:
                book, si, rc = self._cell(i["book"], i["ref"])
                calc = self.svc._calc(user_key(user), book)
                cell = self.svc.renderers[book.id].cell(calc, si, *divmod(rc, COLS), loc)
                info = {"text": cell.get("t", ""), "value": cell.get("v") if type(cell.get("v")) is float else None}
            except (KeyError, ValueError):
                info = {"text": "hücre yok", "value": None}
            d = self.days.get((user, i["book"], i["ref"])) or {}
            name, k = UNITS.get(i.get("unit") or "px", UNITS["px"])
            v = info["value"]
            fmt = i.get("fmt") or "General"

            def chg(a: Any) -> Optional[float]:
                return (v - a) * k if type(v) is float and type(a) is float else None

            def txt(x: Any) -> str:
                return numfmt.format_value(x, fmt, loc) if type(x) is float else ""

            out_items.append(dict(i, now=info["text"], value=v, open=d.get("open"), high=d.get("high"), low=d.get("low"),
                                  open_text=txt(d.get("open")), high_text=txt(d.get("high")), low_text=txt(d.get("low")),
                                  base_text=txt(i.get("base")), moved=d.get("moved"), change=chg(d.get("open")),
                                  since_base=chg(i.get("base")), unit_name=name, path=[p[1] for p in d.get("path") or []][-240:]))
        alarms = []
        for a in self.alarms(user):
            try:
                book, si, rc = self._cell(a["book"], a["ref"])
                v = self.svc._calc(user_key(user), book).get(si, *divmod(rc, COLS))
            except (KeyError, ValueError):
                v = None
            name, k = UNITS.get(a.get("unit") or "px", UNITS["px"])
            fmt = a.get("fmt") or "General"
            alarms.append(dict(a, now=v if type(v) is float else None, unit_name=name,
                               now_text=numfmt.format_value(v, fmt, loc) if type(v) is float else "",
                               level_text=numfmt.format_value(a["level"], fmt, loc),
                               fired_text=numfmt.format_value(a["fired_value"], fmt, loc) if type(a.get("fired_value")) is float else "",
                               distance=(a["level"] - v) * k if type(v) is float else None))
        notes = self.svc.store.get("desk.notes:%s" % self.svc.today_iso(), {})
        return {"items": out_items, "alarms": alarms, "fired": [e for e in self.fired() if e.get("user") == user],
                "notes": notes if isinstance(notes, dict) else {}, "presets": [{"group": g, "items": [x[0] for x in p]} for g, p in PRESETS],
                "units": {k: v[0] for k, v in UNITS.items()}, "ops": OPS, "day": self.svc.today_iso()}
