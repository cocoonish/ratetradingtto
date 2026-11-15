"""Desk alarms (Masa alarmları): set once, they ring for everyone - and everyone sees who is on it.

* **Alarms of the desk**: anything the watch can follow (a level, a move, a z-score - as the personal alarms),
  set by an administrator for everyone.  They are kept with the personal alarms (``watch.alarms``) as the
  market's: user ``""`` with ``desk`` set, so they are read on the market's values and never on someone's
  scenario; they fire once and are re-armed.
* **System alarms**: the Bloomberg data has not flowed for some minutes in market hours, the RET curve is not
  loaded by its time, no TLREF fixing by its time, the database's check or its backup failed.  The operations
  loop (ops.py) looks every 15 seconds; one fires when its condition starts to hold and closes by itself when
  the condition ends.

Every open page tells a firing (a toast, a tone, the browser's notification) and the top bar counts the alarms
nobody has answered yet.  "Gördüm, ben bakıyorum" answers one for everyone ("✓ Ayşe bakıyor"); an alarm can be
muted for a while (it does not fire meanwhile).  The day's log (``desk.alarmlog:<day>``) keeps all of it: what
fired, who answered, who muted, what was set, removed, re-armed.
"""
from __future__ import annotations

import datetime as _dt
import threading
from typing import Any, Dict, List, Optional

#: the system alarms: key -> name
SYSTEM = {"feed": "Bloomberg veri akışı", "ret": "RET eğrisi", "tlref": "TLREF fixingi", "db": "Veritabanı"}
#: how long an alarm may be muted (minutes; "gün" = until the end of the day)
MUTE_MINUTES = (15, 30, 60, 120)
MAX_LOG = 1000
ACTIONS = {"fired": "çaldı", "ack": "gördüm", "mute": "susturuldu", "unmute": "susturma kalktı", "resolved": "düzeldi",
           "set": "kuruldu", "removed": "silindi", "rearmed": "yeniden kuruldu", "settings": "ayarlar değişti"}


def _now() -> _dt.datetime:
    return _dt.datetime.now()


class DeskAlarmError(ValueError):
    pass


