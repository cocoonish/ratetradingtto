"""The data folder's guards: one dashboard per data folder, and whether the folder is on a network drive.

**Why** (24.11.2026, the office): the dashboard's install and its ``data`` folder sat on a mapped share; after the
desk's own Bloomberg limit ran out the dashboard was opened from a colleague's computer on the same folder, and the
database came back damaged ("database disk image is malformed").  SQLite's write-ahead log (WAL) needs every process
on one computer - they share memory through the ``-shm`` file - and does not work on a network filesystem: two
computers on one database file, or one over a share, can damage it.

* **One dashboard per data folder** (``data/tto.lock``, :class:`DataLock`).  A file made with an exclusive create -
  that works on a share of the network too; no lock of the operating system is relied on across computers - says who
  holds the folder (the program, computer, user, process, port), since when, and carries a heartbeat rewritten every
  BEAT_EVERY seconds.
  - A start while another holds a fresh lock is refused (:class:`LockHeld`: who, where, since when; a non-zero exit).
  - A stale lock - its holder gone without a clean exit: the window closed, a crash, the computer switched off - is
    taken over, with a log line.  On this computer a lock is stale when its process is gone, or its heartbeat is older
    than FRESH seconds.  Another computer's clock is not this one's: its lock is watched for up to WATCH seconds, and
    only a heartbeat that does not move meanwhile is stale.
  - A clean exit removes it.
  - ``yedekten-don`` and ``kurtar`` hold it too while they change the database (``kurtar --dene`` only looks:
    :func:`check_free`).
  - A dashboard whose lock another one took over (its heartbeat could not be written for a minute: the network folder
    was gone, the computer slept) is told (``on_lost``) and stops: two dashboards must not write one file.
* **A data folder on a network drive** (:func:`on_network_drive`; Windows: a ``\\\\server\\share`` path, or a drive
  letter the system calls remote; no detection elsewhere): the store runs the database with ``journal_mode=DELETE``
  instead of WAL there, and the start, the log and the status page say it loudly (NETWORK_WARNING).
"""
from __future__ import annotations

import datetime as _dt
import getpass
import json
import logging
import os
import socket
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional, Tuple

log = logging.getLogger("tto.datadir")

#: the lock file, in the data folder
LOCK_NAME = "tto.lock"
#: seconds between two heartbeats of the holder
BEAT_EVERY = 15.0
#: a heartbeat younger than this (seconds, this computer's clock): the holder runs
FRESH = 60.0
#: another computer's lock is watched this long (seconds) for a heartbeat before it is taken for stale
WATCH = 35.0
#: what the start, the log and the status page say of a data folder on a network drive
NETWORK_WARNING = ("Veri klasörü bir ağ sürücüsünde: veritabanı bozulabilir - dashboard'u bilgisayarın kendi diskine kurun; "
                   "yedeğin ikinci kopyası ağda durabilir")
#: who may hold the lock, as the messages name them
PROGRAMS = {"dashboard": "dashboard", "yedekten-don": "'yedekten-don' komutu", "kurtar": "'kurtar' komutu"}
#: GetDriveTypeW's answer for a drive of the network
DRIVE_REMOTE = 4


# ====================================================================== the network drive
def _drive_type(root: str) -> int:
    """Windows' kind of the drive ``root`` (``"Z:\\"``): 4 is DRIVE_REMOTE."""
    import ctypes
    return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))


def _remote(path: str) -> bool:
    p = os.path.abspath(path).replace("/", "\\")
    if p.upper().startswith("\\\\?\\UNC\\"):
        return True
    if p.startswith("\\\\?\\") or p.startswith("\\\\.\\"):
        p = p[4:]                                       # a local path in its long form (\\?\C:\...)
    elif p.startswith("\\\\"):
        return True                                     # \\server\share\...
    drive = os.path.splitdrive(p)[0]
    if len(drive) != 2 or drive[1] != ":":
        return False
    try:
        return _drive_type(drive + "\\") == DRIVE_REMOTE
    except Exception:  # noqa: BLE001 - no answer: a local disk, as before
        return False


