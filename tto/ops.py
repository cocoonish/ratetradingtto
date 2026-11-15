"""Operations: the dashboard's log file, what went wrong last, and how fresh the market data on the screens is.

* **The log.**  ``python -m tto`` writes ``tto.log`` (rotated at 5 MB, five old files kept) to the install's data
  folder (``data/logs``, outside what git keeps) or to ``--log-dir``.  The background loops log what they used to
  swallow - once with its traceback, then at most once a minute with a count, so a fault that repeats every
  second does not fill the disk.
* **Is the data fresh?**  Prices can stop while everything still looks alive: the Bloomberg helper process may
  hang (it reports at least once a second, so a few seconds of silence is telling), or the session may stay
  connected while no tick arrives.  :func:`feed_state` turns the provider's status into ``ok`` / ``stale`` /
  ``silent`` / ``down`` with the time the data is "as of"; the badge of the top bar shows it.  Ticks are only
  expected in market hours (the desk's days - week days that are not its holidays - between the hours of the
  settings).
* **Settings the desk may tune** (``ops.settings`` in the store; the administrators change them on the alarms
  page): the market hours and how long without a tick counts as stale.
* **The database.**  ``PRAGMA quick_check`` at every start (a failure is said on the console, in the log, in the
  status); every night at ``--backup-time`` (22:00) an online copy to ``--backup-dir`` (``data/backups``) as
  ``tto-YYYY-MM-DD.db``, the newest 30 kept - and a second copy of it in ``--backup-copy-dir`` (another drive:
  ``D:\\tto-yedek`` for the installed dashboard), with the same 30.  The second copy never fails the backup: when it
  cannot be written that is logged once and shown in the status, and only after two nights in a row it is the
  database's system alarm.  A dashboard that was not running at the backup time takes the copy it missed five
  minutes after it starts.  ``python -m tto yedekten-don <file>`` puts one back, from either folder (store.restore).
  Nothing is copied off the machine.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import logging
import logging.handlers
import os
import re
import shutil
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from .deskalarms import SYSTEM

log = logging.getLogger("tto.ops")

LOG_NAME = "tto.log"
LOG_BYTES = 5 * 1024 * 1024
LOG_KEEP = 5
_LOG_FILE: List[str] = []           # the file ``python -m tto`` writes its log to

#: the Bloomberg helper process reports at least once a second: this long without a word, its values are not fresh
HEARD_STALE = 10.0
#: a fault repeated within this many seconds is counted, not written again
REPEAT_QUIET = 60.0

#: the nightly backups: tto-YYYY-MM-DD.db, the newest so many kept (nothing else in the folder is touched)
BACKUP_KEEP = 30
BACKUP_NAME = re.compile(r"^tto-(\d{4}-\d{2}-\d{2})\.db$")
#: a dashboard that missed the night's backup (not running then) takes it once it has run this long
BACKUP_CATCH_UP = 300.0
#: a backup that failed is tried again after this long
BACKUP_RETRY = 1800.0

#: what the desk may tune (the administrators, on the alarms page)
DEFAULTS: Dict[str, Any] = {
    "market_open": "09:00",          # market hours on the desk's days (week days that are not its holidays)
    "market_close": "18:00",
    "tick_stale": 120,               # seconds without any tick in market hours: the prices on the screens are "stale"
    # the system alarms of the desk (deskalarms.py): each on / off, and when it fires
    # (none on the RET curve: it may change at any time of the day, there is no time by which it must be loaded)
    "feed_alarm": True, "feed_minutes": 3,       # the Bloomberg data has been stale this many minutes in market hours
    "tlref_alarm": True, "tlref_due": "14:00",   # today's TLREF fixing is not in by then (published after 12:45 by
                                                 # Borsa İstanbul's rules of 2019; the history fetches it every 15 min)
    "db_alarm": True,                            # the database's check at the start, or its nightly backup, failed
}
#: the bounds of the numbers among them
RANGES = {"tick_stale": (10, 3600), "feed_minutes": (1, 240)}
#: their names in the desk's log of changes
NAMES = {"market_open": "piyasa açılışı", "market_close": "piyasa kapanışı", "tick_stale": "bayat sayılma (sn)",
         "feed_alarm": "veri akışı alarmı", "feed_minutes": "veri akışı alarmı (dk)", "tlref_alarm": "TLREF alarmı",
         "tlref_due": "TLREF saati", "db_alarm": "veritabanı alarmı"}
#: the system alarms, in the order the page lists them
SYSTEM_KINDS = tuple(SYSTEM)
_HHMM = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


def changes(before: Dict[str, Any], after: Dict[str, Any]) -> str:
    """What changed in the settings, as the desk's log says it ("TLREF saati: 14:00 → 14:30")."""
    def text(v: Any) -> str:
        return ("açık" if v else "kapalı") if isinstance(v, bool) else str(v)
    return "; ".join("%s: %s → %s" % (NAMES.get(k, k), text(before.get(k)), text(v)) for k, v in after.items() if before.get(k) != v)


