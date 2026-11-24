"""Bring back what a damaged database still holds: ``python -m tto kurtar <bozuk.db>`` (the dashboard stopped).

The desk's way after a damaged file (README, "Veritabanı bozulursa"): close the dashboard everywhere, go back to the
last backup (``yedekten-don``: the damaged file stays beside the database as ``tto.db.onceki-<time>``), then this,
which reads every table of the damaged file as far as SQLite can and adds to the database now - the backup, typically
- the rows it lacks.  ``--dene`` says what it would do and changes nothing (it works on a copy of the database).

* **Reading** (:class:`Damaged`).  A copy of the damaged file (with its ``-wal`` / ``-journal``, without them when
  they cannot be read) in a scratch folder: the file itself is never opened, so never changed.  It is opened (its list
  of tables read) before the database is: a file SQLite cannot read at all leaves the database untouched.
  - Each table is read in key order (the rowid, or a table without rowid by its primary key) in chunks; where SQLite
    says the file is damaged, one row at a time up to the spot (``LIMIT 1``: Python's sqlite3 before 3.11 loses the row
    before an error while it iterates), then past it.  The next key that reads is looked for - a rowid doubling, then
    halving back; a table without rowid tries the keys the database now has, the keys its own indexes give and its
    key's last column moved on (a day, a number), then the next group of its first columns - and read backwards from
    there (a table without rowid keeps rows in its inner pages too: the one above a damaged leaf is reached that way
    only).  The keys in between are unreadable.
  - The table's indexes hold every row's key: which rows could not be read - and whether the database now has them -
    is said by them.
  - A row whose values are not what its columns hold (a NULL where none may be, text in a number's column, JSON that
    does not read, a date that is none) is unreadable too: nothing of it is written.
* **Adding** (:func:`merge`, table by table - RULES -, in one transaction: all of it or nothing; a copy of the
  database as it was is kept beside it first, ``tto.db.kurtarma-oncesi-<time>``, dropped again when nothing changed).
  A row the database lacks is added, by the table's own key.  A row it has is never overwritten, but where RULES
  says:
  - the table carries the row's own time (``newer``) and the damaged file's row is the later one: a user's input
    typed again, a trade changed or deleted on the day, an agenda item done;
  - a flag that only ever goes on (``flags``: Broker Chat's deleted line);
  - the ``kv`` entries that count what Bloomberg was asked today (KV_MERGE) - so that today's requests are not made
    again against the daily limit - are merged entry by entry.
  A row the database numbers itself (``id``) is the same row when its number and its birth (who made it, when) agree;
  a number the database gave another row meanwhile (the dashboard ran on the backup before the recovery) takes a new
  number, and its children (Trades' log and closes, the agenda's days) follow it.
* History tables (``hist_values`` ...) may stay unread: the dashboard fetches the missing days itself (only new days).
"""
from __future__ import annotations

import bisect
import collections
import datetime as _dt
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("tto.recover")

#: rows read at a time where nothing is damaged
CHUNK = 2000
#: columns that hold a day or a time stamp ("2026-11-24 ...") in the dashboard's tables
DATE_COLS = frozenset(("created_at", "updated_at", "ts", "trade_date", "quote_date", "expires_at", "computed_at", "taken_at",
                       "last_seen", "requested_at", "decided_at", "done_at", "last_login", "day"))
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
#: the damaged files ``yedekten-don`` leaves beside the database
KEPT = re.compile(r"^tto\.db\.onceki-\d{8}-\d{6}$")


class RecoverError(ValueError):
    """The recovery cannot run - why, in Turkish."""


class Rule(object):
    """How one table's rows come back (the module's text).

    ``key``: the columns that name a row (``None``: the database's own number ``id``, with ``birth``: the columns
    fixed when the row was made); ``newer``: the row's own time - the later row wins; ``flags``: columns that only
    ever go from 0 to 1; ``group``: rows written together per this column (a day's) - a group the database has is left
    as it is; ``parent``: (column, table) - the row belongs to that table's row of that number; ``history``: may stay
    unread (fetched again); ``day``: the day a row is about (the summary's "(24.11)"); ``who``: the user a row is of;
    ``json``: columns of JSON text; ``ignore``: columns that change by themselves (not a difference worth saying)."""

    def __init__(self, table: str, label: str, unit: str = "satır", key: Optional[Tuple[str, ...]] = None,
                 birth: Tuple[str, ...] = (), newer: Optional[str] = None, flags: Tuple[str, ...] = (),
                 group: Optional[str] = None, parent: Optional[Tuple[str, str]] = None, history: bool = False,
                 day: Optional[str] = None, who: Optional[str] = None, json: Tuple[str, ...] = (),
                 ignore: Tuple[str, ...] = ()):
        self.table, self.label, self.unit = table, label, unit
        self.key, self.birth, self.newer, self.flags = key, birth, newer, flags
        self.group, self.parent, self.history, self.day, self.who = group, parent, history, day, who
        self.json, self.ignore = json, ignore


