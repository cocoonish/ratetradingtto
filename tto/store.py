"""SQLite persistence: users, personal inputs, named scenarios, shared inputs (RET curve ...), blotter, the Trades page.

A write of several steps (a package of trades deleted, a broker chat pasted, an account removed) is one
transaction: it lands whole or not at all.  Every commit is on the disk before it returns (``synchronous=FULL``):
a trade entered a moment before a power cut is kept.  :meth:`Store.backup_to` makes an online copy (SQLite's backup
API, consistent while the dashboard keeps writing); :func:`restore` puts one back in place.

The file keeps a write-ahead log (``journal_mode=WAL``) - except on a network drive (``datadir.on_network_drive``):
WAL needs every process on one computer (they share memory through ``-shm``) and cannot work on a network filesystem,
so there the rollback journal (``DELETE``) is used for that run, and writers wait longer for a reader that holds the
file (the backup's).

The history's tables - the daily closes (``hist_values``), the watch's own closes (``watch_closes``) and the meeting
pricing (``mpc_days`` / ``mpc_values``) - are kept in memory as well: read once when the file is opened, changed by
every write of the store after it is committed, and read from memory only.  Python's sqlite3 gives the interpreter
up on every row it reads; while a long calculation holds it (the quant fit, the backtest, the history sync) each row
waited for it again (~5 ms): the heat map's closes held the calculation thread for half a minute.
"""
from __future__ import annotations

import bisect
import contextlib
import datetime as _dt
import itertools
import json
import math
import os
import pathlib
import pickle
import re
import shutil
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from . import datadir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY, display TEXT NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_inputs (
    user TEXT NOT NULL, book TEXT NOT NULL, cell TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (user, book, cell));
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (user, name));
CREATE TABLE IF NOT EXISTS shared_inputs (
    book TEXT NOT NULL, cell TEXT NOT NULL, value TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY (book, cell));
CREATE TABLE IF NOT EXISTS ret_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ret_fair_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user TEXT, kind TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT NOT NULL, kind TEXT NOT NULL, package TEXT,
    payload TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS trades_date ON trades (trade_date, deleted);
