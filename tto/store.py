"""SQLite persistence: users, personal inputs, named scenarios, shared inputs (RET curve ...), blotter.

A write of several steps (a package of trades deleted, a broker chat pasted, an account removed) is one
transaction: it lands whole or not at all.  Every commit is on the disk before it returns (``synchronous=FULL``):
a trade entered a moment before a power cut is kept.  :meth:`Store.backup_to` makes an online copy (SQLite's backup
API, consistent while the dashboard keeps writing); :func:`restore` puts one back in place.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import pathlib
import pickle
import re
import shutil
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

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
"""


#: table -> columns added after its first version: the solver's own check of a day (largest distance between
#: model and quote in bp, and what the workbook tolerates), how many quotes were not that day's own close and
#: which closes were not used (the roots of their tickers); a user's sign-in: the password hash, administrator
#: or not, active / waiting for approval / closed, the note sent with a request and who decided on it, the wrong
#: passwords in a row and until when the name is locked.  A user of an earlier version is an active user without
#: a password: they ask for an account under the same name to set one.  An input typed as a formula (``=C60+7``):
#: its text beside its value - the value is the formula's result as it was set (an earlier version reads the value).
_ADDED_COLUMNS = {"mpc_days": (("control", "REAL"), ("tolerance", "REAL"), ("carried", "INTEGER"), ("cleaned", "TEXT")),
                  "users": (("pw_hash", "TEXT"), ("role", "TEXT NOT NULL DEFAULT 'user'"),
                            ("status", "TEXT NOT NULL DEFAULT 'active'"), ("note", "TEXT"), ("requested_at", "TEXT"),
                            ("decided_by", "TEXT"), ("decided_at", "TEXT"), ("failed", "INTEGER NOT NULL DEFAULT 0"),
                            ("locked_until", "TEXT"), ("requested_new", "INTEGER NOT NULL DEFAULT 0")),
                  "user_inputs": (("formula", "TEXT"),),
                  "shared_inputs": (("formula", "TEXT"),)}
_ACCOUNT_FIELDS = ("display", "last_seen", "pw_hash", "role", "status", "note", "requested_at", "decided_by", "decided_at",
                   "failed", "locked_until", "requested_new")


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
    """Put a backup in the place of the database - with the dashboard stopped.  The backup is checked first (a
    sound SQLite file with the dashboard's tables); the database as it was is kept beside it, with its write-ahead
    log (``tto.db.onceki-<time>``): nothing is deleted.  On Windows a database the dashboard still has open cannot be
    moved: that stops the restore before anything changed."""
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
        for suffix in ("", "-wal", "-shm"):          # the database with its log: the log belongs to it, not to the backup
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