#: every table of the store, parents before their children (store.py's _SCHEMA)
RULES = (
    Rule("users", "hesaplar", "hesap", key=("name",),
         ignore=("last_seen", "last_login", "last_login_ip", "failed", "locked_until")),
    Rule("sessions", "oturumlar", "oturum", key=("token",)),
    Rule("user_inputs", "kişisel girdiler", "girdi", key=("user", "book", "cell"), newer="updated_at", who="user",
         json=("value",)),
    Rule("shared_inputs", "ortak girdiler", "girdi", key=("book", "cell"), newer="updated_at", json=("value",)),
    Rule("scenarios", "senaryolar", "senaryo", key=("user", "name"), newer="updated_at", who="user", json=("payload",)),
    Rule("trades", "Günlük İşlemler", "işlem", birth=("created_at", "created_by"), newer="updated_at", day="trade_date",
         json=("payload",)),
    Rule("blotter_snapshots", "Günlük İşlemler'in gün görüntüleri", "gün", key=("trade_date",), newer="updated_at",
         day="trade_date", json=("payload",)),
    Rule("trade_templates", "işlem şablonları", "şablon", birth=("created_at", "created_by"), newer="updated_at",
         json=("payload",)),
    Rule("broker_quotes", "Broker Chat", "satır", birth=("created_at", "created_by"), flags=("deleted",), day="quote_date",
         json=("payload",)),
    Rule("tradebook", "Trades", "işlem", birth=("created_at", "created_by"), newer="updated_at", day="trade_date",
         json=("payload",)),
    Rule("tradebook_log", "Trades günlüğü", "kayıt", birth=("ts", "user", "trade"), parent=("trade", "tradebook"),
         json=("detail",)),
    Rule("tradebook_close_days", "Trades kapanışları", "gün", key=("day",), day="day"),
    Rule("tradebook_closes", "Trades kapanış değerleri", "değer", key=("day", "trade"), group="day",
         parent=("trade", "tradebook"), day="day", json=("payload",)),
    Rule("ret_history", "RET yüklemeleri", "yükleme", birth=("ts", "user"), json=("payload", "meta")),
    Rule("ret_fair_log", "RET adil değer günlüğü", "kayıt", birth=("ts", "user")),
    Rule("feedback", "geri bildirimler", "bildirim", birth=("created_at", "created_by"), newer="done_at"),
    Rule("chat", "chat", "mesaj", birth=("created_at", "user"), day="created_at"),
    Rule("agenda", "ajanda", "madde", birth=("created_at", "created_by"), newer="done_at", day="day"),
    Rule("agenda_rules", "ajandanın tekrarlayan işleri", "iş", birth=("created_at", "created_by"), newer="updated_at"),
    Rule("agenda_rule_days", "tekrarlayan işlerin yapıldığı günler", "gün", key=("rule", "day"),
         parent=("rule", "agenda_rules")),
    Rule("agenda_snoozes", "ajanda ertelemeleri", "erteleme", key=("user", "rule", "day"), parent=("rule", "agenda_rules")),
    Rule("kv", "ayarlar ve kayıtlar (kv)", "kayıt", key=("key",), json=("value",)),
    Rule("bbg_answers", "Bloomberg'in bugünkü cevapları", "cevap", key=("key",), newer="fetched", day="day"),
    Rule("hist_values", "günlük tarihçe", "kapanış", key=("series", "day"), history=True, day="day"),
    Rule("watch_closes", "izleme kapanışları", "kapanış", key=("subject", "day"), history=True, day="day"),
    Rule("mpc_days", "PPK fiyatlama geçmişi", "gün", key=("day",), history=True, day="day"),
    Rule("mpc_values", "PPK fiyatlama geçmişinin değerleri", "değer", key=("day", "meeting"), group="day", history=True,
         day="day"),
)


# ---------------------------------------------------------------------- kv: what Bloomberg was asked today
def _bbg_hits(mine: Any, theirs: Any) -> Any:
    """The day's Bloomberg count (``{"day", "hits"}``): the later day, or the same day's larger count."""
    def k(v: Any) -> Tuple[str, int]:
        try:
            return (str(v.get("day") or ""), int(v.get("hits") or 0))
        except (AttributeError, TypeError, ValueError):
            return ("", -1)
    return theirs if k(theirs) > k(mine) else mine


def _hist_fetch(mine: Any, theirs: Any) -> Any:
    """The history's record of the full ranges asked (series -> {"day", "from", "first", "tail"}): per series the record
    of the later day."""
    if not isinstance(theirs, dict):
        return mine
    out = dict(mine) if isinstance(mine, dict) else {}

    def when(rec: Any) -> str:
        return max(str(rec.get("day") or ""), str(rec.get("tail") or "")) if isinstance(rec, dict) else ""
    for sid, rec in theirs.items():
        if isinstance(rec, dict) and when(rec) > when(out.get(sid)):
            out[sid] = rec
    return out


def _latest_each(mine: Any, theirs: Any) -> Any:
    """series -> when it was last asked (seconds): the later of each."""
    if not isinstance(theirs, dict):
        return mine
    out = dict(mine) if isinstance(mine, dict) else {}
    for k, v in theirs.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and (
                not isinstance(out.get(k), (int, float)) or v > out[k]):
            out[k] = v
    return out


def _each_once(mine: Any, theirs: Any) -> Any:
    """Entries asked once each (ISIN -> facts): the ones the database lacks are added, none is replaced."""
    if not isinstance(theirs, dict):
        return mine
    out = dict(mine) if isinstance(mine, dict) else {}
    for k, v in theirs.items():
        out.setdefault(k, v)
    return out


#: kv entries merged entry by entry - they count what Bloomberg was asked today (the daily limit): key -> (merge, what
#: it is, as the summary says it)
KV_MERGE: Dict[str, Tuple[Callable[[Any, Any], Any], str]] = {
    "bbg.hits": (_bbg_hits, "Bloomberg'in bugünkü veri sayacı (günlük limit koruması bugünü buradan sayar)"),
    "hist.fetch": (_hist_fetch, "tarihçenin istek kaydı (bugün istenen tam aralıklar yeniden istenmez)"),
    "fx.hist.asked": (_latest_each, "Spot / FX tarihçesinin istek kaydı (bugün istenenler yeniden istenmez)"),
    "fiyatyukleme.eurobonds": (_each_once, "Eurobond bilgileri (ISIN başına bir kez istenir)"),
}


# ---------------------------------------------------------------------- reading the damaged file
def _q(name: str) -> str:
    return '"%s"' % name.replace('"', '""')


def _affinity(declared: str) -> str:
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


class Read(object):
    """What could be read of one table of the damaged file."""

    def __init__(self, table: str):
        self.table = table
        self.columns: List[str] = []
        self.keycols: List[str] = []
        self.rowid = True
        self.rows: List[Dict[str, Any]] = []
        self.keys: List[Tuple[Any, ...]] = []             # each row's key (rowid, or the primary key), aligned with rows
        self.gaps: List[Tuple[Any, Any]] = []             # (the last key read, the next one read - None: none after)
        self.failed: Optional[str] = None                 # nothing could be read: why
        self.bad: List[Dict[str, Any]] = []               # rows read whose values are not what their columns hold
        self.indexed: Optional[Dict[Tuple[Any, ...], Dict[str, Any]]] = None   # key -> what the indexes say of it
        self.index_whole = False                          # ... read whole (every row's key)

    def missing(self) -> Optional[List[Tuple[Tuple[Any, ...], Dict[str, Any]]]]:
        """The rows the indexes name that could not be read (``None``: no index read to tell)."""
        if self.indexed is None:
            return None
        have = set(self.keys)
        return sorted(((k, v) for k, v in self.indexed.items() if k not in have), key=lambda kv: kv[0])

    def damaged(self) -> bool:
        return bool(self.failed or self.gaps or self.bad or self.missing())


