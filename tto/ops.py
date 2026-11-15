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
  ``tto-YYYY-MM-DD.db``, the newest 30 kept.  A dashboard that was not running at that time takes the copy it
  missed five minutes after it starts.  ``python -m tto yedekten-don <file>`` puts one back (see store.restore).
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import logging
import logging.handlers
import os
import re
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

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
}
_HHMM = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")


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
                if not 1 <= n <= 24 * 3600:
                    raise ValueError("aralık dışında: %s = %r" % (k, v))
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
        try:                                  # the holidays are the workbook's: read on the calculation thread
            return bool(self.svc.et.submit(watch.market_open, day).result(timeout=20))
        except concurrent.futures.TimeoutError:
            return True                       # a busy engine: a week day it is
        except Exception:  # noqa: BLE001
            return True

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

    def backup_now(self) -> Dict[str, Any]:
        """An online copy of the database as ``tto-<today>.db`` in the backup folder (today's earlier copy is
        replaced), then only the newest BACKUP_KEEP kept."""
        folder = self.svc.settings.backup_dir
        self._backup_tried = time.time()
        try:
            res = self.svc.store.backup_to(os.path.join(folder, "tto-%s.db" % _dt.date.today().isoformat()))
        except Exception as exc:  # noqa: BLE001 - said, kept for the status, tried again later
            self.backup_error = {"at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": "%s: %s" % (type(exc).__name__, exc)}
            log.error("veritabanı yedeği alınamadı (%s): %s", folder, self.backup_error["text"])
            raise
        self.backup_error = None
        removed = []
        for old in backups(folder)[BACKUP_KEEP:]:
            try:
                os.remove(old["path"])
                removed.append(old["name"])
            except OSError as exc:
                log.warning("eski yedek silinemedi: %s (%s)", old["path"], exc)
        log.info("veritabanı yedeklendi: %s (%d bayt, %.1f sn)%s", res["path"], res["bytes"], res["seconds"],
                 (" – eski yedekler silindi: %s" % ", ".join(removed)) if removed else "")
        return dict(res, removed=removed)

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
        return {"check": self.db_check, "backup": {"dir": folder, "count": len(found), "last": found[0] if found else None,
                                                   "error": self.backup_error, "time": self.svc.settings.backup_time,
                                                   "keep": BACKUP_KEEP}}

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
            self._stop.wait(15.0)
