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
  page): the market hours, how long without a tick counts as stale, and Bloomberg's hours (``bbg_open`` /
  ``bbg_close``: when it may be asked again - the provider's quiet hours, ``marketdata/bloomberg.py``).
* **The data folder** (datadir.py): on a network drive the database runs without its write-ahead log - said loud at
  the start (console, log) and in the status, red; the status also shows the lock of one dashboard per data folder.
* **The database.**  ``PRAGMA quick_check`` at every start (a failure is said on the console, in the log, in the
  status); every day at ``--backup-time`` (17:30) an online copy to ``--backup-dir`` (``data/backups``) as
  ``tto-YYYY-MM-DD.db``, the newest 30 kept - and a second copy of it in ``--backup-copy-dir`` (another drive:
  ``D:\\tto-yedek`` for the installed dashboard, when the machine has a D: drive), with the same 30.  The second copy
  never fails the backup: when it cannot be written that is logged once and shown in the status, and only after two
  days in a row it is the database's system alarm.  A dashboard that was not running at the backup time takes the
  copy it missed five minutes after it starts.  ``python -m tto yedekten-don <file>`` puts one back, from any of the
  folders (store.restore).
* **The administrators choose** the time and both folders in the dashboard (Araçlar → Yedekleme; ``ops.backup`` in
  the store): their choice comes before the command line / environment, which come before the defaults, and applies
  at the next look of the loop - no restart.  A folder must be a full path (a drive, a mapped drive or a share of the
  office network); it is made when missing and written to once before it is taken.  A folder that a cloud service
  synchronises (OneDrive, Dropbox, Google Drive, iCloud Drive, Box) is refused: the database holds Bloomberg data and
  password hashes, and by the desk's rule these never go to an outside service.  Changing a folder moves nothing: the
  old backups stay where they are, each folder keeps its own newest 30.
* **A chosen folder that cannot be written** at the backup time (a share that is down, a drive that is gone) does not
  leave the day without a backup: it goes to the dashboard's own folder (``data/backups``) - the day counts as backed
  up, its second copy is still made from it - and the database's alarm rings.  The chosen folder is tried again every
  30 minutes; the file is copied there once it can be written, and the alarm ends.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import json
import logging
import logging.handlers
import os
import re
import shutil
import sqlite3
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from . import config as _config
from .datadir import NETWORK_WARNING
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
#: the administrators' choice of the backup (``ops.backup`` in the store), key by key; their names in the log
BACKUP_KEYS = ("time", "dir", "copy_dir")
BACKUP_NAMES = {"time": "yedek saati", "dir": "yedek klasörü", "copy_dir": "ikinci kopya klasörü"}
#: the newest backups of each folder the administrators' page lists
BACKUP_SHOWN = 10
#: the days whose backup went to the dashboard's own folder because the chosen one could not be written: so many kept
FALLBACK_KEEP = 30
#: the status lists the backup folders at most this often (seconds): every open page asks for the status, and a share
#: of the network that does not answer must hold one request at a time, not all of them
LIST_FRESH = 60.0
#: the file a folder is tried with before it is taken (written and deleted at once)
PROBE_NAME = ".tto-yazma-sinamasi.tmp"
#: where OneDrive says its folders are (the personal one, the company's)
CLOUD_ENV = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")

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
    # the Trades page's close (tradebook.py): every open trade's value kept each business day at this time - a day
    # missed while the dashboard was off at its next start (the daily backup's time by default)
    "trades_close": "17:30",
    # when Bloomberg may be asked again on the desk's days (cache first, docs/market-data.md): outside these hours, at
    # weekends and on TR holidays no refresh and no poll at all - subscriptions keep streaming (the desk, 24.11.2026)
    "bbg_open": "08:00",
    "bbg_close": "19:00",
}
#: the bounds of the numbers among them
RANGES = {"tick_stale": (10, 3600), "feed_minutes": (1, 240)}
#: their names in the desk's log of changes
NAMES = {"market_open": "piyasa açılışı", "market_close": "piyasa kapanışı", "tick_stale": "bayat sayılma (sn)",
         "feed_alarm": "veri akışı alarmı", "feed_minutes": "veri akışı alarmı (dk)", "tlref_alarm": "TLREF alarmı",
         "tlref_due": "TLREF saati", "db_alarm": "veritabanı alarmı", "trades_close": "Trades kapanış saati",
         "bbg_open": "Bloomberg sorgu başlangıcı", "bbg_close": "Bloomberg sorgu bitişi"}
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


class BackupError(ValueError):
    """The administrators' choice of the backup cannot be taken: ``errors`` says why, field by field (in Turkish)."""

    def __init__(self, errors: Dict[str, str]):
        ValueError.__init__(self, next(iter(errors.values())))
        self.errors = errors