class _Table(object):
    """One table of the damaged copy, read as far as SQLite can (the module's text)."""

    def __init__(self, con: sqlite3.Connection, name: str, sql: str,
                 candidates: Callable[[str, List[str]], List[Tuple[Any, ...]]]):
        self.con, self.name, self.candidates = con, name, candidates
        self.read = Read(name)
        info = con.execute("PRAGMA table_info(%s)" % _q(name)).fetchall()
        r = self.read
        r.columns = [i[1] for i in info]
        r.rowid = "WITHOUT ROWID" not in " ".join((sql or "").upper().split())
        r.keycols = ["rowid"] if r.rowid else [i[1] for i in sorted((i for i in info if i[5]), key=lambda i: i[5])]
        keys = ", ".join("rowid" if c == "rowid" else _q(c) for c in r.keycols)
        self.n = len(r.keycols)
        self.sel = "SELECT %s, %s FROM %s" % (keys, ", ".join(_q(c) for c in r.columns), _q(name))
        self.order = " ORDER BY %s" % keys
        self.desc = " ORDER BY %s" % ", ".join("%s DESC" % k for k in keys.split(", "))
        self.kexpr = "(%s)" % keys
        self.marks = "(%s)" % ", ".join("?" for _ in r.keycols)
        self._probe_keys: Optional[List[Tuple[Any, ...]]] = None

    def fetch(self, op: Optional[str], pos: Optional[Tuple[Any, ...]], limit: int) -> List[Tuple[Any, ...]]:
        where = " WHERE %s %s %s" % (self.kexpr, op, self.marks) if op else ""
        return self.con.execute(self.sel + where + self.order + " LIMIT %d" % limit, tuple(pos or ())).fetchall()

    def run(self) -> Read:
        r = self.read
        got: List[Tuple[Any, ...]] = []
        pos: Optional[Tuple[Any, ...]] = None
        while True:
            try:
                part = self.fetch(">" if pos is not None else None, pos, CHUNK)
            except sqlite3.DatabaseError:
                part = None
            if part is not None:
                got.extend(part)
                if len(part) < CHUNK:
                    break
                pos = tuple(part[-1][:self.n])
                continue
            # a damaged spot in this chunk: one row at a time up to it (LIMIT 1: nothing beyond the row is read)
            end = stuck = False
            for _ in range(CHUNK + 1):
                try:
                    one = self.fetch(">" if pos is not None else None, pos, 1)
                except sqlite3.DatabaseError:
                    stuck = True
                    break
                if not one:
                    end = True
                    break
                got.append(one[0])
                pos = tuple(one[0][:self.n])
            if end:
                break
            if not stuck:
                continue                                   # (the chunk's spot was not met: chunks again)
            nxt = self.skip(pos)
            if nxt is None:
                r.gaps.append((pos, None))
                break
            back = self.back_from(pos, tuple(nxt[:self.n]))
            r.gaps.append((pos, tuple((back or [nxt])[0][:self.n])))
            got.extend(back)
            got.append(nxt)
            pos = tuple(nxt[:self.n])
        if not got and r.gaps and r.gaps[0][1] is None:
            r.failed = "tablonun hiçbir satırına ulaşılamadı"
        for row in got:
            r.keys.append(tuple(row[:self.n]))
            r.rows.append(dict(zip(r.columns, row[self.n:])))
        if r.gaps:
            self.index_keys()
        return r

    def probe(self, key: Tuple[Any, ...]) -> Optional[Tuple[Any, ...]]:
        """The first row at or after ``key`` (``None``: none there); raises where the file is damaged."""
        got = self.fetch(">=", key, 1)
        return got[0] if got else None

    def back_from(self, pos: Optional[Tuple[Any, ...]], upto: Tuple[Any, ...]) -> List[Tuple[Any, ...]]:
        """The rows between the damaged spot after ``pos`` and ``upto`` that read going backwards from ``upto``: a table
        without rowid keeps rows in its inner pages too (the one above a damaged leaf: a seek forward to it goes down
        into that leaf, a step back from the next leaf does not)."""
        out: List[Tuple[Any, ...]] = []
        at = upto
        for _ in range(CHUNK):
            try:
                got = self.con.execute(self.sel + " WHERE %s < %s" % (self.kexpr, self.marks) + self.desc + " LIMIT 1",
                                       tuple(at)).fetchall()
            except sqlite3.DatabaseError:
                break
            if not got:
                break
            key = tuple(got[0][:self.n])
            try:
                if pos is not None and key <= pos:
                    break
            except TypeError:
                break
            out.append(got[0])
            at = key
        return out[::-1]

    def skip(self, pos: Optional[Tuple[Any, ...]]) -> Optional[Tuple[Any, ...]]:
        """The first row that reads after the damaged spot just after ``pos`` (``None``: none does)."""
        if self.read.rowid:
            lo = int(pos[0]) if pos is not None else 0     # reading on from lo fails
            step, x, row = 1, None, None
            while True:
                x = lo + step
                if x >= 2 ** 62:
                    return None
                try:
                    row = self.probe((x,))
                    break
                except sqlite3.DatabaseError:
                    lo, step = x, step * 2
            a, b = lo, x                                   # a fails, b reads
            while b - a > 1:
                m = (a + b) // 2
                try:
                    row, b = self.probe((m,)), m
                except sqlite3.DatabaseError:
                    a = m
            return row
        # a table without rowid: keys to look with - the database's now, the ones the table's own indexes give and the
        # key's last column moved on (a day, a number: doubling) -, then the next group of its first columns
        keys = self.probe_keys()
        more = _successors(pos) if pos is not None else []
        if more:
            try:
                keys = sorted(set(keys).union(more))
            except TypeError:
                pass
        found, row = self._search(keys, pos)
        if found:
            return row
        for j in range(self.n - 1, 0, -1) if pos is not None else ():
            try:
                return self.after_prefix(j, pos[:j])
            except sqlite3.DatabaseError:
                continue
        return None

    def _search(self, keys: List[Tuple[Any, ...]], pos: Optional[Tuple[Any, ...]]) -> Tuple[bool, Optional[Tuple[Any, ...]]]:
        """The first of ``keys`` after ``pos`` from which a read works (doubling, then halving back): (found, its row)."""
        try:
            i0 = bisect.bisect_right(keys, pos) if pos is not None else 0
        except TypeError:                                  # (a key of another kind than the database's)
            return False, None
        if i0 >= len(keys):
            return False, None
        a, step = i0 - 1, 1                                # index a fails (i0 - 1: the spot itself)
        while True:
            i = min(i0 - 1 + step, len(keys) - 1)
            try:
                row = self.probe(keys[i])
                break
            except sqlite3.DatabaseError:
                a = i
                if i == len(keys) - 1:
                    return False, None
                step *= 2
        b = i
        while b - a > 1:
            m = (a + b) // 2
            try:
                row, b = self.probe(keys[m]), m
            except sqlite3.DatabaseError:
                a = m
        return True, self._refine(keys[a] if a >= i0 else pos, keys[b], row)

    def _refine(self, lo: Optional[Tuple[Any, ...]], hi: Tuple[Any, ...], row: Optional[Tuple[Any, ...]]
                ) -> Optional[Tuple[Any, ...]]:
        """Between a key that fails (``lo``) and one that reads (``hi``, its row) of one group: the first day / number
        from which a read works - the keys looked with may lie far apart (a day moved on by 64 ...)."""
        if lo is None or tuple(lo[:-1]) != tuple(hi[:-1]):
            return row
        head, a, b = tuple(hi[:-1]), lo[-1], hi[-1]
        if isinstance(a, str) and isinstance(b, str) and _DATE.match(a) and _DATE.match(b):
            try:
                a = _dt.date(int(lo[-1][:4]), int(lo[-1][5:7]), int(lo[-1][8:10])).toordinal()
                b = _dt.date(int(hi[-1][:4]), int(hi[-1][5:7]), int(hi[-1][8:10])).toordinal()
            except ValueError:
                return row

            def key(n: int) -> Tuple[Any, ...]:
                return head + (_dt.date.fromordinal(n).isoformat(),)
        elif type(a) is int and type(b) is int:
            def key(n: int) -> Tuple[Any, ...]:
                return head + (n,)
        else:
            return row
        while b - a > 1:
            m = (a + b) // 2
            try:
                row, b = self.probe(key(m)), m
            except sqlite3.DatabaseError:
                a = m
        return row

    def after_prefix(self, j: int, prefix: Tuple[Any, ...]) -> Optional[Tuple[Any, ...]]:
        """The first row whose key's first ``j`` columns come after ``prefix`` (``None``: none); raises where damaged."""
        cols = ", ".join(_q(c) for c in self.read.keycols[:j])
        got = self.con.execute(self.sel + " WHERE (%s) > (%s)" % (cols, ", ".join("?" for _ in prefix)) + self.order + " LIMIT 1",
                               tuple(prefix)).fetchall()
        return got[0] if got else None

    def probe_keys(self) -> List[Tuple[Any, ...]]:
        """Keys to look for the next readable row with (a table without rowid): the database's now and the ones this
        table's own indexes give."""
        if self._probe_keys is None:
            found = set(self.candidates(self.name, self.read.keycols))
            found.update(self.index_keys())
            try:
                self._probe_keys = sorted(found)
            except TypeError:                              # (keys of mixed kinds: the database's alone)
                self._probe_keys = sorted(set(self.candidates(self.name, self.read.keycols)))
        return self._probe_keys

    def index_keys(self) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
        """Every row's key as the table's indexes hold it, with the indexed columns (a trade's day ...): read from the
        indexes alone - they are other pages of the file.  The first index read whole; else what all of them gave."""
        r = self.read
        if r.indexed is not None:
            return r.indexed
        found: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        try:
            names = [x[0] for x in self.con.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                                                    (self.name,)).fetchall()]
        except sqlite3.DatabaseError:
            names = []
        for name in names:
            try:
                cols = [x[2] for x in self.con.execute("PRAGMA index_info(%s)" % _q(name)).fetchall() if x[2]]
            except sqlite3.DatabaseError:
                continue
            extra = [c for c in cols if c not in r.keycols]      # (an index of a table without rowid holds its key too)
            sql = "SELECT %s%s FROM %s INDEXED BY %s" % (
                ", ".join("rowid" if c == "rowid" else _q(c) for c in r.keycols),
                "".join(", " + _q(c) for c in extra), _q(self.name), _q(name))
            part: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
            whole = True
            try:
                for row in self.con.execute(sql):
                    part[tuple(row[:self.n])] = dict(zip(extra, row[self.n:]))
            except sqlite3.DatabaseError:
                whole = False
            if whole:
                r.indexed, r.index_whole = part, True
                return part
            for k, v in part.items():
                found.setdefault(k, {}).update(v)
        r.indexed = found if names else None
        return found


