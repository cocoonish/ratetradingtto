"""The history's reads answered by SQLite, as the store answered them before it kept its history tables in memory
(``tto/store.py``): the reference the tests compare the memory with - and a spy on the store's connection that records
which thread asked SQLite what."""
from __future__ import annotations

import functools
import threading
from typing import Any, Dict, List, Optional, Tuple

#: the tables the store answers from memory
TABLES = ("hist_values", "watch_closes", "mpc_days", "mpc_values")


def hist_many(store, series: List[str], start: Optional[str] = None, end: Optional[str] = None,
              table: str = "hist_values", key: str = "series") -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {s: {} for s in series}
    for i in range(0, len(series), 400):
        chunk = series[i:i + 400]
        marks = ",".join("?" for _ in chunk)
        for r in store._q("SELECT %s, day, value FROM %s WHERE %s IN (%s) AND day>=? AND day<=?" % (key, table, key, marks),
                          tuple(chunk) + (start or "0000", end or "9999")):
            out[r[key]][r["day"]] = r["value"]
    return out


def closes(store, subjects: List[str], start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    return hist_many(store, subjects, start, end, "watch_closes", "subject")


def hist_series(store, series: str, start: Optional[str] = None, end: Optional[str] = None) -> List[Tuple[str, float]]:
    return [(r["day"], r["value"]) for r in store._q("SELECT day, value FROM hist_values WHERE series=? AND day>=? AND day<=? "
                                                     "ORDER BY day", (series, start or "0000", end or "9999"))]


def hist_bounds(store) -> Dict[str, Tuple[str, str, int]]:
    return {r["series"]: (r["a"], r["b"], r["n"]) for r in store._q(
        "SELECT series, MIN(day) AS a, MAX(day) AS b, COUNT(*) AS n FROM hist_values GROUP BY series")}


def mpc_days(store, start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    if start is None and end is None:
        rows = store._q("SELECT * FROM mpc_days ORDER BY day")
    else:
        rows = store._q("SELECT * FROM mpc_days WHERE day>=? AND day<=? ORDER BY day", (start or "0000", end or "9999"))
    return {r["day"]: dict(r) for r in rows}


def mpc_values(store, start: Optional[str] = None, end: Optional[str] = None,
               meetings: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    sql = "SELECT day, meeting, step, level, cum, sigma, front FROM mpc_values WHERE day>=? AND day<=?"
    args: Tuple = (start or "0000", end or "9999")
    if meetings is not None:
        if not meetings:
            return []
        sql += " AND meeting IN (%s)" % ",".join("?" for _ in meetings)
        args += tuple(meetings)
    return [dict(r) for r in store._q(sql + " ORDER BY day, meeting", args)]


READS = {"hist_many": hist_many, "closes": closes, "hist_series": hist_series, "hist_bounds": hist_bounds,
         "mpc_days": mpc_days, "mpc_values": mpc_values}


def from_sql(monkeypatch, store) -> None:
    """The store answers its history reads from SQLite again, row by row (the reference)."""
    for name, fn in READS.items():
        monkeypatch.setattr(store, name, functools.partial(fn, store))


def same(a: Any, b: Any, path: str = "$") -> None:
    """Equal - with the same types, the same order of keys and the same sign of a zero (what JSON would show)."""
    assert type(a) is type(b), "%s: %r vs %r" % (path, a, b)
    if isinstance(a, dict):
        assert list(a) == list(b), "%s: keys %r vs %r" % (path, list(a)[:6], list(b)[:6])
        for k in a:
            same(a[k], b[k], "%s.%s" % (path, k))
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), "%s: %d vs %d items" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, "%s[%d]" % (path, i))
    elif isinstance(a, float):
        assert repr(a) == repr(b), "%s: %r vs %r" % (path, a, b)
    else:
        assert a == b, "%s: %r vs %r" % (path, a, b)


class Spy(object):
    """The store's connection, recording ``(thread name, SQL)`` of every statement run on it."""

    def __init__(self, db) -> None:
        self._db = db
        self.asked: List[Tuple[str, str]] = []

    def execute(self, sql: str, *args: Any):
        self.asked.append((threading.current_thread().name, sql))
        return self._db.execute(sql, *args)

    def executemany(self, sql: str, *args: Any):
        self.asked.append((threading.current_thread().name, sql))
        return self._db.executemany(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._db, name)

    def history(self, thread: Optional[str] = None) -> List[str]:
        """The statements on the history's tables (of one thread)."""
        return [sql for t, sql in self.asked if (thread is None or t == thread) and any(x in sql for x in TABLES)]

    def reads(self, thread: Optional[str] = None) -> List[str]:
        """... the reads among them (a write - the watch keeping the day's closes - goes to the file, as it should)."""
        return [sql for sql in self.history(thread) if sql.lstrip().upper().startswith("SELECT")]


def spy(monkeypatch, store) -> Spy:
    s = Spy(store._db)
    monkeypatch.setattr(store, "_db", s)
    return s
