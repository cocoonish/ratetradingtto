"""What belongs to a meeting row: one registry for the desk's two meeting calendars, and the one way a list changes.

**TCMB** - the MPC list of the TRY workbook, ``OIS_MAIN!P10:P89`` (80 rows; Ayarlar → Toplantı takvimi, the OIS page, the
roll when a meeting has passed: history.py).  **Fed** - the FOMC list of the USD workbook, ``SOFR_FOMC!B74:B83`` (10 rows;
the USD · FOMC page).  A row of a list is a *slot*: "MPC3" is the third meeting ahead, whichever meeting that is.  What
belongs to the meeting in a slot is registered here, cell by cell, in four kinds:

* ``key`` - the meeting's date.  The list changes through it only; a formula is refused there.
* ``typed`` - what is typed per meeting: TCMB's scenario steps ``U:W`` and Motor's prior mean and start step of the slot
  (``Motor!D4311:D4390``, ``A4481:A4560``), and the rate / MPC spread typed on the OIS page to read the PPK step it
  prices (``EK_PPK!G``, ``S`` - from row 3: the row of the meeting that starts the row's window); Fed's decision flag,
  WIRP and scenario steps (``C``, ``P``, ``R:T``) and the window OIS rate typed to read the FOMC step (``AB``).
  Every user's value, the desk's and the saved scenarios' go with the meeting; a reference to the cell
  (``=OIS_MAIN!U12+25``) follows it; no formula is typed there.
* ``label`` - the desk's name of a meeting (``OIS_MAIN!O``): as ``typed`` - but the file's own names are the slots'
  ("MPC3") and stay with them.
* ``computed`` - a formula of the slot (implied step, path …).  A value typed over it ("Elle değer") goes with the
  meeting; a reference to it stays on the slot (a formula reading ``OIS_MAIN!R10`` reads the next meeting's implied
  step, whichever meeting that is - as in Excel, where these are formulas of their row).

:func:`change` is the one way a list changes: every value of a meeting moves with it, in one transaction.  A meeting
that leaves the list loses nothing: what was typed for it is *set aside* under its date (``calendar.parked``) and comes
back if the date comes back; set aside values go some weeks after the meeting's day.  Formulas (inputs', calc sheets',
watch expressions') that name a moved cell follow it; one naming a meeting that left reads ``#REF!``, as in Excel when
its row is deleted.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .xl.model import COLS
from .xl.tokenizer import FormulaSyntaxError, col_to_index, index_to_col, split_cell, tokenize_a1

KEY, TYPED, LABEL, COMPUTED = "key", "typed", "label", "computed"
#: the kinds a reference follows and that take no formula (their value goes with the meeting)
FOLLOW = (KEY, TYPED, LABEL)
#: where the values of meetings that left a list wait for them: {calendar: {date: record}}
PARK_KEY = "calendar.parked"
#: a set aside meeting's values go this many days after its date (a meeting rolled into the archive by mistake has
#: time to come back)
PARK_DAYS = 30
_MISSING = object()


class Band(object):
    """Cells of the slots of a list: these columns of one sheet, row ``first + k`` for the k-th slot."""

    __slots__ = ("sheet", "first", "cols", "kind", "file_moves")

    def __init__(self, sheet: str, first: int, cols: Sequence[str], kind: str, file_moves: bool = False):
        self.sheet = sheet
        self.first = first
        self.cols = tuple(cols)
        self.kind = kind
        # the file's own values are a meeting's too (the steps the workbook was saved with); else they are the slot's
        # (the names MPC1 … MPC80, a flag every row has) and stay
        self.file_moves = file_moves


class Calendar(object):
    """One list of meetings: its book, its date column and every band of cells that belongs to a slot."""

    def __init__(self, cid: str, name: str, book: str, sheet: str, rows: Tuple[int, int], key: str,
                 bands: Sequence[Band], header: int, where: str):
        self.id = cid
        self.name = name                # how the desk calls its meetings ("PPK", "FOMC")
        self.book = book
        self.sheet = sheet
        self.first, self.last = rows
        self.slots = self.last - self.first + 1
        self.key = key                  # the date column
        self.bands = (Band(sheet, self.first, (key,), KEY),) + tuple(bands)
        self.header = header            # the row of the table's captions
        self.where = where              # where the list is edited (said when something is refused)

    def band_at(self, sheet: str, row: int, col: str) -> Optional[Tuple[Band, int]]:
        """(band, slot) of a cell, or None."""
        for b in self.bands:
            if b.sheet == sheet and col in b.cols and b.first <= row < b.first + self.slots:
                return b, row - b.first
        return None

    def columns(self) -> List[str]:
        """The columns of the list's own table (its sheet), in order."""
        cols = [c for b in self.bands if b.sheet == self.sheet for c in b.cols]
        return sorted(cols, key=col_to_index)

    def band_of(self, colkey: str) -> Optional[Tuple[Band, str]]:
        """A column as a set aside record names it (``"OIS_MAIN!U"``) -> (band, column)."""
        sheet, _, col = colkey.rpartition("!")
        for b in self.bands:
            if b.sheet == sheet and col in b.cols and b.kind != KEY:
                return b, col
        return None