def _copy_damaged(damaged: str, scratch: str, with_log: bool) -> Tuple[str, List[str]]:
    base = os.path.join(scratch, "bozuk.db")
    for s in ("", "-wal", "-shm", "-journal"):
        if os.path.exists(base + s):
            os.remove(base + s)
    shutil.copyfile(damaged, base)
    logs = [s for s in ("-wal", "-journal") if with_log and os.path.isfile(damaged + s)]
    for s in logs:
        shutil.copyfile(damaged + s, base + s)
    return base, logs


def _successors(pos: Tuple[Any, ...]) -> List[Tuple[Any, ...]]:
    """Keys after ``pos`` with its last column moved on - a day by 1, 2, 4 ... days, a number by 1, 2, 4 ... - in the
    same group of its first columns: where the database knows no key to look with (a series new since the backup)."""
    head, last = tuple(pos[:-1]), pos[-1]
    if isinstance(last, str) and _DATE.match(last):
        try:
            day = _dt.date(int(last[:4]), int(last[5:7]), int(last[8:10]))
        except ValueError:
            return []
        return [head + ((day + _dt.timedelta(days=2 ** k)).isoformat(),) for k in range(14)]
    if type(last) is int:
        return [head + (last + 2 ** k,) for k in range(40)]
    return []