class Store(object):
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        # what the history pages and the settings page poll, kept until the history is written to (a GROUP BY over
        # every close each time made the status poll a full scan)
        self._bounds: Optional[Dict[str, Tuple[str, str, int]]] = None
        self._mpc_all: Optional[Dict[str, Dict[str, Any]]] = None
        # told after every write of the inputs: (the user - None for the shared inputs, "*" for every user -, whether
        # formulas were written); the inputs' formulas (inputformula.py) follow what any writer did to their cells
        self.on_inputs: Optional[Any] = None
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            # every commit waits until the write-ahead log is on the disk (NORMAL leaves the last commits to the next
            # checkpoint: a power cut could take back a trade the blotter had shown as entered).  Measured on the desk
            # machine with commits like the dashboard's: ~0.6-1.1 ms a commit (p99 ~4 ms) against ~0.03 ms - the
            # dashboard commits a few times a second at most, so for every table rather than for the trades alone
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
            for table, columns in _ADDED_COLUMNS.items():
                self._add_columns(table, columns)

    def _add_columns(self, table: str, columns) -> None:
        """Columns that came after a table was first created (a database of an earlier version keeps its rows)."""
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(%s)" % table).fetchall()}
        for name, kind in columns:
            if name not in have:
                self._db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, kind))

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
                raise

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
        rows = self._q("SELECT u.name, u.display, u.created_at, u.last_seen, u.role, u.status, u.note, u.requested_at, "
                       "u.decided_by, u.decided_at, u.locked_until, u.requested_new, u.pw_hash IS NOT NULL AS has_password, "
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
    def add_ret_history(self, user: Optional[str], rows: List[Dict[str, Any]]) -> int:
        return self._x("INSERT INTO ret_history (ts, user, payload) VALUES (?,?,?)",
                       (now_iso(), user, json.dumps(rows, ensure_ascii=False)))

    def ret_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._q("SELECT id, ts, user, payload FROM ret_history ORDER BY id DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "ts": r["ts"], "user": r["user"], "rows": json.loads(r["payload"])} for r in rows]

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
        with self._lock:
            cur = self._db.execute("UPDATE trades SET payload=?, updated_by=?, updated_at=? WHERE id=? AND deleted=0",
                                   (json.dumps(payload, ensure_ascii=False), user, now_iso(), trade_id))
            return cur.rowcount > 0

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
        out = []
        for r in rows:
            d = json.loads(r["payload"])
            d.update({"id": r["id"], "kind": r["kind"], "package": r["package"], "trade_date": r["trade_date"],
                      "created_by": r["created_by"], "created_at": r["created_at"],
                      "updated_by": r["updated_by"], "updated_at": r["updated_at"]})
            out.append(d)
        return out

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
        if not rows:
            return None
        r = rows[0]
        d = json.loads(r["payload"])
        d.update({"id": r["id"], "kind": r["kind"], "package": r["package"], "trade_date": r["trade_date"],
                  "created_by": r["created_by"], "created_at": r["created_at"]})
        return d

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
                self._bounds = None
                self._db.execute("BEGIN")
                try:
                    self._db.executemany("INSERT INTO hist_values (series, day, value) VALUES (?,?,?) "
                                         "ON CONFLICT(series, day) DO UPDATE SET value=excluded.value", fresh)
                    self._db.execute("COMMIT")
                except Exception:
                    self._db.execute("ROLLBACK")
                    raise
            return len(fresh)

    def hist_series(self, series: str, start: Optional[str] = None, end: Optional[str] = None) -> List[Tuple[str, float]]:
        rows = self._q("SELECT day, value FROM hist_values WHERE series=? AND day>=? AND day<=? ORDER BY day",
                       (series, start or "0000", end or "9999"))
        return [(r["day"], r["value"]) for r in rows]

    def hist_many(self, series: List[str], start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """``{series: {day: value}}`` for several series at once."""
        out: Dict[str, Dict[str, float]] = {s: {} for s in series}
        for i in range(0, len(series), 400):
            chunk = series[i:i + 400]
            marks = ",".join("?" for _ in chunk)
            for r in self._q("SELECT series, day, value FROM hist_values WHERE series IN (%s) AND day>=? AND day<=?" % marks,
                             tuple(chunk) + (start or "0000", end or "9999")):
                out[r["series"]][r["day"]] = r["value"]
        return out

    def hist_bounds(self) -> Dict[str, Tuple[str, str, int]]:
        """``{series: (first day, last day, count)}`` (kept until the closes change)."""
        with self._lock:
            if self._bounds is None:
                self._bounds = {r["series"]: (r["a"], r["b"], r["n"]) for r in self._q(
                    "SELECT series, MIN(day) AS a, MAX(day) AS b, COUNT(*) AS n FROM hist_values GROUP BY series")}
            return dict(self._bounds)

    def hist_delete(self, series: Optional[str] = None) -> None:
        with self._lock:
            self._bounds = None
            if series is None:
                self._db.execute("DELETE FROM hist_values")
            else:
                self._db.execute("DELETE FROM hist_values WHERE series=?", (series,))

    # ------------------------------------------------------------------ what was priced for the MPC meetings, per day
    def mpc_save(self, day: str, basis: str, meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
        """Replace one day: ``rows`` = ``[{"meeting", "step", "level", "cum", "sigma", "front"}, ...]``."""
        with self._lock:
            self._mpc_all = None
            self._db.execute("BEGIN")
            try:
                self._db.execute("DELETE FROM mpc_values WHERE day=?", (day,))
                self._db.executemany(
                    "INSERT INTO mpc_values (day, meeting, step, level, cum, sigma, front) VALUES (?,?,?,?,?,?,?)",
                    [(day, r["meeting"], r.get("step"), r.get("level"), r.get("cum"), r.get("sigma"), 1 if r.get("front") else 0)
                     for r in rows])
                self._db.execute(
                    "INSERT INTO mpc_days (day, basis, spot, tlref, base, decision, quotes, status, note, computed_at, "
                    "control, tolerance, carried, cleaned) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(day) DO UPDATE SET basis=excluded.basis, spot=excluded.spot, tlref=excluded.tlref, "
                    "base=excluded.base, decision=excluded.decision, quotes=excluded.quotes, status=excluded.status, "
                    "note=excluded.note, computed_at=excluded.computed_at, control=excluded.control, "
                    "tolerance=excluded.tolerance, carried=excluded.carried, cleaned=excluded.cleaned",
                    (day, basis, meta.get("spot"), meta.get("tlref"), meta.get("base"), 1 if meta.get("decision") else 0,
                     meta.get("quotes"), meta.get("status"), meta.get("note"), now_iso(), meta.get("control"),
                     meta.get("tolerance"), meta.get("carried"), meta.get("cleaned")))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def mpc_days(self, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        if start is None and end is None:
            with self._lock:                         # every day: kept until a day is computed again
                if self._mpc_all is None:
                    self._mpc_all = {r["day"]: dict(r) for r in self._q("SELECT * FROM mpc_days ORDER BY day")}
                return {k: dict(v) for k, v in self._mpc_all.items()}
        rows = self._q("SELECT * FROM mpc_days WHERE day>=? AND day<=? ORDER BY day", (start or "0000", end or "9999"))
        return {r["day"]: dict(r) for r in rows}

    def mpc_values(self, start: Optional[str] = None, end: Optional[str] = None,
                   meetings: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        sql = "SELECT day, meeting, step, level, cum, sigma, front FROM mpc_values WHERE day>=? AND day<=?"
        args: Tuple = (start or "0000", end or "9999")
        if meetings is not None:
            if not meetings:
                return []
            sql += " AND meeting IN (%s)" % ",".join("?" for _ in meetings)
            args += tuple(meetings)
        return [dict(r) for r in self._q(sql + " ORDER BY day, meeting", args)]

    def mpc_delete(self, days: Optional[List[str]] = None) -> None:
        with self._lock:
            self._mpc_all = None
            if days is None:
                self._db.execute("DELETE FROM mpc_values")
                self._db.execute("DELETE FROM mpc_days")
            else:
                self._db.executemany("DELETE FROM mpc_values WHERE day=?", [(d,) for d in days])
                self._db.executemany("DELETE FROM mpc_days WHERE day=?", [(d,) for d in days])

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

    # ------------------------------------------------------------------ the closes the watch keeps itself
    def close_upsert(self, rows: List[Tuple[str, str, float]]) -> int:
        """The day's last value of what is watched ``[(subject key, yyyy-mm-dd, value), ...]`` (kept apart from
        the market history: these are the dashboard's own readings, of anything - a VİOP spread, an ASW, an
        expression)."""
        if not rows:
            return 0
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.executemany("INSERT INTO watch_closes (subject, day, value) VALUES (?,?,?) "
                                     "ON CONFLICT(subject, day) DO UPDATE SET value=excluded.value",
                                     [(k, d, float(v)) for k, d, v in rows])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return len(rows)

    def closes(self, subjects: List[str], start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        """``{subject key: {day: value}}``."""
        out: Dict[str, Dict[str, float]] = {s: {} for s in subjects}
        for i in range(0, len(subjects), 400):
            chunk = subjects[i:i + 400]
            marks = ",".join("?" for _ in chunk)
            for r in self._q("SELECT subject, day, value FROM watch_closes WHERE subject IN (%s) AND day>=? AND day<=?" % marks,
                             tuple(chunk) + (start or "0000", end or "9999")):
                out[r["subject"]][r["day"]] = r["value"]
        return out

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