TCMB = Calendar("tcmb", "PPK", "tto", "OIS_MAIN", (10, 89), "P", (
    Band("OIS_MAIN", 10, ("O",), LABEL),
    Band("OIS_MAIN", 10, ("U", "V", "W"), TYPED, file_moves=True),
    Band("OIS_MAIN", 10, ("N", "Q", "R", "S", "T", "X", "Y", "Z", "BM", "BN", "BO"), COMPUTED),
    Band("Motor", 4311, ("D",), TYPED),                   # Öncel μ of PPK sıra 1-80 (Motor!H4311:H4390)
    Band("Motor", 4481, ("A",), TYPED),                   # the solver's start step of the same slots
    # the way back of 'MPC OIS' / 'MPC SPREAD' (extras.PPK_SHEET, from row extras.PPK_FIRST): a window's rate and a pair's
    # spread typed on the row of the meeting that starts the row's (first) window, and what they give
    Band("EK_PPK", 3, ("G", "S"), TYPED),
    Band("EK_PPK", 3, tuple("ABCDEFHIJKLM") + tuple("PQRTUVW"), COMPUTED),
), header=8, where="Ayarlar → Toplantı takvimi")
FED = Calendar("fed", "FOMC", "sofr", "SOFR_FOMC", (74, 83), "B", (
    Band("SOFR_FOMC", 74, ("C", "P", "R", "S", "T"), TYPED),
    Band("SOFR_FOMC", 74, tuple("DEFGHIJKLMNO") + ("Q",) + tuple("UVWXYZ"), COMPUTED),
    # the way back of a window's OIS rate (extras.FOMC_BACK_NAME): typed per meeting, and what it gives
    Band("SOFR_FOMC", 74, ("AB",), TYPED),
    Band("SOFR_FOMC", 74, ("AA", "AC", "AD", "AE"), COMPUTED),
), header=73, where="USD · FOMC sayfası")
CALENDARS = (TCMB, FED)
BY_ID = {c.id: c for c in CALENDARS}


# ---------------------------------------------------------------------------------------------- cells
def place(book, si: int, rc: int) -> Optional[Tuple[Calendar, Band, int, str]]:
    """(calendar, band, slot, column) of a cell of a workbook, or None when it belongs to no meeting row."""
    for cal in CALENDARS:
        if book.id != cal.book:
            continue
        sheet = book.model.sheets[si].name
        r, c = divmod(rc, COLS)
        hit = cal.band_at(sheet, r, index_to_col(c))
        if hit is not None:
            return cal, hit[0], hit[1], index_to_col(c)
    return None


def key_of(book, si: int, rc: int) -> Optional[Calendar]:
    """The calendar whose meeting date the cell is, or None."""
    hit = place(book, si, rc)
    return hit[0] if hit is not None and hit[1].kind == KEY else None


def follows(book, si: int, rc: int) -> bool:
    """A cell whose value goes with its meeting and whose references follow it (date, what is typed per meeting, the
    desk's label): it takes no formula."""
    hit = place(book, si, rc)
    return hit is not None and hit[1].kind in FOLLOW