class Damaged(object):
    """The damaged file, opened from a copy in a scratch folder (the module's text): with its ``-wal`` / ``-journal``,
    or - when its table list cannot be read with them - without.  :class:`RecoverError` when SQLite cannot read the
    list of its tables at all (nothing can be had of it then)."""

    def __init__(self, damaged: str, scratch: str):
        self.path = damaged
        note = ""
        con = None
        schema: List[Tuple[Any, ...]] = []
        logs: List[str] = []
        for with_log in (True, False):
            if not with_log and not os.path.isfile(damaged + "-wal") and not os.path.isfile(damaged + "-journal"):
                break                                    # (no log beside it: tried as it is already)
            base, logs = _copy_damaged(damaged, scratch, with_log)
            try:
                con = sqlite3.connect(base, isolation_level=None)
                schema = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
                break
            except sqlite3.DatabaseError as exc:
                if con is not None:
                    con.close()
                con = None
                note = "%s (%s)" % (exc, "günlük dosyasıyla" if logs else "günlük dosyası olmadan")
        if con is None:
            raise RecoverError("Bozuk dosyanın şeması (tabloların listesi) okunamadı: %s. SQLite bu dosyadan hiçbir tabloya "
                               "ulaşamıyor; geriye en son yedek kalır." % note)
        self.con, self.logs = con, logs
        self.tables = {x[1]: x[3] for x in schema if x[0] == "table"}
        self.note = ("günlük dosyası (%s) okunamadı, onsuz okundu" % ", ".join(
            s for s in ("-wal", "-journal") if os.path.isfile(damaged + s))) if not logs and note else ""
        try:
            found = [str(x[0]) for x in con.execute("PRAGMA quick_check(5)").fetchall()]
        except sqlite3.DatabaseError as exc:
            found = [str(exc)]
        self.check = [] if found == ["ok"] else found

    def read(self, tables: Sequence[str], candidates: Callable[[str, List[str]], List[Tuple[Any, ...]]]) -> Dict[str, Any]:
        """Every table of ``tables`` the file has, read as far as SQLite can: ``{"tables": {name: Read}, "logs": the log
        files read with it, "note": ..., "check": what SQLite's check of the file says}``."""
        out: Dict[str, Read] = {}
        for name in tables:
            if name not in self.tables:
                continue
            try:
                out[name] = _Table(self.con, name, self.tables[name], candidates).run()
            except sqlite3.DatabaseError as exc:          # (its columns cannot even be read)
                rd = Read(name)
                rd.failed = "okunamadı: %s" % exc
                out[name] = rd
        return {"tables": out, "logs": self.logs, "check": self.check, "note": self.note}

    def close(self) -> None:
        self.con.close()


# ---------------------------------------------------------------------- what is written
class Result(object):
    """What one table gave back."""

    def __init__(self, rule: Rule):
        self.rule = rule
        self.read: Optional[Read] = None
        self.absent = False                          # the damaged file has no such table
        self.added: List[Dict[str, Any]] = []
        self.updated: List[Dict[str, Any]] = []
        self.same = 0
        self.kept = 0                                # in both, different, the database's kept
        self.kept_names: List[str] = []              # ... which (kv's keys, the accounts' names)
        self.renumbered = 0
        self.orphans = 0                             # their parent row is nowhere
        self.kv: List[str] = []                      # KV_MERGE entries taken (their names)
        self.lost_known: Optional[Dict[str, int]] = None   # the unreadable rows the indexes name: in the database / lost


def _later(a: Any, b: Any) -> bool:
    """Whether time ``a`` is after ``b`` (``None``: before any)."""
    if a is None:
        return False
    if b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a > b
    return str(a) > str(b)


def _checker(spec: Dict[str, Tuple[str, bool]], rule: Rule) -> Callable[[Dict[str, Any]], bool]:
    """Whether a row read holds what its columns hold (the database's own declarations: ``spec`` column -> (affinity,
    NOT NULL))."""
    def ok(row: Dict[str, Any]) -> bool:
        for col, v in row.items():
            if col not in spec:
                continue
            aff, notnull = spec[col]
            if v is None:
                if notnull:
                    return False
                continue
            t = type(v)
            if (aff == "INTEGER" and t is not int) or (aff == "REAL" and t not in (int, float)) or (aff == "TEXT" and t is not str):
                return False
            if col in rule.json:
                try:
                    json.loads(v)
                except (TypeError, ValueError):
                    return False
            if col in DATE_COLS and not _DATE.match(v if t is str else ""):
                return False
        return True
    return ok


def merge(db: sqlite3.Connection, reads: Dict[str, Read], rules: Sequence[Rule] = RULES) -> List[Result]:
    """Add the rows read to the database ``db`` (inside the caller's transaction), table by table (the module's text)."""
    results: List[Result] = []
    remaps: Dict[str, Dict[Any, Any]] = {}
    ids_now: Dict[str, Set[Any]] = {}
    for rule in rules:
        res = Result(rule)
        results.append(res)
        rd = reads.get(rule.table)
        if rd is None:
            res.absent = True
            continue
        res.read = rd
        info = db.execute("PRAGMA table_info(%s)" % _q(rule.table)).fetchall()
        spec = {i[1]: (_affinity(i[2]), bool(i[3]) or bool(i[5])) for i in info}      # (NOT NULL, or the key)
        cols = [c for c in rd.columns if c in spec]
        ok = _checker(spec, rule)
        good = []
        for row in rd.rows:
            row = {c: row[c] for c in cols}
            if ok(row):
                good.append(row)
            else:
                rd.bad.append(row)
        if rule.parent:
            col, table = rule.parent
            moved, there = remaps.get(table, {}), ids_now.get(table)
            if there is None:                        # (the parent table was not in the damaged file: the database's)
                there = ids_now[table] = {r[0] for r in db.execute("SELECT id FROM %s" % _q(table))}
            kept = []
            for row in good:
                row[col] = moved.get(row[col], row[col])
                if there is not None and row[col] not in there:
                    res.orphans += 1
                    continue
                kept.append(row)
            good = kept
        if rule.key is None:
            _merge_numbered(db, rule, cols, good, res, remaps.setdefault(rule.table, {}), ids_now)
        else:
            _merge_keyed(db, rule, cols, good, res)
        _lost(db, rule, rd, res)
    return results


def _decide(rule: Rule, cur: Dict[str, Any], row: Dict[str, Any], cols: List[str], fixed: Sequence[str]
            ) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """What to do with a row both have: ("update", the columns to set, a KV_MERGE name) / ("same" | "kept", None, None)."""
    if rule.table == "kv" and cur.get("key") in KV_MERGE:
        fn, _ = KV_MERGE[cur["key"]]
        try:
            mine, theirs = json.loads(cur["value"]), json.loads(row["value"])
        except (TypeError, ValueError):
            return "kept", None, None
        merged = fn(mine, theirs)
        if merged != mine:
            return "update", {"value": json.dumps(merged, ensure_ascii=False)}, cur["key"]
        return ("same" if theirs == mine else "kept"), None, None
    if rule.newer and rule.newer in cols and _later(row.get(rule.newer), cur.get(rule.newer)):
        return "update", {c: row[c] for c in cols if c not in fixed and row[c] != cur.get(c)}, None
    flags = {f: row[f] for f in rule.flags if f in cols and (row[f] or 0) > (cur.get(f) or 0)}
    if flags:
        return "update", flags, None
    differs = any(row[c] != cur.get(c) for c in cols if c not in rule.ignore)
    return ("kept" if differs else "same"), None, None