def is_full_path(path: str) -> bool:
    """A full path: on Windows with its drive or its share (``E:\\yedek``, ``\\\\sunucu\\paylasim\\yedek``) - not
    ``\\yedek`` (the root of whatever drive is current) nor ``E:yedek`` (that drive's current folder)."""
    if os.name != "nt":
        return os.path.isabs(path)
    drive, rest = os.path.splitdrive(path)
    return bool(drive) and (drive[:2] in ("\\\\", "//") or rest[:1] in ("\\", "/"))


def _cloud_name(part: str) -> Optional[str]:
    """The cloud service whose synchronised folder carries this name (as these services name their folders)."""
    n = part.strip().lower().replace("\u2019", "'")
    if n == "onedrive" or n.startswith(("onedrive -", "onedrive-")):
        return "OneDrive"
    if n == "dropbox" or n.startswith("dropbox ("):
        return "Dropbox"
    if n in ("google drive", "googledrive", "my drive", "drive'ım", "shared drives", "ortak drive'lar") or n.startswith("googledrive-"):
        return "Google Drive"
    if n in ("iclouddrive", "icloud drive", "com~apple~clouddocs"):
        return "iCloud Drive"
    if n in ("box", "box sync"):
        return "Box"
    return None


def cloud_service(path: str) -> Optional[str]:
    """The cloud service that synchronises ``path`` (OneDrive, Dropbox, Google Drive, iCloud Drive, Box) - by
    OneDrive's own variables and by the names these services give their folders, on the path as written and as it
    resolves (a link into such a folder); ``None``: none."""
    seen = [path]
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        real = path
    if real != path:
        seen.append(real)
    roots = [os.path.normcase(os.path.abspath(os.environ[v].strip())) for v in CLOUD_ENV if (os.environ.get(v) or "").strip()]
    for p in seen:
        n = os.path.normcase(os.path.abspath(p))
        if any(n == r or n.startswith(r.rstrip("\\/") + os.sep) for r in roots):
            return "OneDrive"
        for part in re.split(r"[\\/]+", p):
            hit = _cloud_name(part)
            if hit:
                return hit
    return None


def _why(exc: OSError) -> str:
    """Why a folder could not be made or written, in a few words (the system's own text otherwise)."""
    if isinstance(exc, PermissionError):
        return "erişim izni yok"
    if isinstance(exc, FileExistsError):
        return "aynı adda bir dosya var"
    return str(exc.strerror or exc)