def slot_dates(book, cal: Calendar, calc=None) -> List[Optional[str]]:
    """The list as its rows hold it now, as everybody sees it: ISO date or None per slot (engine thread)."""
    from .xl.values import serial_to_date
    calc = calc or book.engine.shared
    si = book.model.sheet_index[cal.sheet]
    c = col_to_index(cal.key)
    out: List[Optional[str]] = []
    for k in range(cal.slots):
        v = calc.get(si, cal.first + k, c)
        out.append(serial_to_date(v).isoformat() if type(v) is float and 20000 < v < 80000 else None)
    return out


# ---------------------------------------------------------------------------------------------- references
REF = "#REF!"


def _sheet_of(token: str) -> Tuple[str, str]:
    """A formula's sheet prefix (``OIS_MAIN!``, ``'[sofr]SOFR_FOMC'!``) -> (book, folded sheet)."""
    from .calc import _fold, _split_book
    name = token[:-1]
    if name.startswith("'"):
        name = name[1:-1].replace("''", "'")
    bk, sheet = _split_book(name)
    return bk, _fold(sheet.strip())


def ref_moves(cal: Calendar, slot_to: Dict[int, Optional[int]], present: Sequence[str]) -> Dict[Tuple[str, str, int, int], Optional[int]]:
    """``(book, folded sheet, row, column)`` of every cell whose references follow its meeting and moved -> its new row
    (None: the meeting left the list)."""
    from .calc import _fold
    out: Dict[Tuple[str, str, int, int], Optional[int]] = {}
    for b in cal.bands:
        if b.kind not in FOLLOW or b.sheet not in present:
            continue
        for k, j in slot_to.items():
            if j == k:
                continue
            for col in b.cols:
                out[(cal.book, _fold(b.sheet), b.first + k, col_to_index(col))] = None if j is None else b.first + j
    return out


def _cell_text(cabs: bool, c: int, rabs: bool, r: int) -> str:
    return ("$" if cabs else "") + index_to_col(c) + ("$" if rabs else "") + str(r)


def rewrite_formula(text: str, home: Optional[Tuple[str, str]], moves: Dict[Tuple[str, str, int, int], Optional[int]]) -> Optional[str]:
    """``text`` with its references to moved meeting cells following them (``home``: (book, folded sheet) a reference
    without a sheet is on, None for a calc sheet's own cells) - None when nothing in it moved.  A reference to a meeting
    that left the list is ``#REF!``; a range over several meeting rows stays (it means slots: MPC1–MPC5), one inside a
    meeting's row moves with it.  The text comes back as the engine reads it (``;`` → ``,``)."""
    if not moves or not isinstance(text, str) or not text.startswith("="):
        return None
    from .calc import normalise
    try:
        toks = tokenize_a1(normalise(text))
    except (FormulaSyntaxError, ValueError):
        return None
    out: List[str] = []
    changed = False
    i, n = 0, len(toks)
    while i < n:
        kind, t = toks[i]
        sheet_tok = None
        j = i
        if kind == "sheet" and i + 1 < n and toks[i + 1][0] == "cell":
            sheet_tok, j = t, i + 1
            kind, t = toks[j]
        if kind != "cell":
            out.append(t)
            i += 1
            continue
        where = _sheet_of(sheet_tok) if sheet_tok is not None else home
        end = None                                     # the second corner of a range (A1:B2, A1:Sheet!B2)
        if j + 2 < n and toks[j + 1] == ("op", ":"):
            if toks[j + 2][0] == "cell":
                end = (j + 2, None)
            elif toks[j + 2][0] == "sheet" and j + 3 < n and toks[j + 3][0] == "cell":
                end = (j + 3, toks[j + 2][1])
        try:
            a = split_cell(t)
            b = split_cell(toks[end[0]][1]) if end is not None else None
        except FormulaSyntaxError:
            a = b = None
        if a is None or where is None:
            last = end[0] if end is not None else j
            out.extend(x[1] for x in toks[i:last + 1])
            i = last + 1
            continue
        if end is None:
            key = (where[0], where[1], a[3], a[1])
            if key in moves:
                changed = True
                to = moves[key]
                out.append(REF if to is None else (sheet_tok or "") + _cell_text(a[0], a[1], a[2], to))
            else:
                out.append((sheet_tok or "") + t)
            i = j + 1
            continue
        k1, k2 = (where[0], where[1], a[3], a[1]), (where[0], where[1], b[3], b[1])
        if a[3] == b[3] and k1 in moves and k2 in moves and moves[k1] == moves[k2]:
            changed = True
            to = moves[k1]
            if to is None:
                out.append(REF)
            else:
                out.append((sheet_tok or "") + _cell_text(a[0], a[1], a[2], to) + ":" + (end[1] or "")
                           + _cell_text(b[0], b[1], b[2], to))
        else:
            out.extend(x[1] for x in toks[i:end[0] + 1])
        i = end[0] + 1
    return "=" + "".join(out) if changed else None


