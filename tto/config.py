"""Runtime settings."""
from __future__ import annotations

import os
from typing import Optional

#: ports that are already taken on the desk machine by other dashboards
FORBIDDEN_PORTS = (5000, 5001)
DEFAULT_PORT = 1057

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: the second copy of each night's database backup: another drive of the desk machine (the installed dashboard's default)
DEFAULT_BACKUP_COPY_DIR = r"D:\tto-yedek"


class Settings(object):
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT, data_dir: Optional[str] = None,
                 mode: str = "auto", bbg_host: str = "localhost", bbg_port: int = 8194,
                 tick_seconds: float = 2.0, locale: str = "tr", models_dir: Optional[str] = None,
                 bbg_stream: bool = True, bbg_bfx: str = "off", bbg_max_hits: int = 400000,
                 bbg_price_poll: float = 120.0, history: bool = True, history_refresh: float = 900.0,
                 bbg_isolate: bool = True, bbg_interval: Optional[float] = None, bbg_queue: int = 100000,
                 history_pace: float = 1.0, log_dir: Optional[str] = None, bbg_silent_restart: float = 60.0,
                 backup_dir: Optional[str] = None, backup_time: str = "22:00", backup_copy_dir: Optional[str] = None,
                 private_refresh: float = 5.0, idle_minutes: float = 30.0):
        self.host = host
        self.port = check_port(port)
        self.data_dir = data_dir or os.environ.get("TTO_DATA_DIR") or os.path.join(ROOT, "data")
        self.mode = mode                    # auto | live | replay
        self.bbg_host = bbg_host
        self.bbg_port = int(bbg_port)
        self.tick_seconds = float(tick_seconds)
        self.locale = locale
        self.models_dir = models_dir or os.path.join(ROOT, "models")
        self.bbg_stream = bool(bbg_stream)      # real-time fields by subscription (False: poll them)
        self.bbg_bfx = bbg_bfx                  # "off" | "approx"  (BFXFORWARD has no API equivalent)
        self.bbg_max_hits = int(bbg_max_hits)   # daily cap on reference/historical data points (0 = no cap)
        self.bbg_price_poll = float(bbg_price_poll)
        self.history = bool(history)            # keep the daily history up to date in the background
        self.history_refresh = float(history_refresh)   # seconds between history updates in live mode (0: once)
        self.bbg_isolate = bool(bbg_isolate)    # the Bloomberg session in a helper process (see marketdata/bbg_process.py)
        # seconds between two ticks of one subscription; None: every tick in the helper process, 1 s inside this one
        self.bbg_interval = None if bbg_interval is None else max(0.0, float(bbg_interval))
        self.bbg_queue = int(bbg_queue)         # undelivered events the Bloomberg session may hold
        # live mode: after a day of the meeting-pricing history has been computed, rest this many times as long
        self.history_pace = max(0.0, float(history_pace))
        # the log file (tto.log, rotated): in the data folder - the install's, never a folder git keeps
        self.log_dir = log_dir or os.environ.get("TTO_LOG_DIR") or os.path.join(self.data_dir, "logs")
        # a Bloomberg helper silent this many seconds in market hours is started again (0: never; see bbg_process.py)
        self.bbg_silent_restart = max(0.0, float(bbg_silent_restart))
        # the nightly backup of the database: where (the data folder's backups by default) and when (HH:MM)
        self.backup_dir = backup_dir or os.environ.get("TTO_BACKUP_DIR") or os.path.join(self.data_dir, "backups")
        self.backup_time = check_time(backup_time)
        # ... and a second copy of each one in another folder - another drive (None: no second copy)
        given = backup_copy_dir if backup_copy_dir is not None else os.environ.get("TTO_BACKUP_COPY_DIR")
        if given is not None:
            self.backup_copy_dir = None if given.strip() in ("", "-") else given.strip()
        else:
            self.backup_copy_dir = backup_copy_default(self.data_dir)
        # a user with inputs of their own: their header, pages and watch list follow the market at most this often
        # (seconds; their own changes show at once) - each is a calculation of its own (0: every time)
        self.private_refresh = max(0.0, float(private_refresh))
        # a user not seen for this long (minutes) gives their calculations back (made again when they return; 0: never)
        self.idle_minutes = max(0.0, float(idle_minutes))

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "tto.db")


def backup_copy_default(data_dir: str, root: str = ROOT, windows: bool = os.name == "nt") -> Optional[str]:
    """Where the second copy of the backups goes when nothing says: D:\\tto-yedek for the installed dashboard (on
    Windows, in a folder that is no git checkout, with its own data folder).  A checkout - a developer's, the tests' -
    or a dashboard given another data folder has none unless asked: its copies must never land on the desk's."""
    installed = windows and not os.path.exists(os.path.join(root, ".git"))
    own = os.path.normcase(os.path.abspath(data_dir)) == os.path.normcase(os.path.abspath(os.path.join(root, "data")))
    return DEFAULT_BACKUP_COPY_DIR if installed and own else None


def check_time(text) -> str:
    """A time of day as HH:MM ("2:30", "02.30" too)."""
    parts = str(text or "").strip().replace(".", ":").split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise ValueError("saat SS:DD biçiminde olmalı: %r" % (text,))
    if len(parts) != 2 or not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("saat SS:DD biçiminde olmalı: %r" % (text,))
    return "%02d:%02d" % (h, m)


def check_port(port) -> int:
    port = int(port)
    if port in FORBIDDEN_PORTS:
        raise ValueError("port %d is already in use on the desk machine by another dashboard (%s are taken); "
                         "choose another one, e.g. %d" % (port, ", ".join(str(p) for p in FORBIDDEN_PORTS), DEFAULT_PORT))
    if not (1 <= port <= 65535):
        raise ValueError("invalid port %r" % (port,))
    return port