def setup_logging(folder: str) -> str:
    """The rotating log file of the dashboard (``folder``/tto.log); returns its path.  Called once by
    ``python -m tto`` - a second call with the same folder adds nothing."""
    folder = os.path.abspath(folder)
    path = os.path.join(folder, LOG_NAME)
    logger = logging.getLogger("tto")
    for h in logger.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler) and os.path.abspath(h.baseFilename) == path:
            return path
    os.makedirs(folder, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=LOG_BYTES, backupCount=LOG_KEEP, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(threadName)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    _LOG_FILE[:] = [path]
    return path


def log_file() -> Optional[str]:
    return _LOG_FILE[0] if _LOG_FILE else None


def hhmm(text: Any) -> Optional[_dt.time]:
    m = _HHMM.match(str(text or "").strip())
    return _dt.time(int(m.group(1)), int(m.group(2))) if m else None


def clock_text(epoch: Optional[float]) -> str:
    return _dt.datetime.fromtimestamp(epoch).strftime("%H:%M:%S") if epoch else ""


def backups(folder: str) -> List[Dict[str, Any]]:
    """The dated backups in ``folder``, newest first: name, day, path, size, when written."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        m = BACKUP_NAME.match(name)
        if not m:
            continue
        path = os.path.join(folder, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "day": m.group(1), "path": path, "bytes": st.st_size,
                    "at": _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    out.sort(key=lambda b: b["day"], reverse=True)
    return out


def open_failed(settings, exc: BaseException) -> str:
    """What to say when the database cannot even be opened (a damaged file): where the newest backup is."""
    last = backups(settings.backup_dir)
    return ("Veritabanı açılamadı (%s): %s. Dosya bozulmuş olabilir. %s" % (
        settings.db_path, exc, ("En son yedek: %s – dashboard kapalıyken 'python -m tto yedekten-don \"%s\"' ile ona dönülür "
                                "(şimdiki dosya yanında saklanır)." % (last[0]["path"], last[0]["path"])) if last
        else "Yedek klasöründe (%s) yedek yok." % settings.backup_dir))


def feed_state(mode: str, status: Dict[str, Any], now: float, market: bool, started: float,
               tick_stale: float = float(DEFAULTS["tick_stale"]), heard_stale: float = HEARD_STALE) -> Dict[str, Any]:
    """How fresh the market data is: ``state`` (``ok`` / ``stale`` / ``silent`` / ``down`` / ``replay``), ``as_of``
    (the time of the last tick, or of the helper's last word), ``age`` (seconds) and ``reason`` (for the badge).

    * ``silent``: the helper process has said nothing for ``heard_stale`` seconds - it reports every second, so it
      hangs (it is started again after a while, see bbg_process.SILENT_RESTART);
    * ``stale``: in market hours no tick from any subscription for ``tick_stale`` seconds (since the start, if none
      came at all): the session looks alive, the prices do not move;
    * ``down``: no connection (or a helper being started again)."""
    if mode != "live":
        return {"state": "replay", "as_of": "", "age": None, "reason": ""}
    tick = float(status.get("last_tick") or 0.0)
    heard = float(status.get("heard") or 0.0)
    as_of = tick or heard
    out: Dict[str, Any] = {"as_of": clock_text(as_of), "age": round(now - as_of, 1) if as_of else None}
    if status.get("connected") is False or status.get("worker") in ("restarting", "stopped"):
        out.update(state="down", reason=status.get("error") or "Bloomberg bağlantısı yok")
        return out
    if status.get("isolated") and heard and now - heard > heard_stale:
        out.update(state="silent", reason="Bloomberg yardımcı süreci %d sn'dir ses vermiyor – fiyatlar %s itibarıyla"
                   % (now - heard, out["as_of"] or "—"))
        return out
    since = tick or started
    if market and status.get("subscriptions") and now - since > tick_stale:
        out.update(state="stale", reason=("piyasa saatinde %d sn'dir hiçbir abonelikten tick gelmedi" % (now - since))
                   + (" – son tick %s" % out["as_of"] if tick else " (açılıştan beri hiç gelmedi)"))
        return out
    out.update(state="ok", reason="")
    return out


class Ops(object):
    """The operational side of one dashboard (see the module text)."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self._seen: Dict[tuple, List[float]] = {}           # fault -> [last written, repeats since]
        self.last_error: Optional[Dict[str, Any]] = None
        self.errors = 0
        self._market = (0.0, False)                         # (when worked out, in market hours then)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.db_check: Optional[Dict[str, Any]] = None      # the check of the database file at the start
        self.backup_error: Optional[Dict[str, Any]] = None  # the last backup that failed (until one succeeds)
        self._backup_tried = 0.0
        self._days: Dict[str, bool] = {}                    # day -> the desk's market trades on it
        self.sys_state: Dict[str, Dict[str, Any]] = {}      # the system alarms' conditions at the last look
        self._feed_bad: Optional[float] = None              # since when the data has been stale in market hours
        self._tlref_def: Optional[tuple] = None             # (day, the history's TLREF series)

    # ================================================================== what went wrong
    def failure(self, where: str, exc: BaseException) -> None:
        """A fault a background loop survives: written to the log (the first time with its traceback, then at
        most once a minute with how often it came back) and kept as the last error of the status."""
        text = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        now = time.time()
        key = (where, text)
        with self._lock:
            self.errors += 1
            self.last_error = {"where": where, "text": text, "at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               "count": self.errors}
            seen = self._seen.get(key)
            if seen is not None and now - seen[0] < REPEAT_QUIET:
                seen[1] += 1
                return
            repeats = seen[1] if seen else 0
            if len(self._seen) > 500:
                self._seen.clear()
            self._seen[key] = [now, 0]
        if seen is None:
            log.error("%s: %s\n%s", where, text, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
        else:
            log.error("%s: %s (son kayıttan beri %d kez daha)", where, text, repeats)

    # ================================================================== the desk's settings
    def settings(self) -> Dict[str, Any]:
        out = dict(DEFAULTS)
        saved = self.svc.store.get("ops.settings")
        if isinstance(saved, dict):
            out.update({k: v for k, v in saved.items() if k in DEFAULTS})
        return out

    def check_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """The settings with ``values`` applied (refused with ``ValueError`` when one does not read)."""
        cur = self.settings()
        for k, v in (values or {}).items():
            if k not in DEFAULTS:
                continue
            d = DEFAULTS[k]
            if isinstance(d, bool):
                cur[k] = bool(v)
            elif isinstance(d, int):
                try:
                    n = int(float(str(v).replace(",", ".")))
                except (TypeError, ValueError):
                    raise ValueError("sayı değil: %s = %r" % (k, v))
                lo, hi = RANGES.get(k, (1, 24 * 3600))
                if not lo <= n <= hi:
                    raise ValueError("%s %d – %d arasında olmalı (%r)" % (k, lo, hi, v))
                cur[k] = n
            else:
                t = hhmm(v)
                if t is None:
                    raise ValueError("saat SS:DD olmalı: %s = %r" % (k, v))
                cur[k] = t.strftime("%H:%M")
        if hhmm(cur["market_open"]) >= hhmm(cur["market_close"]):
            raise ValueError("piyasa açılışı kapanıştan önce olmalı")
        return cur

    def set_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        cur = self.check_settings(values)
        self.svc.store.put("ops.settings", cur)
        self._market = (0.0, False)
        return cur

    # ================================================================== market hours
    def market_day(self, day: Optional[str] = None) -> bool:
        """A day the desk's market trades (ISO; today when left out): a week day that is not one of its holidays."""
        day = day or self.svc.today_iso()
        try:
            if _dt.date.fromisoformat(day).weekday() >= 5:
                return False
        except ValueError:
            return False
        watch = getattr(self.svc, "watch", None)
        if watch is None:
            return True
        hit = self._days.get(day)
        if hit is not None:
            return hit
        try:                                  # the holidays are the workbook's: read on the calculation thread
            hit = bool(self.svc.et.submit(watch.market_open, day).result(timeout=20))
        except concurrent.futures.TimeoutError:
            return True                       # a busy engine: a week day it is (asked again next time)
        except Exception:  # noqa: BLE001
            return True
        if len(self._days) > 60:
            self._days.clear()
        self._days[day] = hit
        return hit

    def market_hours(self, now: Optional[_dt.datetime] = None) -> bool:
        """Whether the market is open now (worked out again every 20 seconds)."""
        if now is None:
            t, hit = self._market
            if time.time() - t < 20.0:
                return hit
        now = now or _dt.datetime.now()
        st = self.settings()
        hit = self.market_day(now.date().isoformat()) and hhmm(st["market_open"]) <= now.time() < hhmm(st["market_close"])
        self._market = (time.time(), hit)
        return hit

    def in_market(self) -> bool:
        """The last answer of :meth:`market_hours`, never blocking (asked by the Bloomberg provider's own thread)."""
        return self._market[1]

    # ================================================================== the data on the screens
    def feed(self, prov: Dict[str, Any]) -> Dict[str, Any]:
        st = self.settings()
        return feed_state(self.svc.mode, prov, time.time(), self.in_market(), self.svc.started_at,
                          tick_stale=float(st["tick_stale"]))

    def status(self, prov: Dict[str, Any]) -> Dict[str, Any]:
        et = self.svc.et
        return {"engine": {"queue": et.queued(), "busy": round(et.busy_for(), 1)}, "last_error": self.last_error,
                "feed": self.feed(prov), "market": self.in_market(), "log": log_file(), "settings": self.settings(),
                "db": self.db_status()}

    # ================================================================== the database: its check, its backups
    def check_database(self) -> Dict[str, Any]:
        """``PRAGMA quick_check`` of the database file (at the start): a failure is said loud - console, log, status."""
        t0 = time.time()
        found = self.svc.store.quick_check()
        self.db_check = {"ok": not found, "problems": found[:10], "at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         "seconds": round(time.time() - t0, 2)}
        if found:
            last = backups(self.svc.settings.backup_dir)
            text = "VERİTABANI DENETİMİ BAŞARISIZ (%s): %s. Kayıtlar eksik ya da okunamaz olabilir. %s" % (
                self.svc.settings.db_path, "; ".join(found[:3]),
                ("En son yedek: %s – dashboard kapalıyken 'python -m tto yedekten-don' ile ona dönülür." % last[0]["path"])
                if last else "Yedek yok.")
            log.error(text)
            try:
                print("UYARI: " + text, flush=True)          # the console of the desk machine
            except Exception:  # noqa: BLE001 - a console that cannot print
                pass
        else:
            log.info("veritabanı denetimi tamam (%.2f sn): %s", self.db_check["seconds"], self.svc.settings.db_path)
        return self.db_check

    def backup_now(self, day: Optional[_dt.date] = None) -> Dict[str, Any]:
        """An online copy of the database as ``tto-<day>.db`` (today's) in the backup folder (that day's earlier copy
        is replaced), then only the newest BACKUP_KEEP kept; then its second copy (:meth:`copy_backup`), which never
        fails the backup."""
        day = day or _dt.date.today()
        folder = self.svc.settings.backup_dir
        self._backup_tried = time.time()
        try:
            res = self.svc.store.backup_to(os.path.join(folder, "tto-%s.db" % day.isoformat()))
        except Exception as exc:  # noqa: BLE001 - said, kept for the status, tried again later
            self.backup_error = {"at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": "%s: %s" % (type(exc).__name__, exc)}
            log.error("veritabanı yedeği alınamadı (%s): %s", folder, self.backup_error["text"])
            raise
        self.backup_error = None
        removed = self._prune(folder)
        log.info("veritabanı yedeklendi: %s (%d bayt, %.1f sn)%s", res["path"], res["bytes"], res["seconds"],
                 (" – eski yedekler silindi: %s" % ", ".join(removed)) if removed else "")
        return dict(res, removed=removed, copy=self.copy_backup(res["path"], day))

    @staticmethod
    def _prune(folder: str) -> List[str]:
        """Only the newest BACKUP_KEEP dated backups of a folder stay (nothing else in it is touched)."""
        removed = []
        for old in backups(folder)[BACKUP_KEEP:]:
            try:
                os.remove(old["path"])
                removed.append(old["name"])
            except OSError as exc:
                log.warning("eski yedek silinemedi: %s (%s)", old["path"], exc)
        return removed

    def copy_state(self) -> Dict[str, Any]:
        """How the second copies went: the days of the failures in a row (none: the last one worked), the last
        error, the last copy that worked - kept in the store, so that two nights count across a restart."""
        v = self.svc.store.get("ops.backup_copy", {})
        return v if isinstance(v, dict) else {}

    def copy_backup(self, path: str, day: _dt.date) -> Optional[Dict[str, Any]]:
        """The night's backup copied to the second folder (``--backup-copy-dir``: another drive) under the same name,
        the newest BACKUP_KEEP kept there too.  It never fails the backup: a folder or drive that is missing or cannot be
        written is logged once (until a copy works again) and shown in the status; after two nights in a row it is the
        database's system alarm.  Returns what happened (``None``: no second folder set)."""
        folder = getattr(self.svc.settings, "backup_copy_dir", None)
        if not folder:
            return None
        folder = os.path.abspath(folder)
        state = self.copy_state()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dst = os.path.join(folder, os.path.basename(path))
        try:
            if os.path.normcase(folder) == os.path.normcase(os.path.abspath(self.svc.settings.backup_dir)):
                raise OSError("ikinci kopyanın klasörü yedek klasörünün kendisi")
            os.makedirs(folder, exist_ok=True)
            shutil.copyfile(path, dst + ".part")
            if os.path.getsize(dst + ".part") != os.path.getsize(path):
                raise OSError("kopya eksik yazıldı")
            os.replace(dst + ".part", dst)
            removed = self._prune(folder)
        except Exception as exc:  # noqa: BLE001 - the backup itself stands
            try:
                if os.path.exists(dst + ".part"):
                    os.remove(dst + ".part")
            except OSError:
                pass
            failed = [d for d in state.get("failed_days") or [] if d != day.isoformat()] + [day.isoformat()]
            error = {"at": now, "text": "%s: %s" % (type(exc).__name__, exc)}
            self.svc.store.put("ops.backup_copy", dict(state, failed_days=failed[-10:], error=error))
            if not state.get("failed_days"):            # said once, until a copy works again
                log.warning("yedeğin ikinci kopyası alınamadı (%s): %s – yedeğin kendisi alındı; düzelene kadar bu yeniden "
                            "yazılmayacak, durum penceresinde görünür", folder, error["text"])
            return {"dir": folder, "error": error, "failed_nights": len(failed)}
        if state.get("failed_days"):
            log.info("yedeğin ikinci kopyası yeniden alınıyor: %s", dst)
        self.svc.store.put("ops.backup_copy", {"failed_days": [], "error": None, "ok_at": now, "path": dst})
        return {"dir": folder, "path": dst, "removed": removed}

    def backup_due(self, now: Optional[_dt.datetime] = None) -> bool:
        """The night's backup is due when its time (``--backup-time``) has come and no copy was taken since; a dashboard
        that was not running then takes the copy it missed once it has run BACKUP_CATCH_UP seconds (a day without a
        copy is not left behind)."""
        now = now or _dt.datetime.now()
        if self.backup_error and time.time() - self._backup_tried < BACKUP_RETRY:
            return False
        tonight = _dt.datetime.combine(now.date(), hhmm(self.svc.settings.backup_time) or _dt.time(22, 0))
        found = backups(self.svc.settings.backup_dir)
        last = max((_dt.datetime.strptime(b["at"], "%Y-%m-%d %H:%M:%S") for b in found), default=None)
        if now >= tonight and (last is None or last < tonight):
            return True
        missed = last is None or now - last > _dt.timedelta(hours=26)
        return missed and time.time() - self.svc.started_at >= BACKUP_CATCH_UP

    def db_status(self) -> Dict[str, Any]:
        folder = self.svc.settings.backup_dir
        found = backups(folder)
        second = getattr(self.svc.settings, "backup_copy_dir", None)
        copy = None
        if second:
            state = self.copy_state()
            copies = backups(second)
            copy = {"dir": os.path.abspath(second), "count": len(copies), "last": copies[0] if copies else None,
                    "error": state.get("error") if state.get("failed_days") else None,
                    "failed_nights": len(state.get("failed_days") or [])}
        return {"check": self.db_check, "backup": {"dir": folder, "count": len(found), "last": found[0] if found else None,
                                                   "error": self.backup_error, "time": self.svc.settings.backup_time,
                                                   "keep": BACKUP_KEEP, "copy": copy}}

    # ================================================================== the desk's system alarms
    def tlref_fixing(self, today: str) -> tuple:
        """Whether today's TLREF fixing is in: the history's TLREF closes (Bloomberg's, fetched every 15 minutes in
        live mode) have today's point.  Returns ``(in, the last fixing as "day: value")``."""
        cached = self._tlref_def
        if cached is None or cached[0] != today:
            ref = next((d for d in self.svc.history.snapshot().get("defs") or [] if d.group == "ref"), None)
            self._tlref_def = cached = (today, ref)
        ref = cached[1]
        if ref is None:
            return False, "tarihçede TLREF serisi yok"
        start = (_dt.date.fromisoformat(today) - _dt.timedelta(days=12)).isoformat()
        points = ref.pick(self.svc.store.hist_many(ref.ids(), start))[1]
        if not points:
            return False, "son günlerin fixingi yok"
        last = max(points)
        shown = "%s: %s%%" % (".".join(reversed(last.split("-"))), ("%.2f" % points[last]).replace(".", ","))
        return last == today, shown

    def system_checks(self, now: Optional[_dt.datetime] = None) -> Dict[str, Dict[str, Any]]:
        """The system alarms' conditions now (every pass of the loop).  Each goes to the desk's alarms, which fire it
        when it starts to hold and close it when it ends; a page that is open is told (a new generation).  Only the
        database's check is looked at on the saved data: the rest needs the live market."""
        now = now or _dt.datetime.now()
        st = self.settings()
        live = self.svc.mode == "live"
        today = now.date().isoformat()
        stamp = now.strftime("%H:%M:%S")

        def state(kind: str, s: str, text: str = "", since: str = "") -> None:
            states[kind] = {"state": s, "text": text, "since": since, "checked": stamp}

        states: Dict[str, Dict[str, Any]] = {}
        day = self.market_day(today)
        market = self.market_hours(now) if live else False
        # -- the data feed: stale (A4's heartbeat and tick age) for so many minutes in market hours
        if not st["feed_alarm"]:
            state("feed", "off")
        elif not live:
            state("feed", "na", "kayıtlı veride denetlenmez")
        else:
            try:
                prov = self.svc.provider.status()
            except Exception:  # noqa: BLE001
                prov = {}
            feed = self.feed(prov)
            if feed["state"] in ("stale", "silent", "down") and market:
                self._feed_bad = self._feed_bad or time.time()
                since = clock_text(self._feed_bad)
                if time.time() - self._feed_bad >= 60.0 * st["feed_minutes"]:
                    state("feed", "alarm", "Bloomberg verisi akmıyor (%s itibarıyla): %s" % (since[:5], feed["reason"]), since[:5])
                else:
                    state("feed", "ok", "%s itibarıyla bayat – %d dk sürerse alarm" % (since, st["feed_minutes"]))
            else:
                self._feed_bad = None
                state("feed", "ok", "akıyor" if market else "piyasa saati dışında: tick beklenmez")
        # -- TLREF: today's fixing in by its time
        if not st["tlref_alarm"]:
            state("tlref", "off")
        elif not live:
            state("tlref", "na", "kayıtlı veride denetlenmez")
        elif not getattr(self.svc.settings, "history", True):
            state("tlref", "na", "tarihçe kapalı (--no-history): fixing görülemez")
        elif not day:
            state("tlref", "ok", "bugün piyasa kapalı")
        else:
            fixed, last = self.tlref_fixing(today)
            if fixed:
                state("tlref", "ok", "bugünün fixingi geldi (%s)" % last)
            elif now.time() < hhmm(st["tlref_due"]):
                state("tlref", "ok", "henüz gelmedi – son saat %s (son fixing %s)" % (st["tlref_due"], last))
            else:
                state("tlref", "alarm", "Bugünün TLREF fixingi %s itibarıyla gelmedi (son fixing %s)" % (st["tlref_due"], last),
                      st["tlref_due"])
        # -- the database: its check at the start, the nightly backup
        if not st["db_alarm"]:
            state("db", "off")
        else:
            bad = []
            if self.db_check and not self.db_check["ok"]:
                bad.append("açılış denetimi başarısız: %s" % "; ".join(self.db_check["problems"][:2]))
            if self.backup_error:
                bad.append("yedek alınamadı (%s): %s" % (self.backup_error["at"][:16], self.backup_error["text"]))
            copy = self.copy_state()
            if len(copy.get("failed_days") or []) >= 2:  # one night is said in the status only; two in a row: an alarm
                bad.append("yedeğin ikinci kopyası %d gecedir alınamadı (%s): %s" % (
                    len(copy["failed_days"]), getattr(self.svc.settings, "backup_copy_dir", "") or "", (copy.get("error") or {}).get("text", "")))
            last = backups(self.svc.settings.backup_dir)
            state("db", "alarm" if bad else "ok", " · ".join(bad) if bad else ("son yedek %s" % last[0]["at"][:16] if last else "henüz yedek yok"))
        self.sys_state = states
        desk = getattr(self.svc, "desk_alarms", None)
        if desk is not None:
            desk.retire()                             # an earlier version's alarm that is no longer checked
            told = [desk.system(kind, states[kind]["state"] == "alarm", states[kind]["text"]) for kind in SYSTEM_KINDS]
            if any(told):
                self.svc.bump()                       # the pages ask what fired / closed
        return states

    def system_rows(self) -> List[Dict[str, Any]]:
        """The system alarms as the alarms page shows them: their state at the last look and when they fire."""
        st = self.settings()
        when = {"feed": "piyasa saatinde %d dk akmazsa" % st["feed_minutes"], "tlref": "saat %s itibarıyla gelmemişse" % st["tlref_due"],
                "db": "açılış denetimi ya da gece yedeği (%s) başarısızsa; ikinci kopyası 2 gece üst üste alınamazsa"
                      % self.svc.settings.backup_time}
        rows = []
        for kind in SYSTEM_KINDS:
            s = self.sys_state.get(kind) or {"state": "na", "text": "henüz denetlenmedi", "since": "", "checked": ""}
            rows.append(dict(s, kind=kind, label=SYSTEM[kind], threshold=when[kind], on=bool(st["%s_alarm" % kind])))
        return rows

    # ================================================================== the loop
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tto-ops", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=5.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = _dt.datetime.now()
            try:
                self.market_hours(now)
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                self.failure("operasyon döngüsü", exc)
            try:
                if self.backup_due(now):
                    self.backup_now()
            except Exception:  # noqa: BLE001 - said in backup_now; tried again after BACKUP_RETRY
                pass
            try:
                self.system_checks(now)
            except Exception as exc:  # noqa: BLE001
                self.failure("sistem alarmları", exc)
            self._stop.wait(15.0)