def _insert(db: sqlite3.Connection, table: str, row: Dict[str, Any], cols: Sequence[str]) -> int:
    return db.execute("INSERT INTO %s (%s) VALUES (%s)" % (_q(table), ", ".join(_q(c) for c in cols),
                                                          ", ".join("?" for _ in cols)), tuple(row[c] for c in cols)).lastrowid


def _update(db: sqlite3.Connection, table: str, sets: Dict[str, Any], where: Dict[str, Any]) -> None:
    db.execute("UPDATE %s SET %s WHERE %s" % (_q(table), ", ".join("%s=?" % _q(c) for c in sets),
                                              " AND ".join("%s=?" % _q(c) for c in where)),
               tuple(sets.values()) + tuple(where.values()))


def _merge_keyed(db: sqlite3.Connection, rule: Rule, cols: List[str], rows: List[Dict[str, Any]], res: Result) -> None:
    key = [c for c in rule.key if c in cols]
    if len(key) != len(rule.key):
        res.read.failed = res.read.failed or "anahtar sütunları yok"
        return
    sel = ", ".join(_q(c) for c in cols)
    if rule.history:                                 # (big tables, only added to: their keys are enough)
        have = {tuple(r) for r in db.execute("SELECT %s FROM %s" % (", ".join(_q(c) for c in key), _q(rule.table)))}
        rows_now: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    else:
        rows_now = {}
        for r in db.execute("SELECT %s FROM %s" % (sel, _q(rule.table))):
            d = dict(zip(cols, r))
            rows_now[tuple(d[c] for c in key)] = d
        have = set(rows_now)
    groups = None
    if rule.group:
        groups = {r[0] for r in db.execute("SELECT DISTINCT %s FROM %s" % (_q(rule.group), _q(rule.table)))}
    new = []
    for row in rows:
        k = tuple(row[c] for c in key)
        if k not in have:
            if groups is not None and row[rule.group] in groups:
                res.kept += 1                        # (that day's set is in the database already: left as it is)
                continue
            new.append(row)
            have.add(k)
            res.added.append(row)
            continue
        cur = rows_now.get(k)
        if cur is None:
            res.same += 1
            continue
        what, sets, name = _decide(rule, cur, row, cols, key)
        if what == "update" and sets:
            _update(db, rule.table, sets, dict(zip(key, k)))
            res.updated.append(row)
            if name:
                res.kv.append(name)
        elif what == "kept":
            res.kept += 1
            if rule.table in ("kv", "users"):
                res.kept_names.append(str(k[0]))
        else:
            res.same += 1
    if new:
        db.executemany("INSERT INTO %s (%s) VALUES (%s)" % (_q(rule.table), sel, ", ".join("?" for _ in cols)),
                       [tuple(r[c] for c in cols) for r in new])


def _merge_numbered(db: sqlite3.Connection, rule: Rule, cols: List[str], rows: List[Dict[str, Any]], res: Result,
                    remap: Dict[Any, Any], ids_now: Dict[str, Set[Any]]) -> None:
    """A table the database numbers itself (``id``): the same row by its number and its birth (Rule)."""
    if "id" not in cols:
        res.read.failed = res.read.failed or "numara sütunu yok"
        return
    birth = [c for c in rule.birth if c in cols]
    rows_now: Dict[Any, Dict[str, Any]] = {}
    born: Dict[Tuple[Any, ...], List[Any]] = collections.defaultdict(list)
    for r in db.execute("SELECT %s FROM %s" % (", ".join(_q(c) for c in cols), _q(rule.table))):
        d = dict(zip(cols, r))
        rows_now[d["id"]] = d
        born[tuple(d[c] for c in birth)].append(d["id"])
    rest = [c for c in cols if c != "id"]
    # a new number goes above every number of both files - never one a later row of the damaged file still has - and
    # above every number the database ever gave (AUTOINCREMENT's record: a number of a row deleted since is not reused)
    try:
        given = db.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (rule.table,)).fetchone()
    except sqlite3.DatabaseError:
        given = None
    top = max([0] + list(rows_now) + [r["id"] for r in rows] + ([int(given[0])] if given and given[0] is not None else []))
    for row in sorted(rows, key=lambda r: r["id"]):
        cur = rows_now.get(row["id"])
        b = tuple(row[c] for c in birth)
        if cur is None:
            _insert(db, rule.table, row, cols)
            rows_now[row["id"]] = row
            born[b].append(row["id"])
            res.added.append(row)
        elif tuple(cur[c] for c in birth) == b:
            what, sets, _ = _decide(rule, cur, row, cols, ["id"])
            if what == "update" and sets:
                _update(db, rule.table, sets, {"id": row["id"]})
                res.updated.append(row)
            elif what == "kept":
                res.kept += 1
            else:
                res.same += 1
        else:
            # the number went to another row meanwhile: the same row under another number (an earlier recovery), or a
            # new number
            twin = next((i for i in born.get(b, ()) if all(rows_now[i].get(c) == row[c] for c in rest)), None)
            if twin is not None:
                remap[row["id"]] = twin
                res.same += 1
                continue
            top += 1
            new_id = top
            _insert(db, rule.table, dict(row, id=new_id), cols)
            remap[row["id"]] = new_id
            rows_now[new_id] = dict(row, id=new_id)
            born[b].append(new_id)
            res.added.append(row)
            res.renumbered += 1
    ids_now[rule.table] = set(rows_now)


def _lost(db: sqlite3.Connection, rule: Rule, rd: Read, res: Result) -> None:
    """Of the rows the indexes name that could not be read: how many the database has (from the backup) and how many are
    lost."""
    gone = rd.missing()
    if not gone:
        return
    key = list(rule.key) if rule.key else ["id"]
    there = lost = 0
    for k, info in gone:
        if rd.rowid and rule.key is None:
            probe = {"id": k[0]}
        elif not rd.rowid:
            probe = dict(zip(rd.keycols, k))
        else:
            probe = {c: info[c] for c in key if c in info}
        if len(probe) != len(key):
            continue
        hit = db.execute("SELECT 1 FROM %s WHERE %s" % (_q(rule.table), " AND ".join("%s=?" % _q(c) for c in probe)),
                         tuple(probe.values())).fetchone()
        if hit:
            there += 1
        else:
            lost += 1
    if there or lost:
        res.lost_known = {"there": there, "lost": lost}


# ---------------------------------------------------------------------- what is said
def _dm(day: Any) -> str:
    s = str(day or "")
    return "%s.%s" % (s[8:10], s[5:7]) if _DATE.match(s) else s


