"""SQLite persistence: users, personal inputs, named scenarios, shared inputs (RET curve ...), blotter."""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

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
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY, user TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, ip TEXT);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user);
"""


#: table -> columns added after its first version: the solver's own check of a day (largest distance between
#: model and quote in bp, and what the workbook tolerates), how many quotes were not that day's own close and
#: which closes were not used (the roots of their tickers); a user's sign-in: the password hash, administrator
#: or not, active / waiting for approval / closed, the note sent with a request and who decided on it, the wrong
#: passwords in a row and until when the name is locked.  A user of an earlier version is an active user without
#: a password: they ask for an account under the same name to set one.
_ADDED_COLUMNS = {"mpc_days": (("control", "REAL"), ("tolerance", "REAL"), ("carried", "INTEGER"), ("cleaned", "TEXT")),
                  "users": (("pw_hash", "TEXT"), ("role", "TEXT NOT NULL DEFAULT 'user'"),
                            ("status", "TEXT NOT NULL DEFAULT 'active'"), ("note", "TEXT"), ("requested_at", "TEXT"),
                            ("decided_by", "TEXT"), ("decided_at", "TEXT"), ("failed", "INTEGER NOT NULL DEFAULT 0"),
                            ("locked_until", "TEXT"), ("requested_new", "INTEGER NOT NULL DEFAULT 0"))}
_ACCOUNT_FIELDS = ("display", "last_seen", "pw_hash", "role", "status", "note", "requested_at", "decided_by", "decided_at",
                   "failed", "locked_until", "requested_new")


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def user_key(name: str) -> str:
    """Canonical key of a user name: case, surrounding blanks and the Turkish dotted / dotless i do not
    create new users ("AYŞE YILMAZ", "Ayşe Yılmaz" and "ayşe yilmaz" are one person)."""
    key = " ".join(name.strip().split()).casefold()
    return key.replace("\u0307", "").replace("\u0131", "i")


class Store(object):
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
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
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE user=?", (key,))
            self._db.execute("DELETE FROM users WHERE name=?", (key,))

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
    def user_inputs(self, user: str, book: Optional[str] = None) -> Dict[Tuple[str, str], Any]:
        if book is None:
            rows = self._q("SELECT book, cell, value FROM user_inputs WHERE user=?", (user,))
        else:
            rows = self._q("SELECT book, cell, value FROM user_inputs WHERE user=? AND book=?", (user, book))
        return {(r["book"], r["cell"]): json.loads(r["value"]) for r in rows}

    def set_user_inputs(self, user: str, book: str, values: Dict[str, Any]) -> None:
        ts = now_iso()
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for cell, v in values.items():
                    self._db.execute(
                        "INSERT INTO user_inputs (user, book, cell, value, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(user, book, cell) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                        (user, book, cell, json.dumps(v, ensure_ascii=False), ts))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def clear_user_inputs(self, user: str, book: Optional[str] = None, cells: Optional[List[str]] = None) -> None:
        with self._lock:
            if cells is not None:
                self._db.executemany("DELETE FROM user_inputs WHERE user=? AND book=? AND cell=?",
                                     [(user, book, c) for c in cells])
            elif book is not None:
                self._db.execute("DELETE FROM user_inputs WHERE user=? AND book=?", (user, book))
            else:
                self._db.execute("DELETE FROM user_inputs WHERE user=?", (user,))

    def replace_user_inputs(self, user: str, values: Dict[Tuple[str, str], Any]) -> None:
        ts = now_iso()
        with self._lock:
            self._db.execute("BEGIN")
            try:
                self._db.execute("DELETE FROM user_inputs WHERE user=?", (user,))
                self._db.executemany(
                    "INSERT INTO user_inputs (user, book, cell, value, updated_at) VALUES (?,?,?,?,?)",
                    [(user, b, c, json.dumps(v, ensure_ascii=False), ts) for (b, c), v in values.items()])
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ named scenarios
    def scenarios(self, user: str) -> List[Dict[str, Any]]:
        rows = self._q("SELECT id, name, payload, created_at, updated_at FROM scenarios WHERE user=? ORDER BY name", (user,))
        out = []
        for r in rows:
            out.append({"id": r["id"], "name": r["name"], "created_at": r["created_at"], "updated_at": r["updated_at"],
                        "cells": len(json.loads(r["payload"]))})
        return out

    def save_scenario(self, user: str, name: str, values: Dict[Tuple[str, str], Any]) -> Dict[str, Any]:
        name = " ".join(name.strip().split())
        if not name:
            raise ValueError("senaryo adı boş olamaz")
        if len(name) > 60:
            raise ValueError("senaryo adı en fazla 60 karakter olabilir")
        payload = json.dumps([[b, c, v] for (b, c), v in sorted(values.items())], ensure_ascii=False)
        ts = now_iso()
        self._x("INSERT INTO scenarios (user, name, payload, created_at, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(user, name) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (user, name, payload, ts, ts))
        return {"name": name, "cells": len(values), "updated_at": ts}

    def load_scenario(self, user: str, name: str) -> Optional[Dict[Tuple[str, str], Any]]:
        rows = self._q("SELECT payload FROM scenarios WHERE user=? AND name=?", (user, name))
        if not rows:
            return None
        return {(b, c): v for b, c, v in json.loads(rows[0]["payload"])}

    def delete_scenario(self, user: str, name: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM scenarios WHERE user=? AND name=?", (user, name))
            return cur.rowcount > 0

    # ------------------------------------------------------------------ shared inputs
    def shared_inputs(self, book: Optional[str] = None) -> Dict[Tuple[str, str], Any]:
        if book is None:
            rows = self._q("SELECT book, cell, value FROM shared_inputs")
        else:
            rows = self._q("SELECT book, cell, value FROM shared_inputs WHERE book=?", (book,))
        return {(r["book"], r["cell"]): json.loads(r["value"]) for r in rows}

    def shared_meta(self, book: str, cells: List[str]) -> Optional[Dict[str, Any]]:
        """Who changed any of the cells last, and when."""
        if not cells:
            return None
        marks = ",".join("?" for _ in cells)
        rows = self._q("SELECT updated_by, updated_at FROM shared_inputs WHERE book=? AND cell IN (%s) "
                       "ORDER BY updated_at DESC LIMIT 1" % marks, (book,) + tuple(cells))
        return dict(rows[0]) if rows else None

    def set_shared_inputs(self, book: str, values: Dict[str, Any], user: Optional[str]) -> None:
        ts = now_iso()
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for cell, v in values.items():
                    self._db.execute(
                        "INSERT INTO shared_inputs (book, cell, value, updated_by, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(book, cell) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, "
                        "updated_at=excluded.updated_at", (book, cell, json.dumps(v, ensure_ascii=False), user, ts))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def clear_shared_inputs(self, book: str, cells: List[str]) -> None:
        with self._lock:
            self._db.executemany("DELETE FROM shared_inputs WHERE book=? AND cell=?", [(book, c) for c in cells])

    # ------------------------------------------------------------------ RET curve history
    def add_ret_history(self, user: Optional[str], rows: List[Dict[str, Any]]) -> int:
        return self._x("INSERT INTO ret_history (ts, user, payload) VALUES (?,?,?)",
                       (now_iso(), user, json.dumps(rows, ensure_ascii=False)))

    def ret_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._q("SELECT id, ts, user, payload FROM ret_history ORDER BY id DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "ts": r["ts"], "user": r["user"], "rows": json.loads(r["payload"])} for r in rows]

    # ------------------------------------------------------------------ blotter
    def add_trade(self, trade_date: str, kind: str, payload: Dict[str, Any], user: Optional[str],
                  package: Optional[str] = None) -> int:
        ts = now_iso()
        return self._x("INSERT INTO trades (trade_date, kind, package, payload, created_by, created_at, updated_by, "
                       "updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       (trade_date, kind, package, json.dumps(payload, ensure_ascii=False), user, ts, user, ts))

    def update_trade(self, trade_id: int, payload: Dict[str, Any], user: Optional[str]) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE trades SET payload=?, updated_by=?, updated_at=? WHERE id=? AND deleted=0",
                                   (json.dumps(payload, ensure_ascii=False), user, now_iso(), trade_id))
            return cur.rowcount > 0

    def delete_trade(self, trade_id: int, user: Optional[str]) -> List[int]:
        """Soft-delete a trade (and the other legs of its package); returns the ids removed."""
        with self._lock:
            rows = self._db.execute("SELECT id, package FROM trades WHERE id=? AND deleted=0", (trade_id,)).fetchall()
            if not rows:
                return []
            pkg = rows[0]["package"]
            if pkg:
                ids = [r["id"] for r in self._db.execute(
                    "SELECT id FROM trades WHERE package=? AND deleted=0", (pkg,)).fetchall()]
            else:
                ids = [trade_id]
            ts = now_iso()
            self._db.executemany("UPDATE trades SET deleted=1, updated_by=?, updated_at=? WHERE id=?",
                                 [(user, ts, i) for i in ids])
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
        Returns (ids of the new rows, number skipped)."""
        ids: List[int] = []
        skipped = 0
        ts = now_iso()
        with self._lock:
            for row in rows:
                day, time, mark = row["date"], row["time"], row["mark"]
                found = self._db.execute("SELECT id FROM broker_quotes WHERE quote_date=? AND quote_time=? AND mark=? AND deleted=0",
                                         (day, time, mark)).fetchone()
                if found:
                    skipped += 1
                    continue
                cur = self._db.execute("INSERT INTO broker_quotes (quote_date, quote_time, mark, payload, created_by, created_at) "
                                       "VALUES (?,?,?,?,?,?)", (day, time, mark, json.dumps(row, ensure_ascii=False), user, ts))
                ids.append(cur.lastrowid)
        return ids, skipped

    def broker_marks(self, day: str) -> set:
        rows = self._q("SELECT quote_time, mark FROM broker_quotes WHERE quote_date=? AND deleted=0", (day,))
        return {(r["quote_time"], r["mark"]) for r in rows}

    def broker_quotes(self, day: str, until: Optional[str] = None) -> List[Dict[str, Any]]:
        """The rows of a day, or of every day from ``day`` to ``until``, in the order they were said."""
        rows = self._q("SELECT * FROM broker_quotes WHERE quote_date>=? AND quote_date<=? AND deleted=0 "
                       "ORDER BY quote_date, quote_time, id", (day, until or day))
        out = []
        for r in rows:
            d = json.loads(r["payload"])
            d.update({"id": r["id"], "date": r["quote_date"], "time": r["quote_time"], "created_by": r["created_by"],
                      "created_at": r["created_at"]})
            out.append(d)
        return out

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

    # ------------------------------------------------------------------ cells that move with their meeting
    def remap_user_cells(self, book: str, mapping: Dict[str, Optional[str]]) -> Dict[str, int]:
        """Move personal inputs (and the cells of saved scenarios) of one workbook to other cells.

        ``mapping``: old cell -> new cell (``None``: the value is dropped).  All of it happens in one
        transaction, for every user: what was typed for a meeting stays with that meeting when the list of
        meetings is shifted.  Returns how many values moved / were dropped.
        """
        if not mapping:
            return {"moved": 0, "dropped": 0, "scenarios": 0}
        ts = now_iso()
        moved = dropped = touched = 0
        with self._lock:
            self._db.execute("BEGIN")
            try:
                marks = ",".join("?" for _ in mapping)
                rows = self._db.execute("SELECT user, cell, value FROM user_inputs WHERE book=? AND cell IN (%s)" % marks,
                                        (book,) + tuple(mapping)).fetchall()
                self._db.execute("DELETE FROM user_inputs WHERE book=? AND cell IN (%s)" % marks, (book,) + tuple(mapping))
                for r in rows:
                    new = mapping[r["cell"]]
                    if new is None:
                        dropped += 1
                        continue
                    moved += 1 if new != r["cell"] else 0
                    self._db.execute(
                        "INSERT INTO user_inputs (user, book, cell, value, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(user, book, cell) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                        (r["user"], book, new, r["value"], ts))
                for r in self._db.execute("SELECT id, payload FROM scenarios").fetchall():
                    items = json.loads(r["payload"])
                    out, changed = [], False
                    for b, c, v in items:
                        if b == book and c in mapping:
                            new = mapping[c]
                            changed = changed or new != c
                            if new is None:
                                continue
                            out.append([b, new, v])
                        else:
                            out.append([b, c, v])
                    if changed:
                        touched += 1
                        self._db.execute("UPDATE scenarios SET payload=?, updated_at=? WHERE id=?",
                                         (json.dumps(sorted(out, key=lambda x: (x[0], x[1])), ensure_ascii=False), ts, r["id"]))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return {"moved": moved, "dropped": dropped, "scenarios": touched}

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
        """``{series: (first day, last day, count)}``."""
        return {r["series"]: (r["a"], r["b"], r["n"]) for r in self._q(
            "SELECT series, MIN(day) AS a, MAX(day) AS b, COUNT(*) AS n FROM hist_values GROUP BY series")}

    def hist_delete(self, series: Optional[str] = None) -> None:
        with self._lock:
            if series is None:
                self._db.execute("DELETE FROM hist_values")
            else:
                self._db.execute("DELETE FROM hist_values WHERE series=?", (series,))

    # ------------------------------------------------------------------ what was priced for the MPC meetings, per day
    def mpc_save(self, day: str, basis: str, meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
        """Replace one day: ``rows`` = ``[{"meeting", "step", "level", "cum", "sigma", "front"}, ...]``."""
        with self._lock:
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
            if days is None:
                self._db.execute("DELETE FROM mpc_values")
                self._db.execute("DELETE FROM mpc_days")
            else:
                self._db.executemany("DELETE FROM mpc_values WHERE day=?", [(d,) for d in days])
                self._db.executemany("DELETE FROM mpc_days WHERE day=?", [(d,) for d in days])

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