CREATE TABLE IF NOT EXISTS blotter_snapshots (
    trade_date TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broker_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, quote_date TEXT NOT NULL, quote_time TEXT NOT NULL, mark TEXT NOT NULL,
    payload TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS broker_date ON broker_quotes (quote_date, deleted);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hist_values (
    series TEXT NOT NULL, day TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (series, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS mpc_days (
    day TEXT PRIMARY KEY, basis TEXT NOT NULL, spot TEXT, tlref REAL, base REAL, decision INTEGER NOT NULL DEFAULT 0,
    quotes INTEGER, status TEXT, note TEXT, computed_at TEXT NOT NULL, control REAL, tolerance REAL, carried INTEGER,
    cleaned TEXT);
CREATE TABLE IF NOT EXISTS mpc_values (
    day TEXT NOT NULL, meeting TEXT NOT NULL, step REAL, level REAL, cum REAL, sigma REAL, front INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, meeting)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS mpc_values_meeting ON mpc_values (meeting, day);
CREATE TABLE IF NOT EXISTS watch_closes (
    subject TEXT NOT NULL, day TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY (subject, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bbg_answers (key BLOB PRIMARY KEY, day TEXT NOT NULL, fetched REAL NOT NULL, value BLOB);
CREATE TABLE IF NOT EXISTS bbg_usage (key BLOB PRIMARY KEY, day TEXT NOT NULL, hits INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, ip TEXT);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, text TEXT NOT NULL, page TEXT, page_title TEXT,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL, done_by TEXT, done_at TEXT);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agenda (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, day TEXT NOT NULL, time TEXT, text TEXT NOT NULL,
    deadline INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TEXT NOT NULL, done_by TEXT, done_at TEXT);
CREATE INDEX IF NOT EXISTS agenda_day ON agenda (day);
CREATE TABLE IF NOT EXISTS agenda_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, kind TEXT NOT NULL, weekdays TEXT, time TEXT NOT NULL,
    text TEXT NOT NULL, deadline INTEGER NOT NULL DEFAULT 0, start_day TEXT, end_day TEXT, since TEXT NOT NULL,
    paused_by TEXT, paused_at TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS agenda_rule_days (
    rule INTEGER NOT NULL, day TEXT NOT NULL, done_by TEXT NOT NULL, done_at TEXT NOT NULL,
    PRIMARY KEY (rule, day)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS agenda_rule_days_day ON agenda_rule_days (day);
CREATE TABLE IF NOT EXISTS agenda_snoozes (
    user TEXT NOT NULL, rule INTEGER NOT NULL, day TEXT NOT NULL, until TEXT NOT NULL,
    PRIMARY KEY (user, rule, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS trade_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, name TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS trade_templates_owner ON trade_templates (owner);
CREATE TABLE IF NOT EXISTS tradebook (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, owner TEXT NOT NULL, product TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', trade_date TEXT NOT NULL, payload TEXT NOT NULL, created_by TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tradebook_who ON tradebook (scope, owner, status, deleted);
CREATE TABLE IF NOT EXISTS tradebook_close_days (
    day TEXT PRIMARY KEY, at TEXT NOT NULL, taken_at TEXT NOT NULL, late INTEGER NOT NULL DEFAULT 0,
    trades INTEGER NOT NULL DEFAULT 0, valued INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tradebook_closes (
    day TEXT NOT NULL, trade INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (day, trade)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS tradebook_closes_trade ON tradebook_closes (trade, day);
CREATE TABLE IF NOT EXISTS tradebook_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user TEXT NOT NULL, trade INTEGER NOT NULL,
    scope TEXT NOT NULL, owner TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS tradebook_log_trade ON tradebook_log (trade, id);
CREATE INDEX IF NOT EXISTS tradebook_log_who ON tradebook_log (scope, owner, id);
CREATE TABLE IF NOT EXISTS quote_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, quote_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
    payload TEXT NOT NULL, created_by TEXT, created_at TEXT NOT NULL, updated_by TEXT, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS quote_log_date ON quote_log (quote_date, id);
"""


#: table -> columns added after its first version: the solver's own check of a day (largest distance between
#: model and quote in bp, and what the workbook tolerates), how many quotes were not that day's own close and
#: which closes were not used (the roots of their tickers); a user's sign-in: the password hash, administrator
#: or not, active / waiting for approval / closed, the note sent with a request and who decided on it, the wrong
#: passwords in a row and until when the name is locked, the last sign-in and the address it came from (presence.py:
#: ``last_seen`` is the last moment the user was connected from then on).  A user of an earlier version is an active
#: user without a password: they ask for an account under the same name to set one.  An input typed as a formula
#: (``=C60+7``): its text beside its value - the value is the formula's result as it was set (an earlier version reads
#: the value).
_ADDED_COLUMNS = {"mpc_days": (("control", "REAL"), ("tolerance", "REAL"), ("carried", "INTEGER"), ("cleaned", "TEXT")),
                  "users": (("pw_hash", "TEXT"), ("role", "TEXT NOT NULL DEFAULT 'user'"),
                            ("status", "TEXT NOT NULL DEFAULT 'active'"), ("note", "TEXT"), ("requested_at", "TEXT"),
                            ("decided_by", "TEXT"), ("decided_at", "TEXT"), ("failed", "INTEGER NOT NULL DEFAULT 0"),
                            ("locked_until", "TEXT"), ("requested_new", "INTEGER NOT NULL DEFAULT 0"),
                            ("last_login", "TEXT"), ("last_login_ip", "TEXT")),
                  "user_inputs": (("formula", "TEXT"),),
                  "shared_inputs": (("formula", "TEXT"),),
                  # what an upload changed per tenor and where it came from (JSON: {"changes": [...], "source": ...})
                  "ret_history": (("meta", "TEXT"),)}
_ACCOUNT_FIELDS = ("display", "last_seen", "pw_hash", "role", "status", "note", "requested_at", "decided_by", "decided_at",
                   "failed", "locked_until", "requested_new", "last_login", "last_login_ip")


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def user_key(name: str) -> str:
    """Canonical key of a user name: case, surrounding blanks and the Turkish dotted / dotless i do not
    create new users ("AYŞE YILMAZ", "Ayşe Yılmaz" and "ayşe yilmaz" are one person)."""
    key = " ".join(name.strip().split()).casefold()
    return key.replace("\u0307", "").replace("\u0131", "i")


_CELL = re.compile(r"^(.*)!\$?([A-Za-z]{1,3})\$?(\d+)$")


def _cell_order(ref: str) -> Tuple[str, int, int, str]:
    """A cell's place for sorting ("Sheet!B12" after "Sheet!B9"): sheet, row, column."""
    m = _CELL.match(ref or "")
    if not m:
        return (ref or "", 0, 0, "")
    return (m.group(1), int(m.group(3)), len(m.group(2)), m.group(2).upper())


def restore(backup: str, db_path: str) -> Dict[str, Any]:
    """Put a backup in the place of the database - with the dashboard stopped (``python -m tto yedekten-don`` holds
    the data folder's lock while it runs: datadir.py).  The backup is checked first (a sound SQLite file with the
    dashboard's tables); the database as it was is kept beside it, with its write-ahead log or journal
    (``tto.db.onceki-<time>``): nothing is deleted - ``python -m tto kurtar`` reads it back (recover.py).  On Windows a
    database the dashboard still has open cannot be moved: that stops the restore before anything changed."""
    backup, db_path = os.path.abspath(backup), os.path.abspath(db_path)
    if not os.path.isfile(backup):
        raise ValueError("yedek dosyası yok: %s" % backup)
    if backup == db_path:
        raise ValueError("yedek, veritabanının kendisi")
    try:
        con = sqlite3.connect(pathlib.Path(backup).as_uri() + "?mode=ro", uri=True)
        try:
            found = [str(r[0]) for r in con.execute("PRAGMA quick_check(5)").fetchall()]
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError("yedek açılamadı: %s" % exc)
    if found != ["ok"]:
        raise ValueError("yedeğin denetimi başarısız: %s" % "; ".join(found))
    if not {"users", "trades", "kv"} <= tables:
        raise ValueError("bu bir TTO Masa veritabanı değil: %s" % backup)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = db_path + ".onceki-" + stamp
    moved: List[Tuple[str, str]] = []
    try:
        # the database with its log - the write-ahead log, or the rollback journal a run on a network drive left after a
        # crash: it belongs to that file, never to the backup (beside the backup it would "roll back" pages into it)
        for suffix in ("", "-wal", "-shm", "-journal"):
            if os.path.exists(db_path + suffix):
                os.replace(db_path + suffix, kept + suffix)
                moved.append((db_path + suffix, kept + suffix))
    except OSError as exc:
        for src, dst in reversed(moved):             # back as it was
            os.replace(dst, src)
        raise ValueError("veritabanı yerinden alınamadı (%s) – dashboard açık mı? Önce kapatın." % exc)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    shutil.copy2(backup, db_path + ".part")
    os.replace(db_path + ".part", db_path)
    return {"restored": db_path, "from": backup, "kept": kept if moved else None}


class _Daily(object):
    """A table of ``(key, day, value)`` rows in memory - ``hist_values`` (key: the series), ``watch_closes`` (the
    subject): key -> (its days ascending, their values).  Read under the store's ``_mem`` lock; changed only after a
    write of the file is committed (:meth:`Store._later`)."""

    def __init__(self) -> None:
        self.by: Dict[str, Tuple[List[str], List[Any]]] = {}
        self._days: Dict[str, str] = {}               # one string per day for every key (~530 days, ~175 000 closes)

    def load(self, rows: Iterator[Tuple[str, str, Any]]) -> None:
        """The table as read from the file, ordered by key and day."""
        self.by = {}
        for key, group in itertools.groupby(rows, key=lambda r: r[0]):
            days: List[str] = []
            vals: List[Any] = []
            for _, day, v in group:
                days.append(self._days.setdefault(day, day))
                vals.append(v)
            self.by[key] = (days, vals)

    def span(self, key: str, start: str, end: str) -> Tuple[List[str], List[Any]]:
        """The days of ``key`` from ``start`` to ``end`` (both included, as ``day>=? AND day<=?``) and their values."""
        got = self.by.get(key)
        if got is None:
            return [], []
        days, vals = got
        i, j = bisect.bisect_left(days, start), bisect.bisect_right(days, end)
        return days[i:j], vals[i:j]

    def put(self, key: str, rows: Sequence[Tuple[str, Any]]) -> None:
        """Rows written, in their order (an upsert: a day the key has takes the new value).  A key or a day that is not
        text (SQLite would have turned it into some) raises: the store then reads the table again from the file."""
        if not rows:
            return
        if type(key) is not str or any(type(day) is not str for day, _ in rows):
            raise TypeError("not text: %r" % (key,))
        days, vals = self.by.setdefault(key, ([], []))
        for day, v in rows:
            k = bisect.bisect_left(days, day)
            if k < len(days) and days[k] == day:
                vals[k] = v
            else:
                days.insert(k, self._days.setdefault(day, day))
                vals.insert(k, v)

    def drop(self, key: Optional[str] = None) -> None:
        if key is None:
            self.by = {}
        else:
            self.by.pop(key, None)

    def rename(self, old: str, new: str) -> None:
        """``UPDATE OR REPLACE ... SET key=new WHERE key=old``: the old key's rows go under the new one, in place of its
        rows of the same days."""
        if old == new or old not in self.by:
            return
        days, vals = self.by.pop(old)
        self.put(new, list(zip(days, vals)))


_UNSURE = object()


def _zero_back() -> float:
    """What this SQLite gives back of -0.0 written to a REAL column (0.0 as of 3.35: a whole number is kept as an integer)."""
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE t (v REAL)")
        db.execute("INSERT INTO t VALUES (?)", (-0.0,))
        return float(db.execute("SELECT v FROM t").fetchone()[0])
    finally:
        db.close()


_NEG_ZERO = _zero_back()


def _affinity(declared: str) -> str:
    """SQLite's affinity of a column of this declared type (the rules of its "Datatypes" page)."""
    t = (declared or "").upper()
    if "INT" in t:
        return "INTEGER"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"
    if not t or "BLOB" in t:
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "REAL"
    return "NUMERIC"


def _stored(value: Any, affinity: str) -> Any:
    """What SQLite gives back of ``value`` written to a column of this affinity, for the plain values the store writes:
    a NaN is kept as NULL and -0.0 as this SQLite keeps it (``_NEG_ZERO``) in a REAL column, an integer there as a
    float.  ``_UNSURE`` for anything else (a float in an INTEGER column, a number in a TEXT one ...): such a row is read
    back from the file instead."""
    if value is None:
        return None
    t = type(value)
    if t is bool:
        value, t = int(value), int
    if affinity == "TEXT":
        return value if t is str else _UNSURE
    if affinity == "INTEGER":
        return value if t is int and -2 ** 63 <= value < 2 ** 63 else _UNSURE
    if affinity == "REAL":
        if t is int and -2 ** 53 <= value <= 2 ** 53:
            return float(value)
        if t is float:
            if value != value:
                return None
            return _NEG_ZERO if value == 0.0 and math.copysign(1.0, value) < 0 else value
    return _UNSURE


#: the columns of ``mpc_values`` as its readers get them
_MPC_VALUE_COLS = ("day", "meeting", "step", "level", "cum", "sigma", "front")
#: ... and the columns :meth:`Store.mpc_save` writes of ``mpc_days`` (all of them)
_MPC_DAY_COLS = ("day", "basis", "spot", "tlref", "base", "decision", "quotes", "status", "note", "computed_at", "control",
                 "tolerance", "carried", "cleaned")


def _put_day(days: List[str], day: str) -> None:
    k = bisect.bisect_left(days, day)
    if k == len(days) or days[k] != day:
        days.insert(k, day)


def _drop_day(days: List[str], day: str) -> None:
    k = bisect.bisect_left(days, day)
    if k < len(days) and days[k] == day:
        del days[k]


class Store(object):
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        # the history's tables in memory (the module's docstring): their own lock - a reader never waits for the file,
        # nor for another thread's query
        self._mem = threading.RLock()
        self._hist = _Daily()                                       # hist_values
        self._own = _Daily()                                        # watch_closes
        self._mpc_all: Dict[str, Dict[str, Any]] = {}               # mpc_days: day -> its row
        self._mpc_days: List[str] = []                              # ... its days, ascending
        self._mpc_rows: Dict[str, List[Tuple[Any, ...]]] = {}       # mpc_values: day -> its rows (by meeting)
        self._mpc_value_days: List[str] = []                        # ... its days, ascending
        self._kinds: Dict[str, Dict[str, str]] = {}                 # table -> column -> affinity (mpc_days / mpc_values)
        self._pending: List[Tuple[Callable[..., None], tuple]] = []  # changes waiting for their transaction's commit
        self._memory = False                                        # the tables are in memory (not when the file is damaged)
        # what the history pages and the settings page poll, kept until the closes change
        self._bounds: Optional[Dict[str, Tuple[str, str, int]]] = None
        # told after every write of the inputs: (the user - None for the shared inputs, "*" for every user -, whether
        # formulas were written); the inputs' formulas (inputformula.py) follow what any writer did to their cells
        self.on_inputs: Optional[Any] = None
        # a data folder on a network drive (the module's text): the rollback journal, and a writer waits up to 30 s for
        # a reader holding the file (the nightly backup copies it in one step) - with WAL readers never hold a writer
        self.network = path != ":memory:" and datadir.on_network_drive(path)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30.0 if self.network else 5.0)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            #: the journal mode the file runs with ("wal", "delete"; "memory" for ":memory:")
            self.journal_mode = str(self._db.execute("PRAGMA journal_mode=%s" % ("DELETE" if self.network else "WAL"))
                                    .fetchone()[0]).lower()
            # every commit waits until the write-ahead log is on the disk (NORMAL leaves the last commits to the next
            # checkpoint: a power cut could take back a trade the blotter had shown as entered).  Measured on the desk
            # machine with commits like the dashboard's: ~0.6-1.1 ms a commit (p99 ~4 ms) against ~0.03 ms - the
            # dashboard commits a few times a second at most, so for every table rather than for the trades alone
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
            for table, columns in _ADDED_COLUMNS.items():
                added = self._add_columns(table, columns)
                if table == "users" and "last_login" in added:
                    # until then "last seen" was written at a sign-in only: it is the last sign-in of every account that
                    # signed in after it was made (one made and never signed in keeps its creation time there)
                    self._db.execute("UPDATE users SET last_login = last_seen WHERE last_seen > created_at")
            self._load_memory()

    def _load_memory(self) -> None:
        """The history's tables into memory: once, as the file is opened - before any other thread uses the store (the
        desk's ~175 000 closes in ~0.5 s; read while a calculation ran, row by row, they would take minutes).  A
        damaged file still opens (its check says so, loud: ``ops.check_database``): its history is read from the file
        then, as before."""
        hist, own = _Daily(), _Daily()
        try:
            cur = self._db.cursor()
            cur.row_factory = None                                  # (plain tuples: the fastest read)
            hist.load(cur.execute("SELECT series, day, value FROM hist_values ORDER BY series, day"))
            own.load(cur.execute("SELECT subject, day, value FROM watch_closes ORDER BY subject, day"))
            kinds = {t: {r[1]: _affinity(r[2]) for r in cur.execute("PRAGMA table_info(%s)" % t)}
                     for t in ("mpc_days", "mpc_values")}
            cur.row_factory = sqlite3.Row
            days = {r["day"]: dict(r) for r in cur.execute("SELECT * FROM mpc_days ORDER BY day")}
            cur.row_factory = None
            rows = {day: list(group) for day, group in itertools.groupby(
                cur.execute("SELECT %s FROM mpc_values ORDER BY day, meeting" % ", ".join(_MPC_VALUE_COLS)), key=lambda r: r[0])}
        except sqlite3.DatabaseError:
            self._memory = False
            return
        with self._mem:
            self._hist, self._own, self._kinds = hist, own, kinds
            self._mpc_all, self._mpc_days = days, list(days)
            self._mpc_rows, self._mpc_value_days = rows, list(rows)
            self._bounds = None
            self._memory = True

    def _later(self, fn: Callable[..., None], *args: Any) -> None:
        """A change of the tables in memory, after a write of the file (the caller holds ``_lock``): now - or, inside a
        transaction, when it is committed (a rollback takes it back with the write)."""
        if not self._memory:
            return
        if self._db.in_transaction:
            self._pending.append((fn, args))
            return
        self._apply([(fn, args)])

    def _apply(self, changes: List[Tuple[Callable[..., None], tuple]]) -> None:
        """Changes of the tables in memory, in order.  One that fails (a value of a kind no writer gives) has the copy read
        again from the file: it never goes on differing from it."""
        with self._mem:
            try:
                for fn, args in changes:
                    fn(*args)
            except Exception:  # noqa: BLE001 - the write itself is committed: only the copy is in question
                self._load_memory()

    def _add_columns(self, table: str, columns) -> List[str]:
        """Columns that came after a table was first created (a database of an earlier version keeps its rows): the
        ones added now."""
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(%s)" % table).fetchall()}
        added = []
        for name, kind in columns:
            if name not in have:
                self._db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, kind))
                added.append(name)
        return added

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One transaction: what is written inside lands together or - on any error - not at all.  A write inside
        another one's transaction joins it."""
        with self._lock:
            if self._db.in_transaction:
                yield self._db
                return
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                del self._pending[:]                    # (the tables in memory: what the rollback took back)
                raise
            done, self._pending = self._pending, []
            if done:
                self._apply(done)

    # ------------------------------------------------------------------ the file itself: its check, its copy
    def quick_check(self, limit: int = 20) -> List[str]:
        """SQLite's own check of the file (``PRAGMA quick_check``): ``[]`` when it is sound, else what it found."""
        try:
            found = [str(r[0]) for r in self._q("PRAGMA quick_check(%d)" % int(limit))]
        except sqlite3.DatabaseError as exc:
            return ["%s: %s" % (type(exc).__name__, exc)]
        return [] if found == ["ok"] else found

    def backup_to(self, path: str) -> Dict[str, Any]:
        """An online copy of the database at ``path`` (SQLite's backup API: one consistent state, while the dashboard
        goes on writing).  The copy is checked before it takes its name; an existing file of that name is replaced
        only then.  Returns the path, its size and how long it took."""
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        part = path + ".part"
        if os.path.exists(part):
            os.remove(part)
        t0 = time.time()
        try:
            dst = sqlite3.connect(part)
            try:
                if self.path == ":memory:":
                    with self._lock:
                        self._db.backup(dst)
                else:
                    src = sqlite3.connect(self.path, timeout=30.0)
                    try:
                        src.backup(dst)              # in one step: the reader sees one committed state throughout
                    finally:
                        src.close()
                # one self-contained file (the copy would otherwise keep the write-ahead mode and grow -wal / -shm
                # files next to it whenever it is opened): what is copied off the machine is the whole backup
                dst.execute("PRAGMA journal_mode=DELETE")
                found = [str(r[0]) for r in dst.execute("PRAGMA quick_check(5)").fetchall()]
            finally:
                dst.close()
            if found != ["ok"]:
                raise sqlite3.DatabaseError("yedeğin denetimi başarısız: %s" % "; ".join(found))
        except BaseException:
            for leftover in (part, part + "-journal"):    # a copy that is not sound is not kept, half or whole
                if os.path.exists(leftover):
                    os.remove(leftover)
            raise
        os.replace(part, path)
        return {"path": path, "bytes": os.path.getsize(path), "seconds": round(time.time() - t0, 2)}

    def _q(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            return cur.lastrowid

    # ------------------------------------------------------------------ users
    def login(self, name: str) -> Dict[str, Any]:
        display = " ".join(name.strip().split())
        if not display:
            raise ValueError("isim boş olamaz")
        if len(display) > 40:
            raise ValueError("isim en fazla 40 karakter olabilir")
        key = user_key(display)
        ts = now_iso()
        rows = self._q("SELECT * FROM users WHERE name=?", (key,))
        if rows:
            self._x("UPDATE users SET last_seen=? WHERE name=?", (ts, key))
            return {"user": key, "display": rows[0]["display"], "new": False}
        self._x("INSERT INTO users (name, display, created_at, last_seen) VALUES (?,?,?,?)", (key, display, ts, ts))
        return {"user": key, "display": display, "new": True}

    def users(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT name, display, created_at, last_seen FROM users ORDER BY display")]

    def user_exists(self, key: str) -> bool:
        return bool(self._q("SELECT 1 FROM users WHERE name=?", (key,)))

    # ------------------------------------------------------------------ accounts and sessions (sign-in)
    def account(self, key: str) -> Optional[Dict[str, Any]]:
        """Everything kept of a user, the password hash included (for the sign-in itself only)."""
        rows = self._q("SELECT * FROM users WHERE name=?", (key,))
        return dict(rows[0]) if rows else None

    def accounts(self) -> List[Dict[str, Any]]:
        """Every account as the administrators see it - never a password hash - with how much each user has kept
        (personal inputs and scenarios: what a request for an existing name would take over)."""
        rows = self._q("SELECT u.name, u.display, u.created_at, u.last_seen, u.last_login, u.last_login_ip, u.role, u.status, "
                       "u.note, u.requested_at, u.decided_by, u.decided_at, u.locked_until, u.requested_new, "
                       "u.pw_hash IS NOT NULL AS has_password, "
                       "(SELECT COUNT(*) FROM user_inputs i WHERE i.user = u.name) AS inputs, "
                       "(SELECT COUNT(*) FROM scenarios s WHERE s.user = u.name) AS scenarios "
                       "FROM users u ORDER BY u.display")
        return [dict(r, has_password=bool(r["has_password"]), requested_new=bool(r["requested_new"])) for r in rows]

    def create_account(self, display: str, pw_hash: Optional[str], role: str = "user", status: str = "active",
                       note: Optional[str] = None, by: Optional[str] = None) -> str:
        """A new account; one made waiting for approval is a request for a new name (``requested_new``: rejected,
        nothing of it is kept)."""
        key = user_key(display)
        ts = now_iso()
        pending = status == "pending"
        self._x("INSERT INTO users (name, display, created_at, last_seen, pw_hash, role, status, note, requested_at, "
                "decided_by, decided_at, requested_new) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, display, ts, ts, pw_hash, role, status, note, ts if pending else None, by, ts if by else None,
                 1 if pending else 0))
        return key

    def update_account(self, key: str, **fields: Any) -> None:
        unknown = set(fields) - set(_ACCOUNT_FIELDS)
        if unknown:
            raise ValueError("bilinmeyen alan: %s" % ", ".join(sorted(unknown)))
        if fields:
            sets = ", ".join("%s=?" % name for name in fields)
            self._x("UPDATE users SET %s WHERE name=?" % sets, tuple(fields.values()) + (key,))

    def delete_account(self, key: str) -> None:
        with self.transaction() as db:               # the sessions and the account together, or neither
            db.execute("DELETE FROM sessions WHERE user=?", (key,))
            db.execute("DELETE FROM users WHERE name=?", (key,))

    def admins(self) -> List[str]:
        """The administrators who can sign in (active, with a password)."""
        return [r["name"] for r in self._q("SELECT name FROM users WHERE role='admin' AND status='active' "
                                           "AND pw_hash IS NOT NULL ORDER BY name")]

    def pending_count(self) -> int:
        return int(self._q("SELECT COUNT(*) AS n FROM users WHERE status='pending'")[0]["n"])

    def add_session(self, token_hash: str, user: str, expires_at: str, ip: Optional[str] = None) -> None:
        self._x("INSERT INTO sessions (token, user, created_at, expires_at, ip) VALUES (?,?,?,?,?)",
                (token_hash, user, now_iso(), expires_at, ip))

    def session_user(self, token_hash: str, now: str) -> Optional[str]:
        """The user of a session that has not expired, while the account is active."""
        rows = self._q("SELECT s.user FROM sessions s JOIN users u ON u.name = s.user "
                       "WHERE s.token=? AND s.expires_at>? AND u.status='active'", (token_hash, now))
        return rows[0]["user"] if rows else None

    def drop_session(self, token_hash: str) -> None:
        self._x("DELETE FROM sessions WHERE token=?", (token_hash,))

    def drop_sessions(self, user: str, keep: Optional[str] = None) -> None:
        """End the user's sessions - all, or all but ``keep`` (a token hash: the page that asked)."""
        if keep:
            self._x("DELETE FROM sessions WHERE user=? AND token<>?", (user, keep))
        else:
            self._x("DELETE FROM sessions WHERE user=?", (user,))

    def count_attempt(self, key: str, now: str) -> Tuple[int, Optional[str]]:
        """One more sign-in attempt on a name, counted before its password is checked - in one step with the look at
        the lock, so guesses sent at once each take their own turn: ``(attempts in a row now, None)``, or
        ``(0, locked until)`` while the name is locked."""
        with self._lock:
            row = self._db.execute("SELECT failed, locked_until FROM users WHERE name=?", (key,)).fetchone()
            if row is None:
                return 0, None
            if row["locked_until"] and row["locked_until"] > now:
                return 0, row["locked_until"]
            self._db.execute("UPDATE users SET failed = COALESCE(failed, 0) + 1 WHERE name=?", (key,))
            return int(row["failed"] or 0) + 1, None

    def purge_sessions(self, now: str) -> None:
        self._x("DELETE FROM sessions WHERE expires_at<=?", (now,))

    # ------------------------------------------------------------------ who is at the desk (presence.py)
    def desk_users(self) -> List[Dict[str, Any]]:
        """The desk's users as the list of who is online shows them: the active accounts that can sign in (a request
        waiting for approval, a closed account and one of the earlier version without a password are none)."""
        return [dict(r) for r in self._q("SELECT name, display, created_at, last_seen, last_login FROM users "
                                         "WHERE status='active' AND pw_hash IS NOT NULL ORDER BY display")]

    def set_last_seen(self, items: Sequence[Tuple[str, str]]) -> None:
        """Users' "last seen" (``(user, stamp)`` pairs), in one transaction - never moved back."""
        with self.transaction() as db:
            db.executemany("UPDATE users SET last_seen=? WHERE name=? AND last_seen<?", [(s, u, s) for u, s in items])

    # ------------------------------------------------------------------ personal inputs
    def _told(self, user: Optional[str], formulas: bool) -> None:
        hook = self.on_inputs
        if hook is not None:
            hook(user, formulas)

    def user_inputs(self, user: str, book: Optional[str] = None) -> Dict[Tuple[str, str], Any]:
        if book is None:
            rows = self._q("SELECT book, cell, value FROM user_inputs WHERE user=?", (user,))
        else:
            rows = self._q("SELECT book, cell, value FROM user_inputs WHERE user=? AND book=?", (user, book))
        return {(r["book"], r["cell"]): json.loads(r["value"]) for r in rows}

    def user_formulas(self, user: str, book: Optional[str] = None) -> Dict[Tuple[str, str], str]:
        """The user's inputs typed as a formula: (book, cell) -> its text (``=C60+7``)."""
        if book is None:
            rows = self._q("SELECT book, cell, formula FROM user_inputs WHERE user=? AND formula IS NOT NULL", (user,))
        else:
            rows = self._q("SELECT book, cell, formula FROM user_inputs WHERE user=? AND book=? AND formula IS NOT NULL",
                           (user, book))
        return {(r["book"], r["cell"]): r["formula"] for r in rows}

    def input_times(self, user: Optional[str] = None) -> Dict[Tuple[str, str], Tuple[str, Optional[str]]]:
        """When each input was typed last: (book, cell) -> (``updated_at``, who) - a user's personal inputs, or with
        ``user`` None the desk's (shared) ones, who typed each (the shell's "Girdilerim" and its "dünden" marks)."""
        if user is None:
            rows = self._q("SELECT book, cell, updated_at, updated_by FROM shared_inputs")
            return {(r["book"], r["cell"]): (r["updated_at"], r["updated_by"]) for r in rows}
        rows = self._q("SELECT book, cell, updated_at FROM user_inputs WHERE user=?", (user,))
        return {(r["book"], r["cell"]): (r["updated_at"], None) for r in rows}

    def formula_users(self) -> List[str]:
        """The users who keep an input typed as a formula."""
        return [r["user"] for r in self._q("SELECT DISTINCT user FROM user_inputs WHERE formula IS NOT NULL")]

    def drop_formulas(self, user: Optional[str], cells: List[Tuple[str, str]]) -> None:
        """Formulas of inputs that may not hold one any more (``user``: theirs; None: the desk's): each cell keeps its
        value, as a value."""
        with self._lock:
            if user is None:
                self._db.executemany("UPDATE shared_inputs SET formula=NULL WHERE book=? AND cell=?", list(cells))
            else:
                self._db.executemany("UPDATE user_inputs SET formula=NULL WHERE user=? AND book=? AND cell=?",
                                     [(user, b, c) for b, c in cells])

    def users_with_inputs(self) -> List[str]:
        """The users who keep personal inputs (their pages are their own)."""
        return [r["user"] for r in self._q("SELECT DISTINCT user FROM user_inputs")]

    def saved_cells(self) -> List[Tuple[str, str]]:
        """Every (book, cell) any user keeps a value of: personal inputs and the cells of saved scenarios."""
        out = {(r["book"], r["cell"]) for r in self._q("SELECT DISTINCT book, cell FROM user_inputs")}
        for r in self._q("SELECT payload FROM scenarios"):
            try:
                out.update((x[0], x[1]) for x in json.loads(r["payload"]))
            except (TypeError, ValueError, IndexError):
                continue
        return sorted(out)

    def set_user_inputs(self, user: str, book: str, values: Dict[str, Any],
                        formulas: Optional[Dict[str, str]] = None) -> None:
        """Values of the user's inputs; ``formulas``: the cells among them typed as a formula (cell -> its text) - every
        other cell written is a plain value (a formula it had goes)."""
        ts = now_iso()
        formulas = formulas or {}
        with self.transaction() as db:
            for cell, v in values.items():
                db.execute(
                    "INSERT INTO user_inputs (user, book, cell, value, updated_at, formula) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(user, book, cell) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
                    "formula=excluded.formula", (user, book, cell, json.dumps(v, ensure_ascii=False), ts, formulas.get(cell)))
        self._told(user, bool(formulas))

    def clear_user_inputs(self, user: str, book: Optional[str] = None, cells: Optional[List[str]] = None) -> None:
        with self._lock:
            if cells is not None:
                self._db.executemany("DELETE FROM user_inputs WHERE user=? AND book=? AND cell=?",
                                     [(user, book, c) for c in cells])
            elif book is not None:
                self._db.execute("DELETE FROM user_inputs WHERE user=? AND book=?", (user, book))
            else:
                self._db.execute("DELETE FROM user_inputs WHERE user=?", (user,))
        self._told(user, False)

    def replace_user_inputs(self, user: str, values: Dict[Tuple[str, str], Any],
                            formulas: Optional[Dict[Tuple[str, str], str]] = None) -> None:
        ts = now_iso()
        formulas = formulas or {}
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("DELETE FROM user_inputs WHERE user=?", (user,))
                self._db.executemany(
                    "INSERT INTO user_inputs (user, book, cell, value, updated_at, formula) VALUES (?,?,?,?,?,?)",
                    [(user, b, c, json.dumps(v, ensure_ascii=False), ts, formulas.get((b, c))) for (b, c), v in values.items()])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        self._told(user, True)

    def input_stamp(self, user: str, book: str, cells: List[str]) -> Optional[str]:
        """When the user last wrote any of these inputs (``"2026-11-28 09:12:33"``; ``None``: they hold none of them) -
        DV01 Risk's "yapıştırıldı" (one row back: SQLite takes the latest, indexed by user, book and cell)."""
        stamps = []
        cells = list(cells)
        for i in range(0, len(cells), 400):
            chunk = cells[i:i + 400]
            rows = self._q("SELECT MAX(updated_at) AS at FROM user_inputs WHERE user=? AND book=? AND cell IN (%s)"
                           % ",".join("?" for _ in chunk), (user, book) + tuple(chunk))
            if rows and rows[0]["at"]:
                stamps.append(rows[0]["at"])
        return max(stamps) if stamps else None

    # ------------------------------------------------------------------ named scenarios
    def scenarios(self, user: str) -> List[Dict[str, Any]]:
        rows = self._q("SELECT id, name, payload, created_at, updated_at FROM scenarios WHERE user=? ORDER BY name", (user,))
        out = []
        for r in rows:
            out.append({"id": r["id"], "name": r["name"], "created_at": r["created_at"], "updated_at": r["updated_at"],
                        "cells": len(json.loads(r["payload"]))})
        return out

    def save_scenario(self, user: str, name: str, values: Dict[Tuple[str, str], Any],
                      formulas: Optional[Dict[Tuple[str, str], str]] = None) -> Dict[str, Any]:
        """``values``: (book, cell) -> value; ``formulas``: the cells typed as a formula (kept as a fourth item beside the
        value - a scenario of an earlier version has three)."""
        name = " ".join(name.strip().split())
        if not name:
            raise ValueError("senaryo adı boş olamaz")
        if len(name) > 60:
            raise ValueError("senaryo adı en fazla 60 karakter olabilir")
        formulas = formulas or {}
        payload = json.dumps([[b, c, v, formulas[(b, c)]] if (b, c) in formulas else [b, c, v]
                              for (b, c), v in sorted(values.items())], ensure_ascii=False)
        ts = now_iso()
        self._x("INSERT INTO scenarios (user, name, payload, created_at, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(user, name) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (user, name, payload, ts, ts))
        return {"name": name, "cells": len(values), "updated_at": ts}

    def load_scenario(self, user: str, name: str) -> Optional[Dict[Tuple[str, str], Any]]:
        got = self.scenario(user, name)
        return None if got is None else got[0]

    def scenario(self, user: str, name: str) -> Optional[Tuple[Dict[Tuple[str, str], Any], Dict[Tuple[str, str], str]]]:
        """A saved scenario: (its values, the formulas among them)."""
        rows = self._q("SELECT payload FROM scenarios WHERE user=? AND name=?", (user, name))
        if not rows:
            return None
        values: Dict[Tuple[str, str], Any] = {}
        formulas: Dict[Tuple[str, str], str] = {}
        for x in json.loads(rows[0]["payload"]):
            values[(x[0], x[1])] = x[2]
            if len(x) > 3 and isinstance(x[3], str):
                formulas[(x[0], x[1])] = x[3]
        return values, formulas

    def delete_scenario(self, user: str, name: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM scenarios WHERE user=? AND name=?", (user, name))
            return cur.rowcount > 0

    # ------------------------------------------------------------------ values that follow what their row is about
    def move_values(self, book: str, where: Callable[[str], Any], users: Optional[List[str]] = None, shared: bool = True,
                    scenarios: bool = True, keys: Optional[Dict[str, Any]] = None, key_clears: Sequence[str] = (),
                    key_user: Optional[str] = None, by: Optional[str] = None, put: Sequence[Tuple[str, Any]] = (),
                    seed: Optional[Dict[str, Any]] = None, blank: Any = ()) -> Dict[str, Any]:
        """The values of a list's rows follow what each row is about (a bond, by its ISIN): one transaction, for every
        user.  ``where(cell)`` says where a stored value of ``book`` goes - its new cell, ``None`` (it goes) or False (it
        stays) - for each user's values (``users``: theirs alone; None: everybody's), the desk's (``shared``) and the saved
        scenarios' (``scenarios``).  A value moved onto a cell that holds one does not replace it (a bond listed twice: what
        it has on its other row stands; of two moved onto one cell the upper row's), and keeps no formula (its references
        would not move with it).  The desk's: ``seed`` - the workbook's own values of cells that go with their row, taken
        as the desk's first (a pricing source the file has for the bond on that row); ``blank`` - cells whose value, once
        it went, is a blank, not the workbook's own (the file's value was the bond's that left).  With them, in the same
        transaction: the key cells written (``keys``: cell -> value as stored, ``key_clears``: cells whose stored value
        goes - ``key_user``'s, None: the desk's) and ``put`` (key / value pairs).  Returns what moved and what went, value
        by value: ``{"moved": [(user, cell, new cell, value)], "dropped": [(user, cell)], "blanked": [cell], "scenarios":
        scenarios changed, "scenario_moved": n, "scenario_dropped": n, "scenario_cells_moved" / "scenario_cells_dropped":
        [cell, ...]}`` (user None: the desk's)."""
        ts = now_iso()
        moved: List[Tuple[Optional[str], str, str, Any]] = []
        dropped: List[Tuple[Optional[str], str]] = []
        blanked: List[str] = []
        sc_cells_moved: List[str] = []
        sc_cells_dropped: List[str] = []
        sc_moved = sc_dropped = touched = 0
        formulas = False
        with self.transaction() as db:
            if users is None:
                mine = db.execute("SELECT user, cell, value, formula FROM user_inputs WHERE book=?", (book,)).fetchall()
            else:
                mine = [r for u in users for r in db.execute(
                    "SELECT user, cell, value, formula FROM user_inputs WHERE book=? AND user=?", (book, u)).fetchall()]
            if shared:
                for cell, v in (seed or {}).items():
                    db.execute("INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at) VALUES (?,?,?,NULL,?) "
                               "ON CONFLICT(book, cell) DO NOTHING", (book, cell, json.dumps(v, ensure_ascii=False), ts))
            desk = db.execute("SELECT cell, value, formula, updated_by FROM shared_inputs WHERE book=?", (book,)).fetchall() \
                if shared else []
            go = sorted(((r, where(r["cell"])) for r in mine), key=lambda x: (x[0]["user"], _cell_order(x[0]["cell"])))
            go = [(r, w) for r, w in go if w is not False]
            for r, _ in go:
                db.execute("DELETE FROM user_inputs WHERE user=? AND book=? AND cell=?", (r["user"], book, r["cell"]))
                formulas = formulas or r["formula"] is not None
            for r, w in go:
                if w is not None and db.execute(
                        "INSERT INTO user_inputs (user, book, cell, value, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(user, book, cell) DO NOTHING", (r["user"], book, w, r["value"], ts)).rowcount:
                    moved.append((r["user"], r["cell"], w, json.loads(r["value"])))
                else:
                    dropped.append((r["user"], r["cell"]))
            go = sorted(((r, where(r["cell"])) for r in desk), key=lambda x: _cell_order(x[0]["cell"]))
            go = [(r, w) for r, w in go if w is not False]
            for r, _ in go:
                db.execute("DELETE FROM shared_inputs WHERE book=? AND cell=?", (book, r["cell"]))
                formulas = formulas or r["formula"] is not None
            for r, w in go:
                if w is not None and db.execute(
                        "INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(book, cell) DO NOTHING", (book, w, r["value"], r["updated_by"], ts)).rowcount:
                    moved.append((None, r["cell"], w, json.loads(r["value"])))
                else:
                    dropped.append((None, r["cell"]))
            for r, _ in go:
                if r["cell"] in blank and db.execute(
                        "INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at) VALUES (?,?,'null',NULL,?) "
                        "ON CONFLICT(book, cell) DO NOTHING", (book, r["cell"], ts)).rowcount:
                    blanked.append(r["cell"])
            if scenarios:
                rows = db.execute("SELECT id, user, payload FROM scenarios").fetchall()
                for r in rows:
                    if users is not None and r["user"] not in users:
                        continue
                    keep, go_sc, changed = [], [], False
                    for x in json.loads(r["payload"]):
                        w = where(x[1]) if x[0] == book else False
                        if w is False:
                            keep.append(list(x))
                            continue
                        changed = True
                        if w is None:
                            sc_dropped += 1
                            sc_cells_dropped.append(x[1])
                        else:
                            go_sc.append((_cell_order(x[1]), x[1], [x[0], w, x[2]]))
                    if not changed:
                        continue
                    have = {(x[0], x[1]) for x in keep}
                    for _, source, x in sorted(go_sc, key=lambda y: y[0]):
                        if (x[0], x[1]) in have:
                            sc_dropped += 1
                            sc_cells_dropped.append(source)
                            continue
                        have.add((x[0], x[1]))
                        keep.append(x)
                        sc_moved += 1
                        sc_cells_moved.append(source)
                    touched += 1
                    db.execute("UPDATE scenarios SET payload=?, updated_at=? WHERE id=?",
                               (json.dumps(sorted(keep, key=lambda x: (x[0], x[1])), ensure_ascii=False), ts, r["id"]))
            for cell, v in (keys or {}).items():
                if key_user is None:
                    db.execute("INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at, formula) VALUES (?,?,?,?,?,NULL) "
                               "ON CONFLICT(book, cell) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, "
                               "updated_at=excluded.updated_at, formula=NULL", (book, cell, json.dumps(v, ensure_ascii=False), by, ts))
                else:
                    db.execute("INSERT INTO user_inputs (user, book, cell, value, updated_at, formula) VALUES (?,?,?,?,?,NULL) "
                               "ON CONFLICT(user, book, cell) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
                               "formula=NULL", (key_user, book, cell, json.dumps(v, ensure_ascii=False), ts))
            for cell in key_clears:
                if key_user is None:
                    db.execute("DELETE FROM shared_inputs WHERE book=? AND cell=?", (book, cell))
                else:
                    db.execute("DELETE FROM user_inputs WHERE user=? AND book=? AND cell=?", (key_user, book, cell))
            for key, value in put:
                db.execute("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (key, json.dumps(value, ensure_ascii=False)))
        if moved or dropped or keys or key_clears:
            self._told("*", formulas)
            self._told(None, formulas)
        return {"moved": moved, "dropped": dropped, "blanked": blanked, "scenarios": touched, "scenario_moved": sc_moved,
                "scenario_dropped": sc_dropped, "scenario_cells_moved": sc_cells_moved,
                "scenario_cells_dropped": sc_cells_dropped}

    # ------------------------------------------------------------------ shared inputs
    def shared_inputs(self, book: Optional[str] = None) -> Dict[Tuple[str, str], Any]:
        if book is None:
            rows = self._q("SELECT book, cell, value FROM shared_inputs")
        else:
            rows = self._q("SELECT book, cell, value FROM shared_inputs WHERE book=?", (book,))
        return {(r["book"], r["cell"]): json.loads(r["value"]) for r in rows}

    def shared_formulas(self, book: Optional[str] = None) -> Dict[Tuple[str, str], str]:
        """The desk's inputs typed as a formula: (book, cell) -> its text."""
        if book is None:
            rows = self._q("SELECT book, cell, formula FROM shared_inputs WHERE formula IS NOT NULL")
        else:
            rows = self._q("SELECT book, cell, formula FROM shared_inputs WHERE book=? AND formula IS NOT NULL", (book,))
        return {(r["book"], r["cell"]): r["formula"] for r in rows}

    def shared_meta(self, book: str, cells: List[str]) -> Optional[Dict[str, Any]]:
        """Who changed any of the cells last, and when."""
        if not cells:
            return None
        marks = ",".join("?" for _ in cells)
        rows = self._q("SELECT updated_by, updated_at FROM shared_inputs WHERE book=? AND cell IN (%s) "
                       "ORDER BY updated_at DESC LIMIT 1" % marks, (book,) + tuple(cells))
        return dict(rows[0]) if rows else None

    def set_shared_inputs(self, book: str, values: Dict[str, Any], user: Optional[str],
                          formulas: Optional[Dict[str, str]] = None) -> None:
        """The desk's values of inputs; ``formulas`` as for :meth:`set_user_inputs`."""
        ts = now_iso()
        formulas = formulas or {}
        with self.transaction() as db:
            for cell, v in values.items():
                db.execute(
                    "INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at, formula) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(book, cell) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, "
                    "updated_at=excluded.updated_at, formula=excluded.formula",
                    (book, cell, json.dumps(v, ensure_ascii=False), user, ts, formulas.get(cell)))
        self._told(None, bool(formulas))

    def clear_shared_inputs(self, book: str, cells: List[str]) -> None:
        with self._lock:
            self._db.executemany("DELETE FROM shared_inputs WHERE book=? AND cell=?", [(book, c) for c in cells])
        self._told(None, False)

    # ------------------------------------------------------------------ RET curve history
    def add_ret_history(self, user: Optional[str], rows: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> int:
        """An upload of the RET curve: its rows and (``meta``) what it changed per tenor against the curve before it."""
        return self._x("INSERT INTO ret_history (ts, user, payload, meta) VALUES (?,?,?,?)",
                       (now_iso(), user, json.dumps(rows, ensure_ascii=False),
                        json.dumps(meta, ensure_ascii=False) if meta else None))

    def note_ret_history(self, hid: int, fields: Dict[str, Any]) -> None:
        """More about an upload already written (where it came from: "Kopyala ve yayınla", a scenario)."""
        with self._lock:
            got = self._q("SELECT meta FROM ret_history WHERE id=?", (hid,))
            if not got:
                return
            meta = json.loads(got[0]["meta"]) if got[0]["meta"] else {}
            meta.update(fields)
            self._x("UPDATE ret_history SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), hid))

    def ret_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._q("SELECT id, ts, user, payload, meta FROM ret_history ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            entry = {"id": r["id"], "ts": r["ts"], "user": r["user"], "rows": json.loads(r["payload"])}
            if r["meta"]:
                entry.update(json.loads(r["meta"]))          # "changes" (per tenor, bp), "source"
            out.append(entry)
        return out

    # ------------------------------------------------------------------ the fair value RET's changes (retfair.py)
    def add_ret_fair_log(self, user: Optional[str], kind: str, text: str) -> int:
        """Who changed what of the fair value RET (an offset, a base, a flow adjustment, a setting, a publish) and when."""
        return self._x("INSERT INTO ret_fair_log (ts, user, kind, text) VALUES (?,?,?,?)", (now_iso(), user, kind, text))

    def ret_fair_log(self, limit: int = 40) -> List[Dict[str, Any]]:
        rows = self._q("SELECT id, ts, user, kind, text FROM ret_fair_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ blotter
    def add_trade(self, trade_date: str, kind: str, payload: Dict[str, Any], user: Optional[str],
                  package: Optional[str] = None) -> int:
        ts = now_iso()
        return self._x("INSERT INTO trades (trade_date, kind, package, payload, created_by, created_at, updated_by, "
                       "updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       (trade_date, kind, package, json.dumps(payload, ensure_ascii=False), user, ts, user, ts))

    def add_trades(self, trade_date: str, kind: str, payloads: List[Dict[str, Any]], user: Optional[str],
                   package: Optional[str] = None) -> List[int]:
        """The legs of a package in one transaction: all of them are kept, or - on any error - none."""
        with self.transaction():
            return [self.add_trade(trade_date, kind, p, user, package) for p in payloads]

    def add_trade_batch(self, trade_date: str, items: List[Tuple[str, Dict[str, Any], Optional[str]]],
                        user: Optional[str]) -> List[int]:
        """Trades of any kind - ``(kind, payload, package)`` each, rows pasted at once - in one transaction: all of
        them are kept, or - on any error - none."""
        with self.transaction():
            return [self.add_trade(trade_date, kind, p, user, package) for kind, p, package in items]

    def update_trade(self, trade_id: int, payload: Dict[str, Any], user: Optional[str]) -> bool:
        return bool(self.update_trades([(trade_id, payload)], user))

    def update_trades(self, items: Sequence[Tuple[int, Dict[str, Any]]], user: Optional[str]) -> List[int]:
        """Trades changed in place - the legs of a package together - in one transaction: the same ids, new payloads,
        ``updated_by`` / ``updated_at`` set (the day, who entered it and when stay).  All of them, or - when one of them
        is not there (deleted meanwhile) - none: returns the ids changed (``[]`` then)."""
        ts = now_iso()
        try:
            with self.transaction() as db:
                for tid, payload in items:
                    cur = db.execute("UPDATE trades SET payload=?, updated_by=?, updated_at=? WHERE id=? AND deleted=0",
                                     (json.dumps(payload, ensure_ascii=False), user, ts, tid))
                    if cur.rowcount != 1:
                        raise LookupError(tid)              # (the transaction is rolled back)
        except LookupError:
            return []
        return [tid for tid, _ in items]

    def delete_trade(self, trade_id: int, user: Optional[str]) -> List[int]:
        """Soft-delete a trade (and the other legs of its package, in the same transaction: a package is never left
        half deleted); returns the ids removed."""
        with self.transaction() as db:
            rows = db.execute("SELECT id, package FROM trades WHERE id=? AND deleted=0", (trade_id,)).fetchall()
            if not rows:
                return []
            pkg = rows[0]["package"]
            if pkg:
                ids = [r["id"] for r in db.execute("SELECT id FROM trades WHERE package=? AND deleted=0", (pkg,)).fetchall()]
            else:
                ids = [trade_id]
            ts = now_iso()
            db.executemany("UPDATE trades SET deleted=1, updated_by=?, updated_at=? WHERE id=?", [(user, ts, i) for i in ids])
            return ids

    def trades(self, trade_date: str, until: Optional[str] = None) -> List[Dict[str, Any]]:
        """The trades of a day, or of every day from ``trade_date`` to ``until`` (both included), oldest first."""
        if until is None or until == trade_date:
            rows = self._q("SELECT * FROM trades WHERE trade_date=? AND deleted=0 ORDER BY id", (trade_date,))
        else:
            rows = self._q("SELECT * FROM trades WHERE trade_date>=? AND trade_date<=? AND deleted=0 ORDER BY trade_date, id",
                           (trade_date, until))
        return [self._trade_row(r) for r in rows]

    def trade_legs(self, trade_id: int) -> List[Dict[str, Any]]:
        """A trade as it is kept: the legs of its package (oldest first) or the trade alone; ``[]`` when there is none."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM trades WHERE id=? AND deleted=0", (trade_id,)).fetchall()
            if rows and rows[0]["package"]:
                rows = self._db.execute("SELECT * FROM trades WHERE package=? AND deleted=0 ORDER BY id", (rows[0]["package"],)).fetchall()
        return [self._trade_row(r) for r in rows]

    @staticmethod
    def _trade_row(r) -> Dict[str, Any]:
        """A row of ``trades`` as the blotter reads it: the trade's record with the row's own columns."""
        d = json.loads(r["payload"])
        d.update({"id": r["id"], "kind": r["kind"], "package": r["package"], "trade_date": r["trade_date"],
                  "created_by": r["created_by"], "created_at": r["created_at"],
                  "updated_by": r["updated_by"], "updated_at": r["updated_at"]})
        return d

    # ------------------------------------------------------------------ broker chat
    def add_broker_quotes(self, rows: List[Dict[str, Any]], user: Optional[str]) -> Tuple[List[int], int]:
        """Keep what a broker chat said: one row per quote (or line).  A row that is already there - the same
        day, time, sender, text and reading, as when the same stretch of chat is pasted again - is skipped.
        Returns (ids of the new rows, number skipped).  One paste is one transaction: a row that cannot be kept
        leaves none of the paste behind (pasted again, it is all new)."""
        ids: List[int] = []
        skipped = 0
        ts = now_iso()
        with self.transaction() as db:
            for row in rows:
                day, at, mark = row["date"], row["time"], row["mark"]
                found = db.execute("SELECT id FROM broker_quotes WHERE quote_date=? AND quote_time=? AND mark=? AND deleted=0",
                                   (day, at, mark)).fetchone()
                if found:
                    skipped += 1
                    continue
                cur = db.execute("INSERT INTO broker_quotes (quote_date, quote_time, mark, payload, created_by, created_at) "
                                 "VALUES (?,?,?,?,?,?)", (day, at, mark, json.dumps(row, ensure_ascii=False), user, ts))
                ids.append(cur.lastrowid)
        return ids, skipped

    def broker_marks(self, day: str) -> set:
        rows = self._q("SELECT quote_time, mark FROM broker_quotes WHERE quote_date=? AND deleted=0", (day,))
        return {(r["quote_time"], r["mark"]) for r in rows}

    def broker_quotes(self, day: str, until: Optional[str] = None) -> List[Dict[str, Any]]:
        """The rows of a day, or of every day from ``day`` to ``until``, in the order they were said."""
        rows = self._q("SELECT * FROM broker_quotes WHERE quote_date>=? AND quote_date<=? AND deleted=0 "
                       "ORDER BY quote_date, quote_time, id", (day, until or day))
        return [self._broker_row(r) for r in rows]

    def broker_trades(self, day: str, until: Optional[str] = None) -> List[Dict[str, Any]]:
        """The trade lines of a day (or of every day from ``day`` to ``until``) in the order they were said - without
        reading every other line (the rows are kept as ``json.dumps`` writes them: ``"event": "trade"``)."""
        rows = self._q("SELECT * FROM broker_quotes WHERE quote_date>=? AND quote_date<=? AND deleted=0 AND payload LIKE ? "
                       "ORDER BY quote_date, quote_time, id", (day, until or day, '%"event": "trade"%'))
        return [q for q in (self._broker_row(r) for r in rows) if q.get("event") == "trade"]

    def broker_quote(self, quote_id: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM broker_quotes WHERE id=? AND deleted=0", (quote_id,))
        return self._broker_row(rows[0]) if rows else None

    @staticmethod
    def _broker_row(r) -> Dict[str, Any]:
        d = json.loads(r["payload"])
        d.update({"id": r["id"], "date": r["quote_date"], "time": r["quote_time"], "created_by": r["created_by"],
                  "created_at": r["created_at"]})
        return d

    def broker_senders(self) -> List[Tuple[str, int, str]]:
        """Every sender of the kept chats: (name, lines, last day)."""
        out: Dict[str, List[Any]] = {}
        for r in self._q("SELECT quote_date, payload FROM broker_quotes WHERE deleted=0"):
            name = (json.loads(r["payload"]).get("sender") or "").strip()
            if not name:
                continue
            hit = out.setdefault(name, [name, 0, r["quote_date"]])
            hit[1] += 1
            hit[2] = max(hit[2], r["quote_date"])
        return [tuple(v) for v in out.values()]

    def broker_sources(self) -> List[str]:
        """The sources the kept chats were given."""
        found = set()
        for r in self._q("SELECT payload FROM broker_quotes WHERE deleted=0"):
            src = (json.loads(r["payload"]).get("source") or "").strip()
            if src:
                found.add(src)
        return sorted(found)

    def delete_broker_quote(self, quote_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE broker_quotes SET deleted=1 WHERE id=? AND deleted=0", (quote_id,))
            return cur.rowcount > 0

    def broker_dates(self, limit: int = 120) -> List[Dict[str, Any]]:
        rows = self._q("SELECT quote_date, COUNT(*) AS n FROM broker_quotes WHERE deleted=0 GROUP BY quote_date "
                       "ORDER BY quote_date DESC LIMIT ?", (limit,))
        return [{"date": r["quote_date"], "count": r["n"]} for r in rows]

    def trade(self, trade_id: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM trades WHERE id=? AND deleted=0", (trade_id,))
        return self._trade_row(rows[0]) if rows else None

    def trade_dates(self, limit: int = 120) -> List[Dict[str, Any]]:
        rows = self._q("SELECT trade_date, COUNT(*) AS n FROM trades WHERE deleted=0 GROUP BY trade_date "
                       "ORDER BY trade_date DESC LIMIT ?", (limit,))
        return [{"date": r["trade_date"], "count": r["n"]} for r in rows]

    def save_blotter_snapshot(self, trade_date: str, payload: Dict[str, Any]) -> None:
        self._x("INSERT INTO blotter_snapshots (trade_date, payload, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(trade_date) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (trade_date, json.dumps(payload, ensure_ascii=False), now_iso()))

    def blotter_snapshot(self, trade_date: str) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT payload, updated_at FROM blotter_snapshots WHERE trade_date=?", (trade_date,))
        if not rows:
            return None
        d = json.loads(rows[0]["payload"])
        d["snapshot_at"] = rows[0]["updated_at"]
        return d

    # ------------------------------------------------------------------ trade templates (Günlük İşlemler's "Şablonlar")
    @staticmethod
    def _template_row(r) -> Dict[str, Any]:
        return {"id": r["id"], "owner": r["owner"], "name": r["name"], "kind": r["kind"], "spec": json.loads(r["payload"]),
                "created_by": r["created_by"], "created_at": r["created_at"], "updated_by": r["updated_by"],
                "updated_at": r["updated_at"]}

    def trade_templates(self, user: Optional[str]) -> List[Dict[str, Any]]:
        """The templates a user may fill the entry form from: their own (``owner``) and the desk's (``owner`` NULL)."""
        rows = self._q("SELECT * FROM trade_templates WHERE owner IS NULL OR owner=? ORDER BY id", (user,))
        return [self._template_row(r) for r in rows]

    def trade_template(self, tid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM trade_templates WHERE id=?", (tid,))
        return self._template_row(rows[0]) if rows else None

    def add_trade_template(self, owner: Optional[str], name: str, kind: str, spec: Dict[str, Any], user: str) -> int:
        ts = now_iso()
        return self._x("INSERT INTO trade_templates (owner, name, kind, payload, created_by, created_at, updated_by, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?)", (owner, name, kind, json.dumps(spec, ensure_ascii=False), user, ts, user, ts))

    def update_trade_template(self, tid: int, user: str, **fields: Any) -> bool:
        """Change a template: ``name``, ``kind``, ``spec``, ``owner`` (None: the desk's)."""
        sets, args = [], []
        for k, v in fields.items():
            if k not in ("name", "kind", "spec", "owner"):
                raise ValueError("bilinmeyen alan: %s" % k)
            sets.append("%s=?" % ("payload" if k == "spec" else k))
            args.append(json.dumps(v, ensure_ascii=False) if k == "spec" else v)
        sets += ["updated_by=?", "updated_at=?"]
        with self._lock:
            cur = self._db.execute("UPDATE trade_templates SET %s WHERE id=?" % ", ".join(sets), tuple(args) + (user, now_iso(), tid))
            return cur.rowcount > 0

    def delete_trade_template(self, tid: int) -> bool:
        with self._lock:
            return self._db.execute("DELETE FROM trade_templates WHERE id=?", (tid,)).rowcount > 0

    # ------------------------------------------------------------------ Trades (tradebook.py): the desk's and each trader's own
    # Apart from the blotter's ``trades``: nothing of the desk's reads these tables.  A trade is one row (its product's
    # fields as JSON); every change is written with its line of the log in one transaction; the close values of a day
    # are written with the day's row, once.
    TB_COLS = ("id", "scope", "owner", "product", "status", "trade_date", "created_by", "created_at", "updated_by",
                "updated_at")

    @classmethod
    def _tb_row(cls, r) -> Dict[str, Any]:
        d = json.loads(r["payload"])
        d.update({k: r[k] for k in cls.TB_COLS})
        return d

    @staticmethod
    def _tb_logged(db: sqlite3.Connection, ts: str, user: str, tid: int, scope: str, owner: str, action: str,
                   detail: Dict[str, Any]) -> None:
        db.execute("INSERT INTO tradebook_log (ts, user, trade, scope, owner, action, detail) VALUES (?,?,?,?,?,?,?)",
                   (ts, user, tid, scope, owner, action, json.dumps(detail, ensure_ascii=False)))

    def tb_add(self, scope: str, owner: str, product: str, trade_date: str, payload: Dict[str, Any], user: str,
               detail: Dict[str, Any]) -> int:
        """A new trade (open) and its "create" line of the log."""
        ts = now_iso()
        with self.transaction() as db:
            cur = db.execute("INSERT INTO tradebook (scope, owner, product, status, trade_date, payload, created_by, created_at, "
                             "updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (scope, owner, product, "open", trade_date, json.dumps(payload, ensure_ascii=False), user, ts,
                              user, ts))
            tid = cur.lastrowid
            self._tb_logged(db, ts, user, tid, scope, owner, "create", detail)
            return tid

    def tb_get(self, tid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM tradebook WHERE id=? AND deleted=0", (tid,))
        return self._tb_row(rows[0]) if rows else None

    def tb_list(self, scope: str, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        """The desk's trades (``owner`` None) or one trader's own, oldest first."""
        if owner is None:
            rows = self._q("SELECT * FROM tradebook WHERE scope=? AND deleted=0 ORDER BY id", (scope,))
        else:
            rows = self._q("SELECT * FROM tradebook WHERE scope=? AND owner=? AND deleted=0 ORDER BY id", (scope, owner))
        return [self._tb_row(r) for r in rows]

    def tb_dealt_by(self, day: str) -> List[Dict[str, Any]]:
        """Every trade (the desk's and every trader's own) dealt on ``day`` or before - a day's close values."""
        return [self._tb_row(r) for r in self._q("SELECT * FROM tradebook WHERE trade_date<=? AND deleted=0 ORDER BY id", (day,))]

    def tb_update(self, tid: int, payload: Dict[str, Any], status: str, trade_date: str, user: str, action: str,
                  detail: Dict[str, Any]) -> bool:
        """A trade changed (edited, closed, opened again) and its line of the log, together."""
        ts = now_iso()
        with self.transaction() as db:
            row = db.execute("SELECT scope, owner FROM tradebook WHERE id=? AND deleted=0", (tid,)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE tradebook SET payload=?, status=?, trade_date=?, updated_by=?, updated_at=? WHERE id=?",
                       (json.dumps(payload, ensure_ascii=False), status, trade_date, user, ts, tid))
            self._tb_logged(db, ts, user, tid, row["scope"], row["owner"], action, detail)
            return True

    def tb_set_payload(self, tid: int, payload: Dict[str, Any]) -> None:
        """What the dashboard itself keeps with a trade (a closed trade's realised value): no change of the trade's own."""
        with self._lock:
            self._db.execute("UPDATE tradebook SET payload=? WHERE id=? AND deleted=0", (json.dumps(payload, ensure_ascii=False), tid))

    def tb_delete(self, tid: int, user: str, detail: Dict[str, Any]) -> bool:
        """Delete a trade (kept, marked deleted: its log stays readable) and log it."""
        ts = now_iso()
        with self.transaction() as db:
            row = db.execute("SELECT scope, owner FROM tradebook WHERE id=? AND deleted=0", (tid,)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE tradebook SET deleted=1, updated_by=?, updated_at=? WHERE id=?", (user, ts, tid))
            self._tb_logged(db, ts, user, tid, row["scope"], row["owner"], "delete", detail)
            return True

    def tb_log(self, trade: Optional[int] = None, scope: Optional[str] = None, owner: Optional[str] = None,
               limit: int = 200) -> List[Dict[str, Any]]:
        """The log of one trade (oldest first), or of the desk's / one trader's trades (``scope``, ``owner``; newest
        first)."""
        if trade is not None:
            rows = self._q("SELECT * FROM tradebook_log WHERE trade=? ORDER BY id", (trade,))
        elif owner is None:
            rows = self._q("SELECT * FROM tradebook_log WHERE scope=? ORDER BY id DESC LIMIT ?", (scope, limit))
        else:
            rows = self._q("SELECT * FROM tradebook_log WHERE scope=? AND owner=? ORDER BY id DESC LIMIT ?", (scope, owner, limit))
        return [{"id": r["id"], "ts": r["ts"], "user": r["user"], "trade": r["trade"], "scope": r["scope"], "owner": r["owner"],
                 "action": r["action"], "detail": json.loads(r["detail"])} for r in rows]

    def tb_close_days(self, limit: int = 60) -> List[Dict[str, Any]]:
        """The days whose close values were taken, the latest first."""
        return [dict(r) for r in self._q("SELECT * FROM tradebook_close_days ORDER BY day DESC LIMIT ?", (limit,))]

    def tb_close_day(self, day: str) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM tradebook_close_days WHERE day=?", (day,))
        return dict(rows[0]) if rows else None

    def tb_put_close(self, day: str, at: str, late: bool, values: List[Tuple[int, Dict[str, Any]]]) -> bool:
        """A day's close: its row and every trade's values, in one transaction - ``False`` (nothing written) when the
        day was taken already: a day is never taken twice."""
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM tradebook_close_days WHERE day=?", (day,)).fetchone():
                return False
            db.execute("INSERT INTO tradebook_close_days (day, at, taken_at, late, trades, valued) VALUES (?,?,?,?,?,?)",
                       (day, at, now_iso(), 1 if late else 0, len(values), sum(1 for _, v in values if v.get("ok"))))
            db.executemany("INSERT INTO tradebook_closes (day, trade, payload) VALUES (?,?,?)",
                           [(day, tid, json.dumps(v, ensure_ascii=False)) for tid, v in values])
            return True

    def tb_closes(self, trades: Sequence[int], since: Optional[str] = None) -> Dict[int, Dict[str, Dict[str, Any]]]:
        """trade -> day -> its close values (from ``since`` on)."""
        out: Dict[int, Dict[str, Dict[str, Any]]] = {}
        ids = [int(t) for t in trades]
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            sql = "SELECT day, trade, payload FROM tradebook_closes WHERE trade IN (%s)" % ",".join("?" * len(part))
            args: Tuple[Any, ...] = tuple(part)
            if since:
                sql += " AND day>=?"
                args += (since,)
            for r in self._q(sql, args):
                out.setdefault(r["trade"], {})[r["day"]] = json.loads(r["payload"])
        return out

    # ------------------------------------------------------------------ cells that move with their meeting
    def remap_user_cells(self, book: str, mapping: Dict[str, Optional[str]]) -> Dict[str, int]:
        """Move personal inputs (and the cells of saved scenarios) of one workbook to other cells.

        ``mapping``: old cell -> new cell (``None``: the value is dropped).  All of it happens in one
        transaction, for every user: what was typed for a meeting stays with that meeting when the list of
        meetings is shifted.  A formula never moves: its references would not move with it - a moved cell keeps its
        value, as a value (the dashboard takes no formula in these cells).  Returns how many values moved / were
        dropped.
        """
        if not mapping:
            return {"moved": 0, "dropped": 0, "scenarios": 0}
        ts = now_iso()
        moved = dropped = touched = 0
        with self.transaction() as db:
            marks = ",".join("?" for _ in mapping)
            rows = db.execute("SELECT user, cell, value, formula FROM user_inputs WHERE book=? AND cell IN (%s)" % marks,
                              (book,) + tuple(mapping)).fetchall()
            db.execute("DELETE FROM user_inputs WHERE book=? AND cell IN (%s)" % marks, (book,) + tuple(mapping))
            for r in rows:
                new = mapping[r["cell"]]
                if new is None:
                    dropped += 1
                    continue
                moved += 1 if new != r["cell"] else 0
                db.execute(
                    "INSERT INTO user_inputs (user, book, cell, value, updated_at) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(user, book, cell) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
                    "formula=NULL", (r["user"], book, new, r["value"], ts))
            for r in db.execute("SELECT id, payload FROM scenarios").fetchall():
                items = json.loads(r["payload"])
                out, changed = [], False
                for x in items:
                    if x[0] == book and x[1] in mapping:
                        new = mapping[x[1]]
                        changed = changed or new != x[1] or len(x) > 3
                        if new is None:
                            continue
                        out.append([x[0], new, x[2]])
                    else:
                        out.append(list(x))
                if changed:
                    touched += 1
                    db.execute("UPDATE scenarios SET payload=?, updated_at=? WHERE id=?",
                               (json.dumps(sorted(out, key=lambda x: (x[0], x[1])), ensure_ascii=False), ts, r["id"]))
        self._told("*", any(r["formula"] for r in rows))
        return {"moved": moved, "dropped": dropped, "scenarios": touched}

    # ------------------------------------------------------------------ the meeting calendars' own (tto/meetings.py)
    # Small steps of one calendar change: each joins the transaction the change opens (store.transaction()), so the
    # whole change lands together or not at all.  Nothing here tells the input formulas: the change does, once, after
    # it committed.
    def input_rows(self, book: str, cells: List[str]) -> List[Dict[str, Any]]:
        """Every user's inputs at these cells of a workbook: ``[{"user", "cell", "value", "formula"}]``."""
        out: List[Dict[str, Any]] = []
        cells = list(cells)
        for i in range(0, len(cells), 400):
            chunk = cells[i:i + 400]
            marks = ",".join("?" for _ in chunk)
            for r in self._q("SELECT user, cell, value, formula FROM user_inputs WHERE book=? AND cell IN (%s)" % marks,
                             (book,) + tuple(chunk)):
                out.append({"user": r["user"], "cell": r["cell"], "value": json.loads(r["value"]), "formula": r["formula"]})
        return out

    def drop_input_cells(self, book: str, cells: List[str]) -> None:
        """Every user's inputs at these cells go (with their formulas)."""
        with self.transaction() as db:
            db.executemany("DELETE FROM user_inputs WHERE book=? AND cell=?", [(book, c) for c in cells])

    def put_input_rows(self, book: str, rows: List[Tuple[str, str, Any]]) -> None:
        """``[(user, cell, value)]`` as plain values (a formula the cell had goes)."""
        ts = now_iso()
        with self.transaction() as db:
            db.executemany(
                "INSERT INTO user_inputs (user, book, cell, value, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(user, book, cell) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, formula=NULL",
                [(u, book, c, json.dumps(v, ensure_ascii=False), ts) for u, c, v in rows])

    def scenario_rows(self) -> List[Dict[str, Any]]:
        """Every saved scenario: ``[{"id", "user", "name", "items"}]`` (items as kept: ``[book, cell, value, formula?]``)."""
        out = []
        for r in self._q("SELECT id, user, name, payload FROM scenarios ORDER BY id"):
            try:
                items = json.loads(r["payload"])
            except (TypeError, ValueError):
                continue
            out.append({"id": r["id"], "user": r["user"], "name": r["name"], "items": items})
        return out

    def put_scenario_items(self, sid: int, items: List[List[Any]]) -> None:
        with self.transaction() as db:
            db.execute("UPDATE scenarios SET payload=?, updated_at=? WHERE id=?",
                       (json.dumps(sorted(items, key=lambda x: (x[0], x[1])), ensure_ascii=False), now_iso(), sid))

    def formula_rows(self) -> List[Tuple[Optional[str], str, str, str]]:
        """Every input typed as a formula: ``[(user - None for the desk's -, book, cell, text)]``."""
        out: List[Tuple[Optional[str], str, str, str]] = [
            (r["user"], r["book"], r["cell"], r["formula"]) for r in
            self._q("SELECT user, book, cell, formula FROM user_inputs WHERE formula IS NOT NULL")]
        out += [(None, r["book"], r["cell"], r["formula"]) for r in
                self._q("SELECT book, cell, formula FROM shared_inputs WHERE formula IS NOT NULL")]
        return out

    def put_formula_text(self, user: Optional[str], book: str, cell: str, text: str) -> None:
        """Another text for an input's formula (its value stays until the formula is evaluated again)."""
        with self.transaction() as db:
            if user is None:
                db.execute("UPDATE shared_inputs SET formula=? WHERE book=? AND cell=?", (text, book, cell))
            else:
                db.execute("UPDATE user_inputs SET formula=? WHERE user=? AND book=? AND cell=?", (text, user, book, cell))

    def kv_prefixed(self, prefix: str) -> Dict[str, Any]:
        """Every key / value whose key starts with ``prefix``."""
        out = {}
        for r in self._q("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)):
            try:
                out[r["key"]] = json.loads(r["value"])
            except (TypeError, ValueError):
                continue
        return out

    def rename_closes(self, renames: Dict[str, str]) -> None:
        """The watch's own closes kept under another subject key (a meeting whose date was corrected)."""
        if not renames:
            return
        with self.transaction() as db:
            db.executemany("UPDATE OR REPLACE watch_closes SET subject=? WHERE subject=?",
                           [(new, old) for old, new in renames.items()])
            self._later(self._own_renamed, list(renames.items()))

    def _own_renamed(self, renames: List[Tuple[str, str]]) -> None:
        for old, new in renames:
            self._own.rename(old, new)

    # ------------------------------------------------------------------ daily history of market series
    def hist_upsert(self, series: str, rows: List[Tuple[str, float]]) -> int:
        """Store closes ``[(yyyy-mm-dd, value), ...]``; returns how many rows are new or changed."""
        if not rows:
            return 0
        with self._lock:
            have = {r["day"]: r["value"] for r in self._db.execute(
                "SELECT day, value FROM hist_values WHERE series=? AND day>=? AND day<=?",
                (series, min(d for d, _ in rows), max(d for d, _ in rows))).fetchall()}
            fresh = [(series, d, float(v)) for d, v in rows if have.get(d) != float(v)]
            if fresh:
                self._db.execute("BEGIN")
                try:
                    self._db.executemany("INSERT INTO hist_values (series, day, value) VALUES (?,?,?) "
                                         "ON CONFLICT(series, day) DO UPDATE SET value=excluded.value", fresh)
                    self._db.execute("COMMIT")
                except Exception:
                    self._db.execute("ROLLBACK")
                    raise
                self._later(self._hist_put, series, [(d, _stored(v, "REAL")) for _, d, v in fresh])
            return len(fresh)

    def _hist_put(self, series: str, rows: List[Tuple[str, float]]) -> None:
        self._hist.put(series, rows)
        self._bounds = None

    def hist_series(self, series: str, start: Optional[str] = None, end: Optional[str] = None) -> List[Tuple[str, float]]:
        """``[(day, value), ...]`` of one series, by day (from memory)."""
        if not self._memory:
            return [(r["day"], r["value"]) for r in self._q("SELECT day, value FROM hist_values WHERE series=? AND day>=? "
                                                            "AND day<=? ORDER BY day", (series, start or "0000", end or "9999"))]
        with self._mem:
            days, vals = self._hist.span(series, start or "0000", end or "9999")
            return list(zip(days, vals))

    def hist_many(self, series: List[str], start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """``{series: {day: value}}`` for several series at once (from memory; each series' days ascending)."""
        if not self._memory:
            return self._file_daily("hist_values", "series", series, start, end)
        lo, hi = start or "0000", end or "9999"
        with self._mem:
            return {s: dict(zip(*self._hist.span(s, lo, hi))) for s in series}

    def _file_daily(self, table: str, key: str, keys: List[str], start: Optional[str],
                    end: Optional[str]) -> Dict[str, Dict[str, float]]:
        """``hist_many`` / ``closes`` read from the file, row by row (a damaged file only: see :meth:`_load_memory`)."""
        out: Dict[str, Dict[str, float]] = {k: {} for k in keys}
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            for r in self._q("SELECT %s, day, value FROM %s WHERE %s IN (%s) AND day>=? AND day<=?" % (
                    key, table, key, ",".join("?" for _ in chunk)), tuple(chunk) + (start or "0000", end or "9999")):
                out[r[key]][r["day"]] = r["value"]
        return out

    def hist_bounds(self) -> Dict[str, Tuple[str, str, int]]:
        """``{series: (first day, last day, count)}`` (kept until the closes change)."""
        if not self._memory:
            return {r["series"]: (r["a"], r["b"], r["n"]) for r in self._q(
                "SELECT series, MIN(day) AS a, MAX(day) AS b, COUNT(*) AS n FROM hist_values GROUP BY series")}
        with self._mem:
            if self._bounds is None:
                self._bounds = {s: (days[0], days[-1], len(days)) for s, (days, _) in sorted(self._hist.by.items()) if days}
            return dict(self._bounds)

    def hist_delete(self, series: Optional[str] = None) -> None:
        with self._lock:
            if series is None:
                self._db.execute("DELETE FROM hist_values")
            else:
                self._db.execute("DELETE FROM hist_values WHERE series=?", (series,))
            self._later(self._hist_dropped, series)

    def _hist_dropped(self, series: Optional[str]) -> None:
        self._hist.drop(series)
        self._bounds = None

    # ------------------------------------------------------------------ what was priced for the MPC meetings, per day
    def mpc_save(self, day: str, basis: str, meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
        """Replace one day: ``rows`` = ``[{"meeting", "step", "level", "cum", "sigma", "front"}, ...]``."""
        values = [(day, r["meeting"], r.get("step"), r.get("level"), r.get("cum"), r.get("sigma"), 1 if r.get("front") else 0)
                  for r in rows]
        head = (day, basis, meta.get("spot"), meta.get("tlref"), meta.get("base"), 1 if meta.get("decision") else 0,
                meta.get("quotes"), meta.get("status"), meta.get("note"), now_iso(), meta.get("control"),
                meta.get("tolerance"), meta.get("carried"), meta.get("cleaned"))
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("DELETE FROM mpc_values WHERE day=?", (day,))
                self._db.executemany(
                    "INSERT INTO mpc_values (day, meeting, step, level, cum, sigma, front) VALUES (?,?,?,?,?,?,?)", values)
                self._db.execute(
                    "INSERT INTO mpc_days (day, basis, spot, tlref, base, decision, quotes, status, note, computed_at, "
                    "control, tolerance, carried, cleaned) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(day) DO UPDATE SET basis=excluded.basis, spot=excluded.spot, tlref=excluded.tlref, "
                    "base=excluded.base, decision=excluded.decision, quotes=excluded.quotes, status=excluded.status, "
                    "note=excluded.note, computed_at=excluded.computed_at, control=excluded.control, "
                    "tolerance=excluded.tolerance, carried=excluded.carried, cleaned=excluded.cleaned", head)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            if self._memory:
                self._later(self._mpc_put, *self._mpc_stored(day, head, values))

    def _mpc_stored(self, day: Any, head: Tuple[Any, ...], values: List[Tuple[Any, ...]]
                    ) -> Tuple[str, Dict[str, Any], List[Tuple[Any, ...]]]:
        """A day just saved as the file holds it: ``(day, its mpc_days row, its mpc_values rows by meeting)`` - worked
        out from what was written (:func:`_stored`), read back when a value is not one of the plain kinds."""
        kinds = self._kinds.get("mpc_days") or {}
        named = dict(zip(_MPC_DAY_COLS, head))
        row: Optional[Dict[str, Any]] = None
        if set(kinds) == set(_MPC_DAY_COLS):
            row = {c: _stored(named[c], a) for c, a in kinds.items()}       # (the table's own column order: SELECT *)
            if any(v is _UNSURE for v in row.values()):
                row = None
        if row is None:
            row = dict(self._db.execute("SELECT * FROM mpc_days WHERE day=?", (day,)).fetchone())
        affinities = [(self._kinds.get("mpc_values") or {}).get(c, "") for c in _MPC_VALUE_COLS]
        got: Optional[List[Tuple[Any, ...]]] = [tuple(_stored(x, a) for x, a in zip(t, affinities)) for t in values]
        if any(x is _UNSURE for t in got or () for x in t):
            cur = self._db.cursor()
            cur.row_factory = None
            got = cur.execute("SELECT %s FROM mpc_values WHERE day=? ORDER BY meeting" % ", ".join(_MPC_VALUE_COLS),
                              (day,)).fetchall()
        else:
            got.sort(key=lambda t: t[1])
        return row["day"], row, got

    def _mpc_put(self, day: str, row: Dict[str, Any], rows: List[Tuple[Any, ...]]) -> None:
        self._mpc_all[day] = row
        _put_day(self._mpc_days, day)
        if rows:
            self._mpc_rows[day] = rows
            _put_day(self._mpc_value_days, day)
        elif self._mpc_rows.pop(day, None) is not None:
            _drop_day(self._mpc_value_days, day)

    def mpc_days(self, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """``{day: its row}``, by day (from memory)."""
        if not self._memory:
            rows = self._q("SELECT * FROM mpc_days ORDER BY day") if start is None and end is None else self._q(
                "SELECT * FROM mpc_days WHERE day>=? AND day<=? ORDER BY day", (start or "0000", end or "9999"))
            return {r["day"]: dict(r) for r in rows}
        with self._mem:
            days = self._mpc_days
            if start is not None or end is not None:
                days = days[bisect.bisect_left(days, start or "0000"):bisect.bisect_right(days, end or "9999")]
            return {d: dict(self._mpc_all[d]) for d in days}

    def mpc_values(self, start: Optional[str] = None, end: Optional[str] = None,
                   meetings: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """The rows of the days from ``start`` to ``end`` (of these ``meetings`` only), by day and meeting (from memory)."""
        if meetings is not None and not meetings:
            return []
        if not self._memory:
            sql = "SELECT %s FROM mpc_values WHERE day>=? AND day<=?" % ", ".join(_MPC_VALUE_COLS)
            if meetings is not None:
                sql += " AND meeting IN (%s)" % ",".join("?" for _ in meetings)
            args = (start or "0000", end or "9999") + tuple(meetings or ())
            return [dict(r) for r in self._q(sql + " ORDER BY day, meeting", args)]
        want = None if meetings is None else set(meetings)
        with self._mem:
            days = self._mpc_value_days
            days = days[bisect.bisect_left(days, start or "0000"):bisect.bisect_right(days, end or "9999")]
            return [dict(zip(_MPC_VALUE_COLS, t)) for d in days for t in self._mpc_rows[d] if want is None or t[1] in want]

    def mpc_delete(self, days: Optional[List[str]] = None) -> None:
        with self.transaction():                                     # (both tables, or neither)
            if days is None:
                self._db.execute("DELETE FROM mpc_values")
                self._db.execute("DELETE FROM mpc_days")
            else:
                days = list(days)
                self._db.executemany("DELETE FROM mpc_values WHERE day=?", [(d,) for d in days])
                self._db.executemany("DELETE FROM mpc_days WHERE day=?", [(d,) for d in days])
            self._later(self._mpc_dropped, days)

    def _mpc_dropped(self, days: Optional[List[str]]) -> None:
        if days is None:
            self._mpc_all, self._mpc_days, self._mpc_rows, self._mpc_value_days = {}, [], {}, []
            return
        for d in days:
            if self._mpc_all.pop(d, None) is not None:
                _drop_day(self._mpc_days, d)
            if self._mpc_rows.pop(d, None) is not None:
                _drop_day(self._mpc_value_days, d)

    # ------------------------------------------------------------------ Bloomberg's answers of the day
    def bbg_answers(self, day: str) -> List[Tuple[Tuple, Any, float]]:
        """The reference answers Bloomberg gave on ``day`` (kept for a restart): ``[(key, value, fetched), ...]``."""
        out = []
        for r in self._q("SELECT key, value, fetched FROM bbg_answers WHERE day=?", (day,)):
            try:
                out.append((pickle.loads(r["key"]), pickle.loads(r["value"]), float(r["fetched"])))
            except Exception:  # noqa: BLE001 - an answer that cannot be read is asked again
                continue
        return out

    def bbg_keep(self, day: str, answers) -> int:
        """Keep these answers of ``day`` (those of another day go)."""
        rows = [(sqlite3.Binary(pickle.dumps(k, protocol=4)), day, float(t), sqlite3.Binary(pickle.dumps(v, protocol=4)))
                for k, v, t in answers]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("DELETE FROM bbg_answers WHERE day<>?", (day,))
                self._db.executemany("INSERT OR REPLACE INTO bbg_answers (key, day, fetched, value) VALUES (?,?,?,?)", rows)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return len(rows)

    def bbg_usage(self, day: str) -> Dict[Tuple, int]:
        """The day's Bloomberg hits by key (the status page's sheets and fields; kept for a restart): ``{key: hits}``."""
        out: Dict[Tuple, int] = {}
        for r in self._q("SELECT key, hits FROM bbg_usage WHERE day=?", (day,)):
            try:
                out[pickle.loads(r["key"])] = int(r["hits"])
            except Exception:  # noqa: BLE001 - a count that cannot be read starts again
                continue
        return out

    def bbg_usage_keep(self, day: str, counts) -> int:
        """Keep these counts of ``day`` - ``[(key, hits), ...]``, the keys whose count changed (another day's go)."""
        rows = [(sqlite3.Binary(pickle.dumps(k, protocol=4)), day, int(n)) for k, n in counts]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("DELETE FROM bbg_usage WHERE day<>?", (day,))
                self._db.executemany("INSERT OR REPLACE INTO bbg_usage (key, day, hits) VALUES (?,?,?)", rows)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return len(rows)

    # ------------------------------------------------------------------ the closes the watch keeps itself
    def close_upsert(self, rows: List[Tuple[str, str, float]]) -> int:
        """The day's last value of what is watched ``[(subject key, yyyy-mm-dd, value), ...]`` (kept apart from
        the market history: these are the dashboard's own readings, of anything - a VİOP spread, an ASW, an
        expression)."""
        if not rows:
            return 0
        written = [(k, d, float(v)) for k, d, v in rows]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.executemany("INSERT INTO watch_closes (subject, day, value) VALUES (?,?,?) "
                                     "ON CONFLICT(subject, day) DO UPDATE SET value=excluded.value", written)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            self._later(self._own_put, written)
        return len(rows)

    def _own_put(self, written: List[Tuple[str, str, float]]) -> None:
        for key, group in itertools.groupby(written, key=lambda r: r[0]):
            self._own.put(key, [(d, _stored(v, "REAL")) for _, d, v in group])

    def closes(self, subjects: List[str], start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """``{subject key: {day: value}}`` (from memory; each subject's days ascending)."""
        if not self._memory:
            return self._file_daily("watch_closes", "subject", subjects, start, end)
        lo, hi = start or "0000", end or "9999"
        with self._mem:
            return {s: dict(zip(*self._own.span(s, lo, hi))) for s in subjects}

    # ------------------------------------------------------------------ misc key/value
    def get(self, key: str, default: Any = None) -> Any:
        rows = self._q("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def put(self, key: str, value: Any) -> None:
        self._x("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))

    # ------------------------------------------------------------------ the desk's own: reports, chat, agenda
    def add_feedback(self, kind: str, text: str, page: Optional[str], page_title: Optional[str], user: str) -> int:
        return self._x("INSERT INTO feedback (kind, text, page, page_title, created_by, created_at) VALUES (?,?,?,?,?,?)",
                       (kind, text, page, page_title, user, now_iso()))

    def feedback(self, done: bool, limit: int = 200) -> List[Dict[str, Any]]:
        """The reports still open, or the ones dealt with - the latest first."""
        if done:
            rows = self._q("SELECT * FROM feedback WHERE done_at IS NOT NULL ORDER BY done_at DESC, id DESC LIMIT ?", (limit,))
        else:
            rows = self._q("SELECT * FROM feedback WHERE done_at IS NULL ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def feedback_item(self, fid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM feedback WHERE id=?", (fid,))
        return dict(rows[0]) if rows else None

    def feedback_open(self) -> int:
        return int(self._q("SELECT COUNT(*) AS n FROM feedback WHERE done_at IS NULL")[0]["n"])

    def set_feedback_done(self, fid: int, user: Optional[str]) -> bool:
        """A report dealt with by ``user`` - or open again (``None``).  False: no such report, or it already is."""
        if user:
            sql, args = "UPDATE feedback SET done_by=?, done_at=? WHERE id=? AND done_at IS NULL", (user, now_iso(), fid)
        else:
            sql, args = "UPDATE feedback SET done_by=NULL, done_at=NULL WHERE id=? AND done_at IS NOT NULL", (fid,)
        with self._lock:
            return self._db.execute(sql, args).rowcount > 0

    def add_chat(self, user: str, text: str) -> Dict[str, Any]:
        ts = now_iso()
        mid = self._x("INSERT INTO chat (user, text, created_at) VALUES (?,?,?)", (user, text, ts))
        return {"id": mid, "user": user, "text": text, "created_at": ts}

    def chat(self, before: Optional[int] = None, since: Optional[int] = None, limit: int = 200) -> Tuple[List[Dict[str, Any]], bool]:
        """Chat messages, oldest first: the last ``limit`` (those before the message ``before``), or - ``since`` - the
        last ``limit`` from that message on; and whether there are earlier ones."""
        if since is not None:
            rows = self._q("SELECT * FROM chat WHERE id>=? ORDER BY id DESC LIMIT ?", (since, limit))
        elif before is not None:
            rows = self._q("SELECT * FROM chat WHERE id<? ORDER BY id DESC LIMIT ?", (before, limit))
        else:
            rows = self._q("SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,))
        out = [dict(r) for r in reversed(rows)]
        more = bool(out) and bool(self._q("SELECT 1 FROM chat WHERE id<? LIMIT 1", (out[0]["id"],)))
        return out, more

    def chat_item(self, mid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM chat WHERE id=?", (mid,))
        return dict(rows[0]) if rows else None

    def chat_last(self) -> int:
        return int(self._q("SELECT COALESCE(MAX(id), 0) AS n FROM chat")[0]["n"])

    def chat_unread(self, user: str, after: int) -> int:
        """Messages of the others after the message ``after``."""
        return int(self._q("SELECT COUNT(*) AS n FROM chat WHERE id>? AND user<>?", (after, user))[0]["n"])

    def delete_chat(self, mid: int, user: str) -> bool:
        with self._lock:
            return self._db.execute("DELETE FROM chat WHERE id=? AND user=?", (mid, user)).rowcount > 0

    def add_agenda(self, owner: Optional[str], day: str, time: Optional[str], text: str, deadline: bool, user: str) -> int:
        """An item of the agenda: the desk's (``owner`` None) or one user's own."""
        return self._x("INSERT INTO agenda (owner, day, time, text, deadline, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                       (owner, day, time, text, 1 if deadline else 0, user, now_iso()))

    def agenda(self, user: str, start: str, limit: int = 1000, late: int = 200) -> List[Dict[str, Any]]:
        """The desk's items and the user's own from the day ``start`` on (the first ``limit``), and before it the
        deadlines still not met (the latest ``late``); by day, then time (an item without a time first in its day)."""
        mine = "(owner IS NULL OR owner=?)"
        before = self._q("SELECT * FROM agenda WHERE %s AND day<? AND deadline=1 AND done_at IS NULL "
                         "ORDER BY day DESC, time IS NOT NULL DESC, time DESC, id DESC LIMIT ?" % mine, (user, start, late))
        rows = self._q("SELECT * FROM agenda WHERE %s AND day>=? ORDER BY day, time IS NOT NULL, time, id LIMIT ?" % mine,
                       (user, start, limit))
        return [dict(r) for r in reversed(before)] + [dict(r) for r in rows]

    def agenda_due(self, user: str, today: str, tomorrow: str) -> List[Dict[str, Any]]:
        """What is not done yet of today, of tomorrow, and the deadlines of the days before (the reminders, the badge)."""
        return [dict(r) for r in self._q(
            "SELECT * FROM agenda WHERE (owner IS NULL OR owner=?) AND done_at IS NULL "
            "AND (day IN (?, ?) OR (deadline=1 AND day<?)) ORDER BY day, time IS NOT NULL, time, id LIMIT 500",
            (user, today, tomorrow, today))]

    def agenda_item(self, aid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM agenda WHERE id=?", (aid,))
        return dict(rows[0]) if rows else None

    def set_agenda_done(self, aid: int, user: Optional[str]) -> None:
        """Done by ``user`` - or not done (``None``)."""
        self._x("UPDATE agenda SET done_by=?, done_at=? WHERE id=?", (user, now_iso() if user else None, aid))

    def delete_agenda(self, aid: int) -> None:
        self._x("DELETE FROM agenda WHERE id=?", (aid,))

    # ------------------------------------------------------------------ the agenda's recurring items
    #: what of a recurring item's rule may change after it was added (who it is for does not)
    _RULE_FIELDS = ("kind", "weekdays", "time", "text", "deadline", "start_day", "end_day", "since", "paused_by", "paused_at")

    def add_agenda_rule(self, owner: Optional[str], rule: Dict[str, Any], user: str) -> int:
        """A recurring item of the agenda: the desk's (``owner`` None) or one user's own; ``rule``: its kind, days of the
        week, time, text, deadline, first and last day and ``since`` (the moment its days count from)."""
        cols = [k for k in self._RULE_FIELDS if k in rule]
        return self._x("INSERT INTO agenda_rules (owner, %s, created_by, created_at) VALUES (?, %s, ?, ?)"
                       % (", ".join(cols), ", ".join("?" for _ in cols)),
                       (owner,) + tuple(rule[k] for k in cols) + (user, now_iso()))

    def agenda_rules(self, user: str) -> List[Dict[str, Any]]:
        """The desk's recurring items and the user's own, by time."""
        return [dict(r) for r in self._q("SELECT * FROM agenda_rules WHERE owner IS NULL OR owner=? ORDER BY time, id", (user,))]

    def agenda_rule(self, rid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM agenda_rules WHERE id=?", (rid,))
        return dict(rows[0]) if rows else None

    def agenda_rules_added(self, user: str) -> int:
        """How many recurring items ``user`` added (the desk's and their own)."""
        return int(self._q("SELECT COUNT(*) AS n FROM agenda_rules WHERE created_by=?", (user,))[0]["n"])

    def update_agenda_rule(self, rid: int, fields: Dict[str, Any], user: str) -> None:
        """A recurring item changed (``fields`` of its rule; paused: ``paused_by`` / ``paused_at``), by ``user`` now."""
        bad = [k for k in fields if k not in self._RULE_FIELDS]
        if bad:
            raise ValueError("not a field of a recurring item: %s" % ", ".join(bad))
        self._x("UPDATE agenda_rules SET %s, updated_by=?, updated_at=? WHERE id=?" % ", ".join("%s=?" % k for k in fields),
                tuple(fields.values()) + (user, now_iso(), rid))

    def delete_agenda_rule(self, rid: int) -> None:
        """A recurring item goes with the days it was done and its snoozes - all of it or nothing."""
        with self.transaction() as db:
            db.execute("DELETE FROM agenda_snoozes WHERE rule=?", (rid,))
            db.execute("DELETE FROM agenda_rule_days WHERE rule=?", (rid,))
            db.execute("DELETE FROM agenda_rules WHERE id=?", (rid,))

    def agenda_rule_days(self, first: str, last: str) -> Dict[Tuple[int, str], Dict[str, Any]]:
        """The recurring items' days done from ``first`` to ``last``: (rule, day) -> who, when."""
        return {(r["rule"], r["day"]): dict(r) for r in self._q(
            "SELECT * FROM agenda_rule_days WHERE day>=? AND day<=?", (first, last))}

    def set_agenda_rule_day(self, rid: int, day: str, user: Optional[str]) -> bool:
        """A recurring item done on a day by ``user`` - or not done after all (``None``).  False: it already was (not)
        - two at once: the first one's stands."""
        with self._lock:
            if user:
                return self._db.execute("INSERT OR IGNORE INTO agenda_rule_days (rule, day, done_by, done_at) VALUES (?,?,?,?)",
                                        (rid, day, user, now_iso())).rowcount > 0
            return self._db.execute("DELETE FROM agenda_rule_days WHERE rule=? AND day=?", (rid, day)).rowcount > 0

    def agenda_snoozes(self, user: str, first: str) -> Dict[Tuple[int, str], str]:
        """Until when ``user`` put off the alarms of the recurring items' days from ``first`` on: (rule, day) -> until."""
        return {(r["rule"], r["day"]): r["until"] for r in self._q(
            "SELECT rule, day, until FROM agenda_snoozes WHERE user=? AND day>=?", (user, first))}

    def snooze_agenda_rule(self, rid: int, day: str, user: str, until: str, keep_from: str) -> None:
        """``user`` puts off the alarm of a recurring item's day until ``until`` (for themselves); the snoozes of the
        days before ``keep_from`` are of no use any more and go."""
        with self.transaction() as db:
            db.execute("DELETE FROM agenda_snoozes WHERE day<?", (keep_from,))
            db.execute("INSERT INTO agenda_snoozes (user, rule, day, until) VALUES (?,?,?,?) "
                       "ON CONFLICT(user, rule, day) DO UPDATE SET until=excluded.until", (user, rid, day, until))

    # ------------------------------------------------------------------ the quote log (tto/quotelog.py)
    def add_quote_log(self, day: str, payload: Dict[str, Any], status: str, user: Optional[str]) -> int:
        """A quote given to a client (Kotasyon kopyala, Fiyatlama's forward card): kept with its day, status and who."""
        ts = now_iso()
        return self._x("INSERT INTO quote_log (quote_date, status, payload, created_by, created_at, updated_by, updated_at) "
                       "VALUES (?,?,?,?,?,?,?)", (day, status, json.dumps(payload, ensure_ascii=False), user, ts, user, ts))

    def quote_log(self, first: str, last: str) -> List[Dict[str, Any]]:
        """The quotes of the days ``first`` … ``last`` (ISO), in the order they were given."""
        rows = self._q("SELECT * FROM quote_log WHERE quote_date>=? AND quote_date<=? ORDER BY quote_date, id", (first, last))
        return [self._quote_log_row(r) for r in rows]

    def quote_log_item(self, qid: int) -> Optional[Dict[str, Any]]:
        rows = self._q("SELECT * FROM quote_log WHERE id=?", (qid,))
        return self._quote_log_row(rows[0]) if rows else None

    def set_quote_log(self, qid: int, status: Optional[str], fields: Dict[str, Any], user: Optional[str]) -> Optional[Dict[str, Any]]:
        """A quote's status (``None``: as it is) and fields of its record changed (``fields``: merged into it, a value
        ``None`` taken out) - ``None`` when there is no such quote."""
        with self.transaction() as db:
            row = db.execute("SELECT * FROM quote_log WHERE id=?", (qid,)).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload"])
            for k, v in fields.items():
                if v is None:
                    payload.pop(k, None)
                else:
                    payload[k] = v
            db.execute("UPDATE quote_log SET status=?, payload=?, updated_by=?, updated_at=? WHERE id=?",
                       (status or row["status"], json.dumps(payload, ensure_ascii=False), user, now_iso(), qid))
        return self.quote_log_item(qid)

    @staticmethod
    def _quote_log_row(r) -> Dict[str, Any]:
        d = json.loads(r["payload"])
        d.update({"id": r["id"], "date": r["quote_date"], "status": r["status"], "created_by": r["created_by"],
                  "created_at": r["created_at"], "updated_by": r["updated_by"], "updated_at": r["updated_at"]})
        return d