def _days(rows: Sequence[Dict[str, Any]], col: Optional[str]) -> str:
    """ " (24.11)", " (23.11: 2, 24.11: 10)" - the days the rows are about."""
    if not col or not rows:
        return ""
    n = collections.Counter(str(r.get(col))[:10] for r in rows if r.get(col))
    if not n:
        return ""
    days = sorted(n)
    if len(days) == 1:
        return " (%s)" % _dm(days[0])
    if len(days) <= 4:
        return " (%s)" % ", ".join("%s: %d" % (_dm(d), n[d]) for d in days)
    return " (%s – %s, %d gün)" % (_dm(days[0]), _dm(days[-1]), len(days))


def _brief(values: Sequence[Any], most: int = 5) -> str:
    shown = [str(v) for v in values[:most]]
    return ", ".join(shown) + (" …" if len(values) > most else "")


def came_line(res: Result, trial: bool) -> str:
    rule = res.rule
    parts = []
    if res.added:
        extra = ""
        if rule.who:
            users = {r.get(rule.who) for r in res.added + res.updated}
            extra = " (%d kullanıcı)" % len(users)
        parts.append("%d %s%s%s" % (len(res.added), rule.unit, _days(res.added, rule.day), extra))
        if res.renumbered:
            parts.append("%d tanesi yeni numarayla (şimdiki veritabanında o numarada başka bir kayıt vardı)" % res.renumbered)
    plain = len(res.updated) - len(res.kv)
    if plain:
        parts.append("%d %s %s (bozuk dosyadaki hali daha yeni)" % (plain, rule.unit,
                                                                    "güncellenecek" if trial else "güncellendi"))
    for name in res.kv:
        parts.append("%s %s" % (KV_MERGE[name][1], "alınacak" if trial else "alındı"))
    return "%s: %s" % (rule.label, " · ".join(parts))


def lost_line(res: Result) -> str:
    rule, rd = res.rule, res.read
    if rd.failed:
        text = "okunamadı (%s)" % rd.failed
    else:
        gone = rd.missing()
        bits = []
        if gone:
            n = len(gone)
            what = "%d %s okunamadı" % (n, rule.unit)
            if rule.day:
                what += _days([info for _, info in gone], rule.day)
            if rule.table in ("kv", "users"):          # (their names say what they were: a setting, an account)
                names = [info.get(rule.key[0]) for _, info in gone if info.get(rule.key[0]) is not None]
                if names:
                    what += " (%s)" % _brief(names)
            elif rule.key is None and rd.rowid:
                what += " (numara %s)" % _ranges([k[0] for k, _ in gone])
            if res.lost_known:
                what += " – şimdiki veritabanında olan: %d, kayıp: %d" % (res.lost_known["there"], res.lost_known["lost"])
            if not rd.index_whole:
                what += " (dizin de tam okunamadı: en az bu kadar)"
            bits.append(what)
        elif rd.gaps:
            bits.append("okunamayan %d bölüm var%s; kaç satır olduğu bilinmiyor" % (
                len(rd.gaps), " (%s)" % "; ".join(_gap(rd, g) for g in rd.gaps[:3])))
        if rd.bad:
            bits.append("%d satırın değerleri bozuk (alınmadı)" % len(rd.bad))
        text = " · ".join(bits)
    if rule.history:
        text += " – tarihçe olduğu için atlandı: dashboard eksik günleri kendisi çeker (yalnızca yeni günler)"
    return "%s: %s" % (rule.label, text)


def _ranges(ids: Sequence[Any], most: int = 4) -> str:
    """ "100–108, 190" - numbers as runs."""
    runs: List[List[Any]] = []
    for i in sorted(ids):
        if runs and isinstance(i, int) and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    shown = ["%s" % a if a == b else "%s–%s" % (a, b) for a, b in runs[:most]]
    return ", ".join(shown) + (" …" if len(runs) > most else "")


def _gap(rd: Read, gap: Tuple[Any, Any]) -> str:
    def k(key: Any) -> str:
        if key is None:
            return "sonuna kadar"
        return "/".join(str(x) for x in key)
    a, b = gap
    if a is None:
        return "başından %s" % ("%s öncesine" % k(b) if b else "sonuna kadar")
    return "%s sonrası – %s" % (k(a), "%s öncesi" % k(b) if b else "sonuna kadar")


def summary(results: Sequence[Result], info: Dict[str, Any], trial: bool, damaged: str, db_path: str,
            safety: Optional[str], fresh: bool) -> str:
    lines = ["%s: %s  ->  %s" % ("Kurtarma DENEMESİ (--dene: hiçbir şey yazılmadı)" if trial else "Kurtarma", damaged, db_path)]
    lines.append("Bozuk dosyaya dokunulmadı (bir kopyası okundu%s)." % (
        ", yanındaki %s dosyasıyla" % " / ".join(info["logs"]) if info.get("logs") else ""))
    if info.get("check"):
        lines.append("SQLite'ın denetimi (bozuk dosya): %s" % "; ".join(info["check"][:2]))
    if info.get("note"):
        lines.append("Not: %s." % info["note"])
    if fresh:
        lines.append("Şimdiki veritabanı yoktu: okunabilen her şey yeni bir veritabanına %s." % ("yazılacak" if trial else "yazıldı"))
    came = [r for r in results if r.read is not None and (r.added or r.updated)]
    lines.append("")
    if came:
        lines.append("Geri %s (şimdiki veritabanında olmayanlar%s):" % (
            "gelecekler" if trial else "gelenler", " eklenecek" if trial else " eklendi"))
        lines.extend("  " + came_line(r, trial) for r in came)
    else:
        lines.append("Bozuk dosyada şimdiki veritabanında olmayan, okunabilen bir kayıt yok: %s." % (
            "eklenecek bir şey yok" if trial else "hiçbir şey eklenmedi"))
    lost = [r for r in results if r.read is not None and r.read.damaged()]
    orphans = [r for r in results if r.orphans]
    if lost or orphans:
        lines.append("")
        lines.append("Okunamayanlar:")
        lines.extend("  " + lost_line(r) for r in lost)
        lines.extend("  %s: %d %s alınmadı (ait olduğu kayıt ne bozuk dosyada okunabildi ne şimdiki veritabanında var)"
                     % (r.rule.label, r.orphans, r.rule.unit) for r in orphans)
    else:
        lines.append("Bozuk dosyanın her tablosu baştan sona okundu.")
    kept = [r for r in results if r.kept]
    if kept:
        lines.append("")
        lines.append("Şimdiki hali korunanlar (bozuk dosyada farklı; satırın kendi zamanı yok ya da şimdiki daha yeni):")
        lines.extend("  %s: %d %s%s" % (r.rule.label, r.kept, r.rule.unit, " (%s)" % _brief(r.kept_names) if r.kept_names else "")
                     for r in kept)
    lines.append("")
    lines.append("Tablo tablo (okunan / okunamayan / %s / %s / aynı / farklı ama şimdiki korunan):" % (
        "eklenecek" if trial else "eklenen", "güncellenecek" if trial else "güncellenen"))
    empty = []
    for r in results:
        if r.absent:
            lines.append("  %-22s bozuk dosyada yok" % r.rule.table)
            continue
        rd = r.read
        gone = rd.missing()
        unread = (len(gone) if gone is not None else ("?" if rd.gaps else 0))
        if isinstance(unread, int):
            unread += len(rd.bad)
        if not rd.rows and not unread and not rd.failed:
            empty.append(r.rule.table)
            continue
        lines.append("  %-22s %d / %s / %d / %d / %d / %d" % (r.rule.table, len(rd.rows) - len(rd.bad),
                                                             "hepsi" if rd.failed else unread, len(r.added), len(r.updated),
                                                             r.same, r.kept))
    if empty:
        lines.append("  (bozuk dosyada boş: %s)" % ", ".join(empty))
    if safety:
        lines.append("")
        lines.append("Kurtarmadan önceki hali yanında duruyor: %s  (geri almak için, dashboard kapalıyken: python -m tto "
                     "yedekten-don \"%s\")" % (safety, safety))
    return "\n".join(lines)