_EXPR_REF = re.compile(r"('(?:[^']|'')+'|[A-Za-z_][\w.]*)!(\$?[A-Za-z]{1,3}\$?\d+)")


def rewrite_expr(text: str, moves: Dict[Tuple[str, str, int, int], Optional[int]]) -> Optional[str]:
    """A watch expression's cell references (``OIS_MAIN!U12``: the TRY workbook's) following their meeting - None when
    nothing in it moved; one naming a meeting that left reads ``#REF!`` (the expression then says it cannot be read)."""
    from .calc import _fold
    if not moves or not isinstance(text, str):
        return None
    changed = [False]

    def one(m: "re.Match") -> str:
        sheet = m.group(1)
        if sheet.startswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
        try:
            cabs, c, rabs, r = split_cell(m.group(2))
        except FormulaSyntaxError:
            return m.group(0)
        key = ("tto", _fold(sheet.strip()), r, c)
        if key not in moves:
            return m.group(0)
        changed[0] = True
        to = moves[key]
        return REF if to is None else m.group(1) + "!" + _cell_text(cabs, c, rabs, to)

    out = []
    pos = 0
    for m in re.finditer(r"\[[^\]]*\]", text):               # (names in brackets are never references)
        out.append(_EXPR_REF.sub(one, text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_EXPR_REF.sub(one, text[pos:]))
    return "".join(out) if changed[0] else None


# ---------------------------------------------------------------------------------------------- set aside
def parked(store) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """``{calendar: {date: record}}`` - the values of meetings that left a list, waiting for them."""
    v = store.get(PARK_KEY)
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    if isinstance(v, dict):
        for cid, recs in v.items():
            if cid in BY_ID and isinstance(recs, dict):
                out[cid] = {d: r for d, r in recs.items() if isinstance(r, dict) and isinstance(d, str)}
    return out


def _record_count(rec: Dict[str, Any]) -> Tuple[int, int, int]:
    """(personal values, users, values in saved scenarios) of a set aside record."""
    users = rec.get("user") or {}
    cells = sum(len(v) for v in users.values() if isinstance(v, dict))
    scen = sum(len(x) for s in (rec.get("scenarios") or {}).values() if isinstance(s, dict)
               for x in s.values() if isinstance(x, dict))
    return cells + len(rec.get("shared") or {}), len(users), scen


def tr_day(iso: str) -> str:
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[:4])


