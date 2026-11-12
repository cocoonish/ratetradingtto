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
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def user_key(name: str) -> str:
    """Canonical key of a user name (case / surrounding blanks do not create new users)."""
    return " ".join(name.strip().split()).casefold()


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

    def trades(self, trade_date: str) -> List[Dict[str, Any]]:
        rows = self._q("SELECT * FROM trades WHERE trade_date=? AND deleted=0 ORDER BY id", (trade_date,))
        out = []
        for r in rows:
            d = json.loads(r["payload"])
            d.update({"id": r["id"], "kind": r["kind"], "package": r["package"], "trade_date": r["trade_date"],
                      "created_by": r["created_by"], "created_at": r["created_at"],
                      "updated_by": r["updated_by"], "updated_at": r["updated_at"]})
            out.append(d)
        return out

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

    # ------------------------------------------------------------------ misc key/value
    def get(self, key: str, default: Any = None) -> Any:
        rows = self._q("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def put(self, key: str, value: Any) -> None:
        self._x("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))