class DeskAlarms(object):
    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.RLock()
        self._mutes: Optional[Dict[str, Dict[str, Any]]] = None

    # ================================================================== the day's log
    def _key(self, day: Optional[str] = None) -> str:
        return "desk.alarmlog:%s" % (day or self.svc.today_iso())

    def log(self, day: Optional[str] = None) -> List[Dict[str, Any]]:
        v = self.svc.store.get(self._key(day), [])
        return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []

    def name(self, user: Optional[str]) -> str:
        """A user's name as the desk sees it."""
        if not user:
            return ""
        acc = self.svc.store.account(user)
        return (acc or {}).get("display") or user

    def _add(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            entries = self.log()
            entry = dict(entry, seq=max([int(e.get("seq") or 0) for e in entries] or [0]) + 1,
                         at=entry.get("at") or _now().strftime("%H:%M:%S"))
            if entry.get("by") and not entry.get("by_name"):
                entry["by_name"] = self.name(entry["by"])
            entries.append(entry)
            self.svc.store.put(self._key(), entries[-MAX_LOG:])
            return entry

    def note(self, kind: str, alarm: str, label: str, text: str = "", by: Optional[str] = None) -> Dict[str, Any]:
        """A line of the log for what was done to an alarm (set, removed, re-armed, the settings changed)."""
        return self._add({"kind": kind, "alarm": alarm, "label": label, "text": text, "by": by})

    @staticmethod
    def _current(alarm: str, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """The alarm's last firing of the day when it is not closed."""
        for e in reversed(entries):
            if e.get("alarm") == alarm and e.get("kind") == "fired":
                return None if e.get("closed_at") else e
        return None

    # ================================================================== firing
    def fired(self, events: List[Dict[str, Any]]) -> None:
        """The desk's alarms that fired in a round of the watch (Watch.tick)."""
        for e in events:
            with self._lock:
                entries = self.log()
                old = self._current(e["id"], entries)
                if old is not None:                      # an earlier firing still open: it is answered by this one
                    self._close(old["seq"], "yeniden çaldı")
            # "35,90% (≥ 35,80%)"; a move or a z-score with its measure: "35,90% · +15,0 bp (açılıştan ± 15,0 bp)"
            level = (e.get("mode") or "level") == "level"
            text = ("%s (%s)" % (e.get("value_text") or "", e.get("condition") or "")) if level else \
                "%s · %s (%s)" % (e.get("value_text") or "", e.get("measure_text") or "", e.get("condition") or "")
            self._add({"kind": "fired", "alarm": e["id"], "label": e.get("label") or "", "at": e.get("time"), "text": text,
                       "value_text": e.get("value_text") or "", "condition": e.get("condition") or "",
                       "measure_text": e.get("measure_text") or "", "note": e.get("note") or "", "system": False,
                       "set_by": e.get("by") or ""})

    def system(self, kind: str, active: bool, text: str = "") -> Optional[Dict[str, Any]]:
        """A system alarm's condition now: it fires when the condition starts to hold (not while it is muted) and
        closes ("düzeldi") when it ends.  Returns the line written, if any."""
        alarm = "sys:" + kind
        with self._lock:
            cur = self._current(alarm, self.log())
            if active and cur is None:
                if self.muted(alarm):
                    return None
                return self._add({"kind": "fired", "alarm": alarm, "label": SYSTEM[kind], "text": text, "system": True})
            if not active and cur is not None:
                self._close(cur["seq"], "düzeldi")
                return self._add({"kind": "resolved", "alarm": alarm, "label": SYSTEM[kind], "text": "durum normale döndü"})
        return None

    def _close(self, seq: int, why: str) -> None:
        with self._lock:
            entries = self.log()
            for e in entries:
                if e.get("seq") == seq and not e.get("closed_at"):
                    e["closed_at"], e["closed_why"] = _now().strftime("%H:%M:%S"), why
                    self.svc.store.put(self._key(), entries)
                    return

    def close(self, alarm: str, why: str) -> None:
        """An alarm re-armed or removed: its firing of the day is no longer open."""
        with self._lock:
            cur = self._current(alarm, self.log())
            if cur is not None:
                self._close(cur["seq"], why)

    # ================================================================== answering
    def ack(self, user: str, seq: Any) -> Dict[str, Any]:
        """"Gördüm, ben bakıyorum": a firing answered for everyone."""
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            raise DeskAlarmError("hangi alarm?")
        with self._lock:
            entries = self.log()
            e = next((x for x in entries if x.get("seq") == seq and x.get("kind") == "fired"), None)
            if e is None:
                raise DeskAlarmError("bu alarm bugünün kaydında yok")
            if e.get("ack_by"):
                return e                                  # someone was quicker: theirs stands
            e["ack_by"], e["ack_name"], e["ack_at"] = user, self.name(user), _now().strftime("%H:%M:%S")
            self.svc.store.put(self._key(), entries)
            self._add({"kind": "ack", "alarm": e["alarm"], "label": e.get("label") or "", "ref": seq, "by": user,
                       "by_name": e["ack_name"], "text": "Gördüm – %s bakıyor" % e["ack_name"]})
            return e

    def mutes(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            if self._mutes is None:
                v = self.svc.store.get("desk.mutes", {})
                self._mutes = v if isinstance(v, dict) else {}
            return self._mutes

    def muted(self, alarm: str, now: Optional[_dt.datetime] = None) -> Optional[Dict[str, Any]]:
        """The mute of an alarm while it lasts (``None``: it may fire)."""
        m = self.mutes().get(alarm)
        if not m:
            return None
        return m if (now or _now()).strftime("%Y-%m-%d %H:%M:%S") < str(m.get("until") or "") else None

    def mute(self, user: str, alarm: str, minutes: Any, label: str = "") -> Dict[str, Any]:
        """Keep an alarm from firing for ``minutes`` (15, 30, 60, 120; "gün": until the end of the day; 0: lift it)."""
        now = _now()
        if minutes in ("gün", "day"):
            until = now.replace(hour=23, minute=59, second=59, microsecond=0)
            span = "gün sonuna kadar"
        else:
            try:
                minutes = int(minutes)
            except (TypeError, ValueError):
                raise DeskAlarmError("süre anlaşılmadı: %r" % (minutes,))
            if minutes and minutes not in MUTE_MINUTES:
                raise DeskAlarmError("susturma süresi 15, 30, 60, 120 dakika ya da gün sonuna kadar olur")
            until = now + _dt.timedelta(minutes=minutes)
            span = "%d dk" % minutes
        with self._lock:
            mutes = dict(self.mutes())
            if not minutes:
                had = mutes.pop(alarm, None)
                self._mutes = mutes
                self.svc.store.put("desk.mutes", mutes)
                if had:
                    self._add({"kind": "unmute", "alarm": alarm, "label": label, "by": user, "text": "susturma kaldırıldı"})
                return {"alarm": alarm, "until": None}
            m = {"until": until.strftime("%Y-%m-%d %H:%M:%S"), "by": user, "by_name": self.name(user)}
            mutes = {k: v for k, v in mutes.items() if str(v.get("until") or "") > now.strftime("%Y-%m-%d %H:%M:%S")}
            mutes[alarm] = m
            self._mutes = mutes
            self.svc.store.put("desk.mutes", mutes)
            self._add({"kind": "mute", "alarm": alarm, "label": label, "by": user, "by_name": m["by_name"],
                       "text": "%s susturuldu (bitiş %s)" % (span, until.strftime("%H:%M"))})
            return dict(m, alarm=alarm)

    # ================================================================== what the pages get
    @staticmethod
    def opened(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Firings nobody has answered and that have not closed: what the top bar counts."""
        return [e for e in entries if e.get("kind") == "fired" and not e.get("ack_by") and not e.get("closed_at")]

    def since(self, seq: Any) -> Dict[str, Any]:
        """The log's lines after ``seq`` (the last a page has seen), the open firings and the day's last number."""
        try:
            seq = int(seq or 0)
        except (TypeError, ValueError):
            seq = 0
        entries = self.log()
        last = max([int(e.get("seq") or 0) for e in entries] or [0])
        if seq > last:
            seq = 0                                       # a new day began: its log starts again from 1
        return {"events": [e for e in entries if int(e.get("seq") or 0) > seq], "last": last, "open": self.opened(entries)}