def on_network_drive(path: str) -> bool:
    """Whether ``path`` (a file or a folder) is on a drive of the network: on Windows a ``\\\\server\\share`` path or a
    drive letter mapped to one - also through a link into such a folder; elsewhere never (no detection)."""
    if os.name != "nt" or not path or path == ":memory:":
        return False
    if _remote(path):
        return True
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return os.path.normcase(real) != os.path.normcase(os.path.abspath(path)) and _remote(real)


# ====================================================================== the lock
def host_name() -> str:
    try:
        name = socket.gethostname()
    except Exception:  # noqa: BLE001
        name = ""
    return name or os.environ.get("COMPUTERNAME") or "?"


def user_name() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return os.environ.get("USERNAME") or os.environ.get("USER") or "?"


def _stamp(t: Optional[float] = None) -> str:
    return _dt.datetime.fromtimestamp(time.time() if t is None else t).strftime("%Y-%m-%d %H:%M:%S")


def _shown(stamp: Any) -> str:
    """"2026-11-24 09:01:02" as the desk reads it: 24.11.2026 09:01."""
    try:
        return _dt.datetime.strptime(str(stamp), "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(stamp or "?")


def pid_running(pid: Any) -> Optional[bool]:
    """Whether a process of this computer runs with that number (``None``: cannot tell).  Never ``os.kill(pid, 0)`` on
    Windows: signal 0 is CTRL_C_EVENT there."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.OpenProcess.restype = wintypes.HANDLE
            k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            handle = k.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ctypes.get_last_error() == 5                 # ERROR_ACCESS_DENIED: it is there (another user's)
            try:
                code = wintypes.DWORD()
                if not k.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259                            # STILL_ACTIVE
            finally:
                k.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _parse(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        rec = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("token") else None


def read_lock(path: str, tries: int = 5) -> Optional[Dict[str, Any]]:
    """The lock's record; ``None`` when there is no lock.  A file being rewritten that moment is read again; one that
    never reads is ``{"raw": <its bytes>}`` (a holder that died while it was writing)."""
    data = b""
    for k in range(tries):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return None
        except OSError:
            data = b""
        rec = _parse(data)
        if rec is not None:
            return rec
        if k + 1 < tries:
            time.sleep(0.2)
    return {"raw": data}


def _mark(rec: Optional[Dict[str, Any]]) -> Tuple[Any, ...]:
    """What tells one heartbeat from the next."""
    if not rec:
        return (None,)
    if "raw" in rec:
        return ("raw", rec["raw"])
    return (rec.get("token"), rec.get("seq"), rec.get("beat"))


def _same_host(rec: Dict[str, Any]) -> bool:
    return str(rec.get("host") or "").casefold() == host_name().casefold()


def holder_alive(path: str, rec: Dict[str, Any], watch: float = WATCH, say: Optional[Callable[[str], None]] = None,
                 sleep: Callable[[float], None] = time.sleep) -> Tuple[bool, str]:
    """Whether the holder of the lock ``rec`` (read from ``path``) still runs, and why it is taken for gone.

    * This computer: gone when its process is, or when its heartbeat is FRESH seconds old (one clock: this one's).
    * Another computer (or a record that cannot be read): its clock is not ours - the lock is watched for ``watch``
      seconds; a heartbeat that moves meanwhile is a holder that runs."""
    if "raw" not in rec and _same_host(rec):
        if pid_running(rec.get("pid")) is False:
            return False, "süreci (%s) yok" % rec.get("pid")
        age = time.time() - float(rec.get("beat_epoch") or 0.0)
        if age >= FRESH:
            return False, "son işareti %d sn önce" % age
        return True, ""
    if say is not None:
        say("Veri klasöründe %s: açık olup olmadığına bakılıyor (en çok %d sn)..." % (
            "okunamayan bir kilit var" if "raw" in rec else "%s bilgisayarının kilidi var (%s, açılışı %s)" % (
                rec.get("host") or "?", PROGRAMS.get(rec.get("program"), "dashboard"), _shown(rec.get("started"))),
            watch))
    first = _mark(rec)
    deadline = time.monotonic() + watch
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return False, "%d sn boyunca işaret vermedi" % watch
        sleep(min(1.0, left))
        now = read_lock(path)
        if now is None:
            return False, "kilit kalktı"
        if _mark(now) != first:
            return True, ""


def held_text(rec: Dict[str, Any], wanted: str = "dashboard") -> str:
    """Why ``wanted`` (a program of PROGRAMS) cannot run now: who holds the data folder, where, since when."""
    if "raw" in rec:
        return ("Veri klasöründe okunamayan bir kilit dosyası (%s) var ve hâlâ yazılıyor: başka bir dashboard açık olabilir. "
                "Her yerde kapatıp yeniden deneyin." % LOCK_NAME)
    who = rec.get("program") or "dashboard"
    host = rec.get("host") or "?"
    same = _same_host(rec)
    where = "bu bilgisayarda (%s)" % host if same else "%s bilgisayarında" % host
    detail = ", ".join(x for x in ("kullanıcı: %s" % rec["user"] if rec.get("user") else "",
                                   "açılışı %s" % _shown(rec.get("started")),
                                   "port %s" % rec["port"] if rec.get("port") else "") if x)
    if who != "dashboard":
        holder = "%s %s %s çalışıyor (%s)" % ("Bu veri klasöründe", where, PROGRAMS.get(who, who), detail)
        return "%s: bitmesini bekleyin, sonra yeniden deneyin." % holder
    holder = "Bu veri klasörünü %s bir dashboard kullanıyor (%s)" % (where, detail)
    if wanted == "dashboard":
        if same:
            return ("%s - aynı veritabanını iki dashboard birlikte açarsa dosya bozulabilir, bu dashboard başlatılmadı. Açık "
                    "olanı kullanın%s ya da önce onu kapatın (penceresinde Ctrl+C), sonra yeniden başlatın." % (
                        holder, " (tarayıcıda http://localhost:%s)" % rec["port"] if rec.get("port") else ""))
        return ("%s - aynı veritabanını iki bilgisayar birlikte açarsa dosya bozulabilir, bu dashboard başlatılmadı. O "
                "bilgisayardaki dashboard'u kullanın ya da önce onu kapatın (penceresinde Ctrl+C), sonra yeniden başlatın." % holder)
    doing = {"yedekten-don": "yedekten dönülmez", "kurtar": "kurtarma yapılmaz"}.get(wanted, "bu komut çalışmaz")
    return ("Dashboard açıkken %s: %s. Önce dashboard'u her yerde kapatın (penceresinde Ctrl+C), sonra komutu yeniden "
            "çalıştırın." % (doing, holder[0].lower() + holder[1:]))


def took_over_text(rec: Optional[Dict[str, Any]], why: str) -> str:
    """The log line of a stale lock taken over."""
    if not rec or "raw" in rec:
        return "veri klasörünün okunamayan eski kilidi devralındı (%s)" % why
    return "veri klasörünün eski kilidi devralındı: %s · %s · kullanıcı %s · süreç %s · açılışı %s · son işareti %s (%s)" % (
        rec.get("host") or "?", PROGRAMS.get(rec.get("program"), rec.get("program") or "?"), rec.get("user") or "?",
        rec.get("pid") or "?", _shown(rec.get("started")), rec.get("beat") or "?", why)


class LockHeld(RuntimeError):
    """The data folder is held by another dashboard or command: ``holder`` is its record (``None``: the lock could
    not be had for another reason), the text says who, where and since when."""

    def __init__(self, text: str, holder: Optional[Dict[str, Any]] = None):
        RuntimeError.__init__(self, text)
        self.holder = holder


def check_free(folder: str, wanted: str, watch: float = WATCH, say: Optional[Callable[[str], None]] = None) -> None:
    """Raise :class:`LockHeld` when a dashboard or a command runs on ``folder`` now (nothing is taken: a command that
    only looks)."""
    path = os.path.join(os.path.abspath(folder), LOCK_NAME)
    rec = read_lock(path)
    if rec is not None and holder_alive(path, rec, watch=watch, say=say)[0]:
        raise LockHeld(held_text(rec, wanted), rec)


class DataLock(object):
    """The lock of one data folder, held by this process (see the module text): :meth:`acquire`, the heartbeat thread
    (:meth:`start`), :meth:`release`."""

    def __init__(self, folder: str, program: str = "dashboard", port: Optional[int] = None, watch: float = WATCH,
                 say: Optional[Callable[[str], None]] = None):
        self.folder = os.path.abspath(folder)
        self.path = os.path.join(self.folder, LOCK_NAME)
        self.program = program
        self.port = port
        self.watch = watch
        self.say = say                                         # console lines while another computer's lock is watched
        self.token = uuid.uuid4().hex
        self.held = False
        self.started: Optional[str] = None
        self.beat_at: Optional[str] = None                     # the last heartbeat written
        self.took_over: Optional[Dict[str, Any]] = None        # the stale lock taken over at the start ...
        self.took_over_why = ""                                # ... and why it was stale
        self.lost: Optional[Dict[str, Any]] = None             # the lock that took this one's place
        self.on_lost: Optional[Callable[[Dict[str, Any]], None]] = None
        self._seq = 0
        self._io = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._failing: Optional[float] = None                  # since when the heartbeat cannot be written

    # ------------------------------------------------------------------ taking it
    def _record(self) -> Dict[str, Any]:
        now = time.time()
        self.beat_at = _stamp(now)
        rec = {"program": self.program, "host": host_name(), "user": user_name(), "pid": os.getpid(),
               "started": self.started, "beat": self.beat_at, "beat_epoch": round(now, 3), "seq": self._seq,
               "token": self.token}
        if self.port:
            rec["port"] = self.port
        return rec

    def _create(self) -> None:
        """The lock file made with an exclusive create (``FileExistsError``: there is one)."""
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        try:
            os.write(fd, json.dumps(self._record(), ensure_ascii=False).encode("utf-8"))
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.remove(self.path)                           # (half made: not left behind)
            except OSError:
                pass
            raise
        os.close(fd)

    def _move_aside(self, seen: Dict[str, Any]) -> bool:
        """The stale lock ``seen`` out of the way: renamed aside, checked to be the one judged (a lock another start made
        meanwhile goes back), removed."""
        aside = "%s.eski-%s" % (self.path, self.token[:12])
        try:
            os.rename(self.path, aside)
        except FileNotFoundError:
            return False
        except OSError:
            time.sleep(0.5)                                    # (open elsewhere that moment: looked at again)
            return False
        if _mark(read_lock(aside, tries=1)) != _mark(seen):
            try:
                if os.name == "nt":
                    os.rename(aside, self.path)                # (never over a lock made meanwhile)
                else:
                    os.link(aside, self.path)
                    os.remove(aside)
            except OSError:
                pass
            return False
        try:
            os.remove(aside)
        except OSError:
            pass
        return True

    def acquire(self) -> "DataLock":
        """Take the data folder: :class:`LockHeld` while another dashboard or command holds it; a stale lock is taken
        over (``took_over``: its record, ``took_over_why``: why it was stale - the caller logs it)."""
        os.makedirs(self.folder, exist_ok=True)
        self.started = _stamp()
        for _ in range(6):
            try:
                with self._io:
                    self._create()
                    self.held = True
                return self
            except FileExistsError:
                pass
            seen = read_lock(self.path)
            if seen is None:
                continue                                       # (gone meanwhile)
            alive, why = holder_alive(self.path, seen, watch=self.watch, say=self.say)
            if alive:
                raise LockHeld(held_text(seen, self.program), seen)
            if self._move_aside(seen):
                self.took_over, self.took_over_why = seen, why
        raise LockHeld("Veri klasörünün kilidi (%s) alınamadı: aynı anda başka bir başlatma var. Bir dakika sonra yeniden deneyin."
                       % LOCK_NAME)

    # ------------------------------------------------------------------ keeping it
    def beat(self) -> bool:
        """One heartbeat: the lock rewritten in place with a new time - only while it is still this process's.  False:
        another dashboard took it over (``lost``, ``on_lost`` told)."""
        with self._io:
            if not self.held:
                return False
            try:
                # read and rewritten through one handle: on Windows nobody can rename the file away meanwhile (a start
                # that takes a stale lock over renames it first)
                for k in range(5):
                    with open(self.path, "r+b") as fh:
                        rec = _parse(fh.read())
                        if rec is not None and rec.get("token") != self.token:
                            return self._was_taken(rec)
                        if rec is not None or k == 4:      # ours - or ours, left broken by a write that failed
                            self._seq += 1
                            fh.seek(0)
                            fh.truncate()
                            fh.write(json.dumps(self._record(), ensure_ascii=False).encode("utf-8"))
                            fh.flush()
                            os.fsync(fh.fileno())
                            break
                    time.sleep(0.2)                        # (a start writing its new lock that moment: read again)
            except FileNotFoundError:
                try:
                    self._create()                             # (deleted by hand: made again)
                except FileExistsError:
                    return self._was_taken(read_lock(self.path))
                except OSError as exc:
                    self._failed(exc)
                    return True
            except OSError as exc:                             # a folder of the network that does not answer: tried again
                self._failed(exc)
                return True
            if self._failing is not None:
                log.warning("veri klasörünün kilidi yeniden yazılabiliyor (%d sn yazılamadı)", time.time() - self._failing)
                self._failing = None
            return True

    def _failed(self, exc: OSError) -> None:
        if self._failing is None:
            self._failing = time.time()
            log.warning("veri klasörünün kilidi yazılamadı (%s) - yeniden denenecek; %d sn yazılamazsa başka bir dashboard "
                        "onu devralabilir", exc, FRESH)

    def _was_taken(self, rec: Optional[Dict[str, Any]]) -> bool:
        self.held = False
        self.lost = rec or {"raw": b""}
        log.error("veri klasörünün kilidi başka bir dashboard'a geçti (%s): bu %s duruyor - iki dashboard aynı veritabanına "
                  "yazmasın diye", "%s, açılışı %s" % (rec.get("host") or "?", _shown(rec.get("started")))
                  if rec and "raw" not in rec else "okunamayan kilit", PROGRAMS.get(self.program, self.program))
        told = self.on_lost
        if told is not None:
            try:
                told(self.lost)
            except Exception:  # noqa: BLE001
                log.exception("kilit kaybı bildirilemedi")
        return False

    def start(self) -> "DataLock":
        """The heartbeat thread (every BEAT_EVERY seconds, until :meth:`release` or the lock is lost)."""
        if self._thread is None and self.held:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="tto-kilit", daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(BEAT_EVERY):
            try:
                if not self.beat():
                    return
            except Exception:  # noqa: BLE001 - the heartbeat must outlive anything
                log.exception("kilidin kalp atışı")

    # ------------------------------------------------------------------ giving it back
    def release(self) -> None:
        """Stop the heartbeat and remove the lock - only if it is still this process's."""
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5.0)
        self._thread = None
        with self._io:
            if not self.held:
                return
            self.held = False
            rec = read_lock(self.path, tries=2)
            if rec is not None and rec.get("token") == self.token:
                try:
                    os.remove(self.path)
                except OSError as exc:
                    log.warning("veri klasörünün kilidi silinemedi (%s): bir sonraki açılış onu eski kilit sayıp devralır", exc)

    def __enter__(self) -> "DataLock":
        return self.acquire().start()

    def __exit__(self, *exc: Any) -> None:
        self.release()

    # ------------------------------------------------------------------ for the status page
    def info(self) -> Dict[str, Any]:
        def brief(rec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not rec:
                return None
            if "raw" in rec:
                return {"host": "?", "started": None, "beat": None}
            return {"host": rec.get("host"), "program": rec.get("program"), "started": _shown(rec.get("started")),
                    "beat": rec.get("beat")}
        return {"held": self.held, "program": self.program, "host": host_name(), "since": _shown(self.started),
                "beat": self.beat_at, "every": BEAT_EVERY, "failing": _stamp(self._failing) if self._failing else None,
                "took_over": dict(brief(self.took_over) or {}, why=self.took_over_why) if self.took_over else None,
                "lost": brief(self.lost)}