def check_folder(text: Any) -> str:
    """A folder for the backups as an administrator typed it: a full path (a drive, a mapped drive, a share of the
    office network) outside every cloud-synced folder; made when missing, then written to once (a small file made and
    deleted).  Returns the folder as the backups will use it; ``ValueError`` with the reason (in Turkish) when it
    cannot be taken."""
    path = str(text or "").strip().strip('"').strip()
    if not path:
        raise ValueError("Klasörü yazın.")
    if not is_full_path(path):
        raise ValueError("Tam yol yazın – sürücüsüyle (ör. E:\\tto-yedek) ya da ağ paylaşımıyla (\\\\sunucu\\paylaşım\\tto-yedek); "
                         "\"%s\" göreli bir yol." % path)
    path = os.path.normpath(path)
    cloud = cloud_service(path)
    if cloud:
        raise ValueError("Bu klasörü %s eşitliyor: veritabanında Bloomberg verisi ve şifre özetleri var, masanın kuralı gereği "
                         "bunlar hiçbir dış hizmete gitmez. Bu bilgisayarın kendi diskinde ya da ofis ağındaki bir paylaşımda "
                         "bir klasör seçin." % cloud)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise ValueError("Klasör açılamadı: %s" % _why(exc))
    probe = os.path.join(path, PROBE_NAME)
    try:
        with open(probe, "wb") as fh:
            fh.write(b"tto")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        raise ValueError("Klasöre yazılamıyor: %s" % _why(exc))
    try:
        os.remove(probe)
    except OSError as exc:
        raise ValueError("Klasörde dosya silinemiyor (eski yedekler silinemez, günün yedeği yenilenemez): %s" % _why(exc))
    return path


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _when(stamp: Any) -> Optional[_dt.datetime]:
    """"YYYY-MM-DD HH:MM:SS" as a time (``None`` when it is not one)."""
    try:
        return _dt.datetime.strptime(str(stamp), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _written_since(path: str, stamp: Any) -> bool:
    """Whether ``path`` is a file written at ``stamp`` ("YYYY-MM-DD HH:MM:SS") or later."""
    since = _when(stamp)
    try:
        return since is not None and os.path.isfile(path) and _dt.datetime.fromtimestamp(os.path.getmtime(path)) >= since
    except OSError:
        return False


def same_folder(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two folders are one (``None`` / empty: no folder)."""
    if a and b:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    return not a and not b


def hide_paths(text: str, paths: List[str]) -> str:
    """``text`` without the given paths - as written and as an error message quotes them (backslashes doubled)."""
    for p in paths:
        if "\\" in p:
            text = text.replace(p.replace("\\", "\\\\"), "…")
        text = text.replace(p, "…")
    return text


def saved_folders(db_path: str) -> Dict[str, str]:
    """The backup folders the administrators chose in the dashboard (``dir``, ``copy_dir``), only read from the
    database: ``yedekten-don`` runs while the dashboard is stopped.  Empty when there is none or it cannot be read."""
    if not os.path.isfile(db_path):
        return {}
    try:
        con = sqlite3.connect(db_path)
        try:
            row = con.execute("SELECT value FROM kv WHERE key='ops.backup'").fetchone()
        finally:
            con.close()
        saved = json.loads(row[0]) if row else {}
    except Exception:  # noqa: BLE001 - a damaged database: the folders of the command line only
        return {}
    return {k: str(saved[k]) for k in ("dir", "copy_dir") if isinstance(saved, dict) and saved.get(k)}


def open_failed(settings, exc: BaseException) -> str:
    """What to say when the database cannot even be opened (a damaged file): where the newest backup is."""
    last = backups(settings.backup_dir)
    return ("Veritabanı açılamadı (%s): %s. Dosya bozulmuş olabilir. %s" % (
        settings.db_path, exc, ("En son yedek: %s – dashboard kapalıyken 'python -m tto yedekten-don \"%s\"' ile ona dönülür "
                                "(şimdiki dosya yanında saklanır; ondan okunabilenler sonra 'python -m tto kurtar' ile "
                                "eklenir)." % (last[0]["path"], last[0]["path"])) if last
        else "Yedek klasöründe (%s) yedek yok – yöneticiler dashboard'da başka bir klasör seçtiyse yedekler oradadır."
        % settings.backup_dir))


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
        self.folder: Optional[Dict[str, Any]] = None        # where the data folder is (check_folder, at the start)
        self.backup_error: Optional[Dict[str, Any]] = None  # the last backup that failed (until one succeeds)
        self._backup_tried = 0.0
        self._fallback_tried = 0.0                          # when the chosen folder was last tried for the days that wait
        self._backup_lock = threading.RLock()               # one backup at a time (the loop's, "Şimdi yedek al", catching up)
        self._choice_lock = threading.Lock()                # one change of the administrators' choice at a time
        self._lists: Dict[str, tuple] = {}                  # folder -> (when listed, its backups, being listed)
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
        if hhmm(cur["bbg_open"]) >= hhmm(cur["bbg_close"]):
            raise ValueError("Bloomberg sorgu başlangıcı bitişten önce olmalı")
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
            last = backups(self.backup_conf()["dir"])
            text = "VERİTABANI DENETİMİ BAŞARISIZ (%s): %s. Kayıtlar eksik ya da okunamaz olabilir. %s" % (
                self.svc.settings.db_path, "; ".join(found[:3]),
                ("En son yedek: %s – dashboard kapalıyken 'python -m tto yedekten-don' ile ona dönülür, sonra 'python -m tto "
                 "kurtar' bozuk dosyadan okunabilenleri ekler (README: \"Veritabanı bozulursa\")." % last[0]["path"])
                if last else "Yedek yok.")
            log.error(text)
            try:
                print("UYARI: " + text, flush=True)          # the console of the desk machine
            except Exception:  # noqa: BLE001 - a console that cannot print
                pass
        else:
            log.info("veritabanı denetimi tamam (%.2f sn): %s", self.db_check["seconds"], self.svc.settings.db_path)
        return self.db_check

    def check_folder(self) -> Dict[str, Any]:
        """Where the data folder is (at the start): on a network drive the database runs without its write-ahead log
        (store.py, datadir.py) - said loud on the console and in the log; the status shows it red."""
        store = self.svc.store
        self.folder = {"network": bool(getattr(store, "network", False)), "journal": getattr(store, "journal_mode", None)}
        if self.folder["network"]:
            text = ("%s (%s). Bu açılışta veritabanı WAL yerine DELETE günlük kipinde çalışıyor: WAL ağ sürücüsünde çalışmaz."
                    % (NETWORK_WARNING, self.svc.settings.data_dir))
            log.warning(text)
            try:
                print("!" * 100 + "\nUYARI: " + text + "\n" + "!" * 100, flush=True)     # the console of the desk machine
            except Exception:  # noqa: BLE001 - a console that cannot print
                pass
        return self.folder

    def folder_status(self) -> Dict[str, Any]:
        """The data folder as the status shows it: on a network drive (the warning) or not, the journal mode, and the
        lock of one dashboard per data folder (held by the dashboard's own process: ``settings.data_lock``)."""
        out = dict(self.folder or {})
        out["warning"] = NETWORK_WARNING if out.get("network") else None
        lock = getattr(self.svc.settings, "data_lock", None)
        out["lock"] = lock.info() if lock is not None else None
        return out

    def backup_now(self, day: Optional[_dt.date] = None, by: Optional[str] = None) -> Dict[str, Any]:
        """An online copy of the database as ``tto-<day>.db`` (today's) in the backup folder (that day's earlier copy
        is replaced), then only the newest BACKUP_KEEP kept; then its second copy (:meth:`copy_backup`), which never
        fails the backup.  The folders as they stand now (:meth:`backup_conf`); one backup at a time - the loop's and
        an administrator's "Şimdi yedek al" (``by``: who asked).

        A chosen folder that cannot be written (a share that is down, a drive that is gone) does not leave the day
        without a backup: it goes to the dashboard's own folder (data/backups) - ``fallback`` says so -, the day counts
        as backed up, the database's alarm rings until the file reaches the chosen folder (:meth:`catch_up`)."""
        with self._backup_lock:
            conf = self.backup_conf()
            day = day or _dt.date.today()
            folder, own = conf["dir"], self.own_backup_dir()
            name = "tto-%s.db" % day.isoformat()
            self._backup_tried = time.time()
            fallback = None
            try:
                try:
                    res = self.svc.store.backup_to(os.path.join(folder, name))
                except Exception as exc:  # noqa: BLE001 - said, kept for the status, tried again later
                    first = "%s: %s" % (type(exc).__name__, exc)
                    if same_folder(folder, own):                 # (the dashboard's own folder itself: nowhere else to go)
                        self._backup_failed(folder, first)
                        raise
                    log.error("seçilen yedek klasörüne yazılamadı (%s): %s – yedek dashboard'un kendi klasörüne alınıyor: %s",
                              folder, first, own)
                    try:
                        res = self.svc.store.backup_to(os.path.join(own, name))
                    except Exception as exc2:  # noqa: BLE001
                        self._backup_failed(own, "seçilen klasör: %s · dashboard'un kendi klasörü: %s: %s" % (first, type(exc2).__name__, exc2))
                        raise
                    fallback = {"dir": folder, "error": {"at": _stamp(), "text": first}}
                self.backup_error = None
                removed = self._prune(own if fallback else folder)
                log.info("veritabanı yedeklendi%s: %s (%d bayt, %.1f sn)%s", " (elle, %s)" % by if by else "", res["path"],
                         res["bytes"], res["seconds"], (" – eski yedekler silindi: %s" % ", ".join(removed)) if removed else "")
                if fallback:
                    self._fell_back(day, res["path"], folder, fallback["error"])
                else:
                    self._reached(day, conf)
                return dict(res, removed=removed, fallback=fallback, copy=self.copy_backup(res["path"], day, conf))
            finally:
                with self._lock:
                    self._lists.clear()                      # the status lists the folders again

    def _backup_failed(self, folder: str, text: str) -> None:
        self.backup_error = {"at": _stamp(), "text": text}
        log.error("veritabanı yedeği alınamadı (%s): %s", folder, text)

    # ------------------------------------------------------------------ the dashboard's own folder, when the chosen one fails
    def own_backup_dir(self) -> str:
        """The dashboard's own backup folder (``data/backups``): where a day's backup goes when the chosen folder cannot
        be written."""
        return os.path.join(self.svc.settings.data_dir, "backups")

    def fallback_state(self) -> Dict[str, Any]:
        """The days whose backup went to the dashboard's own folder (``ops.backup_fallback``): day -> the file, the chosen
        folder it is for, when, why, when it reached that folder (``None``: it waits); the last failure to write there."""
        try:
            v = self.svc.store.get("ops.backup_fallback", {})
        except Exception:  # noqa: BLE001 - a database that cannot be read: nothing waits
            v = {}
        v = v if isinstance(v, dict) else {}
        v["days"] = v.get("days") if isinstance(v.get("days"), dict) else {}
        return v

    def fallback_pending(self, conf: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """The days whose backup still waits to reach the chosen folder (the one chosen now)."""
        conf = conf or self.backup_conf()
        return {d: r for d, r in self.fallback_state()["days"].items()
                if isinstance(r, dict) and not r.get("reached_at") and not r.get("gone") and same_folder(r.get("dir"), conf["dir"])}

    def fallback_view(self, conf: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """What the administrators' page and the status say of it: the latest day that went to the dashboard's own folder
        (while one waits, or when it is today's), whether it has reached the chosen folder since, the days that wait."""
        conf = conf or self.backup_conf()
        state = self.fallback_state()
        mine = {d: r for d, r in state["days"].items() if isinstance(r, dict) and same_folder(r.get("dir"), conf["dir"])}
        waiting = sorted(d for d, r in mine.items() if not r.get("reached_at") and not r.get("gone"))
        today = _dt.date.today().isoformat()
        if not mine or (not waiting and max(mine) != today):
            return None
        day = max(mine)
        rec = mine[day]
        return {"day": day, "today": day == today, "at": rec.get("at"), "path": rec.get("path"), "dir": self.own_backup_dir(),
                "reached_at": rec.get("reached_at"), "waiting": waiting, "error": state.get("error") if waiting else None}

    def _fell_back(self, day: _dt.date, path: str, folder: str, error: Dict[str, Any]) -> None:
        state = self.fallback_state()
        state["days"][day.isoformat()] = {"path": path, "dir": folder, "at": _stamp(), "error": error["text"], "reached_at": None}
        state["error"] = error
        for old in sorted(state["days"])[:-FALLBACK_KEEP]:
            del state["days"][old]
        self.svc.store.put("ops.backup_fallback", state)
        self._fallback_tried = time.time()                   # (the chosen folder is tried again after BACKUP_RETRY)

    def _reached(self, day: _dt.date, conf: Dict[str, Any]) -> None:
        """A backup of ``day`` written to the chosen folder itself: that day waits no more; the days still waiting are
        copied there now (the folder answers)."""
        state = self.fallback_state()
        rec = state["days"].get(day.isoformat())
        if isinstance(rec, dict) and not rec.get("reached_at") and same_folder(rec.get("dir"), conf["dir"]):
            rec["reached_at"] = _stamp()
            if not any(not r.get("reached_at") and not r.get("gone") for r in state["days"].values() if isinstance(r, dict)):
                state["error"] = None
            self.svc.store.put("ops.backup_fallback", state)
        if self.fallback_pending(conf):
            self.catch_up(force=True)

    def catch_up(self, force: bool = False) -> List[str]:
        """The days whose backup went to the dashboard's own folder, copied to the chosen folder once it can be written
        again - tried every BACKUP_RETRY seconds (``force``: now), oldest first.  A day the chosen folder has meanwhile (a
        later backup of that day) needs nothing; the alarm ends with the last day that waited.  Returns the days that
        arrived."""
        with self._backup_lock:
            conf = self.backup_conf()
            pending = self.fallback_pending(conf)
            if not pending or (not force and time.time() - self._fallback_tried < BACKUP_RETRY):
                return []
            self._fallback_tried = time.time()
            state = self.fallback_state()
            folder = os.path.abspath(conf["dir"])
            arrived: List[str] = []
            for day in sorted(pending):
                rec = state["days"][day]
                src = str(rec.get("path") or "")
                dst = os.path.join(folder, os.path.basename(src))
                if not _written_since(dst, rec.get("at")):        # (a later backup of that day is there already)
                    if not os.path.isfile(src):
                        rec["gone"] = _stamp()
                        log.warning("seçilen klasöre kopyalanacak yedek dashboard'un kendi klasöründe artık yok: %s", src)
                        continue
                    try:
                        os.makedirs(folder, exist_ok=True)
                        shutil.copyfile(src, dst + ".part")
                        if os.path.getsize(dst + ".part") != os.path.getsize(src):
                            raise OSError("kopya eksik yazıldı")
                        os.replace(dst + ".part", dst)
                    except Exception as exc:  # noqa: BLE001 - the folder still does not answer: tried again later
                        try:
                            if os.path.exists(dst + ".part"):
                                os.remove(dst + ".part")
                        except OSError:
                            pass
                        error = {"at": _stamp(), "text": "%s: %s" % (type(exc).__name__, exc)}
                        if (state.get("error") or {}).get("text") != error["text"]:
                            log.warning("seçilen yedek klasörü hâlâ yazılamıyor (%s): %s – yarım saat sonra yeniden denenecek",
                                        folder, error["text"])
                        state["error"] = error
                        break
                rec["reached_at"] = _stamp()
                arrived.append(day)
            if arrived:
                removed = self._prune(folder)
                log.info("dashboard'un kendi klasörüne alınan yedek seçilen klasöre ulaştı (%s): %s%s", folder, ", ".join(arrived),
                         (" – eski yedekler silindi: %s" % ", ".join(removed)) if removed else "")
            if not any(not r.get("reached_at") and not r.get("gone") for r in state["days"].values() if isinstance(r, dict)):
                state["error"] = None
            self.svc.store.put("ops.backup_fallback", state)
            with self._lock:
                self._lists.clear()
            return arrived

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
        error, the last copy that worked - kept in the store, so that two days count across a restart."""
        v = self.svc.store.get("ops.backup_copy", {})
        return v if isinstance(v, dict) else {}

    def copy_backup(self, path: str, day: _dt.date, conf: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """The day's backup copied to the second folder (another drive, a share of the network) under the same name,
        the newest BACKUP_KEEP kept there too.  It never fails the backup: a folder or drive that is missing or cannot be
        written is logged once (until a copy works again) and shown in the status; after two days in a row it is the
        database's system alarm.  Returns what happened (``None``: no second folder set)."""
        conf = conf or self.backup_conf()
        folder = conf.get("copy_dir")
        if not folder:
            return None
        folder = os.path.abspath(folder)
        state = self.copy_state()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dst = os.path.join(folder, os.path.basename(path))
        try:
            if same_folder(folder, conf["dir"]):
                raise OSError("ikinci kopyanın klasörü yedek klasörünün kendisi")
            if same_folder(folder, os.path.dirname(os.path.abspath(path))):
                removed = []                     # (the backup itself went there: the dashboard's own folder, the chosen one failing)
            else:
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
        """The day's backup is due when its time has come and no copy was taken since; a dashboard that was not running
        then takes the copy it missed once it has run BACKUP_CATCH_UP seconds (a day without a copy is not left behind -
        nor a folder just chosen without one).  The time and the folder as they stand now (:meth:`backup_conf`)."""
        now = now or _dt.datetime.now()
        if self.backup_error and time.time() - self._backup_tried < BACKUP_RETRY:
            return False
        conf = self.backup_conf()
        due = _dt.datetime.combine(now.date(), hhmm(conf["time"]) or hhmm(_config.DEFAULT_BACKUP_TIME))
        taken = [_when(b["at"]) for b in backups(conf["dir"])]
        # a day whose backup went to the dashboard's own folder (the chosen one could not be written) is backed up too
        taken += [_when(r.get("at")) for r in self.fallback_state()["days"].values()
                  if isinstance(r, dict) and same_folder(r.get("dir"), conf["dir"])]
        last = max((t for t in taken if t), default=None)
        if now >= due and (last is None or last < due):
            return True
        missed = last is None or now - last > _dt.timedelta(hours=26)
        return missed and time.time() - self.svc.started_at >= BACKUP_CATCH_UP

    def _listed(self, folder: str) -> List[Dict[str, Any]]:
        """The backups of a folder as the status shows them: listed at most every LIST_FRESH seconds and by one
        request at a time (the others take the last list meanwhile) - a share of the network that does not answer
        holds one request, not every open page's."""
        now = time.time()
        with self._lock:
            hit = self._lists.get(folder)
            if hit is not None and (hit[2] or now - hit[0] < LIST_FRESH):
                return hit[1]
            if len(self._lists) > 20:
                self._lists.clear()
            found = hit[1] if hit else []
            self._lists[folder] = (hit[0] if hit else 0.0, found, True)
        try:
            found = backups(folder)
        finally:
            with self._lock:
                self._lists[folder] = (time.time(), found, False)
        return found

    def db_status(self) -> Dict[str, Any]:
        conf = self.backup_conf()
        found = self._listed(conf["dir"])
        second = conf["copy_dir"]
        copy = None
        if second:
            state = self.copy_state()
            copies = self._listed(second)
            copy = {"dir": os.path.abspath(second), "count": len(copies), "last": copies[0] if copies else None,
                    "error": state.get("error") if state.get("failed_days") else None,
                    "failed_nights": len(state.get("failed_days") or [])}
        return {"check": self.db_check, "folder": self.folder_status(),
                "backup": {"dir": conf["dir"], "count": len(found), "last": found[0] if found else None,
                           "error": self.backup_error, "time": conf["time"],
                           "keep": BACKUP_KEEP, "copy": copy, "fallback": self.fallback_view(conf)}}

    # ================================================================== the backup: the administrators' choice
    def saved_backup(self) -> Dict[str, Any]:
        """The administrators' choice (``ops.backup``): the keys they set, who saved it and when.  A database that
        cannot be read leaves the command line / defaults."""
        try:
            v = self.svc.store.get("ops.backup")
        except Exception:  # noqa: BLE001 - a damaged file: what the command line says
            return {}
        return v if isinstance(v, dict) else {}

    def backup_conf(self) -> Dict[str, Any]:
        """The daily backup as it stands now: ``time``, ``dir``, ``copy_dir`` (``None``: no second copy), the
        ``source`` of each (``saved``: the administrators' choice in the dashboard, ``cli``: the command line or the
        environment, ``default``) and ``base`` (what applies without the choice).  Read at every look: a choice
        applies without a restart."""
        st = self.svc.settings
        base = {"time": st.backup_time, "dir": st.backup_dir, "copy_dir": getattr(st, "backup_copy_dir", None)}
        origin = getattr(st, "backup_from", None) or {}
        saved = self.saved_backup()
        out: Dict[str, Any] = {"source": {}, "base": base}
        for k in BACKUP_KEYS:
            v = saved.get(k)
            if k in saved and (v or k == "copy_dir"):
                out[k], out["source"][k] = v or None, "saved"
            else:
                out[k], out["source"][k] = base[k], origin.get(k, "default")
        return out

    def check_backup(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """The administrators' choice with ``values`` applied - any of ``time``, ``dir`` and ``copy_dir`` (empty: no
        second copy); what it does not name stays as it was.  Each folder is checked (:func:`check_folder`: made when
        missing, written to once).  ``BackupError`` says, field by field, what cannot be taken."""
        values = values if isinstance(values, dict) else {}
        saved = {k: v for k, v in self.saved_backup().items() if k in BACKUP_KEYS}
        errors: Dict[str, str] = {}
        for k in BACKUP_KEYS:
            if k not in values:
                continue
            v = values[k]
            try:
                if k == "time":
                    try:
                        saved[k] = _config.check_time(v)
                    except ValueError:
                        raise ValueError("Saati SS:DD olarak yazın (ör. 17:30).")
                elif k == "copy_dir" and not str(v or "").strip().strip('"').strip():
                    saved[k] = ""                            # no second copy
                else:
                    saved[k] = check_folder(v)
            except ValueError as exc:
                errors[k] = str(exc)
        if not errors:
            base = self.backup_conf()["base"]
            main, second = saved.get("dir") or base["dir"], saved["copy_dir"] if "copy_dir" in saved else base["copy_dir"]
            if second and same_folder(main, second):
                errors["copy_dir" if "copy_dir" in values else "dir"] = (
                    "İkinci kopya yedek klasörünün kendisi olamaz: başka bir sürücüde ya da ağ paylaşımında bir klasör seçin.")
        if errors:
            raise BackupError(errors)
        return saved

    def set_backup(self, values: Dict[str, Any], by: Optional[str] = None) -> Dict[str, Any]:
        """Save the administrators' choice (:meth:`check_backup`); it applies at the loop's next look."""
        with self._choice_lock:
            before = self.backup_conf()
            saved = self.check_backup(values)
            self.svc.store.put("ops.backup", dict(saved, by=by, at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            return self._backup_changed(before, by)

    def reset_backup(self, by: Optional[str] = None) -> Dict[str, Any]:
        """Forget the administrators' choice: the command line / environment and the defaults again."""
        with self._choice_lock:
            before = self.backup_conf()
            self.svc.store.put("ops.backup", {})
            return self._backup_changed(before, by)

    def _backup_changed(self, before: Dict[str, Any], by: Optional[str]) -> Dict[str, Any]:
        """After a change of the choice: the log says what changed; a failure that was the old folder's is forgotten
        (a new backup folder is tried at once - it has no backup yet -, a new second folder at the next backup) - and so
        are the days that waited to reach the old folder (their files stay in the dashboard's own folder)."""
        after = self.backup_conf()
        said = "; ".join("%s: %s → %s" % (BACKUP_NAMES[k], before[k] or "yok", after[k] or "yok")
                         for k in BACKUP_KEYS if before[k] != after[k])
        if said:
            log.info("yedek ayarları değişti (%s): %s", by or "?", said)
        if not same_folder(before["dir"], after["dir"]):
            self.backup_error = None
            with self._backup_lock:
                if self.fallback_state()["days"]:
                    self.svc.store.put("ops.backup_fallback", {})
                self._fallback_tried = 0.0
        if not same_folder(before["copy_dir"], after["copy_dir"]):
            state = self.copy_state()
            if state.get("failed_days") or state.get("error"):
                self.svc.store.put("ops.backup_copy", dict(state, failed_days=[], error=None))
        with self._lock:
            self._lists.clear()
        return after

    def backup_page(self) -> Dict[str, Any]:
        """What the administrators' page shows: the settings as they stand and where each comes from, who saved the
        choice, the newest backups of each folder, the last failures."""
        conf = self.backup_conf()
        saved = self.saved_backup()
        found = backups(conf["dir"])
        copies = backups(conf["copy_dir"]) if conf["copy_dir"] else []
        state = self.copy_state()
        failing = bool(conf["copy_dir"] and state.get("failed_days"))
        fallback = self.fallback_view(conf)
        own = None
        if fallback is not None:                             # the dashboard's own folder, where the day's backup went
            mine = backups(fallback["dir"])
            own = {"dir": fallback["dir"], "backups": mine[:BACKUP_SHOWN], "count": len(mine)}
        return {"time": conf["time"], "dir": conf["dir"], "copy_dir": conf["copy_dir"], "source": conf["source"],
                "base": conf["base"], "keep": BACKUP_KEEP, "default_time": _config.DEFAULT_BACKUP_TIME,
                "saved": {"by": saved.get("by"), "at": saved.get("at")} if any(k in saved for k in BACKUP_KEYS) else None,
                "backups": found[:BACKUP_SHOWN], "count": len(found), "copies": copies[:BACKUP_SHOWN], "copy_count": len(copies),
                "error": self.backup_error, "copy_error": state.get("error") if failing else None,
                "copy_failed": len(state.get("failed_days") or []) if failing else 0, "fallback": fallback, "own": own,
                # no second copy: whether this machine has the drive of the installed dashboard's default (a hint)
                "d_drive": None if conf["copy_dir"] else _config.drive_exists(_config.DEFAULT_BACKUP_COPY_DIR)}

    def private_paths(self) -> List[str]:
        """Where the desk's files live on its computer - the database and its folder, the backup folders (chosen or
        not, the dashboard's own), the log: the administrators' to know, left out of what everyone reads.  The longest
        first."""
        st = self.svc.settings
        conf = self.backup_conf()
        found = {os.path.abspath(str(p)) for p in (getattr(st, "db_path", None), getattr(st, "data_dir", None), conf["dir"],
                                                   conf["copy_dir"], conf["base"]["dir"], conf["base"]["copy_dir"],
                                                   self.own_backup_dir(), log_file()) if p}
        return sorted(found, key=len, reverse=True)

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
        # -- the database: its check at the start, the daily backup (the whole desk reads the text: no folder in it)
        if not st["db_alarm"]:
            state("db", "off")
        else:
            bad = []
            conf = self.backup_conf()
            hide = self.private_paths()
            if self.db_check and not self.db_check["ok"]:
                bad.append("açılış denetimi başarısız: %s" % "; ".join(self.db_check["problems"][:2]))
            if self.backup_error:
                bad.append("yedek alınamadı (%s): %s" % (self.backup_error["at"][:16], hide_paths(self.backup_error["text"], hide)))
            waiting = sorted(self.fallback_pending(conf))   # backed up in the dashboard's own folder, not yet in the chosen one
            if waiting:
                own = os.path.join("data", "backups")
                if len(waiting) == 1:
                    which = "bugünkü yedek" if waiting[0] == today else "%s yedeği" % ".".join(reversed(waiting[0].split("-")))
                    bad.append("seçilen yedek klasörüne yazılamadı – %s dashboard'un kendi klasörüne (%s) alındı" % (which, own))
                else:
                    bad.append("seçilen yedek klasörüne %d gündür yazılamıyor – yedekler dashboard'un kendi klasörüne (%s) alındı"
                               % (len(waiting), own))
            copy = self.copy_state()
            # one day is said in the status only; two in a row: an alarm (no second folder chosen: nothing to say)
            if conf["copy_dir"] and len(copy.get("failed_days") or []) >= 2:
                bad.append("yedeğin ikinci kopyası %d gündür alınamadı: %s" % (
                    len(copy["failed_days"]), hide_paths((copy.get("error") or {}).get("text", ""), hide)))
            last = backups(conf["dir"])
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
                "db": "açılış denetimi ya da günlük yedek (%s) başarısızsa, yedek seçilen klasöre yazılamayıp dashboard'un kendi "
                      "klasörüne alındıysa; ikinci kopyası 2 gün üst üste alınamazsa" % self.backup_conf()["time"]}
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
            self.look(_dt.datetime.now())
            self._stop.wait(15.0)

    def look(self, now: _dt.datetime) -> None:
        """One look of the loop (every 15 s): market hours, the day's backup when due, the days that wait to reach the
        chosen folder (every BACKUP_RETRY), the Trades page's close when due, the system alarms."""
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
            self.catch_up()
        except Exception as exc:  # noqa: BLE001
            self.failure("yedeğin seçilen klasöre kopyası", exc)
        try:
            # the Trades page's close: every open trade's value, once a business day (a day missed: at the start)
            book = getattr(self.svc, "tradebook", None)
            if book is not None:
                book.look(now)
        except Exception as exc:  # noqa: BLE001 - tried again after tradebook.RETRY
            self.failure("Trades kapanış kaydı", exc)
        try:
            # Bugün's close record of DİBS RV's signals (the sheet keeps no history of them): once a business day
            today = getattr(self.svc, "bugun", None)
            if today is not None:
                today.look(now)
        except Exception as exc:  # noqa: BLE001 - tried again at the next look
            self.failure("Bugün · DİBS sinyal kaydı", exc)
        try:
            self.system_checks(now)
        except Exception as exc:  # noqa: BLE001
            self.failure("sistem alarmları", exc)