def note(res: Dict[str, Any]) -> str:
    """What a change did, in the desk's words (the answer's ``note``; the pages' toasts show it)."""
    bits = []
    p = res.get("parked") or {}
    if p.get("meetings"):
        days = ", ".join(tr_day(d) for d in p["meetings"][:4]) + (" …" if len(p["meetings"]) > 4 else "")
        what = []
        if p.get("cells"):
            what.append("%d değer (%d kullanıcı)" % (p["cells"], p.get("users", 0)))
        if p.get("scenario_cells"):
            what.append("kayıtlı senaryolarda %d değer" % p["scenario_cells"])
        bits.append("%d toplantı listeden çıktı (%s)%s" % (len(p["meetings"]), days,
                    (": " + " ve ".join(what) + " kenara alındı - tarih geri eklenirse geri gelir") if what else ""))
    r = res.get("restored") or {}
    if r.get("meetings"):
        bits.append("%s listeye geri geldi: kenara alınan %d değer yerine kondu"
                    % (", ".join(tr_day(d) for d in r["meetings"]), r.get("cells", 0) + r.get("scenario_cells", 0)))
    if res.get("moved") or res.get("scenarios"):
        bits.append("toplantısıyla taşınan: %d değer, %d kayıtlı senaryo" % (res.get("moved", 0), res.get("scenarios", 0)))
    f = res.get("formulas") or {}
    if f.get("moved"):
        bits.append("%d formülün başvurusu toplantısıyla taşındı" % f["moved"])
    if f.get("broken"):
        bits.append("%d formül listeden çıkan toplantıya başvuruyordu: #REF!" % f["broken"])
    return " · ".join(bits)


# ---------------------------------------------------------------------------------------------- the change
def _today(book) -> str:
    from .xl.values import serial_to_date
    try:
        return serial_to_date(book.engine.clock.today()).isoformat()
    except Exception:  # noqa: BLE001
        return _dt.date.today().isoformat()