# ---------------------------------------------------------------------- the command
def candidates(data_dir: str) -> List[Dict[str, Any]]:
    """The damaged files ``yedekten-don`` left in the data folder (``tto.db.onceki-<time>``), newest first."""
    out = []
    try:
        names = os.listdir(data_dir)
    except OSError:
        return []
    for name in names:
        if not KEPT.match(name):
            continue
        path = os.path.join(data_dir, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append({"name": name, "path": path, "bytes": st.st_size,
                    "at": _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "logs": [s for s in ("-wal", "-journal") if os.path.isfile(path + s)]})
    out.sort(key=lambda c: c["name"], reverse=True)
    return out


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def run(damaged: str, db_path: str, trial: bool = False) -> Dict[str, Any]:
    """Read ``damaged`` and add what the database ``db_path`` lacks (``trial``: on a copy of it - nothing written).
    The dashboard must be stopped: the caller holds the data folder's lock (``__main__.cmd_recover``).  Returns
    ``{"text": the summary, "results", "safety": the copy kept of the database before}``."""
    from .store import Store
    damaged, db_path = os.path.abspath(damaged), os.path.abspath(db_path)
    if not os.path.isfile(damaged):
        raise RecoverError("bozuk dosya yok: %s" % damaged)
    if _same_file(damaged, db_path):
        raise RecoverError("verilen dosya şimdiki veritabanının kendisi (%s): önce 'python -m tto yedekten-don' ile en son "
                           "yedeğe dönün, bozuk dosya yanında tto.db.onceki-… adıyla kalır; sonra onu verin" % db_path)
    scratch = tempfile.mkdtemp(prefix="tto-kurtar-")
    bad = None
    try:
        bad = Damaged(damaged, scratch)             # (first: a file SQLite cannot read leaves the database unopened)
        target = db_path
        fresh = not os.path.isfile(db_path)
        if trial:                                   # a copy of the database: the real one is never opened
            target = os.path.join(scratch, "simdiki.db")
            if not fresh:
                for s in ("", "-wal", "-journal"):
                    if os.path.isfile(db_path + s):
                        shutil.copyfile(db_path + s, target + s)
        try:
            store = Store(target)
        except sqlite3.DatabaseError as exc:
            raise RecoverError("şimdiki veritabanı açılamadı (%s): %s. Önce 'python -m tto yedekten-don' ile en son yedeğe "
                               "dönün." % (db_path, exc))
        safety = None
        try:
            found = store.quick_check()
            if found:
                raise RecoverError("şimdiki veritabanı da sağlam değil (%s: %s). Önce 'python -m tto yedekten-don' ile en "
                                   "son yedeğe dönün, sonra kurtarmayı yeniden çalıştırın." % (db_path, "; ".join(found[:3])))
            known = [r.table for r in RULES]
            tables = known + sorted(t for (t,) in store._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if t not in known)

            def now_keys(table: str, cols: List[str]) -> List[Tuple[Any, ...]]:
                try:
                    return [tuple(r) for r in store._db.execute("SELECT %s FROM %s" % (", ".join(_q(c) for c in cols),
                                                                                       _q(table)))]
                except sqlite3.DatabaseError:
                    return []
            info = bad.read(tables, now_keys)
            rules = list(RULES) + [_rule_for(store._db, t) for t in tables[len(known):] if t in info["tables"]]
            rules = [r for r in rules if r is not None]
            if not trial and not fresh:
                name = db_path + ".kurtarma-oncesi-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                at, n = name, 1
                while os.path.exists(at):              # (two runs in one second: never over the first one's copy)
                    n += 1
                    at = "%s-%d" % (name, n)
                safety = store.backup_to(at)["path"]
            try:
                with store.transaction() as db:
                    results = merge(db, info["tables"], rules)
            except sqlite3.DatabaseError as exc:      # (rolled back: nothing of it was written)
                raise RecoverError("kurtarma yazılamadı, hiçbir şey değişmedi: %s: %s" % (type(exc).__name__, exc))
        except BaseException:
            if safety:
                try:
                    os.remove(safety)                # (the database is as it was: no copy needed)
                except OSError:
                    pass
            raise
        finally:
            store.close()
        if safety and not any(r.added or r.updated for r in results):
            try:
                os.remove(safety)                    # (nothing changed: no copy needed)
            except OSError:
                pass
            safety = None
        text = summary(results, info, trial, damaged, db_path, safety, fresh)
        if not trial:
            log.info("kurtarma:\n%s", text)
        return {"text": text, "results": results, "safety": safety, "check": info.get("check")}
    finally:
        if bad is not None:
            bad.close()
        shutil.rmtree(scratch, ignore_errors=True)


def _rule_for(db: sqlite3.Connection, table: str) -> Optional[Rule]:
    """A table RULES does not know (a later version's): rows added by its primary key, none changed; none without one."""
    pk = [i[1] for i in sorted((i for i in db.execute("PRAGMA table_info(%s)" % _q(table)).fetchall() if i[5]),
                               key=lambda i: i[5])]
    return Rule(table, table, key=tuple(pk)) if pk else None