def change(svc, cal: Calendar, old_slots: Sequence[Optional[str]], new_dates: Sequence[str], user: str,
           extra: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """The list of ``cal`` goes from ``old_slots`` (ISO date or None per slot, as its rows hold it now) to ``new_dates``
    (ascending, packed from the first slot) - engine thread.  Meetings are paired by date (a corrected date is the same
    meeting: history.align_meetings).  Everything of a meeting moves with it, for every user, in one transaction with
    ``extra(store)`` (the TCMB archive): personal and desk values of its cells, "Elle değer", saved scenarios, the
    references to its cells in input formulas, scenarios, calc sheets and watch expressions, the watch's items, alarms
    and closes of it.  A meeting that left is set aside; a date that comes back gets its values back.  Returns what
    happened (``moved``, ``dropped``, ``scenarios``, ``parked``, ``restored``, ``formulas``, ``changed``, ``note``) and,
    for the writer of the dates (service._set_inputs), ``slot_to``: old slot -> new slot."""
    from .history import align_meetings
    from .service import ServiceError, _from_json, _same_value, _to_json
    from .store import now_iso
    from .xl.values import date_to_serial
    book = svc.books.get(cal.book)
    if book is None:
        raise ServiceError("%s listesinin çalışma kitabı yüklü değil" % cal.name, 500)
    store = svc.store
    engine = book.engine
    index = book.model.sheet_index
    present = [b.sheet for b in cal.bands if b.sheet in index]
    bands = [b for b in cal.bands if b.sheet in index]
    values = [b for b in bands if b.kind != KEY]
    new_dates = list(new_dates)
    if len(new_dates) > cal.slots:
        raise ServiceError("%s listesinde en fazla %d toplantı olabilir (%d verildi)" % (cal.name, cal.slots, len(new_dates)))

    # ---- which meeting goes where
    meeting_of: Dict[int, str] = {}
    slot_to: Dict[int, Optional[int]] = {}
    for d, k in sorted((d, k) for k, d in enumerate(old_slots) if d):
        if d in meeting_of.values():
            slot_to[k] = None                   # (a date in two rows of an earlier list: one meeting, the other row goes)
            continue
        meeting_of[k] = d
    order = sorted(meeting_of, key=lambda k: meeting_of[k])
    al = align_meetings([meeting_of[k] for k in order], new_dates)
    for i, k in enumerate(order):
        slot_to[k] = al[i]
    used = max([k for k, d in enumerate(old_slots) if d] + [-1]) + 1
    span = max(used, len(new_dates))
    for k in range(min(span, len(new_dates))):
        slot_to.setdefault(k, None)             # an empty row a meeting comes to: what was typed there goes
    source = {j: k for k, j in slot_to.items() if j is not None}
    removed = [(k, meeting_of[k]) for k in order if slot_to[k] is None]
    added = [(j, new_dates[j]) for j in range(len(new_dates)) if j not in source]
    corrected = {meeting_of[k]: new_dates[j] for k, j in slot_to.items()
                 if j is not None and k in meeting_of and new_dates[j] != meeting_of[k]}
    moving = {k: j for k, j in slot_to.items() if j != k}

    def ref(b: Band, col: str, k: int) -> str:
        return "%s!%s%d" % (b.sheet, col, b.first + k)

    ts = now_iso()
    today = _today(book)
    kept = parked(store)
    mine = dict(kept.get(cal.id) or {})
    park: Dict[str, Dict[str, Any]] = {d: {"at": ts, "by": user, "user": {}, "shared": {}, "scenarios": {}} for _, d in removed}
    back = {j: mine[d] for j, d in added if d in mine}

    # ---- every user's own values (typed per meeting, "Elle değer") and the saved scenarios
    mapping: Dict[str, Optional[str]] = {}
    where: Dict[str, Tuple[Band, str, int]] = {}
    for k, j in moving.items():
        for b in values:
            for col in b.cols:
                a = ref(b, col, k)
                mapping[a] = None if j is None else ref(b, col, j)
                where[a] = (b, col, k)
    rows = store.input_rows(cal.book, list(mapping)) if mapping else []
    puts: List[Tuple[str, str, Any]] = []
    moved = dropped = 0
    for r in rows:
        to = mapping[r["cell"]]
        b, col, k = where[r["cell"]]
        if to is not None:
            puts.append((r["user"], to, r["value"]))
            moved += 1
        elif k in meeting_of:
            park[meeting_of[k]]["user"].setdefault(r["user"], {})[b.sheet + "!" + col] = r["value"]
        else:
            dropped += 1                         # (typed on a row without a meeting, or a date twice)
    restored_users: Set[str] = set()
    for j, rec in back.items():
        for u, vals in (rec.get("user") or {}).items():
            for colkey, v in (vals or {}).items():
                hit = cal.band_of(colkey)
                if hit is not None and hit[0].sheet in index:
                    puts.append((u, ref(hit[0], hit[1], j), v))
                    restored_users.add(u)

    # ---- the references that follow their meeting: input formulas, scenarios' formulas, calc sheets, the watch
    moves = ref_moves(cal, slot_to, present)
    from .calc import _fold
    fx_moved = fx_broken = 0

    def rewritten(text: str, home: Optional[Tuple[str, str]]) -> Optional[str]:
        nonlocal fx_moved, fx_broken
        new = rewrite_formula(text, home, moves)
        if new is not None:
            if REF in new and REF not in text:
                fx_broken += 1
            else:
                fx_moved += 1
        return new

    def home_of(bk: str, a: str) -> Tuple[str, str]:
        return bk, _fold(a.rpartition("!")[0].strip("'"))

    formula_puts: List[Tuple[Optional[str], str, str, str]] = []
    for u, bk, a, text in (store.formula_rows() if moves else []):
        if bk == cal.book and a in mapping:
            continue                             # (in a cell that moved: it goes as a value, as before)
        new = rewritten(text, home_of(bk, a))
        if new is not None:
            formula_puts.append((u, bk, a, new))

    scenario_puts: List[Tuple[int, List[List[Any]]]] = []
    scenarios_touched = 0
    scen_parked = scen_restored = 0
    for s in store.scenario_rows():
        out: List[List[Any]] = []
        changed = False
        for x in s["items"]:
            if not isinstance(x, list) or len(x) < 3:
                continue
            if x[0] == cal.book and x[1] in mapping:
                to = mapping[x[1]]
                changed = changed or to != x[1] or len(x) > 3
                if to is None:
                    b, col, k = where[x[1]]
                    if k in meeting_of:
                        park[meeting_of[k]]["scenarios"].setdefault(s["user"], {}).setdefault(s["name"], {})[b.sheet + "!" + col] = x[2]
                        scen_parked += 1
                    continue
                out.append([x[0], to, x[2]])                     # (a formula never moves: none is taken in these cells)
                continue
            x = list(x)
            if len(x) > 3 and isinstance(x[3], str):
                new = rewritten(x[3], home_of(x[0], x[1]))
                if new is not None:
                    x[3] = new
                    changed = True
            out.append(x)
        for j, rec in back.items():
            for colkey, v in ((rec.get("scenarios") or {}).get(s["user"]) or {}).get(s["name"], {}).items():
                hit = cal.band_of(colkey)
                if hit is not None and hit[0].sheet in index:
                    out.append([cal.book, ref(hit[0], hit[1], j), v])
                    scen_restored += 1
                    changed = True
        if changed:
            scenarios_touched += 1
            scenario_puts.append((s["id"], out))

    # ---- the desk's values (the workbook's own steps, the desk's labels) and the dates
    sets: Dict[Tuple[int, int], Any] = {}
    clears: List[Tuple[int, int]] = []
    for b in values:
        if b.kind == COMPUTED:
            continue                             # ("Elle değer" is personal: the desk has none)
        si = index[b.sheet]
        held = engine.input_value[si]
        consts = book.model.sheets[si].consts
        for col in b.cols:
            c = col_to_index(col)
            colkey = b.sheet + "!" + col

            def rc(k: int) -> int:
                return (b.first + k) * COLS + c

            for k, d in removed:                                  # set aside: the desk's value of the meeting that left
                v = held.get(rc(k), _MISSING)
                if v is _MISSING and b.file_moves:
                    v = consts.get(rc(k), _MISSING)
                if v is not _MISSING and v is not None:
                    park[d]["shared"][colkey] = _to_json(v)
            for k in range(span):
                src = source.get(k)
                r = rc(k)
                if src is not None:
                    want = held.get(rc(src), consts.get(rc(src))) if b.file_moves else held.get(rc(src), _MISSING)
                else:
                    want = None if b.file_moves else _MISSING
                    if k in back and colkey in (back[k].get("shared") or {}):
                        want = _from_json(back[k]["shared"][colkey])
                if b.file_moves:
                    current = held[r] if r in held else consts.get(r)
                    base = consts.get(r)
                    if want == base and type(want) is type(base):
                        if r in held:
                            clears.append((si, r))
                    elif current != want or type(current) is not type(want):
                        sets[(si, r)] = want
                elif want is _MISSING:
                    if r in held:
                        clears.append((si, r))
                elif r not in held or not _same_value(held[r], want):
                    sets[(si, r)] = want
    ksi, kc = index[cal.sheet], col_to_index(cal.key)
    dates = {(ksi, (cal.first + k) * COLS + kc): float(date_to_serial(_dt.date.fromisoformat(new_dates[k]))) if k < len(new_dates)
             else None for k in range(cal.slots)}

    # ---- what was set aside, what came back
    for j, d in added:
        mine.pop(d, None)
    for d, rec in park.items():
        cells, users, scen = _record_count(rec)
        if cells or scen:
            if d in mine:                                         # (set aside before and back meanwhile: merged)
                old = mine[d]
                for part in ("user", "shared", "scenarios"):
                    merged = dict(old.get(part) or {})
                    merged.update(rec[part])
                    rec[part] = merged
            mine[d] = rec
    gone_after = (_dt.date.fromisoformat(today) - _dt.timedelta(days=PARK_DAYS)).isoformat()
    for d in [d for d in mine if d < gone_after and d not in new_dates]:
        del mine[d]
    kept[cal.id] = mine

    # ---- one transaction: all of it, or - on any error - none of it.  The calc sheets and the watch lists are read and
    #      written under their own locks (a user's save in between would be lost), taken before the store's as their own
    #      writers take them
    cs = getattr(svc, "calcsheets", None)
    watch = getattr(svc, "watch", None)
    locks = [x for x in (getattr(cs, "_lock", None), getattr(watch, "_lock", None)) if x is not None]
    for lk in locks:
        lk.acquire()
    try:
        calc_puts: Dict[str, Any] = {}
        for key, v in (store.kv_prefixed("calc.") if moves else {}).items():
            sheets = v.get("sheets") if isinstance(v, dict) else None
            if not isinstance(sheets, dict):
                continue
            new_sheets = dict(sheets)
            hit = False
            for sid, sh in sheets.items():
                cells = sh.get("cells") if isinstance(sh, dict) else None
                if not isinstance(cells, dict):
                    continue
                fresh = None
                for a, raw in cells.items():
                    if isinstance(raw, str) and raw.startswith("="):
                        new = rewritten(raw, None)          # (a reference without a sheet is the calc sheet's own)
                        if new is not None:
                            fresh = fresh or dict(cells)
                            fresh[a] = new
                if fresh is not None:
                    new_sheets[sid] = dict(sh, cells=fresh, rev=int(sh.get("rev") or 0) + 1)
                    hit = True
            if hit:
                calc_puts[key] = dict(v, sheets=new_sheets)
        wplan = watch.meetings_changed(cal.id, corrected, moves) if watch is not None else {}
        with store.transaction():
            if mapping:
                store.drop_input_cells(cal.book, list(mapping))
            if puts:
                store.put_input_rows(cal.book, puts)
            for sid, items in scenario_puts:
                store.put_scenario_items(sid, items)
            for u, bk, a, text in formula_puts:
                store.put_formula_text(u, bk, a, text)
            if clears:
                store.clear_shared_inputs(cal.book, [book.ref(*k) for k in clears])
            shared = {book.ref(*k): _to_json(v) for k, v in sets.items()}
            shared.update({book.ref(*k): v for k, v in dates.items()})
            store.set_shared_inputs(cal.book, shared, user)
            for key, v in calc_puts.items():
                store.put(key, v)
            if wplan.get("items") is not None:
                store.put("watch.items", wplan["items"])
            if wplan.get("alarms") is not None:
                store.put("watch.alarms", wplan["alarms"])
            if wplan.get("opens") is not None:
                store.put(wplan["opens"][0], wplan["opens"][1])
            store.rename_closes(wplan.get("keys") or {})
            store.put(PARK_KEY, kept)
            if extra is not None:
                extra(store)
        if cs is not None:
            for key in calc_puts:
                cs._users.pop(key[len("calc."):], None)
    finally:
        for lk in reversed(locks):
            lk.release()

    # ---- the engine: what the store holds now
    for key in list(sets) + clears + list(dates):
        if key not in book.inputs:
            book.declare(book.ref(*key), scope="shared", group="adhoc-shared")
    if clears:
        engine.clear_inputs(clears)
    changes = dict(sets)
    changes.update(dates)
    engine.set_inputs(changes)
    personal = bool(mapping or puts)
    if personal:
        for name in list(engine.users):                           # overlays are rebuilt from what is stored now
            svc._overlays.pop((name, cal.book), None)
            engine.set_user_inputs(name, svc._overlay(name, book))
        for key in [k for k in svc._overlays if k[1] == cal.book]:
            svc._overlays.pop(key, None)
    store._told("*", True)                                         # (the input formulas read again: texts that moved)
    store._told(None, bool(formula_puts) or bool(sets or clears))
    if watch is not None and wplan.get("keys"):
        watch.keys_renamed(wplan["keys"])
    if personal or formula_puts:
        svc._note_private()

    left = [d for _, d in removed]
    counted = [_record_count(park[d]) for d in left]
    res: Dict[str, Any] = {
        "moved": moved, "dropped": dropped, "scenarios": scenarios_touched,
        "changed": sum(1 for k, j in slot_to.items() if k in meeting_of and j != k),
        "parked": {"meetings": [d for d, c in zip(left, counted) if c[0] or c[2]],
                   "cells": sum(c[0] for c in counted),
                   "users": len({u for d in left for u in (park[d]["user"] or {})}),
                   "scenario_cells": scen_parked},
        "restored": {"meetings": [rec_d for j, rec_d in added if j in back], "cells": sum(_record_count(r)[0] for r in back.values()),
                     "users": len(restored_users), "scenario_cells": scen_restored},
        "formulas": {"moved": fx_moved, "broken": fx_broken},
        "slot_to": slot_to, "left": left, "corrected": corrected,
    }
    res["note"] = note(res)
    return res
